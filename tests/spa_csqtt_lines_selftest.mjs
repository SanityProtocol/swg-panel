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
 *  [7] q189 SPA-11 — a record naming a line the panel no longer offers (a stand-in line taken away) reads as the panel reads
 *      it (_csqtt_line_of: 2.1, what the node is sent): the card is not "switching" for ever; with the line back on offer
 *      the same record is a switch again
 *  [8] the fork badge names the line the server RUNS (operator, 2026-10-16: "amurcanov 2.5", no line of its own) — during a
 *      switch still the running one, and 2.1 for a node that reports no line
 *  [9] App routing (2.5): the sheet's form → the record the panel stores — the built-in list is a direct list (dropped in
 *      tunnel mode), lists split on whitespace or commas; a stored rule round-trips the form ("every app" ignoring the
 *      app list is the panel's: csqtt_app_routing [1])
 *
 * Run: node tests/spa_csqtt_lines_selftest.mjs     --perturb <hide|refuse|failed|blocked|unoffered|stale|runline|runseen> plants one regression, expects RED.
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
  runline: ["turn.js", "  return seen ? s.run : s.want;", "  return s.want;"],
  artpl: ["turn.js", "template_domains: a.domains_mode === \"direct\" && !!a.template_domains,", "template_domains: !!a.template_domains,"],
  runseen: ["turn.js", "  return seen ? s.run : s.want;", "  return s.run;"],
  stale: ["turn.js", "export const csqttLineOf = cfg => { const l = String((cfg && cfg.line) || \"\").trim(); return (Store.csqttLines || []).includes(l) ? l : CSQTT_DEFAULT_LINE; };",
          "export const csqttLineOf = cfg => (cfg && cfg.line) || CSQTT_DEFAULT_LINE;"],
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

// [7] q189 SPA-11
Store.csqttLines = ["2.1"];
Store.nodes = [{ id: "nnew", csqtt_cfg: { s: { line: "2.5" } } }];
Store.stats = { nnew: { csqtt_lines: ["2.1", "2.5"], csqtt: [{ iface: "s", line: "2.1" }] } };
const s7 = TU.csqttSwitchState("nnew", "s");
check("[7] a record naming 2.5 when only 2.1 is offered: asked 2.1 (what the node is sent), runs 2.1 — not switching for ever",
      s7.want === "2.1" && !s7.switching && !s7.blocked, s7);
check("[7] …and csqttLineOf reads it as the panel does", TU.csqttLineOf({ line: "2.5" }) === "2.1" && TU.csqttLineOf({}) === "2.1", TU.csqttLineOf({ line: "2.5" }));
Store.csqttLines = ["2.1", "2.5"];
const s7b = TU.csqttSwitchState("nnew", "s");
check("[7] with 2.5 back on offer, the same record is a switch again", s7b.want === "2.5" && s7b.switching, s7b);

// [8]
Store.nodes = [{ id: "nnew", csqtt_cfg: { r: { line: "2.5" }, m: { line: "2.5" } } }];
Store.stats = { nnew: { csqtt_lines: ["2.1", "2.5"], csqtt: [{ iface: "r", line: "2.5" }, { iface: "m", line: "2.1" }, { iface: "o" }] } };
check("[8] a server on 2.5: its badge says 2.5", TU.csqttRunLine("nnew", "r") === "2.5", TU.csqttRunLine("nnew", "r"));
check("[8] mid-switch (asked 2.5, runs 2.1): the badge says what runs, 2.1", TU.csqttRunLine("nnew", "m") === "2.1", TU.csqttRunLine("nnew", "m"));
check("[8] a node that reports no line: 2.1", TU.csqttRunLine("nnew", "o") === "2.1", TU.csqttRunLine("nnew", "o"));
Store.nodes[0].csqtt_cfg.g = { line: "2.5" };   // configured 2.5, not in the node's report (awaiting restore, a stale node)
check("[8] a 2.5 server the node does not report: its configured 2.5, never 2.1", TU.csqttRunLine("nnew", "g") === "2.5", TU.csqttRunLine("nnew", "g"));

// [9]
const f9 = { apps_mode: "all", packages: "com.a", domains_mode: "tunnel", domains: "a.ru\n b.ru ,c.ru", template_domains: true, ips_mode: "direct", ips: "" };
const b9 = TU.arBody(f9);
check("[9] the built-in list is dropped in tunnel mode", b9.template_domains === false, b9);
check("[9] lists split on lines and commas, trimmed", JSON.stringify(b9.domains) === '["a.ru","b.ru","c.ru"]', b9.domains);
const rec9 = { apps_mode: "except", packages: ["org.telegram.messenger"], domains_mode: "direct", domains: ["ya.ru"], template_domains: true, ips_mode: "direct", ips: ["10.0.0.0/8"] };
check("[9] a stored rule round-trips the form", JSON.stringify(TU.arBody(TU.arInit({ app_routing: rec9 }))) === JSON.stringify(rec9), TU.arBody(TU.arInit({ app_routing: rec9 })));
check("[9] a stored punycode domain is shown as typed (and saves back the same)", TU.arInit({ app_routing: { domains: ["xn--c1aapkosapc.xn--p1ai"] } }).domains === "госуслуги.рф");
check("[9] whitespace splits a list as the app does", JSON.stringify(TU.arBody({ ...TU.arInit({}), domains: "ya.ru vk.com\tok.ru" }).domains) === '["ya.ru","vk.com","ok.ru"]');
check("[9] no stored rule: every app, direct, empty", JSON.stringify(TU.arBody(TU.arInit({}))) === JSON.stringify({ apps_mode: "all", packages: [], domains_mode: "direct", domains: [], template_domains: false, ips_mode: "direct", ips: [] }));

done(!!MODE, MODE || "");
