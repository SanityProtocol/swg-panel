/* Self-test: a rule's target field takes only the Escape meant for it — never the next control's.
 *
 * TargetField listens for Escape on `window` in the capture phase while its list is open, so a row just clicked or the pager
 * can abandon a badge edit exactly as the field does, before a Sheet closes itself instead. But the list closes on a click
 * outside, not on blur: after Tab-ing to another control the list stayed open behind and that control's Escape was
 * swallowed (the certificate series' code review, 2026-09-25; loose ends §D). Now the handler acts only when focus is in the
 * field, in its list, or on the page body (a clicked row is not focusable), and focus leaving the field closes the list.
 *
 * The two handlers are lifted out of js/routing.js as shipped and run against fake elements. No browser.
 *
 * Run: node tests/spa_targetfield_escape_selftest.mjs
 *      --perturb   the focus test taken out of the Escape handler (the shipped one) and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PERTURB = process.argv.includes("--perturb");
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (!ok && detail !== undefined ? "  — " + JSON.stringify(detail) : "")); if (!ok) fails++; };

let src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
const a = src.indexOf("    const mine = t => !!t && ((ref.current"), b = src.indexOf("    window.addEventListener(\"scroll\", onMove, true);", a);
if (a < 0 || b < 0) { console.log("ANCHOR MISSING: TargetField's Escape / focus handlers"); process.exit(1); }
let body = src.slice(a, b);
if (PERTURB) {
  const g = " || (a && a !== document.body && !mine(a))";
  if (body.split(g).length !== 2) { console.log("ANCHOR MISSING: the focus test"); process.exit(1); }
  body = body.replace(g, "");
}

// fake elements: an element "contains" itself and the ids listed as its descendants
const el = (id, kids = []) => ({ id, contains: t => !!t && (t.id === id || kids.includes(t.id)) });
const input = el("input"), field = el("field", ["input", "trail"]), pop = el("pop", ["row", "pager"]);
const body_ = el("body"), other = el("other-dropdown");
function run(active) {
  const calls = { key: 0, close: 0, stopped: 0 };
  const document = { activeElement: active, body: body_ };
  const ref = { current: field }, popRef = { current: pop }, inRef = { current: input };
  const onKeyRef = { current: () => { calls.key++; } }, setOpen = v => { if (v === false) calls.close++; };
  const f = new Function("document", "ref", "popRef", "inRef", "onKeyRef", "setOpen", body + "\nreturn { onEsc, onFocus };");
  const h = f(document, ref, popRef, inRef, onKeyRef, setOpen);
  const ev = { key: "Escape", stopPropagation: () => { calls.stopped++; }, preventDefault() {} };
  return { h, calls, ev };
}

console.log("[Escape: the field's own, and nobody else's]");
let r = run(el("row")); r.h.onEsc(r.ev);
check("a row of the list focused → the field takes it (a badge edit is abandoned)", r.calls.key === 1 && r.calls.stopped === 1, r.calls);
r = run(body_); r.h.onEsc(r.ev);
check("focus on the page body (a clicked row is not focusable) → the field takes it", r.calls.key === 1, r.calls);
r = run(input); r.h.onEsc(r.ev);
check("the field's own input → left to its onKey (not handled twice)", r.calls.key === 0 && r.calls.stopped === 0, r.calls);
r = run(other); r.h.onEsc(r.ev);
check("another control, Tab-ed to → its Escape is NOT swallowed", r.calls.key === 0 && r.calls.stopped === 0, r.calls);

console.log("\n[focus leaving closes the list]");
r = run(other); r.h.onFocus({ target: other });
check("focus moves to another control → the list closes", r.calls.close === 1, r.calls);
r = run(el("trail")); r.h.onFocus({ target: el("trail") });
check("focus moves within the field (its trail) → the list stays", r.calls.close === 0, r.calls);
r = run(el("pager")); r.h.onFocus({ target: el("pager") });
check("focus moves into the list (the pager) → the list stays", r.calls.close === 0, r.calls);

console.log(fails ? `\nFAIL (${fails})` : "\nALL PASS" + (PERTURB ? " — but the perturbation was planted and should have gone RED" : ""));
process.exit(fails ? 1 : PERTURB ? 2 : 0);
