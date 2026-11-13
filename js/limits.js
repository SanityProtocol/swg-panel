// Speed limits in the browser (docs/LIMITS-PLAN.md, limits-l3). The panel stores `limits` = {d, u} or {c} in Mbit/s on a group,
// a user, a device and a deployment, and sends each node its wire list (limits-l2); the node loads tc policers (limits-l1). This
// module is the read side and the one editor control: what a record's limit is, which one wins for a deployment, whether a
// deployment is held at it now, and where a limit would not be enforced. It reads only what the roster and the snapshots already
// carry — nothing on the 5 s poll is added for it (SCALE-PLAN U1).
import { Store } from "./store.js";
import { tgtXfer, isSelfContainedTgt } from "./model.js";
import { unvouchedTarget, namedFew } from "./views.js";
import { Ic, Sheet, footRow, pushModal, closeModal, dlul } from "./ui.js";
import { T } from "./i18n.js";
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";
const html = htm.bind(h);

export const LIMITS_MAX_MBIT = 100000;          // the server's LIMITS_MAX_MBIT
export const HELD_AT = 0.85;                    // a direction moving at 85 % of its limit or more reads "held at its limit"

const okRate = v => typeof v === "number" && isFinite(v) && v >= 1 && v <= LIMITS_MAX_MBIT;
// A stored limit as the server's limits_clean reads it: {d?, u?} or {c}, each 1..100000, else none (a hand edit reads as none).
export function limClean(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const ks = Object.keys(raw);
  if (!ks.length || ks.some(k => k !== "d" && k !== "u" && k !== "c") || ("c" in raw && ks.length > 1)) return null;
  return ks.every(k => okRate(raw[k])) ? raw : null;
}
// Lower is tighter: download (combined or d) first, then upload; a direction with no figure is unlimited — the server's _lim_key.
const limKey = l => [l.c || l.d || Infinity, l.c || l.u || Infinity];
const lower = (a, b) => { const x = limKey(a), y = limKey(b); return x[0] < y[0] || (x[0] === y[0] && x[1] < y[1]); };
const canon = l => { l = limClean(l); return !l ? "" : l.c ? "c" + l.c : "d" + (l.d || 0) + "u" + (l.u || 0); };   // key order never matters
export const limSame = (a, b) => canon(a) === canon(b);

const num = v => String(+(+v).toFixed(3));
// In the rate cell's own shape and arrows, so a limit reads against the rate beside it: the panel's throughput perspective
// (dlul) decides which side ↓ is. A limit's u is what the node receives (the rx side), its d what it sends (tx).
export function limText(l) {
  l = limClean(l);
  if (!l) return "";
  if (l.c) return T("{v1} Mbit/s both ways", { v1: num(l.c) });
  const [dn, up] = dlul(l.u || 0, l.d || 0);
  return [dn ? "↓ " + num(dn) : "", up ? "↑ " + num(up) : ""].filter(Boolean).join(" ") + " " + T("Mbit/s");
}
// In words from the device's side, as the editor's Download / Upload fields say it — for the sentences around those fields.
export function limWords(l) {
  l = limClean(l);
  if (!l) return "";
  if (l.c) return T("{v1} Mbit/s both ways", { v1: num(l.c) });
  return [l.d ? T("download {v1}", { v1: num(l.d) }) : "", l.u ? T("upload {v1}", { v1: num(l.u) }) : ""].filter(Boolean).join(", ") + " " + T("Mbit/s");
}

// A user's limit: their own (pool u:<uid>), else the LOWEST of their groups' (pool g:<gid>) — ties to the group whose id sorts
// first, as the server walks them. Built once per roster: the Live grid asks it per row.
let _uCache = null, _uOf = null;
export function userLimit(uid) {
  if (!uid) return null;
  if (_uOf !== Store.roster) { _uCache = new Map(); _uOf = Store.roster; }
  if (_uCache.has(uid)) return _uCache.get(uid);
  const u = Store.user(uid);
  let out = null;
  const own = u && limClean(u.limits);
  if (own) out = { lim: own, src: "user", name: u.name || "", pool: "u:" + uid };
  else if (u) {
    const gs = Store.groupsByUser(uid).slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    for (const g of gs) { const l = limClean(g.limits); if (l && (!out || lower(l, out.lim))) out = { lim: l, src: "group", name: g.name, gid: g.id, pool: "g:" + g.id }; }
  }
  _uCache.set(uid, out);
  return out;
}
// The limit a deployment runs under (docs/LIMITS-PLAN.md §3.4): its own, else the device's, else the user's or the lowest group's.
// A device's own limit is ONE budget for its entries on a node (limits-l2 F4), hence its pool p:<id>.
export function effLimit(peer, t) {
  if (!peer || !t) return null;
  const tl = limClean(t.limits);
  if (tl) return { lim: tl, src: "deployment", pool: "t:" + peer.id + "|" + t.iface };
  const pl = limClean(peer.limits);
  if (pl) return { lim: pl, src: "device", pool: "p:" + peer.id };
  return peer.user_id ? userLimit(peer.user_id) : null;
}
// The limit a record WOULD fall back to without its own — the line under the editor. A user: the lowest group's; a device: the
// user's (or their group's); a deployment: the device's, else the user's.
export function fallbackFor(level, rec, peer) {
  if (level === "user") {
    let out = null;
    for (const g of Store.groupsByUser(rec.id).slice().sort((a, b) => (a.id < b.id ? -1 : 1))) {
      const l = limClean(g.limits); if (l && (!out || lower(l, out.lim))) out = { lim: l, src: "group", name: g.name };
    }
    return out;
  }
  if (level === "device") return rec.user_id ? userLimit(rec.user_id) : null;
  if (level === "deployment") return effLimit(peer, { ...rec, limits: null });
  return null;
}

// What a limit's source is called, short (the peer view's cell) and in a sentence (the editor's fallback line).
export const srcShort = e => e.src === "deployment" ? T("lim|own") : e.src === "device" ? T("lim|device")
  : e.src === "user" ? T("lim|user {name}", { name: e.name }) : T("lim|group {name}", { name: e.name });
function fallbackLine(e, own) {
  const lim = limWords(e.lim);
  if (e.src === "device") return own ? T("This replaces the device's limit ({lim}).", { lim }) : T("Without one of its own, the device's limit applies: {lim}.", { lim });
  if (e.src === "user") return own ? T("This replaces {name}'s limit ({lim}).", { name: e.name, lim }) : T("Without one of its own, {name}'s limit applies: {lim}.", { name: e.name, lim });
  return own ? T("This replaces group {name}'s limit ({lim}).", { name: e.name, lim }) : T("Without one of its own, group {name}'s limit applies: {lim}.", { name: e.name, lim });
}

// ── held at its limit (Live) ──────────────────────────────────────────────────────────────────────────────────────────────
// The rates the browser already has, against the limit: a deployment's own policer reads its own rates; a pool (a device on two
// interfaces, a user, a group) reads the sum of its members' deployments on that node — the shared policer holds the SUM. One
// index per recon, built only when the roster carries a limit at all.
let _pIdx = null, _pOf = null;
const anyLimit = () => {
  const r = Store.roster || {};
  const has = o => o && typeof o === "object" && Object.values(o).some(x => x && (x.limits || (x.targets || []).some(t => t && t.limits)));
  return has(r.users) || has(r.groups) || has(r.peers);
};
function poolRates() {
  if (_pOf === Store.recon) return _pIdx;
  _pOf = Store.recon; _pIdx = null;
  if (!anyLimit()) return null;
  const m = new Map();
  for (const p of (Store.recon.peers || [])) for (const t of (p.targets || [])) {
    const e = effLimit(p, t), x = e && tgtXfer(t);
    if (!x) continue;
    const k = t.node + "|" + e.pool, a = m.get(k) || m.set(k, { rx: 0, tx: 0 }).get(k);
    a.rx += x.rx_speed || 0; a.tx += x.tx_speed || 0;
  }
  return (_pIdx = m);
}
// {e, dir} when this deployment's limit is holding it now, else null. rx = what the node received (the device's upload), tx = what
// it sent (the device's download); the limit's d / u are the device's download / upload.
export function limitHeld(peer, t) {
  const e = effLimit(peer, t);
  if (!e) return null;
  const idx = poolRates(), a = idx && idx.get(t.node + "|" + e.pool);
  if (!a) return null;
  const mbit = b => b * 8 / 1e6, l = e.lim;
  if (l.c) return mbit(a.rx + a.tx) >= HELD_AT * l.c ? e : null;
  return (l.d && mbit(a.tx) >= HELD_AT * l.d) || (l.u && mbit(a.rx) >= HELD_AT * l.u) ? e : null;
}
export const heldTitle = e => T("Held at its speed limit: {lim} ({src})", { lim: limText(e.lim), src: srcShort(e) });
// The peer view's mark beside its rate; the Live grid has no room for one (a fixed-width column) and tints its figures instead.
export function HeldMark({ peer, t }) {
  const e = limitHeld(peer, t);
  return e ? html`<span class="limheld" title=${heldTitle(e)}><${Ic} i="gauge"/></span>` : null;
}

// ── where a limit would not be enforced ──────────────────────────────────────────────────────────────────────────────────────
// A node that reports no `limits` in net_deps runs a build without them (read from there, not the version string: a dev build
// reports the last release's); a keyless deployment on a build the node cannot vouch for has no address to limit (§3.3). Only
// LIVE nodes: a node not reporting says nothing either way.
export function limitGaps(targets) {
  const old = new Set(), unv = [];
  for (const t of targets || []) {
    if (!t || !t.node || Store.recon.nodeStatus[t.node] !== "live") continue;
    if (!(((Store.stats[t.node] || {}).net_deps || {}).limits)) old.add(t.node);
    else if (isSelfContainedTgt(t) && unvouchedTarget(t)) unv.push(t);
  }
  return { old: [...old], unv };
}
// Every deployment a level's limit reaches.
export const targetsOfUsers = uids => uids.flatMap(u => Store.peersByUser(u)).flatMap(p => p.targets || []);
function GapNotes({ gaps }) {
  if (!gaps) return null;
  return html`${gaps.old.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${gaps.old.length === 1
      ? T("Not enforced on {node}: it runs a version without speed limits. Update it.", { node: Store.nodeName(gaps.old[0]) })
      : T("Not enforced on {nodes}: they run a version without speed limits. Update them.", { nodes: namedFew(gaps.old.map(n => Store.nodeName(n))) })}</span></div>` : null}
    ${gaps.unv.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Not enforced for {targets}: this server build can't prove which address a device has.",
      { targets: namedFew(gaps.unv.map(t => t.iface + " · " + Store.nodeName(t.node))) })}</span></div>` : null}`;
}

// ── a node's own report (limit_err) ──────────────────────────────────────────────────────────────────────────────────────────
// The node fails open: a limiter it could not load cuts nobody, the traffic just flows. Each line names the device (or `caps`,
// `sweep`, `limits`) and the node's own words, for the node's issues badge.
export function limitIssues(nid) {
  const e = (Store.stats[nid] || {}).limit_err;
  if (!e || typeof e !== "object") return [];
  return Object.keys(e).sort().map(k => T("Speed limit not applied on {dev}: {why}. Nothing is cut; traffic there runs unlimited.", { dev: k, why: String(e[k] || "") }));
}

// ── the editor ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
// The draft a field edits, as typed: {mode: "none" | "du" | "c", d, u, c} (strings). limDraft from a stored limit; limFromDraft
// back to what is sent, or an error the field shows. A blank direction is unlimited; at least one figure in "du".
export function limDraft(l) {
  l = limClean(l);
  return !l ? { mode: "none", d: "", u: "", c: "" } : l.c ? { mode: "c", d: "", u: "", c: num(l.c) } : { mode: "du", d: l.d ? num(l.d) : "", u: l.u ? num(l.u) : "", c: "" };
}
export function limFromDraft(dr) {
  const one = s => (String(s).trim() === "" ? null : +String(s).trim().replace(",", "."));
  const bad = v => v !== null && !okRate(v);
  if (dr.mode === "c") {
    const c = one(dr.c);
    if (c === null || bad(c)) return { err: T("A speed limit must be between 1 and {v1} Mbit/s", { v1: LIMITS_MAX_MBIT }) };
    return { lim: { c } };
  }
  if (dr.mode === "du") {
    const d = one(dr.d), u = one(dr.u);
    if (bad(d) || bad(u)) return { err: T("A speed limit must be between 1 and {v1} Mbit/s", { v1: LIMITS_MAX_MBIT }) };
    if (d === null && u === null) return { err: T("Enter a download or an upload limit, or choose No limit.") };
    return { lim: { ...(d !== null ? { d } : {}), ...(u !== null ? { u } : {}) } };
  }
  return { lim: {} };
}
const HINTS = {
  user: () => T("One budget for all of this person's devices on a server, shared between the ones in use. On two servers they can reach it on each."),
  group: () => T("One budget for everyone in the group on a server, shared between the devices in use. On two servers the group can reach it on each. A person in two limited groups gets the lower limit, and a person's own limit replaces the group's."),
  device: () => T("For this device on each server it is on. Download and upload are the device's own."),
  deployment: () => T("For this deployment only. Removing the deployment removes its limit too."),
};
// level: user | group | device | deployment. fallback: what applies without one of its own (fallbackFor), gaps: limitGaps(…).
export function LimitField({ draft, onChange, level, fallback, gaps, err }) {
  const set = p => onChange({ ...draft, ...p });
  const seg = (m, label) => html`<button type="button" role="radio" aria-checked=${draft.mode === m} class=${"seg" + (draft.mode === m ? " on" : "")}
    onClick=${() => set({ mode: m })}>${label}</button>`;
  const box = (k, label) => html`<label class="limin"><span class="limin-k">${label}</span>
    <input type="text" inputmode="decimal" value=${draft[k]} placeholder=${k === "c" ? "" : T("no limit")} aria-label=${label}
      class=${err && String(draft[k]).trim() !== "" && !okRate(+String(draft[k]).replace(",", ".")) ? "bad" : ""}
      onInput=${e => set({ [k]: e.target.value })}/><span class="limin-u">${T("Mbit/s")}</span></label>`;
  const own = draft.mode !== "none";
  return html`<div class="field limfield">
    <label>${T("Speed limit")}</label>
    <div class="segrow" role="radiogroup" aria-label=${T("Speed limit")}>
      ${seg("none", T("No limit"))}${seg("du", T("Download / upload"))}${seg("c", T("Combined"))}
    </div>
    ${draft.mode === "du" ? html`<div class="limrow">${box("d", T("lim|Download"))}${box("u", T("lim|Upload"))}</div>`
      : draft.mode === "c" ? html`<div class="limrow">${box("c", T("Both ways together"))}</div>` : null}
    ${err ? html`<div class="hint err">${err}</div>` : null}
    <div class="hint">${HINTS[level]()}${fallback ? " " + fallbackLine(fallback, own) : ""}</div>
    ${own ? html`<${GapNotes} gaps=${gaps}/>` : null}
  </div>`;
}

// A field's state: the draft, whether it differs from what is stored (a draft that does not parse counts as a change, so Save
// stays on and shows why), and take(): the limit to send — {} clears it — or null once the error is on screen.
export function useLimit(stored) {
  const [draft, setDraft] = useState(() => limDraft(stored));
  const [err, setErr] = useState("");
  const out = limFromDraft(draft);
  return { draft, err, changed: !!out.err || !limSame(out.lim, stored),
           set: d => { setDraft(d); setErr(""); },
           take: () => { if (out.err) { setErr(out.err); return null; } return out.lim; } };
}

// A deployment's own limit (R7): a gauge on its row in Edit peer, lit when it has one, opening the sheet below. Staged like the gear's
// settings: the row's limit is sent with Edit peer's Save, through update-target — the only door a deployment limit has.
export function LimitGauge({ peer, t, value, onApply }) {
  const own = limClean(value);
  return html`<button type="button" class=${"btn btn-mini ico topt-gear topt-lim" + (own ? " on" : "")}
    title=${own ? T("Speed limit for this deployment: {lim}", { lim: limWords(own) }) : T("Speed limit for this deployment")}
    aria-label=${T("Speed limit for this deployment")}
    onClick=${e => { e.preventDefault(); e.stopPropagation(); pushModal(html`<${TargetLimitSheet} peer=${peer} t=${t} value=${value} onApply=${onApply}/>`); }}><${Ic} i="gauge"/></button>`;
}
function TargetLimitSheet({ peer, t, value, onApply }) {
  const lim = useLimit(value);
  const apply = () => { const l = lim.take(); if (l === null) return; onApply(l); closeModal(); };
  return html`<${Sheet} title=${T("Speed limit — {v1} on {v2}", { v1: t.iface, v2: Store.nodeName(t.node) })} width=${560} onBack=${closeModal}
    foot=${footRow({ onCancel: closeModal, onAction: apply, action: T("Apply") })}>
    <${LimitField} draft=${lim.draft} onChange=${lim.set} err=${lim.err} level="deployment"
      fallback=${fallbackFor("deployment", t, peer)} gaps=${limitGaps([t])}/>
  <//>`;
}
