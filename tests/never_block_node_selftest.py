#!/usr/bin/env python3
"""Self-test — the Never-block list's names on the node (docs/NEVER-BLOCK-AND-PORT-RULES-PLAN.md A.3, 1.8.11 S5 A1).

The panel sends `smart.allow` (names) to Force-DNS and Hybrid SNI nodes; swg-noded takes those names out of every block
LIST (a `blku:host:` union) in the one map both name engines read, so swg-sni itself is unchanged. On the REAL programs —
swg-noded's `_never_block_adjust`, `_ensure_smart_dnsmasq` (conf to a temp file), `_ensure_smart_nft` through the nft
transaction model, and swg-sni's `Classifier` fed real ClientHello packets:

  [1] the map: a union loses an allowed name and every name under it; an allowed name a union covers through a PARENT gets
      a key of its own — in the non-union categories that would match it (its routing kept), else in the reserved category;
      a union ZONE is a parent too; a name already keyed by a rule needs nothing; names no union covers add nothing; rule
      categories never lose a name; no list (or a list that touches nothing) leaves the map as it was
  [2] dnsmasq: the parent keeps its union set; the allowed name's own key carries `dnsok` alone; with no Block to spare it
      from (D2 off) no directive is written for it; a list that touches nothing leaves the conf byte-identical
  [3] swg-sni: the reserved category is in `nolearn` only when it holds names (sni-blocks.json otherwise as before); the
      allowed name's ClientHello is not refused and nothing is learned for it, its parent's sibling still is refused, and an
      allowed name under a routed parent is still learned into the route's set
  [4] wiring: the pass runs before the domain-tier cache is filled, the list joins the signature only when set, only the
      name engines read it, and the node reports `allow`
  [5] cost: one adjustment over a 400k-name union (a re-tier, never a sync) — printed, and bounded

Hermetic. Run: python3 tests/never_block_node_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     nocut       a union keeps the allowed names                                               [1]
     nokey       an allowed name under a union parent gets no key of its own                   [1] [3]
     nolearn     the reserved category is not in swg-sni's nolearn                             [3]
     dnsempty    a key with no set is written as a directive anyway                            [2]
"""
import importlib.machinery, importlib.util, json, os, re, shutil, socket, struct, subprocess, sys, tempfile, time
os.environ["SWG_NFT_CLI_ONLY"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {
    "nocut": ('                if under(d):\n                    cut += 1\n                else:\n                    keep.append(d)',
              '                keep.append(d)'),
    "nokey": ('        for c in cats:\n            domains[c] = list(domains.get(c) or []) + [a]', '        pass'),
    "nolearn": ('| ({NEVER_BLOCK_CAT} & set(name_cats or ()))', '| set()'),
    "dnsempty": ('        if sns:                                                # a Never-block key', '        if True:  # a Never-block key'),
}
TMP = tempfile.mkdtemp(prefix="never-block-")
path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    old, new = PLANTS[PLANT]
    src = open(NODED, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    path = os.path.join(TMP, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))


def load(p, name):
    l = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NODED_STATE"] = TMP
N = load(path, "swgnoded_nb")
S = load(SNI, "swgsni_nb")
N.GEO_DIR = os.path.join(TMP, "geo")
T = N.SMART_NFT_TABLE
R = N.NEVER_BLOCK_CAT

U = "blku:host:4fe45fc4b8fa"                       # an ads/tracker list
UZ = "blku:host:0a1b2c3d4e5f"                      # a list that carries a zone (`+.xyz` → `xyz`)
ALLOW = ["allowed.net", "cdn.tracker.com", "maps.googleapis.com", "shop.xyz", "keep.example", "plain.org"]


def base():
    return {U: ["allowed.net", "sub.allowed.net", "tracker.com", "x.tracker.com", "googleapis.com", "ads.other.io"],
            UZ: ["bad.io"],
            "google": ["googleapis.com", "google.com"],
            "custom_keep": ["keep.example", "allowed.net"],          # a rule's own names: never touched
            "custom_parent": ["example"]}                            # (not a union: its names stay)


ZONES = {UZ: ["xyz", "example"]}

# ── [1] the map ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the map")
D = base()
cut = N._never_block_adjust(D, ZONES, ALLOW)
check("the union loses the allowed name and the name under it (allowed.net, sub.allowed.net)",
      "allowed.net" not in D[U] and "sub.allowed.net" not in D[U] and cut == 2, (D[U], cut))
check("…and keeps every other name, the allowed names' parents included",
      D[U] == ["tracker.com", "x.tracker.com", "googleapis.com", "ads.other.io"], D[U])
check("an allowed name under a union parent with no rule over it gets the reserved key (cdn.tracker.com)",
      "cdn.tracker.com" in (D.get(R) or []), D.get(R))
check("an allowed name under a union parent a rule also routes joins that rule's category, not the reserved one "
      "(maps.googleapis.com → google)", "maps.googleapis.com" in D["google"] and "maps.googleapis.com" not in (D.get(R) or []),
      (D["google"], D.get(R)))
check("a union ZONE is a parent too (shop.xyz under `xyz`)", "shop.xyz" in (D.get(R) or []), D.get(R))
check("a name a rule already keys needs nothing (keep.example)", D["custom_keep"] == ["keep.example", "allowed.net"]
      and "keep.example" not in (D.get(R) or []), (D["custom_keep"], D.get(R)))
check("a name no union covers adds nothing (plain.org)", not any("plain.org" in v for v in D.values()), D)
check("rule categories never lose a name", D["custom_keep"] == base()["custom_keep"] and D["custom_parent"] == ["example"])
check("the reserved category holds exactly the two names nothing else keys", sorted(D.get(R) or []) == ["cdn.tracker.com", "shop.xyz"],
      D.get(R))
D0 = base()
check("no list: the map as it was, nothing cut", N._never_block_adjust(D0, ZONES, []) == 0 and D0 == base())
D1 = base()
check("a list that touches nothing: the map as it was", N._never_block_adjust(D1, ZONES, ["plain.org"]) == 0 and D1 == base(), D1)
D2 = base()
_src = {c: v for c, v in D2.items()}
N._never_block_adjust(D2, ZONES, ALLOW)
check("a list object some cache holds is never mutated (new lists only)", _src[U] is not D2[U] and base()[U] == _src[U]
      and "maps.googleapis.com" not in _src["google"], (_src[U], _src["google"]))

# ── [2] dnsmasq ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] dnsmasq")
N.DNSMASQ_CONF = os.path.join(TMP, "smart-dnsmasq.conf")
N._dnsmasq_running = lambda: 0
N._dnsmasq_kill = lambda: None
N._smart_dns_redirect = lambda *a, **k: None
N.DNSMASQ_BIN = "true"
S0 = "10.188.1.0/24"
BLK = {"block_sets": [N._smart_setname(U), N._smart_setname(UZ)]}


def conf(domains, spare):
    N._DNSMASQ_BUILD["n"] = 0
    N.run = lambda args, **kw: subprocess.CompletedProcess(args, 0, "", "")
    with open(N.DNSMASQ_CONF, "w") as f:
        f.write("")
    N._ensure_smart_dnsmasq(domains, [{"subnet": S0}], {"changed": 0, "errors": []}, zones=ZONES, spare=spare)
    return open(N.DNSMASQ_CONF).read()


def sets_of(c, name):
    out = [l.split("/")[-1].split(",") for l in c.splitlines() if l.startswith("nftset=/") and name in l.split("/")[1:-1]]
    return [sorted(x.rsplit("#", 1)[-1] for x in s) for s in out]   # an empty-set directive reads as [""]


DA = base()
N._never_block_adjust(DA, ZONES, ALLOW)
c = conf(DA, BLK)
check("the parent keeps its union set and no dnsok (tracker.com)", sets_of(c, "tracker.com") == [[N._smart_setname(U)]],
      sets_of(c, "tracker.com"))
check("the allowed name's own key carries dnsok alone (cdn.tracker.com)", sets_of(c, "cdn.tracker.com") == [["dnsok"]],
      sets_of(c, "cdn.tracker.com"))
check("an allowed name a rule routes fills the rule's set, and dnsok (maps.googleapis.com)",
      sets_of(c, "maps.googleapis.com") == [sorted(["dnsok", N._smart_setname("google")])], sets_of(c, "maps.googleapis.com"))
check("the allowed name is in no union directive (allowed.net only under custom_keep)",
      sets_of(c, "allowed.net") == [sorted(["dnsok", N._smart_setname("custom_keep")])], sets_of(c, "allowed.net"))
check("the reserved category has no set of its own anywhere in the conf", "never" not in c.replace("never-block", ""), "")
c_nospare = conf(DA, None)
check("with no Block to spare it from (D2 off): no directive for a key with no set", not sets_of(c_nospare, "cdn.tracker.com")
      and not re.search(r"^nftset=/[^#]*/$", c_nospare, re.M), sets_of(c_nospare, "cdn.tracker.com"))
DT = base()
N._never_block_adjust(DT, ZONES, ["plain.org"])
check("a list that touches nothing: the conf byte-identical", conf(DT, BLK) == conf(base(), BLK))

# ── [3] swg-sni ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] swg-sni")
WGQ = "10.188.1.0/24"
ENTRIES = [{"subnet": WGQ, "category": U, "action": "block"},
           {"subnet": WGQ, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
           {"subnet": WGQ, "category": "all", "action": "direct"}]


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    N._SRC_SETS.clear()
    K = SmartKernel()
    N.run = K
    return K


def blocks(name_cats):
    K = fresh()
    N._LOOP["n"] += 1
    N._SNI_BLOCKS["v"] = None
    res = {"changed": 0, "errors": []}
    N._ensure_smart_nft([dict(e) for e in ENTRIES], sorted({e["category"] for e in ENTRIES}), res, pin=True, queue=True,
                        reset_mark=N.SNI_RESET_MARK, srcs={}, name_cats=name_cats)
    return N._SNI_BLOCKS["v"] or {}, res


B, res = blocks({c for c, v in DA.items() if v})
check("the pass ran clean", not res["errors"], res["errors"])
check("the reserved category is in nolearn while it holds names", R in (B.get("nolearn") or []), B.get("nolearn"))
B0, _r = blocks({c for c, v in base().items() if v})
check("…and absent without it: sni-blocks.json as before", R not in (B0.get("nolearn") or []) and B0.get("nolearn") == [U],
      B0.get("nolearn"))


def hello(host):
    name = host.encode()
    sni = struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    ext = struct.pack(">HH", 0, len(sni)) + sni
    body = b"\x03\x03" + b"\x11" * 32 + b"\x00" + struct.pack(">H", 2) + b"\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs


def packet(src, dst, host, sport):
    tls = hello(host)
    tcp = struct.pack(">HHIIBBHHH", sport, 443, 1000, 1, 5 << 4, 0x18, 65535, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(tls), 1, 0, 64, 6, 0, socket.inet_aton(src), socket.inet_aton(dst))
    return ip + tcp + tls


class NoNft:
    def __init__(self):
        self.scripts = []

    def __call__(self, args, input=None, capture_output=True, text=True, **kw):
        self.scripts.append(input or "")
        return subprocess.CompletedProcess(args, 0, "", "")


d = tempfile.mkdtemp(dir=TMP)
json.dump({c: sorted(v) for c, v in DA.items() if v}, open(os.path.join(d, "sni-map.json"), "w"))
json.dump(B, open(os.path.join(d, "sni-blocks.json"), "w"))
S.subprocess.run = NoNft()
cl = S.Classifier(os.path.join(d, "sni-map.json"), T, reset_mark=N.SNI_RESET_MARK, learn_ttl=3600)


def learned():
    with cl._lock:
        pend = list(cl._pending)
    return {(cat, ip) for cat, ip in pend} | {(cat, ip) for (ip, cat) in cl.seen}


BM = (1 << 16) | 0x9998
m = cl.on_packet(packet("10.188.1.9", "198.51.100.10", "x.tracker.com", 40001))
check("the parent's other name is still refused (x.tracker.com)", m == BM, m)
m = cl.on_packet(packet("10.188.1.9", "198.51.100.11", "cdn.tracker.com", 40002))
m2 = cl.on_packet(packet("10.188.1.9", "198.51.100.11", "cdn.tracker.com", 40012))
check("the allowed name under it is not, and is never reset either — no first-hit RST for a name never learned (cdn.tracker.com)",
      m is None and m2 is None, (m, m2))
check("…and nothing is learned for it", not any(ip == "198.51.100.11" for _c, ip in learned()), learned())
m = cl.on_packet(packet("10.188.1.9", "198.51.100.12", "maps.googleapis.com", 40003))
check("an allowed name under a routed parent is not refused and is learned into the route's set",
      m in (None, N.SNI_RESET_MARK) and ("google", "198.51.100.12") in learned(), (m, learned()))
m = cl.on_packet(packet("10.188.1.9", "198.51.100.13", "allowed.net", 40004))
check("an allowed name the union listed itself is not refused (allowed.net)", m in (None, N.SNI_RESET_MARK), m)

# ── [4] wiring ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] wiring")
src = open(path, encoding="utf-8").read()
body = src[src.index("    _dns_e = smart_e + [{\"subnet\": S} for S in arr_subs]"):src.index("    _shw = _smart_shadows(")]
check("the adjustment runs in the re-tier branch, before the cache is filled",
      body.index("_never_block_adjust(domains, _zones, _nb_allow)") < body.index('_DOMTIER_CACHE["v"] = (dom_sig, domains)')
      and body.index("if dom_unchanged:") < body.index("_never_block_adjust("))
check("only the name engines read the list (dns, sni_user)", 'if host_engine in ("dns", "sni_user") else []' in body)
sig = N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {})
check("the list joins the signature only when set", N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=()) == sig
      and N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=["p.q"]) != sig)
check("the node reports `allow` in its smart status", '"allow": 1}' in src[src.index("def smart_status"):])

# ── [5] cost ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] cost")
big = {U: ["n%d.host%d.example%d.com" % (i, i % 997, i % 13) for i in range(400000)], "google": ["googleapis.com"]}
allow500 = ["a%d.example%d.com" % (i, i % 13) for i in range(500)]
t0 = time.perf_counter()
N._never_block_adjust(big, {}, allow500)
dt = time.perf_counter() - t0
print("  one adjustment, 400 000-name union, 500 allowed names: %.0f ms" % (dt * 1000))
check("bounded: under 3 s on this box (a re-tier only)", dt < 3.0, dt)

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    print(("PLANT CAUGHT — %d check(s) went red" % len(FAILS)) if FAILS else "PLANT MISSED — every check still passed")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
