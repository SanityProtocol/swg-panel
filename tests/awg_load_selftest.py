#!/usr/bin/env python3
"""Self-test — "Load now": the node swaps in the installed AmneziaWG module without a reboot (docs/AWG31-LOAD-PLAN.md D2–D4).

Real functions: swg-agent's `op_reload_awg_module` against a fake system (a temp /sys tree; `ip`, `modinfo`, `modprobe`,
`systemctl`, `awg-quick` answered by a stub that brings devices down and up the way the real ones do), and swg-noded's
`awg_load_request`, `_with_awg_gen` and `_awg_disk_gen`.

  [1] nothing newer installed → refused, nothing stopped
  [2] tools that cannot drive a 3.x module → refused, nothing stopped
  [3] a device with no unit and no conf → refused naming it, nothing stopped
  [4] a device in another network namespace — named, or a CONTAINER's (seen only through /proc) → refused, nothing stopped
  [5] the swap: every device down BEFORE the unload, back the way it was started (unit / conf / an exit's conf path),
      on the new module
  [6] the module will not unload → every device brought back, "busy"
  [7] the new module will not load → every device brought back (userspace), "load_failed" — data, not an error
  [8] the node acts ONCE per press, only on a fresh one (age on the panel's clock), with a long agent timeout, in a scope
      of its own (a swg-noded restart must not kill it between the unload and the bring-up)
  [9] the result reaches the snapshot and outlives a daemon restart; the module on disk is reported by its version

Run: python3 tests/awg_load_selftest.py      --plant order | busyback | age | timeout | procscan | noscope   (exit 0 when caught)
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"order": ("[5]", "agent", "    for step in plan:\n        _down(*step)\n", "    pass\n"),
          "busyback": ("[6]", "agent", "        for step in plan:\n            _up(*step)\n        raise AgentError(\"busy\"",
                       "        raise AgentError(\"busy\""),
          "age": ("[8]", "noded", "    if n <= 0 or age < 0 or age > AWG_LOAD_MAX_AGE:", "    if n <= 0:"),
          "timeout": ("[8]", "noded", "\"extra_confs\": extra}, timeout=600,", "\"extra_confs\": extra},"),
          "procscan": ("[4]", "agent", "    if not shutil.which(\"nsenter\"):\n        return out\n", "    return out\n"),
          "noscope": ("[8]", "noded", "                  scope=\"swg-awg-load-%d-%d\" % (n, int(time.time())))", "                  )")}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="awg-load-")
paths = {"agent": os.path.join(ROOT, "swg-agent"), "noded": os.path.join(ROOT, "swg-noded")}
if PLANT:
    _s, which, old, new = PLANTS[PLANT]
    src = open(paths[which]).read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    paths[which] = os.path.join(TMP, "planted-" + which + ".py")
    open(paths[which], "w").write(src.replace(old, new, 1))


def load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NODED_STATE"] = os.path.join(TMP, "state"); os.makedirs(os.environ["SWG_NODED_STATE"])
A = load(paths["agent"], "agent_load")
N = load(paths["noded"], "noded_load")


class Sys:
    """A fake box: devices, a module on disk and a loaded one, units — and the log of what was asked, in order."""
    def __init__(self, devs, loaded="1.0.20251009", disk="3.1.20260812", tools3=True, netns=None, fail_rm=False, fail_load=False, ctr_dev=False):
        self.root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(self.root + "/class/net"); os.makedirs(self.root + "/module/amneziawg")
        open(self.root + "/module/amneziawg/version", "w").write(loaded)
        self.devs, self.disk, self.netns, self.fail_rm, self.fail_load, self.calls = devs, disk, netns or {}, fail_rm, fail_load, []
        for d in devs:
            os.makedirs(self.root + "/class/net/" + d)
        self.ctr_dev, self.proc = ctr_dev, os.path.join(self.root, "proc")
        for pid, ns in (("self", "net:[4026531840]"), ("1", "net:[4026531840]"), ("4242", "net:[4026532999]")):
            os.makedirs(os.path.join(self.proc, pid, "ns")); os.symlink(ns, os.path.join(self.proc, pid, "ns", "net"))
        self.awg = os.path.join(self.root, "awg")
        open(self.awg, "wb").write(b"\x7fELF ... " + (b"HeaderProtectionKey" if tools3 else b"Jc Jmin"))

    def loaded(self):
        p = self.root + "/module/amneziawg/version"
        return open(p).read() if os.path.exists(p) else ""

    def up(self, d):
        os.makedirs(self.root + "/class/net/" + d, exist_ok=True)
        if not self.loaded():
            open(self.root + "/class/net/" + d + "/tun_flags", "w").write("1")   # awg-quick falls to amneziawg-go

    def down(self, d):
        shutil.rmtree(self.root + "/class/net/" + d, ignore_errors=True)

    def kdevs(self):
        return [d for d in self.devs if os.path.isdir(self.root + "/class/net/" + d)
                and not os.path.exists(self.root + "/class/net/" + d + "/tun_flags")]

    def __call__(self, args, input=None, **kw):
        a = [str(x) for x in args]
        self.calls.append(" ".join(a))
        out, rc = "", 0
        if a[:1] == ["ip"] and "netns" in a and "list" in a:
            out = "".join(ns + "\n" for ns in self.netns)
        elif a[:1] == ["nsenter"]:
            if os.readlink(a[1].split("=", 1)[1]) == "net:[4026532999]" and self.ctr_dev:
                out = "9: awg-ctr: <POINTOPOINT>\n"
        elif a[:2] == ["ip", "-n"]:
            out = "".join("%d: %s: <POINTOPOINT>\n" % (i, d) for i, d in enumerate(self.netns.get(a[2], []), 7))
        elif a[:1] == ["ip"] and "amneziawg" in a:
            out = "".join("%d: %s: <POINTOPOINT,NOARP,UP>\n" % (i, d) for i, d in enumerate(self.kdevs(), 5))
        elif a[:1] == ["modinfo"]:
            out = self.disk
        elif a[:2] == ["modprobe", "-r"]:
            if self.fail_rm or self.kdevs():
                rc = 1
            else:
                os.remove(self.root + "/module/amneziawg/version")
        elif a[:1] == ["modprobe"]:
            if self.fail_load:
                rc = 1
            else:
                open(self.root + "/module/amneziawg/version", "w").write(self.disk)
        elif a[:2] == ["systemctl", "is-active"]:
            d = a[-1].split("@", 1)[1]
            rc = 0 if self.devs.get(d) == "unit" and os.path.isdir(self.root + "/class/net/" + d) else 3
        elif a[:1] == ["systemctl"] and a[1] in ("stop", "start"):
            d = a[2].split("@", 1)[1]
            (self.down if a[1] == "stop" else self.up)(d)
        elif a[:1] == ["awg-quick"]:
            d = os.path.basename(a[2]).rsplit(".conf", 1)[0]
            (self.down if a[1] == "down" else self.up)(d)
        return subprocess.CompletedProcess(args, rc, out, "")


def agent_on(box, cfg=None, extra=None):
    A._SYS, A._PROC = box.root, box.proc
    A.subprocess.run = box
    A._scope_available = lambda: False
    A._IN_CONTAINER = False
    A.shutil.which = lambda n: {"systemctl": "/bin/systemctl", "awg": box.awg, "nsenter": "/usr/bin/nsenter"}.get(n)
    try:
        return True, A.op_reload_awg_module(cfg or {"interfaces": {}}, {"op": "reload-awg-module", "extra_confs": extra or {}})
    except A.AgentError as e:
        return False, e.code


CONF = os.path.join(TMP, "awg1.conf"); open(CONF, "w").write("[Interface]\n")
CFG = {"interfaces": {"awg1": {"conf": CONF, "cmd": ["awg"]}}}

SECTION[0] = "[1]"
print("\n[1] nothing newer")
b = Sys({"awg0": "unit"}, disk="1.0.20251009"); ok, r = agent_on(b)
check("refused: nothing_newer", not ok and r == "nothing_newer", r)
check("nothing stopped", not any("stop" in c or "down" in c or "modprobe" in c for c in b.calls), b.calls)

SECTION[0] = "[2]"
print("\n[2] 2.0 tools, a 3.1 module on disk")
b = Sys({"awg0": "unit"}, tools3=False); ok, r = agent_on(b)
check("refused: tools_old, nothing stopped", not ok and r == "tools_old" and not any("stop" in c for c in b.calls), (r, b.calls))

SECTION[0] = "[3]"
print("\n[3] a device with no way back")
b = Sys({"awg0": "unit", "stray": "none"}); ok, r = agent_on(b)
check("refused: no_way_back, nothing stopped", not ok and r == "no_way_back" and not any("stop" in c for c in b.calls), (r, b.calls))

SECTION[0] = "[4]"
print("\n[4] a device in another namespace")
b = Sys({"awg0": "unit"}, netns={"ve": ["e0"]}); ok, r = agent_on(b)
check("refused: other_netns, nothing stopped", not ok and r == "other_netns" and not any("stop" in c for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}, ctr_dev=True); ok, r = agent_on(b)
check("a device in a container's namespace (only /proc sees it) → refused, nothing stopped",
      not ok and r == "other_netns" and not any("stop" in c for c in b.calls), (r, b.calls))

SECTION[0] = "[5]"
print("\n[5] the swap")
b = Sys({"awg0": "unit", "awg1": "conf", "wgx-a1": "exit"})
ok, r = agent_on(b, CFG, {"wgx-a1": os.path.join(TMP, "exits", "wgx-a1.conf")})
check("done, on the new module", ok and r.get("result") == "done" and r.get("loaded") == "3.1.20260812" and r.get("was") == "1.0.20251009", r)
check("every interface back on the kernel module", ok and r.get("ifaces") == {"awg0": "kernel", "awg1": "kernel", "wgx-a1": "kernel"}, r)
i_rm = next((i for i, c in enumerate(b.calls) if c.startswith("modprobe -r")), 99)
downs = [i for i, c in enumerate(b.calls) if c.startswith("systemctl stop") or c.startswith("awg-quick down")]
ups = [i for i, c in enumerate(b.calls) if c.startswith("systemctl start") or c.startswith("awg-quick up")]
check("all three taken down BEFORE the unload, brought up after the load", len(downs) == 3 and max(downs) < i_rm < min(ups), b.calls)
check("each the way it was started: unit, its conf path, the exit's path",
      "systemctl stop awg-quick@awg0" in b.calls and ("awg-quick down " + CONF) in b.calls
      and any(c.startswith("awg-quick down") and c.endswith("wgx-a1.conf") for c in b.calls), b.calls)

SECTION[0] = "[6]"
print("\n[6] the module will not unload")
b = Sys({"awg0": "unit", "awg1": "conf"}, fail_rm=True); ok, r = agent_on(b, CFG)
check("refused: busy", not ok and r == "busy", r)
check("every interface brought back as it was", sorted(b.kdevs()) == ["awg0", "awg1"] and b.loaded() == "1.0.20251009", (b.kdevs(), b.loaded()))

SECTION[0] = "[7]"
print("\n[7] the new module will not load")
b = Sys({"awg0": "unit"}, fail_load=True); ok, r = agent_on(b)
check("reported as load_failed, not raised", ok and r.get("result") == "load_failed", r)
check("the interface is back — on the userspace fallback", ok and r.get("ifaces") == {"awg0": "userspace"}, r)

SECTION[0] = "[8]"
print("\n[8] the request")
seen = []
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: (seen.append((payload, timeout, scope)) or
                                                        {"ok": True, "data": {"result": "done", "was": "1.0.20251009",
                                                                              "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}}})
check("a fresh press acts", N.awg_load_request({"n": 1, "age": 3}, "agent", False) and len(seen) == 1, seen)
check("…with a long agent timeout (never the default 20 s)", seen and seen[0][1] >= 300, seen)
check("…in a transient scope of its own", seen and str(seen[0][2] or "").startswith("swg-awg-load-"), seen)
check("the same press does not act twice", not N.awg_load_request({"n": 1, "age": 5}, "agent", False) and len(seen) == 1, seen)
check("an old press does not act (a restored node)", not N.awg_load_request({"n": 2, "age": 7200}, "agent", False) and len(seen) == 1, seen)
check("a malformed one does not act", not N.awg_load_request({"n": "x"}, "agent", False) and not N.awg_load_request(None, "agent", False)
      and len(seen) == 1, seen)

SECTION[0] = "[9]"
print("\n[9] the report")
N.awg_gen_report = lambda now=None: {"module": "3.1", "disk": "3.1"}
dp = N._with_awg_gen({})
check("the result is in the snapshot", (dp["awg"].get("load") or {}).get("n") == 1 and dp["awg"]["load"].get("ok") is True, dp)
N2 = load(paths["noded"], "noded_load2")
check("…and read back after a daemon restart", (N2._AWG_LOAD["v"] or {}).get("code") == "done", N2._AWG_LOAD)
for ver, want in (("1.0.20251009", "2.0"), ("3.1.20260812", "3.1"), ("3.0.20260731", "3.0"), ("", None), ("garbage", None)):
    N2.run = lambda args, **kw: subprocess.CompletedProcess(args, 0, ver, "")
    check("modinfo %r → %r" % (ver, want), N2._awg_disk_gen() == want, N2._awg_disk_gen())

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
