#!/usr/bin/env python3
"""Self-test: a network's gateway only ever sees its own tunnel subnet — the node translates every other client.

⚠️ MEASURED through a real Keenetic on swgt (2026-09-17), set up exactly as the Networks window says (Allowed IPs, a route and a
permit for the gateway interface's own subnet): a client from that subnet (10.9.0.1) got HTTP 200; one from another interface's
(10.8.0.1, wg1) had its SYN delivered and the LAN host's SYN-ACK went to the router nine times in 38 s — never back into the tunnel,
because the router routes only the tunnel subnet back. The node carries a network to every client interface and to mesh arrivals,
with the client's own address as source, so only the gateway interface's own clients had a working path.

  [1] a carried network gets ONE tagged MASQUERADE: out the gateway interface, to the network, from anything NOT in that interface's
      subnet — so the gateway's own clients (and the node's own reachability test) keep their address
  [2] a second pass changes nothing
  [3] the interface's subnet moved → the rule is replaced, not duplicated
  [4] the network is no longer carried → its rule goes, by NUMBER (a nixpkgs iptables deletes the wrong rule by spec)
  [5] D1 — a node carrying nothing lists the NAT table once per process for leftovers, then never again; and a leftover from an
      earlier process is removed on that one look, with every rule that is not ours left alone
  [6] an interface name that could not be a device never reaches iptables
  [7] the routing pass calls it right after the routes it follows
  [8] a rule that would not go keeps the reconciler looking on later passes

Hermetic: `run()` is a small iptables that keeps the nat POSTROUTING chain in memory and prints it the way `iptables -S` does.

Run: python3 tests/network_snat_selftest.py        (0 = pass)
     --perturb       the routing pass never calls it → RED on [7]
     --perturb-src   the rule translates everyone, the gateway's own clients too → RED on [1]
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_SRC = "--perturb-src" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
CALL = "                    reconcile_net_snat(node_cfg, _nets, nr)"
INS = '''        a = run(["iptables", "-t", "nat", "-I", "POSTROUTING", "1", "!", "-s", sub, "-d", prefix, "-o", iface,'''
assert src.count(CALL) == 1 and src.count(INS) == 1, "an anchor moved — this run would FALSE-PASS"
if PERTURB:
    src = src.replace(CALL, "                    pass", 1)
if PERTURB_SRC:
    src = src.replace(INS, '''        a = run(["iptables", "-t", "nat", "-I", "POSTROUTING", "1", "-d", prefix, "-o", iface,''', 1)
if PERTURB or PERTURB_SRC:
    NODED = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(NODED, "w", encoding="utf-8").write(src)
_l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="netsnat-")
def conf(name, addr):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\nListenPort = 51820\n" % addr)
    return p
CFG = {"interfaces": {"wg1": {"cmd": ["wg"], "conf": conf("wg1", "10.8.0.1/24")},
                      "awg2": {"cmd": ["awg"], "conf": conf("awg2", "10.9.0.1/24")}}}


class Result:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


class FakeIptables:
    """nat POSTROUTING only, printed the way `iptables -S` prints it."""
    def __init__(self, rules=()):
        self.rules = list(rules)
        self.calls = []
        self.refuse_delete = False

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[:1] != ["iptables"]:
            return Result(0)
        a = argv[1:]
        if a[:2] != ["-t", "nat"]:
            return Result(0)
        a = a[2:]
        if a[:2] == ["-S", "POSTROUTING"]:
            body = ["-P POSTROUTING ACCEPT"] + self.rules
            if len(a) == 3:
                n = int(a[2])
                return Result(0, (self.rules[n - 1] + "\n") if 0 < n <= len(self.rules) else "")
            return Result(0, "\n".join(body) + "\n")
        if a[:2] == ["-D", "POSTROUTING"] and len(a) == 3:
            if self.refuse_delete:
                return Result(1, "", "iptables: Resource temporarily unavailable.")
            n = int(a[2])
            if 0 < n <= len(self.rules):
                del self.rules[n - 1]
                return Result(0)
            return Result(1, "", "Index of deletion too big.")
        if a[:3] == ["-I", "POSTROUTING", "1"]:
            spec, parts, i = a[3:], [], 0
            neg = False
            while i < len(spec):
                tok = spec[i]
                if tok == "!":
                    neg = True; i += 1; continue
                if tok in ("-s", "-d", "-o"):
                    parts.append(("! " if neg else "") + tok + " " + spec[i + 1]); neg = False; i += 2; continue
                if tok == "-m":
                    parts.append("-m " + spec[i + 1]); i += 2; continue
                if tok == "--comment":
                    parts.append('--comment "%s"' % spec[i + 1]); i += 2; continue
                if tok == "-j":
                    parts.append("-j " + spec[i + 1]); i += 2; continue
                return Result(2, "", "unknown option " + tok)
            order = lambda p: (0 if p.lstrip("! ").startswith("-s") else 1 if p.startswith("-d") else 2 if p.startswith("-o")
                               else 3 if p.startswith("-m") else 4 if p.startswith("--comment") else 5)
            self.rules.insert(0, "-A POSTROUTING " + " ".join(sorted(parts, key=order)))
            return Result(0)
        return Result(1, "", "unsupported: %s" % a)


def fresh(rules=()):
    fake = FakeIptables(rules)
    N.run = fake
    N._NETSNAT.update({"checked": False, "have": 0})
    return fake

def ours(fake):
    return [r for r in fake.rules if "swg-net-snat:" in r]

EGRESS = '-A POSTROUTING -s 10.9.0.0/24 -o eth0 -j MASQUERADE'
FOREIGN = '-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE'

print("[1] a carried network gets one translation, and the gateway's own clients are left out of it")
fake = fresh([EGRESS, FOREIGN])
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG, [("192.168.2.0/24", "awg2")], res)
r1 = ours(fake)
check("exactly one rule for the network", len(r1) == 1, fake.rules)
rule = r1[0] if r1 else ""
check("…out the gateway interface, to the network", " -o awg2" in rule and " -d 192.168.2.0/24" in rule, rule)
check("…translating only what is NOT from the gateway interface's own subnet (its clients, and the node's own test, keep theirs)",
      "! -s 10.9.0.0/24" in rule and rule.count("-s ") == 1, rule)
check("…by MASQUERADE, i.e. to the interface's own address", rule.endswith("-j MASQUERADE"), rule)
check("…and every other POSTROUTING rule is where it was", EGRESS in fake.rules and FOREIGN in fake.rules, fake.rules)
check("…counted as a change, with no error", res == {"changed": 1, "errors": []}, res)

print("\n[2] a second pass changes nothing")
before = list(fake.rules); fake.calls.clear()
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG, [("192.168.2.0/24", "awg2")], res)
check("the table is untouched", fake.rules == before and res["changed"] == 0, (fake.rules, res))
check("…and nothing was inserted or deleted", not any(c[3:4] in (["-I"], ["-D"]) for c in fake.calls), fake.calls)

print("\n[3] the interface's subnet moves → the rule is replaced, not duplicated")
CFG2 = {"interfaces": dict(CFG["interfaces"], awg2={"cmd": ["awg"], "conf": conf("awg2b", "10.19.0.1/24")})}
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG2, [("192.168.2.0/24", "awg2")], res)
r3 = ours(fake)
check("one rule, now excluding the new subnet", len(r3) == 1 and "! -s 10.19.0.0/24" in r3[0], r3)

print("\n[4] the network is no longer carried → its rule goes, by number")
fake.calls.clear()
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG2, [], res)
check("no translation left", not ours(fake), fake.rules)
check("…deleted by position, never by spec", any(c[:5] == ["iptables", "-t", "nat", "-D", "POSTROUTING"] and len(c) == 6 and c[5].isdigit()
                                               for c in fake.calls), fake.calls)
check("…and the others still stand", EGRESS in fake.rules and FOREIGN in fake.rules, fake.rules)
fake.calls.clear()
N.reconcile_net_snat(CFG2, [], {"changed": 0, "errors": []})
check("…after which a node carrying nothing asks iptables nothing", fake.calls == [], fake.calls)

print("\n[5] D1 — a node that carries nothing, and a leftover from an earlier process")
fake = fresh([EGRESS])
N.reconcile_net_snat(CFG, [], {"changed": 0, "errors": []})
check("the first pass lists the table once, and changes nothing", len(fake.calls) == 1 and fake.rules == [EGRESS], fake.calls)
fake.calls.clear()
for _ in range(3):
    N.reconcile_net_snat(CFG, [], {"changed": 0, "errors": []})
check("…and never again", fake.calls == [], fake.calls)
LEFT = '-A POSTROUTING ! -s 10.9.0.0/24 -d 10.50.0.0/16 -o awg2 -m comment --comment "swg-net-snat:awg2:10.50.0.0/16" -j MASQUERADE'
fake = fresh([EGRESS, LEFT, FOREIGN])
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG, [], res)
check("a leftover translation is removed on the one look", not ours(fake) and res["changed"] == 1, (fake.rules, res))
check("…and nothing that is not ours is touched", fake.rules == [EGRESS, FOREIGN], fake.rules)

print("\n[6] an interface name that could not be a device never reaches iptables")
fake = fresh([])
CFG3 = {"interfaces": dict(CFG["interfaces"], **{"bad name;x": {"cmd": ["wg"], "conf": conf("bad", "10.7.0.1/24")}})}
N.reconcile_net_snat(CFG3, [("192.168.9.0/24", "bad name;x")], {"changed": 0, "errors": []})
check("no rule and no insert for it", not ours(fake) and not any("-I" in c for c in fake.calls), fake.calls)

print("\n[7] the routing pass calls it right after the routes it follows")
live = open(NODED, encoding="utf-8").read()
i = live.find("_nets = reconcile_net_routes(node_cfg, reply[\"desired\"], nr)")
nxt = live[i:i + 400].splitlines()[1] if i >= 0 else ""
check("the line after the routes is the translation", "reconcile_net_snat(node_cfg, _nets, nr)" in nxt, nxt)

print("\n[8] a rule that would not go keeps the reconciler looking")
fake = fresh([LEFT])
fake.refuse_delete = True
res = {"changed": 0, "errors": []}
N.reconcile_net_snat(CFG, [], res)
check("the failure is reported", res["errors"] and "could not remove" in res["errors"][0], res)
fake.refuse_delete = False; fake.calls.clear()
N.reconcile_net_snat(CFG, [], {"changed": 0, "errors": []})
check("…and the next pass looks again and removes it", not ours(fake) and fake.calls, (fake.rules, fake.calls))

print()
if PERTURB or PERTURB_SRC:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red" % len(FAILS)) if ok else "PERTURB FAILED — the fix was undone and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
