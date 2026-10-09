/* Self-test — the node page's issue bubble speaks the operator's language (q189 VERIFY1-B2 #1; 1.8.8 the same).
 *
 * The node page's header rendered `<HealthDot issues=${nrec.issues}/>` without the translations the panel ships beside them
 * (`issues_i18n`, perr-shaped), so every issue row stayed English under Russian there — while the Nodes list's bubble, given
 * them, translated. The operator wants no untranslated text on screen.
 *
 * [1] every HealthDot in the SPA is given `i18n=` (the node page's included)
 * [2] the panel's own issue sentences — _node_issues run in python on a node with a stopped turn proxy, an unloadable
 *     AmneziaWG module, a torrent policy that failed to load and unfinished package work — rendered by the real HealthDot
 *     in Russian: every row is Russian (the node's own words, an nft line, stay as values), none is the English sentence
 *
 * Run: node tests/spa_issue_bubble_selftest.mjs      --perturb nodepage   the node page's i18n= taken off → RED in [1]
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = { nodepage: ["<${HealthDot} issues=${nrec.issues} i18n=${nrec.issues_i18n}/>", "<${HealthDot} issues=${nrec.issues}/>"] };
if (MODE && !PLANTS[MODE]) { console.log("unknown perturbation " + MODE); process.exit(2); }
let SN = fs.readFileSync(path.join(ROOT, "js", "screen-nodes.js"), "utf8");
if (MODE) {
  if (SN.split(PLANTS[MODE][0]).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would measure nothing"); process.exit(1); }
  SN = SN.replace(PLANTS[MODE][0], PLANTS[MODE][1]);
}

// [1]
console.log("[1] every HealthDot is given the translations");
const calls = [...SN.matchAll(/<\$\{HealthDot\}[^>]*>/g)].map(m => m[0]);
check("[1] the SPA renders HealthDot in two places (the Nodes list, the node page)", calls.length === 2, calls);
check("[1] …and both pass i18n=", calls.length && calls.every(c => /\bi18n=\$\{/.test(c)), calls);

// [2]
console.log("\n[2] the panel's own issue sentences, rendered in Russian");
const PY = `
import json, sys, types
src = open(sys.argv[1], encoding="utf-8").read()
m = types.ModuleType("p"); m.__file__ = sys.argv[1]
exec(compile(src, sys.argv[1], "exec"), m.__dict__)
c = {"id": "n1", "name": "n1", "ifaces": {}, "p2p": {"action": "block"}}
snap = {"turn_proxies": [{"service": "vk-turn-proxy-WINGS-N-56000", "running": False}],
        "datapath": {"awg": {"needed": True, "ok": False, "fallback": True}},
        "smartroute": {"p2p": {"state": "error", "mode": "block", "detail": "Error: Could not process rule: No such file or directory"}},
        "dpkg": {"pending": ["amneziawg-dkms"]}}
print(json.dumps(m._node_issues(c, snap)))`;
const py = spawnSync("python3", ["-c", PY, path.join(ROOT, "swg-panel-server")], { encoding: "utf8" });
const ISS = py.status === 0 ? JSON.parse(py.stdout.trim().split("\n").pop()) : null;
check("[2] the panel's _node_issues ran on the fixture (four issues at least)", Array.isArray(ISS) && ISS.length >= 4, (py.stderr || "").slice(-400));
globalThis.localStorage = { getItem: k => (k === "swg-lang" ? "ru" : null), setItem: () => {}, removeItem: () => {} };
const I = await import(pathToFileURL(path.join(ROOT, "js", "i18n.js")).href);
await I.loadLang();
const made = path.join(ROOT, "js", "__perturbed_screen-nodes.js");
let SNM;
try { fs.writeFileSync(made, SN); SNM = await import(pathToFileURL(made).href); } finally { fs.rmSync(made, { force: true }); }
if (ISS) {
  const flat = x => Array.isArray(x) ? x.map(flat).join("") : x && typeof x === "object" && x.props ? flat(x.props.children) : x == null || x === false ? "" : String(x);
  const rows = v => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
    else if (x && typeof x === "object" && x.props) { if (/\bon-name\b/.test(String(x.props.class || ""))) out.push(flat(x.props.children)); w(x.props.children); } }; w(v); return out; };
  const v = SNM.HealthDot({ issues: ISS.map(i => i.error), i18n: ISS });
  const R = rows(v);
  const eng = ISS.map(i => i.error);
  check("[2] the bubble shows every issue", R.length === ISS.length, R);
  check("[2] …each row in Russian, none the English sentence", R.length && R.every((r, i) => /[А-Яа-яЁё]/.test(r) && r !== eng[i]), R);
  check("[2] …the node's own nft line kept as it is, inside the Russian sentence",
        R.some(r => r.includes("Error: Could not process rule") && /[А-Яа-яЁё]/.test(r)), R);
}

done(MODE, MODE || "");
