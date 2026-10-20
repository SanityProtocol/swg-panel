#!/usr/bin/env python3
"""Self-test — swg-noded as a container's PID 1 stops at once on SIGTERM (1.8.9 qualification NX-L1).

A PID 1 has no default signal action, and a signal sent from outside its pid namespace (docker stop, podman stop) is
delivered only to a handler: swg-noded installed none, so every container stop waited 10 s for SIGKILL — +10 s of client
outage on every update, restart, recreate and arm switch. The panel had fixed exactly this for itself (_sigterm_exit).

  [1] main() installs the handler first, only as PID 1 (bare metal keeps the default: SIGTERM ends it at once)
  [2] the REAL thing, where `sudo -n` and unshare exist: swg-noded's code as PID 1 of a throwaway pid namespace, SIGTERM
      sent from outside — it exits at once with 0 (it ignored it and ran on)

Run: python3 tests/noded_pid1_sigterm_selftest.py     (0 = pass)
     --perturb   no handler again (the shipped code) → RED on [2] (and [1])
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv[1:]
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
ANCHOR = "            signal.signal(signal.SIGTERM, _sigterm_exit)\n"
if PERTURB:
    assert src.count(ANCHOR) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(ANCHOR, "            pass\n")
T = tempfile.mkdtemp(prefix="pid1term-")
noded = os.path.join(T, "swg-noded"); open(noded, "w", encoding="utf-8").write(src)

print("[1] the handler")
m = re.search(r"^def main\(\):\n(.*?)\n", src, re.M)
check("main() installs it first", bool(m) and m.group(1).strip() == "_pid1_signals()", m.group(1) if m else None)
g = re.search(r"^def _pid1_signals\(\):.*?(?=^def )", src, re.S | re.M)
check("…only as PID 1 (bare metal keeps SIGTERM's default: it ends at once)",
      bool(g) and "if os.getpid() == 1:" in g.group(0) and "signal.signal(signal.SIGTERM, _sigterm_exit)" in g.group(0))

print("\n[2] as PID 1 of a pid namespace, SIGTERM from outside")
P1 = r'''
import os, sys, time, types
src = open(sys.argv[1], encoding="utf-8").read()
N = types.ModuleType("n"); N.__dict__.update({"__name__": "n", "__file__": "swg-noded"})
exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)
N._pid1_signals()
print("pid", os.getpid(), flush=True)
time.sleep(30)
'''
RUN = r'''
unshare --pid --fork python3 "$1" "$2" > "$3" 2>/dev/null & U=$!
for i in $(seq 1 80); do C=$(pgrep -P $U | head -1); [ -n "$C" ] && grep -q pid "$3" 2>/dev/null && break; sleep 0.1; done
[ -n "$C" ] || { echo SETUP-FAILED; kill $U 2>/dev/null; exit 0; }
t0=$(date +%s%N); kill -TERM "$C"
for i in $(seq 1 40); do kill -0 "$C" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$C" 2>/dev/null; then echo "RAN-ON $(head -1 "$3")"; kill -KILL "$C"; wait $U 2>/dev/null
else wait $U; echo "EXITED $? $(( ($(date +%s%N)-t0)/1000000 )) $(head -1 "$3")"; fi
'''
if shutil.which("sudo") and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0 and shutil.which("unshare"):
    p1 = os.path.join(T, "p1.py"); open(p1, "w").write(P1)
    r = subprocess.run(["sudo", "-n", "bash", "-c", RUN, "_", p1, noded, os.path.join(T, "out")], capture_output=True, text=True,
                       timeout=60)
    out = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if out[0].startswith("SETUP-FAILED"):
        print("  SKIPPED [2] — the pid namespace could not be set up here")
    else:
        f = out[0].split()
        check("swg-noded as PID 1 exits at once with 0 on a SIGTERM sent from outside its namespace (docker stop)",
              f[:2] == ["EXITED", "0"] and f[-1] == "1" and int(f[2]) < 2000, out[0])
else:
    print("  SKIPPED [2] — no `sudo -n` / unshare here; [1] still ran")
shutil.rmtree(T, ignore_errors=True)

print("")
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS else "PERTURB FAILED — nothing went red")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
