#!/usr/bin/env python3
"""Self-test for the exit IP — which of a far node's addresses an interface's traffic leaves it by
(docs/ROUTING-PEERS-MESH-PLAN.md §4.2, §6.4, §8 P2).

It is stored as a MAP ON THE INTERFACE, `routing_exit_ips: {<node id>: <IPv4>}`, not as a field on a rule,
because that is where the fact lives: the far node applies it as ONE `swg-fwd-snat:<arriving subnet>
--to-source X`, so every rule that sends this interface through that node shares one address. Most of what
this file checks is therefore that things are IMPOSSIBLE rather than refused — two rules cannot disagree
about one address, a re-pointed rule cannot carry the previous node's address, and an old tab rewriting
`routing` cannot touch the addresses at all.

  THE DOOR (`_clean_exit_ips` through `_apply_egress_mode`) — the shape; a blank clears an entry; the
      asymmetric door on node ids (a NEW unknown one refused, a STORED one tolerated, or deleting a node
      would make the interface unsavable); and ABSENT MEANS UNCHANGED, which is what lets an older client
      save the rules it understands without destroying the addresses it does not.
  THE PLAN (`cascade_plan`) — the address reaches the far node as that subnet's exit record `egress_ip`,
      whatever order the rules are in; a fleet that pins nothing gets exactly the plan it got before this
      existed; and a hand-edited value that is not an address never reaches a node (`_ip4`).
  P's DEFAULT — a pinned (S, P) does not then leave P by P's default exit.
  WHAT IS GONE — the rule list carries no address, so a client that sends one on a rule has it dropped.

Run: python3 tests/routing_exit_ip_selftest.py   (0 = pass)
  --plant a|b|c|d|e|f plant one defect and expect RED on its own check (exit 0 when caught):
     a  `_ip4` trusts the stored value (a hand-edited map becomes `--to-source <junk>` on a real node)
     b  a pinned interface is not exempt from the far node's default exit (the address is overruled, invisibly)
     c  the door refuses a STORED node id (deleting a node makes that interface unsavable, fix included)
     d  the plan ignores the map (the address is configured, shown, and routes nothing)
     e  a save that does not mention the addresses wipes them (every older client silently clears them)
     f  the interface record served to the browser drops the map (the editor reopens empty and the next save clears it)
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
    "f": ('''        ifc["routing_exit_ips"] = dict(ov.get("routing_exit_ips") or {})''',
          '''        pass'''),
    "a": ('''    try:
        ipaddress.IPv4Address(v)
    except Exception:
        return ""
    return v''',
          '''    return v'''),
    "b": ('''        _pd = str((nodes.get(P) or {}).get("default_exit") or "").strip()
        if _pd and not X and not W:''',
          '''        _pd = str((nodes.get(P) or {}).get("default_exit") or "").strip()
        if _pd:'''),
    "c": ('''        if (k not in nodes or k == nid) and k not in stored:''',
          '''        if k not in nodes or k == nid:'''),
    "d": ('''            _pin = ov.get("routing_exit_ips") or {}''',
          '''            _pin = {}'''),
    "e": ('''    if "routing_exit_ips" not in body:
        return None''',
          '''    if False:
        return None'''),
}
path = PANEL
TMP = tempfile.mkdtemp(prefix="routing-exit-ip-")
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))

_l = importlib.machinery.SourceFileLoader("swgpanel_xip", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_xip", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

X1, X2 = "198.51.100.7", "198.51.100.8"
SNAP_N = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.28.0.0/24"}}},
          "smartroute": {"mode": "kernel", "src": 1}}
SNAP_P = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}},
          "ether_ifaces": ["eth0"], "wan_iface": "eth0", "ether_gws": {"eth0": "198.51.100.1"},
          "node_ips": [X1, X2], "smartroute": {"mode": "kernel", "src": 1}}
SNAPS = {"n1": SNAP_N, "n2": SNAP_P}
DEPS = {"panel_settings": {}, "node_snaps": SNAPS, "roster_path": os.path.join(TMP, "users.json")}


def fleet(wg0=None, wg9=None, p_default="", p_exits=None):
    n1 = {"name": "node-one", "routing_mode": "kernel", "ifaces": {"wg0": wg0 if wg0 is not None else {}},
          "links": {"n2": {"iface": "swg_n2", "peer_address": "10.255.0.1"}}}
    if wg9 is not None:
        n1["ifaces"]["wg9"] = wg9
    n2 = {"name": "node-two", "routing_mode": "kernel", "ifaces": {"wg0": {}},
          "exits": p_exits or [], "default_exit": p_default,
          "links": {"n1": {"iface": "swg_n1", "peer_address": "10.255.0.0"}}}
    return {"n1": n1, "n2": n2}


def R(targets="203.0.113.0/24", node="n2", **kw):
    return {"enabled": True, "category": "custom", "targets": targets, "action": "exit", "node": node, **kw}


def save(body, stored=None):
    """One egress save against the real helper. `stored` is the record as it already is."""
    rec = dict(stored if stored is not None else {"egress_mode": "smart", "routing": []})
    err, _drop = P._apply_egress_mode(rec, body, fleet(), "n1", DEPS)
    return err, rec


def smart(routing, **kw):
    return {"egress_mode": "smart", "routing": routing, "routing_v": 2, **kw}


# ── 1. the door ─────────────────────────────────────────────────────────────────────────────────────────
print("[the door]")
e, rec = save(smart([R()], routing_exit_ips={"n2": X1}))
check("an address is stored on the INTERFACE, keyed by the far node", e is None and rec.get("routing_exit_ips") == {"n2": X1}, (e, rec))
check("…and the rule list carries none of it — no rule has an address to disagree about",
      all("exit_ip" not in r for r in rec["routing"]), rec["routing"])
e, rec = save(smart([R(exit_ip=X2)], routing_exit_ips={"n2": X1}))
check("an address sent ON A RULE is dropped, not stored (the shape it would need does not exist)",
      e is None and all("exit_ip" not in r for r in rec["routing"]), rec["routing"])
e, rec = save(smart([R()], routing_exit_ips={"n2": ""}), stored={"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n2": X1}})
check("a blank clears that node's entry — Auto is the absence of an address, not an empty one",
      e is None and "routing_exit_ips" not in rec, (e, rec))
e, rec = save(smart([R()], routing_exit_ips={}), stored={"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n2": X1}})
check("…and an empty map pops the key entirely", e is None and "routing_exit_ips" not in rec, (e, rec))
e, _r = save(smart([R()], routing_exit_ips={"n2": "not-an-address"}))
check("a value that is not an IPv4 address is refused", isinstance(e, str) and "IPv4" in e, e)
e, _r = save(smart([R()], routing_exit_ips=["n2", X1]))
check("a map that is not a map is refused", isinstance(e, str) and "per node" in e, e)
e, _r = save(smart([R()], routing_exit_ips={"n9": X1}))
check("a NEW key naming a node that is not in this panel is refused", isinstance(e, str) and "another node" in e, e)
e, _r = save(smart([R()], routing_exit_ips={"n1": X1}))
check("…and one naming this node itself is refused too", isinstance(e, str) and "another node" in e, e)
e, rec = save(smart([R()], routing_exit_ips={"n9": X1}), stored={"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n9": X1}})
check("a STORED key for a node that has since been deleted is tolerated (the interface stays savable)",
      e is None and rec.get("routing_exit_ips") == {"n9": X1}, (e, rec))
e, rec = save(smart([R()], routing_exit_ips={"n2": X1}))
check("an address the far node has NOT reported is accepted (its snapshot may be missing — the shape is what is checked)",
      e is None and rec.get("routing_exit_ips") == {"n2": X1})
e, rec = save(smart([R()], routing_exit_ips={"n2": X1, "n9": X2}), stored={"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n9": X2}})
check("…and an entry for a node NO RULE names is kept, like the rule list itself is when a mode changes",
      e is None and rec.get("routing_exit_ips") == {"n2": X1, "n9": X2}, (e, rec))

print("\n[absent means unchanged — what makes an older client harmless]")
STORED = {"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n2": X1}}
e, rec = save(smart([R()]), stored=STORED)
check("a save that does not mention the addresses leaves them exactly as they were",
      e is None and rec.get("routing_exit_ips") == {"n2": X1}, (e, rec))
e, rec = save({"egress_mode": "smart", "routing": [R()]}, stored=STORED)
check("…including one from a tab too old to know about them (no routing_v): it saves, and they survive",
      e is None and rec.get("routing_exit_ips") == {"n2": X1}, (e, rec))
e, rec = save({"routing": [R()]}, stored=STORED)
check("…and the rule-only save path behaves the same", e is None and rec.get("routing_exit_ips") == {"n2": X1}, (e, rec))
WHO = {"enabled": False, "category": "custom", "targets": "203.0.113.0/24", "action": "exit", "node": "n2",
       "who": {"on": True, "users": ["u1"], "groups": [], "peers": []}}
e, _r = save({"egress_mode": "smart", "routing": [R()]}, stored={"egress_mode": "smart", "routing": [WHO]})
check("a stored SELECTION is still guarded from an old tab — that one IS in the rule list (D7)",
      isinstance(e, str) and e.startswith("This browser tab is older"), e)

# ── 2. the plan ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[the plan]")


def plan(rules, ips=None, **kw):
    cl, err, _d = P._validate_routing(rules, fleet(**kw), "n1", (), snap=SNAP_N, prev=[])
    assert err is None, err
    ov = {"egress_mode": "smart", "routing": cl}
    if ips is not None:
        ov["routing_exit_ips"] = ips
    return P.cascade_plan(fleet(wg0=ov, **kw), SNAPS)


def ex(pl):
    return (pl.get("n2") or {}).get("exit") or []


pl = plan([R()], {"n2": X1})
check("the address reaches the FAR node as that subnet's exit record egress_ip (`swg-fwd-snat:S --to-source X`)",
      len(ex(pl)) == 1 and ex(pl)[0]["subnet"] == "10.8.0.0/24" and ex(pl)[0]["egress_ip"] == X1, ex(pl))
check("…and nothing else about the record changed", ex(pl)[0]["via_iface"] == "swg_n1" and ex(pl)[0]["wan_iface"] == "", ex(pl))
pl2 = plan([R("192.0.2.0/24"), R("203.0.113.0/24")], {"n2": X1})
check("EVERY rule to that node leaves by it, in any order — the map is read once, not per rule",
      len(ex(pl2)) == 1 and ex(pl2)[0]["egress_ip"] == X1, ex(pl2))
pl3 = plan([R()])
check("a fleet that pins nothing gets `egress_ip: \"\"`, exactly as before this existed", ex(pl3) and ex(pl3)[0]["egress_ip"] == "", ex(pl3))
pl4 = plan([R()], {"n9": X1})
check("an entry for a node this interface does not route to changes nothing", ex(pl4)[0]["egress_ip"] == "", ex(pl4))
pl5 = plan([R()], {"n2": "10.0.0.1; rm -rf /"})
check("a hand-edited value that is not an address never reaches a node (`_ip4`)", ex(pl5)[0]["egress_ip"] == "", ex(pl5))
a = json.dumps(plan([R()], {"n2": X1}), sort_keys=True, default=str)
b = json.dumps(plan([R()]), sort_keys=True, default=str)
check("the pinned plan and the unpinned one differ in EXACTLY one field — that record's egress_ip (§5.3)",
      a.replace('"egress_ip": "%s"' % X1, '"egress_ip": ""') == b)

# ── 3. the far node's own default exit ──────────────────────────────────────────────────────────────────
print("\n[the far node's own default exit]")
PX = [{"id": "aabbccdd", "device": "wgx0", "enabled": True, "producer": "adopted", "egress_ip": "", "gw": ""}]
FWD = {"egress_mode": "forward", "egress_node": "n2"}


def dx(pl):
    return [d["subnet"] for d in ((pl.get("n2") or {}).get("devexit") or [])]


pd = P.cascade_plan(fleet(wg9=dict(FWD), p_default="aabbccdd", p_exits=PX), SNAPS)
check("CONTROL — an UNPINNED forward arrival leaves P by P's default exit", "10.28.0.0/24" in dx(pd), dx(pd))
pp = P.cascade_plan(fleet(wg9=dict(FWD, egress_ip=X2), p_default="aabbccdd", p_exits=PX), SNAPS)
check("a PINNED (S, P) is exempt from P's default exit — the operator named an address and it must not be overruled",
      "10.28.0.0/24" not in dx(pp), dx(pp))
check("…and it is the pinned address the exit record carries", [e["egress_ip"] for e in ex(pp)] == [X2], ex(pp))
check("…while P's OWN clients keep their default either way (the exemption is about the ARRIVING subnet)",
      all("10.9.0.0/24" in dx(x) for x in (pd, pp)), [dx(x) for x in (pd, pp)])
ps = plan([R()], {"n2": X1}, p_default="aabbccdd", p_exits=PX)
check("a pinned SMART rule's subnet gets no default-exit entry at P either "
      "(today because no smart arrival does — D5; when P3 gives them one, this is what must keep it off a pinned pair)",
      "10.8.0.0/24" not in dx(ps), dx(ps))
check("…and its exit record still carries the address", [e["egress_ip"] for e in ex(ps)] == [X1], ex(ps))

# ── 3b. the round trip through the browser ──────────────────────────────────────────────────────────────
# ⚠️ THE ONE THAT SHIPPED. A record field the save path writes and NO builder publishes reads to the browser
# as absent, so `egressInit` opens the editor with an empty map and the very next save — even one that only
# changes the MTU — sends `{}` and clears it. The feature was write-once-then-lost, and nothing said so.
# `tests/settings_node_fields_selftest.py` derives the ladder's fields and checks all three builders; this is
# the same fact from the other end, on the function itself.
print("\n[the round trip through the browser]")
_ifs = {"wg0": {"meta": {}}}
P.apply_iface_meta({"ifaces": {"wg0": {"egress_mode": "smart", "routing": [], "routing_exit_ips": {"n2": X1}}}}, _ifs)
check("the interface record the browser is served carries the address map",
      _ifs["wg0"].get("routing_exit_ips") == {"n2": X1}, sorted(_ifs["wg0"]))
_ifs2 = {"wg0": {"meta": {}}}
P.apply_iface_meta({"ifaces": {"wg0": {"egress_mode": "smart", "routing": []}}}, _ifs2)
check("…and an interface with none is served an empty map, not a missing key",
      _ifs2["wg0"].get("routing_exit_ips") == {}, _ifs2["wg0"].get("routing_exit_ips"))

print("\n[the create path is lenient, the edit path is not]")
_ov = {}
_cerr = P._apply_exit_ips(_ov, {"routing_exit_ips": {"n9": X1}}, fleet(), "n1", lenient=True)
check("creating an interface drops an entry for a node that is not there rather than refusing the creation",
      _cerr is None and "routing_exit_ips" not in _ov, (_cerr, _ov))
_ov2 = {}
_cerr2 = P._apply_exit_ips(_ov2, {"routing_exit_ips": {"n9": "nope"}}, fleet(), "n1", lenient=True)
check("…but a malformed address is still refused there — that is a bad request, not a stale reference",
      isinstance(_cerr2, str) and "IPv4" in _cerr2, _cerr2)

# ── 4. what the shape removed ───────────────────────────────────────────────────────────────────────────
print("\n[what the shape removed]")
src = open(path, encoding="utf-8").read()
check("no refusal exists for two rules disagreeing about one node's address — they cannot",
      "exit_ip_conflict" not in src and "with different addresses" not in src)
check("no per-rule address is read anywhere in the panel", '"exit_ip"' not in src)
check("the wire is unchanged: the address travels only as an exit record's `egress_ip`",
      '"routing_exit_ips"' not in json.dumps(plan([R()], {"n2": X1}), default=str))

if PLANT:
    want = {"a": "never reaches a node", "b": "exempt from P's default", "c": "STORED key",
            "d": "reaches the FAR node", "e": "leaves them exactly as they were",
            "f": "browser is served carries"}[PLANT]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
