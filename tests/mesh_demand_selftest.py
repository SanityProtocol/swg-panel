#!/usr/bin/env python3
"""Self-test: the on-demand mesh links the pairs something routes over, retires the rest after the grace, and leaves a
full-mesh fleet exactly as it was.

A full mesh is N(N-1)/2 links — an interface, a /31 and a port on both ends of every pair, stored in nodes.json (68 MB at
200 nodes; one core full near 77 nodes on a laptop, ~55 on a slow VPS). Only a forward's `egress_node` and a smart exit
rule's `node` route over a link (verified 2026-09-18). docs/MESH-ON-DEMAND-PLAN.md.

  [1]  the mode in force: auto = full through MESH_AUTO_FULL_MAX nodes, demand above; an explicit choice wins
  [2]  the need set is a SUPERSET of every pair cascade_plan routes over — randomized fleets, WDTT and csqtt included
  [3]  demand links exactly the named pairs (a disabled rule names nothing); an explicit full links every pair
  [4]  a retarget links the new pair at once and keeps the old one for the grace; past it the old pair is retired on
       BOTH ends — records, interface overrides, pending creates — and staged for delete; one event names it
  [5]  flipping a target back and forth moves nothing, and restarts the timer
  [6]  a link the operator configured (relay, dial endpoint, dial source) is kept
  [7]  a pair needed again while its old device is still being deleted gets a DIFFERENT interface name
  [8]  a link to a node no longer in the store is retired on the side that exists
  [9]  events: the first MESH_AUTO_FULL_MAX links of a reconcile keep today's per-pair event exactly; beyond, one line
  [10] a steady fleet writes nothing, idle timers running or not
  [11] a pair the last plan routed over is kept even when the configuration does not name it (the backstop)
  [12] SMALL FLEETS FEEL NOTHING: in full mode (auto ≤ the line) the need set is never computed and no timer runs

Hermetic: no network, no panel process.
Run:  python3 tests/mesh_demand_selftest.py              (0 = pass)
      python3 tests/mesh_demand_selftest.py --perturb    every plant must go red on its own check ("N plants, N caught")
"""
import importlib.machinery, importlib.util, json, os, random, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

# One plant per guard: (name, exact source text, replacement, the check that must go red).
PLANTS = [
    ("auto-line", '    return "full" if len(nodes) <= MESH_AUTO_FULL_MAX else "demand"', '    return "demand"',
     "auto: 30 nodes are a full mesh"),
    ("need-smart", '                    if isinstance(r, dict) and r.get("enabled", True) is not False and r.get("action") == "exit":',
     '                    if False:', "every pair the plan routes over is in the need set"),
    ("need-instances", '        recs += [v for k in ("wdtt", "csqtt") for v in (n.get(k) or {}).values() if isinstance(v, dict)]',
     '        recs += []', "…WDTT and csqtt instances included"),
    ("need-pin", '            if ((((lr.get("relay") or {}).get("mode") or "forward") == "relay")',
     '            if False and ((((lr.get("relay") or {}).get("mode") or "forward") == "relay")',
     "a relay-configured link is kept past the grace"),
    ("need-legs", '            want(nid, str((lg or {}).get("peer") or ""))', '            pass',
     "a pair only the last plan names is kept past the grace"),
    ("anchored-mode", '    if deps is not None and mesh_mode_effective(deps, nodes) == "demand":', '    if False:',
     "the node door counts the links a node anchors in the mode in force"),
    ("grace", '        if p in need or now_ - _MESH_IDLE.setdefault(p, now_) < MESH_RETIRE_GRACE_S:', '        if p in need:',
     "the old pair is not retired a second before the grace"),
    ("both-ends", '        for x, y in ((a, b), (b, a)):\n            n = nodes.get(x)', '        for x, y in ((a, b),):\n            n = nodes.get(x)',
     "past the grace the old pair is gone from BOTH ends"),
    ("idle-clear", '    for p in [p for p in _MESH_IDLE if p not in linked or p in need]:', '    for p in []:',
     "flipping back restarts the timer (no early retire)"),
    ("name-pending", '    existing |= set(node.get("delete") or {})', '    existing |= set()',
     "re-needed during its delete: a different interface name"),
    ("events-cap", 'log=made < MESH_LINK_EVENTS_MAX)', 'log=True)', "a mass link: 30 per-pair events + one summary"),
    ("full-untouched", '        _MESH_IDLE.clear()\n        pairs = ((a, b)', '        mesh_need(nodes, deps); _MESH_IDLE.clear()\n        pairs = ((a, b)',
     "full mode never computes the need set"),
]


def perturb_all():
    src = open(SERVER).read()
    caught, bad = 0, []
    for name, old, new, must in PLANTS:
        if src.count(old) != 1:
            bad.append("%s: anchor found %d times (stale plant)" % (name, src.count(old)))
            continue
        with tempfile.NamedTemporaryFile("w", suffix="-swg-panel-server", delete=False) as f:
            f.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_PANEL_SERVER=f.name),
                           capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = "  FAIL " + must in r.stdout
        print("  %-15s %s" % (name, "caught" if red and r.returncode else
                                   ("CRASHED (not a catch)" if "Traceback" in r.stderr else "NOT CAUGHT")))
        if red and r.returncode:
            caught += 1
        else:
            bad.append(name)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    for b in bad:
        print("  ✗ " + b)
    return 0 if caught == len(PLANTS) and not bad else 1


if "--perturb" in sys.argv:
    sys.exit(perturb_all())

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgpanel", SERVER)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="meshdemand.")
ROSTER = os.path.join(TMP, "users.json")
EVP = P.events_path(ROSTER)

def deps(mode=None):
    return {"fleet": {}, "roster_path": ROSTER, "panel_settings": ({"mesh_mode": mode} if mode else {})}

def fleet(n):
    return {"n%02d" % i: {"id": "n%02d" % i, "name": "node%02d" % i, "ifaces": {}} for i in range(n)}

def pairs(nodes):
    return {tuple(sorted((a, b))) for a, n in nodes.items() for b in (n.get("links") or {})}

def events():
    try:
        return [json.loads(l) for l in open(EVP) if l.strip()]
    except OSError:
        return []

def age_all(by):
    for p in list(P._MESH_IDLE):
        P._MESH_IDLE[p] -= by


print("[1] the mode in force")
check("auto: 30 nodes are a full mesh", P.mesh_mode_effective(deps(), fleet(30)) == "full")
check("auto: 31 nodes are on demand", P.mesh_mode_effective(deps(), fleet(31)) == "demand")
check("an explicit full wins at 31, an explicit demand at 3",
      P.mesh_mode_effective(deps("full"), fleet(31)) == "full" and P.mesh_mode_effective(deps("demand"), fleet(3)) == "demand")
check("a value it does not know is auto", P.mesh_mode_effective(deps("sometimes"), fleet(3)) == "full")


print("[2] the need set covers every pair the plan routes over")
rnd = random.Random(7)
def random_fleet(n):
    nodes, snaps = fleet(n), {}
    ids = list(nodes)
    for i, nid in enumerate(ids):
        sifs = {}
        for k, ifn in enumerate(("awg0", "wg1")):
            others = [x for x in ids if x != nid]
            mode = rnd.choice(["direct", "forward", "smart", "smart", None])
            ov = {}
            if mode == "forward":
                ov = {"egress_mode": "forward", "egress_node": rnd.choice(others)}
            elif mode == "smart":
                ov = {"egress_mode": "smart", "routing": [
                    {"category": rnd.choice(["youtube", "telegram", "all"]), "action": rnd.choice(["exit", "exit", "direct", "block"]),
                     "node": rnd.choice(others), **({"enabled": False} if rnd.random() < .2 else {})} for _ in range(rnd.randint(1, 3))]}
            elif mode == "direct":
                ov = {"egress_mode": "direct", "routing": [{"category": "youtube", "action": "exit", "node": rnd.choice(others)}]}
            nodes[nid]["ifaces"][ifn] = ov
            sifs[ifn] = {"meta": {"subnet": "10.%d.%d.0/24" % (20 + k, i), "address": "10.%d.%d.1/24" % (20 + k, i)}, "peers": []}
        others = [x for x in ids if x != nid]
        nodes[nid]["wdtt"] = {"wdtt0": {"wg_addr": "10.40.%d.1/24" % i, "egress_mode": "forward", "egress_node": rnd.choice(others)}} \
            if rnd.random() < .3 else {}
        nodes[nid]["csqtt"] = {"csqtt1": {"tun_addr": "10.41.%d.1/24" % i, "egress_mode": "smart",
                                          "routing": [{"category": "all", "action": "exit", "node": rnd.choice(others)}]}} \
            if rnd.random() < .3 else {}
        snaps[nid] = {"interfaces": sifs}
    return nodes, snaps
missing, used_total, inst_used = [], 0, 0
for trial in range(40):
    nodes, snaps = random_fleet(10)
    P.reconcile_mesh(nodes, snaps, deps("full"))        # every pair linked, so the plan can route over any of them
    plans = P.cascade_plan(nodes, snaps, {})
    used = {frozenset((nid, lg["peer"])) for nid, pl in plans.items() for lg in (pl.get("_legs") or [])}
    inst_used += sum(1 for nid, pl in plans.items() for lg in (pl.get("_legs") or [])
                     if lg["subnet"].startswith(("10.40.", "10.41.")))
    need = P.mesh_need(nodes, deps())                     # config alone — no cas_legs
    used_total += len(used)
    missing += [sorted(p) for p in used - need]
check("control: the random fleets route over many pairs (%d legs' pairs)" % used_total, used_total > 100, used_total)
check("every pair the plan routes over is in the need set", not missing, missing[:5])
check("…WDTT and csqtt instances included", inst_used > 5 and not missing, inst_used)


print("[3] demand links exactly the named pairs")
nodes = fleet(35)
nodes["n01"]["ifaces"]["wg0"] = {"egress_mode": "forward", "egress_node": "n05"}
nodes["n02"]["ifaces"]["awg0"] = {"egress_mode": "smart", "routing": [{"category": "youtube", "action": "exit", "node": "n05"},
                                                                     {"category": "all", "action": "exit", "node": "n07", "enabled": False},
                                                                     {"category": "telegram", "action": "direct", "node": "n08"}]}
nodes["n03"]["wdtt"] = {"wdtt0": {"wg_addr": "10.66.0.1/24", "egress_mode": "forward", "egress_node": "n08"}}
nodes["n04"]["csqtt"] = {"csqtt1": {"tun_addr": "10.67.0.1/24", "egress_mode": "smart",
                                    "routing": [{"category": "all", "action": "exit", "node": "n09"}]}}
nodes["n06"]["ifaces"]["wg0"] = {"egress_mode": "direct", "routing": [{"category": "all", "action": "exit", "node": "n10"}]}
d = deps()
P.reconcile_mesh(nodes, {}, d)
check("35 nodes on auto link exactly the four named pairs (a disabled rule and a direct interface's stored rules name nothing)",
      pairs(nodes) == {("n01", "n05"), ("n02", "n05"), ("n03", "n08"), ("n04", "n09")}, sorted(pairs(nodes)))
full = fleet(35); P.reconcile_mesh(full, {}, deps("full"))
check("…while an explicit full links all 595 pairs", len(pairs(full)) == 595, len(pairs(full)))
check("the node door counts the links a node anchors in the mode in force (demand: n01 anchors 1, full: 33)",
      P._mesh_anchored(nodes, d).get("n01") == 1 and P._mesh_anchored(nodes).get("n01") == 33,
      (P._mesh_anchored(nodes, d).get("n01"), P._mesh_anchored(nodes).get("n01")))


print("[4] a retarget: the new pair at once, the old one after the grace, on both ends")
old01 = nodes["n01"]["links"]["n05"]["iface"]; old05 = nodes["n05"]["links"]["n01"]["iface"]
nodes["n01"]["ifaces"]["wg0"]["egress_node"] = "n06"
P.reconcile_mesh(nodes, {}, d)
check("retargeted: n01–n06 is linked at once, n01–n05 is still there", {("n01", "n06"), ("n01", "n05")} <= pairs(nodes),
      sorted(pairs(nodes)))
age_all(P.MESH_RETIRE_GRACE_S - 5)
P.reconcile_mesh(nodes, {}, d)
check("the old pair is not retired a second before the grace", ("n01", "n05") in pairs(nodes), sorted(pairs(nodes)))
ev0 = len(events())
age_all(10)
changed = P.reconcile_mesh(nodes, {}, d)
check("past the grace the old pair is gone from BOTH ends",
      "n05" not in nodes["n01"].get("links", {}) and "n01" not in nodes["n05"].get("links", {}), (nodes["n01"].get("links"), nodes["n05"].get("links")))
check("…its interfaces are staged for delete on both ends, their overrides and pending creates gone",
      old01 in nodes["n01"].get("delete", {}) and old05 in nodes["n05"].get("delete", {})
      and old01 not in nodes["n01"].get("ifaces", {}) and old05 not in nodes["n05"].get("ifaces", {})
      and old01 not in nodes["n01"].get("create", {}) and old05 not in nodes["n05"].get("create", {}),
      (nodes["n01"].get("delete"), list(nodes["n01"].get("ifaces", {}))))
check("…the other links are untouched", {("n01", "n06"), ("n02", "n05"), ("n03", "n08"), ("n04", "n09")} == pairs(nodes),
      sorted(pairs(nodes)))
new_ev = events()[ev0:]
check("…the reconcile says it changed something, with one event naming the pair, the count and the mode",
      changed is True and [e.get("verb") for e in new_ev] == ["Removed unused mesh links"]
      and new_ev[0].get("kind") == "node" and new_ev[0].get("name") == "node01 ↔ node05"
      and new_ev[0].get("detail_key") == "{count} · on demand, {nodes}"
      and new_ev[0].get("detail_vars", {}).get("count") == {"n": 1, "noun": "link"}, new_ev)


print("[5] flipping a target back and forth moves nothing")
nodes["n02"]["ifaces"]["awg0"]["routing"][0]["node"] = "n11"          # n02–n05 unneeded: its timer starts
P.reconcile_mesh(nodes, {}, d)
age_all(P.MESH_RETIRE_GRACE_S - 5)
nodes["n02"]["ifaces"]["awg0"]["routing"][0]["node"] = "n05"          # …and back, just before the grace
P.reconcile_mesh(nodes, {}, d)
nodes["n02"]["ifaces"]["awg0"]["routing"][0]["node"] = "n11"          # …and away again
P.reconcile_mesh(nodes, {}, d)
age_all(10)
P.reconcile_mesh(nodes, {}, d)
check("flipping back restarts the timer (no early retire)", ("n02", "n05") in pairs(nodes), sorted(pairs(nodes)))


print("[6] a link the operator configured is kept")
cfg = fleet(35)
for a, b, extra in (("n20", "n21", {"relay": {"mode": "relay"}}), ("n22", "n23", {"dial_endpoint": "203.0.113.9"}),
                    ("n24", "n25", {"dial_src": "198.51.100.4"}), ("n26", "n27", {"relay": {"mode": "forward"}})):
    cfg[a]["ifaces"]["wg0"] = {"egress_mode": "forward", "egress_node": b}
P.reconcile_mesh(cfg, {}, deps())
for a, b, extra in (("n20", "n21", {"relay": {"mode": "relay"}}), ("n22", "n23", {"dial_endpoint": "203.0.113.9"}),
                    ("n24", "n25", {"dial_src": "198.51.100.4"}), ("n26", "n27", {"relay": {"mode": "forward"}})):
    cfg[a]["links"][b].update(extra)
    cfg[a]["ifaces"]["wg0"] = {}                                      # nothing routes over it any more
dc = deps()
P.reconcile_mesh(cfg, {}, dc)
age_all(P.MESH_RETIRE_GRACE_S + 1)
P.reconcile_mesh(cfg, {}, dc)
check("a relay-configured link is kept past the grace", ("n20", "n21") in pairs(cfg), sorted(pairs(cfg)))
check("…and one with a dial endpoint, and one with a dial source", {("n22", "n23"), ("n24", "n25")} <= pairs(cfg), sorted(pairs(cfg)))
check("control: a link whose relay is plain forward is retired like any other", ("n26", "n27") not in pairs(cfg), sorted(pairs(cfg)))


print("[7] needed again while its old device is still being deleted")
pend01 = set(nodes["n01"].get("delete", {}))
nodes["n01"]["ifaces"]["wg0"]["egress_node"] = "n05"
P.reconcile_mesh(nodes, {}, d)
new01 = nodes["n01"]["links"]["n05"]["iface"]; new05 = nodes["n05"]["links"]["n01"]["iface"]
check("re-needed during its delete: a different interface name",
      new01 != old01 and new05 != old05 and old01 in nodes["n01"]["delete"] and old05 in nodes["n05"]["delete"],
      (old01, new01, old05, new05))
check("…and the node is asked to create the new one", new01 in nodes["n01"].get("create", {}), list(nodes["n01"].get("create", {})))


print("[8] a link to a node that is no longer in the store")
g = fleet(35)
g["n01"]["links"] = {"gone": {"iface": "swg_deadbeef", "link_id": "deadbeef", "subnet": "10.255.9.0/31", "address": "10.255.9.0",
                              "peer_address": "10.255.9.1", "listen_port": 9999, "psk": "x", "role": "x"}}   # a real record's shape
g["n01"]["ifaces"]["swg_deadbeef"] = {"system": True, "link_node": "gone"}
dg = deps()
P.reconcile_mesh(g, {}, dg)
age_all(P.MESH_RETIRE_GRACE_S + 1)
P.reconcile_mesh(g, {}, dg)
check("…is retired on the side that exists", not g["n01"].get("links") and "swg_deadbeef" in g["n01"].get("delete", {}),
      (g["n01"].get("links"), g["n01"].get("delete")))


print("[9] events")
ev0 = len(events())
m = fleet(25); P.reconcile_mesh(m, {}, deps("full"))                  # a switch to full: 300 links at once
new_ev = events()[ev0:]
check("a mass link: 30 per-pair events + one summary",
      [e.get("verb") for e in new_ev].count("Linked node") == 30
      and [(e.get("verb"), (e.get("detail_vars") or {}).get("count")) for e in new_ev if e.get("verb") != "Linked node"]
      == [("Linked more node pairs", {"n": 270, "noun": "link"})],
      [(e.get("verb"), e.get("detail_vars")) for e in new_ev][-3:])
s29 = fleet(29); P.reconcile_mesh(s29, {}, deps())
ev0 = len(events())
s29["n29"] = {"id": "n29", "name": "node29", "ifaces": {}}          # the 30th node enrols: still a full mesh under auto
P.reconcile_mesh(s29, {}, deps())
new_ev = events()[ev0:]
check("an enrolment into any full mesh auto keeps logs what it always did: 29 × Linked node, no summary",
      [e.get("verb") for e in new_ev] == ["Linked node"] * 29, [e.get("verb") for e in new_ev])


print("[10] a steady fleet writes nothing")
st = fleet(35)
st["n01"]["ifaces"]["wg0"] = {"egress_mode": "forward", "egress_node": "n05"}
ds = deps()
P.reconcile_mesh(st, {}, ds)
snaps_st = {nid: {"interfaces": {lr["iface"]: {} for lr in (n.get("links") or {}).values()}} for nid, n in st.items()}
P.reconcile_mesh(st, snaps_st, ds)
check("a second pass changes nothing", P.reconcile_mesh(st, snaps_st, ds) is False)
st["n01"]["ifaces"]["wg0"]["egress_node"] = "n06"
P.reconcile_mesh(st, snaps_st, ds)
snaps_st = {nid: {"interfaces": {lr["iface"]: {} for lr in (n.get("links") or {}).values()}} for nid, n in st.items()}
P.reconcile_mesh(st, snaps_st, ds)
check("…nor with an idle timer running", P.reconcile_mesh(st, snaps_st, ds) is False and P._MESH_IDLE, dict(P._MESH_IDLE))


print("[11] the backstop: what the last plan routed over is kept")
b = fleet(35)
b["n10"]["ifaces"]["wg0"] = {"egress_mode": "forward", "egress_node": "n11"}
db = deps()
P.reconcile_mesh(b, {}, db)
b["n10"]["ifaces"]["wg0"] = {}                                        # the configuration no longer names it…
db["cas_legs"] = {"n10": [{"subnet": "10.20.0.0/24", "peer": "n11", "mark": 7000, "mode": "forward"}]}   # …the plan did
P.reconcile_mesh(b, {}, db)
age_all(P.MESH_RETIRE_GRACE_S + 1)
P.reconcile_mesh(b, {}, db)
check("a pair only the last plan names is kept past the grace", ("n10", "n11") in pairs(b), sorted(pairs(b)))
db["cas_legs"] = {}
P.reconcile_mesh(b, {}, db)
age_all(P.MESH_RETIRE_GRACE_S + 1)
P.reconcile_mesh(b, {}, db)
check("control: once the plan stops naming it, it is retired", ("n10", "n11") not in pairs(b), sorted(pairs(b)))


print("[12] small fleets feel nothing")
_real_need = P.mesh_need
calls = []
P.mesh_need = lambda *a, **k: (calls.append(1), _real_need(*a, **k))[1]
P._MESH_IDLE.clear()
sm = fleet(30)
sm["n01"]["ifaces"]["wg0"] = {"egress_mode": "forward", "egress_node": "n05"}
P.reconcile_mesh(sm, {}, deps()); P.reconcile_mesh(sm, {}, deps())
check("full mode never computes the need set", not calls, len(calls))
check("…every pair is linked and no timer runs", len(pairs(sm)) == 435 and not P._MESH_IDLE, (len(pairs(sm)), len(P._MESH_IDLE)))
P.mesh_need = _real_need

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    sys.exit(1)
print("OK")
