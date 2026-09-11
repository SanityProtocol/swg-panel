#!/usr/bin/env python3
"""Self-test for the list importer's ZONE records — a bare label like `ru`.

The bug this locks down: every line of MetaCubeX's `tld-*` lists is `+.ru` / `+.moscow` / `+.cn`, i.e.
nothing but bare labels. `_PDOM_RE` ends in `(\\.label)+` and so demands a dot, which is right for "is this
a hostname" and wrong for "is this a routable record". All five TLD lists therefore resolved to ZERO
records and the provider catalog greyed them out as "no routable records" (`CatalogRow`'s `empty`).
Measured 2026-09-08 against the live files: tld-ru is 11 lines and every one was dropped.

Nothing was wrong with the lists. The datapath has always been ready — `*.ru` typed by hand classifies as
`{kind:"zone", value:"ru"}`, and swg-noded lowers a one-label zone as `nftset=/ru/…`, matching `ru` and
everything under it. The IMPORTER disagreed with the rule builder about the same value.

⚠️ THE DANGEROUS HALF, AND THE REASON THIS TEST EXISTS. The tempting fix — loosen `_PDOM_RE` — also
loosens `_line_hosts`, which reads hosts-file blocklists, and those are full of `0.0.0.0 localhost`. That
would turn `localhost` into a zone suffix-matching every name under it, and `.local` is mDNS: breaking it
breaks name resolution with no error anywhere. So a bare label counts ONLY where the line declares a zone
(`+.x`, `*.x`, `DOMAIN-SUFFIX,x`) and never for a reserved name. Most checks below are about what must
still be REFUSED.

Run: python3 tests/tld_zone_list_selftest.py (0 = pass).
  --perturb[=name]  rewrite the fix out and expect these checks to go red. Names: zone, plain, classical,
                    reserved.
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PERTURBATIONS = {
    # the bare-label acceptance goes away entirely — the pre-fix behaviour
    "zone":      ("    return bool(_PLABEL_RE.match(d)) and d not in _RESERVED_LABEL",
                  "    return False"),
    # the plain parser stops honouring its own wildcard prefix
    "plain":     ('    return ln if zone and _zone_label_ok(ln) else None',
                  '    return None'),
    # the classical parser drifts away from the plain one — the two-readers split
    "classical": ('    return d if kind == "DOMAIN-SUFFIX" and _zone_label_ok(d) else None',
                  '    return None'),
    # the reserved-name guard is dropped, so a blocklist's `localhost` becomes a routable zone.
    # ⚠️ The first version of this plant was `frozenset((` -> `frozenset(() or (`, which rewrites the source
    # but changes NOTHING: `() or (...)` returns the non-empty tuple. It reported "nothing went red" and the
    # code was fine — a perturbation that does not perturb cannot tell you that.
    "reserved":  ("    return bool(_PLABEL_RE.match(d)) and d not in _RESERVED_LABEL",
                  "    return bool(_PLABEL_RE.match(d))"),
}
ASKED = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--perturb=")]
ALL = any(a == "--perturb" for a in sys.argv)
WANT = list(PERTURBATIONS) if ALL else ASKED
PERTURB = bool(WANT)

src = open(SERVER, encoding="utf-8").read()
path = SERVER
if PERTURB:
    for name in WANT:
        frm, to = PERTURBATIONS[name]
        if src.count(frm) != 1:
            print("HARNESS BROKEN: perturbation %r matched %d times, not 1" % (name, src.count(frm)))
            sys.exit(2)
        src = src.replace(frm, to, 1)
    path = os.path.join(tempfile.mkdtemp(), "swg-panel-server")
    open(path, "w", encoding="utf-8").write(src)

loader = importlib.machinery.SourceFileLoader("swgpanel", path)
S = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
try:
    loader.exec_module(S)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

print("── the real file, verbatim: MetaCubeX geosite/tld-ru.list (fetched 2026-09-08) ──")
TLD_RU = "+.moscow\n+.ru\n+.su\n+.tatar\n+.xn--80adxhks\n+.xn--80asehdb\n+.xn--80aswg\n+.xn--90a3ac\n+.xn--c1avg\n+.xn--p1ai\n+.xn--p1acf\n"
got = S._norm_host_plain(TLD_RU)
check("all 11 lines resolve — the list is no longer empty", len(got) == 11, got)
check("…as bare labels, which is what a zone key IS", "ru" in got and "moscow" in got, got)
check("…including punycode TLDs", "xn--p1ai" in got, got)
check("a real domain list is unchanged",
      S._norm_host_plain("+.example.com\nfoo.bar.org\n") == ["example.com", "foo.bar.org"])

print("── what must STILL be refused (the half that matters) ──")
check("a hosts-file line is untouched: `0.0.0.0 localhost` is not a zone",
      S._norm_host_plain("0.0.0.0 localhost\n") == [] and S._line_hosts("0.0.0.0 localhost") is None)
check("a bare label with NO wildcard stays ambiguous and is refused",
      S._line_host_plain("ru") is None and S._line_host_plain("localhost") is None)
for bad in ("+.localhost", "*.local", "+.internal", "*.onion", "+.arpa", "+.lan", "+.corp"):
    check("a RESERVED name is refused even when declared a zone: " + bad,
          S._line_host_plain(bad) is None, S._line_host_plain(bad))
check("…and the same through the classical parser",
      S._line_classical_host("DOMAIN-SUFFIX,local") is None)
check("a malformed label is still refused", S._line_host_plain("+.-nope-") is None)
check("an empty declaration is refused", S._line_host_plain("+.") is None)
check("a hosts-file blocklist with a bare label yields nothing routable",
      S._norm_hosts("0.0.0.0 localhost\n127.0.0.1 local\n0.0.0.0 ads.example.com\n") == ["ads.example.com"])

print("── the two importers must agree, or this is a fresh two-readers split ──")
check("`DOMAIN-SUFFIX,ru` == `+.ru`",
      S._line_classical_host("DOMAIN-SUFFIX,ru") == S._line_host_plain("+.ru") == "ru")
check("`DOMAIN,ru` is an EXACT name, not a zone — still refused",
      S._line_classical_host("DOMAIN,ru") is None)
check("both still agree on an ordinary domain",
      S._line_classical_host("DOMAIN-SUFFIX,example.com") == S._line_host_plain("+.example.com") == "example.com")

print("── the value the importer produces is the value the RULE BUILDER produces ──")
# js/classify.js reads `*.ru` as {kind:"zone", value:"ru"}. The importer must hand the node the same key,
# or a list-routed zone and a hand-typed one would lower differently.
check("importer('+.ru') == what classify('*.ru') stores as its value", S._line_host_plain("+.ru") == "ru")

print()
if PERTURB:
    if FAILS:
        print("PERTURB(%s) OK — %d check(s) red: %s" % (",".join(WANT), len(FAILS), FAILS[:4]))
        sys.exit(0)
    print("PERTURB(%s) FAILED — nothing went red, this test does not cover the fix" % ",".join(WANT))
    sys.exit(1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "PASS")
sys.exit(1 if FAILS else 0)
