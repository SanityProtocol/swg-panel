// panelTwin (js/store.js) — when has this browser been served by TWO panels alive at once?
// A restart / update is a new instance whose life begins after the old one's last answer → never an alarm.
// Two instances whose lifetimes overlap, the other seen recently → the alarm. Clocks: each server's own, with a
// margin for two servers disagreeing. Extracted from the source (store.js imports preact via the importmap).
// Run: node tests/panel_twin_selftest.mjs   (exit 0 = all pass)
import { readFileSync } from "fs";
const src = readFileSync(new URL("../js/store.js", import.meta.url), "utf8");
const pick = re => { const m = src.match(re); if (!m) throw new Error("anchor missing: " + re); return m[0]; };
const code = pick(/const INST_MARGIN = [^\n]*\n/) + pick(/const INST_RECENT = [^\n]*\n/)
  + pick(/export function panelTwin\(list, cur\) \{[\s\S]*?\n\}\n/).replace("export ", "");
const panelTwin = new Function(code + "return panelTwin;")();
let fails = 0;
const check = (name, ok, d) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  — " + JSON.stringify(d))); if (!ok) fails++; };
const T = 1_790_000_000, H = 3600;
const A = { id: "a", started: T - 10 * 86400, last: T };             // the real panel, up for 10 days, answering now
check("first sight of a panel → nothing", panelTwin([], A) === null);
check("the same instance again → nothing", panelTwin([{ ...A, last: T - 60 }], A) === null);
// restart: old instance last answered at T-30, new one started at T-20
check("a restart is not two panels", panelTwin([{ id: "old", started: T - 5 * 86400, last: T - 30 }], { id: "new", started: T - 20, last: T }) === null);
check("…nor an update that took a minute", panelTwin([{ id: "old", started: T - 5 * 86400, last: T - 90 }], { id: "new", started: T, last: T + 5 }) === null);
// the client's case: a stray panel up for 3 days answered an hour ago; the real one (up 10 days) answers now
const stray = { id: "s", started: T - 3 * 86400, last: T - 600 };
check("two panels alive at once → the other is named", (panelTwin([stray], A) || {}).id === "s");
check("…from either side", (panelTwin([{ ...A, last: T - 600 }], { ...stray, last: T }) || {}).id === "a");
check("clock disagreement inside the margin is not overlap",
  panelTwin([{ id: "old", started: T - 86400, last: T - 10 }], { id: "new", started: T + 60, last: T + 100 }) === null);
check("a twin not seen for longer than the window stops alarming", panelTwin([{ ...stray, last: T - 7 * H }], A) === null);
check("…and the window is short enough that stopping the stray visibly works (≤ 1 h)",
  panelTwin([{ ...stray, last: T - H - 1 }], A) === null);
check("the list is kept per mount path, not per origin", /INST_KEY = "swg\.panelInstances:" \+ url\(""\)/.test(src));
console.log(fails ? `\n${fails} FAILED` : "\nALL PASS"); process.exit(fails ? 1 : 0);
