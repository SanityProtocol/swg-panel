#!/usr/bin/env python3
"""Self-test for `contains` lowering — `*google*` on Kernel SNI (ROUTING-RULE-BUILDER-PLAN, Phase 3).

One panel half and one node half, and they must agree:

  PANEL       cascade_plan buckets a rule's patterns by kind into `smart.patterns[cat] = {contains:[…], …}`,
              storing the canonical operand (`*google*` → `google`). No node classifies anything.
  KERNEL SNI  _ensure_smart_xtstring merges the `contains` bucket with the category's domains into ONE list
              of xt_string operands — to Boyer-Moore over a ClientHello a domain and a substring are the
              same rule — and builds `-m string` rules from it.

THE POINT OF THE KIND. xt_string asks only "do these bytes appear anywhere", so `contains` is the one
Tier-2 shape it answers NATIVELY and `starts` / `ends` / `zone` are refused outright: there is no anchor at
either end to hang them on (§4.1). The negative assertion here is therefore the mirror of the zone one —
`*google*` is SUPPOSED to match notgoogle.com, and what must not happen is a kind this engine cannot anchor
arriving in the same list and silently behaving as a substring.

Four things this covers that reading the diff does not:
  · a category with ONLY a contains is a real category — entry, ipset, counting chain, signature. The old
    line filtered on `domains.get(cat)` and would have dropped it at the first statement;
  · the shared budget: patterns take their slots FIRST, so a long auto-fetched list cannot push out the one
    line an operator wrote;
  · the drift signature moves when only the contains change (the zone-only-edit trap, on this engine);
  · an operand xt_string cannot install (>128 bytes) is dropped and REPORTED, not left to fail — one
    refused rule leaves the signature unwritten and rebuilds the whole chain every cycle for ever.

Run:  python3 tests/contains_lowering_selftest.py          (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
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


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def main():
    P = load(SERVER, "swgpanel")

    # ── PANEL: the pattern survives, and is bucketed by kind as its operand ──────────────────────────────
    rules = [{"enabled": True, "category": "custom", "action": "block",
              "domains": ["keep.example"], "cidrs": [], "patterns": ["*google*", "*.ru"]}]
    kept, err, _ = P._validate_routing(rules, {}, "n1")
    check("a contains survives validation as a written pattern",
          err is None and kept[0].get("patterns") == ["*google*", "*.ru"], json.dumps(kept))

    nodes = {"n1": {"name": "a", "routing_mode": "sni_kernel", "stats_file": "s.json",
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": kept}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.9.0.0/24", "listen_port": 1}, "peers": []}}}}
    plan = P.cascade_plan(nodes, snaps)["n1"]
    cat = plan["smart"][0]["category"]
    check("the panel buckets it by kind, as the operand",
          (plan["patterns"].get(cat) or {}).get("contains") == ["google"], json.dumps(plan["patterns"]))
    # The panel ships EVERY kind and lets each engine take what it can run — the capability matrix lives
    # beside the lowering, never in a second copy here (§8, open item 5).
    check("…and ships the zone alongside it, for the engine that can run one",
          (plan["patterns"].get(cat) or {}).get("zone") == ["ru"], json.dumps(plan["patterns"]))
    check("…and never merges either into `domains`",
          plan["domains"].get(cat) == ["keep.example"], json.dumps(plan["domains"]))

    # ── NODE ────────────────────────────────────────────────────────────────────────────────────────────
    N = load(NODED, "swgnoded")
    tmp = tempfile.mkdtemp(prefix="contains-")
    N.GEO_DIR = tmp
    added = []

    def fake_run(args, *a, **kw):
        if (args[:1] == ["iptables"] and "-A" in args) or args[:2] == ["ipset", "create"]:
            added.append(args)
        if args[:1] == ["iptables"] and "-C" in args:
            return _R(1)                              # never hooked → always the rebuild path
        if args[:2] == ["ipset", "list"]:
            return _R(0, "")
        return _R(0)
    N.run = fake_run

    def strings_for(prefix=""):
        """Every distinct `--string` operand the chain was told to match, in the order first emitted."""
        out = []
        for a in added:
            if "--string" in a:
                v = a[a.index("--string") + 1]
                if v.startswith(prefix) and v not in out:
                    out.append(v)
        return out

    # DERIVED from the plan by the node's own transpose, never hand-built: a bucket the test assembles is a
    # bucket the transpose could be getting wrong (the reason _pattern_buckets exists).
    pats = N._pattern_buckets({"patterns": plan["patterns"]})
    check("the node transposes the panel's buckets kind-first",
          pats == {"contains": {cat: ["google"]}, "zone": {cat: ["ru"]}}, json.dumps(pats))

    ents = [{"subnet": "10.9.0.0/24", "category": cat, "table": 7000}]
    N._ensure_smart_xtstring(ents, plan["domains"], 0x9999, {"errors": [], "changed": 0},
                             ttl=3600, contains=pats.get("contains"))
    ops = strings_for()
    print("   chain operands:", ops)
    check("the contains operand becomes an xt_string rule", "google" in ops, json.dumps(ops))
    check("the ordinary domain is still there", "keep.example" in ops, json.dumps(ops))

    # ── THE NEGATIVE: only `contains` is lowered here ───────────────────────────────────────────────────
    # A zone is a label, and to xt_string a label is a substring matching every ClientHello that carries
    # those bytes anywhere — `ru` would catch ruble.com, brutal.io and truecaller.com. The panel ships the
    # bucket regardless; refusing to lower it is this engine's own knowledge, and this is where it is held.
    check("THE NEGATIVE: the zone bucket is NOT lowered into the scanner", "ru" not in ops, json.dumps(ops))
    check("…and nothing else reached the chain at all",
          set(ops) == {"google", "keep.example"}, json.dumps(ops))

    # ── a contains-ONLY category is a real category ─────────────────────────────────────────────────────
    # The line this replaced was `if domains.get(e["category"])`, which drops such a category at the first
    # statement: no entry, no ipset, no counting chain, no rules — a saved rule and a shipped bucket that
    # route nothing, with nothing anywhere saying so.
    added.clear()
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "conly", "table": 7001}],
                             {}, 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={"conly": ["deepstate"]})
    check("a category with ONLY a contains still builds its rules",
          "deepstate" in strings_for(), json.dumps(strings_for()))
    check("…and creates its ipset", any(a[:2] == ["ipset", "create"] and "swgk_conly" in a for a in added),
          json.dumps([a for a in added if a[:1] == ["ipset"]]))

    # ── the SHARED budget, patterns first ───────────────────────────────────────────────────────────────
    # One budget, because a separate one would double the chain length the cap exists to bound. Something
    # has to lose when a category is over it, and it must not be the line the operator typed: a list is bulk
    # and arrives by itself, a contains is one deliberate decision.
    big = ["h%03d.example" % i for i in range(N._XTS_CAP + 50)]
    added.clear()
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "bigcat", "table": 7002}],
                             {"bigcat": big}, 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={"bigcat": ["mine"]})
    got = strings_for()
    check("the budget is SHARED — patterns plus names, capped once",
          len(got) == N._XTS_CAP, "%d operands, cap %d" % (len(got), N._XTS_CAP))
    check("…and the operator's own pattern is the one that survives",
          got[0] == "mine" and "mine" in got, json.dumps(got[:3]))
    check("…so the list is the half that loses a slot",
          "h%03d.example" % (N._XTS_CAP - 1) not in got, json.dumps(got[-2:]))
    cap = N._SMART_MODE.get("xts_cap")
    check("the cap is reported over the WHOLE budget",
          cap and cap.get("capped") == ["bigcat"] and cap.get("missed") == len(big) + 1 - N._XTS_CAP,
          json.dumps(cap))

    # ── the drift signature moves with the contains ─────────────────────────────────────────────────────
    # The guard the direct calls above cannot see. The signature used to be a SECOND expression of the same
    # truncation, computed from `domains` alone: a contains-only edit would have left it identical and the
    # chain would never have been rebuilt — the zone-only-edit trap, on this engine.
    added.clear()
    N._ensure_smart_xtstring(ents, plan["domains"], 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={cat: ["google"]})
    hooked = [True]

    def steady_run(args, *a, **kw):
        if args[:1] == ["iptables"] and "-C" in args:
            return _R(0) if hooked[0] else _R(1)      # hooked → the signature file decides
        return fake_run(args, *a, **kw)
    N.run = steady_run
    added.clear()
    N._ensure_smart_xtstring(ents, plan["domains"], 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={cat: ["google"]})
    check("an unchanged pass rebuilds nothing", not [a for a in added if "--string" in a],
          json.dumps(added[:2]))
    added.clear()
    N._ensure_smart_xtstring(ents, plan["domains"], 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={cat: ["yandex"]})
    check("changing ONLY the contains rebuilds the chain", "yandex" in strings_for(), json.dumps(strings_for()))
    N.run = fake_run

    # ── an operand xt_string cannot install is dropped and REPORTED ─────────────────────────────────────
    # 128 bytes is the kernel's own ceiling (XT_STRING_MAX_PATLEN), measured on a real box: 128 installs,
    # 129 is refused with `STRING too long`. Left to fail, one such rule sets _ok=False, the signature is
    # never written, and every cycle tears the chain down and rebuilds it — for ever, silently.
    added.clear()
    r = {"errors": [], "changed": 0}
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "lc", "table": 7003}],
                             {}, 0x9999, r, ttl=3600,
                             contains={"lc": ["a" * (N._XTS_MAXLEN + 1), "b" * N._XTS_MAXLEN]})
    got = strings_for()
    check("an over-long operand never reaches iptables",
          got == ["b" * N._XTS_MAXLEN], "%d operands" % len(got))
    check("…the one exactly AT the ceiling does", "b" * N._XTS_MAXLEN in got)
    cap = N._SMART_MODE.get("xts_cap")
    check("…and it is reported rather than dropped in silence",
          cap and cap.get("long") == 1 and cap.get("maxlen") == N._XTS_MAXLEN, json.dumps(cap))
    check("…without inventing a truncation that did not happen",
          cap and cap.get("capped") == [] and cap.get("missed") == 0, json.dumps(cap))
    check("…and the chain still commits (no error, no rebuild loop)", not r["errors"], json.dumps(r["errors"]))

    # THE WORST CASE, and the one the first version of this report missed: a category whose ONLY operand is
    # too long. It builds no rules, so it has no entry, so it falls out of `want_cats` — and a report summed
    # over `want_cats` says nothing at all about it. A saved rule, a shipped bucket, no routing and no word
    # anywhere is precisely what this report exists to prevent, so it is counted from what the PANEL asked
    # for rather than from what survived.
    added.clear()
    r = {"errors": [], "changed": 0}
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "allgone", "table": 7004}],
                             {}, 0x9999, r, ttl=3600, contains={"allgone": ["z" * (N._XTS_MAXLEN + 1)]})
    cap = N._SMART_MODE.get("xts_cap")
    check("a category whose ONLY operand is too long still reports it",
          cap and cap.get("long") == 1, json.dumps(cap))
    check("…and builds nothing rather than a broken rule",
          not [a for a in added if "--string" in a], json.dumps(added[:2]))

    # …and a category the node was NOT asked to route is not reported at all: a too-long operand in a bucket
    # no exit rule names is not this node's problem to announce.
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "wanted", "table": 7005}],
                             {"wanted": ["ok.example"]}, 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={"unrouted": ["z" * (N._XTS_MAXLEN + 1)]})
    check("…but an over-long operand in an UNROUTED category is not announced",
          not N._SMART_MODE.get("xts_cap"), json.dumps(N._SMART_MODE.get("xts_cap")))

    # ── the report clears when neither applies ──────────────────────────────────────────────────────────
    N._ensure_smart_xtstring(ents, plan["domains"], 0x9999, {"errors": [], "changed": 0}, ttl=3600,
                             contains={cat: ["google"]})
    check("a node with nothing capped and nothing over-long reports neither",
          not N._SMART_MODE.get("xts_cap"), json.dumps(N._SMART_MODE.get("xts_cap")))

    # ── THE SIGNATURE COVERS THE RULES' SHAPE, NOT JUST THEIR INPUTS ────────────────────────────────────
    # The drift signature decides whether the chain is rebuilt. It used to be a hand-listed set of inputs —
    # subnets, operands, reset mark, ttl — which is a promise that must be re-kept every time the rules
    # change, and it was broken the moment the scan gained its connbytes bound: every rule's TEXT changed and
    # not one input did. An already-running kernel-SNI node upgrading into that fix would have matched its
    # stored signature, taken the steady-state return, and kept the old unconfined rules for ever. So the
    # signature is now of the RENDERED rules, and this asserts the property directly: change the shape, and
    # the signature must move.
    _real_scan = N._xts_scan
    sig_of = lambda: (lambda d: (N._ensure_smart_xtstring(
        [{"subnet": "10.9.0.0/24", "category": "sg", "table": 7}], {"sg": ["x.example"]},
        0x9999, {"errors": [], "changed": 0}, ttl=3600),
        open(os.path.join(d, ".xtstring-sig")).read().strip())[1])(N.GEO_DIR)
    before = sig_of()
    N._xts_scan = lambda subnet: [x for x in _real_scan(subnet) if x != "--connbytes"]   # a shape change
    after = sig_of()
    N._xts_scan = _real_scan
    check("changing the RULE SHAPE moves the signature", before != after,
          "both %s — an upgrade would keep the old rules for ever" % before)
    check("…and the shape restored gives the signature back", sig_of() == before)

    # ── THE SCAN IS CONFINED TO THE HANDSHAKE ───────────────────────────────────────────────────────────
    # An SNI can only be in the handshake, but the rules match `-p tcp --dport 443` — so without a bound they
    # Boyer-Moore every operand against every outbound packet to an unlearned destination, encrypted
    # application data included. A match LEARNS that destination, so a chance hit misroutes an unrelated host
    # for the whole TTL. Over a 1 GB upload a 3-character operand hits with probability ~1.0; confined to the
    # handshake the same operand is ~8e-6 per connection. Without this, §12.1's 3-character floor is a
    # promise this engine cannot keep.
    added.clear()
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "cb", "table": 7008}],
                             {"cb": ["a.example"]}, 0x9999, {"errors": [], "changed": 0},
                             ttl=3600, contains={"cb": ["shortish"]})
    strs = [a for a in added if "--string" in a]
    check("every string rule is bounded to the first packets of a connection",
          strs and all("--connbytes" in a for a in strs),
          "%d of %d rules unbounded" % (sum(1 for a in strs if "--connbytes" not in a), len(strs)))
    check("…in the ORIGINAL direction, counting packets",
          all(a[a.index("--connbytes-dir") + 1] == "original"
              and a[a.index("--connbytes-mode") + 1] == "packets" for a in strs),
          json.dumps(strs[0] if strs else []))
    # The learn rule and the reset rule must carry the SAME match, or one flags a connection the other never
    # learned from. They are built from one helper for that reason; this is what holds the helper in place.
    # ⚠️ THE RESET RULE IS THE ONE THAT FLAGS THE PACKET, and which target that is has moved. It used to be
    # a per-operand `-j CONNMARK --set-mark`; the connection mark is now saved once per entry by a rule that
    # carries no `--string` at all (it costs no Boyer-Moore search — see kernel_sni_marks_selftest [2]), and
    # the flag itself is `-j MARK`. Selecting on the string "CONNMARK" therefore matched nothing and this
    # check went red for the right reason with the wrong name. Selected on the TARGET, positionally, so
    # "CONNMARK" can never be mistaken for "MARK" again.
    tgt = lambda a: (a[a.index("-j") + 1] if "-j" in a else "")
    learn = [a for a in strs if tgt(a) == "SET"]
    reset = [a for a in strs if tgt(a) == "MARK"]
    pre = lambda a: a[:a.index("--string")]
    check("…and the learn and reset rules match identically",
          learn and reset and all(pre(x) == pre(learn[0]) for x in learn + reset),
          json.dumps([pre(learn[0]) if learn else [], pre(reset[0]) if reset else []]))
    # …and the rule that saves the connection mark is deliberately NOT one of them: it is keyed on the mark
    # this chain just wrote, so it needs neither the string nor the connbytes window.
    _save = [a for a in added if "--save-mark" in a]
    check("the ct-mark save carries no string match at all", _save and all("--string" not in a for a in _save),
          json.dumps(_save[:1]))
    # A box without xt_connbytes must not run this engine at all — it degrades to the userspace SNI parser,
    # which reads the parsed hostname and cannot make this mistake. One probe, one meaning.
    N._KSNI["ok"] = None
    _real_run = N.run
    N.run = lambda a, *x, **k: (_R(1) if (a[:1] == ["sh"] and "connbytes" in a[-1]) else _real_run(a, *x, **k))
    check("a box without xt_connbytes is not offered the kernel scanner", not N._kernel_sni_ok())
    N.run = _real_run
    N._KSNI["ok"] = None
    check("…and one with it is", N._kernel_sni_ok())

    # ── THE PATTERN CEILING: a bulk paste must not starve the category's names ───────────────────────────
    # Patterns are taken first, which is right — but taken first WITHOUT A CEILING it becomes its own silent
    # failure in the other direction: 300 pasted substrings would take the whole 256 and a category's entire
    # domain list would never reach the chain. The panel is getting §12.1's per-interface gate, but a node
    # cannot rely on that: an API client can post a plan the panel would have refused.
    ops, notes, _built = N._xts_ops({"c": ["d%04d.example" % i for i in range(500)]},
                            {"c": ["p%03d" % i for i in range(300)]})
    pats = [o for o in ops["c"] if o.startswith("p")]
    dmns = [o for o in ops["c"] if o.startswith("d")]
    check("a 300-pattern paste cannot take the whole budget",
          len(pats) == N._XTS_PAT_MAX, "%d patterns took the budget" % len(pats))
    check("…so the category's names still reach the chain",
          len(dmns) == N._XTS_CAP - N._XTS_PAT_MAX, "%d names survived" % len(dmns))
    check("…and everything that did not fit is counted",
          (notes.get("c") or {}).get("over") == 800 - N._XTS_CAP, json.dumps(notes))

    # ── `over` counts what was LOST, and a duplicate is not a loss ───────────────────────────────────────
    # `total - built` would be the easy way to compute this and it would report a loss that did not happen:
    # a `contains` operand equal to one of the names is ONE rule doing the job of two, not a dropped entry.
    ops, notes, _built = N._xts_ops({"c": ["dup.example", "other.example"]}, {"c": ["dup.example"]})
    check("a cross-channel duplicate becomes one rule",
          ops["c"] == ["dup.example", "other.example"], json.dumps(ops))
    check("…and is NOT reported as something that failed to match", not notes, json.dumps(notes))

    # ── WHAT IT LOWERED, its own channel (§10.5 item 4) ─────────────────────────────────────────────────
    # Every other reading here is about what did NOT fit, so a node building exactly what it was asked said
    # nothing at all. `built` counts the operands that came from the PATTERN channel and reached the chain —
    # after the per-category ceiling, after the dedupe, after the _XTS_MAXLEN drop — so it is a count of the
    # rules, not an echo of the request. It rides beside `notes` rather than inside it because `notes` means
    # "what failed", and putting it there made a clean category look like a failure (the check above).
    ops, notes, built = N._xts_ops({"c": ["a.example"]}, {"c": ["google", "yandex"]})
    check("what reached the chain is counted, not what was asked for",
          built == {"c": 2}, json.dumps(built))
    check("…and a duplicate across the two channels is counted once",
          N._xts_ops({"c": ["dup.example"]}, {"c": ["dup.example"]})[2] == {"c": 1},
          json.dumps(N._xts_ops({"c": ["dup.example"]}, {"c": ["dup.example"]})[2]))
    check("…an operand too long for xt_string is NOT counted as lowered",
          N._xts_ops({}, {"c": ["x" * (N._XTS_MAXLEN + 1)]})[2] == {},
          json.dumps(N._xts_ops({}, {"c": ["x" * (N._XTS_MAXLEN + 1)]})[2]))
    check("…and patterns past the per-category ceiling are not either",
          (N._xts_ops({}, {"c": ["p%03d" % i for i in range(300)]})[2] or {}).get("c") == N._XTS_PAT_MAX,
          json.dumps(N._xts_ops({}, {"c": ["p%03d" % i for i in range(300)]})[2]))
    check("a category with no patterns reports no count at all",
          N._xts_ops({"c": ["a.example"]}, {})[2] == {}, json.dumps(N._xts_ops({"c": ["a.example"]}, {})[2]))

    # ── the built-category list is ANSWERED, not re-derived ──────────────────────────────────────────────
    # reconcile_catk_chain counts bytes with `--match-set swgk_<c>`, so it needs exactly the sets that exist.
    # The call site used to compute that beside the function that had just decided it — one truth, two
    # expressions, and the second one walked the enriched lists all over again.
    built = N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "rc", "table": 7006}],
                                     {"rc": ["a.example"]}, 0x9999, {"errors": [], "changed": 0}, ttl=3600)
    check("the builder answers which categories now have a swgk_ set", built == ["rc"], json.dumps(built))
    # THE STEADY STATE ANSWERS TOO, and this is the path that matters most: it is the one a settled node takes
    # on EVERY cycle. Returning nothing there would hand reconcile_catk_chain an empty list once the chain
    # stopped changing, which tears the per-category byte counters down and rebuilds them for ever — visible
    # only as counters that reset. (Written after perturbing the steady-state return and watching this test
    # stay green: the stub always took the rebuild path, so the case had never been exercised.)
    hooked2 = [True]
    def steady2(args, *a, **kw):
        if args[:1] == ["iptables"] and "-C" in args:
            return _R(0) if hooked2[0] else _R(1)
        return fake_run(args, *a, **kw)
    N.run = steady2
    again = N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "rc", "table": 7006}],
                                     {"rc": ["a.example"]}, 0x9999, {"errors": [], "changed": 0}, ttl=3600)
    N.run = fake_run
    check("…and so does the steady state, which is every cycle on a settled node",
          again == ["rc"], json.dumps(again))

    torn = N._ensure_smart_xtstring([], {}, 0, {"errors": [], "changed": 0}, active=False)
    check("…and a teardown answers with none", torn == [], json.dumps(torn))
    none = N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": "empty", "table": 7007}],
                                    {}, 0x9999, {"errors": [], "changed": 0}, ttl=3600, contains={})
    check("…as does a category with nothing to match on", none == [], json.dumps(none))

    print()
    if FAILS:
        print("✗ contains lowering: %d failed" % len(FAILS))
        for f in FAILS:
            print("   · " + f)
        return 1
    print("✓ contains lowering: the panel buckets `*google*` as an operand, kernel-SNI builds it into an "
          "xt_string rule beside the category's names on one shared budget, refuses the kinds it cannot "
          "anchor, and says what it could not take")
    return 0


if __name__ == "__main__":
    sys.exit(main())
