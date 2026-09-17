#!/usr/bin/env python3
"""Self-test: the relay divert takes a connection ATTEMPT that LEAVES BY A MESH LEG — nothing else.

Measured on swgt 2026-09-16 (docs: 1.8.7 qualification §N14), with the divert naming only a source:
  · a device on a relay-mode interface could not ACCEPT a TCP connection from anywhere else on the node — its SYN-ACK
    missed every socket and `tproxy` handed it to the relay listener (ICMP passed, TCP did not);
  · the watchdog's `tcp flags syn / syn,rst` counted those SYN-ACKs as attempts the relay never accepted, and pulled
    the interface's divert as "a blackhole" — relay mode switched itself off because a neighbour tried to connect;
  · a client dialling the node's OWN address was terminated and re-dialled from the gateway address, inside the
    diverted subnet, so the dial came back through the divert: one `nc -z` → 7,790 connections, 7,782 deep;
  · every connection to a neighbour, or to a network behind one, was relayed although no leg carries it.

This judges the rules `_relay_nft` really emits BY PACKET: a small evaluator for the grammar those two lines use, run
over the packets that matter. `fib daddr [. mark] oifname` is modelled as the measured answer — the interface the
packet's own policy route leaves by (`from <subnet> lookup T` honoured), "" for a local destination.

Run: python3 tests/relay_divert_scope_selftest.py (0 = pass)
     --perturb-flags    the attempt test goes back to `syn / syn,rst`          → RED
     --perturb-fib      the leg test is dropped from both lines                 → RED
     --perturb-counter  the watchdog counter loses the leg test (counts ≠ takes)→ RED
     --perturb-mark     a whole-interface leg looks the route up WITH the mark  → RED
     --perturb-links    the links are the `swg_` prefix again                   → RED
     --perturb-shadow   the parameter is reassigned inside reconcile_relay      → RED
"""
import importlib.machinery, importlib.util, ipaddress, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
MODE = next((a[len("--perturb-"):] for a in sys.argv[1:] if a.startswith("--perturb-")), "")

src = open(NODED, encoding="utf-8").read()
ATT = '''        _att = 'tcp flags syn / fin,syn,rst,ack fib daddr %soifname { %s } ' % (
            ". mark " if e.get("mark") else "", ", ".join('"%s"' % d for d in links))'''
CNT = '''        L.append('    ip saddr %s %smeta l4proto tcp %scounter comment "%s"'
                 % (S, _m, _att, _relay_syn_tag(e["iid"])))'''
PLANTS = {
    "flags": (ATT, ATT.replace("syn / fin,syn,rst,ack", "syn / syn,rst")),
    "fib": (ATT, '''        _att = 'tcp flags syn / fin,syn,rst,ack ' '''),
    "links": ('''        _RELAY_LINKS["links"] = tuple(sorted(n for n in ifs if _iface_is_mesh(node_cfg, n, _iface_subnet(node_cfg, n))))''',
              '''        _RELAY_LINKS["links"] = tuple(sorted(n for n in ifs if n.startswith("swg_")))'''),
    "counter": (CNT, '''        L.append('    ip saddr %s %smeta l4proto tcp tcp flags syn / fin,syn,rst,ack counter comment "%s"'
                 % (S, _m, _relay_syn_tag(e["iid"])))'''),
    "mark": (ATT, '''        _att = 'tcp flags syn / fin,syn,rst,ack fib daddr . mark oifname { %s } ' % ", ".join('"%s"' % d for d in links)'''),
}
if MODE == "shadow":
    # the shape that shipped to swgt and loaded nothing: the parameter named like the plan's own `legs`, which the body
    # reassigns — every `links` inside reconcile_relay spelled `legs` again
    a0, a1 = src.index("def reconcile_relay("), src.index("def _relay_quota_effective(")
    assert len(re.findall(r"\blinks\b", src[a0:a1])) == 4, "perturbation anchor missing (shadow) — this run would FALSE-PASS"
    src = src[:a0] + re.sub(r"\blinks\b", "legs", src[a0:a1]) + src[a1:]
elif MODE:
    frm, to = PLANTS[MODE]
    assert src.count(frm) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % MODE
    src = src.replace(frm, to, 1)
path = os.path.join(tempfile.mkdtemp(), "swg-noded")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", loader))
try:
    loader.exec_module(N)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

FLAG = {"fin": 1, "syn": 2, "rst": 4, "psh": 8, "ack": 16}


def matches(rule, pkt):
    """Does `rule` match `pkt`? The grammar _relay_nft's divert lines use, and nothing more: an expression this does not
    know is a failure to model, never a silent match."""
    toks = rule.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "ip" and toks[i + 1] == "saddr":
            if ipaddress.ip_address(pkt["src"]) not in ipaddress.ip_network(toks[i + 2]):
                return False
            i += 3
        elif t == "meta" and toks[i + 1] == "mark" and toks[i + 2] != "set":
            if pkt["mark"] != int(toks[i + 2], 0):
                return False
            i += 3
        elif t == "meta" and toks[i + 1] == "l4proto":
            i += 3                                           # every packet here is tcp
        elif t == "tcp" and toks[i + 1] == "flags":
            want, mask = toks[i + 2], toks[i + 4]
            wv = sum(FLAG[f] for f in want.split(","))
            mv = sum(FLAG[f] for f in mask.split(","))
            if sum(FLAG[f] for f in pkt["flags"]) & mv != wv:
                return False
            i += 5
        elif t == "fib" and toks[i + 1] == "daddr":
            with_mark = toks[i + 2] == "."
            j = i + (4 if with_mark else 2)
            assert toks[j] == "oifname" and toks[j + 1] == "{", "unmodelled fib result: " + " ".join(toks[j:j + 2])
            k = toks.index("}", j)
            names = {t.strip('",') for t in toks[j + 2:k]}
            oif = pkt["route_mark"] if with_mark else pkt["route"]
            if oif not in names:
                return False
            i = k + 1
        elif t in ("counter", "accept") or t == "comment":
            break
        elif t == "tproxy":
            break
        else:
            raise AssertionError("unmodelled expression %r in %r" % (t, rule))
    return True


LEGS = ("swg_1d430ded", "swg_93c2fdf8")


def rules_for(entries):
    txt = N._relay_nft(entries, (), LEGS)
    take = {m.group(1): l for l in txt.splitlines() for m in [re.search(r'comment "swg-relay:([^"]+)"', l)] if m}
    count = {m.group(1): l for l in txt.splitlines() for m in [re.search(r'comment "swg-relay-syn:([^"]+)"', l)] if m}
    return take, count


def pkt(src, flags, route, route_mark=None, mark=0):
    return {"src": src, "flags": flags, "route": route, "route_mark": route_mark if route_mark is not None else route, "mark": mark}


print("[1] a whole-interface leg (mark 0) — what it takes")
W = {"subnet": "10.141.0.0/24", "port": 5703, "mark": 0, "iid": "wgn1", "iface": "wgn1", "peer": "hel"}
take, count = rules_for([W])
T, C = take["wgn1"], count["wgn1"]
CASES = [
    ("a client's SYN to the internet, routed into the leg", pkt("10.141.0.10", ["syn"], "swg_93c2fdf8"), True),
    ("a SYN routed into a device exit (not a mesh link)", pkt("10.141.0.10", ["syn"], "wgx-736a24bf"), False),
    ("⚠️ a device's SYN-ACK answering a neighbour's connection", pkt("10.141.0.20", ["syn", "ack"], "wgn2"), False),
    ("⚠️ …even when that neighbour is across the leg", pkt("10.141.0.20", ["syn", "ack"], "swg_93c2fdf8"), False),
    ("a stray ACK / FIN of a dead connection", pkt("10.141.0.10", ["ack", "fin"], "swg_93c2fdf8"), False),
    ("⚠️ a SYN to a neighbour on this node", pkt("10.141.0.10", ["syn"], "wgn1"), False),
    ("⚠️ a SYN to a network behind a device here", pkt("10.141.0.10", ["syn"], "wgn1"), False),
    ("⚠️ a SYN to this node's own address (type local, no oif)", pkt("10.141.0.10", ["syn"], ""), False),
    ("⚠️ a SYN carrying ANOTHER product's mark still judged by its own route",
     pkt("10.141.0.10", ["syn"], "swg_93c2fdf8", route_mark="eth0", mark=0x1), True),
    ("a SYN from outside the subnet", pkt("10.142.0.50", ["syn"], "swg_93c2fdf8"), False),
]
for name, p, want in CASES:
    check("%s → %s" % (name, "taken" if want else "left alone"), matches(T, p) == want, T)
    check("…and the watchdog counts it exactly when it is taken", matches(C, p) == matches(T, p), C)

print("\n[2] a smart leg (marked) — its mark scopes it, and the route is looked up WITH that mark")
M = {"subnet": "10.9.0.0/24", "port": 5632, "mark": 0x1b58, "iid": "awg2.hel", "iface": "awg2", "peer": "hel"}
take, count = rules_for([M])
T, C = take["awg2.hel"], count["awg2.hel"]
for name, p, want in [
    ("a marked SYN whose marked route is the leg", pkt("10.9.0.5", ["syn"], "eth0", route_mark="swg_1d430ded", mark=0x1b58), True),
    ("an unmarked SYN (a direct destination)", pkt("10.9.0.5", ["syn"], "eth0", mark=0), False),
    ("⚠️ a marked SYN to a destination the marked table keeps on this node", pkt("10.9.0.5", ["syn"], "eth0", route_mark="wgn1", mark=0x1b58), False),
    ("⚠️ a marked SYN-ACK", pkt("10.9.0.5", ["syn", "ack"], "eth0", route_mark="swg_1d430ded", mark=0x1b58), False),
]:
    check("%s → %s" % (name, "taken" if want else "left alone"), matches(T, p) == want, T)
    check("…and counted exactly when taken", matches(C, p) == matches(T, p), C)

print("\n[3] the rest of the table is untouched by this")
txt = N._relay_nft([W, M], (), LEGS)
check("the established-connection rule still comes first and still needs a transparent socket",
      txt.index("socket transparent 1") < txt.index('swg-relay-syn:'), txt[:300])
check("the input port guard is still there for every relay port",
      "tcp th dport 5703 counter drop" in txt and "tcp th dport 5632 counter drop" in txt)
check("each counter sits directly above the rule it counts for", all(
    txt.splitlines()[k + 1].endswith('comment "swg-relay:%s"' % re.search(r'swg-relay-syn:([^"]+)', l).group(1))
    for k, l in enumerate(txt.splitlines()) if "swg-relay-syn:" in l))

print("\n[3b] the legs are the node's own mesh links, whatever the panel called them")
d = tempfile.mkdtemp()
def conf(name, addr, extra=""):
    f = os.path.join(d, name + ".conf")
    open(f, "w").write("[Interface]\nAddress = %s\nPrivateKey = x\n%s" % (addr, extra))
    return {"conf": f}
cfg = {"interfaces": {"wgn1": conf("wgn1", "10.141.0.1/24"), "swg_1d430ded": conf("swg_1d430ded", "10.255.0.1/31"),
                      "mesh_ab12": conf("mesh_ab12", "10.255.0.9/31"), "lnk7": conf("lnk7", "10.254.0.1/24", "Table = off\n")}}
N._RELAY_LINKS.update(key=None, links=())
legs = N._relay_links(cfg)
check("a swg_ link, a /31 link under another prefix and a `Table = off` link are legs; a client tunnel is not",
      legs == ("lnk7", "mesh_ab12", "swg_1d430ded"), legs)
cfg["interfaces"]["swg_0900e8bd"] = conf("swg_0900e8bd", "10.255.0.7/31")
check("…and a link added later is picked up", "swg_0900e8bd" in N._relay_links(cfg), N._relay_links(cfg))
rr = open(NODED, encoding="utf-8").read()
body = rr[rr.index("def reconcile_relay("):rr.index("def _relay_quota_effective(")]
check("the loop hands the watchdog the node's links", "reconcile_relay(_relay_plan, _rr, _relay_sync_ok, _relay_links(node_cfg))" in rr)

print("\n[3c] driven through reconcile_relay itself — the table it would load, not the builder in isolation")
# ⚠️ WHY THIS EXISTS: the first build passed every check above and loaded NOTHING on swgt. `reconcile_relay` reassigns
# `legs = plan.get("legs")`, and the new parameter had the same name, so the divert named the plan's leg dicts:
# `oifname { "{'iface': 'wg1', …}" }`. Only a run through the caller shows what reaches nft.
loaded = []
class R:
    def __init__(self, out=""): self.returncode, self.stdout, self.stderr = 0, out, ""
def fake_run(cmd, input_text=None, **kw):
    if cmd[:2] == ["nft", "-f"]:
        loaded.append(input_text)
    return R()
for name, val in (("run", fake_run), ("_relay_capable", lambda: (True, "")), ("_relay_supervise", lambda *a, **k: None),
                  ("_relay_probe", lambda i, now, div: (True, "", {"live": 0})), ("_relay_diverted", lambda: {}),
                  ("_relay_unroutable", lambda *a, **k: {}), ("_relay_table_live", lambda: False),
                  ("_relay_note", lambda *a, **k: None), ("_iface_addr", lambda i: "10.141.0.1"),
                  ("_relay_mss", lambda *a, **k: 1300)):
    setattr(N, name, val)
N._RELAY_ARM.update(sig=None, booted=True, want=None)
plan = {"legs": [{"iface": "wgn1", "peer": "", "subnet": "10.141.0.0/24", "mark": 0, "up_table": 7001, "port": 5703}]}   # a whole-interface cascade: no peer in the instance name
res = {"changed": 0, "errors": []}
N.reconcile_relay(plan, res, True, ("swg_93c2fdf8",))
div = [l for l in (loaded[-1] if loaded else "").splitlines() if 'swg-relay:wgn1"' in l]
check("the divert it loads names the node's mesh link, and nothing else in that set",
      len(div) == 1 and 'oifname { "swg_93c2fdf8" }' in div[0], (div or loaded)[:1])
loaded.clear(); N._RELAY_ARM.update(sig=None)
res = {"changed": 0, "errors": []}
N.reconcile_relay(plan, res, True, ())
check("a node with no mesh link loads no divert and says why", not any("tproxy" in t for t in loaded)
      and "no mesh link" in (N._RELAY.get("wgn1") or {}).get("why", ""), (loaded, N._RELAY.get("wgn1")))
check("the arm signature carries the links, so a link added or removed re-arms", "json.dumps([entries, list(links)]" in body)

relay = open(os.path.join(HERE, "..", "swg-relay"), encoding="utf-8").read()
print("\n[4] the relay itself never dials an address of this host, on any port")
acc = relay[relay.index("dst = cli.getsockname()"):relay.index("R.start(cli, dst)")]
check("the accept-site guard is `is_local_addr(dst[0])` with no port condition",
      re.search(r"if is_local_addr\(dst\[0\]\):", acc) is not None and "a.port" not in acc, acc[-240:])

print()
if MODE:
    print("--perturb-%s: %d check(s) RED" % (MODE, len(FAILS)))
    sys.exit(0 if FAILS else 1)
print("%d failing" % len(FAILS))
sys.exit(1 if FAILS else 0)
