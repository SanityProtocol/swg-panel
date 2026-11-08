/* Self-test: the browser's scale fixes (docs/SCALE-PLAN.md K3, U3) give the answers the code before them gave.
 *
 * Every change in K3 is a cheaper way to reach the SAME output, so the gate is a differential: the pre-K3 code is the oracle.
 *
 *   reach      reachIndex no longer holds every user × user pair per node; reachOwners works one person's set out when asked.
 *              The pre-K3 js/views.js (git show PRE_K3) runs beside today's on the same Store, on 200 random rosters — nodes
 *              live / stale / too old to enforce, interfaces at Everyone / user / Nobody / unvouched, groups with duplicate and
 *              deleted members, private / blocked / expired / unassigned / orphaned devices, blocked users: reachOwners (in
 *              ORDER), userReach and reachTally equal for every user and for one who does not exist.
 *   lookups    Store.user / Store.peer through a Map per array equal the linear find for every id and a missing one, also
 *              after `Store.recon.peers` is REPLACED on the same recon object (a gate does that; a Map keyed on the recon
 *              would keep answering from the old array).
 *   scope      Overview's scopeCounts equal the expressions it replaced: users with a scoped peer, and per node the peers
 *              with a deployment there / an online one — a peer counted once however many of its deployments sit there.
 *   apply      with no patch pending the screens read the fetched objects themselves (no clone); a pending patch writes a
 *              clone, never the fetched copy, and the next apply without it shows the fetched value again.
 *
 * FlowMap2's per-render memos need a DOM and are checked in a browser (the card), not here.
 *
 * Run: node tests/spa_scale_selftest.mjs          (0 = pass)
 *      --plant NAME   applies one plant and expects RED (exit 0 = it went red)
 *      plants: order self atuser mapkey clonenever clonealways twice
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, check, done, FAILS } from "./spa_env.mjs";

const PRE_K3 = "58857cad";   // the last commit before K3: its reachIndex builds every pair
const PLANT = process.argv.includes("--plant") ? process.argv[process.argv.indexOf("--plant") + 1] : "";
const PLANTS = {   // name: [file, anchor, replacement]
  order: ["js/views.js",
    "    for (const o of open.get(nid) || []) if (o !== uid) out.add(o);\n    // \"user\": every member of a group reaches every other member's devices there (a member at \"user\" there is on the node)\n    const atUser = lvl.get(nid);\n    if (atUser) for (const g of groups) for (const b of g.users) if (b !== uid && atUser.has(b)) out.add(b);\n",
    "    const atUser = lvl.get(nid);\n    if (atUser) for (const g of groups) for (const b of g.users) if (b !== uid && atUser.has(b)) out.add(b);\n    for (const o of open.get(nid) || []) if (o !== uid) out.add(o);\n"],
  self: ["js/views.js", "for (const o of open.get(nid) || []) if (o !== uid) out.add(o);", "for (const o of open.get(nid) || []) out.add(o);"],
  atuser: ["js/views.js", "if (b !== uid && atUser.has(b)) out.add(b);", "if (b !== uid && users.has(b)) out.add(b);"],
  mapkey: ["js/store.js", "  if (c[0] !== arr) {\n    const m = new Map();\n    for (const x of arr) if (x && !m.has(x.id)) m.set(x.id, x);\n    c[0] = arr; c[1] = m;",
    "  if (c[0] !== store.recon) {\n    const m = new Map();\n    for (const x of arr) if (x && !m.has(x.id)) m.set(x.id, x);\n    c[0] = store.recon; c[1] = m;"],
  clonenever: ["js/store.js", "const snap = !pend ? this._server :", "const snap = true ? this._server :"],
  clonealways: ["js/store.js", "const snap = !pend ? this._server :", "const snap = false ? this._server :"],
  twice: ["js/screen-overview.js",
    "    for (const t of p.targets) { seen.add(t.node); if (t.online) on.add(t.node); }\n    for (const n of seen) total.set(n, (total.get(n) || 0) + 1);",
    "    for (const t of p.targets) { total.set(t.node, (total.get(t.node) || 0) + 1); if (t.online) on.add(t.node); }"],
};
if (PLANT && !PLANTS[PLANT]) { console.log("unknown plant " + PLANT); process.exit(2); }
const written = [];
const sibling = (file, src, tag) => {   // a sibling copy keeps relative imports working; removed at the end
  const out = path.join(ROOT, path.dirname(file), "." + tag + "_" + path.basename(file).replace(/\.js$/, ".mjs"));
  fs.writeFileSync(out, src); written.push(out);
  return import(pathToFileURL(out).href);
};
function load(file) {
  const p = PLANTS[PLANT], abs = path.join(ROOT, file);
  if (!p || p[0] !== file) return import(pathToFileURL(abs).href);
  const src = fs.readFileSync(abs, "utf8");
  if (src.split(p[1]).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would FALSE-PASS: " + p[1]); process.exit(1); }
  return sibling(file, src.replace(p[1], p[2]), "plant");
}

let OLD, V, PS, O, Store;
try {
  let oldSrc;
  try { oldSrc = execFileSync("git", ["-C", ROOT, "show", PRE_K3 + ":js/views.js"], { encoding: "utf8", maxBuffer: 1 << 26 }); }
  catch (e) { console.log("spa_scale_selftest: cannot read the pre-K3 views.js (" + PRE_K3 + "): " + String(e.message).slice(0, 200)); process.exit(1); }
  OLD = await sibling("js/views.js", oldSrc, "prek3");
  V = await load("js/views.js");
  O = await load("js/screen-overview.js");
  PS = (await load("js/store.js")).Store;                                         // the (planted) store: lookups + apply
  Store = (await import(pathToFileURL(path.join(ROOT, "js/store.js")).href)).Store;   // the one both views copies read
} finally {
  for (const f of written) { try { fs.unlinkSync(f); } catch (_) { /* gone */ } }
}

// ── a random fleet, shaped as apply() leaves it ───────────────────────────────────────────────────────────────────────────
let seed = 12345;
const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
const pick = a => a[Math.floor(rnd() * a.length)];
const NODES = ["n1", "n2", "n3", "n4", "n5"], IFS = ["wg0", "awg0", "wg1"];
function fleet() {
  const nodeStatus = {}, stats = {}, describe = {}, nodes = [];
  for (const n of NODES) {
    nodeStatus[n] = rnd() < 0.75 ? "live" : "stale";
    stats[n] = { net_deps: { reach: rnd() < 0.8 ? 2 : 1 } };
    describe[n] = {};
    for (const i of IFS) describe[n][i] = { reach: pick(["everyone", "user", "user", "nobody", undefined]) };
    nodes.push({ id: n, name: "node-" + n, reach_unvouched: rnd() < 0.2 ? [pick(IFS)] : [] });
  }
  const nU = 3 + Math.floor(rnd() * 30), users = [], rUsers = {};
  for (let i = 0; i < nU; i++) {
    const id = "u" + i, u = { id, name: "User" + Math.floor(rnd() * nU / 2), disabled: rnd() < 0.08 };   // repeated names: sort ties
    users.push(u); rUsers[id] = { name: u.name };
  }
  const peers = [];
  let k = 0;
  const target = () => ({ node: pick(NODES), iface: pick(IFS), ip: "10." + Math.floor(rnd() * 9) + ".0." + (k + 2), online: rnd() < 0.5 });
  for (const u of users) for (let d = Math.floor(rnd() * 4); d > 0; d--) {
    const tg = [target()];
    if (rnd() < 0.35) tg.push(target());                       // a second deployment — sometimes on the same node
    if (rnd() < 0.15) tg.push({ ...tg[0], iface: tg[0].iface === "wg0" ? "awg0" : "wg0" });
    peers.push({ id: "p" + (k++), user_id: u.id, title: rnd() < 0.5 ? "dev" + k : "", unassigned: false, targets: tg,
                 private: rnd() < 0.15, disabled: rnd() < 0.08, expired: rnd() < 0.06 });
  }
  for (let i = 0; i < 3; i++) peers.push({ id: "p" + (k++), user_id: null, unassigned: true, title: "", targets: [target()] });
  peers.push({ id: "p" + (k++), user_id: "deleted-owner", unassigned: true, title: "orphan", targets: [target()] });
  const groups = {};
  for (let g = Math.floor(rnd() * 5); g > 0; g--) {
    const mem = [];
    for (let j = Math.floor(rnd() * 8); j > 0; j--) mem.push(pick(users).id);
    if (mem.length && rnd() < 0.3) mem.push(mem[0]);           // a duplicate member
    if (rnd() < 0.3) mem.push("deleted-user");                  // a member who no longer exists
    groups["g" + g] = { name: "Group" + Math.floor(rnd() * 3), users: mem };
  }
  return { nodeStatus, stats, describe, nodes, users, rUsers, peers, groups };
}
function install(S, f) {
  S.roster = { users: f.rUsers, groups: f.groups, peers: {} };
  S.recon = { peers: f.peers, users: f.users, nodeStatus: f.nodeStatus, orphans: [] };   // a new recon: every memo's key
  S.stats = f.stats; S.describe = f.describe; S.nodes = f.nodes; S.panelSettings = {};
}
const reachOf = (VV, uid) => JSON.stringify({
  owners: [...VV.reachOwners(uid)],
  rows: VV.userReach(uid).map(r => [r.user.id, r.online, r.devices.map(d => [d.peer.id, d.node, d.ip, d.online])]),
  tally: VV.reachTally(uid),
});

console.log("\n[1] reach — today's per-node index answers exactly what the pair walk answered, order included");
let rows = 0, owners = 0, bad = null;
const ROUNDS = 200;
for (let r = 0; r < ROUNDS && !bad; r++) {
  const f = fleet();
  install(Store, f);
  const uids = [...f.users.map(u => u.id), "nobody-at-all"];
  // The new copy first on half the rounds: neither may lean on a memo the other filled.
  const order = r % 2 ? [V, OLD] : [OLD, V];
  const got = new Map(uids.map(u => [u, {}]));
  for (const VV of order) {
    install(Store, f);                                          // fresh recon → both start cold
    for (const u of uids) got.get(u)[VV === V ? "new" : "old"] = reachOf(VV, u);
  }
  for (const u of uids) {
    const g = got.get(u);
    rows++; owners += JSON.parse(g.old).owners.length;
    if (g.old !== g.new) bad = { round: r, user: u, old: JSON.parse(g.old), new: JSON.parse(g.new) };
  }
}
check(`reachOwners / userReach / reachTally equal the pre-K3 code for every user of ${ROUNDS} random fleets`, !bad, bad);
check("…and the fleets were not trivial (people reached someone)", owners > rows, { rows, owners });

console.log("\n[2] Store.user / Store.peer — a Map per array, the same answer as find()");
{
  let miss = null;
  for (let r = 0; r < 30 && !miss; r++) {
    const f = fleet();
    install(PS, f);
    for (const p of f.peers) if (PS.peer(p.id) !== f.peers.find(x => x.id === p.id)) miss = { peer: p.id };
    for (const u of f.users) if (PS.user(u.id) !== f.users.find(x => x.id === u.id)) miss = { user: u.id };
    if (PS.peer("p-none") !== undefined || PS.user("u-none") !== undefined) miss = { missing: "answered" };
  }
  check("every id answers the object find() returns; a missing id answers undefined", !miss, miss);
  const f = fleet();
  install(PS, f);
  const first = f.peers[0];
  check("a lookup builds from the current array", PS.peer(first.id) === first);
  const swapped = { ...first, title: "swapped" };
  PS.recon.peers = [swapped, ...f.peers.slice(1)];              // replaced on the SAME recon object (spa_dialin does this)
  check("⚠️ after recon.peers is replaced on the same recon, the lookup reads the new array", PS.peer(first.id) === swapped,
        { title: (PS.peer(first.id) || {}).title });
  const dup = [{ id: "x", n: 1 }, { id: "x", n: 2 }];
  PS.recon.users = dup;
  check("two equal ids: the first wins, as find() does", PS.user("x") === dup[0]);
}

console.log("\n[3] Overview's scopeCounts — the expressions it replaced");
{
  let diff = null;
  for (let r = 0; r < 200 && !diff; r++) {
    const f = fleet();
    const sel = new Set(NODES.filter(() => rnd() < 0.6));
    const sPeers = f.peers.filter(p => p.targets.some(t => sel.has(t.node)));
    const sc = O.scopeCounts(sPeers);
    const oldUsers = f.users.filter(u => sPeers.some(p => p.user_id === u.id)).map(u => u.id);
    const newUsers = f.users.filter(u => sc.users.has(u.id)).map(u => u.id);
    if (JSON.stringify(oldUsers) !== JSON.stringify(newUsers)) diff = { round: r, oldUsers, newUsers };
    for (const n of NODES) {
      const ot = sPeers.filter(p => p.targets.some(d => d.node === n)).length;
      const oo = sPeers.filter(p => p.targets.some(t => t.node === n && t.online)).length;
      if (ot !== (sc.total.get(n) || 0) || oo !== (sc.online.get(n) || 0))
        diff = { round: r, node: n, total: [ot, sc.total.get(n)], online: [oo, sc.online.get(n)] };
    }
  }
  check("users in scope, and per node the peers there and the peers online there, equal on 200 random selections", !diff, diff);
}

console.log("\n[4] apply() — a clone only while a patch is pending");
{
  const f = fleet();
  const roster = { version: 1, users: { ...f.rUsers }, peers: {}, groups: f.groups };
  for (const p of f.peers) roster.peers[p.id] = { user_id: p.unassigned ? null : p.user_id, title: p.title, pubkey: "k" + p.id,
                                                  targets: p.targets.map(t => ({ node: t.node, iface: t.iface, ip: t.ip })) };
  PS._server = { roster, nodes: f.nodes };
  PS.stats = {}; PS.describe = {}; PS.panelSettings = {}; PS.pending = {};
  PS.apply();
  check("no patch pending: the screens read the fetched roster and nodes themselves",
        PS.roster === PS._server.roster && PS.nodes === PS._server.nodes);
  const uid = Object.keys(roster.users)[0], was = roster.users[uid].name;
  PS.pending.t1 = { done: false, apply: s => { s.roster.users[uid].name = "PATCHED"; } };
  PS.apply();
  check("a pending patch shows on screen", PS.roster.users[uid].name === "PATCHED");
  check("⚠️ …and never reaches the fetched copy", PS._server.roster.users[uid].name === was, { fetched: PS._server.roster.users[uid].name });
  delete PS.pending.t1;
  PS.apply();
  check("the next apply without it shows the fetched value again", PS.roster.users[uid].name === was && PS.roster === PS._server.roster,
        { name: PS.roster.users[uid].name });
}

if (PLANT) done(true, PLANT);
done(false);
