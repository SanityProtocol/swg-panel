/* util.js — pure helpers for the operator console.
 *
 * LAYER 0 of the SPA module graph (see docs/APP-JS-SPLIT-PLAN.md). This module must stay a LEAF:
 * it may import from `preact`/`preact/hooks` and (later) `./i18n.js`, and from NOTHING else in js/.
 * Nothing here may read `Store` — anything that does belongs in `model.js`, one layer up.
 *
 * The formatters below (`ago`, `seen`, `rate`, `dur`, `configErrors`) return USER-VISIBLE text and
 * are therefore the first things the i18n pass will route through `T()`; that is why i18n.js sits
 * BELOW this module in the graph rather than beside it.
 */

import { useRef } from "preact/hooks";
import { T } from "./i18n.js";

// ───────────────────────── tiny helpers ─────────────────────────
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
export const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const b64 = u => { let s = ""; for (const x of u) s += String.fromCharCode(x); return btoa(s); };

// Mount-point prefix: when served under a subpath (e.g. /swg), <base href> carries
// it, so root-absolute API/stats paths must be prefixed to stay inside the mount.
export const BASE = (() => { try { return new URL(document.baseURI).pathname.replace(/\/+$/, ""); } catch (_) { return ""; } })();
export const url = p => BASE + p;

export const tkey = (node, iface) => node + "|" + iface;          // session-config key for one target
// A peer's targets ordered PRIMARY-first (the one flagged `primary`, else the first), then creation order.
export function orderedTargets(targets) {
  const ts = (targets || []).slice();
  const pi = ts.findIndex(t => t && t.primary);
  if (pi > 0) { const [pt] = ts.splice(pi, 1); ts.unshift(pt); }
  return ts;
}
// Is this target the peer's primary? (explicit `primary`, else the first target is the implicit primary.)
export function isPrimaryTarget(targets, t) {
  const ts = targets || [];
  const pi = ts.findIndex(x => x && x.primary);
  const idx = ts.findIndex(x => x && x.node === t.node && x.iface === t.iface);
  return pi >= 0 ? idx === pi : idx === 0;
}
// Primary-first order FROZEN on first render (per component mount) — so toggling the primary ★ or picking targets
// inside a modal never re-shuffles the rows under the operator's cursor; the order re-sorts only on the next open.
// New targets append (they stay put on subsequent renders too). Call at the top level of a component (it's a hook).
export function useStableOrder(targets) {
  const ref = useRef(null);
  const ts = targets || [];
  if (ref.current === null && ts.length) ref.current = orderedTargets(ts).map(t => tkey(t.node, t.iface));
  const pos = ref.current;
  if (!pos) return ts.slice();
  const rank = t => { const i = pos.indexOf(tkey(t.node, t.iface)); return i < 0 ? pos.length : i; };
  const out = ts.slice().sort((a, b) => rank(a) - rank(b));
  out.forEach(t => { const k = tkey(t.node, t.iface); if (!pos.includes(k)) pos.push(k); });
  return out;
}
export const isWdttIface = (name) => /^wdtt\d{1,3}$/.test(String(name));   // classify a WDTT interface by NAME (when there's no roster target to read `type` from); mirrors the node's _WDTT_IFACE_RE
export const isCsqttIface = (name) => /^csqtt\d{1,4}$/.test(String(name));   // classify a csqtt interface by NAME; mirrors the node's _CSQTT_NAME_RE
export const isSelfContainedIface = (name) => isWdttIface(name) || isCsqttIface(name);   // WDTT + csqtt own their own interface (keyless, not a WG target)
// The self-contained turn-family KINDS: they own their interface, mint the client address on connect, and carry a
// panel-owned access password instead of a browser keypair. ONE source of truth — every shared gate reads these,
// so adding the next such kind is a single edit here, not a hunt through every filter/colour/vault/picker site.
export const SELF_CONTAINED_KINDS = ["wdtt", "csqtt"];
export const isSelfContainedKind = (kind) => kind === "wdtt" || kind === "csqtt";
export const isSelfContainedTarget = (t) => !!t && (isSelfContainedKind(t.type) || isSelfContainedIface(t.iface));   // by roster target `type` OR iface-name sniff
export function ipOf(hostport) { if (!hostport) return ""; const s = String(hostport); return s[0] === "[" ? s.slice(1, s.indexOf("]")) : s.split(":")[0]; }
export const listenAddr = (host, port) => (port ? ((host ? host : "0.0.0.0") + ":" + port) : "\u2014");

export function portOf(hostport) { if (!hostport) return ""; const s = String(hostport); const i = s.lastIndexOf(":"); return i < 0 ? "" : s.slice(i + 1); }
export const ipPickerVal = (sel, custom) => sel === "__custom__" ? (custom || "").trim() : sel;

export function ago(sec) {
  if (sec == null) return "—";
  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec));
  if (d < 60) return T("just now");
  if (d < 3600) return T("{n}m ago", { n: Math.floor(d / 60) });
  if (d < 86400) return T("{n}h ago", { n: Math.floor(d / 3600) });
  return T("{n}d ago", { n: Math.floor(d / 86400) });
}
export function seen(age) {
  if (age == null) return "—";
  if (age < 90) return age + T("unit|s");
  if (age < 5400) return Math.round(age / 60) + T("unit|m");
  if (age < 172800) return Math.round(age / 3600) + T("unit|h");
  return Math.round(age / 86400) + T("unit|d");
}
export function rate(bps) {
  bps = bps || 0;
  const u = ["B", "K", "M", "G"]; let i = 0, v = bps;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + u[i] + "/s";
}
// Nice y-axis ceiling for a throughput graph: the smallest "1/5/10/50/100/500 × {B,K,M,G}" value ≥ bps.
// Base-1024 to match rate(), so the scale badge reads e.g. "50 K/s" / "500 K/s" / "1 M/s"; past 500 it rolls to
// the next unit (…500 K → 1 M, never an ugly "1000 K"). Callers pass peak/0.85 to guarantee ≥15% headroom.
export function niceScaleCeil(bps) {
  const LADDER = [1, 5, 10, 50, 100, 500];
  let unit = 1;
  while (bps >= 1024 * unit) unit *= 1024;
  const m = bps / unit;
  for (const L of LADDER) if (m <= L) return L * unit;
  return 1024 * unit;
}

// ── validation for fields that affect connectivity / data-structure ──
export const V = {
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
export function configErrors(cf) {
  const e = {};
  if (cf.allowed.trim() && !V.list(cf.allowed, V.cidr)) e.allowed = T("Comma-separated CIDRs, e.g. 0.0.0.0/0, ::/0");
  else if (!cf.allowed.trim()) e.allowed = T("Required (use 0.0.0.0/0, ::/0 for full tunnel).");
  if (cf.dns.trim() && !V.list(cf.dns, V.ip)) e.dns = T("Each DNS must be a valid IP.");
  if (cf.mtu.trim() && !V.mtu(cf.mtu)) e.mtu = T("MTU must be a number 1280–9200.");
  if (cf.keepalive.trim() && !V.keepalive(cf.keepalive)) e.keepalive = T("Keepalive must be 0–65535.");
  return e;
}
export function fmtBytes(n) {
  n = n || 0;
  const u = ["B", "K", "M", "G", "T"]; let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)) + u[i];
}
export function dur(sec) {
  if (sec == null) return "—";
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d) return d + T("unit|d") + " " + h + T("unit|h");
  if (h) return h + T("unit|h") + " " + m + T("unit|m");
  if (m) return m + T("unit|m");
  return sec + T("unit|s");
}

// RFC1918 / loopback / link-local / CGNAT — kept selectable (valid behind cloud 1:1 NAT or on a private
// interconnect) but tagged "(private)" so an operator knows it isn't a public address.
export const isPrivIp = ip => /^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(ip || "");
