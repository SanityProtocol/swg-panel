#!/usr/bin/env python3
"""Self-test for NIC-EXIT step 6 — the refusal grammar for a network card.

A NIC used to be refused outright, and that was right while the only route shape was `default dev <D>`:
down a multi-access card it makes the box ARP the internet on the LAN (measured on the wire — 20
destinations, 20 FAILED neighbour entries, 100% loss). `default via <gw> dev <nic>` is the missing shape,
so the flat refusal splits into three verdicts that are NOT interchangeable:

  `nic_wan`    the node's own way out. Its route is the one `main` already has, and `reconcile_inet_chain`
               gives it no `@`-tagged counter — so it would carry traffic and report none. A no-op that
               reads as a choice is worse than a refusal, which is why it is one (plan B2).
  `nic_nogw`   no gateway, so no path off-box. The refusal the feature is built around.
  `nic`        this node has never reported gateways (an older build). NOT a verdict about the card — a
               refusal we have no data to make — so that node keeps precisely today's behaviour.

⚠️ THE ORDER OF THE FIRST TWO IS LOAD-BEARING, and the first version of [2] got the reason WRONG — its
perturbation moved the WAN test below the gateway test and NOTHING went red, because the WAN usually has a
gateway and so falls straight through to it. The order matters for the card where it does not: a box whose
default route is gatewayless (`default dev eth0`, ordinary on some VPS images). Test the gateway first and
that operator is told "give this card a default route" about the card their whole node is already reaching
the internet through — advice that is both useless and false. The verdict is the same either way; the
SENTENCE is not, and the sentence is the entire point of a refusal grammar.

⚠️ AND "FOUND NOTHING" IS NOT "ASKED AND THERE IS NOTHING", twice over — an empty `nics` (the node has not
spoken) and a `gws` of None (this build cannot say) must both decline to invent a verdict. A panel that
refused on absent data would black out every card on every node for the whole window after a restart.

[3] is the point of the whole step: ONE grammar, spelled in three lists. The same device asked of the
editor, the plan and the mint has to come back with the same answer, or a card is offered in one screen and
refused by the next — the defect this tree has already fixed once for exit DEVICES.

Run: python3 tests/nic_refusal_selftest.py  (0 = pass)
     --perturb  tests the gateway before the WAN, which is the plausible ordering, and expects RED on [2].
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
# [6]'s own red case: put back the tolerance that only asked "same id, same device", which is what
# let an EDIT clear a typed gateway into a state creation refuses.
PERTURB2 = "--perturb-edit" in sys.argv

_B2 = '''        if why and (eid not in known or str((known.get(eid) or {}).get("device") or "") != dev
                    or _why_prev != why):'''

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_A = '''        if wan and d == str(wan):
            return "nic_wan"'''
if PERTURB:
    _src = open(PANEL, encoding="utf-8").read()
    assert _src.count(_A) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    # Move the WAN test BELOW the gateway test — the plausible order, and the one that makes it dead code.
    _src = _src.replace(_A, "", 1).replace(
        '''        if not str((gws or {}).get(d) or "").strip() and not gw_known:
            return "nic_nogw"''',
        '''        if not str((gws or {}).get(d) or "").strip() and not gw_known:
            return "nic_nogw"
        if wan and d == str(wan):
            return "nic_wan"''', 1)
    _fd, PANEL = tempfile.mkstemp(suffix=".py", prefix="perturbed-panel-", dir=HERE)
    os.write(_fd, _src.encode()); os.close(_fd)

if PERTURB2:
    _src = open(PANEL, encoding="utf-8").read()
    assert _src.count(_B2) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    _src = _src.replace(_B2, '''        if why and (eid not in known or str((known.get(eid) or {}).get("device") or "") != dev):''', 1)
    _fd, PANEL = tempfile.mkstemp(suffix=".py", prefix="perturbed-panel2-", dir=HERE)
    os.write(_fd, _src.encode()); os.close(_fd)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod

P = _load(PANEL, "swgpanel")
if PERTURB or PERTURB2:
    os.unlink(PANEL)

NODE = {"name": "n1", "links": {}, "exits": [], "ifaces": {}}
NICS = ["eth0", "eth1", "eth2"]
GWS = {"eth0": "192.168.1.1", "eth1": "10.9.0.1", "eth2": ""}      # eth0 is the WAN; eth2 is the dummy
WAN = "eth0"
R = lambda d, **kw: P.exit_device_refusal(NODE, d, nics=NICS, gws=GWS, wan=WAN, **kw)

print("\n[1] the three verdicts")
check("a card with a gateway that is NOT the node's way out may be an exit", R("eth1") is None, R("eth1"))
check("the node's own WAN is refused as a no-op", R("eth0") == "nic_wan", R("eth0"))
check("a card with no gateway is refused for having no path off-box", R("eth2") == "nic_nogw", R("eth2"))
check("…and the operator's typed gateway lifts exactly that refusal",
      R("eth2", gw_known=True) is None, R("eth2", gw_known=True))
check("…but a typed gateway does NOT make the WAN usable — it was never about the gateway",
      R("eth0", gw_known=True) == "nic_wan", R("eth0", gw_known=True))

print("\n[2] ⚠️ the WAN is judged BEFORE the gateway — which only shows on a GATEWAYLESS WAN")
# A box whose default route is `default dev eth0` with no `via` — ordinary on some VPS images. Both orders
# refuse it; only one of them says something true. Asked with the WAN's own gateway blanked, because with a
# gateway present the two orders are indistinguishable, which is what the first perturbation proved.
_GW0 = dict(GWS, eth0="")
_r = P.exit_device_refusal(NODE, "eth0", nics=NICS, gws=_GW0, wan=WAN)
check("a gatewayless WAN is still 'that is already your way out', not 'give it a gateway'",
      _r == "nic_wan", _r)
check("…while another gatewayless card is still told to get one",
      P.exit_device_refusal(NODE, "eth2", nics=NICS, gws=_GW0, wan=WAN) == "nic_nogw")

print("\n[3] absence is not a verdict")
check("a node that has not reported its cards refuses none of them as a card",
      P.exit_device_refusal(NODE, "eth2", nics=[], gws=GWS, wan=WAN) is None)
check("⚠️ a node that has never reported GATEWAYS keeps today's flat refusal, not an invented one",
      P.exit_device_refusal(NODE, "eth1", nics=NICS, gws=None, wan=WAN) == "nic",
      P.exit_device_refusal(NODE, "eth1", nics=NICS, gws=None, wan=WAN))
check("…and that is a different code from 'no gateway', so the sentence can differ",
      P.exit_device_refusal(NODE, "eth1", nics=NICS, gws=None, wan=WAN) != "nic_nogw")
check("a node with no reported WAN does not refuse a card for being it",
      P.exit_device_refusal(NODE, "eth0", nics=NICS, gws=GWS, wan="") is None)

print("\n[4] the roles that outrank a card still do")
_n2 = {"name": "n1", "links": {"a": {"iface": "swg_ab"}}, "ifaces": {"awg0": {}},
       "exits": [], "wdtt": {}, "csqtt": {}}
_R2 = lambda d, **kw: P.exit_device_refusal(_n2, d, nics=NICS + ["swg_ab", "awg0"], gws=dict(GWS, swg_ab="1.2.3.4", awg0="1.2.3.4"), wan=WAN, **kw)
check("a mesh link is a mesh link even with a gateway", _R2("swg_ab") == "mesh", _R2("swg_ab"))
check("an interface this node serves clients on is still `managed`", _R2("awg0") == "managed", _R2("awg0"))
check("loopback is still loopback", _R2("lo") == "loopback")

print("\n[5] ONE GRAMMAR, THREE LISTS — the editor, the plan and the mint agree")
# A card offered by one screen and refused by the next is the defect this tree has already fixed once for
# exit devices. Each of these is a separate reader of the same question.
_ok, _err = P._validate_exits([{"id": "aaaa1111", "device": "eth1", "label": "Second uplink"}],
                              NODE, nics=NICS, gws=GWS, wan=WAN)
check("the EDITOR accepts a usable card", _err is None and _ok and _ok[0]["device"] == "eth1", _err)
_bad, _e2 = P._validate_exits([{"id": "aaaa2222", "device": "eth0"}], NODE, nics=NICS, gws=GWS, wan=WAN)
check("…and refuses the WAN with the same code the picker shows",
      _bad is None and "nic_wan" in str(_e2), _e2)
_bad3, _e3 = P._validate_exits([{"id": "aaaa3333", "device": "eth2"}], NODE, nics=NICS, gws=GWS, wan=WAN)
check("…and the gatewayless card", _bad3 is None and "nic_nogw" in str(_e3), _e3)
_gwok, _e4 = P._validate_exits([{"id": "aaaa4444", "device": "eth2", "gw": "192.0.2.1"}],
                               NODE, nics=NICS, gws=GWS, wan=WAN)
check("…but takes it once the operator types the gateway, and STORES that gateway",
      _e4 is None and _gwok and _gwok[0].get("gw") == "192.0.2.1", (_e4, _gwok))
_bad5, _e5 = P._validate_exits([{"id": "aaaa5555", "device": "eth2", "gw": "not-an-ip"}],
                               NODE, nics=NICS, gws=GWS, wan=WAN)
check("…and a gateway that is not an address is refused as one", _bad5 is None and "gateway" in str(_e5), _e5)

SNAPS = {"n1": {"ether_ifaces": NICS, "ether_gws": GWS, "wan_iface": WAN}}
_nodes = {"n1": dict(NODE, exits=[{"id": "aaaa1111", "device": "eth1", "producer": "adopted",
                                   "enabled": True, "killswitch": False},
                                  {"id": "aaaa2222", "device": "eth2", "producer": "adopted",
                                   "enabled": True, "killswitch": False},
                                  {"id": "aaaa3333", "device": "eth2", "producer": "adopted",
                                   "enabled": True, "killswitch": False, "gw": "192.0.2.1"}])}
check("the PLAN lowers the usable card", P.resolve_exit(_nodes, SNAPS, "n1", "aaaa1111") is not None)
check("…declines the gatewayless one", P.resolve_exit(_nodes, SNAPS, "n1", "aaaa2222") is None)
check("…and lowers it once it carries a typed gateway, handing that gateway to the node",
      (P.resolve_exit(_nodes, SNAPS, "n1", "aaaa3333") or (None,) * 5)[4] == "192.0.2.1",
      P.resolve_exit(_nodes, SNAPS, "n1", "aaaa3333"))

# ⚠️ THE ASYMMETRY, found in review: `nic_wan` is refused at the DOOR and tolerated once STORED. Every
# other verdict names something destructive, so going inert at plan time is the safe answer. `nic_wan`
# names a NO-OP — and the way a stored exit's device BECOMES the WAN is a failover, where dropping the exit
# would take its egress_ip, its kill-switch and its counter away at the worst possible moment.
_fail = {"n1": {"ether_ifaces": NICS, "ether_gws": GWS, "wan_iface": "eth1"}}
_r = P.resolve_exit(_nodes, _fail, "n1", "aaaa1111")
check("⚠️ a failover onto the exit's own card keeps the exit lowered", _r is not None, _r)
check("…with its source and kill-switch intact", _r and _r[3] == "" and _r[2] is False, _r)
check("…while a card with no gateway is STILL inert, because that one is destructive",
      P.resolve_exit(_nodes, _fail, "n1", "aaaa2222") is None)
check("…and creating one on the WAN is still refused at the door",
      P._validate_exits([{"id": "dddd4444", "device": "eth1"}], NODE,
                        nics=NICS, gws=GWS, wan="eth1")[0] is None)

_mnodes = {"n1": dict(NODE, exits=[])}
_id, _merr = P._mint_device_exit(_mnodes, "n1", "dev:eth1", SNAPS["n1"])
check("the MINT accepts a usable card", _id and not _merr, (_id, _merr))
_id2, _merr2 = P._mint_device_exit({"n1": dict(NODE, exits=[])}, "n1", "dev:eth0", SNAPS["n1"])
check("⚠️ …and refuses the WAN, which it could not even see before this step",
      not _id2 and "nic_wan" in str(_merr2), (_id2, _merr2))
_id3, _merr3 = P._mint_device_exit({"n1": dict(NODE, exits=[])}, "n1", "dev:eth2", SNAPS["n1"])
check("…and the gatewayless card", not _id3 and "nic_nogw" in str(_merr3), (_id3, _merr3))

print("\n[6] ⚠️ a NAT pin does not survive into a mode that never stores one")
# Found in review. `egressBody` sends `wan_iface` for direct/forward and NOT for smart/exit, so a pin set
# while the interface was direct was never overwritten on a switch — it sat in the record, kept shipping in
# `desired_ifaces`, and became the interface's BASELINE on the node. In smart mode that baseline is exactly
# what the `direct` categories leave by: one MASQUERADE out a card routing does not use, no baseline out the
# real WAN, and those categories die un-NATted. Invisible, because the control is not shown in that mode.
_nodes6 = {"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {},
                  "exits": [{"id": "x1", "producer": "adopted", "device": "tun0", "enabled": True}]},
           "n2": {"id": "n2", "name": "n2", "links": {}, "ifaces": {}, "exits": []}}
_deps6 = {"node_snaps": {}, "panel_settings": {}}
for _mode, _body in (("smart", {"egress_mode": "smart", "routing": []}),
                     ("exit", {"egress_mode": "exit", "exit_id": "x1"})):
    _rec = {"subnet": "10.17.0.0/24", "wan_iface": "eth2"}
    P._apply_egress_mode(_rec, _body, _nodes6, "n1", _deps6)
    check("switching to %s clears the stale NAT pin" % _mode, "wan_iface" not in _rec, _rec)
# ⚠️ …but `forward` KEEPS it, because `egressBody` does send it there — it is a live choice, not a leftover.
_recf = {"subnet": "10.17.0.0/24", "wan_iface": "eth2"}
P._apply_egress_mode(_recf, {"egress_mode": "forward", "egress_node": "n2"}, _nodes6, "n1", _deps6)
check("…while forward keeps it, because that mode does store one", _recf.get("wan_iface") == "eth2", _recf)

print("\n[7] AN EDIT MUST NOT CREATE THE STATE CREATION REFUSES")
# The tolerance for a stored device exists for state that moves UNDERNEATH the record — a card that became
# the WAN, a detected gateway that went away. Asking only "same id, same device" also tolerated the
# operator CLEARING the typed gateway that made a card legal, which stored a NIC exit with no way off the
# box: refused as a create, accepted as an edit, and then carrying nothing at all because the node's
# `_devfwd` correctly declines to lower a gatewayless card. Found live on msk-main, 1.8.5 qualification.
_KNOWN = [{"id": "e0000001", "device": "eth2", "label": "Lab uplink", "producer": "adopted", "gw": "192.0.2.1"}]
_V = lambda ex, prev=_KNOWN: P._validate_exits(ex, NODE, nics=NICS, gws=GWS, wan=WAN, prev=prev)

_ok, _err = _V([{"id": "e0000001", "device": "eth2", "label": "Lab uplink", "gw": "192.0.2.1"}])
check("the create that is legal stays legal on re-save", _err is None and _ok, _err)

_ok, _err = _V([{"id": "e0000001", "device": "eth2", "label": "Lab uplink", "gw": ""}])
check("clearing the typed gateway on a card with none detected is REFUSED",
      _ok is None and "nic_nogw" in str(_err), (_ok, _err))

# …and the failover case the tolerance exists for is untouched: same verdict before and after the edit.
_KW = [{"id": "e0000002", "device": "eth0", "label": "Uplink", "producer": "adopted", "gw": ""}]
_ok, _err = P._validate_exits([{"id": "e0000002", "device": "eth0", "label": "Renamed", "gw": ""}],
                              NODE, nics=NICS, gws=GWS, wan=WAN, prev=_KW)
check("a STORED exit whose device became the WAN still saves (the failover it exists for)",
      _err is None and _ok and _ok[0]["label"] == "Renamed", (_ok, _err))

# …and a stored card that merely LOST its detected gateway still saves — the other half of the same rule.
_KL = [{"id": "e0000003", "device": "eth2", "label": "Lab", "producer": "adopted", "gw": ""}]
_ok, _err = P._validate_exits([{"id": "e0000003", "device": "eth2", "label": "Lab renamed", "gw": ""}],
                              NODE, nics=NICS, gws=GWS, wan=WAN, prev=_KL)
check("a stored card that lost its DETECTED gateway still saves", _err is None and _ok, (_ok, _err))

# …and pointing an existing exit at a DIFFERENT bad card is still refused (the device test still carries).
_ok, _err = _V([{"id": "e0000001", "device": "eth0", "label": "Lab uplink", "gw": ""}])
check("re-pointing a stored exit at a refused card is still refused",
      _ok is None and "nic_wan" in str(_err), (_ok, _err))

print("")
if PERTURB2:
    ok = len(FAILS) > 0
    print(("perturbed: the id+device-only tolerance was CAUGHT (%d red)" % len(FAILS)) if ok
          else "perturbed: NOTHING FAILED — [6] is not actually gated")
    sys.exit(0 if ok else 1)
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the gateway tested before the WAN was CAUGHT (%d red)" % len(FAILS)) if ok
          else "perturbed: NOTHING FAILED — the ordering in [2] is not actually gated")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
