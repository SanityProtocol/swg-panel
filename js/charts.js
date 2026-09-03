/* charts.js — the inline-SVG chart vocabulary.
 *
 * LAYER 2 (see docs/APP-JS-SPLIT-PLAN.md). No charting library: every shape here is hand-built SVG, which
 * is what keeps the SPA buildless and dependency-free.
 *
 * Only the reusable VOCABULARY lives here. The node-specific composites that arrange these — ifaceTags,
 * NodeHealthPanel, IfaceThroughput, NodeThroughput, NodeHealth — stay behind and travel with the nodes
 * screen; they read node records and the iface-op lifecycle, which is not chart business.
 */

import { rate, niceScaleCeil } from "./util.js";
import { resolvedTheme } from "./theme.js";
import { Store, api } from "./store.js";
import { Tag, Panel } from "./ui.js";
import { T } from "./i18n.js";
import { rangeLabel } from "./views.js";
import { h, Fragment } from "preact";
import { useState, useEffect, useRef, useMemo } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// Minimal auto-scaling filled sparkline — trend shape only, no axes (distinct from Sparkline, which is a fixed
// 0–100 % line for CPU load). `data` is oldest→newest; flat/short/all-zero series draw nothing.
export function TrendSpark({ data, w = 104, h = 24, color = "var(--brand)" }) {
  const a = (data || []).filter(v => v != null);
  if (a.length < 2) return null;
  const max = Math.max.apply(null, a), min = Math.min.apply(null, a), span = (max - min) || 1, n = a.length;
  const xy = a.map((v, i) => [(i / (n - 1)) * w, h - 1 - ((v - min) / span) * (h - 3)]);
  const line = xy.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  if (max <= 0) return null;   // all-zero window → nothing worth drawing
  return html`<svg class="spark" width=${w} height=${h} viewBox=${"0 0 " + w + " " + h} preserveAspectRatio="none" aria-hidden="true">
    <polygon points=${"0," + h + " " + line + " " + w + "," + h} fill=${color} opacity="0.12"/>
    <polyline points=${line} fill="none" stroke=${color} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// Tiny inline-SVG sparkline (no charting lib). `points` is an array of numbers 0..100.
export function Sparkline({ points, color, w, h }) {
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
// Gradient area chart for a history series (0–100). Stretches to its container width;
// the stroke stays crisp via non-scaling-stroke. Used for the CPU-load history.
// format a chart point's timestamp for the hover tooltip — time of day, + date for week/month ranges
export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// per-range tooltip time: live = h:m:s, hour/day = h:m, week/month = "June 24, 6PM" (date + 12h hour)
export function histTime(ts, range) {
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
export function ChartHover({ xp, dots, label }) {
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
export const LOAD_G_DARK = [63, 216, 154], LOAD_G_LIGHT = [14, 158, 99], LOAD_O = [242, 163, 60], LOAD_R = [242, 84, 91];
export function cpuColor(v) {
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
  const LOAD_G = resolvedTheme() === "light" ? LOAD_G_LIGHT : LOAD_G_DARK;   // the low-load green must stay legible on white
  if (v <= 60) return mix(LOAD_G, LOAD_G, 0);
  if (v <= 85) return mix(LOAD_G, LOAD_O, (v - 60) / 25);
  if (v <= 100) return mix(LOAD_O, LOAD_R, (v - 85) / 15);
  return mix(LOAD_R, LOAD_R, 0);
}
// Loss / drop colour ramp, in the panel's own status hues — NOT the CPU ramp's green. Green means "fine",
// and a link losing packets is not fine, so the lowest band is BLUE: "measured, and not a problem".
//
// The blue is a FLOOR, not the first stop of the gradient. Interpolating out of blue lands on a grey-beige
// right where the interesting values sit, and interpolating hue instead walks through green to get there —
// the exact wrong signal. Above the floor the ramp runs warm only: partial (yellow) → fault (orange) →
// dangling (red), three adjacent hues that stay saturated the whole way.
//
// Bands, chosen to under-warn rather than over-warn: blue to 0.5%, yellow→orange 0.5–2%, orange→red 2–5%,
// full red past 5%. ⚠️ Known trade-off, recorded deliberately: 0.4% loss is enough to collapse a cascaded
// upload (measured — 147 Mbit/s to 8 on this fleet) and under these bands it reads BLUE. That is the
// operator's call and the right default for a panel nobody should learn to ignore; the number and its
// sample count are always on the row for anyone reading closely. Tune here; no caller picks colours.
const LOSS_FLOOR = 0.5;
const LOSS_FLOOR_DARK = [79, 168, 240], LOSS_FLOOR_LIGHT = [43, 124, 211];        // --ready
const LOSS_STOPS_DARK = [[0.5, [226, 200, 74]], [2, [242, 153, 74]], [5, [242, 107, 130]]];   // partial → fault → dangling
const LOSS_STOPS_LIGHT = [[0.5, [176, 122, 22]], [2, [217, 119, 42]], [5, [214, 58, 85]]];
export function lossColor(pct) {
  const light = resolvedTheme() === "light";
  const S = light ? LOSS_STOPS_LIGHT : LOSS_STOPS_DARK;
  const rgb = a => "rgb(" + a.join(",") + ")";
  if (!(pct > LOSS_FLOOR)) return rgb(light ? LOSS_FLOOR_LIGHT : LOSS_FLOOR_DARK);
  for (let i = 1; i < S.length; i++) {
    if (pct <= S[i][0]) {
      const [lo, a] = S[i - 1], [hi, b] = S[i], t = (pct - lo) / (hi - lo);
      return rgb(a.map((x, k) => Math.round(x + (b[k] - x) * t)));
    }
  }
  return rgb(S[S.length - 1][1]);
}

export function MiniArea({ points, h, times, range, cap }) {
  const [hov, setHov] = useState(null);
  const wref = useRef(null);
  const pts = (points || []).filter(v => v != null);
  h = h || 42; const w = 100;
  const n = pts.length;
  // x-axis holds `cap` blocks (the ring's full capacity); data is pinned to the RIGHT edge and
  // grows leftward as blocks arrive, so a fresh node fills one block at a time instead of stretching.
  const C = Math.max(cap || n || 1, 2);
  const xAt = i => w - (n - 1 - i) * (w / (C - 1));
  const TS = times || [];
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
      label=${histTime(TS[hov], range) + " · " + Math.round(pts[hov]) + "%"}/>` : null}
  </div>`;
}

// Throughput history: rx as a filled area + tx as a line, scaled to the series max.
export function ThroughputChart({ rx, tx, h, head, times, range, cap }) {
  const [hov, setHov] = useState(null);
  const wref = useRef(null);
  // Perspective is applied HERE (once, centrally) so every caller can pass raw node rx/tx and the ↓ series
  // always means "download in the active perspective" — node-side by default, user-side when set to peers.
  const _pov = (Store.panelSettings || {}).throughput_perspective === "peers";
  const dnArr = _pov ? tx : rx, upArr = _pov ? rx : tx;
  const R = (dnArr || []).map(v => v || 0), TS = (upArr || []).map(v => v || 0);
  const n = Math.max(R.length, TS.length);
  const curR = R[R.length - 1] || 0, curT = TS[TS.length - 1] || 0;
  const hi = n ? Math.max(0, ...R, ...TS) : 0;
  // DYNAMIC y-scale from the DISPLAYED peak (this range's series, not a global/hour peak): ceiling = the nearest
  // 1/5/10/50/100/500×unit above the peak, with ≥15% headroom baked in via peak/0.85 (so a peak sitting within
  // 15% of a ceiling takes the next one up). Reflects real magnitude without stretching a tiny peak to fill height.
  const scaleMax = niceScaleCeil(Math.max(hi, 1024) / 0.85);
  const scaleLabel = rate(scaleMax);
  const legend = html`<div class="tp-legend"><span class="tp-k"><i class="sw rx"></i>↓ ${rate(curR)}</span><span class="tp-k"><i class="sw tx"></i>↑ ${rate(curT)}</span><span class="tp-peak">${T("peak {v1}", { v1: rate(hi) })}</span><span class="tp-scale" title=${T("Vertical scale — nearest 1/5/10/50/100/500 unit above the peak (≥15% headroom)")}>${scaleLabel}</span><span class="grow"></span>${head || null}</div>`;
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
  const TSX = times || [];
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
        <polyline points=${line(TS)} fill="none" stroke="var(--tp-tx)" stroke-width="1.3" vector-effect="non-scaling-stroke" stroke-dasharray="3 2"/>` : null}
      </svg>
      ${n === 1 ? html`<div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(R[0]) / h * 100) + "%;background:var(--tp-rx)"}></div>
        <div class="ch-dot" style=${"left:" + xAt(0) + "%;top:" + (Y(TS[0]) / h * 100) + "%;background:var(--tp-tx)"}></div>` : null}
      ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xAt(hov)}
        dots=${[{ yp: Y(R[hov] || 0) / h * 100, color: "var(--tp-rx)" }, { yp: Y(TS[hov] || 0) / h * 100, color: "var(--tp-tx)" }]}
        label=${histTime(TSX[hov], range) + " · ↓ " + rate(R[hov] || 0) + " · ↑ " + rate(TS[hov] || 0)}/>` : null}
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
export function MultiRing({ rings, size, thick, gap, center, active, onActive }) {
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
  // The arrow comes from the ring's own `dir`, never from its label text — the label is translated, and
  // inferring direction from words is a coupling that breaks silently in every language but English.
  const arrowOf = dir => dir === "dn" ? "↓ " : dir === "up" ? "↑ " : "";
  // an arc is LIT when it matches the active key AND (whole-entity hover, or its exact ring)
  const lit = a => active && a.seg.key === active.key && (active.dir == null || a.ri === active.dir);
  const set = t => onActive && onActive(t);
  // ── centre readout while hovering ──
  let readout = center;
  if (active) {
    const ea = arcs.filter(a => !a.track && a.seg && a.seg.key === active.key).sort((p, q) => p.ri - q.ri);
    if (ea.length) {
      const nm = ea[0].seg.name, col = ea[0].seg.color;
      const valLine = a => html`<div class="mrc-val" style=${a.ring.unitColor ? "color:" + a.ring.unitColor : ""}>${arrowOf(a.ring.dir)}${(a.ring.fmt || (v => v))(a.seg.value)}</div>`;
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
export function RingLegend({ items, cols, active, onActive }) {
  const set = t => onActive && onActive(t);
  return html`<div class=${"mring-leg" + (cols ? " c" + cols : "")}>${(items || []).map(it => {
    const k = it.key || it.name;
    const on = active && active.key === k, rowDim = active && active.key !== k, hasDU = it.down != null;
    return html`<div class=${"mrl-row" + (rowDim ? " dim" : "") + (on ? " on" : "")} key=${k}
        onMouseEnter=${() => set({ key: k, dir: null })} onMouseLeave=${() => set(null)}>
      <span class="mrl-sw" style=${"--sw:" + it.color}></span>
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
export function OnlineBlocks({ blocks, step, endTs, range, h, color }) {
  const [hov, setHov] = useState(null); const wref = useRef(null);
  color = color || "var(--online)"; h = h || 70;
  const n = blocks.length, hi = Math.max(1, ...blocks.filter(v => v != null));
  const onMove = e => { const el = wref.current; if (!el) return; const r = el.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left) / r.width * n); setHov(i >= 0 && i < n && blocks[i] != null ? i : null); };
  return html`<div class="oblk-wrap" ref=${wref} style=${"height:" + h + "px"} onMouseMove=${onMove} onMouseLeave=${() => setHov(null)}>
    ${blocks.map((v, i) => html`<div class=${"oblk" + (hov === i ? " hot" : "")} key=${i}>
      ${v == null ? null : html`<i style=${"height:" + Math.max(4, v / hi * 100) + "%;background:" + color}></i>`}</div>`)}
    ${hov != null ? html`<${ChartHover} xp=${(hov + 0.5) / n * 100} dots=${[{ yp: 100 - Math.max(4, blocks[hov] / hi * 100), color }]}
      label=${(endTs != null ? histTime(endTs - (n - 1 - hov) * step, range) + " · " : "") + T("{v1} online", { v1: Math.round(blocks[hov]) })}/>` : null}
  </div>`;
}
// A simple single-colour filled-area trend (for count series like online-peers, where MiniArea's
// load-colour ramp would be semantically wrong). Fixed y-scale from 0 to the series peak; right-anchored
// and fills leftward like the other charts; hover shows the value via `fmt`.
export function TrendArea({ points, times, color, h, cap, fmt, range, label }) {
  const [hov, setHov] = useState(null); const wref = useRef(null);
  const pts = (points || []).map(v => v || 0); h = h || 46; const w = 100, n = pts.length;
  color = color || "var(--online)"; fmt = fmt || (v => v);
  const C = Math.max(cap || n || 1, 2), xAt = i => w - (n - 1 - i) * (w / (C - 1)), TS = times || [];
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
    ${(hov != null && hov < n) ? html`<${ChartHover} xp=${xy[hov][0]} dots=${[{ yp: xy[hov][1] / h * 100, color }]} label=${histTime(TS[hov], range || "live") + " · " + fmt(pts[hov]) + (label ? " " + label : "")}/>` : null}
  </div>`;
}

// A ranked horizontal-bar list. rows: [{label, value, sub, color, href}].
export function RankBars({ rows }) {
  const mx = Math.max(1, ...rows.map(r => r.value || 0));
  if (!rows.length) return html`<div class="harea-empty">${T("no data")}</div>`;
  return html`<div class="rankbars">${rows.map(r => {
    const inner = html`<span class="rb-label"><span class="rb-nm">${r.label}</span>${r.count > 1 ? html`<span class="rb-n" title=${T("{v1} peers", { v1: r.count })}>${r.count}</span>` : ""}</span>
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
      : html`<div class=${T("{v1} static", { v1: cls })} key=${r.label}>${inner}${bub}</div>`;
  })}</div>`;
}

// A history chart (CPU or throughput) with live/day/week/month range tabs. "live" uses the
// series already in /api/state; day/week/month are fetched on demand from /api/node-history.
export const HIST_RANGES = ["live", "hour", "day", "week", "month"];
// blocks (= slots = plotted points) each range's x-axis holds — must match swg-panel-server
// HRRD_RINGS slot counts (live = LIVE_MAX). Charts pin data to the right and fill leftward.
export const RANGE_CAP = { live: 200, hour: 250, day: 300, week: 350, month: 400 };
// Seconds each range covers — mirrors the panel's RANGE_SPEC windows. Only used to work out how many samples
// a window can hold at a series' real resolution (densityCap).
export const RANGE_WIN = { live: 200 * 15, hour: 3600, day: 86400, week: 7 * 86400, month: 30 * 86400 };

/* How many slots this range's x-axis should hold FOR THIS SERIES.

   RANGE_CAP assumes a series folded once per its ring's step. A source that writes less often can never
   reach that count, and the chart — which right-anchors a partly-filled ring on purpose, so it fills from
   the right as blocks arrive — would then sit pinned at a fraction of the width for ever. The mesh pair ring
   is exactly that: it folds at most once a minute into a 15s ring, so live and hour topped out at a quarter
   width no matter how long the link had been up.

   So derive the capacity from the spacing the series actually has. A ring that is merely still filling is
   unaffected: its samples are correctly spaced, so C comes out right and the short series keeps
   right-anchoring — a month graph on a 13-day-old file still reads as 13 days of a 30-day window. */
export function densityCap(times, range) {
  const fallback = RANGE_CAP[range] || 0, win = RANGE_WIN[range];
  const t = (times || []).filter(x => x != null);
  if (!win || t.length < 3) return fallback;
  const gaps = [];
  for (let i = 1; i < t.length; i++) { const d = t[i] - t[i - 1]; if (d > 0) gaps.push(d); }
  if (!gaps.length) return fallback;
  gaps.sort((a, b) => a - b);
  const step = gaps[Math.floor(gaps.length / 2)];   // median: one long gap from a restart must not widen the axis
  if (!step) return fallback;
  // never exceed the designed block count — this only ever narrows the axis to what the data can fill
  return Math.max(2, Math.min(fallback, Math.round(win / step)));
}
export const tailSeries = (s, n) => { const o = {}; for (const k of ["t", "cpu", "mem", "disk", "rx", "tx", "mrx", "mtx"]) if (Array.isArray((s || {})[k])) o[k] = s[k].slice(-n); return o; };

// The live/hour/day/week/month picker. Rendered inside the chart by default, or lifted into a panel header
// (controlled `range`/`setRange`) so Health/Throughput can host it up top.
export function RangeTabs({ range, setRange }) {
  // The key stays raw everywhere it carries identity (the active class, the value handed to setRange);
  // only the LABEL is spelled out, through the same rangeLabel() the Overview's picker uses — so the two
  // pickers can never drift into two different words for the same range.
  return html`<div class="rangetabs">${HIST_RANGES.map(t => html`<button class=${"rtab" + (range === t ? " on" : "")} onClick=${() => setRange(t)}>${rangeLabel(t)}</button>`)}</div>`;
}
export function RangedHistory({ node, kind, live, h, head, liveFine, fetch, traf, range: cRange, setRange: cSetRange }) {
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
  const cap = custom ? densityCap(s.t, range) : range === "live" ? (liveBuf ? RANGE_CAP.live : 0) : RANGE_CAP[range];
  const hasData = (s.cpu || s.rx || []).some(x => x != null);
  const nlive = Store.recon.nodeStatus[node] === "live";   // node hasn't reported for several rounds → the live feed is frozen
  // A node that stops reporting (update / re-install / convert / brief outage) must NEVER blank the
  // chart — the data already collected stays on screen, flagged with a small "paused" pill.
  const notLive = !nlive && (range === "live" || range === "hour");   // only the live-fed ranges; day/week/month keep their stored history
  const pausedPill = (notLive && hasData) ? html`<span class="rt-paused" title=${T("This node isn't reporting right now — showing the last data it sent.")}>${T("tag|paused")}</span>` : null;
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

// Interface throughput panel (interface-detail screen): range picker hoisted into the header, like the node graph.
export function IfaceThroughput({ node, iface }) {
  const [range, setRange] = useState("live");
  return html`<${Panel} icon="gauge" title=${T("Throughput")} actions=${html`<${RangeTabs} range=${range} setRange=${setRange}/>`}>
    <${RangedHistory} node=${node} kind="throughput" h=${72} fetch=${r => api.ifaceSeries(node, iface, r).then(x => x && x.ok ? x.data : {})} range=${range} setRange=${setRange}/>
  <//>`;
}
