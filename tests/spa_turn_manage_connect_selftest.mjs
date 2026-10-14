/* Self-test: a turn proxy's manage sheet reads and writes its "Forwards to" faithfully (the review of 356a08f9, F1/F2).
 *
 * [1] F1 — the sheet matched the proxy's -connect to a local interface by PORT alone, so a custom target that shares a
 *     port ("10.0.0.5:51820") opened as the local wg0, and a Save — a title edit included — rewrote it to 127.0.0.1:51820.
 *     Only a local host (127.0.0.1, localhost, none) is one of the node's interfaces now; the matched interface keeps the
 *     saved spelling ("localhost:51820"), in save() and in the Save-enable check alike, so a title edit stays title-only.
 * [2] F2 — save() looked the chosen interface up with no guard: one that left the node's report while the sheet was
 *     open threw. It says so instead, in both languages.
 *
 * The match rule is exercised as written (lifted from js/turn.js), the rest read from the source.
 * Run: node tests/spa_turn_manage_connect_selftest.mjs
 *      --perturb        the port-only match again → RED in [1]
 *      --perturb-guard  the unguarded lookup again → RED in [2]
 */
import fs from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb"), PERTURB_GUARD = process.argv.includes("--perturb-guard");
let TU = fs.readFileSync(path.join(ROOT, "js", "turn.js"), "utf8");
const RU = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
const MATCH = "  const match = /^(127\\.0\\.0\\.1|localhost)?$/.test(conHost) ? ifaces.find(i => i.port === conPort) : null;";
const GUARD = '      if (!fi) return fail(T("That interface is no longer on this node — pick another."));';
for (const [on, a, b] of [[PERTURB, MATCH, "  const match = ifaces.find(i => i.port === conPort);"], [PERTURB_GUARD, GUARD, ""]]) {
  if (!on) continue;
  if (TU.split(a).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would measure nothing"); process.exit(1); }
  TU = TU.replace(a, b);
}

console.log("[1] the forward target");
const line = TU.split("\n").find(l => /^ {2}const match = /.test(l));
check("[1] the match rule is found in TurnManageSheet", !!line, "");
// lift the rule: (con, ifaces) → the matched interface's name, or null
const rule = new Function("con", "ifaces", `
  const conPort = con.includes(":") ? con.slice(con.lastIndexOf(":") + 1) : con;
  const conHost = con.includes(":") ? con.slice(0, con.lastIndexOf(":")) : "";
  ${line}
  return match ? match.name : null;`);
const IF = [{ name: "wg0", port: "51820" }, { name: "awg0", port: "51821" }];
check("[1] 127.0.0.1:51820 is the local wg0", rule("127.0.0.1:51820", IF) === "wg0", rule("127.0.0.1:51820", IF));
check("[1] localhost:51820 is the local wg0 too", rule("localhost:51820", IF) === "wg0", rule("localhost:51820", IF));
check("[1] 10.0.0.5:51820 — another box's port — is NOT wg0 (it opens as a custom target)", rule("10.0.0.5:51820", IF) === null, rule("10.0.0.5:51820", IF));
check("[1] the matched interface keeps its saved spelling in save() and in the Save-enable check (a title edit stays title-only)",
      TU.includes('connect = (match && fwd === match.name) ? con : "127.0.0.1:" + fi.port;')
      && TU.includes("const _mConnect = isCustom ? custom.trim() : (match && fwd === match.name) ? con"), "");

console.log("\n[2] an interface gone while the sheet is open");
check("[2] save() says so instead of throwing", TU.includes(GUARD), "");
check("[2] …in Russian too", RU.includes('"That interface is no longer on this node — pick another.":'), "");

done(PERTURB || PERTURB_GUARD);
