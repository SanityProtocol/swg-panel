#!/usr/bin/env python3
"""Self-test — swg-netctl's idle gate: the helper starts only when it has work (docs/CPU-PLAN.md, Part A).

swg-netctl.service starts on every tick of a 10 s timer (the path watch can die unseen, the panel waits as little as 15–60 s
for some answers, and on Docker the timer is the drainer), and every tick was a whole Python start: 80–140 ms of CPU, 8 640 a
day, more than the panel itself spent on hel-infra (2026-10-09). An ExecCondition now runs a gate of bash builtins first.

  [1] The gate's decisions: it runs the helper for any entry in the queue — dotfiles and directories too, exactly what the
      path watch's DirectoryNotEmpty fires on (a gate blind to one would make the path fire, skip and re-fire in a tight
      loop) —, for settings saved since the last run, for a stamp that is missing, junk or past due, and for a clock that
      went back; it skips only an idle tick. The Docker form asks the queue only.
  [2] The drop-in fails OPEN: systemd skips a start on any exit from 1 to 254, so only the gate's explicit 1 may skip — a
      gate that is missing, broken or killed runs the helper, as before the gate existed.
  [3] The stamp, through swg-netctl's real main(): the next own work is the journal refresh, Debug's end or the budget's
      retry, whichever comes first; its mtime is a second before the run read the settings, so a save made while the run
      was reading them is still newer than it; a dry run writes nothing; no settings still writes one.
  [4] One text each: the installers and update.sh render the gate and its drop-ins from lib/common.sh and nowhere else; the
      heal runs after the helper's own; an update that replaces the helper removes the stamp (the new build runs next tick).
  [5] update.sh's heal writes the gate and the drop-in when missing, nothing on a second run, rewrites an older text, writes
      nothing for a unit that is not there, and only says what it would do on a dry run.
  [6] The gate goes with the last unit that runs it (lib/common.sh netctl_gate_reap, uninstall.sh rm_netctl_gate_if_last).

Run: python3 tests/netctl_idle_gate_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nodot        the gate does not count dotfiles (the path watch fires on them: a loop)
     clockback    the gate trusts a due time far ahead (a clock that went back stalls the helper's own work)
     failclosed   the drop-in runs the gate bare (a missing gate stops the helper for good)
     stampnow     the stamp's mtime is when it was written (a save during the run is missed for up to 5 min)
     noretry      the stamp ignores the budget's retry time (a failed journald restart waits 5 min, not 1)
     nodebug      the stamp ignores Debug's end (the caps stay lifted up to 5 min after it)
     healonce     update.sh writes the gate only when missing (an older release's text stays for ever)
     keepstamp    an update replaces the helper and leaves the stamp (the new build's log work waits up to 5 min)
"""
import importlib.machinery, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


FILES = {k: os.path.join(ROOT, f) for k, f in (("common", "lib/common.sh"), ("netctl", "swg-netctl"), ("update", "update.sh"),
                                                ("host", "install-host.sh"), ("docker", "install-docker.sh"),
                                                ("uninstall", "uninstall.sh"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in FILES.items()}
PLANTS = {
    "nodot": ("common", "shopt -s nullglob dotglob\n", "shopt -s nullglob\n"),
    "clockback": ("common", "(( now >= due || due - now > 600 )) && exit 0", "(( now >= due )) && exit 0"),
    "failclosed": ("common", "ExecCondition=/bin/sh -c '/usr/local/bin/swg-netctl-due $1; [ \\$\\$? -eq 1 ] && exit 1; exit 0'",
                   "ExecCondition=/usr/local/bin/swg-netctl-due $1"),
    "stampnow": ("netctl", "os.utime(DUE_STAMP + \".tmp\", (read_at - 1, read_at - 1))", "os.utime(DUE_STAMP + \".tmp\", None)"),
    "noretry": ("netctl", "    if retry and retry > read_at:\n", "    if False:\n"),
    "nodebug": ("netctl", "        if until > read_at:\n", "        if False:\n"),
    "healonce": ("common", '  [ "$(cat "$d/$SWG_NETCTL_DUE_DROPIN" 2>/dev/null)" = "$2" ] && return 0\n',
                 '  [ -f "$d/$SWG_NETCTL_DUE_DROPIN" ] && return 0\n'),
    "keepstamp": ("update", "      run rm -f /run/swg-netctl.due   #", "      : run rm -f /run/swg-netctl.due   #"),
}
if PLANT:
    f, a, b = PLANTS[PLANT]
    assert SRC[f].count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC[f] = SRC[f].replace(a, b)

T = tempfile.mkdtemp(prefix="netctlgate-")


def fn(src, name):
    """A shell function lifted verbatim (its first line may carry a comment after the brace)."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}") or l.rstrip().endswith("; }"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)


C = SRC["common"]
LIB = ("SWG_NETCTL_DUE_DROPIN=swg-due.conf\n" + "".join(
    fn(C, n) for n in ("swg_netctl_due_text", "swg_netctl_due_dropin_text", "swg_netctl_docker_due_dropin_text",
                       "netctl_gate_heal", "netctl_gate_current", "netctl_gate_reap")))
assert re.search(r"^SWG_NETCTL_DUE_DROPIN=swg-due\.conf$", C, re.M), "the drop-in's name moved — this run would measure nothing"


def render(call):
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + LIB + call], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


# ── [1] the gate ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the gate's decisions")
STAMP = os.path.join(T, "run", "swg-netctl.due")
os.makedirs(os.path.dirname(STAMP))
GATE = os.path.join(T, "bin", "swg-netctl-due")
os.makedirs(os.path.dirname(GATE))
gate_text = render("swg_netctl_due_text")
assert gate_text.count("/run/swg-netctl.due") == 1
open(GATE, "w").write(gate_text.replace("/run/swg-netctl.due", STAMP))
os.chmod(GATE, 0o755)
ST = os.path.join(T, "state")
Q = os.path.join(ST, "netctl", "queue")
os.makedirs(Q)
SETTINGS = os.path.join(ST, "panel-settings.json")
open(SETTINGS, "w").write('{"log_level": "info"}')


def gate(*args):
    return subprocess.run([GATE] + list(args), capture_output=True, text=True, timeout=10).returncode


def stamp(due, mtime=None):
    open(STAMP, "w").write("%s\n" % due)
    if mtime is not None:
        os.utime(STAMP, (mtime, mtime))


def idle():
    """the steady state: empty queue, settings older than the stamp, the helper's own work 5 min away"""
    for n in os.listdir(Q):
        p = os.path.join(Q, n)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    now = time.time()
    os.utime(SETTINGS, (now - 100, now - 100))
    stamp(int(now) + 300, now - 50)


idle()
check("[1] CONTROL: an idle tick is skipped (exit 1)", gate(ST) == 1)
for what, make in (("a request", lambda: open(os.path.join(Q, "acc-1.json"), "w").write("{}")),
                   ("a request being written (.json.tmp)", lambda: open(os.path.join(Q, "acc-2.json.tmp"), "w").write("{")),
                   ("a dotfile", lambda: open(os.path.join(Q, ".stray"), "w").write("")),
                   ("a directory", lambda: os.makedirs(os.path.join(Q, "junk")))):
    idle(); make()
    check("[1] %s in the queue → run — and the path watch fires on it too (the same test: not empty)" % what,
          gate(ST) == 0 and os.listdir(Q) != [], os.listdir(Q))
idle(); os.utime(SETTINGS, None)
check("[1] settings saved after the stamp → run", gate(ST) == 0)
idle(); os.remove(STAMP)
check("[1] no stamp (the first tick since boot) → run", gate(ST) == 0)
for junk in ("abc", "", "12a", "-5"):
    idle(); stamp(junk, time.time() - 50)
    check("[1] a junk stamp %r → run" % junk, gate(ST) == 0)
idle(); stamp(int(time.time()) - 1, time.time() - 50)
check("[1] the helper's own work is due → run", gate(ST) == 0)
idle(); stamp(int(time.time()) + 3600, time.time() - 50)
check("[1] a due time far ahead (the clock went back) → run", gate(ST) == 0)
idle(); shutil.rmtree(os.path.join(ST, "netctl"))
check("[1] no queue directory at all, nothing due → skipped (the path watch does not fire on it either)", gate(ST) == 1)
os.makedirs(Q)
check("[1] no state dir argument → run", gate() == 0)
DQ = os.path.join(T, "dq")
os.makedirs(DQ)
check("[1] Docker form: an empty queue → skipped", gate("--queue-only", DQ) == 1)
open(os.path.join(DQ, ".x"), "w").write("")
check("[1] Docker form: a dotfile in the queue → run", gate("--queue-only", DQ) == 0)
check("[1] Docker form: no queue argument → run", gate("--queue-only") == 0)

# ── [2] the drop-in fails open ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the drop-in: only the gate's explicit 1 skips the start")


def exec_condition(dropin, gate_path):
    """the ExecCondition command line, as systemd runs it: argv split on its quotes, `$$` → `$`"""
    line = [l for l in dropin.splitlines() if l.startswith("ExecCondition=")]
    assert len(line) == 1, dropin
    cmd = line[0][len("ExecCondition="):].replace("/usr/local/bin/swg-netctl-due", gate_path)
    m = re.match(r"^(\S+) -c '(.*)'$", cmd)
    argv = [m.group(1), "-c", m.group(2)] if m else cmd.split()
    return [a.replace("$$", "$") for a in argv]


for name, args in (("swg-netctl.service", ("swg_netctl_due_dropin_text", ST)),
                   ("swg-netctl-docker.service", ("swg_netctl_docker_due_dropin_text", DQ))):
    dropin = render("%s %s" % args)
    check("[2] %s: the drop-in names the gate with its argument" % name,
          "/usr/local/bin/swg-netctl-due" in dropin and args[1] in dropin, dropin)
    fake = os.path.join(T, "fake-gate")
    for what, body, want in (("exits 1 (idle)", "exit 1", 1), ("exits 0 (work)", "exit 0", 0),
                             ("is broken (exit 2)", "exit 2", 0), ("is killed", "kill -9 $$", 0), ("is missing", None, 0)):
        if os.path.exists(fake):
            os.remove(fake)
        if body is not None:
            open(fake, "w").write("#!/bin/sh\n%s\n" % body)
            os.chmod(fake, 0o755)
        try:
            rc = subprocess.run(exec_condition(dropin, fake), capture_output=True, text=True, timeout=10).returncode
        except FileNotFoundError:
            rc = 203                                   # what systemd gets when the exec itself fails (EXEC) — a "skip"
        check("[2] %s: a gate that %s → %s" % (name, what, "skip (1)" if want else "run (0)"), rc == want, rc)

# ── [3] the stamp, through the real main() ─────────────────────────────────────────────────────────────────────────────
print("\n[3] the stamp swg-netctl writes")
NST = os.path.join(T, "nstate")
os.makedirs(os.path.join(NST, "netctl", "queue"))
DUE = os.path.join(T, "nrun", "swg-netctl.due")
os.makedirs(os.path.dirname(DUE))
ENV = {"SWG_STATE_DIR": NST, "SWG_NETCTL_DUE": DUE, "SWG_LOG_DROPIN_DIR": os.path.join(T, "dropins"),
       "SWG_LOG_NS_CONF": os.path.join(T, "ns", "swg.conf"), "SWG_NETCTL_STATE": os.path.join(T, "hs"),
       "SWG_LOG_NS_PROBE": os.path.join(T, "no-probe")}
os.makedirs(ENV["SWG_LOG_DROPIN_DIR"])
prog = os.path.join(T, "swg-netctl")
open(prog, "w", encoding="utf-8").write(SRC["netctl"])


def load(dry=False):
    old = {k: os.environ.get(k) for k in list(ENV) + ["SWG_NETCTL_DRYRUN"]}
    os.environ.update(ENV)
    if dry:
        os.environ["SWG_NETCTL_DRYRUN"] = "1"
    else:
        os.environ.pop("SWG_NETCTL_DRYRUN", None)
    ld = importlib.machinery.SourceFileLoader("ng_" + str(time.monotonic_ns()), prog)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
    try:
        ld.exec_module(m)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    m.log_ns_ok = lambda: True
    m.log = lambda *a, **k: None
    return m


M = load()
RESTART_RC = [0]
M.run = lambda argv, env=None, timeout=None: (RESTART_RC[0] if "try-restart" in argv else 0, "")
PSF = os.path.join(NST, "panel-settings.json")


def tick(settings, restart_rc=0, mod=None):
    """one real run: (rc, the stamp's due, its mtime, when the run started)"""
    RESTART_RC[0] = restart_rc
    if os.path.exists(DUE):
        os.remove(DUE)
    if os.path.exists(ENV["SWG_LOG_NS_CONF"]):
        os.remove(ENV["SWG_LOG_NS_CONF"])
    if settings is None:
        if os.path.exists(PSF):
            os.remove(PSF)
    else:
        json.dump(settings, open(PSF, "w"))
    t0 = time.time()
    rc = (mod or M).main(["swg-netctl", "run"])
    if not os.path.exists(DUE):
        return rc, None, None, t0
    return rc, int(open(DUE).read()), os.stat(DUE).st_mtime, t0


rc, due, mt, t0 = tick({"log_level": "info"})
check("[3] a plain run: the next own work is the journal refresh, 5 min on", rc == 0 and due is not None and
      int(t0) + 299 <= due <= int(t0) + 301, (rc, due, t0))
check("[3] …its mtime is a second before the run read the settings", mt is not None and t0 - 1.5 <= mt <= t0 - 0.5, (mt, t0))
# a save the run did not see: settings written the instant the run read them (its start, t0) — older than the stamp's
# write, newer than the time it read them
shutil.copy(DUE, STAMP); os.utime(STAMP, (mt, mt))
for n in os.listdir(Q):
    os.remove(os.path.join(Q, n))
os.utime(SETTINGS, (t0, t0))
check("[3] a save made while the run was reading the settings is still newer than the stamp → the next tick runs",
      gate(ST) == 0)
until = int(time.time()) + 120
rc, due, mt, t0 = tick({"log_level": "info", "log_debug_until": until})
check("[3] Debug ends in 2 min: the stamp wakes the helper then, not in 5", due == until, (due, until))
rc, due, mt, t0 = tick({"log_level": "info", "log_debug_until": -1})
check("[3] Debug until changed (-1): no end to wait for — 5 min", due is not None and abs(due - (int(t0) + 300)) <= 1, (due, t0))
rc, due, mt, t0 = tick({"log_level": "info", "log_mb_panel": 64}, restart_rc=1)
check("[3] journald did not restart: the stamp wakes the helper for the retry (a minute), not in 5",
      due is not None and int(t0) + 59 <= due <= int(t0) + 61, (due, t0))
rc, due, mt, t0 = tick(None)
check("[3] no settings at all: still a stamp (5 min) — the panel's save will be newer", due is not None and
      abs(due - (int(t0) + 300)) <= 1, due)
MD = load(dry=True)
MD.run = M.run
rc, due, mt, t0 = tick({"log_level": "info"}, mod=MD)
check("[3] a dry run writes no stamp", due is None, due)

# ── [4] one text each ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the texts live in lib/common.sh only")
for k in ("host", "docker", "update", "uninstall", "netctl"):
    check("[4] %s carries no copy of the gate or its drop-in" % os.path.basename(FILES[k]),
          "ExecCondition=" not in SRC[k] and "printf -v now" not in SRC[k])
wn = fn(SRC["host"], "write_netctl")
check("[4] install-host.sh's write_netctl renders both from lib/common.sh (the gate by rename: it may be running)",
      "swg_netctl_due_text | writef_atomic /usr/local/bin/swg-netctl-due 755" in wn
      and 'swg_netctl_due_dropin_text "$STATE_DIR" | writef "/etc/systemd/system/swg-netctl.service.d/$SWG_NETCTL_DUE_DROPIN"' in wn, wn[-600:])
wd = fn(SRC["docker"], "wire_docker_netctl")
check("[4] install-docker.sh's wire_docker_netctl heals the gate for its own queue",
      'netctl_gate_heal swg-netctl-docker.service "$(swg_netctl_docker_due_dropin_text "$INSTALL_DIR/data/lib/netctl/queue")"' in wd)
U = SRC["update"]
check("[4] update.sh heals the gate after the helper's own heal, and the Docker gate after the Docker helper's",
      re.search(r"^  ensure_netctl_helper .*\n  ensure_netctl_gate ", U, re.M) is not None
      and re.search(r'^  ensure_netctl_docker "\$prof" .*\n  ensure_netctl_docker_gate "\$prof"', U, re.M) is not None)
check("[4] an update that replaces the helper removes the stamp (the new build runs on the next tick)",
      re.search(r'run cp "\$SRC/swg-netctl" /usr/local/bin/swg-netctl;.*\n      run rm -f /run/swg-netctl\.due', U) is not None)

# ── [5] update.sh's heal ───────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] update.sh's heal")
HEAL = fn(U, "ensure_netctl_gate") + fn(U, "ensure_netctl_docker_gate")


def heal(root, call, dry=False):
    lib = (LIB + HEAL).replace("/etc/systemd/system", root + "/sd").replace("/usr/local/bin", root + "/bin")
    stub = os.path.join(root, "stub")
    os.makedirs(stub, exist_ok=True)
    open(os.path.join(stub, "systemctl"), "w").write('#!/bin/sh\necho "systemctl $*" >> "%s/calls"\n' % root)
    os.chmod(os.path.join(stub, "systemctl"), 0o755)
    script = ('set -euo pipefail\nDRYRUN=%s; DID_UPDATE=no; STATE_DIR=/var/lib/swg-panel; DOCKER_DIR=/opt/swg-panel-docker\n'
              'NOTES=(); note(){ NOTES+=("$*"); }\n%s%s\necho "DID_UPDATE=$DID_UPDATE"\n') % ("true" if dry else "false", lib, call)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, PATH=stub + os.pathsep + os.environ["PATH"]))
    calls = open(os.path.join(root, "calls")).read() if os.path.exists(os.path.join(root, "calls")) else ""
    return r, calls


R = os.path.join(T, "heal")
os.makedirs(os.path.join(R, "sd")); os.makedirs(os.path.join(R, "bin"))
open(os.path.join(R, "sd", "swg-netctl.service"), "w").write("[Service]\n")
DROP = os.path.join(R, "sd", "swg-netctl.service.d", "swg-due.conf")
r, calls = heal(R, "ensure_netctl_gate", dry=True)
check("[5] dry run: says what it would write, writes nothing",
      "[skip] swg-netctl idle gate" in r.stdout and not os.path.exists(DROP) and "daemon-reload" not in calls, (r.stdout, r.stderr))
r, calls = heal(R, "ensure_netctl_gate")
check("[5] missing: the gate and the drop-in are written, systemd reloaded, and the update counts it",
      r.returncode == 0 and os.path.isfile(os.path.join(R, "bin", "swg-netctl-due")) and os.path.isfile(DROP)
      and "daemon-reload" in calls and "DID_UPDATE=yes" in r.stdout, (r.returncode, r.stderr, calls))
check("[5] …the gate is executable and is this release's text", os.access(os.path.join(R, "bin", "swg-netctl-due"), os.X_OK)
      and open(os.path.join(R, "bin", "swg-netctl-due")).read() == gate_text)
check("[5] …the drop-in names this box's state dir", "/usr/local/bin/swg-netctl-due /var/lib/swg-panel;" in open(DROP).read()
      .replace(R + "/bin", "/usr/local/bin"))
os.remove(os.path.join(R, "calls"))
r, calls = heal(R, "ensure_netctl_gate")
check("[5] a second run writes nothing and changes nothing", r.returncode == 0 and "DID_UPDATE=no" in r.stdout and not calls,
      (r.stdout, calls))
open(DROP, "w").write("[Service]\nExecCondition=/usr/local/bin/swg-netctl-due /var/lib/swg-panel\n")   # an older release's text
r, calls = heal(R, "ensure_netctl_gate")
check("[5] an older release's drop-in is rewritten (present is not current)",
      "[ $$? -eq 1 ]" in open(DROP).read() and "DID_UPDATE=yes" in r.stdout, open(DROP).read())
R2 = os.path.join(T, "heal2")
os.makedirs(os.path.join(R2, "sd")); os.makedirs(os.path.join(R2, "bin"))
r, calls = heal(R2, "ensure_netctl_gate; ensure_netctl_docker_gate master")
check("[5] no unit, nothing written (a node-only box, a Docker box without the bare helper)",
      r.returncode == 0 and not os.listdir(os.path.join(R2, "bin")) and not os.listdir(os.path.join(R2, "sd")), os.listdir(R2))
open(os.path.join(R2, "sd", "swg-netctl-docker.service"), "w").write("[Service]\n")
r, calls = heal(R2, "ensure_netctl_docker_gate node")
check("[5] Docker: a node profile gets no gate", not os.listdir(os.path.join(R2, "bin")))
r, calls = heal(R2, "ensure_netctl_docker_gate master")
dd = os.path.join(R2, "sd", "swg-netctl-docker.service.d", "swg-due.conf")
check("[5] Docker: a panel-bearing profile gets the queue-only gate on its own queue",
      os.path.isfile(dd) and "--queue-only /opt/swg-panel-docker/data/lib/netctl/queue;" in open(dd).read(), r.stderr)

# ── [6] removal ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the gate goes with the last unit that runs it")


def reap(root, units, call="netctl_gate_reap", extra=""):
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "sd")); os.makedirs(os.path.join(root, "bin"))
    open(os.path.join(root, "bin", "swg-netctl-due"), "w").write("#!/bin/bash\n")
    for u in units:
        open(os.path.join(root, "sd", u), "w").write("")
    body = (LIB + extra).replace("/etc/systemd/system", root + "/sd").replace("/usr/local/bin", root + "/bin")
    subprocess.run(["bash", "-c", "set -euo pipefail\nDRYRUN=false; SD=%s/sd\nrun(){ \"$@\"; }\n%s%s\n" % (root, body, call)],
                   capture_output=True, text=True, timeout=30)
    return os.path.exists(os.path.join(root, "bin", "swg-netctl-due"))


RR = os.path.join(T, "reap")
UN = SRC["uninstall"]
rmrf = fn(UN, "rmrf") if re.search(r"^rmrf\(\)\{", UN, re.M) else ""
unf = rmrf + fn(UN, "rm_netctl_gate_if_last")
for who, call, extra in (("lib/common.sh", "netctl_gate_reap", ""), ("uninstall.sh", "rm_netctl_gate_if_last", unf)):
    check("[6] %s: kept while the bare helper's unit is there" % who, reap(RR, ["swg-netctl.service"], call, extra))
    check("[6] %s: kept while the Docker drainer's unit is there" % who, reap(RR, ["swg-netctl-docker.service"], call, extra))
    check("[6] %s: removed with the last of them" % who, not reap(RR, [], call, extra))
TB = fn(C, "teardown_bare_panel")
check("[6] a bare→Docker convert's teardown removes both drop-ins and reaps the gate",
      '"/etc/systemd/system/swg-netctl.service.d/$SWG_NETCTL_DUE_DROPIN"' in TB and "netctl_gate_reap" in TB)
check("[6] a Docker→bare convert's helper removal reaps the gate (kept while the bare helper runs it)",
      "netctl_gate_reap" in fn(C, "remove_docker_netctl"))

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
