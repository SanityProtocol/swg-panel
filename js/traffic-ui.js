/* traffic-ui.js — what the operator sees of the traffic totals (docs/TRAFFIC-HISTORY-PLAN.md P2): the window control the
 * Peers and Users grids and both views share, the ranged Total cell and its bubble, and the volume chart.
 * The data is traffic.js's; the sheets that host the chart (the peer and user views) live in sheets-crud.js.
 *
 * ⚠️ EVERY FIGURE GOES THROUGH dlul(). xferCell() takes figures already oriented to Settings → Throughput perspective —
 * it does not orient them itself, unlike rateCell() — so a ranged total handed to it raw would read upside down for an
 * operator who counts from the peers' side.
 */
import { fmtBytes } from "./util.js";
import { T, locale } from "./i18n.js";
import { Store, useStore, bus } from "./store.js";
import { Popover, xferCell, dlul } from "./ui.js";
import { ChartHover } from "./charts.js";
import { trafficRangeLabel, peerTraffic, userTraffic } from "./views.js";
import { trafficView, trafficTotals, trafficData, trafficSeries, panelToday, volumeColumns, customWindow } from "./traffic.js";
import { h, Fragment } from "preact";
import { useState, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// A day in the panel's own zone (the one days are counted in), from an epoch. The formatters are built once per
// language — constructing an Intl.DateTimeFormat costs ~50 µs, and a chart's hover asks for one per column.
const _fmt = {};
function panelDate(ts, withTime) {
  if (!ts) return "";
  const off = ((Store.panelSettings || {}).time_zone_now || {}).offset || 0;
  const d = new Date((ts + off) * 1000);
  try {
    const k = locale() + (withTime ? "|t" : "|d");
    const f = _fmt[k] || (_fmt[k] = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short",
      ...(withTime ? { hour: "2-digit", minute: "2-digit" } : { year: "numeric" }), timeZone: "UTC" }));
    return f.format(d);
  } catch (_) { return d.toISOString().slice(0, withTime ? 16 : 10).replace("T", " "); }
}
const pair = (rx, tx) => { const [d, u] = dlul(rx, tx); return "↓ " + fmtBytes(d) + "  ↑ " + fmtBytes(u); };

// ── the window control ──────────────────────────────────────────────────────────────────────────────────────────
// This month · Last 30 days · Custom — one window for the Peers and Users grids and both views (traffic.js). Custom opens
// two date fields, capped at the panel's own today; a window applies as soon as both ends make one.
// ⚠️ THE DATES ARE A DRAFT until Apply — this control's own, never the shared window. Written into it as they were
// typed, every keystroke of a year (0002, 0020, 0202, 2026) was a fetch cached for good, and a start after the end made
// every grid ask for a window the panel refuses. customWindow() judges the draft (a gated pure function).
export function TrafficRange({ onChange }) {
  const [, force] = useState(0);
  const [draft, setDraft] = useState(null);   // null: showing the window in force
  const v = trafficView, today = panelToday();
  const set = patch => { Object.assign(trafficView, patch); setDraft(null); force(x => x + 1); bus.emit(); if (onChange) onChange(); };   // every grid and view re-reads it
  const pick = r => r !== "custom" ? set({ range: r })
    : set({ range: "custom", from: v.from || today.slice(0, 8) + "01", to: v.to && v.to <= today ? v.to : today });
  const tab = (r, label) => html`<button type="button" class=${"rtab" + (v.range === r ? " on" : "")} aria-pressed=${v.range === r} onClick=${() => pick(r)}>${label}</button>`;
  const dr = draft || { from: v.from, to: v.to };
  const date = k => html`<input type="date" class="datein" value=${dr[k]} min="1970-01-01" max=${today}
    aria-label=${k === "from" ? T("From") : T("To")} onInput=${e => setDraft({ ...dr, [k]: e.target.value })}/>`;
  const w = customWindow(dr.from, dr.to, today);
  const bad = !w.ok && w.why !== "incomplete";
  const changed = !!draft && (dr.from !== v.from || dr.to !== v.to);
  const apply = () => { if (w.ok) set({ from: w.from, to: w.to }); };
  return html`<span class="trange" title=${T("The window the Total column counts — in the panel's days (Settings → Display)")}>
    <span class="rangetabs">${tab("month", T("This month"))}${tab("30d", T("Last 30 days"))}${tab("custom", T("range|Custom"))}</span>
    ${v.range === "custom" ? html`<span class="trange-dates" onKeyDown=${e => { if (e.key === "Enter") apply(); }}>${date("from")}<span class="faint">–</span>${date("to")}
      ${changed ? html`<button type="button" class="btn btn-mini" disabled=${!w.ok} onClick=${apply}>${T("Apply")}</button>` : null}</span>` : null}
    ${bad ? html`<span class="hint warn">${w.why === "future" ? T("The start is after today.") : T("The start is after the end.")}</span>` : null}
  </span>`;
}

// ── the ranged Total cell ───────────────────────────────────────────────────────────────────────────────────────
// `a` is the aggregate (peerTraffic / userTraffic); `ctx` is what the caller knows about the row (ungrouped, filtered, a
// user's own list, the live wire counter — O2) — turned into sentences only inside the bubble, when it opens.
export function TrafficCell({ a, e, ctx, user }) {
  if (e && e.off) return html`<span class="faint" title=${T("Traffic totals are off — Settings → Display says why.")}>—</span>`;
  if (!e || !e.data) return html`<span class="faint">…</span>`;
  const rx = a ? a.rx : 0, tx = a ? a.tx : 0;
  const cell = xferCell(...dlul(rx, tx));
  // ⚠️ THE BUBBLE IS A COMPONENT, so it is built only when it opens: Popover renders its children only while shown.
  // Built inline it cost ~110 µs a cell on every 5 s poll — 11 ms a 100-row page — for bubbles nobody opened.
  return html`<${Popover} hoverOnly cls="tcellpop" popCls="netroute-bub tbub" trigger=${cell}><${TrafficBubble} a=${a} rx=${rx} tx=${tx} ctx=${ctx} user=${user}/><//>`;
}
function TrafficBubble({ a, rx, tx, ctx, user }) {
  const c = ctx || {};
  const notes = user ? [] : [
    c.owner ? T("What this device carried while it belonged to this user.")
      : (a && a.owners > 1 ? T("The whole device — including what it carried for an earlier owner.") : null),
    c.ungrouped ? T("This peer's total across all its deployments — every row of it repeats it.") : null,
    c.filtered ? T("The whole peer, not only the deployments this filter shows.") : null,
    c.wire ? T("On {v1} now: {v2} — since the interface came up", { v1: c.iface, v2: pair(c.wire.rx_bytes || 0, c.wire.tx_bytes || 0) }) : null,
  ];
  const d = user ? trafficData() : null;
  const gone = d ? goneDevices(user, d) : 0;   // the user's devices no longer theirs — walked only when the bubble opens
  return html`<${Fragment}>
    <span class="netroute-h">${trafficRangeLabel()}</span>
    <div class="tb-row"><b>${pair(rx, tx)}</b></div>
    ${a ? html`<div class="tb-row">${T("Lifetime")}: ${pair(a.lifetime_rx, a.lifetime_tx)}</div>
      ${a.opening_rx || a.opening_tx ? html`<div class="tb-row sub">${T("Of which {v1} was already on the counters when history began, {v2}", { v1: pair(a.opening_rx, a.opening_tx), v2: panelDate(a.opening_at) })}</div>` : null}
      ${a.since ? html`<div class="tb-row sub">${T("Counted since {v1}", { v1: panelDate(a.since) })}</div>` : null}`
      : html`<div class="tb-row sub">${T("Nothing counted yet.")}</div>`}
    ${gone ? html`<div class="tb-row">${T("Includes devices no longer theirs (deleted or handed on): {n}", { n: gone })}</div>` : null}
    ${notes.filter(Boolean).map(n => html`<div class="tb-row">${n}</div>`)}
    ${user ? html`<div class="tb-row sub">${T("Traffic between this user's own devices — for example to a home network shared through the VPN — counts on both devices.")}</div>` : null}
  <//>`;
}

// A peer's cell. `owner` = inside that user's own list (what the device carried while it was theirs); `ungrouped` = a row
// per deployment (O10: every row repeats the peer's total); `filtered` = a grouped row under a node or interface filter;
// `wire` = this deployment's live counter and its interface (the old Total's meaning, kept here — O2).
export function PeerTrafficCell({ pid, owner, ungrouped, filtered, wire, iface }) {
  return html`<${TrafficCell} a=${peerTraffic(pid, owner)} e=${trafficTotals()} ctx=${{ owner, ungrouped, filtered, wire, iface }}/>`;
}
export function UserTrafficCell({ uid }) {
  return html`<${TrafficCell} a=${userTraffic(uid)} e=${trafficTotals()} user=${uid}/>`;
}
// A user's devices in the window that are no longer theirs: deleted, or now another user's (or nobody's).
export function goneDevices(uid, d) {
  let n = 0;
  for (const r of (d.rows.get(uid) || [])) { const p = Store.peer(r.id); if (!p || p.user_id !== uid) n++; }
  return n;
}

// ── the volume chart ────────────────────────────────────────────────────────────────────────────────────────────
// A column per bucket over the whole window (volumeColumns): ↓ below, ↑ stacked on it with a 2px gap, both in the
// throughput colours; the scale is the tallest column's. Hover names the column and both figures.
export function VolumeBars({ series, h }) {
  const [hov, setHov] = useState(null); const wref = useRef(null);
  h = h || 84;
  if (!series) return html`<div class="harea-wrap vbars-empty" style=${"height:" + h + "px"}></div>`;
  const cols = volumeColumns(series.points, series.since, series.until);
  const oriented = cols.map(c => { const [d, u] = dlul(c.rx, c.tx); return { ...c, d, u }; });
  const hi = Math.max(1, ...oriented.map(c => c.d + c.u));
  const n = oriented.length;
  const onMove = ev => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const i = Math.floor((ev.clientX - r.left) / r.width * n); setHov(i >= 0 && i < n ? i : null); };
  // a day column is named by its first day, read at NOON: the zone's offset today may differ by an hour from that day's
  // (DST), and read at midnight an hour off names the day before
  const label = c => (c.step >= 86400 ? panelDate(c.start + 43200) : panelDate(c.start, true)) + " · ↓ " + fmtBytes(c.d) + " · ↑ " + fmtBytes(c.u);
  const any = oriented.some(c => c.d + c.u > 0);
  return html`<div class="vbars" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    ${!any ? html`<div class="vbars-none faint">${T("No traffic in this window.")}</div>` : null}
    ${oriented.map((c, i) => html`<div class=${"vbar" + (hov === i ? " hot" : "")} key=${i}>
      ${c.u ? html`<i class="u" style=${"height:" + (c.u / hi * 100) + "%"}></i>` : null}
      ${c.d ? html`<i class="d" style=${"height:" + (c.d / hi * 100) + "%"}></i>` : null}</div>`)}
    ${hov != null ? html`<${ChartHover} xp=${(hov + 0.5) / n * 100} dots=${[]} label=${label(oriented[hov])}/>` : null}
  </div>`;
}

// The traffic block of the peer and user views: the window control, the window's figures, the chart. `by` is "peer" or
// "user". The figures are the totals' (the same numbers the grids show); the chart is the series'.
export function TrafficBlock({ by, id }) {
  useStore();
  const e = trafficTotals();
  const s = trafficSeries(by, id);
  const a = by === "user" ? userTraffic(id) : peerTraffic(id);
  const d = s.data;
  // A gap that opens at the series' own start is the time before the first reading — nothing was missed there. Only a
  // node that went quiet AFTER it had been seen is an outage worth a sentence.
  const gaps = d && d.gaps ? Object.keys(d.gaps).filter(k => (d.gaps[k] || []).some(g => g[0] > d.since)) : [];
  // The series starts where history does: a window reaching back before it is drawn from that day, and says so.
  const began = d && e && e.data && d.from > e.data.from ? d.since : 0;
  return html`<div class="tblock">
    <div class="tblock-head"><span class="lbl">${T("Traffic")}</span><span class="grow"></span><${TrafficRange}/></div>
    ${e && e.off ? html`<div class="notice warn">${T("Traffic totals are off — Settings → Display says why.")}</div>` : html`<${Fragment}>
      <div class="tp-legend tblock-sum">
        <span class="tp-k"><i class="sw rx"></i>↓ ${fmtBytes(a ? dlul(a.rx, a.tx)[0] : 0)}</span>
        <span class="tp-k"><i class="sw tx"></i>↑ ${fmtBytes(a ? dlul(a.rx, a.tx)[1] : 0)}</span>
        <span class="tp-peak">${trafficRangeLabel()}</span>
        ${a ? html`<span class="tp-peak">${T("Lifetime")} ${pair(a.lifetime_rx, a.lifetime_tx)}</span>` : null}
      </div>
      <${VolumeBars} series=${d}/>
      ${began ? html`<div class="hint">${T("History begins on {v1}; the graph starts there.", { v1: panelDate(began + 43200) })}</div>` : null}
      ${gaps.length ? html`<div class="hint">${T("A server this traffic crosses was not reporting for part of the window: what it carried meanwhile lands in the column where it reported again.")}</div>` : null}
      ${s.err && !d ? html`<div class="hint warn">${T("The graph could not be loaded.")}</div>` : null}
    <//>`}
  </div>`;
}
