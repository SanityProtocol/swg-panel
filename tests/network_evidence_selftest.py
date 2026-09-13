#!/usr/bin/env python3
"""Self-test for NETWORKS P3 — evidence, all on the panel (docs/NETWORKS-PLAN.md §4.9, §4.10, features 7, 8, 12, 13).

  [1] the gateway, as the node sees it: online and last handshake, its byte counters, its effective keepalive —
      and `reported` False when the node lists no such peer, never a guessed "offline".
  [2] §4.9 — a gateway on SEVERAL nodes needs a live session with each, which only its keepalive keeps; a
      keepalive of 0 is named per node. On one node it is nobody's business.
  [3] "my networks": per deployment, every network another provider carries on that node; `covered` from the
      client's own rendered routing; a device's own networks not listed for it; a keyless deployment's routing
      reported as unknown, not as "covered"; the node's own LAN with whether it is open.
  [4] §4.10 — the cross-product is ON DEMAND: `/api/state`'s node builder never computes it.

Hermetic. Run: python3 tests/network_evidence_selftest.py            (0 = pass)
     --perturb   makes every client config "cover" every network and expects RED on [3].
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if PERTURB:
    P._allowed_covers = lambda allowed, prefix: True

def snap(peers, lan=True):
    s = {"node_ips": ["203.0.113.5"] + (["192.168.1.50"] if lan else []),
         "node_ip_ifaces": [{"ip": "203.0.113.5", "iface": "eth0"}] + ([{"ip": "192.168.1.50", "iface": "eth1"}] if lan else []),
         "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24", "address": "10.8.0.1/24"}, "peers": peers}},
         "ether_gws": {"eth0": "203.0.113.1"},
         "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True}}
    return s
K = lambda c: c * 43 + "="
T = lambda ip, node="n1", **k: dict({"node": node, "iface": "awg0", "ip": ip, "type": "awg"}, **k)
R = {"users": {"u1": {"name": "Alice"}, "u2": {"name": "Bob"}},
     "peers": {
         "gwA": {"id": "gwA", "user_id": "u1", "pubkey": K("A"), "created_at": 10, "title": "office",
                 "targets": [T("10.8.0.10"), T("10.8.1.10", node="n2", overrides={"keepalive": 0})],
                 "routes": ["192.168.50.0/24"]},
         "pB": {"id": "pB", "user_id": "u2", "pubkey": K("B"), "created_at": 20, "title": "laptop", "targets": [T("10.8.0.11")]},
         "pC": {"id": "pC", "user_id": "u2", "pubkey": K("C"), "created_at": 30, "title": "phone",
                "targets": [T("10.8.0.12", overrides={"allowed": "10.8.0.0/24"})]},
         "pD": {"id": "pD", "user_id": "u2", "created_at": 40, "title": "turn", "wdtt_password": "x",
                "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
     }}
SNAPS = {"n1": snap([{"public_key": K("A"), "online": True, "handshake_age": 12, "rx_bytes": 5000, "tx_bytes": 7000,
                      "rx_speed": 10.0, "tx_speed": 20.0},
                     {"public_key": K("B"), "online": True}]),
         "n2": dict(snap([], lan=False), interfaces={"awg0": {"meta": {"subnet": "10.8.1.0/24", "address": "10.8.1.1/24"},
                                                              "peers": [{"public_key": K("A"), "online": False, "handshake_age": 900}]}})}

print("\n[1] the gateway, as each node sees it")
rep = P.network_report(R, "gwA", SNAPS)
g1 = next(e for e in rep["targets"] if e["node"] == "n1")["gateway"]
g2 = next(e for e in rep["targets"] if e["node"] == "n2")["gateway"]
check("n1: online, last handshake, traffic THROUGH the gateway",
      g1 == {"reported": True, "online": True, "handshake_age": 12, "keepalive": 25,
             "rx_bytes": 5000, "tx_bytes": 7000, "rx_speed": 10.0, "tx_speed": 20.0}, g1)
check("n2: reported but offline, and its own keepalive (0, from that deployment's override)",
      g2["reported"] and not g2["online"] and g2["handshake_age"] == 900 and g2["keepalive"] == 0, g2)
S_MISSING = dict(SNAPS, n1=snap([]))
g0 = next(e for e in P.network_report(R, "gwA", S_MISSING)["targets"] if e["node"] == "n1")["gateway"]
check("a node that lists no such peer says `reported: false` — not a guessed offline", g0["reported"] is False and g0["online"] is False, g0)

print("\n[2] §4.9 — the multi-node keepalive check")
check("on two nodes, the node whose deployment has keepalive 0 is named", rep["multi_node"] and rep["keepalive_off"] == ["n2"], rep)
R1 = dict(R, peers=dict(R["peers"], gwA=dict(R["peers"]["gwA"], targets=[T("10.8.0.10", overrides={"keepalive": 0})])))
rep1 = P.network_report(R1, "gwA", SNAPS)
check("on ONE node a keepalive of 0 is not flagged", rep1["multi_node"] is False and rep1["keepalive_off"] == [], rep1)

print("\n[3] my networks")
un = P.user_networks(R, "u2", SNAPS, nodes={"n1": {"lan_share": False}})
by = {p["peer_id"]: p for p in un["peers"]}
tB, tC, tD = by["pB"]["targets"][0], by["pC"]["targets"][0], by["pD"]["targets"][0]
check("a full-tunnel device: the office network via its gateway, covered",
      tB["networks"] == [{"prefix": "192.168.50.0/24", "via": "gwA", "covered": True}], tB)
check("a narrowed device: the same network, NOT covered", tC["networks"] == [{"prefix": "192.168.50.0/24", "via": "gwA", "covered": False}], tC)
check("a keyless deployment: covered is unknown (None), never assumed", tD["networks"][0]["covered"] is None, tD)
check("the node's own LAN, closed on this node", tB.get("lan") == {"addrs": ["192.168.1.50"], "open": False}, tB)
own = P.user_networks(R, "u1", SNAPS)["peers"][0]["targets"]
check("the gateway's own networks are not listed as something it reaches", all(n["via"] != "gwA" for t in own for n in t["networks"]), own)
check("a node without a private address has no LAN entry", "lan" not in next(t for t in own if t["node"] == "n2"), own)
RB = dict(R, users=dict(R["users"], u1={"name": "Alice", "disabled": True}))
check("a blocked provider's network disappears from everyone's list",
      P.user_networks(RB, "u2", SNAPS)["peers"][0]["targets"][0]["networks"] == [])

print("\n[4] §4.10 — on demand only")
src = open(PANEL).read()
# ⚠️ BY HANDLER, NOT BY `def`. The node records are built inside the `/api/fleet` branch of one very large `api()`,
# which ALSO holds the on-demand endpoints — slicing by function found those and read them as the poll path.
HANDLER = re.compile(r'\n    if method == "[A-Z]+" and path == "([^"]+)"')
def branch(path):
    ms = list(HANDLER.finditer(src))
    for i, mm in enumerate(ms):
        if mm.group(1) == path:
            return src[mm.start():(ms[i + 1].start() if i + 1 < len(ms) else len(src))]
    return ""
fleet, state = branch("/api/fleet"), branch("/api/state")
check("found the /api/fleet branch that builds node records", '"lans": node_lans(snap, _is_sysif)' in fleet)
check("found the /api/state branch", bool(state))
for name, body in (("/api/fleet", fleet), ("/api/state", state)):
    hit = re.search(r"\b(user_networks|network_report|node_networks)\(", body)
    check("%s never computes the cross-product" % name, not hit, hit and hit.group(0))
check("CONTROL: the guard can see a call when there is one", bool(re.search(
      r"\b(user_networks|network_report|node_networks)\(", branch("/api/users/networks"))))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
