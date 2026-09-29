#!/usr/bin/env python3
"""Self-test: a FRESH, default (image-pulling) docker panel install wires the address helper, swg-netctl-docker.

Measured in the 1.8.8-beta qualification: every fresh non-`--build` docker panel install printed
"! docker/swg-netctl-docker missing — one-click address changes will fall back to a manual restart". The default
install stages only docker-compose.yml into /opt/swg-panel-docker — the docker/ directory is copied only by
`--build` — but wire_docker_netctl looked for the drainer at $INSTALL_DIR/docker/swg-netctl-docker. The first
update.sh healed it (ensure_netctl_docker installs from the SOURCE tree), so the gap lived exactly as long as the
operator never pressed Update.

  [1] wire_docker_netctl, run as shipped against an install dir that holds only what a default install stages
      (no docker/), installs the drainer and its three units and does not warn
  [2] the installed drainer is the source tree's swg-netctl-docker, byte for byte
  [3] a node profile still wires nothing (panel-bearing profiles only)

The function is lifted out of install-docker.sh verbatim; only its two absolute system paths (/etc/systemd/system,
/usr/local/bin) are pointed into a temp dir, and `systemctl` is a recording stub.

Run: python3 tests/docker_netctl_wired_fresh_selftest.py      (0 = pass)
     --perturb   restores the shipped lookup ($INSTALL_DIR/docker only) → RED
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
m = re.search(r"^wire_docker_netctl\(\)\{\n.*?\n\}\n", src, re.S | re.M)
assert m, "wire_docker_netctl missing — this run would FALSE-PASS"
fn = m.group(0)
if PERTURB:
    blk = re.search(r'  local drainer="\$SRC/docker/swg-netctl-docker"\n  \[ -f "\$drainer" \] \|\| drainer="\$INSTALL_DIR/docker/swg-netctl-docker"\n', fn)
    assert blk, "perturbation anchor missing — this run would FALSE-PASS"
    fn = fn[:blk.start()] + '  local drainer="$INSTALL_DIR/docker/swg-netctl-docker"\n' + fn[blk.end():]

T = tempfile.mkdtemp(prefix="netctlwire-")
SD, BIN, STUB = os.path.join(T, "systemd"), os.path.join(T, "usrlocalbin"), os.path.join(T, "stub")
for d in (SD, BIN, STUB):
    os.makedirs(d)
fn = fn.replace("/etc/systemd/system", SD).replace("/usr/local/bin", BIN)
assert "/etc/systemd" not in fn and "/usr/local/bin" not in fn
open(os.path.join(STUB, "systemctl"), "w").write('#!/bin/sh\necho "systemctl $*" >> "%s/systemctl.log"\n' % T)
os.chmod(os.path.join(STUB, "systemctl"), 0o755)


def wire(profile):
    inst = os.path.join(T, "inst-" + profile)
    os.makedirs(inst)
    shutil.copy(os.path.join(ROOT, "docker-compose.yml"), inst)   # exactly what a default install stages
    script = ('set -euo pipefail\nDRYRUN=false; PROFILE=%s; SRC="%s"; INSTALL_DIR="%s"\n'
              'ok(){ echo "OK $*"; }; warn(){ echo "WARN $*" >&2; }; b(){ printf %%s "$*"; }\n%s\nwire_docker_netctl\n'
              ) % (profile, ROOT, inst, fn)
    r = subprocess.run(["bash", "-c", script], env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    return r, inst


print("[1] a default install (compose file only, no docker/) wires the helper")
r, inst = wire("host")
out = r.stdout + r.stderr
check("the install dir has no docker/ — the shape a non---build install stages", not os.path.exists(os.path.join(inst, "docker")))
check("it ran clean", r.returncode == 0, (r.returncode, out[-300:]))
check("⚠️ no 'swg-netctl-docker missing' warning", "missing" not in out, out[-300:])
check("the drainer is installed", os.path.isfile(os.path.join(BIN, "swg-netctl-docker")))
check("…with its .service, .path and .timer",
      all(os.path.isfile(os.path.join(SD, "swg-netctl-docker." + u)) for u in ("service", "path", "timer")), os.listdir(SD))
check("the .path watches this install's queue",
      os.path.isfile(os.path.join(SD, "swg-netctl-docker.path")) and
      ("DirectoryNotEmpty=%s/data/lib/netctl/queue" % inst) in open(os.path.join(SD, "swg-netctl-docker.path")).read())

print("\n[2] it is the source tree's drainer")
check("byte-identical to docker/swg-netctl-docker",
      os.path.isfile(os.path.join(BIN, "swg-netctl-docker")) and
      open(os.path.join(BIN, "swg-netctl-docker"), "rb").read() == open(os.path.join(ROOT, "docker", "swg-netctl-docker"), "rb").read())

print("\n[3] a node profile wires nothing")
shutil.rmtree(BIN); os.makedirs(BIN)
r, _ = wire("node")
check("no drainer for a node", r.returncode == 0 and not os.listdir(BIN), (r.returncode, os.listdir(BIN)))

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
