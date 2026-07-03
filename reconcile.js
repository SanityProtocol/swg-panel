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
//   dangling missing on every live target, past grace
//   unknown  every target's node is stale -> can't assert anything
// A peer with no user (user_id null) is flagged `unassigned` (rendered grey); its
// deployment status is still computed so you can see whether it is live.
// Stale nodes never count as "missing" (they're unknown, not absent), so a peer
// stays "online" while a replica is briefly unreachable.

const DEFAULTS = { graceMs: 60000, nodeStaleMs: 30000 };

// status priority for rolling several targets/peers into one (most-alive wins). faulty (handshake up, no data)
// sits just under online; blocked (reaching but no handshake) is a fault above the plain-missing states.
const RANK = { online: 8, faulty: 7, ready: 6, blocked: 5, partial: 4, pending: 3, creating: 3, rotating: 3, dangling: 2, unknown: 1 };

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
  const turnConnIps = {}, turnByPort = {};   // node → { connectIP: true } · node → { wgPort: [service] }
  for (const node of Object.keys(stats)) {
    const ips = {}, byPort = {};
    for (const tp of ((stats[node] && stats[node].turn_proxies) || [])) {
      const ip = ipOf(tp && tp.connect); if (ip) ips[ip] = true;
      const port = portOf(tp && tp.connect); if (port) (byPort[port] = byPort[port] || []).push((tp && tp.service) || "turn");
    }
    turnConnIps[node] = ips; turnByPort[node] = byPort;
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
            else { if (prev.flatSince == null) prev.flatSince = now; if ((now - prev.flatSince) >= (cfg.faultyMs || 45000)) st = "faulty"; }
          }
        } else if (obs.endpoint && obs.handshake_age == null && (now - createdMs) > cfg.graceMs) {
          // BLOCKED: wg learned the client's endpoint (it IS sending packets) but no handshake ever completed —
          // the client reaches the server but the tunnel won't come up (DPI on the handshake, MTU, wrong params).
          st = "blocked";
        } else st = "ready";
      }
      else st = (now - createdMs) <= cfg.graceMs ? "creating" : "dangling";
      const epIp = (obs && obs.endpoint) ? ipOf(obs.endpoint) : "";
      const via = epIp ? ((turnConnIps[t.node] || {})[epIp] ? "turn" : "direct") : null;
      let viaTurn = null;
      if (via === "turn") {   // attribute to a proxy forwarding to THIS interface (connect port == iface listen port)
        const lp = ((((((stats[t.node] || {}).interfaces || {})[t.iface] || {}).meta) || {}).listen_port);
        const svcs = (turnByPort[t.node] || {})[String(lp)] || [];
        viaTurn = svcs.length ? svcs[0] : null;
      }
      return { node: t.node, iface: t.iface, ip: t.ip, type: t.type,
               status: st, online: !!(obs && obs.online), observed: obs, via: via,
               viaTurn: viaTurn,   // the SPECIFIC turn-proxy service the peer came in through (one per connection)
               down: ifDown[t.node + "|" + t.iface] || null };
    });

    const live = targets.filter(d => nodeStatus[d.node] === "live");
    const present = live.filter(d => d.observed);
    const onlineAny = targets.some(d => d.online);
    let status;
    if (p._creating) status = "creating";          // optimistic: the create POST is still in flight
    else if (targets.length === 0 || live.length === 0) status = "unknown";
    else if (present.length === 0) status = (now - createdMs) <= cfg.graceMs ? "creating" : "dangling";
    else if (present.length < live.length) status = "partial";
    else { status = "ready"; present.forEach(d => { if ((RANK[d.status] || 0) > (RANK[status] || 0)) status = d.status; }); }   // all present → best of the targets' states (online/faulty/blocked/ready)

    // a key rotation in flight: the new key isn't on the wire yet — show "rotating", not dangling
    if (cfg.rotating && cfg.rotating.has(pid) && (status === "dangling" || status === "creating" || status === "unknown")) status = "rotating";

    let reason = null;   // why a peer isn't healthy — surfaced on the status badge (incl. a DOWN interface)
    if (status === "dangling" || status === "partial" || status === "creating") {
      const dt = targets.find(d => d.down);
      reason = dt ? ("interface " + dt.iface + " is down — " + dt.down)
                  : (status === "dangling" ? "missing on every server"
                     : status === "partial" ? "missing on some live servers" : "created — not seen on a node yet");
    } else if (status === "blocked") reason = "reaching the server but the handshake never completes — likely DPI / MTU / wrong AmneziaWG params";
    else if (status === "faulty") reason = "connected, but no inbound data is flowing — likely a one-way block / DPI on the return path";

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
    return {
      id: uid, name: u.name || "", tag: u.tag || "", note: u.note || "",
      created_at: u.created_at || null, modified_at: u.modified_at || null,
      peerIds: mine.map(pr => pr.id),
      peerCount: mine.length, onlineCount: mine.filter(pr => pr.online).length,
      status: status, online: online,
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
