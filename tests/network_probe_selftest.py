#!/usr/bin/env python3
"""Self-test for NETWORKS P4 — the reachability test (docs/NETWORKS-PLAN.md §8 P4).

  [1] the panel door: only an address inside a network the panel CARRIES for that peer on that node, from a node
      that is syncing; the panel's own reason when the address sits in a declared network it does not carry; one
      test at a time per node.
  [2] the round trip: the reply carries the request until the answer rides a snapshot, then carries nothing; a
      foreign id, a repeat and a malformed answer change nothing; a request never collected and one collected but
      never answered each expire with their own word; an answer is readable for a while, then gone.
  [3] the node's own check (D7): the address must lie inside a network the panel sent for THAT peer on THAT
      interface in the very reply that asks — never a tunnel address, never another peer's network, never the
      node's LAN or the internet, never a mesh link — and a network the node refused answers `no_route` with its
      reason. None of it forks.
  [4] every answer means one thing: the verdict for each outcome measured on the rig, with the path and the ACL
      checked BEFORE anything is sent.
  [5] bounds: a request taken once however often the reply repeats it; the answer dropped once the panel stops
      asking; a test the panel has given up on is never reported late.
  [6] measured, and pinned: the probe binds its SOURCE and never a device — SO_BINDTODEVICE got an answer with no
      route on the node, and in forward mode while every client went into the leg.
  [7] the operator's door itself, through `api()`: arm, read by id, list, refuse.

Hermetic. Run: python3 tests/network_probe_selftest.py            (0 = pass)
     --perturb   lets the node probe whatever address the panel names (its containment check waved through) and
                 expects RED on [3].
"""
import importlib.machinery, importlib.util, inspect, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel", PANEL)
N = load("swgnoded", NODED)

if PERTURB:
    _chk = N.net_probe_check
    def _waved(cfg, req, desired):
        ref, ctx = _chk(cfg, req, desired)
        if ref is not None and ref.get("verdict") == "not_carried":
            return None, {"id": req.get("id"), "iface": req.get("iface"), "pubkey": req.get("pubkey"),
                          "addr": req.get("addr"), "port": req.get("port"), "prefix": "", "src": "10.8.0.1"}
        return ref, ctx
    N.net_probe_check = _waved

K = lambda c: c * 43 + "="
TG = lambda ip, node="n1": {"node": node, "iface": "wg0", "ip": ip, "type": "wg"}
SNAP = {"node_ips": ["192.168.1.50"], "ether_gws": {"lan0": "192.168.1.1"},
        "interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24", "address": "10.8.0.1/24"}}},
        "net_deps": {"panel": "203.0.113.10", "resolvers": ["10.20.0.53"], "resolvers_known": True}}
def roster():
    return {"users": {"u1": {"name": "Alice"}, "u2": {"name": "Bob"}},
            "peers": {
                "gw1": {"id": "gw1", "user_id": "u1", "pubkey": K("A"), "created_at": 1, "title": "office",
                        "targets": [TG("10.8.0.10")], "routes": ["192.168.50.0/24", "10.8.0.128/25"]},
                "gw2": {"id": "gw2", "user_id": "u2", "pubkey": K("B"), "created_at": 2, "title": "home",
                        "targets": [TG("10.8.0.11")], "routes": ["192.168.60.0/24"]},
                "p3": {"id": "p3", "user_id": "u2", "pubkey": K("C"), "created_at": 3, "targets": [TG("10.8.0.12")]},
                "p4": {"id": "p4", "user_id": "u2", "pubkey": K("D"), "created_at": 4, "routes": ["192.168.70.0/24"],
                       "targets": [TG("10.8.1.13", node="n2")]}}}
R = roster()
NOW = 1_000_000.0
SNAPS, SEEN = {"n1": SNAP}, {"n1": NOW - 3}

def arm(pid="gw1", nid="n1", addr="192.168.50.5", port=None, r=None, seen=None, now=NOW, clear=True):
    if clear:
        P._NET_PROBES.clear()
    return P.net_probe_request(r or R, pid, nid, addr, port, SNAPS, SEEN if seen is None else seen, 30, now=now)
def why(st_body):
    return st_body[1].get("why")

# ── [1] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[1] the panel door")
st, body = arm()
check("an address inside a carried network, on a syncing node: armed, pending, sent through that gateway's interface",
      st == 200 and body["data"]["state"] == "pending" and body["data"]["iface"] == "wg0"
      and body["data"]["prefix"] == "192.168.50.0/24" and body["data"]["addr"] == "192.168.50.5", body)
for a in ("nope", "fe80::1", "", None):
    check("bad_address: %r" % (a,), why(arm(addr=a)) == "bad_address")
for p in (0, 70000, True, -1, 22.5):
    check("bad_port: %r" % (p,), why(arm(port=p)) == "bad_port")
check("a TCP port is accepted", arm(port=443)[1]["data"]["port"] == 443)
check("not_deployed: the peer is not on that node", why(arm(pid="p4")) == "not_deployed")
check("node_offline: the node has not synced within the stale window", why(arm(seen={"n1": NOW - 31})) == "node_offline")
check("node_offline: …or never reported", why(arm(seen={})) == "node_offline")
for a, what in (("192.168.1.1", "the node's own LAN router"), ("8.8.8.8", "the internet"),
                ("10.8.0.11", "another client's tunnel address"), ("10.8.0.10", "the gateway's own tunnel address"),
                ("192.168.60.5", "ANOTHER gateway's network")):
    st, b = arm(addr=a)
    check("not_carried: %s (%s) — nothing armed" % (a, what), st == 400 and b["why"] == "not_carried"
          and not P._NET_PROBES, b)
st, b = arm(addr="10.8.0.200")
check("not_carried, WITH the panel's reason when the address is in a network it declares but does not carry",
      b["why"] == "not_carried" and b["detail"] == {"prefix": "10.8.0.128/25", "because": {"why": "iface_subnet", "addr": "10.8.0.1"}}, b)
check("not_carried: a peer that fronts nothing", why(arm(pid="p3")) == "not_carried")
RB = roster(); RB["peers"]["gw1"]["disabled"] = True
check("not_carried: a blocked gateway carries nothing", why(arm(r=RB)) == "not_carried")
for a in ("192.168.50.0", "192.168.50.255"):
    check("network_address: %s" % a, why(arm(addr=a)) == "network_address")
RH = roster(); RH["peers"]["gw1"]["routes"] = ["172.30.9.9/32"]
check("a single-host network (/32) can be tested at its only address", arm(r=RH, addr="172.30.9.9")[0] == 200)
arm()
st, b = arm(addr="192.168.50.6", clear=False)
check("busy: one test at a time per node", st == 409 and b["why"] == "busy", b)
check("…another node is not held up by it", P.net_probe_request(R, "gw1", "n1", "192.168.50.6", None, SNAPS, SEEN, 30, now=NOW)[0] == 409
      and len(P._NET_PROBES) == 1)
check("…and once that test is over (expired), the next one arms", arm(addr="192.168.50.6", now=NOW + P.NET_PROBE_TTL + 1,
      seen={"n1": NOW + P.NET_PROBE_TTL}, clear=False)[0] == 200)

# ── [2] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the round trip")
st, b = arm(port=None)
rid = b["data"]["id"]
rep = P.net_probe_reply("n1", now=NOW + 1)
check("the reply carries exactly what the node needs — and no port for an echo",
      rep == {"id": rid, "iface": "wg0", "pubkey": K("A"), "addr": "192.168.50.5"}, rep)
check("…and nothing for a node with no test", P.net_probe_reply("n2", now=NOW + 1) is None)
check("…repeated on the next sync while no answer has come", P.net_probe_reply("n1", now=NOW + 6) == rep)
check("a foreign id is ignored", not P.net_probe_absorb("n1", {"net_probe": {"id": "f" * 16, "verdict": "answered"}}, now=NOW + 7))
check("a malformed value is ignored", not P.net_probe_absorb("n1", {"net_probe": "answered"}, now=NOW + 7)
      and not P.net_probe_absorb("n1", {"net_probe": ["x"]}, now=NOW + 7) and not P.net_probe_absorb("n1", None))
check("…the request still waits", P.net_probe_status("gw1", rid, now=NOW + 7)["state"] == "pending")
check("the answer is kept", P.net_probe_absorb("n1", {"net_probe": {"id": rid, "verdict": "answered", "ms": 1.2,
      "src": "10.8.0.1", "kind": "icmp"}}, now=NOW + 11))
v = P.net_probe_status("gw1", rid, now=NOW + 12)
check("…read back by id: done, collected, the verdict and its RTT",
      v["state"] == "done" and v["collected"] and v["result"] == {"verdict": "answered", "ms": 1.2, "src": "10.8.0.1", "kind": "icmp"}, v)
check("…and the reply stops carrying it", P.net_probe_reply("n1", now=NOW + 12) is None)
check("…a repeat of the same answer changes nothing", not P.net_probe_absorb("n1", {"net_probe": {"id": rid, "verdict": "no_answer"}}, now=NOW + 13)
      and P.net_probe_status("gw1", rid, now=NOW + 13)["result"]["verdict"] == "answered")
check("…another peer cannot read it", P.net_probe_status("gw2", rid, now=NOW + 13) is None)
check("…a list for the peer holds it", [x["id"] for x in P.net_probe_status("gw1", now=NOW + 13)] == [rid])
check("…readable for NET_PROBE_KEEP, then gone", P.net_probe_reply("n1", now=NOW + 11 + P.NET_PROBE_KEEP + 1) is None
      and P.net_probe_status("gw1", rid, now=NOW + 11 + P.NET_PROBE_KEEP + 2) is None)

st, b = arm()
rid = b["data"]["id"]
P.net_probe_absorb("n1", {"net_probe": {"id": rid, "verdict": "rm -rf /", "ms": True, "from": "x" * 100,
                                        "handshake_age": "7", "dev": ["leg0"], "extra": {"a": 1}}}, now=NOW + 5)
res = P.net_probe_status("gw1", rid, now=NOW + 5)["result"]
check("a hostile answer is cut to shape: unknown verdict → error, wrong types dropped, strings capped, extras gone",
      res == {"verdict": "error", "from": "x" * 45}, res)

st, b = arm()
rid = b["data"]["id"]
v = P.net_probe_status("gw1", rid, now=NOW + P.NET_PROBE_TTL + 1)
check("a request no sync ever collected expires as NOT collected",
      v["result"] == {"verdict": "expired", "collected": False} and not v["collected"], v)
st, b = arm()
rid = b["data"]["id"]
P.net_probe_reply("n1", now=NOW + 2)
v = P.net_probe_status("gw1", rid, now=NOW + P.NET_PROBE_TTL + 1)
check("a request collected and never answered expires as collected — the node took it (an older build ignores it)",
      v["result"] == {"verdict": "expired", "collected": True}, v)
check("…and an answer arriving after that changes nothing", not P.net_probe_absorb("n1", {"net_probe": {"id": rid, "verdict": "answered"}}, now=NOW + 60))
check("…nor is it sent again", P.net_probe_reply("n1", now=NOW + 60) is None)

# ── [3] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the node's own check (D7) — against the reply that asks")
TMP = tempfile.mkdtemp(prefix="netprobe-")
def conf(name, text):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write(text)
    return p
CFG = {"interfaces": {"wg0": {"conf": conf("wg0", "[Interface]\nAddress = 10.8.0.1/24\n")},
                      "wg6": {"conf": conf("wg6", "[Interface]\nAddress = fd42::1/64, 10.9.0.1/24\n")},
                      "swg_ab": {"conf": conf("swg_ab", "[Interface]\nAddress = 10.200.0.0/31\n")}}}
DES = {"wg0": [{"public_key": K("A"), "allowed_ips": "10.8.0.10/32,192.168.50.0/24,172.30.9.9/32"},
               {"public_key": K("B"), "allowed_ips": "10.8.0.11/32,192.168.60.0/24"},
               {"public_key": K("C"), "allowed_ips": "10.8.0.12/32"}],
       "wg6": [{"public_key": K("E"), "allowed_ips": "10.9.0.2/32,192.168.80.0/24"}],
       "swg_ab": [{"public_key": K("M"), "allowed_ips": "10.200.0.1/32,0.0.0.0/0"}]}
FORKS = []
N.run = lambda a, input_text=None, timeout=20: FORKS.append(a) or N.subprocess.CompletedProcess(a, 1, "", "")
N._iface_dump = lambda *a, **k: FORKS.append("wg show dump") or None
def rq(addr, pub="A", iface="wg0", port=None, rid="abcdef0123456789"):
    return dict({"id": rid, "iface": iface, "pubkey": K(pub), "addr": addr}, **({"port": port} if port is not None else {}))
ref, ctx = N.net_probe_check(CFG, rq("192.168.50.5"), DES)
check("accepted: inside the gateway's own network — sent FROM this node's address on that interface",
      ref is None and ctx == {"id": "abcdef0123456789", "iface": "wg0", "pubkey": K("A"), "addr": "192.168.50.5",
                              "port": None, "prefix": "192.168.50.0/24", "src": "10.8.0.1"}, (ref, ctx))
check("accepted: a single-host network, with a port", N.net_probe_check(CFG, rq("172.30.9.9", port=22), DES)[1]["port"] == 22)
for addr, pub, iface, what in (("10.8.0.10", "A", "wg0", "the gateway's own /32 (first member, never a network)"),
                               ("10.8.0.11", "A", "wg0", "another client's tunnel address"),
                               ("192.168.60.5", "A", "wg0", "ANOTHER gateway's network, named with this one's key"),
                               ("192.168.50.5", "B", "wg0", "this network, named with another gateway's key"),
                               ("192.168.50.5", "Z", "wg0", "a key the reply does not carry"),
                               ("192.168.1.1", "A", "wg0", "the node's own LAN router"),
                               ("1.1.1.1", "A", "wg0", "the internet"),
                               ("192.168.50.5", "A", "wg9", "an interface this node does not manage"),
                               ("8.8.8.8", "M", "swg_ab", "anything through a mesh link, even its /0"),
                               ("192.168.80.5", "E", "wg6", "an interface whose first Address is IPv6 — refused, not a crash")):
    r_, c_ = N.net_probe_check(CFG, rq(addr, pub, iface), DES)
    check("not_carried: %s — %s" % (addr, what), c_ is None and (r_ or {}).get("verdict") == "not_carried", (r_, c_))
check("not_carried: an empty reply carries nothing", N.net_probe_check(CFG, rq("192.168.50.5"), {})[0]["verdict"] == "not_carried")
check("network_address", N.net_probe_check(CFG, rq("192.168.50.255"), DES)[0]["verdict"] == "network_address")
for bad in (rq("fd00::5"), rq("x"), rq("192.168.50.5", port=0), rq("192.168.50.5", port="22"), rq("192.168.50.5", port=True)):
    check("bad_request: %r" % ({k: bad[k] for k in bad if k in ("addr", "port")},), N.net_probe_check(CFG, bad, DES)[0]["verdict"] == "bad_request")
N._NET["refused"]["192.168.50.0/24"] = {"why": "node_lan", "addr": "192.168.1.50", "iface": "wg0"}
ref, _ = N.net_probe_check(CFG, rq("192.168.50.5"), DES)
check("no_route: a network this node refused, with ITS reason and address",
      ref == {"id": "abcdef0123456789", "addr": "192.168.50.5", "prefix": "192.168.50.0/24", "verdict": "no_route",
              "why": "node_lan", "raddr": "192.168.1.50"}, ref)
N._NET["refused"].clear()
CFG_NA = {"interfaces": {"wg0": {"conf": conf("wg0na", "[Interface]\nAddress = 10.8.0.0/24\n")}}}
check("no_source is not reached for a readable Address; an unreadable conf reads as nothing carried",
      N.net_probe_check({"interfaces": {"wg0": {"conf": "/nonexistent"}}}, rq("192.168.50.5"), DES)[0]["verdict"] == "not_carried")
check("none of it forked", FORKS == [], FORKS)

# ── [4] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] every answer means one thing")
CTX = {"id": "abcdef0123456789", "iface": "wg0", "pubkey": K("A"), "addr": "192.168.50.5", "port": None,
       "prefix": "192.168.50.0/24", "src": "10.8.0.1"}
def world(route="192.168.50.5 from 10.8.0.1 dev wg0 uid 0", rc=0, allowed="10.8.0.10/32,192.168.50.0/24",
          hs_before=10, hs_after=None, dump_ok=True):
    calls = {"probe": 0, "dumps": 0}
    def _run(a, input_text=None, timeout=20):
        return N.subprocess.CompletedProcess(a, rc, route if rc == 0 else "", "" if rc == 0 else "RTNETLINK answers: Network is unreachable")
    def _dump(cfg, iface):
        calls["dumps"] += 1
        if not dump_ok:
            return None
        hs = hs_before if calls["dumps"] == 1 or hs_after is None else hs_after
        return ([], [{"public_key": K("A"), "allowed_ips": allowed, "last_handshake": int(time.time()) - hs if hs is not None else 0}])
    N.run, N._iface_dump = _run, _dump
    return calls
def probe(outcome, ctx=CTX, **w):
    calls = world(**w)
    def prim(*a):
        calls["probe"] += 1
        return outcome
    res = N.net_probe_run(CFG, ctx, 180, _icmp=prim, _tcp=prim)
    return res, calls

r_, c_ = probe(("answered", 1.2))
check("answered: an echo came back — with the RTT, the source and the kind",
      r_["verdict"] == "answered" and r_["ms"] == 1.2 and r_["src"] == "10.8.0.1" and r_["kind"] == "icmp" and "port" not in r_, r_)
r_, c_ = probe(("answered", 2.0), ctx=dict(CTX, port=8080))
check("answered: a TCP connect, with its port", r_["verdict"] == "answered" and r_["kind"] == "tcp" and r_["port"] == 8080, r_)
r_, c_ = probe(("refused_port", 1.0), ctx=dict(CTX, port=22))
check("refused_port: a reset IS an answer — measured, from a host that drops ICMP", r_["verdict"] == "refused_port" and r_["ms"] == 1.0, r_)
r_, c_ = probe(("answered", 1.0), route="192.168.50.5 from 10.8.0.1 dev leg0 table 150 uid 0")
check("route_elsewhere: the client's own lookup leaves by another device (forward mode, measured) — NOTHING sent",
      r_["verdict"] == "route_elsewhere" and r_["dev"] == "leg0" and c_["probe"] == 0, (r_, c_))
r_, c_ = probe(("answered", 1.0), rc=2)
check("route_elsewhere with no device: no route at all — nothing sent", r_["verdict"] == "route_elsewhere" and r_["dev"] == "" and c_["probe"] == 0, r_)
r_, c_ = probe(("answered", 1.0), rc=127)
check("error: the routing table could not be asked — nothing sent", r_["verdict"] == "error" and c_["probe"] == 0, r_)
r_, c_ = probe(("answered", 1.0), dump_ok=False)
check("error: the interface could not be read — nothing sent", r_["verdict"] == "error" and c_["probe"] == 0, r_)
r_, c_ = probe(("answered", 1.0), allowed="10.8.0.10/32")
check("no_acl: the gateway's live ACL does not carry the network — nothing sent", r_["verdict"] == "no_acl" and c_["probe"] == 0, r_)
r_, c_ = probe(("send_error", "ENOKEY"))
check("no_acl: ENOKEY on send (measured: wg's own refusal)", r_["verdict"] == "no_acl", r_)
r_, c_ = probe(("send_error", "EDESTADDRREQ"), hs_before=None)
check("gateway_offline: EDESTADDRREQ, never a handshake (measured: wg with no endpoint)",
      r_["verdict"] == "gateway_offline" and r_["handshake_age"] is None, r_)
r_, c_ = probe(("no_answer",), hs_before=600)
check("gateway_offline: silence from a gateway whose last handshake is past online_max", r_["verdict"] == "gateway_offline"
      and r_["handshake_age"] >= 600, r_)
r_, c_ = probe(("no_answer",), hs_before=600, hs_after=2)
check("no_answer: an idle session the probe itself brought back is CONNECTED — the handshake is read after sending",
      r_["verdict"] == "no_answer" and r_["handshake_age"] <= 3, r_)
r_, c_ = probe(("no_answer",))
check("no_answer: sent through a connected gateway, nothing came back — the far side's", r_["verdict"] == "no_answer", r_)
r_, c_ = probe(("unreachable", 3000.0, "192.168.50.1"), hs_before=900)
check("unreachable: an ICMP error that came back THROUGH the tunnel — the gateway is there, whatever the handshake says",
      r_["verdict"] == "unreachable" and r_["from"] == "192.168.50.1", r_)
r_, c_ = probe(("unreachable", 3090.0, ""), ctx=dict(CTX, port=80))
check("unreachable: a TCP host-unreachable through a connected gateway (measured, ~3 s: ARP gave up)", r_["verdict"] == "unreachable" and "from" not in r_, r_)
r_, c_ = probe(("unreachable", 0.1, ""), ctx=dict(CTX, port=80), hs_before=None)
check("gateway_offline: the same errno, instantly, with no session (measured) — never read as the far side", r_["verdict"] == "gateway_offline", r_)
r_, c_ = probe(("send_error", "EPERM"))
check("error: any other send failure through a connected gateway, named", r_["verdict"] == "error" and r_["detail"] == "EPERM", r_)

# ── [5] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] bounds")
RUNS, THREADS = [], []
class _T:
    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args
    def start(self):
        THREADS.append(self)
N.threading.Thread = _T
N.net_probe_run = lambda cfg, ctx, om=180, **k: RUNS.append(ctx["id"]) or dict(verdict="answered", ms=1.0, id=ctx["id"])
N._PROBE.update(id="", result=None, at=0.0)
def drain():
    while THREADS:
        t = THREADS.pop(0)
        t.target(*t.args)
REQ = rq("192.168.50.5", rid="aaaaaaaa11111111")
for _ in range(3):
    N.net_probe_take(CFG, REQ, DES)
drain()
for _ in range(3):
    N.net_probe_take(CFG, REQ, DES)
drain()
check("taken ONCE, however many replies repeat it", RUNS == ["aaaaaaaa11111111"], RUNS)
st_ = N.net_probe_status()
check("…its answer waits for the snapshot", st_ and st_["id"] == "aaaaaaaa11111111" and st_["verdict"] == "answered", st_)
N.net_probe_take(CFG, None, DES)
check("the panel stops asking → the answer is dropped", N.net_probe_status() is None)
N.net_probe_take(CFG, REQ, DES)
drain()
check("…and the same id arriving again afterwards is a NEW test only because the panel re-armed it", len(RUNS) == 2)
N.net_probe_take(CFG, rq("192.168.50.5", rid="bbbbbbbb22222222"), DES)
late = THREADS[:]
N.net_probe_take(CFG, rq("192.168.50.6", rid="cccccccc33333333"), DES)
del THREADS[:1]
for t in late:
    t.target(*t.args)
check("a test the panel moved on from is never reported late", (N.net_probe_status() or {}).get("id") != "bbbbbbbb22222222")
drain()
check("…the current one is", (N.net_probe_status() or {}).get("id") == "cccccccc33333333")
N._PROBE["at"] = time.time() - N.NET_PROBE_KEEP_S - 1
N.net_probe_take(CFG, rq("192.168.50.6", rid="cccccccc33333333"), DES)
check("an answer the panel keeps asking about but never collects stops being repeated", N.net_probe_status() is None)
n0 = len(RUNS)
N.net_probe_take(CFG, rq("192.168.1.1", rid="dddddddd44444444"), DES)
check("a request the node refuses answers straight away, with no thread", N.net_probe_status()["verdict"] == "not_carried"
      and not THREADS and len(RUNS) == n0)
for bad in ("../../etc", "short", "x" * 40, 12345678):
    N._PROBE.update(id="", result=None, at=0.0)
    N.net_probe_take(CFG, dict(REQ, id=bad), DES)
    check("a malformed id is not taken: %r" % (bad,), N._PROBE["id"] == "" and not THREADS)

# ── [6] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] measured, and pinned")
N2 = load("swgnoded2", NODED)
srcs = {f: inspect.getsource(getattr(N2, f)) for f in ("net_probe_check", "net_probe_run", "_net_icmp", "_net_tcp",
                                                        "net_probe_take", "_net_route_dev")}
check("no probe function binds a device (SO_BINDTODEVICE answered with no route, and past forward mode's table)",
      not any("SO_BINDTODEVICE" in s for s in srcs.values()))
check("both probes bind the interface's own address as their source", all("s.bind((src, 0))" in srcs[f] for f in ("_net_icmp", "_net_tcp")))
check("the path is the client's lookup: `ip route get <addr> from <src>`",
      '["ip", "-4", "route", "get", addr, "from", src]' in srcs["_net_route_dev"])
check("the wait catches the gateway's ARP give-up (~3 s measured)", N2.NET_PROBE_WAIT_S >= 3.5)

# ── [7] ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[7] the operator's door, through api()")
RP = os.path.join(TMP, "users.json")
P.roster_save(RP, roster())
DEPS = {"fleet": {}, "roster_path": RP, "nodes_path": os.path.join(TMP, "nodes.json"),
        "node_snaps": {"n1": SNAP}, "node_seen": {"n1": int(time.time())}, "panel_settings": {}}
P._NET_PROBES.clear()
def call(body):
    return P.api("POST", "/api/peers/networks/probe", {}, body, DEPS)
st, b = call({"peer_id": "gw1", "node": "n1", "addr": "192.168.50.5", "port": "22"})
check("arms, with a port given as the form gives it (a string)", st == 200 and b["data"]["port"] == 22 and b["data"]["state"] == "pending", (st, b))
rid = b["data"]["id"]
st, b2 = call({"peer_id": "gw1", "id": rid})
check("reads it back by id", st == 200 and b2["data"]["id"] == rid, (st, b2))
st, b3 = call({"peer_id": "gw1"})
check("lists this peer's tests", st == 200 and [x["id"] for x in b3["data"]] == [rid], (st, b3))
check("busy, while it runs", call({"peer_id": "gw1", "node": "n1", "addr": "192.168.50.6"})[1].get("why") == "busy")
check("an unknown id is 404 `unknown`", call({"peer_id": "gw1", "id": "0" * 16})[1].get("why") == "unknown")
check("an unknown peer is 404", call({"peer_id": "nobody", "node": "n1", "addr": "192.168.50.5"})[0] == 404)
P._NET_PROBES.clear()
check("a port that is not a number is refused, not coerced", call({"peer_id": "gw1", "node": "n1", "addr": "192.168.50.5", "port": "ssh"})[1].get("why") == "bad_port")
check("refused at the door: the node's LAN router", call({"peer_id": "gw1", "node": "n1", "addr": "192.168.1.1"})[1].get("why") == "not_carried")
check("the arming was written to the activity log", any("Tested a network" in ln for ln in open(P.events_path(RP))))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
