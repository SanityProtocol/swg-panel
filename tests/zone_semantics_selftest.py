#!/usr/bin/env python3
"""Self-test for zone SEMANTICS — ROUTING-RULE-BUILDER-PLAN §5.2, the four things the classifier owes.

zone_lowering_selftest.py asks whether a zone reaches each engine. This one asks what a zone MEANS, and
follows one written token all the way to the two matchers:

  trailing dot   `*.ru.` is `*.ru`, and a hostname written `x.ru.` still matches — a trailing dot is a legal
                 FQDN on both sides of the question, and on the matching side it used to leave an EMPTY last
                 label, which is the one string that must never be a zone key.
  lowercase      `*.RU` is `*.ru`, and an uppercase SNI matches it.
  punycode       `*.рф` is `xn--p1ai`, because that is what a resolver and a ClientHello carry. Without the
                 conversion the rule is stored, shipped, lowered, and silently matches nothing for ever.
  no PSL         `*.uk` also matches `bbc.co.uk`. There is no public-suffix list in the datapath and none is
                 proposed: a zone is the LAST LABEL, and both engines agree about that. `*.co.uk` is a
                 different thing — a `site`, two labels — and reaches the same host by the ordinary suffix
                 walk, which is why both are pinned in .campaign/classify-vectors.json side by side.

And the consequence that ties them together: all four spellings of one zone are ONE pattern. They dedupe on
what they MEAN, not on how they were typed, or the operator gets several badges reading `.ru` with no way to
tell them apart and the rule's nft set changes id for nothing.

Run:  python3 tests/zone_semantics_selftest.py          (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, struct, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(HERE, "..", "swg-sni")
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("   " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, os.path.abspath(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def client_hello(host):
    """The smallest ClientHello parse_sni() accepts, carrying `host` verbatim — the only way to test that the
    lowercasing happens where the bytes arrive rather than somewhere a caller could forget."""
    name = host.encode()
    ext = b"\x00\x00" + struct.pack(">H", len(name) + 5) + struct.pack(">H", len(name) + 3) \
          + b"\x00" + struct.pack(">H", len(name)) + name
    body = b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x00" + b"\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs


def main():
    P = load(SERVER, "swgpanel")

    # ── ONE ZONE, FOUR SPELLINGS ─────────────────────────────────────────────────────────────────────────
    written = ["*.ru", "*.RU", "*.ru.", "*.рф", "*.РФ.", "*.xn--p1ai", "*.uk"]
    for w in written:
        k = P.classify_target(w)
        check("`%s` reads as a zone" % w, k.get("kind") == "zone", json.dumps(k, ensure_ascii=False))
    check("case, trailing dot and IDN all reach the same operand",
          [P.classify_target(w)["value"] for w in written] == ["ru", "ru", "ru", "xn--p1ai", "xn--p1ai",
                                                               "xn--p1ai", "uk"],
          json.dumps([P.classify_target(w)["value"] for w in written]))

    _, _, _, pats = P._clean_targets(", ".join(written), keep_asns=True, keep_patterns=True)
    check("…so they store as THREE patterns, kept as written", pats == ["*.ru", "*.рф", "*.uk"],
          json.dumps(pats, ensure_ascii=False))

    # The dedupe has to be the browser's, or the two disagree about what is already in the rule. This is the
    # same key js/rulerows.js's badgeIdentity builds.
    check("…deduped on (kind, value), which is badgeIdentity's key",
          len({(P.classify_target(w)["kind"], P.classify_target(w)["value"]) for w in written}) == 3)

    # ── ONE MEANING, ONE nft SET ─────────────────────────────────────────────────────────────────────────
    # custom_cat_id's contract is "same target set → same id/set", and `domains`/`cidrs` reach it canonical.
    # Patterns are stored AS WRITTEN, so hashing the written form broke that promise: `*.ru` and `*.ru.` route
    # identically and got two sets — two chain rules and two dnsmasq directives for one destination, on every
    # node carrying both. It hashes kind:value now.
    ids = {P.custom_cat_id(["example.com"], [], [w]) for w in ("*.ru", "*.RU", "*.ru.")}
    check("every spelling of one zone shares one nft set", len(ids) == 1, json.dumps(sorted(ids)))
    idn = {P.custom_cat_id(["example.com"], [], [w]) for w in ("*.рф", "*.РФ.", "*.xn--p1ai")}
    check("…including the Cyrillic and the punycode spelling", len(idn) == 1, json.dumps(sorted(idn)))
    check("…and two DIFFERENT zones still get two sets",
          P.custom_cat_id([], [], ["*.ru"]) != P.custom_cat_id([], [], ["*.io"]))
    # The golden value is the point of the third segment: a rule WITHOUT patterns must hash as it always has,
    # or every custom set in the fleet is torn down and rebuilt on one sync for nothing.
    check("a pattern-free rule hashes exactly as it always has",
          P.custom_cat_id(["example.com"], ["1.2.3.0/24"]) == "custom_234c87cc9d",
          P.custom_cat_id(["example.com"], ["1.2.3.0/24"]))

    # ── WHAT THE NODE IS TOLD ────────────────────────────────────────────────────────────────────────────
    rules = [{"enabled": True, "category": "custom", "action": "block",
              "domains": ["keep.example"], "cidrs": [], "patterns": written}]
    kept, err, _ = P._validate_routing(rules, {}, "n1")
    check("validation keeps the three", err is None and kept[0]["patterns"] == ["*.ru", "*.рф", "*.uk"],
          json.dumps(kept, ensure_ascii=False))
    nodes = {"n1": {"name": "a", "routing_mode": "sni", "stats_file": "s.json",
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": kept}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.9.0.0/24", "listen_port": 1}, "peers": []}}}}
    plan = P.cascade_plan(nodes, snaps)["n1"]
    cat = plan["smart"][0]["category"]
    zones = (plan["patterns"].get(cat) or {}).get("zone")
    check("the bucket carries punycode operands, once each", zones == ["ru", "xn--p1ai", "uk"],
          json.dumps(zones))

    # A rule STORED before the dedupe existed still holds every spelling — nobody rewrites a state file to
    # add a guard. It ships clean anyway because the plan re-CLEANS every pass instead of trusting the file,
    # which is also why a second dedupe at the bucket was written and then removed: nothing could make it
    # fire. This is that claim, asserted on a rule that never went through _validate_routing.
    legacy = dict(nodes["n1"], ifaces={"awg0": {"egress_mode": "smart", "routing": [
        {"enabled": True, "category": "custom", "action": "block", "domains": ["keep.example"],
         "cidrs": [], "patterns": written}]}})
    lp = P.cascade_plan({"n1": legacy}, snaps)["n1"]
    lz = (lp["patterns"].get(lp["smart"][0]["category"]) or {}).get("zone")
    check("…and a rule stored with every spelling ships the same three", lz == ["ru", "xn--p1ai", "uk"],
          json.dumps(lz))

    # ── ENGINE 1 · FORCE-DNS ─────────────────────────────────────────────────────────────────────────────
    N = load(NODED, "swgnoded")
    tmp = tempfile.mkdtemp(prefix="zsem-")
    N.DNSMASQ_CONF = os.path.join(tmp, "smart-dnsmasq.conf")
    N.GEO_DIR = tmp
    N.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    N._dnsmasq_running = lambda: True
    N._ensure_smart_dnsmasq(plan["domains"], plan["smart"], {"errors": [], "changed": 0}, zones={cat: zones})
    conf = open(N.DNSMASQ_CONF).read()
    setn = N._smart_setname(cat)
    told = set()
    for line in conf.split("\n"):
        if line.startswith("nftset=/") and ("#" + setn) in line:
            told |= {d for d in line[len("nftset=/"):].rsplit("/4#", 1)[0].split("/") if d}
    check("dnsmasq is told the punycode label, not the Cyrillic one",
          "xn--p1ai" in told and "рф" not in conf, sorted(told))
    check("…and `uk` as a whole label", "uk" in told, sorted(told))
    # dnsmasq is not run here, so this is about the SHAPE the directive takes: `nftset=/uk/…` matches uk and
    # every name under it, however many labels deep — which IS bbc.co.uk, and is why there is no PSL to have.
    # The assertion that carries that is what is NOT emitted: no narrower uk key exists, so the coverage of
    # bbc.co.uk can only be coming from the bare label.
    check("…and nothing narrower is emitted for it — the single label IS the coverage",
          not any(d.endswith(".uk") for d in told), sorted(told))

    # ── ENGINE 2 · HYBRID SNI, where the matching side can actually be run ───────────────────────────────
    S = load(SNI, "swgsni")
    N.SNI_MAP_PATH = os.path.join(tmp, "sni-map.json")
    N.SNI_PATTERNS_PATH = os.path.join(tmp, "sni-patterns.json")
    N._SNI_PROC["p"], N._SNI_PROC["ttl"] = type("P", (), {"poll": lambda self: None})(), 3600
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600,
                         patterns=N._pattern_buckets(plan))   # the node's own transpose, not a hand-built dict
    cls = S.Classifier.__new__(S.Classifier)
    cls.map_path, cls.pat_path = N.SNI_MAP_PATH, N.SNI_PATTERNS_PATH
    cls.map_mtime = cls.pat_mtime = None
    cls.dom2cat, cls.pats = {}, S._empty_pats()
    cls._reload()

    check("a punycode host matches the IDN zone", cls._match("xn--80aswg.xn--p1ai") == [cat],
          repr(cls._match("xn--80aswg.xn--p1ai")))
    check("a trailing dot on the HOST does not defeat the zone", cls._match("x.ru.") == [cat])
    check("NO PUBLIC-SUFFIX LIST: *.uk matches bbc.co.uk", cls._match("bbc.co.uk") == [cat],
          repr(cls._match("bbc.co.uk")))
    check("…and it is the last label that decides, not a substring",
          cls._match("sub.ruble.com") == () and cls._match("uk.example.org") == (),
          repr(cls._match("uk.example.org")))

    # The lowercasing has to happen where the bytes arrive: a ClientHello may carry any case at all, and
    # nothing downstream lowercases it a second time.
    check("an uppercase SNI is lowercased at the parser",
          S.parse_sni(client_hello("WWW.X.RU")) == "www.x.ru", repr(S.parse_sni(client_hello("WWW.X.RU"))))
    check("…so it reaches the zone", cls._match(S.parse_sni(client_hello("WWW.X.RU"))) == [cat])
    check("…and an IDN host sent as punycode in any case does too",
          cls._match(S.parse_sni(client_hello("XN--80ASWG.XN--P1AI"))) == [cat])

    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
