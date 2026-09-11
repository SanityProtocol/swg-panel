#!/usr/bin/env python3
"""Self-test: a routing target that falls off the 7000-band is REPORTED, not dropped in silence.

One node can route to `SWG_RT_BAND` destinations at once — peer nodes and exit devices share the ceiling on
purpose, so nobody can spend it on one kind to sneak past it on the other. Past that, `cascade_plan` skips
the target with `continue` and it gets no plan entry.

For a forward that is a degrade the operator eventually sees in the traffic. For an exit carrying a
KILL-SWITCH it is the switch failing OPEN — they asked for that traffic to STOP and it goes out directly
instead — and until now nothing anywhere said so. That is the one failure this whole feature exists to
prevent, so the silence was the defect, not the skipping.

Two halves, and both are load-bearing: `cascade_plan` must RECORD which targets fell off, and `_node_issues`
must turn that into a sentence naming them — with a different sentence when a kill-switch is among them,
because "your traffic is going direct" and "the switch you turned on is holding nothing" are not the same
news. Checked here against the real allocator with 105 real targets, not a hand-set `_capped`.

Hermetic: no network, no state dir, no server. Only `cascade_plan` and `_node_issues` are called.

Run: python3 tests/exit_band_cap_selftest.py (0 = pass).  --perturb removes the recording — the skipping
still works, so the plan is still "correct" and only the operator is left uninformed, which is exactly how
this shipped. Expects the checks to FAIL.
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

_src = open(PANEL, encoding="utf-8").read()
if PERTURB:
    # Back out the RECORDING only, leaving the skipping exactly as it is — the shape this shipped in: a plan
    # that is right about the datapath and says nothing about what it left out.
    _cut = '''            _over = _srt[SWG_RT_MAX - SWG_RT_BASE + 1:]
            if _over:
                slot(nid)["_capped"] = _over'''
    assert _src.count(_cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _src = _src.replace(_cut, "            pass", 1)
    PANEL = os.path.join(HERE, ".perturbed-cap.py")
    open(PANEL, "w", encoding="utf-8").write(_src)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if PERTURB:
    os.unlink(PANEL)

BAND = P.SWG_RT_BAND
OVER = 5                                       # how many targets to push past the ceiling
N = BAND + OVER


def fixture(ks_on=(), over=OVER):
    """One node with BAND+`over` interfaces, each on its own exit — so that many distinct targets, `over` of
    them past the band. Ids are zero-padded because the allocator sorts: that makes exactly which ones fall
    off a fact this test can state, rather than something it has to discover."""
    exits, ifaces, snaps_if = [], {}, {}
    for i in range(BAND + over):
        xid = "x%03d" % i
        exits.append({"id": xid, "label": "exit " + xid, "device": "tun" + xid,
                      "enabled": True, "killswitch": xid in ks_on, "producer": "adopted"})
        ifaces["if%03d" % i] = {"egress_mode": "exit", "exit_id": xid}
        snaps_if["if%03d" % i] = {"meta": {"subnet": "10.%d.%d.0/24" % (i // 256, i % 256)}}
    return ({"n1": {"name": "n1", "links": {}, "exits": exits, "ifaces": ifaces}},
            {"n1": {"interfaces": snaps_if}})


kept = ["exit:x%03d" % i for i in range(BAND)]
lost = ["exit:x%03d" % i for i in range(BAND, N)]

print("\n[1] the allocator — %d targets into a band of %d" % (N, BAND))
nodes, snaps = fixture()
plan = P.cascade_plan(nodes, snaps).get("n1", {})
cap = plan.get("_capped") or []
check("the overflow is recorded", bool(cap), "nothing recorded — the skip is silent")
check("…naming exactly the targets past the ceiling", sorted(cap) == lost, sorted(cap)[:8])
check("…and none of the ones that fit", not (set(cap) & set(kept)))
devs = {e["dev"] for e in (plan.get("devexit") or [])}
check("a capped exit still gets NO plan entry (the skip is unchanged)",
      not (devs & {"tun" + x[5:] for x in lost}), sorted(devs & {"tun" + x[5:] for x in lost}))
check("…while every exit that fit does route", len(devs) == BAND, len(devs))
tbl = [e["table"] for e in (plan.get("devexit") or [])]
check("every table issued is inside the band", tbl and min(tbl) >= P.SWG_RT_BASE and max(tbl) <= P.SWG_RT_MAX,
      (min(tbl), max(tbl)) if tbl else None)

print("\n[2] a node under the ceiling says nothing")
_n2, _s2 = fixture()
_n2["n1"]["exits"] = _n2["n1"]["exits"][:BAND]
_n2["n1"]["ifaces"] = {k: v for k, v in list(_n2["n1"]["ifaces"].items())[:BAND]}
_p2 = P.cascade_plan(_n2, _s2).get("n1", {})
check("no overflow, no report", not (_p2.get("_capped") or []), _p2.get("_capped"))

print("\n[3] the sentence the operator reads")
def issues(ks_on=()):
    nd, sn = fixture(ks_on)
    pl = P.cascade_plan(nd, sn).get("n1", {})
    return [i.get("error") or "" for i in P._node_issues(nd["n1"], sn["n1"], "", pl.get("_capped") or ())]

LAST = "exit x%03d" % (N - 1)                    # x104 — past the ceiling
_plain = [t for t in issues() if "route to" in t]
check("a capped exit is reported at all", len(_plain) == 1, _plain)
check("…naming the exit by the operator's own label", _plain and LAST in _plain[0], _plain)
check("…and not claiming a kill-switch that is off", _plain and "kill-switch" not in _plain[0], _plain)

# ⚠️ THE KILL-SWITCH SENTENCE MUST BE TRUE OF EVERY EXIT IT NAMES. A first version listed all five capped
# targets and then said "its kill-switch is holding nothing" — a claim about ONE of them applied to all of
# them, in the one message on this screen that has to be exact. So: two sentences, and neither may borrow
# the other's subjects.
_two = issues(ks_on=("x%03d" % (N - 1),))
_ks = [t for t in _two if "kill-switch" in t]
_oth = [t for t in _two if "route to" in t and "kill-switch" not in t]
check("a capped KILL-SWITCH exit gets its own sentence", len(_ks) == 1, _two)
check("…naming ONLY the exit that carries one", _ks and LAST in _ks[0]
      and not any(("exit x%03d" % i) in _ks[0] for i in range(BAND, N - 1)), _ks)
check("…which says the switch is holding nothing", _ks and "holding nothing" in _ks[0], _ks)
check("…and that the traffic is going out anyway", _ks and "going out" in _ks[0], _ks)
check("the OTHER capped exits still get their own line", len(_oth) == 1, _oth)
check("…and that line does NOT borrow the kill-switch exit", _oth and LAST not in _oth[0], _oth)

# A kill-switch on an exit that FIT must not raise it: the alarm is about the switch that lost its slot.
_fit = issues(ks_on=("x000",))
check("a kill-switch on an exit that fit does not raise the alarm",
      len(_fit) == 1 and "kill-switch" not in _fit[0], _fit)

# …and the list is BOUNDED — checked with TWENTY over the ceiling, not the five above, or "names at most a
# handful" is a check that cannot fail. A node can be over by ninety and a message naming all ninety is one
# nobody reads; but silent truncation is worse, so the overflow has to be COUNTED in the sentence.
_nd, _sn = fixture(over=20)
_many = [t.get("error") or "" for t in P._node_issues(_nd["n1"], _sn["n1"], "",
         P.cascade_plan(_nd, _sn).get("n1", {}).get("_capped") or ())]
_many = [t for t in _many if "route to" in t]
check("20 over the ceiling still produces one line", len(_many) == 1, _many)
check("…naming at most a handful of them", _many and _many[0].count("exit x") <= 5, _many)
check("…and SAYING how many it did not name", _many and "(+15)" in _many[0], _many)

print("\n[4] it is a report, not a plan key")
check("`_capped` is underscored, so the wire gate cannot demand the node carry it",
      all(k.startswith("_") or k in ("forward", "smart", "exit", "devexit", "allowed", "domains", "cidrs",
                                     "patterns", "asns") for k in plan), sorted(plan))
check("…and it is not in the cascade payload", '"cascade": {"forward"' in _src and "_capped" not in
      _src.split('"cascade": {')[1].split("},")[0])

# ⚠️ THE SEAM. Everything above proves both ENDS: the plan records the overflow, and `_node_issues` turns a
# list into the sentence. Neither notices if nothing carries the list from one to the other — which is how
# `devexit` shipped computed, consumable and unreachable through three review passes, because every gate
# handed each end a fixture. The plan is built on the sync path (too expensive to rebuild per /api/state),
# parked on `Handler.deps`, and read where the node cards are assembled; all three have to be there.
import ast, re
_t = ast.parse(_src)
_writes = [n for n in ast.walk(_t) if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                   and t.slice.value == "cas_capped" for t in n.targets)]
check("the sync path parks the overflow where the state builder can reach it", len(_writes) == 1, len(_writes))
check("…filled from the plan it just built, not from a literal",
      _writes and "_capped" in ast.dump(_writes[0].value), ast.dump(_writes[0].value)[:90] if _writes else "")
_calls = [n for n in ast.walk(_t) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_node_issues"]
check("the node cards are built by calling _node_issues", len(_calls) == 1, len(_calls))
check("…and it is HANDED the overflow, not left to default to empty",
      _calls and len(_calls[0].args) >= 4 and "cas_capped" in ast.dump(_calls[0].args[3]),
      ast.dump(_calls[0].args[3])[:100] if (_calls and len(_calls[0].args) >= 4) else "called with %d args"
      % (len(_calls[0].args) if _calls else 0))

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the plan still routes correctly and tells the operator "
           "nothing" % len(FAILS)) if ok else
          "PERTURB FAILED — the recording was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
