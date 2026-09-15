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

Hermetic: `run()` is a recorder; the rest of `reconcile_cascade` is stopped at its iptables step.
Run: python3 tests/cascade_reflect_backstop_selftest.py            (0 = pass)
     --perturb   stops signing the backstop (an upgraded node would then never install it) and expects RED on [1], [2].
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

print("")
if PERTURB:
    ok_ = len(FAILS) > 0
    print(("perturbed: the unsigned backstop was CAUGHT (%d red) — an upgraded node would never install it" % len(FAILS))
          if ok_ else "perturbed: NOTHING FAILED — this gate does not test the signature")
    sys.exit(0 if ok_ else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
