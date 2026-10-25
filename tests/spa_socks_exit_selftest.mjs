/* Self-test — THE SOCKS5 EXIT in the browser (docs/SOCKS5-EXIT-PLAN.md §6.9, release plan S10 / P3).
 *
 *  [1] health: a SOCKS row is the imported arm WITHOUT the WireGuard handshake test — a TUN has no peer, the node reports
 *      `handshake: null`, and "never answered" would mark every SOCKS exit broken; a dead one reads stalled; on a node too
 *      old for the kind (`why_not: kind_unsupported`, s9a F17) it says to update the node, as a warning, not a fault
 *  [2] the pickers: a group of its own, "Exit via a SOCKS5 proxy" — not "Other exits" — dimmed until it is ok
 *  [3] the words: every code the node's proxy check returns has a sentence; "not allowed" names this node's address;
 *      UDP carried / not carried say what that means for calls, games and QUIC
 *  [4] the save paths (a source gate — they are closures in a rendered sheet): the sheet sends the paste only when it
 *      changed and the keep-sentinel for an untouched password; every list save (nFields) carries `socks` with an EMPTY
 *      paste and password, so saving any other exit never re-submits or blanks a proxy
 *
 * Run: node tests/spa_socks_exit_selftest.mjs     --perturb-<name> plants one regression and expects RED (see PLANTS)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PLANTS = {
  "--perturb-kind": ["routing.js", '  if (why === "kind_unsupported") return { state: "unsupported",', '  if (false) return { state: "unsupported",'],
  "--perturb-group": ["routing.js", '  const socks = imp.filter(x => exitProv(x) === "socks5").map(x => mk(x, exitLabel(x, node)));',
                      '  const socks = [];'],
  "--perturb-why": ["screen-settings.js", '  auth_failed: T("The proxy refused the login — check the user and password."),', ''],
  "--perturb-udp": ["screen-settings.js", '  if (r.udp === true) out.push(["ok",', '  if (false) out.push(["ok",'],
  // the max review's fix round (runs/s10-p3-socks)
  "--perturb-roundtrip": ["screen-settings.js", '  return s.user && /[:@%]/.test(s.user) ?', '  return false ?'],                     // F42
  "--perturb-pubip": ["screen-settings.js", '{ v1: nodePublicIp(node) || T("this node\'s public address") }', '{ v1: ((node || {}).ips || [])[0] || T("this node\'s public address") }'],  // F31
  "--perturb-setup": ["routing.js", '  if (l.setup && !l.error) return', '  if (false) return'],                                         // F13
  "--perturb-reason": ["routing.js", '  const probe = String(((l.no_traffic || {}).why) || (l.trace || {}).err || "").trim();',
                       '  const probe = String((l.trace || {}).err || "").trim();'],                                                // F14
};
// [4]'s plants rewrite the SOURCE the section reads (the save paths are closures in a rendered sheet: read, not run)
const SRC_PLANTS = {
  "--perturb-paste": ['socks_text: sTxt !== sTxt0 ? sTxt.trim() : ""', "socks_text: sTxt.trim()"],
  "--perturb-keep": ['socks_pass: sPass || (((ex || {}).socks || {}).has_pass ? Store.exitPassKeep : "")', "socks_pass: sPass"],
  "--perturb-nfields": ['...(x.socks ? { socks: x.socks, socks_text: "", socks_pass: "" } : {})', "...{}"],
  "--perturb-testsend": ['socks_pass: sPass || (st.has_pass ? Store.exitPassKeep : "")', "socks_pass: sPass"],
  "--perturb-poll404": ['else if (ok && r && r.code === "not_found") {', 'else if (false) {'],                                      // F19
  "--perturb-add": ['if (p2.provider === "profile" || p2.provider === "socks5") return openEdit(rec, true);',
                    'if (p2.provider === "profile") return openEdit(rec, true);'],
};
const MODE = [...Object.keys(PLANTS), ...Object.keys(SRC_PLANTS)].find(k => process.argv.includes(k));
const load = async f => {
  if (!MODE || !PLANTS[MODE] || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, "js", f)).href);
  const src = fs.readFileSync(path.join(ROOT, "js", f), "utf8");
  if (src.split(PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + PLANTS[MODE][1]); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_socks_" + f);
  fs.writeFileSync(tmp, src.replace(PLANTS[MODE][1], PLANTS[MODE][2]));
  try { return await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
};
const R = await load("routing.js");
const S = await load("screen-settings.js");
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
Store.recon.nodeStatus = { n1: "live" };

console.log("[1] a SOCKS exit's health");
const NODE = { id: "n1", name: "n1", ips: ["203.0.113.40"], exit_candidates: [], exits: [] };
const sx = (o = {}, live = {}) => ({ id: "5a5a5a5a", producer: "imported", provider: "socks5", device: "s5x-5a5a5a5a",
  enabled: true, cfg_sig: "c1", socks: { host: "proxy.example", port: 1080, user: "u", has_pass: true }, ...o,
  live: { device: "s5x-5a5a5a5a", up: true, handshake: null, cfg_sig: "c1", trace: { ip: "203.0.113.9" }, udp_ok: true, ...live } });
const h = (o, l) => R.exitHealth(sx(o, l), NODE);
check("up and carrying: ok", h({}, {}).state === "ok", h({}, {}));
check("…with no WireGuard handshake to read (`handshake: null`) and no trace this pass: still not \"never answered\"",
      h({}, { trace: {} }).state !== "nohandshake", h({}, { trace: {} }));
check("judged dead by the node: stalled, worded by its kill-switch",
      h({ killswitch: true }, { no_traffic: { since: 1, why: "the proxy refused the login" } }).state === "stalled");
const old = R.exitHealth(sx({ why_not: "kind_unsupported" }, {}), NODE);
check("on a node too old for the kind: `unsupported`, a warning that says to update", old.state === "unsupported"
      && old.tone === "warn" && /1\.8\.11/.test(old.why), old);
check("SOCKS5 is one of the kinds this panel knows, by name", R.EXIT_KINDS.includes("socks5"));
check("an untitled one is called what it is", R.exitTypeLabel(sx(), NODE) === "SOCKS5 exit", R.exitTypeLabel(sx(), NODE));

console.log("\n[2] the pickers");
const PN = { ...NODE, exits: [sx(), sx({ id: "6b6b6b6b", device: "s5x-6b6b6b6b" }, { up: false })] };
const groups = R.exitOptionGroups(PN, { prefix: "exit|" });
const g = groups.find(x => x.group === "Exit via a SOCKS5 proxy");
check("SOCKS exits have a group of their own", g && g.items.length === 2, groups.map(x => x.group));
check("…not \"Other exits\"", !groups.some(x => x.group === "Other exits"), groups.map(x => x.group));
check("…and one that is not up is dimmed and refused, like any created exit",
      g && /dim/.test((g.items.find(i => i.value === "exit|6b6b6b6b") || {}).className || "")
      && !!(g.items.find(i => i.value === "exit|6b6b6b6b") || {}).refuse, g && g.items);

console.log("\n[3] the words");
for (const c of ["unreachable", "refused", "timeout", "not_socks5", "auth_required", "auth_failed", "not_allowed",
                 "connect_failed", "expired"])
  check("a sentence for `" + c + "`", !!S.socksWhy(c, NODE), c);
check("\"not allowed\" names this node's address, for the provider's allow-list", S.socksWhy("not_allowed", NODE).includes("203.0.113.40"));
const ok = S.socksSays({ why: "", login: true, egress_ip: "203.0.113.9", loc: "FI", udp: true }, NODE);
check("a good check: who the sites see, and that UDP is carried", ok[0][1].includes("203.0.113.9 (FI)") && ok.some(([, t]) => /UDP is carried/.test(t)), ok);
const nu = S.socksSays({ why: "", login: true, egress_ip: "1.2.3.4", udp: false }, NODE);
check("no UDP: says calls and games won't work, and that QUIC falls back", nu.some(([t, x]) => t === "warn" && /QUIC falls back/.test(x)), nu);
check("a failed check: one bad line with its reason", S.socksSays({ why: "auth_failed" }, NODE).length === 1
      && S.socksSays({ why: "auth_failed" }, NODE)[0][0] === "bad");

console.log("\n[3b] the fix round");
const RT = { socks: { host: "gw.example.com", port: 1080, user: "cust:zone@a%b", has_pass: true } };
check("a login with ':' '@' '%' is written as a URL, percent-encoded, so it reads back as the same user — F42",
      S.socksText(RT) === "socks5://" + encodeURIComponent("cust:zone@a%b") + "@gw.example.com:1080", S.socksText(RT));
const PRIV = { ...NODE, ips: ["10.0.0.5", "172.20.1.2", "100.64.3.4", "192.168.1.9", "198.51.100.77"] };
check("\"not allowed\" names the node's PUBLIC address, never a private one NAT hides — F31",
      S.socksWhy("not_allowed", PRIV).includes("198.51.100.77") && !S.socksWhy("not_allowed", PRIV).includes("10.0.0.5"));
const setupH = R.exitHealth(sx({}, { up: false, device: "s5x-5a5a5a5a", setup: "fetching the SOCKS5 tunnel program…" }), NODE);
check("the tunnel program being fetched reads busy (`creating`), not a red failure — F13", setupH.state === "creating" && setupH.tone === "busy", setupH);
const why14 = R.exitHealth(sx({}, { no_traffic: { since: 1, why: "the proxy refused the login — check the user and password" }, trace: { err: "TimeoutError" } }), NODE).why;
check("a stalled SOCKS exit shows the proxy's own reason, not the trace's timeout — F14", /refused the login/.test(why14), why14);

console.log("\n[4] the save paths");
let SET = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
if (SRC_PLANTS[MODE]) {
  if (SET.split(SRC_PLANTS[MODE][0]).length !== 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[MODE][0]); process.exit(1); }
  SET = SET.replace(SRC_PLANTS[MODE][0], SRC_PLANTS[MODE][1]);
}
check("the sheet sends the paste only when it changed", SET.includes('socks_text: sTxt !== sTxt0 ? sTxt.trim() : ""'));
check("…and the keep-sentinel for a password nobody typed (the stored one is kept)",
      SET.includes('socks_pass: sPass || (((ex || {}).socks || {}).has_pass ? Store.exitPassKeep : "")'));
check("every list save carries the SOCKS record with an empty paste and password",
      /\.\.\.\(x\.socks \? \{ socks: x\.socks, socks_text: "", socks_pass: "" \} : \{\}\)/.test(SET));
check("the Test sends the same two fields the save does", SET.includes("socks_text: sTxt.trim(),")
      && SET.includes('socks_pass: sPass || (st.has_pass ? Store.exitPassKeep : "")'));
check("a Test the panel no longer has stops the poll and says so (no button stuck on \"Testing…\") — F19",
      SET.includes('else if (ok && r && r.code === "not_found") {') && SET.includes('setTmsg(T("The panel no longer has that test — run it again."))'));
check("the add button opens the sheet (nothing is stored before the paste)", SET.includes('if (p2.provider === "profile" || p2.provider === "socks5") return openEdit(rec, true);'));

done(MODE, MODE || "");
