#!/usr/bin/env python3
"""Self-test for ARRIVALS on the node — the node's default list, for traffic other nodes cascade out through it
(docs/ROUTING-PEERS-MESH-PLAN.md §3, §6.1–6.3, §8 P3, T2/T6/T14/T28/T31/T34/T35).

`smart.arrivals = {subnets, entries}` becomes one jump right after the ct-mark restore,
`iifname @lg ip saddr @ar ip daddr != @cln jump sa`, and a chain `sa` holding the list. Checked on what `_ensure_smart_nft`
actually hands nft, through the swg_smart transaction model (tests/nft_guarded_model.py) and a packet walk, in all three
engine shapes (IP-only / Force-DNS, Hybrid SNI with the queue, Kernel SNI):

  · an arrival is routed by the list, first match, the catch-all last;
  · the ORIGIN GUARD — an arrival never takes a rule that would send it back out the leg it came in on (T28);
  · `cln` — an arrival to one of this node's own clients (or another origin's) is never marked away (T6);
  · the legs — only this node's mesh links, as the node judges them, never a name prefix;
  · a local client never walks `sa`, and a spoofed arrival source on a client device is not taken for one;
  · pin mode — every mark in `sa` decides on `ct state new`, so an established arrival packet reaches swg-sni's queue (T35),
    and a Block below an Exit keeps the Exit's connection (the 6a329ba shape, `pa<i>`);
  · the dashboards — arrivals are counted at their origin, never in this node's catcount (D12);
  · lifecycle — members replaced whole with no chain rebuild, the TTL swap flushes `sa` first (T2), everything reaped
    when the arrivals go, and a plan without arrivals renders exactly as without this code (§5.3);
  · Kernel SNI — the (subnet, leg) pairs in `swga`, the guard as `! -i`, and the closing RETURN (T34);
  · the report — `arr: 1`, arrival sets are not destinations, and the `devexit` report is one entry per key for arrivals (T31).

Hermetic: no nft, no ip, no root. Run: python3 tests/arrival_nft_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     cln  the arrival jump has no `ip daddr != @cln` (an arrival to a local client is sent out the exit)
     cc   arrivals are counted in catcount (the fleet total counts them twice)
     og   no origin guard on an arrival entry (a U-turn back out its own leg)
     lg   the legs are taken by name prefix (a mesh link the panel names otherwise carries no arrivals)
     t35  a mark in `sa` without the pin-mode `ct state new` gate (established arrival packets never reach swg-sni)
     t2   the TTL swap forgets `sa` (the whole batch is refused on an IP-learning change)
     reap `sa` is left behind when the arrivals go
     t34  Kernel SNI: no closing RETURN for arrivals (every guarded-out connection is reset for ever)
     kog  Kernel SNI: no origin guard
     ash  arrival rules ignore their shadow sets (a local rule's narrower name takes the arrival rule's hosts, T36)
     rf   an arrival set emptied from outside is never refilled (review #7)
     dd   the devexit report is not deduplicated for arrivals (~50 KB a sync at 30 nodes)
"""
import importlib.machinery, importlib.util, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "cln": ('''            _add("iifname", "@lg", "ip", "saddr", "@ar", "ip", "daddr", "!=", "@cln", "jump", "sa")''',
            '''            _add("iifname", "@lg", "ip", "saddr", "@ar", "jump", "sa")'''),
    "cc": ('''        subnets = sorted({e["subnet"] for e in smart_e})           # every client subnet under smart routing (incl catch-all)''',
           '''        subnets = sorted({e["subnet"] for e in smart_e} | set((arr or {}).get("subnets") or ()))'''),
    "og": ('''                gd = ["iifname", "!=", '"%s"' % g] if a == "exit" and g else []   # the ORIGIN GUARD (see aw)''',
           '''                gd = []'''),
    "lg": ('''    _arr = ({"subnets": arr_subs, "entries": arr_e, "legs": list(_relay_links(node_cfg)),''',
           '''    _arr = ({"subnets": arr_subs, "entries": arr_e, "legs": [n for n in (node_cfg.get("interfaces") or {}) if n.startswith("swg_")],'''),
    "t35": ('''                            _sa(*gd, *_new, "ip", "daddr", "@" + snm, *mk, "accept")''',
            '''                            _sa(*gd, "ip", "daddr", "@" + snm, *mk, "accept")'''),
    "t2": ('''if re.fullmatch(r"sr\\d+|pb\\d+|sa|pa\\d+", c))):''', '''if re.fullmatch(r"sr\\d+|pb\\d+", c))):'''),
    "reap": ('''        _gone_ax = [c for c in _here_ax if not arr or (c != "sa" and c not in want_pa)]''',
             '''        _gone_ax = [c for c in _here_ax if arr and c != "sa" and c not in want_pa]'''),
    "t34": ('''    for c in sorted({e["category"] for e in arr_ents}):
        rules.append(["-A", CHAIN, *_asrc, "-m", "set", "--match-set", _xts_setname(c), "dst", "-j", "RETURN"])''', ''),
    "kog": ('''        gd = ["!", "-i", e["via_iface"]]''', '''        gd = []'''),
    "rf": ("""            if sn not in have_sets or _ARR_SETS.get(sn) != msig or (mem and not _t["counts"].get(sn, 0)):""",
           """            if sn not in have_sets or _ARR_SETS.get(sn) != msig:"""),
    "ash": ("""                for c2 in [c] + ash_of.get(i, []):""", """                for c2 in [c]:"""),
    "dd": ('''               "@arr" if (e.get("subnet") or "") in _arr_raw else (e.get("subnet") or ""))''',
           '''               e.get("subnet") or "")'''),
}
STATE = tempfile.mkdtemp(prefix="arrival-nft-")
os.environ["SWG_NODED_STATE"] = STATE
path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(NODED, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(STATE, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))


def load(p, name):
    l = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    m.GEO_DIR = os.path.join(STATE, "geo-" + name)
    return m


N = load(path, "swgnoded_arr")
T = N.SMART_NFT_TABLE
S_LOCAL = "10.9.0.0/24"
LOCAL = [{"subnet": S_LOCAL, "category": "custom_l", "action": "exit", "via_iface": "wgx0", "table": 7000},
         {"subnet": S_LOCAL, "category": "all", "action": "exit", "via_iface": "wgy0", "table": 7001}]
# the list for arrivals: D2 → X (device), D1 → onward over swg_q (a leg: the origin guard is live), D3 → Block, rest → Y
ARR_E = [{"category": "custom_x", "action": "exit", "via_iface": "wgx0", "table": 7000},
         {"category": "custom_q", "action": "exit", "via_iface": "swg_q", "table": 7002},
         {"category": "custom_b", "action": "block"},
         {"category": "all", "action": "exit", "via_iface": "wgy0", "table": 7001}]
ARR = {"subnets": ["10.8.0.0/24", "10.28.0.0/24"], "entries": ARR_E, "legs": ["swg_n", "swg_q"],
       "cln": ["10.9.0.0/24", "10.8.0.0/24", "10.28.0.0/24"]}
DEST = {"custom_l": "198.51.100.0/24", "custom_x": "192.0.2.0/24", "custom_q": "203.0.113.0/24", "custom_b": "100.64.0.0/24"}
CATS = sorted({e["category"] for e in LOCAL + ARR_E})
MODES = (("IP-only / Force-DNS", False, False), ("Hybrid SNI", True, True), ("Kernel SNI", True, False))


def fresh(mod=None):
    mod = mod or N
    shutil.rmtree(mod.GEO_DIR, ignore_errors=True)
    os.makedirs(mod.GEO_DIR)
    open(os.path.join(mod.GEO_DIR, ".automerge-migrated"), "w").write("1")
    for d in ("_SRC_SETS", "_ARR_SETS"):
        if hasattr(mod, d):
            getattr(mod, d).clear()
    K = SmartKernel()
    mod.run = K
    return K


def fill(K, queue):
    for c, net in DEST.items():
        if ("cat_" + c) in K.m.tables[T]["sets"]:
            K.load_set(T, "cat_" + c, [net])


def apply(K, pin, queue, arrivals=ARR, ttl=3600, mod=None, cats=None):
    mod = mod or N
    mod._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    mod._ensure_smart_nft(LOCAL, cats or CATS, res, pin=pin, reset_mark=(0x9999 if pin else 0), queue=queue, learn_ttl=ttl,
                          arrivals=arrivals)
    return res


def pk(K, iif, s, d, **kw):
    return K.m.packet(T, iif, s, d, **kw)


for label, pin, queue in MODES:
    print("\n[%s]" % label)
    K = fresh()
    r = apply(K, pin, queue)
    fill(K, queue)
    check("%s: the batch landed" % label, not r["errors"] and not K.refused, (r["errors"], K.refused))
    a = pk(K, "swg_n", "10.8.0.10", "192.0.2.5")
    check("%s: an arrival to D2 is marked into X's table by the list" % label, a["mark"] == 7000 and "sa" in a["via"], a)
    a2 = pk(K, "swg_n", "10.28.0.10", "203.0.113.5")
    check("%s: an arrival from N to D1 takes the onward rule over swg_q" % label, a2["mark"] == 7002, a2)
    a3 = pk(K, "swg_q", "10.8.0.10", "203.0.113.5")
    check("%s: ⚠️ the same arrival coming IN over swg_q skips that rule — the origin guard (T28) — and meets the next" % label,
          a3["mark"] == 7001, a3)
    a4 = pk(K, "swg_n", "10.8.0.10", "100.64.0.5")
    check("%s: an arrival to a Block category is dropped" % label, a4["verdict"] == "drop", a4)
    a5 = pk(K, "swg_n", "10.8.0.10", "198.18.0.5")
    check("%s: an arrival no rule names takes the list's catch-all" % label, a5["mark"] == 7001, a5)
    a6 = pk(K, "swg_n", "10.8.0.10", "10.9.0.10")
    check("%s: ⚠️ an arrival to this node's OWN client is never marked away (`cln`, T6)" % label,
          a6["mark"] == 0 and "sa" not in a6["via"], a6)
    a7 = pk(K, "swg_n", "10.8.0.10", "10.28.0.99")
    check("%s: …nor one to another origin's client" % label, a7["mark"] == 0, a7)
    l1 = pk(K, "wg0", "10.9.0.10", "192.0.2.5")
    check("%s: this node's own client never walks `sa`" % label, "sa" not in l1["via"] and l1["mark"] == 7001, l1)
    l2 = pk(K, "wg0", "10.8.0.10", "192.0.2.5")
    check("%s: an arrival's source sent from a CLIENT device is not taken for an arrival" % label, "sa" not in l2["via"], l2)
    if pin:
        e1 = pk(K, "swg_n", "10.8.0.10", "192.0.2.5", ct="established", ctmark=7000, ctpackets=3)
        check("%s: ⚠️ an ESTABLISHED arrival packet is not accepted by `sa` — every mark there waits for `ct state new` (T35)" % label,
              e1["mark"] == 7000 and (e1["verdict"] == ("queue" if queue else "accept")), e1)
        if queue:
            check("%s: …so it reaches swg-sni's queue, which reads its ClientHello (§3.6)" % label, e1["verdict"] == "queue", e1)
    if pin:
        fw = " ".join(r_["text"] for r_ in (K.m.tables[T]["chains"].get("forward") or {}).get("rules", []))
        check("%s: an arrival's first-hit reset is rejected like a local one's" % label, "@ar" in fw and "reject" in fw, fw)
    # steady state: a second pass changes nothing; a member change replaces a set and rebuilds no chain
    h0 = K.handles(T, "prerouting") + K.handles(T, "sa")
    apply(K, pin, queue)
    check("%s: a second pass changes nothing" % label, K.handles(T, "prerouting") + K.handles(T, "sa") == h0)
    cc = " ".join(r_["text"] for c in ("catcount", "catany") for r_ in (K.m.tables[T]["chains"].get(c) or {}).get("rules", []))
    check("%s: catcount was built at all (a filled set is what builds it)" % label, bool(cc), cc)
    check("%s: arrivals are counted at their origin, never in this node's catcount (D12)" % label,
          "10.8.0.0" not in cc and "10.28.0.0" not in cc and "@ar" not in cc, cc[:300])
    apply(K, pin, queue, arrivals=dict(ARR, subnets=ARR["subnets"] + ["10.38.0.0/24"], legs=ARR["legs"] + ["mesh9"]))
    check("%s: a new origin subnet and a new leg replace the sets and rebuild NO chain" % label,
          K.handles(T, "prerouting") + K.handles(T, "sa") == h0 and pk(K, "mesh9", "10.38.0.1", "192.0.2.5")["mark"] == 7000,
          (h0, K.handles(T, "prerouting") + K.handles(T, "sa")))
    K.m.tables[T]["sets"]["ar"]["els"] = set()                   # a flush from outside (`nft flush set inet swg_smart ar`)
    apply(K, pin, queue, arrivals=dict(ARR, subnets=ARR["subnets"] + ["10.38.0.0/24"], legs=ARR["legs"] + ["mesh9"]))
    check("%s: an arrival set emptied from outside is refilled on the next pass (review #7)" % label,
          pk(K, "swg_n", "10.8.0.10", "192.0.2.5")["mark"] == 7000, pk(K, "swg_n", "10.8.0.10", "192.0.2.5"))
    if queue:
        rt = apply(K, pin, queue, ttl=120)
        check("%s: an IP-learning change with arrivals lands (T2: `sa` flushed before the learned sets are swapped)" % label,
              not rt["errors"] and not K.refused and "sa" in K.m.tables[T]["chains"], (rt["errors"], K.refused))
    apply(K, pin, queue, arrivals=None)
    t = K.m.tables[T]
    check("%s: with no arrivals left, `sa` and its sets are gone" % label,
          "sa" not in t["chains"] and not ({"lg", "ar", "cln"} & set(t["sets"])), (sorted(t["chains"]), sorted(t["sets"])))
    check("%s: …and the local client still routes" % label, pk(K, "wg0", "10.9.0.10", "192.0.2.5")["mark"] == 7001)

print("\n[a Block below an Exit, pin mode]")
K = fresh()
ov = [{"category": "custom_x", "action": "exit", "via_iface": "wgx0", "table": 7000}, {"category": "custom_ov", "action": "block"}]
apply(K, True, True, arrivals=dict(ARR, entries=ov), cats=CATS + ["custom_ov"])
DEST["custom_ov"] = "192.0.2.0/25"
K.load_set(T, "cat_custom_x", ["192.0.2.0/24"]); K.load_set(T, "cat_custom_ov", ["192.0.2.0/25"])
s1 = pk(K, "swg_n", "10.8.0.10", "192.0.2.5")
e1 = pk(K, "swg_n", "10.8.0.10", "192.0.2.5", ct="established", ctmark=7000, ctpackets=30)
check("an Exit above an overlapping Block keeps its connection past the SYN (`pa<i>`, the 6a329ba shape)",
      s1["mark"] == 7000 and e1["verdict"] != "drop", (s1, e1))
b1 = pk(K, "swg_n", "10.8.0.10", "192.0.2.200", ct="established", ctmark=0, ctpackets=30)
check("…while the Block still cuts every packet of what the Exit does not name", pk(K, "swg_n", "10.8.0.10", "192.0.2.5")["mark"] == 7000
      and pk(K, "swg_n", "10.8.0.10", "10.200.0.1")["mark"] == 0, b1)
del DEST["custom_ov"]

print("\n[shadow sets — an arrival rule's broader name keeps the hosts a local rule's narrower name claims (T36)]")
# Force-DNS: wg0's rule `sh.example.net` → Direct claims its hosts into ONE set (the most specific name wins, node-wide); the
# arrival rule `example.net` → X must still take them for arrivals — through the shadow set dnsmasq fills in lockstep.
_le = [{"subnet": S_LOCAL, "category": "custom_sh", "action": "direct"}]
_ae = [{"category": "custom_ex", "action": "exit", "via_iface": "wgx0", "table": 7000}]
_doms = {"custom_sh": ["sh.example.net"], "custom_ex": ["example.net"]}
_shw = N._smart_shadows(_le + [{"subnet": "@arr", "category": "custom_ex"}], _doms, {}, "dns")
K = fresh(); N._LOOP["n"] += 1
N._ensure_smart_nft(_le, ["custom_sh", "custom_ex"], {"changed": 0, "errors": []}, pin=False, queue=False, shadows=_shw,
                    arrivals=dict(ARR, entries=_ae))
_sh = [x[0] for x in (_shw.get("by_target") or {}).get("custom_ex", [])]
check("a shadow category exists for the broader arrival rule", len(_sh) == 1, _shw)
for _sn in ["cat_custom_sh"] + ["cat_" + x for x in _sh]:        # dnsmasq: the claimed host lands in the claimer's set AND the shadow
    K.load_set(T, _sn, ["198.18.5.5/32"])
_s1 = pk(K, "swg_n", "10.8.0.10", "198.18.5.5")
check("an ARRIVAL to a host the local rule's narrower name claimed is still routed by the arrival rule (via the shadow)",
      _s1["mark"] == 7000, _s1)
_s2 = pk(K, "wg0", "10.9.0.10", "198.18.5.5")
check("…while this node's own client keeps its own more specific Direct", _s2["mark"] == 0, _s2)

_le2 = [{"subnet": S_LOCAL, "category": "custom_ex", "action": "exit", "via_iface": "wgx0", "table": 7000}]
_ae2 = [{"category": "custom_sh", "action": "direct"}]
_shw2 = N._smart_shadows(_le2 + [{"subnet": "@arr", "category": "custom_sh"}], _doms, {}, "dns")
K = fresh(); N._LOOP["n"] += 1
N._ensure_smart_nft(_le2, ["custom_sh", "custom_ex"], {"changed": 0, "errors": []}, pin=False, queue=False, shadows=_shw2,
                    arrivals=dict(ARR, entries=_ae2))
for _sn in ["cat_custom_sh"] + ["cat_" + x[0] for x in (_shw2.get("by_target") or {}).get("custom_ex", [])]:
    K.load_set(T, _sn, ["198.18.5.5/32"])
_s3 = pk(K, "wg0", "10.9.0.10", "198.18.5.5")
check("…and the other way: an ARRIVAL rule's narrower name does not take the host from this node's own broader rule",
      _s3["mark"] == 7000, _s3)
check("…while the arrival keeps its own more specific Direct", pk(K, "swg_n", "10.8.0.10", "198.18.5.5")["mark"] == 0)

print("\n[a plan without arrivals is the plan it always was — §5.3]")
_base = os.environ.get("RIG_BASE_NODED")
K1 = fresh()
apply(K1, True, True, arrivals=None)
sig1 = open(os.path.join(N.GEO_DIR, ".smart-sig")).read()
check("no `sa`, no arrival set, and no arrival rule in a node with none",
      not any(re.search(r"\b(sa|lg|ar|cln)\b", s_) for s_ in K1.scripts), K1.scripts[:1])
if _base and os.path.exists(_base):
    B = load(_base, "swgnoded_base")
    KB = fresh(B)
    B._LOOP["n"] += 1
    B._ensure_smart_nft(LOCAL, CATS, {"changed": 0, "errors": []}, pin=True, reset_mark=0x9999, queue=True, learn_ttl=3600)
    check("…and it renders and signs EXACTLY what the base node did (§5.3)",
          KB.scripts == K1.scripts and open(os.path.join(B.GEO_DIR, ".smart-sig")).read() == sig1,
          (len(KB.scripts), len(K1.scripts)))

print("\n[Kernel SNI — P1b's ipsets, for arrivals]")
calls = []
N.run = lambda a, input_text=None, timeout=20: (calls.append((list(a), input_text)) or
                                                __import__("subprocess").CompletedProcess(a, 1 if a[:3] == ["iptables", "-t", "mangle"] and "-C" in a else 0, "", ""))
N._KSNI["ok"] = True
N._ensure_smart_xtstring([], {"custom_q": ["example.com"], "custom_x": ["example.net"]}, 0x9999, {"changed": 0, "errors": []},
                         arrivals={"entries": [e for e in ARR_E if e["action"] == "exit" and e["category"] != "all"],
                                   "pairs": [("10.8.0.0/24", "swg_n"), ("10.8.0.0/24", "swg_q")]})
ipt = [" ".join(a) for a, _ in calls if a[:3] == ["iptables", "-t", "mangle"] and "-A" in a]
rst = [x for (a, i) in calls if a[:2] == ["ipset", "-exist"] for x in (i or "").splitlines()]
check("the (origin subnet, leg) pairs are loaded into `swga`, bound to their leg",
      "add swgat 10.8.0.0/24,swg_n" in rst and "add swgat 10.8.0.0/24,swg_q" in rst, rst)
route_q = [x for x in ipt if "swgk_custom_q dst" in x and "MARK --set-mark 7002" in x]
check("a learned destination routes an arrival — with the origin guard as `! -i <leg>` (§3.5)",
      route_q and all("! -i swg_q" in x and "--match-set swga src,src" in x for x in route_q), route_q)
ret = [x for x in ipt if "--match-set swga src,src -m set --match-set swgk_custom_q dst -j RETURN" in x and "! -i" not in x]
check("⚠️ …closed by an UNGUARDED RETURN per category, so a guarded-out arrival is not re-learned and reset for ever (T34)", ret, ipt)
learn = [x for x in ipt if "--add-set swgk_custom_q" in x]
check("arrivals learn once per category, matched as `swga` pairs", len(learn) == 1 and "--match-set swga src,src" in learn[0], learn)

print("\n[the report]")
N.run = lambda a, input_text=None, timeout=20: __import__("subprocess").CompletedProcess(a, 1, "", "")
st = N.smart_status()
check("the node says it runs arrivals (`arr: 1`, §4.3)", st.get("arr") == 1, st)
N._SMART_TABLE.update(n=N._LOOP["n"], rc=0, out="", counts={"lg": 2, "ar": 2, "cln": 3, "cat_x": 4}, setnames=set(), bytes={})
st2 = N.smart_status()
check("…and does not report its arrival sets as destinations", set(st2.get("sets") or {}) == {"cat_x"}, st2.get("sets"))
# the devexit report, through reconcile_cascade with everything but the report stubbed away
N._devexit_state = lambda dev: "up"
N._dev_is_ether = lambda dev: False
cap = {}
N._ensure_smart_nft = lambda *a, **k: cap.update(k) or {}
for fn in ("_ensure_fwd_iptables", "_ensure_sni_router", "_ensure_smart_xtstring", "reconcile_catk_chain", "_ensure_smart_dnsmasq",
           "_dnsmasq_refill", "_ensure_doh_block", "_ensure_mech_block", "_ensure_torrent_sig", "_smart_geo_refresh",
           "_smart_load_cidrs", "_panel_list_refresh", "_apply_routing_reset", "_smart_domain_refresh"):
    setattr(N, fn, (lambda *a, **k: ({}, {})) if fn == "_smart_domain_refresh" else (lambda *a, **k: None))
N.run = lambda a, input_text=None, timeout=20: __import__("subprocess").CompletedProcess(a, 0, "", "")
N._cascade_local_routes = lambda cfg, _proc=None: [("10.9.0.0/24", "wg0")]
subs = ["10.%d.0.0/24" % i for i in range(40, 70)]
dxl = [{"subnet": s_, "dev": "wgx0", "table": 7000, "killswitch": True, "scope": "rule", "egress_ip": "", "gw": ""} for s_ in subs]
dxl += [{"subnet": "10.9.0.0/24", "dev": "wgx0", "table": 7000, "killswitch": True, "scope": "rule", "egress_ip": "", "gw": ""}]
cfg = {"interfaces": {"wg0": {"conf": "/nonexistent"}, "swg_n": {"conf": "/nonexistent"}, "lnk7": {"conf": "/nonexistent"}}}
N._iface_subnet = lambda c, n: {"wg0": "10.9.0.0/24", "swg_n": "10.255.0.0/31", "lnk7": "10.255.0.4/31"}.get(n, "")
N.reconcile_cascade(cfg, {"devexit": dxl, "exit": [{"subnet": s_, "via_iface": "swg_n", "table": 7003, "egress_ip": "", "wan_iface": ""}
                                                   for s_ in subs]},
                    {"entries": [], "arrivals": {"subnets": subs, "entries": [{"category": "all", "action": "exit", "via_iface": "wgx0", "table": 7000}]}})
rep = N._DEVEXIT["list"]
check("the devexit report stands for all 30 arrival subnets of one exit with ONE entry, flagged `arr` (T31)",
      len([e for e in rep if e.get("arr")]) == 1, len(rep))
check("…while this node's own entry keeps its own line and its subnet", any(e["subnet"] == "10.9.0.0/24" and not e.get("arr") for e in rep), rep)
check("the legs handed to the chain are this node's mesh links as the NODE judges them — a /31 link not named `swg_` too",
      sorted((cap.get("arrivals") or {}).get("legs") or []) == ["lnk7", "swg_n"], cap.get("arrivals"))
check("…and `cln` holds its client subnets and the exit subnets it holds for other nodes",
      {"10.9.0.0/24", "10.40.0.0/24"} <= set((cap.get("arrivals") or {}).get("cln") or []), (cap.get("arrivals") or {}).get("cln"))

if PLANT:
    want = {"cln": "OWN client is never marked", "cc": "counted at their origin", "og": "origin guard (T28)",
            "lg": "as the NODE judges them", "t35": "ESTABLISHED arrival packet", "t2": "IP-learning change with arrivals",
            "reap": "`sa` and its sets are gone", "t34": "UNGUARDED RETURN", "kog": "`! -i <leg>`",
            "dd": "ONE entry, flagged", "rf": "review #7", "ash": "via the shadow"}[PLANT]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit[:2]) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
