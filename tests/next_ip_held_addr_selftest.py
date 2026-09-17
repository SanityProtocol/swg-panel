#!/usr/bin/env python3
"""Self-test: the address picker never hands a peer an address the node holds itself.

⚠️ MEASURED on swgt, 2026-09-17. An imported exit's profile carried its provider's client address, 10.9.0.2 — inside
awg2's 10.9.0.0/24. The picker looked only at the interface's own address and at peers, so it offered 10.9.0.2 to a
new router peer on awg2. The node then owned the router's address: every packet from the router was dropped as a
spoofed source and every reply was delivered to the node itself, while the handshake kept the peer reading online.
Switching the exit off freed the address and the router came up at once.

What the node holds comes from its snapshot (its own IPs, every exit's tunnel address, every tunnel or card it could
use as an exit) and from the panel's own record of each imported exit profile, which a DISABLED exit keeps — so
switching that exit back on cannot take a peer's address away again.

Run: python3 tests/next_ip_held_addr_selftest.py    (0 = pass)
     --perturb  the picker ignores what the node holds again, and expects RED.
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
CALL = "        used |= node_held_addrs(snap, (node_store or {}).get(node))\n"
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert CALL in src, "the picker's held-address line is not where this expects it — this run would FALSE-PASS"
for caller in ("panel_next_ip(snaps, roster_load(roster_path), sel, iface, nodes)",
               "panel_next_ip(snaps, roster, same_iface_nodes or [node], iface, nodes)"):
    assert caller in src, "a caller no longer passes the node store: " + caller
if PERTURB:
    src = src.replace(CALL, "", 1)

m = types.ModuleType("p")
m.__dict__.update({"__name__": "p", "__file__": os.path.join(ROOT, "swg-panel-server")})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)


def snap(**extra):
    s = {"interfaces": {"awg2": {"meta": {"subnet": "10.9.0.0/24", "address": "10.9.0.1/24"},
                                 "peers": [{"allowed_ips": "10.9.0.3/32"}]}}}
    s.update(extra)
    return s

ROSTER = {"peers": {"p4": {"targets": [{"node": "n1", "iface": "awg2", "ip": "10.9.0.4"}]}}}
def pick(snaps, store=None, roster=ROSTER, nodes=("n1",)):
    r = m.panel_next_ip(snaps, roster, list(nodes), "awg2", store)
    return r["data"]["next_ip"] if r.get("ok") else r

print("[1] control — a node that reports nothing it holds gets the lowest free address, as before")
check("peers, the roster and the interface's own address are still skipped", pick({"n1": snap()}) == "10.9.0.2/32",
      pick({"n1": snap()}))
check("…and a caller that passes no node store still works", m.panel_next_ip({"n1": snap()}, ROSTER, ["n1"], "awg2")
      .get("data", {}).get("next_ip") == "10.9.0.2/32")

print("\n[2] ⚠️ the swgt case — an exit's tunnel address inside the interface's subnet")
S = {"n1": snap(exits=[{"id": "8167d251", "device": "wgx-8167d251", "address": "10.9.0.2"}])}
check("the exit's 10.9.0.2 is never handed to a peer", pick(S) == "10.9.0.5/32", pick(S))

print("\n[3] every other address the node reports holding")
check("a tunnel or card it could use as an exit (with a prefix)",
      pick({"n1": snap(exit_candidates=[{"name": "wg-lab0", "address": "10.9.0.2/32"}])}) == "10.9.0.5/32")
check("its own IPs", pick({"n1": snap(node_ips=["201.24.126.212", "10.9.0.2"])}) == "10.9.0.5/32")

print("\n[4] ⚠️ a DISABLED imported exit still reserves its address — switching it back on must not take a peer's")
STORE = {"n1": {"exits": [{"id": "8167d251", "enabled": False, "profile": {"address": "10.9.0.2", "mtu": 1420}},
                          {"id": "736a24bf", "profile": None}]}}
check("the stored profile's address is skipped with no live exit", pick({"n1": snap()}, STORE) == "10.9.0.5/32",
      pick({"n1": snap()}, STORE))

print("\n[5] across every selected node, and nothing outside the subnet matters")
S2 = {"n1": snap(), "n2": snap(exits=[{"address": "10.9.0.2"}])}
check("an address held on ONE of the selected nodes is skipped for all of them", pick(S2, nodes=("n1", "n2")) == "10.9.0.5/32",
      pick(S2, nodes=("n1", "n2")))
check("held addresses in other ranges change nothing",
      pick({"n1": snap(exits=[{"address": "172.16.0.2"}], node_ips=["201.24.126.212"])}) == "10.9.0.2/32")

print("\n[6] what a node reports is not trusted to be well formed")
junk = snap(node_ips=[None, 7, "not an ip", "fd00::2", "10.9.0.2/32, fd00::3"],
            exits=[None, "x", {"address": None}, {"address": ["10.9.0.9"]}],
            exit_candidates="nope")
check("junk is skipped, and a comma-separated value still counts", pick({"n1": junk}) == "10.9.0.5/32", pick({"n1": junk}))
check("a junk node record is skipped", pick({"n1": snap()}, {"n1": {"exits": [None, {"profile": "x"}, 3]}}) == "10.9.0.2/32")

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the picker offers the node's own address again" % len(FAILS))
          if ok else "PERTURB FAILED — the held addresses were ignored and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
