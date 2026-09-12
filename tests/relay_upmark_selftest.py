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
     --perturb-docker    launches the container relay with the DIVERT mark              → RED
     --perturb-dspec     drops `up` from the container's recreate signature             → RED
     --perturb-tbl       feeds upstream priorities to the drift check as table ids      → RED
     --perturb-guard     arms a leg whose routing rule was never installed               → RED
     --perturb-sweep     sweeps only in-memory state, so a restart stops nothing         → RED
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
P_DOCKER = "--perturb-docker" in sys.argv
P_DSPEC = "--perturb-dspec" in sys.argv
P_TBL = "--perturb-tbl" in sys.argv
P_GUARD = "--perturb-guard" in sys.argv
P_SWEEP = "--perturb-sweep" in sys.argv
PERTURB = (P_BAND or P_SOMARK or P_DIVERT or P_FLUSH or P_SIG or P_DOCKER or P_DSPEC or P_TBL or P_GUARD
           or P_SWEEP)

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
if P_SWEEP:     # the shape it shipped in: the stop-sweep walks only this process's own memory
    nsrc = cut(nsrc, "    for iface in sorted((set(_RELAY) | _relay_existing()) - set(want)):\n        run([\"sh\", \"-c\", \"systemctl disable --now \"",
               "    for iface in [i for i in _RELAY if i not in want]:\n        run([\"sh\", \"-c\", \"systemctl disable --now \"", "systemd sweep")
if P_GUARD:     # the shape it was first written in: refuse on the rule's ABSENCE, not on where it would go
    nsrc = cut(nsrc, "            if _falls_to == _want_tbl:\n                continue",
               "            if False:\n                continue", "guard falls-to")
if P_SOMARK:
    nsrc = cut(nsrc, 'int(e.get("up") or 0)))', 'int(e.get("mark") or 0)))', "env so_mark")
if P_DIVERT:
    nsrc = cut(nsrc, '"mark": want[iface]["mark"], "iid": iface})', '"mark": want[iface]["up"], "iid": iface})', "divert scope")
if P_FLUSH:
    nsrc = cut(nsrc, "    return [p for p in prios if SWG_RT_BASE <= p <= SWG_RT_MAX]", "    return list(prios)", "flush set")
if P_SIG:
    nsrc = cut(nsrc, "            if mfw and _up:", "            if False:", "live sig")
if P_DOCKER:   # the shape it shipped in: two run-models, two contracts
    nsrc = cut(nsrc, '"--bind", e["gw"], "--mark", str(int(e.get("up") or 0)),',
               '"--bind", e["gw"], "--mark", str(int(e.get("mark") or 0)),', "docker argv")
if P_DSPEC:
    nsrc = cut(nsrc, '"mark": int(e.get("mark") or 0), "up": int(e.get("up") or 0),',
               '"mark": int(e.get("mark") or 0),', "docker spec")
if P_TBL:
    nsrc = cut(nsrc, "    live_sig = _cascade_live_sig({str(p) for p in _band_tables(band)} | want_tables)",
               "    live_sig = _cascade_live_sig({str(p) for p in band} | want_tables)", "live sig tables")

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

N = load("noded_up", NODED, nsrc, P_BAND or P_SOMARK or P_DIVERT or P_FLUSH or P_SIG or P_DOCKER
             or P_DSPEC or P_TBL or P_GUARD or P_SWEEP)
P = load("panel_up", PANEL, psrc, False)

print("[1] the band is below every source rule, and collides with nothing")
check("it starts below SWG_RT_BASE", N.SWG_RT_UP_MAX < N.SWG_RT_BASE, (N.SWG_RT_UP_BASE, N.SWG_RT_UP_MAX))
check("…with a slot for every table", N.SWG_RT_UP_MAX - N.SWG_RT_UP_BASE == N.SWG_RT_MAX - N.SWG_RT_BASE)
# ⚠️ DERIVED, NOT A LITERAL. Widening the table band must move this one, or a wider band would run straight
# through it: at SWG_RT_MAX = 7199 a literal 6890 base would have reached 7089.
check("⚠️ …and it is derived from the table band's width",
      "SWG_RT_UP_BASE = SWG_RT_BASE - (SWG_RT_MAX - SWG_RT_BASE) - 11" in nsrc,
      "a literal base stops being below the table band the moment that band is widened")
check("⚠️ …and it does not swallow the relay's own divert rule",
      not (N.SWG_RT_UP_BASE <= N.RELAY_RT <= N.SWG_RT_UP_MAX),
      "RELAY_RT %d inside [%d, %d] would make the signature drift for ever" % (N.RELAY_RT, N.SWG_RT_UP_BASE, N.SWG_RT_UP_MAX))
check("…nor the relay's divert MARK", not (N.SWG_RT_UP_BASE <= N.RELAY_MARK <= N.SWG_RT_UP_MAX))
check("…nor the torrent connmark", not (N.SWG_RT_UP_BASE <= N.TORRENT_MARK <= N.SWG_RT_UP_MAX))
check("a table maps to a distinct mark", N._up_mark(7000) != 7000 and N._up_mark(7000) < N.SWG_RT_BASE, N._up_mark(7000))
check("…and a table outside our band maps to nothing",
      N._up_mark(0) == 0 and N._up_mark(7100) == 0 and N._up_mark(6999) == 0)

print("\n[2] ⚠️ THE SEAM IS GONE — the panel names a LEG, the node decides how to ask for it")
# This used to be a twin check: both programs computed the mark and had to agree. A pair that must be kept
# in step is a pair that can drift, and the contract everywhere else in the cascade already speaks in
# TABLES. So the arithmetic lives in one place now, and the thing to assert is that it is NOT in the other.
check("the panel carries no copy of the band", not hasattr(P, "SWG_RT_UP_BASE") and not hasattr(P, "_up_mark"),
      "a second reader of one grammar is the pair that drifts")
check("…and names the leg by its table instead", "up_table" in psrc and "up_mark" not in psrc)
check("the node is where a table becomes a mark", N._up_mark(7000) == N.SWG_RT_UP_BASE)

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
check("⚠️ …and names its leg by table", legs.get("wg8", {}).get("up_table") == 7000, legs.get("wg8"))
check("…which the node turns into an in-band mark",
      N.SWG_RT_UP_BASE <= N._up_mark(legs.get("wg8", {}).get("up_table", 0)) <= N.SWG_RT_UP_MAX, legs.get("wg8"))
check("the smart leg names its leg the same way",
      legs.get("wg9", {}).get("up_table") == legs.get("wg9", {}).get("mark"), legs.get("wg9"))

print("\n[7] the node reads it, and an older panel still works")
def derive(leg):
    e = dict(leg or {}); e["mark"] = int(e.get("mark") or 0)
    e["up"] = N._up_mark(int(e.get("up_table") or 0)) or e["mark"]
    return e
check("both legs survived into the plan (else nothing below is tested)", "wg8" in legs and "wg9" in legs, sorted(legs))
_w8, _w9 = legs.get("wg8") or {}, legs.get("wg9") or {}
check("a leg with an upstream mark uses it", derive(_w8)["up"] == N._up_mark(7000))
_old = {k: v for k, v in _w8.items() if k != "up_table"}
check("⚠️ …and one WITHOUT falls back to the divert mark", derive(_old)["up"] == 0,
      "a cascade from a panel too old to send one must keep being routed by its bind address")
_olds = {k: v for k, v in _w9.items() if k != "up_table"}
check("…which for a smart leg is its own table", bool(_w9) and derive(_olds)["up"] == _w9.get("mark"))

print("\n[8] the guard, and the reason it is kept rather than deleted")
RULES = ["0:\tfrom all lookup local",
         "%d:\tfrom all fwmark 0x%x lookup 7001" % (N._up_mark(7001), N._up_mark(7001)),
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
_other = dict(_w8, up_table=7001)
check("the contract expresses it", derive(_other)["up"] == N._up_mark(7001) != derive(_w8)["up"])
check("…and it is still a leg we route to", P._relay_ineligible({}, 0, 7001) == "")
check("…while a table we do NOT route to is refused with a reason",
      bool(P._relay_ineligible({}, 0, 6890)) and bool(P._relay_ineligible({}, 0, N.SWG_RT_MAX + 1)),
      "a leg no rule looks up leaves by this node's own uplink instead — it WORKS, so nothing would say so")

print("\n[9b] ⚠️ …and a missing rule is judged by WHERE THE PACKET WOULD GO, not by the rule's absence")
# MEASURED on msk-main: `from 10.8.0.1 mark 6999` (a mark with no rule) resolves to `via 201.24.126.1 dev
# eth0` — the node's own uplink. A smart leg has no source rule behind it, so the relay would re-originate
# out the ENTRY node's address instead of the exit. That works, so nothing else would ever report it.
# ⚠⚠ THE FIRST VERSION OF THIS GUARD ASKED "IS THE RULE THERE" AND REFUSED A HEALTHY CASCADE. A
# whole-interface cascade binds inside a subnet its own `from S lookup T` rule already claims, so a missing
# upstream rule changes nothing for it — the packet still takes that table. Refusing it tore the divert down
# and dropped every relayed connection on a leg that was routing perfectly. Worse, it was demonstrated ON a
# cascade and read as the guard working, because the traffic kept flowing — which is exactly WHY it should
# not have been refused. MEASURED on msk-main with pref 6891 deleted: `from 10.18.0.1 mark 6891` still
# resolved to `dev swg_93c2fdf8 table 7001`.
_FWD_SRC = "7001:\tfrom 10.18.0.0/24 lookup 7001"
_R_OK = ["0:\tfrom all lookup local", _FWD_SRC,
         "%d:\tfrom all fwmark 0x%x lookup 7001" % (N._up_mark(7001), N._up_mark(7001)),
         "32766:\tfrom all lookup main"]
_R_NO = ["0:\tfrom all lookup local", _FWD_SRC, "32766:\tfrom all lookup main"]
def _sh(subnet, up, rules):
    return N._relay_shadowed([{"iid": "a", "subnet": subnet, "mark": up}], rules)
check("a leg whose rule is installed arms", _sh("10.18.0.0/24", N._up_mark(7001), _R_OK) == {})
check("⚠️ a CASCADE whose rule is missing but names its OWN leg still arms",
      _sh("10.18.0.0/24", N._up_mark(7001), _R_NO) == {},
      "the source rule answers with the same table — same answer, nothing is wrong")
_other = _sh("10.18.0.0/24", N._up_mark(7000), _R_NO)
check("⚠️ …but one naming ANOTHER leg is refused", "a" in _other, _other)
check("…saying which table would answer instead", _other and "table 7001" in _other["a"], _other)
_smart = _sh("10.8.0.0/24", N._up_mark(7000), _R_NO)
check("⚠️ a SMART leg with no source rule behind it is refused", "a" in _smart, _smart)
check("…saying it would leave by this node's own address",
      _smart and "this node's own address" in _smart["a"], _smart)
check("…and a leg with no upstream mark at all is untouched",
      _sh("10.18.0.0/24", 0, _R_NO) == {}, "mark 0 is a panel too old to name a leg")

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

print("\n[11] ⚠️ ONE CONTRACT, TWO RUN-MODELS — a bare-metal node and a container must agree")
# The systemd half writes an env file and the docker half builds an argv, and they had diverged: the unit
# asked for its leg by name while the container was still launched with the DIVERT mark. Two consequences,
# and the second is the bad one — `_relay_shadowed` is asked about the UPSTREAM mark, which is always
# in-band and therefore always skipped, so a container node was running with the shadowable client-side
# mark and no longer being guarded against exactly the silent wrong-exit that guard exists for.
_dk = nsrc[nsrc.index("def _relay_supervise_docker("):]
_dk = _dk[:_dk.index("\ndef ")]
check("the container is launched with the UPSTREAM mark", '"--mark", str(int(e.get("up") or 0))' in _dk,
      "a container node otherwise never asks for its leg by name, and loses the shadow guard with it")
# ⚠️ BOUNDED BY THE NEXT `def`, not by a character count — a fixed slice stops covering the function the
# moment a comment is added to it, which is the second time that has cost a red check in this work.
_env = nsrc[nsrc.index("def _relay_env_text("):]
_env = _env[:_env.index("\ndef ")]
check("…the same field the unit writes", 'int(e.get("up") or 0)' in _env, _env[-200:])
# Behavioural, not a grep: re-pointing a leg must make the container recreate.
_a = {"port": 5629, "gw": "10.18.0.1", "mss": 1340, "mark": 0, "up": N._up_mark(7000)}   # `up` is post-derivation
_b = dict(_a, up=N._up_mark(7001))
check("⚠️ changing ONLY the leg changes the recreate signature",
      N._relay_docker_spec("wg8", _a, 0.5) != N._relay_docker_spec("wg8", _b, 0.5),
      "a leg re-pointed by up_mark alone would restart a systemd relay and leave a container on the OLD leg")
check("…and an unchanged leg does not", N._relay_docker_spec("wg8", _a, 0.5) == N._relay_docker_spec("wg8", dict(_a), 0.5))

print("\n[12] the drift check does not ask the kernel about tables that cannot exist")
_seen = []
_saved = N.run
N.run = lambda argv, **kw: (_seen.append(list(map(str, argv))),
                            type("R", (), {"stdout": "", "returncode": 0})())[1]
try:
    N._cascade_live_sig({str(p) for p in N._band_tables([7000, N._up_mark(7000)])})
finally:
    N.run = _saved
_asked = [a[a.index("table") + 1] for a in _seen if a[:3] == ["ip", "route", "show"] and "table" in a]
check("it asks about the real table", "7000" in _asked, _asked)
check("⚠️ …and not about an upstream PRIORITY", str(N._up_mark(7000)) not in _asked, _asked)
check("…and the caller passes it through _band_tables",
      "_cascade_live_sig({str(p) for p in _band_tables(band)}" in nsrc,
      "otherwise one wasted fork per leg per reconcile — and phantom routes if anything else owns that number")

print("\n[13] ⚠️ an instance no longer wanted is stopped AFTER A RESTART, not just within one process")
# `_RELAY` is in-memory and empty on a fresh start, so a sweep over it alone stops nothing after any
# restart — and "the wanted set shrank across a restart" is the ordinary case (a link switched back to
# Forward plus an update or reboot; or a DOWNGRADE to a build that names instances differently). MEASURED
# by rolling a node back to released 1.8.6 on the rig: `swg-relay@wg1.<peer>` stayed active and listening
# on 0.0.0.0:5632 while the released node managed only `wg8` and could not even name the other one.
import tempfile as _tf
_d = _tf.mkdtemp()
for _n in ("wg8.env", "wg1.peerA.env", "awg2.peerB.env"):
    open(os.path.join(_d, _n), "w").write("x")
_saved_dir, N.RELAY_ENV_DIR = N.RELAY_ENV_DIR, _d
try:
    check("the durable record is read from disk", N._relay_existing() == {"wg8", "wg1.peerA", "awg2.peerB"},
          N._relay_existing())
    _sweep = sorted((set({}) | N._relay_existing()) - {"wg8"})
    check("⚠️ …so a FRESH process still knows what to stop", _sweep == ["awg2.peerB", "wg1.peerA"], _sweep)
finally:
    N.RELAY_ENV_DIR = _saved_dir
check("…and both run-models sweep the same way",
      nsrc.count("sorted((set(_RELAY) | _relay_existing()) - set(want))") == 2,
      "the container arm leaks the same way if it walks memory alone")
check("…and the container arm removes the env file too, or the record outlives the container",
      "os.unlink(os.path.join(RELAY_ENV_DIR, iface" in nsrc[nsrc.index("def _relay_supervise_docker("):
                                                          nsrc.index("def _relay_supervise(")])
check("a missing env dir is not an error", isinstance(N._relay_existing(), set))
# ⚠️ AND SYSTEMD IS ASKED TOO, ONCE. The env file is OUR bookkeeping, so it cannot see an orphan left by a
# build with a different naming scheme — which is exactly what a downgrade leaves. Enumerating units finds
# those; doing it once keeps it off the 5-second loop, the same trade the startup disarm already makes.
_seen_cmd = []
N._RELAY_UNITS["at"] = None
_sv, N.run = N.run, lambda a, **k: (_seen_cmd.append(" ".join(a)),
                                    type("R", (), {"stdout": "swg-relay@wg1.ghostpeer.service\nswg-relay@wg8.service\n",
                                                   "returncode": 0})())[1]
_sv_kind, N.NODE_KIND = N.NODE_KIND, "bare"
try:
    got = N._relay_existing()
finally:
    N.run, N.NODE_KIND = _sv, _sv_kind
check("⚠️ an orphan with NO env record is still found, via systemd",
      {"wg1.ghostpeer", "wg8"} <= got, got)
check("…and it is asked exactly once per process", len([c for c in _seen_cmd if "list-units" in c]) == 1,
      _seen_cmd)
N._RELAY_UNITS["at"] = None
check("…and a second call does not fork again",
      (lambda: (N.__dict__.__setitem__("_RELAY_UNITS", {"at": {"x"}}), N._relay_existing() >= {"x"})[1])())
# The record must survive a stop that did not take, or nothing can ever find the unit again — and BOTH
# arms have to honour that, so each is located by its own stop command rather than by a shared prefix.
_sysd = nsrc[nsrc.index("systemctl disable --now "):][:900]
check("⚠️ systemd: the env record survives a stop that did not take",
      "is-active" in _sysd and _sysd.index("is-active") < _sysd.index("os.unlink"),
      "an unconditional unlink loses the only handle on a unit whose stop failed")
_dock = nsrc[nsrc.index('run(["docker", "rm", "-f", _relay_cname(iface)]'):][:600]
check("⚠️ docker: the same, keyed on the removal actually succeeding",
      ".returncode == 0" in _dock and _dock.index(".returncode == 0") < _dock.index("os.unlink"), _dock[:160])

bad = len(FAILS)
if PERTURB:
    which = ("the upstream mark colliding with the table" if P_BAND else
             "the divert's mark sent to the socket" if P_SOMARK else
             "the divert scoped by the upstream mark" if P_DIVERT else
             "a table flushed by an upstream priority" if P_FLUSH else
             "the container launched with the divert mark" if P_DOCKER else
             "`up` dropped from the container's recreate signature" if P_DSPEC else
             "upstream priorities fed to the drift check as tables" if P_TBL else
             "a leg armed without its routing rule" if P_GUARD else
             "the stop-sweep walking only in-memory state" if P_SWEEP else
             "the signature blind to the upstream rules")
    print("\n--perturb (%s): %d check(s) RED" % (which, bad))
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
