#!/usr/bin/env python3
"""Self-test: reconcile_mesh drops a pending `create` for a mesh link the node does not own.

A `create` for a `swg_*` interface with no interface record asks the node to build a link that the same reply's
`owned_ifaces` says the panel does not own. The node builds it and `orphan_mesh_links` drops it in the same pass;
the request closes only once the interface is seen, so it repeats every sync, for ever. Live on hel-relay
(2026-10-04): a create left from a replaced link held UDP 10000, and the current link to msk-shadow on the same
port failed "Address already in use" on every pass — re-provisioning could not reach it.
Pinned here:
  • the stale create is dropped, and the pass says it changed something (so the caller persists);
  • a create for a link the node DOES own (its interface record exists) stays — a new or lost link is re-staged;
  • a create for a non-mesh interface (not `swg_*`) is never touched — that is not the mesh's to judge;
  • a second pass changes nothing (this runs on every sync).
Hermetic: no network, no panel process. Run: python3 tests/mesh_stale_create_selftest.py        (0 = pass)
                                           python3 tests/mesh_stale_create_selftest.py --perturb (must FAIL)
"""
import importlib.machinery, importlib.util, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
src = open(SERVER).read()
if "--perturb" in sys.argv:          # the tree before the fix: the stale create is never dropped
    src = src.replace('            for _ifc in [k for k in _cr if str(k).startswith("swg_") and k not in _own]:',
                      '            for _ifc in []:', 1)
    print("(perturbed: no stale-create drop — this run must FAIL)")
TMPD = tempfile.mkdtemp(prefix="meshstale.")
_path = os.path.join(TMPD, "swg-panel-server")
open(_path, "w").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel", _path)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass
deps = {"fleet": {"mesh_mtu": 1320}, "panel_settings": {}, "roster_path": os.path.join(TMPD, "users.json")}
params = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "97", "S2": "70", "S3": "72", "S4": "31",
          "H1": "1-16", "H2": "100-115", "H3": "200-215", "H4": "300-315"}
def link(nodes, a, b, name, i):
    for x, y, addr in ((a, b, "10.255.0.%d" % (2 * i)), (b, a, "10.255.0.%d" % (2 * i + 1))):
        n = nodes[x]
        n.setdefault("links", {})[y] = {"iface": name, "link_id": name[4:], "subnet": "10.255.0.%d/31" % (2 * i),
                                        "address": addr, "listen_port": 10000 + i}
        n.setdefault("ifaces", {})[name] = {"awg_params": dict(params), "system": True, "link_node": y, "mtu": 1320}
# hel-relay's shape: linked to hel-flux (up) and msk-shadow (its end not up yet), plus a create left from a replaced link
nodes = {"relay": {"name": "hel-relay"}, "flux": {"name": "hel-flux"}, "shadow": {"name": "msk-shadow"}}
link(nodes, "relay", "flux", "swg_3f564a39", 2)
link(nodes, "relay", "shadow", "swg_7525d05f", 0)
link(nodes, "flux", "shadow", "swg_8d7baed4", 1)
nodes["relay"]["create"] = {
    "swg_693f8489": {"cmd": ["awg"], "subnet": "10.255.0.4/31", "address": "10.255.0.4/31", "listen_port": 10000},   # stale
    "swg_7525d05f": {"cmd": ["awg"], "subnet": "10.255.0.0/31", "address": "10.255.0.0/31", "listen_port": 10000},   # owned
    "awg5": {"listen_port": 51825},                                                                                 # not mesh
}
snaps = {"relay": {"interfaces": {"swg_3f564a39": {}}},            # relay reports only its hel-flux link
         "flux": {"interfaces": {"swg_3f564a39": {}, "swg_8d7baed4": {}}},
         "shadow": {"interfaces": {"swg_7525d05f": {}, "swg_8d7baed4": {}}}}

print("[mesh] a create for a link the node does not own")
ch = P.reconcile_mesh(nodes, snaps, deps)
cr = nodes["relay"].get("create") or {}
check("the stale swg_693f8489 create is dropped", "swg_693f8489" not in cr, sorted(cr))
check("…and the pass reports a change, so the caller saves it", ch is True, ch)
check("the owned link's create (swg_7525d05f, not reported yet) stays", "swg_7525d05f" in cr, sorted(cr))
check("a non-mesh create (awg5) is never touched", "awg5" in cr, sorted(cr))
check("hel-flux and msk-shadow get no new creates (their links are reported)",
      not nodes["flux"].get("create") and not nodes["shadow"].get("create"),
      (nodes["flux"].get("create"), nodes["shadow"].get("create")))
before = repr(sorted((k, sorted((v.get("create") or {}))) for k, v in nodes.items()))
P.reconcile_mesh(nodes, snaps, deps)
after = repr(sorted((k, sorted((v.get("create") or {}))) for k, v in nodes.items()))
check("a second pass changes no create (this runs on every sync)", before == after, (before, after))

print("[mesh] a link that is being made is never mistaken for a stale one")
nodes2 = {"a": {"name": "A"}, "b": {"name": "B"}}
P.reconcile_mesh(nodes2, {}, deps)                 # full mode: _mesh_make_link builds the a↔b link now
mk = (nodes2["a"].get("create") or {})
check("a freshly made link keeps its create on both ends", any(k.startswith("swg_") for k in mk)
      and any(k.startswith("swg_") for k in (nodes2["b"].get("create") or {})), (sorted(mk), sorted(nodes2["b"].get("create") or {})))
P.reconcile_mesh(nodes2, {}, deps)
check("…and still keeps it on the next pass (its interface record is there)",
      sorted(nodes2["a"].get("create") or {}) == sorted(mk), (sorted(nodes2["a"].get("create") or {}), sorted(mk)))

if FAILS:
    print("mesh_stale_create_selftest: FAIL (%d)" % len(FAILS))
    sys.exit(1)
print("mesh_stale_create_selftest: PASS")
