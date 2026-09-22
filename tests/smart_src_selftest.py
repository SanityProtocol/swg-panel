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
  · the interim Kernel-SNI gate — no `src` entry reaches `_ensure_smart_xtstring`, whose `-s <subnet>` would widen it;
  · the three positional readers of the want-tuple — driven in all three engine shapes (kernel/Force-DNS,
    Hybrid SNI with the queue, Kernel SNI), because one of them runs only with the queue on.

Hermetic: no nft, no ip, no root. Run: python3 tests/smart_src_selftest.py   (0 = pass)
  --plant a|b|c|d|e|f|g1|g2|g3|h   plant one defect and expect RED on its own check (exit 0 when caught):
     a  the source set is never created, so the row's jump names a set that is not there
     b  a row chain's rules end in `return`
     c  the learned-set TTL swap forgets the row chains
     d  the signature gains a marker for everyone, `src` or not (every node's chain rebuilds on upgrade)
     e  the chain signature signs the set MEMBERS (a member change rebuilds the chain)
     f  the Kernel-SNI filter is removed
     g1/g2/g3  one positional reader of the want-tuple left at four names (expect_pre · the emit loop · `_routed_cats`)
     h  the drift gate forgets that a row emits prerouting rules (an all-Direct per-person chain emptied from outside stays empty)
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
    "c": ('                for _c in ("catcount", "catany", "forward") + tuple(sorted(c for c in re.findall(r"chain (\\S+) {", body) if re.fullmatch(r"sr\\d+", c))):',
          '                for _c in ("catcount", "catany", "forward"):'),
    "d": ('''("|lttl:" + str(learn_ttl) if queue else "") + "|s9").encode()).hexdigest()[:16]''',
          '''("|lttl:" + str(learn_ttl) if queue else "") + "|s9|src").encode()).hexdigest()[:16]'''),
    "e": ('''    sig = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(want) +''',
          '''    sig = hashlib.sha1((("pin;" if pin else "") + ("q;" if queue else "") + json.dumps(want) + json.dumps(want_src) +'''),
    "f": ('''        _built = _ensure_smart_xtstring([e for e in smart_exit if not e.get("src")], domains,''',
          '''        _built = _ensure_smart_xtstring(smart_exit, domains,'''),
    "g1": ('''    expect_pre = pin or any(w[2] != "direct" or len(w) > 4 for w in want)''',
           '''    expect_pre = pin or any(a != "direct" for (_, _, a, _) in want)'''),
    "g2": ('''            S, cat, act, T = w[:4]
            if len(w) > 4:''', '''            S, cat, act, T = w
            if len(w) > 4:'''),
    "h": ('''    expect_pre = pin or any(w[2] != "direct" or len(w) > 4 for w in want)''',
          '''    expect_pre = pin or any(w[2] != "direct" for w in want)'''),
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
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(STATE, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))

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

# ── 6. the interim Kernel-SNI gate (plan §6.3): no `src` entry reaches xt_string ───────────────────────────────────────────
print("\n[Kernel SNI: the interim gate]")
_seen = []
N._ensure_smart_xtstring = lambda host_entries, *a, **k: (_seen.append([dict(e) for e in host_entries]), [])[1]
N._kernel_sni_ok = lambda: True
N._ensure_sni_router = lambda *a, **k: None
N.reconcile_catk_chain = lambda *a, **k: None
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
check("reconcile_cascade runs a Kernel-SNI node with per-person entries", not _err, _err)
check("xt_string was asked to build (the everyone-rules still go there)", bool(_seen) and any(_seen), _seen)
check("…but no entry carrying `src` reached it (its `-s <subnet>` would widen the row to everyone)",
      bool(_seen) and not any(e.get("src") for call in _seen for e in call), [e for c in _seen for e in c if e.get("src")])
check("the node reports the capability the panel withholds on (`src: 1`)", N.smart_status().get("src") == 1, N.smart_status())

shutil.rmtree(STATE, ignore_errors=True)
print()
if PLANT:
    print("PLANT %s — %d check(s) red: %s" % (PLANT, len(FAILS), FAILS[:4]))
    sys.exit(0 if FAILS else 1)
print(("FAILED (%d): " % len(FAILS) + ", ".join(FAILS)) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
