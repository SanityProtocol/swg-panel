/* Self-test — a client config read back by parseFullConf rebuilds to the same config (docs/AWG3-PLAN.md §9 trap 9).
 *
 * Saving an Edit peer sheet (js/sheets-crud.js) or a deployment's settings rebuilds that device's config for the QR
 * from the stored one: parseFullConf → buildConf. The AWG values were captured with `(\S+)`, which stops at the first
 * space — and every I1–I5 an interface has carried since 2026-08-20 has spaces (`<b 0xc000000001><r 64><t>`). MEASURED
 * on swgt awg2's real params through the shipped code: all five came back cut (`I1 = <b`), and the rebuilt config was
 * refused by the 3.1 kernel, amneziawg-go 3.1 and our pinned build, where the same config before the round trip was
 * accepted by all three.
 *
 *   [1] buildConf → parseFullConf → buildConf is byte-identical, with the five default I-lines and ranged H1–H4.
 *   [2] the AWG values parse back exactly (no truncation, no trailing space); a key the config lacks, or one written
 *       with an empty value, stays absent — it never takes the next line as its value.
 *   [3] nothing else parseFullConf returns moved: keys, address, DNS, MTU, routes, endpoint, keepalive.
 *
 * Run: node tests/parse_full_conf_selftest.mjs    --perturb       serves crypto.js with the old `(\S+)` capture, RED.
 *                                                  --perturb-line  lets the match run past the end of the line, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { ROOT, spa, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb"), PERTURB_LINE = process.argv.includes("--perturb-line");
const FILE = path.join(ROOT, "js", "crypto.js");
const src = fs.readFileSync(FILE, "utf8");
const FIXED = String.raw`"[ \\t]*=[ \\t]*(.*\\S)"`;
const SERVED = PERTURB ? String.raw`"\\s*=\\s*(\\S+)"` : PERTURB_LINE ? String.raw`"\\s*=\\s*(.*\\S)"` : null;
if (SERVED) {
  // ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
  if (!src.includes(FIXED)) { console.log("ANCHOR MISSING: " + FIXED); process.exit(1); }
  const hook = "let S, U; export async function initialize(d) { S = d.src; U = d.url; }\n" +
    "export async function load(u, c, n) { return u === U ? { format: 'module', source: S, shortCircuit: true } : n(u, c); }";
  register("data:text/javascript," + encodeURIComponent(hook), import.meta.url,
           { data: { src: src.replace(FIXED, SERVED), url: pathToFileURL(FILE).href } });
}
const { buildConf, parseFullConf } = await spa("crypto.js");

// The five defaults every new AWG interface gets (swg-agent _awg_obfuscation), swgt awg2's H ranges and S values.
const awg = { Jc: "4", Jmin: "40", Jmax: "70", S1: "28", S2: "94", S3: "88", S4: "33",
  H1: "103509605-103509620", H2: "1694692368-1694692383", H3: "2553282719-2553282734", H4: "3170237912-3170237927",
  I1: "<b 0xc000000001><r 64><t>", I2: "<r 24><t>", I3: "<r 32>", I4: "<b 0xc000000001><r 32><t>", I5: "<t><r 48>" };
const o = { privkey: "cPrivKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", address: "10.9.0.7/32", dns: ["1.1.1.1", "8.8.8.8"],
  mtu: "1280", awg_params: awg, server_pubkey: "sPubKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  psk: "pskAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", endpoint: "201.24.126.212:443", allowed: "0.0.0.0/0, ::/0", keepalive: "25" };
const conf = buildConf(o);
const s = parseFullConf(conf);
const again = buildConf(s);

console.log("[1] the round trip Save runs is byte-identical");
check("buildConf(parseFullConf(conf)) === conf", again === conf,
      conf.split("\n").map((l, i) => l === again.split("\n")[i] ? null : l + "  →  " + again.split("\n")[i]).filter(Boolean));

console.log("\n[2] every AWG value parses back whole");
for (const k of Object.keys(awg)) check(k + " = " + awg[k], s.awg_params[k] === awg[k], s.awg_params[k]);
const noI = parseFullConf(buildConf({ ...o, awg_params: { Jc: "4", S1: "28" } }));
check("a key the config does not carry stays absent", !("I1" in noI.awg_params) && noI.awg_params.Jc === "4", noI.awg_params);
const empty = parseFullConf(buildConf({ ...o, awg_params: { I2: "", I3: "<r 32>" } }));   // buildConf writes `I2 = `
check("an empty value stays absent and leaves the next line alone", !("I2" in empty.awg_params) && empty.awg_params.I3 === "<r 32>",
      empty.awg_params);

console.log("\n[3] nothing else moved");
for (const k of ["privkey", "address", "psk", "endpoint", "allowed", "server_pubkey"]) check(k, s[k] === o[k], s[k]);
check("dns", JSON.stringify(s.dns) === JSON.stringify(o.dns), s.dns);
check("mtu, keepalive", String(s.mtu) === o.mtu && String(s.keepalive) === o.keepalive, [s.mtu, s.keepalive]);

done(PERTURB || PERTURB_LINE, PERTURB ? "the capture stops at the first space again" : "the match runs past the end of the line");
