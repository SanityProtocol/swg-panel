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
import { useState, useEffect, useRef, useMemo, useCallback } from "preact/hooks";
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
// wg vs awg for an interface. A single peer/key can't span both protocols, so the target pickers hide the other
// kind once one is chosen (enforced wherever peers get interfaces — peers module, users module, …).
const iTypeOf = (node, iface) => { const m = (Store.describe[node] || {})[iface] || {}; return (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg"; };
// wg/awg for a peer TARGET — from the LIVE interface (authoritative), falling back to the stored target.type only
// when the node isn't reporting the interface. Use this everywhere a target's protocol tag/colour is shown so a
// stale target.type can never mislabel/miscolour a row (peers · users · live · interface grids all share this).
const targetType = t => { const m = t && (Store.describe[t.node] || {})[t.iface]; return m ? ((m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg") : (((t && t.type) || "wg").toLowerCase() === "awg" ? "awg" : "wg"); };
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
    <${Dropdown} value=${sel} onChange=${v => setSel(v)} options=${[
      ...(ips || []).filter(ip => !isPrivIp(ip)).map(ip => ({ value: ip, label: ip })),
      { value: "__custom__", label: "Custom IP / Host…" }]}/>
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
// Nice y-axis ceiling for a throughput graph: the smallest "1/5/10/50/100/500 × {B,K,M,G}" value ≥ bps.
// Base-1024 to match rate(), so the scale badge reads e.g. "50 K/s" / "500 K/s" / "1 M/s"; past 500 it rolls to
// the next unit (…500 K → 1 M, never an ugly "1000 K"). Callers pass peak/0.85 to guarantee ≥15% headroom.
function niceScaleCeil(bps) {
  const LADDER = [1, 5, 10, 50, 100, 500];
  let unit = 1;
  while (bps >= 1024 * unit) unit *= 1024;
  const m = bps / unit;
  for (const L of LADDER) if (m <= L) return L * unit;
  return 1024 * unit;
}

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
  compass: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15.8 8.2l-2 5.6-5.6 2 2-5.6z"/></svg>',
  eye: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
  activity: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  users: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1"/><circle cx="9" cy="7" r="3.4"/><path d="M22 19v-1a4 4 0 0 0-3-3.85M16 3.2a4 4 0 0 1 0 7.6"/></svg>',
  user: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M19 20v-1a5 5 0 0 0-5-5h-4a5 5 0 0 0-5 5v1"/><circle cx="12" cy="7" r="4"/></svg>',
  device: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="3" width="10" height="18" rx="2.4"/><path d="M11 18h2"/></svg>',
  cpu: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="7" width="10" height="10" rx="1.6"/><path d="M9 1.5v3M15 1.5v3M9 19.5v3M15 19.5v3M1.5 9h3M1.5 15h3M19.5 9h3M19.5 15h3"/></svg>',
  disk: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5.2 13 7.5 5h9l2.3 8M7 16.5h.01"/></svg>',
  database: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  clock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5l3.2 2"/></svg>',
  "cal-day": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><rect x="10.2" y="12.4" width="3.6" height="3.6" rx="0.7" fill="currentColor" stroke="none"/></svg>',
  "cal-week": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M6.3 14h11.4" stroke-width="2.7"/></svg>',
  cal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M7.5 13h.01M12 13h.01M16.5 13h.01M7.5 16.6h.01M12 16.6h.01M16.5 16.6h.01" stroke-width="2.3"/></svg>',
  donut: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.4"/></svg>',
  flow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="18" cy="18" r="2.6"/><path d="M8.3 10.9 15.7 7.1M8.3 13.1 15.7 16.9"/></svg>',
  bars: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 20V12M12 20V4M19 20V15"/></svg>',
  exclaim: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.3v5.4"/><path d="M12 16.3v.01" stroke-width="2.4"/></svg>',
  excl: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M12 3.5v11"/><path d="M12 20v.01" stroke-width="3.4"/></svg>',
  hour2: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 12 9.7 8.1"/><path d="M12 12 17 12"/></svg>',
  sun: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.3M12 19.2v2.3M2.5 12h2.3M19.2 12h2.3M5.1 5.1l1.7 1.7M17.2 17.2l1.7 1.7M18.9 5.1l-1.7 1.7M6.8 17.2l-1.7 1.7"/></svg>',
  weekcal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><rect x="6.2" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/><rect x="10.4" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/><rect x="14.6" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/></svg>',
  monthcal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><g fill="currentColor" stroke="none"><rect x="6.3" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="10.65" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="15" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="6.3" y="15.4" width="2.7" height="2.7" rx="0.5"/><rect x="10.65" y="15.4" width="2.7" height="2.7" rx="0.5"/><rect x="15" y="15.4" width="2.7" height="2.7" rx="0.5"/></g></svg>',
  daycal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><rect x="9.9" y="12.2" width="4.2" height="4.2" rx="0.8" fill="currentColor" stroke="none"/></svg>',
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

// ── subscription vault crypto — all client-side (AES-GCM + PBKDF2 via WebCrypto). The panel only ever
//    receives wrapped/ciphertext blobs it can't read. See swg-panel-server's subscriptions helper block. ──
const SUB_CHECK = "swg-sub-v1";   // known plaintext → lets the browser verify it unwrapped the vault correctly
async function subWrapKey(password, saltBytes) {   // password → AES key, via PBKDF2 (never leaves the browser)
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: saltBytes, iterations: 200000, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function subEnc(key, bytes) {   // → base64( iv(12) ‖ ciphertext )
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, bytes));
  const out = new Uint8Array(12 + ct.length); out.set(iv); out.set(ct, 12); return b64(out);
}
async function subDec(key, b64s) {    // base64(iv‖ct) → bytes; throws on wrong key / tamper (GCM auth)
  const all = _b64ToBytes(b64s); return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, key, all.slice(12)));
}
// First-time setup: mint the Subscription Key, wrap it with the password (convenience cache), store the
// wrapped form + a verifier. Returns the SK (base64) to SHOW ONCE — it is never sent to the server in the clear.
async function subVaultCreate(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const wk = await subWrapKey(password, salt);
  const sk = crypto.getRandomValues(new Uint8Array(32));
  const skKey = await _importAes(sk, ["encrypt", "decrypt"]);
  const r = await api.subVaultSet({ salt: b64(salt), sk_by_pw: await subEnc(wk, sk),
    sk_check: await subEnc(wk, new TextEncoder().encode(SUB_CHECK)),
    // SK self-verifier (encrypted UNDER the SK) so a cached SK can be validated against THIS vault on boot —
    // a stale cache left over from a previous (reset) vault is then detected + discarded, never trusted.
    sk_verify: await subEnc(skKey, new TextEncoder().encode(SUB_CHECK)) });
  if (!r || r.ok === false) throw new Error((r && r.error) || "couldn't save the vault");
  _subSK = skKey;                                          // unlock immediately with the NEW SK (replaces any stale cache)
  try { sessionStorage.setItem(_SK_CACHE, b64(sk)); } catch (_) {}
  return b64(sk);
}

// ── Subscription Key session cache + the token/URL/blob operations that ride on it ──
// The Subscription Key (SK) is unwrapped from the vault ONCE per session with the login password
// (the "convenience cache") and held only in memory as an AES-GCM key — never persisted, never sent
// to the server. Every per-user secret (the unlock-key, the URL token, each peer's config) is wrapped
// with it in the browser; the panel only ever stores ciphertext it can't read.
const b64url = u => b64(u).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
async function sha256hex(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const _importAes = (bytes, uses) => crypto.subtle.importKey("raw", bytes, { name: "AES-GCM" }, false, uses);

let _subSK = null;                       // the unwrapped encryption key (CryptoKey), cached for this session
const _SK_CACHE = "swg_ck";              // key-cache: sessionStorage always (tab-scoped); ALSO localStorage when the
const _SK_PERSIST = "swg_ck_keep";       // operator opts into "keep this device unlocked" (survives a browser restart).
function subSKCached() { return _subSK; }
// Is device-persist opted in on THIS device? When on, the raw key also lives in localStorage so a cookie-only
// login (browser restart, no password typed) can restore it — the same convenience the auth cookie already gives,
// still 100% client-side (the server never receives the key; localStorage, unlike a cookie, is never transmitted).
function subPersistOn() { try { return localStorage.getItem(_SK_PERSIST) === "1"; } catch (_) { return false; } }
function subSetPersist(on) {
  try {
    if (on) { localStorage.setItem(_SK_PERSIST, "1"); const b = sessionStorage.getItem(_SK_CACHE); if (b) localStorage.setItem(_SK_CACHE, b); }
    else { localStorage.removeItem(_SK_PERSIST); localStorage.removeItem(_SK_CACHE); }
  } catch (_) {}
}
function subForget() { _subSK = null; try { sessionStorage.removeItem(_SK_CACHE); localStorage.removeItem(_SK_CACHE); } catch (_) {} }   // drop the key from memory + both stores (logout / password change / lock)
// Operator-initiated lock (header padlock): drop the cached key so subscription-affecting actions prompt for it
// again — for re-locking on a shared machine, and to exercise the unlock prompt. Also turns OFF device-persist (an
// explicit lock means "stop keeping this device unlocked"), clears the heal skip-set so a later unlock re-checks
// every user, and bumps configEpoch so open QR views fall back to the unlock bar.
function lockVault() {
  subForget();
  try { localStorage.removeItem(_SK_PERSIST); } catch (_) {}
  try { for (const k in _healTried) delete _healTried[k]; } catch (_) {}
  Store.configEpoch++; bus.emit();
  try { toast("Encryption key locked on this device.", "ok"); } catch (_) {}
}
// Restore the session convenience cache after a reload (login reloads the page). Raw key bytes live in
// sessionStorage — tab-scoped, cleared on logout, never sent to the server; the deliberate convenience-cache
// tradeoff so a normal login auto-unlocks config encryption without re-typing the password.
async function subBootRestore() {
  if (_subSK) return;
  // localStorage first (device-persist survives a browser restart / cookie-only login), then sessionStorage (tab).
  let s = null; try { s = localStorage.getItem(_SK_CACHE) || sessionStorage.getItem(_SK_CACHE); } catch (_) {}
  if (!s) return;
  try { sessionStorage.setItem(_SK_CACHE, s); } catch (_) {}   // mirror into the tab cache so the rest of the code path is unchanged
  try {
    const key = await _importAes(_b64ToBytes(s), ["encrypt", "decrypt"]);
    const v = await api.subVault();
    if (!v || !v.ok || !v.data || !v.data.exists) { subForget(); return; }   // vault gone (reset) → the cache is stale
    if (v.data.sk_verify) {                                                    // validate the cache matches THIS vault's SK
      let ok = false;
      try { ok = new TextDecoder().decode(await subDec(key, v.data.sk_verify)) === SUB_CHECK; } catch (_) {}
      if (!ok) { subForget(); return; }                                       // stale SK (a different/reset vault) → discard, never trust
    }
    _subSK = key;
  } catch (_) { subForget(); }
}
async function subUnlock(password) {      // unwrap the SK from the vault with the password → cache it
  const v = await api.subVault();
  if (!v || v.ok === false || !v.data || !v.data.exists) throw new Error("Config encryption isn't set up yet.");
  const wk = await subWrapKey(password, _b64ToBytes(v.data.salt));
  let skBytes;
  try {
    if (new TextDecoder().decode(await subDec(wk, v.data.sk_check)) !== SUB_CHECK) throw new Error("bad");
    skBytes = await subDec(wk, v.data.sk_by_pw);        // GCM auth fails here on a wrong password
  } catch (_) { throw new Error("That password didn't unlock the encryption key."); }
  _subSK = await _importAes(skBytes, ["encrypt", "decrypt"]);
  try { sessionStorage.setItem(_SK_CACHE, b64(skBytes)); if (subPersistOn()) localStorage.setItem(_SK_CACHE, b64(skBytes)); } catch (_) {}   // tab cache; also localStorage when device-persist is opted in
  // self-heal: give an older vault (pre-sk_verify) an SK self-verifier so a cached SK can be validated on boot.
  if (!v.data.sk_verify) {
    try { await api.subVaultSet({ salt: v.data.salt, sk_by_pw: v.data.sk_by_pw, sk_check: v.data.sk_check,
      sk_verify: await subEnc(_subSK, new TextEncoder().encode(SUB_CHECK)) }); } catch (_) {}
  }
  try { subFlushPending(); } catch (_) {}   // save anything the operator skipped earlier this session (incl. overwriting a stale rotate blob)
  try { subAutoHeal(); } catch (_) {}   // key just became available → silently publish anything left unpublished while locked
  return _subSK;
}
// Re-wrap the vault under a NEW panel password so the convenience cache keeps auto-unlocking after a password
// change (the SK itself is unchanged — every blob stays valid). Uses the raw SK from the session cache; returns
// false if it isn't cached (then the operator unlocks with the old password or the shown-once key). Best-effort.
async function subRewrap(newPassword) {
  let skB64 = null; try { skB64 = sessionStorage.getItem(_SK_CACHE); } catch (_) {}
  if (!skB64 || !newPassword) return false;
  try {
    const skBytes = _b64ToBytes(skB64);
    const v = await api.subVault(); if (!v || !v.ok || !v.data || !v.data.exists) return false;
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const wk = await subWrapKey(newPassword, salt);
    const r = await api.subVaultSet({ salt: b64(salt), sk_by_pw: await subEnc(wk, skBytes),
      sk_check: await subEnc(wk, new TextEncoder().encode(SUB_CHECK)) });
    return !!(r && r.ok !== false);
  } catch (_) { return false; }
}

// Enable a user's subscription: mint a fresh 256-bit URL token, and REUSE the user's existing unlock-key if
// they already hold one (their encrypted-config blobs are encrypted under it — minting a fresh key would orphan
// them); only mint a fresh unlock-key for a brand-new escrow. Returns {token, unlockKeyB64} for the URL. SK unlocked.
async function subEnableUser(uid) {
  const sk = subSKCached(); if (!sk) throw new Error("Unlock the encryption key first.");
  const token = b64url(crypto.getRandomValues(new Uint8Array(32)));   // the URL path segment (opaque, 256-bit)
  const rec = (await subUsersMap(true))[uid];
  let unlockBytes, unlock_by_sk;
  if (rec && rec.unlock_by_sk) { unlockBytes = await subDec(sk, rec.unlock_by_sk); unlock_by_sk = rec.unlock_by_sk; }
  else { unlockBytes = crypto.getRandomValues(new Uint8Array(32)); unlock_by_sk = await subEnc(sk, unlockBytes); }
  const r = await api.subUserEnable({
    user_id: uid, token_sha: await sha256hex(token),
    unlock_by_sk,
    token_by_sk: await subEnc(sk, new TextEncoder().encode(token)),
  });
  if (!r || r.ok === false) throw new Error((r && r.error) || "couldn't enable the subscription");
  return { token, unlockKeyB64: b64url(unlockBytes) };
}

// Rotate a user's URL (kill the old link): fresh token, SAME unlock-key, so existing ciphertext stays valid.
async function subRotateUser(uid) {
  const sk = subSKCached(); if (!sk) throw new Error("Unlock the Subscription Key first.");
  const tokenBytes = crypto.getRandomValues(new Uint8Array(32));
  const token = b64url(tokenBytes);
  const r = await api.subUserRotate({
    user_id: uid, token_sha: await sha256hex(token),
    token_by_sk: await subEnc(sk, new TextEncoder().encode(token)),
  });
  if (!r || r.ok === false) throw new Error((r && r.error) || "couldn't rotate the URL");
  return { token };
}

// Recover ONLY the unlock-key (CryptoKey, encrypt+decrypt) from a user's escrow — works for a plain
// encrypted-config user (no subscription token) as well as a subscribed one. Used to encrypt/decrypt blobs.
async function subRecoverUnlock(escRec) {
  const sk = subSKCached(); if (!sk) throw new Error("Unlock the encryption key first.");
  if (!escRec || !escRec.unlock_by_sk) throw new Error("no encryption key for this user");
  return _importAes(await subDec(sk, escRec.unlock_by_sk), ["encrypt", "decrypt"]);
}

// Recover a user's {token, unlockKey(CryptoKey), unlockKeyB64} from their escrow record via the SK.
async function subRecover(escRec) {
  const sk = subSKCached(); if (!sk) throw new Error("Unlock the Subscription Key first.");
  if (!escRec || !escRec.unlock_by_sk || !escRec.token_by_sk) throw new Error("no subscription for this user");
  const unlockBytes = await subDec(sk, escRec.unlock_by_sk);
  const token = new TextDecoder().decode(await subDec(sk, escRec.token_by_sk));
  // encrypt (publish a peer's secret) AND decrypt (Show-QR reads the peer's blob back) — same key material.
  return { token, unlockKey: await _importAes(unlockBytes, ["encrypt", "decrypt"]), unlockKeyB64: b64url(unlockBytes) };
}

// The shareable URL base for a user. Canonical source is Access & TLS (access.sub.url); falls back to the
// legacy subscriptions.base_url. Blank → null (operator must set it in Access & TLS). When the public URL
// carries no explicit port, we append the sub's listen port so a directly-reached sub — or one behind
// Cloudflare on an alt HTTPS port like 8443 — links to the right place. 443/80 are scheme defaults → left
// implicit; a reverse proxy that remaps the port overrides this by putting an explicit port in the URL.
// Public URLs (panel / sub) are often typed without a scheme — store them WITH https:// so every link builds
// correctly (and the port logic in subBaseUrl can parse them).
function normPublicUrl(s) { s = (s || "").trim().replace(/\/+$/, ""); return s && !/^https?:\/\//i.test(s) ? "https://" + s : s; }
function subBaseUrl() {
  const ps = Store.panelSettings || {};
  const sub = (ps.access || {}).sub || {};
  let raw = String(sub.url || (ps.subscriptions || {}).base_url || "").trim().replace(/\/+$/, "");
  if (!raw) return "";
  // Re-derive host:port LIVE from the settings every time (only the token is stored), so a port/host change
  // flows into every link. The public URL is often typed WITHOUT a scheme ("sub.example.net") — default it,
  // otherwise new URL() throws and the configured listen port silently never gets appended.
  if (!/^https?:\/\//i.test(raw)) raw = "https://" + raw;
  try {
    const u = new URL(raw);
    const lp = parseInt(sub.port, 10);
    // append the configured listen port unless the URL already carries one, or it's the scheme default
    if (!u.port && lp && !((u.protocol === "https:" && lp === 443) || (u.protocol === "http:" && lp === 80))) u.port = String(lp);
    return (u.origin + u.pathname).replace(/\/+$/, "");
  } catch (_) { return raw.replace(/\/+$/, ""); }
}
const SUB_LANG_LIST = [["en", "English"], ["ru", "Русский"]];   // languages the swgSub page ships (must match swg-panel-server SUB_LANGS)
async function subUrlFor(escRec) {
  const base = subBaseUrl(); if (!base) return null;
  const { token, unlockKeyB64 } = await subRecover(escRec);
  return base + "/" + token + "#" + unlockKeyB64;
}

// Encrypt one peer's secret (private key + PSK) under the user's unlock-key and store the ciphertext.
// This is the ONLY way a peer's key reaches the subscription page — encrypted here, decrypted only by
// whoever holds the URL fragment. Best-effort: callers must not let a failure here break peer creation.
async function subEncryptPeer(uid, pid, privkey, psk, unlockKey) {
  const sec = await subEnc(unlockKey, new TextEncoder().encode(JSON.stringify({ k: privkey, p: psk || "" })));
  const r = await api.subBlob({ user_id: uid, peer_id: pid, sec });
  if (!r || r.ok === false) throw new Error((r && r.error) || "couldn't store the subscription config");
}

// Is the subscriptions feature switched on for this panel?
function subFeatureOn() { return !!(((Store.panelSettings || {}).subscriptions || {}).enabled); }
// The per-user subscription records (enabled + the SK-wrapped escrow), briefly cached.
let _subUsersCache = { at: 0, map: null };
async function subUsersMap(force) {
  if (!force && _subUsersCache.map && Date.now() - _subUsersCache.at < 4000) return _subUsersCache.map;
  try { const r = await api.subUsers(); _subUsersCache = { at: Date.now(), map: (r && r.ok && r.data && r.data.users) || {} }; }
  catch (_) { _subUsersCache = { at: Date.now(), map: {} }; }
  return _subUsersCache.map;
}
function subUsersForget() { _subUsersCache = { at: 0, map: null }; }
// Get a user's encryption unlock-key, minting an escrow entry (unlock-key wrapped by the SK) the first time
// they own an encrypted-stored peer. Idempotent: an existing key is returned as-is (every blob is encrypted
// under it), and the server returns the authoritative one so a race can't fork keys. null if the vault is locked.
async function ensureUserUnlockKey(uid) {
  const sk = subSKCached(); if (!sk || !uid) return null;
  const rec = (await subUsersMap(true))[uid];
  if (rec && rec.unlock_by_sk) { try { return await subRecoverUnlock(rec); } catch (_) { return null; } }
  const unlockKeyBytes = crypto.getRandomValues(new Uint8Array(32));
  const r = await api.subEscrow({ user_id: uid, unlock_by_sk: await subEnc(sk, unlockKeyBytes) });
  if (!r || r.ok === false || !r.data || !r.data.unlock_by_sk) return null;
  subUsersForget();
  try { return await subRecoverUnlock(r.data); } catch (_) { return null; }
}
// Publish a peer's freshly-minted secret to the encrypted config store — the ONLY moment the browser holds the
// private key (create / rekey / reassign). In encrypted mode this IS the config store (and doubles as the
// subscription blob when the user is subscribed). Best-effort and silent: skips in "off" mode or while the
// vault is locked (then the peer publishes on a later rekey, or via the migration/encrypt-all pass). NEVER
// breaks peer creation.
// Reserved bucket for UNASSIGNED peers (mirrors SUB_ORPHAN on the server): their config is encrypted under a
// dedicated SK-escrowed key so it survives a reload just like an assigned peer's, and is re-keyed into the
// user's bucket on assignment.
const SUB_ORPHAN = "_orphan";
async function subMaybePublish(userId, peerId, privkey, psk) {
  try {
    if (Store.storeMode !== "encrypted" || !peerId || !subSKCached()) return;
    const uid = userId || SUB_ORPHAN;                      // unassigned → the orphan bucket
    const unlockKey = await ensureUserUnlockKey(uid);
    if (!unlockKey) return;
    await subEncryptPeer(uid, peerId, privkey, psk, unlockKey);
  } catch (_) { /* an encryption hiccup must never break the peer flow */ }
}
// Peers whose publish was SKIPPED while the vault was locked — peer_id → {userId, privkey, psk}. The private key
// lives ONLY in this tab (never on the server), so this is the one chance to still save it: unlocking the vault
// later in the SAME session flushes these into the vault, OVERWRITING any stale blob (the rotate case: the peer
// already has a blob with its OLD key, which a count-based heal can't spot). Cleared on reload, like every
// in-session key copy — after that the config is unrecoverable and the peer must be rekeyed.
const _pendingPublish = new Map();
async function subFlushPending() {
  if (Store.storeMode !== "encrypted" || !subSKCached() || !_pendingPublish.size) return;
  let n = 0;
  for (const [peerId, p] of [..._pendingPublish]) {
    try { await subMaybePublish(p.userId, peerId, p.privkey, p.psk); _pendingPublish.delete(peerId); n++; } catch (_) {}
  }
  if (n) bus.emit();
}
// Ensure the encryption vault is unlocked before an action that needs it. Resolves true when the key is
// available (already unlocked, or the operator just unlocked it) or not needed (store mode isn't encrypted);
// false when the operator chose to skip. Shows a modal (VaultPromptSheet) explaining the action + the cost of
// skipping. Never throws.
let _vaultPromptPending = null;   // the in-flight unlock promise while the modal is open — coalesces concurrent asks
function ensureVaultUnlocked(opts) {
  if (Store.storeMode !== "encrypted") return Promise.resolve(true);   // nothing is stored encrypted → no key needed
  if (subSKCached()) return Promise.resolve(true);                     // already unlocked this session
  if (_vaultPromptPending) return _vaultPromptPending;                 // a modal is already up → share it (one prompt for a burst of actions)
  _vaultPromptPending = new Promise(function (resolve) {
    pushModal(html`<${VaultPromptSheet} opts=${opts || {}} onDone=${v => { _vaultPromptPending = null; resolve(v); }}/>`);
  });
  return _vaultPromptPending;
}
// subMaybePublish, but if the vault is locked it PROMPTS the operator (instead of silently skipping) so they can
// unlock + publish or knowingly skip. Use for user-triggered actions (create / rekey / reassign a peer).
async function subPublishOrPrompt(userId, peerId, privkey, psk) {
  if (Store.storeMode !== "encrypted" || !peerId) return;   // userId may be null → published to the orphan bucket
  if (!subSKCached()) {
    const ok = await ensureVaultUnlocked({
      title: "Unlock to publish this config",
      reason: "This peer's config is stored encrypted — only you can read it, with your encryption key. Unlock the key to publish this peer now, so its QR appears on the user's subscription page and stays re-viewable in the panel later.",
      consequence: "the peer is created and works right away, but its config isn't published — its QR won't appear on the subscription page. You can still save it by unlocking the key in this browser tab before you reload; after a reload the key is gone from the browser (it was never on the server) and you'd have to rekey the peer to re-issue it.",
    });
    if (!ok) { _pendingPublish.set(peerId, { userId, privkey, psk }); return; }   // skipped → remember, so a later in-session unlock still saves it (incl. overwriting a stale rotate blob)
  }
  await subMaybePublish(userId, peerId, privkey, psk);
  _pendingPublish.delete(peerId);   // published → no longer pending
}
// A subscription-affecting action that DOESN'T hand us a fresh private key (e.g. assigning an EXISTING peer to a
// user, which keeps its key) can still leave that user with an unpublished peer → an empty "Not ready yet" QR on
// their subscription page. Publish the user's recoverable-but-unpublished peers, PROMPTING for the key first if
// the vault is locked (Skip leaves them unpublished, as the modal warns). Only acts for a subscribed user with a
// real gap, so it never prompts pointlessly. Best-effort; never throws.
async function subReconcileUser(userId) {
  if (Store.storeMode !== "encrypted" || !userId) return;
  let rec; try { rec = (await subUsersMap(true))[userId]; } catch (_) { return; }
  if (!rec || !rec.enabled) return;                              // not subscribed → no client QR to keep populated
  if ((rec.peers || 0) <= (rec.provisioned || 0)) return;        // already fully published → nothing to do
  if (!subSKCached()) {
    const ok = await ensureVaultUnlocked({
      title: "Unlock to update this subscription",
      reason: "This user is subscribed, and this change left a peer whose config isn't published yet. Unlock your encryption key to publish it now, so the peer's QR appears on their subscription page.",
      consequence: "the peer works right away, but it shows “Not ready yet” (an empty QR) on the user's subscription page. Unlock the key in this browser tab before you reload and it publishes automatically; after a reload you'd have to rekey the peer to re-issue it.",
    });
    if (!ok || !subSKCached()) return;                           // operator skipped
  }
  try { const k = await ensureUserUnlockKey(userId); if (k) { await subBackfillUser(userId, k); bus.emit(); } } catch (_) {}
}
// Peers whose encrypted blob we've already ensured this session (so viewing a multi-deployment peer's QRs
// doesn't re-encrypt the same blob repeatedly).
const _blobEnsured = new Set();
// Viewing a peer's QR/config with the vault unlocked PUBLISHES its blob if it's missing — this is the real
// "open the peer once to publish it" path for a peer created while the vault was locked (its config lives in
// this session or the plaintext store, but no blob was written). Idempotent + best-effort; never throws.
async function ensurePeerBlob(peer, conf) {
  if (Store.storeMode !== "encrypted" || !subSKCached() || !peer || !peer.id || !conf) return;   // user_id optional (orphan bucket)
  if (_blobEnsured.has(peer.id)) return;
  _blobEnsured.add(peer.id);
  try {
    const g = await api.subBlobGet(peer.id);
    if (g && g.ok && g.data && g.data.sec) return;             // already published — nothing to do
    const parsed = parseFullConf(conf);
    if (parsed && parsed.privkey) await subMaybePublish(peer.user_id, peer.id, parsed.privkey, parsed.psk);
  } catch (_) { _blobEnsured.delete(peer.id); }                // let a later open retry
}

// Publish every EXISTING peer of a user to their (just-enabled) subscription — subMaybePublish only fires
// at peer creation, so without this a user's current peers would never reach the sub page. One blob per
// peer (the private key is shared across a peer's deployments). A peer whose config isn't available
// (store_configs off, or a pre-existing/imported peer with no stored key) can't be published — counted in
// `missing` so the caller can warn instead of leaving a silently-empty page. Best-effort per peer.
async function subBackfillUser(uid, unlockKey) {
  const peers = Store.peersOfUser(uid);
  let published = 0, missing = 0; const missingPeers = [];
  for (const p of peers) {
    let conf = anySessionConf(p.pubkey);                          // just-created config still in this session
    // the private key is the same on every deployment, so any target that has a stored config will do —
    // try them all rather than give up if only the first is missing/unreadable (legacy plaintext or session)
    if (!conf) {
      for (const t of (p.targets || [])) {
        try { const r = await api.config(p.pubkey, t.node, t.iface); if (r && r.ok && r.data && r.data.config) { conf = r.data.config; break; } } catch (_) {}
      }
    }
    const parsed = conf ? parseFullConf(conf) : null;
    if (!parsed || !parsed.privkey) {
      // no readable plaintext config — but an encrypted blob may already cover it (idempotent resume), or it may
      // still sit in the ORPHAN bucket from when this peer was unassigned → re-key that into the user's bucket.
      try {
        const g = await api.subBlobGet(p.id);
        if (g && g.ok && g.data && g.data.sec) {
          if (g.data.user_id === uid) { published++; continue; }          // already in this user's bucket
          const srcRec = (await subUsersMap())[g.data.user_id];           // the bucket it's in now (e.g. orphan)
          if (srcRec && srcRec.unlock_by_sk) {
            const srcKey = await subRecoverUnlock(srcRec);
            const secret = JSON.parse(new TextDecoder().decode(await subDec(srcKey, g.data.sec)));
            if (secret && secret.k) { await subEncryptPeer(uid, p.id, secret.k, secret.p, unlockKey); published++; continue; }
          }
        }
      } catch (_) {}
      missing++; missingPeers.push(p.id); continue;                 // no key available → can't encrypt / flag for rekey
    }
    try {
      await subEncryptPeer(uid, p.id, parsed.privkey, parsed.psk, unlockKey);
      await captureOverridesFrom(p, parsed);                       // move the config's non-secret DNS/MTU/AllowedIPs into the roster
      published++;
    } catch (_) { missing++; missingPeers.push(p.id); }
  }
  return { published, missing, total: peers.length, missingPeers };
}

// Silent safety net: publish every subscription-enabled user whose LIVE peers outnumber their provisioned
// blobs — i.e. peers created/assigned while the vault was locked (possibly in another admin session), which
// would otherwise show "Not ready yet" on the subscription page. Runs only with the key already available
// (no prompt — the per-action subPublishOrPrompt owns the "ask for the password" flow); best-effort, never
// throws. Guarded against re-entrancy so overlapping polls/unlocks don't double-run. Idempotent.
let _autoHealRunning = false;
const _healTried = {};   // uid → the exact blob deficit we last attempted with the key available. Peers whose key
                         // can't be recovered (no session/plaintext config, no blob — they need a rekey) can't be
                         // published, so re-probing them every heal is wasted work + console 404 noise at fleet
                         // scale. Attempt a given gap once; retry only when the deficit changes (a peer added, or
                         // one got published elsewhere). Cleared for a user the moment they're fully covered.
async function subAutoHeal() {
  if (Store.storeMode !== "encrypted" || !subSKCached() || _autoHealRunning) return;
  _autoHealRunning = true;
  try {
    let st; try { st = await api.subUsers(); } catch (_) { return; }
    const users = (st && st.data && st.data.users) || {};
    let healed = 0;
    for (const uid of Object.keys(users)) {
      const u = users[uid] || {};
      if (!u.enabled) { delete _healTried[uid]; continue; }        // only a live subscription renders "Not ready yet"
      const deficit = (u.peers || 0) - (u.provisioned || 0);
      if (deficit <= 0) { delete _healTried[uid]; continue; }       // every live peer already has a blob → nothing to do
      if (_healTried[uid] === deficit) continue;                    // this exact gap was already attempted → don't re-probe
      _healTried[uid] = deficit;
      try {
        const k = await ensureUserUnlockKey(uid);
        if (k) { const r = await subBackfillUser(uid, k); healed += (r.published || 0); if (r.published) delete _healTried[uid]; }
        else delete _healTried[uid];                                // couldn't get the key → let a later pass retry
      } catch (_) { delete _healTried[uid]; }
    }
    if (healed) bus.emit();   // refresh any open sub / QR views now that blobs exist
  } finally { _autoHealRunning = false; }
}

// Migrating a plaintext config → blob keeps ONLY {k,p}; its non-secret DNS/MTU/AllowedIPs/keepalive would be
// lost, so capture them into the roster (once — never clobber an existing override). Sparse vs the interface default.
async function captureOverridesFrom(peer, parsed) {
  if (peer.overrides && Object.keys(peer.overrides).length) return;   // already has roster overrides
  const t0 = (peer.targets || [])[0]; if (!t0) return;
  const ov = configOverrides({ dns: (parsed.dns || []).join(", "), mtu: parsed.mtu, allowed: parsed.allowed, keepalive: parsed.keepalive },
                             Store.ifaceMeta(t0.node, t0.iface));
  if (Object.keys(ov).length) { try { await api.peerUpdate({ peer_id: peer.id, overrides: ov }); } catch (_) {} }
}

// The one-time migration pass. Touches ONLY the peers the server says still hold plaintext (O(plaintext), so a
// 1000-peer fleet isn't a full-fleet probe): encrypt each ASSIGNED one's config into its blob, capture non-secret
// overrides, then purge plaintext ONLY where a blob now exists (server re-checks) + clean orphan .conf files
// (dead keys, no live peer). Resumable — re-running does only the stragglers. `flagged` = peers that couldn't be
// encrypted (unassigned, or no stored/importable key) → the rekey affordance. Requires the vault unlocked.
async function runConfigMigration() {
  if (!subSKCached()) throw new Error("Unlock the encryption key first.");
  let list = [];
  try { const pp = await api.plaintextPeers(); list = (pp && pp.data && pp.data.peers) || []; } catch (_) {}
  let migrated = 0; const flagged = [];
  // group the assigned plaintext-holders by user (one unlock-key each); unassigned can't be encrypted → flag.
  const byUser = {};
  for (const it of list) {
    const p = (Store.recon.peers || []).find(x => x.id === it.peer_id);
    if (!p) continue;
    if (!p.user_id) { flagged.push(p.id); continue; }
    (byUser[p.user_id] = byUser[p.user_id] || []).push(p);
  }
  for (const uid of Object.keys(byUser)) {
    const unlockKey = await ensureUserUnlockKey(uid);
    if (!unlockKey) { byUser[uid].forEach(p => flagged.push(p.id)); continue; }
    for (const p of byUser[uid]) {
      let conf = anySessionConf(p.pubkey);
      if (!conf) for (const t of (p.targets || [])) {
        try { const r = await api.config(p.pubkey, t.node, t.iface); if (r && r.ok && r.data && r.data.config) { conf = r.data.config; break; } } catch (_) {}
      }
      const parsed = conf ? parseFullConf(conf) : null;
      if (!parsed || !parsed.privkey) { flagged.push(p.id); continue; }
      try { await subEncryptPeer(uid, p.id, parsed.privkey, parsed.psk, unlockKey); await captureOverridesFrom(p, parsed); migrated++; }
      catch (_) { flagged.push(p.id); }
    }
  }
  const pr = await api.purgePlaintext({ purge_orphans: true });    // blob-gated purge + orphan cleanup (dead keys)
  await Store.poll();                                              // refresh the plaintext count
  return { migrated, total: list.length, flagged: [...new Set(flagged)],
           purged: (pr && pr.data && pr.data.purged) || 0, orphansPurged: (pr && pr.data && pr.data.orphans_purged) || 0,
           remaining: (pr && pr.data && pr.data.remaining) || 0 };
}

const AWG_ORDER = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"];
// IPv6 leak-guard: a FULL v4 tunnel (AllowedIPs contains 0.0.0.0/0) MUST also capture v6 (::/0), else the client's
// IPv6 traffic escapes the tunnel over its real IP (the tunnels are v4-only, so captured v6 is dropped node-side and
// apps fall back to v4 — no leak). Append ::/0 when it's missing. Split-tunnel (specific v4 CIDRs, no 0.0.0.0/0) is
// left untouched — routing only some v4 is an explicit choice and v6 staying local is expected there.
function guardAllowed(a) {
  const parts = ((a || "").trim() || "0.0.0.0/0, ::/0").split(",").map(s => s.trim()).filter(Boolean);
  if (parts.includes("0.0.0.0/0") && !parts.some(p => p.includes(":"))) parts.push("::/0");
  return parts.join(", ");
}
function buildConf(o) {
  const L = ["[Interface]", "PrivateKey = " + o.privkey, "Address = " + o.address];
  if (o.dns && o.dns.length) L.push("DNS = " + o.dns.join(", "));
  L.push("MTU = " + (o.mtu || 1280));
  for (const k of AWG_ORDER) if (o.awg_params && o.awg_params[k] != null) L.push(k + " = " + o.awg_params[k]);
  L.push("", "[Peer]", "PublicKey = " + o.server_pubkey);
  if (o.psk) L.push("PresharedKey = " + o.psk);
  L.push("AllowedIPs = " + guardAllowed(o.allowed), "Endpoint = " + o.endpoint,
    "PersistentKeepalive = " + (o.keepalive != null && o.keepalive !== "" ? o.keepalive : 25));
  return L.join("\n") + "\n";
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

// Sparse per-peer NON-secret overrides for the roster: only the fields the operator set to something
// OTHER than the interface's live default (so a peer left on defaults stores nothing and keeps tracking
// fleet-wide changes). `opts` = {dns (string), mtu, allowed, keepalive}; `meta` = the (first) target's
// interface meta. Mirrors the server's clean_overrides / effective_client_params so panel + sub + roster
// agree. dns=[] is kept as an explicit "no DNS line" when the interface default is non-empty.
function configOverrides(opts, meta) {
  const ov = {}; meta = meta || {};
  const dnsArr = String(opts.dns || "").split(",").map(s => s.trim()).filter(Boolean);
  const defDns = (meta.dns || []).map(String);
  if (JSON.stringify(dnsArr) !== JSON.stringify(defDns)) ov.dns = dnsArr;
  const mtu = String(opts.mtu || "").trim();
  if (mtu && mtu !== String(meta.mtu || 1280)) ov.mtu = +mtu;
  const allowed = String(opts.allowed || "").trim();
  if (allowed && guardAllowed(allowed) !== "0.0.0.0/0, ::/0") ov.allowed = allowed;
  const ka = String(opts.keepalive || "").trim();
  if (ka !== "" && ka !== "25") ov.keepalive = +ka;
  return ov;
}

function downloadConf(text, base) {
  // octet-stream (not text/plain) so the browser keeps the .conf name instead of appending .txt
  const blob = new Blob([text], { type: "application/octet-stream" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = base.replace(/[^\w.-]+/g, "_").replace(/\.(conf|txt)$/i, "") + ".conf"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Turn-proxy client-artifact encoders live in the shared turn-artifacts.js (window.SWGTurn) so the
// admin app and the subscription page build byte-identical configs from ONE source. _b64ToBytes stays
// here (used beyond turn, e.g. subDec).
function _b64ToBytes(b64) { try { const s = atob(String(b64 || "").trim()); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; } catch (_) { return new Uint8Array(0); } }

// Client-import artifact for a peer behind a turn-proxy — the per-fork wire formats live in the shared
// turn-artifacts.js (window.SWGTurn), loaded by both the admin app and the subscription page.
function turnArtifact(baseConf, tp, vkLink) { return SWGTurn.artifact(baseConf, tp, vkLink); }

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
  events(limit) { return this.get("/api/events?limit=" + (limit || 15)); },
  eventDelete(eid) { return this.post("/api/events/delete", { eid }); },
  eventsClear() { return this.post("/api/events/clear", {}); },
  nodeHistory(node, range) { return this.get("/api/node-history?node=" + encodeURIComponent(node) + "&range=" + encodeURIComponent(range)); },
  meshHistory(range) { return this.get("/api/mesh-history?range=" + encodeURIComponent(range)); },
  categoryHistory(range) { return this.get("/api/category-history?range=" + encodeURIComponent(range)); },
  turnHistory(range) { return this.get("/api/turn-history?range=" + encodeURIComponent(range)); },
  peerHistory(range) { return this.get("/api/peer-history?range=" + encodeURIComponent(range)); },
  // DISTINCT peers/users seen online over a range — set-union of per-bucket presence bitmaps, never a mean
  // and never a traffic proxy (so an idle-but-connected peer counts). One call feeds the bars, the node
  // cards and the doughnuts' "online" figure, so they can no longer disagree.
  presence(range, blocks, step, nodes) {
    return this.get("/api/presence?range=" + encodeURIComponent(range) + "&blocks=" + blocks + "&step=" + step
      + (nodes && nodes.length ? "&nodes=" + encodeURIComponent(nodes.join(",")) : ""));
  },
  ifaceSeries(node, iface, range) { return this.get("/api/iface-series?node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface) + "&range=" + encodeURIComponent(range)); },
  turnSeries(node, fork, range) { return this.get("/api/turn-series?node=" + encodeURIComponent(node) + "&fork=" + encodeURIComponent(fork) + "&range=" + encodeURIComponent(range)); },
  meshSeries(node, peer, range) { return this.get("/api/mesh-series?node=" + encodeURIComponent(node) + "&peer=" + encodeURIComponent(peer) + "&range=" + encodeURIComponent(range)); },
  turnIps() { return this.get("/api/turn-ips"); },
  turnIpsFlush(body) { return this.post("/api/turn-ips/flush", body || {}); },   // {node?, ip?, service?}: ip → delete one; service → this proxy's offline; else node/fleet inactive (keep online)
  catalog(search, page) { return this.get("/api/catalog?search=" + encodeURIComponent(search || "") + "&page=" + (page || 0)); },
  catalogIndex() { return this.get("/api/catalog/index"); },
  catalogRefresh() { return this.post("/api/catalog/refresh", {}); },
  listInfo(cat) { return this.get("/api/list-info?cat=" + encodeURIComponent(cat)); },
  geoUpdate() { return this.post("/api/geo/update", {}); },
  geoProviderRetry(provider) { return this.post("/api/geo/provider-retry", { provider }); },
  nextIp(nodes, iface) { return this.get("/api/next-ip?nodes=" + encodeURIComponent(nodes.join(",")) + "&iface=" + encodeURIComponent(iface)); },
  config(pubkey, node, iface) { return this.get("/api/config?pubkey=" + encodeURIComponent(pubkey) + "&node=" + encodeURIComponent(node) + "&iface=" + encodeURIComponent(iface)); },
  account() { return this.get("/api/account"); },
  accountSave(b) { return this.post("/api/account", b); },
  twofaSetup() { return this.post("/api/account/2fa/setup", {}); },
  twofaEnable(code) { return this.post("/api/account/2fa/enable", { code }); },
  twofaDisable(b) { return this.post("/api/account/2fa/disable", b); },
  nodes() { return this.get("/api/nodes"); },
  nodeCreate(b) { return this.post("/api/nodes/create", b); },
  nodeUpdate(b) { return this.post("/api/nodes/update", b); },
  connectionUpdate(b) { return this.post("/api/connection/update", b); },
  panelSettings(b) { return this.post("/api/panel/settings", b); },
  subVault() { return this.get("/api/sub/vault"); },
  subVaultSet(b) { return this.post("/api/sub/vault", b); },
  subReset() { return this.post("/api/sub/reset", {}); },
  subUsers() { return this.get("/api/sub/users"); },
  subUserEnable(b) { return this.post("/api/sub/user/enable", b); },
  subUserRotate(b) { return this.post("/api/sub/user/rotate", b); },
  subUserDisable(b) { return this.post("/api/sub/user/disable", b); },
  subBlob(b) { return this.post("/api/sub/blob", b); },
  subBlobGet(pid) { return this.get("/api/sub/blob?peer_id=" + encodeURIComponent(pid)); },   // read one peer's ciphertext for in-browser Show-QR decrypt
  subEscrow(b) { return this.post("/api/sub/escrow", b); },   // ensure a user holds an encryption unlock-key (encrypted config storage, no subscription)
  purgePlaintext(b) { return this.post("/api/config/purge-plaintext", b || {}); },   // migration: delete legacy plaintext where a blob exists
  plaintextPeers() { return this.get("/api/config/plaintext-peers"); },   // migration: exactly which peers still hold plaintext (+ orphan count)
  refreshGeo() { return this.post("/api/panel/refresh-geo", {}); },
  // external integration API (Settings → Integrations): read-only tokens + webhooks
  apiTokenCreate(label) { return this.post("/api/integrations/token", { label }); },
  apiTokenRevoke(id) { return this.post("/api/integrations/token/revoke", { id }); },
  apiWebhookSave(b) { return this.post("/api/integrations/webhook", b); },
  apiWebhookDelete(id) { return this.post("/api/integrations/webhook/delete", { id }); },
  apiWebhookTest(id) { return this.post("/api/integrations/webhook/test", { id }); },
  routingReset(b) { return this.post("/api/node/routing-reset", b); },   // per-node: wipe + rebuild + re-pull all smart-routing state
  asnCount(n) { return this.get("/api/asn?n=" + encodeURIComponent(n)); },   // resolve an ASN → prefix count (live editor feedback)
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
    // store_configs is now an enum: "encrypted" (blob at rest) | "off". storeConfigs stays a convenience bool
    // meaning "the panel keeps configs" (now encrypted). configsPlaintext = legacy plaintext files awaiting migration.
    this.storeMode = (d.store_configs === "off" || d.store_configs === false) ? "off" : "encrypted";
    this.storeConfigs = this.storeMode !== "off";
    this.configsPlaintext = d.configs_plaintext || 0;
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
    // Silent auto-heal net: catch peers that ended up unpublished (created/assigned while locked, or in another
    // session) and publish them once the key is available. Gated on a cheap signature — the peer/user counts plus
    // lock state — so the extra /api/sub/users round-trip fires on a roster change or an unlock, not every idle poll.
    try {
      const hk = (subSKCached() && this.storeMode === "encrypted")
        ? (Object.keys(this.roster.peers || {}).length + ":" + Object.keys(this.roster.users || {}).length)
        : "off";
      if (hk !== this._healKey) { this._healKey = hk; if (hk !== "off") subAutoHeal(); }
    } catch (_) {}
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
  // Two dims (see app.css): `dim` = THIS proxy needs attention or is in flight — dim through the whole
  // 'creating' phase (installing/queued/assigned) plus failed/down/stopped/deleting; only a settled card is
  // full-bright. `nblocked` = the NODE forbids editing (offline / converting / re-installing / updating), which
  // is exactly what disables the buttons — so every card on the page dims together, not just the mesh ones.
  const dim = !justRestarted && (installing || queued || pend || failed || down || stopped || err);
  const nblocked = nodeStale(node) || inProc(nrec.proc_status);
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
  const canOpen = nrec.turn_manage && !nblocked && !_busy && pend !== "delete";   // clickable only once it settles — NOT while creating/queued/deleting, and never while the node blocks edits (don't open a half-created proxy)
  return html`<div class=${"ifcard tp" + (canOpen ? " clickable" : "") + (dim ? " down" : "") + (nblocked ? " locked" : "") + (it ? it.cls : "")} onClick=${canOpen ? () => openTurnManage(node, tp) : null} data-rid=${it ? it.rid : null}>
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
      actions=${(!iface && nrec.turn_manage) ? html`<${Fragment}><button class="btn btn-mini ico" title="Turn-proxy settings in Settings → Turn proxies" onClick=${() => goSettings("turn")}><${Ic} i="gear"/></button><button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openSetupTurn(node)}><${Ic} i="plus"/> Setup new proxy</button><//>` : null}>
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
// Per-peer render params — the peer's stored overrides where set, else the interface's LIVE defaults.
// Mirrors the server's effective_client_params so a blob-only render matches what the sub page produces.
function effectiveClientParams(peer, meta) {
  const ov = (peer && peer.overrides) || {}; meta = meta || {};
  return {
    dns: ("dns" in ov) ? ov.dns : (meta.dns || []),
    mtu: ov.mtu || meta.mtu || 1280,
    allowed: ov.allowed || "0.0.0.0/0, ::/0",
    keepalive: ("keepalive" in ov) ? ov.keepalive : 25,
  };
}

// The ENCRYPTED-AT-REST config path: fetch the peer's ciphertext blob, decrypt it in-browser with the
// user's unlock-key (recovered from the vault), and rebuild the config LIVE from the decrypted {k,p} +
// the peer's overrides + the interface's current params. Returns null (caller falls back to plaintext /
// session) when the peer is unassigned, the vault is locked, or no blob exists yet. Never sends a key.
async function blobConfig(peer, node, iface) {
  if (!peer || !subSKCached()) return null;                // user_id optional — unassigned peers use the orphan bucket
  const t = (peer.targets || []).find(x => x.node === node && x.iface === iface);
  const meta = Store.ifaceMeta(node, iface);
  if (!t || !meta) return null;
  let sec, unlockKey;
  try {
    const r = await api.subBlobGet(peer.id);
    if (!r || !r.ok || !r.data || !r.data.sec) return null;
    sec = r.data.sec;
    const buid = r.data.user_id || peer.user_id || SUB_ORPHAN;   // decrypt with the key of the bucket the blob is IN
    const rec = (await subUsersMap())[buid];
    if (!rec || !rec.unlock_by_sk) return null;
    unlockKey = await subRecoverUnlock(rec);   // unlock-key only (works whether or not the user is subscribed)
  } catch (_) { return null; }
  try {
    const secret = JSON.parse(new TextDecoder().decode(await subDec(unlockKey, sec)));   // GCM auth fails on a wrong key
    if (!secret || !secret.k) return null;
    const eff = effectiveClientParams(peer, meta);
    return buildConf({ privkey: secret.k, address: (t.ip || "").split("/")[0] + "/32",
      dns: eff.dns, mtu: eff.mtu, awg_params: meta.awg_params, server_pubkey: meta.public_key,
      psk: secret.p || peer.psk, endpoint: meta.endpoint, allowed: eff.allowed, keepalive: eff.keepalive });
  } catch (_) { return null; }
}

function getConfig(pubkey, node, iface) {
  const s = Store.sessionConfigs[pubkey];
  if (s && s[tkey(node, iface)]) return Promise.resolve(rerenderConf(s[tkey(node, iface)], node, iface));
  // encrypted-at-rest blob first (assigned peer + vault unlocked); else the transitional plaintext store.
  const peer = (Store.recon.peers || []).find(p => p.pubkey === pubkey);
  return blobConfig(peer, node, iface).then(c => {
    if (c) return c;
    if (Store.storeConfigs) return api.config(pubkey, node, iface).then(r => rerenderConf(r.ok ? r.data.config : null, node, iface)).catch(() => null);
    return null;
  });
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
function _blurActive() { requestAnimationFrame(() => { const a = document.activeElement; if (a && a.blur && a.tagName !== "BODY") a.blur(); }); }
function closeModal() { _applyStack(_stack.slice(0, -1)); _blurActive(); }   // drop the focus ring the trigger regains on ESC/close
function closeAllModals() { _applyStack([]); _blurActive(); }
let _sheetStack = [];   // mounted Sheet tokens (LIFO) — only the topmost handles Esc/Enter/Tab

// Row activation: a single click runs `fn` after a short delay; a double click cancels that and runs `dbl`
// instead (open the QR modal). Clicks on interactive children (buttons/links/inputs/the assign combo) pass
// through untouched. One shared timer is enough — a person clicks one row at a time.
let _rowClickT = null;
const _rowInteractive = e => !!(e.target.closest && e.target.closest("button, a, input, select, textarea, label, .assigncell, .rowacts, .selwrap"));
function rowSingle(e, fn) { if (_rowInteractive(e)) return; clearTimeout(_rowClickT); _rowClickT = setTimeout(() => { _rowClickT = null; fn(); }, 200); }
function rowDouble(e, fn) { if (_rowInteractive(e)) return; clearTimeout(_rowClickT); _rowClickT = null; fn(); }
const rowNoSelect = e => { if (e.detail > 1) e.preventDefault(); };   // stop the 2nd click of a double-click from selecting the row text

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
// operator title of a turn-proxy (by service) on a node, if one was set — for the "Connected via" bubble
function turnProxyTitle(node, service) {
  const tp = ((Store.stats[node] || {}).turn_proxies || []).find(x => x && x.service === service);
  return (tp && tp.title) || "";
}
// The interface badge for one peer-grid row (protocol + iface name).
function gridIfaceTag(t) {
  return html`<${Tag} kind=${targetType(t)} label=${t.iface} muted=${!t.online}/>`;
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
// loopback (127.0.0.1) — the relay forwards locally — so instead of the bare IP show "turn-proxy" tinted with
// the fork colour + the same "Connected via <fork>" hover bubble the status dot uses.
//
// This holds once the peer goes OFFLINE too: wg keeps the last endpoint, so `via` is still "turn" and printing
// the raw 127.0.0.1 tells the operator nothing at all. Keep the attribution, dim it, and say "Last connected
// via". If the exact fork can no longer be resolved (the proxy was removed, or the node predates wg_sports) we
// still know it was relayed — say so rather than fall back to a loopback address.
function endpointCell(t) {
  const obs = t.observed;
  if (t.via === "turn") {
    const tn = t.viaTurn ? turnLabel(t.viaTurn) : null;
    const tc = tn ? turnColor(tn) : "var(--dim)";
    const ptitle = t.viaTurn ? turnProxyTitle(t.node, t.viaTurn) : null;
    return html`<span class="turnwrap">
      <span class=${"addr turnep" + (t.online ? "" : " off")} style=${"color:" + (t.online ? tc : "var(--dim)")}>turn-proxy</span>
      <span class="turnbub">${t.online ? "Connected via" : "Last connected via"} ${tn
          ? html`<span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>`
          : html`<span class="faint">a turn-proxy</span>`}${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
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
        <${Tag} kind=${targetType(d)} label=${d.iface} muted=${!d.online}/>
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
// Open Live on the tab that matches the bubble that was clicked. `connView.mode` is module state that
// remembers the last toggle, so without this a Users bubble could land on the Peers table (or vice versa).
// The appbar bubble is visible ON the Live screen too, where the hash does not change — so nudge the bus.
const openLiveTab = mode => e => {
  e.stopPropagation();
  connView.mode = mode; connView.page = 1;
  if (location.hash === "#/connections") bus.emit();     // already there: no hashchange to re-render us
};
function OnlPop({ title, rows, peer, orphans, orphHref, trigger, cls }) {
  const tab = peer ? "peers" : "users";                  // this bubble lists peers, or users
  const renderRow = peer
    ? r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.title}</span><span class="on-user faint">${r.user}${r.iface ? " · " + r.iface : ""}${r.ip ? " · " + r.ip : ""}</span></div>`
    : r => html`<div class=${"onrow" + (r.unassigned ? " un" : "")}><span class="on-name">${r.name}</span><span class="on-ct">${r.count} <span class="faint">peer${r.count > 1 ? "s" : ""}</span></span></div>`;
  return html`<${Popover} cls=${"onlinetag " + (cls || "")} trigger=${trigger(rows.length)}>
    <a class="onpop-h onpop-link" href="#/connections" onClick=${openLiveTab(tab)}>${title} · ${rows.length} →</a>
    ${rows.length ? rows.slice(0, 10).map(renderRow) : html`<div class="onrow faint">${peer ? "no peers online" : "no one online"}</div>`}
    ${orphans ? html`<a class="onpop-orph" href=${orphHref || "#/connections"} onClick=${openLiveTab("peers")}>${orphans} unmanaged orphan peer${orphans > 1 ? "s" : ""}</a>` : null}
    ${rows.length > 10 ? html`<a class="onpop-viewall" href="#/connections" onClick=${openLiveTab(tab)}>view all ${rows.length} connections →</a>` : null}
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
// `presence` (from /api/presence, per node) switches this from "online right now" to "distinct users seen
// online during the selected range" — the question the range picker is actually asking. Without it the card
// answered "nobody is connected this instant" while the Day doughnut reported peers online that day.
function OnlineUsersTag({ nodeId, cls, trigger, presence, rangeLabel }) {
  const rows = presence ? (presence.userRows || []).map(r => ({ ...r, lastAge: null })) : onlineUserRows(nodeId);
  return html`<${OnlPop} title=${presence ? "Users online · " + (rangeLabel || "range") : "Online users"} rows=${rows} cls=${cls}
    trigger=${trigger || (c => html`<span class="dot"></span><b class=${"oncount" + (c ? " on" : "")}>${c}</b> online`)}/>`;
}
// "N online" peers bubble (device · user · ip). orphans: count to append. Used on interface cards/screens.
function OnlinePeersTag({ nodeId, iface, total, cls, trigger, orphans, orphHref }) {
  return html`<${OnlPop} peer title="Online peers" rows=${onlinePeerRows(nodeId, iface)} orphans=${orphans} orphHref=${orphHref} cls=${cls}
    trigger=${trigger || (c => html`<b class=${"oncount" + (c ? " on" : "")}>${c}</b>${total != null ? " / " + total : ""} online`)}/>`;
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
    call: () => api.peerRekey({ peer_id: peer.id, user_id: userId, pubkey: keys.pub, psk }),   // no plaintext to the server
    onOk: () => { Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++; revealAssignedPeer(userId, peer.id);
      subPublishOrPrompt(userId, peer.id, keys.priv, psk); },
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
    call: () => api.peerRekey({ peer_id: peer.id, user_id: peer.user_id, pubkey: keys.pub, psk }),   // no plaintext to the server
    onOk: () => { delete Store.sessionConfigs[peer.pubkey]; Store.sessionConfigs[keys.pub] = configs; Store.configEpoch++;
      subPublishOrPrompt(peer.user_id, peer.id, keys.priv, psk); },
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
    onOk: () => { revealAssignedPeer(userId, peer.id); subReconcileUser(userId); } });   // keeps its key, so publish via backfill (prompts to unlock if locked)
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
// `traffic` = this node's client (non-mesh) rx/tx for the SELECTED range — a live rate, or windowed volume
// when `ranged`. Computed once in Overview (nodeTraffic) so the card agrees with the doughnuts/top-nodes.
function FleetNodeCard({ n, traffic, ranged, histRange, nodeHist, presence }) {
  const live = Store.recon.nodeStatus[n.id] === "live";
  const snap = Store.stats[n.id];
  const nrec = (Store.nodes || []).find(x => x.id === n.id) || {};   // health lives on the node-store record
  const health = nrec.health || null;
  const tr = traffic || { rx: 0, tx: 0 };
  const trafCell = ranged ? xferCell(...dlul(tr.rx, tr.tx)) : rateCell(tr.rx, tr.tx);
  let sync = "no data"; if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); sync = live ? "synced " + seen(a) + " ago" : "stale · " + seen(a); }
  const al = healthAlerts(health);
  // client interface-type badges — one per type present, "awg" / "awg ×5" (mesh/system ifaces excluded)
  const ifs = Store.describe[n.id] || {}; let wg = 0, awg = 0;
  for (const ifn in ifs) { const m = ifs[ifn]; if (!m || m.system) continue; if (m.awg_params && Object.keys(m.awg_params).length) awg++; else wg++; }
  const ifBadges = []; if (awg) ifBadges.push(["awg", awg]); if (wg) ifBadges.push(["wg", wg]);
  return html`<a class=${"fnode " + (live ? "" : "stale")} href=${"#/node/" + encodeURIComponent(n.id)}>
    <div class="fnode-main">
      <div class="fnode-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="fnode-name">${n.name}</span>${al.length ? html`<span class="halert hot"><${Ic} i="warn"/> ${al.length}</span>` : ""}<span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>
      <div class="fnode-stats">
        <div><span class="fl">Traffic</span>${trafCell}</div>
        <div><span class="fl">Online</span><span class="fv"><${OnlineUsersTag} nodeId=${n.id} presence=${presence} rangeLabel=${histRange} trigger=${c => html`${c} <span class="faint">user${c === 1 ? "" : "s"}</span>`}/></span></div>
        <div><span class="fl">Sync</span><span class="fv">${sync}</span></div>
        ${ifBadges.length ? html`<div class="fnode-ifs">${ifBadges.map(([t, c]) => html`<span key=${t} class=${"iftype " + t}>${t}${c > 1 ? " ×" + c : ""}</span>`)}</div>` : null}
      </div>
    </div>
    <div class="fnode-health">
      ${health ? html`<${NodeHealth} health=${health} node=${n.id} compact=${true} range=${histRange} nodeHist=${nodeHist}/>` : html`<div class="fnode-nohealth">${live ? "no health data reported" : "node offline"}</div>`}
    </div>
  </a>`;
}

// ─────────── Activity taxonomy ───────────
// The panel's server-side event log (/api/events) records every operator action. One place decides
// each record's ITEM category (icon + the history "Item" filter), an ACTION bucket (Added / Changed /
// Removed, the history "Action" filter), and where a click lands. Shared by the Overview feed and the
// full Activity-history grid so both stay consistent.
const EV_ITEMS = ["Peer", "User", "Node", "Interface", "Turn-proxy", "Mesh", "Settings", "Update"];
const EV_ACTIONS = ["Added", "Changed", "Removed"];
const EV_ITEM_IC = { Peer: "device", User: "user", Node: "server", Interface: "network", "Turn-proxy": "relay", Mesh: "cascade", Settings: "gear", Update: "download" };
const evSlug = s => s.toLowerCase().replace(/[^a-z]/g, "");   // "Turn-proxy" → "turnproxy" (CSS tint class)
function evItem(e) {
  const v = e.verb || "";
  if (e.kind === "peer") return "Peer";
  if (e.kind === "user") return "User";
  if (e.kind === "panel") return v === "Panel updated" ? "Update" : "Settings";
  if (/interface/i.test(v)) return "Interface";       // kind === node from here
  if (/turn-proxy/i.test(v)) return "Turn-proxy";
  if (/mesh/i.test(v)) return "Mesh";
  if (/^update |host update/i.test(v)) return "Update";   // update LIFECYCLE ("Update requested", "Host update started") — NOT "Updated node/interface"
  return "Node";
}
function evAction(e) {
  const v = (e.verb || "").toLowerCase();
  if (/\b(deleted|removed|deleting|uninstalled|flagged)\b/.test(v)) return "Removed";
  if (/\b(created|enrolled|installing|creating|onboarding|added|linked|adopted)\b/.test(v)) return "Added";
  return "Changed";
}
// Where a feed/grid row navigates. Returns {href} for a plain link, {href,on} for a scripted reveal
// (flash + scroll), or null for non-actionable rows (a version bump, an update-lifecycle note).
function evClick(e) {
  const item = evItem(e), v = e.verb || "", gone = /\bdeleted\b/i.test(v);
  if (item === "Peer") return gone ? { href: "#/peers" } : { href: "#/peers", on: () => revealPeerInPeersById(e.id) };
  if (item === "User") return gone ? { href: "#/users" } : { href: "#/users", on: () => revealUser(e.id) };
  if (item === "Settings") return { href: "#/panel/settings", on: () => { pendingSettingsSection = (e.id && e.id !== "settings") ? e.id : null; go("#/panel/settings"); } };
  if (item === "Update") return null;                 // panel version bump / update lifecycle — nothing to open
  if (/\b(removed node|uninstalled)\b/i.test(v)) return { href: "#/nodes" };   // the node is gone
  return e.id ? { href: "#/node/" + encodeURIComponent(e.id) } : { href: "#/nodes" };
}
function evDecorate(e, i) {
  const item = evItem(e);
  return { ...e, item, action: evAction(e), icon: EV_ITEM_IC[item] || "info", slug: evSlug(item),
           click: evClick(e), key: "e" + (e.eid || e.ts) + "_" + i };
}
// Fallback feed when the server log is still empty: synthesise created/updated rows from the roster's
// created_at vs modified_at, so a fresh panel's Overview is never blank.
function synthEvents() {
  const ev = [];
  for (const u of Store.recon.users) {
    const c = u.created_at || 0, m = u.modified_at || c;
    ev.push({ ts: m, kind: "user", id: u.id, verb: m > c + 5 ? "Updated user" : "Created user", name: u.name, detail: "" });
  }
  for (const p of Store.recon.peers) {
    const c = p.created_at || 0, m = p.modified_at || c;
    ev.push({ ts: m, kind: "peer", id: p.id, verb: m > c + 5 ? "Updated peer" : "Created peer", name: p.title || p.name || "unassigned peer", detail: "" });
  }
  return ev.filter(e => e.ts).sort((a, b) => b.ts - a.ts);
}
function recentActivity(n) {
  const src = (Store.events && Store.events.length) ? Store.events : synthEvents();
  return src.slice(0, n || 15).map(evDecorate);
}
// "3 WireGuard and 2 AmneziaWG interfaces" — the interface breakdown for a grouped-unassigned row.
function ifCountPhrase(g) {
  const parts = [];
  if (g.wg.size) parts.push(g.wg.size + " WireGuard");
  if (g.awg.size) parts.push(g.awg.size + " AmneziaWG");
  const tot = g.wg.size + g.awg.size;
  return (parts.join(" and ") || "0") + " interface" + (tot === 1 ? "" : "s");
}
function ifTypeLabel(node, iface) {
  const m = Store.ifaceMeta && Store.ifaceMeta(node, iface);
  return (m && Object.keys(m.awg_params || {}).length) ? "AmneziaWG" : "WireGuard";
}
// Deep-link target for a Settings activity row (the first changed section id, applied on the settings screen).
let pendingSettingsSection = null;
let pendingTurnIpsOpen = false;   // set by the "Turn IPs" header → Settings opens + expands + scrolls to the Collected IPs grid
// Jump to a Settings sub-section, closing any open modal first (a no-op when nothing is open). Used by the
// gear shortcuts next to Add rule / Create interface / Setup proxy.
function goSettings(section) { pendingSettingsSection = section; closeAllModals(); go("#/panel/settings"); }

// ─────────── Dashboard controls: node selector + time range ───────────
// Two module-level controls drive every Overview widget. The NODE selector filters the fleet the
// dashboard aggregates over (default = ALL, stored as null); unselecting nodes re-renders every widget
// for the remaining set (all-but-one = a single-node view). The RANGE selector chooses the history
// window for the range-driven visuals (doughnuts + flow map); live derives from the /api/state bundle,
// the rest read the per-node RRD on demand. Both live in module state + localStorage so a re-render or
// the 5s poll never clobbers the operator's selection (it's not derived from server data).
const DASH_RANGES = [["live", "Live"], ["hour", "Hour"], ["day", "Day"], ["week", "Week"], ["month", "Month"]];
const RANGE_ICON = { hour: "hour2", day: "daycal", week: "weekcal", month: "monthcal" };   // side-rail renders range as icons (live = glowing dot)
// side-rail section jump-nav: [label, section-title h2 substring to scroll to, icon]
const DASH_NAV = [["Fleet", "Fleet", "server"], ["Distribution", "Distribution", "donut"], ["Traffic flow", "Traffic flow", "flow"], ["Top charts", "Top nodes", "bars"], ["Activity log", "Recent activity", "excl"]];
// nodes: null = whole fleet, else a Set of node ids. peers/mesh = which traffic COMPONENTS the figures count
// (the toolbar badges): peers = client traffic (total−mesh), mesh = node↔node relay traffic. `ov` = per-widget
// overrides keyed by widget id, each {peers?,mesh?} where a set field pins that pill and null inherits the global.
const dashState = { nodes: null, range: "live", peers: true, mesh: true, ov: {} };
(function () {
  try {
    const raw = JSON.parse(localStorage.getItem("swg-dash") || "{}");
    if (Array.isArray(raw.nodes) && raw.nodes.length) dashState.nodes = new Set(raw.nodes);   // ignore a stale empty selection → default to the whole fleet
    if (DASH_RANGES.some(r => r[0] === raw.range)) dashState.range = raw.range;
    if (typeof raw.peers === "boolean") dashState.peers = raw.peers;
    if (typeof raw.mesh === "boolean") dashState.mesh = raw.mesh;
    if (raw.ov && typeof raw.ov === "object") dashState.ov = raw.ov;
  } catch (_) {}
})();
function dashSave() {
  try { localStorage.setItem("swg-dash", JSON.stringify({ nodes: dashState.nodes ? [...dashState.nodes] : null, range: dashState.range, peers: dashState.peers, mesh: dashState.mesh, ov: dashState.ov })); } catch (_) {}
}
// ── Peers/Mesh traffic filter ──────────────────────────────────────────────────────────────────────────────
// Every traffic figure has the raw total (rx,tx) and its mesh portion (mrx,mtx) in hand. The badges decide which
// components survive: peers = client (total−mesh), mesh = the relay portion. Either, both, or neither (→ 0).
function trafPick(rx, tx, mrx, mtx, f) {
  const crx = Math.max(0, (rx || 0) - (mrx || 0)), ctx = Math.max(0, (tx || 0) - (mtx || 0));
  return { rx: (f.peers ? crx : 0) + (f.mesh ? (mrx || 0) : 0),
           tx: (f.peers ? ctx : 0) + (f.mesh ? (mtx || 0) : 0) };
}
// Effective flags for a widget: its per-widget override pins a pill, otherwise the pill inherits the global badge.
function trafFlags(key) {
  const ov = key && dashState.ov ? dashState.ov[key] : null;
  return { peers: ov && ov.peers != null ? ov.peers : dashState.peers,
           mesh:  ov && ov.mesh  != null ? ov.mesh  : dashState.mesh };
}
// Flip one widget's own Peers/Mesh override (pinned in dashState.ov[key]) without touching the others — each traffic
// doughnut drives its filter independently. Never leave BOTH off: turning off the only-selected one flips to the other.
function dashToggleTrafKey(key, which) {
  const cur = trafFlags(key), other = which === "peers" ? "mesh" : "peers";
  const next = { peers: cur.peers, mesh: cur.mesh };
  if (next[which] && !next[other]) { next[which] = false; next[other] = true; }
  else next[which] = !next[which];
  dashState.ov = dashState.ov || {}; dashState.ov[key] = next;
  dashSave(); bus.emit();
}
// Effective selected node ids, reconciled against the CURRENT fleet (ids for departed nodes drop out).
// An empty selection collapses back to the whole fleet — the dashboard is never blank.
// null OR an empty set both mean "the whole fleet" — the selection can never be empty (nothing to show).
function dashNodes() {
  const fleet = (Store.fleet || []).map(n => n.id);
  if (!dashState.nodes || !dashState.nodes.size) return fleet;
  const sel = fleet.filter(id => dashState.nodes.has(id));
  return sel.length ? sel : fleet;
}
function dashNodeOn(id) { const s = dashState.nodes; return !s || !s.size || s.has(id); }
function dashToggleNode(id) {
  const fleet = (Store.fleet || []).map(n => n.id);
  const sel = new Set(dashState.nodes && dashState.nodes.size ? [...dashState.nodes].filter(x => fleet.includes(x)) : fleet);
  if (sel.has(id)) {
    if (sel.size <= 1) return;   // the last selected node can NOT be deselected — the dashboard always shows ≥1 node
    sel.delete(id);
  } else sel.add(id);
  dashState.nodes = (sel.size >= fleet.length) ? null : sel;   // all selected → canonical null (never an empty set)
  dashSave(); bus.emit();
}
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
    h.t.forEach((t, i) => { const r = byT.get(t) || { rx: 0, tx: 0, on: 0 };
      r.rx += Math.max(0, ((h.rx || [])[i] || 0) - ((h.mrx || [])[i] || 0));
      r.tx += Math.max(0, ((h.tx || [])[i] || 0) - ((h.mtx || [])[i] || 0));
      r.on += (h.pon || [])[i] || 0; byT.set(t, r); });                       // online-peer count from the ring (survives reload)
  });
  const t = [...byT.keys()].sort((a, b) => a - b);
  return { t, rx: t.map(x => byT.get(x).rx), tx: t.map(x => byT.get(x).tx), on: t.map(x => byT.get(x).on), hasOn: t.some(x => byT.get(x).on > 0) };
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
// Fleet-summed history for the hero charts over the SELECTED range. Live → the 15s ring (rx/tx, mesh netted
// out) + the client online accumulator; a range → Σ per-node RRD (rx−mesh, tx−mesh, pon) aligned by bucket
// timestamp. Returns { t, rx, tx, on } — everything the fleet-throughput + online-peers charts need.
function fleetHistory(selIds, range, hist) {
  if (range === "live") {
    const m = mergeFleetSeries(selIds);
    // online-peer trend: prefer the panel ring's `pon` (full on load, survives reload); fall back to the
    // client-side accumulator for a node/panel too old to report pon in health_history.
    if (m.hasOn) return { t: m.t, rx: m.rx, tx: m.tx, onT: m.t, on: m.on };
    const o = dashOnlineTrend(selIds);
    return { t: m.t, rx: m.rx, tx: m.tx, onT: o ? o.t : [], on: o ? o.pts : [] };
  }
  const byT = new Map();
  selIds.forEach(id => { const d = hist.byNode[id]; if (!d || !d.t) return;
    d.t.forEach((t, i) => { const r = byT.get(t) || { rx: 0, tx: 0, on: 0 };
      r.rx += Math.max(0, ((d.rx || [])[i] || 0) - ((d.mrx || [])[i] || 0));
      r.tx += Math.max(0, ((d.tx || [])[i] || 0) - ((d.mtx || [])[i] || 0));
      r.on += (d.pon || [])[i] || 0; byT.set(t, r); }); });
  const t = [...byT.keys()].sort((a, b) => a - b);
  return { t, rx: t.map(x => byT.get(x).rx), tx: t.map(x => byT.get(x).tx), onT: t, on: t.map(x => byT.get(x).on) };
}
// Online-peers block chart: fixed BLOCK count + step per range (independent of the RRD ring granularity).
//   live 30×30s (15 min) · hour 30×2 min · day 24×1 h · week 28×6 h · month 30×1 day.
const ONLINE_BLOCKS = { live: [30, 30], hour: [30, 120], day: [24, 3600], week: [28, 21600], month: [30, 86400] };
// Resample an irregular (t[], v[]) series into `n` right-anchored blocks of `step` seconds — each block = the
// PEAK (max) of the samples in its window (null when empty, so the chart can show a gap). This charts a COUNT of
// online peers: a MEAN renders integer counts as misleading fractions ("0.05 peers" when one peer was online for
// one sample of the window); the peak stays a whole number and still surfaces that brief activity.
function resampleBlocks(t, v, n, step) {
  const out = new Array(n).fill(null);
  if (!t || !t.length) return out;
  const end = t[t.length - 1];
  for (let i = 0; i < t.length; i++) {
    const idx = n - 1 - Math.floor((end - t[i]) / step);
    if (idx >= 0 && idx < n) { const x = v[i] || 0; out[idx] = out[idx] == null ? x : Math.max(out[idx], x); }
  }
  return out;
}

// The dashboard toolbar: a multi-select node filter (themed chips) + a live/day/week/month range toggle.

// Once you scroll the dashbar out of view, the SAME node selector + range dock as a compact vertical rail pinned to the
// right edge, vertically centred and travelling with the scroll. It shrinks further when the pointer leaves it (a "peek")
// and grows back on hover; scrolling back to the top slides it away and the inline dashbar takes over again. Self-contained
// scroll state (rAF-throttled, no-op when the boolean doesn't flip) so it never taxes the poll path.
// The node rail panel — shared by the Overview rail (nav=false: toggle a node in/out of the dashboard) and the
// node/interface-detail rail (nav=true: jump to a node). Identical markup/CSS; only the per-row behaviour differs.
function NodesRailPanel({ nav, active }) {
  const ns = Store.nodes || [];
  return html`<div class="railpanel railmenu railmenu-nodes">
    ${ns.map(n => {
      const down = Store.recon.nodeStatus[n.id] !== "live";
      const on = nav ? (n.id === active) : dashNodeOn(n.id);
      const cls = "railmenu-b node" + (on ? " on" : (nav ? "" : " off")) + (down ? " down" : "");
      const inner = html`<span class="railmenu-ic"><span class="railnode-dot" style=${"--c:" + Store.nodeColor(n.id)}></span></span><span class="railmenu-t">${n.name}</span>`;
      if (!nav)
        return html`<button key=${n.id} class=${cls} onClick=${() => dashToggleNode(n.id)} title=${(on ? "Hide " : "Show ") + n.name + (down ? " · not reporting" : "")}>${inner}</button>`;
      return on
        ? html`<span key=${n.id} class=${cls} title=${n.name + (down ? " · not reporting" : "")}>${inner}</span>`
        : html`<a key=${n.id} class=${cls} href=${"#/node/" + encodeURIComponent(n.id)} title=${(down ? "Down — " : "Go to ") + n.name}>${inner}</a>`;
    })}
  </div>`;
}
function DashRail() {
  const fleet = Store.fleet || [];
  const range = dashState.range;
  const findSection = find => [...document.querySelectorAll(".section-title")].find(x => { const h = x.querySelector("h2"); return h && h.textContent.indexOf(find) !== -1; });
  const jump = find => { const s = findSection(find); if (s) s.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const menuIc = ic => /^[a-z0-9_-]+$/.test(ic) ? html`<${Ic} i=${ic}/>` : html`<span class="railmenu-emoji">${ic}</span>`;   // registry key → svg icon · anything else (emoji) → text
  // scroll-spy: highlight the jump icon of the section currently in view (first one at the top, one at a time as you scroll)
  const [active, setActive] = useState(0);
  useEffect(() => {
    let raf = 0;
    const compute = () => { raf = 0;
      const titles = [...document.querySelectorAll(".section-title")]; let idx = 0;
      DASH_NAV.forEach(([label, find], i) => { const el = titles.find(x => { const h = x.querySelector("h2"); return h && h.textContent.indexOf(find) !== -1; });
        if (el && el.getBoundingClientRect().top <= 130) idx = i; });   // last section whose title has reached the top band
      setActive(idx); };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(compute); };
    window.addEventListener("scroll", onScroll, { passive: true }); compute();
    return () => { window.removeEventListener("scroll", onScroll); if (raf) cancelAnimationFrame(raf); };
  }, []);
  // Always-on rail: one uniform menu-panel shape for all three (jump · ranges · nodes) — collapsed to icons, hover the
  // panel to slide the labels out, each row highlights on hover (icon → theme colour, label stays neutral).
  return html`<div class="dashrail">
    <div class="dashrail-stack">
      <div class="railpanel railmenu">
        ${DASH_NAV.map(([label, find, ic], i) => html`<button key=${label} class=${"railmenu-b" + (i === active ? " on" : "")} onClick=${() => jump(find)} title=${label}>
          <span class="railmenu-ic">${menuIc(ic)}</span><span class="railmenu-t">${label}</span></button>`)}
      </div>
      <div class="railpanel railmenu">
        ${DASH_RANGES.map(([k, lbl]) => html`<button key=${k} class=${"railmenu-b" + (range === k ? " on" : "")} onClick=${() => dashSetRange(k)} title=${lbl}>
          <span class="railmenu-ic">${k === "live" ? html`<span class="rlive-dot"></span>` : html`<${Ic} i=${RANGE_ICON[k]}/>`}</span><span class="railmenu-t">${lbl}</span></button>`)}
      </div>
      ${fleet.length > 1 ? html`<${NodesRailPanel} nav=${false}/>` : null}
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
  const [st, setSt] = useState({ loading: false, byNode: {}, mesh: [], cats: [], turn: [], peers: [], presence: null, range: "live" });
  const key = range + "|" + selIds.slice().sort().join(",");
  useEffect(() => {
    if (range === "live") { setSt({ loading: false, byNode: {}, mesh: [], cats: [], turn: [], peers: [], presence: null, range: "live" }); return; }
    let alive = true; setSt(s => ({ ...s, loading: true }));
    const [obN, obStep] = ONLINE_BLOCKS[range] || ONLINE_BLOCKS.live;   // the bars ask for exactly the blocks they draw
    Promise.all([
      Promise.all(selIds.map(id => api.nodeHistory(id, range).then(r => [id, (r && r.data) || null]).catch(() => [id, null]))),
      api.meshHistory(range).then(r => (r && r.data && r.data.pairs) || []).catch(() => []),
      api.categoryHistory(range).then(r => (r && r.data && r.data.cats) || []).catch(() => []),
      api.turnHistory(range).then(r => (r && r.data && r.data.turn) || []).catch(() => []),
      api.peerHistory(range).then(r => (r && r.data && r.data.peers) || []).catch(() => []),
      api.presence(range, obN, obStep, selIds).then(r => (r && r.data) || null).catch(() => null),
    ]).then(([rows, mesh, cats, turn, peers, presence]) => { if (!alive) return; const byNode = {}; rows.forEach(([id, d]) => { byNode[id] = d; }); setSt({ loading: false, byNode, mesh, cats, turn, peers, presence, range }); });
    return () => { alive = false; };
  }, [key]);
  return st;
}
// total bytes moved over a range window = Σ(per-bucket mean B/s) × bucket step

// The 4 concentric-ring doughnuts. All respect the node selector AND the time range: live comes from the
// /api/state bundle; day/week/month read the per-node RRD (client rx/tx = total−mesh, awg-client rx/tx, and
// peer online/total counts) fetched on demand off the hot path. Traffic → volume over the window; counts →
// mean over the window.
function DashDoughnuts({ selIds, range, hist }) {
  const sel = new Set(selIds);
  const fleet = (Store.fleet || []).filter(n => sel.has(n.id));
  const live = range === "live";
  const ranged = !live && hist.range === range;   // caller passes the EFFECTIVE (loaded) range, so this holds the old data through a fetch instead of flashing live
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
  const meshVol = d => ({ rx: _sum(d && d.mrx) * STEP, tx: _sum(d && d.mtx) * STEP });

  // ── traffic by node + by iface type. Each doughnut owns an INDEPENDENT Peers/Mesh filter (FN = by node,
  //    FT = by interface): accumulate the raw client/mesh components once, then apply each filter at the end. ──
  const FN = trafFlags("dnode"), FT = trafFlags("dtype");
  const nodeRaw = {};   // per node: client (crx/ctx) and mesh (mrx/mtx) kept apart so either filter can pick them
  const typeRaw = { wg: { rx: 0, tx: 0 }, awg: { rx: 0, tx: 0 }, mesh: { rx: 0, tx: 0 } };
  const addType = (k, rx, tx) => { typeRaw[k].rx += rx; typeRaw[k].tx += tx; };
  fleet.forEach(n => {
    if (ranged) {
      const d = hist.byNode[n.id]; const cv = clientVol(d), av = awgVol(d), mv = meshVol(d);
      nodeRaw[n.id] = { crx: cv.rx, ctx: cv.tx, mrx: mv.rx, mtx: mv.tx };
      addType("awg", av.rx, av.tx); addType("wg", Math.max(0, cv.rx - av.rx), Math.max(0, cv.tx - av.tx));
      addType("mesh", mv.rx, mv.tx);
    } else {
      let crx = 0, ctx = 0, mrx = 0, mtx = 0; const snap = Store.stats[n.id];
      if (snap) for (const [ifn, blk] of Object.entries(snap.interfaces || {})) {
        let r = 0, t = 0; for (const pp of blk.peers || []) { r += pp.rx_speed || 0; t += pp.tx_speed || 0; }
        if (isSys(n.id, ifn)) { mrx += r; mtx += t; }                          // mesh link (swg_*)
        else { crx += r; ctx += t; addType(ifType(n.id, ifn), r, t); }
      }
      addType("mesh", mrx, mtx);
      nodeRaw[n.id] = { crx, ctx, mrx, mtx };
    }
  });
  // apply each doughnut's own filter to the raw components
  const nodeTraf = {}; fleet.forEach(n => { const r = nodeRaw[n.id] || { crx: 0, ctx: 0, mrx: 0, mtx: 0 }; nodeTraf[n.id] = trafPick(r.crx + r.mrx, r.ctx + r.mtx, r.mrx, r.mtx, FN); });
  const typePick = k => k === "mesh" ? { rx: FT.mesh ? typeRaw.mesh.rx : 0, tx: FT.mesh ? typeRaw.mesh.tx : 0 }
                                     : { rx: FT.peers ? typeRaw[k].rx : 0, tx: FT.peers ? typeRaw[k].tx : 0 };
  const typeTraf = { wg: typePick("wg"), awg: typePick("awg"), mesh: typePick("mesh") };
  const trafFmt = ranged ? fmtBytes : rate;

  // ── peer deployments by node + by iface type. TOTAL = the roster count deployed to each node/iface (a real head-
  //    count, not a time-average). ONLINE = DISTINCT peers seen connected: live → online right now; a range → the
  //    distinct peers that were active at any point in the window (unioned from the per-peer RRD, so cycling peers
  //    all count once — not the peak or the mean). ──
  const nodeCnt = {}, typeCnt = { wg: { tot: 0, on: 0 }, awg: { tot: 0, on: 0 } };
  fleet.forEach(n => nodeCnt[n.id] = { tot: 0, on: 0 });
  // live interface is authoritative; the stored target.type is only a fallback for interfaces the node isn't reporting.
  const tyOf = t => { const m = Store.describe[t.node] && Store.describe[t.node][t.iface]; return m ? ifType(t.node, t.iface) : ((t.type === "awg") ? "awg" : "wg"); };
  sPeers.forEach(p => p.targets.forEach(t => {
    if (!sel.has(t.node)) return;
    const ty = tyOf(t);
    nodeCnt[t.node].tot++; (typeCnt[ty] = typeCnt[ty] || { tot: 0, on: 0 }).tot++;
    if (!ranged && t.online) { nodeCnt[t.node].on++; typeCnt[ty].on++; }
  }));
  if (ranged) {
    // DISTINCT peers seen online during the window, from the presence bitmaps. This used to be derived from the
    // per-peer TRAFFIC rings (rx+tx>0), which is wrong twice over: those rings skip idle peers (PEER_MIN_BPS), and
    // before the window fix a peer that moved bytes a day ago still counted as "online this hour".
    const pnodes = (hist.presence && hist.presence.nodes) || {};
    fleet.forEach(n => nodeCnt[n.id].on = ((pnodes[n.id] || {}).peers) || 0);
    Object.keys(typeCnt).forEach(ty => typeCnt[ty].on = 0);
    Object.entries(pnodes).forEach(([nid, v]) => {
      if (!sel.has(nid)) return;
      Object.entries(v.ifaces || {}).forEach(([ifn, c]) => {   // the peer's target iface on that node → its protocol
        const ty = ifType(nid, ifn);
        if (typeCnt[ty]) typeCnt[ty].on += c;
      });
    });
  }

  const nodeName = id => Store.nodeName(id), nodeColor = id => Store.nodeColor(id);
  const TYPES = [["awg", "AmneziaWG"], ["wg", "WireGuard"], ["mesh", "Mesh"]];   // the Mesh slice only fills when the Mesh badge is on
  const typeColor = t => t === "mesh" ? FLOW_MESH : ifaceColor(t);
  const segNodes = kind => fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: (nodeTraf[n.id] || {})[kind] || 0, color: nodeColor(n.id) }));
  const segTypes = kind => TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeTraf[t] || {})[kind] || 0, color: typeColor(t) }));
  const sum = (o, k) => Object.values(o).reduce((a, v) => a + (v[k] || 0), 0);

  // centre readouts
  // Auto-fit the font to the widest value string so a wide figure (e.g. "1023.66 M/s") stays on one line
  // inside the ring hole instead of wrapping/spilling over the arc.
  const fitFs = n => n <= 9 ? 16 : n <= 11 ? 14 : n <= 13 ? 12.5 : 11;   // a touch smaller so the up/down rates clear the inner ring
  const povPeers = (Store.panelSettings || {}).throughput_perspective === "peers";   // ↓/↑ from the peer's side when set
  const trafCenter = (rx, tx) => {
    const [down, up] = dlul(rx, tx);
    const ds = "↓ " + trafFmt(down), us = "↑ " + trafFmt(up);
    const dfs = fitFs(Math.max(ds.length, us.length)), ufs = Math.max(11, dfs - 3);
    return html`<div class="mrc-def"><span class="mrc-k">total</span>
      <span class="mrc-tot dn" style=${"font-size:" + dfs + "px"}>${ds}</span><span class="mrc-tot up" style=${"font-size:" + ufs + "px"}>${us}</span></div>`;
  };
  const cntCenter = (on, tot) => html`<div class="mrc-def"><span class="mrc-k">online</span>
    <span class="mrc-tot dn">${on}<small style="color:var(--faint)"> / ${tot}</small></span></div>`;

  const totDownN = sum(nodeTraf, "rx"), totUpN = sum(nodeTraf, "tx");
  const totDownT = typeTraf.wg.rx + typeTraf.awg.rx + typeTraf.mesh.rx, totUpT = typeTraf.wg.tx + typeTraf.awg.tx + typeTraf.mesh.tx;
  const nodeOn = Object.values(nodeCnt).reduce((a, v) => a + v.on, 0), nodeTot = Object.values(nodeCnt).reduce((a, v) => a + v.tot, 0);
  const typeOn = typeCnt.wg.on + typeCnt.awg.on, typeTot = typeCnt.wg.tot + typeCnt.awg.tot;

  // traffic legends carry down/up SEPARATELY (perspective-adjusted) so each is independently hoverable —
  // hovering the ↓ value isolates the Download arc, the ↑ value the Upload arc.
  const legDU = (rx, tx) => { const [d, u] = dlul(rx, tx); return { down: trafFmt(d), up: trafFmt(u) }; };
  const trafLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id),
    ...legDU((nodeTraf[n.id] || {}).rx || 0, (nodeTraf[n.id] || {}).tx || 0) }));
  const trafLegTypes = TYPES.filter(([t]) => (typeTraf[t] || {}).rx + (typeTraf[t] || {}).tx > 0).map(([t, nm]) => ({ key: t, name: nm, color: typeColor(t),
    ...legDU(typeTraf[t].rx, typeTraf[t].tx) }));
  const cntLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id), right: nodeCnt[n.id].on + " / " + nodeCnt[n.id].tot }));
  const cntLegTypes = TYPES.filter(([t]) => (typeCnt[t] || { tot: 0 }).tot > 0).map(([t, nm]) => ({ key: t, name: nm, color: ifaceColor(t), right: typeCnt[t].on + " / " + typeCnt[t].tot }));

  const rlabel = DASH_RANGES.find(r => r[0] === range);
  const rname = rlabel ? rlabel[1].toLowerCase() : range;
  const loadingNote = (!live && hist.loading) ? html`<div class="donut-note">loading ${rname} history…</div>` : null;
  const volNote = ranged ? html`<div class="donut-note">volume over the ${rname}</div>` : null;
  const avgNote = ranged ? html`<div class="donut-note">avg over the ${rname}</div>` : null;
  // traffic rings carry unitColor so the hovered centre readout tints the unit letter ↓ green / ↑ blue.
  // Under the peer perspective the ↓ (Download) ring is fed by tx and ↑ (Upload) by rx, so it agrees with
  // the centre total, the legend, and every other figure.
  const trafRings = (rxSegs, txSegs) => { const dnSegs = povPeers ? txSegs : rxSegs, upSegs = povPeers ? rxSegs : txSegs;
    return [{ label: "Download", fmt: trafFmt, unitColor: "var(--online)", segments: dnSegs },
      { label: "Upload", fmt: trafFmt, unitColor: "var(--rate-up)", segments: upSegs }]; };

  // ── by TURN-PROXY FORK (the 3rd row). Aggregated BY FORK across the fleet (like "by interface type"), only for
  //    the forks enabled in Panel settings. Live = attribute each turn-routed peer (target.viaTurn) to its fork;
  //    ranged = the per-(node,fork) RRD (hist.turn). The fork's interface tags come from its live peers. Turn has
  //    no per-fork history until a node has been reporting, so on a range with no rows it falls back to live. ──
  const turnOn = turnEnabled();
  const enSet = new Set(turnOn ? enabledTurnForks().map(f => f.id) : []);
  const sanF = s => String(s).replace(/[^A-Za-z0-9_]/g, "_");
  const fLive = {};   // fork → { rx, tx, on, tot } aggregated across every node/instance of that fork
  if (turnOn) sPeers.forEach(p => p.targets.forEach(t => {
    if (!sel.has(t.node) || !t.viaTurn) return;
    const fk = turnFork(t.viaTurn); if (!enSet.has(fk)) return;
    const a = fLive[fk] = fLive[fk] || { rx: 0, tx: 0, on: 0, tot: 0 };
    const o = t.observed; if (o) { a.rx += o.rx_speed || 0; a.tx += o.tx_speed || 0; }
    a.tot++; if (t.online) a.on++;
  }));
  const fRanged = {};   // sanitised fork → { rx, tx, pon, ptot } summed over selected nodes
  if (ranged) (hist.turn || []).forEach(e => { if (!sel.has(e.node)) return;
    const a = fRanged[e.fork] = fRanged[e.fork] || { rx: 0, tx: 0, pon: 0, ptot: 0 };
    a.rx += e.rx || 0; a.tx += e.tx || 0; a.pon += e.pon || 0; a.ptot += e.ptot || 0; });
  const turnRanged = ranged && Object.keys(fRanged).length > 0;   // ranged turn data present → use it; else live
  const fTraf = fk => turnRanged ? (fRanged[sanF(fk)] || { rx: 0, tx: 0 }) : (fLive[fk] || { rx: 0, tx: 0 });
  const fCnt = fk => turnRanged ? { on: Math.round((fRanged[sanF(fk)] || {}).pon || 0), tot: Math.round((fRanged[sanF(fk)] || {}).ptot || 0) }
                                : { on: (fLive[fk] || {}).on || 0, tot: (fLive[fk] || {}).tot || 0 };
  const forks = [...enSet].filter(fk => { const t = fTraf(fk), c = fCnt(fk); return (t.rx + t.tx) > 0 || c.tot > 0; });
  const turnFmt = turnRanged ? fmtBytes : rate;
  const turnCenter = (rx, tx) => { const [d, u] = dlul(rx, tx); const ds = "↓ " + turnFmt(d), us = "↑ " + turnFmt(u);
    const dfs = fitFs(Math.max(ds.length, us.length)), ufs = Math.max(11, dfs - 3);
    return html`<div class="mrc-def"><span class="mrc-k">total</span>
      <span class="mrc-tot dn" style=${"font-size:" + dfs + "px"}>${ds}</span><span class="mrc-tot up" style=${"font-size:" + ufs + "px"}>${us}</span></div>`; };
  const turnTrafRings = () => { const rxS = forks.map(fk => ({ key: fk, name: fk, value: fTraf(fk).rx, color: turnColor(fk) })),
      txS = forks.map(fk => ({ key: fk, name: fk, value: fTraf(fk).tx, color: turnColor(fk) }));
    const dn = povPeers ? txS : rxS, up = povPeers ? rxS : txS;
    return [{ label: "Download", fmt: turnFmt, unitColor: "var(--online)", segments: dn }, { label: "Upload", fmt: turnFmt, unitColor: "var(--rate-up)", segments: up }]; };
  const turnCntRings = () => [
    { label: "Total peers", fmt: v => v, segments: forks.map(fk => ({ key: fk, name: fk, value: fCnt(fk).tot, color: turnColor(fk) })) },
    { label: "Online", fmt: v => v, segments: forks.map(fk => ({ key: fk, name: fk, value: fCnt(fk).on, color: turnColor(fk) })) }];
  const turnTrafLeg = forks.map(fk => ({ key: fk, name: fk, color: turnColor(fk), ...(() => { const t = fTraf(fk), [d, u] = dlul(t.rx, t.tx); return { down: turnFmt(d), up: turnFmt(u) }; })() }));
  const turnCntLeg = forks.map(fk => { const c = fCnt(fk); return { key: fk, name: fk, color: turnColor(fk), right: c.on + " / " + c.tot }; });
  const turnTot = forks.reduce((s, fk) => { const t = fTraf(fk), c = fCnt(fk); s.rx += t.rx; s.tx += t.tx; s.on += c.on; s.tot += c.tot; return s; }, { rx: 0, tx: 0, on: 0, tot: 0 });
  const turnLiveNote = html`<div class="donut-note">live rates${ranged ? " · no history yet for this range" : ""}</div>`;
  const turnNote = turnRanged ? volNote : turnLiveNote;       // traffic card → volume
  const turnAvgNote = turnRanged ? avgNote : turnLiveNote;    // peers card → avg

  const loading = !live && hist.loading;
  // Each traffic doughnut gets its OWN Peers/Mesh toggle (its own override key) so they operate independently.
  const trafBadgesFor = (key, F) => html`<div class="dcard-traf">
    <button class=${"tbadge peers" + (F.peers ? " on" : "")} onClick=${() => dashToggleTrafKey(key, "peers")} title=${(F.peers ? "Hide" : "Show") + " client (peer) traffic"}>Peers</button>
    <button class=${"tbadge mesh" + (F.mesh ? " on" : "")} onClick=${() => dashToggleTrafKey(key, "mesh")} title=${(F.mesh ? "Hide" : "Show") + " mesh (node-to-node relay) traffic"}>Mesh</button>
  </div>`;
  // Grid rows group BY DIMENSION: row 1 = the two "by node" rings, row 2 = the two "by interface" rings.
  return html`<div class="donutgrid">
    <${DoughCard} title="Traffic by node" badges=${trafBadgesFor("dnode", FN)} loading=${loading}
      rings=${trafRings(segNodes("rx"), segNodes("tx"))} center=${trafCenter(totDownN, totUpN)} legend=${trafLegNodes} note=${loadingNote || volNote}/>

    <${DoughCard} title="Peers by node" loading=${loading}
      rings=${[{ label: "Total peers", fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].tot, color: nodeColor(n.id) })) },
               { label: "Online", fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].on, color: nodeColor(n.id) })) }]}
      center=${cntCenter(nodeOn, nodeTot)} legend=${cntLegNodes} note=${loadingNote || avgNote}/>

    <${DoughCard} title="Traffic by interface" badges=${trafBadgesFor("dtype", FT)} loading=${loading}
      rings=${trafRings(segTypes("rx"), segTypes("tx"))} center=${trafCenter(totDownT, totUpT)} legend=${trafLegTypes} note=${loadingNote || volNote}/>

    <${DoughCard} title="Peers by interface" loading=${loading}
      rings=${[{ label: "Total peers", fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).tot || 0, color: ifaceColor(t) })) },
               { label: "Online", fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).on || 0, color: ifaceColor(t) })) }]}
      center=${cntCenter(typeOn, typeTot)} legend=${cntLegTypes} note=${loadingNote || avgNote}/>

    ${turnOn && forks.length ? html`<${Fragment}>
      <${DoughCard} title="Traffic by turn-proxy" loading=${loading}
        rings=${turnTrafRings()} center=${turnCenter(turnTot.rx, turnTot.tx)} legend=${turnTrafLeg} note=${loadingNote || turnNote}/>

      <${DoughCard} title="Peers by turn-proxy" loading=${loading}
        rings=${turnCntRings()} center=${cntCenter(turnTot.on, turnTot.tot)} legend=${turnCntLeg} note=${loadingNote || turnAvgNote}/>
    <//>` : null}
  </div>`;
}

// One distribution card = a doughnut + its legend sharing a hovered {key, dir} target, so hovering ONE ring
// arc (or one ↓/↑ value) isolates exactly that arc and that value — its partner arc/value dims too. Hovering
// the NAME (dir:null) lights both arcs and shows that entity's own numbers in the centre. Fully bidirectional
// between ring and legend. Hover-only state — no poll-path cost, cheap Preact re-renders (no SVG rebuild).
function DoughCard({ title, rings, center, legend, note, loading, badges }) {
  const [active, setActive] = useState(null);   // { key, dir } | null · dir = ring index, or null for the whole entity
  return html`<div class="donutcard">
    <div class="donutcard-h"><h3>${title}</h3><span class="grow"></span>${badges || null}</div>
    <div class="donut-body">
      <${MultiRing} rings=${rings} center=${center} active=${active} onActive=${setActive}/>
      <${RingLegend} items=${legend} active=${active} onActive=${setActive}/>
    </div></div>`;
}

// ═══════════════ Signal-flow map (redesign, P1: categorized model + static split/merge render) ═══════════════
// Per selected server, live rx/tx split into endpoint KINDS: clients (direct wg/awg peers), turn (per VK fork),
// internet (direct exit — approximate until the node SNAT counter), mesh (per peer server). Each is a bidirectional
// pair (ingress = rx, egress = tx); 0-value flows dropped. Every flow is drawn source→dest as blue(egress)→green(ingress).
const FLOW_EG = "#2E90FF", FLOW_IN = "#22D07A", FLOW_GLOBE = "#12BECE", FLOW_MESH = "#9B8AFF";   // egress blue · ingress green · internet cyan-teal (distinct from egress blue) · off-fleet mesh violet
function flowGraph(selIds, range, hist) {
  const sel = new Set(selIds);
  const fleet = (Store.fleet || []).filter(n => sel.has(n.id));
  const ranged = range && range !== "live" && hist && hist.range === range;   // caller passes the EFFECTIVE (loaded) range → holds old data through a fetch (no flash to live)
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
    // split turn-proxy volume OUT of the client lane (turn rides the client iface) using the per-fork turn RRD, so the
    // ranged map shows the SAME turn satellites as live instead of folding them into "clients".
    (hist.turn || []).forEach(e => { const a = acc[e.node]; if (!a) return; const rx = e.rx || 0, tx = e.tx || 0; if (!rx && !tx) return;
      (a.turn[e.fork] = a.turn[e.fork] || { rx: 0, tx: 0 }); a.turn[e.fork].rx += rx; a.turn[e.fork].tx += tx;
      a.cl.rx = Math.max(0, a.cl.rx - rx); a.cl.tx = Math.max(0, a.cl.tx - tx); });
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
  const rankRef = useRef({ key: null, order: [] });   // frozen busyness ordering (see `ranked` below) — hook must sit above the early return
  const anim = (Store.panelSettings || {}).flow_anim || "off";   // HOST-WIDE setting — shared by every operator, persists across logins (default = OFF until an operator picks a style)
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
  // Few nodes → the adaptive frame renders the whole diagram at a bigger scale, so a fixed 25px ceiling reads TOO thick.
  // Trim the max line width for sparse selections (N=1 → ~12px … N≥5 → full 25px); the floor stays put.
  const wCeil = 25 * Math.min(1, 0.62 + 0.1 * (N - 1));
  const wMap = mapper(flows.map(f => f.bps), 2, wCeil, LOQ);             // line width px: floor 2 · ceiling wCeil (per direction)
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
  // Node POSITIONS are seeded by busyness, but FROZEN per selection — re-ranked only when nodes are selected/
  // unselected, never on the 5s poll. Re-ranking live made the whole diagram reshuffle as traffic fluctuated
  // (visual churn + wasted client CPU); the initial (or last selection-change) order now holds steady.
  const _selKey = fleet.map(n => n.id).slice().sort().join(",");
  if (rankRef.current.key !== _selKey)
    rankRef.current = { key: _selKey, order: fleet.slice().sort((p, q) => (busy(q.id) - busy(p.id)) || (p.id < q.id ? -1 : 1)).map(n => n.id) };
  const ranked = rankRef.current.order.map(id => fleet.find(n => n.id === id)).filter(Boolean);   // biggest traffic first, held stable
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
    if (allIsle || N === 1) {                             // ISLAND STAR (single node, or a grid of all-islands): the UPSTREAM sats — internet
      const up = mine.filter(s => s.kind === "internet" || s.kind === "mesh");    // + the rest-of-fleet MESH — fan on TOP; clients + turn-proxies
      const down = mine.filter(s => s.kind !== "internet" && s.kind !== "mesh");  // fan on the BOTTOM. Even fans keep them off neighbours' lines.
      const fan = (grp, base) => { const sp = Math.min(Math.PI - 2 * HB - 0.15, 0.5 + grp.length * 0.42);
        grp.forEach((s, i) => place(s, base + (grp.length === 1 ? 0 : (i / (grp.length - 1) - 0.5) * sp))); };
      fan(up, -Math.PI / 2); fan(down, Math.PI / 2);
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
  // ADAPTIVE frame — the aspect FOLLOWS the content's own shape (clamped to a band) instead of a fixed ratio, so sparse
  // selections tighten toward the cluster (no dead band) while dense webs keep their taller spread. A gentle min-width keeps
  // a lone node from being blown up. Content is then centred in whatever frame we land on.
  const AR_MIN = 1.4, AR_MAX = 1.75, FRAME_W = 480;
  const cw = vx1 - vx0, ch = vy1 - vy0, ccx = (vx0 + vx1) / 2, ccy = (vy0 + vy1) / 2;
  const AR = Math.max(AR_MIN, Math.min(AR_MAX, cw / ch));   // frame width:height, clamped to the band
  const vbW = Math.max(cw, ch * AR, FRAME_W), vbH = vbW / AR;   // frame always contains the content (vbW≥cw, vbH≥ch)
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
  // Fresh install (or every node removed) → there's no fleet to chart. Skip the whole dashboard and invite
  // the operator to add their first entry server. (After the two hooks above, so rules-of-hooks holds.)
  if (fleet.length === 0) return html`<div class="screen"><div class="nonodes">
    <div class="nonodes-ic"><${Ic} i="server"/></div>
    <h2>No nodes yet</h2>
    <p>Add your first entry server to start deploying peers. The panel stays the source of truth — each node syncs to it over outbound HTTPS.</p>
    <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> Add node</button>
  </div></div>`;
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
  const pAssigned = sPeers.filter(p => !p.unassigned).length;   // peers attached to a user vs. floating (no owner)
  const pUnassigned = sPeers.length - pAssigned;
  const sUsers = users.filter(u => sPeers.some(p => p.user_id === u.id));
  const liveNodes = fleetSel.filter(n => ns[n.id] === "live").length;
  const ifaceCount = selIds.reduce((a, id) => a + Object.keys(Store.describe[id] || {}).filter(ifn => !isSys(id, ifn)).length, 0);
  const nodesAlerting = fleetSel.filter(n => healthAlerts(((Store.nodes || []).find(x => x.id === n.id) || {}).health).length).length;
  let rx = 0, tx = 0;
  fleetSel.forEach(n => { const [r, t] = nodeRate(n.id); rx += r; tx += t; });

  const PROB_STATUSES = ["dangling", "partial", "blocked", "faulty", "pending", "unknown"];
  const probs = sPeers.filter(p => PROB_STATUSES.includes(p.status))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const unassigned = Store.unassignedPeers().filter(onSel);
  const orphans = Store.recon.orphans.filter(o => sel.has(o.node));
  const why = { dangling: "missing on every server", partial: "missing on some servers", blocked: "handshake never completes", faulty: "no inbound data flowing", pending: "just created, not seen yet", unknown: "server stale — can't confirm" };

  // Needs-attention shown IN BULK: problem peers grouped by status, unassigned grouped by node, orphans
  // grouped by interface — each row lands where you'd fix it (Peers filtered, or the interface detail).
  const STATUS_WORD = { dangling: "dangling", partial: "partially deployed", blocked: "blocked", faulty: "faulty", pending: "pending", unknown: "on a stale server" };
  const statusGroups = PROB_STATUSES.map(s => ({ status: s, peers: probs.filter(p => p.status === s) })).filter(g => g.peers.length);
  const unByNode = {};
  unassigned.forEach(p => p.targets.forEach(t => {
    if (!sel.has(t.node)) return;
    const g = unByNode[t.node] || (unByNode[t.node] = { node: t.node, peers: new Set(), wg: new Set(), awg: new Set() });
    g.peers.add(p.id); (targetType(t) === "awg" ? g.awg : g.wg).add(t.iface);
  }));
  const unGroups = Object.values(unByNode);
  const orphByIf = {};
  orphans.forEach(o => { const k = o.node + "|" + o.iface; (orphByIf[k] || (orphByIf[k] = { node: o.node, iface: o.iface, n: 0 })).n++; });
  const orphGroups = Object.values(orphByIf);
  const attnCount = statusGroups.length + unGroups.length + orphGroups.length;

  const recent = recentActivity();

  // ranked nodes — by traffic over the SELECTED RANGE (live rate, or windowed client volume = Σ(rx−mesh)·step,
  // matching the doughnuts), or by peer count when the fleet is idle (selected nodes only)
  // EFFECTIVE range = the range whose data is actually loaded/showing. During a fetch it LAGS the just-clicked range
  // (rangeHist keeps the previous range's data), so every ranged figure holds the OLD range until the new one lands —
  // no flash to live, no layout jump. Live is immediate. Only the rail's active highlight reads the raw dashState.range.
  const effRange = dashState.range === "live" ? "live" : (rangeHist.range || dashState.range);
  const dRanged = effRange !== "live";
  const dStep = RANGE_STEP[effRange] || 1;
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
      sub: anyTraffic ? (dRanged ? xferCell(...dlul(x.rx, x.tx)) : rateCell(x.rx, x.tx)) : x.peers + " peer" + (x.peers === 1 ? "" : "s"),
      color: x.color || "var(--brand)", href: "#/node/" + encodeURIComponent(x.id) }));

  // ── range-aware fleet hero series. Live = the 15s ring + online accumulator (no server hit); a range =
  //    Σ per-node RRD (fetched once by useRangeHistory, off the hot path). Fleet throughput reuses the node
  //    ThroughputChart summed; online-peers resamples pon into the fixed per-range block count. ──
  const fleetHist = fleetHistory(selIds, effRange, rangeHist);
  const tputRange = effRange === "live" ? "hour" : effRange;   // fleet live feed IS the 15s (hour) ring
  const [obN, obStep] = ONLINE_BLOCKS[effRange] || ONLINE_BLOCKS.live;
  // Each bar = DISTINCT peers seen online in that bar's span, unioned from the presence bitmaps. `pon` (the
  // health ring) is a mean of concurrency and cannot answer this: five peers online 12 min each average to 1.
  // Live keeps the client-side accumulator — a 30s bar of "online now" needs no server round-trip.
  const _pres = rangeHist.presence;
  const onlineBlocks = (dRanged && _pres && _pres.blocks) ? _pres.blocks : resampleBlocks(fleetHist.onT, fleetHist.on, obN, obStep);
  const onlineEndTs = (dRanged && _pres) ? _pres.end : fleetHist.onT[fleetHist.onT.length - 1];
  const hasOnline = onlineBlocks.some(v => v != null);
  // how many rows the ranked lists show — operator-set in Panel settings → Display (1–50, default 10)
  const nTalk = Math.max(1, Math.min(50, (Store.panelSettings || {}).top_talkers || 10));
  const nDest = Math.max(1, Math.min(50, (Store.panelSettings || {}).top_destinations || 10));
  // top talkers — peers ranked by traffic across the selected nodes. Live = current per-peer rx/tx from the
  // snapshot; a range = per-peer windowed VOLUME from the peer RRD (/api/peer-history), matched back to the peer
  // by pubkey. Same node-selector + perspective as every other figure.
  let perPeer;   // per-PEER traffic first (live per-target speeds, or ranged per-peer volume from the RRD)…
  if (dRanged) {
    const pkPeer = {}; sPeers.forEach(p => { if (p.pubkey) pkPeer[p.pubkey] = p; });   // pubkey → reconciled peer
    const byPk = {};
    (rangeHist.peers || []).forEach(e => { if (!sel.has(e.node) || !pkPeer[e.pubkey]) return;
      const a = byPk[e.pubkey] = byPk[e.pubkey] || { rx: 0, tx: 0 }; a.rx += e.rx || 0; a.tx += e.tx || 0; });
    perPeer = Object.entries(byPk).map(([pk, v]) => ({ p: pkPeer[pk], rx: v.rx, tx: v.tx })).filter(x => x.p);
  } else {
    perPeer = sPeers.map(p => {
      let r = 0, t = 0; p.targets.forEach(tg => { if (!sel.has(tg.node)) return; const o = tg.observed; if (o) { r += o.rx_speed || 0; t += o.tx_speed || 0; } });
      return { p, rx: r, tx: t };
    });
  }
  // …then COMBINE a user's peers into ONE talker (a user with several devices is one bar, not one per device; the
  // hover bubble breaks the total down per peer). Unassigned peers have no user to merge under → each stays its own row.
  const talkG = {};
  perPeer.forEach(x => { if (x.rx + x.tx <= 0) return;
    const key = x.p.user_id ? "u" + x.p.user_id : "p" + x.p.id;
    const g = talkG[key] || (talkG[key] = { user: x.p.user_id ? Store.user(x.p.user_id) : null, sample: x.p, rx: 0, tx: 0, peers: [] });
    g.rx += x.rx; g.tx += x.tx; g.peers.push(x); });
  const talkers = Object.values(talkG).sort((a, b) => (b.rx + b.tx) - (a.rx + a.tx)).slice(0, nTalk);
  const talkerRows = talkers.map((g, i) => {
    const peers = g.peers.slice().sort((a, b) => (b.rx + b.tx) - (a.rx + a.tx));
    return {
      label: g.user ? g.user.name : (g.sample.title || "Unassigned peer"), value: g.rx + g.tx, count: peers.length,
      sub: dRanged ? xferCell(...dlul(g.rx, g.tx)) : rateCell(g.rx, g.tx),
      // per-peer breakdown for the hover bubble — only when a user has >1 peer actually contributing traffic.
      // Each row carries its protocol (wg/awg, from the live interface) + a name: the peer's title, or — when it has
      // none — "Peer .<last octet of its tunnel IP>" (e.g. 10.99.3.43 → "Peer .43"), never the user's name.
      bub: peers.length > 1 ? peers.map(pp => { const t = (pp.p.targets || [])[0] || {}; const oct = (t.ip || "").split(".").pop();
        return { kind: targetType(t), name: pp.p.title || (oct ? "Peer ." + oct : "Peer"), value: pp.rx + pp.tx,
          sub: dRanged ? xferCell(...dlul(pp.rx, pp.tx)) : rateCell(pp.rx, pp.tx) }; }) : null,
      color: dashRankColor(i, "talker"), href: "#/users",
      onClick: e => { e.preventDefault(); g.user ? revealUser(g.user.id) : revealPeer(g.sample); },
    };
  });
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
    .sort((a, b) => (b[1].dn + b[1].up) - (a[1].dn + a[1].up)).slice(0, nDest)
    .map(([cat, v], i) => ({ label: catLabelOf(cat), value: v.dn + v.up, sub: dRanged ? xferCell(...dlul(v.dn, v.up)) : rateCell(v.dn, v.up), color: dashRankColor(i, "dest") }));
  const _un = catAgg.uncat;   // the first-match "matched no set" bucket — always pinned last (a catch-all, not ranked), even if it's the largest
  if (_un && _un.up + _un.dn > 0) catRows.push({ label: catLabelOf("uncat"), value: _un.dn + _un.up, sub: dRanged ? xferCell(...dlul(_un.dn, _un.up)) : rateCell(_un.dn, _un.up), color: CAT_UNCAT_COLOR });
  const totClientRx = nodeTraffic.reduce((a, x) => a + (x.rx || 0), 0);   // distinct client total (rx/tx) — categories are a subset/overlap of this
  const totClientTx = nodeTraffic.reduce((a, x) => a + (x.tx || 0), 0);

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <${DashRail}/>
    <div class="statgrid">
      <a class="stat accent clk" href="#/connections" onClick=${openLiveTab("peers")}><span class="stat-ic"><${Ic} i="activity"/></span><div class="stat-c"><div class="k">Online now</div><div class="v">${online}<small> / ${sPeers.length}</small></div><div class="sub">live connections →</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="users"/></span><div class="stat-c"><div class="k">Users</div><div class="v">${sUsers.length}</div><div class="sub">${sPeers.length} peers${scoped ? " here" : " total"}</div></div></a>
      <a class="stat clk" href="#/peers"><span class="stat-ic"><${Ic} i="device"/></span><div class="stat-c"><div class="k">Peers</div><div class="v" style="font-size:19px"><span style="color:var(--ink)">${pAssigned}</span> · <span style="color:var(--dim)">${pUnassigned}</span></div><div class="sub">assigned · unassigned</div>${orphans.length ? html`<div class="sub" style="color:#E8912D;font-weight:600">Orphan peers ${orphans.length}</div>` : ""}</div></a>
      <a class="stat clk" href="#/nodes"><span class="stat-ic"><${Ic} i="server"/></span><div class="stat-c"><div class="k">Nodes</div><div class="v">${liveNodes}<small> / ${fleetSel.length}</small></div><div class="sub">${ifaceCount} interface${ifaceCount === 1 ? "" : "s"}${nodesAlerting ? html` · <span style="color:var(--dangling)">${nodesAlerting} alerting</span>` : ""}</div></div></a>
      <div class="stat"><span class="stat-ic"><${Ic} i="gauge"/></span><div class="stat-c"><div class="k">Throughput</div><div class="v" style=${"font-size:19px;color:" + (rx + tx > 0 ? "var(--online)" : "var(--faint)")}>↓ ${rate(dlul(rx, tx)[0])}</div><div class="sub"><span style=${"color:" + (rx + tx > 0 ? "var(--ready)" : "var(--faint)")}>↑ ${rate(dlul(rx, tx)[1])}</span>${scoped ? " selected" : " aggregate"}</div></div></div>
    </div>

    ${secTitle("Fleet", html`${scoped ? fleetSel.length + " of " + fleet.length : fleet.length} server${fleet.length === 1 ? "" : "s"}`)}
    ${fleetSel.length ? html`<div class="trends">
      <div class="trendcard wide">
        <div class="donutcard-h"><h3>Fleet throughput</h3></div>
        ${(fleetHist.t || []).length > 1
          ? html`<${ThroughputChart} rx=${fleetHist.rx} tx=${fleetHist.tx} times=${fleetHist.t} range=${tputRange} cap=${RANGE_CAP[tputRange]} h=${70}/>`
          : html`<div class="harea-empty">gathering — no history yet</div>`}
      </div>
      <div class="trendcard">
        <div class="donutcard-h"><h3>Online peers</h3><span class="grow"></span><span class="trend-now">${dRanged && _pres ? _pres.total.peers : online}</span></div>
        ${hasOnline
          ? html`<${OnlineBlocks} blocks=${onlineBlocks} step=${obStep} endTs=${onlineEndTs} range=${effRange} color="var(--online)" h=${70}/>`
          : html`<div class="harea-empty">gathering — fills as it polls</div>`}
      </div>
    </div>` : null}
    ${fleetSel.length ? html`<div class="fleet2">${fleetSel.map(n => html`<${FleetNodeCard} key=${n.id} n=${n} traffic=${nodeTraffic.find(x => x.id === n.id)} ranged=${dRanged} histRange=${effRange} nodeHist=${(rangeHist.byNode || {})[n.id] || null} presence=${dRanged && _pres ? (_pres.nodes || {})[n.id] || null : null}/>`)}</div>`
      : html`<div class="allclear">No servers configured in fleet.json.</div>`}

    ${fleetSel.length ? html`<${Fragment}>
      ${secTitle("Distribution", html`${scoped ? "selected nodes" : "whole fleet"} · ${DASH_RANGES.find(r => r[0] === effRange)[1].toLowerCase()}`)}
      <${DashDoughnuts} selIds=${selIds} range=${effRange} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length ? html`<${Fragment}>
      ${secTitle("Traffic flow map", "signal flow · by category")}
      <${FlowMap2} selIds=${selIds} range=${effRange} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length > 1 ? html`<${Fragment}>
      ${secTitle(anyTraffic ? "Top nodes by traffic" : "Top nodes by peers", anyTraffic ? (DASH_RANGES.find(r => r[0] === effRange) || ["", "live"])[1].toLowerCase() : "")}
      <div class="rankcard"><${RankBars} rows=${rankRows}/></div>
    <//>` : null}

    ${talkerRows.length ? html`<${Fragment}>
      ${secTitle("Top talkers", dRanged ? (DASH_RANGES.find(r => r[0] === effRange) || ["", ""])[1].toLowerCase() + " · by volume" : "by live throughput")}
      <div class="rankcard"><${RankBars} rows=${talkerRows}/></div>
    <//>` : null}

    ${catRows.length ? html`<${Fragment}>
      ${secTitle("Top destinations", html`${dRanged ? (DASH_RANGES.find(r => r[0] === effRange) || ["", "live"])[1].toLowerCase() : "live"} · categories overlap${(totClientRx + totClientTx) ? (() => { const f = dRanged ? fmtBytes : rate, [d, u] = dlul(totClientRx, totClientTx); return html` · of <span style="color:var(--online)">↓${f(d)}</span> and <span style="color:var(--rate-up)">↑${f(u)}</span> total`; })() : ""}`)}
      <div class="rankcard"><${RankBars} rows=${catRows}/></div>
    <//>` : null}

    ${recent.length ? html`<${Fragment}>
      ${secTitle("Recent activity", null, false)}
      <div class="actlist">${recent.map(e => html`<a class=${"act-row" + (e.click ? "" : " noclk")} href=${e.click ? e.click.href : null} key=${e.key}
          onClick=${e.click && e.click.on ? (ev => { ev.preventDefault(); e.click.on(); }) : (e.click ? null : (ev => ev.preventDefault()))}>
        <span class=${"act-ic t-" + e.slug}><${Ic} i=${e.icon}/></span>
        <span class="act-what">${e.verb}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}
        ${e.detail ? html`<span class="act-detail">${e.detail}</span>` : null}
        <span class="grow"></span><span class="when">${ago(e.ts)}</span>${e.click ? html`<span class="act-arrow"><${Ic} i="arrow"/></span>` : null}</a>`)}</div>
      <div class="act-morewrap"><a class="act-more" href="#/activity">Show all history »</a></div>
    <//>` : null}

    ${secTitle("Needs attention", attnCount ? html`${attnCount} group${attnCount === 1 ? "" : "s"}` : null)}
    ${!attnCount
      ? html`<div class="allclear"><${Ic} i="check"/><span>Everything's deployed and reporting. No drift across the fleet.</span></div>`
      : html`<div class="attn">
          ${statusGroups.map(g => html`<div class="attn-row" key=${"s" + g.status} onClick=${() => revealPeersFiltered({ status: g.status })}>
            <${Badge} s=${g.status}/><span class="name"><b>${g.peers.length}</b> peer${g.peers.length === 1 ? "" : "s"} ${STATUS_WORD[g.status] || g.status}</span>
            <span class="why">${why[g.status] || ""}</span><span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${unGroups.map(g => html`<div class="attn-row" key=${"u" + g.node} onClick=${() => revealPeersFiltered({ node: g.node, status: "unassigned" })}>
            <${Badge} s="unassigned"/><span class="name"><b>${g.peers.size}</b> unassigned peer${g.peers.size === 1 ? "" : "s"} on ${ifCountPhrase(g)} on ${Store.nodeName(g.node)}</span>
            <span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${orphGroups.map(g => html`<div class="attn-row" key=${"o" + g.node + g.iface} onClick=${() => revealOrphans(g.node, g.iface)}>
            <${Badge} s="orphan"/><span class="name"><b>${g.n}</b> orphan peer${g.n === 1 ? "" : "s"} on ${g.iface} (${ifTypeLabel(g.node, g.iface)}) on ${Store.nodeName(g.node)}</span>
            <span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
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
// Quick node→node nav as a pinned SIDE RAIL — the exact Overview node rail (reused via NodesRailPanel), in nav
// mode: the current node highlighted, click navigates. Same markup/CSS as the dashboard's node selector.
function NodeRail({ active }) {
  if ((Store.nodes || []).length < 2) return null;
  // Render at <body> (Portal) so the fixed rail escapes the .screen "rise" transform — otherwise a fixed child of a
  // transformed ancestor is positioned relative to THAT ancestor and rides the 0.32s enter animation into place.
  return html`<${Portal}><div class="dashrail noderail"><div class="dashrail-stack">
    <${NodesRailPanel} nav=${true} active=${active}/>
  </div></div><//>`;
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
    <${NodeRail} active=${name}/>
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><b>${dname}</b></div>
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

    ${nrec.health ? html`<${NodeHealthPanel} name=${name} nrec=${nrec}/>` : null}

    ${nrec.health_history ? html`<${NodeThroughput} name=${name} nrec=${nrec}/>` : null}

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
        const canOpen = !reprov && !!ifn && !blocked;   // node unavailable (converting / down / mid-proc) → dim + not editable, matching the interface/turn cards
        return html`<div key=${peer} class=${"ifcard tp" + (canOpen ? " clickable" : "") + (muted ? " down" : "") + (blocked ? " locked" : "")} onClick=${canOpen ? () => openConnectionEdit(name, ifn) : null}>
          <div class="ifcard-top"><span class="iftype turn" style=${"--tfc:" + col}><${Ic} i="server"/></span><span class="ifname">${Store.nodeName(peer)}</span><span class="grow"></span>${smartCarried.length ? html`<span class="egb egb-smart" title=${"Smart cascade: routes selected destinations out via " + Store.nodeName(peer)}><${Ic} i="cascade"/>smart cascade</span>` : carried.length ? html`<span class="egb egb-cascade" title=${"Cascade: relays " + carried.length + " interface" + (carried.length === 1 ? "" : "s") + " out via " + Store.nodeName(peer)}><${Ic} i="cascade"/>cascade</span>` : null}${reprov ? html`<span class="tg tg-busy" title="Rebuilding this node's mesh link — it reconnects in a few seconds"><${Ic} i="clock"/>re-provisioning</span>` : html`<span class=${"lkdot " + lk} title=${lkTitle}></span>`}</div>
          <div class="ifcard-rows">
            <div class="ifrow"><span class="l">Endpoint</span><span class="r addr">${(m && m.peer_endpoint) || "—"}</span></div>
            <div class="ifrow"><span class="l">Tunnel</span><span class="r addr">${(m && m.subnet) || "—"}</span></div>
            ${carried.length ? html`<div class="ifrow"><span class="l">Carrying</span><span class="r"><span class="carry-tags">${carried.map(k => html`<span class=${"tg tg-" + ((meta[k].awg_params && Object.keys(meta[k].awg_params).length) ? "awg" : "wg")}>${k}</span>`)}</span></span></div>` : null}
          </div></div>`;
      })}</div>
    <//>` : null}

    <${Panel} icon="globe" title="User interfaces" tone="ready" count=${userKeys.length}
        actions=${html`<${Fragment}>${turnEnabled() && nrec.turn_manage && !hasTurns ? html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : "Set up the node's first turn-proxy"} onClick=${() => openSetupTurn(name)}><${Ic} i="plus"/> Setup turn-proxy</button>` : null}<button class="btn btn-mini ico" title="Interface defaults in Settings → Interfaces" onClick=${() => goSettings("defaults")}><${Ic} i="gear"/></button><button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openOnboardIface(name)}><${Ic} i="plus"/> Create new interface</button><//>`}>
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
              // `.down` = THIS interface needs attention or is in flight. Node-wide states (offline, converting,
              // re-installing, updating) are `.locked` instead — nothing is wrong with the interface, it just
              // can't be edited, and every card on the page gets it at once. `iconverting`/`nodeStale` moved out
              // of here into `blocked` for exactly that reason.
              const idim = deleting || idown || istopped || irestarting || iopBusy || !!iprog || !!(nrec.cmd_errors || {})[ifn];
              return html`<a key=${ifn} class=${"ifcard" + (deleting ? " pending" : "") + (idim ? " down" : "") + (blocked ? " locked" : "") + it.cls} href=${"#/node/" + encodeURIComponent(name) + "/" + encodeURIComponent(ifn)} draggable=${false} data-rid=${it.rid}>
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
    <${NodeRail} active=${node}/>
    <div class="crumb"><a href="#/nodes">Nodes</a><span class="sep">/</span><a href=${"#/node/" + encodeURIComponent(node)}>${dname}</a><span class="sep">/</span><b>${iface}</b></div>
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

    ${meta ? html`<${IfaceThroughput} node=${node} iface=${iface}/>` : null}

    ${turnEnabled() ? html`<${TurnProxiesBlock} node=${node} nrec=${nrec} metas=${Store.describe[node] || {}} title="Reachable via turn-proxy" iface=${iface}/>` : null}

    <${Panel} icon="users" title="Peers on this interface" count=${peers.length} pad=${false}
        lead=${html`<div class="search hdr"><${Ic} i="search"/><input placeholder="Search title, user, address…" value=${q} onInput=${e => setQ(e.target.value)}/></div>`}
        actions=${html`<button class="btn btn-mini" disabled=${blocked} title=${blocked ? "Unavailable while the node is down / converting" : ""} onClick=${() => openCreatePeer({ node, iface, lock: true })}><${Ic} i="plus"/> Add peer</button>`}>
      <${PeerGrid} rows=${ifaceFiltered} agg=${false} node=${node} iface=${iface} shownByPeer=${ifaceShown} q=${q} blocked=${blocked}/>
    <//>

    ${orphans.length ? html`<div id="iface-orphans"><${Panel} icon="warn" title="Unmanaged on this interface" tone="warn" pad=${false}
        actions=${html`<button class="btn btn-mini" onClick=${() => orphans.forEach(o => mutate({
          key: "orphan:" + o.node + "|" + o.iface + "|" + o.pubkey,
          call: () => api.peerAdopt({ pubkey: o.pubkey, psk: o.preshared_key || "", target: { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] } }),
        }))}><${Ic} i="link"/> Adopt all</button>`}>
      <table><tbody>
        ${orphans.map(o => html`<${OrphanRow} key=${o.node + "|" + o.iface + "|" + o.pubkey} o=${o}/>`)}
      </tbody></table>
    <//></div>` : null}
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
// Curated "Recommended presets" — MUST stay in sync with CURATED_PRESETS in swg-panel-server (id + label + order).
const SMART_CATEGORIES = [
  ["google", "Google"], ["youtube", "YouTube"], ["telegram", "Telegram"], ["netflix", "Netflix"],
  ["meta", "Meta (FB / IG / WA)"], ["twitter", "X (Twitter)"], ["tiktok", "TikTok"], ["discord", "Discord"],
  ["yandex", "Yandex"], ["vk", "VK"], ["openai", "ChatGPT (OpenAI)"], ["claude", "Claude (Anthropic)"],
  ["grok", "Grok (xAI)"], ["gemini", "Gemini (Google AI)"], ["copilot", "Microsoft Copilot"], ["signal", "Signal"],
  ["spotify", "Spotify"], ["twitch", "Twitch"], ["disney", "Disney+"], ["reddit", "Reddit"], ["github", "GitHub"],
  ["ru_net", "Russia — all IPs"], ["ru_gov", "Russia — Government"], ["ru_banks", "Russia — Banks"],
  ["ru_blocked", "Russia — Blocked (all)"], ["ru_blocked_media", "Russia — Blocked (media)"],
  ["all", "All traffic (catch-all)"],
];
const CURATED_HEAVY = { ru_blocked: 1, ru_net: 1 };   // UI weight flag — large lists
const SMART_CAT_LABEL = Object.fromEntries(SMART_CATEGORIES);
const CAT_UNCAT_COLOR = "#8A94A6";   // muted slate — the "everything else" catch-all, deliberately off-palette
// HSL→hex, no deps.
function hsl2hex(h, s, l) {
  s /= 100; l /= 100;
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => { const c = l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1)); return Math.round(255 * c).toString(16).padStart(2, "0"); };
  return "#" + f(0) + f(8) + f(4);
}
// Colour for a ranked bar by its ROW INDEX: a golden-angle hue rotation (~137.5° per step) so consecutive rows
// are always far apart on the wheel — adjacent bars can never look similar, at ANY list length (so the count is
// free to be configurable). Talkers and destinations use a different start hue + saturation so the two lists read
// as distinct colour families.
const dashRankColor = (i, kind) => kind === "talker" ? hsl2hex((205 + i * 137.508) % 360, 68, 62) : hsl2hex((32 + i * 137.508) % 360, 58, 55);
// labels for catalog categories the CatPicker has fetched this session — lets a just-added (staged, not yet
// saved+polled) catalog cat show its provider label immediately, before Store.catLabels carries it.
const _CATALOG_LABEL_CACHE = {};
// If a resolved label has NO capital letters (a bare list name like "timeweb"), capitalise its first letter —
// but leave intentional casing alone ("iCloud", "YouTube" stay as-is).
const capFirst = s => (typeof s === "string" && s && !/[A-Z]/.test(s)) ? s.charAt(0).toUpperCase() + s.slice(1) : s;
function catLabelOf(c) {   // built-in label · custom-list title (keyed by the list's id AND name, so whichever the node emits resolves to the human title) · inline custom → "Custom" · else the id
  if (c === "uncat") return "Uncategorised";
  const lt = {};
  (Store.panelSettings?.custom_lists || []).forEach(l => { if (l && l.title) { if (l.id) lt[l.id] = l.title; if (l.name) lt[l.name] = l.title; } });
  if (isProviderCat(c)) return capFirst(prettyCatLabel(c, (Store.catLabels || {})[c] || _CATALOG_LABEL_CACHE[c]));   // provider list → humanised (country names etc.)
  return capFirst(SMART_CAT_LABEL[c] || (Store.catLabels || {})[c] || lt[c] || _CATALOG_LABEL_CACHE[c] || (String(c).startsWith("custom") ? "Custom" : c));
}
// Host/IP capability flags for a list — ALWAYS Host first, IP second (house rule).
const capBadges = caps => html`<span class="capbs">
  ${caps && caps.host ? html`<span class="capb host" title="Matchable by domain — needs Force-DNS or SNI mode">Host</span>` : null}
  ${caps && caps.ip ? html`<span class="capb ip" title="Matchable by IP range — works in every mode">IP</span>` : null}</span>`;
// A provider-catalog id is "<prov>:<rawid>"; return the provider's display label (MetaCubeX / v2fly / …) for the source tag.
const isProviderCat = c => typeof c === "string" && c.includes(":") && !String(c).startsWith("custom");
// A "Curated" category = one of the panel's own hand-maintained built-in sets (bare id, no ":"). These are presented
// as the first-class "Curated" provider — the old "built-in" concept, retired. ("all" is the catch-all, not a list.)
const isCuratedCat = c => typeof c === "string" && !c.includes(":") && c !== "all" && c !== "custom" && !String(c).startsWith("custom") && SMART_CAT_LABEL[c] != null;
// The provider a category belongs to: "<prov>" for a namespaced catalog id, "curated" for a built-in, else "".
const providerOf = c => isProviderCat(c) ? String(c).split(":")[0] : (isCuratedCat(c) ? "curated" : "");
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
  xai: "Grok / xAI", grok: "Grok / xAI", anthropic: "Claude / Anthropic", claude: "Claude / Anthropic",
  gemini: "Gemini (Google AI)", perplexity: "Perplexity AI", deepseek: "DeepSeek", copilot: "Microsoft Copilot",
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
  claude: "Claude & the Anthropic API", grok: "Grok (xAI) — grok.com & x.ai",
  gemini: "Google Gemini AI — kept separate from the rest of Google", copilot: "Microsoft & GitHub Copilot",
  signal: "Signal private messenger",
  ru_net: "The whole Russian IP space (GeoIP) — works in every mode",
  ru_blocked: "Sites blocked inside Russia — comprehensive (~86k domains, heavy)",
  ru_blocked_media: "News / media blocked inside Russia — light subset (~130)",
};
const catDescOf = id => CAT_DESC[catRawId(id).toLowerCase()] || "";
// Info icon that shows a description bubble on hover — used for curated presets (which have no external URL to link).
const DescInfo = ({ text }) => text ? html`<span class="catrow-info descinfo" tabindex="0" role="note" onClick=${e => e.stopPropagation()}>
  <${Ic} i="info"/><span class="descbub" role="tooltip">${text}</span></span>` : null;
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
function CatalogRow({ it, added, onPick }) {
  const [info, setInfo] = useState(() => _LIST_INFO_CACHE[it.id] || null);
  useEffect(() => {   // one synchronous (server-side, retried) fetch → counts + samples; caches so paging is instant
    if (info) return; let live = true;
    api.listInfo(it.id).then(r => { const d = r && r.ok ? r.data : { err: true }; _LIST_INFO_CACHE[it.id] = d; if (live) setInfo(d); })
      .catch(() => live && setInfo({ err: true }));
    return () => { live = false; }; }, [it.id]);
  const title = prettyCatLabel(it.id, it.label), rid = catRawId(it.id), desc = catDescOf(it.id);
  const hostD = info && info.tiers && info.tiers.host, ipD = info && info.tiers && info.tiers.ip;
  const summary = sizeSummary((hostD && hostD.n) || 0, (ipD && ipD.n) || 0);
  const samples = ((hostD && hostD.sample) || (ipD && ipD.sample) || []).slice(0, 4);
  const more = (((hostD && hostD.n) || (ipD && ipD.n) || 0) > samples.length);
  const anyFailed = info && info.tiers && Object.keys(info.tiers).some(t => info.tiers[t].failed);
  const empty = info && !info.err && !summary && !samples.length && !anyFailed;   // resolved to 0 routable records
  const sub = desc || (samples.length ? "e.g. " + samples.join(", ") + (more ? "…" : "")
    : (!info ? "loading…" : anyFailed ? "couldn't load — will retry" : empty ? "no routable records" : "—"));
  return html`<button type="button" class=${"catrow" + (added ? " sel" : "") + (empty ? " off" : "")} disabled=${empty} title=${empty ? "This list has no routable records" : ""} onClick=${() => !empty && onPick(it.id)}>
    <span class=${"catpick-tick" + (added ? " on" : "")}>${added ? "✓" : ""}</span>
    <div class="catrow-main">
      <div class="catrow-l1"><span class="catrow-title">${title}</span>${rid.toLowerCase() !== title.toLowerCase() ? html`<span class="catrow-id">${rid}</span>` : null}${CURATED_HEAVY[it.id] ? html`<span class="catrow-heavy" title="Large list — noticeable memory / reload on any node that routes it">heavy</span>` : null}</div>
      ${sub ? html`<div class="catrow-l2">${desc ? html`<span class="catrow-desc">${desc}</span>` : null}${desc && samples.length ? html`<span class="catrow-eg"> · e.g. ${samples.join(", ")}${more ? "…" : ""}</span>` : (!desc ? html`<span class="catrow-eg">${sub}</span>` : null)}</div>` : null}
    </div>
    <div class="catrow-right">
      <${ProvTag} id=${it.id} label=${it.provider_label || provLabelOf(it.id)}/>${capBadges(it.caps)}${summary ? html`<span class="catrow-size">${summary}</span>` : null}
      ${catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title="View this list on GitHub" onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>`
        : html`<${DescInfo} text=${catDescOf(it.id)}/>`}</div>
  </button>`;
}
function provLabelOf(c) {
  const pid = providerOf(c);
  if (!pid) return "";
  return ((Store.catalogProviders || []).find(p => p.id === pid) || {}).label || (pid === "curated" ? "Curated" : pid);
}
// Each provider gets a distinct colour (default palette + a Panel-settings per-mode override, like turn forks).
const CAT_PROVIDER_DEFAULTS = { mc: { color: "#5B8FF9", colorL: "#2C6FD6" }, v2: { color: "#61DDAA", colorL: "#1E9E6E" },
  ls: { color: "#F6BD16", colorL: "#B8890A" }, rf: { color: "#E8684A", colorL: "#C2452A" }, bm: { color: "#B07BE0", colorL: "#8347C0" },
  curated: { color: "#E85D9E", colorL: "#C43B7E" } };   // "Curated" — the panel's own maintained set (rose; distinct from every fetched provider)
function providerColor(prov) {
  const ov = (Store.panelSettings && Store.panelSettings.provider_colors) || {};
  const d = CAT_PROVIDER_DEFAULTS[prov] || (prov === "custom" ? { color: "#8A94A6", colorL: "#5E6875" } : { color: "#8FA8C0", colorL: "#5E7085" });
  return pickThemed(ov[prov], d.color, d.colorL);
}
// The app-wide on/off switch (34×19). Used for every enable/disable toggle in Settings.
const Switch = ({ on, onChange, title, disabled }) => html`<label class=${"swt" + (disabled ? " swt-off" : "")} title=${title || ""}>
  <input type="checkbox" checked=${!!on} disabled=${!!disabled} onChange=${e => onChange(e.target.checked)}/><span class="track"></span><span class="knob"></span></label>`;
// Provider source tag — colour-coded by provider. Curated built-ins and catalog cats both get a coloured chip;
// only genuinely source-less chips (a raw "Custom" label) stay plain. `plain` forces the neutral chip.
function ProvTag({ id, label, plain }) {
  const prov = providerOf(id);
  if (plain || !prov) return html`<span class="catpick-src legacy">${label}</span>`;
  return html`<span class="catpick-src" style=${"--pc:" + providerColor(prov)}>${label || provLabelOf(id)}</span>`;
}
// Routing-mode metadata: icon + labels + the full explanation (shown in the mode banner).
// NOTE: all three modes are kernel-based — there is NO "Kernel" mode. The IP-only mode is "Default". (Stored value
// stays "kernel"|"forcedns"|"sni" — the node reads it — but never DISPLAY the word "Kernel".) See MODES for the text.
// Each entry is framed as an OPTIONAL host-matching layer ON TOP of the always-on IP base: `adds` = what the layer
// does, `bene` = its upside (+), `cost` = its trade-off (−), `exp` = the full description under the selected card.
const MODE_META = {
  kernel:   { icon: "globe",  label: "Default routing", short: "IP only", tag: "no host layer",
    adds: "Just the always-on IP layer — no domain matching added",
    bene: ["Simplest & most robust · never touches DNS · carries all traffic (calls, UDP, QUIC)"],
    cost: "Can't separate services that share IPs (YouTube vs Google), no Host routing",
    exp: "Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it.",
    lists: ["GeoIP", "Custom IPs / ASNs"] },
  forcedns: { icon: "compass", label: "Force-DNS", short: "Host via DNS", tag: "host layer · via DNS",
    adds: "Adds domain matching by resolving your clients' DNS through the node",
    bene: ["Per-service precise · fills before the first connection (no first-hit miss)"],
    cost: "Intercepts & downgrades client DNS — blocks their DoH / DoT",
    exp: "The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past.",
    lists: ["GeoSite", "GeoIP", "Custom IPs/Domains/ASNs"] },
  sni_kernel: { icon: "cpu", label: "Kernel SNI", short: "Host via SNI", tag: "host layer · SNI in-kernel",
    adds: "Scans the TLS SNI in-kernel — client DNS stays private",
    bene: ["Daemonless & parallel per-CPU · lightest at high connection rates",
           "Wins stability and high-connection-rate CPU over Hybrid"],
    cost: "Substring match only (no regex) · needs xt_string + ipset on the node",
    exp: "Scans the SNI from each TLS handshake entirely in the kernel (xt_string) and learns each destination's IP into the routing set — no userspace helper, and your clients' DNS (DoH, DoT or plain) is never touched. Runs in parallel across CPUs, so it stays light even at high connection rates. Matches by substring only (no regex) and needs the node's kernel to provide xt_string + ipset. Names hidden by ECH, and QUIC / HTTP3, fall back to IP routing.",
    lists: ["GeoSite", "GeoIP", "Custom IPs/Domains/ASNs"] },
  sni:      { icon: "eye", label: "Hybrid SNI", short: "Host via SNI", tag: "host layer · SNI in userspace",
    adds: "Parses the TLS SNI in a small helper — client DNS stays private",
    bene: ["Precise parsed-SNI matching · regex-capable · unbothered by big lists",
           "Has fewer kernel deps, wins accuracy and large-list CPU cost over Kernel"],
    cost: "Runs a helper process (fails open — learning pauses — if it stops)",
    exp: "Routes by hostname by parsing the SNI from each TLS handshake in a small userspace helper, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Parses the real SNI field (precise, regex-capable, fine with very large lists). Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing.",
    lists: ["GeoSite", "GeoIP", "Custom IPs/Domains/ASNs"] },
};
// Reusable styled dropdown — a drop-in for a native <select> so every dropdown in the app shares one look (the
// OS-rendered <select> option list can't be styled, hence this). `options` is a flat [{value,label,disabled}] or
// grouped [{group,items:[…]}]. `short(label)` optionally shortens the CLOSED label (e.g. cut at a comma).
function Dropdown({ value, onChange, options, className, placeholder, disabled, short }) {
  const [open, setOpen] = useState(false), [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null);
  const flat = (options || []).flatMap(o => o.items ? o.items : [o]);
  const cur = flat.find(o => String(o.value) === String(value));
  const curLabel = cur ? (short ? short(cur.label) : cur.label) : (placeholder || "");
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12; const flip = below < 240 && above > below;
    setPos({ left: Math.round(r.left), top: Math.round(flip ? r.top - 4 : r.bottom + 4), width: Math.round(r.width), flip, maxh: Math.max(180, Math.round(flip ? above : below) - 16) }); };
  useEffect(() => { if (!open) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) setOpen(false); };
    const onKey = e => { if (e.key === "Escape") { setOpen(false); _blurActive(); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true); document.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const opt = o => html`<button type="button" disabled=${o.disabled} class=${"ddopt" + (String(o.value) === String(value) ? " sel" : "") + (o.disabled ? " off" : "")}
    onClick=${() => { if (o.disabled) return; onChange(o.value); setOpen(false); }}>${o.label}</button>`;
  return html`<div class=${"dropdown " + (className || "")} ref=${ref}>
    <button type="button" class=${"ddbtn" + (open ? " on" : "")} disabled=${disabled} onClick=${() => !disabled && setOpen(o => !o)}>
      <span class="ddlbl">${curLabel}</span><span class="catpick-caret">▾</span></button>
    ${open && pos ? html`<${Portal}><div ref=${popRef} class=${"ddpop" + (pos.flip ? " flip" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;min-width:" + pos.width + "px;--ddmaxh:" + pos.maxh + "px"}>
      ${(options || []).map(o => o.items ? html`<div class="ddgrp">${o.group}</div>${o.items.map(opt)}` : opt(o))}
    </div><//>` : null}
  </div>`;
}
// Match-mode picker — a compact row of four icons (IP · Force-DNS · Kernel-SNI · Hybrid-SNI); the selected one is
// highlighted in its mode colour and its full detail card renders below (see the routing banner). Icon-only keeps
// it tight; the tooltip + the detail card carry the names, so no per-option text is needed here.
function ModeTabs({ value, onChange }) {
  return html`<div class="rmode-tabs" role="radiogroup">
    ${["kernel", "forcedns", "sni_kernel", "sni"].map(m => { const mm = MODE_META[m], on = m === value;
      return html`<button type="button" role="radio" aria-checked=${on} key=${m} title=${mm.label}
        class=${"rmtab m-" + m + (on ? " on" : "")} onClick=${() => onChange(m)}><${Ic} i=${mm.icon}/></button>`; })}
  </div>`;
}
// Full-width detail for the currently-selected mode (icon + name + tag, what it adds, +benefit / −trade-off, full text).
// Operator recovery: wipe a node's smart-routing state (tables, learned IPs, cached lists), then let it rebuild from
// scratch + re-pull every enabled/curated list from the panel. Destructive → modal confirm, never a browser popup.
function resetRouting(node, name) {
  openModal(html`<${ResetRoutingSheet} node=${node} name=${name || "node"}/>`);
}
// Two-scope reset: "learned" clears only the node's SNI-learned IPs; "all" wipes tables + learned IPs + list cache
// and rebuilds/re-pulls. Each button is gated by its own typed token ("RESET LEARNED" / "RESET ALL").
function ResetRoutingSheet({ node, name }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const t = typed.trim();   // case-sensitive: the tokens must be typed in CAPS exactly
  const learnOk = t === "RESET LEARNED", allOk = t === "RESET ALL";
  const run = async scope => {
    if (busy) return; setBusy(true);
    const r = await api.routingReset({ id: node, scope });
    if (r && r.ok === false) toast(r.error || "Reset failed.", "err", 4500);
    else toast(scope === "learned"
      ? "Learned IPs cleared — the node forgets them and re-learns on its next sync."
      : "Routing reset queued — the node wipes, rebuilds and re-pulls on its next sync.", "ok");
    closeModal();
  };
  return html`<${Sheet} title=${"Reset routing · " + name} onClose=${closeModal}
    foot=${html`<${Fragment}><span class="grow"></span>
      <button class="btn btn-ghost" onClick=${closeModal}>Cancel</button>
      <button class="btn btn-warn" disabled=${busy || !learnOk} onClick=${() => run("learned")}><${Ic} i="refresh"/> Reset learned IPs</button>
      <button class="btn btn-danger" disabled=${busy || !allOk} onClick=${() => run("all")}><${Ic} i="refresh"/> Reset all routing</button></>`}>
    <div class="notice warn"><${Ic} i="warn"/><span><b>Reset learned IPs</b> clears only the IPs this node has learned from SNI so far — its tables and lists stay in place and it re-learns as traffic flows. <b>Reset all routing</b> wipes the smart-routing tables, learned IPs and cached lists, then rebuilds from scratch and re-pulls every list from the panel; routing may blip for a few seconds.</span></div>
    <label class="confirm-type"><span>Type <b class="ct-learn">RESET LEARNED</b> or <b class="ct-all">RESET ALL</b> to confirm your action</span>
      <input class="ctype-input" type="text" autofocus spellcheck="false" autocomplete="off" placeholder="RESET LEARNED / RESET ALL" value=${typed}
        onInput=${e => setTyped(e.target.value)}/></label>
  <//>`;
}
// Live host-layer health for a node, from its reported smartroute: is the mode's fill engine actually alive (swg-sni
// for SNI, dnsmasq for Force-DNS), plus the SNI first-hit reset count. Surfaces a SILENT host-layer failure (dead
// reader ⇒ host categories quietly stop routing). Hidden for IP-only and for nodes too old to report it (no false alarms).
function HostHealth({ node, mode, learn, onLearn }) {
  if (mode === "kernel") return null;
  const sr = (Store.stats[node] || {}).smartroute || {};
  if (!sr.mode) return null;                                  // node hasn't reported host-layer health yet → don't guess
  const eng = sr.engine || "";                                // ACTUAL running engine (may differ from configured — see degrade)
  const label = eng === "dns" ? "DNS resolver" : eng === "sni_kernel" ? "SNI scanner" : "SNI parser";
  const ok = sr.engine_ok !== false;
  let extra = null, note = null;
  if (eng.startsWith("sni") && sr.resets) extra = sr.resets + " new host" + (sr.resets === 1 ? "" : "s") + " rerouted";
  if (mode === "sni_kernel" && eng === "sni_user") note = "kernel SNI scanner unavailable — running userspace SNI parser";   // degraded-open
  return html`<div class=${"rmode-health " + (ok ? "ok" : "down")}>
    <span class="rmh-dot"></span><b>${label}</b> <span>${ok ? "healthy" : "down — host routing degraded"}</span>
    ${extra ? html`<span class="rmh-sep">·</span><span>${extra}</span>
      ${onLearn ? html`<button class=${"learn-toggle" + (learn ? " on" : "")} title=${"IP learning is " + (learn ? "ON — the node remembers each learned IP" : "OFF — routing stays fresh, no remembered IPs") + " · click to turn it " + (learn ? "off" : "on")} onClick=${() => onLearn(!learn)}><${Ic} i="database"/></button>` : null}
      <${Popover} hoverOnly cls="rmh-info" popCls="rmode-info-pop" trigger=${html`<span class="rmh-infobtn"><${Ic} i="info"/></span>`}>
        <div class="rmode-info-body">A host's name is only visible once its connection starts, so the <b>first</b> connection to a brand-new host has already left on the default path before it can be routed. The engine learns that host's IP and <b>resets that one connection</b> so the client instantly reconnects on the correct route — that's the <b>new hosts rerouted</b> count; every later connection matches by IP and is never reset.<div style="margin-top:9px">The <b>records</b> toggle (the database icon) controls <b>IP learning</b>. Each IP is remembered by <b>category</b> (not by domain), so it stays valid even if you later change that category's lists or custom domains. Nothing is kept forever: <b>On</b> (default) holds a learned IP for about <b>1 hour</b>, so repeat connections route instantly. <b>Off</b> keeps the node <b>fresh</b> — an IP is held only about <b>2 minutes</b>, so a host whose address rotates is never routed on a stale IP (at a little extra CPU, as more connections are re-scanned). Once it expires, the IP is simply re-learned on the next connection.</div></div>
      <//>` : null}
    ${note ? html`<span class="rmh-note">${note}</span>` : null}
  </div>`;
}
// "on N/M nodes ▾" fleet-assignment popover — toggle a list on each node. disabledFor(nid) → a reason string greys it.
function FleetAssign({ nodes, isOn, onToggle, disabledFor }) {
  const on = (nodes || []).filter(n => isOn(n.id)).length;
  return html`<${Popover} cls="fleetassign" popCls="fleetpop"
    trigger=${html`<span class="fleet-trig">on <b>${on}</b>/${(nodes || []).length} <span class="fleet-caret">▾</span></span>`}
    children=${html`<div class="fleetlist"><div class="fleetlist-h">Enabled on</div>${(nodes || []).map(n => { const dis = disabledFor && disabledFor(n.id);
      return html`<div class=${"fleetrow" + (dis ? " off" : "")} title=${dis || ""}>
        <span class="fleet-dot" style=${"--c:" + Store.nodeColor(n.id)}></span><span class="fleet-nm">${n.name}</span><span class="grow"></span>
        <${Switch} on=${isOn(n.id)} disabled=${!!dis} onChange=${v => onToggle(n.id, v)}/></div>`; })}</div>`}/>`;
}
// Per-category match capability, shipped by /api/state (Store.smartCaps). ip = matchable by geoip (works in
// EVERY routing mode); host = matchable by domain via the node's dnsmasq (needs DNS → forcedns). A
// host-ONLY category (youtube today) is dead weight in kernel mode, so the UI greys/hides it there.
const catCap = id => (Store.smartCaps || {})[id] || { ip: false, host: false };
const catHostOnly = id => { const c = catCap(id); return c.host && !c.ip; };
const catUsableInMode = (id, mode) => mode === "kernel" ? catCap(id).ip : (catCap(id).ip || catCap(id).host);
const catDoms = id => (Store.catDomains || {})[id] || [];   // curated domains for a host category (empty for geoip/fetched cats)
// hover bubble listing a list's domains/IPs (only when there are some); `note` = a faint footer caption
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
function CatPicker({ value, mode, customLists, catalogCats, listTitle, onChange, onAdd, addMode, selected, triggerLabel, primary }) {
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
    if (addMode) {   // the catalog browser spans the FULL card width (grid-wide), anchored under its header row
      const card = el.closest(".card") || el.closest(".setpane");
      const cr = card ? card.getBoundingClientRect() : r; const pad = 18;
      const flip = below < 360 && above > below;
      setPos({ left: Math.round(cr.left + pad), top: Math.round(flip ? r.top - 4 : r.bottom + 6),
        width: Math.round(cr.width - pad * 2), flip, wide: true, maxh: Math.max(300, Math.round(flip ? above : below)) });
      return;
    }
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
    const onKey = e => {
      if (e.key === "Escape") { setOpen(false); ref.current && ref.current.focus(); return; }
      // start typing anywhere while the dropdown is open (focus outside the box) → clear the box + focus it + start a
      // FRESH search with the typed char, so you can search → select → search again without re-clicking the field.
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && inRef.current && document.activeElement !== inRef.current) {
        e.preventDefault();
        inRef.current.focus();
        setQ(e.key); setPage(0);
      }
    };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true); document.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); document.removeEventListener("keydown", onKey); };
  }, [open]);
  // Focus-on-open is done via the input's ref-callback (fires exactly when the input MOUNTS — robust against the
  // Portal render timing that made `[open]`/`[pos]` effects miss the very first open). `focusGuard` fires it once
  // per open. Reset when the popover closes.
  const focusGuard = useRef(false);
  const sessionPicked = useRef(false);   // addMode: did the operator add/toggle anything this open session? (drives Enter-to-close)
  useEffect(() => { if (!open) { focusGuard.current = false; sessionPicked.current = false; } }, [open]);
  const pick = id => { if (addMode) sessionPicked.current = true; onChange(id); if (addMode) return; setOpen(false); setQ(""); setPage(0); };   // addMode stays open for multi-add
  const capBadge = capBadges;   // shared Host-first renderer (defined near catLabelOf)
  // addMode: filter the full index by title/id/description, sort by readable title, paginate 40/page locally.
  const per = 40;
  const _aq = q.trim().toLowerCase();
  // Curated "Recommended presets" — pinned above the provider catalog, always shown in full (only ~26).
  const _curatedAll = addMode ? SMART_CATEGORIES.filter(([id]) => id !== "all")
    .map(([id, label]) => ({ id, provider: "curated", provider_label: "Curated", caps: catCap(id), recommended: true, disp: label })) : [];
  const curatedFiltered = _curatedAll.filter(it => !_aq || it.id.toLowerCase().includes(_aq)
    || it.disp.toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq))
    .sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase()));
  const filtered = addMode && cidx ? cidx.filter(it => { if (!_aq) return true;
    return it.id.toLowerCase().includes(_aq) || catRawId(it.id).toLowerCase().includes(_aq)
      || prettyCatLabel(it.id, "").toLowerCase().includes(_aq) || catDescOf(it.id).toLowerCase().includes(_aq); })
    .map(it => ({ ...it, disp: prettyCatLabel(it.id, "") })).sort((a, b) => a.disp.toLowerCase().localeCompare(b.disp.toLowerCase())) : [];
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / per));
  const items = filtered.slice(page * per, (page + 1) * per);
  const _matchTotal = curatedFiltered.length + total, _firstMatch = curatedFiltered[0] || items[0];
  const lists = customLists || [];
  // Routing picker (non-addMode): TWO sections — Provider lists (the node's opted-in provider-catalog cats, each
  // source-tagged) and Custom lists (your own). Never the full catalog — filtered client-side; add more via Settings.
  // A currently-selected LEGACY built-in (existing rule) is shown under Provider lists so it stays editable.
  const _ql = q.trim().toLowerCase();
  const _match = (id, label) => !_ql || String(label).toLowerCase().includes(_ql) || String(id).toLowerCase().includes(_ql);
  const _provRows = (catalogCats || []).map(c => ({ id: c.id, label: c.title, caps: catCap(c.id), src: provLabelOf(c.id) }));
  if (!addMode && value && !isProviderCat(value) && value !== "custom" && !lists.some(l => l.id === value) && !_provRows.some(r => r.id === value))
    _provRows.push({ id: value, label: catLabelOf(value), caps: catCap(value), src: provLabelOf(value) || "Curated" });   // keep a curated/legacy rule visible + editable, tagged by its provider
  const localGroups = addMode ? [] : [
    { grp: "Provider lists", rows: _provRows.filter(r => _match(r.id, r.label)).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
    { grp: "Custom lists", rows: lists.filter(l => _match(l.id, l.title)).map(l => ({ id: l.id, label: l.title, caps: customCaps(l), src: "Custom", list: l })).sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())) },
  ].filter(g => g.rows.length);
  const localEmpty = !addMode && !localGroups.length && !!_ql;
  return html`<div class=${"catpick" + (addMode ? " catpick-add" : "")} ref=${ref}>
    ${addMode ? html`<button type="button" class=${(primary ? "btn btn-add" : "btn btn-mini") + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}><${Ic} i="plus"/> ${curLabel}</button>`
      : html`<button type="button" class=${"catpick-btn" + (open ? " on" : "")} onClick=${() => setOpen(o => !o)}>
      <span class="catpick-lbl">${curLabel}</span><span class="catpick-caret">▾</span>
    </button>`}
    ${open && pos ? html`<${Portal}><div ref=${popRef} class=${"catpick-pop" + (pos.flip ? " flip" : "") + (pos.wide ? " wide" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;" + (pos.wide ? "width:" + pos.width + "px;" : "min-width:" + Math.max(pos.width, 320) + "px;") + "--catpick-maxh:" + (pos.maxh - 108) + "px"}>
      <div class="catpick-search">
        <${Ic} i="search"/>
        <input ref=${el => { inRef.current = el; if (el && open && !focusGuard.current) { focusGuard.current = true; requestAnimationFrame(() => el.focus()); } }} type="text" placeholder=${addMode ? "Search " + ((cidx && cidx.length) || "") + " lists — name, country, service…" : "Filter this node's lists…"} value=${q}
          onInput=${e => { setQ(e.target.value); setPage(0); }} spellcheck="false" autocomplete="off"
          onKeyDown=${e => { if (e.key === "Enter" && addMode && _matchTotal === 1 && _firstMatch) {   // ONLY when exactly one result:
            e.preventDefault(); e.stopPropagation();
            (onAdd || pick)(_firstMatch.id);   // add-only (never toggles off)
            setOpen(false);
          } /* any other case (0 or many results): Enter does nothing */ }}/>
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
              ${/* A curated preset is a first-class provider ("Curated") but keeps a BARE id, so isProviderCat()
                    alone hid its size: the panel ships cat_sizes for curated cats too (they resolve on the panel,
                    same as provider lists), the row just never asked for it. */
                it.caps ? capBadge(it.caps) : null}${it.list ? html`<${ListInfo} list=${it.list}/>` : ((isProviderCat(it.id) || isCuratedCat(it.id)) ? html`<${ListInfo} cat=${it.id}/>` : null)}
              ${isProviderCat(it.id) && catListUrl(it.id, it.caps) ? html`<a class="catrow-info" href=${catListUrl(it.id, it.caps)} target="_blank" rel="noopener" title="View this list on GitHub" onClick=${e => e.stopPropagation()}><${Ic} i="info"/></a>`
                : (!isProviderCat(it.id) && catDescOf(it.id)) ? html`<${DescInfo} text=${catDescOf(it.id)}/>` : null}</button>`; })}`)}
          ${localEmpty ? html`<div class="catpick-empty">No list on this node matches “${q}”. Add more in Settings → Routing lists.</div>` : null}
        ` : html`
          ${page === 0 && curatedFiltered.length ? html`<div class="catpick-grp">Recommended presets</div>
            ${curatedFiltered.map(it => html`<${CatalogRow} key=${it.id} it=${it} added=${selSet.has(it.id)} onPick=${pick}/>`)}` : null}
          ${total ? html`<div class="catpick-grp">Provider catalog</div>
            ${items.map(it => html`<${CatalogRow} key=${it.id} it=${it} added=${selSet.has(it.id)} onPick=${pick}/>`)}` : null}
          ${cidx == null && !curatedFiltered.length ? html`<div class="catpick-empty">Loading catalog…</div>`
            : _matchTotal === 0 ? html`<div class="catpick-empty">No list matches “${q}”.${cidx && cidx.length === 0 ? html`<br/><span class="faint">Enable a provider in Settings → Geo data to search its catalog.</span>` : ""}</div>` : null}
        `}
      </div>
      ${mode === "kernel" ? html`<div class="catpick-note">Greyed lists match by <b>domain</b> only — this node is <b>IP-only</b> (no host layer). Switch it to Force-DNS or SNI to use them.</div>` : null}
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
        ${r.category === "custom" ? html`<textarea class="rrdoms" rows="1" spellcheck="false" placeholder=${ipOnly ? "IPs / CIDRs / AS numbers (IP-only mode) — e.g. 1.2.3.0/24, AS62041" : "IPs / domains / AS numbers — e.g. youtube.com, 1.2.3.0/24, AS62041"} value=${r.targets || ""} onInput=${e => { autoGrow(e.target); setRule(r._rid, { targets: e.target.value }); }} ref=${el => autoGrow(el)}/>${!splitTargets(r.targets || "").length ? html`<span class="rrlint">add at least one IP${ipOnly ? " or CIDR" : " or domain"}</span>` : badToks.length ? html`<span class="rrlint">not a valid IP, CIDR or domain: ${badToks.join(", ")}</span>` : domToks.length ? html`<span class="rrlint">IP-only mode — ${domToks.slice(0, 3).join(", ")}${domToks.length > 3 ? "…" : ""} ${domToks.length > 1 ? "are domains" : "is a domain"}. Use IPs/CIDRs, or <button type="button" class="linkbtn" onClick=${switchToForceDns}>switch this node to Force-DNS</button>.</span>` : null}` : null}
        ${r.category === "custom" ? html`<${AsnHint} targets=${r.targets}/>` : null}
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
      <button class="xbtn rrfoot-gear" title="Manage routing lists in Settings → Routing lists" onClick=${() => goSettings("routing")}><${Ic} i="gear"/></button>
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
const _RR_ASN = /^as:?\d{1,10}$/i;                  // AS<n> / AS:<n> — the panel resolves it to the ASN's IPv4 prefixes
const _RR_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;   // one DNS label
const splitTargets = raw => String(raw || "").split(/[\s,]+/).filter(Boolean);
function validTarget(tok) {
  const t = String(tok).trim().toLowerCase(); if (!t) return false;
  if (_RR_ASN.test(t)) return true;                 // AS<n> → resolved to CIDRs on the panel (counts as an IP target)
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
const isIpTarget = tok => { const t = String(tok).trim().toLowerCase(); if (_RR_ASN.test(t)) return true; const m = t.match(_RR_IP4); return !!m && [1, 2, 3, 4].every(i => +m[i] <= 255) && (!m[5] || +m[5].slice(1) <= 32); };   // AS<n> resolves to IPs → an IP target
const domainTargets = raw => splitTargets(raw).filter(t => validTarget(t) && !isIpTarget(t));   // real hostnames among the valid tokens (kernel mode can't match these)
// Live feedback for AS<n> tokens in a rule/list: shows "AS62041 → 5 prefixes" (or "not found") so the operator knows
// the ASN resolved. Counts are cached module-wide (keyed by AS number) so switching rows never re-fetches.
const _asnCache = {};
function AsnHint({ targets }) {
  const asns = [...new Set((String(targets || "").match(/\bas:?\d{1,10}\b/gi) || []).map(t => t.replace(/^as:?/i, "")))];
  const [, force] = useState(0);
  useEffect(() => {
    let alive = true;
    asns.forEach(n => { if (_asnCache[n] === undefined) { _asnCache[n] = "loading";
      api.asnCount(n).then(r => { _asnCache[n] = (r && r.ok && r.data) ? r.data : { count: 0 }; if (alive) force(x => x + 1); }); } });
    return () => { alive = false; };
  }, [asns.join(",")]);
  if (!asns.length) return null;
  return html`<div class="asn-hint">${asns.map(n => { const c = _asnCache[n]; const load = c === "loading" || c === undefined;
    const cnt = (c && typeof c === "object") ? c.count : 0;
    return html`<span class=${"asn-tok " + (load ? "load" : cnt ? "ok" : "bad")}>AS${n} ${load ? "resolving…" : cnt ? "→ " + cnt + " prefix" + (cnt === 1 ? "" : "es") : "→ not found"}</span>`; })}</div>`;
}
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
      if (doms.length) return "IP-only mode routes by IP only — remove the domain" + (doms.length > 1 ? "s" : "") + " (" + doms.slice(0, 3).join(", ") + (doms.length > 3 ? "…" : "") + "), or switch this node to Force-DNS.";
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
    foot=${footRow({ onCancel: closeModal, disabled: busy || (!existing && !!egressError(eg, nrec.routing_mode || "kernel")), title: (!existing && egressError(eg, nrec.routing_mode || "kernel")) || "", onAction: save, action: existing ? "Adopt" : "Create" })}>
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
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: "Delete interface" })}>
    <div class="notice warn"><${Ic} i="warn"/><span>This permanently tears down <b>${iface}</b> on the node: the interface goes <b>down</b>, its <b>.conf and server key are removed</b>, and <b>every peer on this interface is destroyed</b>. Peers deployed only here are deleted from the panel and their configs/QRs stop working. This can't be undone.</span></div>
    <div class="field"><label>Type <span class="mono" style="text-transform:none">${phrase}</span> to confirm</label><input autofocus value=${txt} onInput=${e => setTxt(e.target.value)} placeholder=${phrase} autocomplete="off" spellcheck="false"/></div>
  <//>`;
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
  const nodeDown = nodeStale(node) || inProc(nrec.proc_status);   // node not reporting / mid re-install → can't apply a dial change
  const lk = nodeStale(node) ? "down" : (meta.handshake_age == null ? "connecting" : (meta.handshake_age < 180 ? "up" : "down"));
  const lkLabel = { up: "connected", connecting: "connecting", down: "down" }[lk];
  const proto = (meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg";
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
      foot=${footRow({ onCancel: closeModal, disabled: nodeDown, title: nodeDown ? Store.nodeName(node) + " isn't reporting — reconnect it before changing this link" : "", onAction: saveDial, action: "Save" })}>
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
    <div style="margin-top:12px"><${RangedHistory} node=${node} kind="throughput" h=${60} fetch=${r => api.meshSeries(node, peer, r).then(x => x && x.ok ? x.data : {})}/></div>
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
        note=${html`<${SubAutoNote}/>`}
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
    <div class="iface-intro"><div>Changing the <b>endpoint</b> or <b>port</b> will break the existing clients' connections; you will need to re-distribute the configs / QR codes.</div><${SubAutoNote}/></div>
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
  const snap = Store.stats[node] || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";
  // node's PUBLIC endpoint (what clients dial): on a bridge node the reported nrec.ips are container-private (and
  // filtered out), so surface the public endpoint so the LISTEN-IP dropdown offers it — noded rebinds it to
  // 0.0.0.0 inside the netns, so binding "the public IP" works there despite it not being a local container address.
  const epIp = (() => { for (const b of Object.values(snap.interfaces || {})) { const ep = (b.meta || {}).endpoint || ""; if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep; } return ""; })();
  const ips = [...new Set([epIp, (nrec.endpoint_host || "").trim(), ...(nrec.ips || [])].filter(Boolean))];
  const lInit = ips.includes(lh) ? lh : "__custom__";
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? lh : "");
  const [lport, setLport] = useState(lp);
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_"), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // this proxy's fork is fixed here; a WireGuard-only fork can't front an AmneziaWG interface → hide awg ones
  const fork = turnFork(svc);
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const conPort = con.includes(":") ? con.slice(con.lastIndexOf(":") + 1) : con;
  const match = ifaces.find(i => i.port === conPort);
  const [fwd, setFwd] = useState(match ? match.name : "__custom__");
  const [custom, setCustom] = useState(con || "127.0.0.1:");
  const [params, setParams] = useState(tp.params != null ? tp.params : (tp.wrap_key ? "-wrap-key " + tp.wrap_key : ""));
  const [showExec, setShowExec] = useState(false);   // Additional ExecStart params collapsed by default
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
  return html`<${Sheet} title=${html`${turnSheetTitle(turnFork(svc), title)}${installed ? html` <span class="sheet-ver">${installed}</span>` : ""}`} width=${660} headExtra=${html`<${TurnIpsHeader} node=${node} svc=${svc}/>`}
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
    <${RangedHistory} node=${node} kind="throughput" h=${60} fetch=${r => api.turnSeries(node, turnFork(svc), r).then(x => x && x.ok ? x.data : {})}/>
    <div class="iface-intro" style="margin-top:8px">
      <div>Changing any field rewrites the unit's ExecStart on the node and restarts it.</div>
      <div>The parameters below are placed verbatim after <span class="mono">-connect</span> — wrap key, wrap mode, any flags the fork supports.</div>
      <${SubAutoNote}/>
    </div>
    <div class="field"><label>Title <span class="faint" style="text-transform:none;letter-spacing:0">— optional</span></label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder=${turnFork(svc)} autocomplete="off"/></div>
    <div class="row2">
      <div class="field"><label>Listen IP</label>
        <${IpPicker} ips=${ips} sel=${lsel} setSel=${setLsel} custom=${lcustom} setCustom=${setLcustom} placeholder="203.0.113.7"/></div>
      <div class="field"><label>Listen port</label><input value=${lport} onInput=${e => setLport(e.target.value)} placeholder="57000"/></div>
    </div>
    ${lsel === "__custom__" && lhost && !ips.includes(lhost) ? (isBridge
      ? html`<div class="notice" style="margin:-6px 0 16px"><${Ic} i="info"/><span>Bridge node: the proxy binds <span class="mono">0.0.0.0</span> inside the container and this port is published, so enter the node's <b>public</b> IP/host (what clients dial) here.</span></div>`
      : html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This isn't a detected address on the node. The proxy <b>binds</b> to this address — it must be a real IP on the server, or it dies with <span class="mono">bind: cannot assign requested address</span>.</span></div>`) : null}
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
    <button type="button" class="advtoggle" onClick=${() => setShowExec(a => !a)}><span class="advcaret">${showExec ? "▾" : "▸"}</span> Additional ExecStart parameters</button>
    ${showExec ? html`<div class="field">
      <textarea class="ta mono" rows="4" value=${params} onInput=${e => setParams(e.target.value)} placeholder="-wrap-mode on -wrap-key <64 hex chars>" spellcheck="false"></textarea>
      <div class="hint">Free text appended after <span class="mono">-connect ip:port</span>. Changing the wrap key breaks every client using the old one. <button type="button" class="linkbtn" onClick=${randKey}>Copy a random 64-hex key</button></div>
    </div>` : null}
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
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: "Delete turn-proxy" })}>
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
  { id: "samosvalishe", label: "samosvalishe", owner: "samosvalishe/free-turn-proxy", wrap: "-obf-profile rtpopus", keyflag: "-obf-key", color: "#E0A85F", colorL: "#C07A1E" },
  { id: "Moroka8", label: "Moroka8", owner: "Moroka8/vk-turn-proxy", wrap: "-wrap", color: "#E07A9A", colorL: "#C24468" },
  { id: "kiper292", label: "kiper292", owner: "kiper292/vk-turn-proxy", wrap: "", color: "#6FD9A8", colorL: "#12A46B" },
  { id: "anton48", label: "anton48", owner: "anton48/vk-turn-proxy", wrap: "-wrap-srtp", color: "#D9CF5F", colorL: "#8E8420" },
];
// forks whose CLIENT is WireGuard-only — they can't front an AmneziaWG interface, so awg interfaces are hidden
// from their "Forwards to" picker. kiper292 = plain wireguard-go + a config parser that REJECTS awg params;
// anton48 (iOS) has no AmneziaWG fields at all; samosvalishe = free-turn-proxy's FreeTurn app, an integrated
// plain-WireGuard client with no AmneziaWG support (unlike the old sidecar, which relayed UDP to the standalone
// AmneziaWG app). WINGS-N is app-integrated but DOES support awg; the sidecar forks relay UDP transparently.
const TURN_WG_ONLY = new Set(["kiper292", "anton48", "samosvalishe"]);
function forkSupportsAwg(fork) { return !TURN_WG_ONLY.has(fork); }
// stable colour for a turn-proxy fork in the ACTIVE mode (peers connected via it get their badge tinted this);
// a Panel-settings override (turn_fork_colors[id] = {dark,light}) wins over the TURN_FORKS default.
function turnColor(label) {
  const ov = (Store.panelSettings && Store.panelSettings.turn_fork_colors) || {};
  const fk = TURN_FORKS.find(x => x.id === label);
  return pickThemed(ov[label], (fk && fk.color) || "#8FA8C0", (fk && fk.colorL) || "#5E7085");
}
const _forkTag = svc => html`<span class="tg tg-turn" style=${"--tfc:" + turnColor(turnFork(svc))}>${turnFork(svc)}</span>`;
const _lastSeen = last => last ? seen(Math.max(0, Math.floor(Date.now() / 1000) - last)) + " ago" : "—";

// The "Turn IPs" header control on the turn-edit modal: unique client IPs seen connecting to THIS proxy. The
// active count comes from the live snapshot (no fetch); the hover bubble lists them (green dot = online) with a
// Flush that drops the offline ones. `src_ips` is node-collected (ss); history persists on the panel.
function TurnIpsHeader({ node, svc }) {
  const [data, setData] = useState(null);
  const load = () => api.turnIps().then(r => setData(r && r.ok ? ((r.data.nodes || {})[node] || {}) : {})).catch(() => setData({}));
  useEffect(() => { load(); }, [node]);
  const tp = ((Store.stats[node] || {}).turn_proxies || []).find(t => t.service === svc);
  const active = new Set(tp ? (tp.src_ips || []) : []);
  const recs = data || {};
  const ips = new Set([...Object.keys(recs).filter(ip => (recs[ip].by || []).includes(svc)), ...active]);
  const all = [...ips].map(ip => ({ ip, last: (recs[ip] || {}).last, on: active.has(ip) }))
    .sort((a, b) => (a.on === b.on ? (b.last || 0) - (a.last || 0) : a.on ? -1 : 1));
  const rows = all.slice(0, 10);   // show at most 10 here — the full list lives in Settings
  const offlineN = all.filter(r => !r.on).length;   // only OFFLINE recorded IPs are flushable (online are kept)
  const flush = () => openConfirm({ title: "Flush offline recorded IPs", confirmLabel: "Flush", danger: true,
    body: html`Remove ${offlineN} offline recorded IP${offlineN === 1 ? "" : "s"} for <b>this turn-proxy only</b>. Currently-online clients are kept, and other proxies are untouched.`,
    onConfirm: async () => { await api.turnIpsFlush({ node, service: svc }); load(); } });   // service-scoped on the backend → this proxy's offline IPs only
  const openSettings = () => { pendingSettingsSection = "turn"; pendingTurnIpsOpen = true; closeAllModals(); go("#/panel/settings"); };
  const trigger = html`<span class="turnips-hd" onClick=${openSettings}>Turn IPs${active.size ? html` · <b>${active.size}</b>` : ""}</span>`;
  return html`<${Popover} hoverOnly cls="turnips-wrap" popCls="turnips-pop" trigger=${trigger}>
    <div class="onpop-h">Collected VK IPs</div>
    ${rows.length ? html`<${Fragment}>
      ${rows.map(r => html`<div class="tipbub-row" key=${r.ip}><span class=${"tipdot" + (r.on ? " on" : "")}></span><span class="tipbub-ip">${r.ip}</span><span class="grow"></span><span class="tipbub-when">${r.on ? "online" : _lastSeen(r.last)}</span></div>`)}
      ${all.length > rows.length ? html`<div class="tipbub-more">+${all.length - rows.length} more in Settings</div>` : null}
      ${offlineN ? html`<button class="tipbub-flush" onClick=${flush}><${Ic} i="trash"/> Flush offline recorded IPs</button>` : null}
    <//>`
      : html`<div class="tipbub-empty">No connections seen yet.</div>`}
  <//>`;
}

// The "Collected IPs" grid in Settings → Turn proxies: every unique client IP across the fleet's proxies,
// sorted by Last (online first), with per-row delete and a fleet-wide "Flush …" that keeps the online ones.
function TurnCollectedIps() {
  const [show, setShow] = useState(false);   // collapsed by default (advtoggle concept) — fetch on first expand
  const [data, setData] = useState(null);
  const secRef = useRef(null);
  const load = () => api.turnIps().then(r => setData(r && r.ok ? (r.data.nodes || {}) : {})).catch(() => setData({}));
  useEffect(() => { if (show && data === null) load(); }, [show]);
  useEffect(() => {   // deep-linked from a "Turn IPs" header → expand + scroll into view
    if (pendingTurnIpsOpen) { pendingTurnIpsOpen = false; setShow(true); setTimeout(() => secRef.current && secRef.current.scrollIntoView({ behavior: "smooth", block: "center" }), 150); }
  }, []);
  const rows = [];
  for (const [nid, ips] of Object.entries(data || {}))
    for (const [ip, rec] of Object.entries(ips))
      rows.push({ nid, ip, last: rec.last, by: rec.by || [], on: (rec.active_by || []).length > 0 });
  rows.sort((a, b) => (a.on === b.on ? (b.last || 0) - (a.last || 0) : a.on ? -1 : 1));   // default: Last (online first)
  const del = async (nid, ip) => { await api.turnIpsFlush({ node: nid, ip }); load(); };
  const flushAll = () => openConfirm({ title: "Flush recorded IP history", confirmLabel: "Flush", danger: true,
    body: "Flush the collected turn-proxy IP history across the fleet? The currently-online IPs are kept.",
    onConfirm: async () => { await api.turnIpsFlush({}); load(); } });
  return html`<${Fragment}>
    <button type="button" ref=${secRef} class="advtoggle" style="margin-top:18px" onClick=${() => setShow(a => !a)}><span class="advcaret">${show ? "▾" : "▸"}</span> Collected IPs${show && rows.length ? html` <span class="count">${rows.length}</span>` : ""}</button>
    ${show ? html`<${Fragment}>
    <p class="hint" style="margin:8px 0 10px">Unique VK server IPs the nodes collected via turn-proxies.</p>
    ${data === null ? html`<div class="hint">Loading…</div>`
      : rows.length ? html`<${Fragment}>
        <div class="tipgrid">
          <div class="tipgrid-h"><span>Turn IP</span><span>Last</span><span>Collected by</span><span></span></div>
          ${rows.map(r => html`<div class="tiprow" key=${r.nid + "|" + r.ip}>
            <span class="tip-ip"><span class=${"tipdot" + (r.on ? " on" : "")}></span>${r.ip}</span>
            <span class="tip-last">${r.on ? "online" : _lastSeen(r.last)}</span>
            <span class="tip-by">${r.by.map(_forkTag)}</span>
            <button class="xbtn" title="Delete this IP record" onClick=${() => del(r.nid, r.ip)}><${Ic} i="x"/></button>
          </div>`)}
        </div>
        <div class="tipfoot"><button class="btn btn-mini warn" onClick=${flushAll}><${Ic} i="trash"/> Flush turn-proxies history</button></div>
      <//>`
      : html`<div class="hint">No turn-proxy connections collected yet.</div>`}
    <//>` : null}
  <//>`;
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
  const snap = Store.stats[node] || {};
  const isBridge = nrec.kind === "docker" && (nrec.net_mode || "host") === "bridge";
  const epIp = (() => {   // the node's PUBLIC endpoint (what clients dial); on bridge the proxy rebinds it to 0.0.0.0
    for (const b of Object.values(snap.interfaces || {})) {
      const ep = (b.meta || {}).endpoint || "";
      if (ep) return ep.includes(":") ? ep.slice(0, ep.lastIndexOf(":")) : ep;
    }
    return "";
  })();
  // include the public endpoint so bridge nodes (whose reported ips are container-private + filtered) still offer it
  const ips = [...new Set([epIp, (nrec.endpoint_host || "").trim(), ...(nrec.ips || [])].filter(Boolean))];
  const allIfaces = Object.entries(snap.interfaces || {})
    .map(([n, b]) => ({ name: n, port: String((b.meta || {}).listen_port || ""), sys: !!(b.meta || {}).system || n.startsWith("swg_"), awg: !!Object.keys((b.meta || {}).awg_params || {}).length }))
    .filter(i => i.port && !i.sys);   // turn proxies forward to USER interfaces only — never the system/mesh link (swg_*)
  // a WireGuard-only fork can't front an AmneziaWG interface → hide awg interfaces from its picker
  const ifaces = forkSupportsAwg(fork) ? allIfaces : allIfaces.filter(i => !i.awg);
  const hideAwg = !forkSupportsAwg(fork) && allIfaces.some(i => i.awg);
  const lInit = epIp ? (ips.includes(epIp) ? epIp : "__custom__") : (ips[0] || "__custom__");
  const [lsel, setLsel] = useState(lInit);
  const [lcustom, setLcustom] = useState(lInit === "__custom__" ? epIp : "");
  const [lport, setLport] = useState(String(suggestPort(node, "turn")));
  const [fwd, setFwd] = useState(ifaces[0] ? ifaces[0].name : "__custom__");
  const [custom, setCustom] = useState("127.0.0.1:51820");
  const [title, setTitle] = useState("");
  const [wrapKey] = useState(randWrapKey);            // one fresh key, reused so a fork switch is deterministic
  const dflParams = fk => fk.wrap ? (fk.wrap + " " + (fk.keyflag || "-wrap-key") + " " + wrapKey) : "";
  const [params, setParams] = useState(dflParams(FORKS[0] || TURN_FORKS[0]));
  const [showExec, setShowExec] = useState(false);   // Additional ExecStart params collapsed by default
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
    foot=${footRow({ onCancel: closeModal, disabled: busy || (mode === "new" && !FORKS.length), onAction: save, action: mode === "existing" ? "Adopt" : "Install" })}>
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
      ${lsel === "__custom__" && lhost && !ips.includes(lhost) ? (isBridge
        ? html`<div class="notice" style="margin:-6px 0 16px"><${Ic} i="info"/><span>Bridge node: the proxy binds <span class="mono">0.0.0.0</span> inside the container and this port is published, so enter the node's <b>public</b> IP/host (what clients dial) here.</span></div>`
        : html`<div class="notice warn" style="margin:-6px 0 16px"><${Ic} i="warn"/><span>This isn't a detected address on the node. The proxy <b>binds</b> to it, so it must be a real IP on the server — otherwise it dies with <span class="mono">bind: cannot assign requested address</span>.</span></div>`) : null}
      <div class="field"><label>Forwards to</label>
        <select class="selwrap" value=${fwd} onChange=${e => setFwd(e.target.value)}>
          ${ifaces.map(i => html`<option value=${i.name}>${i.name} · 127.0.0.1:${i.port}</option>`)}
          <option value="__custom__">Custom IP:Port…</option>
        </select>
        ${hideAwg ? html`<div class="hint">${fork} is WireGuard-only — AmneziaWG interfaces are hidden (its client doesn't do AmneziaWG).</div>` : null}
      </div>
      ${isCustom ? html`<div class="field"><input value=${custom} onInput=${e => setCustom(e.target.value)} placeholder="127.0.0.1:51820" autocomplete="off"/></div>` : null}
      <button type="button" class="advtoggle" onClick=${() => setShowExec(a => !a)}><span class="advcaret">${showExec ? "▾" : "▸"}</span> Additional ExecStart parameters</button>
      ${showExec ? html`<div class="field">
        <textarea class="ta mono" rows="3" value=${params} onInput=${e => setParams(e.target.value)} placeholder="-wrap-mode on -wrap-key <64 hex chars>" spellcheck="false"></textarea>
        <div class="hint">Appended after <span class="mono">-connect ip:port</span>. ${f.wrap ? "Pre-filled with this fork's obfuscation flags + a fresh key." : "This fork has no obfuscation flags."} <button type="button" class="linkbtn" onClick=${randKey}>Copy a random 64-hex key</button></div>
      </div>` : null}
    <//>`}
    ${msg ? html`<div class=${"formmsg " + msg.k}>${msg.t}</div>` : null}
  <//>`;
}

// ═════════════════════════ SCREEN: PEERS (by node) ═════════════════════════
const peersView = { node: "", iface: "", q: "", sort: "status", dir: -1, status: null };
// Peers-screen status filter options (also the deep-link targets from grouped Needs-attention rows).
const PEER_STATUS_FILTERS = [["", "All statuses"], ["online", "Online"], ["ready", "Ready"], ["unassigned", "Unassigned"],
  ["dangling", "Dangling"], ["partial", "Partial"], ["blocked", "Blocked"], ["faulty", "Faulty"], ["pending", "Pending"], ["unknown", "Unknown"]];
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
// ── order freeze ─────────────────────────────────────────────────────────────────────────────────
// Keep rows where they are WHILE you look at them: editing a record (rename, status flip) must not make its
// row jump or leave the page. The sorted order is snapshotted per (list, sort, dir); a known row holds its
// slot even if its sort key changes. The order is recomputed only when you change the sort (a new key) or
// reload the page (this module var resets). New/removed rows fold into the snapshot so they stay put too.
const _orderFreeze = {};   // freezeKey -> [ids] in frozen order
function stableOrder(freezeKey, items, idOf, cmp) {
  const frozen = _orderFreeze[freezeKey];
  if (!frozen) { const s = items.slice().sort(cmp); _orderFreeze[freezeKey] = s.map(idOf); return s; }
  const pos = new Map(frozen.map((id, i) => [id, i]));
  const s = items.slice().sort((a, b) => {
    const ai = pos.has(idOf(a)) ? pos.get(idOf(a)) : Infinity;   // known rows keep their frozen slot
    const bi = pos.has(idOf(b)) ? pos.get(idOf(b)) : Infinity;   // new rows sort live, after the known ones
    return ai !== bi ? ai - bi : cmp(a, b);
  });
  if (items.length !== frozen.length || items.some(it => !pos.has(idOf(it)))) _orderFreeze[freezeKey] = s.map(idOf);
  return s;
}
function sortPeerRows(rows, sort, dir, freeze) {
  const key = PEER_SORT[sort] || PEER_SORT.status;
  const cmp = (a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1)
    || String(a.p.title || a.p.name || "").localeCompare(String(b.p.title || b.p.name || ""));
  return freeze ? stableOrder(freeze + "|" + sort + "|" + dir, rows, r => r.p.id + "|" + tkey(r.t.node, r.t.iface), cmp)
    : rows.slice().sort(cmp);
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
        return html`<tr key=${p.id + "|" + tkey(t.node, t.iface)} data-peer=${p.id} class=${"clk" + (fresh ? " pcreate" : "")} title="Double-click for QR / configs" onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, () => openPeerView(p.id, t.node, t.iface))} onDblClick=${e => rowDouble(e, () => openPeerConfigs(p))}>
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
            const userCell = hideUser ? null : html`<td data-label="User" class=${"usercell" + (u ? " linked" : "")} onClick=${u ? (e => { e.stopPropagation(); revealUser(u.id); }) : (e => e.stopPropagation())}>
              ${u ? html`<a class="namecell" href="#/users" onClick=${e => { e.preventDefault(); e.stopPropagation(); revealUser(u.id); }}><span>${u.name}</span><${Ic} i="user"/></a>`
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
  // freeze the order over this view's full row set (per node/iface), THEN apply search/status filters — so
  // filtering or editing never reshuffles the frozen rows
  rows = sortPeerRows(rows, peersView.sort, peersView.dir, "peers|" + node + "|" + iface);
  if (q) rows = rows.filter(({ p, t }) => searchMatch((p.title || "") + " " + (p.name || "") + " " + (t.ip || "") + " " + Store.nodeName(t.node) + " " + t.iface, q));
  if (peersView.status) rows = rows.filter(({ p }) => peersView.status === "unassigned" ? p.unassigned : p.status === peersView.status);   // status filter (set directly, or via a grouped Needs-attention click)
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
      <${SearchBox} placeholder="Search title, user, address…" value=${peersView.q} onInput=${e => { peersView.q = e.target.value; peersView.page = 1; force(x => x + 1); }}/>
      <select class="selwrap" value=${node} onChange=${e => { peersView.node = e.target.value; peersView.iface = ""; peersView.page = 1; force(x => x + 1); }}>
        ${multiServer ? html`<option value="*">All nodes</option>` : null}
        ${fleet.map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${iface} onChange=${e => { peersView.iface = e.target.value; peersView.page = 1; force(x => x + 1); }}>
        ${(node === "*" || ifaceOpts.length > 1) ? html`<option value="*">All interfaces</option>` : null}
        ${ifaceOpts.length ? ifaceOptGroups(ifaceOpts) : (node === "*" ? null : html`<option value="">no interfaces reported</option>`)}
      </select>
      <select class="selwrap" value=${peersView.status || ""} onChange=${e => { peersView.status = e.target.value || null; peersView.page = 1; force(x => x + 1); }}>
        ${PEER_STATUS_FILTERS.map(([v, l]) => html`<option value=${v}>${l}</option>`)}
      </select>
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

// ═════════════════════════ SCREEN: ACTIVITY HISTORY ═════════════════════════
// The full operator-action log ("Show history" from the Overview feed): search + Item/Action filters,
// pagination, per-row delete, and Clear all. Pulls the whole capped log once and filters client-side with
// the same taxonomy (evDecorate) as the feed, so a row's icon / click target / category stay identical.
const activityView = { q: "", item: "", action: "", page: 1 };
function ActivityHistoryScreen() {
  const [rows, setRows] = useState(null);   // null = still loading
  const [, force] = useState(0);
  const bump = () => force(x => x + 1);
  const load = () => api.events(1000).then(r => setRows(Array.isArray(r.data) ? r.data : [])).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const all = (rows || []).map(evDecorate);
  const q = activityView.q.toLowerCase();
  let list = all;
  if (activityView.item) list = list.filter(e => e.item === activityView.item);
  if (activityView.action) list = list.filter(e => e.action === activityView.action);
  if (q) list = list.filter(e => (e.verb + " " + e.name + " " + (e.detail || "")).toLowerCase().includes(q));
  const pageSize = 25;
  const totalPages = Math.max(1, Math.ceil(list.length / pageSize));
  const page = Math.min(Math.max(1, activityView.page), totalPages);
  const pageRows = list.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { activityView.page = p; bump(); };
  const delOne = e => openConfirm({ title: "Delete this entry?", confirmLabel: "Delete", danger: true,
    body: html`Remove this record — <b>${e.verb}${e.name ? " · " + e.name : ""}</b>? This can't be undone.`,
    onConfirm: async () => { await api.eventDelete(e.eid); await load(); } });
  const clearAll = () => openConfirm({ title: "Clear all activity?", confirmLabel: "Clear history", danger: true,
    body: html`Delete <b>all ${all.length} record${all.length === 1 ? "" : "s"}</b> from the activity log? This can't be undone.`,
    onConfirm: async () => { await api.eventsClear(); activityView.page = 1; await load(); } });
  return html`<div class="screen">
    <div class="crumb"><a href="#/">Overview</a><span class="sep">/</span><b>Activity history</b></div>
    <div class="toolbar">
      <${SearchBox} placeholder="Search action, name, detail…" value=${activityView.q} onInput=${e => { activityView.q = e.target.value; activityView.page = 1; bump(); }}/>
      <select class="selwrap" value=${activityView.item} onChange=${e => { activityView.item = e.target.value; activityView.page = 1; bump(); }}>
        <option value="">All items</option>${EV_ITEMS.map(i => html`<option value=${i}>${i}</option>`)}
      </select>
      <select class="selwrap" value=${activityView.action} onChange=${e => { activityView.action = e.target.value; activityView.page = 1; bump(); }}>
        <option value="">All actions</option>${EV_ACTIONS.map(a => html`<option value=${a}>${a}</option>`)}
      </select>
      <button class="btn btn-danger" disabled=${!all.length} onClick=${clearAll}><${Ic} i="trash"/> Clear history</button>
    </div>
    ${secTitle("Activity history", html`${list.length}${list.length !== all.length ? " / " + all.length : ""}`, false)}
    ${rows === null ? html`<div class="loading"><${Ic} i="refresh"/> Loading…</div>`
      : !all.length ? html`<div class="empty"><b>No activity yet</b>Operator actions across the panel will show up here.</div>`
      : !list.length ? html`<div class="empty"><b>No matches</b>Try a different search or filter.</div>`
      : html`<div class="acthist">${pageRows.map(e => html`<div class=${"act-row" + (e.click ? "" : " noclk")} key=${e.key}>
          <span class=${"act-ic t-" + e.slug}><${Ic} i=${e.icon}/></span>
          ${e.click
            ? html`<a class="act-link" href=${e.click.href} onClick=${e.click.on ? (ev => { ev.preventDefault(); e.click.on(); }) : null}><span class="act-what">${e.verb}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}</a>`
            : html`<span class="act-what">${e.verb}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}`}
          ${e.detail ? html`<span class="act-detail">${e.detail}</span>` : null}
          <span class="grow"></span>
          <span class="act-cat">${e.item}</span>
          <span class="when">${ago(e.ts)}</span>
          <button class="iconbtn danger" title="Delete entry" onClick=${() => delOne(e)}><${Ic} i="x"/></button>
        </div>`)}</div>`}
    ${list.length > pageSize ? html`<div class="pager">
      <span class="pager-info">${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, list.length)} of ${list.length}</span>
      <button class="btn btn-ghost" disabled=${page <= 1} onClick=${() => setPage(page - 1)}>‹ Prev</button>
      <span class="pager-pg">${page} / ${totalPages}</span>
      <button class="btn btn-ghost" disabled=${page >= totalPages} onClick=${() => setPage(page + 1)}>Next ›</button>
    </div>` : null}
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
    <${SearchBox} placeholder=${mode === "users" ? "Search users, tags, peers…" : "Search peer, user, endpoint, IP…"} value=${connView.q} onInput=${e => { connView.q = e.target.value; reset(); }}/>
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
    const users = sortUsers(Store.recon.users, connView.usort, connView.udir, "live").filter(u => userMatchesQ(u, q) && userOnNodeIface(u, connView.node, connView.iface) && (!connView.online || u.onlineCount > 0));
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
  rows = sortPeerRows(rows, connView.sort, connView.dir, "livepeers");
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
function sortUsers(users, sort, dir, freeze) {
  const key = USER_SORT[sort] || USER_SORT.status;
  const cmp = (a, b) => ((x, y) => x < y ? -1 : x > y ? 1 : 0)(key(a), key(b)) * (dir || -1) || String(a.name).localeCompare(String(b.name));
  return freeze ? stableOrder(freeze + "|" + sort + "|" + dir, users, u => u.id, cmp) : users.slice().sort(cmp);
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
// Clicking a PEER anywhere reveals its OWNER on the Users screen (row expanded, that peer's row glowing) — there
// is no standalone peer page. An unassigned peer (no owner) just lands on the Users screen with its row glowing.
function revealPeer(peer) {
  if (!peer) return go("#/users");
  if (peer.user_id != null) { revealUser(peer.user_id, peer.id); return; }
  Store.recentlyCreated[peer.id] = Date.now(); go("#/users");
}
// Land on the PEERS screen with a specific peer visible + its row flashing (activity-feed clicks). Filters
// the grid to that peer (unique IP) so it's guaranteed on-page, then scrolls to + glows it for ~2.5s.
function revealPeerInPeers(peer) {
  if (!peer) return go("#/peers");
  const ip = (peer.targets && peer.targets[0] && peer.targets[0].ip) || "";
  peersView.node = "*"; peersView.iface = "*"; peersView.status = null;
  peersView.q = ip || peer.title || peer.name || ""; peersView.page = 1;
  Store.recentlyCreated[peer.id] = Date.now();
  go("#/peers");
  setTimeout(() => {
    Store.apply();
    requestAnimationFrame(() => { const el = document.querySelector('[data-peer="' + peer.id + '"]'); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); });
  }, 240);
}
function revealPeerInPeersById(id) { revealPeerInPeers((Store.recon.peers || []).find(p => p.id === id)); }
// Land on the PEERS screen filtered to a status (a grouped Needs-attention click) — optionally scoped to
// one node. status "unassigned" is a synthetic filter (peers with no owner); the rest match a peer status.
function revealPeersFiltered({ node, status }) {
  peersView.node = node || "*"; peersView.iface = "*";
  peersView.status = status || null; peersView.q = ""; peersView.page = 1;
  go("#/peers");
}
// Land on an interface detail and scroll to its unmanaged/orphan panel (a grouped-orphans click).
function revealOrphans(node, iface) {
  go("#/node/" + encodeURIComponent(node) + "/" + encodeURIComponent(iface));
  setTimeout(() => requestAnimationFrame(() => { const el = document.getElementById("iface-orphans"); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }), 320);
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
function EmbeddedPeers({ peers, view, onNew, newLabel, hideUser, hideToolbar, collapse, live, onlineOnly, freezeKey }) {
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
  // freeze the order so an edit/rotate (a status change) doesn't make the row jump out of view
  rows = sortPeerRows(rows, view.sort, view.dir, freezeKey ? freezeKey + "|" + node + "|" + iface : null);

  const pageSize = view.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(Math.max(1, view.page || 1), totalPages);
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { view.page = p; bump(); };

  return html`<div class="peerspanel">
    ${hideToolbar ? null : html`<div class="toolbar sub">
      <${SearchBox} placeholder="Search title, address…" value=${view.q || ""} onInput=${e => { view.q = e.target.value; view.page = 1; bump(); }}/>
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
// One peer's QR cards on a SINGLE line — up to 3 per view, paged with ‹ › when the peer has more
// (never wraps to a second row). The card cards are passed in already built.
// A horizontal carousel of fixed-width cards. Steps ONE card at a time; the counter + ‹/› enabled-state derive
// from live scroll metrics (not a mid-scroll index guess), so it never jumps back or gets stuck before the last.
const QR_ITEM = 256, QR_GAP = 14;
function QRRow({ cards }) {
  const ref = useRef(null);
  const [m, setM] = useState({ l: 0, cw: 0, sw: 0, step: QR_ITEM + QR_GAP });
  useEffect(() => { const el = ref.current; if (!el) return;
    const measure = () => {
      const first = el.firstElementChild;                                   // real card width (varies by card type)
      const cardW = first ? first.getBoundingClientRect().width : QR_ITEM;
      const cs = getComputedStyle(el);
      const gap = parseFloat(cs.columnGap || cs.gap) || QR_GAP;
      setM({ l: el.scrollLeft, cw: el.clientWidth, sw: el.scrollWidth, step: cardW + gap });
    };
    measure(); el.addEventListener("scroll", measure, { passive: true });
    let ro; try { ro = new ResizeObserver(measure); ro.observe(el); } catch (_) {}
    return () => { el.removeEventListener("scroll", measure); if (ro) ro.disconnect(); }; }, [cards.length]);
  const n = cards.length;
  const step = m.step || (QR_ITEM + QR_GAP);
  const paged = m.sw > m.cw + 4;
  const atStart = m.l <= 2;
  const atEnd = m.sw > 0 && m.l + m.cw >= m.sw - 2;
  const per = Math.max(1, Math.round(m.cw / step));                         // cards visible per view
  let first = Math.max(0, Math.min(Math.round(m.l / step), n - per));       // 0-based index of the first visible card
  if (atEnd) first = Math.max(0, n - per);
  const last = Math.min(n - 1, first + per - 1);
  const range = first === last ? `${first + 1} of ${n}` : `${first + 1}–${last + 1} of ${n}`;
  const go = d => { const el = ref.current; if (el) el.scrollBy({ left: d * step, behavior: "smooth" }); };
  return html`<div class=${"qrrowwrap" + (paged ? " paged" : "")}>
    <div class="qrrow" ref=${ref}>${cards}</div>
    ${paged ? html`<div class="qrnav">
      <button class="qrnavbtn" disabled=${atStart} onClick=${() => go(-1)} aria-label="Previous">‹</button>
      <span class="qrnavcount">${range}</span>
      <button class="qrnavbtn" disabled=${atEnd} onClick=${() => go(1)} aria-label="Next">›</button>
    </div>` : null}
  </div>`;
}

// ── QR-modal building blocks (shared by the peer + user views) ──────────────────────────────────
// A user's subscription record from the cached status map: undefined=loading · null=none/feature-off · object.
function useSubRec(userId) {
  const [rec, setRec] = useState(undefined);
  useEffect(() => { let ok = true;
    if (!subFeatureOn() || !userId) { setRec(null); return; }
    subUsersMap().then(m => { if (ok) setRec(m[userId] || null); }).catch(() => { if (ok) setRec(null); });
    return () => { ok = false; }; }, [userId, Store.configEpoch]);
  return rec;
}
// "Part of an active subscription" — a right-aligned line under the modal title. Only when the user has a
// subscription record at all; nothing for unsubscribed users or with the feature off.
function SubStatusTag({ userId, activeOnly, header }) {
  const rec = useSubRec(userId);
  if (!subFeatureOn() || !rec) return null;
  if (activeOnly && !rec.enabled) return null;   // peer modal: only surface it for a live subscription
  // compact header badge (peer modal): a green dot + "In subscription", right-aligned in the title row
  if (header) return rec.enabled ? html`<span class="hsub"><span class="substatus-dot"></span><b>In subscription</b></span>` : null;
  const s = rec.enabled ? "active" : "disabled";
  return html`<div class=${"substatus " + s}><span class="substatus-dot"></span>Part of ${rec.enabled ? "an" : "a"} <b>${s}</b> subscription</div>`;
}
// The single unlock gate. One panel, one password — unlocking reveals BOTH the stored QRs and the subscription
// link (one encryption key gates both). Renders nothing once unlocked, or when no vault is set up.
function VaultUnlockPanel() {
  const [exists, setExists] = useState(null);
  const [ready, setReady] = useState(!!subSKCached());
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [keep, setKeep] = useState(subPersistOn());
  useEffect(() => { if (subSKCached()) { setReady(true); return; }
    let ok = true; api.subVault().then(r => { if (ok) setExists(!!(r && r.ok && r.data && r.data.exists)); }).catch(() => { if (ok) setExists(false); });
    return () => { ok = false; }; }, []);
  if (ready || subSKCached() || !exists) return null;
  const unlock = async () => {
    if (!pw || busy) return; setBusy(true);
    try { await subUnlock(pw); subSetPersist(keep); setPw(""); setReady(true); Store.configEpoch++; bus.emit(); }
    catch (e) { toast((e && e.message) || "That password didn’t unlock the key vault.", "err"); }
    setBusy(false);
  };
  return html`<div class="unlockpanel">
    <div class="unlockpanel-msg"><${Ic} i="lock"/><span>Unlock the key vault to see configs, QR codes and the subscription link.</span></div>
    <div class="unlockpanel-row">
      <input class="subpw" type="password" autofocus autocomplete="off" placeholder="Panel password" value=${pw}
        onKeyDown=${e => { if (e.key === "Enter") unlock(); }} onInput=${e => setPw(e.target.value)}/>
      <button class="btn btn-primary" disabled=${busy || !pw} onClick=${unlock}>${busy ? "Unlocking…" : "Unlock"}</button>
    </div>
    <label class="vp-keep-row"><input type="checkbox" checked=${keep} onChange=${e => setKeep(e.target.checked)}/> <span>Trust this device and keep it unlocked</span></label>
  </div>`;
}
// The subscription link + controls (user modal). Shown only once the vault is unlocked — the link's secret is
// derived from the key. Enable / Rotate / Disable, each behind a confirm; the link + copy sits above them.
function SubLinkActions({ user }) {
  useStore();
  const rec = useSubRec(user.id);
  const [url, setUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const base = subBaseUrl();
  useEffect(() => { let ok = true;
    (async () => { if (rec && rec.enabled && subSKCached()) { try { const u = await subUrlFor(rec); if (ok) setUrl(u); } catch (_) { if (ok) setUrl(null); } } else if (ok) setUrl(null); })();
    return () => { ok = false; }; }, [rec && rec.enabled, Store.configEpoch]);
  if (!subFeatureOn() || !subSKCached() || rec === undefined) return null;   // locked → the unlock panel owns it
  const after = async () => { subUsersForget(); Store.configEpoch++; bus.emit(); };
  const settingsLink = html`<a href="#/panel/settings" onClick=${() => closeAllModals()}>Settings → Subscriptions</a>`;
  const confirm = opts => pushModal(html`<${ConfirmSheet} ...${opts}/>`);   // stacks over the user modal; pops back on cancel/confirm
  const act = fn => async () => { setBusy(true); try { await fn(); } catch (e) { toast((e && e.message) || "Failed", "err"); } setBusy(false); await after(); };
  const enable = () => confirm({ title: "Enable subscription", confirmLabel: "Enable",
    body: "Create a shareable link to this user's QR codes. New peers appear on it automatically; the unlock secret rides in the link and never reaches the server.",
    onConfirm: act(async () => { await subEnableUser(user.id); const r2 = (await subUsersMap(true))[user.id]; if (r2 && r2.enabled && r2.unlock_by_sk) { const { unlockKey } = await subRecover(r2); await subBackfillUser(user.id, unlockKey); } }) });
  const rotate = () => confirm({ title: "Rotate subscription link", confirmLabel: "Rotate", warn: true,
    body: "Issue a fresh link and invalidate the current one. A config already scanned keeps working until you rekey or remove the peer.",
    onConfirm: act(() => subRotateUser(user.id)) });
  const disable = () => confirm({ title: "Disable subscription", confirmLabel: "Disable", danger: true,
    body: "Stop serving this user's link. A config already scanned keeps working until you rekey or remove the peer.",
    onConfirm: act(() => api.subUserDisable({ user_id: user.id })) });
  const enabled = !!(rec && rec.enabled);
  if (!enabled) return html`<div class="sublink sublink-off">
    <span class="sublink-off-msg">No subscription link yet — enable one to share this user's QRs.</span>
    <button class="btn btn-primary btn-mini" disabled=${busy} onClick=${enable}>Enable subscription</button>
  </div>`;
  return html`<div class="field sublink-field">
    <label>Subscription link <span class="faint" style="text-transform:none;letter-spacing:0">— this user's shareable QR page</span></label>
    <div class="sublink sublink-row">
      ${url ? html`<${SubUrlBar} url=${url}/>` : !base
        ? html`<div class="hint warn">Set a public base URL in ${settingsLink} to build the link.</div>`
        : html`<div class="hint">Building link…</div>`}
      <span class="fieldbtns">
        <button class="btn btn-ghost btn-mini" disabled=${busy} onClick=${rotate}>Rotate</button>
        <button class="btn btn-ghost btn-mini danger" disabled=${busy} onClick=${disable}>Disable</button>
      </span>
    </div>
  </div>`;
}
// One user-modal card: a peer's PRIMARY/only QR under a two-line clickable header that opens the peer's own
// modal. Line 1: title (or "Peer .{last IP octet}") · server name + protocol badge. Line 2: interface badge
// (+N when there are more deployments) · status. Reuses TargetCard's QR body + actions via its `head` override.
function UserPeerCard({ peer, onOpen }) {
  const targets = peer.targets || [];
  const t = targets[0] || {};
  const col = Store.nodeColor(t.node);
  const dnode = Store.nodeName(t.node);
  const ltype = targetType(t);
  const oct = String(t.ip || "").split("/")[0].split(".").pop() || "";
  const nm = peer.title || (oct ? "Peer ." + oct : "Peer");
  const lt = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const head = html`<div class="upc-head">
    <div class="upc-l1"><span class="upc-nm">${nm}</span><span class="grow"></span><${Badge} s=${lt.status}/></div>
    <div class="upc-l2"><span class="upc-srv" style=${"color:" + col}>${dnode}</span><${Tag} kind=${ltype} label=${t.iface}/><span class="grow"></span>${targets.length > 1 ? html`<span class="upc-deps">${targets.length} deployments</span>` : null}</div>
  </div>`;
  // Only a MULTI-config peer opens its own modal (a single-config peer has nothing extra to show — it's already
  // fully presented here). When it does: the whole card opens it EXCEPT the QR image (enlarges) and the action
  // buttons (their own jobs). `.hot` is toggled by the pointer so the card highlights only over clickable regions.
  if (!onOpen) return html`<div class="upc-wrap upc-static">
    <${TargetCard} peer=${peer} t=${t} bare=${true} head=${head}/>
  </div>`;
  const own = el => el && el.closest(".qr, button, a");
  const onClick = e => { if (own(e.target)) return; onOpen(peer); };
  const onMove = e => e.currentTarget.classList.toggle("hot", !own(e.target));
  const onLeave = e => e.currentTarget.classList.remove("hot");
  return html`<div class="upc-wrap" onClick=${onClick} onMouseMove=${onMove} onMouseLeave=${onLeave} title="Open this peer's configs">
    <${TargetCard} peer=${peer} t=${t} bare=${true} head=${head}/>
  </div>`;
}
// The VK link baked into a peer's turn configs IN THE PANEL: the owning user's own link, falling back to the
// panel-wide test link (Settings → Turn proxies) for the admin's own testing + for unassigned peers. The
// subscription page never falls back — it uses only the per-user link (see swg-sub).
function userVkLink(user) {
  return (((user && user.vk_link) || "").trim()) || (((Store.panelSettings || {}).vk_link || "").trim());
}
// Is any of these deployments behind a turn-proxy? (turn feature on AND a proxy forwards to the interface.) Gates
// the per-user VK field + the sub's VK warning — no turn-proxy on a user's interfaces ⇒ they never use a VK link.
function targetsBehindTurn(targets) {
  return turnEnabled() && (targets || []).some(t => turnProxiesFor(t.node, t.iface).length > 0);
}
const _VK_CALL_RE = /^https:\/\/(?:[\w.-]+\.)?vk(?:ontakte)?\.(?:com|ru)\/call\/join\/[\w-]+/i;
// let the operator paste a VK link with or without the scheme — add https:// when it's missing
function normVkLink(s) { s = (s || "").trim(); return s && !/^https?:\/\//i.test(s) ? "https://" + s : s; }
// Per-user VK call link, editable inline from the QR modals. Shown only when the user has a peer behind a
// turn-proxy. Empty → amber border + a hint (the panel falls back to the test link; the subscription page won't).
// Saves on blur / Enter; re-renders turn configs with the new link.
function VkLinkField({ user }) {
  // track the SAVED value locally: the modal holds a stale `user` snapshot (openUserConfigs isn't re-invoked
  // after a poll), so comparing against user.vk_link would leave the button "dirty" forever after a save.
  const [saved, setSaved] = useState(user.vk_link || "");
  const [val, setVal] = useState(user.vk_link || "");
  const [busy, setBusy] = useState(false);
  const [subd, setSubd] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);   // "saved" | "failed" — shown ~5s next to the button
  const savedTimer = useRef(null);
  const flashStatus = s => { setSaveStatus(s); if (savedTimer.current) clearTimeout(savedTimer.current); savedTimer.current = setTimeout(() => setSaveStatus(null), 5000); };
  useEffect(() => { setVal(user.vk_link || ""); setSaved(user.vk_link || ""); }, [user.id, user.vk_link]);
  useEffect(() => { let ok = true; if (subFeatureOn()) subUsersMap().then(m => { if (ok) setSubd(!!(m[user.id] && m[user.id].enabled)); }).catch(() => {}); return () => { ok = false; }; }, [user.id]);
  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current); }, []);
  const v = normVkLink(val);                    // accept the link with or without https:// — add it when missing
  const invalid = !!v && !_VK_CALL_RE.test(v);
  const empty = !v;
  const set = !empty && !invalid;               // a valid link is present → blue highlight
  const dirty = v !== saved;
  const save = async () => {
    if (!dirty || invalid) return;
    setBusy(true);
    const r = await api.userUpdate({ id: user.id, vk_link: v });
    setBusy(false);
    if (!r || !r.ok) { flashStatus("failed"); toast((r && r.error) || "Couldn't save the VK link", "err"); return; }
    setSaved(v); setVal(v);                      // reflect the saved (normalised) value → dirty=false → button disables
    flashStatus("saved");
    Store.poll(); Store.configEpoch++; bus.emit();   // turn configs re-render with the new link
  };
  return html`<div class=${"field vkfield" + (invalid ? " warn" : set ? " set" : " warn")} style="margin-bottom:14px">
    <label>VK call link <span class="faint" style="text-transform:none;letter-spacing:0">— for this user's turn-proxy configs</span></label>
    <div class="vkfield-row">
      <div class="vkbox">
        <${Ic} i="link"/>
        <input class="vkbox-input" data-noautofocus value=${val} placeholder="vk.ru/call/join/…" disabled=${busy}
          onInput=${e => setVal(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") { e.preventDefault(); save(); } }}/>
      </div>
      <span class="fieldbtns">
        ${saveStatus === "saved" ? html`<span class="vk-status ok"><${Ic} i="check"/> Saved</span>`
          : saveStatus === "failed" ? html`<span class="vk-status err"><${Ic} i="warn"/> Failed</span>` : null}
        <button class="btn btn-primary btn-mini" disabled=${busy || !dirty || invalid} onClick=${save}>${busy ? "Saving…" : "Save"}</button>
      </span>
    </div>
    ${invalid ? html`<div class="hint err">Expected a VK call link like <span class="mono">https://vk.ru/call/join/…</span></div>`
      : empty ? html`<div class="hint vk-warn">No VK link for this user yet — the panel is using your <b>test</b> link to build these turn configs. Enter their own before you distribute.${subd ? html` Right now their subscription page will show the turn configs <b>without</b> a VK link, so they'd have to add one in their turn app.` : ""}</div>` : null}
  </div>`;
}
// `child` = opened from another modal (user modal, peer view, edit peer). Then it's PUSHED onto the modal
// stack so the parent stays mounted behind it (no reload, scroll preserved) and ✕/Esc/backdrop/"Back" just
// pop back to it. Root (from a table) replaces the top as before.
function openPeerConfigs(peer, opts) {
  opts = opts || {};
  const child = !!opts.child;      // pushed onto the stack (opened from another modal) → "Back" pops to the parent
  const hideVk = !!opts.hideVk;    // the parent (user modal) already shows the VK link — don't repeat it here
  const cols = Math.min(peer.targets.length || 1, 3);   // up to 3 QRs per view; the modal sizes to fit (more → page with ‹ ›)
  const wcols = Math.max(cols, 2);                       // hold 2 QRs wide even for a single deployment (roomier layout)
  const width = wcols * 256 + (wcols - 1) * 14 + 56;
  const vkUser = peer.user_id ? Store.recon.users.find(u => u.id === peer.user_id) : null;
  // an unassigned peer always leads with "Unassigned peer", then its title — or, with no title, its internal IP
  const ipShort = (((peer.targets || [])[0] || {}).ip || "").split("/")[0];
  const parts = []; parts.push(vkUser ? vkUser.name : "Unassigned peer");
  if (peer.title) parts.push(peer.title);
  else if (!vkUser && ipShort) parts.push(ipShort);
  const nm = parts.join(" · ");
  const title = html`<span class="qrhd"><span class="qrhd-nm">${nm}</span></span>`;
  const headExtra = vkUser ? html`<${SubStatusTag} userId=${vkUser.id} activeOnly=${true} header=${true}/>` : null;
  (child ? pushModal : openModal)(html`<${Sheet} title=${title} width=${width} headExtra=${headExtra} noGuard=${true} onClose=${closeModal} onBack=${child ? closeModal : null}>
    <${VaultUnlockPanel}/>
    ${!hideVk && vkUser && targetsBehindTurn(peer.targets) ? html`<${VkLinkField} user=${vkUser}/>` : null}
    <${QRRow} cards=${peer.targets.map((t, i) => html`<${TargetCard} key=${tkey(t.node, t.iface)} peer=${peer} t=${t} bare=${true} primary=${peer.targets.length > 1 && i === 0}/>`)}/>
  <//>`);
}
function openUserEdit(user) {
  openModal(html`<${Sheet} title=${"Edit · " + user.name}><${UserEditCard} user=${user} done=${closeModal}/><//>`);
}
// Every QR/config the user owns, grouped by peer — one horizontal row of deployment QRs per peer (the peer's
// PRIMARY deployment first, tagged, when it has more than one). Same TargetCard the peer QR modal uses, so a
// stored-config / session-config peer renders its QR and an un-stored one shows the same hint.
// The subscription URL + one-tap copy. Hovering highlights the whole row (URL + button) as a single
// click target; clicking anywhere copies. Used under the title in the user + peer QR modals.
// Shown at the top of the QR/config modals when the encryption vault is configured but not unlocked this
// session: the stored configs are ciphertext, so a peer's QR can't be rebuilt until the admin unlocks the
// key with the panel password. Unlocking caches the SK (subUnlock) and bumps configEpoch so every open
// TargetCard re-resolves via the blob. Renders nothing when there's no vault or it's already unlocked.
// A blocking prompt for a user-triggered action that needs the encryption key when it isn't unlocked this
// session. Explains WHY the key is needed and the cost of skipping; "Unlock & continue" proceeds, "Skip"
// continues without the encrypted step. Resolves the ensureVaultUnlocked() promise with true/false.
function VaultPromptSheet({ opts, onDone }) {
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [keep, setKeep] = useState(subPersistOn());   // "keep this device unlocked" — device-persist opt-in
  const [exists, setExists] = useState(null);   // null = checking; whether an encryption vault is set up at all
  useEffect(() => { let ok = true; api.subVault().then(r => { if (ok) setExists(!!(r && r.ok && r.data && r.data.exists)); }).catch(() => { if (ok) setExists(false); }); return () => { ok = false; }; }, []);
  const done = v => { closeModal(); onDone(v); };
  const unlock = async () => {
    if (!pw || busy) return; setBusy(true);
    try { await subUnlock(pw); subSetPersist(keep); Store.configEpoch++; bus.emit(); setBusy(false); done(true); }
    catch (e) { setBusy(false); toast((e && e.message) || "That password didn’t unlock the encryption key.", "err"); }
  };
  return html`<${Sheet} title=${opts.title || "Enter your password to continue"} width=${480} onClose=${() => done(false)}
    foot=${html`<${Fragment}><span class="grow"></span>
      <button class="btn btn-ghost" disabled=${busy} onClick=${() => done(false)}>Skip</button>
      <button class="btn btn-primary" disabled=${busy || !pw || exists === false} onClick=${unlock}>${busy ? "Unlocking…" : "Unlock vault"}</button></>`}>
    <div class="vaultprompt">
      <p class="vp-reason">${opts.reason || "This action needs your encryption key, which isn’t unlocked in this session."}</p>
      ${exists === false
        ? html`<div class="notice err"><${Ic} i="warn"/><span>No encryption key is set up yet — set one up in <a href="#/panel/settings" onClick=${() => done(false)}>Settings → Client configs → Encryption</a>, then try again.</span></div>`
        : html`<${Fragment}><div class="field"><label>Panel password</label>
            <input class="subpw" type="password" autofocus value=${pw} autocomplete="off" placeholder="Panel password"
              onKeyDown=${e => { if (e.key === "Enter") unlock(); }} onInput=${e => setPw(e.target.value)}/></div>
            <div class="vp-keep"><label class="vp-keep-row"><input type="checkbox" checked=${keep} onChange=${e => setKeep(e.target.checked)}/> <span>Keep this device unlocked</span></label>
              <div class="hint">Stay unlocked across restarts on this device — the key is stored only here, never sent to the server.</div></div><//>`}
      <div class="notice warn vp-skip"><${Ic} i="info"/><span><b>If you skip:</b> ${opts.consequence || "the action completes, but anything that needed the key won’t be saved."}</span></div>
    </div>
  <//>`;
}
function VaultUnlockBar() {
  const [exists, setExists] = useState(false);
  const [ready, setReady] = useState(!!subSKCached());
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [keep, setKeep] = useState(subPersistOn());
  useEffect(() => { if (subSKCached()) { setReady(true); return; }
    let ok = true; api.subVault().then(r => { if (ok) setExists(!!(r && r.ok && r.data && r.data.exists)); }).catch(() => {});
    return () => { ok = false; }; }, []);
  if (ready || subSKCached() || !exists) return null;
  const unlock = async () => {
    if (!pw) return; setBusy(true);
    try { await subUnlock(pw); subSetPersist(keep); setPw(""); setReady(true); Store.configEpoch++; bus.emit(); }
    catch (e) { toast((e && e.message) || "Unlock failed", "err"); }
    setBusy(false);
  };
  return html`<div class="notice" style="margin-bottom:12px;align-items:center;gap:8px;flex-wrap:wrap">
    <${Ic} i="lock"/><span style="min-width:120px;flex:1">Unlock your encryption key to show stored QRs.</span>
    <input class="subpw" type="password" style="max-width:200px" value=${pw} autocomplete="off" placeholder="Panel password"
      onKeyDown=${e => { if (e.key === "Enter") unlock(); }} onInput=${e => setPw(e.target.value)}/>
    <button class="btn btn-primary btn-mini" disabled=${busy || !pw} onClick=${unlock}>${busy ? "Unlocking…" : "Unlock"}</button>
    <div style="flex-basis:100%">
      <label class="vp-keep-row"><input type="checkbox" checked=${keep} onChange=${e => setKeep(e.target.checked)}/> <span>Keep this device unlocked</span></label>
      <div class="hint">Survives a browser restart; the key stays on this device, never sent to the server.</div>
    </div>
  </div>`;
}
function SubUrlBar({ url }) {
  const [copied, setCopied] = useState(false);
  if (!url) return null;
  const copy = () => { (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {}); };
  return html`<div class="suburl" onClick=${copy} title="Copy subscription link">
    <${Ic} i="link"/><span class="suburl-txt">${url}</span>
    <span class=${"suburl-copy" + (copied ? " ok" : "")}><${Ic} i=${copied ? "check" : "copy"}/></span>
  </div>`;
}

// The owning user's subscription link, shown under the title in the peer QR modal. Only appears when the
// peer is assigned to a subscription-enabled user; if the Subscription Key isn't unlocked this session it
// points the operator to the user's QR view (where unlocking lives), rather than a dead control here.
function SubPeerUrl({ peer }) {
  useStore();                          // re-render when the store loads (panel settings arrive after mount)
  const on = subFeatureOn();
  const [url, setUrl] = useState(null);
  const [enabled, setEnabled] = useState(false);
  useEffect(() => { let ok = true;
    (async () => {
      if (!on || !peer.user_id) return;
      const rec = (await subUsersMap())[peer.user_id];
      if (!rec || !rec.enabled) return;
      if (ok) setEnabled(true);
      if (subSKCached()) { try { const u = await subUrlFor(rec); if (ok) setUrl(u); } catch (_) {} }
    })();
    return () => { ok = false; }; }, [peer.id, peer.user_id, on]);
  if (!on || !peer.user_id || !enabled) return null;
  return url ? html`<${SubUrlBar} url=${url}/>`
    : html`<div class="hint suburl-hint">Subscription active — open this user's QR view to copy the shareable link.</div>`;
}

// Per-user subscription control: enable/create the shareable link, show + copy it, rotate (kill the old
// link), or disable. All the crypto is client-side — enabling needs the Subscription Key, which is
// unlocked once per session with the panel password (the convenience cache). Off entirely unless the
// subscriptions feature is enabled in Settings.
function SubUserPanel({ user }) {
  useStore();                          // re-render when the store loads (panel settings arrive after mount)
  const on = subFeatureOn();
  const [rec, setRec] = useState(undefined);   // undefined=loading · null=none · object=record
  const [url, setUrl] = useState(null);
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [warn, setWarn] = useState("");
  const [vault, setVault] = useState(null);    // null=loading · bool
  const [skReady, setSkReady] = useState(!!subSKCached());
  const base = subBaseUrl();
  const load = async () => {
    const r = await api.subUsers();
    setVault(!!(r && r.ok && r.data && r.data.vault));
    setRec((r && r.ok && r.data && r.data.users && r.data.users[user.id]) || null);
  };
  useEffect(() => { if (on) load(); }, [user.id, on]);
  useEffect(() => { let ok = true;
    (async () => { if (rec && rec.enabled && subSKCached()) { try { const u = await subUrlFor(rec); if (ok) setUrl(u); } catch (_) { if (ok) setUrl(null); } } else if (ok) setUrl(null); })();
    return () => { ok = false; }; }, [rec, skReady]);
  if (!subFeatureOn()) return null;
  const settingsLink = html`<a href="#/panel/settings" onClick=${() => closeAllModals()}>Settings → Subscriptions</a>`;
  const run = fn => async () => { setBusy(true); setErr(""); setWarn(""); try { await fn(); } catch (e) { setErr(e.message || String(e)); } setBusy(false); };
  const unlock = async () => { await subUnlock(pw); setPw(""); setSkReady(true); };
  const doEnable = run(async () => {
    if (!subSKCached()) await unlock();
    await subEnableUser(user.id); subUsersForget(); await load();
    // publish the user's EXISTING peers now (subMaybePublish only covers newly-created ones)
    const rec2 = (await subUsersMap(true))[user.id];
    if (rec2 && rec2.enabled && rec2.unlock_by_sk) {
      const { unlockKey } = await subRecover(rec2);
      const res = await subBackfillUser(user.id, unlockKey);
      if (res.missing) setWarn(`${res.missing} of ${res.total} peer${res.total === 1 ? "" : "s"} ${res.missing === 1 ? "has" : "have"} no stored config, so ${res.missing === 1 ? "its QR won't" : "their QRs won't"} appear on the page. Re-issue ${res.missing === 1 ? "that peer" : "those peers"}${Store.storeConfigs ? "" : ", or enable “Keep configs” in Settings,"} to publish ${res.missing === 1 ? "it" : "them"}.`);
    }
  });
  const doRotate = run(async () => { if (!subSKCached()) await unlock(); await subRotateUser(user.id); subUsersForget(); await load(); });
  const doUnlock = run(unlock);
  const doDisable = run(async () => { await api.subUserDisable({ user_id: user.id }); subUsersForget(); setUrl(null); await load(); });
  const pwField = html`<input class="subpw" type="password" autocomplete="off" placeholder="Panel password (unlocks the Subscription Key)"
    value=${pw} onInput=${e => setPw(e.target.value)} onKeyDown=${e => { if (e.key === "Enter" && pw && !busy) doUnlock(); }}/>`;
  let bodyEl;
  if (vault === null || rec === undefined) bodyEl = html`<div class="hint">Loading…</div>`;
  else if (vault === false) bodyEl = html`<div class="hint">Set up subscription encryption in ${settingsLink} first.</div>`;
  else if (!rec || !rec.enabled) bodyEl = html`
    <div class="hint">A shareable, mobile-friendly page of this user's QRs. New peers appear automatically; the unlock secret rides in the link and never reaches the server.</div>
    ${!subSKCached() ? pwField : null}
    <button class="btn" disabled=${busy || (!subSKCached() && !pw)} onClick=${doEnable}>Create subscription link</button>`;
  else bodyEl = html`
    ${url ? html`<${SubUrlBar} url=${url}/>` : !base
      ? html`<div class="hint warn">Set a public base URL in ${settingsLink} to build the shareable link.</div>`
      : subSKCached() ? html`<div class="hint">Building link…</div>`
      : html`<div class="hint">Unlock the Subscription Key to view this user's link.</div>${pwField}
             <button class="btn" disabled=${busy || !pw} onClick=${doUnlock}>Unlock</button>`}
    <div class="subpanel-actions">
      <button class="btn ghost" disabled=${busy} onClick=${doRotate} title="Issue a new link and invalidate the old one">New link</button>
      <button class="btn ghost danger" disabled=${busy} onClick=${doDisable}>Disable</button>
    </div>
    <div class="hint">Replacing or disabling the link stops serving new configs — but a config already scanned keeps working until you rekey or remove the peer.</div>`;
  return html`<div class="subpanel">
    <div class="subpanel-hd"><${Ic} i="link"/> Subscription${rec && rec.enabled ? html`<span class="subpanel-on">active</span>` : null}</div>
    ${err ? html`<div class="hint err">${err}</div>` : null}
    ${warn ? html`<div class="hint warn"><${Ic} i="warn"/> ${warn}</div>` : null}
    ${bodyEl}
  </div>`;
}

function openUserConfigs(user, back) {
  const peers = Store.peersOfUser(user.id);
  // the user modal shows ONE card per peer, so size by the peer COUNT (up to 3 across), not the widest peer's
  // deployment count — otherwise a user's modal width flip-flopped on whether any one peer had 3+ configs
  const cols = Math.min(peers.length || 1, 3);
  const wcols = Math.max(cols, 2);                        // hold 2 cards wide even for a single peer (roomier layout)
  const width = wcols * 256 + (wcols - 1) * 14 + 56;
  const anyTurn = peers.some(p => targetsBehindTurn(p.targets));
  const nCfg = peers.reduce((a, p) => a + ((p.targets || []).length || 0), 0);
  const title = html`<span class="qrhd"><span class="qrhd-nm">${user.name}</span>${user.tag ? html`<span class="qrhd-tag">${user.tag}</span>` : null}</span>`;
  const headExtra = html`<span class="hcount">${peers.length} peer${peers.length === 1 ? "" : "s"}${nCfg > 1 ? ` (${nCfg} configs)` : ""}</span>`;
  openModal(html`<${Sheet} title=${title} width=${width} headExtra=${headExtra} noGuard=${true} onClose=${back || closeModal}>
    <${VaultUnlockPanel}/>
    <${SubLinkActions} user=${user}/>
    ${anyTurn ? html`<${VkLinkField} user=${user}/>` : null}
    ${peers.length ? html`<${QRRow} cards=${peers.map(p => html`<${UserPeerCard} key=${p.id} peer=${p} onOpen=${(p.targets || []).length > 1 ? () => openPeerConfigs(p, { child: true, hideVk: true }) : null}/>`)}/>`
      : html`<div class="empty" style="padding:24px">This user has no peers yet.</div>`}
  <//>`);
}
// Turn-proxy client configs for one deployment — one section per turn-proxy on the interface, generated
// on the fly for the DEPLOYED fork. `conf` is the base WG config (needs the private key, so session/stored).
// Turn always opens FROM another modal (a peer or user QR view), so it's PUSHED — ✕/Esc/backdrop/"Back" pop
// straight back to whatever it was launched from, with that view intact.
function openTurnConfigs(peer, t, conf) {
  pushModal(html`<${Sheet} title=${"Turn configs · " + (peer.title || peer.name || "peer")} width=${560} noGuard=${true} onClose=${closeModal} onBack=${closeModal}>
    <${TurnConfigSheet} peer=${peer} t=${t} conf=${conf}/>
  <//>`);
}
function TurnConfigSheet({ peer, t, conf }) {
  const [selFork, setSelFork] = useState(0);
  const [inst, setInst] = useState({});   // fork → chosen instance index (for redundant same-fork proxies)
  // One badge PER FORK; the peer's own fork (observed viaTurn) sorts first and is selected by default. When a
  // fork has several proxies (redundancy), a dropdown picks which one. Only the selected proxy's config shows.
  const lt = ((Store.recon.peers.find(p => p.id === peer.id) || {}).targets || []).find(d => d.node === t.node && d.iface === t.iface) || t;
  const all = turnProxiesFor(t.node, t.iface);
  const sorted = lt.viaTurn ? [...all].sort((a, b) => (b.service === lt.viaTurn ? 1 : 0) - (a.service === lt.viaTurn ? 1 : 0)) : all;
  const order = [], byFork = {};
  sorted.forEach(p => { const f = turnFork(p.service); if (!byFork[f]) { byFork[f] = []; order.push(f); } byFork[f].push(p); });
  const vkUser = peer.user_id ? Store.recon.users.find(u => u.id === peer.user_id) : null;
  const vk = userVkLink(vkUser);   // this user's own link, falling back to the panel test link (subs never fall back)
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
    <${TurnCfgItem} key=${cur.service} conf=${conf} tp=${cur} vk=${vk} base=${base}/>
  </div>`;
}
// One turn-proxy's client artifact. Sync forks fill `text`; wingsv:// fills `buildAsync` (needs zlib), so
// we resolve it in an effect and show "generating…" until ready. Textarea wraps + auto-grows (no scroll).
function TurnCfgItem({ conf, tp, vk, base }) {
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
    if (!nn[t.iface]) nn[t.iface] = { iface: t.iface, type: targetType(t), count: 0 };
    nn[t.iface].count++;
  }
  const srvNodes = Object.keys(_nm).map(nid => ({ node: nid, ifaces: Object.values(_nm[nid]).sort((a, b) => a.iface.localeCompare(b.iface)) }))
    .sort((a, b) => Store.nodeName(a.node).localeCompare(Store.nodeName(b.node)));
  const st = userStats(user.id);
  const [db, ub] = dlul(st.rxb, st.txb);
  const view = userPeerViews[user.id] || (userPeerViews[user.id] = { node: "", iface: "", q: "", page: 1, pageSize: 20, sort: "status", dir: -1 });
  return html`<div class=${"urow" + (expanded ? " open" : "")} id=${"urow-" + user.id}>
    <div class="urow-head" title="Double-click for QR / configs" onMouseDown=${rowNoSelect} onClick=${e => rowSingle(e, toggle)} onDblClick=${e => rowDouble(e, () => openUserConfigs(user))}>
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
          <button class="iconbtn" title="Show QR / configs" onClick=${() => openUserConfigs(user)}><${Ic} i="qr"/></button>
          <button class="iconbtn" title="Edit user" onClick=${() => openUserEdit(user)}><${Ic} i="pencil"/></button>
          <button class="iconbtn iconbtn-add" title="Add peer" onClick=${() => openAddPeers(user.id, user.name)}><${Ic} i="plus"/></button>
        </span>`}
      </span>
    </div>
    ${expanded ? html`<div class="urow-body">
      ${shownPeers.length ? html`<${EmbeddedPeers} peers=${shownPeers} view=${view} hideUser=${true} hideToolbar=${true} collapse=${true} live=${live} onlineOnly=${onlineOnly} freezeKey=${"uembed|" + user.id}/>`
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
  // freeze the order over the FULL list, then filter — so searching/clearing never reshuffles the frozen rows
  const users = sortUsers(allUsers, usersView.sort, usersView.dir, "users").filter(u => userMatchesQ(u, q) && userOnNodeIface(u, usersView.node, usersView.iface));
  // The toolbar search filters the USER list only. The unassigned grid is deliberately NOT filtered by it:
  // the whole point of searching for a user here is to then assign an unassigned peer to them, and filtering
  // both by the same term hid every peer whose title didn't happen to match the user's name. The grid has its
  // own search box (unassignedView.q, applied inside EmbeddedPeers) for filtering the peers themselves.
  const unassigned = Store.unassignedPeers();

  const pageSize = usersView.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil(users.length / pageSize));
  const page = Math.min(Math.max(1, usersView.page || 1), totalPages);
  const pageUsers = users.slice((page - 1) * pageSize, page * pageSize);
  const setPage = p => { usersView.page = p; force(x => x + 1); };

  return html`<div class="screen">
    <${StoreOffBanner}/>
    <div class="toolbar">
      <${SearchBox} placeholder="Search users, tags, notes, peers…" value=${usersView.q} onInput=${e => { usersView.q = e.target.value; usersView.page = 1; force(x => x + 1); }}/>
      <select class="selwrap" value=${usersView.node} onChange=${e => { usersView.node = e.target.value; usersView.iface = ""; usersView.page = 1; force(x => x + 1); }}>
        <option value="">All nodes</option>${(Store.nodes || []).map(n => html`<option value=${n.id}>${n.name}</option>`)}
      </select>
      <select class="selwrap" value=${usersView.iface} onChange=${e => { usersView.iface = e.target.value; usersView.page = 1; force(x => x + 1); }}>
        <option value="">All interfaces</option>${ifaceOptGroups(ifaceOpts)}
      </select>
      <button class="btn btn-ghost" onClick=${() => openCreatePeer({})}><span class="plus"><${Ic} i="plus"/></span> New peer</button>
      <button class="btn btn-primary" onClick=${openCreateUser}><span class="plus"><${Ic} i="plus"/></span> New user</button>
    </div>

    ${secTitle("Users", users.length, false)}
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

    ${unassigned.length ? html`<${Fragment}>
      <div class="section-title"><h2 style="color:var(--faint)">Unassigned peers</h2><span class="count">${unassigned.length}</span></div>
      <${EmbeddedPeers} peers=${unassigned} view=${unassignedView} collapse=${true} freezeKey=${"unassigned-embed"}/>
    <//>` : null}
  </div>`;
}

// ═════════════════════════ SCREEN: USER DETAIL ═════════════════════════

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
  const [vk, setVk] = useState(user.vk_link || "");
  const showVk = Store.peersOfUser(user.id).some(p => targetsBehindTurn(p.targets));   // only when they have a peer behind a turn-proxy
  const vkBad = vk.trim() && !_VK_CALL_RE.test(normVkLink(vk));
  const save = async () => {
    if (!name.trim()) { toast("Name can't be empty.", "err"); return; }
    if (vkBad) { toast("Not a valid VK call link — expected vk.ru/call/join/…", "err"); return; }
    const vkv = normVkLink(vk);
    done();   // close the editor immediately; the row updates optimistically
    mutate({
      key: "user:" + user.id,
      patch: s => { const u = s.roster.users[user.id]; if (u) { u.name = name.trim(); u.tag = tag.trim(); u.note = note; if (showVk) u.vk_link = vkv; } },
      call: () => api.userUpdate(Object.assign({ id: user.id, name: name.trim(), tag: tag.trim(), note }, showVk ? { vk_link: vkv } : {})),
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
    ${showVk ? html`<div class=${"field vkfield" + (vkBad ? " warn" : "")}><label>VK call link <span class="faint" style="text-transform:none;letter-spacing:0">— for this user's turn-proxy configs</span></label>
      <input value=${vk} onInput=${e => setVk(e.target.value)} placeholder="https://vk.ru/call/join/…" maxlength="512"/>
      ${vkBad ? html`<div class="hint err">Expected a VK call link like <span class="mono">https://vk.ru/call/join/…</span></div>`
        : html`<div class="hint">Baked into this user's turn-proxy configs. Blank → the panel uses your test link and their subscription page shows no VK link until you set one.</div>`}</div>` : null}
    <div class="editfoot"><button class="btn btn-danger" onClick=${del}><${Ic} i="trash"/> Delete user</button><span class="grow"></span><button class="btn btn-ghost" onClick=${done}>Cancel</button><button class="btn btn-primary" onClick=${save}>Save</button></div>
  </div>`;
}

// one credential: its targets, each a QR card; owner controls + edit + add-target

function TargetCard({ peer, t, bare, primary, head }) {
  useStore();   // re-render on each poll so the status badge stays live (t is a snapshot from open)
  const [conf, setConf] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { let ok = true; getConfig(peer.pubkey, t.node, t.iface).then(c => { if (ok) { setConf(c); setLoaded(true); ensurePeerBlob(peer, c); } }); return () => { ok = false; }; }, [peer.pubkey, t.node, t.iface, Store.configEpoch]);
  // live target (status / observed) from the store, falling back to the passed-in snapshot
  const ft = (Store.recon.peers.find(p => p.id === peer.id) || {}).targets;
  const lt = (ft && ft.find(d => d.node === t.node && d.iface === t.iface)) || t;
  const col = Store.nodeColor(t.node);
  const obs = lt.observed;
  const tps = turnProxiesFor(t.node, t.iface);
  const dnode = Store.nodeName(t.node);
  // zoom caption: username + title (or "Unassigned"), then the server name (in its colour) + iface tag
  const idParts = []; if (peer.name) idParts.push(esc(peer.name)); if (peer.title) idParts.push(esc(peer.title));
  const ltype = targetType(t);
  const label = `<span class="qrc-id">${idParts.length ? idParts.join(" · ") : "Unassigned"}</span>`
    + `<span class="qrc-srv" style="color:${esc(col)}">${esc(dnode)}</span><span class="tg tg-${ltype}">${esc(t.iface)}</span>`;

  return html`<div class="deploy">
    ${head || html`<div class="deploy-head"><div class="nmwrap"><a class="nm nmlink" style=${"color:" + col} onClick=${() => { closeModal(); go("#/node/" + encodeURIComponent(t.node)); }}>${dnode}</a></div><${Tag} kind=${ltype} label=${t.iface}/><span class="grow"></span><${Badge} s=${lt.status}/></div>`}
    <div class="deploy-body">
      ${primary ? html`<span class="qr-primary">Primary</span>` : null}
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
   // green→amber→red util ramp (matches hm-fill + the CPU cpuColor ramp)
// Threshold alerts for a node: disk/memory > 90%, CPU saturated, one core pinned, load > 1.5/core.
// CPU and load are separate signals: load counts D-state tasks, so heavy disk I/O raises load while
// the CPU sits idle. Reporting both keeps each honest.
function healthAlerts(health) {
  const out = [];
  for (const d of (health && health.disk || [])) if (d.total && d.used / d.total > 0.9) out.push({ sev: "hot", msg: "disk " + d.mount + " " + Math.round(d.used / d.total * 100) + "%" });
  const m = health && health.mem;
  if (m && m.total && m.used / m.total > 0.9) out.push({ sev: "hot", msg: "memory " + Math.round(m.used / m.total * 100) + "%" });
  const ncpu = (health && health.ncpu) || 1;
  if (health && typeof health.cpu_pct === "number") {
    // Saturation is described per-CPU, counted from the node's per-vCPU list — never inferred from
    // (max − mean), which can't tell 1 pinned CPU from 5 and goes silent at 6-of-8. The all-saturated case
    // MUST be tested before any mean-based alert: when every CPU is hot the mean is necessarily ≥ SAT_PCT,
    // so a mean-first branch would swallow it and "All … saturated" could never appear.
    const cores = cpuCores(health), hot = hotCores(health), tot = cores.length;
    const pk = tot ? " (peak " + Math.max(...cores) + "%)" : "";
    if (!tot) {                                                    // older swg-noded: mean only, no per-CPU list
      if (health.cpu_pct >= SAT_PCT) out.push({ sev: "hot", msg: "CPU " + Math.round(health.cpu_pct) + "%" });
    } else if (hot && tot === 1) {
      out.push({ sev: "hot", msg: "1 " + cpuName(health) + " saturated" + pk });
    } else if (hot && hot === tot) {
      out.push({ sev: "hot", msg: "All " + cpuNamePl(health, tot) + " saturated" + pk });
    } else if (hot) {                                              // plural keyed off the TOTAL: "1 of 2 vCPUs"
      out.push({ sev: health.cpu_pct >= SAT_PCT ? "hot" : "warn",
                 msg: hot + " of " + tot + " " + cpuNamePl(health, tot) + " saturated" + pk });
    }
  }
  if (health && Array.isArray(health.load) && (health.load[0] || 0) / ncpu > 1.5) out.push({ sev: "warn", msg: "load " + health.load[0].toFixed(1) + " / " + ncpu + " " + cpuNamePl(health, ncpu) });
  return out;
}
const SAT_PCT = 90;                                     // a logical CPU at/above this is "saturated" (matches CPU_SAT_PCT in swg-panel-server)
const cpuCores = h => (h && Array.isArray(h.cpu_cores)) ? h.cpu_cores : [];
const hotCores = h => cpuCores(h).reduce((n, c) => n + (c >= SAT_PCT ? 1 : 0), 0);
// /proc/stat's cpuN are LOGICAL cpus: vCPUs under a hypervisor, hardware threads on bare metal. Never
// "cores" — an 8-core box with hyperthreading lists 16. The node reports `virt`; unknown ⇒ plain "CPU".
const cpuName = h => (h && h.virt) ? "vCPU" : "CPU";
const cpuNamePl = (h, n) => cpuName(h) + (n === 1 ? "" : "s");

// The CPU bar+number is ALWAYS the hover target — per-vCPU detail is useful on a healthy node too.
// The triangle is only an attention marker, added when at least one vCPU is saturated.
// `idle` is 100 - usage (i.e. it folds in that vCPU's iowait share). Per-CPU iowait is not reported:
// the kernel credits it to whichever CPU was idle when the I/O completed, so only the node-level
// figure in the header is meaningful — and it's the share that used to masquerade as CPU.
function CpuPop({ health, trigger, alignRight }) {
  const cores = cpuCores(health);
  if (!cores.length) return trigger;                    // older swg-noded: no per-vCPU data, no bubble
  const hot = hotCores(health), iow = health.cpu_iowait_pct;
  const l1 = Array.isArray(health.load) ? (health.load[0] || 0) : null;   // system-wide; the kernel keeps no per-CPU load
  return html`<${Popover} cls="cpupop" popCls="cpu-bubble" alignRight=${alignRight} trigger=${trigger}>
    <div class="onpop-h">${cores.length} ${cpuNamePl(health, cores.length)} · mean ${Math.round(health.cpu_pct)}%${l1 !== null ? " · load " + l1.toFixed(2) : ""}${typeof iow === "number" && iow >= 1 ? " · iowait " + Math.round(iow) + "%" : ""}${hot ? html` · <b class="cpu-hot-n">${hot} saturated</b>` : ""}</div>
    ${cores.map((c, i) => html`<div class=${"onrow cpu-row" + (c >= SAT_PCT ? " hot" : "")} key=${i}>
      <span class="on-name">${cpuName(health)} ${i}</span>
      <span class="hm-bar cpu-corebar"><i class="hm-fill" style=${"width:" + Math.min(100, c) + "%;background:" + cpuColor(c)}></i></span>
      <span class="cpu-use" style=${"color:" + cpuColor(c)}>${c}%</span>
      <span class="cpu-idle">idle ${Math.max(0, 100 - c)}%</span>
      <span class="cpu-sat">${c >= SAT_PCT ? html`<${Ic} i="warn"/>` : null}</span>
    </div>`)}
  </${Popover}>`;
}
// The attention triangle itself — rendered inside the trigger, so it hovers with the bar.
const CpuWarnIc = ({ health }) => hotCores(health) ? html`<span class="cpu-warn" aria-label=${cpuNamePl(health, hotCores(health)) + " saturated"}><${Ic} i="warn"/></span>` : null;
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
// Gradient area chart for a history series (0–100). Stretches to its container width;
// the stroke stays crisp via non-scaling-stroke. Used for the CPU-load history.
// format a chart point's timestamp for the hover tooltip — time of day, + date for week/month ranges
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// per-range tooltip time: live = h:m:s, hour/day = h:m, week/month = "June 24, 6PM" (date + 12h hour)
function histTime(ts, range) {
  if (ts == null) return "";
  const d = new Date(ts * 1000), p2 = x => String(x).padStart(2, "0");
  const hm = p2(d.getHours()) + ":" + p2(d.getMinutes());
  const date = MONTHS[d.getMonth()] + " " + d.getDate();
  if (range === "month") return date;                                  // date only
  if (range === "day" || range === "week") return date + " " + hm;     // date + time
  if (range === "live") return hm + ":" + p2(d.getSeconds());          // time + seconds
  return hm;                                                           // hour → time
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
// CPU colour ramp for the meters + history line: green ≤60%, green→orange 60–85%, orange→red
// 85–100%. v is utilization (mean across cores, 0–100), so it means the same on every node.
// A node still on an older swg-noded sends load-per-core instead, which can exceed 100 — that
// pins to solid red, the right signal for a genuinely overloaded box.
const LOAD_G_DARK = [63, 216, 154], LOAD_G_LIGHT = [14, 158, 99], LOAD_O = [242, 163, 60], LOAD_R = [242, 84, 91];
function cpuColor(v) {
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
  const LOAD_G = resolvedTheme() === "light" ? LOAD_G_LIGHT : LOAD_G_DARK;   // the low-load green must stay legible on white
  if (v <= 60) return mix(LOAD_G, LOAD_G, 0);
  if (v <= 85) return mix(LOAD_G, LOAD_O, (v - 60) / 25);
  if (v <= 100) return mix(LOAD_O, LOAD_R, (v - 85) / 15);
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
  // vertical stroke gradient: colour each height by its absolute utilization (green→orange→red).
  // Stops at the band edges that fall inside the visible [lo,hi] window — linear between them
  // reproduces the ramp exactly (both colour and y are linear in value within a band).
  // offsets are normalised to the polyline's own bounding box (objectBoundingBox): top = hi → 0, bottom = lo → 1
  const edges = [...new Set([lo, 60, 85, hi].filter(v => v >= lo && v <= hi))].sort((a, b) => b - a);
  const stops = edges.map(v => ({ off: Math.max(0, Math.min(1, (hi - v) / rng)), col: cpuColor(v) }));
  const cur = pts[n - 1];   // area fade is tinted by the latest value
  return html`<div class="harea-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    <svg class="harea" viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" height=${h}>
      <defs>
        <linearGradient id=${id + "s"} x1="0" x2="0" y1="0" y2="1">
          ${stops.map(s => html`<stop offset=${s.off} stop-color=${s.col}/>`)}
        </linearGradient>
        <linearGradient id=${id + "a"} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color=${cpuColor(cur)} stop-opacity="0.30"/><stop offset="1" stop-color=${cpuColor(cur)} stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${n >= 2 ? html`<polygon points=${area} fill=${"url(#" + id + "a)"}/>
      <polyline points=${line} fill="none" stroke=${"url(#" + id + "s)"} stroke-width="1.4" vector-effect="non-scaling-stroke"/>` : null}
    </svg>
    ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xy[0][0] + "%;top:" + (xy[0][1] / h * 100) + "%;background:" + cpuColor(cur)}></div>` : null}
    ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xy[hov][0]} dots=${[{ yp: xy[hov][1] / h * 100, color: cpuColor(pts[hov]) }]}
      label=${histTime(T[hov], range) + " · " + Math.round(pts[hov]) + "%"}/>` : null}
  </div>`;
}

// Throughput history: rx as a filled area + tx as a line, scaled to the series max.
function ThroughputChart({ rx, tx, h, head, times, range, cap }) {
  const [hov, setHov] = useState(null);
  const wref = useRef(null);
  // Perspective is applied HERE (once, centrally) so every caller can pass raw node rx/tx and the ↓ series
  // always means "download in the active perspective" — node-side by default, user-side when set to peers.
  const _pov = (Store.panelSettings || {}).throughput_perspective === "peers";
  const dnArr = _pov ? tx : rx, upArr = _pov ? rx : tx;
  const R = (dnArr || []).map(v => v || 0), T = (upArr || []).map(v => v || 0);
  const n = Math.max(R.length, T.length);
  const curR = R[R.length - 1] || 0, curT = T[T.length - 1] || 0;
  const hi = n ? Math.max(0, ...R, ...T) : 0;
  // DYNAMIC y-scale from the DISPLAYED peak (this range's series, not a global/hour peak): ceiling = the nearest
  // 1/5/10/50/100/500×unit above the peak, with ≥15% headroom baked in via peak/0.85 (so a peak sitting within
  // 15% of a ceiling takes the next one up). Reflects real magnitude without stretching a tiny peak to fill height.
  const scaleMax = niceScaleCeil(Math.max(hi, 1024) / 0.85);
  const scaleLabel = rate(scaleMax);
  const legend = html`<div class="tp-legend"><span class="tp-k"><i class="sw rx"></i>↓ ${rate(curR)}</span><span class="tp-k"><i class="sw tx"></i>↑ ${rate(curT)}</span><span class="tp-peak">peak ${rate(hi)}</span><span class="tp-scale" title="Vertical scale — nearest 1/5/10/50/100/500 unit above the peak (≥15% headroom)">${scaleLabel}</span><span class="grow"></span>${head || null}</div>`;
  h = h || 60; const w = 100;
  // right-anchored to the ring's full capacity, like MiniArea — fills from the right as blocks arrive
  const C = Math.max(cap || n || 1, 2);
  const xAt = i => w - (n - 1 - i) * (w / (C - 1));
  // baseline 0 at the bottom, scaleMax (the nice ceiling) at the very top — the ceiling itself carries the ≥15%
  // headroom, so no extra top padding is needed (the peak line lands at ≥15% below the top).
  const top = 0;
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
          <stop offset="0" stop-color="var(--tp-rx)" stop-opacity="0.30"/><stop offset="1" stop-color="var(--tp-rx)" stop-opacity="0"/>
        </linearGradient></defs>
        ${n >= 2 ? html`<polygon points=${rxArea} fill=${"url(#" + gid + ")"}/>
        <polyline points=${rxLine} fill="none" stroke="var(--tp-rx)" stroke-width="1.3" vector-effect="non-scaling-stroke"/>
        <polyline points=${line(T)} fill="none" stroke="var(--tp-tx)" stroke-width="1.3" vector-effect="non-scaling-stroke" stroke-dasharray="3 2"/>` : null}
      </svg>
      ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(R[0]) / h * 100) + "%;background:var(--tp-rx)"}></div>
        <div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(T[0]) / h * 100) + "%;background:var(--tp-tx)"}></div>` : null}
      ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xAt(hov)}
        dots=${[{ yp: Y(R[hov] || 0) / h * 100, color: "var(--tp-rx)" }, { yp: Y(T[hov] || 0) / h * 100, color: "var(--tp-tx)" }]}
        label=${histTime(TT[hov], range) + " · ↓ " + rate(R[hov] || 0) + " · ↑ " + rate(T[hov] || 0)}/>` : null}
    </div>
  </div>`;
}

// Split a formatted value into its numeric head and unit tail so the unit can be tinted separately
// (e.g. "261G" → "261" + green "G"). No space is inserted — the parts render flush.
// Concentric-ring doughnut (hand-rolled SVG, no deps). `rings` = outer→inner; each ring is
//   { label, fmt, unitColor?, segments:[{ key, name, value, color }] }.
// Fully controlled by `active` = { key, dir } (or null): `dir` is the ring index to isolate, or null for the
// whole entity (both arcs). Hovering ONE arc lights only that arc and reports {key, dir:its-ring}; the centre
// then shows that one value (arrow + unitColor, resting style · % of ring). A null-dir target (the legend
// name) lights every arc for the key and the centre shows that entity's own per-ring numbers — never totals.
// `onActive` reports hover back up so the legend isolates in lock-step. Cheap re-renders — no SVG rebuild.
function MultiRing({ rings, size, thick, gap, center, active, onActive }) {
  size = size || 168; thick = thick || 15; gap = gap == null ? 1.1 : gap;
  const cx = size / 2, cy = size / 2;
  const rings2 = (rings || []).filter(Boolean);
  const directional = rings2.some(r => r.unitColor);
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
  const arrowOf = lbl => lbl === "Download" ? "↓ " : lbl === "Upload" ? "↑ " : "";
  // an arc is LIT when it matches the active key AND (whole-entity hover, or its exact ring)
  const lit = a => active && a.seg.key === active.key && (active.dir == null || a.ri === active.dir);
  const set = t => onActive && onActive(t);
  // ── centre readout while hovering ──
  let readout = center;
  if (active) {
    const ea = arcs.filter(a => !a.track && a.seg && a.seg.key === active.key).sort((p, q) => p.ri - q.ri);
    if (ea.length) {
      const nm = ea[0].seg.name, col = ea[0].seg.color;
      const valLine = a => html`<div class="mrc-val" style=${a.ring.unitColor ? "color:" + a.ring.unitColor : ""}>${arrowOf(a.ring.label)}${(a.ring.fmt || (v => v))(a.seg.value)}</div>`;
      if (active.dir != null) {                                   // one arc → its single value + which ring / %
        const a = ea.find(x => x.ri === active.dir) || ea[0];
        readout = html`<div class="mrc-hov"><div class="mrc-name" style=${"color:" + col}>${nm}</div>
          ${valLine(a)}<div class="mrc-sub">${a.ring.label} · ${Math.round(a.pct)}%</div></div>`;
      } else if (directional) {                                   // whole entity → its own ↓ / ↑
        readout = html`<div class="mrc-hov"><div class="mrc-name" style=${"color:" + col}>${nm}</div>${ea.map(valLine)}</div>`;
      } else {                                                    // count doughnut → this entity's on / tot
        const tot = (ea.find(a => a.ri === 0) || {}).seg, on = (ea[ea.length - 1] || {}).seg;
        readout = html`<div class="mrc-hov"><div class="mrc-name" style=${"color:" + col}>${nm}</div>
          <div class="mrc-val">${on ? on.value : 0}<small style="color:var(--faint)"> / ${tot ? tot.value : 0}</small></div></div>`;
      }
    }
  }
  return html`<div class="mring" style=${"width:" + size + "px;height:" + size + "px"} onMouseLeave=${() => set(null)}>
    <svg width=${size} height=${size} viewBox=${"0 0 " + size + " " + size}>
      <g transform=${"rotate(-90 " + cx + " " + cy + ")"}>
        ${arcs.map((a, i) => a.track
          ? html`<circle key=${"t" + i} cx=${cx} cy=${cy} r=${a.r} fill="none" stroke="var(--track)" stroke-width=${thick} pathLength="100"/>`
          : html`<circle key=${"a" + a.ri + "-" + a.si} cx=${cx} cy=${cy} r=${a.r} fill="none" stroke=${a.seg.color} stroke-width=${thick}
              pathLength="100" stroke-dasharray=${Math.max(0, a.pct - gap) + " " + (100 - Math.max(0, a.pct - gap))} stroke-dashoffset=${-a.off}
              class=${"mring-seg" + (active && !lit(a) ? " dim" : "")}
              onMouseEnter=${() => set({ key: a.seg.key, dir: a.ri })}/>`)}
      </g>
    </svg>
    <div class="mring-center">${readout}</div>
  </div>`;
}
// Legend for a doughnut. Rows carry either directional values {down, up} (traffic) or a single {right}
// (counts). Wired with the shared `active` = {key, dir}: hovering the NAME targets the whole entity (dir
// null, both arcs); hovering the ↓ or ↑ value targets just that ring (dir 0 / 1) and dims its partner value.
// The whole thing mirrors the doughnut — hover either side, the same arc/value lights, the rest dim.
function RingLegend({ items, cols, active, onActive }) {
  const set = t => onActive && onActive(t);
  return html`<div class=${"mring-leg" + (cols ? " c" + cols : "")}>${(items || []).map(it => {
    const k = it.key || it.name;
    const on = active && active.key === k, rowDim = active && active.key !== k, hasDU = it.down != null;
    return html`<div class=${"mrl-row" + (rowDim ? " dim" : "") + (on ? " on" : "")} key=${k}
        onMouseEnter=${() => set({ key: k, dir: null })} onMouseLeave=${() => set(null)}>
      <span class="mrl-sw" style=${"background:" + it.color}></span>
      <span class="mrl-nm">${it.name}</span>
      <span class="grow"></span>
      ${hasDU
        ? html`<span class=${"mrl-dv" + (on && active.dir === 1 ? " vdim" : "")} onMouseEnter=${() => set({ key: k, dir: 0 })} onMouseLeave=${() => set({ key: k, dir: null })}>↓${it.down}</span>
               <span class=${"mrl-uv" + (on && active.dir === 0 ? " vdim" : "")} onMouseEnter=${() => set({ key: k, dir: 1 })} onMouseLeave=${() => set({ key: k, dir: null })}>↑${it.up}</span>`
        : (it.right != null ? html`<span class="mrl-v">${it.right}</span>` : null)}
    </div>`;
  })}</div>`;
}

// Discrete BLOCK history — one bar per time bucket (right-anchored, newest at the right). Height ∝ value,
// each bar seated in its own track so a low, fixed block count (24–30) reads as clean blocks. Hovering shows
// the same ChartHover bubble as the throughput/CPU charts: the bucket's time/date (per `range`) + the value.
function OnlineBlocks({ blocks, step, endTs, range, h, color }) {
  const [hov, setHov] = useState(null); const wref = useRef(null);
  color = color || "var(--online)"; h = h || 70;
  const n = blocks.length, hi = Math.max(1, ...blocks.filter(v => v != null));
  const onMove = e => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left) / r.width * n); setHov(i >= 0 && i < n && blocks[i] != null ? i : null); };
  return html`<div class="oblk-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    ${blocks.map((v, i) => html`<div class=${"oblk" + (hov === i ? " hot" : "")} key=${i}>
      ${v == null ? null : html`<i style=${"height:" + Math.max(4, v / hi * 100) + "%;background:" + color}></i>`}</div>`)}
    ${hov != null ? html`<${ChartHover} xp=${(hov + 0.5) / n * 100} dots=${[{ yp: 100 - Math.max(4, blocks[hov] / hi * 100), color }]}
      label=${(endTs != null ? histTime(endTs - (n - 1 - hov) * step, range) + " · " : "") + Math.round(blocks[hov]) + " online"}/>` : null}
  </div>`;
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
  return html`<div class="rankbars">${rows.map(r => {
    const inner = html`<span class="rb-label"><span class="rb-nm">${r.label}</span>${r.count > 1 ? html`<span class="rb-n" title=${r.count + " peers"}>${r.count}</span>` : ""}</span>
      <span class="rb-track"><i style=${"width:" + Math.max(2, (r.value || 0) / mx * 100) + "%;background:" + (r.color || "var(--brand)")}></i></span>
      <span class="rb-val">${r.sub}</span>`;
    // a talker aggregating several peers carries a per-peer breakdown, shown on hover as its own mini bar list
    const bmx = (r.bub && r.bub.length) ? Math.max(1, ...r.bub.map(b => b.value || 0)) : 1;
    const bub = (r.bub && r.bub.length) ? html`<span class="rb-bub">${r.bub.map(b => html`<${Fragment}>
        <span class="rb-bub-n">${b.kind ? html`<${Tag} kind=${b.kind} label=${b.kind}/>` : ""}<span class="rb-bub-nm" title=${b.name}>${b.name}</span></span>
        <span class="rb-bub-track"><i style=${"width:" + Math.max(3, (b.value || 0) / bmx * 100) + "%;background:" + (r.color || "var(--brand)")}></i></span>
        <span class="rb-bub-v">${b.sub}</span><//>`)}</span>` : null;
    // rows with an href/onClick are interactive; rows without (e.g. destinations — nothing to open) render static
    const cls = "rb" + (bub ? " hasbub" : "");
    return (r.href || r.onClick)
      ? html`<a class=${cls} href=${r.href || "#"} onClick=${r.onClick || null} key=${r.label}>${inner}${bub}</a>`
      : html`<div class=${cls + " static"} key=${r.label}>${inner}${bub}</div>`;
  })}</div>`;
}

// A history chart (CPU or throughput) with live/day/week/month range tabs. "live" uses the
// series already in /api/state; day/week/month are fetched on demand from /api/node-history.
const HIST_RANGES = ["live", "hour", "day", "week", "month"];
// blocks (= slots = plotted points) each range's x-axis holds — must match swg-panel-server
// HRRD_RINGS slot counts (live = LIVE_MAX). Charts pin data to the right and fill leftward.
const RANGE_CAP = { live: 200, hour: 250, day: 300, week: 350, month: 400 };
const tailSeries = (s, n) => { const o = {}; for (const k of ["t", "cpu", "mem", "disk", "rx", "tx", "mrx", "mtx"]) if (Array.isArray((s || {})[k])) o[k] = s[k].slice(-n); return o; };
// Node throughput panel: a Peers/Mesh toggle in the header (right-aligned) splits the graph into client (rx−mrx),
// mesh (mrx), or both. Never both off — turning off the only-selected one switches to the other (like the doughnuts).
// Node health panel: CPU/Mem/Disk meters + the CPU-load history, with the range picker hoisted into the header.
function NodeHealthPanel({ name, nrec }) {
  const [range, setRange] = useState("live");
  const removing = nrec.removing ? html`<span class="nstat removing"><${Ic} i="trash"/> flagged for removal</span><button class="btn btn-mini" style="margin-left:9px" title="Cancel removal — keep this node" onClick=${() => unflagNode(nrec)}>Cancel</button>` : null;
  const actions = html`<div class="panel-tools">${removing}${nrec.health_history ? html`<${RangeTabs} range=${range} setRange=${setRange}/>` : null}</div>`;
  return html`<${Panel} icon="activity" title="Health" tone="online" actions=${actions}>
    <${HealthAlerts} health=${nrec.health}/>
    ${nrec.health_history
      ? html`<${RangedHistory} node=${name} kind="cpu" live=${nrec.health_history} liveFine=${nrec.health_live} h=${52} head=${html`<${HealthMeters} health=${nrec.health}/>`} range=${range} setRange=${setRange}/>`
      : html`<${HealthMeters} health=${nrec.health}/>`}
  <//>`;
}
// Interface throughput panel (interface-detail screen): range picker hoisted into the header, like the node graph.
function IfaceThroughput({ node, iface }) {
  const [range, setRange] = useState("live");
  return html`<${Panel} icon="gauge" title="Throughput" actions=${html`<${RangeTabs} range=${range} setRange=${setRange}/>`}>
    <${RangedHistory} node=${node} kind="throughput" h=${72} fetch=${r => api.ifaceSeries(node, iface, r).then(x => x && x.ok ? x.data : {})} range=${range} setRange=${setRange}/>
  <//>`;
}
function NodeThroughput({ name, nrec }) {
  const [peers, setPeers] = useState(true);
  const [mesh, setMesh] = useState(true);
  const [range, setRange] = useState("live");
  const togP = () => { if (peers && !mesh) { setPeers(false); setMesh(true); } else setPeers(!peers); };
  const togM = () => { if (mesh && !peers) { setMesh(false); setPeers(true); } else setMesh(!mesh); };
  // Peers/Mesh sits on the LEFT (as the header's `lead`, right after the title); the range picker stays on the right.
  const lead = html`<div class="dcard-traf hdr-lead">
    <button class=${"tbadge peers" + (peers ? " on" : "")} onClick=${togP} title=${(peers ? "Hide" : "Show") + " client (peer) traffic"}>Peers</button>
    <button class=${"tbadge mesh" + (mesh ? " on" : "")} onClick=${togM} title=${(mesh ? "Hide" : "Show") + " mesh (node-to-node relay) traffic"}>Mesh</button>
  </div>`;
  return html`<${Panel} icon="gauge" title="Throughput" lead=${lead} actions=${html`<${RangeTabs} range=${range} setRange=${setRange}/>`}>
    <${RangedHistory} node=${name} kind="throughput" live=${nrec.health_history} liveFine=${nrec.health_live} h=${72} traf=${{ peers, mesh }} range=${range} setRange=${setRange}/>
  <//>`;
}
// The live/hour/day/week/month picker. Rendered inside the chart by default, or lifted into a panel header
// (controlled `range`/`setRange`) so Health/Throughput can host it up top.
function RangeTabs({ range, setRange }) {
  return html`<div class="rangetabs">${HIST_RANGES.map(t => html`<button class=${"rtab" + (range === t ? " on" : "")} onClick=${() => setRange(t)}>${t}</button>`)}</div>`;
}
function RangedHistory({ node, kind, live, h, head, liveFine, fetch, traf, range: cRange, setRange: cSetRange }) {
  const [iRange, iSetRange] = useState("live");
  const controlled = cRange !== undefined;   // parent owns the range (tabs live in a panel header) → don't draw them here
  const range = controlled ? cRange : iRange, setRange = cSetRange || iSetRange;
  const [fetched, setFetched] = useState(null);
  const custom = !!fetch;   // per-entity graphs (turn / mesh / interface): fetch EVERY range on-demand off their own RRD (never in /api/state)
  const fetchRange = custom || range === "day" || range === "week" || range === "month";   // node graph: live/hour ride /api/state
  useEffect(() => {
    if (!fetchRange) { setFetched(null); return; }
    let ok = true; setFetched(null);   // clear so the chart shows an empty area, then fills when the fetch lands
    const p = custom ? Promise.resolve(fetch(range)) : api.nodeHistory(node, range).then(r => r && r.ok ? r.data : {});
    p.then(d => { if (ok) setFetched(d || {}); }).catch(() => {});
    return () => { ok = false; };
  }, [node, range]);
  // LIVE = the raw ~5s in-memory buffer when present; else — e.g. just after a panel restart, before
  // the buffer refills — fall back to the tail of the 15s ring (`live`, the hour series) so the chart
  // keeps showing recent history. hour = the full 15s series from /api/state; day/week/month fetched.
  const liveBuf = range === "live" && liveFine && (liveFine.t || []).length > 1;
  const s = custom ? (fetched || {})
    : range === "live" ? (liveBuf ? liveFine : tailSeries(live, 70))
    : range === "hour" ? (live || {}) : (fetched || {});
  // x-axis capacity: the live fallback is coarse 15s data, so let it fit to its own length (cap 0)
  // rather than pinning to the 5s window; every other range uses its fixed block count.
  const cap = custom ? RANGE_CAP[range] : range === "live" ? (liveBuf ? RANGE_CAP.live : 0) : RANGE_CAP[range];
  const hasData = (s.cpu || s.rx || []).some(x => x != null);
  const nlive = Store.recon.nodeStatus[node] === "live";   // node hasn't reported for several rounds → the live feed is frozen
  // A node that stops reporting (update / re-install / convert / brief outage) must NEVER blank the
  // chart — the data already collected stays on screen, flagged with a small "paused" pill.
  const notLive = !nlive && (range === "live" || range === "hour");   // only the live-fed ranges; day/week/month keep their stored history
  const pausedPill = (notLive && hasData) ? html`<span class="rt-paused" title="This node isn't reporting right now — showing the last data it sent.">paused</span>` : null;
  // when the range picker is hoisted into the panel header, the in-chart slot keeps only the "paused" pill
  const tabs = html`${pausedPill}${controlled ? null : html`<${RangeTabs} range=${range} setRange=${setRange}/>`}`;
  if (kind === "throughput") {
    // The node throughput carries a mesh split; the parent passes a `traf` {peers,mesh} filter (its Peers/Mesh toggle
    // lives in the panel header). client = rx−mrx, mesh = mrx. Per-entity graphs (iface/turn/mesh) pass no filter.
    let rx = s.rx, tx = s.tx;
    if (traf) {
      const pick = (tot, mesh) => (tot || []).map((v, i) => (traf.peers ? Math.max(0, (v || 0) - ((mesh || [])[i] || 0)) : 0) + (traf.mesh ? ((mesh || [])[i] || 0) : 0));
      rx = pick(s.rx, s.mrx); tx = pick(s.tx, s.mtx);
    }
    return html`<${ThroughputChart} rx=${rx} tx=${tx} h=${h} head=${tabs} times=${s.t} range=${range} cap=${cap}/>`;   // perspective handled inside ThroughputChart
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
  const ncpu = health.ncpu || 1;
  const l1 = Array.isArray(health.load) ? (health.load[0] || 0) : null;
  const loadTxt = () => l1.toFixed(2) + " / " + ncpu + " " + cpuNamePl(health, ncpu);
  if (typeof health.cpu_pct === "number") {
    // Only bounded percentages get a bar. Load is unbounded and system-wide, so a bar clamped at 100%
    // would erase the one thing load adds over utilization: how DEEP the run queue is (util reads 100%
    // at load 1.0 and at load 8.0 alike). It lives as a plain number in the CPU hover bubble instead.
    cols.push({ label: "CPU", heat: true, cpu: true, pct: health.cpu_pct, text: Math.round(health.cpu_pct) + "%" });
  } else if (l1 !== null) {
    cols.push({ label: "CPU load", heat: true, pct: l1 / ncpu * 100, text: loadTxt() });   // older swg-noded: no cpu_pct, load-per-core as before
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
    const heat = !!c.heat;                               // CPU bar+number: continuous green→red, like the graph
    const col = heat ? cpuColor(c.pct) : null;          // uncapped pct → an old node's overloaded load-per-core reads full red
    const body = html`<div class="hcol">
      <div class="hcol-top"><span class="hcol-l">${c.label}</span><span class="hcol-v" style=${col ? "color:" + col : ""}>${c.text}${c.cpu ? html`<${CpuWarnIc} health=${health}/>` : null}</span></div>
      <div class="hm-bar"><i class=${"hm-fill" + (heat ? "" : " " + htone(p))} style=${"width:" + p + "%" + (col ? ";background:" + col : "")}></i></div>
    </div>`;
    // the whole CPU meter (number + bar) is the hover target, saturated or not
    return c.cpu ? html`<${CpuPop} health=${health} trigger=${body}/>` : body;
  })}</div>`;
}
function HealthAlerts({ health }) {
  const alerts = healthAlerts(health);
  return alerts.length ? html`<div class="halerts">${alerts.map(a => html`<span class=${"halert " + a.sev}><${Ic} i="warn"/> ${a.msg}</span>`)}</div>` : null;
}
function NodeHealth({ health, node, compact, history, range, nodeHist }) {
  if (!health) return compact ? null : html`<div class="hint" style="margin:2px">No health data reported yet.</div>`;
  const hh = (node && (Store.nodes || []).find(n => n.id === node) || {}).health_history || null;  // server-side RRD (node = id)
  // CPU history follows the dashboard range. `range` here is the range the passed nodeHist is FOR (the Overview passes
  // rangeHist.range) — it LAGS the just-clicked range while a fetch is in flight, so the chart keeps showing the last
  // loaded range's data until the new one lands (no flick to empty or to live).
  const useRanged = range && range !== "live" && nodeHist && Array.isArray(nodeHist.cpu) && nodeHist.cpu.some(x => x != null);
  const liveCpu = (hh && Array.isArray(hh.cpu) && hh.cpu.length > 1) ? hh.cpu : null;
  const cpuHist = useRanged ? nodeHist.cpu : liveCpu;
  const cpuTimes = useRanged ? nodeHist.t : (hh ? hh.t : null);
  const cpuRange = useRanged ? range : "live", cpuCap = useRanged ? (RANGE_CAP[range] || 0) : 0;
  const showHist = history !== false && !!cpuHist;
  return html`<div class="health">
    <${HealthAlerts} health=${health}/>
    <${HealthMeters} health=${health}/>
    ${showHist ? html`<div class="health-hist">
      <span class="hist-cap">CPU history</span>
      <${MiniArea} points=${cpuHist} h=${compact ? 36 : 52} times=${cpuTimes} range=${cpuRange} cap=${cpuCap}/>
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
    foot=${footRow({ onCancel: closeModal, onAction: go, action: "Update now" })}>
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
  const h = n.health, cpuUtil = h && typeof h.cpu_pct === "number";
  const hasCpu = cpuUtil || (h && Array.isArray(h.load));
  const l1 = (h && Array.isArray(h.load)) ? (h.load[0] || 0) : 0;
  // Utilization when the node reports it; load-per-core for an older swg-noded (which can exceed 100).
  const cpctRaw = cpuUtil ? h.cpu_pct : l1 / ((h && h.ncpu) || 1) * 100, cpct = Math.min(100, cpctRaw);   // cpctRaw (uncapped) colours the bar+number green→red like the graph; cpct caps the bar width
  const cpuLabel = cpuUtil ? "CPU" : "CPU load", cpuText = cpuUtil ? Math.round(cpctRaw) + "%" : l1.toFixed(2);
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
    <div class="nc-cpu nm-item"><span class="nm-l">${cpuLabel}</span>${hasCpu ? html`<${CpuPop} health=${h} alignRight=${true} trigger=${html`<span class="nm-cpu"><span class="hm-bar"><i class="hm-fill" style=${"width:" + cpct + "%;background:" + cpuColor(cpctRaw)}></i></span><span class="nm-v" style=${"color:" + cpuColor(cpctRaw)}>${cpuText}</span><${CpuWarnIc} health=${h}/></span>`}/>` : html`<span class="nm-v faint">—</span>`}</span>
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
    if (np) await subRewrap(np);   // keep the config-encryption convenience cache unlockable with the new password
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

// Add / edit an outbound webhook (Settings → Integrations). Immediate-persist via a dedicated endpoint —
// not part of the batched Save. On create the panel returns the signing secret once; edits keep the secret.
const WH_EVENTS = [["peer.added", "Peer added"], ["peer.removed", "Peer removed"], ["node.online", "Node came online"], ["node.offline", "Node went offline"]];
function WebhookSheet({ hook, onSaved, onClose }) {
  const [url, setUrl] = useState((hook && hook.url) || "");
  const [events, setEvents] = useState(new Set((hook && hook.events) || WH_EVENTS.map(e => e[0])));
  const [enabled, setEnabled] = useState(hook ? hook.enabled !== false : true);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState("");                 // shown once, only on create
  const valid = /^https?:\/\/.+/i.test(url.trim());
  const toggle = ev => setEvents(s => { const n = new Set(s); n.has(ev) ? n.delete(ev) : n.add(ev); return n; });
  const save = async () => {
    if (!valid) return toast("Enter a valid http(s) URL.", "err");
    setBusy(true);
    const r = await api.apiWebhookSave({ id: hook && hook.id, url: url.trim(), events: [...events], enabled });
    setBusy(false);
    if (!r.ok) return toast(r.error || "Failed to save webhook", "err");
    if (r.data && r.data.secret && !hook) { setSecret(r.data.secret); onSaved && onSaved(); return; }   // creation: reveal the secret, keep the sheet open
    onSaved && onSaved(); onClose && onClose();
  };
  return html`<${Sheet} title=${hook ? "Edit webhook" : "Add webhook"} onClose=${onClose}
    foot=${secret ? html`<${Fragment}><span class="grow"></span><button class="btn" onClick=${onClose}>Done</button></>`
      : html`<${Fragment}><span class="grow"></span>
        <button class="btn btn-ghost" onClick=${onClose}>Cancel</button>
        <button class="btn btn-primary" disabled=${busy || !valid} onClick=${save}>${hook ? "Save" : "Add webhook"}</button></>`}>
    ${secret ? html`<div class="notice ok"><${Ic} i="check"/><span>Webhook saved. This is its <b>signing secret</b> — shown once. Every delivery carries an <span class="mono">X-SWG-Signature: sha256=HMAC(secret, body)</span> header so you can verify it's from this panel.</span></div>
      <div class="tokreveal"><code class="tokval">${secret}</code><button class="btn btn-mini" onClick=${() => copy(secret, "Secret")}><${Ic} i="copy"/> Copy</button></div>`
    : html`<div class="field"><label>Payload URL</label>
        <input value=${url} onInput=${e => setUrl(e.target.value)} placeholder="https://example.com/hooks/swg" spellcheck="false"/>
        <div class="hint">The panel POSTs a JSON body here on each selected event. A signing secret is generated on save.</div></div>
      <div class="seclabel">Events</div>
      <div class="wh-events">${WH_EVENTS.map(([ev, lbl]) => html`<label class="wh-ev" key=${ev}>
        <input type="checkbox" checked=${events.has(ev)} onChange=${() => toggle(ev)}/><span class="mono">${ev}</span><span class="wh-ev-lbl">${lbl}</span></label>`)}</div>
      <label class="wh-en"><${Switch} on=${enabled} onChange=${setEnabled}/><span>Deliveries enabled</span></label>`}
  <//>`;
}

// Settings → Integrations: the read-only external API (tokens + Prometheus) and outbound webhooks. All actions
// persist immediately via dedicated endpoints (outside the batched Save), mirrored optimistically into Store.
function IntegrationsSettings() {
  const cfg = () => ((Store.panelSettings || {}).api) || { enabled: false, tokens: [], webhooks: [] };
  const [label, setLabel] = useState("");
  const [minted, setMinted] = useState(null);               // {label, token} — revealed once after minting
  const [busy, setBusy] = useState(false);
  const c = cfg();
  const baseUrl = `${location.origin}${BASE}`;
  const optimistic = next => { Store.panelSettings = { ...(Store.panelSettings || {}), api: next }; bus.emit(); };
  const setEnabled = async v => { optimistic({ ...cfg(), enabled: v }); const r = await api.panelSettings({ api_enabled: v }); if (r && r.ok === false) toast(r.error || "Failed", "err"); };
  const mint = async () => {
    setBusy(true);
    const r = await api.apiTokenCreate(label.trim());
    setBusy(false);
    if (!r.ok) return toast(r.error || "Failed to create token", "err");
    setMinted({ label: r.data.label, token: r.data.token });
    setLabel("");
    optimistic({ ...cfg(), enabled: true, tokens: [...(cfg().tokens || []), { id: r.data.id, label: r.data.label, created: r.data.created, last_used: null }] });
  };
  const revoke = t => openConfirm({ title: "Revoke API token", confirmLabel: "Revoke", danger: true,
    body: html`Revoke <b>${t.label}</b>? Any integration still using it stops working immediately.`,
    onConfirm: async () => { await api.apiTokenRevoke(t.id); optimistic({ ...cfg(), tokens: (cfg().tokens || []).filter(x => x.id !== t.id) }); } });
  const editHook = h => openModal(html`<${WebhookSheet} hook=${h} onClose=${closeModal}/>`);
  const delHook = h => openConfirm({ title: "Delete webhook", confirmLabel: "Delete", danger: true,
    body: html`Stop sending events to <b>${h.url}</b>?`,
    onConfirm: async () => { await api.apiWebhookDelete(h.id); optimistic({ ...cfg(), webhooks: (cfg().webhooks || []).filter(x => x.id !== h.id) }); } });
  const testHook = async h => { const r = await api.apiWebhookTest(h.id); toast(r.ok ? ("Delivered — HTTP " + ((r.data || {}).status || "200")) : ("Delivery failed: " + (r.error || "unreachable")), r.ok ? "ok" : "err", 4200); };
  return html`<div class="card">
    <div class="seclabel turnhead" style="margin-top:0">External API<span class="grow"></span>
      <${Switch} on=${c.enabled === true} title=${c.enabled ? "API on — tokens are accepted" : "API off — all tokens are rejected"} onChange=${setEnabled}/></div>
    <p class="hint" style="margin:0 0 12px">A <b>read-only</b> REST + Prometheus surface for external monitoring and automation — Grafana, Uptime Kuma, Prometheus, Terraform/Ansible. No token can ever change the fleet. Authenticate with a bearer token below; <span class="mono">/healthz</span> and <span class="mono">/api/v1/health</span> stay open as liveness probes.</p>
    ${c.enabled !== true ? html`<div class="notice warn"><${Ic} i="warn"/><span>The API is <b>off</b> — endpoints return 401. Minting a token turns it on, or flip the switch above.</span></div>` : null}

    <div class="seclabel">Access tokens</div>
    <div class="tok-add"><input value=${label} onInput=${e => setLabel(e.target.value)} placeholder="Label (e.g. grafana, prometheus)" spellcheck="false" onKeyDown=${e => { if (e.key === "Enter") mint(); }}/>
      <button class="btn btn-primary" disabled=${busy} onClick=${mint}><span class="plus"><${Ic} i="plus"/></span> Create token</button></div>
    ${minted ? html`<div class="notice ok"><${Ic} i="check"/><span>New token <b>${minted.label}</b> — copy it now, it won't be shown again.</span></div>
      <div class="tokreveal"><code class="tokval">${minted.token}</code><button class="btn btn-mini" onClick=${() => copy(minted.token, "Token")}><${Ic} i="copy"/> Copy</button><button class="btn btn-mini btn-ghost" onClick=${() => setMinted(null)}>Dismiss</button></div>` : null}
    ${(c.tokens || []).length ? html`<div class="toklist">${c.tokens.map(t => html`<div class="tokrow" key=${t.id}>
      <div class="tokrow-main"><span class="tokrow-label">${t.label}</span>
        <span class="tokrow-meta">created ${ago(t.created)}${t.last_used ? " · last used " + ago(t.last_used) : " · never used"}</span></div>
      <button class="btn btn-mini btn-danger" onClick=${() => revoke(t)}><${Ic} i="trash"/> Revoke</button></div>`)}</div>`
      : html`<p class="hint" style="margin:2px 0 0">No tokens yet — create one to let an external system read the fleet.</p>`}

    <div class="seclabel">Webhooks</div>
    <p class="hint" style="margin:0 0 10px">The panel POSTs a signed JSON body to your endpoint when a peer is added/removed or a node goes online/offline. Use them for alerting or automation.</p>
    ${(c.webhooks || []).length ? html`<div class="toklist">${c.webhooks.map(h => html`<div class=${"tokrow" + (h.enabled === false ? " off" : "")} key=${h.id}>
      <div class="tokrow-main"><span class="tokrow-label mono">${h.url}</span>
        <span class="tokrow-meta">${(h.events || []).join(", ") || "all events"}${h.enabled === false ? " · disabled" : ""}</span></div>
      <button class="btn btn-mini" title="Send a test ping" onClick=${() => testHook(h)}><${Ic} i="refresh"/> Test</button>
      <button class="btn btn-mini" onClick=${() => editHook(h)}><${Ic} i="pencil"/></button>
      <button class="btn btn-mini btn-danger" onClick=${() => delHook(h)}><${Ic} i="trash"/></button></div>`)}</div>` : null}
    <div style="margin-top:10px"><button class="btn btn-ghost" onClick=${() => editHook(null)}><${Ic} i="plus"/> Add webhook</button></div>

    <div class="seclabel">Endpoints</div>
    <div class="apiendpoints">
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/health</span><span class="apiep-d">liveness + counts (no auth)</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/metrics</span><span class="apiep-d">Prometheus exposition</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers</span><span class="apiep-d">nodes with status + counts</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/servers/{id}/peers</span><span class="apiep-d">peers + last-handshake timing</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/peers</span><span class="apiep-d">all peers, per-node presence</span></div>
      <div class="apiep"><span class="apiep-m">GET</span><span class="mono">/api/v1/summary</span><span class="apiep-d">fleet totals</span></div>
    </div>
    <div class="apisnip"><div class="apisnip-h">Test it<button class="btn btn-mini" onClick=${() => copy(`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`, "Command")}><${Ic} i="copy"/> Copy</button></div>
      <code class="apisnip-c">${`curl -H 'Authorization: Bearer <token>' ${baseUrl}/api/v1/servers`}</code></div>
    <div class="apisnip"><div class="apisnip-h">Prometheus scrape config<button class="btn btn-mini" onClick=${() => copy(`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    scheme: ${location.protocol.replace(":", "")}\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`, "Scrape config")}><${Ic} i="copy"/> Copy</button></div>
      <code class="apisnip-c">${`scrape_configs:\n  - job_name: swg-panel\n    metrics_path: /metrics\n    authorization:\n      credentials: <token>\n    static_configs:\n      - targets: ['${location.host}${BASE}']`}</code></div>
  </div>`;
}

// Cloudflare's proxy only connects back to origin HTTPS on this fixed port set (everything else is
// unreachable behind the orange cloud). A bundled snapshot of CF's published IP ranges (v4 + v6) for the
// copy-list — it changes rarely; the panel never fetches it live.
const CF_HTTPS_PORTS = [443, 8443, 2053, 2083, 2087, 2096];
const CF_IP_RANGES = [
  "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
  "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
  "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
  "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
  "2a06:98c0::/29", "2c0f:f248::/32"];
const TLS_MODE_OPTS = [
  { value: "", label: "None — plain HTTP (behind a reverse proxy / Cloudflare)" },
  { value: "letsencrypt", label: "Let's Encrypt (HTTP-01 — needs port 80 reachable)" },
  { value: "cloudflare", label: "Let's Encrypt via Cloudflare DNS (no port 80; needs a token)" },
  { value: "cf15", label: "Cloudflare Origin certificate (15y — only valid behind Cloudflare)" },
  { value: "selfsigned", label: "Self-signed" }];

// The panel + swg-sub network address (bindable IP + port) and the ONE certificate config both derive from.
// A change is applied LIVE: the panel dual-listens on the new address and only drops the old once the browser
// confirms the new one works, so a bad value never locks the operator out. swg-sub just restarts.
function AccessTLSCard({ onChange }) {
  const acc = (Store.panelSettings || {}).access || {};
  const p0 = acc.panel || {}, s0 = acc.sub || {}, t0 = acc.tls || {};
  const subsOn = !!((Store.panelSettings || {}).subscriptions || {}).enabled;
  const [pUrl, setPUrl] = useState(p0.url || ""); const [pHost, setPHost] = useState(p0.host || "0.0.0.0"); const [pPort, setPPort] = useState(String(p0.port || 443));
  const [sUrl, setSUrl] = useState(s0.url || ""); const [sHost, setSHost] = useState(s0.host || "0.0.0.0"); const [sPort, setSPort] = useState(String(s0.port || 8444));
  const [mode, setMode] = useState(t0.mode || ""); const [email, setEmail] = useState(t0.email || "");
  const [cfTok, setCfTok] = useState(""); const [cfOrig, setCfOrig] = useState("");
  const [hasCfTok, setHasCfTok] = useState(!!t0.has_cf_token); const [hasCfOrig, setHasCfOrig] = useState(!!t0.has_cf_origin_token);
  const [ips, setIps] = useState([]); const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  // Baseline of what's currently live — the form is compared to this to decide what changed (and thus what needs
  // a live apply). Refreshed after a successful save so the button disables until the next edit.
  const [orig, setOrig] = useState({ pUrl: p0.url || "", pHost: p0.host || "0.0.0.0", pPort: String(p0.port || 443),
    sUrl: s0.url || "", sHost: s0.host || "0.0.0.0", sPort: String(s0.port || 8444), mode: t0.mode || "", email: t0.email || "" });
  useEffect(() => { api.get("/api/access/ips").then(r => { if (r && r.ok) setIps(r.ips || []); }); }, []);
  // Pull the CURRENT saved config back into the form (+ baseline) — used after a revert, where the backend rolled
  // the bind back to the live one, so the form never keeps showing a value the panel rejected.
  const resync = async () => {
    const r = await api.get("/api/state").catch(() => null);
    const ps = ((r || {}).data || {}).panel_settings;
    if (ps) { Store.panelSettings = ps; bus.emit(); }   // refresh the GLOBAL store too, so a remount/reload can't rehydrate the rejected value the apply rolled back
    const a = (ps || {}).access || {};
    const pp = a.panel || {}, ss = a.sub || {}, tt = a.tls || {};
    setPUrl(pp.url || ""); setPHost(pp.host || "0.0.0.0"); setPPort(String(pp.port || 443));
    setSUrl(ss.url || ""); setSHost(ss.host || "0.0.0.0"); setSPort(String(ss.port || 8444));
    setMode(tt.mode || ""); setEmail(tt.email || "");
    setOrig({ pUrl: pp.url || "", pHost: pp.host || "0.0.0.0", pPort: String(pp.port || 443),
      sUrl: ss.url || "", sHost: ss.host || "0.0.0.0", sPort: String(ss.port || 8444), mode: tt.mode || "", email: tt.email || "" });
  };
  // poll the apply state machine while a change is in flight; auto-redirect to the new panel address to confirm it,
  // and surface a single running status (shown in the settings footer, like every other section).
  useEffect(() => {
    if (!polling) return; let live = true, timer;
    const tick = async () => {
      const r = await api.get("/api/access/status"); if (!live) return;
      if (r && r.ok) {
        const p = r.panel || {}, s = r.sub || {};
        if (p.state === "verifying" && p.redirect) { location.href = p.redirect; return; }
        const parts = [];
        if (p.state && p.state !== "idle") parts.push("Panel: " + (p.message || p.state));
        if (subsOn && s.state && s.state !== "idle") parts.push("Subscriptions: " + (s.message || s.state));
        const fail = ["failed", "reverted"].includes(p.state) || s.state === "failed";
        if (parts.length) setMsg({ ok: !fail, t: parts.join(" · ") });
        const done = ["saved", "failed", "reverted", "idle"].includes(p.state) && ["saved", "failed", "reverted", "idle"].includes(s.state);
        if (done) { setPolling(false); if (!parts.length) setMsg({ ok: true, t: "Applied." });
          if (fail) resync();    // the form was left showing the rejected value → pull the rolled-back config back in
          return; }
      }
      timer = setTimeout(tick, 1400);
    };
    tick(); return () => { live = false; clearTimeout(timer); };
  }, [polling]);

  const presets = new Set(["0.0.0.0", "127.0.0.1", ...ips.map(x => x.ip)]);
  const ipOpts = (host, withLocal) => [
    ...(withLocal ? [{ value: "127.0.0.1", label: "127.0.0.1 — local only" }] : []),
    ...ips.map(x => ({ value: x.ip, label: `${x.ip} — ${x.iface}` })),
    { value: "0.0.0.0", label: "0.0.0.0 — any IP" },
    { value: "__custom", label: "Custom IP…" }];
  const cfMode = (mode === "cloudflare" || mode === "cf15");
  const pBad = cfMode && pPort && !CF_HTTPS_PORTS.includes(+pPort);
  const sBad = subsOn && cfMode && sPort && !CF_HTTPS_PORTS.includes(+sPort);
  const hard = mode === "cf15";                                   // cf15 origin certs ONLY work behind CF → block
  const blocked = hard && (pBad || sBad);

  const ipField = (host, setHost, withLocal) => {
    const val = presets.has(host) ? host : "__custom";
    return html`<div class="field"><label>Listen IP</label>
      <${Dropdown} value=${val} onChange=${v => setHost(v === "__custom" ? (presets.has(host) ? "" : host) : v)}
        options=${ipOpts(host, withLocal)}/>
      ${val === "__custom" ? html`<input class="mt8" type="text" placeholder="e.g. 203.0.113.5" value=${host} onInput=${e => setHost(e.target.value)}/>` : null}</div>`;
  };
  const portField = (port, setPort, bad) => html`<div class="field"><label>Port${bad ? html` <span class="ciw" title="Cloudflare can't reach this port"><${Ic} i="warn"/></span>` : null}</label>
    <input class=${bad ? "bad" : ""} type="text" value=${port} onInput=${e => setPort(e.target.value)}/></div>`;
  const cfNote = html`<div class=${"notice " + (hard ? "err" : "warn")}><${Ic} i="warn"/><span>
    Cloudflare's proxy only reaches origin HTTPS on ${CF_HTTPS_PORTS.join(", ")}. ${hard ? "A cf15 origin certificate is only valid behind Cloudflare, so this port won't work — pick one of those." : "If this panel is behind Cloudflare, this port won't be reachable."}<br/>
    If it IS behind Cloudflare, restrict this port to Cloudflare's IP ranges:<br/>
    <button class="btn btn-mini mt8" onClick=${() => copy(CF_IP_RANGES.join("\n"), "Cloudflare IP ranges")}><${Ic} i="copy"/> Copy Cloudflare IP ranges</button></span></div>`;

  // ── ONE action. The operator never chooses "save" vs "apply" or an order: this saves the config, then runs
  //    exactly the live-applies the change requires, safely. A panel address/cert change is applied with the
  //    dual-listen + browser-confirm dance (a wrong value auto-reverts — it can never lock you out). ──
  const _pPortN = () => Math.max(1, Math.min(65535, parseInt(pPort) || 443));
  const _sPortN = () => Math.max(1, Math.min(65535, parseInt(sPort) || 8444));
  const panelBindChanged = () => (pHost.trim() || "0.0.0.0") !== (orig.pHost || "0.0.0.0") || _pPortN() !== (+orig.pPort || 443);
  const subBindChanged   = () => (sHost.trim() || "0.0.0.0") !== (orig.sHost || "0.0.0.0") || _sPortN() !== (+orig.sPort || 8444);
  const certChanged      = () => mode !== (orig.mode || "") || email.trim() !== (orig.email || "") || !!cfTok || !!cfOrig;
  const urlChanged       = () => pUrl.trim() !== (orig.pUrl || "") || sUrl.trim() !== (orig.sUrl || "");
  const dirty            = () => panelBindChanged() || subBindChanged() || certChanged() || urlChanged();
  // Contention: the two services would trade ports on one host, so applying both at once needs one to bind a
  // port the other still holds — a single host can't do that atomically. Detect it and guide two saves instead
  // of attempting a doomed order (which is what produced the "Address already in use" + both-on-443 mess).
  const _overlap = (a, b) => { a = (a || "").trim() || "0.0.0.0"; b = (b || "").trim() || "0.0.0.0"; return a === b || a === "0.0.0.0" || b === "0.0.0.0"; };
  const subWantsPanelLive = () => subsOn && subBindChanged() && _sPortN() === (+orig.pPort || 443) && _overlap(sHost, orig.pHost);   // sub's target is the panel's current port
  const panelWantsSubLive = () => subsOn && panelBindChanged() && _pPortN() === (+orig.sPort || 8444) && _overlap(pHost, orig.sHost); // panel's target is the sub's current port

  // Wait for an in-flight subscription apply to reach a terminal state — so the panel apply below never binds
  // a port while the sub is still vacating it (the race that surfaced as "Address already in use").
  const _awaitSub = async () => {
    for (let i = 0; i < 60; i++) {                 // ~90s cap (a cert issuance can be slow); most settle in a few s
      const r = await api.get("/api/access/status").catch(() => null);
      const s = (r && r.sub) || {};
      if (["saved", "failed", "reverted", "idle"].includes(s.state)) return s;
      await new Promise(res => setTimeout(res, 1500));
    }
    return { state: "unknown", message: "The subscription update didn't finish in time." };
  };

  const saveAndApply = async () => {
    if (blocked) return setMsg({ ok: false, t: "Fix the highlighted port first." });
    if (!dirty()) return;
    // Trading ports between panel and sub can't be done in one shot on a single host — one must free its port
    // before the other can take it. Guide the operator through two saves instead of attempting a doomed order.
    if (subWantsPanelLive() || panelWantsSubLive()) {
      if (subWantsPanelLive() && panelWantsSubLive())
        return setMsg({ ok: false, t: "The panel and subscription are swapping ports — a single host can't swap two ports at once. First move one of them to a spare free port and Save, then set both to their final ports and Save again." });
      const first = subWantsPanelLive() ? "the panel" : "the subscription server";
      const second = subWantsPanelLive() ? "the subscription server" : "the panel";
      return setMsg({ ok: false, t: `The panel and subscription are trading ports. Do it in two saves so one frees the port before the other takes it: first move ${first} and Save, then set ${second}'s port and Save again.` });
    }
    const needSub = subsOn && (subBindChanged() || certChanged());
    const needPanel = panelBindChanged() || certChanged();
    setBusy(true); setMsg({ ok: true, t: "Saving your changes…" });
    const npUrl = normPublicUrl(pUrl), nsUrl = normPublicUrl(sUrl);   // add https:// when the operator omitted it
    setPUrl(npUrl); setSUrl(nsUrl);                                    // reflect it back in the fields
    const r = await api.panelSettings({ access: {
      panel: { url: npUrl, host: pHost.trim() || "0.0.0.0", port: _pPortN() },
      sub: { url: nsUrl, host: sHost.trim() || "0.0.0.0", port: _sPortN() },
      tls: { mode, email: email.trim(), cf_token: cfTok, cf_origin_token: cfOrig } } });
    if (!r || r.ok === false) { setBusy(false); return setMsg({ ok: false, t: (r && (r.error || (r.errors || []).join("; "))) || "Save failed." }); }
    const rtls = ((r.data || {}).access || {}).tls || {};        // redacted echo → refresh the "(set)" markers
    setHasCfTok(!!rtls.has_cf_token); setHasCfOrig(!!rtls.has_cf_origin_token); setCfTok(""); setCfOrig("");
    setOrig({ pUrl: npUrl, pHost: pHost.trim() || "0.0.0.0", pPort: String(_pPortN()),
      sUrl: nsUrl, sHost: sHost.trim() || "0.0.0.0", sPort: String(_sPortN()), mode, email: email.trim() });
    // subscription server first (a background restart — it can never lock you out of the panel). Don't start
    // polling yet: the panel apply below arms its pending, and we want the very first poll tick to already see
    // it (so the confirm-redirect fires immediately, not after a wasted interval).
    if (needSub) {
      setMsg({ ok: true, t: "Updating the subscription server…" });
      await api.post("/api/access/apply-sub", {});
      const ss = await _awaitSub();               // let it settle before the panel apply — no bind race
      if (ss.state === "failed") { setBusy(false); await resync(); return setMsg({ ok: false, t: ss.message || "The subscription server couldn't be updated." }); }
    }
    // then the panel address/cert (dual-listen + confirm — you'll be redirected briefly to prove it's reachable)
    if (needPanel) {
      const rp = await api.post("/api/access/apply", {});
      if (rp && rp.ok === false) { setBusy(false); await resync(); return setMsg({ ok: false, t: rp.error || "Couldn't apply the panel address." }); }
      if (rp && !rp.applied) {    // a live bind/cert change is in progress → status poll redirects to confirm on the first tick
        setMsg({ ok: true, t: "Verifying the new panel address is reachable — you'll be redirected in a moment…" });
        setPolling(true); return;
      }
    }
    if (needSub) setPolling(true);   // no panel redirect — just watch the sub restart finish
    setBusy(false);
    setMsg({ ok: true, t: needSub ? "Saved & applying — the subscription server is restarting." : (needPanel ? "Saved & applied." : "Saved.") });
  };

  // Report state up to the settings footer (which owns the Save button + status line, like every other section).
  // Runs after each render; the parent only re-renders when a DISPLAYED bit actually changes (see onAccess).
  useEffect(() => { if (onChange) onChange({ dirty: dirty() && !blocked, busy: busy || polling, msg, run: saveAndApply }); });

  return html`<div class="card acctls">
    <p class="hint" style="margin:0 0 12px">How the panel${subsOn ? " and subscription page are" : " is"} reached. Fill these in and press <b>Save</b> — the panel applies whatever changed, safely. A panel-address change is verified from your browser before it takes over, so a wrong value can never lock you out.</p>

    <div class="seclabel" style="margin-top:0">Certificate</div>
    <p class="hint" style="margin:0 0 12px">How TLS is terminated — this decides which ports are valid below. One choice issues both certificates (the panel's and swg-sub's, always separate keys).</p>
    <div class="field"><label>Type</label><${Dropdown} value=${mode} onChange=${setMode} options=${TLS_MODE_OPTS}/></div>
    ${(mode === "letsencrypt" || mode === "cloudflare") ? html`<div class="field"><label>Account email</label><input type="text" placeholder="admin@example.com" value=${email} onInput=${e => setEmail(e.target.value)}/></div>` : null}
    ${mode === "cloudflare" ? html`<div class="field"><label>Cloudflare API token</label><input type="password" placeholder=${hasCfTok ? "•••••••• (set — leave blank to keep)" : "Zone:DNS:Edit token"} value=${cfTok} onInput=${e => setCfTok(e.target.value)}/>
      <div class="hint">Used for DNS-01 validation. Stored on the panel only; never sent to the browser. Enter "-" to clear.</div></div>` : null}
    ${mode === "cf15" ? html`<div class="field"><label>Cloudflare Origin CA token</label><input type="password" placeholder=${hasCfOrig ? "•••••••• (set — leave blank to keep)" : "Zone:SSL and Certificates:Edit token"} value=${cfOrig} onInput=${e => setCfOrig(e.target.value)}/>
      <div class="hint">Requests a 15-year Cloudflare Origin certificate — valid <b>only</b> behind Cloudflare's proxy. Stored on the panel only. Enter "-" to clear.</div></div>` : null}

    <div class="seclabel">Panel address</div>
    <p class="hint" style="margin:0 0 12px">Where the panel itself is reached. If it's directly reachable, the URL's host and this port should match; behind a reverse proxy / Cloudflare, the URL is the public address.</p>
    <div class="field"><label>Public URL</label><input type="text" placeholder="https://panel.example.com" value=${pUrl} onInput=${e => setPUrl(e.target.value)}/></div>
    <div class="fieldrow">${ipField(pHost, setPHost, true)}${portField(pPort, setPPort, pBad)}</div>
    ${pBad ? cfNote : null}

    ${subsOn ? html`<div class="seclabel">Subscription address</div>
      <p class="hint" style="margin:0 0 12px">Where the swg-sub page is reached (a separate service; changing it only restarts swg-sub).</p>
      <div class="field"><label>Public URL</label><input type="text" placeholder="https://sub.example.com" value=${sUrl} onInput=${e => setSUrl(e.target.value)}/></div>
      <div class="fieldrow">${ipField(sHost, setSHost, false)}${portField(sPort, setSPort, sBad)}</div>
      ${sBad ? cfNote : null}` : null}
  </div>`;
}

// Subscription encryption setup. The Subscription Key is generated + wrapped IN THE BROWSER; the server only
// ever gets the wrapped form. It's shown once (like 2FA recovery codes) and is independent of the login password.
function SubVaultCard() {
  const [state, setState] = useState({ loading: true });
  const [pw, setPw] = useState(""); const [busy, setBusy] = useState(false);
  const [sk, setSk] = useState(null);                    // the shown-once Subscription Key
  const [resetMode, setResetMode] = useState(false); const [confirm, setConfirm] = useState("");
  const load = () => api.subVault().then(r => setState({ loading: false, exists: !!(r && r.ok && r.data && r.data.exists) })).catch(() => setState({ loading: false, exists: false }));
  useEffect(() => { load(); }, []);
  const create = async () => {
    if (!pw) return; setBusy(true);
    try { setSk(await subVaultCreate(pw)); setPw(""); }
    catch (e) { toast((e && e.message) || "Setup failed", "err"); }
    setBusy(false);
  };
  const doReset = async () => {
    setBusy(true); const r = await api.subReset(); setBusy(false);
    if (r && r.ok) { subForget(); setResetMode(false); setConfirm(""); setSk(null); load(); toast("Config encryption reset.", "ok"); }   // drop the now-stale cached SK
    else toast((r && r.error) || "Reset failed", "err");
  };
  if (state.loading) return html`<div class="hint">Checking…</div>`;
  if (sk) return html`<div class="notice ok"><div style="min-width:0">
    <b>Save your encryption key now — it is shown only once.</b> It protects every stored client config (and your subscriptions) and is independent of your login password; store it somewhere safe (a password manager). Lose it and your login both, and you'd re-key the affected peers.
    <div class="tokenbox" style="margin:8px 0;word-break:break-all">${sk}</div>
    <div class="chiprow">
      <button class="btn btn-mini" onClick=${() => copy(sk, "Encryption key copied")}><${Ic} i="copy"/> Copy</button>
      <button class="btn btn-mini" onClick=${() => downloadConf(sk, "swg-config-key")}><${Ic} i="download"/> Download</button>
      <span class="grow"></span>
      <button class="btn btn-primary btn-mini" onClick=${() => { setSk(null); load(); }}>I've saved it</button>
    </div></div></div>`;
  if (!state.exists) return html`<${Fragment}>
    <p class="hint" style="margin:0 0 8px">Set up once. Confirm your panel password — an encryption key is generated in your browser and shown once; the server only ever stores it wrapped, so it can't read your clients' private keys.</p>
    <div class="fieldrow">
      <div class="field"><label>Confirm password</label><input type="password" value=${pw} onInput=${e => setPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field" style="flex:none;align-self:end"><button class="btn btn-primary" disabled=${busy || !pw} onClick=${create}>${busy ? "Setting up…" : "Set up encryption"}</button></div>
    </div><//>`;
  return html`<${Fragment}>
    <div class="notice ok" style="margin-bottom:8px"><${Ic} i="check"/><span>Encryption is configured — stored configs are wrapped automatically, and their QRs (and any subscription links) keep working across your password changes.</span></div>
    ${resetMode
      ? html`<div class="notice warn"><div style="min-width:0"><b>Reset drops all stored encrypted configs and invalidates every subscription URL.</b> You'll set up a new encryption key afterwards, then re-issue affected peers. Type <b>RESET</b> to confirm.
          <div class="chiprow" style="margin-top:8px"><input type="text" placeholder="RESET" value=${confirm} onInput=${e => setConfirm(e.target.value)} style="max-width:120px"/>
            <button class="btn btn-danger btn-mini" disabled=${busy || confirm !== "RESET"} onClick=${doReset}>Reset encryption</button>
            <button class="btn btn-ghost btn-mini" onClick=${() => { setResetMode(false); setConfirm(""); }}>Cancel</button></div></div></div>`
      : html`<button class="btn btn-ghost btn-mini danger" onClick=${() => setResetMode(true)}>Reset encryption…</button>`}
  <//>`;
}
// The one-time "Encrypt stored configs" migration prompt — shown in Client configs whenever LEGACY plaintext
// configs are still on the panel (Store.configsPlaintext). Requires the vault (set it up in the card above first)
// + the encryption key unlocked; runs runConfigMigration (encrypt-all → capture overrides → purge plaintext where
// a blob exists), then reports peers that couldn't be encrypted (→ rekey). Resumable: re-running does the rest.
function ConfigMigrationCard() {
  useStore();                          // re-render as the plaintext count drops after a pass
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState("");
  const [report, setReport] = useState(null);
  const [vaultExists, setVaultExists] = useState(true);
  useEffect(() => { api.subVault().then(r => setVaultExists(!!(r && r.ok && r.data && r.data.exists))).catch(() => {}); }, []);
  const n = Store.configsPlaintext || 0;
  if (n <= 0 && !report) return null;                          // nothing to migrate
  const flaggedNames = report ? report.flagged.map(pid => {
    const p = (Store.recon.peers || []).find(x => x.id === pid) || {};
    return (p.name ? p.name + " · " : "") + (p.title || "peer");
  }) : [];
  const run = async () => {
    if (!subSKCached()) {                                  // a cached SK ⇒ the vault exists (e.g. just set up this session)
      if (!vaultExists) { toast("Set up the encryption key above first.", "err"); return; }
      if (!pw) { toast("Enter your panel password to unlock the encryption key.", "err"); return; }
      try { await subUnlock(pw); setPw(""); } catch (e) { toast((e && e.message) || "Unlock failed", "err"); return; }
    }
    setBusy(true);
    try {
      const rep = await runConfigMigration();
      setReport(rep);
      toast(`Encrypted ${rep.migrated} config${rep.migrated === 1 ? "" : "s"}${rep.purged ? `, purged ${rep.purged} plaintext` : ""}.`, "ok");
    } catch (e) { toast((e && e.message) || "Migration failed", "err"); }
    setBusy(false);
  };
  const pwField = html`<input class="subpw" type="password" style="max-width:220px" value=${pw} autocomplete="off"
    placeholder="Panel password (unlocks the encryption key)" onKeyDown=${e => { if (e.key === "Enter") run(); }} onInput=${e => setPw(e.target.value)}/>`;
  return html`<div class=${"notice " + (n > 0 ? "warn" : "ok")} style="margin-top:10px"><div style="min-width:0">
    ${n > 0
      ? html`<b>${n} plaintext config${n === 1 ? "" : "s"} still on the panel.</b> Encrypt them so the server can no longer read a client private key. Safe and resumable — the plaintext is deleted only after its encrypted copy exists.`
      : html`<b>All stored configs are encrypted.</b>`}
    ${report ? html`<div class="hint" style="margin-top:8px">Encrypted <b>${report.migrated}</b> of ${report.total} · purged <b>${report.purged}</b> plaintext${report.orphansPurged ? ` (+${report.orphansPurged} orphan)` : ""}${report.remaining ? ` · ${report.remaining} still plaintext` : ""}.
      ${report.flagged.length ? html`<div style="margin-top:6px"><b>${report.flagged.length} peer${report.flagged.length === 1 ? "" : "s"}</b> couldn't be encrypted (unassigned, or no stored key) — <b>rekey</b> or assign ${report.flagged.length === 1 ? "it" : "them"} to include: ${flaggedNames.slice(0, 8).join(", ")}${flaggedNames.length > 8 ? ` +${flaggedNames.length - 8} more` : ""}.</div>` : html`<div style="margin-top:6px">Every assigned peer with a stored key is encrypted.</div>`}</div>` : null}
    <div class="chiprow" style="margin-top:8px">
      ${(n > 0 && !subSKCached()) ? pwField : null}
      ${n > 0 ? html`<button class="btn btn-primary btn-mini" disabled=${busy || (!vaultExists && !subSKCached())} onClick=${run}>${busy ? "Encrypting…" : (report ? "Encrypt remaining" : "Encrypt stored configs")}</button>` : null}
    </div>
  </div></div>`;
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
  const retryProvider = async (pid) => {   // manual retry after a provider's automatic fetch retries (4×, backoff) all failed
    const r = await api.geoProviderRetry(pid);
    if (!r || !r.ok) return toast((r && r.error) || "Couldn't retry", "err");
    const t0 = Date.now();
    const tick = async () => { await Store.poll();
      const busy = (Store.catalogProviders || []).some(p => p.id === pid && p.status === "downloading");
      if (busy && Date.now() - t0 < 25000) return setTimeout(tick, 1500); };
    setTimeout(tick, 1500);
  };
  // Transient "updated" / "up to date" — show for 5s AFTER a busy→done transition, then hide. In-progress
  // (downloading/updating) always shows; failed persists (with Retry). No flash on first load (statuses stay hidden).
  const [provFlash, setProvFlash] = useState({});   // pid -> expiry ts
  const _provSeen = useRef({});
  useEffect(() => {
    const now = Date.now(), seen = _provSeen.current; let next = null;
    for (const p of (Store.catalogProviders || [])) {
      const prev = seen[p.id];
      if (p.status !== prev) {
        if (prev !== undefined && (p.status === "updated" || p.status === "uptodate")) { next = next || { ...provFlash }; next[p.id] = now + 5000; }
        seen[p.id] = p.status;
      }
    }
    if (next) setProvFlash(next);
  }, [Store.catalogProviders]);
  useEffect(() => {
    const exps = Object.values(provFlash).filter(t => t > Date.now());
    if (!exps.length) return;
    const t = setTimeout(() => setProvFlash(f => ({ ...f })), Math.min(...exps) - Date.now() + 50);
    return () => clearTimeout(t);
  }, [provFlash]);
  const _scMode = Store.storeMode || "encrypted";   // the RESOLVED enum (server considers the panel/fleet default)
  const [sc, setSc] = useState(_scMode);
  const [tput, setTput] = useState(ps.throughput_perspective === "peers" ? "peers" : "nodes");
  const [staleS, setStaleS] = useState(String(Math.round((adv.node_stale_ms || 30000) / 1000)));
  const [graceS, setGraceS] = useState(String(Math.round((adv.peer_grace_ms || 60000) / 1000)));
  const [ttlD, setTtlD] = useState(String(adv.geo_ttl_days || 3));
  const [topTalk, setTopTalk] = useState(String(ps.top_talkers || 10));
  const [topDest, setTopDest] = useState(String(ps.top_destinations || 10));
  const [hidden, setHidden] = useState(new Set(ps.hidden_categories || []));   // built-in categories hidden from the routing dropdown
  const [lists, setLists] = useState((ps.custom_lists || []).map(l => ({ ...l, _rid: newRid(), targets: [...(l.domains || []), ...(l.cidrs || [])].join(", ") })));
  const [turnEnabledS, setTurnEnabledS] = useState(ps.turn_enabled !== false);   // master turn-proxy switch
  const [turnForks, setTurnForks] = useState(new Set(ps.enabled_turn_forks || ["WINGS-N", "anton48"]));   // forks offered in the install picker
  const [vkLinkS, setVkLinkS] = useState(ps.vk_link || "");   // VK call link baked into generated turn-proxy client configs
  // ---- themed colour pickers ({dark,light} each) — Interfaces / Display / Turn sections ----
  const asThemed = (v, dd, dl) => (v && typeof v === "object") ? { dark: v.dark || dd, light: v.light || dl } : { dark: v || dd, light: v || dl };
  const sameThemed = (a, dd, dl) => (a.dark || "").toLowerCase() === dd.toLowerCase() && (a.light || "").toLowerCase() === dl.toLowerCase();
  const _provColDefault = p => { const d = CAT_PROVIDER_DEFAULTS[p] || (p === "custom" ? { color: "#8A94A6", colorL: "#5E6875" } : { color: "#8FA8C0", colorL: "#5E7085" }); return { dark: d.color, light: d.colorL }; };
  const _provColKeys = [..._provReg.map(p => p.id), "custom"];
  const [provColors, setProvColors] = useState(() => Object.fromEntries(_provColKeys.map(k => [k, asThemed((ps.provider_colors || {})[k], _provColDefault(k).dark, _provColDefault(k).light)])));
  const provColorOverrides = () => { const o = {}; for (const k of _provColKeys) { const d = _provColDefault(k); const t = asThemed(provColors[k], d.dark, d.light); if (!sameThemed(t, d.dark, d.light)) o[k] = t; } return o; };
  const [customEnabled, setCustomEnabled] = useState(ps.custom_lists_enabled !== false);
  const [forkColors, setForkColors] = useState(() => Object.fromEntries(TURN_FORKS.map(f => [f.id, asThemed((ps.turn_fork_colors || {})[f.id], f.color, f.colorL)])));
  const _tu = ps.turn_update || {};   // turn-proxy auto-update schedule: every_days (0=off) + node-checked panel-local hour
  const [tuEvery, setTuEvery] = useState(String(_tu.every_days == null ? 0 : _tu.every_days));
  const [tuAt, setTuAt] = useState(_tu.at || "04:00");
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
  const [sec2fa, setSec2fa] = useState(false);    // TOTP currently enabled on the account
  useEffect(() => { api.account().then(r => { if (r && r.ok) { setSecAuth(r.data.auth_enabled !== false); setSec2fa(!!r.data.twofa_enabled); if (r.data.username) { setSecUser(r.data.username); setSecOrigUser(r.data.username); } } }); }, []);
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
  const [section, setSection] = useState(pendingSettingsSection || "display");   // active left-rail section (a Settings activity click can deep-link here)
  useEffect(() => { pendingSettingsSection = null; }, []);   // one-shot: don't pin the section on later visits
  const rsv = ps.reserved || {};
  const [rsvSubnet, setRsvSubnet] = useState(rsv.mesh_subnet || "10.255.0.0/16");
  const [rsvPort, setRsvPort] = useState(String(rsv.mesh_port_base || 9999));
  const [rsvPrefix, setRsvPrefix] = useState(rsv.iface_prefix || "swg_");
  const [awg, setAwg] = useState(ps.mesh_awg || {});
  const [showAwg, setShowAwg] = useState(false);
  const awgSet = AWG_KEYS.some(k => String(awg[k] ?? "").trim() !== "");
  const [showAdv, setShowAdv] = useState(false);
  const [msg, setMsg] = useState(null);
  // subscriptions section state — enable + languages ride the global save; the vault ceremony uses /api/sub/*.
  // The sub's address, URL and certificate now live in the Access & TLS section (access.sub / access.tls).
  const subCfg = ps.subscriptions || {};
  const [subsOn, setSubsOn] = useState(!!subCfg.enabled);
  const subLangCfg = (subCfg.languages && typeof subCfg.languages === "object") ? subCfg.languages : {};
  const [subLangs, setSubLangs] = useState((subLangCfg.enabled && subLangCfg.enabled.length) ? [...subLangCfg.enabled] : ["en"]);
  const [subLangDef, setSubLangDef] = useState(subLangCfg.default || "en");
  const toggleSubLang = (id, on) => {
    let next = on ? [...new Set([...subLangs, id])] : subLangs.filter(l => l !== id);
    if (!next.length) next = [id];                 // never empty — at least one language
    setSubLangs(next);
    if (next.indexOf(subLangDef) < 0) setSubLangDef(next[0]);   // default must stay enabled
  };
  // per-node pending edits (mode / mesh / egress) — lifted here so switching node or section keeps unsaved
  // changes; the single Save commits the global settings AND one nodeUpdate per changed node.
  const eq = (a, b) => { const c = v => v == null ? "" : Array.isArray(v) ? JSON.stringify([...v].sort()) : typeof v === "object" ? JSON.stringify(Object.keys(v).sort().reduce((o, k) => (o[k] = v[k], o), {})) : String(v); return c(a) === c(b); };
  const nFields = n => ({ routing_mode: n.routing_mode || "kernel", ip_learning: n.ip_learning !== false, endpoint_host: n.endpoint_host || "",
    mesh_subnet: n.mesh_subnet || "", mesh_port: n.mesh_port ? String(n.mesh_port) : "", mesh_prefix: n.mesh_prefix || "",
    default_egress_ip: n.default_egress_ip || "", panel_ip: n.panel_ip || "",
    enabled_categories: (n.enabled_categories && n.enabled_categories.length) ? [...n.enabled_categories] : null,   // null = all built-ins enabled for this node
    catalog_cats: [...(n.catalog_cats || [])],   // provider-catalog categories opted into on this node (node-lens; separate from the 26 built-ins)
    mesh_awg: (n.mesh_awg_set && Object.keys(n.mesh_awg_set).length) ? { ...n.mesh_awg_set } : {} });   // per-node mesh obfuscation override ({} = inherit/auto)
  const [nodeEdits, setNodeEdits] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [orig, setOrig] = useState(() => Object.fromEntries((Store.nodes || []).map(n => [n.id, nFields(n)])));
  const [gridKeep, setGridKeep] = useState([]);   // provider-list rows kept visible after toggling to 0/N nodes (until × removes them)
  const setNV = (nid, patch) => setNodeEdits(e => ({ ...e, [nid]: { ...nFields((Store.nodes || []).find(n => n.id === nid) || {}), ...(e[nid] || {}), ...patch } }));
  const nv = (nid, f) => (nodeEdits[nid] || {})[f];
  const [saved, setSaved] = useState(0);   // timestamp; the green "All settings saved" flash shows while now < saved
  // Access & TLS reports its {dirty,busy,msg,run} up here so the shared footer drives its Save + status like every
  // other section. The ref always holds the latest; accessSig re-renders the footer only when a shown bit changes.
  const accessRef = useRef({ dirty: false, busy: false, msg: null, run: () => {} });
  const [, setAccessSig] = useState("");
  const onAccess = useCallback(s => {
    accessRef.current = s;
    const sig = (s.dirty ? "1" : "0") + (s.busy ? "1" : "0") + "|" + (s.msg ? (s.msg.ok ? "o" : "e") + s.msg.t : "");
    setAccessSig(prev => prev === sig ? prev : sig);
  }, []);
  const save = async () => {
    setMsg({ ok: true, t: "Saving…" });
    if (SECTIONS.some(([s]) => glDirty(s))) {   // only rewrite panel_settings when a GLOBAL setting actually changed (nodes go via nodeUpdate below)
      const dirtySecs = SECTIONS.filter(([s]) => glDirty(s)), secLabel = Object.fromEntries(SECTIONS);   // for the activity one-liner + deep-link
      const r = await api.panelSettings({
        _ev: { first: (dirtySecs[0] || [""])[0], sections: dirtySecs.map(([s]) => secLabel[s]).join(", ") },   // display-only: which sections changed (drives the "Settings changed" activity row)
        interface_defaults: { dns: dns.split(",").map(s => s.trim()).filter(Boolean), mtu: +mtu || 1280, keepalive: +ka || 25 },
        mirrors: { geo: geoMir.trim(), turn: turnMir.trim() },
        providers: provEnabled,
        provider_colors: provColorOverrides(),
        custom_lists_enabled: customEnabled,
        geo_update: { every_days: Math.max(0, Math.min(30, parseInt(guEvery) || 0)), at: guAt },
        store_configs: sc === "off" ? "off" : "encrypted",
        subscriptions: { enabled: subsOn,   // base_url + serve now live in Access & TLS (access.sub/access.tls)
          languages: { enabled: subLangs, default: subLangDef } },
        throughput_perspective: tput,
        top_talkers: Math.max(1, Math.min(50, parseInt(topTalk) || 10)),
        top_destinations: Math.max(1, Math.min(50, parseInt(topDest) || 10)),
        reserved: { mesh_subnet: rsvSubnet.trim(), mesh_port_base: +rsvPort || 9999, iface_prefix: rsvPrefix.trim() || "swg_" },
        mesh_awg: awgSet ? awg : {},
        advanced: { node_stale_ms: (+staleS || 30) * 1000, peer_grace_ms: (+graceS || 60) * 1000, geo_ttl_days: +ttlD || 3 },
        hidden_categories: [...hidden],
        custom_lists: lists.map(({ _rid, domains, cidrs, ...l }) => l),   // send id/title/targets/enabled; backend re-derives domains+cidrs
        turn_enabled: turnEnabledS,
        turn_update: { every_days: Math.max(0, Math.min(30, parseInt(tuEvery) || 0)), at: tuAt },
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
      const nr = await api.nodeUpdate({ id: n.id, routing_mode: e.routing_mode, ip_learning: e.ip_learning !== false, endpoint_host: (e.endpoint_host || "").trim(),
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
      if (secNp) await subRewrap(secNp);   // keep the config-encryption convenience cache unlockable with the new password
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
    if (glDirty("routing")) out.push("Routing lists — presets / custom");
    if (secChanged()) out.push("Authentication — panel credentials");
    if (glDirty("turn")) out.push("Turn proxies — forks / colours / VK link");
    if (glDirty("geo")) out.push("Geo data");
    if (glDirty("defaults")) out.push("Interfaces — colours / defaults");
    if (glDirty("configs")) out.push("Client configs → " + (sc === "off" ? "off" : "encrypted"));
    if (glDirty("display")) out.push("Display — theme / status timing");
    if (glDirty("mesh")) out.push("System mesh defaults");
    for (const n of (Store.nodes || [])) {
      const e = nodeEdits[n.id] || {}, o = orig[n.id] || {}, fl = [];
      if (!eq(e.routing_mode, o.routing_mode)) fl.push("mode → " + e.routing_mode);
      if (!eq(e.ip_learning !== false, o.ip_learning !== false)) fl.push("IP learning → " + (e.ip_learning !== false ? "on" : "off"));
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
  const openList = l => openModal(html`<${CustomListSheet} list=${l} onSave=${nl => persistLists(l ? lists.map(x => x._rid === nl._rid ? nl : x) : [...lists, nl])} onClose=${closeModal}/>`);
  const confirmDeleteList = l => openConfirm({ title: "Delete custom list", confirmLabel: "Delete", danger: true,
    body: html`Delete <b>${l.title || "Untitled list"}</b>? It's removed from <b>every node</b> it's enabled on, and its interface rules stop matching on the next sync. This can't be undone.`,
    onConfirm: () => persistLists(lists.filter(x => x._rid !== l._rid)) });
    const SECTIONS = [["display", "Display"], ["security", "Authentication"], ["access", "Access & TLS"], ["configs", "Client configs"], ["subs", "Subscriptions"], ["mesh", "System mesh"], ["nodesegress", "Nodes egress"], ["defaults", "Interfaces"], ["turn", "Turn proxies"], ["routing", "Routing lists"], ["geo", "Geo data"], ["integrations", "Integrations"]];
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
  const nodeMode = nv(selNode, "routing_mode") || "kernel";       // DRAFT mode being edited (drives the mode card + tabs)
  const setMode = m => setNV(selNode, { routing_mode: m });
  const savedMode = (nodeRec && nodeRec.routing_mode) || "kernel"; // what the node is ACTUALLY running (drives the status runbar — only changes on Save)
  const ipLearn = nv(selNode, "ip_learning") !== false;           // per-node "remember learned IPs" toggle (default on)
  const setIpLearn = v => setNV(selNode, { ip_learning: v });
  const hostDegraded = savedMode === "sni_kernel" && (((Store.stats[selNode] || {}).smartroute || {}).engine === "sni_user");   // → HostHealth shows a 2nd (note) line
  const ecOf = nid => nv(nid, "enabled_categories");               // per-node enabled built-ins (null = all)
  const catOn = id => { const ec = ecOf(selNode); return !ec || ec.includes(id); };
    // node-lens for the provider catalog: catalog_cats[] = the categories the operator opted THIS node into (staged; commits on Save)
  const ccOf = nid => nv(nid, "catalog_cats") || [];
  const addCatalogCat = id => { if (!id || id === "all" || (lists || []).some(l => l.id === id) || id === "custom") return; setNV(selNode, { catalog_cats: [...new Set([...ccOf(selNode), id])] }); };   // provider cats + curated presets (bare id) are both first-class opt-ins
  const removeCatalogCat = id => setNV(selNode, { catalog_cats: ccOf(selNode).filter(c => c !== id) });
  // Fleet-wide provider-list grid: rows = the union of every node's opted-in provider cats. gridKeep holds ids that
  // must stay visible even at 0/N nodes (so toggling PULL off doesn't make the row vanish — only × removes it).
  const fleetNodes = Store.nodes || [];
  const catOnNode = (id, nid) => ccOf(nid).includes(id);
  const setCatOnNode = (id, nid, on) => setNV(nid, { catalog_cats: on ? [...new Set([...ccOf(nid), id])] : ccOf(nid).filter(c => c !== id) });
  const pullCatOnNode = (id, on) => { setCatOnNode(id, selNode, on); if (!on) setGridKeep(g => g.includes(id) ? g : [...g, id]); };   // keep the row even at 0/N
  const fleetToggleCat = (id, nid, on) => { setCatOnNode(id, nid, on); if (!on) setGridKeep(g => g.includes(id) ? g : [...g, id]); };   // fleet popover toggle: keep the row visible at 0/N
  const removeCatFleet = id => { fleetNodes.forEach(n => { if (ccOf(n.id).includes(id)) setCatOnNode(id, n.id, false); }); setGridKeep(g => g.filter(x => x !== id)); };   // × drops it everywhere + hides the row
  const provFleetCats = [...new Set([...fleetNodes.flatMap(n => ccOf(n.id)), ...gridKeep])].sort((a, b) => catLabelOf(a).toLowerCase().localeCompare(catLabelOf(b).toLowerCase()));
  const compatCats = () => provFleetCats.filter(id => nodeMode !== "kernel" || catCap(id).ip);   // usable on selNode in its mode
  const allCompatOn = () => compatCats().length > 0 && compatCats().every(id => catOnNode(id, selNode));
  const toggleAllCompat = () => { const off = allCompatOn();
    if (off) setGridKeep(g => [...new Set([...g, ...compatCats()])]);              // Disable all: keep the rows visible (0/N)
    setNV(selNode, { catalog_cats: off ? ccOf(selNode).filter(id => !compatCats().includes(id)) : [...new Set([...ccOf(selNode), ...compatCats()])] }); };
  const confirmRemoveCat = id => openConfirm({ title: "Remove list from the fleet", confirmLabel: "Remove", danger: true,
    body: html`Remove <b>${catLabelOf(id)}</b> <span class="faint">(${provLabelOf(id)})</span> from <b>every node</b>? Interface rules that use it stop matching, and each node drops its records on the next sync. You can add it back from the catalog any time.`,
    onConfirm: () => removeCatFleet(id) });
  const customOnNode = (l, nid) => !(l.disabled_nodes || []).includes(nid);
  const setCustomOnNode = (l, nid, on) => persistLists(lists.map(x => x._rid === l._rid ? { ...x, disabled_nodes: on ? (x.disabled_nodes || []).filter(z => z !== nid) : [...new Set([...(x.disabled_nodes || []), nid])] } : x));
  // dirty tracking — per global section + per node-per-section, drives the rail dots and badge glow
  const SECF = { routing: ["routing_mode", "ip_learning", "enabled_categories", "catalog_cats"], mesh: ["endpoint_host", "mesh_subnet", "mesh_port", "mesh_prefix", "mesh_awg"], nodesegress: ["default_egress_ip", "panel_ip"] };
  const nodeDirty = (nid, sec) => (SECF[sec] || []).some(f => !eq((nodeEdits[nid] || {})[f], (orig[nid] || {})[f]));
  const listsJSON = ls => JSON.stringify((ls || []).map(l => ({ id: l.id || "", title: l.title || "", enabled: l.enabled !== false, targets: (l.targets ?? [...(l.domains || []), ...(l.cidrs || [])].join(", ")).trim() })));
  const glDirty = sec =>
    sec === "routing" ? ([...hidden].sort().join() !== (ps.hidden_categories || []).slice().sort().join() || listsJSON(lists) !== listsJSON(ps.custom_lists || [])) :
    sec === "turn" ? (turnEnabledS !== (ps.turn_enabled !== false) || [...turnForks].sort().join() !== (ps.enabled_turn_forks || ["WINGS-N", "anton48"]).slice().sort().join() || JSON.stringify(forkColorOverrides()) !== JSON.stringify(forkOvFrom(ps.turn_fork_colors)) || vkLinkS.trim() !== (ps.vk_link || "") || String(Math.max(0, parseInt(tuEvery) || 0)) !== String((ps.turn_update || {}).every_days == null ? 0 : (ps.turn_update || {}).every_days) || tuAt !== ((ps.turn_update || {}).at || "04:00")) :
    sec === "security" ? secChanged() :
    sec === "geo" ? (JSON.stringify(provEnabled) !== JSON.stringify(Object.fromEntries((Store.catalogProviders || []).map(p => [p.id, p.enabled !== false]))) || JSON.stringify(provColorOverrides()) !== JSON.stringify(ps.provider_colors || {}) || customEnabled !== (ps.custom_lists_enabled !== false) || String(Math.max(0, parseInt(guEvery) || 0)) !== String(_gu.every_days == null ? 1 : _gu.every_days) || guAt !== (_gu.at || "04:00")) :
    sec === "defaults" ? (dns !== (idf.dns || []).join(", ") || mtu !== String(idf.mtu || 1280) || ka !== String(idf.keepalive || 25) || JSON.stringify(ifaceColorOverrides()) !== JSON.stringify(ifaceOvFrom(ps.iface_colors)) || JSON.stringify(statusCondsOut()) !== JSON.stringify({ blocked: (ps.status_conditions || {}).blocked !== false, faulty: (ps.status_conditions || {}).faulty !== false })) :
    sec === "configs" ? (sc !== _scMode) :
    sec === "subs" ? (subsOn !== !!subCfg.enabled || JSON.stringify([...subLangs].sort()) !== JSON.stringify([...(subLangCfg.enabled || ["en"])].sort()) || subLangDef !== (subLangCfg.default || "en")) :
    sec === "display" ? (tput !== (ps.throughput_perspective === "peers" ? "peers" : "nodes") || staleS !== String(Math.round((adv.node_stale_ms || 30000) / 1000)) || graceS !== String(Math.round((adv.peer_grace_ms || 60000) / 1000)) || topTalk !== String(ps.top_talkers || 10) || topDest !== String(ps.top_destinations || 10) || themeColorS.toLowerCase() !== clampBrand(ps.theme_color || THEME_COLOR_DEFAULT, false).toLowerCase() || themeColorLightS.toLowerCase() !== clampBrand(ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT, true).toLowerCase()) :
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
    ["kernel", "Default — IP only. DNS not involved", "Matches by destination IP (GeoIP / ASN) — routing never depends on DNS, so your clients' DoH, DoT and plain DNS all keep working untouched. Simplest and most robust; it just can't separate services that share IPs (YouTube vs Google), and a CDN category catches everything behind it. Lists: GeoIP + Custom IPs."],
    ["forcedns", "Force DNS — Host + IP. Overrides encrypted DNS", "The node becomes your clients' resolver and blocks their encrypted DNS — both DoH (known providers) and all DoT — so it can route by hostname too, per-service precise. Trade-off: it sees and downgrades the client's DNS, can break a client that insists on its own encrypted DNS, and a DoH server it doesn't recognise can still slip past. Lists: GeoSite (host) + GeoIP + Custom IPs/domains."],
    ["sni", "SNI Sniffer — Host + IP. DNS stays private", "Routes by hostname by reading the SNI from each TLS handshake, so your clients' DNS — DoH, DoT or plain — is never touched, observed or downgraded: the connection stays encrypted end-to-end. Learns each destination on its first connection (a brand-new host routes on the next one); names hidden by ECH, and QUIC / HTTP3, fall back to IP routing. Lists: GeoSite (host) + GeoIP + Custom IPs/domains."],
  ];
  return html`<div class="screen setscreen">
    <div class="sethead"><b>Panel settings</b></div>
    ${msg ? html`<div class=${"formmsg " + (msg.ok ? "ok" : "err")}>${msg.t}</div>` : null}
    <div class="setbody">
      <nav class="setrail">${SECTIONS.map(([id, lbl]) => html`<button class=${"setrail-i" + (section === id ? " on" : "")} onClick=${() => setSection(id)}>${lbl}${secDirty(id) ? html`<span class="dirtydot"></span>` : null}</button>`)}</nav>
      <div class="setpane">
        ${perNodeSection && (Store.nodes || []).length ? html`<div class="setnodes">${(Store.nodes || []).map(n => html`<button class=${"snbadge" + (selNode === n.id ? " on" : "") + (badgeDirty(n.id) ? " dirty" : "")} style=${"--c:" + Store.nodeColor(n.id)} onClick=${() => setSelNode(n.id)}><span class="ndot"></span>${n.name}</button>`)}</div>` : null}
        ${section === "routing" ? html`<div class="card rcard">
          ${(() => { const mm = MODE_META[nodeMode] || MODE_META.kernel;
            const resetBtn = html`<button class="rmode-reset" title="Wipe or refresh this node's smart routing — learned IPs and/or the full rebuild" onClick=${() => resetRouting(selNode, nodeRec ? nodeRec.name : "this node")}><${Ic} i="refresh"/> Reset routing</button>`;
            const mmRun = MODE_META[savedMode] || MODE_META.kernel;   // runbar reflects the SAVED/running mode, not the draft
            const caption = html`<div class="rmr-title"><b class="rmr-node">${nodeRec ? nodeRec.name : "Node"}</b> currently runs on <b class="rmr-mode">${mmRun.label}</b></div>`;
            const infoPop = html`<${Popover} hoverOnly cls="rmode-info" popCls="rmode-info-pop" trigger=${html`<span class="rmode-infobtn"><${Ic} i="info"/></span>`}>
                  <div class="rmode-info-body">Every mode matches by destination <b>IP</b> first (GeoIP / ASN / your IP lists) — that layer is <b>always on</b> and carries all traffic, including calls, UDP and QUIC. The choice adds an optional <b>host (domain)</b> matching layer on top: none, via the node's <b>DNS</b>, or read from the <b>TLS handshake</b>. Traffic always stays in-kernel in any mode including <b>Hybrid SNI</b> (no userspace proxy). Changing it reconfigures ${nodeRec ? nodeRec.name : "the node"} and changes which lists its interfaces can use.<div style="margin-top:9px"><b>Reset routing</b> recovers a stuck node — clear just the learned IPs, or wipe + rebuild + re-pull everything.</div></div>
                <//>`;
            const runbar = savedMode === "kernel"
              ? html`<div class="rmode-runbar">
                  ${caption}
                  <span class="grow"></span>
                  <div class="rmr-actions">${resetBtn}${infoPop}</div>
                </div>`
              : html`<div class="rmode-runbar">
                  <div class="rmr-left">
                    <${HostHealth} node=${selNode} mode=${savedMode} learn=${ipLearn} onLearn=${setIpLearn}/>
                    ${!hostDegraded ? resetBtn : null}
                  </div>
                  <span class="grow"></span>
                  <div class="rmr-right">
                    <div class="rmr-rtop">${caption}${infoPop}</div>
                    ${hostDegraded ? resetBtn : null}
                  </div>
                </div>`;
            return html`
          ${runbar}
          <div class=${"rmode-banner m-" + nodeMode}>
            <div class="rd-head">
              <div class="rd-headmain">
                <div class="rd-titlerow">
                  <span class="rd-ic"><${Ic} i=${mm.icon}/></span>
                  <b class="rd-name">${mm.label}</b>
                  <span class="rmc-tag">${mm.short}</span>
                </div>
                <div class="rd-adds">${mm.adds}</div>
              </div>
              <${ModeTabs} value=${nodeMode} onChange=${setMode}/>
            </div>
            <div class="rd-lines">
              ${(mm.bene || []).map(b => html`<div class="rmc-bene"><b>+</b><span>${b}</span></div>`)}
              <div class="rmc-cost"><b>−</b><span>${mm.cost}</span></div>
            </div>
            <div class="rmode-desc">${mm.exp}</div>
            ${mm.lists ? html`<div class="rmode-lists">${mm.lists.map((l, i) => html`${i ? " + " : ""}<b>${l}</b>`)}</div>` : null}
          </div>`; })()}

          <div class="lgrid-head">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">Provider lists</span><span class="lg-count">${provFleetCats.length}</span><span class="faint lg-sub">provider-maintained · read-only</span></div>
            <span class="grow"></span>
            ${compatCats().length ? html`<button class="btn btn-mini" onClick=${toggleAllCompat}>${allCompatOn() ? "Disable all" : "Enable all"}</button>` : null}
            <${CatPicker} addMode=${true} primary=${true} mode=${nodeMode} triggerLabel="Add preset list" selected=${ccOf(selNode)} onChange=${id => ccOf(selNode).includes(id) ? removeCatalogCat(id) : addCatalogCat(id)} onAdd=${id => { if (!ccOf(selNode).includes(id)) addCatalogCat(id); }}/>
          </div>
          ${provFleetCats.length ? html`<div class="lgrid">
            ${provFleetCats.map(id => { const cap = catCap(id); const usable = nodeMode !== "kernel" || cap.ip; const sz = (Store.catSizes || {})[id] || {};
              return html`<div class=${"lgrow" + (usable ? "" : " lg-lock")} key=${id}>
                <div class="lg-pull"><${Switch} on=${catOnNode(id, selNode)} disabled=${!usable} title=${usable ? "Pull this list on " + (nodeRec ? nodeRec.name : "this node") : "Host-only — needs Force-DNS or SNI on this node"} onChange=${v => pullCatOnNode(id, v)}/></div>
                <div class="lg-cat"><span class="lg-title">${catLabelOf(id)}</span><span class="lg-id">${catRawId(id)}</span>${provLabelOf(id) ? html`<${ProvTag} id=${id}/>` : null}</div>
                <div class="lg-size">${sizeSummary(sz.host || 0, sz.ip || 0) || html`<span class="faint">—</span>`}</div>
                <div class="lg-fleet"><${FleetAssign} nodes=${fleetNodes} isOn=${nid => catOnNode(id, nid)} onToggle=${(nid, on) => fleetToggleCat(id, nid, on)} disabledFor=${nid => (nv(nid, "routing_mode") || "kernel") === "kernel" && !cap.ip ? "Host-only — this node is IP-only" : null}/></div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act">${catListUrl(id, cap) ? html`<a class="ccchip-info" href=${catListUrl(id, cap)} target="_blank" rel="noopener" title="View this list on GitHub"><${Ic} i="info"/></a>`
                  : catDescOf(id) ? html`<${DescInfo} text=${catDescOf(id)}/>` : null}<button class="ccchip-x" title="Remove from the fleet" onClick=${() => confirmRemoveCat(id)}><${Ic} i="x"/></button></div>
              </div>`; })}
          </div>` : html`<div class="hint" style="margin:2px 0 0">No preset lists yet — use <b>Add preset list</b> to pull from the catalog.</div>`}

          ${(Store.panelSettings || {}).custom_lists_enabled !== false ? html`
          <div class="lgrid-head" style="margin-top:26px">
            <div class="lg-htitle"><span class="seclabel" style="margin:0">Custom lists</span><span class="lg-count">${lists.length}</span><span class="faint lg-sub">your own IPs / domains · editable · apply immediately</span></div>
            <span class="grow"></span>
            <button class="btn btn-add" onClick=${() => openList(null)}><${Ic} i="plus"/> New custom list</button>
          </div>
          ${lists.length ? html`<div class="lgrid">
            ${[...lists].sort((a, b) => (a.title || "").toLowerCase().localeCompare((b.title || "").toLowerCase())).map(l => { const cap = customCaps(l);
              return html`<div class="lgrow" key=${l._rid}>
                <div class="lg-pull"><${Switch} on=${customOnNode(l, selNode)} title=${"Enable on " + (nodeRec ? nodeRec.name : "this node")} onChange=${v => setCustomOnNode(l, selNode, v)}/></div>
                <div class="lg-cat"><button class="lg-title asbtn" onClick=${() => openList(l)}>${l.title || "Untitled list"}</button><button class="lg-id asbtn" onClick=${() => openList(l)}>edit</button><span class="catpick-src" style=${"--pc:" + providerColor("custom")}>Custom</span></div>
                <div class="lg-size"><${ListInfo} list=${l}/></div>
                <div class="lg-fleet"><${FleetAssign} nodes=${fleetNodes} isOn=${nid => customOnNode(l, nid)} onToggle=${(nid, on) => setCustomOnNode(l, nid, on)}/></div>
                <div class="lg-caps">${capBadges(cap)}</div>
                <div class="lg-act"><button class="ccchip-x" title="Delete this list" onClick=${() => confirmDeleteList(l)}><${Ic} i="x"/></button></div>
              </div>`; })}
          </div>` : html`<div class="hint" style="margin:2px 0 0">No custom lists yet.</div>`}` : null}

          <div class="lg-legend">
            <div class="lg-leg-row"><span class="capb ip">IP</span> matched by address range (GeoIP / ASN) — works in every mode.</div>
            <div class="lg-leg-row"><span class="capb host">Host</span> matched by domain name — needs Force-DNS or SNI mode.</div>
            ${provFleetCats.some(id => nodeMode === "kernel" && !catCap(id).ip) ? html`<div class="lg-leg-row faint">Greyed rows are Host-only — this node is IP-only, so they can't match here. The pull stays remembered; switch to Force-DNS or SNI to activate them.</div>` : null}
          </div>
        </div>` : null}
        ${section === "turn" ? html`<div class="card">
          <div class="seclabel turnhead" style="margin-top:0">Turn proxies<span class="grow"></span>
            <label class="swt" title=${turnEnabledS ? "Turn proxies are on" : "Turn proxies are off"}><input type="checkbox" checked=${turnEnabledS} onChange=${e => setTurnEnabledS(e.target.checked)}/><span class="track"></span><span class="knob"></span></label></div>
          ${!turnEnabledS ? html`<p class="hint" style="margin:0 0 12px"><b class="warntext">Turn proxies are off.</b> Creation buttons and the turn-proxy sections are hidden across the panel. Deployed proxies keep running — they're just not shown here.</p>`
            : html`<p class="hint" style="margin:0 0 12px">Which forks appear in the <b>"Install a fork"</b> picker when you add a proxy to a node, and each fork's colour. Unticking one only <b>hides it from that list</b> — it never touches proxies you've already deployed. ${turnForks.size === 0 ? html`<b class="warntext">No forks are enabled — the install picker will be empty.</b>` : null}</p>`}
          <div class=${"cllist" + (turnEnabledS ? "" : " dimmed")}>${TURN_FORKS.map(f => { const fcol = pickThemed(forkColors[f.id], f.color, f.colorL); return html`<div class=${"cl-row" + (turnForks.has(f.id) ? "" : " off")} key=${f.id}>
            <${Switch} on=${turnForks.has(f.id)} title=${"Offer " + f.label + " in the install picker"} onChange=${v => setTurnForks(s => { const n = new Set(s); v ? n.add(f.id) : n.delete(f.id); return n; })}/>
            <${ThemedSwatch} val=${forkColors[f.id]} title=${"Colour for " + f.label} onChange=${nv => setForkColors(c => ({ ...c, [f.id]: nv }))}
              sample=${(c) => html`<span class="tg tg-turn" style=${"--tfc:" + c}>${f.label}</span>`}/>
            <span class=${"tf-name tf-" + f.id} style=${"color:" + fcol}>${f.label}</span>
            <span class="cl-caps" title=${forkSupportsAwg(f.id) ? "Works with WireGuard and AmneziaWG interfaces" : f.label + " is WireGuard-only — its client can't front an AmneziaWG interface"}>
              <span class="tg tg-wg">wg</span>${forkSupportsAwg(f.id) ? html`<span class="tg tg-awg">awg</span>` : null}
            </span>
            ${(() => {
              const v = forkVersions(f.id); const col = fcol;
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
            <span class="grow"></span>
            ${(() => { const cs = turnCheck[f.id]; if (!cs || !cs.status) return null;   // update status — right-aligned, just before the repo URL (like Geo data)
              if (cs.status === "checking") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> checking…</span>`;
              if (cs.status === "updating") return html`<span class="tf-chk"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;
              if (cs.status === "update") return html`<button class="tf-chk upd tf-updbtn" title=${"Update every deployed " + f.label + " proxy to " + cs.latest} onClick=${() => updateFork(f.id, cs.latest)}><${Ic} i="download"/> update to ${cs.latest}</button>`;
              return html`<span class="tf-chk ok"><${Ic} i="check"/> up to date</span>`; })()}
            <a class="tf-repo" href=${"https://github.com/" + f.owner} target="_blank" rel="noopener" title=${"Open " + f.owner + " on GitHub"}>${f.owner}</a>
          </div>`; })}</div>
          ${turnEnabledS ? html`<${Fragment}>
          <div class="seclabel" style="margin-top:18px">Auto-update schedule</div>
          <p class="hint" style="margin:0 0 10px">The panel checks each deployed proxy's fork for a newer release and, if there is one, updates the binary and restarts the proxy automatically. A restart briefly drops that proxy's clients, so pick a <b>quiet hour</b>. (The panel stages the update; each node applies it on its next sync.)</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>How often</label>
              <${Dropdown} value=${tuEvery} onChange=${v => setTuEvery(v)} options=${[
                { value: "1", label: "Every day" }, { value: "2", label: "Every 2 days" }, { value: "3", label: "Every 3 days" },
                { value: "7", label: "Every week" }, { value: "0", label: "Off — no auto-updates" }]}/></div>
            <div class="field" style="margin:0"><label>At (panel time)</label>
              <input type="time" class="timein" value=${tuAt} disabled=${tuEvery === "0"} onInput=${e => setTuAt(e.target.value || "04:00")}/>
              <div class="hint">${tuEvery === "0" ? "Auto-updates are off — use “Check for updates” below to update manually." : "The panel checks at this local time, on the chosen cadence."}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">Check every deployed proxy's fork for a newer release now, and update the ones that are behind</span><button class="btn btn-mini" disabled=${Object.values(turnCheck).some(v => v && v.status === "checking")} onClick=${checkTurnUpdates}><span class=${Object.values(turnCheck).some(v => v && v.status === "checking") ? "tf-arrow" : ""}><${Ic} i="refresh"/></span> Check for updates</button></div>
          <//>` : null}
          <div class="seclabel" style="margin-top:18px">Fallback VK call link</div>
          <p class="hint" style="margin:0 0 8px">Used for <b>unassigned</b> peers, and as the link the panel bakes in when you generate a config here to <b>test a connection yourself</b> before handing it out. Leave blank to emit a <span class="mono">${"<PASTE VK CALL LINK>"}</span> placeholder. Assigned users should get their <b>own</b> VK link — set it in their profile or QR view before you distribute. <b>Subscription pages ignore this link</b> and use only the per-user one.</p>
          <input class="vklink-in" value=${vkLinkS} onInput=${e => setVkLinkS(e.target.value)} placeholder="https://vk.com/call/join/…"/>
          ${turnEnabledS ? html`<${TurnCollectedIps}/>` : null}
        </div>` : null}
        ${section === "geo" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">List providers</div>
          <p class="hint" style="margin:0 0 12px"><b>Curated</b> presets are on by default — recommended, ready-to-route lists maintained by the panel. Turn on any public <b>provider</b> below to also search its raw catalog; the panel fetches it (<b>Downloading…</b>) so its lists appear in the picker. Disabling a provider hides its lists and <b>deactivates</b> anything already routed from it until you re-enable it.</p>
          <div class="provlist">${(_provReg.length ? _provReg : []).map(p => { const on = provEnabled[p.id] !== false; return html`<div class=${"provrow" + (on ? "" : " off") + (p.builtin ? " builtin" : "")} key=${p.id}>
            <${Switch} on=${on} title=${on ? (p.builtin ? "On — presets are selectable" : "Enabled — its lists are selectable") : "Off — its lists are hidden and deactivated on nodes"} onChange=${v => setProvEnabled(m => ({ ...m, [p.id]: v }))}/>
            <${ThemedSwatch} val=${provColors[p.id]} title=${p.label + " tag colour"} onChange=${nv => setProvColors(c => ({ ...c, [p.id]: nv }))}
              sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>${p.label}</span>`}/>
            <div class="prov-meta">
              <span class="prov-name" style=${"color:" + pickThemed(provColors[p.id], _provColDefault(p.id).dark, _provColDefault(p.id).light)}>${p.label}</span>
              <span class="prov-tiers">${capBadges({ host: (p.tiers || []).includes("host"), ip: (p.tiers || []).includes("ip") })}</span>
              ${p.builtin || p.enabled === false ? null : html`<span class=${"prov-upd" + (p.last_updated ? "" : " never")} title=${p.last_updated ? "When this provider's data was last pulled to the panel" : "No list from this provider has been routed yet — nothing pulled"}>${p.last_updated ? html`updated ${ago(p.last_updated)}` : "never updated"}</span>`}
            </div>
            <span class="grow"></span>
            ${p.builtin ? html`<span class="prov-desc">${p.desc || "Built-in recommended presets for common services"}</span>`
              : p.enabled === false ? null
              : (() => { const s = p.status, flashing = provFlash[p.id] > Date.now();
              if (s === "downloading") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> Downloading…</span>`;
              if (s === "updating") return html`<span class="prov-st upd"><span class="tf-arrow"><${Ic} i="refresh"/></span> updating…</span>`;
              if (s === "updated") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> updated</span>` : null;
              if (s === "uptodate") return flashing ? html`<span class="prov-st ok"><${Ic} i="check"/> up to date</span>` : null;
              if (s === "failed" || p.error) return html`<${Fragment}><span class="prov-st err" title=${p.error || ""}><${Ic} i="warn"/> ${p.last_updated ? "update failed" : "download failed"}</span><button class="btn btn-mini" style="margin-left:8px" onClick=${() => retryProvider(p.id)}>Retry</button></>`;
              return null; })()}
            ${p.builtin ? null : html`<a class="prov-repo" href=${p.url} target="_blank" rel="noopener" title=${"Open " + p.label + " on GitHub"}>${(p.url || "").replace(/^https?:\/\/github\.com\//, "")}</a>`}
          </div>`; })}${!_provReg.length ? html`<div class="hint">Loading providers…</div>` : null}
            <div class=${"provrow" + (customEnabled ? "" : " off")}>
              <${Switch} on=${customEnabled} title=${customEnabled ? "On — you can create custom lists" : "Off — the Custom lists section is hidden"} onChange=${v => setCustomEnabled(v)}/>
              <${ThemedSwatch} val=${provColors.custom} title="Custom-list tag colour" onChange=${nv => setProvColors(c => ({ ...c, custom: nv }))}
                sample=${(c) => html`<span class="sw-sample" style=${"--pc:" + c}>Custom</span>`}/>
              <div class="prov-meta"><span class="prov-name" style="color:var(--ink)">Custom lists</span></div>
              <span class="grow"></span>
              <span class="prov-desc">Your own IP / domain lists — turn off to hide the Custom lists section in routing</span>
            </div>
          </div>

          <div class="seclabel">Update schedule</div>
          <p class="hint" style="margin:0 0 10px">When each node re-fetches its lists. Refreshing briefly reloads the node's match sets, which clients can feel — so schedule it for a <b>quiet hour</b>. (A failed fetch retries on the next sync; existing lists keep working meanwhile.)</p>
          <div class="schedrow">
            <div class="field" style="margin:0"><label>How often</label>
              <${Dropdown} value=${guEvery} onChange=${v => setGuEvery(v)} options=${[
                { value: "1", label: "Every day" }, { value: "2", label: "Every 2 days" }, { value: "3", label: "Every 3 days" },
                { value: "7", label: "Every week" }, { value: "0", label: "Continuous (rolling " + ttlD + "-day TTL)" }]}/></div>
            <div class="field" style="margin:0"><label>At (node-local time)</label>
              <input type="time" class="timein" value=${guAt} disabled=${guEvery === "0"} onInput=${e => setGuAt(e.target.value || "04:00")}/>
              <div class="hint">${guEvery === "0" ? "Continuous mode ignores the time — nodes refresh whenever a list is older than the TTL." : "Nodes update at this local time, on the chosen cadence."}</div></div>
          </div>
          <div class="georefresh"><span class="faint" style="font-size:11px">Re-fetch every routed list from its provider now (updates the panel; nodes pull the changes on their schedule)</span><button class="btn btn-mini" disabled=${geoUpdating} onClick=${updateAllLists}><span class=${geoUpdating ? "tf-arrow" : ""}><${Ic} i="refresh"/></span> ${geoUpdating ? "Updating…" : "Update all lists now"}</button></div>
        </div>` : null}
        ${section === "integrations" ? html`<${IntegrationsSettings}/>` : null}
        ${section === "access" ? html`<${AccessTLSCard} onChange=${onAccess}/>` : null}
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
          <div class="condrow"><${Switch} on=${statusConds.blocked} onChange=${v => setStatusConds(c => ({ ...c, blocked: v }))}/>
            <span class="cond-b"><span class="badge b-blocked ic"><${Ic} i="warn"/>blocked</span></span>
            <span class="cond-t">Endpoint is reaching the server, but the handshake never completes (likely DPI / MTU / wrong AmneziaWG params).</span></div>
          <div class="condrow"><${Switch} on=${statusConds.faulty} onChange=${v => setStatusConds(c => ({ ...c, faulty: v }))}/>
            <span class="cond-b"><span class="badge b-faulty ic"><${Ic} i="warn"/>faulty</span></span>
            <span class="cond-t">Handshake is up but no inbound data has flowed for a while — a one-way block / DPI on the return path. (This can't tell a genuinely-stuck peer from a simply-idle one, so turn it off if idle peers bother you.)</span></div>
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
        ${section === "security" ? html`<${TwoFactorCard} enabled=${sec2fa} disabled=${!secAuth} onChange=${setSec2fa}/>` : null}
        ${section === "configs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">Client configs</div>
          <div class="field"><label>Store client configs</label>
            <${Dropdown} value=${sc} onChange=${v => setSc(v)} options=${[
              { value: "encrypted", label: "Keep encrypted configs — QRs re-viewable anytime" },
              { value: "off", label: "Keep nothing — QR shown once" }]}/>
            <div class=${"hint" + (sc === "off" ? " err" : "")}>${sc === "off" ? "Live tunnels and creation-time QRs are unaffected, but you won't be able to re-view a peer's QR/config later — you'd rotate its key and re-distribute." : "Client configs are stored encrypted at rest (the server can't read the private keys) so a peer's QR stays re-viewable — you unlock it with your encryption key below. Requires the encryption key."}</div></div>
          ${sc === "off" && subsOn ? html`<div class="hint warn" style="margin-top:10px"><${Ic} i="warn"/> Subscriptions are on and need encrypted config storage. Turn <button class="linkbtn" onClick=${() => setSection("subs")}>Subscriptions</button> off first, or keep encrypted storage on — saving this as-is will be rejected.</div>` : null}
          <div class="seclabel">Encryption</div>
          <p class="hint" style="margin:0 0 8px">An encryption key held only by you (independent of your login password) protects stored client configs so the server can't read the private keys, and unlocks a peer's QR any time you're signed in. The same key powers subscriptions when you turn them on.</p>
          <${SubVaultCard}/>
          <${ConfigMigrationCard}/>
        </div>` : null}
        ${section === "subs" ? html`<div class="card">
          <div class="seclabel" style="margin-top:0">Subscriptions</div>
          <p class="hint" style="margin:0 0 12px">A shareable, themed, mobile page per user showing their QRs. The page's private keys ride in the URL <b>fragment</b> and are never sent to the panel — nothing readable is stored on the server. Treat each user's URL as a credential (whoever holds it holds that user's configs). A separate <b>swg-sub</b> service serves the page; configure it here and install it on the panel host.</p>
          <div class="field"><label>Enable subscriptions</label>
            <${Dropdown} value=${subsOn ? "on" : "off"} disabled=${sc === "off"} onChange=${v => setSubsOn(v === "on")} options=${[
              { value: "off", label: "Off — the subscription page is blocked entirely" },
              { value: "on", label: "On — per-user subscription URLs are served" }]}/>
            ${sc === "off"
              ? html`<div class="hint warn">Subscriptions serve the encrypted config blobs — turn on <b>Keep encrypted configs</b> in <button class="linkbtn" onClick=${() => setSection("configs")}>Client configs</button> first.</div>`
              : html`<div class="hint">Off returns 404 for every subscription URL, regardless of the rest.</div>`}</div>
          <div class="seclabel">Address & certificate</div>
          <div class="subaddr">
            <div class="subaddr-row"><span class="subaddr-k">Public URL</span><span class="subaddr-v mono">${subBaseUrl() || html`<span class="faint">not set</span>`}</span></div>
            <div class="subaddr-row"><span class="subaddr-k">Listen</span><span class="subaddr-v mono">${(((ps.access || {}).sub || {}).host || "0.0.0.0")}:${(((ps.access || {}).sub || {}).port || 8444)}</span></div>
            <div class="subaddr-row"><span class="subaddr-k">Certificate</span><span class="subaddr-v mono">${(TLS_MODE_OPTS.find(o => o.value === (((ps.access || {}).tls || {}).mode || "")) || {}).label || "—"}</span></div>
          </div>
          <div class="hint" style="margin:6px 0 0">The subscription page's URL, listen address and certificate are configured in <button class="linkbtn" onClick=${() => setSection("access")}>Access & TLS</button>.</div>
          <div class="seclabel">Languages</div>
          <div class="field"><label>Offered on the subscription page</label>
            <div class="sublangs">${SUB_LANG_LIST.map(([id, name]) => html`<div class=${"sublang" + (subLangs.includes(id) ? " on" : "")} key=${id}>
              <label class="sublang-en"><input type="checkbox" checked=${subLangs.includes(id)} onChange=${e => toggleSubLang(id, e.target.checked)}/><span>${name}</span></label>
              <button class=${"sublang-def" + (subLangDef === id ? " on" : "")} disabled=${!subLangs.includes(id)} onClick=${() => setSubLangDef(id)} title="Load this language by default">${subLangDef === id ? "Default" : "Set default"}</button>
            </div>`)}</div>
            <div class="hint">Which languages the page offers. With just one enabled, it hides the selector and loads that language; the <b>default</b> is what loads first when several are offered.</div></div>
          <div class="seclabel">Encryption</div>
          <p class="hint" style="margin:0">Subscriptions reuse the same encryption key that protects your stored client configs — set it up under <button class="linkbtn" onClick=${() => setSection("configs")}>Client configs → Encryption</button>. No separate key.</p>
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
            <${Dropdown} value=${tput} onChange=${v => setTput(v)} options=${[
              { value: "nodes", label: "Nodes — what the node downloads / uploads" },
              { value: "peers", label: "Peers — what the client downloads / uploads" }]}/>
            <div class="hint">Which way ↓/↑ are labelled across the panel. Same numbers, swapped arrows.</div></div>
          <div class="seclabel">Status timing</div>
          <p class="hint" style="margin:0 0 12px">How long the panel waits before treating things as stale — in seconds.</p>
          <div class="row2"><div class="field"><label>Node stale after (s)</label><input value=${staleS} onInput=${e => setStaleS(e.target.value)} placeholder="30"/><div class="hint">No sync for this long → the node shows stale.</div></div>
            <div class="field"><label>Peer grace window (s)</label><input value=${graceS} onInput=${e => setGraceS(e.target.value)} placeholder="60"/><div class="hint">A peer stays "online" this long after its last handshake.</div></div></div>
          <div class="seclabel">Overview lists</div>
          <p class="hint" style="margin:0 0 12px">How many rows the Overview's ranked lists show (1–50).</p>
          <div class="row2"><div class="field"><label>Top talkers</label><input type="text" inputmode="numeric" value=${topTalk} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopTalk(v); }} placeholder="10"/><div class="hint">Number of peers in the Top talkers list (max 50).</div></div>
            <div class="field"><label>Top destinations</label><input type="text" inputmode="numeric" value=${topDest} onDblClick=${e => e.target.select()} onInput=${e => { let v = e.target.value.replace(/[^0-9]/g, ""); if (+v > 50) v = "50"; setTopDest(v); }} placeholder="10"/><div class="hint">Number of categories in the Top destinations list (max 50).</div></div></div>
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
        <div class="setfoot">
          ${section === "access"
            ? (accessRef.current.msg ? html`<span class=${"formmsg setfoot-msg " + (accessRef.current.msg.ok ? "ok" : "err")}>${accessRef.current.msg.t}</span>` : null)
            : (Date.now() < saved ? html`<span class="savedflash"><${Ic} i="check"/> All settings saved</span>` : null)}
          <span class="grow"></span>
          <button class="btn btn-ghost" onClick=${leaveSettings}>Back</button>
          ${section === "access"
            ? html`<button class="btn btn-primary" disabled=${accessRef.current.busy || !accessRef.current.dirty} title=${!accessRef.current.dirty ? "No changes to save" : ""} onClick=${() => accessRef.current.run()}>${accessRef.current.busy ? "Saving…" : "Save"}</button>`
            : html`<button class="btn btn-primary" disabled=${!!secErr() || !anyDirty} title=${secErr() || (!anyDirty ? "No changes to save" : "")} onClick=${confirmSave}>Save</button>`}</div>
      </div>
    </div>
  </div>`;
}

function CustomListSheet({ list, onSave, onClose }) {
  const [title, setTitle] = useState(list?.title || "");
  const [targets, setTargets] = useState(list ? (list.targets ?? [...(list.domains || []), ...(list.cidrs || [])].join(", ")) : "");
  const toks = splitTargets(targets), bad = invalidTargets(targets);   // same token validation as the interface smart-rule editor
  const err = !toks.length ? "add at least one IP or domain"
    : bad.length ? "not a valid IP, CIDR or domain: " + bad.slice(0, 4).join(", ") + (bad.length > 4 ? "…" : "") : null;
  const save = () => { if (err) return; onSave({ ...(list || { _rid: newRid() }), title: title.trim() || "Untitled list", targets }); onClose(); };
  const foot = html`<span class="grow"></span><button class="btn btn-ghost" onClick=${onClose}>Cancel</button><button class="btn btn-primary" disabled=${!!err} title=${err || ""} onClick=${save}>${list ? "Save" : "Add"}</button>`;
  return html`<${Sheet} title=${list ? "Edit list" : "New list"} width=${520} onClose=${onClose} foot=${foot}>
    <div class="field"><label>Title</label><input value=${title} onInput=${e => setTitle(e.target.value)} placeholder="e.g. Streaming"/></div>
    <div class="field"><label>IPs / domains / AS numbers</label>
      <textarea class="rrdoms" rows="1" spellcheck="false" placeholder="comma-separated — spotify.com, 1.2.3.0/24, AS62041" value=${targets} onInput=${e => { autoGrow(e.target); setTargets(e.target.value); }} ref=${el => autoGrow(el)}/>
      <${AsnHint} targets=${targets}/>
      ${err ? html`<div class="rrlint" style="margin-top:5px">${err}</div>` : html`<div class="hint">Domains match their subdomains too; IPs / CIDRs directly; an <b>AS number</b> (e.g. AS62041) resolves to that provider's IP ranges.</div>`}</div>
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
    if (np) await subRewrap(np);   // keep the config-encryption convenience cache unlockable with the new password
    setMsg({ ok: true, t: "Updated. Reloading — sign in with your new credentials…" });
    setTimeout(() => location.reload(), 1400);
  };
  return html`<${Sheet} title="Account"
    foot=${footRow({ cancelLabel: "Close", onCancel: closeModal, disabled: !enabled, onAction: save, action: "Save changes" })}>
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

// The recurring section header: <h2>title</h2> + an optional .count pill + a right-hand spacer.
// title/count may be a string or html; count null → no pill; grow===false → no spacer. The few
// headers with a styled/classed h2 or extra children (the Live .tags) stay inline.
function secTitle(title, count, grow) {
  return html`<div class="section-title"><h2>${title}</h2>${count != null ? html`<span class="count">${count}</span>` : null}${grow === false ? null : html`<span class="grow"></span>`}</div>`;
}

// The shared toolbar search box (Peers / Users / Activity / Live / expanded-peer grids): a magnifier
// icon + a filter input. Only placeholder / value / onInput vary per screen.
function SearchBox({ placeholder, value, onInput }) {
  return html`<div class="search"><${Ic} i="search"/><input placeholder=${placeholder} value=${value} onInput=${onInput}/></div>`;
}

// The standard modal footer action row: [optional `left` buttons] · spacer · Cancel · one primary/danger action.
// Collapses the ~15 dialogs that share this exact shape into one call; irregular footers (multiple actions,
// a left-aligned Cancel) stay inline. `danger` paints the action red; `actionCls` overrides the class outright;
// `title`/`disabled` are only emitted when passed, so the rendered DOM stays byte-identical to the old inline form.
function footRow({ left, cancelLabel, onCancel, action, onAction, danger, actionCls, disabled, title }) {
  return html`<${Fragment}>${left || null}<span class="grow"></span><button class="btn btn-ghost" onClick=${onCancel}>${cancelLabel || "Cancel"}</button><button class=${actionCls || ("btn " + (danger ? "btn-danger" : "btn-primary"))} disabled=${disabled} ...${title != null ? { title } : {}} onClick=${onAction}>${action}</button><//>`;
}
function Sheet({ title, children, foot, onClose, width, headExtra, dirtyRef, closeRef, onBack, noGuard }) {
  onClose = onClose || closeModal;
  const ref = useRef(null);
  const dirty = useRef(false);   // set by a real user edit — programmatic value changes don't fire input/change
  const discardRef = useRef(false);             // armed once; read live so the captured onKey closure stays correct
  const [discard, setDiscardState] = useState(false);
  const setDiscarding = v => { discardRef.current = v; setDiscardState(v); };
  const fields = () => Array.from(ref.current ? ref.current.querySelectorAll("input,textarea,select") : []);
  // closing a dirty sheet swaps the footer into an inline "discard?" confirm instead of a native dialog. `dirtyRef`
  // lets a caller flag changes the input/change listener can't see (e.g. click-toggled grids). `noGuard` opts out
  // entirely — view modals (QR / turn configs) save every field inline, so there's nothing to discard.
  const tryClose = () => { if (!noGuard && (dirty.current || (dirtyRef && dirtyRef.current)) && !discardRef.current) { setDiscarding(true); return; } onClose(); };
  if (closeRef) closeRef.current = tryClose;   // expose the guarded close so a footer Cancel routes through it too
  // The keydown listener below is registered ONCE (useEffect []), but openModal REPLACES one <Sheet> with
  // another at the same position, so Preact reuses this instance and only updates props — the effect never
  // re-runs. Without this ref, Esc would keep calling the FIRST render's onClose: a config sheet reached via a
  // `back` (turn configs → back to QR) closed everything on Esc while ✕/backdrop/Back (recreated each render)
  // correctly went back. Route Esc through the live tryClose instead.
  const tryCloseRef = useRef(tryClose); tryCloseRef.current = tryClose;
  const noGuardRef = useRef(noGuard); noGuardRef.current = noGuard;   // read live (the Sheet instance is reused across openModal)

  useEffect(() => {
    const root = ref.current; if (!root) return;
    const onEdit = () => { dirty.current = true; };
    root.addEventListener("input", onEdit, true);
    root.addEventListener("change", onEdit, true);
    // fields can opt out of autofocus with [data-noautofocus] (e.g. the VK box); and a view modal (noGuard)
    // never grabs focus onto a button as a fallback
    let first = root.querySelector("[autofocus]") || root.querySelector("input:not([data-noautofocus]),textarea,select,button.btn-primary");
    if (first && noGuardRef.current && first.tagName === "BUTTON") first = null;
    if (first) setTimeout(() => { try { first.focus(); } catch (_) {} }, 0);
    const tok = {}; _sheetStack.push(tok);   // only the TOP stacked Sheet reacts to Esc/Enter/Tab
    const onKey = e => {
      if (qrZoomEl) return;   // a QR enlargement is open — let it handle Esc (collapse it, keep the modal)
      if (_sheetStack[_sheetStack.length - 1] !== tok) return;   // a child modal is on top — defer to it
      if ((e.key === "Enter" || e.key === "Escape") && e.target && e.target.dataset && e.target.dataset.enter === "self") return;   // input handles its own Enter/Esc (e.g. inline rename) — don't submit/close the sheet
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); tryCloseRef.current(); return; }
      if (e.key === "Enter" && !noGuardRef.current && e.target.tagName !== "TEXTAREA" && !e.shiftKey) {
        // view modals (QR / turn) have no single submit action — Enter must not fire a random primary button
        // (e.g. "Enable subscription"); their own fields (the VK box) handle Enter themselves
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
      <div class="sheet-head"><h3>${title}</h3>${headExtra || null}${onBack
        ? html`<button class="sheet-back" onClick=${tryClose}><${Ic} i="back"/> Back</button>`
        : html`<button class="x" onClick=${tryClose}>×</button>`}</div>
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
// Opened from within a modal → stack it as a child (parent stays mounted; ✕/Esc/Cancel pop back). Opened
// standalone (from a table/card) → open as the root. This is the one rule: a modal opened from a modal is
// a child. `openChildOrRoot` captures it for every opener that can be reached both ways.
function openChildOrRoot(node) { (_stack.length ? pushModal : openModal)(node); }
function openConfirm(opts) { openChildOrRoot(html`<${ConfirmSheet} ...${opts}/>`); }
// Standout reassurance for "you'll need to re-distribute the configs" warnings: interface / turn-proxy
// IP/port/endpoint changes are NOT baked into the encrypted blob (only the private key + PSK are), so every
// subscription page re-renders the corrected config on its own. Renders nothing when subscriptions are off.
function SubAutoNote() {
  if (!subFeatureOn()) return null;
  return html`<div class="sub-auto"><${Ic} i="check"/><span><b>Subscribed users need nothing</b> — their subscription page serves the corrected config automatically; only manually-shared QR codes / configs need re-distributing.</span></div>`;
}
function ConfirmSheet({ title, body, note, log, confirmLabel, danger, warn, onConfirm, back, requireType }) {
  back = back || closeModal;
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState(false);
  const [typed, setTyped] = useState("");
  const isLog = log != null && String(log) !== "";
  const canToggle = isLog && logRaw(log) !== logRendered(log);   // only offer raw/rendered when they differ (ANSI present)
  const typeOk = !requireType || typed.trim() === requireType;   // type-to-confirm gate for destructive actions
  const go = async () => { if (busy || !typeOk) return; if (!onConfirm) return back(); setBusy(true); const seq = _modalSeq;
    try { await onConfirm(); } finally { if (_modalSeq === seq) closeModal(); } };   // skip close if onConfirm opened another modal (no flicker)
  const tone = danger || warn;
  return html`<${Sheet} title=${title} onClose=${back}
    foot=${html`<${Fragment}>
      ${canToggle ? html`<button class="btn btn-ghost logtoggle" onClick=${() => setRaw(r => !r)}>${raw ? "Display rendered" : "Display raw"}</button>` : null}
      <span class="grow"></span>
      <button class=${"btn " + (onConfirm ? "btn-ghost" : "btn-primary")} onClick=${back}>${onConfirm ? "Cancel" : (confirmLabel || "Close")}</button>
      ${onConfirm ? html`<button class=${"btn " + (danger ? "btn-danger" : "btn-primary")} disabled=${busy || !typeOk} onClick=${go}>${confirmLabel || "Confirm"}</button>` : null}</>`}>
    ${isLog
      ? html`<${LogBody} text=${log} raw=${raw}/>`
      : html`<${Fragment}>
          <div class=${"notice" + (tone ? " warn" : "")}><${Ic} i=${tone ? "warn" : "info"}/><span>${body}</span></div>
          ${note || null}
          ${requireType ? html`<label class="confirm-type"><span>Type <b>${requireType}</b> to confirm</span>
            <input class="ctype-input" type="text" autofocus spellcheck="false" autocomplete="off" placeholder=${requireType} value=${typed}
              onInput=${e => setTyped(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") go(); }}/></label>` : null}
        <//>`}
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

function openAddPeers(userId, userName) { openModal(html`<${AddPeersSheet} userId=${userId} userName=${userName}/>`); }
// A multi-peer editor. The dropdown ADDS peers (existing unassigned — key kept — or a fresh "new peer") to a
// working set; the carousel flips between them (◀ / ▶ / click-to-jump · N/M counter); the interfaces grid below
// reflects THE SELECTED peer (existing peers' current interfaces pre-checked + locked; new peers all unchecked).
// Save assigns each existing peer (+ any newly-ticked interfaces) and mints each new peer across its ticked
// interfaces (one key). The user's already-assigned peers seed the carousel so they're editable in place too.
function AddPeersSheet({ userId, userName }) {
  const cf = useConfigFields();
  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const lastOnline = p => { const a = (p.targets || []).map(t => t.observed && t.observed.handshake_age).filter(x => x != null); return a.length ? seen(Math.min(...a)) + " ago" : "never online"; };
  // Type from the LIVE interface (awg_params), falling back to the peer's stored target.type only when the interface
  // isn't reported — so the badge/label always agree with the interfaces grid (which reads the live interface too).
  const tgtType = targetType;   // module helper — live interface authoritative, stored target.type only as fallback
  const peerLabel = p => { const t = (p.targets || [])[0] || {}; return [p.title || "untitled", Store.nodeName(t.node), tgtType(t).toUpperCase() + " " + t.iface, t.ip].filter(Boolean).join(" · "); };
  const peerCtx = p => { const t = (p.targets || [])[0] || {}; return [Store.nodeName(t.node), tgtType(t).toUpperCase() + " " + t.iface, t.ip].filter(Boolean).join(" · "); };   // the label MINUS the (now-editable) title
  const rep = p => (p.targets || [])[0] || {};
  const orderPeers = list => [...list].sort((a, b) => (Store.nodeName(rep(a).node) || "").localeCompare(Store.nodeName(rep(b).node) || "")
    || (rep(a).iface || "").localeCompare(rep(b).iface || "") || String(rep(a).ip || "").localeCompare(String(rep(b).ip || ""), undefined, { numeric: true }));
  const mkExisting = (p, assigned) => ({ key: "e:" + p.id, kind: "existing", peer: p, assigned, title: p.title || "", sel: Object.fromEntries((p.targets || []).map(t => [tkey(t.node, t.iface), { node: t.node, iface: t.iface, ip: String(t.ip || "").split("/")[0], existing: true }])) });
  const mkNew = () => ({ key: "n:" + (seq.current++), kind: "new", title: "", sel: {} });
  const [items, setItems] = useState(() => orderPeers(userId ? Store.peersOfUser(userId) : []).map(p => mkExisting(p, true)));
  const [cursor, setCursor] = useState(0);
  const [jump, setJump] = useState(false);
  const [editTitle, setEditTitle] = useState(false);   // click the title → inline edit; blur/Enter keeps, Esc reverts
  const editOrig = useRef("");                          // the title as it was when edit started → restored on Esc
  const titleInput = useRef(null);
  useEffect(() => { if (editTitle && titleInput.current) { titleInput.current.focus(); try { titleInput.current.select(); } catch (_) {} } }, [editTitle, cursor]);   // focus the inline box so typing starts immediately
  const goTo = i => { setJump(false); setEditTitle(false); setCursor(i); };
  const [toUnassign, setToUnassign] = useState([]);   // saved peers the operator unlinked → unassigned on Save
  const dirty = useRef(false); const sheetClose = useRef(null);
  const cur = items[cursor] || null;
  const usedExisting = new Set(items.filter(it => it.kind === "existing").map(it => it.peer.id));
  const addable = orderPeers(Store.unassignedPeers().filter(p => !usedExisting.has(p.id)));
  const carLabel = it => (it.title || "").trim() || (it.kind === "new" ? "New peer" : peerLabel(it.peer));

  const stayExpanded = () => { usersView.expanded[userId] = true; usersView.q = ""; usersView.page = 1; closeModal(); go("#/users"); };
  const addFromDrop = v => {
    if (!v) return; const idx = items.length; dirty.current = true;
    if (v === "__new") setItems(its => [...its, mkNew()]);
    else { const p = Store.unassignedPeers().find(x => x.id === v); if (!p) return; setItems(its => [...its, mkExisting(p, false)]); }
    setCursor(idx); setJump(false);
  };
  const updateSel = updater => { dirty.current = true; setItems(its => its.map((it, i) => i === cursor ? { ...it, sel: typeof updater === "function" ? updater(it.sel) : updater } : it)); };
  const updateTitle = v => { dirty.current = true; setItems(its => its.map((it, i) => i === cursor ? { ...it, title: v } : it)); };
  const dropAt = i => { setJump(false); setItems(its => its.filter((_, k) => k !== i)); setCursor(c => Math.max(0, Math.min(c, items.length - 2))); };
  const removeCur = () => {
    const it = items[cursor]; if (!it) return; dirty.current = true;
    if (it.kind === "existing" && it.assigned)   // unlinking a SAVED peer = unassign on Save → confirm (pushed, keeps this sheet)
      pushModal(html`<${ConfirmSheet} title=${"Unlink peer" + (userName ? " · " + userName : "")} confirmLabel="Unlink" danger=${true}
        body=${html`Unassign <b>${it.peer.title || "this peer"}</b> from ${userName || "the user"} when you Save? Access is revoked and the key changes — re-adding later needs a fresh QR / config.`}
        onConfirm=${() => { setToUnassign(u => [...u, it.peer.id]); dropAt(cursor); }}/>`);
    else dropAt(cursor);
  };

  const save = async () => {
    if (!items.length && !toUnassign.length) return setMsg({ k: "err", t: "Add at least one peer." });
    for (const it of items) {
      for (const s of Object.values(it.sel)) if (!V.ipv4(String(s.ip || "").trim())) return setMsg({ k: "err", t: "Invalid address for " + Store.nodeName(s.node) + "/" + s.iface + "." });
      if (it.kind === "new" && !Object.keys(it.sel).length) return setMsg({ k: "err", t: "A new peer has no interfaces — tick at least one (or remove it)." });
    }
    if (items.some(it => it.kind === "new")) { const ce = configErrors(cf); const ck = Object.keys(ce)[0]; if (ck) return setMsg({ k: "err", t: ce[ck] }); }
    setBusy(true); setMsg({ k: "work", t: "saving…" });
    const fails = []; let firstPid = null;
    for (const it of items) {
      if (it.kind === "new") {
        const res = await createOneMultiTargetPeer(userId, Object.values(it.sel), cf.opts(), (it.title || "").trim());
        if (!res.ok) fails.push(...res.fails); else if (res.id && !firstPid) firstPid = res.id;
      } else {
        const patch = {};
        if (!it.assigned) patch.user_id = userId;
        if ((it.title || "").trim() !== (it.peer.title || "")) patch.title = (it.title || "").trim();   // inline title edit
        if (Object.keys(patch).length) { const r = await api.peerUpdate({ peer_id: it.peer.id, ...patch }); if (!r.ok) { fails.push(peerLabel(it.peer) + ": " + (r.error || "update failed")); continue; } }
        const have = new Set((it.peer.targets || []).map(t => tkey(t.node, t.iface)));
        for (const s of Object.values(it.sel)) {
          if (have.has(tkey(s.node, s.iface))) continue;
          const rr = await api.peerAddTarget({ peer_id: it.peer.id, target: { node: s.node, iface: s.iface, ip: String(s.ip).trim().split("/")[0] } });
          if (!rr.ok) fails.push(Store.nodeName(s.node) + "/" + s.iface + ": " + (rr.error || rr.code || "failed"));
        }
        if (!firstPid) firstPid = it.peer.id;
      }
    }
    for (const pid of toUnassign) { const r = await api.peerUnassign({ peer_id: pid }); if (!r.ok) fails.push("unassign: " + (r.error || r.code || "failed")); }
    setBusy(false); await Store.poll();
    if (fails.length) toast("Some operations failed: " + fails.join("; "), "err", 6000);
    closeModal();
    if (firstPid) revealAssignedPeer(userId, firstPid); else stayExpanded();
    subReconcileUser(userId);   // assigning an EXISTING peer here only writes user_id — publish its (and any new peer's) blob, prompting to unlock if locked
  };

  const newCount = items.filter(it => it.kind === "new").length;
  const cta = "Save" + (items.length ? " · " + items.length + " peer" + (items.length === 1 ? "" : "s") : (toUnassign.length ? " · unlink " + toUnassign.length : ""));
  return html`<${Sheet} title=${"Add peers" + (userName ? " · " + userName : "")} dirtyRef=${dirty} closeRef=${sheetClose}
    foot=${footRow({ onCancel: () => (sheetClose.current || closeModal)(), disabled: busy || (!items.length && !toUnassign.length), onAction: save, action: cta })}>
    <div class="field"><label>Add peer</label>
      <select class="selwrap" value="" onChange=${e => { addFromDrop(e.target.value); e.target.value = ""; }}>
        <option value="">Add an existing peer or create a new one…</option>
        <option value="__new">＋  Create new peer</option>
        ${addable.map(p => html`<option value=${p.id}>${peerLabel(p)} · ${lastOnline(p)}</option>`)}
      </select></div>
    ${items.length && cur ? html`<${Fragment}>
      <div class="peercar">
        <button class="pc-arrow" title="Previous peer" disabled=${cursor <= 0} onClick=${() => goTo(Math.max(0, cursor - 1))}>◀</button>
        <div class="pc-face" title="Pick a peer" onClick=${e => { if (!editTitle && !e.target.closest(".pc-titletext")) setJump(j => !j); }}>
          <span class=${"pc-kind " + (cur.kind === "new" ? "new" : tgtType(rep(cur.peer)))}>${cur.kind === "new" ? "new" : tgtType(rep(cur.peer))}</span>
          <span class="pc-name">${editTitle
            ? html`<input class="pc-title" data-enter="self" ref=${titleInput} value=${cur.title} placeholder=${cur.kind === "new" ? "New peer" : "untitled"} onInput=${e => updateTitle(e.target.value)}
                onBlur=${() => setEditTitle(false)} onClick=${e => e.stopPropagation()}
                onKeyDown=${e => {
                  if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); setEditTitle(false); }          // keep the new title, back to static
                  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); updateTitle(editOrig.current); setEditTitle(false); }   // revert to the pre-edit title
                }}/>`
            : html`<span class="pc-titletext" title="Click to rename this peer" onClick=${e => { e.stopPropagation(); editOrig.current = cur.title || ""; setEditTitle(true); }}>${(cur.title || "").trim() || (cur.kind === "new" ? "New peer" : "untitled")}</span>`}${cur.kind === "existing" ? html`<span class="pc-rest"> · ${peerCtx(cur.peer)}</span>` : null}</span>
          <span class="pc-count">${cursor + 1}/${items.length}</span>
        </div>
        <button class="pc-arrow" title="Next peer" disabled=${cursor >= items.length - 1} onClick=${() => goTo(Math.min(items.length - 1, cursor + 1))}>▶</button>
        <button class="pc-x" title=${(cur.kind === "existing" && cur.assigned) ? "Unlink (unassign on save)" : "Remove from the list"} onClick=${removeCur}><${Ic} i="link"/></button>
        ${jump ? html`<div class="pc-menu">${items.map((it, i) => html`<button key=${it.key} class=${i === cursor ? "on" : ""} onClick=${() => goTo(i)}><span class="pc-mi">${i + 1}</span> ${carLabel(it)}</button>`)}</div>` : null}
      </div>
      <div class="field"><label>Interfaces${cur.kind === "new" ? " · pick where to deploy" : ""}</label>
        <${PeerIfaceGrid} value=${cur.sel} onChange=${updateSel} lockExisting=${cur.kind === "existing"}/></div>
      ${newCount ? html`<${AdvancedFields} st=${cf}/>` : null}
    <//>` : html`<div class="hint" style="margin-top:6px">Add an existing unassigned peer (its key is kept) or create a new one, then tick which interfaces to deploy it on.</div>`}
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
  // order by the CURRENT checked state (checked targets on top), then node, then interface — so a ticked row
  // jumps up to join the selected group and every selection stays gathered at the top with its IP visible.
  const _sv = Object.values(sel);
  const lockType = _sv.length ? iTypeOf(_sv[0].node, _sv[0].iface) : null;   // a peer is one protocol — hide the other kind once one is ticked
  const ordered = [...targets].filter(t => !lockType || iTypeOf(t.node, t.iface) === lockType).sort((a, b) =>
    (sel[tkey(a.node, a.iface)] ? 0 : 1) - (sel[tkey(b.node, b.iface)] ? 0 : 1)
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

// CONTROLLED interfaces grid for the Add-peers carousel: `value` = {tkey:{node,iface,ip,existing?}}; `onChange`
// takes a functional updater so an async IP allocation merges against the LATEST selection. `lockExisting` keeps
// already-deployed rows checked + read-only (removing a live deployment isn't done here). Scrolls past 5 rows.
function PeerIfaceGrid({ value, onChange, lockExisting }) {
  const all = useMemo(allTargets, [Store.describe]);
  const allocIp = async (node, iface) => {
    const k = tkey(node, iface);
    onChange(sel => ({ ...sel, [k]: { node, iface, ip: "", ipHint: "finding a free address…" } }));
    const r = await api.nextIp([node], iface);
    onChange(sel => sel[k] ? { ...sel, [k]: { ...sel[k], ip: r.ok ? String(r.data.next_ip).split("/")[0] : "", ipHint: r.ok ? "" : (r.error || "no free address") } } : sel);
  };
  const toggle = (node, iface) => {
    const k = tkey(node, iface); const s = value[k];
    if (s) { if (s.existing && lockExisting) return; onChange(sel => { const n = { ...sel }; delete n[k]; return n; }); }
    else allocIp(node, iface);
  };
  const setIp = (k, v) => onChange(sel => sel[k] ? { ...sel, [k]: { ...sel[k], ip: v } } : sel);
  if (!all.length) return html`<div class="hint">No interfaces available — is a node online?</div>`;
  const _sv = Object.values(value);
  const lockType = _sv.length ? iTypeOf(_sv[0].node, _sv[0].iface) : null;   // a peer is one protocol — hide the other kind once one is ticked
  const ordered = [...all].filter(t => !lockType || iTypeOf(t.node, t.iface) === lockType).sort((a, b) => (Store.nodeName(a.node) || "").localeCompare(Store.nodeName(b.node) || "") || (a.iface || "").localeCompare(b.iface || ""));
  return html`<div class=${"targetpick" + (ordered.length > 5 ? " scroll" : "")}>${ordered.map(t => {
    const k = tkey(t.node, t.iface); const s = value[k];
    const im = (Store.describe[t.node] || {})[t.iface] || {};
    const ity = (im.awg_params && Object.keys(im.awg_params).length) ? "awg" : "wg";
    const locked = !!(s && s.existing && lockExisting);
    return html`<div class=${"targetopt " + (s ? "sel " : "") + (locked ? "locked" : "")}>
      <label class="topt-main" onClick=${locked ? null : () => toggle(t.node, t.iface)}>
        <span class="box">${s ? html`<${Ic} i="check"/>` : ""}</span>
        <span class="nm" style=${"color:" + (Store.nodeColor(t.node) || "var(--ink)")}>${Store.nodeName(t.node)}</span>
        <span class="tp">${t.iface}</span></label>
      <${Tag} kind=${ity} label=${ity}/>
      ${s ? html`<input class=${"topt-ip " + (s.ip && !V.ipv4(s.ip) ? "bad" : "")} value=${s.ip} placeholder=${s.ipHint || "address"} readOnly=${locked} onInput=${e => setIp(k, e.target.value)}/>` : null}
    </div>`;
  })}</div>`;
}

// Mint ONE peer (single key + PSK) deployed to MULTIPLE targets in a single atomic peerCreate (per-target configs
// keyed node|iface). Returns { ok, id?, fails:[...] }. Used by the Add-peers carousel for a "new peer" item.
async function createOneMultiTargetPeer(userId, targets, opts, title) {
  if (!targets.length) return { ok: false, fails: ["no interfaces"] };
  const dnsArr = (opts.dns || "").split(",").map(s => s.trim()).filter(Boolean);
  try {
    const keys = await genKeys(); const psk = genPSK();
    const tlist = []; const configs = {};
    for (const t of targets) {
      const m = Store.ifaceMeta(t.node, t.iface);
      if (!m) return { ok: false, fails: [Store.nodeName(t.node) + "/" + t.iface + " (no interface meta)"] };
      const ipClean = String(t.ip).trim().split("/")[0];
      const ty = (m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg";
      tlist.push({ node: t.node, iface: t.iface, ip: ipClean, type: ty });
      configs[tkey(t.node, t.iface)] = buildConf({ privkey: keys.priv, address: ipClean + "/32", dns: dnsArr, mtu: (opts.mtu || "").trim() || 1280,
        awg_params: m.awg_params, server_pubkey: m.public_key, psk, endpoint: m.endpoint,
        allowed: (opts.allowed || "").trim() || "0.0.0.0/0, ::/0", keepalive: (opts.keepalive || "").trim() });
    }
    const body = { user_id: userId, pubkey: keys.pub, psk, targets: tlist };
    if (title) body.title = title;
    const _ov = configOverrides(opts, Store.ifaceMeta(targets[0].node, targets[0].iface));
    if (Object.keys(_ov).length) body.overrides = _ov;
    // No plaintext to the server: the private key stays in the browser, encrypted into the blob by subMaybePublish below.
    const r = await api.peerCreate(body);
    if (!r.ok) return { ok: false, fails: ["create: " + (r.error || r.code || "failed")] };
    Store.sessionConfigs[keys.pub] = Object.assign(Store.sessionConfigs[keys.pub] || {}, configs);
    if (r.data && r.data.id) Store.recentlyCreated[r.data.id] = Date.now();
    await subPublishOrPrompt(userId, r.data && r.data.id, keys.priv, psk);   // publish to the user's subscription (prompt to unlock if locked)
    return { ok: true, id: r.data && r.data.id };
  } catch (e) { return { ok: false, fails: [e.message || String(e)] }; }
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
      const _ov = configOverrides(cf.opts(), Store.ifaceMeta(chosen[0].node, chosen[0].iface));
      if (Object.keys(_ov).length) body.overrides = _ov;
      // No plaintext to the server: the key stays in the browser (session config for the immediate QR) and is
      // encrypted into the blob by subMaybePublish (below, after the create POST succeeds).
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
    else if (userId) revealUser(userId, tempId);
    mutate({
      patch: s => { s.roster.peers[tempId] = optimistic; },        // shows instantly with status "creating"
      call: () => api.peerCreate(body),
      onOk: r => { if (r && r.data && r.data.id) { Store.recentlyCreated[r.data.id] = Date.now();
        subPublishOrPrompt(userId || null, r.data.id, keys.priv, pskV); } },   // encrypt {k,p} → blob (prompt to unlock if locked)
    });
  };

  return html`<${Sheet} title="New peer"
    foot=${footRow({ onCancel: closeModal, disabled: busy, onAction: create, action: "Create peer" })}>
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
function openAddTarget(peer, back) {
  const child = _stack.length > 0;   // opened from another modal (peer view / edit) → child; Cancel pops back to it
  (child ? pushModal : openModal)(html`<${AddTargetSheet} peer=${peer} back=${back || closeModal} child=${child}/>`);
}
function AddTargetSheet({ peer, back, child }) {
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
      // Same key as the existing deployments → the peer's blob already covers it; no plaintext to the server.
      const r = await api.peerAddTarget(body);
      if (r.ok) { if (conf) (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
      else fails.push(Store.nodeName(t.node) + "/" + t.iface + " (add)");
    }
    for (const t of ipChanged) {
      const info = Store.ifaceMeta(t.node, t.iface);
      const ipClean = String(t.ip || "").split("/")[0];
      const body = { peer_id: peer.id, node: t.node, iface: t.iface, ip: ipClean };
      // address lives in the roster (rendered live); rebuild the session config for the QR, but send no plaintext.
      if (srcConf) { const s = parseFullConf(srcConf); const conf = buildConf({ privkey: s.privkey, address: ipClean + "/32", dns: s.dns, mtu: s.mtu, awg_params: info.awg_params, server_pubkey: info.public_key, psk: s.psk || peer.psk, endpoint: info.endpoint, allowed: s.allowed, keepalive: s.keepalive }); (Store.sessionConfigs[peer.pubkey] = Store.sessionConfigs[peer.pubkey] || {})[tkey(t.node, t.iface)] = conf; }
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
        note=${ipChanged.length ? html`<${SubAutoNote}/>` : null}
        onConfirm=${async () => { if (await doSave()) { closeModal(); back(); } }}/>`);
    } else doSave().then(ok => { if (ok) back(); });
  };

  return html`<${Sheet} title=${"Peer targets"} onClose=${back} onBack=${child ? back : null}
    foot=${footRow({ onCancel: back, actionCls: "btn " + (chosen.length === 0 ? "btn-danger" : "btn-primary"), disabled: busy || !confLoaded || nochange, onAction: save, action: chosen.length === 0 ? "Delete peer" : ((removed.length || ipChanged.length) ? "Save changes" : "Deploy") })}>
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
      <button class="btn btn-ghost" onClick=${() => openPeerConfigs(p, { child: true })}><${Ic} i="qr"/> QR</button>
      <button class="btn btn-ghost" onClick=${() => openAddTarget(p)}><${Ic} i="copy"/> Targets</button>
      <button class="btn btn-ghost" onClick=${() => openEditPeer(p, node && iface ? { node, iface } : null)}><${Ic} i="pencil"/> Edit</button>
      ${p.unassigned ? html`<button class="btn btn-danger" onClick=${() => confirmDeletePeer(p)}>Delete</button>`
        : html`<button class="btn btn-danger" onClick=${() => confirmUnassign(p)}>Unassign</button>`}<//>`}>
    <div class="pv-head">
      <div class="pv-id"><div class="pv-sub">${u ? html`<a class="pv-user" href="#/users" onClick=${e => { e.preventDefault(); closeModal(); revealUser(u.id); }}>${u.name}</a>`
          : html`<${UserCombo} onPick=${uid => assignPeer(p, uid)} placeholder="Assign to a user…"/>`}</div></div>
      <${Badge} s=${p.unassigned ? "unassigned" : p.status}/></div>
    <div class="lbl" style="margin:16px 2px 4px">Deployments · ${p.targets.length}</div>
    <div class="pv-deps">${p.targets.map(t => {
      const obs = t.observed;
      const proto = targetType(t);
      return html`<div class=${"pv-dep" + (node === t.node && iface === t.iface ? " hl" : "")} key=${tkey(t.node, t.iface)}>
        <div class="pv-dep-top"><${Badge} s=${t.status}/>
          <span class="tags">
            <${Tag} kind=${proto} label=${proto} muted=${!t.online}/>
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
function openEditPeer(peer, focus, done, flash) {
  const child = _stack.length > 0;   // opened from another modal (peer view) → child; closing pops back to it
  (child ? pushModal : openModal)(html`<${EditPeerSheet} peer=${peer} focus=${focus} done=${done || closeModal} flash=${flash} child=${child}/>`);
}
function EditPeerSheet({ peer, focus, done, flash, child }) {
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
      // persist the roster copy of the non-secret overrides (custom DNS/MTU/AllowedIPs/keepalive), so a
      // blob-only render (encrypted store / the sub page) reproduces this peer's config faithfully.
      if (editable) {
        const _meta0 = Store.ifaceMeta(peer.targets[0].node, peer.targets[0].iface);
        const ovNew = configOverrides({ dns, mtu, allowed, keepalive }, _meta0);
        if (JSON.stringify(ovNew) !== JSON.stringify(peer.overrides || {})) {
          const r = await api.peerUpdate({ peer_id: peer.id, overrides: ovNew }); if (!r.ok) fails++;
        }
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
        // No plaintext to the server: the address moves via the roster, and the DNS/MTU/AllowedIPs edits are
        // persisted as roster overrides (the peerUpdate above); the key is unchanged, so the blob still holds it.
        if (changed) { const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, ip: newIP }); if (!r.ok) fails++; }
      }
    } catch (e) { setBusy(false); return setMsg({ k: "err", t: String(e.message || e) }); }
    setBusy(false); Store.configEpoch++;
    // an already-assigned peer changing owner is destructive (keys rotate) — confirm it now, on
    // Save (so cancelling keeps the previous owner). Title/config above are already persisted.
    const oldUid = peer.user_id || "", newUid = userId || "";
    if (oldUid && newUid !== oldUid) {
      await Store.poll();
      const fresh = (Store.recon.peers.find(x => x.id === peer.id)) || peer;
      return newUid ? confirmReassign(fresh, newUid) : confirmUnassign(fresh);   // stacks over this sheet; Cancel pops back
    }
    toast(fails ? "Saved (some changes couldn't be persisted)." : "Peer updated.", fails ? "info" : "ok");
    done(); await Store.poll();
  };

  const rotate = () => {
    openConfirm({ title: "Rotate keys", confirmLabel: "Rotate keys", warn: true,
      body: "A fresh keypair and preshared key are generated. The current config stops working — you'll need to send out the fresh QR / config to re-import. Useful if a config may have leaked.",
      onConfirm: () => {
        // confirm pops back to the edit sheet (its parent); the rotate runs and reports via a toast.
        rotatePeerKeys(peer).then(async () => {
          await Store.poll();
          const re = Store.rowErrors["peer:" + peer.id];
          toast(re ? (re.msg || "Rotate failed.") : "Keys rotated — send the user the new QR / config; the old one no longer works.", re ? "err" : "ok");
        });
      } });
  };

  return html`<${Sheet} title=${"Edit peer"} onClose=${done} onBack=${child ? done : null}
    foot=${footRow({ left: html`${editable ? html`<button class="btn btn-ghost" onClick=${() => openPeerConfigs(peer, { child: true })}><${Ic} i="qr"/> QR</button>` : null}<button class="btn btn-ghost" onClick=${() => openAddTarget(peer)}><${Ic} i="copy"/> Targets</button><button class="btn btn-ghost" onClick=${rotate}><${Ic} i="key"/> Rotate keys</button>`, onCancel: done, disabled: busy, onAction: save, action: "Save" })}>
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
    foot=${footRow({ onCancel: closeModal, onAction: create, action: "Create node" })}>
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
function NodeIpPick({ ips, value, onChange, auto, customPlaceholder, disabled }) {
  const pub = (ips || []).filter(ip => !isPrivIp(ip));
  const valIsCustom = !!value && !pub.includes(value);
  const [custom, setCustom] = useState(valIsCustom);
  const sel = (custom || valIsCustom) ? "__custom__" : (value || "");
  const onSel = v => { if (v === "__custom__") setCustom(true); else { setCustom(false); onChange(v); } };
  return html`<${Fragment}>
    <${Dropdown} value=${sel} onChange=${onSel} disabled=${disabled} options=${[
      { value: "", label: auto },
      ...pub.map(ip => ({ value: ip, label: ip })),
      { value: "__custom__", label: "Use custom…" }]}/>
    ${sel === "__custom__" ? html`<input class="ipk-custom" placeholder=${customPlaceholder || "Custom IP — e.g. 203.0.113.5"} value=${value || ""} onInput=${e => onChange(e.target.value)} disabled=${disabled} spellcheck="false" autocomplete="off"/>` : null}
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
    foot=${footRow({ left: html`<button class="btn btn-ghost" title="Rotate this node's enrollment token (re-enroll / re-install)" onClick=${() => openNodeRotate(node)}><${Ic} i="key"/> Rotate key</button>`, onCancel: closeModal, onAction: save, action: "Save" })}>
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
    foot=${footRow({ onCancel: closeModal, onAction: go, action: "Generate recovery command" })}>
    <div class="notice"><${Ic} i="info"/><span>This node isn't reporting. Generating a recovery command rotates its token and gives you a one-line command to paste on the server — it re-installs/recovers <b>${node.name}</b> as the <b>same node</b>, so its interfaces and peers come straight back (no need to find the old token).</span></div>
    <div class="notice warn" style="margin-top:10px"><${Ic} i="warn"/><span>The node's current token stops working immediately — use this only when the node is genuinely down or you've lost its install command.</span></div>
  <//>`;
}
function openNodeRotate(node) { openModal(html`<${NodeRotateSheet} node=${node}/>`); }
function NodeRotateSheet({ node }) {
  const go2 = async () => { const r = await api.nodeRotate({ id: node.id }); if (!r.ok) { toast(r.error || "rotate failed", "err"); return; } openModal(html`<${NodeTokenSheet} name=${node.name} token=${r.data.token} isNew=${false} kind=${node.kind}/>`); };
  return html`<${Sheet} title=${"Rotate token · " + node.name}
    foot=${footRow({ onCancel: closeModal, onAction: go2, action: "Rotate" })}>
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
    foot=${footRow({ onCancel: closeModal, danger: true, disabled: !ok || busy, onAction: del, action: "Force remove" })}>
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
  { re: /^\/activity$/, fn: ActivityHistoryScreen, tab: "overview" },
  { re: /^\/users$/, fn: UsersScreen, tab: "users" },
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
  // Access & TLS confirm handshake: an address change redirects the browser to the NEW panel address with
  // ?__apply=<nonce>. Landing here proves the new listener is reachable → confirm it (the panel then drops
  // the old listener). Runs once on load; strips the param so a reload can't re-fire.
  useEffect(() => {
    const m = /[?&]__apply=([A-Za-z0-9]+)/.exec(location.search);
    if (!m) return;
    api.post("/api/access/confirm", { nonce: m[1] }).then(r => {
      toast(r && r.ok ? "New panel address confirmed." : ("Couldn't confirm: " + ((r && r.error) || "unknown")), r && r.ok ? "ok" : "err", 4000);
    }).finally(() => history.replaceState(null, "", location.pathname + location.hash));
  }, []);
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
    const vl = $("#vaultlock-btn");   // padlock: removed from the header by request — kept (wired to lockVault) but always hidden
    if (vl) { vl.hidden = true; if (!vl._wired) { vl._wired = true; vl.onclick = lockVault; } }
  });

  return html`<${Fragment}>
    ${h(route.fn, params)}
    ${modalStack}
  <//>`;
}

// ───────────────────────── auth: login page + logout ─────────────────────────
let _loginShown = false;
// Two-factor (TOTP / Google Authenticator) card for Settings → Authentication.
// Self-contained: setup → scan → verify → recovery codes → enabled/disable.
function TwoFactorCard({ enabled, disabled, onChange }) {
  const [stage, setStage] = useState("idle");     // idle | setup | recovery | disabling
  const [setup, setSetup] = useState(null);        // {secret, otpauth}
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState([]);
  const [disPw, setDisPw] = useState(""); const [disCode, setDisCode] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const reset = () => { setStage("idle"); setSetup(null); setQr(""); setCode(""); setErr(""); setDisPw(""); setDisCode(""); };
  const beginSetup = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.twofaSetup();
      if (!r || !r.ok) { setErr((r && r.error) || "Couldn't start setup."); setBusy(false); return; }
      setSetup(r.data); setStage("setup");
      try { setQr(await qrDataURL(r.data.otpauth, 200)); } catch (_) { setQr(""); }
    } catch (_) { setErr("Couldn't reach the panel."); }
    setBusy(false);
  };
  const doEnable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaEnable(code.trim());
      if (!r || !r.ok) { setErr((r && r.error) || "That code isn't valid — try the current one."); setBusy(false); return; }
      setRecovery((r.data && r.data.recovery) || []); setStage("recovery"); setCode(""); onChange && onChange(true);
    } catch (_) { setErr("Couldn't reach the panel."); }
    setBusy(false);
  };
  const doDisable = async () => {
    if (busy) return; setBusy(true); setErr("");
    try {
      const r = await api.twofaDisable({ current_password: disPw, code: disCode.trim() });
      if (!r || !r.ok) { setErr((r && r.error) || "Couldn't disable — check your password and code."); setBusy(false); return; }
      reset(); onChange && onChange(false); toast("Two-factor authentication disabled.", "ok");
    } catch (_) { setErr("Couldn't reach the panel."); }
    setBusy(false);
  };
  const copyRecovery = () => { try { navigator.clipboard.writeText(recovery.join("\n")); toast("Recovery codes copied.", "ok"); } catch (_) {} };

  return html`<div class="card">
    <div class="seclabel" style="margin-top:0">Two-factor authentication
      ${enabled && stage === "idle" ? html`<span class="grow"></span><span class="tg tg-ok">On</span>` : null}</div>
    ${err ? html`<div class="formmsg err">${err}</div>` : null}
    ${!enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">Add a second step at sign-in using an authenticator app (Google Authenticator, Authy, 1Password…). ${disabled ? html`<b class="warntext">Configure a panel login first.</b>` : null}</p>
      <button class="btn btn-primary" disabled=${disabled || busy} onClick=${beginSetup}>${busy ? "Starting…" : "Set up two-factor"}</button>
    ` : null}
    ${enabled && stage === "idle" ? html`
      <p class="hint" style="margin:0 0 12px">Sign-in requires a code from your authenticator app. Keep your recovery codes somewhere safe in case you lose the device.</p>
      <button class="btn btn-danger" onClick=${() => { reset(); setStage("disabling"); }}>Disable two-factor</button>
    ` : null}
    ${stage === "setup" ? html`
      <p class="hint" style="margin:0 0 12px">Scan this with your authenticator app, then enter the 6-digit code it shows to confirm.</p>
      <div class="twofa-setup">
        ${qr ? html`<img class="twofa-qr" src=${qr} alt="TOTP QR code" width="200" height="200"/>` : html`<div class="twofa-qr empty">QR unavailable</div>`}
        <div class="twofa-manual">
          <label>Can't scan? Enter this key manually</label>
          <code class="twofa-secret">${setup && setup.secret}</code>
          <div class="field" style="margin-top:12px"><label>Code from the app</label>
            <input autofocus value=${code} onInput=${e => setCode(e.target.value)} inputmode="text" autocomplete="one-time-code" placeholder="123 456"/></div>
          <div class="btnrow" style="margin-top:8px">
            <button class="btn btn-primary" disabled=${busy || code.trim().length < 6} onClick=${doEnable}>${busy ? "Verifying…" : "Verify & enable"}</button>
            <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>Cancel</button>
          </div>
        </div>
      </div>
    ` : null}
    ${stage === "recovery" ? html`
      <p class="hint" style="margin:0 0 12px"><b>Two-factor is on.</b> Save these recovery codes now — each works once if you lose your authenticator. <b class="warntext">They won't be shown again.</b></p>
      <div class="twofa-codes">${recovery.map(c => html`<code key=${c}>${c}</code>`)}</div>
      <div class="btnrow" style="margin-top:12px">
        <button class="btn btn-ghost" onClick=${copyRecovery}><${Ic} i="copy"/> Copy codes</button>
        <button class="btn btn-primary" onClick=${reset}>Done</button>
      </div>
    ` : null}
    ${stage === "disabling" ? html`
      <p class="hint" style="margin:0 0 12px">Confirm with your password and a current code to turn two-factor off.</p>
      <div class="field"><label>Current password</label><input type="password" value=${disPw} onInput=${e => setDisPw(e.target.value)} autocomplete="current-password"/></div>
      <div class="field"><label>Authentication code (or recovery code)</label><input value=${disCode} onInput=${e => setDisCode(e.target.value)} autocomplete="one-time-code" placeholder="123 456"/></div>
      <div class="btnrow" style="margin-top:8px">
        <button class="btn btn-danger" disabled=${busy || !disPw || !disCode.trim()} onClick=${doDisable}>${busy ? "Disabling…" : "Disable two-factor"}</button>
        <button class="btn btn-ghost" disabled=${busy} onClick=${reset}>Cancel</button>
      </div>
    ` : null}
  </div>`;
}
function require401() { showLogin(); throw new Error("unauthorized"); }
function showLogin() { if (_loginShown) return; _loginShown = true; document.body.classList.add("loggedout"); try { render(h(LoginScreen), viewEl); } catch (_) {} }
function LoginScreen() {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [twofa, setTwofa] = useState(false); const [code, setCode] = useState("");
  // The `autofocus` attribute is inert here: showLogin() renders this form long after page load, and a
  // browser only honours autofocus for elements present when the document flushes its autofocus candidates
  // (Preact doesn't special-case it either). Focus explicitly — on mount, and again when the 2FA step
  // replaces the form, so the code can be typed without reaching for the mouse.
  const focusRef = useRef(null);
  useEffect(() => { focusRef.current && focusRef.current.focus(); }, [twofa]);
  const submit = async e => {
    if (e) e.preventDefault();
    if (busy) return;
    setBusy(true); setErr("");
    try {
      const r = await api.login({ username: u, password: p, code: twofa ? code.trim() : undefined });
      if (r && r.ok) {
        try { await subUnlock(p); } catch (_) {}   // convenience cache: auto-unlock config encryption with the login password (no-op if no vault); survives the reload via sessionStorage
        location.reload(); return;
      }
      if (r && r.twofa_required) {                       // password OK — panel wants the 6-digit code
        const msg = (r && r.error) || "";
        setTwofa(true); setErr(msg);
        if (msg) {                                       // a REJECTED code: clear it (else the next digits append) and
          setCode("");                                   // take focus back from the Verify button so retyping just works.
          focusRef.current && focusRef.current.focus();  // same DOM node — `twofa` didn't flip, so it is not remounted
        }
        setBusy(false); return;
      }
      setErr((r && r.error) || "Login failed."); setBusy(false);
    } catch (_) { setErr("Couldn't reach the panel."); setBusy(false); }
  };
  return html`<div class="login-wrap"><form class="login-card" onSubmit=${submit}>
    <div class="login-brand"><span class="brand-mark"></span><span class="brand-name">swg<span>Panel</span></span></div>
    <h2>${twofa ? "Two-factor" : "Sign in"}</h2>
    ${twofa ? html`
      <p class="muted" style="margin:-4px 0 12px">Enter the 6-digit code from your authenticator app, or a recovery code.</p>
      <div class="field"><label>Authentication code</label><input ref=${focusRef} value=${code} onInput=${e => setCode(e.target.value)} inputmode="text" autocomplete="one-time-code" placeholder="123 456"/></div>
      ${err ? html`<div class="formmsg err">${err}</div>` : null}
      <button class="btn btn-primary" type="submit" disabled=${busy} style="width:100%;justify-content:center;margin-top:4px">${busy ? "Verifying…" : "Verify"}</button>
      <button class="btn btn-ghost" type="button" onClick=${() => { setTwofa(false); setCode(""); setErr(""); }} style="width:100%;justify-content:center;margin-top:8px">Back</button>
    ` : html`
      <div class="field"><label>Username</label><input ref=${focusRef} value=${u} onInput=${e => setU(e.target.value)} autocomplete="username"/></div>
      <div class="field"><label>Password</label><input type="password" value=${p} onInput=${e => setP(e.target.value)} autocomplete="current-password"/></div>
      ${err ? html`<div class="formmsg err">${err}</div>` : null}
      <button class="btn btn-primary" type="submit" disabled=${busy} style="width:100%;justify-content:center;margin-top:4px">${busy ? "Signing in…" : "Sign in"}</button>
    `}
  </form></div>`;
}
function doLogout() {
  openConfirm({ title: "Log out", confirmLabel: "Log out",
    body: "Are you sure you want to logout?",
    onConfirm: async () => { subForget(); try { await api.logout(); } catch (_) {} location.reload(); } });
}
// Account form as a modal (same chrome as the node sheets).

// ───────────────────────── boot ─────────────────────────
const viewEl = $("#view");
viewEl.innerHTML = `<div class="loading"><span class="spin"></span>connecting…</div>`;
(async () => {
  await subBootRestore();   // restore the config-encryption convenience cache from sessionStorage (post-login reload)
  try { await Store.init(); }
  catch (e) { if (!_loginShown) viewEl.innerHTML = `<div class="empty"><b>Can't reach the panel</b>${esc(e.message)}</div>`; return; }
  if (!location.hash) location.hash = "#/";
  render(h(App), viewEl);
})();
