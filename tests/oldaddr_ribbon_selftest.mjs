/* Self-test: the panel's own entry file is not "a previous address".
 *
 * The migration ribbon compares this tab's location against the panel's BLESSED public url and, when they
 * differ, says "You're on a previous panel address" with a button to the current one. The comparison
 * included the raw `location.pathname`, and a mount base never carries a file name — so opening the panel
 * at `https://host:2087/index.html` (a bookmark, a hand-typed URL, a proxy that does not rewrite `/`)
 * differed from a blessed base of "" and the ribbon fired, offering to send the operator to the address
 * they were already on. Observed on swgt.
 *
 * ⚠️ AND A REAL SUBPATH MOUNT MUST STILL COMPARE. `/swg` is a base; `/swg/index.html` is the same place;
 * `/other` is not, and neither is `/indexing` — the guard must strip a file name, not a prefix.
 *
 * Run: node tests/oldaddr_ribbon_selftest.mjs    --perturb  compares the raw pathname again, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const src = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");

// Take the real expression out of app.js — not a retyped copy, or this tests itself.
const m = src.match(/const hereBase = (location\.pathname[^\n;]*);/);
check("the base normaliser was found in app.js", !!m, "it moved — this gate is blind");
if (!m) { done(PERTURB); }
let expr = m[1];
if (PERTURB) expr = 'location.pathname.replace(/\\/+$/, "")';

const norm = p => new Function("location", "return " + expr + ";")({ pathname: p });

console.log("\n[1] the entry file is the same address as the mount it sits in");
for (const [p, base] of [["/", ""], ["/index.html", ""], ["/index.htm", ""],
                         ["/swg/", "/swg"], ["/swg/index.html", "/swg"], ["/swg", "/swg"]]) {
  check(`${p.padEnd(17)} is the base ${JSON.stringify(base)}`, norm(p) === base, `-> ${JSON.stringify(norm(p))}`);
}

console.log("\n[2] ⚠️ …and a genuinely different path still differs");
// A guard that swallowed these would hide a real migration, which is worse than the false alarm it fixes.
for (const [p, base] of [["/other", ""], ["/swg/index.html", ""], ["/indexing", ""], ["/", "/swg"]]) {
  check(`${p.padEnd(17)} is NOT the base ${JSON.stringify(base)}`, norm(p) !== base, `-> ${JSON.stringify(norm(p))}`);
}

console.log("\n[3] …and the ribbon still has the rest of its guards");
check("the console door is still exempt", /this IS the console door/.test(src));
check("…and host and port are still compared", /location\.hostname === c\.host/.test(src) && /_effPort\(scheme, location\.port\) === c\.port/.test(src));

done(PERTURB, "the raw pathname compared again");
