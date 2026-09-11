#!/usr/bin/env python3
"""Self-test — CONVERTING OUT OF DOCKER MUST RETIRE THE DOCKER-ONLY UPDATER.

`wire_host_updater` lays `swg-update`, `swg-update-check` and swg-update.service/.timer down on EVERY docker
profile, node included, because a container cannot recreate itself: the panel/node touches a trigger and
this host-side unit does the `compose pull && up`. None of it means anything once the box is bare-metal, and
`convert.sh` removed none of it — the word `swg-update` did not appear in that file at all.

MEASURED on hel-fresh, doing bare→docker→bare: the converted node came back to bare-metal with
`swg-update.timer` ACTIVE, polling every 30 s for docker update requests on a box with no docker install,
and a wrapper `update.sh` will never touch again (a bare-metal NODE has no wrapper BY DESIGN —
`ensure_update_unit` is panel-only). Two identical bare-metal nodes then differ by history alone. Removing
them on the real box took the timer from `active` with 4 files to inactive with 0.

⚠️ TWO THINGS THE FIRST VERSION GOT WRONG, both asserted below:
  · It used `run` and `rmrf`. Those are the INSTALLERS' helpers — install-host.sh, install-docker.sh and
    uninstall.sh each define their own — and convert.sh has neither. It would have died with
    "run: command not found" on the one path nobody re-runs.
  · It was inserted inside another function, so it would only have been DEFINED when that block ran, and
    the second call site is 140 lines further on.

Run: python3 tests/convert_retires_docker_updater_selftest.py      (0 = pass)
     --perturb   drops the call from the node path and expects RED.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CONV = os.environ.get("SWG_CONVERT_SH") or os.path.join(ROOT, "convert.sh")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(CONV, encoding="utf-8").read()
CALL = "  retire_docker_updater   # the docker-only one-click updater has no meaning on a bare box — see above"
assert SRC.count(CALL) == 2, "anchor missing (%d call sites) — this run would FALSE-PASS" % SRC.count(CALL)
if PERTURB:
    SRC = SRC.replace(CALL, "  :", 1)          # drop the first (the panel/host path)

print("[1] it is defined at TOP LEVEL, so both call sites can reach it")
i_def = SRC.index("retire_docker_updater(){")
depth = SRC[:i_def].count("{") - SRC[:i_def].count("}")
check("brace depth 0 at the definition", depth == 0, depth)
for n, m in enumerate(re.finditer(r"^  retire_docker_updater", SRC, re.M), 1):
    check("call site %d comes after the definition" % n, m.start() > i_def)

print("\n[2] convert.sh's OWN idiom — `run`/`rmrf` do not exist in this file")
# Include the closing brace: without it the extracted text is an unterminated function definition and
# every behavioural check below dies of a bash syntax error rather than testing anything.
body = SRC[i_def:SRC.index("\n}\n", i_def) + 3]
# Continuation lines joined, so a `|| true` that sits at the END of a multi-line `rm -f` is seen as
# belonging to it — checking only the first physical line reported a guarded command as unguarded.
body_joined = body.replace(chr(92) + chr(10), " ")   # backslash-newline -> space
check("the file defines neither helper", not re.search(r"^(run|rmrf)\(\)", SRC, re.M))
check("…so the function calls neither", not re.search(r"\b(run|rmrf)\s", body), body)
check("it uses systemctl directly", "systemctl disable --now" in body)
check("…and rm -f directly", "rm -f /etc/systemd/system/swg-update.service" in body)

print("\n[3] every step tolerates a unit that was never installed (`set -euo pipefail`)")
check("the file is set -e", "set -euo pipefail" in SRC)
for step in ("systemctl disable --now", "rm -f", "systemctl daemon-reload"):
    line = next((l for l in body_joined.splitlines() if step in l), "")
    check("`%s` cannot abort the conversion" % step, "|| true" in line or "|| continue" in line, line.strip())

print("\n[4] BOTH docker→bare paths call it (host/master and node)")
check("two call sites remain", SRC.count("retire_docker_updater   #") == 2, SRC.count("retire_docker_updater   #"))

print("\n[5] behaviour: it removes exactly the six docker-updater artefacts, and tolerates their absence")
tmp = tempfile.mkdtemp(prefix="retire-")
sd, ub, vl = (os.path.join(tmp, "etc/systemd/system"), os.path.join(tmp, "usr/local/bin"),
              os.path.join(tmp, "var/lib"))
for d in (sd, ub, vl):
    os.makedirs(d)
planted = ["etc/systemd/system/swg-update.service", "etc/systemd/system/swg-update.timer",
           "usr/local/bin/swg-update", "usr/local/bin/swg-update-check", "var/lib/swg-update.stamp"]
keep = ["etc/systemd/system/swg-noded.service", "usr/local/bin/swg-noded"]
for f in planted + keep:
    open(os.path.join(tmp, f), "w").write("x")
sandboxed = (body.replace("/etc/systemd/system", tmp + "/etc/systemd/system")
                 .replace("/usr/local/bin", tmp + "/usr/local/bin")
                 .replace("/var/lib/swg-update.stamp", tmp + "/var/lib/swg-update.stamp")
                 .replace("systemctl disable --now \"$_u\"", "true"))
script = "#!/bin/bash\nset -euo pipefail\nsystemctl(){ return 0; }\n" + sandboxed + "\nretire_docker_updater\necho RC=$?\n"
sp = os.path.join(tmp, "t.sh"); open(sp, "w").write(script)
r = subprocess.run(["bash", sp], capture_output=True, text=True)
check("it exits cleanly", "RC=0" in (r.stdout or ""), (r.stdout, r.stderr)[:2])
for f in planted:
    check("removed %s" % f.split("/")[-1], not os.path.exists(os.path.join(tmp, f)))
for f in keep:
    check("left %s alone" % f.split("/")[-1], os.path.exists(os.path.join(tmp, f)))
r2 = subprocess.run(["bash", sp], capture_output=True, text=True)   # already-clean box
check("a second run on a clean box still exits 0", "RC=0" in (r2.stdout or ""), (r2.stdout, r2.stderr)[:2])

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
