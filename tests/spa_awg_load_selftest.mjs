/* Self-test: "Load now" under the AmneziaWG version switch (docs/AWG31-LOAD-PLAN.md D5) — the real iface.js.
 *
 * [1] nothing to offer and no press → nothing rendered
 * [2] 3.1 installed but not loaded (awg31_loadable) → a "Load now" button
 * [3] a press the node has not answered → "Loading…", in the not-ready colour, no second button
 * [4] the node's answer: done → its sentence, no button (nothing left to load); failed → its sentence in the failure
 *     colour, and the button again (the node still has 3.1 to load)
 * [5] a result older than an hour is no longer shown
 * [6] the switch carries the line where it knows the node (create form, Edit sheet) — not in Settings' preset
 * [7] the button's confirm promises the next reboot only if the kernel accepts it, and says the node page tells why when it
 *     does not — FP-3's words for the two sibling sentences (1.8.9 qualification W5: Secure Boot without the enrolled key, a
 *     build for another kernel) — in English and in its Russian line
 *
 * Run: node tests/spa_awg_load_selftest.mjs     --perturb pending|age|field|promise   plants one and expects RED.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, spa, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  pending: ['  if (pending) return html`<div class="hint warnish">', '  if (false) return html`<div class="hint warnish">'],
  age: ["st.msg && (st.age || 0) < 3600 ? srvText(st.msg)", "st.msg ? srvText(st.msg)"],
  field: ['    ${nrec ? html`<${AwgLoadLine} node=${node} nrec=${nrec}/>` : null}\n', ""],
  promise: ['Or leave it: the module loads at the next reboot if the kernel accepts it; the node page says why when it does not.", { name })',
            'Or leave it: the module loads at the next reboot.", { name })'],   // W5: the unconditional promise back
};
let IF, made = null;
if (MODE) {
  const s = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
  const [a, b] = PLANTS[MODE];
  if (s.split(a).length !== 2) { console.log("ANCHOR MISSING for " + MODE); process.exit(1); }
  // ⚠️ IN A DIRECTORY OF ITS OWN, its siblings by absolute URL (the very modules the real iface.js imports, ui.js's modal stack
  // included): written into js/, the planted copy was a file a gate copying the tree meanwhile could list, one `git add -A`
  // from shipping (1.8.9 qualification GATES-14).
  made = fs.mkdtempSync(path.join(os.tmpdir(), "awgload-"));
  const JS_URL = pathToFileURL(path.join(ROOT, "js") + path.sep).href;
  fs.writeFileSync(path.join(made, "iface.mjs"), s.replace(a, b).replace(/(\bfrom\s*)(["'])\.\//g, (m, f, q) => f + q + JS_URL));
}
try { IF = await import(pathToFileURL(made ? path.join(made, "iface.mjs") : path.join(ROOT, "js", "iface.js")).href); }
finally { if (made) fs.rmSync(made, { recursive: true, force: true }); }

const texts = n => { const out = []; const walk = x => { if (Array.isArray(x)) x.forEach(walk); else if (typeof x === "string") out.push(x);
  else if (x && typeof x === "object" && x.props) walk(x.props.children); }; walk(n); return out.join(" "); };
const cls = n => { const out = []; const walk = x => { if (Array.isArray(x)) x.forEach(walk); else if (x && typeof x === "object" && x.props) {
  if (x.props.class) out.push(x.props.class); walk(x.props.children); } }; walk(n); return out.join(" "); };   // every class in the tree
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
const l4c = L({ awg31_loadable: false, awg_load: { n: 1, age: 20, state: "partial", msg: msg("{v1}: AmneziaWG {v2} is loaded, but not every interface came back on it — on the userspace fallback: {v3}; down: {v4}") } });
check("partial (loaded, not every interface back) → in the failure colour, not as a success", /err/.test(cls(l4c)), [texts(l4c), cls(l4c)]);
console.log("\n[5] an old result");
check("an hour on, a done result is gone", L({ awg31_loadable: false, awg_load: { n: 1, age: 4000, state: "done", msg: msg("{v1}: AmneziaWG {v2} is loaded — every AmneziaWG interface is back on the kernel module") } }) == null);
console.log("\n[6] where the switch shows it");
const kids = n => (Array.isArray(n) ? n : [n]).flatMap(x => x && x.props ? [x, ...kids(x.props.children || [])] : []);
const withNode = IF.AwgGenField({ value: "2.0", onChange: () => {}, was: "2.0", node: "n1", nrec: { name: "msk", awg31_loadable: true } });
check("create form / Edit sheet: the line is there", kids(withNode).some(x => x.type === IF.AwgLoadLine || (x.type && x.type.name === "AwgLoadLine")));
const preset = IF.AwgGenField({ value: "2.0", onChange: () => {}, label: "x", hint: "y" });
check("Settings' preset: not there", !kids(preset).some(x => x.type && x.type.name === "AwgLoadLine"));
console.log("\n[7] the confirm (1.8.9 qualification W5)");
// The button pressed, and the confirm it opens read off the real modal stack (ui.js); an untranslated T() returns its key, so the
// name "{name}" gives the confirm's own catalog key, and js/lang/ru.js its Russian line.
const UI = await spa("ui.js");
const RU = (await spa("lang/ru.js")).STR;
let top = null;
UI.setModalRenderer(st => { top = st[st.length - 1] || null; });
const btnOf = n => { let b = null; const walk = x => { if (b) return; if (Array.isArray(x)) x.forEach(walk);
  else if (x && typeof x === "object" && x.props) { if (x.type === "button" && x.props.onClick) b = x; else walk(x.props.children); } };
  walk(n); return b; };
const confirmOf = name => { UI.clearModalStack(); top = null; const b = btnOf(L({ name, awg31_loadable: true }));
  if (b) b.props.onClick(); return (top && top.props) || {}; };
const c7 = confirmOf("msk");
check("Load now opens its confirm", c7.title === "Load AmneziaWG 3.1 · msk" && typeof c7.body === "string", c7.title);
check("…which promises the next reboot only if the kernel accepts it, and says the node page tells why when it does not (FP-3's words)",
      typeof c7.body === "string" && c7.body.endsWith("Or leave it: the module loads at the next reboot if the kernel accepts it; the node page says why when it does not."),
      c7.body);
const k7 = confirmOf("{name}").body || "";
check("…and its Russian line says the same", /модуль загрузится при следующей перезагрузке, если ядро его примет; если не примет, страница ноды скажет почему\.$/
      .test(RU[k7] || ""), RU[k7] || "no Russian line for: " + k7);
done(!!MODE, MODE);
