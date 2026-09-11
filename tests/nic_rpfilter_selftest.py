#!/usr/bin/env python3
"""Self-test for NIC-EXIT step 5 — rp_filter and the exit NIC (plan Q3).

An exit device's return traffic can arrive on an interface the reverse route does not name, which is what
strict rp_filter drops. The node's answer is `net.ipv4.conf.<dev>.rp_filter=2`, written and READ BACK for
every device in the cascade, and Q3's claim was that a NIC gets this "for free" because a device exit
arrives as a `fwd` entry. This gate holds that claim — for BOTH scopes, which is where it could quietly
fail: a rule-scoped device exit is deliberately NOT folded into `fwd` (its packets arrive by fwmark, and a
`from S lookup T` rule would drag the whole subnet out the device), so if `smart_exit` did not carry it
instead, a per-category NIC exit would get no loosening and no signal.

⚠️ ASKED, NOT WRITTEN. `_sysctl_ensure` takes an `ok` predicate, and the loop passes `_eff(cur) == 2`, so a
device sitting at 0 under an `all` of 2 is ALREADY correct and is deliberately not written — fewer forks,
and the documented behaviour. A gate asserting a per-device write would assert the opposite of what the
code is for. What matters is that the device is in the SET the pass consults.

⚠️ THE EFFECTIVE VALUE IS THE ONE THAT MATTERS: max(conf.all, conf.<dev>). A check reading the device alone
reports a healthy node broken. `_rp_effective` encodes that, and [3] pins both directions.

Measured in the rig (.campaign/nich/step5.sh) with a PERTURBED instrument — strict really does drop and
loose really does pass, counted at two nft hooks so "dropped by rp_filter" is distinguishable from "never
arrived". That run also corrected Q3's premise; see the plan's §3f.

Hermetic: no ip, no sysctl, no network.

Run: python3 tests/nic_rpfilter_selftest.py  (0 = pass)
     --perturb  removes the exit devices from the two places the loosening set is built — what a NIC exit
                given a lowering path of its own would look like — and expects RED.
"""
import importlib.machinery, importlib.util, os, sys, tempfile

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

# ⚠️ PERTURBED AT THE SOURCE, and both anchors asserted. The first draft of this file set a module flag
# nothing read — a perturbation that changes nothing, which is the shape that reports a clean pass over an
# untested fix ([[perturbation-harness-cannot-report-green]]).
_A1 = 'sorted(d for d in {_detect_wan()} | {e["via_iface"] for e in (fwd + smart_exit + exit_)}'
_A2 = 'for dev in sorted({"all", wan} | {e["via_iface"] for e in (fwd + smart_exit + exit_)}):'
if PERTURB:
    _src = open(NODED, encoding="utf-8").read()
    for _old, _new in ((_A1, 'sorted(d for d in {_detect_wan()}'), (_A2, 'for dev in sorted({"all", wan}):')):
        assert _src.count(_old) == 1, "perturbation anchor missing — this run would FALSE-PASS"
        _src = _src.replace(_old, _new, 1)
    _fd, NODED = tempfile.mkstemp(suffix=".py", prefix="perturbed-noded-", dir=HERE)
    os.write(_fd, _src.encode()); os.close(_fd)

N = _load(NODED, "swgnoded")
if PERTURB:
    os.unlink(NODED)

NIC, WAN, SUB = "eth2", "eth0", "10.17.0.0/24"

class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def _stub(vals=None):
    N.run = lambda argv, **kw: _R("")
    N._dev_link_state = lambda d: "up"
    N._dev_is_ether = lambda d: d.startswith("eth")
    N._dev_gateway = lambda d, _proc="/proc/net/route": "10.0.0.1" if d.startswith("eth") else ""
    N._table_default_via = lambda t, d: ""
    N._detect_wan = lambda: WAN
    N._ensure_fwd_iptables = lambda *a, **kw: None
    N._DEVEXIT["list"] = []

def pass_(devexit, smart=None):
    """One routing reconcile. → (devices the loosening pass consulted, what it wrote, bad list, needed)."""
    asked, wrote, vals = [], {}, {}
    def fake_sysctl(key, want, ok=None):
        dev = key.split(".")[-2]
        if key.endswith(".rp_filter"):
            asked.append(dev)
        cur = vals.get(dev, 0)
        if (ok or (lambda v: v == want))(cur):
            return cur
        wrote[dev] = want; vals[dev] = want
        return want
    _stub()
    N._sysctl_ensure = fake_sysctl
    N._rp_filter_val = lambda d: vals.get(d, 0)
    N.reconcile_cascade({"interfaces": {}}, {"devexit": devexit}, smart, "")
    return asked, wrote, list(N._RPF["bad"]), bool(N._RPF["needed"])

print("\n[1] a WHOLE-INTERFACE NIC exit reaches the loosening set")
DX = [{"subnet": SUB, "dev": NIC, "table": 7000, "killswitch": False, "egress_ip": "", "gw": ""}]
asked, wrote, bad, needed = pass_(DX)
check("the loosening is needed at all once an exit exists", needed)
check("conf.all is set loose", wrote.get("all") == 2, wrote)
check("…and the exit NIC is in the set the pass consults", NIC in asked, asked)
check("…and the node's own WAN, which the return path also crosses", WAN in asked, asked)
check("nothing is reported bad once the effective value is 2 everywhere", bad == [], bad)

print("\n[2] ⚠️ …and so does a RULE-SCOPED one, which is NOT folded into `fwd`")
DXR = [dict(DX[0], scope="rule")]
SMART = {"entries": [{"subnet": SUB, "category": "c1", "action": "exit", "via_iface": NIC, "table": 7000}],
         "mode": "kernel"}
asked, wrote, bad, needed = pass_(DXR, SMART)
check("a per-category NIC exit still reaches the loosening set", NIC in asked, asked)
check("…and is still reported as needing it", needed)

print("\n[3] the EFFECTIVE value decides — max(conf.all, conf.<dev>)")
_saved = N._rp_filter_val
N._rp_filter_val = lambda d: {NIC: 0}.get(d, 2)
check("a device left at 0 while `all` is 2 reads as 2, not 0", N._rp_effective(NIC, 2) == 2,
      N._rp_effective(NIC, 2))
N._rp_filter_val = lambda d: 1
check("…and 1 under an `all` of 1 stays 1 — the forgiving direction is not assumed",
      N._rp_effective(NIC, 1) == 1, N._rp_effective(NIC, 1))
N._rp_filter_val = lambda d: None
check("a device that is not there reads None, not 0 — absence is not a value",
      N._rp_effective(NIC, 2) is None)
N._rp_filter_val = _saved

print("\n[4] a box where the knob will not move SAYS SO")
# ⚠️ AND THE MODEL OF "CANNOT LOOSEN" HAS TO BE THE REAL ONE. Making only the NIC's knob stick while
# `conf.all` moves to 2 is not a failure at all — effective = max(all, dev) = 2, and the node is right to
# say nothing. The case this re-read exists for is a container's read-only /proc/sys, where NOTHING moves.
_stub()
N._sysctl_ensure = lambda key, want, ok=None: 1 if key.endswith(".rp_filter") else want
N._rp_filter_val = lambda d: 1
N.reconcile_cascade({"interfaces": {}}, {"devexit": DX}, None, "")
check("a box that cannot be loosened names the exit NIC in its bad list", NIC in N._RPF["bad"], N._RPF["bad"])
check("…and the WAN with it, since the return path crosses both", WAN in N._RPF["bad"], N._RPF["bad"])

print("")
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the exit device dropped from the loosening set was CAUGHT (%d red)" % len(FAILS))
          if ok else "perturbed: NOTHING FAILED — this gate does not test the loosening set")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
