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


def test_panel_smart():
    """Phase 3: smart per-destination routing compiles into cascade_plan's smart entries + reused exits."""
    m = _load("swg_panel_smart", "swg-panel-server")
    A, B, C = "aaaa", "bbbb", "cccc"

    def link(self_a, peer_a, i):
        return {"iface": i, "subnet": "x", "address": self_a, "peer_address": peer_a, "listen_port": 1, "psk": "k", "role": "x"}
    nodes = {
        A: {"id": A, "name": "msk", "endpoint_host": "a",
            "links": {B: link("10.99.0.0", "10.99.0.1", "swg_AB"), C: link("10.99.0.2", "10.99.0.3", "swg_AC")},
            "ifaces": {"awg1": {"egress_mode": "smart", "routing": [
                {"category": "google", "action": "exit", "node": B},
                {"category": "vk", "action": "exit", "node": C},
                {"category": "ru", "action": "direct"}]},
                       "swg_AB": {"system": True, "link_node": B}, "swg_AC": {"system": True, "link_node": C}}},
        B: {"id": B, "name": "ams", "endpoint_host": "b", "links": {A: link("10.99.0.1", "10.99.0.0", "swg_AB")}, "ifaces": {"swg_AB": {"system": True}}},
        C: {"id": C, "name": "sgp", "endpoint_host": "c", "links": {A: link("10.99.0.3", "10.99.0.2", "swg_AC")}, "ifaces": {"swg_AC": {"system": True}}},
    }
    snaps = {A: {"interfaces": {"awg1": {"meta": {"subnet": "10.8.0.0/24"}}}}}
    plans = m.cascade_plan(nodes, snaps)
    sm = {(e["category"], e["via_iface"], e["table"]) for e in plans[A]["smart"]}
    assert ("google", "swg_AB", 7000) in sm and ("vk", "swg_AC", 7001) in sm, sm
    assert plans[A]["forward"] == [] and plans[A]["allowed"] == {"swg_AB": "0.0.0.0/0", "swg_AC": "0.0.0.0/0"}
    assert plans[B]["exit"] == [{"subnet": "10.8.0.0/24", "via_iface": "swg_AB", "table": 7000, "egress_ip": "", "wan_iface": ""}], plans[B]["exit"]
    assert plans[C]["exit"][0]["table"] == 7001
    # validation + safe-skips
    assert m._validate_routing([{"category": "nope", "action": "exit", "node": B}], nodes, A)[1]
    assert m._validate_routing([{"category": "google", "action": "exit", "node": A}], nodes, A)[1]   # exit-to-self
    nodes[A]["ifaces"]["awg1"]["routing"] = [{"category": "google", "action": "exit", "node": B, "enabled": False}, {"category": "vk", "action": "direct"}]
    assert m.cascade_plan(nodes, snaps).get(A, {}).get("smart", []) == []   # disabled + direct → no entry
    # "All traffic" catch-all is a valid category and compiles to a smart entry like any other exit rule
    assert m._validate_routing([{"category": "all", "action": "exit", "node": B}], nodes, A)[1] is None
    nodes[A]["ifaces"]["awg1"]["routing"] = [{"category": "google", "action": "exit", "node": B}, {"category": "all", "action": "exit", "node": C}]
    sm2 = {(e["category"], e["table"]) for e in m.cascade_plan(nodes, snaps)[A]["smart"]}
    assert ("google", 7000) in sm2 and ("all", 7001) in sm2, sm2
    # custom rule: mixed IPs + domains (a raw string), normalized + split into domains/cidrs (lowercase, scheme/
    # path strip, bad-octet drop, /32 fill, dedupe), compiled to a synthetic custom_<hash> set; both halves
    # shipped — domains→dnsmasq, cidrs→direct nft load.
    cv, ce = m._validate_routing([{"category": "custom", "action": "exit", "node": B,
                                   "targets": "YouTube.com, https://twitch.tv/x, 1.2.3.0/24, 8.8.8.8, bad"}], nodes, A)
    assert ce is None and cv[0]["domains"] == ["youtube.com", "twitch.tv"] and cv[0]["cidrs"] == ["1.2.3.0/24", "8.8.8.8/32"], cv
    assert m._validate_routing([{"category": "custom", "action": "exit", "node": B, "targets": "???"}], nodes, A)[1]
    cid = m.custom_cat_id(["twitch.tv", "youtube.com"], ["1.2.3.0/24", "8.8.8.8/32"])
    nodes[A]["ifaces"]["awg1"]["routing"] = [{"category": "custom", "action": "exit", "node": B, "targets": "youtube.com, twitch.tv, 1.2.3.0/24, 8.8.8.8"}]
    cp = m.cascade_plan(nodes, snaps)[A]
    assert any(e["category"] == cid for e in cp["smart"]), cp["smart"]
    assert cp["domains"].get(cid) == ["youtube.com", "twitch.tv"] and cp["cidrs"].get(cid) == ["1.2.3.0/24", "8.8.8.8/32"], (cp["domains"], cp["cidrs"])
    print("OK panel: smart routing plan + validation (incl. All-traffic catch-all + custom IPs/domains)")


def test_node_smart():
    """Phase 3: reconcile_cascade with a smart plan → nft set/chain/mark + ip rule fwmark; idempotent."""
    m = _load("swg_noded_smart", "swg-noded")
    calls = []

    def R(rc=0, out=""):
        class _R:
            pass
        r = _R(); r.returncode = rc; r.stdout = out; r.stderr = ""; return r
    LIVE = {"nft_rc": 1, "iprule": "", "natP": "", "fwd": "", "mangle": "", "routes": {}, "nft_out": ""}

    def fake(args, **k):
        calls.append([str(x) for x in args])
        if args[:3] == ["ip", "rule", "show"]:
            return R(0, LIVE["iprule"])
        if args[:3] == ["ip", "route", "show"]:
            return R(0, LIVE["routes"].get(args[args.index("table") + 1], ""))
        if args[:1] == ["iptables"] and "-S" in args:
            return R(0, LIVE["natP"] if "POSTROUTING" in args else (LIVE["mangle"] if "mangle" in args else LIVE["fwd"]))
        if args[:1] == ["nft"]:
            return R(LIVE["nft_rc"], LIVE["nft_out"]) if args[1:3] == ["list", "table"] else R(0)
        return R(0)
    m.run = fake; m._detect_wan = lambda: "eth0"
    m._smart_geo_refresh = lambda *a, **k: None   # isolate from the geo fetch (covered by test_node_geo)
    smart = {"entries": [{"subnet": "10.8.0.0/24", "category": "google", "via_iface": "swg_AB", "table": 7000}], "categories": ["google"]}
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []}, smart)
    a = [" ".join(c) for c in calls]
    assert "ip route replace default dev swg_AB table 7000" in a
    assert "ip rule add fwmark 7000 lookup 7000 priority 7000" in a, a
    assert any("add set inet swg_smart cat_google" in x for x in a)
    assert any("add chain inet swg_smart prerouting" in x for x in a)
    assert any("add rule inet swg_smart prerouting ip saddr 10.8.0.0/24 ip daddr @cat_google meta mark set 7000" in x for x in a), a
    # fwmark in the 7000-band, never WG's 0xca6c (51820)
    assert not any("51820" in x or "0xca6c" in x for x in a)
    # "All traffic" catch-all: no set, guarded mark 0x0 rule emitted AFTER the category rule
    LIVE["nft_rc"] = 1
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []}, {"categories": ["google", "all"], "entries": [
        {"subnet": "10.8.0.0/24", "category": "google", "via_iface": "swg_AB", "table": 7000},
        {"subnet": "10.8.0.0/24", "category": "all", "via_iface": "swg_AC", "table": 7001}]})
    a2 = [" ".join(c) for c in calls]
    assert not any("cat_all" in x for x in a2), "no geo set for 'all'"
    gi = next(i for i, x in enumerate(a2) if "ip daddr @cat_google meta mark set 7000" in x)
    ai = next(i for i, x in enumerate(a2) if "ip saddr 10.8.0.0/24 meta mark 0x0 meta mark set 7001" in x)
    assert gi < ai, "catch-all must be emitted after the category rule"
    LIVE["nft_rc"] = 0
    # idempotent: live state matches → no nft flush / no ip rule churn
    LIVE.update(nft_rc=0, natP="-P POSTROUTING ACCEPT\n",
                iprule="7000:\tfrom all fwmark 0x1b58 lookup 7000\n",
                routes={"7000": "default dev swg_AB scope link\n"},
                fwd="-A FORWARD -i swg_AB -m comment --comment swg-fwd-acl:swg_AB -j ACCEPT\n-A FORWARD -o swg_AB -m comment --comment swg-fwd-acl:swg_AB -j ACCEPT\n",
                mangle="-A FORWARD -o swg_AB -p tcp -m comment --comment swg-fwd-mss:swg_AB -j TCPMSS --clamp-mss-to-pmtu\n",
                nft_out=("table inet swg_smart {\n\tset cat_google { type ipv4_addr\n\tflags interval\n\t}\n"
                         "\tchain prerouting {\n\t\ttype filter hook prerouting priority mangle; policy accept;\n"
                         "\t\tip saddr 10.8.0.0/24 ip daddr @cat_google meta mark set 0x00001b58\n\t}\n}\n"))
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []}, smart)
    churn = [" ".join(c) for c in calls if any(k in " ".join(c) for k in ("ip rule add", "ip rule del", "ip route replace", "nft flush", "nft add rule"))]
    assert churn == [], churn
    print("OK node: smart reconcile (nft mark + fwmark route) + idempotent")


def test_node_geo():
    """Phase 3 geo: a fetched category list loads into its nft set; reload only on data change or empty set."""
    import tempfile, os as _os
    m = _load("swg_noded_geo", "swg-noded")
    m.GEO_DIR = tempfile.mkdtemp()
    m._geo_fetch = lambda cat: ["149.154.160.0/20", "91.108.4.0/22"] if cat == "telegram" else None
    calls = []

    def R(rc=0):
        class _R:
            pass
        r = _R(); r.returncode = rc; r.stdout = ""; r.stderr = ""; return r

    def fake(args, **k):
        c = [str(x) for x in args]
        if c[:2] == ["nft", "-f"]:
            c = ["nft", "-f", open(args[2]).read()]            # capture the generated file body
        calls.append(c); return R(0)
    m.run = fake
    res = {"changed": 0, "errors": []}
    m._smart_geo_refresh(["telegram"], {"cat_telegram": 0}, res)        # set empty → load
    body = next((c[2] for c in calls if c[:2] == ["nft", "-f"]), "")
    assert "flush set inet swg_smart cat_telegram" in body and "149.154.160.0/20" in body, body
    assert res["changed"] == 1
    calls.clear()
    m._smart_geo_refresh(["telegram"], {"cat_telegram": 2}, res)        # unchanged + populated → no reload
    assert not [c for c in calls if c[:2] == ["nft", "-f"]]
    m._geo_fetch = lambda cat: ["1.2.3.0/24"]                           # data changes → reload
    _os.utime(_os.path.join(m.GEO_DIR, "telegram.txt"), (0, 0))         # age cache + attempt marker so it refetches
    _os.utime(_os.path.join(m.GEO_DIR, ".telegram.attempt"), (0, 0))
    calls.clear()
    m._smart_geo_refresh(["telegram"], {"cat_telegram": 2}, res)
    assert [c for c in calls if c[:2] == ["nft", "-f"]], "changed data should reload the set"
    # demotion: a category now in `skip` (moved to the domain tier) with a stale geoip cache → flushed once
    open(_os.path.join(m.GEO_DIR, ".telegram.loaded"), "w").write("x")
    calls.clear()
    m._smart_geo_refresh(["telegram"], {"cat_telegram": 9}, res, skip={"telegram"})
    assert any(c[:3] == ["nft", "flush", "set"] and "cat_telegram" in c for c in calls), calls
    assert not _os.path.exists(_os.path.join(m.GEO_DIR, ".telegram.loaded")), "loaded marker dropped after demotion"
    print("OK node: geo fetch→set load + change/empty reload-gating + domain-tier demotion")


def test_node_domain_dns():
    """Phase 3 domain tier: a smart plan carrying domain bundles → a dnsmasq conf with nftset directives, the
    dnsmasq (re)started, and smart-subnet DNS DNAT-redirected to it; an empty plan tears both down."""
    import tempfile, os as _os
    m = _load("swg_noded_dns", "swg-noded")
    d = tempfile.mkdtemp()
    m.DNSMASQ_CONF = _os.path.join(d, "dns.conf")
    m.DNSMASQ_PID = _os.path.join(d, "dns.pid")
    m._smart_geo_refresh = lambda *a, **k: None
    calls = []

    def R(rc=0, out=""):
        class _R:
            pass
        r = _R(); r.returncode = rc; r.stdout = out; r.stderr = ""; return r
    NAT = {"out": ""}

    def fake(args, **k):
        c = [str(x) for x in args]; calls.append(c)
        if c[:1] == ["nft"]:
            return R(1) if c[1:3] == ["list", "table"] else R(0)
        if c[:1] == ["iptables"] and "-S" in c:
            return R(0, NAT["out"])
        return R(0)
    m.run = fake; m._detect_wan = lambda: "eth0"
    smart = {"entries": [{"subnet": "10.8.0.0/24", "category": "google", "via_iface": "swg_AB", "table": 7000}],
             "categories": ["google"], "domains": {"google": ["google.com", "gstatic.com"]}}
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []}, smart)
    conf = open(m.DNSMASQ_CONF).read()
    assert "nftset=/google.com/gstatic.com/4#inet#swg_smart#cat_google" in conf, conf
    assert "port=5354" in conf and "listen-address=127.0.0.1" in conf
    a = [" ".join(c) for c in calls]
    assert any("dnsmasq --conf-file=" in x for x in a), a
    assert any("iptables -t nat -A PREROUTING -s 10.8.0.0/24 -p udp --dport 53" in x and "DNAT" in x for x in a), a
    assert any("net.ipv4.conf.all.route_localnet=1" in x for x in a)
    # teardown: empty plan → DNS redirect removed + conf gone (simulate the live redirect so removal runs)
    NAT["out"] = ("-A PREROUTING -s 10.8.0.0/24 -p udp -m comment --comment swg-smartdns --dport 53 -j DNAT --to-destination 127.0.0.1:5354\n"
                  "-A PREROUTING -s 10.8.0.0/24 -p tcp -m comment --comment swg-smartdns --dport 53 -j DNAT --to-destination 127.0.0.1:5354\n")
    calls.clear()
    m.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": []}, {"entries": [], "categories": []})
    a2 = [" ".join(c) for c in calls]
    assert any("iptables -t nat -D PREROUTING -s 10.8.0.0/24 -p udp" in x for x in a2), a2
    assert not _os.path.exists(m.DNSMASQ_CONF), "conf removed on teardown"
    print("OK node: domain-tier dnsmasq conf + DNS redirect + teardown")


def test_node_dial_src():
    """Part 3: a per-link dial_src installs a /32 source route to the peer endpoint; clearing it removes it."""
    import tempfile
    m = _load("swg_noded_dial", "swg-noded")
    m.STATE_DIR = tempfile.mkdtemp()
    calls = []

    def R(rc=0, out=""):
        class _R:
            pass
        r = _R(); r.returncode = rc; r.stdout = out; r.stderr = ""; return r

    def fake(a, **k):
        calls.append([str(x) for x in a])
        if a[:3] == ["ip", "route", "get"]:
            return R(0, "203.0.113.50 via 203.0.113.1 dev eth0 src 203.0.113.11 \n")
        return R(0)
    m.run = fake
    res = {"changed": 0, "errors": []}
    m.reconcile_dial_src({"swg_AB": [{"endpoint": "203.0.113.50:51820", "dial_src": "203.0.113.12"}]}, res)
    a = [" ".join(c) for c in calls]
    assert any("ip route replace 203.0.113.50/32 via 203.0.113.1 dev eth0 src 203.0.113.12" in x for x in a), a
    calls.clear()
    m.reconcile_dial_src({"swg_AB": [{"endpoint": "203.0.113.50:51820", "dial_src": ""}]}, res)   # cleared → drop /32
    assert any("ip route del 203.0.113.50/32" in " ".join(c) for c in calls), calls
    print("OK node: dial-src /32 source route install + remove")


def test_node_endpoint_redial():
    """A peer's endpoint (ingress IP) change re-dials existing links; unchanged → no churn."""
    import tempfile
    m = _load("swg_noded_redial", "swg-noded")
    m.STATE_DIR = tempfile.mkdtemp()
    ops = []
    m.run_agent = lambda agent, sudo, req: (ops.append(req) or {"ok": True})
    m.current_pubkeys = lambda nc, i: {"PK"}                      # peer already present
    m.current_allowed = lambda nc, i: {"PK": "10.255.0.1/32"}
    nc = {"interfaces": {"swg_AB": {"cmd": ["awg"]}}}
    des = {"swg_AB": [{"public_key": "PK", "allowed_ips": "10.255.0.1/32", "endpoint": "1.1.1.1:9999", "persistent_keepalive": 25}]}
    m.reconcile(nc, des, "agent", False)                         # first run re-asserts + records the endpoint
    assert [o for o in ops if o["op"] == "add-peer" and o.get("endpoint") == "1.1.1.1:9999"], ops
    ops.clear(); m.reconcile(nc, des, "agent", False)            # unchanged → no re-dial
    assert not [o for o in ops if o["op"] == "add-peer"], ops
    ops.clear(); des["swg_AB"][0]["endpoint"] = "2.2.2.2:9999"   # ingress changed → re-dial
    m.reconcile(nc, des, "agent", False)
    assert [o for o in ops if o.get("endpoint") == "2.2.2.2:9999"], ops
    print("OK node: existing peer re-dials on endpoint change (churn-safe)")


def main():
    test_panel()
    test_panel_smart()
    test_node_cascade()
    test_node_smart()
    test_node_geo()
    test_node_domain_dns()
    test_node_dial_src()
    test_node_endpoint_redial()
    test_node_allowed_drift()
    test_agent_conf()
    print("OK test_cascade: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
