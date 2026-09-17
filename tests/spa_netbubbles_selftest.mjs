/* Self-test: the derivations behind the reach / networks / reached-by bubbles (docs/NETWORKS-PLAN.md §18.2–§18.3).
 *
 * These four pure functions decide what an operator is told about who reaches what, and every one of them shipped a bug
 * that a browser found and no gate could have:
 *
 *   deviceNameAt   a device with no title printed its address TWICE — `deviceLabel` already falls back to the address,
 *                  and the caller appended it again ("10.8.0.3 (10.8.0.3)").
 *   ownerNameAt    somebody else's device is named by WHOSE it is: the title belongs to a device you cannot see, the
 *                  owner is who you go to when you want the sharing changed.
 *   peerAudience   ⚠️ the one that matters. `share_grants` ALWAYS puts the owner in its own grant list, so a restricted
 *                  device of a user's own granted to them and the sheet read it back as "shared with this user". It also
 *                  has to drop what the panel drops — a lapsed date, a disabled user, a group that no longer exists —
 *                  and count only the devices a grant is actually worth (ones on a node the provider is deployed to).
 *   reachTally     the chip says the number worth acting on: online while any are, otherwise all of them.
 *
 * Hermetic: a roster is built here and handed to Store, exactly as apply() would.
 *   privateOffOpens  what the sheet warns turning Private OFF opens: the DEVICE by its interface's level, the NETWORKS
 *                  behind it by their share. Reading the share alone told an operator "opens to n-erin" while everyone on
 *                  the node reached the device itself (measured on wire, 1.8.7 qualification D5).
 *
 * Run: node tests/spa_netbubbles_selftest.mjs        (0 = pass)
 *      --perturb       counts a grantee's devices FLEET-WIDE instead of per node, and expects RED.
 *      --perturb-off   privateOffOpens reads the device as still private, and expects RED on [4e].
 */
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const PERTURB_OFF = process.argv.includes("--perturb-off");
const imp = f => import(pathToFileURL(path.join(ROOT, "js", f)).href);
const { Store } = await imp("store.js");
// --perturb: count a grantee's devices FLEET-WIDE instead of on the nodes this device is actually deployed to. That is the
// difference between "this grant is worth 3 devices" and "worth nothing", and [3] must go red on it.
let VSRC = path.join(ROOT, "js", "views.js");
if (PERTURB || PERTURB_OFF) {
  const fs = await import("node:fs");
  let src = fs.readFileSync(VSRC, "utf8");
  const [anchor, to] = PERTURB
    ? ["&& (q.targets || []).some(t => t && nodes.includes(t.node))).length;", "&& (q.targets || []).some(t => !!t)).length;"]
    : ["const p = { ...(peer || {}), private: false };", "const p = { ...(peer || {}) };"];
  if (!src.includes(anchor)) { console.log("ANCHOR MISSING — the perturbation cannot be applied"); process.exit(1); }
  src = src.replace(anchor, to);
  // ⚠️ NOT into js/. That directory is what the panel serves; an exception between the write and the unlink used to
  // leave a 100 KB __perturb_views.js sitting in it. A sibling under the same parent keeps relative imports working.
  VSRC = path.join(ROOT, "js", "..", "js", ".perturb_views.mjs");
  fs.writeFileSync(VSRC, src);
}
let V;
try {
  V = await import(pathToFileURL(VSRC).href);
} finally {
  if (PERTURB || PERTURB_OFF) { try { (await import("node:fs")).unlinkSync(VSRC); } catch (_) { /* already gone */ } }
}

const NOW = Math.floor(Date.now() / 1000);
const DAY = 86400;

// ── the fixture ──────────────────────────────────────────────────────────────────────────────────────────────────────
// gw  — Alice's gateway on n1, carrying a network, shared with: bob (no end), carl (lapsed), dana (disabled),
//       eve (fine, but all her devices are on ANOTHER node), the "fam" group, and a group that no longer exists.
// Every peer is a reconciled peer as the SPA sees it: targets carry node/iface/ip/online.
const T = (node, ip, online = false, iface = "wg0") => ({ node, iface, ip, online });
const peers = [
  { id: "gw", user_id: "alice", title: "office router", routes: ["192.168.50.0/24"], targets: [T("n1", "10.8.0.10", true)],
    // ⚠️ eve (0 devices here) is listed BEFORE bob (2) on purpose: with the fixture in grant order the "grantees who
    // actually reach it sort first" check passed even with the comparator deleted.
    share: { users: { alice: 0, frank: 0, carl: NOW - DAY, dana: 0, bob: 0 }, groups: { fam: 0, ghost: 0 } } },
  { id: "a2", user_id: "alice", title: "", targets: [T("n1", "10.8.0.3", true)] },          // ⚠️ NO TITLE
  { id: "b1", user_id: "bob", title: "laptop", targets: [T("n1", "10.8.0.11", true)] },
  { id: "b2", user_id: "bob", title: "phone", targets: [T("n1", "10.8.0.12")] },            // offline
  { id: "b3", user_id: "bob", title: "old laptop", disabled: true, targets: [T("n1", "10.8.0.13", true)] },   // ⚠️ blocked
  { id: "b4", user_id: "bob", title: "lapsed", expired: true, targets: [T("n1", "10.8.0.14", true)] },        // ⚠️ expired
  { id: "a3", user_id: "alice", title: "alice blocked", disabled: true, targets: [T("n9", "10.9.0.5", true)] },// ⚠️ not presence
  { id: "e1", user_id: "eve", title: "faraway", targets: [T("n9", "10.9.0.1", true)] },     // ⚠️ must never be listed
  { id: "e2", user_id: "eve", title: "nearby", targets: [T("n1", "10.8.0.20", true)] },      // …this is why eve is reachable
  { id: "f1", user_id: "frank", title: "elsewhere", targets: [T("n9", "10.9.0.9", true)] },  // ⚠️ a grant worth nothing
  { id: "u1", user_id: null, title: "", targets: [T("n1", "10.8.0.77")] },                  // unassigned: no owner to name
  // ⚠️ ORPHANED, not unassigned: it HAS a user_id, and that user is not in the roster. The panel reads
  // `user_id if user_id in users else None`, so it is dropped exactly like u1 — while desired_for_node still deploys it,
  // because that one skips only disabled/expired. A live tunnel that loses all reach when its interface is promoted.
  { id: "o1", user_id: "deleted-owner", title: "orphan", targets: [T("n1", "10.8.0.78")] },
  // A PRIVATE device of Alice's, carrying a network and shared with bob and the "fam" group — so every derivation that
  // reads a stored share has something to get wrong. share_grants answers "Alice alone" whatever this share says.
  { id: "apriv", user_id: "alice", title: "vault", private: true, routes: ["192.168.99.0/24"],
    targets: [T("n1", "10.8.0.30", true)], share: { users: { bob: 0 }, groups: { fam: 0 } } },
];
const users = [{ id: "alice", name: "Alice" }, { id: "bob", name: "Bob" }, { id: "carl", name: "Carl" },
  { id: "dana", name: "Dana", disabled: true }, { id: "eve", name: "Eve" }, { id: "frank", name: "Frank" }];
Store.roster = { users: Object.fromEntries(users.map(u => [u.id, u])),
  groups: { fam: { name: "Family", users: ["bob", "carl"] } } };
Store.recon = { peers, users, nodeStatus: {} };
Store.nodes = [{ id: "n1", name: "node-one" }, { id: "n9", name: "node-nine" }];
Store.panelSettings = {};
const peer = id => peers.find(p => p.id === id);

console.log("\n[1] deviceNameAt — the address appears once, and it is the one for THAT node");
check("a titled device reads 'Title (address)'", V.deviceNameAt(peer("b1"), "n1") === "laptop (10.8.0.11)", V.deviceNameAt(peer("b1"), "n1"));
check("⚠️ an UNTITLED device reads its address once, not twice",
      V.deviceNameAt(peer("a2"), "n1") === "10.8.0.3", V.deviceNameAt(peer("a2"), "n1"));
check("the address is the one it answers on that node, not any it has",
      V.deviceNameAt(peer("e1"), "n1") === "faraway", V.deviceNameAt(peer("e1"), "n1"));
check("with no node asked it takes the first address it has", V.deviceNameAt(peer("e1"), null) === "faraway (10.9.0.1)");

console.log("\n[2] ownerNameAt — somebody else's device is named by whose it is");
check("names the owner, not the device's title", V.ownerNameAt(peer("gw"), "n1") === "Alice (10.8.0.10)", V.ownerNameAt(peer("gw"), "n1"));
check("an unassigned device has no owner to name, so it falls back to the device",
      V.ownerNameAt(peer("u1"), "n1") === "10.8.0.77", V.ownerNameAt(peer("u1"), "n1"));

console.log("\n[3] peerAudience — who reaches what is behind ONE device");
const aud = V.peerAudience(peer("gw"));
check("a device with grants reads as shared, not as owner-only", aud.mode === "shared", aud.mode);
check("the owner is named apart, never listed as somebody it was shared WITH",
      aud.owner && aud.owner.id === "alice" && !aud.users.some(u => u.id === "alice"), aud.users.map(u => u.id));
check("⚠️ a LAPSED grant is not access", !aud.users.some(u => u.id === "carl"), aud.users.map(u => u.id));
check("⚠️ a DISABLED user's grant is not access", !aud.users.some(u => u.id === "dana"), aud.users.map(u => u.id));
check("a live grantee is listed", aud.users.some(u => u.id === "bob"), aud.users.map(u => u.id));
check("the group is listed with its live members", aud.groups.length === 1 && aud.groups[0].name === "Family"
      && aud.groups[0].members === 2, aud.groups);
check("⚠️ a group that no longer exists grants nothing", !aud.groups.some(g => g.id === "ghost"), aud.groups.map(g => g.id));
check("⚠️ a grantee is counted only for devices on a node this one is deployed to — a grant worth nothing shows 0",
      (aud.users.find(u => u.id === "frank") || {}).devices === 0, aud.users.map(u => [u.id, u.devices]));
check("…and one whose devices ARE here counts them", (aud.users.find(u => u.id === "bob") || {}).devices === 2,
      aud.users.map(u => [u.id, u.devices]));
check("grantees who actually reach it sort first, so the cap drops the empty ones",
      aud.users[0].id === "bob", aud.users.map(u => u.id));
const open = V.peerAudience({ id: "x", user_id: "alice", routes: ["10.0.0.0/8"], targets: [T("n1", "10.8.0.90")] });
check("a device with no share at all is open to everyone on its node", open.mode === "everyone", open.mode);
const ownOnly = V.peerAudience({ id: "y", user_id: "alice", routes: ["10.0.0.0/8"], targets: [T("n1", "10.8.0.91")],
                                 share: { users: { alice: 0 }, groups: {} } });
check("⚠️ restricted with only the owner in it is OWNER-ONLY — share_grants always puts the owner in",
      ownOnly.mode === "owner" && ownOnly.users.length === 0, [ownOnly.mode, ownOnly.users]);

console.log("\n[4] reachTally — the number worth acting on");
// These nodes report no `net_deps`, so they enforce nothing and everyone on one reaches everyone there (§10.2) — which is
// what makes the tally exercisable here at all. Alice reaches Bob's two devices on n1; one of them is online.
// Alice reaches Bob (laptop online, phone offline — his blocked and expired devices are filtered) and Eve (one device
// on n1). Three devices, two of them online.
const t = V.reachTally("alice");
check("counts the DEVICES reachable, not the people", t.total === 3, t);
check("⚠️ and a blocked or expired device of THEIRS is not one of them", t.total === 3 && !V.userReach("alice")
      .some(r => r.devices.some(d => d.peer.disabled || d.peer.expired)), V.userReach("alice").map(r => r.devices.map(d => d.peer.id)));
check("counts how many of them are online", t.online === 2, t);
check("shows the online number while any are online", t.shown === 2, t);
// ⚠️ THE SINGLE-POINT PIN for myNodes: Eve IS reachable (she has a device on n1), and Alice has a BLOCKED device on n9.
// If presence counted blocked devices, n9 would join myNodes and Eve's n9 device would be listed as reachable too.
check("⚠️ a blocked device of this user's is not presence — the other node's device stays out",
      (V.userReach("alice").find(r => r.user.id === "eve") || { devices: [] }).devices.map(d => d.peer.id).join() === "e2",
      V.userReach("alice").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
const t0 = V.reachTally("nobody-at-all");
check("a user who reaches nothing tallies zero and shows zero", t0.total === 0 && t0.online === 0 && t0.shown === 0, t0);
// …and with nothing online the chip falls back to the total, so it never reads 0 beside a list that has rows in it.
peers.filter(p => p.user_id === "bob" || p.user_id === "eve").forEach(p => p.targets.forEach(x => { x.online = false; }));
Store.recon = { peers, users, nodeStatus: {} };          // a new recon object: that identity is the memo's key
const tOff = V.reachTally("alice");
check("with nothing online it falls back to the total", tOff.online === 0 && tOff.shown === tOff.total && tOff.total === 3, tOff);
peers.filter(p => p.id === "b1").forEach(p => p.targets.forEach(x => { x.online = true; }));
Store.recon = { peers, users, nodeStatus: {} };

console.log("\n[4a] the flag survives the trip into the browser");
// ⚠️ THE ONE THAT ACTUALLY BIT. reconcile() rebuilds every peer from a whitelist, so a field it does not name does not
// exist in the SPA — `private` was dropped there and the whole browser half of the feature was inert while the server
// was perfectly correct, which is exactly what made it look like it worked. Behavioural, not a grep: build a peer.
{
  const { reconcile } = await import(pathToFileURL(path.join(ROOT, "reconcile.js")).href);
  const _rec = reconcile({ version: 1, users: { alice: { name: "Alice" } },
    peers: { pv: { id: "pv", user_id: "alice", pubkey: "k", private: true, targets: [] },
             pn: { id: "pn", user_id: "alice", pubkey: "k2", targets: [] } } }, {});
  const got = id => (_rec.peers || []).find(x => x.id === id) || {};
  check("⚠️ a private peer reaches the SPA as private", got("pv").private === true, got("pv").private);
  check("…and an ordinary one as not private, never undefined", got("pn").private === false, got("pn").private);
}

console.log("\n[4c] the browser READS the flag — not just receives it");
// ⚠️ [4a] proves `private` ARRIVES. Nothing proved anything acted on it: deleting the private branch from peerAudience,
// or `|| p.private` from the reach loop, left the whole board green. Both mutations produce a confident wrong answer —
// the Networks window naming an audience share_grants refuses, and the SPA telling Bob he reaches Alice's private device.
{
  // ⚠️ THE NODE HAS TO BE ABLE TO ENFORCE for "private" to mean anything on the wire. Private is applied where the node
  // guards, not before: on a box too old to restrict, or one not reporting, everything on that subnet still reaches the
  // device, and saying otherwise claims an isolation it does not have.
  const keepRecon = Store.recon, keepStats = Store.stats, keepMeta = Store.ifaceMeta;
  Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };
  Store.stats = { n1: { net_deps: { reach: 2 } }, n9: { net_deps: { reach: 2 } } };
  // ⚠️ THE INTERFACE MUST ALLOW BOB IN, or "private hides it from Bob" passes for the wrong reason: Alice shares no group
  // with Bob, so at "user" he could not reach her devices anyway and deleting the private test entirely stayed green.
  // At Everyone the ONLY thing standing between Bob and this device is the flag, which is what the check is about.
  Store.ifaceMeta = () => ({ reach: "everyone" });
  const a = V.peerAudience(peer("apriv"));
  check("⚠️ a private device's audience is its OWNER ALONE, whatever its stored share says",
        a.mode === "owner" && (a.owner || {}).id === "alice", a);
  check("…so the grantee it was shared with is not named", !(a.users || []).some(u => u.id === "bob"), (a.users || []).map(u => u.id));
  check("…and neither is the group", !(a.groups || []).length, a.groups);
  check("⚠️ and nobody else is told they reach it", !V.userReach("bob").some(r => r.devices.some(d => d.peer.id === "apriv")),
        V.userReach("bob").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
  check("…while its owner still reaches their own device", V.userNets("alice").some(n => n.peer.id === "apriv"),
        V.userNets("alice").map(n => n.peer.id));
  check("⚠️ a grantee's pre-answer count does NOT include it — the chip must not flicker down when the panel replies",
        !V.userNets("bob").some(n => n.peer.id === "apriv"), V.userNets("bob").map(n => n.peer.id));
  check("⚠️ and the group it was shared with is granted nothing by it",
        !V.groupShares("fam").some(p => p.id === "apriv"), V.groupShares("fam").map(p => p.id));
  // ⚠️ THE HONEST DIRECTION, and the one the rule in this file demands: where the node CANNOT enforce, the device really
  // is reachable, and the bubble has to say so. Private was applied before the node's capability was consulted, so a box
  // too old to restrict reported the device as reached by nobody while everything on its subnet still reached it.
  Store.stats = { n1: { net_deps: { reach: 1 } }, n9: { net_deps: { reach: 2 } } };
  Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };   // new identity: userReach is memoised per poll
  check("⚠️ on a node that CANNOT enforce, a private device is reported as reachable — no isolation is claimed for it",
        V.userReach("bob").some(r => r.devices.some(d => d.peer.id === "apriv")),
        V.userReach("bob").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
  // ⚠️ And one level up: a PROMOTED interface is still Everyone for every device on it but the private ones — the node
  // passes the rest of the subnet (qualification 1.8.7 §N10, where guarding the rest measured cutting everyone else off).
  // The first shape read a promoted interface as "user", so the bubble told a group-less stranger they reached nothing
  // there while the node still let them in.
  Store.stats = { n1: { net_deps: { reach: 2 } }, n9: { net_deps: { reach: 2 } } };
  const keepN = Store.nodes;
  Store.nodes = [{ id: "n1", name: "node-one", reach_promoted: ["wg0"] }, { id: "n9", name: "node-nine" }];
  Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };
  check("⚠️ on a PROMOTED interface a stranger still reaches the devices that are not private",
        V.userReach("bob").some(r => r.user.id === "alice" && r.devices.some(d => d.peer.id === "a2")),
        V.userReach("bob").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
  check("…and still not the private one", !V.userReach("bob").some(r => r.devices.some(d => d.peer.id === "apriv")),
        V.userReach("bob").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
  Store.nodes = keepN;
  Store.recon = keepRecon; Store.stats = keepStats; Store.ifaceMeta = keepMeta;
}

console.log("\n[4d] promoted — the panel's verdict, read rather than derived");
// A private device gives its Everyone interface a table, so a refused or skipped reload there has to be reportable and the
// device that caused it nameable. The PANEL decides and publishes it; this proves the browser reads that verdict.
{
  const keepNodes = Store.nodes;
  Store.nodes = [{ id: "n1", name: "node-one", reach_promoted: ["wg0"] }, { id: "n9", name: "node-nine" }];
  check("⚠️ an interface the panel says is promoted reads as promoted", V.promotedAt("n1", "wg0") === true);
  check("…and one it does not name does not", V.promotedAt("n1", "wgX") === false && V.promotedAt("n9", "wg0") === false);
  check("⚠️ nothing exports a level that turns a promoted Everyone interface into a guarded one — that was the first shape",
        typeof V.effectiveLevel === "undefined");
  check("⚠️ and the devices that caused it can be named — otherwise a subnet goes quiet with nothing to act on",
        V.promotedBy("n1", "wg0").map(p => p.id).join() === "apriv", V.promotedBy("n1", "wg0").map(p => p.id));
  check("…naming only devices the panel can vouch for, and only live ones",
        !V.promotedBy("n1", "wg0").some(p => p.disabled || p.expired || !Store.user(p.user_id)));
  Store.nodes = keepNodes;
}

console.log("\n[4b] privateUnenforced — where the Private switch promises something the node cannot keep");
// ⚠️ THERE IS NO PROMOTION WARNING ANY MORE, because there is no cost to warn about: an Everyone interface with a private
// device passes everything on it but that device. What the sheet must still say is where the device is NOT protected.
Store.nodes = [{ id: "n1", name: "node-one" }, { id: "n9", name: "node-nine" }];
Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };
Store.stats = { n1: { net_deps: { reach: 2 } }, n9: { net_deps: { reach: 2 } } };
Store.ifaceMeta = (node, iface) => (node === "n1" && iface === "wg0" ? { reach: "everyone" } : { reach: "user" });
check("⚠️ nothing exports the old promotion warning", typeof V.privatePromotes === "undefined");
check("a device on an Everyone interface of a node that enforces is protected — nothing to say",
      V.privateUnenforced(peer("b1")).length === 0, V.privateUnenforced(peer("b1")));
Store.stats = { n1: { net_deps: { reach: 1 } } };
check("⚠️ a node too old to enforce is named once, as too old",
      JSON.stringify(V.privateUnenforced(peer("b1"))) === JSON.stringify([{ node: "n1", why: "old" }]), V.privateUnenforced(peer("b1")));
Store.stats = { n1: { net_deps: { reach: 2 } }, n9: { net_deps: { reach: 2 } } };
check("⚠️ a device with no user on an Everyone interface is named — the node guards by owner and has none to use",
      (r => r.length === 1 && r[0].why === "no_user" && r[0].iface === "wg0")(V.privateUnenforced({ ...peer("b1"), user_id: null })),
      V.privateUnenforced({ ...peer("b1"), user_id: null }));
check("…and so is one whose user was deleted", (r => r.length === 1 && r[0].why === "no_user")(V.privateUnenforced({ ...peer("b1"), user_id: "deleted-owner" })));
check("a BLOCKED device is named nowhere — it is off the node", V.privateUnenforced({ ...peer("b1"), disabled: true }).length === 0);
{
  const keepN = Store.nodes;
  Store.nodes = [{ id: "n1", name: "node-one", reach_unvouched: ["wg0"] }, { id: "n9", name: "node-nine" }];
  check("⚠️ a device on a build that can't prove its address, at Everyone, is named — nothing guards it there",
        (r => r.length === 1 && r[0].why === "unvouched")(V.privateUnenforced(peer("b1"))), V.privateUnenforced(peer("b1")));
  Store.ifaceMeta = () => ({ reach: "user" });
  check("…but not at \"user\", where that build makes every device there Nobody and the promise holds",
        V.privateUnenforced(peer("b1")).length === 0, V.privateUnenforced(peer("b1")));
  Store.ifaceMeta = () => ({ reach: "everyone" });
  Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };
  check("⚠️ and an unvouched build at Everyone is NOT read as Nobody — the bubble must not hide devices everyone reaches",
        V.userReach("bob").some(r => r.user.id === "alice" && r.devices.some(d => d.peer.id === "a2")),
        V.userReach("bob").map(r => [r.user.id, r.devices.map(d => d.peer.id)]));
  Store.nodes = keepN;
}
console.log("\n[4e] privateOffOpens — what saving Private OFF opens, device and networks apart");
{
  const keepMeta = Store.ifaceMeta, keepStats = Store.stats, keepRecon = Store.recon;
  Store.recon = { peers, users, nodeStatus: { n1: "live", n9: "live" } };
  Store.stats = { n1: { net_deps: { reach: 2 } }, n9: { net_deps: { reach: 2 } } };
  Store.ifaceMeta = () => ({ reach: "everyone" });
  const o = V.privateOffOpens(peer("apriv"));
  check("⚠️ on an Everyone interface the DEVICE opens to everyone on its node", JSON.stringify(o.everyoneAt) === '["n1"]', o.everyoneAt);
  check("⚠️ …and the NETWORKS open to the stored share, which Private was overriding — not to its owner alone",
        o.nets && o.nets.mode === "shared" && o.nets.users.some(u => u.id === "bob") && o.nets.groups.some(g => g.name === "Family"),
        o.nets && [o.nets.mode, o.nets.users.map(u => u.id), o.nets.groups.map(g => g.name)]);
  Store.ifaceMeta = () => ({ reach: "user" });
  const u = V.privateOffOpens(peer("apriv"));
  check("on a \"user\" interface the device is NOT said to open to everyone", u.everyoneAt.length === 0, u.everyoneAt);
  const noShare = V.privateOffOpens({ ...peer("apriv"), share: null });
  check("⚠️ with no share the networks open to everyone — while the device, on \"user\", still does not",
        noShare.nets && noShare.nets.mode === "everyone" && noShare.everyoneAt.length === 0, [noShare.nets && noShare.nets.mode, noShare.everyoneAt]);
  check("a device with no networks says nothing about networks", V.privateOffOpens({ ...peer("apriv"), routes: [] }).nets === null);
  Store.stats = { n1: { net_deps: { reach: 1 } } };
  check("a node that cannot enforce opens the device to everyone there, whatever the interface says",
        JSON.stringify(V.privateOffOpens(peer("apriv")).everyoneAt) === '["n1"]', V.privateOffOpens(peer("apriv")).everyoneAt);
  Store.ifaceMeta = keepMeta; Store.stats = keepStats; Store.recon = keepRecon;
}
// ⚠️ ifaceLevelOf reads WDTT/csqtt levels from the node's instance records, not from the interface meta.
{
  const keepN = Store.nodes, keepMeta = Store.ifaceMeta;
  Store.nodes = [{ id: "n1", name: "node-one", wdtt_cfg: { wdtt1: { reach: "everyone" } }, reach_unvouched: ["wdtt1"] }, { id: "n9", name: "node-nine" }];
  Store.ifaceMeta = () => ({ reach: "user" });               // the meta says "user"; the instance record must win
  const kp = { id: "kw", user_id: "bob", targets: [{ node: "n1", iface: "wdtt1", ip: "10.77.0.2" }] };
  check("⚠️ a WDTT instance at Everyone is read from its instance record",
        (r => r.length === 1 && r[0].iface === "wdtt1" && r[0].why === "unvouched")(V.privateUnenforced(kp)), V.privateUnenforced(kp));
  Store.nodes = keepN; Store.ifaceMeta = keepMeta;
}
Store.ifaceMeta = () => ({ reach: "user" });
check("a device with no deployments is named nowhere", V.privateUnenforced({ id: "z", user_id: "bob", targets: [] }).length === 0);

console.log("\n[5] askSig / askFresh — one rule for everything asked of the panel");
// ⚠️ THE SIGNATURE ITSELF, not just the === around it. This started as `askFresh({sig: askSig()})` compared against
// askSig() — which passes for ANY signature, including a constant one that never invalidates. What has to hold is that
// each thing the panel's answer depends on MOVES the signature; a mutation to the signature's content must be caught.
const sig0 = V.askSig();
const bump = () => { Store.recon = { peers, users, nodeStatus: {} }; return V.askSig(); };   // new identity = recompute
const moves = (what, mutate) => {
  const before = bump();
  mutate();
  check("⚠️ the signature moves when " + what, bump() !== before, [before.length, "chars"]);
};
check("a signature is not empty, and is stable while nothing changes", !!sig0 && bump() === V.askSig(), sig0.slice(0, 40));
moves("a device's ROUTES change", () => { peer("gw").routes = ["192.168.50.0/24", "10.10.0.0/16"]; });
moves("a network's SHARING changes", () => { peer("gw").share.users.bob = NOW + 99 * DAY; });
// ⚠️ BOTH DIRECTIONS, and on a device that carries networks AND one that does not — the flag is the first thing
// share_grants reads, so it changes every grantee's answer, and it lives on both branches of the signature. Without it
// the chip and both bubbles served the pre-Private answer for the whole 5-minute backstop, in either direction.
moves("a provider is made PRIVATE", () => { peer("gw").private = true; });
moves("…and when it stops being private again", () => { peer("gw").private = false; });
moves("a device that carries NO networks is made private", () => { peer("b1").private = true; });
moves("a provider is BLOCKED", () => { peer("b1").private = false; peer("gw").disabled = true; });
moves("a provider EXPIRES", () => { peer("gw").disabled = false; peer("gw").expired = true; });
moves("a device is DEPLOYED somewhere new", () => { peer("gw").expired = false; peer("gw").targets.push(T("n9", "10.9.0.77")); });
moves("GROUP MEMBERSHIP changes", () => { Store.roster = { ...Store.roster, groups: { fam: { name: "Family", users: ["bob"] } } }; });
moves("a node's LAN switch changes", () => { Store.nodes = [{ id: "n1", name: "node-one", lan_share: false }, { id: "n9", name: "node-nine" }]; });
moves("a node's ability to RESTRICT changes", () => { Store.nodes = [{ id: "n1", name: "node-one", lan_share: false, net_capable: true }, { id: "n9", name: "node-nine" }]; });
moves("the panel-wide LAN setting changes", () => { Store.panelSettings = { show_node_lans: false }; });
const sig = V.askSig();
check("an answer tagged with the current signature is fresh", V.askFresh({ sig, at: Date.now() }));
check("⚠️ an answer from a different signature is not", !V.askFresh({ sig: sig + "x", at: Date.now() }));
check("⚠️ and neither is one older than the backstop, however unchanged the inputs",
      !V.askFresh({ sig, at: Date.now() - 6 * 60 * 1000 }));
check("⚠️ a backstop long enough to matter — a 1 s TTL would hammer an on-demand endpoint every render",
      V.askFresh({ sig, at: Date.now() - 60 * 1000 }), "one minute old must still be fresh");
check("nothing cached is never fresh", !V.askFresh(null) && !V.askFresh(undefined));
check("⚠️ a bare number is not a cache entry — that shape shipped once and read back as undefined", !V.askFresh(4));

done(PERTURB, "a grantee's devices counted fleet-wide instead of per node");
