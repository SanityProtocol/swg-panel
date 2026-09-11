/* Self-test: every field the exit form can EDIT must be carried by every path that SAVES it.
 *
 * `ExitFields` asks four questions — title, device, "leaves as", and the typed gateway. The gateway was
 * rendered, typed into, and then dropped: `commitForm` passed three of the four to `addDevice`/`renameExit`,
 * `addRow` built its row from three, and the pencil seeded three. So the operator typed the address that
 * makes a card legal, pressed Add, and the server answered "exit device refused: nic_nogw" — refusing the
 * card because of the very field they had just filled in. A NIC reached only by policy routing has no
 * DETECTABLE gateway, so for that whole class of two-uplink boxes this was the feature's only door.
 *
 * ⚠️ GATED AS A CLASS, NOT AS AN INSTANCE. A test that asserted "gw is carried" would pass for ever and
 * catch nothing when a FIFTH field is added the same way. This derives the editable set from the form
 * itself and requires each writer to mention every member, so the next field added to `ExitFields` fails
 * here until it is wired.
 *
 * ⚠️ AND IT IS A SOURCE GATE ON PURPOSE. These are closures inside a rendered component: the no-DOM harness
 * imports modules without rendering sheets, so it cannot call them, and it did not see this bug. Only the
 * browser did. A source gate is what is available; its own anchors are asserted present so a rename fails
 * loudly rather than passing vacuously.
 *
 * Run: node tests/spa_exitform_selftest.mjs      --perturb  drops `gw` from every writer, as it shipped.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let SET = readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
let ROU = readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
if (PERTURB) {
  SET = SET.replace(/,?\s*gw: String\((?:gw|nv\.gw)\s*\|\|\s*""\)\.trim\(\)/g, "")
           .replace(/, form\.gw\)/g, ")").replace(/, gw = ""\)/g, ")").replace(/, gw\)/g, ")");
  ROU = ROU.replace(/, gw: x\.gw \|\| ""/g, "");
}

/** The body of a named function/const, from its declaration to the next top-level one. */
const body = (src, decl, endMark) => {
  const i = src.indexOf(decl);
  if (i < 0) return "";
  const j = endMark ? src.indexOf(endMark, i + decl.length) : -1;
  return src.slice(i, j > 0 ? j : i + 2600);
};

// ── what the form can edit, derived from the form ────────────────────────────────────────────────────
const form = body(SET, "function ExitFields(", "\nfunction ExitManageSheet");
check("the ExitFields body is locatable (a miss here would pass everything)", form.length > 400, form.length);
const editable = [...new Set([...form.matchAll(/onChange\(\{\s*([A-Za-z_]+)\s*:/g)].map(m => m[1]))].sort();
check("the form's editable fields are discoverable", editable.length >= 4, editable.join(","));
console.log("      editable: " + editable.join(", "));

// ── every writer must mention every one of them ──────────────────────────────────────────────────────
const WRITERS = [
  ["commitForm  (the Network screen's submit)", body(SET, "const commitForm = ()", "\n  return html"), "form."],
  ["addDevice   (mint / update the record)",    body(SET, "const addDevice = async", "const renameExit"), null],
  ["renameExit  (edit an existing exit)",       body(SET, "const renameExit = async", "const commitForm"), null],
  ["addRow      (the manage sheet's add)",      body(SET, "const addRow = ()", "\n  // A pasted profile"), "nv."],
];
console.log("\n[1] every editable field reaches every writer");
for (const [name, src, pfx] of WRITERS) {
  check(`${name} — body found`, src.length > 60, src.length);
  for (const f of editable) {
    // `device` is the row's identity and each writer names it its own way; the rest are values that must
    // be carried by name. `title` becomes `label` in the record, so accept either spelling.
    const alt = f === "title" ? ["title", "label"] : [f];
    const seen = alt.some(a => src.includes(pfx ? pfx + a : a));
    check(`  ${name.split(" ")[0]} carries \`${f}\``, seen, src.slice(0, 200));
  }
}

console.log("\n[2] the pencil SEEDS every editable field, or the form opens blank and saves the blank");
const pen = body(ROU, 'penBtn({ kind: "exit"', "\n                       // The switch answers");
check("the rename penBtn payload is locatable", pen.includes("kind:"), pen.slice(0, 120));
for (const f of editable) {
  if (f === "title") { check("  penBtn seeds `title`", /title:/.test(pen), pen); continue; }
  check(`  penBtn seeds \`${f}\``, new RegExp(f + "\\s*:").test(pen), pen.slice(0, 260));
}

done(PERTURB, "gw dropped from every writer and from the pencil");
