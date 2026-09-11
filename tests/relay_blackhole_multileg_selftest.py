#!/usr/bin/env python3
"""Self-test: with two relayed legs, a leg that serves nobody is still caught.

⚠️ THIS GATE EXISTS BECAUSE THE PER-LEG CHANGE CAN SILENTLY UNDO 233d168.

That commit fixed a live defect: a relay whose status socket answers, whose `loops` counter turns and whose
CPU is idle looks perfectly healthy while accepting NOTHING — and the divert stays armed over it, so every
client TCP connection is swallowed. Measured on a production node: `accepted=0` for three hours and
forty-five minutes with the divert armed the whole time, and the panel green. The fix compares packets the
tproxy rule TOOK against connections the relay ACCEPTED, and disarms when one moves without the other.

That comparison was written when a node relayed at most one leg, so it summed the whole nft table. Under a
smart cascade a node relays several legs at once, and a total is then judging every leg by every other leg's
traffic.

⚠️ THE DIRECTION OF THAT BUG IS NOT THE OBVIOUS ONE, and this gate's first draft asserted it backwards. A
total does NOT hide a starved leg — that leg's accept counter is per-instance and still flat, so it strikes
either way. What a total does is the reverse and worse: it makes a leg that is correctly IDLE look like it
is swallowing traffic, because a busy neighbour's packets inflate the number it is judged by. The watchdog
then pulls a divert that was working and drops every live connection on it, on a leg where nothing was
wrong. §2b is that case, and it is the only check here that a summed counter fails — which is exactly why
the perturbation is run rather than assumed.

The divert rules therefore carry a per-instance `comment` and `_relay_diverted()` returns a mapping. The two
have to change together; this gate is what makes that true.

Run: python3 tests/relay_blackhole_multileg_selftest.py (0 = pass)
     --perturb  sums the table again, the way it was written for one leg, and expects RED.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    # the one-leg shape: every instance reads the SAME number, the sum over the table
    anchor = '    dv = None if _all is None else int(_all.get(iface, 0))'
    assert anchor in src, "perturbation anchor missing — this run would FALSE-PASS"
    src = src.replace(anchor, '    dv = None if _all is None else int(sum(_all.values()))', 1)

path = os.path.join(ROOT, "__perturb_noded.py") if PERTURB else NODED
if PERTURB:
    open(path, "w").write(src)
l = importlib.machinery.SourceFileLoader("noded_bh", path)
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_bh", l))
try:
    l.exec_module(m)
except SystemExit:
    pass
finally:
    if PERTURB:
        os.unlink(path)

# ── a fleet-shaped fixture: two legs off ONE interface, which is what smart cascade produces ────────────
BUSY, STARVED = "awg2.busypeer", "awg2.starvedpeer"
DIVERTED = {BUSY: 0, STARVED: 0}
ACCEPTED = {BUSY: 0, STARVED: 0}

m._relay_diverted = lambda: dict(DIVERTED)
m._relay_cpu = lambda iid, pid, now: 1.0
_loops = {"n": 0}
def _status(iid, timeout=2.0):
    return {"loops": _loops["n"], "accepted": ACCEPTED[iid], "refused_self": 0, "pid": 1}
m._relay_status = _status

def pump(busy_div, busy_acc, starved_div, starved_acc, passes=3):
    """Run `passes` watchdog passes, moving the counters each time. Returns the last verdict per leg."""
    out = {}
    for _ in range(passes):
        _loops["n"] += 10                       # the loop is turning: a liveness check alone sees health
        DIVERTED[BUSY] += busy_div; ACCEPTED[BUSY] += busy_acc
        DIVERTED[STARVED] += starved_div; ACCEPTED[STARVED] += starved_acc
        for iid in (BUSY, STARVED):
            out[iid] = m._relay_probe(iid, 1000.0 + _loops["n"])
    return out

print("[1] ⚠️ the starved leg is caught while the busy one keeps working")
# busy: 50 diverted, 50 accepted. starved: 50 diverted, 0 accepted. A TOTAL would read 100 diverted and 50
# accepted and call both of them fine — which is the bug this file exists for.
v = pump(50, 50, 50, 0)
check("the busy leg stays healthy", v[BUSY][0] is True, v[BUSY][1])
check("⚠️ the starved leg is NOT healthy", v[STARVED][0] is False, "it was called healthy")
check("…and says it is a blackhole", "blackhole" in (v[STARVED][1] or ""), v[STARVED][1])

print("\n[2] …and the reason is the two counters, not a guess")
m._RELAY.clear()
v = pump(0, 0, 200, 0)                          # only the starved leg sees traffic at all
check("a leg diverting with no accepts at all is caught", v[STARVED][0] is False, v[STARVED][1])
m._RELAY.clear()
v = pump(0, 0, 0, 0)                            # nothing diverted anywhere: quiet, not broken
check("a quiet leg is NOT called a blackhole", v[STARVED][0] is True, v[STARVED][1])

print("\n[2b] ⚠️⚠️ AN IDLE LEG BESIDE A BUSY ONE — the check the whole file turns on")
# This is the case a summed counter gets WRONG, and working it out on paper is how the direction of the bug
# was found. A total does NOT hide a starved leg: that leg's accepts are per-instance and still flat, so it
# strikes either way. What a total does is the opposite and worse — it makes a leg that is correctly idle
# look like it is swallowing traffic, because ANOTHER leg's packets inflate the number it is judged by. The
# watchdog then pulls a working divert, dropping every live connection on a leg that had nothing wrong with
# it. Loss on an idle leg is also exactly what nobody is watching for.
m._RELAY.clear()
v = pump(100, 100, 0, 0, passes=4)              # BUSY is healthy and loud; STARVED is simply idle
check("the busy leg is healthy", v[BUSY][0] is True, v[BUSY][1])
check("⚠️ …and the IDLE leg is NOT disarmed by its neighbour's traffic", v[STARVED][0] is True,
      "%r — a summed counter judges this leg by another leg's packets" % (v[STARVED][1],))

print("\n[3] one slow pass is not a verdict — the exact sequence, because it is off-by-one twice")
# From a cold start the verdict lands on the THIRD pass, and both delays are deliberate:
#   pass 1  no previous sample at all -> "waiting for a second sample" (never arm on one observation)
#   pass 2  first sample where diverted moved and accepted did not -> one strike, still healthy
#   pass 3  second consecutive strike -> blackhole
# A gate that asserted "the second pass disarms" would be asserting a bug: a single SYN arriving between
# two probes moves the divert counter without an accept, and pulling a working divert for that would
# interrupt every live connection on the leg.
m._RELAY.clear()
v = pump(0, 0, 40, 0, passes=1)
check("pass 1 refuses to judge on one observation", v[STARVED][0] is False
      and "second sample" in (v[STARVED][1] or ""), v[STARVED][1])
v = pump(0, 0, 40, 0, passes=1)
check("pass 2 is one strike, not a verdict", v[STARVED][0] is True, v[STARVED][1])
v = pump(0, 0, 40, 0, passes=1)
check("⚠️ pass 3 disarms", v[STARVED][0] is False and "blackhole" in (v[STARVED][1] or ""), v[STARVED][1])

print("\n[4] …and a leg that recovers is armed again")
m._RELAY.clear()
pump(0, 0, 40, 0, passes=3)
v = pump(0, 0, 40, 40, passes=2)                # accepts start moving with the diverts
check("recovery clears the strike run", v[STARVED][0] is True, v[STARVED][1])

print("\n[5] a table that cannot be read is not 'nothing diverted'")
m._RELAY.clear()
pump(10, 10, 10, 10, passes=2)                  # healthy baseline
m._relay_diverted = lambda: None
v = pump(0, 0, 0, 0, passes=2)
check("⚠️ an unreadable table does not fabricate a pass or a failure",
      v[STARVED][0] is True and "blackhole" not in (v[STARVED][1] or ""),
      "%r — None must not be read as 0" % (v[STARVED][1],))

bad = len(FAILS)
if PERTURB:
    print("\n--perturb (the counter summed over the table again): %d check(s) RED" % bad)
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
