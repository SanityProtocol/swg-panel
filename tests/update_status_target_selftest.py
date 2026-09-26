#!/usr/bin/env python3
"""Self-test — an update reports its status to the panel that is RUNNING, and posts a node status only for a node.

  N2  On a box carrying both panels — the bare one parked (guard_second_panel) beside a live docker panel — update.sh
      wrote its final status into the PARKED panel's /var/lib/swg-panel/host_proc: the bare file was taken whenever the
      bare panel was installed, the docker one only when there was none. The live docker panel's header stayed
      "updating" and /api/state read "update failed" for a run that exited 0 (1.8.8 qualification, R8).
  N4  A docker panel-only install carries the placeholder NODE_TOKEN=set-in-nodes-screen, and update.sh POSTed it to
      /api/node/proc-status as a node token: 401, a 6 s + 25 s wait and two "couldn't reach the panel to record …"
      lines on every update of a box with no node (1.8.7 did the same).

  [1] bare panel parked + docker panel live → the DOCKER panel's host_proc; no node POST (there is no node)
  [2] a bare panel alone → its own host_proc (unchanged)
  [3] a docker master → the docker host_proc + the node's .env token, its loopback URL (and a bridged
      https://swg-panel:… URL rewritten to the host's loopback port, unverified) — unchanged
  [4] a docker panel-only install (placeholder token, no swg-node) → the docker host_proc and NO node POST
  [5] a docker node only → the node POST, no panel file (unchanged)
  [6] a bare node beside a docker panel → the docker panel's host_proc AND the bare node's POST
  [7] --node-only → no panel file at all
  [8] both panels live (kept both) → the bare panel's file, as before

lc_targets comes from update.sh and bare_panel_parked / docker_panel_live / docker_parked from lib/common.sh, AS
SHIPPED; systemctl and docker are stubs, the fixed paths are moved under a temp root.

Run: python3 tests/update_status_target_selftest.py     (0 = pass)
     --perturb   the shipped selection planted back (bare file first, placeholder token accepted) → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
UP = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b):
    global UP
    assert UP.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    UP = UP.replace(a, b)

if PERTURB:
    plant('    if [ -f "$PANEL_DIR/swg-panel-server" ] && [ -d /var/lib/swg-panel ] && ! bare_panel_parked; then',
          '    if [ -f "$PANEL_DIR/swg-panel-server" ] && [ -d /var/lib/swg-panel ]; then')
    plant('    [ "$LC_TOKEN" = set-in-nodes-screen ] && LC_TOKEN=""\n', '')
    plant("  elif [ -f \"$DOCKER_DIR/.env\" ] && command -v docker >/dev/null 2>&1 \\\n"
          "       && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then",
          '  elif [ -f "$DOCKER_DIR/.env" ]; then')

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

def world(bare_panel=False, bare_enabled=True, bare_active=True, containers=None, env=None, agent=None):
    """containers: {name: "running restart-policy"} for docker ps / inspect. env: the docker .env text, or None."""
    t = tempfile.mkdtemp(prefix="lctgt-")
    pdir = os.path.join(t, "opt/swg-panel"); ddir = os.path.join(t, "opt/swg-panel-docker")
    if bare_panel:
        os.makedirs(pdir); open(os.path.join(pdir, "swg-panel-server"), "w").write("x")
        os.makedirs(os.path.join(t, "var/lib/swg-panel"))
    if env is not None:
        os.makedirs(os.path.join(ddir, "data/lib")); open(os.path.join(ddir, ".env"), "w").write(env)
    if agent is not None:
        os.makedirs(os.path.join(t, "etc/swg-agent")); open(os.path.join(t, "etc/swg-agent/config.json"), "w").write(agent)
    stub = os.path.join(t, "stub"); os.makedirs(stub)
    cs = containers or {}
    sysd = ('case "$*" in *"is-enabled --quiet swg-panel-server"*) exit %d;; *"is-active --quiet swg-panel-server"*) exit %d;; esac\n'
            'exit 1') % (0 if bare_enabled else 1, 0 if bare_active else 3)
    # `docker ps` answers in ONE write, like the real client (strace: docker ps --format writes once). bash's own echo and
    # printf write a line at a time, and under pipefail a `grep -q` that has already matched can SIGPIPE the next write —
    # a flake of the stub, never of docker. cat writes once.
    dk = 'case "$1" in\n  ps) cat <<\'CEOF\'\n%sCEOF\n  ;;\n  inspect) case "${@: -1}" in %s *) exit 1;; esac;;\nesac\nexit 0' % (
        "".join(n + "\n" for n in cs), " ".join('%s) echo "%s";;' % (n, s) for n, s in cs.items()))
    for n, b in (("systemctl", sysd), ("docker", dk)):
        p = os.path.join(stub, n); open(p, "w").write("#!/bin/bash\n" + b + "\n"); os.chmod(p, 0o755)
    return t, pdir, ddir

def targets(t, pdir, ddir, node_only=False):
    body = fn(C, "docker_panel_live") + fn(C, "bare_panel_parked") + fn(C, "docker_parked") + fn(UP, "lc_targets")
    for p in ("/var/lib/swg-panel", "/etc/swg-agent/"):
        body = body.replace(p, t + p)
    script = ('set -euo pipefail\nNODE_ONLY=%s; PANEL_DIR=%s; DOCKER_DIR=%s\n%slc_targets\n'
              'echo "FILE=${LC_FILE:-}"; echo "TOKEN=${LC_TOKEN:-}"; echo "URL=${LC_URL:-}"; echo "VERIFY=${LC_VERIFY:-}"\n') % (
        "true" if node_only else "false", pdir, ddir, body)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=dict(os.environ, PATH=os.path.join(t, "stub") + ":" + os.environ["PATH"]))
    out = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    out["_raw"] = r.stdout + r.stderr
    return out

HOST_ENV = "PANEL_PORT=2087\nPANEL_URL=https://swg-panel:8443\nNODE_TOKEN=set-in-nodes-screen\nTLS_VERIFY=no\n"
MASTER_ENV = "PANEL_PORT=2087\nPANEL_URL=http://127.0.0.1:8088\nNODE_TOKEN=realtok-abc\nTLS_VERIFY=no\n"
AGENT = '{"panel": {"url": "https://192.168.77.3:2087", "token": "bare-node-tok", "verify": false}}'
LIVE, PARKED = "true unless-stopped", "false no"

print("[1] the two-panel box: bare panel parked beside a live docker panel")
t, p, d = world(bare_panel=True, bare_enabled=False, bare_active=False,
                containers={"swg-panel": LIVE, "swg-sub": LIVE}, env=HOST_ENV)
o = targets(t, p, d)
check("status goes to the LIVE docker panel's data/lib/host_proc", o.get("FILE") == d + "/data/lib/host_proc", o)
check("…not to the parked bare panel's /var/lib/swg-panel/host_proc", "var/lib/swg-panel" not in o.get("FILE", ""), o)
check("…and there is no node here, so nothing is POSTed", o.get("TOKEN") == "", o)

print("\n[2] a bare panel alone")
t, p, d = world(bare_panel=True)
o = targets(t, p, d)
check("its own host_proc", o.get("FILE") == t + "/var/lib/swg-panel/host_proc", o)

print("\n[3] a docker master")
t, p, d = world(containers={"swg-panel": LIVE, "swg-node": LIVE, "swg-sub": LIVE}, env=MASTER_ENV)
o = targets(t, p, d)
check("the docker host_proc + the node's .env token + its loopback URL",
      o.get("FILE") == d + "/data/lib/host_proc" and o.get("TOKEN") == "realtok-abc"
      and o.get("URL") == "http://127.0.0.1:8088", o)
t, p, d = world(containers={"swg-panel": LIVE, "swg-node": LIVE},
                env=MASTER_ENV.replace("http://127.0.0.1:8088", "https://swg-panel:8443").replace("TLS_VERIFY=no", "TLS_VERIFY=yes"))
o = targets(t, p, d)
check("a bridged https://swg-panel:… URL goes to the host's loopback on PANEL_PORT, unverified",
      o.get("URL") == "https://127.0.0.1:2087" and o.get("VERIFY") == "no", o)

print("\n[4] a docker panel-only install")
t, p, d = world(containers={"swg-panel": LIVE, "swg-sub": LIVE}, env=HOST_ENV)
o = targets(t, p, d)
check("the docker host_proc", o.get("FILE") == d + "/data/lib/host_proc", o)
check("…and NO node POST: the placeholder token is not a node's, and there is no swg-node", o.get("TOKEN") == "", o)
t, p, d = world(containers={"swg-panel": LIVE, "swg-node": LIVE}, env=HOST_ENV)
o = targets(t, p, d)
check("…the placeholder is never a token, even beside a swg-node container", o.get("TOKEN") == "", o)

print("\n[5] a docker node only")
t, p, d = world(containers={"swg-node": LIVE}, env=MASTER_ENV.replace("http://127.0.0.1:8088", "https://panel.example:2087"))
o = targets(t, p, d)
check("the node POST with its .env token, no panel file", o.get("FILE") == "" and o.get("TOKEN") == "realtok-abc"
      and o.get("URL") == "https://panel.example:2087", o)

print("\n[6] a bare node beside a docker panel")
t, p, d = world(containers={"swg-panel": LIVE}, env=HOST_ENV, agent=AGENT)
o = targets(t, p, d)
check("the docker panel's host_proc AND the bare node's own POST",
      o.get("FILE") == d + "/data/lib/host_proc" and o.get("TOKEN") == "bare-node-tok", o)

print("\n[7] --node-only")
t, p, d = world(bare_panel=True, agent=AGENT)
o = targets(t, p, d, node_only=True)
check("no panel file (updating just the node must not touch the panel's header)", o.get("FILE") == ""
      and o.get("TOKEN") == "bare-node-tok", o)

print("\n[8] both panels live (the operator kept both)")
t, p, d = world(bare_panel=True, containers={"swg-panel": LIVE}, env=HOST_ENV)
o = targets(t, p, d)
check("the bare panel's file, as before", o.get("FILE") == t + "/var/lib/swg-panel/host_proc", o)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
