#!/usr/bin/env python3
"""Self-test for the device-exit SNAT when ONE subnet leaves by TWO exit devices — the exit NAT flip.

A smart interface that routes two categories to two device exits hands `swg-noded` two `devexit` entries with the same
subnet. The SNAT used to be tagged by subnet alone (`swg-egress:exit:<subnet>`), and `_snat_reconcile_rule` keeps exactly
one rule per tag, so every pass rewrote that one rule to the other device: the exit not holding it sent its traffic out
with the private source. Measured before the fix in a netns with the real function (two dummy exits, four passes): the
rule alternated exA → exB → exA, one change a pass, and traffic out the exit without the rule was not NATed. On swgt it
was the `cascade~1` of every sync. The tag is `swg-egress:exit:<subnet>@<device>` now.

  [1] two exits on one subnet: pass 1 writes one rule per device; passes 2–4 change nothing and both stay
  [2] the upgrade: a rule of the old shape is swept, and only AFTER both new rules are in (never a moment with no NAT)
  [3] one exit taken away: its rule goes, the other is not touched
  [4] one exit named twice (the whole interface and one rule): one rule, stable
  [5] a device name the kernel could not give an interface: no rule, an error, and nothing run through a shell
  [6] a single exit: one rule, and a second pass changes nothing — as before
  [7] the rule stays inside the `swg-egress:` namespace, so the interface's baseline NAT is not read as foreign

Hermetic: `run()` is a fake kernel that KEEPS STATE, so what one pass writes is what the next reads.
Run: python3 tests/devexit_two_exits_snat_selftest.py            (0 = pass)
     --perturb   keys the tag by subnet again and expects RED on [1].
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
SUB = "10.9.0.0/24"

class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc

class Kernel:
    """A POSTROUTING that remembers, and a log of every mutation in order."""
    def __init__(s, lines=()): s.post, s.log, s.shells = list(lines), [], []
    def run(s, argv, **kw):
        if argv[:2] == ["sh", "-c"]:
            s.shells.append(argv[2])
            m = re.search(r"-D POSTROUTING (.*)$", argv[2])
            if m:
                ln = "-A POSTROUTING " + m.group(1).strip()
                if ln in s.post:
                    s.post.remove(ln)
                    s.log.append(("D", ln))
            return _R("")
        if argv[:4] == ["iptables", "-t", "nat", "-S"]:
            return _R("\n".join(s.post) + ("\n" if s.post else ""))
        if argv[:5] == ["iptables", "-t", "nat", "-I", "POSTROUTING"]:
            a = argv[5:]
            g = lambda f: (a[a.index(f) + 1] if f in a else "")
            ln = '-A POSTROUTING -s %s -o %s -m comment --comment "%s" -j %s%s' % (
                g("-s"), g("-o"), g("--comment"), a[a.index("-j") + 1], (" --to-source " + g("--to-source")) if "--to-source" in a else "")
            s.post.insert(0, ln)
            s.log.append(("I", ln))
        return _R("")

N._ensure_dev_rules = lambda *a, **kw: None           # FORWARD/MSS toward the device is another gate's subject
N._ensure_tunnel_acl = lambda *a, **kw: None

if PERTURB:
    # The shape before the fix: one tag per subnet, whatever the device.
    _orig = N._snat_reconcile_rule
    N._snat_reconcile_rule = lambda tag, subnet, des, rules: _orig(tag.split("@")[0], subnet, des, rules)

def run_pass(k, devexit):
    N.run = k.run
    res = {"changed": 0, "errors": []}
    N._ensure_fwd_iptables([], [], "eth0", res, "", devexit=devexit)
    return res

def exits(k):
    return sorted(re.search(r"-o (\S+)", ln).group(1) for ln in k.post if "swg-egress:exit:" in ln)

E = lambda dev, **kw: dict({"subnet": SUB, "dev": dev, "table": 7001 if dev == "exA" else 7002, "killswitch": False,
                            "scope": "rule", "egress_ip": "", "gw": ""}, **kw)
TWO = [E("exA"), E("exB")]

print("\n[1] two exits on one subnet")
k = Kernel()
r1 = run_pass(k, TWO)
check("pass 1: one rule out each device", exits(k) == ["exA", "exB"], k.post)
flips = []
for p in (2, 3, 4):
    r = run_pass(k, TWO)
    flips.append((p, r["changed"], exits(k)))
check("passes 2–4 change nothing, and both rules stay", all(c == 0 and e == ["exA", "exB"] for _p, c, e in flips), flips)
check("no errors", not r1["errors"], r1["errors"])

if not PERTURB:
    print("\n[2] the upgrade from the old one-tag rule")
    OLD = '-A POSTROUTING -s %s -o exB -m comment --comment "swg-egress:exit:%s" -j MASQUERADE' % (SUB, SUB)
    k2 = Kernel([OLD])
    run_pass(k2, TWO)
    check("after one pass: a rule out each device, and the old-shape rule is gone", exits(k2) == ["exA", "exB"] and OLD not in k2.post, k2.post)
    ins = [i for i, (op, _ln) in enumerate(k2.log) if op == "I"]
    dels = [i for i, (op, ln) in enumerate(k2.log) if op == "D" and ln == OLD]
    check("…swept only after BOTH new rules were in — the subnet was never without NAT", len(ins) == 2 and dels and dels[0] > max(ins), k2.log)
    check("…and the next pass is quiet", run_pass(k2, TWO)["changed"] == 0)

    print("\n[3] one exit taken away")
    k3 = Kernel()
    run_pass(k3, TWO)
    keep = next(ln for ln in k3.post if "-o exA" in ln)
    k3.log.clear()
    run_pass(k3, [E("exA")])
    check("its rule goes, the other stays", exits(k3) == ["exA"], k3.post)
    check("…and the remaining rule was not rewritten", keep in k3.post and not any(ln == keep for _op, ln in k3.log), k3.log)

    print("\n[4] one exit named twice")
    k4 = Kernel()
    run_pass(k4, [E("exA", scope="iface"), E("exA")])
    check("one rule", exits(k4) == ["exA"], k4.post)
    check("…and it stays put", run_pass(k4, [E("exA", scope="iface"), E("exA")])["changed"] == 0)

    print("\n[5] a device name no interface could have")
    k5 = Kernel()
    r5 = run_pass(k5, [E("ex;reboot"), E("exA")])
    check("no rule for it, and the good exit still gets one", exits(k5) == ["exA"], k5.post)
    check("…the refusal is reported", any("refused device name" in x for x in r5["errors"]), r5["errors"])
    check("…and the name never reached a shell or a rule", not any("reboot" in x for x in k5.shells + k5.post), (k5.shells, k5.post))

    print("\n[6] a single exit")
    k6 = Kernel()
    run_pass(k6, [E("exA")])
    check("one rule, tagged with its subnet AND device", len(k6.post) == 1 and '"swg-egress:exit:%s@exA"' % SUB in k6.post[0], k6.post)
    check("…and a second pass changes nothing", run_pass(k6, [E("exA")])["changed"] == 0)

    print("\n[7] the baseline still reads our rule as ours")
    base = '-A POSTROUTING -s %s -o eth0 -m comment --comment "swg-egress:awg2" -j MASQUERADE' % SUB
    check("_has_foreign_egress is False beside both exit rules", N._has_foreign_egress(SUB, [base] + k.post) is False, k.post)

print("")
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the subnet-only tag was CAUGHT (%d red) — the flip is back" % len(FAILS)) if ok
          else "perturbed: NOTHING FAILED — this gate does not test the tag's key")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
