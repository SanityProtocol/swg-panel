#!/usr/bin/env python3
"""Self-test — THE STATS RINGS PILE UP ONE PER DEAD SUBJECT, AND NOTHING SWEPT THEM.

Every ring is a fixed-size circular buffer — 62,413 bytes, wrapping for ever — so no individual file grows
and the leak looks like nothing. What grows is the NUMBER of them: one per (node, peer), (node, interface),
(node, category), (node, exit), mesh pair, turn fork, and nothing removed one when its subject stopped
existing.

MEASURED on the qualification panel, which is as small as a fleet gets — 4 nodes, 3 peers: 104 rings, 69
with no live subject. 4.2 MB of 6.3 MB is 66% waste at the smallest possible scale, and it only goes up.
Worst family: mesh link interfaces, where every re-provision mints a fresh `swg_<hash>` and abandons the old
ring. There were also rings for a node no longer in the fleet at all.

⚠️ THE SWEEP IS BY MTIME, NOT BY SUBJECT, and that is the safety of it. Matching a file back to a live
subject means re-deriving eight key schemes — a sha256 prefix, a node-id rsplit, a sanitised fork name —
eight chances to get one wrong and delete a live ring. An mtime cannot be mis-derived. And it implements a
STRONGER rule: past the cutoff, `hrrd_read` returns nothing from the file whatever it contains, so deleting
it destroys nothing any range could still show.

⚠️ AND THE CUTOFF IS DERIVED, NOT CHOSEN. It is the larger of the coarsest ring's span and the widest
`RANGE_SPEC` window, plus two days. Change `HRRD_RINGS` and it follows — which is exactly what a hand-picked
"30 days" would not do.

Run: python3 tests/rings_gc_selftest.py      (0 = pass)
     --perturb   sweeps everything older than an hour and expects RED.
"""
import importlib.machinery, importlib.util, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv          # cutoff collapses to an hour → section [1] must go red
PERTURB_EAGER = "--perturb-eager" in sys.argv   # freshness guard removed → section [2] must go red

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()
_ANCH = "    return max(span, window) + 2 * 86400"
_ANCH2 = """                if st.st_mtime >= cutoff:
                    continue"""
assert SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
assert SRC.count(_ANCH2) == 1, "freshness-guard anchor missing — this run would FALSE-PASS"
path = PANEL
# TWO guards, two perturbations. One collapses the derived cutoff (caught by [1]); the other removes the
# freshness test entirely, so every ring is swept (caught by [2]). A single perturbation proved only the
# first — with the cutoff at an hour the fixtures in [2] all land on the safe side of it and pass, which is
# a gate reporting green about the guard it was written for.
if PERTURB:                                   # far too eager a cutoff: a live-but-quiet ring would be destroyed
    SRC = SRC.replace(_ANCH, "    return 3600")
if PERTURB_EAGER:                             # no freshness test at all: sweeps the live rings too
    SRC = SRC.replace(_ANCH2, "                pass")
if PERTURB or PERTURB_EAGER:
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="ringsgc-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(path, "swgpanel")
if PERTURB or PERTURB_EAGER:
    os.unlink(path)

DAY = 86400
print("[1] the cutoff is DERIVED from the ring geometry, not chosen")
span = max(step * n for step, n in P.HRRD_RINGS)
window = max(spec[2] for spec in P.RANGE_SPEC.values())
cut = P._rings_dead_after()
check("it is at least the coarsest ring's span (%.1f d)" % (span / DAY), cut >= span, cut / DAY)
check("…and at least the widest range window (%.1f d)" % (window / DAY), cut >= window, cut / DAY)
check("…with a grace on top", cut > max(span, window), (cut, max(span, window)))
check("nothing a range can still read is inside it", cut / DAY >= 30, cut / DAY)

print("\n[2] a ring older than the cutoff goes; a fresh one stays")
TMP = tempfile.mkdtemp(prefix="ringsgc-")
now = time.time()
def ring(name, age_days, size=62413):
    p = os.path.join(TMP, name)
    open(p, "wb").write(b"\0" * size)
    os.utime(p, (now - age_days * DAY, now - age_days * DAY))
    return p
fresh   = ring("iface-n1-awg0.rrd", 0)
hour    = ring("peer-n1-abc123.rrd", 0.04)
old_mid = ring("mesh-n1-n2.rrd", (cut / DAY) - 1)          # just INSIDE the cutoff → must survive
dead1   = ring("iface-gone-swg_deadbeef.rrd", (cut / DAY) + 5)
dead2   = ring("peer-gone-0123456789abcdef.rrd", (cut / DAY) + 400)
notring = os.path.join(TMP, "live-n1.json"); open(notring, "w").write("{}")
os.utime(notring, (now - 9999 * DAY, now - 9999 * DAY))

gone, freed = P.rings_gc(TMP)
left = sorted(os.listdir(TMP))
check("the two dead rings are gone", gone == 2, (gone, left))
check("bytes reported", freed == 2 * 62413, freed)
for p, why in ((fresh, "a ring written seconds ago"), (hour, "a ring written this hour"),
               (old_mid, "a ring one day INSIDE the cutoff")):
    check("%s survives" % why, os.path.exists(p), left)
check("a non-.rrd file is never touched, however old", os.path.exists(notring), left)

print("\n[3] it is harmless on an empty or missing stats dir")
check("missing dir → no crash, nothing removed", P.rings_gc(os.path.join(TMP, "nope")) == (0, 0))
check("no stats_dir configured → no crash", P.rings_gc("") == (0, 0))
check("second run over a swept dir removes nothing more", P.rings_gc(TMP)[0] == 0)

print("\n[4] it is actually WIRED — a function nobody calls sweeps nothing")
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("called from the background loop", "rings_gc((Handler.deps.get(\"fleet\") or {}).get(\"stats_dir\"))" in src)
check("…beside the lists GC, on its cadence", src.index("lists_gc(nodes_load") < src.index("rings_gc((Handler.deps"))
# Test for the CALL, not the word: the docstring explains why subject-matching was rejected and says
# "sha256" while doing so, and a check that cannot tell prose from code is a check that fails on a comment.
_body = src[src.index("def rings_gc"):src.index("def hrrd_read")]
check("the sweep never hashes anything — no subject identity is derived", "hashlib." not in _body)
check("…and it decides on mtime", "st.st_mtime" in _body)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
