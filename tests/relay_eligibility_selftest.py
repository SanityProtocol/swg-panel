#!/usr/bin/env python3
"""Self-test: the panel offers a relay per (interface, LEG) — and a whole-interface cascade does not move.

Relay used to be barred under a smart cascade in one line (`egress_mode != "forward"`), because the divert
was source-keyed: `ip saddr <subnet>` can say "this interface's traffic" but not "the destinations this
interface routes over leg X", which is the only thing a cascade that splits one subnet across several legs
is about. The node keys the divert on the leg's MARK now (the mark IS the routing table, already written on
the packet by swg_smart), so the question has an answer and this is the panel half: one plan entry, one
relay instance, one port and one divert per leg.

⚠️ THE HALF THAT MATTERS TODAY IS THE ONE THAT MUST NOT CHANGE. Every relaying node on every real fleet is
a whole-interface cascade. Its instance keeps the bare interface name, its mark stays 0, its port stays the
one the NODE hashes for itself, and the old `ifaces` contract keeps being emitted so a node older than its
panel does not have its datapath taken away mid-upgrade. §4 is that regression.

⚠️ AND A DEVICE EXIT (WARP / NIC) MUST NOT BECOME ELIGIBLE. `action:"dev"` rules are `exit` entries ON THE
WIRE, deliberately — the node's lowering does not care whether the table's device is a mesh link or a
tunnel out of the box. So eligibility cannot be read off the wire shape: the relay exists to mask loss on a
mesh leg, and a device exit has no far end to mask. Keyed on "the target is a peer node" instead.

Hermetic: no network, no state dir, no server. `cascade_plan`, `relay_eligibility` and `relay_plan` only,
plus swg-noded loaded to prove the two ends agree about the port and the instance name.

Run: python3 tests/relay_eligibility_selftest.py   (0 = pass)
     --perturb-dev     records a leg for a device-exit rule too  → RED
     --perturb-band    drops the mark-band guard                 → RED
     --perturb-port    hands out the bare hash, no collision fix → RED
     --perturb-compat  puts smart legs in the old `ifaces` map   → RED
     --perturb-order   sorts the kinds together, so a smart leg
                       can take a forward leg's live port        → RED
     --perturb-sunset  ships the old contract to every node,
                       including the ones that say they read the
                       new one                                   → RED
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
P_DEV = "--perturb-dev" in sys.argv
P_BAND = "--perturb-band" in sys.argv
P_PORT = "--perturb-port" in sys.argv
P_COMPAT = "--perturb-compat" in sys.argv
P_ORDER = "--perturb-order" in sys.argv
P_SUNSET = "--perturb-sunset" in sys.argv
PERTURB = P_DEV or P_BAND or P_PORT or P_COMPAT or P_ORDER or P_SUNSET

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()
def cut(a, b, why):
    global SRC
    assert SRC.count(a) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % why
    SRC = SRC.replace(a, b, 1)

if P_DEV:
    # The mistake this guards: reading eligibility off the wire, where a device exit is an `exit` entry too.
    cut('''            if _de not in sn["devexit"]:
                sn["devexit"].append(_de)''',
        '''            if _de not in sn["devexit"]:
                sn["devexit"].append(_de)
            if (S, xkey) not in sn["_leg_seen"]:
                sn["_leg_seen"].add((S, xkey))
                sn["_legs"].append({"subnet": S, "peer": xkey, "mark": T})''', "dev leg")
if P_BAND:
    cut('    if mark and not (SWG_RT_BASE <= mark <= SWG_RT_MAX):',
        '    if False:', "band guard")
if P_PORT:
    cut('''        h = _relay_port_hash(iid)
        for k in range(RELAY_PORT_SPAN):
            q = RELAY_PORT_BASE + ((h - RELAY_PORT_BASE + k) % RELAY_PORT_SPAN)
            if q not in taken:
                taken.add(q)
                out[iid] = q
                break''',
        '''        out[iid] = _relay_port_hash(iid)''', "port probe")
if P_SUNSET:
    cut("    _reads_legs = bool(((snaps.get(nid) or {}).get(\"relay\") or {}).get(\"legs\"))",
        "    _reads_legs = False", "compat sunset")
if P_ORDER:
    cut('    for iid in sorted(marks, key=lambda i: (bool(marks[i]), i)):',
        '    for iid in sorted(marks):', "alloc order")
if P_COMPAT:
    cut('                           for l in legs if not l["mark"]}}),',
        '                           for l in legs}}),', "compat filter")

path = PANEL
if PERTURB:
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="relayelig-", dir=HERE)
    os.write(_fd, SRC.encode("utf-8")); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m

P = _load(path, "swgpanel")
if PERTURB:
    os.unlink(path)
N = _load(NODED, "swgnoded")

SNAP = {"n1": {"interfaces": {"wg8": {"meta": {"subnet": "10.18.0.0/24"}},
                             "wg9": {"meta": {"subnet": "10.19.0.0/24"}},
                             "wg7": {"meta": {}}}}}                    # subnet not reported yet


def fleet(ifaces, relay_on=("n2", "n3"), quota=None, max_conns=None):
    """One entry node with mesh links to two exit nodes and one local WARP device."""
    rel = {p: {"iface": "swg_a" + p[-1], "relay": {"mode": "relay" if p in relay_on else "forward"}}
           for p in ("n2", "n3")}
    n1 = {"name": "entry", "links": rel, "ifaces": ifaces,
          "exits": [{"id": "x1", "device": "warp0", "enabled": True, "producer": "imported"}]}
    if quota is not None or max_conns is not None:
        n1["relay"] = {"quota_pct": quota or 50, "max_conns": max_conns or 0}
    return {"n1": n1,
            "n2": {"name": "b", "links": {"n1": {"iface": "swg_b1", "peer_address": "10.255.0.1"}}},
            "n3": {"name": "c", "links": {"n1": {"iface": "swg_c1", "peer_address": "10.255.1.1"}}}}


def resolve(nodes, snaps=SNAP):
    plans = P.cascade_plan(nodes, snaps)
    legs = (plans.get("n1") or {}).get("_legs") or ()
    return plans, P.relay_eligibility(nodes["n1"], snaps, "n1", legs), P.relay_plan(nodes, plans, "n1", snaps)


SMART = {"egress_mode": "smart", "routing": [
    {"enabled": True, "category": "media", "action": "exit", "node": "n2"},
    {"enabled": True, "category": "news", "action": "exit", "node": "n2"},     # same leg → still ONE instance
    {"enabled": True, "category": "social", "action": "exit", "node": "n3"},
    {"enabled": True, "category": "ads", "action": "dev", "exit_id": "x1"},    # WARP — no far end to mask
    {"enabled": False, "category": "gaming", "action": "exit", "node": "n3"},  # disabled → no traffic, no leg
    {"enabled": True, "category": "all", "action": "direct"}]}
FWD = {"egress_mode": "forward", "egress_node": "n2"}

print("[1] a smart interface offers one leg per PEER NODE it routes to")
plans, elig, plan = resolve(fleet({"wg9": dict(SMART)}))
check("two rules to one peer collapse to one instance", "wg9.n2" in elig and len(elig) == 2, sorted(elig))
check("…and the second peer gets its own", "wg9.n3" in elig, sorted(elig))
check("…each carrying the table swg_smart marks the packet with",
      (elig.get("wg9.n2") or {}).get("mark") and (elig.get("wg9.n3") or {}).get("mark")
      and elig["wg9.n2"]["mark"] != elig["wg9.n3"]["mark"], elig)
check("…inside the band the node routes by",
      all(P.SWG_RT_BASE <= e["mark"] <= P.SWG_RT_MAX for e in elig.values()), elig)
check("…and every one of them is offerable", not any(e["why"] for e in elig.values()), elig)
_smart = [e for e in (plans["n1"].get("smart") or []) if e.get("action") == "exit"]
check("the fixture really does route (or nothing above is proven)", len(_smart) == 4, _smart)

print("\n[2] ⚠️ a DEVICE exit is an `exit` entry on the wire and must NOT become a leg")
check("no instance for the WARP rule", not any("x1" in k for k in elig), sorted(elig))
check("…though the plan does route it out the device",
      any(e.get("via_iface") == "warp0" for e in (plans["n1"].get("smart") or [])), plans["n1"].get("smart"))
check("…and a DISABLED rule's peer yields nothing either",
      not any(e["via"] == "n3" and e["mark"] == 0 for e in elig.values()), elig)
_only_dev = fleet({"wg9": {"egress_mode": "smart", "routing": [
    {"enabled": True, "category": "ads", "action": "dev", "exit_id": "x1"},
    {"enabled": True, "category": "all", "action": "direct"}]}})
_, _e2, _p2 = resolve(_only_dev)
check("an interface with ONLY device/direct rules offers no switch at all", _e2 == {}, _e2)
check("…so its plan is empty", not (_p2.get("legs") or []), _p2)

print("\n[3] the plan the node receives")
_, elig, plan = resolve(fleet({"wg8": dict(FWD), "wg9": dict(SMART), "wg7": dict(FWD)}))
legs = plan.get("legs") or []
check("one leg per eligible instance", len(legs) == 3, legs)
check("…an unreported subnet is skipped, not guessed", not any(l["iface"] == "wg7" for l in legs), legs)
check("no two legs share a port", len({l["port"] for l in legs}) == len(legs), legs)
check("every port is inside the node's own window",
      all(P.RELAY_PORT_BASE <= l["port"] < P.RELAY_PORT_BASE + P.RELAY_PORT_SPAN for l in legs), legs)
check("the smart legs carry their mark", sorted(l["mark"] for l in legs if l["peer"]) and
      all(l["mark"] for l in legs if l["peer"]), legs)
check("…and name the peer, so the node can key the instance",
      all(l["peer"] for l in legs if l["mark"]), legs)
check("the per-link congestion settings ride along", all("cc_up" in l and "cc_cli" in l for l in legs), legs)

print("\n[4] ⚠️ …and a WHOLE-INTERFACE CASCADE is exactly what it is today")
_fwd = [l for l in legs if l["iface"] == "wg8"]
check("forward yields exactly one leg", len(_fwd) == 1, _fwd)
check("⚠️ …with mark 0 — no mark match, no --mark, byte-identical on the wire",
      _fwd and _fwd[0]["mark"] == 0, _fwd)
check("⚠️ …and an EMPTY peer, so the instance keeps the bare interface name",
      _fwd and _fwd[0]["peer"] == "", _fwd)
check("⚠️ …which is the port the node hashes for ITSELF (no unit moves on upgrade)",
      _fwd and _fwd[0]["port"] == N._relay_port(N._relay_iid("wg8", "")), (_fwd, N._relay_port("wg8")))
_compat = plan.get("ifaces") or {}
check("the old `ifaces` contract is still emitted for a node older than this panel", _compat, plan)
check("⚠️ …carrying ONLY the forward legs", sorted(_compat) == ["wg8"], _compat)
check("…with the same fields it always had",
      _compat.get("wg8", {}).get("subnet") == "10.18.0.0/24" and "port" in _compat["wg8"]
      and "cc_up" in _compat["wg8"] and "cc_cli" in _compat["wg8"], _compat)

print("\n[5] ⚠️ the SEAM — the panel and the node must name the same instance and the same port")
# Two readers of one grammar. If the panel's hash drifted from the node's, every forward leg on every
# relaying fleet would be re-ported on the upgrade: the unit restarts and the divert points at a port
# nothing is listening on yet.
for a, b in (("wg8", ""), ("awg2", "e08fb18c67da"), ("wg-0", "n3"), ("x", "y")):
    check("iid %-22s agrees" % (a + "/" + (b or "-")), P._relay_iid(a, b) == N._relay_iid(a, b),
          (P._relay_iid(a, b), N._relay_iid(a, b)))
_ids = ["wg%d" % i for i in range(40)] + ["awg2.n%d" % i for i in range(40)]
check("the port hash agrees on 80 instance ids",
      all(P._relay_port_hash(i) == N._relay_port(i) for i in _ids),
      [i for i in _ids if P._relay_port_hash(i) != N._relay_port(i)][:4])

print("\n[6] the allocator resolves a REAL hash collision")
# Found, not assumed: two instance ids the node's own hash sends to the same slot.
_seen, _pair = {}, None
for i in range(4000):
    k = "wg9.p%04d" % i
    h = N._relay_port(k)
    if h in _seen:
        _pair = (_seen[h], k); break
    _seen[h] = k
check("a colliding pair exists to test with", _pair is not None, _pair)
if _pair:
    check("…and they really do hash the same", N._relay_port(_pair[0]) == N._relay_port(_pair[1]), _pair)
    _marks = {_pair[0]: 7000, _pair[1]: 7001}
    _al = P._relay_ports(_marks)
    check("⚠️ the panel does not hand them the same port", len(set(_al.values())) == 2, _al)
    check("…the first id keeps the hashed slot (stable across a re-plan)",
          _al[sorted(_pair)[0]] == N._relay_port(sorted(_pair)[0]), (_al, N._relay_port(sorted(_pair)[0])))
    check("…and re-planning is deterministic", P._relay_ports(_marks) == _al, _al)

print("\n[6b] ⚠️ …and a SMART leg never displaces a FORWARD one")
# `sorted()` alone mixes the kinds and "awg0.n2" < "wg8", so a smart leg on an UNRELATED interface could
# take the hashed slot a forward leg is listening on. The node would rewrite that unit's port and restart
# it, dropping every TCP connection on a leg the operator never touched. Found by search: a real pair whose
# smart id sorts FIRST and hashes to the same slot, so `sorted()` alone would fail this.
_FWD_IID = "wg8"
_h = N._relay_port(_FWD_IID)
_clash = None
for i in range(200000):
    k = "awg0.n%05d" % i
    if k < _FWD_IID and N._relay_port(k) == _h:
        _clash = k; break
check("a smart id exists that sorts first AND collides", _clash is not None, _clash)
if _clash:
    _al2 = P._relay_ports({_FWD_IID: 0, _clash: 7000})
    check("⚠️ the forward leg keeps the port it is listening on", _al2[_FWD_IID] == _h, (_al2, _h))
    check("…and the smart leg is the one that moves", _al2[_clash] != _h, _al2)
    check("…which a plain sorted() would have got backwards", sorted([_clash, _FWD_IID])[0] == _clash)

print("\n[7] ⚠️ a mark outside the band is refused, not shipped")
# A divert matching a mark nothing ever sets diverts nothing — the traffic forwards instead, which WORKS,
# so the leg reads as relayed and the only symptom is the loss the operator turned Relay on to hide.
check("an in-band mark is fine", P._relay_ineligible({"egress_mode": "smart"}, P.SWG_RT_BASE) == "")
check("…and mark 0 (forward) is fine", P._relay_ineligible({"egress_mode": "forward"}, 0) == "")
for _bad in (P.SWG_RT_BASE - 1, P.SWG_RT_MAX + 1, 0x9c40, 1):
    check("mark %d is refused with a reason" % _bad,
          bool(P._relay_ineligible({"egress_mode": "smart"}, _bad)), P._relay_ineligible({}, _bad))
_nodes = fleet({"wg9": dict(SMART)})
_bad_legs = [{"subnet": "10.19.0.0/24", "peer": "n2", "mark": P.SWG_RT_MAX + 7}]
_e3 = P.relay_eligibility(_nodes["n1"], SNAP, "n1", _bad_legs)
check("…and it reaches the operator as a `why`, not as silence",
      list(_e3) == ["wg9.n2"] and _e3["wg9.n2"]["why"], _e3)
# ⚠️ AND IT MUST NAME THE HALF THAT IS ACTUALLY BROKEN. A smart leg passes the same table as both the
# divert mark and the upstream, so with the upstream arm judged first an out-of-band table was reported as
# "its upstream table …" when the leg itself is what is wrong. Asserting only that SOME reason exists
# passes either way, which is how it got through.
check("⚠️ …naming the leg's own table, not its upstream",
      "routing table" in _e3["wg9.n2"]["why"] and "upstream" not in _e3["wg9.n2"]["why"], _e3["wg9.n2"]["why"])
check("…while a bad UPSTREAM alone is reported as the upstream",
      "upstream" in P._relay_ineligible({}, 7001, P.SWG_RT_MAX + 7), P._relay_ineligible({}, 7001, P.SWG_RT_MAX + 7))
_plans = P.cascade_plan(_nodes, SNAP)
_plans["n1"]["_legs"] = _bad_legs
_p3 = P.relay_plan(_nodes, _plans, "n1", SNAP)
# The reason used to be echoed back in the plan as `excluded`, which nothing ever read — the sheet takes
# it from `relay_eligibility` directly. So the claim to assert is the one that matters: the node is not
# asked to arm it, and the operator is still told why.
check("…so the node is never asked to arm it", not (_p3.get("legs") or []), _p3)
check("…while the operator still has the reason", bool(_e3["wg9.n2"]["why"]), _e3)

print("\n[8] inert unless the operator asked for it")
_, _e4, _p4 = resolve(fleet({"wg8": dict(FWD), "wg9": dict(SMART)}, relay_on=()))
check("no link on Relay ⇒ no plan at all", _p4 == {}, _p4)
check("…but the sheet is still told what WOULD be possible", len(_e4) == 3, sorted(_e4))
_, _e5, _p5 = resolve(fleet({"wg9": dict(SMART)}, relay_on=("n3",)))
check("a leg switched on alone relays only itself",
      [l["peer"] for l in (_p5.get("legs") or [])] == ["n3"], _p5.get("legs"))
_, _, _p6 = resolve(fleet({"wg9": dict(SMART)}, quota=77, max_conns=900))
check("the node-wide cap rides on the plan",
      _p6.get("quota_pct") == 77 and _p6.get("max_conns") == 900, _p6)
_, _, _p7 = resolve(fleet({"wg9": dict(SMART)}, quota=999))
check("…clamped, because it writes a CPUQuota", _p7.get("quota_pct") == P.RELAY_QUOTA_MAX, _p7)

print("\n[9] ⚠️ the old contract goes to the nodes that need it, and STOPS at the ones that do not")
# Without this the compat map is permanent: on a PUBLIC panel nobody can ever know the last old node is
# gone, and permanent compatibility code is code no one dares delete. Asked of the node, like `capable`.
_N2 = fleet({"wg8": dict(FWD), "wg9": dict(SMART)})
def _plan_for(relay):
    _s = {"n1": dict(SNAP["n1"], **({"relay": relay} if relay else {}))}
    return P.relay_plan(_N2, P.cascade_plan(_N2, _s), "n1", _s)
_old, _new, _never = _plan_for({"capable": True}), _plan_for({"capable": True, "legs": True}), _plan_for(None)
check("a node that says it reads legs is sent legs alone", "ifaces" not in _new, sorted(_new))
check("⚠️ …and one that does not still gets the map it has always read", "ifaces" in _old, sorted(_old))
check("⚠️ …as does one that has never synced, which is the safe way round",
      "ifaces" in _never, "no snapshot means no marker means assume old")
check("both are sent the same legs regardless", _old.get("legs") == _new.get("legs"))
check("…and the node ADVERTISES it rather than the panel guessing a version",
      '"legs": True' in open(NODED, encoding="utf-8").read(),
      "comparing version strings to answer a capability question is how that answer goes stale")

print("\n[10] the plan carries nothing nobody reads")
check("⚠️ `excluded` is gone from the contract",
      "excluded" not in json.dumps(_old) and "excluded" not in json.dumps(_new), sorted(_old))
check("…and the reasons still reach the operator, from eligibility",
      any(e.get("why") for e in P.relay_eligibility(
          fleet({"wg9": dict(SMART)})["n1"], SNAP, "n1",
          [{"subnet": "10.19.0.0/24", "peer": "n2", "mark": P.SWG_RT_MAX + 7, "mode": "smart"}]).values()),
      "the sheet reads relay_eligibility directly; the plan never had a reader for them")

bad = len(FAILS)
if PERTURB:
    which = ("a device-exit rule recorded as a leg" if P_DEV else
             "the mark-band guard removed" if P_BAND else
             "the bare hash with no collision fix" if P_PORT else
             "the two kinds of leg sorted together" if P_ORDER else
             "the old contract shipped to every node" if P_SUNSET else
             "smart legs leaking into the old `ifaces` contract")
    print("\n--perturb (%s): %d check(s) RED" % (which, bad))
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
