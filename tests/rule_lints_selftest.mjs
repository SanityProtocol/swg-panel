/* Self-test: a routing row's lints judge a rule only against rows that reach the SAME devices (ROUTING-PEERS-MESH P1, review S1).
 *
 * "already sent somewhere else above" says a badge can never fire because an earlier row takes it. That is true when the
 * earlier row is for everyone — and false when it is for chosen people: the headline per-person layout, "alice's YouTube by
 * one node, everyone else's by another", read as a dead second rule, amber, inviting its deletion (which would send everyone
 * else's YouTube to "Everything else"). The P1 rig proves the second rule fires for everyone not chosen (cells K5/K6).
 * "a more specific rule below wins these hosts" had the mirror blind spot: a rule below that is for chosen people takes the
 * hosts for its people only — the node keeps them on the upper rule for everyone else (shadow sets, swg-noded 129af8b).
 *
 * Run: node tests/rule_lints_selftest.mjs   --perturb  makes every row count as reaching every device, and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC = path.join(ROOT, "js", "rulerows.js");
let mod = SRC;
if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  // Anchored on the declaration, not its body: the body grew an audience term (D9) and stranded a whole-text anchor.
  // `true || …` short-circuits whatever the body says — every row reaches every device, as before.
  const a = "export const rowCovers = (a, b) => ";
  if (s.split(a).length !== 2) { console.log("ANCHOR MISSING: rowCovers"); process.exit(1); }
  mod = path.join(ROOT, "js", "__perturb_rowlints.js");
  fs.writeFileSync(mod, s.replace(a, "export const rowCovers = (a, b) => true || "));
}
const { rulesToRows, rowLints } = await import(pathToFileURL(mod).href);
if (PERTURB) fs.unlinkSync(mod);

const ALICE = { on: true, users: ["u1"], groups: [], peers: [] }, BOB = { on: true, users: ["u2"], groups: [], peers: [] };
const r = (targets, action, who, extra = {}) => ({ enabled: who ? false : true, category: "custom", targets, action,
                                                    ...(action === "exit" ? { node: "n2" } : {}), ...(who ? { who } : {}), ...extra });
const dest = x => x.action === "exit" ? "exit|" + (x.node || "") : x.action;
const lint = rules => rowLints(rulesToRows(rules).rows, dest);
const n = b => b.length;

console.log("[1] a badge an earlier row already sends somewhere");
let L = lint([r("203.0.113.0/24", "exit", ALICE), r("203.0.113.0/24", "direct")]);
check("alice's rule, then the same target for everyone: the second rule is NOT dead (it fires for everyone else)", n(L[1].dupes) === 0, L[1]);
L = lint([r("203.0.113.0/24", "exit"), r("203.0.113.0/24", "direct")]);
check("CONTROL — two rules for everyone: the second is dead, as before", n(L[1].dupes) === 1, L[1]);
L = lint([r("203.0.113.0/24", "exit"), r("203.0.113.0/24", "direct", ALICE)]);
check("a rule for everyone, then alice's: hers is dead (everyone's reaches her first)", n(L[1].dupes) === 1, L[1]);
L = lint([r("203.0.113.0/24", "exit", ALICE), r("203.0.113.0/24", "direct", { ...ALICE, users: ["u1"] })]);
check("the same selection twice: the second is dead", n(L[1].dupes) === 1, L[1]);
L = lint([r("203.0.113.0/24", "exit", ALICE), r("203.0.113.0/24", "direct", BOB)]);
check("two different selections: neither is dead", n(L[1].dupes) === 0, L[1]);
L = lint([r("203.0.113.0/24, 203.0.113.0/24", "exit")]);
check("one badge twice in one row is still caught", n(L[0].dupes) === 1, L[0]);

console.log("\n[2] a more specific rule below");
L = lint([r("example.com", "exit"), r("shop.example.com", "direct")]);
check("CONTROL — a rule for everyone below takes the hosts for everyone this row is for", n(L[0].takenBy) === 1 && n(L[0].takenFew) === 0, L[0]);
L = lint([r("example.com", "exit"), r("shop.example.com", "direct", ALICE)]);
check("alice's rule below takes them for her alone — said as such, not as for everyone", n(L[0].takenBy) === 0 && n(L[0].takenFew) === 1, L[0]);
L = lint([r("example.com", "exit", ALICE), r("shop.example.com", "direct", ALICE)]);
check("…while a rule below for the same selection takes them for everyone this row is for", n(L[0].takenBy) === 1, L[0]);
L = lint([r("example.com", "exit", ALICE), r("shop.example.com", "direct", BOB)]);
check("alice's row above bob's more specific row: nothing said (which people they share is the panel's to resolve)",
      n(L[0].takenBy) === 0 && n(L[0].takenFew) === 0, L[0]);
L = lint([r("example.com", "exit"), r("shop.example.com", "direct", ALICE), r("shop.example.com", "block")]);
check("one host taken by both kinds of rule below is said once, as the wider claim", n(L[0].takenBy) === 1 && n(L[0].takenFew) === 0, L[0]);

console.log("\n[3] a stored selection of the wrong shape (the panel names nobody with it) does not break the editor");
let threw = "";
try { L = lint([r("203.0.113.0/24", "exit", { on: true, users: 5, groups: "g1", peers: [["p"]] }), r("203.0.113.0/24", "direct")]); }
catch (e) { threw = String(e); }
check("rulesToRows and the lints take it without throwing, and read it as nobody", !threw && n(L[1].dupes) === 0, threw);

console.log("\n[4] a list with no per-person rule lints exactly as it did");
const plain = [r("198.51.100.0/24", "exit"), r("198.51.100.0/24, example.org", "direct"), r("shop.example.org", "block")];
L = lint(plain);
check("the dead badge and the more specific rule below are reported as before, nothing as `takenFew`",
      n(L[1].dupes) === 1 && n(L[1].takenBy) === 1 && L.every(x => n(x.takenFew) === 0), L);

console.log("\n[5] a node's default list: audiences (P3, D9)");
L = lint([r("example.org", "exit"), r("shop.example.org", "direct", null, { aud: "local" })]);
check("a rule for one AUDIENCE below takes the hosts for that audience alone — `takenFew`, never nothing",
      n(L[0].takenBy) === 0 && n(L[0].takenFew) === 1, L[0]);
L = lint([r("example.org", "exit", null, { aud: "local" }), r("shop.example.org", "direct", null, { aud: "cascaded" })]);
check("…and two different audiences are not compared (they reach no traffic in common)",
      n(L[0].takenBy) === 0 && n(L[0].takenFew) === 0, L[0]);
L = lint([r("example.org", "exit", null, { aud: "cascaded" }), r("shop.example.org", "direct")]);
check("…while a rule for both below takes them for everyone the narrowed row is for", n(L[0].takenBy) === 1, L[0]);

done(PERTURB, "every row reaches every device");
