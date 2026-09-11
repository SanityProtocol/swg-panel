#!/usr/bin/env python3
"""Self-test for zone lowering — `*.ru` on Force-DNS and Hybrid SNI (ROUTING-RULE-BUILDER-PLAN, Phase 2).

One panel half and TWO node halves, and all three must agree:

  PANEL       cascade_plan buckets a rule's patterns by kind into `smart.patterns[cat] = {zone:[…], …}`,
              storing the canonical operand (`*.ru` → `ru`). No node ever classifies anything; each lowers a
              bucket it was handed.
  FORCE-DNS   _ensure_smart_dnsmasq merges the `zone` bucket into dom_sets, where a one-label name is just
              another key — dnsmasq's `nftset=/ru/…` matches `ru` and everything under it, which IS the zone.
  HYBRID SNI  _ensure_sni_router writes the buckets to `sni-patterns.json`, a file of its own beside the
              domain map, keyed by KIND, and swg-sni matches `zone` against the hostname's LAST LABEL.

The assertion that matters most is the NEGATIVE one, and it is made against both engines. `*.ru` must route
`x.ru` and must NOT route `sub.ruble.com`: both match on label boundaries, so `ru` never reaches `ruble.com` —
which is exactly the difference between a zone and the substring an xt_string engine would have made of the
same two bytes. That is why zones travel in their own channel, and why Kernel-SNI is handed none of them.

Run:  python3 tests/zone_lowering_selftest.py          (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("   " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class _Alive:
    """Stands in for a running swg-sni: `poll()` → None means alive, so the writer under test writes its files
    and returns instead of trying to launch a classifier. `_SNI_PROC["ttl"]` has to be set to match, or the
    writer decides the TTL flipped, terminates this and goes looking for a swg-sni to exec — which on a node
    it would find."""
    def poll(self):
        return None


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, os.path.abspath(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    P = load(SERVER, "swgpanel")

    # ── PANEL: a rule's patterns are bucketed by kind, as operands ────────────────────────────────────────
    rules = [{"enabled": True, "category": "custom", "action": "block",
              "domains": ["keep.example"], "cidrs": [], "patterns": ["*.ru", "*.io"]}]
    kept, err, _ = P._validate_routing(rules, {}, "n1")
    check("a zone survives validation as a written pattern",
          err is None and kept[0].get("patterns") == ["*.ru", "*.io"], json.dumps(kept))

    nodes = {"n1": {"name": "a", "routing_mode": "forcedns", "stats_file": "s.json",
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": kept}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.9.0.0/24", "listen_port": 1}, "peers": []}}}}
    plan = P.cascade_plan(nodes, snaps)["n1"]
    cat = plan["smart"][0]["category"]
    check("the panel buckets zones by kind, as operands",
          (plan["patterns"].get(cat) or {}).get("zone") == ["ru", "io"], json.dumps(plan["patterns"]))
    check("…and never merges them into `domains`",
          plan["domains"].get(cat) == ["keep.example"], json.dumps(plan["domains"]))

    # ── NODE: the zone bucket is lowered into dnsmasq, and ONLY there ─────────────────────────────────────
    N = load(NODED, "swgnoded")
    tmp = tempfile.mkdtemp(prefix="zone-")
    N.DNSMASQ_CONF = os.path.join(tmp, "smart-dnsmasq.conf")
    N.GEO_DIR = tmp
    N.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    N._dnsmasq_running = lambda: True
    N._ensure_smart_dnsmasq(plan["domains"], plan["smart"], {"errors": [], "changed": 0},
                            zones=(plan["patterns"].get(cat) or {}).get("zone")
                            and {cat: plan["patterns"][cat]["zone"]} or {})
    conf = open(N.DNSMASQ_CONF).read()
    print("   dnsmasq config:\n     " + "\n     ".join(conf.strip().split("\n")[:4]))

    # ── WHAT IT LOWERED (§10.5 item 4), the engine the item said says NOTHING AT ALL ──────────────────────
    # Force-DNS has no cap to report against — a zone is one more dnsmasq key — so the only thing it can
    # honestly report is what it built. Distinct KEYS, because two rules claiming `ru` merge into one
    # directive (the merge above), and reporting 2 would be counting rules while calling them patterns.
    # Isolated on its own conf path: the block below re-runs the builder, and the checks further down read
    # `conf` from the run above (the mistake the hybrid twin of this block made first).
    _real_conf = N.DNSMASQ_CONF
    try:
        N.DNSMASQ_CONF = os.path.join(tmp, "lowered-probe.conf")
        N._SMART_MODE["engine"] = "dns"          # this branch also serves IP-only; the report is engine-guarded
        N._ensure_smart_dnsmasq({"catA": ["keep.example"]}, plan["smart"], {"errors": [], "changed": 0},
                                zones={"catA": ["ru", "shared"], "catB": ["shared"], "catC": []})
        _probe = open(N.DNSMASQ_CONF).read()
        check("Force-DNS reports the zone keys it built",
              N._SMART_MODE.get("lowered") == {"zone": 2}, json.dumps(N._SMART_MODE.get("lowered")))
        check("…and every counted key is actually in the config it wrote",
              all(("/" + z) in _probe or ("/" + z + "/") in _probe for z in ("ru", "shared")), _probe[:200])
        # AN ENGINE SETS ITS REPORT AND NEVER CLEARS IT — the dispatch pops `lowered` once per pass, before
        # choosing an engine. It has to be that way round: each branch installs one engine and then TEARS THE
        # OTHER TWO DOWN, and this function is one of those teardowns (`_ensure_smart_dnsmasq({}, [], …)` runs
        # in both SNI branches). A clear in here would wipe the running engine's report one line after it
        # wrote it. So what this asserts is the half that IS this function's job: with nothing to build, it
        # invents no report.
        # …and an IP-ONLY node reports nothing even when zone keys reach this function. The dispatch's
        # `else` branch serves Force-DNS AND IP-only, and still calls this when a DNSMASQ_CONF survives from
        # an earlier mode; patterns deliberately survive `_ip_only` upstream. So the keys can be here on a
        # node with no host layer, and saying "matching 6 patterns" there would be false — invisibly, since
        # the panel hides host health on IP-only.
        N._SMART_MODE.pop("lowered", None)
        _eng = N._SMART_MODE.get("engine")
        N._SMART_MODE["engine"] = "none"
        N._ensure_smart_dnsmasq({"catA": ["keep.example"]}, plan["smart"], {"errors": [], "changed": 0},
                                zones={"catA": ["ru", "shared"]})
        check("an IP-only node reports no patterns even when zone keys reach the builder",
              "lowered" not in N._SMART_MODE, json.dumps(N._SMART_MODE.get("lowered")))
        N._SMART_MODE["engine"] = _eng

        N._SMART_MODE.pop("lowered", None)
        N._ensure_smart_dnsmasq({"catA": ["keep.example"]}, plan["smart"], {"errors": [], "changed": 0}, zones={})
        check("…and a node with no zones reports nothing rather than zero",
              "lowered" not in N._SMART_MODE, json.dumps(N._SMART_MODE.get("lowered")))
    finally:
        N.DNSMASQ_CONF = _real_conf
    setn = N._smart_setname(cat)

    def names_for(setname, text=None):
        """Every domain dnsmasq is told to put in this set. `text` defaults to the config read most recently —
        pass it explicitly after a rebuild, or this answers about the previous one."""
        out = set()
        for line in (text if text is not None else conf).split("\n"):
            if not line.startswith("nftset=/") or ("#" + setname) not in line:
                continue
            body = line[len("nftset=/"):].rsplit("/4#", 1)[0]
            out |= {d for d in body.split("/") if d}
        return out

    got = names_for(setn)
    check("the zone label reaches dnsmasq", "ru" in got and "io" in got, sorted(got))
    check("the ordinary domain is still there", "keep.example" in got, sorted(got))

    # ── THE NEGATIVE: a zone is a label boundary, never a substring ───────────────────────────────────────
    # dnsmasq matches nftset=/ru/ against `ru` and `*.ru` — never `ruble.com`. This asserts the shape the
    # config takes, which is what decides that: a bare label, not a pattern the resolver could widen.
    check("`ru` is emitted as a whole label, not a fragment",
          re.search(r"(^|/)ru(/|$)", conf.split("4#")[0]) is not None
          and "ruble" not in conf, conf[:200])
    check("nothing resembling sub.ruble.com is in the config", "ruble.com" not in conf)

    # ── `domains` is handed NOTHING ──────────────────────────────────────────────────────────────────────
    # A bare label reaching xt_string through `domains` is a catastrophic substring, and swg-sni's suffix walk
    # would never look one up. Both engines are served instead from the pattern channel, in the form each can
    # run — which is only possible because the label never enters the list all three of them read.
    check("zones are not in the domains dict any engine reads",
          not any("ru" == d or "io" == d for v in plan["domains"].values() for d in v),
          json.dumps(plan["domains"]))

    # ── the DRIFT SIGNATURE must move with the zones, or a zone-only edit is skipped before it is written ─
    # This is the guard the direct call below cannot see: _ensure_smart_dnsmasq is only reached with
    # unchanged=False when the signature says something changed, and a zone edit changes no domain.
    e, d, f = plan["smart"], plan["domains"], {}
    check("the signature moves when only the zones change",
          N._dom_signature(e, d, {cat: ["ru"]}, f) != N._dom_signature(e, d, {cat: ["de"]}, f))
    check("…and is stable when nothing changes",
          N._dom_signature(e, d, {cat: ["ru"]}, f) == N._dom_signature(e, d, {cat: ["ru"]}, f))
    check("…and an empty zone set reads the same as none at all",
          N._dom_signature(e, d, {}, f) == N._dom_signature(e, d, None, f))

    # ── a zone-only change must rebuild the config, or the edit never lands ───────────────────────────────
    before = conf
    N._ensure_smart_dnsmasq(plan["domains"], plan["smart"], {"errors": [], "changed": 0}, zones={cat: ["de"]})
    after = open(N.DNSMASQ_CONF).read()
    check("changing only the zones rewrites the config",
          after != before and "de" in names_for(setn, after) and "ru" not in names_for(setn, after),
          "unchanged" if after == before else json.dumps(sorted(names_for(setn, after))))

    # ── NODE, THE OTHER ENGINE: the same bucket, lowered for Hybrid SNI ──────────────────────────────────
    # swg-sni is a separate program, so this is the one place the two files are read by the code that
    # actually consumes them: swg-noded writes, swg-sni looks up. `nft` never runs — the assertion is about
    # which categories a hostname resolves to, which is decided before anything is added to a set.
    N.SNI_MAP_PATH = os.path.join(tmp, "sni-map.json")
    N.SNI_PATTERNS_PATH = os.path.join(tmp, "sni-patterns.json")
    N._SNI_PROC["p"], N._SNI_PROC["ttl"] = _Alive(), 3600   # a live classifier AT THIS TTL → the writer launches none
    # DERIVED from the plan by the node's own transpose, not hand-built: a bucket assembled by the test is a
    # bucket the transpose could be getting wrong. A kind nothing lowers rides along, to hold the wire format's
    # forward-compat contract. It used to be `starts`, which Phase 4 shipped — so it is now a NAME NO PHASE WILL
    # EVER EMIT, because the only kinds left are ones this build lowers and the contract still has to be tested.
    _plan_smart = {"patterns": {cat: dict(plan["patterns"][cat], somefuturekind=["nothinglowersthis"])}}
    zbucket = N._pattern_buckets(_plan_smart)
    check("the node transposes the panel's buckets kind-first",
          zbucket == {"zone": {cat: ["ru", "io"]}, "somefuturekind": {cat: ["nothinglowersthis"]}},
          json.dumps(zbucket))
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600, patterns=zbucket)
    check("the buckets are written to a file of their OWN, keyed by kind",
          json.load(open(N.SNI_PATTERNS_PATH)) == {"zone": {cat: ["io", "ru"]},
                                                   "somefuturekind": {cat: ["nothinglowersthis"]}},
          open(N.SNI_PATTERNS_PATH).read())
    check("…and never into the domain map swg-sni suffix-matches",
          json.load(open(N.SNI_MAP_PATH)) == {cat: ["keep.example"]}, open(N.SNI_MAP_PATH).read())

    S = load(os.path.join(HERE, "..", "swg-sni"), "swgsni")
    cls = S.Classifier.__new__(S.Classifier)               # no flusher thread, no nft: only the lookup is under test
    cls.map_path, cls.pat_path = N.SNI_MAP_PATH, N.SNI_PATTERNS_PATH
    cls.map_mtime = cls.pat_mtime = None
    cls.dom2cat, cls.pats = {}, S._empty_pats()
    cls._reload()
    check("swg-sni loads the zones", cls.pats["zone"] == {"ru": [cat], "io": [cat]}, json.dumps(cls.pats))
    check("…and IGNORES a kind it cannot lower", "somefuturekind" not in cls.pats, json.dumps(sorted(cls.pats)))
    check("a host in the zone matches", cls._match("x.ru") == [cat], repr(cls._match("x.ru")))
    check("…including the bare zone name itself", cls._match("ru") == [cat], repr(cls._match("ru")))
    check("…and a trailing dot does not defeat it", cls._match("x.ru.") == [cat], repr(cls._match("x.ru.")))
    check("THE NEGATIVE: sub.ruble.com is not in the .ru zone",
          cls._match("sub.ruble.com") == (), repr(cls._match("sub.ruble.com")))
    check("…nor is any other name merely containing the label",
          cls._match("ru.example.org") == () and cls._match("rugby.io.example") == (),
          repr(cls._match("ru.example.org")) + " " + repr(cls._match("rugby.io.example")))
    check("an ordinary domain still matches by suffix", cls._match("a.keep.example") == [cat])

    # A domain key is MORE SPECIFIC than a zone and must win outright — same rule dnsmasq's longest-suffix
    # match gives, so the two engines answer a name covered by both the same way.
    json.dump({"deep": ["keep.example"], "zoned": ["example"]}, open(N.SNI_MAP_PATH, "w"))
    json.dump({"zone": {"zoned": ["example"]}}, open(N.SNI_PATTERNS_PATH, "w"))
    cls.map_mtime = cls.pat_mtime = None; cls._reload()
    check("a domain key beats a zone that also covers the name",
          cls._match("a.keep.example") == ["deep"], repr(cls._match("a.keep.example")))
    check("…and the zone still catches what no domain key covers",
          cls._match("other.example") == ["zoned"], repr(cls._match("other.example")))

    # Absence IS the empty set, at both ends: the writer removes the file when the last zone rule goes, and
    # the reader must then stop matching zones rather than keep the copy it had.
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600, patterns={})
    check("dropping the last pattern removes the file", not os.path.exists(N.SNI_PATTERNS_PATH))
    cls._reload()
    check("…and swg-sni stops matching the zone", cls.pats["zone"] == {} and cls._match("x.ru") == (),
          json.dumps(cls.pats))
    r = {"errors": [], "changed": 0}
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], r, 3600, patterns={})
    check("a node with no patterns reports no change every cycle", r["changed"] == 0, json.dumps(r))

    # A ZONE-ONLY EDIT moves no domain, so the map is written byte-identical and its mtime does not change.
    # The reload has to gate on BOTH files or swg-sni goes on routing the zones it had until something
    # unrelated touches the map — which, on a settled node, is never.
    N._ensure_sni_router(plan["domains"], ["10.9.0.0/24"], {"errors": [], "changed": 0}, 3600,
                         patterns={"zone": {cat: ["de"]}})
    cls._reload()
    check("a zone-only edit is picked up, with the domain map unmoved",
          cls._match("x.de") == [cat] and cls._match("x.ru") == (), json.dumps(cls.pats))

    # ── THE TWO FILES ARE PARSED INDEPENDENTLY ───────────────────────────────────────────────────────────
    # They arrive as two separate writes, so one being unreadable says nothing about the other. A patterns
    # file that does not parse must not freeze the DOMAIN map with it — that would take a node's ordinary
    # routing down over a bucket it may not even use — and the patterns it already had are kept rather than
    # dropped, which routes what it was routing a second ago and never more.
    with open(N.SNI_PATTERNS_PATH, "w") as f:
        f.write("{ this is not json")
    json.dump({"fresh": ["moved.example"]}, open(N.SNI_MAP_PATH, "w"))
    cls._reload()
    check("a broken patterns file does not freeze the domain map",
          cls._match("a.moved.example") == ["fresh"], repr(cls._match("a.moved.example")))
    check("…and the patterns already loaded are kept, not dropped",
          cls._match("x.de") == [cat], json.dumps(cls.pats))

    # ── A RULE WHOSE ONLY CONTENT IS A PATTERN ───────────────────────────────────────────────────────────
    # THE SHAPE EVERY FIXTURE ABOVE AVOIDS. Every rule in this file carries `domains: ["keep.example"]`
    # alongside its patterns, and that is the whole reason this file passed while `*.ru` on its own routed
    # nothing on a real node: two separate guards — cascade_plan's `if not doms and not cidrs` and
    # _ensure_smart_dnsmasq's `want = bool(domains and subnets)` — were written when no engine could lower a
    # pattern, and neither was revisited when Phase 2 gave `zone` a datapath. The panel accepted the rule,
    # rendered a live amber badge for it, stored it, and dropped it at plan time; the node, had it ever been
    # reached, would have torn down the resolver meant to serve it. Silent at both ends.
    #
    # A pattern alone in a rule is not an edge case — it is the first thing an operator does with the field.
    # So it is asserted here as its own shape, at BOTH ends, rather than being assumed to follow from the
    # mixed rule: a guard that tests `domains` cannot be caught by a fixture that always supplies one.
    only = [{"enabled": True, "category": "custom", "action": "block",
             "domains": [], "cidrs": [], "patterns": ["*.ru"]}]
    kept1, err1, _ = P._validate_routing(only, {}, "n1")
    check("a patterns-only rule survives validation", err1 is None and len(kept1) == 1, json.dumps(kept1))
    nodes1 = {"n1": {"name": "a", "routing_mode": "forcedns", "stats_file": "s.json",
                     "ifaces": {"awg0": {"egress_mode": "smart", "routing": kept1}}}}
    # `.get`, not `[...]`: when this regresses the node drops out of the plan ENTIRELY, and a KeyError
    # traceback here would report a broken test instead of the defect — and would skip every check below it.
    plan1 = P.cascade_plan(nodes1, snaps).get("n1") or {}
    smart1 = plan1.get("smart") or []
    check("a patterns-only rule REACHES THE PLAN", len(smart1) == 1,
          "the rule is dropped at plan time — it routes nothing and says nothing" if not smart1
          else json.dumps(smart1))
    cat1 = smart1[0]["category"] if smart1 else None
    check("…and carries its zone bucket",
          bool(cat1) and ((plan1.get("patterns") or {}).get(cat1) or {}).get("zone") == ["ru"],
          json.dumps(plan1.get("patterns")))
    # It must still get a set of ITS OWN. `tld`'s real failure was not that it named a set, it was that every
    # rule named the SAME one; custom_cat_id hashing the patterns is what keeps that from coming back.
    other = [{"enabled": True, "category": "custom", "action": "block",
              "domains": [], "cidrs": [], "patterns": ["*.de"]}]
    nodes2 = {"n1": dict(nodes1["n1"], ifaces={"awg0": {"egress_mode": "smart",
                                                        "routing": P._validate_routing(other, {}, "n1")[0]}})}
    cat2 = (P.cascade_plan(nodes2, snaps)["n1"]["smart"] or [{}])[0].get("category")
    check("two patterns-only rules do not collapse into one shared set", bool(cat1) and cat1 != cat2,
          "%s vs %s" % (cat1, cat2))
    # And the node half, driven with the plan the panel now actually produces.
    zonly = {cat1: plan1["patterns"][cat1]["zone"]} if cat1 else {}
    N._ensure_smart_dnsmasq({}, plan1["smart"], {"errors": [], "changed": 0}, zones=zonly)
    conf1 = open(N.DNSMASQ_CONF).read() if os.path.exists(N.DNSMASQ_CONF) else ""
    check("the node CONFIGURES dnsmasq for zones with no domains at all",
          "nftset=" in conf1 and "ru" in names_for(N._smart_setname(cat1), conf1) if cat1 else False,
          "config torn down" if not conf1 else conf1.strip().split("\n")[-1])
    # The teardown that guard exists for must still happen when there is genuinely nothing to fill.
    N._ensure_smart_dnsmasq({}, plan1["smart"], {"errors": [], "changed": 0}, zones={})
    check("…and still tears down when there is nothing to fill at all",
          not os.path.exists(N.DNSMASQ_CONF), "config left behind")

    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
