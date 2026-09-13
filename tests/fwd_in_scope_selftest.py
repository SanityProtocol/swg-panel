#!/usr/bin/env python3
"""Self-test — tunnel FORWARD accepts no longer open Docker's containers.

MEASURED (.campaign/rigs/docker-bridge-exposure.sh): on Docker older than 28 with FORWARD policy DROP, swg-noded's
`-i <tunnel> -j ACCEPT` at the top of FORWARD made every container's unpublished ports reachable from every client.
The fix sends tunnel-originated packets through SWG_FWD_IN, which RETURNs anything bound into a Docker bridge to
FORWARD (Docker's chains decide) and accepts the rest. What can go wrong without anything saying so:

  [1] the chain's contents: the RETURNs only where Docker manages FORWARD — a hand-made `br-lan` on a ufw host must
      not lose its clients — in RETURN-then-ACCEPT order.
  [2] converged once per loop, rebuilt only when it drifts.
  [3] ⚠️ THE MIGRATION. `_ensure_dev_rules` used to call a rule present by tag + direction, so an existing node's
      `-j ACCEPT` would have read as already right and the fix would never have reached it. It is replaced — one
      rule, not two — and a second pass changes nothing.
  [4] the MSS clamp (`-j TCPMSS --clamp-mss-to-pmtu`) does not churn under the target-aware presence test.
  [5] fail-safe: a chain that cannot be created leaves plain ACCEPTs — scoping must never stop forwarding.
  [6] the mesh/exit family goes through the same door.
  [7] ⚠️ an iptables whose spec delete cannot tell `-i` from `-o` (MEASURED: nixpkgs 1.8.11, the nixos node). A delete
      by spec there took the return-path `-o` accept and left the stale `-i` one. Stale rules go by NUMBER now: one
      pass, the right rule, and a second pass changes nothing. The fake is checked to really be that blind.
  [8] the WDTT teardown deletes by number too — every rule with exactly its tag, never a longer tag.

Hermetic: a small in-memory iptables. Run: python3 tests/fwd_in_scope_selftest.py   (0 = pass)
     --perturb          ignores Docker when building the chain (no RETURNs) and expects RED on [1].
     --perturb-delete   puts back the delete by spec and expects RED on [7].
"""
import importlib.machinery, importlib.util, os, re, shlex, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_DELETE = "--perturb-delete" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
CP = N.subprocess.CompletedProcess
if PERTURB:
    _w = N._fwd_in_want
    N._fwd_in_want = lambda lines: _w([])
if PERTURB_DELETE:
    N._ipt_del_listed = lambda targs, chain, ln: N.run(["sh", "-c", "iptables " + " ".join(targs) + " " +
                                                        ln.replace("-A " + chain, "-D " + chain, 1)]).returncode == 0

class Ipt:
    """filter/mangle chains as `iptables -S` prints them. Enough to watch rules appear, move and disappear."""
    def __init__(self, forward=(), mangle=(), can_create=True, blind=False, nat=()):
        self.t = {"filter": {"FORWARD": list(forward)}, "mangle": {"FORWARD": list(mangle)},
                  "nat": {"POSTROUTING": list(nat)}}
        self.can_create = can_create
        self.blind = blind          # nixpkgs 1.8.11: a spec delete matches `-i X` and `-o X` alike, first one wins
        self.calls = []
    def norm(self, ln):
        return re.sub(r'"', "", ln).strip()
    def __call__(self, args, input_text=None, timeout=20):
        self.calls.append(list(args))
        if args[:2] == ["sh", "-c"]:
            args = shlex.split(args[2])
        if args[0] != "iptables":
            return CP(args, 0, "", "")
        a = list(args[1:]); table = "filter"
        if a[:1] == ["-t"]:
            table, a = a[1], a[2:]
        ch = self.t[table]
        op, name, rest = a[0], a[1], a[2:]
        if op == "-S":
            if name not in ch:
                return CP(args, 1, "", "iptables: No chain/target/match by that name.")
            if rest and rest[0].isdigit():
                i = int(rest[0]) - 1
                return CP(args, 0, (ch[name][i] + "\n") if 0 <= i < len(ch[name]) else "", "")
            return CP(args, 0, "\n".join(["-P FORWARD ACCEPT" if name == "FORWARD" else "-N " + name] + ch[name]) + "\n", "")
        if op == "-N":
            if not self.can_create:
                return CP(args, 1, "", "iptables: Permission denied")
            ch[name] = []
            return CP(args, 0, "", "")
        if op == "-F":
            ch[name] = []
            return CP(args, 0, "", "")
        line = "-A %s %s" % (name, " ".join(shlex.quote(x) if " " in x else x for x in rest))
        if op == "-A":
            ch[name].append(line)
        elif op == "-I":
            ch[name].insert(0, line)
        elif op == "-D" and len(rest) == 1 and rest[0].isdigit():
            i = int(rest[0]) - 1
            if not 0 <= i < len(ch[name]):
                return CP(args, 1, "", "iptables: Index of deletion too big.")
            del ch[name][i]
        elif op == "-D":
            key = (lambda l: re.sub(r"-[io] (\S+)", r"-io \1", self.norm(l))) if self.blind else self.norm
            hit = next((i for i, l in enumerate(ch[name]) if key(l) == key(line)), None)
            if hit is None:
                return CP(args, 1, "", "iptables: Bad rule (does a matching rule exist in that chain?).")
            del ch[name][hit]
        return CP(args, 0, "", "")
    def fwd(self):
        return self.t["filter"]["FORWARD"]
    def chain(self):
        return self.t["filter"].get("SWG_FWD_IN")

DOCKER = ["-A FORWARD -j DOCKER-USER", "-A FORWARD -j DOCKER-FORWARD"]
def loop():
    N._LOOP["n"] += 1
def fresh(**kw):
    ipt = Ipt(**kw); N.run = ipt; loop()
    return ipt

print("\n[1] the chain")
ipt = fresh(forward=DOCKER); res = {"changed": 0, "errors": []}
check("created where it was missing", N._ensure_fwd_in_chain(res) and ipt.chain() is not None, ipt.calls)
check("on a Docker host: RETURN into docker0, RETURN into br-+, then ACCEPT — in that order",
      ipt.chain() == ["-A SWG_FWD_IN -o docker0 -j RETURN", "-A SWG_FWD_IN -o br-+ -j RETURN", "-A SWG_FWD_IN -j ACCEPT"], ipt.chain())
ipt = fresh(forward=[])
N._ensure_fwd_in_chain({"changed": 0, "errors": []})
check("with no Docker: ACCEPT only — a hand-made br-lan keeps its clients", ipt.chain() == ["-A SWG_FWD_IN -j ACCEPT"], ipt.chain())

print("\n[2] once per loop, rebuilt only on drift")
ipt = fresh(forward=DOCKER)
N._ensure_fwd_in_chain({"changed": 0, "errors": []}); n = len(ipt.calls)
N._ensure_fwd_in_chain({"changed": 0, "errors": []})
check("a second call in the same loop forks nothing", len(ipt.calls) == n, ipt.calls[n:])
loop(); del ipt.calls[:]; res = {"changed": 0, "errors": []}
N._ensure_fwd_in_chain(res)
check("next loop, unchanged: read, not rebuilt", res["changed"] == 0 and not any(c[1:2] in (["-F"], ["-A"]) for c in ipt.calls), ipt.calls)
ipt.t["filter"]["FORWARD"] = []; loop(); res = {"changed": 0, "errors": []}
N._ensure_fwd_in_chain(res)
check("Docker gone: rebuilt without the RETURNs", res["changed"] == 1 and ipt.chain() == ["-A SWG_FWD_IN -j ACCEPT"], ipt.chain())

print("\n[3] the migration from what every node carries today")
OLD = ['-A FORWARD -i wg0 -m comment --comment "swg-egress-acl:wg0" -j ACCEPT',
       '-A FORWARD -o wg0 -m comment --comment "swg-egress-acl:wg0" -j ACCEPT']
ipt = fresh(forward=OLD + DOCKER); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0"], res)
ins = [l for l in ipt.fwd() if "-i wg0" in l]; outs = [l for l in ipt.fwd() if "-o wg0" in l]
check("the old `-i wg0 … -j ACCEPT` is REPLACED by a jump to SWG_FWD_IN — one rule, not two",
      len(ins) == 1 and ins[0].endswith("-j SWG_FWD_IN"), ins)
check("the `-o wg0` accept (into the tunnel) is untouched", outs == [OLD[1]], outs)
check("…and it sits above Docker's chains, where the old one was", ipt.fwd().index(ins[0]) < ipt.fwd().index(DOCKER[0]), ipt.fwd())
loop(); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0"], res)
check("a second pass changes nothing", res["changed"] == 0, (res, ipt.fwd()))

print("\n[4] the MSS clamp does not churn under the target-aware test")
MSS = ['-A FORWARD -o wg0 -p tcp -m tcp --tcp-flags SYN,RST SYN -m comment --comment "swg-egress-mss:wg0" -j TCPMSS --clamp-mss-to-pmtu']
ipt = fresh(mangle=MSS); res = {"changed": 0, "errors": []}
N._ensure_dev_rules("mangle", "FORWARD", "swg-egress-mss:", ["wg0"], res,
                    lambda d, direction: (["iptables", "-t", "mangle", "-I", "FORWARD", "-o", d, "-p", "tcp", "--tcp-flags",
                                           "SYN,RST", "SYN", "-m", "comment", "--comment", "swg-egress-mss:" + d,
                                           "-j", "TCPMSS", "--clamp-mss-to-pmtu"] if direction == "-o" else None))
check("an existing clamp is present, not replaced", res["changed"] == 0 and ipt.t["mangle"]["FORWARD"] == MSS, (res, ipt.calls))

print("\n[5] fail-safe")
ipt = fresh(forward=OLD + DOCKER, can_create=False); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0"], res)
check("a chain that cannot be created leaves plain ACCEPTs — clients keep forwarding, and it is said",
      [l for l in ipt.fwd() if "-i wg0" in l] == [OLD[0]] and res["errors"], (ipt.fwd(), res))
ipt = fresh(forward=DOCKER); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", [], res)
check("no tunnel devices: the chain is not even asked about", not any(c[1:3] == ["-S", "SWG_FWD_IN"] for c in ipt.calls), ipt.calls)

print("\n[6] mesh links and device exits go through the same door")
ipt = fresh(forward=['-A FORWARD -i swg_ab12 -m comment --comment "swg-fwd-acl:swg_ab12" -j ACCEPT'] + DOCKER)
N._ensure_tunnel_acl("swg-fwd-acl:", ["swg_ab12"], {"changed": 0, "errors": []})
check("`-i swg_ab12` now jumps to SWG_FWD_IN", any(l.startswith("-A FORWARD -i swg_ab12") and l.endswith("-j SWG_FWD_IN") for l in ipt.fwd()), ipt.fwd())

print("\n[7] ⚠️ an iptables that cannot tell -i from -o in a spec (nixpkgs 1.8.11, measured)")
# the order an old noded leaves: each `-I` put the `-o` rule above the `-i` one
OLDER = ['-A FORWARD -o wg0 -m comment --comment "swg-egress-acl:wg0" -j ACCEPT',
         '-A FORWARD -i wg0 -m comment --comment "swg-egress-acl:wg0" -j ACCEPT',
         '-A FORWARD -o wg1 -m comment --comment "swg-egress-acl:wg1" -j ACCEPT',
         '-A FORWARD -i wg1 -m comment --comment "swg-egress-acl:wg1" -j ACCEPT']
probe = Ipt(forward=OLDER[:2], blind=True)
probe(["iptables", "-D", "FORWARD", "-i", "wg0", "-m", "comment", "--comment", "swg-egress-acl:wg0", "-j", "ACCEPT"])
check("the fake is really that blind: a spec delete of `-i wg0` takes the `-o wg0` rule", probe.fwd() == [OLDER[1]], probe.fwd())
ipt = fresh(forward=OLDER + DOCKER, blind=True); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0", "wg1"], res)
for d in ("wg0", "wg1"):
    ins = [l for l in ipt.fwd() if "-i %s " % d in l]; outs = [l for l in ipt.fwd() if "-o %s " % d in l]
    check("one pass, %s: the only `-i` rule jumps to SWG_FWD_IN — the stale ACCEPT is gone" % d,
          len(ins) == 1 and ins[0].endswith("-j SWG_FWD_IN"), ipt.fwd())
    check("one pass, %s: the `-o` return-path accept is still there" % d,
          outs == ['-A FORWARD -o %s -m comment --comment "swg-egress-acl:%s" -j ACCEPT' % (d, d)], ipt.fwd())
check("no rule text ever went through a shell", not any(c[:2] == ["sh", "-c"] for c in ipt.calls), [c for c in ipt.calls if c[:2] == ["sh", "-c"]])
loop(); res = {"changed": 0, "errors": []}
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0", "wg1"], res)
check("a second pass changes nothing", res["changed"] == 0, (res, ipt.fwd()))
ipt = fresh(forward=['-A FORWARD -i gone0 -m comment --comment "swg-egress-acl:gone0" -j SWG_FWD_IN',
                     '-A FORWARD -o gone0 -m comment --comment "swg-egress-acl:gone0" -j ACCEPT'] + DOCKER, blind=True)
N._ensure_tunnel_acl("swg-egress-acl:", ["wg0"], {"changed": 0, "errors": []})
check("an interface that went away loses both of its rules", not any("gone0" in l for l in ipt.fwd()), ipt.fwd())

print("\n[8] the WDTT teardown deletes by number: exactly its tag, never a longer one")
NAT = ['-A POSTROUTING -s 10.7.0.0/24 -o eth0 -m comment --comment "swg-egress:wdtt7" -j MASQUERADE',
       '-A POSTROUTING -s 10.77.0.0/24 -o eth0 -m comment --comment "swg-egress:wdtt77" -j MASQUERADE',
       '-A POSTROUTING -s 10.7.0.0/24 -o eth1 -m comment --comment "swg-egress:wdtt7" -j MASQUERADE']
ipt = fresh(nat=NAT, blind=True)
N._wdtt_del_iptables_comment("nat", "POSTROUTING", "swg-egress:wdtt7")
check("both wdtt7 rules gone, wdtt77 kept", ipt.t["nat"]["POSTROUTING"] == [NAT[1]], ipt.t["nat"]["POSTROUTING"])

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
