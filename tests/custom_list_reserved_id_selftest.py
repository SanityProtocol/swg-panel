#!/usr/bin/env python3
"""Self-test: a custom list never takes an id a rule already means something by (operator 2026-10-17).

A rule names its custom list by id in `category`. So a list saved with the id "all" was read two ways — the node routed
the list, the SPA showed its rules as "Everything else" — "custom" / "tld" are read by the validator before any list,
custom_<10 hex> is an inline rule's set id, and a curated preset's id ("google") is that preset to the SPA. The browser
sends no id for a new list, so only an API caller can send one; the save mints such an id the way it mints a duplicate's
and reports it (`id_reserved`).

A list ALREADY stored keeps its id, whatever it is: re-minting it would re-point or orphan the rules naming it. That keeps
a stored "all" read two ways and a stored "custom" / "tld" unreachable, as they were (API-only, none known; the operator's
choice, round 4). This gate checks only that no stored id is touched — not how a rule naming one resolves.
Driven through api() as the browser drives it.

Run:  python3 tests/custom_list_reserved_id_selftest.py   (exit 0 = all pass)
  --perturb       the reserved-id check is taken out of the save; expects RED (exit 0 when caught)
  --perturb-was   a list already stored under a reserved id is re-minted too (its rules re-pointed or orphaned); expects RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB_WAS = "--perturb-was" in sys.argv
PERTURB = "--perturb" in sys.argv or PERTURB_WAS
ANCHOR, PUT = (("_reserved = lid not in _cl_was and (", "_reserved = (") if PERTURB_WAS
               else ("if not lid or lid in seen or _reserved:", "if not lid or lid in seen:"))

path = os.path.abspath(SERVER)
if PERTURB:
    src = open(path, encoding="utf-8").read()
    if src.count(ANCHOR) != 1:
        print("✗ perturbation anchor missing — this run would FALSE-PASS")
        sys.exit(2)
    path = os.path.join(tempfile.mkdtemp(), "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(ANCHOR, PUT))
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
def save(lists, stored=None):
    deps["panel_settings"] = {"custom_lists": stored} if stored else {}
    st, resp = P.api("POST", "/api/panel/settings", "", {"custom_lists": lists}, deps)
    d = resp.get("data") or {}
    return st, {l["title"]: l["id"] for l in d.get("custom_lists", [])}, (d.get("dropped") or {}).get("entries", [])
L = lambda n, i: {"id": i, "title": "List %d" % n, "targets": "example%d.com" % n, "enabled": True}

reserved = ["all", "ALL", "custom", "tld", "custom_0123456789", curated]
kept = ["cl_shop", "my_list", "customers", "customs_ru", "custom_de"]   # custom_<not 10 hex> is no set id
asked = reserved + kept
st, by_title, drop = save([L(n, i) for n, i in enumerate(asked)])
print("[a NEW list sent with an id a rule already means something by]")
for n, i in enumerate(reserved):
    got = by_title.get("List %d" % n, "")
    check("%r is stored under a minted cl_ id" % i, got.startswith("cl_") and got != i.lower(), got)
    check("…and the rename is said (`id_reserved`)", {"entry": i.lower()[:24], "reason": "id_reserved"} in drop, drop)
print("[every other id is kept — only exact collisions are reserved]")
for n, i in enumerate(kept, start=len(reserved)):
    check("%r keeps it" % i, by_title.get("List %d" % n) == i, by_title.get("List %d" % n))
check("every list was saved (none dropped)", st == 200 and len(by_title) == len(asked), (st, len(by_title)))
check("…and no two share an id", len(set(by_title.values())) == len(by_title), by_title)
print("[a list ALREADY stored keeps its id, whatever it is — nothing re-minted, nothing said]")
_st = [L(0, curated), L(1, "all"), L(2, "tld"), L(3, "custom_0123456789")]
st2, by2, drop2 = save(_st, stored=_st)
for n, i in enumerate(l["id"] for l in _st):
    check("a stored %r list re-saved keeps its id, nothing said" % i,
          st2 == 200 and by2.get("List %d" % n) == i and not any(d.get("entry") == i for d in drop2), (by2, drop2))

if PERTURB:
    print("\nperturbed: " + ("CAUGHT (%d red)" % len(FAIL) if FAIL else "NOT CAUGHT"))
    sys.exit(0 if FAIL else 1)
print(("\n✗ %d failed" % len(FAIL)) if FAIL else "\n✓ a custom list never takes a reserved id")
sys.exit(1 if FAIL else 0)
