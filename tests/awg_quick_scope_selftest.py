#!/usr/bin/env python3
"""Self-test — an interface swg-agent brings up is not killed by a swg-noded restart (docs/AWG-DATAPATH-RESILIENCE-PLAN.md,
review finding 2).

On a node without the AmneziaWG kernel module, awg-quick leaves amneziawg-go running. Started as a plain child of the agent
it sat in /system.slice/swg-noded.service and died 2 s after `systemctl restart swg-noded` (measured). `_quick_up` starts it
in a transient scope instead — when the host can make one, which is asked by making one (`systemd-run --scope true`), not by
matching systemd-run's refusal text (worded differently across systemd releases).

  [1] a systemd host: the probe scope, then systemd-run --scope … <tool>-quick up <iface>
  [2] inside a container: the plain call, no probe
  [3] no systemd running: the plain call, no probe
  [4] the probe scope fails (any wording): the plain call; [4b] systemd-run cannot even be executed: the plain call
  [5] awg-quick itself fails ("Unknown device type") after a good probe: the error comes back as is — no second attempt
  [6] no plain `<tool>-quick up` call is left anywhere else in swg-agent
  [7] swg-noded's own exit bring-up: scoped on systemd, plain on docker, plain after a failed probe or an unrunnable one
  [8] neither program keeps a refusal phrase list, and no plain exit `up` is left in swg-noded

Hermetic. Run: python3 tests/awg_quick_scope_selftest.py    (0 = pass)
     --perturb   makes both programs think no scope is available on a systemd host and expects RED on [1] and [7].
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond: FAILS.append(name)
def load(name, path, old=None):
    src = open(path).read()
    if PERTURB and old:
        assert src.count(old) == 1, old; src = src.replace(old, "    if True:\n")
    fd, tmp = tempfile.mkstemp(suffix=".py"); os.write(fd, src.encode()); os.close(fd)
    l = importlib.machinery.SourceFileLoader(name, tmp); m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m
A = load("swgagent", AGENT, '    if _IN_CONTAINER or not os.path.isdir("/run/systemd/system") or not shutil.which("systemd-run"):\n')
N = load("swgnoded", NODED, '    if NODE_KIND == "docker" or not os.path.isdir("/run/systemd/system") or not shutil.which("systemd-run"):\n')
PROBE = ["systemd-run", "--scope", "--quiet", "--collect", "true"]

def scenario(container=False, systemd=True, probe_rc=0, probe_raises=False, fail=None):
    calls = []
    def fake_run(args, input_text=None, check=True):
        calls.append(list(args))
        if fail and fail(args):
            raise A.AgentError("internal", " ".join(args) + " failed: " + fail(args))
        return ""
    def fake_sp(args, **k):
        calls.append(list(args))
        if probe_raises: raise PermissionError(13, "Permission denied", "systemd-run")
        return types.SimpleNamespace(returncode=probe_rc, stdout="", stderr="")
    A.run = fake_run; A._IN_CONTAINER = container
    real_isdir, real_which, real_sp = A.os.path.isdir, A.shutil.which, A.subprocess.run
    A.os.path.isdir = lambda p: systemd if p == "/run/systemd/system" else real_isdir(p)
    A.shutil.which = lambda t: "/usr/bin/systemd-run" if t == "systemd-run" else real_which(t)
    A.subprocess.run = fake_sp
    err = None
    try: A._quick_up("awg", "awg1")
    except Exception as e: err = e
    finally: A.os.path.isdir, A.shutil.which, A.subprocess.run = real_isdir, real_which, real_sp
    return calls, err
PLAIN = ["awg-quick", "up", "awg1"]
c, e = scenario()
check("[1] systemd host → probe, then one scoped call", len(c) == 2 and c[0] == PROBE and c[1][:2] == ["systemd-run", "--scope"] and c[1][-3:] == PLAIN and e is None, c)
c, e = scenario(container=True)
check("[2] container → plain call, no probe", c == [PLAIN] and e is None, c)
c, e = scenario(systemd=False)
check("[3] no systemd → plain call, no probe", c == [PLAIN] and e is None, c)
c, e = scenario(probe_rc=1)
check("[4] the probe scope fails → plain call", c == [PROBE, PLAIN] and e is None, c)
c, e = scenario(probe_raises=True)
check("[4b] systemd-run cannot be executed → plain call", c == [PROBE, PLAIN] and e is None, c)
c, e = scenario(fail=lambda a: "Error: Unknown device type." if a[0] == "systemd-run" else None)
check("[5] awg-quick's own failure propagates, one attempt", len(c) == 2 and e is not None and "Unknown device type" in str(e), (c, e))
check("[6] no plain -quick up left in swg-agent",
      not re.search(r'run\(\s*\[\s*(tool\s*\+\s*"-quick"|f"\{tool\}-quick")\s*,\s*"up"', open(AGENT).read()))
class R:
    def __init__(self, rc=0, err=""): self.returncode, self.stderr, self.stdout = rc, err, ""
def nscenario(kind="baremetal", systemd=True, probe_rc=0):
    calls = []
    def fake_run(args, *a, **k):
        calls.append(list(args))
        return R(probe_rc) if list(args) == PROBE else R(0)
    N.run = fake_run; N.NODE_KIND = kind
    ri, rw = N.os.path.isdir, N.shutil.which
    N.os.path.isdir = lambda p: systemd if p == "/run/systemd/system" else ri(p)
    N.shutil.which = lambda t: "/usr/bin/systemd-run" if t == "systemd-run" else rw(t)
    try: r = N._scoped_up("awg-quick", "/etc/swg-exits/wgx-1.conf")
    finally: N.os.path.isdir, N.shutil.which = ri, rw
    return calls, r
XPLAIN = ["awg-quick", "up", "/etc/swg-exits/wgx-1.conf"]
c, r = nscenario()
check("[7] noded exit on a systemd host → probe, then scoped", len(c) == 2 and c[0] == PROBE and c[1][:2] == ["systemd-run", "--scope"] and c[1][-3:] == XPLAIN, c)
c, r = nscenario(kind="docker")
check("[7] noded exit on a docker node → plain", c == [XPLAIN], c)
c, r = nscenario(probe_rc=1)
check("[7] noded: the probe fails → plain", c == [PROBE, XPLAIN] and r.returncode == 0, c)
c, r = nscenario(probe_rc=127)
check("[7] noded: systemd-run cannot be executed (rc 127) → plain", c == [PROBE, XPLAIN], c)
check("[8] no refusal phrase list left in either program", "_SCOPE_REFUSED" not in open(AGENT).read() and "_SCOPE_REFUSED" not in open(NODED).read())
check("[8] no plain exit `up` left in swg-noded", 'run([_exit_tool(rec), "up", conf])' not in open(NODED).read())
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS))); sys.exit(1 if FAILS else 0)
