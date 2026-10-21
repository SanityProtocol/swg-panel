#!/usr/bin/env python3
"""Self-test — A DOCKER UPDATE NAMES ONLY THE COMPOSE GAPS OF THE SERVICES THIS BOX RUNS.

`update.sh` compares the shipped docker-compose.yml with the installed one and warns about what the installed copy
lacks (the PYDRIFT checker). The file carries every role's services, and the comparison took all of them: a client's
Docker NODE, updating to 1.8.8, was told its copy predated the release and lacked env:SWG_PANEL_SUB_BIND and
env:SWG_PANEL_SUB_PORT — keys of the swg-panel service, which the node profile never starts — and to re-run the
installer for them. The checker now takes a profile and skips a service whose `profiles:` does not name it; a service
with no `profiles:`, a top-level item (an x- anchor), a blank profile and a `profiles:` it cannot read filter nothing.
A key both services carry (SWG_UPDATE_TRIGGER) counts for every service carrying it, not the last one in the file.
A key whose whole value is "${VAR:-}" counts only where the install's .env gives VAR a value: a Docker node updating to
1.8.9 was told to re-run the installer for SWG_NFT_CLI_ONLY, an opt-in no .env sets. No readable .env -> it counts.

The profile is $prof — docker_profile's, the one the same update's `compose up` takes — so the report names the gaps of
exactly the services this update brings up.

Run: python3 tests/compose_drift_profile_selftest.py      (0 = pass)
     --perturb          drops the profile filter (the 1.8.8 shape) and expects RED.
     --perturb-shared   credits a shared key to one service only and expects RED.
     --perturb-wrap     reads a wrapped `profiles:` list's first line as the whole list and expects RED.
     --perturb-optional counts a "${VAR:-}" key whatever .env says (the 1.8.9 shape) and expects RED.
     --perturb-shell    reads .env alone, blind to the update's own shell, and expects RED.
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
assert '"$prof" "$DOCKER_DIR/.env" 2>/dev/null <<\'PYDRIFT\'' in SRC, \
    "the caller no longer hands the checker the update's profile and the install's .env"
if "--perturb" in ARGS:                       # the shape that shipped: every service's gaps, whatever the box runs
    CHECKER = plant(CHECKER, "{o for o in owners if runs(o) and matters(t, o)}", "{o for o in owners if matters(t, o)}")
if "--perturb-shared" in ARGS:                # last service in the file wins a shared key
    CHECKER = plant(CHECKER, "out.setdefault(t, set()).add(svc)", "out.__setitem__(t, {svc})")
if "--perturb-optional" in ARGS:              # every "${VAR:-}" key counts, set or not
    CHECKER = plant(CHECKER, "    if env is None or var is None or os.environ.get(var):\n        return True\n", "    return True\n")
if "--perturb-shell" in ARGS:                 # .env only: a VAR the shell running compose sets is missed
    CHECKER = plant(CHECKER, "if env is None or var is None or os.environ.get(var):", "if env is None or var is None:")
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

def drift(inst, prof, ship=SHIP, env=None, shell=None):
    e = {k: v for k, v in os.environ.items() if k not in ("SWG_NFT_CLI_ONLY", "NODE_UPDATE_TRIGGER", "SWG_UPDATE_TRIGGER")}
    e.update(shell or {})
    r = subprocess.run([sys.executable, "-I", CHK, ship, inst, prof] + ([env] if env is not None else []),
                       capture_output=True, text=True, env=e)
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

print("[10] a \"${VAR:-}\" key is named only where .env gives VAR a value")
def dotenv(text):
    N[0] += 1
    p = os.path.join(TMP, "env-%d" % N[0]); write(p, text); return p
assert re.search(r'(?m)^\s{6}SWG_NFT_CLI_ONLY: "\$\{SWG_NFT_CLI_ONLY:-\}"', SHIPPED), "anchor missing — [10] would test nothing"
nocli = installed(("SWG_NFT_CLI_ONLY:",))
plain = dotenv("# swg docker .env — profile: node\nPANEL_URL=https://panel.example\nNODE_TOKEN=abc\n")
rc, out = drift(nocli, "node", env=plain)
check("node, opt-in unset in .env: nothing named (the 1.8.9 report)", rc == 0 and out == "", out)
rc, out = drift(nocli, "node", env=dotenv("NODE_TOKEN=abc\nSWG_NFT_CLI_ONLY=1\n"))
check("node, .env sets SWG_NFT_CLI_ONLY=1: named", "env:SWG_NFT_CLI_ONLY" in out, out)
rc, out = drift(nocli, "node", env=dotenv('export SWG_NFT_CLI_ONLY="1"   # a way back\n'))
check("…an `export`ed, quoted, commented value counts too", "env:SWG_NFT_CLI_ONLY" in out, out)
rc, out = drift(nocli, "node", env=dotenv("SWG_NFT_CLI_ONLY=\n"))
check("…an empty value is unset", out == "", out)
rc, out = drift(nocli, "node", env=plain, shell={"SWG_NFT_CLI_ONLY": "1"})
check("…the update's own shell sets it (compose takes it, over .env): named", "env:SWG_NFT_CLI_ONLY" in out, out)
rc, out = drift(nocli, "node", env=dotenv("SWG_NFT_CLI_ONLY=${OTHER}\n"))
check("…a value naming another variable, not resolvable here: named", "env:SWG_NFT_CLI_ONLY" in out, out)
rc, out = drift(nocli, "node", env=os.path.join(TMP, "no-such-env"))
check("no readable .env: named, as before", "env:SWG_NFT_CLI_ONLY" in out, out)
notrig = installed(("SWG_UPDATE_TRIGGER:",))
rc, out = drift(notrig, "node", env=dotenv("NODE_UPDATE_TRIGGER=/run/swg/update\n"))
check("node, the installer's NODE_UPDATE_TRIGGER set: SWG_UPDATE_TRIGGER named", "env:SWG_UPDATE_TRIGGER" in out, out)
rc, out = drift(notrig, "host", env=dotenv("NODE_UPDATE_TRIGGER=/run/swg/update\n"))
check("host, only the node's variable set: the panel's SWG_UPDATE_TRIGGER not named", out == "", out)
rc, out = drift(notrig, "master", env=dotenv("NODE_UPDATE_TRIGGER=/run/swg/update\n"))
check("master runs the node too: named", "env:SWG_UPDATE_TRIGGER" in out, out)
rc, out = drift(installed(SUBKEYS), "host", env=plain)
check("a key with a default of its own (SWG_PANEL_SUB_BIND) stays named whatever .env says",
      "env:SWG_PANEL_SUB_BIND" in out, out)


print()
if FAILS:
    print("RED — %d failed: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("GREEN")
