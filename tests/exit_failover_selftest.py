#!/usr/bin/env python3
"""Self-test for EXIT TUNNEL HEALTH — a tunnel that carries nothing is a FAILED exit, and the kill-switch decides.

What shipped before this: the node decided whether a device exit could carry traffic from `_dev_link_state`
alone — is the device there and up. The device of an IMPORTED exit (a WARP account, a pasted profile) stays
up when the far side dies. Measured in the field on 2026-09-15: a Cloudflare outage left both `wgx-*`
devices up, the kill-switch was OFF on both, and every client of four interfaces sat in a tunnel that
answered nobody until the operator disabled the exits by hand. "Kill-switch off ⇒ fall back to direct"
(decision 1) was unreachable for the one failure WARP actually has.

So the node now judges the TUNNEL (`_exit_judge`) and every reader that decides whether an exit device may
carry traffic asks `_devexit_state`, which reads `dead` for an up device whose tunnel is judged dead:

  [1] the verdict — the trace proves it cheaply; only when it fails is a second, non-Cloudflare probe
      asked, and only both failing counts; an unaskable probe moves nothing; hysteresis both ways.
  [2] `_devexit_state` — dead only for an UP device with a verdict; an adopted device reads as before.
  [3] the datapath through the real `reconcile_cascade` — dead is routed exactly like down: kill-switch
      OFF falls through to direct, ON installs the `prohibit` AND the rule that makes it reachable; a
      rule-scoped exit withholds its route but keeps its fwmark rule.
  [4] the drift signature moves the same pass the verdict does (no 60 s wait).
  [5] `reconcile_exits` reports `no_traffic` and a rebuilt tunnel starts unjudged.
  [6] the panel says what happened to the traffic, in words that differ by kill-switch.
  [7] a pass with several failing exits pays ONE device's timeouts: every live device is probed at once (measured on
      swgt 2026-09-18: one after another, four WARP exits in an outage stretched every pass 5 s → ~55 s, past the
      panel's 30 s offline threshold); a probe that raises or outlasts the bound is no evidence; verdicts stay in the
      calling thread.

Hermetic: `run()` is stubbed and argv inspected; the probes are injected; nothing touches the network.

Run: python3 tests/exit_failover_selftest.py            (0 = pass)
     --perturb             `_devexit_state` ignores the verdict — the shipped behaviour — expects RED
     --perturb-hysteresis  the 30 s window is dropped, so three quick failures fail over — expects RED in [1]
     --perturb-reach       the trace alone decides — a Cloudflare-only problem fails the tunnel — RED in [1]
     --perturb-serial      the exit probes run one device after another again — RED in [7]
     --perturb-bound       a probe that never answers holds the pass — RED in [7]
     --perturb-icmp        a ping takes any echo reply carrying its ident, whoever sent it — RED in [7]
     --perturb-finally     a later exit whose setup raises leaves the earlier ones unjudged — RED in [7]
     --perturb-evidence    a ping that overruns the bound takes the trace + reach evidence with it — RED in [7]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

# Each perturbation rewrites the SOURCE (a flag nothing reads would change nothing), anchored on an expression
# that must occur exactly once — a missing or duplicated anchor aborts rather than running a false green.
PLANTS = {
    "--perturb": ('return "dead" if s == "up" and (_EXIT_HEALTH.get(str(dev or "")) or {}).get("dead") else s',
                  "return s"),
    "--perturb-hysteresis": ('and now - st["fail_since"] >= EXIT_DEAD_AFTER_S):', "):"),
    "--perturb-reach": ('carried = True if (tr or {}).get("ip") else (reach or _exit_reach)(dev)',
                        'carried = bool((tr or {}).get("ip"))'),
    "--perturb-serial": ("    for t in ths:\n        t.start()\n", "    for t in ths:\n        t.start(); t.join()\n"),
    "--perturb-bound": ("        t.join(max(0.0, end - time.monotonic()))\n", "        t.join()\n"),
    "--perturb-icmp": ("if typ == 0 and rid == ident and frm[0] == ip:", "if typ == 0 and rid == ident:"),
    "--perturb-finally": ("    finally:\n        # ⚠️ IN A `finally`: a later exit",
                          "    except BaseException:\n        raise\n    if True:\n        # ⚠️ IN A `finally`: a later exit"),
    "--perturb-evidence": ("        res[dev] = (tr, rch, None)", "        pass"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

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

if MODE:
    _src = open(NODED, encoding="utf-8").read()
    _cut, _new = PLANTS[MODE]
    assert _src.count(_cut) == 1, "perturbation anchor for %s is missing or not unique — would FALSE-PASS" % MODE
    _tmp = os.path.join(HERE, ".perturbed-noded-failover.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, _new, 1))
    N = _load(_tmp, "swgnoded")
    os.unlink(_tmp)
else:
    N = _load(NODED, "swgnoded")
P = _load(PANEL, "swgpanel")
_REAL_PING = N._exit_ping          # the real one, before any section stubs it

class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc

D = "wgx-aabbccdd"
OK = {"ip": "104.28.222.16", "warp": "on", "loc": "FI"}
BAD = {"err": "TimeoutError: timed out"}
_asked = []
def reach(v):
    def f(dev):
        _asked.append(dev)
        return v
    return f
def judge(tr, now, r):
    return N._exit_judge(D, tr, now=now, reach=reach(r))

# ── 1. the verdict ────────────────────────────────────────────────────────────────────────────────
N._EXIT_HEALTH.clear(); _asked.clear()
st = judge(OK, 1000, False)
check("a trace that crossed the tunnel is enough — the second probe is never asked", not _asked and not st["dead"],
      (_asked, st))

N._EXIT_HEALTH.clear()
for t in (0, 10, 20):
    st = judge(BAD, t, False)
check("three failed passes inside 20 s do NOT fail the exit over — a blip must not publish the node's IP",
      not st["dead"], st)
st = judge(BAD, 30, False)
check("…the next one, 30 s after the first failure, does", st["dead"], st)
check("…and the reason given is the trace's own words", st["why"] == "TimeoutError: timed out", st)

N._EXIT_HEALTH.clear()
judge(BAD, 0, False)
st = judge(BAD, 45, False)
check("45 s of failure seen by only TWO passes is not enough evidence — a stalled loop is not a dead tunnel",
      not st["dead"], st)

N._EXIT_HEALTH.clear()
for t in range(0, 120, 10):
    st = judge(BAD, t, True)
check("the trace failing while another network answers THROUGH the tunnel is not a dead tunnel "
      "(www.cloudflare.com alone, or the node's resolver, being down)", not st["dead"], st)

N._EXIT_HEALTH.clear()
for t in (0, 10, 20):
    judge(BAD, t, False)
for t in (30, 60, 90):
    st = judge(BAD, t, None)
check("a probe that could not be made moves nothing — being unable to ask is not a failure",
      not st["dead"] and st["fails"] == 3, st)

N._EXIT_HEALTH.clear()
for t in (0, 10, 20, 30):
    judge(BAD, t, False)
st = judge(OK, 40, False)
check("one good pass does not move traffic back into a tunnel that just failed", st["dead"], st)
judge(BAD, 70, False)
judge(OK, 80, False)
st = judge(OK, 130, False)
check("a failure in between restarts the recovery clock", st["dead"], st)
st = judge(OK, 140, False)
check("60 s of carrying traffic again moves it back, and clears the reason", not st["dead"] and st["why"] == "", st)

# ── 2. _devexit_state ─────────────────────────────────────────────────────────────────────────────
_REAL_LINK = N._dev_link_state
N._EXIT_HEALTH.clear()
N._EXIT_HEALTH[D] = {"dead": True, "fail_since": 0, "fails": 9, "ok_since": None, "since": 0, "why": "x"}
N._dev_link_state = lambda d: "up"
check("an UP device whose tunnel is judged dead reads dead", N._devexit_state(D) == "dead", N._devexit_state(D))
check("a device with no verdict — an adopted one — reads exactly its link state", N._devexit_state("eth9") == "up")
N._dev_link_state = lambda d: "absent"
check("a device that is gone reads absent, whatever verdict it last had", N._devexit_state(D) == "absent")

# ── 3. the datapath ───────────────────────────────────────────────────────────────────────────────
ROUTE = "ip route replace default dev wgcf table 7000"
RULE = "ip rule add from 10.17.0.0/24 lookup 7000 priority 7000"
FWM = "ip rule add fwmark 7000 lookup 7000 priority 7000"
GUARD = "ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC

def lower(dead, ks, scope=None):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: "up"
    N._EXIT_HEALTH.clear()
    if dead:
        N._EXIT_HEALTH["wgcf"] = {"dead": True, "fail_since": 0, "fails": 9, "ok_since": None, "since": 0, "why": "x"}
    N._DEVEXIT["list"] = []
    ent = {"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": ks}
    smart = None
    if scope:
        ent["scope"] = scope
        smart = {"entries": [{"subnet": "10.17.0.0/24", "category": "netflix", "action": "exit",
                              "via_iface": "wgcf", "table": 7000}], "categories": ["netflix"]}
    N.reconcile_cascade({"interfaces": {}}, {"devexit": [ent]}, smart, "")
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"], list(N._DEVEXIT["list"])

c, rep = lower(False, False)
check("control: a live tunnel keeps its route (nothing about a healthy exit changes)", ROUTE in c and RULE in c, c)
c, rep = lower(True, False)
check("DEAD tunnel, kill-switch OFF: no route into it", ROUTE not in c, c)
check("DEAD tunnel, kill-switch OFF: no prohibit either — traffic falls through to direct", GUARD not in c, c)
check("…and the node reports the state as dead", [e.get("state") for e in rep] == ["dead"], rep)
c, rep = lower(True, True)
check("DEAD tunnel, kill-switch ON: the prohibit backstop is installed", GUARD in c, c)
check("DEAD tunnel, kill-switch ON: …with the from-rule that makes it reachable", RULE in c, c)
check("DEAD tunnel, kill-switch ON: no route into the dead tunnel", ROUTE not in c, c)
c, rep = lower(False, True, scope="rule")
check("control: a rule-scoped live tunnel keeps its route", ROUTE in c and FWM in c, c)
c, rep = lower(True, True, scope="rule")
check("rule-scoped DEAD tunnel: its route is withheld (an UP device would otherwise take it)", ROUTE not in c, c)
check("rule-scoped DEAD tunnel: …the fwmark rule stays, so the kill-switch is still reachable", FWM in c, c)
check("rule-scoped DEAD tunnel: …and still no from-rule dragging the whole subnet in", RULE not in c, c)
_ent = {"subnet": "10.17.0.0/24", "category": "netflix", "action": "exit", "via_iface": "wgcf", "table": 7000}
check("the signature does not sign the withheld route (else the band rebuilds every sync)",
      "T|7000|default|wgcf|" not in N._cascade_want_sig([], [], [dict(_ent, _noroute=True)]))

# ── 4. the drift signature ────────────────────────────────────────────────────────────────────────
_CAS = {"devexit": [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": False}]}
N._dev_link_state = lambda d: "up"
N._dev_gateway = lambda d, *a, **k: ""
N._EXIT_HEALTH.clear()
_alive = N._devexit_sig(_CAS)
N._EXIT_HEALTH["wgcf"] = {"dead": True, "fail_since": 0, "fails": 9, "ok_since": None, "since": 0, "why": "x"}
_dead = N._devexit_sig(_CAS)
check("a tunnel judged dead changes the routing signature, so the same sync acts on it", _alive != _dead,
      (_alive, _dead))

# ── 5. reconcile_exits reports it ─────────────────────────────────────────────────────────────────
WARP = {"priv": "cHJpdmF0ZS1rZXktcHJpdmF0ZS1rZXktcHJpdmF0ZS0=", "pub": "cHVia2V5LXB1YmtleS1wdWJrZXktcHVia2V5LXB1Yms=",
        "address": "172.16.0.2", "peer_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
        "endpoint": "engage.cloudflareclient.com:2408", "account_id": "acc", "token": "tok", "account_type": "free"}
N.EXIT_DIR = tempfile.mkdtemp()
_calls = []
N.run = lambda a, **k: (_calls.append(" ".join(map(str, a))), _R(""))[1]
N._dev_link_state = lambda d: "up" if any(" up " in x for x in _calls) else "absent"
N._warp_register = lambda: (dict(WARP), "")
N._exit_trace = lambda d: dict(BAD)
N._exit_reach = lambda d, *a, **k: False
N._exit_handshake = lambda rec, dev: 0
N._exit_ping = lambda ep, *a, **k: None
N.EXIT_DEAD_AFTER_S, N.EXIT_DEAD_MIN_PROBES = 0, 2
N._EXIT_HEALTH.clear()
_want = [{"id": "aabbccdd", "device": D, "provider": "warp"}]
N.reconcile_exits(_want, {"changed": 0, "errors": []})
_r1 = next(x for x in N._EXITS["list"] if x["id"] == "aabbccdd")
check("first failed pass: not reported yet (hysteresis)", _r1.get("no_traffic") is None, _r1)
N.reconcile_exits(_want, {"changed": 0, "errors": []})
_r2 = next(x for x in N._EXITS["list"] if x["id"] == "aabbccdd")
check("once judged dead, the exit's report carries no_traffic with the reason",
      isinstance(_r2.get("no_traffic"), dict) and _r2["no_traffic"].get("why") == BAD["err"], _r2)
check("…and the routing reads the same verdict", N._devexit_state(D) == "dead", N._devexit_state(D))
_calls.clear()
N._dev_link_state = lambda d: "up" if any(" up " in x for x in _calls) else "absent"
N._exit_trace = lambda d: dict(OK)
N.reconcile_exits(_want, {"changed": 0, "errors": []})
check("a tunnel rebuilt this pass is judged from scratch, not dead by inheritance",
      N._devexit_state(D) == "up" and next(x for x in N._EXITS["list"] if x["id"] == "aabbccdd").get("no_traffic")
      is None, N._EXIT_HEALTH.get(D))

# ── 7. several failing exits cost one device's timeouts, not the sum ─────────────────────────────────────
import threading, time as _t
_calls.clear()
N.EXIT_DIR = tempfile.mkdtemp()
N._dev_link_state = lambda d: "up" if any((" up " in x and d in x) for x in _calls) else "absent"
_SLOW = {"trace": 0.8, "reach": 0.3, "ping": 0.2}          # 1.3 s a device: four in a row = 5.2 s, together ≈ 1.3 s
_raise, _stall, _judged_in = set(), set(), set()
def _trace7(d):
    if d in _raise:
        raise OSError("probe blew up")
    _t.sleep(3.0 if d in _stall else _SLOW["trace"]); return dict(BAD)
N._exit_trace = _trace7
N._exit_reach = lambda d, *a, **k: (_t.sleep(_SLOW["reach"]), False)[1]
N._exit_ping = lambda ep, *a, **k: (_t.sleep(_SLOW["ping"]), None)[1]
_real_judge = N._exit_judge
def _judge7(*a, **k):
    _judged_in.add(threading.current_thread() is threading.main_thread())
    return _real_judge(*a, **k)
N._exit_judge = _judge7
N.EXIT_DEAD_AFTER_S, N.EXIT_DEAD_MIN_PROBES = 0, 2
N._EXIT_HEALTH.clear()
_w7 = [{"id": "a%07d" % i, "device": "wgx-a%07d" % i, "provider": "warp"} for i in range(1, 5)]
N.reconcile_exits(_w7, {"changed": 0, "errors": []})         # pass 1 builds the four tunnels (their probes included)
_t0 = _t.time(); N.reconcile_exits(_w7, {"changed": 0, "errors": []}); _dt = _t.time() - _t0
_rows = {x["id"]: x for x in N._EXITS["list"]}
check("four failing exits: the pass pays one device's timeouts (%.1f s; one after another would be 5.2 s)" % _dt,
      _dt < 2.6, _dt)
check("…every one of them is still reported and judged (dead after its second failing pass)",
      all((_rows.get(x["id"]) or {}).get("no_traffic") for x in _w7) and [x["id"] for x in N._EXITS["list"]] == [x["id"] for x in _w7],
      [(k, v.get("no_traffic")) for k, v in _rows.items()])
check("…and every verdict was taken in the calling thread (_EXIT_HEALTH is never touched by a probe thread)",
      _judged_in == {True}, _judged_in)
N._EXIT_HEALTH.clear(); _raise.add("wgx-a0000002"); _stall.add("wgx-a0000003"); N.EXIT_PROBE_BOUND_S = 1.5
_t0 = _t.time(); N.reconcile_exits(_w7, {"changed": 0, "errors": []}); _dt = _t.time() - _t0
_rows = {x["id"]: x for x in N._EXITS["list"]}
check("a probe that raises and one that outlasts the bound cost the pass no more than the bound (%.1f s)" % _dt, _dt < 2.2, _dt)
check("…each is no evidence: reported, trace empty, its verdict untouched — the others judged as usual",
      _rows["a0000002"]["trace"] == {} and _rows["a0000003"]["trace"] == {}
      and all(not (N._EXIT_HEALTH.get(d) or {}).get("fails") and not (N._EXIT_HEALTH.get(d) or {}).get("dead")
              for d in ("wgx-a0000002", "wgx-a0000003"))
      and N._EXIT_HEALTH["wgx-a0000001"]["fails"] == 1 and N._EXIT_HEALTH["wgx-a0000004"]["fails"] == 1,
      ({k: v["trace"] for k, v in _rows.items()}, {k: v.get("fails") for k, v in N._EXIT_HEALTH.items()}))
# a ping that overruns the bound loses only itself: the trace + reach evidence is already recorded
N._EXIT_HEALTH.clear(); _raise.clear(); _stall.clear(); N.EXIT_PROBE_BOUND_S = 1.5
N._exit_ping = lambda ep, *a, **k: (_t.sleep(4.0), None)[1]
N.reconcile_exits(_w7, {"changed": 0, "errors": []})
check("a ping that overruns the bound does not cost the verdict its evidence (every device counted its failure)",
      all((N._EXIT_HEALTH.get(x["device"]) or {}).get("fails") == 1 for x in _w7),
      {k: v.get("fails") for k, v in N._EXIT_HEALTH.items()})
# a later exit whose setup raises: the exits before it are still judged that pass (and the exception still propagates)
N._EXIT_HEALTH.clear(); N.EXIT_PROBE_BOUND_S = 40
N._exit_ping = lambda ep, *a, **k: None
_real_link = N._dev_link_state
def _link_boom(d):
    if d == "wgx-a0000003":
        raise ValueError("a malformed exit state")
    return _real_link(d)
N._dev_link_state = _link_boom
_boom = None
try:
    N.reconcile_exits(_w7, {"changed": 0, "errors": []})
except Exception as e:
    _boom = e
check("a later exit whose setup raises: the ones before it are still judged, and the exception still propagates",
      isinstance(_boom, ValueError) and all((N._EXIT_HEALTH.get(d) or {}).get("fails") == 1 for d in ("wgx-a0000001", "wgx-a0000002")),
      (_boom, {k: v.get("fails") for k, v in N._EXIT_HEALTH.items()}))
N._dev_link_state = _real_link
N._exit_judge = _real_judge

# concurrent pings: every raw ICMP socket gets EVERY echo reply, so a probe must take only its own, from its own server
import types
_real_sock_mod, _real_sel_mod = N.socket, N.select
class _FakeIcmp:
    def __init__(s, *a): s.q, s.t0 = [], None
    def settimeout(s, t): pass
    def sendto(s, pkt, addr):
        s.ident = int.from_bytes(pkt[4:6], "big"); s.t0 = _t.monotonic()
        ihdr = bytes([0x45]) + bytes(19)                  # a 20-byte IPv4 header, as a raw socket hands it over
        rep = lambda rid: ihdr + bytes([0, 0, 0, 0]) + rid.to_bytes(2, "big") + (1).to_bytes(2, "big")
        s.q = [(0.0, rep(s.ident), ("198.51.100.9", 0)),          # ANOTHER exit's server answering first, same ident
               (0.0, rep((s.ident + 1) & 0xFFFF), (addr[0], 0)),  # our server, someone else's ident
               (0.06, rep(s.ident), (addr[0], 0))]               # ours: 60 ms
    def recvfrom(s, n):
        at, d, frm = s.q.pop(0)
        _t.sleep(max(0.0, s.t0 + at - _t.monotonic())); return d, frm
    def close(s): pass
N.socket = types.SimpleNamespace(socket=_FakeIcmp, AF_INET=2, SOCK_RAW=3, IPPROTO_ICMP=1, gethostbyname=lambda h: h)
N.select = types.SimpleNamespace(select=lambda r, w, x, t: (r, [], []))
try:
    _ms = _REAL_PING("203.0.113.7:2408")
finally:
    N.socket, N.select = _real_sock_mod, _real_sel_mod
check("a ping takes only ITS echo reply, from the server it pinged — not another exit's (%s ms)" % _ms,
      _ms is not None and _ms >= 55, _ms)

# ── 6. the panel ──────────────────────────────────────────────────────────────────────────────────
def issues(ks):
    node = {"name": "n1",
            "exits": [{"id": "aabbccdd", "label": "WARP", "device": "wgcf", "enabled": True, "killswitch": ks}],
            "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"}}}
    snap = {"devexit": [{"dev": "wgcf", "subnet": "10.17.0.0/24", "state": "dead", "killswitch": ks}]}
    return [i["error"] for i in P._node_issues(node, snap)]
_off = issues(False)
check("dead, kill-switch OFF: one line saying the traffic is going out through the node's own IP",
      len(_off) == 1 and "stopped carrying traffic" in _off[0] and "node's own IP" in _off[0], _off)
check("…and never the down-device advice to 'bring it up' (the device is fine)",
      _off and "Bring" not in _off[0] and "is down" not in _off[0], _off)
_on = issues(True)
check("dead, kill-switch ON: says the kill-switch is holding it, never that it went direct",
      len(_on) == 1 and "kill-switch is holding" in _on[0] and "own IP" not in _on[0], _on)

N._dev_link_state = _REAL_LINK

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
