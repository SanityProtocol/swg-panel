#!/usr/bin/env python3
"""Self-test: the divert can name a LEG, and a whole-interface cascade is untouched by that.

A source-keyed divert (`ip saddr <subnet>`) can say "this interface's traffic". It cannot say "the
destinations this interface routes over leg X", which is the only thing a smart cascade is about — so Relay
was barred there. The routing engine already writes the leg down as a packet mark (the mark IS the table
number) and `swg_relay` already hooks at mangle+10, AFTER `swg_smart` at mangle. So the divert matches the
mark, and the relay puts it back on its upstream with SO_MARK.

⚠️ EVERY CHECK HERE EXISTS BECAUSE THE FORWARD PATH IS THE ONE RUNNING ON REAL FLEETS. `mark == 0` means a
whole-interface cascade and must stay byte-identical on the wire: no mark match, no --mark, same instance
name, same port. §4 is that regression, and it is the half of this gate that matters most today.

Run: python3 tests/relay_multileg_selftest.py (0 = pass)
     --perturb        scopes the `socket transparent` rule by mark too, RED.
     --perturb-mss    asks the kernel for the leg without the mark, RED.
     --perturb-fwd    makes forward mode emit a mark match, RED.
     --perturb-ctstate  lets the socket rule match a SYN again, RED.
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
P_SOCK = "--perturb" in sys.argv
P_MSS = "--perturb-mss" in sys.argv
P_FWD = "--perturb-fwd" in sys.argv
P_CTST = "--perturb-ctstate" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
def cut(a, b, why):
    global src
    assert a in src, "perturbation anchor missing (%s) — this run would FALSE-PASS" % why
    src = src.replace(a, b, 1)

if P_SOCK:   # the shipped-regression shape: scope the established-connection rule by mark as well
    cut('L.append("    ip saddr %s ct state != new meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept" % (S, RELAY_MARK))',
        'L.append("    ip saddr %s ct state != new meta mark 0x1 meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept" % (S, RELAY_MARK))',
        "socket transparent")
if P_CTST:  # the shape this shipped in: the socket rule matching a SYN as well as an established packet
    cut('L.append("    ip saddr %s ct state != new meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept" % (S, RELAY_MARK))',
        'L.append("    ip saddr %s meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept" % (S, RELAY_MARK))',
        "socket ct state")
if P_MSS:
    cut('out = run(["ip", "route", "get", "1.1.1.1", "from", gw] + (["mark", str(mark)] if mark else [])).stdout or ""',
        'out = run(["ip", "route", "get", "1.1.1.1", "from", gw]).stdout or ""', "mss mark")
if P_FWD:
    cut('_m = ("meta mark 0x%x " % e["mark"]) if e.get("mark") else ""',
        '_m = "meta mark 0x%x " % (e.get("mark") or 1)', "forward inertness")

path = os.path.join(ROOT, "__perturb_multileg.py")
if P_SOCK or P_MSS or P_FWD or P_CTST:
    open(path, "w").write(src)
l = importlib.machinery.SourceFileLoader("noded_ml", path if (P_SOCK or P_MSS or P_FWD or P_CTST) else NODED)
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_ml", l))
try:
    l.exec_module(m)
except SystemExit:
    pass
finally:
    if os.path.exists(path):
        os.unlink(path)

FWD = {"subnet": "10.18.0.0/24", "port": 5629, "iface": "wg8", "peer": "", "mark": 0, "iid": "wg8"}
LEG_A = {"subnet": "10.9.0.0/24", "port": 5701, "iface": "awg2", "peer": "peerA", "mark": 7001, "iid": "awg2.peerA"}
LEG_B = {"subnet": "10.9.0.0/24", "port": 5702, "iface": "awg2", "peer": "peerB", "mark": 7000, "iid": "awg2.peerB"}
nft = m._relay_nft([FWD, LEG_A, LEG_B])
tproxy = [l for l in nft.splitlines() if "tproxy" in l]
sock = [l for l in nft.splitlines() if "socket transparent" in l]

print("[1] a smart leg's divert names the mark the routing engine set")
check("leg A matches its own mark", any("mark 0x%x" % 7001 in l and ":5701" in l for l in tproxy), tproxy)
check("leg B matches its own mark", any("mark 0x%x" % 7000 in l and ":5702" in l for l in tproxy), tproxy)
check("…two legs on ONE interface get two rules", len([l for l in tproxy if "10.9.0.0/24" in l]) == 2, tproxy)
check("…each tagged with its instance", all(('"%s"' % m._relay_rule_tag(e["iid"])) in nft for e in (LEG_A, LEG_B)))
check("…and the tags differ", m._relay_rule_tag(LEG_A["iid"]) != m._relay_rule_tag(LEG_B["iid"]))

print("\n[2] ⚠️ the `socket transparent` rule is per SUBNET and carries NO mark")
# It keeps an ALREADY relayed connection reaching the socket we hold. A smart mark is recomputed per packet
# from set membership and Hybrid SNI adds learned IPs mid-flight, so a mark-scoped rule would stop matching
# and break a live connection mid-stream.
check("one rule per distinct subnet, not per leg", len(sock) == 2, "%d rules for 2 subnets" % len(sock))
check("⚠️ …and none of them matches a mark", not any("meta mark 0x" in l.split("socket")[0] for l in sock), sock)
check("…while the tproxy rules DO", any("meta mark 0x" in l for l in tproxy))
# ⚠️ …AND IT MUST NOT MATCH A CONNECTION ATTEMPT. The relay listens on 0.0.0.0 because a transparent
# socket must receive packets for ANY destination, so the kernel's listener lookup matches that wildcard
# bind for a SYN to any host on that port — the same fact the `fib daddr type local` scoping on the input
# drop was measured from. Under a whole-interface cascade that was harmless (every destination took the leg
# anyway); under a SMART cascade the relay would terminate a `direct` destination and re-originate it down
# the mesh leg with the leg's mark. The relay never picks an egress the rule did not.
check("⚠️ …and none of them matches a connection ATTEMPT",
      all("ct state != new" in l.split("socket")[0] for l in sock), sock)
check("…which is the only packet that could misroute a direct destination", "ct state" in nft)

print("\n[3] the relay port is closed, once per distinct port")
inp = nft[nft.index("chain inp"):]
for p in (5629, 5701, 5702):
    check("port %d is dropped in input" % p, ("dport %d counter drop" % p) in inp)
check("…and only once each", len(re.findall(r"dport \d+ counter drop", inp)) == 3, inp)

print("\n[4] ⚠️ …and a WHOLE-INTERFACE CASCADE is byte-identical to what ships today")
fwd_only = m._relay_nft([FWD])
fwd_tproxy = [l for l in fwd_only.splitlines() if "tproxy" in l]
check("⚠️ forward mode emits NO mark match", not any("meta mark 0x" in l.split("tproxy")[0] for l in fwd_tproxy),
      "%s — a mark match here would divert nothing, because nothing sets one" % fwd_tproxy)
check("…its instance id is still the bare interface", m._relay_iid("wg8", "") == "wg8", m._relay_iid("wg8", ""))
check("…so its unit, socket and port hash do not move",
      m._relay_unit("wg8") == "swg-relay@wg8.service" and m._relay_port("wg8") == m._relay_port("wg8"))
check("…and a leg with a peer DOES get a distinct id", m._relay_iid("awg2", "peerA") == "awg2.peerA")
check("…which is a legal systemd instance name", "/" not in m._relay_iid("awg2", "peerA"))

print("\n[5] the upstream MSS is derived for the leg the packet will ACTUALLY take")
seen = {}
m.run = lambda argv, **kw: seen.setdefault("argv", list(argv)) and None or type("R", (), {"stdout": "", "returncode": 1})()
m._relay_mss("10.9.0.1", 7001)
check("⚠️ `ip route get` is asked with the mark", "mark" in (seen.get("argv") or []) and "7001" in (seen.get("argv") or []),
      "%s — without it the kernel answers with the node's default route and the exit silently drops what it cannot fit"
      % (seen.get("argv"),))
seen.clear()
m._relay_mss("10.18.0.1", 0)
check("…and NOT asked with one in forward mode", "mark" not in (seen.get("argv") or []), seen.get("argv"))

bad = len(FAILS)
if P_SOCK or P_MSS or P_FWD or P_CTST:
    which = ("the socket-transparent rule mark-scoped" if P_SOCK else
             "the MSS lookup without its mark" if P_MSS else
             "the socket rule matching a SYN" if P_CTST else "forward mode emitting a mark match")
    print("\n--perturb (%s): %d check(s) RED" % (which, bad))
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
