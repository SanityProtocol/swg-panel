#!/usr/bin/env python3
"""Self-test for P5 — A SMART RULE WHOSE DESTINATION IS A DEVICE ON THIS NODE (plan §8 "P5", decision 10).

The whole-interface exit ("everything on awg0 leaves by WARP") shipped in P2. P5 is the same destination
offered one rule at a time: "send Netflix out WARP, everything else direct". Both spend the SAME table,
because both are the same exit — a node that routes five rules and an interface at one exit must spend one
of its hundred tables, not six.

WHAT MAKES THIS ITS OWN GATE, rather than a case bolted onto the P2 one: the two arms want DIFFERENT halves
of the same machinery, and the half they disagree about is the one that silently does the wrong thing.

    wanted by both      the default route in table T, the `swg-egress:exit:<S>` SNAT (every SNAT here is
                        `-o`-scoped, so without one the packets leave with a 10.x source and die), and the
                        `prohibit` kill-switch backstop.
    wanted by P2 ONLY   `ip rule from S lookup T`. A P5 packet arrives by FWMARK, from the smart chain. Add
                        the from-rule as well and the ENTIRE subnet leaves by the device — every other
                        destination in the rule list included, silently, with the rule list still on screen
                        saying otherwise.

So the plan tags a rule-scoped entry `scope:"rule"` and the node honours it in three places: `_devfwd`, the
kill-switch's from-rule fallback, and `_cascade_want_sig`. The third is the one with no symptom of its own —
a signature that names a rule the rebuild never installs can never equal the live one, so the node flushes
and rebuilds its whole policy band on EVERY sync, which is the packet-leaking gap the signature exists to
avoid. It is checked here because nothing else would notice it.

Hermetic: no ip, no iptables, no network. Run: python3 tests/devexit_rule_selftest.py  (0 = pass)
     --perturb  drops the scope test from `_devfwd` — the naive "a devexit entry is a devexit entry"
                reading — and expects RED.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

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

if PERTURB:
    _src = open(NODED, encoding="utf-8").read()
    _cut = 'for e in _dxs if e["state"] == "up" and e.get("scope") != "rule"]'
    assert _src.count(_cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _tmp = os.path.join(HERE, ".perturbed-noded.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, 'for e in _dxs if e["state"] == "up"]', 1))
    NODED = _tmp

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
if PERTURB:
    os.unlink(NODED)

EXITS = [{"id": "aabbccdd", "label": "WARP", "device": "wgcf", "enabled": True, "killswitch": False},
         {"id": "11223344", "label": "VPS", "device": "wg-ams", "enabled": True, "killswitch": True}]


def plan(rules, ifaces=None, exits=None):
    nodes = {"n1": {"name": "n1", "links": {}, "exits": list(exits if exits is not None else EXITS),
                    "ifaces": ifaces or {"awg0": {"egress_mode": "smart", "routing": rules}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}},
                                   "awg1": {"meta": {"subnet": "10.18.0.0/24"}}}}}
    return P.cascade_plan(nodes, snaps).get("n1", {})


# ── 1. the panel lowers a `dev` rule into a marked category + a rule-scoped devexit ───────────────
p = plan([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"}])
sm = p.get("smart") or []
dx = p.get("devexit") or []
check("a dev rule lowers to exactly one smart entry", len(sm) == 1, sm)
check("…which reaches the node as an `exit` entry out the exit's DEVICE",
      sm and sm[0].get("action") == "exit" and sm[0].get("via_iface") == "wgcf", sm)
check("…in the 7000 band", sm and P.SWG_RT_BASE <= sm[0].get("table", 0) <= P.SWG_RT_MAX, sm)
check("…for the category the rule names", sm and sm[0].get("category") == "netflix", sm)
check("a devexit entry rides with it, so the SNAT and the backstop exist", len(dx) == 1, dx)
check("…tagged scope=rule, which is what keeps it from claiming the whole subnet",
      dx and dx[0].get("scope") == "rule", dx)
check("…on the SAME table as the smart entry", dx and sm and dx[0].get("table") == sm[0].get("table"), (dx, sm))
check("NO mesh preparation — there is no peer node to prepare",
      not p.get("exit") and not p.get("allowed"), (p.get("exit"), p.get("allowed")))
check("and no whole-subnet forward entry", not p.get("forward"), p.get("forward"))

# ── 2. one exit, two users, ONE table ────────────────────────────────────────────────────────────
p2 = plan(None, ifaces={"awg0": {"egress_mode": "smart",
                                 "routing": [{"enabled": True, "category": "netflix", "action": "dev",
                                              "exit_id": "aabbccdd"}]},
                        "awg1": {"egress_mode": "exit", "exit_id": "aabbccdd"}})
_tabs = {e["table"] for e in (p2.get("devexit") or [])} | {e["table"] for e in (p2.get("smart") or [])}
check("an interface and a rule at the SAME exit share one table", len(_tabs) == 1, p2)
check("…and the interface still gets its own whole-subnet entry",
      any(e.get("scope") != "rule" and e["subnet"] == "10.18.0.0/24" for e in (p2.get("devexit") or [])),
      p2.get("devexit"))
# Two DIFFERENT exits are two tables — the sanity check that the one above is not passing by collapsing
# everything into a single table for the wrong reason.
p3 = plan([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"},
           {"enabled": True, "category": "google", "action": "dev", "exit_id": "11223344"}])
check("two different exits are two tables",
      len({e["table"] for e in (p3.get("smart") or [])}) == 2, p3.get("smart"))
check("…and the second exit's kill-switch travels with ITS entry, not the first's",
      {(e["dev"], e["killswitch"]) for e in (p3.get("devexit") or [])}
      == {("wgcf", False), ("wg-ams", True)}, p3.get("devexit"))

# ── 3. decision 3's degrade reaches the rule arm too ──────────────────────────────────────────────
check("a dev rule naming a DISABLED exit is inert (degrade, selection kept)",
      not (plan([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"}],
                exits=[dict(EXITS[0], enabled=False)]).get("smart") or []))
check("a dev rule naming an exit that no longer exists is inert",
      not (plan([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "deadbeef"}]).get("smart") or []))
check("an exit whose device became a mesh link is inert here as well",
      not (plan([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"}],
                exits=[dict(EXITS[0], device="swg_x")]).get("smart") or []))
check("a DISABLED rule is not lowered at all",
      not (plan([{"enabled": False, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"}]).get("smart") or []))

# ── 3b. rule ORDER survives the new kind — first-match is the node's whole contract ───────────────
_ord = plan([{"enabled": True, "category": "netflix", "action": "direct"},
             {"enabled": True, "category": "google", "action": "dev", "exit_id": "aabbccdd"},
             {"enabled": True, "category": "youtube", "action": "block"}])
check("a dev rule keeps its place among direct/block rules",
      [e["category"] for e in (_ord.get("smart") or [])] == ["netflix", "google", "youtube"],
      _ord.get("smart"))

# ── 4. _validate_routing — the door ───────────────────────────────────────────────────────────────
_nodes = {"n1": {"exits": EXITS}, "n2": {}}
def val(rules, prev=()):
    return P._validate_routing(rules, _nodes, "n1", (), prev=prev)
_c, _e, _ = val([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "aabbccdd"}])
check("a dev rule naming one of this node's exits is accepted",
      _e is None and _c and _c[0].get("exit_id") == "aabbccdd", (_e, _c))
check("a dev rule naming NOTHING is refused, not stored to route nothing",
      val([{"enabled": True, "category": "netflix", "action": "dev"}])[1] is not None)
check("a dev rule naming an exit this node does not have is refused",
      val([{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "deadbeef"}])[1] is not None)
# ⚠️ The asymmetry `_apply_egress_mode` already keeps: the SPA re-sends the whole rule list on every save,
# so refusing a STORED reference to a deleted exit makes the interface unsavable — including the save that
# would move it off. Tolerated on the way in, inert at plan time (checked in part 3).
_prev = [{"enabled": True, "category": "netflix", "action": "dev", "exit_id": "deadbeef"}]
check("…but one already STORED is tolerated, or deleting an exit locks the interface out",
      val(_prev, prev=_prev)[1] is None, val(_prev, prev=_prev)[1])
check("an unknown action is still refused",
      val([{"enabled": True, "category": "netflix", "action": "smuggle"}])[1] is not None)

# ── 5. the node: the SNAT and the backstop, but never the from-rule ───────────────────────────────
class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def lower(scope, ks=True, state="up"):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: state
    N._DEVEXIT["list"] = []
    ent = {"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": ks}
    if scope:
        ent["scope"] = scope
    smart = {"entries": [{"subnet": "10.17.0.0/24", "category": "netflix", "action": "exit",
                          "via_iface": "wgcf", "table": 7000}], "categories": ["netflix"]}
    N.reconcile_cascade({"interfaces": {}}, {"devexit": [ent]}, smart, "")
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"]

FROM  = "ip rule add from 10.17.0.0/24 lookup 7000 priority 7000"
FWM   = "ip rule add fwmark 7000 lookup 7000 priority 7000"
ROUTE = "ip route replace default dev wgcf table 7000"
GUARD = "ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC

c_rule = lower("rule")
check("rule-scoped, device up: the table gets its default route", ROUTE in c_rule, c_rule)
check("rule-scoped: reached by FWMARK", FWM in c_rule, c_rule)
check("rule-scoped: NEVER by `from <subnet>` — that would send the whole subnet out the device",
      FROM not in c_rule, c_rule)
check("rule-scoped: the kill-switch backstop is still installed", GUARD in c_rule, c_rule)
c_dead = lower("rule", ks=True, state="absent")
check("rule-scoped, device gone: still no from-rule, so only the marked category is stopped",
      FROM not in c_dead and GUARD in c_dead, c_dead)
c_iface = lower(None)
check("an interface-scoped entry is UNCHANGED — it still claims its subnet", FROM in c_iface, c_iface)

# ── 6. the signature, the half with no symptom of its own ─────────────────────────────────────────
_gr = [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": True,
        "state": "absent", "scope": "rule"}]
sig_r = N._cascade_want_sig([], [], [], guard=_gr)
check("a rule-scoped guard signs the prohibit route", "T|7000|prohibit||" in sig_r, sorted(sig_r))
check("…and does NOT sign a from-rule the rebuild never installs (else: flush+rebuild EVERY sync)",
      "R|from|10.17.0.0/24|7000" not in sig_r, sorted(sig_r))
_gi = [{k: v for k, v in _gr[0].items() if k != "scope"}]
check("an interface-scoped guard still signs both", 
      {"T|7000|prohibit||", "R|from|10.17.0.0/24|7000"} <= N._cascade_want_sig([], [], [], guard=_gi),
      sorted(N._cascade_want_sig([], [], [], guard=_gi)))

# ── 7. it SETTLES — the second pass must rebuild nothing ──────────────────────────────────────────
def settles():
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: "up"
    N._DEVEXIT["list"] = []
    ent = {"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000, "killswitch": True, "scope": "rule"}
    smart = {"entries": [{"subnet": "10.17.0.0/24", "category": "netflix", "action": "exit",
                          "via_iface": "wgcf", "table": 7000}], "categories": ["netflix"]}
    cfg = {"interfaces": {}}
    N.reconcile_cascade(cfg, {"devexit": [ent]}, smart, "")
    # the live reader is stubbed to answer with exactly what the first pass wanted
    want = N._cascade_want_sig([], [], smart["entries"], guard=[dict(ent, state="up")])
    N._cascade_live_sig = lambda tables: set(want)
    calls.clear()
    N.reconcile_cascade(cfg, {"devexit": [ent]}, smart, "")
    return [" ".join(map(str, c)) for c in calls
            if c and c[0] == "ip" and (c[1:3] == ["rule", "del"] or c[1:3] == ["route", "flush"])]

_churn = settles()
check("a rule-scoped exit settles — the second pass flushes nothing",
      not _churn, "the band is flushed and rebuilt every sync: " + str(_churn[:3]))

print()
if PERTURB:
    print("PERTURBED RUN — expected RED. failures: %d" % len(FAILS))
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All checks passed.")
