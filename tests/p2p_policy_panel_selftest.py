#!/usr/bin/env python3
"""Self-test — the node-wide P2P policy on the PANEL (docs/P2P-POLICY-PLAN.md, P2).

  [1] p2p_policy: a stored choice wins (iface included); absent → BLOCK, never written — whatever the records say: an
      interface recorded with no block list (the installer's, an onboarded one, the sync's own record), one with
      Torrents / P2P off, a WDTT or csqtt server without it. ⚠️ Reversed 2026-10-08: the default used to be computed
      from those records (iface as soon as one lacked torrents) and was off on 3 of 4 swgt nodes, none by choice
  [2] THE DOOR — /api/nodes/update through the real handler: block|direct|iface stored as {action}; null → back to the
      default; anything else refused and nothing written
  [3] THE WIRE — the sync slice sends smart.p2p = {action} for block|direct — a node with nothing saved gets block —
      and None only for a saved iface (the node keeps the per-interface mechanism alone)
  [4] THE CARD — a node told to block/direct that does not report `p2p` gets one issue (a node with only a bare
      interface record included — it is block by default); a node that reports it, or a node under a saved iface, or
      one that has not reported smart status at all, gets none
  [5] PUBLISHED — /api/state's node carries p2p (stored), p2p_eff (in force) and p2p_node (what the node runs)
  P3 — ROUTE
  [6] the door: exit → another existing node only; dev → one of THIS node's exits only; refused otherwise, nothing written
  [7] the plan: exit(Q) lowers every own client subnet through the link to Q — the node gets `_p2p` {table, via_iface,
      subnets}, Q gets the exit records — and a subnet that clashes at Q is LEFT OUT (never routed into a reply mix-up);
      no mesh link → no `_p2p` at all; dev(exit) → rule-scoped devexits on the node's own subnets, never a `from S` rule
  [8] the wire: route + the lowered entry; route that could not be lowered → route with entry None (the node blocks)
  [10] the Settings draft (js/screen-settings.js nFields) keeps the WHOLE record — a route's node / exit_id — or the picker
       empties after a save and the next save of anything posts a route with no target (refused): found live on swgt
  [11] a pruned route is SAID: node_remove writes "Torrent route removed" to the activity log
  [12] the card: a route whose way out is down (node reports route "down") is named
  [13] the picker's exits ARE the routing pickers' list (`exitOptionGroups` — a switched-off exit and a WARP account that
       is not ready refused with their reason); a node with no mesh link is refused; a node not reporting is a WARNING on
       the chosen target, never a refusal (judged in this browser, before its first status pass too — code review);
       and it says when the policy shown is the automatic default — the one sentence, that the default is block and an
       interface's switch counts only under "Each interface decides"; with no p2p_eff from the server it shows block
  [14] CODE REVIEW #2: "not reporting" is the panel's own verdict (`nodeStatusOf` — the server's "never synced" too), and an
       exit that is gone from the list is named by its id, never "Custom"
  [9] the card: a route the node runs as block → "the torrent route is unavailable"; the target gone → pruned to block
  [15] q189 F2 — ONE NODE'S MALFORMED REPORT NEVER FAILS /api/state FOR EVERY OPERATOR: `smartroute` or its `p2p` that is
       not an object (a string, a list, a number) is read as "not reported" by _node_issues — never an exception — and
       /api/state through the real api() answers 200 with that node's p2p_node null (it was a 500 on every poll)
  [17] q189 SPA-2 / PR-7 — an exit write re-bases the Settings draft's torrent route with the exits (rebaseDefault, the
       same writer that already re-bases the default list): taken from the server where it was not being edited, and a
       route through a removed exit made Block where it was (prune_p2p_refs' rule) — else every later save of the node
       posted the dead route and was refused "torrents can only be routed through one of this node's exits" until a reload
       (measured in the browser: Settings → WARP → Remove, then a Network change → Save → 400)
  [16] q189 NR-2 (panel row): a node whose torrent rules failed to load (p2p state "error") is SAID, in one translated
       sentence with nft's own line as its value (as it is, cut at 160) — under any policy, iface included, and in place
       of the route rows; no detail → the same sentence without it; state ok/degraded → nothing

Run: python3 tests/p2p_policy_panel_selftest.py        (0 = pass)
     --perturb    plant each old behaviour in turn → every one must go RED (exit 0 when all are caught)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SRC = open(PANEL, encoding="utf-8").read()
SPA = os.path.join(ROOT, "js", "screen-settings.js")

PLANTS = {
    # the default before 2026-10-08: computed from the records, iface as soon as one lacked torrents
    "computed-default": ('        return v["action"]\n    return "block"\n',
                         '        return v["action"]\n'
                         '    recs = [ov for ov in (node.get("ifaces") or {}).values() if isinstance(ov, dict) and not ov.get("system")]\n'
                         '    recs += [ov for ov in (node.get("wdtt") or {}).values() if isinstance(ov, dict)]\n'
                         '    recs += [ov for ov in (node.get("csqtt") or {}).values() if isinstance(ov, dict)]\n'
                         '    return "block" if all("torrents" in (r.get("block") or []) for r in recs) else "iface"\n'),
    "default-iface": ('        return v["action"]\n    return "block"\n', '        return v["action"]\n    return "iface"\n'),
    "spa-iface-fallback": ('{ action: node.p2p_eff || "block" }', '{ action: node.p2p_eff || "iface" }'),
    "door-open":     ('            elif isinstance(_pp, dict) and _pp.get("action") in P2P_ACTIONS:',
                      '            elif isinstance(_pp, dict):'),
    "wire-iface":    ('"p2p": ({"action": _p2pa} if (_p2pa := p2p_policy(node)) in ("block", "direct")',
                      '"p2p": ({"action": _p2pa} if (_p2pa := p2p_policy(node)) in ("block", "direct", "iface")'),
    "issue-always":  ('    if _p2pa != "iface" and _srp is not None and not _p2pn:',
                      '    if _p2pa != "iface" and _srp is not None:'),
    "p3-no-clash":   ('                    _subs = [s for n_, s in _own if not _clashes(nid, n_, s, _Q, "rule")]',
                      '                    _subs = [s for n_, s in _own]'),
    "p3-into-smart": ('        sn["_p2p"] = {"table": T, "via_iface": dev_n, "subnets": sorted(set(subs))}',
                      '        sn["_p2p"] = {"table": T, "via_iface": dev_n, "subnets": sorted(set(subs))}\n        sn["smart"].append({"subnet": subs[0], "category": "p2p", "action": "exit", "via_iface": dev_n, "table": T})'),
    "p3-iface-scope":('            for S in subs:\n                _dx_add(sn, {"subnet": S, "dev": dev_n, "table": T, "killswitch": bool(xks), "scope": "rule",',
                      '            for S in subs:\n                _dx_add(sn, {"subnet": S, "dev": dev_n, "table": T, "killswitch": bool(xks), "scope": "iface",'),
    "p3-no-prune":   ("    _p2p_pruned = prune_p2p_refs(nodes)                       # …and a torrent route to it becomes Block\n", "    _p2p_pruned = []\n"),
    "spa-action-only": ('    p2p: n.p2p && n.p2p.action ? { action: n.p2p.action, ...(n.p2p.node ? { node: n.p2p.node } : {}),\n                                   ...(n.p2p.exit_id ? { exit_id: n.p2p.exit_id } : {}) } : null,',
                        '    p2p: n.p2p && n.p2p.action ? { action: n.p2p.action } : null,'),
    "no-prune-event":("    _report_p2p_pruned(deps, _p2p_pruned)\n", ""),
    "no-route-down": ('    elif _p2pa in ("exit", "dev") and _p2pn and _p2pn.get("route") == "down":', "    elif False:"),
    # q189 FP-1: cascade_plan's arrivals check reads a malformed report again
    "fp1-arr":       ('        return isinstance(_sr, dict) and bool(_sr.get("arr"))',
                      '        return bool((_sr or {}).get("arr"))'),
    # q189 F2: the unguarded reads of 52aa9c4 put back, one at a time
    "f2-sr-any":     ('    _srp = snap.get("smartroute") if isinstance(snap.get("smartroute"), dict) else None',
                      '    _srp = snap.get("smartroute") if snap.get("smartroute") is not None else None'),
    "f2-p2p-any":    ('    _p2pn = _srp.get("p2p") if _srp is not None and isinstance(_srp.get("p2p"), dict) else None',
                      '    _p2pn = _srp.get("p2p") if _srp is not None else None'),
    "f2-p2p-node":   ('''                        "p2p_node": (lambda s: s["p2p"] if isinstance(s, dict) and isinstance(s.get("p2p"), dict)
                                     and s["p2p"] else None)(snap.get("smartroute")),   # an object or nothing (F2)''',
                      '''                        "p2p_node": (snap.get("smartroute") or {}).get("p2p") or None,'''),
    # q189 NR-2: the failed load unsaid, or said without nft's line
    "nr2-silent":    ('    elif _p2pn and _p2pn.get("state") == "error":', '    elif False:'),
    "nr2-no-detail": ('''                           "load, torrents are not blocked or routed as set", v1=_pd) if _pd else''',
                      '''                           "load, torrents are not blocked or routed as set", v1=_pd) if False else'''),
    "spa-own-list":  ('        ...exitOptionGroups({ ...node, exits }, { prefix: "dev:", stored: node.exits || [] })',
                      '        ...exits.filter(x => x && x.id).map(x => ({ value: "dev:" + x.id, label: x.label || x.id }))'),
    "spa-stale-refuse": ('        ...(!linked.has(n.id) ? { refuse: T("There is no mesh link to {v1}.", { v1: n.name }), className: "dim" } : {}) }));',
                         '        ...(!linked.has(n.id) ? { refuse: T("There is no mesh link to {v1}.", { v1: n.name }), className: "dim" } : nodeStale(n.id) ? { refuse: "x" } : {}) }));'),
    "spa-inline-stale": ('      const tgtStale = !tgtDrops && !!tgt && nodeStatusOf(tgt) !== "online";',
                         '      const tgtSt = tgt ? (((Store.recon || {}).nodeStatus) || {})[tgt.id] : undefined;\n      const tgtStale = !tgtDrops && !!tgtSt && tgtSt !== "live";'),
    "spa-custom-name": ('  return x ? exitLabel(x, node) : String(p.exit_id || "");', '  return exitLabel(x || { id: p.exit_id }, node);'),
    # q189 SPA-2: the draft's torrent route is no longer re-based with the exits
    "spa-p2p-rebase": ("      const p2p = eq(cur.p2p, o.p2p) ? fresh.p2p\n", "      const p2p = cur.p2p; ({}).x = eq(cur.p2p, o.p2p) ? fresh.p2p\n"),
    "spa-p2p-orig":   ("default_exit: fresh.default_exit, p2p: fresh.p2p } }));", "default_exit: fresh.default_exit } }));"),
    "unpublished":   ('                        "p2p_eff": p2p_policy(c),\n', ""),
}


def load(src):
    m = types.ModuleType("swgpanel_p2p"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


def run_checks(src, spa=None):
    fails = []
    def ok(cond, what):
        if not cond:
            fails.append(what)
    P = load(src)
    tor = {"block": ["torrents", "smtp"]}
    # [1]
    ok(P.p2p_policy({}) == "block", "[1] nothing saved, no user interfaces (a pure exit) → block")
    ok(P.p2p_policy({"ifaces": {"awg0": {}}}) == "block",
       "[1] an interface recorded with no block list (installer / onboard / the sync's own record) → still block")
    ok(P.p2p_policy({"ifaces": {"wg0": tor, "wg1": {"block": ["smtp"]}}}) == "block", "[1] an interface with Torrents off → still block")
    ok(P.p2p_policy({"ifaces": {"wg0": tor}, "wdtt": {"w1": {"block": []}}, "csqtt": {"c1": {}}}) == "block",
       "[1] a WDTT or csqtt server without torrents (the Turn proxies card sends none) → still block")
    ok(P.p2p_policy({"ifaces": {"wg1": {}}, "p2p": {"action": "direct"}}) == "direct", "[1] a stored choice wins")
    ok(P.p2p_policy({"ifaces": {"wg1": tor}, "p2p": {"action": "iface"}}) == "iface",
       "[1] …iface too: the per-interface switches decide once the operator picks it")
    ok(P.p2p_policy({"p2p": {"action": "nonsense"}}) == "block", "[1] a junk stored value falls back to the default")

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
    i0 = src.find('"p2p": ({"action": _p2pa}')
    ok(i0 > 0, "[3] the sync slice carries smart.p2p")
    def wire(node, plan=None):
        s = src[i0 + len('"p2p": '):]
        depth = 0
        for j, ch in enumerate(s):
            depth += ch == "("; depth -= ch == ")"
            if depth == 0 and j:
                break
        return eval(s[:j + 1], {"p2p_policy": P.p2p_policy, "node": node, "my_plan": plan})
    if i0 > 0:
        for node, want in (({}, {"action": "block"}), ({"p2p": {"action": "direct"}}, {"action": "direct"}),
                           ({"p2p": {"action": "iface"}}, None), ({"ifaces": {"wg1": {}}}, {"action": "block"})):
            got = wire(node)
            ok(got == want, "[3] %s → %s (got %s)" % (node, want, got))

    # [4] the card
    key = "the torrent policy needs a node update"
    def iss(c, snap):
        return [i for i in P._node_issues(c, snap) if key in (i.get("error_key") or i.get("error") or "")]
    ok(len(iss({}, {"smartroute": {}})) == 1, "[4] block, node silent about p2p → one issue")
    ok(len(iss({"ifaces": {"awg0": {}}}, {"smartroute": {}})) == 1,
       "[4] …a node with only a bare interface record too (block by default, so an old noded is named)")
    ok(not iss({}, {"smartroute": {"p2p": {"state": "ok", "mode": "block"}}}), "[4] node reports p2p → no issue")
    ok(not iss({"p2p": {"action": "iface"}}, {"smartroute": {}}), "[4] iface → no issue")
    ok(not iss({}, {}), "[4] no smart status reported yet → no issue (absence is not evidence)")

    # [5] published
    blk = [l for l in src.splitlines() if '"p2p_eff": p2p_policy(c)' in l or '"p2p": c.get("p2p") if isinstance' in l
           or '"p2p_node": ' in l]
    ok(len(blk) == 3, "[5] /api/state publishes p2p, p2p_eff, p2p_node")
    # ── P3 ──
    X1 = {"id": "aaaa0001", "label": "X", "device": "wgx0", "enabled": True, "producer": "adopted", "killswitch": True}
    SN = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.28.0.0/24"}}},
          "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
    SP = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}, "wg5": {"meta": {"subnet": "10.19.0.0/24"}}},
          "ether_ifaces": ["eth0"], "wan_iface": "eth0", "ether_gws": {"eth0": "198.51.100.1"},
          "node_ips": ["198.51.100.254"], "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
    def fleet(n1p=None, n2p=None, links=True):
        n1 = {"name": "node-n", "ifaces": {"wg0": {}, "wg9": {}}}
        n2 = {"name": "node-p", "exits": [dict(X1)], "ifaces": {"wg0": {}, "wg5": {}}}
        if links:
            n1["links"] = {"n2": {"iface": "swg_p", "peer_address": "10.255.0.1"}}
            n2["links"] = {"n1": {"iface": "swg_n", "peer_address": "10.255.0.0"}}
        if n1p: n1["p2p"] = n1p
        if n2p: n2["p2p"] = n2p
        return {"n1": n1, "n2": n2}
    # [6] the door
    json.dump(fleet(), open(np_, "w"))
    deps["node_snaps"] = {"n1": SN, "n2": SP}
    for body, want in (({"id": "n1", "p2p": {"action": "exit", "node": "n1"}}, 400), ({"id": "n1", "p2p": {"action": "exit", "node": "nX"}}, 400),
                       ({"id": "n2", "p2p": {"action": "dev", "exit_id": "ffff0000"}}, 400)):
        code, _r = P.api("POST", "/api/nodes/update", {}, body, deps)
        ok(code == want and "p2p" not in json.load(open(np_))[body["id"]], "[6] refused: %s" % body["p2p"])
    code, _r = P.api("POST", "/api/nodes/update", {}, {"id": "n1", "p2p": {"action": "exit", "node": "n2"}}, deps)
    ok(code == 200 and json.load(open(np_))["n1"].get("p2p") == {"action": "exit", "node": "n2"}, "[6] exit → another node stored")
    code, _r = P.api("POST", "/api/nodes/update", {}, {"id": "n2", "p2p": {"action": "dev", "exit_id": X1["id"]}}, deps)
    ok(code == 200 and json.load(open(np_))["n2"].get("p2p") == {"action": "dev", "exit_id": X1["id"]}, "[6] dev → own exit stored")
    # [7] the plan
    pl = P.cascade_plan(fleet(n1p={"action": "exit", "node": "n2"}), {"n1": SN, "n2": SP})
    e = (pl.get("n1") or {}).get("_p2p") or {}
    ok(e.get("via_iface") == "swg_p" and e.get("subnets") == ["10.28.0.0/24", "10.8.0.0/24"] and P.SWG_RT_BASE <= e.get("table", 0) <= P.SWG_RT_MAX,
       "[7] exit(n2): n1 gets the leg, a band table and both its subnets (%s)" % e)
    xs = {x["subnet"] for x in (pl.get("n2") or {}).get("exit") or []}
    ok({"10.8.0.0/24", "10.28.0.0/24"} <= xs, "[7] …and n2 gets the exit records for them (%s)" % sorted(xs))
    ok(not (pl.get("n1") or {}).get("smart"), "[7] …and NOTHING enters smart.entries (a `p2p` category set would never exist)")
    SNc = dict(SN, interfaces={"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.9.0.0/24"}}})
    e = (P.cascade_plan(fleet(n1p={"action": "exit", "node": "n2"}), {"n1": SNc, "n2": SP}).get("n1") or {}).get("_p2p") or {}
    ok(e.get("subnets") == ["10.8.0.0/24"], "[7] a subnet that clashes with n2's own is left out (%s)" % e.get("subnets"))
    ok(not (P.cascade_plan(fleet(n1p={"action": "exit", "node": "n2"}, links=False), {"n1": SN, "n2": SP}).get("n1") or {}).get("_p2p"),
       "[7] no mesh link → nothing lowered")
    pl = P.cascade_plan(fleet(n2p={"action": "dev", "exit_id": X1["id"]}), {"n1": SN, "n2": SP})
    e = (pl.get("n2") or {}).get("_p2p") or {}
    dx = [d for d in (pl.get("n2") or {}).get("devexit") or [] if d.get("dev") == "wgx0"]
    ok(e.get("via_iface") == "wgx0" and e.get("subnets") == ["10.19.0.0/24", "10.9.0.0/24"], "[7] dev: n2 routes its own subnets via wgx0 (%s)" % e)
    ok(sorted(d["subnet"] for d in dx) == ["10.19.0.0/24", "10.9.0.0/24"] and all(d.get("scope") == "rule" and d.get("killswitch") for d in dx),
       "[7] …through RULE-scoped devexits that keep the exit's kill-switch (%s)" % dx)
    # [8] the wire
    if i0 > 0:
        ok(wire({"p2p": {"action": "dev", "exit_id": "x"}}, {"_p2p": {"table": 7001, "via_iface": "wgx0", "subnets": ["10.9.0.0/24"]}})
           == {"action": "route", "entry": {"table": 7001, "via_iface": "wgx0", "subnets": ["10.9.0.0/24"]}}, "[8] route + the lowered entry")
        ok(wire({"p2p": {"action": "exit", "node": "n2"}}, {}) == {"action": "route", "entry": None}, "[8] unlowered route → entry None")
    # [9] the card + prune
    issues = [i.get("error_key") or i.get("error") for i in P._node_issues({"p2p": {"action": "exit", "node": "n2"}},
              {"smartroute": {"p2p": {"state": "ok", "mode": "block"}}})]
    ok(any("torrent route is unavailable" in (i or "") for i in issues), "[9] a route run as block is said on the card")
    fl = fleet(n1p={"action": "exit", "node": "n2"}, n2p={"action": "dev", "exit_id": X1["id"]})
    del fl["n2"]["exits"]
    fl.pop("n2") if False else None
    P.prune_p2p_refs(fl)
    ok(fl["n2"].get("p2p") == {"action": "block"}, "[9] dev with its exit deleted → block")
    del fl["n2"]
    P.prune_p2p_refs(fl)
    ok(fl["n1"].get("p2p") == {"action": "block"}, "[9] exit to a removed node → block")
    json.dump(fleet(n1p={"action": "exit", "node": "n2"}), open(np_, "w"))   # …and through the real removal path
    P.node_remove(deps, "n2")
    ok(json.load(open(np_))["n1"].get("p2p") == {"action": "block"}, "[9] node_remove prunes the torrent route to it")
    evs = ""
    with __import__("contextlib").suppress(OSError):
        evs = open(os.path.join(os.path.dirname(rp_), "events.jsonl")).read()
    ok("Torrent route removed" in evs, "[11] node_remove records the pruned route in the activity log")
    iss12 = [i.get("error_key") or i.get("error") for i in P._node_issues({"p2p": {"action": "dev", "exit_id": "x"}},
             {"smartroute": {"p2p": {"state": "ok", "mode": "route", "route": "down"}}})]
    ok(any("way out is down" in (i or "") for i in iss12), "[12] a route that is down is named on the card")
    iss12b = [i.get("error_key") or i.get("error") for i in P._node_issues({"p2p": {"action": "dev", "exit_id": "x"}},
              {"smartroute": {"p2p": {"state": "ok", "mode": "route", "route": "up"}}})]
    ok(not any("torrent" in (i or "") for i in iss12b), "[12] …and an up route says nothing")
    # [15] q189 F2 — a malformed report is "not reported", never an exception, never a 500 for everyone
    for pol in ({}, {"p2p": {"action": "exit", "node": "n2"}}, {"p2p": {"action": "dev", "exit_id": "x"}}):
        for sr in ({"p2p": "block"}, {"p2p": ["x"]}, {"p2p": 3}, ["x"], "block", 5):
            try:
                got = [i.get("error_key") or "" for i in P._node_issues(pol, {"smartroute": sr})]
            except Exception as e:
                got = "raised %s: %s" % (type(e).__name__, e)
            want = (["the torrent policy needs a node update — until then torrents are blocked only on interfaces that have "
                     "Torrents / P2P switched on"] if isinstance(sr, dict) else [])
            ok(got == want, "[15] smartroute=%r under %s → %s (got %s)" % (sr, pol.get("p2p") or "the default", want or "nothing",
                                                                          got))
    tmp15 = tempfile.mkdtemp()
    np15, rp15 = os.path.join(tmp15, "nodes.json"), os.path.join(tmp15, "users.json")
    json.dump({"n1": {"name": "n1", "ifaces": {}, "p2p": {"action": "exit", "node": "n2"}}, "n2": {"name": "n2", "ifaces": {}},
               "n3": {"name": "n3", "ifaces": {}}}, open(np15, "w"))
    json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp15, "w"))
    d15 = {"nodes_path": np15, "roster_path": rp15, "stats_dir": tmp15, "fleet": {}, "panel_settings": {},
           "node_snaps": {"n1": {"smartroute": {"p2p": "block"}}, "n2": {"smartroute": ["x"]},
                          "n3": {"smartroute": {"p2p": {"state": "ok", "mode": "block"}}}},
           "node_seen": {"n1": 1, "n2": 1, "n3": 1}}
    P.Handler.deps = d15
    try:
        code, obj = P.api("GET", "/api/state", {}, {}, d15)
    except Exception as e:
        code, obj = "raised %s: %s" % (type(e).__name__, e), {}
    pn = {n["id"]: n.get("p2p_node") for n in ((obj or {}).get("data") or {}).get("nodes") or []} if code == 200 else code
    ok(pn == {"n1": None, "n2": None, "n3": {"state": "ok", "mode": "block"}},
       "[15] /api/state through the real api(): 200 with a string p2p and a list smartroute on two nodes — their p2p_node "
       "null, the good node's kept (got %s)" % (pn,))
    # [15] q189 FP-1 — …nor fails cascade_plan, which plans EVERY node's sync over every other node's report
    SN15 = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}}, "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
    SP15 = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}}, "ether_ifaces": ["eth0"], "wan_iface": "eth0",
            "ether_gws": {"eth0": "198.51.100.1"}, "node_ips": ["198.51.100.254"]}
    def fl15():
        return {"n1": {"name": "a", "ifaces": {"wg0": {}}, "links": {"n2": {"iface": "swg_p", "peer_address": "10.255.0.1"}},
                       "default_routing": [{"category": "*", "action": "exit", "node": "n2", "on": True}]},
                "n2": {"name": "b", "ifaces": {"wg0": {}}, "links": {"n1": {"iface": "swg_n", "peer_address": "10.255.0.0"}},
                       "default_routing": [{"category": "*", "action": "direct", "on": True}]}}
    for bad in ("x", ["x"], 5):
        try:
            pl = P.cascade_plan(fl15(), {"n1": SN15, "n2": dict(SP15, smartroute=bad)})
            got = "ok, %d nodes planned" % len(pl)
        except Exception as e:
            got = "raised %s: %s" % (type(e).__name__, e)
        ok(got.startswith("ok"), "[15] cascade_plan with n2's smartroute=%r beside n1's default list: %s" % (bad, got))
    # [16] q189 NR-2 — the node's torrent rules did not load
    K16 = ("the torrent policy is not in force on this node — its rules failed to load ({v1}); until they load, torrents "
           "are not blocked or routed as set")
    K16b = ("the torrent policy is not in force on this node — its rules failed to load; until they load, torrents are not "
            "blocked or routed as set")
    det = "Error: Could not process rule: No such file or directory"
    def tor(pol, p2p):
        return [(i.get("error_key"), (i.get("error_vars") or {}).get("v1")) for i in P._node_issues(pol, {"smartroute": {"p2p": p2p}})
                if "torrent" in (i.get("error_key") or "")]
    for pol in ({}, {"p2p": {"action": "direct"}}, {"p2p": {"action": "iface"}}, {"p2p": {"action": "exit", "node": "n2"}}):
        got = tor(pol, {"state": "error", "mode": "route" if "node" in str(pol) else "block", "route": "down", "detail": det})
        ok(got == [(K16, det)], "[16] state error under %s → the one sentence, nft's line as its value (got %s)"
           % (pol.get("p2p") or "the default", got))
    ok(tor({}, {"state": "error", "mode": "block"}) == [(K16b, None)], "[16] no detail → the sentence without it")
    ok(tor({}, {"state": "error", "mode": "block", "detail": ["x"]}) == [(K16b, None)], "[16] a detail that is no string → without it")
    ok(tor({}, {"state": "error", "mode": "block", "detail": "x" * 400}) == [(K16, "x" * 160)], "[16] a long detail is cut at 160")
    ok(not tor({}, {"state": "ok", "mode": "block"}) and not tor({}, {"state": "degraded", "mode": "block"}),
       "[16] state ok / degraded → nothing said")
    # [10] the draft keeps the route's target
    spa = spa if spa is not None else open(SPA, encoding="utf-8").read()
    nf = spa[spa.find("const nFields = n =>"):]
    nf = nf[:nf.find("});")]
    line = nf[nf.find("p2p:"):]
    line = line[:line.find(" : null,")]
    ok("n.p2p.node" in line and "n.p2p.exit_id" in line, "[10] the Settings draft keeps p2p.node and p2p.exit_id")
    blk = spa[spa.find("const linked = new Set("):]
    blk = blk[:blk.find("return html`")]
    ok('exitOptionGroups({ ...node, exits }, { prefix: "dev:", stored: node.exits || [] })' in blk,
       "[13] the exits come from exitOptionGroups (with the stored record for health)")
    ok("!linked.has(n.id) ? { refuse:" in blk, "[13] a node with no mesh link is refused")
    ok("nodeStale" not in blk and "tgtStale" in blk and "refuse: T(\"{v1} is not reporting" not in blk,
       "[13] a node not reporting is a warning on the chosen target, never a refusal")
    ok('nodeStatusOf(tgt) !== "online"' in blk and "Store.recon" not in blk,
       "[14] the warning uses nodeStatusOf (the server's verdict where this browser has none), not a copy of the rule")
    pt = spa[spa.find("const p2pTarget = "):]
    pt = pt[:pt.find("};")]
    ok('return x ? exitLabel(x, node) : String(p.exit_id || "")' in pt, "[14] an exit gone from the list is named by its id")
    ok("Chosen automatically" in spa, "[13] the automatic default is said")
    ok("lets torrents through. Pick a setting" not in spa and "Pick a setting to keep it from changing" not in spa,
       "[13] …as the default, not as a value that follows the interfaces")
    ok('{ action: node.p2p_eff || "block" }' in spa, "[13] with no p2p_eff from the server the card shows block, the default")
    # [17] q189 SPA-2: the exit writers' re-base carries the torrent route
    rb = spa[spa.find("const rebaseDefault = (nid, fresh) => {"):]
    rb = rb[:rb.find("\n  };\n")]
    ok("const p2p = eq(cur.p2p, o.p2p) ? fresh.p2p" in rb, "[17] an unedited torrent route in the draft is taken from the server after an exit write")
    ok('cur.p2p.action === "dev" && !live.has(String(cur.p2p.exit_id || "")) ? { action: "block" }' in rb,
       "[17] …an edited one through a removed exit becomes Block, as the server's prune makes it")
    ok(", p2p } }; });" in rb, "[17] …and the draft is written with it")
    ok("p2p: fresh.p2p } }));" in rb, "[17] …and `orig` follows the server, so the section is not left dirty by the prune")
    ok(spa.count("rebaseDefault(selNode, fresh);") == 3, "[17] all three exit writers call the re-base (%d)" % spa.count("rebaseDefault(selNode, fresh);"))
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        spa = open(SPA, encoding="utf-8").read()
        for name, (old, new) in PLANTS.items():
            if name.startswith("spa-"):
                if old not in spa:
                    print("PLANT %-14s anchor missing — fix the plant" % name); missed.append(name); continue
                f = run_checks(SRC, spa.replace(old, new, 1))
                print("PLANT %-14s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
                if not f:
                    missed.append(name)
                continue
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
