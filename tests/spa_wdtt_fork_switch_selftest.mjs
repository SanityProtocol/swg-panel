/* Self-test — switching a WDTT server's fork, the SPA's half (1.8.12 item 23, docs/RELEASE-1.8.12-PLAN.md "Switching a
 * WDTT server's fork"). Its node and panel halves: tests/wdtt_fork_switch_selftest.py.
 *
 *  [1] the switch as the node reports it: steady, switching (asked ≠ running), failed (the node's fork_failed for the fork
 *      the panel asks — another fork's failure is not this one's), blocked (a node that does not list the asked fork: an
 *      older noded, or one older than the fork) — never "switching" for ever
 *  [2] the Fork field: absent with one WDTT fork on offer; the asked and the running fork are never refused; a fork with no
 *      published build and one the node can't run are refused, each with its reason
 *  [3] the confirm sheet: names the target, says how many users keep their passwords, links and apps, that a device online
 *      carries on by itself — or, to ildarmaga or wdttplus, must reconnect once (they resume no connection after any restart
 *      of their own, measured on the rig with the qWDTT client) — and that the node falls back by itself; names the extra flags that go, and RAW turning off only for a target without RAW;
 *      confirming saves
 *  [4] the save: a pick sends `fork_switch` with the fork; untouched, the field follows the record; going back to the fork
 *      that runs asks nothing; the RAW toggle follows the picked fork (read from the source — the sheet has hooks)
 *  [5] the card: "switching", "switch failed" and "update node", each from the switch state
 *
 * Run: node tests/spa_wdtt_fork_switch_selftest.mjs     --perturb <failed|blocked|oneforks|refusebuild|refusenode|keepwant|
 *        users|ildarnote|flagsnote|rawnote|confirmgo|switchflag|backnoask|rawpick|cardtag|closefirst|typednote|stoppednote|keeprun|rocopy>
 *        plants one regression, expects RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

const MODE = process.argv.includes("--perturb") ? process.argv[process.argv.indexOf("--perturb") + 1] : null;
const PLANTS = {
  failed: ["  const failed = w.fork_failed && w.fork_failed.fork === want ? w.fork_failed : null;", "  const failed = w.fork_failed || null;"],
  blocked: ["  const blocked = moving && !((Store.stats[node] || {}).wdtt_forks || []).includes(want);", "  const blocked = false;"],
  oneforks: ["  if (forks.length < 2) return null;\n  const can = (Store.stats[node] || {}).wdtt_forks || [];", "  const can = (Store.stats[node] || {}).wdtt_forks || [];"],
  refusebuild: ["!(f.wdtt_versions || []).length ? T(\"no build published yet\")", "false ? T(\"no build published yet\")"],
  refusenode: [": !can.includes(f.id) ? T(\"Update this node to run {v1}.\", { v1: forkLabel(f.id) }) : \"\");", ": \"\");"],
  keepwant: ["const opts = forkOpts(forks, f => f.id === sw.want || f.id === sw.run ? \"\"", "const opts = forkOpts(forks, f => false ? \"\""],
  users: ["  const n = ghostPeers(node, iface).length, fl = forkLabel(from), tl = forkLabel(to);", "  const n = 0, fl = forkLabel(from), tl = forkLabel(to);"],
  flagsnote: ["${params ? html`<p class=\"hint\">${T(\"Its extra flags", "${false ? html`<p class=\"hint\">${T(\"Its extra flags"],
  rawnote: ["  const rawGone = rawOn && !(turnForkList().find(f => f.id === to) || {}).raw;", "  const rawGone = rawOn;"],
  ildarnote: ["const WDTT_NO_RESUME = [\"ildarmaga\", \"wdttplus\"];", "const WDTT_NO_RESUME = [];"],
  confirmgo: ["    onConfirm=${go}/>`);\n}\nexport const WdttForkNotices", "    onConfirm=${() => {}}/>`);\n}\nexport const WdttForkNotices"],
  switchflag: ["fork: forkTo, ...(forkDirty ? { fork_switch: true } : {}), title", "fork: forkTo, title"],
  backnoask: ["  const save = () => forkDirty && forkTo !== sw.run\n    ? confirmWdttSwitch(", "  const save = () => forkDirty\n    ? confirmWdttSwitch("],
  closefirst: ["() => { closeModal(); return save2(); }, !!cfg.stopped)", "save2, !!cfg.stopped)"],
  typednote: ["paramsDirty ? \"\" : (cfg.params || \"\").trim(), !!rawCur", "(cfg.params || \"\").trim(), !!rawCur"],
  stoppednote: ["    body=${stopped ? T(\"The server is stopped", "    body=${false ? T(\"The server is stopped"],
  rocopy: ["  ${sw.failed ? html`<div class=\"notice warn\"><${Ic} i=\"warn\"/><span>${ro\n", "  ${sw.failed ? html`<div class=\"notice warn\"><${Ic} i=\"warn\"/><span>${false\n"],
  keeprun: ["  const forks = (run && !shown.some(f => f.id === sw.run) ? [...shown, run] : shown).filter(f => f.kind === \"wdtt\");", "  const forks = shown.filter(f => f.kind === \"wdtt\");"],
  rawpick: ["  const rawCapable = !!(turnForkList().find(x => x.id === forkTo) || {}).raw;", "  const rawCapable = !!(turnForkList().find(x => x.id === fork) || {}).raw;"],
  cardtag: ["    : sw.switching ? html`<${StatusTag} cls=\"tg tg-pending\" icon=\"clock\" label=${T(\"tag|switching\")} title=${T(\"Moving to {v1} on the node's next sync\", { v1: forkLabel(sw.want) })}/>`\n", ""],
};
let TU, TSRC, made = null;
try {
  let p = path.join(ROOT, "js", "turn.js");
  TSRC = fs.readFileSync(p, "utf8");
  if (MODE) {
    const [old, nu] = PLANTS[MODE];
    if (TSRC.split(old).length !== 2) throw new Error("plant anchor did not match exactly once — this run would measure nothing");
    TSRC = TSRC.replace(old, nu);
    made = p = path.join(ROOT, "js", "__perturbed_wfs_turn.js"); fs.writeFileSync(p, TSRC);
  }
  TU = await import(pathToFileURL(p).href);
} finally { if (made) fs.rmSync(made, { force: true }); }
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const UI = await import(pathToFileURL(path.join(ROOT, "js", "ui.js")).href);

const walk = (n, pick) => { const out = []; const w = x => { if (Array.isArray(x)) x.forEach(w);
  else if (x && typeof x === "object" && x.props) { const r = pick(x); if (r !== undefined) out.push(r); w(x.props.children); } }; w(n); return out; };
const dropdown = n => walk(n, x => (x.props && Array.isArray(x.props.options)) ? x.props : undefined)[0];
const text = n => { const o = []; const w = x => { if (x == null || x === false) return; if (Array.isArray(x)) return x.forEach(w);
  if (typeof x === "object") return x.props ? (w(x.props.children), w(x.props.body), w(x.props.note), w(x.props.label), w(x.props.title)) : undefined; o.push(String(x)); }; w(n); return o.join(" "); };

const srv = (id, kind, o = {}) => ({ id, kind, label: o.label || id, raw: !!o.raw, hidden: !!o.hidden, wdtt_versions: o.v || [] });
Store.turnCatalog = { servers: [srv("amurcanov", "wdtt", { v: ["1.2.4-3"] }), srv("ildarmaga", "wdtt", { raw: true, v: ["1.5.0-4"] }),
  srv("wdttplus", "wdtt", { label: "Ivan4537", v: ["20-1"] }), srv("qwdtt", "wdtt", { label: "SpaceNeuroX", raw: true, v: ["1.4.4-2"] }),
  srv("xxcipherx", "wdtt", { label: "XXcipherX", hidden: true }), srv("csqtt", "csqtt", { v: [] })] };
Store.panelSettings = { enabled_turn_forks: ["amurcanov", "ildarmaga", "wdttplus", "qwdtt", "csqtt"] };
const ALL = ["amurcanov", "ildarmaga", "qwdtt", "wdttplus", "xxcipherx"];

// [1]
Store.nodes = [{ id: "nn", wdtt_cfg: { a: { fork: "amurcanov" }, b: { fork: "qwdtt" }, c: { fork: "qwdtt" }, d: { fork: "amurcanov" }, e: { fork: "ildarmaga" } } },
               { id: "no", wdtt_cfg: { f: { fork: "qwdtt" } } }];
Store.stats = { nn: { wdtt_forks: ALL, wdtt: [{ iface: "a", fork: "amurcanov" }, { iface: "b", fork: "amurcanov" },
  { iface: "c", fork: "amurcanov", fork_failed: { fork: "qwdtt", ver: "1.4.4-2", why: "the server exited" } },
  { iface: "d", fork: "amurcanov", fork_failed: { fork: "qwdtt", ver: "x", why: "old" } }, { iface: "e", fork: "amurcanov" }] },
  no: { wdtt: [{ iface: "f", fork: "amurcanov" }] } };
const s = (n, i) => TU.wdttSwitchState(n, i);
check("[1] steady: asked amurcanov, runs amurcanov", !s("nn", "a").switching && !s("nn", "a").failed && !s("nn", "a").blocked, s("nn", "a"));
check("[1] switching: asked qwdtt, runs amurcanov", s("nn", "b").switching && !s("nn", "b").failed, s("nn", "b"));
check("[1] failed: the node's fork_failed for qwdtt", !!s("nn", "c").failed && !s("nn", "c").switching && s("nn", "c").failed.why === "the server exited", s("nn", "c"));
check("[1] another fork's failure is not this switch's (asked amurcanov again)", !s("nn", "d").failed && !s("nn", "d").switching, s("nn", "d"));
check("[1] an older node (no wdtt_forks) asked for qwdtt: blocked, not switching", s("no", "f").blocked && !s("no", "f").switching, s("no", "f"));
Store.stats.nn.wdtt_forks = ["amurcanov", "qwdtt"];
check("[1] a node that does not list the asked fork: blocked", s("nn", "e").blocked && !s("nn", "e").switching, s("nn", "e"));
Store.stats.nn.wdtt_forks = ALL;

// [2]
const fieldOf = (node, iface, value) => TU.WdttForkField({ node, sw: TU.wdttSwitchState(node, iface), value, onChange: () => {} });
const f2 = fieldOf("nn", "a", "amurcanov");
const d2 = dropdown(f2) || { options: [] };
check("[2] the field lists every visible WDTT fork (never csqtt, never a hidden one)", JSON.stringify(d2.options.map(o => o.value).sort()) === '["amurcanov","ildarmaga","qwdtt","wdttplus"]', d2.options);
check("[2] a capable node: nothing with a build is refused", d2.options.every(o => !o.disabled), d2.options);
Store.stats.nn.wdtt_forks = ["amurcanov", "qwdtt"];
const d2b = dropdown(fieldOf("nn", "a", "amurcanov")) || { options: [] };
const il = d2b.options.find(o => o.value === "ildarmaga") || {};
check("[2] a fork the node can't run is refused, saying update the node", il.disabled && /Update this node to run/.test(il.label), il);
Store.stats.nn.wdtt_forks = ALL;
Store.turnCatalog.servers.find(x => x.id === "wdttplus").wdtt_versions = [];
const wp = (dropdown(fieldOf("nn", "a", "amurcanov")) || { options: [] }).options.find(o => o.value === "wdttplus") || {};
check("[2] a fork with no published build is refused, saying so", wp.disabled && /no build published yet/.test(wp.label), wp);
Store.turnCatalog.servers.find(x => x.id === "wdttplus").wdtt_versions = ["20-1"];
Store.nodes[0].wdtt_cfg.x = { fork: "xxcipherx" }; Store.stats.nn.wdtt.push({ iface: "x", fork: "xxcipherx" });
const dx = dropdown(fieldOf("nn", "x", "xxcipherx")) || { options: [] };
const xo = dx.options.find(o => o.value === "xxcipherx") || {};
check("[2] a server on the hidden fork: shown as its value, not refused, and it may leave it", !!dx.options.length && xo.value === "xxcipherx" && !xo.disabled
      && dx.options.some(o => o.value === "qwdtt" && !o.disabled), dx.options);
Store.nodes[0].wdtt_cfg.y = { fork: "qwdtt" }; Store.stats.nn.wdtt.push({ iface: "y", fork: "xxcipherx", fork_failed: { fork: "qwdtt", ver: "1.4.4-2", why: "x" } });
const dy = dropdown(fieldOf("nn", "y", "qwdtt")) || { options: [] };
check("[2] after a failed switch away from the hidden fork, the fork it runs is still a choice (\"pick it to stay there\")",
      dy.options.some(o => o.value === "xxcipherx" && !o.disabled), dy.options);
Store.panelSettings = { enabled_turn_forks: ["amurcanov", "csqtt"] };
check("[2] one WDTT fork on offer: no field", fieldOf("nn", "a", "amurcanov") === null);
Store.panelSettings = { enabled_turn_forks: ["amurcanov", "ildarmaga", "wdttplus", "qwdtt", "csqtt"] };

// [3]
let top = null; UI.setModalRenderer(st => { top = st[st.length - 1] || null; });
const ask = (from, to, params, rawOn, users, stopped) => { UI.clearModalStack(); top = null; let went = 0;
  Store.recon = Object.assign(Store.recon || {}, { peers: Array.from({ length: users }, (_, i) => ({ id: "p" + i, targets: [{ node: "nn", iface: "a" }] })) });
  TU.confirmWdttSwitch("nn", "a", from, to, params, rawOn, () => went++, stopped);
  const p = (top && top.props) || {}; const r = { title: p.title, body: String(p.body || ""), note: text(p.note) };
  if (p.onConfirm) p.onConfirm(); return { ...r, went }; };
const a3 = ask("amurcanov", "qwdtt", "", false, 3);
check("[3] the sheet names the target", a3.title === "Switch to SpaceNeuroX?", a3.title);
check("[3] …how many users keep their passwords, links and apps", /3 users keep their passwords, links and apps/.test(a3.body), a3.body);
check("[3] …and that a device online carries on by itself", /carries on by itself/.test(a3.body), a3.body);
const a3i = ask("amurcanov", "ildarmaga", "", false, 2);
check("[3] to ildarmaga: a device online must turn the VPN off and on once (ildarmaga resumes no connection after a restart)",
      /must turn the VPN off and on once/.test(a3i.body) && !/carries on by itself/.test(a3i.body), a3i.body);
const a3w = ask("qwdtt", "wdttplus", "", false, 2);
check("[3] …and to wdttplus the same", /must turn the VPN off and on once/.test(a3w.body), a3w.body);
check("[3] …and that the node puts it back by itself", /puts the server back on amurcanov by itself/.test(a3.body), a3.body);
check("[3] confirming saves", a3.went === 1, a3);
check("[3] no flags, no RAW: no note", !a3.note.trim(), a3.note);
const a3s = ask("amurcanov", "qwdtt", "", false, 3, true);
check("[3] a stopped server: it moves now and starts on the target when started — no promise of a check it never gets",
      /The server is stopped/.test(a3s.body) && !/puts the server back/.test(a3s.body), a3s.body);
const a4 = ask("amurcanov", "ildarmaga", "-x 1", false, 0);
check("[3] the extra flags that go are named", /extra flags \(-x 1\) are removed/.test(a4.note), a4.note);
const a5 = ask("qwdtt", "amurcanov", "", true, 2);
check("[3] RAW on, a target without RAW: it says RAW turns off", /RAW turns off: amurcanov has none/.test(a5.note), a5.note);
const a6 = ask("qwdtt", "ildarmaga", "", true, 2);
check("[3] RAW on, a target with RAW: nothing about RAW", !/RAW/.test(a6.note), a6.note);

// [4] read from the source (the sheet has hooks)
const sheet = TSRC.slice(TSRC.indexOf("export function WdttManageSheet("), TSRC.indexOf("export async function wdttRestoreIdentity("));
check("[4] a pick sends the fork with fork_switch", sheet.includes("fork: forkTo, ...(forkDirty ? { fork_switch: true } : {}), title"));
check("[4] only a pick that differs from the record is held", sheet.includes("onChange=${v => setForkPick(v === sw.want ? null : v)}")
      && sheet.includes("const forkTo = forkPick || sw.want, forkDirty = forkTo !== sw.want;"));
check("[4] a switch away from what runs asks first; back to what runs asks nothing",
      sheet.includes("  const save = () => forkDirty && forkTo !== sw.run\n    ? confirmWdttSwitch(node, iface, sw.run, forkTo,") && sheet.includes("\n    : save2();"));
check("[4] the confirm closes before the save goes on (a second question or a refusal lands on the sheet, not under a spinning confirm)",
      sheet.includes("() => { closeModal(); return save2(); }, !!cfg.stopped)"));
check("[4] flags typed in the same save are the target's: only untouched ones are named as going",
      sheet.includes("paramsDirty ? \"\" : (cfg.params || \"\").trim(), !!rawCur"));
check("[4] the RAW toggle follows the picked fork", sheet.includes("const rawCapable = !!(turnForkList().find(x => x.id === forkTo) || {}).raw;"));
check("[4] the node's notices show while nothing is picked; a failover copy gets no field",
      sheet.includes("${forkDirty ? null : html`<${WdttForkNotices} sw=${sw} ro=${!!roWhy}/>`}") && sheet.includes("${roWhy ? null : html`<${WdttForkField}"));
const nf = ro => text(TU.WdttForkNotices({ sw: TU.wdttSwitchState("nn", "c"), ro }));
check("[4] a failed switch: Restart or pick the old fork; on a failover copy (no Restart, no field) it says when it retries",
      /Restart the service to try again/.test(nf(false)) && /tries SpaceNeuroX again when a new build is published/.test(nf(true))
      && !/Restart/.test(nf(true)), [nf(false), nf(true)]);

// [5]
const tagOf = iface => { const w = Store.stats.nn.wdtt.find(x => x.iface === iface) || {};
  const v = TU.WdttCard({ node: "nn", w: { ...w, active: "active" } });
  return walk(v, x => x.props && typeof x.props.label === "string" ? x.props.label : undefined).join(","); };
Store.recon = Object.assign(Store.recon || {}, { nodeStatus: { nn: "live" } });
check("[5] a switch the node has not made: the card says switching", /switching/.test(tagOf("b")), tagOf("b"));
check("[5] a switch put back: switch failed", /switch failed/.test(tagOf("c")), tagOf("c"));
Store.stats.nn.wdtt_forks = ["amurcanov"];
check("[5] a node that can't run it: update node", /update node/.test(tagOf("b")), tagOf("b"));
Store.stats.nn.wdtt_forks = ALL;
check("[5] steady: no switch tag", !/switch|update node/.test(tagOf("a")), tagOf("a"));

done(!!MODE, MODE || "");
