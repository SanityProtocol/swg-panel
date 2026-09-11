#!/usr/bin/env python3
"""Self-test: nothing may forward to a node that is not in the fleet — and if it does, it is NAMED.

Removing a node took its mesh links and every roster target that used it, and left every INTERFACE that
forwarded to it pointing at a ghost. `cascade_plan` then does

    if not P or P not in nodes: return

and drops the forwarding silently, so the interface behaves as `direct` while still claiming `forward`; the
picker builds its options from the nodes that DO exist, so the control renders BLANK.

⚠️ THE PANEL ALREADY ENFORCED THIS ON WRITE. `/api/iface/update` refuses a forward whose target is not a
node ("egress_node must be another known node"), so "egress_node is always live" was plainly the intended
invariant — it just was not maintained on delete. `prune_exit_refs` does exactly this for the other kind of
reference (a dead `exit_id` -> `direct`), which is the shape this follows.

MEASURED on the qualification fleet: hel-flux removed 09-10 06:54, and nixos/awg2 still forwarding to it —
its clients leaving by nixos's own address, with nothing on any screen saying so, for a day.

⚠️ ROUTING RULES ARE NOT PRUNED, ON PURPOSE. A rule whose destination is gone degrades gracefully (traffic
takes the next matching rule) AND is already named on screen by `goneDest`. Rewriting those would erase a
decision the operator can see. Asserted here so the asymmetry is deliberate rather than an oversight.

Run: python3 tests/orphan_egress_selftest.py      (0 = pass)
     --perturb  puts the dangling reference back and expects RED.
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
CALL = "    _orphans = prune_node_refs(nodes)\n"
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert CALL in src, "the removal-path prune is not where this expects it — this run would FALSE-PASS"
if PERTURB:
    src = src.replace(CALL, "    _orphans = []\n", 1)

m = types.ModuleType("p")
m.__dict__.update({"__name__": "p", "__file__": os.path.join(ROOT, "swg-panel-server")})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)

print("[1] a forward whose target node is gone is rewritten to direct")
def fleet():
    return {"a": {"name": "a", "ifaces": {
                "awg2":  {"egress_mode": "forward", "egress_node": "GONE"},
                "awg3":  {"egress_mode": "forward", "egress_node": "b"},
                "wg1":   {"egress_mode": "smart", "routing": [{"action": "exit", "node": "GONE"}]},
                "wg2":   {"egress_mode": "direct"},
                "swg_x": {"system": True, "egress_mode": "forward", "egress_node": "GONE"}}},
            "b": {"name": "b", "csqtt": {"c1": {"egress_mode": "forward", "egress_node": "GONE"}}}}
n = fleet(); hit = m.prune_node_refs(n)
check("the dangling one is repaired", n["a"]["ifaces"]["awg2"]["egress_mode"] == "direct", n["a"]["ifaces"]["awg2"])
check("…and its dead reference is dropped", "egress_node" not in n["a"]["ifaces"]["awg2"])
check("…and it is reported, not silent", any(h[2] == "awg2" for h in hit), hit)
check("csqtt and wdtt records are covered too", n["b"]["csqtt"]["c1"]["egress_mode"] == "direct", n["b"]["csqtt"]["c1"])

print("\n[2] ⚠️ …and nothing else is touched")
check("a forward to a LIVE node is left alone",
      n["a"]["ifaces"]["awg3"] == {"egress_mode": "forward", "egress_node": "b"}, n["a"]["ifaces"]["awg3"])
check("a direct interface is left alone", n["a"]["ifaces"]["wg2"] == {"egress_mode": "direct"})
check("⚠️ a ROUTING RULE to a gone node is left alone — `goneDest` names it and the operator decides",
      n["a"]["ifaces"]["wg1"]["routing"] == [{"action": "exit", "node": "GONE"}], n["a"]["ifaces"]["wg1"])
check("⚠️ a panel-managed mesh link is left alone",
      n["a"]["ifaces"]["swg_x"]["egress_mode"] == "forward", n["a"]["ifaces"]["swg_x"])
# and it is idempotent — a second sweep finds nothing left to do
check("a second sweep is a no-op", m.prune_node_refs(n) == [])

print("\n[3] the sweep runs where it has to")
_rm = src[src.index("mesh_unlink_node(nodes, nid)"):]
_rm = _rm[:_rm.index('ev_append(deps["roster_path"], "node", nid, "Removed node"')]
check("on node removal, before the store is written",
      "_orphans = prune_node_refs(nodes)" in _rm
      and _rm.index("_orphans = prune_node_refs(nodes)") < _rm.index('nodes_save(deps["nodes_path"], nodes)'),
      "the sweep must run before the store is written, or the removal persists the orphans")
check("…and unconditionally on any node save, so an old record self-heals",
      "prune_node_refs(nodes)" in src.split("prune_default_exit(nodes[nid])")[1][:400])
check("…and the operator is told whose routing changed",
      "Egress reset to direct — its target node was removed" in src)

print("\n[4] …and the write-side invariant it restores still exists")
check("the API still refuses to STORE a forward to an unknown node",
      "egress_node must be another known node" in src)

print("\n[5] ⚠️ …and a reference held before the sweep is NAMED, not blank")
rt = open(os.path.join(ROOT, "js", "routing.js"), encoding="utf-8").read()
check("EgressPicker asks whether its value can be named",
      'const _goneFwd = value.mode === "forward" && !!value.node' in rt)
check("…from the SAME list the options are built from", "!others.some(n => n.id === value.node)" in rt)
# ⚠️ AND FROM THE WHOLE FLEET AS WELL. `others` excludes the current node, so on its own it answers
# "would we offer this?" rather than "does this id resolve to a node?" — and a record pointing at the
# node's own id would render as "A node that is no longer here" about a node that is right here.
check("…and does not call the node itself missing",
      "(Store.nodes || []).some(n => n.id === value.node)" in rt,
      "a self-referencing forward would be reported as a removed node")
check("…and appends a refusing row when it cannot", "_goneFwd ? [{ value: ifSel" in rt and 'className: "bad"' in rt)
check("…that says what is happening to the traffic",
      "so it routes nothing and its clients leave by this node's own address" in rt)
# the rule-level twin must still be there — this is the pair, not a replacement
check("…and the rule-level twin is untouched", "A node that is no longer here" in rt and "goneDest" in rt)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: a removed node leaves orphans again" % len(FAILS))
          if ok else "PERTURB FAILED — the prune was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
