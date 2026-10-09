#!/usr/bin/env python3
"""Self-test — swg-sub as a container's PID 1 stops at once on SIGTERM (1.8.9 qualification, VERIFY2-VMB; the class of
swg-noded's NX-L1).

A PID 1 has no default signal action, and a signal sent from outside its pid namespace (docker stop) is delivered only to a
handler: swg-sub installed none, so every stop of a Docker master's swg-sub container (an update, a restart) waited ~10 s for
SIGKILL (exit 137). The real swg-sub is run as a script, parked in its own wait for a fleet.json that does not exist.

  [1] as PID 1 of a throwaway pid namespace (`sudo -n` + unshare; SKIPPED where they are not), a SIGTERM sent from outside
      ends it at once, exit 0
  [2] off PID 1 (bare metal, systemd) SIGTERM's default stays: it is killed by the signal

Run: python3 tests/sub_pid1_sigterm_selftest.py      --plant nohandler | always   (exit 0 when caught)
     SWG_SUB=<swg-sub of an older build> python3 tests/sub_pid1_sigterm_selftest.py   (that build, unplanted)
"""
import contextlib, os, shutil, signal, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {   # name: (sections that must go red, anchor, planted text)
    "nohandler": (("[1]",), "        signal.signal(signal.SIGTERM, lambda _sig, _frm: os._exit(0))\n", "        pass\n"),
    "always":    (("[2]",), "    if os.getpid() == 1:\n        signal.signal(signal.SIGTERM,", "    if True:\n        signal.signal(signal.SIGTERM,"),
}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))


T = tempfile.mkdtemp(prefix="sub-pid1-")
src = open(SUB, encoding="utf-8").read()
if PLANT:
    _secs, old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    src = src.replace(old, new)
SUBP = os.path.join(T, "swg-sub"); open(SUBP, "w", encoding="utf-8").write(src)
os.chmod(T, 0o755); os.chmod(SUBP, 0o644)
NOFLEET = os.path.join(T, "no-such", "fleet.json")         # main() waits for it (up to 60 s): the process is parked there

SECTION[0] = "[1]"; print("[1] as PID 1 of a pid namespace, SIGTERM sent from outside (docker stop)", flush=True)
RUN = r'''
unshare --pid --fork env SWG_SUB_FLEET="$3" python3 "$1" > "$2" 2>&1 & U=$!
for i in $(seq 1 100); do C=$(pgrep -P $U | head -1); [ -n "$C" ] && grep -q waiting "$2" 2>/dev/null && break; sleep 0.1; done
[ -n "$C" ] || { echo SETUP-FAILED; kill $U 2>/dev/null; exit 0; }
P=$(awk '/^NSpid:/{print $NF}' /proc/$C/status)
t0=$(date +%s%N); kill -TERM "$C"
for i in $(seq 1 40); do kill -0 "$C" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$C" 2>/dev/null; then echo "RAN-ON $P"; kill -KILL "$C"; wait $U 2>/dev/null
else wait $U; echo "EXITED $? $(( ($(date +%s%N)-t0)/1000000 )) $P"; fi
'''
if shutil.which("sudo") and shutil.which("unshare") and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
    r = subprocess.run(["sudo", "-n", "bash", "-c", RUN, "_", SUBP, os.path.join(T, "out1"), NOFLEET], capture_output=True,
                       text=True, timeout=60)
    out = ((r.stdout or "").strip().splitlines() or [""])[-1]
    if out.startswith("SETUP-FAILED"):
        print("  SKIPPED [1] — the pid namespace could not be set up here")
    else:
        f = out.split()
        check("swg-sub as PID 1 exits at once with 0 on a SIGTERM sent from outside its namespace",
              f[:2] == ["EXITED", "0"] and f[-1] == "1" and int(f[2]) < 2000, out)
else:
    print("  SKIPPED [1] — no `sudo -n` / unshare here")

SECTION[0] = "[2]"; print("\n[2] off PID 1 (bare metal): SIGTERM's default stays", flush=True)
env = dict(os.environ, SWG_SUB_FLEET=NOFLEET); env.pop("JOURNAL_STREAM", None)
log = open(os.path.join(T, "out2"), "w")
p = subprocess.Popen([sys.executable, SUBP], env=env, stdout=log, stderr=log)
end = time.monotonic() + 10
while "waiting" not in open(os.path.join(T, "out2")).read() and time.monotonic() < end:
    time.sleep(0.1)
p.send_signal(signal.SIGTERM)
try:
    rc = p.wait(5)
except subprocess.TimeoutExpired:
    p.kill(); rc = "ran on"
check("killed by the SIGTERM itself (its default action), no handler installed", rc == -signal.SIGTERM, rc)

with contextlib.suppress(Exception):
    subprocess.run(["sudo", "-n", "rm", "-rf", T], capture_output=True, timeout=30)   # out1 is root's
shutil.rmtree(T, ignore_errors=True)
print()
if PLANT:
    want = PLANTS[PLANT][0]
    red = sorted({sec for sec, _n in FAILS})
    ok = bool(red) and all(sec in want for sec in red)
    print("plant %s: %s — red in %s (expected %s)" % (PLANT, "RED as it must be" if ok else "NOT caught as it must be", red, list(want)))
    sys.exit(0 if ok else 1)
print("FAIL: %d — %s" % (len(FAILS), FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
