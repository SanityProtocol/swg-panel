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
// turn-proxy display label: strip the vk-turn-proxy- prefix and render as name:port (a "-NNNN"
// suffix in the service name becomes ":NNNN"; otherwise the listen port is appended).
function turnLabel(service, port) {
  let s = (service || "turn-proxy").replace(/^vk-turn-proxy-?/, "") || "turn";
  if (/-\d+$/.test(s)) return s.replace(/-(\d+)$/, ":$1");
  return port ? s + ":" + port : s;
}

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

// ── validation for fields that affect connectivity / data-structure ──
const V = {
  ipv4: s => { const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(String(s).trim()); return !!m && m.slice(1).every(o => +o >= 0 && +o <= 255 && (o === "0" || o[0] !== "0")); },
  ipv6: s => { s = String(s).trim(); if (!/^[0-9a-fA-F:]+$/.test(s) || (s.match(/::/g) || []).length > 1) return false; const parts = s.split("::"); const segs = s.includes("::") ? parts.join(":").split(":").filter(Boolean) : s.split(":"); return s.includes("::") ? segs.length <= 7 : segs.length === 8 && segs.every(x => /^[0-9a-fA-F]{1,4}$/.test(x)); },
  ip: s => V.ipv4(s) || V.ipv6(s),
  cidr: s => { s = String(s).trim(); const i = s.indexOf("/"); if (i < 0) return V.ip(s); const a = s.slice(0, i), n = s.slice(i + 1); if (!/^\d+$/.test(n)) return false; if (V.ipv4(a)) return +n >= 0 && +n <= 32; if (V.ipv6(a)) return +n >= 0 && +n <= 128; return false; },
  host: s => { s = String(s).trim(); return s.length > 0 && s.length <= 253 && /^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$/.test(s); },
  hostOrIp: s => V.ipv4(s) || V.ipv6(s) || V.host(s),
  nodeName: s => /^[A-Za-z0-9_-]{1,40}$/.test(String(s).trim()),
  mtu: s => /^\d+$/.test(String(s).trim()) && +s >= 1280 && +s <= 9200,
  keepalive: s => /^\d+$/.test(String(s).trim()) && +s >= 0 && +s <= 65535,
  psk: s => /^[A-Za-z0-9+/]{43}=$/.test(String(s).trim()),               // 32-byte base64
  list: (s, f) => String(s).split(",").map(x => x.trim()).filter(Boolean).every(f),
};
// connectivity-config field errors (DNS / MTU / keepalive / AllowedIPs) → { field: message }
function configErrors(cf) {
  const e = {};
  if (cf.allowed.trim() && !V.list(cf.allowed, V.cidr)) e.allowed = "Comma-separated CIDRs, e.g. 0.0.0.0/0, ::/0";
  else if (!cf.allowed.trim()) e.allowed = "Required (use 0.0.0.0/0, ::/0 for full tunnel).";
  if (cf.dns.trim() && !V.list(cf.dns, V.ip)) e.dns = "Each DNS must be a valid IP.";
  if (cf.mtu.trim() && !V.mtu(cf.mtu)) e.mtu = "MTU must be a number 1280–9200.";
  if (cf.keepalive.trim() && !V.keepalive(cf.keepalive)) e.keepalive = "Keepalive must be 0–65535.";
  return e;
}
function fmtBytes(n) {
  n = n || 0;
  const u = ["B", "K", "M", "G", "T"]; let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)) + u[i];
}
function dur(sec) {
  if (sec == null) return "—";
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d) return d + "d " + h + "h";
  if (h) return h + "h " + m + "m";
  if (m) return m + "m";
  return sec + "s";
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
  server: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="4" width="18" height="7" rx="1.6"/><rect x="3" y="13" width="18" height="7" rx="1.6"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>',
  network: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="19" r="2.2"/><path d="M12 7.2v3.3M12 10.5 6.2 17M12 10.5 17.8 17"/></svg>',
  key: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="8" cy="15" r="4"/><path d="M10.9 12.1 21 2m-4 1 2.4 2.4M14 5l2.4 2.4"/></svg>',
  shield: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M12 3l7.5 3.2v5C19.5 16 16.4 19 12 21 7.6 19 4.5 16 4.5 11.2v-5z"/></svg>',
  activity: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  users: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1"/><circle cx="9" cy="7" r="3.4"/><path d="M22 19v-1a4 4 0 0 0-3-3.85M16 3.2a4 4 0 0 1 0 7.6"/></svg>',
  user: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M19 20v-1a5 5 0 0 0-5-5h-4a5 5 0 0 0-5 5v1"/><circle cx="12" cy="7" r="4"/></svg>',
  device: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="3" width="10" height="18" rx="2.4"/><path d="M11 18h2"/></svg>',
  cpu: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="7" width="10" height="10" rx="1.6"/><path d="M9 1.5v3M15 1.5v3M9 19.5v3M15 19.5v3M1.5 9h3M1.5 15h3M19.5 9h3M19.5 15h3"/></svg>',
  disk: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5.2 13 7.5 5h9l2.3 8M7 16.5h.01"/></svg>',
  clock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5l3.2 2"/></svg>',
  relay: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="2"/><path d="M8.2 8.2a5.4 5.4 0 0 0 0 7.6M15.8 15.8a5.4 5.4 0 0 0 0-7.6M5.4 5.4a9.4 9.4 0 0 0 0 13.2M18.6 18.6a9.4 9.4 0 0 0 0-13.2"/></svg>',
  globe: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/></svg>',
  bolt: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
  gauge: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 13.5 16 9"/><path d="M4 18a9 9 0 1 1 16 0"/></svg>',
  gear: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 13a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V20a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.6 13H4.5a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.1V2a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-1.1 2.7v.1a2 2 0 1 1 0 4z"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/></svg>',
  link: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M10 13a4 4 0 0 0 6 .5l2-2a4 4 0 0 0-5.7-5.7l-1.2 1.1M14 11a4 4 0 0 0-6-.5l-2 2A4 4 0 0 0 11.7 18l1.2-1.1"/></svg>',
  qr: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.2"/><rect x="14" y="3" width="7" height="7" rx="1.2"/><rect x="3" y="14" width="7" height="7" rx="1.2"/><path d="M14 14h3v3M21 14v3M17 21h4M14 21h.01M21 21v.01M17 17h.01"/></svg>',
};
const Ic = ({ i }) => html`<span class="ic" dangerouslySetInnerHTML=${{ __html: ICON[i] || "" }}></span>`;

// A titled, icon-headed group panel — the primary way related info is clustered
// (server details / health / vitals / config). tone tints the icon square.
function Panel({ icon, title, count, actions, tone, children, pad }) {
  return html`<section class="panel">
    <div class="panel-head">
      ${icon ? html`<span class=${"panel-ic" + (tone ? " t-" + tone : "")}><${Ic} i=${icon}/></span>` : null}
      <h3>${title}</h3>${count != null ? html`<span class="panel-count">${count}</span>` : null}
      <span class="grow"></span>${actions || null}
    </div>
    <div class=${"panel-body" + (pad === false ? " flush" : "")}>${children}</div>
  </section>`;
}

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
  L.push("AllowedIPs = " + (o.allowed || "0.0.0.0/0, ::/0"), "Endpoint = " + o.endpoint,
    "PersistentKeepalive = " + (o.keepalive != null && o.keepalive !== "" ? o.keepalive : 25));
  return L.join("\n") + "\n";
}
function parseConf(text) {
  const priv = (text.match(/PrivateKey\s*=\s*(\S+)/) || [])[1] || null;
  const psk = (text.match(/PresharedKey\s*=\s*(\S+)/) || [])[1] || null;
  return { priv, psk };
}
// Full parse of a client config back into buildConf()'s shape — so an edit/copy can
// rebuild the config from the existing one (the only place the private key lives).
function parseFullConf(text) {
  const m = re => (text.match(re) || [])[1];
  const dnsLine = m(/DNS\s*=\s*(.+)/);
  const awg = {};
  for (const k of AWG_ORDER) { const v = m(new RegExp("^" + k + "\\s*=\\s*(\\S+)", "m")); if (v != null) awg[k] = v; }
  return {
    privkey: m(/PrivateKey\s*=\s*(\S+)/) || "",
    address: m(/Address\s*=\s*(.+)/) || "",
    dns: dnsLine ? dnsLine.split(",").map(s => s.trim()).filter(Boolean) : [],
    mtu: m(/MTU\s*=\s*(\d+)/) || 1280,
    awg_params: awg,
    server_pubkey: m(/PublicKey\s*=\s*(\S+)/) || "",
    psk: m(/PresharedKey\s*=\s*(\S+)/) || "",
    allowed: m(/AllowedIPs\s*=\s*(.+)/) || "0.0.0.0/0, ::/0",
    endpoint: m(/Endpoint\s*=\s*(\S+)/) || "",
    keepalive: m(/PersistentKeepalive\s*=\s*(\d+)/) || 25,
  };
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
  async get(p) { const r = await fetch(url(p)); if (r.status === 401) return require401(); return r.json(); },
  async post(p, b) { const r = await fetch(url(p), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }); if (r.status === 401 && !/\/api\/login$/.test(p)) return require401(); return r.json(); },
  login(b) { return this.post("/api/login", b); },
  logout() { return this.post("/api/logout", {}); },
  state() { return this.get("/api/state"); },
  events(limit) { return this.get("/api/events?limit=" + (limit || 12)); },
  nodeHistory(node, range) { return this.get("/api/node-history?node=" + encodeURIComponent(node) + "&range=" + encodeURIComponent(range)); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  nodeRotate(b) { return this.post("/api/nodes/rotate", b); },
  nodeFlagRemove(b) { return this.post("/api/nodes/flag-remove", b); },
  nodeDelete(b) { return this.post("/api/nodes/delete", b); },
  // users
  userCreate(b) { return this.post("/api/users/create", b); },
  userUpdate(b) { return this.post("/api/users/update", b); },
  userDelete(b) { return this.post("/api/users/delete", b); },
  // peers
  peerCreate(b) { return this.post("/api/peers/create", b); },
  peerUpdate(b) { return this.post("/api/peers/update", b); },
  peerAddTarget(b) { return this.post("/api/peers/add-target", b); },
  peerUpdateTarget(b) { return this.post("/api/peers/update-target", b); },
  peerRemoveTarget(b) { return this.post("/api/peers/remove-target", b); },
  peerDelete(b) { return this.post("/api/peers/delete", b); },
  peerUnassign(b) { return this.post("/api/peers/unassign", b); },
  peerRekey(b) { return this.post("/api/peers/rekey", b); },
  peerAdopt(b) { return this.post("/api/peers/adopt", b); },
  peerSaveConfig(b) { return this.post("/api/peers/save-config", b); },
  ifaceUpdate(b) { return this.post("/api/iface/update", b); },
};

// ───────────────────────── store + reactive bus ─────────────────────────
const bus = { subs: new Set(), emit() { this.subs.forEach(f => { try { f(); } catch (e) { console.error(e); } }); }, sub(f) { this.subs.add(f); return () => this.subs.delete(f); } };
function useStore() { const [, set] = useState(0); useEffect(() => bus.sub(() => set(x => x + 1)), []); }

const Store = {
  fleet: [], storeConfigs: false, env: {}, versions: {},
  roster: { version: 1, users: {}, peers: {} }, stats: {}, nodes: [], describe: {}, events: [],
  recon: { peers: [], users: [], orphans: [], nodeStatus: {} },
  sessionConfigs: {},        // pubkey -> { "node|iface" -> confText }   (built at creation, in-memory)
  configEpoch: 0,            // bumps when a config is re-issued, so QR cards re-read it
  recentlyCreated: {},       // id -> ts (row flash)
  pending: {},               // opId -> { apply(store), done }  — optimistic overlay (Model B)
  rowErrors: {},             // entityKey -> { msg, at }        — explained failure, shown on the row
  async init() {
    await this.poll();
    setInterval(() => this.poll().catch(() => {}), 5000);
  },
  // One round trip: /api/state bundles roster + nodes (incl. health_history) + per-node
  // interface meta + raw snapshots. Status is still derived in the browser via reconcile.js.
  _server: { roster: { version: 1, users: {}, peers: {} }, nodes: [] },   // pristine, last fetched
  async poll() {
    const [s, ev] = await Promise.all([api.state(), api.events().catch(() => null)]);
    const d = (s && s.data) || {};
    this._server = { roster: d.roster || { version: 1, users: {}, peers: {} }, nodes: d.nodes || [] };
    this.describe = d.describe || {};
    this.stats = d.snapshots || {};
    this.storeConfigs = !!d.store_configs;
    this.env = d.env || this.env || {};
    this.versions = d.versions || this.versions;
    if (ev && Array.isArray(ev.data)) this.events = ev.data;
    this.apply();
  },
  // Re-derive everything the UI reads from a PRISTINE copy of server data + the optimistic
  // overlay. Confirmed ops (done) are dropped first — fresh server data already reflects them
  // — then still-pending patches are layered on a fresh clone, so re-applying is idempotent and
  // an in-flight change never blinks out between polls.
  apply() {
    for (const id of Object.keys(this.pending)) if (this.pending[id].done) delete this.pending[id];
    const snap = (typeof structuredClone === "function") ? structuredClone(this._server)
                                                         : JSON.parse(JSON.stringify(this._server));
    this.roster = snap.roster; this.nodes = snap.nodes;
    for (const id of Object.keys(this.pending)) { try { this.pending[id].apply(this); } catch (_) {} }
    // fleet entries carry the stable id (the connector everywhere) + the mutable name (display)
    this.fleet = this.nodes.map(n => ({ id: n.id, name: n.name, color: n.color, transport: "https" }));
    this.recon = reconcile(this.roster, this.stats, Date.now());
    bus.emit();
  },
  node(id) { return this.fleet.find(n => n.id === id); },              // lookup by stable id
  nodeName(id) { const n = this.node(id); return (n && n.name) || id; }, // display title (falls back to id)
  nodeColor(id) { const n = this.node(id); return (n && n.color) || "#5f7569"; },
  ifacesOf(node) { return Object.keys(this.describe[node] || {}); },   // node = id (describe keyed by id)
  ifaceMeta(node, iface) { return (this.describe[node] || {})[iface] || null; },
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
// Resolve a peer's config and RE-RENDER it on the fly: client-side fields (private key, address,
// DNS, MTU, AllowedIPs, keepalive, PSK) come from the stored/session source, but the server-facing
// fields (Endpoint, server PublicKey, AmneziaWG params) are rebuilt from the CURRENT interface
// metadata — so an interface endpoint change shows up in every config/QR without a re-issue.
function rerenderConf(text, node, iface) {
  if (!text) return text;
  const meta = Store.ifaceMeta(node, iface);
  if (!meta || !meta.public_key) return text;
  const c = parseFullConf(text);
  if (!c.privkey) return text;
  return buildConf({ privkey: c.privkey, address: c.address, dns: c.dns, mtu: c.mtu,
    awg_params: meta.awg_params, server_pubkey: meta.public_key, psk: c.psk,
    endpoint: meta.endpoint, allowed: c.allowed, keepalive: c.keepalive });
}
function getConfig(pubkey, node, iface) {
  const s = Store.sessionConfigs[pubkey];
  if (s && s[tkey(node, iface)]) return Promise.resolve(rerenderConf(s[tkey(node, iface)], node, iface));
  if (Store.storeConfigs) return api.config(pubkey, node, iface).then(r => rerenderConf(r.ok ? r.data.config : null, node, iface)).catch(() => null);
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

// ───────────────────────── mutations (optimistic, status-on-failure) ─────────────────────────
//
// Single funnel for every write. The optimistic `patch` (if given) is applied to the store
// immediately so the UI reacts instantly; the API call runs; on success the patch is kept until
// the next poll supersedes it (no blink); on failure it's reverted and an *explained* error is
// pinned to the row (rowErrors[key]) plus a toast. A safety timeout clears a stuck op and resyncs.
// Verify-only actions (create / rekey / anything revealing a secret) simply pass no `patch`.
let _mutSeq = 0;
function mutate({ key, patch, call, onOk, timeout = 8000 }) {
  const id = "m" + (++_mutSeq);
  if (key) delete Store.rowErrors[key];
  if (patch) { Store.pending[id] = { apply: patch, done: false }; }
  if (patch || key) Store.apply();
  const timer = setTimeout(() => { if (Store.pending[id]) { delete Store.pending[id]; Store.poll().catch(() => {}); } }, timeout);
  return (async () => {
    let r;
    try { r = await call(); }
    catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
    clearTimeout(timer);
    if (!r || !r.ok) {
      delete Store.pending[id];                                  // revert optimistic change
      if (key) Store.rowErrors[key] = { msg: (r && (r.error || r.code)) || "request failed", at: Date.now() };
      Store.apply();
      toast((r && (r.error || r.code)) || "Action failed.", "err", 4500);
      return r || { ok: false };
    }
    if (key) delete Store.rowErrors[key];
    if (onOk) { try { onOk(r); } catch (_) {} }
    if (Store.pending[id]) Store.pending[id].done = true;        // keep applied until the next poll supersedes
    await Store.poll().catch(() => {});
    return r;
  })();
}
function rowError(key) { return Store.rowErrors[key] || null; }
function dismissError(key) { if (Store.rowErrors[key]) { delete Store.rowErrors[key]; Store.apply(); } }

// ───────────────────────── modal ─────────────────────────
let _setModal = () => {};
function openModal(node) { _setModal(node); }
function closeModal() { _setModal(null); }

// ───────────────────────── shared bits ─────────────────────────
const STATUS_RANK = { dangling: 0, partial: 1, pending: 2, unknown: 3, unassigned: 4, online: 5, ready: 6 };
const STATUS_ICON = { online: "check", ready: "clock", partial: "warn", pending: "clock",
  dangling: "err", unknown: "info", unassigned: "user", orphan: "link", removing: "trash", empty: "info" };
function Badge({ s }) {
  const ic = STATUS_ICON[s];
  return html`<span class=${"badge b-" + s + (ic ? " ic" : "")}>${ic ? html`<${Ic} i=${ic}/>` : null}${s}</span>`;
}

// inline metadata tag (protocol / interface / turn-proxy / generic) — the dense, colored
// row signature. iface tags take the node's colour via --tgc.
function Tag({ kind, label, color, muted }) {
  return html`<span class=${"tg tg-" + (kind || "gen") + (muted ? " muted" : "")} style=${color && !muted ? "--tgc:" + color : ""}>${label}</span>`;
}
// the tags that describe a peer's deployment on a (node,iface): protocol + interface + turn-proxy.
// `muted` greys them out for inactive (offline / dangling / disconnected) rows.
function targetTags(node, iface, type, via, muted) {
  const tags = [];
  const proto = (type || "").toLowerCase();
  if (proto === "awg") tags.push(html`<${Tag} kind="awg" label="awg" muted=${muted}/>`);
  else if (proto === "wg") tags.push(html`<${Tag} kind="wg" label="wg" muted=${muted}/>`);
  tags.push(html`<${Tag} kind="iface" label=${iface} color=${Store.nodeColor(node)} muted=${muted}/>`);
  if (via === "turn" || turnProxiesFor(node, iface).length) tags.push(html`<${Tag} kind="turn" label="turn" muted=${muted}/>`);
  return tags;
}
// rate cell, green when traffic is flowing
function rateCell(rx, tx) {
  const live = (rx || 0) + (tx || 0) > 0;
  return html`<span class=${"ratecell" + (live ? " live" : "")}>↓ ${rate(rx)} <span class="up">↑ ${rate(tx)}</span></span>`;
}

// "+N" pill listing a peer's other deployments. Hover OR click opens a bubble (click pins it for
// touch); each row is server name · interface tag · right-aligned IP. The bubble is position:fixed
// (anchored to the pill's rect) so the table's overflow:hidden can't clip it.
function DepBadge({ others }) {
  const [open, setOpen] = useState(false);     // hover preview
  const [pinned, setPinned] = useState(false); // click-pinned (mobile / sticky)
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  const closeT = useRef(null);
  const show = open || pinned;
  const cancelClose = () => clearTimeout(closeT.current);
  const scheduleClose = () => { cancelClose(); closeT.current = setTimeout(() => setOpen(false), 140); };
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect(); setPos({ left: Math.round(r.left), top: Math.round(r.bottom + 6) }); };
  useEffect(() => {
    if (!show) return; place();
    const onMove = () => place();
    const onDoc = e => { if (!(ref.current && ref.current.contains(e.target))) { setPinned(false); setOpen(false); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    if (pinned) document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [show, pinned]);
  useEffect(() => () => clearTimeout(closeT.current), []);
  return html`<span class=${"depmore" + (show ? " on" : "")} ref=${ref}
    onClick=${e => { e.stopPropagation(); setPinned(p => !p); }}
    onMouseEnter=${() => { cancelClose(); setOpen(true); }} onMouseLeave=${scheduleClose}>+${others.length}
    ${show && pos ? html`<div class="deppop" style=${"left:" + pos.left + "px;top:" + pos.top + "px"}
      onClick=${e => e.stopPropagation()} onMouseEnter=${cancelClose} onMouseLeave=${scheduleClose}>
      ${others.map(d => html`<div class="deprow" key=${tkey(d.node, d.iface)}>
        <span class="dep-name" style=${"color:" + (Store.nodeColor(d.node) || "var(--ink)")}>${Store.nodeName(d.node)}</span>
        <${Tag} kind=${(d.type || "").toLowerCase() === "awg" ? "awg" : "wg"} label=${d.iface} muted=${!d.online}/>
        <span class="dep-ip addr">${d.ip || "—"}</span></div>`)}
    </div>` : null}
  </span>`;
}
function peerLabel(p) { return p.unassigned ? "" : (p.name || ""); }

function TargetPips({ peer }) {
  return html`<span class="pips">${peer.targets.map(d => {
    const col = Store.nodeColor(d.node);
    let cls = "unk";
    if (d.status === "online") cls = "on";
    else if (d.status === "ready") cls = "present";
    else if (d.status === "dangling" || d.status === "pending") cls = "miss";
    return html`<span class="pip ${cls}" style=${"--pc:" + col} title=${Store.nodeName(d.node) + " · " + d.iface + " · " + d.status}></span>`;
  })}</span>`;
}

// inline user assignment <select>
// Assign an unassigned peer to a user with a FRESH credential: mint a new keypair + PSK in
// the browser, rebuild the client config for every target, push via rekey. The new owner
// gets a working config; nobody inherits a key a previous holder could still have.
// Verify-only (mints a fresh key + rebuilds configs, so we reveal only on confirm). Routed
// through mutate() for the unified error path; no optimistic patch — heavy/crypto action.
async function assignPeerToUser(peer, userId) {
  if (!userId) return;
  const key = "peer:" + peer.id;
  let keys, psk, configs;
  try {
    keys = await genKeys(); psk = genPSK(); configs = {};
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { Store.rowErrors[key] = { msg: Store.nodeName(t.node) + " hasn't reported " + t.iface + " yet", at: Date.now() }; Store.apply(); return; }
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: t.ip + "/32", dns: m.dns, mtu: 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk, endpoint: m.endpoint, allowed: "0.0.0.0/0, ::/0", keepalive: 25 });
    }
  } catch (e) { Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
  await mutate({
    key,
    call: () => api.peerRekey({ peer_id: peer.id, user_id: userId, pubkey: keys.pub, psk, configs }),
    onOk: () => { Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; },
  });
}

// Rotate a peer's keypair while KEEPING its PSK (PSK is user-owned — rotated only from the user
// module). Mints a new keypair in the browser, preserves each target's current config settings
// (DNS/MTU/AllowedIPs/keepalive) where readable, and re-issues. The old config stops working,
// so the client must re-import the fresh QR/config. Only meaningful for an assigned peer.
async function rotatePeerKeys(peer) {
  const key = "peer:" + peer.id;
  let keys, configs;
  try {
    keys = await genKeys(); configs = {};
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { Store.rowErrors[key] = { msg: Store.nodeName(t.node) + " hasn't reported " + t.iface + " yet", at: Date.now() }; Store.apply(); return; }
      const cur = await getConfig(peer.pubkey, t.node, t.iface);
      const s = cur ? parseFullConf(cur) : null;
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: (t.ip || "").split("/")[0] + "/32",
        dns: s ? s.dns : m.dns, mtu: s ? s.mtu : 1280, awg_params: m.awg_params, server_pubkey: m.public_key,
        psk: peer.psk, endpoint: m.endpoint, allowed: s ? s.allowed : "0.0.0.0/0, ::/0", keepalive: s ? s.keepalive : 25 });
    }
  } catch (e) { Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
  await mutate({
    key,
    call: () => api.peerRekey({ peer_id: peer.id, user_id: peer.user_id, pubkey: keys.pub, psk: peer.psk, configs }),
    onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; },
  });
}

// Confirmed unassign — revokes the holder (PSK rotates) and is irreversible (keys change).
// `back` = where Cancel returns to (e.g. the peer view it was launched from).
function confirmUnassign(peer, back) {
  openConfirm({ title: "Unassign peer" + (peer.name ? " · " + peer.name : ""), confirmLabel: "Unassign", danger: true, back,
    body: "This revokes access immediately and is irreversible — the keys change, so re-assigning later means sending the user a brand-new QR / config to import.",
    onConfirm: () => mutate({ key: "peer:" + peer.id,
      patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = null; },
      call: () => api.peerUnassign({ peer_id: peer.id }),
      onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.configEpoch++; } }) });
}
// Confirmed delete (unassigned peers only). `back` = Cancel target.
function confirmDeletePeer(peer, back) {
  openConfirm({ title: "Delete peer", confirmLabel: "Delete", danger: true, back,
    body: "This is irreversible — the peer's key is removed from every interface it's deployed on.",
    onConfirm: () => mutate({ key: "peer:" + peer.id, patch: s => { delete s.roster.peers[peer.id]; },
      call: () => api.peerDelete({ peer_id: peer.id }) }) });
}

// A type-to-filter user picker (the "assign to" control for unassigned peers).
function UserCombo({ onPick, placeholder }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const ql = q.toLowerCase();
  const shown = users.filter(u => !ql || (u.name + " " + (u.tag || "")).toLowerCase().includes(ql)).slice(0, 8);
  return html`<div class="usercombo" onfocusout=${e => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
    <input class="uc-input" value=${q} placeholder=${placeholder || "Assign to…"} onFocus=${() => setOpen(true)}
      onInput=${e => { setQ(e.target.value); setOpen(true); }}/>
    ${open ? html`<div class="uc-list">${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id}
      onClick=${() => { setOpen(false); setQ(""); onPick(u.id); }}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
      : html`<div class="uc-empty">${users.length ? "no match" : "no users yet"}</div>`}</div>` : null}
  </div>`;
}

// A type-to-filter user *select* that holds a value (current owner) — used by the create/edit
// peer forms. Like UserCombo but reflects a selection and can offer "— unassigned —".
function UserPicker({ value, onChange, allowUnassigned, placeholder }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const sel = users.find(u => u.id === value);
  const selText = sel ? sel.name + (sel.tag ? " · " + sel.tag : "") : "";
  const ql = q.toLowerCase();
  const shown = users.filter(u => !ql || (u.name + " " + (u.tag || "")).toLowerCase().includes(ql)).slice(0, 8);
  const pick = uid => { setOpen(false); setQ(""); onChange(uid); };
  return html`<div class="usercombo" onfocusout=${e => { if (!e.currentTarget.contains(e.relatedTarget)) { setOpen(false); setQ(""); } }}>
    <input class="uc-input" value=${open ? q : selText}
      placeholder=${placeholder || (allowUnassigned ? "— unassigned —" : "Assign to a user…")}
      onFocus=${() => { setOpen(true); setQ(""); }} onInput=${e => { setQ(e.target.value); setOpen(true); }}/>
    ${open ? html`<div class="uc-list">
      ${allowUnassigned ? html`<button class="uc-opt" onClick=${() => pick("")}><span class="faint">— unassigned —</span></button>` : null}
      ${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id} onClick=${() => pick(u.id)}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
        : html`<div class="uc-empty">${users.length ? "no match" : "no users yet"}</div>`}
    </div>` : null}
  </div>`;
}

// Simple assign for an UNASSIGNED peer: just record the owner (roster metadata). The key / PSK /
// config are kept, so a config already handed out keeps working — no fresh credential, no warning.
function assignPeer(peer, userId) {
  if (!userId) return;
  return mutate({ key: "peer:" + peer.id,
    patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = userId; },
    call: () => api.peerUpdate({ peer_id: peer.id, user_id: userId }) });
}

// Reassign an ALREADY-assigned peer to a different user — this DOES rotate keys (the previous
// holder must be revoked), so it's confirmed and the new owner needs a re-issued config.
function confirmReassign(peer, userId, back) {
  const to = Store.recon.users.find(u => u.id === userId);
  const toName = to ? to.name : "the selected user";
  openConfirm({
    title: "Reassign peer", confirmLabel: "Reassign", danger: true, back,
    body: "Reassigning to " + toName + " rotates the peer's keys. The current user loses access immediately and permanently — assigning them back later would still be a brand-new credential. " + toName + " gets a fresh QR / config that must be re-distributed.",
    onConfirm: () => assignPeerToUser(peer, userId),
  });
}

// Owner controls: assigned peers can only be Unassigned (revokes the holder); unassigned
// peers offer Assign-to (fresh key) and Delete. Deletion is gated to unassigned peers.
function PeerOwnerControls({ peer, showDelete }) {
  const key = "peer:" + peer.id;
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  if (!peer.unassigned) {
    return html`<${Fragment}>
      <${DangerButton} label="Unassign" confirm="Unassign — revoke access?" onConfirm=${() => mutate({
        key, patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = null; },   // optimistic: greys instantly
        call: () => api.peerUnassign({ peer_id: peer.id }),
        onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.configEpoch++; },
      })}/>
      <${RowError} k=${key}/>
    <//>`;
  }
  return html`<span class="ownerctl">
    <select class="selwrap mini" onChange=${e => { const uid = e.target.value; e.target.value = ""; if (uid) assignPeer(peer, uid); }}>
      <option value="">Assign to…</option>
      ${users.map(u => html`<option value=${u.id}>${u.name}${u.tag ? " · " + u.tag : ""}</option>`)}
    </select>
    ${showDelete ? html`<${DangerButton} label="Delete" confirm="Delete peer?" onConfirm=${() => mutate({
      key, patch: s => { delete s.roster.peers[peer.id]; },                                  // optimistic: row leaves
      call: () => api.peerDelete({ peer_id: peer.id }),
    })}/>` : null}
    <${RowError} k=${key}/>
  </span>`;
}

// pinned, explained failure for a row's last action; dismissable
function RowError({ k }) {
  const e = rowError(k);
  if (!e) return null;
  return html`<span class="rowerr" title=${e.msg}><${Ic} i="err"/> ${e.msg}<button class="rowerr-x" onClick=${() => dismissError(k)}>×</button></span>`;
}

// confirm-on-second-click button; shows a working state while its action is in flight
function DangerButton({ label, confirm, onConfirm, className }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const tref = useRef(null);
  useEffect(() => () => clearTimeout(tref.current), []);
  return html`<button class=${"btn btn-mini " + (className || "warn")} disabled=${busy} onClick=${async () => {
    if (busy) return;
    if (!armed) { setArmed(true); tref.current = setTimeout(() => setArmed(false), 2800); return; }
    clearTimeout(tref.current); setArmed(false); setBusy(true);
    try { await onConfirm(); } finally { setBusy(false); }
  }}>${busy ? "…" : (armed ? (confirm || "Confirm?") : label)}</button>`;
}

// One fleet entry: main block (identity/traffic/sync) on the left, health block on the right.
function FleetNodeCard({ n }) {
  const live = Store.recon.nodeStatus[n.id] === "live";
  const snap = Store.stats[n.id];
  const nrec = (Store.nodes || []).find(x => x.id === n.id) || {};   // health lives on the node-store record
  const health = nrec.health || null;
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === n.id));
  const onl = here.filter(p => p.targets.some(t => t.node === n.id && t.online)).length;
  let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
  let sync = "no data"; if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); sync = live ? "synced " + seen(a) + " ago" : "stale · " + seen(a); }
  const al = healthAlerts(health);
  return html`<a class=${"fnode " + (live ? "" : "stale")} href=${"#/node/" + encodeURIComponent(n.id)}>
    <div class="fnode-main">
      <div class="fnode-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="fnode-name">${n.name}</span><span class="tport">${n.transport}</span>${al.length ? html`<span class="halert hot"><${Ic} i="warn"/> ${al.length}</span>` : ""}<span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>
      <div class="fnode-stats">
        <div><span class="fl">Traffic</span><span class=${"ratecell" + (nrx + ntx > 0 ? " live" : "")}>↓ ${rate(nrx)} <span class="up">↑ ${rate(ntx)}</span></span></div>
        <div><span class="fl">Online</span><span class="fv">${onl} / ${here.length}</span></div>
        <div><span class="fl">Sync</span><span class="fv">${sync}</span></div>
      </div>
    </div>
    <div class="fnode-health">
      ${health ? html`<${NodeHealth} health=${health} node=${n.id} compact=${true}/>` : html`<div class="fnode-nohealth">${live ? "no health data reported" : "node offline"}</div>`}
    </div>
  </a>`;
}

// Recent activity comes from the panel's server-side event log (/api/events): real per-action
// history ("Assigned peer", "Removed deployment", …). Until the log has entries we fall back to
// the created/updated heuristic derived from created_at vs modified_at, so the feed is never blank.
const ACT_ICON = { user: "user", peer: "device", node: "server" };
const ACT_HREF = { user: id => "#/user/" + encodeURIComponent(id), peer: id => "#/peer/" + encodeURIComponent(id), node: id => "#/node/" + encodeURIComponent(id) };
function recentActivity() {
  if (Store.events && Store.events.length) {
    return Store.events.slice(0, 7).map((e, i) => ({
      ts: e.ts, action: e.verb, name: e.name, detail: e.detail || "",
      icon: ACT_ICON[e.kind] || "info", kind: e.kind, key: "e" + e.ts + i,
      href: (ACT_HREF[e.kind] || (() => "#/"))(e.id),
    }));
  }
  const ev = [];
  for (const u of Store.recon.users) {
    const c = u.created_at || 0, m = u.modified_at || c;
    ev.push({ ts: m, action: m > c + 5 ? "Updated user" : "Created user", name: u.name, detail: "", icon: "user", kind: "user", key: "u" + u.id, href: "#/user/" + encodeURIComponent(u.id) });
  }
  for (const p of Store.recon.peers) {
    const c = p.created_at || 0, m = p.modified_at || c;
    ev.push({ ts: m, action: m > c + 5 ? "Updated peer" : "Created peer", name: p.title || p.name || "unassigned peer", detail: "", icon: "device", kind: "peer", key: "p" + p.id, href: "#/peer/" + encodeURIComponent(p.id) });
  }
  return ev.filter(e => e.ts).sort((a, b) => b.ts - a.ts).slice(0, 7);
}

// ═════════════════════════ SCREEN: OVERVIEW ═════════════════════════
function Overview() {
  const peers = Store.recon.peers, users = Store.recon.users, fleet = Store.fleet, ns = Store.recon.nodeStatus;
  const online = peers.filter(p => p.online).length;
  const partial = peers.filter(p => p.status === "partial").length;
  const offline = peers.filter(p => ["dangling", "unknown"].includes(p.status)).length;
  const liveNodes = fleet.filter(n => ns[n.id] === "live").length;
  const ifaceCount = Object.values(Store.describe).reduce((a, d) => a + Object.keys(d || {}).length, 0);
  const nodesAlerting = (Store.nodes || []).filter(n => healthAlerts(n.health).length).length;
  let rx = 0, tx = 0;
  fleet.forEach(n => { const snap = Store.stats[n.id]; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { rx += pp.rx_speed || 0; tx += pp.tx_speed || 0; } });

  const probs = peers.filter(p => ["dangling", "partial", "pending", "unknown"].includes(p.status))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const unassigned = Store.unassignedPeers();
  const orphans = Store.recon.orphans;
  const why = { dangling: "missing on every server", partial: "missing on some servers", pending: "just created, not seen yet", unknown: "server stale — can't confirm" };

  const recent = recentActivity();

  // ranked nodes — by live traffic, or by peer count when the fleet is idle
  const nodeTraffic = fleet.map(n => {
    const snap = Store.stats[n.id]; let r = 0, t = 0;
    if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { r += pp.rx_speed || 0; t += pp.tx_speed || 0; }
    return { id: n.id, name: n.name, color: n.color, rx: r, tx: t, peers: peers.filter(p => p.targets.some(d => d.node === n.id)).length };
  });
  const anyTraffic = nodeTraffic.some(x => x.rx + x.tx > 0);
  const rankRows = nodeTraffic.slice()
    .sort((a, b) => anyTraffic ? (b.rx + b.tx) - (a.rx + a.tx) : b.peers - a.peers)
    .slice(0, 6)
    .map(x => ({ label: x.name, value: anyTraffic ? x.rx + x.tx : x.peers,
      sub: anyTraffic ? "↓ " + rate(x.rx) + " ↑ " + rate(x.tx) : x.peers + " peer" + (x.peers === 1 ? "" : "s"),
      color: x.color || "var(--brand)", href: "#/node/" + encodeURIComponent(x.id) }));

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="statgrid">
      <a class="stat accent clk" href="#/connections"><span class="stat-ic"><${Ic} i="activity"/></span><div class="stat-c"><div class="k">Online now</div><div class="v">${online}<small> / ${peers.length}</small></div><div class="sub">live connections →</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="users"/></span><div class="stat-c"><div class="k">Users</div><div class="v">${users.length}</div><div class="sub">${peers.length} peers total</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="device"/></span><div class="stat-c"><div class="k">Peer status</div><div class="v" style="font-size:17px"><span style="color:var(--online)">${online}</span> · <span style="color:var(--partial)">${partial}</span> · <span style="color:var(--dangling)">${offline}</span></div><div class="sub">online · partial · offline</div></div></a>
      <a class="stat clk" href="#/nodes"><span class="stat-ic"><${Ic} i="server"/></span><div class="stat-c"><div class="k">Nodes</div><div class="v">${liveNodes}<small> / ${fleet.length}</small></div><div class="sub">${ifaceCount} interface${ifaceCount === 1 ? "" : "s"}${nodesAlerting ? html` · <span style="color:var(--dangling)">${nodesAlerting} alerting</span>` : ""}</div></div></a>
      <div class="stat"><span class="stat-ic"><${Ic} i="gauge"/></span><div class="stat-c"><div class="k">Throughput</div><div class="v" style="font-size:19px">↓ ${rate(rx)}</div><div class="sub">↑ ${rate(tx)} aggregate</div></div></div>
    </div>

    <div class="section-title"><h2>Fleet</h2><span class="count">${fleet.length} server${fleet.length === 1 ? "" : "s"}</span><span class="grow"></span></div>
    ${fleet.length ? html`<div class="fleet2">${fleet.map(n => html`<${FleetNodeCard} key=${n.id} n=${n}/>`)}</div>`
      : html`<div class="allclear">No servers configured in fleet.json.</div>`}

    ${fleet.length > 1 ? html`<${Fragment}>
      <div class="section-title"><h2>${anyTraffic ? "Top nodes by traffic" : "Top nodes by peers"}</h2><span class="grow"></span></div>
      <div class="rankcard"><${RankBars} rows=${rankRows}/></div>
    <//>` : null}

    ${recent.length ? html`<${Fragment}>
      <div class="section-title"><h2>Recent activity</h2></div>
      <div class="actlist">${recent.map(e => html`<a class="act-row" href=${e.href} key=${e.key}>
        <span class=${"act-ic t-" + e.kind}><${Ic} i=${e.icon}/></span>
        <span class="act-what">${e.action}</span><span class="act-name">${e.name}</span>
        ${e.detail ? html`<span class="act-detail">${e.detail}</span>` : null}
        <span class="grow"></span><span class="when">${ago(e.ts)}</span></a>`)}</div>
    <//>` : null}

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
  const name = decodeURIComponent(rawName);   // `name` is the node id (the connector); display uses dname
  const node = Store.node(name);
  const nrec = Store.nodes.find(x => x.id === name) || {};   // full record carries health
  const meta = Store.describe[name] || null;       // interface meta from the consolidated state
  const metaErr = node && !meta;

  if (!node) return html`<div class="screen"><div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>${name}</b></div>
    <div class="empty"><b>Unknown server</b>this server isn't in the fleet.</div></div>`;
  const dname = node.name || name;

  const live = Store.recon.nodeStatus[name] === "live";
  const snap = Store.stats[name];
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === name));
  const onl = here.filter(p => p.targets.some(t => t.node === name && t.online)).length;
  let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
  let syncTxt = "no snapshot yet";
  if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); syncTxt = live ? "synced " + seen(a) + " ago" : "stale for " + seen(a); }

  return html`<div class="screen">
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>${dname}</b></div>
    <div class="detail-head">
      <div class="title"><h1>${dname}</h1><span class=${"tport" + (node.transport === "https" ? " https" : "")}>${node.transport}</span>${live ? html`<span class="reporting">reporting</span>` : html`<span class="badge b-unknown ic"><${Ic} i="info"/>stale</span>`}</div>
      <div class="grow"></div>
    </div>

    <div class="noderibbon">
      <div class="nr-tags">
        ${(meta ? Object.keys(meta) : []).map(ifn => {
          const type = (meta[ifn].awg_params && Object.keys(meta[ifn].awg_params).length) ? "awg" : "wg";
          return html`<a class=${"tg tg-" + type} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}>${ifn}</a>`;
        })}
        ${((snap && snap.turn_proxies) || []).map(tp => html`<span class="tg tg-turn">${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`)}
      </div>
      <span class="grow"></span>
      <div class="nr-sync"><span class="when">${syncTxt}</span>${nrec.health && nrec.health.uptime != null ? html`<span class="when">up ${dur(nrec.health.uptime)}</span>` : null}</div>
    </div>

    ${nrec.health ? html`<${Panel} icon="activity" title="Health" tone="online">
      <${HealthAlerts} health=${nrec.health}/>
      ${nrec.health_history
        ? html`<${RangedHistory} node=${name} kind="cpu" live=${nrec.health_history} h=${52} head=${html`<${HealthMeters} health=${nrec.health}/>`}/>`
        : html`<${HealthMeters} health=${nrec.health}/>`}
    <//>` : null}

    ${nrec.health_history ? html`<${Panel} icon="gauge" title="Throughput">
      <${RangedHistory} node=${name} kind="throughput" live=${nrec.health_history} h=${72}/>
    <//>` : null}

    <${Panel} icon="network" title="Interfaces" count=${meta ? Object.keys(meta).length : 0}>
      ${metaErr ? html`<div class="notice warn"><${Ic} i="warn"/><span>This node hasn't reported in yet — its interfaces will show up here once it runs the installer and syncs.<br/><br/>Lost the enrollment token or the install command? Rotate the node's token to generate a fresh install command.</span></div>`
        : !meta ? html`<div class="loading"><span class="spin"></span>reading server…</div>`
        : !Object.keys(meta).length ? html`<div class="notice warn"><${Ic} i="warn"/><span>No managed interfaces reported.</span></div>`
        : html`<div class="ifgrid">${Object.keys(meta).map(ifn => {
            const m = meta[ifn];
            const type = (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg";
            const ps = here.filter(p => p.targets.some(t => t.node === name && t.iface === ifn));
            const onlc = ps.filter(p => p.targets.some(t => t.node === name && t.iface === ifn && t.online)).length;
            return html`<a class="ifcard" href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}>
              <div class="ifcard-top"><span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span></div>
              <div class="ifcard-rows">
                <div class="ifrow"><span class="l">Listen</span><span class="r addr">${m.endpoint || ((m.address || "").split("/")[0] + (m.listen_port ? ":" + m.listen_port : "")) || "—"}</span></div>
                <div class="ifrow"><span class="l">Subnet</span><span class="r addr">${m.subnet || "—"}</span></div>
                <div class="ifrow"><span class="l">Peers</span><span class="r">${ps.length ? html`<${UsageBar} value=${onlc} total=${ps.length}/>` : html`<span class="faint">none</span>`}</span></div>
              </div></a>`;
          })}</div>`}
    <//>

    ${snap && (snap.turn_proxies || []).length ? html`<${Panel} icon="relay" title="Turn proxies" tone="turn" count=${snap.turn_proxies.length}>
      <div class="ifgrid">${snap.turn_proxies.map(tp => {
        const lp = portOf(tp.connect);
        const fronted = meta ? Object.keys(meta).find(i => String(meta[i].listen_port) === lp) : null;
        const ftype = (fronted && meta[fronted].awg_params && Object.keys(meta[fronted].awg_params).length) ? "awg" : "wg";
        return html`<div class="ifcard tp">
          <div class="ifcard-top"><span class="iftype turn">turn</span><span class="ifname">${turnLabel(tp.service, portOf(tp.listen))}</span>${!fronted ? html`<span class="grow"></span><span class="tg tg-warn" title="Forwards to a port with no managed interface behind it — likely a misconfiguration.">unbound</span>` : null}</div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">Listen</span><span class="r addr">${tp.listen || "—"}</span></div>
            <div class="ifrow"><span class="l">Forwards to</span><span class="r">${fronted ? html`<a class=${"tg tg-" + ftype} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(fronted)}>${fronted}</a>` : (tp.connect || "—")}</span></div>
            ${tp.wrap_key ? html`<div class="ifrow"><span class="l">Wrap key</span><span class="r addr">${String(tp.wrap_key).slice(0, 8)}…<button class="copybtn" title="Copy wrap key" onClick=${() => copy(tp.wrap_key, "Wrap key copied")}><${Ic} i="copy"/></button></span></div>` : null}
          </div></div>`;
      })}</div>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: INTERFACE DETAIL ═════════════════════════
function IfaceDetail({ node: rawNode, iface: rawIface }) {
  useStore();
  const [q, setQ] = useState("");
  const node = decodeURIComponent(rawNode);
  const iface = decodeURIComponent(rawIface);
  const nrec = Store.node(node);   // node = id (the connector)
  if (!nrec) return html`<div class="screen"><div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>server</b></div>
    <div class="empty"><b>Unknown server</b>this server isn't in the fleet.</div></div>`;
  const dname = nrec.name || node;
  const meta = Store.ifaceMeta(node, iface);
  const live = Store.recon.nodeStatus[node] === "live";
  // a pending listen-port change: desired (panel) != reported (node) until the node converges
  const updating = !!(meta && meta.desired_port && meta.listen_port && Number(meta.desired_port) !== Number(meta.listen_port));
  const type = (meta && meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg";
  const peers = Store.recon.peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface));
  const onl = peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface && t.online)).length;
  const orphans = Store.recon.orphans.filter(o => o.node === node && o.iface === iface);
  const tps = turnProxiesFor(node, iface);
  const awg = meta && Object.keys(meta.awg_params || {}).length ? Object.entries(meta.awg_params).map(([k, v]) => k + "=" + v).join("  ") : "—";
  const rows = peers.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
  // one {peer,target} row per peer on this interface, fed to the shared PeerGrid
  const ifaceRows = rows.map(p => ({ p, t: p.targets.find(d => d.node === node && d.iface === iface) || {} }));
  const ifaceShown = {};
  for (const { p, t } of ifaceRows) (ifaceShown[p.id] = ifaceShown[p.id] || new Set()).add(tkey(t.node, t.iface));
  const ql = q.trim().toLowerCase();
  const ifaceFiltered = !ql ? ifaceRows : ifaceRows.filter(({ p, t }) => {
    const u = p.user_id ? Store.user(p.user_id) : null;
    return ((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + (u ? u.name : "")).toLowerCase().includes(ql);
  });

  return html`<div class="screen">
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b></div>
    <div class="detail-head">
      <div class="title"><h1>${iface}</h1><span class=${"iftype " + type}>${type}</span>${updating ? html`<span class="badge" style="background:rgba(154,139,240,.16);color:var(--pending)"><${Ic} i="clock"/>updating</span>` : html`<span class="badge b-${live ? "online" : "unknown"}">${live ? "reporting" : "stale"}</span>`}<span class="when">${onl} / ${peers.length} online</span></div>
      <div class="grow"></div>
    </div>

    ${!meta ? html`<div class="notice warn"><${Ic} i="warn"/><span>This interface hasn't been reported in a snapshot yet.</span></div>`
      : html`<${Panel} icon="key" title="Interface details" tone=${type === "awg" ? "" : "online"}
          actions=${html`<button class="btn btn-mini" onClick=${() => openEditIface(node, iface)}><${Ic} i="pencil"/> Edit interface</button>`}>
        <div class="iface-grid">
          <div class="ig-item"><span class="ig-l">Endpoint</span><span class="ig-v">${meta.endpoint || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">Server address</span><span class="ig-v">${meta.address || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">DNS</span><span class="ig-v">${(meta.dns || []).join(", ") || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">MTU</span><span class="ig-v">${meta.mtu || 1280}</span></div>
        </div>
        ${type === "awg" ? html`<div class="iface-amnezia"><span class="ig-l">AmneziaWG</span><span class="ig-v">${awg}</span></div>` : null}
      <//>`}

    ${tps.length ? html`<${Panel} icon="relay" title="Reachable via turn-proxy" tone="turn" count=${tps.length}>
      <div class="ifgrid">${tps.map(tp => html`<div class="ifcard tp">
        <div class="ifcard-top"><span class="iftype turn">turn</span><span class="ifname">${turnLabel(tp.service, portOf(tp.listen))}</span></div>
        <div class="ifcard-rows">
          <div class="ifrow"><span class="l">Listen</span><span class="r addr">${tp.listen || "—"}</span></div>
          ${tp.wrap_key ? html`<div class="ifrow"><span class="l">Wrap key</span><span class="r addr">${String(tp.wrap_key).slice(0, 8)}…<button class="copybtn" title="Copy wrap key" onClick=${() => copy(tp.wrap_key, "Wrap key copied")}><${Ic} i="copy"/></button></span></div>` : null}
        </div></div>`)}</div>
    <//>` : null}

    <${Panel} icon="users" title="Peers on this interface" count=${peers.length} pad=${false}
        actions=${html`<${Fragment}>
          <div class="search sm"><${Ic} i="search"/><input placeholder="Search peers…" value=${q} onInput=${e => setQ(e.target.value)}/></div>
          <button class="btn btn-mini" onClick=${() => openCreatePeer({ node, iface })}><${Ic} i="plus"/> Add peer</button></>`}>
      <${PeerGrid} rows=${ifaceFiltered} agg=${false} node=${node} iface=${iface} shownByPeer=${ifaceShown} q=${q}/>
    <//>

    ${orphans.length ? html`<${Panel} icon="warn" title="Unmanaged on this interface" tone="warn" pad=${false}>
      <table><tbody>
        ${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}
      </tbody></table>
    <//>` : null}
  </div>`;
}

function OrphanRow({ o }) {
  return html`<tr>
    <td data-label="Status"><${Badge} s="orphan"/></td>
    <td data-label="Key" class="addr">${o.pubkey.slice(0, 22)}…</td>
    <td data-label="Address"><span class="addr">${o.iface} · ${o.allowed_ips || "—"}</span></td>
    <td data-label="" style="text-align:right" class="rowacts">
      <button class="btn btn-mini" onClick=${() => mutate({   // verify-only: server assigns the id
        key: "orphan:" + o.node + "|" + o.iface + "|" + o.pubkey,
        call: () => api.peerAdopt({ pubkey: o.pubkey, target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
      })}>Adopt</button>
      <${RowError} k=${"orphan:" + o.node + "|" + o.iface + "|" + o.pubkey}/>
    </td></tr>`;
}

// Edit an interface: the Endpoint IP (what clients dial — config-facing only) and the Listen
// port (pushed to the node's wgXX.conf — the interface rebinds to it; peers are untouched and
// reconnect via the new port). Default DNS / MTU seed new peers. Interface key shown read-only.
function openEditIface(node, iface) { openModal(html`<${EditIfaceSheet} node=${node} iface=${iface}/>`); }
function EditIfaceSheet({ node, iface }) {
  const meta = Store.ifaceMeta(node, iface) || {};
  const ep = meta.endpoint || "";
  const epHost = ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
  const [host, setHost] = useState(epHost);
  const [port, setPort] = useState(String(meta.desired_port || meta.listen_port || ""));
  const [dns, setDns] = useState((meta.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(meta.mtu || 1280));
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    const r = await api.ifaceUpdate({ node, iface, endpoint_host: host.trim(), listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim() });
    if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: r.error || "Failed to update interface." }); }
    closeModal(); await Store.poll(); toast("Interface saved — the node applies the port on its next sync.", "ok");
  };
  return html`<${Sheet} title=${"Edit interface · " + iface}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>Save</button></>`}>
    <p class="hint" style="margin:0 0 16px">Endpoint IP only changes what configs/QRs tell clients to dial. Changing the Listen port reconfigures the interface on the node (peers are kept; clients reconnect on the new port). DNS / MTU seed new peers — existing per-peer values aren't touched.</p>
    <div class="row2">
      <div class="field"><label>Endpoint IP</label><input autofocus value=${host} onInput=${e => setHost(e.target.value)} placeholder="vpn.example.com or 203.0.113.7"/><div class="hint">What clients dial. Config-facing only.</div></div>
      <div class="field"><label>Listen port</label><input value=${port} onInput=${e => setPort(e.target.value)} placeholder=${String(meta.listen_port || "")}/><div class="hint">Applied to the node (currently ${meta.listen_port || "—"}).</div></div>
    </div>
    <div class="row2">
      <div class="field"><label>Default DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="1.1.1.1, 1.0.0.1"/><div class="hint">Comma-separated. Default for new peers (per-peer DNS isn't overwritten).</div></div>
      <div class="field"><label>Default MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">Default for new peers.</div></div>
    </div>
    <div class="field"><label>Interface public key <span class="faint" style="text-transform:none;letter-spacing:0">— read-only</span></label><div class="cmdrow"><div class="tokenbox">${meta.public_key || "—"}</div>${meta.public_key ? html`<button class="copyaction" onClick=${() => copy(meta.public_key, "Public key copied")}><${Ic} i="copy"/> Copy</button>` : null}</div></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ═════════════════════════ SCREEN: PEERS (by node) ═════════════════════════
const peersView = { node: "", iface: "", q: "" };
// Prominent warning when the panel keeps no client configs at rest — QRs/downloads then only work
// in the session a peer is created, and existing peers can't be re-shared. Shown on Overview + Peers.
function StoreOffBanner() {
  if (Store.storeConfigs) return null;
  const docker = !!(Store.env && Store.env.docker);
  const fp = (Store.env && Store.env.fleet_path) || "/etc/swg-panel/fleet.json";
  const sed = `sed -i -E 's/("store_configs":[[:space:]]*)false/\\1true/' ${fp}`;
  const cmd = docker
    ? `docker exec swg-panel ${sed} && docker restart swg-panel`
    : `sudo ${sed} && sudo systemctl restart swg-panel-server`;
  return html`<div class="banner warn"><${Ic} i="warn"/><div class="banner-body">
    <b>Config storage is off.</b> Client configs (with their private keys) aren't kept on the panel, so QR codes and
    downloads only work right after a peer is created — existing peers can't be re-shared. Run this on the
    ${docker ? "Docker host" : "panel host"} to enable it (existing peers then need a one-time Rotate-keys to capture a config):
    <div class="cmdrow"><div class="tokenbox">${cmd}</div><button class="copyaction" onClick=${() => copy(cmd, "Command copied")}><${Ic} i="copy"/> Copy</button></div>
  </div></div>`;
}
// The shared peers grid — one row per (peer, target) deployment. Reused by the Peers screen and
// the interface-detail screen so they're identical. `agg` adds the Server/IF column; `shownByPeer`
// drives the "+N other deployments" badge; row click opens the peer-view popup.
function PeerGrid({ rows, agg, node, iface, shownByPeer, q }) {
  return html`<div class="tablewrap"><table class="peergrid">
    <thead><tr><th>Status</th>${agg ? html`<th>${node === "*" ? "Server" : "IF"}</th>` : null}<th>User</th><th>Title</th><th>Address</th><th>Last</th><th>Rate ↓↑</th><th>Total ↓↑</th><th></th></tr></thead>
    <tbody>
      ${rows.length ? rows.map(({ p, t }) => {
        const obs = t.observed;
        const u = p.user_id ? Store.user(p.user_id) : null;
        const hidden = p.targets.filter(d => !(shownByPeer[p.id] || new Set()).has(tkey(d.node, d.iface)));   // this peer's deployments not shown in the grid
        return html`<tr key=${p.id + "|" + tkey(t.node, t.iface)} class="clk" onClick=${() => openPeerView(p.id, t.node, t.iface)}>
          <td data-label="Status"><${Badge} s=${t.status || p.status}/></td>
          ${agg ? html`<td data-label=${node === "*" ? "Server" : "IF"}><div class="srvcell">
            ${node === "*" ? html`<span class="srv-name" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>` : null}
            ${iface === "*" ? html`<${Tag} kind=${(t.type || "").toLowerCase() === "awg" ? "awg" : "wg"} label=${t.iface} muted=${!t.online}/>` : null}
          </div></td>` : null}
          <td data-label="User" class=${"usercell" + (u ? " linked" : "")} onClick=${u ? (e => { e.stopPropagation(); go("#/user/" + encodeURIComponent(u.id)); }) : (e => e.stopPropagation())}>
            ${u ? html`<a class="namecell" href=${"#/user/" + encodeURIComponent(u.id)} onClick=${e => e.stopPropagation()}><span>${u.name}</span><${Ic} i="user"/></a>`
                : html`<div class="assigncell"><${UserCombo} onPick=${uid => assignPeer(p, uid)}/><${RowError} k=${"peer:" + p.id}/></div>`}</td>
          <td data-label="Title" class="c-name">${p.title ? html`<b>${p.title}</b>` : html`<span class="faint">untitled</span>`}</td>
          <td data-label="Address"><span class="addr">${t.ip || "—"}</span>${hidden.length ? html`<${DepBadge} others=${hidden}/>` : null}</td>
          <td data-label="Last"><span class="when">${seen(obs ? obs.handshake_age : null)}</span></td>
          <td data-label="Rate">${rateCell(obs ? obs.rx_speed : 0, obs ? obs.tx_speed : 0)}</td>
          <td data-label="Total"><span class="addr xfer">↓ ${fmtBytes(obs ? obs.rx_bytes : 0)} <span class="up">↑ ${fmtBytes(obs ? obs.tx_bytes : 0)}</span></span></td>
          <td data-label="" class="rowacts" onClick=${e => e.stopPropagation()}>
            <button class="iconbtn" title="Edit peer" onClick=${() => openEditPeer(p, { node: t.node, iface: t.iface })}><${Ic} i="pencil"/></button>
            ${p.unassigned
              ? html`<button class="iconbtn danger" title="Delete peer" onClick=${() => confirmDeletePeer(p)}><${Ic} i="trash"/></button>`
              : html`<button class="iconbtn danger" title="Unassign peer" onClick=${() => confirmUnassign(p)}><${Ic} i="link"/></button>`}
            <${RowError} k=${"peer:" + p.id}/>
          </td></tr>`;
      }) : html`<tr><td colspan=${agg ? 9 : 8} class="empty"><b>${q ? "No matches" : "No peers here"}</b>${q ? "Try a different search." : (!agg ? "Create one, or copy an existing peer onto this interface." : "No peers deployed yet.")}</td></tr>`}
    </tbody></table></div>`;
}
function PeersScreen() {
  useStore();
  const [, force] = useState(0);
  const fleet = Store.fleet;
  const multiServer = fleet.length > 1;
  // "*" = aggregate (all). With more than one server, default to fleet-wide so search spans it.
  if (!peersView.node) peersView.node = multiServer ? "*" : (fleet[0] ? fleet[0].id : "");
  if (peersView.node !== "*" && !fleet.some(n => n.id === peersView.node)) peersView.node = multiServer ? "*" : (fleet[0] ? fleet[0].id : "");
  const node = peersView.node;   // node = id, or "*" for all servers

  const allIfaces = Array.from(new Set(Object.values(Store.describe).flatMap(d => Object.keys(d || {})))).sort();
  const snap = node !== "*" ? Store.stats[node] : null;
  const ifaceOpts = node === "*" ? allIfaces : (snap ? Object.keys(snap.interfaces || {}) : []);
  // default interface: aggregate when several exist (or all-servers); else the only one.
  const ifaceDefault = () => (node === "*" || ifaceOpts.length > 1) ? "*" : (ifaceOpts[0] || "");
  if (!peersView.iface) peersView.iface = ifaceDefault();
  if (peersView.iface !== "*" && !ifaceOpts.includes(peersView.iface)) peersView.iface = ifaceDefault();
  const iface = peersView.iface;
  const agg = node === "*" || iface === "*";
  const itype = (!agg && Store.ifaceMeta(node, iface) && Object.keys(Store.ifaceMeta(node, iface).awg_params || {}).length) ? "awg" : "wg";

  const q = peersView.q.toLowerCase();
  // one row per matching (peer, target) deployment, so a fleet-wide view shows where each peer lives.
  let rows = [];
  for (const p of Store.recon.peers) for (const t of p.targets) {
    if (node !== "*" && t.node !== node) continue;
    if (iface !== "*" && t.iface !== iface) continue;
    rows.push({ p, t });
  }
  if (q) rows = rows.filter(({ p, t }) => ((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface).toLowerCase().includes(q));
  rows.sort((a, b) => STATUS_RANK[a.t.status || a.p.status] - STATUS_RANK[b.t.status || b.p.status]
    || String(a.p.title || a.p.name).localeCompare(String(b.p.title || b.p.name))
    || Store.nodeName(a.t.node).localeCompare(Store.nodeName(b.t.node)));
  // which of each peer's deployments are actually visible as rows here — so a row can flag the rest
  // (filtered out by server/interface or search) with a "+N" the operator can hover/tap.
  const shownByPeer = {};
  for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  const orphans = !agg ? Store.recon.orphans.filter(o => o.node === node && o.iface === iface) : [];

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <div class="search"><${Ic} i="search"/><input placeholder="Search title, user, address…" value=${peersView.q}
        onInput=${e => { peersView.q = e.target.value.trim(); force(x => x + 1); }}/></div>
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; force(x => x + 1); }}>
        ${multiServer ? html`<option value="*">All servers</option>` : null}
        ${fleet.map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; force(x => x + 1); }}>
        ${(node === "*" || ifaceOpts.length > 1) ? html`<option value="*">All interfaces</option>` : null}
        ${ifaceOpts.length ? ifaceOpts.map(i => html`<option value=${i}>${i}</option>`) : (node === "*" ? null : html`<option value="">no interfaces reported</option>`)}
      </select>
      <span class="grow"></span>
      <button class="btn btn-primary" onClick=${() => openCreatePeer(agg ? {} : { node, iface })}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
    </div>

    <div class="section-title"><h2>${agg ? "Peers" : "Peers on"}</h2><span class="tags">
      ${node !== "*" ? html`<${Tag} kind="iface" label=${Store.nodeName(node) || "—"} color=${Store.nodeColor(node)}/>` : null}
      ${iface !== "*" && iface ? html`<${Tag} kind=${itype} label=${iface}/>` : null}
    </span><span class="count">${rows.length}</span></div>
    <${PeerGrid} rows=${rows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${peersView.q}/>

    ${orphans.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--orphan)">Unmanaged here</h2></div>
      <div class="tablewrap"><table><tbody>${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}</tbody></table></div>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: CONNECTIONS (live monitor) ═════════════════════════
// Read-only over the enriched snapshot: every target the node currently knows about becomes a
// row. Filters/sort live in module state so a 5s poll never loses them; Preact + keyed rows
// keep scroll position and update cells in place.
function connRows() {
  const out = [];
  for (const p of Store.recon.peers) {
    const u = p.user_id ? Store.user(p.user_id) : null;
    for (const t of p.targets) {
      const obs = t.observed; if (!obs) continue;          // only present-on-node connections
      out.push({
        key: p.id + "|" + t.node + "|" + t.iface, pid: p.id, uid: u ? u.id : null,
        user: u ? u.name : "", peer: p.title || p.name || "", unassigned: p.unassigned,
        node: t.node, iface: t.iface, type: t.type || "", endpoint: obs.endpoint || "", ip: t.ip || "",
        hs: (obs.handshake_age == null ? null : obs.handshake_age),
        rxb: obs.rx_bytes || 0, txb: obs.tx_bytes || 0, rx: obs.rx_speed || 0, tx: obs.tx_speed || 0,
        online: !!obs.online, via: t.via,
      });
    }
  }
  return out;
}
const connView = { node: "", iface: "", user: "", q: "", online: false, sort: "rate", dir: -1 };
const CONN_DEFDIR = { rate: -1, hs: 1, peer: 1, user: 1, node: 1 };
function ConnectionsScreen() {
  useStore();
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const sortBy = col => { if (connView.sort === col) connView.dir = -connView.dir; else { connView.sort = col; connView.dir = CONN_DEFDIR[col] || 1; } bump(); };

  const all = connRows();
  const ifaceList = Array.from(new Set(Object.values(Store.describe).flatMap(d => Object.keys(d || {})))).sort();
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const q = connView.q.toLowerCase();
  let rows = all.filter(r => {
    if (connView.node && r.node !== connView.node) return false;
    if (connView.iface && r.iface !== connView.iface) return false;
    if (connView.user && r.uid !== connView.user) return false;
    if (connView.online && !r.online) return false;
    if (q && !((r.user + " " + r.peer + " " + Store.nodeName(r.node) + " " + r.iface + " " + r.endpoint + " " + r.ip).toLowerCase().includes(q))) return false;
    return true;
  });
  const keyf = { rate: r => r.rx + r.tx, hs: r => (r.hs == null ? Infinity : r.hs), peer: r => r.peer.toLowerCase(), user: r => r.user.toLowerCase(), node: r => r.node + "|" + r.iface }[connView.sort] || (r => r.rx + r.tx);
  rows = rows.sort((a, b) => { const A = keyf(a), B = keyf(b); return (A < B ? -1 : A > B ? 1 : 0) * connView.dir; });
  const onlineCount = all.filter(r => r.online).length;
  const arrow = col => connView.sort === col ? (connView.dir < 0 ? " ↓" : " ↑") : "";

  return html`<div class="screen">
    <div class="toolbar">
      <div class="search"><${Ic} i="search"/><input placeholder="Search peer, user, endpoint, IP…" value=${connView.q} onInput=${e => { connView.q = e.target.value.trim(); bump(); }}/></div>
      <select class="selwrap" value=${connView.node} onChange=${e => { connView.node = e.target.value; bump(); }}>
        <option value="">All nodes</option>${(Store.nodes || []).map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${connView.iface} onChange=${e => { connView.iface = e.target.value; bump(); }}>
        <option value="">All interfaces</option>${ifaceList.map(i => html`<option value=${i}>${i}</option>`)}
      </select>
      <select class="selwrap" value=${connView.user} onChange=${e => { connView.user = e.target.value; bump(); }}>
        <option value="">All users</option>${users.map(u => html`<option value=${u.id}>${u.name}</option>`)}
      </select>
      <label class="chk"><input type="checkbox" checked=${connView.online} onChange=${e => { connView.online = e.target.checked; bump(); }}/> online only</label>
    </div>

    <div class="section-title"><h2>Live connections</h2><span class="count">${rows.length} shown · ${onlineCount} online</span></div>
    <div class="tablewrap"><table class="conntable">
      <thead><tr>
        <th></th>
        <th class="clk" onClick=${() => sortBy("peer")}>Peer${arrow("peer")}</th>
        <th class="clk" onClick=${() => sortBy("user")}>User${arrow("user")}</th>
        <th class="clk" onClick=${() => sortBy("node")}>Node · iface${arrow("node")}</th>
        <th>Endpoint</th>
        <th class="clk" onClick=${() => sortBy("hs")}>Last${arrow("hs")}</th>
        <th class="clk" onClick=${() => sortBy("rate")}>Rate ↓↑${arrow("rate")}</th>
        <th>Transfer ↓↑</th>
      </tr></thead>
      <tbody>
        ${rows.length ? rows.map(r => html`<tr key=${r.key}>
          <td data-label=""><span class=${"condot " + (r.online ? "on" : "off")} title=${r.online ? "online" : "idle"}></span></td>
          <td data-label="Peer" class="c-name clk" onClick=${() => go("#/peer/" + encodeURIComponent(r.pid))}>${r.peer ? html`<b>${r.peer}</b>` : html`<span class="faint">unassigned</span>`}</td>
          <td data-label="User">${r.uid ? html`<a href=${"#/user/" + encodeURIComponent(r.uid)}>${r.user}</a>` : html`<span class="faint">—</span>`}</td>
          <td data-label="Node" class="clk" onClick=${() => go("#/node/" + encodeURIComponent(r.node) + "/" + encodeURIComponent(r.iface))}>
            <span class="addr" style="color:var(--ink-2)">${Store.nodeName(r.node)}</span><span class="tags">${targetTags(r.node, r.iface, r.type, r.via, !r.online)}</span></td>
          <td data-label="Endpoint"><span class="addr">${r.endpoint || "—"}</span></td>
          <td data-label="Last"><span class="when">${seen(r.hs)}</span></td>
          <td data-label="Rate">${rateCell(r.rx, r.tx)}</td>
          <td data-label="Transfer"><span class="addr">↓ ${fmtBytes(r.rxb)} ↑ ${fmtBytes(r.txb)}</span></td>
        </tr>`) : html`<tr><td colspan="8" class="empty"><b>No connections${all.length ? " match" : " yet"}</b>${all.length ? "Clear the filters." : "Peers appear here once a node reports them."}</td></tr>`}
      </tbody></table></div>
  </div>`;
}

// ═════════════════════════ SCREEN: USERS ═════════════════════════
const usersFilter = { text: "" };
// A peer's configs as a modal: one QR/download card per target (reuses TargetCard).
function openPeerConfigs(peer) {
  openModal(html`<${Sheet} title=${"Configs · " + (peer.title || peer.name || "peer")}>
    <div class="cfgsheet">${peer.targets.map(t => html`<${TargetCard} key=${tkey(t.node, t.iface)} peer=${peer} t=${t}/>`)}</div>
  <//>`);
}
function openUserEdit(user) {
  openModal(html`<${Sheet} title=${"Edit · " + user.name}><${UserEditCard} user=${user} done=${closeModal}/><//>`);
}

// One peer as a compact line inside a user group: identity + per-target tags + action icons.
function PeerLine({ peer }) {
  const single = peer.targets.length === 1;
  const flash = Store.recentlyCreated[peer.id] && Date.now() - Store.recentlyCreated[peer.id] < 3000;
  const download = async () => {
    if (!single) return openPeerConfigs(peer);
    const t = peer.targets[0];
    const c = await getConfig(peer.pubkey, t.node, t.iface);
    if (c) downloadConf(c, (peer.title || peer.name || "peer") + "-" + Store.nodeName(t.node));
    else toast(Store.storeConfigs ? "No stored config — re-issue this peer to enable download." : "Config is only available right after creation.", "err");
  };
  return html`<div class=${"pline" + (flash ? " flash" : "")}>
    <div class="pl-main">
      <div class="pl-title">${peer.title ? html`<b>${peer.title}</b>` : html`<span class="faint">untitled peer</span>`}<span class="pl-key addr" title=${peer.pubkey}>${peer.pubkey.slice(0, 10)}…</span></div>
      <div class="pl-targets">${peer.targets.map(t => html`<span class="pl-t" key=${tkey(t.node, t.iface)}>
        <span class="tags">${targetTags(t.node, t.iface, t.type, t.via, !t.online)}</span><span class="pl-ip addr">${t.ip || "—"}</span></span>`)}</div>
    </div>
    <${Badge} s=${peer.status}/>
    <div class="pl-acts">
      <button class="iconbtn" title="Show QR / configs" onClick=${() => openPeerConfigs(peer)}><${Ic} i="qr"/></button>
      <button class="iconbtn" title="Download config" onClick=${download}><${Ic} i="download"/></button>
      <button class="iconbtn" title="Edit config" onClick=${() => openEditPeer(peer)}><${Ic} i="pencil"/></button>
      <button class="iconbtn" title="Copy to another interface" onClick=${() => openAddTarget(peer)}><${Ic} i="copy"/></button>
      <button class="iconbtn danger" title="Delete peer (revoke + remove)" onClick=${() => openConfirm({ title: "Delete peer", confirmLabel: "Delete", danger: true, body: "This revokes access immediately and removes the peer from every interface it's deployed on. This can't be undone.", onConfirm: () => deleteAssignedPeer(peer) })}><${Ic} i="trash"/></button>
    </div>
    <${RowError} k=${"peer:" + peer.id}/>
  </div>`;
}

// One user with all their peers underneath.
function UserGroup({ user }) {
  const peers = Store.peersOfUser(user.id).slice().sort((a, b) => STATUS_RANK[b.status] - STATUS_RANK[a.status]);
  const delUser = () => openConfirm({ title: "Delete user · " + user.name, confirmLabel: "Delete user", danger: true,
    body: "Their peers are revoked and become unassigned. This can't be undone.",
    onConfirm: () => mutate({ key: "user:" + user.id,
      patch: s => { delete s.roster.users[user.id]; for (const p of Object.values(s.roster.peers)) if (p.user_id === user.id) p.user_id = null; },
      call: () => api.userDelete({ id: user.id }) }) });
  return html`<div class="ugroup">
    <div class="ug-head">
      <div class="ug-id">
        <div class="ug-name"><a href=${"#/user/" + encodeURIComponent(user.id)}>${user.name}</a>${user.tag ? html`<span class="tagchip">${user.tag}</span>` : null}</div>
        ${user.note ? html`<div class="ug-note">${user.note}</div>` : null}
      </div>
      <${Badge} s=${user.peerCount ? user.status : "empty"}/>
      ${user.peerCount ? html`<${UsageBar} value=${user.onlineCount} total=${user.peerCount}/>` : html`<span class="faint pl-none">no peers</span>`}
      <span class="grow"></span>
      <button class="btn btn-mini" onClick=${() => openAddPeers(user.id, user.name)}><${Ic} i="plus"/> Add peer</button>
      <button class="iconbtn" title="Edit user" onClick=${() => openUserEdit(user)}><${Ic} i="pencil"/></button>
      <button class="iconbtn danger" title="Delete user" onClick=${delUser}><${Ic} i="trash"/></button>
    </div>
    ${peers.length ? html`<div class="ug-peers">${peers.map(p => html`<${PeerLine} key=${p.id} peer=${p}/>`)}</div>`
      : html`<div class="ug-empty">No peers yet — <button class="linkbtn" onClick=${() => openAddPeers(user.id, user.name)}>add one</button>.</div>`}
    <${RowError} k=${"user:" + user.id}/>
  </div>`;
}

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

    ${!users.length ? html`<div class="empty"><b>No users yet</b>Create a user, then mint peers for them — or create a peer and assign it later.</div>`
      : !shown.length ? html`<div class="empty"><b>Nothing matches</b>Clear the search.</div>`
      : html`<div class="ugroups">${shown.map(u => html`<${UserGroup} key=${u.id} user=${u}/>`)}</div>`}

    ${unassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">Unassigned peers</h2><span class="count">${unassigned.length}</span></div>
      <div class="ugroup unassigned"><div class="ug-peers">${unassigned.map(p => html`<div class="pline" key=${p.id}>
        <div class="pl-main">
          <div class="pl-title">${p.title ? html`<b>${p.title}</b>` : html`<span class="faint">untitled peer</span>`}<span class="pl-key addr">${p.pubkey.slice(0, 10)}…</span></div>
          <div class="pl-targets">${p.targets.map(t => html`<span class="pl-t" key=${tkey(t.node, t.iface)}><span class="tags">${targetTags(t.node, t.iface, t.type, t.via, !t.online)}</span><span class="pl-ip addr">${t.ip || "—"}</span></span>`)}</div>
        </div>
        <${Badge} s=${p.status}/>
        <div class="pl-acts">
          <button class="iconbtn" title="Show QR / configs" onClick=${() => openPeerConfigs(p)}><${Ic} i="qr"/></button>
          <${PeerOwnerControls} peer=${p} showDelete=${true}/>
        </div>
      </div>`)}</div></div>
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

    <div class="detail-head">
      <div class="nameline"><h1>${u.name}</h1>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}<${Badge} s=${u.peerCount ? u.status : "empty"}/>
        <button class="editname" title="Edit" onClick=${() => setEdit(true)}><${Ic} i="pencil"/></button></div>
      <div class="grow"></div>
      <button class="btn btn-ghost" onClick=${() => openAddPeers(id, u.name)}><span class="plus"><${Ic} i="plus"/></span> Add peers</button>
      <${DangerButton} label="Delete user" confirm="Delete — peers go unassigned?" className="warn" onConfirm=${() => mutate({
        key: "user:" + id,
        patch: s => {                               // optimistic: drop the user, its peers go unassigned (mirrors the cascade)
          delete s.roster.users[id];
          for (const p of Object.values(s.roster.peers)) if (p.user_id === id) p.user_id = null;
        },
        call: () => api.userDelete({ id }),
        onOk: () => go("#/users"),
      })}/>
    </div>
    <${RowError} k=${"user:" + id}/>

    ${edit ? html`<${UserEditCard} user=${u} done=${() => setEdit(false)}/>` : html`<div class="identity">
      <div class="item"><div class="k">Tag</div><div class="v">${u.tag || "—"}</div></div>
      <div class="item"><div class="k">Note</div><div class="v">${u.note || "—"}</div></div>
      <div class="item"><div class="k">Peers</div><div class="v">${u.onlineCount}/${u.peerCount} online</div></div>
      <div class="item"><div class="k">Added</div><div class="v">${ago(u.created_at)}</div></div>
    </div>`}

    <div class="section-title"><h2>Peers by interface</h2><span class="count">${peers.length}</span></div>
    <${UserPeers} user=${u}/>
  </div>`;
}

// A user's peers, grouped by the interface each deployment lands on (one QR/link per target).
function UserPeers({ user }) {
  const peers = Store.peersOfUser(user.id);
  if (!peers.length) return html`<div class="empty"><b>No peers yet</b>Add peers for ${user.name} — each interface becomes its own peer.</div>`;
  const groups = {};
  for (const p of peers) for (const t of p.targets) {
    const k = t.node + "|" + t.iface;
    (groups[k] = groups[k] || { node: t.node, iface: t.iface, items: [] }).items.push({ peer: p, t });
  }
  return html`${Object.keys(groups).sort().map(k => {
    const g = groups[k];
    return html`<div class="ifgroup" key=${k}>
      <a class="ifgroup-head" href=${"#/node/" + encodeURIComponent(g.node) + "/" + encodeURIComponent(g.iface)} title="Open interface"><span class="dot" style=${"background:" + Store.nodeColor(g.node)}></span><b>${Store.nodeName(g.node)}</b><span class="sep2">·</span><span class="ifn">${g.iface}</span><span class="tags">${(() => {
        const ty = ((g.items[0].t || {}).type || "").toLowerCase();
        const tags = [];
        if (ty === "awg") tags.push(html`<${Tag} kind="awg" label="awg"/>`);
        else if (ty === "wg") tags.push(html`<${Tag} kind="wg" label="wg"/>`);
        if (g.items.some(it => it.t.via === "turn")) tags.push(html`<${Tag} kind="turn" label="turn"/>`);
        return tags;
      })()}</span><span class="count">${g.items.length}</span><span class="rowarrow"><${Ic} i="arrow"/></span></a>
      <div class="deploys">${g.items.map(it => html`<${UserTargetCard} key=${it.peer.id + "|" + k} peer=${it.peer} t=${it.t}/>`)}</div>
    </div>`;
  })}`;
}

// Inline-editable peer title (optimistic). The operator's label to tell a user's devices apart.
function PeerTitle({ peer }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(peer.title || "");
  const save = () => {
    setEditing(false);
    mutate({ key: "peer:" + peer.id,
      patch: s => { const p = s.roster.peers[peer.id]; if (p) p.title = val.trim(); },
      call: () => api.peerUpdate({ peer_id: peer.id, title: val.trim() }) });
  };
  if (editing) return html`<span class="ptitle-edit"><input autofocus value=${val} maxlength="64" placeholder="title"
      onInput=${e => setVal(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}/>
    <button class="btn btn-mini" onClick=${save}><${Ic} i="check"/></button></span>`;
  return html`<span class="ptitle">${peer.title ? html`<b>${peer.title}</b>` : html`<span class="faint">untitled</span>`}
    <button class="editname" title="Rename peer" onClick=${() => { setVal(peer.title || ""); setEditing(true); }}><${Ic} i="pencil"/></button></span>`;
}

// One target of a user's peer: its QR/link (TargetCard) + per-target management actions.
function UserTargetCard({ peer, t }) {
  const key = "peer:" + peer.id;
  return html`<div class="utc">
    <div class="utc-title"><${PeerTitle} peer=${peer}/></div>
    <${TargetCard} peer=${peer} t=${t}/>
    <div class="utc-acts">
      <span class="addr" title=${peer.pubkey}>${peer.pubkey.slice(0, 14)}…</span>
      <span class="grow"></span>
      <button class="btn btn-mini" onClick=${() => openEditPeer(peer)}><${Ic} i="pencil"/> Config</button>
      <button class="btn btn-mini" onClick=${() => openAddTarget(peer)}>Copy → iface</button>
      ${peer.targets.length > 1 ? html`<${DangerButton} label="Remove here" confirm="Remove here?" onConfirm=${() => mutate({
        key, patch: s => { const pp = s.roster.peers[peer.id]; if (pp) pp.targets = pp.targets.filter(x => !(x.node === t.node && x.iface === t.iface)); },
        call: () => api.peerRemoveTarget({ peer_id: peer.id, node: t.node, iface: t.iface }),
      })}/>` : null}
      <${DangerButton} label="Delete" confirm="Delete peer — revoke + remove?" onConfirm=${() => deleteAssignedPeer(peer)}/>
      <${RowError} k=${key}/>
    </div>
  </div>`;
}

// Delete an assigned peer from the user view: unassign (revokes via PSK rotation) then delete,
// honouring the gate that a live credential is never one-click-deleted without revocation.
function deleteAssignedPeer(peer) {
  return mutate({
    key: "peer:" + peer.id,
    patch: s => { delete s.roster.peers[peer.id]; },
    call: async () => {
      const r1 = await api.peerUnassign({ peer_id: peer.id });
      if (!r1.ok) return r1;
      return api.peerDelete({ peer_id: peer.id });
    },
  });
}

function UserEditCard({ user, done }) {
  const [name, setName] = useState(user.name || "");
  const [tag, setTag] = useState(user.tag || "");
  const [note, setNote] = useState(user.note || "");
  const save = async () => {
    if (!name.trim()) { toast("Name can't be empty.", "err"); return; }
    done();   // close the editor immediately; the row updates optimistically
    mutate({
      key: "user:" + user.id,
      patch: s => { const u = s.roster.users[user.id]; if (u) { u.name = name.trim(); u.tag = tag.trim(); u.note = note; } },
      call: () => api.userUpdate({ id: user.id, name: name.trim(), tag: tag.trim(), note }),
    });
  };
  return html`<div class="card" style="max-width:560px">
    <div class="field"><label>Name</label><input value=${name} onInput=${e => setName(e.target.value)} maxlength="64"/></div>
    <div class="field"><label>Tag</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder="Friend, Family, Work…" maxlength="32"/></div>
    <div class="field"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="Uses iPhone and router" maxlength="200"/></div>
    <div style="display:flex;gap:8px;margin-top:6px"><button class="btn btn-primary" onClick=${save}>Save</button><button class="btn btn-ghost" onClick=${done}>Cancel</button></div>
  </div>`;
}

// one credential: its targets, each a QR card; owner controls + edit + add-target
function PeerCard({ peer }) {
  return html`<div class="peercard">
    <div class="peercard-head">
      <span class="ptitle-h"><${PeerTitle} peer=${peer}/></span>
      <span class="addr">${peer.pubkey.slice(0, 16)}…</span>
      <button class="copybtn" title="Copy public key" onClick=${() => copy(peer.pubkey, "Public key copied")}><${Ic} i="copy"/></button>
      <span class="grow"></span>
      ${peer.unassigned ? null : html`<button class="btn btn-mini" onClick=${() => openEditPeer(peer)}><${Ic} i="pencil"/> Config</button>`}
      <span class="assignwrap"><${PeerOwnerControls} peer=${peer} showDelete=${true}/></span>
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
  useEffect(() => { let ok = true; getConfig(peer.pubkey, t.node, t.iface).then(c => { if (ok) { setConf(c); setLoaded(true); } }); return () => { ok = false; }; }, [peer.pubkey, t.node, t.iface, Store.configEpoch]);
  const col = Store.nodeColor(t.node);
  const obs = t.observed;
  const tps = turnProxiesFor(t.node, t.iface);
  const dnode = Store.nodeName(t.node);
  const label = (peer.name || "peer") + " · " + dnode + "/" + t.iface;

  return html`<div class="deploy">
    <div class="deploy-head"><span class="dot" style=${{ background: col }}></span><span class="nm">${dnode} · ${t.iface}</span><span class="grow"></span><${Badge} s=${t.status}/></div>
    <div class="deploy-body">
      ${conf ? html`<${QR} conf=${conf} label=${label}/>`
        : html`<div class="qr-none">${!loaded ? "loading…"
            : Store.storeConfigs ? "No stored config — re-issue this peer to enable its QR & download."
            : "Config shown right after creation, or enable store_configs to keep it."}</div>`}
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
      <button class="btn btn-mini" onClick=${() => downloadConf(conf, (peer.name || "peer") + "-" + dnode)}><${Ic} i="download"/> Config</button>
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
    <div class="detail-head"><div class="nameline"><h1>${p.title || p.name || "Unassigned peer"}</h1>${p.title && p.name ? html`<span class="tagchip">${p.name}</span>` : null}<${Badge} s=${p.unassigned ? "unassigned" : p.status}/></div></div>
    <${PeerCard} peer=${p}/>
  </div>`;
}

// ═════════════════════════ SCREEN: NODES ═════════════════════════
const SWATCHES = ["#34d399", "#22d3ee", "#e8c04b", "#f0913c", "#f0596b", "#c084e8", "#7dd3fc", "#a3e635"];
function NodesScreen() {
  useStore();
  const ns = Store.nodes || [];
  return html`<div class="screen">
    <div class="section-title" style="margin:6px 2px 16px"><h2>Nodes</h2><span class="count">${ns.length + (ns.length === 1 ? " server" : " servers")}</span>
      <span class="nodehint">Entry servers run <span class="mono">swg-noded</span>, which syncs to this panel over HTTPS — the node needs no inbound access.</span><span class="grow"></span>
      <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> Add node</button></div>
    ${!ns.length ? html`<div class="empty"><b>No nodes yet</b>Add your first entry server — you'll get a one-time command to run on it.</div>`
      : html`<div class="nodegrid">${ns.map(n => html`<${NodeCard} key=${n.id} n=${n}/>`)}</div>`}
  </div>`;
}
// load/util tone: green under 70%, amber to 90%, red above.
function htone(pct) { return pct >= 90 ? "hot" : (pct >= 70 ? "warn" : "ok"); }
// Threshold alerts for a node: disk/memory > 90%, CPU saturated (load-per-core > 1.5).
function healthAlerts(health) {
  const out = [];
  for (const d of (health && health.disk || [])) if (d.total && d.used / d.total > 0.9) out.push({ sev: "hot", msg: "disk " + d.mount + " " + Math.round(d.used / d.total * 100) + "%" });
  const m = health && health.mem;
  if (m && m.total && m.used / m.total > 0.9) out.push({ sev: "hot", msg: "memory " + Math.round(m.used / m.total * 100) + "%" });
  if (health && Array.isArray(health.load) && (health.load[0] || 0) / (health.ncpu || 1) > 1.5) out.push({ sev: "warn", msg: "CPU load " + health.load[0].toFixed(1) });
  return out;
}
// Tiny inline-SVG sparkline (no charting lib). `points` is an array of numbers 0..100.
function Sparkline({ points, color, w, h }) {
  w = w || 90; h = h || 22;
  const pts = (points || []).filter(v => v != null);
  if (pts.length < 2) return html`<svg class="spark" width=${w} height=${h}></svg>`;
  const max = 100, n = pts.length;
  const d = pts.map((v, i) => (i / (n - 1) * (w - 2) + 1).toFixed(1) + "," + (h - 1 - Math.min(max, Math.max(0, v)) / max * (h - 2)).toFixed(1)).join(" ");
  const last = pts[pts.length - 1];
  return html`<svg class="spark" width=${w} height=${h} viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none">
    <polyline points=${d} fill="none" stroke=${color || "var(--online)"} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx=${(w - 1).toFixed(1)} cy=${(h - 1 - Math.min(max, Math.max(0, last)) / max * (h - 2)).toFixed(1)} r="1.6" fill=${color || "var(--online)"}/>
  </svg>`;
}
const toneColor = t => t === "hot" ? "var(--dangling)" : t === "warn" ? "var(--pending)" : "var(--online)";
function HealthMeter({ label, pct, text, tone, spark }) {
  const p = Math.min(100, Math.max(0, pct || 0));
  const tn = tone || htone(p);
  return html`<div class="hmeter">
    <div class="hm-top"><span class="hm-l">${label}</span><span class="hm-r">${text}</span></div>
    <div class="hm-row">
      <div class="hm-bar"><i class=${"hm-fill " + tn} style=${"width:" + p + "%"}></i></div>
      ${spark && spark.length > 1 ? html`<${Sparkline} points=${spark} color=${toneColor(tn)}/>` : null}
    </div>
  </div>`;
}
// Gradient area chart for a history series (0–100). Stretches to its container width;
// the stroke stays crisp via non-scaling-stroke. Used for the CPU-load history.
function MiniArea({ points, color, h }) {
  const pts = (points || []).filter(v => v != null);
  h = h || 42; const w = 100;
  if (pts.length < 2) return html`<div class="harea-empty">collecting history…</div>`;
  // tight autoscale to the series' own min/max (small vpad) so CPU reads as a jagged "heartbeat"
  const n = pts.length, lo = Math.min(...pts), hi = Math.max(...pts), range = (hi - lo) || 1, vpad = h * 0.06;
  const xy = pts.map((v, i) => [i / (n - 1) * w, h - vpad - ((v - lo) / range) * (h - 2 * vpad)]);
  const line = xy.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = "0," + h + " " + line + " " + w + "," + h;
  const gid = "ha" + (MiniArea._n = (MiniArea._n || 0) + 1);
  return html`<svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
    <defs><linearGradient id=${gid} x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color=${color} stop-opacity="0.32"/><stop offset="1" stop-color=${color} stop-opacity="0"/>
    </linearGradient></defs>
    <polygon points=${area} fill=${"url(#" + gid + ")"}/>
    <polyline points=${line} fill="none" stroke=${color} stroke-width="1.4" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

// Throughput history: rx as a filled area + tx as a line, scaled to the series max.
function ThroughputChart({ rx, tx, h, head }) {
  const R = (rx || []).map(v => v || 0), T = (tx || []).map(v => v || 0);
  const n = Math.max(R.length, T.length);
  const curR = R[R.length - 1] || 0, curT = T[T.length - 1] || 0;
  const hi = n ? Math.max(0, ...R, ...T) : 0;
  const legend = html`<div class="tp-legend"><span class="tp-k"><i class="sw rx"></i>↓ ${rate(curR)}</span><span class="tp-k"><i class="sw tx"></i>↑ ${rate(curT)}</span><span class="tp-peak">peak ${rate(hi)}</span><span class="grow"></span>${head || null}</div>`;
  // Only collapse to a slim strip when there genuinely aren't enough points yet. A flat-zero
  // window still draws the chart (baseline line) so LIVE/HOUR/DAY stay visually consistent.
  if (n < 2)
    return html`<div class="tp-wrap">${legend}<div class="tp-idle">collecting throughput history…</div></div>`;
  h = h || 60; const w = 100;
  // autoscale to the combined min/max so the curve is spiky/expressive, not a flat baseline
  const lo = Math.min(...R, ...T), range = (hi - lo) || 1, vpad = h * 0.12;
  const X = i => i / (n - 1) * w, Y = v => h - vpad - ((v - lo) / range) * (h - 2 * vpad);
  const line = arr => arr.map((v, i) => X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(" ");
  const rxLine = line(R), rxArea = "0," + h + " " + rxLine + " " + w + "," + h;
  const gid = "tp" + (ThroughputChart._n = (ThroughputChart._n || 0) + 1);
  return html`<div class="tp-wrap">
    ${legend}
    <svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
      <defs><linearGradient id=${gid} x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="var(--brand)" stop-opacity="0.30"/><stop offset="1" stop-color="var(--brand)" stop-opacity="0"/>
      </linearGradient></defs>
      <polygon points=${rxArea} fill=${"url(#" + gid + ")"}/>
      <polyline points=${rxLine} fill="none" stroke="var(--brand)" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
      <polyline points=${line(T)} fill="none" stroke="var(--tp-tx)" stroke-width="1.2" vector-effect="non-scaling-stroke" stroke-dasharray="3 2"/>
    </svg>
  </div>`;
}

// Inline "x of y" usage bar for table rows — a compact track + count.
function UsageBar({ value, total, color }) {
  const v = value || 0, tt = total || 0, pct = tt ? Math.min(100, v / tt * 100) : 0;
  return html`<span class="usebar" title=${v + " / " + tt}>
    <span class="usebar-t"><i style=${"width:" + pct + "%;background:" + (color || "var(--online)")}></i></span>
    <span class="usebar-n">${v}<small>/${tt}</small></span>
  </span>`;
}
// interface tags for a node: each iface coloured by protocol, linking to its detail.
function ifaceTags(node) {
  const meta = Store.describe[node] || {};
  return Object.keys(meta).map(ifn => {
    const type = (meta[ifn].awg_params && Object.keys(meta[ifn].awg_params).length) ? "awg" : "wg";
    return html`<a class=${"tg tg-" + type} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(ifn)} onClick=${e => e.stopPropagation()}>${ifn}</a>`;
  });
}

// A ranked horizontal-bar list. rows: [{label, value, sub, color, href}].
function RankBars({ rows }) {
  const mx = Math.max(1, ...rows.map(r => r.value || 0));
  if (!rows.length) return html`<div class="harea-empty">no data</div>`;
  return html`<div class="rankbars">${rows.map(r => html`<a class="rb" href=${r.href || "#"} key=${r.label}>
    <span class="rb-label">${r.label}</span>
    <span class="rb-track"><i style=${"width:" + Math.max(2, (r.value || 0) / mx * 100) + "%;background:" + (r.color || "var(--brand)")}></i></span>
    <span class="rb-val">${r.sub}</span>
  </a>`)}</div>`;
}

// A history chart (CPU or throughput) with live/day/week/month range tabs. "live" uses the
// series already in /api/state; day/week/month are fetched on demand from /api/node-history.
const HIST_RANGES = ["live", "hour", "day", "week", "month"];
const HIST_WIN = { live: 600, hour: 3600, day: 86400, week: 604800, month: 2592000 };  // seconds each range spans
const tailSeries = (s, n) => { const o = {}; for (const k of ["t", "cpu", "mem", "disk", "rx", "tx"]) if (Array.isArray((s || {})[k])) o[k] = s[k].slice(-n); return o; };
// shown instead of a misleading chart when the node hasn't collected enough history for the range
function HistMsg({ span, need, range }) {
  return html`<div class="harea-msg"><${Ic} i="info"/><span>This node has only <b>${dur(span)}</b> of history so far — the <b>${range}</b> view needs about <b>${dur(need)}</b>. It'll fill in as the node keeps running.</span></div>`;
}
function RangedHistory({ node, kind, live, h, head }) {
  const [range, setRange] = useState("live");
  const [fetched, setFetched] = useState(null);
  const [loading, setLoading] = useState(false);
  const fetchRange = range === "day" || range === "week" || range === "month";   // live/hour come from /api/state
  useEffect(() => {
    if (!fetchRange) { setFetched(null); setLoading(false); return; }
    let ok = true; setLoading(true);
    api.nodeHistory(node, range).then(r => { if (ok) { setFetched(r && r.ok ? r.data : {}); setLoading(false); } }).catch(() => { if (ok) setLoading(false); });
    return () => { ok = false; };
  }, [node, range]);
  // live = last 10 minute-buckets, hour = the full ~60-pt /api/state series, longer ranges fetched
  const s = range === "live" ? tailSeries(live, 10) : range === "hour" ? (live || {}) : (fetched || {});
  // the node may not have run long enough to fill this range — detect from the data's own time span
  const tt = (s.t || []).filter(x => x != null);
  const span = tt.length > 1 ? (tt[tt.length - 1] - tt[0]) : 0;
  const need = HIST_WIN[range] || 0;
  const sparse = !loading && tt.length > 1 && need && span < need * 0.7;
  const tabs = html`<div class="rangetabs">${HIST_RANGES.map(t => html`<button class=${"rtab" + (range === t ? " on" : "")} onClick=${() => setRange(t)}>${t}</button>`)}</div>`;
  if (kind === "throughput") {
    const tpinner = loading ? html`<div class="harea-empty">loading ${range}…</div>`
      : sparse ? html`<${HistMsg} span=${span} need=${need} range=${range}/>` : null;
    if (tpinner) return html`<div class="tp-wrap"><div class="tp-legend"><span class="grow"></span>${tabs}</div>${tpinner}</div>`;
    return html`<${ThroughputChart} rx=${s.rx} tx=${s.tx} h=${h} head=${tabs}/>`;
  }
  return html`<div class="chartwrap">
    <div class="chart-head">${head || null}<span class="grow"></span>${tabs}</div>
    ${loading ? html`<div class="harea-empty">loading ${range}…</div>`
      : sparse ? html`<${HistMsg} span=${span} need=${need} range=${range}/>`
      : html`<${MiniArea} points=${s.cpu} color="var(--online)" h=${h}/>`}
  </div>`;
}

// Per-node health: CPU / Memory / Disk on one row (each a third), with the CPU-load history
// charted below. `history=false` omits the inline chart (node detail uses RangedHistory instead).
// The CPU/Memory/Disk meter row — reused standalone (as the head of the node-detail Health
// chart row) and inside NodeHealth (overview cards).
function healthCols(health) {
  const cols = [];
  if (Array.isArray(health.load)) {
    const ncpu = health.ncpu || 1, l1 = health.load[0] || 0;
    cols.push({ label: "CPU load", pct: l1 / ncpu * 100, text: l1.toFixed(2) + " / " + ncpu + (ncpu === 1 ? " cpu" : " cpus") });
  }
  const m = health.mem;
  if (m && m.total) cols.push({ label: "Memory", pct: m.used / m.total * 100, text: fmtBytes(m.used) + " / " + fmtBytes(m.total) });
  const d0 = (health.disk || [])[0];
  if (d0 && d0.total) cols.push({ label: "Disk", pct: d0.used / d0.total * 100, text: fmtBytes(d0.used) + " / " + fmtBytes(d0.total) });
  return cols;
}
function HealthMeters({ health }) {
  return html`<div class="health-cols">${healthCols(health).map(c => {
    const p = Math.min(100, Math.max(0, c.pct || 0)), tn = htone(p);
    return html`<div class="hcol">
      <div class="hcol-top"><span class="hcol-l">${c.label}</span><span class="hcol-v">${c.text}</span></div>
      <div class="hm-bar"><i class=${"hm-fill " + tn} style=${"width:" + p + "%"}></i></div>
    </div>`;
  })}</div>`;
}
function HealthAlerts({ health }) {
  const alerts = healthAlerts(health);
  return alerts.length ? html`<div class="halerts">${alerts.map(a => html`<span class=${"halert " + a.sev}><${Ic} i="warn"/> ${a.msg}</span>`)}</div>` : null;
}
function NodeHealth({ health, node, compact, history }) {
  if (!health) return compact ? null : html`<div class="hint" style="margin:2px">No health data reported yet.</div>`;
  const hh = (node && (Store.nodes || []).find(n => n.id === node) || {}).health_history || null;  // server-side RRD (node = id)
  const cpuHist = (hh && Array.isArray(hh.cpu) && hh.cpu.length > 1) ? hh.cpu : null;
  return html`<div class="health">
    <${HealthAlerts} health=${health}/>
    <${HealthMeters} health=${health}/>
    ${(history !== false && cpuHist) ? html`<div class="health-hist">
      <span class="hist-cap">CPU history</span>
      <${MiniArea} points=${cpuHist} color="var(--online)" h=${compact ? 36 : 52}/>
    </div>` : null}
  </div>`;
}

function NodeCard({ n }) {
  const st = n.status || "dangling";
  const stTxt = st === "online" ? "reporting" : (st === "offline" ? "offline" : "awaiting enroll");
  const ifTags = ifaceTags(n.id);
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === n.id));
  const onl = here.filter(p => p.targets.some(t => t.node === n.id && t.online)).length;
  const snap = Store.stats[n.id];
  const tps = (snap && snap.turn_proxies) || [];
  const h = n.health, hasCpu = h && Array.isArray(h.load);
  const l1 = hasCpu ? (h.load[0] || 0) : 0, cpct = Math.min(100, l1 / ((h && h.ncpu) || 1) * 100);
  const removing = n.removing;
  const nav = () => go("#/node/" + encodeURIComponent(n.id));
  return html`<div class=${"ncard clk" + (removing ? " removing" : "")} onClick=${nav}>
    <div class="ntop">
      <span class="nname">${n.name}</span>
      <span class=${"tport" + (n.transport === "https" ? " https" : "")}>${n.transport}</span>
      <span class=${"nstat " + st}>${stTxt}</span>
      ${removing ? html`<span class="badge b-removing ic"><${Ic} i="trash"/>flagged for removal</span>` : null}
      <span class="grow"></span>
      <span class="nm-item nm-cpuitem"><span class="nm-l">CPU load</span>${hasCpu ? html`<span class="nm-cpu"><span class="hm-bar"><i class=${"hm-fill " + htone(cpct)} style=${"width:" + cpct + "%"}></i></span><span class="nm-v">${l1.toFixed(2)}</span></span>` : html`<span class="nm-v faint">—</span>`}</span>
    </div>
    <div class="nmeta">
      <span class="nm-item"><span class="nm-l">Peers</span>${here.length ? html`<span class="nm-v nm-peers">${onl}<small>/${here.length}</small></span>` : html`<span class="nm-v nm-peers faint">none</span>`}</span>
      <span class="nm-item"><span class="nm-l">Interfaces</span>${ifTags.length ? html`<span class="tags">${ifTags}</span>` : html`<span class="nm-v faint">—</span>`}</span>
      <span class="nm-item"><span class="nm-l">Turn-proxies</span>${tps.length ? html`<span class="tags">${tps.map(tp => html`<span class="tg tg-turn">${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`)}</span>` : html`<span class="nm-v faint">—</span>`}</span>
      <span class="nm-item nm-thru"><span class="nm-v thru"><span class="down">↓ ${rate(n.rx_speed)}</span><span class="up">↑ ${rate(n.tx_speed)}</span></span></span>
    </div>
    <div class="nacts" onClick=${e => e.stopPropagation()}>
      <button class="iconbtn" title="Edit node" onClick=${() => openNodeEdit(n)}><${Ic} i="pencil"/></button>
      <button class="iconbtn" title="Rotate token" onClick=${() => openNodeRotate(n)}><${Ic} i="key"/></button>
      <button class="iconbtn danger" title=${removing ? "Force remove" : "Remove node"} onClick=${() => openNodeRemove(n)}><${Ic} i="trash"/></button>
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
    if (user.includes(":")) return setMsg({ ok: false, t: "Username can't contain a colon." });
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

// Account form as a modal (opened from the header user icon).
function AccountSheet() {
  const [user, setUser] = useState("");
  const [cur, setCur] = useState(""); const [np, setNp] = useState(""); const [np2, setNp2] = useState("");
  const [msg, setMsg] = useState(null); const [enabled, setEnabled] = useState(true);
  useEffect(() => { api.account().then(r => { if (r && r.ok) { if (r.data.username) setUser(r.data.username); if (!r.data.auth_enabled) { setEnabled(false); setMsg({ ok: false, t: "This panel has no login configured — changes are disabled." }); } } }); }, []);
  const save = async () => {
    if (!user.trim()) return setMsg({ ok: false, t: "Username can't be empty." });
    if (user.includes(":")) return setMsg({ ok: false, t: "Username can't contain a colon." });
    if (!cur) return setMsg({ ok: false, t: "Enter your current password to confirm." });
    if (np && np !== np2) return setMsg({ ok: false, t: "New passwords don't match." });
    if (np && np.length < 8) return setMsg({ ok: false, t: "New password must be at least 8 characters." });
    setMsg({ ok: true, t: "Saving…" });
    const r = await api.accountSave({ username: user.trim(), current_password: cur, new_password: np });
    if (!r.ok) return setMsg({ ok: false, t: r.error || "Failed to update." });
    setMsg({ ok: true, t: "Updated. Reloading — sign in with your new credentials…" });
    setTimeout(() => location.reload(), 1400);
  };
  return html`<${Sheet} title="Account"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Close</button><button class="btn btn-primary" disabled=${!enabled} onClick=${save}>Save changes</button></>`}>
    <p class="hint" style="margin:0 0 16px">Change the panel username and password. Takes effect immediately — you'll be asked to sign in again.</p>
    ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
    <div class="field"><label>Username</label><input autofocus value=${user} onInput=${e => setUser(e.target.value)} autocomplete="username"/></div>
    <div class="field"><label>Current password</label><input type="password" value=${cur} onInput=${e => setCur(e.target.value)} autocomplete="current-password" placeholder="required to confirm changes"/></div>
    <div class="field"><label>New password</label><input type="password" value=${np} onInput=${e => setNp(e.target.value)} autocomplete="new-password" placeholder="leave blank to keep current"/></div>
    <div class="field"><label>Confirm new password</label><input type="password" value=${np2} onInput=${e => setNp2(e.target.value)} autocomplete="new-password"/></div>
  <//>`;
}

// ═════════════════════════ MODALS / SHEETS ═════════════════════════
// Universal dialog behaviours live here so every sheet gets them for free (no per-sheet code):
//  • autofocus the first field on open
//  • Enter submits (clicks the primary button) unless you're in a textarea
//  • Esc / backdrop closes — but if any field changed, it warns before discarding
//  • Tab is trapped within the dialog
// Dirtiness is detected by snapshotting field values on open and comparing live, so it works
// regardless of which inputs a given sheet renders.
// `onClose` is the single dismiss target for EVERY exit path — ✕, Esc, overlay-click, the discard
// confirm. Openers pass the place to return to (e.g. reopen the peer view); default just closes.
// Cancel/Save buttons in a sheet's foot should call the same target so all paths land identically.
function Sheet({ title, children, foot, onClose }) {
  onClose = onClose || closeModal;
  const ref = useRef(null);
  const dirty = useRef(false);   // set by a real user edit — programmatic value changes don't fire input/change
  const discardRef = useRef(false);             // armed once; read live so the captured onKey closure stays correct
  const [discard, setDiscardState] = useState(false);
  const setDiscarding = v => { discardRef.current = v; setDiscardState(v); };
  const fields = () => Array.from(ref.current ? ref.current.querySelectorAll("input,textarea,select") : []);
  // closing a dirty sheet swaps the footer into an inline "discard?" confirm instead of a native dialog.
  const tryClose = () => { if (dirty.current && !discardRef.current) { setDiscarding(true); return; } onClose(); };

  useEffect(() => {
    const root = ref.current; if (!root) return;
    const onEdit = () => { dirty.current = true; };
    root.addEventListener("input", onEdit, true);
    root.addEventListener("change", onEdit, true);
    const first = root.querySelector("[autofocus]") || root.querySelector("input,textarea,select,button.btn-primary");
    if (first) setTimeout(() => { try { first.focus(); } catch (_) {} }, 0);
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); tryClose(); return; }
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && !e.shiftKey) {
        const primary = root.querySelector(".sheet-foot .btn-primary:not([disabled])") || root.querySelector(".btn-primary:not([disabled])");
        if (primary) { e.preventDefault(); primary.click(); }
        return;
      }
      if (e.key === "Tab") {                                   // focus trap
        const f = fields().concat(Array.from(root.querySelectorAll("button"))).filter(el => !el.disabled && el.offsetParent !== null);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);          // capture so it works regardless of focus
    return () => {
      document.removeEventListener("keydown", onKey, true);
      root.removeEventListener("input", onEdit, true);
      root.removeEventListener("change", onEdit, true);
    };
  }, []);

  return html`<div class="overlay show" onClick=${e => { if (e.target.classList.contains("overlay")) tryClose(); }}>
    <div class="sheet" role="dialog" aria-modal="true" ref=${ref}>
      <div class="sheet-head"><h3>${title}</h3><button class="x" onClick=${tryClose}>×</button></div>
      <div class="sheet-body">${children}</div>
      <div class="sheet-foot">${discard
        ? html`<${Fragment}><span class="discard-msg"><${Ic} i="warn"/> Discard unsaved changes?</span><span class="grow"></span>
            <button class="btn btn-ghost" onClick=${() => setDiscarding(false)}>Keep editing</button>
            <button class="btn btn-danger" onClick=${onClose}>Discard</button></>`
        : foot}</div>
    </div></div>`;
}

// Designed confirmation modal — the in-app replacement for native confirm(). `danger` paints the
// action button red; `danger`/`warn` give the notice a warn tint + icon (else a neutral info note).
// `back` (optional) = where Cancel / Esc returns to (e.g. reopen the peer view it was launched from);
// default just closes. After a confirmed action we always close, since the action changed the state.
function openConfirm(opts) { openModal(html`<${ConfirmSheet} ...${opts}/>`); }
function ConfirmSheet({ title, body, confirmLabel, danger, warn, onConfirm, back }) {
  back = back || closeModal;
  const [busy, setBusy] = useState(false);
  const go = async () => { if (busy) return; setBusy(true); try { await onConfirm(); } finally { closeModal(); } };
  const tone = danger || warn;
  return html`<${Sheet} title=${title} onClose=${back}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${back}>Cancel</button>
      <button class=${"btn " + (danger ? "btn-danger" : "btn-primary")} disabled=${busy} onClick=${go}>${confirmLabel || "Confirm"}</button></>`}>
    <div class=${"notice" + (tone ? " warn" : "")}><${Ic} i=${tone ? "warn" : "info"}/><span>${body}</span></div>
  <//>`;
}

// New user — identity, then optionally straight into adding peers (one per interface).
function openCreateUser() { openModal(html`<${CreateUserSheet}/>`); }
function CreateUserSheet() {
  const [name, setName] = useState(""); const [tag, setTag] = useState(""); const [note, setNote] = useState(""); const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const createUser = async () => {
    if (!name.trim()) { setMsg({ k: "err", t: "Give the user a name." }); return null; }
    setBusy(true); setMsg({ k: "work", t: "creating…" });
    const r = await api.userCreate({ name: name.trim(), tag: tag.trim(), note });
    setBusy(false);
    if (!r.ok) { setMsg({ k: "err", t: r.error || "couldn't create user" }); return null; }
    Store.recentlyCreated[r.data.id] = Date.now(); await Store.poll();
    return r.data;
  };
  const createOnly = async () => { const u = await createUser(); if (u) { closeModal(); go("#/user/" + encodeURIComponent(u.id)); } };
  const createAndAdd = async () => { const u = await createUser(); if (u) openModal(html`<${AddPeersSheet} userId=${u.id} userName=${u.name}/>`); };
  return html`<${Sheet} title="New user"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-ghost" disabled=${busy} onClick=${createOnly}>Create only</button><button class="btn btn-primary" disabled=${busy} onClick=${createAndAdd}>Add peers ▸</button></>`}>
    <div class="field"><label>Name</label><input autofocus value=${name} onInput=${e => setName(e.target.value)} placeholder="Alex"/></div>
    <div class="field"><label>Tag</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder="Friend"/></div>
    <div class="field"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="Uses iPhone and router"/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// Mint one peer per chosen interface for a user (own key each). Used by create-user step 2 and
// the user-detail "Add peers" button. Excludes interfaces the user is already on.
function openAddPeers(userId, userName) { openModal(html`<${AddPeersSheet} userId=${userId} userName=${userName}/>`); }
function AddPeersSheet({ userId, userName }) {
  const [chosen, setChosen] = useState([]);
  const cf = useConfigFields();
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const have = new Set((Store.peersOfUser(userId) || []).flatMap(p => p.targets.map(t => tkey(t.node, t.iface))));
  useEffect(() => {
    if (!cf.dnsTouched.current && chosen.length) { const m = Store.ifaceMeta(chosen[0].node, chosen[0].iface); if (m) cf.setDns((m.dns || []).join(", ")); }
  }, [chosen]);
  const finish = () => { closeModal(); go("#/user/" + encodeURIComponent(userId)); };
  const create = async () => {
    if (!chosen.length) return setMsg({ k: "err", t: "Pick at least one interface." });
    const badIp = chosen.find(t => !V.ipv4(String(t.ip).trim()));
    if (badIp) return setMsg({ k: "err", t: "Invalid address for " + Store.nodeName(badIp.node) + "/" + badIp.iface + "." });
    const ce = configErrors(cf); const ck = Object.keys(ce)[0];
    if (ck) return setMsg({ k: "err", t: ce[ck] });
    setBusy(true); setMsg({ k: "work", t: "minting " + chosen.length + " peer" + (chosen.length > 1 ? "s" : "") + "…" });
    const res = await createPeersForTargets(userId, chosen, cf.opts());
    setBusy(false); await Store.poll();
    if (res.fails.length) toast("Some peers failed: " + res.fails.join("; "), "err", 6000);
    finish();
  };
  return html`<${Sheet} title=${"Add peers" + (userName ? " · " + userName : "")}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${finish}>Skip</button><button class="btn btn-primary" disabled=${busy} onClick=${create}>Create ${chosen.length || ""} peer${chosen.length === 1 ? "" : "s"}</button></>`}>
    <div class="hint" style="margin-bottom:10px">Each interface becomes its own peer (own key) — one QR per peer. Add redundancy later with “copy to another interface”.</div>
    <div class="field"><label>Interfaces</label><${TargetPicker} exclude=${have} onChange=${setChosen}/></div>
    <${AdvancedFields} st=${cf}/>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// All deployable (node, iface) targets known from the consolidated state.
function allTargets() {
  const out = [];
  for (const node of Object.keys(Store.describe)) for (const iface of Object.keys(Store.describe[node] || {})) out.push({ node, iface });
  return out;
}

// Reusable (node,iface) picker with per-target IP allocation. `exclude` is a Set of tkeys
// to hide (interfaces a user is already on); `onChange` receives the chosen target list
// [{node,iface,ip,ipHint}]. Used by the create-peer, create-user and add-peers flows.
function TargetPicker({ prefill, exclude, onChange }) {
  const all = useMemo(allTargets, [Store.describe]);
  const targets = exclude ? all.filter(t => !exclude.has(tkey(t.node, t.iface))) : all;
  const [sel, setSel] = useState({});
  const allocIp = async (node, iface) => {
    const k = tkey(node, iface);
    setSel(s => ({ ...s, [k]: { node, iface, ip: "", ipHint: "finding a free address…" } }));
    const r = await api.nextIp([node], iface);
    setSel(s => s[k] ? { ...s, [k]: { node, iface, ip: r.ok ? String(r.data.next_ip).split("/")[0] : "", ipHint: r.ok ? "" : (r.error || "no free address") } } : s);
  };
  const toggle = (node, iface) => {
    const k = tkey(node, iface);
    if (sel[k]) setSel(s => { const n = { ...s }; delete n[k]; return n; });
    else allocIp(node, iface);
  };
  const setIp = (k, v) => setSel(s => s[k] ? { ...s, [k]: { ...s[k], ip: v } } : s);
  useEffect(() => {                                  // preselect from prefill once targets are known
    if (!targets.length || Object.keys(sel).length) return;
    if (prefill && prefill.node && prefill.iface) allocIp(prefill.node, prefill.iface);
    else if (prefill && prefill.node) targets.filter(t => t.node === prefill.node).slice(0, 1).forEach(t => allocIp(t.node, t.iface));
  }, [all]);
  useEffect(() => { onChange(Object.values(sel)); }, [sel]);

  if (!targets.length) return html`<div class="hint">No interfaces available — is a node online?</div>`;
  return html`<div class="targetpick">${targets.map(t => {
    const k = tkey(t.node, t.iface); const s = sel[k];
    return html`<div class=${"targetopt " + (s ? "sel" : "")}>
      <label class="topt-main" onClick=${() => toggle(t.node, t.iface)}>
        <span class="box">${s ? html`<${Ic} i="check"/>` : ""}</span>
        <span class="swatch" style=${"background:" + Store.nodeColor(t.node)}></span>
        <span class="nm">${Store.nodeName(t.node)}</span><span class="tp">${t.iface}</span></label>
      ${s ? html`<input class=${"topt-ip " + (s.ip && !V.ipv4(s.ip) ? "bad" : "")} value=${s.ip} placeholder=${s.ipHint || "address"} title=${s.ip && !V.ipv4(s.ip) ? "not a valid IPv4 address" : ""} onInput=${e => setIp(k, e.target.value)}/>` : null}
    </div>`;
  })}</div>`;
}

// Advanced client-config fields (DNS / MTU / keepalive / AllowedIPs) — shared by the
// peer-minting sheets. `v` is a {dns,mtu,keepalive,allowed,dnsTouched} ref-ish object.
function AdvancedFields({ st, startOpen }) {
  const [open, setOpen] = useState(!!startOpen);
  const errs = configErrors(st);
  const fld = (k, fallback) => (errs[k] ? html`<div class="hint err">${errs[k]}</div>` : html`<div class="hint">${fallback}</div>`);
  return html`<${Fragment}>
    <button class="advtoggle" onClick=${() => setOpen(o => !o)}><span>${open ? "▾" : "▸"}</span> Advanced${Object.keys(errs).length ? html` <span class="advbad">${Object.keys(errs).length} issue${Object.keys(errs).length > 1 ? "s" : ""}</span>` : ""}</button>
    ${open ? html`<div class="adv open">
      <div class="field" style="margin-top:8px"><label>Client allowed IPs (routing)</label>
        <input class=${errs.allowed ? "bad" : ""} value=${st.allowed} onInput=${e => st.set("allowed", e.target.value)}/>${fld("allowed", "Full tunnel by default. Narrow for split tunnel.")}</div>
      <div class="field"><label>DNS</label>
        <input class=${errs.dns ? "bad" : ""} value=${st.dns} onInput=${e => { st.dnsTouched.current = true; st.set("dns", e.target.value); }} placeholder="from server, or e.g. 1.1.1.1"/>${fld("dns", "Comma-separated IPs. Blank = no DNS line.")}</div>
      <div class="row2">
        <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} value=${st.mtu} onInput=${e => { if (st.mtuTouched) st.mtuTouched.current = true; st.set("mtu", e.target.value); }} placeholder="1280"/>${fld("mtu", "Blank = 1280.")}</div>
        <div class="field"><label>Persistent keepalive (s)</label><input class=${errs.keepalive ? "bad" : ""} value=${st.keepalive} onInput=${e => st.set("keepalive", e.target.value)} placeholder="25"/>${fld("keepalive", "0 disables · blank = 25.")}</div>
      </div></div>` : null}
  <//>`;
}

// Mint ONE peer per chosen target (own keypair + PSK each), assigned to userId. Builds each
// config in-browser, stashes it in sessionConfigs (so the QR shows), and creates the peer via
// the Phase-2 endpoint. Returns { ok, made, fails:[...] }.
async function createPeersForTargets(userId, chosen, opts) {
  const dnsArr = (opts.dns || "").split(",").map(s => s.trim()).filter(Boolean);
  let made = 0; const fails = [];
  for (const t of chosen) {
    const m = Store.ifaceMeta(t.node, t.iface);
    if (!m) { fails.push(Store.nodeName(t.node) + "/" + t.iface + " (no interface meta)"); continue; }
    try {
      const keys = await genKeys();
      const psk = genPSK();
      const ipClean = String(t.ip).trim().split("/")[0];
      const conf = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: dnsArr, mtu: (opts.mtu || "").trim() || 1280,
        awg_params: m.awg_params, server_pubkey: m.public_key, psk, endpoint: m.endpoint,
        allowed: (opts.allowed || "").trim() || "0.0.0.0/0, ::/0", keepalive: (opts.keepalive || "").trim() });
      const body = { user_id: userId, pubkey: keys.pub, psk, targets: [{ node: t.node, iface: t.iface, ip: ipClean, type: (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg" }] };
      if (Store.storeConfigs) body.configs = { [tkey(t.node, t.iface)]: conf };
      const r = await api.peerCreate(body);
      if (!r.ok) { fails.push(Store.nodeName(t.node) + "/" + t.iface + ": " + (r.error || r.code || "failed")); continue; }
      Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, { [tkey(t.node, t.iface)]: conf });
      if (r.data && r.data.id) Store.recentlyCreated[r.data.id] = Date.now();
      made++;
    } catch (e) { fails.push(Store.nodeName(t.node) + "/" + t.iface + ": " + (e.message || e)); }
  }
  return { ok: made > 0 || chosen.length === 0, made, fails };
}

// Shared client-config field state (DNS / MTU / keepalive / AllowedIPs) for the peer sheets.
function useConfigFields() {
  const [dns, setDns] = useState(""); const [mtu, setMtu] = useState("1280");
  const [keepalive, setKeepalive] = useState("25"); const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const dnsTouched = useRef(false); const mtuTouched = useRef(false);
  const setters = { dns: setDns, mtu: setMtu, keepalive: setKeepalive, allowed: setAllowed };
  return { dns, mtu, keepalive, allowed, dnsTouched, mtuTouched, setDns, setMtu, set: (k, v) => setters[k](v),
           opts: () => ({ dns, mtu, keepalive, allowed }) };
}

// New peer (mint a fresh keypair) deployed to one OR MORE (node,iface) targets as ONE
// credential (redundancy / failover). For per-interface devices, use a user's "Add peers".
function openCreatePeer(prefill) { openModal(html`<${CreatePeerSheet} prefill=${prefill || {}}/>`); }
function CreatePeerSheet({ prefill }) {
  const [chosen, setChosen] = useState([]);
  const [title, setTitle] = useState("");
  const [psk, setPsk] = useState(genPSK());
  const cf = useConfigFields();
  const [userId, setUserId] = useState(prefill.user_id || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {   // default DNS + MTU from the first chosen interface until the operator edits them
    if (!chosen.length) return;
    const m = Store.ifaceMeta(chosen[0].node, chosen[0].iface); if (!m) return;
    if (!cf.dnsTouched.current) cf.setDns((m.dns || []).join(", "));
    if (!cf.mtuTouched.current && m.mtu) cf.setMtu(String(m.mtu));
  }, [chosen]);

  const pskBad = psk.trim() && !V.psk(psk);
  const validate = () => {
    if (!chosen.length) return "Pick at least one target.";
    const badIp = chosen.find(t => !V.ipv4(String(t.ip).trim()));
    if (badIp) return "Invalid address for " + Store.nodeName(badIp.node) + "/" + badIp.iface + ".";
    if (pskBad) return "Preshared key must be 44-char base64 (or blank to auto-generate).";
    const ce = configErrors(cf); const k = Object.keys(ce)[0];
    if (k) return ce[k];
    return null;
  };

  const create = async () => {
    const err = validate(); if (err) return setMsg({ k: "err", t: err });
    setBusy(true); setMsg({ k: "work", t: "generating key…" });
    try {
      const keys = await genKeys();
      const pskV = psk.trim() || genPSK();
      const dnsArr = cf.dns.split(",").map(s => s.trim()).filter(Boolean);
      const tgts = [], configs = {};
      for (const t of chosen) {
        const m = Store.ifaceMeta(t.node, t.iface); if (!m) continue;
        const ipClean = String(t.ip).trim().split("/")[0];
        tgts.push({ node: t.node, iface: t.iface, ip: ipClean, type: (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg" });
        configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: dnsArr, mtu: cf.mtu.trim() || 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk: pskV, endpoint: m.endpoint, allowed: cf.allowed.trim() || "0.0.0.0/0, ::/0", keepalive: cf.keepalive.trim() });
      }
      setMsg({ k: "work", t: "creating on " + tgts.length + " target" + (tgts.length > 1 ? "s" : "") + "…" });
      const body = { user_id: userId || null, title: title.trim(), pubkey: keys.pub, psk: pskV, targets: tgts };
      if (Store.storeConfigs) body.configs = configs;
      const r = await api.peerCreate(body);
      if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: "Failed: " + (r.error || r.code || "unknown") }); }
      Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, configs);
      Store.recentlyCreated[r.data.id] = Date.now();
      closeModal(); await Store.poll();
      go(userId ? "#/user/" + encodeURIComponent(userId) : "#/peer/" + encodeURIComponent(r.data.id));
    } catch (e) { setBusy(false); setMsg({ k: "err", t: "Error: " + e.message }); }
  };

  return html`<${Sheet} title="New peer"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${create}>Create peer</button></>`}>
    <div class="field"><label>User</label>
      <${UserPicker} value=${userId} allowUnassigned=${true} onChange=${setUserId}/></div>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional, to tell devices apart</span></label>
      <input value=${title} onInput=${e => setTitle(e.target.value)} maxlength="64" placeholder="iPhone, Router, Laptop…"/></div>
    <div class="field"><label>Targets <span class="faint" style="text-transform:none;letter-spacing:0">— one, or several for redundancy (same key)</span></label>
      <${TargetPicker} prefill=${prefill} onChange=${setChosen}/></div>
    <div class="field"><label>Preshared key</label><div class="inline"><input class=${pskBad ? "bad" : ""} value=${psk} onInput=${e => setPsk(e.target.value)}/><button class="btn btn-ghost" title="Regenerate" onClick=${() => { setPsk(genPSK()); toast("New preshared key.", "info", 1500); }}>↻</button></div>${pskBad ? html`<div class="hint err">Must be 44-char base64, or blank to auto-generate.</div>` : null}</div>
    <${AdvancedFields} st=${cf}/>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// Copy peer interface→interface (same key + PSK, new target). Needs the client's
// private key (session config, or stored) to build the new client config / QR.
// `back` = where Cancel / Deploy / Esc returns to (e.g. reopen the peer view); default just closes.
function openAddTarget(peer, back) { openModal(html`<${AddTargetSheet} peer=${peer} back=${back || closeModal}/>`); }
function AddTargetSheet({ peer, back }) {
  back = back || closeModal;
  const [iface, setIface] = useState(""); const [node, setNode] = useState("");
  const [ip, setIp] = useState(""); const [ipHint, setIpHint] = useState("");
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  // source config (holds the client's private key) to rebuild the copy's QR: session first, then
  // the panel's stored copy when store_configs is on — so copy works across sessions, not just the
  // one the peer was created in. Any target's config carries the same key.
  const [srcConf, setSrcConf] = useState(() => anySessionConf(peer.pubkey));
  const [confLoaded, setConfLoaded] = useState(() => !!anySessionConf(peer.pubkey) || !Store.storeConfigs);
  useEffect(() => {
    if (srcConf || !Store.storeConfigs) { setConfLoaded(true); return; }
    let ok = true;
    (async () => {
      for (const t of peer.targets) { const c = await getConfig(peer.pubkey, t.node, t.iface); if (c) { if (ok) setSrcConf(c); break; } }
      if (ok) setConfLoaded(true);
    })();
    return () => { ok = false; };
  }, [peer.id]);

  const have = new Set(peer.targets.map(t => tkey(t.node, t.iface)));
  // server id -> the interfaces on it this peer isn't deployed to yet; servers with none drop out.
  const avail = useMemo(() => {
    const m = {};
    Object.keys(Store.describe).forEach(n => {
      const free = Object.keys(Store.describe[n] || {}).filter(i => !have.has(tkey(n, i)));
      if (free.length) m[n] = free;
    });
    return m;
  }, [Store.describe]);
  const availNodes = Object.keys(avail);
  const none = availNodes.length === 0;             // peer already lives on every interface, everywhere
  const ifaceOpts = node && avail[node] ? avail[node] : [];

  useEffect(() => {                                  // keep a valid server selected (server first)
    if (none) { if (node) setNode(""); return; }
    if (!avail[node]) setNode(availNodes[0]);
  }, [availNodes.join("|")]);
  useEffect(() => {                                  // keep a valid interface for the chosen server
    const opts = avail[node] || [];
    if (!opts.includes(iface)) setIface(opts[0] || "");
  }, [node, availNodes.join("|")]);
  useEffect(() => {                                  // then pick a free address for server+interface
    if (!node || !iface) { setIp(""); setIpHint(""); return; }
    setIp(""); setIpHint("finding a free address on " + Store.nodeName(node) + "…");
    api.nextIp([node], iface).then(r => { if (r.ok) { setIp(String(r.data.next_ip).split("/")[0]); setIpHint("Next free address."); } else { setIp(""); setIpHint(r.error || "couldn't pick an address"); } });
  }, [node, iface]);

  const ipBad = ip.trim() && !V.ipv4(ip.trim().split("/")[0]);
  const deploy = async () => {
    if (!node) return setMsg({ k: "err", t: "Pick a server." });
    if (!ip.trim()) return setMsg({ k: "err", t: "No address available." });
    if (!V.ipv4(ip.trim().split("/")[0])) return setMsg({ k: "err", t: "Address must be a valid IPv4." });
    setBusy(true); setMsg({ k: "work", t: "deploying to " + Store.nodeName(node) + "…" });
    const info = Store.ifaceMeta(node, iface);
    const ipClean = ip.trim().split("/")[0];
    let conf = null;
    if (srcConf) { const s = parseFullConf(srcConf); conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); }
    const body = { peer_id: peer.id, target: { node, iface, ip: ipClean, type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" } };
    if (Store.storeConfigs && conf) body.config = conf;
    const r = await api.peerAddTarget(body);
    if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: "Failed: " + (r.error || r.code || "") }); }
    if (conf) (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(node, iface)] = conf;
    toast("Copied to " + Store.nodeName(node) + "/" + iface + ".", "ok"); back(); await Store.poll();
  };

  return html`<${Sheet} title=${"Copy peer to another interface"} onClose=${back}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${back}>Cancel</button><button class="btn btn-primary" disabled=${busy || none || !confLoaded} onClick=${deploy}>Deploy</button></>`}>
    ${none ? html`<div class="notice"><${Ic} i="info"/><span>This peer already exists on all the available interfaces across the servers.</span></div>`
      : html`<${Fragment}>
        ${!confLoaded ? html`<div class="loading"><span class="spin"></span>loading config…</div>`
          : !srcConf ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Store.storeConfigs
              ? "This peer was created before configs were stored, so its private key is gone here — the copy is added with the same key + PSK, but a fresh QR / config can't be generated. Re-issue (rotate keys) to get a downloadable config."
              : "store_configs is off, so the client's private key isn't kept — a fresh QR can't be shown unless you copy right after creating. The target is still added with the same key + PSK."}</span></div>` : null}
        <div class="field"><label>Server</label>
          <select class="selwrap" value=${node} onChange=${e => setNode(e.target.value)}>
            ${availNodes.map(n => html`<option value=${n}>${Store.nodeName(n)}</option>`)}
          </select></div>
        <div class="field"><label>Interface</label>
          <select class="selwrap" value=${iface} onChange=${e => setIface(e.target.value)}>
            ${ifaceOpts.map(i => html`<option value=${i}>${i}</option>`)}
          </select></div>
        <div class="field"><label>Address</label><input class=${ipBad ? "bad" : ""} value=${ip} onInput=${e => setIp(e.target.value)}/><div class=${"hint" + (ipBad ? " err" : "")}>${ipBad ? "Must be a valid IPv4 address." : ipHint}</div></div>
        ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
      </>`}
  <//>`;
}

// Edit a peer's client-config settings (DNS / MTU / keepalive / AllowedIPs) and re-issue
// the config for every target. The private key only lives in the existing config, so this
// rebuilds from it — available right after creation, or whenever store_configs is on.
// (Address / interface / server are deployment moves — use copy + remove for those.)
// Read-only peer view: all the peer's info + actions (edit / unassign|delete / close).
function openPeerView(pid, node, iface) { openModal(html`<${PeerViewSheet} pid=${pid} node=${node} iface=${iface}/>`); }
function PeerViewSheet({ pid, node, iface }) {
  useStore();
  const p = Store.peer(pid);
  if (!p) return html`<${Sheet} title="Peer" foot=${html`<button class="btn btn-ghost" onClick=${closeModal}>Close</button>`}><div class="empty"><b>Peer not found</b>It may have been removed.</div><//>`;
  const u = p.user_id ? Store.user(p.user_id) : null;
  return html`<${Sheet} title=${p.title || (u ? u.name : "Unassigned peer")}
    foot=${html`<${Fragment}>
      <button class="btn btn-ghost" onClick=${closeModal}>Close</button><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => openAddTarget(p, () => openPeerView(p.id, node, iface))}><${Ic} i="copy"/> Copy to interface</button>
      <button class="btn btn-ghost" onClick=${() => openEditPeer(p, node && iface ? { node, iface } : null, () => openPeerView(p.id, node, iface))}><${Ic} i="pencil"/> Edit</button>
      ${p.unassigned ? html`<button class="btn btn-danger" onClick=${() => confirmDeletePeer(p, () => openPeerView(p.id, node, iface))}>Delete</button>`
        : html`<button class="btn btn-danger" onClick=${() => confirmUnassign(p, () => openPeerView(p.id, node, iface))}>Unassign</button>`}<//>`}>
    <div class="pv-head">
      <div class="pv-id"><div class="pv-sub">${u ? html`<a class="pv-user" href=${"#/user/" + encodeURIComponent(u.id)}>${u.name}</a>`
          : html`<${UserCombo} onPick=${uid => assignPeer(p, uid)} placeholder="Assign to a user…"/>`}</div></div>
      <${Badge} s=${p.unassigned ? "unassigned" : p.status}/></div>
    <dl class="dl" style="margin:14px 0">
      <dt>Public key</dt><dd>${p.pubkey.slice(0, 22)}… <button class="copybtn" onClick=${() => copy(p.pubkey, "Public key copied")}><${Ic} i="copy"/></button></dd>
    </dl>
    <div class="lbl" style="margin:4px 2px">Deployments · ${p.targets.length}</div>
    <div class="pv-deps">${p.targets.map(t => {
      const obs = t.observed;
      const proto = (t.type || "").toLowerCase();
      return html`<div class=${"pv-dep" + (node === t.node && iface === t.iface ? " hl" : "")} key=${tkey(t.node, t.iface)}>
        <div class="pv-dep-top"><${Badge} s=${t.status}/>
          <span class="tags">
            <${Tag} kind=${proto === "awg" ? "awg" : "wg"} label=${proto === "awg" ? "awg" : "wg"} muted=${!t.online}/>
            ${/* TURN tag hidden until we can detect a peer is *actively* connected via turn-proxy (nodes-interface work) */ null}
          </span></div>
        <div class="pv-dep-grid">
          <span><span class="k">Server</span> ${Store.nodeName(t.node)}</span>
          <span><span class="k">Interface</span> ${t.iface}</span>
          <span><span class="k">Address</span> <span class="addr">${t.ip || "—"}</span></span>
          <span><span class="k">Rate</span> ${rateCell(obs ? obs.rx_speed : 0, obs ? obs.tx_speed : 0)}</span>
          <span><span class="k">Total</span> <span class="addr">↓ ${fmtBytes(obs ? obs.rx_bytes : 0)} ↑ ${fmtBytes(obs ? obs.tx_bytes : 0)}</span></span>
          <span><span class="k">Last</span> ${seen(obs ? obs.handshake_age : null)}</span>
        </div></div>`;
    })}</div>
  <//>`;
}

// Edit a peer: title (peer-wide), the focused target's address, and the client-config settings
// (DNS/MTU/keepalive/AllowedIPs, applied to every target with a known config). Also offers copy
// → another interface and key rotation (keeps the PSK). `focus` = the {node,iface} to edit IP for.
// `done` = where Cancel / Save returns to (reopen the peer view when edit came from it, else close).
function openEditPeer(peer, focus, done) { openModal(html`<${EditPeerSheet} peer=${peer} focus=${focus} done=${done || closeModal}/>`); }
function EditPeerSheet({ peer, focus, done }) {
  done = done || closeModal;
  const ft = focus ? peer.targets.find(t => t.node === focus.node && t.iface === focus.iface) : null;
  const [title, setTitle] = useState(peer.title || "");
  const [ip, setIp] = useState(ft ? (ft.ip || "").split("/")[0] : "");
  const [loaded, setLoaded] = useState(false);
  const [confs, setConfs] = useState({});            // "node|iface" -> conf text (those we can rebuild)
  const [dns, setDns] = useState(""); const [mtu, setMtu] = useState("1280");
  const [keepalive, setKeepalive] = useState("25"); const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const [userId, setUserId] = useState(peer.user_id || "");   // staged owner (applied on Save for an unassigned peer)
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);

  useEffect(() => {
    let ok = true;
    (async () => {
      const found = {};
      for (const t of peer.targets) { const c = await getConfig(peer.pubkey, t.node, t.iface); if (c) found[tkey(t.node, t.iface)] = c; }
      if (!ok) return;
      setConfs(found); setLoaded(true);
      const first = found[tkey(focus && focus.node, focus && focus.iface)] || Object.values(found)[0];
      if (first) { const s = parseFullConf(first); setDns((s.dns || []).join(", ")); setMtu(String(s.mtu)); setKeepalive(String(s.keepalive)); setAllowed(s.allowed); }
    })();
    return () => { ok = false; };
  }, [peer.id]);

  const editable = Object.keys(confs).length;
  const ipChanged = ft && ip.trim() && ip.trim() !== (ft.ip || "").split("/")[0];
  const ipBad = ft && ip.trim() && !V.ipv4(ip.trim().split("/")[0]);
  const errs = editable ? configErrors({ dns, mtu, keepalive, allowed }) : {};
  const save = async () => {
    if (ipBad) return setMsg({ k: "err", t: "Address must be a valid IPv4." });
    const ek = Object.keys(errs)[0]; if (ek) return setMsg({ k: "err", t: errs[ek] });
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    const dnsArr = dns.split(",").map(s => s.trim()).filter(Boolean);
    const newIP = ip.trim().split("/")[0];
    let fails = 0;
    try {
      if (title.trim() !== (peer.title || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, title: title.trim() }); if (!r.ok) fails++;
      }
      // staged assignment of a previously-unassigned peer — keep the key, just set the owner
      if (peer.unassigned && userId && userId !== (peer.user_id || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, user_id: userId }); if (!r.ok) fails++;
      }
      // rebuild + persist each target's config (focus target gets the new address)
      for (const t of peer.targets) {
        const k = tkey(t.node, t.iface); const cur = confs[k];
        const isFocus = ft && t.node === ft.node && t.iface === ft.iface;
        if (!cur) {                                  // no config to rebuild — IP can still move
          if (isFocus && ipChanged) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
          continue;
        }
        const s = parseFullConf(cur);
        const addr = (isFocus && ipChanged ? newIP : (s.address || "").split("/")[0]) + "/32";
        const conf = buildConf({ privkey: s.privkey, address: addr, dns: editable ? dnsArr : s.dns, mtu: (mtu.trim() || 1280), awg_params: s.awg_params, server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: (allowed.trim() || "0.0.0.0/0, ::/0"), keepalive: keepalive.trim() });
        (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[k] = conf;
        if (isFocus && ipChanged) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP, config: conf }); if (!r.ok) fails++; }
        else if (Store.storeConfigs) { const r = await api.peerSaveConfig({ pubkey: peer.pubkey, node: t.node, iface: t.iface, config: conf }); if (!r.ok) fails++; }
      }
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: String(e.message || e) }); }
    setBusy(false); Store.configEpoch++;
    // an already-assigned peer changing owner is destructive (keys rotate) — confirm it now, on
    // Save (so cancelling keeps the previous owner). Title/config above are already persisted.
    const oldUid = peer.user_id || "", newUid = userId || "";
    if (oldUid && newUid !== oldUid) {
      await Store.poll();
      const fresh = (Store.recon.peers.find(x => x.id === peer.id)) || peer;
      const back = () => openEditPeer(fresh, focus, done);
      return newUid ? confirmReassign(fresh, newUid, back) : confirmUnassign(fresh, back);
    }
    toast(fails ? "Saved (some changes couldn't be persisted)." : "Peer updated.", fails ? "info" : "ok");
    done(); await Store.poll();
  };

  const rotate = () => {
    if (peer.unassigned) return toast("Assign the peer to a user first.", "err");
    openConfirm({ title: "Rotate keys", confirmLabel: "Rotate keys", warn: true, back: done,
      body: "A new keypair is generated (the PSK is kept). The current config stops working — you'll need to send the user the fresh QR / config to re-import.",
      onConfirm: () => rotatePeerKeys(peer) });
  };

  return html`<${Sheet} title=${"Edit peer"} onClose=${done}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${done}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>Save</button></>`}>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input autofocus value=${title} maxlength="64" onInput=${e => setTitle(e.target.value)} placeholder="e.g. iPhone, Work laptop"/></div>
    <div class="field"><label>User</label>
      <${UserPicker} value=${userId} allowUnassigned=${!peer.unassigned} onChange=${setUserId}/>
      <div class=${"hint"}>${
        peer.unassigned ? "Pick a user to assign this peer to — the existing key and config are kept, applied when you Save."
        : (userId || "") === (peer.user_id || "") ? "Reassigning rotates the keys; you'll confirm on Save and the new user needs a fresh config."
        : !userId ? "On Save you'll confirm unassigning — access is revoked and the keys rotate."
        : "On Save you'll confirm reassigning — the current user loses access for good and the new user needs a fresh config."
      }</div></div>
    ${ft ? html`<div class="field"><label>Address on ${Store.nodeName(ft.node)} · ${ft.iface}</label><input class=${ipBad ? "bad" : ""} value=${ip} onInput=${e => setIp(e.target.value)}/><div class=${"hint" + (ipBad ? " err" : "")}>${ipBad ? "Must be a valid IPv4 address." : "Changing this moves the peer's address on this interface."}</div></div>` : null}
    ${!loaded ? html`<div class="loading"><span class="spin"></span>loading config…</div>`
      : !editable ? html`<div class="notice warn"><${Ic} i="warn"/><span>The client's private key isn't available, so DNS / MTU / routing can't be rebuilt${Store.storeConfigs ? "" : " (enable store_configs, or edit right after creating)"}. Title and address can still change.</span></div>`
      : html`<${Fragment}>
        <div class="hint" style="margin:4px 0 6px">DNS / MTU / routing apply to all ${Object.keys(confs).length} target(s) with a known config.</div>
        <div class="field"><label>Client allowed IPs (routing)</label><input class=${errs.allowed ? "bad" : ""} value=${allowed} onInput=${e => setAllowed(e.target.value)}/><div class=${"hint" + (errs.allowed ? " err" : "")}>${errs.allowed || "Full tunnel by default. Narrow for split tunnel."}</div></div>
        <div class="field"><label>DNS</label><input class=${errs.dns ? "bad" : ""} value=${dns} onInput=${e => setDns(e.target.value)} placeholder="e.g. 1.1.1.1, 1.0.0.1"/><div class=${"hint" + (errs.dns ? " err" : "")}>${errs.dns || "Comma-separated IPs. Blank = no DNS line."}</div></div>
        <div class="row2">
          <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class=${"hint" + (errs.mtu ? " err" : "")}>${errs.mtu || "Blank = 1280."}</div></div>
          <div class="field"><label>Persistent keepalive (s)</label><input class=${errs.keepalive ? "bad" : ""} value=${keepalive} onInput=${e => setKeepalive(e.target.value)} placeholder="25"/><div class=${"hint" + (errs.keepalive ? " err" : "")}>${errs.keepalive || "0 disables · blank = 25."}</div></div>
        </div>
      <//>`}
    <div class="editrow">
      <button class="btn btn-ghost" onClick=${() => openAddTarget(peer, done)}><${Ic} i="copy"/> Copy to interface</button>
      <button class="btn btn-ghost" onClick=${rotate}><${Ic} i="key"/> Rotate keys</button>
    </div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── node sheets ──
function SwatchPicker({ value, onChange }) {
  return html`<div class="swrow">
    ${SWATCHES.map(c => html`<button type="button" class=${"swopt " + (c.toLowerCase() === (value || "").toLowerCase() ? "sel" : "")} style=${{ background: c }} title=${c} onClick=${() => onChange(c)}></button>`)}
    <label class="swopt custom" title="Custom colour — full palette">
      <input type="color" value=${value} onInput=${e => onChange(e.target.value)}/>
    </label>
  </div>`;
}
function openNodeCreate() { openModal(html`<${NodeCreateSheet}/>`); }
function NodeCreateSheet() {
  const [name, setName] = useState(""); const [color, setColor] = useState(SWATCHES[0]); const [msg, setMsg] = useState(null);
  const nameBad = name.trim() && !V.nodeName(name);
  const create = async () => {
    if (!name.trim()) return setMsg({ k: "err", t: "Give the node a name." });
    if (!V.nodeName(name)) return setMsg({ k: "err", t: "Name: 1–40 chars, letters/digits/-/_ only." });
    setMsg({ k: "work", t: "creating…" });
    const r = await api.nodeCreate({ name: name.trim(), endpoint_host: "", color });
    if (!r.ok) return setMsg({ k: "err", t: r.error || "couldn't create node" });
    await Store.poll(); openModal(html`<${NodeTokenSheet} name=${r.data.name} token=${r.data.token} isNew=${true}/>`);
  };
  return html`<${Sheet} title="Add node"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${create}>Create node</button></>`}>
    <div class="field"><label>Name</label><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} placeholder="msk-edge1" autocomplete="off"/><div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : "A label for this node — you can rename it anytime."}</div></div>
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
      <div class="hint">Pick one. Both fetch the installer and prompt for the node's endpoint.</div></div>
  <//>`;
}
function openNodeEdit(node) { openModal(html`<${NodeEditSheet} node=${node}/>`); }
function NodeEditSheet({ node }) {
  const [name, setName] = useState(node.name || ""); const [color, setColor] = useState(node.color || SWATCHES[0]); const [msg, setMsg] = useState(null);
  const nameBad = name.trim() && !V.nodeName(name);
  const save = async () => {
    if (!name.trim() || !V.nodeName(name)) return setMsg({ k: "err", t: "Name: 1–40 chars, letters/digits/-/_ only." });
    closeModal();   // optimistic: card reflects the rename immediately (name is just a label — no refs to migrate)
    mutate({
      key: "node:" + node.id,
      patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) { n.name = name.trim(); n.color = color; } },
      call: () => api.nodeUpdate({ id: node.id, name: name.trim(), color }),
    });
  };
  return html`<${Sheet} title=${"Edit " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${save}>Save</button></>`}>
    <div class="field"><label>Name</label><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} autocomplete="off"/><div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : "A label for this node — rename anytime, nothing else changes."}</div></div>
    <div class="field"><label>Colour</label><${SwatchPicker} value=${color} onChange=${setColor}/></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
function openNodeRotate(node) { openModal(html`<${NodeRotateSheet} node=${node}/>`); }
function NodeRotateSheet({ node }) {
  const go2 = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(r.error || "rotate failed", "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false}/>`); };
  return html`<${Sheet} title=${"Rotate token · " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${go2}>Rotate</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>The current token stops working immediately. Re-enroll the node with the new token or it will go offline.</span></div>
  <//>`;
}
function openNodeRemove(node) { openModal(html`<${NodeRemoveSheet} node=${node}/>`); }
function NodeRemoveSheet({ node }) {
  const [flagged, setFlagged] = useState(!!node.removing);
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === node.id));
  const onlyHere = here.filter(p => new Set(p.targets.map(t => t.node)).size === 1).length;
  const note = here.length ? `${here.length} peer${here.length > 1 ? "s" : ""} reference it${onlyHere ? `; ${onlyHere} live only here and will be dropped` : ""}.` : "No peers reference it.";
  const uninstall = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s uninstall`;
  const flag = () => { setFlagged(true); mutate({
    key: "node:" + node.id,
    patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) n.removing = true; },
    call: () => api.nodeFlagRemove({ id: node.id }),
  }); };
  const force = () => { openConfirm({ title: "Force remove · " + node.name, confirmLabel: "Force remove", danger: true, back: () => openNodeRemove(node),
    body: "This cuts the node off immediately without waiting for it to confirm. Peers that live only here are dropped. Use this only when the server is unreachable.",
    onConfirm: () => mutate({
      key: "node:" + node.id,
      patch: s => {                                  // optimistic: drop the node + purge its targets (mirrors the cascade)
        s.nodes = s.nodes.filter(x => x.id !== node.id);
        for (const id of Object.keys(s.roster.peers)) {
          const p = s.roster.peers[id]; p.targets = p.targets.filter(t => t.node !== node.id);
          if (!p.targets.length) delete s.roster.peers[id];
        }
      },
      call: () => api.nodeDelete({ id: node.id }),
    }) }); };
  return html`<${Sheet} title=${"Remove " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Close</button>
      ${flagged ? null : html`<button class="btn btn-primary" onClick=${flag}>Flag for removal</button>`}
      <button class="btn btn-danger" onClick=${force}>Force remove now</button></>`}>
    ${flagged
      ? html`<div class="notice"><${Ic} i="info"/><span><b>Flagged for removal.</b> Run the command below on the node — it'll sign off and disappear here automatically. If you've lost access to the server, use <b>Force remove now</b> to cut it off.</span></div>`
      : html`<div class="notice"><${Ic} i="info"/><span>Clean removal: flag the node, then run the uninstall command on the server. The node keeps serving its ${here.length} peer${here.length === 1 ? "" : "s"} until it confirms, then drops itself from the panel. ${note}</span></div>`}
    <div class="field" style="margin-top:14px"><label>Run on the node to uninstall + sign off</label>
      <div class="cmdrow"><div class="tokenbox">${uninstall}</div><button class="copyaction" onClick=${() => copy(uninstall, "Copied")}><${Ic} i="copy"/> Copy</button></div>
      <div class="hint">Removes swg-noded / swg-agent and tells the panel it's gone. Force remove is for when the server is unreachable.</div></div>
  <//>`;
}

// ═════════════════════════ ROUTER + APP ═════════════════════════
const ROUTES = [
  { re: /^\/$/, fn: Overview, tab: "overview" },
  { re: /^\/connections$/, fn: ConnectionsScreen, tab: "connections" },
  { re: /^\/node\/([^/]+)\/([^/]+)$/, fn: IfaceDetail, tab: "nodes", keys: ["node", "iface"] },
  { re: /^\/node\/(.+)$/, fn: NodeDetail, tab: "nodes", keys: ["node"] },
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
    // Esc/Enter inside dialogs are owned by <Sheet> (with its dirty-guard); nothing global here.
    return () => window.removeEventListener("hashchange", onHash);
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
    const acct = $("#acct-btn"); if (acct) acct.onclick = openAccount;
    const out = $("#logout-btn"); if (out) out.onclick = doLogout;
  });

  return html`<${Fragment}>
    ${h(route.fn, params)}
    ${modal}
  <//>`;
}

// ───────────────────────── auth: login page + logout ─────────────────────────
let _loginShown = false;
function require401() { showLogin(); throw new Error("unauthorized"); }
function showLogin() { if (_loginShown) return; _loginShown = true; document.body.classList.add("loggedout"); try { render(h(LoginScreen), viewEl); } catch (_) {} }
function LoginScreen() {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async e => {
    if (e) e.preventDefault();
    if (busy) return;
    setBusy(true); setErr("");
    try {
      const r = await api.login({ username: u, password: p });
      if (r && r.ok) { location.reload(); return; }
      setErr((r && r.error) || "Login failed."); setBusy(false);
    } catch (_) { setErr("Couldn't reach the panel."); setBusy(false); }
  };
  return html`<div class="login-wrap"><form class="login-card" onSubmit=${submit}>
    <div class="login-brand"><span class="brand-mark"></span><span class="brand-name">swg<span>Panel</span></span></div>
    <h2>Sign in</h2>
    <div class="field"><label>Username</label><input autofocus value=${u} onInput=${e => setU(e.target.value)} autocomplete="username"/></div>
    <div class="field"><label>Password</label><input type="password" value=${p} onInput=${e => setP(e.target.value)} autocomplete="current-password"/></div>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    <button class="btn btn-primary" type="submit" disabled=${busy} style="width:100%;justify-content:center;margin-top:4px">${busy ? "Signing in…" : "Sign in"}</button>
  </form></div>`;
}
function doLogout() {
  openConfirm({ title: "Log out", confirmLabel: "Log out",
    body: "You'll need to sign in again to manage the fleet.",
    onConfirm: async () => { try { await api.logout(); } catch (_) {} location.reload(); } });
}
// Account form as a modal (same chrome as the node sheets).
function openAccount() { openModal(html`<${AccountSheet}/>`); }

// ───────────────────────── boot ─────────────────────────
const viewEl = $("#view");
viewEl.innerHTML = `<div class="loading"><span class="spin"></span>connecting…</div>`;
(async () => {
  try { await Store.init(); }
  catch (e) { if (!_loginShown) viewEl.innerHTML = `<div class="empty"><b>Can't reach the panel</b>${esc(e.message)}</div>`; return; }
  if (!location.hash) location.hash = "#/";
  render(h(App), viewEl);
})();
