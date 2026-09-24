/* Self-test: Custom on the Overview (docs/TRAFFIC-HISTORY-PLAN.md P3, §8) — the SPA half.
 *
 * Each rule here is silent when broken: a volume reads 300–7200× too small, the last window's numbers render under the new
 * title, or a window in the past is polled for ever.
 *   [1] the key       a custom window travels as its KEY ("custom:YYYYMMDD-YYYYMMDD", the server's rangeKey), never as the
 *                     bare word: two windows are both "custom". Its query names its days; a named range's is unchanged.
 *   [2] the step      a custom volume's step is the server's (axis), never a per-range map entry; no axis → 0, never 1.
 *   [3] the guards    the Overview fetches, holds and labels by the key it LOADED — change only `from` and it refetches,
 *                     and the old window's figures never sit under the new window's name.
 *   [4] the poll      a named range polls Protection every 15 s; a custom window running to today once a minute; one
 *                     that ended, never.
 *   [5] Top talkers   are the Users grid's figures (the same cache): a named range as a rolling window of its length, a custom window as its days, a subset
 *                     of nodes by `nodes=`; the subtitle says each peer is whole on a subset, and where a widened window
 *                     really starts.
 *   [6] the picker    a custom chart window starts no earlier than the charts keep (33 days, today included).
 *
 * Run: node tests/spa_chart_range_selftest.mjs                 (0 = pass)
 *      node tests/spa_chart_range_selftest.mjs --plant <name>  breaks one rule on purpose; exits 0 only if a check went red.
 *      plants: step key label query poll talk early since clamp eff cpucap gridbusy grid gone scope apply talkerr
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, FAILS } from "./spa_env.mjs";

const PLANT = process.argv.includes("--plant") ? process.argv[process.argv.indexOf("--plant") + 1] : "";
const PLANTS = {   // name: [file, anchor, replacement]
  step: ["screen-overview.js", "return isCustomKey(key) ? ((hist && hist.axis && hist.axis.step) || 0) : (RANGE_STEP[key] || 1);", "return RANGE_STEP[key] || 1;"],
  key: ["views.js", `return "custom:" + from.replace(/-/g, "") + "-" + to.replace(/-/g, "");`, `return "custom";`],
  label: ["views.js", "export const rangeWord = k => isCustomKey(k) ? customKeyLabel(k) : ", "export const rangeWord = k => "],
  query: ["store.js", `  return "range=custom&from=" + w.from + "&to=" + w.to;`, `  return "range=" + encodeURIComponent(k);`],
  poll: ["screen-overview.js", "return customKeyWindow(key).to < today ? 0 : 60000;", "return 15000;"],
  talk: ["screen-overview.js", `export const talkWindow = key => isCustomKey(key) ? customKeyWindow(key) : { window: RANGE_WIN[key] };`,
    `export const talkWindow = key => isCustomKey(key) ? customKeyWindow(key) : { range: key };`],
  grid: ["traffic.js", `    out.push({ uid, rx: a.rx, tx: a.tx, devices: devs.map(id => {`,
    `    const cur = devs.filter(id => (Store.peer(id) || {}).user_id === uid).reduce((m, id) => { const q = d.peer.get(id) || {}; m.rx += q.rx || 0; m.tx += q.tx || 0; return m; }, { rx: 0, tx: 0 });\n    out.push({ uid, rx: cur.rx, tx: cur.tx, devices: devs.map(id => {`],
  gone: ["traffic.js", `    if (!Store.user(uid)) continue;\n`, ``],
  scope: ["traffic.js", `    if (inScope && !devs.some(id => { const p = Store.peer(id); return p && p.user_id === uid && ok(id); })) continue;\n`, ``],
  clamp: ["views.js", `const first = chartsFirstDay(), from = dashState.from < first ? first : dashState.from,`, `const first = "", from = dashState.from,`],
  eff: ["screen-overview.js", `export const effRangeOf = (dKey, loaded) => dKey === "live" ? "live" : loaded;`,
    `export const effRangeOf = (dKey, loaded) => dKey === "live" ? "live" : (loaded !== "live" ? loaded : dKey);`],
  cpucap: ["screen-nodes.js", `cpuCap = useRanged ? (RANGE_CAP[range] || axisCap(nodeHist.axis) || 0) : 0;`, `cpuCap = useRanged ? (RANGE_CAP[range] || 0) : 0;`],
  talkerr: ["screen-overview.js", "(!talkD || talkE.off || talkE.err)", "(!talkD || talkE.off)"],
  apply: ["traffic-ui.js", "const changed = !!pending || (!!draft && (dr.from !== from || dr.to !== to));", "const changed = !!draft && (dr.from !== from || dr.to !== to);"],
  gridbusy: ["traffic.js", `      if (r && r.code === "busy") e.at = Date.now() - TTL_MS + BUSY_MS;`, ""],
  early: ["traffic.js", `  if (min && from < min) return { ok: false, why: "early" };\n`, ""],
  since: ["screen-overview.js", `  if (d && d.asked && win && (d.since > d.asked + 60 || d.asked - d.since > win / 10))`, `  if (d && d.asked && win)`],
};
const written = [];
function load(file) {   // a planted module is a sibling copy in js/ (relative imports keep working) — removed at the end
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
  const S = await load("store.js");
  const RS = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);   // the store every other module uses (stubs go here)
  const V = await load("views.js");
  const TR = await load("traffic.js");
  const O = await load("screen-overview.js");
  const N = await load("screen-nodes.js");
  const C = await import(pathToFileURL(path.join(ROOT, "js", "charts.js")).href);
  S.Store.panelSettings = { time_zone_now: { offset: 3 * 3600 } };

  console.log("[1] a custom window travels as its key");
  Object.assign(V.dashState, { range: "custom", from: "2026-09-01", to: "2026-09-15" });
  const k = V.dashKey();
  check("the Overview's key names the window's days — two custom windows are two keys", k === "custom:20260901-20260915"
    && V.isCustomKey(k) && !V.isCustomKey("custom") && !V.isCustomKey("day"), k);
  Object.assign(V.dashState, { from: "2026-09-02" });
  check("…so changing only `from` changes the key", V.dashKey() === "custom:20260902-20260915", V.dashKey());
  check("its query names its days; a named range's is what it always was",
    S.rangeQ(k) === "range=custom&from=2026-09-01&to=2026-09-15" && S.rangeQ("week") === "range=week", S.rangeQ(k));
  const w = V.rangeWord(k);
  check("its name is its dates — never the word for live", w && w !== V.rangeWord("live") && /1/.test(w) && /15/.test(w), w);
  check("a custom point is named by its date (and its time unless midnight), months through Intl",
    C.histTime(Date.parse("2026-09-03T00:00:00") / 1000, k) === "September 3"
    && C.histTime(Date.parse("2026-09-03T14:00:00") / 1000, k) === "September 3 14:00"
    && C.histTime(Date.parse("2026-06-24T18:00:00") / 1000, "week") === "June 24 18:00", C.histTime(Date.parse("2026-09-03T00:00:00") / 1000, k));
  const vs = src("views.js");
  check("(source) the window persists and comes back on reload — a custom range must not fall back to live",
    vs.includes(`...(dashState.range === "custom" ? { from: dashState.from, to: dashState.to } : {})`)
    && vs.includes(`else if (raw.range === "custom" && /^\\d{4}-\\d{2}-\\d{2}$/.test(raw.from || "")`), "");

  S.Store.panelSettings = { time_zone_now: { offset: 3 * 3600 } };
  const first = TR.chartsFirstDay();
  const d0 = new Date(first + "T00:00:00Z"); d0.setUTCDate(d0.getUTCDate() - 30);
  const old = d0.toISOString().slice(0, 10);
  Object.assign(V.dashState, { range: "custom", from: old, to: first });
  check("a window kept from an earlier visit that aged past the charts' reach is read from the first day they hold",
    V.dashKey() === "custom:" + first.replace(/-/g, "") + "-" + first.replace(/-/g, ""), [V.dashKey(), first]);
  Object.assign(V.dashState, { range: "custom", from: "2026-09-02", to: "2026-09-15" });
  S.Store.nodes = [];
  const nh = N.NodeHealth({ health: { cpu: 10 }, node: "n1", compact: true, range: k,
    nodeHist: { t: [1, 2, 3], cpu: [5, 6, 7], axis: { since: 0, until: 86400, step: 1800 } } });
  const findCap = n => { if (!n || typeof n !== "object") return null; if (Array.isArray(n)) { for (const x of n) { const c = findCap(x); if (c != null) return c; } return null; }
    if (n.props && n.props.cap !== undefined && n.props.points) return n.props.cap; return findCap(n.props && n.props.children); };
  check("a node card's CPU chart lays a custom window on its buckets, like the fleet chart beside it", findCap(nh) === 48, findCap(nh));

  console.log("[2] the step is the server's");
  check("a custom volume's step is the one the server used", O.rangeStep(k, { axis: { step: 7200 } }) === 7200, O.rangeStep(k, { axis: { step: 7200 } }));
  check("…with no axis yet it is 0 (an empty figure), never 1 (a figure 300–7200× too small)", O.rangeStep(k, {}) === 0, O.rangeStep(k, {}));
  check("…and a named range keeps its ring's step", O.rangeStep("day", {}) === 300 && O.rangeStep("month", null) === 7200, "");
  check("a custom window's x-axis holds its buckets", C.axisCap({ since: 0, until: 86400 * 3, step: 1800 }) === 144 && C.axisCap(null) === 0, "");

  console.log("[3] the guards read the key that was loaded");
  const so = src("screen-overview.js");
  check("(source) both Overview feeds are keyed on the window, not on the bare range",
    so.includes("const rangeHist = useRangeHistory(dKey, selIds);") && so.includes("const blockStats = useBlockStats(dKey);")
    && so.includes(`const key = range + "|" + selIds.slice().sort().join(",");`), "");
  check("the figures and titles follow the LOADED key while a new window is fetched — live until the first ranged fetch lands",
    O.effRangeOf("day", "live") === "live" && O.effRangeOf(k, "day") === "day" && O.effRangeOf("live", "day") === "live"
    && so.includes("const effRange = effRangeOf(dKey, rangeHist.range);")
    && so.includes("setSt({ loading: false, byNode, mesh, cats, turn, exits, presence, axis, err, range }); });")
    && !/RANGE_STEP\[(range|effRange)\]/.test(so), [O.effRangeOf("day", "live"), O.effRangeOf(k, "day")]);

  console.log("[4] the Protection poll");
  check("a named range polls every 15 s", O.blockPollMs("day", "2026-09-24") === 15000, O.blockPollMs("day", "2026-09-24"));
  check("a custom window running to the panel's today, once a minute", O.blockPollMs("custom:20260920-20260924", "2026-09-24") === 60000, "");
  check("a custom window that ended is never polled", O.blockPollMs("custom:20260901-20260915", "2026-09-24") === 0,
    O.blockPollMs("custom:20260901-20260915", "2026-09-24"));

  console.log("[5] Top talkers are the Users grid's figures");
  check("a named range is a rolling window of its length up to the PANEL's now — never a start from this browser's clock",
    JSON.stringify(O.talkWindow("day")) === '{"window":86400}' && TR.trafficQuery(O.talkWindow("hour")) === "window=3600", O.talkWindow("day"));
  check("a custom window is its days — the same cache entry the grids use for those days",
    TR.trafficQuery(O.talkWindow("custom:20260901-20260915")) === TR.trafficQuery({ range: "custom", from: "2026-09-01", to: "2026-09-15" }), "");
  // Anna (u1): phone p1 (hers now), tablet p3 (deleted), laptop p5 (handed to Boris, u2); a deleted user u9 (p9);
  // p4 belongs to nobody; p6 belonged to nobody, then to Boris.
  const peersT = { p1: { id: "p1", title: "phone", user_id: "u1", targets: [{ node: "n1", iface: "awg0", ip: "10.0.0.1" }] },
    p5: { id: "p5", title: "laptop", user_id: "u2", targets: [{ node: "n2", iface: "awg0", ip: "10.0.0.5" }] },
    p4: { id: "p4", title: "spare", user_id: "", targets: [{ node: "n1", iface: "awg0", ip: "10.0.0.4" }] },
    p6: { id: "p6", title: "kiosk", user_id: "u2", targets: [{ node: "n2", iface: "awg0", ip: "10.0.0.6" }] } };
  const usersT = { u1: { id: "u1", name: "Anna" }, u2: { id: "u2", name: "Boris" } };
  const [rp, ru] = [RS.Store.peer, RS.Store.user];
  RS.Store.peer = id => peersT[id] || null; RS.Store.user = id => usersT[id] || null;
  const FT = TR.foldTotals([
    { id: "p1", owner: "u1", rx: 100, tx: 10 }, { id: "p3", owner: "u1", rx: 300, tx: 30 }, { id: "p5", owner: "u1", rx: 500, tx: 50 },
    { id: "p5", owner: "u2", rx: 70, tx: 7 }, { id: "p9", owner: "u9", rx: 9000, tx: 900 },
    { id: "p4", owner: "", rx: 40, tx: 4 }, { id: "p6", owner: "", rx: 60, tx: 6 }, { id: "p6", owner: "u2", rx: 20, tx: 2 }]);
  const G = TR.talkerGroups(FT);
  const gu = id => G.find(g => g.uid === id);
  check("a person's figure is exactly their Users-grid figure — a deleted device and one handed on (up to the handover) included",
    gu("u1") && gu("u1").rx === FT.user.get("u1").rx && gu("u1").rx === 900 && gu("u2").rx === FT.user.get("u2").rx, G.map(g => [g.uid || g.pid, g.rx]));
  check("…a deleted user is not listed (the grid has no row for them), and the order is by that figure",
    !gu("u9") && G.map(g => g.uid || g.pid).join() === "u1,u2,p4", G.map(g => g.uid || g.pid));
  check("a device that belongs to nobody is its own talker with what it carried meanwhile; one assigned since is not",
    G.some(g => g.pid === "p4" && g.rx === 40) && !G.some(g => g.pid === "p6"), G.map(g => g.uid || g.pid));
  const d1 = gu("u1").devices, dv = id => d1.find(x => x.id === id) || {};
  check("the bubble names each device over the window — deleted and handed on said so, each with its own part",
    dv("p3").gone === "deleted" && dv("p5").gone === "handed" && dv("p5").rx === 500 && dv("p1").gone === "" && dv("p3").name === "", d1);
  const GS = TR.talkerGroups(FT, pid => (peersT[pid] || { targets: [] }).targets.some(t => t.node === "n1"));
  check("a subset of nodes lists the people with a device there now, each with their whole figure",
    GS.map(g => g.uid || g.pid).join() === "u1,p4" && GS[0].rx === 900, GS.map(g => [g.uid || g.pid, g.rx]));
  RS.Store.peer = rp; RS.Store.user = ru;
  const A = 1790000000;
  check("the subtitle says each figure is whole on a subset", O.talkSub("day", null, true).includes("each on all their servers"), O.talkSub("day", null, true));
  check("…where a rolling window starts, when it matters: an Hour widened to the ledger's hour, or history beginning later",
    /since /.test(O.talkSub("hour", { asked: A, since: A - 1800 })) && /since /.test(O.talkSub("day", { asked: A, since: A + 3600 })), "");
  check("…and not for a Day, Week or Month widened by less than a tenth of it",
    O.talkSub("day", { asked: A, since: A - 1800 }) === "day · by volume" && O.talkSub("month", { asked: A, since: A - 3500 }) === "month · by volume",
    O.talkSub("day", { asked: A, since: A - 1800 }));
  check("(source) ranged Top talkers read the grids' cache, and the Overview asks the ledger nothing of its own",
    so.includes("const talkE = dRanged ? trafficTotals(talkWindow(effRange)) : null;") && !so.includes("/api/traffic-totals")
    && !so.includes("api.peerHistory("), "");

  let nGrid = 0;
  const realGet = RS.api.get;
  RS.api.get = () => { nGrid++; return Promise.resolve({ ok: false, code: "busy", error: "being written" }); };
  const gv = { range: "custom", from: "2026-01-01", to: "2026-01-31" };
  TR.trafficTotals(gv); await new Promise(r => setTimeout(r, 0));
  TR.trafficTotals(gv, Date.now() + 3500); await new Promise(r => setTimeout(r, 0));
  RS.api.get = realGet;
  check("the grids ask a busy ledger again within seconds, not after a minute", nGrid === 2, nGrid);

  const tu = src("traffic-ui.js");
  check("(source) the rail's proposed window can be applied as it stands — Apply is offered before any date is touched",
    so.includes("onApply=${dashSetCustom} pending=${!on}/>") && tu.includes("const changed = !!pending || (!!draft && (dr.from !== from || dr.to !== to));"), "");

  check("(source) Top talkers that could not be loaded say why — never an endless ellipsis",
    so.includes("(!talkD || talkE.off || talkE.err)") && so.includes(": talkE.err ? html`<div class=\"hint\">"), "");

  console.log("[6] the picker's reach");
  check("a custom chart window starts no earlier than the charts keep — 33 days, today included",
    TR.chartsFirstDay("2026-09-24") === "2026-08-23" && TR.customWindow("2026-08-22", "2026-09-01", "2026-09-24", "2026-08-23").why === "early"
    && TR.customWindow("2026-08-23", "2026-09-01", "2026-09-24", "2026-08-23").ok, TR.customWindow("2026-08-22", "2026-09-01", "2026-09-24", "2026-08-23"));
  check("…while the grids' window keeps any day", TR.customWindow("2020-01-01", "2026-09-01", "2026-09-24").ok, "");
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
