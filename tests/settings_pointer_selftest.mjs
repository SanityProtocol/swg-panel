/* Self-test: every sentence that sends the operator to "Settings ▸ <section>" names a section the sidebar HAS — in
 * English and in each translation, under the name that translation's sidebar shows.
 *
 * Found by the 1.8.8 qualification: the Russian sidebar calls "Routing & Blocking" «Маршрутизация», while the link
 * that jumps there read «Настройки ▸ Политики» — a name the operator could not find on the screen — and a rule
 * badge said "Switched off for this node in Settings ▸ Routing lists", a caption inside that section, not a place
 * in the sidebar. A pointer is only useful if the words match the sidebar.
 *
 * Reads the sidebar's canonical labels from screen-settings.js (SECTIONS) and every key of js/lang/ru.js.
 *
 * Run: node tests/settings_pointer_selftest.mjs
 *      --perturb   plants the old «Настройки ▸ Политики» and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PERTURB = process.argv.includes("--perturb");
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (!ok && detail ? "  — " + detail : "")); if (!ok) fails++; };

const settings = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
const secLine = settings.split("\n").find(l => l.includes("const SECTIONS = [["));
if (!secLine) { console.log("ANCHOR MISSING: const SECTIONS"); process.exit(1); }
const EN = [...secLine.matchAll(/\["[a-z]+", "([^"]+)"\]/g)].map(m => m[1]);
check("the sidebar's sections were read (" + EN.length + ")", EN.length >= 10, secLine.slice(0, 200));

let ruSrc = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
if (PERTURB) {
  const a = '"Settings ▸ Routing & Blocking": "Настройки ▸ Маршрутизация",';
  if (ruSrc.split(a).length !== 2) { console.log("ANCHOR MISSING: the Routing & Blocking pointer"); process.exit(1); }
  ruSrc = ruSrc.replace(a, '"Settings ▸ Routing & Blocking": "Настройки ▸ Политики",');
}
const RU = new Map();
for (const m of ruSrc.matchAll(/^\s*"((?:[^"\\]|\\.)*)":\s*\n?\s*"((?:[^"\\]|\\.)*)"/gm)) RU.set(m[1], m[2]);
const ruLabel = en => RU.get(en) || en;             // an untranslated label (a brand: "WARP") stays itself

const POINT_EN = /Settings\s*[▸→]\s*([^.,;:)\n"]+)/g;
const POINT_RU = /Настройк(?:и|ах)\s*[▸→]\s*«?([^».,;:)\n"]+)/g;   // «в Настройках → Сеть» is the same place, declined
// A CLIENT APP's own menu ("VK TURN Proxy → Settings → Import…", "the app's Settings → …", a WINGS V path) is not the
// panel's sidebar: skip a pointer that follows an arrow or names an app just before it.
const isAppPath = (str, at) => /(→|▸)\s*$/.test(str.slice(0, at)) || /app'?s?\W{0,3}$|app's\s+$/.test(str.slice(Math.max(0, at - 12), at))
  || /link \($/.test(str.slice(Math.max(0, at - 6), at));
let seen = 0;
for (const [en, ru] of RU) {
  for (const m of en.matchAll(POINT_EN)) {
    if (isAppPath(en, m.index)) continue;
    seen++;
    const tail = m[1].trim();
    const sec = EN.find(s => tail.startsWith(s));
    check("EN names a sidebar section: \"" + m[0].trim() + "\"", !!sec, "no sidebar section starts \"" + tail + "\"");
    if (!sec) continue;
    const want = ruLabel(sec);
    const rus = [...ru.matchAll(POINT_RU)].map(r => r[1].trim());
    check("RU names it as its sidebar does («" + want + "»): " + JSON.stringify(ru.slice(0, 80)),
          rus.length > 0 && rus.every(t => t.startsWith(want)), "found " + JSON.stringify(rus));
  }
}
check("pointers were found at all (" + seen + ")", seen >= 3);
console.log(fails ? `\nFAIL (${fails})` : "\nALL PASS" + (PERTURB ? " — but the perturbation was planted and should have gone RED" : ""));
process.exit(fails ? 1 : PERTURB ? 2 : 0);
