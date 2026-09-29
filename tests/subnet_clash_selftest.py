#!/usr/bin/env python3
"""Self-test — a subnet is never cascaded to a node that has an interface on it (T37, docs/ROUTING-PEERS-MESH-PLAN.md §8 P3).

The exit routes replies by DESTINATION (`to S lookup T`, above its main table), so a subnet it also holds cannot work both
ways, and the side that loses is the exit's OWN clients on it: every packet to them goes back over the mesh, the moment
another node's rule or default list names that exit. Subnets are meant to be unique across the fleet, but adopted
interfaces, declarative nodes and servers enrolled from another panel bypass that check, and the installers' defaults
(10.8.0.0/24, 10.9.0.0/24) make a shared subnet the ordinary case. Live 2026-09-23: a test default list on msk-main
cascaded its awg2 (10.9.0.0/24) to nixos, whose wdtt1 is 10.9.0.0/24 — nixos sent its own wdtt1 clients' traffic to
msk-main. So `cascade_plan` leaves such a pair out, as it leaves out a pair whose mesh link is missing, and the ENTRY
node's card says which interface clashes with what.

  THE PLAN (in-process `cascade_plan`)
    [1] control — nothing shared: the smart rule, the forward and their exit records are planned, and nothing is reported
    [2] a smart rule toward P for a subnet P also holds: no entry, no exit record at P, the other pair untouched, reported
    [3] a whole-interface forward to P for a subnet P holds: the same
    [4] P's WDTT subnet counts (the live case)   [5] its RAW subnet counts, named "(raw)"   [6] its csqtt subnet counts
    [7] P's mesh links never count — by the link's device, the `swg_` prefix, or the `system` flag (P3b's onward hop
        arrives from a link address inside one of them)
    [8] a partial overlap counts
    [9] the entry's own RAW subnet is named "(raw)" on its card
    [10] the node's default list (an Auto interface lowered with it) is held to the same rule
    [11] P's arrivals never include the subnet
    [13] a subnet ANOTHER node already sends P: the first origin keeps it, the second is left out and told who has it
    [14] an operator's mesh prefix ("wg") hides none of P's real interfaces   [15] what the node itself flags `system` is not P's
  THE CARD (a REAL panel process: temp state, scratch port, no auth; the nodes are played by POSTing /api/node/sync)
    [12] the entry node's card names both interfaces and both subnets, a whole-interface forward's line says its traffic
         leaves by the node's own address, a second origin's line names the node that has the subnet; the far node's card
         says nothing; and what the panel sends each node matches the plan

Run: python3 tests/subnet_clash_selftest.py   (0 = pass)
  --plant <x>  plant one defect in a copy of the panel and expect RED on its own check (exit 0 when caught):
     smart    the rule branch plans the pair anyway
     forward  the whole-interface forward plans the pair anyway
     wdtt     P's WDTT subnets are not counted as P's
     mesh     P's mesh links are counted as P's subnets
     raw      the entry's RAW subnet goes unnamed
     card     the card never says it
     seam     the sync never hands the card what the plan found
     dup      a subnet another node already sends P is planned again
     metasys  what the node flags `system` is counted as P's
"""
import importlib.machinery, importlib.util, json, os, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {   # name: (marker of the check it must redden, anchor, replacement)
    "smart": ("[2]", "                if _clashes(nid, name or auto_label, S, P, \"rule\"):\n                    return False",
              "                if False:\n                    return False"),
    "forward": ("[3]", "            if _clashes(nid, name or auto_label, S, P, \"forward\"):\n                return\n",
                "            if False:\n                return\n"),
    "wdtt": ("[4]", '    for ifn, w in ((node or {}).get("wdtt") or {}).items():\n        for nm, a in',
             '    for ifn, w in {}.items():\n        for nm, a in'),
    "mesh": ("[7]", '                if (ifn in _mesh or str(ifn).startswith("swg_") or meta.get("system")\n'
                    '                        or ((n.get("ifaces") or {}).get(ifn) or {}).get("system")):\n                    continue',
             "                if False:\n                    continue"),
    "raw": ("[9]", '_collect_egress(nid, _wov, _RS, targets, name=_wn + " (raw)")', "_collect_egress(nid, _wov, _RS, targets)"),
    "card": ("[12]", "    for e in clash or ():\n        why = (", "    for e in ():\n        why = ("),
    "seam": ("[12]", '        Handler.deps["cas_clash"] = {_n: _p["_clash"] for _n, _p in cas_plans.items() if _p.get("_clash")}',
             '        Handler.deps["cas_clash"] = {}'),
    "dup": ("[13]", "        dup = next((e for e in _into.get(P) or () if e[1] != nid and e[0].version == s.version and e[0].overlaps(s)), None)",
            "        dup = None"),
    "metasys": ("[15]", 'if (ifn in _mesh or str(ifn).startswith("swg_") or meta.get("system")',
                'if (ifn in _mesh or str(ifn).startswith("swg_")'),
}
TMP = tempfile.mkdtemp(prefix="subnet-clash-")
server = PANEL
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _m, old, new = PLANTS[PLANT]
    src = open(PANEL, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new, 1))

_l = importlib.machinery.SourceFileLoader("swgpanel_clash", server)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_clash", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

D1 = "203.0.113.80/32"
SR = {"mode": "kernel", "src": 1, "arr": 1}


def R(targets, **kw):
    return {"enabled": True, "category": "custom", "targets": targets, **kw}


def iface(sub):
    return {"meta": {"subnet": sub}}


def fleet(n_list=None, p_wdtt=None, p_csqtt=None, p_ifaces=None, p_list=None, n_wdtt=None):
    """N = n1: wg0 SMART 10.8/24 (D1 → P), wg9 FORWARD 10.28/24 → P, wg3 Auto 10.33/24. P = n2."""
    n1 = {"name": "node-n", "routing_mode": "kernel",
          "ifaces": {"wg0": {"egress_mode": "smart", "routing": [R(D1, action="exit", node="n2")]},
                     "wg9": {"egress_mode": "forward", "egress_node": "n2"}, "wg3": {}},
          "links": {"n2": {"iface": "swg_p", "peer_address": "10.255.0.1"}}}
    n2 = {"name": "node-p", "routing_mode": "kernel", "ifaces": dict(p_ifaces or {}),
          "links": {"n1": {"iface": "swg_n", "peer_address": "10.255.0.0"}}}
    if n_list is not None:
        n1["default_routing"] = n_list
        P.derive_default_exit(n1)
    if p_list is not None:
        n2["default_routing"] = p_list
        P.derive_default_exit(n2)
    if p_wdtt:
        n2["wdtt"] = p_wdtt
    if p_csqtt:
        n2["csqtt"] = p_csqtt
    if n_wdtt:
        n1["wdtt"] = n_wdtt
    return {"n1": n1, "n2": n2}


def snaps(p_extra=None, p_links=None):
    sn = {"interfaces": {"wg0": iface("10.8.0.0/24"), "wg9": iface("10.28.0.0/24"), "wg3": iface("10.33.0.0/24"),
                         "swg_p": iface("10.255.0.0/31")}, "smartroute": dict(SR)}
    sp = {"interfaces": {"wg0": iface("10.9.0.0/24"), "wg5": iface("10.19.0.0/24"), "swg_n": iface("10.255.0.0/31"),
                         **{k: iface(v) for k, v in (p_extra or {}).items()}},
          "ether_ifaces": ["eth0"], "wan_iface": "eth0", "node_ips": ["198.51.100.9"], "smartroute": dict(SR)}
    return {"n1": sn, "n2": sp}


def plan(nodes, sn=None):
    return P.cascade_plan(nodes, sn or snaps())


def smart_to_p(pl, S):
    return [e for e in (pl.get("n1") or {}).get("smart") or [] if e.get("subnet") == S and e.get("via_iface") == "swg_p"]


def fwd_to_p(pl, S):
    return [e for e in (pl.get("n1") or {}).get("forward") or [] if e.get("subnet") == S]


def exit_at_p(pl, S):
    return [e for e in (pl.get("n2") or {}).get("exit") or [] if e.get("subnet") == S]


def clash(pl, nid="n1"):
    return (pl.get(nid) or {}).get("_clash") or []


try:
    # ── THE PLAN ─────────────────────────────────────────────────────────────────────────────────────────────────
    print("[1] control — nothing shared")
    pl = plan(fleet())
    check("[1] the smart rule's entry toward P is planned", len(smart_to_p(pl, "10.8.0.0/24")) == 1, pl.get("n1"))
    check("[1] the forward is planned, and P holds both exit records",
          fwd_to_p(pl, "10.28.0.0/24") and exit_at_p(pl, "10.8.0.0/24") and exit_at_p(pl, "10.28.0.0/24"), pl)
    check("[1] nothing is reported on either node", not clash(pl) and not clash(pl, "n2"), clash(pl))

    print("\n[2] a smart rule toward P for a subnet P also holds")
    pl = plan(fleet(), snaps({"wg7": "10.8.0.0/24"}))
    check("[2] no entry toward P for 10.8.0.0/24", not smart_to_p(pl, "10.8.0.0/24"), smart_to_p(pl, "10.8.0.0/24"))
    check("[2] no exit record for it at P (P's own wg7 keeps its routing)", not exit_at_p(pl, "10.8.0.0/24"), exit_at_p(pl, "10.8.0.0/24"))
    check("[2] the other pair (the 10.28 forward) is untouched", fwd_to_p(pl, "10.28.0.0/24") and exit_at_p(pl, "10.28.0.0/24"), pl)
    check("[2] reported on the entry node, exactly", clash(pl) == [{"iface": "wg0", "subnet": "10.8.0.0/24", "node": "n2", "kind": "rule",
                                                                  "their": "wg7", "their_subnet": "10.8.0.0/24", "via": ""}], clash(pl))
    check("[2] …and not on the far node", not clash(pl, "n2"), clash(pl, "n2"))
    check("[2] the report is a list, so a plan still serialises", isinstance((pl.get("n1") or {}).get("_clash"), list)
          and bool(json.dumps(pl)), type((pl.get("n1") or {}).get("_clash")))

    print("\n[3] a whole-interface forward to P for a subnet P holds")
    pl = plan(fleet(), snaps({"wg7": "10.28.0.0/24"}))
    check("[3] no forward, no exit record", not fwd_to_p(pl, "10.28.0.0/24") and not exit_at_p(pl, "10.28.0.0/24"), pl)
    check("[3] the smart pair is untouched", smart_to_p(pl, "10.8.0.0/24") and exit_at_p(pl, "10.8.0.0/24"), pl)
    check("[3] reported, naming wg9, as a forward", [(e["iface"], e["kind"]) for e in clash(pl)] == [("wg9", "forward")], clash(pl))

    print("\n[4]–[6] P's WDTT, RAW and csqtt subnets are P's")
    pl = plan(fleet(p_wdtt={"wdtt1": {"wg_addr": "10.8.0.1/24"}}))
    check("[4] P's WDTT subnet counts (the live case) — no entry, reported with its name",
          not smart_to_p(pl, "10.8.0.0/24") and [e["their"] for e in clash(pl)] == ["wdtt1"], clash(pl))
    pl = plan(fleet(p_wdtt={"wdtt2": {"wg_addr": "10.60.0.1/24", "raw_addr": "10.8.0.1/24", "raw_port": 56003}}))
    check("[5] its RAW subnet counts, named \"(raw)\"", not smart_to_p(pl, "10.8.0.0/24")
          and [e["their"] for e in clash(pl)] == ["wdtt2 (raw)"], clash(pl))
    pl = plan(fleet(p_csqtt={"csqtt1": {"tun_addr": "10.8.0.1/24"}}))
    check("[6] its csqtt subnet counts", not smart_to_p(pl, "10.8.0.0/24") and [e["their"] for e in clash(pl)] == ["csqtt1"], clash(pl))

    print("\n[7] P's mesh links never count")
    pl = plan(fleet(), snaps({"swg_q": "10.8.0.0/24"}))
    check("[7] a `swg_` device P reports on the subnet is not P's", smart_to_p(pl, "10.8.0.0/24") and not clash(pl), clash(pl))
    _f = fleet(); _f["n2"]["links"]["n3"] = {"iface": "meshq", "peer_address": "10.255.0.3"}
    pl = plan(_f, snaps({"meshq": "10.8.0.0/24"}))
    check("[7] a link device of any name is not P's", smart_to_p(pl, "10.8.0.0/24") and not clash(pl), clash(pl))
    pl = plan(fleet(p_ifaces={"lnk9": {"system": True}}), snaps({"lnk9": "10.8.0.0/24"}))
    check("[7] a `system` interface is not P's", smart_to_p(pl, "10.8.0.0/24") and not clash(pl), clash(pl))

    print("\n[8] a partial overlap")
    pl = plan(fleet(), snaps({"wg7": "10.8.0.128/25"}))
    check("[8] a /25 inside the entry's /24 counts", not smart_to_p(pl, "10.8.0.0/24")
          and [e["their_subnet"] for e in clash(pl)] == ["10.8.0.128/25"], clash(pl))

    print("\n[9] the entry's own RAW subnet")
    pl = plan(fleet(n_wdtt={"wdttN": {"wg_addr": "10.44.0.1/24", "raw_addr": "10.45.0.1/24", "raw_port": 56003,
                                      "egress_mode": "smart", "routing": [R(D1, action="exit", node="n2")]}}),
              snaps({"wg7": "10.45.0.0/24"}))
    check("[9] its entry is left out and the card names it \"wdttN (raw)\"",
          [e["iface"] for e in clash(pl)] == ["wdttN (raw)"]
          and not [e for e in pl["n1"].get("smart") or [] if e.get("subnet") == "10.45.0.0/24" and e.get("via_iface") == "swg_p"]
          and [e for e in pl["n1"].get("smart") or [] if e.get("subnet") == "10.44.0.0/24" and e.get("via_iface") == "swg_p"],
          clash(pl))

    print("\n[10] the node's default list is held to the same rule")
    LST = [R(D1, action="exit", node="n2")]
    pl = plan(fleet(n_list=LST))
    check("[10] control: the list lowers the Auto wg3 toward P", len(smart_to_p(pl, "10.33.0.0/24")) == 1, pl.get("n1"))
    pl = plan(fleet(n_list=LST), snaps({"wg7": "10.33.0.0/24"}))
    check("[10] P holds 10.33.0.0/24: no entry for the Auto interface, reported naming it",
          not smart_to_p(pl, "10.33.0.0/24") and not exit_at_p(pl, "10.33.0.0/24")
          and [e["iface"] for e in clash(pl)] == ["wg3"], clash(pl))

    print("\n[11] P's arrivals")
    pl = plan(fleet(p_list=[R(D1, action="direct")]), snaps({"wg7": "10.8.0.0/24"}))
    _subs = ((pl.get("n2") or {}).get("arrivals") or {}).get("subnets") or []
    check("[11] P's arrivals never include the subnet it holds, and still include the other one",
          "10.8.0.0/24" not in _subs and "10.28.0.0/24" in _subs, _subs)

    print("\n[13] a subnet another node already sends P")
    N3 = {"name": "node-m", "routing_mode": "kernel",
          "ifaces": {"wgZ": {"egress_mode": "smart", "routing": [R(D1, action="exit", node="n2")]}},
          "links": {"n2": {"iface": "swg_pm", "peer_address": "10.255.0.3"}}}
    _f = fleet(); _f["n3"] = N3; _f["n2"]["links"]["n3"] = {"iface": "swg_m", "peer_address": "10.255.0.2"}
    _sn = snaps(); _sn["n3"] = {"interfaces": {"wgZ": iface("10.8.0.0/24")}, "smartroute": dict(SR)}
    pl = plan(_f, _sn)
    check("[13] the first origin keeps it: node-n's entry and ONE exit record at P for 10.8.0.0/24, through node-n's link",
          smart_to_p(pl, "10.8.0.0/24") and [e.get("via_iface") for e in exit_at_p(pl, "10.8.0.0/24")] == ["swg_n"], exit_at_p(pl, "10.8.0.0/24"))
    check("[13] the second is left out: node-m is sent no entry toward P for it",
          not [e for e in (pl.get("n3") or {}).get("smart") or [] if e.get("subnet") == "10.8.0.0/24" and e.get("via_iface") == "swg_pm"],
          (pl.get("n3") or {}).get("smart"))
    check("[13] …and told who has it", clash(pl, "n3") == [{"iface": "wgZ", "subnet": "10.8.0.0/24", "node": "n2", "kind": "rule",
                                                            "their": "wg0", "their_subnet": "10.8.0.0/24", "via": "n1"}], clash(pl, "n3"))
    check("[13] the first origin is told nothing", not clash(pl), clash(pl))

    print("\n[14]–[15] what is P's and what is not")
    _f = fleet(); _f["n2"]["mesh_prefix"] = "wg"
    pl = plan(_f, snaps({"wg7": "10.8.0.0/24"}))
    check("[14] an operator's mesh prefix \"wg\" hides none of P's real interfaces: wg7 still clashes",
          not smart_to_p(pl, "10.8.0.0/24") and [e["their"] for e in clash(pl)] == ["wg7"], clash(pl))
    _sn = snaps(); _sn["n2"]["interfaces"]["lnkx"] = {"meta": {"subnet": "10.8.0.0/24", "system": True}}
    pl = plan(fleet(), _sn)
    check("[15] an interface the node itself flags `system` (no stored flag, no link record) is not P's",
          smart_to_p(pl, "10.8.0.0/24") and not clash(pl), clash(pl))

    # ── THE CARD — a real panel ────────────────────────────────────────────────────────────────────────────────────
    print("\n[12] the card, through a real panel")
    state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
    NODES = os.path.join(state, "nodes.json")
    _f = fleet()
    _f["n3"] = {"name": "node-m", "routing_mode": "kernel", "ifaces": {"wg4": {"egress_mode": "forward", "egress_node": "n2"}},
                "links": {"n2": {"iface": "swg_pm", "peer_address": "10.255.0.3"}}}
    _f["n2"]["links"]["n3"] = {"iface": "swg_m", "peer_address": "10.255.0.2"}
    # the rest of a real link record (the mesh reconciler re-stages a link device a node has not reported yet from it)
    for _a, _b, _addr, _sub in (("n1", "n2", "10.255.0.0", "10.255.0.0/31"), ("n2", "n1", "10.255.0.1", "10.255.0.0/31"),
                                ("n3", "n2", "10.255.0.2", "10.255.0.2/31"), ("n2", "n3", "10.255.0.3", "10.255.0.2/31")):
        _f[_a]["links"][_b].update({"subnet": _sub, "address": _addr, "listen_port": 9999})
    for _n in _f:
        _f[_n]["id"] = _n
    json.dump(_f, open(NODES, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    fleet_cfg = os.path.join(TMP, "fleet.json")
    json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet_cfg, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
    log = open(os.path.join(TMP, "panel.log"), "w+")
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "SWG_PANEL_FLEET": fleet_cfg, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                 "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                 "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
    try:
        def req(path, data=None, token=None):
            r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                       data=json.dumps(data).encode() if data is not None else None,
                                       headers={"Content-Type": "application/json",
                                                **({"Authorization": "Bearer " + token} if token else {})})
            try:
                with urllib.request.urlopen(r, timeout=30) as resp:
                    return resp.status, json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    sys.exit("panel exited: " + open(log.name).read()[-2000:])
                time.sleep(0.1)
        TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("n1", "n2", "n3")}
        SN = snaps({"wg7": "10.8.0.0/24"})
        SN["n3"] = {"interfaces": {"wg4": iface("10.28.0.0/24"), "swg_pm": iface("10.255.0.2/31")}, "smartroute": dict(SR)}
        SN["n2"]["interfaces"]["swg_m"] = iface("10.255.0.2/31")      # each end reports its link device, as a real node does
        for _n in SN:
            SN[_n].update({"hostname": _n, "generated_at": int(time.time()), "noded_version": "t"})
        _c2, r2 = req("/api/node/sync", {"snapshot": SN["n2"]}, TOK["n2"])
        _c1, r1 = req("/api/node/sync", {"snapshot": SN["n1"]}, TOK["n1"])
        _c3, r3 = req("/api/node/sync", {"snapshot": SN["n3"]}, TOK["n3"])
        _c2, r2 = req("/api/node/sync", {"snapshot": SN["n2"]}, TOK["n2"])      # again, now that all have reported
        check("[12] every sync answered", _c1 == 200 and _c2 == 200 and _c3 == 200, (_c1, _c2, _c3))
        check("[12] what node-m is sent: no forward for 10.28.0.0/24 (node-n already sends P that subnet)",
              not [e for e in ((r3.get("cascade") or {}).get("forward") or []) if e.get("subnet") == "10.28.0.0/24"], r3.get("cascade"))
        _ents = ((r1.get("smart") or {}).get("entries") or [])
        check("[12] what n1 is sent: no entry for 10.8.0.0/24 toward P, the forward to P kept",
              not [e for e in _ents if e.get("subnet") == "10.8.0.0/24" and e.get("via_iface") == "swg_p"]
              and [e for e in ((r1.get("cascade") or {}).get("forward") or []) if e.get("subnet") == "10.28.0.0/24"], r1.get("cascade"))
        check("[12] what P is sent: no exit record for 10.8.0.0/24, the 10.28 one kept",
              not [e for e in ((r2.get("cascade") or {}).get("exit") or []) if e.get("subnet") == "10.8.0.0/24"]
              and [e for e in ((r2.get("cascade") or {}).get("exit") or []) if e.get("subnet") == "10.28.0.0/24"], r2.get("cascade"))
        _c, st = req("/api/state")
        cards = {n.get("id"): n.get("issues") or [] for n in (st.get("data") or {}).get("nodes") or []}
        want = ("wg0 (10.8.0.0/24) isn't sent to node-p: wg7 there uses 10.8.0.0/24, so replies couldn't find their way back. "
                "Rules toward node-p are skipped for wg0 until one of them gets a different subnet.")
        check("[12] the entry node's card names both interfaces and both subnets", want in cards.get("n1", []), cards.get("n1"))
        want3 = ("wg4 (10.28.0.0/24) isn't sent to node-p: wg9 on node-n already sends it 10.28.0.0/24, so replies couldn't find "
                 "their way back. Forwarding is off for wg4, so its traffic leaves by this server's own address until one of them "
                 "gets a different subnet.")
        check("[12] a second origin's card names the node that has the subnet, and says its forward leaves by its own address",
              want3 in cards.get("n3", []), cards.get("n3"))
        check("[12] the far node's card says nothing about it", not any("isn't sent to" in i for i in cards.get("n2", [])), cards.get("n2"))
        _raw = [i for n in (st.get("data") or {}).get("nodes") or [] if n.get("id") == "n3" for i in (n.get("issue_keys") or n.get("issues_i18n") or [])]
        print("    (translation payload for the second origin's line: %s)" % ("present" if _raw else "not exposed under issue_keys/issues_i18n"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
finally:
    pass

if PLANT:
    marker = PLANTS[PLANT][0]
    hit = [f for f in FAILS if f.startswith(marker)]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
