#!/usr/bin/env python3
"""Self-test: a node that reports a shape the panel cannot read is handled per FIELD, not per accident.

A snapshot is remote input and `swg-noded` reconciles ONLY on a 200 — so a field whose shape a reader cannot
handle does not merely lose a chart. It raises inside the sync handler, the node gets a 500, and it never
converges again: its peers freeze where they are and the panel says "offline", which is the one thing that
is not wrong with it. Five long-shipped fields could do this. The realistic trigger is version skew — a node
newer than its panel sending a shape this build does not expect.

⚠️ THE ANSWER IS NOT THE SAME FOR EVERY FIELD, and that is the whole point of this gate:

  TELEMETRY (`inet`, `cat_rate`, `exit_rate`) — a lost sample is a gap in a graph. Cleaned and kept, so the
    node keeps syncing and no reader downstream needs a guard of its own.
  STATE (`interfaces`, `wdtt`, `csqtt`) — these say what the node is RUNNING. Syncing a malformed one as
    empty would read as every peer on that node having vanished; refusing leaves it stale, and `reconcile.js`
    deliberately never counts a stale node's peers as missing. So refusing is right — what was wrong was that
    the refusal was a silent 500. It is a 400 with a reason, recorded on the node and said on its card.

Hermetic. Run: python3 tests/snap_shape_selftest.py (0 = pass).  --perturb makes the sanitiser a no-op and
expects the malformed shapes to sail through.
"""
import importlib.machinery, importlib.util, os, sys

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
_san = P._snap_sanitise
if PERTURB:
    P._snap_sanitise = lambda snap: None          # accepts anything, cleans nothing — how it shipped

print("\n[1] telemetry is CLEANED, and the node keeps syncing")
for field, bad, why in (("inet", "nope", "a string where a rate map goes"),
                        ("cat_rate", [1, 2], "a list"),
                        ("exit_rate", {"d": 5}, "an entry that is not an object")):
    s = {"generated_at": 1, field: bad}
    err = P._snap_sanitise(s)
    check("%s: %s is dropped, not refused" % (field, why),
          err is None and not s.get(field), (err, s.get(field)))
s = {"inet": {"up": "5000", "down": None, "junk": "x"}}
check("a numeric STRING counts — this project's own nodes send them", P._snap_sanitise(s) is None
      and s["inet"].get("up") == 5000.0, s.get("inet"))
# `None` coerces to 0.0 — "reported nothing this pass" IS zero for a rate. Only a value that cannot be read
# as a number at all (`"x"`) is dropped, because guessing a rate from it would be inventing data.
check("a null rate reads as zero", s["inet"].get("down") == 0.0, s["inet"])
check("…and an unreadable one is simply absent", "junk" not in s["inet"], s["inet"])
s = {"exit_rate": {"tun0": {"up": "7", "down": 2}, "bad": 9, "empty": {"up": "x"}}}
P._snap_sanitise(s)
check("a rate map keeps its good entries and drops the rest",
      s["exit_rate"] == {"tun0": {"up": 7.0, "down": 2.0}}, s["exit_rate"])

print("\n[2] malformed STATE is refused, with a reason that names the field")
for field, bad in (("interfaces", {"awg0": "x"}), ("interfaces", "x"),
                   ("wdtt", ["x"]), ("csqtt", 7), ("csqtt", {"c1": 3})):
    err = P._snap_sanitise({"generated_at": 1, field: bad})
    check("%s = %r is refused" % (field, bad), bool(err), err)
    check("…and the reason names the field", bool(err) and field in err, err)

print("\n[3] a well-formed snapshot is left alone")
good = {"generated_at": 1, "interfaces": {"awg0": {"up": True, "peers": []}},
        "wdtt": {"w1": {"fork": "x"}}, "csqtt": [{"iface": "c1"}],
        "inet": {"up": 10, "down": 20}, "exit_rate": {"tun0": {"up": 1, "down": 2}}}
import copy
before = copy.deepcopy(good)
check("no refusal", P._snap_sanitise(good) is None)
check("state is untouched", good["interfaces"] == before["interfaces"] and good["wdtt"] == before["wdtt"]
      and good["csqtt"] == before["csqtt"], good)
check("telemetry survives as numbers", good["inet"] == {"up": 10.0, "down": 20.0}
      and good["exit_rate"] == {"tun0": {"up": 1.0, "down": 2.0}}, (good["inet"], good["exit_rate"]))

print("\n[4] BOTH doors into the snapshot cache run it")
# ⚠️ The readers downstream state this as an invariant instead of re-checking it, so a door that skipped the
# sanitiser would put back exactly the value the other one refuses. The warm-start seed is the easy one to
# forget: those files were written by an EARLIER run, possibly one that stored a shape this build cannot read.
lines = open(PANEL, encoding="utf-8").read().splitlines()
doors = [i for i, l in enumerate(lines)
         if ("node_snaps" in l and "=" in l and l.strip().endswith(("= snap", "= _snap")))]
check("both entry points into node_snaps were found", len(doors) == 2,
      [lines[i].strip()[:60] for i in doors])
near = [i for i in doors if any("_snap_sanitise" in lines[j] for j in range(max(0, i - 14), i + 1))]
check("…and neither seeds the cache without sanitising first", len(near) == len(doors) == 2,
      [lines[i].strip()[:60] for i in doors if i not in near])

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: malformed shapes sailed through" % len(FAILS)) if ok
          else "PERTURB FAILED — the sanitiser was disabled and nothing noticed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
