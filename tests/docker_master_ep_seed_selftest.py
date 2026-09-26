#!/usr/bin/env python3
"""Self-test — a Docker MASTER's own node record gets the endpoint its node already reports, on an update and on a
re-install (the Docker twin of D7, update_node_ep_seed_selftest.py).

1.8.8 qualification, q3 (a Docker master installed by 1.8.7, updated, uninstalled and re-installed): its own node kept
endpoint_host '' throughout. install-docker.sh fills it only from an endpoint GIVEN on that run, and update.sh's
seed_local_node_ep was bare-metal only. The panel fills a blank from the node's first PUBLIC address, so a master
whose addresses are all private (a LAN, a NAT'd lab) had no dial host: the other nodes' mesh peers to it were never
emitted, and WDTT / csqtt on a wildcard bind advertised nothing.

  [1] update.sh's docker recreate path, run AS SHIPPED over stubbed docker / compose: the agent config is copied out of
      the RUNNING node container before the containers go, the record is seeded while BOTH are gone (never while the
      panel runs), and the panel comes back up with it; the file keeps its mode
  [2] a bridged master's node dials its panel as `swg-panel` — that is this box's panel too
  [3] left alone, exactly as on bare metal: an endpoint already set, an interface with its own endpoint, an address not
      on this box, a token matching no record, a node syncing to another panel; a node container that could not be read
  [4] install-docker.sh: a RE-install seeds from the kept NODE_ENDPOINT under the same rules; a fresh install still takes
      only a given endpoint

Run: python3 tests/docker_master_ep_seed_selftest.py     (0 = pass)
     --perturb   the shipped behaviour planted back (no docker seed; a re-install passes only a given endpoint) → RED
"""
import hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
UP = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
DI = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    UP = plant(UP, '[ -n "$_seedcfg" ] && { seed_docker_node_ep "$_seedcfg"; rm -f "$_seedcfg"; }', '[ -n "$_seedcfg" ] && rm -f "$_seedcfg"')
    UP = plant(UP, '"::1", "swg-panel"):', '"::1"):')
    DI = plant(DI, '    _EP_SEED="$NODE_ENDPOINT"\n', '    :\n')

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

# the recreate branch AS SHIPPED: from the agent-config copy through `compose up` (the rest of that line is the verdict)
a = UP.index("        # a master's node reports with the agent config inside its container")
b = UP.index('up -d --force-recreate )', a) + len('up -d --force-recreate )')
BRANCH = UP[a:b] + "\n"
SEED = fn(UP, "seed_local_node_ep") + fn(UP, "seed_docker_node_ep")

TOK = "node-tok-123"
def world(rec_ep="", agent_ep="192.168.77.3", ifaces=None, url="http://127.0.0.1:8088", tok=TOK, exec_ok=True):
    t = tempfile.mkdtemp(prefix="dseed-")
    lib = os.path.join(t, "docker/data/lib"); os.makedirs(lib)
    nodes = {"n1": {"id": "n1", "name": "q3m", "endpoint_host": rec_ep, "token_sha": hashlib.sha256(tok.encode()).hexdigest()},
             "n2": {"id": "n2", "name": "q4n", "endpoint_host": "", "token_sha": "00"}}
    np = os.path.join(lib, "nodes.json"); json.dump(nodes, open(np, "w")); os.chmod(np, 0o600)
    cfg = {"endpoint_host": agent_ep, "panel": {"url": url, "token": TOK},
           "interfaces": ifaces if ifaces is not None else {"awg0": {"endpoint_host": agent_ep}, "wg0": {"endpoint_host": agent_ep},
                                                            "swg_c83e6fc7": {"endpoint_host": agent_ep}}}
    cp = os.path.join(t, "container-config.json"); json.dump(cfg, open(cp, "w"))
    stub = os.path.join(t, "stub"); os.makedirs(stub); log = os.path.join(t, "calls")
    ep = "python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[\"n1\"][\"endpoint_host\"] or \"-\")' %s" % np
    docker = ('case "$1" in\n'
              '  exec) %s;;\n'
              '  ps) echo "id-$4";;\n'
              '  rm) echo "rm EP=$(%s)" >> %s;;\n'
              'esac\nexit 0\n') % (("cat %s" % cp) if exec_ok else "exit 1", ep, log)
    compose = 'echo "compose $* EP=$(%s)" >> %s\nexit 0\n' % (ep, log)
    for n, body in (("docker", docker), ("compose", compose)):
        p = os.path.join(stub, n); open(p, "w").write("#!/bin/bash\n" + body); os.chmod(p, 0o755)
    return t, np, log

def recreate(t, addrs="127.0.0.1 10.0.2.15 192.168.77.3 172.18.0.1", prof="master"):
    script = ('set -euo pipefail\nDRYRUN=false; STATE_DIR=/nonexistent; DOCKER_DIR=%s/docker; prof=%s; COMPOSE=compose\n'
              'RESULTS=(); note(){ RESULTS+=("$*"); echo "NOTE $*"; }\nok(){ echo "OK $*"; }\ncol_v(){ printf %%s "$*"; }\n'
              'have(){ command -v "$1" >/dev/null 2>&1; }\non_tty(){ "$@"; }\nrescue_container_confs(){ :; }\n'
              'local_addrs(){ printf "%%s\\n" %s; }\n%s%s') % (t, prof, addrs, SEED, BRANCH)
    os.makedirs(os.path.join(t, "tmp"), exist_ok=True)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=dict(os.environ, PATH=os.path.join(t, "stub") + ":" + os.environ["PATH"], TMPDIR=os.path.join(t, "tmp")))
    calls = open(os.path.join(t, "calls")).read().splitlines() if os.path.exists(os.path.join(t, "calls")) else []
    return r.stdout + r.stderr, calls

def ep(np):
    return json.load(open(np))["n1"]["endpoint_host"]

print("[1] an update that recreates a docker master seeds its own node's blank record — with no panel running")
t, np, log = world()
out, calls = recreate(t)
check("seeded with the endpoint the running node reports (192.168.77.3)", ep(np) == "192.168.77.3", (out, calls))
check("…the containers were removed with the record still blank (never written while the panel ran)",
      calls[:2] == ["rm EP=-", "rm EP=-"], calls)
check("…and the panel came back up already holding it", any(c.startswith("compose --profile master up -d --force-recreate")
                                                             and c.endswith("EP=192.168.77.3") for c in calls), calls)
check("…said, and listed among the changes", "now carries its endpoint 192.168.77.3" in out
      and "NOTE docker: the panel's own node endpoint set to 192.168.77.3 (was blank)" in out, out)
check("…the store keeps its mode", oct(os.stat(np).st_mode & 0o777) == "0o600", oct(os.stat(np).st_mode))
check("…the other nodes' records are untouched", json.load(open(np))["n2"]["endpoint_host"] == "", json.load(open(np)))
check("…and the copied agent config (it holds the node token) is gone", os.listdir(os.path.join(t, "tmp")) == [],
      os.listdir(os.path.join(t, "tmp")))

print("\n[2] a bridged master's node dials its panel as swg-panel — this box's panel too")
t, np, log = world(url="http://swg-panel:8088")
out, calls = recreate(t)
check("seeded", ep(np) == "192.168.77.3", (out, calls))

print("\n[3] everything the bare-metal seed leaves alone, the docker one leaves alone")
for why, kw, addrs in (
        ("the record already has an endpoint (the operator's, or the panel's own fill)", {"rec_ep": "vpn.example.com"}, None),
        ("an interface reports its OWN endpoint — the record would override it",
         {"ifaces": {"awg0": {"endpoint_host": "awg.example.com"}}}, None),
        ("the endpoint is not an address of this box (NAT'd public IP)", {"agent_ep": "203.0.113.7", "ifaces": {}}, None),
        ("the token matches no record here", {"tok": "someone-else"}, None),
        ("the node syncs to another panel", {"url": "https://192.168.77.5:2087"}, None),
        ("the node container could not be read", {"exec_ok": False}, None)):
    t, np, log = world(**kw)
    before = ep(np)
    out, calls = recreate(t, **({"addrs": addrs} if addrs else {}))
    check(why, ep(np) == before and any("up -d --force-recreate" in c for c in calls), (out, calls))
t, np, log = world()
out, calls = recreate(t, prof="node")
check("a node-only box (its panel is elsewhere) copies nothing and seeds nothing", ep(np) == "", (out, calls))

print("\n[4] install-docker.sh: a re-install seeds from the endpoint its node already has")
a = DI.index('  _EP_SEED="${_GIVEN_NODE_ENDPOINT:-}"\n')
b = DI.index("  fi\n", a) + len("  fi\n")
DERIVE = DI[a:b]
def derive(existing, given="", node_ep="192.168.77.3", ifaces="", local="192.168.77.3 10.0.2.15"):
    script = ('set -euo pipefail\n%s%sEXISTING_DOCKER=%s; _GIVEN_NODE_ENDPOINT="%s"; NODE_ENDPOINT="%s"; NODE_IFACES="%s"\n%s'
              'echo "SEED=$_EP_SEED"\n') % (fn(C, "local_addrs"), fn(C, "host_is_local"), existing, given, node_ep, ifaces, DERIVE)
    stub = tempfile.mkdtemp(prefix="dseedip-")
    for n, body in (("ip", 'printf "1: lo    inet 127.0.0.1/8\\n"; for a in %s; do printf "2: eth0    inet %%s/24\\n" "$a"; done' % local),
                    ("hostname", "exit 0"), ("getent", "exit 2")):
        p = os.path.join(stub, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=stub + ":" + os.environ["PATH"]))
    return (r.stdout.strip().splitlines() or ["?"])[-1] + ("" if r.returncode == 0 else " rc=%d %s" % (r.returncode, r.stderr))
check("re-install, kept NODE_ENDPOINT on this box, every interface on it → seeded with it",
      derive("yes") == "SEED=192.168.77.3", derive("yes"))
check("…a NODE_IFACES entry naming the same endpoint still counts as agreeing",
      derive("yes", ifaces="awg0:51820:10.8.0.1/24::192.168.77.3,wg0:51821:10.9.0.1/24:wg") == "SEED=192.168.77.3",
      derive("yes", ifaces="awg0:51820:10.8.0.1/24::192.168.77.3,wg0:51821:10.9.0.1/24:wg"))
check("…an interface with an endpoint of its own → not seeded",
      derive("yes", ifaces="awg0:51820:10.8.0.1/24:awg:vpn.example.com") == "SEED=", derive("yes", ifaces="awg0:51820:10.8.0.1/24:awg:vpn.example.com"))
check("…an endpoint that is not an address of this box → not seeded", derive("yes", node_ep="203.0.113.7") == "SEED=",
      derive("yes", node_ep="203.0.113.7"))
check("a FRESH install with nothing given → blank (the panel's own fill stays in charge)", derive("no") == "SEED=", derive("no"))
check("a given endpoint wins, fresh or not", derive("no", given="192.168.77.9") == "SEED=192.168.77.9"
      and derive("yes", given="192.168.77.9") == "SEED=192.168.77.9", (derive("no", given="192.168.77.9"), derive("yes", given="192.168.77.9")))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
