/* Self-test: the SPA's side of the forks and apps hidden on the operator's word (2026-10-14) — MYSOREZ, Moroka8 and
 * xxcipherx join cacggghp; the MYSOREZ app and XXcipherX's leave every visible fork (the panel's turn_hidden_forks gate).
 *
 * [1] the install pickers (enabledTurnForks) skip a hidden fork even where the stored list names it — the default list
 *     still does (MYSOREZ, Moroka8, xxcipherx); an adopt sheet that detected one on the box keeps it (its `keep`), so
 *     adopting keeps the fork the server runs, and its dropdown shows it
 * [2] the Overview's traffic-by-fork row (enabledTurnForkIds) holds every hidden fork whatever the stored list says (a hidden
 *     fork has no switch to tick back), so the proxies a node still runs keep their traffic there; the Overview reads that set, not the pickers'
 * [3] a WDTT fork's system default is its own app, the top of the real ranking (pickerEntries → turnForkPlatforms) even
 *     where it cannot open one-tap and a friendly app can — XXcipherX's one-tap app no longer stands in (its repository is
 *     gone), and the one-tap substitution and the catalog's default_client are gone with it
 *
 * Imports js/turn.js as shipped (spa_env) against a served catalog shaped like /api/state.turn_catalog.
 * Run: node tests/spa_hidden_forks_selftest.mjs
 *      --perturb        enabledTurnForks lets a hidden fork through again → RED in [1]
 *      --perturb-chart  the Overview reads the pickers' set again (a hidden fork's traffic gone) → RED in [2]
 *      --perturb-cli    pickerEntries ranks a `cli` client as an app again (a turn.js copy) → RED in [4]
 * [4] (S13a) csq-socks, a command-line csqtt client (`cli`), ranks after the desktop apps of its band: the csqtt fork's
 *     system default on Linux stays FOCSQ — as the sub page ranks it — and csq-socks is listed last, tagged CLI
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const PERTURB_CHART = process.argv.includes("--perturb-chart");
const PERTURB_CLI = process.argv.includes("--perturb-cli");
const { Store } = await spa("store.js");
let T;
if (PERTURB_CLI) {   // a turn.js copy OUTSIDE the served tree, its siblings by absolute URL (the shared Store instance)
  const src = fs.readFileSync(path.join(ROOT, "js", "turn.js"), "utf8"), a = "isCli: !!cl.cli, native, obf,";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); }
  const copy = src.replace(a, "isCli: false, native, obf,").replaceAll('from "./', 'from "' + pathToFileURL(path.join(ROOT, "js")).href + "/");
  if (/(?:from\s*|import\s*\(\s*)['"]\.{1,2}\/|import\.meta\.url/.test(copy)) { console.log("ANCHOR MISSING — a relative import is left: would FALSE-PASS"); process.exit(1); }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "spa-hidden-cli-")), file = path.join(dir, "turn.mjs");
  fs.writeFileSync(file, copy);
  process.on("exit", () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* gone */ } });
  T = await import(pathToFileURL(file).href);
} else T = await spa("turn.js");
let { enabledTurnForks, enabledTurnForkIds, turnForkPlatforms, TURN_FORKS_DEFAULT } = T;
if (PERTURB) { const { turnForkList } = await spa("turn-catalog.js");
  enabledTurnForks = keep => turnForkList().filter(f => enabledTurnForkIds().has(f.id) || f.id === keep); }

Store.turnCatalog = { servers: [
  { id: "WINGS-N", label: "WINGS-N", kind: "turn" },
  { id: "MYSOREZ", label: "MYSOREZ", kind: "turn", hidden: true },
  { id: "Moroka8", label: "Moroka8", kind: "turn", hidden: true },
  { id: "samosvalishe", label: "hack-diaz", kind: "turn" },
  { id: "amurcanov", label: "amurcanov", kind: "wdtt", product: "WDTT",
    compat: { wdttapp: "native", wdttplus: "friendly", qwdtt: "friendly", vkturnproxy: "friendly" } },
  { id: "qwdtt", label: "SpaceNeuroX", kind: "wdtt", product: "qWDTT" },
  { id: "xxcipherx", label: "XXcipherX", kind: "wdtt", product: "WDTT", hidden: true },
  { id: "cacggghp", label: "cacggghp", kind: "turn", hidden: true },
], clients: {   // as served: amurcanov's own app cannot open one-tap, WDTT-Plus can
  wdttapp: { name: "WDTT", author: "amurcanov", platforms: { android: { github: "g" } } },
  wdttplus: { name: "WDTT-Plus", author: "Ivan4537", platforms: { android: { github: "g", autostart: true } } },
  qwdtt: { name: "qWDTT", author: "SpaceNeuroX", platforms: { android: { github: "g" } } },
  vkturnproxy: { name: "VK TURN Proxy", platforms: { ios: { github: "g", autostart: true } } } } };

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
Store.panelSettings = { enabled_turn_forks: ["WINGS-N", "samosvalishe"] };   // a stored list that names no hidden fork (unticked long ago)
const en = enabledTurnForkIds();
check("[2] the chart's set holds every hidden fork whatever the stored list says (no switch could bring one back)",
      ["MYSOREZ", "Moroka8", "xxcipherx", "cacggghp"].every(f => en.has(f)) && en.has("WINGS-N") && !en.has("amurcanov"), [...en]);
const OV = fs.readFileSync(path.join(ROOT, "js", "screen-overview.js"), "utf8");
const ovRead = PERTURB_CHART ? OV.replace("const enSet = turnOn ? enabledTurnForkIds() : new Set();",
                                          "const enSet = new Set(turnOn ? enabledTurnForks().map(f => f.id) : []);") : OV;
check("[2] the Overview reads that set, not the pickers' (which drops hidden forks)",
      ovRead.includes("const enSet = turnOn ? enabledTurnForkIds() : new Set();") && !/enabledTurnForks\(/.test(ovRead), "");

console.log("\n[3] a WDTT fork's own app is its default");
Store.panelSettings = {};   // no operator choice
const amurAndroid = turnForkPlatforms(Store.turnCatalog.servers.find(f => f.id === "amurcanov")).find(p => p.os === "android");
check("[3] amurcanov on Android, no operator choice: its own WDTT, though WDTT-Plus opens one-tap",
      amurAndroid && amurAndroid.name === "WDTT" && amurAndroid.native === true, amurAndroid);
const TSRC = fs.readFileSync(path.join(ROOT, "js", "turn.js"), "utf8");
check("[3] no one-tap substitution, no default_client, no xxcipher left in the SPA's default rule",
      !/sysDefaultKey|default_client\b(?!.*went)|"xxcipher"/.test(TSRC.split("\n").filter(l => !/^\s*\/\//.test(l)).join("\n")), "");

console.log("\n[4] a command-line client ranks after the apps (csq-socks, S13a)");
Store.turnCatalog.servers.push({ id: "csqtt", label: "amurcanov", kind: "csqtt", product: "CSQTT",
  compat: { csqttapp: "native", focsq: "friendly", lalune: "friendly", csqsocks: "friendly", vkturnproxy: "friendly" } });
Object.assign(Store.turnCatalog.clients, {   // the served shapes (swg-panel-server TURN_CLIENTS), Linux only where it matters
  csqttapp: { name: "CSQTT", author: "amurcanov", platforms: { android: { github: "g", autostart: true } } },
  focsq: { name: "FOCSQ", author: "luminescq", platforms: { linux: { github: "g" }, windows: { github: "g" } } },
  lalune: { name: "La Lune", author: "Endlad2", platforms: { linux: { github: "g" }, windows: { github: "g" }, android: { github: "g", autostart: true } } },
  csqsocks: { name: "csq-socks", author: "SanityProtocol", cli: true, platforms: { linux: { github: "g" }, windows: { github: "g" } } } });
const csq = Store.turnCatalog.servers.find(f => f.id === "csqtt");
const lin = T.pickerEntries(csq, "linux");
check("[4] csqtt on Linux: csq-socks is listed last, tagged CLI", lin.length === 3 && lin[2].cid === "csqsocks" && lin[2].isCli === true,
      lin.map(e => [e.cid, e.isCli]));
const linDef = turnForkPlatforms(csq).find(p => p.os === "linux");
check("[4] …and the system default there stays FOCSQ, as the sub page ranks it", linDef && linDef.name === "FOCSQ", linDef);

done(PERTURB || PERTURB_CHART || PERTURB_CLI);
