/* Self-test: the SPA's side of the forks and apps hidden on the operator's word (2026-10-14) — MYSOREZ, Moroka8 and
 * xxcipherx join cacggghp; the MYSOREZ app and XXcipherX's leave every visible fork (the panel's turn_hidden_forks gate).
 *
 * [1] the install pickers (enabledTurnForks) skip a hidden fork even where the stored list names it — the default list
 *     still does (MYSOREZ, Moroka8, xxcipherx); an adopt sheet that detected one on the box keeps it (its `keep`), so
 *     adopting keeps the fork the server runs, and its dropdown shows it
 * [2] the Overview's traffic-by-fork row (enabledTurnForkIds) keeps a hidden fork the list names, so the proxies a node still
 *     runs keep their traffic there; the Overview reads that set, not the pickers'
 * [3] a WDTT fork's system default is its own app: the top-ranked entry, or the catalog's default_client — XXcipherX's
 *     one-tap app no longer stands in where a fork's own cannot open one-tap (its repository is gone)
 *
 * Imports js/turn.js as shipped (spa_env) against a served catalog shaped like /api/state.turn_catalog.
 * Run: node tests/spa_hidden_forks_selftest.mjs
 *      --perturb        enabledTurnForks lets a hidden fork through again → RED in [1]
 *      --perturb-chart  the Overview reads the pickers' set again (a hidden fork's traffic gone) → RED in [2]
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const PERTURB_CHART = process.argv.includes("--perturb-chart");
const { Store } = await spa("store.js");
const T = await spa("turn.js");
let { enabledTurnForks, enabledTurnForkIds, sysDefaultKey, TURN_FORKS_DEFAULT } = T;
if (PERTURB) { const { turnForkList } = await spa("turn-catalog.js");
  enabledTurnForks = keep => turnForkList().filter(f => enabledTurnForkIds().has(f.id) || f.id === keep); }

Store.turnCatalog = { servers: [
  { id: "WINGS-N", label: "WINGS-N", kind: "turn" },
  { id: "MYSOREZ", label: "MYSOREZ", kind: "turn", hidden: true },
  { id: "Moroka8", label: "Moroka8", kind: "turn", hidden: true },
  { id: "samosvalishe", label: "hack-diaz", kind: "turn" },
  { id: "amurcanov", label: "amurcanov", kind: "wdtt", product: "WDTT" },
  { id: "qwdtt", label: "SpaceNeuroX", kind: "wdtt", product: "qWDTT", default_client: "qwdtt" },
  { id: "xxcipherx", label: "XXcipherX", kind: "wdtt", product: "WDTT", hidden: true },
  { id: "cacggghp", label: "cacggghp", kind: "turn", hidden: true },
], clients: {} };

console.log("[1] the install pickers");
Store.panelSettings = {};   // no stored list: the default, which still names MYSOREZ, Moroka8 and xxcipherx
check("[1] the default list still names MYSOREZ, Moroka8 and xxcipherx (so the Overview keeps their traffic)",
      ["MYSOREZ", "Moroka8", "xxcipherx"].every(f => TURN_FORKS_DEFAULT.includes(f)), TURN_FORKS_DEFAULT);
const ids = enabledTurnForks().map(f => f.id);
check("[1] …yet no picker offers a hidden fork", !ids.some(f => ["MYSOREZ", "Moroka8", "xxcipherx", "cacggghp"].includes(f)), ids);
check("[1] …and the visible ones are offered", ["WINGS-N", "samosvalishe", "amurcanov", "qwdtt"].every(f => ids.includes(f)), ids);
Store.panelSettings = { enabled_turn_forks: ["WINGS-N", "Moroka8", "cacggghp"] };
check("[1] a stored list naming hidden forks offers only its visible ones", JSON.stringify(enabledTurnForks().map(f => f.id)) === '["WINGS-N"]',
      enabledTurnForks().map(f => f.id));
Store.panelSettings = {};
const kept = enabledTurnForks("xxcipherx").filter(f => f.kind === "wdtt").map(f => f.id);
check("[1] an adopt sheet that detected xxcipherx keeps it in its fork list", kept.includes("xxcipherx") && kept.includes("amurcanov"), kept);
const IF = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
check("[1] …both adopt sheets pass the fork they detected",
      IF.includes('const forks = enabledTurnForks(d.fork).filter(f => f.kind === "wdtt");')
      && IF.includes('const forks = enabledTurnForks(w.fork).filter(f => f.kind === "wdtt");'), "");

console.log("\n[2] the Overview's traffic by fork");
Store.panelSettings = { enabled_turn_forks: ["WINGS-N", "Moroka8", "cacggghp"] };
const en = enabledTurnForkIds();
check("[2] the chart's set keeps a hidden fork the list names (Moroka8, cacggghp)", en.has("Moroka8") && en.has("cacggghp") && !en.has("MYSOREZ"), [...en]);
const OV = fs.readFileSync(path.join(ROOT, "js", "screen-overview.js"), "utf8");
const ovRead = PERTURB_CHART ? OV.replace("const enSet = turnOn ? enabledTurnForkIds() : new Set();",
                                          "const enSet = new Set(turnOn ? enabledTurnForks().map(f => f.id) : []);") : OV;
check("[2] the Overview reads that set, not the pickers' (which drops hidden forks)",
      ovRead.includes("const enSet = turnOn ? enabledTurnForkIds() : new Set();") && !/enabledTurnForks\(/.test(ovRead), "");

console.log("\n[3] a WDTT fork's own app is its default");
const E = (cid, autostart) => ({ key: cid, cid, autostart });
const amur = Store.turnCatalog.servers.find(f => f.id === "amurcanov"), qw = Store.turnCatalog.servers.find(f => f.id === "qwdtt");
check("[3] amurcanov (its own app cannot open one-tap): the top-ranked entry, not XXcipherX's",
      sysDefaultKey(amur, [E("wdttapp", false), E("wdttplus", true), E("xxcipher", true)]) === null, sysDefaultKey(amur, [E("wdttapp", false), E("xxcipher", true)]));
check("[3] the catalog's default_client still wins (qWDTT)", sysDefaultKey(qw, [E("wdttplus", true), E("qwdtt", false)]) === "qwdtt",
      sysDefaultKey(qw, [E("wdttplus", true), E("qwdtt", false)]));
check("[3] no xxcipher left in the SPA's default rule", !/"xxcipher"/.test(fs.readFileSync(path.join(ROOT, "js", "turn.js"), "utf8")), "");

done(PERTURB || PERTURB_CHART);
