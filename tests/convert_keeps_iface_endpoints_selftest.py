#!/usr/bin/env python3
"""Self-test: a docker → bare-metal convert hands install-node.sh the endpoint each interface's clients already dial,
and a master convert removes the docker network it leaves behind.

Measured in the 1.8.8-beta VM upgrade re-run: both docker → bare converts (master and node) logged "Used 10.0.2.15
endpoint IP for awg0 / wg0 / …" — install-node.sh re-detected every migrated interface's endpoint from the default
route and wrote it into config.json, so the panel's client configs moved from the 192.168.77.x the docker node had
served to the box's NAT address (on a real box: from a DNS name to a raw IP). convert.sh passed only the node-level
ENDPOINT_IP. It now computes, per migrated interface, what the RUNNING docker node reports (its agent config inside
the container), else the NODE_IFACES spec's endpoint field, else NODE_ENDPOINT — the docker entrypoint's own
precedence — and passes it as ADOPTED_ENDPOINTS="name=host,…", which install-node.sh reads.

The same master convert left `swg-panel-docker_default` and its br-… bridge behind: the containers go one by one (the
docker node must outlive the panel), so compose never took the project down.

  [1] docker_iface_endpoints (as shipped, `docker` stubbed): the live value wins; then the spec's field 5; then
      NODE_ENDPOINT; a loopback is never handed on; nothing but host characters survives
  [2] both hand-offs (master and node) compute it and pass ADOPTED_ENDPOINTS to install-node.sh
  [3] install-node.sh's reader (as in the tree) turns that exact string into per-interface endpoints
  [4] the master branch removes the project's docker networks after the node is converted (stubbed `docker`)

Run: python3 tests/convert_keeps_iface_endpoints_selftest.py      (0 = pass)
     --perturb   re-plants the shipped convert (no per-interface endpoints handed on, no network cleanup) → RED
"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
if PERTURB:
    for a, b in [(' ADOPTED_IFACES="$mnames" ADOPTED_ENDPOINTS="$MEPS" \\', ' ADOPTED_IFACES="$mnames" \\'),
                 (' ADOPTED_IFACES="$names" ADOPTED_ENDPOINTS="$NEPS" \\', ' ADOPTED_IFACES="$names" \\')]:
        assert src.count(a) == 1, "perturbation anchor missing — this run would FALSE-PASS: %r" % a
        src = src.replace(a, b, 1)
    m = re.search(r"\n    for _nw in \$\(docker network ls .*?\n    done\n", src, re.S)
    assert m, "perturbation anchor missing (network cleanup) — this run would FALSE-PASS"
    src = src[:m.start()] + "\n" + src[m.end():]
    # the shipped helper did not exist: an empty answer is what install-node.sh got
    src = src.replace('docker_iface_endpoints(){ local names="$1"', 'docker_iface_endpoints(){ return 0; local names="$1"', 1)

fn = re.search(r"^docker_iface_endpoints\(\)\{.*?\n  printf '%s' \"\$out\"; \}\n", src, re.S | re.M)
assert fn, "docker_iface_endpoints missing — this run would FALSE-PASS"
T = tempfile.mkdtemp(prefix="convep-")
STUB = os.path.join(T, "stub"); os.makedirs(STUB)
LIVE = {"interfaces": {"awg0": {"cmd": ["awg"], "endpoint_host": "192.168.77.4"},
                       "wg0": {"cmd": ["wg"], "endpoint_host": "vpn.example.net"},
                       "wg9": {"cmd": ["wg"], "endpoint_host": "127.0.0.1"}},
        "panel": {"token": "secret-token-never-printed"}}


def endpoints(names, nep, specs, live=True):
    open(os.path.join(STUB, "docker"), "w").write(
        "#!/bin/sh\n" + ("cat <<'J'\n%s\nJ\n" % json.dumps(LIVE) if live else "exit 1\n"))
    os.chmod(os.path.join(STUB, "docker"), 0o755)
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\n%s\ndocker_iface_endpoints "$1" "$2" "$3"' % fn.group(0), "x", names, nep, specs],
                       env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
    return r.returncode, r.stdout


print("[1] docker_iface_endpoints")
rc, out = endpoints("awg0 wg0", "192.168.77.9", "")
check("⚠️ the running node's per-interface endpoints are handed on", rc == 0 and out == "awg0=192.168.77.4,wg0=vpn.example.net", (rc, out))
rc, out = endpoints("awg1", "192.168.77.9", "awg1:51822:10.9.0.1/24:awg:203.0.113.5,wg2:51823:10.10.0.1/24:wg")
check("not in the live config → the NODE_IFACES spec's endpoint field", out == "awg1=203.0.113.5", out)
rc, out = endpoints("wg2", "192.168.77.9", "wg2:51823:10.10.0.1/24:wg")
check("no spec endpoint → NODE_ENDPOINT", out == "wg2=192.168.77.9", out)
rc, out = endpoints("awg0 wg0", "192.168.77.9", "", live=False)
check("container gone (a resume) → NODE_ENDPOINT for each, no abort", rc == 0 and out == "awg0=192.168.77.9,wg0=192.168.77.9", (rc, out))
rc, out = endpoints("wg9", "127.0.0.1", "")
check("a loopback is never handed to clients", rc == 0 and out == "", (rc, out))
rc, out = endpoints("wg2", "evil,x=1 $(id)", "")
check("only host characters survive (',' and '=' frame the list)", "," not in out.split("=", 1)[-1] and "$" not in out and " " not in out, out)
check("the node token in the live config is never echoed", "secret-token" not in endpoints("awg0", "", "")[1])

print("\n[2] both hand-offs pass ADOPTED_ENDPOINTS")
master = re.search(r'    MEPS="\$\(docker_iface_endpoints "\$mnames" "\$NEP" .*?\)"\n.*?ADOPTED_ENDPOINTS="\$MEPS"', src, re.S)
node = re.search(r'  NEPS="\$\(docker_iface_endpoints "\$names" "\$NEP" "\$NIFS"\)"\n.*?ADOPTED_ENDPOINTS="\$NEPS"', src, re.S)
check("⚠️ master: MEPS computed and passed to install-node.sh", master is not None)
check("⚠️ node: NEPS computed and passed to install-node.sh", node is not None)

print("\n[3] install-node.sh reads that exact format")
inode = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
reader = re.search(r'\nfor _ae in \$\(printf \'%s\' "\$ADOPTED_ENDPOINTS" \| tr \',\' \' \'\); do\n.*?\ndone\n', inode, re.S)
check("install-node.sh has an ADOPTED_ENDPOINTS reader", reader is not None, "install-node.sh must read ADOPTED_ENDPOINTS — see the report")
if reader:
    s = ('set -euo pipefail\ndeclare -A IF_ENDPOINT=( [wg0]="kept-by-this-box" )\nADOPTED_ENDPOINTS="$1"\n%s\n'
         'for k in awg0 wg0; do echo "$k=${IF_ENDPOINT[$k]:-}"; done\n') % reader.group(0)
    r = subprocess.run(["bash", "-c", s, "x", "awg0=192.168.77.4,wg0=vpn.example.net"], capture_output=True, text=True)
    check("awg0 takes the handed-on endpoint", "awg0=192.168.77.4" in r.stdout, r.stdout + r.stderr)
    check("…an endpoint this box already records wins (a re-run never clobbers it)", "wg0=kept-by-this-box" in r.stdout, r.stdout)

print("\n[4] the master convert removes the docker project's networks")
loop = re.search(r"\n(    for _nw in \$\(docker network ls .*?\n    done\n)", src, re.S)
panel = re.search(r"# ── PANEL host/master: docker → bare-metal ──.*?\n(if .*?\nfi)\n", src, re.S)
check("the cleanup sits in the panel branch, after the node's install-node.sh",
      loop is not None and panel is not None and loop.group(1) in panel.group(1)
      and panel.group(1).find(loop.group(1)) > panel.group(1).find('ADOPTED_IFACES="$mnames"'))
if loop:
    log = os.path.join(T, "docker.log")
    open(os.path.join(STUB, "docker"), "w").write(
        '#!/bin/sh\necho "$*" >> "%s"\n[ "$1 $2" = "network ls" ] && { echo net1; echo net2; }\nexit 0\n' % log)
    os.chmod(os.path.join(STUB, "docker"), 0o755)
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\nDOCKER_DIR=/opt/swg-panel-docker\n' + loop.group(1)],
                       env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
    calls = open(log).read() if os.path.exists(log) else ""
    check("it asks for exactly this compose project's networks", "label=com.docker.compose.project=swg-panel-docker" in calls, calls)
    check("⚠️ and removes each of them", "network rm net1" in calls and "network rm net2" in calls, calls)
else:
    check("⚠️ network cleanup present", False, "no cleanup loop")

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
