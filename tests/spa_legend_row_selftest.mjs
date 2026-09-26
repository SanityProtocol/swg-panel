/* Self-test: a legend row is the badge and ONE flowing sentence — never a row of columns.
 *
 * `.lg-leg-row` is a flex row. `Trich` returns a sentence with *bold* runs as several nodes, and rendered straight into
 * the row each node became a flex item: on Settings ▸ Routing & Blocking ▸ Blocking the "Host" line split into columns,
 * "Force-DNS" and "Hybrid-SNI" wrapped on their own, and " or " lost its space at the item edge — "orHybrid-SNI"
 * (1.8.8 qualification, GUI review). `legRow` keeps the badge as the one hanging item and puts the words in one span.
 *
 * Imports js/screen-settings.js as shipped (spa_env) and walks the vnodes; also checks every legend row goes through it.
 * Run: node tests/spa_legend_row_selftest.mjs
 *      --perturb   the row rendered the old way (Trich straight into the flex row) and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const { h } = await spa("../vendor/preact.module.js").catch(async () => ({ h: (await import("preact")).h }));
let { legRow } = await spa("screen-settings.js");
const { Trich } = await spa("i18n.js");
const html = (await spa("../vendor/htm.module.js").catch(() => null)) || null;
if (PERTURB) legRow = parts => ({ type: "div", props: { class: "lg-leg-row", children: parts } });

const badge = { type: "span", props: { class: "capb host", children: "Host" } };
const row = legRow(Trich("{v1} matched by domain name — needs *{v2}* or *Hybrid-SNI* mode (they fill the block set from DNS).", { v1: badge, v2: "Force-DNS" }));
const kids = [].concat(row.props.children).flat(Infinity).filter(x => x != null && x !== false && x !== "");
const text = n => n == null ? "" : typeof n === "string" ? n : Array.isArray(n) ? n.map(text).join("") : text(n.props && n.props.children);
console.log("[the Host row of the Blocking legend]");
check("exactly two flex items: the badge and the sentence", kids.length === 2, kids.length);
check("the badge first", kids[0] === badge);
check("the whole sentence, spaces intact, in the second", /needs Force-DNS or Hybrid-SNI mode/.test(text(kids[1])), text(kids[1]));
const plain = legRow(Trich("{v1} matched by IP address — works in every mode.", { v1: badge }));
check("a row without bold runs has the same shape", [].concat(plain.props.children).flat(Infinity).filter(x => x != null && x !== "").length === 2);

console.log("\n[every legend row goes through it]");
const src = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
check("no `lg-leg-row` div is built around a raw Trich any more", !/<div class="lg-leg-row">\$\{Trich\(/.test(src));
check("five rows use legRow(Trich(…))", (src.match(/\$\{legRow\(Trich\(/g) || []).length === 5);
done(PERTURB);
