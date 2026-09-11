#!/usr/bin/env python3
"""Self-test for Hybrid-SNI Tier 1 + Tier 2 — `google.*`, `*.google.*`, `google*`, `*google`, `*google*`
(ROUTING-RULE-BUILDER-PLAN, Phase 4).

One panel half and one node half, and they must agree:

  PANEL       cascade_plan buckets a rule's patterns by kind into `smart.patterns[cat]`, storing the
              canonical operand (`*.google.*` → `google`). No node classifies anything, ever.
  HYBRID SNI  swg-noded writes the buckets to `sni-patterns.json`; swg-sni's `_match` lowers all six kinds,
              Tier 1 by dict lookup on a LABEL and Tier 2 by a linear scan over the name as a STRING.

WHAT THIS FILE IS REALLY FOR — THE PRECEDENCE (§1.4). Five rungs claim overlapping hostnames, and which one
wins is the whole semantics of the feature. A test that fed each kind a host only it could match would pass
on an implementation whose ladder was in any order at all, and dict iteration order — the order that a
JSON file happens to be written in — is exactly what §1.4 says the answer must never come from. So every
precedence case here is a host that TWO OR MORE rungs claim, and the assertion names which one takes it.

The other three things it covers:
  · WITHIN a Tier-2 kind, the longest matching operand wins — the same "most specific" rule, applied where a
    scan (unlike a dict) really can have several answers at once;
  · the Tier-1 negatives, which are what separate a zone from a substring: `*.ru` must never touch
    `sub.ruble.com`, and `google.*` must never touch `www.google.com` — the label is FIRST, not anywhere;
  · SNI_KINDS is a LOADING list and `_match` is what lowers. A kind loaded and not matched routes nothing,
    silently, and is the exact failure this phase was warned about.

Run:  python3 tests/hybrid_patterns_selftest.py          (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
SNI = os.path.join(HERE, "..", "swg-sni")
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("   " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class _Alive:
    def poll(self):
        return None

    def terminate(self):
        pass


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, os.path.abspath(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    P = load(SERVER, "swgpanel")
    N = load(NODED, "swgnoded")
    S = load(SNI, "swgsni")

    # ── PANEL: every star-form survives validation and is bucketed by kind, as a canonical operand ────────
    # ONE OPERAND PER KIND, all different: with a shared operand a host could be claimed by two rungs and
    # a passing case would not say which one answered.
    written = ["*.anyx.*", "firstx.*", "*.ru", "cdnx*", "*tail", "*middl*"]
    # `block`, not `exit`: an exit rule needs a second known node in the fleet, and what is under test here
    # is the pattern channel, which both actions share verbatim.
    rules = [{"enabled": True, "category": "custom", "action": "block",
              "domains": ["keep.example"], "cidrs": [], "patterns": written}]
    kept, err, _ = P._validate_routing(rules, {}, "n1")
    check("every star-form survives validation as the operator wrote it",
          err is None and kept[0].get("patterns") == written, json.dumps(kept))

    nodes = {"n1": {"name": "a", "routing_mode": "sni", "stats_file": "s.json",
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": kept}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.9.0.0/24", "listen_port": 1}, "peers": []}}}}
    plan = P.cascade_plan(nodes, snaps)["n1"]
    cat = plan["smart"][0]["category"]
    got = plan["patterns"].get(cat) or {}
    check("the panel buckets all six kinds, as canonical operands",
          got == {"any": ["anyx"], "first": ["firstx"], "zone": ["ru"],
                  "starts": ["cdnx"], "ends": ["tail"], "contains": ["middl"]}, json.dumps(got))
    check("…and never merges any of them into `domains`",
          plan["domains"].get(cat) == ["keep.example"], json.dumps(plan["domains"]))

    # ── NODE: the buckets are written, and swg-sni lowers every one of them ───────────────────────────────
    # DERIVED by the node's own transpose from the panel's own plan — a bucket the test hand-built is a
    # bucket a broken transpose would still satisfy.
    buckets = N._pattern_buckets({"patterns": plan["patterns"]})
    tmp = tempfile.mkdtemp(prefix="hybrid-")
    N.SNI_MAP_PATH = os.path.join(tmp, "sni-map.json")
    N.SNI_PATTERNS_PATH = os.path.join(tmp, "sni-patterns.json")
    N._SNI_PROC["p"], N._SNI_PROC["ttl"] = _Alive(), 3600
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600, patterns=buckets)

    # ── WHAT IT LOWERED, reported (§10.5 item 4) ─────────────────────────────────────────────────────────
    # Read from the FILE, then compared with what the node reported: `lowered` is counted from the same dict
    # that is serialised into it, so the two agree by construction — and this is the check that says so. A
    # count taken from `patterns` instead would survive a cap that dropped half of them, or a write that
    # never happened ([[lesson-sign-the-output]]). Distinct operands per kind: one operand claimed by three
    # categories is ONE thing for swg-sni to scan.
    _onfile = json.load(open(N.SNI_PATTERNS_PATH))
    _want = {k: len({o for lst in byc.values() for o in lst}) for k, byc in _onfile.items()}
    check("the node reports what it lowered, per kind",
          N._SMART_MODE.get("lowered") == _want and _want,
          "reported %s · on file %s" % (json.dumps(N._SMART_MODE.get("lowered")), json.dumps(_want)))

    # ⚠️ THE CHECK ABOVE ALONE CANNOT FAIL USEFULLY. Its fixture gives every kind exactly one category with
    # one operand, so "distinct operands" and "number of categories" are the same number, and the cap trims
    # nothing, so "what was written" and "what was asked for" are the same dict. Both wrong implementations
    # passed it. This second call makes the two distinctions visible: `shared` is claimed by TWO categories
    # (so operands=2 while categories=3), and the cap is dropped to 1 so two of the three never reach the
    # file. Perturbation-proven — counting `patterns`, or counting `len(byc)`, now both fail here.
    # ITS OWN FILE. The first version of this block reused SNI_PATTERNS_PATH and overwrote the buckets the
    # Classifier reads twenty lines further down, failing all six routing checks — the fixture, not the code.
    _real_max, _real_path = N._SNI_TIER2_MAX, N.SNI_PATTERNS_PATH
    try:
        N.SNI_PATTERNS_PATH = os.path.join(tmp, "lowered-probe.json")
        N._SNI_TIER2_MAX = 1
        N._ensure_sni_router({"catA": ["keep.example"]}, ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600,
                             patterns={"contains": {"catA": ["shared"], "catB": ["shared"], "catC": ["unique"]}})
        _f = json.load(open(N.SNI_PATTERNS_PATH))
        _ops = {o for byc in _f.values() for lst in byc.values() for o in lst}
        check("…counted from the file, so a cap that dropped operands moves it",
              len(_ops) == 1 and N._SMART_MODE.get("lowered") == {"contains": 1},
              "file %s · reported %s" % (json.dumps(_f), json.dumps(N._SMART_MODE.get("lowered"))))
        N._SNI_TIER2_MAX = 10
        N._ensure_sni_router({"catA": ["keep.example"]}, ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600,
                             patterns={"contains": {"catA": ["shared"], "catB": ["shared"], "catC": ["unique"]}})
        check("…and one operand claimed by two categories is ONE thing to scan",
              N._SMART_MODE.get("lowered") == {"contains": 2},
              json.dumps(N._SMART_MODE.get("lowered")))
    finally:
        N._SNI_TIER2_MAX, N.SNI_PATTERNS_PATH = _real_max, _real_path

    cls = S.Classifier.__new__(S.Classifier)           # no flusher thread, no nft: only the lookup is under test
    cls.map_path, cls.pat_path = N.SNI_MAP_PATH, N.SNI_PATTERNS_PATH
    cls.map_mtime = cls.pat_mtime = None
    cls.dom2cat, cls.pats = {}, S._empty_pats()
    cls._reload()

    for kind, host in (("any", "a.anyx.b"), ("first", "firstx.example"), ("zone", "x.ru"),
                       ("starts", "cdnxyz.example"), ("ends", "www.foo.tail"), ("contains", "a.xmiddlx.io")):
        check("`%s` routes the host it claims" % kind, cls._match(host) == [cat],
              host + " → " + repr(cls._match(host)))

    # THE TIER-1 NEGATIVES — the boundary that makes these kinds worth having at all.
    check("THE NEGATIVE: a zone is a LABEL — sub.ruble.com is not in .ru",
          cls._match("sub.ruble.com") == (), repr(cls._match("sub.ruble.com")))
    check("THE NEGATIVE: `firstx.*` is the FIRST label — www.firstx.io is not it",
          cls._match("www.firstx.io") == (), repr(cls._match("www.firstx.io")))
    check("THE NEGATIVE: `*.anyx.*` is a WHOLE label — notanyxx.com is not one",
          cls._match("notanyxx.com") == (), repr(cls._match("notanyxx.com")))

    # ── THE PRECEDENCE LADDER (§1.4) ─────────────────────────────────────────────────────────────────────
    # Every rung is loaded with an operand that claims the SAME hostname, so each case is decided by the
    # order and by nothing else. Written as one file per case so the losing rungs are genuinely present.
    # `google.com` is claimed by ALL SEVEN rungs at once — that is the point, and it is why the operands
    # look contrived: `googl` starts it, `e.com` ends it, `oogle` is inside it, `google` is both its first
    # and some label, `com` is its last. Rungs are then peeled off one at a time and the winner must walk
    # down the ladder in order. One host throughout: changing the host between cases would let a wrong
    # order pass by accident.
    HOST = "google.com"
    ladder = {"any": {"L_any": ["google"]}, "first": {"L_first": ["google"]}, "zone": {"L_zone": ["com"]},
              "starts": {"L_starts": ["googl"]}, "ends": {"L_ends": ["e.com"]},
              "contains": {"L_contains": ["oogle"]}}
    json.dump({"L_suffix": [HOST]}, open(N.SNI_MAP_PATH, "w"))
    json.dump(ladder, open(N.SNI_PATTERNS_PATH, "w"))
    cls.map_mtime = cls.pat_mtime = None
    cls._reload()
    check("1. a full suffix beats every pattern kind", cls._match(HOST) == ["L_suffix"], repr(cls._match(HOST)))
    json.dump({}, open(N.SNI_MAP_PATH, "w"))
    cls.map_mtime = None
    cls._reload()
    check("2. first-label beats zone, any-label and all three Tier-2 kinds",
          cls._match(HOST) == ["L_first"], repr(cls._match(HOST)))
    for gone, expect, why in (
            ("first",  "L_zone",     "3. zone beats any-label and Tier 2"),
            ("zone",   "L_any",      "4. any-label beats Tier 2 — the broadest LABEL still outranks a character run"),
            ("any",    "L_starts",   "5. within Tier 2, `starts` is tried first"),
            ("starts", "L_ends",     "6. …then `ends`"),
            ("ends",   "L_contains", "7. …and `contains` last, anchored by neither end")):
        ladder.pop(gone)
        json.dump(ladder, open(N.SNI_PATTERNS_PATH, "w"))
        cls.pat_mtime = None
        cls._reload()
        check(why, cls._match(HOST) == [expect], HOST + " → " + repr(cls._match(HOST)))

    # THE LADDER'S OWN PRINCIPLE, asserted as the SUBSET RELATION it claims rather than as an order. "Most
    # specific first" is only meaningful if each rung really does match fewer hosts than the one below it, and
    # that is checkable for one operand: every host `first` claims, `any` claims too, and not the reverse.
    # This is the check that would have caught §1.4's own list, which put `any` above `first`.
    json.dump({}, open(N.SNI_MAP_PATH, "w"))
    for narrow, broad, host_both, host_broad_only in (
            ("first", "any", "google.com", "www.google.com"),
            ("zone",  "any", "x.google",   "google.x")):
        json.dump({narrow: {"N": ["google"]}, broad: {"B": ["google"]}},
                  open(N.SNI_PATTERNS_PATH, "w"))
        cls.map_mtime = cls.pat_mtime = None
        cls._reload()
        both, only = cls._match(host_both), cls._match(host_broad_only)
        check("`%s` is a strict subset of `%s`, and the ladder tries the subset first" % (narrow, broad),
              both == ["N"] and only == ["B"],
              "%s->%s  %s->%s" % (host_both, both, host_broad_only, only))

    # A TIER-2 OPERAND IS BYTES, NOT LABELS: a dot at either end is the operator pinning a boundary, and
    # stripping it (which is right for every label kind) silently WIDENS the rule. `*yandex.*` is one of
    # PATTERNS §1.3's own examples, and xt_string matches it as stored — so stripping here would also make
    # the two engines that both run `contains` disagree about one saved rule.
    json.dump({"contains": {"dotted": ["yandex."]}, "zone": {"zoned": ["ru."]}},
              open(N.SNI_PATTERNS_PATH, "w"))
    cls.pat_mtime = None
    cls._reload()
    check("a Tier-2 operand keeps a dot the operator wrote",
          [o for o, _ in cls.pats["contains"]] == ["yandex."], repr(cls.pats["contains"]))
    # `.com`, not `.ru`: the zone rung in this same fixture claims every .ru name and would answer first —
    # correctly, which is exactly why the probe for a Tier-2 rung must not also be claimed by a rung above it.
    check("…so it still excludes what the dot excludes",
          cls._match("www.yandex.com") == ["dotted"] and cls._match("notyandexmail.com") == (),
          "%s / %s" % (cls._match("www.yandex.com"), cls._match("notyandexmail.com")))
    check("…while a LABEL kind still has its punctuation stripped",
          cls.pats["zone"] == {"ru": ["zoned"]} and cls._match("x.ru") == ["zoned"], json.dumps(cls.pats["zone"]))
    check("…and the node ships that operand to Kernel-SNI unchanged, so the two engines agree",
          (N._xts_ops({}, {"c": ["yandex."]})[0]["c"]) == ["yandex."],
          json.dumps(N._xts_ops({}, {"c": ["yandex."]})[0]))

    # WITHIN one Tier-2 kind, the longest matching operand wins. A dict would answer with whichever key the
    # JSON listed first, which is the emergent order §1.4 forbids — and a panel that wrote its buckets in a
    # different order would then route the same rules differently.
    json.dump({"contains": {"short": ["goo"], "longest": ["google"], "mid": ["googl"]}},
              open(N.SNI_PATTERNS_PATH, "w"))
    cls.pat_mtime = None
    cls._reload()
    check("within a Tier-2 kind the LONGEST matching operand wins",
          cls._match("www.google.com") == ["longest"], repr(cls._match("www.google.com")))
    check("…and it is ordered at reload, not left to the file's key order",
          [o for o, _ in cls.pats["contains"]] == ["google", "googl", "goo"],
          repr(cls.pats["contains"]))

    # ── SNI_KINDS IS A LOADING LIST; `_match` IS WHAT LOWERS ──────────────────────────────────────────────
    # The failure this phase was warned about: a kind added to the tuple loads its bucket and routes nothing.
    # Asserted from the OTHER side — every kind the loader knows must be reachable through _match — because
    # that is the direction that fails silently.
    probe = {"any": "a.kindprobe.b", "first": "kindprobe.example", "zone": "x.kindprobe",
             "starts": "kindprobefoo.example", "ends": "foo.zzkindprobe", "contains": "a.xkindprobex.io"}
    check("every kind in SNI_KINDS has a probe here", sorted(probe) == sorted(S.SNI_KINDS),
          repr(sorted(S.SNI_KINDS)))
    for kind in S.SNI_KINDS:
        json.dump({kind: {"solo": ["kindprobe"]}}, open(N.SNI_PATTERNS_PATH, "w"))
        cls.pat_mtime = None
        cls._reload()
        check("`%s` is LOWERED by _match, not merely loaded" % kind,
              cls._match(probe[kind]) == ["solo"], probe[kind] + " → " + repr(cls._match(probe[kind])))

    # ── THE NODE'S TIER-2 BOUND (§12.1, widened to a node TOTAL) ─────────────────────────────────────────
    # Tier 2 is the only cost in this matcher that grows with the operand count, and it is one flat scan
    # across every category the node routes — so the thing that has to be bounded is a node total, not a
    # per-interface number. The panel has §12.1's per-interface gate; this is the node holding on its own.
    check("the node's Tier-2 kinds are swg-sni's, in swg-sni's order",
          N._SNI_TIER2_KINDS == S.SNI_TIER2, repr(N._SNI_TIER2_KINDS) + " vs " + repr(S.SNI_TIER2))

    # THE OTHER TWIN ACROSS THESE TWO FILES, and until this line only a comment held it. swg-noded CREATES the
    # per-category learned set and writes the nft rule that reads it; swg-sni ADDS elements to a name it
    # derives itself. Diverge the two sanitisers and every `nft add element` fails — which swg-sni handles by
    # forgetting the IP so it re-learns, so every single connection is learned afresh and RESET afresh, for
    # ever, while `sni_alive` still reports healthy and the operator sees sites that will not load.
    # Not hypothetical punctuation: block categories are `blku:<tier>:<hash>`, so the regex runs in anger on a
    # live fleet, and the two would have to agree about every character class they collapse.
    for _cat in ("custom_a4b88ea4f6", "blku:host:9f2c1d", "telegram", "MC:Geo-IP.CN", "ru", "a b/c"):
        check("swg-sni and swg-noded name %r's learned set identically" % _cat,
              S._learnsetname(_cat) == N._smart_learnsetname(_cat),
              S._learnsetname(_cat) + " vs " + N._smart_learnsetname(_cat))

    # DISTINCT OPERANDS, not rows: the scan tests an operand once however many categories claim it.
    shared = {"starts": {"c1": ["sharedop"], "c2": ["sharedop"]}}
    _, notes = N._sni_tier2_cap(shared, cap=1)
    check("an operand two categories claim costs ONE slot, not two", notes["missed"] == 0, json.dumps(notes))

    # Tier 1 is dict lookups — flat, and untouched by a bound written for the scan.
    t1 = {"zone": {"c": ["ru", "io", "de"]}, "contains": {"c": ["aaaa", "bbb"]}}
    capped, notes = N._sni_tier2_cap(t1, cap=1)
    # `.get`, not `[...]`: sweeping a Tier-1 kind into the bound DELETES the key, and a KeyError here would
    # kill the run before the cases below it ever report.
    check("Tier 1 passes the bound untouched", capped.get("zone") == {"c": ["ru", "io", "de"]}, json.dumps(capped))
    check("…while Tier 2 is cut to the budget", capped.get("contains") == {"c": ["aaaa"]}, json.dumps(capped))
    check("…and the miss is counted, the category named and the operand itself reported",
          notes == {"capped": ["c"], "missed": 1, "sample": [["contains", "bbb"]]}, json.dumps(notes))

    # A REPORTED OPERAND IS BOUNDED. Nothing caps how LONG a Tier-2 operand may be — the classifier has a
    # 3-character floor and no ceiling — so an unbounded sample would carry a pasted five-thousand-character
    # string into smart_status on every sync and into a one-line health note.
    _long = {"contains": {"c": ["x" * 500, "ok" + "y" * 5]}}
    _, _n = N._sni_tier2_cap(_long, cap=0)
    check("a reported operand is truncated to the report's bound",
          max(len(o) for _, o in _n["sample"]) == N._SNI_CAP_OPLEN, json.dumps([len(o) for _, o in _n["sample"]]))
    check("…and says so, rather than looking like a shorter pattern that exists",
          [o for _, o in _n["sample"] if len(o) == N._SNI_CAP_OPLEN][0].endswith("…"),
          json.dumps(_n["sample"][0]))
    check("…while one that fits is reported verbatim",
          any(o == "ok" + "y" * 5 for _, o in _n["sample"]), json.dumps(_n["sample"]))

    # THE CUT IS IN SWG-SNI'S SCAN ORDER, which is what makes it safe: everything that survives would have
    # beaten everything dropped, so no hostname that still matches changes category.
    mix = {"starts": {"cs": ["ssssssss", "sss"]}, "ends": {"ce": ["eeeeeeee"]},
           "contains": {"cc": ["cccccccc"]}}
    capped, notes = N._sni_tier2_cap(mix, cap=2)
    check("the cut follows the scan: kinds in order, longest operand first",
          capped == {"starts": {"cs": ["ssssssss", "sss"]}}, json.dumps(capped))
    check("…and the report names both categories that lost everything",
          notes == {"capped": ["cc", "ce"], "missed": 2,
                    "sample": [["ends", "eeeeeeee"], ["contains", "cccccccc"]]}, json.dumps(notes))

    # END TO END: what the node WRITES under the bound is what swg-sni scans. A cap that trimmed a count and
    # not the file would report a truncation that never happened, and vice versa.
    N._SNI_TIER2_MAX = 2                               # reach the branch without needing a thousand operands
    N._ensure_sni_router({}, ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600, patterns=mix)
    on_disk = json.load(open(N.SNI_PATTERNS_PATH))
    check("the bounded buckets are what reaches the file", on_disk == {"starts": {"cs": ["sss", "ssssssss"]}},
          json.dumps(on_disk))
    check("…and the node reports the truncation to the panel",
          (N._SMART_MODE.get("sni_cap") or {}).get("missed") == 2, json.dumps(N._SMART_MODE.get("sni_cap")))
    cls.pat_mtime = None
    cls._reload()
    check("a surviving operand still routes", cls._match("ssssssssx.example") == ["cs"],
          repr(cls._match("ssssssssx.example")))
    check("a dropped one routes nothing — and does so on the node, not in a counter",
          cls._match("x.eeeeeeee") == () and cls._match("x.cccccccc.y") == (),
          repr(cls._match("x.eeeeeeee")) + " " + repr(cls._match("x.cccccccc.y")))

    # A stale truncation count outliving its rules would be a lie in the one place the operator looks.
    N._ensure_sni_router({}, ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600,
                         patterns={"contains": {"cc": ["cccccccc"]}})
    check("the report clears when the patterns fit again", "sni_cap" not in N._SMART_MODE,
          json.dumps(N._SMART_MODE.get("sni_cap")))

    # …and when the node leaves this engine altogether, which is the OTHER way a truncation count outlives
    # its rules: every non-sni branch of reconcile_cascade calls this to stop the classifier, and a report
    # left standing there would attribute a Hybrid-SNI truncation to a node no longer running Hybrid SNI.
    N._ensure_sni_router({}, ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600, patterns=mix)
    _armed = bool(N._SMART_MODE.get("sni_cap"))
    N._ensure_sni_router(None, [], {"errors": [], "changed": 0})
    check("…and when the node leaves the engine, having first been armed",
          _armed and "sni_cap" not in N._SMART_MODE, json.dumps(N._SMART_MODE.get("sni_cap")))

    print()
    if FAILS:
        print("FAILED: " + "; ".join(FAILS))
        return 1
    print("✓ hybrid patterns: all six kinds lower, the §1.4 ladder decides every overlap, and the Tier-2\n"
          "  scan is bounded node-wide in the order swg-sni actually scans it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
