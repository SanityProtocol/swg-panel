/* Self-test: the fast lane's select in Node settings (docs/DATAPATH-PLAN.md D3, §11 decisions 10 and 11) — the real sheets-crud.js.
 *
 * The panel stores a node's `fast_lane` as an exact int from its own steps and refuses anything else, a string included
 * (tests/fast_lane_selftest.py [8]). The select is the only way an operator sets it, so what it offers and what it sends is
 * the whole contract:
 *
 * [1] the options: the server's FAST_LANE_STEPS exactly, in order, each a number — "80" from a select would be refused;
 *     0 reads Off, the server's default (70) and only it reads "(default)"
 * [2] the field: a Dropdown on those options and the given value, whose choice reaches the sheet as the number it is
 * [3] the sheet (its wiring, read as shipped — NodeEditSheet keeps its state in hooks): it opens on the node's published
 *     value (70 when none is stored), shows the field under Datapath, posts `fast_lane` only when it changed (a save of the
 *     name never writes it), and a changed choice — a click the Sheet's own guard cannot hear — asks before Esc or Cancel
 *     discards it
 * [4] Russian: the label, the options and the hint each have a Russian line
 *
 * Run: node tests/spa_fast_lane_selftest.mjs     --perturb strval|nodefault|nosave|noguard   plants one and expects RED.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, spa, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  strval: ["FAST_LANE_STEPS.map(v => ({ value: v, label:", "FAST_LANE_STEPS.map(v => ({ value: String(v), label:"],   // [1]
  nodefault: [': v === FAST_LANE_DEFAULT ? T("Starts at {v1}% CPU (default)", { v1: v }) :', ":"],                    // [1]
  nosave: ["\n        ...(fastLane !== fl0 ? { fast_lane: fastLane } : {}) }),", " }),"],                                // [3]
  noguard: ["  dirtyRef.current = editKey !== base.current;\n", ""],                                                     // [3]
};
const FILE = path.join(ROOT, "js", "sheets-crud.js");
let src = fs.readFileSync(FILE, "utf8"), made = null, SC;
if (MODE) {
  if (!PLANTS[MODE]) { console.log("unknown plant " + MODE + " (one of: " + Object.keys(PLANTS).join(", ") + ")"); process.exit(1); }
  const [a, b] = PLANTS[MODE];
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING for " + MODE); process.exit(1); }
  src = src.replace(a, b);
  // In a directory of its own, its siblings by absolute URL (the very modules the real sheets-crud.js imports): never a planted
  // file inside js/, one `git add -A` from shipping (1.8.9 qualification GATES-14).
  made = fs.mkdtempSync(path.join(os.tmpdir(), "fastlane-"));
  const JS_URL = pathToFileURL(path.join(ROOT, "js") + path.sep).href;
  fs.writeFileSync(path.join(made, "sheets-crud.mjs"), src.replace(/(\bfrom\s*)(["'])\.\//g, (m, f, q) => f + q + JS_URL));
}
try { SC = await import(pathToFileURL(made ? path.join(made, "sheets-crud.mjs") : FILE).href); }
finally { if (made) fs.rmSync(made, { recursive: true, force: true }); }
const UI = await spa("ui.js");
const RU = (await spa("lang/ru.js")).STR;

// the server's own steps and default, read from swg-panel-server as shipped
const srv = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
const m = srv.match(/^FAST_LANE_DEFAULT, FAST_LANE_STEPS = (\d+), \(([\d, ]+)\)$/m);
if (!m) { console.log("FAIL the server's FAST_LANE_DEFAULT, FAST_LANE_STEPS line is not where this gate reads it"); process.exit(1); }
const SRV_DEF = +m[1], SRV_STEPS = m[2].split(",").map(s => +s.trim());

console.log("\n[1] the options");
const opts = SC.fastLaneOptions();
check("the server's steps exactly, in order", JSON.stringify(opts.map(o => +o.value)) === JSON.stringify(SRV_STEPS), [opts.map(o => o.value), SRV_STEPS]);
check("…each a number (the panel refuses a string)", opts.every(o => Number.isInteger(o.value)), opts.map(o => typeof o.value));
check("the sheet's default is the server's", SC.FAST_LANE_DEFAULT === SRV_DEF, [SC.FAST_LANE_DEFAULT, SRV_DEF]);
check("0 reads Off", (opts.find(o => o.value === 0) || {}).label === "Off", opts[0]);
const marked = opts.filter(o => /\(default\)$/.test(o.label));
check("the default and only it reads (default)", marked.length === 1 && +marked[0].value === SRV_DEF && marked[0].label === "Starts at 70% CPU (default)",
      opts.map(o => o.label));
check("…the others say where the lane starts", opts.filter(o => +o.value && +o.value !== SRV_DEF).every(o => o.label === "Starts at " + o.value + "% CPU"),
      opts.map(o => o.label));

console.log("\n[2] the field");
const kids = n => (Array.isArray(n) ? n : [n]).flatMap(x => x && x.props ? [x, ...kids(x.props.children || [])] : []);
let got = "none";
const field = SC.FastLaneField({ value: 70, onChange: v => { got = v; } });
const dd = kids(field).find(x => x.type === UI.Dropdown);
check("a Dropdown", !!dd);
check("…on the options and the given value", dd && dd.props.value === 70
      && JSON.stringify(dd.props.options.map(o => o.value)) === JSON.stringify(SRV_STEPS), dd && [dd.props.value, dd.props.options]);
if (dd) dd.props.onChange(0);
check("a choice reaches the sheet as the number it is", got === 0, got);

console.log("\n[3] the sheet");
const a = src.indexOf("export function NodeEditSheet("), body = a < 0 ? "" : src.slice(a, src.indexOf("\n}\n", a));
const has = (what, s) => check(what, body.includes(s), s);
has("opens on the node's published value, 70 when none is stored", "const fl0 = node.fast_lane ?? FAST_LANE_DEFAULT;");
has("…shows the field under Datapath", '<div class="seclabel">${T("Datapath")}</div>\n    <${FastLaneField} value=${fastLane} onChange=${setFastLane}/>');
has("posts fast_lane only when it changed", "...(fastLane !== fl0 ? { fast_lane: fastLane } : {}) }),");
has("a changed choice is part of what the guard compares", "JSON.stringify([name, color, defEgress, panelIp, meshEgress, fastLane])");
has("…the guard is told", "  dirtyRef.current = editKey !== base.current;\n");
has("…the Sheet carries it", "dirtyRef=${dirtyRef} closeRef=${closeRef}");
has("…and Cancel goes through it", "onCancel: () => (closeRef.current ? closeRef.current() : closeModal())");

console.log("\n[4] Russian");
const hint = kids(field).find(x => x.props && x.props.class === "hint");
const hintKey = hint ? [].concat(hint.props.children).join("") : "";
for (const k of ["Fast lane", "Datapath", "Off", "Starts at {v1}% CPU", "Starts at {v1}% CPU (default)", hintKey])
  check("a Russian line for " + JSON.stringify(k.length > 40 ? k.slice(0, 40) + "…" : k), !!k && typeof RU[k] === "string" && RU[k].length > 0);
done(!!MODE, MODE);
