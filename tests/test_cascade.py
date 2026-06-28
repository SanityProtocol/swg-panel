#!/usr/bin/env python3
"""Standalone tests for the Phase-2 traffic cascade — no nodes, no pytest, stdlib only.

Covers the three layers:
  - panel  : cascade_plan() + forward-aware desired_mesh_for_node()
  - node   : reconcile_cascade() rule generation (fake `run`), reconcile() AllowedIPs drift
  - agent  : ensure_table_off_in_conf() / rewrite_peer_allowed_in_conf() against temp confs

Run: `python3 tests/test_cascade.py` (exit 0 = pass)."""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, fname):
    path = os.path.join(ROOT, fname)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# ───────────────────────── fixtures ─────────────────────────
def _link(self_addr, peer_addr, iface):
    return {"iface": iface, "link_id": "L", "subnet": "10.99.0.0/31", "address": self_addr,
            "peer_address": peer_addr, "listen_port": 52000, "psk": "k", "role": "x"}


def two_node_fleet():
    """N(=msk) forwards user iface awg1 (10.8.0.0/24) → P(=ams), egress_ip 5.5.5.5."""
    N, P = "nnnn1111", "pppp2222"
    nodes = {
        N: {"id": N, "name": "msk", "endpoint_host": "1.1.1.1",
            "links": {P: _link("10.99.0.0", "10.99.0.1", "swg_AB")},
            "ifaces": {"awg1": {"egress_mode": "forward", "egress_node": P, "egress_ip": "5.5.5.5"},
                       "swg_AB": {"system": True, "link_node": P, "public_key": "PUBn"}}},
        P: {"id": P, "name": "ams", "endpoint_host": "2.2.2.2",
            "links": {N: _link("10.99.0.1", "10.99.0.0", "swg_AB")},
            "ifaces": {"swg_AB": {"system": True, "link_node": N, "public_key": "PUBp"}}},
    }
    snaps = {N: {"interfaces": {"awg1": {"meta": {"subnet": "10.8.0.0/24", "address": "10.8.0.1/24"}}}}}
    return nodes, snaps, N, P


# ───────────────────────── panel ─────────────────────────
def test_panel():
    m = _load("swg_panel_server", "swg-panel-server")
    nodes, snaps, N, P = two_node_fleet()
    plans = m.cascade_plan(nodes, snaps)

    assert plans[N]["forward"] == [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000}], plans[N]
    assert plans[N]["allowed"] == {"swg_AB": "0.0.0.0/0"}, plans[N]
    assert plans[N]["exit"] == [], plans[N]
    assert plans[P]["exit"] == [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000,
                                 "egress_ip": "5.5.5.5", "wan_iface": ""}], plans[P]
    assert plans[P]["allowed"] == {"swg_AB": "10.8.0.0/24,10.99.0.0/32"}, plans[P]

    # forward-aware desired_mesh_for_node applies the override
    mesh_n = m.desired_mesh_for_node(nodes, N, 25, plans[N]["allowed"])
    assert mesh_n["swg_AB"][0]["allowed_ips"] == "0.0.0.0/0", mesh_n
    mesh_p = m.desired_mesh_for_node(nodes, P, 25, plans[P]["allowed"])
    assert mesh_p["swg_AB"][0]["allowed_ips"] == "10.8.0.0/24,10.99.0.0/32", mesh_p
    # no override → default link /32 (Phase-1 behavior preserved)
    assert m.desired_mesh_for_node(nodes, N, 25)["swg_AB"][0]["allowed_ips"] == "10.99.0.1/32"

    # safe-skip: subnet not reported, or direct mode → empty plan (engine inert)
    assert m.cascade_plan(nodes, {}) == {}
    nodes[N]["ifaces"]["awg1"]["egress_mode"] = "direct"
    assert m.cascade_plan(nodes, snaps) == {}
    nodes[N]["ifaces"]["awg1"]["egress_mode"] = "forward"

    # deterministic table ids across multiple targets (a third node C)
    C = "cccc3333"
    nodes[C] = {"id": C, "name": "sgp", "endpoint_host": "3.3.3.3",
                "links": {N: _link("10.99.0.3", "10.99.0.2", "swg_AC")},
                "ifaces": {"swg_AC": {"system": True, "link_node": N, "public_key": "PUBc"}}}
    nodes[N]["links"][C] = _link("10.99.0.2", "10.99.0.3", "swg_AC")
    nodes[N]["ifaces"]["awg2"] = {"egress_mode": "forward", "egress_node": C, "egress_ip": "9.9.9.9"}
    snaps[N]["interfaces"]["awg2"] = {"meta": {"subnet": "10.9.0.0/24"}}
    plans = m.cascade_plan(nodes, snaps)
    tabs = {f["via_iface"]: f["table"] for f in plans[N]["forward"]}
    # table ids are sorted by TARGET NODE ID (deterministic): cccc3333 < pppp2222 → swg_AC=7000, swg_AB=7001
    assert tabs == {"swg_AC": 7000, "swg_AB": 7001}, tabs
    # determinism: recompute → identical
    assert {f["via_iface"]: f["table"] for f in m.cascade_plan(nodes, snaps)[N]["forward"]} == tabs

    print("OK panel: cascade_plan + forward-aware mesh")


# ───────────────────────── node ─────────────────────────
class _R:
    def __init__(self, rc=0, out=""):
        self.returncode = rc; self.stdout = out; self.stderr = ""


def test_node_cascade():
    m = _load("swg_noded", "swg-noded")
    calls = []
    LIVE = {"iprule": "", "natP": "", "fwd": "", "mangle": "", "routes": {}}

    def fake_run(args, **kw):
        calls.append(list(args))
        if args[:3] == ["ip", "rule", "show"]:
            return _R(0, LIVE["iprule"])
        if args[:3] == ["ip", "route", "show"]:
            return _R(0, LIVE["routes"].get(args[args.index("table") + 1], ""))
        if args[:1] == ["iptables"] and "-S" in args:
            if "POSTROUTING" in args:
                return _R(0, LIVE["natP"])
            if "mangle" in args:
                return _R(0, LIVE["mangle"])
            return _R(0, LIVE["fwd"])
        return _R(0)

    m.run = fake_run
    m._detect_wan = lambda: "eth0"
    argv = lambda: [" ".join(c) for c in calls]

    # ENTRY rule generation
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000}], "exit": []})
    a = argv()
    assert "ip route replace default dev swg_AB table 7000" in a, a
    assert "ip rule add from 10.8.0.0/24 lookup 7000 priority 7000" in a, a
    assert "sysctl -q -w net.ipv4.ip_forward=1" in a
    assert "sysctl -q -w net.ipv4.conf.all.rp_filter=2" in a, a
    assert "sysctl -q -w net.ipv4.conf.swg_AB.rp_filter=2" in a
    assert any("swg-fwd-acl:swg_AB" in x and "-i swg_AB" in x for x in a), a
    assert any("swg-fwd-mss:swg_AB" in x and "TCPMSS" in x for x in a), a

    # EXIT rule generation
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000, "egress_ip": "5.5.5.5", "wan_iface": "eth0"}]})
    a = argv()
    assert "ip route replace 10.8.0.0/24 dev swg_AB table 7000" in a, a
    assert "ip rule add to 10.8.0.0/24 lookup 7000 priority 7000" in a, a
    assert any("swg-fwd-snat:10.8.0.0/24" in x and "SNAT" in x and "5.5.5.5" in x for x in a), a

    # IDEMPOTENT: live state already matches the entry plan → NO rule churn (the packet-leak guard)
    LIVE["iprule"] = "0:\tfrom all lookup local\n7000:\tfrom 10.8.0.0/24 lookup 7000\n32766:\tfrom all lookup main\n"
    LIVE["routes"] = {"7000": "default dev swg_AB scope link\n"}
    LIVE["natP"] = "-P POSTROUTING ACCEPT\n"
    LIVE["fwd"] = ("-A FORWARD -i swg_AB -m comment --comment swg-fwd-acl:swg_AB -j ACCEPT\n"
                   "-A FORWARD -o swg_AB -m comment --comment swg-fwd-acl:swg_AB -j ACCEPT\n")
    LIVE["mangle"] = "-A FORWARD -o swg_AB -p tcp -m tcp --tcp-flags SYN,RST SYN -m comment --comment swg-fwd-mss:swg_AB -j TCPMSS --clamp-mss-to-pmtu\n"
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000}], "exit": []})
    mutated = [x for x in argv() if any(k in x for k in ("ip rule add", "ip rule del", "ip route replace", "ip route flush"))]
    assert mutated == [], mutated

    # TEARDOWN: empty plan but a leftover band rule + stale SNAT → cleaned up
    LIVE["iprule"] = "7000:\tfrom 10.8.0.0/24 lookup 7000\n"
    LIVE["routes"] = {"7000": "default dev swg_AB scope link\n"}
    LIVE["natP"] = "-A POSTROUTING -s 10.8.0.0/24 -o eth0 -m comment --comment swg-fwd-snat:10.8.0.0/24 -j SNAT --to-source 5.5.5.5\n"
    LIVE["fwd"] = ""; LIVE["mangle"] = ""
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []})
    a = argv()
    assert any("ip rule del pref 7000" in x for x in a), a
    assert any("ip route flush table 7000" in x for x in a), a
    assert any("swg-fwd-snat" in x and "-D POSTROUTING" in x for x in a), a

    print("OK node: reconcile_cascade (entry/exit/idempotent/teardown)")


def test_node_allowed_drift():
    m = _load("swg_noded2", "swg-noded")
    agent_calls = []
    m.run_agent = lambda a, s, p: (agent_calls.append(p) or {"ok": True})
    m.current_pubkeys = lambda nc, i: {"PUBmesh"}
    node_cfg = {"interfaces": {"swg_AB": {"cmd": ["awg"], "conf": "/x"}}}

    # /32 live, /0 desired → one set-peer-allowed
    m.current_allowed = lambda nc, i: {"PUBmesh": m._norm_allowed("10.99.0.1/32")}
    desired = {"swg_AB": [{"public_key": "PUBmesh", "allowed_ips": "0.0.0.0/0"}]}
    m.reconcile(node_cfg, desired, "agent", False)
    assert any(c.get("op") == "set-peer-allowed" and c["allowed_ips"] == "0.0.0.0/0" for c in agent_calls), agent_calls

    # in-sync (same set, reordered) → no call
    agent_calls.clear()
    m.current_allowed = lambda nc, i: {"PUBmesh": m._norm_allowed("0.0.0.0/0")}
    m.reconcile(node_cfg, desired, "agent", False)
    assert agent_calls == [], agent_calls

    # exit gains a subnet (reorder-insensitive)
    agent_calls.clear()
    m.current_allowed = lambda nc, i: {"PUBmesh": m._norm_allowed("10.99.0.0/32")}
    d2 = {"swg_AB": [{"public_key": "PUBmesh", "allowed_ips": "10.8.0.0/24,10.99.0.0/32"}]}
    m.reconcile(node_cfg, d2, "agent", False)
    assert any(c.get("op") == "set-peer-allowed" for c in agent_calls), agent_calls
    agent_calls.clear()
    m.current_allowed = lambda nc, i: {"PUBmesh": m._norm_allowed("10.99.0.0/32,10.8.0.0/24")}
    m.reconcile(node_cfg, d2, "agent", False)
    assert agent_calls == [], agent_calls

    print("OK node: reconcile() AllowedIPs drift re-apply")


# ───────────────────────── agent ─────────────────────────
def test_agent_conf():
    m = _load("swg_agent", "swg-agent")
    d = tempfile.mkdtemp()
    conf = os.path.join(d, "swg_AB.conf")
    pub = "P" * 43 + "="
    with open(conf, "w") as f:
        f.write("[Interface]\nPrivateKey = aaa\nAddress = 10.99.0.0/31\nListenPort = 52000\nMTU = 1320\n"
                "PostUp = true\nPostDown = true\n\n# name: mesh:ams\n[Peer]\nPublicKey = " + pub + "\n"
                "PresharedKey = " + ("k" * 43) + "=\nAllowedIPs = 10.99.0.1/32\nEndpoint = 2.2.2.2:52000\nPersistentKeepalive = 25\n")

    m.ensure_table_off_in_conf(conf)
    assert "Table = off" in open(conf).read()
    m.ensure_table_off_in_conf(conf)                       # idempotent
    assert open(conf).read().count("Table = off") == 1

    m.rewrite_peer_allowed_in_conf(conf, pub, "0.0.0.0/0")
    t = open(conf).read()
    assert "AllowedIPs = 0.0.0.0/0" in t and "10.99.0.1/32" not in t, t
    assert "Endpoint = 2.2.2.2:52000" in t and "PersistentKeepalive = 25" in t and "PresharedKey" in t

    m.rewrite_peer_allowed_in_conf(conf, pub, "10.8.0.0/24,10.99.0.0/32")
    assert "AllowedIPs = 10.8.0.0/24,10.99.0.0/32" in open(conf).read()

    # set-peer-allowed + create-iface Table=off are registered/wired
    assert "set-peer-allowed" in m.WRITE_OPS
    print("OK agent: Table=off self-heal + peer-allowed rewrite")


def main():
    test_panel()
    test_node_cascade()
    test_node_allowed_drift()
    test_agent_conf()
    print("OK test_cascade: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
