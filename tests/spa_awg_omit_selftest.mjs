/* Self-test: an AmneziaWG field set to none ("-") in the SPA (docs/AWG-OMIT-AND-MESH-GEN-PLAN.md A7).
 *
 * [1] the rules an operator meets while typing (awgOmitIssue, awgW1) — the panel's own sentences checked again on save:
 *     Jc/Jmin/Jmax all "-" or none of them; a template with every 2.0 field "-"; ContentPaddingAddition "-" while
 *     RandomTrailers is on. A value, a blank and "-" in other cells are no issue.
 * [2] AwgGrid (Settings' templates): a "-" cell is an input with the `awg-none` class and a value cell has none; the line under
 *     a template grid is its `omit` hint until a rule is broken, then the rule; read-only "-" reads "none"; a grid with no
 *     `omit` (no template) draws no line.
 * [3] Awg3Grid: a "-" cell is `awg-none`; the W1 warning shows only while RandomTrailers reads on.
 * [4] q189 SPA-3 — Save waits for what the panel would refuse: awgSaveRule (the Edit sheet: the panel's awg_rules R1, R3–R5 on
 *     the set the save leaves) and meshSNone (the mesh-link sheet: mesh_omit_s_refusal over the panel's template layering) give
 *     the SAME sentence as the panel's own functions, run in python on the same corpus — and both sheets' Save is held on them
 *     (the sheet closed on the refusal before, and every other edit in it went with it).
 *
 * The browser half (the Edit sheet and the interface page fed by a real panel's /api/state, the removal confirm) was checked
 * against a running panel — .campaign/rigs/omit-ui-rig.py; logic only here.
 *
 * Run: node tests/spa_awg_omit_selftest.mjs     --perturb trio   plants a trio rule that never fires and expects RED.
 *      --perturb saverule | linkrule   a sheet's Save no longer waits on the rule → RED in [4]
 *      --perturb rules | layer         awgSaveRule drops R4 / meshSNone ignores the fleet's template → RED in [4] (parity)
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = { trio: ["iface.js", "  if (n && n < 3) return T(", "  if (false) return T("],
  saverule: ["iface.js", "  const mimErr = mimBad ? mimicWhy(mimBad[0], mimBad[1]) : omitNo || omitRule;", "  const mimErr = mimBad ? mimicWhy(mimBad[0], mimBad[1]) : omitNo;"],
  linkrule: ["iface.js", "disabled: nodeDown || !connDirty || !!quotaErr || !!awgRule,", "disabled: nodeDown || !connDirty || !!quotaErr,"],
  rules: ["iface.js", '  if ("HeaderProtectionKey" in set && !S.every(k => k in set))', '  if (false)'],
  layer: ["iface.js", " || (awgIsNone(fleet[k]) && !String(o[k] ?? \"\").trim())", ""] };
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

// [4] q189 SPA-3
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
Store.nodes = Store.fleet = [{ id: "na", name: "alpha" }, { id: "nb", name: "beta" }];   // nodeName reads the fleet projection
const B = { Jc: "4", Jmin: "40", Jmax: "70", S1: "28", S2: "94", S3: "88", S4: "33", H1: "1", H2: "2", H3: "3", H4: "4" };
const B31 = { ...B, HeaderProtectionKey: "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0=", RandomTrailers: "1", ContentPaddingAddition: "10-100" };
const none = ks => Object.fromEntries(ks.map(k => [k, "-"]));
const EDIT = [   // [cells typed, the record, gen3] — the panel stores {**record, **typed} minus the "-" keys, then awg_rules
  [{ Jc: "-" }, B, false], [none(["Jc", "Jmin", "Jmax"]), B, false], [{ Jc: "-", Jmin: "" }, B, false],
  [none(Object.keys(B)), B, false], [{ ...none(Object.keys(B)), I1: "<b 0x01>" }, B, false],
  [{ S3: "-" }, B31, true], [{ S3: "-" }, B31, false], [{ HeaderProtectionKey: "-", S3: "-" }, B31, true],
  [{ S1: "28", S2: "84", I5: "-" }, B, false], [{ S1: "", S2: "84", H1: "-" }, B, false], [{ Jc: "-", Jmin: "-", Jmax: "-", S4: "-" }, B31, true],
];
const LINK = [   // [the link's own template, the fleet's, the link type in force]
  [{ S2: "-" }, {}, "3.1"], [{ S2: "-" }, {}, "2.0"], [{}, { S3: "-" }, "3.1"], [{ S3: "5" }, { S3: "-" }, "3.1"],
  [{ S3: "" }, { S3: "-", S1: "-" }, "3.1"], [{ Jc: "5" }, { S4: "-" }, "3.1"], [{ S1: "-", S4: "-" }, { S2: "-" }, "3.1"],
];
const PY = `
import json, sys, types
src = open(sys.argv[1], encoding="utf-8").read()
m = types.ModuleType("p"); m.__file__ = sys.argv[1]
exec(compile(src, sys.argv[1], "exec"), m.__dict__)
data = json.loads(sys.argv[2])
out = {"edit": [], "link": []}
for cells, rec, gen3 in data["edit"]:
    om = {k for k, v in cells.items() if str(v).strip() == "-"}
    d = {**{k: v for k, v in rec.items()}, **{k: v for k, v in cells.items() if str(v).strip() and k not in om}}
    d = {k: v for k, v in d.items() if k not in om and (gen3 or k not in m.AWG3_FIELDS)}
    r = m.awg_rules(d, "awg9", gen3=None)
    out["edit"].append(r["error"] if r else "")
for own, fleet, gen in data["link"]:
    om = m.mesh_template({"panel_settings": {"mesh_awg": fleet}}, {"mesh_awg": own})[1]
    r = m.mesh_omit_s_refusal(gen, om, m.mesh_pair_name({"na": {"name": "alpha"}, "nb": {"name": "beta"}}, "nb", "na"))
    out["link"].append(r["error"] if r else "")
print(json.dumps(out))`;
const py = spawnSync("python3", ["-c", PY, path.join(ROOT, "swg-panel-server"), JSON.stringify({ edit: EDIT, link: LINK })], { encoding: "utf8" });
const PANEL = py.status === 0 ? JSON.parse(py.stdout.trim().split("\n").pop()) : null;
check("[4] the panel's own awg_rules / mesh_template / mesh_omit_s_refusal ran on the corpus", !!PANEL, (py.stderr || "").slice(-400));
if (PANEL) {
  const spaE = EDIT.map(([c, r, g]) => IF.awgSaveRule(c, r, "awg9", g));
  const mis = EDIT.map((e, i) => [JSON.stringify(e[0]), spaE[i], PANEL.edit[i]]).filter(([, a, b]) => a !== b);
  check("[4] Edit sheet: awgSaveRule says what the panel's awg_rules says, case by case (R1, R3, R4, R5 and the legal omissions)", !mis.length, mis);
  check("[4] …and the corpus reaches every rule and a pass", ["no AmneziaWG field left", "go together", "header protection needs", "S1 + 56", ""]
        .every(w => PANEL.edit.some(x => w ? x.includes(w) : x === "")), PANEL.edit);
  const spaL = LINK.map(([o, f, g]) => { Store.panelSettings = { mesh_awg: f }; return IF.meshSNone(o, g, "na", "nb"); });
  const misL = LINK.map((l, i) => [JSON.stringify(l), spaL[i], PANEL.link[i]]).filter(([, a, b]) => a !== b);
  check("[4] mesh-link sheet: meshSNone says what the panel's mesh_omit_s_refusal says over its template layering", !misL.length, misL);
}
let isrc = fs.readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
if (MODE && PLANTS[MODE][0] === "iface.js") isrc = isrc.replace(PLANTS[MODE][1], PLANTS[MODE][2]);
check("[4] the Edit sheet's Save waits on it: mimErr (Save's disabled and its title) carries the rule",
      isrc.includes("const mimErr = mimBad ? mimicWhy(mimBad[0], mimBad[1]) : omitNo || omitRule;")
      && isrc.includes("const omitRule = isAwg && AWG_ORDER.some(k => awgIsNone(awg[k])) ? awgSaveRule(awg, meta.awg_params, iface, gen === \"3.1\") : \"\";"));
check("[4] the mesh-link sheet's Save waits on its rule, and says it",
      isrc.includes("disabled: nodeDown || !connDirty || !!quotaErr || !!awgRule,") && isrc.includes("(quotaErr || awgRule ||"));

done(MODE, MODE || "");
