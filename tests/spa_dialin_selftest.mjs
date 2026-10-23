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
 *  [5] (S9c) the router's key in the config store: nothing is kept with the store off, and a locked vault says so — and a
 *      later unlock in the same tab keeps it after all; kept, it goes to the node's bucket as ciphertext against the
 *      router's public key and the node key's digest, and reads back (in one request) as both keys the config needs; a
 *      locked vault reads "locked", a bucket key or a blob this vault cannot open reads "sealed", a refused mint is not
 *      blamed on an old key, an exit the panel no longer has reads "none", a dead panel reads "unreachable"
 *
 * Run: node tests/spa_dialin_selftest.mjs
 *      --perturb-text    the box prints `Endpoint = ` for a dial-in profile again        → RED [1]
 *      --perturb-status  the row has no dial-in arm (the dial-out sentences)              → RED [2]
 *      --perturb-old     the old-node read removed                                        → RED [2]
 *      --perturb-warp    the WARP group is "not profile" again                            → RED [3]
 *      --perturb-rconf   the router's address is the node's own (no +1)                  → RED [4]
 *      --perturb-r31     the router's address is a /32 again (Keenetic forwards nothing)  → RED [4]
 *      --perturb-rawg    the steps tell AmneziaWG by a `Jc =` line (a template may omit it) → RED [4]
 *      --perturb-keepn   the node's public key is left out of the kept blob                → RED [5]
 *      --perturb-pending a keep skipped at a locked vault is forgotten                    → RED [5]
 *      --perturb-pendfail a queued keep is dropped before it is tried (a failed flush loses it) → RED [5]
 *      --perturb-blobgcm  a peer's blob GCM refuses reads "no stored config" again (s9c F25/F45) → RED [5]
 *      --perturb-s4twin   the browser's wire overhead differs from the panel's (review F6)   → RED [5b]
 *      --perturb-rewrap   the pre-flight promises a re-wrap again (NODE-TRANSFER I.18)         → RED [6]
 *      --perturb-keepseal a queued keep whose bucket is sealed reads "queued" for ever (review F1) → RED [5]
 *      --perturb-sealplain a sealed blob hides the plaintext copy a migrating panel still has (F2) → RED [5]
 *      --perturb-keepdrop a keep the panel refused for good is re-posted on every unlock (s9c F57) → RED [5]
 *      --perturb-keepwhy  a failed flush is silent — the open sheet cannot say why (s9c F60)   → RED [5]
 *      --perturb-stalenat a stale node's recovering dial-in exit blames NAT on the router (s9d F9) → RED [2]
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
  "--perturb-rconf": ["screen-settings.js", 'Number(o[3]) ^ 1].join(".") + "/31"', 'Number(o[3])].join(".") + "/31"'],
  "--perturb-r31": ["screen-settings.js", 'Number(o[3]) ^ 1].join(".") + "/31"', 'Number(o[3]) + 1].join(".") + "/32"'],
  "--perturb-rawg": ["screen-settings.js", 'awg = Object.keys((ex.profile || {}).awg || {}).length > 0;', 'awg = /^\\s*Jc\\s*=/m.test(conf);'],
  "--perturb-warp": ["routing.js", 'imp.filter(x => exitProv(x) === "warp")', 'imp.filter(x => x.provider !== "profile")'],
  "--perturb-keepn": ["crypto.js", "JSON.stringify({ k: routerPriv, n: nodePub })", "JSON.stringify({ k: routerPriv })"],
  "--perturb-pending": ["crypto.js", "_pendingKeep.set(pk, [nid, exitId, routerPub, routerPriv, nodePub, nodePriv]); _keepFail.delete(pk); return", "return"],
  "--perturb-pendfail": ["crypto.js", "if (r && r.ok !== false) { _pendingKeep.delete(pk); _keepFail.delete(pk); return true; }", "_pendingKeep.delete(pk); if (r && r.ok !== false) return true;"],
  "--perturb-blobgcm": ["crypto.js", "try { secret = JSON.parse(new TextDecoder().decode(await subDec(unlockKey, sec))); } catch (_) { return CONF_SEALED_OLD; }",
                        "secret = JSON.parse(new TextDecoder().decode(await subDec(unlockKey, sec)));"],
  "--perturb-keepseal": ["crypto.js", "if (_pendingKeep.has(pk)) { _keepFail.set(pk, why); if (sealed) _pendingKeep.delete(pk); }", "0;"],
  "--perturb-sealplain": ["crypto.js", "if (!(Store.configsPlaintext > 0)) return null;\n      return api.config(", "return null;\n      return api.config("],
  "--perturb-keepdrop": ["crypto.js", 'if (r && ["stale", "not_found", "bad_request"].includes(r.code)) _pendingKeep.delete(pk);', "0;"],
  "--perturb-keepwhy": ["crypto.js", "if (_pendingKeep.has(pk)) _keepFail.set(pk, why);\n", "\n"],
  "--perturb-stalenat": ["routing.js", "if (exitIsDialin(ex) && l.no_traffic && !Number.isFinite(l.no_traffic.back_in) && !(l.trace || {}).ip) return", "if (exitIsDialin(ex) && l.no_traffic && !(l.trace || {}).ip) return"],
};
PLANTS["--perturb-rewrap"] = ["sheets-crud.js", "", ""];
PLANTS["--perturb-s4twin"] = ["screen-settings-text", "", ""];   // read by [5b] itself, as text   // read by [6] itself: no module to load perturbed
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
Store.recon.nodeStatus = { n1: "stale" };
const sback = H({ handshake: 40, no_traffic: { since: 1, why: "x", back_in: 30 } });
Store.recon.nodeStatus = { n1: "live" };
check("a node that stopped reporting while its dial-in exit recovered: the plain stalled reading, not blamed on NAT (s9d F9)",
      !/NAT/.test(sback.why) && sback.state === "stalled", sback);
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
  // (S9d) as a /31, so the node's address is on the router's own link — as a /32 a Keenetic forwarded nothing (live)
  check(nm + ": …as a /31 — the node's address on the router's own link", /\nAddress = 10\.254\.0\.7\/31\n/.test(rc), rc);
  // against the stored dict itself, not against another rendering by the same awgConfLines (which would agree with itself)
  const want = Object.fromEntries(Object.entries(awg).sort());
  check(nm + ": the same AmneziaWG set as stored, keepalive on", r.p && JSON.stringify(Object.fromEntries(Object.entries(r.p.awg).sort())) === JSON.stringify(want)
        && r.p.keepalive === 25, [r.p && r.p.awg, want]);
}
check("a re-pasted odd node address pairs downwards — the router still the other half of its /31",
      /\nAddress = 10\.254\.0\.6\/31\n/.test(SSM.routerConf("203.0.113.7", { ...DIN.profile, address: "10.254.0.7", listen_port: 51824 }, K1, K2, "")));
// the steps name the AmneziaWG tools by the stored set — a generated AWG config may carry no Jc line (the template's "-")
const vtext = v => v == null || v === false ? "" : Array.isArray(v) ? v.map(vtext).join("") : typeof v === "object" ? vtext((v.props || {}).children) : String(v);
const awgNoJc = { id: "aabbccdd", profile: { address: "10.254.0.0", listen_port: 51824, awg: { S1: "36", H1: "5-20" } } };
const awgConf = SSM.routerConf("203.0.113.7", awgNoJc.profile, K1, K2, "");
const oth = vtext(SSM.routerSteps("other", awgNoJc, awgConf)), owrt = vtext(SSM.routerSteps("openwrt", awgNoJc, awgConf));
check("an AmneziaWG config with no Jc line still gets the AmneziaWG steps (awg-quick, protocol AmneziaWG)",
      !/^\s*Jc\s*=/m.test(awgConf) && /awg-quick up/.test(oth) && /amnezia\/amneziawg/.test(oth) && /protocol AmneziaWG/.test(owrt), [oth, owrt]);
const wgEx = { id: "aabbccdd", profile: { address: "10.254.0.0", listen_port: 51824, awg: {} } };
check("…and a WireGuard one the WireGuard steps", /wg-quick up/.test(vtext(SSM.routerSteps("other", wgEx, ""))) && !/awg-quick/.test(vtext(SSM.routerSteps("other", wgEx, ""))));
check("a host already bracketed is not bracketed twice", /\nEndpoint = \[2001:db8::1\]:51824\n/.test(SSM.routerConf("[2001:db8::1]", { ...DIN.profile, listen_port: 51824 }, K1, K2, "")));
check("an IPv6 host is bracketed", /\nEndpoint = \[2001:db8::1\]:51824\n/.test(SSM.routerConf("2001:db8::1", { ...DIN.profile, listen_port: 51824 }, K1, K2, "")));

console.log("\n[5] the router's key in the config store");
const { api } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const ESC = {}, BLOBS = {}, SENT = [];
let GET = (n, e) => ({ ok: true, data: { sec: (BLOBS[e] || {}).sec || "", pub: (BLOBS[e] || {}).pub || "", user_id: C.exitBucket(n),
                                         unlock_by_sk: ESC[C.exitBucket(n)] || "" } });
let USERS = () => ({ ok: true, data: { users: Object.fromEntries(Object.entries(ESC).map(([u, w]) => [u, { unlock_by_sk: w }])) } });
Object.assign(api, {
  subVault: async () => ({ ok: true, data: { exists: true } }),          // a vault from before sk_verify: any key opens it
  subUsers: async () => USERS(),
  subEscrow: async b => { if (b.user_id === "_x_n2") return { ok: false, error: "escrow.json is not writable" };
                          if (!ESC[b.user_id]) ESC[b.user_id] = b.unlock_by_sk; return { ok: true, data: { unlock_by_sk: ESC[b.user_id] } }; },
  subExitBlob: async b => { SENT.push(b); BLOBS[b.exit] = { sec: b.sec, pub: b.pub }; return { ok: true, data: { stored: true } }; },
  subExitBlobGet: async (n, e) => GET(n, e),
});
const rk = await C.genKeys(), nk = await C.genKeys();
const SK = Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString("base64");
const tick = () => new Promise(ok => setTimeout(ok, 50));
Store.storeMode = "off";
check("the store off: nothing kept, nothing sent", await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub, nk.priv) === false && !SENT.length);
Store.storeMode = "encrypted";
const locked = await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub, nk.priv);
check("a locked vault: not kept, and says so by a sentinel a language switch cannot break (s9d F10)",
      locked === C.EXIT_KEEP_LOCKED && !SENT.length && C.exitKeepState("n1", "aabbccdd") === "queued", String(locked));
await C.subUnlockWithKey(SK); await tick();
check("…and unlocking later in the same tab keeps it after all, as a skipped peer's config", SENT.length === 1, SENT);
check("…and the open sheet can read that it is kept now (s9d F11)", C.exitKeepState("n1", "aabbccdd") === null);
check("…in the node's bucket, against the router's public key and the node key's digest", !!ESC["_x_n1"] && SENT.length === 1
      && SENT[0].node === "n1" && SENT[0].exit === "aabbccdd" && SENT[0].pub === rk.pub
      && SENT[0].nkh === (await C.sha256hex(nk.priv)).slice(0, 16), SENT);
check("…as ciphertext: neither private key is in what was sent", SENT.length === 1 && !JSON.stringify(SENT[0]).includes(rk.priv)
      && !JSON.stringify(SENT[0]).includes(nk.priv), SENT);
check("kept, with the vault open", await C.exitKeepRouter("n1", "aabbccdd", rk.pub, rk.priv, nk.pub, nk.priv) === true, SENT);
USERS = () => { throw new Error("a blip"); };                           // the read is ONE request: a second one failing is no "none"
const kb = await C.exitRouterKey("n1", "aabbccdd");
check("it reads back as the router's private key, the node's public key and the router key it was kept against",
      kb && kb.k === rk.priv && kb.n === nk.pub && kb.pub === rk.pub, kb);
C.subForget();
check("kept, with the vault locked: says locked (the caller asks), never 'none kept'", await C.exitRouterKey("n1", "aabbccdd") === C.EXIT_LOCKED);
await C.subUnlockWithKey(SK); await tick();
const wrap = ESC["_x_n1"];
ESC["_x_n1"] = ESC["_x_n1"].split("").reverse().join("");                // another bucket key: the wrap no longer opens
check("a bucket key this vault cannot open reads sealed", await C.exitRouterKey("n1", "aabbccdd") === C.CONF_SEALED_OLD);
ESC["_x_n1"] = wrap;
const sec0 = BLOBS.aabbccdd.sec;
BLOBS.aabbccdd.sec = sec0.slice(0, 30) + (sec0[30] === "A" ? "B" : "A") + sec0.slice(31);   // one ciphertext byte off
check("a blob the bucket key does not open (GCM refuses it) reads sealed", await C.exitRouterKey("n1", "aabbccdd") === C.CONF_SEALED_OLD);
// …and a PEER's stored config the same way: sealed, not "No stored config — re-issue", the one advice that destroys it (s9c F25)
Store.describe = { ...(Store.describe || {}), n1: { wg0: { public_key: K2, endpoint: "203.0.113.7:51820", awg_params: {} } } };
const bpeer = { id: "p1", user_id: C.exitBucket("n1"), targets: [{ node: "n1", iface: "wg0", ip: "10.9.0.2/32" }] };
api.subBlobGet = async () => ({ ok: true, data: { sec: BLOBS.aabbccdd.sec, user_id: C.exitBucket("n1") } });
const bsealed = await C.blobConfig(bpeer, "n1", "wg0");
api.subBlobGet = async () => ({ ok: true, data: { sec: sec0, user_id: C.exitBucket("n1") } });
const bopen = await C.blobConfig(bpeer, "n1", "wg0");
check("a peer's stored config the bucket key does not open reads sealed; one it opens is built", bsealed === C.CONF_SEALED_OLD
      && typeof bopen === "string" && bopen.includes("PrivateKey = " + rk.priv), [String(bsealed), typeof bopen]);
// …and on a panel still migrating, the plaintext copy of a sealed one is still read (backlog C review F2)
api.subBlobGet = async () => ({ ok: true, data: { sec: BLOBS.aabbccdd.sec.slice(0, 30) + (BLOBS.aabbccdd.sec[30] === "A" ? "B" : "A") + BLOBS.aabbccdd.sec.slice(31), user_id: C.exitBucket("n1") } });
Store.recon.peers = [{ ...bpeer, pubkey: "PKSEALED" }];
Store.configsPlaintext = 1;
const PLAIN = "[Interface]\nPrivateKey = " + rk.priv + "\nAddress = 10.9.0.2/32\n\n[Peer]\nPublicKey = " + K2 + "\nEndpoint = 203.0.113.7:51820\nAllowedIPs = 0.0.0.0/0\n";
api.config = async () => ({ ok: true, data: { config: PLAIN } });
const gplain = await C.getConfig("PKSEALED", "n1", "wg0");
Store.configsPlaintext = 0;
check("…a sealed blob with a plaintext copy still on the panel shows that copy, not 're-issue'",
      typeof gplain === "string" && gplain.includes("PrivateKey = " + rk.priv) && !C.confWasSealedOld("PKSEALED", "n1", "wg0"), [typeof gplain, String(gplain).slice(0, 60)]);
BLOBS.aabbccdd.sec = sec0;
USERS = () => ({ ok: true, data: { users: {} } });
const refused = await C.exitKeepRouter("n2", "aabbccdd", rk.pub, rk.priv, nk.pub, nk.priv);
check("a bucket key the panel refused to mint is not blamed on a previous encryption key", typeof refused === "string"
      && !/previous/.test(refused) && /couldn't store/.test(refused), refused);
GET = () => ({ ok: false, code: "not_found" });
check("an exit the panel no longer has reads none", await C.exitRouterKey("n1", "aabbccdd") === null);
GET = () => null;
check("a panel that does not answer reads unreachable", await C.exitRouterKey("n1", "aabbccdd") === C.CONF_UNREACHABLE);
// a queued keep whose flush fails stays queued — the router's key lives only in this tab — and a later unlock keeps it
C.subForget();
const rk2 = await C.genKeys(), okPost = api.subExitBlob;
await C.exitKeepRouter("n1", "eeff0011", rk2.pub, rk2.priv, nk.pub, nk.priv);
let fails = 0;
api.subExitBlob = async () => { fails++; return { ok: false, error: "panel busy" }; };
await C.subUnlockWithKey(SK); await tick();
api.subExitBlob = okPost;
const sent0 = SENT.length;
C.subForget(); await C.subUnlockWithKey(SK); await tick();
check("a queued keep whose flush failed is kept on the next unlock, not lost", fails === 1 && SENT.length === sent0 + 1
      && SENT[SENT.length - 1].exit === "eeff0011" && SENT[SENT.length - 1].pub === rk2.pub, { fails, sent: SENT.length - sent0 });
// …its failure is said while it waits (s9c F60), and a refusal for good is not re-posted on every unlock (s9c F57)
C.subForget();
const rk3 = await C.genKeys();
await C.exitKeepRouter("n1", "22334455", rk3.pub, rk3.priv, nk.pub, nk.priv);
api.subExitBlob = async () => ({ ok: false, error: "panel busy" });
await C.subUnlockWithKey(SK); await tick();
check("…a failed flush leaves its reason for the open sheet", C.exitKeepState("n1", "22334455") === "panel busy", C.exitKeepState("n1", "22334455"));
let posts = 0;
api.subExitBlob = async () => { posts++; return { ok: false, code: "stale", error: "the exit's router key has changed since this config was made" }; };
C.subForget(); await C.subUnlockWithKey(SK); await tick();
C.subForget(); await C.subUnlockWithKey(SK); await tick();
api.subExitBlob = okPost;
check("a keep the panel refuses for good (stale) is dropped, not re-posted on every unlock, and still says why",
      posts === 1 && /changed since/.test(String(C.exitKeepState("n1", "22334455"))), { posts, st: C.exitKeepState("n1", "22334455") });
// a queued keep whose bucket is sealed under a previous key: said, and not re-tried on every unlock (backlog C review F1)
C.subForget();
ESC["_x_n7"] = "c2VhbGVkLXVuZGVyLWFub3RoZXIta2V5LXh4eHh4eHh4eHh4eHh4eA==";
USERS = () => ({ ok: true, data: { users: Object.fromEntries(Object.entries(ESC).map(([u, w]) => [u, { unlock_by_sk: w }])) } });
C.subUsersForget();                                                     // the users map is cached 4 s; a fresh read sees the bucket
let p7 = 0;
api.subExitBlob = async b => { p7++; return okPost(b); };
await C.exitKeepRouter("n7", "77777777", rk3.pub, rk3.priv, nk.pub, nk.priv);
await C.subUnlockWithKey(SK); await tick();
C.subForget(); await C.subUnlockWithKey(SK); await tick();
api.subExitBlob = okPost;
check("…a queued keep whose bucket is sealed: the sheet reads why, never \"queued\", and nothing is posted",
      /previous encryption key/.test(String(C.exitKeepState("n7", "77777777"))) && p7 === 0, { st: C.exitKeepState("n7", "77777777"), p7 });

console.log("\n[5b] the browser fits a drawn S4 by the panel's own numbers (backlog B review F6)");
const _ss = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8").replace(PLANT === "--perturb-s4twin" ? "const DIN_WIRE = 60;" : "\0", "const DIN_WIRE = 61;");
const _jw = (_ss.match(/^const DIN_WIRE = (\d+);/m) || [])[1], _pw = (fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8").match(/^MESH_WIRE_OVERHEAD = (\d+)/m) || [])[1];
check("the browser's wire overhead is the panel's MESH_WIRE_OVERHEAD", !!_jw && _jw === _pw, { browser: _jw, panel: _pw });
check("…and it reads the MTU as the panel does: digits only", /\/\^\[0-9\]\+\$\/\.test\(String\(mtu \?\? ""\)\.trim\(\)\)/.test(_ss));

console.log("\n[6] a node transfer's pre-flight says what becomes of users' encryption keys (NODE-TRANSFER I.18)");
const SC = PLANT === "--perturb-rewrap" ? fs.readFileSync(path.join(ROOT, "js", "sheets-crud.js"), "utf8")
    .replace("esc.length ? [T(\"These users' encryption keys stay sealed", "esc.length ? [T(\"Users' encryption keys — re-wrapped there the next time you unlock the vault\"), plural(esc.length, \"user\")] : null,\n    false ? [T(\"These users' encryption keys stay sealed")
  : fs.readFileSync(path.join(ROOT, "js", "sheets-crud.js"), "utf8");
const _l0 = SC.indexOf("const lost = ["), _lost = SC.slice(_l0, SC.indexOf("const kept = [", _l0));   // TransferOutcome's two lists
check("…among \"Worth knowing before you do this\": they stay sealed to this panel — nothing re-wraps them there",
      /esc\.length \? \[T\("These users' encryption keys stay sealed to this panel's vault/.test(_lost) && !/T\("[^"]*re-wrapped there the next time/.test(SC), _lost.slice(0, 200));

done(!!PLANT, PLANT);
