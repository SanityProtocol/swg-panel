#!/usr/bin/env python3
"""Self-test — converting a bare-metal box to Docker installs Docker, before it touches anything else.

A bare-metal box asked to become a Docker one usually has no Docker yet. The pre-flight said "pre-flight OK",
the operator said yes, and convert.sh answered "✗ docker is required" (1.8.8 qualification, a 1.8.7 master VM
converted by hand) — while install-docker.sh, which the conversion hands off to, installs Docker for a fresh
install. Now the conversion installs it the same way and proves the daemon answers, BEFORE the recovery marker
and the staging, so a failure leaves the bare-metal install serving and nothing to resume.

The block is lifted out of convert.sh as shipped and run under bash with `docker`, `sh` and `systemctl` stubs.

Run: python3 tests/convert_installs_docker_selftest.py            (0 = pass)
     --perturb   the old refusal put back → RED
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
SRC = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

a = SRC.index("  # ⚠️ DOCKER IS INSTALLED HERE, NOT REFUSED.")
b = SRC.index('  info "Converting the bare-metal $(b "$ROLE") → docker', a)
block = SRC[a:b]
if PERTURB:
    block = '  command -v docker >/dev/null 2>&1 || die "docker is required"\n'

print("[1] the order: Docker first, then the recovery marker and the staging")
rec = SRC.index('write_recovery ""', b)
check("the install block sits before `write_recovery` in the bare→docker path", a < rec and b < rec)
check("the pre-flight names it", "the conversion installs it first" in SRC)

def run(have_docker, install_ok=True, daemon_ok=True):
    d = tempfile.mkdtemp(); log = os.path.join(d, "log"); state = os.path.join(d, "installed")
    if have_docker:
        open(state, "w").close()
    def stub(name, body):
        p = os.path.join(d, name); open(p, "w").write("#!/bin/bash\necho \"%s $*\" >> %s\n%s\n" % (name, log, body)); os.chmod(p, 0o755)
    # `docker` exists only once "installed"; `docker info` answers per daemon_ok
    stub("docker-real", 'exit %d' % (0 if daemon_ok else 1))
    stub("sh", ('[ -n "$2" ] && case "$2" in *get.docker.com*) %s ;; esac; exit 0'
                % ('/usr/bin/touch %s; /usr/bin/ln -sf %s/docker-real %s/docker; exit 0' % (state, d, d) if install_ok else 'exit 1')))
    stub("systemctl", "exit 0"); stub("sleep", "exit 0")
    if have_docker:
        os.symlink(os.path.join(d, "docker-real"), os.path.join(d, "docker"))
    script = ('set -u\nROLE=master\nb(){ printf %%s "$*"; }\ninfo(){ echo "INFO $*"; }\ndie(){ echo "DIE $*"; exit 1; }\n'
              '%s\necho REACHED-STAGING\n') % block
    env = dict(os.environ, PATH=d)   # ONLY the stubs: this machine has a real docker in /usr/bin
    p = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env)
    return p.stdout + p.stderr, (open(log).read() if os.path.exists(log) else "")

print("\n[2] no Docker on the box → it is installed, and the conversion goes on")
out, calls = run(have_docker=False)
check("get.docker.com is run", "get.docker.com" in calls, calls)
check("…and the conversion reaches the staging", "REACHED-STAGING" in out, out)

print("\n[3] Docker already there → nothing installed")
out, calls = run(have_docker=True)
check("no install", "get.docker.com" not in calls and "REACHED-STAGING" in out, (out, calls))

print("\n[4] the install fails / the daemon does not answer → stop BEFORE anything is touched, and say so")
out, calls = run(have_docker=False, install_ok=False)
check("install failed → stops, 'nothing has been changed'", "REACHED-STAGING" not in out and "nothing has been changed" in out, out)
out, calls = run(have_docker=True, daemon_ok=False)
check("daemon down → stops, 'nothing has been changed'", "REACHED-STAGING" not in out and "nothing has been changed" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
