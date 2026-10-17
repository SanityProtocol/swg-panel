#!/usr/bin/env python3
"""Self-test: a custom list never takes an id a rule already means something by (operator 2026-10-17).

A rule names its custom list by id in `category`. So a list saved with the id "all" was stored as the catch-all — every
rule naming it became "Everything else" — "custom…" collides with an inline rule's own set id (custom_cat_id), and a
curated preset's id ("google") with that preset. The SPA mints `cl_<name>`, so only an API caller can send one; the save
mints such an id the way it mints a duplicate's. Driven through api() as the browser drives it.

Run:  python3 tests/custom_list_reserved_id_selftest.py   (exit 0 = all pass)
  --perturb   the reserved-id check is taken out of the save; expects RED (exit 0 when caught)
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB = "--perturb" in sys.argv
ANCHOR = ' or lid in SMART_CATEGORIES or lid.startswith("custom"):'

path = os.path.abspath(SERVER)
if PERTURB:
    src = open(path, encoding="utf-8").read()
    if src.count(ANCHOR) != 1:
        print("✗ perturbation anchor missing — this run would FALSE-PASS")
        sys.exit(2)
    path = os.path.join(tempfile.mkdtemp(), "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(ANCHOR, ":"))
_l = importlib.machinery.SourceFileLoader("swgpanel_clid", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_clid", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

FAIL = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("   " + str(detail)) if not cond and detail else ""))
    if not cond:
        FAIL.append(name)

td = tempfile.mkdtemp()
tmp, nodes_path, roster_path = (os.path.join(td, f) for f in ("panel-settings.json", "nodes.json", "users.json"))
for f in (nodes_path, roster_path):
    open(f, "w").write("{}\n")
deps = {"fleet": {}, "roster_path": roster_path, "nodes_path": nodes_path,
        "panel_settings": {}, "panel_settings_path": tmp}
curated = next(c for c in P.SMART_CATEGORIES if c != "all")
asked = ["all", "ALL", "custom", "custom_0123456789", curated, "cl_shop", "my_list"]
st, resp = P.api("POST", "/api/panel/settings", "", {"custom_lists": [
    {"id": i, "title": "List %d" % n, "targets": "example%d.com" % n, "enabled": True} for n, i in enumerate(asked)]}, deps)
saved = (resp.get("data") or {}).get("custom_lists", []) if st == 200 else []
by_title = {l["title"]: l["id"] for l in saved}
print("[ids a rule already means something by]")
for n, i in enumerate(asked[:5]):
    got = by_title.get("List %d" % n, "")
    check("a list sent with id %r is stored under a minted cl_ id, not %r" % (i, i.lower()),
          got.startswith("cl_") and got != i.lower(), got)
print("[every other id is kept]")
for n, i in enumerate(asked[5:], start=5):
    check("a list sent with id %r keeps it" % i, by_title.get("List %d" % n) == i, by_title.get("List %d" % n))
check("every list was saved (none dropped)", st == 200 and len(saved) == len(asked), (st, len(saved)))
check("…and no two share an id", len({l["id"] for l in saved}) == len(saved), [l["id"] for l in saved])

if PERTURB:
    print("\nperturbed: " + ("CAUGHT (%d red)" % len(FAIL) if FAIL else "NOT CAUGHT"))
    sys.exit(0 if FAIL else 1)
print(("\n✗ %d failed" % len(FAIL)) if FAIL else "\n✓ a custom list never takes a reserved id")
sys.exit(1 if FAIL else 0)
