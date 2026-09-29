#!/usr/bin/env python3
"""Self-test — Force-DNS never drops an address a name ALLOWED on the node resolved to (docs/KSNI-HOSTNAMES-PLAN.md D2).

Force-DNS blocks by DNS: dnsmasq puts every answer for a blocked name into the Block's set and the chain drops the set. The
tracker `googleads.googleapis.com` answers with the same Google front ends as `youtubei.googleapis.com`, so resolving the
tracker once took every front end of that pool away from the interface until the table was rebuilt (reproduced on msk-main,
2026-09-28: 172.217.112–119.4 in `cat_blku_host_…`, youtubei timing out). Force-DNS cannot see which name a connection is
for — so it now spares what an allowed name resolved to: dnsmasq fills `dnsok` with the answer of every name that is not a
blocked one anywhere on the node, and a Block drops a NAME's address only where `dnsok` does not hold it. A Block category
with a static half (a list's IP addresses) keeps that half whole: dnsmasq also fills its names into `catd_<cat>`, and the
static half is `cat_` minus `catd_`.

  [1] the chain (real `_ensure_smart_nft`, nft transaction model): the union's drop carries `!= @dnsok`; a Block with both
      halves drops `@cat_ != @catd_` unconditionally and `@catd_ != @dnsok`; exits are untouched; `dnsok` is made with its size
  [2] packets: the tracker's address that an allowed name also resolved to PASSES (the collateral is gone); an address only
      the tracker resolved to is DROPPED (the negative control — a tracker's exclusive address stays blocked); a list's
      static address is dropped even where an allowed name resolved to it; its names' shared address passes
  [3] a Block's shadow category drops with `!= @dnsok` too
  [4] dnsmasq (real `_ensure_smart_dnsmasq`, conf written to a temp file): the catch-all `nftset=/#/…#dnsok`; `dnsok` on a
      routing key's directive; NOT on a key a Block uses; `catd_` beside `cat_` on the split category's keys
  [5] a node with no Block: no `dnsok`, no catch-all, the conf byte-identical and the chain signed as before
  [6] `dnsok` near its size is flushed, and dnsmasq's cache is cleared so it refills
  [7] the reconcile: a Block added where no name changed still rewrites the dnsmasq conf

Hermetic. Run: python3 tests/forcedns_spare_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     nospare    a Block drops its whole set again (no `!= @dnsok`)                           [2]
     nostatic   the static half is spared too (no `catd_` split)                            [2]
     noshadow   a Block's shadow drops without `!= @dnsok`                                  [3]
     nocatch    no catch-all directive (an unrouted allowed name is never spared)           [4]
     okblk      `dnsok` rides on a Block's own keys (the tracker spares itself)              [4]
     noflush    `dnsok` is never flushed                                                     [6]
     nochange   a Block added with no name change leaves dnsmasq "unchanged"                 [7]
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
SECTION = [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


PLANTS = {
    "nospare": ("[2]", '        if c in dns_blk:                                       # Force-DNS, names only: what an allowed name resolved to is spared\n'
                       '            return [(_smart_setname(c), ["ip", "daddr", "!=", "@dnsok"])]',
                '        if False:\n            return []'),
    "nostatic": ("[2]", "        catd = {c for c in dns_blk if c in (static_cats or ())}", "        catd = set()"),
    "noshadow": ("[3]", '*(["ip", "daddr", "!=", "@dnsok"] if sh in dns_blk else []),   # Force-DNS (D2)', "   # Force-DNS (D2)"),
    "nocatch": ("[4]", '        conf.append("nftset=/#/4#inet#" + SMART_NFT_TABLE + "#dnsok")', "        pass"),
    "okblk": ("[4]", "            if not (sns & _blk_sets):\n                sns.add(\"dnsok\")", "            if True:\n                sns.add(\"dnsok\")"),
    "noflush": ("[6]", "            if _t[\"counts\"].get(\"dnsok\", 0) >= DNSOK_MAX * 9 // 10:", "            if False:"),
    "nochange": ("[7]", "        if _SHADOW.get(\"spare\") != _DNS_SPARE[\"v\"]:", "        if False:"),
}
TMP = tempfile.mkdtemp(prefix="dns-spare-")
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
_l = importlib.machinery.SourceFileLoader("swgnoded_spare", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_spare", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = os.path.join(TMP, "geo")
T = N.SMART_NFT_TABLE

S0, S1 = "10.188.1.0/24", "10.8.0.0/24"
UNION = "blku:host:4fe45fc4b8fa"
ENTRIES = [
    {"subnet": S0, "category": UNION, "action": "block"},
    {"subnet": S0, "category": "custom_dual", "action": "block"},                            # names AND an address
    {"subnet": S0, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
    {"subnet": S0, "category": "all", "action": "direct"},
    {"subnet": S1, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
    {"subnet": S1, "category": "all", "action": "direct"},
]
DOMAINS = {UNION: ["googleads.googleapis.com", "g.doubleclick.net"], "custom_dual": ["dual.example"],
           "google": ["googleapis.com"]}
STATIC = {"custom_dual"}
SHARED, EXCL, DUAL_STATIC, DUAL_NAME = "172.217.114.4", "172.217.200.9", "198.51.100.7", "203.0.113.20"


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    K = SmartKernel()
    N.run = K
    N._DNSMASQ_SETS_EMPTIED["v"] = False
    return K


def npass(K, entries, shadows=None, spare=True):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    try:
        N._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=False, queue=False,
                            name_cats=set(DOMAINS), spare_dns=spare, static_cats=STATIC, shadows=shadows)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    return res


def rules(K, chain="prerouting"):
    return [r["text"] for r in ((K.m.tables.get(T) or {}).get("chains", {}).get(chain) or {}).get("rules", [])]


def sets(K):
    return (K.m.tables.get(T) or {}).get("sets") or {}


def put(K, name, *ips):
    if name in sets(K):                                         # a set the node did not make stays empty — its check says so
        K.m._add_elements(sets(K)[name], ", ".join(ips))


SECTION[0] = "[1]"
print("\n[1] the chain on Force-DNS")
K = fresh()
r = [npass(K, ENTRIES) for _ in range(3)]
check("three passes, no error, nothing refused", not any(x["errors"] for x in r) and not K.refused, ([x["errors"] for x in r], K.refused[:2]))
pre = rules(K)
check("the union's drop spares `dnsok` (and still counts)",
      any("@cat_blku_host_4fe45fc4b8fa ip daddr != @dnsok counter drop" in t for t in pre), [t for t in pre if "blku" in t])
check("the Block with both halves: the static half whole (`cat_` minus `catd_`) …",
      any("@cat_custom_dual ip daddr != @catd_custom_dual drop" in t for t in pre), [t for t in pre if "dual" in t])
check("…and its names' half spares `dnsok`", any("@catd_custom_dual ip daddr != @dnsok drop" in t for t in pre), [t for t in pre if "dual" in t])
check("the exit is untouched", any(t.endswith("@cat_google meta mark set 7001 return") for t in pre), [t for t in pre if "google" in t])
check("`dnsok` exists with its size, `catd_custom_dual` exists", "dnsok" in sets(K) and "catd_custom_dual" in sets(K), sorted(sets(K)))
check("a third pass changes nothing", r[2]["changed"] == 0, r[2])

SECTION[0] = "[2]"
print("\n[2] packets")
put(K, "cat_blku_host_4fe45fc4b8fa", SHARED, EXCL)             # the tracker resolved to both
put(K, "dnsok", SHARED)                                         # youtubei resolved to the shared one
put(K, "cat_custom_dual", DUAL_STATIC, DUAL_NAME)               # the static half + what dual.example resolved to (dnsmasq
put(K, "catd_custom_dual", DUAL_NAME)                           # fills both sets for a split category)
put(K, "dnsok", DUAL_STATIC)                                    # an allowed name happens to resolve to the listed address too
v = K.m.packet(T, "wg0", "10.188.1.9", SHARED)
check("the tracker's address that an ALLOWED name also resolved to passes — the collateral is gone", v["verdict"] != "drop", v)
v = K.m.packet(T, "wg0", "10.188.1.9", EXCL)
check("an address only the tracker resolved to is dropped (negative control)", v["verdict"] == "drop", v)
v = K.m.packet(T, "wg0", "10.188.1.9", DUAL_STATIC)
check("a list's STATIC address is dropped even where an allowed name resolved to it", v["verdict"] == "drop", v)
put(K, "dnsok", DUAL_NAME)
v = K.m.packet(T, "wg0", "10.188.1.9", DUAL_NAME)
check("its names' address that an allowed name shares passes", v["verdict"] != "drop", v)
v = K.m.packet(T, "wg0", "10.8.0.9", EXCL)
check("another interface without the filter never meets the drop", v["verdict"] != "drop", v)

SECTION[0] = "[3]"
print("\n[3] a Block's shadow")
SH = {"by_target": {UNION: [("sw_0123456789", "custom_al", [])]}, "domains": {"sw_0123456789": ["x.g.doubleclick.net"]}, "pats": {},
      "sig": "t"}
ENT3 = [{"subnet": S0, "category": "custom_al", "action": "direct", "src": "1f2e3d4c5b6a"}] + ENTRIES
K3 = fresh()
for _ in range(2):
    npass(K3, ENT3, shadows=SH)
check("the union's shadow drops with `!= @dnsok`", any("@cat_sw_0123456789" in t and "!= @dnsok" in t for t in rules(K3)),
      [t for t in rules(K3) if "sw_" in t])

SECTION[0] = "[4]"
print("\n[4] dnsmasq")
N.DNSMASQ_CONF = os.path.join(TMP, "smart-dnsmasq.conf")
N._dnsmasq_running = lambda: 0
N._dnsmasq_kill = lambda: None
N._smart_dns_redirect = lambda *a, **k: None
N.DNSMASQ_BIN = "true"


def conf(spare):
    N._DNSMASQ_BUILD["n"] = 0
    res = {"changed": 0, "errors": []}
    N.run = lambda args, **kw: subprocess.CompletedProcess(args, 0, "", "")
    with open(N.DNSMASQ_CONF, "w") as f:
        f.write("")
    N._ensure_smart_dnsmasq(DOMAINS, [{"subnet": S0}], res, spare=spare)
    return open(N.DNSMASQ_CONF).read()


K = fresh()
for _ in range(2):
    npass(K, ENTRIES)
c = conf(N._DNS_SPARE["v"])
lines = c.splitlines()
check("the catch-all: `nftset=/#/4#inet#swg_smart#dnsok`", "nftset=/#/4#inet#swg_smart#dnsok" in lines, [l for l in lines if "#/" in l])
check("`dnsok` rides on the routing key's directive", any("/googleapis.com/" in l and "#dnsok" in l for l in lines),
      [l for l in lines if "googleapis.com/" in l])
check("…and NOT on a key a Block uses", not any(("googleads.googleapis.com" in l or "g.doubleclick.net" in l) and "#dnsok" in l for l in lines),
      [l for l in lines if "googleads" in l])
check("the split category's key fills `catd_` beside `cat_`",
      any("/dual.example/" in l and "#cat_custom_dual" in l and "#catd_custom_dual" in l for l in lines), [l for l in lines if "dual" in l])

SECTION[0] = "[5]"
print("\n[5] a node with no Block is what it always was")
PLAIN = [e for e in ENTRIES if e["action"] != "block"]
K5 = fresh()
for _ in range(2):
    npass(K5, PLAIN)
check("no `dnsok`, no split, nothing handed to dnsmasq", "dnsok" not in sets(K5) and N._DNS_SPARE["v"] is None, (sorted(sets(K5)), N._DNS_SPARE["v"]))
check("the dnsmasq conf is byte-identical to one written with no spare at all", conf(N._DNS_SPARE["v"]) == conf(None))
K6 = fresh()
for _ in range(2):
    npass(K6, PLAIN, spare=False)
s_off = open(os.path.join(N.GEO_DIR, ".smart-sig")).read()
K7 = fresh()
for _ in range(2):
    npass(K7, PLAIN, spare=True)
check("…and the chain signs exactly as a node that never heard of it", open(os.path.join(N.GEO_DIR, ".smart-sig")).read() == s_off)

SECTION[0] = "[6]"
print("\n[6] `dnsok` near its size")
K = fresh()
for _ in range(2):
    npass(K, ENTRIES)
sets(K)["dnsok"]["els"] = {(None, i, i) for i in range(N.DNSOK_MAX * 9 // 10)}
N._DNSMASQ_SETS_EMPTIED["v"] = False
npass(K, ENTRIES)
check("flushed", len(sets(K)["dnsok"]["els"]) == 0, len(sets(K)["dnsok"]["els"]))
check("…and dnsmasq's cache is to be cleared, so its next answers refill it", N._DNSMASQ_SETS_EMPTIED["v"] is True)

SECTION[0] = "[7]"
print("\n[7] the reconcile: a Block added where no name changed rewrites the dnsmasq conf")
_seen = []
N._ensure_smart_dnsmasq = lambda domains, smart_e, res, unchanged=False, zones=None, nets=(), upstream=None, spare=None: \
    _seen.append((unchanged, spare))
N._dnsmasq_refill = lambda res: None
N._smart_geo_refresh = lambda *a, **k: None
N._smart_load_cidrs = lambda *a, **k: None
N._smart_domain_refresh = lambda cats, res: ({}, {})
N._panel_list_refresh = lambda *a, **k: None
N._ensure_doh_block = lambda *a, **k: None
N._ensure_mech_block = lambda *a, **k: None
N._ensure_torrent_sig = lambda *a, **k: None
N._ensure_sni_router = lambda *a, **k: None
N._ensure_smart_xtstring = lambda *a, **k: []
N.reconcile_catk_chain = lambda *a, **k: None
K = fresh()
N.run = lambda args, input_text=None, timeout=20, **kw: K(args, input_text, timeout) if args and args[0] == "nft" else \
    subprocess.CompletedProcess(args, 0, "", "")
N._DOMTIER_CACHE.pop("v", None)
BASE = [{"subnet": S0, "category": "custom_dual", "action": "exit", "via_iface": "swg_h", "table": 7001},
        {"subnet": S1, "category": "custom_dual", "action": "exit", "via_iface": "swg_h", "table": 7001}]
MORE = [{"subnet": S0, "category": "custom_dual", "action": "block"},
        {"subnet": S1, "category": "custom_dual", "action": "exit", "via_iface": "swg_h", "table": 7001}]
for ents in (BASE, BASE, MORE):
    smart = {"entries": ents, "categories": ["custom_dual"], "mode": "forcedns", "domains": {"custom_dual": ["dual.example"]}}
    try:
        N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
    except Exception as e:
        _seen.append(("raised", str(e)))
check("the second identical pass tells dnsmasq it is unchanged", len(_seen) >= 2 and _seen[1][0] is True, _seen)
check("the Block (same names, same subnets) is a changed config, and dnsmasq gets the spare", len(_seen) >= 3 and _seen[2][0] is False
      and (_seen[2][1] or {}).get("block_sets") == ["cat_custom_dual"], _seen)

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    red = [f for f in FAILS if f.split()[0] in sec.split()]
    print("plant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(red), sec)) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
