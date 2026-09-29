#!/usr/bin/env python3
"""Self-test — AN UPDATE READS A STOPPED DOCKER CONTAINER'S VERSION FROM ITS IMAGE (N11).

A pull install stages no VERSION file of its own: only a --build install copies the source's, and staging one for a pull
would be a guess (it pulls a tag, not this checkout). update.sh's docker_ver read the RUNNING container, then that staged
file — so with the containers stopped, the update's header showed no current version at all ("latest is …" with nothing
to compare), the one thing the missing file cost (1.8.8 qualification, round 10, N11). A stopped container still holds
its image's VERSION: `docker cp` reads it where `docker exec` cannot.

  [1] docker_ver (update.sh), driven against a docker stub: a running container → exec's answer; a STOPPED one → the
      image's file through docker cp; no container → the staged $DOCKER_DIR/VERSION; nothing at all → "?"; under
      set -euo pipefail, never aborting
  [2] install-docker.sh stages VERSION only for a --build install (the file a pull install lacks is not invented)

Run: python3 tests/docker_ver_stopped_selftest.py        (0 = pass)
     --perturb   the docker cp read taken out → [1] red
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
UPATH = os.environ.get("SWG_DV_UPDATE") or os.path.join(ROOT, "update.sh")
U = open(UPATH, encoding="utf-8").read()
PLANT = ('  if [ -z "$v" ] && have docker; then\n'
         '    v="$(docker cp "$c:$path" - 2>/dev/null | tar -xOf - 2>/dev/null | sed -n 1p | tr -d \'[:space:]\' || true)"; fi\n')
if "--perturb" in sys.argv:
    if U.count(PLANT) != 1:
        print("  STALE ANCHOR (%d) — this plant would plant nothing" % U.count(PLANT)); sys.exit(1)
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-cp"); f.write(U.replace(PLANT, "")); f.close()
    r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_DV_UPDATE=f.name), capture_output=True, text=True, timeout=120)
    os.unlink(f.name)
    red = "FAIL [1] a STOPPED container" in r.stdout and r.returncode != 0
    print("  cp  %s" % ("caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
    print("1 plants, %d caught" % (1 if red else 0))
    sys.exit(0 if red else 1)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

DV = fn(U, "docker_ver")
def ver(mode, staged=None, docker=True):
    t = tempfile.mkdtemp(prefix="dv-")
    img = os.path.join(t, "img"); os.makedirs(img); open(os.path.join(img, "VERSION"), "w").write("1.8.7-beta\n")
    dd = os.path.join(t, "docker-dir"); os.makedirs(dd)
    if staged:
        open(os.path.join(dd, "VERSION"), "w").write(staged + "\n")
    stub = os.path.join(t, "bin"); os.makedirs(stub)
    if docker:
        open(os.path.join(stub, "docker"), "w").write(
            '#!/bin/bash\ncase "$1" in\n'
            '  exec) [ "%s" = running ] && { echo "1.8.8-beta"; exit 0; }; echo "Error response from daemon: container is not running" >&2; exit 1;;\n'
            '  cp) case "%s" in running|stopped) tar -cf - -C "%s" VERSION; exit 0;; esac; echo "Error: No such container" >&2; exit 1;;\n'
            'esac\nexit 1\n' % (mode, mode, img))
        os.chmod(os.path.join(stub, "docker"), 0o755)
    for tool in ("tar", "sed", "tr", "cat", "bash"):
        src = __import__("shutil").which(tool)
        if src:
            os.symlink(src, os.path.join(stub, tool))
    script = ('set -euo pipefail\nDOCKER_DIR="%s"\nhave(){ command -v "$1" >/dev/null 2>&1; }\n'
              'oldver(){ cat "$1/VERSION" 2>/dev/null || echo \'?\'; }\n%sprintf "[%%s]" "$(docker_ver swg-panel /opt/swg-panel/VERSION)"\necho " RC=$?"\n') % (dd, DV)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=dict(os.environ, PATH=stub))
    return r.stdout.strip(), r.returncode, r.stderr

print("[1] docker_ver")
out, rc, err = ver("running")
check("[1] a running container → exec's answer", out == "[1.8.8-beta] RC=0", (out, rc, err))
out, rc, err = ver("stopped")
check("[1] a STOPPED container → its image's VERSION, through docker cp", out == "[1.8.7-beta] RC=0", (out, rc, err))
out, rc, err = ver("gone", staged="1.8.6-beta")
check("[1] no container → the staged $DOCKER_DIR/VERSION (a --build install's)", out == "[1.8.6-beta] RC=0", (out, rc, err))
out, rc, err = ver("gone")
check("[1] nothing at all → \"?\" — and set -euo pipefail never aborts on the way", out == "[?] RC=0" and rc == 0, (out, rc, err))
out, rc, err = ver("gone", docker=False)
check("[1] no docker client → the staged file or \"?\", no abort", out == "[?] RC=0" and rc == 0, (out, rc, err))

print("\n[2] what install-docker.sh stages")
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
i_if = D.find("if $BUILD; then\n  for f in Dockerfile Dockerfile.node .dockerignore VERSION \\\n")
i_fi = D.find("\nfi\n", i_if)
check("[2] VERSION is staged only inside the --build branch (a pull install gets no guessed file)",
      i_if > 0 and D.count(" VERSION \\\n") == 1 and i_if < D.find(" VERSION \\\n") < i_fi, (i_if, i_fi))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
