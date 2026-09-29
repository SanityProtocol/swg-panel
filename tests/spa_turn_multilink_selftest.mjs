/* Self-test: a turn-proxy config carries EVERY VK call link wherever the client's core takes a list.
 *
 * Each call link is its own pool of TURN streams, so a user holding three links and handed one gets a third of
 * the throughput. The freeturn:// link used to carry only the primary in `vk`, although the free-turn core copies
 * `vk` into -links and splits it on commas (internal/config/raw.go applyURI + normalizeVKLinks), and the FreeTurn
 * Android app passes it through as relay.links=[callLink], which the core joins and splits the same way.
 *
 * What this drives, through the REAL encoder:
 *   [1] freeturn:// — `vk` is every link comma-joined, and the core's own split gives them all back
 *   [2] VKTGZ (MYSOREZ app) — vkLink carries the list for the MYSOREZ (-vk) and free-turn (-links) cores
 *   [3] CONTROL: VKTGZ for the cacggghp / Moroka8 cores (-vk-link takes ONE link) stays the primary only
 *   [4] CLI commands — free-turn -links and MYSOREZ -vk carry the list; Moroka8 -vk-link carries one
 *   [5] CONTROL: one link / no link behave as before; the removed kiper292 fork/client degrade to the CLI config
 *
 * Run: node tests/spa_turn_multilink_selftest.mjs
 *      --perturb   puts freeturn back to the primary only — expects RED in [1].
 */
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import path from "node:path";
import vm from "node:vm";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");

let src = readFileSync(path.join(ROOT, "turn-artifacts.js"), "utf8");
const ANCHOR = '    if (vks.length) o.vk = vks.join(",");\n';
// ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
if (src.split(ANCHOR).length - 1 !== 1) {
  console.log("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
  process.exit(1);
}
if (PERTURB) src = src.replace(ANCHOR, '    if (vks.length) o.vk = vks[0];\n');
vm.runInThisContext(src, { filename: "turn-artifacts.js" });
const SWGTurn = globalThis.SWGTurn;

const J = "https://vk.ru/call/join/";
const LINKS = [J + "AAAAAAAAAAAAAAAAAAAA", J + "BBBBBBBBBBBBBBBBBBBB", J + "CCCCCCCCCCCCCCCCCCCC"];
const CONF = "[Interface]\nPrivateKey = cHJpdmtleXByaXZrZXlwcml2a2V5cHJpdmtleXByaXY=\nAddress = 10.8.0.5/32\nDNS = 1.1.1.1\n\n" +
  "[Peer]\nPublicKey = cHVia2V5cHVia2V5cHVia2V5cHVia2V5cHVia2V5cHU=\nAllowedIPs = 0.0.0.0/0\nEndpoint = 1.2.3.4:51820\n";
const tp = (fork, key) => ({ service: "vk-turn-proxy-" + fork + "-56000", listen: "1.2.3.4:56000", wrap_key: key || "",
  params: fork === "samosvalishe" && key ? "-obf-profile rtpopus -obf-key " + key : "" });
const KEY = "ab".repeat(32);
// The free-turn core's normalizeVKLinks, ported: split on commas, keep the join code of each.
const coreLinks = s => String(s || "").split(",").map(x => x.trim()).filter(Boolean)
  .map(x => x.split("join/").pop().split(/[/?#]/)[0]).filter(Boolean);
const vktgz = async a => JSON.parse(gunzipSync(Buffer.from((await a.buildAsync()).slice(6), "base64")).toString("utf8"));

console.log("[1] freeturn:// carries every link");
{
  const a = SWGTurn.artifact(CONF, tp("samosvalishe", KEY), LINKS[0], {}, LINKS, "freeturn");
  const o = JSON.parse(Buffer.from(a.text.replace("freeturn://", ""), "base64url").toString("utf8"));
  check("`vk` is all three, comma-joined in order", o.vk === LINKS.join(","), o.vk);
  check("the core's own split gives three stream pools", coreLinks(o.vk).length === 3, coreLinks(o.vk));
  check("the rest of the link is intact (peer, obf, key, wg)", o.peer === "1.2.3.4:56000" && o.obf && o.key === KEY && /\[Interface\]/.test(o.wg), o);
}

console.log("[2] VKTGZ carries the list for the cores that take one");
for (const fork of ["MYSOREZ", "samosvalishe"]) {
  const p = await vktgz(SWGTurn.artifact(CONF, tp(fork, KEY), LINKS[0], {}, LINKS, "vktgz"));
  check(fork + ": vkLink is all three, comma-joined, one token", p.config.vkLink === LINKS.join(",") && !/\s/.test(p.config.vkLink), p.config.vkLink);
}

console.log("[3] CONTROL: VKTGZ for single-link cores keeps the primary");
for (const fork of ["cacggghp", "Moroka8"]) {
  const p = await vktgz(SWGTurn.artifact(CONF, tp(fork, fork === "Moroka8" ? KEY : ""), LINKS[0], {}, LINKS, "vktgz"));
  check(fork + ": vkLink is the primary only", p.config.vkLink === LINKS[0], p.config.vkLink);
}

{
  const p = await vktgz(SWGTurn.artifact(CONF, tp("samosvalishe", KEY), LINKS[0], { linkArgument: "-link" }, LINKS, "vktgz"));
  check("free-turn core with the link flag overridden to -link (single) → primary only", p.config.vkLink === LINKS[0], p.config.vkLink);
}

{
  const p = await vktgz(SWGTurn.artifact(CONF, tp("samosvalishe", KEY), LINKS[0], { linkArgument: "--links" }, LINKS, "vktgz"));
  check("the same flag spelled --links still carries the list", p.config.vkLink === LINKS.join(","), p.config.vkLink);
}

console.log("[4] CLI commands");
{
  const a = SWGTurn.artifact(CONF, tp("samosvalishe", KEY), LINKS[0], {}, LINKS, "sidecar");
  const by = f => (a.cliAuthors.find(x => x.fork === f) || {}).cmd || "";
  check("free-turn: -links <all three>", by("samosvalishe").includes(" -links " + LINKS.join(",") + " "), by("samosvalishe"));
  check("Moroka8: -vk-link <primary>", by("Moroka8").includes(" -vk-link " + LINKS[0] + " ") && !by("Moroka8").includes(LINKS[1]), by("Moroka8"));
  const m = SWGTurn.artifact(CONF, tp("MYSOREZ", KEY), LINKS[0], {}, LINKS, "sidecar");
  check("MYSOREZ: -vk <all three>", m.cmd.includes(" -vk " + LINKS.join(",") + " "), m.cmd);
  const none = SWGTurn.artifact(CONF, tp("samosvalishe", KEY), "", {}, [], "sidecar");
  check("no link → the visible placeholder, as before", none.cmd.includes(" -links <PASTE VK CALL LINK>"), none.cmd);
}

console.log("[5] CONTROL: single-link clients and edge cases");
{
  // kiper292 and its WireGuard-TURN client are removed: a proxy still running on a node, or a saved client choice
  // naming the old encoder, falls through to the CLI sidecar config instead of breaking.
  const k = SWGTurn.artifact(CONF, tp("kiper292"), LINKS[0], {}, LINKS);
  check("removed kiper292: a leftover proxy gets the CLI config", k.enc === "sidecar" && /Endpoint = 127\.0\.0\.1:9000/.test(k.text), k.enc);
  const k2 = SWGTurn.artifact(CONF, tp("WINGS-N"), LINKS[0], {}, LINKS, "kiper292");
  check("removed kiper292: a stale saved client choice gets the CLI config", k2.enc === "kiper292" && !/#@wgt/.test(k2.text) && !!k2.cmd, k2.text);
  const one = SWGTurn.artifact(CONF, tp("samosvalishe", KEY), LINKS[0], {}, [LINKS[0]], "freeturn");
  const o1 = JSON.parse(Buffer.from(one.text.replace("freeturn://", ""), "base64url").toString("utf8"));
  check("freeturn with one link: `vk` is that link, no comma", o1.vk === LINKS[0], o1.vk);
  const zero = SWGTurn.artifact(CONF, tp("samosvalishe", KEY), "", {}, [], "freeturn");
  const o0 = JSON.parse(Buffer.from(zero.text.replace("freeturn://", ""), "base64url").toString("utf8"));
  check("freeturn with no link: `vk` omitted, vkMissing set", !("vk" in o0) && zero.vkMissing === true, o0);
}

done(PERTURB, "freeturn back to the primary link only");
