/* Self-test: a card pinned for NAT and a card used as an exit are TELLABLE APART (plan B1, decision 1).
 *
 * The feature makes it possible for `eth2` to appear twice in one dropdown meaning two different things:
 *   - `wan_iface`  — a NAT selector. Routing is untouched; only the source address the rule rewrites to.
 *   - an exit      — a route. `default via <gw> dev eth2` in the interface's own table.
 * "Direct" already meant two things before any of this (§2 of the plan). Replacing one confusion with a
 * worse one is the main risk in the whole feature, which is why naming was settled before it was built.
 *
 * First decision: NAME EACH BY WHAT IT CHANGES. Not enough — read in a list of destinations, "Source address
 * only" was still taken for a milder way of leaving by that card, twice, by the operator who commissioned
 * it. A row that has to be explained every time it is read is in the wrong list.
 *
 * SECOND decision: DEMOTE IT. The mode dropdown answers "where does traffic go", and the pin answers
 * nothing of the kind — it routes nothing. So it left that list entirely: it is `NatSourcePick`, which each
 * sheet renders under "Advanced settings", beside that protocol's own settings, with a sentence that leads
 * with what it does NOT do. [6] holds the placement at the SOURCE, because where a control lives is a fact
 * about the four sheets and not about the component.
 *
 * ⚠️ WHAT THIS GATES IS NOT PROSE. A test that string-matched the sentences would break on every wording
 * change and prove nothing. It holds the properties that make the two readable: the pin's group does not
 * merely name the card, the two rows for ONE card are different strings, a card is labelled differently
 * from a tunnel, and every list spells the card identically.
 *
 * Run: node tests/spa_nicnaming_selftest.mjs
 *      --perturb  drops the card's own label so it reads `Discovered` like any tunnel, and makes the pin
 *                 control render nothing. Expects RED on [1] and [5].
 */
import { spa, check, done } from "./spa_env.mjs";
import fs from "node:fs";
import path from "node:path";

const PERTURB = process.argv.includes("--perturb");
const ROOT = path.resolve(new URL(".", import.meta.url).pathname, "..");

// The perturbation is applied to a COPY of the module, imported instead of the real one — the labels live
// inside a component and a builder, with no seam to monkey-patch. Both anchors asserted, or the run tests
// nothing and reports a clean pass ([[perturbation-harness-cannot-report-green]]).
let mod = "routing.js";
if (PERTURB) {
  let src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
  for (const [a, b] of [
    ['_cand.proto === "nic" ? T("val|Network card") : T("val|Discovered")', 'T("val|Discovered")'],
    // ⚠️ THIS ANCHOR HAS ALREADY DRIFTED ONCE — it carried `if (!nics.length) return null;` and stopped
    // matching the moment that condition grew a second clause (`natPinApplies`). The assert fired rather
    // than false-passing, which is the design working, but a perturbation repaired by hand is one that was
    // not running in between. [[refactor-breaks-gate-anchors]]
    ['if (!nics.length || !natPinApplies(value)) return null;', 'if (true) return null;'],
  ]) {
    if (!src.includes(a)) throw new Error("perturbation anchor missing — this run would FALSE-PASS: " + a);
    src = src.replace(a, b);
  }
  mod = ".perturbed-routing.js";
  fs.writeFileSync(path.join(ROOT, "js", mod), src);
}
const { exitOptionGroups, exitLabel, EgressPicker, NatSourcePick } = await spa(mod);
const { Store } = await spa("store.js");
if (PERTURB) fs.unlinkSync(path.join(ROOT, "js", mod));

// eth0 is the WAN (refused), eth1 a usable second card, eth2 a card with no gateway (refused), tun0 a tunnel.
const NODE = {
  id: "n1", name: "n1", wan_iface: "eth0", ether_ifaces: ["eth0", "eth1", "eth2"],
  ip_ifaces: [{ ip: "203.0.113.9", iface: "eth0" }, { ip: "10.9.0.2", iface: "eth1" },
              { ip: "192.0.2.2", iface: "eth2" }],
  exits: [],
  exit_candidates: [
    { name: "eth1", proto: "nic", offerable: true, gw: "10.9.0.1" },
    { name: "eth0", proto: "nic", offerable: false, why_not: "nic_wan", gw: "203.0.113.1" },
    { name: "eth2", proto: "nic", offerable: false, why_not: "nic_nogw", gw: "" },
    { name: "tun0", proto: "tun", offerable: true },
  ],
};
Store.nodes = [NODE];

const flat = o => exitOptionGroups(NODE, o).flatMap(g => (g.items || [g]).map(i => ({ ...i, group: g.group })));
const IFACE = { prefix: "exit|", devices: true }, RULE = { prefix: "dev|", devices: true }, NODEP = { prefix: "", devices: true };

console.log("\n[1] a card offered as an EXIT says it is a card");
const dev = flat(IFACE);
const eth1 = dev.find(i => String(i.value).endsWith("dev:eth1"));
const tun0 = dev.find(i => String(i.value).endsWith("dev:tun0"));
check("the usable card is offered", !!eth1, dev.map(i => i.value).join(", "));
check("…and does not read the same as a tunnel", eth1 && tun0 && eth1.label !== tun0.label,
      eth1 && tun0 ? `${eth1.label} vs ${tun0.label}` : "");
check("…the tunnel still reads as a discovered device", tun0 && /Discovered/.test(tun0.label), tun0 && tun0.label);
check("…and the card names what it is", eth1 && /card/i.test(eth1.label), eth1 && eth1.label);

console.log("\n[2] a card the panel refuses is offered by NO list");
for (const [name, o] of [["interface", IFACE], ["rule", RULE], ["node default", NODEP]]) {
  const vals = flat(o).map(i => String(i.value));
  check(`${name}: the node's own WAN is not offered`, !vals.some(v => v.endsWith("dev:eth0")), vals.join(", "));
  check(`${name}: the card with no gateway is not offered`, !vals.some(v => v.endsWith("dev:eth2")), vals.join(", "));
}

console.log("\n[3] every list spells the card the same way");
const nameIn = o => (flat(o).find(i => String(i.value).endsWith("dev:eth1")) || {}).label;
check("interface, rule and node-default agree on the card's name",
      nameIn(IFACE) && nameIn(IFACE) === nameIn(RULE) && nameIn(RULE) === nameIn(NODEP),
      [nameIn(IFACE), nameIn(RULE), nameIn(NODEP)].join(" | "));

console.log("\n[4] ⚠️ the mode list answers WHERE TRAFFIC GOES — and offers no NAT pin");
// Walk the picker's real vnode tree, keeping each Dropdown's options separately and in order: the first is
// the mode list, any later one belongs to a control below it.
function dropdowns(value) {
  const found = [];
  const walk = n => {
    if (n == null || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(walk);
    const p = n.props || {};
    if (Array.isArray(p.options)) found.push(p.options.flatMap(o => (o && o.items) ? o.items.map(i => ({ ...i, group: o.group })) : [o]).filter(Boolean));
    walk(p.children);
  };
  walk(EgressPicker({ node: "n1", value, onChange() {}, noRules: true }));
  return found;
}
const modeRows = dropdowns({ mode: "auto" })[0] || [];
const vals = modeRows.map(r => String(r.value));
check("the mode list offers no `direct|<nic>` row at all", !vals.some(v => v.startsWith("direct|")), vals.join(", "));
check("…while the card as an EXIT is still there", vals.includes("exit|dev:eth1"), vals.join(", "));
check("…and nothing in it is grouped as a source", !modeRows.some(r => /source/i.test(String(r.group || ""))),
      modeRows.map(r => r.group).filter(Boolean).join(" | "));

console.log("\n[5] ⚠️ the pin is its own control, and it says what it is NOT");
const pinTree = NatSourcePick({ node: "n1", value: { mode: "direct", nic: "eth1" }, onChange() {} });
check("it renders a control at all", !!pinTree, String(pinTree));
const pinOpts = [];
const pinHints = [];
(function walk(n) {
  if (n == null || typeof n !== "object") return;
  if (Array.isArray(n)) return n.forEach(walk);
  const p = n.props || {};
  if (Array.isArray(p.options)) p.options.forEach(o => pinOpts.push(String((o || {}).value ?? "")));
  if (typeof p.class === "string" && p.class.includes("hint")) {
    const t = []; (function txt(x) { if (x == null) return; if (Array.isArray(x)) return x.forEach(txt);
      if (typeof x === "object") return txt((x.props || {}).children); t.push(String(x)); })(p.children);
    pinHints.push(t.join(""));
  }
  walk(p.children);
})(pinTree);
check("…offering every card, and a way to unpin",
      pinOpts.includes("eth1") && pinOpts.includes(""), pinOpts.join(", "));
// ⚠️ MATCHED ON THE PROPERTY, NOT THE WORDING. This was `/NOT send/i`, which broke the moment a copy pass
// turned "does NOT send" into "doesn't send" — the sentence still did its job and the gate went red. The
// claim being held is "it opens by denying that it sends traffic", so the alternation covers how that can
// be phrased rather than one spelling of it.
const pinHint = pinHints.find(h => /(does not|doesn'?t|don'?t) send traffic/i.test(h)) || "";
check("⚠️ its sentence leads with what it does NOT do", !!pinHint, pinHints.join(" ~~ ").slice(0, 200));
check("…and points at the control that does what the reader probably wanted",
      /Leave by a device/i.test(pinHint), pinHint);
// A node that reports no cards has nothing to pin to, and a dead dropdown is worse than no control.
Store.nodes = [{ id: "n1", name: "n1", exits: [], exit_candidates: [] }];
check("a node with no cards gets no control at all",
      NatSourcePick({ node: "n1", value: { mode: "auto" }, onChange() {} }) === null);
Store.nodes = [NODE];

console.log("\n[6] ⚠️ …and every sheet puts it under Advanced settings");
// WHERE a control lives is a fact about the sheets, so it is read from their source. All four render the
// same picker; the two turn sheets had no Advanced section at all before this, and skipping them would
// have deleted the control for that whole kind rather than demoting it.
const SHEETS = [["js/iface.js", 2], ["js/turn.js", 2]];
for (const [file, want] of SHEETS) {
  const src = fs.readFileSync(path.join(ROOT, file), "utf8");
  const uses = (src.match(/<\$\{NatSourcePick\}/g) || []).length;
  check(`${file} renders it ${want}\u00d7`, uses === want, "found " + uses);
  // each use must sit inside an "Advanced settings" disclosure — checked by looking back from the use to
  // the nearest Disclosure title before it.
  let ok = true, at = 0;
  for (let i = 0; i < uses; i++) {
    at = src.indexOf("<${NatSourcePick}", at + 1);
    const before = src.slice(0, at);
    const lastDisc = before.lastIndexOf('<${Disclosure} title=${T("');
    const title = src.slice(lastDisc, at).match(/title=\$\{T\("([^"]+)"\)\}/);
    if (!title || title[1] !== "Advanced settings") ok = false;
  }
  check(`…each one inside an "Advanced settings" section`, ok);
}

done(PERTURB, "the card called `Discovered` and the pin control rendering nothing");
