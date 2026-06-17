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

// status priority for rolling several targets/peers into one (most-alive wins)
const RANK = { online: 6, ready: 5, partial: 4, pending: 3, dangling: 2, unknown: 1 };

function ipOf(hostport) {
  if (!hostport) return "";
  const s = String(hostport);
  return s[0] === "[" ? s.slice(1, s.indexOf("]")) : s.split(":")[0];
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

  // observed peers, keyed node|iface|pubkey
  const observed = {};
  for (const node of Object.keys(stats)) {
    const ifaces = (stats[node] && stats[node].interfaces) || {};
    for (const iface of Object.keys(ifaces)) {
      for (const p of (ifaces[iface].peers || [])) observed[node + "|" + iface + "|" + p.public_key] = p;
    }
  }

  // turn-proxy connect-IPs per node: a turn-proxied client reaches wg THROUGH the local
  // proxy, so wg sees its endpoint as the proxy's connect IP (typically 127.0.0.1).
  const turnIp = {};
  for (const node of Object.keys(stats)) {
    const set = new Set();
    for (const tp of ((stats[node] && stats[node].turn_proxies) || [])) {
      const ip = ipOf(tp && tp.connect); if (ip) set.add(ip);
    }
    turnIp[node] = set;
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
      else if (obs) st = obs.online ? "online" : "ready";
      else st = (now - createdMs) <= cfg.graceMs ? "pending" : "dangling";
      const via = (obs && obs.endpoint)
        ? ((turnIp[t.node] && turnIp[t.node].has(ipOf(obs.endpoint))) ? "turn" : "direct") : null;
      return { node: t.node, iface: t.iface, ip: t.ip, type: t.type,
               status: st, online: !!(obs && obs.online), observed: obs, via: via };
    });

    const live = targets.filter(d => nodeStatus[d.node] === "live");
    const present = live.filter(d => d.observed);
    const onlineAny = targets.some(d => d.online);
    let status;
    if (targets.length === 0 || live.length === 0) status = "unknown";
    else if (present.length === 0) status = (now - createdMs) <= cfg.graceMs ? "pending" : "dangling";
    else if (present.length < live.length) status = "partial";
    else status = onlineAny ? "online" : "ready";

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
      targets: targets, created_at: p.created_at || null,
      status: status, online: onlineAny, lastHandshakeAge: lastAge,
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
  const orphans = [];
  for (const key of Object.keys(observed)) {
    if (managed[key]) continue;
    const parts = key.split("|");
    if (nodeStatus[parts[0]] !== "live") continue;
    orphans.push(Object.assign({ node: parts[0], iface: parts[1], pubkey: parts[2], status: "orphan" }, observed[key]));
  }

  return { nodeStatus: nodeStatus, peers: peers, users: userList, orphans: orphans };
}

export { reconcile, DEFAULTS };
