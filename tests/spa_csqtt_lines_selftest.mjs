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
 *  [10] the csqtt interface sheet offers the Version too (operator, 2026-10-17), on the csqtt server's line, saved with
 *      the same questions as the csqtt-proxy modal (one askCsqttLine for both, both branches run here off the real modal
 *      stack), and App routing follows the picked line; both sheets hold only a PICK (useCsqttPick): untouched, the field
 *      follows the polled record and nothing is sent; the csqtt-proxy sheet hands only a real pick to the interface sheet
 *
 * Run: node tests/spa_csqtt_lines_selftest.mjs     --perturb <hide|refuse|failed|blocked|unoffered|stale|runline|runseen|ifver|ifline|ifopen|ifpick|askgo|pickdirty> plants one regression, expects RED.
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
  ardrop: ["turn.js", "export const csqttArDropAsk = (cfg, line) => !csqttArLine(line) && !!(cfg && cfg.app_routing);",
    "export const csqttArDropAsk = (cfg, line) => false;"],
  artpl: ["turn.js", "template_domains: a.domains_mode === \"direct\" && !!a.template_domains,", "template_domains: !!a.template_domains,"],
  runseen: ["turn.js", "  return seen ? s.run : s.want;", "  return s.run;"],
  ifver: ["turn.js", "      <${CsqttVersionField} node=${node} value=${line} onChange=${setLine}/>\n    </div>", "    </div>"],
  ifline: ["turn.js", "      ...(lineDirty ? { line } : {}), ...(is25 ? { app_routing: arBody(ar) } : {}) }), errMsg(setMsg), setBusy);",
           "      ...(is25 ? { app_routing: arBody(ar) } : {}) }), errMsg(setMsg), setBusy);"],
  ifopen: ["turn.js", "  const { line, setLine, lineDirty } = useCsqttPick(cfg, pick);", "  const { line, setLine, lineDirty } = useCsqttPick(cfg);"],
  pickdirty: ["turn.js", "line = picked || cur; return { line, lineDirty: line !== cur }; };", "line = picked || cur; return { line, lineDirty: !!picked }; };"],
  ifpick: ["turn.js", " pick=${lineDirty ? line : null}/>", "/>"],
  askgo: ["turn.js", "      body=${T(\"Its App routing is removed: csqtt {v1} has none.\", { v1: line })} onConfirm=${go}/>`);",
          "      body=${T(\"Its App routing is removed: csqtt {v1} has none.\", { v1: line })} onConfirm=${() => {}}/>`);"],
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
let TU, ST, TSRC;
try { TU = await load("turn.js"); TSRC = fs.readFileSync(made[0] || path.join(ROOT, "js", "turn.js"), "utf8"); ST = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href); }
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
check("[9] \";\" separates entries too", JSON.stringify(TU.arBody({ ...TU.arInit({}), domains: "ya.ru;vk.com" }).domains) === '["ya.ru","vk.com"]');
check("[9] back to the 2.1 that runs with a stored rule: asked (the rule goes)", TU.csqttArDropAsk({ app_routing: { domains: ["ya.ru"] } }, "2.1") === true
      && TU.csqttArDropAsk({}, "2.1") === false && TU.csqttArDropAsk({ app_routing: {} }, "2.5") === false);
check("[9] App routing is every line's but 2.1's (as the panel stores it)", TU.csqttArLine("2.5") && !TU.csqttArLine("2.1") && !TU.csqttArLine(undefined));
check("[9] no stored rule: every app, direct, empty", JSON.stringify(TU.arBody(TU.arInit({}))) === JSON.stringify({ apps_mode: "all", packages: [], domains_mode: "direct", domains: [], template_domains: false, ips_mode: "direct", ips: [] }));

// [10] — read from the source the run loaded (a sheet with hooks is not rendered here)
const sheet = (TSRC.split("export function EditCsqttSheet(")[1] || "").split("\nexport function ")[0];
check("[10] the interface sheet exists where this gate looks", sheet.length > 500, sheet.length);
const row = (sheet.split('<div class="row2">')[1] || "").split("\n    </div>")[0];
check("[10] the Version sits on the csqtt server's line (one row2)", /T\("csqtt server"\)/.test(row) && row.includes("<${CsqttVersionField} node=${node} value=${line} onChange=${setLine}/>"), row.slice(0, 200));
check("[10] a changed version is sent with the save", sheet.includes("...(lineDirty ? { line } : {})"));
check("[10] …after the same questions as the csqtt-proxy modal", sheet.includes("if (lineDirty && askCsqttLine(sw, node, iface, cfg, line, doSave)) return;")
      && TSRC.includes("if (lineDirty && askCsqttLine(sw, node, iface, cfg, line, endpointDirty ? askEndpoint : doSave)) return;"));
check("[10] both sheets hold a pick, not a copy of the record", sheet.includes("const { line, setLine, lineDirty } = useCsqttPick(cfg, pick);")
      && TSRC.includes("  const { line, setLine, lineDirty } = useCsqttPick(cfg);   // the csqtt version"));
check("[10] the csqtt-proxy sheet hands its unsaved pick to the interface sheet", TSRC.includes("<${EditCsqttSheet} node=${node} iface=${iface} pick=${lineDirty ? line : null}/>"));
// the pick against the record, as the hook reads it on every render (csqttPickState; the hook adds only the state)
Store.csqttLines = ["2.1", "2.5"];
const p1 = TU.csqttPickState(null, { line: "2.5" });
check("[10] untouched, the record moved to 2.5 by the poll: the field shows 2.5 and nothing is sent", p1.line === "2.5" && !p1.lineDirty, p1);
const p2 = TU.csqttPickState("2.1", { line: "2.5" });
check("[10] 2.1 picked over a 2.5 record: shown and sent", p2.line === "2.1" && p2.lineDirty, p2);
const p3 = TU.csqttPickState("2.5", { line: "2.5" });
check("[10] picked what the record already says (another tab got there first): nothing to send", p3.line === "2.5" && !p3.lineDirty, p3);
check("[10] …and the node's notices about the last switch", sheet.includes("<${CsqttLineNotices} sw=${sw} dirty=${lineDirty}/>"));
check("[10] App routing follows the picked line", sheet.includes("const is25 = csqttArLine(lineDirty ? line : cfg.line);"));
Store.nodes = [{ id: "nnew", csqtt_cfg: { q: { line: "2.5", app_routing: { domains: ["ya.ru"] } }, z: {} } }];
Store.stats = { nnew: { csqtt_lines: ["2.1", "2.5"], csqtt: [{ iface: "q", line: "2.5" }, { iface: "z", line: "2.1" }] } };
const UI = await import(pathToFileURL(path.join(ROOT, "js", "ui.js")).href);
let top = null; UI.setModalRenderer(st => { top = st[st.length - 1] || null; });
const ask = (iface, cfg, line) => { UI.clearModalStack(); top = null; let went = 0;
  const asked = TU.askCsqttLine(TU.csqttSwitchState("nnew", iface), "nnew", iface, cfg, line, () => went++);
  const p = (top && top.props) || {}; if (p.onConfirm) p.onConfirm(); return { asked, title: p.title, went }; };
const a1 = ask("z", {}, "2.1");
check("[10] picking what already runs, nothing to drop: no question, nothing saved by it", !a1.asked && !a1.title && a1.went === 0, a1);
const a2 = ask("q", Store.nodes[0].csqtt_cfg.q, "2.1");
check("[10] a switch away from what runs is confirmed, and confirming saves", a2.asked && a2.title === "Switch to csqtt 2.1?" && a2.went === 1, a2);
Store.stats.nnew.csqtt[0].line = "2.1";   // q now runs 2.1, its record still holds a 2.5 rule
const a3 = ask("q", Store.nodes[0].csqtt_cfg.q, "2.1");
check("[10] back to the 2.1 that runs with a rule: asked to remove it, and confirming goes on to the caller's next step", a3.asked && a3.title === "Remove App routing?" && a3.went === 1, a3);

done(!!MODE, MODE || "");
