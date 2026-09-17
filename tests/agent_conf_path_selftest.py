#!/usr/bin/env python3
"""Self-test: swg-agent acts on a managed interface by its conf PATH, and a delete leaves nothing that brings it back.

By name, `wg-quick` looks in /etc/wireguard and nowhere else. A plain-WireGuard conf lives outside it on every container
node (the mount is /etc/amnezia/amneziawg; the link create leaves in /etc/wireguard is container-local and gone after the
first recreate) and on a native node after the documented docker → native carry. Measured (1.8.7 qualification PART 4, A7):
  · svo (docker): panel Restart of wg9 → "wg-quick: `/etc/wireguard/wg9.conf' does not exist"
  · NixOS VM, wg6 carried into /etc/amnezia/amneziawg: Restart failed the same way, and Delete removed the conf and left
    the device UP with its peer — the panel forgot wg6 while its device still reached the node (0% loss to 10.56.0.1)
  · NixOS VM, wg5 switched native → container → native (a conf in BOTH directories): Delete removed one; the next boot
    brought wg5 back from the other — old key, old port, listed by the panel again

  [1] restart of a wg interface whose conf is in the AWG dir: down AND up get the conf PATH, not the name
  [2] stop, start and key restore do the same
  [3] a conf file under another name keeps going by name (wg-quick names the device after the file)
  [4] delete: down by path; the same-named twin with a `#swg:` header in the other directory is removed and its rules reaped
  [5] delete: a same-named conf WITHOUT a `#swg:` header (an operator's own file) is kept
  [6] delete: a link to the removed conf is removed; a link to something else is kept
  [7] delete: a device still present after the down is removed (`ip link delete`); an absent one is not touched
  [8] the directories the agent sweeps are the ones the bootstrap brings interfaces up from (node-entrypoint.sh)

Hermetic: swg-agent imported, `run` recorded, directories and sysfs in a temp tree. Run: python3 tests/agent_conf_path_selftest.py
     --perturb-name     by name again                    → RED on [1] [2] [4]
     --perturb-twin     the twin is not swept             → RED on [4]
     --perturb-marker   any same-named file is swept      → RED on [5]
     --perturb-linkdel  no fallback when the down fails   → RED on [7]
     ("PERTURB OK", exit 0 when something went red; exit 1 if nothing did)
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")
ENTRY = os.path.join(ROOT, "docker", "node-entrypoint.sh")
PERTURBS = {
    "--perturb-name": ('    if conf and os.path.basename(conf) == iface + ".conf" and os.path.isfile(conf):\n        return conf\n',
                       '    if False:\n        return conf\n'),
    "--perturb-twin": ('    for twin_text in _remove_conf_twins(iface, ic.get("conf") or ""):\n',
                       '    for twin_text in []:\n'),
    "--perturb-marker": ('                if not re.search(r"(?m)^#swg:", text.split("[Interface]", 1)[0]):\n                    continue\n',
                         '                if False:\n                    continue\n'),
    "--perturb-linkdel": ('    if os.path.exists(os.path.join(_SYS_NET, iface)):\n', '    if False:\n'),
}
PERTURB = [a for a in sys.argv[1:] if a in PERTURBS]

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(AGENT).read()
REAL_DIRS = re.search(r'^_CONF_DIRS = \(([^)]*)\)', src, re.M)
for flag in PERTURB:
    old, new = PERTURBS[flag]
    if src.count(old) != 1:
        print("PERTURB FAILED — anchor for %s is not in swg-agent exactly once" % flag)
        sys.exit(1)
    src = src.replace(old, new)
path = os.path.join(tempfile.mkdtemp(), "swg-agent")
open(path, "w").write(src)
ld = importlib.machinery.SourceFileLoader("swgagent_confpath", path)
A = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgagent_confpath", ld))
try:
    ld.exec_module(A)
except SystemExit:
    pass

T = tempfile.mkdtemp(prefix="confpath-")
AWGD, WGD, SYS = os.path.join(T, "etc/amnezia/amneziawg"), os.path.join(T, "etc/wireguard"), os.path.join(T, "sys/class/net")
for d in (AWGD, WGD, SYS):
    os.makedirs(d)
A._CONF_DIRS = (AWGD, WGD)
A._SYS_NET = SYS
CALLS, REAPED = [], []
A.run = lambda args, input_text=None, check=True: CALLS.append(list(args)) or ""
A._scope_available = lambda: False
A._iface_unit = lambda action, tool, iface: None
A._reap_egress_rules = lambda text, iface: REAPED.append(text)

CONF = ("#swg:cmd wg\n[Interface]\nPrivateKey = {k}\nAddress = 10.56.0.1/24\nListenPort = 51826\n"
        "PostUp = iptables -t nat -A POSTROUTING -s 10.56.0.0/24 -o ens3 -j MASQUERADE\n")
def put(p, text):
    with open(p, "w") as f:
        f.write(text)
    return p
def cfg(iface, conf):
    return {"interfaces": {iface: {"cmd": ["wg"], "conf": conf}}}
def quick(verb):
    return [c for c in CALLS if len(c) >= 3 and c[0] == "wg-quick" and c[1] == verb]

print("[1] restart, conf in the AWG directory")
c9 = put(os.path.join(AWGD, "wgq9.conf"), CONF.format(k="a" * 43 + "="))
CALLS.clear()
A.op_restart_iface(cfg("wgq9", c9), {"iface": "wgq9"})
check("down gets the path", [c[2] for c in quick("down")] == [c9], quick("down"))
check("up gets the path", [c[2] for c in quick("up")] == [c9], quick("up"))

print("\n[2] stop, start, key restore")
CALLS.clear()
A.op_stop_iface(cfg("wgq9", c9), {"iface": "wgq9"})
check("stop: down by path", [c[2] for c in quick("down")] == [c9], quick("down"))
CALLS.clear()
A.op_start_iface(cfg("wgq9", c9), {"iface": "wgq9"})
check("start: up by path", [c[2] for c in quick("up")] == [c9], quick("up"))
CALLS.clear()
A.op_restore_iface_key(cfg("wgq9", c9), {"iface": "wgq9", "private_key": "b" * 43 + "="})
check("key restore: down and up by path", [c[2] for c in quick("down") + quick("up")] == [c9, c9], CALLS)
check("…and the key really went into that conf", "b" * 43 + "=" in open(c9).read())

print("\n[3] a conf under another name goes by name")
other = put(os.path.join(T, "legacy-awg.conf"), CONF.format(k="c" * 43 + "="))
CALLS.clear()
A.op_restart_iface(cfg("wgq8", other), {"iface": "wgq8"})
check("down and up by name", [c[2] for c in quick("down") + quick("up")] == ["wgq8", "wgq8"], CALLS)

print("\n[4] delete sweeps our twin")
c5 = put(os.path.join(AWGD, "wgq5.conf"), "#swg:onboarded\n#swg:cmd wg\n[Interface]\nAddress = 10.55.0.1/24\n")
t5 = put(os.path.join(WGD, "wgq5.conf"), CONF.format(k="d" * 43 + "="))
CALLS.clear(); REAPED.clear()
A.op_delete_iface(cfg("wgq5", c5), {"iface": "wgq5"})
check("down by path", [c[2] for c in quick("down")] == [c5], quick("down"))
check("the named conf is gone", not os.path.exists(c5))
check("⚠️ the twin with a #swg: header is gone too", not os.path.exists(t5))
check("…and its egress rules were reaped", any("10.56.0.0/24" in (t or "") for t in REAPED), REAPED)

print("\n[5] an operator's own file of the same name is kept")
c4 = put(os.path.join(AWGD, "wgq4.conf"), CONF.format(k="e" * 43 + "="))
own = put(os.path.join(WGD, "wgq4.conf"), "[Interface]\nPrivateKey = " + "f" * 43 + "=\n# the operator's\n")
A.op_delete_iface(cfg("wgq4", c4), {"iface": "wgq4"})
check("named conf gone, the unmarked file kept", not os.path.exists(c4) and os.path.exists(own))

print("\n[6] links")
c3 = put(os.path.join(AWGD, "wgq3.conf"), CONF.format(k="g" * 43 + "="))
l3 = os.path.join(WGD, "wgq3.conf"); os.symlink(c3, l3)
A.op_delete_iface(cfg("wgq3", c3), {"iface": "wgq3"})
check("a link to the removed conf is removed", not os.path.lexists(l3))
c2 = put(os.path.join(AWGD, "wgq2.conf"), CONF.format(k="h" * 43 + "="))
elsewhere = put(os.path.join(T, "elsewhere.conf"), "#swg:cmd wg\n[Interface]\n")
l2 = os.path.join(WGD, "wgq2.conf"); os.symlink(elsewhere, l2)
A.op_delete_iface(cfg("wgq2", c2), {"iface": "wgq2"})
check("a link to something else is kept", os.path.lexists(l2) and os.path.exists(elsewhere))

print("\n[7] the device goes even when the down did not take it")
c1 = put(os.path.join(AWGD, "wgq1.conf"), CONF.format(k="i" * 43 + "="))
os.makedirs(os.path.join(SYS, "wgq1"))             # the down "failed": the device is still there
CALLS.clear()
A.op_delete_iface(cfg("wgq1", c1), {"iface": "wgq1"})
check("⚠️ ip link delete dev wgq1", ["ip", "link", "delete", "dev", "wgq1"] in CALLS, CALLS)
c0 = put(os.path.join(AWGD, "wgq0.conf"), CONF.format(k="j" * 43 + "="))
CALLS.clear()
A.op_delete_iface(cfg("wgq0", c0), {"iface": "wgq0"})
check("no device left → no ip link delete", not any(c[:2] == ["ip", "link"] for c in CALLS), CALLS)

print("\n[8] the swept directories are the bootstrap's")
entry = open(ENTRY).read()
awg = re.search(r'^AWG_DIR=(\S+)', entry, re.M)
wg = re.search(r'\$\{WG_DIR:-([^}]+)\}', entry)
dirs = tuple(x.strip().strip('"') for x in REAL_DIRS.group(1).split(",") if x.strip()) if REAL_DIRS else ()
check("node-entrypoint.sh AWG_DIR and WG_DIR default == swg-agent _CONF_DIRS",
      awg and wg and set(dirs) == {awg.group(1), wg.group(1)}, (dirs, awg and awg.group(1), wg and wg.group(1)))

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — %s undone and every check still passed" % PERTURB)
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
