/* Self-test: the Upstream DNS hint says WHICH of the two cases a node is in.
 *
 * Settings ▸ Routing & Blocking, Force-DNS: when the saved upstream is not what the node's resolver runs, the hint said
 * "It applies on the next sync; a node too old to know this setting keeps the default until it updates" — one sentence
 * for both cases, so on a node the SPA KNEW was too old (its resolver runs, it reports no `dns_upstream`) it still promised
 * the next sync (1.8.8 qualification, F1). The hint now branches on what the node reports.
 *
 * Reads js/screen-settings.js as shipped (the hint is inline in the section's render) and checks the branch.
 * Run: node tests/spa_upstream_dns_hint_selftest.mjs
 *      --perturb   the one-sentence hint back and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let src = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
const ru = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
if (PERTURB) {
  const a = "                  : Array.isArray(sr.dns_upstream)\n";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING: the hint's branch"); process.exit(1); }
  src = src.replace(a, "                  : true\n");
}
const NEW = "Not on the node yet — it still asks {v1}. It applies on the next sync.";
const OLD = "This node is too old to use this setting — it keeps asking {v1} until it is updated.";
console.log("[the two cases, told apart]");
check("a node that reports its upstream and has not applied the saved one yet: \"the next sync\"", src.includes('T("' + NEW + '"'));
check("a node too old to know the setting: it keeps the default until it is updated", src.includes('T("' + OLD + '"'));
check("…chosen by whether the node reports `dns_upstream` at all", /: Array\.isArray\(sr\.dns_upstream\)\s*\n\s*\? html`<div class="hint warnish">\$\{T\("Not on the node yet/.test(src));
check("the one-sentence promise is gone", !src.includes("a node too old to know this setting keeps the default until it updates"));
console.log("\n[Russian]");
check("both sentences are translated", ru.includes('"' + NEW + '"') && ru.includes('"' + OLD + '"'));
done(PERTURB);
