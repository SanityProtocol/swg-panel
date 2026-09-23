#!/usr/bin/env python3
"""Self-test for the node's default made smart, and the traffic other nodes cascade out through it
(docs/ROUTING-PEERS-MESH-PLAN.md §3.1–3.4, §4.2–4.4, §8 P3, D2/D3/D5/D9/D11).

The node's default may be a RULE LIST (`default_routing`, its presence the switch). One list routes three things:
its Auto interfaces, the silence of its smart interfaces (D11), and — on a node that runs `smart.arrivals` — the
subnets other nodes cascade out through it. `default_exit` is DERIVED from the list's catch-all, and is what an older
panel and an older node fall back to.

  THE DOOR          — `/api/nodes/update` through the real handler: the list stored, `aud` kept only on it, `who` refused
                      on it, `default_exit` derived and a body's own ignored while the list exists (T12), `null` switches
                      it off, and a device the list names that is minted in the same save survives the `exits` it sent.
  THE PLAN          — Auto → the list; silence falls through past the node's `cascaded`-only rules (D11); arrivals are
                      lowered once for the node's `cascaded` + All rules, with one rule-scoped devexit per (arrival subnet,
                      device); a capable node keeps NO `from S` default beside its marks (D3's trap, T1); an incapable one
                      gets nothing new and falls back to the catch-all as a plain default (D4); D5 gives a SMART arrival a
                      plain default exactly as a forward one gets it; a PINNED (S, P) is exempt from P's default in both
                      halves (§3.4 — the P2 constraint); a subnet two origins send is left out (T15); arrivals never reach
                      the relay's legs (T8); and a fleet with none of this plans exactly what it did before (§5.3).
  THE SYNC SLICE    — the syncing node's slice keeps the arrivals' categories in its domain / CIDR channels even where a
                      rule names people (`who_plan_for_node` filters those channels).
  THE CARD          — an older node with a list is told it lacks `arr`; an arrival's exit alarm names "traffic cascaded in"
                      rather than subnets; a mesh leg is never announced as a broken exit (T31).

Run: python3 tests/default_routing_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     a  a `from S` default is left beside the arrival marks on a capable node (a mark loses to it, D3/T1)
     b  arrival entries are sent to a node that does not run them (it would ignore them, and they stand in for its fallback)
     c  an Auto interface is not lowered with the list
     d  a smart interface's silence does not fall through to the list
     e  the D5 branch is removed (a smart arrival leaves P's own address past P's plain default and its kill-switch)
     f  `default_exit` is not derived from the list on write (an older panel/node then falls back to a stale or absent exit)
     g  arrival devexits are not one per (arrival subnet, device) — a second origin's subnet loses its SNAT at the exit
     h  the local lowering ignores `aud` (a "cascaded in" rule routes this node's own clients)
     i  the arrivals lowering ignores `aud` (an "own clients" rule routes traffic cascaded in)
     j  silence stops at the node's first `cascaded`-only rule instead of passing it (D11)
     k  a pinned arrival is not exempt from P's list (the origin's chosen address is overruled)
     l  the list's exit IP is not applied before the interface's own rules lower (review #2)
     o  every list is lowered as smart for the node's own clients, even one that is only a catch-all (their IPv6/HTTP/3 lost)
     n  a list node with no plan slot gets no "whom it affects" (review #8)
     m  an interface pinned to an unusable exit falls back past the list to the node's own address (review #3)
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
    "a": ("""        if _nlist(P) is not None and _arr_ok(P) and not hop2:
            return""", """        pass"""),
    "b": ('''        if not subs or not _arr_ok(P):
            continue
        ents, dx = [], []''', '''        if not subs:
            continue
        ents, dx = [], []'''),
    "c": ('''        if _auto and _nlist(nid) is not None and _nlist_selective(nid):''', '''        if False:'''),
    "d": ('''            if not _all_said and _nl is not None:''', '''            if False:'''),
    "e": ('''            arrival_default(P, S, pin, "")                   # D5''', '''            pass                                             # D5'''),
    "f": ('''        derive_default_exit(nodes[nid])      # the list's catch-all''',
          '''        pass                                 # the list's catch-all'''),
    "g": ("""                for S in subs:
                    dx.append({"subnet": S, "dev": _xdev,""", """                for S in subs[:1]:
                    dx.append({"subnet": S, "dev": _xdev,"""),
    "h": ('''                    if isinstance(r, dict) and r.get("aud") != "cascaded":
                        _lower(r)''', '''                    if isinstance(r, dict):
                        _lower(r)'''),
    "i": ('''            if not isinstance(r, dict) or not rule_on(r) or r.get("aud") == "local":''',
          '''            if not isinstance(r, dict) or not rule_on(r):'''),
    "j": ('''                    if isinstance(r, dict) and r.get("aud") != "cascaded":
                        _lower(r)''', '''                    if isinstance(r, dict) and r.get("aud") == "cascaded":
                        break
                    if isinstance(r, dict):
                        _lower(r)'''),
    "l": ('                exit_ips_of[(nid, S)] = {**((nodes.get(nid) or {}).get("default_routing_exit_ips") or {}), **_xm}',
          '                pass'),
    "m": ('        elif mode == "exit" and _nlist(nid) is not None and _nlist_selective(nid) and not resolve_exit(nodes, snaps, nid, ov.get("exit_id")):',
          '        elif False:'),
    "n": ("""        if _nl is None:
            continue
        sp = slot(P) """, """        if _nl is None or P not in plans:
            continue
        sp = slot(P) """),
    "o": ("""        nl = _nlist(nid) or []
        for r in nl:""", """        return True
        nl = _nlist(nid) or []
        for r in nl:"""),
    "k": ('''        subs = sorted(S for S in _via if S not in _pinned and S not in _dup''',
          '''        subs = sorted(S for S in _via if S not in _dup'''),
}
TMP = tempfile.mkdtemp(prefix="default-routing-")
path = PANEL
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))

_l = importlib.machinery.SourceFileLoader("swgpanel_dr", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_dr", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

# p0's topology (§1.1): N = n1 (wg0 SMART 10.8/24, wg9 FORWARD 10.28/24), P = n2 (wg0 10.9/24, exits x1 wgx0 / y1 wgy0)
X1 = {"id": "aaaa0001", "label": "X", "device": "wgx0", "enabled": True, "producer": "adopted", "killswitch": False}
Y1 = {"id": "bbbb0002", "label": "Y", "device": "wgy0", "enabled": True, "producer": "adopted", "killswitch": True}
SN = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.28.0.0/24"}}},
      "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
SP = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}, "wg5": {"meta": {"subnet": "10.19.0.0/24"}}},
      "ether_ifaces": ["eth0"], "wan_iface": "eth0", "ether_gws": {"eth0": "198.51.100.1"},
      "node_ips": ["198.51.100.254", "198.51.100.9"], "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
OLD = {k: v for k, v in SP.items() if k != "smartroute"}
OLD["smartroute"] = {"mode": "kernel", "src": 1}                       # a node that does not run `smart.arrivals`
D1, D2 = "203.0.113.80/32", "192.0.2.80/32"


def R(targets, **kw):
    return {"enabled": True, "category": "custom", "targets": targets, **kw}


def fleet(n_wg0=None, n_wg9=None, p_list=None, p_default="", p_wg0=None, p_wg5=None, p_xips=None):
    n1 = {"name": "node-n", "routing_mode": "kernel",
          "ifaces": {"wg0": n_wg0 if n_wg0 is not None else {"egress_mode": "smart", "routing": [R(D1 + ", " + D2, action="exit", node="n2")]},
                     "wg9": n_wg9 if n_wg9 is not None else {"egress_mode": "forward", "egress_node": "n2"}},
          "links": {"n2": {"iface": "swg_p", "peer_address": "10.255.0.1"}}}
    n2 = {"name": "node-p", "routing_mode": "kernel", "exits": [dict(X1), dict(Y1)],
          "ifaces": {"wg0": p_wg0 if p_wg0 is not None else {}, "wg5": p_wg5 if p_wg5 is not None else {}},
          "links": {"n1": {"iface": "swg_n", "peer_address": "10.255.0.0"}}}
    if p_list is not None:
        n2["default_routing"] = p_list
        P.derive_default_exit(n2)
    elif p_default:
        n2["default_exit"] = p_default
    if p_xips:
        n2["default_routing_exit_ips"] = p_xips
    return {"n1": n1, "n2": n2}


def plan(nodes, sp=SP, sn=SN):
    return P.cascade_plan(nodes, {"n1": sn, "n2": sp})


def arr(pl):
    return (pl.get("n2") or {}).get("arrivals") or {}


def dx(pl, scope=None):
    return [d for d in ((pl.get("n2") or {}).get("devexit") or []) if scope is None or (d.get("scope") or "iface") == scope]


def iface_fromS(pl, S):     # an iface-scoped devexit for S at P = `ip rule from S lookup T` at the node
    return [d for d in dx(pl, "iface") if d["subnet"] == S]


# A list: D2 → X for everyone, D1 → Y for traffic cascaded in only, 198.51.100.0/24 → Direct for own clients, catch-all → Y
LIST = [R(D2, action="dev", exit_id=X1["id"]),
        R(D1, action="dev", exit_id=Y1["id"], aud="cascaded"),
        R("198.51.100.0/24", action="direct", aud="local"),
        {"enabled": True, "category": "all", "action": "dev", "exit_id": Y1["id"]}]

# ── 1. the door ─────────────────────────────────────────────────────────────────────────────────────────────
print("[the door — /api/nodes/update, the real handler]")
np_, rp_ = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
json.dump(fleet(), open(np_, "w"))
json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp_, "w"))
deps = {"nodes_path": np_, "roster_path": rp_, "node_snaps": {"n1": SN, "n2": SP}, "stats_dir": TMP, "fleet": {},
        "panel_settings": {}}
code, rsp = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_routing": LIST, "default_exit": X1["id"],
                                                    "exits": [dict(X1), dict(Y1)]}, deps)
st = json.load(open(np_))["n2"]
check("the list is stored", code == 200 and isinstance(st.get("default_routing"), list) and len(st["default_routing"]) == 4, (code, rsp))
check("…with each rule's audience kept on it", [r.get("aud") for r in st.get("default_routing") or []] == [None, "cascaded", "local", None],
      [r.get("aud") for r in st.get("default_routing") or []])
check("`default_exit` is DERIVED from the catch-all, and the body's own is ignored (T12)",
      st.get("default_exit") == Y1["id"], st.get("default_exit"))
code2, _ = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_exit": X1["id"]}, deps)
check("…and an older tab sending only `default_exit` cannot contradict the list",
      json.load(open(np_))["n2"].get("default_exit") == Y1["id"], json.load(open(np_))["n2"].get("default_exit"))
code3, rsp3 = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_routing": [
    {"enabled": True, "category": "custom", "targets": D1, "action": "direct", "who": {"on": True, "users": ["u1"]}}]}, deps)
check("a rule naming people is refused on a node's list (D9: audiences, not people)", code3 == 400, (code3, rsp3))
code4, rsp4 = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_routing": [
    {"enabled": True, "category": "all", "action": "direct", "aud": "local"}]}, deps)
check("an audience on the catch-all is refused — one 'Everything else' for both", code4 == 400, (code4, rsp4))
code5, _ = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_routing": [
    {"enabled": True, "category": "all", "action": "direct"}]}, deps)
check("a Direct catch-all leaves NO default_exit (an older node then lets arrivals out by its own address)",
      code5 == 200 and "default_exit" not in json.load(open(np_))["n2"], json.load(open(np_))["n2"].get("default_exit"))
code6, _ = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "default_routing": None, "default_exit": X1["id"]}, deps)
st6 = json.load(open(np_))["n2"]
check("`null` switches the list off, and `default_exit` is written from the request again",
      code6 == 200 and "default_routing" not in st6 and st6.get("default_exit") == X1["id"], st6.get("default_exit"))
# an interface's rule keeps no `aud`
_ir, _ie, _ = P._validate_routing([R(D1, action="direct", aud="cascaded")], fleet(), "n1")
check("an interface's list does not keep `aud` (it means nothing there)", _ie is None and "aud" not in _ir[0], _ir)
# a device the list names, minted in the same save as the `exits` the browser always sends
json.dump(fleet(), open(np_, "w"))
deps["node_snaps"]["n2"] = dict(SP, exit_devices=["wgz0"])
code7, rsp7 = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "exits": [dict(X1), dict(Y1)], "default_routing": [
    {"enabled": True, "category": "all", "action": "dev", "exit_id": "dev:wgz0"}]}, deps)
st7 = json.load(open(np_))["n2"]
_mint = [x for x in st7.get("exits") or [] if x.get("device") == "wgz0"]
check("a device the list names is minted AFTER the `exits` the same save sends, so it survives them",
      code7 != 200 or (len(_mint) == 1 and st7["default_routing"][0].get("exit_id") == _mint[0]["id"]
                       and st7.get("default_exit") == _mint[0]["id"]), (code7, rsp7, st7.get("exits"), st7.get("default_routing")))

# ── 2. the plan ────────────────────────────────────────────────────────────────────────────────────────────
print("\n[the plan — cascade_plan]")
pl = plan(fleet(p_list=LIST))
a = arr(pl)
check("P's arrivals are N's two subnets (smart wg0 and forward wg9)", a.get("subnets") == ["10.28.0.0/24", "10.8.0.0/24"], a)
_ent = a.get("entries") or []
_cats = [(e["action"], e.get("via_iface")) for e in _ent]
check("the list is lowered ONCE for arrivals: All + cascaded rules, and the catch-all, in order",
      _cats == [("exit", "wgx0"), ("exit", "wgy0"), ("exit", "wgy0")] and _ent[-1]["category"] == "all", _ent)
check("…never the `local`-only rule (D9)", not any(e["action"] == "direct" for e in _ent), _ent)
check("a capable node keeps NO `from S` default for an arrival subnet — a mark loses to it (D3, T1)",
      not iface_fromS(pl, "10.28.0.0/24") and not iface_fromS(pl, "10.8.0.0/24"), dx(pl, "iface"))
_rs = {(d["subnet"], d["dev"]) for d in dx(pl, "rule")}
check("every arrival subnet gets a rule-scoped devexit for every device the list sends it out (the SNAT, table, guard)",
      {("10.8.0.0/24", "wgx0"), ("10.28.0.0/24", "wgx0"), ("10.8.0.0/24", "wgy0"), ("10.28.0.0/24", "wgy0")} <= _rs, sorted(_rs))
check("…scoped to the rule (never `from S`, which would send the whole subnet out the device)",
      all(d.get("scope") == "rule" for d in dx(pl) if d["subnet"] in ("10.8.0.0/24", "10.28.0.0/24")), dx(pl))
check("arrivals never reach the relay's legs (T8)", all(l["subnet"] not in ("10.8.0.0/24", "10.28.0.0/24")
                                                        for l in (pl.get("n2") or {}).get("_legs") or ()), (pl.get("n2") or {}).get("_legs"))
# Auto and D11 at P: wg0 Auto, wg5 smart with its own rule and nothing said about the remainder
p_wg5 = {"egress_mode": "smart", "routing": [R("100.64.0.0/10", action="block")]}
pl2 = plan(fleet(p_list=LIST, p_wg5=p_wg5))
sm = [(e["subnet"], e["category"] == "all", e["action"], e.get("via_iface")) for e in (pl2.get("n2") or {}).get("smart") or []]
wg0 = [x for x in sm if x[0] == "10.9.0.0/24"]
check("an Auto interface is lowered as SMART with the list: All + own-client rules, then the catch-all (§3.1)",
      [x[1:] for x in wg0] == [(False, "exit", "wgx0"), (False, "direct", None), (True, "exit", "wgy0")], wg0)
check("…and not as the catch-all's exit for the whole interface beside the list (T12)",
      not iface_fromS(pl2, "10.9.0.0/24"), dx(pl2, "iface"))
wg5 = [x for x in sm if x[0] == "10.19.0.0/24"]
check("a smart interface's silence falls through: its rules, then the node's (past `cascaded`-only), then the catch-all (D11)",
      [x[1:] for x in wg5] == [(False, "block", None), (False, "exit", "wgx0"), (False, "direct", None), (True, "exit", "wgy0")], wg5)
check("the list's Auto interfaces are counted for 'whom it affects' (§7.3)", (pl2["n2"].get("_reach") or {}).get("auto") == ["wg0"],
      pl2["n2"].get("_reach"))
check("…and its arrivals by origin node and subnet", (pl2["n2"].get("_reach") or {}).get("arr") == [["n1", "10.28.0.0/24"], ["n1", "10.8.0.0/24"]],
      pl2["n2"].get("_reach"))
# an older node with a list: nothing new, the catch-all as a plain default (D4)
pl3 = plan(fleet(p_list=LIST), sp=OLD)
check("a node that does not run arrivals is sent none (D4)", not arr(pl3), arr(pl3))
check("…and falls back to the catch-all as a PLAIN default for both kinds of arrival",
      iface_fromS(pl3, "10.28.0.0/24") and iface_fromS(pl3, "10.8.0.0/24")
      and all(d["dev"] == "wgy0" for d in iface_fromS(pl3, "10.28.0.0/24") + iface_fromS(pl3, "10.8.0.0/24")), dx(pl3, "iface"))
check("…while its own Auto interface is still lowered with the list — ordinary smart entries every node runs",
      any(e["subnet"] == "10.9.0.0/24" for e in (pl3.get("n2") or {}).get("smart") or []), (pl3.get("n2") or {}).get("smart"))
# D5 — a plain default, a smart arrival
pl4 = plan(fleet(p_default=Y1["id"]))
check("D5 — a SMART arrival takes P's plain default exactly as a forward one does (§3.3)",
      [d["dev"] for d in iface_fromS(pl4, "10.8.0.0/24")] == ["wgy0"], dx(pl4, "iface"))
check("…the forward one as before", [d["dev"] for d in iface_fromS(pl4, "10.28.0.0/24")] == ["wgy0"], dx(pl4, "iface"))
check("…with the default's kill-switch carried, so it fails closed (§1.3 K2)", all(d["killswitch"] for d in iface_fromS(pl4, "10.8.0.0/24")),
      iface_fromS(pl4, "10.8.0.0/24"))
# §3.4 — a pinned (S, P): the interface's exit IP for P
pinned = {"egress_mode": "smart", "routing": [R(D1, action="exit", node="n2")], "routing_exit_ips": {"n2": "198.51.100.9"}}
pl5 = plan(fleet(n_wg0=pinned, p_default=Y1["id"]))
check("⚠️ a PINNED smart (S, P) skips P's PLAIN default — the P2 constraint, now live (§3.4)",
      not iface_fromS(pl5, "10.8.0.0/24"), dx(pl5, "iface"))
pl6 = plan(fleet(n_wg0=pinned, p_list=LIST))
check("⚠️ …and P's SMART default: the pinned subnet is not an arrival (§3.4)",
      "10.8.0.0/24" not in (arr(pl6).get("subnets") or []) and "10.28.0.0/24" in (arr(pl6).get("subnets") or []), arr(pl6))
check("…and its exit record still carries the address", [e["egress_ip"] for e in (pl6["n2"]["exit"]) if e["subnet"] == "10.8.0.0/24"] == ["198.51.100.9"],
      pl6["n2"]["exit"])
fwdpin = {"egress_mode": "forward", "egress_node": "n2", "egress_ip": "198.51.100.9"}
pl7 = plan(fleet(n_wg9=fwdpin, p_list=LIST))
check("…a pinned FORWARD arrival too", "10.28.0.0/24" not in (arr(pl7).get("subnets") or []), arr(pl7))
# T15 — one subnet from two origins
nodes8 = fleet(p_list=LIST)
nodes8["n3"] = {"name": "node-q", "routing_mode": "kernel", "ifaces": {"wg0": {"egress_mode": "forward", "egress_node": "n2"}},
                "links": {"n2": {"iface": "swg_p", "peer_address": "10.255.0.3"}}}
nodes8["n2"]["links"]["n3"] = {"iface": "swg_q", "peer_address": "10.255.0.2"}
pl8 = P.cascade_plan(nodes8, {"n1": SN, "n2": SP, "n3": {"interfaces": {"wg0": {"meta": {"subnet": "10.28.0.0/24"}}}}})
check("a subnet two origins both send is left out of the arrivals, not merged into one set (T15)",
      "10.28.0.0/24" not in (arr(pl8).get("subnets") or []) and "10.8.0.0/24" in (arr(pl8).get("subnets") or []), arr(pl8))
check("…and reported", (pl8["n2"].get("_reach") or {}).get("dup") == ["10.28.0.0/24"], pl8["n2"].get("_reach"))
# a list that says nothing selective to this node's own clients is a plain default wearing a list
_ca = [{"enabled": True, "category": "all", "action": "dev", "exit_id": Y1["id"]}]
_a = {k: v for k, v in plan(fleet(p_list=_ca), sp=OLD).items()}
_b = plan(fleet(p_default=Y1["id"]), sp=OLD)
for _x in _a.values():
    _x.pop("_reach", None)
check("⚠️ choosing 'Routing' with only a device-exit catch-all plans EXACTLY the plain default for this node's own clients "
      "(no smart lowering: no IPv6 drop, no QUIC drop, no SNI queue for them)",
      json.dumps(_a, sort_keys=True, default=str) == json.dumps(_b, sort_keys=True, default=str))
check("…and its Auto interfaces are still counted in 'whom it affects'",
      (plan(fleet(p_list=_ca))["n2"].get("_reach") or {}).get("auto") == ["wg0", "wg5"], plan(fleet(p_list=_ca))["n2"].get("_reach"))
# mesh_need and the prunes see the list
_mn = fleet(p_list=[R(D1, action="exit", node="n1"), {"enabled": True, "category": "all", "action": "direct"}],
            n_wg0={}, n_wg9={})
check("mesh_need wants the link a node list's \"Forward to node\" rule routes over (a demand-mode fleet keeps it)",
      frozenset(("n1", "n2")) in P.mesh_need(_mn, {"cas_legs": {}}), P.mesh_need(_mn, {"cas_legs": {}}))
_pr = fleet(p_list=[R(D1, action="dev", exit_id=Y1["id"]), {"enabled": True, "category": "all", "action": "dev", "exit_id": Y1["id"]}])["n2"]
_pr["exits"] = [dict(X1)]                                         # Y1 deleted
P.prune_exit_refs(_pr); P.prune_default_exit(_pr); P.derive_default_exit(_pr)
check("a deleted exit the list names is rewritten to Direct in the list, and `default_exit` follows (never names a ghost)",
      [r["action"] for r in _pr["default_routing"]] == ["direct", "direct"] and "default_exit" not in _pr,
      (_pr["default_routing"], _pr.get("default_exit")))
# the third review
_gq = fleet(p_list=[{"enabled": True, "category": "all", "action": "exit", "node": "n1"}])
_gq["n2"]["links"] = {}                                           # the node it forwards to is not linked (gone, or not yet)
check("a Forward catch-all to a node it cannot reach is not 'selective': Auto interfaces keep the plain lowering",
      not any(e["subnet"] == "10.9.0.0/24" for e in (plan(_gq).get("n2") or {}).get("smart") or []),
      (plan(_gq).get("n2") or {}).get("smart"))
check("a list whose catch-all is Direct still counts its Auto interfaces in 'whom it affects'",
      (plan(fleet(p_list=[{"enabled": True, "category": "all", "action": "direct"}])).get("n2") or {}).get("_reach", {}).get("auto") == ["wg0", "wg5"])
# review fixes (P3 code review)
_lp = [R("198.18.0.0/15", action="exit", node="n1"), {"enabled": True, "category": "all", "action": "block"}]
_pw = {"egress_mode": "smart", "routing": [R("100.64.0.0/10", action="exit", node="n1")]}
_n9 = fleet(p_list=_lp, p_xips={"n1": "198.51.100.44"}, p_wg5=_pw)
_n9["n1"]["ifaces"]["wg0"] = {}                                   # N forwards nothing to P here; P's wg5 forwards to N
_pl9 = P.cascade_plan(_n9, {"n1": SN, "n2": SP})
_rec = [e for e in (_pl9.get("n1") or {}).get("exit") or [] if e["subnet"] == "10.19.0.0/24"]
check("⚠️ the list's exit IP for a node reaches the (S, node) record even where the interface's own rule to that node "
      "lowers first — one address per pair, decided before any rule (review #2)", [e["egress_ip"] for e in _rec] == ["198.51.100.44"], _rec)
_pw2 = {"egress_mode": "smart", "routing": [R("100.64.0.0/10", action="exit", node="n1"),
                                            {"enabled": True, "category": "all", "action": "dev", "exit_id": "gone0000"}]}
_pl9b = P.cascade_plan(fleet(p_list=_lp, p_xips={"n1": "198.51.100.44"}, p_wg5=_pw2), {"n1": SN, "n2": SP})
_rec2 = [e for e in (_pl9b.get("n1") or {}).get("exit") or [] if e["subnet"] == "10.19.0.0/24"]
check("…and where a STORED catch-all does not lower (its exit is gone), the silence falls through and the list's address "
      "still governs (review of the fixes)", [e["egress_ip"] for e in _rec2] == ["198.51.100.44"], _rec2)
_pw3 = dict(_pw, routing_exit_ips={"n1": "198.51.100.45"})
_rec3 = [e for e in (P.cascade_plan(fleet(p_list=_lp, p_xips={"n1": "198.51.100.44"}, p_wg5=_pw3), {"n1": SN, "n2": SP}).get("n1") or {}).get("exit") or []
         if e["subnet"] == "10.19.0.0/24"]
check("…while the interface's OWN pin for that node still wins", [e["egress_ip"] for e in _rec3] == ["198.51.100.45"], _rec3)
_n10 = fleet(p_list=_lp, p_wg5={"egress_mode": "exit", "exit_id": "gone0000"})
_pl10 = P.cascade_plan(_n10, {"n1": SN, "n2": SP})
_w5 = [(e["category"], e["action"]) for e in (_pl10.get("n2") or {}).get("smart") or [] if e["subnet"] == "10.19.0.0/24"]
check("⚠️ an interface pinned to an exit that is gone falls back to the LIST, not to the node's own address (review #3)",
      ("all", "block") in _w5, _w5)
_n11 = fleet(p_list=[{"enabled": True, "category": "all", "action": "direct"}], p_wg0={"egress_mode": "direct", "wan_iface": "eth0"},
              p_wg5={"egress_mode": "direct", "wan_iface": "eth0"})
_n11["n1"]["ifaces"] = {"wg0": {}, "wg9": {}}
_pl11 = P.cascade_plan(_n11, {"n1": SN, "n2": SP})
check("a list node that nothing reaches still gets 'whom it affects' — zero, not 'worked out on the next sync' (review #8)",
      (_pl11.get("n2") or {}).get("_reach") == {"auto": [], "arr": [], "dup": []}, (_pl11.get("n2") or {}).get("_reach"))
# the byte-identical gate (§5.3) — against the tree this phase started from
_base = os.environ.get("RIG_BASE_PANEL")
if not (_base and os.path.exists(_base)):
    print("  SKIP the byte-identical check (§5.3) — set RIG_BASE_PANEL to the base tree's swg-panel-server; the 300-fleet "
          "differential (.campaign/rigs/routing-peers-mesh-p3-panel-diff.py) is the full gate")
if _base and os.path.exists(_base):
    _bl = importlib.machinery.SourceFileLoader("swgpanel_base", _base)
    B = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_base", _bl))
    try:
        _bl.exec_module(B)
    except SystemExit:
        pass
    same = []
    for f in (fleet(), fleet(p_default=X1["id"], n_wg0={}), fleet(n_wg0={"egress_mode": "direct"})):
        same.append(json.dumps(B.cascade_plan(json.loads(json.dumps(f)), {"n1": SN, "n2": SP}), sort_keys=True, default=str)
                    == json.dumps(P.cascade_plan(json.loads(json.dumps(f)), {"n1": SN, "n2": SP}), sort_keys=True, default=str))
    check("a fleet with no list and no smart arrival at a plain default plans EXACTLY what the base tree planned (§5.3)", all(same), same)

# ── 3. the syncing node's slice ────────────────────────────────────────────────────────────────────────────
print("\n[the sync slice]")
_lst = [R("example.net", action="dev", exit_id=X1["id"], aud="cascaded")]
_nd = fleet(p_list=_lst, p_wg0={"egress_mode": "smart", "routing": [
    {"enabled": False, "category": "custom", "targets": "10.0.0.0/8", "action": "direct", "who": {"on": True, "users": ["u1"]}}]})
_nd["n2"]["routing_mode"] = "forcedns"
_pp = P.cascade_plan(_nd, {"n1": SN, "n2": dict(SP, smartroute={"mode": "forcedns", "src": 1, "arr": 1})})["n2"]
_c = (_pp.get("arrivals") or {}).get("entries", [{}])[0].get("category")
_sl = P.who_plan_for_node(_pp, {"users": {}, "peers": {}, "groups": {}}, "n2", {"smartroute": {"src": 1}})
check("the slice keeps an arrival category's domains where a rule names people (`who_plan_for_node` filters them)",
      _c and _c in (_sl.get("domains") or {}), (_c, sorted(_sl.get("domains") or {})))

# ── 4. the node card ───────────────────────────────────────────────────────────────────────────────────────
print("\n[the node card]")
_rec = fleet(p_list=LIST)["n2"]
_rch = {"arr": [["n1", "10.8.0.0/24"]], "auto": [], "dup": []}
_iss = P._node_issues(_rec, dict(OLD), reach=_rch)
check("an older node with a list is told it cannot route traffic cascaded in, and by what it all leaves (D4)",
      any("needs an update to route traffic cascaded in" in i["error"] and "Y" in i["error"] for i in _iss), [i["error"] for i in _iss])
check("…but not while nothing is cascaded in to it (or the last sync has not said)",
      not any("traffic cascaded in by destination" in i["error"] for i in P._node_issues(_rec, dict(OLD), reach={"arr": []}) + P._node_issues(_rec, dict(OLD))))
_rec_ca = fleet(p_list=[{"enabled": True, "category": "all", "action": "dev", "exit_id": Y1["id"]}])["n2"]
check("…nor when its list is only a device catch-all — an older node runs that identically",
      not any("traffic cascaded in by destination" in i["error"] for i in P._node_issues(_rec_ca, dict(OLD), reach=_rch)))
_same = fleet(p_list=[R(D1, action="direct"), {"enabled": True, "category": "all", "action": "direct"}])["n2"]
_same2 = fleet(p_list=[R(D1, action="dev", exit_id=Y1["id"]), {"enabled": True, "category": "all", "action": "dev", "exit_id": Y1["id"]}])["n2"]
check("…nor when every rule sends arrivals where the older node's fallback does anyway (no false alarm)",
      not any("traffic cascaded in by destination" in i["error"] for x in (_same, _same2) for i in P._node_issues(x, dict(OLD), reach=_rch)))
_iss2 = P._node_issues(_rec, dict(SP), reach=_rch)
check("…and a node that runs arrivals is not", not any("traffic cascaded in by destination" in i["error"] for i in _iss2))
_dxr = [{"dev": "wgy0", "subnet": "10.8.0.0/24", "state": "down", "killswitch": True, "scope": "rule", "arr": True}]
_iss3 = [i for i in P._node_issues(_rec, dict(SP, devexit=_dxr)) if "wgy0" in i["error"]]
check("an arrival's exit alarm says 'traffic cascaded in', translatable, not a subnet (T31)",
      _iss3 and "traffic cascaded in" in _iss3[0]["error"] and "10.8.0.0/24" not in _iss3[0]["error"]
      and isinstance(_iss3[0]["error_vars"].get("v3"), dict), _iss3)
_iss4 = P._node_issues(_rec, dict(SP, devexit=[{"dev": "swg_n", "subnet": "10.8.0.0/24", "state": "absent", "killswitch": False, "scope": "rule"}]))
check("a mesh leg reported absent is never announced as a broken exit (T31)", not any("swg_n" in i["error"] for i in _iss4),
      [i["error"] for i in _iss4])

if PLANT:
    want = {"a": "keeps NO `from S`", "b": "does not run arrivals is sent none", "c": "Auto interface is lowered",
            "d": "silence falls through", "e": "D5 — a SMART arrival", "f": "DERIVED from the catch-all",
            "g": "every arrival subnet gets", "h": "Auto interface is lowered", "i": "never the `local`-only",
            "j": "silence falls through", "k": "SMART default: the pinned", "l": "review #2", "m": "review #3", "n": "review #8", "o": "plain default for this node's own"}[PLANT]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
