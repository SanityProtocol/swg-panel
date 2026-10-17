#!/usr/bin/env node
/* Self-test: a typed `list:all` never becomes a list badge, on any path (operator 2026-10-17: "refuse list:all").
 *
 * `all` is no list — it is "Everything else". As a badge it stored {category:"all"} in the middle of a rule list, which the
 * node runs first-match, so every rule below it was dead while the footer showed another choice. Two readers decide whether
 * a typed list is addable: `readToken` (space, comma, Tab, the textarea, paste) and `knownListId` (the box's Enter and the
 * dropdown's "Use what you typed" row, through `readList`). Both must say no; a real list must still read as one.
 *
 * Run: node tests/spa_list_all_selftest.mjs   (0 = pass)
 *      --perturb   knownListId accepts `all` again (the Enter / dropdown path) — expects red
 */
import { spa, check, done, ROOT } from "./spa_env.mjs";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PERTURB = process.argv.includes("--perturb");
let R;
if (PERTURB) {
  const src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
  const a = 'export const knownListId = id => !!id && String(id).toLowerCase() !== "all" && (';
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING: knownListId's `all` guard — this run would FALSE-PASS"); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_list_all.js");
  fs.writeFileSync(tmp, src.replace(a, "export const knownListId = id => !!id && ("));
  try { R = await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
} else {
  R = await spa("routing.js");
}
const { knownListId, SMART_CATEGORIES } = R;
const { readToken } = await spa("rulerows.js");

console.log("[the box's Enter and the dropdown — knownListId]");
for (const id of ["all", "ALL", "All"])
  check(`knownListId(${JSON.stringify(id)}) is false — "Everything else" is not a list`, knownListId(id) === false, knownListId(id));
const real = (SMART_CATEGORIES().find(([c]) => c !== "all") || [])[0];
check(`…and a curated list (${real}) is still known`, !!real && knownListId(real) === true, real);

console.log("[space, comma, Tab, the textarea, paste — readToken, with the panel's own policy]");
for (const tok of ["list:all", "LIST:All", "list: all"]) {
  const r = readToken(tok, { knownList: knownListId });
  check(`readToken(${JSON.stringify(tok)}) is refused as "catch_all", never a badge`, r && r.why === "catch_all" && !r.b, r);
}
const rr = readToken("list:" + real, { knownList: knownListId });
check("…and `list:<a curated list>` still reads as that list", !!(rr && rr.b && rr.b.id === real), rr);

done(PERTURB, "knownListId accepts `all`");
