#!/usr/bin/env python3
"""A custom LIST holds what an inline RULE holds — the same six kinds, reaching the node the same way.

For most of this panel's life it did not. `_clean_targets` was called for a list WITHOUT `keep_patterns`, so
`*.ru` typed into a list was accepted by the field, dropped on save, and never mentioned — while the same
token in a rule shipped and routed. The asymmetry was invisible from either side: the list looked saved.

So the invariant here is EQUIVALENCE, not "patterns work". A test that only checked a list keeps its
patterns would still pass if the list shipped them under a different category id, or bucketed them
differently, or resolved to a second nft set beside the identical rule's. Each of those is a real way for
the two halves to disagree once they are meant to be the same thing, so each is asserted against the inline
path rather than against a hard-coded expectation.

  1. a list stores every kind, and REPORTS what it could not read (§5.4)
  2. a list whose every token is unreadable is reported as such — the row is gone, not shortened
  3. a list's patterns reach the plan bucketed by kind, exactly as an inline rule's do
  4. a list and the identical inline rule share ONE category id, so the fleet builds one set, not two
  5. a pattern-free list keeps the id it has today — upgrading must not rebuild every existing set

Run:  python3 tests/custom_list_patterns_selftest.py   (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")

def load():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    spec = importlib.util.spec_from_loader("swgpanel", loader)
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m

FAIL = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("   " + detail) if not cond and detail else ""))
    if not cond:
        FAIL.append(name)

def plan_for(P, rules, custom_lists=None, mode="sni"):
    nodes = {"n1": {"name": "a", "routing_mode": mode, "stats_file": "s.json",
                    "ifaces": {"awg0": {"egress_mode": "smart", "routing": rules}}}}
    snaps = {"n1": {"interfaces": {"awg0": {"meta": {"subnet": "10.9.0.0/24", "listen_port": 1}, "peers": []}}}}
    return P.cascade_plan(nodes, snaps, custom_lists)["n1"]

def main():
    P = load()
    TARGETS = "example.com, *.ru, *shop*, 10.0.0.0/8, AS62041"

    # ── 1 + 2. THROUGH THE REAL SAVE, not through _clean_targets ─────────────────────────────────────
    # ⚠️ An earlier draft called _clean_targets(keep_patterns=True) directly. It passed — and went on
    # passing when the SAVE was reverted to its shipped state, because the bug was never in the primitive:
    # the primitive always could keep patterns, the save just never asked it to. A guard that cannot see
    # the original defect is not a guard, so this drives api() the way the browser does.
    td = tempfile.mkdtemp()
    tmp, nodes_path, roster_path = (os.path.join(td, f) for f in ("panel-settings.json", "nodes.json", "users.json"))
    for f in (nodes_path, roster_path):
        open(f, "w").write("{}\n")
    deps = {"fleet": {}, "roster_path": roster_path, "nodes_path": nodes_path,
            "panel_settings": {}, "panel_settings_path": tmp}
    st, resp = P.api("POST", "/api/panel/settings", "", {"custom_lists": [
        {"id": "probe", "title": "Probe", "targets": TARGETS + ", !!garbage!!", "enabled": True},
        {"id": "junk", "title": "All junk", "targets": "!!a!!, ??b??", "enabled": True},
    ]}, deps)
    saved = {l["id"]: l for l in (resp.get("data") or {}).get("custom_lists", [])}
    drop = ((resp.get("data") or {}).get("dropped") or {}).get("entries", [])
    check("the save keeps every kind, patterns included", st == 200 and saved.get("probe", {}).get("patterns") == ["*.ru", "*shop*"]
          and saved["probe"]["domains"] == ["example.com"] and saved["probe"]["cidrs"] == ["10.0.0.0/8"]
          and saved["probe"]["asns"] == ["as62041"], json.dumps(saved.get("probe")))
    check("…and reports the token it could not read (§5.4)",
          {"entry": "!!garbage!!", "reason": "unreadable"} in drop, json.dumps(drop))
    check("a list with nothing readable in it is dropped AND said so — the row is gone, not shortened",
          "junk" not in saved and any(d.get("reason") == "list_empty" for d in drop), json.dumps(drop))

    # ── 3 + 4. the list path and the inline path must agree, on the bucket AND on the id ─────────────
    inline = [{"enabled": True, "category": "custom", "action": "block",
               "domains": ["example.com"], "cidrs": ["10.0.0.0/8"], "patterns": ["*.ru", "*shop*"]}]
    kept, err, _ = P._validate_routing(inline, {}, "n1")
    p_inline = plan_for(P, kept)
    cat_inline = p_inline["smart"][0]["category"]

    lists = {"probe": {"id": "probe", "title": "Probe", "domains": ["example.com"], "cidrs": ["10.0.0.0/8"],
                       "patterns": ["*.ru", "*shop*"], "enabled": True}}
    via_list = [{"enabled": True, "category": "probe", "action": "block"}]
    p_list = plan_for(P, via_list, lists)
    check("a rule naming a list produces a smart entry at all", bool(p_list["smart"]), json.dumps(p_list["smart"]))
    cat_list = p_list["smart"][0]["category"] if p_list["smart"] else None

    check("a list's patterns are bucketed by kind, exactly as an inline rule's are",
          (p_list["patterns"].get(cat_list) or {}) == (p_inline["patterns"].get(cat_inline) or {}),
          "list=" + json.dumps(p_list["patterns"]) + " inline=" + json.dumps(p_inline["patterns"]))
    check("…and its domains land in `domains`, never merged with the patterns",
          p_list["domains"].get(cat_list) == ["example.com"], json.dumps(p_list["domains"]))
    check("a list and the identical inline rule share ONE category id (one nft set, not two)",
          cat_list == cat_inline, "%s vs %s" % (cat_list, cat_inline))

    # ── 5. UPGRADE SAFETY: a list that has no patterns must hash as it always has ────────────────────
    check("a pattern-free list keeps the id it has today",
          P.custom_cat_id(["example.com"], ["10.0.0.0/8"]) == P.custom_cat_id(["example.com"], ["10.0.0.0/8"], []),
          "the third id segment must stay absent when there are no patterns")

    print(("\n✗ %d failed" % len(FAIL)) if FAIL else "\n✓ a custom list holds what an inline rule holds")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
