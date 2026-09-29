#!/usr/bin/env python3
"""guard_second_panel (lib/common.sh) — an installer must not quietly start a second panel beside a live one.

Hermetic: `docker` and `systemctl` are shell stubs on PATH; the bare-metal unit path is the real one, so the
bare-metal-side cases stub `systemctl` and point the check at a temp unit via a sed'd copy of the function.

  1. nothing of the other method → silent, continues
  2. the other panel is live → asks; unattended with no answer → refuses (exit 1), never assumes
  3. SWG_OTHER_PANEL=stop → stops it the right way (docker: restart=no + stop; bare: disable --now) and continues
  4. SWG_OTHER_PANEL=keep → continues without touching it; abort → exit 1
  5. the other is installed but stopped and not set to start → a note, no question
  6. a convert (SWG_CONVERT_DIR) is exempt — convert.sh owns the switch-over
  7. a parked panel stays parked through update.sh — its subscription server with it (1.8.8 qualification: the
     bare branch disabled only swg-panel-server, so the bare swg-sub kept serving the parked panel's frozen store on
     the port the Docker stack's own swg-sub publishes, and every update restarted it and re-enabled it)

Run:  python3 tests/second_panel_guard_selftest.py             (exit 0 = all pass)
      python3 tests/second_panel_guard_selftest.py --perturb   the three swg-sub guards taken back out → RED
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib", "common.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

PERTURB = "--perturb" in sys.argv
src = open(LIB).read()
UPSRC = open(os.path.join(HERE, "..", "update.sh")).read()
if PERTURB:
    _a = "systemctl disable --now swg-panel-server swg-sub >/dev/null 2>&1 || true"
    assert src.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(_a, "systemctl disable --now swg-panel-server >/dev/null 2>&1 || true")
    for _b, _c in (("      if bare_panel_parked; then   # its panel is parked (guard_second_panel), and it is parked with it\n", "      if false; then\n"),
                   ("  [ -f /etc/systemd/system/swg-panel-server.service ] && bare_panel_parked && return 0\n", "")):
        assert UPSRC.count(_b) == 1, "perturbation anchor missing — would FALSE-PASS: %r" % _b[:60]
        UPSRC = UPSRC.replace(_b, _c)
i = src.index("guard_second_panel(){"); j = src.index("\n}\n", i) + 3
FN = src[i:j]

def run(me, docker_names_all="", docker_running="", policy="unless-stopped", unit=False, active=False, enabled=False, env=None):
    d = tempfile.mkdtemp()
    log = os.path.join(d, "log")
    unitp = os.path.join(d, "swg-panel-server.service")
    if unit:
        open(unitp, "w").write("[Unit]\n")
    stub = lambda name, body: (open(os.path.join(d, name), "w").write("#!/bin/sh\necho \"%s $*\" >> %s\n%s\n" % (name, log, body)),
                               os.chmod(os.path.join(d, name), 0o755))
    stub("docker", '''case "$1" in
  ps) case "$*" in *-a*) printf "%%s" "%s";; *) printf "%%s" "%s";; esac;;
  inspect) echo "%s";;
esac; exit 0''' % (docker_names_all, docker_running, policy))
    stub("systemctl", '''case "$1" in
  is-active) exit %d;; is-enabled) exit %d;;
esac; exit 0''' % (0 if active else 3, 0 if enabled else 1))
    fn = FN.replace("/etc/systemd/system/swg-panel-server.service", unitp)
    script = fn + "\nset -e\nguard_second_panel %s\necho CONTINUED\n" % me
    e = dict(os.environ, PATH=d + ":" + os.environ["PATH"])
    e.pop("SWG_CONVERT_DIR", None); e.pop("SWG_OTHER_PANEL", None)
    e.update(env or {})
    p = subprocess.run(["setsid", "bash", "-c", script], env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    calls = open(log).read() if os.path.exists(log) else ""
    return p.returncode, p.stdout + p.stderr, calls

print("1. nothing of the other method")
rc, out, _ = run("baremetal")
check("bare-metal install, no docker panel → continues silently", rc == 0 and "CONTINUED" in out and "!" not in out, out)
rc, out, _ = run("docker")
check("docker install, no bare unit → continues silently", rc == 0 and "CONTINUED" in out and "!" not in out, out)

print("2. a live other panel, nobody to ask")
rc, out, calls = run("baremetal", "swg-panel\n", "swg-panel\n")
check("refuses without a terminal or SWG_OTHER_PANEL", rc == 1 and "CONTINUED" not in out and "no interactive input" in out, out)
check("…and touched nothing", "stop" not in calls and "update" not in calls, calls)
rc, out, _ = run("docker", unit=True, active=True)
check("docker side: a live bare-metal panel refuses too", rc == 1 and "CONTINUED" not in out, out)
rc, out, _ = run("docker", unit=True, active=False, enabled=True)
check("an enabled-but-stopped bare panel counts as live (it returns on reboot)", rc == 1, out)
rc, out, _ = run("baremetal", "swg-panel\n", "", policy="always")
check("a stopped container with restart=always counts as live", rc == 1, out)

print("3. stop")
rc, out, calls = run("baremetal", "swg-panel\n", "swg-panel\n", env={"SWG_OTHER_PANEL": "stop"})
check("docker panel: restart=no, then stopped, then continues",
      rc == 0 and "CONTINUED" in out and "docker update --restart=no swg-panel" in calls and "docker stop swg-panel" in calls, (out, calls))
rc, out, calls = run("docker", unit=True, active=True, env={"SWG_OTHER_PANEL": "stop"})
check("bare panel: disabled --now, then continues", rc == 0 and "systemctl disable --now swg-panel-server" in calls, (out, calls))
rc, out, calls = run("docker", unit=True, active=True, env={"SWG_OTHER_PANEL": "stop", "DRYRUN": "true"})
check("dry-run stops nothing", rc == 0 and "disable" not in calls, calls)
rc, out, calls = run("docker", unit=True, active=True, env={"DRYRUN": "true"})
check("dry-run never asks — it says what it would ask and continues", rc == 0 and "CONTINUED" in out and "would ask" in out, out)

print("4. keep / abort")
rc, out, calls = run("baremetal", "swg-panel\n", "swg-panel\n", env={"SWG_OTHER_PANEL": "keep"})
check("keep → continues, untouched", rc == 0 and "CONTINUED" in out and "stop" not in calls, (out, calls))
rc, out, _ = run("baremetal", "swg-panel\n", "swg-panel\n", env={"SWG_OTHER_PANEL": "abort"})
check("abort → exit 1", rc == 1 and "CONTINUED" not in out, out)

print("5. installed but inert")
rc, out, _ = run("baremetal", "swg-panel\n", "", policy="unless-stopped")
check("stopped container, no restart-always → a note, continues", rc == 0 and "CONTINUED" in out and "leaving it alone" in out, out)
rc, out, _ = run("docker", unit=True, active=False, enabled=False)
check("stopped + disabled unit → a note, continues", rc == 0 and "CONTINUED" in out, out)

print("6. convert is exempt")
rc, out, calls = run("baremetal", "swg-panel\n", "swg-panel\n", env={"SWG_CONVERT_DIR": "convert-bare"})
check("convert → continues, no question, nothing touched", rc == 0 and "CONTINUED" in out and not calls, (out, calls))

print("7. a parked panel stays parked through update.sh")
def parked(fn_call, docker_inspect="", active=False, enabled=False):
    d = tempfile.mkdtemp()
    for name, body in (("docker", 'echo "%s"' % docker_inspect),
                       ("systemctl", 'case "$1" in is-active) exit %d;; is-enabled) exit %d;; esac' % (0 if active else 3, 0 if enabled else 1))):
        open(os.path.join(d, name), "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(os.path.join(d, name), 0o755)
    fns = src[src.index("bare_panel_parked(){"):src.index("guard_second_panel(){")]
    return subprocess.run(["bash", "-c", fns + "\n" + fn_call], env=dict(os.environ, PATH=d + ":" + os.environ["PATH"])).returncode == 0
check("a disabled, stopped unit is parked", parked("bare_panel_parked"))
check("an enabled unit is not (a crash is not a decision)", not parked("bare_panel_parked", enabled=True))
check("a running unit is not", not parked("bare_panel_parked", active=True))
check("a stopped container with restart=no is parked", parked("docker_parked swg-panel", "false no"))
check("a stopped compose container (unless-stopped) is not", not parked("docker_parked swg-panel", "false unless-stopped"))
check("a running container is not", not parked("docker_parked swg-panel", "true no"))
up = UPSRC
# the restart branch is `restart_panel_seeding_node_ep` since update.sh seeds a master's blank node endpoint while the
# panel is stopped (it restarts exactly like before when there is nothing to seed) — the ORDER is what this pins
check("update.sh leaves a parked bare panel stopped", "if bare_panel_parked; then" in up and up.index("if bare_panel_parked; then") < up.index("elif restart_panel_seeding_node_ep; then"))
check("update.sh does not count a parked container as a live stack", 'docker_parked "$_n" || { _DSTACK=yes; return 0; }' in up)
rc, out, calls = run("baremetal", "swg-panel\n", "swg-panel\n", env={"SWG_OTHER_PANEL": "stop"})
check("stopping a docker panel parks its subscription server too", "docker update --restart=no swg-sub" in calls and "docker stop swg-sub" in calls, calls)
rc, out, calls = run("docker", unit=True, active=True, env={"SWG_OTHER_PANEL": "stop"})
check("stopping a bare panel parks ITS subscription server too (disable --now swg-sub)",
      rc == 0 and "systemctl disable --now swg-panel-server swg-sub" in calls, calls)
_sub = up[up.index('if [ -f "$SUB_DIR/swg-sub" ] && [ -f "$SRC/swg-sub" ]; then'):]
_sub = _sub[:_sub.index("\n    fi\n") + 7]
check("update.sh leaves a parked panel's swg-sub stopped (refreshed on disk, not restarted)",
      "if bare_panel_parked; then   # its panel is parked" in _sub
      and _sub.index("if bare_panel_parked; then") < _sub.index("run systemctl restart swg-sub"), _sub[-400:])
_ens = up[up.index("ensure_sub_server(){"):up.index("ensure_sub_server(){") + 2500]
check("…and the heal pass does not re-enable it (ensure_sub_server returns for a parked bare panel, and only there)",
      "[ -f /etc/systemd/system/swg-panel-server.service ] && bare_panel_parked && return 0" in _ens
      and _ens.index("bare_panel_parked && return 0") < _ens.index("systemctl enable --quiet swg-sub"), _ens[:600])

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
