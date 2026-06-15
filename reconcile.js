// reconcile.js — desired-state reconciliation for swg-panel.
//
// A peer is one identity (pubkey + ip + privkey + PSK) that may be DEPLOYED to
// several nodes for redundancy. Status is derived every refresh, never stored:
//
//   roster  (desired)  — pubkey-keyed, with a list of nodes the peer lives on:
//     { "<pubkey>": { name, ip, if, type, nodes:[...], created_at, deleted_at } }
//     (a legacy single `node` field is still honoured.)
//   stats   (observed) — collector snapshots, keyed by node:
//     { "<node>": { generated_at, interfaces:{ "<iface>":{ peers:[
//         { public_key, online, handshake_age, endpoint, allowed_ips } ] } } } }
//
// For each peer we compute a per-node deployment status and roll it up:
//   online   at least one node online, and present on every live node it targets
//   ready    present on every live node, none online yet
//   partial  present on some live nodes but missing on others — redundancy gap
//   pending  brand new, still inside the grace window, not yet seen anywhere
//   dangling missing on every live node it targets, past grace
//   removing marked for deletion, still present somewhere
//   gone     marked for deletion, absent everywhere -> caller drops it
//   unknown  every node it targets is stale -> can't assert anything
// Stale nodes never count as "missing" (they're unknown, not absent), so a peer
// stays "online" while a replica is briefly unreachable.

const DEFAULTS = { graceMs: 60000, nodeStaleMs: 30000 };

function reconcile(roster, stats, now, cfg) {
  now = now || Date.now();
  cfg = Object.assign({}, DEFAULTS, cfg || {});
  roster = roster || {};
  stats = stats || {};

  const nodeStatus = {};
  for (const node of Object.keys(stats)) {
    const gen = stats[node] && stats[node].generated_at;
    nodeStatus[node] = (gen && (now - gen * 1000) <= cfg.nodeStaleMs) ? "live" : "stale";
  }

  const observed = {};
  for (const node of Object.keys(stats)) {
    const ifaces = (stats[node] && stats[node].interfaces) || {};
    for (const iface of Object.keys(ifaces)) {
      for (const p of (ifaces[iface].peers || [])) observed[node + "|" + iface + "|" + p.public_key] = p;
    }
  }

  // turn-proxy connect-IPs per node: a turn-proxied client reaches wg THROUGH the local
  // proxy, so wg sees its endpoint as the proxy's connect IP (typically 127.0.0.1).
  function ipOf(hostport) {
    if (!hostport) return "";
    const s = String(hostport);
    return s[0] === "[" ? s.slice(1, s.indexOf("]")) : s.split(":")[0];
  }
  const turnIp = {};
  for (const node of Object.keys(stats)) {
    const set = new Set();
    for (const tp of ((stats[node] && stats[node].turn_proxies) || [])) {
      const ip = ipOf(tp && tp.connect); if (ip) set.add(ip);
    }
    turnIp[node] = set;
  }

  const managed = {};
  const peers = Object.keys(roster).map(function (pubkey) {
    const e = roster[pubkey] || {};
    const iface = e.if;
    const nodes = Array.isArray(e.nodes) && e.nodes.length ? e.nodes : (e.node ? [e.node] : []);

    const deployments = nodes.map(function (node) {
      managed[node + "|" + iface + "|" + pubkey] = true;
      const obs = observed[node + "|" + iface + "|" + pubkey] || null;
      let st;
      if (nodeStatus[node] !== "live") st = "unknown";
      else if (e.deleted_at) st = obs ? "removing" : "gone";
      else if (obs) st = obs.online ? "online" : "ready";
      else st = (now - (e.created_at || 0) * 1000) <= cfg.graceMs ? "pending" : "dangling";
      // transport: how this client reached the node — through a local turn-proxy or directly
      const via = (obs && obs.endpoint) ? ((turnIp[node] && turnIp[node].has(ipOf(obs.endpoint))) ? "turn" : "direct") : null;
      return { node: node, status: st, online: !!(obs && obs.online), observed: obs, via: via };
    });

    const live = deployments.filter(d => nodeStatus[d.node] === "live");
    const present = live.filter(d => d.observed);
    const onlineAny = deployments.some(d => d.online);
    let status;
    if (e.deleted_at) {
      status = deployments.some(d => d.observed) ? "removing" : "gone";
    } else if (deployments.length === 0 || live.length === 0) {
      status = "unknown";
    } else if (present.length === 0) {
      status = (now - (e.created_at || 0) * 1000) <= cfg.graceMs ? "pending" : "dangling";
    } else if (present.length < live.length) {
      status = "partial";
    } else {
      status = onlineAny ? "online" : "ready";
    }

    let lastAge = null;
    deployments.forEach(d => {
      if (d.observed && d.observed.handshake_age != null)
        lastAge = (lastAge == null) ? d.observed.handshake_age : Math.min(lastAge, d.observed.handshake_age);
    });

    return {
      pubkey: pubkey, name: e.name || "", ip: e.ip || "", iface: iface, type: e.type || "",
      nodes: nodes, created_at: e.created_at || null, deleted_at: e.deleted_at || null,
      status: status, online: onlineAny, lastHandshakeAge: lastAge,
      presentCount: present.length, liveCount: live.length, deployments: deployments,
    };
  });

  const orphans = [];
  for (const key of Object.keys(observed)) {
    if (managed[key]) continue;
    const parts = key.split("|");
    if (nodeStatus[parts[0]] !== "live") continue;
    orphans.push(Object.assign({ node: parts[0], iface: parts[1], pubkey: parts[2], status: "orphan" }, observed[key]));
  }

  return { nodeStatus: nodeStatus, peers: peers, orphans: orphans };
}

if (typeof module !== "undefined" && module.exports) module.exports = { reconcile: reconcile, DEFAULTS: DEFAULTS };
