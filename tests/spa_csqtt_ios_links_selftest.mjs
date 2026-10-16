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
 *   [6] …but only apps of the server's csqtt LINE (2.1 and 2.5 do not speak to each other): a 2.5 server offers the CSQTT
 *       app alone, a 2.1 one every app, and a node that reports no line (2.1) the whole list as before
 *   [7] a 2.5 server's link is SEALED, as the 2.5 app requires: byte for byte what the 2.5 server's own make_client_link
 *       gives for the same input (vectors proven against it, 2026-10-16, csqtt-2.5 work repo branch linkcheck), its escaping
 *       the server's url_encode; it is a QR (the 2.5 app scans one); a 2.1 server's link is the plain one, no QR; and the
 *       panel card's helper hands the line through
 *
 * Run: node tests/spa_csqtt_ios_links_selftest.mjs
 *      --perturb   routes the iOS client back to the csqtt:// link — expects RED in [1] [2] [4].
 *      --perturb-line  serves a catalog whose apps declare no csqtt line — expects RED in [6].
 *      --perturb-seal  seals with encodeURIComponent's escaping (leaves !'()* bare) — expects RED in [7].
 */
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import vm from "node:vm";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB_LINE = process.argv.includes("--perturb-line");
const PERTURB_SEAL = process.argv.includes("--perturb-seal");
const PERTURB = process.argv.includes("--perturb") || PERTURB_LINE || PERTURB_SEAL;

let src = readFileSync(path.join(ROOT, "turn-artifacts.js"), "utf8");
const ANCHOR = '    if (asClient === "anton48" || asClient === "vkturnproxy") {\n      // anton48\'s iOS VK TURN Proxy reads a csqtt:// link too';
// ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
if (src.split(ANCHOR).length - 1 !== 1) {
  console.log("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
  process.exit(1);
}
const SEAL_ANCHOR = "  function csqttUrlEnc(v) {\n";
if (src.split(SEAL_ANCHOR).length - 1 !== 1) { console.log("SEAL ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS"); process.exit(1); }
if (PERTURB_SEAL) src = src.replace(SEAL_ANCHOR, SEAL_ANCHOR + "    return encodeURIComponent(String(v == null ? \"\" : v));\n");
if (PERTURB && !PERTURB_LINE && !PERTURB_SEAL) src = src.replace(ANCHOR, '    if (false) {\n      //');
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
if (PERTURB_LINE) Object.values(Store.turnCatalog.clients).forEach(c => { delete c.csqtt_lines; });
const { csqttClientCfg, wdttClientIds, csqttClientIds } = await spa("peer-ui.js");

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

console.log("\n[6] only apps of the server's csqtt line");
const ids25 = csqttClientIds({ fork: "csqtt", line: "2.5" });
check("a 2.5 server: the CSQTT app alone", JSON.stringify(ids25) === JSON.stringify(["csqttapp"]), ids25);
const ids21 = csqttClientIds({ fork: "csqtt", line: "2.1" });
check("a 2.1 server: every app, the iOS one included", ["csqttapp", "focsq", "lalune", "vkturnproxy"].every(i => ids21.includes(i)), ids21);
check("a node that reports no line: the fork's whole list", JSON.stringify(csqttClientIds({ fork: "csqtt" })) === JSON.stringify(ids), csqttClientIds({ fork: "csqtt" }));

console.log("\n[7] a 2.5 server's link is sealed, as the 2.5 app requires");
// Proven against the 2.5 server's make_client_link + decrypt_csqtt_link (a deterministic iv: one payload, one link).
const V25 = [
  [{ host: "201.24.126.212", port: 56020, password: "Y8LrRU5ECsKmJpzX", hashes: ["bAzVQ_7VfpGDMiHn3RprNsDm_wAg8bwyPE7DbnchMsE", "MkrZeEH8RkaEPtG2iDBcqS8Piiojx_cOfD-jCbNBWI0"] },
   "csqtt://wgM4Gob8TpOM29vlQ2Js3XB284EkSx7H5p_mdjcM93rfCL6fj0hLJWxLHkRqJRIjSEm4oyYkABntXK5hKHBkz-S8-_DRrDnvcWARflhJ6s-DfPzuChBg1B4YsBWL7BLJa32RQwfL9d8yG_TinJn5A5eRwa66jxbichBSyXxAWC-c_blcKKaoJdDxQEA0CGqtKC80g2BRm1-e9_ohzu0qwdeFTVORZVfwLuJGJkYTotvMyz0kND5mnSMST7DCiEU"],
  [{ host: "vpn.example.org", port: 46000, password: "p@ss w!rd(1)*~", hashes: ["a+b/c=", "x"] },
   "csqtt://flvgIOKGjo_6ixoQp5eOgdytX7XjRt6K29gzsOd-rICB1Snu7_rympiuXcalM2z9a3FYdoaGwdY3Hb5pM2_KrbrOrNdNg8FM_WVvjE95u14sOYOzDNB-uKnMo6t1xbct4dDSPMUHs9_RCbs-M0r3E2vjOGw-MI7ecKUl804uoG_f"],
];
for (const [inp, want] of V25) {
  const a = SWGTurn.csqttArtifact(inp, "csqtt", "2.5");
  let got = null; try { got = await a.buildAsync(); } catch (e) { got = String(e); }
  check("2.5 link for " + inp.host + " is the server's, byte for byte", got === want, got);
  check("…and a QR, with no plain text", a.qr === true && a.text == null, a);
}
const a21 = SWGTurn.csqttArtifact(V25[0][0], "csqtt", "2.1"), a00 = SWGTurn.csqttArtifact(V25[0][0], "csqtt", "");
check("2.1 (and a node that reports no line): the plain csqtt://connect link, no QR",
  /^csqtt:\/\/connect\?v=2&/.test(a21.text) && a21.qr === false && a00.text === a21.text, [a21.text, a00.text]);
const dc25 = csqttClientCfg({ ...V25[0][0], line: "2.5" }, "csqttapp");
check("the panel card's helper hands the line through (a sealed artifact, a QR)", dc25.qr === true && !!(dc25.art && dc25.art.buildAsync) && dc25.uri == null, dc25);

done(PERTURB, PERTURB_LINE ? "apps declare no csqtt line" : PERTURB_SEAL ? "sealed with encodeURIComponent" : "iOS client routed back to csqtt://");
