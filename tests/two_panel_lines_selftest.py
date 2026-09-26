#!/usr/bin/env python3
"""Self-test — two more lines that read wrong around a box's two panels (1.8.8 qualification, third VM round, q5).

  [1] a bare-metal panel installed beside a Docker panel — which the install then PARKED (guard_second_panel) — ended
      with the DOCKER panel's summary: "Docker SWG Host", the Docker panel's user name under "new login — save the
      password now" beside the new bare-metal password, its .env and compose commands. _sum_detect took any Docker
      panel that had ever run. It now takes the live Docker panel first, then a bare-metal one, then a parked Docker one.
  [2] removing the files of a Docker panel-only install printed "No sign-off to send: this node's panel was this box's
      own…" — about a node it never had: the .env's NODE_TOKEN is the placeholder set-in-nodes-screen. A placeholder
      is no node's token; nothing is signed off and nothing said (the "uninstalling" flash likewise).

_sum_detect (lib/common.sh) and the docker node sign-off (uninstall.sh) are lifted out AS SHIPPED over stubbed docker.

Run: python3 tests/two_panel_lines_selftest.py      (0 = pass)
     --perturb   the shipped detection and the placeholder sign-off planted back → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b, cnt=1):
    assert src.count(a) == cnt, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    C = plant(C, "  if _sum_dctr swg-panel && ! docker_parked swg-panel; then hm=docker\n", "  if _sum_dctr swg-panel; then hm=docker\n")
    U = plant(U, '  [ "$tok" = set-in-nodes-screen ] && return 0\n', "")

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

def world(containers, bare=False, env=True):
    """containers: {name: (docker-ps state, inspect 'Running Policy')}."""
    t = tempfile.mkdtemp(prefix="2pl-"); dd = os.path.join(t, "opt/swg-panel-docker"); os.makedirs(dd)
    if env:
        open(os.path.join(dd, ".env"), "w").write(env if isinstance(env, str) else "PANEL_USER=admin702\n")
    if bare:
        os.makedirs(os.path.join(t, "etc/systemd/system")); open(os.path.join(t, "etc/systemd/system/swg-panel-server.service"), "w").write("x")
    stub = os.path.join(t, "stub"); os.makedirs(stub)
    ps = "".join("%s|%s\n" % (n, s) for n, (s, _) in containers.items())
    names = "".join("%s\n" % n for n in containers)
    insp = " ".join('%s) echo "%s";;' % (n, i) for n, (_, i) in containers.items())
    body = ('case "$*" in\n  *"{{.Names}}|{{.State}}"*) cat <<\'CEOF\'\n%sCEOF\n  ;;\n  *"ps -a --format {{.Names}}"*) cat <<\'CEOF\'\n%sCEOF\n  ;;\n'
            '  inspect*) case "${@: -1}" in %s *) exit 1;; esac;;\nesac\nexit 0\n') % (ps, names, insp)
    p = os.path.join(stub, "docker"); open(p, "w").write("#!/bin/bash\n" + body); os.chmod(p, 0o755)
    return t, dd

def run(t, script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=dict(os.environ, PATH=os.path.join(t, "stub") + ":" + os.environ["PATH"]))
    return r.stdout + r.stderr

print("[1] the install summary describes the panel that answers")
DETECT = fn(C, "_sum_dctr") + fn(C, "_sum_detect") + fn(C, "docker_parked")
def detect(t, dd):
    body = DETECT
    for p in ("/etc/systemd/system/", "/opt/swg-panel/", "/etc/swg-agent/"):
        body = body.replace(p, t + p)
    out = run(t, 'set -euo pipefail\nhave(){ command -v "$1" >/dev/null 2>&1; }\n_SUM_DDIR=%s\n%secho "HM=$(_sum_detect)"\n' % (dd, body))
    m = re.search(r"HM=(\S*)", out)
    return m.group(1) if m else out
LIVE, PARKED = ("running", "true unless-stopped"), ("exited", "false no")
for want, why, kw in (
        ("baremetal", "a bare panel just installed beside a docker panel it PARKED → the bare panel's summary",
         dict(containers={"swg-panel": PARKED, "swg-sub": PARKED}, bare=True)),
        ("docker", "the bare panel parked beside a LIVE docker panel → the docker panel's (unchanged)",
         dict(containers={"swg-panel": LIVE, "swg-sub": LIVE}, bare=True)),
        ("docker", "a docker panel alone, running → docker (unchanged)", dict(containers={"swg-panel": LIVE})),
        ("docker", "a docker panel alone, stopped by hand (no bare panel) → still docker", dict(containers={"swg-panel": PARKED})),
        ("baremetal", "a bare panel alone → bare-metal (unchanged)", dict(containers={}, bare=True))):
    t, dd = world(**kw)
    got = detect(t, dd)
    check(why, got == want, got)

print("\n[2] a Docker panel-only install has no node to sign off")
GB = "".join(fn(U, n) for n in ("_url_is_this_box", "_panel_left_here", "_goodbye_nobody", "_goodbye_skipped",
                                "_goodbye_post", "_proc_post", "docker_node_goodbye", "docker_node_uninstalling"))
PRE = ('set -uo pipefail\nDRYRUN=false; _OWN_PANEL_HOST=""\ninfo(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }\n'
       'docker_running(){ command -v docker >/dev/null 2>&1 && docker ps -a --format "{{.Names}}" 2>/dev/null | grep -qx "$1"; }\n')
t, dd = world({}, env="PANEL_URL=https://swg-panel:8443\nNODE_TOKEN=set-in-nodes-screen\nTLS_VERIFY=no\n")
out = run(t, PRE + "SD=%s/sd; DOCKER_DIR=%s\n%sdocker_node_uninstalling\ndocker_node_goodbye\necho DONE\n" % (t, dd, GB))
check("the placeholder token → no sign-off, and not a word about \"this node's panel\"",
      out.strip() == "DONE", out)
t, dd = world({}, env="PANEL_URL=https://swg-panel:8443\nNODE_TOKEN=realtok-abc\nTLS_VERIFY=no\n")
out = run(t, PRE + "SD=%s/sd; DOCKER_DIR=%s\n%sdocker_node_goodbye\necho DONE\n" % (t, dd, GB))
check("a real node token whose panel was this box's own, now gone → \"No sign-off to send\" (unchanged)",
      "No sign-off to send" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
