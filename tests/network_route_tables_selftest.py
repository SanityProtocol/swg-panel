#!/usr/bin/env python3
"""Self-test for NETWORKS §4.2 — a forward/smart interface never consults `main`.

`ip rule from <subnet> lookup T` with `default dev <leg>` in T: a default route matches `192.168.1.0/24` as
happily as the internet, so a client on a forward-mode interface is sent into the mesh and `main` — where the
network's route lives — is never reached. Silent, total, every screen healthy.

The fix puts each network `main` holds into every table serving a client subnet. Two ways that goes wrong
without anything saying so, and this gate holds both:

  [1] the WANT signature signs the network routes, in the KERNEL'S spelling — a /32 bare (§4.11).
  [2] ⚠️ …and it round-trips against the LIVE reader. `_cascade_live_sig` reads every route in a band table;
      a network route the want-set does not sign, or signs as `x/32`, is drift for ever — the whole band
      flushed and rebuilt on every sync, leaking packets in each gap. That is the failure a datapath test that
      only asks "is the route there?" cannot see.
  [3] the rebuild installs it into the forward table AND a smart table AND a kill-switch table — but not an
      EXIT table (those carry other nodes' clients; a network is reached from its own node, D12).
  [4] D1 — with no networks the signature is exactly what it was, and the rebuild issues no network route.

Hermetic: `run()` is a recorder; the rest of `reconcile_cascade` is stopped at its iptables step.

Run: python3 tests/network_route_tables_selftest.py            (0 = pass)
     --perturb   signs a /32 as `x/32` (the obvious spelling) and expects RED on [2].
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
    N._net_kernel_dst = lambda p: p

NETS = [("192.168.50.0/24", "wg0"), ("172.30.9.9/32", "wg0")]
T = N.SWG_RT_BASE + 50
FWD = [{"table": T, "subnet": "10.8.0.0/24", "via_iface": "swg_ab12"}]
CP = N.subprocess.CompletedProcess

print("\n[1] the want signature signs network routes as the kernel prints them")
want = N._cascade_want_sig(FWD, [], [], (), nets=NETS, net_tables=[str(T)])
check("the /24 is signed with its length", "T|%d|192.168.50.0/24|wg0|" % T in want, sorted(want))
check("the /32 is signed BARE", "T|%d|172.30.9.9|wg0|" % T in want, sorted(want))

print("\n[2] …and round-trips against the live reader — no drift, no rebuild every sync")
_u = N._up_mark(T)
rules = "%d:\tfrom 10.8.0.0/24 lookup %d \n" % (T, T)
if _u:
    rules += "%d:\tfrom all fwmark %s lookup %d \n" % (_u, hex(_u), T)
routes = ("default dev swg_ab12 scope link \n"
          "172.30.9.9 dev wg0 scope link \n"                       # ← what `ip route show table T` really prints
          "192.168.50.0/24 dev wg0 scope link \n")
def fake(a, input_text=None, timeout=20):
    if a[:3] == ["ip", "rule", "show"]:
        return CP(a, 0, rules, "")
    if a[:4] == ["ip", "route", "show", "table"]:
        return CP(a, 0, routes if a[4] == str(T) else "", "")
    return CP(a, 0, "", "")
N.run = fake
live = N._cascade_live_sig([str(T)])
check("live == want (the band is NOT rebuilt on the next sync)", live == want,
      {"only_live": sorted(live - want), "only_want": sorted(want - live)})

print("\n[3] the rebuild installs into forward, smart and kill-switch tables — never an exit table")
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
TS, TK, TX = N.SWG_RT_BASE + 51, N.SWG_RT_BASE + 52, N.SWG_RT_BASE + 53
N._live_band_prios = lambda: [T, TS, TK, TX]
plan = {"forward": FWD,
        "exit": [{"table": TX, "subnet": "10.30.0.0/24", "via_iface": "swg_cd34"}],
        "devexit": [{"table": TK, "subnet": "10.9.0.0/24", "dev": "wgx-1", "state": "up", "killswitch": True,
                     "scope": "iface"}]}
smart = {"mode": "kernel", "entries": [{"table": TS, "subnet": "10.11.0.0/24", "via_iface": "swg_ab12",
                                        "category": "ru", "action": "exit"}]}
def lowered(nets):
    del CALLS[:]
    try:
        N.reconcile_cascade({"interfaces": {}}, plan, smart, "", nets=nets)
    except Stop:
        pass
    return [c for c in CALLS if c[:3] == ["ip", "route", "replace"] and c[3] in ("192.168.50.0/24", "172.30.9.9/32")]
got = lowered(NETS)
for tbl, what in ((T, "forward"), (TS, "smart"), (TK, "kill-switch")):
    check("%s table %d gets both networks" % (what, tbl),
          ["ip", "route", "replace", "192.168.50.0/24", "dev", "wg0", "table", str(tbl)] in got
          and ["ip", "route", "replace", "172.30.9.9/32", "dev", "wg0", "table", str(tbl)] in got, got)
check("the EXIT table does not", not any(c[-1] == str(TX) for c in got), got)
idx_def = next((i for i, c in enumerate(CALLS) if c[:4] == ["ip", "route", "replace", "default"] and c[-1] == str(T)), None)
idx_net = next((i for i, c in enumerate(CALLS) if c[3:4] == ["192.168.50.0/24"] and c[-1] == str(T)), None)
check("the table's default exists and the network is a more specific route beside it",
      idx_def is not None and idx_net is not None, (idx_def, idx_net))

print("\n[4] D1 — no networks, nothing changes")
check("want signature with nets=() is identical to the call without it",
      N._cascade_want_sig(FWD, [], [], ()) == N._cascade_want_sig(FWD, [], [], (), nets=(), net_tables=()))
check("the rebuild issues no network route", lowered(()) == [], lowered(()))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
