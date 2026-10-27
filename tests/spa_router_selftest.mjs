/* Self-test — the "Router" mark in the browser (docs/RELEASE-1.8.11-PLAN.md § S11b).
 *
 *  [1] the mark survives reconcile(): reconcile.js rebuilds every peer from a whitelist, and a field it does not name does
 *      not exist in the SPA (the `private` lesson) — a marked peer arrives `shared: true`, an unmarked one `false`
 *  [2] routerCapable: a wg or awg deployment can be a router; a device with only keyless ones (WDTT / csqtt) cannot; one
 *      already marked keeps the switch, so the mark can be taken off
 *  [3] the callers (source): the device sheet shows the switch by routerCapable, counts it in Save's dirty check and sends
 *      `shared`; the peer list tags a marked device; the Protection card's Torrents bubble — and only that one — carries the
 *      "mark it as a router" line
 *
 * Run: node tests/spa_router_selftest.mjs     --perturb-<name> plants one regression and expects RED (see PLANTS)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PLANTS = {   // [file under ROOT, old, new] — loaded as a module
  "--perturb-recon": ["reconcile.js", "      shared: p.shared === true,", "      _shared: p.shared === true,"],
  "--perturb-keyless": ["js/model.js", '(p.targets || []).some(t => ["wg", "awg"].includes(targetType(t)))', "(p.targets || []).length > 0"],
  "--perturb-stuck": ["js/model.js", "!!p && (p.shared === true || (p.targets", "!!p && ((p.targets"],
};
const SRC_PLANTS = {   // [file under ROOT, old, new] — read as source
  "--perturb-sheet-shown": ["js/sheets-crud.js", "    ${router || routerCapable(live) ? html`<div class=\"field\">", "    ${false ? html`<div class=\"field\">"],
  "--perturb-sheet-dirty": ["js/sheets-crud.js", "    || (router !== (peer.shared === true))\n", ""],
  "--perturb-sheet-send": ["js/sheets-crud.js", "api.peerUpdate({ peer_id: peer.id, shared: router })", "api.peerUpdate({ peer_id: peer.id })"],
  "--perturb-tag": ["js/grids.js", "${nm}${priv}${rtr}${chip}", "${nm}${priv}${chip}"],
  "--perturb-foot-scan": ["js/screen-overview.js", "who: who.scan });", "who: who.scan, foot: T(\"x\") });"],
  "--perturb-foot-pass": ["js/screen-overview.js", "color=${t.color} foot=${t.foot}/>", "color=${t.color}/>"],
};
const MODE = [...Object.keys(PLANTS), ...Object.keys(SRC_PLANTS)].find(k => process.argv.includes(k));
const load = async f => {
  if (!MODE || !PLANTS[MODE] || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, f)).href);
  const src = fs.readFileSync(path.join(ROOT, f), "utf8");
  if (src.split(PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + PLANTS[MODE][1]); process.exit(1); }
  const tmp = path.join(ROOT, path.dirname(f), "__perturb_router_" + path.basename(f));
  fs.writeFileSync(tmp, src.replace(PLANTS[MODE][1], PLANTS[MODE][2]));
  try { return await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
};
const src = f => { let t = fs.readFileSync(path.join(ROOT, f), "utf8");
  if (MODE && SRC_PLANTS[MODE] && SRC_PLANTS[MODE][0] === f) {
    if (t.split(SRC_PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[MODE][1]); process.exit(1); }
    t = t.replace(SRC_PLANTS[MODE][1], SRC_PLANTS[MODE][2]);
  }
  return t; };

console.log("[1] the mark survives reconcile()");
{
  const { reconcile } = await load("reconcile.js");
  const r = reconcile({ version: 1, users: { u: { name: "Carol" } },
    peers: { pr: { id: "pr", user_id: "u", pubkey: "k1", shared: true, targets: [] },
             pn: { id: "pn", user_id: "u", pubkey: "k2", targets: [] } } }, {});
  const got = id => (r.peers || []).find(x => x.id === id) || {};
  check("a marked peer reaches the SPA as a router", got("pr").shared === true, got("pr").shared);
  check("…an unmarked one as not, never undefined", got("pn").shared === false, got("pn").shared);
}

console.log("\n[2] who can be a router");
{
  const { routerCapable } = await load("js/model.js");
  const t = type => ({ node: "n1", iface: type + "0", type, ip: "10.8.0.2" });
  check("a wg deployment can", routerCapable({ targets: [t("wg")] }) === true);
  check("an awg deployment can", routerCapable({ targets: [t("awg")] }) === true);
  check("a mixed device (WDTT + wg) can", routerCapable({ targets: [t("wdtt"), t("wg")] }) === true);
  check("only keyless deployments (WDTT, csqtt) cannot", routerCapable({ targets: [t("wdtt"), t("csqtt")] }) === false);
  check("…unless already marked — the switch stays to take it off", routerCapable({ shared: true, targets: [t("wdtt")] }) === true);
  check("no device, no switch", routerCapable(null) === false && routerCapable({ targets: [] }) === false);
}

console.log("\n[3] the callers");
{
  const sheet = src("js/sheets-crud.js");
  check("the device sheet shows the switch by routerCapable", sheet.includes("    ${router || routerCapable(live) ? html`<div class=\"field\">"));
  check("…counts it in Save's dirty check", sheet.includes("    || (router !== (peer.shared === true))\n"));
  check("…and sends it", sheet.includes("api.peerUpdate({ peer_id: peer.id, shared: router })"));
  check("the peer list tags a marked device", src("js/grids.js").includes("${nm}${priv}${rtr}${chip}"));
  const ov = src("js/screen-overview.js");
  const footAt = ov.split("tiles.push(").slice(1).map(s => s.split(/\n  tiles\.push|\n  \/\/ /)[0]).filter(s => s.includes("foot:"));
  check("the Torrents bubble carries the router line — and no other tile does",
    footAt.length === 1 && footAt[0].includes("Torrents caught") && footAt[0].includes("Mark that device as a router"), footAt.map(s => s.slice(0, 60)));
  check("…and the bubble renders it", ov.includes("color=${t.color} foot=${t.foot}/>") && ov.includes("${foot ? html`<div class=\"prot-who-foot\">${foot}</div>` : null}"));
}
done(MODE);
