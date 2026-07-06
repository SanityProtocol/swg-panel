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
function turnLabel(service, port) {   // just the fork name — the port shows in the Listen row
  let s = (service || "turn-proxy").replace(/^vk-turn-proxy-?/, "") || "turn";
  s = s.replace(/-\d+$/, "") || "turn";
  return s === "main" ? "cacggghp" : s;   // legacy "main" services (pre-rename) still display as cacggghp
}
// the fork id baked into a service name (vk-turn-proxy-<fork>-<port>) → its owner repo (for version/update checks)
function turnFork(svc) { return turnLabel(svc, ""); }
function turnOwner(svc) {
  const f = turnFork(svc); const fk = (typeof TURN_FORKS !== "undefined") ? TURN_FORKS.find(x => x.id === f) : null;
  return fk ? fk.owner : (f && f !== "turn" ? f + "/vk-turn-proxy" : "");
}
// turn create/edit sheet heading: "Turn-proxy · <title> · <fork>" (title omitted when blank)
function turnSheetTitle(fork, title) { return "Turn-proxy · " + ((title || "").trim() ? (title.trim() + " · ") : "") + fork; }
// a fresh 64-hex wrap key (browser crypto) — used to pre-fill the create form's params for obfuscation forks
function randWrapKey() { const a = new Uint8Array(32); crypto.getRandomValues(a); return Array.from(a, b => b.toString(16).padStart(2, "0")).join(""); }
// dropdown of a node's known IPs + a trailing free-text "Custom IP / Host…". Shared by the interface
// endpoint field and the turn-proxy listen-IP field so they look/behave identically. Parent owns the
// sel/custom state; resolve the chosen value with ipPickerVal(sel, custom).
function IpPicker({ ips, sel, setSel, custom, setCustom, placeholder }) {
  return html`<${Fragment}>
    <select class="selwrap" value=${sel} onChange=${e => setSel(e.target.value)}>
      ${(ips || []).filter(ip => !isPrivIp(ip)).map(ip => html`<option value=${ip}>${ip}</option>`)}
      <option value="__custom__">Custom IP / Host…</option>
    </select>
    ${sel === "__custom__" ? html`<input style="margin-top:6px" value=${custom} onInput=${e => setCustom(e.target.value)} placeholder=${placeholder || "203.0.113.7"} autocomplete="off"/>` : null}
  <//>`;
}
const ipPickerVal = (sel, custom) => sel === "__custom__" ? (custom || "").trim() : sel;

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
  dots: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2.1"/><circle cx="12" cy="12" r="2.1"/><circle cx="19" cy="12" r="2.1"/></svg>',
  waves: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 8q3.5-4 7 0t7 0"/><path d="M3 13q3.5-4 7 0t7 0"/><path d="M3 18q3.5-4 7 0t7 0"/></svg>',
  off: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg>',
  back: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>',
  search: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  pencil: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6 9 17l-5-5"/></svg>',
  warn: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  info: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  x: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>',
  err: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
  play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M7 4l13 8-13 8z"/></svg>',
  stop: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>',
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
  cascade: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4v4h5v4h5v4h6"/></svg>',
  smart: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M18.5 14l.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8z"/></svg>',
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
function Panel({ icon, title, count, actions, tone, children, pad, lead }) {
  return html`<section class="panel">
    <div class="panel-head">
      ${icon ? html`<span class=${"panel-ic" + (tone ? " t-" + tone : "")}><${Ic} i=${icon}/></span>` : null}
      <h3>${title}</h3>${count != null ? html`<span class="panel-count">${count}</span>` : null}
      ${lead || null}<span class="grow"></span>${actions || null}
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
  // octet-stream (not text/plain) so the browser keeps the .conf name instead of appending .txt
  const blob = new Blob([text], { type: "application/octet-stream" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = base.replace(/[^\w.-]+/g, "_").replace(/\.(conf|txt)$/i, "") + ".conf"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function downloadNamed(text, filename) {   // download with an explicit filename+extension (turn artifacts: .conf or .txt)
  const blob = new Blob([text], { type: "application/octet-stream" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = filename.replace(/[^\w.-]+/g, "_"); a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ── wingsv:// link (WINGS V app) ── the payload is raw protobuf, NOT JSON:
// wingsv:// + base64url( 0x12 ‖ zlib( proto.Marshal(wingsv.Config) ) ). We hand-serialize the Config
// message (buildless — no protobuf lib) and use the browser's CompressionStream('deflate'), which emits
// the RFC1950 zlib stream Go's zlib.NewWriter produces. Schema: WINGS-N/wingsv-proto/wingsv.proto.
function _pbVarint(n) { const o = []; let v = Math.floor(n); while (v > 127) { o.push((v % 128) | 0x80); v = Math.floor(v / 128); } o.push(v & 0x7f); return o; }
function _pbKey(f, w) { return _pbVarint((f << 3) | w); }
function _pbLen(f, arr) { return [..._pbKey(f, 2), ..._pbVarint(arr.length), ...arr]; }          // length-delimited (string / bytes / message)
function _pbVar(f, n) { return [..._pbKey(f, 0), ..._pbVarint(n)]; }                              // varint (uint / bool / enum)
function _pbStr(f, s) { return _pbLen(f, [...new TextEncoder().encode(String(s))]); }
function _pbBin(f, u8) { return _pbLen(f, [...u8]); }
function _b64ToBytes(b64) { try { const s = atob(String(b64 || "").trim()); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; } catch (_) { return new Uint8Array(0); } }
function _hexToBytes(h) { h = String(h || "").replace(/[^0-9a-fA-F]/g, ""); const a = new Uint8Array(h.length >> 1); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }
function _ipToBytes(addr) {
  addr = String(addr || "").trim();
  if (addr.includes(":")) {                                        // IPv6 (handles :: expansion)
    const [head, tail] = addr.split("::");
    const h = head ? head.split(":").filter(Boolean) : [], t = tail ? tail.split(":").filter(Boolean) : [];
    const groups = addr.includes("::") ? [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill("0"), ...t] : addr.split(":");
    const b = new Uint8Array(16); groups.slice(0, 8).forEach((g, i) => { const v = parseInt(g || "0", 16) || 0; b[i * 2] = v >> 8; b[i * 2 + 1] = v & 0xff; }); return b;
  }
  const p = addr.split("."); const b = new Uint8Array(4); for (let i = 0; i < 4; i++) b[i] = (+p[i]) || 0; return b;
}
function _epBytes(hostport) { const s = String(hostport || ""); const i = s.lastIndexOf(":"); if (i < 0) return null; return [..._pbStr(1, s.slice(0, i)), ..._pbVar(2, +s.slice(i + 1) || 0)]; }
function _wingsvConfigBytes(cf, tp, vk, rawConf) {
  // Sidecar model like the other configs: the transport dials the LOCAL turn client on 127.0.0.1:9000; the
  // turn engine reaches the PUBLIC proxy (Turn.endpoint = the proxy's internet ip:listen). Do NOT put the
  // public addr in local_endpoint, and don't dial the real server directly.
  const LOCAL = "127.0.0.1:9000";
  const isAwg = !!(cf.awg_params && Object.keys(cf.awg_params).length);   // AmneziaWG interface → ship an awg transport, not wg
  const pep = _epBytes(tp.listen);
  const turn = [];
  if (pep) turn.push(..._pbLen(1, pep));                           // endpoint = public proxy (internet ip:listen)
  turn.push(..._pbStr(2, vk));                                     // link
  turn.push(..._pbLen(6, _epBytes(LOCAL)));                        // local_endpoint = local turn listen (127.0.0.1:9000)
  turn.push(..._pbVar(4, 1));                                      // use_udp = true
  turn.push(..._pbVar(18, isAwg ? 2 : 1));                         // tunnel_mode = AMNEZIAWG : WIREGUARD (transport discriminator)
  if (tp.wrap_key) { turn.push(..._pbVar(19, 2), ..._pbBin(20, _hexToBytes(tp.wrap_key))); }   // wrap_mode = PREFERRED + key
  // transport sub-message. AWG interfaces carry the full awg-quick config as a STRING in Config.awg (field 7);
  // the WINGS V app parses it and overrides its Endpoint to the local turn client (AmneziaConfigFactory), so we
  // still point it at LOCAL for self-consistency. WG interfaces use the binary WireGuard message (field 4).
  let transport;
  if (isAwg) {
    const quick = String(rawConf || "").replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 " + LOCAL);
    transport = _pbLen(7, _pbStr(1, quick));                       // Config.awg = AmneziaWG{ awg_quick_config }
  } else {
    const iface = [..._pbBin(1, _b64ToBytes(cf.privkey))];
    (cf.address || "").split(",").map(s => s.trim()).filter(Boolean).forEach(a => iface.push(..._pbStr(2, a)));
    (cf.dns || []).forEach(d => iface.push(..._pbStr(3, d)));
    if (cf.mtu) iface.push(..._pbVar(4, +cf.mtu || 1280));
    const peer = [..._pbBin(1, _b64ToBytes(cf.server_pubkey))];
    if (cf.psk) peer.push(..._pbBin(2, _b64ToBytes(cf.psk)));
    (cf.allowed || "").split(",").map(s => s.trim()).filter(Boolean).forEach(c => {
      const [a, pfx] = c.split("/");
      peer.push(..._pbLen(3, [..._pbBin(1, _ipToBytes(a)), ..._pbVar(2, pfx != null ? +pfx : (a.includes(":") ? 128 : 32))]));
    });
    transport = _pbLen(4, [..._pbLen(1, iface), ..._pbLen(2, peer), ..._pbLen(3, _epBytes(LOCAL))]);   // Config.wg (endpoint → local turn client)
  }
  // type: WG uses ALL (4) and works. AWG uses VK_TURN_PROFILE (10) — the type WINGS itself emits for a single
  // VK-TURN profile share link (buildTurnProfileLink), which embeds + links the awg transport to the active VK
  // TURN profile. ALL is a bulk-settings import and doesn't link the awg transport (the xray-userspace-WG engine
  // reads flat wg settings so WG survives it; the native AmneziaWG engine needs the linked profile).
  const type = isAwg ? 10 : 4;
  return new Uint8Array([..._pbVar(1, 1), ..._pbVar(2, type), ..._pbLen(3, turn), ...transport, ..._pbVar(5, 7)]);   // ver=1, type, turn, wg|awg, backend=VK_TURN
}
async function wingsvLink(baseConf, tp, vk) {
  if (typeof CompressionStream === "undefined") throw new Error("this browser can't build a wingsv:// link (no CompressionStream) — copy the fields into the WINGS V app manually");
  const proto = _wingsvConfigBytes(parseFullConf(baseConf), tp, (vk || "").trim() || "<PASTE VK CALL LINK>", baseConf);
  const cs = new CompressionStream("deflate"); const w = cs.writable.getWriter(); w.write(proto); w.close();
  const comp = new Uint8Array(await new Response(cs.readable).arrayBuffer());
  const payload = new Uint8Array(1 + comp.length); payload[0] = 0x12; payload.set(comp, 1);
  let s = ""; for (const b of payload) s += String.fromCharCode(b);
  return "wingsv://" + btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Build the client-import artifact for a peer deployed BEHIND a turn-proxy, matching the DEPLOYED fork.
// kiper292 → annotated WG .conf; anton48 → vkturnproxy:// link; every other (sidecar) fork → a WG .conf
// pointed at the local client on :9000 + the client command to run alongside.
//
// FORMAT SYNC (checked 2026-07: only anton48 ships an actual generator — quick_link.py, git-only, not a
// release asset — so reimplementing the documented, versioned formats here is equivalent and simpler.
// These are the schema versions we target; bump deliberately if a fork changes its format on a major
// release (the update flow only pulls a newer server binary, it can't change these):
//   • anton48   vkturnproxy:// JSON  "version": 1
//   • samosvalishe freeturn://  JSON "v": 1   (migrated to base64url(json) at v1.2.0; obf codecs evolve)
//   • kiper292  #@wgt: comments, PeerType is SERVER-COUPLED — proxy_v2 = kiper292 v2 server (what a
//     "kiper292" proxy IS), proxy_v1 = cacggghp server. We key off the deployed fork, so proxy_v2 is right.
//   • WINGS-N   wingsv:// = 0x12 ‖ zlib(protobuf Config); hand-encoded (see wingsvLink). Config.ver = 1.
// A descriptor may carry `text` (ready) OR `buildAsync` (a promise, e.g. wingsv:// needs zlib).
function turnArtifact(baseConf, tp, vkLink) {
  const fork = turnFork(tp.service);
  const listen = tp.listen || "";
  const vk = (vkLink || "").trim() || "<PASTE VK CALL LINK>";
  const cf = parseFullConf(baseConf);
  if (fork === "WINGS-N") {
    return { fork, label: "WINGS-N · WINGS V (wingsv:// link)", ext: "txt", uri: true,
      hint: "Import this wingsv:// link into the WINGS V app (paste it, or its Settings → import from link).",
      buildAsync: () => wingsvLink(baseConf, tp, vk) };
  }
  if (fork === "kiper292") {
    const block = ["", "#@wgt:EnableTURN = true", "#@wgt:UseUDP = false", "#@wgt:IPPort = " + listen,
      "#@wgt:VKLink = " + vk, "#@wgt:Mode = vk_link", "#@wgt:PeerType = proxy_v2",
      "#@wgt:StreamNum = 4", "#@wgt:LocalPort = 9000", "#@wgt:StreamsPerCred = 4"].join("\n");
    return { fork, label: "kiper292 · WireGuard-TURN (Android)", ext: "conf",
      hint: "Import this .conf into the kiper292 WireGuard-TURN app — the TURN settings ride along as #@wgt: comments (Endpoint stays the real server).",
      text: baseConf.replace(/\s*$/, "") + "\n" + block + "\n" };
  }
  if (fork === "anton48") {
    const s = { privateKey: cf.privkey, peerPublicKey: cf.server_pubkey, presharedKey: cf.psk,
      tunnelAddress: cf.address, dnsServers: cf.dns || [], peerAddress: listen, vkLink: vk,
      numConnections: 10, useUDP: true, useDTLS: false, useSrtp: !tp.wrap_key,
      useWrap: !!tp.wrap_key, useWrapA: false, wrapKeyHex: tp.wrap_key || "" };
    const uri = "vkturnproxy://import?data=" + btoa(JSON.stringify({ settings: s, type: "connection", version: 1 }));
    return { fork, label: "anton48 · VK TURN Proxy (iOS)", ext: "txt", uri: true,
      hint: "Open this link on the iPhone (or the app's Settings → Import from connection link) to import into the anton48 app.",
      text: uri };
  }
  // sidecar forks (WINGS-N / cacggghp / samosvalishe / Moroka8 / unknown): WG dials the local client on :9000
  let sidecar = baseConf.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, "$1 127.0.0.1:9000");
  sidecar = /^[ \t]*MTU[ \t]*=/m.test(sidecar) ? sidecar.replace(/^([ \t]*MTU[ \t]*=).*$/m, "$1 1280")
    : sidecar.replace(/^([ \t]*Address[ \t]*=.*)$/m, "$1\nMTU = 1280");
  const flags = tp.wrap_key ? (" -wrap-key " + tp.wrap_key) : "";
  return { fork, label: fork + " · sidecar client", ext: "conf",
    hint: "This fork runs a separate client binary. Import this .conf into WireGuard, then run the fork's client alongside it:",
    cmd: "./client -listen 127.0.0.1:9000 -peer " + listen + " -vk-link " + vk + flags,
    text: sidecar };
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
let qrZoomEl = null;   // the open QR enlargement, if any — Esc collapses it (instead of closing the modal)
function qrZoom(conf, label) {
  if (qrZoomEl) { try { qrZoomEl.remove(); } catch (_) {} qrZoomEl = null; }
  let img;
  try { img = `<img class="qrimg" alt="config QR" src="${qrDataURL(conf, 920)}">`; }
  catch (e) { img = '<div class="qr-fail">config too large to encode</div>'; }
  const ov = document.createElement("div");
  ov.className = "qr-overlay";
  ov.innerHTML = `<div class="qr-overlay-inner"><div class="qr-overlay-card">${img}</div>` +
    `<div class="qr-overlay-cap">${label || "Scan in WireGuard / AmneziaWG"}</div></div>`;
  const onKey = e => { if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(); } };
  function close() { try { ov.remove(); } catch (_) {} if (qrZoomEl === ov) qrZoomEl = null; document.removeEventListener("keydown", onKey, true); }
  ov.onclick = close;
  document.addEventListener("keydown", onKey, true);
  qrZoomEl = ov;
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
  meshHistory(range) { return this.get("/api/mesh-history?range=" + encodeURIComponent(range)); },
  categoryHistory(range) { return this.get("/api/category-history?range=" + encodeURIComponent(range)); },
  catalog(search, page) { return this.get("/api/catalog?search=" + encodeURIComponent(search || "") + "&page=" + (page || 0)); },
  catalogIndex() { return this.get("/api/catalog/index"); },
  catalogRefresh() { return this.post("/api/catalog/refresh", {}); },
  listInfo(cat) { return this.get("/api/list-info?cat=" + encodeURIComponent(cat)); },
  geoUpdate() { return this.post("/api/geo/update", {}); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  connectionUpdate(b) { return this.post("/api/connection/update", b); },
  panelSettings(b) { return this.post("/api/panel/settings", b); },
  refreshGeo() { return this.post("/api/panel/refresh-geo", {}); },
  nodeRotate(b) { return this.post("/api/nodes/rotate", b); },
  nodeFlagRemove(b) { return this.post("/api/nodes/flag-remove", b); },
  nodeUnflagRemove(b) { return this.post("/api/nodes/unflag-remove", b); },
  nodeDelete(b) { return this.post("/api/nodes/delete", b); },
  saveOrder(b) { return this.post("/api/order", b); },   // drag-to-reorder: {kind:"node"|"iface"|"turn", node?, order:[ids]}
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
  ifaceOnboard(b) { return this.post("/api/iface/onboard", b); },
  ifaceCreate(b) { return this.post("/api/iface/create", b); },
  ifaceCancel(b) { return this.post("/api/iface/cancel", b); },
  ifaceDelete(b) { return this.post("/api/iface/delete", b); },
  ifaceRestart(b) { return this.post("/api/iface/restart", b); },   // bounce the iface service on the node
  ifaceStop(b) { return this.post("/api/iface/stop", b); },         // stop (down + disable) the iface
  ifaceStart(b) { return this.post("/api/iface/start", b); },       // start (up + enable) the iface
  ifaceAdopt(b) { return this.post("/api/iface/adopt", b); },     // drift: pull the node's server-edited value
  ifaceRestore(b) { return this.post("/api/iface/restore", b); }, // drift: re-assert the panel's value
  turnManage(b) { return this.post("/api/turn/manage", b); },     // edit listen/connect (+ wrap key)
  turnTitle(b) { return this.post("/api/turn/title", b); },       // set the display title only — no restart/bounce
  turnRotate(b) { return this.post("/api/turn/rotate", b); },     // regenerate the wrap key
  turnDelete(b) { return this.post("/api/turn/delete", b); },         // stop + remove the service
  turnRestart(b) { return this.post("/api/turn/restart", b); },       // restart the service
  turnStop(b) { return this.post("/api/turn/stop", b); },             // stop the service (kept down, survives reconcile)
  turnStart(b) { return this.post("/api/turn/start", b); },           // start a stopped service
  turnReinstall(b) { return this.post("/api/turn/reinstall", b); },   // re-download the binary (fix a failed install / update) + (re)start
  turnInstall(b) { return this.post("/api/turn/install", b); },       // install a new turn-proxy (download + unit)
  turnOnboard(b) { return this.post("/api/turn/onboard", b); },       // adopt a host .service by path
  turnCancel(b) { return this.post("/api/turn/cancel", b); },
  turnCheckUpdates(b) { return this.post("/api/turn/check-updates", b); },   // resolve each fork's latest release tag
  nodeSelfUpdate(b) { return this.post("/api/node/update", b); },   // flag a node to self-update (≠ nodeUpdate, which renames)
  hostUpdate() { return this.post("/api/host/update", {}); },
  checkUpdate() { return this.post("/api/update/check", {}); },
  procClearNode(node) { return this.post("/api/node/proc-clear", { node }); },   // dismiss a stuck/failed re-install/convert/update tag
  procClearHost() { return this.post("/api/host/proc-clear", {}); },
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
  rotating: {},              // peer id -> ts — key rotation in flight; grid shows "rotating" until the new key is live
  ifaceOp: {},               // "node|iface" -> { verb:start|restart, phase:busy|ok|fail, started, until, err }
  ifaceNew: {},              // "node|iface" -> { type } — optimistic "creating/onboarding" card shown the instant Create is clicked (until the server's own pending/meta picks it up)
  turnNew: {},               // "node|service" -> { listen, connect, ... } — optimistic "installing" turn card (full entered data), shown until the node reports the real proxy
  pending: {},               // opId -> { apply(store), done }  — optimistic overlay (Model B)
  rowErrors: {},             // entityKey -> { msg, at }        — explained failure, shown on the row
  async init() {
    await this.poll();
    // Poll every 5s, but SKIP while the tab is HIDDEN — a background tab needs no live data, and each poll
    // makes the (often 1-CPU) panel rebuild the /api/state bundle. Resume with an immediate poll the moment
    // the operator returns, so they never look at stale numbers.
    setInterval(() => { if (document.visibilityState !== "hidden") this.poll().catch(() => {}); }, 5000);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") this.poll().catch(() => {}); });
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
    this.panelSettings = d.panel_settings || this.panelSettings || {};
    applyForkColors();   // keep every .tf-<fork> tag/badge in sync with the picker override
    applyThemeColors();  // keep wg/awg/blocked/faulty colours + the --brand theme in sync with the pickers
    this.smartCaps = d.smart_caps || this.smartCaps || {};   // per-category {ip,host} → [IP]/[Host] grouping + kernel-mode greying
    this.catDomains = d.cat_domains || this.catDomains || {};   // curated domains per host category → hover tooltip
    this.catLabels = d.cat_labels || this.catLabels || {};   // custom_<hash> → custom-list title (for the destination bars)
    this.catalogProviders = d.catalog_providers || this.catalogProviders || [];   // Geo-data provider registry [{id,label,url,tiers,enabled,error}]
    this.catSizes = d.cat_sizes || this.catSizes || {};   // {cat:{ip,host}} resolved-list record counts → list-size display
    this.env = d.env || this.env || {};
    this.versions = d.versions || this.versions;
    this.latestRemote = d.latest_remote; this.panelOutdated = !!d.panel_outdated;
    if (s && s.ok) { this.hostProc = d.host_proc || null; this.hostProcErr = d.host_proc_err || null; }   // only on a clean poll → the tag HOLDS through the panel's own re-install downtime
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
    const retiring = new Set();   // pubkeys mid-removal (rotation/delete) — keep them out of the orphans grid
    for (const n of this.nodes) for (const pk of (n.retiring || [])) retiring.add(pk);
    const systemIfaces = new Set();   // node|iface that are panel-managed mesh links (swg_*) — their peers
    for (const nid of Object.keys(this.describe || {}))   // are managed via nodes.json, NOT the roster: not orphans
      for (const ifn of Object.keys(this.describe[nid] || {}))
        if (this.describe[nid][ifn] && this.describe[nid][ifn].system) systemIfaces.add(nid + "|" + ifn);
    const _adv = (this.panelSettings || {}).advanced || {};   // operator-tunable stale/grace thresholds
    // rx-history for FAULTY detection persists across polls (keyed node|iface|pubkey, like reconcile's `observed`)
    this._rxHistory = this._rxHistory || {};
    const _sc = (this.panelSettings || {}).status_conditions || {};   // peer-health detection toggles (default on)
    this.recon = reconcile(this.roster, this.stats, Date.now(), { retiring, systemIfaces, rotating: new Set(Object.keys(this.rotating)),
      history: this._rxHistory, faultyMs: _adv.faulty_ms || 45000,
      detectBlocked: _sc.blocked !== false, detectFaulty: _sc.faulty !== false,
      ...(_adv.node_stale_ms ? { nodeStaleMs: _adv.node_stale_ms } : {}), ...(_adv.peer_grace_ms ? { graceMs: _adv.peer_grace_ms } : {}) });
    // a rotation is "done" once the new key shows up live (or after a 45s safety cap) — drop the marker
    for (const id of Object.keys(this.rotating)) {
      const pr = this.recon.peers.find(p => p.id === id);
      if ((pr && (pr.status === "online" || pr.status === "ready" || pr.status === "partial")) || (Date.now() - this.rotating[id] > 45000)) delete this.rotating[id];
    }
    try { recordDashTick(); } catch (_) {}   // accumulate the dashboard's live-only trend series (online counts)
    bus.emit();
  },
  node(id) { return this.fleet.find(n => n.id === id); },              // lookup by stable id
  nodeName(id) { const n = this.node(id); return (n && n.name) || id; }, // display title (falls back to id)
  nodeColor(id) { const n = this.node(id); return pickThemed(n && n.color, NODE_COLOR_DEFAULT.dark, NODE_COLOR_DEFAULT.light); },
  ifacesOf(node) { return Object.keys(this.describe[node] || {}); },   // node = id (describe keyed by id)
  ifaceMeta(node, iface) { return (this.describe[node] || {})[iface] || null; },
  // a panel-managed inter-node mesh link (swg_*): never a user-peer target / egress NIC. Authoritative
  // signal is the backend `.system` flag; fall back to the reserved prefix for un-updated nodes.
  ifaceIsSystem(node, iface) {
    if (!iface) return false;
    const m = (this.describe[node] || {})[iface] || {};
    const pfx = (this.panelSettings || {}).reserved?.iface_prefix || "swg_";
    return !!m.system || String(iface).startsWith(pfx) || String(iface).startsWith("swg_");
  },
  userIfacesOf(node) { return this.ifacesOf(node).filter(i => !this.ifaceIsSystem(node, i)); },
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
// a node is "stale" when its last snapshot is older than the staleness window (reconcile.js) — we can't
// trust any live state then, so cross-reference badges grey out (don't claim "active" on a node gone dark).
function nodeStale(node) { return Store.recon.nodeStatus[node] !== "live"; }
function ifaceDown(node, ifn) { return !!(((((Store.stats[node] || {}).interfaces) || {})[ifn] || {}).down); }
function ifaceNotUp(node, ifn) { const s = (((Store.stats[node] || {}).interfaces) || {})[ifn] || {}; return !!s.down || !!s.stopped; }  // down OR stopped → grey chips
function turnDown(tp) { return tp && tp.running === false; }
// turn badges for an interface card: one fork-coloured "turn" chip per distinct forwarding fork
// (collapses to one in the common single-fork case), greyed when that fork's proxies are all down / node stale.
// When MORE THAN 3 turn-proxies forward here the per-fork list gets noisy, so collapse to ONE badge in the
// general turn colour + a "×N" count; hovering opens a small portaled bubble listing each proxy as a
// fork-coloured badge + its title.
// hover bubble body for a set of forwarding proxies: one line each — fork badge (own colour) + title.
function turnListRows(list) {
  return list.map(tp => { const f = turnFork(tp.service); return html`<div class=${"turnlist-row" + (turnDown(tp) ? " muted" : "")}>
    <span class="tg tg-turn" style=${"--tfc:" + turnColor(f)}>${f}</span>${tp.title ? html`<span class="turnlist-ttl">${tp.title}</span>` : null}</div>`; });
}
// each turn badge on an interface card gets a hover-only bubble listing its proxies; clicks fall through to
// the card link (hoverOnly). ≤3 forwarding proxies → one fork-coloured chip per fork; >3 → collapse to one
// general-colour "turn ×N" badge (the per-fork list gets noisy), same bubble listing all of them.
function ifaceTurnBadges(node, fwdTurns, compact) {
  if (!fwdTurns || !fwdTurns.length) return null;
  const stale = nodeStale(node);
  const bubble = (trigger, list) => html`<${Popover} hoverOnly cls="turncollwrap" popCls="turnlist" trigger=${trigger}>${turnListRows(list)}<//>`;
  if (fwdTurns.length > 3) {
    const allDown = fwdTurns.every(turnDown);
    const trigger = html`<span class=${"tg tg-turn tf-gen turncoll" + ((stale || allDown) ? " muted" : "") + (compact ? " mini" : "")}>${compact ? "t" : "turn"}<b class="turnx">×${fwdTurns.length}</b></span>`;
    return bubble(trigger, fwdTurns);
  }
  const groups = {};
  fwdTurns.forEach(tp => { const f = turnFork(tp.service); (groups[f] = groups[f] || []).push(tp); });
  return Object.entries(groups).map(([f, list]) => {
    const allDown = list.every(turnDown);
    const trigger = html`<span class=${"tg tg-turn tf-" + f + ((stale || allDown) ? " muted" : "") + (compact ? " mini" : "")}>${compact ? "t" : "turn"}</span>`;
    return bubble(trigger, list);
  });
}

// One turn-proxy card — shared by the node detail (Forwards-to shown) and the interface detail
// (showForwards=false, that view is already scoped to the fronted iface). Same data, status tags,
// online/down dimming, click-to-manage. `metas` = the node's all-interface metas (Store.describe[node]).
function TurnCard({ node, tp, nrec, metas, showForwards = true, reorder }) {
  metas = metas || {};
  const it = reorder ? reorder.item(tp.service) : null;
  const lp = portOf(tp.connect);
  const fronted = Object.keys(metas).find(i => String((metas[i] || {}).listen_port) === lp);
  const ftype = (fronted && metas[fronted].awg_params && Object.keys(metas[fronted].awg_params).length) ? "awg" : "wg";
  const pend = (nrec.turn_pending || {})[tp.service];
  const err = (nrec.cmd_errors || {})[tp.service];
  const prog = (nrec.cmd_progress || {})[tp.service];   // node "what's happening now" (slow GitHub download / retry) → yellow note
  const installing = !!tp.installing;   // actively being downloaded / (re)created right now
  const queued = !!tp.pending;          // not up yet, waiting its turn in the sequential reconcile
  const failed = !!tp.failed;
  const stopped = !!tp.stopped;   // intentionally stopped from the panel (kept down)
  const down = tp.running === false && !installing && !queued && !failed && !stopped;   // not-running, not in any in-flight state
  const converting = (nrec.proc_status || "").startsWith("converting");   // node is mid bare↔docker convert → every card "converting"
  const k = node + "|" + tp.service;
  const justRestarted = !pend && turnRestarted[k] && Date.now() < turnRestarted[k];
  const updating = pend && turnUpdating[k] && Date.now() < turnUpdating[k];   // a pending reinstall triggered by an "Update" click
  // in-flight label: a fresh install/reinstall reads "creating"; any other queued action (manage/rotate/…) reads its
  // action word. An Update-click reinstall walks pending (queued, node hasn't picked it up) → updating (node is
  // actively downloading/recreating — signalled by the install marker or a live progress note).
  const pendLabel = updating ? ((installing || prog) ? "updating" : "pending")
    : (pend && pend !== "install" && pend !== "reinstall") ? (TURN_PEND[pend] || "creating") : "creating";
  const dim = converting || nodeStale(node) || (!justRestarted && (installing || queued || pend || failed || down || stopped || err));   // dim through the WHOLE 'creating' phase (installing/queued/assigned) like the pending card + attention states (failed/down/stopped/deleting) — only a settled/ready card is full-bright
  const _busy = !!(queued || installing || (pend && pend !== "delete"));   // any in-flight create / install / op
  const _bad = !!(failed || down || converting || stopped);
  const _settled = !!fronted && !_bad && !_busy;                           // up + healthy
  if (turnWasInstalling[k] && !installing && !_bad) turnReady[k] = Date.now() + 5000;   // OPTIMISTIC: install just ended without failing → "ready" NOW
  if (turnWasBusy[k] && _settled) {                    // settled after any in-flight state
    turnReady[k] = Date.now() + 5000;
    if (turnWasUpd[k]) { turnUpdatedFlash[k] = Date.now() + 5000; delete turnUpdating[k]; }   // it was mid-Update → green "updated" (bare-metal reinstalls set no install marker, so key off the update flag itself)
  }
  turnWasUpd[k] = updating;   // remember for the next render's settle check
  turnWasInstalling[k] = !!installing;
  turnWasBusy[k] = _busy;
  const turnReadyNow = !_bad && !!fronted && !!turnReady[k] && Date.now() < turnReady[k];
  const conn = fronted ? turnConnRows(node, fronted, tp.service) : [];   // online peers via THIS specific proxy → header count
  const canOpen = nrec.turn_manage && !converting && !_busy && pend !== "delete";   // clickable only once it settles — NOT while creating/queued/deleting (don't open a half-created proxy)
  return html`<div class=${"ifcard tp" + (canOpen ? " clickable" : "") + (dim ? " down" : "") + (it ? it.cls : "")} onClick=${canOpen ? () => openTurnManage(node, tp) : null} data-rid=${it ? it.rid : null}>
    <div class="ifcard-top">${reorder ? html`<span class="drag-grip" title="Drag to reorder" onClick=${e => e.stopPropagation()} ...${reorder.grip(tp.service)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}<span class=${"iftype turn tf-" + turnFork(tp.service)}>turn</span><span class="ifname">${tp.title || turnFork(tp.service)}</span><span class="grow"></span>${conn.length ? html`<${OnlPop} peer title="Via this turn-proxy" cls="ifc-conn" rows=${conn} trigger=${c => html`<b class="oncount on">${c}</b>`}/>` : null}${converting
      ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title="The node is converting between bare-metal and docker"/>`
      : pend === "delete"
      ? html`<${StatusTag} cls="tg-busy del" label="deleting…" msg=${err || prog} title=${err ? "Command failed on the node" : "Working on the node"}/><button class="xbtn" title="Cancel this request" onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>`
      : installing ? html`<${StatusTag} cls=${"tg-busy" + (prog ? " warn" : "")} icon="clock" label=${pendLabel} msg=${prog} title="The node is setting it up right now"/>`
      : turnReadyNow ? html`<span class=${"tg " + ((turnUpdatedFlash[k] && Date.now() < turnUpdatedFlash[k]) ? "tg-ok" : "tg-ready")}><${Ic} i="check"/>${(turnUpdatedFlash[k] && Date.now() < turnUpdatedFlash[k]) ? "updated" : "ready"}</span>`
      : (pend || queued) ? html`<${StatusTag} cls="tg-busy" icon="clock" label=${pend ? pendLabel : "creating"} msg=${err} title=${pend ? "The node is setting it up" : "Queued — the node creates these one at a time"}/>${pend ? html`<button class="xbtn" title="Cancel this request" onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>` : null}`
      : failed ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="install failed" msg=${err || "the install failed on the node"} title="Command failed on the node"/>`
      : justRestarted ? html`<span class="tg tg-ok"><${Ic} i="check"/>restarted</span>`
      : stopped ? html`<span class="tg-off" title="Stopped from the panel — open to Start it"><${Ic} i="stop"/>stopped</span>`
      : down ? html`<${StatusTag} cls="tg-busy del" label="down" msg=${err || "service is not running on the node"} title="Service down on the node"/>`
      : (!fronted ? html`<span class="tg tg-warn" title="Forwards to a port with no managed interface behind it — likely a misconfiguration.">unbound</span>` : null)}</div>
    <div class="ifcard-rows">
      <div class="ifrow"><span class="l">Turn-proxy fork</span><span class="r">${turnFork(tp.service)}</span></div>
      <div class="ifrow"><span class="l">Listen</span><span class="r addr">${tp.listen || "—"}</span></div>
      ${showForwards ? html`<div class="ifrow"><span class="l">Forwards to</span><span class="r">${fronted ? html`<a class=${"tg tg-" + ftype + ((nodeStale(node) || ifaceNotUp(node, fronted)) ? " muted" : "")} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(fronted)} onClick=${e => e.stopPropagation()}>${fronted}</a>` : (tp.connect || "—")}</span></div>` : null}
    </div></div>`;
}

// The turn-proxies block — ONE component for both the node screen and the interface screen, so the cards
// never drift. Pass `iface` to scope it to one interface: it then (1) uses a different title, (2) shows only
// the proxies that forward to that interface, and (3) drops the "Forwards to" row. Everything else (the
// cards, the Setup button, pending/onboarding chips) is the node view and is omitted when scoped.
function TurnProxiesBlock({ node, nrec, snap, metas, title, iface }) {
  snap = snap || Store.stats[node] || {}; metas = metas || Store.describe[node] || {}; nrec = nrec || {};
  const all = snap.turn_proxies || [];
  const cards = iface ? turnProxiesFor(node, iface) : orderById(all, nrec.turn_order, tp => tp.service);
  // drag-to-reorder turn-proxies (node view only; the per-interface view is a filtered subset)
  const tReorder = useReorder(iface ? [] : cards.map(tp => tp.service), ids => mutate({
    patch: s => { const nn = (s.nodes || []).find(x => x.id === node); if (nn) nn.turn_order = ids; },
    call: () => api.saveOrder({ kind: "turn", node, order: ids }),
  }));
  if (iface && !cards.length) return null;               // interface view: nothing forwards here → no block
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);
  // client-optimistic installs: a FULL card with the entered data, dimmed + "installing", shown the instant
  // Install is clicked — until the node reports the real proxy (in `all`) or it goes stale. Keyed by service.
  const _tpfx = node + "|";
  for (const k of Object.keys(Store.turnNew)) { if (!k.startsWith(_tpfx)) continue; const s = k.slice(_tpfx.length); if (all.some(t => t.service === s) || (Date.now() - (Store.turnNew[k].at || 0) > 900000)) delete Store.turnNew[k]; }
  const optTurns = iface ? [] : Object.keys(Store.turnNew).filter(k => k.startsWith(_tpfx)).map(k => ({ svc: k.slice(_tpfx.length), d: Store.turnNew[k] })).filter(o => !all.some(t => t.service === o.svc));
  const optSvcs = new Set(optTurns.map(o => o.svc));
  const optCard = (svc, d) => { const lp = portOf(d.connect); const fronted = Object.keys(metas).find(i => String((metas[i] || {}).listen_port) === lp); const ftype = (fronted && metas[fronted].awg_params && Object.keys(metas[fronted].awg_params).length) ? "awg" : "wg";
    return html`<div class="ifcard tp down" key=${"new:" + svc}>
      <div class="ifcard-top"><span class=${"iftype turn tf-" + turnFork(svc)}>turn</span><span class="ifname">${d.title || turnFork(svc)}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[svc]}/><${StatusTag} cls="tg-pending" icon="clock" label="pending" title="Assigned — waiting for the node to pick it up and install it"/><button class="xbtn" title="Cancel this request" onClick=${() => { delete Store.turnNew[node + "|" + svc]; cancelTurn(node, { service: svc }); }}><${Ic} i="x"/></button></div>
      <div class="ifcard-rows">
        <div class="ifrow"><span class="l">Turn-proxy fork</span><span class="r">${turnFork(svc)}</span></div>
        <div class="ifrow"><span class="l">Listen</span><span class="r addr">${d.listen || "—"}</span></div>
        <div class="ifrow"><span class="l">Forwards to</span><span class="r">${fronted ? html`<a class=${"tg tg-" + ftype} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(fronted)} onClick=${e => e.stopPropagation()}>${fronted}</a>` : (d.connect || "—")}</span></div>
      </div></div>`; };
  return html`<${Panel} icon="relay" title=${title} tone="turn" count=${cards.length + optTurns.length}
      actions=${(!iface && nrec.turn_manage) ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openSetupTurn(node)}><${Ic} i="plus"/> Setup new proxy</button>` : null}>
    ${(!iface && !nrec.turn_manage) ? html`<div class="notice"><${Ic} i="info"/><span>Turn-proxy management is <b>off</b> on this node — no Docker socket was mounted at install (<b>TURN_MANAGE=manual</b>), so these are read-only here. Add, edit or restart them on the box directly.</span></div>` : null}
    <div class="ifgrid" ...${iface ? {} : tReorder.container()}>${cards.map(tp => html`<${TurnCard} key=${tp.service} node=${node} tp=${tp} nrec=${nrec} metas=${metas} showForwards=${!iface} reorder=${iface ? null : tReorder}/>`)}
    ${optTurns.map(o => optCard(o.svc, o.d))}
    ${!iface ? Object.entries(nrec.turn_pending || {}).filter(([s]) => !all.some(t => t.service === s) && !optSvcs.has(s)).map(([s, act]) => html`<div class="ifcard tp pending"><div class="ifcard-top"><span class="iftype turn">turn</span><span class="ifname">${turnLabel(s, "")}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[s]}/>${act === "delete" ? html`<span class="tg-busy del">deleting…</span>` : html`<span class="tg tg-pending"><${Ic} i="clock"/>pending</span>`}<button class="xbtn" title="Cancel this request" onClick=${() => cancelTurn(node, { service: s })}><${Ic} i="x"/></button></div></div>`) : null}
    ${!iface ? (nrec.turn_onboarding || []).map(p => html`<div class="ifcard tp pending"><div class="ifcard-top"><span class="iftype turn">turn</span><span class="ifname">adopting…</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[p]}/><span class="tg-busy">adopting…</span><button class="xbtn" title="Cancel this request" onClick=${() => cancelTurn(node, { path: p })}><${Ic} i="x"/></button></div><div class="ifcard-rows"><div class="ifrow"><span class="l faint" style="word-break:break-all">${p}</span></div></div></div>`) : null}
    </div>
  <//>`;
}

// resolve a per-target client config: session (built at creation) → stored → none
// Resolve a peer's config and RE-RENDER it on the fly: client-side fields (private key, address,
// DNS, MTU, AllowedIPs, keepalive, PSK) come from the stored/session source, but the server-facing
// fields (Endpoint, server PublicKey, AmneziaWG params) are rebuilt from the CURRENT interface
// metadata — so an interface endpoint change shows up in every config/QR without a re-issue.
function rerenderConf(text, node, iface) {
  if (!text) return text;
  const meta = Store.ifaceMeta(node, iface);
  if (!meta) return text;
  // surgical in-place updates: swap the Endpoint line and refresh any existing AmneziaWG param
  // lines to the interface's current values — never rebuild the rest, so it can't be malformed.
  let out = text;
  if (meta.endpoint) out = out.replace(/^([ \t]*Endpoint[ \t]*=).*$/m, (m, p1) => p1 + " " + meta.endpoint);
  const awg = meta.awg_params || {};
  for (const k of AWG_ORDER) {
    if (awg[k] == null) continue;
    const re = new RegExp("^([ \\t]*" + k + "[ \\t]*=).*$", "m");
    if (re.test(out)) out = out.replace(re, (m, p1) => p1 + " " + awg[k]);
  }
  return out;
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

// ───────────────────────── drag-to-reorder ─────────────────────────
// Order `items` by their position in `savedOrder` (a list of ids); ids not in the saved order keep
// their original relative order and go LAST (so a newly-reported iface/turn appears at the end).
function orderById(items, savedOrder, idOf) {
  const ord = savedOrder || [];
  if (!ord.length) return items;
  const pos = new Map(ord.map((id, i) => [id, i]));
  return items.map((it, i) => [it, i]).sort((a, b) => {
    const pa = pos.has(idOf(a[0])) ? pos.get(idOf(a[0])) : Infinity;
    const pb = pos.has(idOf(b[0])) ? pos.get(idOf(b[0])) : Infinity;
    return pa - pb || a[1] - b[1];
  }).map(x => x[0]);
}
// 6-dot grip glyph used as the drag handle on reorderable cards.
const GRIP_SVG = `<svg width="11" height="16" viewBox="0 0 11 16" fill="currentColor"><circle cx="3" cy="3" r="1.4"/><circle cx="8" cy="3" r="1.4"/><circle cx="3" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="3" cy="13" r="1.4"/><circle cx="8" cy="13" r="1.4"/></svg>`;
// HTML5 drag-reorder. `ids` is the CURRENT visible order; `onReorder(newIds)` persists it. Returns
// per-item props: grip(id) for the handle, zone(id) for the card wrapper, plus the live dragId.
// FLIP: after a reorder re-renders the (keyed) cards into new positions, slide each from where it WAS
// (`first` rects, snapshot at drop time) to where it now is, so it's visible what moved and where.
function flipPlay(container, first) {
  requestAnimationFrame(() => {
    const moved = [];
    for (const el of container.querySelectorAll("[data-rid]")) {
      const f = first.get(el.dataset.rid); if (!f) continue;
      const l = el.getBoundingClientRect();
      const dx = f.left - l.left, dy = f.top - l.top;
      if (dx || dy) { el.style.transition = "none"; el.style.transform = "translate(" + dx + "px," + dy + "px)"; moved.push(el); }   // INVERT
    }
    if (!moved.length) return;
    requestAnimationFrame(() => { for (const el of moved) { el.style.transition = "transform .24s cubic-bezier(.2,.7,.2,1)"; el.style.transform = ""; } });   // PLAY
    setTimeout(() => { for (const el of moved) { el.style.transition = ""; el.style.transform = ""; } }, 320);
  });
}
function useReorder(ids, onReorder, axis = "x", sel = {}) {   // axis "x" = horizontal grid (left/right edges); "y" = vertical list (top/bottom); sel = {container, card} CSS selectors
  const CONT_SEL = sel.container || ".ifgrid, .nodegrid";   // the drop container (dragEnd has no event target for it)
  const CARD_SEL = sel.card || ".ifcard, .ncard";           // the draggable row/card (for the floating ghost + FLIP)
  const [drag, setDrag] = useState(null);     // { id, k } — for the highlight (k = insertion index among the OTHER cards)
  const dragId = drag && drag.id;
  const prev = useRef(null);      // our floating translucent preview
  const off = useRef([0, 0]);     // cursor offset within the grabbed card
  const cont = useRef(null);      // container element (dragEnd has no event target for it)
  const liveK = useRef(-1);       // CURRENT insertion index — a ref so dragEnd never reads a stale closure
  const idRef = useRef(null);     // the dragged id
  const esc = useRef(false);      // ESC pressed mid-drag → cancel (best-effort; some browsers swallow keydown while dragging)
  const onKey = useRef(null);
  const rest = dragId ? ids.filter(x => x !== dragId) : ids;
  const k = drag ? drag.k : -1;
  const gapL = (k > 0 && k <= rest.length) ? rest[k - 1] : null;
  const gapR = (k >= 0 && k < rest.length) ? rest[k] : null;
  const trail = axis === "y" ? " drop-b" : " drop-r";
  const lead = axis === "y" ? " drop-t" : " drop-l";
  // insertion index from the cursor over the WHOLE container (releasing in a gap / past the ends still
  // lands at the nearest spot, no pixel-precise aiming). Counts the non-dragged cards before the cursor.
  const indexAt = (container, x, y) => {
    let i = 0;
    for (const el of container.querySelectorAll("[data-rid]")) {
      if (el.dataset.rid === dragId) continue;
      const r = el.getBoundingClientRect();
      if (axis === "y") { if (y > r.top + r.height / 2) i++; }
      else if (r.bottom < y) i++;
      else if (y >= r.top && (r.left + r.width / 2) < x) i++;
    }
    return i;
  };
  const movePrev = (x, y) => { if (prev.current) prev.current.style.transform = "translate(" + (x - off.current[0]) + "px," + (y - off.current[1]) + "px)"; };
  const stopPreview = () => { if (prev.current) { prev.current.remove(); prev.current = null; } };
  // Commit on dragEND (always fires) using the LAST highlighted position, so releasing OUTSIDE the
  // container still drops at the highlighted gap. ESC, or never highlighting a spot, returns to origin.
  const finish = () => {
    if (onKey.current) { window.removeEventListener("keydown", onKey.current, true); onKey.current = null; }
    const c = cont.current, kk = liveK.current, did = idRef.current, cancelled = esc.current;
    stopPreview(); cont.current = null; idRef.current = null; liveK.current = -1; esc.current = false;
    setDrag(null);
    if (cancelled || kk < 0 || !c || !did) return;            // ESC / nothing highlighted → back to original
    const first = new Map();                                   // FLIP: snapshot positions before the reorder
    for (const el of c.querySelectorAll("[data-rid]")) first.set(el.dataset.rid, el.getBoundingClientRect());
    const arr = ids.filter(x => x !== did); arr.splice(kk, 0, did);
    if (arr.join(" ") !== ids.join(" ")) { onReorder(arr); flipPlay(c, first); }
  };
  return {
    dragId,
    grip(id) {
      return {
        draggable: true,
        onDragStart: e => {
          cont.current = e.currentTarget.closest(CONT_SEL);
          idRef.current = id; liveK.current = -1; esc.current = false;
          onKey.current = ev => { if (ev.key === "Escape") esc.current = true; };
          window.addEventListener("keydown", onKey.current, true);
          const card = e.currentTarget.closest(CARD_SEL);
          try {
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", id);
            const empty = new Image(); empty.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
            e.dataTransfer.setDragImage(empty, 0, 0);
            if (card) {
              const r = card.getBoundingClientRect();
              off.current = [e.clientX - r.left, e.clientY - r.top];
              const g = card.cloneNode(true);
              g.classList.add("drag-ghost");
              g.style.cssText = "position:fixed;left:0;top:0;margin:0;width:" + r.width + "px;height:" + r.height + "px;pointer-events:none;z-index:9999;transform:translate(" + r.left + "px," + r.top + "px)";
              document.body.appendChild(g);
              prev.current = g;
            }
          } catch (_) {}
          setDrag({ id, k: -1 });
        },
        onDrag: e => { if (e.clientX || e.clientY) movePrev(e.clientX, e.clientY); },   // follow the cursor (fires even outside the container)
        onDragEnd: () => finish(),
      };
    },
    container() {
      return {
        onDragOver: e => { if (!dragId) return; e.preventDefault(); try { e.dataTransfer.dropEffect = "move"; } catch (_) {}
          movePrev(e.clientX, e.clientY);
          const nk = indexAt(e.currentTarget, e.clientX, e.clientY);
          liveK.current = nk;
          if (!drag || drag.k !== nk) setDrag({ id: dragId, k: nk }); },
        onDrop: e => { e.preventDefault(); },   // the real commit happens in dragEnd (covers release-outside too)
      };
    },
    item(id) {
      return { rid: id, cls: (dragId === id ? " dragging" : "") + (id === gapL ? trail : "") + (id === gapR ? lead : "") };
    },
  };
}

// ───────────────────────── modal ─────────────────────────
// Modal STACK. openModal replaces the current top (so every legacy single-modal flow behaves exactly
// as before — the stack is just length 1), pushModal stacks a CHILD over its parent (parent stays
// open behind it), closeModal pops back to the parent. _stack is a synchronous mirror of the state.
let _setStack = () => {};
let _stack = [];
let _modalSeq = 0;   // bumps on every open/close — lets a confirm tell if onConfirm replaced the modal
function _applyStack(next) { _stack = next; _modalSeq++; _setStack(next); }
function openModal(node) { _applyStack(_stack.length ? [..._stack.slice(0, -1), node] : [node]); }
function pushModal(node) { _applyStack([..._stack, node]); }
function closeModal() { _applyStack(_stack.slice(0, -1)); }
function closeAllModals() { _applyStack([]); }
let _sheetStack = [];   // mounted Sheet tokens (LIFO) — only the topmost handles Esc/Enter/Tab

// ───────────────────────── shared bits ─────────────────────────
const IFOP_BUSY = { start: "starting", stop: "stopping", restart: "restarting", apply: "applying" };   // interface op lifecycle labels
const IFOP_DONE = { start: "started", stop: "stopped", restart: "restarted", apply: "applied" };
const IFOP_FAIL = { start: "failed to start", stop: "failed to stop", restart: "failed to restart", apply: "failed to apply" };
const STATUS_RANK = { dangling: 0, blocked: 1, faulty: 1, partial: 1, pending: 2, creating: 2, rotating: 2, unknown: 3, unassigned: 4, online: 5, ready: 6 };
const STATUS_ICON = { online: "check", ready: "clock", partial: "warn", pending: "clock", creating: "clock", rotating: "refresh",
  blocked: "warn", faulty: "warn", dangling: "err", unknown: "info", unassigned: "user", orphan: "link", removing: "trash", empty: "info" };
// a node/panel host that's mid re-install or method conversion (signalled before it goes down)
const PROC_LABEL = {
  reinstalling: "re-installing", "converting-bare": "converting to bare-metal", "converting-docker": "converting to docker", updating: "updating", uninstalling: "uninstalling",
  reinstalled: "re-installed", "reinstalled-updated": "re-installed and updated", "converted-bare": "converted to bare-metal", "converted-docker": "converted to docker", updated: "updated", uptodate: "up to date",
  "reinstall-aborted": "re-install aborted", "convert-aborted": "convert aborted", "update-aborted": "update aborted", "uninstall-aborted": "uninstall aborted",
  "reinstall-failed": "re-install failed", "convert-failed": "convert failed", "update-failed": "update failed", "uninstall-failed": "uninstall failed", failed: "failed" };
// a node still AWAITING ENROLL never came up, so a "re-install" of it is really a first install — relabel the reinstall* states
const PROC_LABEL_FRESH = { reinstalling: "installing", reinstalled: "installed", "reinstalled-updated": "installed and updated",
  "reinstall-aborted": "install aborted", "reinstall-failed": "install failed" };
// Lifecycle tag categories. inProc = an op actually running (violet clock, blocks actions). Terminals:
// success (green, ~5s, no ×), aborted (grey + ×), failed (red + error popup + ×) — all shown beside the real status.
const procFailed  = s => !!s && /failed$/.test(s);
const procAborted = s => !!s && /aborted$/.test(s);
const procSuccess = s => s === "reinstalled" || s === "reinstalled-updated" || s === "converted-bare" || s === "converted-docker" || s === "updated" || s === "uptodate";
const isUpdateState = s => s === "updating" || s === "updated" || s === "update-failed" || s === "update-aborted" || s === "uptodate";   // the whole UPDATE lifecycle lives ONLY in the dh-ver pill, never as a proc-tag beside the node title
const inProc      = s => !!s && !procFailed(s) && !procAborted(s) && !procSuccess(s);
// in-progress proc-tag colour by op — converting→purple, uninstalling→red, everything else active (re-installing /
// updating / installing) → yellow. (pending→blue and ready→green are handled by the turn/iface lifecycle classes.)
const procInClass = s => s === "uninstalling" ? "procuninstall" : (s || "").startsWith("converting") ? "procconvert" : "procbusy";
function procTag(state, onX, err, fresh) {
  const lbl = (fresh && PROC_LABEL_FRESH[state]) || PROC_LABEL[state] || state;
  if (procSuccess(state)) return html`<span class="nstat procok"><${Ic} i="check"/> ${lbl}</span>`;   // green, auto-clears (no ×)
  const xbtn = onX ? html`<button class="xbtn" title="Dismiss — show the node's actual status" onClick=${e => { e.stopPropagation(); e.preventDefault(); onX(e); }}><${Ic} i="x"/></button>` : null;
  if (procAborted(state)) return html`<span class="nstat procaborted"><${Ic} i="info"/> ${lbl}${xbtn}</span>`;
  if (procFailed(state)) {   // whole tag clickable → details popup (when there's a log tail), distinct hover, no caption
    const open = err ? (e => { e.stopPropagation(); e.preventDefault(); openConfirm({ title: lbl, log: err, confirmLabel: "Close" }); }) : null;
    return html`<span class=${"nstat procfail" + (open ? " tg-click" : "")} onClick=${open}><${Ic} i="warn"/> ${lbl}${xbtn}</span>`;
  }
  return html`<span class=${"nstat " + procInClass(state)}><${Ic} i="clock"/> ${lbl}</span>`;   // in-progress (colour by op)
}
function dismissNodeProc(id) {   // optimistic: drop the tag NOW, clear on the server in the background; re-poll only if it fails
  const n = (Store.nodes || []).find(x => x.id === id);
  if (n) { n.proc_status = null; n.proc_err = null; bus.emit(); }
  api.procClearNode(id).then(r => { if (r && r.ok === false) { toast(r.error || "Couldn't dismiss.", "err"); Store.poll(); } });
}
function dismissHostProc() {   // optimistic
  Store.hostProc = null; Store.hostProcErr = null; bus.emit();
  api.procClearHost().then(r => { if (r && r.ok === false) { toast(r.error || "Couldn't dismiss.", "err"); Store.poll(); } });
}
function Badge({ s, title }) {
  const ic = STATUS_ICON[s];
  // online → a glowing animated dot in the status colour (green), not a check — matches the turn badge
  if (s === "online") return html`<span class="badge b-online" title=${title || ""}><span class="sdot"></span>online</span>`;
  return html`<span class=${"badge b-" + s + (ic ? " ic" : "")} title=${title || ""}>${ic ? html`<${Ic} i=${ic}/>` : null}${s}</span>`;
}

// inline metadata tag (protocol / interface / turn-proxy / generic) — the dense, colored
// row signature. iface tags take the node's colour via --tgc.
function Tag({ kind, label, color, muted }) {
  return html`<span class=${"tg tg-" + (kind || "gen") + (muted ? " muted" : "")} style=${color && !muted ? "--tgc:" + color : ""}>${label}</span>`;
}
// the tags that describe a peer's deployment on a (node,iface): protocol + interface + turn-proxy.
// `muted` greys them out for inactive (offline / dangling / disconnected) rows.
function targetTags(node, iface, type, via, muted, viaTurn) {
  const tags = [];
  const proto = (type || "").toLowerCase();
  if (proto === "awg") tags.push(html`<${Tag} kind="awg" label="awg" muted=${muted}/>`);
  else if (proto === "wg") tags.push(html`<${Tag} kind="wg" label="wg" muted=${muted}/>`);
  if (viaTurn) {
    // peer came in THROUGH a turn-proxy → tint the interface badge with the proxy's colour + a hover bubble
    const tn = turnLabel(viaTurn), tc = turnColor(tn);
    tags.push(html`<span class="turnwrap"><${Tag} kind="iface" label=${iface} color=${tc} muted=${muted}/><span class="turnbub">Connected via <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span></span></span>`);
  } else {
    tags.push(html`<${Tag} kind="iface" label=${iface} color=${Store.nodeColor(node)} muted=${muted}/>`);
    if (via === "turn" || turnProxiesFor(node, iface).length) tags.push(html`<${Tag} kind="turn" label="turn" muted=${muted}/>`);
  }
  return tags;
}
// operator title of a turn-proxy (by service) on a node, if one was set — for the "Connected via" bubble
function turnProxyTitle(node, service) {
  const tp = ((Store.stats[node] || {}).turn_proxies || []).find(x => x && x.service === service);
  return (tp && tp.title) || "";
}
// The interface badge for one peer-grid row (protocol + iface name).
function gridIfaceTag(t) {
  const kind = (t.type || "").toLowerCase() === "awg" ? "awg" : "wg";
  return html`<${Tag} kind=${kind} label=${t.iface} muted=${!t.online}/>`;
}
// Status badge for a peer-grid row. A peer ONLINE through a turn-proxy takes the fork colour on its status
// badge with a glowing animated dot, plus a "Connected via <fork> <title>" hover bubble — consistent in
// every grid regardless of which columns are shown. Otherwise the normal Badge.
const STATUS_REASON = {
  blocked: "reaching the server but the handshake never completes — likely DPI / MTU / wrong AmneziaWG params",
  faulty: "connected, but no inbound data is flowing — likely a one-way block / DPI on the return path",
};
function gridStatusBadge(t, p) {
  const st = t.status || p.status;
  const reason = (t.down ? "Interface " + t.iface + " is down — " + t.down : (p.reason || STATUS_REASON[st])) || "";
  if (t.online && t.viaTurn) {
    const tn = turnLabel(t.viaTurn), tc = turnColor(tn), ptitle = turnProxyTitle(t.node, t.viaTurn);
    return html`<span class="turnwrap">
      <span class="badge b-turn" style=${"--tfc:" + tc}><span class="sdot"></span>${st}</span>
      <span class="turnbub">Connected via <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  // Blocked / Faulty carry an explanation — show it in our own hover bubble (like the "Connected via" one) instead
  // of a native title, colour-headed with the status colour so the *why* reads at a glance.
  if ((st === "blocked" || st === "faulty") && reason) {
    const bc = "var(--fault)";
    return html`<span class="turnwrap">
      <${Badge} s=${st}/>
      <span class="turnbub statusbub"><span class="statusbub-h" style=${"color:" + bc}><${Ic} i="warn"/>${st === "blocked" ? "Blocked" : "Faulty"}</span>${reason}</span></span>`;
  }
  return html`<${Badge} s=${st} title=${reason}/>`;
}
// Compact live-status dot for the connections monitor. Same turn language as the peer-grid status badge,
// scaled down to a single dot: online-via-turn → the fork-coloured glowing dot + "Connected via <fork>
// <title>" bubble; online (direct) → a green glowing dot; otherwise a neutral idle dot.
function connDot(r) {
  if (r.online && r.viaTurn) {
    const tn = turnLabel(r.viaTurn), tc = turnColor(tn), ptitle = turnProxyTitle(r.node, r.viaTurn);
    return html`<span class="turnwrap">
      <span class="condot turn" style=${"--tfc:" + tc}></span>
      <span class="turnbub">Connected via <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  return html`<span class=${"condot " + (r.online ? "on" : "off")} title=${r.online ? "online" : "idle"}></span>`;
}
// Endpoint cell for the live grids. A peer that came IN through a turn-proxy has its endpoint on the node's
// loopback (127.0.0.1) — the relay forwards locally — so instead of the bare IP show "Local turn-proxy" tinted
// with the fork colour + the same "Connected via <fork>" hover bubble the status dot uses.
function endpointCell(t) {
  const obs = t.observed;
  if (t.online && t.viaTurn) {
    const tn = turnLabel(t.viaTurn), tc = turnColor(tn), ptitle = turnProxyTitle(t.node, t.viaTurn);
    return html`<span class="turnwrap">
      <span class="addr turnep" style=${"color:" + tc}>turn-proxy</span>
      <span class="turnbub">Connected via <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  return html`<span class="addr" title=${(obs && obs.endpoint) || ""}>${(obs && ipOf(obs.endpoint)) || "—"}</span>`;
}
// rate cell, green when traffic is flowing
// Throughput display perspective (Panel settings): node-reported rx/tx is from the NODE's view (rx=down,
// tx=up). "peers" flips it to the client's view — the peer's download is what the node uploads (tx), etc.
// dlul(rx, tx) returns [downValue, upValue] for whichever perspective is active. Numbers are unchanged;
// only which one is labelled ↓ vs ↑ swaps.
const dlul = (rx, tx) => ((Store.panelSettings || {}).throughput_perspective === "peers") ? [tx || 0, rx || 0] : [rx || 0, tx || 0];
function rateCell(rx, tx) {
  const live = (rx || 0) + (tx || 0) > 0; const [d, u] = dlul(rx, tx);
  return html`<span class=${"ratecell" + (live ? " live" : "")}>↓ ${rate(d)} <span class="up">↑ ${rate(u)}</span></span>`;
}
// cumulative transfer cell — same down/up colours as rateCell (green ↓ / blue ↑ once anything moved). Takes
// already perspective-adjusted down/up byte totals.
function xferCell(db, ub) {
  const has = (db || 0) + (ub || 0) > 0;
  return html`<span class=${"addr xfer" + (has ? " live" : "")}>↓ ${fmtBytes(db)} <span class="up">↑ ${fmtBytes(ub)}</span></span>`;
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

// Minimal portal — renders children into a body-level node. A position:fixed popover that lives inside a
// card paints BEHIND a later sibling once its own card forms a stacking context (turn cards lift with a
// transform on hover; a `.down` card carries opacity:.5) — z-index can't rescue it across contexts.
// Rendering at <body> escapes every ancestor context. Preact core has no createPortal, so we drive a
// detached container with render().
function Portal({ children }) {
  const host = useRef(null);
  if (!host.current) host.current = document.createElement("div");
  useEffect(() => { const el = host.current; document.body.appendChild(el); return () => { render(null, el); el.remove(); }; }, []);
  useEffect(() => { render(children, host.current); });
  return null;
}

// Generic hover/click bubble (the DepBadge mechanics, reusable): hover opens, click pins (touch),
// position:fixed anchored to the trigger so overflow:hidden can't clip it. The bubble is PORTALED to
// <body> so it floats above sibling cards regardless of their stacking contexts.
// hoverOnly: no click-to-pin — clicks fall through to whatever the trigger sits inside (e.g. a card link),
// so a badge can show a hover bubble AND still navigate on click.
function Popover({ trigger, cls, popCls, alignRight, children, hoverOnly }) {
  const [open, setOpen] = useState(false), [pinned, setPinned] = useState(false), [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null), closeT = useRef(null);
  const show = open || pinned;
  const cancelClose = () => clearTimeout(closeT.current);
  const scheduleClose = () => { cancelClose(); closeT.current = setTimeout(() => setOpen(false), 140); };
  // alignRight: anchor the popover's left to the trigger's RIGHT edge, then translateX(-100%) so its own right
  // edge lines up there (under the value, not the label) — scrollbar-proof, no width guessing.
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    setPos({ left: Math.round(alignRight ? r.right + 3 : r.left), top: Math.round(r.bottom + 6) }); };   // alignRight: +3px so the bubble's right edge sits a touch past where the value ends
  useEffect(() => {
    if (!show) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) { setPinned(false); setOpen(false); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    if (pinned) document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [show, pinned]);
  useEffect(() => () => clearTimeout(closeT.current), []);
  return html`<span class=${(cls || "") + (show ? " on" : "")} ref=${ref}
    onClick=${hoverOnly ? null : (e => { e.stopPropagation(); e.preventDefault(); setPinned(p => !p); })}
    onMouseEnter=${() => { cancelClose(); setOpen(true); }} onMouseLeave=${scheduleClose}>${trigger}
    ${show && pos ? html`<${Portal}><div ref=${popRef} class=${"deppop onlpop " + (popCls || "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px" + (alignRight ? ";transform:translateX(-100%)" : "")}
      onClick=${e => e.stopPropagation()} onMouseEnter=${cancelClose} onMouseLeave=${scheduleClose}>${children}</div><//>` : null}
  </span>`;
}

// online USERS + their online-peer counts — global (nodeId null) or scoped to a node
const _byHandshake = (a, b) => {   // most-recent handshake first; never-seen last
  const av = a.lastAge == null ? Infinity : a.lastAge, bv = b.lastAge == null ? Infinity : b.lastAge;
  return av - bv;
};
function orphCount(nodeId, iface) {
  return (Store.recon.orphans || []).filter(o => o.node === nodeId && (iface == null || o.iface === iface)).length;
}
function onlineUserRows(nodeId) {
  const m = {};
  (Store.recon.peers || []).forEach(p => {
    const isOn = nodeId ? p.targets.some(t => t.node === nodeId && t.online) : p.online;
    if (!isOn) return;
    const id = p.unassigned ? "_un" : ("u" + p.user_id);
    if (!m[id]) m[id] = { name: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"), count: 0, unassigned: !!p.unassigned, lastAge: null };
    m[id].count++;
    if (p.lastHandshakeAge != null) m[id].lastAge = (m[id].lastAge == null) ? p.lastHandshakeAge : Math.min(m[id].lastAge, p.lastHandshakeAge);
  });
  return Object.values(m).sort(_byHandshake);
}
// online PEERS on an interface (or the whole node when iface == null), each with its owning user
function onlinePeerRows(nodeId, iface) {
  const onT = (t) => t.node === nodeId && (iface == null || t.iface === iface) && t.online;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || "(peer)", user: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"),
               ip: t.ip || "", iface: t.iface, unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}
// peers reaching `iface` THROUGH a turn-proxy: online, and the wg-observed endpoint IP == the proxy's
// connect IP (so they came via the relay, not directly). connectIp = ipOf(turn.connect).
// online peers attributed to THIS specific turn-proxy. Reconcile maps a peer's observed endpoint IP to one
// service (turnIp), so a peer counts for exactly one proxy — several proxies sharing 127.0.0.1 no longer all
// claim the same connection (was matched by connect IP, which is identical across proxies on one wg port).
function turnConnRows(nodeId, iface, service) {
  const onT = (t) => t.node === nodeId && t.iface === iface && t.online && t.viaTurn === service;
  return (Store.recon.peers || []).filter(p => p.targets.some(onT))
    .map(p => { const t = p.targets.find(onT) || {};
      return { title: p.title || p.name || "(peer)", user: p.unassigned ? "Unassigned" : (p.name || "(unnamed)"), ip: t.ip || "", unassigned: !!p.unassigned, lastAge: p.lastHandshakeAge }; })
    .sort(_byHandshake);
}
// shared online-breakdown bubble: a Live-linked header, top-10 rows (already handshake-sorted), an
// optional "n orphan peers" line, and a "view all" link past 10. trigger: (count)=>vnode.
function OnlPop({ title, rows, peer, orphans, orphHref, trigger, cls }) {
  const renderRow = peer
    ? r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.title}</span><span class="on-user faint">${r.user}${r.iface ? " · " + r.iface : ""}${r.ip ? " · " + r.ip : ""}</span></div>`
    : r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.name}</span><span class="on-ct">${r.count} <span class="faint">peer${r.count > 1 ? "s" : ""}</span></span></div>`;
  return html`<${Popover} cls=${"onlinetag " + (cls || "")} trigger=${trigger(rows.length)}>
    <a class="onpop-h onpop-link" href="#/connections" onClick=${e => e.stopPropagation()}>${title} · ${rows.length} →</a>
    ${rows.length ? rows.slice(0, 10).map(renderRow) : html`<div class="onrow faint">${peer ? "no peers online" : "no one online"}</div>`}
    ${orphans ? html`<a class="onpop-orph" href=${orphHref || "#/connections"} onClick=${e => e.stopPropagation()}>${orphans} unmanaged orphan peer${orphans > 1 ? "s" : ""}</a>` : null}
    ${rows.length > 10 ? html`<a class="onpop-viewall" href="#/connections" onClick=${e => e.stopPropagation()}>view all ${rows.length} connections →</a>` : null}
  </${Popover}>`;
}
// ───── mesh health: per-node, per-direction link status (down = other→this · up = this→other) ─────
// OUT (this node → peer) = this node's reported handshake on its link iface. IN (peer → this node) = the
// PEER's reported handshake on its iface back to this node. Both come from snapshots the panel already has.
function meshHealth(nodeId) {
  const byId = id => (Store.nodes || []).find(n => n.id === id);
  const mp = (byId(nodeId) || {}).mesh_peers || [];
  const hs = (nid, iface) => iface ? (((Store.describe || {})[nid] || {})[iface] || {}).handshake_age : undefined;
  const stat = (nid, iface, reprov) => reprov ? "connecting"
    : (nodeStale(nid) || !iface) ? "down"
    : (hs(nid, iface) == null ? "connecting" : (hs(nid, iface) < 180 ? "up" : "down"));
  const peers = mp.map(({ peer, iface, reprovisioning }) => {
    const pmp = ((byId(peer) || {}).mesh_peers || []).find(x => x.peer === nodeId) || {};
    return { peer, out: stat(nodeId, iface, reprovisioning), in: stat(peer, pmp.iface, pmp.reprovisioning) };
  });
  return { peers, total: peers.length,
    okIn: peers.filter(p => p.in === "up").length, okOut: peers.filter(p => p.out === "up").length };
}
const meshTone = (ok, total) => total === 0 ? "off" : ok === total ? "ok" : ok === 0 ? "bad" : "warn";
const mhArrow = (dir, status) => html`<span class=${"mh-ar mh-" + dir + " s-" + status}>${dir === "down" ? "↓" : "↑"}</span>`;
// mode "in" → node-detail header (inbound only) · mode "both" → nodes-list (down = inbound, up = outbound)
function MeshStat({ nodeId, mode }) {
  const h = meshHealth(nodeId);
  if (!h.total) return null;
  // all-up → the arrow's colour (inbound green · outbound blue) · none up → red · partial → orange
  const num = (ok, dir) => html`<b class=${"mh-num " + (mode === "in" ? "mh-num-hdr " : "") + (ok >= h.total ? dir : ok === 0 ? "mhn-bad" : "mhn-warn")}>${ok}/${h.total}</b>`;
  const ordered = (Store.nodes || []).filter(n => h.peers.some(p => p.peer === n.id));
  const row = n => {   // node name FIRST, then the glowing arrow(s)
    const p = h.peers.find(x => x.peer === n.id);
    const nameCls = p.in === "up" ? "mh-bold" : p.in === "down" ? "mh-dim" : "";
    return html`<div class="mh-row"><span class=${"mh-rn " + nameCls} style=${"color:" + Store.nodeColor(n.id)}>${n.name}</span><span class="mh-rar">${mhArrow("down", p.in)}${mode === "both" ? mhArrow("up", p.out) : null}</span></div>`;
  };
  const trigger = mode === "in"
    ? html`<span class="mh-tag mh-tag-hdr"><span class="mh-lbl-hdr">This node's mesh status:</span> ${num(h.okIn, "mhn-down")}</span>`
    : html`<span class="mh-tag"><span class="nm-l">Mesh</span><span class="mh-grp"><span class="mh-ar mh-down s-up">↓</span>${num(h.okIn, "mhn-down")}</span><span class="mh-grp"><span class="mh-ar mh-up s-up">↑</span>${num(h.okOut, "mhn-up")}</span></span>`;
  return html`<${Popover} cls="mh-pop" popCls="mh-bubble" alignRight=${true} trigger=${trigger}>
    <div class="onpop-h">${mode === "in" ? "Inbound links" : "Mesh connections"}</div>
    ${ordered.map(row)}
  </${Popover}>`;
}
// "N online" tag → users bubble. nodeId null = whole fleet. trigger: optional (count)=>vnode.
function OnlineUsersTag({ nodeId, cls, trigger }) {
  return html`<${OnlPop} title="Online users" rows=${onlineUserRows(nodeId)} cls=${cls}
    trigger=${trigger || (c => html`<span class="dot"></span><b class=${"oncount" + (c ? " on" : "")}>${c}</b> online`)}/>`;
}
// "N online" peers bubble (device · user · ip). orphans: count to append. Used on interface cards/screens.
function OnlinePeersTag({ nodeId, iface, total, cls, trigger, orphans, orphHref }) {
  return html`<${OnlPop} peer title="Online peers" rows=${onlinePeerRows(nodeId, iface)} orphans=${orphans} orphHref=${orphHref} cls=${cls}
    trigger=${trigger || (c => html`<b class=${"oncount" + (c ? " on" : "")}>${c}</b>${total != null ? " / " + total : ""} online`)}/>`;
}

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
    onOk: () => { Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; revealAssignedPeer(userId, peer.id); },
  });
}

// Rotate a peer's keypair while KEEPING its PSK (PSK is user-owned — rotated only from the user
// module). Mints a new keypair in the browser, preserves each target's current config settings
// (DNS/MTU/AllowedIPs/keepalive) where readable, and re-issues. The old config stops working,
// so the client must re-import the fresh QR/config. Only meaningful for an assigned peer.
async function rotatePeerKeys(peer) {
  const key = "peer:" + peer.id;
  Store.rotating[peer.id] = Date.now();   // grid shows "rotating" until the new key is live
  let keys, psk, configs;
  try {
    keys = await genKeys(); psk = genPSK(); configs = {};   // rotate BOTH the keypair and the PSK
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: Store.nodeName(t.node) + " hasn't reported " + t.iface + " yet", at: Date.now() }; Store.apply(); return; }
      const cur = await getConfig(peer.pubkey, t.node, t.iface);
      const s = cur ? parseFullConf(cur) : null;
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: (t.ip || "").split("/")[0] + "/32",
        dns: s ? s.dns : m.dns, mtu: s ? s.mtu : 1280, awg_params: m.awg_params, server_pubkey: m.public_key,
        psk, endpoint: m.endpoint, allowed: s ? s.allowed : "0.0.0.0/0, ::/0", keepalive: s ? s.keepalive : 25 });
    }
  } catch (e) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
  await mutate({
    key,
    call: () => api.peerRekey({ peer_id: peer.id, user_id: peer.user_id, pubkey: keys.pub, psk, configs }),
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
// Anchored-dropdown positioning: a fixed-position list at the trigger's rect so it escapes a grid/table's
// overflow:hidden (and any stacking context) — the list is PORTALED to <body>. Returns refs + pos; the
// caller renders <Portal> with the list and wires close-on-outside via the returned handlers.
function useAnchoredList(open, setOpen, deps) {
  const wrapRef = useRef(null), listRef = useRef(null);
  const [pos, setPos] = useState(null);
  const place = () => { const el = wrapRef.current; if (!el) return; const r = el.getBoundingClientRect();
    setPos({ left: Math.round(r.left), top: Math.round(r.bottom + 4), width: Math.round(r.width) }); };
  useEffect(() => {
    if (!open) { setPos(null); return; }
    place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target;   // close when the click is outside BOTH the input and the portaled list
      if (!((wrapRef.current && wrapRef.current.contains(t)) || (listRef.current && listRef.current.contains(t)))) setOpen(false); };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [open, ...(deps || [])]);
  return { wrapRef, listRef, pos, popStyle: pos ? ("left:" + pos.left + "px;top:" + pos.top + "px;min-width:" + pos.width + "px") : "" };
}
function UserCombo({ onPick, placeholder }) {
  const [q, setQ] = useState(""); const [open, setOpen] = useState(false);
  const users = Store.recon.users.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const ql = q.toLowerCase();
  const shown = users.filter(u => searchMatch(u.name + " " + (u.tag || ""), ql)).slice(0, 8);
  const { wrapRef, listRef, pos, popStyle } = useAnchoredList(open, setOpen, [q]);
  const pick = uid => { setOpen(false); setQ(""); onPick(uid); };
  return html`<div class="usercombo" ref=${wrapRef}>
    <input class="uc-input" value=${q} placeholder=${placeholder || "Assign to…"} onClick=${() => setOpen(true)}
      onInput=${e => { setQ(e.target.value); setOpen(true); }}
      onKeyDown=${e => { if (e.key === "Enter" && shown.length === 1) { e.preventDefault(); pick(shown[0].id); } else if (e.key === "Escape") setOpen(false); }}/>
    ${open && pos ? html`<${Portal}><div class="uc-list uc-pop" ref=${listRef} style=${popStyle}>${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id}
      onClick=${() => pick(u.id)}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
      : html`<div class="uc-empty">${users.length ? "no match" : "no users yet"}</div>`}</div><//>` : null}
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
  const shown = users.filter(u => searchMatch(u.name + " " + (u.tag || ""), ql)).slice(0, 8);
  const { wrapRef, listRef, pos, popStyle } = useAnchoredList(open, setOpen, [q]);
  const pick = uid => { setOpen(false); setQ(""); onChange(uid); };
  return html`<div class="usercombo" ref=${wrapRef}>
    <input class="uc-input" value=${open ? q : selText}
      placeholder=${placeholder || (allowUnassigned ? "— unassigned —" : "Assign to a user…")}
      onClick=${() => { setOpen(true); setQ(""); }} onInput=${e => { setQ(e.target.value); setOpen(true); }}
      onKeyDown=${e => { if (e.key === "Enter" && open && q && shown.length === 1) { e.preventDefault(); pick(shown[0].id); } else if (e.key === "Escape") setOpen(false); }}/>
    ${open && pos ? html`<${Portal}><div class="uc-list uc-pop" ref=${listRef} style=${popStyle}>
      ${allowUnassigned ? html`<button class="uc-opt" onClick=${() => pick("")}><span class="faint">— unassigned —</span></button>` : null}
      ${shown.length ? shown.map(u => html`<button class="uc-opt" key=${u.id} onClick=${() => pick(u.id)}><span>${u.name}</span>${u.tag ? html`<span class="tagchip">${u.tag}</span>` : null}</button>`)
        : html`<div class="uc-empty">${users.length ? "no match" : "no users yet"}</div>`}
    </div><//>` : null}
  </div>`;
}

// Simple assign for an UNASSIGNED peer: just record the owner (roster metadata). The key / PSK /
// config are kept, so a config already handed out keeps working — no fresh credential, no warning.
function assignPeer(peer, userId) {
  if (!userId) return;
  return mutate({ key: "peer:" + peer.id,
    patch: s => { const p = s.roster.peers[peer.id]; if (p) p.user_id = userId; },
    call: () => api.peerUpdate({ peer_id: peer.id, user_id: userId }),
    onOk: () => revealAssignedPeer(userId, peer.id) });
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
      <div class="fnode-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="fnode-name">${n.name}</span>${al.length ? html`<span class="halert hot"><${Ic} i="warn"/> ${al.length}</span>` : ""}<span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>
      <div class="fnode-stats">
        <div><span class="fl">Traffic</span>${rateCell(nrx, ntx)}</div>
        <div><span class="fl">Online</span><span class="fv"><${OnlineUsersTag} nodeId=${n.id} trigger=${c => html`${c} <span class="faint">user${c === 1 ? "" : "s"}</span>`}/></span></div>
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

// ─────────── Dashboard controls: node selector + time range ───────────
// Two module-level controls drive every Overview widget. The NODE selector filters the fleet the
// dashboard aggregates over (default = ALL, stored as null); unselecting nodes re-renders every widget
// for the remaining set (all-but-one = a single-node view). The RANGE selector chooses the history
// window for the range-driven visuals (doughnuts + flow map); live derives from the /api/state bundle,
// the rest read the per-node RRD on demand. Both live in module state + localStorage so a re-render or
// the 5s poll never clobbers the operator's selection (it's not derived from server data).
const DASH_RANGES = [["live", "Live"], ["hour", "Hour"], ["day", "Day"], ["week", "Week"], ["month", "Month"]];
const dashState = { nodes: null, range: "day" };   // nodes: null = whole fleet, else a Set of node ids
(function () {
  try {
    const raw = JSON.parse(localStorage.getItem("swg-dash") || "{}");
    if (Array.isArray(raw.nodes)) dashState.nodes = new Set(raw.nodes);
    if (DASH_RANGES.some(r => r[0] === raw.range)) dashState.range = raw.range;
  } catch (_) {}
})();
function dashSave() {
  try { localStorage.setItem("swg-dash", JSON.stringify({ nodes: dashState.nodes ? [...dashState.nodes] : null, range: dashState.range })); } catch (_) {}
}
// Effective selected node ids, reconciled against the CURRENT fleet (ids for departed nodes drop out).
// An empty selection collapses back to the whole fleet — the dashboard is never blank.
function dashNodes() {
  const fleet = (Store.fleet || []).map(n => n.id);
  if (!dashState.nodes) return fleet;
  const sel = fleet.filter(id => dashState.nodes.has(id));
  return sel.length ? sel : fleet;
}
function dashNodeOn(id) { return !dashState.nodes || dashState.nodes.has(id); }
function dashAllOn() { const f = (Store.fleet || []).length; return !dashState.nodes || dashNodes().length >= f; }
function dashToggleNode(id) {
  const fleet = (Store.fleet || []).map(n => n.id);
  const sel = new Set(dashState.nodes ? [...dashState.nodes].filter(x => fleet.includes(x)) : fleet);
  if (sel.has(id)) sel.delete(id); else sel.add(id);
  dashState.nodes = (sel.size === 0 || sel.size >= fleet.length) ? null : sel;   // all/none → canonical "fleet"
  dashSave(); bus.emit();
}
function dashSetAll() { dashState.nodes = null; dashSave(); bus.emit(); }
function dashSetRange(r) { if (DASH_RANGES.some(x => x[0] === r)) { dashState.range = r; dashSave(); bus.emit(); } }

// Merge the SELECTED nodes' 15s health-ring series (server-provided, bucket-aligned) into one fleet
// series summed per timestamp — powers the live fleet-throughput hero without a client accumulator, and
// survives a reload (the ring is on the panel). Only rx/tx are summed (counts aren't in the ring yet).
function mergeFleetSeries(selIds) {
  const byT = new Map();
  selIds.forEach(id => {
    const n = (Store.nodes || []).find(x => x.id === id); const h = n && n.health_history;
    if (!h || !h.t) return;
    // client throughput = total − mesh, so relayed traffic isn't counted against the fleet's user throughput
    h.t.forEach((t, i) => { const r = byT.get(t) || { rx: 0, tx: 0 };
      r.rx += Math.max(0, ((h.rx || [])[i] || 0) - ((h.mrx || [])[i] || 0));
      r.tx += Math.max(0, ((h.tx || [])[i] || 0) - ((h.mtx || [])[i] || 0)); byT.set(t, r); });
  });
  const t = [...byT.keys()].sort((a, b) => a - b);
  return { t, rx: t.map(x => byT.get(x).rx), tx: t.map(x => byT.get(x).tx) };
}
// Client-side live accumulator for series the RRD ring doesn't keep yet (online-peer counts). One point
// per poll, per node, pushed in lockstep so selected nodes sum by index. Bounded; empty on reload, fills as
// you watch (Phase B will move online counts into the ring so they survive a reload). Cheap — runs each apply().
const DASH_TICK_MAX = 180;
const dashLive = { t: [], on: {} };
function recordDashTick() {
  const rec = Store.recon; if (!rec) return;
  const now = Math.floor(Date.now() / 1000);
  if (dashLive.t.length && now - dashLive.t[dashLive.t.length - 1] < 3) return;   // dedup optimistic re-applies
  const byNode = {};
  rec.peers.forEach(p => p.targets.forEach(t => { if (t.online) byNode[t.node] = (byNode[t.node] || 0) + 1; }));
  const L = dashLive.t.length;
  (Store.fleet || []).forEach(n => { const a = dashLive.on[n.id] || (dashLive.on[n.id] = new Array(L).fill(0)); while (a.length < L) a.push(0); a.push(byNode[n.id] || 0); });
  dashLive.t.push(now);
  if (dashLive.t.length > DASH_TICK_MAX) { dashLive.t.shift(); Object.values(dashLive.on).forEach(a => a.shift()); }
}
function dashOnlineTrend(selIds) {
  const t = dashLive.t; if (t.length < 2) return null;
  return { t, pts: t.map((_, i) => selIds.reduce((a, id) => a + ((dashLive.on[id] || [])[i] || 0), 0)) };
}

// The dashboard toolbar: a multi-select node filter (themed chips) + a live/day/week/month range toggle.
function DashControls() {
  const fleet = Store.fleet || [];
  const range = dashState.range;
  return html`<div class="dashbar">
    ${fleet.length > 1 ? html`<div class="dash-nodes">
      <span class="dash-lbl">Nodes</span>
      <button class=${"dchip all" + (dashAllOn() ? " on" : "")} onClick=${dashSetAll} title="Show the whole fleet">All</button>
      ${fleet.map(n => {
        const on = dashNodeOn(n.id);
        const down = Store.recon.nodeStatus[n.id] !== "live";
        return html`<button key=${n.id} class=${"dchip" + (on ? " on" : "") + (down ? " down" : "")} style=${"--c:" + Store.nodeColor(n.id)}
          onClick=${() => dashToggleNode(n.id)} title=${(on ? "Hide " : "Show ") + n.name + (down ? " · not reporting" : "")}>
          <span class="dchip-dot"></span>${n.name}</button>`;
      })}
    </div>` : html`<div></div>`}
    <div class="dash-range">
      <span class="dash-lbl">Range</span>
      <div class="dseg">${DASH_RANGES.map(([k, lbl]) => html`<button key=${k} class=${"dseg-opt" + (range === k ? " on" : "")} onClick=${() => dashSetRange(k)}>${lbl}</button>`)}</div>
    </div>
  </div>`;
}

// On-demand history for the range-driven visuals. Fetches per-node RRD (/api/node-history) for the
// SELECTED nodes only when the range is NOT "live" — off the 5s hot path, re-run only when the range or
// the selection changes. Returns { loading, byNode:{id:{t,rx,tx,cpu,…}}, range }. Live → empty (widgets
// read the /api/state bundle instead). One fetch burst per range change; results are held until it changes.
const RANGE_STEP = { hour: 15, day: 300, week: 1800, month: 7200 };   // seconds/bucket → volume = Σ(mean B/s)·step
// One fetch burst per range/selection change, shared by the doughnuts AND the flow map (lifted to Overview so
// they don't each hit the API). Pulls per-node RRD + per-pair mesh means. Live → empty (widgets use the bundle).
function useRangeHistory(range, selIds) {
  const [st, setSt] = useState({ loading: false, byNode: {}, mesh: [], cats: [], range: "live" });
  const key = range + "|" + selIds.slice().sort().join(",");
  useEffect(() => {
    if (range === "live") { setSt({ loading: false, byNode: {}, mesh: [], cats: [], range: "live" }); return; }
    let alive = true; setSt(s => ({ ...s, loading: true }));
    Promise.all([
      Promise.all(selIds.map(id => api.nodeHistory(id, range).then(r => [id, (r && r.data) || null]).catch(() => [id, null]))),
      api.meshHistory(range).then(r => (r && r.data && r.data.pairs) || []).catch(() => []),
      api.categoryHistory(range).then(r => (r && r.data && r.data.cats) || []).catch(() => []),
    ]).then(([rows, mesh, cats]) => { if (!alive) return; const byNode = {}; rows.forEach(([id, d]) => { byNode[id] = d; }); setSt({ loading: false, byNode, mesh, cats, range }); });
    return () => { alive = false; };
  }, [key]);
  return st;
}
// total bytes moved over a range window = Σ(per-bucket mean B/s) × bucket step
function histVolume(d, range) { const step = RANGE_STEP[range] || 1, s = a => (a || []).reduce((x, v) => x + (v || 0), 0) * step; return { rx: s(d && d.rx), tx: s(d && d.tx) }; }

// The 4 concentric-ring doughnuts. All respect the node selector AND the time range: live comes from the
// /api/state bundle; day/week/month read the per-node RRD (client rx/tx = total−mesh, awg-client rx/tx, and
// peer online/total counts) fetched on demand off the hot path. Traffic → volume over the window; counts →
// mean over the window.
function DashDoughnuts({ selIds, range, hist }) {
  const sel = new Set(selIds);
  const fleet = (Store.fleet || []).filter(n => sel.has(n.id));
  const live = range === "live";
  const ranged = !live && !hist.loading && hist.range === range;   // history is loaded for this range
  const STEP = RANGE_STEP[range] || 1;
  const isSys = (nid, ifn) => !!(Store.describe[nid] && Store.describe[nid][ifn] && Store.describe[nid][ifn].system);
  const ifType = (nid, ifn) => { const m = Store.describe[nid] && Store.describe[nid][ifn]; return (m && m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg"; };
  const sPeers = Store.recon.peers.filter(p => p.targets.some(t => sel.has(t.node)));
  const _sum = a => (a || []).reduce((x, v) => x + (v || 0), 0);
  const _mean = a => (a && a.length) ? _sum(a) / a.length : 0;
  // per-node history-derived aggregates (client volume, awg volume, mean peer counts)
  const clientVol = d => { let rx = 0, tx = 0; const R = (d && d.rx) || [], T = (d && d.tx) || [], MR = (d && d.mrx) || [], MT = (d && d.mtx) || [];
    for (let i = 0; i < R.length; i++) { rx += Math.max(0, (R[i] || 0) - (MR[i] || 0)); tx += Math.max(0, (T[i] || 0) - (MT[i] || 0)); } return { rx: rx * STEP, tx: tx * STEP }; };
  const awgVol = d => ({ rx: _sum(d && d.arx) * STEP, tx: _sum(d && d.atx) * STEP });

  // ── traffic by node + by iface type ──
  const nodeTraf = {}, typeTraf = { wg: { rx: 0, tx: 0 }, awg: { rx: 0, tx: 0 } };
  fleet.forEach(n => {
    if (ranged) {
      const d = hist.byNode[n.id]; const cv = clientVol(d), av = awgVol(d);
      nodeTraf[n.id] = cv;
      typeTraf.awg.rx += av.rx; typeTraf.awg.tx += av.tx;
      typeTraf.wg.rx += Math.max(0, cv.rx - av.rx); typeTraf.wg.tx += Math.max(0, cv.tx - av.tx);
    } else {
      let rx = 0, tx = 0; const snap = Store.stats[n.id];
      if (snap) for (const [ifn, blk] of Object.entries(snap.interfaces || {})) {
        if (isSys(n.id, ifn)) continue;
        const ty = ifType(n.id, ifn); let r = 0, t = 0;
        for (const pp of blk.peers || []) { r += pp.rx_speed || 0; t += pp.tx_speed || 0; }
        typeTraf[ty].rx += r; typeTraf[ty].tx += t; rx += r; tx += t;
      }
      nodeTraf[n.id] = { rx, tx };
    }
  });
  const trafFmt = ranged ? fmtBytes : rate;

  // ── peer deployments by node + by iface type (live = current count; ranged = mean over window) ──
  const nodeCnt = {}, typeCnt = { wg: { tot: 0, on: 0 }, awg: { tot: 0, on: 0 } };
  fleet.forEach(n => nodeCnt[n.id] = { tot: 0, on: 0 });
  if (ranged) {
    fleet.forEach(n => { const d = hist.byNode[n.id] || {};
      nodeCnt[n.id] = { tot: Math.round(_mean(d.ptot)), on: Math.round(_mean(d.pon)) };
      const at = Math.round(_mean(d.patot)), ao = Math.round(_mean(d.paon));
      typeCnt.awg.tot += at; typeCnt.awg.on += ao;
      typeCnt.wg.tot += Math.max(0, Math.round(_mean(d.ptot)) - at); typeCnt.wg.on += Math.max(0, Math.round(_mean(d.pon)) - ao);
    });
  } else {
    sPeers.forEach(p => p.targets.forEach(t => {
      if (!sel.has(t.node)) return;
      const ty = (t.type === "awg" || t.type === "wg") ? t.type : ifType(t.node, t.iface);
      nodeCnt[t.node].tot++; if (t.online) nodeCnt[t.node].on++;
      (typeCnt[ty] = typeCnt[ty] || { tot: 0, on: 0 }).tot++; if (t.online) typeCnt[ty].on++;
    }));
  }

  const nodeName = id => Store.nodeName(id), nodeColor = id => Store.nodeColor(id);
  const TYPES = [["awg", "AmneziaWG"], ["wg", "WireGuard"]];
  const segNodes = kind => fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: (nodeTraf[n.id] || {})[kind] || 0, color: nodeColor(n.id) }));
  const segTypes = kind => TYPES.map(([t, nm]) => ({ key: t, name: nm, value: typeTraf[t][kind] || 0, color: ifaceColor(t) }));
  const sum = (o, k) => Object.values(o).reduce((a, v) => a + (v[k] || 0), 0);

  // centre readouts
  const trafCenter = (down, up) => html`<div class="mrc-def"><span class="mrc-k">total</span>
    <span class="mrc-tot dn">↓ ${trafFmt(down)}</span><span class="mrc-tot up" style="font-size:14px">↑ ${trafFmt(up)}</span></div>`;
  const cntCenter = (on, tot) => html`<div class="mrc-def"><span class="mrc-k">online</span>
    <span class="mrc-tot dn">${on}<small style="color:var(--faint)"> / ${tot}</small></span></div>`;

  const totDownN = sum(nodeTraf, "rx"), totUpN = sum(nodeTraf, "tx");
  const totDownT = typeTraf.wg.rx + typeTraf.awg.rx, totUpT = typeTraf.wg.tx + typeTraf.awg.tx;
  const nodeOn = Object.values(nodeCnt).reduce((a, v) => a + v.on, 0), nodeTot = Object.values(nodeCnt).reduce((a, v) => a + v.tot, 0);
  const typeOn = typeCnt.wg.on + typeCnt.awg.on, typeTot = typeCnt.wg.tot + typeCnt.awg.tot;

  const trafLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id),
    right: html`<span style="color:var(--online)">↓${trafFmt((nodeTraf[n.id] || {}).rx || 0)}</span> <span style="color:var(--rate-up)">↑${trafFmt((nodeTraf[n.id] || {}).tx || 0)}</span>` }));
  const trafLegTypes = TYPES.filter(([t]) => typeTraf[t].rx + typeTraf[t].tx > 0).map(([t, nm]) => ({ key: t, name: nm, color: ifaceColor(t),
    right: html`<span style="color:var(--online)">↓${trafFmt(typeTraf[t].rx)}</span> <span style="color:var(--rate-up)">↑${trafFmt(typeTraf[t].tx)}</span>` }));
  const cntLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id), right: nodeCnt[n.id].on + " / " + nodeCnt[n.id].tot }));
  const cntLegTypes = TYPES.filter(([t]) => (typeCnt[t] || { tot: 0 }).tot > 0).map(([t, nm]) => ({ key: t, name: nm, color: ifaceColor(t), right: typeCnt[t].on + " / " + typeCnt[t].tot }));

  const rlabel = DASH_RANGES.find(r => r[0] === range);
  const rname = rlabel ? rlabel[1].toLowerCase() : range;
  const loadingNote = (!live && hist.loading) ? html`<div class="donut-note">loading ${rname} history…</div>` : null;
  const volNote = ranged ? html`<div class="donut-note">volume over the ${rname}</div>` : null;
  const avgNote = ranged ? html`<div class="donut-note">avg over the ${rname}</div>` : null;
  const card = (title, ringsOf, body, note) => html`<div class="donutcard">
    <div class="donutcard-h"><h3>${title}</h3><span class="rings-of">${ringsOf}</span></div>
    <div class=${"donut-body" + ((!live && hist.loading) ? " loading" : "")}>${body}</div>${note || null}</div>`;

  return html`<div class="donutgrid">
    ${card("Traffic by node", ranged ? "vol ↓ / ↑" : "↓ / ↑ B/s",
      html`<${MultiRing} rings=${[{ label: "Download", fmt: trafFmt, segments: segNodes("rx") }, { label: "Upload", fmt: trafFmt, segments: segNodes("tx") }]} center=${trafCenter(totDownN, totUpN)}/>
        <${RingLegend} items=${trafLegNodes}/>`,
      loadingNote || volNote)}

    ${card("Traffic by interface", ranged ? "vol ↓ / ↑" : "↓ / ↑ B/s",
      html`<${MultiRing} rings=${[{ label: "Download", fmt: trafFmt, segments: segTypes("rx") }, { label: "Upload", fmt: trafFmt, segments: segTypes("tx") }]} center=${trafCenter(totDownT, totUpT)}/>
        <${RingLegend} items=${trafLegTypes}/>`,
      loadingNote || volNote)}

    ${card("Peers online by node", "online / total",
      html`<${MultiRing} rings=${[{ label: "Total peers", fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].tot, color: nodeColor(n.id) })) },
                                   { label: "Online", fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].on, color: nodeColor(n.id) })) }]} center=${cntCenter(nodeOn, nodeTot)}/>
        <${RingLegend} items=${cntLegNodes}/>`,
      loadingNote || avgNote)}

    ${card("Peers online by interface", "online / total",
      html`<${MultiRing} rings=${[{ label: "Total peers", fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).tot || 0, color: ifaceColor(t) })) },
                                   { label: "Online", fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).on || 0, color: ifaceColor(t) })) }]} center=${cntCenter(typeOn, typeTot)}/>
        <${RingLegend} items=${cntLegTypes}/>`,
      loadingNote || avgNote)}
  </div>`;
}

// ═══════════════ Signal-flow map (redesign, P1: categorized model + static split/merge render) ═══════════════
// Per selected server, live rx/tx split into endpoint KINDS: clients (direct wg/awg peers), turn (per VK fork),
// internet (direct exit — approximate until the node SNAT counter), mesh (per peer server). Each is a bidirectional
// pair (ingress = rx, egress = tx); 0-value flows dropped. Every flow is drawn source→dest as blue(egress)→green(ingress).
const FLOW_EG = "#2E90FF", FLOW_IN = "#22D07A", FLOW_GLOBE = "#12BECE", FLOW_MESH = "#9B8AFF";   // egress blue · ingress green · internet cyan-teal (distinct from egress blue) · off-fleet mesh violet
function flowGraph(selIds, range, hist) {
  const sel = new Set(selIds);
  const fleet = (Store.fleet || []).filter(n => sel.has(n.id));
  const ranged = range && range !== "live" && hist && !hist.loading && hist.range === range;   // history loaded → show totals
  const STEP = RANGE_STEP[range] || 1;
  const acc = {};
  fleet.forEach(n => acc[n.id] = { cl: { rx: 0, tx: 0 }, turn: {}, mesh: {}, offmesh: { rx: 0, tx: 0, n: new Set() }, inet: null });   // offmesh = traffic to fleet nodes NOT selected (n = which ones) · inet = MEASURED internet {out,in} B/s (node counter), null = fall back to the client-derived estimate
  if (ranged) {
    // ── ranged: TOTAL bytes over the window from the RRD. Client = Σ max(0, rx−mesh)·step (turn can't be split out
    //    of the history → folded into clients; there's no per-fork turn lane over a window); mesh from per-pair means. ──
    fleet.forEach(n => { const d = hist.byNode[n.id]; if (!d) return;
      const R = d.rx || [], T = d.tx || [], MR = d.mrx || [], MT = d.mtx || []; let rx = 0, tx = 0;
      for (let i = 0; i < R.length; i++) { rx += Math.max(0, (R[i] || 0) - (MR[i] || 0)); tx += Math.max(0, (T[i] || 0) - (MT[i] || 0)); }
      acc[n.id].cl.rx = rx * STEP; acc[n.id].cl.tx = tx * STEP;
      const IU = d.inet_up || [], ID = d.inet_down || [];   // MEASURED internet total over the window (Σ per-bucket mean · step), same scale as the client volume
      let iu = 0, id = 0; for (let i = 0; i < IU.length; i++) iu += IU[i] || 0; for (let i = 0; i < ID.length; i++) id += ID[i] || 0;
      if (iu || id) acc[n.id].inet = { out: iu * STEP, in: id * STEP }; });
    // mesh/offmesh values are per-pair MEAN rates (B/s) over the window — convert to total bytes with the FULL window
    // duration (samples·step), NOT one step, so they're on the same scale as the client volume (Σ mean·step above). Using
    // STEP alone under-counted mesh by the sample count (~300 for a day), flooring every mesh edge to a uniform hairline.
    const winSec = Math.max(1, ...fleet.map(n => { const d = hist.byNode[n.id]; return d && d.rx ? d.rx.length : 0; })) * STEP;
    (hist.mesh || []).forEach(p => { const aSel = sel.has(p.a), bSel = sel.has(p.b); if (!aSel && !bSel) return;
      if (aSel && bSel) {
        if (p.ab > 0) (acc[p.a].mesh[p.b] = acc[p.a].mesh[p.b] || { rx: 0, tx: 0 }).tx = p.ab * winSec;
        if (p.ba > 0) (acc[p.b].mesh[p.a] = acc[p.b].mesh[p.a] || { rx: 0, tx: 0 }).tx = p.ba * winSec;
      } else if (aSel) { acc[p.a].offmesh.tx += (p.ab || 0) * winSec; acc[p.a].offmesh.rx += (p.ba || 0) * winSec; acc[p.a].offmesh.n.add(p.b); }   // a→off, off→a
      else { acc[p.b].offmesh.tx += (p.ba || 0) * winSec; acc[p.b].offmesh.rx += (p.ab || 0) * winSec; acc[p.b].offmesh.n.add(p.a); } });
  } else {
    Store.recon.peers.forEach(p => p.targets.forEach(t => {
      if (!acc[t.node]) return; const o = t.observed; if (!o) return;
      const rx = o.rx_speed || 0, tx = o.tx_speed || 0; if (!rx && !tx) return;
      const a = acc[t.node];
      if (t.viaTurn) { const fk = turnFork(t.viaTurn); (a.turn[fk] = a.turn[fk] || { rx: 0, tx: 0 }); a.turn[fk].rx += rx; a.turn[fk].tx += tx; }
      else { a.cl.rx += rx; a.cl.tx += tx; }
    }));
    fleet.forEach(n => { const snap = Store.stats[n.id]; if (!snap) return;
      if (snap.inet) acc[n.id].inet = { out: snap.inet.up || 0, in: snap.inet.down || 0 };   // exact internet egress measured by the node (FORWARD counters) — replaces the client estimate
      for (const [ifn, blk] of Object.entries(snap.interfaces || {})) {
        const meta = (Store.describe[n.id] || {})[ifn] || blk.meta || {};
        const peer = meta.link_node || meta.egress_node;   // a system mesh link identifies its peer via link_node (egress_node is the user-iface forward target, blank here)
        if (!(meta.system && peer)) continue;
        let rx = 0, tx = 0; for (const pp of blk.peers || []) { rx += pp.rx_speed || 0; tx += pp.tx_speed || 0; }
        if (sel.has(peer)) acc[n.id].mesh[peer] = { rx, tx };
        else { acc[n.id].offmesh.rx += rx; acc[n.id].offmesh.tx += tx; acc[n.id].offmesh.n.add(peer); }   // peer not shown → fold into the mesh satellite
      }
    });
  }
  const flows = [], sats = [];
  const satId = (n, k) => n + "|" + k;
  fleet.forEach(n => {
    const a = acc[n.id];
    const turnRx = Object.values(a.turn).reduce((s, v) => s + v.rx, 0), turnTx = Object.values(a.turn).reduce((s, v) => s + v.tx, 0);
    if (a.cl.rx || a.cl.tx) { const s = satId(n.id, "clients"); sats.push({ id: s, node: n.id, kind: "clients", label: "clients", color: "var(--online)", ic: "users" });
      if (a.cl.rx) flows.push({ from: s, to: n.id, bps: a.cl.rx }); if (a.cl.tx) flows.push({ from: n.id, to: s, bps: a.cl.tx }); }
    Object.entries(a.turn).forEach(([fk, v]) => { if (!(v.rx || v.tx)) return;
      const s = satId(n.id, "turn:" + fk); sats.push({ id: s, node: n.id, kind: "turn", fork: fk, label: fk, color: turnColor(fk), ic: "relay" });
      if (v.rx) flows.push({ from: s, to: n.id, bps: v.rx }); if (v.tx) flows.push({ from: n.id, to: s, bps: v.tx }); });
    // internet lane: the node's MEASURED egress (a.inet) when present — exact and multi-hop-correct (an exit's
    // relayed traffic shows here; an entry's forwarded traffic does NOT, it rode the mesh lane). Falls back to the
    // client+turn estimate only for a node that doesn't report a counter yet (older noded / no iptables).
    const inetOut = a.inet ? a.inet.out : a.cl.rx + turnRx, inetIn = a.inet ? a.inet.in : a.cl.tx + turnTx;
    if (inetOut || inetIn) { const s = satId(n.id, "internet"); sats.push({ id: s, node: n.id, kind: "internet", label: "internet", color: FLOW_GLOBE, ic: "globe", measured: !!a.inet });
      if (inetOut) flows.push({ from: n.id, to: s, bps: inetOut }); if (inetIn) flows.push({ from: s, to: n.id, bps: inetIn }); }
    Object.entries(a.mesh).forEach(([peer, v]) => { if (v.tx) flows.push({ from: n.id, to: peer, bps: v.tx }); });
    if (a.offmesh.rx || a.offmesh.tx) {   // aggregate of mesh traffic to fleet nodes NOT in the diagram
      const s = satId(n.id, "mesh"), oc = a.offmesh.n.size; sats.push({ id: s, node: n.id, kind: "mesh", label: "Other " + oc + " node" + (oc === 1 ? "" : "s"), color: FLOW_MESH, ic: "server" });
      if (a.offmesh.tx) flows.push({ from: n.id, to: s, bps: a.offmesh.tx }); if (a.offmesh.rx) flows.push({ from: s, to: n.id, bps: a.offmesh.rx });
    }
  });
  const inTot = {}, outTot = {};
  fleet.forEach(n => { inTot[n.id] = 0; outTot[n.id] = 0; });
  flows.forEach(f => { if (outTot[f.from] != null) outTot[f.from] += f.bps; if (inTot[f.to] != null) inTot[f.to] += f.bps; });
  return { fleet, sats, flows, inTot, outTot, ranged };
}
const FLOW_ANIMS = [   // travelling-current styles for the flow lines (the ORIGINAL beautiful versions); "off" for anyone who wants no motion
  { id: "dots", ic: "dots", label: "Dots" },
  { id: "chevrons", ic: "arrow", label: "Arrows" },
  { id: "pulse", ic: "activity", label: "Pulse" },
  { id: "gradient", ic: "waves", label: "Flow" },
  { id: "off", ic: "off", label: "Off" },
];
function FlowMap2({ selIds, range, hist }) {
  const [hov, setHov] = useState(null);
  const anim = (Store.panelSettings || {}).flow_anim || "dots";   // HOST-WIDE setting — shared by every operator, persists across logins (default = the original dots)
  const setAnim = m => { Store.panelSettings = { ...(Store.panelSettings || {}), flow_anim: m }; bus.emit(); api.panelSettings({ flow_anim: m }).catch(() => {}); };
  const G = flowGraph(selIds, range, hist);
  const { fleet, sats, flows, ranged } = G;
  const fmt = ranged ? fmtBytes : rate;                    // Live → speed (K/s…); a range → total bytes (KB, MB…)
  const N = fleet.length;
  if (!N) return html`<div class="allclear">No nodes selected.</div>`;
  const W = 960, H = 520, cx = W / 2, cy = H / 2;
  const nodeIds = new Set(fleet.map(n => n.id));
  const satTot = {}; sats.forEach(s => { let ib = 0, ob = 0; flows.forEach(f => { if (f.to === s.id) ib += f.bps; if (f.from === s.id) ob += f.bps; }); satTot[s.id] = { ib, ob, tot: ib + ob }; });
  const nameLen = id => (Store.nodeName(id) || id).length;
  const busy = id => (G.inTot[id] || 0) + (G.outTot[id] || 0);
  // ── LINE THICKNESS + ELEMENT SIZE — ONE perception-first model, all in REFERENCE PX (the whole diagram then scales to fit
  //    the card, so line↔node ratios hold at every count). Data spans ~100× but the eye resolves ~24 ratio-based levels, so
  //    each metric maps through a CURVE (sqrt) from a low-tail cutoff → its max onto a fixed px FLOOR→CEILING; values below
  //    the cutoff clamp to the floor ("present, but negligible"). Nodes & satellites fit to THEIR OWN throughput, then grow
  //    if needed so their perimeter can SEAT the incident lines (Σ widths). ──
  const LOQ = 0.15;   // fraction of the low tail clamped to the floor ("present, but negligible")
  const curve = Math.sqrt;   // perceptual compression: spreads mid-range off the floor while a lone giant can't crush it
  const mapper = (vals, floor, ceil, loq) => { const s = vals.filter(v => v > 0).sort((a, b) => a - b);   // value distribution → [floor,ceil] px via the curve
    if (!s.length) return () => floor;
    const lo = s[Math.min(s.length - 1, Math.round((loq == null ? LOQ : loq) * (s.length - 1)))], hi = s[s.length - 1];
    if (hi <= lo) return () => ceil;                                     // all values ~equal (incl. a lone element) → full size, not floor
    const cLo = curve(Math.max(lo, 1)), cHi = curve(Math.max(hi, 1));
    return v => v <= lo ? floor : floor + Math.min(1, (curve(v) - cLo) / Math.max(1e-9, cHi - cLo)) * (ceil - floor); };
  const wMap = mapper(flows.map(f => f.bps), 2, 25, LOQ);                // line width px: floor 2 · ceiling 25 (per direction)
  const wOf = bps => wMap(bps);                                          // line width, reference px
  const NODE_FLOOR = 12, SAT_FLOOR = 11, ICON_R = 1.3;                   // ICON_R = sat icon size ÷ radius (circle & icon grow together)
  // size a node by the traffic it VISIBLY shows — Σ of its incident line widths — NOT raw bps. Line widths are
  // sqrt-compressed and capped at 25px, so two nodes whose lines all read "max" look equally busy; sizing by raw
  // bps would still blow one up 10× for having more underlying Mbps behind those same-looking lines.
  const visBusy = id => flows.reduce((a, f) => (f.from === id || f.to === id) ? a + wOf(f.bps) : a, 0);
  const fontMap = mapper(fleet.map(n => visBusy(n.id)), NODE_FLOOR, 21, 0);    // nodes: few & all meaningful → no tail clamp
  const satMap = mapper(sats.map(s => (satTot[s.id] || {}).tot || 0), SAT_FLOOR, 22, 0);
  const seatNeed = id => flows.reduce((a, f) => (f.from === id || f.to === id) ? a + wOf(f.bps) + 4 : a, 0);   // Σ incident line widths + gaps (ref px)
  // the thickest SINGLE connection's pair (both lanes + gap) — a bidirectional link lands as a tight parallel pair on one
  // rim point, so the node's cross-dimension must span it even if the total perimeter (seatNeed) looks roomy.
  const pairThick = id => { const bo = {}; flows.forEach(f => { const o = f.from === id ? f.to : f.to === id ? f.from : null; if (o == null) return; bo[o] = (bo[o] || 0) + wOf(f.bps); }); let mx = 0; for (const k in bo) if (bo[k] > mx) mx = bo[k]; return mx ? mx + 2 : 0; };
  // a satellite's lines all enter from ONE side (toward its parent), so its DIAMETER must span the line stack → r ≥ Σ/2
  const satR = id => Math.max(satMap((satTot[id] || {}).tot || 0), seatNeed(id) / 2);
  // node height is 2·hh = 2·fs+6; the pill's 8px rounded CORNERS eat into the straight edge a pair can seat on, so
  // require the straight run (2fs+6 − 2·8) ≥ pairThick (which already includes the inter-lane gap) → fs ≥ pairThick/2+5.
  const nodeFont = id => Math.max(fontMap(visBusy(id)), (seatNeed(id) / 4 - 5) / (0.31 * nameLen(id) + 1.85), pairThick(id) / 2 + 5);    // size by VISIBLE traffic · pill perimeter 4·(hw+hh) ≥ Σ lines · straight edge ≥ thickest pair
  const nR = id => (0.31 * nameLen(id) + 0.85) * nodeFont(id) + 2;        // ≈ pill half-width
  const nmeta = id => { if (!nodeIds.has(id)) { const r = satR(id); return { hw: r, hh: r }; }   // sat = circle; node = pill (est.)
    const fs = nodeFont(id), L = nameLen(id); return { hw: (0.31 * L + 0.85) * fs + 2, hh: fs + 3 }; };
  const rimDist = (id, ux, uy) => { const m = nmeta(id); return 1 / Math.max(Math.abs(ux) / m.hw, Math.abs(uy) / m.hh, 1e-6); };   // ray→border in a given direction
  // "connected" = has a node↔node mesh line to ANOTHER shown node. A node with NO in-diagram peer is an "island" (single-node
  // view, or e.g. two entries that only mesh to exits): it fans its satellites internet-UP / rest-DOWN instead of outward.
  const connected = id => flows.some(f => (f.from === id && nodeIds.has(f.to)) || (f.to === id && nodeIds.has(f.from)));
  // ── ADAPTIVE LAYOUT. CONNECTED nodes → landscape oval (few sit close, many spread only as needed; sats face outward).
  //    ISLANDS (no in-diagram peer) fan their sats up/down, so a polygon would collide AND waste space — instead pack them into
  //    a GRID sized to the frame aspect, so a wall of islands stays readable. The frame scales the whole thing to fit either way. ──
  const maxNR = Math.max(24, ...fleet.map(n => nR(n.id)));
  const allIsle = N >= 2 && fleet.every(n => !connected(n.id)), maxSatR = Math.max(12, ...sats.map(s => satR(s.id)));
  const sep = 2 * maxNR + 50, Rc = N <= 1 ? 0 : sep / (2 * Math.sin(Math.PI / N));   // ring circumradius (connected layout)
  const start = N === 2 ? 0 : N === 4 ? -Math.PI / 4 : -Math.PI / 2, Rx = Rc * 1.34, Ry = Rc * 0.70;   // 2→left/right · 4→square corners · else polygon from top
  const ranked = fleet.slice().sort((p, q) => (busy(q.id) - busy(p.id)) || (p.id < q.id ? -1 : 1));   // biggest traffic first
  const spos = {};
  if (allIsle) {
    // grid of independent island "stars": cell = down-fan width × (internet-up + node + fan-down) height; columns chosen to
    // roughly match the frame's landscape aspect (≈√(1.3·N)) so a wall of islands doesn't shrink more than necessary.
    const REACH = 108, cellW = 2 * (REACH * 0.85 + maxSatR) + 0.6 * maxNR + 34, cellH = 2 * REACH + 2 * maxSatR + 64;
    const rows = Math.ceil(N / 3), cols = Math.ceil(N / rows);   // ≤3 per row, balanced: 1–3 → one row · 4 → 2×2 · 5 → 3+2 · 6 → 3+3
    ranked.forEach((n, i) => { const rI = Math.floor(i / cols), cN = Math.min(cols, N - rI * cols), cI = i - rI * cols;
      spos[n.id] = { x: cx + (cI - (cN - 1) / 2) * cellW, y: cy + (rI - (rows - 1) / 2) * cellH }; });
  } else {
    // busiest → the TOP(-left) slot; then each next-busiest → the free slot FURTHEST from the previously placed one, so busy
    // nodes spread far apart instead of clustering.
    const ringSlots = fleet.map((n, i) => { const a = N === 1 ? 0 : start + i * 2 * Math.PI / N; return { x: cx + Rx * Math.cos(a), y: cy + Ry * Math.sin(a) }; });
    let startIdx = 0; ringSlots.forEach((p, i) => { const s = ringSlots[startIdx]; if (p.y < s.y - 0.5 || (Math.abs(p.y - s.y) <= 0.5 && p.x < s.x)) startIdx = i; });
    const used = new Array(ringSlots.length).fill(false);
    let prev = startIdx; used[startIdx] = true; spos[ranked[0].id] = ringSlots[startIdx];
    for (let k = 1; k < ranked.length; k++) { let best = -1, bd = -1;
      ringSlots.forEach((p, i) => { if (used[i]) return; const d = (p.x - ringSlots[prev].x) ** 2 + (p.y - ringSlots[prev].y) ** 2; if (d > bd) { bd = d; best = i; } });
      used[best] = true; spos[ranked[k].id] = ringSlots[best]; prev = best; }
  }
  // satellite reach (node-border → sat line length) capped at HALF the shortest node↔node line, so sat lines never
  // dominate the mesh lines. (N=1 has no node↔node line → use the default.)
  let minNN = Infinity;
  flows.forEach(f => { if (nodeIds.has(f.from) && nodeIds.has(f.to)) { const A = spos[f.from], B = spos[f.to]; minNN = Math.min(minNN, Math.hypot(B.x - A.x, B.y - A.y) - nR(f.from) - nR(f.to)); } });
  const satReach = isFinite(minNN) ? Math.max(90, Math.min(120, minNN * 0.6)) : 108;   // shrinks with crowding (mesh room) but gently — 6+ nodes stay reasonable
  // satellites fan outward from each server, then relax so DIFFERENT nodes' satellites don't overlap each other or a node
  const satpos = {};
  fleet.forEach(n => { const mine = sats.filter(s => s.node === n.id), P = spos[n.id];
    const place = (s, a) => { const D = rimDist(n.id, Math.cos(a), Math.sin(a)) + satR(s.id) + satReach; satpos[s.id] = { x: P.x + D * Math.cos(a), y: P.y + D * Math.sin(a) }; };   // gap measured from the node's EDGE in THIS direction → consistent line length all around
    // satellites go ABOVE / BELOW the node — NEVER on its LEFT or RIGHT — so a wide (long-name) badge never stretches a side
    // satellite's line. Cone limited to ±CONE of vertical.
    // satellites face AWAY from the mesh centre (outward) but never sit directly LEFT/RIGHT of the (possibly long) badge:
    // top/bottom arcs whose centre is TILTED toward the node's outward horizontal side, kept clear of pure horizontal.
    const HB = 0.42;                                                          // forbidden horizontal half-band (~24°)
    const hfrac = Rx > 0 ? Math.max(-1, Math.min(1, (P.x - cx) / Rx)) : 0;    // −1 left … +1 right
    const vfrac = Ry > 0 ? (P.y - cy) / Ry : 0;                               // −1 top … +1 bottom
    const arc = (grp, sideSign) => {   // sideSign −1 = top arc, +1 = bottom arc
      const sp = Math.min(Math.PI - 2 * HB - 0.15, 0.5 + grp.length * 0.42);
      const tilt = hfrac * Math.max(0, Math.PI / 2 - HB - sp / 2);            // lean toward outward side, only as far as room allows
      const center = sideSign < 0 ? -Math.PI / 2 + tilt : Math.PI / 2 - tilt;
      grp.forEach((s, i) => place(s, center + (grp.length === 1 ? 0 : (i / (grp.length - 1) - 0.5) * sp)));
    };
    if (allIsle || N === 1) {                             // ISLAND STAR (single node, or a grid of all-islands): internet STRAIGHT UP over the
      const up = mine.filter(s => s.kind === "internet"), down = mine.filter(s => s.kind !== "internet");   // centre, everything else fanned evenly straight DOWN. In a MIXED selection an island instead fans OUTWARD (below) so its
      up.forEach(s => place(s, -Math.PI / 2));            // fan doesn't point at neighbouring nodes / cross their mesh lines.
      const sp = Math.min(Math.PI - 2 * HB - 0.15, 0.5 + down.length * 0.42);
      down.forEach((s, i) => place(s, Math.PI / 2 + (down.length === 1 ? 0 : (i / (down.length - 1) - 0.5) * sp)));
    }
    else if (vfrac < -0.32) arc(mine, -1);                // clearly-upper node → top arc
    else if (vfrac > 0.32) arc(mine, 1);                  // clearly-lower node → bottom arc
    else { const h = Math.ceil(mine.length / 2); arc(mine.slice(0, h), -1); arc(mine.slice(h), 1); }   // side/central → split top+bottom
  });
  for (let it = 0; it < 70; it++) {                        // anti-collision relaxation (deterministic → stable across renders)
    sats.forEach(s => { const P = satpos[s.id]; if (!P) return; const r = satR(s.id); let dx = 0, dy = 0;
      sats.forEach(o => { if (o.id === s.id) return; const Q = satpos[o.id]; if (!Q) return; const ex = P.x - Q.x, ey = P.y - Q.y, d = Math.hypot(ex, ey) || 1, md = r + satR(o.id) + 10; if (d < md) { const k = (md - d) / d * 0.5; dx += ex * k; dy += ey * k; } });
      fleet.forEach(m => { if (m.id === s.node) return; const Q = spos[m.id], ex = P.x - Q.x, ey = P.y - Q.y, d = Math.hypot(ex, ey) || 1, md = r + nR(m.id) + 12; if (d < md) { const k = (md - d) / d * 0.5; dx += ex * k; dy += ey * k; } });
      P.x += dx; P.y += dy; });
    sats.forEach(s => { const P = satpos[s.id]; if (!P) return; const A = spos[s.node], r = satR(s.id);   // leash to parent → stays connected, roughly outward
      const ex = P.x - A.x, ey = P.y - A.y, d = Math.hypot(ex, ey) || 1, base = rimDist(s.node, ex / d, ey / d) + r, minL = base + Math.max(30, satReach * 0.7), maxL = base + satReach;
      if (d < minL) { P.x = A.x + ex / d * minL; P.y = A.y + ey / d * minL; } else if (d > maxL) { P.x = A.x + ex / d * maxL; P.y = A.y + ey / d * maxL; } });
  }
  const epPos = id => spos[id] || satpos[id];
  const epR = id => spos[id] ? nR(id) : satR(id);
  const epName = id => { if (spos[id]) return Store.nodeName(id); const s = sats.find(x => x.id === id) || {}; return s.kind === "turn" ? s.fork : s.label || s.kind || id; };
  // ── viewBox — fit the frame to the content, then centre it in ONE fixed section (fixed aspect + min frame) so the card
  //    never resizes and sparse diagrams render at a consistent scale instead of being blown up to fill the width. All sizes
  //    (line widths, node/sat dims) are already in reference px, so this single scale carries the whole diagram. ──
  let vx0 = 1e9, vy0 = 1e9, vx1 = -1e9, vy1 = -1e9;
  fleet.forEach(n => { const P = spos[n.id], m = nmeta(n.id); vx0 = Math.min(vx0, P.x - m.hw); vx1 = Math.max(vx1, P.x + m.hw); vy0 = Math.min(vy0, P.y - m.hh); vy1 = Math.max(vy1, P.y + m.hh); });
  sats.forEach(s => { const P = satpos[s.id]; if (!P) return; const r = satR(s.id); vx0 = Math.min(vx0, P.x - r); vx1 = Math.max(vx1, P.x + r); vy0 = Math.min(vy0, P.y - r); vy1 = Math.max(vy1, P.y + r); });
  const PAD = 22; vx0 -= PAD; vy0 -= PAD; vx1 += PAD; vy1 += PAD;
  const FRAME_AR = 1.8, FRAME_W = 1060;
  const cw = vx1 - vx0, ch = vy1 - vy0, ccx = (vx0 + vx1) / 2, ccy = (vy0 + vy1) / 2;
  const vbW = Math.max(FRAME_W, cw, ch * FRAME_AR), vbH = vbW / FRAME_AR;
  vx0 = ccx - vbW / 2; vy0 = ccy - vbH / 2;
  // ── Geometry: each flow is a STROKED curve (never a filled ribbon → it can't hourglass/twist). On EVERY endpoint
  //    each touching flow gets its OWN attach ANGLE around the rim — ordered by bearing to the far end, then spread
  //    so thick lines don't overlap — i.e. a fan. Different connections therefore enter at different rim points and
  //    NEVER cross where they meet a node, regardless of node size or flow width. The two directions of a pair land
  //    on adjacent slots → a tight parallel pair. Both ends tuck just INSIDE the opaque badge (butt cap, always
  //    hidden), which clips the line at its TRUE border. ──
  // ONE fan slot per CONNECTION (keyed by the other endpoint) — both its directions share it. PACKED BY ARC-LENGTH on the
  // element's perimeter (rect for a pill, ~square for a sat): each connection reserves a span = its total pixel width (+gap),
  // and overlaps are pushed apart ALONG the perimeter (wrap-around). Because we pack in real pixels, no two lines ever
  // overlap where they meet the element — one line occupies X→Y, the next is moved to Y→Z. The packed position is then
  // converted back to an attach ANGLE (direction to that perimeter point) for the existing centre-endpoint geometry.
  const slot = {};   // `${epId}|${otherId}` → attach angle (radians)
  [...fleet.map(n => n.id), ...sats.map(s => s.id)].forEach(id => {
    const P = epPos(id); if (!P) return; const m = nmeta(id), hw = m.hw, hh = m.hh, Peri = 4 * (hw + hh), byOther = {};
    flows.forEach(f => { if (f.from !== id && f.to !== id) return; const o = f.from === id ? f.to : f.from; if (!epPos(o)) return; (byOther[o] = byOther[o] || { o, w: 0 }).w += wOf(f.bps); });
    const arcOf = (ux, uy) => { const t = 1 / Math.max(Math.abs(ux) / hw, Math.abs(uy) / hh, 1e-9), qx = ux * t, qy = uy * t, onV = Math.abs(qx) > hw - 0.5;
      return !onV && qy < 0 ? qx + hw : onV && qx > 0 ? 2 * hw + (qy + hh) : !onV && qy > 0 ? 2 * hw + 2 * hh + (hw - qx) : 4 * hw + 2 * hh + (hh - qy); };
    const items = Object.values(byOther).map(c => { const O = epPos(c.o), d = Math.hypot(O.x - P.x, O.y - P.y) || 1; return { key: c.o, s: arcOf((O.x - P.x) / d, (O.y - P.y) / d), half: c.w / 2 + 4 }; });
    if (!items.length) return;
    items.sort((a, b) => a.s - b.s); items.forEach(it => it.c = it.s);
    for (let iter = 0; iter < 40; iter++) for (let k = 0; k < items.length; k++) { const a = items[k], b = items[(k + 1) % items.length];
      let gap = b.c - a.c; if (k === items.length - 1) gap += Peri; const need = a.half + b.half;
      if (gap < need) { const push = (need - gap) / 2; a.c -= push; b.c += push; } }
    items.forEach(it => { let s = ((it.c % Peri) + Peri) % Peri, x, y;
      if (s <= 2 * hw) { x = -hw + s; y = -hh; } else if (s -= 2 * hw, s <= 2 * hh) { x = hw; y = -hh + s; } else if (s -= 2 * hh, s <= 2 * hw) { x = hw - s; y = hh; } else { s -= 2 * hw; x = -hw; y = hh - s; }
      slot[id + "|" + it.key] = Math.atan2(y, x); });
  });
  const pkey = f => [f.from, f.to].slice().sort().join("~");
  const pairFlows = {}; flows.forEach((f, i) => { const k = pkey(f); (pairFlows[k] = pairFlows[k] || []).push(i); });
  const ribbons = flows.map((f, idx) => {
    const sa = slot[f.from + "|" + f.to], sb = slot[f.to + "|" + f.from]; if (sa == null || sb == null) return null;
    const Pa = epPos(f.from), Pb = epPos(f.to);
    const [lo, hi] = [f.from, f.to].slice().sort(), Lo = epPos(lo), Hi = epPos(hi);
    const cdx = Hi.x - Lo.x, cdy = Hi.y - Lo.y, cd = Math.hypot(cdx, cdy) || 1, cpx = -cdy / cd, cpy = cdx / cd;   // SHARED perp (sorted lo→hi) → siblings stay parallel
    // offset each direction by ½·(gap + the SIBLING's width) so the pair's outer-edge midline is centred on the connection
    // axis (through both endpoints' centres) even when ingress/egress widths differ — pair enters a badge dead-centre.
    const w = wOf(f.bps), sibs = pairFlows[pkey(f)], sibIdx = sibs.length > 1 ? sibs.find(i => i !== idx) : null;
    // pair offset centres the two directions on the axis; CLAMP it to the smaller endpoint's rim so a tiny satellite can't be
    // pushed off the line (endpoint outside its circle → occlusion can't clip it → looks disconnected).
    const GAP = 2, baseOff = sibIdx != null ? (GAP + wOf(flows[sibIdx].bps)) / 2 : 0;
    const off = sibIdx != null ? (f.from === lo ? 1 : -1) * Math.min(baseOff, 0.62 * Math.min(epR(f.from), epR(f.to))) : 0;
    const aux = Math.cos(sa), auy = Math.sin(sa), bux = Math.cos(sb), buy = Math.sin(sb);
    const ra = rimDist(f.from, aux, auy), rb = rimDist(f.to, bux, buy);
    const dist = Math.hypot(Pb.x - Pa.x, Pb.y - Pa.y), isMesh = spos[f.from] && spos[f.to];
    const ext = isMesh ? Math.min(52, dist * 0.2) : Math.min(16, dist * 0.11);
    // endpoint sits on the slot RAY, DEEP inside the badge (0.28·rim) — the initial bezier direction is still purely radial
    // (endpoint & control share the same perpendicular `off`, so they differ only along the ray → no bend toward centre), but
    // the deeper tuck guarantees the badge occludes the whole junction even when a wide pair-offset nudges an end toward an
    // edge/rounded corner. The `off` clamp keeps a tiny satellite's offset end inside its circle. Control = further out (fan).
    const ax = Pa.x + aux * ra * 0.28 + cpx * off, ay = Pa.y + auy * ra * 0.28 + cpy * off, bx = Pb.x + bux * rb * 0.28 + cpx * off, by = Pb.y + buy * rb * 0.28 + cpy * off;
    const c1x = Pa.x + aux * (ra + ext) + cpx * off, c1y = Pa.y + auy * (ra + ext) + cpy * off, c2x = Pb.x + bux * (rb + ext) + cpx * off, c2y = Pb.y + buy * (rb + ext) + cpy * off;
    const path = `M ${ax.toFixed(1)} ${ay.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${bx.toFixed(1)} ${by.toFixed(1)}`;
    // hover hit-area: widen it, but ONLY on the OUTER side (away from the parallel sibling) — shift the transparent
    // stroke outward by HITEXT/2 so its inner edge stays on the line and the extra reach is all on the free side.
    const HITEXT = 16, hsh = (off === 0 ? 0 : off > 0 ? 1 : -1) * HITEXT / 2, hx = cpx * hsh, hy = cpy * hsh, hitW = Math.max(w, 3) + HITEXT;
    const hitPath = `M ${(ax + hx).toFixed(1)} ${(ay + hy).toFixed(1)} C ${(c1x + hx).toFixed(1)} ${(c1y + hy).toFixed(1)} ${(c2x + hx).toFixed(1)} ${(c2y + hy).toFixed(1)} ${(bx + hx).toFixed(1)} ${(by + hy).toFixed(1)}`;
    return { idx, f, path, hitPath, hitW, w, sx: ax, sy: ay, ex: bx, ey: by, mid: { x: (c1x + c2x) / 2, y: (c1y + c2y) / 2 } };
  }).filter(Boolean);
  const gid = "fg" + (FlowMap2._n = (FlowMap2._n || 0) + 1);
  const satC = id => (sats.find(s => s.id === id) || {}).color;
  const flowLit = idx => hov && (hov.fi === idx || (hov.id != null && (flows[idx].from === hov.id || flows[idx].to === hov.id)));
  const badgeLit = id => !hov || hov.id === id || (hov.fi != null && (flows[hov.fi].from === id || flows[hov.fi].to === id));
  // when hovering a node/sat, its CONNECTED nodes stay dimmed but show their NAME at full colour (so you can read where it links)
  const relOf = id => hov && hov.id != null && hov.id !== id && flows.some(f => (f.from === hov.id && f.to === id) || (f.to === hov.id && f.from === id));
  // ── Bubble placement: sit near the element but inside its biggest ANGULAR GAP, so it never covers a lit line.
  //    `occ` = directions of the lines to dodge; the box then grows AWAY from the element (translate by quadrant). ──
  const bubbleSpot = (P, occ, r) => {
    const M = 15;
    if (!occ.length) return { x: P.x, y: P.y - r - M, tx: "-50%", ty: "-100%" };
    const s = occ.slice().sort((a, b) => a - b); let best = -1, dir = -Math.PI / 2;
    for (let i = 0; i < s.length; i++) { const a = s[i], b = i + 1 < s.length ? s[i + 1] : s[0] + 2 * Math.PI, g = b - a; if (g > best) { best = g; dir = a + g / 2; } }
    const R = r + M, ax = Math.cos(dir), ay = Math.sin(dir);
    return { x: P.x + ax * R, y: P.y + ay * R, tx: ax > 0.35 ? "0" : ax < -0.35 ? "-100%" : "-50%", ty: ay > 0.35 ? "0" : ay < -0.35 ? "-100%" : "-50%" };
  };
  let hv = null, spot = null;
  if (hov && hov.id != null) {
    const P = epPos(hov.id); if (P) {
      const occ = flows.filter(f => f.from === hov.id || f.to === hov.id).map(f => { const O = epPos(f.from === hov.id ? f.to : f.from); return O ? Math.atan2(O.y - P.y, O.x - P.x) : null; }).filter(a => a != null);
      spot = bubbleSpot(P, occ, epR(hov.id));
      if (spos[hov.id]) hv = { type: "ep", name: Store.nodeName(hov.id), ib: G.inTot[hov.id], ob: G.outTot[hov.id], sub: "server", col: Store.nodeColor(hov.id) };
      else { const sm = sats.find(x => x.id === hov.id); if (sm) { const t = satTot[hov.id] || {}; hv = { type: "ep", name: sm.kind === "turn" ? sm.fork : sm.label || sm.kind, ib: t.ib, ob: t.ob, sub: sm.kind === "internet" ? (sm.measured ? "internet · measured" : "internet · estimated") : sm.kind === "turn" ? "turn-proxy" : sm.kind === "mesh" ? "fleet nodes not shown" : "clients", col: sm.color }; } }
    }
  } else if (hov && hov.fi != null) {
    const f = flows[hov.fi], r = ribbons.find(x => x.idx === hov.fi);
    if (r) { const ang = Math.atan2(r.ey - r.sy, r.ex - r.sx); spot = bubbleSpot(r.mid, [ang, ang + Math.PI], 4);
      hv = { type: "flow", a: epName(f.from), b: epName(f.to), v: f.bps, ca: spos[f.from] ? Store.nodeColor(f.from) : satC(f.from), cb: spos[f.to] ? Store.nodeColor(f.to) : satC(f.to) }; }
  }
  // viewBox (vx0/vy0/vbW/vbH) was computed above. PX/PY map reference-px coords → % of the frame.
  const PX = x => (x - vx0) / vbW * 100, PY = y => (y - vy0) / vbH * 100;
  // Badges are HTML over the SVG. The SVG scales its user units to the container width (scale = containerW/vbW ≠ 1). To keep
  // the badges the SAME size the GEOMETRY assumes (else line ends poke past small badges — worse with few nodes / big scale),
  // size them in container units: 1 user unit = (100/vbW) cqw. So a font of `f` user units → `f·U` cqw.
  const U = 100 / vbW;
  const bubStyle = "left:" + (spot ? PX(spot.x) : 0) + "%;top:" + (spot ? PY(spot.y) : 0) + "%;transform:translate(" + (spot ? spot.tx : "-50%") + "," + (spot ? spot.ty : "-100%") + ")";
  return html`<div class="flowcard">
    <div class="flowmap2" style=${"aspect-ratio:" + vbW.toFixed(0) + "/" + vbH.toFixed(0)} onMouseLeave=${() => setHov(null)}>
      <svg viewBox=${vx0.toFixed(1) + " " + vy0.toFixed(1) + " " + vbW.toFixed(1) + " " + vbH.toFixed(1)} preserveAspectRatio="xMidYMid meet">
        <defs>${ribbons.map(r => { if (anim === "gradient") {   // "Flow" mode: the LINE itself is a repeating egress→ingress gradient sliding source→dest (no overlay)
            const dx = r.ex - r.sx, dy = r.ey - r.sy, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len, P = 64, lit = !hov || flowLit(r.idx);
            return html`<linearGradient key=${gid + r.idx} id=${gid + "-" + r.idx} gradientUnits="userSpaceOnUse" spreadMethod="repeat" x1=${r.sx} y1=${r.sy} x2=${(r.sx + ux * P).toFixed(1)} y2=${(r.sy + uy * P).toFixed(1)}>
              <stop offset="0" stop-color=${FLOW_EG}/><stop offset="0.5" stop-color=${FLOW_IN}/><stop offset="1" stop-color=${FLOW_EG}/>
              ${lit ? html`<animateTransform attributeName="gradientTransform" type="translate" from="0 0" to=${(ux * P).toFixed(1) + " " + (uy * P).toFixed(1)} dur=${Math.max(0.6, (2.8 - r.w * 0.12) / 1.5).toFixed(2) + "s"} repeatCount="indefinite"/>` : null}
            </linearGradient>`;
          }
          return html`<linearGradient key=${gid + r.idx} id=${gid + "-" + r.idx} gradientUnits="userSpaceOnUse" x1=${r.sx} y1=${r.sy} x2=${r.ex} y2=${r.ey}>
            <stop offset="0" stop-color=${FLOW_EG}/><stop offset="0.2" stop-color=${FLOW_EG}/><stop offset="0.8" stop-color=${FLOW_IN}/><stop offset="1" stop-color=${FLOW_IN}/>
          </linearGradient>`; })}</defs>
        ${ribbons.map(r => html`<path key=${"r" + r.idx} id=${gid + "-p" + r.idx} d=${r.path} fill="none" stroke=${"url(#" + gid + "-" + r.idx + ")"} stroke-width=${r.w.toFixed(1)} stroke-linecap="butt"
          class=${"fm2-flow" + (hov && !flowLit(r.idx) ? " dim" : flowLit(r.idx) ? " lit" : "")} style="pointer-events:none"/>`)}
        ${anim === "dots" ? ribbons.filter(r => !hov || flowLit(r.idx)).map(r => html`<path key=${"a" + r.idx} d=${r.path} fill="none" stroke="var(--flowdot)" stroke-width=${Math.max(1.3, Math.min(r.w * 0.5, 4.5)).toFixed(1)} stroke-linecap="round"
          class=${"fm2-flowdot" + (hov && !flowLit(r.idx) ? " dim" : "")} style=${"animation-duration:" + Math.max(0.8, 2.6 - r.w * 0.11).toFixed(2) + "s;pointer-events:none"}/>`) : null}
        ${anim === "pulse" ? ribbons.filter(r => !hov || flowLit(r.idx)).map(r => { const L = Math.hypot(r.ex - r.sx, r.ey - r.sy) || 1, nc = Math.max(1, Math.round(L / 240)), hl = Math.max(9, Math.min(L * 0.16, 24)),   // a short round-capped glow SEGMENT gliding along the path (animateMotion → cheap, like the arrows) instead of animating the whole line's dash
          w = Math.max(2.4, r.w * 0.7), dotDur = Math.max(0.8, 2.6 - r.w * 0.11), dur = L * dotDur / 66;   // speed tied to thickness (like dots/arrows), length-independent (3× faster)
          return html`<g key=${"pl" + r.idx} class=${"fm2-pulse" + (hov && !flowLit(r.idx) ? " dim" : "")} style="pointer-events:none">
            ${Array.from({ length: nc }, (_, k) => html`<path key=${k} d=${"M" + (-hl).toFixed(1) + ",0 L" + hl.toFixed(1) + ",0"} fill="none" stroke="var(--flowdot)" stroke-width=${w.toFixed(1)} stroke-linecap="round">
              <animateMotion dur=${dur.toFixed(2) + "s"} begin=${(-k * dur / nc).toFixed(2) + "s"} repeatCount="indefinite" rotate="auto"><mpath href=${"#" + gid + "-p" + r.idx}/></animateMotion></path>`)}
          </g>`; }) : null}
        ${anim === "chevrons" ? ribbons.filter(r => !hov || flowLit(r.idx)).map(r => { const L = Math.hypot(r.ex - r.sx, r.ey - r.sy) || 1, nc = Math.max(2, Math.round(L / 70)), sz = Math.max(3, Math.min(r.w * 0.55, 6.5)),
          dotDur = Math.max(0.8, 2.6 - r.w * 0.11), dur = L * dotDur / 45;   // travel SPEED (px/s) tied to thickness (like dots), length-independent; /45 = 3× the dot speed
          return html`<g key=${"cv" + r.idx} class=${"fm2-chev" + (hov && !flowLit(r.idx) ? " dim" : "")} style="pointer-events:none">
            ${Array.from({ length: nc }, (_, k) => html`<path key=${k} d=${"M" + (-sz).toFixed(1) + "," + (-sz).toFixed(1) + " L0,0 L" + (-sz).toFixed(1) + "," + sz.toFixed(1)} fill="none" stroke="var(--flowdot)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <animateMotion dur=${dur.toFixed(2) + "s"} begin=${(-k * dur / nc).toFixed(2) + "s"} repeatCount="indefinite" rotate="auto"><mpath href=${"#" + gid + "-p" + r.idx}/></animateMotion></path>`)}
          </g>`; }) : null}
        ${ribbons.map(r => html`<path key=${"h" + r.idx} d=${r.hitPath} fill="none" stroke="transparent" stroke-width=${r.hitW.toFixed(0)} stroke-linecap="butt"
          style="pointer-events:stroke;cursor:pointer" onMouseEnter=${() => setHov({ fi: r.idx })} onMouseLeave=${() => setHov(null)}/>`)}
      </svg>
      ${fleet.map(n => { const P = spos[n.id];
        return html`<button key=${n.id} class=${"fm2-nb" + (badgeLit(n.id) ? "" : relOf(n.id) ? " reldim" : " dim")} style=${"left:" + PX(P.x) + "%;top:" + PY(P.y) + "%;--c:" + Store.nodeColor(n.id) + ";font-size:" + (nodeFont(n.id) * U).toFixed(3) + "cqw"}
          onMouseEnter=${() => setHov({ id: n.id })} onMouseLeave=${() => setHov(null)}>${n.name}</button>`; })}
      ${sats.map(s => { const P = satpos[s.id]; if (!P) return null; const rr = satR(s.id), isz = ICON_R * rr;   // icon grows PROPORTIONALLY with the circle (fixed ratio), so a bigger sat = bigger icon
        return html`<button key=${s.id} class=${"fm2-sb sb-" + s.kind + (badgeLit(s.id) ? "" : relOf(s.id) ? " reldim" : " dim")} style=${"left:" + PX(P.x) + "%;top:" + PY(P.y) + "%;--c:" + s.color + ";--isz:" + (isz * U).toFixed(3) + "cqw;width:" + (rr * 2 * U).toFixed(3) + "cqw;height:" + (rr * 2 * U).toFixed(3) + "cqw"}
          onMouseEnter=${() => setHov({ id: s.id })} onMouseLeave=${() => setHov(null)}><${Ic} i=${s.ic}/></button>`; })}
      ${hv && hv.type === "flow" ? html`<div class="fm2-bub" style=${bubStyle}>
        <div class="fm2-bub-h" style="flex-direction:row;gap:6px;align-items:center;flex-wrap:wrap"><span style=${"color:" + hv.ca}>${hv.a}</span><span style="color:var(--faint)">→</span><span style=${"color:" + hv.cb}>${hv.b}</span></div>
        <div class="fm2-bub-r"><span style="color:var(--dim)">${ranged ? "volume" : "throughput"}</span><b>${fmt(hv.v)}</b></div>
      </div>` : hv ? html`<div class="fm2-bub" style=${bubStyle}>
        <div class="fm2-bub-h" style=${"color:" + hv.col}>${hv.name}<span class="fm2-bub-k">${hv.sub}</span></div>
        <div class="fm2-bub-r"><span style=${"color:" + FLOW_IN}>↓ ingress</span><b>${fmt(hv.ib || 0)}</b></div>
        <div class="fm2-bub-r"><span style=${"color:" + FLOW_EG}>↑ egress</span><b>${fmt(hv.ob || 0)}</b></div>
      </div>` : null}
    </div>
    <div class="fm2-anim" title="Flow animation (saved for everyone)">${FLOW_ANIMS.map(a => html`<button key=${a.id} class=${"fm2-anim-b" + (anim === a.id ? " on" : "")} title=${a.label} onClick=${() => setAnim(a.id)}><${Ic} i=${a.ic}/></button>`)}</div>
    <div class="flow-foot"><span class="flow-sum"><i class="fm2-key" style=${"background:" + FLOW_EG}></i>egress <i class="fm2-key" style=${"background:" + FLOW_IN}></i>ingress</span><span class="grow"></span>
      <span class="donut-note">${(!ranged && range && range !== "live") ? "loading history…" : ranged ? "total over the window · width ∝ volume · hover" : "live · width ∝ rate · hover"}</span></div>
  </div>`;
}

// ═════════════════════════ SCREEN: OVERVIEW ═════════════════════════
function Overview() {
  useStore();
  const peers = Store.recon.peers, users = Store.recon.users, fleet = Store.fleet, ns = Store.recon.nodeStatus;
  // Every widget aggregates over the SELECTED node set (default = whole fleet). A peer is "in scope" if
  // it has at least one target on a selected node; its counts/traffic come only from selected nodes.
  const selIds = dashNodes(), sel = new Set(selIds);
  const rangeHist = useRangeHistory(dashState.range, selIds);   // one fetch, shared by the doughnuts + flow map
  const fleetSel = fleet.filter(n => sel.has(n.id));
  const scoped = selIds.length < fleet.length;   // a subset is active → section labels say "selected"
  const isSys = (nid, ifn) => !!(Store.describe[nid] && Store.describe[nid][ifn] && Store.describe[nid][ifn].system);
  const onSel = p => p.targets.some(t => sel.has(t.node));   // peer touches a selected node
  const sPeers = peers.filter(onSel);
  // client (non-mesh) throughput summed over selected nodes — excludes system link ifaces so relayed
  // traffic isn't double-counted against a node's own client throughput.
  const nodeRate = id => { const snap = Store.stats[id]; let r = 0, t = 0;
    if (snap) for (const [ifn, blk] of Object.entries(snap.interfaces || {})) { if (isSys(id, ifn)) continue; for (const pp of blk.peers || []) { r += pp.rx_speed || 0; t += pp.tx_speed || 0; } }
    return [r, t]; };

  const online = sPeers.filter(p => p.targets.some(t => sel.has(t.node) && t.online)).length;
  // Peer-status tile buckets: online (active handshake) · ready (deployed + reporting, idle) · attention
  // (everything else — partial / pending / creating / rotating / dangling / unknown). Always sum to total.
  const ready = sPeers.filter(p => p.status === "ready").length;
  const attention = sPeers.length - online - ready;
  const sUsers = users.filter(u => sPeers.some(p => p.user_id === u.id));
  const liveNodes = fleetSel.filter(n => ns[n.id] === "live").length;
  const ifaceCount = selIds.reduce((a, id) => a + Object.keys(Store.describe[id] || {}).filter(ifn => !isSys(id, ifn)).length, 0);
  const nodesAlerting = fleetSel.filter(n => healthAlerts(((Store.nodes || []).find(x => x.id === n.id) || {}).health).length).length;
  let rx = 0, tx = 0;
  fleetSel.forEach(n => { const [r, t] = nodeRate(n.id); rx += r; tx += t; });

  const probs = sPeers.filter(p => ["dangling", "partial", "pending", "unknown"].includes(p.status))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const unassigned = Store.unassignedPeers().filter(onSel);
  const orphans = Store.recon.orphans.filter(o => sel.has(o.node));
  const why = { dangling: "missing on every server", partial: "missing on some servers", pending: "just created, not seen yet", unknown: "server stale — can't confirm" };

  const recent = recentActivity();

  // ranked nodes — by traffic over the SELECTED RANGE (live rate, or windowed client volume = Σ(rx−mesh)·step,
  // matching the doughnuts), or by peer count when the fleet is idle (selected nodes only)
  const dRanged = dashState.range !== "live" && !rangeHist.loading && rangeHist.range === dashState.range;
  const dStep = RANGE_STEP[dashState.range] || 1;
  const nodeVol = id => { const d = rangeHist.byNode[id]; if (!d) return { rx: 0, tx: 0 };
    let rx = 0, tx = 0; const R = d.rx || [], T = d.tx || [], MR = d.mrx || [], MT = d.mtx || [];
    for (let i = 0; i < R.length; i++) { rx += Math.max(0, (R[i] || 0) - (MR[i] || 0)); tx += Math.max(0, (T[i] || 0) - (MT[i] || 0)); }
    return { rx: rx * dStep, tx: tx * dStep }; };
  const nodeTraffic = fleetSel.map(n => {
    const [lr, lt] = nodeRate(n.id); const v = dRanged ? nodeVol(n.id) : { rx: lr, tx: lt };
    return { id: n.id, name: n.name, color: Store.nodeColor(n.id), rx: v.rx, tx: v.tx, peers: sPeers.filter(p => p.targets.some(d => d.node === n.id)).length };
  });
  const anyTraffic = nodeTraffic.some(x => x.rx + x.tx > 0);
  const rankRows = nodeTraffic.slice()
    .sort((a, b) => anyTraffic ? (b.rx + b.tx) - (a.rx + a.tx) : b.peers - a.peers)
    .slice(0, 6)
    .map(x => ({ label: x.name, value: anyTraffic ? x.rx + x.tx : x.peers,
      sub: anyTraffic ? (dRanged ? xferCell(x.rx, x.tx) : rateCell(x.rx, x.tx)) : x.peers + " peer" + (x.peers === 1 ? "" : "s"),
      color: x.color || "var(--brand)", href: "#/node/" + encodeURIComponent(x.id) }));

  // ── live core-row series (all from the bundle; no server hit on the hot path) ──
  const fleetSeries = mergeFleetSeries(selIds);          // fleet rx/tx over the 15s ring (survives reload)
  const onlineTrend = dashOnlineTrend(selIds);           // client-accumulated online-peer count trend
  // top talkers — peers by live rx+tx across the selected nodes
  const talkers = sPeers.map(p => {
    let r = 0, t = 0; p.targets.forEach(tg => { if (!sel.has(tg.node)) return; const o = tg.observed; if (o) { r += o.rx_speed || 0; t += o.tx_speed || 0; } });
    return { p, rx: r, tx: t };
  }).filter(x => x.rx + x.tx > 0).sort((a, b) => (b.rx + b.tx) - (a.rx + a.tx)).slice(0, 6);
  const talkerRows = talkers.map(x => ({ label: x.p.name || x.p.title || "peer", value: x.rx + x.tx, sub: rateCell(x.rx, x.tx),
    color: Store.nodeColor((x.p.targets.find(t => sel.has(t.node)) || {}).node) || "var(--brand)", href: "#/peer/" + encodeURIComponent(x.p.id) }));
  // turn-proxy load across the selected nodes (hidden when the fleet runs none)
  const turnRows = [];
  if (turnEnabled()) fleetSel.forEach(n => { const snap = Store.stats[n.id]; ((snap && snap.turn_proxies) || []).forEach(tp => turnRows.push({ node: n.id, tp })); });
  // traffic by DESTINATION CATEGORY — each category's FULL total. Categories NEST (youtube ⊂ google, yandex ⊂ ru_net),
  // so a byte counts in EVERY category it matches: they OVERLAP on purpose and do NOT sum to the total (the distinct
  // total is the CLIENT traffic below). Live = per-node `cats` rates (panel-derived from the node's nft counters);
  // ranged = per-(node,cat) volume from /api/category-history.
  const catAgg = {};
  const _cadd = (cat, up, dn) => { const a = catAgg[cat] = catAgg[cat] || { up: 0, dn: 0 }; a.up += up || 0; a.dn += dn || 0; };
  if (dRanged) (rangeHist.cats || []).forEach(e => { if (sel.has(e.node)) _cadd(e.cat, e.up, e.dn); });
  else { const cById = Object.fromEntries((Store.nodes || []).map(n => [n.id, n.cats || {}]));   // Store.fleet is a slim {id,name,color} projection — the live `cats` field lives on the full Store.nodes objects
    fleetSel.forEach(n => { for (const [cat, v] of Object.entries(cById[n.id] || {})) _cadd(cat, v.up, v.dn); }); }
  const catRows = Object.entries(catAgg).filter(([c, v]) => c !== "uncat" && v.up + v.dn > 0)
    .sort((a, b) => (b[1].dn + b[1].up) - (a[1].dn + a[1].up)).slice(0, 10)
    .map(([cat, v]) => ({ label: catLabelOf(cat), value: v.dn + v.up, sub: dRanged ? xferCell(v.dn, v.up) : rateCell(v.dn, v.up), color: catColor(cat) }));
  const _un = catAgg.uncat;   // the first-match "matched no set" bucket — always pinned last (a catch-all, not ranked), even if it's the largest
  if (_un && _un.up + _un.dn > 0) catRows.push({ label: catLabelOf("uncat"), value: _un.dn + _un.up, sub: dRanged ? xferCell(_un.dn, _un.up) : rateCell(_un.dn, _un.up), color: catColor("uncat") });
  const totClientDn = nodeTraffic.reduce((a, x) => a + (x.rx || 0), 0);   // distinct total (client download) — categories are a subset/overlap of this

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <${DashControls}/>
    <div class="statgrid">
      <a class="stat accent clk" href="#/connections"><span class="stat-ic"><${Ic} i="activity"/></span><div class="stat-c"><div class="k">Online now</div><div class="v">${online}<small> / ${sPeers.length}</small></div><div class="sub">live connections →</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="users"/></span><div class="stat-c"><div class="k">Users</div><div class="v">${sUsers.length}</div><div class="sub">${sPeers.length} peers${scoped ? " here" : " total"}</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="device"/></span><div class="stat-c"><div class="k">Peer status</div><div class="v" style="font-size:19px"><span style="color:var(--online)">${online}</span> · <span style="color:var(--ready)">${ready}</span> · <span style=${"color:" + (attention ? "var(--dangling)" : "var(--faint)")}>${attention}</span></div><div class="sub">online · ready · attention</div></div></a>
      <a class="stat clk" href="#/nodes"><span class="stat-ic"><${Ic} i="server"/></span><div class="stat-c"><div class="k">Nodes</div><div class="v">${liveNodes}<small> / ${fleetSel.length}</small></div><div class="sub">${ifaceCount} interface${ifaceCount === 1 ? "" : "s"}${nodesAlerting ? html` · <span style="color:var(--dangling)">${nodesAlerting} alerting</span>` : ""}</div></div></a>
      <div class="stat"><span class="stat-ic"><${Ic} i="gauge"/></span><div class="stat-c"><div class="k">Throughput</div><div class="v" style=${"font-size:19px;color:" + (rx + tx > 0 ? "var(--online)" : "var(--faint)")}>↓ ${rate(dlul(rx, tx)[0])}</div><div class="sub"><span style=${"color:" + (rx + tx > 0 ? "var(--ready)" : "var(--faint)")}>↑ ${rate(dlul(rx, tx)[1])}</span>${scoped ? " selected" : " aggregate"}</div></div></div>
    </div>

    ${fleetSel.length ? html`<div class="trends">
      <div class="trendcard wide">
        <div class="donutcard-h"><h3>Fleet throughput</h3><span class="rings-of">${scoped ? "selected" : "fleet"} · last hour</span></div>
        ${(fleetSeries.t || []).length > 1
          ? html`<${ThroughputChart} rx=${fleetSeries.rx} tx=${fleetSeries.tx} times=${fleetSeries.t} range="hour" cap=${RANGE_CAP.hour} h=${70}/>`
          : html`<div class="harea-empty">gathering — no history yet</div>`}
      </div>
      <div class="trendcard">
        <div class="donutcard-h"><h3>Online peers</h3><span class="rings-of">live trend</span><span class="grow"></span><span class="trend-now">${online}</span></div>
        ${onlineTrend
          ? html`<${TrendArea} points=${onlineTrend.pts} times=${onlineTrend.t} color="var(--online)" h=${70} cap=${0} fmt=${v => v + " online"} range="live"/>`
          : html`<div class="harea-empty">gathering — fills as it polls</div>`}
      </div>
    </div>` : null}

    <div class="section-title"><h2>Fleet</h2><span class="count">${scoped ? fleetSel.length + " of " + fleet.length : fleet.length} server${fleet.length === 1 ? "" : "s"}</span><span class="grow"></span></div>
    ${fleetSel.length ? html`<div class="fleet2">${fleetSel.map(n => html`<${FleetNodeCard} key=${n.id} n=${n}/>`)}</div>`
      : html`<div class="allclear">No servers configured in fleet.json.</div>`}

    ${fleetSel.length ? html`<${Fragment}>
      <div class="section-title"><h2>Distribution</h2><span class="count">${scoped ? "selected nodes" : "whole fleet"} · ${DASH_RANGES.find(r => r[0] === dashState.range)[1].toLowerCase()}</span><span class="grow"></span></div>
      <${DashDoughnuts} selIds=${selIds} range=${dashState.range} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length ? html`<${Fragment}>
      <div class="section-title"><h2>Traffic flow</h2><span class="count">signal flow · by category</span><span class="grow"></span></div>
      <${FlowMap2} selIds=${selIds} range=${dashState.range} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length > 1 ? html`<${Fragment}>
      <div class="section-title"><h2>${anyTraffic ? "Top nodes by traffic" : "Top nodes by peers"}</h2><span class="count">${anyTraffic ? (DASH_RANGES.find(r => r[0] === dashState.range) || ["", "live"])[1].toLowerCase() : ""}</span><span class="grow"></span></div>
      <div class="rankcard"><${RankBars} rows=${rankRows}/></div>
    <//>` : null}

    ${catRows.length ? html`<${Fragment}>
      <div class="section-title"><h2>Traffic by destination</h2><span class="count">${dRanged ? (DASH_RANGES.find(r => r[0] === dashState.range) || ["", "live"])[1].toLowerCase() : "live"} · categories overlap${totClientDn ? " · of " + (dRanged ? fmtBytes(totClientDn) : rate(totClientDn)) + " total ↓" : ""}</span><span class="grow"></span></div>
      <div class="rankcard"><${RankBars} rows=${catRows}/></div>
    <//>` : null}

    ${talkerRows.length ? html`<${Fragment}>
      <div class="section-title"><h2>Top talkers</h2><span class="count">by live throughput</span><span class="grow"></span></div>
      <div class="rankcard"><${RankBars} rows=${talkerRows}/></div>
    <//>` : null}

    ${turnRows.length ? html`<${Fragment}>
      <div class="section-title"><h2>Turn-proxy load</h2><span class="count">${turnRows.length} prox${turnRows.length === 1 ? "y" : "ies"}</span><span class="grow"></span></div>
      <div class="turnload">${turnRows.map(({ node, tp }) => {
        const fork = turnFork(tp.service), down = nodeStale(node) || turnDown(tp);
        return html`<a class="turnload-row" key=${node + tp.service} href=${"#/node/" + encodeURIComponent(node)}>
          <span class=${"tg tg-turn tf-" + fork + (down ? " muted" : "")}>${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>
          <span class="tl-node" style=${"color:" + Store.nodeColor(node)}>${Store.nodeName(node)}</span>
          <span class="grow"></span>
          <span class=${"tl-stat " + (down ? "down" : "up")}>${down ? "down" : "up"}</span>
          ${tp.version ? html`<span class="tl-ver">${tp.version}</span>` : null}</a>`;
      })}</div>
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
// health-check roll-up badge (issues). The data refreshes itself on the 5s poll — no manual re-check
// button (removed as redundant). The `activity` pulse icon it used is now free for a future feature.
function HealthDot({ issues }) {
  if (!issues || !issues.length) return null;
  const n = issues.length;
  const trigger = html`<span class="badge b-issue ic"><${Ic} i="warn"/>${n} issue${n > 1 ? "s" : ""}</span>`;
  return html`<${Popover} cls="onlinetag bare healthpop" trigger=${trigger}>
    <div class="onpop-h">${n} issue${n > 1 ? "s" : ""} on this node</div>
    ${issues.map(it => html`<div class="onrow hrow"><span class="on-name">${it}</span></div>`)}
  </${Popover}>`;
}
// Quick node→node nav: a colour-coded chip per server (saved order), the current one highlighted.
function NodeBadges({ active }) {
  const ns = Store.nodes || [];
  if (ns.length < 2) return null;
  return html`<div class="node-badges">${ns.map(n => {
    const col = Store.nodeColor(n.id);
    const down = Store.recon.nodeStatus[n.id] !== "live";   // not reporting → dim it (greyed, desaturated)
    const cls = "nbadge" + (down ? " off" : "");
    return n.id === active
      ? html`<span class=${cls + " on"} style=${"--c:" + col} title=${n.name + (down ? " · not reporting" : "")}>${n.name}</span>`
      : html`<a class=${cls} style=${"--c:" + col} href=${"#/node/" + encodeURIComponent(n.id)} title=${(down ? "Down — " : "Go to ") + n.name}>${n.name}</a>`;
  })}</div>`;
}
function NodeDetail({ node: rawName }) {
  const name = decodeURIComponent(rawName);   // `name` is the node id (the connector); display uses dname
  const node = Store.node(name);
  const nrec = Store.nodes.find(x => x.id === name) || {};   // full record carries health
  const meta = Store.describe[name] || null;       // interface meta from the consolidated state
  const metaErr = node && !meta;

  // if a node we were viewing gets removed (force-remove, or a flagged node that signed off), bounce
  // to the Nodes list instead of stranding the operator on a dead detail page. A node that was never
  // here (stale link) just shows the message below.
  const seenRef = useRef(false);
  useEffect(() => { if (node) seenRef.current = true; else if (seenRef.current) go("#/nodes"); }, [node]);

  // split the node's interfaces: USER interfaces (operator-created) vs SYSTEM mesh links (node↔node connections).
  // System ifaces are EXCLUDED from the user list by BOTH the reported `system` flag AND the reserved name
  // prefix — a mesh iface mid-delete loses its override flag but keeps its swg_ name, so it must never leak
  // onto the User-interfaces screen as a card.
  const meshPfx = (nrec.mesh_prefix || (Store.panelSettings || {}).reserved?.iface_prefix || "swg_");
  const isSysName = k => k.startsWith(meshPfx) || k.startsWith("swg_");
  const isSysIface = k => (meta[k] && meta[k].system) || isSysName(k);
  const userKeys = meta ? Object.keys(meta).filter(k => !isSysIface(k)) : [];
  const sysKeys = meta ? Object.keys(meta).filter(k => isSysIface(k)) : [];
  // drag-to-reorder the (user) interface cards (saved order overlays the node's reported set)
  const ifaceIds = orderById(userKeys, nrec.iface_order, x => x);
  const ifReorder = useReorder(ifaceIds, ids => mutate({
    patch: s => { const nn = (s.nodes || []).find(x => x.id === name); if (nn) nn.iface_order = ids; },
    call: () => api.saveOrder({ kind: "iface", node: name, order: ids }),
  }));

  if (!node) return html`<div class="screen"><div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>${name}</b></div>
    <div class="empty"><b>Unknown server</b>this server isn't in the fleet.</div></div>`;
  const dname = node.name || name;

  const live = Store.recon.nodeStatus[name] === "live";
  const blocked = !live || inProc(nrec.proc_status);   // node down or mid convert/re-install → only recovery actions (rotate key, delete) stay enabled (a timed-out/failed tag doesn't block)
  const down = !live && !inProc(nrec.proc_status);      // genuinely not reporting (not just mid-convert) → offer one-click Recover in place of rotate-token
  const dhUpdating = nrec.updating || (nrec.local && (hostUpdating || inProc(Store.hostProc) || inProc(nrec.proc_status)));  // the dh-ver pill already shows "updating…" — so suppress a duplicate "updating" proc-tag next to the title
  const snap = Store.stats[name];
  // turn-proxies present (installed, a pending install, or onboarding) → show the Turn-proxies block;
  // none → hide that block and surface a "Setup turn-proxy" button in the Interfaces header instead.
  const hasTurns = !!((snap && (snap.turn_proxies || []).length) || Object.keys(nrec.turn_pending || {}).length || (nrec.turn_onboarding || []).length);
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === name));
  const onl = here.filter(p => p.targets.some(t => t.node === name && t.online)).length;
  let nrx = 0, ntx = 0; if (snap) for (const blk of Object.values(snap.interfaces || {})) for (const pp of blk.peers || []) { nrx += pp.rx_speed || 0; ntx += pp.tx_speed || 0; }
  let syncTxt = "no snapshot yet";
  if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); syncTxt = live ? "synced " + seen(a) + " ago" : "stale for " + seen(a); }

  return html`<div class="screen">
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>${dname}</b><${NodeBadges} active=${name}/></div>
    <div class="detail-head">
      <div class="title">${(nrec.outdated || (nrec.local && Store.panelOutdated)) && !nrec.updating ? html`<span class="upd-dot" title="Update available"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}<h1>${dname}</h1>${nrec.kind ? html`<span class=${"tport " + nrec.kind}>${nrec.kind === "docker" ? "docker" : "bare-metal"}</span>` : null}${nrec.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> uninstalled</span>` : live ? html`<span class="reporting">reporting</span>` : nrec.status === "dangling" ? html`<span class="nstat enroll"><${Ic} i="clock"/> awaiting enroll</span>` : html`<span class="nstat stale"><${Ic} i="info"/> stale</span>`}${nrec.proc_status && !isUpdateState(nrec.proc_status) ? procTag(nrec.proc_status, () => dismissNodeProc(nrec.id), nrec.proc_err, !live && nrec.status === "dangling") : null}<${HealthDot} issues=${nrec.issues}/></div>
      <div class="grow"></div>
      <div class="dh-ver">
        ${nrec.version && !nrec.uninstalled ? html`<span class=${"nm-ver" + (nrec.ahead ? " out" : "")} title=${nrec.ahead ? "Node is running a newer version than the panel — update the panel to catch up" : ""}>v${nrec.version}</span>` : null}
        ${nrec.uninstalled ? null : dhUpdating ? html`<span class="livepill upd-busy">updating… <svg class="updspin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>`
          : (nrec.proc_status && isUpdateState(nrec.proc_status)) ? procTag(nrec.proc_status, () => dismissNodeProc(nrec.id), nrec.proc_err)
          : (nrec.local && Store.panelOutdated) ? html`<button class="livepill updpill" disabled=${blocked} onClick=${() => updateHost()} title="Update this master (panel + co-located node) to the latest release">update to <b>${Store.latestRemote || "?"}</b></button>`
          : nrec.outdated ? html`<button class="livepill updpill" disabled=${blocked} onClick=${() => updateNode(nrec)} title=${blocked ? "Unavailable while the node is down / converting" : "Update this node"}>update node to <b>${nrec.latest || "?"}</b></button>`
          : (nrec.local ? (Store.updFlash && Date.now() < Store.updFlash) : (Store.nodeUpdFlash && Store.nodeUpdFlash.id === nrec.id && Date.now() < Store.nodeUpdFlash.until))
          ? html`<span class="livepill upd-uptodate" title=${nrec.local ? "This master is on the latest version" : "This node is on the latest version"}><${Ic} i="check"/> up to date</span>`
          : html`<button class="iconbtn" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Check for updates"} onClick=${e => checkForUpdate(e, nrec.local ? undefined : nrec.id)}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></button>`}
        <span class="dh-sep"></span>
        <button class="iconbtn" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Node settings"} onClick=${() => openNodeEdit(nrec)}><${Ic} i="gear"/></button>
        ${down ? null : html`<button class="iconbtn" title="Rotate token (re-enroll / re-install)" onClick=${() => openNodeRotate(nrec)}><${Ic} i="key"/></button>`}
        <button class="iconbtn danger" title=${nrec.removing ? "Force remove node" : "Remove node"} onClick=${() => openNodeRemove(nrec)}><${Ic} i="trash"/></button>
        ${down ? html`<button class="iconbtn recover" title="Recover this node — rotate its token and get a fresh paste-on-the-server install command (the node keeps its peers)" onClick=${() => openNodeRecover(nrec)}><${Ic} i="key"/> recover</button>` : null}
      </div>
    </div>

    ${!snap ? html`<div class="node-nodata"><${Ic} i="activity"/><p>This node isn't sending any data right now</p></div>` : html`<div class="noderibbon">
      <div class="nr-tags">
        ${orderById(userKeys, nrec.iface_order, x => x).map(ifn => {
          const type = (meta[ifn].awg_params && Object.keys(meta[ifn].awg_params).length) ? "awg" : "wg";
          return html`<a class=${"tg tg-" + type + ((nodeStale(name) || ifaceNotUp(name, ifn)) ? " muted" : "")} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}>${ifn}</a>`;
        })}
        ${turnEnabled() ? orderById((snap && snap.turn_proxies) || [], nrec.turn_order, tp => tp.service).map(tp => html`<span class=${"tg tg-turn tf-" + turnFork(tp.service) + ((nodeStale(name) || turnDown(tp)) ? " muted" : "")}>${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`) : null}
      </div>
      <span class="grow"></span>
      <div class="nr-sync"><span class="when">${syncTxt}</span>${nrec.health && nrec.health.uptime != null ? html`<span class="when">up ${dur(nrec.health.uptime)}</span>` : null}</div>
    </div>

    ${nrec.health ? html`<${Panel} icon="activity" title="Health" tone="online"
      actions=${html`<${Fragment}>${nrec.removing ? html`<span class="nstat removing"><${Ic} i="trash"/> flagged for removal</span><button class="btn btn-mini" style="margin-left:9px" title="Cancel removal — keep this node" onClick=${() => unflagNode(nrec)}>Cancel</button>` : null}</>`}>
      <${HealthAlerts} health=${nrec.health}/>
      ${nrec.health_history
        ? html`<${RangedHistory} node=${name} kind="cpu" live=${nrec.health_history} liveFine=${nrec.health_live} h=${52} head=${html`<${HealthMeters} health=${nrec.health}/>`}/>`
        : html`<${HealthMeters} health=${nrec.health}/>`}
    <//>` : null}

    ${nrec.health_history ? html`<${Panel} icon="gauge" title="Throughput">
      <${RangedHistory} node=${name} kind="throughput" live=${nrec.health_history} liveFine=${nrec.health_live} h=${72}/>
    <//>` : null}

    ${(nrec.mesh_peers || []).length ? html`<${Panel} icon="network" title="Node connections" tone="pending" count=${(nrec.mesh_peers || []).length}
        actions=${html`<${MeshStat} nodeId=${name} mode="in"/>`}>
      <div class="ifgrid">${[...(nrec.mesh_peers || [])].sort((a, b) => Store.nodeName(a.peer).localeCompare(Store.nodeName(b.peer))).map(mp => {
        const peer = mp.peer;
        const ifn = mp.iface;
        const m = (ifn && meta) ? meta[ifn] : null;   // reported stats for the link's CURRENT iface (absent mid-rebuild)
        const col = Store.nodeColor(peer);
        const reprov = !!mp.reprovisioning || (!!ifn && !m);   // staged create, or iface not reported yet → re-provisioning
        // link health → one glowing dot: green up (recent handshake) · amber connecting (never handshook)
        // · red down (handshook then went stale, or the node itself is dark). reprov takes over the card.
        const lk = reprov ? "reprov" : nodeStale(name) ? "down" : (!m || m.handshake_age == null ? "connecting" : (m.handshake_age < 180 ? "up" : "down"));
        const lkTitle = { up: "Link up", connecting: "Connecting…", down: "Link down" }[lk];
        const muted = lk === "down" || reprov;
        const carried = reprov ? [] : userKeys.filter(k => meta[k].egress_mode === "forward" && meta[k].egress_node === peer);   // user iface NAMES forwarded whole (cascade) out through THIS link
        const smartCarried = reprov ? [] : userKeys.filter(k => meta[k].egress_mode === "smart" && (meta[k].routing || []).some(r => r.action === "exit" && r.node === peer));   // ifaces SMART-routing some destinations out via THIS link
        return html`<div key=${peer} class=${"ifcard tp" + (reprov ? "" : " clickable") + (muted ? " down" : "")} onClick=${reprov || !ifn ? null : () => openConnectionEdit(name, ifn)}>
          <div class="ifcard-top"><span class="iftype turn" style=${"--tfc:" + col}><${Ic} i="server"/></span><span class="ifname">${Store.nodeName(peer)}</span><span class="grow"></span>${smartCarried.length ? html`<span class="egb egb-smart" title=${"Smart cascade: routes selected destinations out via " + Store.nodeName(peer)}><${Ic} i="cascade"/>smart cascade</span>` : carried.length ? html`<span class="egb egb-cascade" title=${"Cascade: relays " + carried.length + " interface" + (carried.length === 1 ? "" : "s") + " out via " + Store.nodeName(peer)}><${Ic} i="cascade"/>cascade</span>` : null}${reprov ? html`<span class="tg tg-busy" title="Rebuilding this node's mesh link — it reconnects in a few seconds"><${Ic} i="clock"/>re-provisioning</span>` : html`<span class=${"lkdot " + lk} title=${lkTitle}></span>`}</div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">Endpoint</span><span class="r addr">${(m && m.peer_endpoint) || "—"}</span></div>
            <div class="ifrow"><span class="l">Tunnel</span><span class="r addr">${(m && m.subnet) || "—"}</span></div>
            ${carried.length ? html`<div class="ifrow"><span class="l">Carrying</span><span class="r"><span class="carry-tags">${carried.map(k => html`<span class=${"tg tg-" + ((meta[k].awg_params && Object.keys(meta[k].awg_params).length) ? "awg" : "wg")}>${k}</span>`)}</span></span></div>` : null}
          </div></div>`;
      })}</div>
    <//>` : null}

    <${Panel} icon="globe" title="User interfaces" tone="ready" count=${userKeys.length}
        actions=${html`<${Fragment}>${turnEnabled() && nrec.turn_manage && !hasTurns ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Set up the node's first turn-proxy"} onClick=${() => openSetupTurn(name)}><${Ic} i="plus"/> Setup turn-proxy</button>` : null}<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openOnboardIface(name)}><${Ic} i="plus"/> Create new interface</button><//>`}>
      ${(() => {
        // server-side pending (no data yet): the simple "waiting…" chip. creating → wg/awg tag; onboarding → "load".
        const pcard = (ifn, label, type) => html`<div class="ifcard pending" key=${label + ":" + ifn}>
          <div class="ifcard-top"><span class=${"iftype " + (type || "turn")}>${type || "load"}</span><span class="ifname">${ifn}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[ifn]}/><${StatusTag} cls="tg-busy" icon="clock" label=${label} title="Setting it up on the node"/></div>
          <div class="ifcard-rows"><div class="ifrow"><span class="l faint">the node is ${label === "creating" ? "creating" : "adding"} it…</span><button class="btn btn-mini warn" title="Drop this pending request" onClick=${() => mutate({ key: "ifcancel:" + name + "|" + ifn, call: () => api.ifaceCancel({ node: name, iface: ifn }) })}>Cancel</button></div><${RowError} k=${"ifcancel:" + name + "|" + ifn}/></div></div>`;
        // client-optimistic create: the FULL card with the values just entered, dimmed + "creating" + × in the
        // header — identical layout to the turn-proxy optimistic card. Shown until the node reports the iface.
        const optIfCard = (ifn, e) => html`<div class="ifcard down" key=${"new:" + ifn}>
          <div class="ifcard-top"><span class=${"iftype " + (e.type || "turn")}>${e.type || "load"}</span><span class="ifname">${ifn}</span><span class="grow"></span><${CmdErr} err=${(nrec.cmd_errors || {})[ifn]}/><${StatusTag} cls="tg-busy" icon="clock" label=${e.type ? "creating" : "onboarding"} title="Setting it up on the node"/><button class="xbtn" title="Cancel this request" onClick=${() => { delete Store.ifaceNew[name + "|" + ifn]; mutate({ key: "ifcancel:" + name + "|" + ifn, call: () => api.ifaceCancel({ node: name, iface: ifn }) }); }}><${Ic} i="x"/></button></div>
          <div class="ifcard-rows">
            ${(e.endpoint || e.port) ? html`<div class="ifrow"><span class="l">Listen</span><span class="r addr">${(e.endpoint || "") + (e.port ? ":" + e.port : "") || "—"}</span></div>` : null}
            ${e.subnet ? html`<div class="ifrow"><span class="l">Subnet</span><span class="r addr">${e.subnet}</span></div>` : null}
            <${RowError} k=${"ifcancel:" + name + "|" + ifn}/></div></div>`;
        const _pfx = name + "|";
        // drop a client-optimistic entry only once the node REPORTS the iface (meta), or it's gone stale —
        // keep it through the whole "creating" phase so its details stay on the card AND the next form's
        // suggestions (name / subnet / port) account for it.
        for (const k of Object.keys(Store.ifaceNew)) {
          if (!k.startsWith(_pfx)) continue;
          const i = k.slice(_pfx.length);
          if (meta && meta[i]) { ifaceReady[name + "|" + i] = Date.now() + 5000; delete Store.ifaceNew[k]; }   // just created/onboarded → flash green→blue "ready" for 5s
          else if (Date.now() - (Store.ifaceNew[k].at || 0) > 900000) delete Store.ifaceNew[k];
        }
        const optNames = Object.keys(Store.ifaceNew).filter(k => k.startsWith(_pfx)).map(k => k.slice(_pfx.length));
        // system mesh-link ifaces (swg_*) are created/torn down by the panel during re-provision — they belong
        // to the Node-connections cards, NEVER the User-interfaces list, so exclude them from every pending lane.
        const pendOn = (nrec.onboarding || []).filter(ifn => !(meta && meta[ifn]) && !optNames.includes(ifn) && !isSysName(ifn));
        const cr = nrec.creating || {};   // { iface: "wg" | "awg" } — server-side, deduped against the client cards
        const pendCr = Object.keys(cr).filter(ifn => !(meta && meta[ifn]) && !optNames.includes(ifn) && !isSysName(ifn));
        const optCards = optNames.filter(ifn => !(meta && meta[ifn])).map(ifn => optIfCard(ifn, Store.ifaceNew[_pfx + ifn]));
        const pending = pendOn.concat(pendCr, optNames);
        pending.forEach(ifn => { ifaceWasBusy[name + "|" + ifn] = true; });   // any in-flight iface (create / onboard / server) → flash "ready" once it appears in meta
        const pcards = pendOn.map(ifn => pcard(ifn, "onboarding", null))
          .concat(pendCr.map(ifn => pcard(ifn, "creating", cr[ifn])))
          .concat(optCards);
        return metaErr ? html`<div class="notice warn"><${Ic} i="warn"/><span>This node hasn't reported in yet — its interfaces will show up here once it runs the installer and syncs.<br/><br/>Lost the enrollment token or the install command? Rotate the node's token to generate a fresh install command.</span></div>`
          : !meta ? html`<div class="loading"><span class="spin"></span>reading server…</div>`
          : (!userKeys.length && !pending.length) ? html`<div class="notice warn"><${Ic} i="warn"/><span>No managed interfaces reported.</span></div>`
          : html`<div class="ifgrid" ...${ifReorder.container()}>${orderById(userKeys, nrec.iface_order, x => x).map(ifn => {
              const m = meta[ifn];
              const it = ifReorder.item(ifn);
              if (ifaceWasBusy[name + "|" + ifn]) { ifaceReady[name + "|" + ifn] = Date.now() + 5000; ifaceWasBusy[name + "|" + ifn] = false; }   // just came up after being pending/creating → "ready" 5s
              const type = (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg";
              const ps = here.filter(p => p.targets.some(t => t.node === name && t.iface === ifn));
              const onlc = ps.filter(p => p.targets.some(t => t.node === name && t.iface === ifn && t.online)).length;
              const orph = Store.recon.orphans.filter(o => o.node === name && o.iface === ifn).length;
              const deleting = (nrec.deleting || []).includes(ifn);
              const istate = (((Store.stats[name] || {}).interfaces || {})[ifn] || {});
              const istopped = !!istate.stopped;   // operator stopped it (a choice, not a failure)
              const idown = !istopped && istate.down;   // genuinely down
              const irestarting = (nrec.restarting || []).includes(ifn);
              const iconverting = (nrec.proc_status || "").startsWith("converting");   // node is mid bare↔docker convert
              const fwdTurns = turnProxiesFor(name, ifn);   // turn-proxies forwarding to this interface (by connect-port == listen_port)
              const iprog = (nrec.cmd_progress || {})[ifn];   // node "what's happening now" (yellow note) for this interface
              const iop = Store.ifaceOp[name + "|" + ifn];   // optimistic start/stop/restart lifecycle (set on click, before the node reflects it)
              const iopBusy = iop && iop.phase === "busy";
              // a wide status badge is showing → keep it on one line by compacting the turn badges (turn→t) and
              // letting the name ellipsize; reverts to full once no such status is shown
              const tight = iopBusy || iconverting || deleting || idown || irestarting || !!(nrec.cmd_errors || {})[ifn];
              const idim = iconverting || deleting || idown || istopped || irestarting || iopBusy || !!iprog || nodeStale(name) || !!(nrec.cmd_errors || {})[ifn];   // attention / stopped / in-flight / node gone dark → dim
              return html`<a key=${ifn} class=${"ifcard" + (deleting ? " pending" : "") + (idim ? " down" : "") + it.cls} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} draggable=${false} data-rid=${it.rid}>
                <div class="ifcard-top"><span class="drag-grip" title="Drag to reorder" onClick=${e => e.preventDefault()} ...${ifReorder.grip(ifn)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>${blocked ? html`<span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span>` : html`<button class="ifc-edit" title=${"Edit interface · " + type.toUpperCase()} onClick=${e => { e.preventDefault(); e.stopPropagation(); openEditIface(name, ifn); }}><span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span><span class="ifc-pic"><${Ic} i="pencil"/></span></button>`}<span class="grow"></span>${ifaceTurnBadges(name, fwdTurns, tight)}${iprog ? html`<${CmdErr} err=${iprog} cls="warn" title="Working on the node"/>` : null}${iopBusy ? html`<span class="tg tg-busy"><${Ic} i="clock"/>${IFOP_BUSY[iop.verb] || iop.verb}</span>` : iconverting ? html`<span class="tg tg-convert" title="The node is converting between bare-metal and docker"><${Ic} i="clock"/>converting</span>` : deleting ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" msg=${(nrec.cmd_errors || {})[ifn]} title="Command failed on the node"/>` : istopped ? html`<span class="tg-off" title="Stopped by you — open to Start it"><${Ic} i="stop"/>stopped</span>` : idown ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="down" msg=${(nrec.cmd_errors || {})[ifn] || ("interface is down on the node — awg-quick couldn't bring it up: " + idown)} title="Interface down on the node"/>` : irestarting ? html`<span class="tg tg-busy"><${Ic} i="clock"/>restarting</span>` : ((nrec.cmd_errors || {})[ifn] ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="error" msg=${(nrec.cmd_errors || {})[ifn]} title="Command failed on the node"/>` : (m.drift && Object.keys(m.drift).length) ? html`<span class="tg tg-pending" title="A setting was edited directly on the server — open to Adopt or Restore"><${Ic} i="warn"/>modified</span>` : (ifaceReady[name + "|" + ifn] && Date.now() < ifaceReady[name + "|" + ifn]) ? html`<span class="tg tg-ready"><${Ic} i="check"/>ready</span>` : null)}</div>
                <div class="ifcard-rows">
                  <div class="ifrow"><span class="l">Listen</span><span class="r addr">${m.endpoint || ((m.address || "").split("/")[0] + (m.listen_port ? ":" + m.listen_port : "")) || "—"}</span></div>
                  <div class="ifrow"><span class="l">Subnet</span><span class="r addr">${m.subnet || "—"}</span></div>
                  <div class="ifrow"><span class="l">Traffic</span><span class="r">${m.egress_mode === "forward" && m.egress_node
                    ? html`<span class="egb egb-fwd" style=${"color:" + Store.nodeColor(m.egress_node)} title=${"Exits via " + Store.nodeName(m.egress_node) + (m.egress_ip ? " (" + m.egress_ip + ")" : "")}><${Ic} i="server"/>→ ${Store.nodeName(m.egress_node)}</span>`
                    : m.egress_mode === "smart"
                    ? html`<span class="egb egb-smart" title=${(m.routing || []).filter(r => r.action === "exit").length + " destination rule(s)"}><${Ic} i="cascade"/>smart</span>`
                    : html`<span class="egb egb-direct" title="Exits directly from this node"><${Ic} i="globe"/>direct</span>`}</span></div>
                  <div class="ifrow"><span class="l">Peers</span><span class="r">${ps.length
                    ? html`<${OnlinePeersTag} nodeId=${name} iface=${ifn} orphans=${orph} orphHref=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}
                        trigger=${() => html`<b class=${"oncount" + (onlc ? " on" : "")}>${onlc}</b><span class="faint">/${ps.length}</span>${orph ? html` <span class="ifc-orph" title=${orph + " unmanaged (orphan) peer" + (orph === 1 ? "" : "s")}>(${orph})</span>` : null}`}/>`
                    : (orph ? html`<span class="ifc-orph" title=${orph + " unmanaged (orphan) peer" + (orph === 1 ? "" : "s")}>${orph}</span>` : html`<span class="faint">none</span>`)}</span></div>
                </div></a>`;
            })}${pcards}</div>`; })()}
    <//>

    ${hasTurns && turnEnabled() ? html`<${TurnProxiesBlock} node=${name} nrec=${nrec} snap=${snap} metas=${meta} title="Turn proxies"/>` : null}
    `}
  </div>`;
}

// ═════════════════════════ SCREEN: INTERFACE DETAIL ═════════════════════════
function IfaceDetail({ node: rawNode, iface: rawIface }) {
  useStore();
  const [q, setQ] = useState("");
  const node = decodeURIComponent(rawNode);
  const iface = decodeURIComponent(rawIface);
  const nrec = (Store.nodes || []).find(n => n.id === node);   // FULL record (turn_manage/restarting/cmd_errors/ip_ifaces)
  if (!nrec) return html`<div class="screen"><div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>server</b></div>
    <div class="empty"><b>Unknown server</b>this server isn't in the fleet.</div></div>`;
  const dname = nrec.name || node;
  const meta = Store.ifaceMeta(node, iface);
  const live = Store.recon.nodeStatus[node] === "live";
  const blocked = !live || inProc(nrec.proc_status);   // node down or mid convert/re-install → only the per-peer QR (view config) stays enabled (a timed-out/failed tag doesn't block)
  // a pending listen-port change: desired (panel) != reported (node) until the node converges
  const updating = !!(meta && meta.desired_port && meta.listen_port && Number(meta.desired_port) !== Number(meta.listen_port));
  const type = (meta && meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg";
  const peers = Store.recon.peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface));
  const onl = peers.filter(p => p.targets.some(t => t.node === node && t.iface === iface && t.online)).length;
  const orphans = Store.recon.orphans.filter(o => o.node === node && o.iface === iface);
  const restarting = (nrec.restarting || []).includes(iface);
  const istate = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
  const istopped = !!istate.stopped;   // operator stopped it → a choice, not a failure (no error notice)
  const idown = !istopped && istate.down;   // genuinely down (failed to come up)
  const notup = !!idown || istopped;        // either way: offer Start + Edit
  const op = Store.ifaceOp[node + "|" + iface];   // start/stop/restart lifecycle (busy/ok/fail flash)
  // AmneziaWG params split into the four header columns: J* under Endpoint, S* under Server
  // address, H* under DNS, and I* (+ anything else) under MTU.
  const ap = (meta && meta.awg_params) || {};
  const awgGrp = pred => Object.entries(ap).filter(([k]) => pred(k)).map(([k, v]) => k + "=" + v);
  const awgCols = [awgGrp(k => k[0] === "J"), awgGrp(k => k[0] === "S"), awgGrp(k => k[0] === "H"), awgGrp(k => !"JSH".includes(k[0]))];
  const rows = peers.slice().sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || String(a.name).localeCompare(String(b.name)));
  // one {peer,target} row per peer on this interface, fed to the shared PeerGrid
  const ifaceRows = rows.map(p => ({ p, t: p.targets.find(d => d.node === node && d.iface === iface) || {} }));
  const ifaceShown = {};
  for (const { p, t } of ifaceRows) (ifaceShown[p.id] = ifaceShown[p.id] || new Set()).add(tkey(t.node, t.iface));
  const ql = q.trim().toLowerCase();
  const ifaceFiltered = !ql ? ifaceRows : ifaceRows.filter(({ p, t }) => {
    const u = p.user_id ? Store.user(p.user_id) : null;
    return searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + (u ? u.name : ""), ql);
  });

  return html`<div class="screen">
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b><${NodeBadges} active=${node}/></div>
    <div class="detail-head">
      <div class="title"><h1>${iface}</h1><span class=${"iftype " + type}>${type}</span>${istopped ? html`<span class="nstat stopped" title="Stopped by you — Start it whenever you're ready"><${Ic} i="stop"/> stopped</span>` : idown ? html`<span class="nstat down" style="cursor:pointer" title=${(nrec.cmd_errors || {})[iface] || ("down on the node — " + idown)} onClick=${() => openConfirm({ title: "Interface down on the node", log: (nrec.cmd_errors || {})[iface] || ("down on the node — " + idown), confirmLabel: "Close" })}><${Ic} i="warn"/> down</span>` : live ? html`<span class="reporting">reporting</span>` : html`<span class="nstat stale"><${Ic} i="info"/> stale</span>`}<span class="when"><${OnlinePeersTag} nodeId=${node} iface=${iface} total=${peers.length} orphans=${orphCount(node, iface)}/></span></div>
      <div class="grow"></div>
    </div>
    ${idown ? html`<div class="notice warn"><${Ic} i="warn"/><span>This interface is <b>down</b> on the node — its config below is read from the <code>.conf</code> (not live). The node reported: <code>${(nrec.cmd_errors || {})[iface] || idown}</code>. Use <b>Start interface</b> — if the bring-up fails, the exact reason (port clash, a left-over kernel interface of the same name, an unsupported AmneziaWG parameter, …) shows here.</span></div>` : null}

    ${!meta ? html`<div class="notice warn"><${Ic} i="warn"/><span>This interface hasn't been reported in a snapshot yet.</span></div>`
      : html`<${Panel} icon="key" title="Interface details" tone=${type === "awg" ? "" : "online"}
          actions=${html`<${Fragment}>${op && op.phase === "busy" ? html`<span class="tg-busy"><${Ic} i="clock"/>${IFOP_BUSY[op.verb] || op.verb}…</span>` : op && op.phase === "ok" ? html`<span class="tg-ok"><${Ic} i="check"/>${IFOP_DONE[op.verb] || op.verb}</span>` : op && op.phase === "fail" ? html`<${StatusTag} cls="tg-del" icon="warn" label=${IFOP_FAIL[op.verb] || "failed"} msg=${op.err || "the action failed on the node"} title="Action failed on the node"/>` : null}${(op && op.phase === "busy") ? null : notup
              ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Bring this interface up on the node"} onClick=${() => startOrRestartIface(node, iface, "start")}><${Ic} i="play"/> Start service</button>`
              : html`<${Fragment}><button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Take this interface down on the node (stays down until started)"} onClick=${() => startOrRestartIface(node, iface, "stop")}><${Ic} i="stop"/> Stop service</button><button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Bounce this interface's service on the node"} onClick=${() => startOrRestartIface(node, iface, "restart")}><${Ic} i="refresh"/> Restart service</button><//>`}<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openEditIface(node, iface)}><${Ic} i="pencil"/> Edit interface</button><//>`}>
        <div class="iface-grid">
          <div class="ig-item"><span class="ig-l">Endpoint</span><span class="ig-v">${meta.endpoint || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">Server address</span><span class="ig-v">${meta.address || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">DNS</span><span class="ig-v">${(Array.isArray(meta.dns) ? meta.dns.join(", ") : (meta.dns || "")) || "—"}</span></div>
          <div class="ig-item"><span class="ig-l">MTU</span><span class="ig-v">${meta.mtu || 1280}</span></div>
        </div>
        ${type === "awg" ? html`<div class="iface-amnezia">
          <span class="ig-l">AmneziaWG</span>
          <div class="iface-grid" style="margin-top:8px">
            ${awgCols.map(g => html`<div class="ig-item"><span class="ig-v">${g.length ? g.map(l => html`<span>${l}</span>`) : "—"}</span></div>`)}
          </div>
        </div>` : null}
      <//>`}

    ${turnEnabled() ? html`<${TurnProxiesBlock} node=${node} nrec=${nrec} metas=${Store.describe[node] || {}} title="Reachable via turn-proxy" iface=${iface}/>` : null}

    <${Panel} icon="users" title="Peers on this interface" count=${peers.length} pad=${false}
        lead=${html`<div class="search hdr"><${Ic} i="search"/><input placeholder="Search title, user, address…" value=${q} onInput=${e => setQ(e.target.value)}/></div>`}
        actions=${html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openCreatePeer({ node, iface, lock: true })}><${Ic} i="plus"/> Add peer</button>`}>
      <${PeerGrid} rows=${ifaceFiltered} agg=${false} node=${node} iface=${iface} shownByPeer=${ifaceShown} q=${q} blocked=${blocked}/>
    <//>

    ${orphans.length ? html`<${Panel} icon="warn" title="Unmanaged on this interface" tone="warn" pad=${false}
        actions=${html`<button class="btn btn-mini" onClick=${() => orphans.forEach(o => mutate({
          key: "orphan:" + o.node + "|" + o.iface + "|" + o.pubkey,
          call: () => api.peerAdopt({ pubkey: o.pubkey, psk: o.preshared_key || "", target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
        }))}><${Ic} i="link"/> Adopt all</button>`}>
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
        call: () => api.peerAdopt({ pubkey: o.pubkey, psk: o.preshared_key || "", target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
      })}>Adopt</button>
      <${RowError} k=${"orphan:" + o.node + "|" + o.iface + "|" + o.pubkey}/>
    </td></tr>`;
}

// Edit an interface: the Endpoint IP (what clients dial — config-facing only) and the Listen
// port (pushed to the node's wgXX.conf — the interface rebinds to it; peers are untouched and
// reconnect via the new port). Default DNS / MTU seed new peers. Interface key shown read-only.
// Ask the node to manage an existing wg/awg interface the panel didn't auto-detect. The node only
// needs the tool (wg/awg) + the .conf path; the public endpoint is a panel-side render override.
function openOnboardIface(node) { openModal(html`<${LoadIfaceSheet} node=${node}/>`); }
function BridgePortSheet({ iface, port }) {   // shown after creating an iface on a bridge docker node
  const p = port || "PORT";
  const portsLine = `- "${p}:${p}/udp"`;
  return html`<${Sheet} title=${"Publish port · " + iface}>
    <div class="iface-intro big"><div>Creation requested — it applies on the node's next sync. This node runs on <b>bridge</b> networking, so this interface's UDP port isn't reachable from outside until you publish it on the host (otherwise peers won't handshake — rx stays 0).</div></div>
    <div class="field"><label>1. Add under <span class="mono">swg-node → ports:</span> in the node's docker-compose.yml</label><div class="ipk-field"><span class="ipk-val" style="text-align:left">${portsLine}</span><button class="copybtn" onClick=${() => copy(portsLine, "Copied")}><${Ic} i="copy"/></button></div></div>
    <div class="field"><label>2. Apply (in the node's compose dir)</label><div class="ipk-field"><span class="ipk-val" style="text-align:left">docker compose up -d</span><button class="copybtn" onClick=${() => copy("docker compose up -d", "Copied")}><${Ic} i="copy"/></button></div><div class="hint">Re-installing the node with host networking avoids per-port publishing entirely.</div></div>
  <//>`;
}
// suggest the next listen port for a NEW interface ("iface") or turn-proxy ("turn") on a node: the highest
// existing port OF THAT KIND + 1 (or the base default if none), skipping any port already used by either.
// client-optimistic interfaces still being created on a node → [{name, subnet, port, type}]. Suggestions
// fold these in so a 2nd "Load new interface" before the 1st is live picks the NEXT free name/subnet/port.
function pendingIf(node) {
  const pfx = node + "|", out = [];
  for (const k of Object.keys(Store.ifaceNew)) if (k.startsWith(pfx)) { const e = Store.ifaceNew[k]; out.push({ name: k.slice(pfx.length), subnet: e.subnet || "", port: e.port || "", type: e.type }); }
  return out;
}
function pendingTurnPorts(node) {   // listen ports of turn-proxies still being installed (client-optimistic)
  const pfx = node + "|", out = [];
  for (const k of Object.keys(Store.turnNew)) if (k.startsWith(pfx)) { const p = Number(portOf(Store.turnNew[k].listen)); if (p) out.push(p); }
  return out;
}
function suggestPort(node, kind) {
  const snap = Store.stats[node] || {};
  const ifacePorts = Object.values(snap.interfaces || {}).map(b => Number((b.meta || {}).listen_port)).filter(Boolean)
    .concat(pendingIf(node).map(p => Number(p.port)).filter(Boolean));   // include interfaces being created
  const turnPorts = ((snap.turn_proxies) || []).map(t => Number(portOf(t.listen))).filter(Boolean)
    .concat(pendingTurnPorts(node));   // include turn-proxies being installed
  const used = new Set([...ifacePorts, ...turnPorts]);
  const mine = kind === "turn" ? turnPorts : ifacePorts;
  let p = mine.length ? Math.max(...mine) + 1 : (kind === "turn" ? 56000 : 51820);
  while (used.has(p) && p < 65535) p++;
  return p;
}
// next free interface name (<base><n>): highest numeric suffix across ALL interfaces + 1, then skip any taken (mirrors install-node.sh iface_next_index)
function suggestIface(node, proto) {
  const names = Object.keys((Store.stats[node] || {}).interfaces || {}).concat(pendingIf(node).map(p => p.name));   // include the ones being created
  const base = proto === "wg" ? "wg" : "awg";
  let hi = 0;
  for (const n of names) { const m = /(\d+)$/.exec(n); if (m) hi = Math.max(hi, Number(m[1])); }
  let i = hi + 1;
  while (names.includes(base + i)) i++;
  return base + i;
}
// next free 10.X.0.0/24 tunnel subnet: highest used second octet + 1 (default 10.8) (mirrors install-node.sh next_free_subnet)
function suggestSubnet(node) {
  let hi = 7;   // → first suggestion 10.8.0.0/24
  const pfx = (Store.panelSettings || {}).reserved?.iface_prefix || "swg_";
  const isSys = ifn => ifn.startsWith(pfx) || ifn.startsWith("swg_");
  const bump = s => { const m = /^10\.(\d{1,3})\./.exec(s || ""); if (m && Number(m[1]) < 255) hi = Math.max(hi, Number(m[1])); };   // skip 10.255.x (reserved mesh range)
  for (const [ifn, b] of Object.entries((Store.stats[node] || {}).interfaces || {})) {
    if (isSys(ifn)) continue;   // ignore system mesh links (10.255.x.x) — count only user wg/awg interfaces
    bump((b.meta || {}).subnet || (b.meta || {}).address || "");
  }
  for (const p of pendingIf(node)) bump(p.subnet);   // include the ones being created
  return "10." + Math.min(hi + 1, 254) + ".0.0/24";
}
// Two-dropdown egress: where an interface's traffic exits — Auto, Direct out a NIC, or Forward (cascade)
// to another node — plus the source IP (this node's, or the TARGET node's for forward). value =
// {mode:"auto"|"direct"|"forward", nic, node, ip}; the routing for "forward" is wired in Phase 2.
// Phase 3 smart-routing categories (keep in sync with SMART_CATEGORIES in swg-panel-server). A category is a
// destination set the node routes into the chosen exit's mesh link. Domain-tier ones (Google/YouTube/Yandex/
// VK/Meta/Twitter/Netflix) match by domain via the node's dnsmasq — so YouTube splits from the rest of Google;
// the rest (Telegram/Cloudflare/RU-net/All) match by provider IP ranges (geoip). "Russia" is TWO distinct lists:
// ru_net = the whole Russian IP space (geoip, every mode); ru_blocked = sites blocked INSIDE Russia (circumvention
// domains, Force-DNS only) — different meanings, so they're separate categories you route independently.
const SMART_CATEGORIES = [
  ["google", "Google"], ["youtube", "YouTube"], ["yandex", "Yandex"], ["vk", "VK"], ["telegram", "Telegram"],
  ["cloudflare", "Cloudflare"], ["meta", "Meta (FB / IG / WA)"], ["twitter", "Twitter / X"],
  ["netflix", "Netflix"], ["spotify", "Spotify"], ["twitch", "Twitch"], ["tiktok", "TikTok"],
  ["disney", "Disney+"], ["reddit", "Reddit"], ["discord", "Discord"], ["github", "GitHub"],
  ["openai", "OpenAI / ChatGPT"], ["claude", "Claude (Anthropic)"], ["gemini", "Google Gemini"],
  ["grok", "Grok (xAI)"], ["perplexity", "Perplexity"], ["deepseek", "DeepSeek"], ["copilot", "Microsoft Copilot"],
  ["ru_net", "Russia (all RU IPs)"], ["ru_blocked", "Russia (all blocked)"],
  ["all", "All traffic (catch-all)"],
];
const SMART_CAT_LABEL = Object.fromEntries(SMART_CATEGORIES);
// destination-stats palette: a fixed hue per category (built-ins by their SMART_CATEGORIES order; custom lists by a
// stable hash) so a category keeps its colour across renders. ≤10 hues → many-category fleets can repeat, but an
// operator routes only a handful at once. custom_<hash>/inline → "Custom".
const CAT_COLORS = ["#5B8FF9", "#61DDAA", "#F6BD16", "#E8684A", "#9270CA", "#269A99", "#FF9D4D", "#6DC8EC", "#FF99C3", "#D66BF0"];
const _CAT_IDX = Object.fromEntries(SMART_CATEGORIES.map(([id], i) => [id, i]));
const CAT_UNCAT_COLOR = "#8A94A6";   // muted slate — the "everything else" bucket, deliberately not a category hue
function catColor(c) {
  if (c === "uncat") return CAT_UNCAT_COLOR;
  if (_CAT_IDX[c] != null) return CAT_COLORS[_CAT_IDX[c] % CAT_COLORS.length];
  let h = 0; for (const ch of String(c)) h = (Math.imul(h, 31) + ch.charCodeAt(0)) >>> 0;
  return CAT_COLORS[h % CAT_COLORS.length];
}
// labels for catalog categories the CatPicker has fetched this session — lets a just-added (staged, not yet
// saved+polled) catalog cat show its provider label immediately, before Store.catLabels carries it.
const _CATALOG_LABEL_CACHE = {};
function catLabelOf(c) {   // built-in label · custom-list title (via the panel's custom_<hash>→title map) · inline custom → "Custom" · else the id
  if (c === "uncat") return "Uncategorised";
  const lt = Object.fromEntries((Store.panelSettings?.custom_lists || []).map(l => [l.id, l.title]));
  if (isProviderCat(c)) return prettyCatLabel(c, (Store.catLabels || {})[c] || _CATALOG_LABEL_CACHE[c]);   // provider list → humanised (country names etc.)
  return SMART_CAT_LABEL[c] || (Store.catLabels || {})[c] || lt[c] || _CATALOG_LABEL_CACHE[c] || (String(c).startsWith("custom") ? "Custom" : c);
}
// Host/IP capability flags for a list — ALWAYS Host first, IP second (house rule).
const capBadges = caps => html`<span class="capbs">
  ${caps && caps.host ? html`<span class="capb host" title="Matchable by domain — needs Force-DNS or SNI mode">Host</span>` : null}
  ${caps && caps.ip ? html`<span class="capb ip" title="Matchable by IP range — works in every mode">IP</span>` : null}</span>`;
// A provider-catalog id is "<prov>:<rawid>"; return the provider's display label (MetaCubeX / v2fly / …) for the source tag.
const isProviderCat = c => typeof c === "string" && c.includes(":") && !String(c).startsWith("custom");
// Provider list ids are cryptic (bare ISO country codes "ad"/"ae", "category-ads-all", "tld-cn"). Make them human:
// 2-letter codes → the country name via the browser's built-in Intl.DisplayNames (no hardcoded country table);
// known prefixes get expanded; everything else is title-cased. `fallback` = the panel's plain label.
const _REGION_NAMES = (() => { try { return new Intl.DisplayNames(["en"], { type: "region" }); } catch { return null; } })();
const _titleize = s => String(s).replace(/[-_]+/g, " ").trim().replace(/\b([a-z])/g, (_, c) => c.toUpperCase());
// Curated friendly names for popular service ids — the providers ship NO titles/descriptions (their lists are
// just id-named files), so this is our own polish for the common ones. Everything else falls back to Intl country
// names / prefix expansion / title-case. Keyed by the provider's raw id (after the "<prov>:").
const CAT_FRIENDLY = {
  meta: "Meta / Facebook", facebook: "Meta / Facebook", openai: "ChatGPT / OpenAI", twitter: "Twitter / X",
  google: "Google", youtube: "YouTube", netflix: "Netflix", telegram: "Telegram", whatsapp: "WhatsApp",
  instagram: "Instagram", tiktok: "TikTok", github: "GitHub", disney: "Disney+", spotify: "Spotify",
  twitch: "Twitch", reddit: "Reddit", discord: "Discord", vk: "VK", yandex: "Yandex", cloudflare: "Cloudflare",
  ru_gov: "Russian Government", ru_banks: "Russian Banks", ru_social: "Russian Social (VK / OK)",
};
function prettyCatLabel(id, fallback) {
  const rid = String(id || "").includes(":") ? String(id).split(":")[1] : String(id || "");
  if (CAT_FRIENDLY[rid.toLowerCase()]) return CAT_FRIENDLY[rid.toLowerCase()];   // curated friendly name (ids vary in case across providers)
  if (/^[a-z]{2}$/i.test(rid) && _REGION_NAMES) {                 // ISO 3166 alpha-2 → country name
    try { const n = _REGION_NAMES.of(rid.toUpperCase()); if (n && n.toUpperCase() !== rid.toUpperCase()) return n; } catch (e) {}
  }
  let m;
  if ((m = rid.match(/^geolocation-(.+)$/))) return "Geolocation: " + prettyCatLabel(m[1], null);
  if ((m = rid.match(/^category-(.+?)(-all)?$/))) return _titleize(m[1]) + (m[2] ? " (all)" : "");
  if ((m = rid.match(/^tld-(.+)$/))) return "TLD ." + m[1].toLowerCase();
  return fallback || _titleize(rid) || rid;
}
const catRawId = id => String(id || "").includes(":") ? String(id).split(":")[1] : String(id || "");   // the provider's raw id ("telegram")
// Providers ship NO descriptions (their lists are bare id-named files). These are OUR curated one-liners for the
// popular categories; everything else shows a live sample of its records instead ("e.g. netflix.com, fast.com").
const CAT_DESC = {
  google: "Google search, accounts & core services", youtube: "YouTube video + its CDN",
  netflix: "Netflix streaming & app", meta: "Facebook, Instagram & WhatsApp", facebook: "Facebook, Instagram & WhatsApp",
  telegram: "Telegram messenger", whatsapp: "WhatsApp messenger", instagram: "Instagram", twitter: "Twitter / X",
  openai: "ChatGPT & the OpenAI API", tiktok: "TikTok video", github: "GitHub & its CDN", disney: "Disney+ streaming",
  spotify: "Spotify audio", twitch: "Twitch live streaming", reddit: "Reddit", discord: "Discord voice & chat",
  cloudflare: "Cloudflare CDN / edge network", vk: "VKontakte", yandex: "Yandex services",
  ru_gov: "Russian government sites", ru_banks: "Russian banks", ru_social: "Russian social (VK / OK)",
};
const catDescOf = id => CAT_DESC[catRawId(id).toLowerCase()] || "";
// The provider's GitHub page for a specific list — where the operator can see exactly what it contains (the raw
// file, or blackmatrix7's folder with its README). Built from the same paths we fetch, as human github.com URLs.
function catListUrl(id, caps) {
  const rid = catRawId(id), prov = String(id).includes(":") ? String(id).split(":")[0] : "";
  const host = !!(caps && caps.host);
  switch (prov) {
    case "mc": return "https://github.com/MetaCubeX/meta-rules-dat/blob/meta/geo/" + (host ? "geosite" : "geoip") + "/" + rid + ".list";
    case "v2": return "https://github.com/v2fly/domain-list-community/blob/master/data/" + rid;
    case "ls": return "https://github.com/Loyalsoldier/geoip/blob/release/text/" + rid + ".txt";
    case "rf": return "https://github.com/1andrevich/Re-filter-lists/blob/main/" + rid + ".lst";
    case "bm": return "https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Clash/" + rid;
    default: return "";
  }
}
// Custom-list caps + size from its targets (domains → Host, IPs/CIDRs → IP). Accepts a targets string or a list obj.
const customTargets = l => (typeof l === "string") ? l : (l && (l.targets ?? [...(l.domains || []), ...(l.cidrs || [])].join(", "))) || "";
function customCaps(l) { const raw = customTargets(l); const doms = domainTargets(raw), ips = splitTargets(raw).filter(isIpTarget);
  return { host: doms.length > 0, ip: ips.length > 0 }; }
const customSize = l => { const raw = customTargets(l); return splitTargets(raw).filter(validTarget).length; };
// Record count for a provider-catalog cat (Host+IP tiers), shipped by the panel in Store.catSizes {cat:{ip,host}}.
const catSize = c => { const s = (Store.catSizes || {})[c] || {}; return (s.host || 0) + (s.ip || 0); };
const fmtCount = n => n == null ? "…" : n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n);
// "142 hosts · 38 nets" style summary from per-tier counts (Host first). Empty string when nothing is known.
function sizeSummary(host, ip) {
  const p = [];
  if (host) p.push(fmtCount(host) + (host === 1 ? " host" : " hosts"));
  if (ip) p.push(fmtCount(ip) + (ip === 1 ? " net" : " nets"));
  return p.join(" · ");
}
// A small record-count pill that, on hover, shows the list's counts (Host domains · IP nets) + the first few
// entries. Provider cats lazy-fetch /api/list-info (session-cached); custom lists read their own targets. With
// `eager`, the count loads on mount so it shows inline (used in the catalog search where sizes aren't preshipped).
const _LIST_INFO_CACHE = {};   // cat -> resolved list-info (count + sample), so CatalogRow paging never re-fetches
// Plain "N hosts · M nets" text for a list. Counts come from the panel's shipped cat_sizes (routed cats) or the
// custom list's own targets — no fetch, no hover bubble (the full sample lives inline in the catalog browse row).
function ListInfo({ cat, list }) {
  let hostN = null, ipN = null;
  if (list) { const raw = customTargets(list); hostN = domainTargets(raw).length; ipN = splitTargets(raw).filter(isIpTarget).length; }
  else if (cat) { const s = (Store.catSizes || {})[cat] || {}; hostN = s.host; ipN = s.ip; }
  const summary = sizeSummary(hostN || 0, ipN || 0);
  if (!summary) return null;
  return html`<span class="listsize">${summary}</span>`;
}

// A rich catalog-browse row (the "Add from catalog" list): title + the raw id (name) dimmed under it, the
// provider tag, a description (curated, else a live sample of records), "N hosts · M nets", and Host/IP tags.
// Eager-loads /api/list-info (session-cached) for the counts + samples. Providers ship no descriptions, so the
// second line falls back to "e.g. <first few records>" — self-explanatory from the list's own contents.
const _isPending = d => !!(d && d.tiers && Object.keys(d.tiers).some(t => (d.tiers[t] || {}).pending));
function CatalogRow({ it, added, onPick }) {
  const [info, setInfo] = useState(() => { const c = _LIST_INFO_CACHE[it.id]; return c && !_isPending(c) ? c : null; });
  useEffect(() => {   // fetch counts+samples; if the panel is still resolving the list, poll a few times until it lands
    let live = true, tries = 0, timer = null;
    const go = () => api.listInfo(it.id).then(r => { const d = r && r.ok ? r.data : { err: true }; _LIST_INFO_CACHE[it.id] = d;
      if (!live) return; setInfo(d);
      if (_isPending(d) && tries++ < 8) timer = setTimeout(go, 1800); }).catch(() => live && setInfo({ err: true }));
    if (!info || _isPending(_LIST_INFO_CACHE[it.id])) go();
    return () => { live = false; clearTimeout(timer); }; }, [it.id]);
  const title = prettyCatLabel(it.id, it.label), rid = catRawId(it.id), desc = catDescOf(it.id);
  const hostD = info && info.tiers && info.tiers.host, ipD = info && info.tiers && info.tiers.ip;
  const summary = sizeSummary((hostD && hostD.n) || 0, (ipD && ipD.n) || 0);
  const samples = ((hostD && hostD.sample) || (ipD && ipD.sample) || []).slice(0, 4);
  const more = (((hostD && hostD.n) || (ipD && ipD.n) || 0) > samples.length);
  const pending = !info || _isPending(info);
  const sub = desc || (samples.length ? "e.g. " + samples.join(", ") + (more ? "…" : "")
    : (pending ? "loading…" : (info && info.err ? "couldn't load" : "")));
  return html`<button type="button" class=${"catrow" + (added ? " sel" : "")} onClick=${() => onPick(it.id)}>
    <span class=${"catpick-tick" + (added ? " on" : "")}>${added ? "✓" : ""}</span>
    <div class="catrow-main">
      <div class="catrow-l1"><span class="catrow-title">${title}</span>${rid.toLowerCase() !== title.toLowerCase() ? html`<span class="catrow-id">${rid}</span>` : null}</div>
      ${sub ? html`<div class="catrow-l2">${desc ? html`<span class="catrow-desc">${desc}</span>` : null}${desc && samples.length ? html`<span class="catrow-eg"> · e.g. ${samples.join(", ")}${more ? "…" : ""}</span>` : (!desc ? html`<span class="catrow-eg">${sub}</span>` : null)}</div>` : null}
    </div>
    <div class="catrow-right">
      <${ProvTag} id=${it.id} label=${it.provider_label || provLabelOf(it.id)}/>${capBadges(it.caps)}${summary ? html`<span class="catrow-size">${summary}</span>` : null}
      ${catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title="View this list on GitHub" onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>` : null}</div>
  </button>`;
}
function provLabelOf(c) {
  if (!isProviderCat(c)) return "";
  const pid = c.split(":")[0];
  return ((Store.catalogProviders || []).find(p => p.id === pid) || {}).label || pid;
}
// Each provider gets a distinct colour (default palette + a Panel-settings per-mode override, like turn forks).
const CAT_PROVIDER_DEFAULTS = { mc: { color: "#5B8FF9", colorL: "#2C6FD6" }, v2: { color: "#61DDAA", colorL: "#1E9E6E" },
  ls: { color: "#F6BD16", colorL: "#B8890A" }, rf: { color: "#E8684A", colorL: "#C2452A" }, bm: { color: "#B07BE0", colorL: "#8347C0" } };
function providerColor(prov) {
  const ov = (Store.panelSettings && Store.panelSettings.provider_colors) || {};
  const d = CAT_PROVIDER_DEFAULTS[prov] || { color: "#8FA8C0", colorL: "#5E7085" };
  return pickThemed(ov[prov], d.color, d.colorL);
}
// Provider source tag — colour-coded by provider (or a neutral "Custom"/"built-in" chip when plain).
function ProvTag({ id, label, plain }) {
  if (plain || !isProviderCat(id)) return html`<span class="catpick-src legacy">${label}</span>`;
  return html`<span class="catpick-src" style=${"--pc:" + providerColor(String(id).split(":")[0])}>${label || provLabelOf(id)}</span>`;
}
// Per-category match capability, shipped by /api/state (Store.smartCaps). ip = matchable by geoip (works in
// EVERY routing mode); host = matchable by domain via the node's dnsmasq (needs DNS → forcedns). A
// host-ONLY category (youtube today) is dead weight in kernel mode, so the UI greys/hides it there.
const catCap = id => (Store.smartCaps || {})[id] || { ip: false, host: false };
const catHostOnly = id => { const c = catCap(id); return c.host && !c.ip; };
const catUsableInMode = (id, mode) => mode === "kernel" ? catCap(id).ip : (catCap(id).ip || catCap(id).host);
const catDoms = id => (Store.catDomains || {})[id] || [];   // curated domains for a host category (empty for geoip/fetched cats)
// hover bubble listing a list's domains/IPs (only when there are some); `note` = a faint footer caption
const listBubble = (items, note) => items && items.length ? html`<span class="listbub" role="tooltip">
  <span class="lb-h">${items.length} entr${items.length === 1 ? "y" : "ies"}</span>
  ${items.slice(0, 40).map(d => html`<span class="lb-i">${d}</span>`)}
  ${items.length > 40 ? html`<span class="lb-m">+${items.length - 40} more</span>` : null}
  ${note ? html`<span class="lb-n">${note}</span>` : null}</span>` : null;
let _ruleSeq = 0;
const newRid = () => "rr" + (++_ruleSeq);
// grow a textarea to fit its content (starts at one row like a textbox, expands as lines wrap)
const autoGrow = el => { if (!el) return; el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; };

// The full catalog index, fetched once and searched CLIENT-side — so search matches the readable title
// (country names, friendly names) and descriptions, not just the raw provider id. ~3.5k tiny rows.
let _CATALOG_INDEX = null;
function loadCatalogIndex() {
  if (_CATALOG_INDEX) return Promise.resolve(_CATALOG_INDEX);
  return api.catalogIndex().then(r => {
    if (r && r.ok) { const pl = r.data.provider_labels || {};
      _CATALOG_INDEX = (r.data.items || []).map(it => ({ ...it, provider_label: pl[it.provider] || it.provider })); }
    return _CATALOG_INDEX || [];
  }).catch(() => []);
}

// Searchable provider-catalog category picker — replaces the native <select> for routing rules. The
// catalog holds ~3.5k categories (far too many for a dropdown), so this is a combobox: a button showing
// the current label, opening a portal'd popover with a search box (filters the full index locally, by title/
// id/description) plus the operator's own custom lists pinned on top. caps ({ip,host}) drive kernel greying —
// a host-only category can't match by dest IP, so it's disabled (not hidden) in kernel mode with a note.
// addMode: the picker becomes a multi-select "Add from catalog" affordance — it stays open on each pick,
// shows a ✓ on already-added ids (from `selected`), and hides the Custom row, custom lists, and the 26
// built-ins (those are managed by the checkboxes above it). Used by the Settings node-lens.
function CatPicker({ value, mode, customLists, catalogCats, listTitle, onChange, addMode, selected, triggerLabel }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [cidx, setCidx] = useState(addMode ? _CATALOG_INDEX : null);   // the full catalog index (addMode only), loaded once
  const [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null), inRef = useRef(null);
  const selSet = new Set(selected || []);
  const curLabel = addMode ? (triggerLabel || "Add from catalog")
    : value === "custom" ? "Custom IPs / domains…"
    : (SMART_CAT_LABEL[value] || (listTitle || {})[value] || (Store.catLabels || {})[value] || value || "Choose a category…");
  const usable = caps => mode === "kernel" ? !!(caps && caps.ip) : !!(caps && (caps.ip || caps.host));
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
    const flip = below < 300 && above > below;                 // not enough room under the trigger → open upward
    setPos({ left: Math.round(r.left), top: Math.round(flip ? r.top - 4 : r.bottom + 4), width: Math.round(r.width),
      flip, maxh: Math.max(200, Math.round(flip ? above : below)) }); };   // list caps to the space actually available
  useEffect(() => {   // addMode: load the full index ONCE, then search/paginate locally (matches title + id + description)
    if (open && addMode && !cidx) { let live = true; loadCatalogIndex().then(x => live && setCidx(x)); return () => { live = false; }; }
  }, [open, addMode]);
  useEffect(() => {   // position + outside-click/Esc/scroll handling while open
    if (!open) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) setOpen(false); };
    const onKey = e => { if (e.key === "Escape") { setOpen(false); ref.current && ref.current.focus(); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true); document.addEventListener("keydown", onKey);
    setTimeout(() => inRef.current && inRef.current.focus(), 0);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const pick = id => { onChange(id); if (addMode) return; setOpen(false); setQ(""); setPage(0); };   // addMode stays open for multi-add
  const capBadge = capBadges;   // shared Host-first renderer (defined near catLabelOf)
  // addMode: filter the full index by title/id/description, sort by readable title, paginate 40/page locally.
  const per = 40;
  const _aq = q.trim().toLowerCase();
  const filtered = addMode && cidx ? cidx.filter(it => { if (!_aq) return true;
    return it.id.toLowerCase().includes(_aq) || catRawId(it.id).toLowerCase().includes(_aq)
      || prettyCatLabel(it.id, "").toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq); })
    .map(it => ({ ...it, disp: prettyCatLabel(it.id, "") })).sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase())) : [];
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / per));
  const items = filtered.slice(page * per, (page + 1) * per);
  const lists = customLists || [];
  // Routing picker (non-addMode): TWO sections — Provider lists (the node's opted-in provider-catalog cats, each
  // source-tagged) and Custom lists (your own). Never the full catalog — filtered client-side; add more via Settings.
  // A currently-selected LEGACY built-in (existing rule) is shown under Provider lists so it stays editable.
  const _ql = q.trim().toLowerCase();
  const _match = (id, label) => !_ql || String(label).toLowerCase().includes(_ql) || String(id).toLowerCase().includes(_ql);
  const _provRows = (catalogCats || []).map(c => ({ id: c.id, label: c.title, caps: catCap(c.id), src: provLabelOf(c.id) }));
  if (!addMode && value && !isProviderCat(value) && value !== "custom" && !lists.some(l => l.id === value) && !_provRows.some(r => r.id === value))
    _provRows.push({ id: value, label: catLabelOf(value), caps: catCap(value), src: "built-in", legacy: true });   // keep a legacy built-in rule visible/editable
  const localGroups = addMode ? [] : [
    { grp: "Provider lists", rows: _provRows.filter(r => _match(r.id, r.label)).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
    { grp: "Custom lists", rows: lists.filter(l => _match(l.id, l.title)).map(l => ({ id: l.id, label: l.title, caps: customCaps(l), src: "Custom", list: l })).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
  ].filter(g => g.rows.length);
  const localEmpty = !addMode && !localGroups.length && !!_ql;
  return html`<div class=${"catpick" + (addMode ? " catpick-add" : "")} ref=${ref}>
    ${addMode ? html`<button type="button" class=${"btn btn-mini" + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}><${Ic} i="plus"/> ${curLabel}</button>`
      : html`<button type="button" class=${"catpick-btn" + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}>
      <span class="catpick-lbl">${curLabel}</span><span class="catpick-caret">▾</span>
    </button>`}
    ${open && pos ? html`<${Portal}><div ref=${popRef} class=${"catpick-pop" + (pos.flip ? " flip" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;min-width:" + Math.max(pos.width, 320) + "px;--catpick-maxh:" + (pos.maxh - 160) + "px"}>
      <div class="catpick-search">
        <${Ic} i="search"/>
        <input ref=${inRef} type="text" placeholder=${addMode ? "Search " + ((cidx && cidx.length) || "") + " lists — name, country, service…" : "Filter this node's lists…"} value=${q}
          onInput=${e => { setQ(e.target.value); setPage(0); }} spellcheck="false" autocomplete="off"/>
      </div>
      <div class="catpick-list">
        ${!addMode ? html`
          ${!_ql ? html`<button type="button" class=${"catpick-row" + (value === "custom" ? " sel" : "")} onClick=${() => pick("custom")}>
            <span class="catpick-rlbl"><${Ic} i="pencil"/> Custom IPs / domains…</span></button>` : null}
          ${localGroups.map(g => html`<div class="catpick-grp">${g.grp}</div>
            ${g.rows.map(it => { const ok = it.caps ? usable(it.caps) : true; return html`<button type="button" disabled=${!ok}
              class=${"catpick-row" + (value === it.id ? " sel" : "") + (ok ? "" : " off")} onClick=${() => ok && pick(it.id)}
              title=${ok ? "" : "Host-only list — switch this node to Force-DNS to use it"}>
              <span class="catpick-rlbl">${it.label}${it.src ? html`<${ProvTag} id=${it.id} label=${it.src} plain=${it.legacy || it.src === "Custom"}/>` : null}</span>
              ${it.caps ? capBadge(it.caps) : null}${it.list ? html`<${ListInfo} list=${it.list}/>` : (isProviderCat(it.id) ? html`<${ListInfo} cat=${it.id}/>` : null)}
              ${isProviderCat(it.id) && catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title="View this list on GitHub" onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>` : null}</button>`; })}`)}
          ${localEmpty ? html`<div class="catpick-empty">No list on this node matches “${q}”. Add more in Settings → Routing lists.</div>` : null}
        ` : html`
          ${cidx == null ? html`<div class="catpick-empty">Loading catalog…</div>`
            : items.length === 0 ? html`<div class="catpick-empty">No list matches “${q}”.</div>`
            : items.map(it => html`<${CatalogRow} key=${it.id} it=${it} added=${selSet.has(it.id)} onPick=${pick}/>`)}
        `}
      </div>
      ${mode === "kernel" ? html`<div class="catpick-note">Greyed lists match by <b>domain</b> only — this node is in <b>Kernel</b> (IP) mode. Switch it to Force-DNS or SNI to use them.</div>` : null}
      ${addMode && total > per ? html`<div class="catpick-foot">
        <button type="button" class="btn btn-mini" disabled=${page === 0} onClick=${() => setPage(p => Math.max(0, p - 1))}>‹ Prev</button>
        <span class="catpick-count">${page * per + 1}–${Math.min(total, (page + 1) * per)} of ${total}</span>
        <button type="button" class="btn btn-mini" disabled=${page >= pages - 1} onClick=${() => setPage(p => Math.min(pages - 1, p + 1))}>Next ›</button>
      </div>` : null}
    </div><//>` : null}
  </div>`;
}

// One smart-routing rule row: a category → a destination (exit node / direct / block). Reuses the
// drag-reorder hook; order is priority (first match wins on the node).
function RoutingRules({ node, rules, onChange }) {
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const _ps = Store.panelSettings || {};
  const _nrec = (Store.nodes || []).find(n => n.id === node);   // built-in categories enabled for THIS node (null/[] = all)
  const _mode = (_nrec && _nrec.routing_mode) || "kernel";        // host-only cats are unusable in kernel mode → drop them from the dropdown
  const _ec = _nrec && _nrec.enabled_categories && _nrec.enabled_categories.length ? new Set(_nrec.enabled_categories) : null;
  const hiddenCats = { has: id => (_ec ? !_ec.has(id) : false) || !catUsableInMode(id, _mode) };   // node-scoped: hidden = not enabled, OR not matchable in this mode
  const customLists = (_ps.custom_lists || []).filter(l => !(l.disabled_nodes || []).includes(node));   // per-node: hide lists the operator disabled on THIS node
  const catalogCats = (_nrec && _nrec.catalog_cats || []).map(id => ({ id, title: catLabelOf(id) }));   // provider-catalog cats opted into this node → the Provider lists section
  const listTitle = Object.fromEntries([...(_ps.custom_lists || []).map(l => [l.id, l.title]), ...catalogCats.map(c => [c.id, c.title])]);
  const catLabel = c => c === "custom" ? "Custom IPs / domains" : (SMART_CAT_LABEL[c] || listTitle[c] || c);
  const allRule = rules.find(r => r.category === "all");          // the catch-all ("everything else") → footer dropdown
  const dispRules = rules.filter(r => r.category !== "all");
  const emit = drules => onChange(allRule ? [...drules, allRule] : drules);   // catch-all is always kept LAST (first-match)
  const rs = useReorder(dispRules.map(r => r._rid), ids => emit(ids.map(id => dispRules.find(r => r._rid === id)).filter(Boolean)), "y", { container: ".rrlist", card: ".rrrow" });
  const setRule = (rid, patch) => emit(dispRules.map(r => r._rid === rid ? { ...r, ...patch } : r));
  const addRule = () => emit([...dispRules, { _rid: newRid(), enabled: true, category: "custom", action: others[0] ? "exit" : "direct", node: (others[0] || {}).id || "" }]);
  const destVal = r => r.action === "exit" ? "exit|" + (r.node || "") : r.action;
  const onDest = (rid, v) => { const [a, n] = v.split("|"); setRule(rid, a === "exit" ? { action: "exit", node: n } : { action: a, node: "" }); };
  // auto-mode: a domain rule can't match in kernel mode — offer a one-click switch of THIS node to Force-DNS instead of a dead-end
  const switchToForceDns = async () => {
    if (!confirm("Switch " + (_nrec ? _nrec.name : "this node") + " to Force-DNS mode?\n\nThis reprovisions the node (adds its DNS resolver) so domain rules can match. IP rules keep working. Save your rule changes afterwards.")) return;
    const r = await api.nodeUpdate({ id: node, routing_mode: "forcedns" });
    if (!r || !r.ok) return toast((r && r.error) || "Couldn't switch mode", "err");
    await Store.poll();
    toast("Switched to Force-DNS — domain rules now match. Save to apply.", "ok");
  };
  const catchVal = !allRule ? "direct" : allRule.action === "exit" ? "exit|" + (allRule.node || "") : allRule.action;   // "exit|<n>" | "block" | "direct" (default = no stored catch-all)
  const setCatch = v => { const [a, n] = v.split("|");
    onChange(a === "exit" && n ? [...dispRules, { _rid: newRid(), enabled: true, category: "all", action: "exit", node: n }]
      : a === "block" ? [...dispRules, { _rid: newRid(), enabled: true, category: "all", action: "block" }]
      : dispRules); };   // "direct" is the implicit default → no stored rule
  const seen = {};
  return html`<div class="field"><label>Routing rules <span class="faint" style="text-transform:none;letter-spacing:0">— first match wins</span></label>
    <div class="rrlist" ...${rs.container()}>${dispRules.map(r => {
      const ckey = r.category === "custom" ? "custom:" + (r.targets || "") : r.category;
      const dup = seen[ckey]; seen[ckey] = true;
      const self = r.action === "exit" && r.node === node;
      const badToks = r.category === "custom" ? invalidTargets(r.targets || "") : [];
      const ipOnly = _mode === "kernel";                       // kernel matches by dest IP only — no hostname routing
      const domToks = (ipOnly && r.category === "custom") ? domainTargets(r.targets || "") : [];   // domains a kernel node can't match
      const it = rs.item(r._rid);
      return html`<div key=${r._rid} class=${"rrrow" + it.cls + ((dup || self || badToks.length || domToks.length) ? " warn" : "")} data-rid=${it.rid}>
        <span class="drag-grip" title="Drag to reorder" ...${rs.grip(r._rid)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>
        <${CatPicker} value=${r.category} mode=${_mode} customLists=${customLists} catalogCats=${catalogCats} listTitle=${listTitle}
          onChange=${v => setRule(r._rid, { category: v })}/>
        <span class="rrarrow">→</span>
        <select class="selwrap" value=${destVal(r)} onChange=${e => onDest(r._rid, e.target.value)}>
          <option value="direct">Direct (this node)</option>
          <option value="block">Block</option>
          ${others.length ? html`<optgroup label="Exit via node">${others.map(n => html`<option value=${"exit|" + n.id}>→ ${n.name}</option>`)}</optgroup>` : null}
        </select>
        <button class="xbtn" title="Remove rule" onClick=${() => emit(dispRules.filter(x => x._rid !== r._rid))}><${Ic} i="x"/></button>
        ${self ? html`<span class="rrlint">can't exit via itself</span>` : dup ? html`<span class="rrlint">shadowed by an earlier ${catLabel(r.category)} rule</span>` : null}
        ${r.category === "custom" ? html`<textarea class="rrdoms" rows="1" spellcheck="false" placeholder=${ipOnly ? "IPs / CIDRs only (Kernel mode) — e.g. 1.2.3.0/24, 5.6.7.8" : "IPs / domains (any level), comma-separated — e.g. youtube.com, 1.2.3.0/24, sub.example.com"} value=${r.targets || ""} onInput=${e => { autoGrow(e.target); setRule(r._rid, { targets: e.target.value }); }} ref=${el => autoGrow(el)}/>${!splitTargets(r.targets || "").length ? html`<span class="rrlint">add at least one IP${ipOnly ? " or CIDR" : " or domain"}</span>` : badToks.length ? html`<span class="rrlint">not a valid IP, CIDR or domain: ${badToks.join(", ")}</span>` : domToks.length ? html`<span class="rrlint">Kernel mode is IP-only — ${domToks.slice(0, 3).join(", ")}${domToks.length > 3 ? "…" : ""} ${domToks.length > 1 ? "are domains" : "is a domain"}. Use IPs/CIDRs, or <button type="button" class="linkbtn" onClick=${switchToForceDns}>switch this node to Force-DNS</button>.</span>` : null}` : null}
      </div>`;
    })}</div>
    <div class="rrfoot">
      <span class="rrfoot-lead"><button class="btn btn-mini" onClick=${addRule}><${Ic} i="plus"/> Add rule</button><b class="rrfoot-label">Everything else</b></span>
      <span class="rrarrow">→</span>
      <select class="selwrap rrcatch" value=${catchVal} onChange=${e => setCatch(e.target.value)}>
        <option value="direct">Direct (this node)</option>
        ${others.map(n => html`<option value=${"exit|" + n.id}>→ ${n.name}</option>`)}
        <option value="block">Block</option>
      </select>
      <button class="xbtn rrfoot-ghost" tabindex="-1"><${Ic} i="x"/></button>
    </div>
    ${dispRules.length || allRule ? null : html`<div class="hint">No rules yet. Add a rule to send a category through another node, or set "Everything else" to channel everything.</div>`}
  </div>`;
}

function EgressPicker({ node, value, onChange }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ipIfaces = nrec.ip_ifaces || [];
  const nics = [...new Set(ipIfaces.map(p => p.iface))];
  const others = (Store.nodes || []).filter(n => n.id !== node);
  const ifSel = value.mode === "smart" ? "smart" : value.mode === "forward" ? "forward|" + (value.node || "") : value.mode === "direct" ? "direct|" + (value.nic || "") : "auto";
  let ipOpts = [];
  if (value.mode === "direct") ipOpts = ipIfaces.filter(p => !value.nic || p.iface === value.nic).map(p => p.ip);
  else if (value.mode === "forward") { const tn = others.find(n => n.id === value.node); ipOpts = (tn && tn.ips) || []; }
  const onIf = e => {
    const v = e.target.value;
    if (v === "auto") return onChange({ mode: "auto", nic: "", node: "", ip: "", rules: value.rules || [] });
    if (v === "smart") return onChange({ mode: "smart", nic: "", node: "", ip: "", rules: value.rules || [] });
    const [mode, x] = v.split("|");
    onChange(mode === "forward" ? { mode, node: x, nic: "", ip: "", rules: value.rules || [] } : { mode, nic: x, node: "", ip: "", rules: value.rules || [] });
  };
  return html`<${Fragment}>
    <div class="field"><label>Outbound (egress) interface</label>
      <select class="selwrap" value=${ifSel} onChange=${onIf}>
        <option value="auto">Auto (MASQUERADE)</option>
        ${nics.map(n => html`<option value=${"direct|" + n}>Direct — ${n}</option>`)}
        ${others.length ? html`<optgroup label="Forward to node (cascade)">${others.map(n => html`<option value=${"forward|" + n.id}>Forward to ${n.name}</option>`)}</optgroup>` : null}
        ${others.length ? html`<option value="smart">Smart routing (by destination)</option>` : null}
      </select>
      <div class="hint">Exit directly out a NIC, channel everything through another node, or route per-destination (smart).</div></div>
    ${value.mode === "smart"
      ? html`<${RoutingRules} node=${node} rules=${value.rules || []} onChange=${rs => onChange({ ...value, rules: rs })}/>`
      : value.mode !== "auto" ? html`<div class="field"><label>Outbound (egress) IP</label>
      <${NodeIpPick} ips=${ipOpts} value=${value.ip || ""} onChange=${ip => onChange({ ...value, ip })} auto=${value.mode === "forward" ? "Auto (target node default)" : "Auto"}/>
      <div class="hint">${value.mode === "forward" ? "Source IP on the target node that clients egress from." : "Source IP clients egress from."}</div></div>` : null}
  <//>`;
}
const egressInit = m => ({ mode: m.egress_mode === "smart" ? "smart" : m.egress_mode === "forward" ? "forward" : (m.egress_ip || m.wan_iface) ? "direct" : "auto",
  nic: m.wan_iface || "", node: m.egress_node || "", ip: m.egress_ip || "",
  rules: (m.routing || []).map(r => ({ ...r, _rid: newRid(), ...(r.category === "custom" ? { targets: [...(r.domains || []), ...(r.cidrs || [])].join(", ") } : {}) })) });
const egressBody = eg => eg.mode === "smart"
  ? { egress_mode: "smart", routing: (eg.rules || []).map(({ _rid, ...r }) => r) }
  : { egress_mode: eg.mode === "auto" ? "direct" : eg.mode, egress_node: eg.node || "", egress_ip: eg.ip || "", wan_iface: eg.nic || "" };
// custom-rule target validation — mirrors the backend _split_targets / _clean_targets exactly, so the UI
// rejects anything the node would silently drop. A token is valid if it's an IPv4 (optionally /0-32) or a
// domain (after stripping scheme/path and a leading "*."). Leading-dot / single-label names are invalid.
const _RR_IP4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(\/\d{1,2})?$/;
const _RR_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;   // one DNS label
const splitTargets = raw => String(raw || "").split(/[\s,]+/).filter(Boolean);
function validTarget(tok) {
  const t = String(tok).trim().toLowerCase(); if (!t) return false;
  // a bare IPv4 or IPv4/CIDR — all four octets ≤255, prefix 0-32 (rejects "22.1", "22.11.5/4343", "1.1.1.1/", "1.1.1.1/555")
  const mi = t.match(_RR_IP4);
  if (mi) return [1, 2, 3, 4].every(i => +mi[i] <= 255) && (!mi[5] || +mi[5].slice(1) <= 32);
  // otherwise a real domain: strip scheme + path + a leading "*."; need ≥2 labels, each a valid DNS label,
  // and an ALPHABETIC TLD (so "22.1", "1.1.1.1", "1.1.1.1/555"→"1.1.1.1" all fail — a bare number is never a host)
  let d = t.replace(/^https?:\/\//, "").split("/")[0];
  if (d.startsWith("*.")) d = d.slice(2);
  if (/[^\x00-\x7f]/.test(d)) { try { d = new URL("http://" + d).hostname; } catch { return false; } }   // IDN (Cyrillic etc.) → punycode, so it validates + matches the node's ASCII rules
  if (!d || d.length > 253) return false;
  const labels = d.split(".");
  return labels.length >= 2 && labels.every(l => _RR_LABEL.test(l)) && /^([a-z]{2,}|xn--[a-z0-9-]+)$/.test(labels[labels.length - 1]);
}
const invalidTargets = raw => splitTargets(raw).filter(t => !validTarget(t));
const isIpTarget = tok => { const m = String(tok).trim().toLowerCase().match(_RR_IP4); return !!m && [1, 2, 3, 4].every(i => +m[i] <= 255) && (!m[5] || +m[5].slice(1) <= 32); };
const domainTargets = raw => splitTargets(raw).filter(t => validTarget(t) && !isIpTarget(t));   // real hostnames among the valid tokens (kernel mode can't match these)
// null when the egress config is savable; otherwise a message the sheets show + disable Save on. `mode` = the node's
// routing_mode: in kernel (IP-only) a custom rule can't use domains — only Force-DNS matches by hostname.
function egressError(eg, mode) {
  if (!eg || eg.mode !== "smart") return null;
  for (const r of (eg.rules || [])) {
    if (r.category !== "custom") continue;
    const toks = splitTargets(r.targets || "");
    if (!toks.length) return "A custom rule needs at least one IP or domain.";
    const bad = toks.filter(t => !validTarget(t));
    if (bad.length) return "Invalid target" + (bad.length > 1 ? "s" : "") + ": " + bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "");
    if (mode === "kernel") {
      const doms = domainTargets(r.targets || "");
      if (doms.length) return "Kernel mode routes by IP only — remove the domain" + (doms.length > 1 ? "s" : "") + " (" + doms.slice(0, 3).join(", ") + (doms.length > 3 ? "…" : "") + "), or switch this node to Force-DNS.";
    }
  }
  return null;
}
function LoadIfaceSheet({ node }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";   // only bridge needs port publishing
  const [proto, setProto] = useState("awg");   // awg | wg | existing
  const sugAwg = suggestIface(node, "awg"), sugWg = suggestIface(node, "wg");   // auto-suggested names (per base)
  const [iface, setIface] = useState(sugAwg); const [subnet, setSubnet] = useState(suggestSubnet(node));
  const [host, setHost] = useState(""); const [port, setPort] = useState(String(suggestPort(node, "iface")));
  const _idf = (Store.panelSettings || {}).interface_defaults || {};   // panel-wide new-interface defaults
  const [dns, setDns] = useState((_idf.dns || ["1.1.1.1"]).join(", ")); const [mtu, setMtu] = useState(String(_idf.mtu || 1280)); const [ka, setKa] = useState(String(_idf.keepalive || 25));
  const [conf, setConf] = useState("");
  const ips = nrec.ips || []; const [eg, setEg] = useState(() => egressInit({}));
  // endpoint host: dropdown of the node's known IPs (default the first), last entry = a free-text "Custom IP / Host…"
  const [hostSel, setHostSel] = useState(ips[0] || "__custom__"); const [hostCustom, setHostCustom] = useState("");
  const pickProto = p => {   // switching base re-suggests the name only if the field is still an untouched suggestion
    if (p !== "existing" && (iface === sugAwg || iface === sugWg || !iface.trim())) setIface(p === "wg" ? sugWg : sugAwg);
    setProto(p);
  };
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const existing = proto === "existing";
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const save = async () => {
    setBusy(true); setMsg({ k: "work", t: "requesting…" });
    let r;
    if (existing) {
      const c = conf.trim();
      if (!c.startsWith("/")) return fail("Enter the absolute path to the interface's .conf.");
      const base = (c.split("/").pop() || "").replace(/\.conf$/i, "");   // seed the name from the filename
      r = await api.ifaceOnboard({ node, iface: base, protocol: "auto", conf: c, endpoint_host: host.trim() });
    } else {
      const nm = iface.trim();
      if (!nm || /[\s/]/.test(nm)) return fail("Interface name is required (no spaces or /).");
      if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(subnet.trim())) return fail("Enter the tunnel subnet as CIDR, e.g. 10.8.0.0/24.");
      if (port.trim() && !/^\d+$/.test(port.trim())) return fail("Listen port must be a number.");
      const ee = egressError(eg, nrec.routing_mode || "kernel"); if (ee) return fail(ee);
      const hostVal = ipPickerVal(hostSel, hostCustom);
      r = await api.ifaceCreate({ node, iface: nm, protocol: proto, subnet: subnet.trim(), endpoint_host: hostVal,
        listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), ...egressBody(eg) });
    }
    if (!r.ok) return fail(r.error || "Request failed.");
    // optimistic: show the card — WITH the details just entered — the instant Create is clicked (use the
    // component-scoped state vars, not the else-block locals). Onboarding doesn't know subnet/port yet.
    const _newName = existing ? (conf.trim().split("/").pop() || "").replace(/\.conf$/i, "") : iface.trim();
    if (_newName) Store.ifaceNew[node + "|" + _newName] = existing
      ? { type: null, at: Date.now() }
      : { type: proto, subnet: subnet.trim(), port: port.trim(), endpoint: ipPickerVal(hostSel, hostCustom), at: Date.now() };
    closeModal(); Store.apply(); await Store.poll();
    if (!existing && isBridge) { openModal(html`<${BridgePortSheet} iface=${nm} port=${port.trim()}/>`); return; }
    toast(existing ? "Onboarding requested — applies on the node's next sync." : "Interface creation requested — applies on the node's next sync.", "ok");
  };
  return html`<${Sheet} title="Create new interface"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy || (!existing && !!egressError(eg, nrec.routing_mode || "kernel"))} title=${(!existing && egressError(eg, nrec.routing_mode || "kernel")) || ""} onClick=${save}>${existing ? "Adopt" : "Create"}</button></>`}>
    <div class="field"><label>Protocol</label>
      <div class="chiprow proto3">
        <button class=${"chip c-awg" + (proto === "awg" ? " on" : "")} onClick=${() => pickProto("awg")}>AmneziaWG</button>
        <button class=${"chip c-wg" + (proto === "wg" ? " on" : "")} onClick=${() => pickProto("wg")}>WireGuard</button>
        <button class=${"chip c-ex" + (proto === "existing" ? " on" : "")} onClick=${() => pickProto("existing")}>Existing unbound interface</button>
      </div></div>
    ${existing ? html`<${Fragment}>
      <div class="iface-intro big">
        <div>Have the node start managing an existing wg/awg interface the panel didn't pick up.</div>
        <div>The node only needs the tool and the interface's .conf path — it reads the rest (keys, subnet, AWG params) and its existing peers show up as adoptable.</div>
        <div>It's applied on the node's next sync, then the interface appears here.</div>
      </div>
      <div class="field"><label>Config path</label><input autofocus value=${conf} onInput=${e => setConf(e.target.value)} placeholder="/etc/wireguard/wg0.conf" autocomplete="off"/></div>
      <div class="field"><label>Public endpoint host / IP <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input value=${host} onInput=${e => setHost(e.target.value)} placeholder="vpn.xyz.com or 203.0.113.7"/><div class="hint">What clients dial. Leave blank to use the node's detected address.</div></div>
    <//>` : html`<${Fragment}>
      <div class="row2">
        <div class="field"><label>Interface name</label><input autofocus value=${iface} onInput=${e => setIface(e.target.value)} placeholder=${proto === "wg" ? "wg0" : "awg0"} autocomplete="off"/></div>
        <div class="field"><label>Tunnel subnet (CIDR)</label><input value=${subnet} onInput=${e => setSubnet(e.target.value)} placeholder="10.8.0.0/24" autocomplete="off"/><div class="hint">The server takes the first host (e.g. 10.8.0.1);</div></div>
      </div>
      <div class="row2">
        <div class="field"><label>Endpoint host / IP</label>
          <${IpPicker} ips=${ips} sel=${hostSel} setSel=${setHostSel} custom=${hostCustom} setCustom=${setHostCustom} placeholder="vpn.xyz.com or 203.0.113.7"/>
          <div class="hint">What clients dial</div></div>
        <div class="field"><label>Listen port</label><input value=${port} onInput=${e => setPort(e.target.value)} placeholder="51820"/></div>
      </div>
      ${isBridge ? html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This docker node uses <span class="mono">bridge</span> networking — after creating you must publish this port in the node's <span class="mono">docker-compose.yml</span> (<span class="mono">ports: "${port || "PORT"}:${port || "PORT"}/udp"</span>) and <span class="mono">up -d</span>, or clients can't reach it. (A host-networking node needs none of this.)</span></div>` : null}
      <div class="row2">
        <div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">Blank = 1280</div></div>
        <div class="field"><label>Persistent keepalive (s)</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/><div class="hint">0 disables · blank = 25</div></div>
      </div>
      <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="1.1.1.1"/><div class="hint">Comma-separated</div></div>
      <${EgressPicker} node=${node} value=${eg} onChange=${setEg}/>
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
// Delete an interface — destructive, so gated behind typing "DELETE <iface>" (case-sensitive).
function DeleteIfaceSheet({ node, iface }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = "DELETE " + iface;
  const ok = txt === phrase;
  const del = async () => {
    if (!ok || busy) return;
    setBusy(true);
    const r = await api.ifaceDelete({ node, iface });
    if (!r.ok) { setBusy(false); return toast(r.error || "Failed to delete interface.", "err"); }
    closeAllModals(); await Store.poll();   // iface is gone → close this + the editor behind it
    toast("Interface deletion requested — the node tears it down on its next sync.", "ok");
    go("#/node/" + encodeURIComponent(node));   // this interface's page is going away
  };
  return html`<${Sheet} title=${"Delete interface · " + iface}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-danger" disabled=${!ok || busy} onClick=${del}>Delete interface</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>This permanently tears down <b>${iface}</b> on the node: the interface goes <b>down</b>, its <b>.conf and server key are removed</b>, and <b>every peer on this interface is destroyed</b>. Peers deployed only here are deleted from the panel and their configs/QRs stop working. This can't be undone.</span></div>
    <div class="field"><label>Type <span class="mono" style="text-transform:none">${phrase}</span> to confirm</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}
async function restartIface(node, iface) {   // legacy callers (e.g. Save auto-restart) — fire-and-forget
  const r = await api.ifaceRestart({ node, iface });
  if (!r.ok) return toast(r.error || "Failed to request restart.", "err");
  await Store.poll();
}
async function stopIface(node, iface) {
  const r = await api.ifaceStop({ node, iface });
  if (!r.ok) return toast(r.error || "Failed to stop.", "err");
  await Store.poll(); toast("Stop requested — applies on the node's next sync.", "ok");
}
async function startIface(node, iface) {
  const r = await api.ifaceStart({ node, iface });
  if (!r.ok) return toast(r.error || "Failed to start.", "err");
  await Store.poll(); toast("Start requested — applies on the node's next sync.", "ok");
}
async function restartIfaceToast(node, iface) {
  const r = await api.ifaceRestart({ node, iface });
  if (!r.ok) return toast(r.error || "Failed to restart.", "err");
  await Store.poll(); toast("Restart requested — applies on the node's next sync.", "ok");
}
// start/restart with an inline progress lifecycle on the interface card: busy tag (button hidden)
// → green "started/restarted" 5s or red "failed" 10s (button back). verb = "start" (down) | "restart".
async function startOrRestartIface(node, iface, verb) {
  const key = node + "|" + iface;
  Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply();
  const m = verb === "stop" ? "ifaceStop" : verb === "start" ? "ifaceStart" : "ifaceRestart";
  const r = await api[m]({ node, iface });
  if (!r.ok) {
    Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 10000, err: r.error || "request failed" };
    Store.apply(); setTimeout(() => Store.apply(), 10100); return;
  }
  await Store.poll();   // queued on the node; trackIfaceOps() watches for completion each poll
}
function trackIfaceOps() {
  const now = Date.now();
  for (const key of Object.keys(Store.ifaceOp)) {
    const op = Store.ifaceOp[key];
    if (op.phase !== "busy") { if (op.until && now > op.until) delete Store.ifaceOp[key]; continue; }
    const cut = key.indexOf("|"); const node = key.slice(0, cut), iface = key.slice(cut + 1);
    const nrec = (Store.nodes || []).find(n => n.id === node) || {};
    const istate = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
    const down = !!istate.down, stopped = !!istate.stopped, notup = down || stopped;   // a stopped iface reports `stopped`, not `down`
    const cerr = (nrec.cmd_errors || {})[iface];
    const starting = (nrec.starting || []).includes(iface);   // panel requests still queued (cleared once the snapshot reflects)
    const stopping = (nrec.stopping || []).includes(iface);
    const restarting = (nrec.restarting || []).includes(iface);
    let done = null;   // { phase, err }
    if (op.verb === "apply") {                                 // up iface live-apply (no restart) → time-based
      if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (now - op.started > 6000) done = { phase: "ok" };   // node has had a sync to pick it up
    } else if (op.verb === "start") {                          // success once the iface is actually UP (not just "not down")
      if (!notup) done = { phase: "ok" };
      else if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (!starting && now - op.started > 8000) done = { phase: "fail", err: cerr || "the interface didn't come up" };
      else if (now - op.started > 20000) done = { phase: "fail", err: cerr || "timed out" };
    } else if (op.verb === "stop") {                           // success once it's actually down/stopped
      if (notup) done = { phase: "ok" };
      else if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (!stopping && now - op.started > 8000) done = { phase: "fail", err: cerr || "the interface didn't stop" };
      else if (now - op.started > 20000) done = { phase: "fail", err: cerr || "timed out" };
    } else {                                                   // RESTART of an up iface → done when the request clears + it's up
      if (down && cerr) done = { phase: "fail", err: cerr };
      else if (!restarting && now - op.started > 6000) done = down ? { phase: "fail", err: cerr || "didn't come back up" } : { phase: "ok" };
      else if (now - op.started > 18000) done = down ? { phase: "fail", err: cerr || "didn't come back up" } : { phase: "ok" };
    }
    if (done) {
      const ms = done.phase === "ok" ? 5000 : 10000;
      Store.ifaceOp[key] = { verb: op.verb, phase: done.phase, until: now + ms, err: done.err || "" };
      setTimeout(() => Store.apply(), 0);        // re-render NOW so the done tag shows on the current screen
      setTimeout(() => Store.apply(), ms + 100); // and again to clear it when it expires
    }
  }
}
function openEditIface(node, iface) { openModal(html`<${EditIfaceSheet} node=${node} iface=${iface}/>`); }
function openConnectionEdit(node, iface) { openModal(html`<${ConnectionEditSheet} node=${node} iface=${iface}/>`); }
// A node↔node mesh link (system interface). Mesh-managed (no create/delete/egress here) — mostly status;
// the only operator knob is whether this link can carry forwarded user traffic (reserved for Phase 2).
function ConnectionEditSheet({ node, iface }) {
  useStore();
  const meta = Store.ifaceMeta(node, iface) || {};
  const peer = meta.link_node;
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const prec = (Store.nodes || []).find(n => n.id === peer) || {};
  const [dialSrc, setDialSrc] = useState(meta.dial_src || "");
  const [dialEp, setDialEp] = useState(meta.dial_endpoint || "");
  const lk = nodeStale(node) ? "down" : (meta.handshake_age == null ? "connecting" : (meta.handshake_age < 180 ? "up" : "down"));
  const lkLabel = { up: "connected", connecting: "connecting", down: "down" }[lk];
  const proto = (meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg";
  const Row = (l, v) => html`<div class="row"><span class="k">${l}</span><span class="vv">${v}</span></div>`;
  const Cell = (l, v) => html`<div class="conn-cell"><span class="cl">${l}</span><span class="cv">${v}</span></div>`;
  const saveDial = () => {
    closeModal();
    mutate({
      key: "conn:" + node + "|" + peer,
      patch: () => {},
      call: () => api.connectionUpdate({ node, peer, dial_src: dialSrc, dial_endpoint: dialEp }),
    });
  };
  // user interfaces on THIS node whose traffic is forwarded out through this link (egress → peer)
  const allMeta = Store.describe[node] || {};
  const carried = Object.keys(allMeta).filter(k => !allMeta[k].system
    && allMeta[k].egress_mode === "forward" && allMeta[k].egress_node === peer)
    .map(k => ({ iface: k, subnet: allMeta[k].subnet, ip: allMeta[k].egress_ip }));
  // interfaces that SMART-route some destination categories out through this link (not the whole iface)
  const _listTitle = Object.fromEntries((Store.panelSettings?.custom_lists || []).map(l => [l.id, l.title]));
  const smartCarried = Object.keys(allMeta).filter(k => !allMeta[k].system && allMeta[k].egress_mode === "smart")
    .map(k => ({ iface: k, cats: (allMeta[k].routing || []).filter(r => r.action === "exit" && r.node === peer)
      .map(r => r.category === "custom" ? [...(r.domains || []), ...(r.cidrs || [])].join(", ") || "custom" : (SMART_CAT_LABEL[r.category] || _listTitle[r.category] || r.category)) }))
    .filter(x => x.cats.length);
  const ifBadge = k => html`<span class=${"tg tg-" + ((allMeta[k].awg_params && Object.keys(allMeta[k].awg_params).length) ? "awg" : "wg")}>${k}</span>`;
  const peerNm = html`<b style=${"color:" + Store.nodeColor(peer)}>${Store.nodeName(peer)}</b>`;
  return html`<${Sheet} title=${"Connection to " + Store.nodeName(peer)} width=${680} onClose=${closeModal}
      foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${saveDial}>Save</button></>`}>
    <div class="conncard">
      <div class="conncard-top">
        <span class=${"iftype " + proto}>System ${proto.toUpperCase()}</span>
        <span class=${"lkpill " + lk}><span class=${"lkdot " + lk}></span>${lkLabel}</span>
      </div>
      <div class="conn-grid">
        ${Cell("Node", html`<a href=${"#/node/" + encodeURIComponent(peer)} onClick=${closeModal}>${Store.nodeName(peer)}</a>`)}
        ${Cell("This end", meta.address || "—")}
        ${Cell("Endpoint", meta.peer_endpoint || "— (not dialed yet)")}
        ${Cell("Rate", rateCell(meta.rx_speed, meta.tx_speed))}
        ${meta.rx_bytes != null || meta.tx_bytes != null ? Cell("Total", xferCell(...dlul(meta.rx_bytes, meta.tx_bytes))) : null}
        ${Cell("Last handshake", meta.handshake_age != null ? seen(meta.handshake_age) + " ago" : "—")}
      </div>
    </div>
    <div class="row2" style="margin-top:14px">
      <div class="field"><label>Dial source IP <span class="faint" style="text-transform:none;letter-spacing:0">— ${Store.nodeName(node)}'s IP</span></label>
        <${NodeIpPick} ips=${nrec.ips || []} value=${dialSrc} onChange=${setDialSrc} auto="Auto (default route)"/></div>
      <div class="field"><label>Dial endpoint IP <span class="faint" style="text-transform:none;letter-spacing:0">— ${Store.nodeName(peer)}'s IP</span></label>
        <${NodeIpPick} ips=${prec.ips || []} value=${dialEp} onChange=${setDialEp} auto=${"Auto (" + Store.nodeName(peer) + "'s ingress)"}/></div>
    </div>
    <div class="hint" style="margin-top:-4px">Per-connection overrides: which of <b>${Store.nodeName(node)}</b>'s IPs dials out, and which of <b>${Store.nodeName(peer)}</b>'s IPs it dials to (overriding ${Store.nodeName(peer)}'s default ingress). Changing the endpoint re-connects this link automatically. Neither changes how routed traffic appears externally — that's the exit node's egress IP.</div>
    ${(carried.length || smartCarried.length) ? html`<div style="margin-top:16px">
      ${carried.length ? html`<div class="fwd-head"><span class="egb egb-cascade"><${Ic} i="cascade"/>cascade</span><span class="fwd-to">to</span>${peerNm}</div>
        <div class="fwd-ifaces">${carried.map(c => ifBadge(c.iface))}</div>` : null}
      ${smartCarried.length ? html`<div class="fwd-head" style=${carried.length ? "margin-top:14px" : ""}><span class="egb egb-smart"><${Ic} i="cascade"/>smart cascade</span><span class="fwd-to">to</span>${peerNm}</div>
        <div class="fwd-list">${smartCarried.map(s => html`<div class="fwd-row">${ifBadge(s.iface)} <span class="faint">(${s.cats.map(c => SMART_CAT_LABEL[c] || c).join(", ")})</span></div>`)}</div>` : null}
      <div class="hint" style="margin-top:16px">These interfaces' client traffic exits the fleet through <b>${Store.nodeName(peer)}</b>${smartCarried.length ? " — smart-routed by destination" : ""}.</div>
    </div>` : null}
    <div class="hint" style="margin-top:14px">This is a panel-managed mesh link to <b>${Store.nodeName(peer)}</b>. It's created and torn down automatically as nodes are added or removed. To route a user interface's traffic out through this node, set that interface's egress to <b>Forward to ${Store.nodeName(peer)}</b>.</div>
  <//>`;
}
function EditIfaceSheet({ node, iface }) {
  const meta = Store.ifaceMeta(node, iface) || {};
  const emode = ((Store.nodes || []).find(n => n.id === node) || {}).routing_mode || "kernel";   // for smart-rule validation (kernel = IP-only)
  const ep = meta.endpoint || "";
  const epHost = ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
  const [host, setHost] = useState(epHost);
  const [port, setPort] = useState(String(meta.desired_port || meta.listen_port || ""));
  const [dns, setDns] = useState((meta.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(meta.mtu || 1280));
  const [ka, setKa] = useState(String(meta.keepalive || 25));
  const [adv, setAdv] = useState(false);     // MTU / keepalive / DNS / AmneziaWG live under "Show advanced"
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const [eg, setEg] = useState(() => egressInit(meta));
  const isAwg = !!(meta.awg_params && Object.keys(meta.awg_params).length);
  const [awg, setAwg] = useState(() => Object.assign({}, meta.awg_params || {}));
  const setAwgK = (k, v) => setAwg(a => ({ ...a, [k]: v }));
  const ist = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
  const istopped = !!ist.stopped;            // operator stopped it (not a failure)
  const idown = !istopped && ist.down;       // genuinely down
  const notup = !!idown || istopped;         // either way: Save brings it up; footer offers Start
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const doSave = async () => {
    const body = { node, iface, endpoint_host: host.trim(), listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), ...egressBody(eg) };
    if (isAwg) body.awg_params = AWG_ORDER.reduce((o, k) => { const v = String(awg[k] == null ? "" : awg[k]).trim(); if (v) o[k] = v; return o; }, {});
    // down → "start" (real bring-up); up → "apply" live (no restart). Optimistic: flip the lifecycle +
    // close the modal(s) NOW so the detail page shows starting/applying the instant Save is pressed.
    const key = node + "|" + iface, verb = notup ? "start" : "apply";
    Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() };
    Store.apply(); closeAllModals();
    const fail = (m) => { Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 5000, err: m }; Store.apply(); setTimeout(() => Store.apply(), 5100); };
    const r = await api.ifaceUpdate(body);
    if (!r.ok) return fail(r.error || "save failed");
    if (notup) { const r2 = await api.ifaceStart({ node, iface }); if (!r2.ok) return fail(r2.error || "start failed"); }
    await Store.poll();   // trackIfaceOps drives busy → done
  };
  const save = () => {
    const ee = egressError(eg, emode); if (ee) return toast(ee, "err");
    const portChanged = port.trim() !== String(meta.desired_port || meta.listen_port || "");
    const epChanged = host.trim() !== epHost;
    if (portChanged || epChanged) {           // client-breaking → confirm first (the editor stays open behind it)
      const what = portChanged && epChanged ? "endpoint and listen port" : portChanged ? "listen port" : "endpoint";
      pushModal(html`<${ConfirmSheet} title=${"Change " + what + "?"} confirmLabel="Apply change" warn=${true}
        body=${"This reconfigures the interface on the node. Existing peers will NOT be able to connect using their old configs — you'll need to re-issue and re-distribute the QR codes. The interface's keys and peers are kept."}
        onConfirm=${() => { doSave(); }}/>`);
      return;
    }
    doSave();
  };
  return html`<${Sheet} title=${"Edit interface · " + iface} width=${720}
    foot=${html`<${Fragment}><button class="btn btn-ghost danger" onClick=${() => pushModal(html`<${DeleteIfaceSheet} node=${node} iface=${iface}/>`)}><${Ic} i="trash"/> Delete</button>
      ${notup
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title="Bring this interface up on the node" onClick=${() => { closeModal(); startOrRestartIface(node, iface, "start"); }}><${Ic} i="play"/> Start service</button>`
        : html`<${Fragment}><button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title="Take this interface down on the node (stays down until started)" onClick=${() => { closeModal(); startOrRestartIface(node, iface, "stop"); }}><${Ic} i="stop"/> Stop service</button><button class="btn btn-ghost" style="margin-left:8px" disabled=${busy} title="Bounce this interface's service on the node (down then up)" onClick=${() => { closeModal(); startOrRestartIface(node, iface, "restart"); }}><${Ic} i="refresh"/> Restart service</button><//>`}
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy || !!egressError(eg, emode)} title=${egressError(eg, emode) || ""} onClick=${save}>Save</button></>`}>
    <div class="iface-intro"><div>Changing the <b>endpoint</b> or <b>port</b> will break the existing clients' connections; you will need to re-distribute the configs / QR codes.</div></div>
    ${idown ? html`<div class="notice warn"><${Ic} i="warn"/><span>This interface is <b>down</b> on the node. Change the <b>Listen port</b> to a free one and <b>Save</b> — the panel will write the new port and restart the interface to bring it up.</span></div>` : null}
    ${meta.drift && meta.drift.public_key ? html`<div class="notice warn">
      <${Ic} i="warn"/><span><b>Server key changed on the node.</b> This interface's server keypair was rotated directly on the server, so <b>every client's existing config / QR for this interface no longer connects</b>. The node kept a backup of the original key.
        <div style="margin-top:9px"><button type="button" class="linkbtn" onClick=${async () => { const r = await api.ifaceRestore({ node, iface, key: "public_key" }); if (!r.ok) return toast(r.error || "Failed", "err"); closeAllModals(); await Store.poll(); toast("Restoring the original server key on the next sync.", "ok"); }}><b>Restore original key</b></button> <span class="faint">— reverts to the backed-up key; existing clients keep working, no re-distribution.</span></div>
        <div style="margin-top:6px"><button type="button" class="linkbtn danger" onClick=${() => pushModal(html`<${ConfirmSheet} title="Adopt the new server key?" confirmLabel="Adopt new key" warn=${true} body=${"Every client on this interface will stop connecting with their current config. You must re-issue and re-distribute every QR code / config. The original key is discarded."} onConfirm=${async () => { const r = await api.ifaceAdopt({ node, iface, key: "public_key" }); if (!r.ok) return toast(r.error || "Failed", "err"); closeAllModals(); await Store.poll(); toast("Adopted the new key — re-distribute the QR codes.", "ok"); }}/>`)}><b>Adopt new key</b></button> <span class="faint">— accept it; you'll re-distribute every QR.</span></div>
      </span></div>` : null}
    ${Object.entries(meta.drift || {}).filter(([k]) => k !== "public_key").length ? html`<div class="notice warn">
      <${Ic} i="warn"/><span><b>Edited directly on the server.</b> The panel paused pushing these so your change survives — Adopt to keep the server value, or Restore to re-apply the panel's:
      ${Object.entries(meta.drift).filter(([k]) => k !== "public_key").map(([k, v]) => html`<div style="margin-top:7px"><span class="mono">${k === "awg_params" ? "AWG params" : k}</span> on node = <span class="mono">${k === "awg_params" ? Object.entries(v).map(([a, b]) => a + "=" + b).join(" ") : v}</span>
        <button type="button" class="linkbtn" style="margin-left:8px" onClick=${async () => { const r = await api.ifaceAdopt({ node, iface, key: k }); if (!r.ok) return toast(r.error || "Failed", "err"); closeModal(); await Store.poll(); toast("Adopted the server value.", "ok"); }}>Adopt</button>
        · <button type="button" class="linkbtn" onClick=${async () => { const r = await api.ifaceRestore({ node, iface, key: k }); if (!r.ok) return toast(r.error || "Failed", "err"); closeModal(); await Store.poll(); toast("Restoring the panel value on the next sync.", "ok"); }}>Restore panel value</button></div>`)}
      </span></div>` : null}
    <div class="field ipk-field subnet-row"><label>Host tunnel IP</label><span class="ipk-val"><b>${(meta.address || "").split("/")[0] || meta.subnet || "—"}</b> <span class="faint">(set at creation — delete & recreate to change)</span></span></div>
    <div class="row2">
      <div class="field"><label>Endpoint host / IP</label>
        <${NodeIpPick} ips=${nrec.ips || []} value=${host} onChange=${setHost} auto="Auto (node's detected address)" customPlaceholder="IP or hostname — e.g. vpn.example.com"/>
        <div class="hint">What clients dial — config-facing only</div></div>
      <div class="field"><label>Listen port</label><input value=${port} onInput=${e => setPort(e.target.value)} placeholder=${String(meta.listen_port || "")}/><div class="hint">Applied to the node (currently ${meta.listen_port || "—"})</div></div>
    </div>
    <${EgressPicker} node=${node} value=${eg} onChange=${setEg}/>
    <button type="button" class="advtoggle" onClick=${() => setAdv(a => !a)}><span class="advcaret">${adv ? "▾" : "▸"}</span> Advanced settings</button>
    ${adv ? html`<${Fragment}>
      <div class="row2">
        <div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">Default for new peers</div></div>
        <div class="field"><label>Persistent keepalive (s)</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/><div class="hint">0 disables · blank = 25</div></div>
      </div>
      <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="https://8.8.8.8/dns-query, 1.1.1.1"/><div class="hint">Comma-separated</div></div>
      ${isAwg ? html`<div class="field"><label>AmneziaWG parameters</label>
        <div class="hint" style="margin:0 0 8px">Pushed to the node's interface and rendered into configs/QRs. Existing clients must re-import after a change.</div>
        <div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1", "I2", "I3", "I4", "I5"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span><input value=${awg[k] == null ? "" : awg[k]} onInput=${e => setAwgK(k, e.target.value)}/></label>`)}</div>`)}</div></div>` : null}
    <//>` : null}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── turn-proxy management (manage modal + onboard) — only on nodes reporting turn_manage ──
function openTurnManage(node, tp) { openModal(html`<${TurnManageSheet} node=${node} tp=${tp}/>`); }
function TurnManageSheet({ node, tp }) {
  const svc = tp.service;
  const lis = tp.listen || "";
  const lh = lis.includes(":") ? lis.slice(0, lis.lastIndexOf(":")) : lis;
  const lp = lis.includes(":") ? lis.slice(lis.lastIndexOf(":") + 1) : "";
  const con = tp.connect || "";
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ips = nrec.ips || [];
  const lInit = ips.includes(lh) ? lh : "__custom__";
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? lh : "");
  const [lport, setLport] = useState(lp);
  const snap = Store.stats[node] || {};
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_"), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // this proxy's fork is fixed here; a WireGuard-only fork can't front an AmneziaWG interface → hide awg ones
  const fork = turnFork(svc);
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const epIp = (() => { for (const b of Object.values(snap.interfaces || {})) { const ep = (b.meta || {}).endpoint || ""; if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep; } return ""; })();
  const conPort = con.includes(":") ? con.slice(con.lastIndexOf(":") + 1) : con;
  const match = ifaces.find(i => i.port === conPort);
  const [fwd, setFwd] = useState(match ? match.name : "__custom__");
  const [custom, setCustom] = useState(con || "127.0.0.1:");
  const [params, setParams] = useState(tp.params != null ? tp.params : (tp.wrap_key ? "-wrap-key " + tp.wrap_key : ""));
  const origParams = tp.params != null ? tp.params : (tp.wrap_key ? "-wrap-key " + tp.wrap_key : "");
  const [title, setTitle] = useState(tp.title || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const blocked = (Store.recon.nodeStatus[node] !== "live") || inProc(nrec.proc_status);   // node down / mid re-install / convert / update → disable every action here, same as the node-detail buttons
  const dis = busy || blocked;
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const isCustom = fwd === "__custom__";
  const lhost = ipPickerVal(lsel, lcustom);
  const installed = tp.version || "";
  const installing = !!tp.installing;
  const failed = !!tp.failed;
  const stopped = !!tp.stopped;
  const down = tp.running === false;
  const owner = turnOwner(svc);
  const [verChk, setVerChk] = useState(null);   // null | {checking} | {latest} | {err}
  const updateAvail = verChk && verChk.latest && installed && verChk.latest !== installed;
  const checkUpdate = async () => {
    setVerChk({ checking: true });
    try {
      const r = await fetch("https://api.github.com/repos/" + owner + "/releases/latest", { headers: { Accept: "application/vnd.github+json" } });
      if (!r.ok) throw new Error("GitHub " + r.status);
      const j = await r.json();
      const latest = String(j.tag_name || "").trim();
      setVerChk({ latest });
      if (!(latest && installed && latest !== installed)) setTimeout(() => setVerChk(null), 5000);   // up to date → show the tag for 5s, then revert
    } catch (e) { setVerChk({ err: String((e && e.message) || e) }); setTimeout(() => setVerChk(null), 5000); }   // no connection → 5s, then revert
  };
  const doReinstall = async (verb) => {
    setBusy(true); setMsg({ k: "work", t: verb.toLowerCase() + "…" });
    if (verb === "Update") turnUpdating[node + "|" + svc] = Date.now() + 120000;   // card shows "updating" (not "installing") while it applies
    const r = await api.turnReinstall({ node, service: svc, owner });
    if (!r.ok) { delete turnUpdating[node + "|" + svc]; return fail(r.error || "Request failed."); }
    closeModal(); await Store.poll();
    toast("Turn-proxy " + verb.toLowerCase() + " requested — applies on the node's next sync.", "ok");
  };
  const save = async () => {
    if (!lhost) return fail("Listen IP is required.");
    if (!/^\d+$/.test(lport.trim())) return fail("Listen port must be a number.");
    let connect;
    if (isCustom) { connect = custom.trim(); if (!/:\d+$/.test(connect)) return fail("Forward-to must be host:port."); }
    else { connect = "127.0.0.1:" + ifaces.find(i => i.name === fwd).port; }
    const newListen = lhost + ":" + lport.trim();
    // title-only change → OPTIMISTIC: a cosmetic panel-side label, so close immediately + save in the background
    // (no status, no node round-trip, the proxy keeps running). Other field changes go the proper pending route.
    const titleOnly = newListen === (tp.listen || "") && connect === (tp.connect || "") && params.trim() === origParams.trim();
    if (titleOnly) {
      closeModal();
      if (title.trim() === (tp.title || "")) return toast("No changes.", "ok");
      const r = await api.turnTitle({ node, service: svc, title: title.trim() });
      if (r.ok) { await Store.poll(); toast("Title saved — the proxy keeps running.", "ok"); }
      else toast(r.error || "Failed to save the title.", "err");
      return;
    }
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    const body = { node, service: svc, listen: newListen, connect, params: params.trim(), title: title.trim() };
    const r = await api.turnManage(body);
    if (!r.ok) return fail(r.error || "Request failed.");
    closeModal(); await Store.poll();
    toast("Turn-proxy update requested — applies on the node's next sync.", "ok");
  };
  const randKey = () => {
    const a = new Uint8Array(32); crypto.getRandomValues(a);
    copy(Array.from(a, b => b.toString(16).padStart(2, "0")).join(""), "Random 64-hex key copied — paste it into the parameters");
  };
  return html`<${Sheet} title=${html`${turnSheetTitle(turnFork(svc), title)}${installed ? html` <span class="sheet-ver">${installed}</span>` : ""}`} width=${660}
    foot=${html`<${Fragment}>
      <button class="btn btn-ghost danger" disabled=${dis} onClick=${() => openModal(html`<${DeleteTurnSheet} node=${node} service=${svc} label=${turnLabel(svc, lp)}/>`)}><${Ic} i="trash"/> Delete</button>
      ${stopped
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title="Start the service on the node" onClick=${() => { startTurn(node, svc); closeModal(); }}><${Ic} i="play"/> Start service</button>`
        : installing
        ? html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${true} title="Installing…"><${Ic} i="refresh"/> Reinstall service</button>`
        : (tp.running !== false && !failed)
        ? html`<${Fragment}>
            <button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title="Stop the service on the node (stays down until started)" onClick=${() => { stopTurn(node, svc); closeModal(); }}><${Ic} i="stop"/> Stop service</button>
            <button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title="Restart the service on the node" onClick=${() => { restartTurn(node, svc); closeModal(); }}><${Ic} i="refresh"/> Restart service</button>
          <//>`
        : html`<button class="btn btn-ghost" style="margin-left:8px" disabled=${dis} title="Re-download the binary and start the service on the node" onClick=${() => doReinstall("Reinstall")}><${Ic} i="refresh"/> Reinstall service</button>`}
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button>
      <button class="btn btn-primary" disabled=${dis} onClick=${save}>Save</button></>`}>
    ${blocked ? html`<div class="notice warn" style="margin-bottom:16px"><${Ic} i="warn"/><span>This node is busy or offline${nrec.proc_status ? html` (${PROC_LABEL[nrec.proc_status] || nrec.proc_status})` : ""} — turn-proxy actions are disabled until it's reporting again.</span></div>` : null}
    <div class="iface-intro">
      <div>Changing any field rewrites the unit's ExecStart on the node and restarts it.</div>
      <div>The parameters below are placed verbatim after <span class="mono">-connect</span> — wrap key, wrap mode, any flags the fork supports.</div>
    </div>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${turnFork(svc)} autocomplete="off"/></div>
    <div class="row2">
      <div class="field"><label>Listen IP</label>
        <${IpPicker} ips=${ips} sel=${lsel} setSel=${setLsel} custom=${lcustom} setCustom=${setLcustom} placeholder="203.0.113.7"/></div>
      <div class="field"><label>Listen port</label><input value=${lport} onInput=${e => setLport(e.target.value)} placeholder="57000"/></div>
    </div>
    ${lsel === "__custom__" && lhost && ips.length && !ips.includes(lhost) ? html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This isn't a detected address on the node. The proxy <b>binds</b> to this address — it must be a real IP on the server, or it dies with <span class="mono">bind: cannot assign requested address</span>.</span></div>` : null}
    <div class="field"><label>Forwards to</label>
      <select class="selwrap" value=${fwd} onChange=${e => setFwd(e.target.value)}>
        ${ifaces.map(i => html`<option value=${i.name}>${i.name} · 127.0.0.1:${i.port}</option>`)}
        <option value="__custom__">Custom IP:Port…</option>
      </select>
      ${hideAwg ? html`<div class="hint">${fork} is WireGuard-only — AmneziaWG interfaces are hidden (its client doesn't do AmneziaWG).</div>` : null}
    </div>
    ${isCustom ? html`<${Fragment}>
      <div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>
      <div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This forwards to a port with no managed interface behind it. Make sure a wg/awg interface is really listening there, or clients reach the proxy but get no tunnel.</span></div>
    <//>` : null}
    <div class="field"><label>Additional ExecStart parameters</label>
      <textarea class="ta mono" rows="4" value=${params} onInput=${e => setParams(e.target.value)} placeholder="-wrap-mode on -wrap-key <64 hex chars>" spellcheck="false"></textarea>
      <div class="hint">Free text appended after <span class="mono">-connect ip:port</span>. Changing the wrap key breaks every client using the old one. <button type="button" class="linkbtn" onClick=${randKey}>Copy a random 64-hex key</button></div>
    </div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
function DeleteTurnSheet({ node, service, label }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = "DELETE " + label;
  const ok = txt === phrase;
  const del = async () => {
    if (!ok || busy) return; setBusy(true);
    const r = await api.turnDelete({ node, service });
    if (!r.ok) { setBusy(false); return toast(r.error || "Failed.", "err"); }
    closeModal(); await Store.poll();
    toast("Turn-proxy removal requested — the node stops + removes it on its next sync.", "ok");
  };
  return html`<${Sheet} title=${"Delete turn-proxy · " + label}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-danger" disabled=${!ok || busy} onClick=${del}>Delete turn-proxy</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>This <b>stops, disables and removes</b> the turn-proxy service <b>${label}</b> on the node. Clients pointed at it stop connecting. This can't be undone. (To keep the service running and only unlink it from the panel, use <b>Disconnect</b>.)</span></div>
    <div class="field"><label>Type <span class="mono" style="text-transform:none">${phrase}</span> to confirm</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}
// the installable turn-proxy forks (owner repo + the fork's obfuscation flags — the node appends a
// fresh -wrap-key). Mirrors the installer's turn_repo_owner / turn_wrap_flags.
// each fork has a dark-mode `color` and a deeper `colorL` (light-mode default, legible on white).
const TURN_FORKS = [
  { id: "cacggghp", label: "cacggghp", owner: "cacggghp/vk-turn-proxy", wrap: "", color: "#5FB0E0", colorL: "#2C7EC0" },
  { id: "WINGS-N", label: "WINGS-N", owner: "WINGS-N/vk-turn-proxy", wrap: "-wrap-mode on", color: "#C98BE0", colorL: "#9B4FC7" },
  { id: "samosvalishe", label: "samosvalishe", owner: "samosvalishe/vk-turn-proxy", wrap: "-wrap", color: "#E0A85F", colorL: "#C07A1E" },
  { id: "kiper292", label: "kiper292", owner: "kiper292/vk-turn-proxy", wrap: "", color: "#6FD9A8", colorL: "#12A46B" },
  { id: "Moroka8", label: "Moroka8", owner: "Moroka8/vk-turn-proxy", wrap: "-wrap", color: "#E07A9A", colorL: "#C24468" },
  { id: "anton48", label: "anton48", owner: "anton48/vk-turn-proxy", wrap: "-wrap-srtp", color: "#D9CF5F", colorL: "#8E8420" },
];
// forks whose CLIENT is WireGuard-only — they can't front an AmneziaWG interface, so awg interfaces are hidden
// from their "Forwards to" picker. kiper292 = plain wireguard-go + a config parser that REJECTS awg params;
// anton48 (iOS) has no AmneziaWG fields at all. Everyone else supports awg (WINGS-N app-integrated; the sidecar
// forks relay UDP transparently so the standard AmneziaWG app handles it).
const TURN_WG_ONLY = new Set(["kiper292", "anton48"]);
function forkSupportsAwg(fork) { return !TURN_WG_ONLY.has(fork); }
// stable colour for a turn-proxy fork in the ACTIVE mode (peers connected via it get their badge tinted this);
// a Panel-settings override (turn_fork_colors[id] = {dark,light}) wins over the TURN_FORKS default.
function turnColor(label) {
  const ov = (Store.panelSettings && Store.panelSettings.turn_fork_colors) || {};
  const fk = TURN_FORKS.find(x => x.id === label);
  return pickThemed(ov[label], (fk && fk.color) || "#8FA8C0", (fk && fk.colorL) || "#5E7085");
}
// Drive EVERY `.tf-<fork>` element (the .tg-turn tags + .iftype.turn badges scattered across the SPA) from the
// picker override — those use a static CSS class, so without this the colour picker would only reach the handful of
// inline-styled sites. One injected <style> keeps the whole app in sync with turn_fork_colors after each poll.
function applyForkColors() {
  let el = document.getElementById("tf-colors");
  if (!el) { el = document.createElement("style"); el.id = "tf-colors"; (document.head || document.documentElement).appendChild(el); }
  el.textContent = TURN_FORKS.map(f => ".tf-" + f.id + "{--tfc:" + turnColor(f.id) + "}").join("");
}
// ---- palette overrides (Panel settings → Interfaces / Display) ----
// Interface protocol colours (wg / awg), peer-health colours (blocked / faulty) and the brand/theme colour
// are all operator-tunable. A Panel-settings override wins over these built-in defaults; nothing is hardcoded
// at the render sites — the wg/awg/blocked/faulty CSS classes and the --brand custom property are driven from
// here via applyThemeColors() after every poll, exactly like applyForkColors() does for the turn tags.
// Every operator-tunable colour carries a value PER light/dark mode ({dark,light}); the active mode's value is
// resolved by pickThemed(). Nothing is hardcoded at the render sites — the wg/awg CSS classes and the --brand
// property are injected by applyThemeColors() after every poll, exactly like applyForkColors() does for the tags.
const IFACE_COLOR_DEFAULTS = { wg: { dark: "#3FD89A", light: "#0E9E63" }, awg: { dark: "#1FC8D6", light: "#0E9BB0" } };
const NODE_COLOR_DEFAULT = { dark: "#5f7569", light: "#4A5C52" };   // fallback node colour when unset (per mode)
const NODE_CREATE_DEFAULT = { dark: "#34d399", light: "#12A46B" };  // a fresh node's starting colour
// normalize a possibly-legacy colour ({dark,light} | string | null) into a {dark,light} pair.
function toThemed(v, def) {
  if (v && typeof v === "object") return { dark: v.dark || def.dark, light: v.light || def.light };
  if (typeof v === "string" && v) return { dark: v, light: v };
  return { ...def };
}
const THEME_COLOR_DEFAULT = "#1FC8D6";        // brand cyan (--brand) — the dark-mode accent
const THEME_COLOR_LIGHT_DEFAULT = "#0E9BB0";  // a deeper cyan reads better on light surfaces
// resolve a themed colour: v may be {dark,light}, a legacy single string (used for both), or missing (→ defaults).
function pickThemed(v, defDark, defLight) {
  const light = resolvedTheme() === "light";
  if (v && typeof v === "object") return (light ? v.light : v.dark) || (light ? defLight : defDark);
  if (typeof v === "string" && v) return v;   // legacy single colour → same in both modes
  return light ? defLight : defDark;
}
function ifaceColor(type) {
  const ov = (Store.panelSettings && Store.panelSettings.iface_colors) || {};
  const k = (type || "").toLowerCase() === "awg" ? "awg" : "wg";
  return pickThemed(ov[k], IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light);
}
// perceived brightness (0–1) of a #rrggbb / #rgb colour — used to pick a contrasting ink for text on the brand.
function hexLum(h) {
  h = String(h).replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  return (isNaN(r) ? 0.5 : 0.299 * r + 0.587 * g + 0.114 * b);
}
function mixHex(a, b, t) {   // blend two hex colours (t=0→a, 1→b)
  const p = h => { h = String(h).replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join(""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  const A = p(a), B = p(b);
  return "#" + A.map((x, i) => Math.max(0, Math.min(255, Math.round(x + (B[i] - x) * t))).toString(16).padStart(2, "0")).join("");
}
function hexToHsl(hex) {
  let h = String(hex).replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; let hh = 0;
  if (d) { hh = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; hh /= 6; }
  const l = (mx + mn) / 2, s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  return [hh, s, l];
}
function hslToHex(h, s, l) {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h * 6) % 2 - 1)), m = l - c / 2;
  const seg = Math.floor(h * 6) % 6, r = [c, x, 0, 0, x, c][seg], g = [x, c, c, x, 0, 0][seg], b = [0, 0, x, c, c, x][seg];
  return "#" + [r, g, b].map(v => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}
// keep the theme accent legible against the active background by clamping LIGHTNESS in HSL (hue + saturation kept,
// so it stays a vivid darker/lighter shade of the SAME colour, not a washed grey). Only genuinely-out-of-band
// picks are moved; the picker snaps to this value too, so what you pick is what you see (WYSIWYG).
function clampBrand(hex, light) {
  if (!/^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(String(hex))) return hex;
  let [h, s, l] = hexToHsl(hex);
  if (light && l > 0.52) l = 0.44;
  else if (!light && l < 0.44) l = 0.54;
  else return hex;
  s = Math.max(s, 0.4);   // keep it saturated so the darker/lighter shade reads as the colour, not grey
  return hslToHex(h, s, l);
}
// the brand accent for the ACTIVE light/dark mode — each mode has its own picker (else its built-in default).
function themeColor() {
  const ps = Store.panelSettings || {};
  return resolvedTheme() === "light" ? (ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT)
                                     : (ps.theme_color || THEME_COLOR_DEFAULT);
}
// Drive the whole palette from the picker overrides: set --brand (and its lighter/chart siblings) on <html> so
// every var(--brand) site follows the theme colour, and inject one <style> overriding the static wg/awg/blocked/
// faulty classes (they don't read a custom property, so like the turn tags they need an explicit rule).
let _themeSig = null;
function applyThemeColors() {
  const theme = themeColor(), wg = ifaceColor("wg"), awg = ifaceColor("awg");
  const sig = [resolvedTheme(), theme, wg, awg].join("|");
  if (sig === _themeSig) return;   // nothing changed since last poll → skip the DOM write
  _themeSig = sig;
  const de = document.documentElement, cm = (c, p, m) => "color-mix(in srgb, " + c + " " + p + "%, " + m + ")";
  const brand = clampBrand(theme, resolvedTheme() === "light");   // legible against the active background
  de.style.setProperty("--brand", brand);
  de.style.setProperty("--brand-2", cm(brand, 70, "#fff"));   // the lighter brand accent
  de.style.setProperty("--tp-rx", brand);                      // throughput chart "down" series tracks the theme
  // text sitting ON the brand colour (primary buttons) must contrast with whatever colour was applied — dark ink on a
  // light brand, light ink on a dark one — so a dark theme colour doesn't make the button label invisible.
  de.style.setProperty("--brand-ink", hexLum(brand) > 0.55 ? "#04232A" : "#EAFBFF");
  let el = document.getElementById("theme-colors");
  if (!el) { el = document.createElement("style"); el.id = "theme-colors"; (document.head || document.documentElement).appendChild(el); }
  el.textContent =
    ".iftype.wg,.tg-wg{background:" + cm(wg, 14, "transparent") + ";color:" + wg + "}" +
    ".iftype.awg,.tg-awg{background:" + cm(awg, 15, "transparent") + ";color:" + awg + "}";
  applyFavicon(theme);
}
// Rebuild the browser-tab favicon (the indicator-LED mark) in the ACTIVE mode's accent colour, with a
// mode-matched centre so it reads on either tab background. Regenerated whenever the theme colour or mode
// changes (called from applyThemeColors, which fires exactly on those changes).
function applyFavicon(accent) {
  const centre = resolvedTheme() === "light" ? "#FFFFFF" : "#0A0E15";
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    + "<rect width='32' height='32' rx='8' fill='" + accent + "'/>"
    + "<circle cx='16' cy='14.5' r='5.5' fill='" + centre + "'/></svg>";
  let link = document.querySelector("link[rel~='icon']");
  if (!link) { link = document.createElement("link"); link.rel = "icon"; (document.head || document.documentElement).appendChild(link); }
  link.setAttribute("href", "data:image/svg+xml," + encodeURIComponent(svg));
}
// A label-less pair of colour pickers — DARK then LIGHT — for one themed colour. Hovering a swatch pops a preview
// of `sample(colour)` on that mode's real backdrop, so you see how it reads in that theme before committing. `val`
// is {dark,light} (a legacy string is accepted and shown for both); onChange receives the whole updated object.
function ThemedSwatch({ val, onChange, sample, title }) {
  const v = (val && typeof val === "object") ? val : { dark: val || "", light: val || "" };
  const cell = mode => html`<span class="tsw">
    <input type="color" class="tf-color" value=${v[mode]}
      title=${(title ? title + " · " : "") + (mode === "dark" ? "Dark theme" : "Light theme")}
      onInput=${e => onChange({ ...v, [mode]: e.target.value })}/>
    <span class=${"tsw-bub tsw-" + mode}>${sample(v[mode], mode)}<span class="tsw-cap">${mode}</span></span>
  </span>`;
  return html`<span class="tswrow">${cell("dark")}${cell("light")}</span>`;
}
// ---- light / dark / auto ----
// The header switch cycles auto → light → dark. "auto" follows the OS. The resolved mode drives
// <html data-theme>, which flips the structural palette (app.css :root[data-theme=light]); the brand
// accent is then re-injected per mode by applyThemeColors(). Persisted in localStorage so it survives reloads;
// an inline <head> script in index.html sets data-theme before first paint so there's no dark→light flash.
const THEME_MODES = ["auto", "light", "dark"];
function themeMode() { try { const m = localStorage.getItem("swg-theme"); return THEME_MODES.includes(m) ? m : "auto"; } catch (_) { return "auto"; } }
function prefersLight() { try { return matchMedia("(prefers-color-scheme: light)").matches; } catch (_) { return false; } }
function resolvedTheme(mode) { mode = mode || themeMode(); return mode === "auto" ? (prefersLight() ? "light" : "dark") : mode; }
function applyThemeMode() {
  document.documentElement.dataset.theme = resolvedTheme();
  _themeSig = null;            // force the accent injection to re-pick this mode's brand colour
  applyThemeColors();
  applyForkColors();           // turn-fork tints are per-mode too
}
function setThemeMode(mode) { try { localStorage.setItem("swg-theme", mode); } catch (_) {} applyThemeMode(); const b = document.getElementById("theme-btn"); if (b) paintThemeBtn(b); }
function cycleThemeMode() { const i = THEME_MODES.indexOf(themeMode()); setThemeMode(THEME_MODES[(i + 1) % THEME_MODES.length]); }
const THEME_ICON = {   // inline SVGs — the button shows the CURRENT mode. auto = the "contrast" glyph (a circle with one
  // half filled), the widely-used convention (GitHub et al.) for "follows the system" — clearer than a monitor.
  light: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  dark: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`,
  auto: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>`,
};
function paintThemeBtn(b) {
  const m = themeMode();
  b.innerHTML = THEME_ICON[m];
  b.title = m === "auto" ? "Theme: Auto (follows your system) — click for Light" : m === "light" ? "Theme: Light — click for Dark" : "Theme: Dark — click for Auto";
}
// re-resolve on OS scheme change while in Auto
try { matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (themeMode() === "auto") { applyThemeMode(); const b = document.getElementById("theme-btn"); if (b) paintThemeBtn(b); } }); } catch (_) {}
// master switch: turn-proxy UI is shown unless explicitly disabled in Panel settings → Turn proxies.
function turnEnabled() { return !(Store.panelSettings && Store.panelSettings.turn_enabled === false); }
// the forks offered in the "install a fork" picker — toggled in Panel settings → Turn proxies. Disabling a fork
// only hides it here; deployed proxies are untouched. Default (setting unset) = WINGS-N + anton48.
function enabledTurnForks() {
  const en = Store.panelSettings && Store.panelSettings.enabled_turn_forks;
  const set = new Set(en || ["WINGS-N", "anton48"]);
  return TURN_FORKS.filter(f => set.has(f.id));
}
const TURN_PEND = { install: "installing", manage: "applying", rotate: "rotating", delete: "deleting", onboard: "adopting", restart: "restarting", reinstall: "installing", start: "starting", stop: "stopping" };
// turn-proxy restart completion flash: when a queued 'restart' clears, show a green "restarted" tag 5s
const _turnRestartPend = {};   // "node|service" currently mid-restart (last poll)
const turnRestarted = {};      // "node|service" -> expiry ts for the green flash
const turnUpdating = {};        // "node|service" -> expiry ts; set on an "Update" click so the pending tag reads "updating" (not "installing")
const turnUpdateTarget = {};    // forkId -> {ver, until}: the version a fleet-wide Update is driving to, so the version bubble can flag converged nodes "updated" (independent of the transient turnCheck state)
const turnReady = {};          // "node|service" -> expiry ts for the blue "ready" flash (5s after it settles → then no tag)
const turnUpdatedFlash = {};   // "node|service" -> expiry ts: settle that FOLLOWED an Update click → green "updated" (not "ready")
const turnWasUpd = {};         // "node|service" -> was this card update-in-flight last render (→ flash "updated" when it settles)
const turnWasBusy = {};        // "node|service" -> was it pending/installing/op last render (settle → ready)
const turnWasInstalling = {};  // "node|service" -> was it INSTALLING last render (install end → "ready" optimistically, never bounce to pending)
const ifaceReady = {};         // "node|iface"   -> expiry ts for the green "ready" flash (5s after an interface comes up)
const ifaceWasBusy = {};       // "node|iface"   -> was it pending/creating last render
function trackTurnRestarts() {
  const seen = {};
  for (const n of (Store.nodes || [])) {
    for (const [svc, act] of Object.entries(n.turn_pending || {})) if (act === "restart") seen[n.id + "|" + svc] = true;
  }
  for (const k of Object.keys(_turnRestartPend)) if (!seen[k]) {   // was restarting, now cleared → done
    turnRestarted[k] = Date.now() + 5000; delete _turnRestartPend[k];
    setTimeout(() => Store.apply(), 0);      // re-render NOW so the "restarted" flash shows on the current screen
    setTimeout(() => Store.apply(), 5100);   // and again to clear it when the 5s window ends
  }
  for (const k of Object.keys(seen)) _turnRestartPend[k] = true;
}
// small ⓘ next to a pending/failed command — hover for the node's error, click to read it in full.
// `cls` tones it (e.g. "warn" = yellow for a non-fatal in-progress note); `title` overrides the modal heading.
function CmdErr({ err, cls, title }) {
  if (!err) return null;   // clickable error icon → details popup (no native tooltip caption)
  return html`<span class=${"cmderr" + (cls ? " " + cls : "")} onClick=${e => { e.stopPropagation(); openConfirm({ title: title || "Command failed on the node", log: err, confirmLabel: "Close" }); }}><${Ic} i="info"/></span>`;
}
// a status tag that, when it carries a node `msg`, makes the WHOLE tag clickable (opens the message) with
// a hover highlight + pointer — so the click target is the tag, not a tiny icon next to it.
function StatusTag({ cls, icon, label, msg, title }) {
  const ic = icon ? html`<${Ic} i=${icon}/>` : null;
  if (!msg) return html`<span class=${cls} title=${title || ""}>${ic}${label}</span>`;   // plain (non-error) tag keeps its hint
  // an error/detail tag: the WHOLE tag is clickable (→ popup), distinct hover, no native caption
  return html`<span class=${cls + " tg-click"}
    onClick=${e => { e.stopPropagation(); openConfirm({ title: title || "Details", log: msg, confirmLabel: "Close" }); }}>${ic}${label}</span>`;
}
async function cancelTurn(node, body) {
  const r = await api.turnCancel({ node, ...body });
  if (!r.ok) return toast(r.error || "Failed to cancel.", "err");
  await Store.poll(); toast("Pending turn-proxy request cancelled.", "ok");
}
async function restartTurn(node, service) {
  const r = await api.turnRestart({ node, service });
  if (!r.ok) return toast(r.error || "Failed to restart.", "err");
  await Store.poll(); toast("Restart requested — applies on the node's next sync.", "ok");
}
async function stopTurn(node, service) {
  const r = await api.turnStop({ node, service });
  if (!r.ok) return toast(r.error || "Failed to stop.", "err");
  await Store.poll(); toast("Stop requested — applies on the node's next sync.", "ok");
}
async function startTurn(node, service) {
  const r = await api.turnStart({ node, service });
  if (!r.ok) return toast(r.error || "Failed to start.", "err");
  await Store.poll(); toast("Start requested — applies on the node's next sync.", "ok");
}
function openSetupTurn(node) { openModal(html`<${SetupTurnSheet} node=${node}/>`); }
function SetupTurnSheet({ node }) {
  const FORKS = enabledTurnForks();           // only the operator-enabled forks appear in the install picker
  const [mode, setMode] = useState("new");   // new (install) | existing (adopt)
  const [fork, setFork] = useState((FORKS[0] || TURN_FORKS[0]).id);
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ips = nrec.ips || [];
  const snap = Store.stats[node] || {};
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_"), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // a WireGuard-only fork can't front an AmneziaWG interface → hide awg interfaces from its picker
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const epIp = (() => {   // the node's detected public IP — the proxy BINDS to listen, so it must be local
    for (const b of Object.values(snap.interfaces || {})) {
      const ep = (b.meta || {}).endpoint || "";
      if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
    }
    return "";
  })();
  const lInit = epIp ? (ips.includes(epIp) ? epIp : "__custom__") : (ips[0] || "__custom__");
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? epIp : "");
  const [lport, setLport] = useState(String(suggestPort(node, "turn")));
  const [fwd, setFwd] = useState(ifaces[0] ? ifaces[0].name : "__custom__");
  const [custom, setCustom] = useState("127.0.0.1:51820");
  const [title, setTitle] = useState("");
  const [wrapKey] = useState(randWrapKey);            // one fresh key, reused so a fork switch is deterministic
  const dflParams = fk => fk.wrap ? (fk.wrap + " -wrap-key " + wrapKey) : "";
  const [params, setParams] = useState(dflParams(FORKS[0] || TURN_FORKS[0]));
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const isCustom = fwd === "__custom__";
  const f = TURN_FORKS.find(x => x.id === fork) || FORKS[0] || TURN_FORKS[0];
  const lhost = ipPickerVal(lsel, lcustom);
  const pickFork = id => {   // re-default params for the new fork only if the field is still an untouched default
    const cf = TURN_FORKS.find(x => x.id === fork) || TURN_FORKS[0];
    const nf = TURN_FORKS.find(x => x.id === id) || TURN_FORKS[0];
    if (params === dflParams(cf)) setParams(dflParams(nf));
    // switching to a WG-only fork while an awg interface is selected → move to the first WG interface (or custom)
    if (!forkSupportsAwg(id) && fwd !== "__custom__" && !allIfaces.some(i => i.name === fwd && !i.awg)) {
      const firstWg = allIfaces.find(i => !i.awg); setFwd(firstWg ? firstWg.name : "__custom__");
    }
    setFork(id);
  };
  const randKey = () => copy(randWrapKey(), "Random 64-hex key copied — paste it into the parameters");
  const save = async () => {
    if (mode === "existing") {
      const p = path.trim();
      if (!p.startsWith("/") || !p.endsWith(".service")) return fail("Enter the absolute path to the .service unit.");
      setBusy(true); setMsg({ k: "work", t: "requesting…" });
      const r = await api.turnOnboard({ node, path: p });
      if (!r.ok) return fail(r.error || "Request failed.");
      closeModal(); await Store.poll();
      return toast("Turn-proxy adopt requested — the node reads it on its next sync.", "ok");
    }
    if (!lhost) return fail("Listen IP is required.");
    if (!/^\d+$/.test(lport.trim())) return fail("Listen port must be a number.");
    let connect;
    if (isCustom) { connect = custom.trim(); if (!/:\d+$/.test(connect)) return fail("Forwards-to must be host:port."); }
    else { connect = "127.0.0.1:" + ifaces.find(i => i.name === fwd).port; }
    setBusy(true); setMsg({ k: "work", t: "installing… (the node downloads the binary, up to ~2 min)" });
    const r = await api.turnInstall({ node, fork: f.id, owner: f.owner, wrap_flags: f.wrap,
      listen: lhost + ":" + lport.trim(), connect, title: title.trim(), params: params.trim() });
    if (!r.ok) return fail(r.error || "Request failed.");
    // optimistic: show the FULL card (entered data) dimmed + "installing" right away — keyed by the service
    // the panel returns (vk-turn-proxy-<fork>-<port>), so it self-clears when the node reports the real proxy.
    const svc = (r.data && r.data.service) || ("vk-turn-proxy-" + f.id + "-" + lport.trim());
    Store.turnNew[node + "|" + svc] = { listen: lhost + ":" + lport.trim(), connect, title: title.trim(), at: Date.now() };
    closeModal(); Store.apply(); await Store.poll();
    toast("Turn-proxy install requested — the node downloads + starts it on its next sync.", "ok");
  };
  return html`<${Sheet} title=${mode === "new" ? turnSheetTitle(f.label, title) : "Adopt turn-proxy"}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy || (mode === "new" && !FORKS.length)} onClick=${save}>${mode === "existing" ? "Adopt" : "Install"}</button></>`}>
    <div class="field"><label>Source</label>
      <div class="chiprow proto3">
        <button class=${"chip c-awg" + (mode === "new" ? " on" : "")} onClick=${() => setMode("new")}>Install a fork</button>
        <button class=${"chip c-ex" + (mode === "existing" ? " on" : "")} onClick=${() => setMode("existing")}>Adopt existing service</button>
      </div></div>
    ${mode === "existing" ? html`<${Fragment}>
      <div class="iface-intro big">
        <div>Adopt a turn-proxy already running as a systemd service on this node.</div>
        <div>The node reads the unit's ExecStart (listen, forwards-to, wrap key) on its next sync and it shows up here.</div>
      </div>
      <div class="field"><label>Service unit path</label><input autofocus value=${path} onInput=${e => setPath(e.target.value)} placeholder="/etc/systemd/system/vk-turn-proxy-...service" autocomplete="off"/></div>
    <//>` : html`<${Fragment}>
      <div class="row2">
        <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${f.label} autocomplete="off"/></div>
        <div class="field"><label>Fork</label>
          <select class="selwrap" value=${fork} disabled=${!FORKS.length} onChange=${e => pickFork(e.target.value)}>
            ${FORKS.map(x => html`<option value=${x.id}>${x.label}${x.wrap ? "" : " · no obfuscation"}</option>`)}
          </select>
          <div class="hint">${FORKS.length ? f.owner : "No forks enabled — turn them on in Panel settings → Turn proxies."}</div></div>
      </div>
      <div class="row2">
        <div class="field"><label>Listen IP</label>
          <${IpPicker} ips=${ips} sel=${lsel} setSel=${setLsel} custom=${lcustom} setCustom=${setLcustom} placeholder="203.0.113.7"/>
          <div class="hint">An address on this server — the proxy binds to it</div></div>
        <div class="field"><label>Listen port</label><input value=${lport} onInput=${e => setLport(e.target.value)} placeholder="56000"/></div>
      </div>
      ${lsel === "__custom__" && lhost && ips.length && !ips.includes(lhost) ? html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This isn't a detected address on the node. The proxy <b>binds</b> to it, so it must be a real IP on the server — otherwise it dies with <span class="mono">bind: cannot assign requested address</span>.</span></div>` : null}
      <div class="field"><label>Forwards to</label>
        <select class="selwrap" value=${fwd} onChange=${e => setFwd(e.target.value)}>
          ${ifaces.map(i => html`<option value=${i.name}>${i.name} · 127.0.0.1:${i.port}</option>`)}
          <option value="__custom__">Custom IP:Port…</option>
        </select>
        ${hideAwg ? html`<div class="hint">${fork} is WireGuard-only — AmneziaWG interfaces are hidden (its client doesn't do AmneziaWG).</div>` : null}
      </div>
      ${isCustom ? html`<div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>` : null}
      <div class="field"><label>Additional ExecStart parameters</label>
        <textarea class="ta mono" rows="3" value=${params} onInput=${e => setParams(e.target.value)} placeholder="-wrap-mode on -wrap-key <64 hex chars>" spellcheck="false"></textarea>
        <div class="hint">Appended after <span class="mono">-connect ip:port</span>. ${f.wrap ? "Pre-filled with this fork's obfuscation flags + a fresh key." : "This fork has no obfuscation flags."} <button type="button" class="linkbtn" onClick=${randKey}>Copy a random 64-hex key</button></div>
      </div>
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ═════════════════════════ SCREEN: PEERS (by node) ═════════════════════════
const peersView = { node: "", iface: "", q: "", sort: "status", dir: -1 };
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
// interface type for the grouped dropdowns — awg if any node's interface of this name carries AmneziaWG params
function ifaceIsAwg(iface) {
  for (const n of Object.keys(Store.describe || {})) { const m = (Store.describe[n] || {})[iface]; if (m && Object.keys(m.awg_params || {}).length) return true; }
  return false;
}
// interface-filter dropdown values: "" / "*" = all · "*awg" / "*wg" = all of one type · else an exact iface name.
const ifaceIsAll = v => !v || v === "*" || v === "*awg" || v === "*wg";   // an aggregate (multi-iface) filter value
function ifaceMatch(iface, filter) {                                       // does an interface name pass the filter value?
  if (!filter || filter === "*") return true;
  if (filter === "*awg") return ifaceIsAwg(iface);
  if (filter === "*wg") return !ifaceIsAwg(iface);
  return iface === filter;
}
// <option>s for an interface dropdown: "All AmneziaWG" / "All WireGuard" shortcuts, then AmneziaWG / WireGuard
// optgroups of the individual interfaces (used everywhere we list ifaces; the caller renders "All interfaces").
function ifaceOptGroups(names) {
  const awg = names.filter(ifaceIsAwg), wg = names.filter(n => !ifaceIsAwg(n));
  return html`${awg.length ? html`<option value="*awg">All AmneziaWG</option>` : null}${wg.length ? html`<option value="*wg">All WireGuard</option>` : null}${awg.length ? html`<optgroup label="AmneziaWG">${awg.map(i => html`<option value=${i}>${i}</option>`)}</optgroup>` : null}${wg.length ? html`<optgroup label="WireGuard">${wg.map(i => html`<option value=${i}>${i}</option>`)}</optgroup>` : null}`;
}
// column sort keys for the shared peer grid — every header is clickable (order-by). Callers hold sort/dir in
// their view-state and sort BEFORE pagination via sortPeerRows(); PeerGrid renders the clickable headers.
const _ipKey = ip => String(ip || "").split(/[./]/).map(n => String((+n) || 0).padStart(3, "0")).join(".");
// status order for the clickable "Status" column — online FIRST (STATUS_RANK ranks ready above online, which is
// right for the Peers-screen default grouping but backwards for an order-by; here online is the top of the sort).
const PEER_STATUS_RANK = { online: 10, faulty: 9, ready: 8, blocked: 7, partial: 6, pending: 5, creating: 5, rotating: 5, unassigned: 3, unknown: 2, dangling: 1 };
const PEER_SORT = {
  status: ({ p, t }) => PEER_STATUS_RANK[t.status || p.status] || 0,
  server: ({ t }) => Store.nodeName(t.node).toLowerCase() + "|" + t.iface,
  user: ({ p }) => { const u = p.user_id ? Store.user(p.user_id) : null; return u ? u.name.toLowerCase() : "￿"; },
  title: ({ p }) => String(p.title || p.name || "").toLowerCase(),
  address: ({ t }) => _ipKey(t.ip),
  endpoint: ({ t }) => ((t.observed && t.observed.endpoint) || "￿").toLowerCase(),
  online: ({ t }) => (t.observed && t.observed.handshake_age != null) ? t.observed.handshake_age : Infinity,
  rate: ({ t }) => t.observed ? (t.observed.rx_speed || 0) + (t.observed.tx_speed || 0) : 0,
  total: ({ t }) => t.observed ? (t.observed.rx_bytes || 0) + (t.observed.tx_bytes || 0) : 0,
};
const PEER_DEFDIR = { status: -1, rate: -1, total: -1, online: 1, title: 1, user: 1, server: 1, address: 1, endpoint: 1 };   // first-click direction per column
function sortPeerRows(rows, sort, dir) {
  const key = PEER_SORT[sort] || PEER_SORT.status;
  return rows.slice().sort((a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1)
    || String(a.p.title || a.p.name || "").localeCompare(String(b.p.title || b.p.name || "")));
}
function peerSortBy(view, col) { if (view.sort === col) view.dir = -view.dir; else { view.sort = col; view.dir = PEER_DEFDIR[col] || 1; } }
// Pager scroll: turning to the NEXT page brings the grid's TOP just under the sticky header; PREV brings its BOTTOM
// into view — so a page turn always lands you at the fresh edge of the list. `e` targets the clicked pager button;
// the grid is the element right before the .pager. Deferred two frames so the new page has rendered/re-sized.
function pageScroll(e, dir) {
  const pager = e.currentTarget && e.currentTarget.closest(".pager");
  const grid = pager && pager.previousElementSibling;
  if (!grid) return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const r = grid.getBoundingClientRect();
    // Next → land the grid top well below the toolbar (scroll a bit further up); Prev → keep the grid bottom
    // clear of the pager/viewport edge (scroll a bit further down). Extra margin = more context on either side.
    const y = dir > 0 ? window.scrollY + r.top - 120 : window.scrollY + r.bottom - window.innerHeight + 64;
    window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
  }));
}
// `live` (the Live monitor): status is the animated connDot (not the pill badge), an Endpoint column is added
// (turn peers show "Local turn-proxy"), the row actions + assign-to-user dropdown are dropped (read-only).
// `sort`/`dir`/`onSort` make every column header a clickable order-by.
function PeerGrid({ rows, agg, node, iface, shownByPeer, q, blocked, hideUser, loc, live, sort, dir, onSort }) {
  const arrow = c => sort === c ? (dir < 0 ? "↓ " : "↑ ") : "";
  const th = (c, label, cls) => onSort ? html`<th class=${(cls ? cls + " " : "") + "clk"} onClick=${() => onSort(c)}>${arrow(c)}${label}</th>` : html`<th class=${cls || ""}>${label}</th>`;
  return html`<div class="tablewrap"><table class=${"peergrid" + (live ? " live" : "") + (loc ? " loc" : "")}>
    <thead><tr>${th("status", live ? "" : "Status", "h-status")}${loc
      ? html`${hideUser ? null : th("user", "User", "h-user")}${th("title", "Title", "h-title")}${live ? th("endpoint", "Endpoint", "h-ep") : null}${th("address", "Address", "h-addr")}${th("server", "Node", "h-node")}`
      : html`${hideUser ? null : th("user", "User", "h-user")}${th("title", "Title", "h-title")}${agg ? th("server", node === "*" ? "Node" : "IF", "h-node") : null}${th("address", "Address", "h-addr")}${live ? th("endpoint", "Endpoint", "h-ep") : null}`
    }${th("online", "Online", "h-online")}${th("rate", "Rate ↓↑", "h-rate")}${th("total", "Total ↓↑", "h-total")}${live ? null : html`<th class="h-acts"></th>`}</tr></thead>
    <tbody>
      ${rows.length ? rows.map(({ p, t }) => {
        const obs = t.observed;
        const u = p.user_id ? Store.user(p.user_id) : null;
        const hidden = p.targets.filter(d => !(shownByPeer[p.id] || new Set()).has(tkey(d.node, d.iface)));   // this peer's deployments not shown in the grid
        const fresh = Store.recentlyCreated[p.id] && (Date.now() - Store.recentlyCreated[p.id] < 2500);   // just-created → one-shot glow
        return html`<tr key=${p.id + "|" + tkey(t.node, t.iface)} class=${"clk" + (fresh ? " pcreate" : "")} onClick=${() => openPeerView(p.id, t.node, t.iface)}>
          <td data-label="Status" class="c-status">${(() => {
            const ifaceB = loc ? gridIfaceTag(t) : null;
            if (!live) return html`${gridStatusBadge(t, p)}${ifaceB}`;
            const dot = html`<span class=${"condot " + (t.status === "faulty" ? "faulty" : t.status === "blocked" ? "blocked" : t.online ? "on" : "off")}></span>`;
            // faulty / blocked → the "why" bubble on hovering the dot OR the interface badge (same as the peer-grid badge)
            if (t.status === "faulty" || t.status === "blocked") {
              return html`<span class="turnwrap">${dot}${ifaceB}
                <span class="turnbub statusbub"><span class="statusbub-h" style="color:var(--fault)"><${Ic} i="warn"/>${t.status === "blocked" ? "Blocked" : "Faulty"}</span>${STATUS_REASON[t.status]}</span></span>`;
            }
            return html`<span class=${"condot " + (t.online ? "on" : "off")} title=${t.online ? "online" : "offline"}></span>${ifaceB}`;
          })()}</td>
          ${(() => {
            const titleCell = html`<td data-label="Title" class="c-name">${p.title ? html`<b>${p.title}</b>` : html`<span class="faint">untitled</span>`}</td>`;
            const addrCell = html`<td data-label="Address"><span class="addr">${t.ip || "—"}</span>${hidden.length ? html`<${DepBadge} others=${hidden}/>` : null}</td>`;
            const epCell = html`<td data-label="Endpoint">${endpointCell(t)}</td>`;
            const nodeCell = html`<td data-label="Node"><div class="srvcell"><span class="srv-name" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></div></td>`;
            const userCell = hideUser ? null : html`<td data-label="User" class=${"usercell" + (u ? " linked" : "")} onClick=${u ? (e => { e.stopPropagation(); go("#/user/" + encodeURIComponent(u.id)); }) : (e => e.stopPropagation())}>
              ${u ? html`<a class="namecell" href=${"#/user/" + encodeURIComponent(u.id)} onClick=${e => e.stopPropagation()}><span>${u.name}</span><${Ic} i="user"/></a>`
                  : (live ? html`<span class="faint">unassigned</span>` : html`<div class="assigncell"><${UserCombo} onPick=${uid => assignPeer(p, uid)}/><${RowError} k=${"peer:" + p.id}/></div>`)}</td>`;
            // embedded / live-peers: Status · [User] · Title · [Endpoint (live)] · Address · Node — iface badge sits by the status
            if (loc) return html`${userCell}${titleCell}${live ? epCell : null}${addrCell}${nodeCell}`;
            const srvAgg = agg ? html`<td data-label=${node === "*" ? "Node" : "IF"}><div class="srvcell">
              ${node === "*" ? html`<span class="srv-name" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>` : null}
              ${ifaceIsAll(iface) ? gridIfaceTag(t) : null}
            </div></td>` : null;
            return html`${userCell}${titleCell}${srvAgg}${addrCell}${live ? epCell : null}`;
          })()}
          <td data-label="Online" class="c-online"><span class="when">${seen(obs ? obs.handshake_age : null)}</span></td>
          <td data-label="Rate">${rateCell(obs ? obs.rx_speed : 0, obs ? obs.tx_speed : 0)}</td>
          <td data-label="Total">${xferCell(...dlul(obs ? obs.rx_bytes : 0, obs ? obs.tx_bytes : 0))}</td>
          ${live ? null : html`<td data-label="" class="rowacts" onClick=${e => e.stopPropagation()}>
            <button class="iconbtn" title="Show QR / configs" onClick=${() => openPeerConfigs(p)}><${Ic} i="qr"/></button>
            <button class="iconbtn" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Edit peer"} onClick=${() => openEditPeer(p, { node: t.node, iface: t.iface })}><${Ic} i="pencil"/></button>
            ${p.unassigned
              ? html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Delete peer"} onClick=${() => confirmDeletePeer(p)}><${Ic} i="trash"/></button>`
              : html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Unassign peer"} onClick=${() => confirmUnassign(p)}><${Ic} i="link"/></button>`}
            <${RowError} k=${"peer:" + p.id}/>
          </td>`}</tr>`;
      }) : html`<tr><td colspan=${((agg || loc) ? 9 : 8) - (hideUser ? 1 : 0)} class="empty"><b>${q ? "No matches" : "No peers here"}</b>${q ? "Try a different search." : (!agg ? "Create one, or copy an existing peer onto this interface." : "No peers deployed yet.")}</td></tr>`}
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

  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();   // user ifaces only — mesh links (swg_*) are not peer-bearing
  const ifaceOpts = node === "*" ? allIfaces : Store.userIfacesOf(node);
  // default interface: aggregate when several exist (or all-servers); else the only one.
  const ifaceDefault = () => (node === "*" || ifaceOpts.length > 1) ? "*" : (ifaceOpts[0] || "");
  if (!peersView.iface) peersView.iface = ifaceDefault();
  if (!ifaceIsAll(peersView.iface) && !ifaceOpts.includes(peersView.iface)) peersView.iface = ifaceDefault();
  const iface = peersView.iface;
  const agg = node === "*" || ifaceIsAll(iface);
  const itype = (!agg && Store.ifaceMeta(node, iface) && Object.keys(Store.ifaceMeta(node, iface).awg_params || {}).length) ? "awg" : "wg";

  const q = peersView.q.toLowerCase();
  // one row per matching (peer, target) deployment, so a fleet-wide view shows where each peer lives.
  let rows = [];
  for (const p of Store.recon.peers) for (const t of p.targets) {
    if (node !== "*" && t.node !== node) continue;
    if (!ifaceMatch(t.iface, iface)) continue;
    rows.push({ p, t });
  }
  if (q) rows = rows.filter(({ p, t }) => searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface, q));
  rows = sortPeerRows(rows, peersView.sort, peersView.dir);
  // which of each peer's deployments are actually visible as rows here — so a row can flag the rest
  // (filtered out by server/interface or search) with a "+N" the operator can hover/tap.
  const shownByPeer = {};
  for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  const orphans = !agg ? Store.recon.orphans.filter(o => o.node === node && o.iface === iface) : [];

  // pagination — default 20/page; the +N badge still reflects ALL rows (shownByPeer above), not the page.
  const pageSize = peersView.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(1, peersView.page || 1), totalPages);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { peersView.page = p; force(x => x + 1); };

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <div class="search"><${Ic} i="search"/><input placeholder="Search title, user, address…" value=${peersView.q}
        onInput=${e => { peersView.q = e.target.value; peersView.page = 1; force(x => x + 1); }}/></div>
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; peersView.page = 1; force(x => x + 1); }}>
        ${multiServer ? html`<option value="*">All nodes</option>` : null}
        ${fleet.map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; peersView.page = 1; force(x => x + 1); }}>
        ${(node === "*" || ifaceOpts.length > 1) ? html`<option value="*">All interfaces</option>` : null}
        ${ifaceOpts.length ? ifaceOptGroups(ifaceOpts) : (node === "*" ? null : html`<option value="">no interfaces reported</option>`)}
      </select>
      <span class="grow"></span>
      <button class="btn btn-primary" onClick=${() => openCreatePeer(agg ? {} : { node, iface })}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
    </div>

    <div class="section-title"><h2>${agg ? "Peers" : "Peers on"}</h2><span class="tags">
      ${node !== "*" ? html`<${Tag} kind="iface" label=${Store.nodeName(node) || "—"} color=${Store.nodeColor(node)}/>` : null}
      ${iface !== "*" && iface ? html`<${Tag} kind=${itype} label=${iface}/>` : null}
    </span><span class="count">${rows.length}</span></div>
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${peersView.q} sort=${peersView.sort} dir=${peersView.dir} onSort=${c => { peerSortBy(peersView, c); peersView.page = 1; force(x => x + 1); }}/>
    ${rows.length > 20 ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { peersView.pageSize = +e.target.value; peersView.page = 1; force(x => x + 1); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select>
      </label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)} of ${rows.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>Next ›</button>
    </div>` : null}

    ${orphans.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--orphan)">Unmanaged here</h2></div>
      <div class="tablewrap"><table><tbody>${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}</tbody></table></div>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: LIVE (Peers / Users monitor) ═════════════════════════
// Read-only over the enriched snapshot. A Peers↔Users toggle switches between the shared PeerGrid (in `live`
// mode — dot status, endpoint column, no controls) and the shared UserRow list (also `live`). Node/interface
// dropdowns + a global search + an Online filter narrow both. State lives in module scope so the 5s poll
// never loses it; Preact keeps scroll + updates cells in place.
const connView = { mode: "peers", node: "", iface: "", q: "", online: false, page: 1, pageSize: 20, sort: "status", dir: -1, usort: "status", udir: -1 };
function ConnectionsScreen() {
  useStore();
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const reset = () => { connView.page = 1; bump(); };   // any filter/mode change → back to page 1
  const mode = connView.mode, q = connView.q.toLowerCase();
  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();
  const ifaceOpts = connView.node ? Store.userIfacesOf(connView.node) : allIfaces;
  if (!ifaceIsAll(connView.iface) && !ifaceOpts.includes(connView.iface)) connView.iface = "";
  const setMode = m => { connView.mode = m; reset(); };
  const setPage = p => { connView.page = p; bump(); };
  // shared pager (both modes) — mirrors the Peers/Users screens
  const pager = (total) => {
    const pageSize = connView.pageSize || 20, totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, connView.page || 1), totalPages);
    return total > pageSize ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { connView.pageSize = +e.target.value; reset(); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${() => setPage(page - 1)}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${() => setPage(page + 1)}>Next ›</button>
    </div>` : null;
  };
  const paginate = (list) => { const pageSize = connView.pageSize || 20, totalPages = Math.max(1, Math.ceil(list.length / pageSize));
    const page = Math.min(Math.max(1, connView.page || 1), totalPages); return list.slice((page - 1) * pageSize, page * pageSize); };

  const toolbar = html`<div class="toolbar">
    <div class="pmode">
      <button class=${"pm-opt pm-peers" + (mode === "peers" ? " on" : "")} onClick=${() => setMode("peers")}>Peers</button>
      <button class=${"pm-opt pm-users" + (mode === "users" ? " on" : "")} onClick=${() => setMode("users")}>Users</button>
    </div>
    <div class="search"><${Ic} i="search"/><input placeholder=${mode === "users" ? "Search users, tags, peers…" : "Search peer, user, endpoint, IP…"} value=${connView.q} onInput=${e => { connView.q = e.target.value; reset(); }}/></div>
    <select class="selwrap" value=${connView.node} onChange=${e => { connView.node = e.target.value; connView.iface = ""; reset(); }}>
      <option value="">All nodes</option>${(Store.nodes || []).map(n => html`<option value=${n.id}>${n.name}</option>`)}
    </select>
    <select class="selwrap" value=${connView.iface} onChange=${e => { connView.iface = e.target.value; reset(); }}>
      <option value="">All interfaces</option>${ifaceOptGroups(ifaceOpts)}
    </select>
    <button class=${"onlbtn" + (connView.online ? " on" : "")} title="Show only online connections" onClick=${() => { connView.online = !connView.online; reset(); }}>Online</button>
  </div>`;

  if (mode === "users") {
    // filter the user LIST by node/iface (has a peer there) + search + Online; the expanded grid still shows ALL peers
    const users = sortUsers(Store.recon.users.filter(u => userMatchesQ(u, q) && userOnNodeIface(u, connView.node, connView.iface) && (!connView.online || u.onlineCount > 0)), connView.usort, connView.udir);
    return html`<div class="screen">
      ${toolbar}
      <div class="section-title"><h2 class="live-users">Users</h2><span class="count">${users.length}</span></div>
      ${users.length ? html`<${Fragment}>
        <${UsersHeader} live=${true} sort=${connView.usort} dir=${connView.udir} onSort=${c => { sortColToggle(connView, "usort", "udir", c, USER_DEFDIR); connView.page = 1; bump(); }}/>
        <div class="urows">${paginate(users).map(u => html`<${UserRow} key=${u.id} user=${u} live=${true} onlineOnly=${connView.online} q=${q}/>`)}</div>
      <//>`
        : html`<div class="empty"><b>${connView.online ? "No users online" : "Nothing matches"}</b>${connView.online ? "No user has an online peer right now." : "Clear the filters."}</div>`}
      ${pager(users.length)}
    </div>`;
  }

  // peers mode — one row per OBSERVED deployment (a live connection), rendered via the shared PeerGrid in live mode
  let rows = [];
  for (const p of Store.recon.peers) for (const t of p.targets) {
    if (!t.observed) continue;                                         // only present-on-node connections
    if (connView.node && t.node !== connView.node) continue;
    if (!ifaceMatch(t.iface, connView.iface)) continue;
    if (connView.online && !t.online) continue;
    rows.push({ p, t });
  }
  if (q) rows = rows.filter(({ p, t }) => { const u = p.user_id ? Store.user(p.user_id) : null; const o = t.observed || {};
    return searchMatch((p.title || "") + " " + (p.name || "") + " " + (u ? u.name : "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface + " " + (o.endpoint || ""), q); });
  rows = sortPeerRows(rows, connView.sort, connView.dir);
  const shownByPeer = {};
  for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  const onlineCount = rows.filter(r => r.t.online).length;

  return html`<div class="screen">
    ${toolbar}
    <div class="section-title"><h2 class="live-peers">Peers</h2><span class="count">${rows.length} shown · ${onlineCount} online</span></div>
    ${rows.length
      ? html`<${PeerGrid} rows=${paginate(rows)} agg=${true} node="*" iface="*" shownByPeer=${shownByPeer} q=${connView.q} live=${true} loc=${true} hideUser=${false} sort=${connView.sort} dir=${connView.dir} onSort=${c => { peerSortBy(connView, c); connView.page = 1; bump(); }}/>`
      : html`<div class="empty"><b>${connView.online ? "No connections online" : "Nothing matches"}</b>${connView.online ? "No peer is online with these filters." : "Clear the filters."}</div>`}
    ${pager(rows.length)}
  </div>`;
}

// ═════════════════════════ SCREEN: USERS ═════════════════════════
// Independent view-state per grid so search / server / interface / page never bleed across them.
const usersView = { q: "", node: "", iface: "", page: 1, pageSize: 20, sort: "status", dir: -1, expanded: {} };   // node/iface filter the LIST (expand shows all peers)
const unassignedView = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 };
const userPeerViews = {};   // uid -> its own { node, iface, q, page, pageSize, sort, dir } for the expanded grid

// User-row status: a BARE tag (dot + uppercase mono label), same style as the node "reporting/offline"
// status, just smaller — not the pill Badge used inside the grids.
function userStatTag(user, live) {
  // Live monitor: a user is simply online (has an online peer, green) or offline (grey) — no ready/partial/etc.
  if (live) { const on = user.onlineCount > 0; return html`<span class=${"ustat s-" + (on ? "online" : "off")}>${on ? "online" : "offline"}</span>`; }
  const s = user.peerCount ? user.status : "empty";
  return html`<span class=${"ustat s-" + s}>${s === "empty" ? "no peers" : s}</span>`;
}
// Combined live stats across ALL of a user's peers/targets — for the user row's rate/total/last columns.
function userStats(uid) {
  let rx = 0, tx = 0, rxb = 0, txb = 0, last = null;
  for (const p of Store.peersOfUser(uid)) for (const t of p.targets) {
    const o = t.observed; if (!o) continue;
    rx += o.rx_speed || 0; tx += o.tx_speed || 0; rxb += o.rx_bytes || 0; txb += o.tx_bytes || 0;
    if (o.handshake_age != null) last = (last == null) ? o.handshake_age : Math.min(last, o.handshake_age);
  }
  return { rx, tx, rxb, txb, last };
}
// Multi-term search: split the query on whitespace and require EVERY term to appear somewhere in the (single,
// combined) haystack — AND across terms, so "ada awg1" matches a peer whose USER is Ada and whose INTERFACE is
// awg1 even though the two terms live in different fields. Empty query matches everything. Callers pass ONE
// haystack that concatenates all searchable fields, so terms are free to match across them.
function searchMatch(hay, q) {
  if (!q) return true;
  hay = String(hay).toLowerCase();
  return String(q).toLowerCase().split(/\s+/).filter(Boolean).every(t => hay.includes(t));
}
// Global Users-search match: a peer's title/name/key/address/server/interface (one combined haystack).
function peerMatchesQ(p, q) {
  if (!q) return true;
  const hay = (p.title || "") + " " + (p.name || "") + " " + (p.pubkey || "") + " "
    + p.targets.map(t => (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface).join(" ");
  return searchMatch(hay, q);
}
// does the user's OWN identity (name/tag/note) match? — distinct from a match via one of their peers.
function userIdentityMatchesQ(u, q) { return searchMatch((u.name || "") + " " + (u.tag || "") + " " + (u.note || ""), q); }
// A user matches if their identity OR any of their peers match — so you can find a user by a peer's IP.
function userMatchesQ(u, q) {
  if (!q) return true;
  if (userIdentityMatchesQ(u, q)) return true;
  return Store.peersOfUser(u.id).some(p => peerMatchesQ(p, q));
}
// does the user have a peer deployed on this node (and interface, if given)? — for the Users node/iface filter.
// The user LIST is filtered by this; the expanded grid still shows ALL of the user's peers.
function userOnNodeIface(u, node, iface) {
  const anyIface = !iface || iface === "*";   // *awg / *wg still filter (by type) — only ""/"*" mean "all interfaces"
  if (!node && anyIface) return true;
  return Store.peersOfUser(u.id).some(p => p.targets.some(t => (!node || node === "*" || t.node === node) && ifaceMatch(t.iface, iface)));
}
// User-list sorting (clickable header). Callers hold sort/dir in their view-state under caller-chosen keys.
const USER_SORT = {
  status: u => PEER_STATUS_RANK[u.status] || 0, name: u => (u.name || "").toLowerCase(),
  peers: u => u.peerCount || 0, online: u => u.onlineCount || 0,
  last: u => { const s = userStats(u.id); return s.last == null ? Infinity : s.last; },
  rate: u => { const s = userStats(u.id); return s.rx + s.tx; },
  total: u => { const s = userStats(u.id); return s.rxb + s.txb; },
  // by node count first, then the total distinct interfaces across those nodes (encoded: nodes×10000 + ifaces)
  nodes: u => { const nm = {}; let ifs = 0; for (const p of Store.peersOfUser(u.id)) for (const t of p.targets) { const s = nm[t.node] = nm[t.node] || new Set(); if (!s.has(t.iface)) { s.add(t.iface); ifs++; } } return Object.keys(nm).length * 10000 + ifs; },
};
const USER_DEFDIR = { status: -1, peers: -1, online: -1, last: 1, rate: -1, total: -1, name: 1, nodes: -1 };
function sortUsers(users, sort, dir) {
  const key = USER_SORT[sort] || USER_SORT.status;
  return users.slice().sort((a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1) || String(a.name).localeCompare(String(b.name)));
}
function sortColToggle(view, sk, dk, col, defdir) { if (view[sk] === col) view[dk] = -view[dk]; else { view[sk] = col; view[dk] = defdir[col] || 1; } }
// The sortable header line above a users list — same grid columns as .urow-head so the titles (which the rows no
// longer repeat inline) sit over their columns.
function UsersHeader({ sort, dir, onSort, live }) {
  const arrow = c => sort === c ? (dir < 0 ? "↓ " : "↑ ") : "";
  const th = (c, label, cls) => html`<span class=${"clk" + (cls ? " " + cls : "")} onClick=${() => onSort(c)}>${arrow(c)}${label}</span>`;
  return html`<div class="uhead">
    <span></span>${th("status", "Status")}${th("name", "User")}
    <span class=${"u-right" + (live ? " live" : "")}>${th("peers", "Peers", "uh-pc")}${th("nodes", "Nodes", "uh-srv")}${th("last", "Online")}${th("rate", "Rate ↓↑", "uh-r")}${th("total", "Total ↓↑", "uh-r")}${live ? null : html`<span></span>`}</span>
  </div>`;
}
// which Users page a user lands on (mirrors UsersScreen's sort; search is cleared before we navigate)
function userPageOf(uid) {
  const users = sortUsers(Store.recon.users, usersView.sort, usersView.dir);
  const idx = users.findIndex(u => u.id === uid);
  return idx < 0 ? 1 : Math.floor(idx / (usersView.pageSize || 20)) + 1;
}
// Land on the Users screen at the PAGE where `userId` sits, expand that user's row and scroll it into view.
// Optionally glow a just-assigned peer's row (peerId). Shared by "click a username anywhere" and the assign
// flow (when it started on the Users screen).
function revealUser(userId, peerId) {
  if (!userId) return;
  usersView.q = ""; usersView.expanded[userId] = true;
  go("#/users");
  setTimeout(() => {                          // after the poll + re-render settles
    usersView.page = userPageOf(userId);      // the page this user actually lands on (not always page 1)
    if (peerId) Store.recentlyCreated[peerId] = Date.now();   // 1.5s glow on the peer's row
    Store.apply();                            // re-render Users with the right page + expansion
    requestAnimationFrame(() => { const el = document.getElementById("urow-" + userId); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); });
  }, 240);
}
// after assigning a peer TO a user: glow the just-assigned peer's row wherever it is. If we're already on the
// Users screen, ALSO reveal the user (their page + expand + scroll). But when the assignment came from the
// Peers screen, a peer-view modal, or a node's interface, STAY on that screen (just the glow) — no jump to Users.
function revealAssignedPeer(userId, peerId) {
  if (!userId) return;
  if (peerId) Store.recentlyCreated[peerId] = Date.now();   // glow the row on whatever screen shows it
  if ((location.hash || "").startsWith("#/user")) revealUser(userId, peerId);   // already on Users → reveal
  else Store.apply();                                       // assigned from Peers / a node interface → stay put
}

// A self-contained peers panel (toolbar + shared PeerGrid + pager) over a GIVEN peer set. Reused for the
// unassigned grid and each user's expanded grid, so they look/behave exactly like the Peers screen. The
// server / interface dropdown options are derived from the set itself (only servers/ifaces that have rows).
function EmbeddedPeers({ peers, view, onNew, newLabel, hideUser, hideToolbar, collapse, live, onlineOnly }) {
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const nodeSet = new Set(), ifByNode = {};
  for (const p of peers) for (const t of p.targets) { nodeSet.add(t.node); (ifByNode[t.node] = ifByNode[t.node] || new Set()).add(t.iface); }
  const nodes = [...nodeSet].sort((a, b) => Store.nodeName(a).localeCompare(Store.nodeName(b)));
  const multiServer = nodes.length > 1;
  if (view.node && view.node !== "*" && !nodeSet.has(view.node)) view.node = "";
  if (!view.node) view.node = multiServer ? "*" : (nodes[0] || "*");
  // with no toolbar (a user's expanded grid) there's no way to change the filter, so always show ALL the
  // set's peers — never let a stale single-server view hide peers on another node.
  const node = hideToolbar ? "*" : view.node;
  const ifaceOpts = node === "*"
    ? [...new Set(Object.values(ifByNode).flatMap(s => [...s]))].sort()
    : [...(ifByNode[node] || [])].sort();
  const ifaceDefault = () => (node === "*" || ifaceOpts.length > 1) ? "*" : (ifaceOpts[0] || "*");
  if (!view.iface) view.iface = ifaceDefault();
  if (!ifaceIsAll(view.iface) && !ifaceOpts.includes(view.iface)) view.iface = ifaceDefault();
  const iface = hideToolbar ? "*" : view.iface;
  const agg = node === "*" || ifaceIsAll(iface);
  const q = (view.q || "").toLowerCase();

  let rows = [];
  const shownByPeer = {};
  if (collapse) {
    // one row PER PEER (a representative deployment); the peer's other interfaces surface as a +N badge
    for (const p of peers) {
      let ts = p.targets.filter(t => (node === "*" || t.node === node) && ifaceMatch(t.iface, iface));
      if (onlineOnly) ts = ts.filter(t => t.online);   // Online filter → only the peer's online deployments
      if (!ts.length) continue;
      if (!searchMatch((p.title || "") + " " + (p.name || "") + " " + p.targets.map(t => (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface).join(" "), q)) continue;
      const rep = ts.slice().sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0))[0];   // prefer an online deployment
      rows.push({ p, t: rep });
      shownByPeer[p.id] = new Set([tkey(rep.node, rep.iface)]);   // only the rep is "shown" → the rest become +N
    }
  } else {
    for (const p of peers) for (const t of p.targets) {
      if (node !== "*" && t.node !== node) continue;
      if (!ifaceMatch(t.iface, iface)) continue;
      if (onlineOnly && !t.online) continue;
      rows.push({ p, t });
    }
    if (q) rows = rows.filter(({ p, t }) => searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface, q));
    for (const { p, t } of rows) (shownByPeer[p.id] = shownByPeer[p.id] || new Set()).add(tkey(t.node, t.iface));
  }
  if (!view.sort) { view.sort = "status"; view.dir = -1; }
  rows = sortPeerRows(rows, view.sort, view.dir);

  const pageSize = view.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(1, view.page || 1), totalPages);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { view.page = p; bump(); };

  return html`<div class="peerspanel">
    ${hideToolbar ? null : html`<div class="toolbar sub">
      <div class="search"><${Ic} i="search"/><input placeholder="Search title, address…" value=${view.q || ""}
        onInput=${e => { view.q = e.target.value; view.page = 1; bump(); }}/></div>
      ${multiServer ? html`<select class="selwrap" value=${node} onChange=${e => { view.node = e.target.value; view.iface = ""; view.page = 1; bump(); }}>
        <option value="*">All nodes</option>${nodes.map(n => html`<option value=${n}>${Store.nodeName(n)}</option>`)}
      </select>` : null}
      ${ifaceOpts.length > 1 ? html`<select class="selwrap" value=${iface} onChange=${e => { view.iface = e.target.value; view.page = 1; bump(); }}>
        <option value="*">All interfaces</option>${ifaceOptGroups(ifaceOpts)}
      </select>` : null}
      ${onNew ? html`<span class="grow"></span><button class="btn btn-primary btn-mini" onClick=${onNew}><${Ic} i="plus"/> ${newLabel || "New peer"}</button>` : null}
    </div>`}
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${view.q} hideUser=${hideUser} loc=${collapse} live=${live} sort=${view.sort} dir=${view.dir} onSort=${c => { peerSortBy(view, c); view.page = 1; bump(); }}/>
    ${rows.length > pageSize ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { view.pageSize = +e.target.value; view.page = 1; bump(); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)} of ${rows.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>Next ›</button>
    </div>` : null}
  </div>`;
}
// A peer's configs as a modal: one QR/download card per target (reuses TargetCard).
function openPeerConfigs(peer, back) {
  const cols = Math.min(peer.targets.length || 1, 3);   // up to 3 QRs per row; the modal sizes to fit
  // border-box width: 256·cols + 14·gaps + 40 body padding + 2 border + slack (so a row never
  // wraps early from rounding). cols caps at 3, so 4→row 2, 7→row 3, etc.
  const width = cols * 256 + (cols - 1) * 14 + 56;
  // close (✕ / Esc / overlay) returns to wherever it was opened from (e.g. the peer view)
  openModal(html`<${Sheet} title=${peer.title || peer.name || "Unassigned"} width=${width} onClose=${back || closeModal}>
    <div class="cfgsheet">${peer.targets.map(t => html`<${TargetCard} key=${tkey(t.node, t.iface)} peer=${peer} t=${t} bare=${true}/>`)}</div>
  <//>`);
}
function openUserEdit(user) {
  openModal(html`<${Sheet} title=${"Edit · " + user.name}><${UserEditCard} user=${user} done=${closeModal}/><//>`);
}
// Turn-proxy client configs for one deployment — one section per turn-proxy on the interface, generated
// on the fly for the DEPLOYED fork. `conf` is the base WG config (needs the private key, so session/stored).
function openTurnConfigs(peer, t, conf) {
  const back = () => openPeerConfigs(peer);   // Turn opens FROM the QR/configs sheet → ✕/Esc/Back all return there
  openModal(html`<${Sheet} title=${"Turn configs · " + (peer.title || peer.name || "peer")} width=${560} onClose=${back}>
    <${TurnConfigSheet} peer=${peer} t=${t} conf=${conf} back=${back}/>
  <//>`);
}
function TurnConfigSheet({ peer, t, conf, back }) {
  const [selFork, setSelFork] = useState(0);
  const [inst, setInst] = useState({});   // fork → chosen instance index (for redundant same-fork proxies)
  // One badge PER FORK; the peer's own fork (observed viaTurn) sorts first and is selected by default. When a
  // fork has several proxies (redundancy), a dropdown picks which one. Only the selected proxy's config shows.
  const lt = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const all = turnProxiesFor(t.node, t.iface);
  const sorted = lt.viaTurn ? [...all].sort((a, b) => (b.service === lt.viaTurn ? 1 : 0) - (a.service === lt.viaTurn ? 1 : 0)) : all;
  const order = [], byFork = {};
  sorted.forEach(p => { const f = turnFork(p.service); if (!byFork[f]) { byFork[f] = []; order.push(f); } byFork[f].push(p); });
  const vk = ((Store.panelSettings || {}).vk_link || "").trim();
  const base = (peer.title || peer.name || "peer") + "-" + Store.nodeName(t.node);
  if (!order.length) return html`<div class="hint">No turn-proxy forwards to this interface.</div>`;
  const fi = Math.min(selFork, order.length - 1); const fork = order[fi];
  const list = byFork[fork]; const ii = Math.min(inst[fork] || 0, list.length - 1); const cur = list[ii];
  return html`<div class="turncfg">
    ${order.length > 1 ? html`<div class="turntabs">${order.map((f, k) => html`<button key=${f}
      class=${"snbadge turntab" + (k === fi ? " on" : "")} style=${"--c:" + turnColor(f)} onClick=${() => setSelFork(k)}>${f}</button>`)}</div>` : null}
    ${list.length > 1 ? html`<div class="turninst">
      <label>Which ${fork} proxy</label>
      <select class="selwrap" value=${ii} onChange=${e => setInst(m => ({ ...m, [fork]: +e.target.value }))}>
        ${list.map((p, k) => html`<option value=${k}>${(p.listen || ("proxy " + (k + 1))) + (p.title ? " (" + p.title + ")" : "")}</option>`)}
      </select></div>` : null}
    ${!vk ? html`<div class="notice warn"><${Ic} i="warn"/><span>No VK call link set — configs carry a placeholder. Set it in <a href="#/panel/settings" onClick=${() => closeAllModals()}>Panel settings → Turn proxies</a>.</span></div>` : null}
    <${TurnCfgItem} key=${cur.service} conf=${conf} tp=${cur} vk=${vk} base=${base} back=${back}/>
  </div>`;
}
// One turn-proxy's client artifact. Sync forks fill `text`; wingsv:// fills `buildAsync` (needs zlib), so
// we resolve it in an effect and show "generating…" until ready. Textarea wraps + auto-grows (no scroll).
function TurnCfgItem({ conf, tp, vk, base, back }) {
  const a = turnArtifact(conf, tp, vk);
  const [text, setText] = useState(a.text != null ? a.text : null);
  const [err, setErr] = useState(null);
  const taRef = useRef(null);
  useEffect(() => {
    if (a.text != null) { setText(a.text); return; }
    let ok = true; setText(null); setErr(null);
    Promise.resolve().then(a.buildAsync).then(t => { if (ok) setText(t); }).catch(e => { if (ok) setErr((e && e.message) || "couldn't generate"); });
    return () => { ok = false; };
  }, [tp.service, conf, vk]);
  useEffect(() => { autoGrow(taRef.current); }, [text]);   // dynamic height to fit wrapped content, no scroll
  const ready = text != null;
  return html`<div class="turncfg-item">
    <div class="turncfg-head"><span class="tcf-label">${a.label}</span></div>
    ${a.hint ? html`<div class="hint" style="margin:2px 0 6px">${a.hint}</div>` : null}
    ${a.cmd ? html`<div class="turncfg-cmd"><div class="tokenbox">${a.cmd}</div>
      <button class="cmd-copy" title="Copy command" onClick=${() => copy(a.cmd, "Command copied")}><${Ic} i="copy"/></button></div>` : null}
    ${err ? html`<div class="hint err">${err}</div>`
      : html`<textarea class="turncfg-ta" readonly spellcheck="false" ref=${taRef} onClick=${e => e.target.select()}>${ready ? text : "generating…"}</textarea>`}
    <div class="turncfg-foot">
      ${back ? html`<button class="btn btn-mini" onClick=${back}><${Ic} i="back"/> Back to QR</button>` : null}
      <span class="grow"></span>
      <button class="btn btn-mini" disabled=${!ready} onClick=${() => copy(text, (a.uri ? "Link" : "Config") + " copied")}><${Ic} i="copy"/> Copy</button>
      <button class="btn btn-mini" disabled=${!ready} onClick=${() => downloadConf(text, base + "-" + a.fork + (portOf(tp.listen) ? "-" + portOf(tp.listen) : ""))}><${Ic} i="download"/> Download .conf</button>
    </div>
  </div>`;
}

// One user as a collapsible row: status · name · tag · note · peers · last · rate · total · controls.
// Click the row to expand its peers (the shared EmbeddedPeers grid); click again to collapse.
function UserRow({ user, live, onlineOnly, q }) {
  const [, force] = useState(0);
  // While searching, matching users auto-expand (unless the operator explicitly collapsed one). If the user
  // matched only via some of their PEERS (not their own name/tag/note), the expanded grid shows just those
  // matching peers — a matching child pulls in its parent, siblings stay hidden. An identity match shows all peers.
  const searching = !!q;
  const idMatch = userIdentityMatchesQ(user, q);
  const expanded = searching ? (usersView.expanded[user.id] !== false) : !!usersView.expanded[user.id];
  const toggle = () => { usersView.expanded[user.id] = !expanded; force(x => x + 1); };
  const allPeers = Store.peersOfUser(user.id);
  const shownPeers = (searching && !idMatch) ? allPeers.filter(p => peerMatchesQ(p, q)) : allPeers;
  // nodes the user has peers on → for the hover bubble: each node's interfaces listed ONCE with a peer count, by node.
  const _nm = {};
  for (const p of allPeers) for (const t of p.targets) {
    const nn = _nm[t.node] = _nm[t.node] || {};
    if (!nn[t.iface]) nn[t.iface] = { iface: t.iface, type: (t.type || "").toLowerCase() === "awg" ? "awg" : "wg", count: 0 };
    nn[t.iface].count++;
  }
  const srvNodes = Object.keys(_nm).map(nid => ({ node: nid, ifaces: Object.values(_nm[nid]).sort((a, b) => a.iface.localeCompare(b.iface)) }))
    .sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node)));
  const st = userStats(user.id);
  const [db, ub] = dlul(st.rxb, st.txb);
  const view = userPeerViews[user.id] || (userPeerViews[user.id] = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 });
  const delUser = () => openConfirm({ title: "Delete user · " + user.name, confirmLabel: "Delete user", danger: true,
    body: "Their peers are revoked and become unassigned. This can't be undone.",
    onConfirm: () => mutate({ key: "user:" + user.id,
      patch: s => { delete s.roster.users[user.id]; for (const p of Object.values(s.roster.peers)) if (p.user_id === user.id) p.user_id = null; },
      call: () => api.userDelete({ id: user.id }) }) });
  return html`<div class=${"urow" + (expanded ? " open" : "")} id=${"urow-" + user.id}>
    <div class="urow-head" onClick=${toggle}>
      <span class="u-exp"><${Ic} i="arrow"/></span>
      ${userStatTag(user, live)}
      <span class="u-name"><span class="un">${user.name}</span>${user.tag ? html`<span class="tagchip">${user.tag}</span>` : null}${user.note ? html`<span class="u-note" title=${user.note}>${user.note}</span>` : null}</span>
      <span class=${"u-right" + (live ? " live" : "")}>
        <span class="u-counts">${(() => {
          const onc = html`<span class=${"u-onc" + (user.onlineCount ? " on" : "")}>${user.onlineCount} Online</span>`;
          const pc = html`<span class="u-pc">${user.peerCount} Peer${user.peerCount === 1 ? "" : "s"}</span>`;
          const sep = html`<span class="u-dot"> · </span>`;
          return live ? html`${onc}${sep}${pc}` : html`${pc}${user.peerCount ? html`${sep}${onc}` : null}`;
        })()}</span>
        <span class="u-servers">${srvNodes.length ? html`<span class="turnwrap srvwrap" onClick=${e => e.stopPropagation()}>
          <span class="srvchips">
            ${srvNodes.length === 1 ? html`<span class="nsrv" style=${"--c:" + Store.nodeColor(srvNodes[0].node)}>${Store.nodeName(srvNodes[0].node)}</span>`
              : html`<span class="nsrv-agg"><${Ic} i="server"/>${srvNodes.length} Nodes</span>`}
          </span>
          <span class="turnbub servbub">${srvNodes.flatMap(n => n.ifaces.map(f => html`<span class="servbub-row">
            <span class="nsrv" style=${"--c:" + Store.nodeColor(n.node)}>${Store.nodeName(n.node)}</span>
            <${Tag} kind=${f.type} label=${f.iface}/>
            <span class="servbub-pc">${f.count} Peer${f.count === 1 ? "" : "s"}</span>
          </span>`))}</span>
        </span>` : html`<span class="faint">—</span>`}</span>
        <span class="u-last">${st.last == null ? html`<span class="u-never">Never</span>` : html`<span class="when">${seen(st.last)}</span>`}</span>
        <span class="u-thru">${rateCell(st.rx, st.tx)}</span>
        <span class="u-total">${xferCell(db, ub)}</span>
        ${live ? null : html`<span class="u-acts" onClick=${e => e.stopPropagation()}>
          <button class="iconbtn" title="Add peer" onClick=${() => openAddPeers(user.id, user.name)}><${Ic} i="plus"/></button>
          <button class="iconbtn" title="Edit user" onClick=${() => openUserEdit(user)}><${Ic} i="pencil"/></button>
          <button class="iconbtn danger" title="Delete user" onClick=${delUser}><${Ic} i="trash"/></button>
        </span>`}
      </span>
    </div>
    ${expanded ? html`<div class="urow-body">
      ${shownPeers.length ? html`<${EmbeddedPeers} peers=${shownPeers} view=${view} hideUser=${true} hideToolbar=${true} collapse=${true} live=${live} onlineOnly=${onlineOnly}/>`
        : html`<div class="ug-empty">${user.peerCount ? "No peers match." : html`<${Fragment}>No peers yet — <button class="linkbtn" onClick=${() => openAddPeers(user.id, user.name)}>add one</button>.<//>`}</div>`}
    </div>` : null}
    <${RowError} k=${"user:" + user.id}/>
  </div>`;
}

function UsersScreen() {
  useStore();
  const [, force] = useState(0);
  const q = usersView.q.toLowerCase();
  const allUsers = Store.recon.users;
  const allIfaces = Array.from(new Set(Object.keys(Store.describe).flatMap(n => Store.userIfacesOf(n)))).sort();
  const ifaceOpts = usersView.node ? Store.userIfacesOf(usersView.node) : allIfaces;
  if (!ifaceIsAll(usersView.iface) && !ifaceOpts.includes(usersView.iface)) usersView.iface = "";
  // node/iface filter the user LIST (has a peer there); each expanded row still shows ALL of that user's peers
  const users = sortUsers(allUsers.filter(u => userMatchesQ(u, q) && userOnNodeIface(u, usersView.node, usersView.iface)), usersView.sort, usersView.dir);
  const allUnassigned = Store.unassignedPeers();
  const unassigned = q ? allUnassigned.filter(p => peerMatchesQ(p, q)) : allUnassigned;

  const pageSize = usersView.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(users.length / pageSize));
  const page = Math.min(Math.max(1, usersView.page || 1), totalPages);
  const pageUsers = users.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { usersView.page = p; force(x => x + 1); };

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <div class="search"><${Ic} i="search"/><input placeholder="Search users, tags, notes, peers…" value=${usersView.q}
        onInput=${e => { usersView.q = e.target.value; usersView.page = 1; force(x => x + 1); }}/></div>
      <select class="selwrap" value=${usersView.node} onChange=${e => { usersView.node = e.target.value; usersView.iface = ""; usersView.page = 1; force(x => x + 1); }}>
        <option value="">All nodes</option>${(Store.nodes || []).map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${usersView.iface} onChange=${e => { usersView.iface = e.target.value; usersView.page = 1; force(x => x + 1); }}>
        <option value="">All interfaces</option>${ifaceOptGroups(ifaceOpts)}
      </select>
      <span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => openCreatePeer({})}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
      <button class="btn btn-primary" onClick=${openCreateUser}><span class="plus"><${Ic} i="plus"/></span> New user</button>
    </div>

    <div class="section-title"><h2>Users</h2><span class="count">${users.length}</span></div>
    ${!allUsers.length ? html`<div class="empty"><b>No users yet</b>Create a user, then mint peers for them — or create a peer and assign it later.</div>`
      : !users.length ? html`<div class="empty"><b>Nothing matches</b>Clear the search.</div>`
      : html`<${Fragment}>
        <${UsersHeader} sort=${usersView.sort} dir=${usersView.dir} onSort=${c => { sortColToggle(usersView, "sort", "dir", c, USER_DEFDIR); usersView.page = 1; force(x => x + 1); }}/>
        <div class="urows">${pageUsers.map(u => html`<${UserRow} key=${u.id} user=${u} q=${q}/>`)}</div>
      <//>`}
    ${users.length > pageSize ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { usersView.pageSize = +e.target.value; usersView.page = 1; force(x => x + 1); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select></label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, users.length)} of ${users.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${e => { setPage(page - 1); pageScroll(e, -1); }}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${e => { setPage(page + 1); pageScroll(e, 1); }}>Next ›</button>
    </div>` : null}

    ${allUnassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">Unassigned peers</h2><span class="count">${unassigned.length}</span></div>
      <${EmbeddedPeers} peers=${unassigned} view=${unassignedView} collapse=${true}/>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USER DETAIL ═════════════════════════
// The per-user detail screen is folded into the Users list: a deep link (or a peers-table user cell)
// just opens the Users screen with that user's row expanded. Kept so old links / bookmarks still work.
function UserDetail({ id: rawId }) {
  const id = decodeURIComponent(rawId);
  // clicking a username anywhere lands here → reveal the user on the Users screen at their real page + expand
  useEffect(() => { revealUser(id); }, [id]);
  return html`<div class="screen"><div class="empty">Opening…</div></div>`;
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
  const del = () => openConfirm({ title: "Delete user · " + user.name, confirmLabel: "Delete user", danger: true, back: done,
    body: "Their peers are revoked and become unassigned. This can't be undone.",
    onConfirm: () => mutate({ key: "user:" + user.id,
      patch: s => { delete s.roster.users[user.id]; for (const p of Object.values(s.roster.peers)) if (p.user_id === user.id) p.user_id = null; },
      call: () => api.userDelete({ id: user.id }) }) });
  return html`<div class="card" style="max-width:560px">
    <div class="field"><label>Name</label><input value=${name} onInput=${e => setName(e.target.value)} maxlength="64"/></div>
    <div class="field"><label>Tag</label><input value=${tag} onInput=${e => setTag(e.target.value)} placeholder="Friend, Family, Work…" maxlength="32"/></div>
    <div class="field"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="Uses iPhone and router" maxlength="200"/></div>
    <div class="editfoot"><button class="btn btn-danger" onClick=${del}><${Ic} i="trash"/> Delete user</button><span class="grow"></span><button class="btn btn-ghost" onClick=${done}>Cancel</button><button class="btn btn-primary" onClick=${save}>Save</button></div>
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
        <div class="inner"><div class="ring"><${Ic} i="plus"/></div><div>Manage targets</div><div class="faint" style="font-size:11px">deploy or remove · same key</div></div>
      </div>
    </div>
  </div>`;
}

function TargetCard({ peer, t, bare }) {
  useStore();   // re-render on each poll so the status badge stays live (t is a snapshot from open)
  const [conf, setConf] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { let ok = true; getConfig(peer.pubkey, t.node, t.iface).then(c => { if (ok) { setConf(c); setLoaded(true); } }); return () => { ok = false; }; }, [peer.pubkey, t.node, t.iface, Store.configEpoch]);
  // live target (status / observed) from the store, falling back to the passed-in snapshot
  const ft = (Store.recon.peers.find(p => p.id === peer.id) || {}).targets;
  const lt = (ft && ft.find(d => d.node === t.node && d.iface === t.iface)) || t;
  const col = Store.nodeColor(t.node);
  const obs = lt.observed;
  const tps = turnProxiesFor(t.node, t.iface);
  const dnode = Store.nodeName(t.node);
  // zoom caption: username + title (or "Unassigned"), then the server name (in its colour) + iface tag
  const idParts = []; if (peer.name) idParts.push(esc(peer.name)); if (peer.title) idParts.push(esc(peer.title));
  const ltype = (t.type || "").toLowerCase() === "awg" ? "awg" : "wg";
  const label = `<span class="qrc-id">${idParts.length ? idParts.join(" · ") : "Unassigned"}</span>`
    + `<span class="qrc-srv" style="color:${col}">${esc(dnode)}</span><span class="tg tg-${ltype}">${esc(t.iface)}</span>`;

  return html`<div class="deploy">
    <div class="deploy-head"><a class="nm nmlink" style=${"color:" + col} onClick=${() => { closeModal(); go("#/node/" + encodeURIComponent(t.node)); }}>${dnode}</a><${Tag} kind=${(t.type || "").toLowerCase() === "awg" ? "awg" : "wg"} label=${t.iface}/><span class="grow"></span><${Badge} s=${lt.status}/></div>
    <div class="deploy-body">
      ${conf ? html`<${QR} conf=${conf} label=${label}/>`
        : html`<div class="qr-none">${!loaded ? "loading…"
            : Store.storeConfigs ? "No stored config — re-issue this peer to enable its QR & download."
            : "Config shown right after creation, or enable store_configs to keep it."}</div>`}
      ${bare ? null : html`<div class="dmeta">
        <div class="row"><span class="k">address</span><span class="vv">${t.ip || "—"}</span></div>
        <div class="row"><span class="k">handshake</span><span class="vv">${obs ? seen(obs.handshake_age) : "—"}</span></div>
        <div class="row"><span class="k">rate</span><span class="vv">${obs ? rateCell(obs.rx_speed, obs.tx_speed) : "—"}</span></div>
        <div class="row"><span class="k">transport</span><span class="vv">${lt.viaTurn ? html`via <span class="tg tg-turn" style=${"--tfc:" + turnColor(turnLabel(lt.viaTurn))}>${turnLabel(lt.viaTurn)}</span>` : (lt.via === "direct" ? "direct" : "—")}</span></div>
        ${tps.map(tp => html`<div class="row"><span class="k">turn-proxy</span><span class="vv">${tp.listen || "—"}
          ${tp.wrap_key ? html`<${Fragment}> · key <span class="addr">${String(tp.wrap_key).slice(0, 8)}…</span><button class="copybtn" title="Copy wrap key" onClick=${() => copy(tp.wrap_key, "Wrap key copied")}><${Ic} i="copy"/></button></>` : null}</span></div>`)}
      </div>`}
    </div>
    ${conf ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => downloadConf(conf, (peer.name || "peer") + "-" + dnode)}><${Ic} i="download"/> Config</button>
      <button class="btn btn-mini" onClick=${() => copy(conf, "Config copied")}><${Ic} i="copy"/> Copy</button>
      ${tps.length ? html`<button class="btn btn-mini" title="Generate turn-proxy client configs" onClick=${() => openTurnConfigs(peer, t, conf)}><${Ic} i="relay"/> Turn</button>` : null}
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
function NodesScreen() {
  useStore();
  const ns = Store.nodes || [];
  // drag-to-reorder the whole fleet (persisted as per-node `pos`)
  const nReorder = useReorder(ns.map(n => n.id), ids => mutate({
    patch: s => { s.nodes = orderById(s.nodes, ids, n => n.id); },
    call: () => api.saveOrder({ kind: "node", order: ids }),
  }), "y");   // nodes stack vertically → top/bottom drop edges
  return html`<div class="screen">
    <div class="section-title" style="margin:6px 2px 16px"><h2>Nodes</h2><span class="count">${ns.length + (ns.length === 1 ? " server" : " servers")}</span>
      <span class="nodehint">Entry servers run <span class="mono">swg-noded</span>, which syncs to this panel over HTTPS — the node needs no inbound access.</span><span class="grow"></span>
      <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> Add node</button></div>
    ${!ns.length ? html`<div class="empty"><b>No nodes yet</b>Add your first entry server — you'll get a one-time command to run on it.</div>`
      : html`<div class="nodegrid" ...${nReorder.container()}>${ns.map(n => html`<${NodeCard} key=${n.id} n=${n} reorder=${nReorder}/>`)}</div>`}
  </div>`;
}
// load/util tone: green under 70%, amber to 90%, red above.
function htone(pct) { return pct >= 90 ? "hot" : (pct >= 70 ? "warn" : "ok"); }
function htcolor(pct) { return pct >= 90 ? "var(--dangling)" : (pct >= 70 ? "var(--fault)" : "var(--online)"); }   // green→amber→red util ramp (matches hm-fill + the CPU loadColor ramp)
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
const toneColor = t => t === "hot" ? "var(--dangling)" : t === "warn" ? "var(--fault)" : "var(--online)";
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
// format a chart point's timestamp for the hover tooltip — time of day, + date for week/month ranges
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// per-range tooltip time: live = h:m:s, hour/day = h:m, week/month = "June 24, 6PM" (date + 12h hour)
function histTime(ts, range) {
  if (ts == null) return "";
  const d = new Date(ts * 1000), p2 = x => String(x).padStart(2, "0");
  if (range === "week" || range === "month") {
    const h = d.getHours(), h12 = ((h + 11) % 12) + 1;
    return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + h12 + (h < 12 ? "AM" : "PM");
  }
  const hm = p2(d.getHours()) + ":" + p2(d.getMinutes());
  return range === "live" ? hm + ":" + p2(d.getSeconds()) : hm;
}
// hover overlay shared by the CPU + throughput charts: vertical guide, point dot(s), value tooltip
function ChartHover({ xp, dots, label }) {
  const anchor = xp < 22 ? "translateX(0)" : xp > 78 ? "translateX(-100%)" : "translateX(-50%)";
  return html`<${Fragment}>
    <div class="ch-guide" style=${"left:" + xp + "%"}></div>
    ${(dots || []).map(d => html`<div class="ch-dot" style=${"left:" + xp + "%;top:" + d.yp + "%;background:" + d.color}></div>`)}
    <div class="ch-tip" style=${"left:" + xp + "%;transform:" + anchor}>${label}</div>
  <//>`;
}
// CPU-load colour ramp for the history line: green ≤60%, green→orange 60–90%, orange→red
// 90–120%, solid red beyond. v is load-per-core as a percentage (so an overloaded box reads >100).
const LOAD_G_DARK = [63, 216, 154], LOAD_G_LIGHT = [14, 158, 99], LOAD_O = [242, 163, 60], LOAD_R = [242, 84, 91];
function loadColor(v) {
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
  const LOAD_G = resolvedTheme() === "light" ? LOAD_G_LIGHT : LOAD_G_DARK;   // the low-load green must stay legible on white
  if (v <= 60) return mix(LOAD_G, LOAD_G, 0);
  if (v <= 90) return mix(LOAD_G, LOAD_O, (v - 60) / 30);
  if (v <= 120) return mix(LOAD_O, LOAD_R, (v - 90) / 30);
  return mix(LOAD_R, LOAD_R, 0);
}
function MiniArea({ points, h, times, range, cap }) {
  const [hov, setHov] = useState(null);
  const wref = useRef(null);
  const pts = (points || []).filter(v => v != null);
  h = h || 42; const w = 100;
  const n = pts.length;
  // x-axis holds `cap` blocks (the ring's full capacity); data is pinned to the RIGHT edge and
  // grows leftward as blocks arrive, so a fresh node fills one block at a time instead of stretching.
  const C = Math.max(cap || n || 1, 2);
  const xAt = i => w - (n - 1 - i) * (w / (C - 1));
  const T = times || [];
  // map a mouse x to the nearest plotted block (null over the still-empty left area)
  const onMove = e => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * w; const i = Math.round((n - 1) - (w - x) * (C - 1) / w);
    setHov(i >= 0 && i < n ? i : null); };
  if (n === 0)   // empty plot area — fills from the right as the first blocks arrive
    return html`<div class="harea-wrap" style=${"height:" + h + "px"}></div>`;
  // FIXED stepped y-scale from 0 (not min/max autoscale) so CPU doesn't always touch the top. Pick the bar
  // height by the peak: ≤10% → 0–20% · ≤30% → 0–50% · ≤60% → 0–80% · above → 0–100%.
  const lo = Math.min(...pts), hi = Math.max(...pts), rng = (hi - lo) || 1, vpad = h * 0.06;
  const scaleMax = hi <= 10 ? 20 : hi <= 30 ? 50 : hi <= 60 ? 80 : 100;
  const Y = v => h - vpad - (Math.min(Math.max(v, 0), scaleMax) / scaleMax) * (h - 2 * vpad);
  const xy = pts.map((v, i) => [xAt(i), Y(v)]);
  const line = xy.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = xy[0][0].toFixed(1) + "," + h + " " + line + " " + xy[n - 1][0].toFixed(1) + "," + h;
  const id = "ha" + (MiniArea._n = (MiniArea._n || 0) + 1);
  // vertical stroke gradient: colour each height by its absolute load value (green→orange→red).
  // Stops at the band edges that fall inside the visible [lo,hi] window — linear between them
  // reproduces the ramp exactly (both colour and y are linear in value within a band).
  // offsets are normalised to the polyline's own bounding box (objectBoundingBox): top = hi → 0, bottom = lo → 1
  const edges = [...new Set([lo, 60, 90, 120, hi].filter(v => v >= lo && v <= hi))].sort((a, b) => b - a);
  const stops = edges.map(v => ({ off: Math.max(0, Math.min(1, (hi - v) / rng)), col: loadColor(v) }));
  const cur = pts[n - 1];   // area fade is tinted by the latest value
  return html`<div class="harea-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    <svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
      <defs>
        <linearGradient id=${id + "s"} x1="0" x2="0" y1="0" y2="1">
          ${stops.map(s => html`<stop offset=${s.off} stop-color=${s.col}/>`)}
        </linearGradient>
        <linearGradient id=${id + "a"} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color=${loadColor(cur)} stop-opacity="0.30"/><stop offset="1" stop-color=${loadColor(cur)} stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${n >= 2 ? html`<polygon points=${area} fill=${"url(#" + id + "a)"}/>
      <polyline points=${line} fill="none" stroke=${"url(#" + id + "s)"} stroke-width="1.4" vector-effect="non-scaling-stroke"/>` : null}
    </svg>
    ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xy[0][0] + "%;top:" + (xy[0][1] / h * 100) + "%;background:" + loadColor(cur)}></div>` : null}
    ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xy[hov][0]} dots=${[{ yp: xy[hov][1] / h * 100, color: loadColor(pts[hov]) }]}
      label=${histTime(T[hov], range) + " · " + Math.round(pts[hov]) + "%"}/>` : null}
  </div>`;
}

// Throughput history: rx as a filled area + tx as a line, scaled to the series max.
function ThroughputChart({ rx, tx, h, head, times, range, cap }) {
  const [hov, setHov] = useState(null);
  const wref = useRef(null);
  const R = (rx || []).map(v => v || 0), T = (tx || []).map(v => v || 0);
  const n = Math.max(R.length, T.length);
  const curR = R[R.length - 1] || 0, curT = T[T.length - 1] || 0;
  const hi = n ? Math.max(0, ...R, ...T) : 0;
  // FIXED tiered y-scale so the curve reflects real magnitude instead of stretching to fill the height
  // (a 39 B/s peak shouldn't look identical to a 39 Mbps one). Tier the scale by the view's peak (Mbps):
  //   ≤45 → 0–50 · ≤90 → 0–100 · ≤180 → 0–200 · ≤470 → 0–500 · ≤1000 → 0–1 Gbps · above → dynamic (peak +10%).
  const MBIT = 125000;                                   // bytes/sec per megabit/sec
  const hiM = hi / MBIT;                                 // peak in Mbps
  const [smM, scaleLabel] = hiM <= 45 ? [50, "50 Mbps"]
    : hiM <= 90 ? [100, "100 Mbps"]
    : hiM <= 180 ? [200, "200 Mbps"]
    : hiM <= 470 ? [500, "500 Mbps"]
    : hiM <= 1000 ? [1000, "1 Gbps"]
    : [hiM * 1.1, "auto"];
  const scaleMax = (smM * MBIT) || 1;
  const legend = html`<div class="tp-legend"><span class="tp-k"><i class="sw rx"></i>↓ ${rate(curR)}</span><span class="tp-k"><i class="sw tx"></i>↑ ${rate(curT)}</span><span class="tp-peak">peak ${rate(hi)}</span><span class="tp-scale" title="Vertical scale (auto = peak +10%, above 1 Gbps)">${scaleLabel}</span><span class="grow"></span>${head || null}</div>`;
  h = h || 60; const w = 100;
  // right-anchored to the ring's full capacity, like MiniArea — fills from the right as blocks arrive
  const C = Math.max(cap || n || 1, 2);
  const xAt = i => w - (n - 1 - i) * (w / (C - 1));
  // baseline 0 at the bottom, scaleMax at the top (with a little headroom) — fixed, not min/max autoscale
  const top = h * 0.10;
  const Y = v => h - (Math.max(0, Math.min(v, scaleMax)) / scaleMax) * (h - top);
  const line = arr => arr.map((v, i) => xAt(i).toFixed(1) + "," + Y(v).toFixed(1)).join(" ");
  const rxLine = line(R), rxArea = n >= 2 ? (xAt(0).toFixed(1) + "," + h + " " + rxLine + " " + xAt(n - 1).toFixed(1) + "," + h) : "";
  const gid = "tp" + (ThroughputChart._n = (ThroughputChart._n || 0) + 1);
  const TT = times || [];
  const onMove = e => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * w; const i = Math.round((n - 1) - (w - x) * (C - 1) / w);
    setHov(i >= 0 && i < n ? i : null); };
  return html`<div class="tp-wrap">
    ${legend}
    <div class="harea-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
      <svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
        <defs><linearGradient id=${gid} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="var(--brand)" stop-opacity="0.30"/><stop offset="1" stop-color="var(--brand)" stop-opacity="0"/>
        </linearGradient></defs>
        ${n >= 2 ? html`<polygon points=${rxArea} fill=${"url(#" + gid + ")"}/>
        <polyline points=${rxLine} fill="none" stroke="var(--brand)" stroke-width="1.3" vector-effect="non-scaling-stroke" stroke-dasharray="3 2"/>
        <polyline points=${line(T)} fill="none" stroke="var(--tp-tx)" stroke-width="1.3" vector-effect="non-scaling-stroke"/>` : null}
      </svg>
      ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(R[0]) / h * 100) + "%;background:var(--brand)"}></div>
        <div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(T[0]) / h * 100) + "%;background:var(--tp-tx)"}></div>` : null}
      ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xAt(hov)}
        dots=${[{ yp: Y(R[hov] || 0) / h * 100, color: "var(--brand)" }, { yp: Y(T[hov] || 0) / h * 100, color: "var(--tp-tx)" }]}
        label=${histTime(TT[hov], range) + " · ↓ " + rate(R[hov] || 0) + " · ↑ " + rate(T[hov] || 0)}/>` : null}
    </div>
  </div>`;
}

// Concentric-ring doughnut (hand-rolled SVG, no deps). `rings` = outer→inner; each ring is
//   { label, fmt, segments:[{ key, name, value, color }] }.
// Each ring's segments are drawn as arcs of a single circle via pathLength=100 (so dash maths is in
// percent, independent of radius). A tiny gap separates segments. Hovering a segment swaps the centre
// readout to that segment (name · ring-label value · % of ring); leaving restores the `center` node.
// Re-renders are cheap: only arc dash values + the centre text change per poll, no full rebuild.
function MultiRing({ rings, size, thick, gap, center, onHover }) {
  const [hov, setHov] = useState(null);   // {ri, si}
  size = size || 168; thick = thick || 15; gap = gap == null ? 1.1 : gap;
  const cx = size / 2, cy = size / 2;
  const rings2 = (rings || []).filter(Boolean);
  // outer ring radius leaves a thick/2 margin; each inner ring steps in by thick + a 4px groove
  const step = thick + 5;
  const arcs = [];
  rings2.forEach((ring, ri) => {
    const r = (size / 2) - thick / 2 - ri * step;
    const segs = (ring.segments || []).filter(s => s && s.value > 0);
    const total = segs.reduce((a, s) => a + s.value, 0) || (ring.total || 0);
    arcs.push({ ri, r, track: true });
    if (total <= 0) return;
    let acc = 0;
    segs.forEach((s, si) => {
      const pct = s.value / total * 100;
      arcs.push({ ri, si, r, pct, off: acc, seg: s, ring, total });
      acc += pct;
    });
  });
  const active = hov ? (arcs.find(a => a.ri === hov.ri && a.si === hov.si) || null) : null;
  return html`<div class="mring" style=${"width:" + size + "px;height:" + size + "px"}>
    <svg width=${size} height=${size} viewBox=${"0 0 " + size + " " + size}>
      <g transform=${"rotate(-90 " + cx + " " + cy + ")"}>
        ${arcs.map((a, i) => a.track
          ? html`<circle key=${"t" + i} cx=${cx} cy=${cy} r=${a.r} fill="none" stroke="var(--track)" stroke-width=${thick} pathLength="100"/>`
          : html`<circle key=${"a" + a.ri + "-" + a.si} cx=${cx} cy=${cy} r=${a.r} fill="none" stroke=${a.seg.color} stroke-width=${thick}
              pathLength="100" stroke-dasharray=${Math.max(0, a.pct - gap) + " " + (100 - Math.max(0, a.pct - gap))} stroke-dashoffset=${-a.off}
              class=${"mring-seg" + (active && active !== a ? " dim" : "")}
              onMouseEnter=${() => { setHov({ ri: a.ri, si: a.si }); onHover && onHover(a); }}
              onMouseLeave=${() => { setHov(null); onHover && onHover(null); }}/>`)}
      </g>
    </svg>
    <div class="mring-center">
      ${active ? html`<div class="mrc-hov">
          <div class="mrc-name" style=${"color:" + active.seg.color}>${active.seg.name}</div>
          <div class="mrc-val">${(active.ring.fmt || (v => v))(active.seg.value)}</div>
          <div class="mrc-sub">${active.ring.label} · ${Math.round(active.pct)}%</div>
        </div>`
        : center}
    </div>
  </div>`;
}
// Legend for a doughnut: one keyed swatch row per entry {name,color,value,fmt}. Optional second value.
function RingLegend({ items, cols }) {
  return html`<div class=${"mring-leg" + (cols ? " c" + cols : "")}>${(items || []).map(it => html`<div class="mrl-row" key=${it.key || it.name}>
    <span class="mrl-sw" style=${"background:" + it.color}></span><span class="mrl-nm">${it.name}</span>
    <span class="grow"></span>${it.right != null ? html`<span class="mrl-v">${it.right}</span>` : null}</div>`)}</div>`;
}

// A simple single-colour filled-area trend (for count series like online-peers, where MiniArea's
// load-colour ramp would be semantically wrong). Fixed y-scale from 0 to the series peak; right-anchored
// and fills leftward like the other charts; hover shows the value via `fmt`.
function TrendArea({ points, times, color, h, cap, fmt, range, label }) {
  const [hov, setHov] = useState(null); const wref = useRef(null);
  const pts = (points || []).map(v => v || 0); h = h || 46; const w = 100, n = pts.length;
  color = color || "var(--online)"; fmt = fmt || (v => v);
  const C = Math.max(cap || n || 1, 2), xAt = i => w - (n - 1 - i) * (w / (C - 1)), T = times || [];
  const onMove = e => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * w, i = Math.round((n - 1) - (w - x) * (C - 1) / w); setHov(i >= 0 && i < n ? i : null); };
  if (n === 0) return html`<div class="harea-wrap" style=${"height:" + h + "px"}></div>`;
  const hi = Math.max(1, ...pts), scaleMax = hi * 1.15, vpad = h * 0.08;
  const Y = v => h - vpad - (Math.min(Math.max(v, 0), scaleMax) / scaleMax) * (h - 2 * vpad);
  const xy = pts.map((v, i) => [xAt(i), Y(v)]);
  const line = xy.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = xy[0][0].toFixed(1) + "," + h + " " + line + " " + xy[n - 1][0].toFixed(1) + "," + h;
  const id = "ta" + (TrendArea._n = (TrendArea._n || 0) + 1);
  return html`<div class="harea-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    <svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
      <defs><linearGradient id=${id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color=${color} stop-opacity="0.28"/><stop offset="1" stop-color=${color} stop-opacity="0"/></linearGradient></defs>
      ${n >= 2 ? html`<polygon points=${area} fill=${"url(#" + id + ")"}/><polyline points=${line} fill="none" stroke=${color} stroke-width="1.4" vector-effect="non-scaling-stroke"/>` : null}
    </svg>
    ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xy[hov][0]} dots=${[{ yp: xy[hov][1] / h * 100, color }]} label=${histTime(T[hov], range || "live") + " · " + fmt(pts[hov]) + (label ? " " + label : "")}/>` : null}
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
  const pfx = (Store.panelSettings || {}).reserved?.iface_prefix || "swg_";
  return Object.keys(meta).filter(ifn => !meta[ifn].system && !ifn.startsWith(pfx) && !ifn.startsWith("swg_")).map(ifn => {
    const op = Store.ifaceOp[node + "|" + ifn];   // start/stop/restart in flight → show it here too (optimistic, set on click)
    if (op && op.phase === "busy") return html`<a class="tg tg-busy" href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(ifn)} onClick=${e => e.stopPropagation()}><${Ic} i="clock"/>${ifn} ${IFOP_BUSY[op.verb] || op.verb}</a>`;
    const type = (meta[ifn].awg_params && Object.keys(meta[ifn].awg_params).length) ? "awg" : "wg";
    const muted = nodeStale(node) || ifaceNotUp(node, ifn);
    return html`<a class=${"tg tg-" + type + (muted ? " muted" : "")} href=${"#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(ifn)} onClick=${e => e.stopPropagation()}>${ifn}</a>`;
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
// blocks (= slots = plotted points) each range's x-axis holds — must match swg-panel-server
// HRRD_RINGS slot counts (live = LIVE_MAX). Charts pin data to the right and fill leftward.
const RANGE_CAP = { live: 200, hour: 250, day: 300, week: 350, month: 400 };
const tailSeries = (s, n) => { const o = {}; for (const k of ["t", "cpu", "mem", "disk", "rx", "tx"]) if (Array.isArray((s || {})[k])) o[k] = s[k].slice(-n); return o; };
function RangedHistory({ node, kind, live, h, head, liveFine }) {
  const [range, setRange] = useState("live");
  const [fetched, setFetched] = useState(null);
  const fetchRange = range === "day" || range === "week" || range === "month";   // live/hour come from /api/state
  useEffect(() => {
    if (!fetchRange) { setFetched(null); return; }
    let ok = true; setFetched(null);   // clear so the chart shows an empty area, then fills when the fetch lands
    api.nodeHistory(node, range).then(r => { if (ok) setFetched(r && r.ok ? r.data : {}); }).catch(() => {});
    return () => { ok = false; };
  }, [node, range]);
  // LIVE = the raw ~5s in-memory buffer when present; else — e.g. just after a panel restart, before
  // the buffer refills — fall back to the tail of the 15s ring (`live`, the hour series) so the chart
  // keeps showing recent history. hour = the full 15s series from /api/state; day/week/month fetched.
  const liveBuf = range === "live" && liveFine && (liveFine.t || []).length > 1;
  const s = range === "live" ? (liveBuf ? liveFine : tailSeries(live, 70))
    : range === "hour" ? (live || {}) : (fetched || {});
  // x-axis capacity: the live fallback is coarse 15s data, so let it fit to its own length (cap 0)
  // rather than pinning to the 5s window; every other range uses its fixed block count.
  const cap = range === "live" ? (liveBuf ? RANGE_CAP.live : 0) : RANGE_CAP[range];
  const hasData = (s.cpu || s.rx || []).some(x => x != null);
  const nlive = Store.recon.nodeStatus[node] === "live";   // node hasn't reported for several rounds → the live feed is frozen
  // A node that stops reporting (update / re-install / convert / brief outage) must NEVER blank the
  // chart — the data already collected stays on screen, flagged with a small "paused" pill.
  const notLive = !nlive && (range === "live" || range === "hour");   // only the live-fed ranges; day/week/month keep their stored history
  const pausedPill = (notLive && hasData) ? html`<span class="rt-paused" title="This node isn't reporting right now — showing the last data it sent.">paused</span>` : null;
  const tabs = html`${pausedPill}<div class="rangetabs">${HIST_RANGES.map(t => html`<button class=${"rtab" + (range === t ? " on" : "")} onClick=${() => setRange(t)}>${t}</button>`)}</div>`;
  if (kind === "throughput") {
    const peerPov = (Store.panelSettings || {}).throughput_perspective === "peers";   // flip series so ↓ = download in the chosen perspective
    return html`<${ThroughputChart} rx=${peerPov ? s.tx : s.rx} tx=${peerPov ? s.rx : s.tx} h=${h} head=${tabs} times=${s.t} range=${range} cap=${cap}/>`;
  }
  return html`<div class="chartwrap">
    <div class="chart-head">${head || null}<span class="grow"></span>${tabs}</div>
    <${MiniArea} points=${s.cpu} h=${h} times=${s.t} range=${range} cap=${cap}/>
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
    const p = Math.min(100, Math.max(0, c.pct || 0));
    const heat = c.label === "CPU load";                 // CPU bar+number: continuous green→red by load, like the graph
    const col = heat ? loadColor(c.pct) : null;          // uncapped pct → a badly overloaded core reads full red
    return html`<div class="hcol">
      <div class="hcol-top"><span class="hcol-l">${c.label}</span><span class="hcol-v" style=${col ? "color:" + col : ""}>${c.text}</span></div>
      <div class="hm-bar"><i class=${"hm-fill" + (heat ? "" : " " + htone(p))} style=${"width:" + p + "%" + (col ? ";background:" + col : "")}></i></div>
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
      <${MiniArea} points=${cpuHist} h=${compact ? 36 : 52}/>
    </div>` : null}
  </div>`;
}

let hostUpdating = false;                 // once Update is clicked, lock the header pill into "updating"
let pendingUpdateDone = null;             // [from,to] of a panel version bump, held until the WHOLE host update finishes (a master's panel restarts mid-update, before the node phase — don't pop the "updated" dialog yet)
// the circular-arrow glyph (same as the check icon), spun in yellow while an update runs
const UPD_SPIN_SVG = `<svg class="updspin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg>`;
const WARN_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>`;
const X_SVG = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
const CHECK_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;
const INFO_SVG = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`;
function setHostUpdating() {
  hostUpdating = true;
  const slot = $("#updslot");
  if (slot) slot.innerHTML = `<span class="livepill upd-busy">updating… ${UPD_SPIN_SVG}</span>`;
  Store.apply();   // re-render the whole SPA so a co-located (local) node tile flips to "updating…" at the SAME instant, not on the next poll
}
let seenPanelVer = null;   // detect the panel coming back on a new version (after an update), to prompt a hard reload
function openUpdateDone(from, to) {
  openModal(html`<${Sheet} title="Panel updated"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-primary" onClick=${() => location.reload()}>Reload now</button></>`}>
    <div class="updone">
      <p>The panel was updated from <b>v${from}</b> to <b>v${to}</b>.</p>
      <p>To be sure every change takes effect, give the panel a hard reload — it drops the cached app so the new version loads cleanly.</p>
      <p class="updone-hint">Press <kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>R</kbd></p>
    </div>
  <//>`);
}
// One consistent update modal for both a node and the panel header: the full (third-party-included) command to
// run by hand, plus an "Update now" button that kicks off the automatic swg-only update.
function openUpdateModal({ title, side, onConfirm }) {
  const full = "curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update";
  const go = async () => { closeModal(); await onConfirm(); };
  openModal(html`<${Sheet} title=${title}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${go}>Update now</button></>`}>
    <div class="iface-intro" style="font-size:14px;line-height:1.55"><div>For a <b>full, controlled update</b> — including third-party components (docker / wg-awg / turn-proxies) — run this on the ${side} box:</div></div>
    <div class="field"><div class="ipk-field"><span class="ipk-val" style="text-align:left">${full}</span><button class="copybtn" onClick=${() => copy(full, "Command copied")}><${Ic} i="copy"/></button></div></div>
    <div class="iface-intro" style="font-size:14px;line-height:1.55;margin-top:26px;margin-bottom:2px"><div>For an <b>automatic update of SWG components only</b>, press <b>Update now</b> below.</div></div>
  <//>`);
}
function updateNode(n) {
  openUpdateModal({
    title: "Update " + n.name, side: "node's",
    onConfirm: async () => { const r = await api.nodeSelfUpdate({ node: n.id }); if (r.ok) { await Store.poll(); toast("Update requested — applies on the node's next sync.", "ok"); } else toast(r.error || "Failed to request update.", "err"); },
  });
}
function updateHost() {
  openUpdateModal({
    title: "Update this server", side: "panel's",
    onConfirm: async () => {
      const r = await api.hostUpdate();
      if (!r.ok) return toast(r.error || "Failed to start update.", "err");
      if (r.data && r.data.manual) return toast("Automatic update isn't wired on this install — run the command shown in the dialog on the host.", "err");
      setHostUpdating(); toast("Update started — the panel will restart shortly.", "ok");
    },
  });
}
async function checkForUpdate(e, nodeId) {
  const btn = e && e.currentTarget;                  // spin + cyan it while we poll, so it reads as "searching"
  if (btn) btn.classList.add("checking");
  try {
    const r = await api.checkUpdate();
    await Store.poll();
    if (!r.ok) toast(r.error || "Couldn't check for updates.", "err");
    else if (r.data && !r.data.checked) toast("Couldn't reach the repo to check for updates.", "err");
    else if (nodeId) {                               // invoked from a NODE header → show the result THERE, not on the panel header
      const n = (Store.nodes || []).find(x => x.id === nodeId);   // outdated → its "update node" button appears; up-to-date → flash on the node row
      if (!(n && n.outdated)) { Store.nodeUpdFlash = { id: nodeId, until: Date.now() + 5000 }; Store.apply(); setTimeout(() => Store.apply(), 5100); }
    }
    else if (r.data && r.data.panel_outdated) toast("Update available — v" + r.data.latest_remote, "ok");
    else { Store.updFlash = Date.now() + 5000; Store.apply(); setTimeout(() => Store.apply(), 5100); }   // panel up to date → green "up to date" tag for 5s
  } finally { if (btn) btn.classList.remove("checking"); }
}
function NodeCard({ n, reorder }) {
  const it = reorder ? reorder.item(n.id) : null;
  const st = n.status || "dangling";
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === n.id));
  const onl = here.filter(p => p.targets.some(t => t.node === n.id && t.online)).length;
  const snap = Store.stats[n.id];
  const tps = (snap && snap.turn_proxies) || [];
  const ifTags = ifaceTags(n.id);   // every interface tag, one wrapping line
  const turnChip = tp => html`<span class=${"tg tg-turn tf-" + turnFork(tp.service) + ((nodeStale(n.id) || turnDown(tp)) ? " muted" : "")}>${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`;
  const h = n.health, hasCpu = h && Array.isArray(h.load);
  const l1 = hasCpu ? (h.load[0] || 0) : 0, cpctRaw = l1 / ((h && h.ncpu) || 1) * 100, cpct = Math.min(100, cpctRaw);   // cpctRaw (uncapped) colours the bar+number green→red like the graph; cpct caps the bar width
  const removing = n.removing;
  const ndown = st !== "online" && !inProc(n.proc_status);    // genuinely not reporting (recover state) → mirror the detail: disable card actions
  const nblocked = st !== "online" || inProc(n.proc_status);  // down OR mid convert/re-install
  // list-card update tag: a co-located node updates WITH the panel (its "updating" comes from hostUpdating, not
  // its own proc_status) — mirror the detail's dh-ver so the LIST shows "updating" too, while a terminal wins.
  const nUpdating = n.updating || (n.local && (hostUpdating || inProc(Store.hostProc)));
  const procEff = (n.proc_status && !inProc(n.proc_status)) ? n.proc_status : (nUpdating ? "updating" : n.proc_status);
  const nav = () => go("#/node/" + encodeURIComponent(n.id));
  return html`<div class=${"ncard clk" + (removing ? " removing" : "") + (it ? it.cls : "")} onClick=${nav} data-rid=${it ? it.rid : null}>
    <div class="nc-gutter">${reorder ? html`<span class="drag-grip" title="Drag to reorder" onClick=${e => e.stopPropagation()} ...${reorder.grip(n.id)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}</div>
    <div class="nc-name">
      ${!n.uninstalled && (n.outdated || (n.local && Store.panelOutdated)) && !n.updating ? html`<span class="upd-dot" title="Update available — open the node to update"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}
      <span class="nname">${n.name}</span>
      ${n.kind ? html`<span class=${"tport " + n.kind}>${n.kind === "docker" ? "docker" : "bare-metal"}</span>` : null}
      ${n.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> uninstalled</span>`
        : st === "online" ? html`<span class="reporting">reporting</span>`
        : st === "offline" ? html`<span class="nstat offline"><${Ic} i="info"/> offline</span>`
        : html`<span class="nstat enroll"><${Ic} i="clock"/> awaiting enroll</span>`}${procEff ? procTag(procEff, e => { e.stopPropagation(); e.preventDefault(); dismissNodeProc(n.id); }, n.proc_err, st !== "online" && st !== "offline") : null}
      <span style="margin-left:8px"><${HealthDot} issues=${n.issues}/></span>
      ${removing ? html`<span class="nstat removing" style="margin-left:14px"><${Ic} i="trash"/> flagged for removal</span>` : null}
    </div>
    <div class="nc-mesh nm-item">${(n.mesh_peers || []).length ? html`<${MeshStat} nodeId=${n.id} mode="both"/>` : null}</div>
    <div class="nc-cpu nm-item"><span class="nm-l">CPU load</span>${hasCpu ? html`<span class="nm-cpu"><span class="hm-bar"><i class="hm-fill" style=${"width:" + cpct + "%;background:" + loadColor(cpctRaw)}></i></span><span class="nm-v" style=${"color:" + loadColor(cpctRaw)}>${l1.toFixed(2)}</span></span>` : html`<span class="nm-v faint">—</span>`}</span>
    <button class="iconbtn nc-ctl" disabled=${nblocked} title=${nblocked ? "Unavailable while the node is down / converting" : "Node settings"} onClick=${e => { e.stopPropagation(); openNodeEdit(n); }}><${Ic} i="gear"/></button>

    <span class="nc-peers nm-item">${here.length
      ? html`<${OnlinePeersTag} nodeId=${n.id} orphans=${orphCount(n.id, null)} cls="nm-peerpop"
          trigger=${() => html`<span class="nm-l">Peers</span><span class="nm-v nm-peers"><b class=${"oncount" + (onl ? " on" : "")}>${onl}</b><small>/${here.length}</small></span>`}/>`
      : html`<span class="nm-l">Peers</span><span class="nm-v nm-peers faint">none</span>`}</span>
    <div class="nc-ifaces nm-item"><span class="nm-l">Interfaces</span><span class="tags">${ifTags.length ? ifTags : html`<span class="nm-v faint">—</span>`}</span></div>
    <span class="nc-thru nm-thru"><span class="nm-l">Throughput</span>${st === "online"
      ? html`<span class=${"nm-v thru" + ((n.rx_speed || 0) + (n.tx_speed || 0) > 0 ? "" : " idle")}><span class="down">↓ ${rate(dlul(n.rx_speed, n.tx_speed)[0])}</span><span class="up">↑ ${rate(dlul(n.rx_speed, n.tx_speed)[1])}</span></span>`
      : html`<span class="nm-v faint">—</span>`}</span>
    <button class="iconbtn nc-ctl danger" title=${removing ? "Force remove" : "Remove node"} onClick=${e => { e.stopPropagation(); openNodeRemove(n); }}><${Ic} i="trash"/></button>

    ${turnEnabled() && tps.length ? html`<div class="nc-turn nm-item"><span class="nm-l">Turn-proxies</span><span class="tags">${tps.map(turnChip)}</span></div>` : null}
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

const AWG_KEYS = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1"];
// client-side AmneziaWG obfuscation generator — mirrors the panel's gen_awg_params (for the "Generate" button)
function genAwg() {
  const r = n => Math.floor(Math.random() * n), w = 15;
  let s1 = 15 + r(135), s2 = 15 + r(135);
  while (s2 === s1 || s2 === s1 + 56) s2 = 15 + r(135);
  const b = [5, 1e9, 2e9, 3e9].map(base => base + r(9e8));
  return { Jc: 4, Jmin: 40, Jmax: 70, S1: s1, S2: s2, S3: 15 + r(85), S4: 15 + r(85),
    H1: `${b[0]}-${b[0] + w}`, H2: `${b[1]}-${b[1] + w}`, H3: `${b[2]}-${b[2] + w}`, H4: `${b[3]}-${b[3] + w}`,
    I1: "<b 0xc300000001><r 1200>" };
}
// labelled grid of the 12 AWG fields — read-only display (node settings) or editable (panel settings).
function AwgGrid({ value, onChange, readOnly }) {
  const v = value || {};
  // J / S / H / I as columns, fields stacked — same layout as the interface AWG display
  return html`<div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span>${readOnly
    ? html`<span class="awg-val">${v[k] != null && v[k] !== "" ? v[k] : "—"}</span>`
    : html`<input value=${v[k] ?? ""} onInput=${e => onChange({ ...v, [k]: e.target.value })} spellcheck="false"/>`}</label>`)}</div>`)}</div>`;
}

function PanelSettingsScreen() {
  // NOTE: deliberately NOT subscribed to the 5s poll (no useStore) — this is an edit form seeded from a
  // snapshot at mount. Re-rendering every poll re-diffs every controlled input (the source of the checkbox
  // repaint flicker) and is pointless for a form; it still re-renders on its own edits (setNodeEdits etc.),
  // and save() re-polls + reseeds. A node added/renamed mid-edit just won't reflect until you re-enter.
  const ps = Store.panelSettings || {};
  const idf = ps.interface_defaults || {}; const mir = ps.mirrors || {}; const adv = ps.advanced || {};
  const [dns, setDns] = useState((idf.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(idf.mtu || 1280));
  const [ka, setKa] = useState(String(idf.keepalive || 25));
  const [geoMir, setGeoMir] = useState(mir.geo || "");
  const [turnMir, setTurnMir] = useState(mir.turn || "");
  // Geo-data: catalog provider enable/disable + scheduled list refresh (replacing the geo mirror).
  const _provReg = Store.catalogProviders || [];
  const [provEnabled, setProvEnabled] = useState(() => Object.fromEntries(_provReg.map(p => [p.id, p.enabled !== false])));
  const _gu = ps.geo_update || {};
  const [guEvery, setGuEvery] = useState(String(_gu.every_days == null ? 1 : _gu.every_days));
  const [guAt, setGuAt] = useState(_gu.at || "04:00");
  const [geoUpdating, setGeoUpdating] = useState(false);   // "Update all lists now" in flight → poll provider status
  const updateAllLists = async () => {
    setGeoUpdating(true);
    const r = await api.geoUpdate();
    if (!r || !r.ok) { setGeoUpdating(false); return toast((r && r.error) || "Couldn't start update", "err"); }
    // poll /api/state until no provider is still "updating" (or a 25s cap)
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.status === "updating");
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500);
      setGeoUpdating(false); };
    setTimeout(tick, 1500);
  };
  const [sc, setSc] = useState(ps.store_configs === false ? "off" : "on");   // ON and "default" merged — both keep configs
  const [tput, setTput] = useState(ps.throughput_perspective === "peers" ? "peers" : "nodes");
  const [staleS, setStaleS] = useState(String(Math.round((adv.node_stale_ms || 30000) / 1000)));
  const [graceS, setGraceS] = useState(String(Math.round((adv.peer_grace_ms || 60000) / 1000)));
  const [ttlD, setTtlD] = useState(String(adv.geo_ttl_days || 3));
  const [hidden, setHidden] = useState(new Set(ps.hidden_categories || []));   // built-in categories hidden from the routing dropdown
  const [lists, setLists] = useState((ps.custom_lists || []).map(l => ({ ...l, _rid: newRid(), targets: [...(l.domains || []), ...(l.cidrs || [])].join(", ") })));
  const [turnEnabledS, setTurnEnabledS] = useState(ps.turn_enabled !== false);   // master turn-proxy switch
  const [turnForks, setTurnForks] = useState(new Set(ps.enabled_turn_forks || ["WINGS-N", "anton48"]));   // forks offered in the install picker
  const [vkLinkS, setVkLinkS] = useState(ps.vk_link || "");   // VK call link baked into generated turn-proxy client configs
  // ---- themed colour pickers ({dark,light} each) — Interfaces / Display / Turn sections ----
  const asThemed = (v, dd, dl) => (v && typeof v === "object") ? { dark: v.dark || dd, light: v.light || dl } : { dark: v || dd, light: v || dl };
  const sameThemed = (a, dd, dl) => (a.dark || "").toLowerCase() === dd.toLowerCase() && (a.light || "").toLowerCase() === dl.toLowerCase();
  const _provColDefault = p => { const d = CAT_PROVIDER_DEFAULTS[p] || { color: "#8FA8C0", colorL: "#5E7085" }; return { dark: d.color, light: d.colorL }; };
  const [provColors, setProvColors] = useState(() => Object.fromEntries(_provReg.map(p => [p.id, asThemed((ps.provider_colors || {})[p.id], _provColDefault(p.id).dark, _provColDefault(p.id).light)])));
  const provColorOverrides = () => { const o = {}; for (const p of _provReg) { const d = _provColDefault(p.id); const t = asThemed(provColors[p.id], d.dark, d.light); if (!sameThemed(t, d.dark, d.light)) o[p.id] = t; } return o; };
  const [forkColors, setForkColors] = useState(() => Object.fromEntries(TURN_FORKS.map(f => [f.id, asThemed((ps.turn_fork_colors || {})[f.id], f.color, f.colorL)])));
  const [ifaceColors, setIfaceColors] = useState(() => ({
    wg: asThemed((ps.iface_colors || {}).wg, IFACE_COLOR_DEFAULTS.wg.dark, IFACE_COLOR_DEFAULTS.wg.light),
    awg: asThemed((ps.iface_colors || {}).awg, IFACE_COLOR_DEFAULTS.awg.dark, IFACE_COLOR_DEFAULTS.awg.light) }));
  const [themeColorS, setThemeColorS] = useState(clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false));         // dark-mode accent (shown = applied)
  const [themeColorLightS, setThemeColorLightS] = useState(clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true));   // light-mode accent
  const themeVal = { dark: themeColorS, light: themeColorLightS };   // the theme accent as one themed swatch
  // peer-health DETECTION toggles (not colours): each condition ON by default; unchecking stops it flagging the status.
  const _sc = ps.status_conditions || {};
  const [statusConds, setStatusConds] = useState({ blocked: _sc.blocked !== false, faulty: _sc.faulty !== false });
  // overrides derived from a raw source (state OR the stored panel-settings), normalized identically so a legacy
  // single-colour value in panel-settings compares equal to its normalized {dark,light} form (no phantom "dirty").
  const forkOvFrom = src => { const o = {}; for (const f of TURN_FORKS) { const t = asThemed((src || {})[f.id], f.color, f.colorL); if (!sameThemed(t, f.color, f.colorL)) o[f.id] = t; } return o; };
  const ifaceOvFrom = src => { const o = {}; for (const k of ["wg", "awg"]) { const t = asThemed((src || {})[k], IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light); if (!sameThemed(t, IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light)) o[k] = t; } return o; };
  const forkColorOverrides = () => forkOvFrom(forkColors);
  const ifaceColorOverrides = () => ifaceOvFrom(ifaceColors);
  const statusCondsOut = () => ({ blocked: statusConds.blocked, faulty: statusConds.faulty });
  const themeColorOut = () => themeColorS.toLowerCase() === THEME_COLOR_DEFAULT.toLowerCase() ? "" : themeColorS;
  const themeColorLightOut = () => themeColorLightS.toLowerCase() === THEME_COLOR_LIGHT_DEFAULT.toLowerCase() ? "" : themeColorLightS;
  // deployed version(s) of a fork across the fleet (from snapshots) — "" if it's never been installed
  const forkVersions = fid => { const v = new Set(); for (const snap of Object.values(Store.stats || {})) for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid && tp.version) v.add(tp.version); return [...v]; };
  // per-NODE view of a fork for the hover bubble: one row per node carrying its version + whether it's mid-update
  // (a shared per-fork binary → one version/node; updating if ANY of its instances is installing or Update-clicked).
  const forkNodeStates = fid => {
    const m = {};   // nodeId -> {version, installing (real, clears when done), updatePending (Update-clicked, 120s hint)}
    for (const [nid, snap] of Object.entries(Store.stats || {}))
      for (const tp of (snap.turn_proxies || [])) {
        if (!tp.service || turnFork(tp.service) !== fid) continue;
        const cur = m[nid] || { version: "", installing: false, updatePending: false };
        if (tp.version) cur.version = tp.version;
        if (tp.installing) cur.installing = true;
        const uk = nid + "|" + tp.service;
        if (turnUpdating[uk] && Date.now() < turnUpdating[uk]) cur.updatePending = true;
        m[nid] = cur;
      }
    return Object.entries(m).map(([node, v]) => ({ node, ...v })).sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node)));
  };
  const [turnCheck, setTurnCheck] = useState({});   // {forkId: {status:'checking'|'uptodate'|'update', latest}}
  const checkTurnUpdates = async () => {
    setTurnCheck(Object.fromEntries(TURN_FORKS.map(f => [f.id, { status: "checking" }])));
    const r = await api.turnCheckUpdates({ forks: TURN_FORKS.map(f => ({ id: f.id, owner: f.owner })) });
    const latest = (r && r.ok && r.data.latest) || {};
    const next = {};
    for (const f of TURN_FORKS) {
      const lt = latest[f.id] || "", dep = forkVersions(f.id);
      next[f.id] = (lt && dep.length && dep.some(v => v !== lt)) ? { status: "update", latest: lt } : { status: "uptodate" };
    }
    setTurnCheck(next);
    setTimeout(() => setTurnCheck(c => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, v.status === "update" ? v : {}]))), 5000);   // "up to date" clears after 5s; "update" persists
  };
  // update every deployed instance of a fork to `latest` — reinstall (re-download binary) on each (node,service)
  const updateFork = async (fid, latest) => {
    const owner = (TURN_FORKS.find(x => x.id === fid) || {}).owner || "";
    const targets = [];
    for (const [nid, snap] of Object.entries(Store.stats || {})) for (const tp of (snap.turn_proxies || [])) if (tp.service && turnFork(tp.service) === fid) targets.push({ node: nid, service: tp.service });
    if (!targets.length) return;
    setTurnCheck(c => ({ ...c, [fid]: { status: "updating", latest } }));
    turnUpdateTarget[fid] = { ver: latest, until: Date.now() + 120000 };   // persists past the turnCheck reset so the bubble can show per-node updating→updated
    for (const t of targets) { turnUpdating[t.node + "|" + t.service] = Date.now() + 120000; await api.turnReinstall({ node: t.node, service: t.service, owner }); }
    await Store.poll();
    setTurnCheck(c => ({ ...c, [fid]: {} }));
    toast("Update requested on " + targets.length + " proxy" + (targets.length > 1 ? "ies" : "") + " — each node applies it on its next sync.", "ok");
  };
  // Security (panel login) — folded into the unified Save: credentials update on Save (if changed), and a
  // validation error blocks Save. Username is loaded from the server once on mount.
  const [secUser, setSecUser] = useState(""); const [secOrigUser, setSecOrigUser] = useState("");
  const [secCur, setSecCur] = useState(""); const [secNp, setSecNp] = useState(""); const [secNp2, setSecNp2] = useState("");
  const [secAuth, setSecAuth] = useState(true);   // false = panel has no login configured (fields disabled)
  useEffect(() => { api.account().then(r => { if (r && r.ok) { setSecAuth(r.data.auth_enabled !== false); if (r.data.username) { setSecUser(r.data.username); setSecOrigUser(r.data.username); } } }); }, []);
  const secChanged = () => secAuth && (secUser.trim() !== secOrigUser || !!secNp);
  const secErr = () => {
    if (!secAuth || !secChanged()) return null;
    if (!secUser.trim()) return "Username can't be empty.";
    if (secUser.includes(":")) return "Username can't contain a colon.";
    if (!secCur) return "Enter your current password to confirm the change.";
    if (secNp && secNp !== secNp2) return "New passwords don't match.";
    if (secNp && secNp.length < 8) return "New password must be at least 8 characters.";
    return null;
  };
  const [section, setSection] = useState("display");   // active left-rail section
  const rsv = ps.reserved || {};
  const [rsvSubnet, setRsvSubnet] = useState(rsv.mesh_subnet || "10.255.0.0/16");
  const [rsvPort, setRsvPort] = useState(String(rsv.mesh_port_base || 9999));
  const [rsvPrefix, setRsvPrefix] = useState(rsv.iface_prefix || "swg_");
  const [awg, setAwg] = useState(ps.mesh_awg || {});
  const [showAwg, setShowAwg] = useState(false);
  const awgSet = AWG_KEYS.some(k => String(awg[k] ?? "").trim() !== "");
  const [showAdv, setShowAdv] = useState(false);
  const [msg, setMsg] = useState(null);
  // per-node pending edits (mode / mesh / egress) — lifted here so switching node or section keeps unsaved
  // changes; the single Save commits the global settings AND one nodeUpdate per changed node.
  const eq = (a, b) => { const c = v => v == null ? "" : Array.isArray(v) ? JSON.stringify([...v].sort()) : typeof v === "object" ? JSON.stringify(Object.keys(v).sort().reduce((o, k) => (o[k] = v[k], o), {})) : String(v); return c(a) === c(b); };
  const nFields = n => ({ routing_mode: n.routing_mode || "kernel", endpoint_host: n.endpoint_host || "",
    mesh_subnet: n.mesh_subnet || "", mesh_port: n.mesh_port ? String(n.mesh_port) : "", mesh_prefix: n.mesh_prefix || "",
    default_egress_ip: n.default_egress_ip || "", panel_ip: n.panel_ip || "",
    enabled_categories: (n.enabled_categories && n.enabled_categories.length) ? [...n.enabled_categories] : null,   // null = all built-ins enabled for this node
    catalog_cats: [...(n.catalog_cats || [])],   // provider-catalog categories opted into on this node (node-lens; separate from the 26 built-ins)
    mesh_awg: (n.mesh_awg_set && Object.keys(n.mesh_awg_set).length) ? { ...n.mesh_awg_set } : {} });   // per-node mesh obfuscation override ({} = inherit/auto)
  const [nodeEdits, setNodeEdits] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [orig, setOrig] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const setNV = (nid, patch) => setNodeEdits(e => ({ ...e, [nid]: { ...nFields((Store.nodes || []).find(n => n.id === nid) || {}), ...(e[nid] || {}), ...patch } }));
  const nv = (nid, f) => (nodeEdits[nid] || {})[f];
  const [saved, setSaved] = useState(0);   // timestamp; the green "All settings saved" flash shows while now < saved
  const save = async () => {
    setMsg({ ok: true, t: "Saving…" });
    if (SECTIONS.some(([s]) => glDirty(s))) {   // only rewrite panel_settings when a GLOBAL setting actually changed (nodes go via nodeUpdate below)
      const r = await api.panelSettings({
        interface_defaults: { dns: dns.split(",").map(s => s.trim()).filter(Boolean), mtu: +mtu || 1280, keepalive: +ka || 25 },
        mirrors: { geo: geoMir.trim(), turn: turnMir.trim() },
        providers: provEnabled,
        provider_colors: provColorOverrides(),
        geo_update: { every_days: Math.max(0, Math.min(30, parseInt(guEvery) || 0)), at: guAt },
        store_configs: sc === "off" ? false : true,
        throughput_perspective: tput,
        reserved: { mesh_subnet: rsvSubnet.trim(), mesh_port_base: +rsvPort || 9999, iface_prefix: rsvPrefix.trim() || "swg_" },
        mesh_awg: awgSet ? awg : {},
        advanced: { node_stale_ms: (+staleS || 30) * 1000, peer_grace_ms: (+graceS || 60) * 1000, geo_ttl_days: +ttlD || 3 },
        hidden_categories: [...hidden],
        custom_lists: lists.map(({ _rid, domains, cidrs, ...l }) => l),   // send id/title/targets/enabled; backend re-derives domains+cidrs
        turn_enabled: turnEnabledS,
        enabled_turn_forks: [...turnForks],
        turn_fork_colors: forkColorOverrides(),
        iface_colors: ifaceColorOverrides(),
        status_conditions: statusCondsOut(),
        theme_color: themeColorOut(),
        theme_color_light: themeColorLightOut(),
        vk_link: vkLinkS.trim(),
      });
      if (!r.ok) return setMsg({ ok: false, t: r.error || "Failed to save." });
    }
    // per-node changes: one nodeUpdate per node whose edits differ from the saved baseline
    const dSub = rsvSubnet.trim(), dPort = String(+rsvPort || 9999), dPfx = rsvPrefix.trim() || "swg_";
    let nerr = null;
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {};
      if (!Object.keys(nFields(n)).some(k => !eq(e[k], o[k]))) continue;
      const nr = await api.nodeUpdate({ id: n.id, routing_mode: e.routing_mode, endpoint_host: (e.endpoint_host || "").trim(),
        mesh_subnet: (e.mesh_subnet || "").trim() === dSub ? "" : (e.mesh_subnet || "").trim(),
        mesh_port: (e.mesh_port || "").trim() === dPort ? "" : (e.mesh_port || "").trim(),
        mesh_prefix: (e.mesh_prefix || "").trim() === dPfx ? "" : (e.mesh_prefix || "").trim(),
        default_egress_ip: e.default_egress_ip || "", panel_ip: e.panel_ip || "",
        enabled_categories: e.enabled_categories || [], catalog_cats: e.catalog_cats || [], mesh_awg: e.mesh_awg || {} });
      if (!nr.ok) nerr = nr.error || ("Couldn't save " + n.name);
    }
    if (nerr) return setMsg({ ok: false, t: nerr });
    // credentials (if changed) — last, since a username/password change re-auths and forces a reload
    if (secChanged()) {
      const ar = await api.accountSave({ username: secUser.trim(), current_password: secCur, new_password: secNp });
      if (!ar.ok) return setMsg({ ok: false, t: ar.error || "Couldn't update credentials." });
      setMsg({ ok: true, t: "Saved. Reloading — sign in with your new credentials…" });
      return setTimeout(() => location.reload(), 1400);
    }
    setMsg(null); setSaved(Date.now() + 4000);   // green "All settings saved" flash in the header
    await Store.poll();
    const fresh = Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)]));
    setNodeEdits(fresh); setOrig(fresh);
  };
  // Save click → confirm modal listing the modified values + a reprovisioning warning, then commit.
  const REPROV_WARN = "Heads up: changing a node's mesh subnet, interface prefix, or AWG params re-provisions its mesh links — it briefly drops off the mesh while every peer pulls the new config and reconnects.";
  const diffList = () => {
    const out = [];
    if (glDirty("routing")) out.push("Routing lists — built-in / custom");
    if (secChanged()) out.push("Authentication — panel credentials");
    if (glDirty("turn")) out.push("Turn proxies — forks / colours / VK link");
    if (glDirty("geo")) out.push("Geo data");
    if (glDirty("defaults")) out.push("Interfaces — colours / defaults");
    if (glDirty("configs")) out.push("Client configs → " + (sc === "off" ? "off" : "on"));
    if (glDirty("display")) out.push("Display — theme / status timing");
    if (glDirty("mesh")) out.push("System mesh defaults");
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}, fl = [];
      if (!eq(e.routing_mode, o.routing_mode)) fl.push("mode → " + e.routing_mode);
      if (!eq(e.endpoint_host, o.endpoint_host)) fl.push("ingress IP → " + (e.endpoint_host || "auto"));
      if (!eq(e.mesh_subnet, o.mesh_subnet)) fl.push("mesh subnet → " + (e.mesh_subnet || "default"));
      if (!eq(e.mesh_port, o.mesh_port)) fl.push("mesh port → " + (e.mesh_port || "default"));
      if (!eq(e.mesh_prefix, o.mesh_prefix)) fl.push("prefix → " + (e.mesh_prefix || "default"));
      if (!eq(e.default_egress_ip, o.default_egress_ip)) fl.push("egress IP → " + (e.default_egress_ip || "auto"));
      if (!eq(e.panel_ip, o.panel_ip)) fl.push("panel IP → " + (e.panel_ip || "auto"));
      if (!eq(e.enabled_categories, o.enabled_categories)) fl.push("enabled lists");
      if (!eq(e.catalog_cats, o.catalog_cats)) fl.push("catalog categories");
      if (!eq(e.mesh_awg, o.mesh_awg)) fl.push("mesh AWG params");
      if (fl.length) out.push(n.name + " — " + fl.join(", "));
    }
    return out;
  };
  const needsReprov = () => (Store.nodes || []).some(n => { const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}; return !eq(e.mesh_subnet, o.mesh_subnet) || !eq(e.mesh_prefix, o.mesh_prefix) || !eq(e.mesh_awg, o.mesh_awg); });
  const confirmSave = () => {
    const ch = diffList();
    if (!ch.length) { toast("No changes to save.", "ok"); return; }
    const rp = needsReprov();
    openConfirm({ title: "Save settings", confirmLabel: "Save", warn: rp, onConfirm: save,
      body: html`<div class="savediff"><div class="savediff-h">${ch.length} change${ch.length === 1 ? "" : "s"} to apply:</div><ul>${ch.map(c => html`<li>${c}</li>`)}</ul>${rp ? html`<div class="savediff-w">${REPROV_WARN}</div>` : null}</div>` });
  };
  const refreshGeo = async () => { const r = await api.refreshGeo(); toast(r.ok ? "Geo lists will refresh on each node's next sync." : (r.error || "Failed"), r.ok ? "ok" : "err"); };
  const setList = (rid, patch) => setLists(ls => ls.map(l => l._rid === rid ? { ...l, ...patch } : l));
  // Custom lists AUTOSAVE on add/edit/delete — they persist on their own (POST just custom_lists), no global Save needed.
  // Re-baseline the local rows from the server afterwards so the row content + the routing dirty-state both stay correct.
  const persistLists = async newLists => {
    setLists(newLists);
    const r = await api.panelSettings({ custom_lists: newLists.map(({ _rid, domains, cidrs, ...l }) => l) });
    if (!r.ok) return setMsg({ ok: false, t: r.error || "Couldn't save the list." });
    await Store.poll();
    const ridById = Object.fromEntries(newLists.filter(l => l.id).map(l => [l.id, l._rid]));   // keep row identity so a per-node toggle / edit doesn't remount every row
    setLists(((Store.panelSettings || {}).custom_lists || []).map(l => ({ ...l, _rid: ridById[l.id] || newRid(), targets: [...(l.domains || []), ...(l.cidrs || [])].join(", ") })));
    setSaved(Date.now() + 2500);
  };
  const openList = l => openModal(html`<${CustomListSheet} list=${l} onSave=${nl => persistLists(l ? lists.map(x => x._rid === nl._rid ? nl : x) : [...lists, nl])} onDelete=${l ? () => persistLists(lists.filter(x => x._rid !== l._rid)) : null} onClose=${closeModal}/>`);
  const toggleCat = (id, on) => setHidden(h => { const n = new Set(h); on ? n.delete(id) : n.add(id); return n; });
  const SECTIONS = [["display", "Display"], ["security", "Authentication"], ["configs", "Client configs"], ["mesh", "System mesh"], ["nodesegress", "Nodes egress"], ["defaults", "Interfaces"], ["turn", "Turn proxies"], ["routing", "Routing lists"], ["geo", "Geo data"]];
  const sysCats = SMART_CATEGORIES.filter(([id]) => id !== "all" && id !== "custom");
  const entryCount = t => (t || "").split(/[\s,]+/).filter(Boolean).length;
  const entryPreview = t => {   // as many WHOLE entries as fit ~one line, then a "(N more)" tail — never cuts an entry
    const items = (t || "").split(/[\s,]+/).filter(Boolean);
    const shown = []; let len = 0;
    for (const it of items) {
      const add = (shown.length ? 2 : 0) + it.length;   // ", " separator
      if (shown.length && len + add > 52) break;         // always keep ≥1, then stop before overflow
      shown.push(it); len += add;
    }
    return { text: shown.join(", "), more: items.length - shown.length };
  };
  // per-node context: the node whose mode/lists/mesh/egress we're editing — defaults to the first node (no "default")
  const [selNode, setSelNode] = useState(() => ((Store.nodes || [])[0] || {}).id || "");
  const perNodeSection = section === "routing" || section === "mesh" || section === "nodesegress";
  const nodeRec = (Store.nodes || []).find(n => n.id === selNode);
  const nodeMode = nv(selNode, "routing_mode") || "kernel";
  const setMode = m => setNV(selNode, { routing_mode: m });
  const ecOf = nid => nv(nid, "enabled_categories");               // per-node enabled built-ins (null = all)
  const catOn = id => { const ec = ecOf(selNode); return !ec || ec.includes(id); };
  const toggleNodeCat = (id, on) => { if (nodeMode === "kernel" && catHostOnly(id)) return; const all = sysCats.map(([c]) => c); let ec = ecOf(selNode); if (ec == null) ec = all.slice(); ec = on ? [...new Set([...ec, id])] : ec.filter(c => c !== id); setNV(selNode, { enabled_categories: ec.length >= all.length ? null : ec }); };
  // node-lens for the provider catalog: catalog_cats[] = the categories the operator opted THIS node into (staged; commits on Save)
  const ccOf = nid => nv(nid, "catalog_cats") || [];
  const addCatalogCat = id => { if (!id || SMART_CAT_LABEL[id] || (lists || []).some(l => l.id === id) || id === "custom") return; setNV(selNode, { catalog_cats: [...new Set([...ccOf(selNode), id])] }); };
  const removeCatalogCat = id => setNV(selNode, { catalog_cats: ccOf(selNode).filter(c => c !== id) });
  // dirty tracking — per global section + per node-per-section, drives the rail dots and badge glow
  const SECF = { routing: ["routing_mode", "enabled_categories", "catalog_cats"], mesh: ["endpoint_host", "mesh_subnet", "mesh_port", "mesh_prefix", "mesh_awg"], nodesegress: ["default_egress_ip", "panel_ip"] };
  const nodeDirty = (nid, sec) => (SECF[sec] || []).some(f => !eq((nodeEdits[nid] || {})[f], (orig[nid] || {})[f]));
  const listsJSON = ls => JSON.stringify((ls || []).map(l => ({ id: l.id || "", title: l.title || "", enabled: l.enabled !== false, targets: (l.targets ?? [...(l.domains || []), ...(l.cidrs || [])].join(", ")).trim() })));
  const glDirty = sec =>
    sec === "routing" ? ([...hidden].sort().join() !== (ps.hidden_categories || []).slice().sort().join() || listsJSON(lists) !== listsJSON(ps.custom_lists || [])) :
    sec === "turn" ? (turnEnabledS !== (ps.turn_enabled !== false) || [...turnForks].sort().join() !== (ps.enabled_turn_forks || ["WINGS-N", "anton48"]).slice().sort().join() || JSON.stringify(forkColorOverrides()) !== JSON.stringify(forkOvFrom(ps.turn_fork_colors)) || vkLinkS.trim() !== (ps.vk_link || "")) :
    sec === "security" ? secChanged() :
    sec === "geo" ? (JSON.stringify(provEnabled) !== JSON.stringify(Object.fromEntries((Store.catalogProviders || []).map(p => [p.id, p.enabled !== false]))) || JSON.stringify(provColorOverrides()) !== JSON.stringify(ps.provider_colors || {}) || String(Math.max(0, parseInt(guEvery) || 0)) !== String(_gu.every_days == null ? 1 : _gu.every_days) || guAt !== (_gu.at || "04:00")) :
    sec === "defaults" ? (dns !== (idf.dns || []).join(", ") || mtu !== String(idf.mtu || 1280) || ka !== String(idf.keepalive || 25) || JSON.stringify(ifaceColorOverrides()) !== JSON.stringify(ifaceOvFrom(ps.iface_colors)) || JSON.stringify(statusCondsOut()) !== JSON.stringify({ blocked: (ps.status_conditions || {}).blocked !== false, faulty: (ps.status_conditions || {}).faulty !== false })) :
    sec === "configs" ? (sc !== (ps.store_configs === false ? "off" : "on")) :
    sec === "display" ? (tput !== (ps.throughput_perspective === "peers" ? "peers" : "nodes") || staleS !== String(Math.round((adv.node_stale_ms || 30000) / 1000)) || graceS !== String(Math.round((adv.peer_grace_ms || 60000) / 1000)) || themeColorS.toLowerCase() !== clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false).toLowerCase() || themeColorLightS.toLowerCase() !== clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true).toLowerCase()) :
    sec === "mesh" ? (rsvSubnet !== (rsv.mesh_subnet || "10.255.0.0/16") || rsvPort !== String(rsv.mesh_port_base || 9999) || rsvPrefix !== (rsv.iface_prefix || "swg_") || JSON.stringify(awgSet ? awg : {}) !== JSON.stringify(ps.mesh_awg || {})) : false;
  const secDirty = sec => glDirty(sec) || (SECF[sec] ? (Store.nodes || []).some(n => nodeDirty(n.id, sec)) : false);
  const badgeDirty = nid => nid === "" ? glDirty(section) : nodeDirty(nid, section);
  const anyDirty = SECTIONS.some(([s]) => secDirty(s));
  // Unsaved-changes guard: warn before leaving (in-app nav via the router, the Back button, or a browser refresh/close)
  const dirtyRef = useRef(anyDirty); dirtyRef.current = anyDirty;
  useEffect(() => {
    _unsavedGuard = () => dirtyRef.current;
    const bu = e => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", bu);
    return () => { _unsavedGuard = null; window.removeEventListener("beforeunload", bu); };
  }, []);
  const leaveSettings = () => { if (!anyDirty || confirm("You have unsaved changes that will be lost. Leave without saving?")) { _unsavedGuard = null; history.back(); } };
  const MODES = [
    ["kernel", "Default — IP only, DNS is not involved", "Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it. Lists: GeoIP + Custom IPs."],
    ["forcedns", "Force DNS — Host + IP, overrides encrypted DNS", "The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. Lists: GeoSite (host) + GeoIP + Custom IPs/domains."],
    ["sni", "SNI router — Host + IP, DNS stays private", "Routes by hostname by reading the SNI from each TLS handshake, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing. Lists: GeoSite (host) + GeoIP + Custom IPs/domains."],
  ];
  return html`<div class="screen setscreen">
    <div class="sethead"><b>Panel settings</b></div>
    ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
    <div class="setbody">
      <nav class="setrail">${SECTIONS.map(([id, lbl]) => html`<button class=${"setrail-i" + (section === id ? " on" : "")} onClick=${() => setSection(id)}>${lbl}${secDirty(id) ? html`<span class="dirtydot"></span>` : null}</button>`)}</nav>
      <div class="setpane">
        ${perNodeSection && (Store.nodes || []).length ? html`<div class="setnodes">${(Store.nodes || []).map(n => html`<button class=${"snbadge" + (selNode === n.id ? " on" : "") + (badgeDirty(n.id) ? " dirty" : "")} style=${"--c:" + Store.nodeColor(n.id)} onClick=${() => setSelNode(n.id)}><span class="ndot"></span>${n.name}</button>`)}</div>` : null}
        ${section === "routing" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">${nodeRec ? nodeRec.name : "Node"} — match mode</div>
          <p class="hint" style="margin:0 0 12px">Select how this node matches smart-routing traffic — by destination <b>IP</b>, or by <b>hostname</b> (via the node's DNS, or read from the TLS handshake). In every mode the traffic stays in-kernel (no userspace proxy); the modes differ only in match precision and in whether they touch your clients' DNS. Changing the mode reconfigures the node (adds or removes its DNS resolver or SNI reader) and changes which lists its interfaces can use.</p>
          ${MODES.map(([id, lbl, exp]) => html`<label class=${"moderow" + (nodeMode === id ? " on" : "")}>
            <input type="radio" name="rmode" checked=${nodeMode === id} onChange=${() => setMode(id)}/>
            <div class="modetxt"><div class="modelbl">${lbl}</div>${nodeMode === id ? html`<div class="modeexp">${exp}</div>` : null}</div></label>`)}
          <div class="seclabel">Provider lists <span class="faint" style="font-weight:400;text-transform:none;letter-spacing:0">— added to <b>${nodeRec ? nodeRec.name : "this node"}</b> from the public catalogs</span></div>
          <p class="hint" style="margin:0 0 8px">Search the catalog (across every enabled provider — manage which in <b>Geo data</b>) and add the lists you want routable on <b>${nodeRec ? nodeRec.name : "this node"}</b>. The same service often comes from several providers; each shows its <b>source</b>, so you can pick who you trust. Added lists appear in this node's interface routing dropdowns. ${nodeMode === "kernel" ? html`In Kernel mode only IP-matchable lists route; domain-only lists stay greyed until you switch to Force-DNS or SNI.` : null}</p>
          <div class="ccchips">${ccOf(selNode).length ? [...ccOf(selNode)].sort((a, b) => catLabelOf(a).toLowerCase().localeCompare(catLabelOf(b).toLowerCase())).map(id => { const cap = catCap(id); const greyed = nodeMode === "kernel" && !cap.ip;
            return html`<span class=${"ccchip" + (greyed ? " off" : "")} key=${id} title=${greyed ? "Domain-only — needs Force-DNS or SNI on this node" : ""}>
              <span class="ccchip-lbl">${catLabelOf(id)}</span>
              ${provLabelOf(id) ? html`<${ProvTag} id=${id}/>` : null}
              ${capBadges(cap)}<${ListInfo} cat=${id}/>
              ${catListUrl(id, cap) ? html`<a class="ccchip-info" href=${catListUrl(id, cap)} target="_blank" rel="noopener" title="View this list on GitHub"><${Ic} i="info"/></a>` : null}
              <button class="ccchip-x" title="Remove from this node" onClick=${() => removeCatalogCat(id)}><${Ic} i="x"/></button>
            </span>`; }) : html`<span class="hint" style="margin:0">No provider lists added to this node yet.</span>`}</div>
          <div style="margin-top:10px"><${CatPicker} addMode=${true} mode=${nodeMode} triggerLabel="Add from catalog" selected=${ccOf(selNode)} onChange=${id => ccOf(selNode).includes(id) ? removeCatalogCat(id) : addCatalogCat(id)}/></div>
          <div class="seclabel">Custom lists <span class="faint" style="font-weight:400;text-transform:none;letter-spacing:0">— your own IPs / domains; the tick enables each on <b>${nodeRec ? nodeRec.name : "this node"}</b></span></div>
          <p class="hint" style="margin:0 0 8px">Shared across the fleet. Edits apply immediately (no schedule) on every node a list is enabled for.</p>
          <div class="ccchips">${lists.length ? [...lists].sort((a, b) => (a.title || "").toLowerCase().localeCompare((b.title || "").toLowerCase())).map(l => { const on = !(l.disabled_nodes || []).includes(selNode); const cap = customCaps(l);
            return html`<span class=${"ccchip" + (on ? "" : " off")} key=${l._rid}>
              <label class="ccchip-tick" title=${on ? "Enabled on " + (nodeRec ? nodeRec.name : "this node") + " — untick to hide" : "Disabled on this node"}><input type="checkbox" checked=${on} onChange=${e => { const v = e.target.checked; persistLists(lists.map(x => x._rid === l._rid ? { ...x, disabled_nodes: v ? (x.disabled_nodes || []).filter(n => n !== selNode) : [...new Set([...(x.disabled_nodes || []), selNode])] } : x)); }}/></label>
              <button class="ccchip-lbl asbtn" onClick=${() => openList(l)} title="Click to edit">${l.title || "Untitled list"}</button>
              <span class="catpick-src legacy">Custom</span>
              ${capBadges(cap)}<${ListInfo} list=${l}/>
            </span>`; }) : html`<span class="hint" style="margin:0">No custom lists yet.</span>`}</div>
          <div style="margin-top:10px"><button class="btn btn-mini" onClick=${() => openList(null)}><${Ic} i="plus"/> Add new list</button></div>
        </div>` : null}
        ${section === "turn" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">Turn proxies<span class="grow"></span>
            ${turnEnabledS ? html`<button class="btn btn-mini" disabled=${Object.values(turnCheck).some(v => v && v.status === "checking")} onClick=${checkTurnUpdates}><${Ic} i="refresh"/> Check for updates</button>` : null}
            <label class="swt" title=${turnEnabledS ? "Turn proxies are on" : "Turn proxies are off"}><input type="checkbox" checked=${turnEnabledS} onChange=${e => setTurnEnabledS(e.target.checked)}/><span class="track"></span><span class="knob"></span></label></div>
          ${!turnEnabledS ? html`<p class="hint" style="margin:0 0 12px"><b class="warntext">Turn proxies are off.</b> Creation buttons and the turn-proxy sections are hidden across the panel. Deployed proxies keep running — they're just not shown here.</p>`
            : html`<p class="hint" style="margin:0 0 12px">Which forks appear in the <b>"Install a fork"</b> picker when you add a proxy to a node, and each fork's colour. Unticking one only <b>hides it from that list</b> — it never touches proxies you've already deployed. ${turnForks.size === 0 ? html`<b class="warntext">No forks are enabled — the install picker will be empty.</b>` : null}</p>`}
          <div class=${"cllist" + (turnEnabledS ? "" : " dimmed")}>${TURN_FORKS.map(f => html`<div class="cl-row" key=${f.id}>
            <label class="chk" title=${"Offer " + f.label + " in the install picker"}><input type="checkbox" checked=${turnForks.has(f.id)} onChange=${e => setTurnForks(s => { const n = new Set(s); e.target.checked ? n.add(f.id) : n.delete(f.id); return n; })}/></label>
            <${ThemedSwatch} val=${forkColors[f.id]} title=${"Colour for " + f.label} onChange=${nv => setForkColors(c => ({ ...c, [f.id]: nv }))}
              sample=${(c) => html`<span class="tg tg-turn" style=${"--tfc:" + c}>${f.label}</span>`}/>
            <span class=${"tf-name tf-" + f.id} style="color:var(--tfc)">${f.label}</span>
            ${(() => {
              const v = forkVersions(f.id); const col = turnColor(f.id);
              if (!v.length) return html`<span class="tf-ver none">not yet used</span>`;
              const nodes = forkNodeStates(f.id); const ut = turnUpdateTarget[f.id]; const latest = (ut && Date.now() < ut.until) ? ut.ver : ((turnCheck[f.id] || {}).latest || null);
              const bub = html`<span class="tf-verpop">
                ${nodes.map(n => html`<span class="tf-vg-node">
                  <span class="tf-vg-dot" style=${"background:" + (Store.nodeColor(n.node) || "var(--ink)")}></span>
                  <span class="tf-vg-nm">${Store.nodeName(n.node)}</span>
                  ${n.installing ? html`<span class="tf-vg-st upd">updating…</span>` : (n.updatePending && latest && n.version === latest) ? html`<span class="tf-vg-st ok"><${Ic} i="check"/>updated</span>` : null}
                </span>`)}
              </span>`;
              return html`<span class="tf-verwrap" style=${"--tfc:" + col}><span class="tf-ver">${v.join(", ")}</span>${bub}</span>`;
            })()}
            ${(() => { const cs = turnCheck[f.id]; if (!cs || !cs.status) return null;
              if (cs.status === "checking") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> checking…</span>`;
              if (cs.status === "updating") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;
              if (cs.status === "update") return html`<button class="tf-chk upd tf-updbtn" title=${"Update every deployed " + f.label + " proxy to " + cs.latest} onClick=${() => updateFork(f.id, cs.latest)}><${Ic} i="download"/> update to ${cs.latest}</button>`;
              return html`<span class="tf-chk ok"><${Ic} i="check"/> up to date</span>`; })()}
            <span class="grow"></span>
            <a class="tf-repo" href=${"https://github.com/" + f.owner} target="_blank" rel="noopener" title=${"Open " + f.owner + " on GitHub"}>${f.owner}</a>
            <span class="cl-caps" title=${forkSupportsAwg(f.id) ? "Works with WireGuard and AmneziaWG interfaces" : f.label + " is WireGuard-only — its client can't front an AmneziaWG interface"}>
              <span class="tg tg-wg">wg</span>${forkSupportsAwg(f.id) ? html`<span class="tg tg-awg">awg</span>` : null}
            </span>
          </div>`)}</div>
          <div class="seclabel" style="margin-top:18px">VK call link</div>
          <p class="hint" style="margin:0 0 8px">Baked into the client configs a peer's <b>Turn</b> button generates — it's the call the turn-proxy relays through. Leave blank to emit a <span class="mono">${"<PASTE VK CALL LINK>"}</span> placeholder.</p>
          <input class="vklink-in" value=${vkLinkS} onInput=${e => setVkLinkS(e.target.value)} placeholder="https://vk.com/call/join/…"/>
        </div>` : null}
        ${section === "geo" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">List providers</div>
          <p class="hint" style="margin:0 0 12px">The public GitHub sources the routing-list catalog draws from. Each node fetches the lists you route directly over HTTPS. <b>Disable</b> a provider to hide its lists from the routing picker — anything already routed from it is <b>kept but greyed</b> (deactivated), and the nodes drop those records until you re-enable it.</p>
          <div class="provlist">${(_provReg.length ? _provReg : []).map(p => { const on = provEnabled[p.id] !== false; return html`<div class=${"provrow" + (on ? "" : " off")} key=${p.id}>
            <label class="swt" title=${on ? "Enabled — its lists are selectable" : "Disabled — its lists are hidden and deactivated on nodes"}>
              <input type="checkbox" checked=${on} onChange=${e => setProvEnabled(m => ({ ...m, [p.id]: e.target.checked }))}/><span class="track"></span><span class="knob"></span></label>
            <${ThemedSwatch} val=${provColors[p.id]} title=${p.label + " tag colour"} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
              sample=${(c) => html`<span class="catpick-src" style=${"--pc:" + c}>${p.label}</span>`}/>
            <div class="prov-meta">
              <span class="prov-name">${p.label}</span>
              <span class="prov-tiers">${capBadges({ host: (p.tiers || []).includes("host"), ip: (p.tiers || []).includes("ip") })}</span>
              ${p.last_updated ? html`<span class="prov-upd" title="When this provider's lists last changed on the panel">updated ${ago(p.last_updated)}</span>` : null}
            </div>
            <span class="grow"></span>
            ${(() => { const s = p.status;
              if (s === "updating") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;
              if (s === "updated") return html`<span class="prov-st ok"><${Ic} i="check"/> updated</span>`;
              if (s === "uptodate") return html`<span class="prov-st ok"><${Ic} i="check"/> up to date</span>`;
              if (s === "failed" || p.error) return html`<span class="prov-st err" title=${p.error || ""}><${Ic} i="warn"/> failed to update</span>`;
              return null; })()}
            <a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${"Open " + p.label + " on GitHub"}>${(p.url || "").replace(/^https?:\/\/github\.com\//, "")}</a>
          </div>`; })}${!_provReg.length ? html`<div class="hint">Loading providers…</div>` : null}</div>

          <div class="seclabel">Update schedule</div>
          <p class="hint" style="margin:0 0 10px">When each node re-fetches its lists. Refreshing briefly reloads the node's match sets, which clients can feel — so schedule it for a <b>quiet hour</b>. (A failed fetch retries on the next sync; existing lists keep working meanwhile.)</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>How often</label>
              <select class="selwrap" value=${guEvery} onChange=${e => setGuEvery(e.target.value)}>
                <option value="1">Every day</option>
                <option value="2">Every 2 days</option>
                <option value="3">Every 3 days</option>
                <option value="7">Every week</option>
                <option value="0">Continuous (rolling ${ttlD}-day TTL)</option>
              </select></div>
            <div class="field" style="margin:0"><label>At (node-local time)</label>
              <input type="time" class="timein" value=${guAt} disabled=${guEvery === "0"} onInput=${e => setGuAt(e.target.value || "04:00")}/>
              <div class="hint">${guEvery === "0" ? "Continuous mode ignores the time — nodes refresh whenever a list is older than the TTL." : "Nodes update at this local time, on the chosen cadence."}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">Re-fetch every routed list from its provider now (updates the panel; nodes pull the changes on their schedule)</span><button class="btn btn-mini" disabled=${geoUpdating} onClick=${updateAllLists}><span class=${geoUpdating ? "tf-arrow" : ""}><${Ic} i="refresh"/></span> ${geoUpdating ? "Updating…" : "Update all lists now"}</button></div>
        </div>` : null}
        ${section === "defaults" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">Interface colours<span class="grow"></span>
            ${Object.keys(ifaceColorOverrides()).length ? html`<button class="btn btn-mini" onClick=${() => setIfaceColors({ wg: { ...IFACE_COLOR_DEFAULTS.wg }, awg: { ...IFACE_COLOR_DEFAULTS.awg } })}><${Ic} i="refresh"/> Reset</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">The colour each protocol's tags take everywhere — a value per theme. Hover a swatch to preview it.</p>
          <div class="palrow">
            <span class="palcell"><span class="pallbl">WireGuard</span><${ThemedSwatch} val=${ifaceColors.wg} title="WireGuard" onChange=${nv => setIfaceColors(c => ({ ...c, wg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>wg</span>`}/></span>
            <span class="palcell"><span class="pallbl">AmneziaWG</span><${ThemedSwatch} val=${ifaceColors.awg} title="AmneziaWG" onChange=${nv => setIfaceColors(c => ({ ...c, awg: nv }))}
              sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 15%,transparent);color:" + c}>awg</span>`}/></span>
          </div>
          <div class="seclabel">Peer health detection</div>
          <p class="hint" style="margin:0 0 10px">Which failure conditions the panel flags on a peer. All on by default — untick one to stop it showing that status (the peer just reads online / ready instead). Both appear in <span class="b-faulty" style="padding:1px 6px;border-radius:6px">orange</span>.</p>
          <label class="condrow"><input type="checkbox" checked=${statusConds.blocked} onChange=${e => setStatusConds(c => ({ ...c, blocked: e.target.checked }))}/>
            <span class="cond-b"><span class="badge b-blocked ic"><${Ic} i="warn"/>blocked</span></span>
            <span class="cond-t">Endpoint is reaching the server, but the handshake never completes (likely DPI / MTU / wrong AmneziaWG params).</span></label>
          <label class="condrow"><input type="checkbox" checked=${statusConds.faulty} onChange=${e => setStatusConds(c => ({ ...c, faulty: e.target.checked }))}/>
            <span class="cond-b"><span class="badge b-faulty ic"><${Ic} i="warn"/>faulty</span></span>
            <span class="cond-t">Handshake is up but no inbound data has flowed for a while — a one-way block / DPI on the return path. (This can't tell a genuinely-stuck peer from a simply-idle one, so turn it off if idle peers bother you.)</span></label>
          <div class="seclabel">Defaults</div>
          <p class="hint" style="margin:0 0 12px">Applied when creating a new interface — you can still override per interface.</p>
          <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="https://8.8.8.8/dns-query, 1.1.1.1"/><div class="hint">Comma-separated</div></div>
          <div class="row2"><div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/></div>
            <div class="field"><label>Persistent keepalive (s)</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/></div></div>
        </div>` : null}
        ${section === "security" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">Authentication</div>
          <p class="hint" style="margin:0 0 14px">Change the panel username and password — applied on <b>Save</b>. Changing either takes effect immediately and you'll be asked to sign in again.</p>
          ${!secAuth ? html`<div class="formmsg err">This panel has no login configured — changes are disabled.</div>` : (secErr() ? html`<div class="formmsg err">${secErr()}</div>` : null)}
          <div class="field"><label>Username</label><input value=${secUser} disabled=${!secAuth} onInput=${e => setSecUser(e.target.value)} autocomplete="username"/></div>
          <div class="field"><label>Current password</label><input type="password" value=${secCur} disabled=${!secAuth} onInput=${e => setSecCur(e.target.value)} autocomplete="current-password" placeholder="required to confirm a change"/></div>
          <div class="row2"><div class="field"><label>New password</label><input type="password" value=${secNp} disabled=${!secAuth} onInput=${e => setSecNp(e.target.value)} autocomplete="new-password" placeholder="leave blank to keep current"/></div>
            <div class="field"><label>Confirm new password</label><input type="password" value=${secNp2} disabled=${!secAuth} onInput=${e => setSecNp2(e.target.value)} autocomplete="new-password"/></div></div>
        </div>` : null}
        ${section === "configs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">Client configs</div>
          <div class="field"><label>Store client configs</label>
            <select class="selwrap" value=${sc} onChange=${e => setSc(e.target.value)}>
              <option value="on">On — keep configs (QRs re-viewable anytime)</option>
              <option value="off">Off — never store private keys</option>
            </select>
            <div class=${"hint" + (sc === "off" ? " err" : "")}>${sc === "off" ? "Live tunnels and creation-time QRs are unaffected, but you won't be able to re-view a peer's QR/config later — you'd rotate its key and re-distribute." : "On keeps client configs (incl. private keys) on the panel so QRs stay re-viewable."}</div></div>
        </div>` : null}
        ${section === "display" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">Interface theme<span class="grow"></span>
            ${(themeColorS.toLowerCase() !== THEME_COLOR_DEFAULT.toLowerCase() || themeColorLightS.toLowerCase() !== THEME_COLOR_LIGHT_DEFAULT.toLowerCase()) ? html`<button class="btn btn-mini" onClick=${() => { setThemeColorS(THEME_COLOR_DEFAULT); setThemeColorLightS(THEME_COLOR_LIGHT_DEFAULT); }}><${Ic} i="refresh"/> Reset</button>` : null}</div>
          <p class="hint" style="margin:0 0 12px">The panel's accent colour — button borders, checkboxes, focus rings, the throughput "down" series and the live / hour / day / week / month chart tabs all follow it. A separate colour for each mode; switch <b>Light / Dark / Auto</b> from the sun / moon button in the header.</p>
          <div class="palrow">
            <${ThemedSwatch} val=${themeVal} title="Interface theme" onChange=${nv => { setThemeColorS(clampBrand(nv.dark, false)); setThemeColorLightS(clampBrand(nv.light, true)); }}
              sample=${(c) => html`<span class="tsw-theme"><span class="tsw-btn" style=${"color:" + c}>Button</span><span class="tsw-chip" style=${"color:" + c}></span></span>`}/>
          </div>
          <div class="seclabel">Display</div>
          <div class="field"><label>Throughput perspective</label>
            <select class="selwrap" value=${tput} onChange=${e => setTput(e.target.value)}>
              <option value="nodes">Nodes — what the node downloads / uploads</option>
              <option value="peers">Peers — what the client downloads / uploads</option>
            </select>
            <div class="hint">Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.</div></div>
          <div class="seclabel">Status timing</div>
          <p class="hint" style="margin:0 0 12px">How long the panel waits before treating things as stale — in seconds.</p>
          <div class="row2"><div class="field"><label>Node stale after (s)</label><input value=${staleS} onInput=${e => setStaleS(e.target.value)} placeholder="30"/><div class="hint">No sync for this long → the node shows stale.</div></div>
            <div class="field"><label>Peer grace window (s)</label><input value=${graceS} onInput=${e => setGraceS(e.target.value)} placeholder="60"/><div class="hint">A peer stays "online" this long after its last handshake.</div></div></div>
        </div>` : null}
        ${section === "mesh" ? html`<div class="card">
          ${nodeRec ? html`<div class="seclabel" style="margin-top:0">${nodeRec.name} — mesh</div>
          <${NodeMeshForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>`
            : html`<p class="hint" style="margin:0">No nodes yet — enroll a node to configure its mesh.</p>`}
        </div>` : null}
        ${section === "nodesegress" ? html`<div class="card">
          ${nodeRec ? html`<div class="seclabel" style="margin-top:0">${nodeRec.name} — egress</div>
          <${NodeEgressForm} node=${nodeRec} vals=${nodeEdits[selNode]} set=${p => setNV(selNode, p)}/>`
            : html`<p class="hint" style="margin:0">No nodes yet — enroll a node to configure its egress.</p>`}
        </div>` : null}
        <div class="setfoot">${Date.now() < saved ? html`<span class="savedflash"><${Ic} i="check"/> All settings saved</span>` : null}<span class="grow"></span>
          <button class="btn btn-ghost" onClick=${leaveSettings}>Back</button>
          <button class="btn btn-primary" disabled=${!!secErr() || !anyDirty} title=${secErr() || (!anyDirty ? "No changes to save" : "")} onClick=${confirmSave}>Save</button></div>
      </div>
    </div>
  </div>`;
}

function CustomListSheet({ list, onSave, onDelete, onClose }) {
  const [title, setTitle] = useState(list?.title || "");
  const [targets, setTargets] = useState(list ? (list.targets ?? [...(list.domains || []), ...(list.cidrs || [])].join(", ")) : "");
  const [confirmDel, setConfirmDel] = useState(false);
  const toks = splitTargets(targets), bad = invalidTargets(targets);   // same token validation as the interface smart-rule editor
  const err = !toks.length ? "add at least one IP or domain"
    : bad.length ? "not a valid IP, CIDR or domain: " + bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "") : null;
  const save = () => { if (err) return; onSave({ ...(list || { _rid: newRid() }), title: title.trim() || "Untitled list", targets }); onClose(); };
  const del = onDelete ? (confirmDel                                   // left-aligned delete, two-step confirm
    ? html`<span class="del-confirm"><span class="faint">Delete this list?</span><button class="btn-danger" onClick=${() => { onDelete(); onClose(); }}>Delete</button><button class="btn btn-mini" onClick=${() => setConfirmDel(false)}>Keep</button></span>`
    : html`<button class="btn btn-ghost danger del-btn" onClick=${() => setConfirmDel(true)}><${Ic} i="trash"/> Delete</button>`) : null;
  const foot = html`${del}<span class="grow"></span><button class="btn btn-ghost" onClick=${onClose}>Cancel</button><button class="btn btn-primary" disabled=${!!err} title=${err || ""} onClick=${save}>${list ? "Save" : "Add"}</button>`;
  return html`<${Sheet} title=${list ? "Edit list" : "New list"} width=${520} onClose=${onClose} foot=${foot}>
    <div class="field"><label>Title</label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder="e.g. Streaming"/></div>
    <div class="field"><label>IPs / domains</label>
      <textarea class="rrdoms" rows="1" spellcheck="false" placeholder="comma-separated — spotify.com, 1.2.3.0/24, sub.example.com" value=${targets} onInput=${e => { autoGrow(e.target); setTargets(e.target.value); }} ref=${el => autoGrow(el)}/>
      ${err ? html`<div class="rrlint" style="margin-top:5px">${err}</div>` : html`<div class="hint">Domains match their subdomains too; IPs / CIDRs are matched directly.</div>`}</div>
  <//>`;
}

// Per-node mesh overrides, edited in Panel settings → System mesh (keyed by node, so it re-inits on badge switch)
function NodeMeshForm({ node, vals, set }) {
  const rsv = (Store.panelSettings || {}).reserved || {};
  const dSub = rsv.mesh_subnet || "10.255.0.0/16", dPort = String(rsv.mesh_port_base || 9999), dPfx = rsv.iface_prefix || "swg_";
  const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">Overrides for <b>${node.name}</b> — blank inherits the default. Changing the subnet, prefix, or AWG re-provisions this node's links on Save (it briefly drops off the mesh while peers reconnect with the new config).</p>
    <div class="field"><label>Mesh Ingress IP <span class="faint" style="text-transform:none;letter-spacing:0">— the address peers dial to reach this node</span></label>
      <${NodeIpPick} ips=${node.ips || []} value=${v.endpoint_host || ""} onChange=${ip => set({ endpoint_host: ip })} auto="Auto (public IP)"/></div>
    <div class="row2"><div class="field"><label>Mesh subnet</label><input value=${v.mesh_subnet || ""} onInput=${e => set({ mesh_subnet: e.target.value })} placeholder=${dSub}/></div>
      <div class="field"><label>Mesh port</label><input value=${v.mesh_port || ""} onInput=${e => set({ mesh_port: e.target.value })} placeholder=${dPort}/></div></div>
    <div class="field"><label>Interface name prefix</label><input value=${v.mesh_prefix || ""} onInput=${e => set({ mesh_prefix: e.target.value })} placeholder=${dPfx}/></div>
    ${(() => {
      const isSet = AWG_KEYS.some(k => String((v.mesh_awg || {})[k] ?? "").trim() !== "");
      return html`<div style="margin-top:6px"><button type="button" class="advtoggle" onClick=${e => { const d = e.currentTarget.nextElementSibling; d.style.display = d.style.display === "none" ? "" : "none"; }}><span class="advcaret">▸</span> This node's mesh AWG params${isSet ? "" : html` <span class="faint" style="font-weight:400">(auto)</span>`}</button>
        <div style="display:none;margin-top:8px">
          <${AwgGrid} value=${v.mesh_awg || {}} onChange=${a => set({ mesh_awg: a })}/>
          <div class="hint" style="margin:8px 0 0">Obfuscation for the mesh links that terminate on <b>${node.name}</b> — any node connecting to it adopts these and reconnects on Save. Blank = auto (a fresh set per link).</div>
          <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: genAwg() })}><${Ic} i="refresh"/> Generate a set</button>${isSet ? html`<button type="button" class="btn btn-mini" onClick=${() => set({ mesh_awg: {} })}>Clear (auto)</button>` : null}</div>
        </div></div>`;
    })()}
  </div>`;
}

// Per-node egress IP roles, edited in Panel settings → Nodes egress (copied from node settings). Controlled by the parent.
function NodeEgressForm({ node, vals, set }) {
  const ips = node.ips || []; const v = vals || {};
  return html`<div>
    <p class="hint" style="margin:0 0 12px">Which of <b>${node.name}</b>'s IPs it uses for each outbound role.</p>
    <div class="field"><label>Default egress IP <span class="faint" style="text-transform:none;letter-spacing:0">— direct internet exit</span></label>
      <${NodeIpPick} ips=${ips} value=${v.default_egress_ip || ""} onChange=${ip => set({ default_egress_ip: ip })} auto="Auto (MASQUERADE)"/></div>
    <div class="field"><label>Panel egress connection IP <span class="faint" style="text-transform:none;letter-spacing:0">— source to reach the panel</span></label>
      <${NodeIpPick} ips=${ips} value=${v.panel_ip || ""} onChange=${ip => set({ panel_ip: ip })} auto="Auto (default route)"/></div>
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
function Sheet({ title, children, foot, onClose, width }) {
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
    const tok = {}; _sheetStack.push(tok);   // only the TOP stacked Sheet reacts to Esc/Enter/Tab
    const onKey = e => {
      if (qrZoomEl) return;   // a QR enlargement is open — let it handle Esc (collapse it, keep the modal)
      if (_sheetStack[_sheetStack.length - 1] !== tok) return;   // a child modal is on top — defer to it
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
      _sheetStack = _sheetStack.filter(t => t !== tok);
      root.removeEventListener("input", onEdit, true);
      root.removeEventListener("change", onEdit, true);
    };
  }, []);

  return html`<div class="overlay show" onClick=${e => { if (e.target.classList.contains("overlay")) tryClose(); }}>
    <div class="sheet" role="dialog" aria-modal="true" ref=${ref} style=${width ? "width:" + width + "px;max-width:calc(100vw - 32px)" : ""}>
      <div class="sheet-head"><h3>${title}</h3><button class="x" onClick=${tryClose}>×</button></div>
      <div class="sheet-body">${children}</div>
      ${(foot || discard) ? html`<div class="sheet-foot">${discard
        ? html`<${Fragment}><span class="discard-msg"><${Ic} i="warn"/> Discard unsaved changes?</span><span class="grow"></span>
            <button class="btn btn-ghost" onClick=${() => setDiscarding(false)}>Keep editing</button>
            <button class="btn btn-danger" onClick=${onClose}>Discard</button></>`
        : foot}</div>` : null}
    </div></div>`;
}

// Designed confirmation modal — the in-app replacement for native confirm(). `danger` paints the
// action button red; `danger`/`warn` give the notice a warn tint + icon (else a neutral info note).
// `back` (optional) = where Cancel / Esc returns to (e.g. reopen the peer view it was launched from);
// default just closes. After a confirmed action we always close, since the action changed the state.
// Error/log bodies (captured installer output, command errors) carry ANSI colour codes + newlines that read
// as one mashed line. `log:` renders them line-by-line, ANSI stripped for humans ("rendered"), with a toggle
// to the unprocessed log ("raw", ESC shown as ␛, still line-by-line). Used by every error/detail modal.
function logRendered(s) { return String(s == null ? "" : s).replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "").replace(/\r/g, "").replace(/[ \t]+$/gm, ""); }
function logRaw(s) { return String(s == null ? "" : s).replace(/\x1b/g, "␛").replace(/\r/g, ""); }
function LogBody({ text, raw }) {
  const t = (raw ? logRaw(text) : logRendered(text)).replace(/\n+$/, "");
  return html`<div class=${"logview" + (raw ? " raw" : "")}>${t.split("\n").map(l => html`<div class="logline">${l === "" ? " " : l}</div>`)}</div>`;
}
function openConfirm(opts) { openModal(html`<${ConfirmSheet} ...${opts}/>`); }
function ConfirmSheet({ title, body, log, confirmLabel, danger, warn, onConfirm, back }) {
  back = back || closeModal;
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState(false);
  const isLog = log != null && String(log) !== "";
  const canToggle = isLog && logRaw(log) !== logRendered(log);   // only offer raw/rendered when they differ (ANSI present)
  const go = async () => { if (busy) return; if (!onConfirm) return back(); setBusy(true); const seq = _modalSeq;
    try { await onConfirm(); } finally { if (_modalSeq === seq) closeModal(); } };   // skip close if onConfirm opened another modal (no flicker)
  const tone = danger || warn;
  return html`<${Sheet} title=${title} onClose=${back}
    foot=${html`<${Fragment}>
      ${canToggle ? html`<button class="btn btn-ghost logtoggle" onClick=${() => setRaw(r => !r)}>${raw ? "Display rendered" : "Display raw"}</button>` : null}
      <span class="grow"></span>
      <button class=${"btn " + (onConfirm ? "btn-ghost" : "btn-primary")} onClick=${back}>${onConfirm ? "Cancel" : (confirmLabel || "Close")}</button>
      ${onConfirm ? html`<button class=${"btn " + (danger ? "btn-danger" : "btn-primary")} disabled=${busy} onClick=${go}>${confirmLabel || "Confirm"}</button>` : null}</>`}>
    ${isLog
      ? html`<${LogBody} text=${log} raw=${raw}/>`
      : html`<div class=${"notice" + (tone ? " warn" : "")}><${Ic} i=${tone ? "warn" : "info"}/><span>${body}</span></div>`}
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
  const stayExpanded = uid => { usersView.expanded[uid] = true; usersView.q = ""; usersView.page = 1; closeModal(); go("#/users"); };
  const createOnly = async () => { const u = await createUser(); if (u) stayExpanded(u.id); };
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
// the user-detail "Add peers" button. Lists every interface — a user may run several devices (phone / router /
// laptop, even a 2nd phone) on the same interface, each its own peer + IP, so occupied interfaces aren't hidden.
function openAddPeers(userId, userName) { openModal(html`<${AddPeersSheet} userId=${userId} userName=${userName}/>`); }
function AddPeersSheet({ userId, userName }) {
  const [mode, setMode] = useState("new");   // "new" = mint peers per interface, else an existing unassigned peer id to assign
  const [chosen, setChosen] = useState([]);
  const cf = useConfigFields();
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const unassigned = Store.unassignedPeers();
  const selPeer = mode !== "new" ? unassigned.find(p => p.id === mode) : null;
  useEffect(() => { if (mode !== "new" && !unassigned.some(p => p.id === mode)) setMode("new"); }, [unassigned, mode]);   // chosen peer got assigned/removed elsewhere
  useEffect(() => {
    if (!selPeer && !cf.dnsTouched.current && chosen.length) { const m = Store.ifaceMeta(chosen[0].node, chosen[0].iface); if (m) cf.setDns((m.dns || []).join(", ")); }
  }, [chosen, selPeer]);
  const stayExpanded = () => { usersView.expanded[userId] = true; usersView.q = ""; usersView.page = 1; closeModal(); go("#/users"); };
  const peerLabel = p => {   // title · node · <tag> iface · internal IP  (representative = first target)
    const t = p.targets[0] || {};
    const ty = (t.type || "").toLowerCase() === "awg" ? "AWG" : "WG";
    return [p.title || "untitled", Store.nodeName(t.node), ty + " " + t.iface, t.ip].filter(Boolean).join(" · ");
  };
  const create = async () => {
    if (selPeer) {                                    // assign an existing unassigned peer (+ deploy any new interfaces, same key)
      const existing = new Set(selPeer.targets.map(t => tkey(t.node, t.iface)));
      const adds = chosen.filter(t => !existing.has(tkey(t.node, t.iface)) && !t.existing);
      const badIp = adds.find(t => !V.ipv4(String(t.ip).trim()));
      if (badIp) return setMsg({ k: "err", t: "Invalid address for " + Store.nodeName(badIp.node) + "/" + badIp.iface + "." });
      setBusy(true); setMsg({ k: "work", t: "assigning…" });
      const r = await api.peerUpdate({ peer_id: selPeer.id, user_id: userId });
      if (!r.ok) { setBusy(false); return setMsg({ k: "err", t: r.error || "couldn't assign peer" }); }
      const fails = [];
      for (const t of adds) {
        const rr = await api.peerAddTarget({ peer_id: selPeer.id, target: { node: t.node, iface: t.iface, ip: String(t.ip).trim().split("/")[0] } });
        if (!rr.ok) fails.push(Store.nodeName(t.node) + "/" + t.iface + ": " + (rr.error || rr.code || "failed"));
      }
      setBusy(false); await Store.poll();
      if (fails.length) toast("Some deployments failed: " + fails.join("; "), "err", 6000);
      closeModal(); return revealAssignedPeer(userId, selPeer.id);
    }
    if (!chosen.length) return setMsg({ k: "err", t: "Pick at least one interface." });
    const badIp = chosen.find(t => !V.ipv4(String(t.ip).trim()));
    if (badIp) return setMsg({ k: "err", t: "Invalid address for " + Store.nodeName(badIp.node) + "/" + badIp.iface + "." });
    const ce = configErrors(cf); const ck = Object.keys(ce)[0];
    if (ck) return setMsg({ k: "err", t: ce[ck] });
    setBusy(true); setMsg({ k: "work", t: "minting " + chosen.length + " peer" + (chosen.length > 1 ? "s" : "") + "…" });
    const res = await createPeersForTargets(userId, chosen, cf.opts());
    setBusy(false); await Store.poll();
    if (res.fails.length) toast("Some peers failed: " + res.fails.join("; "), "err", 6000);
    stayExpanded();
  };
  // when an existing peer is picked, its current targets get an add-target on newly-checked ifaces
  const newAdds = selPeer ? chosen.filter(t => !t.existing && !selPeer.targets.some(x => x.node === t.node && x.iface === t.iface)).length : chosen.length;
  const ctaLabel = selPeer ? ("Assign" + (newAdds ? " + " + newAdds + " target" + (newAdds === 1 ? "" : "s") : "")) : ("Create " + (chosen.length || "") + " peer" + (chosen.length === 1 ? "" : "s"));
  return html`<${Sheet} title=${"Add peers" + (userName ? " · " + userName : "")}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${create}>${ctaLabel}</button></>`}>
    <div class="field"><label>Peer</label>
      <select class="selwrap" value=${mode} onChange=${e => { setMode(e.target.value); setChosen([]); }}>
        <option value="new">Create new peer</option>
        ${unassigned.map(p => html`<option value=${p.id}>${peerLabel(p)}</option>`)}
      </select></div>
    ${selPeer
      ? html`<div class="hint" style="margin-bottom:10px">Assign this unassigned peer to ${userName || "the user"} (its key is kept). Tick more interfaces to also deploy it there with the same key.</div>`
      : html`<div class="hint" style="margin-bottom:10px">Each interface becomes its own peer (own key) — one QR per peer. Add redundancy later with “copy to another interface”.</div>`}
    <div class="field"><label>Interfaces</label><${TargetPicker} key=${mode} initial=${selPeer ? selPeer.targets : null} onChange=${setChosen}/></div>
    ${selPeer ? null : html`<${AdvancedFields} st=${cf}/>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// All deployable (node, iface) targets known from the consolidated state.
function allTargets() {
  const out = [];
  for (const node of Object.keys(Store.describe)) for (const iface of Object.keys(Store.describe[node] || {}))
    if (!Store.ifaceIsSystem(node, iface)) out.push({ node, iface });   // never offer a mesh link (swg_*) as a peer target
  return out;
}

// Reusable (node,iface) picker with per-target IP allocation. `exclude` is a Set of tkeys
// to hide (interfaces a user is already on); `onChange` receives the chosen target list
// [{node,iface,ip,ipHint}]. Used by the create-peer, create-user and add-peers flows.
function TargetPicker({ prefill, exclude, onChange, initial }) {
  const all = useMemo(allTargets, [Store.describe]);
  // locked: launched from one interface — show only that target, no toggling, just the IP.
  const locked = !!(prefill && prefill.lock && prefill.node && prefill.iface);
  const targets = locked ? all.filter(t => t.node === prefill.node && t.iface === prefill.iface)
    : (exclude ? all.filter(t => !exclude.has(tkey(t.node, t.iface))) : all);
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
  const seeded = useRef(false);
  useEffect(() => {                                  // seed already-deployed targets (their assigned IP, read-only)
    if (seeded.current || !initial || !initial.length || !all.length) return;
    seeded.current = true;
    const seed = {};
    initial.forEach(t => { seed[tkey(t.node, t.iface)] = { node: t.node, iface: t.iface, ip: String(t.ip || "").split("/")[0], existing: true }; });
    setSel(seed);
  }, [all, initial]);
  useEffect(() => {                                  // preselect from prefill once targets are known
    if (!targets.length || Object.keys(sel).length || (initial && initial.length)) return;
    if (prefill && prefill.node && prefill.iface) allocIp(prefill.node, prefill.iface);
    else if (prefill && prefill.node) targets.filter(t => t.node === prefill.node).slice(0, 1).forEach(t => allocIp(t.node, t.iface));
  }, [all]);
  useEffect(() => { onChange(Object.values(sel)); }, [sel]);

  if (!targets.length) return html`<div class="hint">No interfaces available — is a node online?</div>`;
  // order by the INITIAL checked state (already-deployed targets), then node, then interface — so the
  // pre-checked rows sit on top and the list does NOT reshuffle as you toggle.
  const initialKeys = new Set((initial || []).map(t => tkey(t.node, t.iface)));
  const ordered = [...targets].sort((a, b) =>
    (initialKeys.has(tkey(a.node, a.iface)) ? 0 : 1) - (initialKeys.has(tkey(b.node, b.iface)) ? 0 : 1)
    || (Store.nodeName(a.node) || "").localeCompare(Store.nodeName(b.node) || "")
    || (a.iface || "").localeCompare(b.iface || ""));
  return html`<div class="targetpick">${ordered.map(t => {
    const k = tkey(t.node, t.iface); const s = sel[k];
    const im = (Store.describe[t.node] || {})[t.iface] || {};
    const ity = (im.awg_params && Object.keys(im.awg_params).length) ? "awg" : "wg";
    return html`<div class=${"targetopt " + (s ? "sel " : "") + (locked ? "locked" : "")}>
      <label class="topt-main" onClick=${locked ? null : () => toggle(t.node, t.iface)}>
        <span class="box">${s ? html`<${Ic} i="check"/>` : ""}</span>
        <span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>
        <span class="tp">${t.iface}</span></label>
      <${Tag} kind=${ity} label=${ity}/>
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

  const validate = () => {
    if (!chosen.length) return "Pick at least one target.";
    const badIp = chosen.find(t => !V.ipv4(String(t.ip).trim()));
    if (badIp) return "Invalid address for " + Store.nodeName(badIp.node) + "/" + badIp.iface + ".";
    const ce = configErrors(cf); const k = Object.keys(ce)[0];
    if (k) return ce[k];
    return null;
  };

  const create = async () => {
    const err = validate(); if (err) return setMsg({ k: "err", t: err });
    setBusy(true); setMsg({ k: "work", t: "generating key…" });
    let keys, pskV, tgts, configs, body;
    try {                                            // browser-side crypto/config build is the only awaited part
      keys = await genKeys();
      pskV = genPSK();   // PSK is panel-owned & auto-minted; change it via a peer's Rotate keys
      const dnsArr = cf.dns.split(",").map(s => s.trim()).filter(Boolean);
      tgts = []; configs = {};
      for (const t of chosen) {
        const m = Store.ifaceMeta(t.node, t.iface); if (!m) continue;
        const ipClean = String(t.ip).trim().split("/")[0];
        tgts.push({ node: t.node, iface: t.iface, ip: ipClean, type: (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg" });
        configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: dnsArr, mtu: cf.mtu.trim() || 1280, awg_params: m.awg_params, server_pubkey: m.public_key, psk: pskV, endpoint: m.endpoint, allowed: cf.allowed.trim() || "0.0.0.0/0, ::/0", keepalive: cf.keepalive.trim() });
      }
      body = { user_id: userId || null, title: title.trim(), pubkey: keys.pub, psk: pskV, targets: tgts };
      if (Store.storeConfigs) body.configs = configs;
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: "Error: " + e.message }); }
    // Optimistic: stash the config, drop a "creating" peer onto the grid, close the modal NOW, and let
    // the create POST run in the background (mutate reverts + toasts on failure; the next poll supersedes).
    Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, configs);
    const tempId = "tmp_" + keys.pub.slice(0, 14);
    const optimistic = { id: tempId, pubkey: keys.pub, user_id: userId || null, title: title.trim(), psk: pskV,
      targets: tgts.map(t => ({ node: t.node, iface: t.iface, ip: t.ip, type: t.type })),
      created_at: Math.floor(Date.now() / 1000), _creating: true };
    closeModal();
    if (prefill.lock && prefill.node && prefill.iface) go("#/node/" + encodeURIComponent(prefill.node) + "/" + encodeURIComponent(prefill.iface));
    else if (userId) go("#/user/" + encodeURIComponent(userId));
    mutate({
      patch: s => { s.roster.peers[tempId] = optimistic; },        // shows instantly with status "creating"
      call: () => api.peerCreate(body),
      onOk: r => { if (r && r.data && r.data.id) Store.recentlyCreated[r.data.id] = Date.now(); },
    });
  };

  return html`<${Sheet} title="New peer"
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${create}>Create peer</button></>`}>
    <div class="field"><label>User</label>
      <${UserPicker} value=${userId} allowUnassigned=${true} onChange=${setUserId}/></div>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional, to tell devices apart</span></label>
      <input value=${title} onInput=${e => setTitle(e.target.value)} maxlength="64" placeholder="iPhone, Router, Laptop…"/></div>
    <div class="field"><label>Targets <span class="faint" style="text-transform:none;letter-spacing:0">— one, or several for redundancy (same key)</span></label>
      <${TargetPicker} prefill=${prefill} onChange=${setChosen}/></div>
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
  const [chosen, setChosen] = useState([]);
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  // source config (holds the client's private key) so NEW targets can rebuild a QR: session first,
  // then the panel's stored copy when store_configs is on. Any target's config carries the same key.
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

  const initial = useMemo(() => peer.targets.map(t => ({ node: t.node, iface: t.iface, ip: t.ip })), [peer.id]);
  const haveKeys = new Set(peer.targets.map(t => tkey(t.node, t.iface)));
  const origIp = {}; peer.targets.forEach(t => origIp[tkey(t.node, t.iface)] = String(t.ip || "").split("/")[0]);
  const chosenKeys = new Set(chosen.map(c => tkey(c.node, c.iface)));
  const added = chosen.filter(c => !haveKeys.has(tkey(c.node, c.iface)));         // newly checked
  const removed = peer.targets.filter(t => !chosenKeys.has(tkey(t.node, t.iface))); // unchecked existing
  const ipChanged = chosen.filter(c => haveKeys.has(tkey(c.node, c.iface)) && c.ip && String(c.ip).split("/")[0] !== origIp[tkey(c.node, c.iface)]);  // existing whose address was edited
  const badIp = added.concat(ipChanged).some(c => !c.ip || !V.ipv4(String(c.ip).split("/")[0]));
  const nochange = !added.length && !removed.length && !ipChanged.length;

  const doSave = async () => {
    setBusy(true); setMsg({ k: "work", t: "applying…" });
    const fails = [];
    for (const t of added) {
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      let conf = null;
      if (srcConf) { const s = parseFullConf(srcConf); conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); }
      const body = { peer_id: peer.id, target: { node: t.node, iface: t.iface, ip: ipClean, type: info.awg_params && Object.keys(info.awg_params).length ? "awg" : "wg" } };
      if (Store.storeConfigs && conf) body.config = conf;
      const r = await api.peerAddTarget(body);
      if (r.ok) { if (conf) (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
      else fails.push(Store.nodeName(t.node) + "/" + t.iface + " (add)");
    }
    for (const t of ipChanged) {
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      const body = { peer_id: peer.id, node: t.node, iface: t.iface, ip: ipClean };
      if (srcConf && Store.storeConfigs) { const s = parseFullConf(srcConf); const conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); body.config = conf; (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
      const r = await api.peerUpdateTarget(body);
      if (!r.ok) fails.push(Store.nodeName(t.node) + "/" + t.iface + " (address)");
    }
    for (const t of removed) {
      const r = await api.peerRemoveTarget({ peer_id: peer.id, node: t.node, iface: t.iface });
      if (!r.ok) fails.push(Store.nodeName(t.node) + "/" + t.iface + " (remove)");
    }
    setBusy(false);
    if (fails.length) { setMsg({ k: "err", t: "Some changes failed: " + fails.join(", ") }); return false; }
    toast("Peer targets updated.", "ok"); await Store.poll(); return true;
  };
  const save = () => {
    if (nochange) { back(); return; }
    if (badIp) return setMsg({ k: "err", t: "A target has an invalid address." });
    if (chosen.length === 0) {                       // a peer must live on at least one interface — none left = delete it
      pushModal(html`<${ConfirmSheet} title="Delete this peer?" confirmLabel="Yes, delete" danger=${true}
        body=${"You've unchecked every interface, so there's nothing left to deploy this peer to — saving will completely delete it. Its access is revoked everywhere and its config / QR stops working. This action is irreversible. Are you sure you want to continue?"}
        onConfirm=${async () => {
          if (peer.user_id != null) { const u = await api.peerUnassign({ peer_id: peer.id }); if (!u.ok) return setMsg({ k: "err", t: "Delete failed: " + (u.error || u.code || "") }); }
          const r = await api.peerDelete({ peer_id: peer.id });
          if (!r.ok) return setMsg({ k: "err", t: "Delete failed: " + (r.error || r.code || "") });
          closeModal(); back(); toast("Peer deleted.", "ok"); await Store.poll();
        }}/>`);
      return;
    }
    if (removed.length || ipChanged.length) {
      const parts = [];
      if (removed.length) parts.push("Remove the peer from " + removed.map(t => Store.nodeName(t.node) + "/" + t.iface).join(", ") + " — " + (removed.length > 1 ? "those tunnels drop" : "that tunnel drops") + " immediately and the client can no longer connect through " + (removed.length > 1 ? "them" : "it") + ".");
      if (ipChanged.length) parts.push("Change the peer's address on " + ipChanged.map(c => Store.nodeName(c.node) + "/" + c.iface).join(", ") + " — the config / QR already handed out for " + (ipChanged.length > 1 ? "those interfaces stops" : "that interface stops") + " connecting, so you'll need to re-issue and re-distribute " + (ipChanged.length > 1 ? "them" : "it") + ".");
      const title = removed.length && ipChanged.length ? "Apply these changes?"
        : removed.length ? ("Remove from " + removed.length + " interface" + (removed.length > 1 ? "s" : "") + "?")
        : ("Change " + ipChanged.length + " address" + (ipChanged.length > 1 ? "es" : "") + "?");
      pushModal(html`<${ConfirmSheet} title=${title} confirmLabel="Save changes" danger=${true} body=${parts.join(" ") + " This can't be undone."}
        onConfirm=${async () => { if (await doSave()) { closeModal(); back(); } }}/>`);
    } else doSave().then(ok => { if (ok) back(); });
  };

  return html`<${Sheet} title=${"Peer targets"} onClose=${back}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${back}>Cancel</button><button class=${"btn " + (chosen.length === 0 ? "btn-danger" : "btn-primary")} disabled=${busy || !confLoaded || nochange} onClick=${save}>${chosen.length === 0 ? "Delete peer" : ((removed.length || ipChanged.length) ? "Save changes" : "Deploy")}</button></>`}>
    ${!confLoaded ? html`<div class="loading"><span class="spin"></span>loading config…</div>`
      : html`<${Fragment}>
        ${added.length && !srcConf ? html`<div class="notice warn"><${Ic} i="warn"/><span>${Store.storeConfigs
            ? "This peer's private key isn't available here, so newly-added targets get the same key + PSK but a fresh QR / config can't be generated. Re-issue (rotate keys) for a downloadable config."
            : "store_configs is off, so the client's private key isn't kept — new targets get the same key + PSK, but a fresh QR can't be shown."}</span></div>` : null}
        <div class="field"><label>Targets <span class="faint" style="text-transform:none;letter-spacing:0">— check to deploy, uncheck to remove</span></label>
          <${TargetPicker} initial=${initial} onChange=${setChosen}/></div>
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
  return html`<${Sheet} title=${p.title || (u ? u.name : "Unassigned peer")} width=${640}
    foot=${html`<${Fragment}>
      <button class="btn btn-ghost" onClick=${closeModal}>Close</button><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${() => openPeerConfigs(p, () => openPeerView(p.id, node, iface))}><${Ic} i="qr"/> QR</button>
      <button class="btn btn-ghost" onClick=${() => openAddTarget(p, () => openPeerView(p.id, node, iface))}><${Ic} i="copy"/> Targets</button>
      <button class="btn btn-ghost" onClick=${() => openEditPeer(p, node && iface ? { node, iface } : null, () => openPeerView(p.id, node, iface))}><${Ic} i="pencil"/> Edit</button>
      ${p.unassigned ? html`<button class="btn btn-danger" onClick=${() => confirmDeletePeer(p, () => openPeerView(p.id, node, iface))}>Delete</button>`
        : html`<button class="btn btn-danger" onClick=${() => confirmUnassign(p, () => openPeerView(p.id, node, iface))}>Unassign</button>`}<//>`}>
    <div class="pv-head">
      <div class="pv-id"><div class="pv-sub">${u ? html`<a class="pv-user" href=${"#/user/" + encodeURIComponent(u.id)}>${u.name}</a>`
          : html`<${UserCombo} onPick=${uid => assignPeer(p, uid)} placeholder="Assign to a user…"/>`}</div></div>
      <${Badge} s=${p.unassigned ? "unassigned" : p.status}/></div>
    <div class="lbl" style="margin:16px 2px 4px">Deployments · ${p.targets.length}</div>
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
          <span><span class="k">Node</span> <span style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></span>
          <span><span class="k">Interface</span> ${t.iface}</span>
          <span><span class="k">Address</span> <span class="addr">${t.ip || "—"}</span></span>
          <span><span class="k">Rate</span> ${rateCell(obs ? obs.rx_speed : 0, obs ? obs.tx_speed : 0)}</span>
          <span><span class="k">Total</span> ${xferCell(...dlul(obs ? obs.rx_bytes : 0, obs ? obs.tx_bytes : 0))}</span>
          <span><span class="k">Online</span> ${seen(obs ? obs.handshake_age : null)}</span>
        </div></div>`;
    })}</div>
  <//>`;
}

// Edit a peer: title (peer-wide), the focused target's address, and the client-config settings
// (DNS/MTU/keepalive/AllowedIPs, applied to every target with a known config). Also offers copy
// → another interface and key rotation (keeps the PSK). `focus` = the {node,iface} to edit IP for.
// `done` = where Cancel / Save returns to (reopen the peer view when edit came from it, else close).
function openEditPeer(peer, focus, done, flash) { openModal(html`<${EditPeerSheet} peer=${peer} focus=${focus} done=${done || closeModal} flash=${flash}/>`); }
function EditPeerSheet({ peer, focus, done, flash }) {
  done = done || closeModal;
  const [title, setTitle] = useState(peer.title || "");
  const [ips, setIps] = useState(() => Object.fromEntries(peer.targets.map(t => [tkey(t.node, t.iface), (t.ip || "").split("/")[0]])));
  const setIpFor = (k, v) => setIps(m => ({ ...m, [k]: v }));
  const [loaded, setLoaded] = useState(false);
  const [confs, setConfs] = useState({});            // "node|iface" -> conf text (those we can rebuild)
  const [dns, setDns] = useState(""); const [mtu, setMtu] = useState("1280");
  const [keepalive, setKeepalive] = useState("25"); const [allowed, setAllowed] = useState("0.0.0.0/0, ::/0");
  const [userId, setUserId] = useState(peer.user_id || "");   // staged owner (applied on Save for an unassigned peer)
  const [msg, setMsg] = useState(flash || null); const [busy, setBusy] = useState(false);
  // reopening THIS sheet with a new flash (e.g. rotate: orange "Rotating…" → green "Keys rotated")
  // reuses the instance, so the useState initial above is ignored — sync the prop into state.
  useEffect(() => { if (flash) setMsg(flash); }, [flash]);

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
  }, [peer.id, peer.pubkey, Store.configEpoch]);   // pubkey/epoch change (e.g. after Rotate) re-reads the now-available config

  const editable = Object.keys(confs).length;
  const ipChangedFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && v !== (t.ip || "").split("/")[0]; };
  const ipBadFor = t => { const v = (ips[tkey(t.node, t.iface)] || "").trim(); return !!v && !V.ipv4(v.split("/")[0]); };
  const anyIpBad = peer.targets.some(ipBadFor);
  const errs = editable ? configErrors({ dns, mtu, keepalive, allowed }) : {};
  const save = async () => {
    if (anyIpBad) return setMsg({ k: "err", t: "Each address must be a valid IPv4." });
    const ek = Object.keys(errs)[0]; if (ek) return setMsg({ k: "err", t: errs[ek] });
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    const dnsArr = dns.split(",").map(s => s.trim()).filter(Boolean);
    let fails = 0;
    try {
      if (title.trim() !== (peer.title || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, title: title.trim() }); if (!r.ok) fails++;
      }
      // staged assignment of a previously-unassigned peer — keep the key, just set the owner
      if (peer.unassigned && userId && userId !== (peer.user_id || "")) {
        const r = await api.peerUpdate({ peer_id: peer.id, user_id: userId }); if (!r.ok) fails++;
      }
      // rebuild + persist each target's config; any target whose address changed moves on its iface
      for (const t of peer.targets) {
        const k = tkey(t.node, t.iface); const cur = confs[k];
        const changed = ipChangedFor(t);
        const newIP = (ips[k] || "").trim().split("/")[0];
        if (!cur) {                                  // no config to rebuild — IP can still move
          if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
          continue;
        }
        const s = parseFullConf(cur);
        const addr = (changed ? newIP : (s.address || "").split("/")[0]) + "/32";
        const conf = buildConf({ privkey: s.privkey, address: addr, dns: editable ? dnsArr : s.dns, mtu: (mtu.trim() || 1280), awg_params: s.awg_params, server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: (allowed.trim() || "0.0.0.0/0, ::/0"), keepalive: keepalive.trim() });
        (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[k] = conf;
        if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP, config: conf }); if (!r.ok) fails++; }
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
    openConfirm({ title: "Rotate keys", confirmLabel: "Rotate keys", warn: true,
      back: () => openEditPeer(peer, focus, done),   // cancel/esc returns to the edit modal
      body: "A fresh keypair and preshared key are generated. The current config stops working — you'll need to send out the fresh QR / config to re-import. Useful if a config may have leaked.",
      onConfirm: () => {
        // the user did the action they came for → return to the previous screen; report the result via a toast.
        done();
        rotatePeerKeys(peer).then(async () => {
          await Store.poll();
          const re = Store.rowErrors["peer:" + peer.id];
          toast(re ? (re.msg || "Rotate failed.") : "Keys rotated — send the user the new QR / config; the old one no longer works.", re ? "err" : "ok");
        });
      } });
  };

  return html`<${Sheet} title=${"Edit peer"} onClose=${done}
    foot=${html`<${Fragment}>${editable ? html`<button class="btn btn-ghost" onClick=${() => openPeerConfigs(peer, () => openEditPeer(peer, focus, done))}><${Ic} i="qr"/> QR</button>` : null}<button class="btn btn-ghost" onClick=${() => openAddTarget(peer, done)}><${Ic} i="copy"/> Targets</button><button class="btn btn-ghost" onClick=${rotate}><${Ic} i="key"/> Rotate keys</button><span class="grow"></span><button class="btn btn-ghost" onClick=${done}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>Save</button></>`}>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input autofocus value=${title} maxlength="64" onInput=${e => setTitle(e.target.value)} placeholder="e.g. iPhone, Work laptop"/></div>
    <div class="field"><label>User</label>
      <${UserPicker} value=${userId} allowUnassigned=${!peer.unassigned} onChange=${setUserId}/>
      <div class=${"hint"}>${
        peer.unassigned ? "Pick a user to assign this peer to — the existing key and config are kept, applied when you Save."
        : (userId || "") === (peer.user_id || "") ? "Reassigning rotates the keys; you'll confirm on Save and the new user needs a fresh config."
        : !userId ? "On Save you'll confirm unassigning — access is revoked and the keys rotate."
        : "On Save you'll confirm reassigning — the current user loses access for good and the new user needs a fresh config."
      }</div></div>
    <div class="field"><label>Addresses</label>
      <div class="targetpick">${peer.targets.map(t => {
        const k = tkey(t.node, t.iface);
        const im = (Store.describe[t.node] || {})[t.iface] || {};
        const ity = (im.awg_params && Object.keys(im.awg_params).length) ? "awg" : "wg";
        return html`<div class="targetopt sel locked" key=${k}>
          <div class="topt-main"><span class="box"><${Ic} i="check"/></span><span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span><span class="tp">${t.iface}</span></div>
          <${Tag} kind=${ity} label=${ity}/>
          <input class=${"topt-ip " + (ipBadFor(t) ? "bad" : "")} value=${ips[k] || ""} onInput=${e => setIpFor(k, e.target.value)}/>
        </div>`;
      })}</div>
      <div class="hint">Changing an address moves the peer on that interface.</div>
    </div>
    ${!loaded ? html`<div class="loading"><span class="spin"></span>loading config…</div>`
      : !editable ? html`<div class="notice warn"><${Ic} i="warn"/><span>The client's private key isn't available, so DNS / MTU / routing can't be rebuilt${Store.storeConfigs ? "" : " (enable store_configs, or edit right after creating)"}. Title and address can still change.</span></div>`
      : html`<${Fragment}>
        <div class="field"><label>Client allowed IPs (routing)</label><input class=${errs.allowed ? "bad" : ""} value=${allowed} onInput=${e => setAllowed(e.target.value)}/><div class=${"hint" + (errs.allowed ? " err" : "")}>${errs.allowed || "Full tunnel by default. Narrow for split tunnel."}</div></div>
        <div class="field"><label>DNS</label><input class=${errs.dns ? "bad" : ""} value=${dns} onInput=${e => setDns(e.target.value)} placeholder="e.g. 1.1.1.1, 1.0.0.1"/><div class=${"hint" + (errs.dns ? " err" : "")}>${errs.dns || "Comma-separated IPs. Blank = no DNS line."}</div></div>
        <div class="row2">
          <div class="field"><label>MTU</label><input class=${errs.mtu ? "bad" : ""} value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class=${"hint" + (errs.mtu ? " err" : "")}>${errs.mtu || "Blank = 1280."}</div></div>
          <div class="field"><label>Persistent keepalive (s)</label><input class=${errs.keepalive ? "bad" : ""} value=${keepalive} onInput=${e => setKeepalive(e.target.value)} placeholder="25"/><div class=${"hint" + (errs.keepalive ? " err" : "")}>${errs.keepalive || "0 disables · blank = 25."}</div></div>
        </div>
      <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ── node sheets ──
function openNodeCreate() { openModal(html`<${NodeCreateSheet}/>`); }
function NodeCreateSheet() {
  const [name, setName] = useState(""); const [color, setColor] = useState({ ...NODE_CREATE_DEFAULT }); const [msg, setMsg] = useState(null);
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
    <div class="field"><label>Name</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} placeholder="msk-edge1" autocomplete="off"/>
        <${ThemedSwatch} val=${color} title="Node colour" onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : "A label for this node — you can rename it anytime. The swatches set its colour per theme."}</div></div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
const BOOTSTRAP_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh";
function NodeTokenSheet({ name, token, isNew, kind }) {
  const host = `${location.origin}${BASE}`;
  const bare = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s node -key ${token} -host ${host}`;
  const docker = `curl -fsSL ${BOOTSTRAP_URL} | sudo bash -s docker node -key ${token} -host ${host}`;
  // recover/rotate of an existing node → show ONLY its method's command (a docker box re-installed as
  // bare, or vice-versa, would NOT carry its turn-proxies over — that's a deliberate convert, not this).
  const cmds = kind === "docker" ? [["docker", docker, "#c084e8"]]
    : kind === "baremetal" ? [["bare-metal", bare, "#60a5fa"]]
    : [["bare-metal", bare, "#60a5fa"], ["docker", docker, "#c084e8"]];
  return html`<${Sheet} title=${(isNew ? "Node created" : "New token") + " · " + name}
    foot=${html`<button class="btn btn-primary" onClick=${closeModal}>Done</button>`}>
    <div class="notice warn"><${Ic} i="warn"/><span><b>Shown once.</b> This token authenticates the node to the panel — copy it now. You can rotate it later if it leaks.</span></div>
    ${kind ? html`<div class="hint" style="margin-top:9px">This recovers <b>${name}</b> as <b>${kind === "docker" ? "docker" : "bare-metal"}</b> — the method it was already running, so its turn-proxies and interfaces are kept. To switch methods, convert the node instead.</div>` : null}
    <div class="field" style="margin-top:15px"><label>Enrollment token</label><div class="cmdrow"><div class="tokenbox">${token}</div><button class="copyaction" onClick=${() => copy(token, "Copied")}><${Ic} i="copy"/> Copy</button></div></div>
    ${cmds.map(([label, cmd, color]) => html`<div class="field"><label>Run on the node — <span style=${"color:" + color + ";font-weight:700"}>${label}</span></label><div class="cmdrow"><div class="tokenbox">${cmd}</div><button class="copyaction" onClick=${() => copy(cmd, "Copied")}><${Ic} i="copy"/> Copy</button></div></div>`)}
    ${kind ? null : html`<div class="hint">Pick one. Both fetch the installer and prompt for the node's endpoint.</div>`}
  <//>`;
}
function openNodeEdit(node) { openModal(html`<${NodeEditSheet} node=${node}/>`); }
// RFC1918 / loopback / link-local / CGNAT — kept selectable (valid behind cloud 1:1 NAT or on a private
// interconnect) but tagged "(private)" so an operator knows it isn't a public address.
const isPrivIp = ip => /^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(ip || "");
const ipLabel = ip => isPrivIp(ip) ? ip + " (private)" : ip;
// dropdown of the node's internet IPs (already excludes wg/awg/swg/docker) + an Auto option; keeps a
// current custom value (e.g. a hostname ingress) selectable even if it isn't in the reported IP list.
// IP picker: only the node's PUBLIC (internet-routable) IPs are listed; internal/private IPs are hidden.
// A "Use custom IP…" entry reveals a free-text field for any address not in the list (also how an already-set
// private/custom value is shown — preserved, editable). value "" = the Auto option.
function NodeIpPick({ ips, value, onChange, auto, customPlaceholder }) {
  const pub = (ips || []).filter(ip => !isPrivIp(ip));
  const valIsCustom = !!value && !pub.includes(value);
  const [custom, setCustom] = useState(valIsCustom);
  const sel = (custom || valIsCustom) ? "__custom__" : (value || "");
  const onSel = v => { if (v === "__custom__") setCustom(true); else { setCustom(false); onChange(v); } };
  return html`<${Fragment}>
    <select class="selwrap" value=${sel} onChange=${e => onSel(e.target.value)}>
      <option value="">${auto}</option>
      ${pub.map(ip => html`<option value=${ip}>${ip}</option>`)}
      <option value="__custom__">Use custom…</option>
    </select>
    ${sel === "__custom__" ? html`<input class="ipk-custom" placeholder=${customPlaceholder || "Custom IP — e.g. 203.0.113.5"} value=${value || ""} onInput=${e => onChange(e.target.value)} spellcheck="false" autocomplete="off"/>` : null}
  </${Fragment}>`;
}
function NodeEditSheet({ node }) {
  const rsv = (Store.panelSettings || {}).reserved || {};   // panel-wide defaults (used when the node has no override)
  const dSub = rsv.mesh_subnet || "10.255.0.0/16", dPort = String(rsv.mesh_port_base || 9999), dPfx = rsv.iface_prefix || "swg_";
  const [name, setName] = useState(node.name || ""); const [color, setColor] = useState(() => toThemed(node.color, NODE_COLOR_DEFAULT)); const [msg, setMsg] = useState(null);
  const [ingress, setIngress] = useState(node.endpoint_host || "");
  // mesh fields show the EFFECTIVE value in use (the node's override, else the panel default). Leaving it at
  // the default normalizes to "inherit" on save (no spurious override / re-provision).
  const [meshPort, setMeshPort] = useState(node.mesh_port ? String(node.mesh_port) : dPort);
  const [meshSubnet, setMeshSubnet] = useState(node.mesh_subnet || dSub);
  const [meshPrefix, setMeshPrefix] = useState(node.mesh_prefix || dPfx);
  const [defEgress, setDefEgress] = useState(node.default_egress_ip || "");
  const [panelIp, setPanelIp] = useState(node.panel_ip || "");
  const ips = node.ips || [];
  const ovSub = meshSubnet.trim() === dSub ? "" : meshSubnet.trim();   // normalized overrides (default → inherit)
  const ovPort = meshPort.trim() === dPort ? "" : meshPort.trim();
  const ovPfx = meshPrefix.trim() === dPfx ? "" : meshPrefix.trim();
  const nameBad = name.trim() && !V.nodeName(name);
  // Only a subnet or PREFIX change re-provisions (re-addresses / renames the iface → rebuild). A port-only
  // change is applied LIVE (the node re-ports in place + peers re-dial), so it needs no re-provision confirm.
  const reprovChanged = ovSub !== (node.mesh_subnet || "") || ovPfx !== (node.mesh_prefix || "");
  const doSave = () => {
    closeAllModals();   // close the sheet AND any re-provision confirm stacked on top; optimistic — the card reflects the change immediately
    mutate({
      key: "node:" + node.id,
      patch: s => { const n = s.nodes.find(x => x.id === node.id); if (n) { n.name = name.trim(); n.color = color; n.endpoint_host = ingress; n.mesh_port = ovPort; n.mesh_subnet = ovSub; n.mesh_prefix = ovPfx; n.default_egress_ip = defEgress; n.panel_ip = panelIp; } },
      call: () => api.nodeUpdate({ id: node.id, name: name.trim(), color, endpoint_host: ingress, mesh_port: ovPort, mesh_subnet: ovSub, mesh_prefix: ovPfx, default_egress_ip: defEgress, panel_ip: panelIp }),
    });
  };
  const save = async () => {
    if (!name.trim() || !V.nodeName(name)) return setMsg({ k: "err", t: "Name: 1–40 chars, letters/digits/-/_ only." });
    if (reprovChanged) {   // re-provisioning bounces this node's mesh links → confirm first
      return pushModal(html`<${ConfirmSheet} title="Re-provision this node's mesh links?" confirmLabel="Re-provision" warn=${true}
        body=${"Changing " + node.name + "'s mesh subnet/port/prefix rebuilds all of its node-to-node links with the new settings. " + node.name + " will briefly drop off the mesh (and any cascade/smart traffic routed through it pauses) until every peer pulls the new config and reconnects — usually a few seconds. Other nodes' links to each other are unaffected."}
        onConfirm=${doSave}/>`);
    }
    doSave();
  };
  const [showAwg, setShowAwg] = useState(false);
  const meshAwg = node.mesh_awg || {};
  const hasAwg = AWG_KEYS.some(k => meshAwg[k] != null && meshAwg[k] !== "");
  return html`<${Sheet} title=${"Node settings · " + node.name}
    foot=${html`<${Fragment}><button class="btn btn-ghost" title="Rotate this node's enrollment token (re-enroll / re-install)" onClick=${() => openNodeRotate(node)}><${Ic} i="key"/> Rotate key</button><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${save}>Save</button></>`}>
    <div class="field"><label>Name</label>
      <div class="namerow"><input autofocus class=${nameBad ? "bad" : ""} value=${name} onInput=${e => setName(e.target.value)} autocomplete="off"/>
        <${ThemedSwatch} val=${color} title="Node colour" onChange=${setColor} sample=${(c) => html`<span class="tg" style=${"background:color-mix(in srgb," + c + " 16%,transparent);color:" + c}>${name.trim() || node.name || "node"}</span>`}/></div>
      <div class=${"hint" + (nameBad ? " err" : "")}>${nameBad ? "1–40 chars: letters, digits, - or _ only." : "A label for this node — rename anytime, nothing else changes. The swatches set its colour per theme."}</div></div>
    <div class="seclabel">Egress</div>
    <div class="field"><label>Default egress IP <span class="faint" style="text-transform:none;letter-spacing:0">— direct internet exit</span></label>
      <${NodeIpPick} ips=${ips} value=${defEgress} onChange=${setDefEgress} auto="Auto (MASQUERADE)"/>
      <div class="hint">The fallback source IP this node SNATs to when traffic exits to the internet here — applied to any interface (and traffic received from other nodes) that doesn't set its own egress IP. Interfaces with their own egress IP, and cascading traffic that exits elsewhere, are unaffected.</div></div>
    <div class="field"><label>Panel egress connection IP <span class="faint" style="text-transform:none;letter-spacing:0">— source to reach the panel</span></label>
      <${NodeIpPick} ips=${ips} value=${panelIp} onChange=${setPanelIp} auto="Auto (default route)"/>
      <div class="hint">Source IP this node uses to reach the panel. Ignored on same-server installs; falls back to auto if it can't connect.</div></div>
    <div class="hint" style="margin-top:14px">Mesh settings (ingress IP, subnet, port, prefix, AWG) for this node are configured in <a href="#/panel/settings">Panel settings → System mesh</a> — select this node there.</div>
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}
function openNodeRecover(node) { openModal(html`<${NodeRecoverSheet} node=${node}/>`); }
function NodeRecoverSheet({ node }) {
  const go = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(r.error || "couldn't generate a recovery command", "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind}/>`); };
  return html`<${Sheet} title=${"Recover node · " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${go}>Generate recovery command</button></>`}>
    <div class="notice"><${Ic} i="info"/><span>This node isn't reporting. Generating a recovery command rotates its token and gives you a one-line command to paste on the server — it re-installs/recovers <b>${node.name}</b> as the <b>same node</b>, so its interfaces and peers come straight back (no need to find the old token).</span></div>
    <div class="notice warn" style="margin-top:10px"><${Ic} i="warn"/><span>The node's current token stops working immediately — use this only when the node is genuinely down or you've lost its install command.</span></div>
  <//>`;
}
function openNodeRotate(node) { openModal(html`<${NodeRotateSheet} node=${node}/>`); }
function NodeRotateSheet({ node }) {
  const go2 = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(r.error || "rotate failed", "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind}/>`); };
  return html`<${Sheet} title=${"Rotate token · " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" onClick=${go2}>Rotate</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>The current token stops working immediately. Re-enroll the node with the new token or it will go offline.</span></div>
  <//>`;
}
function openNodeRemove(node) { openModal(html`<${NodeRemoveSheet} node=${node}/>`); }
function unflagNode(n) {   // cancel a pending soft removal — keep the node
  mutate({
    key: "node:" + n.id,
    patch: s => { const x = s.nodes.find(y => y.id === n.id); if (x) { delete x.removing; delete x.removing_at; } },
    call: () => api.nodeUnflagRemove({ id: n.id }),
  });
}
// Force-remove a node — destructive (cuts it off immediately + drops peers that live only here), so gated behind typing "DELETE <name>" (case-sensitive), like deleting an interface/turn-proxy.
function ForceRemoveNodeSheet({ node }) {
  const [txt, setTxt] = useState(""); const [busy, setBusy] = useState(false);
  const phrase = "DELETE " + node.name;
  const ok = txt === phrase;
  const here = Store.recon.peers.filter(p => p.targets.some(t => t.node === node.id));
  const onlyHere = here.filter(p => new Set(p.targets.map(t => t.node)).size === 1).length;
  const del = () => {
    if (!ok || busy) return;
    setBusy(true); closeAllModals();
    mutate({
      key: "node:" + node.id,
      patch: s => {                                  // optimistic: drop the node + purge its targets (mirrors the cascade)
        s.nodes = s.nodes.filter(x => x.id !== node.id);
        for (const id of Object.keys(s.roster.peers)) {
          const p = s.roster.peers[id]; p.targets = p.targets.filter(t => t.node !== node.id);
          if (!p.targets.length) delete s.roster.peers[id];
        }
      },
      call: () => api.nodeDelete({ id: node.id }),
    });
    toast("Node force-removed.", "ok");
  };
  return html`<${Sheet} title=${"Force remove · " + node.name}
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-danger" disabled=${!ok || busy} onClick=${del}>Force remove</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span>This cuts <b>${node.name}</b> off <b>immediately</b> without waiting for it to confirm — ${onlyHere ? html`<b>${onlyHere}</b> peer${onlyHere === 1 ? "" : "s"} that live only here ${onlyHere === 1 ? "is" : "are"} dropped` : "peers that live only here are dropped"}. Use this only when the server is unreachable. This can't be undone.</span></div>
    <div class="field"><label>Type <span class="mono" style="text-transform:none">${phrase}</span> to confirm</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
}
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
  const force = () => pushModal(html`<${ForceRemoveNodeSheet} node=${node}/>`);   // typed "DELETE <name>" confirmation (matches interface/turn-proxy deletes)
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
  { re: /^\/panel\/settings$/, fn: PanelSettingsScreen, tab: "panel-settings" },
];
function go(hash) { location.hash = hash; }
let _unsavedGuard = null, _prevHash = location.hash || "#/";   // a screen with unsaved edits registers () => true; the router confirms before navigating away
function matchRoute(hash) {
  const path = (hash || "#/").replace(/^#/, "") || "/";
  for (const r of ROUTES) { const m = path.match(r.re); if (m) { const params = {}; (r.keys || []).forEach((k, i) => params[k] = m[i + 1]); return { route: r, params }; } }
  return { route: ROUTES[0], params: {} };
}

function App() {
  useStore();                                   // re-render on every poll
  const [hash, setHash] = useState(location.hash || "#/");
  const [modalStack, setModalStack] = useState([]);
  useEffect(() => { _setStack = setModalStack; }, []);
  useEffect(() => {
    const onHash = () => {
      const nh = location.hash || "#/";
      if (_unsavedGuard && nh !== _prevHash && _unsavedGuard() && !confirm("You have unsaved changes that will be lost. Leave without saving?")) {
        history.replaceState(null, "", _prevHash); return;   // stay put — restore the URL without re-firing
      }
      _unsavedGuard = null; _prevHash = nh;
      setHash(nh); _applyStack([]); window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    // Esc/Enter inside dialogs are owned by <Sheet> (with its dirty-guard); nothing global here.
    // A MOUSE click on an icon button / nav tab shouldn't leave a lingering focus ring (it persists
    // after a modal closes, then any keypress like Shift re-shows it). Suppressing the focus on
    // mousedown keeps the click working while keyboard Tab still focuses (and shows the ring).
    const onMD = e => { const el = e.target && e.target.closest && e.target.closest(".iconbtn, #tabs a"); if (el) e.preventDefault(); };
    document.addEventListener("mousedown", onMD, true);
    return () => { window.removeEventListener("hashchange", onHash); document.removeEventListener("mousedown", onMD, true); };
  }, []);

  const { route, params } = matchRoute(hash);

  // static chrome lives in index.html — keep it in sync imperatively
  useEffect(() => {
    trackTurnRestarts();                                             // detect completed turn restarts → green flash
    trackIfaceOps();                                                 // interface start/restart progress lifecycle
    const lp = $("#livepill");                                       // online USERS, with a per-user peer-count bubble
    if (lp) {
      lp.classList.toggle("off", onlineUserRows(null).length === 0);   // 0 = grey, no dot
      render(html`<${OnlineUsersTag} nodeId=${null} cls="bare" trigger=${c => html`<span class="dot"></span><b id="kpi-online">${c}</b> online`}/>`, lp);
    }
    const v = Store.versions || {}, el = $("#appver");
    if (v.panel) {            // panel came back on a different version → it was updated; prompt a hard reload
      if (seenPanelVer && seenPanelVer !== v.panel) { hostUpdating = false; pendingUpdateDone = [seenPanelVer, v.panel]; }
      seenPanelVer = v.panel;
    }
    // Pop the "Panel updated — reload" prompt only once the host lifecycle has FINISHED (host_proc no longer
    // in-progress). On a master the panel restarts after its own phase while the node phase is still running, so
    // firing on the version bump alone would show "updated" once now and again when host_proc lands its terminal —
    // i.e. twice on the header. Holding it until host_proc settles makes that a single "updated".
    if (pendingUpdateDone && !inProc(Store.hostProc)) { const _u = pendingUpdateDone; pendingUpdateDone = null; openUpdateDone(_u[0], _u[1]); }
    if (el && v.panel) {        // panel version only — the host's awg/wg/docker versions aren't shown
      el.innerHTML = `<b>${esc(v.panel)}</b>`;
    }
    const ht = $("#host-tport");      // how the PANEL itself is deployed (docker / bare-metal)
    if (ht && Store.env && ("docker" in Store.env)) {
      const dk = !!Store.env.docker;
      ht.className = "tport " + (dk ? "docker" : "baremetal");
      ht.textContent = dk ? "docker" : "bare-metal";
      ht.hidden = false;
    }
    const slot = $("#updslot");
    if (slot) {
      // a host lifecycle status (re-install / update) OWNS the slot — in-progress, then its terminal
      // (success ~5s auto-clears, aborted/failed until ×) — so it never shows alongside the update-check
      // "up to date"/button. With no lifecycle status, the slot is the normal update widget.
      let body;
      const _hl = esc(PROC_LABEL[Store.hostProc] || Store.hostProc || "");
      if (inProc(Store.hostProc)) body = `<span class="hostproc-tag ${procInClass(Store.hostProc)}">${UPD_SPIN_SVG} ${_hl}</span>`;
      else if (procSuccess(Store.hostProc)) body = `<span class="hostproc-tag ok">${CHECK_SVG} ${_hl}</span>`;   // green, auto-clears (no ×)
      else if (procAborted(Store.hostProc)) body = `<span class="hostproc-tag aborted">${INFO_SVG} ${_hl}<button class="xbtn" id="hostproc-x" title="Dismiss">${X_SVG}</button></span>`;
      else if (procFailed(Store.hostProc)) body = `<span class="hostproc-tag fail${Store.hostProcErr ? ' tg-click' : ''}" id="hostproc-tag">${WARN_SVG} ${_hl}<button class="xbtn" id="hostproc-x" title="Dismiss">${X_SVG}</button></span>`;   // whole tag clickable → error popup
      else if (hostUpdating) body = `<span class="livepill upd-busy">updating… ${UPD_SPIN_SVG}</span>`;
      else if (Store.panelOutdated) body = `<button class="livepill updpill" id="host-upd" title="Update this server">update to <b>${esc(Store.latestRemote || "?")}</b></button>`;
      else if (Store.updFlash && Date.now() < Store.updFlash) body = `<span class="livepill upd-uptodate" title="You're on the latest version"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> up to date</span>`;
      else body = `<button class="iconbtn lg" id="upd-check" title="Check for updates"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></button>`;
      slot.innerHTML = body;
      const b = $("#host-upd"); if (b) b.onclick = updateHost;
      const c = $("#upd-check"); if (c) c.onclick = checkForUpdate;
      const hx = $("#hostproc-x"); if (hx) hx.onclick = e => { e.stopPropagation(); dismissHostProc(); };
      const htg = $("#hostproc-tag"); if (htg && Store.hostProcErr) htg.onclick = () => openConfirm({ title: PROC_LABEL[Store.hostProc] || Store.hostProc, log: Store.hostProcErr, confirmLabel: "Close" });
    }
    $$("#tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === route.tab));
    const acct = $("#acct-btn"); if (acct) acct.onclick = () => doLogout();   // header logout icon → straight to the confirm
    const tb = $("#theme-btn"); if (tb && !tb._wired) { tb._wired = true; tb.onclick = cycleThemeMode; paintThemeBtn(tb); }   // light/dark/auto switch
  });

  return html`<${Fragment}>
    ${h(route.fn, params)}
    ${modalStack}
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
    body: "Are you sure you want to logout?",
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
