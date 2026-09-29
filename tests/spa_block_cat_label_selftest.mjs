/* Self-test: the panel's built-in block categories and the provider lists behind them read in the panel's language —
 * and a renamed category reads as typed.
 *
 * The categories are DATA: swg-panel-server's BLOCK_CATEGORIES / MECH_CATEGORIES, each with an English label, reach the
 * browser through /api/block-catalog and the Overview's stats. Every screen printed `c.label` as it came, so the Russian
 * panel's Blocking tab, each interface's blocking chips and the Overview's Blocked bubble read "Ads & Trackers",
 * "Torrents / P2P", "Port-scan / Brute-force" (1.8.8 qualification, a sweep of every Settings section in Russian).
 * No i18n audit could see it: there is no literal to find, only `${c.label}`.
 *
 * blockCatLabel (js/routing.js) translates a label only while it is still the built-in English text — an operator may
 * rename a category (the API takes a label for any), and the Overview's entries carry the label alone. This reads the
 * server's labels with Python's own parser, loads the real routing.js with the real Russian catalogue, and checks:
 * every built-in label that is a word reads in Russian, protocol names stay as they are, a renamed label is untouched,
 * the helper lists no label the server no longer has, and the screens that print a category go through it.
 *
 * The same for the lists (BLOCK_PROVIDER_LISTS, blistText): every description is the panel's own prose and reads in
 * Russian; a name that describes content does too; a provider's own edition or brand name stays as published (KEEP
 * below, each with its reason) — "Light" must never become the theme's «Светлая».
 *
 * Run: node tests/spa_block_cat_label_selftest.mjs
 *      --perturb        blockCatLabel hands every label back untouched → RED
 *      --perturb-drift  a built-in label changed on the server ("Adult" → "Adult content") → RED
 *      --perturb-case   the Overview's category name title-cased in every language again → RED
 *      --perturb-list   blistText hands every list name and description back untouched → RED
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const DRIFT = process.argv.includes("--perturb-drift");
const CASE = process.argv.includes("--perturb-case");
const LIST = process.argv.includes("--perturb-list");
globalThis.localStorage = { getItem: k => (k === "swg-lang" ? "ru" : null), setItem: () => {}, removeItem: () => {} };

// ── the server's built-in labels, from the dict literals themselves ──────────────────────────────────────────────
const py = `import ast, json, sys
out = {}
for n in ast.parse(open(sys.argv[1], encoding="utf-8").read()).body:
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", "") in ("BLOCK_CATEGORIES", "MECH_CATEGORIES"):
        out[n.targets[0].id] = {k: v[0] for k, v in ast.literal_eval(n.value).items()}
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", "") == "BLOCK_PROVIDER_LISTS":
        out["LISTS"] = [list(v[:2]) for l in ast.literal_eval(n.value).values() for v in l.values()]
print(json.dumps(out))`;
const r = spawnSync("python3", ["-c", py, path.join(ROOT, "swg-panel-server")], { encoding: "utf8" });
const srv = r.status === 0 ? JSON.parse(r.stdout) : {};
const labels = [...Object.values(srv.BLOCK_CATEGORIES || {}), ...Object.values(srv.MECH_CATEGORIES || {})];
if (DRIFT) { const i = labels.indexOf("Adult"); if (i < 0) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); } labels[i] = "Adult content"; }
check("the server's built-in categories are read (8 list-backed + 7 mechanisms)",
      Object.keys(srv.BLOCK_CATEGORIES || {}).length === 8 && Object.keys(srv.MECH_CATEGORIES || {}).length === 7, r.stderr || srv);

// ── the real routing.js (a perturbed copy beside it, so its relative imports still resolve) ──────────────────────
let file = path.join(ROOT, "js", "routing.js");
if (PERTURB || LIST) {
  const src = fs.readFileSync(file, "utf8");
  const a = PERTURB ? "export const blockCatLabel = label => (" : "export const blistText = s => (";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); }
  file = path.join(ROOT, "js", ".routing-perturbed.mjs");
  fs.writeFileSync(file, src.replace(a, PERTURB ? "export const blockCatLabel = label => label || (" : "export const blistText = s => s || ("));
  process.on("exit", () => { try { fs.unlinkSync(file); } catch (_) { /* gone */ } });
}
const I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
await I.loadLang();
const { blockCatLabel, blistText } = await import(pathToFileURL(file).href);
check("the Russian catalogue is loaded", I.lang() === "ru" && I.T("bcat|Adult") !== "Adult", I.T("bcat|Adult"));

console.log("\n[every built-in label]");
const PROTOCOL = new Set(["QUIC / HTTP-3", "DoH / DoT / DoQ", "WebRTC / STUN"]);   // the same in every language
for (const l of labels) {
  const out = blockCatLabel(l);
  if (PROTOCOL.has(l)) check(`"${l}" stays as it is (protocol names)`, out === l, out);
  else check(`"${l}" reads in Russian`, out !== l && /[Ѐ-ӿ]/.test(out), out);
}

console.log("\n[a label that is not the built-in text]");
check("a renamed category prints as typed", blockCatLabel("My ads list") === "My ads list");
check("…and so does one that differs only in case", blockCatLabel("adult") === "adult");
check("an empty label stays empty", blockCatLabel("") === "");

console.log("\n[the helper and the screens]");
const rsrc = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
const block = (rsrc.split("export const blockCatLabel = label => (")[1] || "").split("}))[label] || label;")[0] || "";
const entries = [...block.matchAll(/^\s*"([^"]+)":\s*T\("bcat\|([^"]+)"\),/gm)].map(m => [m[1], m[2]]);
check("the helper's map is read (12 entries)", entries.length === 12, entries.length);
check("each entry looks itself up — key and catalogue key are the same text", entries.every(([k, t]) => k === t),
      entries.filter(([k, t]) => k !== t));
check("the helper lists no label the server no longer has", entries.every(([k]) => labels.includes(k)),
      entries.filter(([k]) => !labels.includes(k)).map(([k]) => k));
const screens = ["routing.js", "screen-settings.js", "screen-overview.js"].map(f => [f, fs.readFileSync(path.join(ROOT, "js", f), "utf8")]);
const raw = screens.filter(([, s]) => /\$\{c\.label\}/.test(s)).map(([f]) => f);
check("no screen that shows a block category prints `${c.label}` raw", !raw.length, raw);
const uses = screens.reduce((n, [, s]) => n + (s.match(/\bblockCatLabel\(c\.label\)/g) || []).length, 0);
check("the four places go through blockCatLabel (two chips, the Blocking row, the Overview bubble)", uses === 4, uses);

console.log("\n[the provider lists behind them]");
// A provider's own edition or brand name — an operator matches it against the provider's page, which the row links to.
const KEEP = new Set(["Pro", "Light", "Lite", "Xtra", "Big", "Small", "Unified", "NSFW", "Level 1", "Level 2", "Level 3",
                      "Threat Intelligence Feed", "DShield", "Spamhaus DROP", "TikTok", "Facebook", "YouTube"]);
const lists = srv.LISTS || [];
const lnames = [...new Set(lists.map(l => l[0]))], ldescs = [...new Set(lists.map(l => l[1]))];
check("the server's provider lists are read (51 lists)", lists.length === 51, lists.length);
const ru = t => /[\u0400-\u04FF]/.test(t);
const untranslatedD = ldescs.filter(d => !ru(blistText(d)));
check(`every list description reads in Russian (${ldescs.length})`, !untranslatedD.length, untranslatedD);
const badN = lnames.filter(n => KEEP.has(n) ? blistText(n) !== n : !ru(blistText(n)));
check(`every list name that describes content reads in Russian, an edition or brand name as published (${lnames.length})`, !badN.length,
      badN.map(n => n + " → " + blistText(n)));
check("a list called \"Light\" is not the theme's «Светлая»", blistText("Light") === "Light", blistText("Light"));
check("every kept name is still one the server has", [...KEEP].every(n => lnames.includes(n)), [...KEEP].filter(n => !lnames.includes(n)));
const lblock = (rsrc.split("export const blistText = s => (")[1] || "").split("}))[s] || s;")[0] || "";
const lentries = [...lblock.matchAll(/"((?:[^"\\]|\\.)+)":\s*T\("blist\|((?:[^"\\]|\\.)+)"\),/g)].map(m => [m[1], m[2]]);
check("the list map is read (69 entries)", lentries.length === 69, lentries.length);
check("each list entry looks itself up", lentries.every(([k, t]) => k === t), lentries.filter(([k, t]) => k !== t));
check("the list map holds nothing the server dropped", lentries.every(([k]) => lnames.includes(k) || ldescs.includes(k)),
      lentries.filter(([k]) => !lnames.includes(k) && !ldescs.includes(k)).map(([k]) => k));
const ssrc = screens.find(([f]) => f === "screen-settings.js")[1];
check("the picker shows names and descriptions through blistText", /bk-pilabel">\$\{blistText\(it\.label\)\}/.test(rsrc) && /bk-pidesc">\$\{blistText\(it\.desc\)\}/.test(rsrc));
check("…and so do the Blocking tab's rows", /blistText\(L\.label\)/.test(ssrc) && /blistText\(L\.desc\)/.test(ssrc));
check("the picker's rows and its \"No lists match\" use one search", (rsrc.match(/\bshown\(p, it\)/g) || []).length === 2);

// The Overview's category name was title-cased by CSS for every language — «Реклама И Трекеры». Title Case is English.
let css = fs.readFileSync(path.join(ROOT, "app.css"), "utf8");
if (CASE) {
  // ⚠️ ASSERT THE ANCHOR: a replace that finds nothing plants nothing, and the run would read green (round 10)
  if (!css.includes("html[lang=en] .prot-cat-nm{text-transform:capitalize}")) {
    console.log("perturbation anchor missing in app.css — this run would FALSE-PASS"); process.exit(3);
  }
  css = css.replace("html[lang=en] .prot-cat-nm{text-transform:capitalize}", ".prot-cat-nm{text-transform:capitalize}");
}
css = css.replace(/\/\*[\s\S]*?\*\//g, "");                   // a comment is not part of a selector
const rules = [...css.matchAll(/([^{}]*\.prot-cat-nm[^{}]*)\{([^}]*)\}/g)].map(m => [m[1].trim(), m[2]]);
const cap = rules.filter(([, body]) => /text-transform\s*:\s*capitalize/.test(body)).map(([sel]) => sel);
check("the Overview's category name is title-cased in English only", cap.length === 1 && /^html\[lang=en\]\s/.test(cap[0]), cap);

done(PERTURB || DRIFT || CASE || LIST, PERTURB ? "the helper hands labels back untouched" : DRIFT ? "a server label drifted"
     : CASE ? "title case for every language" : "list names and descriptions handed back untouched");
