/* Self-test: an iPhone on a csqtt server is handed EVERY VK call link, not the first one.
 *
 * anton48's iOS VK TURN Proxy reads a csqtt:// link (BackupManager.parseCsqttLink), but it keeps only the
 * first hash of `hashes=a+b+c` — `split("+").first` — and the import then OVERWRITES the app's global call-link
 * list with that one link. So a user with three calls on the panel lost two of them on every import, silently:
 * the import succeeds, the list just shrinks. The app's own vkturnproxy:// link stores `vkLink` verbatim, and
 * the app keeps that as a multiline string, one call per line (TunnelManager splits on newlines). So the iOS
 * client is given that link instead, in csqtt mode — and the csqtt:// link every csqtt APP takes stays as it was.
 *
 * What this drives, through the REAL encoder and the REAL panel helper, against the REAL client catalog:
 *   [1] the vkturnproxy:// link carries every call, one per line, in csqtt mode — byte for byte what the app's
 *       own generator (quick_link.py build_link) emits for the same settings
 *   [2] no cap: the 6 is the CSQTT app's limit, not this app's
 *   [3] CONTROL: the csqtt:// link is unchanged — with no client, and with the csqtt encoder
 *   [4] the panel card's helper picks the link by the CLIENT's encoder, from the catalog the panel serves
 *   [5] the csqtt server's client list still offers the iOS app (so the card's Alternatives sheet can show it)
 *
 * Run: node tests/spa_csqtt_ios_links_selftest.mjs
 *      --perturb   routes the iOS client back to the csqtt:// link — expects RED in [1] [2] [4].
 */
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import vm from "node:vm";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");

let src = readFileSync(path.join(ROOT, "turn-artifacts.js"), "utf8");
const ANCHOR = '    if (asClient === "anton48" || asClient === "vkturnproxy") {\n      // anton48\'s iOS VK TURN Proxy reads a csqtt:// link too';
// ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
if (src.split(ANCHOR).length - 1 !== 1) {
  console.log("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
  process.exit(1);
}
if (PERTURB) src = src.replace(ANCHOR, '    if (false) {\n      //');
// turn-artifacts.js is a classic script: evaluate it into the SAME global the SPA modules read SWGTurn from.
vm.runInThisContext(src, { filename: "turn-artifacts.js" });
const SWGTurn = globalThis.SWGTurn;

// The catalog exactly as the panel serves it in /api/state.
const py = spawnSync("python3", ["-c", `
import types, json, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = types.ModuleType("p"); m.__dict__.update({"__name__": "p", "__file__": sys.argv[1]})
exec(compile(src.split("\\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)
print(json.dumps(m.turn_catalog_view()))`, path.join(ROOT, "swg-panel-server")], { encoding: "utf8" });
if (py.status !== 0) { console.log("could not load the catalog from swg-panel-server:\n" + py.stderr); process.exit(1); }
const { Store } = await spa("store.js");
Store.turnCatalog = JSON.parse(py.stdout);
const { csqttClientCfg, wdttClientIds } = await spa("peer-ui.js");

const J = "https://vk.ru/call/join/";
const INP = { host: "1.2.3.4", port: 46000, password: "p@ss", vk_hash: "AAA",
  vk_links: ["https://vk.com/call/join/BBB", J + "AAA", J + "CCC?x=1", J + "D", J + "E", J + "F", J + "G"] };
const decode = uri => JSON.parse(Buffer.from(uri.split("data=")[1], "base64url").toString("utf8"));

console.log("[1] the iOS link carries every call, one per line, in csqtt mode");
const ios = SWGTurn.csqttArtifact(INP, "anton48");
check("it is a vkturnproxy:// link", /^vkturnproxy:\/\/import\?data=/.test(ios.text), ios.text);
const sIos = ios.text.startsWith("vkturnproxy://") ? decode(ios.text).settings : {};
check("csqtt mode + password + server", sIos.useCsqtt === true && sIos.csqttPassword === "p@ss" && sIos.peerAddress === "1.2.3.4:46000", sIos);
const lines = String(sIos.vkLink || "").split("\n");
check("every call, deduped, the peer's own hash first", lines.join(" ") === ["AAA", "BBB", "CCC", "D", "E", "F", "G"].map(h => J + h).join(" "), lines);
// quick_link.py build_link({csqttPassword, peerAddress, useCsqtt, vkLink}) for these values, captured from the script itself.
const QL = "vkturnproxy://import?data=eyJzZXR0aW5ncyI6eyJjc3F0dFBhc3N3b3JkIjoicEBzcyIsInBlZXJBZGRyZXNzIjoiMS4yLjMuNDo0NjAwMCIsInVzZUNzcXR0Ijp0cnVlLCJ2a0xpbmsiOiJodHRwczovL3ZrLnJ1L2NhbGwvam9pbi9BQUFcbmh0dHBzOi8vdmsucnUvY2FsbC9qb2luL0JCQlxuaHR0cHM6Ly92ay5ydS9jYWxsL2pvaW4vQ0NDIn0sInR5cGUiOiJjb25uZWN0aW9uIiwidmVyc2lvbiI6MX0";
check("byte-identical to quick_link.py", SWGTurn.csqttArtifact({ ...INP, vk_links: INP.vk_links.slice(0, 3) }, "vkturnproxy").text === QL);
check("no call → an empty vkLink the app will not write, and the UI is told", (() => {
  const a = SWGTurn.csqttArtifact({ host: "h", port: 1, password: "x" }, "anton48");
  return a.vkMissing === true && a.text.startsWith("vkturnproxy://") && decode(a.text).settings.vkLink === "";
})());

console.log("\n[2] no cap on the iOS link");
check("7 calls in, 7 carried", lines.length === 7, lines.length);

console.log("\n[3] CONTROL: the csqtt:// link is unchanged");
const plain = SWGTurn.csqttArtifact(INP).text;
check("no client → csqtt://, first 6 hashes", plain === "csqtt://connect?v=2&host=1.2.3.4&peer=46000&password=p%40ss&hashes=AAA+BBB+CCC+D+E+F", plain);
check("csqtt encoder → the same link", SWGTurn.csqttArtifact(INP, "csqtt").text === plain);

console.log("\n[4] the panel card picks the link by the client's encoder");
check("VK TURN Proxy (iOS) → vkturnproxy://", String(csqttClientCfg(INP, "vkturnproxy").uri).startsWith("vkturnproxy://"), csqttClientCfg(INP, "vkturnproxy").uri);
for (const cid of ["csqttapp", "focsq", "lalune"]) check(cid + " → csqtt://", csqttClientCfg(INP, cid).uri === plain, csqttClientCfg(INP, cid).uri);

console.log("\n[5] the csqtt server offers the iOS app, its own app first");
const ids = wdttClientIds("csqtt");
check("CSQTT is the default", ids[0] === "csqttapp", ids);
check("VK TURN Proxy is an alternative", ids.includes("vkturnproxy"), ids);

done(PERTURB, "iOS client routed back to csqtt://");
