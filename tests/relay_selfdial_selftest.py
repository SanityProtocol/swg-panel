#!/usr/bin/env python3
"""Self-test: the relay never dials itself, and a divert that serves nobody is not called healthy.

Two defects, one root cause — the relay decided what traffic was by looking at an ADDRESS, and the node
decided the relay was well by looking at LIVENESS. Both were measured on real nodes, not reasoned about.

── 1. ONE STRAY CONNECT WAS AN UNBOUNDED LOOP ────────────────────────────────────────────────────────────
`getsockname()` on an accepted socket is the original destination ONLY IF tproxy put it there. A connection
that reaches the listener any other way gets the listener's own address back, and the relay then dials it —
which arrives at the listener, which dials it again. Measured on a test node: one `/dev/tcp/127.0.0.1/<port>`
took the relay from 6 open fds to 47,780 in six seconds and wedged its status socket, so the watchdog then
read the relay as dead while the divert stayed armed over it.

⚠️ AND THE LISTENER IS ON 0.0.0.0, because a transparent socket must be able to receive packets addressed
to any destination. So that was reachable from anywhere that could reach the node — a public panel's nodes,
one packet. Two independent guards, because either alone is a single point of failure:
  · the port is DROPPED in input. Free, and that is measured not argued: tproxy leaves the destination the
    CLIENT asked for, so a real diverted connection never carries the relay's port — counted live on the rig
    at 16 packets on the client's own dport and 0 on the relay's.
  · the relay refuses a destination that is its own listening address. Deliberately not a bare port test:
    a client dialling a REMOTE host that happens to use our port is legitimate and still works.

── 2. "ANSWERING" IS NOT "SERVING" ───────────────────────────────────────────────────────────────────────
`_relay_probe` asked three questions — does the status socket reply, does `loops` move, is CPU sane — and a
relay accepting NOTHING passes all three: `loops` ticks ~1.2/s from the select timeout alone. Measured on a
live node: `accepted=0` for 3h45m with the divert armed the whole time, every client TCP connection
swallowed, and the panel green. swg-relay's own docstring states the requirement it did not meet —
"Anything that arms a divert must prove `accepted` rises before it walks away."

Run: python3 tests/relay_selfdial_selftest.py (0 = pass)
     --perturb        removes the relay's self-dial guard, RED.
     --perturb-nft    removes the input port drop, RED.
     --perturb-probe  restores the liveness-only health check, RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RELAY = os.environ.get("SWG_RELAY") or os.path.join(ROOT, "swg-relay")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
P_GUARD = "--perturb" in sys.argv
P_NFT = "--perturb-nft" in sys.argv
P_PROBE = "--perturb-probe" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def cut(src, anchor, repl, why):
    # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind and reports the
    # gate as having caught the bug it never removed. [[lesson-perturb-the-verifier]]
    assert anchor in src, "perturbation anchor missing (%s) — this run would FALSE-PASS" % why
    return src.replace(anchor, repl, 1)

relay = open(RELAY, encoding="utf-8").read()
noded = open(NODED, encoding="utf-8").read()

if P_GUARD:
    relay = cut(relay, 'if dst[1] == a.port and is_local_addr(dst[0]):', 'if False:', "relay guard")
if P_NFT:
    noded = cut(noded, 'L.append("    meta l4proto tcp th dport %d counter drop" % port)',
                'pass', "nft port drop")
if P_PROBE:
    noded = cut(noded, "and dv - dv_prev >= RELAY_DIVERT_MIN and ac <= ac_prev):",
                "and False):", "serving check")

print("[1] the relay refuses to dial its own listener")
# the guard sits at the ACCEPT site, on the branch that trusts getsockname() — not on the --dst branch,
# which is a fixed upstream and was never the loop.
acc = relay[relay.index("dst = cli.getsockname()"):relay.index("R.start(cli, dst)")]
check("the guard is on the getsockname() path", "is_local_addr(" in acc, acc[-200:])
check("…and refuses only OUR port on a LOCAL address",
      re.search(r"if dst\[1\] == a\.port and is_local_addr\(dst\[0\]\):", acc) is not None,
      "a bare port test would break a client dialling a remote host on that port")
check("…and the refusal is counted, not silent", '"refused_self"' in relay and 'ST["refused_self"] += 1' in relay)
check("…and the counter is declared, so the status line always carries it",
      re.search(r'ST = \{[^}]*"refused_self": 0', relay, re.S) is not None)
check("…and the connection is closed rather than leaked",
      re.search(r'ST\["refused_self"\] \+= 1\s*\n\s*cli\.close\(\); continue', relay) is not None)
# is_local_addr must consult the KERNEL. A hardcoded loopback list would miss 10.18.0.1 — the address the
# relay is actually bound through — and the loop would come straight back on the divert's own subnet.
check("the local-address test reads real interface addresses", "SIOCGIFCONF" in relay and "def local_addrs(" in relay)
check("…without a subprocess on the accept path", "subprocess" not in relay)
check("…and re-reads them, because addresses change under a running relay",
      re.search(r'def is_local_addr\(ip, ttl=', relay) is not None and '_LOCAL["at"]' in relay)
check("…counting loopback as local even when no interface reports it",
      '"127.0.0.1"' in relay and '"0.0.0.0"' in relay)

print("\n[2] the port is closed to everything but the divert")
nft = noded[noded.index("def _relay_nft("):noded.index("def _relay_arm(")]
check("an input chain exists", 'chain inp {' in nft)
check("…hooked in input", "hook input" in nft)
check("…dropping tcp to each relay port", "dport %d counter drop" in nft)
check("…counted, so 'it never fires' is a reading and not a hope", "counter drop" in nft)
# ⚠️ THE GUARD OUTLIVES THE DIVERT. `_relay_disarm` deletes the whole table, so a guard tied to the
# armed set vanished exactly when the relay was in a bad state — and a blackhole hold now keeps a leg
# disarmed for up to fifteen minutes while the process is still listening on 0.0.0.0. Observed live: a
# stray connect during a disarm window reached the relay while the drop rule counter sat at 0.
guard_only = noded[noded.index("def _relay_nft("):noded.index("def _relay_note(")]
check("the builder takes ports independently of entries", "guard_ports" in guard_only)
check("⚠️ …so a disarmed relay still has its port shut",
      "if want:" in noded and re.search(r'_relay_nft\(\[\], sorted\(\{want\[i\]\["port"\]', noded) is not None,
      "a disarm that opens the port re-opens the 47,000-fd loop to anything that can reach the node")
check("…and a guard-only table does NOT read as armed",
      '"tproxy" in (r.stdout or "")' in noded,
      "else the next pass would never re-assert the divert")
check("⚠️ the divert rules carry counters — the blackhole check has no other input",
      nft.count("counter meta mark set") >= 2)

print("\n[3] the watchdog proves SERVING, not merely answering")
probe = noded[noded.index("def _relay_probe("):noded.index("def _relay_nft(")]
check("it reads the diverted-packet counter", "_relay_diverted()" in probe)
check("…and the relay's accept counter", 's.get("accepted")' in probe)
check("⚠️ …and fails when one moves and the other does not",
      re.search(r"dv - dv_prev >= RELAY_DIVERT_MIN and ac <= ac_prev", probe) is not None,
      "a divert carrying traffic into a relay that accepts none is a blackhole")
check("…over two passes, not one", 'st["mute"] >= 2' in probe)
check("…and resets the run when it recovers", 'st["mute"] = 0' in probe)
check("it also fails on a relay being dialled on its own port", "refused_self" in probe)
check("…and the two thresholds are named, not inline numbers",
      "RELAY_DIVERT_MIN" in noded and "RELAY_SELFDIAL_MAX" in noded)
# the old criteria must SURVIVE — this adds evidence, it does not replace it
for keep, why in (("relay not answering", "a dead relay"), ("loops stuck at", "a wedged loop"),
                  ("over CPU budget", "a quota that is not enforcing")):
    check("…while still catching %s" % why, keep in probe)

print("\n[3b] ⚠️ …and every arm/disarm is on the record")
# This did not exist, and it is why the live failure could not be settled after the fact: the node armed a
# blackhole-capable divert and wrote nothing anywhere. Detection without a record just moves the same
# unanswerable question one layer along.
arm = noded[noded.index("def _relay_note("):noded.index("def _relay_arm(")]
check("a transition is written to the journal", "print(" in arm and "relay divert" in arm)
check("…and says WHY", re.search(r'\(" — " \+ why\) if why else ""', arm) is not None)
check("…once, not every pass", '_RELAY_ARM.get("noted")' in arm and "if prev == now:" in arm)
body = noded[noded.index("def _relay_note("):]
check("⚠️ the ARM path records it", re.search(r'_relay_note\("ARMED"', body) is not None)
# ⚠️ the INSTANCE, not the interface — one interface can carry two relayed legs under a smart cascade, and
# naming the interface would print the same name twice with different ports.
check("…naming the instances and ports a client now depends on",
      re.search(r'_relay_note\("ARMED",[^)]*e\["iid"\][^)]*e\["port"\]', body, re.S) is not None)
check("…and every DISARM path records it too",
      len(re.findall(r'_relay_note\("DISARMED"', body)) >= 4, "a disarm that is not logged is the same blind spot")
# ⚠️ INCLUDING THE SETTINGS-CHANGE ONE, in BOTH run-models. `_relay_note` dedupes on (state, why), so an
# unrecorded disarm makes the ARMED line after it identical to the one before and it is swallowed — the
# journal then reads as continuously armed across a window where the divert was pulled.
for _fn, _label in (("_relay_supervise_docker", "docker"), ("_relay_supervise", "systemd")):
    _seg = noded[noded.index("def %s(" % _fn):]
    _seg = _seg[:_seg.index("\ndef ", 10)]
    check("…the %s settings-change disarm is recorded" % _label,
          '_relay_note("DISARMED"' in _seg, "a restart pulls the divert and says nothing")
check("…including the one where arming itself failed",
      re.search(r'_RELAY_ARM\["sig"\] = None\s*\n\s*_relay_note\("DISARMED", "arming failed"\)', body) is not None)

print("\n[4] and the reader it depends on is real")
rd = noded[noded.index("def _relay_diverted("):noded.index("def _relay_probe(")]
check("_relay_diverted parses nft's own json", '"nft", "-j", "list"' in rd)
check("…sums only the tproxy rules", '"tproxy" in e' in rd)
check("…returns None (not 0) when it cannot read", re.search(r"return None", rd) is not None,
      "0 would read as 'nothing diverted' and silently pass the blackhole check")
check("…and None is handled at the call site", "dv is not None" in probe)

bad = len(FAILS)
if P_GUARD or P_NFT or P_PROBE:
    which = "the relay's self-dial guard" if P_GUARD else ("the nft port drop" if P_NFT else "the serving check")
    print("\n--perturb (%s removed): %d check(s) RED" % (which, bad))
    sys.exit(0 if bad else 1)
print("\n%d failing" % bad)
sys.exit(1 if bad else 0)
