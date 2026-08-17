/* screen-overview.js — the dashboard: fleet cards, the traffic flow map, the doughnuts and Protection.
 *
 * LAYER 11 (see docs/APP-JS-SPLIT-PLAN.md). A screen — only the router table references it.
 *
 * Nearly everything here is a READING of state the panel already has: the doughnuts, the flow map and the
 * ranked bars all re-derive from Store snapshots plus the history rings. recordDashTick is the exception,
 * and the reason store.js calls back into this module — the live trend series is accumulated in the
 * browser, one sample per poll, and exists nowhere else.
 */

import {
  ago, dur, fmtBytes, isWdttIface, isCsqttIface, rate, seen,
} from "./util.js";
import { T, Trich, plural, pluralWord, srvVerb, srvDetail } from "./i18n.js";
import {
  Store, api, bus, useStore,
} from "./store.js";
import {
  turnColor, turnFork, turnForkList, forkLabel,
} from "./turn-catalog.js";
import {
  targetType,
} from "./model.js";
import {
  Badge, Popover, STATUS_RANK, Sheet, StoreOffBanner, closeModal, dlul, ifaceColor, modalDepth, openModal,
  rateCell, secTitle, xferCell,
  Ic,
} from "./ui.js";
import {
  MultiRing, OnlineBlocks, RANGE_CAP, RankBars, RingLegend, ThroughputChart, TrendSpark,
} from "./charts.js";
import {
  DASH_RANGES, OnlineUsersTag, SVC_KINDWORD, dashNodes, dashSave, dashState, openLiveTab, rangeLabel, rangeWord, recentActivity,
  revealOrphans, revealPeer, revealPeersFiltered, revealUser, serviceIssues, svcKey, svcSaveSilence,
  svcSilence, svcSilencedSet,
} from "./views.js";
import {
  CAT_UNCAT_COLOR, catLabelOf, dashRankColor, fmtCount, isBlockCat,
} from "./routing.js";
import {
  enabledTurnForks, turnEnabled,
} from "./turn.js";
import {
  openNodeCreate,
} from "./sheets-crud.js";
import {
  NodesRailPanel,
} from "./grids.js";
import {
  NodeHealth, healthAlerts, updateHost,
} from "./screen-nodes.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// `traffic` = this node's client (non-mesh) rx/tx for the SELECTED range — a live rate, or windowed volume
// when `ranged`. Computed once in Overview (nodeTraffic) so the card agrees with the doughnuts/top-nodes.
export function FleetNodeCard({ n, traffic, ranged, histRange, nodeHist, presence }) {
  const live = Store.recon.nodeStatus[n.id] === "live";
  const snap = Store.stats[n.id];
  const nrec = (Store.nodes || []).find(x => x.id === n.id) || {};   // health lives on the node-store record
  const health = nrec.health || null;
  const tr = traffic || { rx: 0, tx: 0 };
  const trafCell = ranged ? xferCell(...dlul(tr.rx, tr.tx)) : rateCell(tr.rx, tr.tx);
  let sync = T("no data"); if (snap && snap.generated_at) { const a = Math.floor(Date.now() / 1000 - snap.generated_at); sync = live ? T("{v1} ago", { v1: seen(a) }) : T("stale · {v1}", { v1: seen(a) }); }
  const al = healthAlerts(health);
  // client interface-type badges — one per type present, "awg" / "awg ×5" (mesh/system ifaces excluded)
  const ifs = Store.describe[n.id] || {}; let wg = 0, awg = 0;
  for (const ifn in ifs) { const m = ifs[ifn]; if (!m || m.system) continue; if (m.awg_params && Object.keys(m.awg_params).length) awg++; else wg++; }
  const wdtt = ((Store.stats[n.id] || {}).wdtt || []).filter(w => w && w.iface).length;   // WDTT interfaces (own their TUN; not in describe)
  const csqtt = ((Store.stats[n.id] || {}).csqtt || []).filter(c => c && c.iface).length;   // csqtt interfaces (own their raw TUN; not in describe)
  const ifBadges = []; if (awg) ifBadges.push(["awg", awg]); if (wg) ifBadges.push(["wg", wg]); if (wdtt) ifBadges.push(["wdtt", wdtt]); if (csqtt) ifBadges.push(["csqtt", csqtt]);
  return html`<a class=${"fnode " + (live ? "" : "stale")} href=${"#/node/" + encodeURIComponent(n.id)}>
    <div class="fnode-main">
      <div class="fnode-top"><span class="dot ${live ? "live" : "stale"}"></span><span class="fnode-name">${n.name}</span>${al.length ? html`<span class="halert hot"><${Ic} i="warn"/> ${al.length}</span>` : ""}<span class="grow"></span>${ifBadges.length ? html`<div class="fnode-ifs">${ifBadges.map(([t, c]) => html`<span key=${t} class=${"iftype " + t}>${t}${c > 1 ? " ×" + c : ""}</span>`)}</div>` : null}<span class="rowarrow"><${Ic} i="arrow"/></span></div>
      <div class="fnode-stats">
        <div><span class="fl">${T("Throughput")}</span>${trafCell}</div>
        <div><span class="fl">${T("status|Online")}</span><span class="fv"><${OnlineUsersTag} nodeId=${n.id} presence=${presence} rangeLabel=${histRange} trigger=${(c, w) => html`<span class="faint">${plural(c, w || "user")}</span>`}/></span></div>
        <div><span class="fl">${T("Sync")}</span><span class="fv">${sync}</span></div>
      </div>
    </div>
    <div class="fnode-health">
      ${health ? html`<${NodeHealth} health=${health} node=${n.id} compact=${true} range=${histRange} nodeHist=${nodeHist}/>` : html`<div class="fnode-nohealth">${live ? T("no health data reported") : T("node offline")}</div>`}
    </div>
  </a>`;
}

// "3 WireGuard and 2 AmneziaWG interfaces" — the interface breakdown for a grouped-unassigned row.
export function ifCountPhrase(g) {
  const parts = [];
  if (g.wg.size) parts.push(T("{v1} WireGuard", { v1: g.wg.size }));
  if (g.awg.size) parts.push(T("{v1} AmneziaWG", { v1: g.awg.size }));
  if (g.wdtt && g.wdtt.size) parts.push(T("{v1} WDTT", { v1: g.wdtt.size }));
  if (g.csqtt && g.csqtt.size) parts.push(T("{v1} CSQTT", { v1: g.csqtt.size }));
  const tot = g.wg.size + g.awg.size + (g.wdtt ? g.wdtt.size : 0) + (g.csqtt ? g.csqtt.size : 0);
  return T("{v1} {v2}", { v1: parts.join(" and ") || "0", v2: pluralWord(tot, "interface") });
}
export function ifTypeLabel(node, iface) {
  const m = Store.ifaceMeta && Store.ifaceMeta(node, iface);
  return (m && Object.keys(m.awg_params || {}).length) ? "AmneziaWG" : "WireGuard";
}
// Deep-link target for a Settings activity row (the first changed section id, applied on the settings screen).


export const RANGE_ICON = { hour: "hour2", day: "daycal", week: "weekcal", month: "monthcal" };   // side-rail renders range as icons (live = glowing dot)
// side-rail section jump-nav: [label, section-title h2 substring to scroll to, icon]
/* The dashboard rail. The middle field is the section's ANCHOR (secTitle's data-sec), never its heading text:
   the headings are translated and a text match would quietly stop finding them. "a|b" = first present wins. */
export const DASH_NAV = [["Fleet", "fleet", "server"], ["Distribution", "distribution", "donut"],   // i18n-keys
  ["Traffic flow", "flow", "flow"], ["Top charts", "protection|topnodes", "bars"], ["Activity log", "activity", "excl"]];   // i18n-keys
export const dashNavLabel = k => ({ "Fleet": T("nav|Fleet"), "Distribution": T("nav|Distribution"), "Traffic flow": T("nav|Traffic flow"),   // i18n-keys
  "Top charts": T("nav|Top charts"), "Activity log": T("nav|Activity log") }[k] || k);   // i18n-keys
// ── Peers/Mesh traffic filter ──────────────────────────────────────────────────────────────────────────────
// Every traffic figure has the raw total (rx,tx) and its mesh portion (mrx,mtx) in hand. The badges decide which
// components survive: peers = client (total−mesh), mesh = the relay portion. Either, both, or neither (→ 0).
export function trafPick(rx, tx, mrx, mtx, f) {
  const crx = Math.max(0, (rx || 0) - (mrx || 0)), ctx = Math.max(0, (tx || 0) - (mtx || 0));
  return { rx: (f.peers ? crx : 0) + (f.mesh ? (mrx || 0) : 0),
           tx: (f.peers ? ctx : 0) + (f.mesh ? (mtx || 0) : 0) };
}
// Effective flags for a widget: its per-widget override pins a pill, otherwise the pill inherits the global badge.
export function trafFlags(key) {
  const ov = key && dashState.ov ? dashState.ov[key] : null;
  return { peers: ov && ov.peers != null ? ov.peers : dashState.peers,
           mesh:  ov && ov.mesh  != null ? ov.mesh  : dashState.mesh };
}
// Flip one widget's own Peers/Mesh override (pinned in dashState.ov[key]) without touching the others — each traffic
// doughnut drives its filter independently. Never leave BOTH off: turning off the only-selected one flips to the other.
export function dashToggleTrafKey(key, which) {
  const cur = trafFlags(key), other = which === "peers" ? "mesh" : "peers";
  const next = { peers: cur.peers, mesh: cur.mesh };
  if (next[which] && !next[other]) { next[which] = false; next[other] = true; }
  else next[which] = !next[which];
  dashState.ov = dashState.ov || {}; dashState.ov[key] = next;
  dashSave(); bus.emit();
}
/* "of ↓12 GB and ↑3 GB total" — two STYLED numbers in one sentence, so it is one key with two markers,
   split around them. Three T() fragments glued with `+` would fix English word order into every language. */
function ofTotal(dn, up) {
  const one = T("of {dn} and {up} total");
  const [a, r1] = [one.split("{dn}")[0], one.split("{dn}").slice(1).join("{dn}")];
  const [b, c] = [r1.split("{up}")[0], r1.split("{up}").slice(1).join("{up}")];
  return html`<${Fragment}>${a}<span style="color:var(--online)">↓${dn}</span>${b}<span style="color:var(--rate-up)">↑${up}</span>${c}<//>`;
}

export function dashSetRange(r) { if (DASH_RANGES.some(x => x[0] === r)) { dashState.range = r; dashSave(); bus.emit(); } }

// Merge the SELECTED nodes' 15s health-ring series (server-provided, bucket-aligned) into one fleet
// series summed per timestamp — powers the live fleet-throughput hero without a client accumulator, and
// survives a reload (the ring is on the panel). Only rx/tx are summed (counts aren't in the ring yet).
export function mergeFleetSeries(selIds) {
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
export const DASH_TICK_MAX = 180;
export const dashLive = { t: [], on: {} };
export function recordDashTick() {
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
export function dashOnlineTrend(selIds) {
  const t = dashLive.t; if (t.length < 2) return null;
  return { t, pts: t.map((_, i) => selIds.reduce((a, id) => a + ((dashLive.on[id] || [])[i] || 0), 0)) };
}
// Fleet-summed history for the hero charts over the SELECTED range. Live → the 15s ring (rx/tx, mesh netted
// out) + the client online accumulator; a range → Σ per-node RRD (rx−mesh, tx−mesh, pon) aligned by bucket
// timestamp. Returns { t, rx, tx, on } — everything the fleet-throughput + online-peers charts need.
export function fleetHistory(selIds, range, hist) {
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
export const ONLINE_BLOCKS = { live: [30, 30], hour: [30, 120], day: [24, 3600], week: [28, 21600], month: [30, 86400] };
// Resample an irregular (t[], v[]) series into `n` right-anchored blocks of `step` seconds — each block = the
// PEAK (max) of the samples in its window (null when empty, so the chart can show a gap). This charts a COUNT of
// online peers: a MEAN renders integer counts as misleading fractions ("0.05 peers" when one peer was online for
// one sample of the window); the peak stays a whole number and still surfaces that brief activity.
export function resampleBlocks(t, v, n, step) {
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

export function DashRail() {
  const fleet = Store.fleet || [];
  const range = dashState.range;
  // find a section by its ANCHOR (data-sec); `find` may be "a|b" alternatives (first present wins — e.g. protection, else topnodes)
  const findSection = find => { for (const a of String(find).split("|")) { const el = document.querySelector('.section-title[data-sec="' + a + '"]'); if (el) return el; } return null; };
  const jump = find => { const s = findSection(find); if (s) s.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const menuIc = ic => /^[a-z0-9_-]+$/.test(ic) ? html`<${Ic} i=${ic}/>` : html`<span class="railmenu-emoji">${ic}</span>`;   // registry key → svg icon · anything else (emoji) → text
  // scroll-spy: highlight the jump icon of the section currently in view (first one at the top, one at a time as you scroll)
  const [active, setActive] = useState(0);
  useEffect(() => {
    let raf = 0;
    const compute = () => { raf = 0;
      let idx = 0;
      DASH_NAV.forEach(([label, find], i) => { const el = findSection(find);   // supports "A|B" fallback (Protection, else Top nodes)
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
        ${DASH_NAV.map(([label, find, ic], i) => html`<button key=${label} class=${"railmenu-b" + (i === active ? " on" : "")} onClick=${() => jump(find)} title=${dashNavLabel(label)}>
          <span class="railmenu-ic">${menuIc(ic)}</span><span class="railmenu-t">${dashNavLabel(label)}</span></button>`)}
      </div>
      <div class="railpanel railmenu">
        ${DASH_RANGES.map(([k]) => html`<button key=${k} class=${"railmenu-b" + (range === k ? " on" : "")} onClick=${() => dashSetRange(k)} title=${rangeLabel(k)}>
          <span class="railmenu-ic">${k === "live" ? html`<span class="rlive-dot"></span>` : html`<${Ic} i=${RANGE_ICON[k]}/>`}</span><span class="railmenu-t">${rangeLabel(k)}</span></button>`)}
      </div>
      ${fleet.length > 1 ? html`<${NodesRailPanel} nav=${false}/>` : null}
    </div>
  </div>`;
}

// On-demand history for the range-driven visuals. Fetches per-node RRD (/api/node-history) for the
// SELECTED nodes only when the range is NOT "live" — off the 5s hot path, re-run only when the range or
// the selection changes. Returns { loading, byNode:{id:{t,rx,tx,cpu,…}}, range }. Live → empty (widgets
// read the /api/state bundle instead). One fetch burst per range change; results are held until it changes.
export const RANGE_STEP = { hour: 15, day: 300, week: 1800, month: 7200 };   // seconds/bucket → volume = Σ(mean B/s)·step
// One fetch burst per range/selection change, shared by the doughnuts AND the flow map (lifted to Overview so
// they don't each hit the API). Pulls per-node RRD + per-pair mesh means. Live → empty (widgets use the bundle).
export function useRangeHistory(range, selIds) {
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
export function DashDoughnuts({ selIds, range, hist }) {
  const sel = new Set(selIds);
  const fleet = (Store.fleet || []).filter(n => sel.has(n.id));
  const live = range === "live";
  const ranged = !live && hist.range === range;   // caller passes the EFFECTIVE (loaded) range, so this holds the old data through a fetch instead of flashing live
  const STEP = RANGE_STEP[range] || 1;
  const isSys = (nid, ifn) => !!(Store.describe[nid] && Store.describe[nid][ifn] && Store.describe[nid][ifn].system);
  const ifType = (nid, ifn) => {
    if (((Store.stats[nid] || {}).wdtt || []).some(w => w && w.iface === ifn)) return "wdtt";   // WDTT owns its iface (snap.wdtt, not describe)
    if (((Store.stats[nid] || {}).csqtt || []).some(c => c && c.iface === ifn)) return "csqtt";   // csqtt owns its raw-TUN iface (snap.csqtt, not describe)
    const m = Store.describe[nid] && Store.describe[nid][ifn]; return (m && m.awg_params && Object.keys(m.awg_params).length) ? "awg" : "wg"; };
  const sPeers = Store.recon.peers.filter(p => p.targets.some(t => sel.has(t.node)));
  const _sum = a => (a || []).reduce((x, v) => x + (v || 0), 0);
  // per-node history-derived aggregates (client volume, awg volume, mean peer counts)
  const clientVol = d => { let rx = 0, tx = 0; const R = (d && d.rx) || [], T = (d && d.tx) || [], MR = (d && d.mrx) || [], MT = (d && d.mtx) || [];
    for (let i = 0; i < R.length; i++) { rx += Math.max(0, (R[i] || 0) - (MR[i] || 0)); tx += Math.max(0, (T[i] || 0) - (MT[i] || 0)); } return { rx: rx * STEP, tx: tx * STEP }; };
  const awgVol = d => ({ rx: _sum(d && d.arx) * STEP, tx: _sum(d && d.atx) * STEP });
  const meshVol = d => ({ rx: _sum(d && d.mrx) * STEP, tx: _sum(d && d.mtx) * STEP });

  // ── traffic by node + by iface type. Each doughnut owns an INDEPENDENT Peers/Mesh filter (FN = by node,
  //    FT = by interface): accumulate the raw client/mesh components once, then apply each filter at the end. ──
  const FN = trafFlags("dnode"), FT = trafFlags("dtype");
  const nodeRaw = {};   // per node: client (crx/ctx) and mesh (mrx/mtx) kept apart so either filter can pick them
  const typeRaw = { wg: { rx: 0, tx: 0 }, awg: { rx: 0, tx: 0 }, wdtt: { rx: 0, tx: 0 }, csqtt: { rx: 0, tx: 0 }, mesh: { rx: 0, tx: 0 } };
  const addType = (k, rx, tx) => { (typeRaw[k] = typeRaw[k] || { rx: 0, tx: 0 }).rx += rx; typeRaw[k].tx += tx; };
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
      if (snap) for (const w of (snap.wdtt || [])) {   // WDTT interfaces (own their TUN, report aggregate rx/tx) → client traffic, WDTT bucket
        const r = w.rx_speed || 0, t = w.tx_speed || 0; crx += r; ctx += t; addType("wdtt", r, t);
      }
      if (snap) for (const c of (snap.csqtt || [])) {   // csqtt interfaces (own raw TUN, aggregate rx/tx) → client traffic, csqtt bucket
        const r = c.rx_speed || 0, t = c.tx_speed || 0; crx += r; ctx += t; addType("csqtt", r, t);
      }
      addType("mesh", mrx, mtx);
      nodeRaw[n.id] = { crx, ctx, mrx, mtx };
    }
  });
  // apply each doughnut's own filter to the raw components
  const nodeTraf = {}; fleet.forEach(n => { const r = nodeRaw[n.id] || { crx: 0, ctx: 0, mrx: 0, mtx: 0 }; nodeTraf[n.id] = trafPick(r.crx + r.mrx, r.ctx + r.mtx, r.mrx, r.mtx, FN); });
  const typePick = k => k === "mesh" ? { rx: FT.mesh ? typeRaw.mesh.rx : 0, tx: FT.mesh ? typeRaw.mesh.tx : 0 }
                                     : { rx: FT.peers ? typeRaw[k].rx : 0, tx: FT.peers ? typeRaw[k].tx : 0 };
  const typeTraf = { wg: typePick("wg"), awg: typePick("awg"), wdtt: typePick("wdtt"), csqtt: typePick("csqtt"), mesh: typePick("mesh") };
  const trafFmt = ranged ? fmtBytes : rate;

  // ── peer deployments by node + by iface type. TOTAL = the roster count deployed to each node/iface (a real head-
  //    count, not a time-average). ONLINE = DISTINCT peers seen connected: live → online right now; a range → the
  //    distinct peers that were active at any point in the window (unioned from the per-peer RRD, so cycling peers
  //    all count once — not the peak or the mean). ──
  const nodeCnt = {}, typeCnt = { wg: { tot: 0, on: 0 }, awg: { tot: 0, on: 0 }, wdtt: { tot: 0, on: 0 }, csqtt: { tot: 0, on: 0 } };
  fleet.forEach(n => nodeCnt[n.id] = { tot: 0, on: 0 });
  // live interface is authoritative; the stored target.type is only a fallback for interfaces the node isn't reporting.
  // (WDTT targets classify as "wdtt" → counted in their own bucket, never miscounted under WireGuard.)
  const tyOf = targetType;
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
  const TYPES = [["awg", "AmneziaWG"], ["wg", "WireGuard"], ["wdtt", "WDTT"], ["csqtt", "CSQTT"], ["mesh", T("Mesh")]];   // the Mesh slice only fills when the Mesh badge is on
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
    return html`<div class="mrc-def"><span class="mrc-k">${T("val|total")}</span>
      <span class="mrc-tot dn" style=${"font-size:" + dfs + "px"}>${ds}</span><span class="mrc-tot up" style=${"font-size:" + ufs + "px"}>${us}</span></div>`;
  };
  const cntCenter = (on, tot) => html`<div class="mrc-def"><span class="mrc-k">${T("val|online")}</span>
    <span class="mrc-tot dn">${on}<small style="color:var(--faint)"> / ${tot}</small></span></div>`;

  const totDownN = sum(nodeTraf, "rx"), totUpN = sum(nodeTraf, "tx");
  const totDownT = typeTraf.wg.rx + typeTraf.awg.rx + typeTraf.wdtt.rx + typeTraf.csqtt.rx + typeTraf.mesh.rx, totUpT = typeTraf.wg.tx + typeTraf.awg.tx + typeTraf.wdtt.tx + typeTraf.csqtt.tx + typeTraf.mesh.tx;
  const nodeOn = Object.values(nodeCnt).reduce((a, v) => a + v.on, 0), nodeTot = Object.values(nodeCnt).reduce((a, v) => a + v.tot, 0);
  const typeOn = typeCnt.wg.on + typeCnt.awg.on + typeCnt.wdtt.on + typeCnt.csqtt.on, typeTot = typeCnt.wg.tot + typeCnt.awg.tot + typeCnt.wdtt.tot + typeCnt.csqtt.tot;

  // traffic legends carry down/up SEPARATELY (perspective-adjusted) so each is independently hoverable —
  // hovering the ↓ value isolates the Download arc, the ↑ value the Upload arc.
  const legDU = (rx, tx) => { const [d, u] = dlul(rx, tx); return { down: trafFmt(d), up: trafFmt(u) }; };
  const trafLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id),
    ...legDU((nodeTraf[n.id] || {}).rx || 0, (nodeTraf[n.id] || {}).tx || 0) }));
  // Keyed off what the fleet HAS, not what moved bytes — the same test the counts card beside it uses. Filtering
  // on traffic emptied the whole legend on an idle fleet, so the one card in the grid went blank while every other
  // ring still listed its entries at 0. `mesh` is not a deployment kind and never appears in typeCnt, so it stays
  // traffic-gated: it shows up exactly when the Mesh badge has put something in the ring.
  const trafLegTypes = TYPES.filter(([t]) => (typeCnt[t] || { tot: 0 }).tot > 0
      || ((typeTraf[t] || {}).rx || 0) + ((typeTraf[t] || {}).tx || 0) > 0).map(([t, nm]) => ({ key: t, name: nm, color: typeColor(t),
    ...legDU((typeTraf[t] || {}).rx || 0, (typeTraf[t] || {}).tx || 0) }));
  const cntLegNodes = fleet.map(n => ({ key: n.id, name: nodeName(n.id), color: nodeColor(n.id), right: nodeCnt[n.id].on + " / " + nodeCnt[n.id].tot }));
  const cntLegTypes = TYPES.filter(([t]) => (typeCnt[t] || { tot: 0 }).tot > 0).map(([t, nm]) => ({ key: t, name: nm, color: ifaceColor(t), right: typeCnt[t].on + " / " + typeCnt[t].tot }));

  const rlabel = DASH_RANGES.find(r => r[0] === range);
  const rname = rlabel ? rlabel[1].toLowerCase() : range;
  const loadingNote = (!live && hist.loading) ? html`<div class="donut-note">${T("loading {v1} history…", { v1: rname })}</div>` : null;
  const volNote = ranged ? html`<div class="donut-note">${T("volume over the {v1}", { v1: rname })}</div>` : null;
  const avgNote = ranged ? html`<div class="donut-note">${T("avg over the {v1}", { v1: rname })}</div>` : null;
  // traffic rings carry unitColor so the hovered centre readout tints the unit letter ↓ green / ↑ blue.
  // Under the peer perspective the ↓ (Download) ring is fed by tx and ↑ (Upload) by rx, so it agrees with
  // the centre total, the legend, and every other figure.
  const trafRings = (rxSegs, txSegs) => { const dnSegs = povPeers ? txSegs : rxSegs, upSegs = povPeers ? rxSegs : txSegs;
    return [{ label: T("traffic|Download"), dir: "dn", fmt: trafFmt, unitColor: "var(--online)", segments: dnSegs },
      { label: T("traffic|Upload"), dir: "up", fmt: trafFmt, unitColor: "var(--rate-up)", segments: upSegs }]; };

  // ── by TURN-PROXY FORK (the 3rd row). Aggregated BY FORK across the fleet (like "by interface type"), only for
  //    the forks enabled in Panel settings. Live = attribute each turn-routed peer (target.viaTurn) to its fork;
  //    ranged = the per-(node,fork) RRD (hist.turn). The fork's interface tags come from its live peers. Turn has
  //    no per-fork history until a node has been reporting, so on a range with no rows it falls back to live. ──
  const turnOn = turnEnabled();
  const enSet = new Set(turnOn ? enabledTurnForks().map(f => f.id) : []);
  const sanF = s => String(s).replace(/[^A-Za-z0-9_]/g, "_");
  const fLive = {};   // fork → { rx, tx, on, tot } aggregated across every node/instance of that fork
  if (turnOn) sPeers.forEach(p => p.targets.forEach(t => {
    if (!sel.has(t.node)) return;
    const isCS = t.type === "csqtt" || isCsqttIface(t.iface);
    const isSC = t.type === "wdtt" || isWdttIface(t.iface) || isCS;   // self-contained VK-turn servers (WDTT/csqtt) are ON the server (no viaTurn) → fork = the instance's fork
    let fk;
    if (isSC) { const kind = isCS ? "csqtt" : "wdtt"; const inst = ((Store.stats[t.node] || {})[kind] || []).find(x => x && x.iface === t.iface); fk = (inst && inst.fork) || (isCS ? "csqtt" : "amurcanov"); }
    else if (t.viaTurn) fk = turnFork(t.viaTurn);
    else return;
    if (!enSet.has(fk)) return;
    const a = fLive[fk] = fLive[fk] || { rx: 0, tx: 0, on: 0, tot: 0 };
    if (!isSC) { const o = t.observed; if (o) { a.rx += o.rx_speed || 0; a.tx += o.tx_speed || 0; } }   // self-contained per-peer speed n/a → the iface counter is added below
    a.tot++; if (t.online) a.on++;
  }));
  // Self-contained servers (WDTT + csqtt) report traffic per-interface (own TUN), not per-peer → add each instance's
  // aggregate rx/tx to its fork. tot/on already came from the roster targets above — DON'T re-add the passwords count
  // here (that double-counted every WDTT peer, inflating its deployment ring). A running server with traffic still
  // shows via the (rx+tx)>0 test; the roster provides tot for the idle case.
  if (turnOn) fleet.forEach(n => { if (!sel.has(n.id)) return;
    for (const w of ((Store.stats[n.id] || {}).wdtt || [])) { const fk = (w && w.fork) || "amurcanov"; if (!enSet.has(fk)) continue;
      const a = fLive[fk] = fLive[fk] || { rx: 0, tx: 0, on: 0, tot: 0 }; a.rx += w.rx_speed || 0; a.tx += w.tx_speed || 0; }
    for (const c of ((Store.stats[n.id] || {}).csqtt || [])) { const fk = (c && c.fork) || "csqtt"; if (!enSet.has(fk)) continue;
      const a = fLive[fk] = fLive[fk] || { rx: 0, tx: 0, on: 0, tot: 0 }; a.rx += c.rx_speed || 0; a.tx += c.tx_speed || 0; } });
  const fRanged = {};   // sanitised fork → { rx, tx, pon, ptot } summed over selected nodes
  if (ranged) (hist.turn || []).forEach(e => { if (!sel.has(e.node)) return;
    const a = fRanged[e.fork] = fRanged[e.fork] || { rx: 0, tx: 0, pon: 0, ptot: 0 };
    a.rx += e.rx || 0; a.tx += e.tx || 0; a.pon += e.pon || 0; a.ptot += e.ptot || 0; });
  const turnRanged = ranged && Object.keys(fRanged).length > 0;   // ranged turn data present → use it; else live
  const _selfFork = fk => { const k = (((typeof turnForkList === "function" && turnForkList().find(f => f.id === fk)) || {}).kind); return k === "wdtt" || k === "csqtt"; };   // self-contained forks (WDTT/csqtt) have NO per-fork turn RRD yet → always show their live traffic/counts, even on a range (else they vanish)
  const fTraf = fk => (turnRanged && !_selfFork(fk)) ? (fRanged[sanF(fk)] || { rx: 0, tx: 0 }) : (fLive[fk] || { rx: 0, tx: 0 });
  // On a range, BOTH numbers come from the per-fork RRD so they stay consistent: on = distinct deployments online
  // during the window (`pon`), tot = distinct deployments seen during the window (`ptot`). Pairing a windowed `pon`
  // against a LIVE-instant tot was the bug that showed 7 / 2 (7 seen over the window, 2 connected right now).
  // Self-contained forks have no turn RRD → live counts for them (roster tot, live on).
  const fCnt = fk => (turnRanged && !_selfFork(fk))
    ? { on: Math.round((fRanged[sanF(fk)] || {}).pon || 0), tot: Math.round((fRanged[sanF(fk)] || {}).ptot || 0) }
    : { on: (fLive[fk] || {}).on || 0, tot: (fLive[fk] || {}).tot || 0 };
  const forks = [...enSet].filter(fk => { const t = fTraf(fk), c = fCnt(fk); return (t.rx + t.tx) > 0 || c.tot > 0; });
  const turnFmt = turnRanged ? fmtBytes : rate;
  const turnCenter = (rx, tx) => { const [d, u] = dlul(rx, tx); const ds = "↓ " + turnFmt(d), us = "↑ " + turnFmt(u);
    const dfs = fitFs(Math.max(ds.length, us.length)), ufs = Math.max(11, dfs - 3);
    return html`<div class="mrc-def"><span class="mrc-k">${T("val|total")}</span>
      <span class="mrc-tot dn" style=${"font-size:" + dfs + "px"}>${ds}</span><span class="mrc-tot up" style=${"font-size:" + ufs + "px"}>${us}</span></div>`; };
  const turnTrafRings = () => { const rxS = forks.map(fk => ({ key: fk, name: forkLabel(fk), value: fTraf(fk).rx, color: turnColor(fk) })),
      txS = forks.map(fk => ({ key: fk, name: forkLabel(fk), value: fTraf(fk).tx, color: turnColor(fk) }));
    const dn = povPeers ? txS : rxS, up = povPeers ? rxS : txS;
    return [{ label: T("traffic|Download"), dir: "dn", fmt: turnFmt, unitColor: "var(--online)", segments: dn }, { label: T("traffic|Upload"), dir: "up", fmt: turnFmt, unitColor: "var(--rate-up)", segments: up }]; };
  const turnCntRings = () => [
    { label: T("Deployments"), fmt: v => v, segments: forks.map(fk => ({ key: fk, name: forkLabel(fk), value: fCnt(fk).tot, color: turnColor(fk) })) },
    { label: T("Online"), fmt: v => v, segments: forks.map(fk => ({ key: fk, name: forkLabel(fk), value: fCnt(fk).on, color: turnColor(fk) })) }];
  const turnTrafLeg = forks.map(fk => ({ key: fk, name: forkLabel(fk), color: turnColor(fk), ...(() => { const t = fTraf(fk), [d, u] = dlul(t.rx, t.tx); return { down: turnFmt(d), up: turnFmt(u) }; })() }));
  const turnCntLeg = forks.map(fk => { const c = fCnt(fk); return { key: fk, name: forkLabel(fk), color: turnColor(fk), right: c.on + " / " + c.tot }; });
  const turnTot = forks.reduce((s, fk) => { const t = fTraf(fk), c = fCnt(fk); s.rx += t.rx; s.tx += t.tx; s.on += c.on; s.tot += c.tot; return s; }, { rx: 0, tx: 0, on: 0, tot: 0 });
  const turnLiveNote = html`<div class="donut-note">${T("live rates")}${ranged ? T(" · no history yet for this range") : ""}</div>`;
  const turnNote = turnRanged ? volNote : turnLiveNote;       // traffic card → volume
  const turnAvgNote = turnRanged ? avgNote : turnLiveNote;    // peers card → avg

  const loading = !live && hist.loading;
  // Each traffic doughnut gets its OWN Peers/Mesh toggle (its own override key) so they operate independently.
  const trafBadgesFor = (key, F) => html`<div class="dcard-traf">
    <button class=${"tbadge peers" + (F.peers ? " on" : "")} onClick=${() => dashToggleTrafKey(key, "peers")} title=${F.peers ? T("Hide client (peer) traffic") : T("Show client (peer) traffic")}>${T("Peers")}</button>
    <button class=${"tbadge mesh" + (F.mesh ? " on" : "")} onClick=${() => dashToggleTrafKey(key, "mesh")} title=${F.mesh ? T("Hide mesh (node-to-node relay) traffic") : T("Show mesh (node-to-node relay) traffic")}>${T("Mesh")}</button>
  </div>`;
  // Grid rows group BY DIMENSION: row 1 = the two "by node" rings, row 2 = the two "by interface" rings.
  return html`<div class="donutgrid">
    <${DoughCard} title=${T("Traffic by node")} badges=${trafBadgesFor("dnode", FN)} loading=${loading}
      rings=${trafRings(segNodes("rx"), segNodes("tx"))} center=${trafCenter(totDownN, totUpN)} legend=${trafLegNodes} note=${loadingNote || volNote}/>

    <${DoughCard} title=${T("Deployments by node")} loading=${loading}
      rings=${[{ label: T("Deployments"), fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].tot, color: nodeColor(n.id) })) },
               { label: T("Online"), fmt: v => v, segments: fleet.map(n => ({ key: n.id, name: nodeName(n.id), value: nodeCnt[n.id].on, color: nodeColor(n.id) })) }]}
      center=${cntCenter(nodeOn, nodeTot)} legend=${cntLegNodes} note=${loadingNote || avgNote}/>

    <${DoughCard} title=${T("Traffic by interface")} badges=${trafBadgesFor("dtype", FT)} loading=${loading}
      rings=${trafRings(segTypes("rx"), segTypes("tx"))} center=${trafCenter(totDownT, totUpT)} legend=${trafLegTypes} note=${loadingNote || volNote}/>

    <${DoughCard} title=${T("Deployments by interface")} loading=${loading}
      rings=${[{ label: T("Deployments"), fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).tot || 0, color: ifaceColor(t) })) },
               { label: T("Online"), fmt: v => v, segments: TYPES.map(([t, nm]) => ({ key: t, name: nm, value: (typeCnt[t] || {}).on || 0, color: ifaceColor(t) })) }]}
      center=${cntCenter(typeOn, typeTot)} legend=${cntLegTypes} note=${loadingNote || avgNote}/>

    ${turnOn && forks.length ? html`<${Fragment}>
      <${DoughCard} title=${T("Traffic by turn-proxy")} loading=${loading}
        rings=${turnTrafRings()} center=${turnCenter(turnTot.rx, turnTot.tx)} legend=${turnTrafLeg} note=${loadingNote || turnNote}/>

      <${DoughCard} title=${T("Deployments by turn-proxy")} loading=${loading}
        rings=${turnCntRings()} center=${cntCenter(turnTot.on, turnTot.tot)} legend=${turnCntLeg} note=${loadingNote || turnAvgNote}/>
    <//>` : null}
  </div>`;
}

// One distribution card = a doughnut + its legend sharing a hovered {key, dir} target, so hovering ONE ring
// arc (or one ↓/↑ value) isolates exactly that arc and that value — its partner arc/value dims too. Hovering
// the NAME (dir:null) lights both arcs and shows that entity's own numbers in the centre. Fully bidirectional
// between ring and legend. Hover-only state — no poll-path cost, cheap Preact re-renders (no SVG rebuild).
export function DoughCard({ title, rings, center, legend, note, loading, badges }) {
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
export const FLOW_EG = "#2E90FF", FLOW_IN = "#22D07A", FLOW_GLOBE = "#12BECE", FLOW_MESH = "#9B8AFF";   // egress blue · ingress green · internet cyan-teal (distinct from egress blue) · off-fleet mesh violet
export function flowGraph(selIds, range, hist) {
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
    // hist.turn keys forks SANITISED (WINGS-N → WINGS_N in the RRD filename); reverse-map to the real catalog id so
    // the satellite gets the right colour + label (turnColor/turnFork key on the real id — "WINGS_N" misses → grey).
    const _sanF = s => String(s).replace(/[^A-Za-z0-9_]/g, "_");
    const _realFork = {}; ((typeof turnForkList === "function" ? turnForkList() : []) || []).forEach(f => { _realFork[_sanF(f.id)] = f.id; });
    (hist.turn || []).forEach(e => { const a = acc[e.node]; if (!a) return; const rx = e.rx || 0, tx = e.tx || 0; if (!rx && !tx) return;
      const fk = _realFork[e.fork] || e.fork;
      (a.turn[fk] = a.turn[fk] || { rx: 0, tx: 0 }); a.turn[fk].rx += rx; a.turn[fk].tx += tx;
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
      for (const w of (snap.wdtt || [])) { if (!w) continue; const fk = w.fork || "amurcanov"; const at = (acc[n.id].turn[fk] = acc[n.id].turn[fk] || { rx: 0, tx: 0 }); at.rx += w.rx_speed || 0; at.tx += w.tx_speed || 0; }   // WDTT = a turn-family fork → its OWN relay satellite (like other turn proxies), coloured by fork; feeds the internet lane via turnRx
      for (const c of (snap.csqtt || [])) { if (!c) continue; const fk = c.fork || "csqtt"; const at = (acc[n.id].turn[fk] = acc[n.id].turn[fk] || { rx: 0, tx: 0 }); at.rx += c.rx_speed || 0; at.tx += c.tx_speed || 0; }   // csqtt = a turn-family fork → its OWN relay satellite too
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
      const s = satId(n.id, "mesh"), oc = a.offmesh.n.size; sats.push({ id: s, node: n.id, kind: "mesh", label: T("Other {v1}", { v1: plural(oc, "node") }), color: FLOW_MESH, ic: "server" });
      if (a.offmesh.tx) flows.push({ from: n.id, to: s, bps: a.offmesh.tx }); if (a.offmesh.rx) flows.push({ from: s, to: n.id, bps: a.offmesh.rx });
    }
  });
  const inTot = {}, outTot = {};
  fleet.forEach(n => { inTot[n.id] = 0; outTot[n.id] = 0; });
  flows.forEach(f => { if (outTot[f.from] != null) outTot[f.from] += f.bps; if (inTot[f.to] != null) inTot[f.to] += f.bps; });
  return { fleet, sats, flows, inTot, outTot, ranged };
}
// Built on FIRST READ, never at import: modules load before loadLang() resolves, so a T() here would
// freeze in English whatever the catalog says (see --frozen).
let _flow_anims = null;
export const FLOW_ANIMS = () => (_flow_anims || (_flow_anims = [   // travelling-current styles for the flow lines (the ORIGINAL beautiful versions); "off" for anyone who wants no motion
  { id: "dots", ic: "dots", label: T("Dots") },
  { id: "chevrons", ic: "arrow", label: T("Arrows") },
  { id: "pulse", ic: "activity", label: T("Pulse") },
  { id: "gradient", ic: "waves", label: T("Flow") },
  { id: "off", ic: "off", label: T("Off") },
]));
export function FlowMap2({ selIds, range, hist }) {
  const [hov, setHov] = useState(null);
  const rankRef = useRef({ key: null, order: [] });   // frozen busyness ordering (see `ranked` below) — hook must sit above the early return
  const anim = (Store.panelSettings || {}).flow_anim || "off";   // HOST-WIDE setting — shared by every operator, persists across logins (default = OFF until an operator picks a style)
  const setAnim = m => { Store.panelSettings = { ...(Store.panelSettings || {}), flow_anim: m }; bus.emit(); api.panelSettings({ flow_anim: m }).catch(() => {}); };
  const G = flowGraph(selIds, range, hist);
  const { fleet, sats, flows, ranged } = G;
  const fmt = ranged ? fmtBytes : rate;                    // Live → speed (K/s…); a range → total bytes (KB, MB…)
  const N = fleet.length;
  if (!N) return html`<div class="allclear">${T("No nodes selected.")}</div>`;
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
  // FIXED frame aspect — the section must NEVER change height (its resizing scrolled the page out from under the
  // reader). The content is centred + scaled into a constant-aspect frame; sparse diagrams sit a touch looser, but the
  // card height is rock-stable across polls/range changes. (Was adaptive AR 1.4–1.75 → ~25% height swings → scroll jumps.)
  // aspect from FLEET SIZE (N), not content shape → STABLE per poll (N doesn't change every 5s, so no height jump) while
  // still giving denser fleets more vertical room: 2 nodes ≈ 1.7 (wide) … 12 nodes ≈ 1.25 (taller). Content scales to fit.
  const AR = Math.max(1.25, Math.min(1.7, 1.7 - Math.max(0, N - 2) * 0.05)), FRAME_W = 480;
  const cw = vx1 - vx0, ch = vy1 - vy0, ccx = (vx0 + vx1) / 2, ccy = (vy0 + vy1) / 2;
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
      else { const sm = sats.find(x => x.id === hov.id); if (sm) { const t = satTot[hov.id] || {}; hv = { type: "ep", name: sm.kind === "turn" ? sm.fork : sm.label || sm.kind, ib: t.ib, ob: t.ob, sub: sm.kind === "internet" ? (sm.measured ? "internet · measured" : "internet · estimated") : sm.kind === "turn" ? "turn-proxy" : sm.kind === "mesh" ? T("fleet nodes not shown") : "clients", col: sm.color }; } }   // i18n-keys: internal fork/service id
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
        <div class="fm2-bub-r"><span style=${"color:" + FLOW_IN}>${T("↓ ingress")}</span><b>${fmt(hv.ib || 0)}</b></div>
        <div class="fm2-bub-r"><span style=${"color:" + FLOW_EG}>${T("↑ egress")}</span><b>${fmt(hv.ob || 0)}</b></div>
      </div>` : null}
    </div>
    <div class="fm2-anim" title=${T("Flow animation (saved for everyone)")}>${FLOW_ANIMS().map(a => html`<button key=${a.id} class=${"fm2-anim-b" + (anim === a.id ? " on" : "")} title=${a.label} onClick=${() => setAnim(a.id)}><${Ic} i=${a.ic}/></button>`)}</div>
  </div>`;
}

let _svcAlerted = new Set();   // incidents already popped THIS page-load (resets on hard refresh); clears per-incident when it recovers
let _appReady = false;
// App tells this module when it has mounted: before that the modal renderer is a no-op, so a
// service-issue alert raised during the first poll would be opened into nothing and lost.
export const setAppReady = v => { _appReady = !!v; };         // set once the App has mounted (so openModal's setState is wired) — the first poll can land BEFORE mount
export function maybeAlertServices() {
  if (!_appReady) return;      // pre-mount: _setStack is a no-op → a modal opened now would be orphaned; wait for mount
  try {
    const issues = serviceIssues();
    const live = new Set(issues.map(svcKey));
    const sil = svcSilencedSet(); let silChanged = false;   // prune silences whose incident cleared → recurrence re-alerts
    [...sil].forEach(k => { if (!live.has(k)) { sil.delete(k); silChanged = true; } });
    if (silChanged) svcSaveSilence(sil);
    [..._svcAlerted].forEach(k => { if (!live.has(k)) _svcAlerted.delete(k); });
    if (modalDepth()) return;                              // don't clobber a modal the operator has open
    const crit = issues.filter(i => i.sev === "critical" && !sil.has(svcKey(i)));
    const fresh = crit.filter(i => !_svcAlerted.has(svcKey(i)));
    if (!fresh.length) return;
    crit.forEach(i => _svcAlerted.add(svcKey(i)));
    setTimeout(() => { if (!modalDepth()) openModal(html`<${ServiceIssueSheet} issues=${crit}/>`); }, 0);   // defer past any hashchange (resets the stack)
  } catch (_) {}
}
// The modal for service issues — the row click and the critical on-load alert both open it. Explains each
// issue + the two honest remediations: "Run update" (reinstalls anything missing + re-enables) and the
// exact status/log commands for a service that's actually crashing.
export function ServiceIssueSheet({ issues }) {
  const list = (issues || []).filter(Boolean);
  if (!list.length) { closeModal(); return null; }
  return html`<${Sheet} noGuard=${true} onClose=${closeModal}
      title=${list.length === 1 ? T("{v1} needs attention", { v1: list[0].label }) : T("Panel services need attention")}
      foot=${html`<${Fragment}>
        <button class="btn btn-ghost" onClick=${() => { list.forEach(svcSilence); closeModal(); }}>${T("Silence")}</button>
        <span class="grow"></span>
        <button class="btn btn-primary" onClick=${() => { closeModal(); updateHost(); }}>${T("Run update")}</button>
      <//>`}>
    <div class="svc-modal">
      ${list.map(i => html`<div class=${"svc-item " + i.sev} key=${svcKey(i)}>
        <div class="svc-head"><span class=${"svc-dot " + i.sev}></span><b>${i.label}</b>
          <span class=${"svc-tag " + i.sev}>${i.sev === "critical" ? "Critical" : "Warning"}</span></div>
        <div class="svc-msg">${i.msg}.</div>
        ${i.unit ? html`<div class="svc-cmd"><code>systemctl status ${i.unit}</code> · <code>journalctl -u ${i.unit} -e</code></div>`
          : html`<div class="svc-cmd"><code>dkms status</code> · <code>modprobe amneziawg</code></div>`}
      </div>`)}
      <div class="svc-foot">${T("“Run update” reinstalls anything missing and re-enables the service — the same repair the Update button runs. A service that keeps crashing needs the logs above.")}</div>
    </div>
  <//>`;
}

// Overview "Protection" card feed. One light fetch keyed on the shared dashboard range (block-stats supports
// live too, unlike useRangeHistory). Node stays a dumb reporter; the panel owns every range. Read-only.
export function useBlockStats(range) {
  const [bs, setBs] = useState({ loading: true, data: null, range: null });
  useEffect(() => {
    let alive = true; setBs(s => ({ ...s, loading: true }));
    const load = () => api.blockStats(range)
      .then(r => { if (alive) setBs({ loading: false, data: (r && r.data) || null, range }); })
      .catch(() => { if (alive) setBs(s => ({ ...s, loading: false })); });
    load();
    const t = setInterval(load, 15000);   // live-poll so the Blocked counter climbs without a reload (RRD buckets are ≥15s)
    return () => { alive = false; clearInterval(t); };
  }, [range]);
  return bs;
}

// Interleave a separator between vnodes (Preact renders arrays fine, but needs the separators as real entries).
export const joinNodes = (nodes, sep) => nodes.flatMap((n, i) => i ? [sep, n] : [n]);



// The blocking Protection card: what the fleet caught (torrents), flagged (scan sources), and dropped (distinct
// destinations reached, forcedns/hybrid only) over the selected range, plus a static coverage line. All FREE
// signals harvested from existing datapath state — nothing here changes blocking. Honest verbs: caught/flagged/dropped.
// The "who" bubble content for a Protection tile — which user / which peers triggered this metric. Rendered inside a
// Popover portal (.deppop.onlpop shell — fixed-position, escapes the card, JS hover with a grace period). rows =
// [{user, peers:[], count}]. ≤15 rows show as-is; 16–50 scroll the list; >50 paginate 50/page (Next → top, Prev → bottom).
export const WHO_PER_PAGE = 50, WHO_VISIBLE = 15;
export function WhoBubble({ rows, color }) {
  // Flatten user→peers into ONE row per peer ("user · peer  ·  when"), newest first — reads at a glance, no nesting.
  const flat = [];
  for (const g of rows) for (const q of (g.peers || [])) flat.push({ user: g.user, name: q.name, ago: q.ago, dur: q.dur });
  flat.sort((a, b) => a.ago - b.ago);
  const [page, setPage] = useState(0);
  const listRef = useRef(null), dir = useRef(0);
  const pages = Math.max(1, Math.ceil(flat.length / WHO_PER_PAGE));
  const p = Math.min(page, pages - 1);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = dir.current < 0 ? el.scrollHeight : 0; }, [p]);
  const paged = pages > 1 ? flat.slice(p * WHO_PER_PAGE, p * WHO_PER_PAGE + WHO_PER_PAGE) : flat;
  const go = d => { dir.current = d; setPage(x => Math.max(0, Math.min(pages - 1, x + d))); };
  const scroll = flat.length > WHO_VISIBLE || pages > 1;
  const agoS = s => (s == null ? "" : s < 5 ? "now" : T("{v1} ago", { v1: seen(s) }));   // relative last-seen from panel-sent seconds
  return html`<div class="prot-who">
    <div class="prot-who-h">${T("Who")}<span class="prot-who-sub">${T("latest first")}</span>${flat.length > 1 ? html`<span class="prot-who-tot">${fmtCount(flat.length)}</span>` : ""}</div>
    <div class=${"prot-who-list" + (scroll ? " scroll" : "")} ref=${listRef}>
      ${paged.map((q, i) => html`<div class="prot-who-r" key=${p + "-" + i}>
        <span class="prot-who-id">${q.user ? html`<span class="prot-who-nm">${q.user}</span>` : html`<span class="prot-who-un">${T("tag|unassigned")}</span>`}<span class="prot-who-sep">·</span><span class="prot-who-pn">${q.name}</span></span>
        <span class="prot-who-ago" style=${"color:" + color}>${agoS(q.ago)}</span>
      </div>`)}
    </div>
    ${pages > 1 ? html`<div class="prot-who-pg">
      <span class="prot-who-pglbl">${p * WHO_PER_PAGE + 1}–${Math.min(flat.length, p * WHO_PER_PAGE + WHO_PER_PAGE)} of ${fmtCount(flat.length)}</span>
      <span class="prot-who-pgbtns">
        <button class="prot-who-pgb" disabled=${p === 0} onClick=${() => go(-1)}>${T("Prev")}</button>
        <button class="prot-who-pgb" disabled=${p >= pages - 1} onClick=${() => go(1)}>${T("Next")}</button>
      </span>
    </div>` : null}
  </div>`;
}
export function CatsBubble({ cats, color, counts }) {
  // Blocked drill-down. Two shapes, biggest first:
  //   counts=true  → per-category blocked COUNTS (SNI mode): which categories are actually catching traffic. Approximate
  //                  (swg-sni sees each blocked site ~once per learn-cycle) → a distribution, not an exact hit count.
  //   counts=false → COMPOSITION: what's loaded, by list size (the datapath merges feeds into one union → no per-cat
  //                  counter, so this is the only signal in Force-DNS / non-SNI modes).
  const kmb = n => { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
    : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n); };
  const scroll = cats.length > WHO_VISIBLE;
  return html`<div class="prot-who">
    <div class="prot-who-h">${counts ? "Blocked" : "Filtering"}<span class="prot-who-sub">${counts ? T("sites caught") : T("by list size")}</span><span class="prot-who-tot">${fmtCount(cats.length)}</span></div>
    <div class=${"prot-who-list" + (scroll ? " scroll" : "")}>
      ${cats.map((c, i) => html`<div class="prot-who-r prot-cat-row" key=${i}>
        <span class="prot-cat-nm">${c.label}</span>
        <span class="prot-who-ago prot-cat-n" style=${"color:" + color}>${counts ? T("{v1} {v2}", { v1: kmb(c.count), v2: pluralWord(c.count, "site") }) : (c.threat_ips ? T("{v1} IPs", { v1: kmb(c.threat_ips) }) : T("{v1} dom", { v1: kmb(c.domains) }))}</span>
      </div>`)}
    </div>
  </div>`;
}
export function Protection({ range, bs }) {
  const d = bs.data;
  const cov = (d && d.coverage) || {};
  const mech = cov.mechanisms || {};
  const mechKeys = Object.keys(mech);
  const hasCov = (cov.domains || 0) + (cov.threat_ips || 0) + (cov.categories || 0) + mechKeys.length > 0;
  const torrents = (d && d.torrents) || 0, scan = (d && d.scan) || 0, reach = (d && d.reach) || 0, blocked = (d && d.blocked) || 0;
  const who = (d && d.who) || {};   // per-metric attribution {scan:[{user,peers,count}], …} → the hover "who" bubble
  const bcats = (d && d.blocked_cats) || [];   // [{label,count}] per-category blocked counts (SNI mode) → Blocked bubble
  // Nothing configured and nothing seen → don't show an empty card on installs that don't use blocking.
  if (!d || (!hasCov && !torrents && !scan && !reach && !blocked)) return null;
  const rw = rangeWord(bs.range || range);
  const kmb = n => { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M"
    : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n); };
  const MECH_LABEL = { torrents: "Torrents", smtp: "Spam / SMTP", portscan: T("Port scans"), quic: "QUIC", doh: "DoH", mining: "Mining" };
  const tiles = [];
  // Blocked — cumulative packets dropped to content-filter sets over the range (GROWS as you browse). The distinct
  // destinations currently blocked (reach) ride along as context. Shown whenever content filtering is in play.
  if (cov.domains || blocked || reach) {
    // the tile's "sites" is the SAME distinct-domain total the bubble breaks down (so they reconcile: 12 = 6+3+3),
    // not reach (distinct IPs — a CDN domain is many IPs). Fall back to reach only when there's no per-category data.
    const bsites = bcats.reduce((a, c) => a + (c.count || 0), 0);
    const bsub = bcats.length ? (T("{v1} sites", { v1: kmb(bsites) })) : (reach ? (T("{v1} sites", { v1: kmb(reach) })) : "");
    tiles.push({ k: "Blocked", v: kmb(blocked), n: blocked,
      sub: bsub ? T("packets · {v1} · {v2}", { v1: bsub, v2: rw }) : (blocked ? T("packets · {v1}", { v1: rw }) : T("none {v1}", { v1: rw })),   // the big number is DROPPED PACKETS (inflated by retries); "sites" is what the bubble sums to
      spark: (d && d.bseries) || null, color: "var(--brand)",
      // Prefer per-category counts (SNI mode, what's actually catching traffic); fall back to composition (what's loaded).
      bcats: bcats.length ? bcats : null, cats: (cov.cats && cov.cats.length) ? cov.cats : null });
  }
  tiles.push({ k: T("Torrents caught"), v: kmb(torrents), n: torrents, sub: torrents ? T("connections · {v1}", { v1: rw }) : T("none {v1}", { v1: rw }), spark: (d && d.series) || null, color: "var(--dangling)", who: who.torrent });
  tiles.push({ k: T("Scanners flagged"), v: kmb(scan), n: scan, sub: scan ? "source" + (scan === 1 ? "" : "s") + " · " + rw : T("none flagged"), color: "var(--partial)", who: who.scan });
  // Coverage sentence — what the fleet is FILTERING (ads/malware/mining live here; they can be listed, not counted).
  const covParts = [];
  if (cov.domains) covParts.push(html`<b>${kmb(cov.domains)}</b> domains`);
  if (cov.threat_ips) covParts.push(html`<b>${kmb(cov.threat_ips)}</b> threat-IPs`);
  const acrossParts = [];
  if (cov.categories) acrossParts.push(html`<b>${cov.categories}</b> categor${cov.categories === 1 ? "y" : "ies"}`);
  if (cov.ifaces) acrossParts.push(html`<b>${cov.ifaces}</b> interface${cov.ifaces === 1 ? "" : "s"}`);
  return html`<${Fragment}>
    ${secTitle(T("Protection"), html`${rw} · ${T("what blocking caught & is filtering")}`, undefined, "protection")}
    <div class="protcard">
      <div class="prot-metrics">
        ${tiles.map(t => { const w = (t.who && t.who.length) ? t.who : null;
          const inner = html`<${Fragment}>
            <div class="prot-top">
              <div class="prot-v" style=${"color:" + (t.n ? t.color : "var(--faint)")}>${t.v}</div>
              <div class="prot-tc">
                <div class="prot-k">${t.k}</div>
                <div class="prot-sub">${t.sub}</div>
              </div>
            </div>
            ${t.spark ? html`<div class="prot-spark"><${TrendSpark} data=${t.spark} color=${t.color}/></div>` : null}
          <//>`;
          // Tiles with a drill-down (offenders for torrent/scan, filter composition for blocked) put it in a Popover
          // portal (fixed-position, escapes the card, hover with a grace period so moving into the bubble never drops
          // it). Plain tiles render as a div.
          const pop = w
            ? html`<${WhoBubble} rows=${w} color=${t.color}/>`
            : (t.bcats ? html`<${CatsBubble} cats=${t.bcats} color=${t.color} counts/>`
              : (t.cats ? html`<${CatsBubble} cats=${t.cats} color=${t.color}/>` : null));
          return pop
            ? html`<${Popover} key=${t.k} hoverOnly flipFit cls="prot-tile haswho" popCls="prot-who-pop" trigger=${inner}>
                ${pop}
              <//>`
            : html`<div class="prot-tile" key=${t.k}>${inner}</div>`;
        })}
      </div>
      ${hasCov ? html`<div class="prot-cov">
        <span class="prot-cov-ic"><${Ic} i="shield"/></span>
        <span class="prot-cov-txt">
          ${covParts.length ? html`Filtering ${joinNodes(covParts, " + ")}` : T("Mechanism blocking")}
          ${acrossParts.length ? html` across ${joinNodes(acrossParts, " · ")}` : ""}
        </span>
        ${mechKeys.length ? html`<span class="prot-mech">${mechKeys.map(m => html`<span class="prot-chip" key=${m}>${MECH_LABEL[m] || m}${mech[m] > 1 ? html` <i>×${mech[m]}</i>` : ""}</span>`)}</span>` : null}
      </div>` : null}
    </div>
  <//>`;
}

// ═════════════════════════ SCREEN: OVERVIEW ═════════════════════════
export function Overview() {
  useStore();
  const peers = Store.recon.peers, users = Store.recon.users, fleet = Store.fleet, ns = Store.recon.nodeStatus;
  // Every widget aggregates over the SELECTED node set (default = whole fleet). A peer is "in scope" if
  // it has at least one target on a selected node; its counts/traffic come only from selected nodes.
  const selIds = dashNodes(), sel = new Set(selIds);
  const rangeHist = useRangeHistory(dashState.range, selIds);   // one fetch, shared by the doughnuts + flow map
  const blockStats = useBlockStats(dashState.range);            // Protection card feed (independent, supports live)
  // Fresh install (or every node removed) → there's no fleet to chart. Skip the whole dashboard and invite
  // the operator to add their first entry server. (After the two hooks above, so rules-of-hooks holds.)
  if (fleet.length === 0) return html`<div class="screen"><div class="nonodes">
    <div class="nonodes-ic"><${Ic} i="server"/></div>
    <h2>${T("No nodes yet")}</h2>
    <p>${T("Add your first entry server to start deploying peers. The panel stays the source of truth — each node syncs to it over outbound HTTPS.")}</p>
    <button class="btn btn-primary" onClick=${openNodeCreate}><span class="plus"><${Ic} i="plus"/></span> ${T("Add node")}</button>
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
    if (snap) for (const w of (snap.wdtt || [])) { r += w.rx_speed || 0; t += w.tx_speed || 0; }   // WDTT owns its TUN (aggregate rx/tx)
    if (snap) for (const c of (snap.csqtt || [])) { r += c.rx_speed || 0; t += c.tx_speed || 0; }   // csqtt owns its raw TUN (aggregate rx/tx)
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
  const ifaceCount = selIds.reduce((a, id) => a + Object.keys(Store.describe[id] || {}).filter(ifn => !isSys(id, ifn)).length + ((Store.stats[id] || {}).wdtt || []).filter(w => w && w.iface).length + ((Store.stats[id] || {}).csqtt || []).filter(c => c && c.iface).length, 0);   // + WDTT + csqtt interfaces (own their TUN, not in describe)
  const nodesAlerting = fleetSel.filter(n => healthAlerts(((Store.nodes || []).find(x => x.id === n.id) || {}).health).length).length;
  let rx = 0, tx = 0;
  fleetSel.forEach(n => { const [r, t] = nodeRate(n.id); rx += r; tx += t; });

  const PROB_STATUSES = ["dangling", "partial", "blocked", "faulty", "pending", "unknown"];
  const probs = sPeers.filter(p => PROB_STATUSES.includes(p.status))
    .sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const unassigned = Store.unassignedPeers().filter(onSel);
  const orphans = Store.recon.orphans.filter(o => sel.has(o.node));
  const why = { dangling: T("missing on every server"), partial: T("missing on some servers"), blocked: T("handshake never completes"), faulty: T("no inbound data flowing"), pending: T("just created, not seen yet"), unknown: T("server stale — can't confirm") };

  // Needs-attention shown IN BULK: problem peers grouped by status, unassigned grouped by node, orphans
  // grouped by interface — each row lands where you'd fix it (Peers filtered, or the interface detail).
  const STATUS_WORD = { dangling: "dangling", partial: T("partially deployed"), blocked: "restricted", faulty: "faulty", pending: "pending", unknown: T("on a stale server") };
  const statusGroups = PROB_STATUSES.map(s => ({ status: s, peers: probs.filter(p => p.status === s) })).filter(g => g.peers.length);
  const unByNode = {};
  unassigned.forEach(p => p.targets.forEach(t => {
    if (!sel.has(t.node)) return;
    const g = unByNode[t.node] || (unByNode[t.node] = { node: t.node, peers: new Set(), wg: new Set(), awg: new Set(), wdtt: new Set(), csqtt: new Set() });
    g.peers.add(p.id); (g[targetType(t)] || g.wg).add(t.iface);   // wg | awg | wdtt | csqtt — each to its own bucket (never lump self-contained under wg)
  }));
  const unGroups = Object.values(unByNode);
  const orphByIf = {};
  orphans.forEach(o => { const k = o.node + "|" + o.iface; (orphByIf[k] || (orphByIf[k] = { node: o.node, iface: o.iface, n: 0 })).n++; });
  const orphGroups = Object.values(orphByIf);
  const svcIssues = serviceIssues();   // panel-host service health — one box, so shown regardless of the node filter (critical first)
  const attnCount = svcIssues.length + statusGroups.length + unGroups.length + orphGroups.length;

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
  // Top nodes by ONLINE peers — live = online right now; a range = DISTINCT peers seen online over the window
  // (presence bitmaps, same source as the online-peers hero). If live and NOBODY is online, fall back to each
  // node's total peer count so the chart still says something.
  const onlineOf = n => dRanged ? (((rangeHist.presence || {}).nodes || {})[n.id] || {}).peers || 0
                                 : sPeers.filter(p => p.targets.some(t => t.node === n.id && t.online)).length;
  const nodeOnline = fleetSel.map(n => ({ id: n.id, name: n.name, color: Store.nodeColor(n.id),
    online: onlineOf(n), total: sPeers.filter(p => p.targets.some(t => t.node === n.id)).length }));
  const rnkTotal = !dRanged && !nodeOnline.some(x => x.online > 0);   // live + nobody online → show totals
  const rankRows = nodeOnline.slice()
    .sort((a, b) => rnkTotal ? b.total - a.total : (b.online - a.online) || (b.total - a.total))
    .slice(0, 6)
    .map(x => ({ label: x.name, value: rnkTotal ? x.total : x.online,
      sub: rnkTotal ? (T("{v1} total", { v1: x.total })) : (T("{v1} online", { v1: x.online })),
      color: x.color || "var(--brand)", href: "#/node/" + encodeURIComponent(x.id) }));
  // Top nodes BY TRAFFIC — separate chart, shown alongside the by-peers one. Live = throughput now; a range = volume.
  const anyTraffic = nodeTraffic.some(x => x.rx + x.tx > 0);
  const rankRowsTraffic = nodeTraffic.slice().sort((a, b) => (b.rx + b.tx) - (a.rx + a.tx)).slice(0, 6)
    .map(x => ({ label: x.name, value: x.rx + x.tx, sub: dRanged ? xferCell(...dlul(x.rx, x.tx)) : rateCell(x.rx, x.tx),
      color: x.color || "var(--brand)", href: "#/node/" + encodeURIComponent(x.id) }));

  // ── range-aware fleet hero series. Live = the 15s ring + online accumulator (no server hit); a range =
  //    Σ per-node RRD (fetched once by useRangeHistory, off the hot path). Fleet throughput reuses the node
  //    ThroughputChart summed; online-peers resamples pon into the fixed per-range block count. ──
  const fleetHist = fleetHistory(selIds, effRange, rangeHist);
  const tputRange = effRange === "live" ? "hour" : effRange;   // fleet live feed IS the 15s (hour) ring
  const [obN, obStep] = ONLINE_BLOCKS[effRange] || ONLINE_BLOCKS.live;
  // Each bar = DISTINCT peers seen online in that bar's span, unioned from the presence bitmaps. `pon` (the
  // health ring) is a mean of concurrency and cannot answer this: five peers online 12 min each average to 1.
  // Live keeps the client-side accumulator — a 30s bar of T("online now") needs no server round-trip.
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
    const pkPeer = {}; sPeers.forEach(p => { if (p.pubkey) pkPeer[p.pubkey] = p; pkPeer[p.id] = p; });   // wg peers keyed by pubkey; keyless (WDTT/csqtt) rows come back keyed by peer id
    const byPk = {};
    (rangeHist.peers || []).forEach(e => { if (!sel.has(e.node) || !pkPeer[e.pubkey]) return;
      const a = byPk[e.pubkey] = byPk[e.pubkey] || { rx: 0, tx: 0 }; a.rx += e.rx || 0; a.tx += e.tx || 0; });
    perPeer = Object.entries(byPk).map(([pk, v]) => ({ p: pkPeer[pk], rx: v.rx, tx: v.tx })).filter(x => x.p);
  } else {
    perPeer = sPeers.map(p => {
      let r = 0, t = 0; p.targets.forEach(tg => { if (!sel.has(tg.node)) return;
        const o = tg.observed; if (o) { r += o.rx_speed || 0; t += o.tx_speed || 0; }
        else if (tg.kwSpeed) { r += tg.kwSpeed.rx || 0; t += tg.kwSpeed.tx || 0; } });   // WDTT/csqtt keyless per-peer speed
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
      label: g.user ? g.user.name : (g.sample.title || T("Unassigned peer")), value: g.rx + g.tx, count: peers.length,
      sub: dRanged ? xferCell(...dlul(g.rx, g.tx)) : rateCell(g.rx, g.tx),
      // per-peer breakdown for the hover bubble — only when a user has >1 peer actually contributing traffic.
      // Each row carries its protocol (wg/awg, from the live interface) + a name: the peer's title, or — when it has
      // none — "Peer .<last octet of its tunnel IP>" (e.g. 10.99.3.43 → "Peer .43"), never the user's name.
      bub: peers.length > 1 ? peers.map(pp => { const t = (pp.p.targets || [])[0] || {}; const oct = (t.ip || "").split(".").pop();
        return { kind: targetType(t), name: pp.p.title || (oct ? T("Peer .{v1}", { v1: oct }) : T("Peer")), value: pp.rx + pp.tx,
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
  // Block-list sets (blku_*) ride the smart-routing chain to get their drop verdict, so they surface a byte counter
  // like a routing category — but a BLOCKED destination is not a "top destination" the client reached. Drop them.
  const _cadd = (cat, up, dn) => { if (isBlockCat(cat)) return; const a = catAgg[cat] = catAgg[cat] || { up: 0, dn: 0 }; a.up += up || 0; a.dn += dn || 0; };
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
      <a class="stat accent clk" href="#/connections" onClick=${openLiveTab("peers")}><span class="stat-ic"><${Ic} i="activity"/></span><div class="stat-c"><div class="k">${T("Online now")}</div><div class="v">${online}<small> / ${sPeers.length}</small></div><div class="sub">${T("live connections →")}</div></div></a>
      <a class="stat clk" href="#/users"><span class="stat-ic"><${Ic} i="users"/></span><div class="stat-c"><div class="k">${T("Users")}</div><div class="v">${sUsers.length}</div><div class="sub">${scoped ? T("{v1} here", { v1: plural(sPeers.length, "peer") }) : T("{v1} total", { v1: plural(sPeers.length, "peer") })}</div></div></a>
      <a class="stat clk" href="#/peers"><span class="stat-ic"><${Ic} i="device"/></span><div class="stat-c"><div class="k">${T("Peers")}</div><div class="v" style="font-size:19px"><span style="color:var(--ink)">${pAssigned}</span> · <span style="color:var(--dim)">${pUnassigned}</span></div><div class="sub">${T("assigned · unassigned")}</div>${orphans.length ? html`<div class="sub" style="color:#E8912D;font-weight:600">${T("Orphan peers {n}", { n: orphans.length })}</div>` : ""}</div></a>
      <a class="stat clk" href="#/nodes"><span class="stat-ic"><${Ic} i="server"/></span><div class="stat-c"><div class="k">${T("col|Nodes")}</div><div class="v">${liveNodes}<small> / ${fleetSel.length}</small></div><div class="sub">${plural(ifaceCount, "interface")}</div>${nodesAlerting ? html`<div class="sub" style="color:var(--dangling)">${T("{n} alerting", { n: nodesAlerting })}</div>` : ""}</div></a>
      <div class="stat"><span class="stat-ic"><${Ic} i="gauge"/></span><div class="stat-c"><div class="k">${T("Throughput")}</div><div class="v" style=${"font-size:19px;color:" + (rx + tx > 0 ? "var(--online)" : "var(--faint)")}>↓ ${rate(dlul(rx, tx)[0])}</div><div class="sub"><span style=${"color:" + (rx + tx > 0 ? "var(--ready)" : "var(--faint)")}>↑ ${rate(dlul(rx, tx)[1])}</span>${scoped ? " selected" : " aggregate"}</div></div></div>
    </div>

    ${secTitle(T("Fleet"), scoped ? T("{n} of {total}", { n: fleetSel.length, total: plural(fleet.length, "server") }) : plural(fleet.length, "server"), undefined, "fleet")}
    ${fleetSel.length ? html`<div class="trends">
      <div class="trendcard wide">
        <div class="donutcard-h"><h3>${T("Fleet throughput")}</h3></div>
        ${(fleetHist.t || []).length > 1
          ? html`<${ThroughputChart} rx=${fleetHist.rx} tx=${fleetHist.tx} times=${fleetHist.t} range=${tputRange} cap=${RANGE_CAP[tputRange]} h=${70}/>`
          : html`<div class="harea-empty">${T("gathering — no history yet")}</div>`}
      </div>
      <div class="trendcard">
        <div class="donutcard-h"><h3>${T("Online peers")}</h3><span class="grow"></span><span class="trend-now">${dRanged && _pres ? (_pres.total || {}).peers : online}</span></div>
        ${hasOnline
          ? html`<${OnlineBlocks} blocks=${onlineBlocks} step=${obStep} endTs=${onlineEndTs} range=${effRange} color="var(--online)" h=${70}/>`
          : html`<div class="harea-empty">${T("gathering — fills as it polls")}</div>`}
      </div>
    </div>` : null}
    ${fleetSel.length ? html`<div class="fleet2">${fleetSel.map(n => html`<${FleetNodeCard} key=${n.id} n=${n} traffic=${nodeTraffic.find(x => x.id === n.id)} ranged=${dRanged} histRange=${effRange} nodeHist=${(rangeHist.byNode || {})[n.id] || null} presence=${dRanged && _pres ? (_pres.nodes || {})[n.id] || null : null}/>`)}</div>`
      : html`<div class="allclear">${T("No servers configured in fleet.json.")}</div>`}

    ${fleetSel.length ? html`<${Fragment}>
      ${secTitle(T("Distribution"), html`${scoped ? T("selected nodes") : T("whole fleet")} · ${rangeWord(effRange)}`, undefined, "distribution")}
      <${DashDoughnuts} selIds=${selIds} range=${effRange} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length ? html`<${Fragment}>
      ${secTitle(T("Traffic flow map"), T("signal flow · by category"), undefined, "flow")}
      <${FlowMap2} selIds=${selIds} range=${effRange} hist=${rangeHist}/>
    <//>` : null}

    ${fleetSel.length ? html`<${Protection} range=${effRange} bs=${blockStats}/>` : null}

    ${fleetSel.length > 1 ? html`<${Fragment}>
      ${secTitle(T("Top nodes by peers"), rnkTotal ? T("total peers") : (dRanged ? T("online · {range}", { range: rangeWord(effRange) }) : T("online now")), undefined, "topnodes")}
      <div class="rankcard"><${RankBars} rows=${rankRows}/></div>
    <//>` : null}

    ${fleetSel.length > 1 && anyTraffic ? html`<${Fragment}>
      ${secTitle(T("Top nodes by traffic"), dRanged ? T("{range} · by volume", { range: rangeWord(effRange) }) : T("by live throughput"), undefined, "topnodestraf")}
      <div class="rankcard"><${RankBars} rows=${rankRowsTraffic}/></div>
    <//>` : null}

    ${talkerRows.length ? html`<${Fragment}>
      ${secTitle(T("Top talkers"), dRanged ? T("{range} · by volume", { range: rangeWord(effRange) }) : T("by live throughput"), undefined, "toptalkers")}
      <div class="rankcard"><${RankBars} rows=${talkerRows}/></div>
    <//>` : null}

    ${catRows.length ? html`<${Fragment}>
      ${secTitle(T("Top destinations"), html`${dRanged ? rangeWord(effRange) : rangeWord("live")} · ${T("categories overlap")}${(totClientRx + totClientTx) ? (() => { const f = dRanged ? fmtBytes : rate, [d, u] = dlul(totClientRx, totClientTx); return html` · ${ofTotal(f(d), f(u))}`; })() : ""}`, undefined, "topdest")}
      <div class="rankcard"><${RankBars} rows=${catRows}/></div>
    <//>` : null}

    ${recent.length ? html`<${Fragment}>
      ${secTitle(T("Recent activity"), null, false, "activity")}
      <div class="actlist">${recent.map(e => html`<a class=${"act-row" + (e.click ? "" : " noclk")} href=${e.click ? e.click.href : null} key=${e.key}
          onClick=${e.click && e.click.on ? (ev => { ev.preventDefault(); e.click.on(); }) : (e.click ? null : (ev => ev.preventDefault()))}>
        <span class=${"act-ic t-" + e.slug}><${Ic} i=${e.icon}/></span>
        <span class="act-what">${srvVerb(e.verb)}</span>${e.name ? html`<span class="act-name">${e.name}</span>` : null}
        ${e.detail || e.detail_key ? html`<span class="act-detail">${srvDetail(e)}</span>` : null}
        <span class="grow"></span><span class="when">${ago(e.ts)}</span>${e.click ? html`<span class="act-arrow"><${Ic} i="arrow"/></span>` : null}</a>`)}</div>
      <div class="act-morewrap"><a class="act-more" href="#/activity">${T("Show all history »")}</a></div>
    <//>` : null}

    ${secTitle(T("Needs attention"), attnCount ? plural(attnCount, "group") : null, undefined, "attention")}
    ${!attnCount
      ? html`<div class="allclear"><${Ic} i="check"/><span>${T("Everything's deployed and reporting. No drift across the fleet.")}</span></div>`
      : html`<div class="attn">
          ${svcIssues.map(is => html`<div class=${"attn-row svc " + is.sev} key=${"svc" + svcKey(is)} onClick=${() => openModal(html`<${ServiceIssueSheet} issues=${[is]}/>`)}>
            <span class=${"svc-badge " + is.sev}><${Ic} i="warn"/>${is.sev === "critical" ? "Critical" : "Warning"}</span>
            <span class="name">${is.label} — ${SVC_KINDWORD[is.kind] || is.kind}</span>
            <span class="why">${is.msg}</span><span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${statusGroups.map(g => html`<div class="attn-row" key=${"s" + g.status} onClick=${() => revealPeersFiltered({ status: g.status })}>
            <${Badge} s=${g.status}/><span class="name">${Trich("*{v1}* {v2}", { v1: plural(g.peers.length, "peer"), v2: STATUS_WORD[g.status] || g.status })}</span>
            <span class="why">${why[g.status] || ""}</span><span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${unGroups.map(g => html`<div class="attn-row" key=${"u" + g.node} onClick=${() => revealPeersFiltered({ node: g.node, status: "unassigned" })}>
            <${Badge} s="unassigned"/><span class="name">${Trich("*{v1}* unassigned on {v2} on {v3}", { v1: plural(g.peers.size, "peer"), v2: ifCountPhrase(g), v3: Store.nodeName(g.node) })}</span>
            <span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
          ${orphGroups.map(g => html`<div class="attn-row" key=${"o" + g.node + g.iface} onClick=${() => revealOrphans(g.node, g.iface)}>
            <${Badge} s="orphan"/><span class="name">${Trich("*{v1}* orphan on {v2} ({v3}) on {v4}", { v1: plural(g.n, "peer"), v2: g.iface, v3: ifTypeLabel(g.node, g.iface), v4: Store.nodeName(g.node) })}</span>
            <span class="grow"></span><span class="rowarrow"><${Ic} i="arrow"/></span></div>`)}
        </div>`}
  </div>`;
}

// ═════════════════════════ SCREEN: NODE DETAIL ═════════════════════════
// health-check roll-up badge (issues). The data refreshes itself on the 5s poll — no manual re-check
// button (removed as redundant). The `activity` pulse icon it used is now free for a future feature.
