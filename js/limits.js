// Speed limits in the browser (docs/LIMITS-PLAN.md, limits-l3). The panel stores `limits` = {d, u} or {c} in Mbit/s on a group,
// a user, a device and a deployment, and sends each node its wire list (limits-l2); the node loads tc policers (limits-l1). This
// module is the read side and the one editor control: what a record's limit is, which one wins for a deployment, whether a
// deployment is held at it now, and where a limit would not be enforced. It reads only what the roster and the snapshots already
// carry — nothing on the 5 s poll is added for it (SCALE-PLAN U1).
import { Store, api } from "./store.js";
import { tgtXfer, isSelfContainedTgt } from "./model.js";
import { namedFew, rawUnvouchedAt } from "./views.js";
import { Ic, Sheet, footRow, pushModal, closeModal, dlul } from "./ui.js";
import { T, locale } from "./i18n.js";
import { h } from "preact";
import { useState, useEffect } from "preact/hooks";
import htm from "htm";
const html = htm.bind(h);

const LIMITS_MAX_MBIT = 100000;                 // the server's LIMITS_MAX_MBIT
const HELD_AT = 0.85;                           // a direction moving at 85 % of its share of a limit or more reads "held at its limit"

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

// The LOWEST of a user's groups' limits (pool g:<gid>) — ties to the group whose id sorts first, as the server walks them.
function groupLimit(uid) {
  let out = null;
  for (const g of Store.groupsByUser(uid).slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const l = limClean(g.limits);
    if (l && (!out || lower(l, out.lim))) out = { lim: l, src: "group", name: g.name, gid: g.id, pool: "g:" + g.id };
  }
  return out;
}
// A user's limit: their own (pool u:<uid>), else their groups' lowest. Kept per roster: the Live grid asks it per row.
const _uMemo = new WeakMap();
export function userLimit(uid) {
  if (!uid) return null;
  const r = Store.roster || {};
  let m = _uMemo.get(r);
  if (!m) _uMemo.set(r, (m = new Map()));
  if (m.has(uid)) return m.get(uid);
  const u = Store.user(uid), own = u && limClean(u.limits);
  const out = own ? { lim: own, src: "user", name: u.name || "", pool: "u:" + uid } : u ? groupLimit(uid) : null;
  m.set(uid, out);
  return out;
}
// The limit a deployment runs under (docs/LIMITS-PLAN.md §3.4): its own, else the device's, else the user's or the lowest group's.
// A device's own limit is ONE budget for its entries on a node (limits-l2 F4), hence its pool p:<id>.
function cfgLimit(peer, t) {
  if (!peer || !t) return null;
  const tl = limClean(t.limits);
  if (tl) return { lim: tl, src: "deployment", pool: "t:" + peer.id + "|" + t.iface };
  const pl = limClean(peer.limits);
  if (pl) return { lim: pl, src: "device", pool: "p:" + peer.id };
  return peer.user_id ? userLimit(peer.user_id) : null;
}
// …and the one in force: a volume limit's "slow" (/api/state `vol`) is 1 Mbit/s both ways, ONE pool for the person's devices on
// a node (or the device's, slowed by its own limit), unless the configured limit is lower already — swg-panel-server
// limits_for_node's rule, so Live's "held" and the peer view say what the node runs.
const SLOW = { c: 1 };
export function effLimit(peer, t) {
  const e = cfgLimit(peer, t), v = Store.vol;
  if (!v || !peer || !t) return e;
  const sk = peer.user_id && v[peer.user_id] === "slow" ? peer.user_id : v[peer.id] === "slow" ? peer.id : null;
  return !sk || (e && !lower(SLOW, e.lim)) ? e : { lim: SLOW, src: "volume", pool: "s:" + sk };
}
// The limit a record WOULD fall back to without its own — the line under the editor. A user: the lowest group's; a device: the
// user's (or their group's); a deployment: the device's, else the user's.
export function fallbackFor(level, rec, peer) {
  if (level === "user") return groupLimit(rec.id);
  if (level === "device") return rec.user_id ? userLimit(rec.user_id) : null;
  if (level === "deployment") return cfgLimit(peer, { ...rec, limits: null });
  return null;
}

// What a limit's source is called, short (the peer view's cell) and in a sentence (the editor's fallback line).
export const srcShort = e => e.src === "volume" ? T("volume used up") : e.src === "deployment" ? T("lim|own") : e.src === "device" ? T("lim|device")
  : e.src === "user" ? T("lim|user {name}", { name: e.name }) : T("lim|group {name}", { name: e.name });
function fallbackLine(e, own) {
  const lim = limWords(e.lim);
  if (e.src === "device") return own ? T("This replaces the device's limit ({lim}).", { lim }) : T("Without one of its own, the device's limit applies: {lim}.", { lim });
  // {lim} first: a name is filled in last, so a name that reads "{lim}" stays a name
  if (e.src === "user") return own ? T("This replaces {name}'s limit ({lim}).", { lim, name: e.name }) : T("Without one of its own, {name}'s limit applies: {lim}.", { lim, name: e.name });
  return own ? T("This replaces group {name}'s limit ({lim}).", { lim, name: e.name }) : T("Without one of its own, group {name}'s limit applies: {lim}.", { lim, name: e.name });
}

// ── where a limit is not in force ────────────────────────────────────────────────────────────────────────────────────────
// Why a limit on this deployment does not hold on its node, else null: "old" — the node reports no `limits` in net_deps, a build
// without them (read from there, not the version string: a dev build reports the last release's); "unv" — a keyless build the
// node cannot vouch for has no address to limit (§3.3); "raw" — a WDTT build vouched for its WireGuard path only, so a device on
// its RAW path runs unlimited. Only LIVE nodes: a node not reporting says nothing either way.
export function gapOf(t) {
  if (!t || !t.node || Store.recon.nodeStatus[t.node] !== "live") return null;
  if (!(((Store.stats[t.node] || {}).net_deps || {}).limits)) return "old";
  if (!isSelfContainedTgt(t)) return null;
  const nr = (Store.nodes || []).find(x => x.id === t.node) || {};
  return (nr.reach_unvouched || []).includes(t.iface) ? "unv" : rawUnvouchedAt(t) ? "raw" : null;
}
// Every gap a level's limit meets: the nodes (once each) and the keyless interfaces (once each, however many devices sit there).
export function limitGaps(targets) {
  const old = new Set(), unv = new Map();
  for (const t of targets || []) {
    const g = gapOf(t);
    if (g === "old") old.add(t.node);
    else if (g) unv.set(t.node + "|" + t.iface + "|" + g, t.iface + (g === "raw" ? " (RAW)" : "") + " · " + Store.nodeName(t.node));
  }
  return { old: [...old], unv: [...unv.values()] };
}
// Every deployment a level's limit reaches.
export const targetsOfUsers = uids => uids.flatMap(u => Store.peersByUser(u)).flatMap(p => p.targets || []);
function GapNotes({ gaps }) {
  if (typeof gaps === "function") gaps = gaps();   // worked out only when a limit is drafted (a 10,000-member group)
  if (!gaps) return null;
  return html`${gaps.old.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${gaps.old.length === 1
      ? T("Not enforced on {node}: it runs a version without speed limits. Update it.", { node: Store.nodeName(gaps.old[0]) })
      : T("Not enforced on {nodes}: they run a version without speed limits. Update them.", { nodes: namedFew(gaps.old.map(n => Store.nodeName(n))) })}</span></div>` : null}
    ${gaps.unv.length ? html`<div class="notice warn"><${Ic} i="warn"/><span>${T("Not enforced for {targets}: this server build can't prove which address a device has.",
      { targets: namedFew(gaps.unv) })}</span></div>` : null}`;
}

// ── held at its limit (Live) ──────────────────────────────────────────────────────────────────────────────────────────────
// The rates the browser already has, against what the node lets this deployment move. A pool shared by several members on a
// node (a device on two interfaces, a user, a group) holds their SUM, and the node also caps each member at the limit ÷ the
// members moving in that direction (≥ 1 % of it, swg-noded _limits_caps) — so a member is held at its share, never by another's
// traffic. One index per recon (node|pool → its members' [rx, tx] in Mbit/s), made the first time a row asks.
const mbit = b => (b || 0) * 8 / 1e6;
const _pools = new WeakMap();
function poolMembers(node, pool) {
  const rc = Store.recon;
  let m = _pools.get(rc);
  if (!m) {
    _pools.set(rc, (m = new Map()));
    for (const p of (rc.peers || [])) for (const t of (p.targets || [])) {
      const e = effLimit(p, t), x = e && tgtXfer(t);
      if (!x) continue;
      const k = t.node + "|" + e.pool;
      (m.get(k) || m.set(k, []).get(k)).push([mbit(x.rx_speed), mbit(x.tx_speed)]);
    }
  }
  return m.get(node + "|" + pool) || [];
}
// {e, rx, tx} when this deployment's limit is holding it now (rx: what the node received, the device's upload, held by u; tx: what
// it sent, the device's download, held by d; both for c), else null. Never where the limit is not in force, and never for a
// WDTT / csqtt deployment: its rates are per-pass counter deltas every 10–30 s, which would flash "held" and back.
export function limitHeld(peer, t) {
  if (!t || isSelfContainedTgt(t) || gapOf(t)) return null;
  const e = effLimit(peer, t), x = e && tgtXfer(t);
  if (!x) return null;
  const mem = poolMembers(t.node, e.pool), l = e.lim, rx = mbit(x.rx_speed), tx = mbit(x.tx_speed);
  const at = (lim, mine, of) => !!lim && mine >= HELD_AT * lim / Math.max(1, mem.filter(m => of(m) >= lim * 0.01).length);
  if (l.c) return at(l.c, rx + tx, m => m[0] + m[1]) ? { e, rx: true, tx: true } : null;
  const hTx = at(l.d, tx, m => m[1]), hRx = at(l.u, rx, m => m[0]);
  return hTx || hRx ? { e, rx: hRx, tx: hTx } : null;
}
export const heldTitle = h => T("Held at its speed limit: {lim} ({src})", { lim: limText(h.e.lim), src: srcShort(h.e) });
// The Live grid's rate cell: the held direction's figure turns amber, in the panel's perspective (a phone shows only ↓).
export const heldCls = h => { if (!h) return ""; const [dn, up] = dlul(h.rx ? 1 : 0, h.tx ? 1 : 0); return (dn ? " held-dn" : "") + (up ? " held-up" : ""); };
// The peer view's mark beside its rate.
export function HeldMark({ peer, t }) {
  const h = limitHeld(peer, t);
  return h ? html`<span class="limheld" title=${heldTitle(h)}><${Ic} i="gauge"/></span>` : null;
}
// The peer view's limit cell: what this deployment runs under, from where, and — where it does not hold — that it does not.
export function LimitCell({ peer, t }) {
  const e = effLimit(peer, t);
  if (!e) return null;
  const g = gapOf(t);
  return html`<span class="pv-lim"><span class="k">${T("col|Speed limit")}</span><${Ic} i="gauge"/> ${limText(e.lim)} <span class="faint">${srcShort(e)}</span>${g
    ? html` <span class="limgap">${g === "raw" ? T("not enforced over RAW") : T("not enforced here")}</span>` : null}</span>`;
}

// ── the editor ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
// The draft a field edits, as typed: {mode: "none" | "du" | "c", d, u, c} (strings). limDraft from a stored limit; limFromDraft
// back to what is sent, or an error the field shows. A blank direction is unlimited; at least one figure in "du".
export function limDraft(l) {
  l = limClean(l);
  return !l ? { mode: "none", d: "", u: "", c: "" } : l.c ? { mode: "c", d: "", u: "", c: num(l.c) } : { mode: "du", d: l.d ? num(l.d) : "", u: l.u ? num(l.u) : "", c: "" };
}
// One box as typed: null when blank, "sep" for a thousands separator ("1,000" — never read as 1), else the number (a decimal comma
// is a decimal point: «2,5»).
const SEP_RE = /^\d{1,3}(,\d{3})+$/;
const parseBox = s => { s = String(s).trim(); return s === "" ? null : SEP_RE.test(s) ? "sep" : +s.replace(",", "."); };
const badBox = v => v !== null && (v === "sep" || !okRate(v));
export function limFromDraft(dr) {
  const range = () => ({ err: T("A speed limit must be between 1 and {v1} Mbit/s", { v1: LIMITS_MAX_MBIT }) });
  const sep = (...vs) => vs.includes("sep") ? { err: T("Write a limit without a thousands separator: 1000, or 1.5 for a fraction.") } : null;
  if (dr.mode === "c") {
    const c = parseBox(dr.c);
    if (c === null || badBox(c)) return sep(c) || range();
    return { lim: { c } };
  }
  if (dr.mode === "du") {
    const d = parseBox(dr.d), u = parseBox(dr.u);
    if (badBox(d) || badBox(u)) return sep(d, u) || range();
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
// level: user | group | device | deployment. fallback: what applies without one of its own (fallbackFor), gaps: () => limitGaps(…).
export function LimitField({ draft, onChange, level, fallback, gaps, err }) {
  const set = p => onChange({ ...draft, ...p });
  const seg = (m, label) => html`<button type="button" role="radio" aria-checked=${draft.mode === m} class=${"seg" + (draft.mode === m ? " on" : "")}
    onClick=${() => set({ mode: m })}>${label}</button>`;
  const box = (k, label) => html`<label class="limin"><span class="limin-k">${label}</span>
    <input type="text" inputmode="decimal" value=${draft[k]} placeholder=${k === "c" ? "" : T("no limit")} aria-label=${label}
      class=${err && badBox(parseBox(draft[k])) ? "bad" : ""}
      onInput=${e => set({ [k]: e.target.value })}/><span class="limin-u">${T("Mbit/s")}</span></label>`;
  const own = draft.mode !== "none";
  // data-tracked (ui.js Sheet): every sheet this field sits in hands its Sheet `lim.changed` in the dirtyRef — keep it so
  return html`<div class="field limfield" data-tracked>
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

// A field's state: the draft, whether the operator changed it from what the editor opened on (never from a later poll's copy:
// another tab's change must not read as this sheet's, nor be sent back over it; a draft that does not parse counts as a change,
// so Save stays on and shows why), cur: the limit as drafted now (the stored one while the draft does not parse), and take():
// the limit to send — {} clears it — or null once the error is on screen.
export function useLimit(stored) {
  const [seed] = useState(() => limDraft(stored));
  const [draft, setDraft] = useState(seed);
  const [err, setErr] = useState("");
  const out = limFromDraft(draft);
  return { draft, err, changed: !!out.err || !limSame(out.lim, limFromDraft(seed).lim), cur: out.err ? limClean(stored) : out.lim,
           set: d => { setDraft(d); setErr(""); },
           take: () => { if (out.err) { setErr(out.err); return null; } return out.lim; } };
}

// A deployment's own limit (R7): a gauge on its row in Edit peer, lit when it has one, opening the sheet below. Staged like the gear's
// settings: the row's limit is sent with Edit peer's Save, through update-target — the only door a deployment limit has. `peer` is
// the device as Edit peer has it drafted (its limit, its owner), so the fallback line says what will apply after that Save.
export function LimitGauge({ peer, t, value, onApply }) {
  const own = limClean(value);
  return html`<button type="button" class=${"btn btn-mini ico topt-lim" + (own ? " on" : "")}
    title=${own ? T("Speed limit for this deployment: {lim}", { lim: limWords(own) }) : T("Speed limit for this deployment")}
    aria-label=${T("Speed limit for this deployment")}
    onClick=${e => { e.preventDefault(); e.stopPropagation(); pushModal(html`<${TargetLimitSheet} peer=${peer} t=${t} value=${value} onApply=${onApply}/>`); }}><${Ic} i="gauge"/></button>`;
}
function TargetLimitSheet({ peer, t, value, onApply }) {
  const lim = useLimit(value);
  const apply = () => { const l = lim.take(); if (l === null) return; onApply(l); closeModal(); };
  return html`<${Sheet} title=${T("Speed limit — {v1} on {v2}", { v1: t.iface, v2: Store.nodeName(t.node) })} width=${560} onBack=${closeModal}
    dirtyRef=${{ current: lim.changed }} foot=${footRow({ onCancel: closeModal, onAction: apply, action: T("Apply") })}>
    <${LimitField} draft=${lim.draft} onChange=${lim.set} err=${lim.err} level="deployment"
      fallback=${fallbackFor("deployment", t, peer)} gaps=${() => limitGaps([t])}/>
  <//>`;
}


// ── volume limits (docs/LIMITS-PLAN.md §3.5, limits-l4) ──────────────────────────────────────────────────────────────────────
// Stored {d, u} or {c} in BYTES with a period (d | w | m | n) and what happens at the end (cut | slow); edited in GB (10^9).
// Every level applies (a device's own, its user's, a group's one budget), so the field says what it counts and shows what is
// used so far — asked from /api/volume when the editor opens, never on the 5 s poll.
const GB = 1e9, VOL_MIN_GB = 0.1, VOL_MAX_GB = 1e6;
const okGb = v => typeof v === "number" && isFinite(v) && v >= VOL_MIN_GB && v <= VOL_MAX_GB;
export function volClean(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const amt = ["d", "u", "c"].filter(k => k in raw);
  if (!amt.length || ("c" in raw && amt.length > 1) || Object.keys(raw).some(k => !["d", "u", "c", "period", "at"].includes(k))) return null;
  if (!["d", "w", "m", "n"].includes(raw.period) || !["cut", "slow", undefined].includes(raw.at)) return null;
  return amt.every(k => typeof raw[k] === "number" && raw[k] >= VOL_MIN_GB * GB && raw[k] <= VOL_MAX_GB * GB) ? raw : null;
}
const volCanon = v => { v = volClean(v); return !v ? "" : ["d", "u", "c"].filter(k => k in v).map(k => k + v[k]).join("") + v.period + (v.at || "cut"); };
export const volSame = (a, b) => volCanon(a) === volCanon(b);
const gbNum = b => String(+(b / GB).toFixed(3));
export function volDraft(v) {
  v = volClean(v);
  const base = { d: "", u: "", c: "", period: "m", at: "cut" };
  return !v ? { mode: "none", ...base } : { mode: "c" in v ? "c" : "du", ...base, ...Object.fromEntries(["d", "u", "c"].filter(k => k in v).map(k => [k, gbNum(v[k])])),
    period: v.period, at: v.at || "cut" };
}
export function volFromDraft(dr) {
  if (dr.mode === "none") return { vol: {} };
  const range = () => ({ err: T("A volume limit must be between {v1} and {v2} GB", { v1: "0.1", v2: "1000000" }) });
  const keys = dr.mode === "c" ? ["c"] : ["d", "u"], out = {};
  for (const k of keys) {
    const v = parseBox(dr[k]);
    if (v === null) continue;
    if (v === "sep") return { err: T("Write a limit without a thousands separator: 1000, or 1.5 for a fraction.") };
    if (!okGb(v)) return range();
    out[k] = Math.round(v * GB);
  }
  if (!Object.keys(out).length) return dr.mode === "c" ? range() : { err: T("Enter a download or an upload limit, or choose No limit.") };
  return { vol: { ...out, period: dr.period, at: dr.at } };
}
export function useVolume(stored) {
  const [seed] = useState(() => volDraft(stored));
  const [draft, setDraft] = useState(seed);
  const [err, setErr] = useState("");
  const out = volFromDraft(draft);
  return { draft, err, changed: !!out.err || !volSame(out.vol, volFromDraft(seed).vol),
           set: d => { setDraft(d); setErr(""); },
           take: () => { if (out.err) { setErr(out.err); return null; } return out.vol; } };
}
const PERIOD = { d: () => T("vol|today"), w: () => T("vol|this week"), m: () => T("vol|this month"), n: () => T("vol|in total") };
export const gbText = b => T("{v1} GB", { v1: String(+(b / GB).toFixed(b >= 10 * GB ? 1 : 2)) });
// What is used in `period`, read from the ledger when asked: {used: {d, u}, period, day, state, vol?} — or {off} when the ledger
// is off. Asked for the period being drafted, so the figure is there BEFORE a limit is saved (a limit set mid-period counts what
// is already used, §3.5); cut off / slowed only for the stored limit's own period.
function useVolUse(kind, id, period) {
  const [u, setU] = useState(null);
  useEffect(() => {
    if (!id || !period) return;
    let live = true;
    api.get("/api/volume?kind=" + kind + "&id=" + encodeURIComponent(id) + "&period=" + period)
      .then(r => { if (live && r && r.ok) setU(r.data || {}); }).catch(() => {});
    return () => { live = false; };
  }, [kind, id, period]);
  return u && u.period && u.period !== period ? null : u;
}
// A reset day, YYYYMMDD in the panel's time zone, as that date wherever the browser is.
const dayText = d => new Date(Date.UTC(Math.floor(d / 10000), Math.floor(d / 100) % 100 - 1, d % 100))
  .toLocaleDateString(locale(), { month: "short", day: "numeric", timeZone: "UTC" }).replace(/\.$/, "");
function UsedLine({ kind, id, draft }) {
  const u = useVolUse(kind, id, draft.period);
  if (!u) return null;
  if (u.off) return html`<div class="notice warn"><${Ic} i="warn"/><span>${T("The traffic history is off on this panel, so no volume limit is enforced.")}</span></div>`;
  if (!u.used) return null;
  const both = draft.mode === "c", words = [T("download {v1}", { v1: gbText(u.used.d) }), T("upload {v1}", { v1: gbText(u.used.u) })].join(", ");
  return html`<div class=${"hint volused" + (u.state ? " at" : "")}><${Ic} i="gauge"/> ${T("Used {when}: {used}.", { when: PERIOD[u.period] ? PERIOD[u.period]() : "", used: both ? T("{v1} together", { v1: gbText(u.used.d + u.used.u) }) + " (" + words + ")" : words })}${
    u.state === "cut" ? " " + T("Cut off now.") : u.state === "slow" ? " " + T("Slowed to 1 Mbit/s now.") : ""}${
    u.day ? " " + T("Resets {v1}.", { v1: dayText(u.day) }) : ""}</div>`;
}
const VHINTS = {
  user: () => T("Counts all of this person's devices together, on every server."),
  group: () => T("One budget for everyone in the group together, on every server. A person's own limit and their devices' count too: whichever runs out first applies."),
  device: () => T("This device on every server together. Its person's and group's limits count too."),
};
// kind/id: the record the used line is asked for (none for a group not created yet).
export function VolumeField({ draft, onChange, level, err, kind, id }) {
  const set = p => onChange({ ...draft, ...p });
  const pill = (key, m, label) => html`<button type="button" role="radio" aria-checked=${draft[key] === m} class=${"seg" + (draft[key] === m ? " on" : "")}
    onClick=${() => set({ [key]: m })}>${label}</button>`;
  const box = (k, label) => html`<label class="limin"><span class="limin-k">${label}</span>
    <input type="text" inputmode="decimal" value=${draft[k]} placeholder=${k === "c" ? "" : T("no limit")} aria-label=${label}
      class=${err && badGb(parseBox(draft[k])) ? "bad" : ""} onInput=${e => set({ [k]: e.target.value })}/><span class="limin-u">${T("GB")}</span></label>`;
  const own = draft.mode !== "none";
  return html`<div class="field limfield volfield" data-tracked>
    <label>${T("Volume limit")}</label>
    <div class="segrow" role="radiogroup" aria-label=${T("Volume limit")}>
      ${pill("mode", "none", T("No limit"))}${pill("mode", "du", T("Download / upload"))}${pill("mode", "c", T("Combined"))}
    </div>
    ${own ? html`
      <div class="limrow">${draft.mode === "du" ? html`${box("d", T("lim|Download"))}${box("u", T("lim|Upload"))}` : box("c", T("Both ways together"))}</div>
      <div class="volopts">
        <span class="limin-k">${T("vol|Period")}</span>
        <div class="segrow" role="radiogroup" aria-label=${T("vol|Period")}>${pill("period", "d", T("vol|Day"))}${pill("period", "w", T("vol|Week"))}${pill("period", "m", T("vol|Month"))}${pill("period", "n", T("vol|Total"))}</div>
        <span class="limin-k">${T("At the limit")}</span>
        <div class="segrow" role="radiogroup" aria-label=${T("At the limit")}>${pill("at", "cut", T("Cut off"))}${pill("at", "slow", T("Slow to 1 Mbit/s"))}</div>
      </div>` : null}
    ${err ? html`<div class="hint err">${err}</div>` : null}
    <div class="hint">${VHINTS[level]()}${own ? " " + (draft.period === "n" ? T("Total never resets.") : T("A week starts on Monday; days follow the panel's time zone.")) : ""}</div>
    ${id && own ? html`<${UsedLine} kind=${kind} id=${id} draft=${draft}/>` : null}
  </div>`;
}
const badGb = v => v !== null && (v === "sep" || !okGb(v));
