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
 *   [7] V-FEAT-A F4 (the 1.8.9 qualification, fix round 2) — "Listen on" offers the node's own addresses, never its tunnels:
 *       on vf12 as measured it listed 10.66.66.1 · wdtt0, 10.70.0.1 · wdttraw0 (a raw WDTT's second device) and
 *       10.66.67.1 · csqtt0 — a proxy bound there reached no client (0/3) — and on a one-NIC box a WDTT or csqtt server made
 *       the field appear at all
 *
 * Run: node tests/spa_turnlisten_selftest.mjs
 *      --perturb [listen|tun]   one fix undone — expects RED in [2] / [7] (exit 0 when caught)
 */
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? (process.argv[process.argv.indexOf("--perturb") + 1] || "listen") : null;
const PLANTS = {   // name → [anchor in js/turn.js, what it was before the fix]
  listen: ["  if (epIp && (have.includes(epIp) || !own.length)) return epIp;", "  if (epIp) return epIp;"],
  tun: ["  const v4 = (nrec.ips || []).filter(ip => _v4(ip) && !tun(nicOf(ip)));", "  const v4 = (nrec.ips || []).filter(_v4);"],
};
if (MODE && !PLANTS[MODE]) { console.log("unknown perturbation " + MODE); process.exit(2); }

const { Store } = await spa("store.js");
let TU = await spa("turn.js");
const TURN = readFileSync(path.join(ROOT, "js", "turn.js"), "utf8");
if (MODE) {
  const [anchor, was] = PLANTS[MODE];
  // ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
  if (TURN.split(anchor).length - 1 !== 1) {
    console.log("PERTURB ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS: " + MODE);
    process.exit(1);
  }
  // Written BESIDE the real module so its own relative imports resolve exactly as they do in the browser.
  const tmp = path.join(ROOT, "js", ".perturbed-turn.mjs");
  writeFileSync(tmp, TURN.replace(anchor, was));
  try {
    TU = await import(pathToFileURL(tmp).href);
  } finally {
    unlinkSync(tmp);
  }
}
const listenHostInit = TU.listenHostInit;

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
// Its reported addresses are container-private, so the picker filters them out: nothing can corroborate. The form
// says it is a bridge node (the 4th argument) — without that, "no public IPv4 of its own" reads as a box behind NAT,
// which starts on All addresses (tests/turn_dial_host_selftest.mjs [5]).
check("nothing to corroborate with is not evidence against",
      listenHostInit(LIVE, choices(LIVE, []), ["172.17.0.2"], true) === LIVE,
      listenHostInit(LIVE, choices(LIVE, []), ["172.17.0.2"], true));

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

// ── [7] "Listen on" ───────────────────────────────────────────────────────────────────────────────────────────────────────
const nic = (ip, iface) => ({ ip, iface });
Store.nodes = [
  // vf12 as measured (q189 V-FEAT-A, t10-liston-options): two NICs, a raw WDTT server (wdtt0 + wdttraw0), a csqtt server
  { id: "vf12", kind: "bare", turn_bind_any: true, ips: ["10.0.2.15", "192.168.77.12", "192.168.77.212", "10.66.66.1", "10.70.0.1", "10.66.67.1"],
    ip_ifaces: [nic("10.0.2.15", "ens3"), nic("192.168.77.12", "ens4"), nic("192.168.77.212", "ens4"), nic("10.66.66.1", "wdtt0"),
                nic("10.70.0.1", "wdttraw0"), nic("10.66.67.1", "csqtt0")] },
  // one NIC, a WDTT and a csqtt server, and a WireGuard interface of its own under a name the node's report does not skip
  { id: "one", kind: "bare", turn_bind_any: true, ips: ["203.0.113.7", "10.66.66.1", "10.66.67.1", "10.8.0.1"],
    ip_ifaces: [nic("203.0.113.7", "eth0"), nic("10.66.66.1", "wdtt0"), nic("10.66.67.1", "csqtt0"), nic("10.8.0.1", "home0")] },
  { id: "two", kind: "bare", turn_bind_any: true, ips: ["203.0.113.8", "192.168.1.8"], ip_ifaces: [nic("203.0.113.8", "eth0"), nic("192.168.1.8", "eth1")] },
];
Store.stats = { vf12: { wdtt: [{ iface: "wdtt0", raw_iface: "wdttraw0" }], csqtt: [{ iface: "csqtt0" }] },
                one: { wdtt: [{ iface: "wdtt0" }], csqtt: [{ iface: "csqtt0" }] } };
Store.describe = { one: { home0: {} } };
const find = (x, f) => !x || typeof x !== "object" ? null : f(x) ? x
  : [].concat(x.props ? x.props.children : []).reduce((a, c) => a || find(c, f), null);
const listenOpts = node => { const v = TU.ListenOnField({ node, value: "", onChange: () => {} });
  const dd = find(v, x => x.props && Array.isArray(x.props.options)); return v ? (dd ? dd.props.options.map(o => o.value) : "no list") : null; };

console.log("\n[7] \"Listen on\" offers the node's own addresses, never its tunnels (V-FEAT-A F4)");
check("[7] vf12: Auto and its three NIC addresses — no wdtt0, wdttraw0 or csqtt0 (before: all six)",
      JSON.stringify(listenOpts("vf12")) === JSON.stringify(["", "10.0.2.15", "192.168.77.12", "192.168.77.212"]), listenOpts("vf12"));
check("[7] a one-NIC box with a WDTT and a csqtt server and a WireGuard interface of its own: no field at all (before: shown)",
      listenOpts("one") === null, listenOpts("one"));
check("[7] the control: two cards, both offered", JSON.stringify(listenOpts("two")) === JSON.stringify(["", "203.0.113.8", "192.168.1.8"]), listenOpts("two"));

done(MODE, MODE || "");
