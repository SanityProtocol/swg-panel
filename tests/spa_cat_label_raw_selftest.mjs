/* Self-test: a destination category the node names by its SANITISED id still reads with its provider label
 * (docs/SCALE-PLAN.md K8 D3).
 *
 * swg-noded keys a category's live rate as nft names its counter — `mc:cloudflare` → `mc_cloudflare` — and the panel's
 * rings (the ranged view) are named the same way. catLabelOf humanises only the raw provider form (prettyCatLabel: curated
 * names, ISO country names), so a sanitised id read bare ("Mc_cloudflare"). Since K8 Kernel SNI keys its rows that way too
 * (one row a category instead of two), so the label maps the id back through the in-use catalog cats /api/state carries
 * (Store.smartCaps' keys) first.
 *
 *  [1] a sanitised provider id labels exactly as its raw id does (a country code, a curated name, a plain id with a dash)
 *  [2] built-in, custom and unknown ids label as before; a provider id not in use stays bare
 *  [3] a new smartCaps object is read afresh (the map is per object, not per page life)
 *
 * Run: node tests/spa_cat_label_raw_selftest.mjs
 *      --perturb   catLabelOf no longer maps a sanitised id back → RED
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

let file = path.join(ROOT, "js", "routing.js");
if (PERTURB) {
  const src = fs.readFileSync(file, "utf8");
  const a = "  c = rawCatOf(c);\n";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "spa-cat-raw-"));
  const base = pathToFileURL(path.join(ROOT, "js")).href + "/";
  file = path.join(dir, "routing.mjs");
  const copy = src.replace(a, "").replaceAll('from "./', 'from "' + base);
  if (/(?:from\s*|import\s*\(\s*)['"]\.{1,2}\/|import\.meta\.url/.test(copy)) {
    console.log("ANCHOR MISSING — the perturbed copy keeps a relative import: this run would FALSE-PASS"); process.exit(1);
  }
  fs.writeFileSync(file, copy);
  process.on("exit", () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* gone */ } });
}
const I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
await I.loadLang();
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const { catLabelOf } = await import(pathToFileURL(file).href);

const RAW = ["mc:cloudflare", "mc:ru", "v2:category-ads-all"];
Store.smartCaps = { google: { ip: 1, host: 1 }, ...Object.fromEntries(RAW.map(k => [k, { ip: 1, host: 1 }])) };
Store.catLabels = {};
const san = k => k.toLowerCase().replace(/[^a-z0-9]/g, "_");

console.log("[1] a sanitised provider id");
for (const k of RAW)
  check(`[1] ${san(k)} labels as ${k} ("${catLabelOf(k)}")`, catLabelOf(san(k)) === catLabelOf(k) && catLabelOf(k) !== san(k),
        [catLabelOf(san(k)), catLabelOf(k)]);

console.log("\n[2] everything else as before");
const before = { google: catLabelOf("google"), uncat: catLabelOf("uncat"), custom: catLabelOf("custom_9ec97659fa") };
check("[2] a built-in, the catch-all and a custom id label as they do without a map",
      before.google !== "google" && before.uncat && before.custom, before);
check("[2] an unknown id and a provider id not in use stay bare", catLabelOf("zz_nothing") === "Zz_nothing" && catLabelOf("mc_spacex") === "Mc_spacex",
      [catLabelOf("zz_nothing"), catLabelOf("mc_spacex")]);

console.log("\n[3] a new smartCaps");
Store.smartCaps = { ...Store.smartCaps, "mc:spacex": { ip: 1 } };
check("[3] a provider id that came into use labels at once", catLabelOf("mc_spacex") === catLabelOf("mc:spacex"),
      [catLabelOf("mc_spacex"), catLabelOf("mc:spacex")]);

done(PERTURB);
