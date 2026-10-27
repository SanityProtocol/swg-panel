/* Self-test — ports the torrent filter never cuts, in the browser (docs/RELEASE-1.8.11-PLAN.md § S11c).
 *
 *  [1] portokRead reads what the operator typed the way the panel stores it: "N" / "A-B", 1-65535, ranges merged and
 *      sorted; what it cannot take is listed by name; `ports` counts the ports covered (the > PORTOK_WIDE warning)
 *  [2] the fleet field (source): Save sends p2p_portok only when it changed — the defaults as null (no key), anything else
 *      as typed so the panel names a bad entry; it counts in the Geo section's dirty check and the confirm list; Reset
 *      puts the defaults back; the canonical form is read back after a save
 *  [3] the node field (source): the node's own list is one of the node's fields (published → read back), sent with the
 *      node save, null = the fleet's; it counts in the Network section's dirty check; both fields carry the hints (bad entries, empty, the wide-list warning)
 *
 * Run: node tests/spa_portok_selftest.mjs     --perturb-<name> plants one regression and expects RED (see PLANTS)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PLANTS = {   // [file under ROOT, old, new] — loaded as a module
  "--perturb-nomerge": ["js/model.js", "if (out.length && lo <= out[out.length - 1][1] + 1)", "if (false)"],
  "--perturb-lax": ["js/model.js", "if (!m || lo < 1 || hi > 65535 || lo > hi) bad.push(it);", "if (!m) bad.push(it);"],
};
const SRC_PLANTS = {   // [file under ROOT, old, new] — read as source
  "--perturb-always-send": ["js/screen-settings.js", "        ...(pokDirty() ? { p2p_portok:", "        ...(true ? { p2p_portok:"],
  "--perturb-default-sent": ["js/screen-settings.js", "!r.bad.length && portokSame(r.list, P2P_PORTOK_DEFAULT) ? null : pok", "pok"],
  "--perturb-not-dirty": ["js/screen-settings.js", "    sec === \"geo\" ? geoDirty() || nbDirty() || pokDirty() :", "    sec === \"geo\" ? geoDirty() || nbDirty() :"],
  "--perturb-no-reseed": ["js/screen-settings.js", "    setPok((((Store.panelSettings) || {}).p2p_portok || P2P_PORTOK_DEFAULT).join(\", \"));", ""],
  "--perturb-node-unsent": ["js/screen-settings.js", "        p2p_portok: e.p2p_portok ?? null,", ""],
  "--perturb-node-field": ["js/screen-settings.js", "    p2p_portok: Array.isArray(n.p2p_portok) ? n.p2p_portok.join(\", \") : null,", ""],
  "--perturb-node-clean": ["js/screen-settings.js", "\"default_routing_exit_ips\", \"p2p\", \"p2p_portok\"], links:", "\"default_routing_exit_ips\", \"p2p\"], links:"],
  "--perturb-no-warn": ["js/screen-settings.js", "${r.ports > PORTOK_WIDE ? html", "${false ? html"],
};
const MODE = [...Object.keys(PLANTS), ...Object.keys(SRC_PLANTS)].find(k => process.argv.includes(k));
const load = async f => {
  if (!MODE || !PLANTS[MODE] || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, f)).href);
  const src = fs.readFileSync(path.join(ROOT, f), "utf8");
  if (src.split(PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + PLANTS[MODE][1]); process.exit(1); }
  const tmp = path.join(ROOT, path.dirname(f), "__perturb_portok_" + path.basename(f));
  fs.writeFileSync(tmp, src.replace(PLANTS[MODE][1], PLANTS[MODE][2]));
  try { return await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
};
const src = f => { let t = fs.readFileSync(path.join(ROOT, f), "utf8");
  if (MODE && SRC_PLANTS[MODE] && SRC_PLANTS[MODE][0] === f) {
    if (t.split(SRC_PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[MODE][1]); process.exit(1); }
    t = t.replace(SRC_PLANTS[MODE][1], SRC_PLANTS[MODE][2]);
  }
  return t; };
const j = JSON.stringify;

console.log("[1] portokRead");
{
  const { portokRead, PORTOK_WIDE } = await load("js/model.js");
  const r = portokRead("51820 1194, 3478-3481 3480-3500 1195");
  check("merged, sorted, adjacent ports joined", j(r.list) === j(["1194-1195", "3478-3500", "51820"]), r.list);
  check("the ports it covers", r.ports === 2 + 23 + 1, r.ports);
  const b = portokRead("x, 0, 70000, 9-8, 443");
  check("what it cannot take, by name", j(b.bad) === j(["x", "0", "70000", "9-8"]) && j(b.list) === j(["443"]), b);
  check("a wide list crosses the warning line", portokRead("1024-65535").ports > PORTOK_WIDE && portokRead("1194, 51820").ports <= PORTOK_WIDE);
}

console.log("\n[2] the fleet field");
{
  const s = src("js/screen-settings.js");
  check("Save sends it only when it changed", s.includes("        ...(pokDirty() ? { p2p_portok:"));
  check("…the defaults as null (no key), anything else as typed", s.includes("!r.bad.length && portokSame(r.list, P2P_PORTOK_DEFAULT) ? null : pok"));
  check("it counts in the Geo section's dirty check", s.includes("    sec === \"geo\" ? geoDirty() || nbDirty() || pokDirty() :"));
  check("…and in the confirm list", s.includes("if (pokDirty()) out.push(T(\"Ports the torrent filter never cuts — updated\"));"));
  check("Reset puts the defaults back", s.includes("onClick=${() => setPok(P2P_PORTOK_DEFAULT.join(\", \"))}"));
  check("the canonical form is read back after a save", s.includes("    setPok((((Store.panelSettings) || {}).p2p_portok || P2P_PORTOK_DEFAULT).join(\", \"));"));
}

console.log("\n[3] the node field");
{
  const s = src("js/screen-settings.js");
  check("the node's own list is one of its fields (null = the fleet's)", s.includes("    p2p_portok: Array.isArray(n.p2p_portok) ? n.p2p_portok.join(\", \") : null,"));
  check("…and counts in the Network section's dirty check (else Save stays off)", s.includes("\"default_routing_exit_ips\", \"p2p\", \"p2p_portok\"], links:"));
  check("…sent with the node save", s.includes("        p2p_portok: e.p2p_portok ?? null,"));
  check("both fields carry the hints", s.split("<${PortokHints} text=").length - 1 === 2);
  check("…which warn on a wide list", s.includes("${r.ports > PORTOK_WIDE ? html"));
}
done(MODE);
