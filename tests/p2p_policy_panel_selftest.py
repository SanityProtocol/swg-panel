#!/usr/bin/env python3
"""Self-test — the node-wide P2P policy on the PANEL (docs/P2P-POLICY-PLAN.md, P2).

  [1] p2p_policy: a stored choice wins; absent → COMPUTED, never written: block when every interface, WDTT and csqtt
      server already blocks torrents (vacuously true for a node with none — a pure exit), else iface; system
      interfaces (mesh links) don't count
  [2] THE DOOR — /api/nodes/update through the real handler: block|direct|iface stored as {action}; null → back to the
      computed default; anything else refused and nothing written
  [3] THE WIRE — the sync slice sends smart.p2p = {action} only for block|direct; iface sends None (the node keeps the
      per-interface mechanism alone, exactly as before)
  [4] THE CARD — a node told to block/direct that does not report `p2p` gets one issue; a node that reports it, or a
      node under iface, or one that has not reported smart status at all, gets none
  [5] PUBLISHED — /api/state's node carries p2p (stored), p2p_eff (in force) and p2p_node (what the node runs)

Run: python3 tests/p2p_policy_panel_selftest.py        (0 = pass)
     --perturb    plant each old behaviour in turn → every one must go RED (exit 0 when all are caught)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SRC = open(PANEL, encoding="utf-8").read()

PLANTS = {
    "wdtt-ignored":  ('    recs += [ov for ov in (node.get("wdtt") or {}).values() if isinstance(ov, dict)]\n', ""),
    "system-counts": ('    recs = [ov for ov in (node.get("ifaces") or {}).values() if isinstance(ov, dict) and not ov.get("system")]',
                      '    recs = [ov for ov in (node.get("ifaces") or {}).values() if isinstance(ov, dict)]'),
    "door-open":     ('            elif isinstance(_pp, dict) and _pp.get("action") in P2P_ACTIONS:',
                      '            elif isinstance(_pp, dict):'),
    "wire-iface":    ('(_p2pa := p2p_policy(node)) in ("block", "direct") else None)', '(_p2pa := p2p_policy(node)) else None)'),
    "issue-always":  ('isinstance(snap.get("smartroute"), dict) and not snap["smartroute"].get("p2p"):',
                      'isinstance(snap.get("smartroute"), dict):'),
    "unpublished":   ('                        "p2p_eff": p2p_policy(c),\n', ""),
}


def load(src):
    m = types.ModuleType("swgpanel_p2p"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


def run_checks(src):
    fails = []
    def ok(cond, what):
        if not cond:
            fails.append(what)
    P = load(src)
    tor = {"block": ["torrents", "smtp"]}
    # [1]
    ok(P.p2p_policy({}) == "block", "[1] a node with no user interfaces (a pure exit) computes block")
    ok(P.p2p_policy({"ifaces": {"wg0": tor, "swg_x": {"system": True}}}) == "block", "[1] system interfaces don't count")
    ok(P.p2p_policy({"ifaces": {"wg0": tor, "wg1": {"block": ["smtp"]}}}) == "iface", "[1] one interface without torrents → iface")
    ok(P.p2p_policy({"ifaces": {"wg0": tor}, "wdtt": {"w1": {"block": []}}}) == "iface", "[1] a WDTT server without torrents counts")
    ok(P.p2p_policy({"ifaces": {"wg0": tor}, "csqtt": {"c1": {}}}) == "iface", "[1] a csqtt server without torrents counts")
    ok(P.p2p_policy({"ifaces": {"wg1": {}}, "p2p": {"action": "direct"}}) == "direct", "[1] a stored choice wins")
    ok(P.p2p_policy({"p2p": {"action": "nonsense"}}) == "block", "[1] a junk stored value falls back to the computed default")

    # [2] the door
    tmp = tempfile.mkdtemp()
    np_, rp_ = os.path.join(tmp, "nodes.json"), os.path.join(tmp, "users.json")
    json.dump({"n1": {"name": "n1", "ifaces": {"wg0": tor}}}, open(np_, "w"))
    json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp_, "w"))
    deps = {"nodes_path": np_, "roster_path": rp_, "node_snaps": {"n1": {}}, "stats_dir": tmp, "fleet": {}, "panel_settings": {}}
    for a in ("direct", "iface", "block"):
        code, rsp = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "p2p": {"action": a}}, deps)
        ok(code == 200 and json.load(open(np_))["n1"].get("p2p") == {"action": a}, "[2] %s stored as {action}" % a)
    code, rsp = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "p2p": {"action": "route", "node": "x"}}, deps)
    ok(code == 400 and json.load(open(np_))["n1"].get("p2p") == {"action": "block"}, "[2] an unknown action is refused, nothing written")
    code, rsp = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "p2p": None}, deps)
    ok(code == 200 and "p2p" not in json.load(open(np_))["n1"], "[2] null → back to the computed default")
    code, rsp = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "panel_ip": ""}, deps)
    ok("p2p" not in json.load(open(np_))["n1"], "[2] a save without the key leaves the policy alone")

    # [3] the wire (the slice expression itself — the sync handler is exercised by the fleet qualification)
    expr = [l for l in src.splitlines() if '"p2p": ({"action": _p2pa}' in l]
    ok(len(expr) == 1, "[3] the sync slice carries smart.p2p")
    if expr:
        e = expr[0].split('"p2p": ', 1)[1].rstrip().rstrip(",")
        for node, want in (({}, {"action": "block"}), ({"p2p": {"action": "direct"}}, {"action": "direct"}),
                           ({"p2p": {"action": "iface"}}, None), ({"ifaces": {"wg1": {}}}, None)):
            got = eval(e, {"p2p_policy": P.p2p_policy, "node": node})
            ok(got == want, "[3] %s → %s (got %s)" % (node, want, got))

    # [4] the card
    key = "the torrent policy needs a node update"
    def iss(c, snap):
        return [i for i in P._node_issues(c, snap) if key in (i.get("error_key") or i.get("error") or "")]
    ok(len(iss({}, {"smartroute": {}})) == 1, "[4] block, node silent about p2p → one issue")
    ok(not iss({}, {"smartroute": {"p2p": {"state": "ok", "mode": "block"}}}), "[4] node reports p2p → no issue")
    ok(not iss({"p2p": {"action": "iface"}}, {"smartroute": {}}), "[4] iface → no issue")
    ok(not iss({}, {}), "[4] no smart status reported yet → no issue (absence is not evidence)")

    # [5] published
    blk = [l for l in src.splitlines() if '"p2p_eff": p2p_policy(c)' in l or '"p2p": c.get("p2p") if isinstance' in l
           or '"p2p_node": (snap.get("smartroute")' in l]
    ok(len(blk) == 3, "[5] /api/state publishes p2p, p2p_eff, p2p_node")
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if old not in SRC:
                print("PLANT %-14s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(SRC.replace(old, new, 1))
            print("PLANT %-14s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(SRC)
    for x in f:
        print("FAIL", x)
    print("p2p_policy_panel_selftest:", "PASS" if not f else "%d FAIL" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
