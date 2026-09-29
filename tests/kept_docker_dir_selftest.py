#!/usr/bin/env python3
"""Self-test — a bare-metal install never deletes the docker data an UNINSTALL KEPT.

uninstall.sh, told to keep the data, leaves /opt/swg-panel-docker holding data/ + .env (the node token) and says
"✓ Kept /opt/swg-panel-docker/data + .env (node token) for a future reinstall". The very next `bootstrap.sh master`
printed ":: removing a stale docker leftover … (likely a cancelled bare→docker convert)" and deleted it, no prompt
(1.8.8 qualification, q1). update.sh does the same through lib/common.sh's lc_clear_convert_leftover.

What tells the two apart: a convert's staging copies docker-compose.yml in beside the data, and the uninstaller strips
it on every keep path. No compose file ⇒ kept, and said. A dry run removes nothing either way.

Both copies are lifted out AS SHIPPED — bootstrap.sh's block and lib/common.sh's function — and run over a temp
DOCKER_DIR with `docker` stubbed to list no containers.

Run: python3 tests/kept_docker_dir_selftest.py          (0 = pass)
     --perturb   the compose-file test taken out of both copies (the shipped behaviour) → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
boot = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
common = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

i = boot.index("_dryrun_flag=no;"); j = boot.index('export STEP_BASE="$STEP"', i)
bblock = boot[i:j]
m = re.search(r"^lc_clear_convert_leftover\(\)\{.*?^  return 0; \}", common, re.S | re.M)
assert m, "cannot extract lc_clear_convert_leftover — would FALSE-PASS"
cfn = m.group(0)
if PERTURB:
    a = '    if [ ! -f "$DOCKER_DIR/docker-compose.yml" ]; then\n'
    assert bblock.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    bblock = bblock.replace(a, '    if false; then\n')
    a = '[ ! -f "$dd/docker-compose.yml" ] && '
    assert cfn.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    cfn = cfn.replace(a, 'false && ')

def mkdir(kind):
    d = tempfile.mkdtemp(prefix="kdd-"); dd = os.path.join(d, "swg-panel-docker")
    os.makedirs(os.path.join(dd, "data", "lib")); open(os.path.join(dd, "data", "lib", "users.json"), "w").write("{}")
    os.makedirs(os.path.join(dd, "data", "node-confs"))
    open(os.path.join(dd, ".env"), "w").write("NODE_TOKEN=abc\n")
    if kind == "convert":
        open(os.path.join(dd, "docker-compose.yml"), "w").write("services: {}\n")
    stub = os.path.join(d, "docker"); open(stub, "w").write("#!/bin/sh\nexit 0\n"); os.chmod(stub, 0o755)   # ps -a → none
    return d, dd

def run_boot(kind, passargs=()):
    d, dd = mkdir(kind)
    script = ("set -euo pipefail\nMETHOD=baremetal; DOCKER_DIR=%s; CHOICE=keep\nPASS=(%s)\nb(){ printf %%s \"$*\"; }\n"
              "info(){ echo \"INFO $*\"; }\n%s\n") % (dd, " ".join(passargs), bblock)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return p.stdout + p.stderr, os.path.isdir(os.path.join(dd, "data"))

def run_common(kind):
    d, dd = mkdir(kind)
    script = "set -euo pipefail\ninfo(){ echo \"INFO $*\"; }\n%s\nlc_clear_convert_leftover baremetal %s\n" % (cfn, dd)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return p.stdout + p.stderr, os.path.isdir(os.path.join(dd, "data"))

print("[1] bootstrap.sh — the front door of a bare-metal (re-)install")
out, kept = run_boot("kept")
check("an uninstall's KEPT dir (data + .env, no docker-compose.yml) survives, and the run says so",
      kept and "keeping" in out and "removing" not in out, out)
out, kept = run_boot("convert")
check("a convert's staging (compose file beside the data, no container) is still cleared", not kept and "removing" in out, out)
out, kept = run_boot("convert", ("--dry-run",))
check("…but not on --dry-run: a dry run changes nothing", kept and "would remove" in out, out)

print("\n[2] lib/common.sh lc_clear_convert_leftover — update.sh's copy of the same decision")
out, kept = run_common("kept")
check("the KEPT dir survives an update, and the run says so", kept and "keeping" in out, out)
out, kept = run_common("convert")
check("a convert's staging is still cleared", not kept and "removing" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
