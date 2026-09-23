/* Self-test: the exit-IP map survives the browser's own round trip, so a save cannot silently clear it.
 *
 * THE DEFECT THIS EXISTS FOR, found in code review after it had shipped and been live-qualified: the panel
 * stored `routing_exit_ips` on the interface record and NO record builder published it back. The browser
 * then read `undefined`, `egressInit` produced an empty map, and `egressBody` sent that empty map on the
 * very next save — which the server's "an empty map clears it" contract faithfully applied. The address was
 * write-once-then-lost, the chip vanished from every row on reload, and nothing reported any of it.
 *
 * The server half is gated in tests/settings_node_fields_selftest.py, which now DERIVES the egress ladder's
 * fields instead of listing them. This is the other end: whatever the panel publishes has to come back out
 * of `egressBody` unchanged, because four call sites re-send it for reasons that have nothing to do with
 * routing — a WDTT instance being restarted, renamed or re-ported posts `egressBody(egressInit(cfg))`, and
 * an interface save that only changes the MTU posts the same body.
 *
 * Run: node tests/spa_exitip_selftest.mjs
 *      --perturb  drops the map from `egressInit`, the way it behaved while the field was unpublished, and
 *                 expects the round-trip checks to go red.
 */
import { spa, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const { egressInit, egressBody } = await spa("routing.js");

const MAP = { n2: "198.51.100.7", n3: "203.0.113.9" };
const init = m => { const eg = egressInit(m); if (PERTURB) delete eg.exitIps; return eg; };

console.log("\n[what the panel published comes back out unchanged]");
const eg = init({ egress_mode: "smart", routing: [], routing_exit_ips: MAP });
check("`egressInit` reads the stored map off the record", JSON.stringify(eg.exitIps) === JSON.stringify(MAP), eg.exitIps);
const body = egressBody(eg);
check("…and `egressBody` sends exactly it back", JSON.stringify(body.routing_exit_ips) === JSON.stringify(MAP), body.routing_exit_ips);
check("…as its own key, never inside a rule", !JSON.stringify(body.routing || []).includes("198.51.100.7"), body.routing);

console.log("\n[a save that has nothing to do with routing must not clear it]");
// The WDTT/csqtt restart, rename and re-port paths, and the interface sheet's MTU-only save, all post
// `egressBody(egressInit(<the stored record>))`. Whatever that produces IS the save.
const resent = egressBody(egressInit({ egress_mode: "smart", routing: [], routing_exit_ips: MAP }));
check("restarting or renaming an instance re-sends the addresses it already had",
      JSON.stringify(resent.routing_exit_ips) === JSON.stringify(MAP), resent.routing_exit_ips);
check("…which is NOT the empty map the server reads as 'clear them'",
      Object.keys(resent.routing_exit_ips || {}).length > 0);

console.log("\n[an interface that has none]");
const none = egressBody(egressInit({ egress_mode: "smart", routing: [] }));
check("sends an empty map rather than nothing at all — the operator clearing the last address is a real edit",
      none.routing_exit_ips && Object.keys(none.routing_exit_ips).length === 0, none.routing_exit_ips);

console.log("\n[the draft is a copy, not the stored object]");
const rec = { egress_mode: "smart", routing: [], routing_exit_ips: { n2: "198.51.100.7" } };
const draft = init(rec);
if (draft.exitIps) draft.exitIps.n2 = "203.0.113.1";
check("editing the draft cannot reach back into the record the store holds",
      rec.routing_exit_ips.n2 === "198.51.100.7", rec.routing_exit_ips);

console.log("\n[modes that are not smart send no routing at all]");
const fwd = egressBody({ ...init({ egress_mode: "forward", egress_node: "n2", routing_exit_ips: MAP }), mode: "forward", node: "n2" });
check("a forward interface's body carries no rule list and no address map",
      !("routing" in fwd) && !("routing_exit_ips" in fwd), Object.keys(fwd));

done(PERTURB, "egressInit drops the map");
