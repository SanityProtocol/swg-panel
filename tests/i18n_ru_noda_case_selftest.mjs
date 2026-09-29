/* Self-test: the Russian panel never leaves «нода» in the nominative where the sentence needs another case.
 *
 * «нода» (feminine) replaced an older noun across the translations, and nine strings kept it undeclined —
 * «переключите нода», «на самый слабый нода», «каждый подключающийся нода», «не удалось создать нода» … — found in
 * the 1.8.8 qualification's Russian pass on the Blocking tab. The i18n audits check that a string IS translated, not
 * its grammar. This gate checks the shapes a nominative «нода» can never follow: an imperative (-ите/-йте) or an
 * infinitive (-ть) whose object it is, and a masculine adjective or participle (-ый/-ий/-ой/-ийся/-ыйся) meant to
 * agree with it. A finite verb is left out on purpose («так что работает нода» is a subject), and so are nouns
 * (a genitive «сети» may stand before a subject).
 *
 * Run: node tests/i18n_ru_noda_case_selftest.mjs
 *      --perturb   plants «переключите нода» into the text and expects red.
 *      SWG_RU=<file>  reads another copy of ru.js (e.g. the release before the fix).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PERTURB = process.argv.includes("--perturb");
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (!ok && detail !== undefined ? "  — " + JSON.stringify(detail).slice(0, 600) : "")); if (!ok) fails++; };

let src = fs.readFileSync(process.env.SWG_RU || path.join(ROOT, "js", "lang", "ru.js"), "utf8");
if (PERTURB) src += '\n  "planted": "Переключите нода на Force-DNS.",\n';

const L = "А-Яа-яЁё";
const BAD = new RegExp(`(?<![${L}])([${L}]+(?:ите|йте|ть|ый|ий|ой|ийся|ыйся))\\s+нода(?![${L}])`, "g");

console.log("[«нода» after a word that needs another case]");
const hits = [];
src.split("\n").forEach((line, i) => { for (const m of line.matchAll(BAD)) hits.push(`${i + 1}: …${line.slice(Math.max(0, m.index - 30), m.index + m[0].length + 10)}…`); });
check("no imperative, infinitive or masculine adjective stands before a nominative «нода»", hits.length === 0, hits);

console.log("\n[the pattern itself — it must catch the shipped mistakes and pass the right forms]");
const t = s => new RegExp(BAD.source).test(s);
check("catches «переключите нода»", t("или переключите нода на Force-DNS"));
check("catches «создать нода»", t("не удалось создать нода"));
check("catches «на самый слабый нода»", t("на самый слабый нода, прежде"));
check("catches «каждый подключающийся нода»", t("каждый подключающийся нода примет"));
check("passes «переключите ноду»", !t("или переключите ноду на Force-DNS"));
check("passes «поэтому нода не может»", !t("поэтому нода не может"));
check("passes «с которого нода обращается»", !t("с которого нода обращается"));
check("passes «так что работает нода»", !t("так что работает нода"));

console.log(fails ? `\nFAIL (${fails})` : "\nALL PASS" + (PERTURB ? " — but the perturbation was planted and should have gone RED" : ""));
process.exit(fails ? 1 : PERTURB ? 2 : 0);
