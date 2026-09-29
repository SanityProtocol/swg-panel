/* Self-test: the Edit interface sheet guards what was changed by a CLICK, and its Cancel goes through the guard.
 *
 * The Sheet's own "Discard unsaved changes?" sees typed fields only (input/change events). The Edit interface sheet's
 * AmneziaWG version switch, access level, exit and routing rules and filter chips are all clicks — they closed on Escape, ✕
 * or a click outside with no word, and the footer's Cancel called closeModal directly, bypassing the guard even for typed
 * fields. Measured in the 1.8.8 qualification: a pending 2.0 → 3.1 switch vanished on Escape while a changed port asked.
 * The sheet now hands the Sheet a `dirtyRef` holding the same `edited` test that enables Save, and a `closeRef` its Cancel
 * goes through.
 *
 * Reads js/iface.js as shipped (EditIfaceSheet renders a live store; the wiring is what regressed, so the wiring is checked).
 *
 * Run: node tests/spa_edit_sheet_guard_selftest.mjs
 *      --perturb   the Cancel back on closeModal and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PERTURB = process.argv.includes("--perturb");
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (!ok && detail !== undefined ? "  — " + JSON.stringify(detail).slice(0, 300) : "")); if (!ok) fails++; };

let src = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
if (PERTURB) {
  const a = 'onClick=${() => (closeRef.current ? closeRef.current() : closeModal())}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${busy || !!egressSaveBlock(eg, emode)';
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING: the Edit sheet's Cancel"); process.exit(1); }
  src = src.replace(a, 'onClick=${closeModal}>${T("Cancel")}</button><button class="btn btn-primary" disabled=${busy || !!egressSaveBlock(eg, emode)');
}
const i = src.indexOf("export function EditIfaceSheet("), j = src.indexOf("\nexport function ", i + 10);
const body = src.slice(i, j > 0 ? j : undefined);
check("found EditIfaceSheet", i > 0, i);

console.log("[the guard knows every change, clicked or typed]");
const ed = /const edited = ([\s\S]*?);\n/.exec(body);
check("`edited` covers the fields, the filter chips, the AWG values and the version switch",
      !!ed && ["_ifBody", "blk", "_awgTrim(awg)", "genChanged"].every(k => ed[1].includes(k)), ed && ed[1]);
check("…the fields it compares include the access level and the exit with its rules (`reach`, egressBody)",
      /const _ifBody = \{[^}]*reach[^}]*\.\.\.egressBody\(eg\)/.test(body));
check("the Sheet gets a dirtyRef set from `edited` (not from `notup`: a bring-up is not an edit)",
      /dirtyRef\.current = edited;/.test(body) && /<\$\{Sheet\}[^>]*dirtyRef=\$\{dirtyRef\}/.test(body));

console.log("\n[Cancel asks, like Escape and ✕]");
check("the Sheet gets a closeRef", /<\$\{Sheet\}[^>]*closeRef=\$\{closeRef\}/.test(body));
check("the footer's Cancel goes through it", /onClick=\$\{\(\) => \(closeRef\.current \? closeRef\.current\(\) : closeModal\(\)\)\}>\$\{T\("Cancel"\)\}/.test(body));

console.log(fails ? `\nFAIL (${fails})` : "\nALL PASS" + (PERTURB ? " — but the perturbation was planted and should have gone RED" : ""));
process.exit(fails ? 1 : PERTURB ? 2 : 0);
