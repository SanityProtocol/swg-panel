#!/usr/bin/env python3
"""Self-test: a relay's upstream can name ITS OWN LEG, which is what lets it later name a different one.

A client's packet picks its leg one of two ways — a smart cascade marks it with the table, and a whole-
interface cascade is routed by its SOURCE. The second could never be overridden: `ip rule` uses
priority == table number for both kinds, so `from <subnet> lookup T'` outranks every mark rule whose table
is numerically greater, and the relay's upstream is deliberately sourced from that very subnet (`--bind gw`,
so the exit's SNAT matches). A forward interface's relay therefore had exactly one possible egress: its
interface's own.

⚠️ THE FIX IS A SECOND MARK, NOT A MOVED ONE. Re-homing the existing `fwmark T` rules below the band would
have worked for the relay and quietly changed precedence for CLIENT traffic — the exit side's
`to <client subnet> lookup T` rules also sit at priority T, and a smart-marked packet addressed to another
node's client subnet takes that `to` rule today. So client marking stays exactly where it is, and legs get a
SECOND name that nothing but this feature ever sets: the band at SWG_RT_UP_BASE, below every source rule.

MEASURED on msk-main before any of this was written (wg8 = forward to table 7001, second leg at 7000):
    from 10.18.0.1 mark 0     -> table 7001     the source rule
    from 10.18.0.1 mark 6891  -> table 7001     its own leg, asked for by name
    from 10.18.0.1 mark 6890  -> table 7000     ANOTHER LEG — unreachable by any mark before

Auto-failover, load balancing and pick-the-fastest all reduce to "make the upstream go somewhere the
client's own rule did not say", so `mark` (which packets to divert) and `up_mark` (which leg to leave by)
are two fields on purpose, even though today every leg the panel emits sets them to the same leg.

Hermetic: no network, no root, no state dir. Both programs are loaded and compared directly.

Run: python3 tests/relay_upmark_selftest.py   (0 = pass)
     --perturb-band      makes the upstream mark the table itself (the old collision)  → RED
     --perturb-somark    sends the DIVERT mark to the socket instead of the upstream's → RED
     --perturb-divert    scopes the divert by the upstream mark                        → RED
     --perturb-flush     flushes a table by an upstream PRIORITY                       → RED
     --perturb-sig       stops the signature seeing the upstream rules                 → RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
P_BAND = "--perturb-band" in sys.argv
P_SOMARK = "--perturb-somark" in sys.argv
P_DIVERT = "--perturb-divert" in sys.argv
P_FLUSH = "--perturb-flush" in sys.argv
P_SIG = "--perturb-sig" in sys.argv
PERTURB = P_BAND or P_SOMARK or P_DIVERT or P_FLUSH or P_SIG

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

nsrc = open(NODED, encoding="utf-8").read()
psrc = open(PANEL, encoding="utf-8").read()
def cut(src, a, b, why):
    assert src.count(a) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % why
    return src.replace(a, b, 1)

if P_BAND:      # the collision the band exists to avoid: name the leg with the table itself
    nsrc = cut(nsrc, "    return SWG_RT_UP_BASE + (t - SWG_RT_BASE) if SWG_RT_BASE <= t <= SWG_RT_MAX else 0",
               "    return t if SWG_RT_BASE <= t <= SWG_RT_MAX else 0", "node up_mark")
    psrc = cut(psrc, "    return SWG_RT_UP_BASE + (t - SWG_RT_BASE) if SWG_RT_BASE <= t <= SWG_RT_MAX else 0",
               "    return t if SWG_RT_BASE <= t <= SWG_RT_MAX else 0", "panel up_mark")
if P_SOMARK:
    nsrc = cut(nsrc, 'int(e.get("up") or 0)))', 'int(e.get("mark") or 0)))', "env so_mark")
if P_DIVERT:
    nsrc = cut(nsrc, '"mark": want[iface]["mark"], "iid": iface})', '"mark": want[iface]["up"], "iid": iface})', "divert scope")
if P_FLUSH:
    nsrc = cut(nsrc, "    return [p for p in prios if SWG_RT_BASE <= p <= SWG_RT_MAX]", "    return list(prios)", "flush set")
if P_SIG:
    nsrc = cut(nsrc, "            if mfw and _up:", "            if False:", "live sig")

def load(name, path, src, changed):
    if changed:
        fd, path = tempfile.mkstemp(suffix=".py", prefix="upmark-", dir=HERE)
        os.write(fd, src.encode("utf-8")); os.close(fd)
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    finally:
        if changed:
            os.unlink(path)
    return m

N = load("noded_up", NODED, nsrc, P_BAND or P_SOMARK or P_DIVERT or P_FLUSH or P_SIG)
P = load("panel_up", PANEL, psrc, P_BAND)

print("[1] the band is below every source rule, and collides with nothing")
check("it starts below SWG_RT_BASE", N.SWG_RT_UP_MAX < N.SWG_RT_BASE, (N.SWG_RT_UP_BASE, N.SWG_RT_UP_MAX))
check("…with a slot for every table", N.SWG_RT_UP_MAX - N.SWG_RT_UP_BASE == N.SWG_RT_MAX - N.SWG_RT_BASE)
check("⚠️ …and it does not swallow the relay's own divert rule",
      not (N.SWG_RT_UP_BASE <= N.RELAY_RT <= N.SWG_RT_UP_MAX),
      "RELAY_RT %d inside [%d, %d] would make the signature drift for ever" % (N.RELAY_RT, N.SWG_RT_UP_BASE, N.SWG_RT_UP_MAX))
check("…nor the relay's divert MARK", not (N.SWG_RT_UP_BASE <= N.RELAY_MARK <= N.SWG_RT_UP_MAX))
check("…nor the torrent connmark", not (N.SWG_RT_UP_BASE <= N.TORRENT_MARK <= N.SWG_RT_UP_MAX))
check("a table maps to a distinct mark", N._up_mark(7000) != 7000 and N._up_mark(7000) < N.SWG_RT_BASE, N._up_mark(7000))
check("…and a table outside our band maps to nothing",
      N._up_mark(0) == 0 and N._up_mark(7100) == 0 and N._up_mark(6999) == 0)

print("\n[2] ⚠️ the SEAM — the panel names the leg the node installs")
for t in (7000, 7001, 7042, 7099):
    check("table %d agrees" % t, P._up_mark(t) == N._up_mark(t), (P._up_mark(t), N._up_mark(t)))
check("…and both refuse the same non-tables", P._up_mark(6999) == N._up_mark(6999) == 0)

print("\n[3] the node installs one upstream rule per leg it can send out of")
FWD = [{"subnet": "10.18.0.0/24", "via_iface": "swg_a", "table": 7001}]
SMART = [{"subnet": "10.19.0.0/24", "via_iface": "swg_b", "table": 7000, "category": "media"}]
EXIT = [{"subnet": "10.9.0.0/24", "via_iface": "swg_c", "table": 7002}]
want = N._cascade_want_sig(FWD, EXIT, SMART)
check("the forward leg gets one", "R|upmark|%d|7001" % N._up_mark(7001) in want, sorted(x for x in want if "upmark" in x))
check("…and so does the smart leg", "R|upmark|%d|7000" % N._up_mark(7000) in want, sorted(x for x in want if "upmark" in x))
check("⚠️ …and an EXIT table does NOT", not any("|7002" in x and "upmark" in x for x in want),
      "those tables carry other nodes' clients home; this node never originates into them")
check("…the source rule it used to depend on is still there", "R|from|10.18.0.0/24|7001" in want, sorted(want))
check("…and the client-side mark rule has not moved", "R|fwmark|7000|7000" in want, sorted(want))

print("\n[4] a priority in the upstream band is NOT a table id")
band = [7000, 7001, N._up_mark(7000), N._up_mark(7001)]
check("teardown reaps both bands", sorted(N._band_tables(band)) == [7000, 7001],
      "%s — flushing `table %d` would be flushing something we never wrote" % (N._band_tables(band), N._up_mark(7000)))

print("\n[5] two marks, two jobs — the divert's and the upstream's")
FWD_LEG = {"subnet": "10.18.0.0/24", "port": 5629, "iface": "wg8", "peer": "", "mark": 0, "iid": "wg8"}
nft = N._relay_nft([FWD_LEG])
tproxy = [l for l in nft.splitlines() if "tproxy" in l]
check("⚠️ a cascade's divert still names the SUBNET, not a mark",
      tproxy and not any("meta mark 0x" in l.split("tproxy")[0] for l in tproxy),
      "%s — nothing marks a forwarded packet, so a mark match here diverts nothing at all" % tproxy)
env = N._relay_env_text("wg8", {"port": 5629, "gw": "10.18.0.1", "mss": 1340, "mark": 0, "up": N._up_mark(7001)})
check("…while the SOCKET asks for its leg by name", ("RELAY_MARK=%d" % N._up_mark(7001)) in env, env)
check("⚠️ …which is NOT the divert's mark", "RELAY_MARK=0" not in env, env)

print("\n[6] the panel emits both, and forward is the case that gains")
NODES = {"n1": {"name": "entry",
                "links": {"n2": {"iface": "swg_a2", "relay": {"mode": "relay"}},
                          "n3": {"iface": "swg_a3", "relay": {"mode": "relay"}}},
                "ifaces": {"wg8": {"egress_mode": "forward", "egress_node": "n2"},
                           "wg9": {"egress_mode": "smart",
                                   "routing": [{"enabled": True, "category": "media", "action": "exit", "node": "n3"}]}}},
         "n2": {"name": "b", "links": {"n1": {"iface": "swg_b1", "peer_address": "10.255.0.1"}}},
         "n3": {"name": "c", "links": {"n1": {"iface": "swg_c1", "peer_address": "10.255.1.1"}}}}
SNAP = {"n1": {"interfaces": {"wg8": {"meta": {"subnet": "10.18.0.0/24"}},
                              "wg9": {"meta": {"subnet": "10.19.0.0/24"}}}}}
plans = P.cascade_plan(NODES, SNAP)
plan = P.relay_plan(NODES, plans, "n1", SNAP)
legs = {l["iface"]: l for l in (plan.get("legs") or [])}
check("a forward interface's leg is recorded at all", any(l.get("mode") == "forward" for l in plans["n1"]["_legs"]),
      plans["n1"]["_legs"])
check("⚠️ the forward leg keeps divert mark 0", legs.get("wg8", {}).get("mark") == 0, legs.get("wg8"))
check("⚠️ …and gains an upstream mark in the band",
      N.SWG_RT_UP_BASE <= legs.get("wg8", {}).get("up_mark", 0) <= N.SWG_RT_UP_MAX, legs.get("wg8"))
check("…naming its OWN leg today", legs.get("wg8", {}).get("up_mark") == P._up_mark(7000), legs.get("wg8"))
check("the smart leg names its leg the same way",
      legs.get("wg9", {}).get("up_mark") == P._up_mark(legs.get("wg9", {}).get("mark", 0)), legs.get("wg9"))

print("\n[7] the node reads it, and an older panel still works")
def derive(leg):
    e = dict(leg or {}); e["mark"] = int(e.get("mark") or 0)
    e["up"] = int(e.get("up_mark") or 0) or e["mark"]
    return e
check("both legs survived into the plan (else nothing below is tested)", "wg8" in legs and "wg9" in legs, sorted(legs))
_w8, _w9 = legs.get("wg8") or {}, legs.get("wg9") or {}
check("a leg with an upstream mark uses it", derive(_w8)["up"] == P._up_mark(7000))
_old = {k: v for k, v in _w8.items() if k != "up_mark"}
check("⚠️ …and one WITHOUT falls back to the divert mark", derive(_old)["up"] == 0,
      "a cascade from a panel too old to send one must keep being routed by its bind address")
_olds = {k: v for k, v in _w9.items() if k != "up_mark"}
check("…which for a smart leg is its own table", bool(_w9) and derive(_olds)["up"] == _w9.get("mark"))

print("\n[8] the guard, and the reason it is kept rather than deleted")
RULES = ["0:\tfrom all lookup local",
         "7000:\tfrom 10.18.0.0/24 lookup 7000",
         "7001:\tfrom all fwmark 0x1b59 lookup 7001",
         "32766:\tfrom all lookup main"]
_up = N._relay_shadowed([{"iid": "wg8", "subnet": "10.18.0.0/24", "mark": N._up_mark(7001)}], RULES)
check("⚠️ an upstream mark cannot be shadowed — its rule is below the whole band", _up == {}, _up)
_legacy = N._relay_shadowed([{"iid": "wg8", "subnet": "10.18.0.0/24", "mark": 7001}], RULES)
check("…while a legacy table-shaped mark still is, and says why", "wg8" in _legacy, _legacy)
check("…naming the rule that outranks it", _legacy and "7000" in _legacy["wg8"], _legacy)

print("\n[9] ⚠️ THE CAPABILITY: the upstream can name a leg the interface never uses")
# This is the whole point, and it is the thing that was impossible before. wg8 forwards to table 7000; its
# relay is pointed at 7001, the OTHER leg. The contract has to be able to say that at all.
_other = dict(_w8, up_mark=P._up_mark(7001))
check("the contract expresses it", derive(_other)["up"] == P._up_mark(7001) != derive(_w8)["up"])
check("…and it is still a legal mark", P._relay_ineligible({}, 0, derive(_other)["up"]) == "")
check("…while a mark outside the band is refused with a reason",
      bool(P._relay_ineligible({}, 0, 7001)) and bool(P._relay_ineligible({}, 0, N.SWG_RT_UP_BASE - 1)),
      "a mark no rule looks up routes by bind address instead — it WORKS, so nothing would say otherwise")

print("\n[10] the two halves the fixtures above route around")
# ⚠️ WRITTEN BECAUSE TWO PERTURBATIONS PASSED WITH ZERO CHECKS RED. `_relay_nft` is fed a hand-built
# entry here, so perturbing the line in `reconcile_relay` that BUILDS that entry changed nothing this gate
# could see; and every signature check above calls the WANT side, so blinding the LIVE side was invisible
# too. A perturbation that matches nothing is a gate asserting a failure mode it cannot detect.
_rr = nsrc[nsrc.index("def reconcile_relay("):]
_rr = _rr[:_rr.index("\ndef ")]
check("the divert entry is built from the DIVERT mark", '"mark": want[iface]["mark"]' in _rr,
      "scoping it by the upstream mark would put a mark match on a cascade's divert, which matches nothing")
check("…and the upstream mark is what reaches the socket", 'e["up"]' in _rr or '"up"' in _rr)

# The LIVE signature, driven through the same `ip rule show` parse the node uses.
_saved = N.run
N.run = lambda argv, **kw: type("R", (), {"stdout": (
    "0:\tfrom all lookup local\n"
    "%d:\tfrom all fwmark 0x%x lookup 7001\n"
    "%d:\tfrom all fwmark 0x%x lookup 6990\n"
    "7000:\tfrom all fwmark 0x1b58 lookup 7000\n"
    "7001:\tfrom 10.18.0.0/24 lookup 7001\n"
    "32766:\tfrom all lookup main\n"
    % (N._up_mark(7001), N._up_mark(7001), N.RELAY_RT, N.RELAY_MARK)) if argv[:3] == ["ip", "rule", "show"]
    else "", "returncode": 0})()
try:
    live = N._cascade_live_sig(set())
finally:
    N.run = _saved
check("the live signature SEES an upstream rule", "R|upmark|%d|7001" % N._up_mark(7001) in live, sorted(live),)
check("…told apart from a client-side mark", "R|fwmark|7000|7000" in live and "R|fwmark|%d|7001" % N._up_mark(7001) not in live,
      sorted(live))
check("⚠️ …and the relay's own divert rule is NOT in it",
      not any("6990" in x for x in live),
      "a token the want set can never carry means permanent drift — the whole band rebuilt every sync")

bad = len(FAILS)
if PERTURB:
    which = ("the upstream mark colliding with the table" if P_BAND else
             "the divert's mark sent to the socket" if P_SOMARK else
             "the divert scoped by the upstream mark" if P_DIVERT else
             "a table flushed by an upstream priority" if P_FLUSH else
             "the signature blind to the upstream rules")
    print("\n--perturb (%s): %d check(s) RED" % (which, bad))
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
