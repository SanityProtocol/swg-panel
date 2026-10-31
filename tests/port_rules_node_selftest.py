#!/usr/bin/env python3
"""Self-test for ports on a routing rule, the node half (docs/NEVER-BLOCK-AND-PORT-RULES-PLAN.md B.4, B.7; 1.8.11 S6).

A smart entry may carry `ports: {proto, list}`. `_ensure_smart_nft` renders it as one L4 match beside the entry's own, in all
four places an entry is rendered, and the three consumers that read every entry as a TCP 443 rule take it only when its ports
include TCP 443. Each checked on what the node hands nft, through the swg_smart model (tests/nft_guarded_model.py) and packets:

  [1] RENDERING      — the base chain, a per-person row, a shadow copy, a pin-mode Block chain's exception: a packet on the
                       rule's ports takes it, the same destination on another port goes on to the next rule (all three engines).
  [2] NEVER WIDER    — an entry whose `ports` does not read is dropped, never rendered for every port.
  [3] THE SIGNATURE  — a change of ports alone rebuilds the chain; a plan without ports signs and renders byte-for-byte as the
                       node before ports (BASE) did, in all three engines.
  [4] TCP 443 ONLY   — swg-sni's verdicts (`sni_blocks`), the route-back chain `svb` and xt_string's list take a port entry
                       only when it reaches TCP 443: a UDP-only Block is never exported to swg-sni.
  [5] COVERAGE       — a port entry covers a broader name's rule only on ports that hold all of that rule's: a UDP 3478 rule
                       takes a UDP 3478 rule's hosts in any order, never a rule's for every port (that one keeps its shadow);
                       decided alike by `_smart_shadows` and per entry at render.
  [6] THE REPORT     — `smartroute.ports`, which the panel's withholding reads.
  Also: the L4 match comes after `ct state new` (an established packet never compares it); a pin-mode Block's exception
  never puts a port match beside swg-sni's `tcp dport 443` (a batch nft refuses — the model refuses it too); a UDP-only
  Block still keeps its names out of swg-sni's learning (`nolearn`); a category whose every Exit and Direct is off TCP 443
  learns without a reset (`quiet`); a port Block is not a name's verdict for Force-DNS's sparing (`dnsok`).

Hermetic: no nft, no root. Run: python3 tests/port_rules_node_selftest.py   (0 = pass)
  --plant p1..p10   plant one defect and expect RED on its own check (exit 0 when caught):
     p1  the base chain drops the ports        p2  a row chain drops them          p3  a pb exception forgets j's ports
     p4  a shadow copy drops them              p5  swg-sni takes a UDP-only rule   p6  a port entry counts as coverage
     p7  an unreadable `ports` is rendered     p8  the ports are not signed        p9  `svb` takes a UDP-only Exit
     p10 every plan signs `pt` (a node without ports rebuilds on upgrade)
     p11 the pb queue rule keeps j's UDP match       p12 a port Block joins Force-DNS's sparing (dns_blk)
     p13 no `quiet` list                             p14 a UDP-only Block alone writes no sni-blocks (no `nolearn`)
     p15 the L4 match before `ct state new`          p16 overlapping spans are not merged
     p17 a port entry covers nothing at render (an equal-ports claimer leaves the broader entry its shadow copy)
"""
import atexit, hashlib, importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile
os.environ["SWG_NFT_CLI_ONLY"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
BASE = os.environ.get("SWG_PORTS_BASE") or "33a6819b"     # origin/dev before 1.8.11 S6 — the last node without ports
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "p1": ('''                    _add("ip", "saddr", S, *_new, *pm, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "return")''',
           '''                    _add("ip", "saddr", S, *_new, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "return")'''),
    "p2": ('''                        bat.add(*_row, *_new, *pm, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "accept")''',
           '''                        bat.add(*_row, *_new, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "accept")'''),
    "p3": ('''[[cnd + pt_of[j], snm, None if j in off443 else cnd] if j in pt_of else [cnd, snm]''', '''[[cnd, snm]'''),
    "p4": ('''            pmi = pt_of.get(i, [])                             # …on its ports (B.4)''', '''            pmi = []'''),
    "p5": ('''            if w[1] != "all" and i not in off443:              # swg-sni decides TCP 443 only: a rule off it is not its to apply''',
           '''            if w[1] != "all":'''),
    "p6": ('''        return any(not any((x is None or x == w) and _ports_cover(p1, p2) for x, p1 in cov.get(S, ()))''',
           '''        return any(not any((x is None or x == w) for x, p1 in cov.get(S, ()))'''),
    "p7": (''' and ("ports" not in e or _ports_spans(e["ports"]) is not None)
''', '''
'''),
    "p8": ('''        sig = hashlib.sha1((sig + "|pt:" + json.dumps(sorted(pt_of.items()))).encode()).hexdigest()[:16]''', '''        pass'''),
    "p9": ('''                if wj[0] == w[0] and wj[2] in ("exit", "direct") and wj[1] != "all" and j not in off443:''',
           '''                if wj[0] == w[0] and wj[2] in ("exit", "direct") and wj[1] != "all":'''),
    "p10": ('''    if pt_of:                                                   # B.4 — only a plan with a port rule signs its ports''',
            '''    if True:'''),
    "p11": ('''cnd, snm, qc = x[0], x[1], (x[2] if len(x) > 2 else x[0])''', '''cnd, snm, qc = x[0], x[1], x[0]'''),
    "p12": ('''            if w[2] == "block" and w[1] != "all" and i not in pt_of:''', '''            if w[2] == "block" and w[1] != "all":'''),
    "p13": ('''            if _q:
                sni_blocks["quiet"] = _q''', '''            if False:
                sni_blocks["quiet"] = _q'''),
    "p14": ('''    if queue and (_has_blk or off443):''',
            '''    if queue and any(w[2] == "block" and w[1] != "all" and i not in off443 for i, w in enumerate(want)):'''),
    "p15": ('''                    _add("ip", "saddr", S, *_new, *pm, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "return")''',
            '''                    _add("ip", "saddr", S, *pm, *_new, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "return")'''),
    "p16": ('''        if out and a <= out[-1][1] + 1:''', '''        if False:'''),
    "p17": ('''for x, p1 in aud.get(c, {}).get(w[0], ()) if _ports_cover(p1, ps_of.get(i))}''',
            '''for x, p1 in aud.get(c, {}).get(w[0], ()) if p1 is None}'''),
}

STATE = tempfile.mkdtemp(prefix="port-rules-node-")
atexit.register(shutil.rmtree, STATE, True)
os.environ["SWG_NODED_STATE"] = STATE


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(NODED, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(STATE, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
N = load(path, "swgnoded_ports")
T = N.SMART_NFT_TABLE
S = "10.8.0.0/24"
W1 = "1f2e3d4c5b6a"
CHOSEN, OTHER = "10.8.0.5", "10.8.0.6"
SRCS = {W1: [["wg0", CHOSEN + "/32"]]}
MODES = (("kernel / Force-DNS", False, False), ("Hybrid SNI", True, True), ("Kernel SNI", True, False))


def fresh(mod):
    mod.GEO_DIR = os.path.join(STATE, "geo-" + mod.__name__)
    shutil.rmtree(mod.GEO_DIR, ignore_errors=True)
    os.makedirs(mod.GEO_DIR)
    open(os.path.join(mod.GEO_DIR, ".automerge-migrated"), "w").write("1")
    mod._SRC_SETS.clear()
    K = SmartKernel()
    mod.run = K
    return K


def npass(mod, K, entries, pin, queue, shadows=None, name_cats=None, **kw):
    mod._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    n0 = len(K.scripts)
    try:
        mod._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=pin, queue=queue,
                              reset_mark=(mod.SNI_RESET_MARK if pin else 0), srcs=SRCS, shadows=shadows, name_cats=name_cats, **kw)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    res["scripts"] = K.scripts[n0:]
    return res


def fill(K, dest):
    for c, cidr in dest.items():
        for nm in (N._smart_setname(c), N._smart_learnsetname(c)):
            if nm in ((K.m.tables.get(T) or {}).get("sets") or {}):
                K.load_set(T, nm, [cidr]) if nm.startswith("cat_") else K.m._add_elements(K.m.tables[T]["sets"][nm], cidr)


def pk(K, src, dst, proto, port, iif="wg0"):
    return K.m.packet(T, iif, src, dst, proto=proto, dport=port, ct="new")


def rules_text(K):
    return [x["text"] for c in ((K.m.tables.get(T) or {}).get("chains") or {}).values() for x in c["rules"]]


G, B, X, Y, Z = "198.51.100.9", "203.0.113.9", "100.64.0.9", "100.65.0.9", "100.66.0.9"
DEST = {"custom_g": "198.51.100.0/24", "custom_b": "203.0.113.0/24", "custom_x": "100.64.0.0/24", "custom_y": "100.64.0.0/24",
        "custom_e": "100.65.0.0/24", "custom_z": "100.66.0.0/24"}
ENT = [
    {"subnet": S, "category": "custom_g", "action": "direct", "ports": {"proto": "udp", "list": "19302-19309"}},
    {"subnet": S, "category": "custom_g", "action": "exit", "via_iface": "swg_p", "table": 7000},
    {"subnet": S, "category": "custom_b", "action": "exit", "via_iface": "swg_q", "table": 7001, "src": W1,
     "ports": {"proto": "tcp", "list": "8000-8100"}},
    {"subnet": S, "category": "custom_e", "action": "block", "ports": {"proto": "udp", "list": "27000,27050-27100"}},
    {"subnet": S, "category": "custom_z", "action": "exit", "via_iface": "swg_r", "table": 7003, "ports": {"proto": "both", "list": "53"}},
    {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_s", "table": 7002},
]

# ── [1] rendering ───────────────────────────────────────────────────────────────────────────────────────────────────────────
for label, pin, queue in MODES:
    print("\n[1] %s" % label)
    K = fresh(N)
    r = [npass(N, K, ENT, pin, queue)]
    fill(K, DEST)
    r += [npass(N, K, ENT, pin, queue) for _ in range(2)]
    check("%s: every pass runs, nothing refused by nft" % label, not any(x["errors"] for x in r) and not K.refused,
          ([x["errors"] for x in r], K.refused[:1]))
    check("%s: pass 3 changes nothing" % label, not r[2]["scripts"], r[2]["scripts"][:1])
    if r[0]["errors"] or T not in K.m.tables:
        continue
    v = pk(K, OTHER, G, "udp", 19305)
    check("%s: base chain — UDP 19305 takes the port rule (Direct, unmarked)" % label, v["mark"] == 0 and v["verdict"] == "accept", v)
    v = pk(K, OTHER, G, "tcp", 19305)
    check("%s: …TCP on the same port goes on to the next rule (7000)" % label, v["mark"] == 7000, v)
    v = pk(K, OTHER, G, "udp", 19310)
    check("%s: …UDP outside its ports too (7000)" % label, v["mark"] == 7000, v)
    v = pk(K, CHOSEN, B, "tcp", 8080)
    check("%s: per-person row — the chosen device on TCP 8080 takes it (7001)" % label, v["mark"] == 7001, v)
    v = pk(K, CHOSEN, B, "tcp", 9000)
    check("%s: …on another port it does not (catch-all 7002)" % label, v["mark"] == 7002, v)
    v = pk(K, OTHER, Y, "udp", 27060)
    check("%s: a UDP-only Block drops its ports" % label, v["verdict"] == "drop", v)
    v = pk(K, OTHER, Y, "tcp", 443)
    check("%s: …and leaves TCP 443 to the same address alone (7002)" % label, v["verdict"] == "accept" and v["mark"] == 7002, v)
    v = pk(K, OTHER, Z, "udp", 53)
    check("%s: `both` matches UDP 53 (7003)…" % label, v["mark"] == 7003, v)
    v = pk(K, OTHER, Z, "tcp", 53)
    check("%s: …and TCP 53 (7003)" % label, v["mark"] == 7003, v)
    if pin:
        bad = [t for t in rules_text(K) if "meta mark set" in t and ("dport" in t or "l4proto" in t)
               and not 0 <= t.find("ct state new") < min(i for i in (t.find("l4proto"), t.find("dport")) if i >= 0)]
        check("%s: a mark rule's port match comes after `ct state new` (an established packet never compares it)" % label, not bad, bad[:2])
    if queue:
        B1 = N._SNI_BLOCKS["v"] or {}
        check("%s: the only Block is UDP-only — swg-sni has no verdict to give for it" % label, not B1.get("src"), B1)
        check("%s: …and still learns none of its names (`nolearn`)" % label, "custom_e" in (B1.get("nolearn") or []), B1)
        check("%s: a category whose every Exit and Direct is off TCP 443 learns without a reset (`quiet`); one with a TCP 443 "
              "rule (custom_g) resets as before" % label, B1.get("quiet") == ["custom_b", "custom_z"], B1)
        K = fresh(N)
        npass(N, K, [{"subnet": S, "category": "custom_e", "action": "block", "ports": {"proto": "udp", "list": "27000"}},
                     {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_s", "table": 7002}], pin, queue)
        B1 = N._SNI_BLOCKS["v"] or {}
        check("%s: a UDP-only Block alone still writes `nolearn` (swg-sni must not learn and reset its names)" % label,
              "custom_e" in (B1.get("nolearn") or []) and "quiet" not in B1, B1)
    if pin:
        # pb<i>: an Exit (UDP 5000 only) above a Block of the same address — the exception is the Exit's ports, nothing more
        PB = [{"subnet": S, "category": "custom_x", "action": "exit", "via_iface": "swg_p", "table": 7004, "ports": {"proto": "udp", "list": "5000"}},
              {"subnet": S, "category": "custom_y", "action": "block"},
              {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_s", "table": 7002}]
        K = fresh(N)
        npass(N, K, PB, pin, queue)
        fill(K, DEST)
        rp = npass(N, K, PB, pin, queue)
        check("%s: pin-mode Block below a port Exit builds its chain" % label, not rp["errors"] and "pb1" in K.m.tables[T]["chains"],
              (rp["errors"], sorted(K.m.tables.get(T, {}).get("chains", {}))))
        v = pk(K, OTHER, X, "udp", 5000)
        check("%s: pb — the Exit's own port is let through its Block (7004)" % label, v["mark"] == 7004 and v["verdict"] != "drop", v)
        v = pk(K, OTHER, X, "tcp", 443, )
        v2 = K.m.packet(T, "wg0", OTHER, X, proto="tcp", dport=443, ct="established", ctmark=7004)
        check("%s: pb — any other port to that address is the Block's (dropped)" % label, v["verdict"] == "drop" and v2["verdict"] == "drop",
              (v, v2))
        # …an Exit on TCP and UDP 400-500 above it: the exception keeps its ports; swg-sni's queue rule (`tcp dport 443`) none
        PB2 = [dict(PB[0], ports={"proto": "both", "list": "400-500"})] + PB[1:]
        K = fresh(N)
        npass(N, K, PB2, pin, queue)
        fill(K, DEST)
        rp = npass(N, K, PB2, pin, queue)
        pbt = [x["text"] for x in ((K.m.tables.get(T) or {}).get("chains") or {}).get("pb1", {}).get("rules", [])]
        check("%s: pb — a TCP+UDP port Exit's exception carries its ports, and a queue rule without them (nft refuses both)" % label,
              not rp["errors"] and any("l4proto" in t and "accept" in t for t in pbt)
              and (not queue or any("queue" in t and "l4proto" not in t for t in pbt)), (rp["errors"], pbt))
        v = pk(K, OTHER, X, "udp", 450)
        check("%s: pb — UDP 450 is the Exit's (7004), let through its Block" % label, v["mark"] == 7004 and v["verdict"] != "drop", v)

# a shadow copy carries its entry's ports — a broad port rule R and a more specific port rule L (never coverage, [5])
print("\n[1] shadow copies")
SH = [{"subnet": S, "category": "custom_r", "action": "exit", "via_iface": "swg_p", "table": 7005, "ports": {"proto": "udp", "list": "3478"}},
      {"subnet": S, "category": "custom_l", "action": "exit", "via_iface": "swg_q", "table": 7006, "ports": {"proto": "tcp", "list": "443"}}]
DOMS = {"custom_r": ["example.com"], "custom_l": ["a.example.com"]}
for label, pin, queue, eng in (("Force-DNS", False, False, "dns"), ("Hybrid SNI", True, True, "sni_user")):
    shw = N._smart_shadows(SH, DOMS, {}, eng)
    K = fresh(N)
    rr = npass(N, K, SH, pin, queue, shadows=shw)
    sh = [x for x in ((shw or {}).get("by_target") or {}).get("custom_r", [])]
    lines = [t for t in rules_text(K) if sh and "@" + N._smart_setname(sh[0][0]) + " " in t + " "]
    check("%s: the broader port rule gets a shadow, and its copy carries the rule's own ports" % label,
          not rr["errors"] and lines and all("meta l4proto udp th dport 3478" in t for t in lines), (rr["errors"], sh, lines))

# ── [2] never wider ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] never wider")
K = fresh(N)
BAD = [{"subnet": S, "category": "custom_b", "action": "block", "ports": {"proto": "udp", "list": "nope"}},
       {"subnet": S, "category": "custom_g", "action": "block", "ports": {"proto": "both", "list": ""}},
       {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_s", "table": 7002}]
rb = npass(N, K, BAD, False, False)
fill(K, DEST)
check("an entry whose `ports` does not read is not rendered at all", not rb["errors"]
      and not any("@cat_custom_b" in t or "@cat_custom_g" in t for t in rules_text(K)), rules_text(K))
check("…so its destination is not blocked on any port", pk(K, OTHER, B, "tcp", 443)["mark"] == 7002)
K = fresh(N)
CA = [{"subnet": S, "category": "all", "action": "block", "ports": {"proto": "udp", "list": "53"}},
      {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_s", "table": 7002}]
rc = npass(N, K, CA, False, False)
v1, v2 = pk(K, OTHER, B, "udp", 53), pk(K, OTHER, B, "tcp", 443)
check("a catch-all carrying `ports` is never lowered (B.2 refuses it): the next one takes its own ports and every other (7002)",
      not rc["errors"] and v1["mark"] == 7002 and v1["verdict"] != "drop" and v2["mark"] == 7002, (rc["errors"], v1, v2))
check("spans that overlap or touch are merged before nft sees them: one interval, one match",
      N._ports_spans({"proto": "tcp", "list": "8050,8000-8100,8101"}) == ("tcp", [(8000, 8101)])
      and N._ports_match({"proto": "tcp", "list": "8050,8000-8100,8101"}) == ["meta", "l4proto", "tcp", "th", "dport", "8000-8101"])

# ── [3] the signature ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the signature")
K = fresh(N)
for _ in range(2):
    npass(N, K, ENT, False, False)
alt = [dict(e, ports={"proto": "udp", "list": "19302-19400"}) if e.get("ports", {}).get("list") == "19302-19309" else e for e in ENT]
ra = npass(N, K, alt, False, False)
fill(K, DEST)
check("a change of ports alone rebuilds the chain", ra["scripts"] and pk(K, OTHER, G, "udp", 19350)["mark"] == 0,
      (ra["scripts"][:1], pk(K, OTHER, G, "udp", 19350)))
r = subprocess.run(["git", "-C", ROOT, "show", "%s:swg-noded" % BASE], capture_output=True, text=True)
if r.returncode:
    check("the base node is readable (git show %s)" % BASE, False, r.stderr[:200])
else:
    bp = os.path.join(STATE, "base-noded.py")
    open(bp, "w", encoding="utf-8").write(r.stdout)
    H = load(bp, "swgnoded_base")
    PLAIN = [dict({k: v for k, v in e.items() if k != "ports"}) for e in ENT] + [
        {"subnet": S, "category": "custom_y", "action": "block"}]
    for label, pin, queue in MODES:
        out = []
        for mod in (N, H):
            K = fresh(mod)
            sc = [npass(mod, K, PLAIN, pin, queue)["scripts"] for _ in range(2)]
            sig = open(os.path.join(mod.GEO_DIR, ".smart-sig")).read() if os.path.exists(os.path.join(mod.GEO_DIR, ".smart-sig")) else ""
            out.append((json.dumps(sc), json.dumps([" ".join(c) for c in K.calls]), sig, json.dumps(mod._SNI_BLOCKS["v"], sort_keys=True)))
        check("%s: a plan without ports renders and signs byte-for-byte as the base node" % label, out[0] == out[1],
              [i for i in range(4) if out[0][i] != out[1][i]])
    for eng in ("dns", "sni_user"):
        a, b = N._smart_shadows(SH and [dict({k: v for k, v in e.items() if k != "ports"}) for e in SH], DOMS, {}, eng), \
            H._smart_shadows([dict({k: v for k, v in e.items() if k != "ports"}) for e in SH], DOMS, {}, eng)
        check("%s: _smart_shadows without ports answers as the base node" % eng, json.dumps(a, sort_keys=True, default=str)
              == json.dumps(b, sort_keys=True, default=str))

# ── [4] TCP 443 only ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the TCP-443 consumers")
check("_ports_t443: no ports, TCP 443, TCP 400-500, `both` with no list — yes; UDP, TCP 80, `both` 53 — no",
      [N._ports_t443(e) for e in ({}, {"ports": {"proto": "tcp", "list": "443"}}, {"ports": {"proto": "tcp", "list": "400-500"}},
                                   {"ports": {"proto": "tcp", "list": ""}}, {"ports": {"proto": "udp", "list": "443"}},
                                   {"ports": {"proto": "tcp", "list": "80"}}, {"ports": {"proto": "both", "list": "53"}},
                                   {"ports": {"proto": "udp", "list": "x"}})] == [True, True, True, True, False, False, False, False])
NC = {"custom_x", "custom_y", "custom_e"}
SB = [{"subnet": S, "category": "custom_x", "action": "exit", "via_iface": "swg_p", "table": 7004, "ports": {"proto": "udp", "list": "443"}},
      {"subnet": S, "category": "custom_y", "action": "block"},
      {"subnet": S, "category": "custom_e", "action": "block", "ports": {"proto": "tcp", "list": "400-500"}},
      {"subnet": S, "category": "custom_z", "action": "block", "ports": {"proto": "udp", "list": "3478"}}]
K = fresh(N)
rs = npass(N, K, SB, True, True, name_cats=NC)
B4 = N._SNI_BLOCKS["v"] or {}
cats = [r[2][0][0] for _S, rl in B4.get("src") or [] for r in rl]
check("swg-sni gets the Blocks that reach TCP 443 (one without ports, one TCP 400-500)", not rs["errors"] and "custom_y" in cats
      and "custom_e" in cats, (rs["errors"], cats))
check("…and neither the UDP-only Block nor the UDP-only Exit", "custom_z" not in cats and "custom_x" not in cats, cats)
check("`svb` — a UDP-only Exit above a Block by name gives it no route back (no chain)", "svb" not in (K.m.tables.get(T) or {}).get("chains", {}),
      sorted((K.m.tables.get(T) or {}).get("chains", {})))
SB2 = [dict(SB[0], ports={"proto": "tcp", "list": "443"})] + SB[1:]
K = fresh(N)
npass(N, K, SB2, True, True, name_cats=NC)
check("…a TCP 443 Exit there does (the control)", "svb" in (K.m.tables.get(T) or {}).get("chains", {}))
src = open(path, encoding="utf-8").read()
check("xt_string is handed only the entries that reach TCP 443 (Exit, Direct and Block by name alike)",
      "and (_ks or \"src\" not in e) and _ports_t443(e)], domains, SNI_RESET_MARK, res," in src
      and "and (_ks or \"src\" not in e) and _ports_t443(e) for e in smart_e)" in src)

# ── [5] not coverage ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] coverage")
R_ = {"subnet": S, "category": "custom_r", "action": "exit", "via_iface": "swg_p", "table": 7005}
L_ = {"subnet": S, "category": "custom_l", "action": "exit", "via_iface": "swg_q", "table": 7006}
for eng in ("dns", "sni_user"):
    with_ports = N._smart_shadows([R_, dict(L_, ports={"proto": "udp", "list": "3478"})], DOMS, {}, eng)
    without = N._smart_shadows([R_, L_], DOMS, {}, eng)
    check("%s: a more specific PORT rule leaves the broader rule a shadow of its hosts" % eng,
          [x[1] for x in ((with_ports or {}).get("by_target") or {}).get("custom_r", [])] == ["custom_l"], with_ports)
    check("%s: …the same rule without ports takes them (no shadow — the control)" % eng, without == {}, without)
K = fresh(N)
shw = N._smart_shadows([R_, dict(L_, ports={"proto": "udp", "list": "3478"})], DOMS, {}, "dns")
rr = npass(N, K, [dict(L_, ports={"proto": "udp", "list": "3478"}), R_], False, False, shadows=shw)
shn = N._smart_setname(shw["by_target"]["custom_r"][0][0]) if shw else ""
K.load_set(T, N._smart_setname("custom_l"), ["192.0.2.0/24"])         # dnsmasq: a.example.com's address, in its own key only
if shn in K.m.tables.get(T, {}).get("sets", {}):
    K.load_set(T, shn, ["192.0.2.0/24"])                               # …and in the shadow of the broader rule
v1, v2 = pk(K, OTHER, "192.0.2.9", "udp", 3478), pk(K, OTHER, "192.0.2.9", "tcp", 443)
check("Force-DNS: the port rule above takes its host on UDP 3478 (7006), the broader rule keeps it elsewhere (7005)",
      not rr["errors"] and v1["mark"] == 7006 and v2["mark"] == 7005, (rr["errors"], v1, v2))
U3 = {"proto": "udp", "list": "3478"}
for eng in ("dns", "sni_user"):
    same = N._smart_shadows([dict(R_, ports=U3), dict(L_, ports=U3)], DOMS, {}, eng)
    check("%s: a more specific port rule on the SAME ports covers the broader one (no shadow: it wins in either order)" % eng,
          same == {}, same)
    fewer = N._smart_shadows([dict(R_, ports={"proto": "udp", "list": "3470-3480"}), dict(L_, ports=U3)], DOMS, {}, eng)
    check("%s: …on fewer ports it does not — the broader rule keeps its hosts on the rest (shadow)" % eng,
          [x[1] for x in ((fewer or {}).get("by_target") or {}).get("custom_r", [])] == ["custom_l"], fewer)
    both = N._smart_shadows([dict(R_, ports=U3), dict(L_, ports={"proto": "both", "list": "3478"})], DOMS, {}, eng)
    check("%s: …on TCP and UDP 3478 it covers a UDP 3478 rule" % eng, both == {}, both)
# the broader category with a UDP 3478 entry ABOVE the claimer and a port-less one below: the shadow exists (the port-less
# entry needs it), but only the port-less entry is given its copy — UDP 3478 to the claimed host is the claimer's
MIX = [dict(R_, ports=U3), dict(L_, ports=U3), R_]
K = fresh(N)
shw = N._smart_shadows(MIX, DOMS, {}, "dns")
rr = npass(N, K, MIX, False, False, shadows=shw)
shn = N._smart_setname(shw["by_target"]["custom_r"][0][0]) if shw else ""
K.load_set(T, N._smart_setname("custom_l"), ["192.0.2.0/24"])
if shn in K.m.tables.get(T, {}).get("sets", {}):
    K.load_set(T, shn, ["192.0.2.0/24"])
v1, v2 = pk(K, OTHER, "192.0.2.9", "udp", 3478), pk(K, OTHER, "192.0.2.9", "tcp", 443)
check("Force-DNS: a UDP 3478 rule of the broader name ABOVE the claimer on the same ports does not take its host (7006); the "
      "broader port-less rule keeps it elsewhere (7005)", not rr["errors"] and shw and v1["mark"] == 7006 and v2["mark"] == 7005,
      (rr["errors"], bool(shw), v1, v2))
# Force-DNS's sparing (D2) is node-wide: a port Block's names must not lose `dnsok`
K = fresh(N)
SP = [{"subnet": S, "category": "custom_a", "action": "block"},
      {"subnet": S, "category": "custom_v", "action": "block", "ports": {"proto": "udp", "list": "443"}}]
rd = npass(N, K, SP, False, False, spare_dns=True)
dsp = (N._DNS_SPARE.get("v") or {}).get("block_sets") or []
check("Force-DNS: a port Block is not a name's verdict for the sparing — only the port-less Block's set is spared by `dnsok`",
      not rd["errors"] and dsp == [N._smart_setname("custom_a")]
      and not any("@" + N._smart_setname("custom_v") in t and "dnsok" in t for t in rules_text(K)), (rd["errors"], dsp))

# ── [6] the report ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the report")
check("smart_status says `ports` (the panel withholds port rules until it does)", '"ports": 1}' in src and "def smart_status" in src)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS)))
if PLANT:
    print("plant %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
