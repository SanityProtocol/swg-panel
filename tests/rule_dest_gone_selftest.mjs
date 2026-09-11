/* Self-test: a rule whose destination has been removed must SAY so, not render blank.
 *
 * A smart rule names its destination by id — a node for `action:"exit"`, an exit for `action:"dev"`. Remove
 * that node from the panel and nothing rewrites the rule: `cascade_plan` drops it silently
 *
 *     P = r.get("node")
 *     if not P or P not in nodes:
 *         continue
 *
 * and the picker, whose options are built from the nodes that DO exist, had no option carrying the stored
 * value — so it rendered COMPLETELY BLANK. Indistinguishable from "nothing chosen yet", while a real choice
 * sat in the store and every packet left by the node's default instead.
 *
 * MEASURED ON THE LIVE FLEET, not imagined: svo-im/awg0's catch-all is
 * `{"category":"all","action":"exit","node":"0138f33f65c3"}` and `nodes.json` holds four ids, none of them
 * that one. The row read `Everything else  →  [    ]` and the collapsed summary said only "1 rule".
 *
 * Two halves, because the section is COLLAPSED by default and an operator who never opens it would never
 * learn that a rule routes nothing:
 *   · the summary counts it, separately from "can't run here" — one says this node's mode cannot match that
 *     target, the other says the place you told it to send the traffic is not there any more;
 *   · the picker keeps the stored value visible and nameable, which is the rule `exitOptionGroups` already
 *     states one scope up: "a stored selection that has since broken must stay visible and nameable".
 *
 * Run: node tests/rule_dest_gone_selftest.mjs   --perturb  removes both and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC = path.join(ROOT, "js", "routing.js");
let mod = SRC;
if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  const cuts = [
    ["...(_gone ? [{ value: _gone.value, label: _gone.label, className: \"bad\", refuse: _gone.why }] : []),", ""],
    ["let dead = _nr ? list.filter(_gone).length + (_gone(catchAll) ? 1 : 0) : 0;", "let dead = 0;"],
  ];
  for (const [a, b] of cuts) {
    // ⚠️ ASSERT, DON'T HOPE — a replacement that matches nothing leaves a clean pass behind.
    if (!s.includes(a)) { console.log("ANCHOR MISSING: " + a.slice(0, 60)); process.exit(1); }
    s = s.replace(a, b);
  }
  mod = path.join(ROOT, "js", "__perturb_destgone.js");
  fs.writeFileSync(mod, s);
}
const { rulesSummary } = await import(pathToFileURL(mod).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
if (PERTURB) fs.unlinkSync(mod);

// The live shape, trimmed: one node that exists, holding one exit, and a rule naming a node that does not.
const NID = "1f64fe9ed5d6";
Store.nodes = [{ id: NID, name: "svo-im", routing_mode: "kernel",
                 exits: [{ id: "a5da1249", label: "Docker WARP", producer: "imported" }] }];
const rows = n => [{ _gid: "g1", enabled: true, badges: [], action: "direct" }].slice(0, n);
const txt = v => JSON.stringify(v);                     // the summary is a vnode; its text is in the tree

console.log("[1] a destination that is gone is COUNTED, in the line you see without expanding anything");
const gone = { enabled: true, category: "all", action: "exit", node: "0138f33f65c3" };
check("a catch-all naming a removed node is counted",
      /pointing nowhere/.test(txt(rulesSummary(NID, rows(1), gone))), txt(rulesSummary(NID, rows(1), gone)));
check("…and a ROW naming one is counted too",
      /pointing nowhere/.test(txt(rulesSummary(NID, [{ _gid: "g1", enabled: true, badges: [], action: "exit", node: "nosuchnode" }], null))));
check("…as is a row naming an exit this node does not have",
      /pointing nowhere/.test(txt(rulesSummary(NID, [{ _gid: "g1", enabled: true, badges: [], action: "dev", exit_id: "deadbeef" }], null))));

console.log("\n[2] ⚠️ …and NOT counted when the destination is fine, or there is nothing to judge");
check("a catch-all naming a node that EXISTS is not flagged",
      !/pointing nowhere/.test(txt(rulesSummary(NID, rows(1), { enabled: true, category: "all", action: "exit", node: NID }))));
check("…nor is one naming an exit this node HAS",
      !/pointing nowhere/.test(txt(rulesSummary(NID, rows(1), { enabled: true, category: "all", action: "dev", exit_id: "a5da1249" }))));
check("…nor `direct`, which names no destination at all",
      !/pointing nowhere/.test(txt(rulesSummary(NID, rows(1), { enabled: true, category: "all", action: "direct" }))));
check("…nor `block`", !/pointing nowhere/.test(txt(rulesSummary(NID, rows(1), { enabled: true, category: "all", action: "block" }))));
check("…nor silence — no catch-all is the node default, not a broken one",
      !/pointing nowhere/.test(txt(rulesSummary(NID, rows(1), null))));
// A legacy row is re-emitted verbatim and is not ours to judge — the same exemption the engine gate takes.
check("⚠️ …and a LOCKED row is left alone, like every other verdict here",
      !/pointing nowhere/.test(txt(rulesSummary(NID, [{ _gid: "g1", locked: true, action: "exit", node: "nosuchnode" }], null))));

console.log("\n[3] the two facts stay separate — they are different problems with different answers");
const both = rulesSummary(NID, [{ _gid: "g1", enabled: true, badges: [], action: "exit", node: "nosuchnode" }], gone);
check("`can't run here` and `pointing nowhere` are not folded into one count",
      /pointing nowhere/.test(txt(both)), txt(both));

console.log("\n[4] the picker keeps the stored value visible, rather than rendering a blank");
const js = fs.readFileSync(SRC, "utf8");
check("`destOpts` is told which value the control is holding",
      /const destOpts = \(withDefault, held\) =>/.test(js));
check("…and both controls tell it — the row and the catch-all",
      /options=\$\{destOpts\(false, destVal\(row\)\)\}/.test(js) && /options=\$\{destOpts\(true, catchVal\)\}/.test(js));
check("…a gone destination is appended as a REFUSING row, not a selectable one",
      /refuse: _gone\.why/.test(js) && /className: "bad"/.test(js));
check("…and it is derived from the SAME lists the options are built from",
      /!others\.some\(n => n\.id === x\)/.test(js) && /!\(exits\.some\(e => String\(e\.id\) === x\)\)/.test(js));

console.log("\n[5] ⚠️ …and asking the question must not take the screen down with it");
// `_nrec` is a `.find()` over Store.nodes and can be undefined — every other line in RoutingRules says
// `(_nrec || {})` for exactly that reason. `goneDest` said `_nrec.exits`, so a control holding a `dev|<id>`
// value threw `Cannot read properties of undefined` and killed the WHOLE RoutingRules render whenever the
// node record was not in the store: a node deleted while its sheet is open, or any render landing before
// /api/state has answered. A blank dropdown is the bug this file is about; a blank SCREEN is worse.
//
// Run the shipped expression rather than read it: lift the function out of the source and give it the
// scope RoutingRules would, with `_nrec` undefined — which is the state that crashed.
const _g = js.match(/const goneDest = v => \{[\s\S]*?\n  \};/);
check("goneDest was found in the source", !!_g, "it moved — this section is blind");
if (_g) {
  const make = (nrec, others, exits) =>
    new Function("T", "_nrec", "others", "exits",
                 _g[0] + "\n  return goneDest;")(x => x, nrec, others, exits);
  let threw = null, out;
  try { out = make(undefined, [], [])("dev|deadbeef"); } catch (e) { threw = String(e && e.message); }
  check("⚠️ a `dev|` value with NO node record does not throw", threw === null, threw);
  check("…and still reports the destination as gone", !!out && /no longer here/.test(out.label || ""), JSON.stringify(out));
  // the arms that always worked must keep working
  threw = null;
  try { out = make(undefined, [], [])("exit|nosuchnode"); } catch (e) { threw = String(e && e.message); }
  check("…and neither does an `exit|` value", threw === null, threw);
  const _live = { id: "x1" };
  check("…while a `dev|` value the node DOES have is not flagged",
        make({ exits: [_live] }, [], [_live])("dev|x1") === null);
  check("…and a `dev|` value it does not have still is",
        !!make({ exits: [_live] }, [], [_live])("dev|other"));
}

console.log("\n[6] ⚠️ …and a count that cannot see fails safe, like the one beside it");
// `off` deliberately stays 0 when the node record has not loaded — "the gate would refuse everything, so
// this counts nothing rather than announcing that every rule is broken". `dead` had the opposite reflex:
// an empty Store.nodes makes `known` empty, so EVERY action:"exit" rule counts as pointing nowhere and the
// collapsed summary reads "3 rules · 3 rules pointing nowhere" on a perfectly healthy interface, on any
// render that lands before /api/state has answered. [[lesson-detection-failure-fail-safe]]
const _saved = Store.nodes;
Store.nodes = [];
const _blind = txt(rulesSummary(NID, [{ _gid: "g1", enabled: true, badges: [], action: "exit", node: NID }], gone));
check("an unloaded node store reports NOTHING, not everything", !/pointing nowhere/.test(_blind), _blind);
Store.nodes = _saved;
check("⚠️ CONTROL: with the store loaded it reports again",
      /pointing nowhere/.test(txt(rulesSummary(NID, rows(1), gone))));

done(PERTURB, "the count and the picker row both removed");
