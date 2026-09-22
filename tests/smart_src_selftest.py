#!/usr/bin/env python3
"""Self-test for per-person smart rows on the node (docs/ROUTING-PEERS-MESH-PLAN.md §6.1–6.3, §8 P1).

A smart entry carrying `src: <wid>` applies only to the devices the panel resolved for that selection
(`smart.srcs = {wid: [[device, "a.b.c.d/32"], …]}`). The node puts them in ONE `ifname . ipv4_addr` hash set per
selection and gives each ROW — a run of consecutive entries with the same (subnet, selection) — its own chain, reached
by one `iifname . ip saddr @src_<wid> jump sr<k>`. What that has to keep, each checked on what `_ensure_smart_nft`
actually hands nft, through the swg_smart transaction model (tests/nft_guarded_model.py) and a packet walk:

  · first match — a row's rules end in `accept` (return there would fall back into the base chain and meet the
    interface's catch-all, which re-marks everything);
  · the binding — a chosen device's ADDRESS sent from another device is not taken for it;
  · the old shape — a plan without `src` signs and renders exactly as it did (T3), so a fleet that uses none of this
    rebuilds nothing on upgrade;
  · churn — a member change replaces the set in the pass's one transaction and rebuilds no chain;
  · the TTL swap — `delete set catl_*` while a row chain still matches it rejects the WHOLE batch (T2);
  · the Kernel-SNI hand-off — a `src` entry reaches `_ensure_smart_xtstring` (with its selection's members) only where the
    `hash:net,iface` probe passed; where it failed, none does and the node reports `src: 1` (tests/ksni_src_selftest.py
    gates what xt_string then builds, and its plant (g) replaces this file's retired plant (f));
  · the three positional readers of the want-tuple — driven in all three engine shapes (kernel/Force-DNS,
    Hybrid SNI with the queue, Kernel SNI), because one of them runs only with the queue on;
  · shadow sets — on Force-DNS and Hybrid SNI a host goes only to its MOST SPECIFIC name's set, so a name used by some
    devices' rules must not take it from a broader name's rules for the others (review B1: Alice's `sh.h2.example` →
    Direct un-blocked `h2.example`'s Block for everyone else). Each case has its control without shadows.

Hermetic: no nft, no ip, no root. Run: python3 tests/smart_src_selftest.py   (0 = pass)
  --plant a|b|c|d|e|g1|g2|g3|h   plant one defect and expect RED on its own check (exit 0 when caught):
     a  the source set is never created, so the row's jump names a set that is not there
     b  a row chain's rules end in `return`
     c  the learned-set TTL swap forgets the row chains (and the pin-mode Block chains)
     d  the signature gains a marker for everyone, `src` or not (every node's chain rebuilds on upgrade)
     e  the chain signature signs the set MEMBERS (a member change rebuilds the chain)
     g1/g2/g3  one positional reader of the want-tuple left at four names (expect_pre · the emit loop · `_routed_cats`)
     h  the drift gate forgets that a row emits prerouting rules (an all-Direct per-person chain emptied from outside stays empty)
     s1 a shadow rule loses its "not these devices" (Alice's own name, placed below the Block, is blocked for her)
     s2 the base chain emits no shadow rule (Bob walks past the everyone Block again)
     s3 a row chain emits no shadow rule (a per-person Block loses the host to another selection's name)
     s4 every pair of categories counts as reaching different devices (everyone-rules on one subnet lose "most specific wins")
     s5 an entry gets the shadow even where the claimer has a rule for everyone on its subnet (same loss, per subnet)
     s6 the node reports shadow sets as destinations of their own
     s7 dnsmasq is told "unchanged" when only the shadows changed (it keeps the old directives)
     s8 a site name is taken as inside a first-label pattern (`mail.google.com` inside `mail.*`: `x.mail.google.com` is not)
     s9 a shadow rule leaves out only the claimer's devices, not a more specific container's (nested names land on the wrong rule)
     s10 the blocked metric ignores a block list's shadow rule (Bob's blocked packets go uncounted)
     s11 Hybrid SNI ranks a zone above a site (the broader `*.example` rule takes Bob's `h2.example` host)
     s12 Force-DNS ranks every key alike (same, on dnsmasq's longest-key ladder)
     n1 an entry whose `src` is empty is lowered for the whole subnet (the key no longer decides)
     pb1 pin mode: the Block's chain exempts nothing (an Exit above it keeps the SYN and loses the rest)
     pb2 pin mode: an exemption forgets whose rule it was (a device outside the row above is let through the Block)
     pb3 the Block chains do not reach the signature (a running SNI node keeps the old rules)
     pb4 Hybrid SNI: an exempted connection skips swg-sni (its first packets are no longer queued)
     pb5 pin mode: a Block decides at the first packet only (a connection that beat swg-sni's learning stays up)
     pb6 Hybrid SNI: a shadow's exemption forgets its "not these devices" (Alice passes a Block above her own row)
     pb7 Hybrid SNI: the exemption leaves out the learned sets (a hostname Exit loses its connection after the SYN again)
     pb8 Hybrid SNI: the queue rule in a Block chain forgets whose rule it was (a device outside the row is queued past the Block)
     pb9 Hybrid SNI: the queue rule in a Block chain matches any address (a connection that beat the learning keeps 11 packets)
     pb10 a Block chain no longer wanted is left behind (the Exit sets it matches can never be reaped)
     c2 the learned-set TTL swap forgets the pin-mode Block chains (they match catl_ sets too — the whole batch is refused)
     sc the swg-sni map is rebuilt on every pass again (every name sorted and serialised to learn nothing changed)
     sc2 the swg-sni map is never rebuilt while its inputs and file look unchanged (an edit the stat cannot see never heals)
"""
import hashlib, importlib.machinery, ipaddress, importlib.util, json, os, shutil, sys, tempfile

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
    "a": ('            run(["nft", "add", "set", "inet", SMART_NFT_TABLE, sn, "{ type ifname . ipv4_addr; }"])',
          '            pass'),
    "b": ('''"meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "accept")
                    elif act == "direct":
                        bat.add(*_row, *_new, "ip", "daddr", "@" + snm, "accept")''',
          '''"meta", "mark", "set", str(T), *(["ct", "mark", "set", str(T)] if pin else []), "return")
                    elif act == "direct":
                        bat.add(*_row, *_new, "ip", "daddr", "@" + snm, "return")'''),
    "c": ('                for _c in ("catcount", "catany", "forward") + tuple(sorted(c for c in re.findall(r"chain (\\S+) {", body) if re.fullmatch(r"sr\\d+|pb\\d+", c))):',
          '                for _c in ("catcount", "catany", "forward"):'),
    "d": ('''("|lttl:" + str(learn_ttl) if queue else "") + "|s9").encode()).hexdigest()[:16]''',
          '''("|lttl:" + str(learn_ttl) if queue else "") + "|s9|src").encode()).hexdigest()[:16]'''),
    "e": ('''    sig = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(want) +''',
          '''    sig = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(want) + json.dumps(want_src) +'''),
    "g1": ('''    expect_pre = pin or any(w[2] != "direct" or len(w) > 4 for w in want)''',
           '''    expect_pre = pin or any(a != "direct" for (_, _, a, _) in want)'''),
    "g2": ('''            S, cat, act, T = w[:4]
            if len(w) > 4:''', '''            S, cat, act, T = w
            if len(w) > 4:'''),
    "h": ('''    expect_pre = pin or any(w[2] != "direct" or len(w) > 4 for w in want)''',
          '''    expect_pre = pin or any(w[2] != "direct" for w in want)'''),
    "s1": ('''                xm = [t for x in ex for t in ("iifname", ".", "ip", "saddr", "!=", "@" + _smart_srcsetname(x))]''',
           '''                xm = []'''),
    "s2": ('''            _shadow_rules(i, lambda *m, _S=S: _add("ip", "saddr", _S, *m), "return")''', '''            pass'''),
    "s3": ('''                _shadow_rules(i, lambda *m, _k=k: bat.add("add", "rule", "inet", SMART_NFT_TABLE, "sr%d" % _k, *m), "accept")''',
           '''                pass'''),
    "s4": ('''        return any(None not in cov.get(S, ()) and not (w and w in cov.get(S, ())) for S, ws in aud[c2].items() for w in ws)''',
           '''        return True'''),
    "s5": ('''                if None not in cov and not (len(w) > 4 and w[4] in cov):''', '''                if True:'''),
    "s6": ('''            "sets": {k: v for k, v in t["counts"].items() if not re.fullmatch(r"catl?_sw_[0-9a-f]{10}|src_[0-9a-f]{12}", k)}, "rules": rules,''',
           '''            "sets": dict(t["counts"]), "rules": rules,'''),
    "s7": ('''            dom_unchanged, _SHADOW["dns"] = False, (_shw or {}).get("sig", "")''',
           '''            _SHADOW["dns"] = (_shw or {}).get("sig", "")'''),
    "s8": ('''                hit += [(c, rank("zone", lb[-1])) for c in own["zone"].get(lb[-1], ())]''',
           '''                hit += [(c, rank("zone", lb[-1])) for c in own["zone"].get(lb[-1], ())] + [(c, (2,)) for c in own.get("first", {}).get(lb[0], ())]'''),
    "s9": ('''                cov = set().union(*(aud.get(c, {}).get(w[0], set()) for c in [c1] + list(more)))''',
           '''                cov = aud.get(c1, {}).get(w[0], set())'''),
    "s10": ('''            if ("blku" not in ln and not (_m and _m.group(1) in _bsw)) or "drop" not in ln:''',
            '''            if "blku" not in ln or "drop" not in ln:'''),
    "s11": ('''        if kd == "zone":
            return (3,)''', '''        if kd == "zone":
            return (1, -99)'''),
    "s12": ('''            return (-(n.count(".") + 1),)                      # dnsmasq: the longest key (a zone is a one-label key)''',
            '''            return (0,)'''),
    "n1": [('''    spec = [e for e in smart_e if e["category"] != "all" and ("src" not in e or _SRC_WID_RE.fullmatch(str(e["src"])))]''',
            '''    spec = [e for e in smart_e if e["category"] != "all" and (not e.get("src") or _SRC_WID_RE.fullmatch(str(e["src"])))]'''),
           ('''e.get("table")) + ((e["src"],) if "src" in e else ())''', '''e.get("table")) + ((e["src"],) if e.get("src") else ())''')],
    "c2": ('                for _c in ("catcount", "catany", "forward") + tuple(sorted(c for c in re.findall(r"chain (\\S+) {", body) if re.fullmatch(r"sr\\d+|pb\\d+", c))):',
           '                for _c in ("catcount", "catany", "forward") + tuple(sorted(c for c in re.findall(r"chain (\\S+) {", body) if re.fullmatch(r"sr\\d+", c))):'),
    "pb1": ('''                bat.add("add", "rule", "inet", SMART_NFT_TABLE, "pb%d" % i, *cnd, "ip", "daddr", "@" + snm, "accept")''',
            '''                pass'''),
    "pb2": ('''                    ex += [[cnd, snm] for snm in''', '''                    ex += [[[], snm] for snm in'''),
    "pb3": ('''        sig = hashlib.sha1((sig + "|pb:" + json.dumps(sorted(pb_of.items()))).encode()).hexdigest()[:16]''', '''        pass'''),
    "pb4": ('''                if queue:                                      # swg-sni still reads the connection's first packets''',
            '''                if False:'''),
    "pb5": ('''                        _add("ip", "saddr", S, "ip", "daddr", "@" + snm, *(["jump", "pb%d" % i] if i in pb_of else ["drop"]))''',
            '''                        _add("ip", "saddr", S, *_new, "ip", "daddr", "@" + snm, *(["jump", "pb%d" % i] if i in pb_of else ["drop"]))'''),
    "pb6": ('''[(sh, cond + [t for x in xs for t in ("iifname", ".", "ip", "saddr", "!=", "@" + _smart_srcsetname(x))])''',
            '''[(sh, cond)'''),
    "pb7": ('''                    ex += [[cnd, snm] for snm in [_smart_setname(c)] + ([_smart_learnsetname(c)] if queue else [])]''',
            '''                    ex += [[cnd, snm] for snm in [_smart_setname(c)]]'''),
    "pb8": ('''"pb%d" % i, *cnd, "ip", "daddr", "@" + snm, "tcp", "dport", "443",''', '''"pb%d" % i, "ip", "daddr", "@" + snm, "tcp", "dport", "443",'''),
    "pb9": ('''"pb%d" % i, *cnd, "ip", "daddr", "@" + snm, "tcp", "dport", "443",''', '''"pb%d" % i, *cnd, "tcp", "dport", "443",'''),
    "pb10": ('''            if c not in want_pb:
                bat.add("flush", "chain", "inet", SMART_NFT_TABLE, c)''', '''            if False:
                bat.add("flush", "chain", "inet", SMART_NFT_TABLE, c)'''),
    "sc": ('''        if not (map_key is not None and _st and _SNI_MAP_LAST["key"] == map_key and _SNI_MAP_LAST["stat"] == _st   # cannot see heals''',
           '''        if True or not (map_key is not None and _st and _SNI_MAP_LAST["key"] == map_key and _SNI_MAP_LAST["stat"] == _st'''),
    "sc2": ('''                and _SNI_MAP_LAST["n"] % 60):''', '''                ):'''),
    "g3": ('''        _routed_cats = {w[1] for w in want if w[1] != "all"} if queue else set()''',
           '''        _routed_cats = {c for (_S, c, _a, _T) in want if c != "all"} if queue else set()'''),
}

STATE = tempfile.mkdtemp(prefix="smart-src-")
os.environ["SWG_NODED_STATE"] = STATE
path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(NODED, encoding="utf-8").read()
    for old, new in (PLANTS[PLANT] if isinstance(PLANTS[PLANT], list) else [PLANTS[PLANT]]):   # a plant may need two lines
        assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
        src = src.replace(old, new, 1)
    path = os.path.join(STATE, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src)

_l = importlib.machinery.SourceFileLoader("swgnoded_src", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_src", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = os.path.join(STATE, "geo")

T = N.SMART_NFT_TABLE
S = "10.8.0.0/24"
W1, W2 = "1f2e3d4c5b6a", "a0b1c2d3e4f5"
CHOSEN, OTHER, W2DEV = "10.8.0.5", "10.8.0.6", "10.8.0.9"
ENTRIES = [
    {"subnet": S, "category": "custom_a", "action": "exit", "via_iface": "swg_p", "table": 7000},               # everyone
    {"subnet": S, "category": "custom_b", "action": "exit", "via_iface": "swg_q", "table": 7001, "src": W1},    # row 0
    {"subnet": S, "category": "custom_c", "action": "direct", "src": W1},                                      # row 0
    {"subnet": S, "category": "custom_d", "action": "exit", "via_iface": "swg_r", "table": 7002},               # everyone
    {"subnet": S, "category": "custom_e", "action": "block", "src": W2},                                       # row 1
    {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_p", "table": 7000},                    # catch-all
]
SRCS = {W1: [["wg0", CHOSEN + "/32"]], W2: [["wg0", W2DEV + "/32"]]}
DEST = {"custom_a": "198.51.100.0/24", "custom_b": "203.0.113.0/24", "custom_c": "192.0.2.0/24",
        "custom_d": "100.64.0.0/24", "custom_e": "100.65.0.0/24"}
MODES = (("kernel / Force-DNS", False, False), ("Hybrid SNI", True, True), ("Kernel SNI", True, False))


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    N._SRC_SETS.clear()
    K = SmartKernel()
    N.run = K
    return K


def npass(K, entries, pin, queue, srcs=SRCS, ttl=3600):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    n0 = len(K.scripts)
    try:
        N._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=pin, queue=queue,
                            reset_mark=(N.SNI_RESET_MARK if pin else 0), learn_ttl=ttl, srcs=srcs)
    except Exception as e:                                     # a crash is reported as ITS check failing, never as a pass
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    res["scripts"] = K.scripts[n0:]
    return res


def fill(K, cats):
    for c in cats:
        if c in DEST and N._smart_setname(c) in ((K.m.tables.get(T) or {}).get("sets") or {}):
            K.load_set(T, N._smart_setname(c), [DEST[c]])


def els(K, name):
    return ((K.m.tables.get(T) or {}).get("sets") or {}).get(name, {}).get("els", set())


def walk(K, iif, saddr, cat_dst, ct="new"):
    return K.m.packet(T, iif, saddr, cat_dst, ct=ct)


# ── 1. all three engine shapes: the rows are built, the batch lands, the node settles, and packets go where the rules say ──
for label, pin, queue in MODES:
    print("\n[%s]" % label)
    K = fresh()
    r = [npass(K, ENTRIES, pin, queue)]
    if not r[0]["errors"] and T in K.m.tables:
        fill(K, DEST)                                           # what the geo/CIDR loaders do between passes: the counting
    r += [npass(K, ENTRIES, pin, queue) for _ in range(2)]      # chains key off populated sets, so pass 2 builds them, pass 3 is 0
    check("%s: every pass runs a per-person entry without an error" % label, not any(x["errors"] for x in r),
          [x["errors"] for x in r])
    check("%s: nothing refused by nft" % label, not K.refused, K.refused[:2])
    if r[0]["errors"] or T not in K.m.tables:
        continue
    tb = K.m.tables[T]
    check("%s: one chain per row — sr0 (two entries, one selection) and sr1" % label,
          {c for c in tb["chains"] if c.startswith("sr")} == {"sr0", "sr1"}, sorted(tb["chains"]))
    jumps = [x["text"] for x in tb["chains"]["prerouting"]["rules"] if "jump" in x["text"]]
    check("%s: ONE jump per row, keyed by the (device, address) set" % label,
          jumps == ["iifname . ip saddr @src_%s jump sr0" % W1, "iifname . ip saddr @src_%s jump sr1" % W2], jumps)
    check("%s: the source sets hold the resolved devices, bare" % label,
          {(e[0], e[1]) for e in els(K, "src_" + W1)} == {("wg0", int(ipaddress.IPv4Address(CHOSEN)))}, els(K, "src_" + W1))
    h0 = K.handles(T, "prerouting")
    check("%s: pass 3 changes nothing" % label, r[2]["changed"] == 0 and not r[2]["scripts"], r[2])
    # packets (a NEW connection; pin mode decides there)
    v = walk(K, "wg0", CHOSEN, "203.0.113.9")
    check("%s: the chosen device → the row's destination leaves by the row's exit (7001)" % label,
          v["mark"] == 7001 and v["verdict"] == "accept" and "sr0" in v["via"], v)
    v = walk(K, "wg0", OTHER, "203.0.113.9")
    check("%s: a device that is NOT chosen, same destination, takes the interface's catch-all (7000)" % label,
          v["mark"] == 7000 and "sr0" not in v["via"], v)
    v = walk(K, "wg1", CHOSEN, "203.0.113.9")
    check("%s: the chosen ADDRESS from another device is not taken for it (catch-all, 7000)" % label,
          v["mark"] == 7000 and "sr0" not in v["via"], v)
    v = walk(K, "wg0", CHOSEN, "192.0.2.9")
    check("%s: a per-person Direct row wins over the later catch-all (first match: unmarked)" % label,
          v["mark"] == 0 and v["verdict"] == "accept", v)
    v = walk(K, "wg0", CHOSEN, "100.64.0.9")
    check("%s: the interface's own rule after the row still applies to the chosen device (7002)" % label,
          v["mark"] == 7002, v)
    v = walk(K, "wg0", CHOSEN, "198.51.100.9")
    check("%s: the interface's own rule BEFORE the row still wins for the chosen device (7000)" % label,
          v["mark"] == 7000 and "sr0" not in v["via"], v)
    v = walk(K, "wg0", W2DEV, "100.65.0.9")
    check("%s: a per-person Block drops only its chosen device" % label, v["verdict"] == "drop", v)
    v = walk(K, "wg0", OTHER, "100.65.0.9")
    check("%s: …and not a device it does not choose (catch-all, 7000)" % label,
          v["verdict"] == "accept" and v["mark"] == 7000, v)
    # a member change: the set is replaced, the chain is not rebuilt
    s2 = {W1: [["wg0", CHOSEN + "/32"], ["wg0", "10.8.0.77/32"]], W2: SRCS[W2]}
    rm = npass(K, ENTRIES, pin, queue, srcs=s2)
    body = "".join(rm["scripts"])
    check("%s: a member change lands" % label, not rm["errors"] and rm["scripts"], rm)
    check("%s: a member change rebuilds no chain (no flush, no rule, handles unchanged)" % label,
          "flush chain" not in body and "add rule" not in body and K.handles(T, "prerouting") == h0, body[:300])
    check("%s: …and replaces the set whole in one script (flush set + add element)" % label,
          "flush set inet %s src_%s" % (T, W1) in body and '"wg0" . 10.8.0.77' in body, body[:300])
    v = walk(K, "wg0", "10.8.0.77", "203.0.113.9")
    check("%s: the new member is covered on the same pass" % label, v["mark"] == 7001, v)
    check("%s: and the pass after it is quiet again" % label, not npass(K, ENTRIES, pin, queue, srcs=s2)["scripts"])

# ── 1b. an interface whose ONLY rules are per-person: nothing for everyone before the row ────────────────────────────────
print("\n[only per-person rows]")
ONLY = [{"subnet": S, "category": "custom_b", "action": "exit", "via_iface": "swg_q", "table": 7001, "src": W1},
        {"subnet": S, "category": "custom_c", "action": "direct", "src": W1}]
DIRECT_ONLY = [{"subnet": S, "category": "custom_c", "action": "direct", "src": W1}]
for label, pin, queue in MODES:
    K = fresh()
    r = [npass(K, ONLY, pin, queue) for _ in range(3)]
    fill(K, DEST)
    check("%s: an interface with only per-person rows runs without an error" % label, not any(x["errors"] for x in r),
          [x["errors"] for x in r])
    v = walk(K, "wg0", CHOSEN, "203.0.113.9")
    check("%s: …its chosen device is routed (7001)" % label, v["mark"] == 7001, v)
    v = walk(K, "wg0", OTHER, "203.0.113.9")
    check("%s: …and a device it does not choose is left alone (no mark)" % label, v["mark"] == 0, v)
K = fresh()
for _ in range(3):
    npass(K, DIRECT_ONLY, False, False)
fill(K, DEST)
if T in K.m.tables:
    K.m.tables[T]["chains"]["prerouting"]["rules"] = []          # something outside the node emptied the chain
rd = npass(K, DIRECT_ONLY, False, False)
v = walk(K, "wg0", CHOSEN, "192.0.2.9")
check("a chain holding only a per-person Direct row is rebuilt when emptied from outside (the drift gate sees rows)",
      not rd["errors"] and "sr0" in v["via"], (rd["errors"], v))

# ── 2. the learned-set TTL swap with rows present (T2) ────────────────────────────────────────────────────────────────────
print("\n[ip_learning TTL change on Hybrid SNI with rows]")
K = fresh()
for _ in range(3):
    npass(K, ENTRIES, True, True)
rt = npass(K, ENTRIES, True, True, ttl=120)
check("a learned-set TTL change lands while row chains match the learned sets", not rt["errors"] and rt["scripts"],
      rt["errors"] or K.refused[-1:])
check("…and the learned sets carry the new TTL",
      K.m.tables.get(T, {}).get("sets", {}).get("catl_custom_b", {}).get("timeout") == 120,
      K.m.tables.get(T, {}).get("sets", {}).get("catl_custom_b"))

# ── 3. a plan without `src` is what it always was (T3) ────────────────────────────────────────────────────────────────────
print("\n[a plan without src]")
PLAIN = [e for e in ENTRIES if not e.get("src")]
for label, pin, queue in MODES:
    K = fresh()
    for _ in range(3):
        npass(K, PLAIN, pin, queue, srcs=None)
    everything = " ".join(" ".join(c) for c in K.calls) + "".join(K.scripts)
    check("%s: no source set, no row chain, no jump" % label,
          "src_" not in everything and " sr0" not in everything and "jump" not in everything, everything[:200])
    # HEAD's own formula, pinned: a 4-tuple want and the `|s9` suffix
    spec = [e for e in PLAIN if e["category"] != "all"]
    allr = [e for e in PLAIN if e["category"] == "all"]
    w4 = [(e["subnet"], e["category"], e.get("action", "exit"), e.get("table")) for e in spec + allr]
    rst = N.SNI_RESET_MARK if pin else 0
    want_sig = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(w4) + "|v6:" + "" + "|rst:" + str(rst)
                             + ("|lttl:3600" if queue else "") + "|s9").encode()).hexdigest()[:16]
    have = open(os.path.join(N.GEO_DIR, ".smart-sig")).read().strip() if os.path.exists(os.path.join(N.GEO_DIR, ".smart-sig")) else ""
    check("%s: the smart signature is byte-for-byte HEAD's (no rebuild on upgrade)" % label, have == want_sig, (have, want_sig))

# ── 4. a selection that resolved to nothing, and one the node cannot read, never widen ─────────────────────────────────────
print("\n[never wider]")
K = fresh()
for _ in range(3):
    npass(K, ENTRIES, False, False, srcs={W2: SRCS[W2]})         # W1 absent from srcs
fill(K, DEST)
v = walk(K, "wg0", CHOSEN, "203.0.113.9")
check("a row whose selection has no members covers nobody (the catch-all, 7000)", v["mark"] == 7000, v)
K = fresh()
bad = [dict(e, src="../x") if e.get("src") == W1 else e for e in ENTRIES]
for _ in range(3):
    r = npass(K, bad, False, False)
fill(K, DEST)
_rules = [x["text"] for c in ((K.m.tables.get(T) or {}).get("chains") or {}).values() for x in c["rules"]]
check("an entry whose selection id is not 12 hex is dropped, never lowered for the whole subnet",
      not r["errors"] and _rules and not any("custom_b" in x for x in _rules), _rules)
K = fresh()
emp = [dict(e, src="") if e.get("src") == W1 else e for e in ENTRIES]
for _ in range(3):
    r = npass(K, emp, False, False)
fill(K, DEST)
v = walk(K, "wg0", OTHER, "203.0.113.9")
check("an entry whose selection id is EMPTY is dropped, never lowered for the whole subnet (the key decides, not its value)",
      not r["errors"] and v["mark"] == 7000 and "sr0" not in v["via"], (r["errors"], v))
K = fresh()
allsrc = [dict(e, src=W1) if e["category"] == "all" else e for e in ENTRIES]
for _ in range(3):
    npass(K, allsrc, False, False)
fill(K, DEST)
v = walk(K, "wg0", OTHER, "8.8.8.8")
check("a catch-all carrying a selection is never lowered for everyone", v["mark"] == 0, v)
K = fresh()
for _ in range(3):
    npass(K, ENTRIES, False, False, srcs={W1: [["wg0", "10.8.0.0/24"], ["bad name!", CHOSEN + "/32"], ["wg0", CHOSEN + "/32"]],
                                          W2: SRCS[W2]})
check("a member that is not one device + one host is left out, the rest load",
      {e[0] for e in els(K, "src_" + W1)} == {"wg0"} and len(els(K, "src_" + W1)) == 1, els(K, "src_" + W1))

# ── 5. rows removed: their chains go in the batch, their sets after it ─────────────────────────────────────────────────────
print("\n[reaper]")
K = fresh()
for _ in range(3):
    npass(K, ENTRIES, False, False)
for _ in range(3):
    rr = npass(K, PLAIN, False, False, srcs=None)
tb = K.m.tables.get(T) or {"chains": {"x": 1}, "sets": {}}
check("rows removed: no sr chain and no src set is left behind",
      not [c for c in tb["chains"] if c.startswith("sr")] and not [s for s in tb["sets"] if s.startswith("src_")],
      (sorted(tb["chains"]), sorted(tb["sets"])))
check("…and nothing was refused on the way", not K.refused, K.refused)

# ── 5b. the swg-sni map is built only when it can have changed ─────────────────────────────────────────────────────────────
print("\n[the swg-sni map: built only when its inputs or the file changed]")


class _Doms(dict):                                              # counts how often the writer walks the name lists
    walks = 0

    def items(self):
        _Doms.walks += 1
        return super().items()


class _Running:                                                 # a classifier that is already up: nothing is (re)launched
    def poll(self):
        return None

    def terminate(self):
        pass


N.SNI_MAP_PATH, N.SNI_PATTERNS_PATH = os.path.join(STATE, "sni-map.json"), os.path.join(STATE, "sni-patterns.json")
N._SNI_PROC.update(p=_Running(), ttl=3600)
N._SNI_MAP_LAST.update(key=None, stat=None)
D1 = _Doms({"custom_a": ["a.example", "b.example"]})


def sni(doms, key):
    res = {"changed": 0, "errors": []}
    N._ensure_sni_router(doms, [S], res, 3600, map_key=key, patterns={})
    return res


sni(D1, ("k1", ""))
w1 = _Doms.walks
check("the first pass writes the map", os.path.exists(N.SNI_MAP_PATH) and w1 == 1, (w1, os.path.exists(N.SNI_MAP_PATH)))
sni(D1, ("k1", ""))
check("an unchanged pass walks nothing (same inputs, the file as this process left it)", _Doms.walks == w1, _Doms.walks)
sni(D1, ("k1", "shadowsig"))
check("a changed shadow signature rebuilds it", _Doms.walks == w1 + 1, _Doms.walks)
os.remove(N.SNI_MAP_PATH)
sni(D1, ("k1", "shadowsig"))
check("a deleted map is written again on the next pass", os.path.exists(N.SNI_MAP_PATH) and _Doms.walks == w1 + 2, _Doms.walks)
open(N.SNI_MAP_PATH, "w").write('{"x": ["edited.example"]}')
sni(D1, ("k1", "shadowsig"))
check("a map edited by hand is put back", json.load(open(N.SNI_MAP_PATH)) == {"custom_a": ["a.example", "b.example"]},
      open(N.SNI_MAP_PATH).read())
N._SNI_MAP_LAST["n"] = 59
w0 = _Doms.walks
sni(D1, ("k1", "shadowsig"))
check("…and once in 60 passes it is rebuilt anyway (an edit the file's size and time cannot show still heals)", _Doms.walks == w0 + 1, _Doms.walks)
sni(D1, ("k1", "shadowsig"))
check("…then quiet again", _Doms.walks == w0 + 1, _Doms.walks)
n0 = _Doms.walks
sni(D1, None); sni(D1, None)
check("with no key (a caller that names no inputs) it builds every pass, as before", _Doms.walks == n0 + 2, _Doms.walks)
N._SNI_PROC.update(p=None)

# ── 6. the Kernel-SNI hand-off (plan §6.3, P1b): per-person entries reach xt_string only where the probe passed ─────────
# P1's plant (f) ("a `src` entry reaches _ensure_smart_xtstring") is RETIRED with P1b: on a box whose probe passes that is
# now the correct code. What stays true either way is checked here; what xt_string builds is tests/ksni_src_selftest.py's.
print("\n[Kernel SNI: the hand-off to xt_string]")
_seen = []
N._ensure_smart_xtstring = lambda host_entries, *a, **k: (_seen.append(([dict(e) for e in host_entries], k.get("srcs"))), [])[1]
N._kernel_sni_ok = lambda: True
N._ensure_sni_router = lambda *a, **k: None
N.reconcile_catk_chain = lambda *a, **k: None
for probe in (False, True):
    _seen.clear()
    N._KSNI_SRC["ok"] = probe
    K = fresh()
    N.run = lambda args, input_text=None, timeout=20: K(args, input_text, timeout) if args and args[0] == "nft" else \
        __import__("subprocess").CompletedProcess(args, 0, "", "")
    smart = {"entries": [dict(e) for e in ENTRIES], "categories": sorted({e["category"] for e in ENTRIES}), "mode": "sni_kernel",
             "srcs": SRCS, "domains": {c: ["x-%s.example" % c] for c in DEST}}
    try:
        N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
        _err = ""
    except Exception as e:
        _err = "%s: %s" % (type(e).__name__, e)
    tag = "probe %s: " % ("passed" if probe else "failed")
    check(tag + "reconcile_cascade runs a Kernel-SNI node with per-person entries", not _err, _err)
    check(tag + "xt_string was asked to build (the everyone-rules still go there)",
          bool(_seen) and any(c for c, _ in _seen), _seen)
    got = [e for c, _ in _seen for e in c if e.get("src")]
    if probe:
        check(tag + "every entry carrying `src` reached it, in plan order beside the rest",
              bool(_seen) and [e.get("src") for e in _seen[-1][0]] == [e.get("src") for e in ENTRIES
                                                                      if e.get("action", "exit") == "exit"], _seen[-1:])
        check(tag + "…with the selections' members", bool(_seen) and _seen[-1][1] == SRCS, _seen[-1:])
    else:
        check(tag + "no entry carrying `src` reached it (its rules would be refused one by one, T33)", not got, got)
        check(tag + "…and it was handed no members", bool(_seen) and not any(m for _, m in _seen), _seen)
    check(tag + "the node reports `src: %d`" % (2 if probe else 1), N.smart_status().get("src") == (2 if probe else 1),
          N.smart_status())
N._KSNI_SRC["ok"] = None

# ── 7. a more specific name never takes a host from rules for other devices (shadow sets, review B1) ─────────────────────
# What the engines do is simulated exactly as measured: a host lands in the sets of the category whose name matches it MOST
# specifically — and, because a shadow category repeats that name, in the shadow's sets too (dnsmasq's per-domain merge,
# swg-sni's `_index`). Every case runs again WITHOUT shadows as its control, which must show the leak.
print("\n[shadow sets]")
H, HB, S9 = "192.0.2.81", "192.0.2.99", "10.28.0.0/24"        # H: named by Alice's `sh.h2.example` AND the Block's `h2.example`
DOMS = {"custom_blk": ["h2.example"], "custom_al": ["sh.h2.example"]}
CA = {"subnet": S, "category": "all", "action": "exit", "via_iface": "swg_p", "table": 7000}
BLK = {"subnet": S, "category": "custom_blk", "action": "block"}
AL = {"subnet": S, "category": "custom_al", "action": "direct", "src": W1}
ALL_ = dict(AL); ALL_.pop("src")                               # the same rule for everyone
SRC1 = {W1: [["wg0", CHOSEN + "/32"]]}


def claim(K, shw, queue, by_cat):
    """{category: {winning operand: [ip]}} as the engine decides by specificity: the category's set fills, and so does every
    shadow that repeats THAT operand (one operand in two categories — dnsmasq's per-domain merge, swg-sni's `_index`).
    A bare [ip] list means the category's only operand in the test's names."""
    sets = (K.m.tables.get(T) or {}).get("sets") or {}
    for cat, won in by_cat.items():
        won = won if isinstance(won, dict) else {None: won}
        for op, ips in won.items():
            shs = [x[0] for lst in ((shw or {}).get("by_target") or {}).values() for x in lst if x[1] == cat
                   and (op is None or op in (shw.get("domains") or {}).get(x[0], [])
                        or any(op in (b.get(x[0]) or []) for b in (shw.get("pats") or {}).values()))]
            for c in [cat] + shs:
                nm = (N._smart_learnsetname if queue else N._smart_setname)(c)
                if nm in sets:
                    K.m._add_elements(sets[nm], ", ".join(ips))


def shpass(K, entries, pin, queue, eng, srcs=SRC1, shadow=True, doms=DOMS, ttl=3600, pats=None):
    shw = N._smart_shadows([dict(e) for e in entries], doms, pats or {}, eng) if shadow else None
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    n0 = len(K.scripts)
    try:
        N._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=pin, queue=queue,
                            reset_mark=(N.SNI_RESET_MARK if pin else 0), learn_ttl=ttl, srcs=srcs, shadows=shw)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    res["scripts"], res["shw"] = K.scripts[n0:], shw
    return res


def setup(entries, pin, queue, eng, shadow=True, srcs=SRC1, by_cat=None, doms=DOMS, pats=None):
    K = fresh()
    r = [shpass(K, entries, pin, queue, eng, srcs=srcs, shadow=shadow, doms=doms, pats=pats) for _ in range(3)]
    claim(K, r[-1]["shw"], queue, by_cat or {"custom_al": [H], "custom_blk": [HB]})
    return K, r


SH_MODES = (("Force-DNS", False, False, "dns"), ("Hybrid SNI", True, True, "sni_user"))
for label, pin, queue, eng in SH_MODES:
    # A — Alice's exception ABOVE the everyone Block (the reproduced layout, cells Z4/Z6)
    K, r = setup([AL, BLK, CA], pin, queue, eng)
    check("%s: a per-person name inside an everyone name makes a shadow" % label, bool(r[0]["shw"]), r[0]["shw"])
    check("%s: …and every pass runs without an error or a refusal" % label, not any(x["errors"] for x in r) and not K.refused,
          ([x["errors"] for x in r], K.refused[:1]))
    check("%s: …pass 3 changes nothing" % label, r[2]["changed"] == 0 and not r[2]["scripts"], r[2]["scripts"][:1])
    v = walk(K, "wg0", OTHER, H)
    check("%s: Bob (not chosen) → Alice's host: the everyone Block still drops it" % label, v["verdict"] == "drop", v)
    v = walk(K, "wg0", CHOSEN, H)
    check("%s: Alice → her host: her Direct exception" % label, v["verdict"] == "accept" and v["mark"] == 0 and "sr0" in v["via"], v)
    v = walk(K, "wg1", CHOSEN, H)
    check("%s: Alice's ADDRESS from another device: blocked (it is not her)" % label, v["verdict"] == "drop", v)
    check("%s: the Block's own host drops for both" % label,
          walk(K, "wg0", OTHER, HB)["verdict"] == walk(K, "wg0", CHOSEN, HB)["verdict"] == "drop")
    check("%s: an unrelated destination takes the catch-all" % label, walk(K, "wg0", OTHER, "8.8.8.8")["mark"] == 7000)
    Kc, _rc = setup([AL, BLK, CA], pin, queue, eng, shadow=False)
    v = walk(Kc, "wg0", OTHER, H)
    check("%s: CONTROL without shadows — Bob walks past the Block (the leak this closes)" % label,
          v["verdict"] == "accept" and v["mark"] == 7000, v)
    # B — the same exception BELOW the Block: most specific still wins for Alice, the Block for everyone else
    K, r = setup([BLK, AL, CA], pin, queue, eng)
    check("%s: exception below the Block — Bob is blocked" % label, walk(K, "wg0", OTHER, H)["verdict"] == "drop")
    v = walk(K, "wg0", CHOSEN, H)
    check("%s: …and Alice still gets her more specific Direct" % label, v["verdict"] == "accept" and v["mark"] == 0, v)
    # C — both rules for everyone on ONE subnet: "most specific wins" is the rule and nothing changes
    K, r = setup([BLK, ALL_, CA], pin, queue, eng)
    everything = " ".join(" ".join(c) for c in K.calls) + "".join(K.scripts)
    check("%s: everyone-rules on one subnet make no shadow (no set, no rule)" % label,
          r[0]["shw"] == {} and "sw_" not in everything, (r[0]["shw"], everything.count("sw_")))
    v = walk(K, "wg0", OTHER, H)
    check("%s: …and the more specific everyone-rule still wins (Direct)" % label, v["verdict"] == "accept" and v["mark"] == 0, v)
    # D — the broader rule is itself per-person: a device in both selections keeps the claimer, the others the Block
    W2S = {W1: [["wg0", CHOSEN + "/32"]], W2: [["wg0", W2DEV + "/32"], ["wg0", CHOSEN + "/32"]]}
    K, r = setup([dict(BLK, src=W2), AL, CA], pin, queue, eng, srcs=W2S)
    check("%s: a per-person Block keeps the host for its own device the claimer does not choose" % label,
          walk(K, "wg0", W2DEV, H)["verdict"] == "drop", walk(K, "wg0", W2DEV, H))
    v = walk(K, "wg0", CHOSEN, H)
    check("%s: …and a device in both selections gets the more specific rule (Direct)" % label,
          v["verdict"] == "accept" and v["mark"] == 0 and "sr1" in v["via"], v)
    check("%s: …and a device in neither takes the catch-all" % label, walk(K, "wg0", OTHER, H)["mark"] == 7000)
    # E — another interface's everyone-rule (the 1.8.7 leak, cell X3) — and the claimer's own interface is left alone
    K, r = setup([BLK, dict(ALL_, subnet=S9), CA], pin, queue, eng)
    check("%s: an everyone-rule on another interface no longer takes the host from this one's Block" % label,
          walk(K, "wg0", OTHER, H)["verdict"] == "drop")
    v = walk(K, "wg9", "10.28.0.5", H)
    check("%s: …and that interface still routes it by its own rule (Direct)" % label, v["verdict"] == "accept" and v["mark"] == 0, v)
    K, r = setup([BLK, ALL_, dict(BLK, subnet=S9), CA], pin, queue, eng)
    v = walk(K, "wg0", OTHER, H)
    check("%s: where the claimer has an everyone-rule on the subnet, most specific still wins there" % label,
          v["verdict"] == "accept" and v["mark"] == 0, v)
    check("%s: …while the other interface, which has only the Block, blocks" % label,
          walk(K, "wg9", "10.28.0.5", H)["verdict"] == "drop")
    # F — the node does not report a shadow set as a destination
    K, r = setup([AL, BLK, CA], pin, queue, eng)
    have = set(((K.m.tables.get(T) or {}).get("sets") or {}))
    N._LOOP["n"] += 1
    rep = set(N.smart_status().get("sets") or {})
    check("%s: the table holds the shadow sets, the report leaves them out" % label,
          any(s.startswith("cat_sw_") for s in have) and not any("_sw_" in s for s in rep), (sorted(have), sorted(rep)))
    check("%s: …and a per-person source set is not reported as a destination either" % label,
          any(s.startswith("src_") for s in have) and not any(s.startswith("src_") for s in rep), (sorted(have), sorted(rep)))
    # G — rules gone: the shadow sets go with them, and nothing is refused on the way (smart_status above asked the model a
    # `list chain` it does not answer — that is the harness, so only this step's own refusals count)
    n_ref = len(K.refused)
    for _ in range(3):
        shpass(K, [dict(ALL_), BLK, CA], pin, queue, eng)
    check("%s: shadows no longer wanted are reaped" % label,
          not [s for s in ((K.m.tables.get(T) or {}).get("sets") or {}) if "_sw_" in s] and not K.refused[n_ref:],
          (sorted((K.m.tables.get(T) or {}).get("sets") or {}), K.refused[n_ref:][:1]))

    # H — TWO broader names contain alice's (review of the fix, finding 1): the claimed host goes where the ENGINE would put
    # it without her rule — the more specific container — whatever the rule order. Both orders, both outcomes.
    ZD = dict(DOMS)
    ZP = {"zone": {"custom_z": ["example"]}}
    ZEX = {"subnet": S, "category": "custom_z", "action": "exit", "via_iface": "swg_q", "table": 7001}      # everyone *.example → Exit
    K, r = setup([ZEX, BLK, AL, CA], pin, queue, eng, doms=ZD, pats=ZP)
    v = walk(K, "wg0", OTHER, H)
    check("%s: `*.example` Exit above `h2.example` Block — Bob is still blocked (the site beats the zone, as without alice)" % label,
          v["verdict"] == "drop", v)
    check("%s: …and alice still gets her Direct" % label, walk(K, "wg0", CHOSEN, H)["mark"] == 0 and walk(K, "wg0", CHOSEN, H)["verdict"] == "accept")
    ZBK = dict(ZEX, action="block"); ZBK.pop("table"); ZBK.pop("via_iface")
    HEX = {"subnet": S, "category": "custom_blk", "action": "exit", "via_iface": "swg_q", "table": 7001}   # everyone h2.example → Exit
    K, r = setup([ZBK, HEX, AL, CA], pin, queue, eng, doms=ZD, pats=ZP)
    v = walk(K, "wg0", OTHER, H)
    check("%s: `*.example` Block above `h2.example` Exit — Bob leaves by the Exit (as without alice)" % label,
          v["verdict"] == "accept" and v["mark"] == 7001, v)
    # I — nested selections: carol's `x.sh.h2.example` inside alice's `sh.h2.example` inside everyone's `h2.example` Block
    W3, CAROL, HX = "c0c1c2c3c4c5", "10.8.0.8", "192.0.2.82"
    CR = {"subnet": S, "category": "custom_cr", "action": "exit", "via_iface": "swg_q", "table": 7001, "src": W3}
    NDOMS = dict(DOMS, custom_cr=["x.sh.h2.example"])
    K, r = setup([BLK, AL, CR, CA], pin, queue, eng, srcs={W1: [["wg0", CHOSEN + "/32"]], W3: [["wg0", CAROL + "/32"]]},
                 doms=NDOMS, by_cat={"custom_cr": [HX], "custom_al": [H], "custom_blk": [HB]})
    v = walk(K, "wg0", CHOSEN, HX)
    check("%s: nested — alice → carol's host takes alice's more specific Direct, not the Block" % label,
          v["verdict"] == "accept" and v["mark"] == 0, v)
    check("%s: …carol → her host leaves by her exit" % label, walk(K, "wg0", CAROL, HX)["mark"] == 7001)
    check("%s: …and Bob is blocked" % label, walk(K, "wg0", OTHER, HX)["verdict"] == "drop")
    # J — the blocked metric counts a block list's shadow drops like the block list's own
    BKU = dict(BLK, category="blku_x")
    K, r = setup([AL, BKU, CA], pin, queue, eng, doms={"blku_x": ["h2.example"], "custom_al": ["sh.h2.example"]},
                 by_cat={"custom_al": [H]})
    walk(K, "wg0", OTHER, H); walk(K, "wg0", OTHER, H)
    N._LOOP["n"] += 1
    ba = N._block_activity().get(S) or {}
    check("%s: two of Bob's packets dropped by a block list's shadow count as blocked" % label, ba.get("blocked") == 2, ba)

# K — a pattern that only partly overlaps (Hybrid SNI): the shadow is kept, so the hosts the pattern does not match still land
# on the containing rule for the devices alice does not reach (dropping it would send them all to "Everything else")
PK = {"first": {"custom_m": ["mail"]}, "zone": {"custom_z": ["com"]}}
MEX = {"subnet": S, "category": "custom_m", "action": "exit", "via_iface": "swg_q", "table": 7001}
ZCB = {"subnet": S, "category": "custom_z", "action": "block"}
K, r = setup([MEX, ZCB, dict(AL, category="custom_g"), CA], True, True, "sni_user", doms={"custom_g": ["google.com"]}, pats=PK,
             by_cat={"custom_g": ["192.0.2.90"]})
check("Hybrid SNI: `mail.*` partly overlaps alice's `google.com` — the `*.com` shadow is kept (Bob's www.google.com stays blocked)",
      walk(K, "wg0", OTHER, "192.0.2.90")["verdict"] == "drop", walk(K, "wg0", OTHER, "192.0.2.90"))

K, r = setup([AL, BLK, CA], True, True, "sni_user")
rt = shpass(K, [AL, BLK, CA], True, True, "sni_user", ttl=120)
_shl = [s for s in (K.m.tables.get(T) or {}).get("sets", {}) if s.startswith("catl_sw_")]
check("Hybrid SNI: a learned-set TTL change lands with shadow sets present, and they take the new TTL",
      not rt["errors"] and _shl and all(K.m.tables[T]["sets"][s]["timeout"] == 120 for s in _shl), (rt["errors"], _shl))
check("Kernel SNI and IP-only make no shadow (xt_string learns per subnet, in rule order)",
      N._smart_shadows([AL, BLK], DOMS, {}, "sni_kernel") == {} and N._smart_shadows([AL, BLK], DOMS, {}, "none") == {})
check("a name that only PARTLY overlaps a pattern makes no shadow (`mail.google.com` against `mail.*` would hand over "
      "x.mail.google.com, which `mail.*` does not name)",
      N._smart_shadows([dict(AL, category="custom_g"), dict(BLK, category="custom_m")], {"custom_g": ["mail.google.com"]},
                       {"first": {"custom_m": ["mail"]}}, "sni_user") == {})
_ks = N._smart_shadows([AL, dict(BLK, category="custom_z"), dict(BLK, category="custom_c")], {"custom_al": ["sh.h2.example"]},
                       {"zone": {"custom_z": ["example"]}, "contains": {"custom_c": ["h2.ex"]}}, "sni_user")
check("an empty operand contains nothing (swg-sni's index drops it — an empty `contains` would claim every name)",
      N._smart_shadows([AL, dict(BLK, category="custom_e")], {"custom_al": ["sh.h2.example"]}, {"contains": {"custom_e": [""]}},
                       "sni_user") == {})
check("an entry the chain drops (a selection id that is not 12 hex) makes no shadow either",
      N._smart_shadows([dict(AL, src="../x"), BLK], DOMS, {}, "dns") == {})
check("Hybrid SNI: a name inside a zone and inside a contains-pattern shadows both",
      sorted((_ks.get("by_target") or {})) == ["custom_c", "custom_z"], _ks)
check("Force-DNS takes only the kinds dnsmasq runs (the contains-pattern makes no shadow there)",
      sorted((N._smart_shadows([AL, dict(BLK, category="custom_z"), dict(BLK, category="custom_c")], {"custom_al": ["sh.h2.example"]},
                                {"zone": {"custom_z": ["example"]}, "contains": {"custom_c": ["h2.ex"]}}, "dns").get("by_target") or {}))
      == ["custom_z"])

# ── 7b. pin mode (Hybrid / Kernel SNI): a Block below an Exit or a Direct ─────────────────────────────────────────────────────
# The 1.8.7 node let an Exit above an overlapping Block keep the SYN and then dropped every packet after it (rig BHxsni/BHxks).
# A Block still meets EVERY packet — swg-sni's learning lands a few ms after its first hit, and a Block added later must cut
# running flows — so only a destination ALSO in a set above it, for the same devices, is let through.
print("\n[pin mode: a Block below an Exit or a Direct]")
D5N, BLKN = "192.0.2.81", "192.0.2.80"
PX = {"subnet": S, "category": "custom_px", "action": "exit", "via_iface": "swg_q", "table": 7001}
PD = {"subnet": S, "category": "custom_pd", "action": "direct"}
PB = {"subnet": S, "category": "custom_pb", "action": "block"}
PR = dict(PX, category="custom_pr", src=W1)
PDEST = {"custom_px": [D5N + "/32"], "custom_pd": [D5N + "/32"], "custom_pr": [D5N + "/32"], "custom_pb": ["192.0.2.0/24"]}


def pb_setup(entries, pin, queue):
    K = fresh()
    for _ in range(3):
        npass(K, entries, pin, queue)
    for c, cidrs in PDEST.items():
        if N._smart_setname(c) in ((K.m.tables.get(T) or {}).get("sets") or {}):
            K.load_set(T, N._smart_setname(c), cidrs)
    return K


def pk(K, src, dst, **kw):
    return K.m.packet(T, "wg0", src, dst, **kw)


for label, pin, queue in MODES:
    K = pb_setup([PX, PB, CA], pin, queue)
    v1 = pk(K, OTHER, D5N)
    check("%s: Exit above an overlapping Block — the first packet leaves by the Exit (7001)" % label, v1["mark"] == 7001, v1)
    v2 = pk(K, OTHER, D5N, ct="established", ctmark=7001, dport=80)
    check("%s: …and the packets after it are not dropped by the Block below" % label, v2["verdict"] == "accept" and v2["mark"] == 7001, v2)
    check("%s: …while the Block alone still stops a connection at its first packet" % label, pk(K, OTHER, BLKN)["verdict"] == "drop")
    v3 = pk(K, OTHER, BLKN, ct="established", ctmark=7000, dport=80)
    check("%s: …AND a running flow to the Block's own destination is still cut (a Block added mid-flow cuts it)" % label,
          v3["verdict"] == "drop", v3)
    if queue:
        v4 = pk(K, OTHER, D5N, ct="established", ctmark=7001, dport=443, ctpackets=3)
        check("%s: an exempted connection's first packets still go to swg-sni (the queue), as the base chain's last rule would send them" % label,
              v4["verdict"] == "queue", v4)
    K = pb_setup([PD, PB, CA], pin, queue)
    v2 = pk(K, OTHER, D5N, ct="established", dport=80)
    check("%s: Direct above an overlapping Block — the packets after the first go Direct too" % label, v2["verdict"] == "accept" and v2["mark"] == 0, v2)
    K = pb_setup([PR, PB, CA], pin, queue)
    v2 = pk(K, CHOSEN, D5N, ct="established", ctmark=7001, dport=80)
    check("%s: a per-person Exit row above an everyone Block keeps its connection" % label, v2["verdict"] == "accept" and v2["mark"] == 7001, v2)
    v2 = pk(K, OTHER, D5N, ct="established", ctmark=7000, dport=80)
    check("%s: …and a device outside that row is not let through the Block by it (first packet or later)" % label,
          pk(K, OTHER, D5N)["verdict"] == "drop" and v2["verdict"] == "drop", v2)
    K = pb_setup([PX, dict(PB, src=W1), CA], pin, queue)
    v2 = pk(K, CHOSEN, D5N, ct="established", ctmark=7001, dport=80)
    check("%s: an everyone Exit above a per-person Block row: the chosen device's connection is not cut by its row" % label,
          v2["verdict"] == "accept" and v2["mark"] == 7001, v2)
    # the swg-sni race (review of this fix, finding 1): a connection whose SYN beat the learning is cut once the address lands
    for setname in (["catl_custom_pb", "cat_custom_pb"] if queue else ["cat_custom_pb"]):
        K = pb_setup([PB, CA], pin, queue)
        s = K.m.tables[T]["sets"][setname]; s["els"] = set()
        syn = pk(K, OTHER, "198.18.0.77")                      # in no set yet
        K.m._add_elements(s, "198.18.0.77")                    # swg-sni's flusher (or a list refresh) lands the address
        late = pk(K, OTHER, "198.18.0.77", ct="established", ctmark=syn["mark"], dport=443, ctpackets=40)
        check("%s: a connection that passed before the Block learned its address (%s) is cut by the next packet" % (label, setname),
              syn["verdict"] == "accept" and late["verdict"] == "drop", (syn, late))
K = pb_setup([PX, PB, CA], True, True)
rt = npass(K, [PX, PB, CA], True, True, ttl=120)
check("Hybrid SNI: a learned-set TTL change lands while a Block chain matches the learned sets",
      not rt["errors"] and K.m.tables.get(T, {}).get("sets", {}).get("catl_custom_px", {}).get("timeout") == 120, rt["errors"] or K.refused[-1:])

# A shadow's exemption keeps its "not these devices": Alice's own name sits BELOW the Block, so for her the Block above it wins,
# while Bob keeps the everyone Exit's connection through the shadow (review of this fix, F2)
XD = {"custom_x": ["h2.example"], "custom_al": ["sh.h2.example"]}
XEX = dict(PX, category="custom_x")
K = fresh()
r = [shpass(K, [XEX, PB, AL, CA], True, True, "sni_user", doms=XD) for _ in range(3)]
K.load_set(T, "cat_custom_pb", ["192.0.2.0/24"])
claim(K, r[-1]["shw"], True, {"custom_al": [D5N]})
check("Hybrid SNI: an everyone Exit above a Block has a shadow for Alice's name below the Block (the case under test)",
      bool(((r[-1]["shw"] or {}).get("by_target") or {}).get("custom_x")) and "pb1" in K.m.tables[T]["chains"], r[-1]["shw"])
v = pk(K, CHOSEN, D5N)
check("Hybrid SNI: Alice → her name, her Direct row BELOW the Block — the Block above it drops her (the shadow's exemption is not hers)",
      v["verdict"] == "drop", v)
v1, v2 = pk(K, OTHER, D5N), pk(K, OTHER, D5N, ct="established", ctmark=7001, dport=80)
check("Hybrid SNI: …while Bob leaves by the everyone Exit through its shadow, and keeps the connection past the Block",
      v1["mark"] == 7001 and v2["verdict"] == "accept" and v2["mark"] == 7001, (v1, v2))
# The exemption covers what swg-sni LEARNED for the Exit, not only its static set: a hostname Exit is the usual Hybrid rule (F3)
K = pb_setup([PX, PB, CA], True, True)
K.m.tables[T]["sets"]["cat_custom_px"]["els"] = set()
K.m._add_elements(K.m.tables[T]["sets"]["catl_custom_px"], D5N)
v1, v2 = pk(K, OTHER, D5N), pk(K, OTHER, D5N, ct="established", ctmark=7001, dport=80)
check("Hybrid SNI: an Exit whose address swg-sni learned (catl_ only) keeps its connection past the Block below",
      v1["mark"] == 7001 and v2["verdict"] == "accept" and v2["mark"] == 7001, (v1, v2))
# The swg-sni rule inside the Block chain queues only what the chain would let through — a queued packet is accepted by
# swg-sni, so a wider rule lets a connection's first packets past the Block (F4). Inside that window: packet 3, port 443.
K = pb_setup([PR, PB, CA], True, True)
v = pk(K, OTHER, D5N, ct="established", ctmark=7000, dport=443, ctpackets=3)
check("Hybrid SNI: a device outside the per-person Exit row, early in a 443 connection to its address — dropped, not queued past the Block",
      v["verdict"] == "drop", v)
K = pb_setup([PX, PB, CA], True, True)
v = pk(K, OTHER, BLKN, ct="established", ctmark=7000, dport=443, ctpackets=3)
check("Hybrid SNI: early in a 443 connection to the Block's own address (one that beat the learning) — dropped, not queued",
      v["verdict"] == "drop", v)
# A Block chain no longer wanted is deleted, so the Exit sets it matched can be reaped when their rule goes (F5)
for label, pin, queue in MODES[1:]:
    K = fresh()
    for ents in ([PX, PB, CA], [PX, PB, CA], [PX, CA], [PX, CA]):
        npass(K, ents, pin, queue)
    left = sorted(c for c in K.m.tables[T]["chains"] if c.startswith("pb"))
    for _ in range(2):
        rr = npass(K, [CA], pin, queue)
    sets_ = sorted(s for s in K.m.tables[T]["sets"] if s.endswith("custom_px"))
    check("%s: the Block removed — its chain goes, and then the Exit's sets go with the Exit rule" % label,
          not left and not sets_ and not rr["errors"], (left, sets_, rr["errors"]))
for label, pin, queue in MODES:
    for ents, tag in (([PX, PB, CA], "a Block below an Exit"), ([PB, PX, CA], "a Block ABOVE the Exit")):
        K = fresh()
        npass(K, ents, pin, queue)
        spec_ = [e for e in ents if e["category"] != "all"]
        w4 = [(e["subnet"], e["category"], e.get("action", "exit"), e.get("table")) for e in spec_ + [CA]]
        rst = N.SNI_RESET_MARK if pin else 0
        old = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(w4) + "|v6:" + "" + "|rst:" + str(rst)
                            + ("|lttl:3600" if queue else "") + "|s9").encode()).hexdigest()[:16]
        have = open(os.path.join(N.GEO_DIR, ".smart-sig")).read().strip() if os.path.exists(os.path.join(N.GEO_DIR, ".smart-sig")) else ""
        changes = pin and tag == "a Block below an Exit"
        check("%s, %s: %s" % (label, tag, "the node rebuilds once (the chain reaches the signature)" if changes
                              else "signed exactly as HEAD did (nothing new is built)"), (have != old) if changes else (have == old), (have, old))

# ── 8. the engines are handed the shadow categories, and dnsmasq rebuilds when only they change ────────────────────────────
print("\n[shadow sets reach the engines]")
_dq, _sq = [], []
N._ensure_smart_dnsmasq = lambda domains, smart_e, res, unchanged=False, zones=None, nets=(): _dq.append((dict(domains), unchanged))
N._ensure_sni_router = lambda domains, subnets, res, learn_ttl=3600, map_key=None, patterns=None: _sq.append(dict(domains or {}))


def rc(entries, mode):
    smart = {"entries": [dict(e) for e in entries], "categories": sorted({e["category"] for e in entries}), "mode": mode,
             "srcs": SRC1, "domains": DOMS}
    try:
        N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
        return ""
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


K = fresh()
N.run = lambda args, input_text=None, timeout=20: K(args, input_text, timeout) if args and args[0] == "nft" else \
    __import__("subprocess").CompletedProcess(args, 0, "", "")
N._DOMTIER_CACHE.pop("v", None)
errs = [rc([AL, BLK, CA], "forcedns") for _ in range(2)] + [rc([ALL_, BLK, CA], "forcedns")]
check("Force-DNS: reconcile_cascade runs with a shadow", not any(errs), errs)
_sw = [k for k in (_dq[0][0] if _dq else {}) if k.startswith("sw_")]
check("Force-DNS: dnsmasq gets the shadow category, holding Alice's name beside hers",
      len(_sw) == 1 and _dq[0][0][_sw[0]] == ["sh.h2.example"] and _dq[0][0]["custom_al"] == ["sh.h2.example"], _dq[:1])
check("Force-DNS: an unchanged pass tells dnsmasq it is unchanged", len(_dq) >= 2 and _dq[1][1] is True, [u for _d, u in _dq])
check("Force-DNS: the rule turned into one for everyone (same names, same dom_sig) — dnsmasq rebuilds without the shadow",
      len(_dq) >= 3 and _dq[2][1] is False and not any(k.startswith("sw_") for k in _dq[2][0]), [(sorted(d), u) for d, u in _dq])
K = fresh()
N.run = lambda args, input_text=None, timeout=20: K(args, input_text, timeout) if args and args[0] == "nft" else \
    __import__("subprocess").CompletedProcess(args, 0, "", "")
e_ = rc([AL, BLK, CA], "sni")
check("Hybrid SNI: swg-sni's map carries the shadow category beside Alice's",
      not e_ and _sq and any(k.startswith("sw_") and v == ["sh.h2.example"] for k, v in _sq[-1].items()), (e_, _sq[-1:]))

shutil.rmtree(STATE, ignore_errors=True)
print()
if PLANT:
    print("PLANT %s — %d check(s) red: %s" % (PLANT, len(FAILS), FAILS[:4]))
    sys.exit(0 if FAILS else 1)
print(("FAILED (%d): " % len(FAILS) + ", ".join(FAILS)) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
