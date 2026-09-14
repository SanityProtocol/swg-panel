#!/usr/bin/env python3
"""Self-test for NETWORKS P2 — the node's own LAN: the disclosure's facts and the opt-out behind them
(docs/NETWORKS-PLAN.md D10, §4.7, §8 P2).

Measured before anything was built: a client already reaches the private network its node sits on. So the panel
discloses it and offers to close it, and the node enforces the close with one nft table. What this holds:

  [1] the panel and the node agree on what a PRIVATE network is — the panel must disclose exactly what the node
      would close, and a public subnet beside a VPS is the internet, not a LAN.
  [2] `node_lans` reads the disclosure from what every node already reports — no tunnels, no mesh links.
  [3] the ruleset: a deterministic priority below the other forward hooks (§4.7), the client tunnels, clients of
      OTHER nodes arriving by mesh, and a device name that could break out of its quotes never reaching nft.
  [4] ⚠️ D1 and the restart. While sharing, the table is asked about ONCE per process and never again — and that
      one question is not optional: a node re-opened while its daemon was down would otherwise keep a drop nobody
      wants, because nothing but the kernel remembers that it exists.
  [5] blocking: installed once, re-read each pass, rebuilt only when missing or its inputs moved.
  [6] failure never opens it: an unreadable address list leaves the table as it is, a failed load says so.
  [7] `lan_share` is stored only as a departure from the default, and cleared rather than written `true`.

Hermetic. Run: python3 tests/lan_block_selftest.py            (0 = pass)
     --perturb         skips the once-per-process probe and expects RED on [4]'s restart case.
     --perturb-owned   the node forgets which devices are its own tunnels → RED on [8].

  [8] ⚠️ the node judges a device by what it RUNS, not by its name: its client interfaces, WDTT instances and their RAW
      TUN, csqtt instances and exit devices are never "the private network it sits on" — neither in the snapshot's
      `lans` nor in what closing blocks. A tunnel it does not run is still disclosed. And the panel shows the node's
      own `lans` over its name test.
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_OWNED = "--perturb-owned" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel", PANEL)
N = load("swgnoded", NODED)
REAL_LAN_NETS = N._node_lan_nets
if PERTURB_OWNED:
    N._own_tunnel_devs = lambda *a, **k: set()
CP = N.subprocess.CompletedProcess

print("\n[1] panel and node agree on what a private network is")
for ip, want in (("192.168.1.5", True), ("10.0.0.1", True), ("172.16.0.1", True), ("172.31.255.1", True),
                 ("172.32.0.1", False), ("100.64.1.1", True), ("100.127.255.1", True), ("100.128.0.1", False),
                 ("203.0.113.5", False), ("127.0.0.1", False), ("169.254.1.1", False), ("fd00::1", False),
                 ("garbage", False), (None, False)):
    p, n = P.lan_private(ip), N.lan_private(ip)
    check("%-14s panel %s node %s (want %s)" % (ip, p, n, want), p == n == want)

print("\n[2] node_lans — the disclosure, from what nodes already report")
snap = {"node_ip_ifaces": [{"ip": "192.168.1.50", "iface": "eth0"}, {"ip": "203.0.113.5", "iface": "eth1"},
                           {"ip": "10.255.0.6", "iface": "swg_ab12"}, {"ip": "100.64.3.9", "iface": "ppp0"}]}
check("private addresses on cards only — public and mesh left out",
      P.node_lans(snap) == [{"ip": "192.168.1.50", "iface": "eth0"}, {"ip": "100.64.3.9", "iface": "ppp0"}], P.node_lans(snap))
check("an old node with only node_ips still discloses", P.node_lans({"node_ips": ["10.1.2.3", "8.8.8.8"]}) == [{"ip": "10.1.2.3", "iface": ""}])
check("no snapshot → nothing, never an error", P.node_lans(None) == [] and P.node_lans({}) == [])

print("\n[2b] the node's own word comes first")
sw = {"lans": [], "node_ip_ifaces": [{"ip": "10.11.0.1", "iface": "wdtt1"}, {"ip": "10.10.0.1", "iface": "csqtt1"}]}
check("a node reporting lans: [] discloses nothing, whatever its tunnels are called (swgt)", P.node_lans(sw) == [], P.node_lans(sw))
check("a reported LAN is shown as the node reported it — a public address still filtered",
      P.node_lans({"lans": [{"ip": "192.168.1.50", "iface": "eth0"}, {"ip": "203.0.113.5", "iface": "x"}]})
      == [{"ip": "192.168.1.50", "iface": "eth0"}])

print("\n[3] the ruleset")
rs = N._lan_ruleset(["192.168.1.0/24", "10.20.0.0/16"], ["awg0", "wg1"])
check("created then deleted then declared — one atomic load, no gap", rs.startswith(
      "table inet swg_lan\ndelete table inet swg_lan\ntable inet swg_lan {"), rs)
check("a DETERMINISTIC priority below the filter-priority hooks (§4.7)", "hook forward priority filter - 5;" in rs, rs)
check("drops from the client tunnels to every private network",
      'iifname { "awg0", "wg1" } ip daddr { 192.168.1.0/24, 10.20.0.0/16 } counter drop' in rs, rs)
check("…and from clients of other nodes arriving over a mesh link", 'iifname "swg_*" ip daddr { 192.168.1.0/24, 10.20.0.0/16 } counter drop' in rs, rs)
check("no client tunnel yet → the mesh rule alone, no empty set", "iifname {" not in N._lan_ruleset(["192.168.1.0/24"], []))

CALLS = []
def stub(rc=None):
    rc = rc or {}
    def run(a, input_text=None, timeout=20):
        CALLS.append((list(a), input_text))
        key = "list" if a[:3] == ["nft", "list", "table"] else "delete" if a[:3] == ["nft", "delete", "table"] else "load" if a[:2] == ["nft", "-f"] else "other"
        return CP(a, rc.get(key, 0), "", rc.get(key + "_err", ""))
    N.run = run
def fresh():
    N._LAN.update(probed=False, installed=False, sig=None, status=None)
    del CALLS[:]
if PERTURB:
    _orig = N.reconcile_lan_block
    def _skip_probe(block, res):
        N._LAN["probed"] = True
        return _orig(block, res)
    N.reconcile_lan_block = _skip_probe

print("\n[4] D1 while sharing — and the restart")
fresh(); stub({"list": 1})
res = {"changed": 0, "errors": []}
check("first pass: returns None (the snapshot carries no key)", N.reconcile_lan_block(False, res) is None)
check("…asked the kernel exactly once", [c[0] for c in CALLS] == [["nft", "list", "table", "inet", "swg_lan"]], CALLS)
del CALLS[:]
for _ in range(3):
    N.reconcile_lan_block(False, res)
check("every later pass: NO subprocess at all", CALLS == [], CALLS)
fresh(); stub({"list": 0})
N.reconcile_lan_block(False, res)
check("RESTART: a table left from before is found and removed — a re-opened LAN does not stay closed",
      ["nft", "delete", "table", "inet", "swg_lan"] in [c[0] for c in CALLS] and not N._LAN["installed"], CALLS)

print("\n[5] blocking")
fresh(); stub({"list": 1})
N._node_lan_nets = lambda *a: ["192.168.1.0/24"]
N._CLIENT_DEVS["list"] = ["awg0", 'bad"name', "wg1"]
res = {"changed": 0, "errors": []}
st = N.reconcile_lan_block(True, res)
loads = [c for c in CALLS if c[0][:2] == ["nft", "-f"]]
check("installed with one load", len(loads) == 1 and st == {"on": True, "ok": True, "nets": ["192.168.1.0/24"]}, (loads, st))
check("a device name that could break out of its quotes never reaches nft", 'bad"name' not in loads[0][1] and '"awg0", "wg1"' in loads[0][1], loads[0][1])
del CALLS[:]; stub({"list": 0})
N.reconcile_lan_block(True, res)
check("steady state: re-read, NOT rebuilt", [c[0][:3] for c in CALLS] == [["nft", "list", "table"]], CALLS)
del CALLS[:]; stub({"list": 1})
N.reconcile_lan_block(True, res)
check("a table somebody flushed away is rebuilt", any(c[0][:2] == ["nft", "-f"] for c in CALLS), CALLS)
del CALLS[:]; stub({"list": 0})
N._CLIENT_DEVS["list"] = ["awg0", "wg1", "wg2"]
N.reconcile_lan_block(True, res)
check("a new client tunnel rebuilds it", any(c[0][:2] == ["nft", "-f"] and '"wg2"' in c[1] for c in CALLS), CALLS)
del CALLS[:]
st = N.reconcile_lan_block(False, res)
check("sharing again removes it and reports nothing", st is None and ["nft", "delete", "table", "inet", "swg_lan"] in [c[0] for c in CALLS], CALLS)

print("\n[6] failure never opens it")
fresh(); stub({"list": 0})
N._LAN.update(probed=True, installed=True, sig="old")
N._node_lan_nets = lambda *a: None
res = {"changed": 0, "errors": []}
st = N.reconcile_lan_block(True, res)
check("addresses unreadable: the installed table is LEFT, and it says so",
      st["ok"] is False and st["why"] == "addresses_unreadable" and not any(c[0][:3] == ["nft", "delete", "table"] for c in CALLS)
      and res["errors"], (st, CALLS))
fresh(); stub({"list": 1, "load": 1, "load_err": "Error: Could not process rule: No such file or directory"})
N._node_lan_nets = lambda *a: ["192.168.1.0/24"]
st = N.reconcile_lan_block(True, {"changed": 0, "errors": []})
check("a failed load says why, and forgets what it thought was installed",
      st["ok"] is False and st["why"] == "nft_failed" and "No such file" in st["detail"] and N._LAN["probed"] is False, st)
fresh(); stub({"list": 0})
N._node_lan_nets = lambda *a: []
st = N.reconcile_lan_block(True, {"changed": 0, "errors": []})
check("no private network on any card: nothing to close, and a leftover table goes",
      st == {"on": True, "ok": True, "nets": []} and ["nft", "delete", "table", "inet", "swg_lan"] in [c[0] for c in CALLS], (st, CALLS))

print("\n[8] the node judges a device by what it runs, not by its name")
_winst = {"raw_port": "56003", "raw_iface": "wdtt1r", "raw_addr": "10.12.0.1/24", "listen": "0.0.0.0:56000"}
N._CLIENT_DEVS["list"] = ["wg1"]
N._wdtt_load = lambda: {"wdtt1": _winst}
N._csqtt_load = lambda: {"csqtt1": {"tun_addr": "10.10.0.1/24"}}
N._EXITS["list"] = [{"id": "x1", "device": "tun-exit"}]
N._DEVEXIT["list"] = [{"dev": "tun0"}]
_raw = N._wdtt_raw(_winst)
check("(the fixture's WDTT instance runs a RAW TUN)", bool(_raw) and _raw[1] == "wdtt1r", _raw)
own = N._own_tunnel_devs({"interfaces": {"awg2": {}}})
check("owned: client and config interfaces, WDTT + its RAW TUN, csqtt, exit devices",
      {"wg1", "awg2", "wdtt1", "wdtt1r", "csqtt1", "tun-exit", "tun0"} <= own, own)
addrs = [("eth0", "192.168.1.50"), ("wdtt1", "10.11.0.1"), ("wdtt1r", "10.12.0.1"), ("csqtt1", "10.10.0.1"),
         ("tun-lab0", "10.66.0.2"), ("eth2", "203.0.113.9")]
rep = N._node_lans_report(addrs, own)
check("the snapshot's lans: the LAN card and a tunnel the node does NOT run — never its own tunnels, never public",
      rep == [{"ip": "192.168.1.50", "iface": "eth0"}, {"ip": "10.66.0.2", "iface": "tun-lab0"}], rep)
N._local_addrs = lambda: [("eth0", "192.168.1.50", "192.168.1.0/24"), ("wdtt1", "10.11.0.1", "10.11.0.0/24"),
                          ("wdtt1r", "10.12.0.1", "10.12.0.0/24"), ("csqtt1", "10.10.0.1", "10.10.0.0/24"),
                          ("tun-lab0", "10.66.0.2", "10.66.0.2/32"), ("wg1", "10.8.0.1", "10.8.0.0/24")]
nets = REAL_LAN_NETS(own)
check("closing blocks exactly the networks the report shows", nets == ["10.66.0.2/32", "192.168.1.0/24"], nets)
check("a VPS whose only private addresses are its own tunnels reports and blocks nothing",
      N._node_lans_report(addrs[1:4], own) == [] and [n for n in nets if n.startswith("10.1")] == [], (addrs[1:4], nets))

print("\n[7] lan_share is stored only as a departure from the default")
TMP = tempfile.mkdtemp(prefix="lanblock-")
nodes_path, roster_path = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
json.dump({"n1": {"id": "n1", "name": "home"}}, open(nodes_path, "w"))
json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(roster_path, "w"))
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {}, "stats_dir": TMP, "fleet": {}}
try:
    code, _ = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "lan_share": False}, deps)
    closed = json.load(open(nodes_path))["n1"]
    code2, _ = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "lan_share": True}, deps)
    reopened = json.load(open(nodes_path))["n1"]
    check("closing writes lan_share: false", code == 200 and closed.get("lan_share") is False, (code, closed))
    check("re-opening REMOVES the key rather than writing true", code2 == 200 and "lan_share" not in reopened, (code2, reopened))
except Exception as e:
    check("the /api/nodes/update round trip ran", False, repr(e))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
