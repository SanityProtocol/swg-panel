#!/usr/bin/env python3
"""Self-test for P2's DEVICE EXIT lowering — panel plan + node datapath.

A device exit is a forward whose far end is a LOCAL device: `ip rule from S lookup T` +
`default dev <D> table T`. The two things that make it different from a mesh forward are exactly the two
things this covers, because both fail SILENTLY:

  §5.7  the SNAT. Every SNAT rule is `-o`-scoped, so the interface's own `swg-egress:<iface>` rule (`-o eth0`)
        can never match traffic leaving by <D>. A rule of its own is required — and `_has_foreign_egress`
        treats ANY POSTROUTING line source-NATting the same subnet as foreign unless the comment contains
        the literal "swg-egress:", so the wrong tag DELETES the interface's baseline MASQUERADE and the
        interface loses direct internet for everything the exit does not carry. Nothing says so.
  §5.10 the clamp. `link_devs` drives FORWARD-accept + TCP-MSS, and a device exit is in neither `fwd` nor
        `exit_` as the cascade builds them, so without folding it in there is no clamp toward the exit —
        which is §5.5's "connects, small pages fine, big pages hang" on a plate.

Also covered: decision 3 (a disabled exit produces NO plan entry, so the interface degrades to direct while
its SELECTION stays stored), and that a device exit does NOT install mesh preparation — no `add_exit`, no
`allowed` — because there is no peer node to prepare.

Hermetic: no iptables, no /proc, no network — `run()` is stubbed and the calls are inspected.

Run: python3 tests/devexit_lowering_selftest.py (0 = pass)
     --perturb  tags the SNAT outside the swg-egress: namespace, as the obvious implementation would, and
                expects RED.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
# A SECOND perturbation, for the obvious way to allocate the table: key it by the DEVICE. Two exits may name
# one device with different kill-switch settings, and the table is where the kill-switch lives — keyed by
# device they collapse into one and the switch of whichever exit has it ON governs the traffic of the one
# that has it OFF. Applied to the panel's SOURCE, because the key has no seam to monkey-patch.
KEYDEV = "--perturb-key" in sys.argv

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

if KEYDEV:
    _src = open(PANEL, encoding="utf-8").read()
    _cut = '_key = "exit:" + str(_x.get("id") or "")'
    assert _src.count(_cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".perturbed-key.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, '_key = "dev:" + _dev', 1))
    PANEL = _tmp

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
if KEYDEV:
    os.unlink(PANEL)

# ── 1. the panel's plan ──────────────────────────────────────────────────────────────────────────
def plan(enabled=True, dev="wgcf", ks=False, xid="aabbccdd"):
    nodes = {"n1": {"name": "n1", "links": {},
                    "exits": [{"id": "aabbccdd", "device": dev, "enabled": enabled, "killswitch": ks}],
                    "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": xid}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}}}}}
    return P.cascade_plan(nodes, snaps).get("n1", {})

p = plan()
dx = p.get("devexit") or []
check("an enabled exit lowers to one devexit entry", len(dx) == 1, dx)
check("…carrying subnet, device and a table in the 7000 band",
      dx and dx[0]["subnet"] == "10.17.0.0/24" and dx[0]["dev"] == "wgcf"
      and P.SWG_RT_BASE <= dx[0]["table"] <= P.SWG_RT_MAX, dx)
check("NO mesh preparation is installed (no peer to prepare)",
      not p.get("exit") and not p.get("allowed"), (p.get("exit"), p.get("allowed")))
check("decision 3: a DISABLED exit lowers to nothing (degrade, selection kept)",
      not (plan(enabled=False).get("devexit") or []))
check("the killswitch flag reaches the node", (plan(ks=True).get("devexit") or [{}])[0].get("killswitch") is True)
check("an exit whose device became a mesh link is inert, not lowered",
      not (plan(dev="swg_x").get("devexit") or []))
check("an exit pointing at this node's own interface is inert",
      not (plan(dev="awg0").get("devexit") or []))
check("an interface pointing at an exit that no longer exists is inert",
      not (plan(xid="gone").get("devexit") or []))
# The table band is SHARED with exit nodes, so devices cannot sneak past the 100-table ceiling by being
# spent on devices instead of peers. Asserted as the OBSERVABLE property — one node carrying both kinds gets
# two distinct tables from the one band — rather than by reading `_targets`, which is internal bookkeeping
# and is not in the returned plan at all. (Reading it was this test's first version, and it failed for that
# reason and not because the allocation was wrong.)
_both = P.cascade_plan(
    {"n1": {"name": "n1", "links": {"n2": {"iface": "swg_a"}},
            "exits": [{"id": "aabbccdd", "device": "wgcf", "enabled": True}],
            "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"},
                       "awg1": {"egress_mode": "forward", "egress_node": "n2"}}},
     "n2": {"name": "n2", "links": {"n1": {"iface": "swg_b", "peer_address": "10.255.0.1"}}, "ifaces": {}}},
    {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}},
                           "awg1": {"meta": {"subnet": "10.18.0.0/24"}}}}}).get("n1", {})
_ts = [e["table"] for e in (_both.get("forward") or [])] + [e["table"] for e in (_both.get("devexit") or [])]
check("a mesh forward and a device exit on one node draw DISTINCT tables from the one 7000 band",
      len(_ts) == 2 and len(set(_ts)) == 2 and all(P.SWG_RT_BASE <= t <= P.SWG_RT_MAX for t in _ts), _ts)

# ⚠️ THE TABLE IMPLEMENTS THE EXIT'S POLICY, NOT THE DEVICE'S. A kill-switch is a `prohibit default` route
# IN THE TABLE, so two exits that share a device but not a kill-switch setting MUST NOT share a table:
# collapsed, the one with the switch ON makes the one with it OFF fail closed, which is an interface
# stopping traffic when its operator explicitly chose fall-through.
def _two(ks_a, ks_b, dev_a="wgcf", dev_b="wgcf"):
    return P.cascade_plan(
        {"n1": {"name": "n1", "links": {},
                "exits": [{"id": "aaaaaaaa", "device": dev_a, "enabled": True, "killswitch": ks_a},
                          {"id": "bbbbbbbb", "device": dev_b, "enabled": True, "killswitch": ks_b}],
                "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aaaaaaaa"},
                           "awg1": {"egress_mode": "exit", "exit_id": "bbbbbbbb"}}}},
        {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}},
                               "awg1": {"meta": {"subnet": "10.18.0.0/24"}}}}}).get("n1", {}).get("devexit", [])
_mix = _two(True, False)
check("two exits sharing ONE device but not one kill-switch get SEPARATE tables",
      len({e["table"] for e in _mix}) == 2, _mix)
check("…and the kill-switch stays with the exit that set it",
      sorted((e["subnet"], e["killswitch"]) for e in _mix)
      == [("10.17.0.0/24", True), ("10.18.0.0/24", False)], _mix)
# …while the economy that matters is kept: one exit serving two interfaces is still ONE table.
_same = P.cascade_plan(
    {"n1": {"name": "n1", "links": {},
            "exits": [{"id": "aaaaaaaa", "device": "wgcf", "enabled": True, "killswitch": True}],
            "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aaaaaaaa"},
                       "awg1": {"egress_mode": "exit", "exit_id": "aaaaaaaa"}}}},
    {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}},
                           "awg1": {"meta": {"subnet": "10.18.0.0/24"}}}}}).get("n1", {}).get("devexit", [])
check("two interfaces on the SAME exit still share one table",
      len(_same) == 2 and len({e["table"] for e in _same}) == 1, _same)

# ⚠️ A NIC IS NOT AN EXIT DEVICE. `default dev <D>` is a SCOPE-LINK route: down a tunnel that is right, down
# a NIC it replaces `via <gw>` with a gatewayless route and the box ARPs the internet on the LAN. Measured.
_nicplan = P.cascade_plan(
    {"n1": {"name": "n1", "links": {},
            "exits": [{"id": "cccccccc", "device": "eth0", "enabled": True, "killswitch": False}],
            "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "cccccccc"}}}},
    {"n1": {"ether_ifaces": ["eth0"],
            "interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}}}}}).get("n1", {})
check("an exit naming the node's own NIC is inert, not lowered",
      not (_nicplan.get("devexit") or []), _nicplan.get("devexit"))
check("…and the refusal names it as a NIC, so the UI can point at the right control",
      P.exit_device_refusal({"name": "n1"}, "eth0", nics=["eth0"]) == "nic")

# ── 2. the node's datapath ───────────────────────────────────────────────────────────────────────
BASE  = '-A POSTROUTING -s 10.17.0.0/24 -o eth0 -m comment --comment "swg-egress:awg0" -j MASQUERADE'
STALE = '-A POSTROUTING -s 10.99.0.0/24 -o wgX -m comment --comment "swg-egress:exit:10.99.0.0/24" -j MASQUERADE'
DX = [{"subnet": "10.17.0.0/24", "dev": "wgcf", "table": 7000}]

class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def issued(devexit):
    calls, devs = [], []
    def fake_run(argv, **kw):
        calls.append(argv)
        if isinstance(argv, list) and argv[:4] == ["iptables", "-t", "nat", "-S"]:
            return _R(BASE + "\n" + STALE + "\n")
        return _R("")
    N.run = fake_run
    N._ensure_dev_rules = lambda table, chain, tag, ds, res, mk: devs.extend(ds)
    res = {"changed": 0, "errors": []}
    N._ensure_fwd_iptables([], [], "eth0", res, "", devexit=devexit)
    return [" ".join(map(str, c)) if isinstance(c, list) else str(c) for c in calls], devs, res

if PERTURB:
    # The obvious implementation: a descriptive tag of its own. It reads better and it deletes the
    # interface's baseline NAT, because `_has_foreign_egress` only ever exempts the literal "swg-egress:".
    _orig = N._snat_reconcile_rule
    N._snat_reconcile_rule = lambda tag, subnet, des, rules: _orig(
        tag.replace("swg-egress:exit:", "swg-devexit:"), subnet, des, rules)

calls, devs, res = issued(DX)
added = [c for c in calls if " -I POSTROUTING " in c]
check("a SNAT is added for the exit's subnet out the exit DEVICE",
      any("-s 10.17.0.0/24" in c and "-o wgcf" in c and "MASQUERADE" in c for c in added), added)
check("§5.7: its tag is inside the swg-egress: namespace, so the baseline is not read as foreign",
      any("swg-egress:exit:10.17.0.0/24" in c for c in added), added)
# the consequence, asked of the real function rather than inferred from the tag
newrule = next((c for c in added), "")
tagged = '-A POSTROUTING -s 10.17.0.0/24 -o wgcf -m comment --comment "%s" -j MASQUERADE' % (
    "swg-egress:exit:10.17.0.0/24" if "swg-egress:exit:" in newrule else "swg-devexit:10.17.0.0/24")
check("§5.7 CONSEQUENCE: the interface's baseline MASQUERADE survives alongside it",
      N._has_foreign_egress("10.17.0.0/24", [BASE, tagged]) is False,
      "foreign=True ⇒ _egress_des returns None ⇒ baseline deleted")
check("a device-exit SNAT that is no longer wanted is swept",
      any(" -D POSTROUTING " in c and "swg-egress:exit:10.99.0.0/24" in c for c in calls), calls)
check("§5.10: the exit device joins link_devs, so it gets FORWARD-accept + the MSS clamp",
      "wgcf" in devs, devs)
check("no errors from the datapath pass", not res["errors"], res["errors"])

if not PERTURB:
    # …and with no device exits at all, nothing about the existing cascade changes.
    calls0, devs0, res0 = issued([])
    check("a node with no device exit issues no device SNAT",
          not any("swg-egress:exit:10.17" in c for c in calls0), calls0)
    check("…but still sweeps a leftover one from a removed exit",
          any(" -D POSTROUTING " in c and "swg-egress:exit:" in c for c in calls0), calls0)
    # the fold: a device exit must reach the policy-routing signature as a forward would
    sig = N._cascade_want_sig([{"subnet": "10.17.0.0/24", "via_iface": "wgcf", "table": 7000}], [], [])
    check("folded into `fwd`, it produces the from-rule and the default route",
          "R|from|10.17.0.0/24|7000" in sig and "T|7000|default|wgcf|" in sig, sorted(sig))

if KEYDEV:
    if FAILS:
        print("\nperturbed (key): keying the table by DEVICE was CAUGHT (%d red) — one exit's kill-switch "
              "would have governed another exit's traffic" % len(FAILS))
        sys.exit(0)
    print("\nperturbed (key): NOTHING FAILED — this gate does not actually test the table keyspace")
    sys.exit(1)

if PERTURB:
    if FAILS:
        print("\nperturbed: the out-of-namespace tag was CAUGHT (%d red) — the baseline would have died" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually test §5.7")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
