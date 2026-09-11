#!/usr/bin/env python3
"""Self-test — A PULLED LIST'S BARE LABELS ARE ZONES, and the node used to throw all of them away.

Every record in a MetaCubeX `tld-*` list is a bare label, because upstream writes them `+.ru` — a DECLARED
ZONE. 3b541de taught the PANEL to keep those (`_zone_label_ok`: "a bare TLD counts"). The node's own reader
of the pulled `<cat>.doms` file still required a dot, so it dropped every one of them, silently.

MEASURED on the qualification fleet 2026-09-10, after the panel half was already correct: the panel served
11 records for `mc:tld-ru`, the catalog row read "11 domains", the operator added it, the panel planned it,
the node pulled the file (`.pver` matching the panel's `v`), built `set cat_mc_tld_ru` and the mark rule
`ip daddr @cat_mc_tld_ru meta mark set … return` — and `smart-dnsmasq.conf` never gained a key for it, so
the set stayed empty for ever. Accepted, stored, planned, routes nothing.

⚠️ THE FIX IS A SPLIT, NOT A LOOSER REGEX. `domains` is read by ALL THREE engines, and to xt_string a bare
label is a substring matching every ClientHello that contains those bytes anywhere — `ru` would catch
brutal.io and truecaller.com. Bare labels therefore travel the ZONE channel the panel's own `*.ru` patterns
already use: dnsmasq makes one more key of it, swg-sni matches the hostname's LAST LABEL, Kernel-SNI is
handed no zones at all. The negative assertions below are the point of this file.

Run: python3 tests/pulled_zone_lowering_selftest.py      (0 = pass)
     --perturb   restores the dotted-only reader and expects RED.
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.abspath(os.path.join(HERE, "..", "swg-noded"))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

_SRC = open(NODED, encoding="utf-8").read()
_ANCH = """                for _raw in open(path).read().splitlines():
                    _d = _raw.strip()
                    if _DOM_RE.match(_d):
                        doms.append(_d)
                    elif _zone_label_ok(_d):                   # `+.ru` → `ru`: a declared zone, not a malformed domain
                        zones.append(_d)"""
assert _SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:                                                    # the shipped reader: dotted names only
    _SRC = _SRC.replace(_ANCH, """                for _raw in open(path).read().splitlines():
                    _d = _raw.strip()
                    if _DOM_RE.match(_d):
                        doms.append(_d)""")
    _fd, NODED = tempfile.mkstemp(suffix=".py", prefix="pulledzone-", dir=HERE)
    os.write(_fd, _SRC.encode()); os.close(_fd)

def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, os.path.abspath(path))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    l.exec_module(m)
    return m

N = load(NODED, "swgnoded")
if PERTURB:
    os.unlink(NODED)

TMP = tempfile.mkdtemp(prefix="pulledzone-")
N.GEO_DIR = TMP
N.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
N._dnsmasq_running = lambda: True

def write_doms(cat, lines):
    open(os.path.join(TMP, cat + ".doms"), "w").write("\n".join(lines) + "\n")
    N._DOM_CACHE.pop(cat, None)

# The real thing: tld-ru's 11 records, exactly as the panel resolves `+.ru` & friends.
TLD_RU = ["moscow", "ru", "su", "tatar", "xn--80adxhks", "xn--80asehdb",
          "xn--80aswg", "xn--c1avg", "xn--d1acj3b", "xn--p1acf", "xn--p1ai"]
write_doms("mc:tld-ru", TLD_RU)
write_doms("mc:mixed", ["example.com", "ru", "mail.example.org", "localhost", "-bad", "su", "a..b"])

res = {"errors": [], "changed": 0}
doms, zones = N._smart_domain_refresh(["mc:tld-ru", "mc:mixed"], res)

print("[1] a tld-* list is ALL zones — and must not come back empty")
check("its 11 records are read as zones", sorted(zones.get("mc:tld-ru") or []) == sorted(TLD_RU),
      json.dumps(zones.get("mc:tld-ru")))
check("…and none of them is mistaken for a domain", not doms.get("mc:tld-ru"), json.dumps(doms.get("mc:tld-ru")))
check("the shipped bug: the cat is not silently absent from BOTH buckets",
      bool(zones.get("mc:tld-ru")) or bool(doms.get("mc:tld-ru")))

print("\n[2] the split is per RECORD — a classical list may carry both shapes")
check("dotted names go to domains", doms.get("mc:mixed") == ["example.com", "mail.example.org"],
      json.dumps(doms.get("mc:mixed")))
check("bare labels go to zones", sorted(zones.get("mc:mixed") or []) == ["ru", "su"],
      json.dumps(zones.get("mc:mixed")))
check("`localhost` is refused — a reserved label is not a zone", "localhost" not in (zones.get("mc:mixed") or []))
check("junk is still junk", not ({"-bad", "a..b"} & set(zones.get("mc:mixed") or []) & set(doms.get("mc:mixed") or [])))

print("\n[3] SAFETY — a bare label must never reach `domains`, which xt_string reads")
for cat in ("mc:tld-ru", "mc:mixed"):
    check("no bare label in domains[%s]" % cat,
          all("." in d for d in (doms.get(cat) or [])), json.dumps(doms.get(cat)))

print("\n[4] the memo caches the SPLIT, not just the domains (a second read must agree)")
d2, z2 = N._smart_domain_refresh(["mc:tld-ru", "mc:mixed"], {"errors": [], "changed": 0})
check("second call returns the same split (memoized)", (d2, z2) == (doms, zones))

print("\n[5] Force-DNS lowers them: `nftset=/ru/…` targeting the cat's own set")
N.DNSMASQ_CONF = os.path.join(TMP, "smart-dnsmasq.conf")
smart_e = [{"subnet": "10.8.2.0/24", "category": "mc:tld-ru", "action": "exit", "table": None}]
N._SMART_MODE["engine"] = "dns"
N._ensure_smart_dnsmasq({}, smart_e, {"errors": [], "changed": 0}, zones={"mc:tld-ru": zones.get("mc:tld-ru") or []})
conf = open(N.DNSMASQ_CONF).read()
sn = N._smart_setname("mc:tld-ru")
check("the config gained a key for `ru`", "/ru/" in conf or conf.count("/ru#") or "/ru" in conf, conf[-300:])
check("…pointed at this category's set", sn in conf, conf[-300:])
check("every zone label is in the config", all(("/" + z) in conf for z in TLD_RU),
      [z for z in TLD_RU if ("/" + z) not in conf])
check("Force-DNS reports what it lowered", (N._SMART_MODE.get("lowered") or {}).get("zone") == len(TLD_RU),
      json.dumps(N._SMART_MODE.get("lowered")))

print("\n[6] a zone-only change MOVES the drift signature (else it never lands on the node)")
a = N._dom_signature(smart_e, {}, {"mc:tld-ru": ["ru"]}, {})
b = N._dom_signature(smart_e, {}, {"mc:tld-ru": ["ru", "su"]}, {})
check("adding a zone changes the signature", a != b)
check("an unchanged zone set does not", a == N._dom_signature(smart_e, {}, {"mc:tld-ru": ["ru"]}, {}))

print("\n[7] TWO CHANNELS, ONE BUCKET — swg-sni must see the pulled zones too")
src = open(os.path.abspath(os.path.join(HERE, "..", "swg-noded")), encoding="utf-8").read()
check("the merge goes into `_pats`, not into the `_zones` alias",
      '_zb = _pats.setdefault("zone", {})' in src)
check("…and it happens BEFORE the signature is taken",
      src.index('_zb = _pats.setdefault("zone", {})') < src.index("dom_sig = _dom_signature("))
check("swg-sni is still handed the whole bucket dict", "patterns=_pats)" in src)
check("the pulled zones are never unioned into `domains`",
      "domains[cat] = sorted(set(domains.get(cat) or []) | set(fl))" in src
      and "domains[cat] = sorted(set(domains.get(cat) or []) | set(_zs))" not in src)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
