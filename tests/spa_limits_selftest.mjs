/* Self-test: speed limits in the browser (docs/LIMITS-PLAN.md, limits-l3) — js/limits.js, the whitelists that carry `limits`
 * into the SPA, and the four editors' doors.
 *
 * [1] the draft: limFromDraft / limDraft / limSame agree with the panel's limits_clean (1..100000, {d,u} or {c}, blank = none)
 * [2] carried: reconcile.js keeps `limits` on a target, a peer and a user, Store.groups() on a group — each a whitelist that
 *     would otherwise drop it, and the editors would open empty on a stored limit and a Save would clear it
 * [3] precedence: for every user, userLimit() names the same limit and pool as the panel's own _lim_index on the same roster
 *     (two limited groups → the lower; a tie → the lower group id; a user's own beats a group's), and effLimit() takes a
 *     deployment's own, then the device's, then the user's
 * [4] read-outs: limText follows the panel's throughput perspective (u is the rx side), the editor's words are the device's;
 *     held at a limit from the device's download (tx) and upload (rx), a pool held by its members' SUM on that node
 * [5] where a limit is not enforced: a live node without net_deps.limits, never a stale one; limit_err as node issues
 * [6] the doors (read as shipped): each editor sends `limits` only when it changed, a deployment's through update-target only;
 *     Peer targets says a removed row takes its own limit with it (R7); the node's issues badge reads limit_err
 * [7] Russian: every string js/limits.js and the doors say has a Russian line
 *
 * Run: node tests/spa_limits_selftest.mjs     --perturb lowest|persp|heldsum|rcarry|gcarry|gapkey|usersend|tgtdoor|r7|clean
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, spa, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {   // name: [file, anchor, replacement]
  lowest: ["js/limits.js", "if (l && (!out || lower(l, out.lim))) out = { lim: l, src: \"group\", name: g.name, gid: g.id", "if (l && (!out || !lower(l, out.lim))) out = { lim: l, src: \"group\", name: g.name, gid: g.id"],   // [3]
  persp: ["js/limits.js", "const [dn, up] = dlul(l.u || 0, l.d || 0);", "const [dn, up] = [l.d || 0, l.u || 0];"],                                   // [4]
  heldsum: ["js/limits.js", "const k = t.node + \"|\" + e.pool, a =", "const k = t.node + \"|\" + e.pool + p.id, a ="],                               // [4]
  clean: ["js/limits.js", "  return ks.every(k => okRate(raw[k])) ? raw : null;", "  return raw;"],                                                       // [1]
  gapkey: ["js/limits.js", "if (!(((Store.stats[t.node] || {}).net_deps || {}).limits)) old.add(t.node);", "if (!(((Store.stats[t.node] || {}).net_deps || {}).reach)) old.add(t.node);"],   // [5]
  rcarry: ["reconcile.js", "               limits: t.limits || null,", "               limits: null,"],                                                  // [2]
  gcarry: ["js/store.js", "                      limits: g[id].limits || null }))", "                      limits: null }))"],                         // [2]
  usersend: ["js/peer-ui.js", "expiry: expSec, ...(limits ? { limits } : {}) }), setSaveErr, setBusy);", "expiry: expSec }), setSaveErr, setBusy);"],    // [6]
  tgtdoor: ["js/sheets-crud.js", "iface: t.iface, limits: tlims[tkey(t.node, t.iface)] });", "iface: t.iface });"],                                       // [6]
  r7: ["js/sheets-crud.js", "  const limGone = removed.filter(t => limClean(t.limits));", "  const limGone = [];"],                                         // [6]
};
const made = [];
const JS_URL = pathToFileURL(path.join(ROOT, "js") + path.sep).href;
const ROOT_URL = pathToFileURL(ROOT + path.sep).href;
// A planted module is a copy in a directory of its own, its imports pointed at the real modules by absolute URL — never a
// planted file inside js/, one `git add -A` from shipping. So a planted limits.js still shares the real Store.
async function load(file) {
  const abs = path.join(ROOT, file);
  const p = MODE && PLANTS[MODE];
  if (!p || p[0] !== file) return import(pathToFileURL(abs).href);
  const src = fs.readFileSync(abs, "utf8");
  if (src.split(p[1]).length !== 2) { console.log("PERTURB FAILED — anchor missing for " + MODE + ", this run would false-pass"); process.exit(1); }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "spa-limits-")); made.push(dir);
  const base = file.startsWith("js/") ? JS_URL : ROOT_URL;
  const out = path.join(dir, path.basename(file).replace(/\.js$/, ".mjs"));
  fs.writeFileSync(out, src.replace(p[1], p[2]).replace(/(\bfrom\s*)(["'])\.\.\//g, (m, f, q) => f + q + new URL("../", base).href)
                          .replace(/(\bfrom\s*)(["'])\.\//g, (m, f, q) => f + q + base));
  return import(pathToFileURL(out).href);
}
const source = file => {   // a wiring check reads the source as shipped — or as planted
  const s = fs.readFileSync(path.join(ROOT, file), "utf8"), p = MODE && PLANTS[MODE];
  if (p && p[0] === file) { if (s.split(p[1]).length !== 2) { console.log("PERTURB FAILED — anchor missing for " + MODE); process.exit(1); } return s.replace(p[1], p[2]); }
  return s;
};
if (MODE && !PLANTS[MODE]) { console.log("unknown plant " + MODE + " (one of: " + Object.keys(PLANTS).join(", ") + ")"); process.exit(1); }

try {
  const L = await load("js/limits.js");
  const R = await load("reconcile.js");
  const { Store } = await spa("store.js");
  const SP = await load("js/store.js");          // the planted copy when gcarry is planted, else the same module
  const RU = (await spa("lang/ru.js")).STR;

  console.log("\n[1] the draft");
  const fd = d => L.limFromDraft({ mode: "du", d: "", u: "", c: "", ...d });
  check("download and upload → {d, u}", JSON.stringify(fd({ d: "20", u: "5" }).lim) === '{"d":20,"u":5}', fd({ d: "20", u: "5" }));
  check("a blank direction is unlimited", JSON.stringify(fd({ d: "", u: "2,5" }).lim) === '{"u":2.5}', fd({ u: "2,5" }));
  check("both blank asks for a figure", !!fd({}).err && !fd({}).lim);
  check("under 1 and over 100000 are refused", !!fd({ d: "0.5" }).err && !!fd({ d: "100001" }).err && !!fd({ d: "abc" }).err);
  check("combined → {c}", JSON.stringify(L.limFromDraft({ mode: "c", c: "40" }).lim) === '{"c":40}');
  check("no limit → {} (the door clears)", JSON.stringify(L.limFromDraft({ mode: "none" }).lim) === "{}");
  check("a stored limit opens as itself", JSON.stringify(L.limDraft({ d: 8, u: 2 })) === JSON.stringify({ mode: "du", d: "8", u: "2", c: "" })
    && L.limDraft({ c: 40 }).mode === "c" && L.limDraft(null).mode === "none");
  check("key order never reads as a change", L.limSame({ u: 5, d: 20 }, { d: 20, u: 5 }) && L.limSame({}, null) && !L.limSame({ d: 20 }, { d: 21 }));
  check("a stored value the panel would refuse reads as none", L.limClean({ c: 40, d: 2 }) === null && L.limClean({ d: 0 }) === null
    && L.limClean({ d: true }) === null && L.limClean({ x: 5 }) === null && L.limClean({ d: 200000 }) === null, [L.limClean({ c: 40, d: 2 }), L.limClean({ d: 0 })]);

  console.log("\n[2] carried into the browser");
  const now = Math.floor(Date.now() / 1000);
  const tg = (node, lim) => ({ node, iface: "awg0", ip: "10.9.0.2/32", type: "awg", ...(lim ? { limits: lim } : {}) });
  const roster = {
    users: { ua: { name: "anna", limits: { d: 20, u: 5 } }, ub: { name: "boris" }, uc: { name: "carol" }, ud: { name: "dora" }, ue: { name: "erin" }, uf: { name: "fred" } },
    groups: { g1: { name: "Family", users: ["ub", "uc", "ud", "uf"], limits: { c: 40 } }, g2: { name: "Work", users: ["uc", "ua"], limits: { d: 10 } },
              g0: { name: "Tie", users: ["ud"], limits: { c: 40 } } },
    peers: {
      pa: { user_id: "ua", pubkey: "PKA", created_at: now - 9999, targets: [tg("n1")] },
      pb: { user_id: "ub", pubkey: "PKB", created_at: now - 9999, targets: [tg("n1")] },
      pc: { user_id: "uc", pubkey: "PKC", created_at: now - 9999, targets: [tg("n1")] },
      pd: { user_id: "ud", pubkey: "PKD", created_at: now - 9999, targets: [tg("n1")] },
      pt: { user_id: "uc", pubkey: "PKT", created_at: now - 9999, limits: { d: 50 }, targets: [tg("n1", { d: 8, u: 2 }), { ...tg("n2"), ip: "10.9.0.3/32" }] },
      pe: { user_id: "ue", pubkey: "PKE", created_at: now - 9999, targets: [tg("n2")] },
      pf: { user_id: "uf", pubkey: "PKF", created_at: now - 9999, targets: [tg("n1")] },
    },
  };
  const peerObs = (pk, rx, tx) => ({ public_key: pk, allowed_ips: "", rx_bytes: 1, tx_bytes: 1, rx_speed: rx, tx_speed: tx, handshake_age: 5, online: true, endpoint: "198.51.100.9:1" });
  const stats = {
    n1: { generated_at: now, net_deps: { limits: 1, reach: 2 }, limit_err: { awg0: "tc: RTNETLINK answers: Operation not supported", caps: "x" },
          interfaces: { awg0: { meta: {}, peers: [peerObs("PKA", 100000, 2400000), peerObs("PKB", 2000000, 2000000), peerObs("PKC", 0, 0),
                                                 peerObs("PKD", 1000000, 1000000), peerObs("PKT", 0, 0), peerObs("PKF", 250000, 250000)] } } },
    n2: { generated_at: now, net_deps: { reach: 2 }, interfaces: { awg0: { meta: {}, peers: [peerObs("PKT", 0, 0), peerObs("PKE", 0, 0)] } } },
  };
  const rc = R.reconcile(roster, stats, Date.now(), { nodeSeen: { n1: now, n2: now } });
  const pt = rc.peers.find(p => p.id === "pt");
  check("a deployment's own limit reaches the browser", JSON.stringify(pt.targets.find(t => t.node === "n1").limits) === '{"d":8,"u":2}', pt.targets);
  check("…a device's own", JSON.stringify(pt.limits) === '{"d":50}', pt.limits);
  check("…a user's own", JSON.stringify((rc.users.find(u => u.id === "ua") || {}).limits) === '{"d":20,"u":5}');
  check("…and none where none is stored", rc.peers.find(p => p.id === "pb").limits === null && rc.users.find(u => u.id === "ub").limits === null);
  SP.Store.roster = roster;
  check("a group's limit, through Store.groups()", JSON.stringify((SP.Store.groups().find(g => g.id === "g1") || {}).limits) === '{"c":40}', SP.Store.groups());

  // the real Store, as the screens hold it
  Store.roster = roster; Store.stats = stats; Store.recon = rc;
  Store.panelSettings = {};

  console.log("\n[3] precedence, against the panel's own");
  const env = { ...process.env, SWG_NO_REEXEC: "1" };
  const py = `
import importlib.machinery, importlib.util, json, sys
ld = importlib.machinery.SourceFileLoader("swgp", sys.argv[1]); m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgp", ld))
try: ld.exec_module(m)
except SystemExit: pass
li = m._lim_index(json.loads(sys.stdin.read()))
print(json.dumps({u: [l, p] for u, (l, p) in li["user"].items()}))`;
  const srv = JSON.parse(execFileSync("python3", ["-c", py, path.join(ROOT, "swg-panel-server")], { input: JSON.stringify(roster), env }).toString());
  for (const uid of Object.keys(roster.users)) {
    const b = L.userLimit(uid), s = srv[uid];
    check("user " + roster.users[uid].name + ": the panel's limit and pool", JSON.stringify(b ? [b.lim, b.pool] : null) === JSON.stringify(s || null), [b && [b.lim, b.pool], s]);
  }
  const e = (pid, node) => { const p = rc.peers.find(x => x.id === pid); return L.effLimit(p, p.targets.find(t => t.node === node)); };
  check("a deployment's own limit wins", e("pt", "n1").src === "deployment" && e("pt", "n1").lim.d === 8);
  check("…else the device's", e("pt", "n2").src === "device" && e("pt", "n2").lim.d === 50);
  check("…else the user's lowest group, named", e("pc", "n1").src === "group" && e("pc", "n1").name === "Work", e("pc", "n1"));
  check("…and nothing for a user with none", e("pe", "n2") === null);
  check("the fallback a device would get without its own", (L.fallbackFor("device", { user_id: "uc" }) || {}).name === "Work");
  check("…a deployment: the device's", (L.fallbackFor("deployment", pt.targets[0], pt) || {}).src === "device");

  console.log("\n[4] read-outs");
  check("limText, the server's perspective: ↓ is what the node receives (u)", L.limText({ d: 20, u: 5 }) === "↓ 5 ↑ 20 Mbit/s", L.limText({ d: 20, u: 5 }));
  Store.panelSettings = { throughput_perspective: "peers" };
  check("…the peers' perspective: ↓ is the device's download (d)", L.limText({ d: 20, u: 5 }) === "↓ 20 ↑ 5 Mbit/s", L.limText({ d: 20, u: 5 }));
  Store.panelSettings = {};
  check("the editor's words are the device's", L.limWords({ d: 20, u: 5 }) === "download 20, upload 5 Mbit/s", L.limWords({ d: 20, u: 5 }));
  const held = (pid, node) => { const p = rc.peers.find(x => x.id === pid); return L.limitHeld(p, p.targets.find(t => t.node === node)); };
  check("anna downloading 19.2 Mbit/s against 20 down is held", !!held("pa", "n1"));
  check("dora, alone in her pool (the tie went to group Tie) at 16 of 40 combined, is not", !held("pd", "n1"));
  check("boris (32) + fred (4) on Family's one 40 Mbit pool: both held, though neither alone is", !!held("pb", "n1") && !!held("pf", "n1"));
  check("carol, quiet in her own pool (Work), is not", !held("pc", "n1"));

  console.log("\n[5] where a limit is not enforced");
  const gaps = L.limitGaps(pt.targets);
  check("a live node without net_deps.limits", JSON.stringify(gaps.old) === '["n2"]', gaps);
  rc.nodeStatus.n2 = "stale";
  check("…never a stale one", L.limitGaps(pt.targets).old.length === 0);
  rc.nodeStatus.n2 = "live";
  const iss = L.limitIssues("n1");
  check("limit_err reads as node issues, one a key", iss.length === 2 && iss[0].includes("awg0") && iss[0].includes("Operation not supported") && iss[1].includes("caps"), iss);
  check("…none without it", L.limitIssues("n2").length === 0);

  console.log("\n[6] the doors, as shipped");
  const pu = source("js/peer-ui.js"), sc = source("js/sheets-crud.js"), sn = source("js/screen-nodes.js");
  const has = (what, s, needle) => check(what, s.includes(needle), needle);
  has("the user editor opens on the stored limit", pu, "const lim = useLimit(user.limits);");
  has("…sends it only when it changed", pu, "const limits = lim.changed ? lim.take() : undefined;");
  has("…in the users/update body", pu, "expiry: expSec, ...(limits ? { limits } : {}) }), setSaveErr, setBusy);");
  has("…and a change enables Save", pu, "|| lim.changed;");
  has("the group editor: an existing group's limit, sent when it changed", pu, "remove, ...(limits ? { limits } : {}) })");
  has("…a change marks it dirty", pu, "|| (!!gid && lim.changed);");
  has("Edit peer: the device's limit through peers/update", sc, "const r = await api.peerUpdate({ peer_id: peer.id, limits });");
  has("…a deployment's through update-target only, when staged and changed", sc, "if (!tlimChanged(t)) continue;\n        const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, limits: tlims[tkey(t.node, t.iface)] });");
  has("…either change enables Save", sc, "|| lim.changed || (live.targets || []).some(tlimChanged);");
  has("Peer targets: R7, a removed row's own limit is named", sc, "  const limGone = removed.filter(t => limClean(t.limits));");
  check("…and its notice is drawn", sc.includes("${limGone.length ? html`<div class=\"notice warn\">"));
  has("the node's issues badge reads limit_err", sn, "<${HealthDot} issues=${nrec.issues} i18n=${nrec.issues_i18n} nid=${nrec.id}/>");
  check("noded says it loads limits", fs.readFileSync(path.join(ROOT, "swg-noded"), "utf8").includes('"reach": 2, "limits": 1}'));

  console.log("\n[7] Russian");
  const keys = new Set();
  for (const f of ["js/limits.js"]) for (const m of fs.readFileSync(path.join(ROOT, f), "utf8").matchAll(/\bT\("((?:[^"\\]|\\.)+)"/g)) keys.add(m[1]);
  for (const k of ["The gauge sets that deployment's own speed limit.", "col|Speed limit",
                   "Removing {target} removes its own speed limit. Deployed again, it follows the device's limit.",
                   "Removing {targets} removes their own speed limits. Deployed again, they follow the device's limit.",
                   "This deployment's own speed limit: {lim}", "Saving removes this deployment and its own speed limit ({lim})."]) keys.add(k);
  const missing = [...keys].filter(k => typeof RU[k] !== "string" || !RU[k]);
  check("a Russian line for each of " + keys.size + " strings", missing.length === 0, missing);
} finally {
  for (const d of made) fs.rmSync(d, { recursive: true, force: true });
}
done(!!MODE, MODE);
