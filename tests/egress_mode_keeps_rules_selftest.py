#!/usr/bin/env python3
"""Self-test — CHANGING AN INTERFACE'S EGRESS MODE MUST NOT DESTROY ITS ROUTING RULES.

The egress ladder clears the fields belonging to the mode it is leaving, which is right for the scalars a
mode owns — `egress_node`, `exit_id`, `wan_iface`. `routing` was cleared alongside them, and it is not that
kind of field: it is authored work — catalog lists, typed patterns, a destination per rule.

MEASURED in Chrome on msk-main 2026-09-10. `wg1` carried one rule with four operands (`2ip.io`,
`whatismyipaddress.com`, `.ru` as a zone, `*google*`) forwarding to nixos. Selecting a WARP device exit and
saving — the exact experiment this release invites — then switching straight back to Smart showed "no rules
yet". No warning before, no undo after.

KEEPING IT IS INERT, which is why this is the fix rather than a confirmation dialog:
  · the plan builder reads `routing` only under `egress_mode == "smart"`;
  · the node never reads it at all — it consumes the panel's computed plan, not the interface record.
So a stored list on a direct/forward/exit interface moves no packet. It is simply still there afterwards.

Run: python3 tests/egress_mode_keeps_rules_selftest.py      (0 = pass)
     --perturb   restores the pops and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()
_ANCH = '            rec.pop("egress_node", None); rec.pop("wan_iface", None)   # `routing` kept — see the note above'
assert SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
path = PANEL
if PERTURB:                                   # the shipped ladder: every non-smart branch dropped the rules
    SRC = SRC.replace(_ANCH, '            rec.pop("egress_node", None); rec.pop("routing", None); rec.pop("wan_iface", None)')
    SRC = SRC.replace('            rec.pop("egress_node", None); rec.pop("exit_id", None)      # `routing` kept — see the note above',
                      '            rec.pop("egress_node", None); rec.pop("routing", None); rec.pop("exit_id", None)')
    # …and the third branch, so the perturbation covers every mode the fix touched rather than two of three.
    SRC = SRC.replace('            rec["egress_mode"] = "forward"; rec["egress_node"] = en\n',
                      '            rec["egress_mode"] = "forward"; rec["egress_node"] = en\n            rec.pop("routing", None)\n')
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="egkeep-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(path, "swgpanel")
if PERTURB:
    os.unlink(path)

# The real grammar: an action of exit|direct|block|dev. "send these to another node" is `exit` + `node`.
RULES = [{"enabled": True, "category": "custom", "action": "exit", "node": "n2",
          "domains": ["2ip.io", "whatismyipaddress.com"], "cidrs": [], "patterns": ["*.ru", "*google*"]}]
NODES = {"n1": {"name": "a", "exits": [{"id": "x1", "device": "wgx-x1", "enabled": True}]},
         "n2": {"name": "b"}}
DEPS = {"panel_settings": {}, "node_snaps": {}}

_fn = None
for cand in ("_apply_egress_mode", "_apply_egress", "_egress_apply"):
    if hasattr(P, cand):
        _fn = getattr(P, cand); break

print("[1] the ladder is reachable as a function (else this gate tests nothing)")
check("found the egress ladder", _fn is not None,
      [n for n in dir(P) if "egress" in n.lower()][:8])

if _fn is not None:
    print("\n[2] every non-smart mode KEEPS the rules")
    for mode, extra in (("direct", {}), ("forward", {"egress_node": "n2"}), ("exit", {"exit_id": "x1"})):
        rec = {"egress_mode": "smart", "routing": [dict(r) for r in RULES]}
        body = {"egress_mode": mode}; body.update(extra)
        err, _ = _fn(rec, body, NODES, "n1", DEPS)
        check("%-8s → mode set, no error" % mode, err is None and rec.get("egress_mode") == mode, (err, rec.get("egress_mode")))
        check("%-8s → the rule list survives" % mode, len(rec.get("routing") or []) == 1, rec.get("routing"))
        check("%-8s → its four operands are intact" % mode,
              len((rec.get("routing") or [{}])[0].get("domains") or []) == 2
              and len((rec.get("routing") or [{}])[0].get("patterns") or []) == 2, rec.get("routing"))

    print("\n[3] the scalars a mode LEAVES are still cleared (this is not 'keep everything')")
    rec = {"egress_mode": "forward", "egress_node": "n2", "routing": [dict(r) for r in RULES]}
    _fn(rec, {"egress_mode": "exit", "exit_id": "x1"}, NODES, "n1", DEPS)
    check("egress_node dropped when leaving forward", "egress_node" not in rec, rec)
    check("exit_id set", rec.get("exit_id") == "x1", rec)
    rec = {"egress_mode": "exit", "exit_id": "x1", "wan_iface": "eth9", "routing": [dict(r) for r in RULES]}
    _fn(rec, {"egress_mode": "direct"}, NODES, "n1", DEPS)
    check("exit_id dropped when leaving exit", "exit_id" not in rec, rec)
    check("wan_iface is NOT resurrected by direct", rec.get("wan_iface") in (None, "eth9"), rec)

    print("\n[4] switching BACK to smart re-applies the kept rules")
    rec = {"egress_mode": "smart", "routing": [dict(r) for r in RULES]}
    _fn(rec, {"egress_mode": "exit", "exit_id": "x1"}, NODES, "n1", DEPS)
    kept = [dict(r) for r in (rec.get("routing") or [])]
    err, _ = _fn(rec, {"egress_mode": "smart", "routing": kept}, NODES, "n1", DEPS)
    check("back to smart with the kept list", err is None and rec.get("egress_mode") == "smart", (err, rec.get("egress_mode")))
    check("…and the rule is there", len(rec.get("routing") or []) == 1, rec.get("routing"))

print("\n[5] KEEPING IT MUST STAY INERT — ASKED OF THE PLAN, not grepped for")
# ⚠️ THIS WAS A STRING MATCH AND IT WAS ANCHORED ON THE WRONG LINE. The sentence claimed "the plan
# builder gates on egress_mode == smart"; the string it looked for lived in `_relay_ineligible`, the
# relay's belt-and-braces bar, which has nothing to do with the plan builder. Deleting that bar (Relay
# works under a smart cascade now) turned this check red while the claim it makes stayed perfectly true —
# which is the same thing as its having been green while the claim was never tested. So ask the plan: the
# SAME interface record, carrying the SAME stored rules, under each mode.
_SNAP = {"n1": {"interfaces": {"wg1": {"meta": {"subnet": "10.7.0.0/24"}}}}}
def _plan_for(mode, extra=None):
    ov = {"egress_mode": mode, "routing": [{"enabled": True, "category": "media", "action": "exit", "node": "n3"}]}
    ov.update(extra or {})
    nd = {"n1": {"name": "a", "ifaces": {"wg1": ov},
                 "links": {"n2": {"iface": "swg_a2"}, "n3": {"iface": "swg_a3"}}},
          "n2": {"name": "b", "links": {"n1": {"iface": "swg_b1", "peer_address": "10.255.0.1"}}},
          "n3": {"name": "c", "links": {"n1": {"iface": "swg_c1", "peer_address": "10.255.1.1"}}}}
    return P.cascade_plan(nd, _SNAP).get("n1") or {}
# The fixture must be PROVEN capable of producing the entry, or "no entry" says nothing about the gating.
_sm = _plan_for("smart")
check("the fixture CAN route a stored rule (smart)", len(_sm.get("smart") or []) == 1, _sm.get("smart"))
check("…out the leg the rule names", (_sm.get("smart") or [{}])[0].get("via_iface") == "swg_a3", _sm.get("smart"))
for _m, _x in (("direct", {}), ("forward", {"egress_node": "n2"}), ("exit", {"exit_id": "x1"})):
    _pl = _plan_for(_m, _x)
    check("%-8s → the kept rules move no packet" % _m, not (_pl.get("smart") or []), _pl.get("smart"))
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
nd = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
check("the node reads neither `routing` nor `egress_mode` from the interface record",
      '"routing"' not in nd and "egress_mode" not in nd)
check("no non-smart branch pops routing any more", 'rec.pop("routing", None)' not in src)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
