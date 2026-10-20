#!/usr/bin/env python3
"""Self-test — A DOCKER UPDATE NAMES ONLY THE COMPOSE GAPS OF THE SERVICES THIS BOX RUNS.

`update.sh` compares the shipped docker-compose.yml with the installed one and warns about what the installed copy
lacks (the PYDRIFT checker). The file carries every role's services, and the comparison took all of them: a client's
Docker NODE, updating to 1.8.8, was told its copy predated the release and lacked env:SWG_PANEL_SUB_BIND and
env:SWG_PANEL_SUB_PORT — keys of the swg-panel service, which the node profile never starts — and to re-run the
installer for them. The checker now takes a profile and skips a service whose `profiles:` does not name it; a service
with no `profiles:`, a top-level item (an x- anchor), a blank profile and a `profiles:` it cannot read filter nothing.
A key both services carry (SWG_UPDATE_TRIGGER) counts for every service carrying it, not the last one in the file.

The profile is $prof — docker_profile's, the one the same update's `compose up` takes — so the report names the gaps of
exactly the services this update brings up.

Run: python3 tests/compose_drift_profile_selftest.py      (0 = pass)
     --perturb          drops the profile filter (the 1.8.8 shape) and expects RED.
     --perturb-shared   credits a shared key to one service only and expects RED.
     --perturb-wrap     reads a wrapped `profiles:` list's first line as the whole list and expects RED.
"""
import atexit, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
UPDATE = os.environ.get("SWG_UPDATE_SH") or os.path.join(ROOT, "update.sh")
ARGS = set(sys.argv[1:])

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, old, new):
    assert src.count(old) == 1, "plant anchor missing: %r" % old
    return src.replace(old, new)

def write(path, text):
    with open(path, "w") as f:
        f.write(text)

SRC = open(UPDATE, encoding="utf-8").read()
m = re.search(r"<<'PYDRIFT'\n(.*?)\nPYDRIFT\n", SRC, re.S)
assert m, "anchor missing — the embedded checker is gone; this run would FALSE-PASS"
CHECKER = m.group(1)
assert '"$prof" 2>/dev/null <<\'PYDRIFT\'' in SRC, "the caller no longer hands the checker the update's profile"
if "--perturb" in ARGS:                       # the shape that shipped: every service's gaps, whatever the box runs
    CHECKER = plant(CHECKER, "{o for o in owners if runs(o)}", "owners")
if "--perturb-shared" in ARGS:                # last service in the file wins a shared key
    CHECKER = plant(CHECKER, "out.setdefault(t, set()).add(svc)", "out.__setitem__(t, {svc})")
if "--perturb-wrap" in ARGS:                  # whatever names sit on the `profiles:` line are the list
    CHECKER = plant(CHECKER, r"""re.findall(r'[A-Za-z0-9_-]+', f.group(1)) if f else []""",
                    r"""re.findall(r'[A-Za-z0-9_-]+', line.split(":", 1)[1].split("#")[0])""")

SHIP = os.path.join(ROOT, "docker-compose.yml")
SHIPPED = open(SHIP, encoding="utf-8").read()
TMP = tempfile.mkdtemp(prefix="driftgate-")
atexit.register(shutil.rmtree, TMP, True)
CHK = os.path.join(TMP, "checker.py"); write(CHK, CHECKER)
N = [0]

def installed(drop_lines=(), drop_service=None):
    """The shipped compose with some lines (and optionally a whole service block) taken out — an older install."""
    out, skip = [], False
    for line in SHIPPED.splitlines():
        if drop_service and re.match(r'^  [a-z0-9-]+:\s*$', line):
            skip = line.strip().rstrip(":") == drop_service
        if skip or any(d in line for d in drop_lines):
            continue
        out.append(line)
    N[0] += 1
    p = os.path.join(TMP, "inst-%d.yml" % N[0]); write(p, "\n".join(out) + "\n")
    return p

def drift(inst, prof, ship=SHIP):
    r = subprocess.run([sys.executable, "-I", CHK, ship, inst, prof], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()

SUBKEYS = ("SWG_PANEL_SUB_BIND:", "SWG_PANEL_SUB_PORT:")
old = installed(SUBKEYS)                      # the client's copy: the two keys 1.8.8 added to swg-panel

print("[1] the client's report: a node is not told about the panel's keys")
rc, out = drift(old, "node")
check("node: nothing named", rc == 0 and out == "", out)

print("[2] a box that runs the panel still is")
for prof in ("host", "master", "host-node"):
    rc, out = drift(old, prof)
    check("%s: both keys named" % prof, "env:SWG_PANEL_SUB_BIND" in out and "env:SWG_PANEL_SUB_PORT" in out, out)

print("[3] a gap in the node's own service is named on a node")
rc, out = drift(installed(SUBKEYS + ("TURN_MANAGE:",)), "node")
check("node: env:TURN_MANAGE named, the panel's keys not",
      out.startswith("1|") and "env:TURN_MANAGE" in out and "SWG_PANEL_SUB" not in out, out)

print("[4] a key both services carry is named for each box that runs either")
shared = installed(("SWG_UPDATE_TRIGGER:",))
for prof in ("host", "node", "master"):
    rc, out = drift(shared, prof)
    check("%s: env:SWG_UPDATE_TRIGGER named" % prof, "env:SWG_UPDATE_TRIGGER" in out, out)

print("[5] a missing service the profile does not run is not named; one it runs is")
nosub = installed(drop_service="swg-sub")
rc, out = drift(nosub, "node")
check("node without swg-sub: nothing named", out == "", out)
rc, out = drift(nosub, "host")
check("host without swg-sub: the service named", out.split("|")[1:2] == ["swg-sub"], out)

print("[6] a top-level item is every profile's")
rc, out = drift(installed(SUBKEYS + ("x-logging:",)), "node")
check("node: anchor:x-logging named", "anchor:x-logging" in out and "SWG_PANEL_SUB" not in out, out)

print("[7] a `profiles:` this reader cannot read whole hides nothing")
PANEL_PROFILES = r'(?m)^(    profiles:) \["host", "master", "host-node"\](.*)$'
for name, repl in (("a block list", r'\1\2\n      - host\n      - master'),
                   ("a wrapped flow list", r'\1 ["node",\2\n      "host", "master"]')):
    ship = os.path.join(TMP, "ship-%d.yml" % len(name))
    text, n = re.subn(PANEL_PROFILES, repl, SHIPPED, count=1)
    assert n == 1, "anchor missing — swg-panel's profiles: line changed; [7] would test nothing"
    write(ship, text)
    rc, out = drift(old, "host", ship)
    check("%s: the panel's keys still named on a host" % name, "env:SWG_PANEL_SUB_BIND" in out, out)

print("[8] a blank profile compares the whole file")
rc, out = drift(old, "")
check("blank profile: both keys named", "env:SWG_PANEL_SUB_BIND" in out and "env:SWG_PANEL_SUB_PORT" in out, out)

print("[9] an up-to-date copy says nothing under any profile")
same = installed()
check("identical: silent", all(drift(same, p)[1] == "" for p in ("node", "host", "master", "")))


print()
if FAILS:
    print("RED — %d failed: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("GREEN")
