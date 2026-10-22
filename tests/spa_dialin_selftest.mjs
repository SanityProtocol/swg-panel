/* Self-test: the exits screen reads a DIAL-IN exit as one (docs/LISTEN-EXIT-PLAN.md §2.4), and names every exit kind
 * instead of reading "not a profile" as WARP (docs/SOCKS5-EXIT-PLAN.md T6).
 *
 *  [1] the edit box renders a dial-in profile as a server config — ListenPort, no Endpoint — and it ROUND-TRIPS through
 *      the panel's real parser to the same profile. Today's box printed `Endpoint = ` on every profile, so the first
 *      edit of a dial-in exit sent an empty Endpoint back and the save refused it. A dial-out box is unchanged.
 *  [2] the row's statuses: waiting for the router (no handshake), connected but carrying nothing (NAT on the router),
 *      up with the router's address, and a node too old for dial-in exits (an error and no `listen_port`)
 *  [3] a kind this panel does not know is not offered as WARP, not labelled WARP, not escrowed as WARP
 *  [4] (S9b) the router's config, built from the stored profile, parses through the same parser as a DIAL-OUT profile that
 *      dials the node: its peer is the node's public key, its address the router's half of the pair, Endpoint the node's
 *      host and port, the AmneziaWG set identical (3.1 included)
 *  [5] (S9c) the router's key in the config store: nothing is kept with the store off, and a locked vault says so; kept, it
 *      goes to the node's bucket as ciphertext against the router's public key, and reads back as both keys the config
 *      needs; a blob under another bucket key reads "sealed", an exit the panel no longer has reads "none", a dead panel
 *      reads "unreachable"
 *
 * Run: node tests/spa_dialin_selftest.mjs
 *      --perturb-text    the box prints `Endpoint = ` for a dial-in profile again        → RED [1]
 *      --perturb-status  the row has no dial-in arm (the dial-out sentences)              → RED [2]
 *      --perturb-old     the old-node read removed                                        → RED [2]
 *      --perturb-warp    the WARP group is "not profile" again                            → RED [3]
 *      --perturb-rconf   the router's address is the node's own (no +1)                  → RED [4]
 *      --perturb-keepn   the node's public key is left out of the kept blob                → RED [5]
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { ROOT, check, done } from "./spa_env.mjs";

// Keyed by the whole flag, written out: runperturb.py finds a gate's plants by their quoted flags — one list, no twin.
const _flag = process.argv.find(a => a.startsWith("--" + "perturb"));
const PLANTS = {
  "--perturb-text": ["screen-settings.js", '...(din ? [] : ["Endpoint = " + (p.endpoint || "")]),', '"Endpoint = " + (p.endpoint || ""),'],
  "--perturb-status": ["routing.js", 'if (exitIsDialin(ex) && !(l.handshake > 0 && l.handshake <= 180)) return', 'if (false) return'],
  "--perturb-old": ["routing.js", 'if (l.error && exitIsDialin(ex) && !l.listen_port && (!ex.cfg_sig || l.cfg_sig === ex.cfg_sig)) return', 'if (false) return'],
  "--perturb-rconf": ["screen-settings.js", 'address: subnetServerAddr(prof.address + "/32")', 'address: prof.address + "/32"'],
  "--perturb-warp": ["routing.js", 'imp.filter(x => exitProv(x) === "warp")', 'imp.filter(x => x.provider !== "profile")'],
  "--perturb-keepn": ["crypto.js", "JSON.stringify({ k: routerPriv, n: nodePub })", "JSON.stringify({ k: routerPriv })"],
};
if (_flag && !PLANTS[_flag]) { console.log("unknown plant " + _flag); process.exit(2); }
const PLANT = _flag || "";
const made = [];
// A perturbed copy sits beside the original so its relative imports resolve. screen-settings.js (for routerConf) imports the
// ORIGINAL routing.js, so a routing.js plant is read through R only — the status checks call R, never screen-settings.
const load = async name => {
  let file = path.join(ROOT, "js", name);
  if (PLANT && PLANTS[PLANT][0] === name) {
    const [, a, b] = PLANTS[PLANT];
    const s = fs.readFileSync(file, "utf8");
    if (!s.includes(a)) { console.log("ANCHOR MISSING: " + a); process.exit(1); }
    file = path.join(ROOT, "js", "__perturb_dialin_" + name);
    fs.writeFileSync(file, s.replace(a, b)); made.push(file);
  }
  return import(pathToFileURL(file).href);
};
let R, Store, C, SSM;
try {
  R = await load("routing.js");
  SSM = await load("screen-settings.js");
  ({ Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href));
  C = await load("crypto.js");
} finally { for (const f of made) fs.unlinkSync(f); }
// `profileText` is private to screen-settings.js: taken from the (maybe perturbed) source and run with what it uses.
let SSRC = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
if (PLANT === "--perturb-text") SSRC = SSRC.replace(PLANTS[PLANT][1], PLANTS[PLANT][2]);
const _pt = /\nfunction profileText\(ex\) \{[\s\S]*?\n\}\n/.exec(SSRC);
check("profileText is locatable (a miss here would pass everything)", !!_pt);
const SS = { profileText: new Function("awgConfLines", "Store", (_pt || [""])[0] + "\nreturn profileText;")(C.awgConfLines, Store) };
const routeFns = R;   // the status checks read the (maybe perturbed) routing.js directly

const K1 = "QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=", K2 = "ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc=";
const PSK = "b3B0aW9uYWwtcHNrLWZvci10aGUtZGlhbC1pbi1leGk=";
const DIN = { id: "aabbccdd", producer: "imported", provider: "profile", device: "wgx-aabbccdd", enabled: true,
  profile: { address: "10.254.0.0", mtu: 1420, listen_port: 51820, endpoint: "", peer_key: K2, psk: PSK, keepalive: 0,
             awg: { Jc: "4", S1: "76", H1: "1234567890" } } };
const OUT = { ...DIN, profile: { ...DIN.profile, listen_port: undefined, endpoint: "203.0.113.9:51820", keepalive: 25 } };

console.log("[1] the edit box: a dial-in profile as a server config, round-tripping through the real parser");
const txt = SS.profileText(DIN);
check("it has ListenPort", /\nListenPort = 51820\n/.test(txt), txt);
check("…no Endpoint and no keepalive", !/Endpoint/.test(txt) && !/PersistentKeepalive/.test(txt), txt);
const parse = t => JSON.parse(execFileSync("python3", ["-c", `
import importlib.machinery, importlib.util, json, sys
l = importlib.machinery.SourceFileLoader("p", sys.argv[1]); m = importlib.util.module_from_spec(importlib.util.spec_from_loader("p", l))
try: l.exec_module(m)
except SystemExit: pass
pr, e = m.parse_wg_profile(sys.stdin.read()); print(json.dumps({"p": pr, "e": e}))`, path.join(ROOT, "swg-panel-server")],
  { input: t.replace(Store.exitKeyKeep || "(unchanged)", K1).replace(Store.exitPskKeep || "(unchanged)", PSK) }).toString());
const back = parse(txt);
const same = (a, b) => JSON.stringify(Object.keys(a).sort().map(k => [k, a[k]])) === JSON.stringify(Object.keys(b).sort().map(k => [k, b[k]]));
check("…and parses back to the same profile", !back.e && back.p && same({ ...back.p, private_key: undefined },
      { ...DIN.profile, private_key: undefined }), back);
const tout = SS.profileText(OUT);
check("a dial-out box still has its Endpoint and keepalive, and no ListenPort",
      /\nEndpoint = 203\.0\.113\.9:51820\n/.test(tout) && /PersistentKeepalive = 25/.test(tout) && !/ListenPort/.test(tout), tout);

console.log("\n[2] the row's statuses");
const NODE = { id: "n1", name: "n1" };
Store.recon.nodeStatus = { n1: "live" };
const H = live => routeFns.exitHealth({ ...DIN, live: { device: "wgx-aabbccdd", up: true, listen_port: 51820, ...live } }, NODE);
const w = H({ handshake: 0 });
check("never a handshake → waiting for the router, naming the port", w.state === "waiting" && /router/.test(w.why) && /51820/.test(w.why), w);
const gone = H({ handshake: 900, no_traffic: { since: 1, why: "x" } });
check("a router that dialled once and went away (handshake 15 min old) → waiting, not 'check NAT'", gone.state === "waiting", gone);
const nt = H({ handshake: 40, no_traffic: { since: 1, why: "x" } });
check("a handshake and no traffic → check NAT on the router", nt.state === "stalled" && /NAT on the router/.test(nt.why), nt);
const back2 = H({ handshake: 40, no_traffic: { since: 1, why: "x" }, trace: { ip: "198.51.100.7" } });
check("a router that carries again while the judge waits out its hysteresis is not blamed for NAT", back2.state !== "stalled" || !/NAT/.test(back2.why), back2);
const unread = H({ handshake: null, no_traffic: { since: 1, why: "x" } });
check("a handshake the node could not read is not 'connected' (waiting)", unread.state === "waiting", unread);
const ks = routeFns.exitHealth({ ...DIN, killswitch: true, live: { device: "wgx-aabbccdd", up: true, listen_port: 51820, handshake: 0, no_traffic: { since: 1, why: "x" } } }, NODE);
check("…and once failed over it says what happened to the traffic, by the kill-switch",
      /kill-switch is holding/.test(ks.why) && /own IP/.test(gone.why), [ks.why, gone.why]);
const ok = H({ handshake: 40, trace: { ip: "198.51.100.7" }, endpoint: "198.51.100.7:40123" });
check("carrying → ok, with the router's address", ok.state === "ok" && /198\.51\.100\.7:40123/.test(ok.why), ok);
const stale = routeFns.exitHealth({ ...DIN, cfg_sig: "new", live: { device: "wgx-aabbccdd", up: false, cfg_sig: "old", error: "x" } }, { id: "n2" });
check("a report about the PREVIOUS config is not read as a node too old for dial-in", !/1\.8\.11 update/.test(stale.why), stale);
const old = routeFns.exitHealth({ ...DIN, live: { device: "wgx-aabbccdd", up: false, error: "the profile is missing its endpoint" } }, NODE);
check("an error and no listen_port → the node needs the update", /needs the 1\.8\.11 update/.test(old.why), old);
const err = H({ up: false, error: "wg-quick up failed" });
check("…but a 1.8.11 node's own error is shown as an error", err.state === "failed" && /wg-quick/.test(err.why), err);
const dout = routeFns.exitHealth({ ...OUT, live: { device: "wgx-aabbccdd", up: true, handshake: 0 } }, NODE);
check("a dial-out exit with no handshake keeps its own advice", dout.state === "nohandshake", dout);

console.log("\n[3] every exit kind by name");
const odd = { id: "11223344", producer: "imported", provider: "socks5", device: "wgx-11223344", enabled: true };
const groups = routeFns.exitOptionGroups({ exits: [odd, { ...DIN }] }, {});
const flat = groups.flatMap(g => (g.items || []).map(i => [g.group, String(i.label || "")]));
check("an unknown kind is in no WARP group", !flat.some(([g, l]) => /WARP/.test(g) && /11223344|socks5/.test(l)), flat);
check("…but in a group of its own, so a stored choice of it still shows", flat.some(([g, l]) => g === "Other exits" && /socks5/.test(l)), flat);
check("a dial-in exit is offered as a custom config", flat.some(([g]) => /custom config/.test(g)), flat);
check("…named a dial-in exit", routeFns.exitTypeLabel(DIN) === "Dial-in exit", routeFns.exitTypeLabel(DIN));
check("an unknown kind is labelled by its own name, never WARP", routeFns.exitTypeLabel(odd) === "socks5", routeFns.exitTypeLabel(odd));
const MD = await import(pathToFileURL(path.join(ROOT, "js", "model.js")).href);
Store.nodes = [{ id: "n9", name: "n9", exits: [DIN] }];
Store.stats = { ...(Store.stats || {}), n9: { interfaces: {} } };
check("the SPA's port check names a dial-in exit's port as taken, as the server does", /dial-in exit/.test(MD.portHolder("n9", 51820) || ""),
      MD.portHolder("n9", 51820));
check("an empty provider is still a WARP exit", routeFns.exitTypeLabel({ producer: "imported" }) === "WARP exit");

console.log("\n[4] the router's config dials the node");
const HPK = "c2l4dGVlbi1ieXRlcy1rZXktZm9yLWhwa3Rlc3QtMDA=";
const A31 = { Jc: "4", Jmin: "40", Jmax: "70", S1: "76", S2: "39", S3: "20", S4: "30", H1: "5-20", H2: "1000000000-1000000015",
              H3: "2000000000-2000000015", H4: "3000000000-3000000015", HeaderProtectionKey: HPK, RandomTrailers: "1" };
for (const [nm, awg] of [["WireGuard", {}], ["AmneziaWG 3.1", A31]]) {
  const prof = { ...DIN.profile, address: "10.254.0.6", listen_port: 51824, awg };
  const rc = SSM.routerConf("203.0.113.7", prof, K1, K2, PSK);
  const r = parse(rc);
  check(nm + ": it parses as a dial-out profile", !r.e && r.p && !r.p.listen_port, r);
  check(nm + ": its peer is the node, at the node's host and port", r.p && r.p.peer_key === K2 && r.p.endpoint === "203.0.113.7:51824", r.p);
  check(nm + ": the router's address is the other half of the pair, AllowedIPs the node's /32",
        r.p && r.p.address === "10.254.0.7" && /\nAllowedIPs = 10\.254\.0\.6\/32\n/.test(rc), rc);
  // against the stored dict itself, not against another rendering by the same awgConfLines (which would agree with itself)
  const want = Object.fromEntries(Object.entries(awg).sort());
  check(nm + ": the same AmneziaWG set as stored, keepalive on", r.p && JSON.stringify(Object.fromEntries(Object.entries(r.p.awg).sort())) === JSON.stringify(want)
        && r.p.keepalive === 25, [r.p && r.p.awg, want]);
}
check("a host already bracketed is not bracketed twice", /\nEndpoint = \[2001:db8::1\]:51824\n/.test(SSM.routerConf("[2001:db8::1]", { ...DIN.profile, listen_port: 51824 }, K1, K2, "")));
check("an IPv6 host is bracketed", /\nEndpoint = \[2001:db8::1\]:51824\n/.test(SSM.routerConf("2001:db8::1", { ...DIN.profile, listen_port: 51824 }, K1, K2, "")));

console.log("\n[5] the router's key in the config store");
const { api } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const ESC = {}, BLOBS = {}, SENT = [];
let GET = (n, e) => ({ ok: true, data: { sec: BLOBS[e] || "", user_id: C.exitBucket(n) } });
Object.assign(api, {
  subVault: async () => ({ ok: true, data: { exists: true } }),          // a vault from before sk_verify: any key opens it
  subUsers: async () => ({ ok: true, data: { users: Object.fromEntries(Object.entries(ESC).map(([u, w]) => [u, { unlock_by_sk: w }])) } }),
  subEscrow: async b => { if (!ESC[b.user_id]) ESC[b.user_id] = b.unlock_by_sk; return { ok: true, data: { unlock_by_sk: ESC[b.user_id] } }; },
  subExitBlob: async b => { SENT.push(b); BLOBS[b.exit] = b.sec; return { ok: true, data: { stored: true } }; },
  subExitBlobGet: async (n, e) => GET(n, e),
});
const rk = await C.genKeys(), nk = await C.genKeys();
Store.storeMode = "off";
check("the store off: nothing kept, nothing sent", await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub) === false && !SENT.length);
Store.storeMode = "encrypted";
const locked = await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub);
check("a locked vault: not kept, and says why", typeof locked === "string" && /locked/.test(locked) && !SENT.length, locked);
await C.subUnlockWithKey(Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString("base64"));
check("kept, with the vault open", await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub) === true, SENT);
check("…in the node's bucket, against the router's public key", !!ESC["_x_n1"] && SENT.length === 1 && SENT[0].node === "n1"
      && SENT[0].exit === "aabbccdd" && SENT[0].pub === rk.pub, SENT);
check("…as ciphertext: the private key is not in what was sent", SENT.length === 1 && !JSON.stringify(SENT[0]).includes(rk.priv), SENT);
const kb = await C.exitRouterKey("n1", "aabbccdd");
check("it reads back as the router's private key and the node's public key", kb && kb.k === rk.priv && kb.n === nk.pub, kb);
const wrap = ESC["_x_n1"];
ESC["_x_n1"] = ESC["_x_n1"].split("").reverse().join("");                // another bucket key: the wrap no longer opens
check("a blob under another bucket key reads sealed", await C.exitRouterKey("n1", "aabbccdd") === C.CONF_SEALED_OLD);
ESC["_x_n1"] = wrap;
GET = () => ({ ok: false, code: "not_found" });
check("an exit the panel no longer has reads none", await C.exitRouterKey("n1", "aabbccdd") === null);
GET = () => null;
check("a panel that does not answer reads unreachable", await C.exitRouterKey("n1", "aabbccdd") === C.CONF_UNREACHABLE);

done(!!PLANT, PLANT);
