#!/usr/bin/env python3
"""Self-test for the node's EXIT REGISTRY — `_validate_exits` (plan decision 10, P1/P2 prerequisite).

An interface, and later a rule, points at an exit BY ID. A device name is not an identity: rename the
device or swap which tunnel the exit dials, and every reference would have to be rewritten. So the list
carries stable ids, and this covers the rules that keep them stable and keep the list SAVABLE.

⚠️ THE ASYMMETRY IS THE POINT, and it is the one thing worth breaking a build over: **block CREATION of a
device that may not be an exit, tolerate one already stored.** A device that was fine when written can stop
being offerable later — the operator adopts it as an interface, or a turn instance takes the name — and
refusing the save *then* is how a node's exit list becomes UNSAVABLE, including the save that would remove
the bad entry. This tree has closed that trap twice (§4.2; `_validate_routing`'s "nothing about a rule's
CONTENT returns an error any more"). It is not being reopened.

Hermetic: no panel process, no state dir — `_validate_exits` is a pure function over a node record.

Run: python3 tests/exit_registry_selftest.py (0 = pass)
     --perturb  re-runs with the asymmetry removed and expects RED.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

NODE = {"ifaces": {"awg0": {}}, "wdtt": {"wdtt1": {"raw_iface": "wdttraw2"}}, "csqtt": {"csqtt1": {}}}
V = P._validate_exits

if PERTURB:
    # The tempting-but-wrong version: validate every entry the same way, every time. It looks stricter and
    # it is how the exit list becomes unsavable the day a device changes role underneath it.
    # Minimal and FAITHFUL: the real validator with the asymmetry removed — every entry judged as if new.
    # A hand-rolled stub was tried first and crashed on a field it forgot to set, and a perturbation that
    # CRASHES cannot be told apart from one that CAUGHT: both exit non-zero with no verdict.
    _real = P._validate_exits
    V = lambda exits, c, mesh_prefix="swg_", link_ifaces=(), prev=(): _real(
        exits, c, mesh_prefix=mesh_prefix, link_ifaces=link_ifaces, prev=())

# ── creation ─────────────────────────────────────────────────────────────────────────────────────
good, err = V([{"device": "wgcf", "label": "WARP"}], NODE)
check("a real exit device is accepted", err is None and len(good or []) == 1, err)
check("…and gets a stable minted id", bool(good and P.EXIT_ID_RE.match(good[0]["id"])), good)
check("…label defaults to the device name when blank",
      V([{"device": "wgcf"}], NODE)[0][0]["label"] == "wgcf")
check("killswitch defaults OFF (decision 1)", good[0]["killswitch"] is False, good)
check("enabled defaults ON", good[0]["enabled"] is True, good)

for dev, why in (("wdttraw2", "ingress"), ("wdtt1", "ingress"), ("csqtt1", "ingress"),
                 ("awg0", "managed"), ("swg_x", "mesh"), ("lo", "loopback"), ("", "empty")):
    check("creating an exit on %-9s is refused (%s)" % (dev or "''", why),
          (V([{"device": dev}], NODE)[1] or "").endswith(why), V([{"device": dev}], NODE)[1])

# ── the asymmetry ────────────────────────────────────────────────────────────────────────────────
STORED = good
AFTER = {"ifaces": {"awg0": {}, "wgcf": {}}, "wdtt": NODE["wdtt"], "csqtt": NODE["csqtt"]}  # wgcf got adopted
kept, err2 = V(STORED, AFTER, prev=STORED)
check("a STORED exit whose device became refused still saves (no lockout)",
      err2 is None and [e["device"] for e in (kept or [])] == ["wgcf"], err2)
check("…and keeps its id, so references do not dangle",
      bool(kept) and kept[0]["id"] == STORED[0]["id"], kept)
check("…but EDITING it onto another bad device is still refused",
      (V([dict(STORED[0], device="wdttraw2")], AFTER, prev=STORED)[1] or "").endswith("ingress"))
check("removing the bad entry is always possible", V([], AFTER, prev=STORED) == ([], None))

# ── shape ────────────────────────────────────────────────────────────────────────────────────────
if not PERTURB:
    check("a non-list is a shape error", V({}, NODE)[1] is not None)
    check("a non-object entry is a shape error", V(["wgcf"], NODE)[1] is not None)
    check("an unknown producer is a shape error",
          V([{"device": "wgcf", "producer": "magic"}], NODE)[1] is not None)
    dup = V([{"id": "aaaaaaaa", "device": "wgcf"}, {"id": "aaaaaaaa", "device": "wgcf"}], NODE)[0]
    check("a duplicate id is re-minted rather than silently collapsing two exits into one",
          len(dup) == 2 and dup[0]["id"] != dup[1]["id"], dup)

# ── the two mode ladders must accept the SAME modes ──────────────────────────────────────────────
# There are two: `_apply_egress_mode` (EDIT, shared by the interface/WDTT/csqtt handlers) and the CREATE
# path's own `_cm ==` chain, which is deliberately more lenient and so cannot just call the helper. A mode
# added to one and missed in the other is silent: the interface is created and simply is not what was asked
# for. Compared structurally, from the source, so it cannot rot into a comment.
import ast as _ast
def _mode_sets(src):
    tree = _ast.parse(src)
    h = next(n for n in _ast.walk(tree)
             if isinstance(n, _ast.FunctionDef) and n.name == "_apply_egress_mode")
    tup = next(n for n in _ast.walk(h) if isinstance(n, _ast.Tuple)
               and all(isinstance(e, _ast.Constant) for e in n.elts)
               and "direct" in [e.value for e in n.elts])
    helper = {e.value for e in tup.elts}
    create = {"direct"}                                   # create's implicit else
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Compare) and isinstance(n.left, _ast.Name) and n.left.id == "_cm":
            create |= {c.value for c in n.comparators if isinstance(c, _ast.Constant)}
    return helper, create

_src = open(PANEL, encoding="utf-8").read()
_h, _c = _mode_sets(_src)
check("the CREATE ladder accepts exactly the modes the EDIT helper does", _h == _c, sorted(_h ^ _c))
check("…and both know about `exit`", "exit" in _h and "exit" in _c, (sorted(_h), sorted(_c)))
# Perturbation for THIS check specifically: drop the create branch and confirm the comparison notices.
_h2, _c2 = _mode_sets(_src.replace('elif _cm == "exit":', 'elif _cm == "__gone__":', 1))
check("…and the comparison actually notices when create loses a mode", _h2 != _c2, (sorted(_h2), sorted(_c2)))

if PERTURB:
    if FAILS:
        print("\nperturbed: validating stored entries like new ones was CAUGHT (%d red)" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not test the asymmetry it claims to")
    sys.exit(1)

# ── the node's own default must not outlive the exit it names ────────────────────────────────────
# ⚠️ NOT the same rule as an interface's reference, on purpose. An interface pointing at a removed exit is
# LEFT dangling: cascade_plan stops lowering it and the interface reads "degraded", which the operator can
# see. `default_exit` has no such tell — the picker finds no matching option, renders blank, and the node
# quietly egresses direct. Deleting the chosen exit from the manage sheet did exactly that, because that
# sheet sends `exits` and never mentions `default_exit`.
_p = P.prune_default_exit
_rec = {"exits": [{"id": "aabbccdd"}, {"id": "11223344"}], "default_exit": "11223344"}
check("a default that still names a live exit is left alone", _p(_rec) is False and _rec.get("default_exit") == "11223344", _rec)
_rec = {"exits": [{"id": "aabbccdd"}], "default_exit": "11223344"}
check("a default whose exit was removed is cleared", _p(_rec) is True and "default_exit" not in _rec, _rec)
_rec = {"exits": [], "default_exit": "11223344"}
check("…including when the last exit goes", _p(_rec) is True and "default_exit" not in _rec, _rec)
_rec = {"default_exit": "11223344"}
check("…and when the node has no exits key at all", _p(_rec) is True and "default_exit" not in _rec, _rec)
_rec = {"exits": [{"id": "aabbccdd"}]}
check("a node with no default is untouched", _p(_rec) is False and "default_exit" not in _rec, _rec)
_rec = {"exits": [{"id": "aabbccdd"}], "default_exit": ""}
check("…and so is an empty one — blank already means Default", _p(_rec) is False, _rec)

# ── nothing may be left POINTING at an exit that is gone ─────────────────────────────────────────
# ⚠️ DELETED IS NOT DISABLED. A disabled exit still exists and can come back, so every reference to it is
# KEPT and the traffic follows the node default meanwhile. A deleted one has nothing to come back to, and a
# reference to it names an id no picker can render — the field matches no option and goes blank, which is
# the same silent hole `prune_default_exit` closes for the node's own default.
_pr = P.prune_exit_refs
_rec = {"exits": [{"id": "keep"}],
        "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "gone"},
                   "awg1": {"egress_mode": "exit", "exit_id": "keep"},
                   "awg2": {"egress_mode": "smart", "routing": [
                       {"category": "netflix", "action": "dev", "exit_id": "gone"},
                       {"category": "banking", "action": "dev", "exit_id": "keep"},
                       {"category": "ads", "action": "block"}]}},
        "wdtt": {"w1": {"egress_mode": "exit", "exit_id": "gone"}},
        "csqtt": {"c1": {"egress_mode": "exit", "exit_id": "keep"}}}
_hit = _pr(_rec)
check("an interface pointing at a removed exit falls back to the node default",
      _rec["ifaces"]["awg0"]["egress_mode"] == "direct" and "exit_id" not in _rec["ifaces"]["awg0"],
      _rec["ifaces"]["awg0"])
check("…and one pointing at a live exit is untouched",
      _rec["ifaces"]["awg1"] == {"egress_mode": "exit", "exit_id": "keep"}, _rec["ifaces"]["awg1"])
_rules = _rec["ifaces"]["awg2"]["routing"]
check("a RULE pointing at a removed exit becomes direct",
      _rules[0]["action"] == "direct" and "exit_id" not in _rules[0], _rules[0])
check("…and its neighbours are untouched",
      _rules[1] == {"category": "banking", "action": "dev", "exit_id": "keep"}
      and _rules[2] == {"category": "ads", "action": "block"}, _rules[1:])
check("WDTT instances are covered too — an exit is not an interfaces-only reference",
      _rec["wdtt"]["w1"]["egress_mode"] == "direct", _rec["wdtt"]["w1"])
check("…and csqtt's live one is left alone",
      _rec["csqtt"]["c1"] == {"egress_mode": "exit", "exit_id": "keep"}, _rec["csqtt"]["c1"])
check("every rewrite is reported, so a caller can say what it changed", len(_hit) == 3, _hit)
check("a record with nothing dangling reports nothing", _pr(_rec) == [], _pr(_rec))
# a DISABLED exit is still an exit: it is in the list, so nothing is rewritten and the selection survives
_dis = {"exits": [{"id": "off", "enabled": False}],
        "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "off"}}}
check("⚠️ a DISABLED exit keeps every reference to it — it can come back",
      _pr(_dis) == [] and _dis["ifaces"]["awg0"] == {"egress_mode": "exit", "exit_id": "off"},
      _dis["ifaces"]["awg0"])

# ── a device the node REPORTS, referenced before anyone wrote a record for it ───────────────────────
# Every picker offers those devices now — the node's default, an interface's egress and a smart rule all
# show the same set. A reference is by id and a candidate has no id, so `_mint_device_exit` turns one into a
# record. It runs on the SAVE, not on the click: the interface sheet is a draft, and minting in the browser
# left a node-level exit behind whenever the operator cancelled.
print("\n[mint] a reported device becomes an exit on the save that references it")
_mk = lambda: {"n1": {"name": "n1", "links": {}, "exits": [], "ifaces": {"awg0": {}},
                      "exit_candidates": [{"name": "tun-lab0", "offerable": True}]}}
_n = _mk()
check("a plain id is handed straight back", P._mint_device_exit(_n, "n1", "aabbccdd") == ("aabbccdd", None))
_id, _e = P._mint_device_exit(_n, "n1", "dev:tun-lab0")
check("the first reference mints an adopted record", _e is None and len(_n["n1"]["exits"]) == 1, (_id, _e))
check("…named after the device, enabled, no kill-switch",
      _n["n1"]["exits"][0]["device"] == "tun-lab0" and _n["n1"]["exits"][0]["producer"] == "adopted"
      and _n["n1"]["exits"][0]["enabled"] is True, _n["n1"]["exits"][0])
_id2, _ = P._mint_device_exit(_n, "n1", "dev:tun-lab0")
check("⚠️ a SECOND reference reuses it — two interfaces on one device are not two exits",
      _id2 == _id and len(_n["n1"]["exits"]) == 1, (_id, _id2, len(_n["n1"]["exits"])))
# the refusal set is the same one the editor and the plan use, or a NIC could become an exit by being named
for _bad, _why in (("dev:awg0", "this node's own ingress"), ("dev:lo", "loopback")):
    _r, _err = P._mint_device_exit(_n, "n1", _bad)
    check("%s is refused, not minted" % _why, _r == "" and _err and len(_n["n1"]["exits"]) == 1, (_r, _err))
check("a refusal leaves no half-written record", len(_n["n1"]["exits"]) == 1, _n["n1"]["exits"])


print("\n[N] AN UNTITLED WARP ACCOUNT KEEPS ITS BLANK TITLE ACROSS SOMEONE ELSE'S EDIT")
# `exits` is a full-list REPLACE, so creating or deleting any exit re-saves every other one. An imported
# exit has no device at CREATE (it is minted from the id), so `label or device` stored blank and every
# reader rendered "WARP exit". On the RE-SAVE it carries the device the panel gave it — and the fallback
# froze `wgx-<id>` into the title of every untitled account, on an edit that was about a different row.
# Reported from the panel during 1.8.6-beta qualification. The create path alone never sees this.
_mk = lambda **kw: dict({"id": "aa11bb22", "producer": "imported", "provider": "warp"}, **kw)

# 1. CREATE: no device on the wire yet
_c, _e = V([_mk(profile_text="")], NODE)
check("create: an untitled WARP account stores a BLANK title", _c is not None and _c[0]["label"] == "",
      (_e, _c and _c[0]))
_dev = _c[0]["device"] if _c else ""
check("…and the panel minted its device from the id", _dev.startswith("wgx-"), _dev)

# 2. RE-SAVE: the shape the SPA sends back — the whole list, devices included
_c2, _e2 = V([_mk(device=_dev, label="")], NODE, prev=_c)
check("⚠️ re-save: the blank title is STILL blank, not the device name",
      _c2 is not None and _c2[0]["label"] == "", (_e2, _c2 and _c2[0].get("label")))

# 3. …and a title the operator actually typed survives both ways
_c3, _ = V([_mk(device=_dev, label="Home WARP")], NODE, prev=_c)
check("a typed title is untouched", _c3 and _c3[0]["label"] == "Home WARP", _c3 and _c3[0].get("label"))

# 3b. …and a title ALREADY frozen by the old code heals itself on the next save of the list, so a fleet
#     that has the corrupted names repairs without a migration. `wgx-<hex>` is panel-minted from the id;
#     nobody types it, so a title equal to it is the bug's fingerprint rather than a choice.
_c4, _ = V([_mk(device=_dev, label=_dev)], NODE, prev=_c)
check("a title frozen to the device name HEALS back to blank", _c4 and _c4[0]["label"] == "",
      _c4 and _c4[0].get("label"))

# 4. the ADOPTED fallback is the one that SHOULD name itself after its device — unchanged
_a, _ = V([{"id": "bb22cc33", "device": "tun-lab0"}], NODE)
check("an adopted exit still falls back to its device name", _a and _a[0]["label"] == "tun-lab0",
      _a and _a[0].get("label"))
_a2, _ = V([{"id": "bb22cc33", "device": "tun-lab0", "label": ""}], NODE, prev=_a)
check("…on a re-save too", _a2 and _a2[0]["label"] == "tun-lab0", _a2 and _a2[0].get("label"))

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
