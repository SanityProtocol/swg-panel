#!/usr/bin/env python3
"""Self-test — A LIST ROUTED ONLY BY A WDTT/csqtt SERVER IS STILL ROUTED.

An interface, a WDTT instance and a csqtt instance all carry the SAME routing block — `_apply_egress_mode`'s
docstring says exactly that, and four walkers in the panel already iterate `("ifaces", "wdtt", "csqtt")`.
`routed_catalog_cats` iterated `ifaces` alone, so a category named ONLY by a csqtt or WDTT server was
invisible to every one of its callers:

  · `cat_sizes` omitted it, so the Routing-lists screen drew the row GREYED, with no size and no capability
    badges — for a list the node is actively routing. That is the reported symptom.
  · `provider_update_all` skipped it, so it was never re-fetched from its source again.
  · `lists_gc` did not find it in `live`, so the panel DELETED a resolved list a running interface was
    routing, and the node had nothing left to pull.

MEASURED on msk-main: `mc:spacex` is named by csqtt1 and by nothing else, and it was the only greyed row on
the screen. Every other list had a second way in — an interface's rule (`mc:cloudflare`, `mc:ookla-speedtest`
on awg2), another node's interface (`mc:tld-ru` on nixos/awg0), or the curated set (`meta`, `google`).
That is why one row and not six: the bug needs a category with no second path.

Run: python3 tests/routed_cats_families_selftest.py      (0 = pass)
     --perturb   walks `ifaces` alone again and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()
_ANCH = '''        for _src in ("ifaces", "wdtt", "csqtt"):
            for ifo in (n.get(_src) or {}).values():
                for r in ((ifo or {}).get("routing") or []):'''
assert SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
path = PANEL
if PERTURB:                                   # the shipped walker: interfaces only
    SRC = SRC.replace(_ANCH, '''        for _src in ("ifaces",):
            for ifo in (n.get(_src) or {}).values():
                for r in ((ifo or {}).get("routing") or []):''')
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="routedcats-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(path, "swgpanel")
if PERTURB:
    os.unlink(path)

# msk-main's real shape, trimmed: the cats that DO have a second path, and the one that does not.
NODES = {"n1": {
    "ifaces": {"awg2": {"routing": [{"category": "mc:cloudflare"}, {"category": "mc:ookla-speedtest"}]},
               "wg1":  {"routing": [{"category": "custom"}]}},
    "csqtt": {"csqtt1": {"egress_mode": "smart",
                         "routing": [{"category": "mc:tld-ru"}, {"category": "mc:cloudflare"},
                                     {"category": "meta"}, {"category": "google"},
                                     {"category": "mc:spacex"}, {"category": "custom"}, {"category": "all"}]},
              "csqtt2": {"routing": [{"category": "mc:cloudflare"}]}},
    "wdtt": {"wdtt1": {"routing": []},
             "wdttplus1": {"routing": [{"category": "mc:wdtt-only"}]}},
}}

got = P.routed_catalog_cats(NODES)

print("[1] the category with NO second path — the reported symptom")
check("mc:spacex is routed (csqtt1 names it, nothing else does)", "mc:spacex" in got, sorted(got))
check("mc:wdtt-only is routed (a WDTT server names it)", "mc:wdtt-only" in got, sorted(got))

print("\n[2] the ones that were already visible stay visible")
for c in ("mc:cloudflare", "mc:ookla-speedtest", "mc:tld-ru"):
    check("%s still routed" % c, c in got, sorted(got))

print("\n[3] non-list categories are still not list cats")
for c in ("custom", "all"):
    check("%r is not treated as a panel-served list" % c, c not in got, sorted(got))

print("\n[4] the callers that were silently wrong")
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
i_fn = src.index("def routed_catalog_cats")
check("cat_sizes builds from it", "for _c in routed_catalog_cats(nodes) | set(CURATED_ORDER):" in src)
check("lists_gc builds its live set from it", "for c in routed_catalog_cats(nodes or {}):" in src)
check("provider_update_all uses it", "cats = routed_catalog_cats(nodes_load(nodes_path))" in src)

print("\n[4b] …and the CAPS map asks the same function instead of re-deriving")
# Fixing the shared walker and leaving this second copy behind fixed the row's SIZE and left it GREYED,
# because `catUsableInMode` reads these caps: a list with no caps is "not usable in this mode".
check("smart_caps' in-use set comes from routed_catalog_cats",
      '_inuse_cat = {_c for _c in routed_catalog_cats(nodes) if ":" in _c}' in src)
check("…and there is no second hand-rolled walk left for it",
      'for _if in (_n.get("ifaces") or {}).values():' not in src)

print("\n[5] the trio idiom is used, not re-invented")
check("the function walks all three families",
      '("ifaces", "wdtt", "csqtt")' in src[i_fn:i_fn + 2000])
n = len(re.findall(r'for _?src in \("ifaces", "wdtt", "csqtt"\)', src))
check("and it is not the only walker that does (>=5 now)", n >= 5, n)

print("\n[6] the legacy `ru` -> `ru_net` migration had the same blind spot")
# Anchor on the migration ITSELF, not on a `changed = False` that three functions happen to share — the
# first version of this check grabbed an unrelated one 8000 lines away and reported a real fix as missing.
i_mig = src.index('r["category"] = "ru_net"')
mig = src[max(0, i_mig - 700):i_mig]
check("the migration walks all three families too", '("ifaces", "wdtt", "csqtt")' in mig, mig[-200:])

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
