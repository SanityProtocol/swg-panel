/* Self-test: a leg with no datapath CHOICE still says why.
 *
 * The Datapath control (Forward ⇄ Relay) only exists on a leg that carries a WHOLE-interface cascade —
 * that is the only thing the relay accelerates in v1. When it does not, the sheet used to
 * `return null`, so the section vanished entirely.
 *
 * ⚠️ AND THE CARD ABOVE IT SAYS "CASCADE" FOR BOTH KINDS. «каскад» (whole-interface forward) and «умный
 * каскад» (smart, per-destination) are one word apart, so an operator comparing two legs sees the same
 * kind of badge with the control on one and not the other, and nothing anywhere explains the difference.
 * Reported from the fleet as "the Forward/Relay switch is gone" — it was never gone; it was never
 * applicable, and saying nothing is what made that indistinguishable.
 *
 * Three reachable causes, three different answers — a shared shrug would be no better than silence:
 *   1. the FAR end forwards to us  → the choice exists, on their side (the mode belongs to whoever sends)
 *   2. the interfaces here smart-route → only a whole-interface cascade can be accelerated
 *   3. nothing forwards at all      → set an interface's egress to "Forward to <peer>" and it appears
 *
 * Run: node tests/datapath_reason_selftest.mjs    --perturb  restores `return null`, RED.
 */
import fs from "node:fs";
import path from "node:path";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let src = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
const GUARD = "      if (!elig.length) {";
// ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
if (!src.includes(GUARD)) { console.log("ANCHOR MISSING: " + GUARD); process.exit(1); }
if (PERTURB) src = src.replace(GUARD, "      if (!elig.length) return null;\n      if (false) {");

const blkEarly = src.slice(src.indexOf(GUARD), src.indexOf(GUARD) + 1800);
console.log("[1] the section is rendered even when there is no choice");
check("the empty case no longer returns null outright", !/if \(!elig\.length\) return null;/.test(src),
      "a leg with nothing to accelerate shows nothing at all again");
check("…it still renders the Datapath label", /dp-sec/.test(blkEarly));
check("…and shows Forward as the standing mode", /T\("Forward"\)/.test(blkEarly));

console.log("\n[2] ⚠️ …and the reason is the RIGHT one of three");
const blk = blkEarly;
check("1 · the far end forwards to us → the choice is on their side",
      /datapath is chosen there/.test(blk) && /e\.via === node/.test(blk),
      "the peer's own eligibility is what says the traffic comes from them");
check("2 · smart cascade here → only a whole-interface cascade is accelerable",
      /smartCarried\.length/.test(blk) && /sends ALL its traffic through this link/.test(blk));
check("3 · nothing forwards → name the setting that would make it appear",
      /Forward to \{peer\}\*? and the datapath choice appears here/.test(blk));
check("⚠️ …and they are distinct, not one shared sentence",
      new Set([/datapath is chosen there/, /sends ALL its traffic/, /Nothing sends its whole traffic/]
        .map(re => re.test(blk))).size === 1 && /datapath is chosen there/.test(blk));

console.log("\n[3] the far-end answer reads the peer's OWN eligibility, not a guess");
// Both ends must agree about who owns the switch; deriving it from the same field is what guarantees that.
// The sheet already resolves the peer at its top as `prec`; the branch reuses it rather than doing the
// same lookup twice, because a second copy is one more thing that can drift from the first.
check("it reads the peer record resolved at the top of the sheet", /\(\(prec\.relay \|\| \{\}\)\.eligibility\)/.test(blk));
check("…and that record is the peer, resolved once", /const prec = \(Store\.nodes \|\| \[\]\)\.find\(n => n\.id === peer\)/.test(src));
check("…and filters that peer's eligibility by THIS node", /\.filter\(\(\[, e\]\) => e\.via === node\)/.test(blk));

console.log("\n[4] …and every sentence is translated");
const ru = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
for (const key of ["datapath is chosen there", "sends ALL its traffic through this link",
                   "Nothing sends its whole traffic through this link yet"]) {
  check(`"${key.slice(0, 34)}…" has a Russian value`, ru.includes(key), "renders English on a Russian panel");
}
check("…and «Датапас» is gone — it was a transliteration, not a word",
      !/Датапас/.test(ru) && /"Datapath": "Путь данных"/.test(ru));

done(PERTURB, "the silent `return null` restored");
