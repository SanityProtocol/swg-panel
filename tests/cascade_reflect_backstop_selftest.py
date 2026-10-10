#!/usr/bin/env python3
"""Self-test for the cascade REFLECTION BACKSTOP on an exit node — swg-noded `reconcile_cascade`.

A forward-mode interface sends everything from its subnet S into the mesh leg (`from S lookup T`), including a packet
to another client of its OWN node. The exit node's `to S lookup T` sent that packet straight back, and it bounced
between the two nodes until its TTL ran out: measured on two real nodes (.campaign/rigs/device-access-p0-cascade.sh),
3 pings forwarded 96 times. The exit node now refuses a packet that arrived over the leg addressed to S —
`ip rule add iif <leg> to S prohibit priority T`, added BEFORE `to S lookup T` at the same priority.

  [1] the want signature: an exit entry signs the backstop; a node that only sends into a leg signs none
  [2] the live reader: the kernel's listing with the backstop first round-trips (no rebuild next sync); the backstop
      listed AFTER the exit rule — where it can never match — is drift; a listing without it is drift
  [3] the rebuild issues the backstop before the exit rule, with the leg, the subnet and the priority
  [4] a forward-only node issues no prohibit rule at all
  [5] a band with more rules at one priority than a fixed cap converges: on a kernel model of `ip rule` (same-priority
      rules kept in the order they were added, an identical add refused), 8 exit subnets on one table — 16 rules at one
      priority, plus a stale one ahead of them — are rebuilt in order once, and the next passes write nothing. A teardown
      capped at 8 deletions left 9 in place, re-added the rest behind them, signed a backstop behind its exit rule as
      drift, and rebuilt the band on every pass (nixos, 17 rules at 7000: CPU re-qualification FLEET-2).

Hermetic: `run()` is a recorder; the rest of `reconcile_cascade` is stopped at its iptables step.
Run: python3 tests/cascade_reflect_backstop_selftest.py            (0 = pass)
     --perturb   stops signing the backstop (an upgraded node would then never install it) and expects RED on [1], [2].
     --plant cap8   the teardown deletes at most 8 rules per priority again; expects RED on [5].
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
if PLANT:
    _src = open(NODED, encoding="utf-8").read()
    _a, _b = {"cap8": ("            for _ in range(4096):\n                if run([\"ip\", \"rule\", \"del\", \"pref\", str(pri)])",
                       "            for _ in range(8):\n                if run([\"ip\", \"rule\", \"del\", \"pref\", str(pri)])")}[PLANT]
    assert _src.count(_a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    NODED = os.path.join(tempfile.mkdtemp(prefix="backstop-"), "swg-noded")
    open(NODED, "w", encoding="utf-8").write(_src.replace(_a, _b))

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
if PERTURB:
    _want = N._cascade_want_sig
    N._cascade_want_sig = lambda *a, **k: {t for t in _want(*a, **k) if not t.startswith("R|backstop|")}

CP = N.subprocess.CompletedProcess
REAL = {k: getattr(N, k) for k in ("_cascade_live_sig", "_live_band_prios")}
X = N.SWG_RT_BASE + 5
S, LEG = "10.8.0.0/24", "swg_n"
EXIT = [{"table": X, "subnet": S, "via_iface": LEG}]

print("\n[1] the want signature")
want = N._cascade_want_sig([], EXIT, [], ())
check("an exit entry signs the backstop with its subnet, leg and priority", "R|backstop|%s|%s|%d" % (S, LEG, X) in want, sorted(want))
fwd_only = N._cascade_want_sig([{"table": X, "subnet": S, "via_iface": LEG}], [], [], ())
check("a node that only SENDS into the leg signs no backstop", not any(t.startswith("R|backstop") for t in fwd_only), sorted(fwd_only))

print("\n[2] the live reader")
ROUTES = "%s dev %s scope link \n" % (S, LEG)
def live_with(rules):
    def fake(a, input_text=None, timeout=20):
        if a[:3] == ["ip", "rule", "show"]:
            return CP(a, 0, rules, "")
        if a[:4] == ["ip", "route", "show", "table"]:
            return CP(a, 0, ROUTES if a[4] == str(X) else "", "")
        return CP(a, 0, "", "")
    N.run = fake
    return N._cascade_live_sig([str(X)])
BACKSTOP = "%d:\tfrom all to %s iif %s prohibit\n" % (X, S, LEG)       # iproute2's own spelling, as the rig lists it
EXITRULE = "%d:\tfrom all to %s lookup %d\n" % (X, S, X)
ok = live_with(BACKSTOP + EXITRULE)
check("the backstop listed first round-trips — no rebuild on the next sync", ok == want,
      {"only_live": sorted(ok - want), "only_want": sorted(want - ok)})
late = live_with(EXITRULE + BACKSTOP)
check("listed AFTER the exit rule it guards (it would never match): drift", late != want and any("backstop-late" in t for t in late), sorted(late))
missing = live_with(EXITRULE)
check("missing (a node upgraded onto an old band): drift, so the band is rebuilt with it", missing != want,
      {"only_want": sorted(want - missing)})
detached = live_with("%d:\tfrom all to %s iif %s [detached] prohibit\n" % (X, S, LEG) + EXITRULE)
check("a leg that is momentarily gone still reads as the same backstop", detached == want, sorted(detached ^ want))

print("\n[3] the rebuild")
class Stop(Exception):
    pass
def _stop(*a, **k):
    raise Stop()
CALLS = []
N.run = lambda a, input_text=None, timeout=20: CALLS.append(list(a)) or CP(a, 1, "", "")
for name, fn in (("_apply_routing_reset", lambda *a, **k: None), ("_panel_list_refresh", lambda *a, **k: None),
                 ("_rp_filter_val", lambda *a, **k: 2), ("_rp_effective", lambda *a, **k: 2),
                 ("_detect_wan", lambda *a, **k: "eth0"), ("_sysctl_ensure", lambda *a, **k: 2),
                 ("_cascade_live_sig", lambda *a, **k: set()), ("_ensure_fwd_iptables", _stop),
                 ("_dev_link_state", lambda *a, **k: "up"), ("_dev_is_ether", lambda *a, **k: False)):
    setattr(N, name, fn)
N._live_band_prios = lambda: [X]
def rebuild(plan):
    del CALLS[:]
    try:
        N.reconcile_cascade({"interfaces": {}}, plan, None, "", nets=())
    except Stop:
        pass
    return list(CALLS)
calls = rebuild({"forward": [], "exit": EXIT, "devexit": []})
BS = ["ip", "rule", "add", "iif", LEG, "to", S, "prohibit", "priority", str(X)]
EX = ["ip", "rule", "add", "to", S, "lookup", str(X), "priority", str(X)]
check("the backstop is added", BS in calls, [c for c in calls if c[:3] == ["ip", "rule", "add"]])
check("…before the exit rule, at the same priority — so the kernel looks at it first",
      BS in calls and EX in calls and calls.index(BS) < calls.index(EX), [c for c in calls if c[:3] == ["ip", "rule", "add"]])

print("\n[4] a forward-only node")
calls = rebuild({"forward": [{"table": X, "subnet": S, "via_iface": LEG}], "exit": [], "devexit": []})
check("no prohibit rule", not any("prohibit" in c for c in calls if c[:3] == ["ip", "rule", "add"]),
      [c for c in calls if c[:3] == ["ip", "rule", "add"]])

print("\n[5] a band with more rules at one priority than any fixed cap converges")


class Kernel:
    """`ip rule` / `ip route` as the kernel keeps them: rules by priority, same-priority rules in the order they were
    added; an add identical to a rule present is refused (EEXIST); `del pref N` removes the first rule at N."""

    def __init__(self, rules):
        self.rules, self.tables, self.writes = list(rules), {}, []

    def __call__(self, a, input_text=None, timeout=20):
        if a[:3] == ["ip", "rule", "show"]:
            return CP(a, 0, "".join("%d:\tfrom all %s\n" % (p, b) if not b.startswith("from ") else "%d:\t%s\n" % (p, b)
                                    for p, b in self.rules), "")
        if a[:3] == ["ip", "rule", "del"] and a[3] == "pref":
            self.writes.append(a)
            for k, (p, _) in enumerate(self.rules):
                if p == int(a[4]):
                    del self.rules[k]
                    return CP(a, 0, "", "")
            return CP(a, 2, "", "RTNETLINK answers: No such file or directory")
        if a[:3] == ["ip", "rule", "add"]:
            self.writes.append(a)
            i = a.index("priority"); p = int(a[i + 1]); sel = a[3:i]
            if "lookup" in sel:                          # iproute2's own order: selectors, then the action
                j = sel.index("lookup"); sel = sel[:j] + sel[j + 2:] + sel[j:j + 2]
            if "iif" in sel:                              # `to S iif L prohibit`, as `ip rule show` spells it
                j = sel.index("iif"); sel = [t for k, t in enumerate(sel) if k not in (j, j + 1)]
                sel = sel[:2] + ["iif", a[3 + a[3:i].index("iif") + 1]] + sel[2:]
            body = " ".join(sel)
            if (p, body) in self.rules:
                return CP(a, 2, "", "RTNETLINK answers: File exists")
            at = max([k + 1 for k, (q, _) in enumerate(self.rules) if q <= p] or [0])
            self.rules.insert(at, (p, body))
            return CP(a, 0, "", "")
        if a[:3] == ["ip", "route", "flush"]:
            self.writes.append(a)
            self.tables[a[4]] = {}
            return CP(a, 0, "", "")
        if a[:3] == ["ip", "route", "replace"]:
            self.writes.append(a)
            t = a[a.index("table") + 1]
            self.tables.setdefault(t, {})[a[3]] = a[a.index("dev") + 1]
            return CP(a, 0, "", "")
        if a[:4] == ["ip", "route", "show", "table"]:
            return CP(a, 0, "".join("%s dev %s scope link \n" % kv for kv in self.tables.get(a[4], {}).items()), "")
        return CP(a, 0, "", "")


for k, v in REAL.items():
    setattr(N, k, v)
SUBS = ["10.%d.0.0/24" % (60 + k) for k in range(8)]
EX8 = [{"table": X, "subnet": s_, "via_iface": LEG} for s_ in SUBS]
_band = []
for s_ in SUBS:
    _band += [(X, "to %s iif %s prohibit" % (s_, LEG)), (X, "to %s lookup %d" % (s_, X))]
K = Kernel([(X, "fwmark %#x lookup %d" % (X, X))] + _band)   # a stale fwmark rule ahead of a healthy band: drift
K.tables[str(X)] = {s_: LEG for s_ in SUBS}
N.run = K
per = []
for _ in range(4):
    del K.writes[:]
    try:
        N.reconcile_cascade({"interfaces": {}}, {"forward": [], "exit": EX8, "devexit": []}, None, "", nets=())
    except Stop:
        pass
    per.append(len(K.writes))
order = [b for p, b in K.rules if p == X]
_late = [s_ for s_ in SUBS if "to %s lookup %d" % (s_, X) in order and "to %s iif %s prohibit" % (s_, LEG) in order
         and order.index("to %s iif %s prohibit" % (s_, LEG)) > order.index("to %s lookup %d" % (s_, X))]
check("the first pass rebuilds the drifted band (17 rules at one priority, one of them stale)", per[0] > 0, per)
check("…and the next three passes write nothing: the band converged", per[1:] == [0, 0, 0], per)
check("every backstop sits ahead of its exit rule, the stale rule is gone, nothing is doubled",
      not _late and len(order) == 16 and len(set(order)) == 16 and not any("fwmark" in b for b in order), {"late": _late, "order": order})
check("the live band reads as the plan wants it", N._cascade_live_sig([str(X)]) == N._cascade_want_sig([], EX8, [], ()),
      sorted(N._cascade_live_sig([str(X)]) ^ N._cascade_want_sig([], EX8, [], ())))

print("")
if PLANT:
    print(("--plant %s: CAUGHT (%d red)" % (PLANT, len(FAILS))) if FAILS else "--plant %s: NOTHING FAILED" % PLANT)
    sys.exit(0 if FAILS else 1)
if PERTURB:
    ok_ = len(FAILS) > 0
    print(("perturbed: the unsigned backstop was CAUGHT (%d red) — an upgraded node would never install it" % len(FAILS))
          if ok_ else "perturbed: NOTHING FAILED — this gate does not test the signature")
    sys.exit(0 if ok_ else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
