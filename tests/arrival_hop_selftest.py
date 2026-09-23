#!/usr/bin/env python3
"""Self-test for the ONWARD HOP — a "Forward to node Q" rule in node P's default list, applied to the traffic other nodes
cascade out through P (docs/ROUTING-PEERS-MESH-PLAN.md §3.5, §8 P3b, §12.3, D8, T27–T30).

P treats Q exactly like a WARP exit, the P↔Q mesh link as the tunnel. Per such rule the arrivals pass emits:
  · at P — the arrival entry via P's leg to Q (the node writes the origin guard `iifname != <leg>` itself), one rule-scoped
    devexit per (ARRIVAL subnet, leg) — the existing SNAT, which masquerades the arrival to P's own link address — and the
    leg's AllowedIPs opened to any destination;
  · at Q — ONE exit record for P's link address, written BARE (T27), marked hop-2 so it is never an arrival at Q (T29),
    carrying the exit IP P's list chose for Q, and Q's device default through the D5 `from` shape.
And `mesh_need` wants the P–Q link, and P's table band reserves Q. Panel-only: every record is a shape the released node runs.

Run: python3 tests/arrival_hop_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     s32   Q's record written with `/32` (the kernel lists it bare, so Q's band is flushed and rebuilt every pass, T27)
     hop2  P's link address is listed among Q's arrival subnets (Q's list would forward second-hop traffic: the loop, T29)
     leg   the devexits keyed by the leg rather than the arrival subnet (P's own clients going to Q get masqueraded, O3)
     mesh  mesh_need blind to a node list's "Forward to node" (a demand-mode fleet retires the P–Q link under the traffic)
     band  P's table band does not reserve Q for the arrivals (the rule routes nothing on a node with no other use for Q)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "s32": ('''                _lka = str(lk).split("/")[0]                   # BARE''',
            '''                _lka = str(lk).split("/")[0] + "/32"           # BARE'''),
    "hop2": ('''            if (sp.get("_hop2") or {}).get(e["subnet"]):
                continue                                   # T29''', '''            if False:
                continue                                   # T29'''),
    "leg": ('''                    _de = {"subnet": S, "dev": dev_p, "table": T, "killswitch": False, "scope": "rule", "egress_ip": "", "gw": ""}''',
            '''                    _de = {"subnet": "0.0.0.0/0", "dev": dev_p, "table": T, "killswitch": False, "scope": "rule", "egress_ip": "", "gw": ""}'''),
    "mesh": ('''                if isinstance(r, dict) and rule_on(r) and r.get("action") == "exit":
                    want(nid, str(r.get("node") or ""))''', '''                if False:
                    want(nid, str(r.get("node") or ""))'''),
    "band": ('''                    targets.append(_r["node"])''', '''                    pass'''),
}
TMP = tempfile.mkdtemp(prefix="arrival-hop-")
path = PANEL
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
_l = importlib.machinery.SourceFileLoader("swgpanel_hop", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_hop", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

# the hop rig's topology (§3.5): N ── P ── Q, and NO link between N and Q
W = {"id": "cccc0003", "label": "Q-WARP", "device": "wgw0", "enabled": True, "producer": "adopted", "killswitch": True}
D1 = "203.0.113.80/32"
CAP = {"mode": "kernel", "src": 1, "arr": 1}
SNAPS = {"n": {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.28.0.0/24"}}}, "smartroute": CAP},
         "p": {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}}, "smartroute": CAP},
         "q": {"interfaces": {"wg0": {"meta": {"subnet": "10.10.0.0/24"}}}, "smartroute": CAP,
               "ether_ifaces": ["eth0"], "wan_iface": "eth0"}}


def R(targets, **kw):
    return {"enabled": True, "category": "custom", "targets": targets, **kw}


def fleet(p_list, q_default="", q_list=None, p_xips=None, p_wg0=None):
    n = {"name": "n", "routing_mode": "kernel",
         "ifaces": {"wg0": {"egress_mode": "smart", "routing": [R(D1, action="exit", node="p")]},
                    "wg9": {"egress_mode": "forward", "egress_node": "p"}},
         "links": {"p": {"iface": "swg_p", "peer_address": "10.255.0.1"}}}
    p = {"name": "p", "routing_mode": "kernel", "ifaces": {"wg0": p_wg0 if p_wg0 is not None else {"egress_mode": "direct", "wan_iface": "eth0"}},
         "links": {"n": {"iface": "swg_n", "peer_address": "10.255.0.0"}, "q": {"iface": "swg_q", "peer_address": "10.255.0.2"}}}
    q = {"name": "q", "routing_mode": "kernel", "ifaces": {"wg0": {"egress_mode": "direct", "wan_iface": "eth0"}}, "exits": [dict(W)],
         "links": {"p": {"iface": "swg_p", "peer_address": "10.255.0.3"}}}
    nodes = {"n": n, "p": p, "q": q}
    for P_, L in (("p", p_list), ("q", q_list)):
        if L is not None:
            cl, err, _d = P._validate_routing(L, nodes, P_, (), snap=SNAPS[P_], prev=[], node_scope=True)
            assert err is None, err
            nodes[P_]["default_routing"] = cl
            P.derive_default_exit(nodes[P_])
    if q_default:
        q["default_exit"] = q_default
    if p_xips:
        p["default_routing_exit_ips"] = p_xips
    return nodes


LIST = [R(D1, action="exit", node="q")]
pl = P.cascade_plan(fleet(LIST), SNAPS)
sp, sq = pl.get("p") or {}, pl.get("q") or {}
a = sp.get("arrivals") or {}
print("[at P — the middle node]")
check("P's arrivals are N's two subnets", a.get("subnets") == ["10.28.0.0/24", "10.8.0.0/24"], a)
check("the rule lowers to an arrival entry via P's leg to Q (a table of P's, like a WARP device)",
      [(e["action"], e.get("via_iface")) for e in a.get("entries") or []] == [("exit", "swg_q")], a)
_legdx = [d for d in sp.get("devexit") or [] if d["dev"] == "swg_q"]
check("one rule-scoped devexit per (ARRIVAL subnet, leg) — the SNAT that masquerades the arrival to P's link address",
      sorted(d["subnet"] for d in _legdx) == ["10.28.0.0/24", "10.8.0.0/24"] and all(d.get("scope") == "rule" for d in _legdx), _legdx)
check("…never keyed by the leg alone: P's own clients going to Q keep their own addresses (O3)",
      all(d["subnet"] in ("10.28.0.0/24", "10.8.0.0/24") for d in _legdx), _legdx)
check("the leg's AllowedIPs open to any destination", (sp.get("allowed") or {}).get("swg_q") == "0.0.0.0/0", sp.get("allowed"))
check("P's table band holds Q (the arrival entry has a table)", bool(a.get("entries")) and all(isinstance(e.get("table"), int) for e in a.get("entries")), a)
check("the arrivals never reach the relay's legs (T8)", not any(l.get("peer") == "q" for l in sp.get("_legs") or []), sp.get("_legs"))
print("\n[at Q — the far node]")
qex = [e for e in sq.get("exit") or [] if e["via_iface"] == "swg_p"]
check("Q gets ONE exit record, for P's link address, over its leg to P", [e["subnet"] for e in qex] == ["10.255.0.3"], qex)
check("…written BARE, as the kernel lists a host rule (T27)", qex and "/" not in qex[0]["subnet"], qex)
check("…and Q's AllowedIPs for P hold it once, as a /32", ((sq.get("allowed") or {}).get("swg_p") or "").split(",").count("10.255.0.3/32") == 1
      and "10.255.0.3," not in (sq.get("allowed") or {}).get("swg_p", "") + ",", sq.get("allowed"))
check("Q never sees N's clients: no record for N's subnets at Q", not any(e["subnet"] in ("10.8.0.0/24", "10.28.0.0/24") for e in sq.get("exit") or []),
      sq.get("exit"))
pl2 = P.cascade_plan(fleet(LIST, q_list=[R(D1, action="exit", node="p"), {"enabled": True, "category": "all", "action": "dev", "exit_id": W["id"]}]), SNAPS)
check("⚠️ P's link address is NEVER an arrival at Q, even where Q's own list forwards back to P — the chain ends at Q (T29)",
      "10.255.0.3" not in ((pl2.get("q") or {}).get("arrivals") or {}).get("subnets", []), (pl2.get("q") or {}).get("arrivals"))
check("…and Q's device default still lets it out through the D5 `from` shape, list or not (§8 P3b)",
      [d["dev"] for d in (pl2.get("q") or {}).get("devexit") or [] if d["subnet"] == "10.255.0.3" and (d.get("scope") or "iface") == "iface"] == ["wgw0"],
      (pl2.get("q") or {}).get("devexit"))
pl3 = P.cascade_plan(fleet(LIST, q_default=W["id"]), SNAPS)
check("a PLAIN device default at Q applies to the hop-2 record too", [d["dev"] for d in (pl3.get("q") or {}).get("devexit") or []
                                                                     if d["subnet"] == "10.255.0.3"] == ["wgw0"], (pl3.get("q") or {}).get("devexit"))
pl4 = P.cascade_plan(fleet(LIST, q_default=W["id"], p_xips={"q": "198.51.100.52"}), SNAPS)
check("the exit IP P's list chose for Q rides on Q's record…", [e["egress_ip"] for e in (pl4.get("q") or {}).get("exit") or []
                                                                if e["subnet"] == "10.255.0.3"] == ["198.51.100.52"], (pl4.get("q") or {}).get("exit"))
check("…and a pinned hop skips Q's default, as any pinned arrival does (§3.4)",
      not [d for d in (pl4.get("q") or {}).get("devexit") or [] if d["subnet"] == "10.255.0.3"], (pl4.get("q") or {}).get("devexit"))
print("\n[around it]")
check("mesh_need wants the P–Q link a node list's \"Forward to node\" routes over",
      frozenset(("p", "q")) in P.mesh_need(fleet(LIST), {"cas_legs": {}}))
check("the audience holds: a Forward rule for this node's OWN clients only is no onward hop",
      not (P.cascade_plan(fleet([R(D1, action="exit", node="q", aud="local")]), SNAPS).get("p") or {}).get("arrivals"))
_old = dict(SNAPS, p=dict(SNAPS["p"], smartroute={"mode": "kernel", "src": 1}))
check("a middle node that does not run arrivals is sent none, and Q gets no hop-2 record (D4)",
      not (P.cascade_plan(fleet(LIST), _old).get("q") or {}).get("exit"), (P.cascade_plan(fleet(LIST), _old).get("q") or {}).get("exit"))

if PLANT:
    want = {"s32": "written BARE", "hop2": "NEVER an arrival at Q", "leg": "never keyed by the leg",
            "mesh": "mesh_need wants the P–Q", "band": "P's table band holds Q"}[PLANT]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
