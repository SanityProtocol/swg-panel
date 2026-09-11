#!/usr/bin/env python3
"""Self-test for NIC-EXIT step 4 — the SNAT, and the baseline it must not delete.

`swg-noded` records the measured trap this exists to hold: the device-exit SNAT is tagged
`swg-egress:exit:<subnet>` and that tag is LOAD-BEARING. `_has_foreign_egress` treats any POSTROUTING line
source-NATting the same subnet as foreign UNLESS its comment contains the literal `swg-egress:` — so tag the
exit SNAT anything more descriptive (`swg-devexit:`, `swg-exit-snat:`) and `_egress_des` returns None, the
interface's BASELINE MASQUERADE is deleted, and the interface loses direct internet *silently*.

That is already gated for a tunnel exit. This file exists because a NIC exit is the case where the two rules
stop being obviously different things: **both the exit device and the interface's WAN are now network
cards**, matched by `-o`, on the same subnet. So the question "does the baseline survive" has to be asked of
a POSTROUTING that actually contains the exit's rule, not of a hand-built pair.

⚠️ THE SEAM IS THE SUBJECT. Both halves of this were already green in isolation — `_ensure_fwd_iptables`
adds the tagged rule, and `_has_foreign_egress` says a hand-written line with that tag is not foreign. What
neither proves is that the rule the FIRST one writes is the rule the SECOND one reads. So [3] runs the real
`reconcile_egress` against a fake kernel that the real `_ensure_fwd_iptables` has just written into, and
asks what actually ended up in POSTROUTING ([[two-readers-one-grammar]]).

Hermetic: no ip, no iptables, no network — `run()` is a fake kernel that KEEPS STATE, so `-I` and `-D`
actually change what the next reader sees.

Run: python3 tests/nic_exit_snat_selftest.py  (0 = pass)
     --perturb  renames the tag out of the `swg-egress:` namespace, the way a descriptive name would, and
                expects the baseline to be gone from the final POSTROUTING.
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
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

N = _load(NODED, "swgnoded")

WAN, NIC, SUB, IF = "eth0", "eth2", "10.17.0.0/24", "awg0"

class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc

class Kernel:
    """A POSTROUTING that remembers. `-I` prepends, `-D` removes — so what one reconcile writes is what the
    next one reads, which is the whole point of this file."""
    def __init__(s, lines=()): s.post = list(lines)
    def run(s, argv, **kw):
        if not isinstance(argv, list):
            argv = ["sh", "-c", str(argv)]
        if argv[:2] == ["sh", "-c"]:                       # the delete path shells out with a rebuilt line
            m = re.search(r"-D POSTROUTING (.*)$", argv[2])
            if m:
                s.post = [ln for ln in s.post if ln != "-A POSTROUTING " + m.group(1).strip()]
            return _R("")
        if argv[:4] == ["iptables", "-t", "nat", "-S"]:
            return _R("\n".join(s.post) + ("\n" if s.post else ""))
        if argv[:5] == ["iptables", "-t", "nat", "-I", "POSTROUTING"]:
            a = argv[5:]
            g = lambda f: (a[a.index(f) + 1] if f in a else "")
            s.post.insert(0, '-A POSTROUTING -s %s -o %s -m comment --comment "%s" -j %s%s'
                          % (g("-s"), g("-o"), g("--comment"), a[a.index("-j") + 1],
                             (" --to-source " + g("--to-source")) if "--to-source" in a else ""))
        return _R("")

def wire(k, devexit, ifaces):
    """One full datapath pass in the order a sync runs it: the cascade's exit SNAT, then the interface's."""
    N.run = k.run
    N._detect_wan = lambda: WAN
    N._iface_subnet = lambda cfg, i: SUB
    N._iface_is_mesh = lambda cfg, i, sub: False
    N._ensure_dev_rules = lambda *a, **kw: None            # FORWARD/MSS is §5.10's subject, not this one
    N._wdtt_load = lambda: {}
    res = {"changed": 0, "errors": []}
    N._ensure_fwd_iptables([], [], WAN, res, "", devexit=devexit)
    N.reconcile_egress({"interfaces": {IF: {"conf": "/dev/null"}}}, ifaces, "")
    return res

if PERTURB:
    # The obvious implementation: a tag that says what it is. It reads better, and it deletes the baseline.
    _orig = N._snat_reconcile_rule
    N._snat_reconcile_rule = lambda tag, subnet, des, rules: _orig(
        tag.replace("swg-egress:exit:", "swg-devexit:"), subnet, des, rules)

DX = [{"subnet": SUB, "dev": NIC, "table": 7000, "killswitch": False, "egress_ip": "", "gw": ""}]
OV = {IF: {"egress_ip": "", "wan_iface": "", "egress_mode": "exit", "exit_id": "x1"}}

print("\n[1] the exit's own SNAT leaves by the NIC, under the load-bearing tag")
k = Kernel(); res = wire(k, DX, OV)
ex = [ln for ln in k.post if "swg-egress:exit:" in ln or "swg-devexit:" in ln]
check("a SNAT is added for the exit's subnet out the NIC, not out the WAN",
      any("-s %s" % SUB in ln and "-o %s" % NIC in ln and "MASQUERADE" in ln for ln in ex), k.post)
check("…tagged inside the swg-egress: namespace",
      any('"swg-egress:exit:%s"' % SUB in ln for ln in ex), ex)
check("no errors from the pass", not res["errors"], res["errors"])

print("\n[2] …and MASQUERADE is right here, unlike the unnumbered-device case the field exists for")
# §3c T2, measured on the wire: `MASQUERADE -o n1` made the upstream see n1's OWN address, and without the
# rule at all it was 100% loss. A NIC cannot be unnumbered — `_node_addrs` requires a non-loopback IPv4
# before a device reaches `ether_ifaces` — so the kernel's answer is the card's address, which is the one
# the operator meant. Nothing to change; the gate is that nothing tries to.
check("no --to-source is invented for a NIC exit with no egress_ip set",
      not any("--to-source" in ln for ln in ex), ex)
k2 = Kernel(); wire(k2, [dict(DX[0], egress_ip="203.0.113.50")], OV)
check("…and an operator who pins one still gets SNAT --to-source, out the NIC",
      any("--to-source 203.0.113.50" in ln and "-o %s" % NIC in ln for ln in k2.post), k2.post)

print("\n[3] ⚠️ THE SEAM — the baseline the exit's rule must not delete")
base = [ln for ln in k.post if '"swg-egress:%s"' % IF in ln]
check("the interface's baseline MASQUERADE is still in POSTROUTING after the exit's SNAT was written",
      len(base) == 1, "POSTROUTING:\n    " + "\n    ".join(k.post))
check("…and it leaves by the WAN, so the two rules cannot match the same packet",
      base and "-o %s" % WAN in base[0], base)
check("…asked of the real classifier too: our own exit tag is not foreign",
      N._has_foreign_egress(SUB, k.post) is False,
      "foreign=True ⇒ _egress_des returns None ⇒ the baseline is deleted, silently")

print("\n[4] a rule somebody ELSE wrote still defers the baseline — the exemption is not a blanket")
k3 = Kernel(['-A POSTROUTING -s %s -o %s -j MASQUERADE' % (SUB, WAN)])     # a legacy PostUp, untagged
wire(k3, DX, OV)
check("a foreign SNAT for the same subnet is still read as foreign",
      N._has_foreign_egress(SUB, k3.post) is True, k3.post)
check("…so the baseline defers to it instead of stacking a duplicate",
      not any('"swg-egress:%s"' % IF in ln for ln in k3.post), k3.post)

print("\n[5] a NIC exit that is NOT lowered still gets its SNAT — inert, and deliberately so")
# `_ensure_fwd_iptables` is handed the RAW plan list, not the folded-in one, so a device with no gateway
# (and a device that is down) keeps a SNAT that matches nothing. That is the existing behaviour for a dead
# device and it is the right one: the rule is harmless while no route sends traffic there, and it is
# already correct the moment a gateway appears. What matters is that it does not disturb the baseline.
k4 = Kernel(); wire(k4, DX, OV)     # DX has gw:"" — never folded in by reconcile_cascade
check("the SNAT exists even with no gateway to route by",
      any("swg-egress:exit:" in ln or "swg-devexit:" in ln for ln in k4.post), k4.post)
check("…and the baseline is still there beside it",
      any('"swg-egress:%s"' % IF in ln for ln in k4.post), k4.post)

print("\n[6] the case a NIC exit newly makes possible: the exit device IS the interface's pinned NIC")
# Not reachable from the UI — `onIf` clears the NIC when an exit is chosen — but the API takes the two
# fields independently, and only now can they name the same device. Both rules then match the same packets
# and the FIRST one wins, which is whichever was written last. Recorded rather than defended against: with
# both MASQUERADE the outcome is identical, and the shapes that could disagree are named in the plan.
k5 = Kernel(); wire(k5, DX, {IF: {"egress_ip": "", "wan_iface": NIC, "egress_mode": "exit", "exit_id": "x1"}})
_both = [ln for ln in k5.post if "-o %s" % NIC in ln]
check("both rules exist and both leave by the same card", len(_both) == 2, k5.post)
check("…and they are still distinguishable by tag, so neither reconciler eats the other",
      len({re.search(r'--comment "([^"]+)"', ln).group(1) for ln in _both if '--comment' in ln}) == 2, _both)

print("")
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the out-of-namespace tag was CAUGHT (%d red) — the baseline would have died" % len(FAILS))
          if ok else "perturbed: NOTHING FAILED — this gate does not actually test the tag")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
