#!/usr/bin/env python3
"""Self-test — a convert takes swg's log pieces of the units it removes (1.8.9 qualification IN-6 = DN-13, L8-a's teardown half).

1.8.9 gave swg's units journal namespaces (swg-ns.conf drop-ins), level drop-ins and a namespace size under /run, and the
command that reads them (swg-logs). The convert teardowns removed the units and left all of it: a bare → Docker convert kept
swg-update.service.d/swg-ns.conf, so the Docker one-click's output went ONLY to a swg-panel journal nothing sizes any more
(`journalctl -u swg-update` and the compose logs show nothing), plus the four template drop-ins swg-noded gives its turn /
relay / WDTT / csqtt units, swg-logs and /var/log/swg-agent (1.8.8 deferred #11); a Docker → bare convert kept the Docker
host's static swg-update.service.d/swg-log.conf, which masks the bare netctl's level drop-in of the same name.

The REAL functions — lib/common.sh's teardown_bare_panel, lc_teardown_baremetal, remove_docker_netctl and the drop-in
helpers, convert.sh's retire_docker_updater — run in a sandbox root (every absolute path they touch rewritten under a temp
dir; systemctl, nginx and the wg tools are stubs).

  [1] bare → Docker, the panel (teardown_bare_panel): the swg-ns.conf drop-ins of swg-sub / swg-netctl / swg-update and
      the panel's own drop-in dir go, the bare netctl's level drop-ins and the swg-panel namespace's size under /run go;
      an operator's own drop-in beside them stays; swg-logs stays while the bare node is still here
  [2] …then the node (lc_teardown_baremetal): the four template swg-ns.conf drop-ins, swg-noded's level drop-ins and the
      swg-node size under /run go, /var/log/swg-agent goes, swg-logs goes (no bare swg unit left); a host turn proxy the
      operator kept keeps its unit; the journals themselves stay (a convert keeps history; an uninstall takes it)
  [3] Docker → bare (retire_docker_updater, remove_docker_netctl): the Docker host's static swg-update.service.d/
      swg-log.conf and swg-netctl-docker's drop-in dir go; an operator's own drop-in stays

Run: python3 tests/convert_log_dropins_selftest.py      (0 = pass)
     --perturb   the teardowns as q189-int2 shipped them (no log pieces taken) → RED on [1] [2] [3]
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv[1:]
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

LIBF = ["teardown_bare_panel", "lc_teardown_baremetal", "remove_docker_netctl", "swg_log_ns_clear"]
LIBSRC = os.path.join(ROOT, "lib/common.sh")
if "swg_log_teardown(){" in open(LIBSRC).read():
    LIBF.append("swg_log_teardown")
r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f "${@:2}"; echo "SWG_LOG_NS_DROPIN=$SWG_LOG_NS_DROPIN"', "_",
                    LIBSRC] + LIBF, capture_output=True, text=True)
assert all((n + " ()") in r.stdout for n in LIBF), "could not read %s from lib/common.sh" % LIBF
LIB = r.stdout
conv = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
a = conv.index("\nretire_docker_updater(){") + 1
RETIRE = conv[a:conv.index("\n}\n", a) + 3]
if PERTURB:   # q189-int2: the teardowns took the units and left every log piece of them
    for name in ("teardown_bare_panel", "lc_teardown_baremetal"):
        m = re.search(r"^ *swg_log_teardown [^\n]*;?\n", LIB, re.M)
        assert m, "perturbation anchor missing — would FALSE-PASS (%s)" % name
        LIB = LIB.replace(m.group(0), "", 1)
    _a = " /var/log/swg-agent"
    assert LIB.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS (swg-agent's log dir)"
    LIB = LIB.replace(_a, "")
    _m = re.search(r"\n *rm -rf /etc/systemd/system/swg-netctl-docker\.service\.d;?", LIB)
    assert _m, "perturbation anchor missing — would FALSE-PASS (remove_docker_netctl)"
    LIB = LIB.replace(_m.group(0), "")
    _r = re.search(r"\n *rm -f /etc/systemd/system/swg-update\.service\.d/swg-log\.conf[^\n]*", RETIRE)
    assert _r, "perturbation anchor missing — would FALSE-PASS (retire_docker_updater)"
    RETIRE = RETIRE.replace(_r.group(0), "")

def sandboxed(text, ur):
    return re.sub(r"(?<![\w/.$-])(/etc/|/run/|/usr/local/|/opt/|/var/)", lambda m: ur + m.group(1), text)

def run(ur, body):
    sh = ('set -uo pipefail\nDRYRUN=false\nT=%s\n'
          'systemctl(){ echo "SYSTEMCTL $*" >> "$T/calls"; return 0; }\nawg-quick(){ :; }\nwg-quick(){ :; }\nnginx(){ :; }\n'
          'seal_archive(){ :; }\n%s\n%s\n%s\n') % (os.path.dirname(ur), sandboxed(LIB, ur), sandboxed(RETIRE, ur), body)
    return subprocess.run(["bash", "-c", sh], capture_output=True, text=True)

def tree(files):
    t = tempfile.mkdtemp(prefix="cvlog-")
    ur = os.path.join(t, "root")
    for p, c in files.items():
        full = os.path.join(ur, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").write(c)
    return ur
def left(ur):
    return sorted(os.path.relpath(os.path.join(dp, f), ur) for dp, _d, fs in os.walk(ur) for f in fs)

NS_P, NS_N = "[Service]\nLogNamespace=swg-panel\n", "[Service]\nLogNamespace=swg-node\n"
LVL = "[Service]\nLogLevelMax=warning\n"
SD, RD = "etc/systemd/system/", "run/systemd/system/"
BARE = {SD + "swg-panel-server.service": "x", SD + "swg-panel-server.service.d/swg-ns.conf": NS_P,
        SD + "swg-panel-server.service.d/swg-journal.conf": "[Service]\nSupplementaryGroups=systemd-journal\n",
        SD + "swg-sub.service": "x", SD + "swg-sub.service.d/swg-ns.conf": NS_P,
        SD + "swg-sub.service.d/operator.conf": "[Service]\nNice=5\n",
        SD + "swg-netctl.service": "x", SD + "swg-netctl.service.d/swg-ns.conf": NS_P,
        SD + "swg-update.service": "x", SD + "swg-update.service.d/swg-ns.conf": NS_P,
        RD + "swg-netctl.service.d/swg-log.conf": LVL, RD + "swg-update.service.d/swg-log.conf": LVL,
        "run/systemd/journald@swg-panel.conf.d/swg.conf": "[Journal]\nSystemMaxUse=100M\n",
        SD + "swg-noded.service": "x", SD + "swg-noded.service.d/swg-ns.conf": NS_N,
        SD + "vk-turn-proxy-.service.d/swg-ns.conf": NS_N, SD + "swg-relay@.service.d/swg-ns.conf": NS_N,
        SD + "swg-wdtt-.service.d/swg-ns.conf": NS_N, SD + "swg-csqtt-.service.d/swg-ns.conf": NS_N,
        RD + "vk-turn-proxy-.service.d/swg-log.conf": LVL, RD + "swg-wdtt-.service.d/swg-log.conf": LVL,
        RD + "swg-csqtt-.service.d/swg-log.conf": LVL,
        "run/systemd/journald@swg-node.conf.d/swg.conf": "[Journal]\nSystemMaxUse=100M\n",
        SD + "vk-turn-proxy-wings-56000.service": "x",       # migrated to Docker: torn down
        SD + "vk-turn-proxy-anton-56001.service": "x",       # kept on bare metal by the operator
        "usr/local/bin/swg-logs": "x", "var/log/swg-agent/agent.log": "x",
        "var/log/journal/MID.swg-node/system.journal": "x", "var/log/journal/MID.swg-panel/system.journal": "x",
        "opt/swg-noded/swg-noded": "x", "opt/swg-panel/swg-panel-server": "x", "var/lib/swg-panel/users.json": "{}"}

print("[1] bare → Docker: the panel's teardown")
ur = tree(BARE)
r = run(ur, "teardown_bare_panel; echo DONE")
L = left(ur)
gone = [SD + "swg-sub.service.d/swg-ns.conf", SD + "swg-netctl.service.d/swg-ns.conf", SD + "swg-update.service.d/swg-ns.conf",
        RD + "swg-netctl.service.d/swg-log.conf", RD + "swg-update.service.d/swg-log.conf", "run/systemd/journald@swg-panel.conf.d/swg.conf"]
check("the swg-ns.conf of swg-sub / swg-netctl / swg-update, the bare netctl's level drop-ins and the swg-panel size are gone",
      "DONE" in r.stdout and not [g for g in gone if g in L], ([g for g in gone if g in L], r.stderr[-300:]))
check("…swg-update.service.d is gone with it (the Docker one-click's unit gets no namespace from a bare-era drop-in)",
      not os.path.isdir(os.path.join(ur, SD + "swg-update.service.d")), L)
check("…an operator's own drop-in beside them stays", SD + "swg-sub.service.d/operator.conf" in L, L)
check("…swg-logs stays while the bare node is still here", "usr/local/bin/swg-logs" in L, L)

print("\n[2] …then the node's teardown")
r = run(ur, "lc_teardown_baremetal vk-turn-proxy-wings-56000; echo DONE")
L = left(ur)
gone = [SD + "vk-turn-proxy-.service.d/swg-ns.conf", SD + "swg-relay@.service.d/swg-ns.conf", SD + "swg-wdtt-.service.d/swg-ns.conf",
        SD + "swg-csqtt-.service.d/swg-ns.conf", RD + "vk-turn-proxy-.service.d/swg-log.conf", RD + "swg-wdtt-.service.d/swg-log.conf",
        RD + "swg-csqtt-.service.d/swg-log.conf", "run/systemd/journald@swg-node.conf.d/swg.conf"]
check("the four template swg-ns.conf drop-ins, swg-noded's level drop-ins and the swg-node size are gone",
      "DONE" in r.stdout and not [g for g in gone if g in L], ([g for g in gone if g in L], r.stderr[-300:]))
check("…and /var/log/swg-agent (1.8.8 deferred #11)", not os.path.exists(os.path.join(ur, "var/log/swg-agent")), L)
check("…and swg-logs: no bare swg unit is left", "usr/local/bin/swg-logs" not in L, L)
check("…the turn proxy the operator kept on bare metal keeps its unit (the migrated one is gone)",
      SD + "vk-turn-proxy-anton-56001.service" in L and SD + "vk-turn-proxy-wings-56000.service" not in L, L)
check("…the journals stay: a convert keeps the history (an uninstall takes it)",
      "var/log/journal/MID.swg-node/system.journal" in L and "var/log/journal/MID.swg-panel/system.journal" in L, L)

print("\n[3] Docker → bare: the Docker host's own log drop-ins")
ur = tree({SD + "swg-update.service": "x", SD + "swg-update.timer": "x",
           SD + "swg-update.service.d/swg-log.conf": "[Service]\nLogLevelMax=notice\nSyslogLevel=notice\n",
           SD + "swg-netctl-docker.service": "x", SD + "swg-netctl-docker.timer": "x",
           SD + "swg-netctl-docker.service.d/swg-log.conf": "[Service]\nLogLevelMax=notice\nSyslogLevel=notice\n",
           SD + "swg-update.service.d/operator.conf": "[Service]\nNice=5\n", "usr/local/bin/swg-update": "x"})
r = run(ur, "retire_docker_updater; remove_docker_netctl; echo DONE")
L = left(ur)
check("the static swg-update.service.d/swg-log.conf is gone (it masked the bare netctl's level drop-in of that name)",
      "DONE" in r.stdout and SD + "swg-update.service.d/swg-log.conf" not in L, (L, r.stderr[-300:]))
check("…swg-netctl-docker's drop-in dir with its unit", not os.path.isdir(os.path.join(ur, SD + "swg-netctl-docker.service.d")), L)
check("…an operator's own drop-in stays", SD + "swg-update.service.d/operator.conf" in L, L)

print("")
if PERTURB:
    ok = bool(FAILS) and all(not (f.startswith("…an operator") or f.startswith("…swg-logs stays") or f.startswith("…the turn proxy")
                                  or f.startswith("…the journals stay")) for f in FAILS)
    print("perturb: %s" % ("RED as it must be (%d), [1] [2] [3], the controls green" % len(FAILS) if ok else "NOT CAUGHT / WRONG: %s" % FAILS))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
