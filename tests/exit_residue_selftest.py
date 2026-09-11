#!/usr/bin/env python3
"""Self-test for §13.4 — a rebuild must reset an EXIT's box-specific fields, and must not leak its key.

`exits` is the node record's only list of dicts, and three of the four fingerprint walkers could not see
into one. `_fp_leaves` has always indexed a list as `[i]`, so the CHECK side names `exits.[0].egress_ip` and
a `*` pattern matches it — while `_fp_prune`, `_fp_mask` and `fp_transform` each returned the list untouched
the moment they met it. One grammar, four readers, and the three that DO something were the blind ones.

Two consequences, both silent, both covered here:

  the SOURCES  `egress_ip` (what traffic leaving by the exit is SNATted to) and `dial_src` (which of the
               node's addresses dials it) are box-specific — the same fact `residue.ifaces.*.egress_ip`
               already resets — and were carried verbatim onto the new box. SNAT, or a `src` route, to an
               address the box does not own drops the traffic and says nothing.
  the KEY      a pasted profile's private key sat in the residue tree in PLAINTEXT, beside a mesh PSK and an
               interface key blob that `_fp_mask` had turned into identity hashes. That tree is stored as a
               baseline and, on a transfer, compared against the far panel.

Also asserted: the `device` is deliberately NOT reset (see the table's own note — a blank NIC means
auto-detect, a blank device means an exit that can carry nothing, and the node's `absent` alarm already
names the exit and everything behind it), and that no PRE-EXISTING rule reaches into `exits` — the
measurement that licensed teaching the walkers to descend in the first place.

Hermetic: no network, no state, no server. Only the fingerprint helpers are called.

Run: python3 tests/exit_residue_selftest.py (0 = pass)
     --perturb         puts the walkers back to dicts-only — the rules stay in the table and reach nothing,
                       which is how a rule that matches nothing looks exactly like a rule with nothing to do
     --perturb-secret  drops the profile-key row, leaving the key in the tree
     --perturb-severity restores the swallowed verdict: the sentence is still right and still filed under
                       `ok`, which is how it shipped and why nobody saw it
"""
import importlib.machinery, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
P_WALK = "--perturb" in sys.argv
P_SEC = "--perturb-secret" in sys.argv
P_SEV = "--perturb-severity" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_src = open(PANEL, encoding="utf-8").read()
if P_SEC:
    cut = '    ("exits.*.profile.private_key", "exit_profile_key"),\n'
    assert _src.count(cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _src = _src.replace(cut, "")
if P_SEV:
    # Put the swallowed severity back: the verdict still carries the right sentence, and `judge` still
    # files it under `ok`. Nothing crashes and the plan is otherwise untouched — which is exactly why it
    # went unnoticed.
    cut = 'return "block", "binds %r, which this box does not have'
    assert _src.count(cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _src = _src.replace(cut, 'return "bad", "binds %r, which this box does not have', 1)
if P_SEC or P_SEV:
    PANEL = os.path.join(HERE, ".perturbed-residue.py")
    open(PANEL, "w", encoding="utf-8").write(_src)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if P_SEC or P_SEV:
    os.unlink(PANEL)

if P_WALK:
    # Every walker asks ONE predicate whether a list is a subtree, so saying "never" puts all six back the
    # way they were: meeting a list, return it untouched. Patched here rather than cut out of the source
    # because six call sites is six anchors to drift, and an anchor that stops matching after a rename is a
    # perturbation that quietly stops perturbing. It cannot raise, so a red run is a caught bug.
    P._fp_record_list = lambda o: False

KEPT, LOST = "198.51.100.5", "203.0.113.10"          # the new box has the first and not the second
CTX = {"before_ips": [KEPT, LOST], "after_ips": [KEPT]}

def record():
    return {"name": "n1",
            "links": {"L": {"psk": "MESH-PSK"}},
            "ifaces": {"awg0": {"egress_ip": LOST, "wan_iface": "eth0"}},
            "exits": [
                {"id": "a", "producer": "adopted", "device": "tun-lab0",   # a device somebody else runs
                 "egress_ip": LOST, "dial_src": LOST, "killswitch": True},
                {"id": "b", "producer": "imported", "device": "wgx-b",     # a pasted profile — ours to recreate
                 "egress_ip": "", "dial_src": KEPT,
                 "profile": {"address": "172.16.0.2/32", "peer_key": "PUB", "private_key": "PROFILE-PRIVATE-KEY"}},
            ]}

print("\n[1] the reset reaches into a list of dicts at all")
out, acts = P.fp_transform(record(), "rebuild", CTX)
paths = {a[0] for a in acts}
check("the interface twin still resets (unchanged behaviour)", "ifaces.awg0.egress_ip" in paths, sorted(paths))
check("an exit's egress source is reached", "exits.[0].egress_ip" in paths, sorted(paths))
check("…and so is its dial source", "exits.[0].dial_src" in paths, sorted(paths))

print("\n[2] two sources, two rules — and they are NOT the same fact")
# ⚠️ THE DISTINCTION THIS SECTION EXISTS FOR. `dial_src` is one of the NODE'S OWN addresses (decision 7 —
# `reconcile_dial_src` puts it in a `src` route, so the box must own it): an address the box does not have
# is useless, whatever its provenance. `egress_ip` belongs to the EXIT'S world — `_validate_exits`
# deliberately does not test it against the node's addresses, because an adopted exit is somebody else's
# device and its source is usually an address inside THAT tunnel. Giving both `bind_swap` — which keeps
# only what the new box reports — would WIPE every foreign-tunnel source on every rebuild: the panel
# refusing to police the value at the door and then silently deleting it here.
FOREIGN = "10.200.0.7"                                   # a source inside the exit's own tunnel, never ours
_r = {"exits": [{"id": "a", "device": "d0", "egress_ip": FOREIGN, "dial_src": LOST},
                {"id": "b", "device": "d1", "egress_ip": LOST,    "dial_src": KEPT},
                {"id": "c", "device": "d2", "egress_ip": KEPT,    "dial_src": FOREIGN}]}
_o, _ = P.fp_transform(_r, "rebuild", CTX)
check("egress_ip: a source the box NEVER had is KEPT — deliberate, not derived",
      _o["exits"][0]["egress_ip"] == FOREIGN, _o["exits"][0])
check("egress_ip: the OLD box's own address resets to blank", _o["exits"][1]["egress_ip"] == "", _o["exits"][1])
check("egress_ip: an address the new box HAS survives", _o["exits"][2]["egress_ip"] == KEPT, _o["exits"][2])
check("dial_src: an address the box no longer has resets", _o["exits"][0]["dial_src"] == "", _o["exits"][0])
check("dial_src: an address the box still has survives", _o["exits"][1]["dial_src"] == KEPT, _o["exits"][1])
check("dial_src: a source the box NEVER owned resets too — it must own the one it dials FROM",
      _o["exits"][2]["dial_src"] == "", _o["exits"][2])
# Three address-shaped fields on one record, three DIFFERENT verbs — which is the point: they are not one
# rubber stamp applied to everything that looks like an IP. `egress_ip` may be foreign and is kept unless it
# was ours; `dial_src` must be ours; a typed `gw` is the old box's LAN and cannot survive a move at all.
check("the address-shaped fields really do carry different verbs",
      {v for t, v, _w in P._fp_reset_rules("rebuild") if t.startswith("exits.")} == {"host_swap", "bind_swap", "cleared"},
      sorted((t, v) for t, v, _w in P._fp_reset_rules("rebuild") if t.startswith("exits.")))
_g, _ = P.fp_transform({"exits": [{"id": "a", "device": "d0", "gw": "192.168.9.1"}]}, "rebuild", CTX)
# `cleared` POPS the key, the same as `ifaces.*.wan_iface` — and a missing key reads as blank everywhere,
# because `_validate_exits` writes "" when the operator types nothing. Both are "detect it".
check("a typed gateway does not survive a rebuild — the new box is behind another router",
      "gw" not in _g["exits"][0] and not _g["exits"][0].get("gw", ""), _g["exits"][0])
check("a blank stays blank — nothing invented", out["exits"][1]["egress_ip"] == "", out["exits"][1])

print("\n[3] the device is left alone, deliberately")
check("an adopted exit keeps its device name", out["exits"][0]["device"] == "tun-lab0", out["exits"][0])
check("…and so does an imported one (that device is ours to recreate)", out["exits"][1]["device"] == "wgx-b")
check("no rule claims to reset a device", not any(t == "exits.*.device" for t, _v, _w in P._fp_reset_rules("rebuild")))

print("\n[4] the pasted profile's private key never reaches the tree")
kept, _ = P._fp_prune(record(), P._FP_EXCLUDE_PATS)
kept, _ = P._fp_prune(kept, P._FP_CONSUMED_PATS)
masked = P._fp_mask(kept)
blob = json.dumps(masked)
check("the mesh PSK is still masked (unchanged behaviour)", "MESH-PSK" not in blob)
check("a pasted profile's private key is masked", "PROFILE-PRIVATE-KEY" not in blob,
      masked["exits"][1].get("profile"))
check("…as an identity, so a diff can still tell same from different",
      str(masked["exits"][1]["profile"]["private_key"]).startswith("secret:"),
      masked["exits"][1]["profile"]["private_key"])
check("…and the rest of the profile survives — it is not a secret",
      masked["exits"][1]["profile"]["address"] == "172.16.0.2/32")

print("\n[5] the diff judges the AFTER value, so an unreset source cannot pass in silence")
before = {"residue": record()}
after_bad = {"residue": record()}                       # a rebuild that restored the record verbatim
_d = P.fp_diff({"sections": ["residue"], "digest": {}, "trees": before},
               {"sections": ["residue"], "digest": {}, "trees": after_bad},
               "rebuild", CTX)
_hits = [r for r in (_d.get("blocks") or []) + (_d.get("review") or [])
         if "exits" in str(r.get("path", ""))]
check("an exit still holding the OLD box's source is surfaced", bool(_hits),
      "nothing said about exits: " + str(sorted({r.get("path") for r in
                                                (_d.get("blocks") or []) + (_d.get("review") or [])})[:6]))

print("\n[6] descending was behaviour-neutral for everything that already shipped")
ex_paths = P._fp_leaves({"exits": record()["exits"]})
for pats, label in ((P._FP_EXCLUDE_PATS, "exclude"), (P._FP_CONSUMED_PATS, "consume")):
    _m = sorted({(p, q) for p in ex_paths for q in pats if P._fp_pat_match(tuple(p.split(".")), q)})
    check("no %s rule reaches into exits" % label, not _m, _m[:4])
_reset = [t for t, _v, _w in P._fp_reset_rules("transfer")]
_m = sorted({(p, q) for p in ex_paths for q in _reset if P._fp_pat_match(tuple(p.split(".")), q)})
check("a TRANSFER resets nothing on an exit — the box does not move, only the panel under it", not _m, _m[:4])

print("\n[7] the verdict this rule exists to give actually lands somewhere the operator reads")
# ⚠️ Found by section 5, not looked for: `_bind_swap_verdict` returned "bad" for the one case that matters,
# and `judge` files anything that is not "block" or "review" under **ok**. So "binds an address this box
# does not have — the service cannot start" was being carried into the list nobody is asked to read, for
# every bind_swap row there is: both turn-family binds, all three node source IPs, the per-interface egress
# source — and now the two exit sources. `_fp_swap_verdict_list`'s RANK would have raised KeyError on it too.
_sev = lambda after, ips: P._bind_swap_verdict("", after, {"before_ips": [LOST], "after_ips": ips})[0]
check("an address the box does not have BLOCKS", _sev(LOST, [KEPT]) == "block", _sev(LOST, [KEPT]))
check("…and never lands in a severity the caller files as ok",
      _sev(LOST, [KEPT]) in ("block", "review", "unknown"), _sev(LOST, [KEPT]))
check("an address the box HAS is ok", _sev(KEPT, [KEPT]) == "ok", _sev(KEPT, [KEPT]))
check("a wildcard bind is ok", _sev("0.0.0.0:51820", [KEPT]) == "ok", _sev("0.0.0.0:51820", [KEPT]))
check("blank is ok — it means auto", _sev("", [KEPT]) == "ok", _sev("", [KEPT]))
# The prospective case: at rebuild time the new box usually has not reported, and "not knowable yet" must
# not read as "wrong" or every dry-run blocks and the operator learns to force past the screen.
check("a box that has not reported yet is UNKNOWN, not a block", _sev(LOST, None) == "unknown", _sev(LOST, None))
# …and the CLASS, not just this instance: `judge` used to file anything it did not recognise under `ok`,
# which is what let "bad" hide. The next verdict function can make the same typo, and "we did not
# understand the answer" must never come out as "fine".
_orig_v = P._bind_swap_verdict
P._bind_swap_verdict = lambda b, a, ctx: ("nonsense", "a verdict nothing downstream knows")
_rec = {"ifaces": {"awg0": {"egress_ip": LOST}}}
_fp = lambda t: {"sections": ["residue"], "digest": {}, "trees": {"residue": t}, "cannot_predict": []}
_d = P.fp_diff(_fp(_rec), _fp(_rec), "rebuild", CTX)
P._bind_swap_verdict = _orig_v
check("an unrecognised verdict fails CLOSED, into blocks", [b["path"] for b in _d["blocks"]]
      == ["residue.ifaces.awg0.egress_ip"], _d["blocks"])
check("…and is never quietly filed as ok", not _d["ok"], _d["ok"])
check("…saying it is a bug in the rule, not in the node",
      _d["blocks"] and "bug in the rule" in _d["blocks"][0]["why"], _d["blocks"])
check("…and its host_swap twin still agrees",
      P._host_swap_verdict(LOST, LOST, {"before_ips": [LOST], "after_ips": None})[0] == "unknown")

print()
if P_WALK or P_SEC or P_SEV:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d checks went red"
           % ("secret" if P_SEC else "severity" if P_SEV else "walkers", len(FAILS))) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
