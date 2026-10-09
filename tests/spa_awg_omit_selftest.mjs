/* Self-test: an AmneziaWG field set to none ("-") in the SPA (docs/AWG-OMIT-AND-MESH-GEN-PLAN.md A7).
 *
 * [1] the rules an operator meets while typing (awgOmitIssue, awgW1) — the panel's own sentences checked again on save:
 *     Jc/Jmin/Jmax all "-" or none of them; a template with every 2.0 field "-"; ContentPaddingAddition "-" while
 *     RandomTrailers is on. A value, a blank and "-" in other cells are no issue.
 * [2] AwgGrid (Settings' templates): a "-" cell is an input with the `awg-none` class and a value cell has none; the line under
 *     a template grid is its `omit` hint until a rule is broken, then the rule; read-only "-" reads "none"; a grid with no
 *     `omit` (no template) draws no line.
 * [3] Awg3Grid: a "-" cell is `awg-none`; the W1 warning shows only while RandomTrailers reads on.
 * [4] q189 SPA-3, the root: the panel judges a save's "-" rules and the sheet reports its refusal (sheetSend; the browser half is
 *     tests/spa_sheet_refusal_selftest.py) — the round-1 copies of those rules in the SPA (awgSaveRule, meshSNone) are gone, and
 *     neither sheet's Save waits on a copied rule.
 *
 * The browser half (the Edit sheet and the interface page fed by a real panel's /api/state, the removal confirm) was checked
 * against a running panel — .campaign/rigs/omit-ui-rig.py; logic only here.
 *
 * Run: node tests/spa_awg_omit_selftest.mjs     --perturb trio   plants a trio rule that never fires and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = { trio: ["iface.js", "  if (n && n < 3) return T(", "  if (false) return T("] };
const made = [];
async function load(name) {
  if (!MODE || PLANTS[MODE][0] !== name) return import(pathToFileURL(path.join(ROOT, "js", name)).href);
  const [, old, nu] = PLANTS[MODE];
  const src = fs.readFileSync(path.join(ROOT, "js", name), "utf8");
  if (src.split(old).length !== 2) throw new Error("plant anchor did not match exactly once — this run would measure nothing");
  const p = path.join(ROOT, "js", "__perturbed_" + name); fs.writeFileSync(p, src.replace(old, nu)); made.push(p);
  return import(pathToFileURL(p).href);
}
let IF, SS;
try { IF = await load("iface.js"); SS = await import(pathToFileURL(path.join(ROOT, "js", "screen-settings.js")).href); }
finally { for (const p of made) fs.rmSync(p, { force: true }); }

const walk = (n, pick) => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
  else if (x && typeof x === "object" && x.props) { const r = pick(x); if (r !== undefined) out.push(r); w(x.props.children); } }; w(n); return out; };
const inputs = n => walk(n, x => x.type === "input" ? x.props : undefined);
const hints = n => walk(n, x => x.type === "p" && String(x.props.class || "").includes("awg-omit-hint") ? x.props : undefined);
const text = p => [].concat(p.children).filter(c => typeof c === "string").join("");

// [1]
check("[1] Jc alone \"-\": the trio rule", /Jc, Jmin and Jmax/.test(IF.awgOmitIssue({ Jc: "-", Jmin: "40", Jmax: "" })));
check("[1] all three \"-\": no issue", IF.awgOmitIssue({ Jc: "-", Jmin: " - ", Jmax: "-" }) === "");
check("[1] values, blanks and other \"-\" cells: no issue", IF.awgOmitIssue({ Jc: "4", S3: "-", I1: "", H1: "1-2" }) === "");
const allNone = Object.fromEntries(["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"].map(k => [k, "-"]));
check("[1] a template with every field \"-\": refused there", /leave at least one/.test(IF.awgOmitIssue(allNone, true)));
check("[1] …and on an interface that is the trio-free R1 the panel words (no template rule here)", IF.awgOmitIssue(allNone, false) === "");
check("[1] W1 only with RandomTrailers on", IF.awgW1({ ContentPaddingAddition: "-" }, true) !== "" && IF.awgW1({ ContentPaddingAddition: "-" }, false) === ""
      && IF.awgW1({ ContentPaddingAddition: "10-100" }, true) === "");

// [2]
const g = SS.AwgGrid({ value: { S3: "-", S1: "20" }, onChange: () => {}, omit: "OMIT-HINT" });

const ins = inputs(g);
check("[2] sixteen cells", ins.length === 16, ins.length);
check("[2] the \"-\" cell (S3) is awg-none, the value cell (S1) and a blank one are not",
      ins[5].class === "awg-none" && !ins[3].class && !ins[0].class, ins.slice(0, 7).map(p => p.class));
check("[2] the line under a template is its omit hint", hints(g).length === 1 && text(hints(g)[0]) === "OMIT-HINT", hints(g).map(text));
const gbad = SS.AwgGrid({ value: { Jc: "-" }, onChange: () => {}, omit: "OMIT-HINT" });
check("[2] …until a rule is broken: then the rule, marked as an error", hints(gbad).length === 1 && /Jc, Jmin and Jmax/.test(text(hints(gbad)[0]))
      && String(hints(gbad)[0].class).includes("err"));
check("[2] a grid with no omit draws no line", hints(SS.AwgGrid({ value: { S3: "-" }, onChange: () => {} })).length === 0);
const ro = SS.AwgGrid({ value: { S3: "-", S1: "20" }, readOnly: true });
const roVals = walk(ro, x => x.type === "span" && String(x.props.class || "").startsWith("awg-val") ? x.props : undefined);
check("[2] read-only: \"-\" reads none, in the none style", roVals.some(p => String(p.class).includes("awg-none") && text(p) === "none"),
      roVals.map(p => [p.class, text(p)]));

// [3]
const a3 = IF.Awg3Grid({ value: { ContentPaddingAddition: "-" }, onKey: () => {}, hpk: "set", rt: "on" });
const a3off = IF.Awg3Grid({ value: { ContentPaddingAddition: "-" }, onKey: () => {}, hpk: "set", rt: "—" });
check("[3] the \"-\" cell is awg-none", inputs(a3).some(p => p.class === "awg-none"));
check("[3] W1 under the 3.1 cells while RandomTrailers is on, not when it reads —",
      hints(a3).length === 1 && /RandomTrailers/.test(text(hints(a3)[0])) && hints(a3off).length === 0);

// [4] q189 SPA-3, the root
console.log("\n[4] the panel judges, the sheet reports — no copy of the panel's rules");
const isrc = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
check("[4] iface.js exports no copy of the panel's save rules (awgSaveRule, meshSNone)", !("awgSaveRule" in IF) && !("meshSNone" in IF) && !/awgSaveRule|meshSNone/.test(isrc));
check("[4] the Edit sheet's Save waits on the disguise check and the node's capability only (mimErr), not on a copied rule",
      isrc.includes("const mimErr = mimBad ? mimicWhy(mimBad[0], mimBad[1]) : omitNo;") && !/omitRule|awgRule/.test(isrc));
check("[4] both sheets send through sheetSend, so the panel's refusal is said in them",
      isrc.includes("sheetSend(() => api.ifaceUpdate(body)") && isrc.includes("sheetSend(() => api.connectionUpdate({"));

done(MODE, MODE ? "the trio rule" : "");
