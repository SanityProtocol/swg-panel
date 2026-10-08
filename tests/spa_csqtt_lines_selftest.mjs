/* Self-test — csqtt version LINES in the SPA (docs/CSQTT-LINES-PLAN.md §4.4).
 *
 *  [1] one line on offer (the default, no stand-in): no Version control anywhere — a 2.1-only panel looks exactly
 *      as it did
 *  [2] two lines, a node that can run both: the select lists csqtt 2.1 and csqtt 2.5, and the hint says what the
 *      chosen version means to the people on it (2.5 names the iPhone app)
 *  [3] two lines, an older node: 2.5 is offered but REFUSED with the reason (update the node), and the hint says so
 *      — never a silent disabled row the operator cannot explain
 *  [4] the switch as the node reports it: steady, switching (asked ≠ running, no failure), failed (the node's
 *      line_failed for the line the panel asks) — and a failure for ANOTHER line is not this switch's failure
 *
 *  [5] a record carried to a node that cannot run its version reads "update the node", never "switching" for ever
 *  [6] one line on offer but a server already runs another: the field stays, with that version selectable
 *
 * Run: node tests/spa_csqtt_lines_selftest.mjs     --perturb <hide|refuse|failed|blocked|unoffered> plants one regression, expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  hide: ["turn.js", "export const csqttLinesOn = () => (Store.csqttLines || []).length > 1;", "export const csqttLinesOn = () => true;"],
  blocked: ["turn.js", "  const blocked = moving && !csqttNodeLines(node).includes(want);", "  const blocked = false;"],
  unoffered: ["turn.js", "  if (!csqttLinesOn() && value === CSQTT_DEFAULT_LINE) return null;", "  if (!csqttLinesOn()) return null;"],
  refuse: ["turn.js", "    ...(id !== value && !can.includes(id) ? {", "    ...(false ? {"],
  failed: ["turn.js", "  const failed = c.line_failed && c.line_failed.line === want ? c.line_failed : null;", "  const failed = c.line_failed || null;"],
};
const made = [];
async function load(name) {
  if (!MODE || PLANTS[MODE][0] !== name) return import(pathToFileURL(path.join(ROOT, "js", name)).href);
  const [, old, nu] = PLANTS[MODE];
  const src = fs.readFileSync(path.join(ROOT, "js", name), "utf8");
  if (src.split(old).length !== 2) throw new Error("plant anchor did not match exactly once — this run would measure nothing");
  const p = path.join(ROOT, "js", "__perturbed_" + name); fs.writeFileSync(p, src.replace(old, nu)); made.push(p);
  return import(pathToFileURL(p).href);
}
let TU, ST;
try { TU = await load("turn.js"); ST = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href); }
finally { for (const p of made) fs.rmSync(p, { force: true }); }
const { Store } = ST;

const walk = (n, pick) => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
  else if (x && typeof x === "object" && x.props) { const r = pick(x); if (r !== undefined) out.push(r); w(x.props.children); } }; w(n); return out; };
const dropdown = n => walk(n, x => (x.props && Array.isArray(x.props.options)) ? x.props : undefined)[0];
const hint = n => walk(n, x => x.type === "div" && x.props.class === "hint" ? [].concat(x.props.children).join("") : undefined)[0] || "";

// [1]
Store.csqttLines = ["2.1"];
Store.stats = { nnew: { csqtt_lines: ["2.1", "2.5"] }, nold: {} };
check("[1] one line: csqttLinesOn is false", TU.csqttLinesOn() === false);
check("[1] one line: the Version field renders nothing", TU.CsqttVersionField({ node: "nnew", value: "2.1", onChange: () => {} }) === null);

// [2]
Store.csqttLines = ["2.1", "2.5"];
const f2 = TU.CsqttVersionField({ node: "nnew", value: "2.1", onChange: () => {} });
const d2 = dropdown(f2) || { options: [] };
check("[2] two lines: the select lists csqtt 2.1 and csqtt 2.5", JSON.stringify(d2.options.map(o => o.label)) === '["csqtt 2.1","csqtt 2.5"]', d2.options);
check("[2] a capable node: nothing is refused", d2.options.every(o => !o.refuse), d2.options);
check("[2] the hint for 2.1 says it is stable", /Stable/.test(hint(f2)), hint(f2));
check("[2] the hint for 2.5 names the iPhone app", /iPhone/.test(hint(TU.CsqttVersionField({ node: "nnew", value: "2.5", onChange: () => {} }))));

// [3]
const f3 = TU.CsqttVersionField({ node: "nold", value: "2.1", onChange: () => {} });
const d3 = dropdown(f3) || { options: [] };
const o25 = d3.options.find(o => o.value === "2.5") || {};
check("[3] an older node: 2.5 is refused with the reason", /Update this node/.test(o25.refuse || ""), o25);
check("[3] …2.1 stays choosable", !(d3.options.find(o => o.value === "2.1") || {}).refuse);
check("[3] …and the hint tells the operator to update the node", /Update this node/.test(hint(f3)), hint(f3));

// [4]
Store.nodes = [{ id: "nnew", csqtt_cfg: { a: {}, b: { line: "2.5" }, c: { line: "2.5" }, d: { line: "2.1" } } }];
Store.stats.nnew.csqtt = [
  { iface: "a", line: "2.1" },
  { iface: "b", line: "2.1" },
  { iface: "c", line: "2.1", line_failed: { line: "2.5", ver: "2.1.9-3", why: "the server exited" } },
  { iface: "d", line: "2.1", line_failed: { line: "2.5", ver: "x", why: "old" } }];
const s = i => TU.csqttSwitchState("nnew", i);
check("[4] steady: asked 2.1, runs 2.1", s("a").want === "2.1" && !s("a").switching && !s("a").failed, s("a"));
check("[4] switching: asked 2.5, runs 2.1, no failure", s("b").switching && !s("b").failed, s("b"));
check("[4] failed: the node's line_failed for 2.5", !!s("c").failed && !s("c").switching && s("c").failed.why === "the server exited", s("c"));
check("[4] a failure for another line is not this one's (asked 2.1 again)", !s("d").failed && !s("d").switching, s("d"));

// [5]
Store.nodes.push({ id: "nold", csqtt_cfg: { e: { line: "2.5" } } });
Store.stats.nold = { csqtt: [{ iface: "e", line: "" }] };
const so = TU.csqttSwitchState("nold", "e");
check("[5] a 2.5 record on a node that cannot run it is blocked, not switching", so.blocked && !so.switching, so);
check("[5] …while on a capable node the same request is switching", s("b").switching && !s("b").blocked, s("b"));

// [6]
Store.csqttLines = ["2.1"];
const f6 = TU.CsqttVersionField({ node: "nnew", value: "2.5", onChange: () => {} });
const d6 = dropdown(f6) || { options: [] };
check("[6] one line on offer, a server on 2.5: the field still shows", f6 !== null, f6);
check("[6] …listing 2.1 and the 2.5 it runs", JSON.stringify(d6.options.map(o => o.value)) === '["2.1","2.5"]', d6.options);

done(!!MODE, MODE || "");
