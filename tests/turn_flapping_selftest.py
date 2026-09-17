#!/usr/bin/env python3
"""Self-test: a crash-looping turn-proxy is reported for AS LONG AS it loops — not for twenty seconds.

`systemctl is-active` answers `active` whenever a looping unit is caught between crashes, so the node's
`running` flag — the only thing the panel had — could call a crash loop healthy, and `_node_issues` never
said a word about it.

Measured in the field 2026-09-16: a proxy whose `-listen` address the box no longer had died with
`panic: bind: cannot assign requested address` and was restarted by systemd **262 times against 272 starts
in 90 minutes**. The panel's node card was green, and the only visible symptom was on the OPERATOR's side
of the world — clients "connected but got no traffic", because every session was cut off when the process
died under it.

⚠️ THE FIRST FIX WAS TUNED TO THE WRONG DISTRIBUTION. It flagged >=3 restarts inside one 20s window — but
the units this node writes back off (`RestartSec=3 RestartSteps=8 RestartMaxDelaySec=300`), so on systemd
>=254 a real loop restarts ~6 times in its first window and then 0,0,0,0,1 — once every five minutes for
as long as it lasts. That check spoke for the first twenty seconds and was silent for the hour after. And
an empty reply from a momentarily busy systemd rebuilt its maps from nothing, so the verdict blinked out.

What this drives, through the REAL `_attach_turn_running` (on a simulated clock) and the REAL `_node_issues`:
  [1] the restart count rides along on the same batched call — one round-trip, not a new poll
  [2] a loop under systemd's BACKOFF is reported on every pass for a whole hour, with a growing duration
  [3] a loop on systemd <254, which ignores the backoff keys (a fixed 3s), is reported from its first pass
  [4] a proxy that crashes now and then is NOT a loop — each crash alone inside its own quiet period
  [5] the operator's own restart ends the episode — systemd's counter cannot be trusted to say so — and so
      does a stop; a loop that survives either is a NEW episode, reported again once it earns one
  [6] the verdict outlives the loop by the quiet period, never less — then it clears
  [7] "I could not look" neither erases the last reading nor invents one, and a stale reading expires
  [8] the verdict is a climb, not an absolute: a box that looped last week reads clean today
  [9] a proxy stopped from the panel is not looping, whatever it did before
  [10] the panel raises ONE issue per proxy, naming the count and how long it has gone on
  [11] live facts stay OUT of the persisted turn record — _attach_turn_running runs after the disk write

Hermetic: host_sh and the clock are stubbed; nothing shells out, no network, no state written.

Run: python3 tests/turn_flapping_selftest.py       (0 = pass)
     Every perturbation arm names the sections it must redden, and the run passes ONLY if exactly those go
     red: a perturbation that reddens some other section, or crashes, has proved nothing about its own.
     --perturb          drops the verdict from the record — RED in [2] [3] [5] [6] [7], the node-side
                        sections that expect one. NOT [10]: that section feeds _node_issues a record
                        carrying `flapping` directly, so it gates the panel's SENTENCE, not the attach.
     --perturb-window   ends an episode at the first pass with no restart (how it shipped) — RED in [2] and
                        [6] only: a fixed-rate loop climbs on every pass, so [3] cannot tell the two apart
     --perturb-abs      counts the first reading's cumulative total as a climb — RED in [8] only
     --perturb-flush    ignores the counter going DOWN — RED in [5] only
     --perturb-forget   a restart issued by this node no longer ends the episode — RED in [5] only
     --perturb-seam     the edit/Restart path stops calling it — RED in [5] only
     --perturb-reread   forgetting leaves the 20s read throttle standing — RED in [5] only
     --perturb-erase    lets a pass that could not look erase the last reading — RED in [7] only
     --perturb-invent   reads an empty answer from systemd as a state — RED in [7] only
"""
import os, re, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

# arm -> (anchor, replacement, the sections that MUST go red and no others)
PLANTS = {
    "--perturb": ('            t["flapping"] = r["ep"]["n"]\n', "", {2, 3, 5, 6, 7}),
    "--perturb-window": ('                elif ep and nowt - ep["last"] >= TURN_FLAP_QUIET:\n',
                         '                elif ep:\n', {2, 6}),
    # ⚠️ A PERTURBATION MUST GIVE A WRONG ANSWER, NOT A TRACEBACK — the lookup stays safe, only the baseline
    # rule is removed.
    "--perturb-abs": ("                    climb = 0                     # a baseline",
                      "                    climb = n                     # a baseline", {8}),
    "--perturb-flush": ("                    ep, climb = None, n           # flushed by a stop",
                        "                    climb = 0                     # flushed by a stop", {5}),
    "--perturb-forget": ("    if r:\n        r[\"ep\"] = None\n", "    if r:\n        pass\n", {5}),
    "--perturb-seam": ("            _turn_loop_forget(svc)                   # a restart was issued, whatever it returned\n",
                       "", {5}),
    "--perturb-reread": ("        r[\"ep\"] = None\n    _TURN_RUN[\"at\"] = 0.0\n", "        r[\"ep\"] = None\n", {5}),
    "--perturb-erase": ("TURN_RUN_TTL = 120\n", "TURN_RUN_TTL = 0\n", {7}),
    "--perturb-invent": ("            if state in _UNIT_STATES:\n", "            if True:\n", {7}),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

nsrc = open(NODED, encoding="utf-8").read()
if MODE:
    cut, new, _ = PLANTS[MODE]
    assert nsrc.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
    nsrc = nsrc.replace(cut, new, 1)

N = types.ModuleType("n")
N.__dict__.update({"__name__": "n", "__file__": NODED})
exec(compile(nsrc.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)

P = types.ModuleType("p")
P.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(open(PANEL, encoding="utf-8").read().split("\nif __name__ ==")[0], "swg-panel-server", "exec"), P.__dict__)

N.TURN_MANAGE_ON = True
SVC = "vk-turn-proxy-WINGS-N-56004"
QUIET, MIN, TTL = N.TURN_FLAP_QUIET, N.TURN_FLAP_MIN, 120   # TTL literal: the -erase arm changes the module's

class Clock:                      # the module's `time`, so every pass reads the simulated second
    t = 1_000_000.0
    def time(self):
        return self.t
CLK = Clock()
N.__dict__["time"] = CLK

class Out:
    def __init__(self, stdout="", rc=0):
        self.stdout = stdout; self.returncode = rc; self.stderr = ""

def fresh():
    N._TURN_RUN["svc"].clear(); N._TURN_RUN["at"] = 0.0

def observe(t, nr=0, state="active", reply=None, rc=0, stopped=False, expire=True):
    """One pass at simulated second `t`, with the 20s throttle expired so it really re-reads (expire=False
    leaves the throttle as the module left it — a snapshot built between two reads).
    `reply` overrides the host's stdout (for the could-not-look cases); rc=126 means host_sh could not reach."""
    CLK.t = 1_000_000.0 + t
    out = "" if rc else (reply if reply is not None else "%s=%s=%s\n" % (SVC, state, nr))
    N.host_sh = lambda cmd, timeout=90: Out(out, rc)
    if expire:
        N._TURN_RUN["at"] = 0.0
    tps = [{"service": SVC, "listen": "10.0.0.1:56004", **({"stopped": True} if stopped else {})}]
    N._attach_turn_running(tps)
    return tps[0]

def restarts_by(t, times):
    return sum(1 for x in times if x <= t)

def backoff_times(start, until):
    """When systemd >=254 restarts a unit that dies at once, under OUR unit's backoff keys."""
    gaps = [3, 5, 9, 17, 30, 53, 95, 169]
    out, t, k = [], start, 0
    while True:
        t += gaps[k] if k < len(gaps) else 300
        if t > until:
            return out
        out.append(t); k += 1

# ── [1] the count rides along on the SAME call ────────────────────────────────────────────────────
print("[1] the restart count comes from the batched call that already runs")
fresh()
rec = observe(0, nr=7)
check("[1] running is still reported", rec.get("running") is True, rec)
check("[1] …and the restart count with it", rec.get("restarts") == 7, rec)

# ── [2] a loop under backoff is reported for as long as it lasts ──────────────────────────────────
print("\n[2] a loop under systemd's backoff is reported for the whole hour, not the first twenty seconds")
fresh()
observe(-20, nr=0)                                    # healthy, and a baseline taken before it breaks
times = backoff_times(0, 3600)
gaps_seen, fors, last = [], [], None
for t in range(20, 3601, 20):
    rec = observe(t, nr=restarts_by(t, times), state="activating")
    if not rec.get("flapping"):
        gaps_seen.append(t)
    else:
        fors.append(rec.get("flapping_for")); last = rec
# the first shape: 6 in the first window, then 0,0,0,0,1 — check the schedule really is that shape, or this
# section is exercising a distribution nobody runs
per_win = [restarts_by(w + 20, times) - restarts_by(w, times) for w in range(0, 120, 20)]
check("[2] the simulated schedule is the one that fooled a 20s window (a burst, then single restarts)",
      per_win[0] >= MIN and max(per_win[1:]) <= 1, per_win)
check("[2] reported on EVERY pass from the first to the last hour of the loop", gaps_seen == [], gaps_seen[:8])
check("[2] …counting every restart systemd made", last and last.get("flapping") == len(times),
      (last or {}).get("flapping"))
check("[2] …with a duration that keeps growing, so an all-night loop reads as one",
      fors == sorted(fors) and fors and fors[-1] >= 3500, fors[-3:])

# ── [3] systemd <254: a fixed 3s restart ──────────────────────────────────────────────────────────
print("\n[3] a loop on systemd <254 (which ignores the backoff keys) is reported from its first pass")
fresh()
observe(-20, nr=0)
rec = observe(20, nr=6)
check("[3] six restarts in the first pass are flagged at once", rec.get("flapping") == 6, rec)
rec = observe(40, nr=12)
check("[3] …and the count keeps climbing with it", rec.get("flapping") == 12, rec)

# ── [4] a crash now and then is not a loop ────────────────────────────────────────────────────────
print("\n[4] a proxy that crashes now and then is not crash-looping")
fresh()
observe(0, nr=0)
daily = [86400 * d + 1000 for d in range(4)]
flagged = [t for t in range(300, 86400 * 4, 300) if observe(t, nr=restarts_by(t, daily)).get("flapping")]
check("[4] one crash a day, for four days, is never reported", flagged == [], flagged[:5])
fresh()
observe(0, nr=0)
spread = [1000, 1000 + QUIET + 60, 1000 + 2 * (QUIET + 60)]      # each crash alone in its own quiet period
flagged = [t for t in range(20, 5000, 20) if observe(t, nr=restarts_by(t, spread)).get("flapping")]
check("[4] three crashes further apart than the quiet period are never reported", flagged == [], flagged[:5])
fresh()
observe(0, nr=0)
flagged = [t for t in range(20, 3000, 20) if observe(t, nr=restarts_by(t, [500, 800])).get("flapping")]
check("[4] two crashes close together are below the threshold", flagged == [], flagged[:5])

# ── [5] the operator's restart, and a stop, end the episode ───────────────────────────────────────
print("\n[5] the operator's own restart ends the episode; a loop that survives it is a new one")
fresh()
observe(-20, nr=0)
observe(20, nr=20)
rec = observe(40, nr=26)
check("[5] setup: a loop is being reported", rec.get("flapping") == 26, rec)
# MEASURED on systemd 255: a restart issued while the unit waits out its backoff leaves NRestarts where it was,
# so the counter says nothing here — the node has to remember that it was the one that restarted it.
N._turn_loop_forget(SVC)
rec = observe(60, nr=26)
check("[5] a restart this node issued ends the verdict, though systemd's counter did not move",
      "flapping" not in rec, rec)
observe(80, nr=27); rec = observe(100, nr=28)
check("[5] …a loop that survives it is not re-reported on its first restarts", "flapping" not in rec, rec)
rec = observe(120, nr=29)
check("[5] …and is reported again once it earns an episode of its own, counted from the restart",
      rec.get("flapping") == MIN and rec.get("flapping_for") == 40, rec)
# MEASURED on swgt: the verdict cleared at once, but `running` kept the reading taken during the restart wait
# for the rest of the 20s throttle, so a proxy just repaired read "not running". Forgetting must re-read.
fresh()
observe(-20, nr=0)
rec = observe(20, nr=6, state="activating")            # a loop, caught in its restart wait
check("[5] setup: looping and not running", rec.get("flapping") == 6 and rec.get("running") is False, rec)
rec = observe(25, nr=6, state="active", expire=False)
# ⚠️ "did not pick up the new state", NOT "still reads False": whether an unread snapshot carries the old
# reading or drops it is TURN_RUN_TTL's business ([7]), and this control must not depend on that answer.
check("[5] control: inside the throttle a snapshot does not re-read (so the next check can discriminate)",
      rec.get("running") is not True, rec)
N._turn_loop_forget(SVC)                               # the operator's fix was just applied and restarted
rec = observe(30, nr=6, state="active", expire=False)
check("[5] the snapshot right after this node's restart reads systemd again — running, not a stale 'not running'",
      rec.get("running") is True and "flapping" not in rec, rec)
fresh()
observe(-20, nr=0); observe(20, nr=20); observe(40, nr=26)
rec = observe(60, nr=0)                                # a stop (or a restart while up): systemd flushed it
check("[5] a counter that went DOWN ends the verdict on that pass", "flapping" not in rec, rec)
rec = observe(80, nr=5)
check("[5] …and a loop after it is counted from the flush, not from before", rec.get("flapping") == 5, rec)
check("[5] …with its duration counted from then too", rec.get("flapping_for") == 0, rec)
fresh()
observe(-20, nr=0); observe(20, nr=20); observe(40, nr=26)
rec = observe(60, nr=2)
check("[5] two restarts since a flush are not yet a loop", "flapping" not in rec, rec)
# ⚠️ THE SEAM. The helper is only as good as the paths that call it: an edit and Restart go through one
# restart line, a reinstall through its own job. Both must forget, or the fix exists and never runs.
_at = nsrc.find("def apply_turn(")
_body = nsrc[_at:nsrc.find("\ndef ", _at + 10)]
_i = _body.find("if _unit_is_envform(unit):")
_manage = _body[_i:_body.find("if w.returncode != 0:", _i)] if _i >= 0 else ""
_j = _body.find("w = host_sh(cmd, timeout=340)")
_reinst = _body[_j:_body.find("return _turn_verify(svc)", _j)] if _j >= 0 else ""
check("[5] the edit / key-rotation / Restart path forgets the episode after its restart",
      "_turn_loop_forget(svc)" in _manage, _manage[:160])
check("[5] …and so does the reinstall job", "_turn_loop_forget(svc)" in _reinst, _reinst[:160])

# ── [6] the verdict outlives the loop by the quiet period — and no less ───────────────────────────
print("\n[6] the verdict clears after a genuinely quiet period, never before")
fresh()
observe(-20, nr=0)
observe(20, nr=6)                                      # the last climb this episode will ever see
early = [t for t in range(40, 20 + QUIET, 20) if not observe(t, nr=6).get("flapping")]
check("[6] still reported throughout the quiet period after the last restart", early == [], early[:5])
rec = observe(20 + QUIET + 20, nr=6)
check("[6] …and cleared once the quiet period has passed", "flapping" not in rec, rec)
check("[6] …while the count itself is still reported", rec.get("restarts") == 6, rec)

# ── [7] "I could not look" is not an answer ───────────────────────────────────────────────────────
print("\n[7] a pass that could not look keeps the last reading — for a while — and never invents one")
fresh()
rec = observe(0, nr=0, rc=126)
check("[7] no reading ever: no running flag is invented", "running" not in rec, rec)
check("[7] …no restart count", "restarts" not in rec, rec)
check("[7] …and no verdict", "flapping" not in rec, rec)
observe(20, nr=0)
good = observe(40, nr=8)
check("[7] setup: a loop is being reported", good.get("flapping") == 8 and good.get("running") is True, good)
for label, kw in (("host unreachable (rc=126, empty stdout)", {"rc": 126}),
                  ("systemd too busy to answer for the unit (empty fields)", {"reply": "%s==\n" % SVC}),
                  ("the unit's line missing from the reply", {"reply": "some-other.service=active=0\n"})):
    rec = observe(60, **kw)
    check("[7] %s keeps `running`" % label, rec.get("running") is True, rec)
    check("[7] …keeps the restart count", rec.get("restarts") == 8, rec)
    check("[7] …and keeps the verdict", rec.get("flapping") == 8, rec)
rec = observe(40 + TTL + 20, rc=126)
check("[7] a reading older than its TTL is no longer reported as running", "running" not in rec, rec)
check("[7] …nor as a count", "restarts" not in rec, rec)
check("[7] …nor as a verdict", "flapping" not in rec, rec)
rec = observe(40 + TTL + 40, nr=14)
check("[7] reads resume: restarts made while nobody could look still count", rec.get("flapping") == 14, rec)

# ── [8] the verdict is a CLIMB, not an absolute ───────────────────────────────────────────────────
print("\n[8] a box that looped last week reads clean today")
fresh()
rec = observe(0, nr=900)
# ⚠️ ABSENCE of a verdict, not a falsy one: `not rec.get(...)` would accept flapping=0.
check("[8] the first reading after a noded start is a baseline, not a verdict", "flapping" not in rec, rec)
rec = observe(20, nr=900)
check("[8] a large but UNCHANGED count yields no verdict at all", "flapping" not in rec, rec)
check("[8] …though the count itself is still reported", rec.get("restarts") == 900, rec)

# ── [9] stopped is not looping ────────────────────────────────────────────────────────────────────
print("\n[9] a proxy stopped from the panel is not crash-looping")
fresh()
observe(-20, nr=0); observe(20, nr=12)
rec = observe(40, nr=12, state="inactive", stopped=True)
check("[9] a stopped proxy carries no verdict", "flapping" not in rec, rec)
check("[9] …and is honestly not running", rec.get("running") is False, rec)
rec = observe(60, nr=12, state="inactive")             # a record that no longer says stopped
check("[9] …and stopping ENDED the episode rather than hiding it", "flapping" not in rec, rec)

# ── [10] the panel says so, once, with the numbers ────────────────────────────────────────────────
print("\n[10] the operator is told — one line per proxy, with the count and how long it has gone on")
def issues_for(tp):
    snap = {"turn_proxies": [tp], "node_ips": [], "node_ifaces": []}
    return [i for i in P._node_issues({}, snap)]
iss = issues_for({"service": SVC, "running": True, "flapping": 262, "flapping_for": 5400})
msgs = [str(i.get("error") or "") for i in iss]
check("[10] a crash-looping proxy raises an issue even though it reports running",
      any("crash-looping" in mm for mm in msgs), msgs)
check("[10] …naming the service, the count and the duration in minutes",
      any(SVC in mm and "262" in mm and "90 min" in mm for mm in msgs), msgs)
check("[10] …exactly once", len(msgs) == 1, msgs)
check("[10] …as a translatable sentence with no number baked into its key",
      bool(iss) and not re.search(r"\d", re.sub(r"\{v\d\}", "", iss[0].get("error_key") or "0")), iss[:1])
msgs = [str(i.get("error") or "") for i in issues_for({"service": SVC, "running": False, "flapping": 9, "flapping_for": 30})]
check("[10] a loop in its backoff (reads not running) is still named as a loop, rounded UP to a minute",
      len(msgs) == 1 and "crash-looping" in msgs[0] and "1 min" in msgs[0], msgs)
msgs = [str(i.get("error") or "") for i in issues_for({"service": SVC, "running": True, "flapping": 6})]
check("[10] an older node that sends no duration still gets a sentence", len(msgs) == 1 and "crash-looping" in msgs[0], msgs)
msgs = [str(i.get("error") or "") for i in issues_for({"service": SVC, "running": False})]
check("[10] a plainly stopped proxy keeps its original sentence",
      msgs and "not running" in msgs[0] and "crash-looping" not in msgs[0], msgs)
msgs = [str(i.get("error") or "") for i in issues_for({"service": SVC, "running": True})]
check("[10] a healthy proxy raises nothing", msgs == [], msgs)

# ── [11] live facts stay out of the persisted record ──────────────────────────────────────────────
print("\n[11] the crash counter is a live fact, not config")
i_dump = nsrc.find("json.dump({\"turn_proxies\": tp}")
i_attach = nsrc.find("_attach_turn_running(tp)")
check("[11] the record is written to disk BEFORE the live flags are attached",
      0 < i_dump < i_attach, (i_dump, i_attach))

red = {int(m.group(1)) for m in (re.match(r"\[(\d+)\]", f) for f in FAILS) if m}
if MODE:
    want = PLANTS[MODE][2]
    if red == want:
        print("\nperturbed (%s): CAUGHT in exactly %s (%d red)" % (MODE, sorted(want), len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): red in %s, expected exactly %s — this arm does not prove what it claims"
          % (MODE, sorted(red), sorted(want)))
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
