#!/usr/bin/env python3
"""Self-test — the docker uninstall says what it keeps, keeps what it says, and takes its network with it.

  [1] With ARCHIVES_DEL=y (an unattended wipe) the uninstaller saved a recovery copy, announced "Removed … — a recovery
      copy (token + interface keys) is kept for re-install", and deleted that copy a minute later in the archive sweep.
      Now no copy is made when the run was told to keep none, and says so; asked interactively, the archive question
      names the copy this run saved, and the result says it went with the rest.
  [2] Removing a docker panel left the compose project's network (swg-panel-docker_default) behind: `compose down`
      drops it only when it runs, and a panel removed while its node stays never gets one. Now removed by the
      project's label wherever the panel or the stack goes (docker refuses while anything is attached).

  [4] Kept recovery archives: "delete by hand once you no longer need them" never said which, or where (M7). They are
      listed now.
  [3] Told to keep the data, the uninstaller said "Kept …/data + .env (node token) for a future reinstall" on every box —
      also on a panel-only one, whose .env carries no node token (the placeholder set-in-nodes-screen; 1.8.8
      qualification, q5). It now says what that .env holds: the node token, the panel's address and ports, or both.

apply_full_data_fate, the archive sweep, docker_rm_project_networks and rm_docker_panel are lifted out of uninstall.sh
AS SHIPPED; docker / systemctl are stubs, the recovery-archive paths are temp dirs.

Run: python3 tests/uninstall_archive_network_selftest.py     (0 = pass)
     --perturb   the shipped behaviour put back (copy always made, archive wording, no network removal) → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b, cnt=1):
    global U
    assert U.count(a) == cnt, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    U = U.replace(a, b)

if PERTURB:
    plant('  case "${ARCHIVES_DEL:-}" in [Yy]*)\n', '  case "${ARCHIVES_DEL:-}" in __never__)\n')            # [1] copy always made
    plant("including the copy saved above: this node can no longer be recovered from this box", "")            # [1] wording
    plant('docker_rm_project_networks(){\n  command -v docker >/dev/null 2>&1 || return 0\n',
          'docker_rm_project_networks(){\n  return 0\n')                                                        # [2]
    plant('    ok "Kept $DOCKER_DIR/data$_env for a future reinstall"\n',
          '    ok "Kept $DOCKER_DIR/data + .env (node token) for a future reinstall"\n')                          # [3]
    plant('  else info "  Kept — delete by hand once you no longer need them:"; _archives | sed \'s/^/      /\'; fi   # …naming them\n',
          '  else info "  Kept — delete by hand once you no longer need them."; fi\n')                               # [4]

def fn(name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), U, re.M)
    assert m, "cannot extract " + name
    lines = U[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

PRE = ('set -uo pipefail\nDRYRUN=false\ninfo(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ :; }\n'
       'b(){ printf %s "$*"; }\nrun(){ "$@"; }\nrmrf(){ local p; for p in "$@"; do rm -rf "$p"; done; }\n')

def stubs(d, body):
    for n, b in body.items():
        p = os.path.join(d, n); open(p, "w").write('#!/bin/bash\necho "%s $*" >> %s/calls\n%s\n' % (n, d, b)); os.chmod(p, 0o755)

print("[1] a recovery copy is kept only when it will stay kept — and every line about it is true")
def fate(archives_del):
    d = tempfile.mkdtemp(prefix="arc-"); dd = os.path.join(d, "swg-panel-docker")
    os.makedirs(os.path.join(dd, "data", "node-confs")); open(os.path.join(dd, ".env"), "w").write("NODE_TOKEN=t\nPANEL_PASSWORD=p\n")
    env = dict(os.environ); env.pop("ARCHIVES_DEL", None)
    if archives_del is not None:
        env["ARCHIVES_DEL"] = archives_del
    r = subprocess.run(["bash", "-c", PRE + 'DOCKER_DIR=%s; DOCKER_DATA_DEL=yes; DOCKER_KEEP_CONFS=no\n%sapply_full_data_fate\necho "RUN_ARCHIVES=${RUN_ARCHIVES:-}"\n'
                        % (dd, fn("apply_full_data_fate"))], capture_output=True, text=True, env=env)
    return r.stdout + r.stderr, [x for x in os.listdir(d) if ".uninstalled-" in x]
out, made = fate("y")
check("ARCHIVES_DEL=y → no recovery copy is made (it would be swept at the end of this very run)", not made, (made, out))
check("…said, and the removal line no longer claims 'a recovery copy … is kept'",
      "no recovery copy saved" in out and "is kept for re-install" not in out, out)
out, made = fate(None)
check("no preset → the copy is made, recorded as this run's, and the line saying so is true",
      len(made) == 1 and "RUN_ARCHIVES= " in out and "is kept for re-install" in out, (made, out))

sweep = U[U.index("_archives(){ ls -d"):U.index("\n# group cleanup")]
def archive_sweep(run_archive, answer="yes"):
    d = tempfile.mkdtemp(prefix="swp-")
    for sub in ("opt", "etc", "var/lib"):
        os.makedirs(os.path.join(d, sub))
    old = os.path.join(d, "opt", "swg-panel-docker.converted-20260101-000000"); os.makedirs(old)
    new = os.path.join(d, "opt", "swg-panel-docker.uninstalled-20260926-000000"); os.makedirs(new)
    s = sweep.replace("/opt/", d + "/opt/").replace("/etc/", d + "/etc/").replace("/var/lib/", d + "/var/lib/")
    r = subprocess.run(["bash", "-c", PRE + 'ask_yn(){ printf -v "$3" %s; }\nRUN_ARCHIVES="%s"\n%s' % (answer, new if run_archive else "", s)],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).replace(d, ""), os.path.exists(new)
out, left = archive_sweep(True)
check("the archive question names the copy THIS run saved (not 'from earlier converts/uninstalls' alone)",
      "1 saved by this run" in out, out)
check("…and when it goes with the rest, the result says so", "including the copy saved above" in out and not left, out)

out, left = archive_sweep(True, answer="no")
check("[4] kept: the line names each archive it leaves, so \"delete by hand\" says what",
      "delete by hand" in out and "/opt/swg-panel-docker.converted-20260101-000000" in out
      and "/opt/swg-panel-docker.uninstalled-20260926-000000" in out and left, out)

print("\n[2] the compose project's network goes with the docker panel / stack")
def nets(func_script):
    d = tempfile.mkdtemp(prefix="net-")
    stubs(d, {"docker": 'case "$1 $2" in "network ls") echo net-abc;; esac; exit 0', "systemctl": "exit 0"})
    r = subprocess.run(["bash", "-c", PRE + "SD=%s; DOCKER_DIR=/opt/swg-panel-docker\n%s" % (d, func_script)],
                       capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    calls = open(os.path.join(d, "calls")).read() if os.path.exists(os.path.join(d, "calls")) else ""
    return r.stdout + r.stderr, calls
out, calls = nets(fn("docker_rm_project_networks") + "docker_rm_project_networks\n")
check("by the project's label (com.docker.compose.project=swg-panel-docker) — nothing else's network",
      "label=com.docker.compose.project=swg-panel-docker" in calls and "docker network rm net-abc" in calls, calls)
out, calls = nets(fn("docker_rm_project_networks") + fn("rm_docker_panel") +
                  'docker_running(){ [ "$1" = swg-node ]; }\nask_yn(){ :; }\n_rm_panel_data(){ :; }\ndocker_cleanup_if_last(){ :; }\n'
                  'rm_docker_panel\n')
check("a docker panel removed while its node STAYS → its network goes too (the node runs on host networking)",
      "docker network rm net-abc" in calls, (calls, out))

print("\n[3] the kept-data line says what the kept .env holds")
def kept(token, panel, node, env=True):
    d = tempfile.mkdtemp(prefix="kept-"); dd = os.path.join(d, "swg-panel-docker")
    for sub, on in (("lib", panel), ("etc", panel), ("node-confs", node)):
        if on:
            os.makedirs(os.path.join(dd, "data", sub))
    os.makedirs(os.path.join(dd, "data"), exist_ok=True)
    if env:
        open(os.path.join(dd, ".env"), "w").write("PANEL_PASSWORD=p\nPANEL_DOMAIN=192.168.77.5\nNODE_TOKEN=%s\n" % token)
    r = subprocess.run(["bash", "-c", PRE + 'DOCKER_DIR=%s; DOCKER_DATA_DEL=no; DOCKER_KEEP_CONFS=""\n%sapply_full_data_fate\n'
                        % (dd, fn("apply_full_data_fate"))], capture_output=True, text=True)
    envtxt = open(os.path.join(dd, ".env")).read() if env else ""
    return (r.stdout + r.stderr).replace(dd, "DIR"), envtxt
out, envtxt = kept("set-in-nodes-screen", panel=True, node=False)
check("a panel-only box: the panel's address and ports — no node token it never had",
      "OK Kept DIR/data + .env (the panel's address and ports) for a future reinstall" in out and "node token" not in out, out)
check("…and the panel password is still stripped from the kept .env", "PANEL_PASSWORD" not in envtxt, envtxt)
out, _ = kept("N3fJrealtoken", panel=False, node=True)
check("a node-only box: the node token", "OK Kept DIR/data + .env (node token) for a future reinstall" in out, out)
out, _ = kept("N3fJrealtoken", panel=True, node=True)
check("a master: both", "OK Kept DIR/data + .env (node token, the panel's address and ports) for a future reinstall" in out, out)
out, _ = kept("", panel=True, node=False, env=False)
check("no .env left at all: only the data is claimed", "OK Kept DIR/data for a future reinstall" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
