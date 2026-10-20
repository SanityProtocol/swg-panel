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

Run: python3 tests/docker_drainer_sweep_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nosweep      the drainer does not clear the queue (the loop)
     keeptmp      a `.json.tmp` is kept however old
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

D.main()
left = sorted(os.listdir(Q))

print("[1] one run")
check("[1] an abandoned .json.tmp (2 min old) is cleared", "1791.json.tmp" not in left, left)
check("[1] …one the panel is writing (just now) is kept", "1792.json.tmp" in left, left)
check("[1] a dotfile, a stale claim and a directory are cleared", not ({".stray", "1790.json.taking", "junk"} & set(left)), left)
check("[1] a symlink: the link is cleared, never what it points at", "link" not in left and open(target).read() == "keep me", left)

print("\n[2] the queue after it")
check("[2] nothing but the request being written is left (the path unit has nothing else to fire on)", left == ["1792.json.tmp"], left)

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
