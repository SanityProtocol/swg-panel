/* Self-test: the box you paste a WireGuard profile into must look like the box you type routing rules into.
 *
 * `.exprof` set width, font-family, font-size, line-height and resize — and nothing else. So in DARK theme
 * it fell through to the browser's own textarea: a near-black rectangle whose hairline border disappears
 * into the sheet behind it, with no radius, no padding and no focus ring, two fields above a routing box
 * that has all four. Reported from the panel with screenshots of the two side by side.
 *
 * ⚠️ SHARED, NOT COPIED. Two controls that must look alike, described by two sets of declarations, is how
 * they stop looking alike — this file has that scar elsewhere ([[css-class-collision]]). So the fix put
 * `.exprof` into `.tf-text`'s own selector list, and what this gate asserts is exactly that: one rule, both
 * names, in all four states. Copying the properties back into a separate `.exprof` block would pass a
 * "does it have a border" check and fail this one, which is the point.
 *
 * Run: node tests/exprof_textarea_selftest.mjs      --perturb  splits them again and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let css = fs.readFileSync(path.join(ROOT, "app.css"), "utf8");
// ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
const ANCHOR = ".tf-text,.exprof{";
if (!css.includes(ANCHOR)) { console.log("ANCHOR MISSING: " + ANCHOR); process.exit(1); }
if (PERTURB) css = css.replace(/\.tf-text,\.exprof/g, ".tf-text").replace(/\.tf-text:(hover|focus),\.exprof:\1/g, ".tf-text:$1")
                      .replace(/\.tf-text::placeholder,\.exprof::placeholder/g, ".tf-text::placeholder");

// every selector list that mentions .tf-text must mention .exprof in the same breath
const rules = [...css.matchAll(/^([^{}\n]*\.tf-text[^{}\n]*)\{([^}]*)\}/gm)].map(m => ({ sel: m[1].trim(), body: m[2] }));
check("the shared rule exists at all", rules.length >= 4, rules.length);
for (const r of rules)
  check("`" + r.sel + "` covers the profile box too", /\.exprof/.test(r.sel), r.sel);

// …and the four properties whose absence was the whole complaint
const base = (rules.find(r => /border:/.test(r.body)) || {}).body || "";
for (const [what, re] of [["a visible border", /border:1px solid var\(--line-solid\)/],
                          ["rounded corners", /border-radius:7px/],
                          ["a background of its own", /background:var\(--bg\)/],
                          ["padding", /padding:7px 9px/]])
  check("…and gives it " + what, re.test(base), base.slice(0, 120));
check("…and an accent focus ring", rules.some(r => /:focus/.test(r.sel) && /border-color:var\(--brand\)/.test(r.body)));

// ⚠️ AND NOTHING RE-DECLARES IT SEPARATELY, which is how the two would drift apart again.
const solo = [...css.matchAll(/^\.exprof(?::[a-z-]+|::[a-z-]+)?\{([^}]*)\}/gm)];
check("nothing styles `.exprof` on its own any more", solo.length === 0,
      solo.map(m => m[0].slice(0, 80)));
// the markup still uses the class this is all about
const js = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
check("the profile textarea still carries the class", /<textarea class="exprof"/.test(js));

done(PERTURB, "the two boxes described separately again");
