#!/usr/bin/env python3
"""Self-test — what a pass reads, read once (docs/CPU-PLAN.md B2, and B3's unit states).

The snapshot and the reconcilers each read the same live state for themselves, two or three times a pass (measured on swgt,
10-10: ~130 processes a pass, 2/3 of the node's CPU in them). The hot reads now opt into a per-pass cache; any spawn that is
not a known read clears it.

  [1] The classifier: every read the node makes is a read, every write a write — sh -c and sudo -n unwrapped, nft's global
      options skipped, a shell operator anywhere makes it a write (it fails toward reading again).
  [2] The cache: one read per pass; the next pass reads again; a write in between (from any spawn that is not a read) reads
      again; another thread reads fresh; a timeout / missing tool / missing socket is never kept.
  [3] The sites share: the snapshot's interface dump and the reconciler's (`_iface_dump`, `current_listen_port`) are one read,
      an agent op between them makes it two; `_node_addrs` and the candidates share `ip -4 addr`; the inet and Kernel SNI
      samplers share one `iptables-save`; the snapshot's and the inventory's turn proxies are one `load_turn_proxies`.
  [4] The WDTT / csqtt units: one `systemctl show` for all of them, read like `is-active` (same words), and a unit outside the
      set — or a batch that could not be read — asked on its own; the verifies that wait for a unit still poll it fresh.
  [5] Relay: `systemctl --version` asked once per process (a timeout asked again), docker's answer kept a minute on success
      only, the slice's cgroup path kept while it exists and looked for again once the relay wants it.

Run: python3 tests/noded_pass_reads_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nopass       the cache ignores the pass (a read from the last pass is served)
     noclear      a write does not clear the cache (a read after it is stale)
     nftadd       `nft add` is taken for a read
     shsemi       a `sh -c` with `;` is taken for a read
     iptany       an iptables write is taken for a read when one of its values reads like a read flag (`--comment -S`)
     threadcache  another thread's read is cached
     keep127      a missing tool's answer is cached
     verifycached _csqtt_verify asks the cache (its wait would never see the unit come up)
"""
import importlib.machinery, importlib.util, os, re, subprocess, sys, tempfile, threading, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "nopass": ("    if hit is not None and hit[0] == _LOOP[\"n\"]:", "    if hit is not None:"),
    "noclear": ("        if _PASS and not _is_read(args):\n            _PASS.clear()", "        pass"),
    "iptany": ("        return not any(a in _WRITE_IPTABLES for a in rest) and any(a in _READ_IPTABLES for a in rest)",
               "        return any(a in _READ_IPTABLES for a in rest)"),
    "nftadd": ("        return bool(words) and words[0] == \"list\" and \"-f\" not in rest",
               "        return bool(words) and words[0] in (\"list\", \"add\") and \"-f\" not in rest"),
    "shsemi": ("    if re.search(r\"[;&|<>`$(){}\\n]\", c):\n        return False", "    if False:\n        return False"),
    "threadcache": ("    if threading.current_thread() is not threading.main_thread():\n        return read()\n    hit = _PASS.get(key)",
                    "    hit = _PASS.get(key)"),
    "keep127": ("    if getattr(v, \"returncode\", 0) not in (124, 126, 127):", "    if True:"),
    "verifycached": ('''        if (host_sh("systemctl is-active " + shlex.quote(_csqtt_svc(iface)) + " 2>/dev/null", probe=True).stdout or "").strip() == "active":''',
                     '''        if _unit_active(_csqtt_svc(iface)) == "active":'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="passreads-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("pr_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("pr_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None

# ── [1] the classifier ────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] what is a read")
HELPER = ["docker", "run", "--rm", "--privileged", "--pid=host", "--network", "none", "--entrypoint", "nsenter", "img",
          "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"]                 # host_sh's helper on a docker node: its command decides
READS = [["ip", "-4", "-o", "addr", "show"], ["ip", "-d", "link", "show", "wgx-1"], ["ip", "-o", "link", "show", "dev", "wg1"],
         ["ip", "route", "get", "1.1.1.1"], ["ip", "rule", "show"], ["ip", "route", "show", "table", "7000"],
         ["wg", "show", "wg1", "dump"], ["awg", "show", "interfaces"], ["wg", "pubkey"],
         ["nft", "-j", "list", "counters", "table", "inet", "swg_p2p"], ["nft", "-t", "list", "table", "inet", "swg_p2p"],
         ["nft", "list", "set", "inet", "swg_turn", "peers"], ["iptables", "-t", "mangle", "-S"],
         ["iptables", "-w", "2", "-t", "mangle", "-C", "PREROUTING", "-j", "SWGK"], ["iptables", "-t", "mangle", "-nL", "SWG_INET"],
         ["iptables-save", "-c", "-t", "mangle"], ["ss", "-Hnp", "-t", "state", "established"], ["systemctl", "--version"],
         ["systemctl", "show", "-p", "ControlGroup", "--value", "swg-relay.slice"], ["systemctl", "is-active", "--quiet", "u"],
         ["ipset", "list", "-name"], ["docker", "ps", "--format", "x"], ["docker", "inspect", "-f", "x", "c"],
         ["sh", "-c", "ip -4 route show default 2>/dev/null"], ["sh", "-c", "systemctl is-active x 2>/dev/null"],
         ["sudo", "-n", "sh", "-c", "wg show x dump"]] + [
         HELPER + ["sh", "-c", "export PATH=/run/current-system/sw/bin:$PATH\nsystemctl is-active x 2>/dev/null"]]
WRITES = [["ip", "route", "replace", "default", "dev", "x", "table", "7001"], ["ip", "rule", "add", "from", "10.0.0.0/24", "lookup", "7001"],
          ["ip", "rule", "del", "pref", "7000"], ["ip", "link", "del", "swg_x"], ["ip", "-4", "-force", "-batch", "-"],
          ["wg", "set", "wg1", "peer", "x", "remove"], ["nft", "-f", "-"], ["nft", "-c", "-f", "-"],
          ["nft", "add", "element", "inet", "swg_smart", "s", "{ 1.2.3.4 }"], ["nft", "delete", "table", "inet", "x"],
          ["nft", "flush", "set", "inet", "t", "s"], ["iptables", "-t", "mangle", "-D", "PREROUTING", "-j", "SWGK"],
          ["iptables", "-t", "nat", "-A", "POSTROUTING", "-j", "SNAT"], ["iptables", "-t", "mangle", "-X", "SWGK"],
          ["iptables", "-t", "mangle", "-A", "SWGK", "-m", "comment", "--comment", "-S", "-j", "RETURN"],
          ["iptables", "-t", "mangle", "-L", "-Z", "SWG_INET"],
          ["iptables-restore", "--noflush"], ["systemctl", "daemon-reload"], ["systemctl", "restart", "x"],
          ["ipset", "create", "x", "hash:ip", "-exist"], ["ipset", "destroy", "x"], ["docker", "run", "--rm", "x"],
          ["docker", "rm", "-f", "x"], ["sh", "-c", "sleep 1.5; systemctl is-active x"],
          ["sh", "-c", "systemctl enable --now x >/dev/null 2>&1"], ["sh", "-c", "cat a | grep b"],
          ["sudo", "-n", "sh", "-c", "wg set x peer y remove"], ["systemd-run", "--scope", "/opt/swg-agent/swg-agent"],
          ["/opt/swg-agent/swg-agent"], ["sysctl", "-w", "x=1"], ["modprobe", "amneziawg"], ["kill", "-HUP", "1"], ["curl", "-s", "x"],
          HELPER + ["sh", "-c", "export PATH=/run/current-system/sw/bin:$PATH\nsystemctl restart x"]]
bad_r = [a for a in READS if not N._is_read(a)]
bad_w = [a for a in WRITES if N._is_read(a)]
check("[1] every read the node makes is a read (%d)" % len(READS), not bad_r, bad_r)
check("[1] every write is a write — and anything unknown counts as one (%d)" % len(WRITES), not bad_w, bad_w)

# ── [2] the cache ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the cache")
CALLS = []


def fake(args, input_text=None, timeout=20, env=None, read=None):
    CALLS.append(" ".join(args))
    if args and args[0] == "boom":
        return subprocess.CompletedProcess(args, 127, "", "no such tool")
    return subprocess.CompletedProcess(args, 0, "out-%d" % len(CALLS), "")


REAL_RUN = N.run


def spawn_with(fn):
    """The REAL run(), its spawn faked: swg-noded's own `subprocess` is replaced by one whose run() calls `fn`."""
    N.subprocess = types.SimpleNamespace(
        run=lambda args, input=None, capture_output=True, text=True, timeout=None, env=None: fn(args, input, timeout, env),
        CompletedProcess=subprocess.CompletedProcess, TimeoutExpired=subprocess.TimeoutExpired)


spawn_with(lambda args, i, t, e: fake(args, i, t, e))
N._LOOP["n"] = 100
rd = lambda: N._pass_cached("k", lambda: N.run(["ip", "-4", "-o", "addr", "show"]))
a, b = rd(), rd()
check("[2] one read per pass, shared", len(CALLS) == 1 and a.stdout == b.stdout, CALLS)
N._LOOP["n"] = 101
rd()
check("[2] the next pass reads again", len(CALLS) == 2, CALLS)
N.run(["nft", "add", "element", "inet", "t", "s", "{ 1.2.3.4 }"])
rd()
check("[2] a write in between: read again", len(CALLS) == 4, CALLS)
rd()
check("[2] …then shared again until the next write", len(CALLS) == 4, CALLS)
holder = []
t = threading.Thread(target=lambda: holder.append(rd())); t.start(); t.join()
check("[2] another thread reads fresh (the probe threads read traffic)", len(CALLS) == 5, CALLS)
N._LOOP["n"] = 102
N._pass_cached("boom", lambda: N.run(["boom"])); N._pass_cached("boom", lambda: N.run(["boom"]))
check("[2] a missing tool's answer (127) is not kept", sum(c == "boom" for c in CALLS) == 2, CALLS)
N._PASS["x"] = (N._LOOP["n"], "kept")
N.run(["true"])
check("[2] run() clears the pass's reads after a spawn it does not know as a read", "x" not in N._PASS, N._PASS)
N._PASS["x"] = (N._LOOP["n"], "kept")
N.run(["ip", "-4", "-o", "addr", "show"])
check("[2] …and keeps them after a read", "x" in N._PASS, N._PASS)

# ── [3] the sites share ───────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the sites share their reads")
DUMP = "PRIV\tPUB\t51820\toff\nPEERPUB\tpsk\t1.2.3.4:5\t10.0.0.2/32\t0\t0\t0\toff\n"
CALLS.clear()


def fake2(args, input_text=None, timeout=20, env=None, read=None):
    CALLS.append(" ".join(args))
    if args[1:] == ["show", "all", "dump"]:
        out = "".join("wg1\t" + l for l in DUMP.splitlines(True))     # the `all` form: the interface's name first (B3)
    elif "dump" in args:
        out = DUMP
    elif args[:2] == ["iptables-save", "-c"]:
        out = "*mangle\nCOMMIT\n"
    else:
        out = ""
    return subprocess.CompletedProcess(args, 0, out, "")


spawn_with(lambda args, i, t, e: fake2(args, i, t, e))
N._LOOP["n"] = 200
CFG = {"interfaces": {"wg1": {"cmd": ["wg"], "conf": os.path.join(T, "wg1.conf")}}}
open(CFG["interfaces"]["wg1"]["conf"], "w").write("[Interface]\nListenPort = 51820\n")
N._iface_dump(CFG, "wg1"); N.current_listen_port(CFG, "wg1"); N._iface_dump(CFG, "wg1")
check("[3] the reconciler's dumps of one interface are one read (the pass's `show all dump`)", sum("dump" in c for c in CALLS) == 1, CALLS)
N.run(["/opt/swg-agent/swg-agent"])                                   # an agent op
N._iface_dump(CFG, "wg1")
check("[3] …and an agent op between them makes it a fresh read", sum("dump" in c for c in CALLS) == 2, CALLS)
CALLS.clear()
N._node_addrs(); N._node_addrs()
check("[3] `ip -4 addr` once for the snapshot's readers", sum("addr" in c for c in CALLS) == 1, CALLS)
check("[3] the inet and Kernel SNI samplers read one `iptables-save -c -t mangle` (one key: the same table)",
      N.SWG_INET_TABLE == "mangle" and SRC.count('_pass_cached("iptables-save-c:mangle"') == 1
      and SRC.count('_pass_cached("iptables-save-c:" + SWG_INET_TABLE') == 1)
check("[3] the snapshot's turn proxies and the inventory's are one load (one key)",
      SRC.count('_pass_cached("turn-proxies", load_turn_proxies)') == 2)
N.subprocess = subprocess

# ── [4] the units ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the WDTT / csqtt units")
SHOW = "Id=swg-wdtt-w1.service\nActiveState=active\n\nId=swg-csqtt-c1.service\nActiveState=activating\n"
UC = []
N._wdtt_load = lambda: {"w1": {}}
N._csqtt_load = lambda: {"c1": {}}
N._wdtt_svc = lambda i: "swg-wdtt-" + i
N._csqtt_svc = lambda i: "swg-csqtt-" + i


def fake3(args, input_text=None, timeout=20, env=None, read=None):
    UC.append(" ".join(args))
    if args[:2] == ["systemctl", "show"]:
        return subprocess.CompletedProcess(args, 0, SHOW, "")
    return subprocess.CompletedProcess(args, 0, "failed\n", "")


N.run = fake3
N._host_sh_available = lambda: True
N._LOOP["n"] = 300
got = (N._unit_active("swg-wdtt-w1"), N._unit_active("swg-csqtt-c1"), N._unit_active("swg-wdtt-w1"))
check("[4] one `systemctl show` for all the units, read as is-active reads", got == ("active", "activating", "active")
      and sum(c.startswith("systemctl show") for c in UC) == 1 and not any("is-active" in c for c in UC), (got, UC))
got2 = N._unit_active("swg-wdtt-other")
check("[4] a unit outside the set is asked on its own (`is-active`)", got2 == "failed" and any("is-active" in c for c in UC), UC)
UC.clear(); N._LOOP["n"] = 301
N.run = lambda args, **k: (UC.append(" ".join(args)), subprocess.CompletedProcess(args, 1, "", "dbus"))[1]
N._unit_active("swg-wdtt-w1")
check("[4] a batch that could not be read: the unit is asked on its own", any("is-active" in c for c in UC), UC)
for fname in ("_csqtt_verify",):
    body = SRC[SRC.index("def %s(" % fname):]
    body = body[:body.index("\ndef ", 1)]
    check("[4] %s still polls the unit fresh (a wait for it to come up must never see a cached answer)" % fname,
          "_unit_active" not in body and 'host_sh("systemctl is-active "' in body)
N.run = REAL_RUN

# ── [5] relay ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] relay")
RC = []
N.NODE_KIND = "bare"
N._RELAY_CAP.update(systemd=None, docker_ok_at=0.0)
answers = [subprocess.CompletedProcess([], 124, "", "timeout"), subprocess.CompletedProcess([], 0, "systemd 255", "")]
N.run = lambda args, **k: (RC.append(" ".join(args)), answers.pop(0) if answers else subprocess.CompletedProcess(args, 0, "", ""))[1]
r1, r2, r3 = N._relay_capable(), N._relay_capable(), N._relay_capable()
check("[5] systemctl --version: a timeout is asked again, an answer is kept for the process",
      r1[0] is False and r2 == (True, "") and r3 == (True, "") and len(RC) == 2, (r1, r2, r3, RC))
N.run = REAL_RUN

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
