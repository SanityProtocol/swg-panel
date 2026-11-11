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
 *   poll       (K4, U1) the roster rides /api/roster, fetched only when the revision /api/state names moves: the same
 *              revision fetches nothing and keeps the SAME object (K3's memos key on it); a failed fetch fails the poll and
 *              keeps roster, identity and revision, and the next poll asks again; a state with no revision keeps the roster;
 *              a mutation's poll fetches the saved roster BEFORE the apply() that drops its done patch (no flicker); a
 *              poll never waits on another poll's (stalled) fetch; a poll overtaken by a later-started one applies nothing —
 *              what is on screen is one poll's state and roster, the newest started — and an error reply takes no place.
 *
 * FlowMap2's per-render memos need a DOM and are checked in a browser (the card), not here.
 *
 * Run: node tests/spa_scale_selftest.mjs          (0 = pass)
 *      --plant NAME   applies one plant and expects RED (exit 0 = it went red)
 *   seats      (K6, T1) the target picker's "n / cap" on a turn server's row: every peer with a target there, blocked ones
 *              too, once however its targets repeat — the panel's create door's count — recounted when the roster object
 *              changes (a save), the cap the node view's; no cap → nothing shown.
 *
 *   online     (K7b, L2) the online rows — onlineUserRows / onlinePeerRows — read a node's peers from one bucket per recon.peers
 *              array: on 200 random fleets, for every node, null, "" and a node nobody is on, every interface and null, the
 *              rows equal the pre-K3 code's (both functions were unchanged since); the array replaced on the same recon is read.
 *   order      (K7b, L3) stableOrder works each row's id out once: over a sequence of calls on one key — rows added, removed,
 *              re-keyed, the input shuffled, sort-key ties — every output equals the pre-K3 code's, call by call.
 *
 *      plants: order self atuser mapkey clonenever clonealways twice revfirst late everypoll copy emptied join errorder noorder
 *              seatmemo seattwice onlinekey onlinetwice onlineoffline frozenignored
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
  revfirst: ["js/store.js", "    if (typeof d.roster_rev === \"string\" && d.roster_rev !== this._rosterRev) {\n",
    "    if (typeof d.roster_rev === \"string\" && d.roster_rev !== this._rosterRev) {\n      this._rosterRev = d.roster_rev;\n"],
  late: ["js/store.js", "      roster = r.data; rev = r.rev;", "      rev = r.rev; setTimeout(() => { this._server.roster = r.data; });"],
  everypoll: ["js/store.js", "d.roster_rev !== this._rosterRev) {", "true) {"],
  copy: ["js/store.js", "roster: roster || this._server.roster,", "roster: structuredClone(roster || this._server.roster),"],
  emptied: ["js/store.js", "roster: roster || this._server.roster,", "roster: roster || { version: 1, users: {}, peers: {} },"],
  join: ["js/store.js", "      const r = await api.roster(d.roster_rev);",
    "      const r = await (this._j && this._j.rev === d.roster_rev ? this._j.p : (this._j = { rev: d.roster_rev, p: api.roster(d.roster_rev) }).p);"],
  errorder: ["js/store.js", "    if (s && s.ok) this._pollApplied = seq;", "    this._pollApplied = seq;"],
  noorder: ["js/store.js", "    if (seq < this._pollApplied) return;\n", ""],
  seatmemo: ["js/model.js", "  const r = Store.roster;\n", "  const r = Store.roster && (globalThis.__seatR = globalThis.__seatR || Store.roster);\n"],
  seattwice: ["js/model.js", "for (const k of new Set(((p && p.targets) || []).filter(Boolean).map(t => t.node + \"|\" + t.iface)))",
    "for (const k of ((p && p.targets) || []).filter(Boolean).map(t => t.node + \"|\" + t.iface))"],
  onlinekey: ["js/views.js", "function onlineAt(nodeId) {\n  const peers = Store.recon.peers || [];\n  let idx = _onlineAt.get(peers);\n  if (!idx) {\n    idx = new Map();\n    for (const p of peers) for (const t of p.targets) if (t.online) {\n      const a = idx.get(t.node);\n      if (!a) idx.set(t.node, [p]);\n      else if (a[a.length - 1] !== p) a.push(p);           // once a peer, however many of its targets are online there\n    }\n    _onlineAt.set(peers, idx);\n  }\n  return idx.get(nodeId) || [];\n}\n",
    "function onlineAt(nodeId) {\n  const peers = Store.recon.peers || [];\n  let idx = _onlineAt.get(Store.recon);\n  if (!idx) {\n    idx = new Map();\n    for (const p of peers) for (const t of p.targets) if (t.online) {\n      const a = idx.get(t.node);\n      if (!a) idx.set(t.node, [p]);\n      else if (a[a.length - 1] !== p) a.push(p);           // once a peer, however many of its targets are online there\n    }\n    _onlineAt.set(Store.recon, idx);\n  }\n  return idx.get(nodeId) || [];\n}\n"],
  onlinetwice: ["js/views.js", "      else if (a[a.length - 1] !== p) a.push(p);", "      else a.push(p);"],
  onlineoffline: ["js/views.js", "    for (const p of peers) for (const t of p.targets) if (t.online) {", "    for (const p of peers) for (const t of p.targets) {"],
  frozenignored: ["js/views.js", "  rs.sort((a, b) => a.at !== b.at ? a.at - b.at : cmp(a.it, b.it));", "  rs.sort((a, b) => cmp(a.it, b.it));"],
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

let OLD, V, PSM, PS, O, Store, MOD;
try {
  let oldSrc;
  try { oldSrc = execFileSync("git", ["-C", ROOT, "show", PRE_K3 + ":js/views.js"], { encoding: "utf8", maxBuffer: 1 << 26 }); }
  catch (e) { console.log("spa_scale_selftest: cannot read the pre-K3 views.js (" + PRE_K3 + "): " + String(e.message).slice(0, 200)); process.exit(1); }
  OLD = await sibling("js/views.js", oldSrc, "prek3");
  V = await load("js/views.js");
  O = await load("js/screen-overview.js");
  MOD = await load("js/model.js");
  PSM = await load("js/store.js"); PS = PSM.Store;                               // the (planted) store: lookups + apply + poll
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

console.log("\n[8] the poll — the roster rides /api/roster, fetched only when its revision moves (K4, U1)");
{
  const A = PSM.api, f = fleet(), uid = Object.keys(f.rUsers)[0];
  const mk = () => {
    const r = { version: 1, users: {}, peers: {}, groups: f.groups };
    for (const [k, u] of Object.entries(f.rUsers)) r.users[k] = { ...u };
    for (const p of f.peers) r.peers[p.id] = { user_id: p.unassigned ? null : p.user_id, title: p.title, pubkey: "k" + p.id,
                                               targets: p.targets.map(t => ({ node: t.node, iface: t.iface, ip: t.ip })) };
    return r;
  };
  let rev = "a", fail = "";
  const serve = { a: mk() }, calls = [];
  // `versions.tag` names the state a poll applied, so a check can see that a poll's state and roster are one pair
  const state = async () => ({ ok: true, data: { roster_rev: rev, nodes: f.nodes, snapshots: {}, describe: {}, panel_settings: {},
                                                 versions: { tag: rev } } });
  A.events = async () => null;
  A.state = state;
  const hold = {};   // rev → the resolvers of its fetches, held open until the check releases them all
  const stall = new Set(), stalled = [];   // a rev whose NEXT fetch stalls (a dead request), and those stalled
  A.roster = async r => {
    calls.push(r);
    if (r in hold) await new Promise(res => { hold[r].push(res); });
    if (stall.has(r)) { stall.delete(r); await new Promise(res => stalled.push(res)); }   // this one fetch only
    const x = fail; fail = "";
    if (x === "throw") throw new Error("network");
    if (x === "notok") return { ok: false, error: "boom" };
    return { ok: true, rev: r, data: serve[r] };
  };
  const tick = () => new Promise(res => setTimeout(res, 0));
  const poll = async () => {   // a poll that must succeed: a throw is a failed check, not a crash
    try { await PS.poll(); } catch (e) { check("a poll that should succeed succeeds", false, String((e && e.message) || e)); }
    await tick();
  };
  PS.pending = {}; PS._rosterRev = null;
  await poll();
  check("a revision not held is fetched once, by the revision the state named",
        calls.length === 1 && calls[0] === "a" && PS.roster === serve.a && PS._rosterRev === "a", { calls, rev: PS._rosterRev });
  const first = PS.roster;
  await poll(); await poll();
  check("the same revision: no fetch, and the screens keep the SAME roster object", calls.length === 1 && PS.roster === first,
        { calls: calls.length, same: PS.roster === first });
  rev = "b"; serve.b = mk();
  for (const how of ["throw", "notok"]) {
    fail = how;
    let threw = false;
    try { await PS.poll(); } catch (_) { threw = true; }
    await tick();
    check("a failed fetch (" + how + ") fails the poll and keeps the roster, its identity and its revision",
          threw && PS.roster === first && PS._rosterRev === "a", { threw, same: PS.roster === first, rev: PS._rosterRev });
  }
  await poll();
  check("…and the next poll fetches it", PS.roster === serve.b && PS._rosterRev === "b", { rev: PS._rosterRev });
  const held = PS.roster, n = calls.length;
  A.state = async () => ({ ok: false, error: "internal" });
  await poll();
  check("a state reply without a revision keeps the held roster", PS.roster === held && calls.length === n,
        { same: PS.roster === held, users: Object.keys(PS.roster.users || {}).length });
  A.state = state;
  // a mutation: its patch is done, the save moved the revision; the poll must bring the saved record in before apply()
  // drops the patch — every apply() of that poll shows it
  rev = "c"; serve.c = mk(); serve.c.users[uid].name = "SAVED";
  PS.pending.m1 = { done: true, apply: s2 => { s2.roster.users[uid].name = "SAVED"; } };
  const seen = [], ap = PS.apply;
  PS.apply = function () { ap.call(this); seen.push(this.roster.users[uid].name); };
  try { await poll(); } finally { PS.apply = ap; }
  check("a mutation's poll: every apply() sees the saved record — no flicker", seen.length > 0 && seen.every(x => x === "SAVED")
        && PS.roster === serve.c && !PS.pending.m1, { seen });
  // overlapping polls each wait only on their own fetch (scale-k4 F14): one asking for the revision another poll's stalled
  // fetch is getting — a save's refresh, say — asks for it itself, applies, and the stalled reply changes nothing
  rev = "d"; serve.d = mk(); stall.add("d");
  const pd = PS.poll();
  await tick(); await tick();
  const second = await Promise.race([PS.poll().then(() => "done", e => "threw " + e), new Promise(r2 => setTimeout(r2, 300, "waited"))]);
  await tick();
  check("a poll never waits on another poll's stalled fetch: it asks for the roster itself and applies", second === "done"
        && PS.roster === serve.d && PS._rosterRev === "d", { second, rev: PS._rosterRev });
  stalled.splice(0).forEach(f2 => f2());
  const [pdr] = await Promise.allSettled([pd]); await tick();
  check("…and the stalled poll, landing at last, settles and changes nothing", pdr.status === "fulfilled" && PS.roster === serve.d
        && PS.versions.tag === "d", { status: pdr.status, state: PS.versions.tag });
  // an older poll landing after a newer one was applied (scale-k4 F3): the newer roster stays
  rev = "e"; serve.e = mk(); hold.e = [];
  const pe = PS.poll();
  await tick(); await tick();
  rev = "f"; serve.f = mk();
  await poll();
  hold.e.forEach(f2 => f2());
  await Promise.allSettled([pe]); await tick();
  check("an older roster landing late never replaces a newer one", PS.roster === serve.f && PS._rosterRev === "f",
        { rev: PS._rosterRev, isF: PS.roster === serve.f, isE: PS.roster === serve.e });
  check("⚠️ …and that late poll applies nothing — not its older state under the newer roster (F10)", PS.versions.tag === "f",
        { state: PS.versions.tag });
  // the later-STARTED poll's pair wins even when its roster is the OLDER one (a pinned revision, F9 F17): the earlier poll
  // names the newer revision and lands first; the later poll names the older one and lands after — it wins, with its state
  rev = "h"; serve.h = mk(); serve.i = mk(); rev = "i"; hold.h = []; hold.i = [];
  const pNewer = PS.poll();                 // started first, names the newer revision i
  await tick(); await tick();
  rev = "h";
  const pOlder = PS.poll();                 // started later, names the older revision h (as a pinned slot answers)
  await tick(); await tick();
  hold.i.forEach(f2 => f2()); await Promise.allSettled([pNewer]); await tick();
  hold.h.forEach(f2 => f2()); await Promise.allSettled([pOlder]); await tick();
  check("the later-started poll's pair is on screen even with the older roster: roster and state from one moment",
        PS.roster === serve.h && PS._rosterRev === "h" && PS.versions.tag === "h", { rev: PS._rosterRev, state: PS.versions.tag });
  // an error reply takes no place in the order (F15): an earlier poll with a good state, landing after it, still applies
  rev = "k"; serve.k = mk(); hold.k = [];
  const pk = PS.poll();
  await tick(); await tick();
  A.state = async () => ({ ok: false, error: "internal" });
  await poll();
  A.state = state;
  hold.k.forEach(f2 => f2()); await Promise.allSettled([pk]); await tick();
  check("an error reply does not drop an earlier poll that brings a good state", PS.roster === serve.k && PS.versions.tag === "k"
        && PS.nodes.length === f.nodes.length, { state: PS.versions.tag, nodes: PS.nodes.length });
}

// ── seats (K6, T1) ────────────────────────────────────────────────────────────────────────────────────────────────────────
{
  const r1 = { version: 1, users: {}, peers: {
    a: { targets: [{ node: "n1", iface: "csqtt1" }, { node: "n2", iface: "csqtt1" }] },
    b: { disabled: true, targets: [{ node: "n1", iface: "csqtt1" }] },
    c: { targets: [{ node: "n1", iface: "wg0" }, null] },
    d: { targets: [{ node: "n1", iface: "csqtt1" }, { node: "n1", iface: "csqtt1" }] } } };   // a hand-edited duplicate: once
  Store.nodes = [{ id: "n1", turn_cap: { csqtt1: 248 } }, { id: "n2" }];
  Store.roster = r1;
  const s1 = MOD.turnSeats("n1", "csqtt1");
  check("a turn server's seats: every peer with a target there, a blocked one too, a duplicate target once",
        s1 && s1.n === 3 && s1.cap === 248, s1);
  check("no cap known → nothing to show", MOD.turnSeats("n2", "csqtt1") === null && MOD.turnSeats("n9", "csqtt1") === null);
  Store.roster = structuredClone(r1); delete Store.roster.peers.b;   // a save: a new roster object
  const s2 = MOD.turnSeats("n1", "csqtt1");
  check("a new roster object is counted again", s2 && s2.n === 2, s2);
}

// ── online rows (K7b, L2) ─────────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[9] online rows — a node's peers from one bucket per recon.peers array, the rows the pre-K3 code built");
{
  const dress = f => {   // the fields the rows read, as reconcile leaves them: online, name, a handshake age with ties
    for (const p of f.peers) {
      p.online = p.targets.some(t => t.online); p.name = p.unassigned ? "" : (f.rUsers[p.user_id] || {}).name;
      p.lastHandshakeAge = pick([null, 5, 5, 30, 120]);
    }
    return f;
  };
  const NS = [...NODES, null, "", "n9"], IS = [...IFS, null, "wg9"];
  const rowsOf = VV => JSON.stringify([NS.map(n => VV.onlineUserRows(n)), NS.map(n => IS.map(i => VV.onlinePeerRows(n, i)))]);
  let bad = null, shown = 0;
  for (let r = 0; r < 200 && !bad; r++) {
    const f = dress(fleet());
    install(Store, f);
    const order = r % 2 ? [V, OLD] : [OLD, V], got = {};
    for (const VV of order) got[VV === V ? "new" : "old"] = rowsOf(VV);
    if (got.old !== got.new) bad = { round: r, old: got.old.slice(0, 300), new: got.new.slice(0, 300) };
    shown += V.onlineUserRows("n1").length;
  }
  check("onlineUserRows / onlinePeerRows equal the pre-K3 code for every node, null, \"\", a stranger, every iface, 200 fleets", !bad, bad);
  check("…and the fleets were not trivial (people online on n1)", shown > 200, { shown });
  const f = dress(fleet());
  install(Store, f);
  V.onlineUserRows("n1"); V.onlinePeerRows("n2", null);         // the buckets are built for this array
  Store.recon.peers = f.peers.map(p => ({ ...p, targets: p.targets.map(t => ({ ...t, online: !t.online })) }));
  check("⚠️ recon.peers replaced on the same recon: the rows come from the new array", rowsOf(V) === rowsOf(OLD));
}

// ── stableOrder (K7b, L3) ─────────────────────────────────────────────────────────────────────────────────────────────────
console.log("\n[10] stableOrder — each row's id once, the order the pre-K3 code kept, call by call");
{
  let bad = null, calls = 0, moved = 0;
  const cmp = (a, b) => a.k - b.k;                                // ties on purpose: stability decides them
  for (let r = 0; r < 200 && !bad; r++) {
    let items = [], next = 0;
    for (let i = Math.floor(rnd() * 30); i > 0; i--) items.push({ id: "r" + next++, k: Math.floor(rnd() * 5) });
    const key = "k7b|" + r;
    for (let c = 0; c < 12 && !bad; c++) {
      const a = OLD.stableOrder(key, items.slice(), x => x.id, cmp).map(x => x.id).join(",");
      const b = V.stableOrder(key, items.slice(), x => x.id, cmp).map(x => x.id).join(",");
      calls++;
      if (a !== b) bad = { round: r, call: c, old: a, new: b };
      if (a !== items.slice().sort(cmp).map(x => x.id).join(",")) moved++;   // the freeze held a row off its live slot
      items = items.filter(() => rnd() > 0.15).map(x => rnd() < 0.3 ? { ...x, k: Math.floor(rnd() * 5) } : x);
      for (let i = Math.floor(rnd() * 4); i > 0; i--) items.push({ id: "r" + next++, k: Math.floor(rnd() * 5) });
      if (rnd() < 0.4) items.reverse();
    }
  }
  check("stableOrder equals the pre-K3 code over 200 sequences of 12 calls (added, removed, re-keyed, shuffled rows)", !bad, bad);
  check("…and the freeze mattered (rows held off their live slot)", moved > calls / 4, { calls, moved });
}

if (PLANT) done(true, PLANT);
done(false);
