#!/usr/bin/env python3
"""Self-test — A LIST THAT RESOLVED TO ZERO MUST NOT STAY ZERO FOR EVER.

A resolved list is stored as a sorted file plus a meta `{v, n, at}`. `n: 0` was treated as a real answer:
`list_ensure` returned it without kicking a resolve, and `/api/list-info` kicked one only when there was NO
meta at all. So the first build that mis-parsed a list froze that verdict for the life of the install.

MEASURED on the qualification panel. Every MetaCubeX `tld-*` list is written in the `+.<tld>` form, which the
parser did not read as a zone declaration until 3b541de ("lists: every MetaCubeX tld-* list resolved to zero
records and greyed itself out"). A panel that had browsed the catalog once before that fix held
`mc_tld_ru__host.meta = {"n": 0}` — and kept holding it two days and one update after the fix shipped, with
the row greyed out and `disabled` in the catalog, which also takes away the operator's own retry. The code
was right and the answer stayed wrong. (Same shape as an empty catalog index cached as a real one, and a CA
404 stored as a certificate — this tree has now shipped it three times.)

Emptiness and failure are the same non-answer to a caller, so they get the same treatment: re-resolve,
BOUNDED by the `_LIST_FAILED` cooldown that already existed for the failing case — whose own docstring says
it is for "a resolve that finished and produced nothing", which is precisely what it did not cover.

Run: python3 tests/list_empty_reresolve_selftest.py      (0 = pass)
     --perturb   restores `if m and not force: return m` and expects RED.
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_SRC = open(PANEL, encoding="utf-8").read()
_ANCH = "    if m and not force and (_meta_n(m) or list_failed(cat, tier)):\n        return m"
assert _SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    _SRC = _SRC.replace(_ANCH, "    if m and not force:\n        return m")   # the shipped behaviour
    _fd, PANEL = tempfile.mkstemp(suffix=".py", prefix="list-empty-", dir=HERE)
    os.write(_fd, _SRC.encode()); os.close(_fd)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m

P = _load(PANEL, "swgpanel")
if PERTURB:
    os.unlink(PANEL)

TMP = tempfile.mkdtemp(prefix="listheal-")
P.LIST_DIR = TMP

def seed(cat, tier, n):
    """Put a stored answer of `n` records on disk, exactly as _list_commit would."""
    P._LIST_META.pop(cat + "|" + tier, None)
    P._LIST_FAILED.pop(cat + "|" + tier, None)
    body = "".join("d%d.example\n" % i for i in range(n))
    open(P._list_path(cat, tier), "w").write(body)
    json.dump({"v": "x" * 12, "n": n, "at": int(time.time())}, open(P._list_metapath(cat, tier), "w"))

def kicked(cat, tier, produces):
    """Call list_ensure and report whether it actually ran a resolve. `produces` = records the resolve finds."""
    ran = []
    def fake_store(c, t):
        ran.append((c, t))
        seed(c, t, produces)                 # NB: seed clears _LIST_FAILED, so arm-checking happens after
        P._LIST_FAILED.pop(c + "|" + t, None)
    real, P.list_store = P.list_store, fake_store
    try:
        P.list_ensure(cat, tier)
        for _ in range(200):                 # the resolve runs on its own thread
            with P._LIST_LOCK:
                busy = (cat + "|" + tier) in P._LIST_INFLIGHT
            if not busy and ran:
                break
            if not busy and not ran:
                time.sleep(0.005)
                break
            time.sleep(0.005)
        time.sleep(0.02)
    finally:
        P.list_store = real
    return bool(ran)

print("[1] _meta_n — what a stored answer is actually worth")
for m, want in [(None, 0), ({}, 0), ({"n": 0}, 0), ({"n": 11}, 11), ({"n": "11"}, 11),
                ({"n": None}, 0), ({"n": "x"}, 0), ({"v": "abc"}, 0)]:
    got = P._meta_n(m)
    check("_meta_n(%-14r) == %-3r" % (m, want), got == want, got)

print("\n[2] a stored-EMPTY list is not an answer — list_ensure re-resolves it")
seed("mc:tld-ru", "host", 0)
check("n=0 kicks a resolve  (the shipped bug: it did not)", kicked("mc:tld-ru", "host", 11))
check("…and the heal lands: the list now has records", P._meta_n(P.list_meta("mc:tld-ru", "host")) == 11)

print("\n[3] a HEALTHY list still short-circuits — no re-fetch storm")
seed("mc:geolocation-cn", "host", 4210)
check("n>0 does NOT kick a resolve", not kicked("mc:geolocation-cn", "host", 4210))

print("\n[4] the retry is BOUNDED — a resolve that finds nothing arms the cooldown")
seed("mc:really-empty", "host", 0)
ran = []
def _store_zero(c, t):
    ran.append(1)
    seed(c, t, 0)
real, P.list_store = P.list_store, _store_zero
try:
    P.list_ensure("mc:really-empty", "host")
    for _ in range(200):
        with P._LIST_LOCK:
            busy = "mc:really-empty|host" in P._LIST_INFLIGHT
        if not busy:
            break
        time.sleep(0.005)
    time.sleep(0.02)
finally:
    P.list_store = real
check("the resolve ran", bool(ran))
check("a zero result arms _LIST_FAILED (so the next ask waits out the cooldown)",
      P.list_failed("mc:really-empty", "host"), dict(P._LIST_FAILED))
check("the cooldown TTL is finite — it heals by itself", 0 < P._LIST_FAIL_TTL <= 3600, P._LIST_FAIL_TTL)

print("\n[5] ⚠️ THE RE-RESOLVE IS BOUNDED IN list_ensure ITSELF — the hot caller never asked")
# The manifest builder calls list_ensure for every routed category on EVERY node sync (5 s on the fastest
# node in the fleet) and, unlike /api/list-info, consults nothing. With the cooldown checked only in the
# caller, a genuinely-empty routed list would have fetched upstream every five seconds for ever.
seed("mc:hot-empty", "host", 0)
_n = []
def _count_store(c, t):
    _n.append(1)
    seed(c, t, 0)
_real, P.list_store = P.list_store, _count_store
try:
    for _ in range(5):                       # five syncs in a row, well inside the cooldown
        P.list_ensure("mc:hot-empty", "host")
        for _ in range(200):
            with P._LIST_LOCK:
                if "mc:hot-empty|host" not in P._LIST_INFLIGHT:
                    break
            time.sleep(0.005)
        time.sleep(0.01)
finally:
    P.list_store = _real
check("five back-to-back syncs cause exactly ONE upstream resolve", len(_n) == 1, len(_n))
check("…because the cooldown is armed", P.list_failed("mc:hot-empty", "host"))
P._LIST_FAILED.pop("mc:hot-empty|host", None)          # cooldown expired
_n2 = []
def _count2(c, t):
    _n2.append(1); seed(c, t, 0)
_real, P.list_store = P.list_store, _count2
try:
    P.list_ensure("mc:hot-empty", "host")
    for _ in range(200):
        with P._LIST_LOCK:
            if "mc:hot-empty|host" not in P._LIST_INFLIGHT:
                break
        time.sleep(0.005)
    time.sleep(0.02)
finally:
    P.list_store = _real
check("once it expires, it tries again (so it still heals)", len(_n2) == 1, len(_n2))
check("a `force`d refresh ignores the cooldown entirely",
      "if m and not force and (_meta_n(m) or list_failed(cat, tier)):" in
      open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read())

print("\n[6] TWO READERS: /api/list-info must judge by records too, not by 'a meta exists'")
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("the endpoint's kick branch reads through _meta_n",
      '            if not _meta_n(m):                                  # missing OR stored-empty' in src)
check("a healthy list mid-refresh is NOT reported pending",
      "            if not m or (_busy and not _meta_n(m)):" in src)
check("nothing tests a bare `if not m:` to decide whether to resolve",
      "            m = list_meta(cat, tier)\n            if not m:\n" not in src)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
