#!/usr/bin/env python3
"""Self-test: a mesh link's S4 fits its MTU — new links are born fitting, and old ones are refitted, on both ends at once.

S4 pads EVERY data packet, so a full-size packet is `mtu + 60 + S4` bytes; over a 1500-byte path anything bigger leaves
as two fragments. Measured on kernel links (.campaign/rigs/awg3-mesh-s4.sh): at MTU 1420, S4 = 47 fragmented every
full-size packet and roughly halved throughput; the swgt fleet runs mesh_mtu 1420 with six links at S4 31–93.

What is pinned here, and why each matters:
  • the ROOM is 1440 − mtu, floored at 0 — and at the default mesh_mtu (1320) every S4 our generator draws already fits,
    so a default fleet is never touched (control);
  • a refit writes ONE value to BOTH ends — two different values would leave the link dead for ever;
  • the operator's stored mesh_awg is never rewritten — only the link — so a mesh_awg over the room cannot loop;
  • a second pass changes nothing (idempotent — this runs on every sync);
  • a link still being made (one end without params) is left to _mesh_make_link.

Hermetic: no network, no panel process. Run: python3 tests/mesh_s4_fit_selftest.py        (0 = pass)
                                           python3 tests/mesh_s4_fit_selftest.py --perturb (must FAIL: no room rule)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

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

if "--perturb" in sys.argv:          # the tree before the fix: no room rule at all
    P.mesh_s4_room = lambda mtu: 10 ** 6
    print("(perturbed: mesh_s4_room ignores the MTU — this run must FAIL)")

TMP = tempfile.mkdtemp(prefix="s4fit.")
def deps(mtu, panel_mesh_awg=None):
    return {"fleet": {"mesh_mtu": mtu}, "panel_settings": {"mesh_awg": panel_mesh_awg or {}},
            "roster_path": os.path.join(TMP, "users.json")}

def s4s(nodes):
    """{pair: (S4 at one end, S4 at the other)} for every link."""
    out = {}
    for a, n in nodes.items():
        for b, lr in (n.get("links") or {}).items():
            if a < b:
                back = nodes[b]["links"][a]
                out[(a, b)] = (n["ifaces"][lr["iface"]]["awg_params"].get("S4"),
                               nodes[b]["ifaces"][back["iface"]]["awg_params"].get("S4"))
    return out

def fleet(link_s4, mtu=1420):
    """Linked nodes shaped like the swgt fleet: {("a","b"): S4, …}, each link's params identical at both ends, the link
    MTU already recorded (as reconcile_mesh's own MTU step leaves it) so a pass that changes nothing can say so."""
    nodes = {}
    for i, ((a, b), s4) in enumerate(sorted(link_s4.items())):
        name = "swg_%08x" % (0x1000 + i)
        params = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "97", "S2": "70", "S3": "72", "S4": str(s4),
                  "H1": "1-16", "H2": "100-115", "H3": "200-215", "H4": "300-315"}
        for x, y, addr in ((a, b, "10.255.0.%d" % (2 * i)), (b, a, "10.255.0.%d" % (2 * i + 1))):
            n = nodes.setdefault(x, {"name": x.upper()})
            n.setdefault("links", {})[y] = {"iface": name, "link_id": name[4:], "subnet": "10.255.0.%d/31" % (2 * i),
                                            "address": addr, "listen_port": 9999 + i}
            n.setdefault("ifaces", {})[name] = {"awg_params": dict(params), "system": True, "link_node": y, "mtu": mtu}
    return nodes

def snaps_of(nodes):   # every link interface reported, so reconcile_mesh's re-stage step has nothing to do
    return {nid: {"interfaces": {lr["iface"]: {} for lr in (n.get("links") or {}).values()}} for nid, n in nodes.items()}

def events():
    p = os.path.join(TMP, "events.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


print("[mesh S4] the room")
check("MTU 1420 leaves 20", P.mesh_s4_room(1420) == 20, P.mesh_s4_room(1420))
check("MTU 1320 (the default mesh_mtu) leaves 120", P.mesh_s4_room(1320) == 120, P.mesh_s4_room(1320))
check("MTU 1440 and above leave 0", P.mesh_s4_room(1440) == 0 and P.mesh_s4_room(1500) == 0)
check("S4 47 does not fit MTU 1420 (swgt's swg_0900e8bd)", not P.mesh_s4_fits(47, 1420))
check("S4 '20' fits MTU 1420 (strings too — records hold both)", P.mesh_s4_fits("20", 1420))
check("S4 100 fits the default MTU 1320", P.mesh_s4_fits(100, 1320))
check("nothing to judge ⇒ fits (never refit on a guess)",
      P.mesh_s4_fits(None, 1420) and P.mesh_s4_fits("x", 1420) and P.mesh_s4_fits(47, "x"))
d = [P.mesh_s4_draw(1420) for _ in range(2000)]
check("a fresh S4 at MTU 1420 is drawn from 15–20", min(d) >= 15 and max(d) <= 20, (min(d), max(d)))
check("a room under 15 is used whole (MTU 1430 → 10; 1440 → 0)", P.mesh_s4_draw(1430) == 10 and P.mesh_s4_draw(1440) == 0)

print("[mesh S4] a NEW link is born fitting")
worst, varied = 0, False
for _ in range(300):
    nodes = {"a": {"name": "A"}, "b": {"name": "B"}}
    P.reconcile_mesh(nodes, {}, deps(1420))
    (x, y), = s4s(nodes).values()
    worst = max(worst, int(x)); varied = varied or x != y
check("300 new links at MTU 1420: every S4 ≤ 20", worst <= 20, worst)
check("…and the two ends always agree", not varied)
seen_big = False
for _ in range(300):
    nodes = {"a": {"name": "A"}, "b": {"name": "B"}}
    P.reconcile_mesh(nodes, {}, deps(1320))
    (x, _y), = s4s(nodes).values()
    seen_big = seen_big or int(x) > 20
check("control: at MTU 1320 the generator is untouched (some S4 > 20 appear)", seen_big)
nodes = {"a": {"name": "A", "mesh_awg": {"S4": "50", "S1": "60"}}, "b": {"name": "B"}}
P.reconcile_mesh(nodes, {}, deps(1420))
(x, y), = s4s(nodes).values()
check("a node's mesh_awg with S4 50 still yields a fitting LINK at MTU 1420", int(x) <= 20 and x == y, (x, y))
check("…and the operator's stored mesh_awg is not rewritten", nodes["a"]["mesh_awg"] == {"S4": "50", "S1": "60"},
      nodes["a"]["mesh_awg"])

print("[mesh S4] existing links are refitted — the swgt fleet (mesh_mtu 1420)")
swgt = {("msk", "nixos"): 93, ("msk", "svo"): 47, ("hel", "msk"): 31, ("nixos", "svo"): 44, ("hel", "nixos"): 55,
        ("hel", "svo"): 67}
nodes = fleet(swgt)
ev0 = len(events())
changed = P.reconcile_mesh(nodes, snaps_of(nodes), deps(1420))
after = s4s(nodes)
check("the pass reports a change (so the caller persists it)", changed is True)
check("every link now fits (S4 ≤ 20)", all(int(x) <= 20 for x, _ in after.values()), after)
check("both ends of every link hold the SAME value", all(x == y for x, y in after.values()), after)
check("one activity-log line per refitted link (6)", len(events()) - ev0 == 6, len(events()) - ev0)
check("…naming both nodes and the change", any("S4 47 →" in (e.get("detail") or "") and "MSK" in (e.get("name") or "")
                                               for e in events()), events()[-6:])
again = P.reconcile_mesh(nodes, snaps_of(nodes), deps(1420))
check("a second pass changes nothing (runs on every sync)", again is False and s4s(nodes) == after, (again, s4s(nodes)))
ctl = fleet(swgt, mtu=1320)
before = s4s(ctl)
check("control: the same fleet at the default MTU 1320 is left alone",
      P.reconcile_mesh(ctl, snaps_of(ctl), deps(1320)) is False and s4s(ctl) == before, s4s(ctl))
half = fleet({("a", "b"): 93})
half["b"]["ifaces"][half["b"]["links"]["a"]["iface"]]["awg_params"] = {}
P.reconcile_mesh(half, snaps_of(half), deps(1420))
check("a link with one end still unparametrised is left to _mesh_make_link",
      half["a"]["ifaces"][half["a"]["links"]["b"]["iface"]]["awg_params"]["S4"] == "93")
mix = fleet({("a", "b"): 18})
mix["b"]["ifaces"][mix["b"]["links"]["a"]["iface"]]["awg_params"]["S4"] = "47"
P.reconcile_mesh(mix, snaps_of(mix), deps(1420))
(x, y), = s4s(mix).values()
check("ends that disagree (one over the room) are set to one fitting value", x == y and int(x) <= 20, (x, y))

print("\n" + ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
