/* Self-test — each interface's own Torrents / P2P in the browser (docs/IFACE-P2P-PICK-PLAN.md §5 + § Refresh 1.8.11 Q-B, S11).
 *
 *  [1] the rows follow the SERVER'S policy: under "Each interface decides" Block · Allow — not checked · Allow, only out this
 *      server's own address · Route through … (the exits, the other nodes — no mesh link refused); under any other policy the
 *      allow / route rows are refused naming where to change it, and "As the server — <its label>" stands for no choice
 *  [2] value ↔ record: Block is "torrents" in block[] (and no p2p), "" is neither, a route is {action, node | exit_id};
 *      every non-Block pick takes "torrents" out of block[]
 *  [3] the hints: the row's own sentence; a stored choice under a non-iface server is said (warnish); Q-B — a SOCKS5 exit
 *      whose udp_ok is not true (false, or null: not proven yet) says DHT and µTP cannot pass it, in BOTH pickers (one
 *      builder); a WARP / device exit or a SOCKS exit carrying UDP says nothing
 *  [4] the draft: egressInit reads `p2p`, egressBody sends it in every mode (null: none) — a WDTT/csqtt restart re-posts
 *      egressBody(egressInit(cfg)); blockActiveN counts a choice as one filter only under "Each interface decides"
 *  [5] the callers (source): all four sheets hand BlockTraffic `p2p` + `onP2p` and count it; the Torrents chip is gone
 *      where the row is shown
 *
 * Run: node tests/spa_iface_p2p_selftest.mjs     --perturb-<name> plants one regression and expects RED (see PLANTS)
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { check, done, ROOT } from "./spa_env.mjs";

const PLANTS = {
  "--perturb-allow-anywhere": ["routing.js", "  const deny = it => iface ? it : { ...it, refuse: elsewhere, className: \"dim\" };", "  const deny = it => it;"],
  "--perturb-block-kept": ["routing.js", "    return [a === \"block\" ? [...rest, \"torrents\"] : rest,", "    return [a === \"block\" ? [...rest, \"torrents\"] : (block || []),"],
  "--perturb-block-p2p": ["routing.js", "a === \"block\" || a === \"\" ? null : p2pRec(a)]; };", "a === \"\" ? null : p2pRec(a)]; };"],
  "--perturb-udp-false-only": ["routing.js", "if (x && exitProv(x) === \"socks5\" && (x.live || {}).udp_ok !== true)", "if (x && exitProv(x) === \"socks5\" && (x.live || {}).udp_ok === false)"],
  "--perturb-udp-any": ["routing.js", "if (x && exitProv(x) === \"socks5\" && (x.live || {}).udp_ok !== true)", "if (x && (x.live || {}).udp_ok !== true)"],
  "--perturb-init": ["routing.js", "    p2p: m.p2p && m.p2p.action ? { ...m.p2p } : null };", "    p2p: null };"],
  "--perturb-body": ["routing.js", "  p2p: eg.p2p || null });", "  });"],
  "--perturb-count-anywhere": ["routing.js", "  const own = p2p && p2p.action && nrec.p2p_eff === \"iface\" ? 1 : 0;", "  const own = p2p && p2p.action ? 1 : 0;"],
  "--perturb-draft-exit": ["routing.js", "(byId((node || {}).exits) || byId(draft))", "(byId((node || {}).exits))"],
  "--perturb-noside-warn": ["routing.js", "  return { iface, cur, opts, rec, hint, warn: rec && !iface ? elsewhere : \"\", pick };", "  return { iface, cur, opts, rec, hint, warn: \"\", pick };"],
};
const SRC_PLANTS = {
  "--perturb-caller": ["turn.js", "<${BlockTraffic} node=${node} value=${blk} onChange=${setBlk} p2p=${eg.p2p} onP2p=${p => setEg(e => ({ ...e, p2p: p }))}/>",
                       "<${BlockTraffic} node=${node} value=${blk} onChange=${setBlk}/>"],
  "--perturb-chip": ["routing.js", " && !(onP2p && c.id === \"torrents\"));", ");"],
  "--perturb-settings-hints": ["screen-settings.js", "            ${p2pTargetHints(curRec, node, exits)}", ""],
};
const MODE = [...Object.keys(PLANTS), ...Object.keys(SRC_PLANTS)].find(k => process.argv.includes(k));
const load = async f => {
  if (!MODE || !PLANTS[MODE] || PLANTS[MODE][0] !== f) return import(pathToFileURL(path.join(ROOT, "js", f)).href);
  const src = fs.readFileSync(path.join(ROOT, "js", f), "utf8");
  if (src.split(PLANTS[MODE][1]).length !== 2) { console.log("ANCHOR MISSING: " + PLANTS[MODE][1]); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_p2pi_" + f);
  fs.writeFileSync(tmp, src.replace(PLANTS[MODE][1], PLANTS[MODE][2]));
  try { return await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
};
const src = f => { let t = fs.readFileSync(path.join(ROOT, "js", f), "utf8");
  if (MODE && SRC_PLANTS[MODE] && SRC_PLANTS[MODE][0] === f) {
    if (t.split(SRC_PLANTS[MODE][1]).length < 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[MODE][1]); process.exit(1); }
    t = t.split(SRC_PLANTS[MODE][1]).join(SRC_PLANTS[MODE][2]);
  }
  return t; };
const R = await load("routing.js");
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);

const WARP = { id: "aaaa0001", producer: "imported", provider: "warp", device: "wgx-aaaa0001", enabled: true, label: "WARP",
  live: { device: "wgx-aaaa0001", up: true, handshake: 1, trace: { ip: "203.0.113.9" } } };
const sx = (id, udp) => ({ id, producer: "imported", provider: "socks5", device: "s5x-" + id, enabled: true, label: "Proxy " + id, cfg_sig: "c",
  socks: { host: "proxy.example", port: 1080 }, live: { device: "s5x-" + id, up: true, handshake: null, cfg_sig: "c", trace: { ip: "203.0.113.8" }, ...(udp === undefined ? {} : { udp_ok: udp }) } });
const N1 = { id: "n1", name: "node-a", p2p_eff: "iface", exits: [WARP, sx("5a5a5a5a", false), sx("6b6b6b6b", null), sx("7c7c7c7c", true)],
  mesh_peers: [{ peer: "n2", iface: "swg_b" }], ips: [], exit_candidates: [] };
const N2 = { id: "n2", name: "node-b", p2p_eff: "direct", exits: [], ips: [], exit_candidates: [] };
const N3 = { id: "n3", name: "node-c", p2p_eff: "block", exits: [], ips: [], exit_candidates: [] };
Store.nodes = [N1, N2, N3];
Store.recon.nodeStatus = { n1: "live", n2: "live", n3: "live" };
const flat = opts => opts.flatMap(o => o.items ? o.items : [o]);

console.log("[1] the rows follow the server's policy");
let M = R.ifaceP2pModel(N1, [], null);
const vals = flat(M.opts).map(o => o.value);
check("under iface: Block · not checked · Direct · every exit · the other nodes", ["block", "", "direct", "dev:aaaa0001", "dev:5a5a5a5a", "exit:n2", "exit:n3"]
      .every(v => vals.includes(v)), vals);
check("…the second row reads \"Allow — not checked\"", flat(M.opts)[1].label === "Allow — not checked", flat(M.opts)[1]);
check("…a node with no mesh link is refused, a linked one is not", !!flat(M.opts).find(o => o.value === "exit:n3").refuse
      && !flat(M.opts).find(o => o.value === "exit:n2").refuse);
check("…the allow / route rows are choosable", !flat(M.opts).find(o => o.value === "direct").refuse && !flat(M.opts).find(o => o.value === "dev:aaaa0001").refuse);
const M2 = R.ifaceP2pModel(N2, [], null);
const deny2 = flat(M2.opts).filter(o => !["block", ""].includes(o.value));
check("under another policy: every allow / route row refused, naming where to change it", deny2.length >= 2 && deny2.every(o =>
      o.refuse && o.refuse.includes("Each interface decides") && o.refuse.includes("node-b") && o.refuse.includes("Settings ▸ Network ▸ Filters & abuse")), deny2.map(o => o.refuse));
check("…Block stays choosable (it counts everywhere)", !flat(M2.opts)[0].refuse && flat(M2.opts)[0].value === "block");
check("…and no choice reads \"As the server — <its label>\"", flat(M2.opts)[1].label === "As the server — this server's address only", flat(M2.opts)[1].label);

console.log("\n[2] value ↔ record");
check("\"torrents\" in block[] reads Block", R.ifaceP2pModel(N1, ["smtp", "torrents"], null).cur === "block");
check("a route reads its target", R.ifaceP2pModel(N1, ["smtp"], { action: "dev", exit_id: "aaaa0001" }).cur === "dev:aaaa0001"
      && R.ifaceP2pModel(N1, [], { action: "exit", node: "n2" }).cur === "exit:n2" && R.ifaceP2pModel(N1, [], { action: "direct" }).cur === "direct");
check("neither reads \"\"", R.ifaceP2pModel(N1, ["smtp"], null).cur === "");
const P = R.ifaceP2pModel(N1, ["smtp", "torrents"], null).pick;
const j = x => JSON.stringify(x);
check("Block → torrents added, no p2p", j(R.ifaceP2pModel(N1, ["smtp"], { action: "direct" }).pick("block")) === j([["smtp", "torrents"], null]));
check("not checked → torrents out, no p2p", j(P("")) === j([["smtp"], null]), P(""));
check("a route → torrents out, the record", j(P("exit:n2")) === j([["smtp"], { action: "exit", node: "n2" }])
      && j(P("dev:aaaa0001")) === j([["smtp"], { action: "dev", exit_id: "aaaa0001" }]) && j(P("direct")) === j([["smtp"], { action: "direct" }]), P("exit:n2"));

console.log("\n[3] the hints");
check("Block / none / Direct / a route each say their own sentence", new Set([R.ifaceP2pModel(N1, ["torrents"], null).hint, R.ifaceP2pModel(N1, [], null).hint,
      R.ifaceP2pModel(N1, [], { action: "direct" }).hint, R.ifaceP2pModel(N1, [], { action: "exit", node: "n2" }).hint]).size === 4);
check("a route's sentence names its target", R.ifaceP2pModel(N1, [], { action: "exit", node: "n2" }).hint.includes("node-b"));
check("a stored choice under a non-iface server is said", R.ifaceP2pModel(N2, [], { action: "direct" }).warn.includes("Each interface decides")
      && !R.ifaceP2pModel(N1, [], { action: "direct" }).warn && !R.ifaceP2pModel(N2, [], null).warn);
const TCP = "This exit carries TCP only — DHT and µTP can't pass it, so torrents find fewer peers and download slower.";
const said = rec => R.p2pTargetHints(rec, N1).some(v => JSON.stringify(v).includes(TCP));
check("Q-B: a SOCKS5 exit with udp_ok false → the TCP-only hint", said({ action: "dev", exit_id: "5a5a5a5a" }));
check("Q-B: …udp_ok null (not proven yet) → the hint too", said({ action: "dev", exit_id: "6b6b6b6b" }));
check("Q-B: …udp_ok true → none", !said({ action: "dev", exit_id: "7c7c7c7c" }));
check("Q-B: a WARP exit, a node, Direct → none", !said({ action: "dev", exit_id: "aaaa0001" }) && !said({ action: "exit", node: "n2" }) && !said({ action: "direct" }));
const ss = src("screen-settings.js");
check("Q-B: the Settings picker shows the same hints (one builder)", ss.includes("${p2pTargetHints(curRec, node, exits)}"));
check("Q-B: a SOCKS5 exit added in this same edit (in the draft only, never checked) → the hint (review F37)",
      R.p2pTargetHints({ action: "dev", exit_id: "8d8d8d8d" }, N1, [sx("8d8d8d8d")]).some(v => JSON.stringify(v).includes(TCP)));
check("…a node that drops what others send it is warned about", R.p2pTargetHints({ action: "exit", node: "n3" }, N1).length === 1);

console.log("\n[4] the draft");
for (const m of [{}, { egress_mode: "smart", routing: [] }, { egress_mode: "exit", exit_id: "x" }, { egress_mode: "forward", egress_node: "n2" }]) {
  const eg = R.egressInit({ ...m, p2p: { action: "exit", node: "n2" } });
  check("egressInit reads p2p, egressBody sends it (" + (m.egress_mode || "auto") + ")", j(R.egressBody(eg).p2p) === j({ action: "exit", node: "n2" }), R.egressBody(eg));
  check("…none → null (" + (m.egress_mode || "auto") + ")", R.egressBody(R.egressInit(m)).p2p === null && "p2p" in R.egressBody(R.egressInit(m)));
}
Store.blockCatalog = null;
check("blockActiveN counts a choice as one filter under iface", R.blockActiveN("n1", ["smtp"], { action: "direct" }) === 2 && R.blockActiveN("n1", ["smtp"], null) === 1);
check("…and not under another policy", R.blockActiveN("n2", ["smtp"], { action: "direct" }) === 1);

console.log("\n[5] the callers");
const callers = src("iface.js") + src("turn.js");
check("all four sheets hand BlockTraffic p2p + onP2p", callers.split("<${BlockTraffic} node=${node} value=${blk} onChange=${setBlk} p2p=${eg.p2p} onP2p=${p => setEg(e => ({ ...e, p2p: p }))}/>").length - 1 === 4);
check("…and count it", callers.split("blockActiveN(node, blk, eg.p2p)").length - 1 === 8);
check("the Torrents chip is gone where the row is shown", src("routing.js").includes('!MECH_UNBUILT.has(c.id) && !(onP2p && c.id === "torrents"));'));
done(MODE);
