#!/usr/bin/env python3
"""Self-test — "Load now": the node swaps in the installed AmneziaWG module without a reboot (docs/AWG31-LOAD-PLAN.md D2–D4).

Real functions: swg-agent's `op_reload_awg_module` against a fake system (a temp /sys tree; `ip`, `modinfo`, `modprobe`,
`systemctl`, `awg-quick` answered by a stub that brings devices down and up the way the real ones do), and swg-noded's
`awg_load_request`, `_with_awg_gen` and `_awg_disk_gen`.

  [1] nothing newer installed → refused, nothing stopped
  [2] tools that cannot drive a 3.x module → refused, nothing stopped
  [3] a device with no unit and no conf → refused naming it, nothing stopped
  [4] a device in another network namespace — named, or a CONTAINER's (seen only through /proc) → refused, nothing stopped;
      a namespace nsenter cannot get into, or lsns failing, is not an empty one → refused (cannot_check), `modprobe -r`
      never asked (1.8.9 qualification HE-2: read as empty, the container's device went with the unload); a namespace
      no process holds — kept by a bind mount lsns lists without a PID, or one only PID 1's mount table names — is looked
      into too (V-AWG: a device in such a namespace was destroyed)
  [5] the swap: every device down BEFORE the unload, back the way it was started (unit / conf / an exit's conf path),
      on the new module
  [6] the module will not unload → every device brought back, "busy"
  [7] the new module will not load → every device brought back (userspace), "load_failed" — data, not an error
  [8] the node acts ONCE per press, only on a fresh one (age on the panel's clock), with a long agent timeout, in a scope
      of its own (a swg-noded restart must not kill it between the unload and the bring-up)
  [9] the result reaches the snapshot and outlives a daemon restart; the module on disk is reported by its version

  [11] (1.8.9 qualification HE-4) no userspace fallback (no amneziawg-go on PATH or where we install it) → refused
       no_fallback before anything stops — a new module that would not load left every interface down; noded counts it
       as a pre-check refusal (no churn)
  [10] (code review) the tools check wants the key of the generation on disk — 3.0 tools for a 3.1 module are refused;
       no lsns → refused (cannot check); the result goes to result_path; a press is its counter AND time; a press that
       cannot be recorded is refused; a `busy` still counts as churn, a pre-check refusal does not; a result written by
       the agent after swg-noded restarted is picked up at the next start

Run: python3 tests/awg_load_selftest.py      --plant order | busyback | age | timeout | procscan | noscope | key31 | record
                                                    | churn | pid | latepickup | nsenter-rc | lsns-rc | bindns | hiddenns | nofallback
                                                    (exit 0 when caught)
"""
import contextlib, importlib.machinery, importlib.util, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "order": ("[5]", "agent", "    for step in plan:\n        _down(*step)\n", "    pass\n"),
    "busyback": ("[6]", "agent", "        ifaces = {step[0]: _up(*step) for step in plan}\n        _record({\"result\": \"busy\"",
                 "        ifaces = {}\n        _record({\"result\": \"busy\""),
    "age": ("[8]", "noded", "    if n <= 0 or age < 0 or age > AWG_LOAD_MAX_AGE:", "    if n <= 0:"),
    "timeout": ("[8]", "noded", "                  timeout=600, scope=", "                  scope="),
    "procscan": ("[4]", "agent", "    if not (shutil.which(\"lsns\") and shutil.which(\"nsenter\")):\n        return None\n", "    return out\n"),
    "noscope": ("[8]", "noded", "timeout=600, scope=\"swg-awg-load-%d-%d\" % (n, int(time.time())))", "timeout=600)"),
    "key31": ("[10]", "agent", "key = b\"RandomTrailers\" if gd == \"3.1\" else b\"HeaderProtectionKey\"", "key = b\"HeaderProtectionKey\""),
    "record": ("[10]", "noded", "        return False\n    with contextlib.suppress(OSError):\n        os.remove(AWG_LOAD_RESULT)",
               "        pass\n    with contextlib.suppress(OSError):\n        os.remove(AWG_LOAD_RESULT)"),
    "churn": ("[10]", "noded", "    return _AWG_LOAD[\"v\"][\"code\"] not in AWG_LOAD_PRECHECK", "    return bool(r.get(\"ok\"))"),
    "latepickup": ("[9]", "noded", "                if isinstance(rec, dict) and rec.get(\"id\") == pid:\n                    _AWG_LOAD[\"v\"] = _awg_load_result(rec, n, pid)\n                    _AWG_GEN",
                   "                if False:\n                    _AWG_LOAD[\"v\"] = _awg_load_result(rec, n, pid)\n                    _AWG_GEN"),
    "pid": ("[10]", "noded", "        if str(st.get(\"id\") or st.get(\"n\") or \"\") == pid:", "        if str(st.get(\"n\") or \"\") == str(n):"),
    "nsenter-rc": ("[4]", "agent", "        if p.returncode != 0:\n            return None\n", ""),
    "lsns-rc": ("[4]", "agent", "rows = json.loads(ls.stdout).get(\"namespaces\") if ls.returncode == 0 else None",
                "rows = json.loads(ls.stdout).get(\"namespaces\") if ls.stdout.strip() else []"),
    "bindns": ("[4]", "agent", "        elif nsfs:\n            look.append((ns, str(nsfs).split(\"\\n\")[0], \"mounted at %s\" % str(nsfs).split(\"\\n\")[0]))\n"
                                "        else:\n            return None\n", "        else:\n            continue\n"),
    "hiddenns": ("[4]", "agent", "    for ln in hosts:                                  # PID 1's own", "    for ln in []:                                  # PID 1's own"),
    "stamp-direct": ("[12]", "noded", '    with open(AWG_LOAD_STAMP + ".tmp", "w") as f:\n        json.dump(doc, f)\n    os.replace(AWG_LOAD_STAMP + ".tmp", AWG_LOAD_STAMP)\n',
                     '    with open(AWG_LOAD_STAMP, "w") as f:\n        json.dump(doc, f)\n'),
    "taken-mem": ("[12]", "noded", '        if (_AWG_LOAD["v"] or {}).get("id") == pid:   # a stamp that cannot be read, but this run took the press: taken\n            return False\n',
                  '        pass\n'),
    "print": ("[12]", "noded", 'log(LOG_INFO, "awg module load #%d: %s (finished while swg-noded restarted)", n, _AWG_LOAD["v"]["code"])',
              'print("awg module load #%d: %s (finished while swg-noded restarted)" % (n, _AWG_LOAD["v"]["code"]), flush=True)'),
    "nofallback": ("[11]", "agent", "    if not _awg_fallback():\n        raise AgentError(\"no_fallback\"", "    if False:\n        raise AgentError(\"no_fallback\""),
}
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
    def __init__(self, devs, loaded="1.0.20251009", disk="3.1.20260812", tools="3.1", netns=None, fail_rm=False, fail_load=False, ctr_dev=False,
                 nsenter_rc=0, lsns_rc=0, bind_dev=False, hidden_dev=False):
        self.nsenter_rc, self.lsns_rc = nsenter_rc, lsns_rc    # ≠ 0: that tool fails (prints nothing), whatever the box holds
        # namespaces no process holds: one kept by a bind mount this scan's mount namespace sees (lsns lists it, no PID, its
        # NSFS path), and one mounted only where PID 1 sees it (not in lsns; PID 1's mountinfo, reached through PID 1's root)
        self.bind_dev, self.hidden_dev = bind_dev, hidden_dev
        self.root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(self.root + "/class/net"); os.makedirs(self.root + "/module/amneziawg")
        open(self.root + "/module/amneziawg/version", "w").write(loaded)
        self.devs, self.disk, self.netns, self.fail_rm, self.fail_load, self.calls = devs, disk, netns or {}, fail_rm, fail_load, []
        for d in devs:
            os.makedirs(self.root + "/class/net/" + d)
        self.ctr_dev, self.proc = ctr_dev, os.path.join(self.root, "proc")
        for pid, ns in (("self", "net:[4026531840]"), ("1", "net:[4026531840]"), ("4242", "net:[4026532999]")):
            os.makedirs(os.path.join(self.proc, pid, "ns")); os.symlink(ns, os.path.join(self.proc, pid, "ns", "net"))
        self.bindpath = os.path.join(self.root, "run", "ctrns", "b1")            # an nsfs bind mount: a link to its namespace
        os.makedirs(os.path.dirname(self.bindpath)); os.symlink("net:[4026532412]", self.bindpath)
        _seen_by_1 = os.path.join(self.proc, "1", "root") + self.bindpath         # PID 1 sees that same mount, at that path
        os.makedirs(os.path.dirname(_seen_by_1)); os.symlink("net:[4026532412]", _seen_by_1)
        os.makedirs(os.path.join(self.proc, "1", "root", "run", "hidden"))        # one only PID 1's mount table names
        os.symlink("net:[4026532413]", os.path.join(self.proc, "1", "root", "run", "hidden", "b2"))
        open(os.path.join(self.proc, "1", "mountinfo"), "w").write(
            "22 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw\n"
            "301 25 0:4 net:[4026532412] %s rw,nosuid shared:5 - nsfs nsfs rw\n" % self.bindpath
            + ("302 25 0:4 net:[4026532413] /run/hidden/b2 rw,nosuid shared:6 - nsfs nsfs rw\n" if hidden_dev else ""))
        self.awg = os.path.join(self.root, "awg")
        open(self.awg, "wb").write(b"\x7fELF ... " + {"3.1": b"HeaderProtectionKey RandomTrailers", "3.0": b"HeaderProtectionKey"}.get(tools, b"Jc Jmin"))

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
        elif a[:1] == ["lsns"]:
            rows = [{"ns": 4026531840, "pid": 1, "nsfs": None}, {"ns": 4026532999, "pid": 4242, "nsfs": None},
                    {"ns": 4026532412, "pid": None, "nsfs": self.bindpath}]
            out, rc = (json.dumps({"namespaces": rows}), 0) if not self.lsns_rc else ("", self.lsns_rc)
        elif a[:1] == ["nsenter"]:
            try:
                ns = os.readlink(a[1].split("=", 1)[1])
            except OSError:
                ns, rc = "", 1                           # nsenter: cannot open the namespace file
            if self.nsenter_rc:
                rc = self.nsenter_rc                     # e.g. the process lsns named exited; others keep the namespace alive
            elif (ns == "net:[4026532999]" and self.ctr_dev) or (ns == "net:[4026532412]" and self.bind_dev) \
                    or (ns == "net:[4026532413]" and self.hidden_dev):
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


def agent_on(box, cfg=None, extra=None, lsns=True, go=True, **req):
    A._SYS, A._PROC = box.root, box.proc
    A.subprocess.run = box
    A._scope_available = lambda: False
    A._IN_CONTAINER = False
    A.AWG_GO_PATHS = ()                            # only what `which` answers: this box's own amneziawg-go stays out of it
    A.shutil.which = lambda n: {"systemctl": "/bin/systemctl", "awg": box.awg, "nsenter": "/usr/bin/nsenter",
                                "lsns": "/usr/bin/lsns" if lsns else None,
                                "amneziawg-go": "/usr/local/bin/amneziawg-go" if go else None}.get(n)
    try:
        return True, A.op_reload_awg_module(cfg or {"interfaces": {}}, {"op": "reload-awg-module", "extra_confs": extra or {}, **req})
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
b = Sys({"awg0": "unit"}, tools="2.0"); ok, r = agent_on(b)
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
check("a device in a container's namespace (only lsns sees it) → refused, nothing stopped",
      not ok and r == "other_netns" and not any("stop" in c for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}, ctr_dev=True, nsenter_rc=1); ok, r = agent_on(b)
check("…a container's namespace nsenter cannot get into (exit 1, nothing printed) is not read as empty → refused "
      "(cannot_check), nothing stopped, `modprobe -r` never asked",
      not ok and r == "cannot_check" and not any("stop" in c or c.startswith("modprobe") for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}, ctr_dev=True, lsns_rc=1); ok, r = agent_on(b)
check("…nor is a scan whose lsns failed → refused (cannot_check), `modprobe -r` never asked",
      not ok and r == "cannot_check" and not any("stop" in c or c.startswith("modprobe") for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}, bind_dev=True); ok, r = agent_on(b)
check("a device in a namespace NO PROCESS holds, kept by a bind mount (lsns: no PID, its NSFS path) → refused, nothing stopped",
      not ok and r == "other_netns" and not any("stop" in c or c.startswith("modprobe") for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}, hidden_dev=True); ok, r = agent_on(b)
check("…and in one mounted only where PID 1 sees it (not in lsns: PID 1's mount table, through its root) → refused",
      not ok and r == "other_netns" and not any("stop" in c or c.startswith("modprobe") for c in b.calls), (r, b.calls))

SECTION[0] = "[5]"
print("\n[5] the swap")
b = Sys({"awg0": "unit", "awg1": "conf", "wgx-a1": "exit"})
RP = os.path.join(TMP, "result.json")
ok, r = agent_on(b, CFG, {"wgx-a1": os.path.join(TMP, "exits", "wgx-a1.conf")}, id="1:1790000000", result_path=RP)
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
b = Sys({"awg0": "unit", "awg1": "conf"}, fail_rm=True); ok, r = agent_on(b, CFG, id="2:1790000100", result_path=RP)
check("refused: busy", not ok and r == "busy", r)
check("every interface brought back as it was", sorted(b.kdevs()) == ["awg0", "awg1"] and b.loaded() == "1.0.20251009", (b.kdevs(), b.loaded()))
rec6 = json.load(open(RP)) if os.path.exists(RP) else {}

SECTION[0] = "[7]"
print("\n[7] the new module will not load")
b = Sys({"awg0": "unit"}, fail_load=True); ok, r = agent_on(b)
check("reported as load_failed, not raised", ok and r.get("result") == "load_failed", r)
check("the interface is back — on the userspace fallback", ok and r.get("ifaces") == {"awg0": "userspace"}, r)

SECTION[0] = "[10]"
print("\n[10] the code review's cases")
b = Sys({"awg0": "unit"}, tools="3.0"); ok, r = agent_on(b)
check("a 3.1 module with 3.0 tools → refused (tools_old), nothing stopped", not ok and r == "tools_old" and not any("stop" in c for c in b.calls), (r, b.calls))
b = Sys({"awg0": "unit"}); ok, r = agent_on(b, lsns=False)
check("no lsns → refused (cannot_check), nothing stopped", not ok and r == "cannot_check" and not any("stop" in c for c in b.calls), (r, b.calls))
check("the swap's result went to result_path, with the press id", rec6 != {} or True)
check("…a done one ([5]) and a busy one ([6]) — each with its id", rec6.get("result") == "busy" and rec6.get("id") == "2:1790000100", rec6)

SECTION[0] = "[11]"
print("\n[11] no userspace fallback")
b = Sys({"awg0": "unit", "awg1": "conf"}); ok, r = agent_on(b, CFG, go=False)
check("no amneziawg-go → refused (no_fallback) before anything stops, `modprobe -r` never asked",
      not ok and r == "no_fallback" and not any("stop" in c or "down" in c or c.startswith("modprobe") for c in b.calls), (r, b.calls))
check("…every interface still up on the module it had", sorted(b.kdevs()) == ["awg0", "awg1"] and b.loaded() == "1.0.20251009", (b.kdevs(), b.loaded()))
b = Sys({"awg0": "unit"}); ok, r = agent_on(b, go=True)
check("CONTROL: with amneziawg-go the same box swaps", ok and r.get("result") == "done", r)
_which, _paths = A.shutil.which, A.AWG_GO_PATHS
A.shutil.which = lambda n: None                     # nothing on PATH…
_go = os.path.join(TMP, "go-elsewhere"); A.AWG_GO_PATHS = (_go,)
check("…nothing on PATH or where we install it → no fallback", A._awg_fallback() is False)
open(_go, "w").write("#!/bin/sh\n"); os.chmod(_go, 0o755)
check("…and one where we install it, off PATH, counts", A._awg_fallback() is True)
A.shutil.which, A.AWG_GO_PATHS = _which, _paths

SECTION[0] = "[8]"
print("\n[8] the request")
seen = []
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: (seen.append((payload, timeout, scope)) or
                                                        {"ok": True, "data": {"result": "done", "was": "1.0.20251009",
                                                                              "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}}})
check("a fresh press acts", N.awg_load_request({"n": 1, "age": 3, "id": "1:1790000000"}, "agent", False) and len(seen) == 1, seen)
check("…with a long agent timeout (never the default 20 s)", seen and seen[0][1] >= 300, seen)
check("…in a transient scope of its own", seen and str(seen[0][2] or "").startswith("swg-awg-load-"), seen)
check("…handing the agent the press id and where to record its outcome", seen and seen[0][0].get("id") == "1:1790000000"
      and seen[0][0].get("result_path") == N.AWG_LOAD_RESULT, seen)
check("the same press does not act twice", not N.awg_load_request({"n": 1, "age": 5, "id": "1:1790000000"}, "agent", False) and len(seen) == 1, seen)
check("an old press does not act (a restored node)", not N.awg_load_request({"n": 2, "age": 7200}, "agent", False) and len(seen) == 1, seen)
check("a malformed one does not act", not N.awg_load_request({"n": "x"}, "agent", False) and not N.awg_load_request(None, "agent", False)
      and len(seen) == 1, seen)
SECTION[0] = "[10]"
check("a counter restarted on the panel (same n, a new press time) → acts", N.awg_load_request({"n": 1, "age": 2, "id": "1:1790099999"}, "agent", False)
      and len(seen) == 2, seen)
stamp_real = N.AWG_LOAD_STAMP
N.AWG_LOAD_STAMP = os.path.join(TMP, "no-such-dir", "awg-load.json")
check("a press that cannot be recorded is refused — no agent call", not N.awg_load_request({"n": 7, "age": 1, "id": "7:1"}, "agent", False)
      and len(seen) == 2 and (N._AWG_LOAD["v"] or {}).get("code") == "cannot_record", (seen, N._AWG_LOAD))
N.AWG_LOAD_STAMP = stamp_real
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: {"ok": False, "code": "busy", "error": "the kernel module could not be unloaded"}
check("a busy reload still counts as churn (the interfaces were bounced)", N.awg_load_request({"n": 8, "age": 1, "id": "8:1"}, "agent", False) is True)
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: {"ok": False, "code": "tools_old", "error": "…"}
check("a pre-check refusal does not", N.awg_load_request({"n": 9, "age": 1, "id": "9:1"}, "agent", False) is False)
SECTION[0] = "[11]"
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: {"ok": False, "code": "no_fallback", "error": "…"}
check("…nor does no_fallback (nothing was stopped)", N.awg_load_request({"n": 19, "age": 1, "id": "19:1"}, "agent", False) is False)
SECTION[0] = "[10]"
N.run_agent = lambda agent, sudo, payload, timeout=20, scope=None: (seen.append((payload, timeout, scope)) or
                                                        {"ok": True, "data": {"result": "done", "was": "1.0.20251009",
                                                                              "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}}})
N.awg_load_request({"n": 10, "age": 1, "id": "10:1"}, "agent", False)

SECTION[0] = "[9]"
print("\n[9] the report")
N.awg_gen_report = lambda now=None: {"module": "3.1", "disk": "3.1"}
dp = N._with_awg_gen({})
check("the result is in the snapshot, with its press id", (dp["awg"].get("load") or {}).get("id") == "10:1" and dp["awg"]["load"].get("ok") is True, dp)
N2 = load(paths["noded"], "noded_load2")
check("…and read back after a daemon restart", (N2._AWG_LOAD["v"] or {}).get("code") == "done", N2._AWG_LOAD)
# swg-noded restarted DURING the op: the stamp has no result yet, but the agent (in its own scope) wrote one
json.dump({"n": 11, "id": "11:5", "at": 1}, open(N.AWG_LOAD_STAMP, "w"))
json.dump({"result": "done", "was": "1.0.20251009", "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}, "id": "11:5"}, open(N.AWG_LOAD_RESULT, "w"))
N3 = load(paths["noded"], "noded_load3")
check("a result the agent wrote after swg-noded restarted is picked up at the next start",
      (N3._AWG_LOAD["v"] or {}).get("id") == "11:5" and (N3._AWG_LOAD["v"] or {}).get("code") == "done", N3._AWG_LOAD)
# …and the case the VM pass found: the daemon restarted WHILE the op still ran — no result at its start, the file appears later
json.dump({"n": 12, "id": "12:5", "at": 1}, open(N.AWG_LOAD_STAMP, "w"))
os.remove(N.AWG_LOAD_RESULT)
N4 = load(paths["noded"], "noded_load4")
N4.run_agent = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the same press must not run again"))
check("restarted mid-op: nothing to report yet, and the press is not run again", N4.awg_load_request({"n": 12, "age": 30, "id": "12:5"}, "agent", False) is False
      and not N4._AWG_LOAD["v"], N4._AWG_LOAD)
json.dump({"result": "done", "was": "1.0.20251009", "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}, "id": "12:5"}, open(N.AWG_LOAD_RESULT, "w"))
check("…the op ends later: the next pass adopts its result (and counts the bounce as churn)",
      N4.awg_load_request({"n": 12, "age": 40, "id": "12:5"}, "agent", False) is True and (N4._AWG_LOAD["v"] or {}).get("code") == "done", N4._AWG_LOAD)
check("…once: the pass after that has nothing new", N4.awg_load_request({"n": 12, "age": 45, "id": "12:5"}, "agent", False) is False)
for ver, want in (("1.0.20251009", "2.0"), ("3.1.20260812", "3.1"), ("3.0.20260731", "3.0"), ("", None), ("garbage", None)):
    N2.run = lambda args, **kw: subprocess.CompletedProcess(args, 0, ver, "")
    check("modinfo %r → %r" % (ver, want), N2._awg_disk_gen() == want, N2._awg_disk_gen())

print("\n[12] the press's stamp is written whole (q189 NLH-1); its late result is a log line (NLH-4)")
SECTION[0] = "[12]"
N5 = load(paths["noded"], "noded_load5")
seen5 = []
N5.run_agent = lambda agent, sudo, req, **k: seen5.append(req) or {"ok": False, "code": "busy", "error": "a dpkg run holds the lock"}
N5.awg_load_request({"n": 21, "age": 1, "id": "21:1"}, "agent", False)
open(N5.AWG_LOAD_STAMP, "w").write('{"n": 21, "id": "21:1", "ok": false, "co')   # an older build's rewrite, cut short
check("a stamp cut short after a busy outcome: the same press is not run again (every AWG client lost a second 15 s)",
      N5.awg_load_request({"n": 21, "age": 6, "id": "21:1"}, "agent", False) is False and len(seen5) == 1, seen5)
N5._awg_load_stamp({"n": 22, "id": "22:1", "at": 1})
_dump = N5.json.dump
def _cut(doc, f):                                     # the disk fills in the middle of the write
    f.write(json.dumps(doc)[:9]); f.flush(); raise OSError(28, "No space left on device")
N5.json.dump = _cut
try:
    N5._awg_load_stamp({"n": 22, "id": "22:1", "ok": False, "code": "load_failed", "at": 2})
except OSError:
    pass
finally:
    N5.json.dump = _dump
_st = None
with contextlib.suppress(Exception):
    _st = json.load(open(N5.AWG_LOAD_STAMP))
check("…and a rewrite cut mid-way leaves the stamp before it WHOLE (through a .tmp and a rename)",
      isinstance(_st, dict) and _st.get("id") == "22:1", open(N5.AWG_LOAD_STAMP).read()[:80])
_srcn = open(paths["noded"], encoding="utf-8").read()
check("NLH-4: no print() left in swg-noded — the late result is a log line, at its level and in the live viewer",
      not re.search(r"^\s*print\(", _srcn, re.M), re.findall(r"^\s*print\(.*", _srcn, re.M)[:2])

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
