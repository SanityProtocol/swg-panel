#!/usr/bin/env python3
"""Self-test for the legacy `tld` → zone-pattern migration (ROUTING-RULE-BUILDER-PLAN §5.1).

`category:"tld"` rules have been storable since 1.5.0-beta and have never routed a packet: cascade_plan has
no branch for them, so one fell through with category "tld" verbatim and `_smart_setname("tld")` is
`cat_tld` — ONE shared, permanently empty set that every tld rule on a node collapsed into, values dropped,
plus a real mark rule that never matched.

The danger is not that they are inert. It is that the moment zones start working, every dormant rule begins
steering traffic on fleets whose operators wrote them months ago and watched them do nothing. So the
migration lands BEFORE the datapath and lands DISABLED, and this asserts both halves.

It rewrites operator state, so most of what is below is about what it must NOT do: touch an ordinary rule,
change an action or a destination, reorder anything, or run twice.

Run:  python3 tests/tld_migration_selftest.py          (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (("   " + detail) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def load():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    spec = importlib.util.spec_from_loader("swgpanel", loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fleet():
    """One node, three interfaces: a tld rule among ordinary ones, a tld-only interface, and one with none."""
    return {"n1": {"name": "berlin", "ifaces": {
        "awg0": {"routing": [
            {"enabled": True, "category": "google", "action": "exit", "node": "n2"},
            {"enabled": True, "category": "tld", "match": "tld", "tlds": ["ru", "io"],
             "action": "exit", "node": "n2"},
            {"enabled": True, "category": "custom", "domains": ["a.example"], "cidrs": [], "action": "block"},
        ]},
        "awg1": {"routing": [{"enabled": False, "category": "tld", "match": "tld", "tlds": ["рф"],
                              "action": "block"}]},
        "awg2": {"routing": [{"enabled": True, "category": "youtube", "action": "block"}]},
    }, "wdtt": {"w0": {"routing": [{"enabled": True, "category": "tld", "match": "tld",
                                    "tlds": ["nope..", "de"], "action": "direct"}]}}}}


def main():
    m = load()
    tmp = tempfile.mkdtemp(prefix="tldmig-")
    npath, ppath = os.path.join(tmp, "nodes.json"), os.path.join(tmp, "panel-settings.json")
    json.dump(fleet(), open(npath, "w"))
    json.dump({}, open(ppath, "w"))

    m.migrate_tld_rules(npath, ppath)
    n = json.load(open(npath))
    ps = json.load(open(ppath))
    awg0 = n["n1"]["ifaces"]["awg0"]["routing"]
    awg1 = n["n1"]["ifaces"]["awg1"]["routing"]
    awg2 = n["n1"]["ifaces"]["awg2"]["routing"]
    w0 = n["n1"]["wdtt"]["w0"]["routing"]
    print(json.dumps(awg0, indent=1))

    # ── the conversion itself ─────────────────────────────────────────────────────────────────────────────
    conv = awg0[1]
    check("tld → custom + zone patterns",
          conv.get("category") == "custom" and conv.get("patterns") == ["*.ru", "*.io"],
          json.dumps(conv))
    check("the legacy keys are gone", not any(k in conv for k in ("match", "tlds", "value")), json.dumps(conv))

    # ── THE SAFETY PROPERTY: it cannot start routing when zones ship ──────────────────────────────────────
    check("converted rules land DISABLED", conv.get("enabled") is False, json.dumps(conv))
    check("…and one already disabled stays disabled", awg1 and awg1[0].get("enabled") is False)

    # ── everything else is untouched ──────────────────────────────────────────────────────────────────────
    check("action and destination preserved", conv.get("action") == "exit" and conv.get("node") == "n2",
          json.dumps(conv))
    check("order preserved (google, converted, custom)",
          [r.get("category") for r in awg0] == ["google", "custom", "custom"],
          json.dumps([r.get("category") for r in awg0]))
    check("an ordinary rule is byte-identical",
          awg0[0] == {"enabled": True, "category": "google", "action": "exit", "node": "n2"}
          and awg0[2] == {"enabled": True, "category": "custom", "domains": ["a.example"], "cidrs": [],
                          "action": "block"})
    check("an interface with no tld rule is untouched",
          awg2 == [{"enabled": True, "category": "youtube", "action": "block"}], json.dumps(awg2))

    # ── the self-contained kinds carry the same routing block, and a bad label is dropped, not kept ────────
    check("wdtt instances are migrated too", w0 and w0[0].get("patterns") == ["*.de"], json.dumps(w0))
    check("IDN converts through punycode", awg1 and awg1[0].get("patterns") == ["*.xn--p1ai"], json.dumps(awg1))

    # ── the record, so the UI can say what happened ───────────────────────────────────────────────────────
    rec = ps.get("tld_migrated") or {}
    check("the migration is recorded and counted", rec.get("count") == 3 and len(rec.get("rules") or []) == 3,
          json.dumps(rec))

    # ── IDEMPOTENT: a second run changes nothing ──────────────────────────────────────────────────────────
    before = open(npath).read()
    m.migrate_tld_rules(npath, ppath)
    check("running it again changes nothing", open(npath).read() == before)

    # ── and the converted rules survive the validator unchanged (the SPA re-posts on every save) ──────────
    kept, err, _ = m._validate_routing(awg0, {"n2": {}}, "n1")
    check("the result round-trips through _validate_routing", err is None and len(kept) == 3
          and kept[1].get("patterns") == ["*.ru", "*.io"] and kept[1].get("enabled") is False,
          json.dumps(kept))

    # ── a rule with nothing readable in it is dropped, never kept as an empty husk ────────────────────────
    # A FRESH directory, not a reset of the one above: load_settings_critical deliberately recovers a non-empty
    # BACKUP when the primary parses as {} — a genuine empty settings file only ever arises from a clobber — so
    # rewriting ppath as {} restores the marker and this migration correctly declines to run twice. Right
    # behaviour, wrong fixture; it cost a few minutes reading a migration that was doing exactly its job.
    tmp2 = tempfile.mkdtemp(prefix="tldmig2-")
    npath, ppath = os.path.join(tmp2, "nodes.json"), os.path.join(tmp2, "panel-settings.json")
    json.dump({"n1": {"name": "x", "ifaces": {"a": {"routing": [
        {"enabled": True, "category": "tld", "match": "tld", "tlds": ["co.uk", "!!"], "action": "block"}]}}}},
        open(npath, "w"))
    json.dump({}, open(ppath, "w"))
    m.migrate_tld_rules(npath, ppath)
    left = json.load(open(npath))["n1"]["ifaces"]["a"]["routing"]
    check("an all-unreadable tld rule is dropped", left == [], json.dumps(left))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(tmp2, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
