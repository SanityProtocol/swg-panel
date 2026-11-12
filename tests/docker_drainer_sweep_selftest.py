#!/usr/bin/env python3
"""Self-test — the Docker address drainer clears what is in its queue and is not a request (code review of docs/CPU-PLAN.md A3).

swg-netctl-docker drains the netctl queue a Docker panel writes, started by swg-netctl-docker.path (DirectoryNotEmpty) and
its 10 s timer, behind the idle gate (lib/common.sh: run when the queue holds anything). It skipped every entry that was not
a `.json` and removed none of them, so a `<rid>.json.tmp` an enqueue left behind (the panel's write failed after creating
it — ENOSPC), a dotfile, a directory or a stale claim kept the path unit firing after every run, and the gate at "run" on
every tick: the Python drainer started for nothing, for ever. Bare-metal swg-netctl clears them (process_queue's _sweep).

  [1] A run clears an abandoned `.json.tmp` (older than a minute), a dotfile, a stale claim, a directory, and a symlink —
      the link only, never what it points at; it keeps a `.json.tmp` the panel is writing (younger than a minute).
  [2] The queue is then empty: the path unit has nothing to fire on, the gate nothing to run for.
  [3] One write, one start (docs/SCALE-PLAN.md K8 D2): a run that meets a `.json.tmp` being written waits in its own run
      (0.2 s looks) and handles the request it becomes — before, it returned, and the .path unit started it back to back
      until systemd's start limit failed the path unit for good.
  [4] A tmp never completed: the run returns once the sweep ages it out (past 60 s), the queue empty; one with a future
      mtime ends the run at 65 s.
  [5] Anything else left (a request that cannot be removed) returns at once, beside a fresh tmp too: never a spin.

Run: python3 tests/docker_drainer_sweep_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nosweep      the drainer does not clear the queue (the loop)
     keeptmp      a `.json.tmp` is kept however old
     nowait       a run returns after one pass while a tmp is being written (the path unit's start loop)
     spin         a run waits on whatever is left, unbounded
"""
import importlib.machinery, importlib.util, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "docker", "swg-netctl-docker"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "nosweep": ("    _sweep_queue()\n", ""),
    "nowait": ("        time.sleep(0.2)\n", "        return\n"),
    "spin": ("        if not left or time.monotonic() > until or not all(n.endswith(\".json.tmp\") for n in left):",
             "        if not left:"),
    "keeptmp": ("            if name.endswith(\".json.tmp\") and now - st.st_mtime <= 60:",
                "            if name.endswith(\".json.tmp\"):"),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="drainsweep-")
Q = os.path.join(T, "data", "lib", "netctl", "queue")
os.makedirs(Q)
os.makedirs(os.path.join(T, "data", "lib", "netctl", "status"))
prog = os.path.join(T, "swg-netctl-docker")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_DOCKER_DIR"] = T
ld = importlib.machinery.SourceFileLoader("drainer", prog)
D = importlib.util.module_from_spec(importlib.util.spec_from_loader("drainer", ld))
ld.exec_module(D)

old = time.time() - 120


def put(name, mtime=None):
    p = os.path.join(Q, name)
    open(p, "w").write("{")
    if mtime is not None:
        os.utime(p, (mtime, mtime))


put("1791.json.tmp", old)                         # an enqueue that failed after creating its temporary file
put("1792.json.tmp")                              # the panel writing a request right now
put(".stray")
put("1790.json.taking", old)                      # a claim an earlier build left
os.makedirs(os.path.join(Q, "junk"))
open(os.path.join(Q, "junk", "f"), "w").write("x")
target = os.path.join(T, "outside")
open(target, "w").write("keep me")
os.symlink(target, os.path.join(Q, "link"))

D._sweep_queue()
left = sorted(os.listdir(Q))

print("[1] one run")
check("[1] an abandoned .json.tmp (2 min old) is cleared", "1791.json.tmp" not in left, left)
check("[1] …one the panel is writing (just now) is kept", "1792.json.tmp" in left, left)
check("[1] a dotfile, a stale claim and a directory are cleared", not ({".stray", "1790.json.taking", "junk"} & set(left)), left)
check("[1] a symlink: the link is cleared, never what it points at", "link" not in left and open(target).read() == "keep me", left)

print("\n[2] the queue after it")
check("[2] nothing but the request being written is left (the path unit has nothing else to fire on)", left == ["1792.json.tmp"], left)



class Clock:
    """The drainer's `time`, run fast: sleep() moves both clocks at once (the sweep ages a tmp by time() against its real
    mtime), and at most 2,000 looks — a run that has not ended by then spins."""
    def __init__(self, on_sleep=None):
        self.off, self.mono, self.sleeps, self.on_sleep = 0.0, 1000.0, 0, on_sleep

    def time(self):
        return time.time() + self.off

    def monotonic(self):
        return self.mono

    def sleep(self, s):
        self.sleeps += 1
        if self.sleeps > 2000:
            raise RuntimeError("spin")
        self.off += s; self.mono += s
        if self.on_sleep:
            self.on_sleep(self)


def run_main(clock):
    D.time = clock
    try:
        D.main()
        return "returned"
    except RuntimeError as e:
        return str(e)
    finally:
        D.time = time


import json
for f in os.listdir(Q):
    os.unlink(os.path.join(Q, f))
ST = os.path.join(T, "data", "lib", "netctl", "status")

print("\n[3] a request being written")
put("2001.json.tmp")
def land(c):                                      # the panel's rename lands on the third look
    if c.sleeps == 3:
        open(os.path.join(Q, "2001.json.tmp"), "w").write(json.dumps({"id": "2001", "verb": "noop", "args": []}))
        os.replace(os.path.join(Q, "2001.json.tmp"), os.path.join(Q, "2001.json"))
c = Clock(land)
r = run_main(c)
check("[3] the same run handles it (status written) and ends with the queue empty",
      r == "returned" and os.path.exists(os.path.join(ST, "2001.json")) and os.listdir(Q) == [], (r, c.sleeps, os.listdir(Q)))
check("[3] …after a few looks, not a minute", 3 <= c.sleeps <= 5, c.sleeps)

print("\n[4] a tmp never completed")
put("2002.json.tmp")
c = Clock()
r = run_main(c)
check("[4] the run returns once the sweep ages it out, the queue empty",
      r == "returned" and os.listdir(Q) == [] and 60 <= c.off <= 61, (r, c.off, os.listdir(Q)))
put("2003.json.tmp", time.time() + 3600)          # a clock that went back: the sweep never ages it
c = Clock()
r = run_main(c)
check("[4] a tmp with a future mtime ends the run at 65 s", r == "returned" and 65 <= c.off <= 65.5, (r, c.off))
os.unlink(os.path.join(Q, "2003.json.tmp"))

print("\n[5] something else left")
os.makedirs(os.path.join(Q, "2004.json"))         # a "request" that cannot be removed
put("2005.json.tmp")
c = Clock()
r = run_main(c)
check("[5] the run returns at once — no look, no spin", r == "returned" and c.sleeps == 0, (r, c.sleeps))

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
