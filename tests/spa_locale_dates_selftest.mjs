/* Self-test: dates in the operator app are written in the PANEL's language, never the browser's.
 *
 * `toLocaleString(undefined, …)` formats in the BROWSER's locale. A Russian panel on an English browser read "Sep 17, 09:20 AM"
 * inside a Russian sentence — the device-access line "Остановлено пакетов к устройствам здесь с Sep 17, 09:20 AM"
 * (1.8.7 qualification PART 3, P3-3). The same `undefined` sat in peer-actions' fmtDate, which dates expiries, sessions and
 * API tokens across the app. i18n.js's `locale()` — what fmtNum already used — is the panel's language.
 *
 * The check runs in a CHILD process whose system locale is German, so a date that follows the environment instead of the panel
 * reads German and cannot pass by coinciding with English.
 *
 *   [1] English panel: fmtWhen and fmtDate write English (en-GB) — not the German environment
 *   [2] Russian panel: both write Russian
 *   [3] the environment really is German here (the control that makes [1] and [2] mean something)
 *
 * Run: node tests/spa_locale_dates_selftest.mjs        (0 = pass)
 *      --perturb   formats with `undefined` again (the browser's locale) and expects RED
 */
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const PERTURB = process.argv.includes("--perturb");

if (!process.env.__SPA_LOCALE_CHILD) {
  const out = [];
  let ok = true;
  for (const lang of ["en", "ru"]) {
    const r = spawnSync(process.execPath, [fileURLToPath(import.meta.url), ...process.argv.slice(2)],
      { env: { ...process.env, __SPA_LOCALE_CHILD: lang, LANG: "de_DE.UTF-8", LC_ALL: "de_DE.UTF-8" }, encoding: "utf8" });
    process.stdout.write(r.stdout); process.stderr.write(r.stderr);
    out.push(r.status);
    if (r.status !== 0) ok = false;
  }
  console.log("");
  if (PERTURB) {
    const red = out.some(s => s !== 0);
    console.log(red ? "PERTURB OK — the browser's locale came back and a check went red" : "PERTURB FAILED — every check still passed");
    process.exit(red ? 0 : 1);
  }
  console.log(ok ? "ALL PASS" : "FAIL");
  process.exit(ok ? 0 : 1);
}

// ── child: one panel language ──────────────────────────────────────────────────────────────────────────────────────────
const LANG = process.env.__SPA_LOCALE_CHILD;
const { check, spa } = await import("./spa_env.mjs");
globalThis.localStorage = { getItem: k => (k === "swg-lang" ? LANG : null), setItem: () => {}, removeItem: () => {} };
const I = await spa("i18n.js");
let V, PA;
if (PERTURB) {
  const load = async (file, from, to) => {
    const src = readFileSync(path.join(ROOT, "js", file), "utf8");
    if (!src.includes(from)) { console.log(`PERTURB FAILED — ${file}: the anchor is gone`); process.exit(2); }
    const tmp = path.join(ROOT, "js", `.perturb_locale_${file.replace(".js", "")}_${LANG}.mjs`);
    writeFileSync(tmp, src.replace(from, to));
    try { return await import(pathToFileURL(tmp).href); } finally { try { unlinkSync(tmp); } catch (_) { /* gone */ } }
  };
  V = await load("views.js", "toLocaleString(locale(), {", "toLocaleString(undefined, {");
  PA = await load("peer-actions.js", "toLocaleDateString(locale(), {", "toLocaleDateString(undefined, {");
} else {
  V = await spa("views.js");
  PA = await spa("peer-actions.js");
}
check(`[${LANG}] the panel language is ${LANG}`, I.lang() === LANG, I.lang());

const SEC = Date.UTC(2026, 8, 17, 9, 20) / 1000;          // 17 September 2026
const opts = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
const want = LANG === "en" ? "en-GB" : "ru";
const de = new Date(SEC * 1000).toLocaleString(undefined, opts);
check(`[3] (${LANG}) the environment's own locale is German here — the control`, /Sept?\.?/.test(de) && !/сент/i.test(de) && de !== new Date(SEC * 1000).toLocaleString("en-GB", opts), de);

const w = V.fmtWhen(SEC), d = PA.fmtDate(SEC);
const expW = new Date(SEC * 1000).toLocaleString(want, opts);
const expD = new Date(SEC * 1000).toLocaleDateString(want, { year: "numeric", month: "short", day: "numeric" });
const tag = LANG === "en" ? "[1]" : "[2]";
check(`${tag} (${LANG}) fmtWhen — the "stopped since" moment — is written in ${want}`, w === expW && w !== de, { got: w, want: expW, env: de });
check(`${tag} (${LANG}) fmtDate — expiries, sessions, tokens — is written in ${want}`, d === expD, { got: d, want: expD });
if (LANG === "ru") check("[2] (ru) …and it reads Russian", /сент/i.test(w) && /сент/i.test(d), { w, d });

const { FAILS } = await import("./spa_env.mjs");
process.exit(FAILS.length ? 1 : 0);
