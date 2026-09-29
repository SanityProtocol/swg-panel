/* Self-test: text typed into a rule and never added holds every Save, like the text view's draft already did.
 *
 * A rule's field reports what it shows but its row does not hold through `onLint` into the row's `_draft`, and every Save
 * path asks for it (egressSaveBlock on the four interface sheets, nodeListBlock on Settings → Network, the custom-list
 * sheet). It reported the `</>` text view's draft only: text typed into the box without Enter was dropped by a Save that
 * went through for another change — measured on Settings → Network in the 1.8.8 qualification: `exa` typed into msk-main's
 * default list, the mesh port changed, Save → "1 change to apply: mesh port", the typed text silently not in it. The
 * routing plan had promised this block ("a half-typed badge in the node list blocks Save, as it does on every interface
 * sheet").
 *
 * Imports js/routing.js as shipped (spa_env) and checks `unappliedLint`, what egressSaveBlock makes of it, and that
 * TargetField's effect is wired to it with the box's state in its dependencies.
 *
 * Run: node tests/spa_unapplied_lint_selftest.mjs
 *      --perturb   the box branch taken out (the shipped behaviour: text view only) and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let { unappliedLint, egressSaveBlock } = await spa("routing.js");
if (PERTURB) {
  const shipped = unappliedLint;
  unappliedLint = a => (a.asText ? shipped(a) : "");
}
const NONE = { text: "", forQ: null };
const b = { t: "target", kind: "site", value: "example.com", raw: "example.com" };

console.log("[the box]");
check("text typed and not added → reported", !!unappliedLint({ asText: false, draft: "", q: "netflix.com", editing: null, pending: NONE }));
check("…including a search left in the box", !!unappliedLint({ asText: false, draft: "", q: "you", editing: null, pending: NONE }));
check("an empty box (or only spaces) → nothing", unappliedLint({ asText: false, draft: "", q: "   ", editing: null, pending: NONE }) === "");
check("a badge opened to read and left as it was → nothing (the row still holds it)",
      unappliedLint({ asText: false, draft: "", q: "example.com", editing: { b }, pending: NONE }) === "");
check("a badge opened and CHANGED → reported (Save would keep the old one)",
      !!unappliedLint({ asText: false, draft: "", q: "example.org", editing: { b }, pending: NONE }));
check("the message does not carry the typed text (the parent hears a transition, not every keystroke)",
      unappliedLint({ asText: false, draft: "", q: "a", editing: null, pending: NONE }) ===
      unappliedLint({ asText: false, draft: "", q: "ab", editing: null, pending: NONE }));

console.log("\n[the text view — unchanged]");
check("an unapplied draft → reported", !!unappliedLint({ asText: true, draft: "a.com\nb.com", q: "", editing: null, pending: NONE }));
check("…with the refusal's own reason when there is one",
      unappliedLint({ asText: true, draft: "x", q: "", editing: null, pending: { text: "why", forQ: "x" } }) === "why");
check("an empty draft → nothing", unappliedLint({ asText: true, draft: "  ", q: "", editing: null, pending: NONE }) === "");

console.log("\n[every Save path asks the row's _draft]");
const msg = unappliedLint({ asText: false, draft: "", q: "netflix.com", editing: null, pending: NONE });
const eg = { mode: "smart", rows: [{ _gid: 1, action: "direct", badges: [b], _draft: msg || undefined }], catchAll: { action: "direct" } };
check("egressSaveBlock holds the Save on it", !!egressSaveBlock(eg, "forcedns") && egressSaveBlock(eg, "forcedns") === msg, egressSaveBlock(eg, "forcedns"));

console.log("\n[TargetField is wired to it]");
const src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
const eff = /const v = unappliedLint\(\{ asText, draft, q, editing, pending \}\);[\s\S]{0,200}?\}, \[([^\]]*)\]\);/.exec(src);
check("the lint effect calls unappliedLint", !!eff);
check("…and re-runs when the box or the badge being edited changes", !!eff && ["q", "editing", "asText", "draft"].every(k => eff[1].split(/[\s,]+/).includes(k)), eff && eff[1]);

done(PERTURB);
