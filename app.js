/* swg-panel — single-page operator console.
   Vanilla JS, no build step (served statically behind nginx). Screens render a
   static shell into #view and return an update() that refreshes only their data
   regions, so live polling never clobbers inputs or open editors. */
'use strict';

// ───────────────────────── tiny helpers ─────────────────────────
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const b64 = u => { let s = ""; for (const x of u) s += String.fromCharCode(x); return btoa(s); };

// Mount-point prefix: when the panel is served under a subpath (e.g. /swg), <base href>
// carries it, so absolute API/stats paths must be prefixed to stay inside the mount.
const BASE = (() => { try { return new URL(document.baseURI).pathname.replace(/\/+$/, ""); } catch (_) { return ""; } })();
const url = p => BASE + p;   // p is a root-absolute path like "/api/fleet"

function ago(sec) {
  if (sec == null) return "—";
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec));
  if (d < 60) return "just now";
  if (d < 3600) return Math.floor(d / 60) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}
function seen(age) {
  if (age == null) return "—";
  if (age < 90) return age + "s";
  if (age < 5400) return Math.round(age / 60) + "m";
  if (age < 172800) return Math.round(age / 3600) + "h";
  return Math.round(age / 86400) + "d";
}
function rate(bps) {
  bps = bps || 0;
  const u = ["B", "K", "M", "G"]; let i = 0, v = bps;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + u[i] + "/s";
}

const ICON = {
  arrow: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>',
  search: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  pencil: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6 9 17l-5-5"/></svg>',
  warn: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  info: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  err: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
  plus: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
};

// ───────────────────────── api ─────────────────────────
const api = {
  async get(p) { const r = await fetch(url(p)); return r.json(); },
  async post(p, b) { const r = await fetch(url(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }); return r.json(); },
  fleet() { return this.get("/api/fleet"); },
  roster() { return this.get("/api/roster"); },
  describe(node) { return this.get("/api/describe?node=" + encodeURIComponent(node)); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  addPeer(body) { return this.post("/api/add-peer", body); },
  removePeer(body) { return this.post("/api/remove-peer", body); },
  rename(body) { return this.post("/api/rename", body); },
  adopt(body) { return this.post("/api/adopt", body); },
  account() { return this.get("/api/account"); },
  accountSave(body) { return this.post("/api/account", body); },
  copyPeer(body) { return this.post("/api/copy-peer", body); },
  config(pubkey, node) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node)); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  nodeRotate(b) { return this.post("/api/nodes/rotate", b); },
  nodeDelete(b) { return this.post("/api/nodes/delete", b); },
};

// ───────────────────────── store ─────────────────────────
const Store = {
  fleet: [], storeConfigs: false, roster: {}, stats: {}, nodes: [],
  recon: { peers: [], orphans: [], nodeStatus: {} },
  sessionConfigs: {},        // pubkey -> { node -> confText }   (built at creation, in-memory)
  recentlyCreated: {},       // pubkey -> ts (for row flash)
  subs: [],
  async init() {
    const f = await api.fleet();
    this.fleet = (f.data && f.data.nodes) || [];
    this.storeConfigs = !!(f.data && f.data.store_configs);
    await this.poll();
    setInterval(() => this.poll().catch(() => {}), 5000);
  },
  async poll() {
    const [f, r, nodes, stats] = await Promise.all([api.fleet(), api.roster(), api.nodes(), this.loadStats()]);
    if (f && f.data) { this.fleet = f.data.nodes || []; this.storeConfigs = !!f.data.store_configs; }
    this.roster = (r && r.data) || {};
    this.nodes = (nodes && nodes.data && nodes.data.nodes) || [];
    this.stats = stats;
    this.recon = reconcile(this.roster, stats, Date.now());
    this.notify();
  },
  async loadStats() {
    const out = {};
    await Promise.all(this.fleet.map(async n => {
      try { const r = await fetch(url("/wgstats/" + n.stats_file), { cache: "no-store" }); if (r.ok) out[n.name] = await r.json(); } catch (_) {}
    }));
    return out;
  },
  node(name) { return this.fleet.find(n => n.name === name); },
  nodeColor(name) { const n = this.node(name); return (n && n.color) || "#5f7569"; },
  peer(pubkey) { return this.recon.peers.find(p => p.pubkey === pubkey); },
  livePeers() { return this.recon.peers.filter(p => p.status !== "gone"); },
  subscribe(fn) { this.subs.push(fn); },
  notify() { this.subs.forEach(f => { try { f(); } catch (e) { console.error(e); } }); },
};

// ───────────────────────── crypto + config ─────────────────────────
async function genKeys() {
  const kp = await crypto.subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const pk8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", kp.privateKey));
  return { pub: b64(raw), priv: b64(pk8.slice(-32)) };
}
function genPSK() { const b = new Uint8Array(32); crypto.getRandomValues(b); return b64(b); }

const AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];
function buildConf(o) {
  const L = ["[Interface]", "PrivateKey = " + o.privkey, "Address = " + o.address];
  if (o.dns && o.dns.length) L.push("DNS = " + o.dns.join(", "));
  L.push("MTU = " + (o.mtu || 1280));
  for (const k of AWG_ORDER) if (o.awg_params && o.awg_params[k] != null) L.push(k + " = " + o.awg_params[k]);
  L.push("", "[Peer]", "PublicKey = " + o.server_pubkey);
  if (o.psk) L.push("PresharedKey = " + o.psk);
  L.push("AllowedIPs = " + (o.allowed || "0.0.0.0/0, ::/0"), "Endpoint = " + o.endpoint, "PersistentKeepalive = 25");
  return L.join("\n") + "\n";
}
function parseConf(text) {
  const priv = (text.match(/PrivateKey\s*=\s*(\S+)/) || [])[1] || null;
  const psk = (text.match(/PresharedKey\s*=\s*(\S+)/) || [])[1] || null;
  return { priv, psk };
}
function getConfig(pubkey, node) {
  const s = Store.sessionConfigs[pubkey];
  if (s && s[node]) return Promise.resolve(s[node]);
  if (Store.storeConfigs) return api.config(pubkey, node).then(r => r.ok ? r.data.config : null).catch(() => null);
  return Promise.resolve(null);
}
function qrDataURL(text, targetPx) {
  // Render to a canvas at an INTEGER module size (no fractional scaling) → crisp, scannable.
  const q = qrcode(0, "L");            // low EC = fewest modules = biggest squares for a given size
  q.addData(text); q.make();
  const n = q.getModuleCount(), quiet = 4, total = n + quiet * 2;
  const cell = Math.max(3, Math.floor((targetPx || 360) / total));
  const size = total * cell;
  const c = document.createElement("canvas"); c.width = c.height = size;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#000";
  for (let r = 0; r < n; r++)
    for (let col = 0; col < n; col++)
      if (q.isDark(r, col)) ctx.fillRect((col + quiet) * cell, (r + quiet) * cell, cell, cell);
  return c.toDataURL("image/png");
}
function qrSVG(text) {                  // name kept; now a crisp canvas-rendered image
  try { return `<img class="qrimg" alt="config QR" src="${qrDataURL(text, 360)}">`; }
  catch (e) { return '<div class="qr-fail">config too large<br>to encode as QR</div>'; }
}
function qrZoom(conf, label) {          // fullscreen overlay sized for easy camera lock-on
  let img;
  try { img = `<img class="qrimg" alt="config QR" src="${qrDataURL(conf, 700)}">`; }
  catch (e) { img = '<div class="qr-fail">config too large to encode</div>'; }
  const ov = document.createElement("div");
  ov.className = "qr-overlay";
  ov.innerHTML = `<div class="qr-overlay-inner"><div class="qr-overlay-card">${img}</div>` +
    `<div class="qr-overlay-cap">${label ? esc(label) : "Scan in WireGuard / AmneziaWG"}</div></div>`;
  ov.onclick = () => ov.remove();
  document.body.appendChild(ov);
}

// ───────────────────────── per-node throughput from stats ─────────────────────────
function nodeRate(name) {
  const snap = Store.stats[name]; let rx = 0, tx = 0;
  if (snap) for (const blk of Object.values(snap.interfaces || {}))
    for (const p of blk.peers || []) { rx += p.rx_speed || 0; tx += p.tx_speed || 0; }
  return { rx, tx };
}
function deploymentObs(pubkey, node, iface) {
  const snap = Store.stats[node]; if (!snap) return null;
  const blk = (snap.interfaces || {})[iface]; if (!blk) return null;
  return (blk.peers || []).find(p => p.public_key === pubkey) || null;
}

// ───────────────────────── toasts ─────────────────────────
function toast(msg, kind = "info", ms = 3600) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = (ICON[kind] || ICON.info) + "<span>" + esc(msg) + "</span>";
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 250); }, ms);
}

// ───────────────────────── chrome (appbar) ─────────────────────────
function updateChrome() {
  const online = Store.livePeers().filter(p => p.online).length;
  $("#kpi-online").textContent = online;
}
function setNav(tab) {
  $$("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
}

// ───────────────────────── status helpers ─────────────────────────
function badge(status) { return '<span class="badge b-' + status + '">' + status + '</span>'; }
function nodePips(peer) {
  return '<span class="pips">' + peer.deployments.map(d => {
    const col = Store.nodeColor(d.node);
    let cls = "unk";
    if (d.status === "online") cls = "on";
    else if (d.status === "ready" || d.status === "removing") cls = "present";
    else if (d.status === "dangling" || d.status === "pending") cls = "miss";
    return '<span class="pip ' + cls + '" style="--pc:' + col + '" title="' + esc(d.node + " · " + d.status) + '"></span>';
  }).join("") + '</span>';
}
const STATUS_RANK = { dangling: 0, partial: 1, pending: 2, unknown: 3, removing: 4, online: 5, ready: 6, gone: 9 };

// ═════════════════════════ SCREEN: OVERVIEW ═════════════════════════
function OverviewScreen() {
  $("#view").innerHTML = `
    <div class="screen">
      <div class="statgrid" id="ov-stats"></div>
      <div class="section-title"><h2>Fleet</h2><span class="count" id="ov-fleet-count"></span><span class="grow"></span></div>
      <div class="fleet" id="ov-fleet"></div>
      <div class="section-title"><h2>Needs attention</h2><span class="grow"></span></div>
      <div id="ov-attn"></div>
    </div>`;

  function renderStats() {
    const peers = Store.livePeers();
    const online = peers.filter(p => p.online).length;
    const redundant = peers.filter(p => p.nodes.length >= 2).length;
    const liveNodes = Store.fleet.filter(n => Store.recon.nodeStatus[n.name] === "live").length;
    let rx = 0, tx = 0; Store.fleet.forEach(n => { const r = nodeRate(n.name); rx += r.rx; tx += r.tx; });
    $("#ov-stats").innerHTML = `
      <div class="stat accent"><div class="k">${ICON.check} Online now</div><div class="v">${online}<small> / ${peers.length}</small></div><div class="sub">peers connected</div></div>
      <div class="stat"><div class="k">Throughput</div><div class="v" style="font-size:19px">↓ ${rate(rx)}</div><div class="sub">↑ ${rate(tx)} aggregate</div></div>
      <div class="stat"><div class="k">Redundancy</div><div class="v">${redundant}<small> / ${peers.length}</small></div><div class="sub">on two or more servers</div></div>
      <div class="stat"><div class="k">Fleet</div><div class="v">${liveNodes}<small> / ${Store.fleet.length}</small></div><div class="sub">servers reporting</div></div>`;
  }
  function renderFleet() {
    $("#ov-fleet-count").textContent = Store.fleet.length + " servers";
    $("#ov-fleet").innerHTML = Store.fleet.map(n => {
      const live = Store.recon.nodeStatus[n.name] === "live";
      const snap = Store.stats[n.name];
      const here = Store.recon.peers.filter(p => p.nodes.includes(n.name) && p.status !== "gone");
      const onl = here.filter(p => p.deployments.some(d => d.node === n.name && d.online)).length;
      const pct = here.length ? Math.round(onl / here.length * 100) : 0;
      const r = nodeRate(n.name);
      let sync = "no data", sc = "warn";
      if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); sync = live ? "synced " + seen(a) + " ago" : "stale · " + seen(a); sc = live ? "" : "warn"; }
      return `<a class="tile ${live ? "" : "stale"}" href="#/node/${encodeURIComponent(n.name)}">
        <span class="arrow">${ICON.arrow}</span>
        <div class="tile-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="tile-name">${esc(n.name)}</span><span class="tport">${esc(n.transport)}</span></div>
        <div class="tile-rate"><span class="down">↓ ${rate(r.rx)}</span><span class="up">↑ ${rate(r.tx)}</span></div>
        <div class="tile-peers">${onl}<i> / ${here.length} online</i></div>
        <div class="meter"><i style="width:${pct}%;--m:${n.color || "var(--online)"}"></i></div>
        <div class="tile-sync ${sc}">${sync}</div>
      </a>`;
    }).join("") || `<div class="allclear">No servers configured in fleet.json.</div>`;
  }
  function renderAttn() {
    const probs = Store.livePeers().filter(p => ["dangling", "partial", "pending", "unknown"].includes(p.status))
      .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
    const orphans = Store.recon.orphans;
    if (!probs.length && !orphans.length) {
      $("#ov-attn").innerHTML = `<div class="allclear">${ICON.check}<span>Everything's deployed and reporting. No drift across the fleet.</span></div>`;
      return;
    }
    const why = { dangling: "missing on every server", partial: "missing on some servers", pending: "just created, not seen yet", unknown: "server stale — can't confirm" };
    let html = probs.map(p => `<div class="attn-row" data-go="#/user/${encodeURIComponent(p.pubkey)}">
        ${badge(p.status)}<span class="name">${p.name ? esc(p.name) : "<span class='faint'>unnamed</span>"}</span>
        <span class="why">${why[p.status] || ""}</span><span class="grow"></span>${nodePips(p)}<span class="rowarrow">${ICON.arrow}</span></div>`).join("");
    html += orphans.map(o => `<div class="attn-row" data-go="#/node/${encodeURIComponent(o.node)}">
        ${badge("orphan")}<span class="name addr">${esc(o.pubkey.slice(0, 18))}…</span>
        <span class="why">on ${esc(o.node)}, not in roster</span><span class="grow"></span><span class="rowarrow">${ICON.arrow}</span></div>`).join("");
    $("#ov-attn").innerHTML = '<div class="attn">' + html + '</div>';
    $$("#ov-attn .attn-row").forEach(r => r.onclick = () => { location.hash = r.dataset.go; });
  }
  return function update() { renderStats(); renderFleet(); renderAttn(); };
}

// ═════════════════════════ SCREEN: NODE DETAIL ═════════════════════════
function NodeScreen(params) {
  const name = decodeURIComponent(params.node);
  const node = Store.node(name);
  if (!node) {
    $("#view").innerHTML = `<div class="screen"><div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>${esc(name)}</b></div>
      <div class="empty"><b>Unknown server</b>“${esc(name)}” isn't in the fleet.</div></div>`;
    return () => {};
  }
  $("#view").innerHTML = `
    <div class="screen">
      <div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>${esc(name)}</b></div>
      <div class="detail-head">
        <div class="title"><span class="dot" id="nd-dot"></span><h1>${esc(name)}</h1><span class="tport">${esc(node.transport)}</span></div>
        <div class="grow"></div>
        <button class="btn btn-primary" id="nd-add"><span class="plus">+</span> Add peer here</button>
      </div>
      <div class="bigdots" id="nd-summary"></div>
      <div class="section-title"><h2>Interfaces</h2></div>
      <div class="metagrid" id="nd-meta"><div class="loading"><span class="spin"></span>reading server…</div></div>
      <div class="section-title"><h2>Peers on this server</h2><span class="count" id="nd-peercount"></span></div>
      <div class="tablewrap"><table>
        <thead><tr><th>Status</th><th>Name</th><th>Address</th><th>Last handshake</th><th>Transfer ↓↑</th><th></th></tr></thead>
        <tbody id="nd-peers"></tbody></table></div>
      <div id="nd-orphan-wrap"></div>
    </div>`;
  $("#nd-add").onclick = () => openCreate({ node: name, iface: null });

  // one-time describe for interface metadata
  api.describe(name).then(r => {
    if (!r.ok) { $("#nd-meta").innerHTML = `<div class="notice warn">${ICON.warn}<span>Can't reach this server: ${esc(r.error || "describe failed")}</span></div>`; return; }
    const ifs = r.data.interfaces || {};
    $("#nd-meta").innerHTML = Object.keys(ifs).map(ifn => {
      const m = ifs[ifn];
      const awg = Object.keys(m.awg_params || {}).length ? Object.entries(m.awg_params).slice(0, 4).map(([k, v]) => k + "=" + v).join("  ") : "—";
      return `<div class="meta"><div class="k">${esc(ifn)} · server key</div><div class="v">${esc((m.public_key || "—"))}</div></div>
        <div class="meta"><div class="k">Endpoint</div><div class="v">${esc(m.endpoint || "—")}</div></div>
        <div class="meta"><div class="k">Subnet</div><div class="v">${esc(m.subnet || "—")} · port ${esc(String(m.listen_port || "—"))}</div></div>
        <div class="meta"><div class="k">AmneziaWG</div><div class="v">${esc(awg)}</div></div>`;
    }).join("") || `<div class="notice warn">${ICON.warn}<span>No managed interfaces reported.</span></div>`;
  }).catch(() => {});

  function update() {
    const live = Store.recon.nodeStatus[name] === "live";
    $("#nd-dot").className = "dot " + (live ? "live" : "stale");
    const snap = Store.stats[name];
    const here = Store.recon.peers.filter(p => p.nodes.includes(name) && p.status !== "gone");
    const onl = here.filter(p => p.deployments.some(d => d.node === name && d.online)).length;
    const r = nodeRate(name);
    let syncTxt = "no snapshot yet";
    if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); syncTxt = live ? "synced " + seen(a) + " ago" : "stale for " + seen(a); }
    $("#nd-summary").innerHTML =
      `<span class="badge b-${live ? "online" : "unknown"}">${live ? "reporting" : "stale"}</span>
       <span class="when">${onl} / ${here.length} online</span>
       <span class="when">↓ ${rate(r.rx)} &nbsp;↑ ${rate(r.tx)}</span>
       <span class="when">${syncTxt}</span>`;
    $("#nd-peercount").textContent = here.length + " peers";

    const rows = here.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
    $("#nd-peers").innerHTML = rows.length ? rows.map(p => {
      const dep = p.deployments.find(d => d.node === name) || {};
      const obs = deploymentObs(p.pubkey, name, p.iface);
      const tr = obs ? `↓ ${rate(obs.rx_speed)} ↑ ${rate(obs.tx_speed)}` : "—";
      return `<tr class="clk" data-go="#/user/${encodeURIComponent(p.pubkey)}">
        <td data-label="Status">${badge(dep.status || p.status)}</td>
        <td data-label="Name" class="c-name">${p.name ? esc(p.name) : "<span class='faint'>unnamed</span>"}</td>
        <td data-label="Address"><span class="addr">${esc(p.ip || "—")}</span></td>
        <td data-label="Last handshake"><span class="when">${seen(obs ? obs.handshake_age : null)}</span></td>
        <td data-label="Transfer"><span class="rate">${tr}</span></td>
        <td data-label=""><span class="rowarrow">${ICON.arrow}</span></td></tr>`;
    }).join("") : `<tr><td colspan="6" class="empty"><b>No peers here yet</b>Add one to this server to get started.</td></tr>`;
    $$("#nd-peers tr.clk").forEach(t => t.onclick = () => { location.hash = t.dataset.go; });

    const orphans = Store.recon.orphans.filter(o => o.node === name);
    if (orphans.length) {
      $("#nd-orphan-wrap").innerHTML = `<div class="section-title"><h2 style="color:var(--orphan)">Unmanaged on this server</h2></div>
        <div class="tablewrap"><table><tbody id="nd-orphans"></tbody></table></div>`;
      $("#nd-orphans").innerHTML = orphans.map(o => `<tr>
        <td data-label="Status">${badge("orphan")}</td>
        <td data-label="Key" class="addr">${esc(o.pubkey.slice(0, 22))}…</td>
        <td data-label="Address"><span class="addr">${esc(o.allowed_ips || "—")}</span></td>
        <td data-label="" style="text-align:right"><button class="btn btn-mini" data-adopt='${esc(JSON.stringify({ node: name, iface: o.iface, pubkey: o.pubkey, ip: o.allowed_ips }))}'>Adopt</button>
          <button class="btn btn-mini warn" data-rm='${esc(JSON.stringify({ node: name, iface: o.iface, pubkey: o.pubkey }))}'>Remove</button></td></tr>`).join("");
      bindOrphanActions("#nd-orphans");
    } else $("#nd-orphan-wrap").innerHTML = "";
  }
  return update;
}

// ═════════════════════════ SCREEN: USERS ═════════════════════════
const usersFilter = { text: "", statuses: new Set(), node: "" };
function UsersScreen() {
  $("#view").innerHTML = `
    <div class="screen">
      <div class="toolbar">
        <div class="search">${ICON.search}<input id="u-search" placeholder="Search name, address, key, server…" value="${esc(usersFilter.text)}"></div>
        <select class="selwrap" id="u-nodefilter"></select>
        <button class="btn btn-primary" id="u-add"><span class="plus">+</span> Add peer</button>
      </div>
      <div class="chips" id="u-chips" style="margin-bottom:14px"></div>
      <div class="tablewrap"><table>
        <thead><tr><th>Status</th><th>Name</th><th>Address</th><th>Servers</th><th>Last connected</th><th>Added</th><th></th></tr></thead>
        <tbody id="u-tbody"></tbody></table></div>
      <div id="u-orphan-wrap"></div>
    </div>`;
  $("#u-add").onclick = () => openCreate({});
  $("#u-nodefilter").innerHTML = `<option value="">All servers</option>` + Store.fleet.map(n => `<option value="${esc(n.name)}" ${usersFilter.node === n.name ? "selected" : ""}>${esc(n.name)}</option>`).join("");
  $("#u-search").oninput = e => { usersFilter.text = e.target.value.trim().toLowerCase(); renderTable(); };
  $("#u-nodefilter").onchange = e => { usersFilter.node = e.target.value; renderTable(); };

  function match(p) {
    if (usersFilter.statuses.size && !usersFilter.statuses.has(p.status)) return false;
    if (usersFilter.node && !p.nodes.includes(usersFilter.node)) return false;
    if (!usersFilter.text) return true;
    return (p.name + " " + p.ip + " " + p.pubkey + " " + p.nodes.join(" ")).toLowerCase().includes(usersFilter.text);
  }
  function renderChips() {
    const counts = {}; Store.livePeers().forEach(p => counts[p.status] = (counts[p.status] || 0) + 1);
    const order = ["online", "ready", "partial", "pending", "dangling", "unknown", "removing"];
    $("#u-chips").innerHTML = order.filter(s => counts[s]).map(s =>
      `<div class="chip ${usersFilter.statuses.has(s) ? "on" : ""}" data-st="${s}"><span class="badge b-${s}" style="padding:0;background:none">●</span>${s} <b>${counts[s]}</b></div>`).join("");
    $$("#u-chips .chip").forEach(c => c.onclick = () => { const s = c.dataset.st; usersFilter.statuses.has(s) ? usersFilter.statuses.delete(s) : usersFilter.statuses.add(s); renderChips(); renderTable(); });
  }
  function renderTable() {
    const all = Store.livePeers();
    const rows = all.filter(match).sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
    if (!all.length) {
      $("#u-tbody").innerHTML = `<tr><td colspan="7" class="empty"><b>No peers yet</b>Add your first peer — pick one or several servers for redundancy.</td></tr>`;
    } else if (!rows.length) {
      $("#u-tbody").innerHTML = `<tr><td colspan="7" class="empty"><b>Nothing matches</b>Clear the search or filters.</td></tr>`;
    } else {
      $("#u-tbody").innerHTML = rows.map(p => {
        const flash = Store.recentlyCreated[p.pubkey] && Date.now() - Store.recentlyCreated[p.pubkey] < 3000;
        return `<tr class="clk ${flash ? "flash" : ""}" data-go="#/user/${encodeURIComponent(p.pubkey)}">
          <td data-label="Status">${badge(p.status)}</td>
          <td data-label="Name" class="c-name">${p.name ? esc(p.name) : "<span class='faint'>unnamed</span>"}</td>
          <td data-label="Address"><span class="addr">${esc(p.ip || "—")}</span></td>
          <td data-label="Servers">${nodePips(p)}</td>
          <td data-label="Last connected"><span class="when">${seen(p.lastHandshakeAge)}</span></td>
          <td data-label="Added"><span class="when">${ago(p.created_at)}</span></td>
          <td data-label=""><span class="rowarrow">${ICON.arrow}</span></td></tr>`;
      }).join("");
      $$("#u-tbody tr.clk").forEach(t => t.onclick = () => { location.hash = t.dataset.go; });
    }
    // orphans across fleet
    const orphans = Store.recon.orphans;
    if (orphans.length) {
      $("#u-orphan-wrap").innerHTML = `<div class="section-title"><h2 style="color:var(--orphan)">Unmanaged</h2><span class="count">on a server but not tracked</span></div>
        <div class="tablewrap"><table><tbody id="u-orphans"></tbody></table></div>`;
      $("#u-orphans").innerHTML = orphans.map(o => `<tr>
        <td data-label="Status">${badge("orphan")}</td>
        <td data-label="Key" class="addr">${esc(o.pubkey.slice(0, 20))}…</td>
        <td data-label="Server" class="addr">${esc(o.node)} / ${esc(o.iface)}</td>
        <td data-label="Address"><span class="addr">${esc(o.allowed_ips || "—")}</span></td>
        <td data-label="" style="text-align:right"><button class="btn btn-mini" data-adopt='${esc(JSON.stringify({ node: o.node, iface: o.iface, pubkey: o.pubkey, ip: o.allowed_ips }))}'>Adopt</button>
          <button class="btn btn-mini warn" data-rm='${esc(JSON.stringify({ node: o.node, iface: o.iface, pubkey: o.pubkey }))}'>Remove</button></td></tr>`).join("");
      bindOrphanActions("#u-orphans");
    } else $("#u-orphan-wrap").innerHTML = "";
  }
  return function update() { renderChips(); renderTable(); };
}

// ═════════════════════════ SCREEN: USER PROFILE ═════════════════════════
function UserScreen(params) {
  const pubkey = decodeURIComponent(params.pubkey);
  const p0 = Store.peer(pubkey);
  if (!p0) {
    $("#view").innerHTML = `<div class="screen"><div class="crumb"><a href="#/users">Users</a><span class="sep">/</span><b>unknown</b></div>
      <div class="empty"><b>Peer not found</b>It may have been removed.</div></div>`;
    return () => {};
  }
  $("#view").innerHTML = `
    <div class="screen">
      <div class="crumb"><a href="#/users">Users</a><span class="sep">/</span><b id="u-crumb">${esc(p0.name || "unnamed")}</b></div>
      ${Store.storeConfigs ? `<div class="notice warn posture">${ICON.warn}<span><b>store_configs is on.</b> Client private keys are kept on the panel host so these QR codes stay viewable. Turn it off in fleet.json to keep no secrets at rest.</span></div>` : ""}
      <div class="detail-head">
        <div class="nameline" id="u-nameline"></div>
        <div class="grow"></div>
        <button class="btn btn-mini warn" id="u-remove">Remove peer</button>
      </div>
      <div class="identity" id="u-identity"></div>
      <div class="section-title"><h2>Deployed on</h2><span class="count" id="u-depcount"></span>
        <div class="grow"></div>
        <div class="copyto" id="u-copyto"></div>
      </div>
      <div class="deploys" id="u-deploys"></div>
    </div>`;

  renderNameline();
  $("#u-remove").onclick = () => removePeerFlow(pubkey, p0.nodes);
  renderCopyTo();
  buildDeploys();   // async; builds QR cards once

  function renderCopyTo() {
    const on = new Set(p0.nodes || []);
    const targets = Store.fleet.filter(n => !on.has(n.name));
    const box = $("#u-copyto");
    if (!targets.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<select class="selwrap" id="u-copysel"><option value="">Copy to server…</option>` +
      targets.map(n => `<option value="${esc(n.name)}">${esc(n.name)}</option>`).join("") + `</select>`;
    $("#u-copysel").onchange = e => { const t = e.target.value; if (t) copyToServer(t); e.target.value = ""; };
  }

  async function copyToServer(target) {
    toast("Copying to " + target + "…", "info", 2000);
    // need the client's private key — from this session's configs, or stored configs if enabled
    let src = (Store.sessionConfigs[pubkey] && Object.values(Store.sessionConfigs[pubkey])[0]) || null;
    if (!src && Store.storeConfigs && p0.nodes && p0.nodes.length) {
      const c = await api.config(pubkey, p0.nodes[0]); if (c.ok) src = c.data.config;
    }
    if (!src) { toast("Can't copy: the private key isn't available (enable store_configs, or copy right after creating).", "err", 6000); return; }
    const { priv, psk } = parseConf(src);
    const iface = p0.iface;
    const d = await api.describe(target);
    if (!d.ok) { toast("Target server unreachable: " + (d.error || ""), "err"); return; }
    const info = (d.data.interfaces || {})[iface];
    if (!info) { toast(`Server ${target} has no interface ${iface}.`, "err", 5000); return; }
    const nip = await api.nextIp([target], iface);
    if (!nip.ok) { toast("No free address on " + target + ": " + (nip.error || ""), "err"); return; }
    const ip = nip.data.next_ip;
    const conf = buildConf({ privkey: priv, address: ip, dns: info.dns, awg_params: info.awg_params,
      server_pubkey: info.public_key, psk, endpoint: info.endpoint, allowed: "0.0.0.0/0, ::/0" });
    const r = await api.copyPeer({ public_key: pubkey, to_node: target, iface, allowed_ips: ip,
      preshared_key: psk, configs: Store.storeConfigs ? { [target]: conf } : undefined });
    if (!r.ok) { toast("Copy failed: " + (r.error || r.code || "unknown"), "err"); return; }
    (Store.sessionConfigs[pubkey] = Store.sessionConfigs[pubkey] || {})[target] = conf;
    toast("Copied to " + target + " (" + ip.split("/")[0] + ").", "ok");
    await Store.poll(); refreshScreen();
  }

  function renderNameline() {
    const p = Store.peer(pubkey) || p0;
    $("#u-nameline").innerHTML = `<h1>${p.name ? esc(p.name) : "<span class='faint'>unnamed</span>"}</h1>
      ${badge(p.status)}<button class="editname" id="u-rename" title="Rename">${ICON.pencil}</button>`;
    $("#u-rename").onclick = startRename;
  }
  function startRename() {
    const p = Store.peer(pubkey) || p0;
    uiBusy = true;   // pause auto-refresh so typing isn't wiped mid-edit
    $("#u-nameline").innerHTML = `<span class="name-edit"><input id="u-rn" value="${esc(p.name)}" maxlength="64" placeholder="name"><button class="btn btn-mini" id="u-rn-save">${ICON.check}</button></span>`;
    const inp = $("#u-rn"); inp.focus(); inp.select();
    const cancel = () => { uiBusy = false; renderNameline(); };
    const save = async () => {
      const r = await api.rename({ public_key: pubkey, name: inp.value.trim() });
      if (!r.ok) { toast("Rename failed: " + (r.error || r.code || ""), "err"); return; }
      uiBusy = false;
      toast("Renamed.", "ok"); await Store.poll(); renderNameline(); $("#u-crumb").textContent = inp.value.trim() || "unnamed";
    };
    $("#u-rn-save").onclick = save;
    inp.onkeydown = e => { if (e.key === "Enter") save(); if (e.key === "Escape") cancel(); };
  }
  function renderIdentity() {
    const p = Store.peer(pubkey); if (!p) return;
    $("#u-depcount").textContent = p.nodes.length + (p.nodes.length === 1 ? " server" : " servers");
    $("#u-identity").innerHTML = `
      <div class="item"><div class="k">Address</div><div class="v">${esc(p.ip || "—")}</div></div>
      <div class="item"><div class="k">Public key</div><div class="v">${esc(p.pubkey.slice(0, 20))}… <button class="copybtn" data-copy="${esc(p.pubkey)}" title="Copy">${ICON.copy}</button></div></div>
      <div class="item"><div class="k">Type</div><div class="v">${esc(p.type || "user")}</div></div>
      <div class="item"><div class="k">Added</div><div class="v">${ago(p.created_at)}</div></div>
      <div class="item"><div class="k">Last connected</div><div class="v">${seen(p.lastHandshakeAge)}${p.lastHandshakeAge != null ? " ago" : ""}</div></div>`;
    $$("#u-identity .copybtn").forEach(b => b.onclick = () => { navigator.clipboard.writeText(b.dataset.copy); toast("Public key copied.", "ok", 1800); });
  }
  async function buildDeploys() {
    const p = Store.peer(pubkey); if (!p) return;
    const box = $("#u-deploys");
    box.innerHTML = p.nodes.map(n => `<div class="deploy" id="dep-${cssid(n)}"><div class="loading"><span class="spin"></span>${esc(n)}…</div></div>`).join("")
      + adderCardHTML(p);
    bindAdder(p);
    for (const n of p.nodes) {
      const conf = await getConfig(pubkey, n);
      const cell = $("#dep-" + cssid(n)); if (!cell) continue;
      const col = Store.nodeColor(n);
      const qr = conf ? `<div class="qr" data-qrzoom="${cssid(n)}" title="Tap to enlarge for scanning">${qrSVG(conf)}</div>`
        : `<div class="qr-none">config shown right after creation${Store.storeConfigs ? "" : ", or enable store_configs to keep it"}</div>`;
      cell.className = "deploy";
      cell.innerHTML = `
        <div class="deploy-head"><span class="dot" id="depdot-${cssid(n)}" style="background:${col}"></span><span class="nm">${esc(n)}</span><span class="grow"></span><span id="depbadge-${cssid(n)}"></span></div>
        <div class="deploy-body">${qr}
          <div class="dmeta">
            <div class="row"><span class="k">handshake</span><span class="vv" id="depseen-${cssid(n)}">—</span></div>
            <div class="row"><span class="k">transfer</span><span class="vv" id="deprate-${cssid(n)}">—</span></div>
            <div class="row"><span class="k">endpoint</span><span class="vv" id="depep-${cssid(n)}">—</span></div>
          </div></div>
        ${conf ? `<div class="acts"><button class="btn btn-mini" data-dl="${cssid(n)}">${ICON.download} Config</button><button class="btn btn-mini" data-cp="${cssid(n)}">${ICON.copy} Copy</button></div>` : ""}`;
      if (conf) {
        cell.querySelector(`[data-dl="${cssid(n)}"]`).onclick = () => downloadConf(conf, (p.name || "peer") + "-" + n);
        cell.querySelector(`[data-cp="${cssid(n)}"]`).onclick = () => { navigator.clipboard.writeText(conf); toast("Config for " + n + " copied.", "ok", 1800); };
        const qz = cell.querySelector(`[data-qrzoom="${cssid(n)}"]`);
        if (qz) qz.onclick = () => qrZoom(conf, (p.name || "peer") + " · " + n);
      }
    }
    patchDeploys();
  }
  function patchDeploys() {
    const p = Store.peer(pubkey); if (!p) return;
    p.deployments.forEach(d => {
      const id = cssid(d.node);
      const bdg = $("#depbadge-" + id); if (bdg) bdg.innerHTML = badge(d.status);
      const obs = deploymentObs(pubkey, d.node, p.iface);
      const sv = $("#depseen-" + id); if (sv) sv.textContent = obs ? seen(obs.handshake_age) : "—";
      const rv = $("#deprate-" + id); if (rv) rv.textContent = obs ? "↓ " + rate(obs.rx_speed) + "  ↑ " + rate(obs.tx_speed) : "—";
      const ev = $("#depep-" + id); if (ev && obs && obs.endpoint) ev.textContent = obs.endpoint;
    });
  }
  function adderCardHTML(p) {
    const avail = Store.fleet.filter(n => !p.nodes.includes(n.name));
    if (!avail.length) return "";
    return `<div class="deploy adder" id="u-adder"><div class="inner"><div class="ring">${ICON.plus}</div><div>Add to another server</div><div class="faint" style="font-size:11px">extend redundancy</div></div></div>`;
  }
  function bindAdder(p) {
    const a = $("#u-adder"); if (!a) return;
    a.onclick = () => addToServerFlow(pubkey);
  }

  let lastNodeKey = p0.nodes.join(",");
  return function update() {
    const p = Store.peer(pubkey);
    if (!p) { return; }
    renderNameline(); renderIdentity();
    const key = p.nodes.join(",");
    if (key !== lastNodeKey) { lastNodeKey = key; buildDeploys(); }   // node set changed -> rebuild QR cards
    else patchDeploys();
  };
}
function cssid(s) { return s.replace(/[^a-zA-Z0-9_-]/g, "_"); }
function downloadConf(text, base) {
  const blob = new Blob([text], { type: "text/plain" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = base.replace(/[^\w.-]+/g, "_") + ".conf"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ───────────────────────── shared actions ─────────────────────────
function bindOrphanActions(scope) {
  $$(scope + " [data-adopt]").forEach(b => b.onclick = async () => {
    const o = JSON.parse(b.dataset.adopt); b.disabled = true;
    const r = await api.adopt({ node: o.node, iface: o.iface, public_key: o.pubkey, allowed_ips: o.ip, name: "" });
    if (!r.ok) { toast("Adopt failed: " + (r.error || ""), "err"); b.disabled = false; return; }
    toast("Adopted into the roster.", "ok"); await Store.poll(); refreshScreen();
  });
  $$(scope + " [data-rm]").forEach(b => {
    let armed = false, t = null;
    b.onclick = async () => {
      const o = JSON.parse(b.dataset.rm);
      if (!armed) { armed = true; b.textContent = "Confirm?"; t = setTimeout(() => { armed = false; b.textContent = "Remove"; }, 2600); return; }
      clearTimeout(t); b.disabled = true; b.textContent = "Removing…";
      const r = await api.removePeer({ node: o.node, iface: o.iface, public_key: o.pubkey, nodes: [o.node] });
      if (!r.ok) { toast("Remove failed: " + (r.error || ""), "err"); b.disabled = false; b.textContent = "Remove"; return; }
      toast("Removed from " + o.node + ".", "ok"); await Store.poll(); refreshScreen();
    };
  });
}
async function removePeerFlow(pubkey, nodes) {
  const btn = $("#u-remove"); if (!btn) return;
  if (btn.dataset.armed !== "1") {
    btn.dataset.armed = "1"; btn.textContent = "Confirm — remove from all " + nodes.length + " servers?";
    setTimeout(() => { if (btn) { btn.dataset.armed = "0"; btn.textContent = "Remove peer"; } }, 3200);
    return;
  }
  btn.disabled = true; btn.textContent = "Removing…";
  const r = await api.removePeer({ public_key: pubkey });
  if (!r.ok) { toast("Remove failed: " + (r.error || ""), "err"); btn.disabled = false; btn.dataset.armed = "0"; btn.textContent = "Remove peer"; return; }
  const queued = Object.values(r.data.results || {}).some(x => x && x.ok);
  toast("Peer removed.", "ok"); await Store.poll(); location.hash = "#/users";
}
async function addToServerFlow(pubkey) {
  const p = Store.peer(pubkey); if (!p) return;
  // need an existing config to extract privkey + PSK
  let srcConf = null;
  for (const n of p.nodes) { srcConf = await getConfig(pubkey, n); if (srcConf) break; }
  if (!srcConf) { toast("Need a saved config to clone the identity. Re-create the peer, or enable store_configs.", "info", 5200); return; }
  const { priv, psk } = parseConf(srcConf);
  const avail = Store.fleet.filter(n => !p.nodes.includes(n.name));
  openSheet(`<div class="sheet-head"><h3>Add ${esc(p.name || "peer")} to another server</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body">
      <div class="field"><label>Server</label><div class="nodepick" id="ats-nodes">
        ${avail.map(n => `<div class="nodeopt" data-n="${esc(n.name)}"><span class="box"></span><span class="swatch" style="background:${n.color || "#5f7569"}"></span><span class="nm">${esc(n.name)}</span><span class="tp">${esc(n.transport)}</span></div>`).join("")}
      </div><div class="hint">Same address (${esc(p.ip)}), key and preshared key — a redundant endpoint.</div></div>
      <div class="formmsg" id="ats-msg"></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="ats-go" disabled>Deploy</button></div>`);
  let chosen = null;
  $$("#ats-nodes .nodeopt").forEach(o => o.onclick = () => { $$("#ats-nodes .nodeopt").forEach(x => x.classList.remove("sel")); o.classList.add("sel"); chosen = o.dataset.n; $("#ats-go").disabled = false; });
  $("#ats-go").onclick = async () => {
    if (!chosen) return;
    const msg = $("#ats-msg"); msg.className = "formmsg work"; msg.textContent = "reading " + chosen + "…";
    const d = await api.describe(chosen);
    if (!d.ok) { msg.className = "formmsg err"; msg.textContent = d.error || "describe failed"; return; }
    const info = (d.data.interfaces || {})[p.iface];
    if (!info) { msg.className = "formmsg err"; msg.textContent = chosen + " has no interface " + p.iface; return; }
    const conf = buildConf({ privkey: priv, address: p.ip + "/32", dns: info.dns, awg_params: info.awg_params, server_pubkey: info.public_key, psk, endpoint: info.endpoint, allowed: "0.0.0.0/0, ::/0" });
    const body = { nodes: [chosen], iface: p.iface, public_key: pubkey, allowed_ips: p.ip + "/32", preshared_key: psk || "none", name: p.name, type: p.type };
    if (Store.storeConfigs) body.configs = { [chosen]: conf };
    msg.textContent = "deploying to " + chosen + "…";
    const r = await api.addPeer(body);
    if (!r.ok) { msg.className = "formmsg err"; msg.textContent = "Failed: " + (r.error || r.code || ""); return; }
    (Store.sessionConfigs[pubkey] = Store.sessionConfigs[pubkey] || {})[chosen] = conf;
    toast("Deployed to " + chosen + ".", "ok"); closeSheet(); await Store.poll(); refreshScreen();
  };
}

// ───────────────────────── create flow ─────────────────────────
let createCache = {};   // node -> describe data (this open)
function openCreate(prefill) {
  prefill = prefill || {};
  openSheet(`<div class="sheet-head"><h3>Add peer</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body">
      <div class="field"><label>Name</label><input id="c-name" placeholder="alice-phone"></div>
      <div class="field"><label>Interface</label><select id="c-iface"><option>…</option></select></div>
      <div class="field"><label>Servers <span class="faint" style="text-transform:none;letter-spacing:0">— pick one, or several for redundancy</span></label>
        <div class="nodepick" id="c-nodes"></div></div>
      <div class="field"><label>Address</label><input id="c-ip" placeholder="auto"><div class="hint" id="c-iphint">Chosen free on every selected server.</div></div>
      <div class="field"><label>Preshared key</label><div class="inline"><input id="c-psk"><button class="btn btn-ghost" id="c-regen" title="Regenerate">↻</button></div></div>
      <button class="advtoggle" id="c-advt"><span id="c-caret">▸</span> Advanced</button>
      <div class="adv" id="c-adv"><div class="field" style="margin-top:8px"><label>Client allowed IPs (routing)</label>
        <input id="c-allowed" value="0.0.0.0/0, ::/0"><div class="hint">Full tunnel by default. Narrow for split tunnel (e.g. a router peer).</div></div></div>
      <div class="formmsg" id="c-msg"></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="c-create">Create peer</button></div>`);

  $("#c-psk").value = genPSK();
  $("#c-regen").onclick = () => { $("#c-psk").value = genPSK(); toast("New preshared key.", "info", 1500); };
  $("#c-advt").onclick = () => { const a = $("#c-adv"); a.classList.toggle("open"); $("#c-caret").textContent = a.classList.contains("open") ? "▾" : "▸"; };
  $("#c-create").onclick = doCreate;
  $("#c-name").addEventListener("keydown", e => { if (e.key === "Enter") doCreate(); });

  // load describe for all nodes (interfaces + server info), then populate
  createCache = {};
  const msg = $("#c-msg"); msg.className = "formmsg work"; msg.textContent = "reading servers…";
  Promise.all(Store.fleet.map(n => api.describe(n.name).then(r => { if (r.ok) createCache[n.name] = r.data; }).catch(() => {})))
    .then(() => {
      msg.textContent = "";
      const ifaces = new Set();
      Object.values(createCache).forEach(d => Object.keys(d.interfaces || {}).forEach(i => ifaces.add(i)));
      const list = Array.from(ifaces);
      if (!list.length) { msg.className = "formmsg err"; msg.textContent = "No servers reachable."; return; }
      $("#c-iface").innerHTML = list.map(i => `<option value="${esc(i)}">${esc(i)}</option>`).join("");
      const want = prefill.iface && list.includes(prefill.iface) ? prefill.iface : list[0];
      $("#c-iface").value = want;
      $("#c-iface").onchange = () => renderNodePick(prefill);
      renderNodePick(prefill, true);
    });
}
function nodesWithIface(iface) { return Store.fleet.filter(n => createCache[n.name] && (createCache[n.name].interfaces || {})[iface]); }
function selectedCreateNodes() { return $$("#c-nodes .nodeopt.sel").map(o => o.dataset.n); }
function renderNodePick(prefill, first) {
  const iface = $("#c-iface").value;
  const usable = nodesWithIface(iface).map(n => n.name);
  $("#c-nodes").innerHTML = Store.fleet.map(n => {
    const ok = usable.includes(n.name);
    const preSel = first && (prefill.node ? prefill.node === n.name : usable[0] === n.name);
    return `<div class="nodeopt ${ok ? "" : "disabled"} ${ok && preSel ? "sel" : ""}" data-n="${esc(n.name)}">
      <span class="box">${ok && preSel ? ICON.check : ""}</span><span class="swatch" style="background:${n.color || "#5f7569"}"></span>
      <span class="nm">${esc(n.name)}</span><span class="tp">${ok ? esc(n.transport) : "no " + esc(iface)}</span></div>`;
  }).join("");
  $$("#c-nodes .nodeopt").forEach(o => {
    if (o.classList.contains("disabled")) return;
    o.onclick = () => { o.classList.toggle("sel"); o.querySelector(".box").innerHTML = o.classList.contains("sel") ? ICON.check : ""; refreshAddr(); };
  });
  refreshAddr();
}
async function refreshAddr() {
  const nodes = selectedCreateNodes(), iface = $("#c-iface").value, ip = $("#c-ip"), hint = $("#c-iphint");
  if (!nodes.length) { ip.value = ""; ip.placeholder = "select a server"; hint.textContent = "Pick at least one server."; return; }
  ip.placeholder = "…"; hint.textContent = "finding a free address on " + nodes.length + " server" + (nodes.length > 1 ? "s" : "") + "…";
  const r = await api.nextIp(nodes, iface);
  if (r.ok) { ip.value = r.data.next_ip; hint.textContent = nodes.length > 1 ? "Free on every selected server (" + (r.data.subnet || "") + ")." : "Next free address."; }
  else { ip.value = ""; hint.textContent = r.error || "couldn't pick an address"; }
}
async function doCreate() {
  const name = $("#c-name").value.trim(), iface = $("#c-iface").value;
  const nodes = selectedCreateNodes(), ip = $("#c-ip").value.trim();
  let psk = $("#c-psk").value.trim();
  if (!psk) { psk = genPSK(); $("#c-psk").value = psk; }   // PSK is mandatory — never create a peer without one
  const allowed = $("#c-allowed").value.trim() || "0.0.0.0/0, ::/0";
  const msg = $("#c-msg");
  if (!nodes.length) { msg.className = "formmsg err"; msg.textContent = "Select at least one server."; return; }
  if (!ip) { msg.className = "formmsg err"; msg.textContent = "No address — check server reachability."; return; }
  $("#c-create").disabled = true; msg.className = "formmsg work"; msg.textContent = "generating keys…";
  try {
    const keys = await genKeys();
    const configs = {};
    for (const n of nodes) {
      const info = (createCache[n].interfaces || {})[iface];
      configs[n] = buildConf({ privkey: keys.priv, address: ip, dns: info.dns, awg_params: info.awg_params, server_pubkey: info.public_key, psk, endpoint: info.endpoint, allowed });
    }
    msg.textContent = "creating on " + nodes.length + " server" + (nodes.length > 1 ? "s" : "") + "…";
    const body = { nodes, iface, public_key: keys.pub, allowed_ips: ip, preshared_key: psk, name, type: "user" };
    if (Store.storeConfigs) body.configs = configs;
    const r = await api.addPeer(body);
    if (!r.ok) { msg.className = "formmsg err"; msg.textContent = "Failed: " + (r.error || r.code || "unknown"); $("#c-create").disabled = false; return; }
    Store.sessionConfigs[keys.pub] = configs;
    Store.recentlyCreated[keys.pub] = Date.now();
    const fails = Object.entries(r.data.results || {}).filter(([, v]) => !v.ok).map(([n]) => n);
    toast(fails.length ? "Created — but failed on " + fails.join(", ") : (name || "Peer") + " created on " + nodes.length + " server" + (nodes.length > 1 ? "s" : ""), fails.length ? "info" : "ok");
    closeSheet();
    await Store.poll();
    location.hash = "#/user/" + encodeURIComponent(keys.pub);   // land on profile -> shows the QR(s)
  } catch (e) { msg.className = "formmsg err"; msg.textContent = "Error: " + e.message; $("#c-create").disabled = false; }
}

// ───────────────────────── modal plumbing ─────────────────────────
function openSheet(html) { $("#sheet").innerHTML = html; const o = $("#overlay"); o.classList.add("show"); o.setAttribute("aria-hidden", "false"); $$("[data-close]", o).forEach(b => b.onclick = closeSheet); }
function closeSheet() { const o = $("#overlay"); o.classList.remove("show"); o.setAttribute("aria-hidden", "true"); $("#sheet").innerHTML = ""; }
$("#overlay").addEventListener("click", e => { if (e.target.id === "overlay") closeSheet(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#overlay").classList.contains("show")) closeSheet(); });
$("#add-peer-btn").onclick = () => openCreate({});


// ═════════════════════════ SCREEN: NODES ═════════════════════════
const SWATCHES = ["#34d399", "#22d3ee", "#e8c04b", "#f0913c", "#f0596b", "#c084e8", "#7dd3fc", "#a3e635"];
function swatchPicker(sel) {
  return `<div class="swrow" id="np-sw">` + SWATCHES.map(c =>
    `<div class="swopt ${c === sel ? "sel" : ""}" data-c="${c}" style="background:${c}"></div>`).join("") + `</div>`;
}
function wireSwatch() {
  $$("#np-sw .swopt").forEach(o => o.onclick = () => {
    $$("#np-sw .swopt").forEach(x => x.classList.remove("sel")); o.classList.add("sel");
  });
}
function pickedSwatch() { const s = $("#np-sw .swopt.sel"); return s ? s.dataset.c : SWATCHES[0]; }

function NodesScreen() {
  $("#view").innerHTML = `
    <div class="screen">
      <div class="section-title" style="margin-top:6px">
        <h2>Nodes</h2><span class="count" id="nodes-count"></span><span class="grow"></span>
        <button class="btn btn-primary" id="nodes-add"><span class="plus">+</span> Add node</button>
      </div>
      <div class="hint" style="margin:0 2px 16px;color:var(--faint);font-size:12px">
        Entry servers run <span class="mono">swg-noded</span>, which syncs to this panel over HTTPS — the node needs no inbound access. Add one here to get a one-time enrollment command.
      </div>
      <div id="nodes-grid"></div>
    </div>`;
  $("#nodes-add").onclick = openNodeCreate;

  return function update() {
    const ns = Store.nodes || [];
    $("#nodes-count").textContent = ns.length + (ns.length === 1 ? " server" : " servers");
    const grid = $("#nodes-grid");
    if (!ns.length) {
      grid.className = "";
      grid.innerHTML = `<div class="empty"><b>No nodes yet</b>Add your first entry server — you'll get a one-time command to run on it.</div>`;
      return;
    }
    grid.className = "nodegrid";
    grid.innerHTML = ns.map(n => {
      const st = n.status || "dangling";
      const stTxt = st === "online" ? "online" : (st === "offline" ? "offline" : "awaiting enroll");
      const sync = st === "dangling" ? "never connected" : (st === "online" ? "synced " + ago(n.last_seen) : "last seen " + ago(n.last_seen));
      const ifaces = (n.interfaces || []).length ? n.interfaces.join(", ") : "—";
      return `<div class="ncard" data-n="${esc(n.name)}">
        <div class="ntop"><span class="nsw" style="background:${esc(n.color || "#5f7569")}"></span>
          <span class="nname">${esc(n.name)}</span><span class="grow"></span>
          <span class="nstat ${st}">${stTxt}</span></div>
        <div class="nrows">
          <div class="nrow"><span class="l">Endpoint</span><span class="r">${esc(n.endpoint_host || "—")}</span></div>
          <div class="nrow"><span class="l">Peers</span><span class="r">${n.peer_count || 0}</span></div>
          <div class="nrow"><span class="l">Throughput</span><span class="r"><span class="down">↓ ${rate(n.rx_speed)}</span> <span class="up">↑ ${rate(n.tx_speed)}</span></span></div>
          <div class="nrow"><span class="l">Interfaces</span><span class="r">${esc(ifaces)}</span></div>
          <div class="nrow"><span class="l">Sync</span><span class="r">${esc(sync)}</span></div>
        </div>
        <div class="nacts">
          <button class="btn-mini" data-act="edit">Edit</button>
          <button class="btn-mini warn" data-act="rotate">Rotate token</button>
          <span style="flex:1"></span>
          <button class="btn-danger" data-act="remove">Remove</button>
        </div>
      </div>`;
    }).join("");
    $$("#nodes-grid .ncard").forEach(card => {
      const node = ns.find(x => x.name === card.dataset.n);
      card.querySelector('[data-act="edit"]').onclick = () => openNodeEdit(node);
      card.querySelector('[data-act="rotate"]').onclick = () => rotateNodeToken(node.name);
      card.querySelector('[data-act="remove"]').onclick = () => removeNode(node);
    });
  };
}

function openNodeCreate() {
  openSheet(`<div class="sheet-head"><h3>Add node</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body">
      <div class="field"><label>Name</label><input id="np-name" placeholder="msk-edge1" autocomplete="off">
        <div class="hint">Letters, digits, - or _. Used as the node's id across the panel.</div></div>
      <div class="field"><label>Public endpoint (host or IP)</label><input id="np-ep" placeholder="203.0.113.7" autocomplete="off">
        <div class="hint">The address clients dial to reach this node. You can change it later.</div></div>
      <div class="field"><label>Colour</label>${swatchPicker(SWATCHES[0])}</div>
      <div class="formmsg" id="np-msg"></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button>
      <button class="btn btn-primary" id="np-create">Create node</button></div>`);
  wireSwatch();
  $("#np-name").focus();
  $("#np-name").addEventListener("keydown", e => { if (e.key === "Enter") $("#np-ep").focus(); });
  $("#np-ep").addEventListener("keydown", e => { if (e.key === "Enter") doNodeCreate(); });
  $("#np-create").onclick = doNodeCreate;
}
async function doNodeCreate() {
  const name = $("#np-name").value.trim(), ep = $("#np-ep").value.trim(), color = pickedSwatch();
  const msg = $("#np-msg");
  if (!name) { msg.className = "formmsg err"; msg.textContent = "Give the node a name."; return; }
  $("#np-create").disabled = true; msg.className = "formmsg work"; msg.textContent = "creating…";
  const r = await api.nodeCreate({ name, endpoint_host: ep, color });
  if (!r.ok) { msg.className = "formmsg err"; msg.textContent = r.error || "couldn't create node"; $("#np-create").disabled = false; return; }
  await Store.poll();
  showNodeToken(r.data.name, r.data.token, true);
}

const BOOTSTRAP_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh";
function enrollCommands(token) {
  // -host carries the mount subpath so the node posts to <origin><base>/api/node/sync.
  // The installer prompts for endpoint (+ interfaces, bare-metal) on the node itself.
  const host = `${location.origin}${BASE}`;
  return {
    bare: `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s node -key ${token} -host ${host}`,
    docker: `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s docker node -key ${token} -host ${host}`,
  };
}
function showNodeToken(name, token, isNew) {
  const cmds = enrollCommands(token);
  openSheet(`<div class="sheet-head"><h3>${isNew ? "Node created" : "New token"} · ${esc(name)}</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body">
      <div class="notice warn">${ICON.warn}<span><b>Shown once.</b> This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.</span></div>
      <div class="field" style="margin-top:15px"><label>Enrollment token</label>
        <div class="cmdrow"><div class="tokenbox">${esc(token)}</div>
          <button class="copyaction" data-cp="${esc(token)}">${ICON.copy} Copy</button></div></div>
      <div class="field"><label>Run on the node — <span style="color:#60a5fa;font-weight:700">bare-metal</span></label>
        <div class="cmdrow"><div class="tokenbox">${esc(cmds.bare)}</div>
          <button class="copyaction" data-cp="${esc(cmds.bare)}">${ICON.copy} Copy</button></div></div>
      <div class="field"><label>Run on the node — <span style="color:#c084e8;font-weight:700">docker</span></label>
        <div class="cmdrow"><div class="tokenbox">${esc(cmds.docker)}</div>
          <button class="copyaction" data-cp="${esc(cmds.docker)}">${ICON.copy} Copy</button></div>
        <div class="hint">Pick one. Both fetch the installer and prompt for the node's endpoint; <b>bare-metal</b> installs <span class="mono">swg-noded</span> via systemd and sets up the wg/awg interface, <b>docker</b> runs the <span class="mono">swg-node</span> container (auto-generating an AmneziaWG interface). The node appears once it syncs.</div></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-primary" data-close>Done</button></div>`);
  $$("#sheet .copyaction").forEach(b => b.onclick = () => { navigator.clipboard.writeText(b.dataset.cp); toast("Copied.", "ok", 1500); });
}

function openNodeEdit(node) {
  openSheet(`<div class="sheet-head"><h3>Edit ${esc(node.name)}</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body">
      <div class="field"><label>Public endpoint (host or IP)</label><input id="ne-ep" value="${esc(node.endpoint_host || "")}" autocomplete="off"></div>
      <div class="field"><label>Colour</label>${swatchPicker(node.color || SWATCHES[0])}</div>
      <div class="formmsg" id="ne-msg"></div>
    </div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button>
      <button class="btn btn-primary" id="ne-save">Save</button></div>`);
  wireSwatch();
  $("#ne-save").onclick = async () => {
    const ep = $("#ne-ep").value.trim(), color = pickedSwatch();
    $("#ne-save").disabled = true;
    const r = await api.nodeUpdate({ name: node.name, endpoint_host: ep, color });
    if (!r.ok) { const m = $("#ne-msg"); m.className = "formmsg err"; m.textContent = r.error || "save failed"; $("#ne-save").disabled = false; return; }
    toast("Saved.", "ok"); closeSheet(); await Store.poll(); refreshScreen();
  };
}

function rotateNodeToken(name) {
  openSheet(`<div class="sheet-head"><h3>Rotate token · ${esc(name)}</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body"><div class="notice warn">${ICON.warn}<span>The current token stops working immediately. Re-enroll the node with the new token (re-run the install command, or update its config) or it will go offline.</span></div></div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button>
      <button class="btn btn-primary" id="rot-go">Rotate</button></div>`);
  $("#rot-go").onclick = async () => {
    $("#rot-go").disabled = true;
    const r = await api.nodeRotate({ name });
    if (!r.ok) { toast(r.error || "rotate failed", "err"); return; }
    showNodeToken(name, r.data.token, false);
  };
}

function removeNode(node) {
  const peers = (Store.recon.peers || []).filter(p => (p.nodes || []).includes(node.name) && p.status !== "gone");
  const onlyHere = peers.filter(p => (p.nodes || []).length === 1).length;
  const note = peers.length
    ? `It's referenced by <b>${peers.length}</b> peer${peers.length > 1 ? "s" : ""}${onlyHere ? ` — <b>${onlyHere}</b> live only here and will be removed from the roster` : ""}.`
    : "No peers reference it.";
  openSheet(`<div class="sheet-head"><h3>Remove ${esc(node.name)}</h3><button class="x" data-close>×</button></div>
    <div class="sheet-body"><div class="notice warn">${ICON.warn}<span>Removes the node from the panel and revokes its token. ${note} The node keeps running until you stop <span class="mono">swg-noded</span> on it.</span></div></div>
    <div class="sheet-foot"><span class="grow"></span><button class="btn btn-ghost" data-close>Cancel</button>
      <button class="btn btn-danger" id="rm-go">Remove node</button></div>`);
  $("#rm-go").onclick = async () => {
    $("#rm-go").disabled = true;
    const r = await api.nodeDelete({ name: node.name });
    if (!r.ok) { toast(r.error || "remove failed", "err"); return; }
    toast("Node removed.", "ok"); closeSheet(); await Store.poll(); refreshScreen();
  };
}

// ───────────────────────── router ─────────────────────────
function AccountScreen() {
  $("#view").innerHTML = `
    <div class="screen">
      <div class="crumb"><b>Account</b></div>
      <div class="card" style="max-width:520px">
        <h3 style="margin:0 0 4px">Admin login</h3>
        <p class="hint" style="margin:0 0 18px">Change the panel username and password. Takes effect immediately — you'll be asked to sign in again.</p>
        <div id="acc-msg" class="formmsg" style="display:none"></div>
        <div class="field"><label>Username</label><input id="acc-user" autocomplete="username"></div>
        <div class="field"><label>Current password</label><input id="acc-cur" type="password" autocomplete="current-password" placeholder="required to confirm changes"></div>
        <div class="field"><label>New password</label><input id="acc-new" type="password" autocomplete="new-password" placeholder="leave blank to keep current"></div>
        <div class="field"><label>Confirm new password</label><input id="acc-new2" type="password" autocomplete="new-password"></div>
        <div style="margin-top:8px"><button class="btn btn-primary" id="acc-save">Save changes</button></div>
      </div>
    </div>`;
  const msg = $("#acc-msg");
  const show = (t, ok) => { msg.style.display = "block"; msg.className = "formmsg " + (ok ? "ok" : "err"); msg.textContent = t; };
  api.account().then(r => { if (r.ok && r.data.username) $("#acc-user").value = r.data.username;
    if (r.ok && !r.data.auth_enabled) show("This panel has no login configured — changes are disabled.", false); });
  $("#acc-save").onclick = async () => {
    const username = $("#acc-user").value.trim();
    const cur = $("#acc-cur").value, np = $("#acc-new").value, np2 = $("#acc-new2").value;
    if (!username) return show("Username can't be empty.", false);
    if (!cur) return show("Enter your current password to confirm.", false);
    if (np && np !== np2) return show("New passwords don't match.", false);
    if (np && np.length < 8) return show("New password must be at least 8 characters.", false);
    $("#acc-save").disabled = true; show("Saving…", true);
    const r = await api.accountSave({ username, current_password: cur, new_password: np });
    if (!r.ok) { $("#acc-save").disabled = false; return show(r.error || "Failed to update.", false); }
    show("Updated. Reloading — sign in with your new credentials…", true);
    setTimeout(() => location.reload(), 1400);   // Basic-Auth: force re-auth with the new creds
  };
  return () => {};
}

const ROUTES = [
  { re: /^\/$/, fn: OverviewScreen, tab: "overview" },
  { re: /^\/node\/(.+)$/, fn: NodeScreen, tab: "overview", keys: ["node"] },
  { re: /^\/nodes$/, fn: NodesScreen, tab: "nodes" },
  { re: /^\/users$/, fn: UsersScreen, tab: "users" },
  { re: /^\/user\/(.+)$/, fn: UserScreen, tab: "users", keys: ["pubkey"] },
  { re: /^\/account$/, fn: AccountScreen, tab: "account" },
];
let activeUpdate = null;
let uiBusy = false;   // when true (e.g. an inline editor is open), suppress auto-refresh re-renders
function mountRoute() {
  uiBusy = false;
  const path = (location.hash || "#/").replace(/^#/, "") || "/";
  let route = null, params = {};
  for (const r of ROUTES) { const m = path.match(r.re); if (m) { route = r; (r.keys || []).forEach((k, i) => params[k] = m[i + 1]); break; } }
  if (!route) { route = ROUTES[0]; }
  setNav(route.tab);
  window.scrollTo(0, 0);
  activeUpdate = route.fn(params) || (() => {});
  updateChrome();
  activeUpdate();
}
function refreshScreen() { mountRoute(); }
window.addEventListener("hashchange", mountRoute);
Store.subscribe(() => { updateChrome(); if (activeUpdate && !uiBusy) activeUpdate(); });

// ───────────────────────── boot ─────────────────────────
(async () => {
  $("#view").innerHTML = `<div class="loading"><span class="spin"></span>connecting…</div>`;
  try { await Store.init(); } catch (e) { $("#view").innerHTML = `<div class="empty"><b>Can't reach the panel</b>${esc(e.message)}</div>`; return; }
  if (!location.hash) location.hash = "#/";
  mountRoute();
})();
