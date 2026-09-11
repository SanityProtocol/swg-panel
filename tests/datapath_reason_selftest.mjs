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
 *   2. the interfaces here smart-route but no leg is planned yet → say THAT, and when it resolves
 *      ⚠️ this branch used to claim "only an interface that sends ALL its traffic can be accelerated",
 *      which stopped being true the moment a smart leg became relayable (RELAY-SMART-CASCADE-PLAN §12.3).
 *      A gate that pins a sentence keeps it alive long after it stops being true, so it pins the NEW one
 *      and asserts the old claim is gone from the module entirely.
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

const END = "      const live = canRelay.map(";
if (!src.includes(END)) { console.log("ANCHOR MISSING: " + END); process.exit(1); }
// ⚠️ BOUNDED BY THE LINE THAT ENDS THE BRANCH, not by a character count. This was `+ 1800`, and adding
// a comment inside the branch pushed its own closing lines out of the window — three checks went red while
// the code they describe was correct. A window that can silently stop covering what it claims to cover is
// the same defect class as a perturbation that matches nothing.
const blkEarly = src.slice(src.indexOf(GUARD), src.indexOf(END));
// Comments are not reachable text. A sentence quoted in a comment explaining why it was REMOVED must not
// read as that sentence still being live.
const srcCode = src.replace(/^\s*\/\/.*$/gm, "");
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
check("2 · smart cascade here, no leg planned → say so, and when it will resolve",
      /smartCarried\.length/.test(blk) && /worked out this link's routes yet/.test(blk)
      && /next sync/.test(blk));
check("⚠️ …and the claim it replaced is GONE, not merely unused",
      !/sends ALL its traffic through this link/.test(srcCode),
      "a smart leg IS accelerable now — the sentence cannot stay reachable anywhere");
check("3 · nothing forwards → name the setting that would make it appear",
      /Forward to \{peer\}\*? and the datapath choice appears here/.test(blk));
check("⚠️ …and they are distinct, not one shared sentence",
      new Set([/datapath is chosen there/, /worked out this link's routes yet/, /Nothing sends its whole traffic/]
        .map(re => re.test(blk))).size === 1 && /datapath is chosen there/.test(blk));

console.log("\n[2b] ⚠️ what the switch COVERS, now that it is not a whole interface");
// Under a cascade "accelerated" reads as "this interface" and under smart it does not: only the
// destinations routed over THIS link are relayed, and the relay terminates TCP, so half a rule's traffic
// stays on the forwarding path. Both are things the sheet has to say rather than leave to be discovered.
check("a smart leg is told apart from a whole-interface one by its MARK",
      /const smartLegs = elig\.filter\(\(\[, e\]\) => !e\.why && e\.mark\)/.test(src),
      "mark 0 is the whole interface; anything else is one leg of a smart cascade");
check("…and the scope sentence appears only for a smart leg", /\$\{smartLegs\.length \? html`/.test(src));
check("…naming the interfaces, not the relay instance ids", /legIfaces\.join\(", "\)/.test(src)
      && /map\(\(\[k, e\]\) => e\.iface \|\| k\)/.test(src));
check("…saying the rest of that traffic is untouched", /the rest of that traffic is untouched/.test(src));
check("⚠️ …and that UDP is never relayed", /UDP keeps forwarding either way/.test(src));
check("the CPU cap says it is the NODE's budget, shared",
      /whole relay budget, shared by every leg it accelerates/.test(src),
      "one switch can start several instances and they share one slice");
check("…and the barred list names the interface, not the instance id",
      /v1: e\.iface \|\| k/.test(src));

console.log("\n[3] the far-end answer reads the peer's OWN eligibility, not a guess");
// Both ends must agree about who owns the switch; deriving it from the same field is what guarantees that.
// The sheet already resolves the peer at its top as `prec`; the branch reuses it rather than doing the
// same lookup twice, because a second copy is one more thing that can drift from the first.
check("it reads the peer record resolved at the top of the sheet", /\(\(prec\.relay \|\| \{\}\)\.eligibility\)/.test(blk));
check("…and that record is the peer, resolved once", /const prec = \(Store\.nodes \|\| \[\]\)\.find\(n => n\.id === peer\)/.test(src));
check("…and filters that peer's eligibility by THIS node", /\.filter\(\(\[, e\]\) => e\.via === node\)/.test(blk));

console.log("\n[4] …and every sentence is translated");
const ru = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
for (const key of ["datapath is chosen there", "worked out this link's routes yet",
                   "Nothing sends its whole traffic through this link yet",
                   "the rest of that traffic is untouched", "UDP keeps forwarding either way",
                   "whole relay budget, shared by every leg it accelerates"]) {
  check(`"${key.slice(0, 34)}…" has a Russian value`, ru.includes(key), "renders English on a Russian panel");
}
check("…and «Датапас» is gone — it was a transliteration, not a word",
      !/Датапас/.test(ru) && /"Datapath": "Путь данных"/.test(ru));

done(PERTURB, "the silent `return null` restored");
