#!/usr/bin/env python3
"""NETWORKS §17 F2–F4: DNS to a network the node CARRIES is let past the Force DNS redirect, and the node says so.

`swg-noded` `_smart_dns_redirect(subnets, res, nets)` against a fake `iptables -t nat` PREROUTING that prints the way
`iptables -S` does (a `-m udp` after `-p udp`, Docker's jump already there):

  [1] a carried network: two RETURNs (udp, tcp) ABOVE the two DNATs, Docker's jump untouched, dns_redirect reported
  [2] a second pass changes nothing — the RETURN is not mistaken for a DNAT (the tags share a prefix)
  [3] a RETURN found BELOW a DNAT (exempts nothing) is moved back above in one pass; the pass after is quiet
  [4] a /32 network reads back as the kernel prints it and converges
  [5] the network goes: its RETURNs go, the DNATs stay, dns_redirect disappears (D1)
  [6] the redirect goes: every rule of ours goes, Docker's stays
  [7] the call site hands `_ensure_smart_dnsmasq` the node's own `nets`, and that function hands them on

  --perturb-append     RETURNs appended like DNATs     → [3] red (within one pass they happen to land above; a repair
                                                          appends them below the DNATs, where they exempt nothing)
  --perturb-noorder    no order repair                 → [3] red
  --perturb-substring  the old substring tag test      → [2] red (a RETURN re-added every pass)
"""
import os, re, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.path.join(HERE, "..", "swg-noded")
MODE = next((a[len("--perturb-"):] for a in sys.argv[1:] if a.startswith("--perturb-")), "")

src = open(NODED).read()
PERTURB = {
    "append": ('run(["iptables", "-t", "nat", "-I", "PREROUTING", "1"] + xrule(S, P, proto))',
               'run(["iptables", "-t", "nat", "-A", "PREROUTING"] + xrule(S, P, proto))'),
    "noorder": ("    if order_bad:                                              # a RETURN below a DNAT exempts nothing",
                "    if False:                                                  # a RETURN below a DNAT exempts nothing"),
    "substring": ('        if tag == SMARTDNS_TAG and "-j DNAT" in ln:', '        if SMARTDNS_TAG in ln:'),
}
if MODE:
    a, b = PERTURB[MODE]
    assert src.count(a) == 1, "perturbation anchor missing: " + MODE
    src = src.replace(a, b)
N = types.ModuleType("swgnoded")
N.__dict__["__name__"] = "swgnoded"
N.__dict__["__file__"] = NODED                  # the node reads its VERSION beside itself
try:
    exec(compile(src, NODED, "exec"), N.__dict__)
except SystemExit:
    pass

FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


DOCKER = "-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER"
CHAIN = [DOCKER]


def render(args):
    out, i = [], 0
    while i < len(args):
        out.append(args[i])
        if args[i] == "-p":                       # iptables -S prints the implicit protocol match
            out += [args[i + 1], "-m", args[i + 1]]
            i += 2
            continue
        i += 1
    return "-A PREROUTING " + " ".join(out)


def fake_run(cmd, *a, **k):
    ok = types.SimpleNamespace(returncode=0, stdout="", stderr="")
    if cmd[:1] != ["iptables"]:
        return ok
    c = cmd[1:]
    if c[:2] == ["-t", "nat"]:
        c = c[2:]
    op, chain, rest = c[0], c[1], c[2:]
    assert chain == "PREROUTING", cmd
    if op == "-S":
        if rest:
            n = int(rest[0])
            return types.SimpleNamespace(returncode=0, stdout=(CHAIN[n - 1] + "\n") if 0 < n <= len(CHAIN) else "", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="-P PREROUTING ACCEPT\n" + "".join(l + "\n" for l in CHAIN), stderr="")
    if op == "-A":
        CHAIN.append(render(rest)); return ok
    if op == "-I":
        CHAIN.insert(int(rest[0]) - 1, render(rest[1:])); return ok
    if op == "-D":
        if len(rest) == 1 and rest[0].isdigit():
            del CHAIN[int(rest[0]) - 1]; return ok
        line = render(rest)
        if line in CHAIN:
            CHAIN.remove(line); return ok
        return types.SimpleNamespace(returncode=1, stdout="", stderr="no such rule")
    raise AssertionError(cmd)


N.run = fake_run
N._route_localnet_ok = lambda: True
S = "10.8.0.0/24"
OFFICE = ("192.168.50.0/24", "wg0")


def ours(kind):
    return [i for i, l in enumerate(CHAIN) if ("swg-smartdns-net" in l) == (kind == "x") and "swg-smartdns" in l]


def converge(subnets, nets):
    res = {"changed": 0, "errors": []}
    N._smart_dns_redirect(subnets, res, nets=[p for p, _ in nets])
    return res["changed"]


print("[1] a carried network")
ch = converge([S], [OFFICE])
X, D = ours("x"), ours("d")
check("two RETURNs and two DNATs", len(X) == 2 and len(D) == 2, CHAIN)
check("every RETURN above every DNAT", X and D and max(X) < min(D), CHAIN)
check("each RETURN is scoped to the smart subnet, the network, and :53",
      all(("-s 10.8.0.0/24" in CHAIN[i] and "-d 192.168.50.0/24" in CHAIN[i] and "--dport 53" in CHAIN[i]
           and CHAIN[i].endswith("-j RETURN")) for i in X), CHAIN)
check("Docker's jump is still there", DOCKER in CHAIN, CHAIN)
check("the node reports it", N._SMART_MODE.get("dns_redirect") == {"subnets": [S], "exempt": ["192.168.50.0/24"]},
      N._SMART_MODE.get("dns_redirect"))

print("[2] steady state")
before = list(CHAIN)
check("a second pass changes nothing", converge([S], [OFFICE]) == 0 and CHAIN == before, CHAIN)

print("[3] order drift")
for i in sorted(ours("x"), reverse=True):
    CHAIN.append(CHAIN.pop(i))                   # something moved our RETURNs below the DNATs
X, D = ours("x"), ours("d")
check("(the drift is real: RETURNs now below the DNATs)", min(X) > max(D), CHAIN)
ch = converge([S], [OFFICE])
X, D = ours("x"), ours("d")
check("one pass puts them back above", ch > 0 and len(X) == 2 and max(X) < min(D), CHAIN)
check("…and the pass after is quiet", converge([S], [OFFICE]) == 0, CHAIN)

print("[4] a single-host network")
ch = converge([S], [OFFICE, ("172.30.9.9/32", "wg0")])
check("a /32 is added once", len(ours("x")) == 4 and any("-d 172.30.9.9/32" in l for l in CHAIN), CHAIN)
check("…and converges", converge([S], [OFFICE, ("172.30.9.9/32", "wg0")]) == 0, CHAIN)

print("[5] the network goes")
converge([S], [])
check("its RETURNs go, the DNATs stay", ours("x") == [] and len(ours("d")) == 2, CHAIN)
check("dns_redirect disappears (D1: nothing exempt → nothing new in the snapshot)", "dns_redirect" not in N._SMART_MODE,
      N._SMART_MODE.get("dns_redirect"))

print("[6] the redirect goes")
converge([S], [OFFICE])
converge([], [OFFICE])
check("every rule of ours goes, Docker's stays", CHAIN == [DOCKER], CHAIN)
check("nothing reported", "dns_redirect" not in N._SMART_MODE)

print("[7] the node's own nets reach the redirect")
check("reconcile_cascade hands its `nets` to _ensure_smart_dnsmasq",
      "_ensure_smart_dnsmasq(domains, _dns_e, res, unchanged=dom_unchanged, zones=_zones, nets=nets)" in src)
check("…which hands the prefixes to the redirect",
      "_smart_dns_redirect(subnets if want else [], res, nets=[p for p, _i in (nets or ())])" in src)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED" % len(FAILS)))
sys.exit(1 if FAILS else 0)
