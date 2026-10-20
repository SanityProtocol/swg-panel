#!/usr/bin/env python3
"""Self-test for UPDATE-RESILIENCE Phase 0b — the node's update says what it did.

A node cannot watch its own update: the updater RESTARTS swg-noded, so the process that launched it is gone
before there is anything to read. That is why the output went to DEVNULL. The declarative arm already solved
it by writing `.update-result` — state on line 1, failure tail after it — which report_update_result() relays
on the next sync; the bare arm never got the same treatment.

What the panel could see without this is a TIMEOUT, and only after PROC_GRACE (5 min): "the node never
reported a new version (e.g. it couldn't reach GitHub)". Correct in outline, late, and a guess about cause.

⚠️ And simply WRONG whenever the updater correctly did nothing. The panel decides an update landed by
watching the version advance, so a box that was already current advances nothing, falls through to that
timeout, and is told its network is at fault. Measured live on `svo-im` 2026-08-27: the updater ran clean,
found nothing newer, the box stayed where it belonged. So there are THREE outcomes here, not two, and the
only way to tell them apart that cannot lie is reading the version file before and after.

What this gate holds down:

  1. The generated shell is VALID SHELL. It is assembled from a Python template with an operator-supplied
     command interpolated into it; `bash -n` is the difference between a wrapper and a syntax error that
     silently never runs the updater at all.
  2. All three verdicts, driven by what actually happened on disk — not by what the command claimed.
  3. ⚠️ THE FAILURE TAIL SURVIVES. It is the whole actionable half: "could not fetch … @ main" names a
     blocked box. A verdict with no tail is the timeout we already had.
  4. ⚠️ A DEAD WRAPPER LEAVES NO STALE VERDICT. The result is removed before the updater runs, so a run that
     dies mid-way reports nothing rather than replaying the previous run's answer as this one's.
  5. The reader and the writer agree — swg-noded's own report_update_result() parses what the wrapper wrote.
  6. The exit code is the updater's, so systemd still sees what happened.

Hermetic: no network, no systemd, no panel. The command under test is a local shell script, and the "version
file" is a real file this test rewrites to simulate an update landing.

  7. (1.8.9 qualification IN-13) WHERE it runs: a transient SERVICE that PID 1 starts — outside swg-noded's cgroup and
     its sandbox (a `--scope` stayed in swg-noded's mount namespace: /usr read-only, a /tmp that went away with the
     restart) — waited for, so a refused start is retried; swg-noded's environment handed over in a file only its
     owner reads, filling only what the updater's own lacks; no systemd → the wrapper as swg-noded's child.

Run: python3 tests/node_update_verdict_selftest.py       (0 = pass)
     --perturb   restores the DEVNULL behaviour (the wrapper is bypassed, the command run bare) and expects
                 RED on every verdict check — nothing is written, which is exactly the old silence.
     --perturb-scope   the updater in a `--scope` again → RED on [9];  --perturb-env   no environment handed over → RED on [9]
     --perturb-dollar  the command line handed to systemd-run unescaped again (PID 1 expands ${VAR}, turns $$ into $) → RED on [9]
"""
import importlib.machinery, importlib.util, os, shutil, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PLANT = {"--perturb-scope": ('            r = subprocess.run(["systemd-run", "--unit", "swg-self-update",',
                             '            r = subprocess.run(["systemd-run", "--scope", "--unit", "swg-self-update",'),
         "--perturb-dollar": ('                               + [a.replace("$", "$$") for a in base],', '                               + base,'),
         "--perturb-env": ("        with contextlib.suppress(OSError):\n            _self_update_env()\n",
                           "        with contextlib.suppress(OSError):\n            pass\n")}
PLANTED = [a for a in sys.argv[1:] if a in PLANT]
if PLANTED:
    _src = open(NODED, encoding="utf-8").read()
    _old, _new = PLANT[PLANTED[0]]
    assert _src.count(_old) == 1, "plant anchor missing — this run would measure nothing"
    NODED = os.path.join(tempfile.mkdtemp(prefix="swg-upd-plant-"), "swg-noded")
    open(NODED, "w", encoding="utf-8").write(_src.replace(_old, _new))

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="swg-upd-verdict-")
os.environ["SWG_NODED_STATE"] = TMP
VER = os.path.join(TMP, "VERSION")
open(VER, "w").write("1.8.0-beta\n")

_spec = importlib.util.spec_from_loader("nd", importlib.machinery.SourceFileLoader("nd", NODED))
m = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(m)
except SystemExit:
    pass

RESULT = m.UPDATE_RESULT_FILE
m._noded_version_path = lambda: VER        # point the wrapper at this test's version file


def run(cmd):
    """Render the wrapper for `cmd`, run it, return (rc, state, tail)."""
    if PERTURB:
        # The shape as it shipped: the command, detached, output discarded. Writes nothing.
        rc = subprocess.run(["bash", "-c", cmd], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
    else:
        rc = subprocess.run(["bash", "-c", m._self_update_wrapper(cmd)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    state, tail = "", ""
    try:
        with open(RESULT) as f:
            state = (f.readline() or "").strip()
            tail = f.read().strip()
    except OSError:
        pass
    return rc, state, tail


# ── [1] the generated shell is valid shell ───────────────────────────────────────────────────────────────
for label, cmd in (("simple", "true"),
                   ("a pipeline with quotes", "curl -fsSL 'https://x/y' | bash -s update -y"),
                   ("a list command", ["bash", "-lc", "echo hi"])):
    w = m._self_update_wrapper(cmd)
    r = subprocess.run(["bash", "-n"], input=w, text=True, capture_output=True)
    check("[1] wrapper is valid shell — %s" % label, r.returncode == 0, r.stderr.strip())

# ── [2] the updater ran and the version moved → updated ──────────────────────────────────────────────────
rc, state, tail = run("printf '1.9.0-beta\\n' > %s; echo installed swg-noded" % VER)
check("[2] version advanced → 'updated'", state == "updated", (rc, state))
check("[2b] exit code is the updater's", rc == 0, rc)

# ── [3] the updater ran clean and the version did NOT move → uptodate, not a failure ─────────────────────
rc, state, tail = run("echo 'already at the latest version, nothing to do'")
check("[3] ⚠️ ran clean, nothing newer → 'uptodate' (NOT update-failed)", state == "uptodate", (rc, state))
check("[3b] …and it is a SUCCESS state the panel accepts", state in ("updated", "uptodate"), state)

# ── [4] the updater failed → update-failed, carrying the reason ──────────────────────────────────────────
rc, state, tail = run("echo 'could not fetch https://github.com/x/y @ main — needs a reachable GitHub' >&2; exit 7")
check("[4] non-zero exit → 'update-failed'", state == "update-failed", (rc, state))
check("[4b] ⚠️ the reason survives — this is the actionable half", "could not fetch" in tail, tail[:120])
check("[4c] the updater's exit code is preserved", rc == 7, rc)

# ── [5] the tail is bounded, and keeps the END (where the error is) ──────────────────────────────────────
rc, state, tail = run("for i in $(seq 1 200); do echo line$i; done; echo THE-REAL-ERROR >&2; exit 1")
lines = [l for l in tail.splitlines() if l.strip()]
check("[5] tail is capped at 20 lines", len(lines) <= 20, len(lines))
check("[5b] …and it is the END that is kept", "THE-REAL-ERROR" in tail, tail[-80:])

# ── [6] a wrapper that dies mid-way leaves NO verdict, rather than the previous one ──────────────────────
rc, state, _ = run("echo 'this one failed' >&2; exit 3")     # leave a verdict on disk
check("[6] precondition: a verdict is on disk", state == "update-failed", state)
# Kill the WRAPPER itself mid-run — not the command, which the wrapper would survive and correctly
# report on. `timeout -s KILL` while the command is still sleeping is that scenario exactly.
w = m._self_update_wrapper("sleep 5")
subprocess.run(["timeout", "-s", "KILL", "1", "bash", "-c", w],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
check("[6b] ⚠️ a killed run reports NOTHING, not the last run's verdict",
      not os.path.exists(RESULT), "stale verdict left behind")

# ── [7] the reader agrees with the writer ────────────────────────────────────────────────────────────────
run("echo 'could not fetch https://github.com/x/y @ main' >&2; exit 4")
posted = {}
m.report_proc = lambda panel, state, err=None: posted.update(state=state, err=err)
m.report_update_result({"url": "https://panel.invalid", "token": "t"})
check("[7] swg-noded's own reader parses it", posted.get("state") == "update-failed", posted)
check("[7b] …and relays the reason with it", "could not fetch" in (posted.get("err") or ""), posted.get("err"))
check("[7c] …and consumes the file, so it is reported once", not os.path.exists(RESULT))

# ── [8] the panel retires the request for EVERY verdict this node can send ───────────────────────────────
# Static on purpose, and it says so: this does not exercise the HTTP path. What it holds down is the
# PAIRING, which is where the realistic failure is. The node emits three terminal states; the panel must
# drop the pending `update` on all of them, because its PROC_GRACE sweep otherwise overwrites the verdict
# five minutes later with a guess — and then Phase 0b has bought nothing at all. Two readers of one
# vocabulary, compared, rather than each checked against itself.
import re
emitted = set(re.findall(r"\bS=([a-z-]+)", m._self_update_wrapper("true")))
check("[8] the wrapper emits the three verdicts", emitted == {"updated", "uptodate", "update-failed"}, emitted)
_panel = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
_mm = re.search(r'if state in \(([^)]*)\):\s*\n\s*nodes\[nid\]\.pop\("update", None\)', _panel)
cleared = set(re.findall(r'"([a-z-]+)"', _mm.group(1))) if _mm else set()
check("[8b] the panel has a clearing rule at all", bool(_mm))
check("[8c] ⚠️ …and it covers every verdict the node can send", emitted <= cleared, sorted(emitted - cleared))

# ── [9] WHERE the updater runs (1.8.9 qualification IN-13) ─────────────────────────────────────────────────
# A `systemd-run --scope` only moves the updater to another cgroup: it stayed in swg-noded's mount namespace, where /usr is
# read-only (apt, the module source, swg-logs: EROFS) and its private /tmp goes away when the update restarts swg-noded.
# Measured on this box's systemd from a ProtectSystem=true unit (q189 IN-13): the scope ran in the unit's namespace with /usr
# READ-ONLY and mktemp failing after the unit stopped; a transient service ran in PID 1's, /usr writable, /tmp kept.
# systemd itself is not asked here: its presence and systemd-run are stubbed, and every call is recorded.
class _Path:
    def __init__(self, sysd): self.sysd = sysd
    def exists(self, p): return self.sysd if p == "/run/systemd/system" else os.path.exists(p)
    def __getattr__(self, k): return getattr(os.path, k)
class _Os:
    def __init__(self, sysd): self.path = _Path(sysd)
    def __getattr__(self, k): return getattr(os, k)
CALLS, LOGS = [], []
class _Sub:
    def __init__(self, rc=0, err=""): self.rc, self.err = rc, err
    def run(self, argv, **kw):
        CALLS.append(("run", list(argv), kw)); return types.SimpleNamespace(returncode=self.rc, stdout="", stderr=self.err)
    def Popen(self, argv, **kw):
        CALLS.append(("Popen", list(argv), kw)); return types.SimpleNamespace(pid=1)
    def __getattr__(self, k): return getattr(subprocess, k)
_real = (m.os, m.shutil, m.subprocess, m.log)
_which = types.SimpleNamespace(which=lambda n: "/usr/bin/" + n)
MIRROR = "https://mirror.example/gh 'quoted' $x"            # what the panel's turn_mirror puts into swg-noded's environment
os.environ["SWG_TURN_MIRROR"] = MIRROR
try:
    m.log = lambda lvl, msg, *a: LOGS.append((lvl, (msg % a) if a else msg))
    m.os, m.shutil, m.subprocess = _Os(True), _which, _Sub()
    ok = m.run_self_update({"node": {"update_cmd": "true"}}, {"to": "9.9.9"})
    kind, argv, kw = CALLS[-1] if CALLS else (None, [], {})
    check("[9] systemd: a transient SERVICE that PID 1 starts — systemd-run WITHOUT --scope, one unit name, collected",
          ok is True and kind == "run" and argv[:5] == ["systemd-run", "--unit", "swg-self-update", "--collect", "--quiet"]
          and "--scope" not in argv, (ok, kind, argv[:8]))
    check("[9b] …running the wrapper, waited for (its answer is the start's)", argv[-3:-1] == ["bash", "-c"] and kw.get("timeout"),
          (argv[-3:-1], kw.get("timeout")))
    check("[9c] …and the log line says where it runs", any("swg-self-update.service, outside swg-noded's sandbox" in s for _, s in LOGS), LOGS)
    _st = os.stat(m.UPDATE_ENV_FILE) if os.path.exists(m.UPDATE_ENV_FILE) else None
    check("[9d] swg-noded's environment is handed over in a file only its owner reads — never --setenv (a unit's "
          "environment is readable by every local user over D-Bus)",
          _st is not None and (_st.st_mode & 0o777) == 0o600 and not any(a.startswith("--setenv") or a == "-E" for a in argv),
          (_st and oct(_st.st_mode), argv[:10]))
    m.os, m.shutil, m.subprocess = _real[:3]
    _seen = os.path.join(TMP, "seen")
    m.os = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    m.os.geteuid = lambda: 0                              # the wrapper as root builds it (swg-noded runs as root): no sudo,
    _w = m._self_update_wrapper('printf "%s|%s" "$SWG_TURN_MIRROR" "$PATH" > ' + _seen)   # which would reset the environment
    m.os = _real[0]
    subprocess.run(["env", "-i", "PATH=/usr/bin:/bin", "bash", "-c", _w], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _got = open(_seen).read() if os.path.exists(_seen) else ""
    check("[9e] the updater, started with PID 1's environment, gets swg-noded's SWG_TURN_MIRROR byte for byte (the "
          "amneziawg-go fetch's mirror); what it has of its own (PATH) stays its own", _got == MIRROR + "|/usr/bin:/bin", _got)
    check("[9f] …and the file is removed once read", not os.path.exists(m.UPDATE_ENV_FILE))
    m.os, m.shutil, m.subprocess = _Os(True), _which, _Sub(1, "Failed to start transient service unit: Unit swg-self-update.service "
                                                            "was already loaded or has a fragment file.")
    del LOGS[:]
    ok = m.run_self_update({"node": {"update_cmd": "true"}}, {"to": "9.9.9"})
    check("[9g] a start systemd refuses (a run still going under the one unit name) → False: the next sync tries again, "
          "systemd's reason in the log", ok is False and any("already loaded" in s for _, s in LOGS), (ok, LOGS))
    # [9i] an operator's own update_cmd holding $HOME, ${X}, $$: PID 1 expands ${VAR} and turns $$ into $ in a service's
    # command line (systemd-run(1)) — every `$` goes to systemd-run doubled, so the shell gets the text exactly as written
    m.os, m.shutil, m.subprocess = _Os(True), _which, _Sub()
    del CALLS[:]
    _cmd = 'X=mine; echo "$HOME ${X} $$" > /dev/null'
    m.run_self_update({"node": {"update_cmd": _cmd}}, {"to": "9.9.9"})
    _a = CALLS[-1][1] if CALLS else []
    _w = _a[-1] if _a else ""
    check("[9i] an update_cmd with $HOME / ${X} / $$: every `$` reaches systemd-run as `$$` — the shell gets it as written",
          _a[-3:-1] == ["bash", "-c"] and "$$HOME $${X} $$$$" in _w and _w.replace("$$", "$") == m._self_update_wrapper(_cmd)
          and "$" not in _w.replace("$$", ""), _w[-160:])
    if shutil.which("sudo") and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0 and \
            os.path.isdir("/run/systemd/system") and shutil.which("systemd-run"):
        # …and systemd itself agrees: the argv run for real (a throwaway unit name, waited for), the shell's own ${X} and $$
        _out = os.path.join(TMP, "dollar")
        m.run_self_update({"node": {"update_cmd": 'X=mine; printf "%%s|%%s" "${X}" "$$" > %s' % _out}}, {"to": "9.9.9"})
        _a = list(CALLS[-1][1]); _a[_a.index("--unit") + 1] = "q189-dollar-%d" % os.getpid()
        subprocess.run(["sudo", "-n", _a[0], "--wait"] + _a[1:], capture_output=True, timeout=60)
        _g = subprocess.run(["sudo", "-n", "cat", _out], capture_output=True, text=True).stdout
        check("[9i] …REAL: systemd-run runs it and the shell writes its own ${X} and its pid (it wrote \"|$\")",
              _g.startswith("mine|") and _g[5:].isdigit(), _g)
    else:
        print("  SKIPPED [9i] real run — no `sudo -n` / systemd here")
    m.os, m.subprocess = _Os(False), _Sub()
    del CALLS[:]
    ok = m.run_self_update({"node": {"update_cmd": "true"}}, {"to": "9.9.9"})
    kind, argv, kw = CALLS[-1] if CALLS else (None, [], {})
    check("[9h] no systemd → the wrapper itself, a child of swg-noded in a session of its own, not waited for",
          ok is True and kind == "Popen" and argv[:2] == ["bash", "-c"] and kw.get("start_new_session"), (ok, kind, argv[:3]))
finally:
    m.os, m.shutil, m.subprocess, m.log = _real
    os.environ.pop("SWG_TURN_MIRROR", None)

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANTED:
    _red = [f for f in FAILS if f.startswith("[9")]
    _ok = bool(_red) and len(_red) == len(FAILS)
    print("plant %s: %s" % (PLANTED[0], ("RED as it must be (%d)" % len(_red)) if _ok
                                       else "NOT CAUGHT" if not FAILS else "ALSO red outside [9]: %s" % FAILS))
    sys.exit(0 if _ok else 1)
if FAILS:
    print("FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all checks passed")
