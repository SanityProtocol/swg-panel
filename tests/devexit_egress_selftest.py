#!/usr/bin/env python3
"""Self-test for the DEVICE-EXIT EGRESS SOURCE — `egress_ip` on an adopted exit (plan §11, decision 12).

Traffic leaving by a device exit is SNAT'd `-o <dev>`, and the default is MASQUERADE, which asks the kernel
"what source would you use out this device?". Measured in a netns, that answer splits:

    exA  10.66.0.2/32   ip route get 1.1.1.1 oif exA  →  src 10.66.0.2   ✓ the device's own address
    exB  unnumbered     ip route get 1.1.1.1 oif exB  →  src 10.17.0.1   ✗ the CLIENT subnet's

An operator's adopted device is one somebody else set up — a corporate tunnel, a router's wg, a container's
veth — and nothing makes it carry an address. In the second row every packet leaves with the internal wg
address: it leaks the private subnet upstream and is dropped there, while `ip link` still says up, the route
still resolves, and the panel still paints the exit green. Nothing anywhere reports it. That is the failure
this field exists to make impossible, and the reason it is worth a gate of its own.

WHAT IS COVERED, and why each half would fail alone:

  the panel STORES it   including the deliberate non-checks. The address is NOT validated against the node's
                        own IP list, because it belongs to a device somebody else runs and the panel sees
                        only what the node happened to report — refusing an address we cannot see would
                        block the exact case this exists for. And it is adopted-only: an imported exit's
                        device is ours, minted with its own /32.
  the plan CARRIES it   the seam. This tree has already shipped a devexit that was computed at one end,
                        consumed at the other, and carried by nobody in between — three reviews missed it
                        because every gate fed a hand-built dict. So the value is followed from a stored
                        exit through `resolve_exit` into the entry the node actually receives, on BOTH
                        scopes (whole-interface and per-rule).
  the node LOWERS it    SNAT with `--to-source` when set, MASQUERADE when blank — and, the case with no
                        symptom, that CHANGING it rewrites the rule. A diff that compared only action and
                        device would call a stale `--to-source` "already correct" and leave the node
                        SNAT'ing to an address the operator has since replaced, forever.

Hermetic: no ip, no iptables, no network — the node's `run` is a fake kernel.

Run: python3 tests/devexit_egress_selftest.py  (0 = pass)
     --perturb  removes the field from the validator's record and the SNAT choice from the node — the
                "MASQUERADE is always right" reading this was built to disprove — and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys

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

def _perturbed(path, cut, put, tag):
    """Write a copy of `path` with `cut` replaced by `put`. Asserts the anchor exists — a perturbation whose
    anchor has drifted patches NOTHING and the run comes back green, which reads exactly like a pass."""
    src = open(path, encoding="utf-8").read()
    assert src.count(cut) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % tag
    tmp = os.path.join(HERE, ".perturbed-" + tag + ".py")
    open(tmp, "w", encoding="utf-8").write(src.replace(cut, put, 1))
    return tmp

_tmps = []
if PERTURB:
    # Both ends of the seam, because either one alone silently reverts the whole feature to MASQUERADE.
    NODED = _perturbed(NODED, '_des = ("SNAT", dev, _eg) if _eg else ("MASQUERADE", dev, "")',
                       '_des = ("MASQUERADE", dev, "")', "noded")
    PANEL = _perturbed(PANEL, '            out["egress_ip"] = _eg\n', "", "panel")
    _tmps = [NODED, PANEL]

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
for _t in _tmps:
    os.unlink(_t)

NODE = {"ifaces": {"awg0": {}}, "wdtt": {}, "csqtt": {}}
EG = "203.0.113.9"

# ── 1. the panel stores the field, and stores it only where it means something ────────────────────
good, err = P._validate_exits([{"device": "tun-lab0", "label": "Lab", "egress_ip": EG}], NODE)
check("an adopted exit keeps the egress source the operator typed",
      err is None and good and good[0].get("egress_ip") == EG, (err, good))
_blank, _e2 = P._validate_exits([{"device": "tun-lab0"}], NODE)
check("…and the key is present even when blank, so the SPA's rebuild cannot drop it",
      _e2 is None and _blank and "egress_ip" in _blank[0], _blank)
check("…blank means MASQUERADE, not a missing field", bool(_blank) and _blank[0].get("egress_ip") == "", _blank)
_bad, _e3 = P._validate_exits([{"device": "tun-lab0", "egress_ip": "not-an-ip"}], NODE)
check("a value that is not an IPv4 address is refused", _bad is None and _e3, (_bad, _e3))
# ⚠️ THE DELIBERATE NON-CHECK. The address lives on a device somebody else runs; the panel knows only what
# the node happened to report about it. Refusing what we cannot see would block the case this exists for.
_far, _e4 = P._validate_exits([{"device": "tun-lab0", "egress_ip": "198.51.100.77"}], NODE)
check("an address this node never reported is ACCEPTED — the panel does not police a foreign device",
      _e4 is None and _far and _far[0].get("egress_ip") == "198.51.100.77", (_e4, _far))
_imp, _e5 = P._validate_exits([{"producer": "imported", "provider": "warp", "egress_ip": EG}], NODE)
check("an IMPORTED exit never carries one — the panel made that device and gave it its address",
      _e5 is None and _imp and "egress_ip" not in _imp[0], (_e5, _imp))

# ── 2. the seam — a STORED exit's value reaches the entry the node receives ───────────────────────
# ⚠️ THE STORED RECORDS COME OUT OF THE VALIDATOR, not out of a literal. The devexit seam bug this tree
# already shipped survived three reviews because every gate hand-built the dict it fed in, so each end was
# tested against a record the other end never produced. The chain under test is operator input → validator
# → store → cascade_plan → the entry on the wire, and it is only a chain if the first link is real.
EXITS, _sverr = P._validate_exits(
    [{"id": "aabbccdd", "label": "Lab", "device": "tun-lab0", "egress_ip": EG},
     {"id": "11223344", "label": "Plain", "device": "tun-lab1"}], NODE)
check("the seam's fixture is the VALIDATOR's own output, not a hand-built dict",
      _sverr is None and len(EXITS or []) == 2
      and [x["id"] for x in EXITS] == ["aabbccdd", "11223344"], (_sverr, EXITS))
EXITS = EXITS or []
SNAPS = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}},
                               "awg1": {"meta": {"subnet": "10.18.0.0/24"}}}}}

def plan(ifaces):
    return P.cascade_plan({"n1": {"name": "n1", "links": {}, "exits": [dict(x) for x in EXITS],
                                  "ifaces": ifaces}}, SNAPS).get("n1", {})

_r = P.resolve_exit({"n1": {"name": "n1", "links": {}, "exits": [dict(x) for x in EXITS]}},
                    SNAPS, "n1", "aabbccdd")
check("resolve_exit answers with the egress source, so no caller has to re-read the exit",
      _r and len(_r) == 5 and _r[3] == EG, _r)
# …and with the typed gateway, for the same reason and in the same tuple: a NIC exit needs one, and a
# second lookup somewhere else is how the callers come to disagree about which gateway an exit has.
check("…and with the exit's typed gateway in the same answer", _r and _r[4] == "", _r)

_p = plan({"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"},
           "awg1": {"egress_mode": "exit", "exit_id": "11223344"}})
_dx = {e["dev"]: e for e in (_p.get("devexit") or [])}
check("a whole-interface exit hands the node the source (the seam this tree has broken before)",
      _dx.get("tun-lab0", {}).get("egress_ip") == EG, _p.get("devexit"))
check("…and an exit without one hands it a blank, never a missing key",
      _dx.get("tun-lab1", {}).get("egress_ip") == "", _p.get("devexit"))

_pr = plan({"awg0": {"egress_mode": "smart",
                     "routing": [{"enabled": True, "category": "netflix",
                                  "action": "dev", "exit_id": "aabbccdd"}]}})
_dxr = [e for e in (_pr.get("devexit") or []) if e.get("scope") == "rule"]
check("a PER-RULE device exit carries it too — the two scopes share one SNAT",
      len(_dxr) == 1 and _dxr[0].get("egress_ip") == EG, _pr.get("devexit"))

# ── 2b. an exit that cannot carry traffic falls back to the node's DEFAULT, not to the node's own IP ──
# ⚠️ THE POINT OF AN EXIT IS THAT THE NODE'S ADDRESS DOES NOT APPEAR. An interface pinned to an exit the
# operator has since DISABLED used to drop through to the plain route and egress from exactly that address —
# the one thing the feature exists to prevent — while the picker still showed the exit it was pinned to.
# Decision 3 is unchanged (degrade, never refuse the edit); this is only about WHAT it degrades to, and the
# answer is what every un-pinned interface on the node already uses.
def plan_with(default_exit, exits):
    nodes = {"n1": {"name": "n1", "links": {}, "exits": [dict(x) for x in exits],
                    "default_exit": default_exit,
                    "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"}}}}
    return P.cascade_plan(nodes, SNAPS).get("n1", {})

_OFF = [dict(EXITS[0], enabled=False), dict(EXITS[1])]
_dv = {e["dev"]: e for e in (plan_with("11223344", _OFF).get("devexit") or [])}
check("a disabled exit's traffic leaves by the node's DEFAULT exit instead",
      "tun-lab1" in _dv and "tun-lab0" not in _dv, list(_dv))
check("…carrying the DEFAULT's egress source, because it is the default's traffic now",
      _dv.get("tun-lab1", {}).get("egress_ip") == "", _dv.get("tun-lab1"))
check("with no node default it still degrades to direct, exactly as before",
      not (plan_with("", _OFF).get("devexit") or []), plan_with("", _OFF).get("devexit"))
check("…and so does a node whose default is the very exit that was disabled",
      not (plan_with("aabbccdd", _OFF).get("devexit") or []), plan_with("aabbccdd", _OFF).get("devexit"))
check("a healthy pinned exit is never re-pointed at the default",
      [e["dev"] for e in (plan_with("11223344", EXITS).get("devexit") or [])] == ["tun-lab0"],
      plan_with("11223344", EXITS).get("devexit"))

# ── 2c. "everything else", unspoken, is the node's default ───────────────────────────────────────
# ⚠️ A SMART INTERFACE CHOSE PER CATEGORY, NOT FOR THE REMAINDER. Decision 4 says the node default is beaten
# by any interface that chose for itself; traffic no rule matches made no choice, so it inherits — the same
# rule an un-pinned interface follows. It used to leave by the node's plain route and egress from the node's
# own address on a node whose stated default was an exit, and the catch-all displayed "Direct (this node)"
# while it happened, which is a value nobody had picked: that is simply what an untouched control showed.
def smart_plan(default_exit, rules):
    nodes = {"n1": {"name": "n1", "links": {}, "exits": [dict(x) for x in EXITS],
                    "default_exit": default_exit,
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": rules}}}}
    return P.cascade_plan(nodes, SNAPS).get("n1", {})

_RULE = [{"enabled": True, "category": "netflix", "action": "direct"}]
_p = smart_plan("aabbccdd", _RULE)
_all = [e for e in (_p.get("smart") or []) if e.get("category") == "all"]
check("with nothing said about the rest, it goes out the node's default exit",
      len(_all) == 1 and _all[0].get("via_iface") == "tun-lab0", _p.get("smart"))
check("…lowered as the catch-all the operator would have written by hand, not a new shape",
      _all and _all[0].get("action") == "exit", _all)
check("…with the SNAT that leaving by a device requires",
      any(e.get("dev") == "tun-lab0" and e.get("scope") == "rule" for e in (_p.get("devexit") or [])),
      _p.get("devexit"))
check("a node with no default leaves the remainder alone, exactly as before",
      not [e for e in (smart_plan("", _RULE).get("smart") or []) if e.get("category") == "all"],
      smart_plan("", _RULE).get("smart"))
# ⚠️ AND SAYING IT WINS. An explicit "Everything else → Direct" is a stored rule, and the whole point of
# storing it is that the node default must not overrule what the operator actually chose.
_said = smart_plan("aabbccdd", _RULE + [{"enabled": True, "category": "all", "action": "direct"}])
_sa = [e for e in (_said.get("smart") or []) if e.get("category") == "all"]
check("an explicit Direct for the rest beats the node default", len(_sa) == 1 and _sa[0]["action"] == "direct", _sa)
check("…and installs no device exit for it", not (_said.get("devexit") or []), _said.get("devexit"))
# …and an explicit catch-all pointing at ANOTHER exit is the case the inherit must not double up on:
# two "all" entries for one subnet is a first-match chain arguing with itself.
_oth = smart_plan("aabbccdd", _RULE + [{"enabled": True, "category": "all", "action": "dev", "exit_id": "11223344"}])
_oa = [e for e in (_oth.get("smart") or []) if e.get("category") == "all"]
check("an explicit catch-all OUT ANOTHER EXIT wins, and is not doubled by the inherit",
      len(_oa) == 1 and _oa[0].get("via_iface") == "tun-lab1", _oa)
_blk = smart_plan("aabbccdd", _RULE + [{"enabled": True, "category": "all", "action": "block"}])
check("…and so does an explicit Block",
      [e["action"] for e in (_blk.get("smart") or []) if e["category"] == "all"] == ["block"], _blk.get("smart"))

# ── 3. the node lowers it, and re-lowers it when it changes ──────────────────────────────────────
class _R:
    def __init__(self, out="", rc=0):
        self.stdout, self.stderr, self.returncode = out, "", rc

def nat_pass(entries, live=()):
    """One reconcile_cascade against a fake kernel holding `live` POSTROUTING lines → its nat argv."""
    seen = []
    def run(argv, **kw):
        a = [str(x) for x in (argv if isinstance(argv, list) else [argv])]
        if a[:5] == ["iptables", "-t", "nat", "-S", "POSTROUTING"]:
            return _R("\n".join(live))
        if "iptables" in " ".join(a) and " nat " in " ".join(a) + " ":
            seen.append(" ".join(a))
        return _R("")
    N.run = run
    N._dev_link_state = lambda d: "up"
    N._DEVEXIT["list"] = []
    N.reconcile_cascade({"interfaces": {}}, {"devexit": [dict(e) for e in entries]}, None, "")
    return [x for x in seen if "POSTROUTING" in x]

E_SNAT = {"subnet": "10.17.0.0/24", "dev": "tun-lab0", "table": 7000, "killswitch": False, "egress_ip": EG}
E_MASQ = dict(E_SNAT, egress_ip="")

c = nat_pass([E_SNAT])
_ins = [x for x in c if "-I POSTROUTING" in x]
check("with a source pinned the node SNATs to it",
      len(_ins) == 1 and "-j SNAT" in _ins[0] and "--to-source " + EG in _ins[0], c)
check("…scoped to the exit device and the forwarded subnet, not to everything",
      _ins and "-o tun-lab0" in _ins[0] and "-s 10.17.0.0/24" in _ins[0], _ins)
check("…and tagged, so the node can find its own rule again",
      _ins and "swg-egress:exit:10.17.0.0/24" in _ins[0], _ins)

c = nat_pass([E_MASQ])
_ins = [x for x in c if "-I POSTROUTING" in x]
check("with the field blank it falls back to MASQUERADE — the kernel's answer, unchanged",
      len(_ins) == 1 and "-j MASQUERADE" in _ins[0] and "--to-source" not in _ins[0], c)

def live_line(rule_argv):
    """The `-I POSTROUTING …` the node just issued, as `iptables -S` would read it back."""
    return re.sub(r"^iptables -t nat -I POSTROUTING", "-A POSTROUTING", rule_argv) \
             .replace('--comment swg-egress', '--comment "swg-egress').replace(" -j ", '" -j ', 1)

L_SNAT = live_line([x for x in nat_pass([E_SNAT]) if "-I " in x][0])
L_MASQ = live_line([x for x in nat_pass([E_MASQ]) if "-I " in x][0])

check("a settled node with the SNAT already in place touches nothing", not nat_pass([E_SNAT], [L_SNAT]),
      nat_pass([E_SNAT], [L_SNAT]))
check("…and so does one on MASQUERADE", not nat_pass([E_MASQ], [L_MASQ]), nat_pass([E_MASQ], [L_MASQ]))

# ⚠️ THE ONE WITH NO SYMPTOM. A diff on action+device alone calls a stale --to-source "already correct",
# and the node keeps SNAT'ing to an address the operator replaced — on a screen showing the new one.
c = nat_pass([dict(E_SNAT, egress_ip="198.51.100.77")], [L_SNAT])
check("changing the source REWRITES the rule — one delete, one insert",
      len([x for x in c if "-D POSTROUTING" in x]) == 1
      and len([x for x in c if "-I POSTROUTING" in x]) == 1
      and any("--to-source 198.51.100.77" in x for x in c), c)

c = nat_pass([E_MASQ], [L_SNAT])
_ins = [x for x in c if "-I POSTROUTING" in x]
check("clearing it goes back to MASQUERADE instead of leaving the old SNAT standing",
      any("-D POSTROUTING" in x for x in c) and len(_ins) == 1 and "-j MASQUERADE" in _ins[0], c)
c = nat_pass([E_SNAT], [L_MASQ])
check("…and setting one on a MASQUERADE'd exit replaces that rule rather than stacking beside it",
      len([x for x in c if "-I POSTROUTING" in x]) == 1
      and any("-D POSTROUTING" in x for x in c), c)

# ── 4. the node REPORTS what it used, so the panel is never guessing ──────────────────────────────
nat_pass([E_SNAT])
_rep = list(N._DEVEXIT["list"])
check("the node echoes the pinned source back, so the panel shows what the node works from",
      _rep and _rep[0].get("egress_ip") == EG, _rep)
nat_pass([E_MASQ])
check("…and reports the blank as a blank rather than inventing the kernel's choice",
      (list(N._DEVEXIT["list"]) or [{}])[0].get("egress_ip") == "", N._DEVEXIT["list"])

print("")
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All checks passed.")
