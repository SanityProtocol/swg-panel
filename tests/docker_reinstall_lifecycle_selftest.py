#!/usr/bin/env python3
"""Self-test — a Docker (re-)install tells its status only to a panel that can hear it, and only as a node.

install-docker.sh arms the lifecycle signal ("reinstalling" → "reinstalled", "converting-docker" → …) with the node
token and panel URL from the kept .env. Two runs spent seconds shouting into the void (1.8.8 qualification):
  f   a Docker MASTER re-installed right after an uninstall: the kept .env points its node at this box's own panel,
      and no swg-panel container was running — "telling the panel this started … up to 6s", "couldn't reach the panel
      to record 'reinstalling'" (q3);
  N4  a Docker panel-only install carries the placeholder NODE_TOKEN=set-in-nodes-screen, POSTed as a node token: a
      401 after the full wait, twice (the same defect update.sh had; tests/update_status_target_selftest.py).

  [1] master re-install after an uninstall (no container running) → no node POST armed
  [2] master re-install with its stack running → the node POST as before, loopback URL, and the panel header file
  [3] panel-only re-install (placeholder token), stack running → the header file only, no node POST
  [4] node re-install → the node POST to its panel wherever that is, as before
  [5] a panel-only bare → docker convert (placeholder token) → the header file only, no node POST

The re-install block is lifted out of install-docker.sh AS SHIPPED and run over stubbed docker / lc_init.

Run: python3 tests/docker_reinstall_lifecycle_selftest.py     (0 = pass)
     --perturb   the shipped block planted back (any token, any panel) → RED
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

if PERTURB:
    a = ("    if [ \"$NODE_TOKEN\" != set-in-nodes-screen ] \\\n"
         "       && { [ \"$PROFILE\" = node ] || docker ps --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; }; then\n")
    assert D.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    D = D.replace(a, "    if true; then\n")

a = D.index('if { [ "$EXISTING_DOCKER" = yes ] || [ -n "${SWG_CONVERT_DIR:-}" ] || ls "$INSTALL_DIR/data/node-confs/"*.conf')
b = D.index("\n\n# bare→docker CONVERT: the panel login", a)
BLOCK = D[a:b] + "\n"

def run(profile, token, url, running=(), existing="yes", convert=""):
    t = tempfile.mkdtemp(prefix="dlc-"); inst = os.path.join(t, "opt/swg-panel-docker"); os.makedirs(inst)
    stub = os.path.join(t, "stub"); os.makedirs(stub)
    p = os.path.join(stub, "docker")
    # `docker ps` answers in ONE write, like the real client (strace: docker ps --format writes once). bash's own echo and
    # printf write a line at a time, and under pipefail a `grep -q` that has already matched can SIGPIPE the next write —
    # a flake of the stub, never of docker. cat writes once.
    open(p, "w").write('#!/bin/bash\ncase "$1" in\n  ps) cat <<\'CEOF\'\n%sCEOF\n  ;;\n  inspect) exit 1;;\nesac\nexit 0\n'
                       % "".join(c + "\n" for c in running))
    os.chmod(p, 0o755)
    script = ('set -euo pipefail\nDRYRUN=false; INSTALL_DIR=%s; EXISTING_DOCKER=%s; PROFILE=%s; NODE_TOKEN="%s"; PANEL_URL="%s"\n'
              'TLS_VERIFY=no; PANEL_PORT=2087; SWG_CONVERT_DIR="%s"\nlc_emit_docker(){ :; }\n'
              'lc_init(){ echo "LC_INIT $1 URL=${LC_URL:-} TOKEN=${LC_TOKEN:-} FILE=${LC_FILE:-}"; }\n%s'
              'echo "END URL=${LC_URL:-} TOKEN=${LC_TOKEN:-} FILE=${LC_FILE:-}"\n') % (
        inst, existing, profile, token, url, convert, BLOCK)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=dict(os.environ, PATH=stub + ":" + os.environ["PATH"]))
    out = r.stdout + r.stderr
    last = [l for l in out.splitlines() if l.startswith("END ")]
    return (last[-1] if last else out), out, inst

print("[1] a Docker master re-installed right after an uninstall")
end, out, inst = run("host", "realtok-abc", "http://127.0.0.1:8088")
check("no node POST is armed — the panel it reports to is this box's own, and it is not running",
      "TOKEN= " in end + " " and "LC_INIT" not in out, out)

print("\n[2] a Docker master re-installed with its stack running")
end, out, inst = run("host", "realtok-abc", "http://127.0.0.1:8088", running=("swg-panel", "swg-node", "swg-sub"))
check("the node POST as before (token + loopback URL) and the panel header file",
      "URL=http://127.0.0.1:8088 TOKEN=realtok-abc FILE=%s/data/lib/host_proc" % inst in end and "LC_INIT reinstall" in out, out)
end, out, inst = run("host", "realtok-abc", "https://swg-panel:8443", running=("swg-panel", "swg-node"))
check("…a bridged https://swg-panel:… URL still goes to the host's loopback on the panel's port",
      "URL=https://127.0.0.1:2087 TOKEN=realtok-abc" in end, end)

print("\n[3] a panel-only re-install")
end, out, inst = run("host", "set-in-nodes-screen", "https://swg-panel:8443", running=("swg-panel", "swg-sub"))
check("the header file only — the placeholder is not a node token", end.endswith("TOKEN= FILE=%s/data/lib/host_proc" % inst)
      and "URL= " in end, end)

print("\n[4] a node re-install")
end, out, inst = run("node", "nodetok-xyz", "https://192.168.77.3:2087")
check("the node POST to its panel, wherever that is (no local panel needed)",
      "URL=https://192.168.77.3:2087 TOKEN=nodetok-xyz FILE=" in end and "LC_INIT reinstall" in out, out)

print("\n[5] a panel-only bare-metal → Docker convert")
end, out, inst = run("host", "set-in-nodes-screen", "https://swg-panel:8443", existing="yes", convert="convert-docker")
check("the header file (the new panel reads it), no node POST", "TOKEN= FILE=%s/data/lib/host_proc" % inst in end
      and "LC_INIT convert-docker" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
