#!/usr/bin/env python3
"""Self-test — a Docker update never takes a working stack down for nothing.

Found by the 1.8.8 qualification on a Docker master VM. update.sh's prebuilt-image branch ran, in order,
`docker rm -f` on the panel and node containers, THEN `compose pull`, THEN `up -d --force-recreate`:

  · a pull that failed (registry unreachable or filtered, rate limit, full disk) left the box with its
    containers REMOVED and nothing started — panel, node and every client down until someone ssh'd in;
  · a pull that brought nothing new still recreated every container, and a docker node's interfaces live in
    its container: every press of Update — which the dialog says is worth pressing when already up to date —
    and every node update a panel update fans out cut every client's tunnel for 20–40 s (measured).

Now the pull runs first, while the stack still runs; a failed pull touches nothing; and when every container
already runs the image its reference names, only `compose up -d` runs (it recreates just a service whose
compose settings changed). The destructive recreate is kept for a real image change, a stopped or missing
container, and anything the check cannot read.

The branch and `docker_images_current` are lifted out of update.sh as SHIPPED and run under bash with a stub
`docker` on PATH that records every call. No docker, no network.

Run: python3 tests/docker_update_recreate_selftest.py            (0 = pass)
     --perturb-order   the pull moved back after `docker rm -f` (the shipped order) → RED
     --perturb-skip    the "already current" check never says yes (the shipped recreate-always) → RED
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
UPDATE = os.environ.get("SWG_UPDATE_SH") or os.path.join(ROOT, "update.sh")
P_ORDER = "--perturb-order" in sys.argv
P_SKIP = "--perturb-skip" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(UPDATE, encoding="utf-8").read()
fn = re.search(r"\ndocker_images_current\(\)\{.*?\n\}\n", SRC, re.S)
assert fn, "anchor missing: docker_images_current — this run would FALSE-PASS"
i = SRC.index("    # prebuilt-image deployment (default)")
j = SRC.index('    else warn "docker ($prof): skipped"; note "docker ($prof): skipped"; fi\n', i)
branch = SRC[i:j] + '    else warn "docker ($prof): skipped"; note "docker ($prof): skipped"; fi\n'
helper = fn.group(0)
if P_SKIP:
    a = "sys.exit(0)\nPYIMG"
    assert helper.count(a) == 1, "perturbation anchor missing"
    helper = helper.replace(a, "sys.exit(1)\nPYIMG")
if P_ORDER:
    # the shipped order: remove the containers, then pull + up in one go
    a = '''      elif ! ( cd "$DOCKER_DIR" && on_tty $COMPOSE --profile "$prof" pull ); then'''
    assert branch.count(a) == 1, "perturbation anchor missing"
    branch = branch.replace(a, '''      elif ! { for _c in swg-panel swg-node; do docker ps -aq -f "name=$_c" | xargs -r docker rm -f; done; ( cd "$DOCKER_DIR" && on_tty $COMPOSE --profile "$prof" pull ); }; then''')

TMP = tempfile.mkdtemp(prefix="dkupd-")
BIN = os.path.join(TMP, "bin"); os.makedirs(BIN)
LOG = os.path.join(TMP, "calls.log")
# The stub: `docker compose …` and the three plain `docker` queries the code asks; state comes from env.
open(os.path.join(BIN, "docker"), "w").write(r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
open(os.environ["CALLS"], "a").write(" ".join(a) + "\n")
if a[:1] == ["compose"]:
    if "pull" in a:
        sys.exit(int(os.environ.get("PULL_RC", "0")))
    if "config" in a:
        if os.environ.get("CONFIG_RC", "0") != "0":
            sys.exit(1)
        print(json.dumps({"services": {
            "swg-panel": {"image": "ghcr.io/x/swg-panel:t", "container_name": "swg-panel"},
            "swg-sub": {"image": "ghcr.io/x/swg-panel:t", "container_name": "swg-sub"},
            "swg-node": {"image": "ghcr.io/x/swg-node:t", "container_name": "swg-node"}}}))
        sys.exit(0)
    if "up" in a:
        sys.exit(0)
    sys.exit(0)
if a[:2] == ["image", "inspect"]:
    print(json.loads(os.environ["WANT"]).get(a[-1], "")); sys.exit(0)
if a[:1] == ["inspect"]:
    v = json.loads(os.environ["HAVE"]).get(a[-1])
    if v is None:
        sys.exit(1)
    print(v); sys.exit(0)
if a[:1] == ["ps"]:
    print("cid-" + a[-1].split("=", 1)[-1]); sys.exit(0)
if a[:1] == ["rm"]:
    sys.exit(0)
sys.exit(0)
''')
os.chmod(os.path.join(BIN, "docker"), 0o755)

HARNESS = r'''set -u
DOCKER_DIR="$TMPD"; COMPOSE="docker compose"; DRYRUN=false; prof=master; DID_UPDATE=no; DID_FAIL=no
have(){ command -v "$1" >/dev/null 2>&1; }
confirm(){ return 0; }; col_l(){ printf %s "$*"; }; on_tty(){ "$@"; }
info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; note(){ echo "NOTE $*"; }
docker_ports_preflight(){ return 0; }; rescue_container_confs(){ :; }
''' + helper + "\n" + branch + "echo \"DID_UPDATE=$DID_UPDATE DID_FAIL=$DID_FAIL\"\n"

IMG = {"ghcr.io/x/swg-panel:t": "sha256:P2", "ghcr.io/x/swg-node:t": "sha256:N2"}
def run(pull_rc=0, config_rc=0, have=None):
    open(LOG, "w").close()
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"], CALLS=LOG, TMPD=TMP,
               PULL_RC=str(pull_rc), CONFIG_RC=str(config_rc), WANT=json.dumps(IMG), HAVE=json.dumps(have or {}))
    p = subprocess.run(["bash", "-c", HARNESS], capture_output=True, text=True, env=env)
    return p.stdout + p.stderr, open(LOG).read()

CUR = {"swg-panel": "sha256:P2 true", "swg-sub": "sha256:P2 true", "swg-node": "sha256:N2 true"}

print("[1] a pull that fails touches nothing — the stack keeps running")
out, calls = run(pull_rc=1, have=CUR)
check("no container removed", "rm -f" not in calls and "rm " not in calls, calls)
check("no `up` either", " up " not in (" " + calls), calls)
check("…and the run says it failed (DID_FAIL=yes)", "DID_FAIL=yes" in out and "nothing was touched" in out, out)

print("\n[2] nothing new pulled → nothing recreated")
out, calls = run(have=CUR)
check("the pull ran", "compose --profile master pull" in calls, calls)
check("no container removed", "rm " not in calls, calls)
check("`up -d` WITHOUT --force-recreate", "up -d" in calls and "--force-recreate" not in calls, calls)
check("…and it is not counted as an update (DID_UPDATE=no)", "DID_UPDATE=no DID_FAIL=no" in out, out)

print("\n[3] a real image change still recreates, as before")
out, calls = run(have=dict(CUR, **{"swg-node": "sha256:N1 true"}))
check("the old containers are removed, then `up -d --force-recreate`",
      "rm -f" in calls and "up -d --force-recreate" in calls and calls.index("pull") < calls.index("rm -f"), calls)
check("…counted as an update", "DID_UPDATE=yes DID_FAIL=no" in out, out)

print("\n[4] what the check cannot vouch for takes the full path")
for why, kw in (("a stopped container", dict(have=dict(CUR, **{"swg-panel": "sha256:P2 false"}))),
                ("a missing container", dict(have={k: v for k, v in CUR.items() if k != "swg-sub"})),
                ("compose cannot render its config", dict(config_rc=1, have=CUR))):
    out, calls = run(**kw)
    check(why + " → recreate", "up -d --force-recreate" in calls, calls)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (P_ORDER or P_SKIP) else ""))
sys.exit(2 if (P_ORDER or P_SKIP) else 0)
