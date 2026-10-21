#!/usr/bin/env python3
"""Self-test for ports on a routing rule, the panel half (docs/NEVER-BLOCK-AND-PORT-RULES-PLAN.md B.2–B.4, B.7; 1.8.11 S6).

An interface rule may carry `ports: {on, proto, list}`. What the panel has to get right, each on the real functions:

  [1] THE GRAMMAR   — `ports_clean` answers every vector in tests/ports_vectors.json (the SPA's `portsClean` reads the same
                      file), and the node's `_ports_spans` reads every canonical answer back.
  [2] THE DOOR      — `_validate_routing` stores the guarded shape: `enabled` false, `who.on` false, the switch in `ports.on`;
                      refuses ports on "Everything else", on a node's default list, and a list that does not read; a rule
                      without ports is stored exactly as before. `rule_on` reads `ports.on` first.
  [3] THE OLD TAB   — D7 numeric: a save without `routing_v` 3 over a stored port rule is refused (an absent or non-int
                      `routing_v` reads as 0 — never a 500); a v3 save goes through, also over a `who` rule.
  [4] THE PLAN      — the entry carries `ports`; "ports refine a destination": a port entry goes above the port-less entry of
                      the same subnet, category and people, in either row order, and nothing else moves; a UDP-only exit to a
                      node adds no relay leg; a stored `ports` that does not read lowers nothing.
  [5] THE SYNC      — a node that does not report `smartroute.ports` gets no port entry (and the categories only they used
                      leave the channels); its card says it needs an update; a capable node gets them; a slice without a port
                      entry is handed back as it was.
  [6] NO PORTS, NO CHANGE — on a fleet without ports, cascade_plan and the sync slice are byte-identical to the panel the
                      feature was built on (BASE, the commit before S6).
  [7] THE OLD PANEL — the released panel (RELEASED, 1.8.10-beta) emits nothing for a stored port rule, with or without `who`.

Run: python3 tests/port_rules_panel_selftest.py   (0 = pass)
  --plant a|b|c|d|e|f|g   plant one defect and expect RED on its own check (exit 0 when caught):
     a  rule_on ignores `ports` (a port rule's `enabled: false` reads as off: it never lowers)
     b  the door keeps `who.on` live beside ports (a downgraded panel lowers a who+ports rule without its ports)
     c  no reorder (a port-less rule above takes the port rule's ports too)
     d  no withholding (an old node builds the rule for every port)
     e  D7 stays an equality on 2 (a v3 tab is refused over every `who` rule)
     f  a UDP-only exit adds a relay leg
     g  the plan lowers a stored `ports` it cannot read (without its ports — wider than written)
"""
import copy, importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "a": ('''    p = r.get("ports") if isinstance(r, dict) else None
    if isinstance(p, dict):
        return p.get("on") is True
''', ''),
    "b": ('''            if "who" in out:
                out["who"]["on"] = False
''', ''),
    "c": ('''        if sn.pop("_ports", None):
            out, first = [], {}''', '''        if sn.pop("_ports", None) and False:
            out, first = [], {}'''),
    "d": ('''    if not any("ports" in e for e in smart) or (isinstance(_sr, dict) and _sr.get("ports")):
        return my''', '''    return my'''),
    "e": ('''            and any(isinstance(r, dict) and ((_rv < 2 and "who" in r) or (_rv < 3 and "ports" in r))''',
          '''            and any(isinstance(r, dict) and ((_rv != 2 and "who" in r) or (_rv < 3 and "ports" in r))'''),
    "f": ('''            if (S, P, "smart") not in sn["_leg_seen"] and not (isinstance(ports, dict) and ports.get("proto") == "udp"):''',
          '''            if (S, P, "smart") not in sn["_leg_seen"]:'''),
    "g": ('''                    if _pp is None or r.get("category") == "all":
                        return False
                    _pt = {"proto": _pp, "list": _pl}''', '''                    _pt = {"proto": _pp, "list": _pl} if _pp else None'''),
}
TMP = tempfile.mkdtemp(prefix="port-rules-panel-")
BASE = os.environ.get("SWG_PORTS_BASE") or "33a6819b"     # origin/dev before 1.8.11 S6 — the last panel without ports
RELEASED = os.environ.get("SWG_PORTS_RELEASED") or "9c4a59d5"   # 1.8.10-beta, the release a panel may be downgraded to


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


path = PANEL
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
P = load(path, "swgpanel_ports")


def git_show(ref, f):
    r = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (ref, f)], capture_output=True, text=True)
    if r.returncode:
        return None
    p = os.path.join(TMP, "%s-%s" % (ref.replace("/", "_"), f))
    open(p, "w", encoding="utf-8").write(r.stdout)
    return p


ROSTER = {"users": {"u1": {"id": "u1", "name": "Alice"}}, "groups": {},
          "peers": {"p1": {"id": "p1", "user_id": "u1", "title": "phone", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5"}]}}}
SNAP1 = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}}, "smartroute": {"mode": "kernel", "src": 1, "ports": 1}}
SNAP2 = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}}, "smartroute": {"mode": "kernel", "src": 1, "ports": 1}}
SNAPS = {"n1": SNAP1, "n2": SNAP2}


def fleet(routing):
    return {"n1": {"name": "node-one", "routing_mode": "kernel", "ifaces": {"wg0": {"egress_mode": "smart", "routing": routing}},
                   "links": {"n2": {"iface": "swg_n2", "peer_address": "10.255.0.1"}}},
            "n2": {"name": "node-two", "routing_mode": "kernel", "ifaces": {"wg0": {}},
                   "links": {"n1": {"iface": "swg_n1", "peer_address": "10.255.0.0"}}}}


def door(rules, node_scope=False):
    return P._validate_routing(rules, fleet([]), "n1", (), roster=ROSTER, node_scope=node_scope)


G = {"category": "custom", "targets": "203.0.113.0/24"}
WHO = {"on": True, "users": ["u1"], "groups": [], "peers": []}

# ── [1] the grammar ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the grammar — tests/ports_vectors.json")
VEC = json.load(open(os.path.join(HERE, "ports_vectors.json"), encoding="utf-8"))["vectors"]
N = load(NODED, "swgnoded_ports")
bad = []
for proto, raw, want in VEC:
    got = P.ports_clean(proto, raw)
    exp = (want["proto"], want["list"]) if "proto" in want else (None, want["bad"])
    if got != exp:
        bad.append((proto, raw, got, exp))
check("ports_clean answers every vector (%d)" % len(VEC), not bad, bad[:4])
nb = [w for _p, _r, w in VEC if "proto" in w and N._ports_spans(w) is None]
check("…and the node reads every canonical answer back", not nb, nb[:4])
check("the node refuses what the panel never sends (a space, `both` with no port, a bad proto, 0, a non-string)",
      all(N._ports_spans(x) is None for x in ({"proto": "udp", "list": "443, 444"}, {"proto": "both", "list": ""},
                                                {"proto": "sctp", "list": "1"}, {"proto": "udp", "list": "0"}, {"proto": "udp", "list": 443}, "udp")))

# ── [2] the door ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the door")
c, e, _ = door([dict(G, enabled=True, action="exit", node="n2", ports={"on": True, "proto": "udp", "list": "19309, 19302-19308"})])
r0 = (c or [{}])[0]
check("a port rule is stored switched off to every older reader, its switch in `ports.on`, its list canonical",
      e is None and r0.get("enabled") is False and r0.get("ports") == {"on": True, "proto": "udp", "list": "19302-19309"}, (e, c))
check("rule_on reads `ports.on` first", P.rule_on(r0) is True and P.rule_on(dict(r0, ports=dict(r0["ports"], on=False))) is False)
c, e, _ = door([dict(G, enabled=False, action="block", who=WHO, ports={"on": True, "proto": "tcp", "list": ""})])
r1 = (c or [{}])[0]
check("with `who` too: `who.on` is stored off as well (a released panel reads `who.on`), the people kept",
      e is None and r1.get("enabled") is False and r1["who"]["on"] is False and r1["who"]["users"] == ["u1"]
      and r1["ports"] == {"on": True, "proto": "tcp", "list": ""}, (e, c))
check("…and rule_on still answers by `ports.on`", P.rule_on(r1) is True)
c, e, _ = door([dict(G, enabled=False, action="direct", ports={"proto": "udp", "list": "53"})])
check("a `ports` without `on` takes its switch from the rule's own (here: off)", e is None and c[0]["ports"]["on"] is False, (e, c))
_, e, _ = door([{"enabled": True, "category": "all", "action": "direct", "ports": {"on": True, "proto": "udp", "list": "1"}}])
check("refused on “Everything else”", e is not None and "Everything else" in e, e)
_, e, _ = door([dict(G, enabled=True, action="direct", ports={"on": True, "proto": "udp", "list": "1"})], node_scope=True)
check("refused on a node's default list (B.1)", e is not None and "default rules" in e, e)
for pv, why in (({"on": True, "proto": "both", "list": ""}, "Any"), ({"on": True, "proto": "udp", "list": "70000"}, "65535"),
                ({"on": True, "proto": "udp", "list": " ".join(str(i) for i in range(1, 40))}, "32"), ("udp", "65535")):
    _, e, _ = door([dict(G, enabled=True, action="direct", ports=pv)])
    check("refused, and said: %r" % (pv,), e is not None and why in e, e)
c, e, _ = door([dict(G, enabled=True, action="exit", node="n2")])
check("a rule without ports is stored exactly as before", e is None and c == [{"enabled": True, "category": "custom", "action": "exit",
                                                                                "domains": [], "cidrs": ["203.0.113.0/24"], "node": "n2"}], c)

# ── [3] the old tab ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the old tab — routing_v")
deps = {"panel_settings": {}, "node_snaps": SNAPS, "roster_path": os.path.join(TMP, "users.json")}
json.dump(ROSTER, open(deps["roster_path"], "w"))
PR = door([dict(G, enabled=True, action="exit", node="n2", ports={"on": True, "proto": "udp", "list": "443"})])[0][0]
WR = door([dict(G, enabled=False, action="exit", node="n2", who=WHO)])[0][0]


def save(stored, body):
    rec = copy.deepcopy(stored)
    return P._apply_egress_mode(rec, body, fleet([]), "n1", deps)[0], rec


for v in (None, 2, "3", True):
    body = {"egress_mode": "smart", "routing": [PR]}
    if v is not None:
        body["routing_v"] = v
    try:
        err, _a = save({"egress_mode": "smart", "routing": [PR]}, body)
    except Exception as x:
        err = "RAISED %s" % x
    check("routing_v %r over a stored port rule is refused (reload), never a 500" % (v,), err is not None and "older than the panel" in err, err)
err, after = save({"egress_mode": "smart", "routing": [PR, WR]}, {"egress_mode": "smart", "routing": [PR, WR], "routing_v": 3})
check("routing_v 3 saves — over a port rule AND a `who` rule", err is None and after["routing"][0].get("ports"), err)
err, _a = save({"egress_mode": "smart", "routing": [WR]}, {"egress_mode": "smart", "routing": [WR], "routing_v": 2})
check("routing_v 2 still saves over a `who` rule with no port rule stored", err is None, err)

# ── [4] the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the plan")


def plan(rules, snaps=SNAPS):
    return P.cascade_plan(fleet(rules), snaps)


def ents(pl):
    return [e for e in (pl.get("n1") or {}).get("smart", []) if e["subnet"] == "10.8.0.0/24"]


A = dict(G, enabled=True, action="exit", node="n2")
B = dict(G, enabled=False, action="direct", ports={"on": True, "proto": "udp", "list": "19302-19309"})
for order, nm in (([A, B], "port rule below"), ([B, A], "port rule above")):
    es = ents(plan(order))
    check("same targets, %s: the port entry goes first, carrying its ports" % nm,
          len(es) == 2 and es[0].get("ports") == {"proto": "udp", "list": "19302-19309"} and es[0]["action"] == "direct"
          and "ports" not in es[1] and es[0]["category"] == es[1]["category"], es)
Bw = dict(B, who=dict(WHO, on=False))
es = ents(plan([A, Bw]))
check("…not across people: a per-person port rule below a rule for everyone stays below", len(es) == 2 and "ports" not in es[0]
      and es[1].get("src"), es)
O = dict(A, targets="198.51.100.0/24")
Bo = dict(B, targets="203.0.113.0/24, 192.0.2.0/24")
es = ents(plan([A, O, Bo]))
check("…not across categories: different targets keep rule order", [("ports" in e) for e in es] == [False, False, True], es)
B2 = dict(B, ports={"on": True, "proto": "tcp", "list": "443"})
es = ents(plan([A, B, B2]))
check("two port rules of one category both go above, in their own order", [e.get("ports", {}).get("proto") for e in es] == ["udp", "tcp", None], es)
U = dict(A, enabled=False, ports={"on": True, "proto": "udp", "list": "3478"})
pl = plan([U])
check("a UDP-only exit to a node adds no relay leg (the divert is TCP-only)", not (pl.get("n1") or {}).get("_legs"), (pl.get("n1") or {}).get("_legs"))
check("…a TCP one does", (plan([dict(U, ports={"on": True, "proto": "tcp", "list": "443"})]).get("n1") or {}).get("_legs"))
check("…and the mesh link is still needed (mesh_need reads the store)", frozenset(("n1", "n2")) in P.mesh_need(fleet([U]), {"cas_legs": {}}))
check("a stored `ports` that does not read lowers nothing (never wider than written)",
      not ents(plan([dict(A, enabled=False, ports={"on": True, "proto": "udp", "list": "nope"})])))
check("a switched-off port rule lowers nothing", not ents(plan([dict(U, ports=dict(U["ports"], on=False))])))

# ── [5] the sync ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] the sync — withholding")
C = dict(G, targets="192.0.2.0/24", enabled=False, action="direct", ports={"on": True, "proto": "udp", "list": "53"})
my = plan([A, C]).get("n1") or {"smart": []}
old = {"interfaces": SNAP1["interfaces"], "smartroute": {"mode": "kernel", "src": 1}}
w = P.ports_plan_for_node(my, old)
check("a node that does not report `ports` gets no port entry", not [e for e in w["smart"] if "ports" in e] and w["smart"], w["smart"])
check("…and the CIDRs of a category only a port rule used leave with it",
      all(cat in {e["category"] for e in w["smart"]} for cat in (w.get("cidrs") or {})) and len(w.get("cidrs") or {}) == 1, w.get("cidrs"))
check("a node not heard from yet is not sent them either", not [e for e in P.ports_plan_for_node(my, {})["smart"] if "ports" in e])
check("a capable node gets them", P.ports_plan_for_node(my, SNAP1) is my)
nop = plan([A]).get("n1") or {"smart": []}
check("a slice with no port entry is handed back as it was", P.ports_plan_for_node(nop, old) is nop)
iss = [x["error"] for x in P._node_issues(fleet([C])["n1"], old)]
check("the old node's card says it needs an update to route by port", any("node-one needs an update to route by port" in x for x in iss), iss)
check("…a capable node's card, and a silent one's, do not",
      not any("route by port" in x["error"] for x in P._node_issues(fleet([C])["n1"], SNAP1) + P._node_issues(fleet([C])["n1"], {})))
src = open(path, encoding="utf-8").read()
check("the handler withholds after resolving people", "my_plan = ports_plan_for_node(my_plan, snap)" in src)

# ── [6] no ports, no change ─────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] no ports, no change — against the panel before ports (%s)" % BASE)
hp = git_show(BASE, "swg-panel-server")
if hp is None:
    check("the base panel is readable (git show)", False)
else:
    H = load(hp, "swgpanel_head")
    rules = [A, O, dict(A, action="block", targets="192.0.2.0/24"), dict(G, enabled=False, action="direct", who=WHO),
             {"enabled": True, "category": "all", "action": "exit", "node": "n2"}]
    a, b = P.cascade_plan(fleet(rules), SNAPS), H.cascade_plan(fleet(rules), SNAPS)
    ser = lambda x: json.dumps(x, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    check("cascade_plan without ports is byte-identical to the base's", ser(a) == ser(b))
    va, vb = door(rules)[0], H._validate_routing(rules, fleet([]), "n1", (), roster=ROSTER)[0]
    check("…and the door stores the same rules", json.dumps(va, sort_keys=True) == json.dumps(vb, sort_keys=True))
    my_ = P.who_plan_for_node(a["n1"], ROSTER, "n1", SNAP1)
    check("…and the sync slice is the one the base hands the node", ser(P.ports_plan_for_node(my_, SNAP1))
          == ser(H.who_plan_for_node(b["n1"], ROSTER, "n1", SNAP1)))

# ── [7] the released panel ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[7] the released panel (%s) — a stored port rule is off to it" % RELEASED)
mp = git_show(RELEASED, "swg-panel-server")
if mp is None:
    check("the released panel is readable (git show)", False)
else:
    M = load(mp, "swgpanel_main")
    for nm, r in (("a port rule", PR), ("a port rule with `who`", door([dict(G, enabled=True, action="exit", node="n2", who=WHO,
                                                                         ports={"on": True, "proto": "udp", "list": "443"})])[0][0])):
        es = [e for e in (M.cascade_plan(fleet([r]), SNAPS).get("n1") or {}).get("smart", []) if e["subnet"] == "10.8.0.0/24"]
        check("the released panel lowers nothing for %s (never without its ports)" % nm, not es, es)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS)))
if PLANT:
    print("plant %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
