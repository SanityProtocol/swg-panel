#!/usr/bin/env python3
"""Self-test — a packet pays only for the rules that can match it (docs/DATAPATH-PLAN.md §8 item 1). DP1: the statistics;
DP2: dispatch by source.

`catcount` and `catany` were written per SUBNET × category: every forwarded packet walked 8·S·C + 4·S rules (1,452 on
msk-main, ~106 µs of a 157 µs packet). They now hold the subnets as one anonymous set and open with a sampling gate,
`numgen random mod N != 0 return`; SWG_INET and SWG_CATK open with the same gate in iptables. N is steered from forwarded
packets a second, lives only in the rule, and multiplies each DELTA a reader takes, never the cumulative value.

  [1] shape (real `_ensure_smart_nft`, nft transaction model): the gate heads both chains at N = 1, one subnet set per
      rule, no rule names one subnet alone; five times the subnets is the same rules, the same text but the set
  [2] the walk: a client packet, a reply, a transit packet — rules read in catcount + catany do not grow with subnets; a
      packet the gate skips reads 1 rule a chain, at any fleet size; a sampled packet still counts in the right counter,
      from every subnet, and a cross-subnet byte with no category counts as "up"
  [3] no empty set: an arrivals-only node (no local subnet) and a plan whose only subnet is not IPv4 render no `{ }`,
      and no batch is refused; a second pass over its own render rebuilds nothing
  [4] numgen refused: no gate, exact, the chains still built and signed apart (a later probe that takes it rebuilds)
  [5] the steer, from forwarded packets/s (ForwDatagrams): raise at once, lower only after 12 samples at a quarter or less;
      the nft gates replaced by handle (the same handle), the iptables gates by `-R 1` — only over a rule that IS the gate;
      a chain with no gate is never written; a refused step is retried on the next sample; a restart starts from the
      gates it finds; a rebuild writes the steered N; a step is a baseline for every reader (the rate holds, no spike)
  [6] the readers: delta × N, the cumulative values as counted; the gate's own bytes are no traffic and no category
  [7] iptables reconcile, SWG_INET and SWG_CATK: a 1.8.11 chain gets the gate by -I (pairs kept), a steered chain stands,
      a rebuild writes it first at the steered N, a chain with two gates or one astray is rebuilt; a refused gate (no
      xt_statistic) is asked again an hour later, not every pass
  [8] DP2, prerouting (real `_ensure_smart_nft`, three engines): each subnet's rules in a chain of its own, `pa100000+i`,
      a head set and one goto a subnet; a reply, an outer packet and transit read the same rules with 2 subnets and 10, a
      client at most the gotos more; one subnet or overlapping ones: one chain; arrivals only: no dispatch; a block list's
      drop counts into `c_bk`, read under "*"; a goto lost or a subnet's chain emptied from outside is rebuilt
  [9] the same verdict, mark and connection mark as the node before dispatch (1.8.11, 7fbf2cfc), packet by packet, three plans
  [10] on one kernel: the update, a subnet with a row leaving, a row leaving, a subnet arriving, and the downgrade to the
      node before dispatch with a row removed in the same window — no batch refused, nothing left of the dispatch
  [11] DP2b — the forward chain: the SNI reset one rule for every subnet, the IPv6 drops one rule a direction for every
      interface; the same rules and the same walk with 2 subnets and 2 interfaces as with 10 and 12; never `{ }`; every
      forwarded packet (IPv4 and IPv6, under every mark) decided as by 1.8.11; an older forward under this node's own render
      rebuilt once, a rule lost from outside rebuilt, an interface named `wg-drop` no rebuild a pass, the downgrade clean.
      swg_mech and swg_doh: one head set of every subnet, then an IPv6 return, ahead of rules that each open with a subnet
      inside the head, the rest the node before's own (swg_doh: the same matches, `fib` behind the port test); the update
      and the downgrade rebuild each once
  [12] prerouting, IPv6: `meta nfproto ipv6 return` right after the dispatch's head (`ip saddr` never holds for IPv6, so
      the head could not return it and it read every goto): the same rules with 2 subnets and 10, accepted unmarked; DP2a's
      layout without it, or one lost from outside, rebuilt once; one subnet's single chain needs none. [9] and [10] compare
      IPv6 packets with 1.8.11 too

Hermetic. Run: python3 tests/datapath_budget_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     ungated    catcount is built without its gate                                              [1]
     subloop    catcount goes back to one rule per subnet                                       [2]
     emptyset   the subnet set is written even when it is empty                                  [3]
     anygate    the steer writes `-R 1` whatever rule 1 is                                       [5]
     nobase     a step in N is not a baseline for the internet lane                              [5]
     nobasecat  …nor for Top destinations                                                        [5]
     noseed     a restart steers from N = 1, not from the gates it finds                         [5]
     rebuild1   a rebuild writes the gate at N = 1 under a steered N                             [5]
     steady1    a reconcile rebuilds a chain whose gate is steered                               [7]
     refusecache  a refused iptables gate is asked again every pass                              [7]
     timeoutno  an iptables timeout holds the gate off for an hour                               [7]
     staleseen  build_snapshot leaves an earlier snapshot's gate reads for the steer             [7]
     cumscale   sample_inet multiplies the cumulative value instead of the delta                 [6]
     gatebytes  read_inet_bytes counts the gate's bytes as traffic                               [6]
     flatpre    every rule stays in prerouting (a subnet loop in a base chain again)             [8] [9]
     headless   a subnet left out of the head set (its Blocks and Exits skipped, no error)        [8] [9]
     nogoto     a subnet's goto left out (the same, by another road)                              [8] [9]
     rowjump    a row's jump in prerouting, ahead of its subnet's earlier rules                   [9]
     gotodrift  the drift gate forgets the gotos (one lost from outside stays lost)               [8]
     emptydrift the drift gate forgets the subnets' chains (one emptied from outside stays empty) [8]
     bkreap     the reaper forgets `c_bk` (it is deleted under the rules that count into it)      [8]
     bklate     `c_bk` is not made in the batch (a fresh table's first batch is refused)          [8]
     fwdloop    the SNI reset goes back to one rule a subnet                                       [11]
     v6loop     the IPv6 drops go back to two rules an interface                                  [11]
     v6empty    the IPv6 set is written with no IPv6 interface (`{ }`)                            [11]
     rstempty   the SNI reset's set is written with no IPv4 subnet (`{ }`)                        [11]
     fwdcount   the drift gate forgets forward's rule count (an older layout, a lost rule, stay)  [11]
     fwdwords   …counts the words `drop`/`reject` again (an interface `wg-drop`: a rebuild a pass) [11]
     nov6ret    swg_mech without its IPv6 return (an IPv6 packet reads every rule)              [11]
     v6pre      the dispatch without its IPv6 return (an IPv6 packet reads every goto)          [12]
     v6drift    the drift gate forgets the IPv6 return (DP2a's layout, or a lost one, stays)    [12]
     mechhead   a subnet left out of swg_mech's head set                                          [11]
     dohhead    a subnet left out of swg_doh's head set                                           [11]
     dohfib     swg_doh's route lookup ahead of the port test again                               [11]
"""
import atexit, importlib.machinery, importlib.util, ipaddress, os, re, shutil, subprocess, sys, tempfile
os.environ["SWG_NFT_CLI_ONLY"] = "1"   # the kernel is this test's model, read through run(): nftables via the CLI only

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
sys.path.insert(0, HERE)
from nft_guarded_model import NftError, SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
SECTION = [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


PLANTS = {
    "ungated": ("[1]", '                bat.add("add", "rule", "inet", SMART_NFT_TABLE, "catcount", *_nft_gate_args(_STEER.get("n", 1)))', "                pass"),
    "subloop": ("[2]", '            S = "{ " + ", ".join(subnets) + " }"                # collapsed: one interval per range (nft would merge an overlap; the model refuses one)\n'
                       '            for c in count_cats:                                # no `return` → a byte counts in EVERY category it matches',
                '            for S, c in [(S, c) for S in subnets for c in count_cats]:'),
    "emptyset": ("[3]", "        catw = [subnets, count_cats] if subnets and count_cats else []", "        catw = [subnets, count_cats] if count_cats else []"),
    "anygate": ("[5]", "    for chain, (tbl, tag) in _IPT_GATE.items():\n        if seen.get(chain, n) != n:",
                "    for chain, (tbl, tag) in _IPT_GATE.items():\n        if seen.get(chain) != n:"),
    "nobase": ("[5]", '    if prev is not None and now > pt and (prev.get("g") or 1) == g:', "    if prev is not None and now > pt:"),
    "nobasecat": ("[5]", "    if prev and now > pt and pg == (ncc, nca):", "    if prev and now > pt:"),
    "noseed": ("[5]", '        _STEER["n"] = max(seen.values(), default=1)', '        _STEER["n"] = 1'),
    "rebuild1": ("[5]", '"catcount", *_nft_gate_args(_STEER.get("n", 1)))', '"catcount", *_nft_gate_args(1))'),
    "steady1": ("[7]", "    if same and gates == 1 and _ipt_gate_n(text):", "    if same and gates == 1 and _ipt_gate_n(text) == 1:"),
    "refusecache": ("[7]", "    if t is not None and time.monotonic() - t < 3600:\n        return", "    if False:\n        return"),
    "timeoutno": ("[7]", "    if r.returncode == 124:                         # a timeout is no answer", "    if False:                         # a timeout is no answer"),
    "staleseen": ("[7]", "    _GATE_SEEN.clear()                          # only what THIS snapshot", "    pass                          # only what THIS snapshot"),
    "cumscale": ("[6]", '        _INET["rate"] = {"up": max(0.0, (cur["up"] - prev["up"]) * k),',
                 '        _INET["rate"] = {"up": max(0.0, (cur["up"] * (cur.get("g") or 1) - prev["up"]) / dt),'),
    "gatebytes": ("[6]", '        if c.group(2).startswith("__"):               # the sampling gate (D1): its bytes are the packets it skipped\n'
                         '            continue\n', ""),
    "flatpre": ("[8] [9]", 'disp[_s] if _s else "prerouting", *a)', '"prerouting", *a)'),
    "headless": ("[8] [9]", '"{ " + ", ".join(_hs) + " }", "return")', '"{ " + ", ".join(_hs[1:] or _hs) + " }", "return")'),
    "nogoto": ("[8] [9]", '                for S in subnets:\n                    bat.add("add", "rule", "inet", SMART_NFT_TABLE, "prerouting", "ip", "saddr", S, "goto", disp[S])',
               '                for S in subnets[1:]:\n                    bat.add("add", "rule", "inet", SMART_NFT_TABLE, "prerouting", "ip", "saddr", S, "goto", disp[S])'),
    "rowjump": ("[9]", 'bat.add("add", "rule", "inet", SMART_NFT_TABLE, disp[S],   # first match holds.',
                'bat.add("add", "rule", "inet", SMART_NFT_TABLE, "prerouting",   # first match holds.'),
    "gotodrift": ("[8]", 'set(re.findall(r"\\bgoto (pa\\d+)", _pre)) == want_disp and ', ''),
    "emptydrift": ("[8]", ' and all(_cbody(c).strip() for c in sorted(_exp))', ''),
    "bkreap": ("[8]", ' | ({"c_bk"} if bk else set())', ''),
    "bklate": ("[8]", '            bat.add("add", "counter", "inet", SMART_NFT_TABLE, "c_bk")', '            pass'),
    "fwdloop": ("[11]", '                if _rst_s:                                  # newly-learned dst with reset_mark → RST it so the client reconnects.\n'
                        '                    bat.add("add", "rule", "inet", SMART_NFT_TABLE, "forward", "ip", "saddr", "{ " + ", ".join(_rst_s) + " }",   # ONE rule,',
                '                for _S in _rst_s:\n                    bat.add("add", "rule", "inet", SMART_NFT_TABLE, "forward", "ip", "saddr", _S,'),
    "v6loop": ("[11]", '            if v6f:                                         # one rule a direction, every interface in its set (D2) — never `{ }`\n'
                       '                _v6s = "{ " + ", ".join(\'"%s"\' % f for f in v6f) + " }"',
               '            for _v6s in v6f:\n                _v6s = \'"%s"\' % _v6s'),
    "v6empty": ("[11]", '            if v6f:                                         # one rule a direction, every interface in its set (D2) — never `{ }`',
                '            if True:'),
    "rstempty": ("[11]", '                if _rst_s:                                  # newly-learned dst with reset_mark → RST it so the client reconnects.',
                 '                if True:'),
    "fwdcount": ("[11]", '              and ((not blk_rst) or ("%#010x" % SNI_BLOCK_MARK) in _cbody("forward"))\n'
                         '              and sum(1 for _l in _cbody("forward").splitlines() if _l.strip() and not _l.strip().startswith("type ")) == _nfw)',
                 '              and ((not blk_rst) or ("%#010x" % SNI_BLOCK_MARK) in _cbody("forward")))'),
    "fwdwords": ("[11]", '              and sum(1 for _l in _cbody("forward").splitlines() if _l.strip() and not _l.strip().startswith("type ")) == _nfw)',
                 '              and len(re.findall(r"\\b(?:drop|reject)\\b", _cbody("forward"))) == _nfw)'),
    "nov6ret": ("[11]", '        lines.append("    meta nfproto ipv6 return")            # swg_mech: no rule below can match IPv6', '        pass'),
    "v6pre": ("[12]", '                bat.add("add", "rule", "inet", SMART_NFT_TABLE, "prerouting", "meta", "nfproto", "ipv6", "return")',
              '                pass'),
    "v6drift": ("[12]", '    pre_ok = pre_ok and (len(want_disp) <= 1 or "meta nfproto ipv6 return" in _pre)', '    pass'),
    "mechhead": ("[11]", "        _ms = _collapse4(sorted(set(portsets) | set(meters)))", "        _ms = _collapse4(sorted(set(portsets) | set(meters))[1:])"),
    "dohhead": ("[11]", "        _ds = _collapse4(want_src)", "        _ds = _collapse4(want_src[1:])"),
    "dohfib": ("[11]", '            lines.append("    ip saddr " + S + " " + _new + "udp dport 853 " + _nl + _rec + _rej_u)',
               '            lines.append("    ip saddr " + S + " " + _nl + _new + "udp dport 853 " + _rec + _rej_u)'),
}
TMP = tempfile.mkdtemp(prefix="dp-budget-")
atexit.register(shutil.rmtree, TMP, True)          # every exit, a plant's copy too
path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _sec, old, new = PLANTS[PLANT]
    src = open(NODED, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    path = os.path.join(TMP, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
os.environ["SWG_NODED_STATE"] = TMP
_l = importlib.machinery.SourceFileLoader("swgnoded_budget", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_budget", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = os.path.join(TMP, "geo")
T = N.SMART_NFT_TABLE
CP = subprocess.CompletedProcess


def fleet(ns, nc):
    """ns client subnets, nc categories each routed somewhere: the node's plan."""
    subs = ["10.%d.0.0/24" % (8 + i) for i in range(ns)]
    cats = ["custom_c%d" % j for j in range(nc)]
    ents = [{"subnet": s, "category": c, "action": "exit", "via_iface": "swg_h", "table": 7001} for s in subs for c in cats]
    ents += [{"subnet": s, "category": "all", "action": "direct"} for s in subs]
    return subs, cats, ents


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    K = SmartKernel()
    N.run = K
    N._NUMGEN["ok"] = None
    return K


def npass(K, ents, cats, **kw):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    try:
        N._ensure_smart_nft([dict(e) for e in ents], cats, res, pin=False, queue=False, **kw)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    return res


def build(ns, nc, fill=True, **kw):
    """Two passes: the first makes the sets, a fill between them (what _smart_geo_refresh does), the second counts them."""
    K = fresh()
    subs, cats, ents = fleet(ns, nc)
    r = [npass(K, ents, cats, **kw)]
    if fill:
        for j, c in enumerate(cats):
            K.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
    r.append(npass(K, ents, cats, **kw))
    return K, subs, cats, ents, r


def rules(K, chain):
    return [r["text"] for r in ((K.m.tables.get(T) or {}).get("chains", {}).get(chain) or {}).get("rules", [])]


def walked(K, src, dst, rnd=0):
    """Rules a forwarded packet reads in the two counting chains (both hang on the forward hook)."""
    return sum(K.m.chain_walk(T, c, "awg0", src, dst, rnd=rnd)["walked"] for c in ("catcount", "catany"))


# ── [1] shape ───────────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[1]"
print("\n[1] catcount and catany: one subnet set, a gate on top")
Ks, subs_s, cats_s, _, rs = build(2, 3)
check("two passes, no error, nothing refused", not any(x["errors"] for x in rs) and not Ks.refused, (rs, Ks.refused[:2]))
for c in ("catcount", "catany"):
    check("%s opens with the gate at N = 1" % c, rules(Ks, c)[:1] == [" ".join(N._nft_gate_args(1))], rules(Ks, c)[:2])
check("no rule names one subnet alone (`ip saddr 10.x` with no set)",
      not any(re.search(r"ip [sd]addr 10\.\d+\.0\.0/24", t) for c in ("catcount", "catany") for t in rules(Ks, c)),
      [t for t in rules(Ks, "catcount")][:3])
check("catcount: 1 + 2·C rules (C = 3, no queue)", len(rules(Ks, "catcount")) == 1 + 2 * 3, len(rules(Ks, "catcount")))
check("catany: 1 + 2·C + 4 rules", len(rules(Ks, "catany")) == 1 + 2 * 3 + 4, len(rules(Ks, "catany")))
Kb, subs_b, _, _, rb = build(10, 3)
check("five times the subnets: the same number of rules in both chains",
      [len(rules(Kb, c)) for c in ("catcount", "catany")] == [len(rules(Ks, c)) for c in ("catcount", "catany")],
      ([len(rules(Kb, c)) for c in ("catcount", "catany")], [len(rules(Ks, c)) for c in ("catcount", "catany")]))
check("…and their set is every subnet, collapsed", all("{ " + ", ".join(N._collapse4(subs_b)) + " }" in t
                                                     for t in rules(Kb, "catcount")[1:]), rules(Kb, "catcount")[1:2])

# ── [2] the walk ────────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[2]"
print("\n[2] rules a packet reads")
pk = {"client→cat": ("10.9.0.5", "198.51.1.7"), "reply": ("198.51.1.7", "10.9.0.5"), "transit": ("192.0.2.1", "203.0.113.9"),
      "client→uncat": ("10.9.0.5", "203.0.113.9")}
for k, (s, d) in pk.items():
    ws, wb = walked(Ks, s, d), walked(Kb, s, d)
    check("%s: the same rules with 2 subnets and with 10 (%d)" % (k, ws), ws == wb, (ws, wb))
for k, (s, d) in pk.items():
    for K_, n in ((Ks, 2), (Kb, 10)):
        for c in ("catcount", "catany"):                       # the gate at a high N, a packet it skips: one rule, whatever the fleet
            K_.m.tables[T]["chains"][c]["rules"][0]["ops"][0] = ("numgen", 256)
        w = walked(K_, s, d, rnd=1)
        check("%s, %d subnets, skipped by the gate at N = 256: 1 rule a chain" % (k, n), w == 2, w)
        for c in ("catcount", "catany"):
            K_.m.tables[T]["chains"][c]["rules"][0]["ops"][0] = ("numgen", 1)
cnt = lambda K_, n: K_.m.tables[T]["counters"].get(n, 0)
b0 = cnt(Kb, "c_custom_c1_up")
for s in ("10.8.0.5", "10.17.0.5"):                            # the first and the last subnet
    Kb.m.chain_walk(T, "catcount", "awg0", s, "198.51.1.7")
check("a sampled packet from every subnet counts in its category", cnt(Kb, "c_custom_c1_up") == b0 + 2, cnt(Kb, "c_custom_c1_up") - b0)
u0, d0 = cnt(Kb, "c_uncat_up"), cnt(Kb, "c_uncat_dn")
Kb.m.chain_walk(T, "catany", "awg0", "10.17.0.5", "10.8.0.9")
check("client to client, no category: counted once, as up", (cnt(Kb, "c_uncat_up") - u0, cnt(Kb, "c_uncat_dn") - d0) == (1, 0),
      (cnt(Kb, "c_uncat_up") - u0, cnt(Kb, "c_uncat_dn") - d0))

# ── [3] no empty set; a second pass ─────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[3]"
print("\n[3] never `{ }`; a pass over its own render")
K3 = fresh()
_, cats3, _ = fleet(0, 2)
arr = {"subnets": ["10.28.0.0/24"], "legs": ["swg_n"],
       "entries": [{"category": c, "action": "exit", "via_iface": "swg_h", "table": 7001} for c in cats3]}
r3 = [npass(K3, [], cats3, arrivals=arr) for _ in range(2)]
for j, c in enumerate(cats3):
    if N._smart_setname(c) in K3.m.tables.get(T, {}).get("sets", {}):
        K3.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
r3.append(npass(K3, [], cats3, arrivals=arr))
EMPTY = re.compile(r"\{\s*\}")                               # `"{ " + "" + " }"` is `{  }`: the empty set as the code would write it
check("an arrivals-only node: no error, nothing refused, no `{ }` anywhere",
      not any(x["errors"] for x in r3) and not K3.refused and not any(EMPTY.search(s) for s in K3.scripts), (r3, K3.refused[:2]))
check("…and no counting chain (nothing local to count)", not rules(K3, "catcount"), rules(K3, "catcount")[:2])
# A plan whose only subnet is IPv6 cannot run in the model (it does not route IPv6), so its half is asked directly: the set
# is the IPv4 collapse, and an empty one writes no counting chain (the arrivals-only node above shows that half).
check("a plan whose only subnet is not IPv4: its set is empty, so no chain is written around it",
      N._collapse4(["fd00:8::/64"]) == [] and N._collapse4(["fd00:8::/64", "10.8.0.0/24"]) == ["10.8.0.0/24"],
      N._collapse4(["fd00:8::/64"]))
Kp, _, cats_p, ents_p, _ = build(4, 3)
n0 = len(Kp.scripts)
rp = npass(Kp, ents_p, cats_p)
check("a third pass over its own render rebuilds nothing", rp["changed"] == 0 and len(Kp.scripts) == n0 and not rp["errors"],
      (rp, Kp.scripts[n0:][:1]))

# ── [4] numgen refused ──────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[4]"
print("\n[4] a kernel or nft without numgen")
K4 = fresh()
_m4 = K4.m._rule


def _no_numgen(text):
    if "numgen" in text:                                       # as a kernel without nft_numgen answers
        raise NftError("Could not process rule: No such file or directory")
    return _m4(text)


K4.m._rule = _no_numgen
PROBES = []
N.run = lambda a, input_text=None, **kw: (PROBES.append(1) if "swg_probe" in (input_text or "") else None) or K4(a, input_text=input_text, **kw)
_, cats4, ents4 = fleet(3, 2)
r4 = [npass(K4, ents4, cats4)]
for j, c in enumerate(cats4):
    K4.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
r4.append(npass(K4, ents4, cats4))
os.unlink(os.path.join(N.GEO_DIR, ".catcount-sig"))               # a third pass that rebuilds the chains asks again only if it forgot
r4.append(npass(K4, ents4, cats4))
check("asked once over three passes; no gate; the chains built and nothing in the smart batch refused",
      len(PROBES) == 1 and N._NUMGEN["ok"] is False and rules(K4, "catcount")
      and not any("numgen" in t for t in rules(K4, "catcount") + rules(K4, "catany"))
      and not any(x["errors"] for x in r4), (len(PROBES), N._NUMGEN, r4, rules(K4, "catcount")[:1]))
_n4 = len(PROBES)
N._NUMGEN["ok"] = None
N.run = lambda a, input_text=None, **kw: (CP(a, 124, "", "") if "swg_probe" in (input_text or "") else K4(a, input_text=input_text, **kw))
check("a probe that times out is no answer: asked again on the next pass", N._numgen_ok() is False and N._NUMGEN["ok"] is None, N._NUMGEN)
N.run = K4
sig_off = open(os.path.join(N.GEO_DIR, ".catcount-sig")).read()
K4.m._rule = _m4
N._NUMGEN["ok"] = None
npass(K4, ents4, cats4)
check("…a later process that can take it rebuilds with the gate (the sig tells them apart)",
      rules(K4, "catcount")[:1] == [" ".join(N._nft_gate_args(1))] and open(os.path.join(N.GEO_DIR, ".catcount-sig")).read() != sig_off,
      rules(K4, "catcount")[:1])

# ── [5] the steer ───────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[5]"
print("\n[5] steering N")
_fw = N._forwarded_packets()
check("this box's forwarded packets read from /proc/net/snmp (ForwDatagrams)", isinstance(_fw, int) and _fw >= 0, _fw)
NOW = [1000.0]
N.time = type("T", (), {"time": staticmethod(lambda: NOW[0]), "monotonic": staticmethod(lambda: NOW[0]),
                        "sleep": staticmethod(lambda s: None)})
PK = [0]
N._forwarded_packets = lambda: PK[0]
IPT = {"SWG_INET": None, "SWG_CATK": None}   # chain text as `-S -v` prints it, None = no chain
IPTW = []


def ipt_chain(name, gate_n, extra=True):
    p = "%.11f" % (1 - 1.0 / gate_n) if gate_n else None
    tag = "swg-inet" if name == "SWG_INET" else "swg-catk"
    ln = ["-N " + name]
    if p:
        ln.append('-A %s -m statistic --mode random --probability %s -m comment --comment "%s-up:__gate" -c 900 90000 -j RETURN' % (name, p, tag))
    if extra:
        ln.append('-A %s -i awg2 -o eth0 -m comment --comment "%s-up:awg2" -c 10 1000' % (name, tag))
        ln.append('-A %s -i eth0 -o awg2 -m comment --comment "%s-dn:awg2" -c 20 2000' % (name, tag))
    return "\n".join(ln) + "\n"


Kn, _, cats5, ents5, _ = build(3, 2)
_nft = Kn


def run5(args, input_text=None, timeout=20, env=None):
    a = [str(x) for x in args]
    if a[:1] == ["iptables"]:
        ch = a[a.index("-S") + 1] if "-S" in a else (a[a.index("-R") + 1] if "-R" in a else "")
        if "-R" in a:
            IPTW.append(a)
            n = int(round(1 / (1 - float(a[a.index("--probability") + 1]))))
            IPT[ch] = re.sub(r"--probability \S+", "--probability %.11f" % (1 - 1.0 / n), IPT[ch], count=1)
            return CP(a, 0, "", "")
        if "-S" in a:
            return CP(a, 0 if IPT.get(ch) else 1, IPT.get(ch) or "", "")
        return CP(a, 0, "", "")
    return _nft(args, input_text=input_text, timeout=timeout)


N.run = run5
N._INET.update(t=0.0, cum=None, rate={"up": 0.0, "down": 0.0}, drate={})
N._CATK.update(t=0.0, cum=None, rate={}, on=True); N._CATK.pop("g", None)
N._CATS.update(t=0.0, cum={}, rate={}, g=None)
N._STEER.clear(); N._GATE_SEEN.clear()
IPT["SWG_INET"], IPT["SWG_CATK"] = ipt_chain("SWG_INET", 1), ipt_chain("SWG_CATK", None)   # SWG_CATK: a chain with no gate
CFG = {"interfaces": {"awg2": {}}}


def sample(pps):
    """One snapshot's samplers and steer, 5 s later, at `pps` forwarded packets a second."""
    N._LOOP["n"] += 1
    NOW[0] += 5
    PK[0] += int(pps * 5)
    N.sample_inet(CFG, NOW[0]); N.sample_cats(); N.sample_catk()
    N._stats_steer()
    return N._STEER.get("n", 1)


gates = lambda: [N._nft_gate(Kn.m.render(T), c)[0] for c in ("catcount", "catany")]
heads = lambda: [Kn.handles(T, c)[0] for c in ("catcount", "catany")]
sample(0)
n1 = sample(500)
check("below 1000 packets/s: N = 1, nothing written", n1 == 1 and not IPTW and gates() == [1, 1], (n1, IPTW, gates()))
h0, len0 = heads(), [len(rules(Kn, c)) for c in ("catcount", "catany")]
n2 = sample(64000)
check("64,000 packets/s: raised at once to 256", n2 == 256, n2)
check("…the nft gates replaced in place (the same handle, the same rules, first rule)", gates() == [256, 256] and heads() == h0
      and [len(rules(Kn, c)) for c in ("catcount", "catany")] == len0
      and all(rules(Kn, c)[0] == "numgen random mod 256 != 0 return" for c in ("catcount", "catany")), (gates(), h0, heads()))
check("…SWG_INET's gate by `-R SWG_INET 1`", any(w[w.index("-R") + 1:w.index("-R") + 3] == ["SWG_INET", "1"] for w in IPTW)
      and N._ipt_gate_n(IPT["SWG_INET"]) == 256, (IPTW, IPT["SWG_INET"][:200]))
check("…and SWG_CATK, whose rule 1 is a counting rule, is never written", not any("SWG_CATK" in w for w in IPTW)
      and "__gate" not in IPT["SWG_CATK"], IPTW)
w0 = len(IPTW)
lows = [sample(1500) for _ in range(11)]
check("11 samples at a quarter or less: still 256", set(lows) == {256} and len(IPTW) == w0, (lows, len(IPTW) - w0))
check("…the 12th lowers it (to 8 at 1,500 packets/s)", sample(1500) == 8 and gates() == [8, 8], (N._STEER, gates()))
mid = [sample(1500 * 3) for _ in range(20)]                    # 4,500/s wants 32 > 8: raised at once
check("a rise between lowers is taken at once, and a steady load does not move it", mid[0] == 32 and set(mid) == {32}, mid[:3])
_bad = [True]


def run5_refuse(args, input_text=None, timeout=20, env=None):
    if _bad[0] and [str(x) for x in args][:2] == ["nft", "-f"]:
        return CP(args, 1, "", "Error: refused")
    return run5(args, input_text=input_text, timeout=timeout)


N.run = run5_refuse
sample(64000)
check("a refused nft step leaves the gates where they were", gates() == [32, 32], gates())
_bad[0] = False
sample(64000)
check("…and the next sample retries it by itself", gates() == [256, 256], gates())
N.run = run5
N._STEER.clear()                                               # a restart: the gates the last process left stand at 256
w0 = len(IPTW)
rs = [sample(20000) for _ in range(3)]                         # 20,000/s wants 128: kept at 256 (not a quarter), as before it
check("a restart steers from the gates it finds: 128 wanted under 256 moves nothing", rs == [256] * 3 and gates() == [256, 256]
      and len(IPTW) == w0, (rs, gates(), IPTW[w0:]))
os.unlink(os.path.join(N.GEO_DIR, ".catcount-sig"))            # a rebuild under a steered N (the 30-minute reverify does this)
rb5 = npass(Kn, ents5, cats5)
check("a rebuild writes the gate at the steered N, not at 1 (no step for the readers)", gates() == [256, 256] and not rb5["errors"],
      (gates(), rb5))

# ── [6] the readers ─────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[6]"
print("\n[6] the readers: delta × N")
sample(64000)
IPT["SWG_INET"] = IPT["SWG_INET"].replace("-c 10 1000", "-c 30 6000")     # +5,000 bytes up in 5 s, sampled 1 in 256
N._LOOP["n"] += 1
NOW[0] += 5
r = N.sample_inet(CFG, NOW[0])
check("the internet lane: 5,000 sampled bytes in 5 s at N = 256 read 256,000 B/s", abs(r["up"] - 256000.0) < 1e-6, r)
check("…the cumulative value kept as counted (the next delta subtracts it)", N._INET["cum"]["up"] == 6000, N._INET["cum"])
got = N.read_inet_bytes()
check("the gate's own bytes are no traffic (90,000 on it)", got["up"] == 6000 and got["down"] == 2000, got)
IPT["SWG_CATK"] = ipt_chain("SWG_CATK", 256)
N._CATK.update(cum=None)
NOW[0] += 5
N.sample_catk()
IPT["SWG_CATK"] = IPT["SWG_CATK"].replace("-c 10 1000", "-c 11 1100")
NOW[0] += 5
rk = N.sample_catk()
check("Kernel SNI's categories: 100 sampled bytes in 5 s at N = 256 read 5,120 B/s, and no `__gate` category",
      abs(rk.get("awg2", {}).get("up", 0) - 5120.0) < 1e-6 and not any(k.startswith("__") for k in rk), rk)
N._LOOP["n"] += 1
NOW[0] += 5
N.sample_cats()
Kn.m.tables[T]["counters"]["c_custom_c0_up"] = Kn.m.tables[T]["counters"].get("c_custom_c0_up", 0) + 10   # +600 bytes (60 a packet)
N._LOOP["n"] += 1
NOW[0] += 5
rc = N.sample_cats()
check("Top destinations: 600 sampled bytes in 5 s at N = 256 read 30,720 B/s", abs(rc.get("custom_c0", {}).get("up", 0) - 30720.0) < 1e-6, rc)
rc["custom_c0"]["up"] += 1                                     # build_snapshot adds Kernel SNI's share into these dicts
check("…and what it hands out is a copy: a caller adding into it changes nothing it holds",
      abs(N._CATS["rate"]["custom_c0"]["up"] - 30720.0) < 1e-6, N._CATS["rate"].get("custom_c0"))

SECTION[0] = "[5]"                                             # the step's baseline is the readers' own: their plants are [5]'s
lows = [sample(100) for _ in range(13)]
check("quiet again: back to N = 1 after 12 samples", lows[-1] == 1 and N._ipt_gate_n(IPT["SWG_INET"]) == 1, (lows, IPT["SWG_INET"][:160]))
sample(100); sample(100)
N._LOOP["n"] += 1                                              # one snapshot by hand: the readers, then bytes counted EXACTLY
NOW[0] += 5                                                    # between their read and the step, then the step to 256
PK[0] += 64000 * 5
N.sample_inet(CFG, NOW[0]); N.sample_cats(); N.sample_catk()
held, heldc = N._INET["rate"]["up"], dict(N._CATS["rate"].get("custom_c0") or {})
IPT["SWG_INET"] = re.sub(r'(swg-inet-up:awg2" -c \d+ )(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + 20000), IPT["SWG_INET"])
Kn.m.tables[T]["counters"]["c_custom_c0_up"] += 20000
N._stats_steer()
check("(the step happened)", N._STEER["n"] == 256 and N._ipt_gate_n(IPT["SWG_INET"]) == 256 and gates() == [256, 256], N._STEER)
N._LOOP["n"] += 1
NOW[0] += 5
r2 = N.sample_inet(CFG, NOW[0])
check("the internet lane after a step: a baseline, its rate holds — no ×256 of bytes counted exactly (1,024,000 B/s)",
      r2["up"] == held, (r2, held))
rc2 = N.sample_cats()
check("Top destinations after a step: a baseline, its rate holds", rc2.get("custom_c0") == heldc, (rc2.get("custom_c0"), heldc))

# ── [7] iptables reconcile ──────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[7]"
print("\n[7] SWG_INET / SWG_CATK reconcile and the gate")
CH = {"SWG_INET": [], "SWG_CATK": [], "calls": [], "nostat": False}


def run7(args, input_text=None, timeout=20, env=None):
    a = [str(x) for x in args]
    CH["calls"].append(a)
    if a[:1] != ["iptables"]:
        return CP(a, 0, "", "")
    if "-S" in a:
        ch = a[a.index("-S") + 1]
        if ch == "FORWARD":
            return CP(a, 0, "-A FORWARD -j SWG_INET\n-A FORWARD -j SWG_CATK\n", "")
        return CP(a, 0, "-N %s\n" % ch + "".join("-A %s " % ch + " ".join(('"%s"' % x) if i and r[i - 1] == "--comment" else x
                                                                          for i, x in enumerate(r)) + "\n" for r in CH[ch]), "")
    if "-nL" in a:
        return CP(a, 0 if "mangle" in a else 1, "", "")
    if CH["nostat"] and "statistic" in a:
        return CP(a, 1, "", "iptables: No chain/target/match by that name.")
    if "-F" in a:
        CH[a[a.index("-F") + 1]] = []
    elif "-A" in a:
        CH[a[a.index("-A") + 1]].append(a[a.index("-A") + 2:])
    elif "-I" in a and a[a.index("-I") + 1] in ("SWG_INET", "SWG_CATK"):
        CH[a[a.index("-I") + 1]].insert(int(a[a.index("-I") + 2]) - 1, a[a.index("-I") + 3:])
    return CP(a, 0, "", "")


def gate7(n):
    return ["-m", "statistic", "--mode", "random", "--probability", "%.11f" % (1 - 1.0 / n)]


N.run = run7
N._detect_wan = lambda: "eth0"
N._STEER["n"] = 1
writes = lambda: [c for c in CH["calls"] if any(x in c for x in ("-F", "-I", "-A", "-R"))]
pairs = [["-i", "awg2", "-o", "eth0", "-m", "comment", "--comment", "swg-inet-up:awg2"],
         ["-i", "eth0", "-o", "awg2", "-m", "comment", "--comment", "swg-inet-dn:awg2"]]
CH["SWG_INET"] = [list(p) for p in pairs]                     # as 1.8.11 left it
N.reconcile_inet_chain(CFG)
check("SWG_INET from 1.8.11: the gate inserted on top, the pairs untouched (no flush)",
      not any("-F" in c for c in CH["calls"]) and CH["SWG_INET"][1:] == pairs and "swg-inet-up:__gate" in CH["SWG_INET"][0], CH["SWG_INET"][:1])
CH["calls"].clear()
N.reconcile_inet_chain(CFG)
check("…and the next pass changes nothing", not writes(), writes())
g256 = gate7(256) + ["-m", "comment", "--comment", "swg-inet-up:__gate", "-j", "RETURN"]
CH["SWG_INET"] = [list(g256)] + [list(p) for p in pairs]       # the steer moved it to 256
CH["calls"].clear()
N.reconcile_inet_chain(CFG)
check("a steered gate (N = 256) stands: no flush, the counts kept", not writes() and CH["SWG_INET"][0] == g256, writes())
CH["SWG_INET"] = [list(p) for p in pairs] + [list(g256)]       # the gate astray: below the pairs
N._STEER["n"] = 256
N.reconcile_inet_chain(CFG)
check("a gate that is not the first rule: rebuilt, the gate first at the steered N (256)",
      "swg-inet-up:__gate" in CH["SWG_INET"][0] and "0.99609375000" in CH["SWG_INET"][0] and CH["SWG_INET"][1:] == pairs, CH["SWG_INET"])
CH["SWG_INET"] = [CH["SWG_INET"][0], CH["SWG_INET"][0]] + [list(p) for p in pairs]
N.reconcile_inet_chain(CFG)
check("two gates: rebuilt with one", sum("swg-inet-up:__gate" in r for r in CH["SWG_INET"]) == 1, CH["SWG_INET"])
N.reconcile_inet_chain({"interfaces": {"awg2": {}, "wg1": {}}})
check("a new interface: rebuilt, the gate first", "swg-inet-up:__gate" in CH["SWG_INET"][0] and len(CH["SWG_INET"]) == 5, CH["SWG_INET"])
N._STEER["n"] = 1
sn = N._xts_setname("c1")
CH["SWG_CATK"] = [["-m", "set", "--match-set", sn, "dst", "-m", "comment", "--comment", "swg-catk-up:c1"],
                  ["-m", "set", "--match-set", sn, "src", "-m", "comment", "--comment", "swg-catk-dn:c1"]]
kp = [list(r) for r in CH["SWG_CATK"]]
CH["calls"].clear()
N.reconcile_catk_chain(["c1"])
check("SWG_CATK from 1.8.11: the gate inserted on top, the rules untouched (no flush)",
      not any("-F" in c for c in CH["calls"]) and CH["SWG_CATK"][1:] == kp and "swg-catk-up:__gate" in CH["SWG_CATK"][0], CH["SWG_CATK"][:1])
CH["SWG_CATK"][0] = gate7(512) + ["-m", "comment", "--comment", "swg-catk-up:__gate", "-j", "RETURN"]
CH["calls"].clear()
N.reconcile_catk_chain(["c1"])
check("…a steered one (N = 512) stands", not writes(), writes())
CH["SWG_CATK"] = kp[::-1] + [CH["SWG_CATK"][0]]
N.reconcile_catk_chain(["c1"])
check("…one astray is rebuilt, the gate first", "swg-catk-up:__gate" in CH["SWG_CATK"][0] and len(CH["SWG_CATK"]) == 3, CH["SWG_CATK"])
CH["nostat"] = True                                            # a kernel without xt_statistic
CH["SWG_INET"] = [list(p) for p in pairs]
CH["calls"].clear()
for _ in range(3):
    N.reconcile_inet_chain(CFG)
    NOW[0] += 60
tries = [c for c in CH["calls"] if "statistic" in c]
check("no xt_statistic: the gate asked once, not on every pass; the pairs count on, exact", len(tries) == 1 and CH["SWG_INET"] == pairs,
      (len(tries), CH["SWG_INET"]))
NOW[0] += 3600
CH["calls"].clear()
N.reconcile_inet_chain(CFG)
check("…and asked again an hour later", len([c for c in CH["calls"] if "statistic" in c]) == 1, CH["calls"][-2:])
CH["nostat"] = False
N._IPT_GATE_NO.clear()
_r7 = N.run
N.run = lambda a, input_text=None, **kw: CP(a, 124, "", "") if "statistic" in [str(x) for x in a] else _r7(a, input_text=input_text, **kw)
CH["SWG_INET"] = [list(p) for p in pairs]
N.reconcile_inet_chain(CFG)
check("an iptables that times out is no answer: not held off for an hour", "SWG_INET" not in N._IPT_GATE_NO, N._IPT_GATE_NO)
N.run = _r7
_bs = open(path, encoding="utf-8").read()
_bs = _bs[_bs.index("\ndef build_snapshot("):]
check("the steer acts only on this snapshot's reads: build_snapshot clears them before the first sampler",
      -1 < _bs.find("_GATE_SEEN.clear()") < _bs.find("sample_inet(node_cfg, now)"), _bs.find("_GATE_SEEN.clear()"))

# ── [8] prerouting: dispatch by source (DP2) ────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[8]"
print("\n[8] prerouting: a packet reads only its own subnet's rules")
ENG = (("kernel / Force-DNS", False, False), ("Hybrid SNI", True, True), ("Kernel SNI", True, False))


def plan8(ns, nc, first=0):
    """ns subnets, the same list on each: an Exit per category but the last, a per-person row (a Direct and a Block), a
    block list's Block (it counts into `c_bk`), an Exit for everything else. Each row's selection is bound to its own subnet,
    as the panel binds it (who_plan_for_node)."""
    subs = ["10.%d.0.0/24" % (8 + first + i) for i in range(ns)]
    cats = ["custom_c%d" % j for j in range(nc - 1)] + ["blku_t"]
    ents, srcs = [], {}
    for i, s in enumerate(subs):
        wid = "%012x" % (0xa00000000000 + first + i)
        srcs[wid] = [["awg0", s.replace("0/24", "5/32")]]
        ents += [{"subnet": s, "category": c, "action": "exit", "via_iface": "swg_h", "table": 7001} for c in cats[:-1]]
        ents += [{"subnet": s, "category": cats[0], "action": "direct", "src": wid},
                 {"subnet": s, "category": cats[1], "action": "block", "src": wid},
                 {"subnet": s, "category": cats[-1], "action": "block"},
                 {"subnet": s, "category": "all", "action": "exit", "via_iface": "swg_h", "table": 7002}]
    return subs, cats, ents, srcs


def mpass(M, K, ents, cats, pin, queue, **kw):
    """One routing pass of module M on kernel K (the candidate, or the node before dispatch)."""
    M.run = K
    M._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    n0 = len(K.scripts)
    try:
        M._ensure_smart_nft([dict(e) for e in ents], cats, res, pin=pin, queue=queue, reset_mark=(M.SNI_RESET_MARK if pin else 0), **kw)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    res["scripts"] = K.scripts[n0:]
    return res


def build8(M, ns, nc, pin, queue, first=0, geo="geo8"):
    M.GEO_DIR = os.path.join(TMP, geo)
    shutil.rmtree(M.GEO_DIR, ignore_errors=True)
    os.makedirs(M.GEO_DIR)
    open(os.path.join(M.GEO_DIR, ".automerge-migrated"), "w").write("1")
    getattr(M, "_NUMGEN", {})["ok"] = None                   # 1.8.11 (the base) has no numgen probe
    K = SmartKernel()
    subs, cats, ents, srcs = plan8(ns, nc, first)
    r = [mpass(M, K, ents, cats, pin, queue, srcs=srcs)]
    for j, c in enumerate(cats):
        K.load_set(T, M._smart_setname(c), ["198.51.%d.0/24" % j])
    r += [mpass(M, K, ents, cats, pin, queue, srcs=srcs) for _ in range(2)]
    return K, subs, cats, ents, srcs, r


# a reply, the tunnel's own outer packet, transit, and a client's established and first packets — as the walk sees them
PK8 = {"reply": dict(iif="eth0", saddr="198.51.1.7", daddr="10.9.0.5", ct="established", reply=True),
       "outer": dict(iif="eth0", saddr="203.0.113.50", daddr="192.0.2.1", proto="udp", dport=51820, ct="established"),
       "transit": dict(iif="swg_n", saddr="192.0.2.77", daddr="203.0.113.9", ct="established"),
       "client, established": dict(iif="awg0", saddr="10.9.0.6", daddr="198.51.1.7", ct="established"),
       "client, first packet": dict(iif="awg0", saddr="10.9.0.6", daddr="198.51.1.7", ct="new")}
walk8 = lambda K, p: dict({"walked": 0}, **K.m.packet(T, p["iif"], p["saddr"], p["daddr"],     # an empty chain reads no rule
                                                       **{k: v for k, v in p.items() if k not in ("iif", "saddr", "daddr")}))
for label, pin, queue in ENG:
    Ka, subs_a, _, _, _, ra = build8(N, 2, 3, pin, queue)
    Kz, subs_z, _, _, _, rz = build8(N, 10, 3, pin, queue)
    check("%s: three passes, 2 subnets and 10, no error, nothing refused" % label,
          not any(x["errors"] for x in ra + rz) and not Ka.refused and not Kz.refused, ([x["errors"] for x in ra + rz], Ka.refused[:1], Kz.refused[:1]))
    if T not in Kz.m.tables:
        continue
    pre_z = [r["text"] for r in Kz.m.tables[T]["chains"]["prerouting"]["rules"]]
    check("%s: one chain a subnet, pa100000 + its place, and one goto to each" % label,
          {c for c in Kz.m.tables[T]["chains"] if re.fullmatch(r"pa1\d{5}", c)} == {"pa%d" % (100000 + k) for k in range(10)}
          and [t for t in pre_z if " goto " in t] == ["ip saddr %s goto pa%d" % (s, 100000 + k) for k, s in enumerate(sorted(subs_z))],
          pre_z)
    check("%s: no rule in prerouting names one subnet but its goto (every list is in its subnet's chain)" % label,
          not [t for t in pre_z if re.search(r"ip saddr 10\.\d+\.0\.0/24 ", t) and " goto " not in t], pre_z)
    _of = {s: "pa%d" % (100000 + k) for k, s in enumerate(sorted(subs_z))}
    stray = [(c, r["text"]) for c, ch in Kz.m.tables[T]["chains"].items() if c == "prerouting" or not ch["hook"]   # what prerouting
             for r in ch["rules"] for s in subs_z                                                                    # reaches (DP2b: the rest)
             if re.search(r"\bip saddr %s " % re.escape(s), r["text"]) and c != _of[s] and not (c == "prerouting" and " goto " in r["text"])]
    check("%s: every prerouting rule matching a subnet's source, wherever in the rule, sits in that subnet's chain" % label, not stray, stray[:3])
    check("%s: …and the head set is every subnet, collapsed, before the gotos" % label,
          ("ip saddr != { %s } return" % ", ".join(N._collapse4(subs_z))) in pre_z
          and pre_z.index("ip saddr != { %s } return" % ", ".join(N._collapse4(subs_z))) < min(i for i, t in enumerate(pre_z) if " goto " in t), pre_z)
    check("%s: pass 3 over its own render rebuilds nothing (2 subnets and 10)" % label,
          not ra[2]["scripts"] and not rz[2]["scripts"] and ra[2]["changed"] == rz[2]["changed"] == 0, (ra[2], rz[2]))
    for k, p in PK8.items():
        wa, wz = walk8(Ka, p)["walked"], walk8(Kz, p)["walked"]
        if k.startswith("client"):
            check("%s, %s: five times the subnets reads at most the 8 gotos more (%d, %d)" % (label, k, wa, wz), wa <= wz <= wa + 8, (wa, wz))
        else:
            check("%s, %s: the same rules with 2 subnets and with 10 (%d)" % (label, k, wa), wa == wz and wz <= 4, (wa, wz))
    c0 = Kz.m.tables[T]["counters"].get("c_bk", -1)
    v = walk8(Kz, dict(PK8["client, first packet"], daddr="198.51.2.7"))    # to the block list's destination
    N.run, N._LOOP["n"] = Kz, N._LOOP["n"] + 1
    _act = N._block_activity()
    check("%s: a block list's drop counts into `c_bk`, reported as blocked under \"*\"" % label,
          v["verdict"] == "drop" and Kz.m.tables[T]["counters"].get("c_bk") == c0 + 1 == (_act.get("*") or {}).get("blocked"),
          (v, c0, Kz.m.tables[T]["counters"].get("c_bk"), _act))
    w_last = walk8(Kz, dict(PK8["client, established"], saddr="10.17.0.6"))["walked"]
    check("%s: a client of the last subnet reads the head, the gotos and its own list — not the nine others' (%d)" % (label, w_last),
          w_last < 2 * walk8(Kz, PK8["client, established"])["walked"] + 10, w_last)
    def _goto_gone(tb):                                       # → the subnet whose goto went (the last one written); a table
        rl = tb["chains"]["prerouting"]["rules"]              # with none (every batch refused) says so in the checks
        return rl.pop()["text"].split()[2] if rl else "10.8.0.0/24"

    def _chain_gone(tb):                                      # → the subnet whose chain was emptied (pa100001)
        tb["chains"].get("pa100001", {})["rules"] = []
        return next((r["text"].split()[2] for r in tb["chains"]["prerouting"]["rules"] if r["text"].endswith("goto pa100001")), "10.8.0.0/24")
    for what, cut in (("a goto lost from outside", _goto_gone), ("a subnet's chain emptied from outside", _chain_gone)):
        Kd, _, cd, ed, sd, _ = build8(N, 3, 3, pin, queue)
        src = cut(Kd.m.tables[T]).replace(".0/24", ".6")
        lost = walk8(Kd, dict(PK8["client, first packet"], saddr=src, daddr="198.51.2.7"))["verdict"]
        rd = mpass(N, Kd, ed, cd, pin, queue, srcs=sd)
        check("%s: %s is rebuilt at the next routing pass — its block list drops again (%s)" % (label, what, src), lost == "accept"
              and rd["scripts"] and not rd["errors"] and walk8(Kd, dict(PK8["client, first packet"], saddr=src, daddr="198.51.2.7"))["verdict"] == "drop",
              (lost, rd["errors"], rd["scripts"][:1]))

# one subnet, and overlapping ones: one chain, one goto, today's walk
K1, _, _, _, _, r1 = build8(N, 1, 3, False, False)
check("one subnet: one chain (pa100000), reached by one rule, no head", [r["text"] for r in K1.m.tables[T]["chains"]["prerouting"]["rules"]]
      == ["ip saddr { 10.8.0.0/24 } goto pa100000"] and not any(x["errors"] for x in r1), K1.m.tables[T]["chains"]["prerouting"]["rules"])
Ko = fresh()
_, cats_o, ents_o, srcs_o = plan8(2, 3)
ents_o += [dict(e, subnet="10.8.0.0/16") for e in ents_o if e["subnet"] == "10.8.0.0/24" and "src" not in e]   # an adopted leftover
ro = [mpass(N, Ko, ents_o, cats_o, False, False, srcs=srcs_o) for _ in range(2)]
pre_o = [r["text"] for r in Ko.m.tables[T]["chains"]["prerouting"]["rules"]]
check("overlapping subnets share pa100000, every rule in it in the plan's order, one goto",
      not any(x["errors"] for x in ro) and not Ko.refused and [t for t in pre_o if "goto" in t] == ["ip saddr { 10.8.0.0/16, 10.9.0.0/24 } goto pa100000"]
      and not any(re.fullmatch(r"pa1\d{5}", c) and c != "pa100000" for c in Ko.m.tables[T]["chains"]), (pre_o, Ko.refused[:1]))
K3b = fresh()
r3b = [mpass(N, K3b, [], cats3, False, False, arrivals=arr) for _ in range(2)]
check("an arrivals-only node: no dispatch chain, no head, no `{ }`, nothing refused",
      not any(re.fullmatch(r"pa1\d{5}", c) for c in K3b.m.tables[T]["chains"]) and not K3b.refused
      and not any(EMPTY.search(s) for s in K3b.scripts), (sorted(K3b.m.tables[T]["chains"]), K3b.refused[:1]))

# ── [9] the same verdict as the node before dispatch ────────────────────────────────────────────────────────────────────
SECTION[0] = "[9]"
print("\n[9] every packet: the verdict, mark and connection mark of the node before dispatch")
BASE = os.environ.get("SWG_DISPATCH_BASE") or "7fbf2cfc"       # 1.8.11-beta on main (a release commit outlives dev's resets)
_rb = subprocess.run(["git", "-C", ROOT, "show", "%s:swg-noded" % BASE], capture_output=True, text=True)
H = None
if _rb.returncode:
    check("the base node is readable (git show %s)" % BASE, False, _rb.stderr[:200])
else:
    _bp = os.path.join(TMP, "base-noded.py")
    open(_bp, "w", encoding="utf-8").write(_rb.stdout)
    _lb = importlib.machinery.SourceFileLoader("swgnoded_dispatch_base", _bp)
    H = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_dispatch_base", _lb))
    try:
        _lb.exec_module(H)
    except SystemExit:
        pass


def grid(subs, cats):
    """Every source a plan can see (each subnet's chosen device and another, a stranger, a public address) to every
    category's destination and one in none, new and established, TCP 443 and UDP 443 and 53."""
    nets = [ipaddress.ip_network(s, strict=False) for s in subs]       # a wider subnet: one address outside the narrower too
    srcs = [str(n.network_address + k) for n in nets for k in ((5, 6) if n.prefixlen >= 24 else (5, 6, 261))] + ["10.200.0.5", "198.51.0.9"]
    dsts = ["198.51.%d.7" % j for j in range(len(cats))] + ["203.0.113.9"]
    g = [(iif, s, d, pr, pt, ct, False) for s in srcs for d in dsts for (pr, pt) in (("tcp", 443), ("udp", 443), ("udp", 53))
         for ct in ("new", "established") for iif in ("awg0", "awg1")]
    return g + [(iif, "0.0.0.0", "0.0.0.0", pr, pt, ct, True) for (pr, pt) in (("tcp", 443), ("udp", 443), ("udp", 53))   # …and
                for ct in ("new", "established") for iif in ("awg0", "awg1", "eth0")]                                    # IPv6


def verdicts(K, g, ctmark=7001):
    return [(lambda v: (v["verdict"], v["mark"], v["ctmark"]))(K.m.packet(T, iif, s, d, proto=pr, dport=pt, ct=ct, ctmark=ctmark, v6=v6))
            for iif, s, d, pr, pt, ct, v6 in g]


EQ = [("3 subnets, rows, a Block, Exits", plan8(3, 3)),
      ("1 subnet", plan8(1, 4)),
      ("overlapping subnets", (lambda p: (p[0] + ["10.8.0.0/16"], p[1],
                                          p[2] + [dict(e, subnet="10.8.0.0/16") for e in p[2] if e["subnet"] == "10.8.0.0/24" and "src" not in e], p[3]))(plan8(2, 3)))]
for label, pin, queue in ENG if H else ():
    for name, (subs, cats, ents, srcs) in EQ:
        out = []
        for M in (N, H):
            M.GEO_DIR = os.path.join(TMP, "geo9-" + ("c" if M is N else "b"))
            shutil.rmtree(M.GEO_DIR, ignore_errors=True)
            os.makedirs(M.GEO_DIR)
            open(os.path.join(M.GEO_DIR, ".automerge-migrated"), "w").write("1")
            getattr(M, "_NUMGEN", {})["ok"] = None                   # 1.8.11 (the base) has no numgen probe
            K = SmartKernel()
            r = [mpass(M, K, ents, cats, pin, queue, srcs=srcs)]
            for j, c in enumerate(cats):
                K.load_set(T, M._smart_setname(c), ["198.51.%d.0/24" % j])
            r.append(mpass(M, K, ents, cats, pin, queue, srcs=srcs))
            out.append((K, r))
        g = grid(sorted({e["subnet"] for e in ents}), cats)
        vc, vb = verdicts(out[0][0], g), verdicts(out[1][0], g)
        diff = [(g[i], vb[i], vc[i]) for i in range(len(g)) if vc[i] != vb[i]]
        check("%s, %s: %d packets, the same verdict, mark and connection mark as %s" % (label, name, len(g), BASE),
              not diff and not any(x["errors"] for _, rr in out for x in rr) and vc.count(vc[0]) != len(vc), (diff[:3], [x["errors"] for _, rr in out for x in rr]))

# ── [10] transitions, the update and the downgrade, on one kernel ───────────────────────────────────────────────────────
SECTION[0] = "[10]"
print("\n[10] transitions: a subnet with a row leaves, a row leaves, a subnet arrives; the update; the downgrade")
for label, pin, queue in ENG:
    G10 = os.path.join(TMP, "geo10")
    shutil.rmtree(G10, ignore_errors=True)
    os.makedirs(G10)
    open(os.path.join(G10, ".automerge-migrated"), "w").write("1")
    K = SmartKernel()
    steps = []

    def step(M, plan, what):
        M.GEO_DIR = G10
        getattr(M, "_NUMGEN", {})["ok"] = None                   # 1.8.11 (the base) has no numgen probe
        subs, cats, ents, srcs = plan
        r = [mpass(M, K, ents, cats, pin, queue, srcs=srcs)]
        for j, c in enumerate(cats):
            if M._smart_setname(c) in K.m.tables.get(T, {}).get("sets", {}):
                K.load_set(T, M._smart_setname(c), ["198.51.%d.0/24" % j])
        r += [mpass(M, K, ents, cats, pin, queue, srcs=srcs) for _ in range(2)]   # the 2nd builds the counting chains (sets filled)
        ok = not any(x["errors"] for x in r) and not r[2]["scripts"]
        g = grid(subs, cats)
        steps.append((what, ok, [x["errors"] for x in r], verdicts(K, g), g))
        return ok

    p3, prow = plan8(3, 3), plan8(3, 3)
    gone = p3[0][-1]                                                            # the last subnet, with its row, leaves
    p2 = ([s for s in p3[0] if s != gone], p3[1], [e for e in p3[2] if e["subnet"] != gone], p3[3])
    assert any("src" in e for e in p3[2] if e["subnet"] == gone) and gone not in {e["subnet"] for e in p2[2]}
    prow = (prow[0], prow[1], [e for e in prow[2] if not (e["subnet"] == "10.9.0.0/24" and "src" in e)], prow[3])   # one row left
    pnew = plan8(4, 3)                                                          # a subnet arrived
    if H:
        step(H, p3, "the node before dispatch")
        step(N, p3, "the update: its render, rebuilt")
    else:
        step(N, p3, "first render")
    step(N, p2, "a subnet with a row leaves")
    step(N, prow, "a row leaves")
    step(N, pnew, "a subnet arrives")
    pdown = plan8(4, 3)
    pdown = (pdown[0], pdown[1], [e for e in pdown[2] if not (e["subnet"] == "10.11.0.0/24" and "src" in e)], pdown[3])
    if H:
        step(H, pdown, "the downgrade, a row removed in the same window")
    for what, ok, errs, _v, _g in steps:
        check("%s: %s — no batch refused, and the next pass rebuilds nothing" % (label, what), ok and not K.refused, (errs, K.refused[:2]))
    if H:
        tb = K.m.tables[T]
        check("%s: after the downgrade no dispatch chain is left, and no `c_bk`" % label,
              not any(re.fullmatch(r"pa1\d{5}", c) for c in tb["chains"]) and "c_bk" not in tb["counters"], (sorted(tb["chains"]), sorted(tb["counters"])))
        Kb = SmartKernel()                                                      # the same plan, built fresh by the node before
        H.GEO_DIR = os.path.join(TMP, "geo10b")
        shutil.rmtree(H.GEO_DIR, ignore_errors=True)
        os.makedirs(H.GEO_DIR)
        open(os.path.join(H.GEO_DIR, ".automerge-migrated"), "w").write("1")
        for _ in range(3):
            mpass(H, Kb, pdown[2], pdown[1], pin, queue, srcs=pdown[3])
            for j, c in enumerate(pdown[1]):
                if H._smart_setname(c) in Kb.m.tables.get(T, {}).get("sets", {}):
                    Kb.load_set(T, H._smart_setname(c), ["198.51.%d.0/24" % j])
        check("%s: …and the downgraded table decides every packet as one that node built itself" % label,
              steps[-1][3] == verdicts(Kb, steps[-1][4]), next(((steps[-1][4][i], steps[-1][3][i]) for i in range(len(steps[-1][4]))
                                                               if steps[-1][3][i] != verdicts(Kb, steps[-1][4])[i]), None))

# ── [11] DP2b: the forward chain, swg_mech, swg_doh ─────────────────────────────────────────────────────────────────────
SECTION[0] = "[11]"
print("\n[11] DP2b: forward, swg_mech and swg_doh — one rule where there was one a subnet or an interface")
ARR11 = {"subnets": ["10.28.0.0/24"], "legs": ["swg_n"],
         "entries": [{"category": "custom_c0", "action": "exit", "via_iface": "swg_h", "table": 7001}]}
IFS = lambda n: ["awg%d" % i for i in range(n)]


def geo11(M, name):
    M.GEO_DIR = os.path.join(TMP, name)
    shutil.rmtree(M.GEO_DIR, ignore_errors=True)
    os.makedirs(M.GEO_DIR)
    open(os.path.join(M.GEO_DIR, ".automerge-migrated"), "w").write("1")
    getattr(M, "_NUMGEN", {})["ok"] = None                   # 1.8.11 (the base) has no numgen probe


def fwd(K):
    return [r["text"] for r in ((K.m.tables.get(T) or {}).get("chains", {}).get("forward") or {}).get("rules", [])]


def routing11(M, K, plan, nv, pin, queue, arr, passes, ifs=None):
    """`passes` routing passes of M on K with nv IPv6 smart interfaces (or those named `ifs`), a block by name refused (pin)
    and, with `arr`, an arrival; the categories filled after the first pass, as _smart_geo_refresh does."""
    subs, cats, ents, srcs = plan
    kw = dict(srcs=srcs, v6_ifaces=(ifs or IFS(nv)), blk_reject=pin, arrivals=(ARR11 if arr else None))
    r = []
    for i in range(passes):
        r.append(mpass(M, K, ents, cats, pin, queue, **kw))
        if i == 0:
            for j, c in enumerate(cats):
                if M._smart_setname(c) in K.m.tables.get(T, {}).get("sets", {}):
                    K.load_set(T, M._smart_setname(c), ["198.51.%d.0/24" % j])
    return r


def build11(M, plan, nv, pin, queue, arr=True, name="geo11", passes=3, ifs=None):
    geo11(M, name)
    K = SmartKernel()
    return K, routing11(M, K, plan, nv, pin, queue, arr, passes, ifs)


# what forward decides on: a client's packet out, a reply in, transit, IPv6 on no smart interface
FWD_PK = {"a client's packet out": dict(iif="awg0", saddr="10.9.0.6", daddr="198.51.1.7", oif="eth0"),
          "a reply in": dict(iif="eth0", saddr="198.51.1.7", daddr="10.9.0.6", oif="awg0"),
          "transit": dict(iif="swg_n", saddr="192.0.2.77", daddr="203.0.113.9", oif="eth0"),
          "IPv6 on no smart interface": dict(iif="eth0", saddr="0.0.0.0", daddr="0.0.0.0", oif="eth1", v6=True)}
LONE = re.compile(r"\b(?:ip saddr|[io]ifname) (?!\{|@|!= \{|!= @)")      # a subnet or a device named alone, not in a set
for label, pin, queue in ENG:
    Ka, ra = build11(N, plan8(2, 3), 2, pin, queue)
    Kz, rz = build11(N, plan8(10, 3), 12, pin, queue)
    fa, fz = fwd(Ka), fwd(Kz)
    check("%s: three passes, 2 subnets and 2 IPv6 interfaces, 10 and 12: no error, nothing refused" % label,
          not any(x["errors"] for x in ra + rz) and not Ka.refused and not Kz.refused, ([x["errors"] for x in ra + rz], Ka.refused[:1], Kz.refused[:1]))
    check("%s: forward holds the same rules, %d, with 2 subnets and 2 interfaces as with 10 and 12" % (label, len(fz)),
          len(fa) == len(fz) == (3 if pin else 0) + 2, (fa, fz))
    check("%s: no forward rule names one subnet or one interface alone" % label, not [t for t in fz if LONE.search(t)], [t for t in fz if LONE.search(t)][:2])
    if pin:
        rst = "ip saddr { %s } tcp dport 443 meta mark %s counter reject with tcp reset" % (", ".join(N._collapse4(plan8(10, 3)[0])), hex(N.SNI_RESET_MARK))
        check("%s: the SNI reset is one rule, every subnet collapsed in its set" % label, rst in fz, fz)
    check("%s: the IPv6 drops are one rule a direction, every interface in its set" % label,
          [t for t in fz if "nfproto ipv6" in t] == ["meta nfproto ipv6 %sname { %s } drop" % (d, ", ".join('"%s"' % f for f in sorted(IFS(12))))
                                                     for d in ("iif", "oif")], fz)
    check("%s: pass 3 over its own render rebuilds nothing" % label, not ra[2]["scripts"] and not rz[2]["scripts"],
          (ra[2]["scripts"][:1], rz[2]["scripts"][:1]))
    for k, p in FWD_PK.items():
        wa, wz = Ka.m.chain_walk(T, "forward", **p)["walked"], Kz.m.chain_walk(T, "forward", **p)["walked"]
        check("%s, %s: the same forward rules read with 2 subnets and 2 interfaces as with 10 and 12 (%d)" % (label, k, wa), wa == wz, (wa, wz))
    Kw, rw = build11(N, plan8(2, 3), 0, pin, queue, ifs=["wg-drop", "reject-x", "awg0"])   # a verdict's word in a device's name
    check("%s: smart interfaces named `wg-drop` and `reject-x`: nothing refused, and the third pass rebuilds nothing — the drift "
          "gate counts forward's rules, not the words in them" % label, not rw[2]["scripts"] and not any(x["errors"] for x in rw) and not Kw.refused,
          (rw[2]["scripts"][:1], [x["errors"] for x in rw], Kw.refused[:1]))
# never `{ }`: an SNI node with no IPv4 subnet of its own (arrivals only) and no IPv6 interface still has a forward chain
Ke = SmartKernel()
geo11(N, "geo11e")
_ce = plan8(1, 3)[1]
re11 = [mpass(N, Ke, [], _ce, True, False, v6_ifaces=[], blk_reject=True, arrivals=ARR11)]
for j, c in enumerate(_ce):
    if N._smart_setname(c) in Ke.m.tables.get(T, {}).get("sets", {}):
        Ke.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
re11 += [mpass(N, Ke, [], _ce, True, False, v6_ifaces=[], blk_reject=True, arrivals=ARR11) for _ in range(2)]
check("an SNI node with arrivals only and no IPv6 interface: no `{ }`, nothing refused, its forward resets the arrivals' first hits",
      not any(x["errors"] for x in re11) and not Ke.refused and not any(EMPTY.search(s) for s in Ke.scripts)
      and any("@ar" in t for t in fwd(Ke)) and not any("nfproto ipv6" in t for t in fwd(Ke)), ([x["errors"] for x in re11], Ke.refused[:2], fwd(Ke)))
check("…and its third pass rebuilds nothing", not re11[2]["scripts"], re11[2]["scripts"][:1])


def fgrid(subs, nv):
    """Every forwarded packet the chain decides on: IPv4 from each subnet, an arrival, a stranger and a public address —
    in by a client device, a mesh leg or the WAN, TCP 443, UDP 443 and TCP 80, under every mark swg-sni or routing leaves
    on it, and replies to them; IPv6 in and out of each smart interface and two others, with and without the block mark."""
    nets = [ipaddress.ip_network(s, strict=False) for s in subs]
    srcs = [str(n.network_address + k) for n in nets for k in ((5, 6) if n.prefixlen >= 24 else (5, 6, 261))] + ["10.28.0.5", "10.200.0.5", "198.51.0.9"]
    marks = (0, 0x1b59, N.SNI_RESET_MARK, N.SNI_BLOCK_MARK, (1 << 16) | N.SNI_BLOCK_MARK)
    g = [dict(iif=iif, saddr=s, daddr="198.51.1.7", oif="eth0", proto=pr, dport=pt, mark=m) for s in srcs for iif in ("awg0", "swg_n", "eth0")
         for pr, pt in (("tcp", 443), ("udp", 443), ("tcp", 80)) for m in marks]
    g += [dict(iif="eth0", saddr="198.51.1.7", daddr=s, oif="awg0", mark=m) for s in srcs for m in marks]
    devs = IFS(nv) + ["eth0", "wg9"]
    return g + [dict(iif=a, saddr="0.0.0.0", daddr="0.0.0.0", oif=b, v6=True, mark=m) for a in devs for b in devs if a != b
                for m in (0, N.SNI_BLOCK_MARK)]


EQ11 = [("3 subnets, 3 IPv6 interfaces, an arrival", plan8(3, 3), 3, True), ("1 subnet, 1 interface", plan8(1, 4), 1, False),
        ("overlapping subnets", EQ[2][1], 2, True)]
for label, pin, queue in ENG if H else ():
    for name, plan, nv, arr in EQ11:
        Kc, rc = build11(N, plan, nv, pin, queue, arr, "geo11c", 2)
        Kb, rb = build11(H, plan, nv, pin, queue, arr, "geo11b", 2)
        g = fgrid(sorted({e["subnet"] for e in plan[2]}), nv)
        vc = [Kc.m.chain_walk(T, "forward", **p)["verdict"] for p in g]
        vb = [Kb.m.chain_walk(T, "forward", **p)["verdict"] for p in g]
        diff = [(g[i], vb[i], vc[i]) for i in range(len(g)) if vc[i] != vb[i]]
        check("%s, %s: %d forwarded packets, the same verdict as %s's forward (%d rules here, %d there)" % (label, name, len(g), BASE, len(fwd(Kc)), len(fwd(Kb))),
              not diff and not any(x["errors"] for x in rc + rb) and len(set(vc)) > 1, (diff[:3], [x["errors"] for x in rc + rb]))

# an older forward under this node's own render (the DP2a node's, with every other chain as this one writes it): rebuilt once
for label, pin, queue in ENG if H else ():
    p11 = plan8(3, 3)
    Kh, _ = build11(H, p11, 3, pin, queue, True, "geo11h", 2)
    Kn, rn = build11(N, p11, 3, pin, queue, True, "geo11n", 2)
    mine = fwd(Kn)
    tb = Kn.m.tables[T]
    tb["chains"]["forward"]["rules"] = [dict(r, ops=list(r["ops"])) for r in Kh.m.tables[T]["chains"]["forward"]["rules"]]
    for r in tb["chains"]["forward"]["rules"]:
        Kn.m.handle += 1
        r["handle"] = Kn.m.handle
    old = fwd(Kn)
    ru = routing11(N, Kn, p11, 3, pin, queue, True, 2)
    check("%s: an older forward (%d rules) under this node's render is rebuilt at the next pass (%d), and the pass after writes nothing" % (label, len(old), len(fwd(Kn))),
          len(old) > len(mine) and ru[0]["scripts"] and not ru[1]["scripts"] and fwd(Kn) == mine and not Kn.refused and not any(x["errors"] for x in ru),
          (old, fwd(Kn), [x["errors"] for x in ru], Kn.refused[:1]))
    v6out = dict(iif="eth0", saddr="0.0.0.0", daddr="0.0.0.0", oif="awg1", v6=True)
    Kn.m.tables[T]["chains"]["forward"]["rules"].pop()                         # the outbound IPv6 drop, lost from outside (a
    #                                                                            script commits a new copy: never a stale `tb`)
    lost = Kn.m.chain_walk(T, "forward", **v6out)["verdict"]
    rl = routing11(N, Kn, p11, 3, pin, queue, True, 1)
    check("%s: an IPv6 drop lost from outside (the inbound one still there) is rebuilt at the next pass — IPv6 out by awg1 drops again" % label,
          lost == "accept" and rl[0]["scripts"] and fwd(Kn) == mine and Kn.m.chain_walk(T, "forward", **v6out)["verdict"] == "drop",
          (lost, fwd(Kn), rl[0]["errors"]))
    H.GEO_DIR = N.GEO_DIR                                                      # the downgrade: the node before, on this kernel
    rd = routing11(H, Kn, p11, 3, pin, queue, True, 2)
    check("%s: the downgrade: the node before rebuilds forward as its own (%d rules), nothing refused, its next pass writes nothing" % (label, len(fwd(Kn))),
          fwd(Kn) == fwd(Kh) and not Kn.refused and not any(x["errors"] for x in rd) and not rd[1]["scripts"], (fwd(Kn), fwd(Kh), Kn.refused[:1]))


class TableNft:
    """One nft table as `_ensure_mech_block` / `_ensure_doh_block` see it: `nft list table` prints what the last load wrote."""
    def __init__(self, name):
        self.name, self.text, self.loads = name, None, []

    def __call__(self, args, input_text=None, timeout=20):
        args = [str(a) for a in args]
        if args[:4] == ["nft", "list", "table", "inet"] and args[4] == self.name:
            return CP(args, 0 if self.text is not None else 1, self.text or "", "" if self.text is not None else "Error: No such file or directory")
        if args[:2] == ["nft", "-f"]:
            text = open(args[2]).read()
            self.loads.append(text)
            self.text = "table inet %s {" % self.name + text.split("table inet %s {" % self.name, 1)[1]
        return CP(args, 0, "", "")


def pre_rules(text):
    m = re.search(r"chain pre \{[^\n]*\n(.*?)\n\s*\}", text or "", re.S)
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()] if m else []


def inside(rules, subs):
    """Rules that do NOT open with `ip saddr S`, S inside one of `subs` — a packet the head returns could match them."""
    hs = [ipaddress.ip_network(x) for x in subs]
    out = []
    for t in rules:
        m = re.match(r"ip saddr (\d+\.\d+\.\d+\.\d+(?:/\d+)?) ", t)
        if not (m and any(ipaddress.ip_network(m.group(1), strict=False).subnet_of(h) for h in hs)):
            out.append(t)
    return out


def table11(M, name, call, geo_name, nf=None):
    """One `_ensure_*_block` pass of M on table `name` (a fresh one unless `nf` is given) → (nf, res, loaded or None)."""
    nf = nf or TableNft(name)
    if geo_name:
        geo11(M, geo_name)
    M.run = nf
    res = {"changed": 0, "errors": []}
    n0 = len(nf.loads)
    call(M, res)
    return nf, res, (nf.loads[n0] if len(nf.loads) > n0 else None)


MECH11 = {"10.8.0.0/24": ["smtp", "portscan"], "10.9.0.0/24": ["portscan"], "10.12.0.0/24": ["quic"], "10.13.0.0/16": ["smtp"]}
SA11 = ["10.10.0.4/32", "192.0.2.0/24"]
OBS11, STR11 = ["10.8.0.0/24", "10.9.0.0/24", "10.13.0.0/16"], ["10.12.0.0/24"]
mech11 = lambda M, res, m=MECH11: M._ensure_mech_block(m, res, scan_allow=SA11)
doh11 = lambda M, res, o=OBS11, s=STR11: M._ensure_doh_block(o, s, res)
CL = re.compile(r"ip saddr \S+|ct state new|(?:udp|tcp) dport \d+|ip daddr @\S+|fib daddr type != local")


def clauses(t):
    """A swg_doh rule → (its matches, as a set; whether they are the whole match part; its statements)."""
    m, _, st = t.partition(" update @doh_seen")
    return set(CL.findall(m)), " ".join(CL.findall(m)) == m.strip(), "update @doh_seen" + st


for tname, call, subs in (("swg_mech", mech11, sorted(MECH11)), ("swg_doh", doh11, sorted(set(OBS11) | set(STR11)))):
    table = N.MECH_NFT_TABLE if tname == "swg_mech" else N.DOH_NFT_TABLE
    _, res_c, txt_c = table11(N, table, call, "geo11t")
    c = pre_rules(txt_c)
    head = "ip saddr != { %s } return" % ", ".join(N._collapse4(subs))
    check("%s: loads, and its first rule is one head set of every subnet, collapsed (%s)" % (tname, head),
          not res_c["errors"] and c[:1] == [head], (res_c["errors"], c[:2]))
    check("%s: …its second, `meta nfproto ipv6 return`: an IPv6 packet, which no `ip saddr` match ever holds for, reads two" % tname,
          c[1:2] == ["meta nfproto ipv6 return"], c[:3])
    hm = re.fullmatch(r"ip saddr != \{ (.+) \} return", c[0]) if c else None   # the head as written, not as this test expects it
    hset = hm.group(1).split(", ") if hm else []
    check("%s: …every rule after those opens with a subnet inside the head set as written: a packet the head returns matched none of them" % tname,
          len(c) > 2 and hset and not inside(c[2:], hset), (hset, inside(c[2:], hset)[:2]))
    if tname == "swg_doh":
        late = [t for t in c[2:] if not -1 < t.find(" dport ") < t.find("fib daddr type != local")]
        check("swg_doh: …the route lookup (`fib`) after the port test in every rule: a packet of S to no DNS port never reaches it", not late, late[:2])
    if H:
        _, res_b, txt_b = table11(H, table, call, "geo11tb")
        b = pre_rules(txt_b)
        if tname == "swg_mech":
            check("swg_mech: …and apart from those two lines, the table is the node before's, byte for byte (%d rules after them)" % len(b),
                  txt_c.replace("    " + head + "\n", "", 1).replace("    meta nfproto ipv6 return\n", "", 1) == txt_b, (c[2:4], b[:2]))
        else:
            cc, bb = [clauses(t) for t in c[2:]], [clauses(t) for t in b]
            check("swg_doh: …and every rule after those is the node before's, rule for rule: the same matches, the same statements (%d)" % len(b),
                  len(cc) == len(bb) and all(x[1] and x[0] == y[0] and x[2] == y[2] for x, y in zip(cc, bb)), (c[2:4], b[:2]))
            check("swg_doh: …and the sets are the node before's", txt_c.split("  chain pre")[0] == txt_b.split("  chain pre")[0],
                  (txt_c.split("  chain pre")[0][-200:], txt_b.split("  chain pre")[0][-200:]))
        nf = TableNft(table)                                       # the update: the node before's table, then this node's passes
        geo11(H, "geo11tu")
        N.GEO_DIR = H.GEO_DIR
        table11(H, table, call, None, nf)
        up = [table11(N, table, call, None, nf)[2] for _ in range(2)]
        down = [table11(H, table, call, None, nf)[2] for _ in range(2)]
        check("%s: the update rebuilds it once and then holds; the downgrade rebuilds it once, to the node before's own table" % tname,
              up[0] is not None and up[1] is None and down[0] is not None and down[1] is None and pre_rules(nf.text) == b,
              ([x is not None for x in up + down], pre_rules(nf.text)[:2]))
    _, res_v, txt_v = table11(N, table, (lambda M, res: mech11(M, res, {"fd00:8::/64": ["smtp"]})) if tname == "swg_mech"
                              else (lambda M, res: doh11(M, res, ["fd00:8::/64"], [])), "geo11tv")
    # The head's own guard, and only that: the panel sends the interfaces' IPv4 subnets alone, and a list with an IPv6 prefix
    # writes `ip saddr <IPv6 prefix>` rules that nft refuses whole, as before DP2b — this checks no `{ }` is ADDED to it
    check("%s: a list with no IPv4 prefix gets no head and no `{ }` from it (not that such a table loads: its own rules name "
          "an IPv6 prefix, refused by nft as before; the panel sends IPv4 subnets only)" % tname,
          txt_v is not None and "ip saddr != " not in txt_v and not EMPTY.search(txt_v), (txt_v or "")[-300:])

# ── [12] prerouting: an IPv6 packet stops at the dispatch's second rule ──────────────────────────────────────────────────
SECTION[0] = "[12]"
print("\n[12] prerouting: an IPv6 packet stops right after the dispatch's head")
V6P = dict(iif="eth0", saddr="0.0.0.0", daddr="0.0.0.0", v6=True)
for label, pin, queue in ENG:
    Ka, _, _, _, _, ra = build8(N, 2, 3, pin, queue, geo="geo12a")
    Kz, _, _, _, _, rz = build8(N, 10, 3, pin, queue, geo="geo12z")
    pre_z = [r["text"] for r in (Kz.m.tables.get(T) or {}).get("chains", {}).get("prerouting", {}).get("rules", [])]
    hi = next((i for i, t in enumerate(pre_z) if t.startswith("ip saddr != {")), -1)
    check("%s: right after the head, `meta nfproto ipv6 return` — `ip saddr` never holds for IPv6, so the head cannot return it" % label,
          hi >= 0 and pre_z[hi + 1:hi + 2] == ["meta nfproto ipv6 return"], pre_z[:hi + 3])
    for k, p in (("an IPv6 packet from the WAN", V6P), ("an IPv6 packet from a client device", dict(V6P, iif="awg0"))):
        wa, wz = Ka.m.chain_walk(T, "prerouting", **p), Kz.m.chain_walk(T, "prerouting", **p)
        check("%s, %s: the same rules with 2 subnets and with 10 (%d), no goto, accepted unmarked" % (label, k, wa["walked"]),
              wa["walked"] == wz["walked"] <= 4 and not [c for c in wz["via"] if c != "prerouting"] and wz["verdict"] == "accept", (wa, wz))
    # DP2a's dispatch had no IPv6 return: a table without it — that layout, or one lost from outside — is rebuilt once
    Kd, _, cats_d, ents_d, srcs_d, _ = build8(N, 3, 3, pin, queue, geo="geo12d")
    rl = (((Kd.m.tables.get(T) or {}).get("chains") or {}).get("prerouting") or {}).get("rules", [])
    i6 = next((i for i, r in enumerate(rl) if r["text"] == "meta nfproto ipv6 return"), None)   # a render without one is RED
    if i6 is not None:                                                                              # below, never a crash
        del rl[i6]
    before = Kd.m.chain_walk(T, "prerouting", **V6P)["walked"]
    rd = [mpass(N, Kd, ents_d, cats_d, pin, queue, srcs=srcs_d) for _ in range(2)]
    after = Kd.m.chain_walk(T, "prerouting", **V6P)["walked"]
    check("%s: DP2a's dispatch, without the IPv6 return (an IPv6 packet read %d rules), is rebuilt at the next pass (%d), "
          "and the pass after writes nothing" % (label, before, after),
          i6 is not None and rd[0]["scripts"] and not rd[1]["scripts"] and after < before and not any(x["errors"] for x in rd)
          and not Kd.refused, (i6, [x["errors"] for x in rd], rd[1]["scripts"][:1], Kd.refused[:1]))
K1v, _, _, _, _, r1v = build8(N, 1, 3, False, False, geo="geo12o")
check("one subnet (one chain, no head): no IPv6 return, an IPv6 packet reads its one goto rule and passes",
      "meta nfproto ipv6 return" not in [r["text"] for r in K1v.m.tables[T]["chains"]["prerouting"]["rules"]]
      and K1v.m.chain_walk(T, "prerouting", **V6P)["walked"] <= 2 and not r1v[2]["scripts"], K1v.m.tables[T]["chains"]["prerouting"]["rules"])

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    red = [f for f in FAILS if f.split()[0] in sec.split()]
    print("plant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(red), sec)) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
