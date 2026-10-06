/* Self-test: a turn link names the host the operator entered; a wildcard falls back to the interface's Endpoint.
 *
 * A turn server's "Endpoint host / IP" is what clients DIAL — any of the node's names, any host. The node binds it when it
 * lands on the box and otherwise listens on every address (swg-noded turn_bind, tests/turn_bind_selftest.py), so the link
 * carries exactly what was entered, a home box's DDNS name included. Two things are left for the panel:
 *
 *   [1] a vk-turn-proxy set up on the wildcard (0.0.0.0) names no host at all — its link used to say `0.0.0.0:port`. It
 *       now takes the host of the interface's own Endpoint (turn-artifacts.js dialListen), with the proxy's port
 *   [2] CONTROL: anything else is carried as entered — a public IP, a hostname, a DDNS name, even a private address
 *   [3] a new listener on a box behind NAT (no public IPv4 of its own) defaults to the node's ingress host, not to a
 *       private address of the box that nobody outside can dial (listenHostInit)
 *
 * Run: node tests/turn_dial_host_selftest.mjs
 *      --perturb   lets a wildcard bind straight into vk-turn-proxy links again — expects RED in [1].
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");

let src = readFileSync(path.join(ROOT, "turn-artifacts.js"), "utf8");
const ANCHOR = "    tp = dialListen(tp, baseConf);\n";
// ⚠️ A perturbation whose anchor has drifted proves nothing and reports green.
if (src.split(ANCHOR).length - 1 !== 1) {
  console.log("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS");
  process.exit(1);
}
if (PERTURB) src = src.replace(ANCHOR, "");
vm.runInThisContext(src, { filename: "turn-artifacts.js" });
const SWGTurn = globalThis.SWGTurn;

const DDNS = "abcd1234.sn.mynetname.net";
const conf = ep => "[Interface]\nPrivateKey = cHJpdmtleXByaXZrZXlwcml2a2V5cHJpdmtleXByaXY=\nAddress = 10.8.0.5/32\nDNS = 1.1.1.1\n\n" +
  "[Peer]\nPublicKey = cHVia2V5cHVia2V5cHVia2V5cHVia2V5cHVia2V5cHU=\nAllowedIPs = 0.0.0.0/0\n" + (ep ? "Endpoint = " + ep + "\n" : "");
const KEY = "ab".repeat(32);
const tp = listen => ({ service: "vk-turn-proxy-samosvalishe-56000", listen, wrap_key: KEY,
  params: "-obf-profile rtpopus -obf-key " + KEY });
const LINK = "https://vk.ru/call/join/AAAAAAAAAAAAAAAAAAAA";
// freeturn:// carries the dialled address as `peer`; the CLI command carries it after -peer.
const peerOf = (listen, ep) => {
  const a = SWGTurn.artifact(conf(ep), tp(listen), LINK, {}, [LINK], "freeturn");
  return JSON.parse(Buffer.from(a.text.replace("freeturn://", ""), "base64url").toString("utf8")).peer;
};
const cliPeer = (listen, ep) => {
  const a = SWGTurn.artifact(conf(ep), tp(listen), LINK, {}, [LINK], "cli");
  return ((a.cmd || a.text || "").match(/-peer\s+(\S+)/) || [])[1] || "";
};
const is = (name, got, want) => check(name, got === want, got);

console.log("[1] vk-turn-proxy on the wildcard: the interface's Endpoint host, with the proxy's port");
is("0.0.0.0 → the DDNS name the WireGuard config carries", peerOf("0.0.0.0:56000", DDNS + ":51820"), DDNS + ":56000");
is("…in the CLI command too", cliPeer("0.0.0.0:56000", DDNS + ":51820"), DDNS + ":56000");
is("an IPv6 wildcard the same", peerOf("[::]:56000", "203.0.113.7:51820"), "203.0.113.7:56000");
is("no Endpoint in the config → left as it was", peerOf("0.0.0.0:56000", ""), "0.0.0.0:56000");
check("the caller's proxy record is not mutated", (() => { const t = tp("0.0.0.0:56000"); SWGTurn.artifact(conf(DDNS + ":51820"), t, LINK, {}, [LINK], "freeturn"); return t.listen === "0.0.0.0:56000"; })());

console.log("\n[2] CONTROL: everything else is carried as entered");
is("a public IP", peerOf("1.2.3.4:56000", DDNS + ":51820"), "1.2.3.4:56000");
is("a hostname", peerOf("vpn.example.com:56000", "1.2.3.4:51820"), "vpn.example.com:56000");
is("the DDNS name itself", peerOf(DDNS + ":56000", "1.2.3.4:51820"), DDNS + ":56000");
is("a private address (the operator's word)", peerOf("192.168.88.10:56000", DDNS + ":51820"), "192.168.88.10:56000");

console.log("\n[3] a new listener's default");
const { listenHostInit } = await spa("turn.js");
const choices = (ep, ips) => [...new Set([ep, ...ips].filter(Boolean))];
is("behind NAT (only a private IPv4) → the ingress host", listenHostInit("", choices("", [DDNS, "192.168.88.10"]), ["192.168.88.10"]), DDNS);
is("…a global IPv6 beside it changes nothing (the VK relay dials IPv4)",
   listenHostInit("", choices("", [DDNS, "192.168.88.10", "2a02:6b8::10"]), ["192.168.88.10", "2a02:6b8::10"]), DDNS);
is("CONTROL: a box with a public IPv4 keeps its own address", listenHostInit("", choices("", ["82.24.110.35"]), ["10.0.0.2", "82.24.110.35"]), "82.24.110.35");
// (its container address is filtered out of the picker, as tests/spa_turnlisten_selftest.mjs [3] models it)
is("CONTROL: a bridge node is not read as NAT", listenHostInit("82.24.110.35", choices("82.24.110.35", []), ["172.17.0.2"], true), "82.24.110.35");
is("CONTROL: a node that reported nothing changes nothing", listenHostInit(DDNS, choices(DDNS, []), []), DDNS);

done(PERTURB, "a wildcard bind goes straight into vk-turn-proxy links");
