/* Self-test: the person / group / device picker answers the arrow keys.
 *
 * `UserPicker` (New peer, Edit peer, a group's sheet, a network's People with access, Rule settings' "For whom") had no
 * keyboard navigation: with more than one match nothing could be picked without a mouse (1.8.8 qualification, F2). The
 * keys are now one pure step, `ucKeyStep`: ↓ / ↑ move a highlight (none until a key moves it — TargetField's −1), Enter
 * picks the highlighted row, and Enter with nothing highlighted keeps its old rule: the one match, or nothing.
 *
 * Imports js/peer-actions.js as shipped (spa_env) and drives the step; checks the component is wired to it.
 * Run: node tests/spa_userpicker_keys_selftest.mjs
 *      --perturb   the arrow keys taken out of the step and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let { ucKeyStep } = await spa("peer-actions.js");
if (PERTURB) { const real = ucKeyStep; ucKeyStep = (k, st) => (k === "ArrowDown" || k === "ArrowUp") ? {} : real(k, st); }
const opts = [["u", ""], ["g", "fam"], ["u", "anna"], ["u", "boris"], ["d", "phone"]];
const st = (o) => ({ open: true, q: "", act: -1, opts, n: 4, ...o });

console.log("[walking the list]");
let r = ucKeyStep("ArrowDown", st({ open: false }));
check("↓ on a closed picker opens it and lights the first row", r.open === true && r.act === 0 && r.prevent, r);
r = ucKeyStep("ArrowDown", st({ act: 2 }));
check("↓ moves one row down", r.act === 3, r);
r = ucKeyStep("ArrowDown", st({ act: 4 }));
check("…and stops at the last row", r.act === 4, r);
r = ucKeyStep("ArrowUp", st({ act: 0 }));
check("↑ from the first row lights nothing (back to typing)", r.act === -1 && r.prevent, r);

console.log("\n[Enter]");
r = ucKeyStep("Enter", st({ act: 2 }));
check("picks the highlighted row", r.pick && r.pick[0] === "u" && r.pick[1] === "anna" && r.prevent, r);
r = ucKeyStep("Enter", st({ act: 1 }));
check("…a group, when a group is lit", r.pick && r.pick[0] === "g", r);
r = ucKeyStep("Enter", { open: true, q: "ann", act: -1, opts: [["u", ""], ["u", "anna"]], n: 1 });
check("nothing lit, one match typed → that match (never the \"unassigned\" row)", r.pick && r.pick[1] === "anna", r);
r = ucKeyStep("Enter", st({ q: "a" }));
check("nothing lit, several matches → no pick, and Enter does not reach the window's main button", !r.pick && r.prevent, r);
r = ucKeyStep("Escape", st({ act: 2 }));
check("Escape closes", r.close === true, r);

console.log("\n[the component is wired to it]");
const src = fs.readFileSync(path.join(ROOT, "js", "peer-actions.js"), "utf8");
check("the input's keys go through ucKeyStep", /onKeyDown=\$\{onKey\}/.test(src) && /const r = ucKeyStep\(e\.key,/.test(src));
check("every row can be lit (unassigned, groups, people, devices)", (src.match(/\(isAct\("[ugd]", /g) || []).length === 4);
check("the lit row is styled like a hovered one", /\.uc-opt:hover,\.uc-opt\.act\{/.test(fs.readFileSync(path.join(ROOT, "app.css"), "utf8")));
done(PERTURB);
