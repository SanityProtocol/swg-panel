#!/usr/bin/env python3
"""swg-sni writes a learned address so that its set timeout is FRESH — on a first learn and on every refresh.

`nft add element` of an element that already exists returns 0 and leaves its expiry where it was, with or without an explicit
`timeout` (measured, 6.17 / nft 1.0.9). swg-sni's refresh was that plain add, so every learned address expired one learn_ttl
after its first learn however busy it was, while its `seen` cache believed it fresh: for up to refresh_age after that, new
connections to it matched no set, left by the wrong route, and were neither written again nor reset (`.campaign` rig bxl,
Bxlt2 — the real-kernel gate for what this file checks the shape of). Each write is now add + delete + add in ONE `nft -f`
transaction — every category's in ONE, so two rules' sets holding the same name go live together (the first rule of the
chain wins; written one process per category, the later rule's set was live ~50 ms early and the RST's retry left by the WRONG
exit — live, msk-main 2026-09-23). A refused joint write falls back to one transaction per category.

  python3 tests/sni_learn_refresh_selftest.py [--plant NAME]

Plants (each must turn at least one check red):
  r1 the write is the plain `add element` again (a refresh changes no expiry)
  r2 a batch holding one address twice lists it twice (its second delete fails and the whole transaction with it)
  r3 a write that nft refuses keeps its `seen` entries (the address is never learned again while they last)
  r4 a sighting past refresh_age is not written again (an address in use expires on schedule)
  r5 the categories are written one process each again (two rules' sets go live apart)
  r6 a refused joint write does not fall back (one missing set stops every other category learning)
"""
import importlib.machinery, importlib.util, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SNI = os.environ.get("SWG_SNI") or os.path.join(HERE, "..", "swg-sni")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []

PLANTS = {
    "r1": ('''return "add element %s\\ndelete element %s\\nadd element %s\\n" % (el, el, el)''',
           '''return "add element %s\\n" % el'''),
    "r2": ('''            if ip not in bycat.setdefault(cat, []):
                bycat[cat].append(ip)''', '''            bycat.setdefault(cat, []).append(ip)'''),
    "r3": ('''                with self._lock:
                    for ip in ips:
                        self.seen.pop((ip, cat), None)
                print("swg-sni: batch add failed''', '''                print("swg-sni: batch add failed'''),
    "r4": ('''                elif now - ts < self.refresh_age:              # fresh → already routing in this category, nothing to do''',
           '''                elif True:                                     # fresh → already routing in this category, nothing to do'''),
    "r5": ("if len(bycat) > 1 and subprocess.run(", "if False and subprocess.run("),
    "r6": ("input=scr, capture_output=True, text=True).returncode == 0:", "input=scr, capture_output=True, text=True) or True:"),
}


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


path = SNI
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(SNI, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(tempfile.mkdtemp(prefix="sni-refresh-"), "swg-sni")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
_l = importlib.machinery.SourceFileLoader("swgsni_refresh", os.path.abspath(path))
S = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgsni_refresh", _l))
_l.exec_module(S)

CALLS = []


class _R:
    def __init__(self, rc):
        self.returncode, self.stdout, self.stderr = rc, "", "" if rc == 0 else "Error: No such file or directory"


def fake_run(argv, input=None, capture_output=False, text=False, **kw):
    CALLS.append((list(argv), input))
    return _R(1 if input and "catl_missing" in input else 0)


S.subprocess.run = fake_run


def classifier(ttl=120):
    C = S.Classifier.__new__(S.Classifier)                 # no flusher thread, no map: only the write and the decision
    C.table, C.seen, C._pending, C._lock, C._wake = "swg_smart", {}, [], threading.Lock(), threading.Event()
    C.learn_ttl, C.refresh_age, C.reset_mark = ttl, ttl / 2.0, 0x9999
    C._blk_hits, C._last_reload = {}, float("inf")
    return C


print("[the write: every category in ONE transaction, add + delete + add]")
C = classifier()
C.seen = {("192.0.2.81", "c1"): 1.0, ("192.0.2.82", "c1"): 1.0, ("192.0.2.91", "c2"): 1.0}
CALLS.clear()
C._write_learned([("c1", "192.0.2.81"), ("c1", "192.0.2.81"), ("c1", "192.0.2.82"), ("c2", "192.0.2.91")])
check("two categories: ONE nft process, a script on stdin, carrying both sets (they go live together)",
      len(CALLS) == 1 and CALLS[0][0] == ["nft", "-f", "-"] and "catl_c1 " in CALLS[0][1] and "catl_c2 " in CALLS[0][1], CALLS)
lines = (CALLS[0][1] if CALLS else "").strip().split("\n")
el = "inet swg_smart catl_c1 { 192.0.2.81, 192.0.2.82 }"
check("the script adds, deletes and adds the same elements — the delete is what makes the second add fresh",
      lines[:3] == ["add element " + el, "delete element " + el, "add element " + el], lines)
check("an address listed twice in the batch is written once (a second delete would fail the whole transaction)",
      (CALLS[0][1] if CALLS else "").count("192.0.2.81") == 3, CALLS)
check("a joint write that lands keeps every `seen` entry", len(C.seen) == 3, C.seen)

print("\n[a refused joint write: one transaction per category, and only the refused one is forgotten]")
C = classifier()
C.seen = {("192.0.2.81", "c1"): 1.0, ("192.0.2.82", "c1"): 1.0, ("192.0.2.90", "missing"): 1.0, ("192.0.2.91", "c2"): 1.0}
CALLS.clear()
C._write_learned([("c1", "192.0.2.81"), ("c1", "192.0.2.82"), ("missing", "192.0.2.90")])
check("the joint write is tried first, then each category on its own (c1 still learns though `missing` has no set)",
      len(CALLS) == 3 and "catl_missing" in CALLS[0][1] and "catl_c1 " in CALLS[0][1]
      and any("catl_c1 " in a[1] and "catl_missing" not in a[1] for a in CALLS[1:]), CALLS)
check("a refused write forgets that category's `seen` entries, so the address is learned again next time",
      ("192.0.2.90", "missing") not in C.seen and ("192.0.2.81", "c1") in C.seen and ("192.0.2.91", "c2") in C.seen, C.seen)
CALLS.clear()
C._write_learned([("c1", "192.0.2.81")])
check("one category: one process, no joint attempt first", len(CALLS) == 1 and "catl_c1 " in CALLS[0][1], CALLS)

print("\n[the decision: a first sight learns and resets, a sighting past refresh_age writes again without a reset]")
C = classifier(ttl=120)
S._dst_and_tcp_payload = lambda p: ("192.0.2.81", b"x")
S.parse_sni = lambda tcp: "h2.example"
C._match = lambda host: ["c1"]
t0 = time.time()
first = C.on_packet(b"")
check("first sight: reset mark, and the address queued for its write", first == 0x9999 and C._pending == [("c1", "192.0.2.81")],
      (first, C._pending))
C._pending = []
v = C.on_packet(b"")
check("a sighting while it is fresh (under refresh_age): nothing queued, no reset", v is None and C._pending == [], (v, C._pending))
C.seen[("192.0.2.81", "c1")] = t0 - 61
v = C.on_packet(b"")
check("a sighting past refresh_age (61 s of 120): queued again for a fresh write, no reset", v is None and C._pending == [("c1", "192.0.2.81")],
      (v, C._pending))

print("\n" + ("All checks passed." if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
