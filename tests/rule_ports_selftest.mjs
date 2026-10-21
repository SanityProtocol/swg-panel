/* Self-test: ports on a routing rule in the SPA (docs/NEVER-BLOCK-AND-PORT-RULES-PLAN.md B.2, B.6; 1.8.11 S6).
 *
 *  [1] the grammar — `portsClean` answers tests/ports_vectors.json exactly as the panel's `ports_clean` does;
 *  [2] the guarded shape round-trips — rulesToRows reads `ports.on` as the row's switch, rowsToRules writes `enabled` and
 *      `who.on` false with the switch in `ports.on`, and a row without ports writes what it always wrote;
 *  [3] a row is (destination, switch, people, PORTS): a port rule never merges into a port-less neighbour;
 *  [4] the lints follow the node: a duplicate is the same badge with the same ports; a port row never takes a port-less row's
 *      hosts; a port row below a row that takes its badge's hosts on all of its ports first never fires (`dupes`) — B.3's
 *      reorder only for the same category and people, a narrower name on equal ports covering on the name engines, a Hybrid
 *      Block taking no learned address;
 *  [5] the engine matrix on the chip (portsNote, the interface's SMTP/QUIC switches included), the 0.0.0.0/0 Block notice
 *      (per person too), and `routing_v: 3` on every save.
 *
 * Run: node tests/rule_ports_selftest.mjs
 *      --perturb guard   rowsToRules leaves `who.on` live beside ports — expects red in [2]
 *      --perturb lint    the duplicate key ignores ports — expects red in [4]
 *      --perturb cover   a narrower name on equal ports never covers (the node's coverage ignored) — red in [4]
 *      --perturb samecat B.3's reorder assumed for any port-less row of the same badge — red in [4]
 *      --perturb hybrid  a Hybrid Block taken to preempt a port row by name — red in [4]
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, spa, check, done } from "./spa_env.mjs";

const GUARD_AT = "base.enabled = false; if (base.who) base.who.on = false; }", GUARD_TO = "base.enabled = false; }";
const LINT_AT = "const pj = portsOf(row), pk = ptKey(row);", LINT_TO = 'const pj = portsOf(row), pk = "";';
const COVER_AT = "badgeCovers(ub, b) && !(shadowEng && portsCover(pj, pu))", COVER_TO = "badgeCovers(ub, b)";
const SRC_AT = "!(!pu && sameSrc(up, row) && (b.t === \"list\" || typedKey(up) === typedKey(row)))", SRC_TO = "!(!pu)";
const HYB_AT = 'if (mode === "sni" && up.action === "block" && isName(b)) return false;', HYB_TO = "";
const PLANTS = {
  guard: [GUARD_AT, GUARD_TO],
  lint: [LINT_AT, LINT_TO],
  cover: [COVER_AT, COVER_TO],
  samecat: [SRC_AT, SRC_TO],
  hybrid: [HYB_AT, HYB_TO],
};
const PERTURB = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] || "" : "";
const SRC = path.join(ROOT, "js", "rulerows.js");
let mod = SRC;
if (PERTURB) {
  const s = fs.readFileSync(SRC, "utf8");
  const [a, b] = PLANTS[PERTURB] || [null, null];
  if (!a || s.split(a).length !== 2) { console.log("ANCHOR MISSING / unknown perturb: " + PERTURB); process.exit(1); }
  mod = path.join(ROOT, "js", "__perturb_rule_ports.js");
  fs.writeFileSync(mod, s.replace(a, b));
}
let RR;
try { RR = await import(pathToFileURL(mod).href); } finally { if (PERTURB) fs.unlinkSync(mod); }   // never left in the served js/
const { portsClean, rulesToRows, rowsToRules, rowLints } = RR;

console.log("[1] the grammar — tests/ports_vectors.json");
const VEC = JSON.parse(fs.readFileSync(path.join(ROOT, "tests", "ports_vectors.json"), "utf8")).vectors;
const bad = VEC.filter(([p, raw, want]) => JSON.stringify(portsClean(p, raw)) !== JSON.stringify("proto" in want ? { proto: want.proto, list: want.list } : { bad: want.bad }));
check(`portsClean answers every vector (${VEC.length}) as the panel does`, !bad.length, bad.slice(0, 3).map(([p, r]) => [p, r, portsClean(p, r)]));

console.log("\n[2] the guarded shape");
const WHO = { on: true, users: ["u1"], groups: [], peers: [] };
const stored = { enabled: false, category: "custom", action: "exit", node: "n2", domains: [], cidrs: ["203.0.113.0/24"],
                 ports: { on: true, proto: "udp", list: "19302-19309" } };
let { rows } = rulesToRows([stored]);
check("a stored port rule reads as a row that is ON, carrying its ports", rows.length === 1 && rows[0].enabled === true
      && JSON.stringify(rows[0].ports) === JSON.stringify({ proto: "udp", list: "19302-19309" }), rows);
let out = rowsToRules(rows, null);
check("…and writes back the guarded shape: `enabled` false, the switch in `ports.on`", out.length === 1 && out[0].enabled === false
      && JSON.stringify(out[0].ports) === JSON.stringify({ on: true, proto: "udp", list: "19302-19309" }), out);
out = rowsToRules([{ ...rows[0], enabled: false }], null);
check("a row switched off writes `ports.on: false`", out[0].ports.on === false && out[0].enabled === false, out);
({ rows } = rulesToRows([{ ...stored, enabled: false, who: { ...WHO, on: false } }]));
out = rowsToRules(rows, null);
check("with people too: `who.on` is written false (a released panel reads it), the people kept, the switch in `ports.on`",
      out[0].who && out[0].who.on === false && out[0].who.users[0] === "u1" && out[0].ports.on === true && out[0].enabled === false, out);
({ rows } = rulesToRows([{ ...stored, ports: { ...stored.ports, on: false } }]));
check("a stored port rule switched off reads as off", rows[0].enabled === false, rows);
({ rows } = rulesToRows([{ ...stored, ports: { on: true } }]));
out = rowsToRules(rows, null);
check("a stored `ports` that does not read stays a port rule and is written back as stored — never as a rule for every port",
      rows[0].ports && out[0].enabled === false && JSON.stringify(out[0].ports) === JSON.stringify({ on: true }), out);
const plain = { enabled: true, category: "custom", action: "exit", node: "n2", domains: [], cidrs: ["203.0.113.0/24"] };
out = rowsToRules(rulesToRows([plain]).rows, null);
check("a rule without ports writes what it always wrote (no `ports`, `enabled` true)", out.length === 1 && !("ports" in out[0])
      && out[0].enabled === true, out);

console.log("\n[3] a row keeps its ports");
({ rows } = rulesToRows([plain, stored]));
check("a port rule after a port-less rule to the same place is a row of its own", rows.length === 2 && !rows[0].ports && rows[1].ports, rows);
({ rows } = rulesToRows([stored, { ...stored, category: "youtube", domains: undefined, cidrs: undefined }]));
check("…and two rules with the same ports to the same place are one row", rows.length === 1 && rows[0].badges.length === 2, rows);

console.log("\n[4] the lints follow the node");
const r = (targets, action, ports, extra = {}) => ({ enabled: ports ? false : true, category: "custom", targets, action,
  ...(action === "exit" ? { node: "n2" } : {}), ...(ports ? { ports: { on: true, ...ports } } : {}), ...extra });
const dest = x => x.action === "exit" ? "exit|" + (x.node || "") : x.action;
const lint = (rules, mode) => rowLints(rulesToRows(rules).rows, dest, { mode });
const U = { proto: "udp", list: "19302-19309" };
let L = lint([r("google.com", "exit"), r("google.com", "direct", U)]);
check("the same badge, port-less above and with ports below: not a duplicate (one category — the port entry goes first)", L[1].dupes.length === 0, L[1]);
L = lint([r("google.com", "exit", U), r("google.com", "direct", U)]);
check("the same badge with the same ports twice: the second is dead", L[1].dupes.length === 1, L[1]);
L = lint([r("google.com", "exit", U), r("google.com", "direct", { proto: "tcp", list: "443" })]);
check("…with other ports: not", L[1].dupes.length === 0, L[1]);
L = lint([r("google.com", "exit"), r("meet.google.com", "direct", U)]);
check("a port row below a port-less row whose broader name reaches it never fires — listed as a duplicate", L[1].dupes.length === 1, L[1]);
check("…and the row above is not told that the row below takes its hosts", L[0].takenBy.length === 0 && L[0].takenFew.length === 0, L[0]);
L = lint([r("meet.google.com", "direct", U), r("google.com", "exit")]);
check("the port row above the broader row: nothing to say (it takes its ports, the broader row keeps the rest)",
      L[0].dupes.length === 0 && L[1].takenBy.length === 0, L);
L = lint([r("google.com", "exit"), r("meet.google.com", "direct")]);
check("CONTROL — the same rows without ports: the lower row takes the hosts (takenBy), nothing is a duplicate",
      L[0].takenBy.length === 1 && L[1].dupes.length === 0, L);
const KIDS = { on: false, users: ["kids"], groups: [], peers: [] };
L = lint([r("google.com", "exit"), r("google.com", "direct", U, { who: KIDS })]);
check("the same badge, port-less for everyone above, with ports for chosen people below: other people, no reorder — dead",
      L[1].dupes.length === 1, L[1]);
L = lint([r("google.com, youtube.com", "exit"), r("google.com", "direct", U)]);
check("…the same badge in another bundle above (another category, no reorder): dead", L[1].dupes.length === 1, L[1]);
L = lint([r("google.com", "exit", { proto: "udp", list: "" }), r("google.com", "direct", U)]);
check("…every UDP port above, UDP 19302-19309 below (port rules keep their order): dead", L[1].dupes.length === 1, L[1]);
const U3 = { proto: "udp", list: "3478" };
L = lint([r("google.com", "exit", U3), r("mail.google.com", "direct", U3)], "forcedns");
check("Force-DNS: a narrower name on the SAME ports below a broader port row covers it — it fires, and takes those hosts",
      L[1].dupes.length === 0 && L[0].takenBy.length === 1, L);
L = lint([r("google.com", "exit", { proto: "udp", list: "3470-3480" }), r("mail.google.com", "direct", U3)], "forcedns");
check("…on fewer ports than the broader row's it does not: dead (the broader row's shadow takes them)", L[1].dupes.length === 1
      && L[0].takenBy.length === 0, L);
L = lint([r("google.com", "block"), r("meet.google.com", "exit", U3)], "sni");
check("Hybrid SNI: a port row below a broader Block by name fires (a Hybrid Block takes no learned address)", L[1].dupes.length === 0, L[1]);
L = lint([r("google.com", "block"), r("meet.google.com", "exit", U3)], "forcedns");
check("…on Force-DNS it does not (the Block's shadow takes them first)", L[1].dupes.length === 1, L[1]);

console.log("\n[5] the engine matrix, the Block notice, the save");
const R = await spa("routing.js");
const { classify } = await spa("classify.js");
const tgt = raw => ({ t: "target", raw, ...classify(raw) });
const row = (action, b, ports) => ({ enabled: true, action, badges: [tgt(b)], ...(ports ? { ports } : {}) });
const note = (mode, rw) => R.portsNote(mode, rw);
check("Hybrid / Kernel SNI: UDP 443 never reaches a rule (QUIC dropped first) — a warning",
      note("sni", row("exit", "203.0.113.0/24", { proto: "udp", list: "443" })).warn && note("sni_kernel", row("exit", "203.0.113.0/24", { proto: "both", list: "400-500" })).warn);
check("Force-DNS: port 53 — a warning", note("forcedns", row("exit", "203.0.113.0/24", { proto: "udp", list: "53" })).warn);
check("Kernel SNI: a site name off TCP 443 — a warning", note("sni_kernel", row("exit", "example.com", { proto: "tcp", list: "8443" })).warn);
check("Hybrid SNI: a site name off TCP 443 — said, not a warning", note("sni", row("exit", "example.com", { proto: "udp", list: "3478" })).warn === false);
check("IP-only, addresses, TCP 8443: nothing to say", note("kernel", row("exit", "203.0.113.0/24", { proto: "tcp", list: "8443" })) === null
      && note("sni", row("exit", "203.0.113.0/24", { proto: "tcp", list: "8443" })) === null);
check("the chip's text: \"UDP 19302–19309\"", R.portsLabel(U) === "UDP 19302–19309", R.portsLabel(U));
const names = row("direct", "example.com"), allBlk = row("block", "0.0.0.0/0");
check("a Block to 0.0.0.0/0 below a name row on an SNI engine is said", R.allBlockPreemptsNames("sni", [names, allBlk]) === 1);
check("…not when its ports leave out TCP 443, not on IP-only, not when it is above",
      R.allBlockPreemptsNames("sni", [names, { ...allBlk, ports: { proto: "udp", list: "" } }]) === -1
      && R.allBlockPreemptsNames("kernel", [names, allBlk]) === -1 && R.allBlockPreemptsNames("sni_kernel", [allBlk, names]) === -1);
check("Hybrid SNI: a Block by site name off TCP 443 — a warning (it blocks only its addresses there)",
      note("sni", row("block", "example.com", { proto: "udp", list: "3478" })).warn === true);
check("Force-DNS: a Block on UDP 53 — a warning that it drops DNS", (n => n.warn && /DNS/.test(n.text))(note("forcedns", row("block", "0.0.0.0/0", { proto: "udp", list: "53" }))));
check("Kernel SNI: a site name on TCP 443 and 8443 — a warning (8443 by address only)", note("sni_kernel", row("exit", "example.com", { proto: "tcp", list: "443,8443" })).warn === true);
check("Hybrid / Kernel SNI: every UDP port — said, not warned (UDP 443 is only inside it)", note("sni", row("exit", "203.0.113.0/24", { proto: "udp", list: "" })).warn === false);
check("the interface's SMTP switch: TCP 25 named — a warning; every TCP port — said", R.portsNote("kernel", row("exit", "203.0.113.0/24", { proto: "tcp", list: "25" }), ["smtp"]).warn === true
      && R.portsNote("kernel", row("exit", "203.0.113.0/24", { proto: "tcp", list: "" }), ["smtp"]).warn === false
      && note("kernel", row("exit", "203.0.113.0/24", { proto: "tcp", list: "25" })) === null);
check("ports that do not read — a warning, and the chip says so", note("kernel", row("exit", "203.0.113.0/24", {})).warn === true
      && R.portsLabel({}) !== "");
const kidsBlk = { ...allBlk, who: { users: ["kids"], groups: [], peers: [] } };
check("a Block to 0.0.0.0/0 for chosen people below a name row for everyone is said; below a name row for other people it is not",
      R.allBlockPreemptsNames("sni", [names, kidsBlk]) === 1
      && R.allBlockPreemptsNames("sni", [{ ...names, who: { users: ["mum"], groups: [], peers: [] } }, kidsBlk]) === -1);
const body = R.egressBody({ mode: "smart", rows: [], catchAll: null });
check("every smart save says `routing_v: 3`", body.routing_v === 3, body);

done(!!PERTURB, PERTURB);
