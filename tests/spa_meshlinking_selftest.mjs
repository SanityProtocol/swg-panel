/* Self-test: the "linking →" badge says a new forward target is waiting for its link — and says nothing else, ever.
 *
 * On demand (docs/MESH-ON-DEMAND-PLAN.md) a node pair is linked when something routes over it, so a newly chosen forward
 * target takes one link-up (~13 s measured live on swgt) before traffic flows; the node holds that traffic in the new
 * peerless tunnel meanwhile rather than sending it out directly. `ifTrafficBadge` says so on the interface's Throughput
 * row. Three guards keep it from saying it when it is not true:
 *   • MODE   — only on demand: in a full mesh every pair is linked already, and full-mesh screens must not change;
 *   • RECORD — only while a link RECORD exists: no record means the pool could not place it (the node card says why), and
 *              "linking" would then be a promise nothing keeps;
 *   • STATE  — only while the link is still coming up ("connecting"): a link that is DOWN is a fault the node card
 *              reports, not a wait; a live one is simply the ordinary cascade badge.
 * And the tooltip promises no time: a link that never comes up would make one a lie.
 *
 * Run: node tests/spa_meshlinking_selftest.mjs            (0 = pass)
 *      node tests/spa_meshlinking_selftest.mjs --perturb  each plant must go red on its own check ("N plants, N caught")
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const SRC = path.join(ROOT, "js", "routing.js");
// One plant per guard: [name, exact source text, replacement, the check that must go red].
const PLANTS = [
  ["mode", '(Store.panelSettings || {}).mesh_effective === "demand" && node &&', "node &&",
   "a full mesh never says linking, even while a link comes up"],
  ["record", "(p => !!p && p.out === \"connecting\")", "(p => !p || p.out === \"connecting\")",
   "no link record (the pool could not place it) → the ordinary badge"],
  ["state", "(p => !!p && p.out === \"connecting\")", "(p => !!p && p.out !== \"up\")",
   "a link that is DOWN → the ordinary badge (a fault, not a wait)"],
];

const plantArg = (process.argv.find(a => a.startsWith("--plant=")) || "").slice(8);
if (process.argv.includes("--perturb")) {
  const src = fs.readFileSync(SRC, "utf8");
  let caught = 0; const bad = [];
  for (const [name, a, b, must] of PLANTS) {
    if (src.split(a).length - 1 !== 1) { bad.push(name + ": anchor not found exactly once (stale plant)"); continue; }
    const r = spawnSync(process.execPath, [fileURLToPath(import.meta.url), "--plant=" + name], { encoding: "utf8" });
    const red = r.stdout.includes("  FAIL " + must) && r.status !== 0;
    console.log("  " + name.padEnd(8) + (red ? "caught" : (/Error|at /.test(r.stderr) ? "CRASHED (not a catch)" : "NOT CAUGHT")));
    red ? caught++ : bad.push(name);
  }
  console.log(`${PLANTS.length} plants, ${caught} caught`);
  bad.forEach(b => console.log("  ✗ " + b));
  process.exit(caught === PLANTS.length && !bad.length ? 0 : 1);
}

let mod = SRC;
if (plantArg) {
  const [, a, b] = PLANTS.find(p => p[0] === plantArg);
  mod = path.join(ROOT, "js", "__perturb_meshlinking.js");   // alongside the original, so its relative imports resolve
  fs.writeFileSync(mod, fs.readFileSync(SRC, "utf8").replace(a, b));
}
// ⚠️ The planted copy lives in js/, where a deploy would ship it: removed whether or not the import succeeds.
let ifTrafficBadge;
try { ({ ifTrafficBadge } = await import(pathToFileURL(mod).href)); }
finally { if (plantArg) fs.rmSync(mod, { force: true }); }
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);

// The badge is a vnode; what the operator reads is its text and its tooltip.
const text = v => v == null || typeof v === "boolean" ? "" : typeof v !== "object" ? String(v)
  : Array.isArray(v) ? v.map(text).join("") : text((v.props || {}).children);
const badge = () => { const v = ifTrafficBadge("forward", "b", "a", ""); return { text: text(v).replace(/\s+/g, " ").trim(), title: (v.props || {}).title || "" }; };

// A two-node fleet: `a` forwards an interface to `b`. `link` shapes the a↔b link as the panel reports it.
function fleet({ mode = "demand", link = "connecting" } = {}) {
  Store.panelSettings = { mesh_effective: mode };
  Store.recon.nodeStatus = { a: "live", b: link === "stale" ? "stale" : "live" };
  const rec = link !== "none";
  Store.fleet = [{ id: "a", name: "A" }, { id: "b", name: "B" }];   // what nodeName() reads
  Store.nodes = [
    { id: "a", name: "A", mesh_peers: rec ? [{ peer: "b", iface: "swg_ab", reprovisioning: link === "creating" }] : [] },
    { id: "b", name: "B", mesh_peers: rec ? [{ peer: "a", iface: "swg_ab", reprovisioning: link === "creating" }] : [] },
  ];
  const hs = { connecting: undefined, creating: undefined, up: 20, down: 900, stale: 20 }[link];
  Store.describe = rec && link !== "creating" ? { a: { swg_ab: { handshake_age: hs } }, b: { swg_ab: { handshake_age: hs } } } : {};
}

console.log("\n[1] on demand, a new target's link coming up reads \"linking\"");
fleet({ link: "creating" });
check("the link is still being created on the node → linking → B", badge().text.startsWith("linking →") && badge().text.endsWith("B"), badge());
fleet({ link: "connecting" });
check("the link exists but has not handshaken yet → linking → B", badge().text.startsWith("linking →"), badge());
check("…and the tooltip names the target and promises no time",
      /Linking to B/.test(badge().title) && !/second|usually|\d/.test(badge().title), badge().title);

console.log("\n[2] …and nothing else ever does");
fleet({ link: "up" });
check("the link is up → the ordinary cascade badge", badge().text.startsWith("cascade →"), badge());
fleet({ link: "down" });
check("a link that is DOWN → the ordinary badge (a fault, not a wait)", badge().text.startsWith("cascade →"), badge());
fleet({ link: "stale" });
check("the target node has gone dark → the ordinary badge", badge().text.startsWith("cascade →"), badge());
fleet({ link: "none" });
check("no link record (the pool could not place it) → the ordinary badge", badge().text.startsWith("cascade →"), badge());
fleet({ mode: "full", link: "connecting" });
check("a full mesh never says linking, even while a link comes up", badge().text.startsWith("cascade →"), badge());
fleet({ mode: "full", link: "up" });
check("…and its ordinary badge is exactly today's", badge().text === "cascade → B" && badge().title === "Cascade — exits via B", badge());

done(false);
