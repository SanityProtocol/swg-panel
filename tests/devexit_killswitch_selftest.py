#!/usr/bin/env python3
"""Self-test for the DEVICE-EXIT KILL-SWITCH (decision 1) and EXIT HEALTH (decision 2) — plan §5.2.

§5.2 is the whole reason this file exists: **"disabled" and "failed" look IDENTICAL at the datapath.**
Both are "no exit route". An implementation that only asks "does the route work?" degrades in both cases,
and the kill-switch is then UNREACHABLE — it can never fire, because nothing ever tells it the difference.

So the split is INTENT vs FACT, and each is answered by the only reader that can:

  panel   a disabled exit, a deleted one, or one whose device is refused by role produces NO devexit entry
          (cascade_plan — covered by tests/devexit_lowering_selftest.py). An entry therefore MEANS
          "this exit should be carrying traffic right now".
  node    is the device actually there. `_dev_link_state` — and only the node can say, its own sysfs being
          the only source that carries wg devices at all.

The kill-switch is a ROUTE, not a re-check, and that is measured rather than preferred (netns, 2026-09-08):

    ip route replace default dev ex0 table 7000          # metric 0
    ip route replace prohibit default metric 4096 table 7000
    → device up:      `ip route get 203.0.113.9 from 10.9.9.5 iif up0` → dev ex0 table 7000   (backstop inert)
    → `ip link del ex0` → the KERNEL purges the dev route → same lookup → Permission denied    (fail closed)
    → control, empty table 7000 instead → the lookup falls through to `main` and egresses dev wan0

That last line is the leak this feature exists to close, and it is why an empty table is not a kill-switch:
a rule whose table has no matching route does not stop, it CONTINUES to the next rule.

Hermetic: no iptables, no ip, no network — `run()` is stubbed and the argv is inspected. `_dev_link_state`
is exercised for real against this box's own sysfs, where `lo` is the one device every host has.

Run: python3 tests/devexit_killswitch_selftest.py (0 = pass)
     --perturb  builds the naive implementation — `_dev_link_state` always answers "up", i.e. "don't
                distinguish, install the route and let it fail" — and expects RED on BOTH halves, because
                decision 1 and decision 2 are one bargain and neither survives alone.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
# A SECOND perturbation, for the wrong turn §5.2 actively invites: "the node must distinguish intent from
# failure" reads like an instruction to send the node BOTH and let it decide. Do that and a disabled exit
# arrives at the node looking exactly like a failed one — the kill-switch fires on an exit the operator
# turned OFF, and decision 3 ("disabling degrades, never rewrites") is the thing that becomes unreachable.
# Applied to the panel's SOURCE, because the branch it removes has no seam to monkey-patch.
INTENT = "--perturb-intent" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod

if INTENT:
    _src = open(PANEL, encoding="utf-8").read()
    # ⚠️ ANCHORED ON THE EXPRESSION, NOT ON ITS INDENTATION. This plant carried the leading spaces, and
    # when `resolve_exit` was de-indented the anchor stopped matching: from then on the assert fired and
    # this perturbation never ran again. It fails loudly rather than silently, which is the only reason it
    # was ever noticed — but a gate that has to be rediscovered is a gate that was not held
    # ([[refactor-breaks-gate-anchors]]). Matching the code and re-using whatever indentation it is found
    # with means moving the function no longer disarms it.
    import re as _re
    _m = _re.search(r'^([ \t]*)if not _x or _x\.get\("enabled"\) is False:$', _src, _re.M)
    assert _m, "perturbation anchor missing — this run would FALSE-PASS"
    _cut = _m.group(0)
    assert _src.count(_cut) == 1, "perturbation anchor is not unique — this run would FALSE-PASS"
    _tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".perturbed-panel.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, _m.group(1) + "if not _x:", 1))
    PANEL = _tmp

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
if INTENT:
    os.unlink(PANEL)

# ── 1. `_dev_link_state` — asked of REAL sysfs, because a stub would only test the stub ──────────
_REAL_STATE = N._dev_link_state
if not PERTURB and not INTENT:
    check("lo — the one device every host has — reads up", _REAL_STATE("lo") == "up", _REAL_STATE("lo"))
    check("a device that is not there reads absent",
          _REAL_STATE("swg-no-such-dev") == "absent", _REAL_STATE("swg-no-such-dev"))
    check("an empty name reads absent (never 'up' by accident)", _REAL_STATE("") == "absent")
    # Fail-safe, not an exception: a name the kernel could never have given an interface is ABSENT, which
    # with the kill-switch on closes the path. A detection failure has to fall that way.
    check("a name with a path separator in it reads absent, not an exception",
          _REAL_STATE("../../etc") == "absent", _REAL_STATE("../../etc"))
    check("a name past IFNAMSIZ reads absent", _REAL_STATE("x" * 32) == "absent")

# ── 2. the datapath, driven through the real reconcile_cascade ───────────────────────────────────
class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def lower(state, ks, dev="wgcf", subnet="10.17.0.0/24", table=7000):
    """Run one device-exit plan through reconcile_cascade with the device in `state`. → (argv strings, report)"""
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = (lambda d: "up") if PERTURB else (lambda d: state)
    N._DEVEXIT["list"] = []
    plan = {"devexit": [{"subnet": subnet, "dev": dev, "table": table, "killswitch": ks}]}
    res = N.reconcile_cascade({"interfaces": {}}, plan, None, "")
    # Only the `ip` calls — the iptables/nft churn below is another gate's subject, and a 30-line argv dump
    # beside a red check is how a real failure gets skimmed past.
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"], list(N._DEVEXIT["list"]), res

ROUTE = "ip route replace default dev wgcf table 7000"
RULE  = "ip rule add from 10.17.0.0/24 lookup 7000 priority 7000"
GUARD = "ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC

# 2a) the working case — nothing about a healthy exit changes
c_up, rep_up, res_up = lower("up", False)
check("device UP: the exit's default route and its from-rule are installed",
      ROUTE in c_up and RULE in c_up, [x for x in c_up if x.startswith("ip ")])
check("device UP, no kill-switch: no backstop route", GUARD not in c_up)
check("no errors from a healthy lowering", not res_up["errors"], res_up["errors"])

# 2b) §5.2 — FAILED, kill-switch OFF. Decision 3's fall-through, and it must NOT be silent (see part 3).
for st in ("down", "absent"):
    c, rep, _ = lower(st, False)
    check("device %s, kill-switch OFF: no route out a device that cannot carry it" % st, ROUTE not in c, c)
    check("device %s, kill-switch OFF: no prohibit — traffic falls through to direct" % st, GUARD not in c, c)

# 2c) §5.2 — FAILED, kill-switch ON. THE CHECK THAT PROVES THE SWITCH IS REACHABLE AT ALL.
for st in ("down", "absent"):
    c, rep, _ = lower(st, True)
    check("device %s, kill-switch ON: the prohibit backstop is installed" % st, GUARD in c, c)
    check("device %s, kill-switch ON: …and the from-rule that makes the table REACHABLE" % st, RULE in c,
          "a prohibit in a table nothing looks up is not a kill-switch, it is an unused table")
    check("device %s, kill-switch ON: no route out the dead device" % st, ROUTE not in c, c)

# 2d) kill-switch ON with the device healthy — the backstop is armed but loses on metric, and the rule that
#     `fwd` already added is not added a SECOND time (a duplicate would be invisible to a set-based signature).
c_uk, _, _ = lower("up", True)
check("device UP, kill-switch ON: the real route AND the armed backstop coexist",
      ROUTE in c_uk and GUARD in c_uk, c_uk)
check("device UP, kill-switch ON: the from-rule is added exactly once",
      c_uk.count(RULE) == 1, c_uk.count(RULE))

# 2e) the drift signature must KNOW about the backstop, or a kill-switched node flushes and rebuilds its
#     whole band every single sync — the gap-inducing churn `_cascade_want_sig` exists to avoid.
_g = [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": True, "state": "absent"}]
sig = N._cascade_want_sig([], [], [], guard=_g)
check("the backstop route is in the wanted signature", "T|7000|prohibit||" in sig, sorted(sig))
check("…and so is its from-rule", "R|from|10.17.0.0/24|7000" in sig, sorted(sig))
# ⚠️ ASSERT THE CLAIM, NOT A TOTAL. This counted the whole signature and expected 3, which is a proxy
# for "the from-rule is not duplicated" that goes red whenever any OTHER token is legitimately added — as
# one was when a leg gained an upstream mark. A set cannot hold a duplicate anyway, so the real question
# is whether both producers agree on the SAME spelling; two spellings would be two tokens.
_both = N._cascade_want_sig([{"subnet": "10.17.0.0/24", "via_iface": "wgcf", "table": 7000}], [], [], guard=_g)
check("a live exit and its backstop do not double-count the from-rule",
      len([t for t in _both if t.startswith("R|from|")]) == 1, sorted(_both))
check("…and the backstop's route rides alongside the real one",
      {"T|7000|prohibit||", "T|7000|default|wgcf|"} <= _both, sorted(_both))
check("…while the leg itself is nameable by an upstream mark",
      ("R|upmark|%d|7000" % N._up_mark(7000)) in _both, sorted(_both))
check("with no kill-switch anywhere the signature is untouched",
      N._cascade_want_sig([], [], []) == set())

# ── 2e-ter) the alarm and the recovery must not wait out the 60s safety window ────────────────────
# `reconcile_cascade` is drift-gated and runs on a plan change, on interface churn, or once every
# ROUTING_RECONCILE_EVERY_S. A foreign device coming up or going down is NONE of those — so without the
# device's liveness in the routing signature the node would fail closed up to a minute late, come back up to
# a minute late after the operator fixed it, and report a minute-stale Issues line in both directions.
_CAS = {"devexit": [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": True}]}
N._dev_link_state = (lambda d: "up") if PERTURB else (lambda d: "up")
_sig_up = N._devexit_sig(_CAS)
N._dev_link_state = (lambda d: "up") if PERTURB else (lambda d: "absent")
_sig_gone = N._devexit_sig(_CAS)
check("a device changing state changes the routing signature, so the next sync acts on it",
      _sig_up != _sig_gone, (_sig_up, _sig_gone))
check("…and it is stable while nothing changes", N._devexit_sig(_CAS) == _sig_gone)
check("a node with no exits pays nothing for the check", N._devexit_sig({}) == [] and N._devexit_sig(None) == [])

# ── 2e-bis) §5.2 ITSELF, END TO END: the two events that look identical must NOT behave identically ──
# DISABLED (intent) and FAILED (fact) both mean "no exit route". Fed through BOTH readers — the panel
# resolves intent into a plan, the node resolves fact into a datapath — they have to come out different, or
# the kill-switch is unreachable and decision 3 is unreachable, whichever way the single test is written.
def through_both(enabled, ks, state):
    nodes = {"n1": {"name": "n1", "links": {},
                    "exits": [{"id": "aabbccdd", "device": "wgcf", "enabled": enabled, "killswitch": ks}],
                    "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}}}}}
    _plan = P.cascade_plan(nodes, snaps).get("n1", {})
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = (lambda d: "up") if PERTURB else (lambda d: state)
    N.reconcile_cascade({"interfaces": {}}, _plan, None, "")
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"]

_dis = through_both(enabled=False, ks=True, state="absent")
check("§5.2: an exit the operator DISABLED degrades to direct even with the kill-switch on",
      GUARD not in _dis and RULE not in _dis, _dis)
_fail = through_both(enabled=True, ks=True, state="absent")
check("§5.2: the SAME device, same kill-switch, failed instead of disabled — traffic STOPS",
      GUARD in _fail and RULE in _fail, _fail)
check("§5.2: …so the two events are distinguishable at the datapath, which is the whole trap",
      _dis != _fail)

# ── 2f) THE CONSEQUENCE, on a model of the kernel that was measured rather than imagined ─────────
# Asking "is the device there?" is the CAUSE; this is the EFFECT, and the effect is the part that costs.
# The naive implementation lowers a dead device as a forward anyway and lets the route install fail — but
# the wanted signature then contains `T|<T>|default|<dead dev>`, a token the live reader can NEVER produce,
# because the route the token describes does not exist and cannot be created. The signature therefore never
# matches, and `reconcile_cascade` flushes and rebuilds the node's ENTIRE policy-routing band on every
# single sync, for ever — the gap-inducing churn the drift compare exists to avoid, inflicted on every
# other interface on the box by one broken exit.
#
# Measured behaviours this fake kernel reproduces (netns, 2026-09-08):
#   `ip route replace default dev D table T`  → rc 2 "Device for nexthop is not up" on a DOWN device
#                                             → rc 1 "Cannot find device"           on an ABSENT one
#   `prohibit default metric N` installs regardless and coexists with a `default dev D` at metric 0.
class _Kernel:
    """Just enough `ip` to answer the two questions the drift compare asks."""
    # ⚠️ IT MUST SPEAK EVERY RULE SHAPE THE RECONCILER EMITS, OR THE SETTLE TEST IS A LIE. It only knew
    # `from` rules; when a leg gained an upstream-mark rule this raised ValueError on the FIRST pass, and a
    # fake kernel that cannot install a rule the real one does is a fake kernel that can never settle.
    def __init__(k, up_devs): k.up, k.rules, k.tables, k.marks = set(up_devs), [], {}, []
    def __call__(k, argv, **kw):
        a = list(map(str, argv))
        if a[:3] == ["ip", "rule", "show"]:
            return _R("".join("%d:\tfrom %s lookup %d\n" % (t, s, t) for s, t in k.rules)
                      + "".join("%d:\tfrom all fwmark 0x%x lookup %d\n" % (m, m, t) for m, t in k.marks))
        if a[:3] == ["ip", "route", "show"] and "table" in a:
            return _R("".join(r + "\n" for r in k.tables.get(a[a.index("table") + 1], [])))
        if a[:3] == ["ip", "route", "replace"] and "table" in a:
            T = a[a.index("table") + 1]
            if "dev" in a:
                dev = a[a.index("dev") + 1]
                if dev not in k.up:
                    r = _R(""); r.returncode = 2; return r        # ENETDOWN / ENODEV — the route is NOT created
                k.tables.setdefault(T, []).append("default dev %s scope link" % dev)
            else:
                k.tables.setdefault(T, []).append("prohibit default metric %d" % N.DEVEXIT_GUARD_METRIC)
            return _R("")
        if a[:3] == ["ip", "rule", "add"]:
            pri = int(a[a.index("priority") + 1])
            if "fwmark" in a:
                k.marks.append((pri, int(a[a.index("lookup") + 1])))
            else:
                k.rules.append((a[a.index("from") + 1], pri))
            return _R("")
        if a[:3] == ["ip", "rule", "del"]:
            pref = int(a[a.index("pref") + 1])
            hit = [x for x in k.rules if x[1] == pref] or [x for x in k.marks if x[0] == pref]
            if not hit:
                r = _R(""); r.returncode = 2; return r
            (k.rules if hit[0] in k.rules else k.marks).remove(hit[0]); return _R("")
        if a[:3] == ["ip", "route", "flush"]:
            k.tables.pop(a[a.index("table") + 1], None); return _R("")
        return _R("")

def settles(state, ks):
    """Two passes against the fake kernel → the argv of the SECOND. A settled node tears nothing down."""
    kern = _Kernel(["wgcf"] if state == "up" else [])
    N._dev_link_state = (lambda d: "up") if PERTURB else (lambda d: state)
    plan = {"devexit": [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": ks}]}
    N.run = kern
    N.reconcile_cascade({"interfaces": {}}, plan, None, "")
    seen = []
    N.run = lambda argv, **kw: (seen.append(" ".join(map(str, argv))), kern(argv, **kw))[1]
    N.reconcile_cascade({"interfaces": {}}, plan, None, "")
    return seen

for _st, _ks in (("up", False), ("up", True), ("down", True), ("absent", True), ("absent", False)):
    _2nd = settles(_st, _ks)
    _churn = [x for x in _2nd if x.startswith("ip rule del") or x.startswith("ip route flush")]
    check("device %s + kill-switch %s settles — the second pass rebuilds nothing"
          % (_st, "ON" if _ks else "OFF"), not _churn,
          "the band is flushed and rebuilt EVERY sync: " + str(_churn[:3]))

# ── 3. decision 2 — the node REPORTS it, and the panel says it out loud ──────────────────────────
# The two decisions are one bargain: kill-switch OFF is only defensible because the fall-back is announced.
_, rep_dn, _ = lower("down", False)
check("the node reports the exit device's state",
      rep_dn == [{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "down",
                  # `wgcf` is point-to-point, so it needs no gateway and gets the gatewayless route shape —
                  # the two fields a NIC exit reports the second route shape with. Compared EXACTLY, so a
                  # field added to the report has to be accounted for here rather than sliding past.
                  "needs_gw": False, "gw": "", "killswitch": False,
                  "scope": "iface", "egress_ip": ""}], rep_dn)
_, rep_ok, _ = lower("up", True)
check("…including the healthy case and the kill-switch flag",
      rep_ok == [{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "up",
                  "needs_gw": False, "gw": "", "killswitch": True,
                  "scope": "iface", "egress_ip": ""}], rep_ok)

NODE = {"name": "n1",
        "exits": [{"id": "aabbccdd", "label": "WARP", "device": "wgcf", "enabled": True, "killswitch": False}],
        "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"},
                   "awg1": {"egress_mode": "direct"}}}

def issues(devexit):
    snap = {} if devexit is None else {"devexit": devexit}
    return [i["error"] for i in P._node_issues(NODE, snap)]

_dn = issues([{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "down", "killswitch": False}])
check("a DOWN device with no kill-switch says the traffic went DIRECT",
      len(_dn) == 1 and "falling back to this node's own IP" in _dn[0], _dn)
check("…named by the exit's own LABEL and its device, not by a subnet",
      _dn and _dn[0].startswith("WARP:") and "wgcf" in _dn[0], _dn)
check("…and it names the interface that chose the exit, not the one that did not",
      _dn and "awg0" in _dn[0] and "awg1" not in _dn[0], _dn)

_ab = issues([{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "absent", "killswitch": False}])
check("an ABSENT device gets the provable wording — no such device, not 'is down' (§11.5 row 3)",
      len(_ab) == 1 and "no device called wgcf" in _ab[0] and "is down" not in _ab[0], _ab)

_ks = issues([{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "down", "killswitch": True}])
check("with the kill-switch ON the sentence says traffic STOPPED, never that it went direct",
      len(_ks) == 1 and "kill-switch is holding" in _ks[0]
      and "falling back" not in _ks[0], _ks)
_ka = issues([{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "absent", "killswitch": True}])
check("…and the absent+kill-switch case is its own sentence too",
      len(_ka) == 1 and "no device called wgcf" in _ka[0] and "kill-switch is holding" in _ka[0], _ka)

check("a HEALTHY exit is silent", issues([{"dev": "wgcf", "subnet": "10.17.0.0/24",
                                           "state": "up", "killswitch": False}]) == [])
# Absent ≠ empty. An older node that reports no `devexit` key is not a node reporting a fault.
check("a node that reports nothing about exits raises nothing", issues(None) == [])
check("a node that reports an empty exit list raises nothing", issues([]) == [])
# Several interfaces on one exit are ONE line about the exit, not one per subnet.
_two = issues([{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "absent", "killswitch": False},
               {"dev": "wgcf", "subnet": "10.18.0.0/24", "state": "absent", "killswitch": False}])
check("two interfaces behind one dead exit produce ONE line", len(_two) == 1, _two)
# The sentence must never come out with a blank where its subject should be.
_orphan = issues([{"dev": "wgX", "subnet": "10.19.0.0/24", "state": "absent", "killswitch": False}])
check("a device belonging to no stored exit still names something concrete",
      len(_orphan) == 1 and "wgX" in _orphan[0] and "10.19.0.0/24" in _orphan[0], _orphan)

N._dev_link_state = _REAL_STATE

if INTENT:
    if FAILS:
        print("\nperturbed (intent): a DISABLED exit reached the node as if it had FAILED and was CAUGHT "
              "(%d red) — the kill-switch fired on an exit the operator turned off" % len(FAILS))
        sys.exit(0)
    print("\nperturbed (intent): NOTHING FAILED — this gate does not actually separate intent from failure")
    sys.exit(1)

if PERTURB:
    if FAILS:
        print("\nperturbed: 'never mind whether the device is there' was CAUGHT (%d red) — "
              "the kill-switch never fired and the failure was never announced" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually test §5.2")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
