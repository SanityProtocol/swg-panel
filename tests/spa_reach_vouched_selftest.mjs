/* Self-test: the create sheet's device-access warning reads `reach_vouched` through the fork list the SPA rebuilds.
 *
 * DEVICE ACCESS (docs/DEVICE-ACCESS-PLAN.md §11.2 F4). The panel publishes `reach_vouched` on every WDTT and csqtt server in
 * `turn_catalog`: whether the build a CREATE installs can prove which user a device belongs to. The create sheet reads it off
 * `enabledTurnForks()`, which is `turnForkList()` — a WHITELIST rebuild of each catalog entry. Written without the key there,
 * the panel sent `true` for amurcanov and the sheet saw `undefined`, so every WDTT create warned that no device could reach
 * any other.
 *
 * ⚠️ FOUND IN A BROWSER, NOT BY A GATE. The python gate checked that the panel emits the key and that iface.js reads it; the
 * seam between the two — this rebuild — was read by nobody. So this gate drives the rebuild itself.
 *
 * Run: node tests/spa_reach_vouched_selftest.mjs     --perturb  drops the key from the rebuild and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC = path.join(ROOT, "js", "turn-catalog.js");
let mod = SRC;
if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  const a = "reach_vouched: s.reach_vouched === true,";
  if (!s.includes(a)) { console.log("ANCHOR MISSING"); process.exit(1); }
  s = s.replace(a, "");
  mod = path.join(ROOT, "js", "__perturb_turn_catalog.js");
  fs.writeFileSync(mod, s);
}
const { turnForkList } = await import(pathToFileURL(mod).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
if (PERTURB) fs.unlinkSync(mod);

// the catalog as swg-panel-server `turn_catalog_view()` sends it: the key on self-contained kinds only
Store.turnCatalog = { clients: {}, servers: [
  { id: "amurcanov", kind: "wdtt", reach_vouched: true },
  { id: "xxcipherx", kind: "wdtt", reach_vouched: false },
  { id: "csqtt", kind: "csqtt", reach_vouched: false },
  { id: "WINGS-N", kind: "turn" },
] };
const f = Object.fromEntries(turnForkList().map(x => [x.id, x]));

console.log("\n[1] the fork list the create sheet reads carries the panel's word");
check("a vouched WDTT build stays vouched", !!f.amurcanov && f.amurcanov.reach_vouched === true, JSON.stringify(f.amurcanov));
check("an unvouched WDTT build stays unvouched", !!f.xxcipherx && f.xxcipherx.reach_vouched === false, JSON.stringify(f.xxcipherx));
check("csqtt stays unvouched", !!f.csqtt && f.csqtt.reach_vouched === false, JSON.stringify(f.csqtt));
check("a turn proxy, with no devices of its own, is never vouched", !!f["WINGS-N"] && f["WINGS-N"].reach_vouched === false);

console.log("\n[2] …and the create sheet decides from that list");
const ifaceSrc = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
check("a WDTT create warns from the chosen fork's entry",
      /isWdtt \? !\(_wdttForks\.find\(f => f\.id === fork\) \|\| \{\}\)\.reach_vouched/.test(ifaceSrc));
check("a csqtt create warns from the chosen build's entry",
      /isCsqtt \? !\(_csqttForks\.find\(f => f\.id === cfork\) \|\| \{\}\)\.reach_vouched/.test(ifaceSrc));

done(PERTURB, "turnForkList drops reach_vouched");
