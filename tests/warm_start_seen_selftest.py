#!/usr/bin/env python3
"""Self-test: a warm start never claims to have heard from a node more recently than the evidence allows.

When the panel process starts it seeds each node's last-known snapshot from the mirrored stats files, so the
console shows the fleet immediately instead of "awaiting enroll" until the next sync. It must also seed WHEN
that sync arrived, because that is what the whole console reads liveness from (`node_seen` → `/api/state`
`last_seen` → `reconcile.js`), and `blocked` on a node's page un-greys every action for a node that reads live.

⚠️ THIS VALUE CAN OUTLIVE THE BOOT. `node_seen` is only ever rewritten by a real sync, so for a node that never
syncs again the seed is permanent. Seeding the mirror file's mtime alone is therefore not safe: a state dir
restored from a backup, moved between boxes, or copied without `-p`/`-a` gives every file a fresh mtime, and a
fleet of long-dead nodes would read "reporting" for as long as the panel ran — offering Delete, Rotate and
Rebuild on boxes nobody has heard from in weeks. Seeding the snapshot's own `generated_at` alone is not safe
either: that is the NODE's clock, which is exactly the reading the 2026-09-24 clock fix stopped trusting, and a
node whose clock runs fast would read live for ever the same way.

So the seed is the OLDEST usable reading, capped at now. Each rule below is silent when broken — nothing logs,
nothing fails; a dead server simply looks alive on the fleet page.

Hermetic. Run: python3 tests/warm_start_seen_selftest.py           (0 = pass)
               python3 tests/warm_start_seen_selftest.py --perturb  restores the mtime-only seed; exits 0 only
                                                                    if a check went red.
"""
import importlib.machinery, importlib.util, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

seed = P._warm_seen
if PERTURB:
    seed = lambda mtime, snap, now=None: int(mtime or 0) or int(now if now is not None else time.time())

NOW = 1790000000
OFFLINE = P.NODE_OFFLINE
# The predicate the panel itself applies to `node_seen` everywhere (nodes_view, the webhook watcher, the
# rebuild plan). Asserting THROUGH it is the point: a seed is only wrong because of what it makes the UI say.
def reads_live(s, now=NOW):
    return s is not None and (now - s) <= OFFLINE

print("\n[1] a fresh mtime cannot resurrect a dead node")
# The restored-backup shape: every mirror file written seconds ago, holding a snapshot from a week back.
week = NOW - 7 * 86400
s = seed(NOW - 2, {"generated_at": week}, NOW)
check("a week-old snapshot in a file touched two seconds ago seeds the week-old reading", s == week, s)
check("…so the node reads offline, and its page stays greyed out", not reads_live(s), s)

print("\n[2] a node's own clock cannot claim the future either")
s = seed(NOW - 600, {"generated_at": NOW + 3600}, NOW)
check("a snapshot stamped an hour ahead does not beat the file it came in", s == NOW - 600, s)
check("…and that reading is old enough to read offline", not reads_live(s), s)
s = seed(NOW + 86400, {"generated_at": NOW + 86400}, NOW)
check("a mirror stamped a day ahead (a clock step, a copy from a fast box) is capped at now", s == NOW, s)

print("\n[3] a slow node clock is taken at its word, because it is the older evidence")
s = seed(NOW, {"generated_at": NOW - 300}, NOW)
check("five minutes behind → the seed is the node's reading, not the file's", s == NOW - 300, s)
check("…which reads offline until the next sync corrects it (~node_interval)", not reads_live(s), s)

print("\n[4] the reason warm start exists still holds")
# A snapshot that arrived moments ago must NOT read stale, or a restart blanks a healthy fleet for a pass.
s = seed(NOW - 3, {"generated_at": NOW - 3}, NOW)
check("a node that synced three seconds before the restart reads live", reads_live(s) and s == NOW - 3, s)
for mt, snap in ((0, {}), (None, None), (0, {"generated_at": 0}), (0, {"generated_at": "x"})):
    s = seed(mt, snap, NOW)
    check("no usable reading (%r, %r) → now, so the last-known state still shows" % (mt, snap),
          s == NOW and reads_live(s), s)

print("\n[5] the boot path cannot bypass it")
lines = open(PANEL, encoding="utf-8").read().splitlines()
seeds = [l.strip() for l in lines if 'node_seen"][' in l and "=" in l and "==" not in l]
check("the warm start's only seed of node_seen goes through _warm_seen",
      len(seeds) == 1 and "_warm_seen(" in seeds[0], seeds)
# …and the live path must NOT: a real sync stamps arrival directly, which is the reading everything else trusts.
live = [l.strip() for l in lines if 'setdefault("node_seen", {})[nid]' in l]
check("a real sync still stamps the arrival time itself", len(live) == 1 and "int(time.time())" in live[0], live)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the mtime-only seed is back" % len(FAILS)) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
