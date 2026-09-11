/* Self-test: recreating a LOST interface must offer what it WAS, not what a new one would be.
 *
 * A "warm ghost" is an interface the node no longer reports but the panel still holds `_lastcfg` for —
 * subnet, listen port, MTU and, decisively, its AmneziaWG parameters. `ghostIface` rebuilt that record from
 * a key list naming only `subnet`, so everything else was dropped before the recreate sheet ever saw it, and
 * the sheet fell back to INFERRING the protocol from a peer's target type. An interface with no peers has
 * nothing to infer from, so the default won.
 *
 * MEASURED on hel-fresh, straight after a vault reset made its two keys unrecoverable: `awg0` was AmneziaWG
 * on port 443 with nine obfuscation parameters, and the recreate sheet offered **WireGuard on 51821** with
 * the protocol chip showing WireGuard [SELECTED]. Both fields look perfectly plausible, which is the whole
 * problem — an operator clicking through gets a different kind of interface on a different port and is told
 * only that clients must re-import.
 *
 * ⚠️ TWO READERS, ONE FACT. `iface.js` already answers the same question correctly for the interface BADGE:
 * `(meta && meta.awg_params) || (missIf && missIf.awg_params)`. It had the rule; `ghostIface` threw the data
 * away before the other reader could apply it.
 *
 * The COLD path — a ghost with no saved config at all — must keep inferring, because there is genuinely
 * nothing else. That is asserted here too, or the fix would just move the bug.
 *
 * Run: node tests/spa_recreate_prefill_selftest.mjs   --perturb  drops the carried fields and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC = path.join(ROOT, "js", "model.js");
let mod = SRC;
if (PERTURB) {
  let s = fs.readFileSync(SRC, "utf8");
  // ⚠️ THE WHOLE LITERAL, not its first line. Typed by hand this anchor silently stopped matching the
  // day the record grew two more fields — and a perturbation that matches nothing leaves a clean PASS.
  const a = "subnet: mi.subnet || null, listen_port: mi.listen_port || 0,\n                                     mtu: mi.mtu || 0, awg_params: mi.awg_params || null,\n                                     // ⚠️ PASSED THROUGH, NOT DEFAULTED. `dns: []` and `keepalive: 0` are\n                                     // both things an operator can mean; `|| 0` / `|| null` would erase the\n                                     // difference between \"off\" and \"never set\" before the sheet sees it.\n                                     endpoint_host: mi.endpoint_host || \"\",\n                                     dns: Array.isArray(mi.dns) ? mi.dns : null,\n                                     keepalive: typeof mi.keepalive === \"number\" ? mi.keepalive : null };";
  if (!s.includes(a)) { console.log("ANCHOR MISSING"); process.exit(1); }
  s = s.replace(a, "subnet: mi.subnet || null };");
  mod = path.join(ROOT, "js", "__perturb_model.js");
  fs.writeFileSync(mod, s);
}
const { ghostIface } = await import(pathToFileURL(mod).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
if (PERTURB) fs.unlinkSync(mod);

// hel-fresh as the panel actually held it: the record is there, the KEY is not (vault reset).
const AWG = { Jc: 7, Jmin: 50, Jmax: 1000, S1: 68, S2: 149, H1: "100000-200000", H2: "1", H3: "2", H4: "3" };
Store.nodes = [{
  id: "n1", name: "hel-fresh", ips: ["89.167.2.2"],
  ghost_ifaces: { dead0: { ripe: true, problemMs: 999999 } },          // COLD: no saved config at all
  missing_ifaces: {
    awg0: { ripe: true, problemMs: 999999, key_source: "", subnet: "10.10.1.0/24",
            listen_port: 443, mtu: 1420, awg_params: AWG,
            // the panel-owned settings the sheet would otherwise post a fleet default for
            endpoint_host: "hel.sanitygate.net", dns: ["9.9.9.9", "149.112.112.112"], keepalive: 15 },
    wg9:  { ripe: true, problemMs: 999999, key_source: "", subnet: "10.15.0.0/24",
            listen_port: 51821, mtu: 1280 },
  },
}];

console.log("\n[1] a warm ghost carries the config the panel saved for it");
const g = ghostIface("n1", "awg0") || {};
check("it is recognised as recoverable-by-recreate", g.cold === false, JSON.stringify(g));
check("the subnet survives (it always did)", g.subnet === "10.10.1.0/24", g.subnet);
check("⚠️ the LISTEN PORT survives", g.listen_port === 443, g.listen_port);
check("⚠️ the MTU survives", g.mtu === 1420, g.mtu);
check("⚠️ the AmneziaWG parameters survive — all nine", g.awg_params && Object.keys(g.awg_params).length === 9,
      g.awg_params && Object.keys(g.awg_params).length);
// ⚠️ AND THE PANEL-OWNED SETTINGS. Anything the sheet is not seeded with, it posts the fleet default for —
// measured against the real create endpoint, a recreate turned a hostname endpoint into a raw IP and reset
// the resolvers and keepalive. tests/recreate_keeps_settings_selftest.py drives that seam end to end.
check("⚠️ the published ENDPOINT survives", g.endpoint_host === "hel.sanitygate.net", g.endpoint_host);
check("⚠️ the resolvers survive", (g.dns || []).join(",") === "9.9.9.9,149.112.112.112", g.dns);
check("⚠️ the keepalive survives", g.keepalive === 15, g.keepalive);

console.log("\n[2] …so the protocol is READ, not guessed from peers it may not have");
// This is the exact shape that failed: an AmneziaWG interface with ZERO peers.
const protoOf = gg => (gg.awg_params && Object.keys(gg.awg_params).length) ? "awg" : "wg";
check("an AWG interface with no peers still reads as AmneziaWG", protoOf(g) === "awg", protoOf(g));
const w = ghostIface("n1", "wg9") || {};
check("…and a WireGuard one still reads as WireGuard", protoOf(w) === "wg", protoOf(w));
check("…keeping its own port too", w.listen_port === 51821, w.listen_port);

console.log("\n[3] the COLD path keeps inferring — there is nothing else to read");
const c = ghostIface("n1", "dead0") || {};
check("a ghost with no saved config is still cold", c.cold === true, JSON.stringify(c));
check("…and carries no port to pre-fill from", !c.listen_port, c.listen_port);

console.log("\n[4] ⚠️ THE SEAM — the panel must actually EMIT every key read above");
// ⚠️ THIS SECTION EXISTS BECAUSE THE FIXTURE ABOVE LIED. Written by hand it carried an `mtu`, and section
// [1] went green on it — but `_missing_ifaces` in swg-panel-server has never emitted one, so `g.mtu` was
// `undefined` on every real panel and the sheet fell back to the panel-wide default. Both ends read green
// while the wire between them carried nothing. So the fixture's keys are checked against the panel's own
// record literal rather than against what this file happens to have typed.
const srvSrc = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
const emit = srvSrc.match(/out\[ifn\] = \{([\s\S]*?)\n {8}if key_src == "vault"/);
check("the panel's missing_ifaces record literal was found", !!emit,
      "…so this whole section would have measured nothing");
const emitted = new Set([...(emit ? emit[1] : "").matchAll(/"([a-z_]+)":/g)].map(m => m[1]));
// every key the SPA reads off a missing_ifaces entry, taken from the readers themselves
const READ = ["subnet", "listen_port", "mtu", "awg_params", "key_source",
              "endpoint_host", "dns", "keepalive"];
for (const k of READ)
  check(`the panel emits \`${k}\`, which the browser reads`, emitted.has(k),
        "emitted: " + [...emitted].sort().join(", "));
// …and the fixture must not invent a key the panel does not send, or [1] goes green on nothing again.
const fixtureKeys = ["ripe", "problemMs"];   // injected client-side by store.js, never by the server
const invented = Object.keys(Store.nodes[0].missing_ifaces.awg0)
  .filter(k => !emitted.has(k) && !fixtureKeys.includes(k));
check("the fixture invents no field the panel never sends", invented.length === 0, invented.join(", "));

console.log("\n[5] the sheet actually honours what it is handed");
const ifaceSrc = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
const paSrc = fs.readFileSync(path.join(ROOT, "js", "peer-actions.js"), "utf8");
check("the recreate flow passes the port and MTU on", /port: g\.listen_port \|\| 0, mtu: g\.mtu \|\| 0/.test(paSrc));
check("…and sets the protocol from the saved parameters", /if \(g\.awg_params && Object\.keys\(g\.awg_params\)\.length\) proto = "awg";/.test(paSrc));
check("the port field prefers pre over a suggestion", /useState\(String\(\(pre && pre\.port\) \|\|/.test(ifaceSrc));
check("the MTU field prefers pre over the panel default", /useState\(String\(\(pre && pre\.mtu\) \|\| _idf\.mtu/.test(ifaceSrc));

console.log("\n[6] the notice must say where the pre-filled values CAME from");
// ⚠️ FOUND IN A BROWSER, NOT BY A GATE. The sheet said "Review the settings below (inferred from the peers)"
// — true while it guessed the protocol from a target type and the port from a suggestion, and false the
// moment a warm ghost began reading its own saved config. That parenthetical sits on the one screen that
// asks the operator to review those values, so it told them to distrust the only trustworthy thing there.
// And with nothing deployed, "every client must re-import" instructs an empty set.
check("the recreate carries whether the panel HAS a saved config", /warm: g\.cold === false/.test(paSrc));
check("a warm ghost is told the values are its last saved config",
      /ghost\.warm[\s\S]{0,400}last saved config\*/.test(ifaceSrc));
check("…and a warm ghost with NO peers is not told clients must re-import",
      /ghost\.warm && !ghost\.total[\s\S]{0,300}no client is affected/.test(ifaceSrc));
check("…while the COLD path still says the values were inferred, because they were",
      /inferred from the peers/.test(ifaceSrc));
// the empty-state sentence must not carry a count at all — nothing to count, and nothing to pluralise
const zero = (ifaceSrc.match(/Nothing is deployed on it[^"]*/) || [""])[0];
check("the empty-state sentence carries no {count} to decline", zero && !zero.includes("{count}"), zero.slice(0, 60));
const ru = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
for (const en of ["Nothing is deployed on it, so no client is affected.",
                  "The settings below are its *last saved config* — review them and recreate."])
  check(`"${en.slice(0, 34)}…" is translated`, ru.includes(en), "missing from ru.js");

done(PERTURB, "ghostIface stops carrying the saved config");
