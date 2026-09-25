/* Self-test: the traffic totals the operator sees (docs/TRAFFIC-HISTORY-PLAN.md P2, §9.1) — the SPA half.
 *
 * Each rule here is silent when broken: nothing errors, a number is just wrong, or a request goes out every 5 s.
 *   [1] foldTotals     one `by=slot` reply feeds every grid: a peer's figure is the whole device (every owner it had), a
 *                      user's is every slot they held (a device deleted or handed on included), and a user's own list reads
 *                      what each device carried while it was theirs — so the list adds up to the user's row.
 *   [2] fetch cost     never per poll: a window is fetched once, "until now" at most once a minute, a window that ended
 *                      before the panel's today never again.
 *   [3] panelToday     the panel's zone, not the browser's — a custom window is capped at the panel's day.
 *   [4] volumeColumns  hundreds of fine buckets fold into ≤ 120 columns over the WHOLE window; nothing is lost or moved.
 *   [5] sort + freeze  PEER_SORT.rtotal / USER_SORT.rtotal are lookups; a sort by ranged total rendered before the totals
 *                      landed must not keep its all-zero order (stableOrder), and must not reshuffle every minute either.
 *   [6] orientation    every new total goes through dlul() — xferCell does not apply Throughput perspective itself.
 *   [7] settings       the Data section's third half: the display arm of glDirty, the payload, the diff lines.
 *
 * Run: node tests/spa_traffic_selftest.mjs                 (0 = pass)
 *      node tests/spa_traffic_selftest.mjs --plant <name>  breaks one rule on purpose; exits 0 only if a check went red.
 *      plants: fold ttl immutable today cols freeze owner dlul settings draft window nodata tzcache lazy lazyuser dst
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, FAILS } from "./spa_env.mjs";

const PLANT = process.argv.includes("--plant") ? process.argv[process.argv.indexOf("--plant") + 1] : "";
const PLANTS = {   // name: [file, anchor, replacement]
  fold: ["traffic.js", `add(slot, uid + "|" + r.id, r, {`, `add(slot, "|" + r.id, r, {`],
  ttl: ["traffic.js", "const TTL_MS = 60000;", "const TTL_MS = -1;"],
  immutable: ["traffic.js", `return v.range === "custom" && !!v.from && !!v.to && v.to < (today || panelToday());`, "return false;"],
  today: ["traffic.js", `const off = typeof tz.offset === "number" ? tz.offset : -new Date().getTimezoneOffset() * 60;`, "const off = 0;"],
  cols: ["traffic.js", "const k = Math.max(1, Math.ceil(span / step0 / max));", "const k = 1;"],
  freeze: ["views.js", `const rtotalTag = sort => sort === "rtotal" ? "|" + trafficFreezeTag() : "";`, `const rtotalTag = sort => "";`],
  owner: ["views.js", `rtotal: ({ p, o }) => { const a = peerTraffic(p.id, o);`, `rtotal: ({ p, o }) => { const a = peerTraffic(p.id);`],
  dlul: ["traffic-ui.js", "const cell = xferCell(...dlul(rx, tx));", "const cell = xferCell(rx, tx);"],
  draft: ["traffic-ui.js", "onInput=${e => setDraft({ ...dr, [k]: e.target.value })}", "onInput=${e => { trafficView[k] = e.target.value; setDraft({ ...dr, [k]: e.target.value }); }}"],
  window: ["traffic.js", "  const t = to > today ? today : to;\n  if (from > t)", "  const t = to > today ? today : to;\n  if (from > to)"],
  nodata: ["screen-settings.js", "const d = u && u.on ? u : null;", "const d = u || {};"],
  tzcache: ["screen-settings.js", "if (dataDirty() || tzDirty()) trafficInvalidate();", "if (dataDirty()) trafficInvalidate();"],
  dst: ["traffic.js", "  const byDay = !pts.length || pts.every(p => (p[1] || 86400) >= 82800);", "  const byDay = false;"],
  lazy: ["traffic-ui.js", "trigger=${cell}><${TrafficBubble} a=${a} rx=${rx} tx=${tx} ctx=${ctx} user=${user}/><//>`;", "trigger=${cell}>${TrafficBubble({ a, rx, tx, ctx, user })}<//>`;"],
  lazyuser: ["traffic-ui.js", "  return html`<${TrafficCell} a=${userTraffic(uid)} e=${trafficTotals()} user=${uid}/>`;",
    "  const d0 = trafficData(); if (d0) goneDevices(uid, d0);\n  return html`<${TrafficCell} a=${userTraffic(uid)} e=${trafficTotals()} user=${uid}/>`;"],
  settings: ["screen-settings.js", `sec === "display" ? (dispDirty() || tzDirty() || dataDirty()) :`, `sec === "display" ? (dispDirty() || tzDirty()) :`],
};
const written = [];
// A planted module is a sibling copy in js/ (relative imports keep working) — removed at the end, whatever happens.
function load(file) {
  const p = PLANTS[PLANT];
  if (!p || p[0] !== file) return import(pathToFileURL(path.join(ROOT, "js", file)).href);
  const src = fs.readFileSync(path.join(ROOT, "js", file), "utf8");
  if (src.split(p[1]).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would FALSE-PASS: " + p[1]); process.exit(1); }
  const out = path.join(ROOT, "js", ".plant_" + file.replace(/\.js$/, ".mjs"));
  fs.writeFileSync(out, src.replace(p[1], p[2]));
  written.push(out);
  return import(pathToFileURL(out).href);
}
const src = f => {
  const s = fs.readFileSync(path.join(ROOT, "js", f), "utf8"), p = PLANTS[PLANT];
  return p && p[0] === f ? s.replace(p[1], p[2]) : s;
};

try {
  const { Store, api } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
  // views.js and traffic-ui.js import the REAL traffic.js; a traffic.js plant is read through its own copy below.
  const TR = await load("traffic.js");
  const V = await load("views.js");
  const TU = await load("traffic-ui.js");
  const realTR = await import(pathToFileURL(path.join(ROOT, "js", "traffic.js")).href);

  // ── the roster: Anna (u1) had p1 and handed it to Boris (u2); p3 was Anna's and is deleted; p2 is Boris's ──────────
  const peers = { p1: { id: "p1", title: "phone", user_id: "u2", targets: [] }, p2: { id: "p2", title: "laptop", user_id: "u2", targets: [] } };
  const users = { u1: { id: "u1", name: "Anna" }, u2: { id: "u2", name: "Boris" } };
  Store.peer = id => peers[id] || null;
  Store.user = id => users[id] || null;
  Store.panelSettings = { time_zone_now: { offset: 3 * 3600 }, throughput_perspective: "nodes" };
  const ROWS = [
    { id: "p1", owner: "u1", rx: 1000, tx: 100, lifetime_rx: 5000, lifetime_tx: 500, opening_rx: 4000, opening_tx: 400, opening_at: 100, since: 100, until: 200, name: "phone", owner_name: "Anna" },
    { id: "p1", owner: "u2", rx: 700, tx: 70, lifetime_rx: 700, lifetime_tx: 70, since: 200, until: null, name: "phone", owner_name: "Boris" },
    { id: "p2", owner: "u2", rx: 5, tx: 5, lifetime_rx: 5, lifetime_tx: 5, since: 150, until: null, name: "laptop", owner_name: "Boris" },
    { id: "p3", owner: "u1", rx: 300, tx: 30, lifetime_rx: 300, lifetime_tx: 30, since: 120, until: 180, name: "old tablet", owner_name: "Anna" },
    { id: "p4", owner: "", rx: 9, tx: 9, lifetime_rx: 9, lifetime_tx: 9, since: 130, until: null, name: "spare", owner_name: "" },
  ];

  console.log("[1] one reply feeds every grid");
  const F = TR.foldTotals(ROWS);
  const s = a => a ? [a.rx, a.tx] : null;
  check("a peer's figure is the whole device — every owner it had", JSON.stringify(s(F.peer.get("p1"))) === "[1700,170]", s(F.peer.get("p1")));
  check("a user's figure is every slot they held — a device handed on and a deleted one included",
    JSON.stringify(s(F.user.get("u1"))) === "[1300,130]" && JSON.stringify(s(F.user.get("u2"))) === "[705,75]", [s(F.user.get("u1")), s(F.user.get("u2"))]);
  check("in a user's own list a device reads what it carried while it was theirs, and the list adds up to the user's row",
    JSON.stringify(s(F.slot.get("u1|p1"))) === "[1000,100]" && JSON.stringify(s(F.slot.get("u2|p1"))) === "[700,70]"
    && (F.rows.get("u1") || []).reduce((a, r) => a + r.rx, 0) === F.user.get("u1").rx, [s(F.slot.get("u1|p1")), s(F.slot.get("u2|p1"))]);
  check("an unassigned slot counts on the device, and on no user", F.peer.get("p4") && !F.user.has(""), [...F.user.keys()]);
  check("a lifetime keeps what was imported and when", F.peer.get("p1").opening_rx === 4000 && F.peer.get("p1").opening_at === 100
    && F.peer.get("p1").since === 100 && F.peer.get("p1").owners === 2, F.peer.get("p1"));
  check("a user's devices no longer theirs are counted (deleted or handed on)", TU.goneDevices("u1", F) === 2, TU.goneDevices("u1", F));

  console.log("[2] never per poll");
  let calls = [];
  const pending = [];
  api.get = p => { calls.push(p); return new Promise(res => pending.push(() => res({ ok: true, data: { rows: ROWS, from: 20260901, to: 20260924, since: 1, until: 2, gaps: {} } }))); };
  const flush = async () => { while (pending.length) pending.shift()(); await new Promise(r => setTimeout(r, 0)); };
  const month = { range: "month", from: "", to: "" };
  const t0 = Date.now();   // the cache stamps its fetches with the real clock
  for (let i = 0; i < 50; i++) TR.trafficTotals(month, t0 + i * 5000 / 50);   // 50 renders within one poll
  await flush();
  for (let i = 0; i < 11; i++) TR.trafficTotals(month, t0 + i * 5000);        // eleven 5 s polls: under a minute
  await flush();
  check("a window is fetched once, however many renders ask", calls.length === 1, calls);
  TR.trafficTotals(month, Date.now() + 61000);
  await flush();
  check("…and a window that runs until now at most once a minute", calls.length === 2, calls.length);
  check("…as rows per (peer, owner), never on /api/state", calls.every(c => c.startsWith("/api/traffic-totals?by=slot&")), calls);
  calls = [];
  const past = { range: "custom", from: "2026-08-01", to: "2026-08-31" };
  TR.trafficTotals(past); await flush();
  TR.trafficTotals(past, Date.now() + 10 * 60000); await flush();
  TR.trafficTotals(past, Date.now() + 24 * 3600000); await flush();
  check("a window that ended before the panel's today is fetched once, ever", calls.length === 1, calls);
  check("a custom window's query names its dates", TR.trafficQuery(past) === "range=custom&from=2026-08-01&to=2026-08-31"
    && TR.trafficQuery({ range: "custom", from: "", to: "" }) === "range=all", TR.trafficQuery(past));
  check("the grids' named windows ask the ledger for whole days: All time, Day, Week, Month",
    TR.trafficQuery({ range: "all" }) === "range=all" && TR.trafficQuery({ range: "today" }) === "range=today"
    && TR.trafficQuery({ range: "7d" }) === "range=7d" && TR.trafficQuery({ range: "30d" }) === "range=30d"
    && TR.trafficQuery({ range: "bogus" }) === "range=all", "");
  check("the grids open on All time, the peer, user and group windows on Week — their own window, never the grids'",
    TR.trafficView.range === "all" && TR.trafficModalView.range === "7d" && TR.trafficModalView !== TR.trafficView, [TR.trafficView, TR.trafficModalView]);

  console.log("[3] the panel's day, not the browser's");
  check("22:30 UTC is already tomorrow for a panel counting days in Moscow",
    TR.panelToday(Date.parse("2026-09-24T22:30:00Z")) === "2026-09-25", TR.panelToday(Date.parse("2026-09-24T22:30:00Z")));
  check("a window ending on the panel's today is not immutable; one ending yesterday is",
    !TR.trafficImmutable({ range: "custom", from: "2026-09-01", to: "2026-09-24" }, "2026-09-24")
    && TR.trafficImmutable({ range: "custom", from: "2026-09-01", to: "2026-09-23" }, "2026-09-24"), "");

  console.log("[4] the chart's columns");
  const since = 1790000000, H = 3600;
  const pts = [];
  for (let i = 0; i < 192; i++) if (i % 7) pts.push([since + i * H, H, 100 + i, i]);
  const cols = TR.volumeColumns(pts, since, since + 192 * H, 120);
  const sum = (a, k) => a.reduce((x, c) => x + (Array.isArray(c) ? c[k === "rx" ? 2 : 3] : c[k]), 0);
  check("192 hourly buckets fold into at most 120 whole-multiple columns, nothing lost",
    cols.length <= 120 && cols.length >= 60 && cols[0].step % H === 0 && sum(cols, "rx") === sum(pts, "rx") && sum(cols, "tx") === sum(pts, "tx"),
    [cols.length, cols[0] && cols[0].step]);
  const sparse = TR.volumeColumns([[since + 5 * 86400, 86400, 10, 1]], since, since + 30 * 86400, 120);
  const D = 86400, ds = [];
  for (let i = 0, t = since; i < 30; i++) { const len = i === 10 ? D - 3600 : i === 20 ? D + 3600 : D; ds.push([t, len, 1, 0]); t += len; }
  const dcols = TR.volumeColumns(ds, since, since + 30 * D, 120);
  check("a DST day (23 or 25 hours) is still one day: 30 day points make 30 columns, one in each",
    dcols.length === 30 && dcols.every(c => c.rx === 1 && c.step === D), [dcols.length, dcols.filter(c => c.rx !== 1).length]);
  check("columns cover the WHOLE window — one busy day of thirty is one column of thirty, in its place",
    sparse.length === 30 && sparse[5].rx === 10 && sparse.filter(c => c.rx).length === 1, sparse.length);

  console.log("[5] the sort key and the order freeze");
  // the real traffic module's cache drives views.js — fill it for this month's window
  calls = [];
  api.get = p => { calls.push(p); return new Promise(res => pending.push(() => res({ ok: true, data: { rows: ROWS, from: 1, to: 2, since: 1, until: 2, gaps: {} } }))); };
  realTR.trafficInvalidate();
  Object.assign(realTR.trafficView, { range: "30d", from: "", to: "" });
  const rows = ["p2", "p1", "p4"].map(id => ({ p: { id, title: id, targets: [] }, t: { node: "n1", iface: "awg0" } }));
  const before = V.sortPeerRows(rows, "rtotal", -1, "tgate").map(r => r.p.id);   // rendered before the totals land
  await flush();
  const after = V.sortPeerRows(rows, "rtotal", -1, "tgate").map(r => r.p.id);
  check("a sort by ranged total rendered before the totals landed is not frozen on zeros", after.join() === "p1,p4,p2", [before, after]);
  api.get = p => { calls.push(p); return new Promise(res => pending.push(() => res({ ok: true, data: { rows: ROWS.map(r => r.id === "p2" ? { ...r, rx: 10 ** 9 } : r), from: 1, to: 2, since: 1, until: 2, gaps: {} } }))); };
  realTR.trafficTotals(undefined, Date.now() + 61000); await flush();   // the minute's refresh: p2 is now the biggest
  const later = V.sortPeerRows(rows, "rtotal", -1, "tgate").map(r => r.p.id);
  check("…and a once-a-minute refresh does not reshuffle rows under the operator's eyes", later.join() === "p1,p4,p2", later);
  const own = [{ p: { id: "p1", targets: [] }, t: { node: "n1", iface: "a" }, o: "u2" }, { p: { id: "p2", targets: [] }, t: { node: "n1", iface: "a" }, o: "u2" }];
  const byOwner = V.PEER_SORT.rtotal(own[0]);
  check("in a user's own list the sort reads what the device carried while it was theirs", byOwner === 770, byOwner);
  const us = V.sortUsers([{ id: "u1", name: "Anna" }, { id: "u2", name: "Boris" }], "rtotal", -1).map(u => u.id);   // after the refresh: Boris's laptop moved 1 GB
  check("USER_SORT.rtotal ranks by the user's window, first click descending", us.join() === "u2,u1" && V.USER_DEFDIR.rtotal === -1 && V.PEER_DEFDIR.rtotal === -1, us);

  console.log("[6] every total through dlul");
  const text = n => n == null || typeof n === "boolean" ? "" : typeof n !== "object" ? String(n)
    : Array.isArray(n) ? n.map(text).join("") : text(n.props && n.props.children);
  Store.panelSettings = { ...Store.panelSettings, throughput_perspective: "peers" };
  const cell = TU.TrafficCell({ a: { rx: 1024, tx: 5 * 1024 * 1024, lifetime_rx: 0, lifetime_tx: 0 }, e: { data: {} } });
  const shown = text(cell.props.trigger);
  check("with Throughput perspective on the peers' side, a ranged total's ↓ is what the node sent",
    /↓\s*5\.0M/.test(shown) && /↑\s*1\.0K/.test(shown), shown);
  Store.panelSettings = { ...Store.panelSettings, throughput_perspective: "nodes" };
  let peerCalls = 0;
  const realPeer = Store.peer;
  Store.peer = id => { peerCalls++; return realPeer(id); };
  for (let i = 0; i < 20; i++) TU.UserTrafficCell({ uid: "u1" });   // a Users page of 20 rows, one poll
  Store.peer = realPeer;
  check("a user's row does not walk the user's devices unless its bubble opens", peerCalls === 0, peerCalls);
  const kid = cell.props.children;
  check("the bubble is a component Popover renders only when open — not built on every poll for every cell",
    kid && !Array.isArray(kid) && typeof kid.type === "function" && kid.type.name === "TrafficBubble", kid && (kid.type && kid.type.name || typeof kid));

  console.log("[7] the settings idiom's three halves");
  const ss = src("screen-settings.js");
  check("the display arm of glDirty carries the Data fields — or Save never enables for them",
    ss.includes(`sec === "display" ? (dispDirty() || tzDirty() || dataDirty()) :`)
    && /const dataDirty = \(\) => infHist !== \(ps\.infinite_history !== false\) \|\| histRes !== String\(ps\.history_resolution \|\| 3600\);/.test(ss), "");
  check("…the payload sends both, and the confirm list names both",
    ss.includes("infinite_history: infHist,") && ss.includes("history_resolution: +histRes || 3600,")
    && ss.includes(`if (infHist !== (ps.infinite_history !== false)) out.push(`) && ss.includes(`if (histRes !== String(ps.history_resolution || 3600)) out.push(`), "");

  console.log("[8] the review's findings");
  const tu = src("traffic-ui.js");
  const onInputs = [...tu.matchAll(/onInput=\$\{[^\n]*\n?/g)].map(m => m[0]);
  check("custom dates are this control's draft until Apply — a keystroke never reaches the shared window",
    tu.includes("onInput=${e => setDraft({ ...dr, [k]: e.target.value })}") && !onInputs.some(l => /trafficView/.test(l)), onInputs);
  const W = (f, t) => TR.customWindow(f, t, "2026-09-24");
  check("Apply takes a window only when both dates are whole, from 1970 on, and the start is not after the capped end",
    W("2026-09-01", "2026-09-24").ok && W("2026-09-01", "2026-12-31").to === "2026-09-24"
    && !W("2026-12-01", "2026-12-31").ok && W("2026-12-01", "2026-12-31").why === "future"
    && !W("2026-09-20", "2026-09-10").ok && W("2026-09-20", "2026-09-10").why === "order"
    && !W("0202-09-01", "2026-09-10").ok && !W("", "2026-09-10").ok,
    [W("2026-12-01", "2026-12-31"), W("2026-09-20", "2026-09-10"), W("0202-09-01", "2026-09-10")]);
  check("without a measurement (or with the ledger off) the OFF confirm never says nothing goes",
    ss.includes("const d = u && u.on ? u : null;")
    && ss.includes(`body: !d ? T("The panel will keep the traffic detail — each day's figures at the history resolution — for the last 33 days only. When you save, older detail is deleted and cannot be recovered.`), "");
  check("a zone change drops the cached totals — a past window counted in the old zone must not stay for the session",
    ss.includes("if (dataDirty() || tzDirty()) trafficInvalidate();"), "");
  const sr = src("screen-roster.js");
  // the row's own traffic button sits among its actions, which stay on screen at every width (the Total cell does not)
  check("(source) a double-click on a user's figure stays there, and a user row opens the user view on any width",
    sr.includes("onClick=${e => { e.stopPropagation(); openUserView(user.id); }} onDblClick=${e => e.stopPropagation()}")
    && sr.includes('onClick=${() => openUserView(user.id)}><${Ic} i="bars"/></button>'), "");
} finally {
  for (const f of written) try { fs.unlinkSync(f); } catch (_) { /* gone */ }
}

console.log("");
if (PLANT) {
  console.log("PLANT " + PLANT + ": " + (FAILS.length ? "CAUGHT — " + FAILS.join(" · ") : "NOT CAUGHT (every check passed with the defect in)"));
  process.exit(FAILS.length ? 0 : 1);
}
console.log(FAILS.length ? "FAIL: " + FAILS.join(", ") : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
