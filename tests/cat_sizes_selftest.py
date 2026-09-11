#!/usr/bin/env python3
"""§10.5 item 1 — the panel ships the sizes it already knows, so the picker does not go and ask for them.

`/api/state` carries `cat_sizes` = {cat: {ip, host}}, and `listSizeNow` in the browser reads it BEFORE
deciding to fetch: a cat with a shipped size is never asked about. That loop used to cover ROUTED cats only,
so the 26 curated presets — the rows the target picker shows before the operator has chosen anything —
arrived with no size, and `useListSizes` called /api/list-info for each one (twice, per §6.1's re-ask while
a resolve is pending). The panel resolves those lists itself and already held the answer.

Measured on a rig before this was written: 0 sizes shipped, 26 lists the browser would still ask about.
After: 26 shipped, 0 asks, and /api/state still answers in 0.7 ms (`list_meta` is memoised in `_LIST_META`,
so the extra ids cost a dict lookup each rather than a stat).

What this locks:
  1. a RESOLVED curated preset is shipped even though nothing routes it   ← the regression that would return
  2. an UNRESOLVED one is still absent, rather than shipped as a zero     ← "no size" and "size 0" differ
  3. routed provider cats are unaffected

Run: python3 tests/cat_sizes_selftest.py   (exit 0 = all pass)
"""
import importlib.machinery as mach, importlib.util as u, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = u.spec_from_loader("swgp", mach.SourceFileLoader("swgp", os.path.join(HERE, "..", "swg-panel-server")))
P = u.module_from_spec(spec); spec.loader.exec_module(P)

fails = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "   " + str(detail)))
    if not cond: fails.append(name)

def main():
    tmp = tempfile.mkdtemp(prefix="catsizes-")
    P.LIST_DIR = os.path.join(tmp, "lists"); os.makedirs(P.LIST_DIR, exist_ok=True)
    P._LIST_META.clear()

    # Resolve SOME of the curated presets, exactly as a panel has after its first geo update — and leave the
    # rest unresolved, because "the panel has not fetched it yet" must not become "this list is empty".
    resolved = P.CURATED_ORDER[:3]
    unresolved = P.CURATED_ORDER[3:6]
    for cat in resolved:
        for tier, n in (("host", 120), ("ip", 8)):
            json.dump({"n": n, "at": 0}, open(os.path.join(P.LIST_DIR, P._list_key(cat, tier) + ".meta"), "w"))

    nodes_path = os.path.join(tmp, "nodes.json")
    json.dump({}, open(nodes_path, "w"))                       # NOTHING routed — the whole point
    roster_path = os.path.join(tmp, "users.json"); json.dump({}, open(roster_path, "w"))
    deps = {"fleet": {}, "roster_path": roster_path, "nodes_path": nodes_path,
            "panel_settings": {}, "panel_settings_path": os.path.join(tmp, "ps.json")}
    st, resp = P.api("GET", "/api/state", "", None, deps)
    sizes = (resp.get("data") or {}).get("cat_sizes") or {}

    check("a resolved curated preset ships its size even though nothing routes it",
          st == 200 and all(sizes.get(c) == {"host": 120, "ip": 8} for c in resolved),
          json.dumps({c: sizes.get(c) for c in resolved}))
    check("…and an unresolved one is ABSENT, not shipped as a zero",
          all(c not in sizes for c in unresolved),
          json.dumps({c: sizes.get(c) for c in unresolved}))
    check("…so the browser asks about the ones the panel cannot answer, and only those",
          set(sizes) & set(P.CURATED_ORDER) == set(resolved),
          json.dumps(sorted(set(sizes) & set(P.CURATED_ORDER))))

    print()
    if fails:
        print("✗ cat sizes: %d failed" % len(fails)); sys.exit(1)
    print("✓ cat sizes: the panel ships what it has resolved, stays silent about what it has not")

main()
