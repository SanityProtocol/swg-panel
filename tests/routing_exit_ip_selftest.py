#!/usr/bin/env python3
"""Self-test for the exit IP on a smart-routing rule (docs/ROUTING-PEERS-MESH-PLAN.md §4.2, §6.4, §8 P2).

A rule that forwards to another node may name ONE of that node's addresses, and the traffic leaves that node
from it. It is panel-only: the (S, P) exit record's `egress_ip` already becomes `swg-fwd-snat:S --to-source X`
at P on every node, 1.8.6 included. What the panel has to get right, each checked on the real functions:

  THE DOOR (`_validate_routing`)  — an address is kept on a forward rule and nowhere else; `exit_ip_who` (the
      per-person pin is cut, §12 C2); `exit_ip_conflict` — one address per (interface, far node), because the
      far node SNATs per SUBNET and two addresses cannot both be it; a switched-off rule is not in the
      conflict; the shape is checked and membership of the far node's list is NOT (its snapshot may be
      missing, and refusing then would make the pin unconfigurable while that node is down).
  THE PLAN (`cascade_plan`)       — the pin reaches the far node as that exit record's `egress_ip`, whatever
      ORDER the rules are in (`add_exit` keeps the first record for a subnet, so a rule without a pin above
      one with it must not silently drop the address); a fleet that pins nothing gets exactly the plan it got
      before this existed, to the byte.
  P's DEFAULT                     — a pinned (S, P) does not then leave P by P's default exit: the operator
      named an address, and a default that overruled it would silently undo the choice.
  THE OLD TAB (`_apply_egress_mode`) — a save without `routing_v: 2` over a stored `exit_ip` is refused, the
      same one predicate that already guards a stored `who` (D7); a list holding neither still saves.

Run: python3 tests/routing_exit_ip_selftest.py   (0 = pass)
  --plant a|b|c|d|e   plant one defect and expect RED on its own check (exit 0 when caught):
     a  the door accepts two rules to one node with different addresses (one silently decides for both)
     b  a pinned interface is not exempt from the far node's default exit (the pin is overruled, invisibly)
     c  the door accepts an `exit_ip` beside a `who` (a per-person pin that applies to everyone)
     d  no `routing_v` refusal for a stored `exit_ip` (an old tab re-saves the rule without its address)
     e  the plan reads the pin rule by rule instead of once per far node (rule ORDER decides whether it lands)
     f  the plan pins from a rule that names PEOPLE (a hand-edited record does what the door refuses)
"""
import importlib.machinery, importlib.util, json, os, re, sys, tempfile

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
    "a": ('''        if _pins.setdefault(_r["node"], _r["exit_ip"]) != _r["exit_ip"]:''',
          '''        if False:'''),
    "b": ('''        _pd = str((nodes.get(P) or {}).get("default_exit") or "").strip()
        if _pd and not X and not W:''',
          '''        _pd = str((nodes.get(P) or {}).get("default_exit") or "").strip()
        if _pd:'''),
    "c": ('''                    return None, "An address can be chosen only for rules that apply to everyone on this interface.", _dropped_report(dropped)''',
          '''                    pass'''),
    "d": ('''            and body.get("routing_v") != 2 and any(isinstance(r, dict) and ("who" in r or "exit_ip" in r)''',
          '''            and body.get("routing_v") != 2 and any(isinstance(r, dict) and ("who" in r)'''),
    "f": ('''                        and r.get("node") and r.get("who") is None):''',
          '''                        and r.get("node")):'''),
    "e": ('''                smart_items.append((nid, P, S, cat, "exit", dev_n, dev_p, base_p, extra, None, None, "", "", r.get("who"), _pin.get(P, "")))''',
          '''                smart_items.append((nid, P, S, cat, "exit", dev_n, dev_p, base_p, extra, None, None, "", "", r.get("who"), str(r.get("exit_ip") or "").strip()))'''),
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


def fleet(routing_wg0=None, wg9=None, p_default="", p_exits=None):
    """N (n1) meshed with P (n2). `wg9` is N's second interface — a WHOLE-INTERFACE forward, which is how a
    pin reaches P's-default guard today; `p_default` gives P a default exit of its own."""
    n1 = {"name": "node-one", "routing_mode": "kernel",
          "ifaces": {"wg0": {"egress_mode": "smart", "routing": routing_wg0 or []}},
          "links": {"n2": {"iface": "swg_n2", "peer_address": "10.255.0.1"}}}
    if wg9 is not None:
        n1["ifaces"]["wg9"] = wg9
    n2 = {"name": "node-two", "routing_mode": "kernel", "ifaces": {"wg0": {}},
          "exits": p_exits or [], "default_exit": p_default,
          "links": {"n1": {"iface": "swg_n1", "peer_address": "10.255.0.0"}}}
    return {"n1": n1, "n2": n2}


def door(rules, prev=(), nodes=None):
    return P._validate_routing(rules, nodes or fleet(), "n1", (), snap=SNAP_N, prev=prev)


def R(targets="203.0.113.0/24", node="n2", **kw):
    return {"enabled": True, "category": "custom", "targets": targets, "action": "exit", "node": node, **kw}


# ── 1. the door ─────────────────────────────────────────────────────────────────────────────────────────
print("[the door]")
c, e, _ = door([R(exit_ip=X1)])
check("a forward rule keeps its exit IP", e is None and c and c[0].get("exit_ip") == X1, (e, c))
check("…and everything else about the rule is stored exactly as before",
      c and c[0].get("action") == "exit" and c[0].get("node") == "n2" and c[0].get("enabled") is True, c)
c0, e0, _ = door([R()])
check("a rule without one stores no `exit_ip` key at all (an older reader sees what it always saw)",
      e0 is None and "exit_ip" not in c0[0], c0)
_, e1, _ = door([R(exit_ip=X1, who={"on": True, "users": ["u1"], "groups": [], "peers": []})])
check("an address beside a selection is refused (exit_ip_who — the per-person pin is cut, §12 C2)",
      isinstance(e1, str) and e1.startswith("An address can be chosen only"), e1)
_, e2, _ = door([R(exit_ip="not-an-address")])
check("a value that is not an IPv4 address is refused", isinstance(e2, str) and "IPv4" in e2, e2)
cD, eD, _ = door([{"enabled": True, "category": "custom", "targets": "203.0.113.0/24", "action": "direct", "exit_ip": X1},
                  {"enabled": True, "category": "custom", "targets": "203.0.113.1/32", "action": "block", "exit_ip": X1}])
check("an address on a rule that is not a forward is dropped, not stored (there is no far node to pin)",
      eD is None and all("exit_ip" not in r for r in cD), cD)
cS, eS, _ = door([R("203.0.113.0/24", exit_ip=X1), R("192.0.2.0/24", exit_ip=X1)])
check("two rules to one node with the SAME address are fine — the pin is interface-wide by design",
      eS is None and [r.get("exit_ip") for r in cS] == [X1, X1], (eS, cS))
_, eC, _ = door([R("203.0.113.0/24", exit_ip=X1), R("192.0.2.0/24", exit_ip=X2)])
check("two rules to one node with DIFFERENT addresses are refused (exit_ip_conflict)", bool(eC), eC)
check("…and the refusal names the node, as a sentence the browser can translate",
      isinstance(eC, dict) and eC.get("error_key") == "Two rules send this interface through {v1} with different addresses."
      and eC.get("error_vars", {}).get("v1") == "node-two" and "node-two" in eC.get("error", ""), eC)
NODES3 = fleet()
NODES3["n3"] = {"name": "node-three", "routing_mode": "kernel", "ifaces": {},
                "links": {"n1": {"iface": "swg_n1", "peer_address": "10.255.0.2"}}}
NODES3["n1"]["links"]["n3"] = {"iface": "swg_n3", "peer_address": "10.255.0.3"}
cT, eT, _ = door([R("203.0.113.0/24", exit_ip=X1), R("192.0.2.0/24", node="n3", exit_ip=X2)], nodes=NODES3)
check("two DIFFERENT nodes with different addresses are fine — the pin is per (interface, node)",
      eT is None and [r.get("exit_ip") for r in cT] == [X1, X2], (eT, cT))
cO, eO, _ = door([R("203.0.113.0/24", exit_ip=X1), R("192.0.2.0/24", enabled=False, exit_ip=X2)])
check("a switched-off rule is not in the conflict — it routes nothing, and refusing would block the edit that fixes it",
      eO is None and cO[1].get("exit_ip") == X2, (eO, cO))
cU, eU, _ = door([R(exit_ip="203.0.113.250")])
check("an address the far node has not reported is ACCEPTED (its snapshot may be missing — the shape is what is checked)",
      eU is None and cU[0].get("exit_ip") == "203.0.113.250", (eU, cU))

# ── 2. the plan ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[the plan]")


def plan(rules, **kw):
    cl, err, _d = P._validate_routing(rules, fleet(**kw), "n1", (), snap=SNAP_N, prev=[])
    assert err is None, err
    return P.cascade_plan(fleet(cl, **kw), SNAPS)


pl = plan([R(exit_ip=X1)])
ex = (pl.get("n2") or {}).get("exit") or []
check("the pin reaches the FAR node as that subnet's exit record egress_ip (`swg-fwd-snat:S --to-source X`)",
      len(ex) == 1 and ex[0]["subnet"] == "10.8.0.0/24" and ex[0]["egress_ip"] == X1, ex)
check("…and nothing else about the record changed", ex and ex[0]["via_iface"] == "swg_n1" and ex[0]["wan_iface"] == "", ex)
pl2 = plan([R("192.0.2.0/24"), R("203.0.113.0/24", exit_ip=X1)])
ex2 = (pl2.get("n2") or {}).get("exit") or []
check("a rule WITHOUT the pin above one with it still lands the address (add_exit keeps the first record — T13's trap, one door along)",
      len(ex2) == 1 and ex2[0]["egress_ip"] == X1, ex2)
pl3 = plan([R("192.0.2.0/24")])
ex3 = (pl3.get("n2") or {}).get("exit") or []
check("a fleet that pins nothing gets `egress_ip: \"\"`, exactly as before this existed", ex3 and ex3[0]["egress_ip"] == "", ex3)


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items()}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


a = json.dumps(strip(pl), sort_keys=True, default=str)
b = json.dumps(strip(plan([R()])), sort_keys=True, default=str)
check("the pinned plan and the unpinned one differ in EXACTLY one field — the exit record's egress_ip (§5.3)",
      a.replace('"egress_ip": "%s"' % X1, '"egress_ip": ""') == b, [x for x in a.split(",") if x not in b.split(",")])

# ── 3. the far node's default exit ──────────────────────────────────────────────────────────────────────
print("\n[the far node's own default exit]")
PX = [{"id": "aabbccdd", "device": "wgx0", "enabled": True, "producer": "adopted", "egress_ip": "", "gw": ""}]
FWD = {"egress_mode": "forward", "egress_node": "n2"}
pd = P.cascade_plan(fleet(wg9=dict(FWD), p_default="aabbccdd", p_exits=PX), SNAPS)
check("CONTROL — an UNPINNED forward arrival leaves P by P's default exit",
      "10.28.0.0/24" in [d["subnet"] for d in (pd.get("n2") or {}).get("devexit") or []], (pd.get("n2") or {}).get("devexit"))
pp = P.cascade_plan(fleet(wg9=dict(FWD, egress_ip=X2), p_default="aabbccdd", p_exits=PX), SNAPS)
check("a PINNED (S, P) is exempt from P's default exit — the operator named an address and it must not be overruled",
      not [d for d in ((pp.get("n2") or {}).get("devexit") or []) if d["subnet"] == "10.28.0.0/24"], (pp.get("n2") or {}).get("devexit"))
check("…and it is the pinned address the exit record carries",
      [e["egress_ip"] for e in (pp.get("n2") or {}).get("exit") or []] == [X2], (pp.get("n2") or {}).get("exit"))
check("…while P's OWN clients keep it either way (the pin is about the arriving subnet, not about P)",
      all("10.9.0.0/24" in [d["subnet"] for d in (x.get("n2") or {}).get("devexit") or []] for x in (pd, pp)),
      [(x.get("n2") or {}).get("devexit") for x in (pd, pp)])
cl4, e4, _ = P._validate_routing([R(exit_ip=X1)], fleet(p_default="aabbccdd", p_exits=PX), "n1", (), snap=SNAP_N, prev=[])
assert e4 is None, e4
ps = P.cascade_plan(fleet(cl4, p_default="aabbccdd", p_exits=PX), SNAPS)
check("a pinned SMART rule's subnet gets no default-exit entry at P either "
      "(today because no smart arrival does — D5; when P3 gives them one, this is what must keep it off a pinned pair)",
      not [d for d in ((ps.get("n2") or {}).get("devexit") or []) if d["subnet"] == "10.8.0.0/24"], (ps.get("n2") or {}).get("devexit"))
check("…and its exit record still carries the pin",
      [e["egress_ip"] for e in (ps.get("n2") or {}).get("exit") or []] == [X1], (ps.get("n2") or {}).get("exit"))

# ⚠️ THE PAIR THE DOOR REFUSES, ALREADY IN THE STORE (hand-edited, or written by some later path that forgets):
# the plan must not quietly do what the door refuses, which here would be pinning the address for EVERYONE the
# interface sends through that node.
# ⚠️ A CIDR, NOT A HOSTNAME. These nodes are IP-only (`routing_mode: kernel`), where a hostname-only rule
# resolves to nothing and is skipped — the plan would then be empty for a reason that has nothing to do with
# what this checks, and the check would pass without ever reaching the branch.
BOTH = [{"enabled": False, "category": "custom", "domains": [], "cidrs": ["203.0.113.0/24"], "action": "exit",
         "node": "n2", "exit_ip": X1, "who": {"on": True, "users": ["u1"], "groups": [], "peers": []}}]
pb = P.cascade_plan(fleet(BOTH), SNAPS)
check("a stored rule carrying BOTH an address and a selection pins nothing (the door refuses that pair — the plan agrees)",
      [e["egress_ip"] for e in (pb.get("n2") or {}).get("exit") or []] == [""], (pb.get("n2") or {}).get("exit"))

# ── 4. the old tab ──────────────────────────────────────────────────────────────────────────────────────
print("\n[the old tab]")
DEPS = {"panel_settings": {}, "node_snaps": SNAPS, "roster_path": os.path.join(TMP, "users.json")}
STORED = door([R(exit_ip=X1)])[0]


def save(body, stored=None):
    rec = {"egress_mode": "smart", "routing": [dict(r) for r in (STORED if stored is None else stored)]}
    err, _drop = P._apply_egress_mode(rec, body, fleet(), "n1", DEPS)
    return err, rec


eOld, _r = save({"egress_mode": "smart", "routing": [R()]})
check("a save WITHOUT routing_v over a stored exit IP is refused (routing_stale, one predicate — §4.2)",
      isinstance(eOld, str) and eOld.startswith("This browser tab is older"), eOld)
eNew, recN = save({"egress_mode": "smart", "routing": [R(exit_ip=X2)], "routing_v": 2})
check("…and the same save from a current tab goes through", eNew is None and recN["routing"][0]["exit_ip"] == X2, (eNew, recN))
eRO, _r2 = save({"routing": [R()]})
check("…including the rule-only save path (no `egress_mode` in the body)", isinstance(eRO, str) and eRO.startswith("This browser tab is older"), eRO)
ePlain, recP = save({"egress_mode": "smart", "routing": [R()]}, stored=door([R()])[0])
check("a list holding neither an address nor people still saves from an old tab (a fleet using none of this notices nothing)",
      ePlain is None, ePlain)
eConf, _r3 = save({"egress_mode": "smart", "routing": [R("203.0.113.0/24", exit_ip=X1), R("192.0.2.0/24", exit_ip=X2)], "routing_v": 2})
check("the conflict is refused through the save helper too, as a translatable sentence",
      isinstance(eConf, dict) and eConf.get("error_key", "").startswith("Two rules send this interface"), eConf)
check("…and its 400 body carries the key and the values (perr_body, not a bare `error`)",
      set(P.perr_body(eConf)) == {"error", "error_key", "error_vars"} and P.perr_body("plain") == {"error": "plain"})

# ── 5. the readers ──────────────────────────────────────────────────────────────────────────────────────
print("\n[the readers]")
src = open(path, encoding="utf-8").read()
check("the wire is unchanged: `exit_ip` is a STORED rule field and never a plan key of its own",
      '"exit_ip"' not in json.dumps(plan([R(exit_ip=X1)]), default=str))
check("the door's refusals are written inline, where the i18n extractor finds them",
      'perr("Two rules send this interface through {v1} with different addresses."' in src)

if PLANT:
    want = {"a": "DIFFERENT addresses", "b": "exempt from P's default", "c": "beside a selection",
            "d": "WITHOUT routing_v", "e": "still lands the address", "f": "pins nothing"}[PLANT]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
