#!/usr/bin/env python3
"""Self-test — the turn socket-buffer raise is tried once an hour where it cannot take, not on every pass.

`_turn_sock_bufs` runs on every pass that carries a turn-family listener. On a Docker node the container mounts /proc/sys
read-only, so `sysctl -w net.core.{r,w}mem_max` no-ops in silence — and it was asked twice a pass, for ever (svo-im,
2026-10-10: 212992 read back every time).

  [1] Read-only: the first pass tries each key once; the passes after it write nothing; the warning is said once.
  [2] An hour on, it is tried again (a /proc/sys made writable meanwhile takes then).
  [3] A larger cap is tried at once, whatever was tried for a smaller one.
  [4] Writable (bare metal): the raise takes on the first pass, and no pass after it writes (cur ≥ want) — as before.

Run: python3 tests/turn_sock_bufs_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     everypass    the raise is tried on every pass again
     never        a raise that did not take is never tried again
"""
import builtins, importlib.machinery, importlib.util, io, os, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "everypass": ("""        if cur < want and not (tried and tried[0] >= want and time.monotonic() - tried[1] < 3600):""",
                  """        if cur < want:"""),
    "never": ("""        if cur < want and not (tried and tried[0] >= want and time.monotonic() - tried[1] < 3600):""",
              """        if cur < want and not (tried and tried[0] >= want):"""),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="sockbufs-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("sb_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("sb_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
LOGS = []
N.log = lambda prio, msg, *a: LOGS.append(msg % a if a else msg)

K = {"rmem_max": 212992, "wmem_max": 212992, "ro": True, "want": 25165824}
WRITES = []
real_open = builtins.open


def fake_open(path, *a, **k):
    if isinstance(path, str) and path.startswith("/proc/sys/net/core/"):
        return io.StringIO("%d\n" % K[path.rsplit("/", 1)[1]])
    return real_open(path, *a, **k)


def fake_run(args, input_text=None, timeout=20, env=None):
    if args[:3] == ["sysctl", "-q", "-w"]:
        WRITES.append(args[3])
        if not K["ro"]:
            key, val = args[3].split("=")
            K[key.rsplit(".", 1)[1]] = int(val)
    return subprocess.CompletedProcess(args, 0, "", "")


N.open, N.run = fake_open, fake_run
N._turn_sock_target = lambda listeners=1: K["want"]
N._turn_sock_persist = lambda want: None


def passes(n):
    WRITES.clear()
    for _ in range(n):
        N._turn_sock_bufs(3)
    return list(WRITES)


# ── [1] read-only ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] /proc/sys read-only (a Docker node)")
w1 = passes(1)
check("[1] the first pass tries each key once", sorted(w1) == ["net.core.rmem_max=25165824", "net.core.wmem_max=25165824"], w1)
w2 = passes(5)
check("[1] the five passes after it write nothing", not w2, w2)
check("[1] the warning is said once per key", sum("could not be raised" in l for l in LOGS) == 2, LOGS)

# ── [2] an hour on ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] an hour on")
K["ro"] = False                                               # meanwhile /proc/sys became writable
for k in list(N._SOCK_BUF_TRIED):
    N._SOCK_BUF_TRIED[k] = (N._SOCK_BUF_TRIED[k][0], N._SOCK_BUF_TRIED[k][1] - 3600)
w3 = passes(1)
check("[2] tried again, and it takes", len(w3) == 2 and K["rmem_max"] == K["wmem_max"] == 25165824, (w3, K))
check("[2] …and nothing is written after it", not passes(3))

# ── [3] a larger cap ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] a larger cap")
K.update(rmem_max=212992, wmem_max=212992, ro=True, want=8388608)
N._SOCK_BUF_TRIED.clear()
passes(2)
K["want"] = 16777216
w4 = passes(1)
check("[3] a larger cap is tried at once", len(w4) == 2 and all(x.endswith("=16777216") for x in w4), w4)

# ── [4] writable ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] /proc/sys writable (bare metal)")
K.update(rmem_max=212992, wmem_max=212992, ro=False, want=25165824)
N._SOCK_BUF_TRIED.clear()
w5 = passes(1)
w6 = passes(5)
check("[4] the raise takes on the first pass, and no pass after it writes", len(w5) == 2 and not w6 and K["rmem_max"] == 25165824, (w5, w6))

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
