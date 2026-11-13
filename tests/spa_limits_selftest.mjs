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
 *     held at a limit from the device's download (tx) and upload (rx); a shared pool's member at ITS share (the limit ÷ the
 *     members moving, as the node caps it), never by another's traffic; never a WDTT / csqtt deployment, never where the limit
 *     does not hold; the Live grid tints the held direction only
 * [5] where a limit is not enforced: a live node without net_deps.limits, never a stale one; a keyless build vouched for no
 *     path, or for WireGuard but not RAW, once per interface; limit_err as the panel's node issues, a sentence per kind
 * [6] the doors (read as shipped): each editor sends `limits` only when the operator changed it (never a later poll's copy),
 *     a deployment's through update-target only; Edit peer and Edit user guard a changed limit on close; the gauge is not the
 *     gear; Peer targets says a removed row takes its own limit with it (R7)
 * [7] Russian: every string js/limits.js, the doors and the node issues say has a Russian line
 * [8] volume limits (limits-l4): the draft in GB → bytes as volume_clean takes it, a thousands separator refused; the device's
 *     volume carried; /api/state's `vol` read as expired (with its reason) for a device and its owner's other devices; review
 *     limits-l4: a slowed device's limit in force is 1 Mbit/s in one pool for its person (Live's "held", the peer view), a date
 *     passed is the reason before a volume cut, the status lines say a volume cut, the group editor stops on a bad volume, the
 *     used line asks for the drafted period and only with a limit drafted
 * [9] the Limits button and sheet (limits-l5): in both QR footers; the button counts what is set (expiry, speed, volume) and says
 *     cut off / slowed / set; the sheet sends only what changed and its Close goes through the discard guard
 *
 * Run: node tests/spa_limits_selftest.mjs     --perturb lowest|persp|heldsum|share|keyheld|rcarry|kcarry|gcarry|gapkey|rawgap|
 *                                              sep|seed|usersend|tgtdoor|dirty|r7|issues|crash|volcut|volcarry|volgb|clean|
 *                                              slowlim|volreason|substate|groupguard|usedperiod|usedown|
 *                                              limscut|limsn|limsguard|limsexp|limsfoot|limsowner|limsclean|limswhy|limsnoname
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
  heldsum: ["js/limits.js", "const k = t.node + \"|\" + e.pool;", "const k = t.node + \"|\" + e.pool + p.id;"],                                     // [4]
  share: ["js/limits.js", "mine >= HELD_AT * lim / Math.max(1, mem.filter(m => of(m) >= lim * 0.01).length);", "mem.reduce((a, m) => a + of(m), 0) >= HELD_AT * lim;"],   // [4]
  keyheld: ["js/limits.js", "  if (!t || isSelfContainedTgt(t) || gapOf(t)) return null;", "  if (!t) return null;"],                                         // [4]
  clean: ["js/limits.js", "  return ks.every(k => okRate(raw[k])) ? raw : null;", "  return raw;"],                                                       // [1]
  gapkey: ["js/limits.js", "if (!(((Store.stats[t.node] || {}).net_deps || {}).limits)) return \"old\";", "if (!(((Store.stats[t.node] || {}).net_deps || {}).reach)) return \"old\";"],   // [5]
  rawgap: ["js/limits.js", ": (nr.reach_unvouched_raw || []).includes(t.iface) ? \"raw\" : null;", ": null;"],                                           // [5]
  rcarry: ["reconcile.js", "limits: t.limits || null,   // THIS deployment's own", "limits: null,   // THIS deployment's own"],                                                  // [2]
  kcarry: ["reconcile.js", "                 limits: t.limits || null,   // its own speed limit (R7)", "                 limits: null,   // its own speed limit (R7)"],   // [2]
  sep: ["js/limits.js", "SEP_RE.test(s) ? \"sep\" :", "false ? \"sep\" :"],                                                                             // [1]
  seed: ["js/limits.js", "!limSame(out.lim, limFromDraft(seed).lim)", "!limSame(out.lim, stored)"],                                                        // [6]
  gcarry: ["js/store.js", "limits: g[id].limits || null, volume: g[id].volume || null }))", "limits: null, volume: g[id].volume || null }))"],                         // [2]
  usersend: ["js/peer-ui.js", "expiry: expSec, ...(limits ? { limits } : {}), ...(volume ? { volume } : {}) }), setSaveErr, setBusy);", "expiry: expSec, ...(volume ? { volume } : {}) }), setSaveErr, setBusy);"],    // [6]
  tgtdoor: ["js/sheets-crud.js", "iface: t.iface, limits: tlims[tkey(t.node, t.iface)] });", "iface: t.iface });"],                                       // [6]
  dirty: ["js/sheets-crud.js", "    dirtyRef=${{ current: lim.changed || vol.changed || (live.targets || []).some(tlimChanged) }}", "    dirtyRef=${{ current: false }}"],   // [6]
  r7: ["js/sheets-crud.js", "  const limGone = removed.filter(t => limClean(t.limits));", "  const limGone = [];"],                                         // [6]
  issues: ["swg-panel-server", "    for _k in (sorted(_le) if isinstance(_le, dict) else ()):", "    for _k in ():"],                                        // [5]
  volcut: ["reconcile.js", "|| (!!vol && vol[pid] === \"cut\");", ";"],                                                                         // [8]
  volcarry: ["reconcile.js", "      volume: p.volume || null,", "      volume: null,"],                                                                  // [8]
  volgb: ["js/limits.js", "    out[k] = Math.round(v * GB);", "    out[k] = Math.round(v);"],                                                           // [8]
  slowlim: ["js/limits.js", "return !sk || (e && !lower(SLOW, e.lim)) ? e :", "return true ? e :"],                                          // [8]
  volreason: ["reconcile.js", "reason = selfDate ? T(\"this peer's access date has passed\") : userDate ?", "reason = (cfg.vol || {})[pid] === \"cut\" ? T(\"its volume limit is used up\") : selfDate ? T(\"this peer's access date has passed\") : userDate ?"],   // [8]
  substate: ["js/peer-actions.js", "  if (volCut(u.id)) return { cls: \"s-expired\", text: T(\"Cut off: the volume limit is used up\") };\n  if (exp && now >= exp - expiryWarnDays() * DAY_S) return { cls: \"s-expiring\", text: T(\"Subscription", "  if (exp && now >= exp - expiryWarnDays() * DAY_S) return { cls: \"s-expiring\", text: T(\"Subscription"],   // [8]
  groupguard: ["js/peer-ui.js", "    const volume = gid && vol.changed ? vol.take() : undefined;\n    if (limits === null || volume === null) return;", "    const volume = gid && vol.changed ? vol.take() : undefined;\n    if (limits === null) return;"],   // [8]
  usedperiod: ["js/limits.js", " + \"&period=\" + period)", ")"],                                                                   // [8]
  usedown: ["js/limits.js", "${id && own ? html`<${UsedLine}", "${id ? html`<${UsedLine}"],                                                     // [8]
  limscut: ["js/peer-ui.js", "  const cut = !!(exp && now >= exp) || !!(oexp && now >= oexp) || ids.some(i => v[i] === \"cut\");", "  const cut = !!(exp && now >= exp) || !!(oexp && now >= oexp);"],   // [9]
  limsowner: ["js/peer-ui.js", "  const ids = [rec.id, ...(owner ? [owner.id] : [])];", "  const ids = [rec.id];"],   // [9]
  limsnoname: ["js/peer-ui.js", "owner: owner ? owner.name || T(\"lim|its owner\") : \"\",", "owner: owner ? owner.name || \"\" : \"\","],   // [9]
  limswhy: ["js/peer-ui.js", ": owner && v[owner.id] === \"cut\" ? \"ovol\" : v[rec.id] === \"slow\" ? \"slow\" : slow ? \"oslow\" : \"\";", ": owner && v[owner.id] === \"cut\" ? \"vol\" : v[rec.id] === \"slow\" ? \"slow\" : slow ? \"slow\" : \"\";"],   // [9]
  limsclean: ["js/peer-ui.js", "  useEffect(() => { if (!dirtyRef.current && cleanRef.current) cleanRef.current(); });", ""],   // [9]
  limsn: ["js/peer-ui.js", "  const n = (exp ? 1 : 0) + (limClean(rec.limits) ? 1 : 0) + (volClean(rec.volume) ? 1 : 0);", "  const n = exp ? 1 : 0;"],   // [9]
  limsguard: ["js/peer-ui.js", "foot=${footRow({ onCancel: () => (closeRef.current ? closeRef.current() : closeModal()), cancelLabel: T(\"Close\"),", "foot=${footRow({ onCancel: closeModal, cancelLabel: T(\"Close\"),"],   // [9]
  limsexp: ["js/peer-ui.js", "const body = { ...(expChanged ? { expiry: sec } : {}),", "const body = { expiry: sec,"],   // [9]
  limsfoot: ["js/peer-ui.js", "<span class=\"grow\"></span><${LimitsButton} kind=\"user\" id=${uid} rec=${u}/>", "<span class=\"grow\"></span>"],   // [9]
  crash: ["swg-panel-server", "\"cut\", v1=_w) if _k == \"exception\" else", "\"cut\", v1=_w) if _k == \"exception!\" else"],                         // [5]
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
  const RUKEYS = new Set();

  console.log("\n[1] the draft");
  const fd = d => L.limFromDraft({ mode: "du", d: "", u: "", c: "", ...d });
  check("download and upload → {d, u}", JSON.stringify(fd({ d: "20", u: "5" }).lim) === '{"d":20,"u":5}', fd({ d: "20", u: "5" }));
  check("a blank direction is unlimited", JSON.stringify(fd({ d: "", u: "2,5" }).lim) === '{"u":2.5}', fd({ u: "2,5" }));
  check("both blank asks for a figure", !!fd({}).err && !fd({}).lim);
  check("under 1 and over 100000 are refused", !!fd({ d: "0.5" }).err && !!fd({ d: "100001" }).err && !!fd({ d: "abc" }).err);
  check("a thousands separator is refused, never read as a decimal point (\"1,000\" is not 1)", !!fd({ d: "1,000" }).err && !fd({ d: "1,000" }).lim
    && /thousands/.test(fd({ u: "2,500" }).err || "") && JSON.stringify(fd({ d: "1,5" }).lim) === '{"d":1.5}', [fd({ d: "1,000" }), fd({ d: "1,5" })]);
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
    users: { ua: { name: "anna", limits: { d: 20, u: 5 } }, ub: { name: "boris" }, uc: { name: "carol" }, ud: { name: "dora" }, ue: { name: "erin" }, uf: { name: "fred" },
             ug: { name: "gina" } },
    groups: { g1: { name: "Family", users: ["ub", "uc", "ud", "uf"], limits: { c: 40 } }, g2: { name: "Work", users: ["uc", "ua", "ug"], limits: { d: 10 } },
              g0: { name: "Tie", users: ["ud"], limits: { c: 40 } } },
    peers: {
      pa: { user_id: "ua", pubkey: "PKA", created_at: now - 9999, targets: [tg("n1")] },
      pb: { user_id: "ub", pubkey: "PKB", created_at: now - 9999, targets: [tg("n1")] },
      pc: { user_id: "uc", pubkey: "PKC", created_at: now - 9999, targets: [tg("n1")] },
      pd: { user_id: "ud", pubkey: "PKD", created_at: now - 9999, targets: [tg("n1")] },
      pt: { user_id: "uc", pubkey: "PKT", created_at: now - 9999, limits: { d: 50 }, targets: [tg("n1", { d: 8, u: 2 }), { ...tg("n2"), ip: "10.9.0.3/32" }] },
      pe: { user_id: "ue", pubkey: "PKE", created_at: now - 9999, targets: [tg("n2")] },
      pf: { user_id: "uf", pubkey: "PKF", created_at: now - 9999, targets: [tg("n1")] },
      pg: { user_id: "ug", pubkey: "PKG", created_at: now - 9999, targets: [tg("n1")] },
      pk: { user_id: "ue", pubkey: "", csqtt_password: "CPW", created_at: now - 9999, targets: [{ node: "n1", iface: "csqtt0", type: "csqtt", limits: { c: 5 } }] },
      pw: { user_id: "ue", pubkey: "", wdtt_password: "WPW", created_at: now - 9999, targets: [{ node: "n1", iface: "wdtt1", type: "wdtt" }] },
      pw2: { user_id: "ue", pubkey: "", wdtt_password: "WPW2", created_at: now - 9999, targets: [{ node: "n1", iface: "wdtt1", type: "wdtt" }] },
    },
  };
  const peerObs = (pk, rx, tx) => ({ public_key: pk, allowed_ips: "", rx_bytes: 1, tx_bytes: 1, rx_speed: rx, tx_speed: tx, handshake_age: 5, online: true, endpoint: "198.51.100.9:1" });
  const stats = {
    n1: { generated_at: now, net_deps: { limits: 1, reach: 2 }, limit_err: { awg0: "tc: RTNETLINK answers: Operation not supported", caps: "x" },
          interfaces: { awg0: { meta: {}, peers: [peerObs("PKA", 100000, 2400000), peerObs("PKB", 2000000, 2000000), peerObs("PKC", 0, 25000),
                                                 peerObs("PKD", 1000000, 1000000), peerObs("PKT", 0, 0), peerObs("PKF", 250000, 250000),
                                                 peerObs("PKG", 0, 625000)] } },
          csqtt: [{ iface: "csqtt0", passwords: { CPW: { ip: "10.30.0.2", online: true, rx_speed: 0, tx_speed: 1000000 } } }],
          wdtt: [{ iface: "wdtt1", passwords: { WPW: { ip: "10.31.0.2", online: true } } }] },
    n2: { generated_at: now, net_deps: { reach: 2 }, interfaces: { awg0: { meta: {}, peers: [peerObs("PKT", 0, 7000000), peerObs("PKE", 0, 0)] } } },
  };
  const rc = R.reconcile(roster, stats, Date.now(), { nodeSeen: { n1: now, n2: now } });
  const pt = rc.peers.find(p => p.id === "pt");
  check("a deployment's own limit reaches the browser", JSON.stringify(pt.targets.find(t => t.node === "n1").limits) === '{"d":8,"u":2}', pt.targets);
  check("…a device's own", JSON.stringify(pt.limits) === '{"d":50}', pt.limits);
  check("…a user's own", JSON.stringify((rc.users.find(u => u.id === "ua") || {}).limits) === '{"d":20,"u":5}');
  check("…a WDTT / csqtt deployment's own (the keyless branch builds its own target)", JSON.stringify(rc.peers.find(p => p.id === "pk").targets[0].limits) === '{"c":5}', rc.peers.find(p => p.id === "pk").targets);
  check("…and none where none is stored", rc.peers.find(p => p.id === "pb").limits === null && rc.users.find(u => u.id === "ub").limits === null);
  SP.Store.roster = roster;
  check("a group's limit, through Store.groups()", JSON.stringify((SP.Store.groups().find(g => g.id === "g1") || {}).limits) === '{"c":40}', SP.Store.groups());

  // the real Store, as the screens hold it
  Store.roster = roster; Store.stats = stats; Store.recon = rc;
  Store.nodes = [{ id: "n1", name: "n1", reach_unvouched: [], reach_unvouched_raw: ["wdtt1"] }, { id: "n2", name: "n2" }];
  Store.panelSettings = {};

  console.log("\n[3] precedence, against the panel's own");
  var env = { ...process.env, SWG_NO_REEXEC: "1" };
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
  const ha = held("pa", "n1");
  check("anna downloading 19.2 Mbit/s against 20 down is held — on her download (tx) only", !!ha && ha.tx && !ha.rx, ha && [ha.rx, ha.tx]);
  check("…the Live grid tints that direction alone: ↑ in the server's perspective", L.heldCls(ha) === " held-up", L.heldCls(ha));
  Store.panelSettings = { throughput_perspective: "peers" };
  check("…↓ in the peers' (a phone, which shows only ↓, shows it)", L.heldCls(ha) === " held-dn", L.heldCls(ha));
  Store.panelSettings = {};
  check("dora, alone in her pool (the tie went to group Tie) at 16 of 40 combined, is not", !held("pd", "n1"));
  check("boris (32) and fred (4) both moving on Family's 40: the node caps each at 20 — boris is held, fred is not", !!held("pb", "n1") && !held("pf", "n1"));
  check("gina at 5 of Work's 10 down while carol moves 0.2: each capped at 5, so gina is held though the pool's sum (5.2) is far below it",
    !!held("pg", "n1") && !held("pc", "n1"));
  check("a csqtt deployment is never judged (its rates are 10–30 s counter deltas)", L.limitHeld(rc.peers.find(p => p.id === "pk"), rc.peers.find(p => p.id === "pk").targets[0]) === null);
  check("a node that does not enforce limits shows none held (pt at 56 of its device's 50 on n2)", !held("pt", "n2"));

  console.log("\n[5] where a limit is not enforced");
  const gaps = L.limitGaps(pt.targets);
  check("a live node without net_deps.limits", JSON.stringify(gaps.old) === '["n2"]', gaps);
  rc.nodeStatus.n2 = "stale";
  check("…never a stale one", L.limitGaps(pt.targets).old.length === 0);
  rc.nodeStatus.n2 = "live";
  const kw = rc.peers.find(p => p.id === "pw").targets[0], kw2 = rc.peers.find(p => p.id === "pw2").targets[0];
  check("a WDTT build vouched for WireGuard but not RAW is named, once however many devices sit there", JSON.stringify(L.limitGaps([kw, kw2]).unv) === '["wdtt1 (RAW) · n1"]', L.limitGaps([kw, kw2]));
  Store.nodes[0].reach_unvouched = ["wdtt1"];
  check("…one vouched for no path, as itself", JSON.stringify(L.limitGaps([kw]).unv) === '["wdtt1 · n1"]', L.limitGaps([kw]));
  Store.nodes[0].reach_unvouched = [];
  // limit_err: the panel's own node issues (every reader of a node's issues sees it, translated like the rest)
  let srvFile = path.join(ROOT, "swg-panel-server");
  if (MODE && PLANTS[MODE][0] === "swg-panel-server") { const d = fs.mkdtempSync(path.join(os.tmpdir(), "spa-limits-")); made.push(d); srvFile = path.join(d, "swg-panel-server"); fs.writeFileSync(srvFile, source("swg-panel-server")); }
  const iss = JSON.parse(execFileSync("python3", ["-c", `
import importlib.machinery, importlib.util, json, sys
ld = importlib.machinery.SourceFileLoader("swgp", sys.argv[1]); m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgp", ld))
try: ld.exec_module(m)
except SystemExit: pass
print(json.dumps([m._node_issues({}, {"limit_err": {"awg0": "tc: no", "caps": "rc 124", "exception": "KeyError: 'x'", "limits": "not a list", "sweep": "rc 127"}}), m._node_issues({}, {})]))`, srvFile], { env }).toString());
  const [li, none] = iss, says = (i, re) => !!li[i] && re.test(li[i].error);
  check("limit_err is a node issue, a line a key, in the node's words", li.length === 5 && li.every(x => x.error_key && x.error_vars), li);
  check("…a device's entry: traffic there runs unlimited", says(0, /awg0: tc: no .*runs unlimited/));
  check("…a failed cap: every limit still holds (never \"unlimited\")", says(1, /every limit still holds/) && !says(1, /unlimited/));
  check("…a limiter that raised: said as itself, never read as a device called \"exception\"", says(2, /limiter failed \(KeyError.*nothing is cut/) && !says(2, /applied on exception|unlimited/));
  check("…a refused list: what was loaded stays", says(3, /loaded before stay/) && !says(3, /unlimited/));
  check("…a failed sweep: nothing loaded yet", says(4, /not loaded yet/));
  check("…and nothing without it", none.length === 0, none);
  for (const x of li) RUKEYS.add(x.error_key);

  console.log("\n[6] the doors, as shipped");
  const pu = source("js/peer-ui.js"), sc = source("js/sheets-crud.js"), lj = source("js/limits.js");
  const has = (what, s, needle) => check(what, s.includes(needle), needle);
  has("the user editor opens on the stored limit", pu, "const lim = useLimit(user.limits);");
  has("…sends it only when it changed", pu, "const limits = lim.changed ? lim.take() : undefined;");
  has("…in the users/update body", pu, "expiry: expSec, ...(limits ? { limits } : {}), ...(volume ? { volume } : {}) }), setSaveErr, setBusy);");
  has("…and a change enables Save", pu, "|| lim.changed || vol.changed;");
  has("the group editor: an existing group's limit, sent when it changed", pu, "remove, ...(limits ? { limits } : {}), ...(volume ? { volume } : {}) })");
  has("…a change marks it dirty", pu, "|| (!!gid && (lim.changed || vol.changed));");
  has("Edit peer: the device's limit through peers/update", sc, "const r = await api.peerUpdate({ peer_id: peer.id, ...(limits ? { limits } : {}), ...(volume ? { volume } : {}) });");
  has("…a deployment's through update-target only, when staged and changed", sc, "if (!tlimChanged(t)) continue;\n        const r = await api.peerUpdateTarget({ peer_id: peer.id, node: t.node, iface: t.iface, limits: tlims[tkey(t.node, t.iface)] });");
  has("…either change enables Save", sc, "|| lim.changed || vol.changed || (live.targets || []).some(tlimChanged);");
  has("…and guards the close (the pills are buttons, a deployment's is staged in its own sheet)", sc, "    dirtyRef=${{ current: lim.changed || vol.changed || (live.targets || []).some(tlimChanged) }}");
  has("Edit user guards a changed limit on close", pu, "  if (dirtyRef) dirtyRef.current = lim.changed || vol.changed;");
  has("a field's change is against what it opened on, never a later poll's copy", lj, "!limSame(out.lim, limFromDraft(seed).lim)");
  check("the deployment's gauge is not the gear (a gate waits for .topt-gear as the sign a config loaded)", !/class=\$\{"[^"]*topt-gear/.test(lj));
  has("Peer targets: R7, a removed row's own limit is named", sc, "  const limGone = removed.filter(t => limClean(t.limits));");
  check("…and its notice is drawn", sc.includes("${limGone.length ? html`<div class=\"notice warn\">"));
  check("noded says it loads limits", fs.readFileSync(path.join(ROOT, "swg-noded"), "utf8").includes('"reach": 2, "limits": 1}'));

  console.log("\n[8] volume limits");
  const vd = d => L.volFromDraft({ mode: "du", d: "", u: "", c: "", period: "m", at: "cut", ...d });
  check("download 12.5 GB a month → bytes", JSON.stringify(vd({ d: "12,5" }).vol) === '{"d":12500000000,"period":"m","at":"cut"}', vd({ d: "12,5" }));
  check("combined, a week, slow", JSON.stringify(L.volFromDraft({ mode: "c", c: "5", period: "w", at: "slow" }).vol) === '{"c":5000000000,"period":"w","at":"slow"}');
  check("refused: under 0.1 GB, a thousands separator, nothing typed", !!vd({ d: "0.05" }).err && !!vd({ d: "1,000" }).err && !!vd({}).err);
  check("no limit → {}", JSON.stringify(L.volFromDraft({ mode: "none" }).vol) === "{}");
  check("a stored volume opens as itself, and reads the same", L.volSame(vd({ d: "12.5" }).vol, L.volFromDraft(L.volDraft({ d: 12500000000, period: "m", at: "cut" })).vol)
    && !L.volSame({ d: 12500000000, period: "m", at: "cut" }, { d: 12500000000, period: "w", at: "cut" }));
  const rv = { ...roster, peers: { ...roster.peers, pb: { ...roster.peers.pb, volume: { d: 5 * 1e9, period: "m", at: "cut" } } } };
  const rcv = R.reconcile(rv, stats, Date.now(), { nodeSeen: { n1: now, n2: now }, vol: { pb: "cut", ud: "cut" } });
  const pbv = rcv.peers.find(p => p.id === "pb"), pdv = rcv.peers.find(p => p.id === "pd");
  check("a device's own volume reaches the browser", JSON.stringify(pbv.volume) === '{"d":5000000000,"period":"m","at":"cut"}', pbv.volume);
  check("a cut device is expired (still online until its node drops it, as for a date)", pbv.expired === true && pbv.selfExpired === true, [pbv.expired, pbv.status]);
  check("…a cut owner's devices too", pdv.expired === true && pdv.userExpired === true, [pdv.expired, pdv.status]);
  check("…and an uncut device is not", rcv.peers.find(p => p.id === "pa").expired === false);
  const rcq = R.reconcile({ ...rv, peers: { pb: rv.peers.pb } }, { n1: { generated_at: now, interfaces: { awg0: { meta: {}, peers: [] } } } }, Date.now(), { nodeSeen: { n1: now }, vol: { pb: "cut" } });
  const pbq = rcq.peers.find(p => p.id === "pb");
  check("…once its node has dropped it: expired, with the volume as the reason", pbq.status === "expired" && /volume limit/.test(pbq.reason || ""), [pbq.status, pbq.reason]);
  const rcd = R.reconcile({ ...rv, peers: { pb: { ...rv.peers.pb, expiry: now - 60 } } }, { n1: { generated_at: now, interfaces: { awg0: { meta: {}, peers: [] } } } }, Date.now(), { nodeSeen: { n1: now }, vol: { pb: "cut" } });
  const pbd = rcd.peers.find(p => p.id === "pb");
  check("…its own date passed too: the date is the reason (raising the volume would not bring it back)", /access date/.test(pbd.reason || ""), pbd.reason);
  const keepVol = Store.vol;
  Store.vol = { uz: "slow" };
  const se = L.effLimit({ id: "px", user_id: "uz", limits: { d: 20 } }, { node: "n1", iface: "awg0" });
  check("a slowed person's device runs at 1 Mbit/s both ways, one pool for the person (Live's held, the peer view)",
    JSON.stringify(se && se.lim) === '{"c":1}' && se.src === "volume" && se.pool === "s:uz", se);
  Store.vol = { px: "slow" };
  const sd = L.effLimit({ id: "px", user_id: "uz" }, { node: "n1", iface: "awg0" });
  check("…a device slowed by its own limit, its own pool", sd && sd.pool === "s:px", sd);
  const PA = await load("js/peer-actions.js");
  Store.vol = { uz: "cut", px: "cut" };
  const ss = PA.subState({ id: "uz" }), ps = PA.peerState({ id: "px" }), us = PA.userState({ id: "uz" });
  check("the status lines say a volume cut (never 'Subscription is active' beside an expired badge)",
    ss.cls === "s-expired" && /volume limit/.test(ss.text) && ps && ps.cls === "s-expired" && us && us.cls === "s-expired", [ss, ps, us]);
  Store.vol = keepVol;
  check("the group editor stops on a volume it cannot save, as Edit user and Edit peer do",
    source("js/peer-ui.js").includes("const volume = gid && vol.changed ? vol.take() : undefined;\n    if (limits === null || volume === null) return;"));
  const ls = source("js/limits.js");
  check("the used line asks for the drafted period, and only with a limit drafted (no ledger-off warning on every editor)",
    ls.includes('encodeURIComponent(id) + "&period=" + period)') && ls.includes("${id && own ? html`<${UsedLine}"));

  console.log("\n[9] the Limits button and sheet");
  const PU = await load("js/peer-ui.js");
  const keepVol2 = Store.vol, past = Math.floor(Date.now() / 1000) - 60, later = past + 86400 * 30;
  Store.vol = { u1: "cut", u2: "slow" };
  const lst = (kind, rec) => PU.limitsState(kind, rec);
  const a = lst("user", { id: "u0" }), b = lst("user", { id: "u0", expiry: later, limits: { d: 20 }, volume: { d: 5e9, period: "m", at: "cut" } });
  check("nothing set: no count, no state; all three set: 3, 'set'", a.n === 0 && a.cls === "" && b.n === 3 && b.cls === " on", [a, b]);
  check("a volume cut or a passed date reads cut off; a volume slow reads slowed", lst("user", { id: "u1" }).cls === " cut"
    && lst("user", { id: "u0", expiry: past }).cls === " cut" && lst("user", { id: "u2" }).cls === " slow", [lst("user", { id: "u1" }), lst("user", { id: "u0", expiry: past })]);
  check("…a device by its OWN expiry (ownExpiry), not its subscription's", lst("peer", { id: "p0", ownExpiry: later }).n === 1 && lst("peer", { id: "p0", expiry: later }).n === 0);
  const ou = ((Store.recon && Store.recon.users) || []).find(u => !u.expiry && Store.user(u.id));   // an owner the store knows
  Store.vol = { [ou && ou.id]: "slow" };
  const lp = lst("peer", { id: "p9", user_id: ou && ou.id });
  check("a device counts its owner: slowed with them (the count stays its own)", !!ou && lp.cls === " slow" && lp.n === 0, [ou && ou.id, lp]);
  check("…and its tooltip names them as the cause", lp.why === "oslow" && lp.owner === (ou && ou.name || ""), lp);
  Store.vol = { [ou && ou.id]: "cut" };
  const nn = ((Store.recon && Store.recon.users) || []).find(u => u.id === (ou && ou.id));
  const keepName = nn ? nn.name : null;
  if (nn) nn.name = "";
  const ln = lst("peer", { id: "p9", user_id: ou && ou.id });
  if (nn) nn.name = keepName;
  check("…an owner with no name is 'its owner', never an empty name in the sentence", !!nn && ln.owner === "its owner", ln);
  check("…cut off with them, named", lst("peer", { id: "p9", user_id: ou && ou.id }).why === "ovol", lst("peer", { id: "p9", user_id: ou && ou.id }));
  check("…cut off with them", lst("peer", { id: "p9", user_id: ou && ou.id }).cls === " cut", lst("peer", { id: "p9", user_id: ou && ou.id }));
  check("…and a stored value the panel would refuse is not counted", lst("user", { id: "u0", limits: { d: 0 }, volume: { d: 1 } }).n === 0);
  Store.vol = keepVol2;
  const pus = source("js/peer-ui.js");
  check("both QR footers carry the Limits button (the expiry-only button is gone)", pus.includes('<${LimitsButton} kind="peer" id=${pid} rec=${p}/>')
    && pus.includes('<span class="grow"></span><${LimitsButton} kind="user" id=${uid} rec=${u}/>') && !pus.includes("openSetExpiry("));
  check("an edit undone asks nothing on Close (the sheet's own typed flag is handed back), and editing the date clears its refusal",
    pus.includes("useEffect(() => { if (!dirtyRef.current && cleanRef.current) cleanRef.current(); });")
    && pus.includes('onInput=${e => { setD(e.target.value); setErr(""); }}'));
  check("the sheet sends only what changed, and its Close asks before dropping an edit",
    pus.includes("const body = { ...(expChanged ? { expiry: sec } : {}), ...(limits ? { limits } : {}), ...(volume ? { volume } : {}) };")
    && pus.includes("foot=${footRow({ onCancel: () => (closeRef.current ? closeRef.current() : closeModal()), cancelLabel: T(\"Close\"),"));
  for (const k of ["Limits", "Limits saved.", "Access until", "Access date, speed limit and volume limit",
                   "Cut off now: its access date has passed", "Cut off now: a volume limit is used up", "Cut off now: {name}'s subscription has ended",
                   "Cut off now: {name} has used up a volume limit", "Slowed to 1 Mbit/s now: a volume limit is used up",
                   "Slowed to 1 Mbit/s now: {name} has used up a volume limit", "lim|its owner"]) RUKEYS.add(k);

  console.log("\n[7] Russian");
  const keys = new Set(RUKEYS);
  for (const f of ["js/limits.js"]) for (const m of fs.readFileSync(path.join(ROOT, f), "utf8").matchAll(/\bT\("((?:[^"\\]|\\.)+)"/g)) keys.add(m[1]);
  for (const k of ["The gauge sets that deployment's own speed limit.", "col|Speed limit",
                   "Removing {target} removes its own speed limit. Deployed again, it starts without one.",
                   "Removing {targets} removes their own speed limits. Deployed again, they start without one.", "A limit wasn't saved.",
                   "This deployment's own speed limit: {lim}", "Saving removes this deployment and its own speed limit ({lim})."]) keys.add(k);
  const missing = [...keys].filter(k => typeof RU[k] !== "string" || !RU[k]);
  check("a Russian line for each of " + keys.size + " strings", missing.length === 0, missing);
} finally {
  for (const d of made) fs.rmSync(d, { recursive: true, force: true });
}
done(!!MODE, MODE);
