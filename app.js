/* swg-panel — single-page operator console.
   Buildless Preact + htm (vendored ESM, no build step). The data model is
   User → Peer → Target: a User is identity only; a Peer is one credential
   (pubkey+psk) deployed to one or more Targets, where a target is one
   (node, iface, ip). Peers are managed from the Users angle and from the Peers
   (by-node) angle; unassigned peers carry no user.

   Live polling re-renders the active screen every few seconds; Preact diffs the
   tree, so open inputs/editors are preserved without the old manual update()
   regions. */

import { h, render, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";
import { reconcile } from "./reconcile.js";

const html = htm.bind(h);

// ───────────────────────── tiny helpers ─────────────────────────
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const b64 = u => { let s = ""; for (const x of u) s += String.fromCharCode(x); return btoa(s); };

// Mount-point prefix: when served under a subpath (e.g. /swg), <base href> carries
// it, so root-absolute API/stats paths must be prefixed to stay inside the mount.
const BASE = (() => { try { return new URL(document.baseURI).pathname.replace(/\/+$/, ""); } catch (_) { return ""; } })();
const url = p => BASE + p;

const tkey = (node, iface) => node + "|" + iface;          // session-config key for one target
function ipOf(hostport) { if (!hostport) return ""; const s = String(hostport); return s[0] === "[" ? s.slice(1, s.indexOf("]")) : s.split(":")[0]; }
function portOf(hostport) { if (!hostport) return ""; const s = String(hostport); const i = s.lastIndexOf(":"); return i < 0 ? "" : s.slice(i + 1); }

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
function cssid(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, "_"); }

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
const Ic = ({ i }) => html`<span class="ic" dangerouslySetInnerHTML=${{ __html: ICON[i] || "" }}></span>`;

// ───────────────────────── crypto + config (in-browser; private key never leaves) ─────────────────────────
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
// Same config, Endpoint swapped to the turn-proxy's public listen address (import via turn-proxy).
function turnConf(baseConf, listen) { return baseConf.replace(/Endpoint\s*=\s*\S.*/m, "Endpoint = " + listen); }

function downloadConf(text, base) {
  const blob = new Blob([text], { type: "text/plain" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = base.replace(/[^\w.-]+/g, "_") + ".conf"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ───────────────────────── QR ─────────────────────────
function qrDataURL(text, targetPx) {
  const q = qrcode(0, "L");
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
function QR({ conf, label, px }) {
  let src = null;
  try { src = qrDataURL(conf, px || 360); } catch (_) { src = null; }
  if (!src) return html`<div class="qr-fail">config too large<br>to encode as QR</div>`;
  return html`<div class="qr" title="Tap to enlarge for scanning" onClick=${() => qrZoom(conf, label)}>
    <img class="qrimg" alt="config QR" src=${src}/></div>`;
}
function qrZoom(conf, label) {
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

// ───────────────────────── api ─────────────────────────
const api = {
  async get(p) { const r = await fetch(url(p)); return r.json(); },
  async post(p, b) { const r = await fetch(url(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }); return r.json(); },
  fleet() { return this.get("/api/fleet"); },
  roster() { return this.get("/api/roster"); },
  describe(node) { return this.get("/api/describe?node=" + encodeURIComponent(node)); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  nodeRotate(b) { return this.post("/api/nodes/rotate", b); },
  nodeDelete(b) { return this.post("/api/nodes/delete", b); },
  // users
  userCreate(b) { return this.post("/api/users/create", b); },
  userUpdate(b) { return this.post("/api/users/update", b); },
  userDelete(b) { return this.post("/api/users/delete", b); },
  // peers
  peerCreate(b) { return this.post("/api/peers/create", b); },
  peerAddTarget(b) { return this.post("/api/peers/add-target", b); },
  peerRemoveTarget(b) { return this.post("/api/peers/remove-target", b); },
  peerDelete(b) { return this.post("/api/peers/delete", b); },
  peerAssign(b) { return this.post("/api/peers/assign", b); },
  peerAdopt(b) { return this.post("/api/peers/adopt", b); },
};

// ───────────────────────── store + reactive bus ─────────────────────────
const bus = { subs: new Set(), emit() { this.subs.forEach(f => { try { f(); } catch (e) { console.error(e); } }); }, sub(f) { this.subs.add(f); return () => this.subs.delete(f); } };
function useStore() { const [, set] = useState(0); useEffect(() => bus.sub(() => set(x => x + 1)), []); }

const Store = {
  fleet: [], storeConfigs: false, versions: {},
  roster: { version: 1, users: {}, peers: {} }, stats: {}, nodes: [],
  recon: { peers: [], users: [], orphans: [], nodeStatus: {} },
  sessionConfigs: {},        // pubkey -> { "node|iface" -> confText }   (built at creation, in-memory)
  recentlyCreated: {},       // id -> ts (row flash)
  async init() {
    const f = await api.fleet();
    this.fleet = (f.data && f.data.nodes) || [];
    this.storeConfigs = !!(f.data && f.data.store_configs);
    this.versions = (f.data && f.data.versions) || {};
    await this.poll();
    setInterval(() => this.poll().catch(() => {}), 5000);
  },
  async poll() {
    const [f, r, nodes, stats] = await Promise.all([api.fleet(), api.roster(), api.nodes(), this.loadStats()]);
    if (f && f.data) { this.fleet = f.data.nodes || []; this.storeConfigs = !!f.data.store_configs; this.versions = f.data.versions || this.versions; }
    this.roster = (r && r.data) || { version: 1, users: {}, peers: {} };
    this.nodes = (nodes && nodes.data && nodes.data.nodes) || [];
    this.stats = stats;
    this.recon = reconcile(this.roster, stats, Date.now());
    bus.emit();
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
  peer(id) { return this.recon.peers.find(p => p.id === id); },
  user(id) { return this.recon.users.find(u => u.id === id); },
  peersOfUser(id) { return this.recon.peers.filter(p => p.user_id === id); },
  unassignedPeers() { return this.recon.peers.filter(p => p.unassigned); },
};

// turn-proxies on a node whose connect-port matches a given iface's listen_port
function turnProxiesFor(node, iface) {
  const snap = Store.stats[node]; if (!snap) return [];
  const lp = String((((snap.interfaces || {})[iface] || {}).meta || {}).listen_port || "");
  return (snap.turn_proxies || []).filter(tp => lp && portOf(tp.connect) === lp);
}

// resolve a per-target client config: session (built at creation) → stored → none
function getConfig(pubkey, node, iface) {
  const s = Store.sessionConfigs[pubkey];
  if (s && s[tkey(node, iface)]) return Promise.resolve(s[tkey(node, iface)]);
  if (Store.storeConfigs) return api.config(pubkey, node, iface).then(r => r.ok ? r.data.config : null).catch(() => null);
  return Promise.resolve(null);
}
function anySessionConf(pubkey) {
  const s = Store.sessionConfigs[pubkey]; return s ? (Object.values(s)[0] || null) : null;
}

// ───────────────────────── toasts (imperative; outside the Preact tree) ─────────────────────────
function toast(msg, kind = "info", ms = 3600) {
  const host = $("#toasts"); if (!host) return;
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = (ICON[kind] || ICON.info) + "<span>" + esc(msg) + "</span>";
  host.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 250); }, ms);
}
function copy(text, what) { navigator.clipboard.writeText(text); toast((what || "Copied") + ".", "ok", 1500); }

// ───────────────────────── modal ─────────────────────────
let _setModal = () => {};
function openModal(node) { _setModal(node); }
function closeModal() { _setModal(null); }

// ───────────────────────── shared bits ─────────────────────────
const STATUS_RANK = { dangling: 0, partial: 1, pending: 2, unknown: 3, unassigned: 4, online: 5, ready: 6 };
function Badge({ s }) { return html`<span class="badge b-${s}">${s}</span>`; }
function peerLabel(p) { return p.unassigned ? "" : (p.name || ""); }

function TargetPips({ peer }) {
  return html`<span class="pips">${peer.targets.map(d => {
    const col = Store.nodeColor(d.node);
    let cls = "unk";
    if (d.status === "online") cls = "on";
    else if (d.status === "ready") cls = "present";
    else if (d.status === "dangling" || d.status === "pending") cls = "miss";
    return html`<span class="pip ${cls}" style=${"--pc:" + col} title=${d.node + " · " + d.iface + " · " + d.status}></span>`;
  })}</span>`;
}

// inline user assignment <select>
function AssignSelect({ peer }) {
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const onChange = async e => {
    const uid = e.target.value || null;
    const r = await api.peerAssign({ peer_id: peer.id, user_id: uid });
    if (!r.ok) { toast("Assign failed: " + (r.error || ""), "err"); return; }
    toast(uid ? "Assigned." : "Unassigned.", "ok"); await Store.poll();
  };
  return html`<select class="selwrap mini" onChange=${onChange}>
    <option value="" selected=${peer.unassigned}>— unassigned —</option>
    ${users.map(u => html`<option value=${u.id} selected=${peer.user_id === u.id}>${u.name}${u.tag ? " · " + u.tag : ""}</option>`)}
  </select>`;
}

// confirm-on-second-click button
function DangerButton({ label, confirm, onConfirm, className }) {
  const [armed, setArmed] = useState(false);
  const tref = useRef(null);
  useEffect(() => () => clearTimeout(tref.current), []);
  return html`<button class=${"btn btn-mini " + (className || "warn")} onClick=${() => {
    if (!armed) { setArmed(true); tref.current = setTimeout(() => setArmed(false), 2800); return; }
    clearTimeout(tref.current); setArmed(false); onConfirm();
  }}>${armed ? (confirm || "Confirm?") : label}</button>`;
}

// ═════════════════════════ SCREEN: OVERVIEW ═════════════════════════
function Overview() {
  const peers = Store.recon.peers, fleet = Store.fleet, ns = Store.recon.nodeStatus;
  const online = peers.filter(p => p.online).length;
  const redundant = peers.filter(p => new Set(p.targets.map(t => t.node)).size >= 2).length;
  const liveNodes = fleet.filter(n => ns[n.name] === "live").length;
  let rx = 0, tx = 0;
  fleet.forEach(n => { const snap = Store.stats[n.name]; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { rx += pp.rx_speed || 0; tx += pp.tx_speed || 0; } });

  const probs = peers.filter(p => ["dangling", "partial", "pending", "unknown"].includes(p.status))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const unassigned = Store.unassignedPeers();
  const orphans = Store.recon.orphans;
  const why = { dangling: "missing on every server", partial: "missing on some servers", pending: "just created, not seen yet", unknown: "server stale — can't confirm" };

  return html`<div class="screen">
    <div class="statgrid">
      <div class="stat accent"><div class="k"><${Ic} i="check"/> Online now</div><div class="v">${online}<small> / ${peers.length}</small></div><div class="sub">peers connected</div></div>
      <div class="stat"><div class="k">Throughput</div><div class="v" style="font-size:19px">↓ ${rate(rx)}</div><div class="sub">↑ ${rate(tx)} aggregate</div></div>
      <div class="stat"><div class="k">Redundancy</div><div class="v">${redundant}<small> / ${peers.length}</small></div><div class="sub">on two or more servers</div></div>
      <div class="stat"><div class="k">Fleet</div><div class="v">${liveNodes}<small> / ${fleet.length}</small></div><div class="sub">servers reporting</div></div>
    </div>

    <div class="section-title"><h2>Fleet</h2><span class="count">${fleet.length} servers</span><span class="grow"></span></div>
    <div class="fleet">
      ${fleet.length ? fleet.map(n => {
        const live = ns[n.name] === "live";
        const snap = Store.stats[n.name];
        const here = peers.filter(p => p.targets.some(t => t.node === n.name));
        const onl = here.filter(p => p.targets.some(t => t.node === n.name && t.online)).length;
        const pct = here.length ? Math.round(onl / here.length * 100) : 0;
        let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
        let sync = "no data", sc = "warn";
        if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); sync = live ? "synced " + seen(a) + " ago" : "stale · " + seen(a); sc = live ? "" : "warn"; }
        return html`<a class="tile ${live ? "" : "stale"}" href=${"#/node/" + encodeURIComponent(n.name)}>
          <span class="arrow"><${Ic} i="arrow"/></span>
          <div class="tile-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="tile-name">${n.name}</span><span class="tport">${n.transport}</span></div>
          <div class="tile-rate"><span class="down">↓ ${rate(nrx)}</span><span class="up">↑ ${rate(ntx)}</span></div>
          <div class="tile-peers">${onl}<i> / ${here.length} online</i></div>
          <div class="meter"><i style=${"width:" + pct + "%;--m:" + (n.color || "var(--online)")}></i></div>
          <div class="tile-sync ${sc}">${sync}</div>
        </a>`;
      }) : html`<div class="allclear">No servers configured in fleet.json.</div>`}
    </div>

    <div class="section-title"><h2>Needs attention</h2><span class="grow"></span></div>
    ${(!probs.length && !unassigned.length && !orphans.length)
      ? html`<div class="allclear"><${Ic} i="check"/><span>Everything's deployed and reporting. No drift across the fleet.</span></div>`
      : html`<div class="attn">
          ${probs.map(p => html`<div class="attn-row" onClick=${() => go("#/peer/" + encodeURIComponent(p.id))}>
            <${Badge} s=${p.status}/><span class="name">${p.name || html`<span class="faint">unassigned peer</span>`}</span>
            <span class="why">${why[p.status] || ""}</span><span class="grow"></span><${TargetPips} peer=${p}/><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${unassigned.map(p => html`<div class="attn-row" onClick=${() => go("#/peer/" + encodeURIComponent(p.id))}>
            <${Badge} s="unassigned"/><span class="name addr">${p.pubkey.slice(0, 18)}…</span>
            <span class="why">no user assigned</span><span class="grow"></span><${TargetPips} peer=${p}/><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${orphans.map(o => html`<div class="attn-row" onClick=${() => go("#/node/" + encodeURIComponent(o.node))}>
            <${Badge} s="orphan"/><span class="name addr">${o.pubkey.slice(0, 18)}…</span>
            <span class="why">on ${o.node}, not in roster</span><span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
        </div>`}
  </div>`;
}

// ═════════════════════════ SCREEN: NODE DETAIL ═════════════════════════
function NodeDetail({ node: rawName }) {
  const name = decodeURIComponent(rawName);
  const node = Store.node(name);
  const [meta, setMeta] = useState(null);
  const [metaErr, setMetaErr] = useState(null);
  useEffect(() => {
    if (!node) return;
    api.describe(name).then(r => { if (r.ok) setMeta(r.data.interfaces || {}); else setMetaErr(r.error || "describe failed"); }).catch(() => setMetaErr("unreachable"));
  }, [name]);

  if (!node) return html`<div class="screen"><div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>${name}</b></div>
    <div class="empty"><b>Unknown server</b>“${name}” isn't in the fleet.</div></div>`;

  const live = Store.recon.nodeStatus[name] === "live";
  const snap = Store.stats[name];
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === name));
  const onl = here.filter(p => p.targets.some(t => t.node === name && t.online)).length;
  let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
  let syncTxt = "no snapshot yet";
  if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); syncTxt = live ? "synced " + seen(a) + " ago" : "stale for " + seen(a); }
  const orphans = Store.recon.orphans.filter(o => o.node === name);
  const rows = here.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));

  return html`<div class="screen">
    <div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>${name}</b></div>
    <div class="detail-head">
      <div class="title"><span class="dot ${live ? "live" : "stale"}"></span><h1>${name}</h1><span class="tport">${node.transport}</span></div>
      <div class="grow"></div>
      <button class="btn btn-primary" onClick=${() => openCreatePeer({ node: name })}><span class="plus"><${Ic} i="plus"/></span> Add peer here</button>
    </div>
    <div class="bigdots">
      <span class="badge b-${live ? "online" : "unknown"}">${live ? "reporting" : "stale"}</span>
      <span class="when">${onl} / ${here.length} online</span>
      <span class="when">↓ ${rate(nrx)} &nbsp;↑ ${rate(ntx)}</span>
      <span class="when">${syncTxt}</span>
    </div>

    <div class="section-title"><h2>Interfaces</h2></div>
    <div class="metagrid">
      ${metaErr ? html`<div class="notice warn"><${Ic} i="warn"/><span>Can't reach this server: ${metaErr}</span></div>`
        : !meta ? html`<div class="loading"><span class="spin"></span>reading server…</div>`
        : Object.keys(meta).length ? Object.keys(meta).map(ifn => {
            const m = meta[ifn];
            const awg = Object.keys(m.awg_params || {}).length ? Object.entries(m.awg_params).slice(0, 4).map(([k, v]) => k + "=" + v).join("  ") : "—";
            return html`<${Fragment}>
              <div class="meta"><div class="k">${ifn} · server key</div><div class="v">${m.public_key || "—"}</div></div>
              <div class="meta"><div class="k">Endpoint</div><div class="v">${m.endpoint || "—"}</div></div>
              <div class="meta"><div class="k">Subnet</div><div class="v">${m.subnet || "—"} · port ${m.listen_port || "—"}</div></div>
              <div class="meta"><div class="k">AmneziaWG</div><div class="v">${awg}</div></div>
            <//>`;
          })
        : html`<div class="notice warn"><${Ic} i="warn"/><span>No managed interfaces reported.</span></div>`}
    </div>

    <div class="section-title"><h2>Peers on this server</h2><span class="count">${here.length} peers</span></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Status</th><th>Name</th><th>Iface · address</th><th>User</th><th>Last handshake</th><th></th></tr></thead>
      <tbody>
        ${rows.length ? rows.map(p => {
          const t = p.targets.find(d => d.node === name) || {};
          const obs = t.observed;
          return html`<tr class="clk" onClick=${() => go("#/peer/" + encodeURIComponent(p.id))}>
            <td data-label="Status"><${Badge} s=${t.status || p.status}/></td>
            <td data-label="Name" class="c-name">${p.name || html`<span class="faint">unassigned</span>`}</td>
            <td data-label="Iface · address"><span class="addr">${t.iface} · ${t.ip || "—"}</span></td>
            <td data-label="User">${p.unassigned ? html`<span class="faint">—</span>` : (p.tag ? p.tag : p.name)}</td>
            <td data-label="Last handshake"><span class="when">${seen(obs ? obs.handshake_age : null)}</span></td>
            <td data-label=""><span class="rowarrow"><${Ic} i="arrow"/></span></td></tr>`;
        }) : html`<tr><td colspan="6" class="empty"><b>No peers here yet</b>Add one to this server to get started.</td></tr>`}
      </tbody></table></div>

    ${orphans.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--orphan)">Unmanaged on this server</h2></div>
      <div class="tablewrap"><table><tbody>
        ${orphans.map(o => html`<${OrphanRow} o=${o}/>`)}
      </tbody></table></div>
    <//>` : null}
  </div>`;
}

function OrphanRow({ o }) {
  return html`<tr>
    <td data-label="Status"><${Badge} s="orphan"/></td>
    <td data-label="Key" class="addr">${o.pubkey.slice(0, 22)}…</td>
    <td data-label="Address"><span class="addr">${o.iface} · ${o.allowed_ips || "—"}</span></td>
    <td data-label="" style="text-align:right">
      <button class="btn btn-mini" onClick=${async () => {
        const r = await api.peerAdopt({ pubkey: o.pubkey, target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } });
        if (!r.ok) { toast("Adopt failed: " + (r.error || ""), "err"); return; }
        toast("Adopted (unassigned).", "ok"); await Store.poll();
      }}>Adopt</button>
    </td></tr>`;
}

// ═════════════════════════ SCREEN: PEERS (by node) ═════════════════════════
const peersView = { node: "", iface: "" };
function PeersScreen() {
  useStore();
  const fleet = Store.fleet;
  if (!peersView.node && fleet.length) peersView.node = fleet[0].name;
  const node = peersView.node;
  const snap = Store.stats[node];
  const ifaces = snap ? Object.keys(snap.interfaces || {}) : [];
  if (ifaces.length && !ifaces.includes(peersView.iface)) peersView.iface = ifaces[0];
  const iface = peersView.iface;

  const onIface = Store.recon.peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface));
  const orphans = Store.recon.orphans.filter(o => o.node === node && o.iface === iface);

  return html`<div class="screen">
    <div class="toolbar">
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; bus.emit(); }}>
        ${fleet.map(n => html`<option value=${n.name}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; bus.emit(); }}>
        ${ifaces.length ? ifaces.map(i => html`<option value=${i}>${i}</option>`) : html`<option value="">no interfaces reported</option>`}
      </select>
      <span class="grow"></span>
      <button class="btn btn-primary" disabled=${!iface} onClick=${() => openCreatePeer({ node, iface })}><span class="plus"><${Ic} i="plus"/></span> New peer here</button>
    </div>

    <div class="section-title"><h2>Peers on ${node || "—"} · ${iface || "—"}</h2><span class="count">${onIface.length}</span></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Status</th><th>Name</th><th>Address</th><th>User</th><th>Last</th><th></th></tr></thead>
      <tbody>
        ${onIface.length ? onIface.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]).map(p => {
          const t = p.targets.find(d => d.node === node && d.iface === iface) || {};
          return html`<tr>
            <td data-label="Status"><${Badge} s=${t.status || p.status}/></td>
            <td data-label="Name" class="c-name clk" onClick=${() => go("#/peer/" + encodeURIComponent(p.id))}>${p.name || html`<span class="faint">unassigned</span>`}</td>
            <td data-label="Address"><span class="addr">${t.ip || "—"}</span></td>
            <td data-label="User"><${AssignSelect} peer=${p}/></td>
            <td data-label="Last"><span class="when">${seen(t.observed ? t.observed.handshake_age : null)}</span></td>
            <td data-label="" style="text-align:right"><${DangerButton} label="Remove" confirm="Remove?" onConfirm=${async () => {
              const r = await api.peerRemoveTarget({ peer_id: p.id, node, iface });
              if (!r.ok) { toast("Remove failed: " + (r.error || ""), "err"); return; }
              toast("Removed from " + node + "/" + iface + ".", "ok"); await Store.poll();
            }}/></td></tr>`;
        }) : html`<tr><td colspan="6" class="empty"><b>No peers here</b>${iface ? "Create one, or copy an existing peer onto this interface." : "This server hasn't reported any interfaces yet."}</td></tr>`}
      </tbody></table></div>

    ${orphans.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--orphan)">Unmanaged here</h2></div>
      <div class="tablewrap"><table><tbody>${orphans.map(o => html`<${OrphanRow} o=${o}/>`)}</tbody></table></div>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USERS ═════════════════════════
const usersFilter = { text: "" };
function UsersScreen() {
  useStore();
  const [, force] = useState(0);
  const users = Store.recon.users.slice();
  const q = usersFilter.text.toLowerCase();
  const shown = users.filter(u => !q || (u.name + " " + u.tag + " " + u.note).toLowerCase().includes(q))
    .sort((a, b) => STATUS_RANK[b.status] - STATUS_RANK[a.status] || String(a.name).localeCompare(String(b.name)));
  const unassigned = Store.unassignedPeers();

  return html`<div class="screen">
    <div class="toolbar">
      <div class="search"><${Ic} i="search"/><input placeholder="Search name, tag, note…" value=${usersFilter.text}
        onInput=${e => { usersFilter.text = e.target.value.trim(); force(x => x + 1); }}/></div>
      <span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => openCreatePeer({})}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
      <button class="btn btn-primary" onClick=${openCreateUser}><span class="plus"><${Ic} i="plus"/></span> New user</button>
    </div>

    <div class="tablewrap"><table>
      <thead><tr><th>Status</th><th>Name</th><th>Tag</th><th>Peers</th><th>Note</th><th>Added</th><th></th></tr></thead>
      <tbody>
        ${!users.length ? html`<tr><td colspan="7" class="empty"><b>No users yet</b>Create a user, then mint peers for them — or create a peer and assign it later.</td></tr>`
          : !shown.length ? html`<tr><td colspan="7" class="empty"><b>Nothing matches</b>Clear the search.</td></tr>`
          : shown.map(u => {
            const flash = Store.recentlyCreated[u.id] && Date.now() - Store.recentlyCreated[u.id] < 3000;
            return html`<tr class="clk ${flash ? "flash" : ""}" onClick=${() => go("#/user/" + encodeURIComponent(u.id))}>
              <td data-label="Status"><${Badge} s=${u.peerCount ? u.status : "empty"}/></td>
              <td data-label="Name" class="c-name">${u.name}</td>
              <td data-label="Tag">${u.tag ? html`<span class="tagchip">${u.tag}</span>` : html`<span class="faint">—</span>`}</td>
              <td data-label="Peers"><span class="when">${u.onlineCount}/${u.peerCount} online</span></td>
              <td data-label="Note" class="c-note">${u.note || html`<span class="faint">—</span>`}</td>
              <td data-label="Added"><span class="when">${ago(u.created_at)}</span></td>
              <td data-label=""><span class="rowarrow"><${Ic} i="arrow"/></span></td></tr>`;
          })}
      </tbody></table></div>

    ${unassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">Unassigned peers</h2><span class="count">${unassigned.length}</span></div>
      <div class="tablewrap"><table>
        <thead><tr><th>Status</th><th>Key</th><th>Targets</th><th>Assign to</th><th></th></tr></thead>
        <tbody>${unassigned.map(p => html`<tr>
          <td data-label="Status"><${Badge} s=${p.status}/></td>
          <td data-label="Key" class="addr clk" onClick=${() => go("#/peer/" + encodeURIComponent(p.id))}>${p.pubkey.slice(0, 20)}…</td>
          <td data-label="Targets">${p.targets.map(t => t.node + "/" + t.iface).join(", ")}</td>
          <td data-label="Assign to"><${AssignSelect} peer=${p}/></td>
          <td data-label="" style="text-align:right"><${DangerButton} label="Delete" confirm="Delete?" onConfirm=${async () => {
            const r = await api.peerDelete({ peer_id: p.id }); if (!r.ok) { toast("Delete failed: " + (r.error || ""), "err"); return; }
            toast("Peer deleted.", "ok"); await Store.poll();
          }}/></td></tr>`)}</tbody></table></div>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USER DETAIL ═════════════════════════
function UserDetail({ id: rawId }) {
  useStore();
  const id = decodeURIComponent(rawId);
  const u = Store.user(id);
  const [edit, setEdit] = useState(false);
  if (!u) return html`<div class="screen"><div class="crumb"><a href="#/users">Users</a><span class="sep">/</span><b>unknown</b></div>
    <div class="empty"><b>User not found</b>It may have been removed.</div></div>`;
  const peers = Store.peersOfUser(id);

  return html`<div class="screen">
    <div class="crumb"><a href="#/users">Users</a><span class="sep">/</span><b>${u.name}</b></div>
    ${Store.storeConfigs ? html`<div class="notice warn posture"><${Ic} i="warn"/><span><b>store_configs is on.</b> Client private keys are kept on the panel host so these QR codes stay viewable. Turn it off in fleet.json to keep no secrets at rest.</span></div>` : null}

    <div class="detail-head">
      <div class="nameline"><h1>${u.name}</h1>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}<${Badge} s=${u.peerCount ? u.status : "empty"}/>
        <button class="editname" title="Edit" onClick=${() => setEdit(true)}><${Ic} i="pencil"/></button></div>
      <div class="grow"></div>
      <button class="btn btn-ghost" onClick=${() => openCreatePeer({ user_id: id })}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
      <${DangerButton} label="Delete user" confirm="Delete — peers go unassigned?" className="warn" onConfirm=${async () => {
        const r = await api.userDelete({ id }); if (!r.ok) { toast("Delete failed: " + (r.error || ""), "err"); return; }
        toast("User deleted; peers unassigned.", "ok"); await Store.poll(); go("#/users");
      }}/>
    </div>

    ${edit ? html`<${UserEditCard} user=${u} done=${() => setEdit(false)}/>` : html`<div class="identity">
      <div class="item"><div class="k">Tag</div><div class="v">${u.tag || "—"}</div></div>
      <div class="item"><div class="k">Note</div><div class="v">${u.note || "—"}</div></div>
      <div class="item"><div class="k">Peers</div><div class="v">${u.onlineCount}/${u.peerCount} online</div></div>
      <div class="item"><div class="k">Added</div><div class="v">${ago(u.created_at)}</div></div>
    </div>`}

    <div class="section-title"><h2>Peers</h2><span class="count">${peers.length}</span></div>
    ${peers.length ? peers.map(p => html`<${PeerCard} key=${p.id} peer=${p}/>`)
      : html`<div class="empty"><b>No peers yet</b>Mint a peer for ${u.name} — pick a server and interface.</div>`}
  </div>`;
}

function UserEditCard({ user, done }) {
  const [name, setName] = useState(user.name || "");
  const [tag, setTag] = useState(user.tag || "");
  const [note, setNote] = useState(user.note || "");
  const save = async () => {
    if (!name.trim()) { toast("Name can't be empty.", "err"); return; }
    const r = await api.userUpdate({ id: user.id, name: name.trim(), tag: tag.trim(), note });
    if (!r.ok) { toast("Save failed: " + (r.error || ""), "err"); return; }
    toast("Saved.", "ok"); await Store.poll(); done();
  };
  return html`<div class="card" style="max-width:560px">
    <div class="field"><label>Name</label><input value=${name} onInput=${e => setName(e.target.value)} maxlength="64"/></div>
    <div class="field"><label>Tag</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder="Friend, Family, Work…" maxlength="32"/></div>
    <div class="field"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="Uses iPhone and router" maxlength="200"/></div>
    <div style="display:flex;gap:8px;margin-top:6px"><button class="btn btn-primary" onClick=${save}>Save</button><button class="btn btn-ghost" onClick=${done}>Cancel</button></div>
  </div>`;
}

// one credential: its targets, each a QR card; plus add-target / reassign / delete
function PeerCard({ peer }) {
  return html`<div class="peercard">
    <div class="peercard-head">
      <span class="addr">${peer.pubkey.slice(0, 22)}…</span>
      <button class="copybtn" title="Copy public key" onClick=${() => copy(peer.pubkey, "Public key copied")}><${Ic} i="copy"/></button>
      <span class="grow"></span>
      <span class="assignwrap"><${AssignSelect} peer=${peer}/></span>
      <${DangerButton} label="Delete peer" confirm="Delete everywhere?" onConfirm=${async () => {
        const r = await api.peerDelete({ peer_id: peer.id }); if (!r.ok) { toast("Delete failed: " + (r.error || ""), "err"); return; }
        toast("Peer deleted.", "ok"); await Store.poll();
      }}/>
    </div>
    <div class="deploys">
      ${peer.targets.map(t => html`<${TargetCard} key=${tkey(t.node, t.iface)} peer=${peer} t=${t}/>`)}
      <div class="deploy adder" onClick=${() => openAddTarget(peer)}>
        <div class="inner"><div class="ring"><${Ic} i="plus"/></div><div>Copy to another interface</div><div class="faint" style="font-size:11px">same key · new endpoint</div></div>
      </div>
    </div>
  </div>`;
}

function TargetCard({ peer, t }) {
  const [conf, setConf] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { let ok = true; getConfig(peer.pubkey, t.node, t.iface).then(c => { if (ok) { setConf(c); setLoaded(true); } }); return () => { ok = false; }; }, [peer.pubkey, t.node, t.iface]);
  const col = Store.nodeColor(t.node);
  const obs = t.observed;
  const tps = turnProxiesFor(t.node, t.iface);
  const label = (peer.name || "peer") + " · " + t.node + "/" + t.iface;

  return html`<div class="deploy">
    <div class="deploy-head"><span class="dot" style=${{ background: col }}></span><span class="nm">${t.node} · ${t.iface}</span><span class="grow"></span><${Badge} s=${t.status}/></div>
    <div class="deploy-body">
      ${conf ? html`<${QR} conf=${conf} label=${label}/>`
        : html`<div class="qr-none">${loaded ? "config shown right after creation" + (Store.storeConfigs ? "" : ", or enable store_configs to keep it") : "loading…"}</div>`}
      <div class="dmeta">
        <div class="row"><span class="k">address</span><span class="vv">${t.ip || "—"}</span></div>
        <div class="row"><span class="k">handshake</span><span class="vv">${obs ? seen(obs.handshake_age) : "—"}</span></div>
        <div class="row"><span class="k">transfer</span><span class="vv">${obs ? "↓ " + rate(obs.rx_speed) + "  ↑ " + rate(obs.tx_speed) : "—"}</span></div>
        <div class="row"><span class="k">transport</span><span class="vv">${t.via === "turn" ? "via turn-proxy" : (t.via === "direct" ? "direct" : "—")}</span></div>
        ${tps.map(tp => html`<div class="row"><span class="k">turn-proxy</span><span class="vv">${tp.listen || "—"}
          ${tp.wrap_key ? html`<${Fragment}> · key <span class="addr">${String(tp.wrap_key).slice(0, 8)}…</span><button class="copybtn" title="Copy wrap key" onClick=${() => copy(tp.wrap_key, "Wrap key copied")}><${Ic} i="copy"/></button></>` : null}</span></div>`)}
      </div>
    </div>
    ${conf ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => downloadConf(conf, (peer.name || "peer") + "-" + t.node)}><${Ic} i="download"/> Config</button>
      <button class="btn btn-mini" onClick=${() => copy(conf, "Config copied")}><${Ic} i="copy"/> Copy</button>
      ${tps.length ? html`<button class="btn btn-mini" title="Import via turn-proxy" onClick=${() => qrZoom(turnConf(conf, tps[0].listen), label + " · turn-proxy")}>turn-proxy QR</button>` : null}
    </div>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: PEER DETAIL (single credential) ═════════════════════════
function PeerDetail({ id: rawId }) {
  useStore();
  const id = decodeURIComponent(rawId);
  const p = Store.peer(id);
  if (!p) return html`<div class="screen"><div class="crumb"><a href="#/users">Users</a><span class="sep">/</span><b>unknown</b></div>
    <div class="empty"><b>Peer not found</b>It may have been removed.</div></div>`;
  const u = p.user_id ? Store.user(p.user_id) : null;
  return html`<div class="screen">
    <div class="crumb">${u ? html`<${Fragment}><a href="#/users">Users</a><span class="sep">/</span><a href=${"#/user/" + encodeURIComponent(u.id)}>${u.name}</a><span class="sep">/</span><b>peer</b></>` : html`<${Fragment}><a href="#/users">Users</a><span class="sep">/</span><b>unassigned peer</b></>`}</div>
    <div class="detail-head"><div class="nameline"><h1>${p.name || "Unassigned peer"}</h1><${Badge} s=${p.unassigned ? "unassigned" : p.status}/></div></div>
    <${PeerCard} peer=${p}/>
  </div>`;
}

// ═════════════════════════ SCREEN: NODES ═════════════════════════
const SWATCHES = ["#34d399", "#22d3ee", "#e8c04b", "#f0913c", "#f0596b", "#c084e8", "#7dd3fc", "#a3e635"];
function NodesScreen() {
  useStore();
  const ns = Store.nodes || [];
  return html`<div class="screen">
    <div class="section-title" style="margin-top:6px"><h2>Nodes</h2><span class="count">${ns.length + (ns.length === 1 ? " server" : " servers")}</span><span class="grow"></span>
      <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> Add node</button></div>
    <div class="hint" style="margin:0 2px 16px;color:var(--faint);font-size:12px">
      Entry servers run <span class="mono">swg-noded</span>, which syncs to this panel over HTTPS — the node needs no inbound access. Add one here to get a one-time enrollment command.
    </div>
    ${!ns.length ? html`<div class="empty"><b>No nodes yet</b>Add your first entry server — you'll get a one-time command to run on it.</div>`
      : html`<div class="nodegrid">${ns.map(n => html`<${NodeCard} key=${n.name} n=${n}/>`)}</div>`}
  </div>`;
}
function NodeCard({ n }) {
  const st = n.status || "dangling";
  const stTxt = st === "online" ? "online" : (st === "offline" ? "offline" : "awaiting enroll");
  const sync = st === "dangling" ? "never connected" : (st === "online" ? "synced " + ago(n.last_seen) : "last seen " + ago(n.last_seen));
  const ifaces = (n.interfaces || []).length ? n.interfaces.join(", ") : "—";
  return html`<div class="ncard">
    <div class="ntop"><span class="nsw" style=${{ background: n.color || "#5f7569" }}></span><span class="nname">${n.name}</span><span class="grow"></span><span class="nstat ${st}">${stTxt}</span></div>
    <div class="nrows">
      <div class="nrow"><span class="l">Endpoint</span><span class="r">${n.endpoint_host || "—"}</span></div>
      <div class="nrow"><span class="l">Peers</span><span class="r">${n.peer_count || 0}</span></div>
      <div class="nrow"><span class="l">Throughput</span><span class="r"><span class="down">↓ ${rate(n.rx_speed)}</span> <span class="up">↑ ${rate(n.tx_speed)}</span></span></div>
      <div class="nrow"><span class="l">Interfaces</span><span class="r">${ifaces}</span></div>
      <div class="nrow"><span class="l">Sync</span><span class="r">${sync}</span></div>
    </div>
    <div class="nacts">
      <button class="btn-mini" onClick=${() => openNodeEdit(n)}>Edit</button>
      <button class="btn-mini warn" onClick=${() => openNodeRotate(n.name)}>Rotate token</button>
      <span style="flex:1"></span>
      <button class="btn-danger" onClick=${() => openNodeRemove(n)}>Remove</button>
    </div>
  </div>`;
}

// ═════════════════════════ SCREEN: ACCOUNT ═════════════════════════
function AccountScreen() {
  const [user, setUser] = useState("");
  const [cur, setCur] = useState(""); const [np, setNp] = useState(""); const [np2, setNp2] = useState("");
  const [msg, setMsg] = useState(null); const [enabled, setEnabled] = useState(true);
  useEffect(() => { api.account().then(r => { if (r.ok) { if (r.data.username) setUser(r.data.username); if (!r.data.auth_enabled) { setEnabled(false); setMsg({ ok: false, t: "This panel has no login configured — changes are disabled." }); } } }); }, []);
  const save = async () => {
    if (!user.trim()) return setMsg({ ok: false, t: "Username can't be empty." });
    if (!cur) return setMsg({ ok: false, t: "Enter your current password to confirm." });
    if (np && np !== np2) return setMsg({ ok: false, t: "New passwords don't match." });
    if (np && np.length < 8) return setMsg({ ok: false, t: "New password must be at least 8 characters." });
    setMsg({ ok: true, t: "Saving…" });
    const r = await api.accountSave({ username: user.trim(), current_password: cur, new_password: np });
    if (!r.ok) return setMsg({ ok: false, t: r.error || "Failed to update." });
    setMsg({ ok: true, t: "Updated. Reloading — sign in with your new credentials…" });
    setTimeout(() => location.reload(), 1400);
  };
  return html`<div class="screen">
    <div class="crumb"><b>Account</b></div>
    <div class="card" style="max-width:520px">
      <h3 style="margin:0 0 4px">Admin login</h3>
      <p class="hint" style="margin:0 0 18px">Change the panel username and password. Takes effect immediately — you'll be asked to sign in again.</p>
      ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
      <div class="field"><label>Username</label><input value=${user} onInput=${e => setUser(e.target.value)} autocomplete="username"/></div>
      <div class="field"><label>Current password</label><input type="password" value=${cur} onInput=${e => setCur(e.target.value)} autocomplete="current-password" placeholder="required to confirm changes"/></div>
      <div class="field"><label>New password</label><input type="password" value=${np} onInput=${e => setNp(e.target.value)} autocomplete="new-password" placeholder="leave blank to keep current"/></div>
      <div class="field"><label>Confirm new password</label><input type="password" value=${np2} onInput=${e => setNp2(e.target.value)} autocomplete="new-password"/></div>
      <div style="margin-top:8px"><button class="btn btn-primary" disabled=${!enabled} onClick=${save}>Save changes</button></div>
    </div>
  </div>`;
}

// ═════════════════════════ MODALS / SHEETS ═════════════════════════
function Sheet({ title, children, foot }) {
  return html`<div class="overlay show" onClick=${e => { if (e.target.classList.contains("overlay")) closeModal(); }}>
    <div class="sheet" role="dialog" aria-modal="true">
      <div class="sheet-head"><h3>${title}</h3><button class="x" onClick=${closeModal}>×</button></div>
      <div class="sheet-body">${children}</div>
      <div class="sheet-foot">${foot}</div>
    </div></div>`;
}

// New user
function openCreateUser() { openModal(html`<${CreateUserSheet}/>`); }
function CreateUserSheet() {
  const [name, setName] = useState(""); const [tag, setTag] = useState(""); const [note, setNote] = useState(""); const [msg, setMsg] = useState(null);
  const create = async () => {
    if (!name.trim()) return setMsg({ k: "err", t: "Give the user a name." });
    setMsg({ k: "work", t: "creating…" });
    const r = await api.userCreate({ name: name.trim(), tag: tag.trim(), note });
    if (!r.ok) return setMsg({ k: "err", t: r.error || "couldn't create user" });
    Store.recentlyCreated[r.data.id] = Date.now();
    toast("User created.", "ok"); closeModal(); await Store.poll(); go("#/user/" + encodeURIComponent(r.data.id));
  };
  return html`<${Sheet} title="New user"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${create}>Create user</button></>`}>
    <div class="field"><label>Name</label><input autofocus value=${name} onInput=${e => setName(e.target.value)} placeholder="Alex"/></div>
    <div class="field"><label>Tag</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder="Friend"/></div>
    <div class="field"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="Uses iPhone and router"/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// New peer (mint a fresh keypair) — optionally pre-bound to a user / node / iface
function openCreatePeer(prefill) { openModal(html`<${CreatePeerSheet} prefill=${prefill || {}}/>`); }
function CreatePeerSheet({ prefill }) {
  const [cache, setCache] = useState({});           // node -> describe data
  const [ready, setReady] = useState(false);
  const [iface, setIface] = useState(prefill.iface || "");
  const [node, setNode] = useState(prefill.node || "");
  const [ip, setIp] = useState(""); const [ipHint, setIpHint] = useState("");
  const [psk, setPsk] = useState(genPSK());
  const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const [adv, setAdv] = useState(false);
  const [userId, setUserId] = useState(prefill.user_id || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMsg({ k: "work", t: "reading servers…" });
    Promise.all(Store.fleet.map(n => api.describe(n.name).then(r => r.ok ? [n.name, r.data] : null).catch(() => null)))
      .then(rs => {
        const c = {}; rs.forEach(x => { if (x) c[x[0]] = x[1]; }); setCache(c); setReady(true); setMsg(null);
        const ifset = new Set(); Object.values(c).forEach(d => Object.keys(d.interfaces || {}).forEach(i => ifset.add(i)));
        const list = Array.from(ifset);
        if (!list.length) { setMsg({ k: "err", t: "No servers reachable." }); return; }
        const wantIf = (prefill.iface && list.includes(prefill.iface)) ? prefill.iface : list[0];
        setIface(wantIf);
      });
  }, []);

  const nodesWithIface = useMemo(() => Store.fleet.filter(n => cache[n.name] && (cache[n.name].interfaces || {})[iface]).map(n => n.name), [cache, iface]);
  const ifaceList = useMemo(() => { const s = new Set(); Object.values(cache).forEach(d => Object.keys(d.interfaces || {}).forEach(i => s.add(i))); return Array.from(s); }, [cache]);

  // once iface known, default the node and fetch a free ip
  useEffect(() => {
    if (!ready || !iface) return;
    let n = node;
    if (!n || !nodesWithIface.includes(n)) { n = nodesWithIface[0] || ""; setNode(n); }
    if (!n) { setIp(""); setIpHint("No server offers " + iface + "."); return; }
    setIp(""); setIpHint("finding a free address on " + n + "…");
    api.nextIp([n], iface).then(r => { if (r.ok) { setIp(r.data.next_ip); setIpHint("Next free address" + (r.data.subnet ? " · " + r.data.subnet : "") + "."); } else { setIp(""); setIpHint(r.error || "couldn't pick an address"); } });
  }, [ready, iface, node]);

  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));

  const create = async () => {
    if (!node) return setMsg({ k: "err", t: "Pick a server." });
    if (!ip.trim()) return setMsg({ k: "err", t: "No address — check server reachability." });
    setBusy(true); setMsg({ k: "work", t: "generating keys…" });
    try {
      const info = (cache[node].interfaces || {})[iface];
      const keys = await genKeys();
      const ipClean = ip.trim();
      const conf = buildConf({ privkey: keys.priv, address: ipClean, dns: info.dns, awg_params: info.awg_params, server_pubkey: info.public_key, psk: psk.trim(), endpoint: info.endpoint, allowed: allowed.trim() || "0.0.0.0/0, ::/0" });
      setMsg({ k: "work", t: "creating on " + node + "…" });
      const body = { user_id: userId || null, pubkey: keys.pub, psk: psk.trim(), target: { node, iface, ip: ipClean.split("/")[0], type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" } };
      if (Store.storeConfigs) body.config = conf;
      const r = await api.peerCreate(body);
      if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: "Failed: " + (r.error || r.code || "unknown") }); }
      (Store.sessionConfigs[keys.pub] = Store.sessionConfigs[keys.pub] || {})[tkey(node, iface)] = conf;
      Store.recentlyCreated[r.data.id] = Date.now();
      toast("Peer created on " + node + "/" + iface + ".", "ok");
      closeModal(); await Store.poll();
      go(userId ? "#/user/" + encodeURIComponent(userId) : "#/peer/" + encodeURIComponent(r.data.id));
    } catch (e) { setBusy(false); setMsg({ k: "err", t: "Error: " + e.message }); }
  };

  return html`<${Sheet} title="New peer"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${create}>Create peer</button></>`}>
    <div class="field"><label>User</label>
      <select class="selwrap" value=${userId} onChange=${e => setUserId(e.target.value)}>
        <option value="">— unassigned —</option>
        ${users.map(u => html`<option value=${u.id}>${u.name}${u.tag ? " · " + u.tag : ""}</option>`)}
      </select></div>
    <div class="field"><label>Interface</label>
      <select class="selwrap" value=${iface} onChange=${e => setIface(e.target.value)}>
        ${ifaceList.length ? ifaceList.map(i => html`<option value=${i}>${i}</option>`) : html`<option>…</option>`}
      </select></div>
    <div class="field"><label>Server</label>
      <select class="selwrap" value=${node} onChange=${e => setNode(e.target.value)}>
        ${nodesWithIface.length ? nodesWithIface.map(n => html`<option value=${n}>${n}</option>`) : html`<option value="">no server offers ${iface}</option>`}
      </select></div>
    <div class="field"><label>Address</label><input value=${ip} onInput=${e => setIp(e.target.value)} placeholder="auto"/><div class="hint">${ipHint}</div></div>
    <div class="field"><label>Preshared key</label><div class="inline"><input value=${psk} onInput=${e => setPsk(e.target.value)}/><button class="btn btn-ghost" title="Regenerate" onClick=${() => { setPsk(genPSK()); toast("New preshared key.", "info", 1500); }}>↻</button></div></div>
    <button class="advtoggle" onClick=${() => setAdv(a => !a)}><span>${adv ? "▾" : "▸"}</span> Advanced</button>
    ${adv ? html`<div class="adv open"><div class="field" style="margin-top:8px"><label>Client allowed IPs (routing)</label>
      <input value=${allowed} onInput=${e => setAllowed(e.target.value)}/><div class="hint">Full tunnel by default. Narrow for split tunnel (e.g. a router peer).</div></div></div>` : null}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// Copy peer interface→interface (same key + PSK, new target). Needs the client's
// private key (session config, or stored) to build the new client config / QR.
function openAddTarget(peer) { openModal(html`<${AddTargetSheet} peer=${peer}/>`); }
function AddTargetSheet({ peer }) {
  const [cache, setCache] = useState({});
  const [iface, setIface] = useState(""); const [node, setNode] = useState("");
  const [ip, setIp] = useState(""); const [ipHint, setIpHint] = useState("");
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const srcConf = anySessionConf(peer.pubkey);

  useEffect(() => {
    Promise.all(Store.fleet.map(n => api.describe(n.name).then(r => r.ok ? [n.name, r.data] : null).catch(() => null)))
      .then(rs => { const c = {}; rs.forEach(x => { if (x) c[x[0]] = x[1]; }); setCache(c); });
  }, []);

  const have = new Set(peer.targets.map(t => tkey(t.node, t.iface)));
  const ifaceList = useMemo(() => { const s = new Set(); Object.values(cache).forEach(d => Object.keys(d.interfaces || {}).forEach(i => s.add(i))); return Array.from(s); }, [cache]);
  const nodesWithIface = useMemo(() => Store.fleet.filter(n => cache[n.name] && (cache[n.name].interfaces || {})[iface] && !have.has(tkey(n.name, iface))).map(n => n.name), [cache, iface]);

  useEffect(() => { if (!ifaceList.length) return; if (!iface) setIface(ifaceList[0]); }, [ifaceList]);
  useEffect(() => {
    if (!iface) return;
    const n = nodesWithIface.includes(node) ? node : (nodesWithIface[0] || "");
    if (n !== node) setNode(n);
    if (!n) { setIp(""); setIpHint("No free server for " + iface + "."); return; }
    setIp(""); setIpHint("finding a free address on " + n + "…");
    api.nextIp([n], iface).then(r => { if (r.ok) { setIp(r.data.next_ip); setIpHint("Next free address."); } else { setIp(""); setIpHint(r.error || "couldn't pick an address"); } });
  }, [iface, node, cache]);

  const deploy = async () => {
    if (!node) return setMsg({ k: "err", t: "Pick a server." });
    if (!ip.trim()) return setMsg({ k: "err", t: "No address available." });
    setBusy(true); setMsg({ k: "work", t: "deploying to " + node + "…" });
    const info = (cache[node].interfaces || {})[iface];
    const ipClean = ip.trim().split("/")[0];
    let conf = null;
    if (srcConf) { const { priv, psk } = parseConf(srcConf); conf = buildConf({ privkey: priv, address: ipClean + "/32", dns: info.dns, awg_params: info.awg_params, server_pubkey: info.public_key, psk: psk || peer.psk, endpoint: info.endpoint, allowed: "0.0.0.0/0, ::/0" }); }
    const body = { peer_id: peer.id, target: { node, iface, ip: ipClean, type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" } };
    if (Store.storeConfigs && conf) body.config = conf;
    const r = await api.peerAddTarget(body);
    if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: "Failed: " + (r.error || r.code || "") }); }
    if (conf) (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(node, iface)] = conf;
    toast("Copied to " + node + "/" + iface + ".", "ok"); closeModal(); await Store.poll();
  };

  return html`<${Sheet} title=${"Copy peer to another interface"}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${deploy}>Deploy</button></>`}>
    ${!srcConf ? html`<div class="notice warn"><${Ic} i="warn"/><span>The client's private key isn't in this session, so a fresh QR can't be shown for the copy${Store.storeConfigs ? "" : " (enable store_configs, or copy right after creating)"}. The target is still added with the same key + PSK.</span></div>` : null}
    <div class="field"><label>Interface</label>
      <select class="selwrap" value=${iface} onChange=${e => setIface(e.target.value)}>
        ${ifaceList.length ? ifaceList.map(i => html`<option value=${i}>${i}</option>`) : html`<option>…</option>`}
      </select></div>
    <div class="field"><label>Server</label>
      <select class="selwrap" value=${node} onChange=${e => setNode(e.target.value)}>
        ${nodesWithIface.length ? nodesWithIface.map(n => html`<option value=${n}>${n}</option>`) : html`<option value="">none available for ${iface}</option>`}
      </select></div>
    <div class="field"><label>Address</label><input value=${ip} onInput=${e => setIp(e.target.value)}/><div class="hint">${ipHint}</div></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── node sheets ──
function SwatchPicker({ value, onChange }) {
  return html`<div class="swrow">${SWATCHES.map(c => html`<div class=${"swopt " + (c === value ? "sel" : "")} style=${{ background: c }} onClick=${() => onChange(c)}></div>`)}</div>`;
}
function openNodeCreate() { openModal(html`<${NodeCreateSheet}/>`); }
function NodeCreateSheet() {
  const [name, setName] = useState(""); const [ep, setEp] = useState(""); const [color, setColor] = useState(SWATCHES[0]); const [msg, setMsg] = useState(null);
  const create = async () => {
    if (!name.trim()) return setMsg({ k: "err", t: "Give the node a name." });
    setMsg({ k: "work", t: "creating…" });
    const r = await api.nodeCreate({ name: name.trim(), endpoint_host: ep.trim(), color });
    if (!r.ok) return setMsg({ k: "err", t: r.error || "couldn't create node" });
    await Store.poll(); openModal(html`<${NodeTokenSheet} name=${r.data.name} token=${r.data.token} isNew=${true}/>`);
  };
  return html`<${Sheet} title="Add node"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${create}>Create node</button></>`}>
    <div class="field"><label>Name</label><input autofocus value=${name} onInput=${e => setName(e.target.value)} placeholder="msk-edge1" autocomplete="off"/><div class="hint">Letters, digits, - or _. Used as the node's id across the panel.</div></div>
    <div class="field"><label>Public endpoint (host or IP)</label><input value=${ep} onInput=${e => setEp(e.target.value)} placeholder="203.0.113.7" autocomplete="off"/><div class="hint">The address clients dial to reach this node. You can change it later.</div></div>
    <div class="field"><label>Colour</label><${SwatchPicker} value=${color} onChange=${setColor}/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
const BOOTSTRAP_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh";
function NodeTokenSheet({ name, token, isNew }) {
  const host = `${location.origin}${BASE}`;
  const bare = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s node -key ${token} -host ${host}`;
  const docker = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s docker node -key ${token} -host ${host}`;
  return html`<${Sheet} title=${(isNew ? "Node created" : "New token") + " · " + name}
    foot=${html`<button class="btn btn-primary" onClick=${closeModal}>Done</button>`}>
    <div class="notice warn"><${Ic} i="warn"/><span><b>Shown once.</b> This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.</span></div>
    <div class="field" style="margin-top:15px"><label>Enrollment token</label><div class="cmdrow"><div class="tokenbox">${token}</div><button class="copyaction" onClick=${() => copy(token, "Copied")}><${Ic} i="copy"/> Copy</button></div></div>
    <div class="field"><label>Run on the node — <span style="color:#60a5fa;font-weight:700">bare-metal</span></label><div class="cmdrow"><div class="tokenbox">${bare}</div><button class="copyaction" onClick=${() => copy(bare, "Copied")}><${Ic} i="copy"/> Copy</button></div></div>
    <div class="field"><label>Run on the node — <span style="color:#c084e8;font-weight:700">docker</span></label><div class="cmdrow"><div class="tokenbox">${docker}</div><button class="copyaction" onClick=${() => copy(docker, "Copied")}><${Ic} i="copy"/> Copy</button></div>
      <div class="hint">Pick one. Both fetch the installer and prompt for the node's endpoint. The node appears once it syncs.</div></div>
  <//>`;
}
function openNodeEdit(node) { openModal(html`<${NodeEditSheet} node=${node}/>`); }
function NodeEditSheet({ node }) {
  const [ep, setEp] = useState(node.endpoint_host || ""); const [color, setColor] = useState(node.color || SWATCHES[0]); const [msg, setMsg] = useState(null);
  const save = async () => {
    const r = await api.nodeUpdate({ name: node.name, endpoint_host: ep.trim(), color });
    if (!r.ok) return setMsg({ k: "err", t: r.error || "save failed" });
    toast("Saved.", "ok"); closeModal(); await Store.poll();
  };
  return html`<${Sheet} title=${"Edit " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${save}>Save</button></>`}>
    <div class="field"><label>Public endpoint (host or IP)</label><input value=${ep} onInput=${e => setEp(e.target.value)} autocomplete="off"/></div>
    <div class="field"><label>Colour</label><${SwatchPicker} value=${color} onChange=${setColor}/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
function openNodeRotate(name) { openModal(html`<${NodeRotateSheet} name=${name}/>`); }
function NodeRotateSheet({ name }) {
  const go2 = async () => { const r = await api.nodeRotate({ name }); if (!r.ok) { toast(r.error || "rotate failed", "err"); return; } openModal(html`<${NodeTokenSheet} name=${name} token=${r.data.token} isNew=${false}/>`); };
  return html`<${Sheet} title=${"Rotate token · " + name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${go2}>Rotate</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>The current token stops working immediately. Re-enroll the node with the new token or it will go offline.</span></div>
  <//>`;
}
function openNodeRemove(node) { openModal(html`<${NodeRemoveSheet} node=${node}/>`); }
function NodeRemoveSheet({ node }) {
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === node.name));
  const onlyHere = here.filter(p => new Set(p.targets.map(t => t.node)).size === 1).length;
  const note = here.length ? `It's referenced by ${here.length} peer${here.length > 1 ? "s" : ""}${onlyHere ? ` — ${onlyHere} live only here and will be dropped from the roster` : ""}.` : "No peers reference it.";
  const go2 = async () => { const r = await api.nodeDelete({ name: node.name }); if (!r.ok) { toast(r.error || "remove failed", "err"); return; } toast("Node removed.", "ok"); closeModal(); await Store.poll(); };
  return html`<${Sheet} title=${"Remove " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-danger" onClick=${go2}>Remove node</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>Removes the node from the panel and revokes its token. ${note} The node keeps running until you stop <span class="mono">swg-noded</span> on it.</span></div>
  <//>`;
}

// ═════════════════════════ ROUTER + APP ═════════════════════════
const ROUTES = [
  { re: /^\/$/, fn: Overview, tab: "overview" },
  { re: /^\/node\/(.+)$/, fn: NodeDetail, tab: "overview", keys: ["node"] },
  { re: /^\/nodes$/, fn: NodesScreen, tab: "nodes" },
  { re: /^\/peers$/, fn: PeersScreen, tab: "peers" },
  { re: /^\/users$/, fn: UsersScreen, tab: "users" },
  { re: /^\/user\/(.+)$/, fn: UserDetail, tab: "users", keys: ["id"] },
  { re: /^\/peer\/(.+)$/, fn: PeerDetail, tab: "users", keys: ["id"] },
  { re: /^\/account$/, fn: AccountScreen, tab: "account" },
];
function go(hash) { location.hash = hash; }
function matchRoute(hash) {
  const path = (hash || "#/").replace(/^#/, "") || "/";
  for (const r of ROUTES) { const m = path.match(r.re); if (m) { const params = {}; (r.keys || []).forEach((k, i) => params[k] = m[i + 1]); return { route: r, params }; } }
  return { route: ROUTES[0], params: {} };
}

function App() {
  useStore();                                   // re-render on every poll
  const [hash, setHash] = useState(location.hash || "#/");
  const [modal, setModalState] = useState(null);
  useEffect(() => { _setModal = setModalState; }, []);
  useEffect(() => {
    const onHash = () => { setHash(location.hash || "#/"); setModalState(null); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onHash);
    const onKey = e => { if (e.key === "Escape") setModalState(null); };
    document.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("hashchange", onHash); document.removeEventListener("keydown", onKey); };
  }, []);

  const { route, params } = matchRoute(hash);

  // static chrome lives in index.html — keep it in sync imperatively
  useEffect(() => {
    const online = Store.recon.peers.filter(p => p.online).length;
    const kpi = $("#kpi-online"); if (kpi) kpi.textContent = online;
    const v = Store.versions || {}, el = $("#appver");
    if (el && v.panel) {
      const tools = ["awg", "wg", "docker"].filter(k => v[k]).map(k => k + " " + v[k]);
      el.innerHTML = `<b>${esc(v.panel)}</b>` + (tools.length ? `<span class="tools"> · ${esc(tools.join(" · "))}</span>` : "");
    }
    $$("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === route.tab));
    const add = $("#add-peer-btn"); if (add) add.onclick = () => openCreatePeer({});
  });

  return html`<${Fragment}>
    ${h(route.fn, params)}
    ${modal}
  <//>`;
}

// ───────────────────────── boot ─────────────────────────
const viewEl = $("#view");
viewEl.innerHTML = `<div class="loading"><span class="spin"></span>connecting…</div>`;
(async () => {
  try { await Store.init(); }
  catch (e) { viewEl.innerHTML = `<div class="empty"><b>Can't reach the panel</b>${esc(e.message)}</div>`; return; }
  if (!location.hash) location.hash = "#/";
  render(h(App), viewEl);
})();
