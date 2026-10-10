#!/usr/bin/env python3
"""Self-test — swg-netctl's idle gate: the helper starts only when it has work (docs/CPU-PLAN.md, Part A).

swg-netctl.service starts on every tick of a 10 s timer (the path watch can die unseen, and the panel waits as little as
15–60 s for some answers; the Docker drainer likewise), and every tick was a whole Python start: 80–140 ms of CPU, 8 640 a
day, more than the panel itself spent on hel-infra (2026-10-09). An ExecCondition now runs a gate of bash builtins first.

  [1] The gate's decisions: it runs the helper for any entry in the queue — dotfiles and directories too, exactly what the
      path watch's DirectoryNotEmpty fires on (a gate blind to one would make the path fire, skip and re-fire in a tight
      loop) —, for settings saved since the last run, for a stamp that is missing, junk or past due, and for a clock that
      went back; it skips only an idle tick. The Docker form asks the queue only.
  [2] The drop-in fails OPEN: systemd skips a start on any exit from 1 to 254, so only the gate's explicit 1 may skip — a
      gate that is missing, broken or killed runs the helper, as before the gate existed. It names no path: the gate gets
      the state dir (the queue) from the unit's own SWG_STATE_DIR (SWG_DOCKER_DIR), under the helper's (the drainer's) own
      default, so the two cannot disagree.
  [3] The stamp, through swg-netctl's real main(): `<due> <the run's time>` — the next own work is the journal refresh,
      Debug's end or the budget's retry, whichever comes first; its mtime is the mtime of the settings version the run read,
      a second before the read at the latest, so a save made while the run was reading them is still newer than it, and so
      is a version the panel renamed into place after a slow fsync (its mtime is when it was written, which can be before
      the run read the old one); copied in nanoseconds, so the real gate skips beside the version the run read, whatever
      its sub-second mtime (a float rounded half of them below their version: Python every tick); a dry run writes
      nothing; no settings still writes one.
  [4] One text each: the installers and update.sh render the gate and its drop-ins from lib/common.sh and nowhere else; the
      heal runs after the helper's own; an update that replaces the helper removes the stamp (the new build runs next tick).
  [5] update.sh's heal writes the gate and the drop-in when missing, nothing on a second run, rewrites an older text, writes
      nothing for a unit that is not there, and only says what it would do on a dry run. The ticks it relies on are on
      time: every swg-netctl / swg-netctl-docker timer text carries AccuracySec=1s, and the heal adds it to an older
      release's timer once (systemd's default 1 min let a quiet box's 10 s ticks drift to 35 s — CPU re-qualification
      AB-F1), never to a timer whose AccuracySec an operator set.
  [6] The gate goes with the last unit that runs it (lib/common.sh netctl_gate_reap, uninstall.sh rm_netctl_gate_if_last).

Run: python3 tests/netctl_idle_gate_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nodot        the gate does not count dotfiles (the path watch fires on them: a loop)
     clockback    the gate ignores the stamp's run time lying ahead (a clock that went back stalls the helper's own work)
     readat       the stamp's mtime is a second before the read, not the version read (a slow-fsync save is missed for 5 min)
     lead0        the gate takes a number with a leading zero (bash reads it as octal, fails, and the gate skips)
     noexec       update.sh takes a gate that lost its exec bit for current (sh answers 126: Python every tick, silently)
     reinstall    a re-install replaces the helper and leaves the stamp (the new build's log work waits up to 5 min)
     drygate      uninstall's dry run never lists the gate (the units it removes are still on disk)
     failclosed   the drop-in runs the gate bare (a missing gate stops the helper for good)
     pathdrift    the drop-in's default state dir is not the helper's (a box without SWG_STATE_DIR: the gate reads elsewhere)
     stampnow     the stamp's mtime is when it was written (a save during the run is missed for up to 5 min)
     floatmtime   the stamp's mtime is set through a float (half the versions read newer than their stamp: every tick runs)
     floatread    the version's mtime is read as a float (the same, from the other side)
     noretry      the stamp ignores the budget's retry time (a failed journald restart waits 5 min, not 1)
     nodebug      the stamp ignores Debug's end (the caps stay lifted up to 5 min after it)
     healonce     update.sh writes the gate only when missing (an older release's text stays for ever)
     keepstamp    an update replaces the helper and leaves the stamp (the new build's log work waits up to 5 min)
     noacc        install-host.sh's timer has no AccuracySec (its ticks drift with whatever else wakes PID 1)
     nomigrate    update.sh leaves an older release's timer without AccuracySec
     operatoracc  update.sh adds AccuracySec to a timer that has an operator's own
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
    "clockback": ("common", "(( now >= due || at > now + 1 )) && exit 0", "(( now >= due )) && exit 0"),
    "readat": ("netctl", "    mt = int((read_at - 1) * 1e9) if seen is None else min(int((read_at - 1) * 1e9), seen)\n",
               "    mt = int((read_at - 1) * 1e9)\n"),
    "lead0": ("common", "[[ $due =~ ^[1-9][0-9]{0,17}$ && $at =~ ^[1-9][0-9]{0,17}$ ]] || exit 0",
              "[[ $due =~ ^[0-9]+$ && $at =~ ^[0-9]+$ ]] || exit 0"),
    "noexec": ("common", '  [ -x /usr/local/bin/swg-netctl-due ] && [ "$(cat /usr/local/bin/swg-netctl-due 2>/dev/null)" = "$(swg_netctl_due_text)" ] \\',
               '  [ "$(cat /usr/local/bin/swg-netctl-due 2>/dev/null)" = "$(swg_netctl_due_text)" ] \\'),
    "reinstall": ("host", "  $DRYRUN || rm -f /run/swg-netctl.due   # the idle gate runs the new build",
                  "  : $DRYRUN || rm -f /run/swg-netctl.due   # the idle gate runs the new build"),
    "drygate": ("uninstall", "case $a in bare-gone) bare=0;; docker-gone) dock=0;; esac", "case $a in nothing) ;; esac"),
    "failclosed": ("common", "ExecCondition=/bin/sh -c '/usr/local/bin/swg-netctl-due \"$${SWG_STATE_DIR:-/var/lib/swg-panel}\"; [ $$? -eq 1 ] && exit 1; exit 0'",
                   "ExecCondition=/usr/local/bin/swg-netctl-due /var/lib/swg-panel"),
    "pathdrift": ("common", '\"$${SWG_STATE_DIR:-/var/lib/swg-panel}\"', '\"$${SWG_STATE_DIR:-/var/lib/swg}\"'),
    "stampnow": ("netctl", "os.utime(DUE_STAMP + \".tmp\", ns=(mt, mt))", "os.utime(DUE_STAMP + \".tmp\", None)"),
    "floatmtime": ("netctl", "os.utime(DUE_STAMP + \".tmp\", ns=(mt, mt))", "os.utime(DUE_STAMP + \".tmp\", (mt / 1e9, mt / 1e9))"),
    "floatread": ("netctl", "os.fstat(f.fileno()).st_mtime_ns", "int(os.fstat(f.fileno()).st_mtime * 1e9)"),
    "noretry": ("netctl", "    if retry and retry > read_at:\n", "    if False:\n"),
    "nodebug": ("netctl", "        if until > read_at:\n", "        if False:\n"),
    "healonce": ("common", '  [ "$(cat "$d/$SWG_NETCTL_DUE_DROPIN" 2>/dev/null)" = "$2" ] && return 0\n',
                 '  [ -f "$d/$SWG_NETCTL_DUE_DROPIN" ] && return 0\n'),
    "keepstamp": ("update", "      run rm -f /run/swg-netctl.due   #", "      : run rm -f /run/swg-netctl.due   #"),
    "noacc": ("host", "[Timer]\nOnActiveSec=10s\nOnUnitActiveSec=10s\nAccuracySec=1s\n", "[Timer]\nOnActiveSec=10s\nOnUnitActiveSec=10s\n"),
    "nomigrate": ("update", "  sed -i '/^\\[Timer\\]$/a AccuracySec=1s' \"$t\"\n", "  :\n"),
    "operatoracc": ("update", "  grep -q '^AccuracySec=' \"$t\" && return 0\n", ""),
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


def stamp(due, mtime=None, at=None, raw=None):
    """the helper's stamp: `<due> <the run's time>` (a run 50 s ago by default), or a raw text"""
    open(STAMP, "w").write(raw if raw is not None else "%s %s\n" % (due, int(time.time()) - 50 if at is None else at))
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
for junk in ("abc", "", "12a", "-5", "0", "0%d" % (int(time.time()) + 300)):
    idle(); stamp(junk, time.time() - 50)
    check("[1] a junk stamp %r → run" % junk, gate(ST) == 0)
idle(); stamp(None, time.time() - 50, raw="%d %s\n" % (int(time.time()) + 300, "0" + str(int(time.time()) - 50)))
check("[1] a run time with a leading zero (bash would read it as octal and fail) → run", gate(ST) == 0)
idle(); stamp(None, time.time() - 50, raw="%d\n" % (int(time.time()) + 300))
check("[1] an older build's stamp (the due time alone) → run", gate(ST) == 0)
idle(); stamp(int(time.time()) - 1, time.time() - 50)
check("[1] the helper's own work is due → run", gate(ST) == 0)
idle(); stamp(int(time.time()) + 270, time.time() - 50, at=int(time.time()) + 30)
check("[1] the run that wrote the stamp lies 30 s ahead (the clock went back) → run", gate(ST) == 0)
idle(); stamp(int(time.time()) + 3600, time.time() - 50, at=int(time.time()) + 3300)
check("[1] …and an hour ahead → run", gate(ST) == 0)
idle(); stamp(int(time.time()) + 300, time.time() - 50, at=int(time.time()))
check("[1] CONTROL: a stamp written this very second is no clock step → skipped", gate(ST) == 1)
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
    """the ExecCondition command line, as systemd runs it: argv split on its quotes, `$$` → `$` (the shell expands what is left
    from the unit's environment)"""
    line = [l for l in dropin.splitlines() if l.startswith("ExecCondition=")]
    assert len(line) == 1, dropin
    cmd = line[0][len("ExecCondition="):].replace("/usr/local/bin/swg-netctl-due", gate_path)
    m = re.match(r"^(\S+) -c '(.*)'$", cmd)
    argv = [m.group(1), "-c", m.group(2)] if m else cmd.split()
    return [a.replace("$$", "$") for a in argv]


HELPER_DEFAULT = re.search(r'^STATE_DIR = os\.environ\.get\("SWG_STATE_DIR", "([^"]+)"\)', SRC["netctl"], re.M).group(1)
DRAINER_DEFAULT = re.search(r'^DIR = os\.environ\.get\("SWG_DOCKER_DIR", "([^"]+)"\)',
                            open(os.path.join(ROOT, "docker", "swg-netctl-docker"), encoding="utf-8").read(), re.M).group(1)
DK = os.path.join(T, "dk")
for name, fname, var, val, want_set, want_unset in (
        ("swg-netctl.service", "swg_netctl_due_dropin_text", "SWG_STATE_DIR", ST, [ST], [HELPER_DEFAULT]),
        ("swg-netctl-docker.service", "swg_netctl_docker_due_dropin_text", "SWG_DOCKER_DIR", DK,
         ["--queue-only", DK + "/data/lib/netctl/queue"], ["--queue-only", DRAINER_DEFAULT + "/data/lib/netctl/queue"])):
    dropin = render(fname)
    check("[2] %s: the drop-in names the gate, and no path — the same text on every box" % name,
          "/usr/local/bin/swg-netctl-due" in dropin and render(fname + " /some/where") == dropin, dropin)
    seen = os.path.join(T, "gate-argv")
    rec = os.path.join(T, "rec-gate")
    open(rec, "w").write('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\nexit 1\n' % seen)
    os.chmod(rec, 0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("SWG_STATE_DIR", "SWG_DOCKER_DIR")}
    subprocess.run(exec_condition(dropin, rec), env=dict(env, **{var: val}), capture_output=True, text=True, timeout=10)
    got_set = open(seen).read().splitlines()
    subprocess.run(exec_condition(dropin, rec), env=env, capture_output=True, text=True, timeout=10)
    got_unset = open(seen).read().splitlines()
    check("[2] %s: the gate reads the unit's %s — and, without one, the %s's own default" % (
          name, var, "helper" if var == "SWG_STATE_DIR" else "drainer"),
          got_set == want_set and got_unset == want_unset, (got_set, got_unset))
    fake = os.path.join(T, "fake-gate")
    for what, body, want in (("exits 1 (idle)", "exit 1", 1), ("exits 0 (work)", "exit 0", 0),
                             ("is broken (exit 2)", "exit 2", 0), ("is killed", "kill -9 $$", 0), ("is missing", None, 0)):
        if os.path.exists(fake):
            os.remove(fake)
        if body is not None:
            open(fake, "w").write("#!/bin/sh\n%s\n" % body)
            os.chmod(fake, 0o755)
        try:
            rc = subprocess.run(exec_condition(dropin, fake), env=dict(env, **{var: val}), capture_output=True, text=True,
                                timeout=10).returncode
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
    return rc, int(open(DUE).read().split()[0]), os.stat(DUE).st_mtime, t0


rc, due, mt, t0 = tick({"log_level": "info"})
check("[3] a plain run: the next own work is the journal refresh, 5 min on", rc == 0 and due is not None and
      int(t0) + 299 <= due <= int(t0) + 301, (rc, due, t0))
check("[3] …its mtime is a second before the run read the settings (saved just now)", mt is not None and t0 - 1.5 <= mt <= t0 - 0.5,
      (mt, t0))
check("[3] …and its second number is the run's time", int(open(DUE).read().split()[1]) in (int(t0), int(t0) + 1), open(DUE).read())
# a save the run did not see: settings written the instant the run read them (its start, t0) — older than the stamp's
# write, newer than the time it read them
shutil.copy(DUE, STAMP); os.utime(STAMP, (mt, mt))
for n in os.listdir(Q):
    os.remove(os.path.join(Q, n))
os.utime(SETTINGS, (t0, t0))
check("[3] a save made while the run was reading the settings is still newer than the stamp → the next tick runs",
      gate(ST) == 0)
# the panel's atomic write: a version's mtime is when its temporary file was written, and its rename can land after a run
# read the old one (a slow fsync) — that version must be newer than the stamp all the same
json.dump({"log_level": "info"}, open(PSF, "w"))
_old = time.time() - 30
os.utime(PSF, (_old, _old))
t1 = time.time()
M.main(["swg-netctl", "run"])
mt1 = os.stat(DUE).st_mtime
check("[3] the stamp's mtime is the version the run read (saved 30 s ago), not a second before the read — to the nanosecond",
      os.stat(DUE).st_mtime_ns == os.stat(PSF).st_mtime_ns, (os.stat(DUE).st_mtime_ns, os.stat(PSF).st_mtime_ns, t1))
shutil.copy(DUE, STAMP); os.utime(STAMP, (mt1, mt1))
for n in os.listdir(Q):
    os.remove(os.path.join(Q, n))
os.utime(SETTINGS, (t1 - 10, t1 - 10))             # written 10 s before the run read the old version, renamed in after it
check("[3] a version written before the run's read and renamed in after it (a slow fsync) is newer → the next tick runs",
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
# end to end: the real gate on the helper's own stamp, beside the settings version that run read, at sub-second mtimes
# as the panel's saves have them — the steady state must skip whatever the nanoseconds (LC F1: a float rounded half of
# them below their version, and that box ran Python on every tick until a save happened to round the other way)
GATE_N = os.path.join(T, "bin", "swg-netctl-due-n")
open(GATE_N, "w").write(gate_text.replace("/run/swg-netctl.due", DUE))
os.chmod(GATE_N, 0o755)
RESTART_RC[0] = 0
_rnd = __import__("random").Random(189)
_ran = []
for _ in range(48):
    json.dump({"log_level": "info"}, open(PSF, "w"))
    _v = (int(time.time()) - 60) * 10 ** 9 + _rnd.randrange(10 ** 9)
    os.utime(PSF, ns=(_v, _v))
    M.main(["swg-netctl", "run"])
    if subprocess.run([GATE_N, NST], capture_output=True, text=True, timeout=10).returncode != 1:
        _ran.append((_v, os.stat(DUE).st_mtime_ns))
check("[3] the next tick after a run is skipped for 48 of 48 sub-second settings mtimes (the stamp carries the version's "
      "mtime to the nanosecond)", not _ran, _ran[:4])

# ── [4] one text each ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the texts live in lib/common.sh only")
for k in ("host", "docker", "update", "uninstall", "netctl"):
    check("[4] %s carries no copy of the gate or its drop-in" % os.path.basename(FILES[k]),
          "ExecCondition=" not in SRC[k] and "printf -v now" not in SRC[k])
wn = fn(SRC["host"], "write_netctl")
check("[4] install-host.sh's write_netctl renders both from lib/common.sh (the gate by rename: it may be running)",
      "swg_netctl_due_text | writef_atomic /usr/local/bin/swg-netctl-due 755" in wn
      and 'swg_netctl_due_dropin_text | writef "/etc/systemd/system/swg-netctl.service.d/$SWG_NETCTL_DUE_DROPIN"' in wn, wn[-600:])
wd = fn(SRC["docker"], "wire_docker_netctl")
check("[4] install-docker.sh's wire_docker_netctl heals the gate (its queue: the unit's SWG_DOCKER_DIR)",
      'netctl_gate_heal swg-netctl-docker.service "$(swg_netctl_docker_due_dropin_text)"' in wd)
U = SRC["update"]
check("[4] update.sh heals the gate after the helper's own heal, and the Docker gate after the Docker helper's",
      re.search(r"^  ensure_netctl_helper .*\n  ensure_netctl_gate ", U, re.M) is not None
      and re.search(r'^  ensure_netctl_docker "\$prof" .*\n  ensure_netctl_docker_gate "\$prof"', U, re.M) is not None)
check("[4] an update that replaces the helper removes the stamp (the new build runs on the next tick)",
      re.search(r'run cp "\$SRC/swg-netctl" /usr/local/bin/swg-netctl;.*\n      run rm -f /run/swg-netctl\.due', U) is not None)
check("[4] …and so does a re-install (install-host.sh write_netctl)",
      re.search(r'cp "\$SRC/swg-netctl" "\$PREFIX/usr/local/bin/swg-netctl";.*\n  \$DRYRUN \|\| rm -f /run/swg-netctl\.due', SRC["host"])
      is not None)

# ── [5] update.sh's heal ───────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] update.sh's heal")
HEAL = fn(U, "ensure_timer_on_time") + fn(U, "ensure_netctl_gate") + fn(U, "ensure_netctl_docker_gate")


def heal(root, call, dry=False):
    lib = (LIB + HEAL).replace("/etc/systemd/system", root + "/sd").replace("/usr/local/bin", root + "/bin")
    stub = os.path.join(root, "stub")
    os.makedirs(stub, exist_ok=True)
    open(os.path.join(stub, "systemctl"), "w").write('#!/bin/sh\necho "systemctl $*" >> "%s/calls"\n' % root)
    os.chmod(os.path.join(stub, "systemctl"), 0o755)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    open(os.path.join(root, "src", "swg-netctl"), "w").write("#!/usr/bin/env python3\n")
    script = ('set -euo pipefail\nDRYRUN=%s; DID_UPDATE=no; STATE_DIR=/var/lib/swg-panel; DOCKER_DIR=/opt/swg-panel-docker; SRC=' + root + '/src\n'
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
check("[5] …the drop-in is this release's text", open(DROP).read().replace(R + "/bin", "/usr/local/bin")
      == render("swg_netctl_due_dropin_text"))
os.remove(os.path.join(R, "calls"))
r, calls = heal(R, "ensure_netctl_gate")
check("[5] a second run writes nothing and changes nothing", r.returncode == 0 and "DID_UPDATE=no" in r.stdout and not calls,
      (r.stdout, calls))
os.chmod(os.path.join(R, "bin", "swg-netctl-due"), 0o644)                    # lost its exec bit (a restore without modes)
r, calls = heal(R, "ensure_netctl_gate")
check("[5] a gate that lost its exec bit is not current: rewritten, executable again",
      "DID_UPDATE=yes" in r.stdout and os.access(os.path.join(R, "bin", "swg-netctl-due"), os.X_OK), (r.stdout, r.stderr))
open(DROP, "w").write("[Service]\nExecCondition=/usr/local/bin/swg-netctl-due /var/lib/swg-panel\n")   # an older release's text
r, calls = heal(R, "ensure_netctl_gate")
check("[5] an older release's drop-in is rewritten (present is not current)",
      "[ $$? -eq 1 ]" in open(DROP).read() and "DID_UPDATE=yes" in r.stdout, open(DROP).read())
R2 = os.path.join(T, "heal2")
os.makedirs(os.path.join(R2, "sd")); os.makedirs(os.path.join(R2, "bin"))
r, calls = heal(R2, "ensure_netctl_gate; ensure_netctl_docker_gate master", dry=True)
check("[5] dry run on a box whose units are not there yet (the helpers' heals would write them): the gates are listed too",
      "[skip] swg-netctl idle gate" in r.stdout and "[skip] swg-netctl-docker idle gate" in r.stdout
      and not os.listdir(os.path.join(R2, "bin")), r.stdout)
r, calls = heal(R2, "ensure_netctl_gate; ensure_netctl_docker_gate master")
check("[5] no unit, nothing written (a node-only box, a Docker box without the bare helper)",
      r.returncode == 0 and not os.listdir(os.path.join(R2, "bin")) and not os.listdir(os.path.join(R2, "sd")), os.listdir(R2))
open(os.path.join(R2, "sd", "swg-netctl-docker.service"), "w").write("[Service]\n")
r, calls = heal(R2, "ensure_netctl_docker_gate node")
check("[5] Docker: a node profile gets no gate", not os.listdir(os.path.join(R2, "bin")))
r, calls = heal(R2, "ensure_netctl_docker_gate master")
dd = os.path.join(R2, "sd", "swg-netctl-docker.service.d", "swg-due.conf")
check("[5] Docker: a panel-bearing profile gets the queue-only gate",
      os.path.isfile(dd) and open(dd).read().replace(R2 + "/bin", "/usr/local/bin") == render("swg_netctl_docker_due_dropin_text"),
      r.stderr)

# the ticks on time (AB-F1)
for k in ("host", "update", "docker"):
    n_all = SRC[k].count("OnUnitActiveSec=10s\n")
    check("[5] %s: every netctl timer text carries AccuracySec=1s (%d)" % (os.path.basename(FILES[k]), n_all),
          n_all >= 1 and SRC[k].count("OnUnitActiveSec=10s\nAccuracySec=1s\n") == n_all)
OLD_TIMER = "[Unit]\nDescription=poll for swg-netctl requests (fallback for the path watch)\n\n[Timer]\nOnActiveSec=10s\n" \
            "OnUnitActiveSec=10s\n\n[Install]\nWantedBy=timers.target\n"
for unit, call in (("swg-netctl", "ensure_netctl_gate"), ("swg-netctl-docker", "ensure_netctl_docker_gate master")):
    RT = os.path.join(T, "acc-" + unit)
    os.makedirs(os.path.join(RT, "sd")); os.makedirs(os.path.join(RT, "bin"))
    open(os.path.join(RT, "sd", unit + ".service"), "w").write("[Service]\n")
    TM = os.path.join(RT, "sd", unit + ".timer")
    open(TM, "w").write(OLD_TIMER)
    r, calls = heal(RT, call, dry=True)
    check("[5] %s: dry run — says it would add AccuracySec, writes nothing" % unit,
          ("[skip] %s.timer: AccuracySec=1s" % unit) in r.stdout and open(TM).read() == OLD_TIMER, (r.stdout, r.stderr))
    r, calls = heal(RT, call)
    t = open(TM).read()
    check("[5] %s: an older release's timer gets AccuracySec=1s once, in [Timer], and is restarted" % unit,
          r.returncode == 0 and t.count("AccuracySec=") == 1 and "[Timer]\nAccuracySec=1s\n" in t
          and ("systemctl restart %s.timer" % unit) in calls and "DID_UPDATE=yes" in r.stdout, (t, calls, r.stderr))
    os.remove(os.path.join(RT, "calls"))
    r, calls = heal(RT, call)
    check("[5] %s: a second run leaves the timer alone" % unit, open(TM).read() == t and ("restart %s.timer" % unit) not in calls,
          calls)
    own = OLD_TIMER.replace("OnUnitActiveSec=10s\n", "OnUnitActiveSec=10s\nAccuracySec=5s\n")
    open(TM, "w").write(own)
    r, calls = heal(RT, call)
    check("[5] %s: a timer whose AccuracySec an operator set is theirs" % unit, open(TM).read() == own, open(TM).read())

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
check("[6] uninstall.sh's dry run (the units it removes still on disk) lists the gate all the same",
      not reap(RR, ["swg-netctl.service", "swg-netctl-docker.service"], "rm_netctl_gate_if_last bare-gone docker-gone", unf))
check("[6] …and keeps it while a unit that run keeps is there",
      reap(RR, ["swg-netctl.service", "swg-netctl-docker.service"], "rm_netctl_gate_if_last bare-gone", unf))
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
