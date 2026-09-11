#!/usr/bin/env python3
"""Self-test — WHICH DEVICE IS THIS NODE'S WAY OUT, asked of the default route rather than of 1.1.1.1.

`_detect_wan` (swg-noded) and `_wan_iface` (swg-agent) answer the same question for the same reason: the
`-o` of every egress SNAT, the device whose rp_filter is loosened, and the interface the SWG_INET counters
hang on. Both used `ip route get 1.1.1.1`, which follows ANY host route for that address.

⚠️ WHY THAT MATTERS HERE AND NOT ELSEWHERE: this product's entire job is putting routes in front of
destinations. Observed on hel-flux during 1.8.5 qualification — a `1.1.1.1 via <gw> dev lab0` added for an
unrelated test moved every interface's egress SNAT to `-o lab0` on the next pass while the traffic still
left by eth0, so the rule matched nothing, no peer was SNAT'd, and every 10.x source went out raw. Silent,
total, and one static route wide.

⚠️ TWO READERS, ONE GRAMMAR. A gate that checked only swg-noded would let the agent keep the old probe, and
the agent WRITES the rule the node then reconciles — a disagreement is a rule rewritten on every pass. Both
implementations are driven here, through a fake `ip`, off the same table.

Run: python3 tests/wan_detect_selftest.py       (0 = pass)
     --perturb   restores the `route get 1.1.1.1` probe in BOTH and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# The kernel's answers, for one box: a normal default out eth0, and a HOST ROUTE for 1.1.1.1 out lab0.
# `route get` follows the host route; `route show default` cannot see it. That difference is the whole gate.
TABLES = {
    "normal": {
        "show_default": "default via 172.31.1.1 dev eth0 proto dhcp src 89.167.2.2 metric 100\n",
        "get_1111":     "1.1.1.1 via 172.31.1.1 dev eth0 src 89.167.2.2 uid 0\n"},
    "hijacked": {   # the live shape found on hel-flux
        "show_default": "default via 172.31.1.1 dev eth0 proto dhcp src 89.167.2.2 metric 100\n",
        "get_1111":     "1.1.1.1 via 10.99.0.1 dev lab0 src 10.99.0.2 uid 0\n"},
    "two_defaults": {   # a VPN default at a better metric — the kernel would pick tun0, so must we
        "show_default": ("default dev tun0 scope link metric 50\n"
                         "default via 172.31.1.1 dev eth0 proto dhcp metric 100\n"),
        "get_1111":     "1.1.1.1 dev tun0 src 10.7.0.2 uid 0\n"},
    "multipath": {
        "show_default": ("default proto static\n"
                         "\tnexthop via 172.31.1.1 dev eth0 weight 1\n"
                         "\tnexthop via 10.0.0.1 dev eth1 weight 1\n"),
        "get_1111":     "1.1.1.1 via 172.31.1.1 dev eth0 uid 0\n"},
    "no_default": {   # a fully policy-routed box: only the probe can answer, so the fallback must survive
        "show_default": "",
        "get_1111":     "1.1.1.1 via 10.0.0.1 dev ens5 src 10.0.0.9 uid 0\n"},
}
CASE = {"t": "normal"}

def _fake_out(argv):
    """Answer the two shapes both implementations issue, from the case under test."""
    s = " ".join(argv) if isinstance(argv, (list, tuple)) else str(argv)
    t = TABLES[CASE["t"]]
    if "route show default" in s:
        return t["show_default"]
    if "route get 1.1.1.1" in s:
        return t["get_1111"]
    return ""

def _load(path, name, run_impl):
    src = open(path, encoding="utf-8").read()
    if PERTURB:
        # Put the probe back, in BOTH — the exact code this gate exists to keep out.
        src = re.sub(r"    best, best_metric = \"\", None\n(?:.|\n)*?    if best:\n        return best\n",
                     "", src, count=2)
        assert "best, best_metric" not in src, "perturbation did not remove both — this run would FALSE-PASS"
    fd, tmp = tempfile.mkstemp(suffix=".py", prefix="wan-" + name + "-", dir=HERE)
    os.write(fd, src.encode()); os.close(fd)
    l = importlib.machinery.SourceFileLoader(name, tmp)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    os.unlink(tmp)
    mod.run = run_impl
    return mod

class _R:      # swg-noded's run() returns an object with .stdout
    def __init__(self, s): self.stdout = s; self.returncode = 0; self.stderr = ""
ND = _load(os.path.join(ROOT, "swg-noded"), "wnoded", lambda a, **k: _R(_fake_out(a)))
# swg-agent's run() returns the string itself
AG = _load(os.path.join(ROOT, "swg-agent"), "wagent", lambda a, **k: _fake_out(a))

print("[1] the WAN is read off the default route, not off a probe that a host route can steer")
for case, want in (("normal", "eth0"), ("hijacked", "eth0"), ("two_defaults", "tun0"),
                   ("multipath", "eth0"), ("no_default", "ens5")):
    CASE["t"] = case
    gn, ga = ND._detect_wan(), AG._wan_iface()
    check("swg-noded  %-13s -> %s" % (case, want), gn == want, gn)
    check("swg-agent  %-13s -> %s" % (case, want), ga == want, ga)

print("\n[2] TWO READERS, ONE GRAMMAR — they must not merely each be right, they must AGREE")
for case in TABLES:
    CASE["t"] = case
    check("agree on %s" % case, ND._detect_wan() == AG._wan_iface(),
          (ND._detect_wan(), AG._wan_iface()))

print("")
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the 1.1.1.1 probe was CAUGHT (%d red)" % len(FAILS)) if ok
          else "perturbed: NOTHING FAILED — this gate does not actually pin the WAN read")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
