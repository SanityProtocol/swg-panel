#!/usr/bin/env python3
"""Self-test — a bare → Docker convert leaves nothing of its own in /tmp (1.8.9 qualification LC24 #15b).

LC-24 found two /tmp/tmp.* files after every bare → Docker convert: a 20 KB copy of the whole install's output and an
empty file. The first is convert.sh's lifecycle log (lc_init tees everything printed into it): convert.sh hands the run
to install-docker.sh with `lc_handoff; exec …`, and an exec'd script never runs the EXIT trap that removes it — the tee
went on copying install-docker's output into it. The second is the carry file (carry_dropins_to_env → SWG_CARRY_ENV),
which nothing removed on any path.

  [1] lib/common.sh's lc_init + lc_handoff + exec, as convert.sh runs them: the log is gone once the handoff is made,
      and what both scripts print still reaches the terminal (the tee writes on into the unlinked file); a handoff
      with no exec after it (update.sh's "up to date") still ends cleanly
  [2] install-docker.sh: the carry file is removed once it has been read — one with keys (they reach the .env first)
      and an empty one; a dry run removes nothing

Run: python3 tests/convert_tmp_leftovers_selftest.py      (0 = pass)
     --perturb   lc_handoff and install-docker.sh as q189-int2 shipped them → RED on [1] and [2]
"""
import os, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv[1:]
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

LIB = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
DK = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
_rm_lc = '  if [ -n "${LC_LOG:-}" ]; then rm -f "$LC_LOG" 2>/dev/null || true; fi; }\n'
_rm_dk = 'if [ -n "${SWG_CARRY_ENV:-}" ] && ! $DRYRUN; then rm -f "$SWG_CARRY_ENV" 2>/dev/null || true; fi'
assert LIB.count(_rm_lc) == 1 and DK.count(_rm_dk) == 1, "the removals are not where this gate reads them — would FALSE-PASS"
if PERTURB:
    LIB = LIB.replace(_rm_lc, "  :; }\n")
    DK = DK.replace(_rm_dk, ":")
T = tempfile.mkdtemp(prefix="cvtmp-")
libf = os.path.join(T, "common.sh")
open(libf, "w").write(LIB)

print("[1] the lifecycle log across `lc_handoff; exec …`")
pathf, outf = os.path.join(T, "lclog"), os.path.join(T, "stdout")
script = ('source "$1" >/dev/null 2>&1; DRYRUN=false; lc_emit_file(){ :; }; LC_FILE=/dev/null\n'
          'lc_init convert-docker lc_emit_file; echo "$LC_LOG" > "$2"; echo "convert.sh output"\n'
          # the tee opens the log on its own time (a process substitution): wait for it, as a convert's minutes of work do
          'for i in $(seq 1 100); do [ -s "$LC_LOG" ] && break; sleep 0.05; done\n'
          'lc_handoff; exec bash -c "echo install-docker output; sleep 0.2"\n')
with open(outf, "w") as o:
    subprocess.run(["bash", "-c", script, "_", libf, pathf], stdout=o, stderr=subprocess.STDOUT, timeout=30)
time.sleep(0.4)   # the tee drains after the exec'd program ends
log = open(pathf).read().strip()
out = open(outf).read()
check("the log (%s) is gone once the run is handed off" % ("/tmp/tmp.*" if log.startswith("/tmp/") else log), log and not os.path.exists(log),
      (log, os.path.exists(log) and open(log).read()))
check("…and both scripts' output still reached the terminal", "convert.sh output" in out and "install-docker output" in out, out)
if log and os.path.exists(log):
    os.remove(log)
r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; DRYRUN=false; lc_emit_file(){ :; }; LC_FILE=/dev/null\n'
                    'lc_init update lc_emit_file; echo "$LC_LOG" > "$2"; lc_handoff; echo done', "_", libf, pathf],
                   capture_output=True, text=True, timeout=30)
time.sleep(0.2)
log = open(pathf).read().strip()
check("a handoff with no exec after it (update.sh's up to date) ends cleanly, its log gone too",
      r.returncode == 0 and "done" in r.stdout and not os.path.exists(log), (r.returncode, r.stdout, r.stderr[-200:]))

print("\n[2] install-docker.sh removes the carry file once it has read it")
i = DK.index('if [ -n "${SWG_CARRY_ENV:-}" ] && [ -s "$SWG_CARRY_ENV" ]; then\n')
j = DK.index("\n", DK.index("read once (LC24 #15b)", i)) + 1   # through the removal's line (its comment names it)
BLK = DK[i:j]
for label, content, dry in (("one with keys", "SWG_LATEST_URL='https://x/dev/V'\n", "false"), ("an empty one", "", "false"),
                            ("a dry run", "SWG_LATEST_URL='https://x/dev/V'\n", "true")):
    d = tempfile.mkdtemp(dir=T); carry = os.path.join(d, "tmp.carry"); open(carry, "w").write(content)
    open(os.path.join(d, ".env"), "w").write("PANEL_DOMAIN=x\n")
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\nDRYRUN=%s; PREFIX=""; INSTALL_DIR=%s; SWG_CARRY_ENV=%s\n%s\necho OK\n'
                        % (dry, d, carry, BLK)], capture_output=True, text=True, timeout=30)
    env = open(os.path.join(d, ".env")).read()
    if dry == "true":
        check("%s: nothing removed" % label, "OK" in r.stdout and os.path.exists(carry), (r.stdout, r.stderr[-200:]))
    else:
        check("%s: removed once read%s" % (label, " — its key reached the .env first" if content else ""),
              "OK" in r.stdout and not os.path.exists(carry) and (not content or "SWG_LATEST_URL='https://x/dev/V'" in env),
              (r.stdout, r.stderr[-200:], os.path.exists(carry), env))

print("")
if PERTURB:
    ok = bool(FAILS) and any(f.startswith("the log") for f in FAILS) and any("removed once read" in f for f in FAILS) \
        and not any("output still reached" in f or "nothing removed" in f for f in FAILS)
    print("perturb: %s" % ("RED as it must be (%d), [1] and [2], the controls green" % len(FAILS) if ok else "NOT CAUGHT / WRONG: %s" % FAILS))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
