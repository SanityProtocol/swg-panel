#!/usr/bin/env python3
"""Self-test for NETWORKS P1 on the node — the route reconciler in `main` (docs/NETWORKS-PLAN.md D6, D14, §4.11,
§4.12) and the ACL filter in front of it.

  [1] §4.12 INERT. With no peer carrying a network the reconciler forks nothing and asks no interface for its
      ACL, and the filter hands back the very object it was given. D1 is a claim about the control path too.
  [2] a wanted network is installed once; [3] one already routed is left alone.
  [4] §4.11 — a /32 network does not churn. The kernel prints it bare; every fixture anyone writes is a /24.
  [5] D6 — a route nothing wants is reaped; a mesh link's and a NIC's routes never are.
  [6] D14 — no ACL, no route (and a route without its ACL is reaped until the ACL lands).
  [7] a refused network is stripped from the ACL before `reconcile` could write it to a .conf — including one
      this process has never judged, on the very first sync. Another interface's own /32 is untouched.
  [8] a ROLLED-BACK network stays out of the ACL for its backoff instead of flapping in and out every pass.
  [9] no state file, and a wiped in-memory state converges to the same answer.
 [10] inputs unreadable → nothing reaped blind.

Hermetic: /proc/net/route is a fixture, `run()` a recorder, the guard stubbed.

Run: python3 tests/network_route_reap_selftest.py            (0 = pass)
     --perturb   reads live routes the way `ip route show` prints them (a /32 bare) and expects RED on [4].
"""
import importlib.machinery, importlib.util, ipaddress, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="netreap-")
def conf(name, body):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write(body)
    return p
CFG = {"interfaces": {
    "wg0": {"cmd": ["wg"], "conf": conf("wg0", "[Interface]\nAddress = 10.8.0.1/24\nListenPort = 51820\n")},
    "awg1": {"cmd": ["awg"], "conf": conf("awg1", "[Interface]\nAddress = 10.9.0.1/24\nListenPort = 51821\n")},
    "swg_ab12": {"cmd": ["awg"], "conf": conf("swg_ab12", "[Interface]\nAddress = 10.255.0.6/31\nTable = off\n")},
}}

def hexle(ip):
    a = [int(x) for x in ip.split(".")]
    return "%02X%02X%02X%02X" % (a[3], a[2], a[1], a[0])
def proc(extra=()):
    rows = [("eth0", "0.0.0.0/0", "203.0.113.1"), ("eth0", "203.0.113.0/24", ""), ("wg0", "10.8.0.0/24", ""),
            ("awg1", "10.9.0.0/24", ""), ("swg_ab12", "10.255.0.6/31", "")] + [r + ("",) for r in extra]
    lines = ["Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT"]
    for dev, pre, gw in rows:
        n = ipaddress.ip_network(pre)
        lines.append("%s\t%s\t%s\t0001\t0\t0\t0\t%s\t0\t0\t0" % (dev, hexle(str(n.network_address)),
                     hexle(gw) if gw else "00000000", hexle(str(n.netmask))))
    p = os.path.join(TMP, "route")
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")
    return p

DEPS = {"local": [("eth0", "203.0.113.5", "203.0.113.0/24"), ("wg0", "10.8.0.1", "10.8.0.0/24"),
                  ("awg1", "10.9.0.1", "10.9.0.0/24"), ("swg_ab12", "10.255.0.6", "10.255.0.6/31")],
        "gateways": ["203.0.113.1"], "panel": ["198.51.100.10"], "resolvers": ["198.51.100.53"], "resolvers_known": True}
CP = N.subprocess.CompletedProcess
REC = {}
def setup(acl=None, install=(True, None, ""), deps=True, fresh=True):
    if fresh:
        N._NET.update(refused={}, seen=set(), sig=[], kept=[])
        N._OP_BACKOFF.clear()
    REC.update(run=[], install=[], acl=[])
    N.run = lambda a, input_text=None, timeout=20: REC["run"].append(list(a)) or CP(a, 0, "", "")
    N.net_route_install = lambda p, dev, table="", _guard=True, _verify=True: REC["install"].append((p, dev)) or install
    N._net_guard_deps = (lambda: dict(DEPS)) if deps else (lambda: None)
    N.current_allowed = lambda cfg, iface, dump=None: REC["acl"].append(iface) or dict((acl or {}).get(iface) or {})
def rec(desired, extra=()):
    res = {"changed": 0, "errors": []}
    return N.reconcile_net_routes(CFG, desired, res, _proc=proc(extra)), res

if PERTURB:
    _orig_live = N._net_live_main
    N._net_live_main = lambda cfg, _proc="/proc/net/route": {
        i: {N._net_kernel_dst(p) for p in ps} for i, ps in (_orig_live(cfg, _proc) or {}).items()}

INERT = {"wg0": [{"public_key": "A", "allowed_ips": "10.8.0.10/32"}],
         "awg1": [{"public_key": "B", "allowed_ips": "10.9.0.5/32"}],
         "swg_ab12": [{"public_key": "M", "allowed_ips": "10.255.0.7/32,0.0.0.0/0"}]}   # a mesh /0: never a network
def with_net(*nets, iface="wg0"):
    d = {k: [dict(p) for p in v] for k, v in INERT.items()}
    d[iface][0]["allowed_ips"] = ",".join([d[iface][0]["allowed_ips"]] + list(nets))
    return d
def acl_for(desired, iface="wg0"):
    return {iface: {p["public_key"]: N._norm_allowed(p["allowed_ips"]) for p in desired[iface]}}

print("\n[1] §4.12 — no networks: nothing forked, no ACL read, the filter returns the same object")
setup()
kept, res = rec(INERT)
check("nothing kept", kept == [], kept)
check("no subprocess at all", REC["run"] == [], REC["run"])
check("no interface asked for its ACL", REC["acl"] == [], REC["acl"])
check("net_filter_desired hands back the SAME object", N.net_filter_desired(CFG, INERT) is INERT)
check("…and the routing signature carries nothing", N._NET["sig"] == [], N._NET["sig"])

print("\n[2] a wanted network is installed")
D = with_net("192.168.50.0/24")
setup(acl=acl_for(D))
kept, res = rec(D)
check("installed once, on the provider's interface", REC["install"] == [("192.168.50.0/24", "wg0")], REC["install"])
check("…and returned for the cascade's tables", kept == [("192.168.50.0/24", "wg0")], kept)
check("…nothing deleted", REC["run"] == [], REC["run"])
check("…and remembered as ROUTED for the snapshot's net_carried", N._NET["kept"] == [("192.168.50.0/24", "wg0")], N._NET["kept"])
setup(acl=acl_for(D), install=(False, "rolled_back", "203.0.113.1"))
rec(D)
check("an install that failed is NOT reported as routed", N._NET["kept"] == [], N._NET["kept"])
setup(acl={"wg0": {}})
rec(D)
check("a network the live ACL does not hold yet is NOT reported as routed (D14: ACL first)", N._NET["kept"] == [], N._NET["kept"])
setup()
rec(INERT)
check("no networks: nothing reported as routed", N._NET["kept"] == [], N._NET["kept"])
N._resolvers = lambda: (["198.51.100.53"], True)
check("net_deps announces that this node reports net_carried", N.net_deps().get("carried") == 1, N.net_deps())

print("\n[3] a network already routed is left alone (wg-quick installs the same route — §4.4)")
setup(acl=acl_for(D))
kept, res = rec(D, extra=[("wg0", "192.168.50.0/24")])
check("no install, no delete", REC["install"] == [] and REC["run"] == [], REC)
check("…still returned as held", kept == [("192.168.50.0/24", "wg0")], kept)

print("\n[4] §4.11 — a /32 network does not churn")
check("the kernel's spelling of a /32 is bare", N._net_kernel_dst("172.30.9.9/32") == "172.30.9.9")
D32 = with_net("172.30.9.9/32")
for n in (1, 2, 3):
    setup(acl=acl_for(D32), fresh=(n == 1))
    kept, res = rec(D32, extra=[("wg0", "172.30.9.9/32")])
    check("pass %d: no install and no delete for a /32 already routed" % n,
          REC["install"] == [] and REC["run"] == [], REC)

print("\n[5] D6 — the reaper is derived")
setup()
kept, res = rec(INERT, extra=[("wg0", "192.168.60.0/24"), ("swg_ab12", "10.99.0.0/24"), ("eth0", "10.200.0.0/16")])
check("a route on a client interface that nothing wants is deleted",
      ["ip", "route", "del", "192.168.60.0/24", "dev", "wg0"] in REC["run"], REC["run"])
check("…a mesh link's route is never touched", not any("swg_ab12" in c for c in REC["run"]), REC["run"])
check("…nor a NIC's", not any("eth0" in c for c in REC["run"]), REC["run"])
check("…and exactly one delete", len(REC["run"]) == 1, REC["run"])

print("\n[6] D14 — ACL first, route second")
setup(acl={})
kept, res = rec(D, extra=[("wg0", "192.168.50.0/24")])
check("no ACL → no install", REC["install"] == [], REC["install"])
check("…and a route without its ACL is reaped until the ACL lands",
      ["ip", "route", "del", "192.168.50.0/24", "dev", "wg0"] in REC["run"], REC["run"])

print("\n[7] a refused network never reaches the ACL")
DR = with_net("203.0.113.0/24")                       # the node's own LAN
DR["awg1"][0]["allowed_ips"] = "10.9.0.5/32"
setup(acl=acl_for(DR))
kept, res = rec(DR)
check("refused by the guard, not installed", REC["install"] == [] and
      (N._NET["refused"].get("203.0.113.0/24") or {}).get("why") == "node_lan", N._NET["refused"])
f = N.net_filter_desired(CFG, DR)
check("the filter strips it from its peer's allowed_ips, own /32 kept", f["wg0"][0]["allowed_ips"] == "10.8.0.10/32", f["wg0"])
check("…another interface's peer is the same object, untouched", f["awg1"][0] is DR["awg1"][0])
setup()                                               # FIRST SYNC of a fresh process: no routing pass has run yet
DP = with_net("198.51.100.0/24")                      # contains the panel
f = N.net_filter_desired(CFG, DP)
check("a network never judged is judged by the filter itself, before any ACL exists",
      f["wg0"][0]["allowed_ips"] == "10.8.0.10/32" and N._NET["refused"]["198.51.100.0/24"]["why"] == "node_panel",
      (f["wg0"], N._NET["refused"]))

print("\n[8] a rolled-back network stays out of the ACL — no flapping")
setup(acl=acl_for(D), install=(False, "rolled_back", "203.0.113.1"))
rec(D)
check("pass 1: rolled back → refused", (N._NET["refused"].get("192.168.50.0/24") or {}).get("why") == "rolled_back",
      N._NET["refused"])
filtered = N.net_filter_desired(CFG, D)
setup(acl=acl_for(filtered), install=(True, None, ""), fresh=False)   # the ACL no longer carries it
rec(D)
check("pass 2 (ACL without it, backoff running): still refused, not silently forgotten",
      "192.168.50.0/24" in N._NET["refused"], N._NET["refused"])
check("…so the filter keeps it out again", N.net_filter_desired(CFG, D)["wg0"][0]["allowed_ips"] == "10.8.0.10/32")
check("…and no install was attempted during the backoff", REC["install"] == [], REC["install"])

print("\n[9] no state file; a wiped memory converges to the same answer")
N.STATE_DIR = os.path.join(TMP, "state"); os.makedirs(N.STATE_DIR, exist_ok=True)
setup(acl=acl_for(D))
k1, _ = rec(D, extra=[("wg0", "192.168.50.0/24"), ("wg0", "192.168.61.0/24")])
r1 = list(REC["run"])
setup(acl=acl_for(D))
k2, _ = rec(D, extra=[("wg0", "192.168.50.0/24"), ("wg0", "192.168.61.0/24")])
check("nothing written under the state dir", os.listdir(N.STATE_DIR) == [], os.listdir(N.STATE_DIR))
check("same kept set and same reap after a wipe", k1 == k2 and r1 == REC["run"], (k1, k2, r1, REC["run"]))

print("\n[10] a failed read reaps nothing")
setup(deps=False)
kept, res = rec(D, extra=[("wg0", "192.168.60.0/24")])
check("guard inputs unreadable → no delete, no install, an error said", REC["run"] == [] and REC["install"] == []
      and res["errors"], (REC, res))
setup()
res = {"changed": 0, "errors": []}
check("routing table unreadable → nothing", N.reconcile_net_routes(CFG, D, res, _proc=os.path.join(TMP, "nope")) == []
      and REC["run"] == [] and res["errors"], (REC, res))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
