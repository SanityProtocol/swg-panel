#!/usr/bin/env python3
"""Self-test for `_pid_alive` / `_reap_children` — "is that pid a LIVE process", and who collects the dead.

The bug this locks down, measured on the svo-im **docker** node 2026-09-08: `_dnsmasq_running()` asked
`os.kill(pid, 0)`, which a ZOMBIE answers happily. In a container swg-noded is PID 1, so every orphan a
daemonising helper leaves is ours and nothing reaps it — dnsmasq's double-fork left two per start. Kill the
resolver and the pid-file's pid stays "alive" for ever: nothing on :5354, every smart client's DNS
blackholed by the :53 DNAT, and the snapshot still reporting `dnsmasq: true`, `engine_ok: true`, no errors.
17 zombies had piled up in two days, 16 of them in one four-second burst.

Hermetic: real fork()ed children of THIS process, real /proc, real waitpid. No network, no state dir, no root
— which is why `_reap_children` takes the pid whose children it collects instead of hard-coding 1.

Run: python3 tests/pid_liveness_selftest.py (0 = pass).

  --perturb            back out ALL of the fix and expect red
  --perturb=<name>     back out one part: alive | grace | ppid
Each perturbation rewrites the SOURCE and re-imports it, so what is exercised is the real code path and not
a stand-in for it. A green run proves nothing unless every red one is reachable.
"""
import importlib.machinery, importlib.util, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

# ── the perturbations: (name, what it breaks, from, to) ───────────────────────────────────────
PERTURBATIONS = {
    # the liveness probe forgets that a zombie is dead — the exact code that shipped before 2026-09-08
    "alive": ('''    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            data = f.read()''',
              '''    if True:
        return True
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            data = f.read()'''),
    # the reaper collects with no grace at all, so it can steal a status `run()` is waiting for
    "grace": ("_ZOMBIE_GRACE = 30.0", "_ZOMBIE_GRACE = 0.0"),
    # the reaper stops asking whether a run() is waiting, so a slow read can lose a FAILED command's status
    "inflight": ("""    with _RUN_LOCK:
        if _RUN_INFLIGHT:
            return 0
""", ""),
    # the reaper stops checking whose child it is, so it reaps a process it never spawned
    "ppid":  ('if fields[0] != b"Z" or int(fields[1]) != me:',
              'if fields[0] != b"Z":'),
}
ASKED = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--perturb=")]
ALL = any(a == "--perturb" for a in sys.argv)
WANT = list(PERTURBATIONS) if ALL else ASKED
PERTURB = bool(WANT)

src = open(NODED).read()
path = NODED
if PERTURB:
    for name in WANT:
        frm, to = PERTURBATIONS[name]
        if src.count(frm) != 1:
            print("HARNESS BROKEN: perturbation %r matched %d times, not 1" % (name, src.count(frm)))
            sys.exit(2)
        src = src.replace(frm, to, 1)
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded", path)
spec = importlib.util.spec_from_loader("swgnoded", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass


def make_zombie(parent_wait=None):
    """A real child of this process that has exited and has not been waited on."""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    for _ in range(300):                       # wait for it to reach Z, not merely for fork() to return
        if state_of(pid) in ("Z", "gone"):
            break
        time.sleep(0.01)
    return pid


def state_of(pid):
    try:
        return open("/proc/%d/stat" % pid, "rb").read().rsplit(b")", 1)[1].split()[0].decode()
    except OSError:
        return "gone"


print("── _pid_alive ──")
check("a live process is alive", N._pid_alive(os.getpid()) is True)

z = make_zombie()
check("fixture: the kernel still accepts signal 0 for a zombie",
      state_of(z) == "Z" and (os.kill(z, 0) is None),
      "if this fails the fixture is wrong, not the code")
check("a zombie reads as DEAD", N._pid_alive(z) is False,
      "state=%s — os.kill(pid,0) succeeds on a zombie, which is why the naive probe lied" % state_of(z))

try:
    pid_max = int(open("/proc/sys/kernel/pid_max").read().strip())
except OSError:
    pid_max = 4194304
check("an absent pid reads as dead", N._pid_alive(pid_max) is False)

# comm sits in parens and may itself contain spaces AND parens — the state is the field after the LAST ')'
def parse_state(line):
    return line.rsplit(b")", 1)[1].split()[0]
check("state is read after the LAST ')' — hostile comm",
      parse_state(b"7 ((sd-pam)) S 1 7 0 0 -1 0 0") == b"S")
check("…and a zombie with a hostile comm still reads Z",
      parse_state(b"7 (a b) c (d) Z 1 7 0 0 -1 0 0") == b"Z")

print("── _reap_children ──")
me = os.getpid()
N._ZOMBIE_SEEN.clear()

N._reap_children(me)
check("a FRESH zombie is left alone (grace protects a sibling thread's own wait)",
      state_of(z) == "Z", "reaped a 0s-old zombie; grace=%.0fs" % N._ZOMBIE_GRACE)

for k in list(N._ZOMBIE_SEEN):                 # age it, rather than sleeping out the grace
    N._ZOMBIE_SEEN[k] -= (N._ZOMBIE_GRACE + 1.0)
n = N._reap_children(me)
check("an AGED zombie is reaped", state_of(z) == "gone", "state=%s reaped=%d" % (state_of(z), n))
check("…and it is counted", n >= 1, n)
check("the seen-map drops pids that are gone", z not in N._ZOMBIE_SEEN, sorted(N._ZOMBIE_SEEN))

# somebody ELSE's child is never touched: a zombie whose ppid is not `me`
kid = os.fork()
if kid == 0:                                   # a child that makes its OWN zombie and holds it
    g = os.fork()
    if g == 0:
        os._exit(0)
    time.sleep(4)
    os._exit(0)
grand = None
for _ in range(300):
    for ent in os.listdir("/proc"):
        if not ent.isdigit():
            continue
        try:
            f = open("/proc/%s/stat" % ent, "rb").read().rsplit(b")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if f[0] == b"Z" and int(f[1]) == kid:
            grand = int(ent)
    if grand:
        break
    time.sleep(0.01)
check("fixture: a grandchild zombie exists under another parent", grand is not None)
if grand:
    # The kernel would refuse `waitpid` on a process that is not our child anyway, so "it survived" alone
    # proves nothing about our filter — it proves the kernel. Record every pid the reaper actually ASKS for.
    class _OsSpy:
        def __init__(self, real): self._real, self.asked = real, []
        def __getattr__(self, k): return getattr(self._real, k)
        def waitpid(self, pid, flags):
            self.asked.append(pid)
            return self._real.waitpid(pid, flags)
    spy = _OsSpy(os)
    N.os = spy
    try:
        N._ZOMBIE_SEEN.clear()
        N._reap_children(me)
        for k in list(N._ZOMBIE_SEEN):
            N._ZOMBIE_SEEN[k] -= (N._ZOMBIE_GRACE + 1.0)
        N._reap_children(me)
    finally:
        N.os = os
    check("the reaper never even ASKS about another parent's zombie", grand not in spy.asked,
          "asked=%s — the ppid filter is what keeps it out of the loop" % spy.asked)
    check("a zombie belonging to ANOTHER parent is never reaped", state_of(grand) == "Z",
          "state=%s" % state_of(grand))
    check("…and it never entered the seen-map", grand not in N._ZOMBIE_SEEN, sorted(N._ZOMBIE_SEEN))
os.waitpid(kid, 0)

print("── the PID-1 guard ──")
z2 = make_zombie()
N._ZOMBIE_SEEN.clear()
check("_reap_orphans is a no-op off PID 1", N._reap_orphans() == 0 and state_of(z2) == "Z")
os.waitpid(z2, 0)

print("── a run() in flight owns every zombie on the box ──")
# `run()`'s child is defunct for microseconds normally — but a command that forks and lets a GRANDCHILD hold
# the stdout pipe stays defunct for the whole read, up to that call's timeout, and those reach 320s in this
# file. No grace covers that without being kept in step with eleven call sites, so the reaper asks the only
# question that actually matters instead: is anybody waiting right now?
_seen_inflight = []
_sp_run = N.subprocess.run
N.subprocess.run = lambda *a, **k: (_seen_inflight.append(N._RUN_INFLIGHT), _sp_run(*a, **k))[1]
N.run(["/bin/true"])
N.subprocess.run = _sp_run
check("run() publishes itself while it waits", _seen_inflight == [1], _seen_inflight)
check("…and clears on the way out", N._RUN_INFLIGHT == 0, N._RUN_INFLIGHT)
N.run(["/nonexistent/binary"])                              # FileNotFoundError -> 127
N.run(["/bin/sleep", "5"], timeout=1)                       # TimeoutExpired -> 124
check("…on the error paths too, or one missing binary wedges the reaper for ever",
      N._RUN_INFLIGHT == 0, N._RUN_INFLIGHT)

z3 = make_zombie()
N._ZOMBIE_SEEN.clear()
N._reap_children(os.getpid())                               # first sighting starts its clock
for k in list(N._ZOMBIE_SEEN):
    N._ZOMBIE_SEEN[k] -= (N._ZOMBIE_GRACE + 1.0)
N._RUN_INFLIGHT += 1
check("an AGED zombie is left alone while a run() is waiting",
      N._reap_children(os.getpid()) == 0 and state_of(z3) == "Z", state_of(z3))
N._RUN_INFLIGHT -= 1
check("…and is collected on the first pass with nothing in flight",
      N._reap_children(os.getpid()) == 1)

print("── the callers that mattered ──")
real = open(NODED).read()
check("_dnsmasq_running asks _pid_alive, not os.kill",
      "return pid if _pid_alive(pid) else 0" in real)
check("the main loop reaps once a pass", "_reap_orphans()                             # PID 1" in real)
live = [l.strip() for l in real.splitlines()
        if "os.kill(" in l and ", 0)" in l and not l.strip().startswith("#")]
check("only _pid_alive still probes with os.kill(pid, 0)", len(live) == 1, live)

print()
if PERTURB:
    if FAILS:
        print("PERTURB(%s) OK — %d check(s) red: %s" % (",".join(WANT), len(FAILS), FAILS))
        sys.exit(0)
    print("PERTURB(%s) FAILED — everything still passed with that part removed" % ",".join(WANT))
    sys.exit(1)
if FAILS:
    print("FAIL: %d — %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("PASS")
