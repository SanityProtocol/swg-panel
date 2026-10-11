/* Self-test: the Geo-data provider the panel itself maintains is named in the panel's language.
 *
 * The provider registry is DATA: swg-panel-server's catalog_providers_view puts the panel's own provider first as
 * {"id": "curated", "label": "Curated"}; every other provider's label is a proper name (MetaCubeX, Loyalsoldier, …).
 * The SPA printed `p.label` as it came, so the Russian panel's Settings → Routing & Blocking → Geo data providers row,
 * and the provider tag of every curated list (provLabelOf: the rule builder, the interface editor), read "Curated" —
 * though the catalogue has its Russian (1.8.9 qualification P3, the screens cell, ru-desktop; 1.8.8 too).
 *
 * provName (js/routing.js) names the panel's own provider in the operator's language and hands every other label back
 * as sent. This loads the real routing.js with the real Russian catalogue and checks: curated reads in Russian, a
 * provider's own name stays as published, provLabelOf of a curated set and of a provider's list, the server still names
 * its own provider `curated` (the id provName keys on), and Settings prints no registry label raw.
 *
 * Run: node tests/spa_geo_provider_name_selftest.mjs
 *      --perturb   provName hands every label back as sent → RED
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
globalThis.localStorage = { getItem: k => (k === "swg-lang" ? "ru" : null), setItem: () => {}, removeItem: () => {} };

// ── the real routing.js (a perturbed copy beside it, so its relative imports still resolve) ──────────────────────
let file = path.join(ROOT, "js", "routing.js");
if (PERTURB) {
  const src = fs.readFileSync(file, "utf8");
  const a = 'export function provName(p) { return p.id === "curated" ? T("Curated") : (p.label || p.id); }';
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); }
  // The copy lives OUTSIDE the served tree — a killed run must never leave a broken routing.js in js/ — and reaches its
  // siblings by their absolute URLs: the same modules (one Store) the test itself imports.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "spa-geo-prov-"));
  const base = pathToFileURL(path.join(ROOT, "js")).href + "/";
  file = path.join(dir, "routing.mjs");
  fs.writeFileSync(file, src.replace(a, "export function provName(p) { return p.label || p.id; }").replaceAll('from "./', 'from "' + base));
  process.on("exit", () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* gone */ } });
}
const I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
await I.loadLang();
const R = await import(pathToFileURL(file).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const ru = I.T("Curated");
check("the Russian catalogue is loaded and has the word", I.lang() === "ru" && ru !== "Curated" && /[Ѐ-ӿ]/.test(ru), ru);

check("the panel's own provider reads in Russian", R.provName({ id: "curated", label: "Curated" }) === ru,
      R.provName({ id: "curated", label: "Curated" }));
check("a provider's own name stays as published", R.provName({ id: "mc", label: "MetaCubeX" }) === "MetaCubeX");
check("a provider with no label reads as its id", R.provName({ id: "zz" }) === "zz");

Store.catalogProviders = [{ id: "curated", label: "Curated" }, { id: "mc", label: "MetaCubeX" }];
const cur = R.SMART_CATEGORIES().map(([id]) => id).find(R.isCuratedCat);
check("a curated set is found to tag", !!cur, cur);
check("a curated set's provider tag reads in Russian (provLabelOf)", R.provLabelOf(cur) === ru, R.provLabelOf(cur));
check("a provider's list keeps its provider's name (provLabelOf)", R.provLabelOf("mc:geosite-google") === "MetaCubeX",
      R.provLabelOf("mc:geosite-google"));

// ── the server still names its own provider `curated`, with the English label provName replaces ───────────────────
const srv = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
check("the registry's own provider is still {id: curated, label: Curated}",
      srv.split('{"id": "curated", "label": "Curated"').length === 2);

// ── Settings prints a registry label only through provName ─────────────────────────────────────────────────────────
const ss = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
const seg = (from, to) => { const i = ss.indexOf(from); const j = i < 0 ? -1 : ss.indexOf(to, i); return i < 0 || j < 0 ? null : ss.slice(i, j); };
const loop = seg("(_provReg.length ? _provReg : []).map(p =>", "Loading providers…");
const conf = seg("const setProvOn = (p, v) => {", "onConfirm:");
check("the Geo data providers rows are found", loop !== null && conf !== null);
check("…and print no registry label raw (`p.label`)", loop !== null && conf !== null && !/\bp\.label\b/.test(loop + conf),
      ((loop || "") + (conf || "")).match(/.{0,40}\bp\.label\b.{0,20}/g));
check("…they go through provName (swatch title, sample, name, repo link; the turn-off confirm twice)",
      ((loop || "") + (conf || "")).split("provName(p)").length - 1 === 6);
const rsrc = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
check("provLabelOf goes through provName", /export function provLabelOf\(c\) \{[^}]*provName\(/.test(rsrc));

done(PERTURB, "provName hands every label back as sent");
