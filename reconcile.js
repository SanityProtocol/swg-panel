// reconcile.js — desired-state reconciliation for swg-panel.
//
// Inputs:
//   roster (desired) — the users.json envelope:
//     { version, users:{ "<uid>": {id,name,tag,note,...} },
//                peers:{ "<pid>": {id,user_id,pubkey,psk,
//                                  targets:[{node,iface,ip,type}], created_at} } }
//   stats  (observed) — node snapshots keyed by node:
//     { "<node>": { generated_at, interfaces:{ "<iface>":{ peers:[
//         { public_key, online, handshake_age, endpoint, allowed_ips } ] } },
//                   turn_proxies:[{connect,...}] } }
//
// A Peer is one credential deployed to one or more TARGETS, where a target is one
// (node, iface, ip). We compute a status PER TARGET and roll it up per peer, then
// per user. Status is derived every refresh, never stored:
//   online   ≥1 target online, and present on every live target
//   ready    present on every live target, none online yet
//   partial  present on some live targets, missing on others — redundancy gap
//   pending  brand new, still inside the grace window, not yet seen anywhere
//   dangling missing on every live target, past grace (the interface is GONE from the node -> Restore recreates it)
//   broken   the interface IS present but the peer's IP is outside its subnet -> the node can't add it; the
//            record is wrong, not the interface (-> Correct fixes the record; distinct from dangling)
//   unknown  every target's node is stale -> can't assert anything
// A peer with no user (user_id null) is flagged `unassigned` (rendered grey); its
// deployment status is still computed so you can see whether it is live.
// Stale nodes never count as "missing" (they're unknown, not absent), so a peer
// stays "online" while a replica is briefly unreachable.

const DEFAULTS = { graceMs: 60000, nodeStaleMs: 30000, unblockMs: 300000, restoreGraceMs: 120000 };   // unblockMs: how long "restoring" shows after an unblock before falling back to the real status. restoreGraceMs: how long a peer must stay dangling/broken before Restore/Correct is offered (not a hiccup / mid-create)

// status priority for rolling several targets/peers into one (most-alive wins). faulty (handshake up, no data)
// sits just under online; blocked (reaching but no handshake) is a fault above the plain-missing states.
// disabled/blocking rank BELOW every live state so a single per-peer block never dominates a user that still
// has healthy peers; restoring ranks with the other transitional states.
const RANK = { online: 8, faulty: 7, ready: 6, blocked: 5, partial: 4, restoring: 3, pending: 3, creating: 3, rotating: 3, dangling: 2, broken: 2, blocking: 1, disabled: 0, unknown: 1 };

// IPv4 membership: is `ip` inside `cidr`? Unknown/unparseable -> true (never false-flag "broken"). IPv6 -> true
// (skip; the "broken" check only guards IPv4 subnets). Used to tell a present-but-wrong peer (broken) from a
// gone-interface peer (dangling).
function ipInCidr(ip, cidr) {
  if (!ip || !cidr || String(cidr).indexOf("/") < 0 || String(ip).indexOf(":") >= 0) return true;
  const parts = String(cidr).split("/"); const bits = +parts[1];
  if (!(bits >= 0 && bits <= 32)) return true;
  const toInt = a => { const o = String(a).split("."); if (o.length !== 4) return null; let v = 0; for (let i = 0; i < 4; i++) { const n = +o[i]; if (!(n >= 0 && n <= 255)) return null; v = (v * 256) + n; } return v >>> 0; };
  const a = toInt(ip), b = toInt(parts[0]); if (a === null || b === null) return true;
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return ((a & mask) >>> 0) === ((b & mask) >>> 0);
}

function ipOf(hostport) {
  if (!hostport) return "";
  const s = String(hostport);
  return s[0] === "[" ? s.slice(1, s.indexOf("]")) : s.split(":")[0];
}
function portOf(hostport) {
  if (!hostport) return "";
  const s = String(hostport); const i = s.lastIndexOf(":");
  return i < 0 ? "" : s.slice(i + 1);
}

function reconcile(roster, stats, now, cfg) {
  now = now || Date.now();
  cfg = Object.assign({}, DEFAULTS, cfg || {});
  roster = roster || {};
  stats = stats || {};
  const users = roster.users || {};
  const peerStore = roster.peers || {};

  const nodeStatus = {};
  for (const node of Object.keys(stats)) {
    const gen = stats[node] && stats[node].generated_at;
    nodeStatus[node] = (gen && (now - gen * 1000) <= cfg.nodeStaleMs) ? "live" : "stale";
  }

  // observed peers, keyed node|iface|pubkey  (+ interfaces the node reports as DOWN, so we can say why)
  const observed = {}, ifDown = {};
  for (const node of Object.keys(stats)) {
    const ifaces = (stats[node] && stats[node].interfaces) || {};
    for (const iface of Object.keys(ifaces)) {
      if (ifaces[iface] && ifaces[iface].down) ifDown[node + "|" + iface] = ifaces[iface].down;
      for (const p of (ifaces[iface].peers || [])) observed[node + "|" + iface + "|" + p.public_key] = p;
    }
  }

  // turn-proxy attribution per node. A turn-proxied client reaches wg THROUGH the local proxy, so wg sees its
  // endpoint IP as the proxy's connect IP (typically 127.0.0.1) — that only says it came via SOME proxy, not
  // which. We attribute a turn-online peer to a proxy that forwards to the peer's OWN interface (proxy connect
  // port == the iface's wg listen port); several such proxies (redundancy) → pick the first, so exactly ONE
  // proxy claims the connection.
  const turnConnIps = {}, turnByPort = {}, turnSportSvc = {};   // node → {connectIP:true} · {wgPort:[svc]} · {wgSourcePort:svc}
  for (const node of Object.keys(stats)) {
    const ips = {}, byPort = {}, sportSvc = {};
    for (const tp of ((stats[node] && stats[node].turn_proxies) || [])) {
      const ip = ipOf(tp && tp.connect); if (ip) ips[ip] = true;
      const port = portOf(tp && tp.connect); if (port) (byPort[port] = byPort[port] || []).push((tp && tp.service) || "turn");
      // exact attribution: a peer whose endpoint is 127.0.0.1:<sport> came in through THIS proxy (disambiguates
      // several proxies fronting one interface). Nodes < the wg_sports change won't send these → we fall back below.
      for (const sp of ((tp && tp.wg_sports) || [])) sportSvc[String(sp)] = (tp && tp.service) || "turn";
    }
    turnConnIps[node] = ips; turnByPort[node] = byPort; turnSportSvc[node] = sportSvc;
  }

  const managed = {};
  const peers = Object.keys(peerStore).map(function (pid) {
    const p = peerStore[pid] || {};
    const pubkey = p.pubkey || "";
    const user = (p.user_id != null) ? (users[p.user_id] || null) : null;
    const createdMs = (p.created_at || 0) * 1000;
    const targetsIn = Array.isArray(p.targets) ? p.targets : [];

    const targets = targetsIn.map(function (t) {
      const key = t.node + "|" + t.iface + "|" + pubkey;
      managed[key] = true;
      const obs = observed[key] || null;
      let st;
      if (nodeStatus[t.node] !== "live") st = "unknown";
      else if (obs) {
        if (obs.online) {
          st = "online";
          // FAULTY: handshake is up but the node has received NO new bytes FROM the client for a while — the
          // tunnel is established yet inbound data isn't flowing (one-way block / DPI / broken return path).
          // Needs rx history across polls, kept by the caller in cfg.history (keyed like `observed`).
          if (cfg.history) {
            const h = cfg.history, rx = obs.rx_bytes || 0, prev = h[key];
            if (!prev) h[key] = { rx: rx, flatSince: null };
            else if (rx > prev.rx) { prev.rx = rx; prev.flatSince = null; }         // data flowing → healthy
            else { if (prev.flatSince == null) prev.flatSince = now; if (cfg.detectFaulty !== false && (now - prev.flatSince) >= (cfg.faultyMs || 45000)) st = "faulty"; }
          }
        } else if (cfg.detectBlocked !== false && obs.endpoint && obs.handshake_age == null && (now - createdMs) > cfg.graceMs) {
          // BLOCKED: wg learned the client's endpoint (it IS sending packets) but no handshake ever completed —
          // the client reaches the server but the tunnel won't come up (DPI on the handshake, MTU, wrong params).
          st = "blocked";
        } else st = "ready";
      }
      else {
        // Not observed on a LIVE node. If the interface is still present but the peer's IP is outside its
        // subnet, the node CAN'T add it — that's a record mismatch ("broken", → Correct), NOT the interface
        // being gone ("dangling", → Restore recreates it).
        const ifm = ((stats[t.node] || {}).interfaces || {})[t.iface];
        const sub = ifm && ifm.meta && ifm.meta.subnet;
        if (sub && t.ip && !ipInCidr(t.ip, sub)) st = "broken";
        else st = (now - createdMs) <= cfg.graceMs ? "creating" : "dangling";
      }
      // Per-deployment Restore/Correct ripeness. A PARTIAL peer has individually dangling/broken targets that
      // must each ripen on their own before we offer to act, so the gate is keyed per deployment (not per peer).
      // Same persistence rule as the rollup below: only a sustained problem (not a hiccup / mid-create) qualifies.
      const _tk = pid + "|" + t.node + "|" + t.iface;
      const _tprob = (st === "dangling" || st === "broken");
      if (cfg.probSince) {
        if (_tprob) { if (!cfg.probSince[_tk]) cfg.probSince[_tk] = now; }
        else if (cfg.probSince[_tk]) delete cfg.probSince[_tk];
      }
      const _tms = (cfg.probSince && cfg.probSince[_tk]) ? (now - cfg.probSince[_tk]) : 0;
      const _trip = _tms >= (cfg.restoreGraceMs || 120000);
      const epIp = (obs && obs.endpoint) ? ipOf(obs.endpoint) : "";
      const via = epIp ? ((turnConnIps[t.node] || {})[epIp] ? "turn" : "direct") : null;
      let viaTurn = null;
      if (via === "turn") {
        // Prefer the EXACT proxy: the wg endpoint's source port maps 1:1 to the proxy that opened it (node-reported).
        const eport = portOf(obs && obs.endpoint);
        const bySport = (turnSportSvc[t.node] || {})[String(eport)];
        // Fall back (old nodes without wg_sports): attribute to a proxy forwarding to THIS iface (connect port ==
        // iface listen port); if several share it we can only guess the first.
        const lp = ((((((stats[t.node] || {}).interfaces || {})[t.iface] || {}).meta) || {}).listen_port);
        const svcs = (turnByPort[t.node] || {})[String(lp)] || [];
        viaTurn = bySport || (svcs.length ? svcs[0] : null);
      }
      return { node: t.node, iface: t.iface, ip: t.ip, type: t.type,
               status: st, online: !!(obs && obs.online), observed: obs, via: via,
               viaTurn: viaTurn,   // the SPECIFIC turn-proxy service the peer came in through (one per connection)
               restorable: (st === "dangling") && _trip,   // this deployment's interface is gone long enough → offer Restore
               correctable: (st === "broken") && _trip,     // this deployment's IP is out-of-subnet long enough → offer Correct
               problemMs: _tprob ? _tms : 0,                // how long THIS deployment has been a problem (confirm-modal copy)
               down: ifDown[t.node + "|" + t.iface] || null };
    });

    const live = targets.filter(d => nodeStatus[d.node] === "live");
    const present = live.filter(d => d.observed);
    const onlineAny = targets.some(d => d.online);
    let status;
    if (p._creating) status = "creating";          // optimistic: the create POST is still in flight
    else if (targets.length === 0 || live.length === 0) status = "unknown";
    else if (present.length === 0) status = (live.length && live.every(d => d.status === "broken")) ? "broken"
                                            : ((now - createdMs) <= cfg.graceMs ? "creating" : "dangling");   // broken record vs gone interface
    else if (present.length < live.length) status = "partial";
    else { status = "ready"; present.forEach(d => { if ((RANK[d.status] || 0) > (RANK[status] || 0)) status = d.status; }); }   // all present → best of the targets' states (online/faulty/blocked/ready)

    // a key rotation in flight: the new key isn't on the wire yet — show "rotating", not dangling
    if (cfg.rotating && cfg.rotating.has(pid) && (status === "dangling" || status === "creating" || status === "unknown")) status = "rotating";

    // BLOCKED access (stored override, wins over any derived state). A peer OR any peer of a disabled user is
    // dropped from the node's desired set: "blocking" while the node still reports it (converging), "disabled"
    // once it's gone from every live target. With no live target to confirm against, stay "blocking".
    // UNBLOCK: `unblock_at` shows "restoring" until the peer is back on every live target (then the real status
    // shows through); a stale marker (past the window) is ignored so a later-offline peer reads dangling, not stuck.
    const blocked = !!(p.disabled || (user && user.disabled));
    const ublkAt = Math.max(p.unblock_at || 0, (user && user.unblock_at) || 0);   // per-peer OR whole-user unblock
    const restoring = !blocked && ublkAt && (now - ublkAt * 1000) < cfg.unblockMs && !(live.length > 0 && present.length === live.length);
    if (blocked) status = (live.length > 0 && present.length === 0) ? "disabled" : "blocking";
    else if (restoring) status = "restoring";
    // Propagate the block/restore state onto each TARGET too, so the per-target Peers grid (which shows
    // t.status) agrees with the peer-level badge instead of still reading online/ready/dangling.
    if (blocked) targets.forEach(d => { d.status = (nodeStatus[d.node] === "live" && !d.observed) ? "disabled" : "blocking"; d.restorable = d.correctable = false; d.problemMs = 0; });
    else if (restoring) targets.forEach(d => { if (!d.observed) { d.status = "restoring"; d.restorable = d.correctable = false; d.problemMs = 0; } });

    let reason = null;   // why a peer isn't healthy — surfaced on the status badge (incl. a DOWN interface)
    if (status === "dangling" || status === "partial" || status === "creating") {
      const dt = targets.find(d => d.down);
      reason = dt ? ("interface " + dt.iface + " is down — " + dt.down)
                  : (status === "dangling" ? "missing on every server"
                     : status === "partial" ? "missing on some live servers" : "created — not seen on a node yet");
    } else if (status === "blocked") {
      // name the datapath the peer's blocked interface(s) actually run (Wireguard vs AmneziaWG), so the "wrong
      // params" hint points at the right knobs; mixed / unknown → name both.
      const bt = new Set(targets.filter(d => d.status === "blocked").map(d => d.type));
      const proto = (bt.has("awg") && bt.has("wg")) ? "Wireguard or AmneziaWG" : bt.has("awg") ? "AmneziaWG" : bt.has("wg") ? "Wireguard" : "Wireguard or AmneziaWG";
      reason = "reaching the server but the handshake never completes — likely DPI / MTU / wrong " + proto + " params";
    }
    else if (status === "faulty") reason = "connected, but no inbound data is flowing — likely a one-way block / DPI on the return path";
    else if (status === "broken") reason = "the interface is up but this peer's IP is outside its subnet — the record needs correcting, not the interface";

    // Restore/Correct is a REAL-PROBLEM affordance, not a hiccup: each deployment tracks how long it has been
    // dangling/broken (per-target block above, gated by restoreGraceMs) so a just-created peer, a brief node
    // blip, or a re-provision in flight never prompts it. The peer rolls up to "any deployment ripe".
    const restorable = targets.some(d => d.restorable);
    const correctable = targets.some(d => d.correctable);
    const problemMs = targets.reduce((m, d) => Math.max(m, d.problemMs || 0), 0);

    let lastAge = null;
    targets.forEach(d => {
      if (d.observed && d.observed.handshake_age != null)
        lastAge = (lastAge == null) ? d.observed.handshake_age : Math.min(lastAge, d.observed.handshake_age);
    });

    return {
      id: pid, pubkey: pubkey, psk: p.psk || "", title: p.title || "",
      user_id: (p.user_id != null) ? p.user_id : null,
      name: user ? (user.name || "") : "", tag: user ? (user.tag || "") : "",
      unassigned: !user,
      targets: targets, created_at: p.created_at || null, modified_at: p.modified_at || null,
      status: status, reason: reason, online: onlineAny, lastHandshakeAge: lastAge,
      presentCount: present.length, liveCount: live.length,
      restorable: restorable,     // any deployment dangling long enough to be a real problem, not a hiccup → offer Restore
      correctable: correctable,   // any deployment broken long enough → offer Correct
      problemMs: problemMs,       // longest a deployment has been a problem (for the confirm modal copy)
      disabled: blocked, selfDisabled: !!p.disabled, userDisabled: !!(user && user.disabled),
    };
  });

  // roll peers up to their user
  const byUser = {};
  peers.forEach(pr => { if (pr.user_id != null) (byUser[pr.user_id] = byUser[pr.user_id] || []).push(pr); });
  const userList = Object.keys(users).map(function (uid) {
    const u = users[uid] || {};
    const mine = byUser[uid] || [];
    let status = "empty", online = false;
    mine.forEach(pr => {
      if (pr.online) online = true;
      if (status === "empty" || (RANK[pr.status] || 0) > (RANK[status] || 0)) status = pr.status;
    });
    // a disabled user with no peers still reads "disabled" (the flag, not a derived state)
    if (u.disabled && mine.length === 0) status = "disabled";
    return {
      id: uid, name: u.name || "", tag: u.tag || "", note: u.note || "", vk_link: u.vk_link || "",
      created_at: u.created_at || null, modified_at: u.modified_at || null,
      peerIds: mine.map(pr => pr.id),
      peerCount: mine.length, onlineCount: mine.filter(pr => pr.online).length,
      status: status, online: online, disabled: !!u.disabled,
    };
  });

  // peers on a node that the roster doesn't own — adoptable
  const retiring = cfg.retiring || null;   // pubkeys the panel is actively dropping (e.g. a rotated key
  const systemIfaces = cfg.systemIfaces || null;   // node|iface mesh-link interfaces (swg_*): their peers are
  const orphans = [];                       // managed via nodes.json links, not the roster — never orphans
  for (const key of Object.keys(observed)) {
    if (managed[key]) continue;
    const parts = key.split("|");
    if (nodeStatus[parts[0]] !== "live") continue;
    if (systemIfaces && systemIfaces.has(parts[0] + "|" + parts[1])) continue;
    if (retiring && retiring.has(parts[2])) continue;
    orphans.push(Object.assign({ node: parts[0], iface: parts[1], pubkey: parts[2], status: "orphan" }, observed[key]));
  }

  return { nodeStatus: nodeStatus, peers: peers, users: userList, orphans: orphans };
}

export { reconcile, DEFAULTS };
