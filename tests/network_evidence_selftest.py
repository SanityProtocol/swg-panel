#!/usr/bin/env python3
"""Self-test for NETWORKS P3 — evidence, all on the panel (docs/NETWORKS-PLAN.md §4.9, §4.10, features 7, 8, 12, 13).

  [1] the gateway, as the node sees it: online and last handshake, its byte counters, its effective keepalive —
      and `reported` False when the node lists no such peer, never a guessed "offline".
  [2] §4.9 — a gateway on SEVERAL nodes needs a live session with each, which only its keepalive keeps; a
      keepalive of 0 is named per node. On one node it is nobody's business.
  [3] "my networks": per deployment, every network another provider carries on that node; `covered` from the
      client's own rendered routing; a device's own networks not listed for it; a keyless deployment's routing
      reported as unknown, not as "covered"; the node's own LAN with whether it is open AND whether this device
      actually routes it (a narrowed device does not, and must not be shown as reaching it).
  [4] §4.10 — the cross-product is ON DEMAND: `/api/state`'s node builder never computes it.

Hermetic. Run: python3 tests/network_evidence_selftest.py            (0 = pass)
     --perturb   makes every client config "cover" every network and expects RED on [3].
     --perturb-lanpath  judges every LAN as if the device's routing stayed on its node and expects RED on [3b].
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_LANPATH = "--perturb-lanpath" in sys.argv

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
if PERTURB_LANPATH:
    P.lan_path = lambda cas, nodes, nid, subnet, addr: ("here", None)

def snap(peers, lan=True):
    s = {"node_ips": ["203.0.113.5"] + (["192.168.1.50"] if lan else []),
         "node_ip_ifaces": [{"ip": "203.0.113.5", "iface": "eth0"}]
                           + ([{"ip": "192.168.1.50", "iface": "eth1"}, {"ip": "172.16.5.10", "iface": "eth2"}] if lan else []),
         "lans": ([{"ip": "192.168.1.50", "iface": "eth1"}, {"ip": "172.16.5.10", "iface": "eth2"}] if lan else []),
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
                # routes ONE of the node's two private addresses (172.16.5.10) and not the other (192.168.1.50)
                "targets": [T("10.8.0.12", overrides={"allowed": "10.8.0.0/24, 172.16.5.0/24"})]},
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
      g1 == {"reported": True, "online": True, "handshake_age": 12, "keepalive": 25, "allowed": "0.0.0.0/0, ::/0",
             "full_tunnel": True, "no_return": False,
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
check("the node's own LAN, closed on this node — and a full-tunnel device does route it",
      tB.get("lan") == {"addrs": ["192.168.1.50", "172.16.5.10"], "open": False, "covered": True}, tB)
# ⚠️ The sheet used to mark this row reachable by every device unconditionally. A device narrowed to the tunnel subnet never
# routes the node's LAN, and saying it does is the failure mode that matters: someone reads "reachable" and acts on it.
check("a NARROWED device does not reach the node's LAN — asked, never assumed",
      tC.get("lan", {}).get("covered") is False, tC.get("lan"))
# ⚠️ ALL-of, not any-of: this device routes 172.16.5.0/24 (one of the node's two private addresses) and not the other,
# so it does NOT reach "the node's local network". With any() it would read as reaching it, and the row names them as
# one place. This is the case that makes the two spellings differ at all.
check("…and covering ONE of a node's two private addresses is not covering it",
      tC["lan"]["addrs"] == ["192.168.1.50", "172.16.5.10"] and tC["lan"]["covered"] is False, tC.get("lan"))
check("a keyless deployment's reach into the node's LAN is unknown, not assumed either way",
      "covered" in tD.get("lan", {}) and tD["lan"]["covered"] is None, tD.get("lan"))
# The operator's setting (panel-wide, OFF by default): a node's own private network is nobody's configuration — it is
# whatever the node happens to sit on — so it stays out of a user's list until an operator asks for it. Applied at the
# endpoint, never here: this function reports what is true, so everything above keeps testing reality.
offB = {p["peer_id"]: p for p in
        P.user_networks(R, "u2", SNAPS, nodes={"n1": {"lan_share": False}}, show_lans=False)["peers"]}["pB"]["targets"][0]
check("show_lans off: the node's own LAN is left out entirely", "lan" not in offB, offB)
check("show_lans off changes nothing else — carried networks are still listed and still judged",
      offB["networks"] == [{"prefix": "192.168.50.0/24", "via": "gwA", "covered": True}], offB)
# ⚠️ ON by default, and the reason is not cosmetic: off CLOSES these networks on every node (see lan_block_selftest [9]).
# A default of off would have closed every fleet's LAN on upgrade, dropping traffic nobody asked to drop.
check("shown by default — turning it off is a deliberate act, because it is also what closes them",
      P.PANEL_SETTINGS_DEFAULTS.get("show_node_lans") is True, P.PANEL_SETTINGS_DEFAULTS.get("show_node_lans"))
# The COUNT beside a user's name is this list's own length, computed here rather than guessed in a browser — a count and
# a list that can disagree is the bug that started this (the chip said 1, the sheet said 4).
check("the count is one per (node, network), with the node's own LAN as one more",
      P.net_rows_count(P.user_networks(R, "u2", SNAPS, nodes={"n1": {"lan_share": False}})) == 2,
      P.net_rows_count(P.user_networks(R, "u2", SNAPS, nodes={"n1": {"lan_share": False}})))
check("…and it follows the setting: with node LANs off, only the carried network is counted",
      P.net_rows_count(P.user_networks(R, "u2", SNAPS, show_lans=False)) == 1)
check("a blocked device contributes nothing to the count",
      P.net_rows_count(P.user_networks(dict(R, users=dict(R["users"], u1={"name": "Alice", "disabled": True})), "u2", SNAPS,
                                       show_lans=False)) == 0)
# A batch shares ONE carry plan per node across every user in it — that is what makes asking for a page of rows cheap.
# It must not change a single answer.
_shared = {}
check("a shared carry plan gives the identical answer to computing it per user",
      [P.net_rows_count(P.user_networks(R, u, SNAPS, plans=_shared)) for u in ("u1", "u2")]
      == [P.net_rows_count(P.user_networks(R, u, SNAPS)) for u in ("u1", "u2")],
      _shared and list(_shared))
print("\n[3b] the LAN a device actually reaches follows its routing (qualification 1.8.7 §N13)")
# ⚠️ A forward or smart table holds only the node's client subnets and carried networks, so a device a forward sends through a
# mesh leg does NOT reach its own node's LAN — it reaches the EXIT node's. Measured on swgt: told msk-main's, reached svo-im's.
_NF = {"n1": {"links": {"n2": {"iface": "swg_a"}}}, "n2": {"links": {"n1": {"iface": "swg_b"}}}}
_S2 = dict(snap([], lan=False), lans=[{"ip": "10.144.0.1", "iface": "nqlanh"}],
           interfaces={"awg0": {"meta": {"subnet": "10.8.1.0/24", "address": "10.8.1.1/24"}, "peers": []}})
_RF = dict(R, peers=dict(R["peers"],
    gwX={"id": "gwX", "user_id": "u1", "pubkey": K("X"), "created_at": 50, "routes": ["192.168.142.0/24"],
         "targets": [T("10.8.1.20", node="n2")]},
    gwY={"id": "gwY", "user_id": "u1", "pubkey": K("Y"), "created_at": 60, "routes": ["192.168.143.0/24"], "share": {"users": {}},
         "targets": [T("10.8.1.21", node="n2")]}))
_SF = dict(SNAPS, n2=dict(_S2, net_deps=dict(_S2["net_deps"], share=1)))
def _un(cas):
    d = P.user_networks(_RF, "u2", _SF, nodes=_NF, cas=cas)
    return {p["peer_id"]: p for p in d["peers"]}["pB"]["targets"]
_fwd = {"n1": {"forward": [{"subnet": "10.8.0.0/24", "via_iface": "swg_a", "table": 7000}]}}
t_fwd = _un(_fwd)
check("⚠️ forward: the entry node's LAN is NOT listed — the device's traffic to it goes into the leg",
      "lan" not in t_fwd[0] and t_fwd[0]["node"] == "n1", t_fwd)
check("…the networks its own node carries still are (they sit in the forward table)",
      [n["prefix"] for n in t_fwd[0]["networks"]] == ["192.168.50.0/24"], t_fwd[0])
_far = next((t for t in t_fwd if t["node"] == "n2"), None)
check("⚠️ …and the EXIT node's LAN is, under that node, through the entry node",
      bool(_far) and _far.get("through") == "n1" and (_far.get("lan") or {}).get("addrs") == ["10.144.0.1"], _far)
check("⚠️ …with the network open to everyone there, and NOT the restricted one (mesh arrivals are never a source)",
      bool(_far) and [n["prefix"] for n in _far["networks"]] == ["192.168.142.0/24"], _far)
# pB and pC on the forwarded subnet: n1's carried network, n2's open network, n2's LAN. pD is a WDTT deployment whose instance the
# plan does not forward, so it still reaches n1's LAN — one more row, which is the point: rows follow each device's own routing.
check("…and the count follows the rows", P.net_rows_count(P.user_networks(_RF, "u2", _SF, nodes=_NF, cas=_fwd)) == 4,
      P.net_rows_count(P.user_networks(_RF, "u2", _SF, nodes=_NF, cas=_fwd)))
t_dir = _un({"n1": {"forward": [{"subnet": "10.99.0.0/24", "via_iface": "swg_a", "table": 7000}]}})
check("control: a forward for ANOTHER subnet leaves this device on its own node's LAN, and nothing far",
      "lan" in t_dir[0] and len(t_dir) == 1, t_dir)
t_dev = _un({"n1": {"devexit": [{"subnet": "10.8.0.0/24", "dev": "wgcf", "table": 7001}]}})
check("a whole-interface device exit reaches neither LAN", "lan" not in t_dev[0] and len(t_dev) == 1, t_dev)
t_ks = _un({"n1": {"devexit": [{"subnet": "10.8.0.0/24", "dev": "wgcf", "table": 7001, "scope": "rule"}]}})
check("…while a device exit for ONE rule leaves the rest on the node", "lan" in t_ks[0], t_ks)
t_sd = _un({"n1": {"smart": [{"subnet": "10.8.0.0/24", "category": "yandex", "action": "exit", "via_iface": "swg_a"},
                             {"subnet": "10.8.0.0/24", "category": "all", "action": "direct"}]}})
check("smart with the catch-all direct: the node's own LAN", "lan" in t_sd[0] and len(t_sd) == 1, t_sd)
t_sx = _un({"n1": {"smart": [{"subnet": "10.8.0.0/24", "category": "all", "action": "exit", "via_iface": "swg_a"}]}})
check("smart with the catch-all through a leg: the exit node's", "lan" not in t_sx[0] and any(t["node"] == "n2" for t in t_sx), t_sx)
t_sc = _un({"n1": {"smart": [{"subnet": "10.8.0.0/24", "category": "c1", "action": "block"},
                             {"subnet": "10.8.0.0/24", "category": "all", "action": "direct"}], "cidrs": {"c1": ["192.168.0.0/16"]}}})
check("smart: a custom rule whose own prefixes hold the LAN decides it, before the catch-all",
      "lan" not in t_sc[0] and len(t_sc) == 1, t_sc)

own = P.user_networks(R, "u1", SNAPS)["peers"][0]["targets"]
check("the gateway's own networks are not listed as something it reaches", all(n["via"] != "gwA" for t in own for n in t["networks"]), own)
check("a node without a private address has no LAN entry", "lan" not in next(t for t in own if t["node"] == "n2"), own)
S_OLD = dict(SNAPS, n1={k: v for k, v in SNAPS["n1"].items() if k != "lans"})
old = P.user_networks(R, "u2", S_OLD)["peers"][0]["targets"][0]
check("a node that does not judge its own devices (no `lans`) claims no local network — its name test reads tunnel pools as LANs",
      "lan" not in old, old)
RB = dict(R, users=dict(R["users"], u1={"name": "Alice", "disabled": True}))
check("a blocked provider's network disappears from everyone's list",
      P.user_networks(RB, "u2", SNAPS)["peers"][0]["targets"][0]["networks"] == [])

print("\n[5] the gateway's OWN routing — the config the panel renders for it")
def gw(**ov):
    r = dict(R, peers=dict(R["peers"], gwA=dict(R["peers"]["gwA"], targets=[T("10.8.0.10", overrides=ov)] if ov else [T("10.8.0.10")])))
    return next(e for e in P.network_report(r, "gwA", SNAPS)["targets"] if e["node"] == "n1")["gateway"]
g = gw()
check("the default config sends everything into the tunnel — flagged full_tunnel, with a way back", g["full_tunnel"] and not g["no_return"], g)
g = gw(allowed="10.8.0.0/24")
check("routing only the tunnel subnet: neither flag", not g["full_tunnel"] and not g["no_return"], g)
g = gw(allowed="10.8.0.0/16")
check("a wider prefix that still holds the subnet: neither flag", not g["full_tunnel"] and not g["no_return"], g)
g = gw(allowed="172.16.0.0/12")
check("routing that leaves the tunnel subnet out: no_return (answers never come back)", g["no_return"] and not g["full_tunnel"], g)
g = gw(allowed="0.0.0.0/1, 128.0.0.0/1")
check("split halves are not a /0: not called full_tunnel, and the subnet IS covered", not g["full_tunnel"] and not g["no_return"], g)

print("\n[6] routed, not just sent — the node's `net_carried`, and whether it can limit who reaches a network")
e = lambda s: next(x for x in P.network_report(R, "gwA", dict(SNAPS, n1=s))["targets"] if x["node"] == "n1")
s_old = SNAPS["n1"]
check("a node that does not report routes: the plan's word stands (active), can_share False (no `share` flag)",
      e(s_old)["networks"][0]["state"] == "active" and e(s_old)["can_share"] is False, e(s_old))
s_new = dict(s_old, net_deps=dict(s_old["net_deps"], carried=1, share=1))
check("a node that reports routes but has not routed it yet: pending", e(s_new)["networks"][0]["state"] == "pending", e(s_new))
check("…pending still counts as what saving means (audience and routing checks run)",
      e(s_new)["audience"]["peers"] >= 1 and e(s_new)["widen_total"] >= 1, e(s_new))
s_done = dict(s_new, net_carried=["192.168.50.0/24"])
check("once the node lists it in net_carried: active, and can_share True", e(s_done)["networks"][0]["state"] == "active"
      and e(s_done)["can_share"] is True, e(s_done))
s_ref = dict(s_new, net_refused={"192.168.50.0/24": {"why": "rolled_back", "addr": ""}})
check("a refusal outranks pending", e(s_ref)["networks"][0]["state"] == "refused_by_node", e(s_ref))
check("a node with no net_deps at all: can_share None (it can't guard networks; the reason line says so)",
      e(dict(s_old, net_deps=None))["can_share"] is None)

print("\n[7] a peer with a turn-server AND a WireGuard deployment on one node carries through the WireGuard one")
KL = {"node": "n1", "iface": "wdtt1", "type": "wdtt"}
RM = dict(R, peers=dict(R["peers"], gwA=dict(R["peers"]["gwA"], targets=[KL, T("10.8.0.10")])))
plan = P.node_networks(RM, "n1", SNAPS["n1"])
check("node_networks carries it, on the keyed interface — not inert self_contained behind the keyless one listed first",
      (plan["carry"].get("gwA") or {}).get("iface") == "awg0" and "gwA" not in plan["inert"], plan)
em = next(x for x in P.network_report(RM, "gwA", SNAPS)["targets"] if x["node"] == "n1")
check("…and the report's entry for that node is the keyed deployment, with its gateway row",
      em["iface"] == "awg0" and em["networks"][0]["state"] == "active" and "gateway" in em, em)
RK = dict(R, peers=dict(R["peers"], gwA=dict(R["peers"]["gwA"], targets=[KL])))
ek = P.network_report(RK, "gwA", SNAPS)["targets"][0]
check("a node where the only deployment is keyless: still inert, self_contained", ek["networks"][0]["state"] == "inert"
      and ek["networks"][0].get("why") == "self_contained", ek)
check("node order is the order the peer lists its nodes in",
      [x["node"] for x in P.network_report(R, "gwA", SNAPS)["targets"]] == ["n1", "n2"])

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

print()
if PERTURB or PERTURB_LANPATH or globals().get("PERTURB_OWNED"):
    # ⚠️ Without this a perturbation that perturbed NOTHING exits 0 and is indistinguishable from a real pass — which is
    # exactly how an ineffective anchor replacement hides. Red is the only success here.
    _ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: %s" % (len(FAILS), "every LAN judged as if the device's routing stayed on its node"
                                                     if PERTURB_LANPATH else "every client config now covers every network")) if _ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if _ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
