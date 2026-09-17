/* Self-test: the listen address a NEW turn-proxy is created with must be one the box actually has.
 *
 * `epIp` is the node's endpoint as read out of its own snapshot — and that value comes from the node's
 * LOCAL config, which the panel never corrects. So it goes stale the moment a provider moves the box, and
 * the install form defaulted to it unconditionally:
 *
 *     const lInit = epIp ? (ips.includes(epIp) ? epIp : "__custom__") : (ips[0] || "__custom__");
 *
 * `ipChoices(nrec, epIp)` puts `epIp` FIRST in the candidate list, so `ips.includes(epIp)` is always true
 * and the default is always the reported endpoint. The safety net could not help either: the form asked
 * `useHostOnNode(lhost, ips)` — validating the candidate against a list built FROM that candidate, which
 * can only ever answer "ok" — and then rendered the warning only for `lsel === "__custom__"`, so an address
 * picked from the dropdown was never questioned at all. A guard that exists and cannot fire.
 *
 * MEASURED 2026-09-16 on a customer's box whose provider changed its IP: every proxy installed or edited
 * afterwards was born with `-listen <dead ip>`, died with `panic: bind: cannot assign requested address`,
 * and was restarted by systemd — 262 panics against 272 starts in 90 minutes. The operator's symptom was
 * "clients connect but get no traffic", because each restart killed sessions mid-handshake. The address was
 * the last thing suspected: the panel's own screens showed the NEW one, since apply_iface_meta overlays the
 * node record on top of the snapshot everywhere except here.
 *
 * What this drives, through the REAL exported helper:
 *   [1] a reported endpoint the node's own addresses corroborate is still the default
 *   [2] one they do NOT corroborate loses its privilege — an address the node reports wins instead
 *   [3] a BRIDGE node keeps defaulting to it: its real addresses are container-private and filtered out of
 *       the picker, so nothing there could ever corroborate, and that absence is not evidence
 *   [4] a node that has reported no addresses at all changes nothing — "I cannot check" is not "wrong"
 *   [5] with no endpoint reported, an offered address is used
 *   [6] with nothing to go on, the form falls back to Custom rather than inventing a default
 *
 * Run: node tests/spa_turnlisten_selftest.mjs
 *      --perturb   restores the unconditional preference for the reported endpoint — expects RED in [2].
 */
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");

let listenHostInit = (await spa("turn.js")).listenHostInit;

if (PERTURB) {
  const SRC = path.join(ROOT, "js", "turn.js");
  const src = readFileSync(SRC, "utf8");
  const anchor = "  if (epIp && (have.includes(epIp) || !own.length)) return epIp;";
  // ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
  if (src.split(anchor).length - 1 !== 1) {
    console.log("PERTURB ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
    process.exit(1);
  }
  // Written BESIDE the real module so its own relative imports resolve exactly as they do in the browser.
  const tmp = path.join(ROOT, "js", ".perturbed-turn.mjs");
  writeFileSync(tmp, src.replace(anchor, "  if (epIp) return epIp;"));
  try {
    listenHostInit = (await import(pathToFileURL(tmp).href)).listenHostInit;
  } finally {
    unlinkSync(tmp);
  }
}

const DEAD = "46.17.99.41";      // what the node's stale local config still reports
const LIVE = "82.24.110.35";     // what the box actually has now
// What ipChoices would build: the reported endpoint first, then the node's own addresses.
const choices = (ep, ips) => [...new Set([ep, ...ips].filter(Boolean))];

console.log("[1] a corroborated endpoint stays the default");
check("the reported endpoint is used when the node reports it too",
      listenHostInit(LIVE, choices(LIVE, [LIVE]), [LIVE]) === LIVE,
      listenHostInit(LIVE, choices(LIVE, [LIVE]), [LIVE]));

console.log("\n[2] an endpoint the box does not have loses its privilege");
const got = listenHostInit(DEAD, choices(DEAD, [LIVE]), [LIVE]);
check("a stale reported endpoint is NOT pre-selected", got !== DEAD, got);
check("…and the address the node actually reports is used instead", got === LIVE, got);

console.log("\n[3] a bridge node still defaults to its public endpoint");
// Its reported addresses are container-private, so the picker filters them out: nothing can corroborate.
check("nothing to corroborate with is not evidence against",
      listenHostInit(LIVE, choices(LIVE, []), ["172.17.0.2"]) === LIVE,
      listenHostInit(LIVE, choices(LIVE, []), ["172.17.0.2"]));

console.log("\n[4] a node that has reported nothing changes nothing");
check("no reported addresses → the endpoint is still offered",
      listenHostInit(DEAD, choices(DEAD, []), []) === DEAD,
      listenHostInit(DEAD, choices(DEAD, []), []));

console.log("\n[5] no endpoint reported → an offered address");
check("the first offered address the node confirms is used",
      listenHostInit("", choices("", [LIVE]), [LIVE]) === LIVE,
      listenHostInit("", choices("", [LIVE]), [LIVE]));

console.log("\n[6] nothing to go on → Custom, not a guess");
check("an empty everything falls back to __custom__",
      listenHostInit("", [], []) === "__custom__", listenHostInit("", [], []));

done(PERTURB, "the reported endpoint is preferred unconditionally again");
