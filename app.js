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
      ${(ips || []).map(ip => html`<option value=${ip}>${ip}</option>`)}
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
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
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
    this.recon = reconcile(this.roster, this.stats, Date.now(), { retiring, rotating: new Set(Object.keys(this.rotating)) });
    // a rotation is "done" once the new key shows up live (or after a 45s safety cap) — drop the marker
    for (const id of Object.keys(this.rotating)) {
      const pr = this.recon.peers.find(p => p.id === id);
      if ((pr && (pr.status === "online" || pr.status === "ready" || pr.status === "partial")) || (Date.now() - this.rotating[id] > 45000)) delete this.rotating[id];
    }
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
// a node is "stale" when its last snapshot is older than the staleness window (reconcile.js) — we can't
// trust any live state then, so cross-reference badges grey out (don't claim "active" on a node gone dark).
function nodeStale(node) { return Store.recon.nodeStatus[node] !== "live"; }
function ifaceDown(node, ifn) { return !!(((((Store.stats[node] || {}).interfaces) || {})[ifn] || {}).down); }
function ifaceNotUp(node, ifn) { const s = (((Store.stats[node] || {}).interfaces) || {})[ifn] || {}; return !!s.down || !!s.stopped; }  // down OR stopped → grey chips
function turnDown(tp) { return tp && tp.running === false; }
// turn badges for an interface card: one fork-coloured "turn" chip per distinct forwarding fork
// (collapses to one in the common single-fork case), greyed when that fork's proxies are all down / node stale.
function ifaceTurnBadges(node, fwdTurns) {
  if (!fwdTurns || !fwdTurns.length) return null;
  const stale = nodeStale(node), groups = {};
  fwdTurns.forEach(tp => { const f = turnFork(tp.service); (groups[f] = groups[f] || []).push(tp); });
  return Object.entries(groups).map(([f, list]) => {
    const allDown = list.every(turnDown);
    return html`<span class=${"tg tg-turn tf-" + f + ((stale || allDown) ? " muted" : "")}
      title=${list.length + " " + f + " turn-prox" + (list.length > 1 ? "ies" : "y") + " forward to this interface" + (allDown ? " — down" : "")}>turn</span>`;
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
  const dim = converting || nodeStale(node) || (!justRestarted && (installing || queued || pend || failed || down || stopped || err));   // dim through the WHOLE 'creating' phase (installing/queued/assigned) like the pending card + attention states (failed/down/stopped/deleting) — only a settled/ready card is full-bright
  const _busy = !!(queued || installing || (pend && pend !== "delete"));   // any in-flight create / install / op
  const _bad = !!(failed || down || converting || stopped);
  const _settled = !!fronted && !_bad && !_busy;                           // up + healthy
  if (turnWasInstalling[k] && !installing && !_bad) turnReady[k] = Date.now() + 5000;   // OPTIMISTIC: install just ended without failing → "ready" NOW (don't fall back to pending)
  if (turnWasBusy[k] && _settled) turnReady[k] = Date.now() + 5000;        // settled to up after any in-flight state (covers no-install reuse: pending → up)
  turnWasInstalling[k] = !!installing;
  turnWasBusy[k] = _busy;
  const turnReadyNow = !_bad && !!fronted && !!turnReady[k] && Date.now() < turnReady[k];
  const conn = fronted ? turnConnRows(node, fronted, ipOf(tp.connect)) : [];   // online peers via this proxy → header count
  const canOpen = nrec.turn_manage && !converting && !_busy && pend !== "delete";   // clickable only once it settles — NOT while creating/queued/deleting (don't open a half-created proxy)
  return html`<div class=${"ifcard tp" + (canOpen ? " clickable" : "") + (dim ? " down" : "") + (it ? it.cls : "")} onClick=${canOpen ? () => openTurnManage(node, tp) : null} data-rid=${it ? it.rid : null}>
    <div class="ifcard-top">${reorder ? html`<span class="drag-grip" title="Drag to reorder" onClick=${e => e.stopPropagation()} ...${reorder.grip(tp.service)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}<span class=${"iftype turn tf-" + turnFork(tp.service)}>turn</span><span class="ifname">${tp.title || turnFork(tp.service)}</span><span class="grow"></span>${conn.length ? html`<${OnlPop} peer title="Via this turn-proxy" cls="ifc-conn" rows=${conn} trigger=${c => html`<b class="oncount on">${c}</b>`}/>` : null}${converting
      ? html`<${StatusTag} cls="tg-convert" icon="clock" label="converting" title="The node is converting between bare-metal and docker"/>`
      : pend === "delete"
      ? html`<${StatusTag} cls="tg-busy del" label="deleting…" msg=${err || prog} title=${err ? "Command failed on the node" : "Working on the node"}/><button class="xbtn" title="Cancel this request" onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>`
      : installing ? html`<${StatusTag} cls=${"tg-busy" + (prog ? " warn" : "")} icon="clock" label="creating" msg=${prog} title="The node is setting it up right now"/>`
      : turnReadyNow ? html`<span class="tg tg-ready"><${Ic} i="check"/>ready</span>`
      : (pend || queued) ? html`<${StatusTag} cls="tg-busy" icon="clock" label="creating" msg=${err} title=${pend ? "The node is setting it up" : "Queued — the node creates these one at a time"}/>${pend ? html`<button class="xbtn" title="Cancel this request" onClick=${e => { e.stopPropagation(); cancelTurn(node, { service: tp.service }); }}><${Ic} i="x"/></button>` : null}`
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
function useReorder(ids, onReorder, axis = "x") {   // axis "x" = horizontal grid (left/right edges); "y" = vertical list (top/bottom)
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
          cont.current = e.currentTarget.closest(".ifgrid, .nodegrid");
          idRef.current = id; liveK.current = -1; esc.current = false;
          onKey.current = ev => { if (ev.key === "Escape") esc.current = true; };
          window.addEventListener("keydown", onKey.current, true);
          const card = e.currentTarget.closest(".ifcard, .ncard");
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
const STATUS_RANK = { dangling: 0, partial: 1, pending: 2, creating: 2, rotating: 2, unknown: 3, unassigned: 4, online: 5, ready: 6 };
const STATUS_ICON = { online: "check", ready: "clock", partial: "warn", pending: "clock", creating: "clock", rotating: "refresh",
  dangling: "err", unknown: "info", unassigned: "user", orphan: "link", removing: "trash", empty: "info" };
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
  return html`<span class=${"badge b-" + s + (ic ? " ic" : "")} title=${title || ""}>${ic ? html`<${Ic} i=${ic}/>` : null}${s}</span>`;
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

// Generic hover/click bubble (the DepBadge mechanics, reusable): hover opens, click pins (touch),
// position:fixed anchored to the trigger so overflow:hidden can't clip it.
function Popover({ trigger, cls, children }) {
  const [open, setOpen] = useState(false), [pinned, setPinned] = useState(false), [pos, setPos] = useState(null);
  const ref = useRef(null), closeT = useRef(null);
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
  return html`<span class=${(cls || "") + (show ? " on" : "")} ref=${ref}
    onClick=${e => { e.stopPropagation(); e.preventDefault(); setPinned(p => !p); }}
    onMouseEnter=${() => { cancelClose(); setOpen(true); }} onMouseLeave=${scheduleClose}>${trigger}
    ${show && pos ? html`<div class="deppop onlpop" style=${"left:" + pos.left + "px;top:" + pos.top + "px"}
      onClick=${e => e.stopPropagation()} onMouseEnter=${cancelClose} onMouseLeave=${scheduleClose}>${children}</div>` : null}
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
function turnConnRows(nodeId, iface, connectIp) {
  const onT = (t) => t.node === nodeId && t.iface === iface && t.online && t.observed && ipOf(t.observed.endpoint) === connectIp;
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
    onOk: () => { Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; },
  });
}

// Rotate a peer's keypair while KEEPING its PSK (PSK is user-owned — rotated only from the user
// module). Mints a new keypair in the browser, preserves each target's current config settings
// (DNS/MTU/AllowedIPs/keepalive) where readable, and re-issues. The old config stops working,
// so the client must re-import the fresh QR/config. Only meaningful for an assigned peer.
async function rotatePeerKeys(peer) {
  const key = "peer:" + peer.id;
  Store.rotating[peer.id] = Date.now();   // grid shows "rotating" until the new key is live
  let keys, configs;
  try {
    keys = await genKeys(); configs = {};
    for (const t of peer.targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: Store.nodeName(t.node) + " hasn't reported " + t.iface + " yet", at: Date.now() }; Store.apply(); return; }
      const cur = await getConfig(peer.pubkey, t.node, t.iface);
      const s = cur ? parseFullConf(cur) : null;
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: (t.ip || "").split("/")[0] + "/32",
        dns: s ? s.dns : m.dns, mtu: s ? s.mtu : 1280, awg_params: m.awg_params, server_pubkey: m.public_key,
        psk: peer.psk, endpoint: m.endpoint, allowed: s ? s.allowed : "0.0.0.0/0, ::/0", keepalive: s ? s.keepalive : 25 });
    }
  } catch (e) { delete Store.rotating[peer.id]; Store.rowErrors[key] = { msg: String(e.message || e), at: Date.now() }; Store.apply(); return; }
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
    <input class="uc-input" value=${q} placeholder=${placeholder || "Assign to…"} onClick=${() => setOpen(true)}
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
      onClick=${() => { setOpen(true); setQ(""); }} onInput=${e => { setQ(e.target.value); setOpen(true); }}/>
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
      <div class="fnode-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="fnode-name">${n.name}</span>${al.length ? html`<span class="halert hot"><${Ic} i="warn"/> ${al.length}</span>` : ""}<span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>
      <div class="fnode-stats">
        <div><span class="fl">Traffic</span><span class=${"ratecell" + (nrx + ntx > 0 ? " live" : "")}>↓ ${rate(nrx)} <span class="up">↑ ${rate(ntx)}</span></span></div>
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
    const col = n.color || Store.nodeColor(n.id);
    return n.id === active
      ? html`<span class="nbadge on" style=${"--c:" + col} title=${n.name}>${n.name}</span>`
      : html`<a class="nbadge" style=${"--c:" + col} href=${"#/node/" + encodeURIComponent(n.id)} title=${"Go to " + n.name}>${n.name}</a>`;
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

  // drag-to-reorder the interface cards (saved order overlays the node's reported set)
  const ifaceIds = orderById(meta ? Object.keys(meta) : [], nrec.iface_order, x => x);
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
      <div class="title">${(nrec.outdated || (nrec.local && Store.panelOutdated)) && !nrec.updating ? html`<span class="upd-dot" title="Update available"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}<h1>${dname}</h1>${nrec.kind ? html`<span class=${"tport " + nrec.kind}>${nrec.kind === "docker" ? "docker" : "bare-metal"}</span>` : null}${nrec.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> uninstalled</span>` : live ? html`<span class="reporting">reporting</span>` : nrec.status === "dangling" ? html`<span class="nstat enroll"><${Ic} i="clock"/> awaiting enroll</span>` : html`<span class="badge b-unknown ic"><${Ic} i="info"/>stale</span>`}${nrec.proc_status && !isUpdateState(nrec.proc_status) ? procTag(nrec.proc_status, () => dismissNodeProc(nrec.id), nrec.proc_err, !live && nrec.status === "dangling") : null}<${HealthDot} issues=${nrec.issues}/></div>
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
        <button class="iconbtn" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Edit node"} onClick=${() => openNodeEdit(nrec)}><${Ic} i="pencil"/></button>
        ${down ? null : html`<button class="iconbtn" title="Rotate token (re-enroll / re-install)" onClick=${() => openNodeRotate(nrec)}><${Ic} i="key"/></button>`}
        <button class="iconbtn danger" title=${nrec.removing ? "Force remove node" : "Remove node"} onClick=${() => openNodeRemove(nrec)}><${Ic} i="trash"/></button>
        ${down ? html`<button class="iconbtn recover" title="Recover this node — rotate its token and get a fresh paste-on-the-server install command (the node keeps its peers)" onClick=${() => openNodeRecover(nrec)}><${Ic} i="key"/> recover</button>` : null}
      </div>
    </div>

    ${!snap ? html`<div class="node-nodata"><${Ic} i="activity"/><p>This node isn't sending any data right now</p></div>` : html`<div class="noderibbon">
      <div class="nr-tags">
        ${orderById(meta ? Object.keys(meta) : [], nrec.iface_order, x => x).map(ifn => {
          const type = (meta[ifn].awg_params && Object.keys(meta[ifn].awg_params).length) ? "awg" : "wg";
          return html`<a class=${"tg tg-" + type + ((nodeStale(name) || ifaceNotUp(name, ifn)) ? " muted" : "")} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}>${ifn}</a>`;
        })}
        ${orderById((snap && snap.turn_proxies) || [], nrec.turn_order, tp => tp.service).map(tp => html`<span class=${"tg tg-turn tf-" + turnFork(tp.service) + ((nodeStale(name) || turnDown(tp)) ? " muted" : "")}>${turnLabel(tp.service, portOf(tp.listen) || portOf(tp.connect))}</span>`)}
      </div>
      <span class="grow"></span>
      <div class="nr-sync"><span class="when">${syncTxt}</span>${nrec.health && nrec.health.uptime != null ? html`<span class="when">up ${dur(nrec.health.uptime)}</span>` : null}</div>
    </div>

    ${nrec.health ? html`<${Panel} icon="activity" title="Health" tone="online"
      actions=${html`<${Fragment}>${nrec.removing ? html`<span class="badge b-removing ic"><${Ic} i="trash"/>flagged for removal</span><button class="btn btn-mini" style="margin-left:9px" title="Cancel removal — keep this node" onClick=${() => unflagNode(nrec)}>Cancel</button>` : null}</>`}>
      <${HealthAlerts} health=${nrec.health}/>
      ${nrec.health_history
        ? html`<${RangedHistory} node=${name} kind="cpu" live=${nrec.health_history} liveFine=${nrec.health_live} h=${52} head=${html`<${HealthMeters} health=${nrec.health}/>`}/>`
        : html`<${HealthMeters} health=${nrec.health}/>`}
    <//>` : null}

    ${nrec.health_history ? html`<${Panel} icon="gauge" title="Throughput">
      <${RangedHistory} node=${name} kind="throughput" live=${nrec.health_history} liveFine=${nrec.health_live} h=${72}/>
    <//>` : null}

    <${Panel} icon="network" title="Interfaces" count=${meta ? Object.keys(meta).length : 0}
        actions=${html`<${Fragment}>${nrec.turn_manage && !hasTurns ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Set up the node's first turn-proxy"} onClick=${() => openSetupTurn(name)}><${Ic} i="plus"/> Setup turn-proxy</button>` : null}<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openOnboardIface(name)}><${Ic} i="plus"/> Create new interface</button><//>`}>
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
        const pendOn = (nrec.onboarding || []).filter(ifn => !(meta && meta[ifn]) && !optNames.includes(ifn));
        const cr = nrec.creating || {};   // { iface: "wg" | "awg" } — server-side, deduped against the client cards
        const pendCr = Object.keys(cr).filter(ifn => !(meta && meta[ifn]) && !optNames.includes(ifn));
        const optCards = optNames.filter(ifn => !(meta && meta[ifn])).map(ifn => optIfCard(ifn, Store.ifaceNew[_pfx + ifn]));
        const pending = pendOn.concat(pendCr, optNames);
        pending.forEach(ifn => { ifaceWasBusy[name + "|" + ifn] = true; });   // any in-flight iface (create / onboard / server) → flash "ready" once it appears in meta
        const pcards = pendOn.map(ifn => pcard(ifn, "onboarding", null))
          .concat(pendCr.map(ifn => pcard(ifn, "creating", cr[ifn])))
          .concat(optCards);
        return metaErr ? html`<div class="notice warn"><${Ic} i="warn"/><span>This node hasn't reported in yet — its interfaces will show up here once it runs the installer and syncs.<br/><br/>Lost the enrollment token or the install command? Rotate the node's token to generate a fresh install command.</span></div>`
          : !meta ? html`<div class="loading"><span class="spin"></span>reading server…</div>`
          : (!Object.keys(meta).length && !pending.length) ? html`<div class="notice warn"><${Ic} i="warn"/><span>No managed interfaces reported.</span></div>`
          : html`<div class="ifgrid" ...${ifReorder.container()}>${orderById(Object.keys(meta), nrec.iface_order, x => x).map(ifn => {
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
              const idim = iconverting || deleting || idown || istopped || irestarting || iopBusy || !!iprog || nodeStale(name) || !!(nrec.cmd_errors || {})[ifn];   // attention / stopped / in-flight / node gone dark → dim
              return html`<a key=${ifn} class=${"ifcard" + (deleting ? " pending" : "") + (idim ? " down" : "") + it.cls} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} draggable=${false} data-rid=${it.rid}>
                <div class="ifcard-top"><span class="drag-grip" title="Drag to reorder" onClick=${e => e.preventDefault()} ...${ifReorder.grip(ifn)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span><span class=${"iftype " + type}>${type}</span><span class="ifname">${ifn}</span><span class="grow"></span>${ifaceTurnBadges(name, fwdTurns)}${iprog ? html`<${CmdErr} err=${iprog} cls="warn" title="Working on the node"/>` : null}${iopBusy ? html`<span class="tg tg-busy"><${Ic} i="clock"/>${IFOP_BUSY[iop.verb] || iop.verb}</span>` : iconverting ? html`<span class="tg tg-convert" title="The node is converting between bare-metal and docker"><${Ic} i="clock"/>converting</span>` : deleting ? html`<${StatusTag} cls="tg-del" icon="clock" label="deleting" msg=${(nrec.cmd_errors || {})[ifn]} title="Command failed on the node"/>` : istopped ? html`<span class="tg-off" title="Stopped by you — open to Start it"><${Ic} i="stop"/>stopped</span>` : idown ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="down" msg=${(nrec.cmd_errors || {})[ifn] || ("interface is down on the node — awg-quick couldn't bring it up: " + idown)} title="Interface down on the node"/>` : irestarting ? html`<span class="tg tg-busy"><${Ic} i="clock"/>restarting</span>` : ((nrec.cmd_errors || {})[ifn] ? html`<${StatusTag} cls="tg-busy del" icon="warn" label="error" msg=${(nrec.cmd_errors || {})[ifn]} title="Command failed on the node"/>` : (m.drift && Object.keys(m.drift).length) ? html`<span class="tg tg-pending" title="A setting was edited directly on the server — open to Adopt or Restore"><${Ic} i="warn"/>modified</span>` : (ifaceReady[name + "|" + ifn] && Date.now() < ifaceReady[name + "|" + ifn]) ? html`<span class="tg tg-ready"><${Ic} i="check"/>ready</span>` : null)}</div>
                <div class="ifcard-rows">
                  <div class="ifrow"><span class="l">Listen</span><span class="r addr">${m.endpoint || ((m.address || "").split("/")[0] + (m.listen_port ? ":" + m.listen_port : "")) || "—"}</span></div>
                  <div class="ifrow"><span class="l">Subnet</span><span class="r addr">${m.subnet || "—"}</span></div>
                  <div class="ifrow"><span class="l">Peers</span><span class="r">${ps.length
                    ? html`<${OnlinePeersTag} nodeId=${name} iface=${ifn} orphans=${orph} orphHref=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)}
                        trigger=${() => html`<b class=${"oncount" + (onlc ? " on" : "")}>${onlc}</b><span class="faint">/${ps.length}</span>${orph ? html` <span class="ifc-orph" title=${orph + " unmanaged (orphan) peer" + (orph === 1 ? "" : "s")}>(${orph})</span>` : null}`}/>`
                    : (orph ? html`<span class="ifc-orph" title=${orph + " unmanaged (orphan) peer" + (orph === 1 ? "" : "s")}>${orph}</span>` : html`<span class="faint">none</span>`)}</span></div>
                </div></a>`;
            })}${pcards}</div>`; })()}
    <//>

    ${hasTurns ? html`<${TurnProxiesBlock} node=${name} nrec=${nrec} snap=${snap} metas=${meta} title="Turn proxies"/>` : null}
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
    return ((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + (u ? u.name : "")).toLowerCase().includes(ql);
  });

  return html`<div class="screen">
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b><${NodeBadges} active=${node}/></div>
    <div class="detail-head">
      <div class="title"><h1>${iface}</h1><span class=${"iftype " + type}>${type}</span>${istopped ? html`<span class="badge b-unknown ic" title="Stopped by you — Start it whenever you're ready"><${Ic} i="stop"/>stopped</span>` : idown ? html`<span class="badge b-dangling ic" style="cursor:pointer" title=${(nrec.cmd_errors || {})[iface] || ("down on the node — " + idown)} onClick=${() => openConfirm({ title: "Interface down on the node", log: (nrec.cmd_errors || {})[iface] || ("down on the node — " + idown), confirmLabel: "Close" })}><${Ic} i="warn"/>down</span>` : live ? html`<span class="reporting">reporting</span>` : html`<span class="badge b-unknown ic"><${Ic} i="info"/>stale</span>`}<span class="when"><${OnlinePeersTag} nodeId=${node} iface=${iface} total=${peers.length} orphans=${orphCount(node, iface)}/></span></div>
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

    <${TurnProxiesBlock} node=${node} nrec=${nrec} metas=${Store.describe[node] || {}} title="Reachable via turn-proxy" iface=${iface}/>

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
  for (const b of Object.values((Store.stats[node] || {}).interfaces || {})) {
    const s = (b.meta || {}).subnet || (b.meta || {}).address || "";
    const m = /^10\.(\d{1,3})\./.exec(s); if (m) hi = Math.max(hi, Number(m[1]));
  }
  for (const p of pendingIf(node)) { const m = /^10\.(\d{1,3})\./.exec(p.subnet || ""); if (m) hi = Math.max(hi, Number(m[1])); }   // include the ones being created
  return "10." + (hi + 1) + ".0.0/24";
}
function LoadIfaceSheet({ node }) {
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";   // only bridge needs port publishing
  const [proto, setProto] = useState("awg");   // awg | wg | existing
  const sugAwg = suggestIface(node, "awg"), sugWg = suggestIface(node, "wg");   // auto-suggested names (per base)
  const [iface, setIface] = useState(sugAwg); const [subnet, setSubnet] = useState(suggestSubnet(node));
  const [host, setHost] = useState(""); const [port, setPort] = useState(String(suggestPort(node, "iface")));
  const [dns, setDns] = useState("1.1.1.1"); const [mtu, setMtu] = useState("1280"); const [ka, setKa] = useState("25");
  const [conf, setConf] = useState("");
  const ips = nrec.ips || []; const [egress, setEgress] = useState("");
  // endpoint host: dropdown of the node's known IPs (default the first), last entry = a free-text "Custom IP / Host…"
  const [hostSel, setHostSel] = useState(ips[0] || "__custom__"); const [hostCustom, setHostCustom] = useState("");
  const pickProto = p => {   // switching base re-suggests the name only if the field is still an untouched suggestion
    if (p !== "existing" && (iface === sugAwg || iface === sugWg || !iface.trim())) setIface(p === "wg" ? sugWg : sugAwg);
    setProto(p);
  };
  const wanifs = nrec.wan_ifaces || []; const [wan, setWan] = useState("");
  const ipIfaces = nrec.ip_ifaces || [];   // [{ip, iface}] for the merged egress picker
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
      const hostVal = ipPickerVal(hostSel, hostCustom);
      r = await api.ifaceCreate({ node, iface: nm, protocol: proto, subnet: subnet.trim(), endpoint_host: hostVal,
        listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), egress_ip: egress, wan_iface: wan });
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
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>${existing ? "Adopt" : "Create"}</button></>`}>
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
      <div class="row2">
        <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="1.1.1.1"/><div class="hint">Comma-separated</div></div>
        <div class="field"><label>Outbound (egress) IP / interface</label>
          <select class="selwrap" value=${egress ? egress + "|" + wan : ""} onChange=${e => { const [eip, eifc] = e.target.value.split("|"); setEgress(eip || ""); setWan(eifc || ""); }}>
            <option value="">Auto (MASQUERADE)</option>
            ${ipIfaces.map(p => html`<option value=${p.ip + "|" + p.iface}>${p.ip} — ${p.iface}</option>`)}
          </select>
          <div class="hint">Source IP + NIC clients egress from</div></div>
      </div>
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
function EditIfaceSheet({ node, iface }) {
  const meta = Store.ifaceMeta(node, iface) || {};
  const ep = meta.endpoint || "";
  const epHost = ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
  const [host, setHost] = useState(epHost);
  const [port, setPort] = useState(String(meta.desired_port || meta.listen_port || ""));
  const [dns, setDns] = useState((meta.dns || []).join(", "));
  const [mtu, setMtu] = useState(String(meta.mtu || 1280));
  const [ka, setKa] = useState(String(meta.keepalive || 25));
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ips = nrec.ips || [];
  const [egress, setEgress] = useState(meta.egress_ip || "");
  const wanifs = nrec.wan_ifaces || [];
  const [wan, setWan] = useState(meta.wan_iface || "");
  const ipIfaces = nrec.ip_ifaces || [];   // [{ip, iface}] — merged egress picker
  const egPairs = (egress && !ipIfaces.some(p => p.ip === egress)) ? [{ ip: egress, iface: wan || "?" }, ...ipIfaces] : ipIfaces;
  const isAwg = !!(meta.awg_params && Object.keys(meta.awg_params).length);
  const [awg, setAwg] = useState(() => Object.assign({}, meta.awg_params || {}));
  const setAwgK = (k, v) => setAwg(a => ({ ...a, [k]: v }));
  const ist = (((Store.stats[node] || {}).interfaces || {})[iface] || {});
  const istopped = !!ist.stopped;            // operator stopped it (not a failure)
  const idown = !istopped && ist.down;       // genuinely down
  const notup = !!idown || istopped;         // either way: Save brings it up; footer offers Start
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const doSave = async () => {
    const body = { node, iface, endpoint_host: host.trim(), listen_port: port.trim(), dns: dns.trim(), mtu: mtu.trim(), keepalive: ka.trim(), egress_ip: egress, wan_iface: wan };
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
      <span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>Save</button></>`}>
    <div class="iface-intro">
      <div>Changing the <b>endpoint</b> or <b>port</b> will break the existing clients' connections.</div>
      <div>You will need to re-distribute the configs / QR codes.</div>
    </div>
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
    <div class="field"><label>Tunnel subnet</label><div style="font-size:13.5px;color:var(--ink);padding:2px 0"><b>${meta.subnet || "—"}</b> <span class="faint">· host uses ${(meta.address || "").split("/")[0] || "—"} (set at creation — delete & recreate to change)</span></div></div>
    <div class="row2">
      <div class="field"><label>Endpoint host / IP</label><input autofocus value=${host} onInput=${e => setHost(e.target.value)} placeholder="vpn.xyz.com or 203.0.113.7"/><div class="hint">What clients dial — config-facing only</div></div>
      <div class="field"><label>Listen port</label><input value=${port} onInput=${e => setPort(e.target.value)} placeholder=${String(meta.listen_port || "")}/><div class="hint">Applied to the node (currently ${meta.listen_port || "—"})</div></div>
    </div>
    <div class="row2">
      <div class="field"><label>MTU</label><input value=${mtu} onInput=${e => setMtu(e.target.value)} placeholder="1280"/><div class="hint">Default for new peers</div></div>
      <div class="field"><label>Persistent keepalive (s)</label><input value=${ka} onInput=${e => setKa(e.target.value)} placeholder="25"/><div class="hint">0 disables · blank = 25</div></div>
    </div>
    <div class="row2">
      <div class="field"><label>DNS</label><input value=${dns} onInput=${e => setDns(e.target.value)} placeholder="1.1.1.1, 1.0.0.1"/><div class="hint">Comma-separated</div></div>
      <div class="field"><label>Outbound (egress) IP / interface</label>
        <select class="selwrap" value=${egress ? egress + "|" + wan : ""} onChange=${e => { const [eip, eifc] = e.target.value.split("|"); setEgress(eip || ""); setWan(eifc || ""); }}>
          <option value="">Auto (MASQUERADE)</option>
          ${egPairs.map(p => html`<option value=${p.ip + "|" + p.iface}>${p.ip} — ${p.iface}${!ipIfaces.some(x => x.ip === p.ip) ? " (not on node now)" : ""}</option>`)}
        </select>
        <div class="hint">Source IP + NIC clients egress from</div></div>
    </div>
    ${isAwg ? html`<div class="field"><label>AmneziaWG parameters</label>
      <div class="hint" style="margin:0 0 8px">Pushed to the node's interface and rendered into configs/QRs. Existing clients must re-import after a change.</div>
      <div class="awg-cols">${[["Jc", "Jmin", "Jmax"], ["S1", "S2", "S3", "S4"], ["H1", "H2", "H3", "H4"], ["I1", "I2", "I3", "I4", "I5"]].map(grp => html`<div class="awg-col">${grp.map(k => html`<label class="awg-f"><span>${k}</span><input value=${awg[k] == null ? "" : awg[k]} onInput=${e => setAwgK(k, e.target.value)}/></label>`)}</div>`)}</div></div>` : null}
    <div class="field ipk-field"><label>Public key</label><span class="grow"></span><span class="ipk-val">${meta.public_key || "—"}</span>${meta.public_key ? html`<button class="copybtn" title="Copy public key" onClick=${() => copy(meta.public_key, "Public key copied")}><${Ic} i="copy"/></button>` : null}</div>
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
  const ifaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || "") })).filter(i => i.port);
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
    // title-only change → save it WITHOUT restarting the proxy (a cosmetic label shouldn't bounce traffic)
    const titleOnly = newListen === (tp.listen || "") && connect === (tp.connect || "") && params.trim() === origParams.trim();
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    if (titleOnly) {
      if (title.trim() === (tp.title || "")) { closeModal(); return toast("No changes.", "ok"); }
      const r = await api.turnTitle({ node, service: svc, title: title.trim() });
      if (!r.ok) return fail(r.error || "Request failed.");
      closeModal(); await Store.poll();
      return toast("Title saved — the proxy keeps running.", "ok");
    }
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
  return html`<${Sheet} title=${turnSheetTitle(turnFork(svc), title)}
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
    </div>
    ${isCustom ? html`<${Fragment}>
      <div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>
      <div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This forwards to a port with no managed interface behind it. Make sure a wg/awg interface is really listening there, or clients reach the proxy but get no tunnel.</span></div>
    <//>` : null}
    <div class="field"><label>Additional ExecStart parameters</label>
      <textarea class="ta mono" rows="4" value=${params} onInput=${e => setParams(e.target.value)} placeholder="-wrap-mode on -wrap-key <64 hex chars>" spellcheck="false"></textarea>
      <div class="hint">Free text appended after <span class="mono">-connect ip:port</span>. Changing the wrap key breaks every client using the old one. <button type="button" class="linkbtn" onClick=${randKey}>Copy a random 64-hex key</button></div>
    </div>
    ${installing ? null : html`<div class="field turn-ver"><label>Installed version</label>
      <div class="turn-ver-row">
        <span class="mono ver">${installed || "unknown"}</span>
        ${verChk && verChk.checking ? html`<span class="faint">checking…</span>`
          : verChk && verChk.err ? html`<span class="tg tg-busy del" title=${verChk.err}><${Ic} i="warn"/>no connection</span>`
          : verChk && verChk.latest ? (updateAvail
              ? html`<button class="btn btn-mini btn-upd" disabled=${dis} onClick=${() => doReinstall("Update")}><${Ic} i="download"/> update to ${verChk.latest}</button>`
              : html`<span class="tg tg-ok"><${Ic} i="check"/> up to date</span>`)
          : html`<button class="btn btn-mini" disabled=${dis || !owner} onClick=${checkUpdate}>Check for update</button>`}
      </div>
    </div>`}
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
const TURN_FORKS = [
  { id: "cacggghp", label: "cacggghp", owner: "cacggghp/vk-turn-proxy", wrap: "" },
  { id: "WINGS-N", label: "WINGS-N", owner: "WINGS-N/vk-turn-proxy", wrap: "-wrap-mode on" },
  { id: "samosvalishe", label: "samosvalishe", owner: "samosvalishe/vk-turn-proxy", wrap: "-wrap" },
  { id: "kiper292", label: "kiper292", owner: "kiper292/vk-turn-proxy", wrap: "" },
  { id: "Moroka8", label: "Moroka8", owner: "Moroka8/vk-turn-proxy", wrap: "-wrap" },
  { id: "anton48", label: "anton48", owner: "anton48/vk-turn-proxy", wrap: "-wrap-srtp" },
];
const TURN_PEND = { install: "installing", manage: "updating", rotate: "rotating", delete: "deleting", onboard: "adopting", restart: "restarting", reinstall: "installing", start: "starting", stop: "stopping" };
// turn-proxy restart completion flash: when a queued 'restart' clears, show a green "restarted" tag 5s
const _turnRestartPend = {};   // "node|service" currently mid-restart (last poll)
const turnRestarted = {};      // "node|service" -> expiry ts for the green flash
const turnUpdating = {};        // "node|service" -> expiry ts; set on an "Update" click so the pending tag reads "updating" (not "installing")
const turnReady = {};          // "node|service" -> expiry ts for the blue "ready" flash (5s after it settles → then no tag)
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
  const [mode, setMode] = useState("new");   // new (install) | existing (adopt)
  const [fork, setFork] = useState(TURN_FORKS[0].id);
  const nrec = (Store.nodes || []).find(n => n.id === node) || {};
  const ips = nrec.ips || [];
  const snap = Store.stats[node] || {};
  const ifaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || "") })).filter(i => i.port);
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
  const [params, setParams] = useState(dflParams(TURN_FORKS[0]));
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const fail = t => { setBusy(false); setMsg({ k: "err", t }); };
  const isCustom = fwd === "__custom__";
  const f = TURN_FORKS.find(x => x.id === fork) || TURN_FORKS[0];
  const lhost = ipPickerVal(lsel, lcustom);
  const pickFork = id => {   // re-default params for the new fork only if the field is still an untouched default
    const cf = TURN_FORKS.find(x => x.id === fork) || TURN_FORKS[0];
    const nf = TURN_FORKS.find(x => x.id === id) || TURN_FORKS[0];
    if (params === dflParams(cf)) setParams(dflParams(nf));
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
    foot=${html`<${Fragment}><span class="grow"></span><button class="btn btn-ghost" onClick=${closeModal}>Cancel</button><button class="btn btn-primary" disabled=${busy} onClick=${save}>${mode === "existing" ? "Adopt" : "Install"}</button></>`}>
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
          <select class="selwrap" value=${fork} onChange=${e => pickFork(e.target.value)}>
            ${TURN_FORKS.map(x => html`<option value=${x.id}>${x.label}${x.wrap ? "" : " · no obfuscation"}</option>`)}
          </select>
          <div class="hint">${f.owner}</div></div>
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
function PeerGrid({ rows, agg, node, iface, shownByPeer, q, blocked }) {
  return html`<div class="tablewrap"><table class="peergrid">
    <thead><tr><th>Status</th>${agg ? html`<th>${node === "*" ? "Server" : "IF"}</th>` : null}<th>User</th><th>Title</th><th>Address</th><th>Last</th><th>Rate ↓↑</th><th>Total ↓↑</th><th></th></tr></thead>
    <tbody>
      ${rows.length ? rows.map(({ p, t }) => {
        const obs = t.observed;
        const u = p.user_id ? Store.user(p.user_id) : null;
        const hidden = p.targets.filter(d => !(shownByPeer[p.id] || new Set()).has(tkey(d.node, d.iface)));   // this peer's deployments not shown in the grid
        return html`<tr key=${p.id + "|" + tkey(t.node, t.iface)} class="clk" onClick=${() => openPeerView(p.id, t.node, t.iface)}>
          <td data-label="Status"><${Badge} s=${t.status || p.status} title=${(t.down ? "interface " + t.iface + " is down — " + t.down : p.reason) || ""}/></td>
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
            <button class="iconbtn" title="Show QR / configs" onClick=${() => openPeerConfigs(p)}><${Ic} i="qr"/></button>
            <button class="iconbtn" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Edit peer"} onClick=${() => openEditPeer(p, { node: t.node, iface: t.iface })}><${Ic} i="pencil"/></button>
            ${p.unassigned
              ? html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Delete peer"} onClick=${() => confirmDeletePeer(p)}><${Ic} i="trash"/></button>`
              : html`<button class="iconbtn danger" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Unassign peer"} onClick=${() => confirmUnassign(p)}><${Ic} i="link"/></button>`}
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
        onInput=${e => { peersView.q = e.target.value.trim(); peersView.page = 1; force(x => x + 1); }}/></div>
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; peersView.page = 1; force(x => x + 1); }}>
        ${multiServer ? html`<option value="*">All servers</option>` : null}
        ${fleet.map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; peersView.page = 1; force(x => x + 1); }}>
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
    <${PeerGrid} rows=${pageRows} agg=${agg} node=${node} iface=${iface} shownByPeer=${shownByPeer} q=${peersView.q}/>
    ${rows.length > 20 ? html`<div class="pager">
      <label class="pager-size">Rows per page
        <select class="selwrap" value=${pageSize} onChange=${e => { peersView.pageSize = +e.target.value; peersView.page = 1; force(x => x + 1); }}>
          ${[20, 30, 50, 100].map(n => html`<option value=${n}>${n}</option>`)}
        </select>
      </label>
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)} of ${rows.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${() => setPage(page - 1)}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${() => setPage(page + 1)}>Next ›</button>
    </div>` : null}

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
      <button class="iconbtn" title="Manage targets — deploy to or remove from interfaces" onClick=${() => openAddTarget(peer)}><${Ic} i="copy"/></button>
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
      <button class="btn btn-mini" onClick=${() => openAddTarget(peer)}>Targets</button>
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
        <div class="row"><span class="k">transfer</span><span class="vv">${obs ? "↓ " + rate(obs.rx_speed) + "  ↑ " + rate(obs.tx_speed) : "—"}</span></div>
        <div class="row"><span class="k">transport</span><span class="vv">${t.via === "turn" ? "via turn-proxy" : (t.via === "direct" ? "direct" : "—")}</span></div>
        ${tps.map(tp => html`<div class="row"><span class="k">turn-proxy</span><span class="vv">${tp.listen || "—"}
          ${tp.wrap_key ? html`<${Fragment}> · key <span class="addr">${String(tp.wrap_key).slice(0, 8)}…</span><button class="copybtn" title="Copy wrap key" onClick=${() => copy(tp.wrap_key, "Wrap key copied")}><${Ic} i="copy"/></button></>` : null}</span></div>`)}
      </div>`}
    </div>
    ${conf ? html`<div class="acts">
      <button class="btn btn-mini" onClick=${() => downloadConf(conf, (peer.name || "peer") + "-" + dnode)}><${Ic} i="download"/> Config</button>
      <button class="btn btn-mini" onClick=${() => copy(conf, "Config copied")}><${Ic} i="copy"/> Copy</button>
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
function htcolor(pct) { return pct >= 90 ? "var(--dangling)" : (pct >= 70 ? "var(--pending)" : "var(--online)"); }   // matches the hm-fill bar tones
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
const LOAD_G = [63, 216, 154], LOAD_O = [242, 163, 60], LOAD_R = [242, 84, 91];
function loadColor(v) {
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
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
  // tight autoscale to the series' own min/max (small vpad) so CPU reads as a jagged "heartbeat"
  const lo = Math.min(...pts), hi = Math.max(...pts), rng = (hi - lo) || 1, vpad = h * 0.06;
  const Y = v => h - vpad - ((v - lo) / rng) * (h - 2 * vpad);
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
  const legend = html`<div class="tp-legend"><span class="tp-k"><i class="sw rx"></i>↓ ${rate(curR)}</span><span class="tp-k"><i class="sw tx"></i>↑ ${rate(curT)}</span><span class="tp-peak">peak ${rate(hi)}</span><span class="grow"></span>${head || null}</div>`;
  h = h || 60; const w = 100;
  // right-anchored to the ring's full capacity, like MiniArea — fills from the right as blocks arrive
  const C = Math.max(cap || n || 1, 2);
  const xAt = i => w - (n - 1 - i) * (w / (C - 1));
  // autoscale to the combined min/max so the curve is spiky/expressive, not a flat baseline
  const lo = n ? Math.min(...R, ...T) : 0, rng = (hi - lo) || 1, vpad = h * 0.12;
  const Y = v => h - vpad - ((v - lo) / rng) * (h - 2 * vpad);
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
        <polyline points=${rxLine} fill="none" stroke="var(--brand)" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
        <polyline points=${line(T)} fill="none" stroke="var(--tp-tx)" stroke-width="1.2" vector-effect="non-scaling-stroke" stroke-dasharray="3 2"/>` : null}
      </svg>
      ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(R[0]) / h * 100) + "%;background:var(--brand)"}></div>
        <div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(T[0]) / h * 100) + "%;background:var(--tp-tx)"}></div>` : null}
      ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xAt(hov)}
        dots=${[{ yp: Y(R[hov] || 0) / h * 100, color: "var(--brand)" }, { yp: Y(T[hov] || 0) / h * 100, color: "var(--tp-tx)" }]}
        label=${histTime(TT[hov], range) + " · ↓ " + rate(R[hov] || 0) + " · ↑ " + rate(T[hov] || 0)}/>` : null}
    </div>
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
  if (kind === "throughput")
    return html`<${ThroughputChart} rx=${s.rx} tx=${s.tx} h=${h} head=${tabs} times=${s.t} range=${range} cap=${cap}/>`;
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
  const l1 = hasCpu ? (h.load[0] || 0) : 0, cpct = Math.min(100, l1 / ((h && h.ncpu) || 1) * 100);
  const removing = n.removing;
  const ndown = st !== "online" && !inProc(n.proc_status);    // genuinely not reporting (recover state) → mirror the detail: disable card actions
  const nblocked = st !== "online" || inProc(n.proc_status);  // down OR mid convert/re-install
  // list-card update tag: a co-located node updates WITH the panel (its "updating" comes from hostUpdating, not
  // its own proc_status) — mirror the detail's dh-ver so the LIST shows "updating" too, while a terminal wins.
  const nUpdating = n.updating || (n.local && (hostUpdating || inProc(Store.hostProc)));
  const procEff = (n.proc_status && !inProc(n.proc_status)) ? n.proc_status : (nUpdating ? "updating" : n.proc_status);
  const nav = () => go("#/node/" + encodeURIComponent(n.id));
  return html`<div class=${"ncard clk" + (removing ? " removing" : "") + (it ? it.cls : "")} onClick=${nav} data-rid=${it ? it.rid : null}>
    <div class="ntop">${reorder ? html`<span class="drag-grip" title="Drag to reorder" onClick=${e => e.stopPropagation()} ...${reorder.grip(n.id)} dangerouslySetInnerHTML=${{ __html: GRIP_SVG }}></span>` : null}
      ${!n.uninstalled && (n.outdated || (n.local && Store.panelOutdated)) && !n.updating ? html`<span class="upd-dot" title="Update available — open the node to update"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v4h-4"/></svg></span>` : null}
      <span class="nname">${n.name}</span>
      ${n.kind ? html`<span class=${"tport " + n.kind}>${n.kind === "docker" ? "docker" : "bare-metal"}</span>` : null}
      ${n.uninstalled ? html`<span class="nstat uninst"><${Ic} i="info"/> uninstalled</span>`
        : st === "online" ? html`<span class="reporting">reporting</span>`
        : st === "offline" ? html`<span class="badge b-unknown ic"><${Ic} i="info"/>offline</span>`
        : html`<span class="nstat enroll"><${Ic} i="clock"/> awaiting enroll</span>`}${procEff ? procTag(procEff, e => { e.stopPropagation(); e.preventDefault(); dismissNodeProc(n.id); }, n.proc_err, st !== "online" && st !== "offline") : null}
      <span style="margin-left:8px"><${HealthDot} issues=${n.issues}/></span>
      ${removing ? html`<span class="badge b-removing ic" style="margin-left:14px"><${Ic} i="trash"/>flagged for removal</span>` : null}
      <span class="grow"></span>
      <span class="nm-item nm-cpuitem"><span class="nm-l">CPU load</span>${hasCpu ? html`<span class="nm-cpu"><span class="hm-bar"><i class=${"hm-fill " + htone(cpct)} style=${"width:" + cpct + "%"}></i></span><span class="nm-v" style=${"color:" + htcolor(cpct)}>${l1.toFixed(2)}</span></span>` : html`<span class="nm-v faint">—</span>`}</span>
    </div>
    <div class="nmeta">
      <span class="nm-item nm-peersitem">${here.length
        ? html`<${OnlinePeersTag} nodeId=${n.id} orphans=${orphCount(n.id, null)} cls="nm-peerpop"
            trigger=${() => html`<span class="nm-l">Peers</span><span class="nm-v nm-peers"><b class=${"oncount" + (onl ? " on" : "")}>${onl}</b><small>/${here.length}</small></span>`}/>`
        : html`<span class="nm-l">Peers</span><span class="nm-v nm-peers faint">none</span>`}</span>
      <div class="nm-rows">
        <div class="nm-row">
          <span class="nm-l">Interfaces</span>
          <span class="tags">${ifTags.length ? ifTags : html`<span class="nm-v faint">—</span>`}</span>
          <span class="nm-thru"><span class="nm-l">Throughput</span>${st === "online"
            ? html`<span class="nm-v thru"><span class="down">↓ ${rate(n.rx_speed)}</span><span class="up">↑ ${rate(n.tx_speed)}</span></span>`
            : html`<span class="nm-v faint">—</span>`}</span>
        </div>
        <div class="nm-row">
          <span class="nm-l">Turn-proxies</span>
          <span class="tags">${tps.length ? tps.map(turnChip) : html`<span class="nm-v faint">—</span>`}</span>
          <div class="nacts" onClick=${e => e.stopPropagation()}>
            <button class="iconbtn" disabled=${nblocked} title=${nblocked ? "Unavailable while the node is down / converting" : "Edit node"} onClick=${() => openNodeEdit(n)}><${Ic} i="pencil"/></button>
            ${ndown ? null : html`<button class="iconbtn" title="Rotate token" onClick=${() => openNodeRotate(n)}><${Ic} i="key"/></button>`}
            <button class="iconbtn danger" title=${removing ? "Force remove" : "Remove node"} onClick=${() => openNodeRemove(n)}><${Ic} i="trash"/></button>
          </div>
        </div>
      </div>
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
    let keys, pskV, tgts, configs, body;
    try {                                            // browser-side crypto/config build is the only awaited part
      keys = await genKeys();
      pskV = psk.trim() || genPSK();
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
          <span><span class="k">Server</span> <span style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span></span>
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
      body: "A new keypair is generated (the PSK is kept). The current config stops working — you'll need to send out the fresh QR / config to re-import. Useful if a config may have leaked.",
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
  const [modalStack, setModalStack] = useState([]);
  useEffect(() => { _setStack = setModalStack; }, []);
  useEffect(() => {
    const onHash = () => { setHash(location.hash || "#/"); _applyStack([]); window.scrollTo(0, 0); };
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
    const acct = $("#acct-btn"); if (acct) acct.onclick = openAccount;
    const out = $("#logout-btn"); if (out) out.onclick = doLogout;
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
