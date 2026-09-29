#!/usr/bin/env python3
"""Self-test — `uninstall.sh --dry-run` changes NOTHING, whatever it is told to remove.

1.8.8 qualification, round 6 (q4, a live Docker node): `uninstall.sh --dry-run --yes` deleted the node's host interfaces
— awg0, wg0, wg8 and the mesh link: the loop that takes a Docker node's leftover host netdevs down was the one removal
in rm_docker_node that no `run` guarded (since 44f6915). swg-noded re-created the user interfaces; the mesh link stayed
down until the container restarted. Reading the whole uninstaller for the same class found two more: the files-only
Docker component ran `docker compose down` and `docker rm -f` for real, and the end of the run removed an empty
/etc/swg-agent.

The WHOLE uninstall.sh runs here with --dry-run --yes (and again with every destructive preset answered yes) over fake
boxes: its absolute paths moved under a temp root, every tool that could change the host (docker, ip, iptables, nft,
ipset, systemctl, wg/awg-quick, userdel, apt-get, ufw, …) a stub that records each call.

  [1] a Docker node box — the node container up, its host interfaces present (awg0, wg0, swg_…), nat/FORWARD rules,
      an empty /etc/swg-agent left behind by an earlier removal
  [2] a Docker files-only box — no swg container, the deployment dir and a leftover turn-proxy container
  [3] a bare master — panel + node, interfaces, an nft table, ipsets, policy rules, a relay
  Each: no stub call that changes anything, the fake root byte-identical afterwards, and the plan still said ("[dry] …").

Run: python3 tests/uninstall_dry_run_selftest.py     (0 = pass)
     --perturb-ifaces   the host-interface loop unguarded again (the round-6 defect) → RED on [1]
     --perturb-files    the files-only component's compose down / docker rm run for real again → RED on [2]
     --perturb-rmdir    the empty /etc/swg-agent removed by a dry run again → RED on [1]
"""
import hashlib, os, re, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PERTURBED = any(a.startswith("--perturb") for a in ARGS)
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[-900:]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b):
    global U
    assert U.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    U = U.replace(a, b)

if "--perturb-ifaces" in ARGS:
    plant('    if $DRYRUN; then echo "    [dry] down + delete the leftover host interface $_n"; continue; fi\n', '')
if "--perturb-files" in ARGS:
    plant('''  run sh -c "cd '$DOCKER_DIR' 2>/dev/null && { docker compose down --remove-orphans >/dev/null 2>&1 || docker-compose down --remove-orphans >/dev/null 2>&1; } || true"\n''',
          '''  ( cd "$DOCKER_DIR" 2>/dev/null && { docker compose down --remove-orphans >/dev/null 2>&1 || docker-compose down --remove-orphans >/dev/null 2>&1; } ) || true\n''')
    plant('''  for _p in swg-node swg-panel swg-turn-; do run sh -c "docker ps -aq -f 'name=$_p' 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true"; done\n''',
          '''  for _p in swg-node swg-panel swg-turn-; do docker ps -aq -f "name=$_p" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1 || true; done\n''')
if "--perturb-rmdir" in ARGS:
    plant('$DRYRUN || rmdir /etc/swg-agent 2>/dev/null || true', 'rmdir /etc/swg-agent 2>/dev/null || true')

T = tempfile.mkdtemp(prefix="unin-dry-")

def rooted(text, box):
    for p in ("/opt/", "/etc/", "/var/", "/usr/local/bin/", "/srv/", "/root/"):
        text = text.replace(p, box + p)
    return text

# Every stub logs its argv; the ones that READ answer from the box's fixture files. `MUT` says which calls change things.
STUB = r'''#!/bin/bash
n="$(basename "$0")"; printf '%s\t%s\n' "$n" "$*" >> "$BOX/calls.log"
f="$BOX/fx/$n"
case "$n" in
  docker)
    case "$1" in
      ps) if printf '%s' "$*" | grep -q 'name=swg-turn-'; then cat "$f.turn" 2>/dev/null; else cat "$f.ps" 2>/dev/null; fi ;;
      exec) case "$*" in *Address*) cat "$f.nets" 2>/dev/null;; *config.json*) echo '{}';; *) cat "$f.confs" 2>/dev/null;; esac ;;
      inspect) exit 1 ;;
      compose) [ "$2" = version ] && exit 0 ;;
      network) [ "$2" = ls ] && echo net-abc123 ;;
      images) echo "ghcr.io/sanityprotocol/swg-node:sha-abc1234" ;;
    esac ;;
  ip)
    case "$*" in
      "link show "*) grep -qx "${3:-${@: -1}}" "$f.links" 2>/dev/null && exit 0 || exit 1 ;;
      *"rule show"*) cat "$f.rules" 2>/dev/null ;;
      *"addr show"*) echo "2: eth0    inet 192.168.77.9/24 brd x scope global eth0" ;;
    esac ;;
  iptables) case "$*" in *" -S"*|*"-S "*) cat "$f" 2>/dev/null ;; esac ;;
  nft) [ "$1" = list ] && cat "$f" 2>/dev/null ;;
  ipset) [ "$1" = list ] && cat "$f" 2>/dev/null ;;
  systemctl) case "$1" in is-enabled|is-active) exit 0;; esac ;;
  dpkg) exit 1 ;;
esac
exit 0
'''
TOOLS = ("docker", "docker-compose", "ip", "iptables", "nft", "ipset", "systemctl", "awg-quick", "wg-quick", "awg", "wg",
         "userdel", "groupdel", "useradd", "apt-get", "add-apt-repository", "dpkg", "ufw", "apparmor_parser", "nginx",
         "modprobe", "sysctl", "kill", "pkill")

def mutating(tool, argv):
    a = argv.split()
    if tool in ("docker", "docker-compose"):
        sub = a[0] if a else ""
        return sub in ("rm", "rmi", "stop", "start", "restart", "kill", "update", "run", "create") or \
            (sub == "network" and a[1:2] == ["rm"]) or (sub == "compose" and ("down" in a or "up" in a)) or \
            (tool == "docker-compose" and ("down" in a or "up" in a))
    if tool == "ip":
        return bool(re.search(r"\b(del|delete|add|flush|set|change|replace)\b", argv))
    if tool == "iptables":
        return bool(re.search(r"(^|\s)-(D|A|I|F|X|N|P|R|Z)(\s|$)", argv))
    if tool in ("nft", "ipset"):
        return a[:1] not in (["list"],)
    if tool == "systemctl":
        return a[:1] not in (["is-enabled"], ["is-active"], ["list-units"], ["show"], ["status"], ["cat"], ["list-unit-files"])
    if tool in ("awg", "wg", "dpkg"):
        return False
    return True   # awg-quick/wg-quick/userdel/apt-get/ufw/sysctl/modprobe/… — any call at all

def tree(box):
    out = {}
    for base, dirs, files in os.walk(box):
        if os.path.relpath(base, box).split(os.sep)[0] in ("stub", "fx", "home"):
            continue
        for n in dirs + files:
            p = os.path.join(base, n); rel = os.path.relpath(p, box)
            if rel in ("calls.log", "run.sh") or rel.startswith(("stub", "fx", "home")):
                continue
            st = os.lstat(p)
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if stat.S_ISREG(st.st_mode) else (os.readlink(p) if stat.S_ISLNK(st.st_mode) else "dir")
            out[rel] = (oct(st.st_mode), h)
    return out

def w(box, rel, text=""):
    p = os.path.join(box, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)

def mkbox(name, fixtures, files):
    box = os.path.join(T, name); os.makedirs(box)
    for rel, text in files.items():
        if rel.endswith("/"):
            os.makedirs(os.path.join(box, rel), exist_ok=True)
        else:
            w(box, rel, text)
    for rel, text in fixtures.items():
        w(box, "fx/" + rel, text)
    os.makedirs(os.path.join(box, "stub")); os.makedirs(os.path.join(box, "home"))
    for t in TOOLS:
        p = os.path.join(box, "stub", t); open(p, "w").write(STUB); os.chmod(p, 0o755)
    open(os.path.join(box, "run.sh"), "w").write(rooted(U, box))
    return box

def run(box, *presets):
    before = tree(box)
    env = dict(os.environ, BOX=box, HOME=os.path.join(box, "home"), PATH=os.path.join(box, "stub") + ":" + os.environ["PATH"])
    for k in presets:
        env[k] = "y"
    r = subprocess.run(["bash", os.path.join(box, "run.sh"), "--dry-run", "--yes"], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300, start_new_session=True)
    calls = [l.split("\t", 1) for l in (open(os.path.join(box, "calls.log")).read().splitlines() if os.path.exists(os.path.join(box, "calls.log")) else [])]
    muts = ["%s %s" % (t, a) for t, a in ((c + [""])[:2] for c in calls) if mutating(t, a)]
    after = tree(box)
    changed = sorted(set(k for k in set(before) | set(after) if before.get(k) != after.get(k)))
    os.remove(os.path.join(box, "calls.log")) if os.path.exists(os.path.join(box, "calls.log")) else None
    return r.returncode, r.stdout + r.stderr, muts, changed

PRESETS = ("PANEL_DATA_DEL", "DOCKER_DATA_DEL", "REMOVE_DOCKER_IMAGES", "ARCHIVES_DEL", "WDTT_DATA_DEL", "CSQTT_DATA_DEL")
ENV_NODE = "PANEL_URL=https://192.168.77.3:2087\nNODE_TOKEN=node-token-0123456789\nNODE_ENDPOINT=192.168.77.4\nTLS_VERIFY=no\n"
IPT = ("-P PREROUTING ACCEPT\n-A PREROUTING -s 10.81.1.0/24 -p udp -m udp --dport 53 -m comment --comment swg-smartdns -j DNAT --to-destination 127.0.0.1:5354\n"
       "-A POSTROUTING -s 10.81.1.0/24 -o eth0 -j MASQUERADE\n-A FORWARD -i awg0 -j ACCEPT\n"
       "-A POSTROUTING -s 10.1.0.0/24 -m comment --comment \"swg-egress:wdtt1\" -j MASQUERADE\n")

print("[1] a Docker node box")
box = mkbox("docker-node",
            {"docker.ps": "swg-node\n", "docker.turn": "swg-turn-a\n",
             "docker.confs": "/etc/amnezia/amneziawg/awg0.conf\n/etc/wireguard/wg0.conf\n/etc/amnezia/amneziawg/swg_7ed95b28.conf\n",
             "docker.nets": "awg0 10.81.1.1/24\nwg0 10.81.2.1/24\nswg_7ed95b28 10.255.0.0/31\n",
             "ip.links": "awg0\nwg0\nswg_7ed95b28\n", "iptables": IPT},
            {"opt/swg-panel-docker/.env": ENV_NODE, "opt/swg-panel-docker/docker-compose.yml": "services: {}\n",
             "opt/swg-panel-docker/data/node-confs/awg0.conf": "[Interface]\nAddress = 10.81.1.1/24\nListenPort = 51820\n",
             "opt/swg-panel-docker/data/node/iface-keys/awg0.json": "{}", "etc/swg-agent/": ""})
for label, presets in (("--yes, defaults", ()), ("--yes, every destructive question preset to yes", PRESETS)):
    rc, out, muts, changed = run(box, *presets)
    check("[1] (%s) no call that changes anything — no ip link delete, no wg-quick down, no docker rm" % label, not muts, muts)
    check("[1] (%s) the box byte-identical afterwards (the empty /etc/swg-agent included)" % label, not changed, changed)
    check("[1] (%s) …and the plan still says it: \"[dry] down + delete the leftover host interface awg0\"" % label,
          "[dry] down + delete the leftover host interface awg0" in out and "DRY RUN — nothing was actually removed" in out, out[-1500:])

print("\n[2] a Docker files-only box (no swg container left)")
box = mkbox("docker-files", {"docker.ps": "", "docker.turn": "swg-turn-a\n", "iptables": IPT},
            {"opt/swg-panel-docker/.env": ENV_NODE, "opt/swg-panel-docker/docker-compose.yml": "services: {}\n",
             "opt/swg-panel-docker/data/node-confs/awg0.conf": "[Interface]\nAddress = 10.81.1.1/24\n"})
for label, presets in (("--yes, defaults", ()), ("--yes, every destructive question preset to yes", PRESETS)):
    rc, out, muts, changed = run(box, *presets)
    check("[2] (%s) no docker compose down, no docker rm -f" % label, not muts, muts)
    check("[2] (%s) the box byte-identical afterwards" % label, not changed, changed)

print("\n[3] a bare master (panel + node)")
box = mkbox("bare-master", {"docker.ps": "", "iptables": IPT, "nft": "table inet swg_smart\ntable ip filter\n",
                            "ipset": "swgk_ads\n", "ip.rules": "7000:\tfrom all fwmark 0x1b58 lookup 7000\n", "ip.links": "awg0\n"},
            {"opt/swg-panel/swg-panel-server": "x", "etc/systemd/system/swg-panel-server.service": "[Unit]\n",
             "etc/systemd/system/swg-noded.service": "[Unit]\n", "etc/systemd/system/swg-sub.service": "[Unit]\n",
             "opt/swg-noded/swg-noded": "x", "opt/swg-agent/swg-agent": "x",
             "etc/swg-agent/config.json": '{"panel": {"url": "http://127.0.0.1:8088", "token": "t0123456789", "verify": false},'
                                           ' "interfaces": {"awg0": {"conf": "/etc/amnezia/amneziawg/awg0.conf"}}}',
             "etc/amnezia/amneziawg/awg0.conf": "[Interface]\nAddress = 10.71.1.1/24\nListenPort = 51820\n",
             "etc/amnezia/amneziawg/swg_44ba3f30.conf": "[Interface]\nAddress = 10.255.0.1/31\n",
             "etc/swg-panel/install.conf": "PANEL_DOMAIN=192.168.77.1\nCF_TOKEN=secret\n",
             "var/lib/swg-panel/users.json": "{}", "var/lib/swg-noded/iface-keys/awg0.json": "{}"})
for label, presets in (("--yes, defaults", ()), ("--yes, every destructive question preset to yes", PRESETS)):
    rc, out, muts, changed = run(box, *presets)
    check("[3] (%s) no call that changes anything" % label, not muts, muts)
    check("[3] (%s) the box byte-identical afterwards" % label, not changed, changed)
    check("[3] (%s) …and the plan is printed ([dry] lines)" % label, out.count("[dry]") >= 10, out[-800:])

shutil.rmtree(T, ignore_errors=True)
print()
if PERTURBED:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see it"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
