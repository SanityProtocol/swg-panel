/* logview.js — Settings → Logs, the live viewer (docs/LOGS-PLAN.md §3, §5, §23).
 *
 * LAYER 10: a leaf screen part that only Settings renders. Pick servers (the Panel first) and sources (grouped, a
 * three-state box per group), and see ONE stream, merged and sorted by each line's own time on the panel's clock (a node
 * whose clock is off is corrected, and its chip says by how much). Nothing is pulled from any node while nobody watches:
 * the viewer opens a request on the panel and renews it with every poll (1.5 s, only while this tab is visible); the
 * panel asks the nodes through their sync reply, and they stop by themselves ~20 s after the polls stop.
 *
 * Its state is module-level (LV), not component state: the 5 s Store poll re-renders Settings, and a viewer that lost
 * its lines, its facets or its scroll on every re-render would be useless. 5 000 lines at most, rendered as a window —
 * blocks of 64 lines, only those near the viewport in the DOM, their heights measured (Wrap makes rows uneven).
 */

import { T, plural } from "./i18n.js";
import { Store, api, useStore } from "./store.js";
import { Ic, Popover, goSettings } from "./ui.js";
import { downloadConf } from "./crypto.js";
import { h, Fragment } from "preact";
import { useState, useRef, useEffect, useLayoutEffect } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

const POLL_MS = 1500, BUF = 5000, BLOCK = 64, ROW_H = 21;
export const LOG_PANEL = "panel";                   // the panel's own entry among the servers (the panel's id for it)
const PANEL_KINDS = ["panel", "sub", "netctl", "update"];
const LEVELS = ["err", "warn", "info", "debug"];
const levelLabel = k => ({ err: T("log|Errors"), warn: T("log|Warnings"), info: T("log|Info"), debug: T("log|Debug") })[k];
// a row's level, as journalctl names priorities: a token, not a word, and the same in every language
const LV_TOKEN = { err: "err", warn: "warn", info: "info", debug: "debug" };
const lvOf = p => p <= 3 ? "err" : p === 4 ? "warn" : p <= 6 ? "info" : "debug";
// a node's chip colour: a stable pick from the panel's own status/brand hues, so 200 chips still read apart
const CHIP = ["--brand", "--online", "--ready", "--pending", "--relay-2", "--smart", "--tport-os", "--partial", "--tport-dock", "--awg3"];
const chipOf = id => { let x = 0; for (const c of String(id)) x = (x * 31 + c.charCodeAt(0)) >>> 0; return "var(" + CHIP[x % CHIP.length] + ")"; };

// The viewer's state, kept across re-renders (see the header).
const LV = {
  nodes: null, src: null,                             // the facets; null = the defaults (see facetDefaults)
  levels: { err: true, warn: true, info: true, debug: true }, q: "", wrap: false, full: false, pick: "",
  req: null, seq: 0, h: "", states: {}, iv: 1, err: "", ver: 0,   // the panel's request and what it last said
  lines: [], frozen: null, missed: 0,                 // the merged lines; Paused: the list as it was, and what came since
  held: {},                                           // a reopen: the newest line each server already has here
  dirty: true, busy: false, timer: null, mounted: 0,
};
const _subs = new Set();
const bump = () => { LV.ver++; _subs.forEach(f => f(LV.ver)); };
const STORE_KEY = "swg-logview";
try { const s = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); if (s && Array.isArray(s.nodes) && Array.isArray(s.src)) Object.assign(LV, { nodes: s.nodes, src: s.src, wrap: !!s.wrap }); } catch (_) { /* private mode */ }
const remember = () => { try { localStorage.setItem(STORE_KEY, JSON.stringify({ nodes: LV.nodes, src: LV.src, wrap: LV.wrap })); } catch (_) { /* private mode */ } };

const panelBare = () => { const lp = (Store.panelSettings || {}).log_panel || {}; return !lp.docker && lp.err !== "nixos"; };
function facetDefaults() {
  const ns = Store.nodes || [];
  return { nodes: [LOG_PANEL, ...(ns.length <= 5 ? ns.map(n => n.id) : [])],
           src: [...(panelBare() ? PANEL_KINDS : ["panel"]), ...NODE_SOURCES] };
}
// the remembered servers that still exist (a deleted node would only make the panel refuse the request)
const nodesOf = () => { const have = new Set((Store.nodes || []).map(n => n.id));
  return (LV.nodes || facetDefaults().nodes).filter(id => id === LOG_PANEL || have.has(id)); };
const srcOf = () => LV.src || facetDefaults().src;

// what a node's own page opens the viewer with: everything of that node's, the kernel aside (it is the whole kernel log)
export const NODE_SOURCES = ["noded", "dns", "sni", "relay:*", "turn:*", "iface:*", "p2p"];
export const TURN_SOURCES = ["turn:*"];             // a node's turn proxies, WDTT and csqtt — every instance
/* Open the viewer from elsewhere (the node page, a failing turn proxy): Settings → Logs with these facets. */
export function openLogs({ nodes, src } = {}) {
  if (nodes) LV.nodes = nodes;
  if (src) LV.src = src;
  LV.dirty = true; LV.full = false; remember(); bump();
  goSettings("logs");
}

const nodeName = id => id === LOG_PANEL ? T("Panel") : ((Store.nodes || []).find(n => n.id === id) || {}).name || id;

// ── talking to the panel ──────────────────────────────────────────────────────────────────────────────────────────
function addLines(raw) {
  if (!raw || !raw.length) return;
  const off = id => ((LV.states[id] || {}).off || 0) * 1e6;
  // a reopened request backfills again: what each server already has on screen is not added twice
  const add = raw.map(([seq, nid, t, src, prio, text]) => ({ k: t - off(nid), seq, nid, src, prio, text }))
    .filter(x => x.src[0] === "!" || !(x.k <= (LV.held[x.nid] || -Infinity)));
  if (!add.length) return;
  const L = LV.lines;
  let prev = L.length ? L[L.length - 1].k : -Infinity, inOrder = true;
  for (const x of add) { if (x.k < prev) { inOrder = false; break; } prev = x.k; }
  L.push(...add);
  if (!inOrder) L.sort((a, b) => a.k - b.k || a.seq - b.seq);   // a late line (a slower node) goes where it belongs
  if (L.length > BUF) L.splice(0, L.length - BUF);
  if (LV.frozen) LV.missed += add.length;
}

async function tick() {
  if (LV.busy || !LV.mounted || document.hidden) return;
  if (LV.err === "refused" && !LV.dirty) return;      // the panel refused these facets: wait for another choice
  LV.busy = true;
  try {
    if (LV.dirty || !LV.req) {
      // New facets are a new stream. A reopen — the tab back in view, the panel restarted — goes on with the same one:
      // what is on screen and a Paused view stay, and the backfill's repeats are skipped (addLines).
      const fresh = LV.dirty;
      const r = await api.post("/api/logs/live", { nodes: nodesOf(), src: srcOf(), ...(LV.req ? { replace: LV.req } : {}) });
      LV.dirty = false;
      if (!r || !r.ok) { LV.req = null; LV.err = r && r.code === "bad_request" ? "refused" : (r && r.code) || "error"; }
      else if (!LV.mounted || document.hidden) api.post("/api/logs/live/close", { id: r.data.id }).catch(() => {});   // left meanwhile
      else {
        Object.assign(LV, { req: r.data.id, seq: 0, h: "", states: {}, iv: r.data.iv, err: "" });
        if (fresh) Object.assign(LV, { lines: [], frozen: null, missed: 0, held: {} });
        else { LV.held = {}; for (const l of LV.lines) if (l.src[0] !== "!" && !(l.k <= (LV.held[l.nid] || -Infinity))) LV.held[l.nid] = l.k; }
      }
    } else {
      const r = await api.get("/api/logs/live?id=" + LV.req + "&after=" + LV.seq + "&h=" + LV.h);
      if (!r || !r.ok) { if (r && r.code === "gone") LV.req = null; else LV.err = "error"; }
      else {
        const d = r.data;
        if (d.nodes) LV.states = d.nodes;
        LV.h = d.h; LV.seq = d.seq; LV.err = "";
        addLines(d.lines);
      }
    }
  } catch (_) { LV.err = "error"; }
  LV.busy = false;
  bump();
}
function closeReq() {
  if (LV.req) { const id = LV.req; LV.req = null; api.post("/api/logs/live/close", { id }).catch(() => {}); }
}
function onVisibility() { if (document.hidden) closeReq(); else tick(); }   // hidden: the nodes stop now, not in 20 s

// ── what the source picker offers: built from what the panel already knows (the node records' last reports) ──────
function sourceGroups(nodeIds) {
  const st = Store.stats || {}, inst = { relay: new Set(), turn: new Set(), iface: new Set() };
  for (const id of nodeIds) {
    const s = st[id] || {};
    for (const n of Object.keys(s.interfaces || {})) inst.iface.add(n);
    for (const n of Object.keys((s.relay || {}).ifaces || {})) inst.relay.add(n);
    for (const t of s.turn_proxies || []) if (t && t.service) inst.turn.add(String(t.service).replace(/^vk-turn-proxy-/, ""));
    for (const w of [...(s.wdtt || []), ...(s.csqtt || [])]) if (w && w.iface) inst.turn.add(w.iface);
  }
  const sorted = k => [...inst[k]].sort().map(n => ({ id: k + ":" + n, label: n }));
  const g = [];
  if (nodeIds.includes(LOG_PANEL)) g.push({ id: "g-panel", label: T("Panel"), items: (panelBare() ? PANEL_KINDS : ["panel"]).map(id => ({ id, label: srcLabel(id) })) });
  if (nodeIds.some(id => id !== LOG_PANEL)) {
    g.push({ id: "g-node", label: T("Node service"), items: [{ id: "noded", label: srcLabel("noded") }] });
    g.push({ id: "g-routing", label: T("Routing"), items: [{ id: "dns", label: srcLabel("dns") }, { id: "sni", label: srcLabel("sni") }] });
    g.push({ id: "relay", label: T("Relays"), wild: "relay:*", items: sorted("relay") });
    g.push({ id: "turn", label: T("Turn proxies"), wild: "turn:*", items: sorted("turn") });
    g.push({ id: "iface", label: T("Interfaces"), wild: "iface:*", items: sorted("iface") });
    g.push({ id: "g-fw", label: T("Firewall and kernel"), items: [{ id: "p2p", label: srcLabel("p2p") }, { id: "kernel", label: srcLabel("kernel") }] });
  }
  return g;
}
function srcLabel(id) {
  const [k, n] = String(id).split(":");
  const base = { panel: T("Panel"), sub: T("Subscription page"), netctl: T("Root helper"), update: T("Updates"), noded: "swg-noded",
                 dns: T("Smart DNS"), sni: T("SNI classifier"), p2p: T("P2P guard"), kernel: T("Kernel") }[k] || k;
  return n == null ? base : n === "*" ? base : n;
}

// ── the facet editors ─────────────────────────────────────────────────────────────────────────────────────────────
function setFacets(nodes, src) {
  if (nodes) LV.nodes = nodes;
  if (src) LV.src = src;
  LV.dirty = true; remember(); bump();
}

function ServerPicker() {
  const [q, setQ] = useState("");
  const sel = new Set(nodesOf());
  const all = [...(Store.nodes || [])].sort((a, b) => Store.byNode(a.id, b.id)).map(n => n.id);   // the panel's order, as everywhere
  const ql = q.trim().toLowerCase();
  const shown = [LOG_PANEL, ...all].filter(id => !ql || nodeName(id).toLowerCase().includes(ql));
  const allOn = all.length > 0 && all.every(id => sel.has(id)), someOn = all.some(id => sel.has(id));
  const toggle = id => { const s = new Set(sel); s.has(id) ? s.delete(id) : s.add(id); setFacets([...s]); };
  const toggleAll = () => { const s = new Set(sel); all.forEach(id => allOn ? s.delete(id) : s.add(id)); setFacets([...s]); };
  return html`<div class="lv-pick">
    <div class="lv-pick-head">
      <label class="lv-check"><input type="checkbox" checked=${allOn} ref=${el => el && (el.indeterminate = !allOn && someOn)} onChange=${toggleAll}/>
        <span>${T("All nodes")}</span><span class="faint">${all.length}</span></label>
      ${all.length > 8 ? html`<input class="lv-pick-q" value=${q} placeholder=${T("Find a server…")} aria-label=${T("Find a server…")} data-enter="self" onInput=${e => setQ(e.target.value)}/>` : null}
    </div>
    <div class="lv-pick-list">
      ${shown.map(id => html`<label class="lv-check" key=${id}><input type="checkbox" checked=${sel.has(id)} onChange=${() => toggle(id)}/>
        <span class="lv-chip" style=${"--lvc:" + chipOf(id)}>${nodeName(id)}</span></label>`)}
      ${!shown.length ? html`<div class="hint">${T("No server matches “{q}”.", { q })}</div>` : null}
    </div>
  </div>`;
}

function SourcePicker() {
  const sel = new Set(srcOf());
  const groups = sourceGroups(nodesOf());
  const put = s => setFacets(null, [...s]);
  return html`<div class="lv-pick lv-pick-src">
    ${groups.map(g => {
      const ids = g.items.map(i => i.id);
      const wildOn = g.wild && sel.has(g.wild);
      const on = id => wildOn || sel.has(id);
      const allOn = wildOn || (ids.length > 0 && ids.every(id => sel.has(id)));
      const someOn = !allOn && ids.some(id => sel.has(id));
      const toggleGroup = () => { const s = new Set(sel); [...ids, g.wild].filter(Boolean).forEach(id => s.delete(id));
        if (!allOn) { if (g.wild) s.add(g.wild); else ids.forEach(id => s.add(id)); } put(s); };
      const toggle = id => { const s = new Set(sel);
        if (wildOn) { s.delete(g.wild); ids.forEach(x => x !== id && s.add(x)); }
        else if (s.has(id)) s.delete(id); else { s.add(id); if (g.wild && ids.every(x => s.has(x))) { ids.forEach(x => s.delete(x)); s.add(g.wild); } }
        put(s); };
      return html`<div class="lv-group" key=${g.id}>
        <label class="lv-check lv-gl"><input type="checkbox" checked=${allOn} ref=${el => el && (el.indeterminate = someOn)} onChange=${toggleGroup}/>
          <span>${g.label}</span>${g.wild && g.items.length ? html`<span class="faint">${g.items.length}</span>` : null}</label>
        ${g.items.length && (!g.wild || g.items.length > 0) ? html`<div class="lv-gi">${g.items.map(i => html`<label class="lv-check" key=${i.id}>
          <input type="checkbox" checked=${on(i.id)} onChange=${() => toggle(i.id)}/><span>${i.label}</span></label>`)}</div>` : null}
      </div>`; })}
  </div>`;
}

// ── what the servers said (a few numbers, the names in a bubble — 2 or 200 servers alike) ───────────────────────────
function stateSummary() {
  const out = [], ids = nodesOf(), S = LV.states || {};
  const by = {};
  const add = (key, id) => (by[key] = by[key] || []).push(id);
  for (const id of ids) {
    const s = S[id];
    if (!s) continue;
    if (s.state !== "ok") { add(s.state, id); continue; }
    const st = s.st || {};
    const vals = Object.values(st);
    if (vals.length && vals.every(v => v === "absent")) add("none", id);
    for (const [src, v] of Object.entries(st)) {
      if (v === "off") add("off", id);
      else if (v === "noaccess") add("noaccess", id);
      else if (v === "unavailable") add("unavail:" + src.split(":")[0], id);
    }
    if (s.off) add("skew", id);
  }
  const uniq = a => [...new Set(a)];
  const say = {
    waiting: [T("Starting"), T("Asked: a server starts sending within a sync or two."), "faint"],
    noanswer: [T("No answer"), T("Asked, but nothing came back. Check that the server syncs and runs a current build."), "warn"],
    old: [T("Update the node"), T("This node's build is too old for the live viewer. Update it to see its logs."), "warn"],
    offline: [T("Offline"), T("Not reporting — nothing can be read until it is back."), "faint"],
    off: [T("Logging is off"), T("Logging is off, so nothing is stored to read. Pick a level above to see lines."), "warn"],
    noaccess: [T("No access yet"), T("The panel reads its own journal once it restarts after the update that added it to systemd-journal."), "warn"],
    none: [T("Nothing to read"), T("None of the chosen sources is on these servers."), "faint"],
    skew: [T("Clock off"), T("These servers' clocks differ from the panel's. Their lines are shown on the panel's clock."), "faint"],
  };
  for (const [key, list] of Object.entries(by)) {
    const u = uniq(list);
    let txt, tip, tone;
    if (key.startsWith("unavail:")) {
      const k = key.slice(8);
      txt = { iface: T("Interfaces: not on docker"), kernel: T("Kernel: not on docker"), p2p: T("P2P guard: not on docker") }[k] || T("Not on docker");
      tip = T("A docker node has no host journal to read these from."); tone = "faint";
    } else [txt, tip, tone] = say[key] || [key, "", "faint"];
    out.push({ key, txt, tip, tone, ids: u });
  }
  return out;
}

function StateChips() {
  const items = stateSummary();
  if (!items.length) return null;
  return html`<div class="lv-states">${items.map(it => html`<${Popover} key=${it.key} cls="lv-stw" popCls="lv-stpop"
    trigger=${html`<span class=${"lv-st t-" + it.tone}>${it.txt} <b>${it.ids.length}</b></span>`}>
    <div class="lv-stpop-t">${it.tip}</div>
    <div class="lv-stpop-n">${it.ids.slice(0, 24).map(id => html`<span class="lv-chip" style=${"--lvc:" + chipOf(id)}>${nodeName(id)}${it.key === "skew" ? " " + skewText((LV.states[id] || {}).off) : ""}</span>`)}
      ${it.ids.length > 24 ? html`<span class="faint">${T("and {n} more", { n: it.ids.length - 24 })}</span>` : null}</div>
  <//>`)}</div>`;
}
const skewText = s => !s ? "" : (s > 0 ? "+" : "−") + (Math.abs(s) >= 120 ? Math.round(Math.abs(s) / 60) + " min" : Math.abs(s) + " s");

// ── the stream ────────────────────────────────────────────────────────────────────────────────────────────────────
const pad = (n, w = 2) => String(n).padStart(w, "0");
const tzLabel = () => { const m = -new Date().getTimezoneOffset(); return "UTC" + (m >= 0 ? "+" : "−") + pad(Math.floor(Math.abs(m) / 60)) + ":" + pad(Math.abs(m) % 60); };
const hms = k => { const d = new Date(k / 1000); return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + "." + pad(d.getMilliseconds(), 3); };
const ymd = k => { const d = new Date(k / 1000); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };

function shownLines() {
  const base = LV.frozen || LV.lines, q = LV.q.trim().toLowerCase(), lv = LV.levels;
  return base.filter(l => l.src[0] === "!" || (lv[lvOf(l.prio)] && (!q || l.text.toLowerCase().includes(q)
    || l.src.toLowerCase().includes(q) || nodeName(l.nid).toLowerCase().includes(q))));
}

function Hi({ text, q }) {
  if (!q) return text;
  const lo = text.toLowerCase(), out = [];
  let i = 0, j;
  while ((j = lo.indexOf(q, i)) >= 0 && out.length < 40) { if (j > i) out.push(text.slice(i, j)); out.push(html`<mark>${text.slice(j, j + q.length)}</mark>`); i = j + q.length; }
  out.push(text.slice(i));
  return out;
}

function Row({ l, q }) {
  if (l.src[0] === "!") return html`<div class="lv-row lv-mark">
    <span class="lv-t" title=${ymd(l.k)}>${hms(l.k)}</span>
    <span class="lv-chip" style=${"--lvc:" + chipOf(l.nid)}>${nodeName(l.nid)}</span>
    <span class="lv-markt">${l.src === "!skip" ? T("{v1} lines skipped — narrow the sources or raise the filter", { v1: Number(l.text).toLocaleString() })
      : T("Resumed — some lines before this may be missing")}</span>
  </div>`;
  const lv = lvOf(l.prio);
  return html`<div class=${"lv-row lv-" + lv}>
    <span class="lv-t" title=${ymd(l.k)}>${hms(l.k)}</span>
    <span class="lv-chip" style=${"--lvc:" + chipOf(l.nid)}>${nodeName(l.nid)}</span>
    <span class="lv-src">${l.src}</span>
    <span class="lv-lv">${LV_TOKEN[lv]}</span>
    <span class="lv-msg"><${Hi} text=${l.text} q=${q}/></span>
  </div>`;
}

function Stream({ lines, follow, onUserScroll }) {
  const box = useRef(null), hts = useRef(new Map()), [, setTick] = useState(0), st = useRef({ top: 0, h: 480, raf: 0 });
  const q = LV.q.trim().toLowerCase();
  const nb = Math.ceil(lines.length / BLOCK);
  const est = i => Math.min(BLOCK, lines.length - i * BLOCK) * ROW_H;
  const hOf = i => { const m = hts.current.get(i); return m && m.n === Math.min(BLOCK, lines.length - i * BLOCK) && m.w === LV.wrap ? m.h : est(i); };
  let y = 0, first = -1, last = -1, top = 0;
  const lo = st.current.top - 600, hi = st.current.top + st.current.h + 600;
  for (let i = 0; i < nb; i++) { const hh = hOf(i); if (y + hh >= lo && y <= hi) { if (first < 0) { first = i; top = y; } last = i; } y += hh; }
  let below = 0;
  for (let i = last + 1; i < nb; i++) below += hOf(i);
  useLayoutEffect(() => {
    const el = box.current; if (!el) return;
    let moved = false;
    el.querySelectorAll(".lv-blk").forEach(b => { const i = +b.dataset.i, n = b.childElementCount, hh = b.offsetHeight;
      const m = hts.current.get(i); if (!m || m.h !== hh || m.n !== n || m.w !== LV.wrap) { hts.current.set(i, { h: hh, n, w: LV.wrap }); moved = true; } });
    if (follow) el.scrollTop = el.scrollHeight;
    st.current.h = el.clientHeight;
    if (moved) setTick(t => t + 1);
  });
  const onScroll = () => {
    const el = box.current; if (!el) return;
    st.current.top = el.scrollTop; st.current.h = el.clientHeight;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    onUserScroll(atEnd);
    if (!st.current.raf) st.current.raf = requestAnimationFrame(() => { st.current.raf = 0; setTick(t => t + 1); });
  };
  const blocks = [];
  for (let i = first; i >= 0 && i <= last; i++) blocks.push(html`<div class="lv-blk" data-i=${i} key=${i}>
    ${lines.slice(i * BLOCK, (i + 1) * BLOCK).map(l => html`<${Row} key=${l.nid + l.seq} l=${l} q=${q}/>`)}</div>`);
  // one column width for every row (each row is its own grid): the longest server name and source shown, in characters
  let cw = 4, sw = 4;
  for (const l of lines) { if (l.src.length > sw) sw = l.src.length; }
  for (const id of nodesOf()) { const n = nodeName(id).length; if (n > cw) cw = n; }
  const cols = "--lv-cw:" + (Math.min(cw, 18) + 2) + "ch;--lv-sw:" + (Math.min(sw, 22) + 1) + "ch";
  return html`<div class=${"lv-stream" + (LV.wrap ? " wrap" : "")} style=${cols} ref=${box} onScroll=${onScroll} role="log" aria-live="off" aria-label=${T("Live logs")}>
    <div style=${"height:" + top + "px"}></div>${blocks}<div style=${"height:" + below + "px"}></div>
  </div>`;
}

function download(lines) {
  const ids = nodesOf(), tz = tzLabel();
  const head = ["# swg logs — " + new Date().toISOString(), "# servers: " + ids.map(nodeName).join(", "), "# sources: " + srcOf().join(", "),
    "# levels shown: " + LEVELS.filter(k => LV.levels[k]).join(", ") + (LV.q ? " · search: " + LV.q : ""),
    "# panel " + ((Store.versions || {}).panel || ""), ""];
  const nw = Math.min(24, Math.max(...ids.map(id => nodeName(id).length), 4)), sw = Math.min(28, Math.max(6, ...lines.map(l => l.src.length)));
  const body = lines.map(l => l.src === "!skip" ? "--- " + l.text + " lines skipped on " + nodeName(l.nid)
    : l.src === "!gap" ? "--- " + nodeName(l.nid) + " resumed: lines before this may be missing"
    : ymd(l.k) + " " + hms(l.k) + " " + tz + "  " + nodeName(l.nid).padEnd(nw) + "  " + l.src.padEnd(sw) + "  " + lvOf(l.prio).toUpperCase().padEnd(5) + "  " + l.text);
  const d = new Date();
  downloadConf(head.concat(body).join("\n") + "\n", "swg-logs-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + "-" + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()), "log");
}

// ── the viewer ────────────────────────────────────────────────────────────────────────────────────────────────────
export function LogViewer() {
  useStore();
  const [, setV] = useState(0);
  useEffect(() => {
    _subs.add(setV);
    LV.mounted++;
    if (LV.mounted === 1) { LV.timer = setInterval(tick, POLL_MS); document.addEventListener("visibilitychange", onVisibility); tick(); }
    return () => { _subs.delete(setV); LV.mounted--;
      if (!LV.mounted) { clearInterval(LV.timer); document.removeEventListener("visibilitychange", onVisibility); closeReq(); LV.full = false; } };
  }, []);
  useEffect(() => {
    if (!LV.full) return;
    const k = e => { if (e.key === "Escape") { LV.full = false; bump(); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [LV.full]);
  const lines = shownLines();
  const counts = { err: 0, warn: 0, info: 0, debug: 0 };
  for (const l of (LV.frozen || LV.lines)) if (l.src[0] !== "!") counts[lvOf(l.prio)]++;
  const ids = nodesOf(), srcs = srcOf();
  const off = ((Store.panelSettings || {}).log_level || "info") === "off";
  const paused = !!LV.frozen;
  const pause = () => { if (!LV.frozen) { LV.frozen = LV.lines.slice(); LV.missed = 0; bump(); } };
  const resume = () => { LV.frozen = null; LV.missed = 0; bump(); };
  const nodeLbl = ids.length === 1 ? nodeName(ids[0]) : ids.includes(LOG_PANEL) && ids.length > 1
    ? T("Panel and {n}", { n: plural(ids.length - 1, "server") }) : plural(ids.length, "server");
  const empty = !ids.length || !srcs.length ? T("Pick at least one server and one source.")
    : LV.err === "busy" ? T("Four log viewers are open already. Close one, or wait a few seconds for a closed tab's to lapse.")
    : LV.err === "refused" ? T("None of the chosen servers can be watched. Pick again.")
    : !LV.req ? T("Connecting…")
    : !(LV.frozen || LV.lines).length ? (off ? T("Logging is off, so nothing is stored to read.") : T("Waiting for lines…"))   // Off: the system journal's (interfaces, kernel) still come
    : !lines.length ? T("Nothing matches the filter.") : "";
  const card = html`<div class=${"card lv" + (LV.full ? " lv-full" : "")} role=${LV.full ? "dialog" : null} aria-modal=${LV.full ? "true" : null} aria-label=${T("Live logs")}>
    <div class="lv-head">
      <div class="seclabel" style="margin:0">${T("Live logs")}</div>
      <span class="lv-tz faint" title=${T("Times are this browser's, on the panel's clock")}>${tzLabel()}</span>
      <span class="grow"></span>
      <button class="btn btn-mini ico" title=${LV.full ? T("Leave full screen (Esc)") : T("Full screen")} aria-label=${LV.full ? T("Leave full screen (Esc)") : T("Full screen")}
        onClick=${() => { LV.full = !LV.full; bump(); }}>${LV.full
          ? html`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>`
          : html`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>`}</button>
    </div>
    <div class="lv-facets">
      <button class=${"lv-facet" + (LV.pick === "nodes" ? " on" : "")} aria-expanded=${LV.pick === "nodes"} onClick=${() => { LV.pick = LV.pick === "nodes" ? "" : "nodes"; bump(); }}>
        <${Ic} i="server"/><span class="lv-fl">${T("Servers")}</span><span class="lv-fv">${nodeLbl}</span></button>
      <button class=${"lv-facet" + (LV.pick === "src" ? " on" : "")} aria-expanded=${LV.pick === "src"} onClick=${() => { LV.pick = LV.pick === "src" ? "" : "src"; bump(); }}>
        <${Ic} i="doc"/><span class="lv-fl">${T("Sources")}</span><span class="lv-fv">${plural(srcs.length, "source")}</span></button>
      <${StateChips}/>
    </div>
    ${LV.pick === "nodes" ? html`<${ServerPicker}/>` : LV.pick === "src" ? html`<${SourcePicker}/>` : null}
    <div class="lv-bar">
      <div class="lv-levels" role="group" aria-label=${T("Levels shown")}>${LEVELS.map(k => html`<button type="button" key=${k}
        class=${"lv-lvb lv-" + k + (LV.levels[k] ? " on" : "")} aria-pressed=${LV.levels[k]} onClick=${() => { LV.levels[k] = !LV.levels[k]; bump(); }}>
        ${levelLabel(k)} <span class="lv-n">${counts[k]}</span></button>`)}</div>
      <div class="search lv-q"><${Ic} i="search"/><input value=${LV.q} placeholder=${T("Search the lines…")} aria-label=${T("Search the lines…")} data-enter="self"
        onInput=${e => { LV.q = e.target.value; bump(); }}/></div>
      <span class="grow"></span>
      <button class=${"btn btn-mini" + (paused ? " lv-paused" : "")} onClick=${paused ? resume : pause} title=${paused ? T("Back to the newest lines, following") : T("Hold the list still")}>
        <${Ic} i=${paused ? "play" : "stop"}/> ${paused ? (LV.missed ? T("Resume · {n} new", { n: LV.missed.toLocaleString() }) : T("Resume")) : T("Pause")}</button>
      <button class=${"btn btn-mini" + (LV.wrap ? " on" : "")} aria-pressed=${LV.wrap} onClick=${() => { LV.wrap = !LV.wrap; remember(); bump(); }}>${T("Wrap")}</button>
      <button class="btn btn-mini" onClick=${() => { LV.lines = []; LV.frozen = LV.frozen ? [] : null; LV.missed = 0; bump(); }}>${T("Clear")}</button>
      <button class="btn btn-mini" disabled=${!lines.length} onClick=${() => download(lines)} title=${T("The lines shown, as a text file")}><${Ic} i="download"/> ${T("Download")}</button>
    </div>
    ${empty ? html`<div class="lv-empty">${empty}</div>` : html`<${Stream} lines=${lines} follow=${!paused}
      onUserScroll=${atEnd => { if (!atEnd && !LV.frozen) pause(); }}/>`}
    <div class="lv-foot faint">${LV.frozen
      ? T("Paused — {v1} lines held", { v1: (LV.frozen.length).toLocaleString() })
      : T("{v1} of the last {v2} lines", { v1: lines.length.toLocaleString(), v2: BUF.toLocaleString() })}</div>
  </div>`;
  return LV.full ? html`<${Fragment}><div class="card lv lv-ph"><div class="lv-empty">${T("Shown full screen — Esc returns it here.")}</div></div>${card}<//>` : card;
}
