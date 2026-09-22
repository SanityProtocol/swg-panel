/* Self-test: the AmneziaWG 3.1 UI asks ONE question, and a 2.0 interface's badges carry nothing new (docs/AWG3-PLAN.md §7.7).
 *
 * [1] awgGen / awgDict3 — the generation is the dict (§7.1): an AWG dict holding a HeaderProtectionKey is 3.1, one without
 *     is 2.0 (a one-sided 3.x key such as ContentPaddingAddition does not make it 3.1), plain WireGuard and an unknown
 *     interface are neither.
 * [2] the badge helpers — 3.1: the `awg3` class, the "AmneziaWG 3.1" title and a key; 2.0: "" and an EMPTY attribute set.
 *     ⚠️ Not `{ title: null }`: Preact writes a null title as title="", and an empty title HIDES the tooltip of the element
 *     around the badge (the interface card's "Edit interface · AWG") — a 2.0 fleet would lose a tooltip it has today.
 * [3] Tag (js/ui.js), which every target tag goes through — the same rule, read off the vnode it builds.
 * [4] turnForkList() — a WHITELIST rebuild of the served catalog — passes `awg3` through: WINGS-N false, the rest true.
 *     Without it the switch window could not name a WINGS-N proxy before the panel refuses the switch, and the turn-proxy
 *     pickers could not hide a 3.1 interface from it (forkSupportsAwg3).
 * [5] awgGenPending — a switch the node has not applied: the record's generation against the node's report, by GENERATION.
 *     A 2.0 interface whose node lags on a 2.0 value is not a switch (every 2.0 fleet would grow a "switching" tag).
 * [6] awg31No — the refusal the Edit sheet greys 3.1 with: an interface on the userspace fallback takes the panel's
 *     per-interface answer (null included — offered), every other one the node's.
 * [7] the 3.1 colour is tunable like every protocol's — ifaceColor("awg3") is its default until Settings → Interfaces saves a
 *     pick, and applyThemeColors puts the pick on --awg3, the one property every 3.1 badge, the switch and the caption read.
 *     A 3.1 pick leaves the 2.0 colour alone.
 * [8] Awg3Grid (js/iface.js) — the 3.1 cells the Edit sheet and Settings' defaults both draw: six typed inputs, and the
 *     HeaderProtectionKey and RandomTrailers as READ-ONLY inputs (the same box, never typed) carrying what they read and why;
 *     with no `placeholders` (the Edit sheet) an input carries NO placeholder prop — Preact writes a null one as
 *     placeholder="", the title trap again — and with them (Settings) each typed cell shows its built-in value.
 *
 * Run: node tests/spa_awg3_ui_selftest.mjs     --perturb tip|samekey|gen|tag|catalog|pending|fork3|us|colour|var|ph   plants one and expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  tip: ["model.js", 'export const tip3 = (on, id) => on ? { title: T("AmneziaWG 3.1"), key: "awg3" + (id ? ":" + id : "") } : {};',
        'export const tip3 = (on, id) => on ? { title: T("AmneziaWG 3.1"), key: "awg3" + (id ? ":" + id : "") } : { title: null };'],
  samekey: ["model.js", 'export const tip3 = (on, id) => on ? { title: T("AmneziaWG 3.1"), key: "awg3" + (id ? ":" + id : "") } : {};',
            'export const tip3 = (on, id) => on ? { title: T("AmneziaWG 3.1"), key: "awg3" } : {};'],
  gen: ["model.js", 'export const awgDict3 = a => !!(a && String(a.HeaderProtectionKey || "").trim());',
        'export const awgDict3 = a => !!(a && Object.keys(a).length);'],
  tag: ["ui.js", '...${notip ? {} : tip3(gen3)}', 'title=${gen3 && !notip ? T("AmneziaWG 3.1") : null}'],
  catalog: ["turn-catalog.js", "      awg3: s.awg3 !== false,", ""],
  pending: ["model.js", "  return want === awgDict3(m.awg_reported) ? null : (want ? \"3.1\" : \"2.0\");",
            "  return JSON.stringify(m.awg_params) === JSON.stringify(m.awg_reported) ? null : (want ? \"3.1\" : \"2.0\");"],
  fork3: ["turn-catalog.js", "  return !f || f.awg3 !== false;", "  return true;"],
  us: ["model.js", "  return (us && Object.prototype.hasOwnProperty.call(us, iface)) ? us[iface] : ((nrec || {}).awg31_no || null);",
       "  return (nrec || {}).awg31_no || null;"],
  colour: ["ui.js", 'const k = t === "awg" ? "awg" : t === "awg3" ? "awg3" : t === "wdtt"', 'const k = t === "awg" ? "awg" : t === "wdtt"'],
  var: ["ui.js", '  de.style.setProperty("--awg3", awg3);', ""],
  ph: ["iface.js", '...${placeholders ? { placeholder: placeholders[k] || "" } : {}}', 'placeholder=${placeholders ? placeholders[k] || "" : null}'],
};
const made = [];
const load = async name => {
  if (!MODE || PLANTS[MODE][0] !== name) return import(pathToFileURL(path.join(ROOT, "js", name)).href);
  let s = fs.readFileSync(path.join(ROOT, "js", name), "utf8");
  const [, a, b] = PLANTS[MODE];
  if (s.split(a).length !== 2) { console.log("ANCHOR MISSING for " + MODE); process.exit(1); }
  const p = path.join(ROOT, "js", "__perturb_" + name); fs.writeFileSync(p, s.replace(a, b)); made.push(p);
  return import(pathToFileURL(p).href);
};
let M, U, C, IF;
try { M = await load("model.js"); U = await load("ui.js"); C = await load("turn-catalog.js"); IF = await load("iface.js"); }
finally { made.forEach(p => { try { fs.unlinkSync(p); } catch (_) { /* already gone */ } }); }   // a plant never outlives this run
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);

const S20 = { Jc: "4", Jmin: "40", Jmax: "70", S1: "28", S2: "94", S3: "88", S4: "33", H1: "1-2", H2: "3-4", H3: "5-6", H4: "7-8" };
const S31 = { ...S20, HeaderProtectionKey: "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0=", RandomTrailers: "1", ContentPaddingAddition: "10-100" };
Store.describe = { n1: { awg0: { awg_params: S20, tool: "awg" }, awg1: { awg_params: S31, tool: "awg" }, wg0: { awg_params: {}, tool: "wg" },
                         awgC: { awg_params: { ...S20, ContentPaddingAddition: "10-100" }, tool: "awg" } } };

console.log("\n[1] the generation is the dict");
check("a 2.0 dict is 2.0", M.awgGen("n1", "awg0") === "2.0", M.awgGen("n1", "awg0"));
check("a dict with a HeaderProtectionKey is 3.1", M.awgGen("n1", "awg1") === "3.1", M.awgGen("n1", "awg1"));
check("plain WireGuard is neither", M.awgGen("n1", "wg0") === null, M.awgGen("n1", "wg0"));
check("a one-sided 3.x key without the key is still 2.0", M.awgGen("n1", "awgC") === "2.0", M.awgGen("n1", "awgC"));
check("an interface nobody reports is neither", M.awgGen("n1", "nope") === null && M.awgGen("n9", "awg0") === null);

console.log("\n[2] a 2.0 badge carries nothing new; a 3.1 one carries the colour, the tooltip and its own key");
const t2 = M.awg3Tip("n1", "awg0"), t3 = M.awg3Tip("n1", "awg1"), tw = M.awg3Tip("n1", "wg0");
check("2.0: no class", M.awg3Cls("n1", "awg0") === "" && M.awg3Cls("n1", "wg0") === "");
check("2.0: an EMPTY attribute set — no title key at all", JSON.stringify(t2) === "{}" && !("title" in t2) && JSON.stringify(tw) === "{}", t2);
check("tip3(false) is {} too", JSON.stringify(M.tip3(false)) === "{}", M.tip3(false));
check("3.1: the awg3 class", M.awg3Cls("n1", "awg1") === " awg3", M.awg3Cls("n1", "awg1"));
check("3.1: the tooltip and a key", t3.title === "AmneziaWG 3.1" && !!t3.key, t3);
Store.describe.n1.awg2 = { awg_params: S31, tool: "awg" };
check("two 3.1 badges in one list never share a key", M.awg3Tip("n1", "awg1").key !== M.awg3Tip("n1", "awg2").key,
      [M.awg3Tip("n1", "awg1").key, M.awg3Tip("n1", "awg2").key]);

console.log("\n[3] Tag — every target tag — follows the same rule");
const v2 = U.Tag({ kind: "awg", label: "awg0" }), v3 = U.Tag({ kind: "awg", label: "awg1", gen3: true });
check("a 2.0 tag: exactly the class it always had", v2.props.class === "tg tg-awg", v2.props.class);
check("a 2.0 tag: no title prop", !("title" in v2.props), Object.keys(v2.props));
check("a muted 2.0 tag unchanged", U.Tag({ kind: "awg", label: "x", muted: true }).props.class === "tg tg-awg muted");
const vn = U.Tag({ kind: "awg", label: "awg1", gen3: true, notip: true });
check("a 3.1 tag that triggers a hover bubble: the colour, no native tooltip over the bubble", vn.props.class === "tg tg-awg awg3" && !("title" in vn.props),
      { cls: vn.props.class, title: vn.props.title });
check("a 3.1 tag: the class, the tooltip, a key", v3.props.class === "tg tg-awg awg3" && v3.props.title === "AmneziaWG 3.1" && v3.key != null,
      { cls: v3.props.class, title: v3.props.title, key: v3.key });
check("tgt3 reads the target's interface", U.tgt3({ node: "n1", iface: "awg1" }) === true && U.tgt3({ node: "n1", iface: "awg0" }) === false
      && U.tgt3(null) === false);

console.log("\n[4] the fork list the switch window reads carries the catalog's awg3");
Store.turnCatalog = { clients: {}, servers: [{ id: "WINGS-N", kind: "turn", awg3: false }, { id: "samosvalishe", kind: "turn" }, { id: "MYSOREZ", kind: "turn", awg3: true }] };
const f = Object.fromEntries(C.turnForkList().map(x => [x.id, x]));
check("WINGS-N: false", !!f["WINGS-N"] && f["WINGS-N"].awg3 === false, f["WINGS-N"]);
check("a fork the catalog says nothing about: true", !!f.samosvalishe && f.samosvalishe.awg3 === true, f.samosvalishe);
check("a fork the catalog says true about: true", !!f.MYSOREZ && f.MYSOREZ.awg3 === true);
check("forkSupportsAwg3: WINGS-N no, the others and an unknown fork yes", C.forkSupportsAwg3("WINGS-N") === false
      && C.forkSupportsAwg3("samosvalishe") === true && C.forkSupportsAwg3("nosuchfork") === true);

console.log("\n[5] a switch in flight is a GENERATION difference, never a key-by-key one");
Store.describe.n2 = {
  lag20: { awg_params: S20, awg_reported: { ...S20, Jc: "3" } },        // a 2.0 record, the node still on an older Jc
  up31: { awg_params: S31, awg_reported: S20 },                           // switched to 3.1, the node not there yet
  back20: { awg_params: S20, awg_reported: S31 },                         // switched back, the node still has the key
  done31: { awg_params: S31, awg_reported: { ...S31, Jc: "3" } },         // applied; a 2.0 value still converging
  norec: { awg_params: S31 },                                             // no record: nothing the panel asked for
};
check("a 2.0 interface whose node lags on a 2.0 value: nothing in flight", M.awgGenPending("n2", "lag20") === null, M.awgGenPending("n2", "lag20"));
check("switched to 3.1, not applied: 3.1", M.awgGenPending("n2", "up31") === "3.1", M.awgGenPending("n2", "up31"));
check("switched back, not applied: 2.0", M.awgGenPending("n2", "back20") === "2.0", M.awgGenPending("n2", "back20"));
check("applied, a 2.0 value still converging: nothing", M.awgGenPending("n2", "done31") === null, M.awgGenPending("n2", "done31"));
check("no record, no report of a wish: nothing", M.awgGenPending("n2", "norec") === null && M.awgGenPending("n2", "nope") === null);

console.log("\n[6] the Edit sheet's refusal: per interface on the userspace fallback, else the node's");
const MOD = { error: "n: its AmneziaWG kernel module is 2.0 — …", error_key: "{v1}: its AmneziaWG kernel module is {v2} — an AmneziaWG 3.1 interface needs 3.1" };
const FB = { error: "n: its userspace AmneziaWG (amneziawg-go) … is 3.0", error_key: "x" };
const nrec = { awg31_no: MOD, awg31_no_us: { awg5: null, awg7: FB } };
check("on a 3.1 fallback: offered, whatever the module says", M.awg31No(nrec, "awg5") === null, M.awg31No(nrec, "awg5"));
check("on a 3.0 fallback: the fallback's own refusal", M.awg31No(nrec, "awg7") === FB, M.awg31No(nrec, "awg7"));
check("on the kernel: the node's (the module's)", M.awg31No(nrec, "awg6") === MOD, M.awg31No(nrec, "awg6"));
check("a node with no per-interface map: the node's, or null", M.awg31No({ awg31_no: MOD }, "awg6") === MOD && M.awg31No({}, "x") === null && M.awg31No(null, "x") === null);

console.log("\n[7] the 3.1 colour: its default until a pick is saved, then the pick — on --awg3");
const { IFACE_COLOR_DEFAULTS } = await import(pathToFileURL(path.join(ROOT, "js", "theme.js")).href);
const props = {};
document.documentElement.style.setProperty = (k, v) => { props[k] = v; };   // applyThemeColors writes --brand, --awg3, … here
document.getElementById = () => null;
Store.panelSettings = {};
check("no pick: the default blue", U.ifaceColor("awg3") === IFACE_COLOR_DEFAULTS.awg3.dark && IFACE_COLOR_DEFAULTS.awg3.dark === "#4481FF", U.ifaceColor("awg3"));
U.applyThemeColors();
check("…and --awg3 carries it", props["--awg3"] === "#4481FF", props["--awg3"]);
Store.panelSettings = { iface_colors: { awg3: { dark: "#FF00AA", light: "#1D3FD6" } } };
check("a saved pick: the pick", U.ifaceColor("awg3") === "#FF00AA", U.ifaceColor("awg3"));
U.applyThemeColors();
check("…on --awg3", props["--awg3"] === "#FF00AA", props["--awg3"]);
check("…and the 2.0 colour is left alone", U.ifaceColor("awg") === IFACE_COLOR_DEFAULTS.awg.dark, U.ifaceColor("awg"));

console.log("\n[8] the 3.1 cells: six inputs, a placeholder only where Settings gives one");
const inputs = n => { const out = []; const walk = x => { if (Array.isArray(x)) x.forEach(walk);
  else if (x && typeof x === "object" && x.props) { if (x.type === "input") out.push(x.props); walk(x.props.children); } }; walk(n); return out; };
const labels = n => { const out = []; const walk = x => { if (Array.isArray(x)) x.forEach(walk);
  else if (x && typeof x === "object" && x.props) { if (x.type === "span" && typeof x.props.children === "string") out.push(x.props.children); walk(x.props.children); } }; walk(n); return out; };
const edit = IF.Awg3Grid({ value: { ContentPaddingAddition: "10-100" }, onKey: () => {}, hpk: "set", rt: "on", hpkTip: "why-k", rtTip: "why-r" });
const setg = IF.Awg3Grid({ value: {}, onKey: () => {}, hpk: "new", rt: "on", hpkTip: "k", rtTip: "r", placeholders: { ContentPaddingAddition: "10-100", MaxHandshakeAttempts: "15-20" } });
const typed = n => inputs(n).filter(p => !p.readonly), ro = n => inputs(n).filter(p => p.readonly);
check("six typed inputs; the key and RandomTrailers read-only, with what they read and why", typed(edit).length === 6
      && JSON.stringify(ro(edit).map(p => [p.value, p.title])) === JSON.stringify([["set", "why-k"], ["on", "why-r"]])
      && labels(edit).includes("HeaderProtectionKey") && labels(edit).includes("RandomTrailers"), inputs(edit).map(p => Object.keys(p)));
check("the Edit sheet (no placeholders): no input carries a placeholder prop", inputs(edit).every(p => !("placeholder" in p)),
      inputs(edit).map(p => p.placeholder));
check("Settings: each typed cell shows its built-in value, blank where none is given — the read-only two none",
      JSON.stringify(typed(setg).map(p => p.placeholder)) === JSON.stringify(["10-100", "15-20", "", "", "", ""])
      && ro(setg).every(p => !("placeholder" in p)), inputs(setg).map(p => p.placeholder));

done(!!MODE, MODE);
