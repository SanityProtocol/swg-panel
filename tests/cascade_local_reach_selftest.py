#!/usr/bin/env python3
"""Self-test: a forward/smart interface's table carries the node's OWN client subnets (DEVICE-ACCESS P0 K5).

`from S lookup T` with only `default dev <leg>` in T sends a forward-mode client's packet to a neighbour on the same node
out the leg — the exit node bounced it back until its TTL ran out (refused there since e3b0d65, still unreachable).
The fix puts each client subnet `main` routes into every table serving a client subnet, beside the networks (§4.2).

  [1] `_cascade_local_routes` lists every kind of client tunnel — a wg interface, a WDTT instance and its RAW TUN, a
      csqtt instance — and nothing else: not a mesh link, not a network carried on a client interface, not a subnet
      whose device `main` does not route right now.
  [2] the rebuild installs them into the forward, smart and kill-switch tables, never an exit table, and even when the
      node carries no networks — but never one spelled like another node's exit subnet (it would take that route over).
  [3] ⚠️ every route installed into a band table is SIGNED. `_cascade_live_sig` reads every route in those tables; one
      the want-set lacks is drift for ever — the whole band flushed and rebuilt on every sync.
  [4] a node with no forward/smart/kill-switch table does not read them at all.

Hermetic: `run()` is a recorder, /proc/net/route is a temp file, the WDTT/csqtt stores are stubs.

Run: python3 tests/cascade_local_reach_selftest.py            (0 = pass)
     --perturb   the want signature leaves the local routes out (installed but unsigned) and expects RED on [3].
"""
import importlib.machinery, importlib.util, os, sys, tempfile

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
if not hasattr(N, "_cascade_local_routes"):
    print("  FAIL this build has no _cascade_local_routes — a forward-mode table carries no local route\n\n1 FAIL")
    sys.exit(1)

TMP = tempfile.mkdtemp(prefix="cascade-local-")
def conf(name, addr):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\nListenPort = 51820\n" % addr)
    return p
def hexle(dotted):
    a = [int(x) for x in dotted.split(".")]
    return "%02X%02X%02X%02X" % (a[3], a[2], a[1], a[0])
def row(dev, dst, mask, gw="0.0.0.0"):
    return "%s\t%s\t%s\t0001\t0\t0\t0\t%s\t0\t0\t0" % (dev, hexle(dst), hexle(gw), hexle(mask))

print("\n[1] _cascade_local_routes lists every kind of client tunnel, and nothing else")
CFG = {"interfaces": {"wg0": {"conf": conf("wg0", "10.8.0.1/24")},
                      "wg9": {"conf": conf("wg9", "10.28.0.1/24, fd00:28::1/64")},
                      "swg_ab12": {"conf": conf("swg_ab12", "10.255.0.1/31")},
                      "awgdown": {"conf": conf("awgdown", "10.40.0.1/24")}}}
N._wdtt_load = lambda: {"wdtt1": {"wg_addr": "10.11.0.1/24", "listen": "192.0.2.7:443", "raw_port": "56003",
                                  "raw_iface": "wdttraw1", "raw_addr": "10.12.0.1/24"}}
N._csqtt_load = lambda: {"csqtt1": {"tun_addr": "10.10.0.1/24"}}
proc = os.path.join(TMP, "route")
with open(proc, "w") as f:
    f.write("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n" + "\n".join([
        row("eth0", "0.0.0.0", "0.0.0.0", "192.0.2.1"),
        row("wg0", "10.8.0.0", "255.255.255.0"),
        row("wg0", "192.168.50.0", "255.255.255.0"),          # a network carried on wg0 — §4.2's, not a client subnet
        row("wg9", "10.28.0.0", "255.255.255.0"),
        row("swg_ab12", "10.255.0.0", "255.255.255.254"),     # mesh link
        row("wdtt1", "10.11.0.0", "255.255.255.0"),
        row("wdttraw1", "10.12.0.0", "255.255.255.0"),
        row("csqtt1", "10.10.0.0", "255.255.255.0"),
        # awgdown: configured, but `main` routes nothing on it
    ]) + "\n")
got = N._cascade_local_routes(CFG, _proc=proc)
want = [("10.10.0.0/24", "csqtt1"), ("10.11.0.0/24", "wdtt1"), ("10.12.0.0/24", "wdttraw1"),
        ("10.28.0.0/24", "wg9"), ("10.8.0.0/24", "wg0")]
check("exactly wg0, wg9 (its IPv4 entry), wdtt1, its RAW TUN and csqtt1", got == want, got)
check("an unreadable table lists nothing (never raises)", N._cascade_local_routes(CFG, _proc=os.path.join(TMP, "nope")) == [])

print("\n[2] the rebuild installs them into forward, smart and kill-switch tables — never an exit table")
class Stop(Exception):
    pass
def _stop(*a, **k):
    raise Stop()
CP = N.subprocess.CompletedProcess
CALLS, SIGS = [], []
N.run = lambda a, input_text=None, timeout=20: CALLS.append(list(a)) or CP(a, 1, "", "")
for name, fn in (("_apply_routing_reset", lambda *a, **k: None), ("_panel_list_refresh", lambda *a, **k: None),
                 ("_rp_filter_val", lambda *a, **k: 2), ("_rp_effective", lambda *a, **k: 2),
                 ("_detect_wan", lambda *a, **k: "eth0"), ("_sysctl_ensure", lambda *a, **k: 2),
                 ("_cascade_live_sig", lambda *a, **k: set()), ("_ensure_fwd_iptables", _stop),
                 ("_dev_link_state", lambda *a, **k: "up"), ("_dev_is_ether", lambda *a, **k: False)):
    setattr(N, name, fn)
LOCAL = [("10.28.0.0/24", "wg9"), ("10.30.0.0/24", "wg5"), ("10.8.0.0/24", "wg0")]
LOOKUPS = []
N._cascade_local_routes = lambda cfg, _proc=None: LOOKUPS.append(1) or list(LOCAL)
_orig_sig = N._cascade_want_sig
def _rec_sig(fwd, exit_, smart=None, guard=(), nets=(), net_tables=(), arr=()):
    if PERTURB:
        nets = [x for x in nets if x not in LOCAL]
    s = _orig_sig(fwd, exit_, smart, guard, nets=nets, net_tables=net_tables, arr=arr)
    SIGS.append(s)
    return s
N._cascade_want_sig = _rec_sig
T, TS, TK, TX = (N.SWG_RT_BASE + i for i in (60, 61, 62, 63))
N._live_band_prios = lambda: [T, TS, TK, TX]
FWD = [{"table": T, "subnet": "10.8.0.0/24", "via_iface": "swg_ab12"}]
EXIT = [{"table": TX, "subnet": "10.30.0.0/24", "via_iface": "swg_cd34"}]
plan = {"forward": FWD, "exit": EXIT,
        "devexit": [{"table": TK, "subnet": "10.9.0.0/24", "dev": "wgx-1", "state": "up", "killswitch": True,
                     "scope": "iface"}]}
smart = {"mode": "kernel", "entries": [{"table": TS, "subnet": "10.11.0.0/24", "via_iface": "swg_ab12",
                                        "category": "ru", "action": "exit"}]}
def lowered(p, s, nets=()):
    del CALLS[:], SIGS[:], LOOKUPS[:]
    try:
        N.reconcile_cascade({"interfaces": {}}, p, s, "", nets=nets)
    except Stop:
        pass
    return [c for c in CALLS if c[:3] == ["ip", "route", "replace"]]
routes = lowered(plan, smart)
for tbl, what in ((T, "forward"), (TS, "smart"), (TK, "kill-switch")):
    check("%s table %d gets wg0's and wg9's subnets with no networks carried" % (what, tbl),
          ["ip", "route", "replace", "10.8.0.0/24", "dev", "wg0", "table", str(tbl)] in routes
          and ["ip", "route", "replace", "10.28.0.0/24", "dev", "wg9", "table", str(tbl)] in routes, routes)
check("the exit table gets no local route",
      not any(c[-1] == str(TX) and c[3] in ("10.8.0.0/24", "10.28.0.0/24") for c in routes), routes)
check("a local subnet spelled like another node's exit subnet is never installed (the exit route stays alone)",
      [c for c in routes if c[3] == "10.30.0.0/24"] == [["ip", "route", "replace", "10.30.0.0/24", "dev", "swg_cd34",
                                                         "table", str(TX)]], [c for c in routes if c[3] == "10.30.0.0/24"])
idx_def = next((i for i, c in enumerate(CALLS) if c[:4] == ["ip", "route", "replace", "default"] and c[-1] == str(T)), None)
check("the forward table's default is still there beside them", idx_def is not None)

print("\n[3] every route installed into a band table is signed — no rebuild on every sync")
sig = SIGS[-1] if SIGS else set()
unsigned = [c for c in routes if c[3] != "default" and c[4:5] == ["dev"]         # `<prefix> dev <d> table T` routes
            and "T|%s|%s|%s|" % (c[-1], N._net_kernel_dst(c[3]), c[5]) not in sig]
check("installed ⇒ signed", SIGS and not unsigned, unsigned)
signed_local = sorted(t for t in sig if t.startswith("T|") and t.split("|")[2] in ("10.8.0.0/24", "10.28.0.0/24"))
check("signed ⇒ installed (6 tokens: 2 subnets × 3 tables)", len(signed_local) == 6, signed_local)

print("\n[4] a node with no forward/smart/kill-switch table does not read them")
routes = lowered({"forward": [], "exit": EXIT, "devexit": []}, None)
check("not consulted", LOOKUPS == [], LOOKUPS)
check("no local route issued", not any(c[3] in ("10.8.0.0/24", "10.28.0.0/24") for c in routes), routes)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
