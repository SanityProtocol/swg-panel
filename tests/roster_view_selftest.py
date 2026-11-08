#!/usr/bin/env python3
"""Self-test — the shared roster view and the per-node index (docs/SCALE-PLAN.md §2 P2 + P3, "K2 — design"; 1.8.12 Scale).

A sync and /api/state read users.json from ONE parsed copy, shared until the next save (roster_view, P2), and a sync walks
only the syncing node's peers (_peers_on, P3). Nothing a node is sent may change, and nothing may ever write the shared copy:
a write there would reach every node's next sync, and a peer dropped from a desired set is REMOVED by its node.

  [1] roster_view — the same object until the file changes: a save, an outside atomic replace or an in-place rewrite gives
      a new one; no file → read each time, never kept
  [2] the mark is taken BEFORE the read: a save landing while the file is read is never kept as current
  [3] writers: peer_set and roster_save refuse the view; roster_own gives a fresh copy of it (any other roster as it is);
      a sync that imports (the T-18 mirror) writes users.json, the import is in the next view, the view it read is unchanged
  [4] _peers_on — from the view: per node, roster order, once a peer, tuples, a non-string node names none, built once per
      revision; any other roster: every dict peer (the walk it replaced)
  [5] SWG_ROSTER_GUARD (the gate runner sets it for every gate): on with the variable; the view is hashed when published;
      a sync and /api/state leave it as it was; a reader that writes it ends the panel; every JSON reply checks
  [6] the differential: 200 random fleets × their nodes — every function the index feeds, on the view, equals the pre-K2
      panel's (bef1783a) on the plain roster, and this panel's on a plain copy
  [7] whole sync replies: the pre-K2 handler and this one, in process, on the same state and snapshots (one with a T-18
      import, for the copy-on-write wiring) — byte for byte

Run: python3 tests/roster_view_selftest.py      (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import base64, contextlib, json, os, random, shutil, subprocess, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PRE_K2 = "bef1783a"                                   # the last commit before K2: its sync walks the whole roster
PSRC = open(PANEL, encoding="utf-8").read()
NOW = 1_800_000_000

PLANTS = {   # name: (old text, planted text) — all in the panel
    "view-nomark":    ("    if c is None or m is None or c[:2] != (path, m):\n        with _ROSTER_VIEW_LOCK:",
                       "    if c is None or m is None:\n        with _ROSTER_VIEW_LOCK:"),
    "view-markafter": ("            c, m = _ROSTER_VIEW[0], roster_mark(path)\n            if c is None or m is None or c[:2] != (path, m):\n"
                       "                v = _RosterView(roster_load(path))",
                       "            c, m = _ROSTER_VIEW[0], roster_mark(path)\n            if c is None or m is None or c[:2] != (path, m):\n"
                       "                v = _RosterView(roster_load(path)); m = roster_mark(path)"),
    "own-noswap":     ("    return roster_load(path) if isinstance(roster, _RosterView) else roster", "    return roster"),
    "own-t18":        ('                    roster = roster_own(Handler.deps["roster_path"], roster)   # (P2: never the shared view)\n'
                       '                    _pp = peer_set(', '                    _pp = peer_set('),
    "set-noguard":    ('    if isinstance(roster, _RosterView):\n        raise RuntimeError("peer_set:', '    if False:\n        raise RuntimeError("peer_set:'),
    "save-noguard":   ('    if isinstance(roster, _RosterView):\n        raise RuntimeError("roster_save:', '    if False:\n        raise RuntimeError("roster_save:'),
    "idx-lists":      ("            idx = roster.idx = {n: tuple(v) for n, v in idx.items()}", "            roster.idx = idx"),
    "idx-anynode":    ("if isinstance(t, dict)\n                              and isinstance(t.get(\"node\"), str)}:", "if isinstance(t, dict)}:"),
    "idx-rebuilt":    ("        idx = roster.idx\n        if idx is None:", "        idx = None\n        if idx is None:"),
    "idx-wrongnode":  ("        return idx.get(nid, ())", "        return idx.get(nid, ()) or next(iter(idx.values()), ())"),
    "walk-filtered":  ("    return [(pid, p) for pid, p in (roster.get(\"peers\") or {}).items() if isinstance(p, dict)]",
                       "    return [(pid, p) for pid, p in (roster.get(\"peers\") or {}).items() if isinstance(p, dict) and p.get(\"targets\")][:1]"),
    "routes-fleet":   ("        _peers_here = [q for _k, q in _peers_on(roster, nid)]", "        _peers_here = []"),
    "guard-nodigest": ("                if _ROSTER_GUARD:\n                    v.digest = _roster_digest(v)", "                pass"),
    "guard-noreply":  ("        if _ROSTER_GUARD:                                # the gates: did this request write the shared roster? (P2)\n"
                       "            _roster_guard_check()\n", ""),
    "reader-writes":  ("        u = users.get(p.get(\"user_id\")) or {}\n        # BLOCKED access",
                       "        u = users.setdefault(p.get(\"user_id\") or \"-\", {})\n        # BLOCKED access"),
    "state-load":     ("        _roster = roster_view(roster_path)[0]", "        _roster = roster_load(roster_path)"),
}


def key(i):
    return base64.b64encode(bytes([i % 256]) * 32).decode()


def load(src, name):
    m = types.ModuleType(name)
    m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


def pre_k2_src():
    r = subprocess.run(["git", "-C", ROOT, "show", PRE_K2 + ":swg-panel-server"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("roster_view_selftest: cannot read the pre-K2 panel (%s): %s" % (PRE_K2, r.stderr.strip()[:200]))
    return r.stdout


def rand_fleet(rnd):
    """A random roster, node records and snapshots: users (blocked, expired, in groups), devices on 0-4 nodes of every kind
    (two interfaces on one node, roles, private, router, networks with shares, keyless passwords), unique torrent ports, every
    access level, enforcing nodes and not, csqtt App routing exceptions."""
    nodes = ["n%d" % i for i in range(1, rnd.randint(1, 4) + 1)]
    users = {}
    for i in range(rnd.randint(0, 10)):
        u = {"id": "u%02d" % i, "name": "U%d" % i}
        r = rnd.random()
        if r < 0.12:
            u["disabled"] = True
        elif r < 0.22:
            u["expiry"] = NOW - 60
        elif r < 0.30:
            u["expiry"] = NOW + 600
        users[u["id"]] = u
    uids = list(users)
    groups = {"g%d" % g: {"name": "G%d" % g, "users": sorted(rnd.sample(uids, rnd.randint(0, min(4, len(uids)))))}
              for g in range(rnd.randint(0, 3))}
    ports, peers = iter(rnd.sample(range(20000, 20500), 200)), {}
    for i in range(rnd.randint(0, 25)):
        tg = []
        for n in rnd.sample(nodes, rnd.randint(0, len(nodes))):
            kind = rnd.choice(("wg", "wg", "awg", "csqtt", "wdtt"))
            if kind in ("wg", "awg"):
                tg.append({"node": n, "iface": kind + "0", "ip": "10.%d.0.%d" % (nodes.index(n) + 1, i + 2), "type": kind})
                if rnd.random() < 0.15:
                    tg.append({"node": n, "iface": "wg1", "ip": "10.%d.1.%d" % (nodes.index(n) + 1, i + 2), "type": "wg"})
                if rnd.random() < 0.2:
                    tg[-1]["primary"] = rnd.choice(("primary", "backup"))
            else:
                tg.append({"node": n, "iface": "csqtt1" if kind == "csqtt" else "wdtt0", "ip": "", "type": kind})
        p = {"id": "p%03d" % i, "user_id": rnd.choice(uids + [None, "ghost"]), "title": "t%d" % i, "pubkey": "", "psk": "",
             "targets": tg, "created_at": rnd.randint(0, 50), "modified_at": 0}
        if any(t["type"] in ("wg", "awg") for t in tg):
            p["pubkey"], p["psk"] = key(i), key(100 + i)
            if rnd.random() < 0.8:
                p["p2p_port"] = next(ports)
        if any(t["type"] == "csqtt" for t in tg):
            p["csqtt_password"] = "c%03d" % i
        if any(t["type"] == "wdtt" for t in tg):
            p["wdtt_password"] = "w%03d" % i
        for k, v, pr in (("disabled", True, 0.1), ("expiry", rnd.choice((NOW - 60, NOW + 600)), 0.08), ("private", True, 0.15),
                         ("router", True, 0.08)):
            if rnd.random() < pr:
                p[k] = v
        if rnd.random() < 0.25:
            p["routes"] = ["192.168.%d.0/24" % rnd.randint(0, 6)]       # providers overlap on purpose
            if rnd.random() < 0.5:
                p["share"] = {"users": {u: rnd.choice((0, NOW - 5, NOW + 500)) for u in rnd.sample(uids, min(len(uids), 2))},
                              "groups": {g: 0 for g in list(groups)[:1]}}
        peers[p["id"]] = p
    rec, snaps = {}, {}
    for n in nodes:
        lv = [rnd.choice((None, "everyone", "user", "none")) for _ in range(3)]
        exc = [{"who": {"users": uids[:1], "groups": list(groups)[:1]}, "app_routing": {"mode": "bypass", "apps": ["a"]}}]
        rec[n] = {"id": n, "name": n, "ifaces": {i: ({"reach": l} if l else {}) for i, l in zip(("wg0", "awg0", "wg1"), lv)},
                  "csqtt": {"csqtt1": dict({"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "line": "2.5"},
                                           **({"app_routing_except": exc} if rnd.random() < 0.4 else {}))},
                  "wdtt": {"wdtt0": {"listen": "0.0.0.0:56000", "wg_port": 56001, "wg_addr": "10.66.73.1/24", "fork": "amurcanov"}}}
        here = [q for q in peers.values() if any(t["node"] == n for t in q["targets"])]
        snaps[n] = {"interfaces": {i: {"peers": [{"public_key": q["pubkey"]} for q in here if q["pubkey"] and rnd.random() < 0.7]}
                                   for i in ("wg0", "awg0")},
                    "csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.5.3", "line": "2.5",
                               "passwords": {q["csqtt_password"]: {"ip": "10.66.67.%d" % (k + 2)}
                                             for k, q in enumerate(here) if q.get("csqtt_password")}}],
                    "wdtt": [{"iface": "wdtt0", "fork": "amurcanov", "version": "1.2.4-3",
                              "passwords": {q["wdtt_password"]: {"ip": "10.66.73.%d" % (k + 2)}
                                            for k, q in enumerate(here) if q.get("wdtt_password")}}],
                    "smartroute": {"src": 1}}
        if rnd.random() < 0.8:
            snaps[n]["net_deps"] = {"panel": "127.0.0.1", "resolvers": [], "resolvers_known": True, "share": 1, "carried": 1,
                                    "reach": 2}
    return {"version": 1, "users": users, "peers": peers, "groups": groups}, rec, snaps


def per_node(P, r, rec, nid, snap):
    """Every function the index feeds, as one node's sync calls them."""
    carry = P.node_networks(r, nid, snap)
    promo = P.dev_reach_promotes(r, rec[nid], nid, snap)
    return {"desired": P.desired_for_node(r, nid, snap), "cut_off": P.cut_off_for_node(r, nid, snap),
            "who_here": P._who_here(r, nid, snap), "networks": carry, "promotes": sorted(promo),
            "dev_reach": P.dev_reach_for_node(r, rec[nid], nid, snap, carry["carry"], promo),
            "net_share": P.net_share_for_node(r, nid, carry["carry"], snap),
            "wdtt": P._wdtt_reply(r, rec, nid, "fb"), "csqtt": P._csqtt_reply(r, rec, nid, "fb", snap),
            "fwd_direct": P.p2p_fwd_for_node(None, r, nid, ("direct", ("10.1.1.0/24",))),
            "fwd_iface": P.p2p_fwd_for_node(None, r, nid, ("iface", ("10.1.0.0/24", "10.2.0.0/24")))}


class _Hdr:
    headers = {"Authorization": "Bearer t"}


def sync_in(P, d, nid, snap):
    """One sync through the real handler, in process: (code, reply as canonical JSON)."""
    s = json.loads(json.dumps(snap))
    P._snap_sanitise(s, nid)
    d["node_snaps"][nid] = s
    d["node_seen"][nid] = NOW
    nodes = P.nodes_load(d["nodes_path"])
    with P._api_lock:
        code, obj = P.Handler._node_sync_apply(_Hdr(), nid, nodes.get(nid), nodes, s, None)
    return code, json.dumps(obj, sort_keys=True)


def deps_for(P, root, roster, rec):
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "stats"))
    json.dump(rec, open(os.path.join(root, "nodes.json"), "w"))
    json.dump(roster, open(os.path.join(root, "users.json"), "w"))
    d = {"nodes_path": os.path.join(root, "nodes.json"), "roster_path": os.path.join(root, "users.json"),
         "stats_dir": os.path.join(root, "stats"), "fleet": {}, "panel_settings": {}, "node_snaps": {}, "node_seen": {}}
    P.Handler.deps = d
    return d


def run_checks(src, old_src, which="all", rounds=200):
    fails = []

    class Caught(Exception):
        pass

    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
            if which != "all":
                raise Caught()
    tmp = tempfile.mkdtemp(prefix="roster-view-")
    real_time, real_exit = time.time, os._exit
    try:
        env = os.environ.pop("SWG_ROSTER_GUARD", None)   # (the gate runner sets it for every gate: P is the panel without it)
        try:
            P = load(src, "swgpanel_rv")
        finally:
            if env is not None:
                os.environ["SWG_ROSTER_GUARD"] = env
        path = os.path.join(tmp, "users.json")
        R0 = {"version": 1, "users": {"u1": {"id": "u1", "name": "A"}},
              "peers": {"p1": {"id": "p1", "user_id": "u1", "pubkey": key(1), "psk": key(2),
                               "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.2", "type": "wg"}]},
                        "p2": {"id": "p2", "user_id": None, "pubkey": key(3), "psk": key(4),
                               "targets": [{"node": "n2", "iface": "wg0", "ip": "10.9.0.2", "type": "wg"},
                                           {"node": ["hand", "edit"], "iface": "wg0", "ip": "10.9.0.3"},
                                           {"node": "n1", "iface": "csqtt1", "ip": "", "type": "csqtt"}]},
                        "p3": "not a peer"}}
        json.dump(R0, open(path, "w"))

        print("[1] roster_view: one object until the file changes")
        v1, m1 = P.roster_view(path)
        v2, m2 = P.roster_view(path)
        ok(v1 is v2 and m1 == m2 and m1 is not None and v1["peers"]["p1"]["user_id"] == "u1", "[1] the same object twice")
        cp = P.roster_load(path)
        cp["users"]["u2"] = {"id": "u2", "name": "B"}
        P.roster_save(path, cp)
        v3, _m3 = P.roster_view(path)
        ok(v3 is not v1 and "u2" in v3["users"] and "u2" not in v1["users"], "[1] a save gives a new view; the old one is as it was")
        nxt = json.loads(json.dumps(v3)); nxt["users"]["u3"] = {"id": "u3", "name": "C"}
        json.dump(nxt, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)
        v4, _m4 = P.roster_view(path)
        ok("u3" in v4["users"], "[1] an outside writer's atomic replace gives a new view")
        nxt["users"]["u4"] = {"id": "u4", "name": "D"}
        with open(path, "w") as f:                       # in place: the same inode, a new size and mtime
            json.dump(nxt, f)
        v5, _m5 = P.roster_view(path)
        ok("u4" in v5["users"], "[1] an in-place rewrite gives a new view")
        gone = os.path.join(tmp, "absent.json")
        g1, gm = P.roster_view(gone)
        g2, _gm = P.roster_view(gone)
        ok(gm is None and g1 is not g2 and g1["peers"] == {} and P._ROSTER_VIEW[0][0] == path,
           "[1] no file: an empty roster, read each time and never kept")

        print("[2] the mark is taken before the read")
        json.dump(R0, open(path, "w"))
        real_load, raced = P.roster_load, []

        def racing_load(p_):
            r = real_load(p_)
            if not raced:                                # a save lands right after this read
                raced.append(1)
                w = real_load(p_); w["users"]["late"] = {"id": "late", "name": "L"}
                P.roster_save(p_, w)
            return r
        P.roster_load = racing_load
        try:
            P.roster_view(path)
        finally:
            P.roster_load = real_load
        ok("late" in P.roster_view(path)[0]["users"], "[2] a save landing during the read is read on the next call, not kept stale")

        print("[3] writers never write the view")
        v, _m = P.roster_view(path)
        for what, fn in (("peer_set", lambda: P.peer_set(v, "px", {"targets": []}, NOW)),
                         ("roster_save", lambda: P.roster_save(path, v))):
            try:
                fn(); got = "wrote"
            except RuntimeError:
                got = "refused"
            ok(got == "refused", "[3] %s refuses the view (%s)" % (what, got))
        own = P.roster_own(path, v)
        plain = {"peers": {}}
        ok(type(own) is dict and own == v and own is not v and P.roster_own(path, plain) is plain,
           "[3] roster_own: a fresh plain copy of the view; any other roster as it is")
        rec3 = {"n1": {"id": "n1", "name": "n1", "ifaces": {"wg0": {}}}}
        d = deps_for(P, os.path.join(tmp, "s3"), json.loads(json.dumps(R0)), rec3)
        before = json.dumps(P.roster_view(d["roster_path"])[0], sort_keys=True)
        seen = P.roster_view(d["roster_path"])[0]
        snap3 = {"interfaces": {"wg0": {"peers": []}},
                 "csqtt": [{"iface": "csqtt9", "fork": "csqtt", "version": "2.5.3", "line": "2.5", "listen": "0.0.0.0:46009",
                            "tun_addr": "10.66.69.1/24", "max_passwords": "", "params": "",
                            "passwords": {"imp1": {"comment": "imported"}}}]}
        try:
            code, _rep = sync_in(P, d, "n1", snap3)
        except Exception as e:
            code = "raised %s: %s" % (type(e).__name__, str(e)[:120])
        after = P.roster_view(d["roster_path"])[0]
        ok(code == 200 and any(q.get("csqtt_password") == "imp1" for q in after["peers"].values() if isinstance(q, dict))
           and json.dumps(seen, sort_keys=True) == before,
           "[3] a sync that imports (T-18) writes users.json — the import is in the next view, the view it read is unchanged (%s)" % code)

        clean = json.loads(json.dumps(R0)); clean["peers"]["p2"]["targets"].pop(1); clean["peers"].pop("p3")
        d = deps_for(P, os.path.join(tmp, "s3b"), clean, rec3)    # (a hand-edited list node breaks /api/state's own
        P.roster_view(d["roster_path"])                           # ghost walk, as before K2 — not this check's subject)
        real_load, loads = P.roster_load, []
        P.roster_load = lambda p_: (loads.append(p_), real_load(p_))[1]
        try:
            sync_in(P, d, "n1", {"interfaces": {"wg0": {"peers": []}}})
            P.api("GET", "/api/state", {}, {}, d)
        finally:
            P.roster_load = real_load
        ok(loads == [], "[3] a steady sync and an /api/state build parse users.json no more — the view is warm (%d)" % len(loads))

        print("[4] _peers_on: the per-node index")
        json.dump(R0, open(path, "w"))
        v, _m = P.roster_view(path)
        a1, a2 = P._peers_on(v, "n1"), P._peers_on(v, "n1")
        ok(isinstance(a1, tuple) and [k for k, _q in a1] == ["p1", "p2"] and a1 is a2,
           "[4] from the view: the node's peers in roster order, once each (p2 has two targets there), a tuple, built once (%s)"
           % [k for k, _q in a1])
        ok([k for k, _q in P._peers_on(v, "n2")] == ["p2"] and P._peers_on(v, "n9") == (),
           "[4] another node's own; an unknown node none")
        ok(not any(isinstance(n, list) for n in (v.idx or {})) and len(v.idx or {}) == 2,
           "[4] a hand-edited list for a node names no node (and does not break the index) (%s)" % sorted(map(str, v.idx or {})))
        ok([k for k, _q in P._peers_on(json.loads(json.dumps(v)), "n9")] == ["p1", "p2"],
           "[4] any other roster: every dict peer, as the walk it replaced")
        cp = P.roster_load(path); cp["peers"]["p4"] = {"id": "p4", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.4"}]}
        P.roster_save(path, cp)
        ok([k for k, _q in P._peers_on(P.roster_view(path)[0], "n1")] == ["p1", "p2", "p4"], "[4] a save: a new index with it")

        print("[5] SWG_ROSTER_GUARD")
        env = os.environ.get("SWG_ROSTER_GUARD")
        os.environ["SWG_ROSTER_GUARD"] = "1"
        try:
            G = load(src, "swgpanel_rvg")
        finally:
            if env is None:
                os.environ.pop("SWG_ROSTER_GUARD", None)
            else:
                os.environ["SWG_ROSTER_GUARD"] = env
        ok(G._ROSTER_GUARD is True and P._ROSTER_GUARD is False, "[5] on with the variable, off without")
        ok(src.count("            _roster_guard_check()\n") == 1
           and "        if _ROSTER_GUARD:                                # the gates" in src[src.index("    def _send_bytes("):],
           "[5] every JSON reply checks (_send_bytes)")
        ended = []
        os._exit = lambda c: (ended.append(c), (_ for _ in ()).throw(SystemExit(c)))
        rnd = random.Random(5)
        roster5, rec5, snaps5 = rand_fleet(rnd)
        while not roster5["peers"]:
            roster5, rec5, snaps5 = rand_fleet(rnd)
        d = deps_for(G, os.path.join(tmp, "s5"), roster5, rec5)
        G.roster_view(d["roster_path"])
        ok(G._ROSTER_VIEW[0][2].digest is not None, "[5] the view is hashed when it is published")
        time.time = lambda: float(NOW)
        try:
            for nid in rec5:
                sync_in(G, d, nid, snaps5[nid])
            G.api("GET", "/api/state", {}, {}, d)
            G._roster_guard_check()
            r5 = "kept"
        except SystemExit:
            r5 = "ended"
        except Exception as e:
            r5 = "raised %s: %s" % (type(e).__name__, str(e)[:100])
        finally:
            time.time = real_time
        ok(r5 == "kept" and not ended, "[5] syncs of every node and /api/state leave the view as it was (%s)" % r5)
        G._ROSTER_VIEW[0][2]["peers"].setdefault("x", {})   # a reader that writes
        try:
            G._roster_guard_check(); r5 = "missed"
        except SystemExit:
            r5 = "ended"
        ok(r5 == "ended" and ended == [70], "[5] a reader that writes the view ends the panel (%s %s)" % (r5, ended))
        os._exit = real_exit

        print("[6] the differential: on the view == the pre-K2 walk == this panel's walk")
        O = load(old_src, "swgpanel_prek2")
        time.time = lambda: float(NOW)
        rnd, bad, n = random.Random(1812), [], 0
        try:
            for i in range(rounds):
                roster, rec, snaps = rand_fleet(rnd)
                fp = os.path.join(tmp, "d%d.json" % (i % 2))
                json.dump(roster, open(fp, "w"))
                view = P.roster_view(fp)[0]
                for nid in rec:
                    n += 1
                    want = json.dumps(per_node(O, json.loads(json.dumps(roster)), rec, nid, snaps[nid]), sort_keys=True)
                    got = json.dumps(per_node(P, view, rec, nid, snaps[nid]), sort_keys=True)
                    walk = json.dumps(per_node(P, json.loads(json.dumps(roster)), rec, nid, snaps[nid]), sort_keys=True)
                    if not (want == got == walk):
                        bad.append((i, nid, [k for k in json.loads(want) if json.loads(want)[k] != json.loads(got)[k]]))
                    if bad and which != "all":
                        break
                if bad and which != "all":
                    break
        finally:
            time.time = real_time
        ok(not bad and n > 3 * rounds // 2, "[6] %d node syncs over %d random fleets: every output identical (%s)" % (n, rounds, bad[:3]))

        print("[7] whole sync replies: the pre-K2 handler == this one")
        time.time = lambda: float(NOW)
        rnd, diff, n = random.Random(7), [], 0
        try:
            for i in range(6):
                roster, rec, snaps = rand_fleet(rnd)
                prov = next((q for q in roster["peers"].values() if q["pubkey"] and any(snaps[t["node"]].get("net_deps")
                             for t in q["targets"])), None)
                if prov:                                     # a restricted network on an enforcing node: net_share and carry
                    prov.update(routes=["192.168.77.0/24"], share={"users": {}})
                if i == 5:                                   # an import: the T-18 mirror takes a server's users
                    snaps[next(iter(rec))]["csqtt"].append(
                        {"iface": "csqtt9", "fork": "csqtt", "version": "2.5.3", "line": "2.5", "listen": "0.0.0.0:46009",
                         "tun_addr": "10.66.69.1/24", "max_passwords": "", "params": "", "passwords": {"imp%d" % k: {} for k in range(3)}})
                do, dn = deps_for(O, os.path.join(tmp, "o%d" % i), roster, rec), deps_for(P, os.path.join(tmp, "n%d" % i), roster, rec)
                for nid in rec:                              # (the mesh self-heal draws each new link's AWG params from
                    n += 1                                   # `random`: the same seed before each, the same draws)
                    random.seed(n); O.Handler.deps, ro = do, sync_in(O, do, nid, snaps[nid])
                    random.seed(n); P.Handler.deps, rn = dn, sync_in(P, dn, nid, snaps[nid])
                    if ro != rn:
                        diff.append((i, nid, ro[0], rn[0]))
        finally:
            time.time = real_time
        ok(not diff and n >= 6, "[7] %d sync replies over 6 fleets (the last imports): byte for byte (%s)" % (n, diff[:3]))
    except Caught:
        pass
    finally:
        time.time, os._exit = real_time, real_exit
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def main():
    old = pre_k2_src()
    if "--perturb" in sys.argv:
        missed = []
        only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
        for name, (a, b) in PLANTS.items():
            if only and name not in only:
                continue
            if PSRC.count(a) != 1:
                print("PLANT %-15s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(PSRC.replace(a, b), old, which=name, rounds=60)
            print("PLANT %-15s %s" % (name, ("RED  (" + f[0][:90] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC, old)
    print("roster_view_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
