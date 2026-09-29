/* Self-test: forks listed side by side never share a name.
 *
 * The Overview's "Traffic by turn-proxy" and "Deployments by turn-proxy" labelled each fork by its AUTHOR (`forkLabel`), and
 * amurcanov ships two servers — a WDTT one and a CSQTT one — so both rings and both legends drew two rows reading
 * "amurcanov" (1.8.8 qualification, O1). `forkNames` gives the author as before and "author · product" only where two
 * listed forks share an author, so the rows that were unambiguous do not grow.
 *
 * Imports js/turn-catalog.js as shipped (spa_env) against a served catalog shaped like /api/state.turn_catalog, and
 * checks that every name the Overview's turn rings draw comes from it.
 *
 * Run: node tests/spa_fork_names_selftest.mjs
 *      --perturb   forkNames back to the author alone and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const { Store } = await spa("store.js");
let { forkNames, forkLabel } = await spa("turn-catalog.js");
if (PERTURB) forkNames = fs => Object.fromEntries((fs || []).map(f => [f, forkLabel(f)]));
Store.turnCatalog = { servers: [
  { id: "amurcanov", label: "amurcanov", product: "WDTT", kind: "wdtt" },
  { id: "csqtt", label: "amurcanov", product: "CSQTT", kind: "csqtt" },
  { id: "qwdtt", label: "SpaceNeuroX", product: "qWDTT", kind: "wdtt" },
  { id: "WINGS-N", label: "WINGS-N", kind: "turn" },
] };

const all = forkNames(["amurcanov", "csqtt", "qwdtt", "WINGS-N"]);
console.log("[two forks by one author, side by side]");
check("amurcanov's WDTT and CSQTT servers get different names", all.amurcanov !== all.csqtt, all);
check("…each saying its product", all.amurcanov === "amurcanov · WDTT" && all.csqtt === "amurcanov · CSQTT", all);
check("a fork alone under its author keeps the short name", all.qwdtt === "SpaceNeuroX" && all["WINGS-N"] === "WINGS-N", all);
const one = forkNames(["amurcanov", "qwdtt"]);
check("with only ONE amurcanov fork listed, it stays \"amurcanov\"", one.amurcanov === "amurcanov", one);

console.log("\n[the Overview draws every turn-proxy name from it]");
const src = fs.readFileSync(path.join(ROOT, "js", "screen-overview.js"), "utf8");
check("no ring or legend row takes forkLabel(fk) directly", !/name: forkLabel\(fk\)/.test(src));
check("all six names come from forkNames (two traffic rings, two deployment rings, two legends)",
      (src.match(/name: fkName\[fk\]/g) || []).length === 6 && /const fkName = forkNames\(forks\)/.test(src));

done(PERTURB);
