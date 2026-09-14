#!/usr/bin/env python3
"""Self-test for NETWORKS P1 on the panel — the refusal set, the plan, the save door and the report
(docs/NETWORKS-PLAN.md §4.3, §4.5, §5, §6, D7, D8, D9).

  [1] §5 — one case per token, answered from the snapshot. Including `node_too_old`: a node that does not send
      `net_deps` cannot guard itself, so NOTHING lowers onto it, the ACL included (D7).
  [2] the panel and the node agree token-for-token on the facts both can see. Where they cannot agree it is
      documented and fails CLOSED: the panel knows the node's addresses, not their prefixes, so half the node's
      LAN passes here and is refused there.
  [3] the plan: a blocked provider carries nothing; two providers of one prefix resolve to the EARLIEST
      `created_at` whatever order the roster happens to be in (§4.3 — so it cannot flap); the cap; a provider
      overlapping itself.
  [4] the wire: own /32 FIRST (D9) — the four positional readers still read the address — networks sorted after,
      and nothing at all onto an old node.
  [5] the save door is ASYMMETRIC: a new prefix is refused, a stored one is kept whatever it would say now, and
      "the node cannot guard itself yet" is not a verdict about the prefix.
  [6] `peer_set` preserves `routes` across an unrelated update — the preserve loop that has dropped a field
      three times before.
  [7] the report: the audience counts the whole NODE, never understating the exposure (§4.5); the widening list
      names exactly the narrowed peers (D8); a node-side refusal and a blocked provider both say so.

Hermetic. Run: python3 tests/network_refusal_selftest.py            (0 = pass)
     --perturb   resolves a collision to the LATEST provider and expects RED on [3].
"""
import importlib.machinery, importlib.util, copy, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

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

if PERTURB:
    _sorted = sorted
    def _latest(it, key=None, reverse=False):
        return _sorted(it, key=key, reverse=not reverse)
    P.sorted = _latest                                  # node_networks' winner order, reversed

SNAP = {"node_ips": ["203.0.113.5", "192.168.1.50"],
        "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24", "address": "10.8.0.1/24"}},
                       "wg1": {"meta": {"subnet": "10.9.0.0/24", "address": "10.9.0.1/24"}},
                       "swg_ab12": {"meta": {"subnet": "10.255.0.6/31", "address": "10.255.0.6/31"}}},
        "ether_gws": {"eth0": "203.0.113.1", "eth1": "100.64.0.1"},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True}}
OLD = {k: v for k, v in SNAP.items() if k != "net_deps"}
T_AWG = {"node": "n1", "iface": "awg0", "ip": "10.8.0.10", "type": "awg"}

print("\n[1] §5 — the refusal table")
table = [
    ("garbage", SNAP, T_AWG, ("invalid", "")),
    ("2001:db8::/64", SNAP, T_AWG, ("not_v4", "")),
    ("0.0.0.0/0", SNAP, T_AWG, ("default_route", "")),
    ("169.254.169.254/32", SNAP, T_AWG, ("reserved", "")),
    ("10.50.0.0/24", SNAP, {"node": "n1", "iface": "wdtt1", "type": "wdtt"}, ("self_contained", "")),
    ("10.50.0.0/24", {}, T_AWG, ("no_snapshot", "")),
    ("192.168.1.0/24", SNAP, T_AWG, ("node_lan", "192.168.1.50")),
    ("10.8.0.128/25", SNAP, T_AWG, ("iface_subnet", "10.8.0.1")),
    ("10.9.0.0/16", SNAP, T_AWG, ("iface_subnet", "10.9.0.1")),          # ANOTHER interface's subnet on the node
    ("10.255.0.7/32", SNAP, T_AWG, ("mesh", "10.255.0.6")),
    ("100.64.0.0/24", SNAP, T_AWG, ("node_gateway", "100.64.0.1")),
    ("10.50.0.0/24", OLD, T_AWG, ("node_too_old", "")),
    ("198.51.100.0/28", SNAP, T_AWG, ("node_panel", "198.51.100.10")),
    ("198.51.100.53/32", SNAP, T_AWG, ("node_resolver", "198.51.100.53")),
    ("10.50.0.0/24", dict(SNAP, net_deps=dict(SNAP["net_deps"], resolvers_known=False)), T_AWG, ("resolver_unknown", "")),
    ("10.50.0.0/24", SNAP, T_AWG, (None, "")),
]
for prefix, snap, tg, want in table:
    got = P.network_subnet_refusal(prefix, snap, tg)
    check("%-18s → %s" % (prefix, want[0]), got == want, got)
check("every token returned is in the declared list the SPA words",
      all(w[0] in P._NETWORK_REFUSALS for _p, _s, _t, w in table if w[0]))

print("\n[2] panel and node agree on the facts both can see")
LOCAL = [("eth0", "203.0.113.5", "203.0.113.0/24"), ("lan0", "192.168.1.50", "192.168.1.0/24"),
         ("awg0", "10.8.0.1", "10.8.0.0/24"), ("wg1", "10.9.0.1", "10.9.0.0/24"), ("swg_ab12", "10.255.0.6", "10.255.0.6/31")]
ND = dict(local=LOCAL, gateways=["203.0.113.1", "100.64.0.1"], panel=["198.51.100.10"], resolvers=["198.51.100.53"],
          resolvers_known=True)
for prefix in ("garbage", "2001:db8::/64", "0.0.0.0/0", "169.254.169.254/32", "192.168.1.0/24", "10.8.0.128/25",
               "10.255.0.7/32", "198.51.100.0/28", "198.51.100.53/32", "10.50.0.0/24"):
    pw, nw = P.network_subnet_refusal(prefix, SNAP, T_AWG), N.network_route_refusal(prefix, **ND)
    check("%-18s panel %s == node %s" % (prefix, pw[0], nw[0]), pw == nw, (pw, nw))
pw, nw = P.network_subnet_refusal("192.168.1.128/25", SNAP, T_AWG), N.network_route_refusal("192.168.1.128/25", **ND)
check("the documented asymmetry fails CLOSED: half the LAN passes the panel and the node refuses it",
      pw == (None, "") and nw[0] == "node_lan", (pw, nw))

print("\n[3] the plan — blocked, deterministic winner, cap, self-overlap")
def roster(extra=None):
    r = {"users": {"u1": {"name": "Alice"}, "u2": {"name": "Bob", "disabled": True}},
         "peers": {
             "pA": {"id": "pA", "user_id": "u1", "pubkey": "A" * 43 + "=", "created_at": 100, "title": "office",
                    "targets": [dict(T_AWG)], "routes": ["192.168.50.0/24"]},
             "pB": {"id": "pB", "user_id": "u1", "pubkey": "B" * 43 + "=", "created_at": 200,
                    "targets": [dict(T_AWG, ip="10.8.0.11")], "routes": ["192.168.50.0/25", "10.60.0.0/24"]},
             "pC": {"id": "pC", "user_id": "u2", "pubkey": "C" * 43 + "=", "created_at": 50,
                    "targets": [dict(T_AWG, ip="10.8.0.12")], "routes": ["192.168.50.0/24"]},
             "pD": {"id": "pD", "user_id": "u1", "pubkey": "D" * 43 + "=", "created_at": 60,
                    "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}], "routes": ["10.61.0.0/24"]},
             "pE": {"id": "pE", "user_id": "u1", "pubkey": "E" * 43 + "=", "created_at": 300,
                    "targets": [dict(T_AWG, ip="10.8.0.14")],
                    "routes": ["10.70.0.0/16", "10.70.1.0/24"] + ["10.%d.0.0/24" % i for i in range(80, 88)]},
             "pF": {"id": "pF", "user_id": "u1", "pubkey": "F" * 43 + "=", "created_at": 10,
                    "targets": [dict(T_AWG, ip="10.8.0.15")]},
         }}
    return r
R = roster()
plan = P.node_networks(R, "n1", SNAP)
check("a blocked provider (user disabled) carries nothing and loses nothing to anyone",
      "pC" not in plan["carry"] and "pC" not in plan["inert"], plan)
check("the EARLIEST provider keeps a contested prefix", plan["carry"].get("pA", {}).get("nets") == ["192.168.50.0/24"], plan)
check("…the later one is inert, `taken`, naming who took it",
      plan["inert"].get("pB", {}).get("192.168.50.0/25") == {"why": "taken", "addr": "192.168.50.0/24", "by": "pA"}, plan["inert"])
check("…and keeps its other network", plan["carry"].get("pB", {}).get("nets") == ["10.60.0.0/24"], plan["carry"])
winners = set()
for seed in range(12):
    R2 = roster(); items = list(R2["peers"].items()); random.Random(seed).shuffle(items); R2["peers"] = dict(items)
    winners.add(json.dumps(P.node_networks(R2, "n1", SNAP), sort_keys=True))
check("…whatever order the roster is in (12 shuffles, one answer)", len(winners) == 1, len(winners))
check("a keyless provider is inert, self_contained", plan["inert"].get("pD", {}).get("10.61.0.0/24", {}).get("why") == "self_contained", plan["inert"])
check("a provider overlapping ITSELF: the second is `overlap`", plan["inert"].get("pE", {}).get("10.70.1.0/24", {}).get("why") == "overlap", plan["inert"].get("pE"))
check("the ninth route is over the cap", plan["inert"].get("pE", {}).get("10.87.0.0/24", {}).get("why") == "cap", plan["inert"].get("pE"))

print("\n[4] the wire — own /32 first, networks sorted after, nothing onto an old node")
R["peers"]["pB"]["routes"] = ["10.60.0.0/24", "10.5.0.0/24"]
d = P.desired_for_node(R, "n1", SNAP)
byk = {x["public_key"]: x["allowed_ips"] for x in d.get("awg0", [])}
check("provider A: its /32 then its network", byk["A" * 43 + "="] == "10.8.0.10/32,192.168.50.0/24", byk)
check("provider B: networks SORTED after the /32 (D9)", byk["B" * 43 + "="] == "10.8.0.11/32,10.5.0.0/24,10.60.0.0/24", byk)
for k, v in byk.items():
    ip = next(t["ip"] for p in R["peers"].values() for t in p["targets"] if p["pubkey"] == k)
    ok = v.split("/")[0] == ip and v.split(",")[0].split("/")[0] == ip
    check("positional readers still read %s's address from %r" % (k[:1], v), ok)
d_old = P.desired_for_node(R, "n1", OLD)
check("an OLD node (no net_deps) gets every peer's bare /32 — no widened ACL",
      all("," not in x["allowed_ips"] for x in d_old.get("awg0", [])), d_old)
check("…and so does a caller with no snapshot at all", all("," not in x["allowed_ips"] for x in P.desired_for_node(R, "n1").get("awg0", [])))

print("\n[5] the save door")
R = roster()
p = R["peers"]["pF"]
clean, ref = P.network_routes_clean(R, p, ["192.168.60.7/24", "192.168.60.0/24", " "], {"n1": SNAP})
check("normalised and de-duplicated", clean == ["192.168.60.0/24"] and ref == [], (clean, ref))
clean, ref = P.network_routes_clean(R, p, ["192.168.1.0/24"], {"n1": SNAP})
check("a NEW prefix on the node's own LAN is refused, naming node, token and address",
      ref == [{"prefix": "192.168.1.0/24", "node": "n1", "iface": "awg0", "why": "node_lan", "addr": "192.168.1.50"}], ref)
p["routes"] = ["192.168.1.0/24"]
clean, ref = P.network_routes_clean(R, p, ["192.168.1.0/24", "192.168.61.0/24"], {"n1": SNAP})
check("…the SAME prefix already stored is kept — the record stays savable", ref == [] and "192.168.1.0/24" in clean, (clean, ref))
p["routes"] = []
clean, ref = P.network_routes_clean(R, p, ["192.168.50.128/25"], {"n1": SNAP})
check("a prefix another provider holds on that node is `taken`, naming it",
      len(ref) == 1 and ref[0]["why"] == "taken" and ref[0]["by"] == "pA", ref)
clean, ref = P.network_routes_clean(R, p, ["10.62.0.0/24"], {"n1": OLD})
check("an old node is NOT a refusal of the prefix — accepted, and the report says why it is inert", ref == [], ref)
clean, ref = P.network_routes_clean(R, p, ["0.0.0.0/0", "fe80::/64", "nope"], {"n1": SNAP})
check("default route, v6 and garbage refused before any node is asked",
      [r["why"] for r in ref] == ["default_route", "not_v4", "invalid"], ref)
clean, ref = P.network_routes_clean(R, p, ["10.%d.0.0/24" % i for i in range(9)], {"n1": SNAP})
check("nine routes: over the cap", any(r["why"] == "cap" for r in ref), ref)
clean, ref = P.network_routes_clean(R, R["peers"]["pD"], ["10.63.0.0/24"], {"n1": SNAP})
check("a peer with only keyless deployments cannot be a provider", any(r["why"] == "self_contained" for r in ref), ref)

print("\n[6] peer_set preserves routes across an unrelated update")
R = roster()
rec = P.peer_set(R, "pA", {"title": "renamed"}, 999)
check("title changed, routes still there", rec.get("title") == "renamed" and rec.get("routes") == ["192.168.50.0/24"], rec)
rec = P.peer_set(R, "pA", {"routes": []}, 999)
check("an explicit empty list clears the key", "routes" not in rec, rec)

print("\n[7] the report")
R = roster()
R["peers"]["pN"] = {"id": "pN", "user_id": "u3", "pubkey": "N" * 43 + "=", "created_at": 5,
                    "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.20", "type": "wg",
                                 "overrides": {"allowed": "10.9.0.0/24"}}]}               # a narrowed client, another iface
R["peers"]["pT"] = {"id": "pT", "user_id": "u1", "pubkey": "T" * 43 + "=", "created_at": 6,
                    "targets": [{"node": "n2", "iface": "awg0", "ip": "10.8.0.30", "type": "awg"}]}   # another node
R["users"]["u3"] = {"name": "Carol"}
rep = P.network_report(R, "pA", {"n1": SNAP})
t0 = rep["targets"][0]
check("one entry per node, with the snippet's facts", (t0["node"], t0["iface"], t0["subnet"], t0["address"])
      == ("n1", "awg0", "10.8.0.0/24", "10.8.0.10"), t0)
check("the network is active", t0["networks"] == [{"prefix": "192.168.50.0/24", "state": "active"}], t0["networks"])
# audience on n1, excluding pA itself and blocked pC: pB pD pE pF pN = 5 peers; users u1 + u3 = 2
check("audience counts the whole NODE — another interface included, the blocked peer and other nodes not",
      t0["audience"] == {"peers": 5, "users": 2}, t0["audience"])
check("the narrowed client on wg1 is named, with what it is missing",
      [(w["peer_id"], w["missing"]) for w in t0["widen"]] == [("pN", ["192.168.50.0/24"])], t0["widen"])
rep = P.network_report(R, "pA", {"n1": dict(SNAP, net_refused={"192.168.50.0/24": {"why": "rolled_back", "addr": "203.0.113.1"}})})
check("a node-side refusal is reported as the node's, with its reason",
      rep["targets"][0]["networks"][0] == {"prefix": "192.168.50.0/24", "state": "refused_by_node",
                                           "why": "rolled_back", "addr": "203.0.113.1"}, rep["targets"][0]["networks"])
rep = P.network_report(R, "pB", {"n1": SNAP})
check("the loser of a collision reads inert/taken by the winner",
      {"prefix": "192.168.50.0/25", "state": "inert", "why": "taken", "addr": "192.168.50.0/24", "by": "pA"}
      in rep["targets"][0]["networks"], rep["targets"][0]["networks"])
rep = P.network_report(R, "pC", {"n1": SNAP})
check("a blocked provider reads `blocked`, not a reason it does not have",
      rep["targets"][0]["networks"][0].get("why") == "blocked", rep["targets"][0]["networks"])
check("a peer with no routes reports nothing", P.network_report(R, "pF", {"n1": SNAP}) == {"targets": []})

# NETWORKS §17 F1 — a blocked gateway says who it cuts off, from the same walk as the audience
tc = P.network_report(R, "pC", {"n1": SNAP})["targets"][0]
_lost = tc.get("lost") or {}
check("a blocked gateway lists who loses its networks — the node's audience, itself excluded",
      _lost.get("peers") == tc["audience"]["peers"] > 0 and _lost.get("total") == _lost.get("peers")
      and {w["peer_id"] for w in _lost.get("list") or []} == {"pA", "pB", "pD", "pE", "pF", "pN"}, tc)
check("an active gateway has no `lost`", "lost" not in t0, t0)

# NETWORKS §17 F5 — the Force DNS note comes only from the node's own dns_redirect, and only for an exempted active prefix
_sr = {"dns_redirect": {"subnets": ["10.8.0.0/24"], "exempt": ["192.168.50.0/24"]}}
tf = P.network_report(R, "pA", {"n1": dict(SNAP, smartroute=_sr)})["targets"][0]
check("a carried network the node exempts carries the Force DNS note, naming the redirected interface",
      tf.get("force_dns") == {"ifaces": ["awg0"], "exempt": ["192.168.50.0/24"]}, tf.get("force_dns"))
check("no note without the node's dns_redirect", "force_dns" not in t0, t0)
_sr2 = {"dns_redirect": {"subnets": ["10.8.0.0/24"], "exempt": ["10.200.0.0/16"]}}
check("no note when the node exempts only other prefixes",
      "force_dns" not in P.network_report(R, "pA", {"n1": dict(SNAP, smartroute=_sr2)})["targets"][0])
_sr3 = {"dns_redirect": {"subnets": ["10.77.0.0/24"], "exempt": ["192.168.50.0/24"]}}
check("an unmapped subnet names itself",
      (P.network_report(R, "pA", {"n1": dict(SNAP, smartroute=_sr3)})["targets"][0].get("force_dns") or {}).get("ifaces")
      == ["10.77.0.0/24"])

# a WDTT / csqtt server is a tunnel too: a network over its pool is refused as a tunnel subnet, not as "the node's LAN"
_ws = dict(SNAP, node_ips=list(SNAP.get("node_ips") or []) + ["10.11.0.1"],
           wdtt=[{"iface": "wdtt1", "wg_addr": "10.11.0.1/24"}], csqtt=[{"iface": "csqtt2", "tun_addr": "10.31.0.1/24"}])
check("a network over a WDTT pool reads as a tunnel subnet, naming the server's address",
      P.network_subnet_refusal("10.11.0.0/24", _ws) == ("iface_subnet", "10.11.0.1"), P.network_subnet_refusal("10.11.0.0/24", _ws))
check("…and over a csqtt pool", P.network_subnet_refusal("10.31.0.0/24", _ws) == ("iface_subnet", "10.31.0.1"),
      P.network_subnet_refusal("10.31.0.0/24", _ws))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
