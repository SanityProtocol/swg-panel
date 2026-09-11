/* Self-test: every list grouped by node follows the ORDER THE OPERATOR SET.
 *
 * The Nodes screen is drag-reorderable and the position is persisted per node (`pos`, POST /api/order).
 * The server sorts every node list it builds by it —
 *
 *     sorted(nodes.items(), key=lambda kv: (kv[1].get("pos", 1 << 30), kv[1].get("created", 0), kv[0]))
 *
 * — so `Store.nodes`, and the `Store.fleet` projection built from it, arrive in that order already.
 *
 * ⚠️ AND SEVEN SCREENS THREW IT AWAY. Each one grouped by node and then re-sorted the groups
 * ALPHABETICALLY by display name. An operator who dragged their busiest server to the top of the Nodes
 * screen found it third in the peer sheet, the interface picker, the turn list and the mesh grid, with
 * nothing on screen explaining why those disagreed with the screen they had just arranged. Reordering is a
 * statement of intent; a list that re-sorts it is discarding an answer the operator already gave.
 *
 * One comparator now, `Store.byNode`, so a new list cannot quietly reintroduce the alphabetical version.
 *
 * Run: node tests/node_order_selftest.mjs    --perturb  puts an alphabetical sort back, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
// ⚠️ THIS FLAG USED TO DO NOTHING. It was read, threaded into `done()`, and never applied — so the gate
// announced a perturbation mode it did not have, and `--perturb` reported "the fix was removed and every
// check still passed" about a tree that had not been touched. A perturbation that perturbs nothing is a
// gate that has never been shown to catch the bug it guards. [[lesson-perturb-the-verifier]]
const SRC = path.join(ROOT, "js", "store.js");
let mod = SRC;
if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  const a = "return this.nodeRank(a) - this.nodeRank(b)";
  if (!s.includes(a)) { console.log("ANCHOR MISSING: " + a); process.exit(1); }
  // the shipped regression: order by display name, discarding the operator's `pos`
  s = s.replace(a, "return 0 * (this.nodeRank(a) - this.nodeRank(b))");
  mod = path.join(ROOT, "js", "__perturb_nodeorder.js");
  fs.writeFileSync(mod, s);
}
const { Store } = await import(pathToFileURL(mod).href);
if (PERTURB) fs.unlinkSync(mod);

// A fleet in an order the alphabet would NOT produce — otherwise the two rules agree and the gate is blind.
// zulu first, alpha last: any check that passes under alphabetical sorting is measuring nothing.
Store.fleet = [
  { id: "n-zulu",  name: "zulu",  color: null },
  { id: "n-mike",  name: "mike",  color: null },
  { id: "n-alpha", name: "alpha", color: null },
];
const IDS = Store.fleet.map(n => n.id);

console.log("[1] the comparator follows the fleet, not the alphabet");
check("the fixture is not already alphabetical",
      JSON.stringify(Store.fleet.map(n => n.name)) !== JSON.stringify([...Store.fleet.map(n => n.name)].sort()),
      "the fixture would pass under either rule — it proves nothing");
const shuffled = ["n-alpha", "n-zulu", "n-mike"];
let sorted = [...shuffled].sort((a, b) => Store.byNode(a, b));
check("⚠️ a shuffled list comes back in fleet order", JSON.stringify(sorted) === JSON.stringify(IDS), sorted.join(","));
check("…which is NOT alphabetical order",
      JSON.stringify(sorted) !== JSON.stringify(["n-alpha", "n-mike", "n-zulu"]), sorted.join(","));
check("nodeRank is the position in the fleet", Store.nodeRank("n-mike") === 1, Store.nodeRank("n-mike"));

console.log("\n[2] …and it degrades safely while /api/state is still arriving");
// An unknown node must sort AFTER every known one. To the FRONT would look deliberate — a stranger at the
// top of a list the operator arranged reads as "this one matters most". [[lesson-detection-failure-fail-safe]]
sorted = ["n-ghost", "n-mike", "n-zulu"].sort((a, b) => Store.byNode(a, b));
check("an unknown node sorts last, not first", sorted[sorted.length - 1] === "n-ghost", sorted.join(","));
check("…and the known ones keep their order", JSON.stringify(sorted.slice(0, 2)) === JSON.stringify(["n-zulu", "n-mike"]), sorted.join(","));
// two unknowns must not swap on every render — an unstable comparator makes rows jump under the cursor
const twice = [["n-g2", "n-g1"], ["n-g1", "n-g2"]].map(l => [...l].sort((a, b) => Store.byNode(a, b)).join(","));
check("two unknown nodes order deterministically", twice[0] === twice[1], twice.join(" vs "));
const savedFleet = Store.fleet;
Store.fleet = [];
check("an EMPTY fleet does not throw", (() => { try { ["a", "b"].sort((x, y) => Store.byNode(x, y)); return true; } catch (_) { return false; } })());
Store.fleet = savedFleet;

console.log("\n[2b] ⚠️ …and a peer with NO deployment does not take the sheet down with it");
// `nodeName(id)` is `(n && n.name) || id`, so an undefined id comes back undefined and `.localeCompare`
// throws. `AddPeersSheet` sorts by `rep(p).node` where an UNASSIGNED peer has no deployment at all — two of
// those tie on rank, the tiebreak runs, and Array.sort throws inside the comparator: the sheet renders
// nothing. The call sites this comparator replaced all guarded with `|| ""`.
const safe = (label, fn) => { try { fn(); return true; } catch (_) { return false; } };
check("byNode(undefined, undefined) does not throw", safe("", () => Store.byNode(undefined, undefined)));
check("…nor byNode(null, null)", safe("", () => Store.byNode(null, null)));
check("…nor one undefined against a real node", safe("", () => Store.byNode(undefined, "n-mike")));
check("…and a list of peers with no deployment sorts",
      safe("", () => [{ n: undefined }, { n: undefined }].sort((x, y) => Store.byNode(x.n, y.n))));
check("…while two unknown-but-named ids still tie-break on the name",
      Store.byNode("zzz", "aaa") > 0, Store.byNode("zzz", "aaa"));

console.log("\n[3] ⚠️ …and every screen that groups by node uses it");
// The point of one comparator is that there is only one. A file that sorts by nodeName again has
// reintroduced the bug locally, where the next reader will not think to look.
const FILES = ["screen-roster.js", "grids.js", "turn.js", "screen-settings.js", "screen-nodes.js", "sheets-crud.js"];
let offenders = [];
for (const f of FILES) {
  const src = fs.readFileSync(path.join(ROOT, "js", f), "utf8");
  check(`${f} sorts by Store.byNode`, /Store\.byNode\(/.test(src), "no fleet-ordered sort in this file");
  if (/nodeName\([^)]*\)[^\n]*localeCompare\(\s*Store\.nodeName/.test(src)) offenders.push(f);
}
check("⚠️ no screen sorts nodes alphabetically any more", offenders.length === 0, offenders.join(", "));
// …and the comparator itself is allowed to use the name — as the TIEBREAK, which is a different thing.
const st = fs.readFileSync(path.join(ROOT, "js", "store.js"), "utf8");
check("the one name comparison left is byNode's own tiebreak",
      /nodeRank\(a\) - this\.nodeRank\(b\)\s*\n?\s*\|\| String\(this\.nodeName\(a\)/.test(st),
      "byNode no longer reads `rank, then name` — or the name is not the tiebreak any more");
check("…and both sides of that tiebreak are guarded against an absent id",
      (st.match(/String\(this\.nodeName\([ab]\) \|\| ""\)/g) || []).length === 2,
      "an undefined node id would throw inside Array.sort again");

console.log("\n[4] …and the server still hands the fleet over in that order");
// If this stops being true the comparator is sorting by an order nobody set. Two builders, both asserted.
const srv = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
const posSorts = srv.match(/sorted\(nodes\.items\(\), key=lambda kv: \(kv\[1\]\.get\("pos"/g) || [];
check("the server sorts its node lists by `pos`", posSorts.length >= 2, `${posSorts.length} builder(s) do`);
check("…and the SPA's fleet projection preserves that order",
      /this\.fleet = this\.nodes\.map\(/.test(st), "fleet is rebuilt some other way — the order may not survive");

done(PERTURB, "an alphabetical sort restored");
