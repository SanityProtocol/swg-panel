#!/usr/bin/env python3
"""Self-test: deploying a device never takes a network away from the device that carries it (qualification 1.8.7 §N12).

The networks door refuses a NEW prefix that overlaps one a node carries. But a device whose networks were saved while it was
deployed somewhere else brings them along when `/api/peers/add-target` puts it on another node, and `node_networks` resolves an
overlap by age, then id — so an older (or same-second, smaller-id) device TOOK the live network over, audience and all. Measured
on swgt: anna's owner-only office network became boris's open one at the same address, and everyone on the node reached it.

  [1] the takeover is refused, with the prefix, the node, `takes` and the device that carries it — and nothing is written
  [2] a device that would LOSE the overlap is deployed (it stays inert with `taken`, which the sheet already shows)
  [3] a device with no networks, and a second interface on a node it is already on, are never refused
  [4] a device whose networks do not overlap anything on the new node is deployed

Run: python3 tests/network_takeover_selftest.py (0 = pass)
     --perturb   removes the refusal and expects RED on [1].
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB = "--perturb" in sys.argv

src = open(PANEL, encoding="utf-8").read()
if PERTURB:
    cut = "            if _took:\n                return 409,"
    assert src.count(cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    src = src.replace(cut, "            if False:\n                return 409,", 1)
path = os.path.join(tempfile.mkdtemp(), "swg-panel-server")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

K = lambda c: (c * 43)[:43] + "="
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {"wgn1": {"meta": {"subnet": "10.141.0.0/24"}}, "wgn2": {"meta": {"subnet": "10.142.0.0/24"}}},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1, "carried": 1}}


def roster():
    return {"version": P.ROSTER_VERSION, "users": {"anna": {"name": "Anna"}, "boris": {"name": "Boris"}},
            "peers": {
                # anna's office router: carried on n1, owner-only
                "g1": {"id": "g1", "user_id": "anna", "pubkey": K("A"), "created_at": 200, "routes": ["192.168.141.0/24"],
                       "share": {"users": {}}, "targets": [{"node": "n1", "iface": "wgn1", "ip": "10.141.0.5", "type": "wg"}]},
                # boris's router with the SAME prefix, saved while it lived on n2 — OLDER than g1, so it would win on n1
                "g2": {"id": "g2", "user_id": "boris", "pubkey": K("B"), "created_at": 100, "routes": ["192.168.141.0/24"],
                       "targets": [{"node": "n2", "iface": "wgs1", "ip": "10.145.0.6", "type": "wg"}]},
                # a YOUNGER device with the same prefix — it would lose on n1
                "g3": {"id": "g3", "user_id": "boris", "pubkey": K("C"), "created_at": 300, "routes": ["192.168.141.128/25"],
                       "targets": [{"node": "n2", "iface": "wgs1", "ip": "10.145.0.7", "type": "wg"}]},
                # an older device with a network nothing on n1 overlaps
                "g4": {"id": "g4", "user_id": "boris", "pubkey": K("D"), "created_at": 50, "routes": ["192.168.77.0/24"],
                       "targets": [{"node": "n2", "iface": "wgs1", "ip": "10.145.0.8", "type": "wg"}]},
                # an older device with no networks
                "b1": {"id": "b1", "user_id": "boris", "pubkey": K("E"), "created_at": 10,
                       "targets": [{"node": "n2", "iface": "wgs1", "ip": "10.145.0.9", "type": "wg"}]},
            }}


D = tempfile.mkdtemp(prefix="takeover-")
nodes_path, roster_path = os.path.join(D, "nodes.json"), os.path.join(D, "users.json")
NODES = {"n1": {"id": "n1", "name": "msk", "ifaces": {"wgn1": {}, "wgn2": {}}},
         "n2": {"id": "n2", "name": "svo", "ifaces": {"wgs1": {}}}}
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {"n1": SNAP, "n2": SNAP}, "stats_dir": D, "fleet": {},
        "panel_settings": json.loads(json.dumps(P.PANEL_SETTINGS_DEFAULTS))}


def reset():
    json.dump(NODES, open(nodes_path, "w"))
    json.dump(roster(), open(roster_path, "w"))


def door(body):
    try:
        return P.api("POST", "/api/peers/add-target", {}, body, deps)
    except Exception as e:
        return 599, {"exception": repr(e)}


def targets(pid):
    return [(t["node"], t["iface"]) for t in json.load(open(roster_path))["peers"][pid]["targets"]]


print("[1] a deployment that would take a live network over is refused")
reset()
before = P.node_networks(roster(), "n1", SNAP)["carry"]
check("fixture: g1 carries the office network on n1", before.get("g1", {}).get("nets") == ["192.168.141.0/24"], before)
c, b = door({"peer_id": "g2", "target": {"node": "n1", "iface": "wgn2", "ip": "10.142.0.6"}})
check("⚠️ refused, as network_refused", c == 409 and b.get("code") == "network_refused", (c, b))
check("…naming the prefix, the node, `takes` and the device carrying it",
      (b.get("refusals") or []) == [{"prefix": "192.168.141.0/24", "node": "n1", "why": "takes", "by": "g1"}], b.get("refusals"))
check("…with a sentence for clients that do not read tokens", "take it over" in str(b.get("error", "")), b.get("error"))
check("…and nothing written: g2 is still only on n2", targets("g2") == [("n2", "wgs1")], targets("g2"))

print("\n[2] a device that would LOSE the overlap is deployed — inert there, visibly")
reset()
c, b = door({"peer_id": "g3", "target": {"node": "n1", "iface": "wgn2", "ip": "10.142.0.7"}})
check("deployed", c == 200 and ("n1", "wgn2") in targets("g3"), (c, b))
after = P.node_networks(json.load(open(roster_path)), "n1", SNAP)
check("…g1 still carries the office network", after["carry"].get("g1", {}).get("nets") == ["192.168.141.0/24"], after["carry"])
check("…and g3's is inert with `taken` by g1", (after["inert"].get("g3") or {}).get("192.168.141.128/25", {}).get("by") == "g1", after["inert"])

print("\n[3] nothing else is refused")
reset()
c, b = door({"peer_id": "b1", "target": {"node": "n1", "iface": "wgn2", "ip": "10.142.0.9"}})
check("a device with no networks", c == 200, (c, b))
reset()
c, b = door({"peer_id": "g1", "target": {"node": "n1", "iface": "wgn2", "ip": "10.142.0.5"}})
check("a second interface on a node the device already carries its network on", c == 200, (c, b))

print("\n[4] a network nothing on the new node overlaps")
reset()
c, b = door({"peer_id": "g4", "target": {"node": "n1", "iface": "wgn2", "ip": "10.142.0.8"}})
check("deployed, and the new node carries both networks",
      c == 200 and sorted(n for e in P.node_networks(json.load(open(roster_path)), "n1", SNAP)["carry"].values() for n in e["nets"])
      == ["192.168.141.0/24", "192.168.77.0/24"], (c, b))

print()
if PERTURB:
    print("--perturb: %d check(s) RED" % len(FAILS))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
