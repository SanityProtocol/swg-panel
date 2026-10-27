#!/usr/bin/env python3
"""Self-test — per-interface torrent choice on the PANEL (docs/IFACE-P2P-PICK-PLAN.md §2–§4, 1.8.11 S11).

  [1] THE DOOR — /api/iface/update, /api/iface/create, /api/wdtt/set, /api/csqtt/set through the real handler: direct /
      exit(another node) / dev(this node's exit) stored; exit to this node, to a node not in the fleet, an exit of another
      node, and junk refused with nothing written; null pops; absent leaves it alone; a STORED target no longer valid is
      tolerated on a re-send (every save sends it back), a new one is not; the node save and the interface save share
      one target check (`_p2p_target`)
  [2] TWO FIELDS, ONE CHOICE — "torrents" in block[] takes `p2p` with it, on the same save and on a save that sends only
      block (an older tab switching the chip on); WDTT/csqtt (block applied before the ladder) and the interface (after)
  [3] PUBLISHED — the interface meta, wdtt_cfg and csqtt_cfg carry `p2p` (a WDTT restart re-posts egressBody(egressInit(cfg)))
  [4] PRUNE → BLOCK — a record whose target node is gone or is its own node, or whose exit is not among its node's exits,
      becomes Block ("torrents" appended, `p2p` popped) and is named "<node> · <record>"; through node_remove (event)
  [5] THE PLAN — under node policy iface, records are grouped by target: one entry per target with every subnet sent
      there (the leg, a band table; the far node's exit records; a device's rule-scoped devexits), direct gathered, RAW
      follows its WDTT instance, csqtt as an interface; a record with Block or no choice contributes nothing
  [6] DEAD → BLOCK + NAMED — no mesh link, a clash at the target, an exit that resolves to nothing: the subnet is in the
      block list and the record named (`_p2p_dead`); the card says "torrents on … have no way out"
  [7] THE WIRE — smart.p2p under iface: None while nothing is lowered, else {action: iface} + only the non-empty keys;
      block / direct / route unchanged
  [8] BYTE-IDENTICAL without per-interface choices — an iface fleet with chips only, and every other policy: no `_p2pi` /
      `_p2p_dead` in the plan, the wire as before
  [10] demand mesh links the pair a record's "Route through node" needs, and the offline-node line names it (node-wide too)
  [9] THE CARD — sent choices while the node reports no mode iface → "need a node update"; mode iface → nothing; a route
      group down → the existing "way out is down" line under iface too

Run: python3 tests/p2p_iface_panel_selftest.py        (0 = pass)
     --perturb    plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import contextlib, json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SRC = open(PANEL, encoding="utf-8").read()

PLANTS = {   # name: (old text, planted text) — each re-introduces a defect the checks exist for
    "door-any-node":  ('        if q not in nodes or q == nid:\n            return None, "torrents can only be routed to another node',
                       '        if q not in nodes:\n            return None, "torrents can only be routed to another node'),
    "door-junk":      ('            return "the torrent choice must be direct, exit or dev"', '            pass'),
    "door-strict":    ('            if err and {k: str(x) for k, x in pp.items() if k in ("action", "node", "exit_id")} != rec.get("p2p"):',
                       '            if err:'),
    "door-lax":       ('            if err and {k: str(x) for k, x in pp.items() if k in ("action", "node", "exit_id")} != rec.get("p2p"):',
                       '            if False:'),
    "two-fields":     ('    if "torrents" in (rec.get("block") or []):\n        rec.pop("p2p", None)\n    return None', '    return None'),
    "iface-before-block": ('        _perr = _apply_iface_p2p(ov, body, nodes, nid)   # after block AND the ladder: "torrents" in block[] wins\n'
                           '        if _perr:\n            return 400, {"ok": False, "error": _perr, "code": "bad_request"}\n        _rv = reach_level_set(ov, body)',
                           '        _rv = reach_level_set(ov, body)'),
    "create-unwired": ('        _perr = _apply_iface_p2p(ov, {k: v for k, v in body.items() if k != "p2p" or v is not None}, nodes, nid)',
                       '        _perr = None'),
    "create-null-pops": ('_apply_iface_p2p(ov, {k: v for k, v in body.items() if k != "p2p" or v is not None}, nodes, nid)',
                         '_apply_iface_p2p(ov, body, nodes, nid)'),
    "unpublished":    ('        ifc["p2p"] = ov.get("p2p") or None ', '        ifc["_p2p"] = ov.get("p2p") or None '),
    "wdtt-unpub":     ('"stopped", "block", "p2p", "egress_mode", "egress_node",', '"stopped", "block", "egress_mode", "egress_node",'),
    "prune-records":  ('        for _k in ("ifaces", "wdtt", "csqtt"):\n            for _rn, _r in', '        for _k in ():\n            for _rn, _r in'),
    "prune-dormant":  ('                if _live and isinstance(_p, dict) and _p.get("action") in ("exit", "dev")', '                if isinstance(_p, dict) and _p.get("action") in ("exit", "dev")'),
    "prune-open":     ('                    _r["block"] = [b for b in (_r.get("block") or []) if b != "torrents"] + ["torrents"]\n', ''),
    "raw-own-way":    ('_own.append((_wn + " (raw)", _RS)); _ownr.append(_wov)', '_own.append((_wn + " (raw)", _RS)); _ownr.append({})'),
    "plan-block-too": ('                if not isinstance(_rp, dict) or "torrents" in ((_r or {}).get("block") or []):',
                       '                if not isinstance(_rp, dict):'),
    "plan-no-clash":  ('                    if all(_ld) and not _clashes(nid, n_, S, _Q, "rule"):', '                    if all(_ld):'),
    "dead-open":      ('                    slot(nid).setdefault("_p2pi", {}).setdefault("block", []).append(S)\n                    slot(nid).setdefault("_p2p_dead", []).append(n_)',
                       '                    slot(nid).setdefault("_p2p_dead", []).append(n_)'),
    "dead-unnamed":   ('                    slot(nid).setdefault("_p2p_dead", []).append(n_)\n                else:', '                    pass\n                else:'),
    "wire-empty":     ('    return {"action": "iface", **out} if out else None', '    return {"action": "iface", **out}'),
    "wire-dups":      ('    out = {k: (sorted(set(pi[k])) if k != "entries"', '    out = {k: (list(pi[k]) if k != "entries"'),
    "card-silent":    ('        issues.append(perr("per-interface torrent choices need a node update', '        (lambda *a: 0)(perr("per-interface torrent choices need a node update'),
    "card-always":    ('    if _p2pa == "iface" and p2p_iface is not None and _srp is not None', '    if _p2pa == "iface" and _srp is not None'),
    "card-down-all": ('                     and p2p_route_dev(c, _r.get("p2p")) in (_dn or ())) if _dn else []',
                      '                     and _r.get("p2p")) if _dn else []'),
    "route-dev-link": ('        return str(lk.get("iface") or "").strip() if isinstance(lk, dict) else ""\n    return ""\n\n\ndef p2p_policy',
                       '        return ""\n    return ""\n\n\ndef p2p_policy'),
    "card-down-fallback": ('        elif _dn is None:                                     # a node that names no device: the line as before. One that names',
                           '        else:                                     # a node that names no device: the line as before. One that names'),
    "card-down-blocked": ('                     if isinstance(_r, dict) and rn not in (p2p_iface or ()) and "torrents" not in (_r.get("block") or [])',
                          '                     if isinstance(_r, dict)'),
    "route-dev-disabled": ('        return str(x.get("device") or "").strip() if x and x.get("enabled") is not False else ""\n    if a == "exit":\n        lk = ((node or {}).get("links") or {}).get(p2p.get("node"))\n        return str(lk.get("iface") or "").strip() if isinstance(lk, dict) else ""\n    return ""\n\n\ndef p2p_policy',
                           '        return str(x.get("device") or "").strip() if x else ""\n    if a == "exit":\n        lk = ((node or {}).get("links") or {}).get(p2p.get("node"))\n        return str(lk.get("iface") or "").strip() if isinstance(lk, dict) else ""\n    return ""\n\n\ndef p2p_policy'),
    "card-down-old":  ('    elif _p2pa in ("exit", "dev", "iface") and _p2pn and _p2pn.get("route") == "down":',
                       '    elif _p2pa in ("exit", "dev") and _p2pn and _p2pn.get("route") == "down":'),
    "card-dead":      ('    elif (_p2pa == "iface" and p2p_iface and _srp is not None and _srp.get("p2pi")', '    elif (False'),
    "card-dead-anyway": ('    elif (_p2pa == "iface" and p2p_iface and _srp is not None and _srp.get("p2pi")', '    if (_p2pa == "iface" and p2p_iface'),
    "card-dead-unheard": ('and p2p_iface and _srp is not None and _srp.get("p2pi")', 'and p2p_iface and (_srp is None or _srp.get("p2pi"))'),
    "card-by-mode":   ('and _srp is not None and not _srp.get("p2pi"):', 'and _srp is not None and (not _p2pn or _p2pn.get("mode") != "iface"):'),
    "mesh-unneeded":  ('            if _pif and _rp.get("action") == "exit" and "torrents" not in (ov.get("block") or []):', '            if False:'),
    "mesh-dormant":   ('            if _pif and _rp.get("action") == "exit" and "torrents" not in (ov.get("block") or []):',
                       '            if _rp.get("action") == "exit" and "torrents" not in (ov.get("block") or []):'),
    "offline-blind":  ('        if _rp.get("action") == "exit" and p2p_policy(n) == "iface" and "torrents" not in (ov.get("block") or []):', '        if False:'),
}


def load(src):
    m = types.ModuleType("swgpanel_p2pi"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


X1 = {"id": "aaaa0001", "label": "X", "device": "wgx0", "enabled": True, "producer": "adopted", "killswitch": True}
SN = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg9": {"meta": {"subnet": "10.28.0.0/24"}},
                     "wg7": {"meta": {"subnet": "10.38.0.0/24"}}},
      "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
SP = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}, "wg5": {"meta": {"subnet": "10.19.0.0/24"}}},
      "ether_ifaces": ["eth0"], "wan_iface": "eth0", "ether_gws": {"eth0": "198.51.100.1"},
      "node_ips": ["198.51.100.254"], "smartroute": {"mode": "kernel", "src": 1, "arr": 1}}
WD = {"wg_addr": "10.66.70.1/24", "listen": "0.0.0.0:56000", "wg_port": 56001, "raw_port": 56002, "raw_addr": "10.66.71.1/24"}
CQ = {"tun_addr": "10.77.0.1/24", "listen": "0.0.0.0:8443"}


def fleet(n1=None, n2=None, links=True, pol1="iface", pol2="iface"):
    a = {"name": "node-n", "ifaces": {"wg0": {}, "wg9": {}, "wg7": {}}, "wdtt": {"wdtt1": dict(WD)}, "csqtt": {"cq1": dict(CQ)}}
    b = {"name": "node-p", "exits": [dict(X1)], "ifaces": {"wg0": {}, "wg5": {}}}
    if links:
        a["links"] = {"n2": {"iface": "swg_p", "peer_address": "10.255.0.1"}}
        b["links"] = {"n1": {"iface": "swg_n", "peer_address": "10.255.0.0"}}
    if pol1: a["p2p"] = {"action": pol1}
    if pol2: b["p2p"] = {"action": pol2}
    for rec, extra in ((a, n1 or {}), (b, n2 or {})):
        for k, v in extra.items():
            kind, name = k.split(":", 1) if ":" in k else ("ifaces", k)
            rec[kind].setdefault(name, {}).update(v)
    return {"n1": a, "n2": b}


def run_checks(src):
    fails = []
    def ok(cond, what):
        if not cond:
            fails.append(what)
    P = load(src)
    tmp = tempfile.mkdtemp(prefix="p2pi-panel-")
    np_, rp_ = os.path.join(tmp, "nodes.json"), os.path.join(tmp, "users.json")
    json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp_, "w"))
    deps = {"nodes_path": np_, "roster_path": rp_, "node_snaps": {"n1": SN, "n2": SP}, "stats_dir": tmp, "fleet": {},
            "panel_settings": json.loads(json.dumps(P.PANEL_SETTINGS_DEFAULTS)),
            "panel_settings_path": os.path.join(tmp, "panel-settings.json")}
    P.Handler.deps = deps
    def door(path, body):
        try:
            return P.api("POST", path, {}, body, deps)
        except Exception as e:
            return 599, {"exception": repr(e)}
    def rec(nid="n1", kind="ifaces", name="wg0"):
        return ((json.load(open(np_)).get(nid) or {}).get(kind) or {}).get(name) or {}
    json.dump(fleet(), open(np_, "w"))

    # [1] the door
    U = lambda **b: door("/api/iface/update", dict({"node": "n1", "iface": "wg0"}, **b))
    for body, want in (({"action": "direct"}, {"action": "direct"}), ({"action": "exit", "node": "n2"}, {"action": "exit", "node": "n2"})):
        c, r = U(p2p=body)
        ok(c == 200 and rec().get("p2p") == want, "[1] interface: %s stored (%s %s)" % (body, c, rec().get("p2p")))
    c, r = door("/api/iface/update", {"node": "n2", "iface": "wg0", "p2p": {"action": "dev", "exit_id": X1["id"]}})
    ok(c == 200 and rec("n2").get("p2p") == {"action": "dev", "exit_id": X1["id"]}, "[1] dev → this node's own exit stored (%s)" % c)
    for bad in ({"action": "exit", "node": "n1"}, {"action": "exit", "node": "nX"}, {"action": "dev", "exit_id": X1["id"]},
                {"action": "block"}, {"action": "iface"}, "direct", ["direct"]):
        c, r = U(p2p=bad)
        ok(c == 400 and rec().get("p2p") == {"action": "exit", "node": "n2"}, "[1] refused, nothing written: %r (%s)" % (bad, c))
    c, r = U(mtu=1300)
    ok(c == 200 and rec().get("p2p") == {"action": "exit", "node": "n2"}, "[1] a save without the key leaves it alone")
    c, r = U(p2p=None)
    ok(c == 200 and "p2p" not in rec(), "[1] null pops")
    fl = json.load(open(np_)); fl["n1"]["ifaces"]["wg0"]["p2p"] = {"action": "exit", "node": "nGone"}; json.dump(fl, open(np_, "w"))
    c, r = U(p2p={"action": "exit", "node": "nGone"}, mtu=1310)
    ok(c == 200 and rec().get("p2p") == {"action": "exit", "node": "nGone"}, "[1] a stored target is tolerated on a re-send (%s %s)" % (c, r))
    c, r = U(p2p={"action": "exit", "node": "nGone2"})
    ok(c == 400, "[1] …a new invalid one is not (%s)" % c)
    c, r = door("/api/iface/create", {"node": "n1", "iface": "wg8", "protocol": "wg", "subnet": "10.31.0.0/24", "p2p": {"action": "direct"}})
    ok(c == 200 and rec(name="wg8").get("p2p") == {"action": "direct"}, "[1] create stores it (%s %s)" % (c, r))
    c, r = door("/api/iface/create", {"node": "n1", "iface": "wg6", "protocol": "wg", "subnet": "10.32.0.0/24", "p2p": {"action": "exit", "node": "n1"}})
    ok(c == 400, "[1] create refuses a bad target (%s)" % c)
    fl = json.load(open(np_)); fl["n1"]["ifaces"]["wg5"] = {"p2p": {"action": "exit", "node": "n2"}}; json.dump(fl, open(np_, "w"))
    c, r = door("/api/iface/create", {"node": "n1", "iface": "wg5", "protocol": "wg", "subnet": "10.33.0.0/24", "p2p": None})
    ok(rec(name="wg5").get("p2p") == {"action": "exit", "node": "n2"}, "[1] a create over a stored record (a ghost Recreate) with p2p null keeps the stored choice (%s %s)" % (c, rec(name="wg5")))
    c, r = door("/api/wdtt/set", {"node": "n1", "iface": "wdtt1", "p2p": {"action": "exit", "node": "n2"}})
    ok(c == 200 and rec(kind="wdtt", name="wdtt1").get("p2p") == {"action": "exit", "node": "n2"}, "[1] WDTT stores it (%s %s)" % (c, r))
    c, r = door("/api/csqtt/set", {"node": "n1", "iface": "cq1", "p2p": {"action": "direct"}})
    ok(c == 200 and rec(kind="csqtt", name="cq1").get("p2p") == {"action": "direct"}, "[1] csqtt stores it (%s %s)" % (c, r))
    ok(SRC_has(src, "def _apply_iface_p2p(", "v, err = _p2p_target(pp, nodes, nid)")
       and SRC_has(src, '        if "p2p" in body:                       # the node-wide P2P policy', "_prec, _perr = _p2p_target(_pp, nodes, nid)"),
       "[1] the node save and the interface save share one target check")

    # [2] block wins
    c, r = U(p2p={"action": "direct"}, block=["torrents", "smtp"])
    ok(c == 200 and "p2p" not in rec() and "torrents" in (rec().get("block") or []), "[2] the same save: Block wins")
    U(p2p={"action": "direct"}, block=["smtp"])
    c, r = U(block=["smtp", "torrents"])
    ok(c == 200 and "p2p" not in rec(), "[2] a save sending only block (an older tab's chip) clears the route")
    door("/api/wdtt/set", {"node": "n1", "iface": "wdtt1", "p2p": {"action": "direct"}, "block": []})
    c, r = door("/api/wdtt/set", {"node": "n1", "iface": "wdtt1", "block": ["torrents"]})
    ok(c == 200 and "p2p" not in rec(kind="wdtt", name="wdtt1"), "[2] WDTT: Block wins")
    door("/api/csqtt/set", {"node": "n1", "iface": "cq1", "p2p": {"action": "direct"}, "block": []})
    c, r = door("/api/csqtt/set", {"node": "n1", "iface": "cq1", "block": ["torrents"], "p2p": {"action": "direct"}})
    ok(c == 200 and "p2p" not in rec(kind="csqtt", name="cq1"), "[2] csqtt: Block wins")

    # [3] published
    json.dump(fleet(n1={"wg0": {"p2p": {"action": "direct"}}, "wdtt:wdtt1": {"p2p": {"action": "direct"}}, "csqtt:cq1": {"p2p": {"action": "direct"}}}), open(np_, "w"))
    ifs = {"wg0": {"meta": {}}}
    try:
        P.apply_iface_meta(json.load(open(np_))["n1"], {"wg0": {}})
        meta = {"wg0": {}}; P.apply_iface_meta(json.load(open(np_))["n1"], meta)
    except Exception as e:
        meta = {"wg0": {"err": repr(e)}}
    ok(meta["wg0"].get("p2p") == {"action": "direct"}, "[3] the interface meta publishes p2p (%s)" % meta["wg0"].get("p2p"))
    deps["node_seen"] = {"n1": 1, "n2": 1}
    try:
        c, st = P.api("GET", "/api/state", {}, {}, deps)
    except Exception as e:
        c, st = repr(e), {}
    blob = json.dumps(st)
    nd = next((n for n in ((st or {}).get("data") or {}).get("nodes") or [] if n.get("id") == "n1"), {})
    wc = (nd.get("wdtt_cfg") or {}).get("wdtt1") or {}; cc = (nd.get("csqtt_cfg") or {}).get("cq1") or {}
    ok(c == 200 and wc.get("p2p") == {"action": "direct"} and cc.get("p2p") == {"action": "direct"},
       "[3] wdtt_cfg and csqtt_cfg publish p2p (%s %s %s)" % (c, wc.get("p2p"), cc.get("p2p")))

    # [4] prune
    fl = fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "nX"}, "block": ["smtp"]}, "wg9": {"p2p": {"action": "exit", "node": "n1"}},
                   "wdtt:wdtt1": {"p2p": {"action": "dev", "exit_id": X1["id"]}}, "wg7": {"p2p": {"action": "exit", "node": "n2"}}},
               n2={"wg0": {"p2p": {"action": "dev", "exit_id": X1["id"]}}})
    ch = P.prune_p2p_refs(fl)
    ok(fl["n1"]["ifaces"]["wg0"].get("block") == ["smtp", "torrents"] and "p2p" not in fl["n1"]["ifaces"]["wg0"]
       and "p2p" not in fl["n1"]["ifaces"]["wg9"] and "torrents" in fl["n1"]["ifaces"]["wg9"]["block"]
       and "p2p" not in fl["n1"]["wdtt"]["wdtt1"] and "torrents" in fl["n1"]["wdtt"]["wdtt1"]["block"],
       "[4] gone node / own node / another node's exit → Block (%s)" % fl["n1"]["ifaces"])
    ok(fl["n1"]["ifaces"]["wg7"].get("p2p") == {"action": "exit", "node": "n2"} and fl["n2"]["ifaces"]["wg0"].get("p2p"),
       "[4] a live target is kept")
    ok(sorted(n for _, n in ch) == ["node-n · wdtt1", "node-n · wg0", "node-n · wg9"], "[4] each named <node> · <record> (%s)" % ch)
    fl = fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "nX"}, "block": ["smtp"]}}, pol1="direct")
    ch = P.prune_p2p_refs(fl)
    ok(fl["n1"]["ifaces"]["wg0"].get("p2p") == {"action": "exit", "node": "nX"} and fl["n1"]["ifaces"]["wg0"]["block"] == ["smtp"] and not ch,
       "[4] a DORMANT choice (the node on Direct) is kept as it is — never Block, never dropped (it would come back as 'not "
       "checked' once the node goes to iface; s11-pick F3) (%s %s)" % (fl["n1"]["ifaces"]["wg0"], ch))
    fl = fleet(n1={"wg0": {"p2p": {"action": "exit", "node": ["x"]}}})
    try:
        P.prune_p2p_refs(fl); _r4 = fl["n1"]["ifaces"]["wg0"]
    except Exception as e:
        _r4 = repr(e)
    ok(isinstance(_r4, dict) and "p2p" not in _r4, "[4] a malformed target (a list for a node id) is pruned, never a crash (%s)" % (_r4,))
    json.dump(fleet(n1={"wg7": {"p2p": {"action": "exit", "node": "n2"}}}), open(np_, "w"))
    with contextlib.suppress(Exception):
        P.node_remove(deps, "n2")
    ok("p2p" not in rec(name="wg7") and "torrents" in (rec(name="wg7").get("block") or []), "[4] node_remove prunes a record's route to it")
    evs = ""
    with contextlib.suppress(OSError):
        evs = open(os.path.join(tmp, "events.jsonl")).read()
    evl = [json.loads(l) for l in evs.splitlines() if l.strip()]
    ok(any(e.get("verb") == "Torrent route removed" and e.get("name") == "node-n · wg7" for e in evl), "[4] …and says so in the activity log (%s)" % evs[-300:])

    # [5] the plan
    F5 = fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}}, "wg9": {"p2p": {"action": "direct"}},
                   "wdtt:wdtt1": {"p2p": {"action": "exit", "node": "n2"}}, "csqtt:cq1": {"p2p": {"action": "direct"}},
                   "wg7": {"p2p": {"action": "direct"}, "block": ["torrents"]}},
               n2={"wg0": {"p2p": {"action": "dev", "exit_id": X1["id"]}}, "wg5": {"block": ["torrents"]}})
    pl = P.cascade_plan(F5, {"n1": SN, "n2": SP})
    pi1, pi2 = (pl.get("n1") or {}).get("_p2pi") or {}, (pl.get("n2") or {}).get("_p2pi") or {}
    e1 = pi1.get("entries") or []
    ok(len(e1) == 1 and e1[0].get("via_iface") == "swg_p" and e1[0].get("subnets") == ["10.66.70.0/24", "10.66.71.0/24", "10.8.0.0/24"]
       and P.SWG_RT_BASE <= e1[0].get("table", 0) <= P.SWG_RT_MAX, "[5] one entry per target, every subnet sent there, RAW with its instance (%s)" % e1)
    ok(sorted(pi1.get("direct") or []) == ["10.28.0.0/24", "10.77.0.0/24"], "[5] direct gathered, csqtt as an interface, Block contributes nothing (%s)" % pi1.get("direct"))
    xs = {x["subnet"] for x in (pl.get("n2") or {}).get("exit") or []}
    ok({"10.8.0.0/24", "10.66.70.0/24", "10.66.71.0/24"} <= xs and "10.28.0.0/24" not in xs, "[5] the far node gets exit records for the routed ones only (%s)" % sorted(xs))
    e2 = pi2.get("entries") or []
    dx = [d for d in (pl.get("n2") or {}).get("devexit") or [] if d.get("dev") == "wgx0"]
    ok(len(e2) == 1 and e2[0].get("via_iface") == "wgx0" and e2[0].get("subnets") == ["10.9.0.0/24"]
       and [d["subnet"] for d in dx] == ["10.9.0.0/24"] and all(d.get("scope") == "rule" and d.get("killswitch") for d in dx),
       "[5] dev: rule-scoped devexits keeping the kill-switch, only the chosen subnet (%s %s)" % (e2, dx))
    ok(not (pl.get("n1") or {}).get("_p2p") and not (pl.get("n2") or {}).get("_p2p") and not (pl.get("n1") or {}).get("smart"),
       "[5] no node-wide route and nothing in smart.entries")
    plb = P.cascade_plan(dict(F5, n1=dict(F5["n1"], p2p={"action": "block"})), {"n1": SN, "n2": SP})
    ok(not (plb.get("n1") or {}).get("_p2pi"), "[5] a stored choice under a node that is not iface is kept and lowers nothing")

    # [6] dead
    for name, fl6, sn, sub in (("no mesh link", fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}}}, links=False), SN, "10.8.0.0/24"),
                               ("a clash at the target", fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}}}),
                                dict(SN, interfaces=dict(SN["interfaces"], wg0={"meta": {"subnet": "10.9.0.0/24"}})), "10.9.0.0/24"),
                               ("an exit that resolves to nothing", fleet(n2={"wg0": {"p2p": {"action": "dev", "exit_id": "ffff0000"}}}), SN, "10.9.0.0/24")):
        pl6 = P.cascade_plan(fl6, {"n1": sn, "n2": SP})
        who = "n2" if "exit that" in name else "n1"
        p6 = (pl6.get(who) or {}).get("_p2pi") or {}
        ok(sub in (p6.get("block") or []) and not p6.get("entries") and (pl6.get(who) or {}).get("_p2p_dead") == ["wg0"],
           "[6] %s → the block list, named (%s %s)" % (name, p6, (pl6.get(who) or {}).get("_p2p_dead")))
    K6 = "torrents on {v1} have no way out (the route is unavailable) — blocked until it is"
    i6 = [(i.get("error_key"), (i.get("error_vars") or {}).get("v1")) for i in
          P._node_issues({"p2p": {"action": "iface"}}, {"smartroute": {"p2pi": 1, "p2p": {"state": "ok", "mode": "iface"}}}, p2p_iface=["wg0", "wdtt1"])]
    ok((K6, "wg0, wdtt1") in i6, "[6] the card names them (%s)" % i6)
    i6b = [i.get("error_key") for i in P._node_issues({"p2p": {"action": "iface"}}, {"smartroute": {"p2p": {"state": "ok", "mode": "legacy"}}}, p2p_iface=["wg0"])]
    ok(K6 not in i6b, "[6] …not on a node that does not run the choices (it lets them out unchecked; it is told to update) (%s)" % i6b)
    i6d = [i.get("error_key") for i in P._node_issues({"p2p": {"action": "iface"}}, {}, p2p_iface=["wg0"])]
    ok(K6 not in i6d, "[6] …nor on a node never heard from (s11-pick F5) (%s)" % i6d)
    i6c = [i.get("error_key") for i in P._node_issues({"p2p": {"action": "iface"}}, {"smartroute": {"p2pi": 1, "p2p": {"state": "error", "mode": "iface"}}}, p2p_iface=["wg0"])]
    ok(K6 not in i6c, "[6] …nor where its rules failed to load (not in force) (%s)" % i6c)
    # [6b] the route's way out down, per interface (backlog F48): the node names the devices down
    KD, KG = "torrents on {v1}: their route's way out is down — blocked until it is back", "the torrent route's way out is down — torrent traffic is blocked until it is back"
    C6 = {"p2p": {"action": "iface"}, "exits": [dict(X1)], "links": {"n2": {"iface": "swg_p"}},
          "ifaces": {"wg9": {"p2p": {"action": "dev", "exit_id": X1["id"]}}, "wg7": {"p2p": {"action": "exit", "node": "n2"}}, "wg0": {}},
          "wdtt": {"wdtt1": {"p2p": {"action": "exit", "node": "n2"}}}}
    def card6(rep):
        return [(i.get("error_key"), (i.get("error_vars") or {}).get("v1")) for i in
                P._node_issues(C6, {"smartroute": {"p2pi": 1, "p2p": dict({"state": "ok", "mode": "iface"}, **rep)}})]
    ok((KD, "wg9") in card6({"route": "down", "down": ["wgx0"]}), "[6b] the exit's device down → only the interface routed through it (%s)" % card6({"route": "down", "down": ["wgx0"]}))
    ok((KD, "wdtt1, wg7") in card6({"route": "down", "down": ["swg_p"]}), "[6b] the link to the node down → the interfaces (and WDTT) routed through it (%s)" % card6({"route": "down", "down": ["swg_p"]}))
    ok((KG, None) in card6({"route": "down"}), "[6b] a node that names no device → the line as before (%s)" % card6({"route": "down"}))
    C6["ifaces"]["wg5"] = {"p2p": {"action": "exit", "node": "n2"}, "block": ["torrents"]}
    ok((KD, "wdtt1, wg7") in card6({"route": "down", "down": ["swg_p"]}), "[6b] (review F3) an interface on Block (strictest wins) is not named (%s)" % card6({"route": "down", "down": ["swg_p"]}))
    _i = [(i.get("error_key"), (i.get("error_vars") or {}).get("v1")) for i in
          P._node_issues(C6, {"smartroute": {"p2pi": 1, "p2p": {"state": "ok", "mode": "iface", "route": "down", "down": ["swg_p"]}}}, p2p_iface=["wg7"])]
    ok((KD, "wdtt1") in _i, "[6b] (review F3) …nor one already named dead (%s)" % _i)
    _i9 = [k for k, _ in card6({"route": "down", "down": ["wgx-unused"]})]
    ok(KD not in _i9 and KG not in _i9, "[6b] (review F9) devices named down that no running interface leaves by → no route line — never the node-wide one, false under per-interface (%s)" % _i9)
    _c = dict(C6, exits=[dict(X1, enabled=False)])
    ok(P.p2p_route_dev(_c, {"action": "dev", "exit_id": X1["id"]}) == "" and P.p2p_route_dev(dict(C6, exits=[dict(X1, device=" wgx0 ")]), {"action": "dev", "exit_id": X1["id"]}) == "wgx0",
       "[6b] (review F1/F4) a disabled exit has no device; a name is stripped — resolve_exit's reading")
    ok(P.p2p_route_dev(C6, {"action": "dev", "exit_id": X1["id"]}) == "wgx0" and P.p2p_route_dev(C6, {"action": "exit", "node": "n2"}) == "swg_p"
       and P.p2p_route_dev(C6, {"action": "direct"}) == "" and P.p2p_route_dev(C6, {"action": "exit", "node": "gone"}) == "",
       "[6b] a record's route device: the exit's, or the mesh link's; none for direct or a node not linked")

    # [7] the wire
    i0 = src.find('"p2p": ({"action": _p2pa}')
    def wire(node, plan=None):
        s = src[i0 + len('"p2p": '):]
        depth = 0
        for j, ch in enumerate(s):
            depth += ch == "("; depth -= ch == ")"
            if depth == 0 and j:
                break
        return eval(s[:j + 1], {"p2p_policy": P.p2p_policy, "p2p_iface_wire": P.p2p_iface_wire, "node": node, "my_plan": plan})
    ok(i0 > 0 and wire({"p2p": {"action": "iface"}}, pl.get("n1")) == {"action": "iface", "entries": e1, "direct": ["10.28.0.0/24", "10.77.0.0/24"]},
       "[7] iface: the lowered groups, only the non-empty keys (%s)" % (wire({"p2p": {"action": "iface"}}, pl.get("n1")) if i0 > 0 else None))
    ok(wire({"p2p": {"action": "iface"}}, {"_p2pi": {"block": ["10.9.0.0/24", "10.8.0.0/24", "10.9.0.0/24"]}}) == {"action": "iface", "block": ["10.8.0.0/24", "10.9.0.0/24"]},
       "[7] a block list alone is sent, sorted and once")
    ok(wire({"p2p": {"action": "iface"}}, {}) is None and wire({"p2p": {"action": "iface"}}, {"_p2pi": {}}) is None, "[7] nothing lowered → None")
    ok(wire({"p2p": {"action": "direct"}}, pl.get("n1")) == {"action": "direct"} and wire({}, pl.get("n1")) == {"action": "block"},
       "[7] block / direct unchanged")

    # [8] byte-identical without per-interface choices
    for pol in ("iface", "block", "direct", None):
        F8 = fleet(n1={"wg0": {"block": ["torrents"]}}, pol1=pol, pol2=pol)
        p8 = P.cascade_plan(F8, {"n1": SN, "n2": SP})
        ok(not any(k in (p8.get(n) or {}) for n in p8 for k in ("_p2pi", "_p2p_dead")), "[8] %s, chips only: no per-interface plan" % pol)
        ok(i0 > 0 and wire(F8["n1"], p8.get("n1")) == ({"action": pol or "block"} if pol != "iface" else None), "[8] %s: the wire as before" % pol)
    F8b = fleet(n1={"wg0": {"p2p": {"action": "direct"}}}, pol1="exit", pol2=None)
    F8b["n1"]["p2p"] = {"action": "exit", "node": "n2"}
    p8b = P.cascade_plan(F8b, {"n1": SN, "n2": SP})
    ok(not (p8b.get("n1") or {}).get("_p2pi") and (p8b.get("n1") or {}).get("_p2p"), "[8] a node-wide route ignores the stored choices")

    # [10] the links and the offline line know a record's route through a node (S11 review F2, F10)
    F10 = fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}}}, links=False)
    need = P.mesh_need(F10, deps)
    ok(any(set(x) == {"n1", "n2"} for x in need), "[10] demand mesh links the pair a record's 'Route through node' needs (%s)" % need)
    ok(not any(set(x) == {"n1", "n2"} for x in P.mesh_need(fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}}}, links=False, pol1="block"), deps)),
       "[10] …not for a dormant one (the node not on iface)")
    ok(P._exit_nodes(F10["n1"]) == {"n2"} and P._exit_nodes(fleet(pol1=None)["n1"] | {"p2p": {"action": "exit", "node": "n2"}}) == {"n2"},
       "[10] the offline-node line knows a record's torrent route through a node, and the node-wide one")
    ok(P._exit_nodes(fleet(n1={"wg0": {"p2p": {"action": "exit", "node": "n2"}, "block": ["torrents"]}})["n1"]) == set(), "[10] …not a blocked record's")

    # [9] the card
    K9 = "per-interface torrent choices need a node update — until then those interfaces' torrents are not checked"
    keys = lambda c, snap, pi: [i.get("error_key") or i.get("error") for i in P._node_issues(c, snap, p2p_iface=pi)]
    ok(K9 in keys({"p2p": {"action": "iface"}}, {"smartroute": {"p2p": {"state": "ok", "mode": "legacy"}}}, []), "[9] node runs legacy → need an update")
    ok(K9 in keys({"p2p": {"action": "iface"}}, {"smartroute": {}}, []), "[9] node reports no p2p → need an update")
    ok(K9 not in keys({"p2p": {"action": "iface"}}, {"smartroute": {"p2pi": 1, "p2p": {"state": "ok", "mode": "iface"}}}, []), "[9] a node that runs them → nothing")
    ok(K9 not in keys({"p2p": {"action": "iface"}}, {"smartroute": {"p2pi": 1, "p2p": {"state": "ok", "mode": "legacy"}}}, []),
       "[9] …nor before its first sync after the choice (it says p2pi; its mode lags a sync)")
    ok(K9 not in keys({"p2p": {"action": "iface"}}, {"smartroute": {}}, None), "[9] nothing sent → nothing")
    ok(K9 not in keys({"p2p": {"action": "iface"}}, {}, []), "[9] no smart status reported yet → nothing")
    ok(any("way out is down" in (k or "") for k in keys({"p2p": {"action": "iface"}}, {"smartroute": {"p2pi": 1, "p2p": {"state": "ok", "mode": "iface", "route": "down"}}}, [])),
       "[9] a route group down → the way-out line under iface too")
    return fails


def SRC_has(src, fn_anchor, needle):
    i = src.find(fn_anchor)
    return i >= 0 and needle in src[i:i + 4000]


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if old not in SRC:
                print("PLANT %-16s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(SRC.replace(old, new, 1))
            print("PLANT %-16s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(SRC)
    for x in f:
        print("FAIL", x)
    print("p2p_iface_panel_selftest:", "PASS" if not f else "%d FAIL" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
