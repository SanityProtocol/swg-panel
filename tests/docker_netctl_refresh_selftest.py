#!/usr/bin/env python3
"""Self-test: an update brings the docker address helper's drainer, swg-netctl-docker, to this release.

Measured in the 1.8.9 qualification (P3, the docker-pristine cell, 10 of 10 updates): ensure_netctl_docker installed the
drainer only when it was MISSING, so a Docker panel updated from 1.8.8 kept 1.8.8's drainer behind 1.8.9's idle gate —
without dace39ce's queue sweep, which clears the strays (an abandoned .json.tmp, a dotfile, a stale claim) the gate's
"is anything queued?" relies on being gone.

  [1] a box updated from 1.8.8 (its drainer the last release's, its units in place): the drainer becomes the source
      tree's, byte for byte, RENAMED in (a new inode — install(1) rewrites a file in place, and the timer may start the
      drainer at any moment); its units are not touched; the update says so
  [2] a drainer already this release's: nothing written (the same inode), nothing said
  [3] a dry run: the old drainer stays, and the run says what it would do
  [4] a node profile: nothing

The function is lifted out of update.sh verbatim; only its two absolute system paths (/etc/systemd/system,
/usr/local/bin) are pointed into a temp dir, and `systemctl` is a recording stub. The last release's drainer is read
from git (origin/main's docker/swg-netctl-docker).

Run: python3 tests/docker_netctl_refresh_selftest.py      (0 = pass)
     --perturb   the drainer is installed only when missing again (as shipped) → RED
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
m = re.search(r"^ensure_netctl_docker\(\)\{[^\n]*\n.*?\n\}\n", src, re.S | re.M)
assert m, "ensure_netctl_docker missing — this run would FALSE-PASS"
fn = m.group(0)
if PERTURB:
    a = '  if [ -x /usr/local/bin/swg-netctl-docker ] && ! cmp -s "$drainer" /usr/local/bin/swg-netctl-docker; then\n'
    assert fn.count(a) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    fn = fn.replace(a, "  if false; then\n")

T = tempfile.mkdtemp(prefix="netctlrefresh-")
SD, BIN, STUB, DD = (os.path.join(T, d) for d in ("systemd", "usrlocalbin", "stub", "docker"))
fn = fn.replace("/etc/systemd/system", SD).replace("/usr/local/bin", BIN)
assert "/etc/systemd" not in fn and "/usr/local/bin" not in fn
NEW = open(os.path.join(ROOT, "docker", "swg-netctl-docker"), "rb").read()
old = subprocess.run(["git", "-C", ROOT, "show", "origin/main:docker/swg-netctl-docker"], capture_output=True)
OLD = old.stdout if old.returncode == 0 and old.stdout else b"#!/usr/bin/env python3\n# a drainer from an older release\n"
check("the last release's drainer is not this one's (else [1] proves nothing)", OLD != NEW)
UNITS = {"swg-netctl-docker.service": "[Service]\nType=oneshot\nExecStart=%s/swg-netctl-docker\n" % BIN,
         "swg-netctl-docker.path": "[Path]\nDirectoryNotEmpty=%s/data/lib/netctl/queue\n" % DD,
         "swg-netctl-docker.timer": "[Timer]\nOnActiveSec=10s\nOnUnitActiveSec=10s\nAccuracySec=1s\n"}


def box(drainer):
    """A docker panel's host as an update finds it: the drainer given, its three units in the queue-watch form."""
    for d in (SD, BIN, STUB, DD):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for n, t in UNITS.items():
        open(os.path.join(SD, n), "w").write(t)
    p = os.path.join(BIN, "swg-netctl-docker"); open(p, "wb").write(drainer); os.chmod(p, 0o755)
    open(os.path.join(STUB, "systemctl"), "w").write('#!/bin/sh\necho "systemctl $*" >> "%s/systemctl.log"\n' % T)
    os.chmod(os.path.join(STUB, "systemctl"), 0o755)
    return p


def run(profile, dry=False):
    script = ('set -uo pipefail\nDRYRUN=%s; SRC="%s"; DOCKER_DIR="%s"; DID_UPDATE=no; RESULTS=()\n'
              'info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*" >&2; }; note(){ echo "NOTE $*"; }\n'
              '%s\nensure_netctl_docker %s\necho "DID_UPDATE=$DID_UPDATE"\n') % ("true" if dry else "false", ROOT, DD, fn, profile)
    r = subprocess.run(["bash", "-c", script], env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    return r, r.stdout + r.stderr


def units_untouched():
    return all(open(os.path.join(SD, n)).read() == t for n, t in UNITS.items())


print("[1] a box updated from the last release: its drainer becomes this release's")
p = box(OLD); ino = os.stat(p).st_ino
r, out = run("host")
check("it ran clean", r.returncode == 0, (r.returncode, out[-300:]))
check("the drainer is the source tree's, byte for byte", open(p, "rb").read() == NEW)
check("…renamed in: a new inode (a running drainer keeps the file it started from)", os.stat(p).st_ino != ino)
check("…executable", os.access(p, os.X_OK))
check("no .new left beside it", not os.path.exists(p + ".new"), os.listdir(BIN))
check("its units are not touched (the heal never rewrites a unit)", units_untouched())
check("the update says so (DID_UPDATE, a note)", "DID_UPDATE=yes" in out and "NOTE docker address helper: this release's drainer" in out,
      out[-300:])

print("\n[2] a drainer already this release's: nothing written, nothing said")
p = box(NEW); ino = os.stat(p).st_ino
r, out = run("host")
check("the same inode, the same bytes", os.stat(p).st_ino == ino and open(p, "rb").read() == NEW)
check("nothing said", "NOTE docker address helper" not in out and "DID_UPDATE=no" in out, out[-300:])

print("\n[3] a dry run: the old drainer stays, and the run says what it would do")
p = box(OLD)
r, out = run("host", dry=True)
check("the drainer is still the last release's", open(p, "rb").read() == OLD)
check("…and the run says it would install this release's", "[skip] install this release's" in out, out[-300:])

print("\n[4] a node profile: nothing")
p = box(OLD)
r, out = run("node")
check("the drainer is untouched", open(p, "rb").read() == OLD and "NOTE" not in out, out[-200:])

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
