#!/usr/bin/env python3
"""Self-test: a custom list never takes an id a rule already means something by (operator 2026-10-17).

A rule names its custom list by id in `category`. So a list saved with the id "all" was stored as the catch-all — every
rule naming it became "Everything else" — "custom" / "tld" are read before any list, and a curated preset's id ("google") is that preset. The browser sends no id for a new list, so only an API caller can
send one; the save mints such an id the way it mints a duplicate's and reports it (`id_reserved`). A list ALREADY stored
under a curated preset's id keeps it (lists are looked up before presets, so its rules route by it; re-minting would
re-point them); one stored as "all" / "custom" / "tld" is re-minted on every save (dead, or for "all" read two ways). An id
shaped like an inline rule's set id (custom_<hex>) is kept, new or stored: a list's id never reaches a node. Driven through api() as the browser drives it.

Run:  python3 tests/custom_list_reserved_id_selftest.py   (exit 0 = all pass)
  --perturb       the reserved-id check is taken out of the save; expects RED (exit 0 when caught)
  --perturb-was   a list already stored under a curated preset's id is re-minted too (its rules re-pointed); expects RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB_WAS = "--perturb-was" in sys.argv
PERTURB = "--perturb" in sys.argv or PERTURB_WAS
ANCHOR, PUT = (("or (lid in SMART_CATEGORIES and lid not in _cl_was)", "or lid in SMART_CATEGORIES") if PERTURB_WAS
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

reserved = ["all", "ALL", "custom", "tld", curated]
kept = ["cl_shop", "my_list", "customers", "customs_ru", "custom_0123456789"]   # a list's id never reaches a node
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
print("[a list ALREADY stored: a curated id keeps it (its rules route by it); all / custom / tld do not]")
_st = [L(0, curated), L(1, "all"), L(2, "tld"), L(3, "custom_0123456789")]
st2, by2, drop2 = save(_st, stored=_st)
check("a stored %r list re-saved keeps its id, nothing said" % curated,
      st2 == 200 and by2.get("List 0") == curated and not any(d.get("entry") == curated for d in drop2), (by2, drop2))
check("a stored \"all\" list is re-minted and said — every reader takes \"all\" as the catch-all",
      by2.get("List 1", "").startswith("cl_") and {"entry": "all", "reason": "id_reserved"} in drop2, (by2, drop2))
check("…and so is a stored \"tld\" (a rule naming it is read as the tld grammar, never the list)",
      by2.get("List 2", "").startswith("cl_") and {"entry": "tld", "reason": "id_reserved"} in drop2, (by2, drop2))
check("a stored custom_<10 hex> list keeps its id — its rules route by it, and re-minting would orphan them",
      by2.get("List 3") == "custom_0123456789" and not any(d.get("entry") == "custom_0123456789" for d in drop2), (by2, drop2))

if PERTURB:
    print("\nperturbed: " + ("CAUGHT (%d red)" % len(FAIL) if FAIL else "NOT CAUGHT"))
    sys.exit(0 if FAIL else 1)
print(("\n✗ %d failed" % len(FAIL)) if FAIL else "\n✓ a custom list never takes a reserved id")
sys.exit(1 if FAIL else 0)
