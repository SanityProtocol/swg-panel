/* Self-test: a turn-family link names a host a client can reach, even when the server cannot bind that host.
 *
 * A home box behind a MikroTik (client report, 2026-10-06): its public name is the router's DDNS host, which resolves
 * to the router's WAN address. Plain WireGuard worked with that name as Endpoint, because an Endpoint is only text in
 * the client config. A turn server could not be brought up at all: its one `listen` field was both the address the
 * node BINDS and the host written into every client link, so the DDNS name failed to bind
 * (`bind: cannot assign requested address`). The wildcard bound fine, but a vk-turn-proxy link then said
 * `0.0.0.0:port`, and a LAN address put `192.168.x.x` in the link — neither reachable from the VK relay.
 *
 * The rule now (js/util.js turnDialHost, and its twins): a specific public bind is what clients dial; a wildcard or
 * a private bind hands over to the node's endpoint host — for a vk-turn-proxy, the Endpoint of the interface it
 * forwards to, which is where the working DDNS name already sits.
 *
 * What this drives, through the REAL code:
 *   [1] vk-turn-proxy links (turn-artifacts.js): a wildcard or private bind takes the interface Endpoint's host
 *   [2] CONTROL: a public IP or a hostname bind stays in the link exactly as before; no usable Endpoint leaves it
 *   [3] turnDialHost (js/util.js) — the WDTT/csqtt rule, including both last resorts
 *   [4] the Python twins (swg-sub _turn_dial_host, swg-panel-server _fp_dial_host) answer the same table
 *   [5] a box behind NAT starts a new listener on All addresses (listenHostInit)
 *
 * Run: node tests/turn_dial_host_selftest.mjs
 *      --perturb   lets a wildcard bind straight into vk-turn-proxy links again — expects RED in [1].
 */
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
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

console.log("[1] vk-turn-proxy: a bind no client can reach takes the interface's Endpoint host");
check("wildcard bind → the DDNS name, with the proxy's port", peerOf("0.0.0.0:56000", DDNS + ":51820") === DDNS + ":56000", peerOf("0.0.0.0:56000", DDNS + ":51820"));
check("…in the CLI command too", cliPeer("0.0.0.0:56000", DDNS + ":51820") === DDNS + ":56000", cliPeer("0.0.0.0:56000", DDNS + ":51820"));
check("a LAN bind (box behind NAT) → the DDNS name", peerOf("192.168.88.10:56000", DDNS + ":51820") === DDNS + ":56000", peerOf("192.168.88.10:56000", DDNS + ":51820"));
check("a CGNAT bind → the Endpoint host", peerOf("100.72.1.9:56000", "203.0.113.7:51820") === "203.0.113.7:56000", peerOf("100.72.1.9:56000", "203.0.113.7:51820"));
check("a hostname that starts like a private address stays", peerOf("10.0.0.5.nip.io:56000", DDNS + ":51820") === "10.0.0.5.nip.io:56000", peerOf("10.0.0.5.nip.io:56000", DDNS + ":51820"));
check("an IPv6 wildcard → the Endpoint host", peerOf("[::]:56000", DDNS + ":51820") === DDNS + ":56000", peerOf("[::]:56000", DDNS + ":51820"));

console.log("\n[2] CONTROL: what already worked is byte-identical");
check("a public IP bind stays, whatever the Endpoint says", peerOf("1.2.3.4:56000", DDNS + ":51820") === "1.2.3.4:56000", peerOf("1.2.3.4:56000", DDNS + ":51820"));
check("a hostname bind stays", peerOf("vpn.example.com:56000", "1.2.3.4:51820") === "vpn.example.com:56000", peerOf("vpn.example.com:56000", "1.2.3.4:51820"));
check("no Endpoint in the config → the bind is left as it was", peerOf("0.0.0.0:56000", "") === "0.0.0.0:56000", peerOf("0.0.0.0:56000", ""));
check("the caller's proxy record is not mutated", (() => { const t = tp("0.0.0.0:56000"); SWGTurn.artifact(conf(DDNS + ":51820"), t, LINK, {}, [LINK], "freeturn"); return t.listen === "0.0.0.0:56000"; })());

console.log("\n[3] turnDialHost — the WDTT / csqtt rule");
const { turnDialHost } = await spa("util.js");
const TABLE = [
  ["1.2.3.4", DDNS, "1.2.3.4"],              // a specific public bind wins
  ["vpn.example.com", DDNS, "vpn.example.com"],
  ["0.0.0.0", DDNS, DDNS],                   // wildcard → the node's endpoint host
  ["", DDNS, DDNS],
  ["::", DDNS, DDNS],
  ["192.168.88.10", DDNS, DDNS],             // private → behind NAT → the node's endpoint host
  ["10.0.0.5", "", "10.0.0.5"],              // …unless there is nothing better: the link it had
  ["0.0.0.0", "", ""],                       // a wildcard is never a link host
  ["10.0.0.5.nip.io", DDNS, "10.0.0.5.nip.io"], // a NAME that starts like a private address is still a name
];
for (const [bind, fb, want] of TABLE) {
  const got = turnDialHost(bind, fb);
  check(`turnDialHost(${JSON.stringify(bind)}, ${JSON.stringify(fb)}) = ${JSON.stringify(want)}`, got === want, got);
}

console.log("\n[4] the Python twins answer the same table");
const PY = `
import importlib.machinery, importlib.util, json, sys
def load(name, path):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    m.__dict__["__file__"] = path
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m
S = load("swgsub_dial", sys.argv[1] + "/swg-sub")
P = load("swgpanel_dial", sys.argv[1] + "/swg-panel-server")
out = []
for bind, fb, _w in json.loads(sys.argv[2]):
    listen = (("[%s]" % bind) if ":" in bind else bind) + ":56000"
    out.append([S._turn_dial_host(listen, fb, None), P._fp_dial_host(listen, fb, None)])
print(json.dumps(out))
`;
const py = JSON.parse(execFileSync("python3", ["-c", PY, ROOT, JSON.stringify(TABLE)], { encoding: "utf8", env: { ...process.env, SWG_NO_REEXEC: "1" } }).trim().split("\n").pop());
TABLE.forEach(([bind, fb, want], i) => {
  check(`swg-sub _turn_dial_host on ${JSON.stringify(bind)} = ${JSON.stringify(want)}`, py[i][0] === want, py[i][0]);
  check(`swg-panel-server _fp_dial_host on ${JSON.stringify(bind)} = ${JSON.stringify(want)}`, py[i][1] === want, py[i][1]);
});

console.log("\n[5] a new listener on a box behind NAT starts on All addresses");
const { listenHostInit } = await spa("turn.js");
const choices = (ep, ips) => [...new Set([ep, ...ips].filter(Boolean))];
check("only private IPv4 reported → 0.0.0.0", listenHostInit(DDNS, choices(DDNS, ["192.168.88.10"]), ["192.168.88.10"]) === "0.0.0.0",
      listenHostInit(DDNS, choices(DDNS, ["192.168.88.10"]), ["192.168.88.10"]));
check("a global IPv6 beside a private IPv4 is still NAT for the VK relay → 0.0.0.0",
      listenHostInit("", choices("", ["192.168.88.10", "2a02:6b8::1"]), ["192.168.88.10", "2a02:6b8::1"]) === "0.0.0.0",
      listenHostInit("", choices("", ["192.168.88.10", "2a02:6b8::1"]), ["192.168.88.10", "2a02:6b8::1"]));
check("CONTROL: a box with a public IPv4 keeps its address", listenHostInit("", choices("", ["10.0.0.2", "82.24.110.35"]), ["10.0.0.2", "82.24.110.35"]) !== "0.0.0.0",
      listenHostInit("", choices("", ["10.0.0.2", "82.24.110.35"]), ["10.0.0.2", "82.24.110.35"]));
check("CONTROL: a bridge node is not read as NAT", listenHostInit("82.24.110.35", choices("82.24.110.35", ["172.17.0.2"]), ["172.17.0.2"], true) !== "0.0.0.0",
      listenHostInit("82.24.110.35", choices("82.24.110.35", ["172.17.0.2"]), ["172.17.0.2"], true));
check("CONTROL: a node that reported nothing changes nothing", listenHostInit(DDNS, choices(DDNS, []), []) === DDNS, listenHostInit(DDNS, choices(DDNS, []), []));

done(PERTURB, "a wildcard bind goes straight into vk-turn-proxy links");
