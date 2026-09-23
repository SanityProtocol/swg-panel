#!/usr/bin/env node
/* Self-test: the rows Settings shows for a node's default list are the draft it will save (ROUTING-PEERS-MESH-PLAN §7.3,
 * P3 code review). `adoptRows(held, rules, live)` keeps the rows already held where they lower to the draft — so a badge
 * still being typed (`_draft`, which the rules cannot carry) survives a remount — and applies the server's exit prune to them
 * when an exit was removed while the list was being edited, rebuilding from the rules only when neither holds.
 *
 * Run: node tests/node_list_rows_selftest.mjs   (0 = pass)
 *   --perturb   adoptRows rebuilds from the rules whenever the held rows differ (the prune path gone) and expects RED
 */
import fs from "fs";
import os from "os";
import path from "path";
import { pathToFileURL } from "url";
const PERTURB = process.argv.includes("--perturb");
let RR = "../js/rulerows.js";
if (PERTURB) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "nlr-"));
  for (const f of fs.readdirSync("js")) if (f.endsWith(".js")) fs.copyFileSync(path.join("js", f), path.join(tmp, f));
  const src = fs.readFileSync(path.join(tmp, "rulerows.js"), "utf8");
  const cut = "    if (same(pr)) return pr;";
  if (src.split(cut).length !== 2) { console.log("✗ perturbation anchor missing — this run would FALSE-PASS"); process.exit(2); }
  fs.writeFileSync(path.join(tmp, "rulerows.js"), src.replace(cut, ""));
  RR = pathToFileURL(path.join(tmp, "rulerows.js")).href;
}
const { adoptRows, rulesToRows, rowsToRules } = await import(RR);
let fails = 0;
const check = (name, ok, detail) => { console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  — " + String(JSON.stringify(detail)).slice(0, 300))); if (!ok) fails++; };

const X = "aaaa0001";
const rules = [{ enabled: true, category: "custom", targets: "example.org", action: "dev", exit_id: X },
               { enabled: true, category: "custom", targets: "203.0.113.0/24", action: "direct" },
               { enabled: true, category: "all", action: "dev", exit_id: X }];
const norm = rs => { const { rows, catchAll } = rulesToRows(rs); return rowsToRules(rows, catchAll); };
const draft = norm(rules);
const held = rulesToRows(draft);
held.rows[1] = { ...held.rows[1], _draft: "shop.exam" };           // a badge being typed in the second row

console.log("[the rows are the draft]");
check("rows that lower to the draft are kept as they are — the very same object", adoptRows(held, draft, new Set([X])) === held);
const live0 = new Set();                                              // exit X removed
const pruned = draft.map(r => r.action === "dev" ? (({ exit_id, ...x }) => ({ ...x, action: "direct" }))(r) : r);
const got = adoptRows(held, pruned, live0);
check("after an exit is removed, the rows follow the server's prune: that rule and the catch-all become Direct",
      JSON.stringify(rowsToRules(got.rows, got.catchAll)) === JSON.stringify(pruned), rowsToRules(got.rows, got.catchAll));
check("…and the badge being typed survives it (the row was pruned, not rebuilt)", got.rows[1] && got.rows[1]._draft === "shop.exam", got.rows[1]);
const other = norm([{ enabled: true, category: "custom", targets: "example.net", action: "block" }]);
const got2 = adoptRows(held, other, new Set([X]));
check("a draft the rows cannot become is rebuilt from the rules", JSON.stringify(rowsToRules(got2.rows, got2.catchAll)) === JSON.stringify(other), got2);
check("no held rows: built from the rules", JSON.stringify(rowsToRules(adoptRows(null, draft, new Set([X])).rows, adoptRows(null, draft, new Set([X])).catchAll)) === JSON.stringify(draft));

if (PERTURB) { console.log(fails ? `\nperturbed: CAUGHT (${fails} red)` : "\nperturbed: NOT CAUGHT"); process.exit(fails ? 0 : 1); }
console.log(fails ? `\n${fails} FAILED` : "\nALL PASS"); process.exit(fails ? 1 : 0);
