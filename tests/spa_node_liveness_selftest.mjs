/* Self-test: a node's liveness is judged on ONE clock — the panel's.
 *
 * The bug this gates (client report, 2026-09-22 — a Docker master, node and panel on one host, syncing every 5 s):
 * the node LIST said "reporting" while the node PAGE said "stale", peers read 0 online, and every action on the page
 * was greyed out, interface creation included. The list asked the panel ("when did this node's sync arrive?", panel
 * clock at both ends); the page asked reconcile, which subtracted the snapshot's `generated_at` — stamped by the
 * NODE — from this browser's Date.now(). Two machines' clocks, 30 s of tolerance: any operator whose PC clock was
 * off by more than that lost the page for a node that was perfectly healthy.
 *
 * Each rule below is silent when broken — a healthy node simply reads dead, or a dead one reads healthy:
 *   [1] the clock     a node whose sync JUST arrived reads live however far its own clock is from this browser's;
 *                     one that really stopped syncing reads stale even while its own clock says "now".
 *   [2] the offset    a poll measures how far this browser is from the panel (`panel_now`) and every window is
 *                     measured on the panel's clock — end to end, through Store.poll → reconcile.
 *   [3] one verdict   the list row and the node page cannot disagree: both take live/not from recon, and "never
 *                     synced" stays the server's fact (awaiting enroll).
 *   [4] the ages      an age the SPA prints is measured on the clock that stamped it.
 *   [5] the fallback  a panel too old to send `panel_now`/`last_seen` still judges by `generated_at` — the old
 *                     behaviour, never "stale for ever".
 *   [6] fail safe     a `panel_now` that is not a number (a proxy's error page, a truncated body) leaves the clock
 *                     as it was — a NaN there would poison every window and every age at once; and the offset is
 *                     measured in the direction that keeps a node reporting a beat too long rather than greying it
 *                     out early, since reading a healthy node as dead is the whole defect.
 *
 * Run: node tests/spa_node_liveness_selftest.mjs                 (0 = pass)
 *      node tests/spa_node_liveness_selftest.mjs --plant <name>  breaks one rule on purpose; exits 0 only if a check went red.
 *      plants: clock finite offset now seen ago row door label guard
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, check, done, FAILS } from "./spa_env.mjs";

const PLANT = process.argv.includes("--plant") ? process.argv[process.argv.indexOf("--plant") + 1] : "";
const PLANTS = {   // name: [file, anchor, replacement]
  clock: ["reconcile.js", `    const gen = Number.isFinite(seen) ? seen : (stats[node] && stats[node].generated_at);`,
    `    const gen = (stats[node] && stats[node].generated_at);`],
  finite: ["reconcile.js", `Number.isFinite(seen) ? seen :`, `seen != null ? seen :`],
  offset: ["js/store.js", `    if (Number.isFinite(d.panel_now) && d.panel_now > 0) clock.skewMs = Date.now() - d.panel_now * 1000;`, ""],
  now: ["js/store.js", `reconcile(this.roster, this.stats, panelNow(), { retiring`, `reconcile(this.roster, this.stats, Date.now(), { retiring`],
  seen: ["js/store.js", `systemIfaces, nodeSeen, rotating:`, `systemIfaces, rotating:`],
  ago: ["js/util.js", `  const d = Math.max(0, Math.floor(panelNowS() - sec));`, `  const d = Math.max(0, Math.floor(Date.now() / 1000 - sec));`],
  row: ["js/screen-nodes.js", `  const st = nodeStatusOf(n);`, `  const st = n.status || "dangling";`],
  door: ["js/sheets-crud.js", `          node.status === "online" ? html`, `          nodeStatusOf(node) === "online" ? html`],
  label: ["js/model.js", `  return Number.isFinite(ls) ? ls : ((snap || {}).generated_at || null);`,
    `  return ls != null ? ls : ((snap || {}).generated_at || null);`],
  guard: ["js/store.js", `    if (Number.isFinite(d.panel_now) && d.panel_now > 0) clock.skewMs = Date.now() - d.panel_now * 1000;`,
    `    if (d.panel_now) clock.skewMs = Date.now() - d.panel_now * 1000;`],
};
const written = [];
function load(file) {   // a planted module is a sibling copy (relative imports keep working) — removed at the end
  const p = PLANTS[PLANT];
  const abs = path.join(ROOT, file);
  if (!p || p[0] !== file) return import(pathToFileURL(abs).href);
  const src = fs.readFileSync(abs, "utf8");
  if (src.split(p[1]).length !== 2) { console.log("PLANT ANCHOR MISSING — this run would FALSE-PASS: " + p[1]); process.exit(1); }
  const out = path.join(path.dirname(abs), ".plant_" + path.basename(file).replace(/\.js$/, ".mjs"));
  fs.writeFileSync(out, src.replace(p[1], p[2]));
  written.push(out);
  return import(pathToFileURL(out).href);
}
const src = f => {
  const s = fs.readFileSync(path.join(ROOT, f), "utf8"), p = PLANTS[PLANT];
  return p && p[0] === f ? s.replace(p[1], p[2]) : s;
};

const S_TO_MS = 1000;
const nowS = () => Math.floor(Date.now() / 1000);
// One peer, deployed to n1/wg0 and long past its creation grace, so its target's fate is ASSERTED (dangling) on a
// live node and withheld ("unknown") on a stale one — the consequence the operator actually sees.
const roster = () => ({ version: 1, users: { u1: { id: "u1", name: "Ann" } },
  peers: { p1: { id: "p1", user_id: "u1", pubkey: "PK1", created_at: nowS() - 3600,
                 targets: [{ node: "n1", iface: "wg0", ip: "10.9.0.2/32", type: "wg" }] } } });
const snap = genAt => ({ n1: { generated_at: genAt, interfaces: { wg0: { meta: {}, peers: [] } } } });

try {
  const R = await load("reconcile.js");
  const U = await load("js/util.js");

  console.log("[1] one clock: the panel's");
  {
    // This browser reads 5 minutes AHEAD of the node (an unsynced desktop clock, or a host RTC left on local time).
    const skewS = 300, panelNow = Date.now(), seen = nowS();
    const r = R.reconcile(roster(), snap(nowS() - skewS), panelNow, { nodeSeen: { n1: seen } });
    check("a node whose sync just arrived is live, however far its own clock is from this browser's",
      r.nodeStatus.n1 === "live", r.nodeStatus);
    check("…so its peers' status is asserted, not withheld as unknown",
      r.peers[0].targets[0].status !== "unknown", r.peers[0].targets[0].status);
    // The other direction, which the old check got wrong for ever: the node's clock says "now", but nothing has
    // arrived for two minutes. A panel outage must not read as a healthy fleet.
    const r2 = R.reconcile(roster(), snap(nowS()), panelNow, { nodeSeen: { n1: nowS() - 120 } });
    check("a node that stopped syncing reads stale even while its own clock says now", r2.nodeStatus.n1 === "stale", r2.nodeStatus);
    check("…and then its peers are unknown, not declared gone", r2.peers[0].targets[0].status === "unknown", r2.peers[0].targets[0].status);
    // And the window itself still governs: 25 s of silence is a blip, not an outage (default nodeStaleMs 30 s).
    const r3 = R.reconcile(roster(), snap(nowS()), panelNow, { nodeSeen: { n1: nowS() - 25 } });
    check("the stale window still decides — 25 s of silence is not stale", r3.nodeStatus.n1 === "live", r3.nodeStatus);
  }

  console.log("[2] the offset is measured, end to end");
  {
    const St = await load("js/store.js");
    const U0 = await import(pathToFileURL(path.join(ROOT, "js/util.js")).href);   // the clock store.js itself writes to
    const panelBehindS = 600;   // the panel's clock reads 10 minutes behind this browser
    const pNow = nowS() - panelBehindS;
    St.api.state = async () => ({ ok: true, data: {
      panel_now: pNow,
      roster: roster(),
      nodes: [{ id: "n1", name: "node-one", status: "online", last_seen: pNow }],
      // ⚠️ AND THE NODE'S OWN CLOCK IS AN HOUR BEHIND THE PANEL'S — a remote box without NTP. Its sync arrived
      // just now (`last_seen`), which is the only thing that says it is alive. With the snapshot's own timestamp
      // read instead, this node would be greyed out for ever. (A co-located node, sharing the panel's clock, is
      // covered by [1] — this case is the one that needs `nodeSeen` to reach reconcile at all.)
      snapshots: snap(pNow - 3600),
      describe: {}, panel_settings: {},
    } });
    St.api.events = async () => null;
    await St.Store.poll();
    check("a poll measures how far this browser reads from the panel", Math.abs(U0.clock.skewMs - panelBehindS * S_TO_MS) <= 5000,
      { skewMs: U0.clock.skewMs, expected: panelBehindS * S_TO_MS });
    check("…and the node it just heard from reads live: the browser 10 min out, the node's own clock an hour out",
      St.Store.recon.nodeStatus.n1 === "live", { nodeStatus: St.Store.recon.nodeStatus, generated_at: "panel now − 1 h", last_seen: "panel now" });
    check("panelNow() is the panel's clock, not this browser's", Math.abs(U0.panelNowS() - pNow) <= 5, { panelNowS: U0.panelNowS(), pNow });
  }

  console.log("[3] one verdict for a node");
  {
    const M = await load("js/model.js");   // load(), not a plain import: a plain one ignores --plant and the
                                           // `label` plant then passed with the fix removed (caught re-running them)
    const RS = await import(pathToFileURL(path.join(ROOT, "js/store.js")).href);
    RS.Store.recon = { peers: [], users: [], nodeStatus: { n1: "stale", n2: "live", n3: "live" } };
    check("the server says online, recon says stale → the row says offline too", M.nodeStatusOf({ id: "n1", status: "online" }) === "offline",
      M.nodeStatusOf({ id: "n1", status: "online" }));
    check("the server says offline, recon says live → the row says reporting too", M.nodeStatusOf({ id: "n2", status: "offline" }) === "online",
      M.nodeStatusOf({ id: "n2", status: "offline" }));
    check("a node that never synced still reads awaiting-enroll, whatever recon holds",
      M.nodeStatusOf({ id: "n3", status: "dangling" }) === "dangling" && M.nodeStatusOf({ id: "n3" }) === "dangling",
      M.nodeStatusOf({ id: "n3", status: "dangling" }));
    check("no snapshot at all → the server's own verdict stands", M.nodeStatusOf({ id: "zz", status: "online" }) === "online",
      M.nodeStatusOf({ id: "zz", status: "online" }));
    check("(source) the fleet row takes that verdict — not its own copy of the rule",
      /const st = nodeStatusOf\(n\);/.test(src("js/screen-nodes.js")), "");
    // …and the one gate that must NOT take it: the Migrate door mirrors what plan_rebuild will decide from the
    // server's own fixed window, so it reads `n.status`. Widened to the operator's window it would offer a
    // one-click rollback the server then does not arm (review finding).
    check("(source) the Migrate / Hand-over door still reads the server's own verdict",
      /node\.status === "online" \? html/.test(src("js/sheets-crud.js"))
      && !/nodeStatusOf\(node\)/.test(src("js/sheets-crud.js")), "");
    const seenAt = M.lastHeard({ last_seen: 1700000000 }, { generated_at: 1 });
    check("a node's age comes from the panel's own last-heard-from", seenAt === 1700000000, seenAt);
    check("…the snapshot's own stamp only when a panel is too old to send it", M.lastHeard({}, { generated_at: 42 }) === 42
      && M.lastHeard({}, {}) === null, M.lastHeard({}, { generated_at: 42 }));
    // A label is worse than a wrong verdict here: seen(NaN) renders "NaNd ago" beside a tag that fell back correctly.
    for (const bad of ["soon", {}, null]) {
      const v = M.lastHeard({ last_seen: bad }, { generated_at: 42 });
      check("a last_seen of " + JSON.stringify(bad) + " never reaches the age label", v === 42, { given: bad, got: v });
    }
    check("(source) both node cards age from that one reading",
      /lastHeard\(nrec, snap\)/.test(src("js/screen-nodes.js")) && /lastHeard\(nrec, snap\)/.test(src("js/screen-overview.js")), "");
  }

  console.log("[4] printed ages are read on the clock that stamped them");
  {
    U.clock.skewMs = 300 * S_TO_MS;                       // this browser reads 5 min ahead of the panel
    const stampedNow = U.panelNowS();                      // …so the panel stamps "now" 5 min behind Date.now()
    check("an age the panel stamped reads as just now, not five minutes old", U.ago(stampedNow) === "just now", U.ago(stampedNow));
    check("…and a real five-minute-old stamp still reads five minutes", /5/.test(U.ago(stampedNow - 300)), U.ago(stampedNow - 300));
    U.clock.skewMs = 0;
  }

  console.log("[6] a bad reading changes nothing, and the error leans the safe way");
  {
    const St = await load("js/store.js");
    const U0 = await import(pathToFileURL(path.join(ROOT, "js/util.js")).href);
    const good = nowS() - 60;
    const reply = pn => ({ ok: true, data: { panel_now: pn, roster: roster(),
      nodes: [{ id: "n1", name: "node-one", status: "online", last_seen: good }], snapshots: snap(good),
      describe: {}, panel_settings: {} } });
    St.api.events = async () => null;
    St.api.state = async () => reply(good);
    await St.Store.poll();
    const sane = U0.clock.skewMs;
    for (const bad of ["not-a-number", NaN, null, 0, -1, undefined]) {
      St.api.state = async () => reply(bad);
      await St.Store.poll();
      check("a panel_now of " + String(bad) + " leaves the clock as it was", U0.clock.skewMs === sane,
        { skewMs: U0.clock.skewMs, kept: sane });
    }
    // The offset is measured from a reading stamped before the reply was sent, so it comes out big and panelNow()
    // sits a beat behind the panel's real now — ages read small, a node reports a moment too long, never stale early.
    St.api.state = async () => reply(good);
    await St.Store.poll();
    check("the measurement errs toward reporting, never toward greying a node out early", U0.panelNowS() <= good + 60,
      { panelNowS: U0.panelNowS(), panelStamp: good });
    // …and the same rule one layer down: a receipt time that is not a finite epoch falls back to the snapshot's own
    // timestamp. Read as-is it would go NaN, and every comparison with NaN is false — i.e. every node reads stale.
    for (const bad of ["soon", null, {}]) {
      const r = R.reconcile(roster(), snap(nowS()), Date.now(), { nodeSeen: { n1: bad } });
      check("a last_seen of " + String(JSON.stringify(bad)) + " falls back to the snapshot, it does not read dead",
        r.nodeStatus.n1 === "live", { given: bad, got: r.nodeStatus });
    }
  }

  console.log("[5] an older panel is judged the way it always was");
  {
    const r = R.reconcile(roster(), snap(nowS()), Date.now(), {});   // no panel_now, no last_seen
    check("no panel clock and no receipt time → the snapshot's own timestamp still decides", r.nodeStatus.n1 === "live", r.nodeStatus);
    const r2 = R.reconcile(roster(), snap(nowS() - 120), Date.now(), {});
    check("…and a snapshot that old still reads stale", r2.nodeStatus.n1 === "stale", r2.nodeStatus);
  }
} finally {
  for (const f of written) fs.rmSync(f, { force: true });
}

done(!!PLANT, PLANT);   // exits: 0 when every rule held (or, with --plant, when one went red)
