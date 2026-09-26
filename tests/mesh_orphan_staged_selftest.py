#!/usr/bin/env python3
"""Self-test — a mesh link the panel asked to delete is not reported as an orphan.

`orphan_mesh_links` is the backstop for `swg_*` links no panel claims any more (a peer node deleted while the node
missed the request, a box moved between panels). The panel's own teardown — mesh on demand retiring an unused pair,
or any ordinary link removal — drops the link from `owned_ifaces` AND names it in `delete` in the same reply, so the
backstop listed it too and the node printed "dropping link(s) this panel does not claim (its peer node is gone, or
this node moved panels)". MEASURED in the 1.8.8 qualification: every on-demand retirement printed it on both ends,
naming a peer that was alive and a panel that had not changed. The link is still deleted (by request); the line now
names only real leftovers.

The real `orphan_mesh_links` runs with `run` stubbed (no wg/awg on the box) and `_persist_config` recording. No root.

Run: python3 tests/mesh_orphan_staged_selftest.py      (0 = pass)
     --perturb   the staged names back in the result (the shipped backstop) → RED
"""
import copy, importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    a = "    return sorted(out - {x for x in (staged or ()) if isinstance(x, str)})\n"
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    return sorted(out)\n")
tmp = tempfile.mkdtemp(prefix="mesh-orphan-")
path = os.path.join(tmp, "noded.py")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded_mesh_orphan", path)
spec = importlib.util.spec_from_loader("swgnoded_mesh_orphan", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if not ok else ""))
    if not ok:
        FAILS.append(name)

class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err

persisted = []
N.run = lambda cmd, *a, **k: R(1)                       # no wg/awg here: the live scan finds nothing
N._persist_config = lambda cfg: persisted.append(copy.deepcopy(cfg))

BASE = {"interfaces": {"wg0": {"cmd": ["wg"]}, "swg_live": {"cmd": ["awg"]}, "swg_retired": {"cmd": ["awg"]},
                       "swg_leftover": {"cmd": ["wg"]}}}
OWNED = ["wg0", "swg_live"]

print("[a link the panel is deleting is not an orphan]")
cfg = copy.deepcopy(BASE)
got = N.orphan_mesh_links(cfg, OWNED, ["swg_retired"])
check("a retired link named in `delete` is left out; a real leftover is still reported", got == ["swg_leftover"], got)
check("…and nothing is removed from the registry here (the delete path does that)", sorted(cfg["interfaces"]) == sorted(BASE["interfaces"]), cfg)

print("\n[the backstop itself is unchanged]")
check("no `delete` in the reply → every unclaimed swg_* is reported", N.orphan_mesh_links(copy.deepcopy(BASE), OWNED, None) == ["swg_leftover", "swg_retired"])
check("an older caller (two arguments) → the same", N.orphan_mesh_links(copy.deepcopy(BASE), OWNED) == ["swg_leftover", "swg_retired"])
check("`owned_ifaces` absent → reap nothing", N.orphan_mesh_links(copy.deepcopy(BASE), None, ["swg_retired"]) == [])
check("`owned_ifaces` empty → reap nothing", N.orphan_mesh_links(copy.deepcopy(BASE), [], []) == [])
check("a user interface the panel does not own is not a mesh orphan", "wg0" not in N.orphan_mesh_links(copy.deepcopy(BASE), ["swg_live"], []))
got = N.orphan_mesh_links(copy.deepcopy(BASE), OWNED, ["swg_retired", {"odd": 1}, None, 7])
check("a malformed `delete` entry is ignored, not a crash", got == ["swg_leftover"], got)

print("\n[the sync loop hands the reply's `delete` list over]")
check("main() passes reply.get(\"delete\") as `staged`",
      bool(re.search(r'_orph = orphan_mesh_links\(node_cfg, reply\.get\("owned_ifaces"\), reply\.get\("delete"\)\)', src)))
check("…and still deletes both the requested and the orphaned names",
      "dl = delete_ifaces(node_cfg, list(reply.get(\"delete\") or []) + _orph, agent, sudo)" in src)

print("\nFAIL (%d)" % len(FAILS) if FAILS else "\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
