/* Self-test: "Load now" under the AmneziaWG version switch (docs/AWG31-LOAD-PLAN.md D5) — the real iface.js.
 *
 * [1] nothing to offer and no press → nothing rendered
 * [2] 3.1 installed but not loaded (awg31_loadable) → a "Load now" button
 * [3] a press the node has not answered → "Loading…", in the not-ready colour, no second button
 * [4] the node's answer: done → its sentence, no button (nothing left to load); failed → its sentence in the failure
 *     colour, and the button again (the node still has 3.1 to load)
 * [5] a result older than an hour is no longer shown
 * [6] the switch carries the line where it knows the node (create form, Edit sheet) — not in Settings' preset
 *
 * Run: node tests/spa_awg_load_selftest.mjs     --perturb pending|age|field   plants one and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  pending: ['  if (pending) return html`<div class="hint warnish">', '  if (false) return html`<div class="hint warnish">'],
  age: ["st.msg && (st.age || 0) < 3600 ? srvText(st.msg)", "st.msg ? srvText(st.msg)"],
  field: ['    ${nrec ? html`<${AwgLoadLine} node=${node} nrec=${nrec}/>` : null}\n', ""],
};
let IF, made = null;
if (MODE) {
  const s = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
  const [a, b] = PLANTS[MODE];
  if (s.split(a).length !== 2) { console.log("ANCHOR MISSING for " + MODE); process.exit(1); }
  made = path.join(ROOT, "js", "__perturb_awgload_iface.js"); fs.writeFileSync(made, s.replace(a, b));
}
try { IF = await import(pathToFileURL(made || path.join(ROOT, "js", "iface.js")).href); }
finally { if (made) { try { fs.unlinkSync(made); } catch (_) { /* gone */ } } }

const texts = n => { const out = []; const walk = x => { if (Array.isArray(x)) x.forEach(walk); else if (typeof x === "string") out.push(x);
  else if (x && typeof x === "object" && x.props) walk(x.props.children); }; walk(n); return out.join(" "); };
const cls = n => (n && n.props && n.props.class) || "";
const hasBtn = n => /Load now/.test(texts(n));
const msg = k => ({ error: k, error_key: k, error_vars: { v1: "msk", v2: "3.1.20260812" } });
const L = nrec => IF.AwgLoadLine({ node: "n1", nrec: { name: "msk", ...nrec } });

console.log("\n[1] nothing to offer"); check("nothing rendered", L({ awg31_loadable: false }) == null);
console.log("\n[2] installed, not loaded");
const l2 = L({ awg31_loadable: true });
check("a Load now button", l2 && hasBtn(l2), texts(l2));
console.log("\n[3] pressed, not answered");
const l3 = L({ awg31_loadable: true, awg_load: { n: 1, age: 4, state: "pending" } });
check("Loading…, in the not-ready colour", /Loading the AmneziaWG module on msk/.test(texts(l3)) && /warnish/.test(cls(l3)), [texts(l3), cls(l3)]);
check("…with no second button", !hasBtn(l3), texts(l3));
console.log("\n[4] the answer");
const l4 = L({ awg31_loadable: false, awg_load: { n: 1, age: 20, state: "done", msg: msg("{v1}: AmneziaWG {v2} is loaded — every AmneziaWG interface is back on the kernel module") } });
check("done → its sentence, no button", /is loaded/.test(texts(l4)) && !hasBtn(l4) && !/err/.test(cls(l4)), [texts(l4), cls(l4)]);
const l4b = L({ awg31_loadable: true, awg_load: { n: 1, age: 20, state: "failed", msg: msg("{v1}: the AmneziaWG module could not be unloaded — every interface was brought back as it was") } });
check("failed → its sentence in the failure colour, and the button again", /could not be unloaded/.test(texts(l4b)) && /err/.test(cls(l4b)) && hasBtn(l4b),
      [texts(l4b), cls(l4b)]);
console.log("\n[5] an old result");
check("an hour on, a done result is gone", L({ awg31_loadable: false, awg_load: { n: 1, age: 4000, state: "done", msg: msg("{v1}: AmneziaWG {v2} is loaded — every AmneziaWG interface is back on the kernel module") } }) == null);
console.log("\n[6] where the switch shows it");
const kids = n => (Array.isArray(n) ? n : [n]).flatMap(x => x && x.props ? [x, ...kids(x.props.children || [])] : []);
const withNode = IF.AwgGenField({ value: "2.0", onChange: () => {}, was: "2.0", node: "n1", nrec: { name: "msk", awg31_loadable: true } });
check("create form / Edit sheet: the line is there", kids(withNode).some(x => x.type === IF.AwgLoadLine || (x.type && x.type.name === "AwgLoadLine")));
const preset = IF.AwgGenField({ value: "2.0", onChange: () => {}, label: "x", hint: "y" });
check("Settings' preset: not there", !kids(preset).some(x => x.type && x.type.name === "AwgLoadLine"));
done(!!MODE, MODE);
