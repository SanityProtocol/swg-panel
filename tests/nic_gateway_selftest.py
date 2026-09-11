#!/usr/bin/env python3
"""Self-test for NIC-EXIT step 3 — GATEWAY DETECTION, and the second default-route shape it unlocks.

Every route this panel installs was gatewayless: `default dev <D> table T`. Down a point-to-point tunnel
that is exactly right. Down a multi-access NIC it is destructive, and that is measured on the wire rather
than reasoned about (plan §3c T1): contacting 20 destinations produced **20 neighbour entries, all FAILED,
and 100% loss** — the box ARPs the internet on the LAN segment. Neighbour-table exhaustion plus a broadcast
storm. With `via <gw>` the same run kept ONE neighbour entry and delivered.

So this gate covers the three things that make a NIC exit safe, and each of them is a place a plausible
implementation goes wrong:

  1. DETECTION reads a gateway only where one is actually declared. A gateway is NOT guessable from the
     device's address — `192.0.2.2/24` says nothing about whether `.1` is a router — and a gatewayless
     default route is NOT a gateway. Guess either and you have built the T1 shape on purpose.
  2. NOTHING GATEWAYLESS IS EVER INSTALLED ON A NIC. A multi-access device with no gateway is treated like
     a down one, which is a degrade this tree already has semantics for.
  3. ⚠️⚠️ THE GATEWAY IS IN THE DRIFT SIGNATURE — and this is the one that is invisible until it bites. The
     signature is what decides whether to rebuild the band. Sign the device but not the gateway and a DHCP
     renewal that MOVES the gateway compares equal: the rebuild is skipped, the box keeps a `via` pointing
     at a router that is gone, and the device still reads up. Traffic dead, every screen green.

⚠️ AND THE INVERSE, WHICH IS THE TRAP THIS FEATURE'S PROTOTYPES KEEP FINDING. Detection must not feed the
WITHDRAW decision. Measured both ways (§3b for carrier, §3c T3 for the gateway): with the route in place,
losing the gateway is a clean blackhole — 13/25 replies, ZERO packets leaked to the WAN. Withdraw the route
and the table EMPTIES, the `ip rule` falls through to `main`, and the client egresses out the very WAN the
exit exists to hide. [7] pins that down: a device whose gateway stopped resolving keeps running with the
one already installed.

Hermetic: no ip, no iptables, no network. `run()` is stubbed and the argv inspected; the parser is fed
fixtures for the shapes this box cannot be made to have, AND asked about the real kernel state, where its
answer is cross-checked against `ip route show default` — two independent readers of one fact.

Run: python3 tests/nic_gateway_selftest.py            (0 = pass)
     --perturb      builds the shape as it shipped — the fold-in guard and the `via` both removed, i.e.
                    every device exit lowered gatewayless — and expects RED on [5].
     --perturb-sig  drops the gateway from the drift signature, the four-field token, and expects RED on
                    [6]: a moved gateway becomes invisible and the box never rebuilds.
"""
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PSIG = "--perturb-sig" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# Both perturbations are applied to the SOURCE, because what they remove is an expression inside a
# function with no seam to monkey-patch. Each asserts its anchor is present exactly once: an anchor that
# has drifted would silently perturb NOTHING and the run would report a clean pass over an untested fix.
_src = open(NODED, encoding="utf-8").read()
_cuts = []
if PERTURB:
    # …both route loops, because there are two: the from-rule one (`fwd`) and the fwmark one (`smart_exit`).
    # Reverting only the first left the rule scope's regression uncaught — which is how it shipped.
    _cuts += [('(["via", _gw] if _gw else [])', "[]"),
              ('(["via", _sg] if _sg else [])', "[]"),
              ('for e in smart_exit if not e.get("_noroute")', "for e in smart_exit"),
              ('               and not (e["needs_gw"] and not e["gw"])]', "               ]")]
if PSIG:
    _cuts += [("""sig.add(f"T|{T}|default|{e['via_iface']}|{str(e.get('gw') or '')}")""",
               """sig.add(f"T|{T}|default|{e['via_iface']}|")""")]
if _cuts:
    for old, new in _cuts:
        assert _src.count(old) >= 1, "perturbation anchor missing (%r) — this run would FALSE-PASS" % old[:40]
        _src = _src.replace(old, new)
    _fd, NODED = tempfile.mkstemp(suffix=".py", prefix="perturbed-noded-", dir=HERE)
    os.write(_fd, _src.encode()); os.close(_fd)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod

N = _load(NODED, "swgnoded")
if _cuts:
    os.unlink(NODED)

# ── 1. the parser, fed the shapes this box cannot be made to have ────────────────────────────────
HDR = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
def proc(*rows):
    """A /proc/net/route fixture. rows: (iface, dest_hex, gw_hex, metric)."""
    f = tempfile.NamedTemporaryFile("w", suffix=".route", delete=False)
    f.write(HDR + "".join("%s\t%s\t%s\t0003\t0\t0\t%d\t00000000\t0\t0\t0\n" % r for r in rows))
    f.close()
    return f.name

print("\n[1] a gateway is read only where one is actually declared")
p = proc(("eth0", "00000000", "0102A8C0", 100))
# The field is the u32 in HOST order printed %08X, so the LOW byte is the FIRST octet. Get this backwards
# and the panel installs `via 1.2.168.192` — a syntactically perfect route to nowhere.
check("a default route yields its gateway, octets in the right order",
      N._dev_gateway("eth0", p) == "192.168.2.1", N._dev_gateway("eth0", p))
p = proc(("eth0", "00000000", "00000000", 100))
check("⚠️ a GATEWAYLESS default is not a gateway — it is the destructive shape itself",
      N._dev_gateway("eth0", p) == "", N._dev_gateway("eth0", p))
p = proc(("eth0", "0002A8C0", "0102A8C0", 100))
check("a route that is not the DEFAULT route is not a way off-box",
      N._dev_gateway("eth0", p) == "", N._dev_gateway("eth0", p))
p = proc(("eth0", "00000000", "0102A8C0", 100))
check("another device's default route is not this device's gateway",
      N._dev_gateway("eth2", p) == "", N._dev_gateway("eth2", p))
p = proc(("eth0", "00000000", "0902A8C0", 600), ("eth0", "00000000", "0102A8C0", 100))
check("two defaults on one device: the lowest metric wins, the way the kernel picks",
      N._dev_gateway("eth0", p) == "192.168.2.1", N._dev_gateway("eth0", p))
check("a file that is not there reads '' rather than raising",
      N._dev_gateway("eth0", os.path.join(HERE, "no-such-proc-file")) == "")
check("an empty device name reads ''", N._dev_gateway("", p) == "")
p = proc(("eth0", "00000000", "0102A8C0", 100))
check("a device the kernel could never have named reads ''", N._dev_gateway("../../etc", p) == "")

print("\n[2] …and it agrees with the kernel about THIS box (two readers, one fact)")
_ipr = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True).stdout
_truth = {}
for _ln in _ipr.splitlines():
    _t = _ln.split()
    if "dev" in _t and "via" in _t:
        _truth.setdefault(_t[_t.index("dev") + 1], _t[_t.index("via") + 1])
if _truth:
    for _d, _gw in _truth.items():
        check("`ip route` says %s is via %s, and so does the /proc reader" % (_d, _gw),
              N._dev_gateway(_d) == _gw, N._dev_gateway(_d))
else:
    # NOT a silent skip. A box with no default route cannot answer this cell, and saying so is the
    # difference between "asked and agreed" and "never asked" ([[lesson-detection-failure-fail-safe]]).
    print("  SKIP this box has no IPv4 default route — [2] cannot be answered here")
check("a device with no default route of its own reads '' on the real box",
      N._dev_gateway("lo") == "", N._dev_gateway("lo"))

print("\n[3] which devices even NEED a gateway — asked of real sysfs")
check("loopback is not a multi-access link", N._dev_is_ether("lo") is False)
check("a device that is not there is not one either", N._dev_is_ether("swg-no-such-dev") is False)
_ether = [d for d in sorted(os.listdir("/sys/class/net"))
          if os.path.exists("/sys/class/net/%s/type" % d)
          and open("/sys/class/net/%s/type" % d).read().strip() == "1"]
if _ether:
    check("a real ARPHRD_ETHER device on this box reads as one (%s)" % _ether[0],
          N._dev_is_ether(_ether[0]) is True)
else:
    print("  SKIP this box has no ARPHRD_ETHER device — the positive half of [3] cannot be answered here")

print("\n[4] which gateway an entry is lowered with, and in which order")
_p_has = proc(("eth2", "00000000", "0102A8C0", 100))
_p_none = proc(("eth9", "00000000", "0102A8C0", 100))
_ent = {"dev": "eth2", "table": 7000, "gw": "10.0.0.254"}   # typed value, deliberately != the running one
_saved, _saved_eth = N._table_default_via, N._dev_is_ether
N._table_default_via = lambda t, d: ""
N._dev_is_ether = lambda d: True                       # eth2/eth9 are fictional; the class is [3]'s subject
check("detection beats the typed override — a box that learns a real default route takes it",
      N._devexit_gw(_ent, detected="192.168.2.1") == "192.168.2.1", N._devexit_gw(_ent, detected="192.168.2.1"))
check("with nothing detected and nothing running, the typed override is used",
      N._devexit_gw(_ent, detected="") == "10.0.0.254")
check("…and with no override either, there is no gateway to lower with",
      N._devexit_gw({"dev": "eth2", "table": 7000}, detected="") == "")
N._table_default_via = lambda t, d: "10.0.0.9"
# ⚠️ THE TYPED VALUE BEATS WHAT IS ALREADY RUNNING, and this used to be the other way round. With the
# last-known-good ahead of it, a route installed FROM a typed gateway answered for ever: the operator
# corrected a wrong gateway, saw it stored, and the node kept running the old one — and since nothing
# drifted, nothing rebuilt, so it never recovered. An explicit instruction beats a memory.
check("⚠️ an EDITED typed gateway applies, even with an old one still installed",
      N._devexit_gw(_ent, detected="") == "10.0.0.254",
      N._devexit_gw(_ent, detected=""))
check("…but with NO typed value, what is running is still kept — that is [7]'s no-withdraw half",
      N._devexit_gw({"dev": "eth2", "table": 7000}, detected="") == "10.0.0.9",
      N._devexit_gw({"dev": "eth2", "table": 7000}, detected=""))
N._dev_is_ether = lambda d: False
check("a point-to-point device gets no gateway at all, whatever is lying around",
      N._devexit_gw(_ent, detected="192.168.2.1") == "")
N._table_default_via, N._dev_is_ether = _saved, _saved_eth

print("\n[5] the two route shapes, driven through the real reconcile_cascade")
class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def lower(dev, ether, gw, table=7000, subnet="10.17.0.0/24", ks=False, live_via=""):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: "up"
    N._dev_is_ether = lambda d: ether
    N._dev_gateway = lambda d, _proc="/proc/net/route": gw
    N._table_default_via = lambda t, d: live_via
    N._DEVEXIT["list"] = []
    res = N.reconcile_cascade({"interfaces": {}},
                              {"devexit": [{"subnet": subnet, "dev": dev, "table": table, "killswitch": ks}]},
                              None, "")
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"], list(N._DEVEXIT["list"]), res

c, rep, _ = lower("eth2", True, "10.201.0.1")
check("a NIC with a gateway lowers to `default via <gw> dev <nic>`",
      "ip route replace default via 10.201.0.1 dev eth2 table 7000" in c, c)
check("…and its from-rule, so the table is reachable",
      "ip rule add from 10.17.0.0/24 lookup 7000 priority 7000" in c, c)
check("…and the panel is told the shape and the gateway",
      rep and rep[0].get("needs_gw") is True and rep[0].get("gw") == "10.201.0.1", rep)

c, rep, _ = lower("eth2", True, "")
check("⚠️ a NIC with NO gateway installs NOTHING gatewayless (the §3c T1 shape, 100% loss)",
      not any(x.startswith("ip route replace default dev eth2") for x in c), c)
check("…and no `via` route either — it is not lowered at all",
      not any("route replace default" in x for x in c), c)
check("…and the panel is told WHY: it needs a gateway and has none",
      rep and rep[0].get("needs_gw") is True and rep[0].get("gw") == "", rep)

c, _, _ = lower("wgcf", False, "")
check("a point-to-point exit is lowered EXACTLY as before — gatewayless, unchanged",
      "ip route replace default dev wgcf table 7000" in c, c)

c, _, _ = lower("eth2", True, "", ks=True)
check("a gatewayless NIC with the kill-switch on still fails CLOSED",
      "ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC in c
      and "ip rule add from 10.17.0.0/24 lookup 7000 priority 7000" in c, c)

print("\n[5b] ⚠️ THE RULE SCOPE GETS THE SAME ROUTE SHAPE — it did not, and that was the destructive one")
# A rule-scoped device exit is reached by fwmark, so it never passes through `_devfwd` and its route is
# built by the smart loop. That loop still wrote `default dev <D>` — on a card, the shape §3c T1 measured
# at 20 FAILED neighbour entries and 100% loss. One of the three scopes decision 4 asked for.
SUB = "10.17.0.0/24"
def rule_lower(dev, ether, gw, ks=False):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: "up"
    N._dev_is_ether = lambda d: ether
    N._dev_gateway = lambda d, _proc="/proc/net/route": gw
    N._table_default_via = lambda t, d: ""
    N._DEVEXIT["list"] = []
    res = N.reconcile_cascade({"interfaces": {}},
        {"devexit": [{"subnet": SUB, "dev": dev, "table": 7000, "killswitch": ks,
                      "egress_ip": "", "gw": "", "scope": "rule"}]},
        {"entries": [{"subnet": SUB, "category": "v", "action": "exit", "via_iface": dev, "table": 7000}],
         "mode": "kernel"}, "")
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"], res

c, _ = rule_lower("eth2", True, "10.201.0.1")
check("a per-category exit out a CARD routes `via` its gateway",
      "ip route replace default via 10.201.0.1 dev eth2 table 7000" in c, c)
check("…and its fwmark rule, so the table is reachable",
      "ip rule add fwmark 7000 lookup 7000 priority 7000" in c, c)
c, _ = rule_lower("eth2", True, "")
check("⚠️ a card with NO gateway installs nothing gatewayless here either",
      not any(x.startswith("ip route replace default dev eth2") for x in c), c)
check("⚠️ …but KEEPS its fwmark rule — it is the only way into the table the kill-switch sits in",
      "ip rule add fwmark 7000 lookup 7000 priority 7000" in c, c)
c, _ = rule_lower("eth2", True, "", ks=True)
check("…so a rule-scoped kill-switch still fails CLOSED on a gatewayless card",
      ("ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC) in c
      and "ip rule add fwmark 7000 lookup 7000 priority 7000" in c, c)
c, _ = rule_lower("wgcf", False, "")
check("a point-to-point rule exit is unchanged — gatewayless, as a tunnel should be",
      "ip route replace default dev wgcf table 7000" in c, c)
# ⚠️ AND IT MUST SETTLE. A route withheld while its token is still signed is permanent drift: the whole
# band flushed and rebuilt every sync, which is the packet-leaking churn the signature exists to prevent.
_sm = [{"subnet": SUB, "category": "v", "action": "exit", "via_iface": "eth2", "table": 7000,
        "gw": "", "_noroute": True}]
_want = N._cascade_want_sig([], [], _sm, guard=[{"subnet": SUB, "table": 7000, "scope": "rule"}])
check("⚠️ a routeless entry signs its RULE but not a route it will never install",
      "R|fwmark|7000|7000" in _want and not any(t.startswith("T|7000|default") for t in _want),
      sorted(_want))

print("\n[6] a gateway that MOVES is visible to the drift signature")
_f = lambda gw: [{"subnet": "10.17.0.0/24", "via_iface": "eth2", "table": 7000, "gw": gw}]
s_a = N._cascade_want_sig(_f("10.201.0.1"), [], [])
s_b = N._cascade_want_sig(_f("10.201.0.254"), [], [])
check("⚠️ a DHCP renewal that moves the gateway makes the wanted signature DIFFER",
      s_a != s_b, "signed the device but not the gateway: " + str(sorted(s_a)))
check("…and the same gateway signs the same", s_a == N._cascade_want_sig(_f("10.201.0.1"), [], []))
# The want and live readers are one grammar or they are two — and two means a permanent rebuild every
# sync, which is the packet-leaking churn the signature exists to prevent.
N.run = lambda argv, **kw: _R("default via 10.201.0.1 dev eth2 \n" if "route" in argv else
                              "7000:\tfrom 10.17.0.0/24 lookup 7000\n")
live = N._cascade_live_sig({"7000"})
check("the LIVE reader spells the installed route the same way the want reader does",
      "T|7000|default|eth2|10.201.0.1" in live, sorted(live))
check("…so a settled NIC exit does not flush and rebuild its band every sync",
      s_a <= live, "want: %s  live: %s" % (sorted(s_a), sorted(live)))
check("a point-to-point route still signs with an empty gateway on both sides",
      "T|7000|default|wgcf|" in N._cascade_want_sig(
          [{"subnet": "10.17.0.0/24", "via_iface": "wgcf", "table": 7000}], [], []))

print("\n[7] ⚠️ a gateway that STOPS RESOLVING is not a reason to withdraw the route")
# §3c T3, measured: with the route in place, gateway loss is a blackhole with +0 leak. Withdraw it and the
# table empties, the rule falls through to `main`, and the client egresses out the WAN. The route we are
# already running with IS the last-known-good, so nothing new has to be remembered to hold this line.
c, rep, _ = lower("eth2", True, "", live_via="10.201.0.1")
check("detection empty, a route already running: the exit keeps carrying traffic",
      "ip route replace default via 10.201.0.1 dev eth2 table 7000" in c, c)
check("…so the table never empties and there is nothing to fall through to `main`",
      any("route replace default via" in x for x in c), c)

print("")
if PERTURB or PSIG:
    what = "gatewayless lowering, the way it shipped" if PERTURB else "the gateway dropped from the signature"
    ok = len(FAILS) > 0
    print(("PERTURB OK (%s) — %d checks went red" % (what, len(FAILS))) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
