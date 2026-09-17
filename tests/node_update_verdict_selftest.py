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

Run: python3 tests/node_update_verdict_selftest.py       (0 = pass)
     --perturb   restores the DEVNULL behaviour (the wrapper is bypassed, the command run bare) and expects
                 RED on every verdict check — nothing is written, which is exactly the old silence.
"""
import importlib.machinery, importlib.util, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

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

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all checks passed")
