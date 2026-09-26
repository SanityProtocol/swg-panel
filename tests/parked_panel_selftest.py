#!/usr/bin/env python3
"""Self-test — a PARKED bare panel stays parked across a trip back to 1.8.7 and forward again.

guard_second_panel parks a bare panel that would answer beside a docker one: swg-panel-server + swg-sub disabled and
stopped. `bare_panel_parked` read that back as "not enabled AND not active". But 1.8.7's update.sh restarts
swg-panel-server unconditionally and enables + restarts swg-sub, so a box that went back to 1.8.7 has the unit still
DISABLED but ACTIVE — "not parked" to the old test, so 1.8.8's update restarted it too and enabled swg-sub, and two
panels answered at one address for good.

Disabled is the decision; active only says something undid it. Parked now = disabled AND (inactive OR a live docker
panel beside it). A disabled unit running with NO docker panel beside it is the operator's own doing, and is left to
run — stopping the only panel on a box is the one outcome worse than two. update.sh's heal pass then stops a parked
panel that is running, with its swg-sub (disabled too).

bare_panel_parked + docker_panel_live + docker_parked come from lib/common.sh and repark_bare_panel from update.sh,
AS SHIPPED, over stubbed `systemctl` / `docker`.

Run: python3 tests/parked_panel_selftest.py        (0 = pass)
     --perturb   the shipped definition put back → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
UP = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def fn(src, name):
    """`name(){ … }` as shipped: header to the first closing line at which the text parses (`bash -n`)."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

parked = fn(C, "docker_panel_live") + fn(C, "bare_panel_parked") + fn(C, "docker_parked")
if PERTURB:
    old = "bare_panel_parked(){ ! systemctl is-enabled --quiet swg-panel-server 2>/dev/null && ! systemctl is-active --quiet swg-panel-server 2>/dev/null; }\n"
    parked = fn(C, "docker_parked") + old
repark = fn(UP, "repark_bare_panel")

def world(enabled, active, docker, sub_on=False, unit=True):
    """docker: None (no container) | 'live' | 'parked'."""
    d = tempfile.mkdtemp(prefix="park-"); log = os.path.join(d, "calls")
    u = os.path.join(d, "swg-panel-server.service")
    if unit:
        open(u, "w").write("[Unit]\n")
    sysd = ('echo "systemctl $*" >> %s\ncase "$*" in\n'
            '  *"is-enabled --quiet swg-panel-server"*) exit %d;;\n  *"is-active --quiet swg-panel-server"*) exit %d;;\n'
            '  *"is-enabled --quiet swg-sub"*|*"is-active --quiet swg-sub"*) exit %d;;\nesac\nexit 0\n') % (
        log, 0 if enabled else 1, 0 if active else 3, 0 if sub_on else 1)
    dk = {None: "exit 0", "live": 'case "$1" in ps) echo swg-panel;; inspect) echo "true always";; esac',
          "parked": 'case "$1" in ps) echo swg-panel;; inspect) echo "false no";; esac'}[docker]
    for n, body in (("systemctl", sysd), ("docker", dk)):
        p = os.path.join(d, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    return d, log, u

def ask(enabled, active, docker):
    d, _, _ = world(enabled, active, docker)
    r = subprocess.run(["bash", "-c", parked + "bare_panel_parked && echo PARKED || echo LIVE"], capture_output=True,
                       text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return r.stdout.strip()

print("[1] what counts as parked")
for en, ac, dk, want, why in (
        (True,  True,  "live",   "LIVE",   "enabled → never parked (the operator kept both, or it is the only panel)"),
        (False, False, "live",   "PARKED", "disabled + stopped → parked (as the guard left it)"),
        (False, True,  "live",   "PARKED", "⚠️ disabled but RUNNING beside a live docker panel → parked (1.8.7 restarted it)"),
        (False, True,  None,     "LIVE",   "disabled but running with NO docker panel → left alone (it is the only panel)"),
        (False, True,  "parked", "LIVE",   "disabled + running, the docker panel itself parked → left alone (this one is in use)"),
        (False, False, None,     "PARKED", "disabled + stopped, no docker → parked, unchanged from before")):
    check(why, ask(en, ac, dk) == want, ask(en, ac, dk))

print("\n[2] update.sh parks it again, with its swg-sub")
d, log, u = world(False, True, "live", sub_on=True)
body = repark.replace("/etc/systemd/system/swg-panel-server.service", u)
r = subprocess.run(["bash", "-c", "set -uo pipefail\nDRYRUN=false; DID_UPDATE=no\nRESULTS=(); note(){ RESULTS+=(\"$*\"); }\n"
                    "run(){ \"$@\"; }\nok(){ echo \"OK $*\"; }\n" + parked + body + "repark_bare_panel\necho DID_UPDATE=$DID_UPDATE\n"],
                   capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
calls = open(log).read()
check("the running parked panel is stopped", "systemctl stop swg-panel-server" in calls, calls)
check("…its swg-sub is stopped AND disabled (1.8.7 enabled it — it would come back at boot)", "systemctl disable --now swg-sub" in calls, calls)
check("…and it is a change the update reports", "DID_UPDATE=yes" in r.stdout and "parked again" in r.stdout, r.stdout + r.stderr)
d, log, u = world(False, True, None, sub_on=True)
body = repark.replace("/etc/systemd/system/swg-panel-server.service", u)
r = subprocess.run(["bash", "-c", "DRYRUN=false; DID_UPDATE=no\nnote(){ :; }\nrun(){ \"$@\"; }\nok(){ :; }\n" + parked + body +
                    "repark_bare_panel\n"], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
calls = open(log).read()
check("the only panel on the box (disabled, no docker) is NOT stopped", "stop" not in calls and "disable" not in calls, calls)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
