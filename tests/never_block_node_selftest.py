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
 [1b] the engine's own ladder decides the key: a more specific rule name than the union's parent needs no key (and gains
      no broader Block); a rule ZONE (dnsmasq, swg-sni) or a PATTERN (swg-sni) that would route the name keeps it; an
      allowed parent that was itself cut covers nothing
 [1c] the shadow sets: a rule for other devices naming an allowed name — or a name between the union's entry and it —
      never hands it back to the union; under a pattern that answers the allowed name, the names below it are not left to
      a union zone
  [2] dnsmasq: the parent keeps its union set; the allowed name's own key carries `dnsok` alone; with no Block to spare it
      from (D2 off) no directive is written for it; a list that touches nothing leaves the conf byte-identical
  [3] swg-sni: the reserved category is in `nolearn` only when it holds names (sni-blocks.json otherwise as before); the
      allowed name's ClientHello is not refused and nothing is learned for it, its parent's sibling still is refused, and an
      allowed name under a routed parent is still learned into the route's set; while the map holds the reserved key the
      verdicts file is written before the map (swg-sni reloads each on its own), and after it otherwise
  [4] wiring: the pass runs before the domain-tier cache is filled, the list joins the signature only when set, only the
      name engines read it, and the node reports `allow`
  [5] cost: one adjustment over a 400k-name union (a re-tier, never a sync) — printed, and bounded

Hermetic. Run: python3 tests/never_block_node_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     nocut       a union keeps the allowed names                                               [1]
     nokey       an allowed name under a union parent gets no key of its own                   [1] [3]
     noladder    the key ignores the ladder: always the reserved category                      [1] [1b]
     noshadow    the shadow sets ignore the list                                               [1c]
     nearparent  only a union listing the DIRECT parent gives a key                            [1c]
     nopatsig    the signature ignores the pattern rules                                       [4]
     nolearn     the reserved category is not in swg-sni's nolearn                             [3]
     blkorder    the map is always written before the verdicts                                 [3]
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
    "nocut": ('                if not _nb_under(d, allow):\n                    keep.append(d)', '                if True:\n                    keep.append(d)'),
    "nokey": ('        for c in (ladder(a) or {NEVER_BLOCK_CAT}):\n            add.setdefault(c, []).append(a)', '        pass'),
    "noladder": ('for c in (ladder(a) or {NEVER_BLOCK_CAT}):', 'for c in {NEVER_BLOCK_CAT}:'),
    "noshadow": ('                if allow and not str(c1).startswith(_NB_UNION) and _nb_under(n, allow):', '                if False:'),
    "nearparent": ('for k in range(1, len(lb)) for c in hit.get(', 'for k in range(1, 2) for c in hit.get('),
    "nopatsig": ('json.dumps({k: v for k, v in (pats or {}).items() if k != "zone"}, sort_keys=True)', '""'),
    "nolearn": ('| ({NEVER_BLOCK_CAT} & set(name_cats or ()))', '| set()'),
    "blkorder": ('    _nb_first = bool((domains or {}).get(NEVER_BLOCK_CAT))', '    _nb_first = False'),
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
PATS = {"zone": ZONES}

# ── [1] the map ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the map")
D = base()
N._never_block_adjust(D, PATS, ALLOW, "dns")
check("the union loses the allowed name and the name under it (allowed.net, sub.allowed.net)",
      "allowed.net" not in D[U] and "sub.allowed.net" not in D[U], D[U])
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
N._never_block_adjust(D0, PATS, [], "dns")
check("no list: the map as it was", D0 == base())
D1 = base()
N._never_block_adjust(D1, PATS, ["plain.org"], "dns")
check("a list that touches nothing: the map as it was", D1 == base(), D1)
D2 = base()
_src = {c: v for c, v in D2.items()}
N._never_block_adjust(D2, PATS, ALLOW, "dns")
check("a list object some cache holds is never mutated (new lists only)", _src[U] is not D2[U] and base()[U] == _src[U]
      and "maps.googleapis.com" not in _src["google"], (_src[U], _src["google"]))
for eng in ("dns", "sni_user"):
    D = base()
    N._never_block_adjust(D, PATS, ALLOW, eng)
    check("%s: the same map from swg-sni's ladder" % eng, eng == "dns" or sorted(D.get(R) or []) == ["cdn.tracker.com", "shop.xyz"]
          and "maps.googleapis.com" in D["google"], D)

# ── [1b] the engine's own ladder decides the key ─────────────────────────────────────────────────────────────────────────
print("\n[1b] the engine's own ladder decides the key")
for eng in ("dns", "sni_user"):
    D = {U: ["example.com"], "blockY": ["example.com"], "directX": ["b.example.com"]}
    N._never_block_adjust(D, {}, ["a.b.example.com"], eng)
    check("%s: a rule name more specific than the union's parent wins — the key carries that rule alone, no broader Block" % eng,
          D == {U: ["example.com"], "blockY": ["example.com"], "directX": ["b.example.com", "a.b.example.com"]}, D)
    D = {U: ["tracker.ru"]}
    N._never_block_adjust(D, {"zone": {"exitE": ["ru"]}}, ["cdn.tracker.ru"], eng)
    check("%s: a rule ZONE that would route the name keeps it (cdn.tracker.ru → the *.ru Exit, not the catch-all)" % eng,
          D.get("exitE") == ["cdn.tracker.ru"] and not D.get(R), D)
    D = {U: ["tracker.com", "cdn.tracker.com", "x.tracker.com"], "custom_com": ["com"]}
    N._never_block_adjust(D, {}, ["tracker.com", "cdn.tracker.com"], eng)
    check("%s: an allowed parent that was cut covers nothing — no key for the name under it" % eng,
          D == {U: [], "custom_com": ["com"]}, D)
D = {U: ["tracker.io"]}
N._never_block_adjust(D, {"contains": {"patP": ["cdn"]}, "first": {"patF": ["img"]}}, ["cdn.tracker.io", "img.tracker.io"], "sni_user")
check("sni_user: a PATTERN rule that would route the name keeps it (contains `cdn`, first label `img`)",
      D.get("patP") == ["cdn.tracker.io"] and D.get("patF") == ["img.tracker.io"] and not D.get(R), D)
D = {U: ["tracker.io"]}
N._never_block_adjust(D, {"contains": {"patP": ["cdn"]}}, ["cdn.tracker.io"], "dns")
check("dns: patterns are not dnsmasq's — the reserved key", D.get(R) == ["cdn.tracker.io"] and not D.get("patP"), D)

# ── [1c] the shadow sets ─────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[1c] the shadow sets")
SA, SB = "10.188.1.0/24", "10.188.2.0/24"
for eng in ("dns", "sni_user"):
    for allow_list in (ALLOW, []):
        D = base()
        D["direct_b"] = ["cdn.tracker.com"]                      # a rule for OTHER devices names the allowed name itself
        N._never_block_adjust(D, PATS, allow_list, eng)
        N._SHADOW.update(k=None, v={})
        shw = N._smart_shadows([{"subnet": SA, "category": U, "action": "block"},
                                {"subnet": SB, "category": "google", "action": "exit"},
                                {"subnet": SB, "category": "direct_b", "action": "direct"}], D, PATS, eng,
                               insig=None, allow=allow_list)
        held = sorted({n for sh, v in (shw.get("domains") or {}).items() for n in v
                       if any(sh == x[0] for x in (shw.get("by_target") or {}).get(U, ()))})
        if allow_list:
            check("%s: no shadow of the union holds an allowed name (maps.googleapis.com, cdn.tracker.com)" % eng,
                  not ({"maps.googleapis.com", "cdn.tracker.com"} & set(held)), held)
        else:
            check("%s: …while without the list the union's shadow still holds the rule's name under its parent" % eng,
                  "cdn.tracker.com" in held, held)
    D = {U: ["tracker.com"], "exitX": ["foo.tracker.com"]}     # a name BETWEEN the union's entry and the allowed one
    N._never_block_adjust(D, {}, ["cdn.foo.tracker.com"], eng)
    N._SHADOW.update(k=None, v={})
    shw = N._smart_shadows([{"subnet": SA, "category": U, "action": "block"}, {"subnet": SB, "category": "exitX", "action": "exit"}],
                           D, {}, eng, insig=None, allow=["cdn.foo.tracker.com"])
    sh_u = [sh for sh, _c1, _m in (shw.get("by_target") or {}).get(U, ())]
    check("%s: a rule for other devices names a name between the union's entry and the allowed one: the allowed name gets "
          "its own key (that rule's), more specific than the union's shadow of the rule's name" % eng,
          "cdn.foo.tracker.com" in D["exitX"] and not any("cdn.foo.tracker.com" in (shw.get("domains") or {}).get(sh, ()) for sh in sh_u)
          and any("foo.tracker.com" in (shw.get("domains") or {}).get(sh, ()) for sh in sh_u), (D, shw.get("domains")))
D = {U: ["placeholder.io"]}
N._never_block_adjust(D, {"zone": {UZ: ["ru"]}, "first": {"patF": ["site"]}}, ["site.ru"], "sni_user")
check("sni_user: a first-label rule answers the allowed name and a union ZONE covers it: it is keyed to the rule, so the "
      "names under it (img.site.ru) meet the key, not the zone", D.get("patF") == ["site.ru"], D)

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
N._never_block_adjust(DA, PATS, ALLOW, "dns")
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
N._never_block_adjust(DT, PATS, ["plain.org"], "dns")
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

class _Alive:
    def poll(self):
        return None


def written_order(domains, blocks_):
    N.SNI_MAP_PATH, N.SNI_BLOCKS_PATH = os.path.join(d, "o-map.json"), os.path.join(d, "o-blocks.json")
    N.SNI_PATTERNS_PATH, N.SNI_SETS_PATH = os.path.join(d, "o-pat.json"), os.path.join(d, "o-sets.json")
    for f in (N.SNI_MAP_PATH, N.SNI_BLOCKS_PATH):
        with __import__("contextlib").suppress(OSError):
            os.remove(f)
    N._SNI_PROC.update(p=_Alive(), ttl=3600)
    N._SNI_MAP_LAST.update(key=None, stat=None)
    order, real = [], N.os.replace
    def rec(a, b):
        order.append(os.path.basename(b)); real(a, b)
    N.os.replace = rec
    try:
        r = {"changed": 0, "errors": []}
        N._ensure_sni_router(domains, ["10.188.1.0/24"], r, blocks=blocks_)
    finally:
        N.os.replace = real
    return [x for x in order if x in ("o-map.json", "o-blocks.json")], r


o, r = written_order({c: v for c, v in DA.items() if v}, B)
check("with the reserved key in the map: the verdicts are written first, then the map", o == ["o-blocks.json", "o-map.json"], (o, r))
o, r = written_order({c: v for c, v in base().items() if v}, B0)
check("without it: the map first, as before", o == ["o-map.json", "o-blocks.json"], (o, r))

# ── [4] wiring ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] wiring")
src = open(path, encoding="utf-8").read()
body = src[src.index("    _dns_e = smart_e + [{\"subnet\": S} for S in arr_subs]"):src.index("    _shw = _smart_shadows(")]
check("the adjustment runs in the re-tier branch, before the cache is filled",
      body.index("_never_block_adjust(domains, _pats, _nb_allow, host_engine)") < body.index('_DOMTIER_CACHE["v"] = (dom_sig, domains)')
      and body.index("if dom_unchanged:") < body.index("_never_block_adjust("))
check("only the name engines read the list (dns, sni_user)", 'if host_engine in ("dns", "sni_user") else []' in body)
sig = N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {})
check("the list joins the signature only when set", N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=()) == sig
      and N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=["p.q"]) != sig)
_P1, _P2 = {"zone": {"z": ["ru"]}, "contains": {"p": ["cdn"]}}, {"zone": {"z": ["ru"]}, "contains": {"p": ["cdn"], "q": ["img"]}}
check("with the list set, a pattern rule's edit moves the signature (the keys are made from it)",
      N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=["p.q"], pats=_P1)
      != N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, allow=["p.q"], pats=_P2))
check("…and without it the signature is as before, whatever the patterns",
      N._dom_signature([{"subnet": S0}], {"a": ["x.y"]}, {}, {}, pats=_P2) == sig)
check("the reconcile passes the patterns", "allow=_nb_allow, pats=_pats)" in body)
check("the node reports `allow` in its smart status", re.search(r'"allow": 1[,}]', src[src.index("def smart_status"):]) is not None)

# ── [5] cost ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] cost")
big = {U: ["n%d.host%d.example%d.com" % (i, i % 997, i % 13) for i in range(400000)], "google": ["googleapis.com"]}
allow500 = ["a%d.example%d.com" % (i, i % 13) for i in range(500)]
t0 = time.perf_counter()
N._never_block_adjust(big, {}, allow500, "dns")
dt = time.perf_counter() - t0
print("  one adjustment, 400 000-name union, 500 allowed names: %.0f ms" % (dt * 1000))
check("bounded: under 3 s on this box (a re-tier only)", dt < 3.0, dt)
big = {U: ["example%d.com" % i for i in range(13)], "google": ["g%d.example.net" % i for i in range(300000)]}
t0 = time.perf_counter()
N._never_block_adjust(big, {"zone": {"google": ["com"]}}, allow500, "sni_user")   # a *.com rule routes them all
dt = time.perf_counter() - t0
print("  500 allowed names under a union parent, each given a key beside a 300 000-name rule list: %.0f ms" % (dt * 1000))
check("…every one keyed, in one copy of the rule list", len(big["google"]) == 300500 and dt < 3.0, (len(big["google"]), dt))

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    print(("PLANT CAUGHT — %d check(s) went red" % len(FAILS)) if FAILS else "PLANT MISSED — every check still passed")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
