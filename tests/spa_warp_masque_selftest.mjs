/* Self-test — WARP over MASQUE in the browser (docs/WARP-MASQUE-PLAN.md §4.8, §6 P3; 1.8.12 item 17b).
 *
 *  [1] health: a MASQUE row is judged as a WARP exit with no WireGuard handshake; on a node that cannot run it the row says
 *      which update (and CPU) it needs, not SOCKS5's; a switch that has not happened yet (`still on WireGuard: …` / `still on
 *      MASQUE: …`, T19) reads as the exit still carrying with the switch pending — a warning while it is refused, progress
 *      while the tunnel program is fetched — never "failed"
 *  [2] the names and the pickers: "WARP exit (MASQUE)", and both WARP kinds in the one WARP group
 *  [3] the save paths (source: closures in a rendered sheet): every list save carries `transport`, the sheet's change test
 *      sees a transport or kind change, a switch is confirmed with the kill-switch's words (Q11), a new WARP exit opens the
 *      sheet (the transport is chosen at create, Q1), the escrow row serves both WARP kinds, and a MASQUE exit offers no
 *      "Connect from"
 *
 * Run: node tests/spa_warp_masque_selftest.mjs     --perturb-<name> plants one regression and expects RED (see PLANTS)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PLANTS = {
  "--perturb-switch": ["routing.js", "  if (sw) {", "  if (false) {"],
  "--perturb-kindmsg": ["routing.js", '    why: exitProv(ex) === "warp-masque" ? T("This node cannot run WARP over MASQUE', '    why: false ? T("This node cannot run WARP over MASQUE'],
  "--perturb-group": ["routing.js", "  const warp = imp.filter(exitIsWarp).map(", '  const warp = imp.filter(x => exitProv(x) === "warp").map('],
  "--perturb-busy": ["routing.js", 'tone: fetching ? "busy" : "warn"', 'tone: "warn"'],
};
const SRC_PLANTS = {
  "--perturb-nfields": ["...(x.transport ? { transport: x.transport } : {}),", ""],
  "--perturb-dirty": ['["label", "dial_src", "licence", "provider", "transport"]', '["label", "dial_src", "licence"]'],
  "--perturb-confirm": ["const save = () => (!switching ? commit(false) : openConfirm({", "const save = () => (true ? commit(false) : openConfirm({"],
  "--perturb-create": ['    if (p2.provider === "warp") return openEdit(rec, true);', ""],
  "--perturb-escrow": ["!exitIsWarp(ex)) return null;", 'exitProv(ex) !== "warp") return null;'],
};
const MODE = [...Object.keys(PLANTS), ...Object.keys(SRC_PLANTS)].find(k => process.argv.includes(k));
const load = async f => {
  if (!MODE || !PLANTS[MODE] || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, "js", f)).href);
  const src = fs.readFileSync(path.join(ROOT, "js", f), "utf8");
  if (src.split(PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + PLANTS[MODE][1]); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_mqx_" + f);
  fs.writeFileSync(tmp, src.replace(PLANTS[MODE][1], PLANTS[MODE][2]));
  try { return await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
};
const R = await load("routing.js");
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
Store.recon.nodeStatus = { n1: "live" };

console.log("[1] a MASQUE exit's health");
const NODE = { id: "n1", name: "n1", ips: ["203.0.113.40"], exit_candidates: [], exits: [] };
const mx = (o = {}, live = {}) => ({ id: "7a7a7a7a", producer: "imported", provider: "warp-masque", transport: "h3",
  device: "wgx-7a7a7a7a", enabled: true, cfg_sig: "c1", ...o,
  live: { device: "wgx-7a7a7a7a", provider: "warp-masque", up: true, handshake: null, cfg_sig: "c1",
          trace: { ip: "104.28.1.2", warp: "on" }, colo: "DME", freeze: "pass", ...live } });
const h = (o, l) => R.exitHealth(mx(o, l), NODE);
check("up and carrying over MASQUE: ok — no WireGuard handshake asked of it", h({}, {}).state === "ok", h({}, {}));
const un = h({ why_not: "kind_unsupported" }, {});
check("on a node that cannot run it: a warning naming 1.8.12 and the CPU, not the SOCKS5 sentence",
      un.state === "unsupported" && un.tone === "warn" && /1\.8\.12/.test(un.why) && /amd64/.test(un.why) && !/SOCKS5/.test(un.why), un);
const s5 = R.exitHealth({ ...mx({ why_not: "kind_unsupported" }), provider: "socks5" }, NODE);
check("…while a SOCKS5 exit there still names 1.8.11", /1\.8\.11/.test(s5.why), s5);
const pend = h({ provider: "warp-masque" }, { provider: "warp", error: "still on WireGuard: Cloudflare did not answer (timed out)", retry_in: 120 });
check("⚠️ a switch to MASQUE that has not happened yet: still carrying (dot up), a warning — never `failed` (T19, F23)",
      pend.state === "switching" && pend.tone === "warn" && pend.dot === "up", pend);
check("…saying it still runs over WireGuard, why, and when it tries again",
      /still runs over WireGuard/.test(pend.why) && /timed out/.test(pend.why) && /2 min/.test(pend.why), pend.why);
const fetch = h({}, { provider: "warp", error: "still on WireGuard: fetching the MASQUE tunnel program…" });
check("…and while the tunnel program is fetched: progress (busy), not a warning (F31)", fetch.state === "switching" && fetch.tone === "busy", fetch);
const back = h({ provider: "warp" }, { provider: "warp-masque", error: "still on MASQUE: Cloudflare refused the key" });
check("the way back says it still runs over MASQUE", back.state === "switching" && /still runs over MASQUE/.test(back.why), back);
const stall = h({}, { provider: "warp", error: "still on WireGuard: x", no_traffic: { since: 1, why: "no answer" } });
check("a pending switch on a tunnel that carries nothing reads as the stall it is, the switch said beside it",
      stall.state === "stalled" && /switch to MASQUE/.test(stall.why), stall);
check("any other error is still a failure", h({}, { error: "Cloudflare no longer accepts this account — re-create the exit" }).state === "failed");

console.log("\n[2] the names and the pickers");
check("the kind is one this panel knows, by name", R.EXIT_KINDS.includes("warp-masque"));
check("an untitled one is called what it is", R.exitTypeLabel(mx(), NODE) === "WARP exit (MASQUE)" && R.exitDefaultTitle(mx()) === "WARP exit (MASQUE)",
      [R.exitTypeLabel(mx(), NODE), R.exitDefaultTitle(mx())]);
check("…WARP+ when it has a licence", R.exitTypeLabel(mx({ licence: "k" }), NODE) === "WARP+ exit (MASQUE)");
const PN = { ...NODE, exits: [mx(), { ...mx({ id: "8b8b8b8b", device: "wgx-8b8b8b8b", provider: "warp" }) }] };
const groups = R.exitOptionGroups(PN, { prefix: "exit|" });
const wg = groups.find(g => g.items.some(i => i.value === "exit|8b8b8b8b"));
check("both WARP kinds sit in the one WARP group — never \"Other exits\"",
      wg && wg.items.some(i => i.value === "exit|7a7a7a7a") && !groups.some(g => g.group === "Other exits"), groups.map(g => g.group));

console.log("\n[3] the save paths");
let SET = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
if (SRC_PLANTS[MODE]) {
  if (SET.split(SRC_PLANTS[MODE][0]).length !== 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[MODE][0]); process.exit(1); }
  SET = SET.replace(SRC_PLANTS[MODE][0], SRC_PLANTS[MODE][1]);
}
const sheet = SET.slice(SET.indexOf("function ExitEditSheet("), SET.indexOf("function WarpTransport("));
check("the sheet is locatable", sheet.length > 2000, sheet.length);
check("every list save carries a MASQUE exit's transport (or saving another exit resets it to HTTP/3)",
      SET.includes("...(x.transport ? { transport: x.transport } : {}),"));
check("the sheet's change test sees a transport or a kind change", sheet.includes('["label", "dial_src", "licence", "provider", "transport"]'));
check("a switch is confirmed first, in the kill-switch's own words (Q11)", sheet.includes("const save = () => (!switching ? commit(false) : openConfirm({")
      && sheet.includes("For a few seconds the kill-switch holds this exit's users.")
      && sheet.includes("For a few seconds this exit's users leave by this node's own address."));
check("…and the confirm and the sheet close together on success", sheet.includes("viaConfirm ? closeModals(2) : (onClose || closeModal)();"));
check("a new WARP exit opens the sheet: WireGuard or MASQUE is chosen at create (Q1)", SET.includes('    if (p2.provider === "warp") return openEdit(rec, true);'));
check("the escrow row serves both WARP kinds (§4.11)", SET.includes("!exitIsWarp(ex)) return null;"));
check("a MASQUE exit offers no \"Connect from\" (usque dials from the node's default source)",
      sheet.includes("${isDialin || isSocks || isMasque || fill ? null : html`<div class=\"field\"><label>${T(\"Connect from\")}</label>"));

done(MODE, MODE || "");
