#!/usr/bin/env python3
"""Self-test: a turn server takes no more users than it has addresses for, and a full one is said (docs/SCALE-PLAN.md K6).

  [1] turn_cap per family, from each fork's source: WDTT amurcanov / xxcipherx / ildarmaga / WDTT-Plus 249 whatever the
      subnet; qWDTT every host of its subnet but its own (/24 253, /23 509, RAW on → at most 253); csqtt 2.1 249, 2.5 248;
      an unknown fork, line or a bad subnet → None (nothing refused)
  [2] a real panel: a csqtt 2.5 instance holding 247 users (blocked and expired among them) takes the 248th, then refuses
      the next through create AND add-target (409 turn_full, naming the server; users.json unchanged), a target beside it
      in the same create refused with it; a WDTT instance on a fork the table does not know is never refused
  [3] /api/state: the node view's `turn_cap` per instance with a known pool; no key on a node without one
  [4] _node_issues: a full pool with someone waiting → the line; full and nobody waiting, or waiting below the pool → none;
      2.1 and WDTT read through their devices; the cap is the RUNNING line's (the snapshot's), not the stored one; a
      malformed report raises nothing
  [2] also: the API-only doors /api/csqtt-peer/create and /api/wdtt-peer/create refuse as well (card scale-k6 F1); a
      csqtt server's pool is its RUNNING line's (the node's report) — a switch to 2.5 pending or failed on a 2.1 server
      keeps 249 (F2)
  [4] also: the cap from the server's own row (a qWDTT the panel has no record of is 253, not WDTT's 249 — F3); a blocked
      or expired user's password without an address is not "waiting" (F4)
  [5] the VK pool's load (T4): a blocked user, an expired one, a user whose devices are all plain WireGuard or all cut off
      → not counted; a user with no device yet, a csqtt one, a WireGuard one behind a turn-proxy, one with a blocked device
      beside a live turn one → counted; the cascade moves its counts only for counted users (F5)
  card scale-k6b: [4] WDTT under -fixed-config (device_id always "") — a full pool with a live password holding no address
      is said (F1); a node row whose iface is not a string is no report (F31); [2] a csqtt pool is the smaller of the
      record's line and the running one (F9); [5] a dead link's uncounted holders spread over the pool by their own count,
      the counted ones pick by the load alone (F3); the gate's own requests skip any proxy (F15)
  [6] (scale-k6b F30) a save that makes a running pool smaller than its users is refused (409 turn_shrink, nothing written):
      /api/wdtt/set moving an unknown fork's 301 users to amurcanov's 249; a title edit of a full server, a pool that grows
      and a pool that still holds everyone go through; csqtt 2.1 → 2.5 with 249 users refused, with 248 not; a server already
      over its pool from before K6 is never refused an edit that does not shrink it

Run: python3 tests/turn_cap_selftest.py
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PSRC = open(PANEL, encoding="utf-8").read()

PLANTS = {   # name: (old text, planted text) — all in the panel
    "gt":         ("    if used < cap:\n        return None\n", "    if used <= cap:\n        return None\n"),
    "blocked":    ("    return sum(1 for _pid, p in _peers_on(roster, nid)\n               if any(",
                   "    return sum(1 for _pid, p in _peers_on(roster, nid)\n               if not p.get(\"disabled\") and any("),
    "addtarget":  ("        full = turn_full(nodes, snaps, roster, target)\n        if full:\n", "        full = None\n        if full:\n"),
    "issuebelow": ("            if _wait and _use >= _cap:\n", "            if _wait:\n"),
    "storedline": ("**{k: e[k] for k in (\"fork\", \"wg_addr\", \"raw_port\", \"line\")", "**{k: e[k] for k in (\"fork\", \"wg_addr\", \"raw_port\")"),
    "recordfork": ("**{k: e[k] for k in (\"fork\", \"wg_addr\", \"raw_port\", \"line\")", "**{k: e[k] for k in (\"line\",)"),
    "waitcut":    ("            _wait = sum(1 for x in _live if not x.get(\"ip\"))\n", "            _wait = sum(1 for x in _pw if not x.get(\"ip\"))\n"),
    "waitdevid":  ("            _wait = sum(1 for x in _live if not x.get(\"ip\"))\n", "            _wait = sum(1 for x in _live if x.get(\"device_id\") and not x.get(\"ip\"))\n"),
    "recordline": ("turn_cap(kind, dict(rec, line=_csqtt_run_line(snap, iface, rec)))) if c is not None]", "turn_cap(kind, rec)) if c is not None]"),
    "runonly":    ("(turn_cap(kind, rec), turn_cap(kind, dict(rec, line=", "(None, turn_cap(kind, dict(rec, line="),
    "ifacehash":  ("            if not isinstance(e, dict) or not isinstance(e.get(\"iface\"), str):\n                continue\n            _ti = _recs.get(e[\"iface\"])",
                   "            if not isinstance(e, dict):\n                continue\n            _ti = _recs.get(e.get(\"iface\"))"),
    "csqdoor":    ("            full = turn_full(nodes, snaps, roster, t)\n            if full:\n                return 409, {\"ok\": False, **full, \"code\": \"turn_full\"}\n        fields = {\"user_id\": uid or None, \"title\": title, \"pubkey\": \"\", \"psk\": \"\",\n                  \"targets\": tgts, \"csqtt_password\"",
                   "            full = None\n            if full:\n                return 409, {\"ok\": False, **full, \"code\": \"turn_full\"}\n        fields = {\"user_id\": uid or None, \"title\": title, \"pubkey\": \"\", \"psk\": \"\",\n                  \"targets\": tgts, \"csqtt_password\""),
    "wdttdoor":   ("            full = turn_full(nodes, snaps, roster, t)\n            if full:\n                return 409, {\"ok\": False, **full, \"code\": \"turn_full\"}\n        fields = {\"user_id\": uid or None, \"title\": title, \"pubkey\": \"\", \"psk\": \"\",\n                  \"targets\": tgts, \"wdtt_password\"",
                   "            full = None\n            if full:\n                return 409, {\"ok\": False, **full, \"code\": \"turn_full\"}\n        fields = {\"user_id\": uid or None, \"title\": title, \"pubkey\": \"\", \"psk\": \"\",\n                  \"targets\": tgts, \"wdtt_password\""),
    "cascadecount": ("else _vk_user_sync(u, ps, counts=spread, pool=pool))", "else _vk_user_sync(u, ps, counts=counts, pool=pool, also=spread))"),
    "nospread":   ("else _vk_user_sync(u, ps, counts=spread, pool=pool))", "else _vk_user_sync(u, ps, counts=dict(counts), pool=pool))"),
    "capkey":     ("**({\"turn_cap\": _tcap} if", "**({\"turn_caps\": _tcap} if"),
    "t4old":      ("        if not isinstance(u, dict) or (uid in has_dev and uid not in serves) or access_cut({}, u, nowv):\n",
                   "        if not isinstance(u, dict):\n"),
    "t4nodev":    ("(uid in has_dev and uid not in serves)", "(uid not in serves)"),
    "shrinkwdtt": ("        _shr = turn_shrink(nodes, snaps, roster_path, nid, iface, \"wdtt\", _existing, inst)\n", "        _shr = None\n"),
    "shrinkcsq":  ("        _shr = turn_shrink(nodes, snaps, roster_path, nid, iface, \"csqtt\", _cur, inst)\n",
                   "        _shr = None\n"),
    "shrinkeq":   ("    if nc is None or (oc is not None and nc >= oc):\n", "    if nc is None or (oc is not None and nc > oc):\n"),
    "shrinkzero": ("        n = max(net.num_addresses - 3, 0)", "        if net.num_addresses < 4:\n            return None\n        n = net.num_addresses - 3"),
    "shrinkle":   ("    if used <= nc:\n        return None\n", "    if used < nc:\n        return None\n"),
}

NOW = int(time.time())
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # a desktop proxy in the env must not see 127.0.0.1


def load(src):
    m = types.ModuleType("panel_t1")
    m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


def run_checks(src):
    fails = []

    def ok(cond, name, detail=""):
        print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
        if not cond:
            fails.append(name)

    P = load(src)

    print("[1] the pool per family")
    tc = P.turn_cap
    ok(all(tc("wdtt", {"fork": f, "wg_addr": "10.66.0.1/20"}) == 249 for f in ("amurcanov", "xxcipherx", "ildarmaga", "wdttplus"))
       and tc("wdtt", {}) == 249, "[1] WDTT forks: 249 whatever the subnet; no fork = amurcanov")
    ok(tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/24"}) == 253 and tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/23"}) == 509
       and tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/23", "raw_port": "56010"}) == 253,
       "[1] qWDTT: every host but its own (/24 253, /23 509), RAW on caps it at its /24's 253")
    ok(tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/30"}) == 1 and tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/31"}) == 0
       and tc("wdtt", {"fork": "qwdtt", "wg_addr": "10.66.70.1/32"}) == 0,
       "[1] qWDTT /30 gives 1; a /31 or /32 gives none — a known 0, not an unknown pool (scale-k6d F1)")
    ok(tc("csqtt", {}) == 249 and tc("csqtt", {"line": "2.1"}) == 249 and tc("csqtt", {"line": "2.5"}) == 248,
       "[1] csqtt 2.1 249, 2.5 248")
    ok(tc("wdtt", {"fork": "mystery"}) is None and tc("csqtt", {"line": "9.9"}) is None
       and tc("wdtt", {"fork": "qwdtt", "wg_addr": "junk"}) is None and tc("wdtt", {"fork": "qwdtt"}) is None
       and tc("wg", {}) is None and tc("csqtt", None) == 249,
       "[1] an unknown fork / line / a bad subnet → None")

    print("[2] [3] a real panel")
    tmp = tempfile.mkdtemp(prefix="turn-cap-")
    try:
        server = os.path.join(tmp, "swg-panel-server")
        open(server, "w", encoding="utf-8").write(src)
        state = os.path.join(tmp, "state"); os.makedirs(state); stats = os.path.join(tmp, "stats"); os.makedirs(stats)
        nodes_p, users_p = os.path.join(state, "nodes.json"), os.path.join(state, "users.json")
        json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {},
                          "csqtt": {"csqtt1": {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "line": "2.5"}},
                          "wdtt": {"wdtt1": {"listen": "0.0.0.0:56000", "wg_addr": "10.66.70.1/24", "fork": "amurcanov"},
                                   "wdtt2": {"listen": "0.0.0.0:58000", "wg_addr": "10.66.72.1/24", "fork": "ildarmaga"},
                                   "wdtt9": {"listen": "0.0.0.0:57000", "wg_addr": "10.66.71.1/24", "fork": "mystery"}}},
                   "n2": {"id": "n2", "name": "node-b", "ifaces": {}}}, open(nodes_p, "w"))
        users, peers = {}, {}
        for i in range(247):                     # csqtt1 holds 247: blocked users, blocked devices and expired ones among them
            uid, pid = "u%03d" % i, "p%03d" % i
            users[uid] = {"id": uid, "name": "user%d" % i, **({"disabled": True} if i % 10 == 1 else {}),
                          **({"expiry": NOW - 3600} if i % 10 == 2 else {})}
            peers[pid] = {"id": pid, "user_id": uid, "title": "", "pubkey": "", "psk": "", "csqtt_password": "pw%05dxxxxxxxxxx" % i,
                          "targets": [{"node": "n1", "iface": "csqtt1", "ip": "", "type": "csqtt"}],
                          **({"disabled": True} if i % 10 == 3 else {}), **({"expiry": NOW - 60} if i % 10 == 4 else {})}
        for i in range(300):                     # an unknown fork's server, far past any pool
            pid = "q%03d" % i
            peers[pid] = {"id": pid, "user_id": None, "title": "", "pubkey": "", "psk": "", "wdtt_password": "wq%05dxxxxxxxxxx" % i,
                          "targets": [{"node": "n1", "iface": "wdtt9", "ip": "", "type": "wdtt"}]}
        for i in range(249):                     # a WDTT server holding its pool
            pid = "f%03d" % i
            peers[pid] = {"id": pid, "user_id": None, "title": "", "pubkey": "", "psk": "", "wdtt_password": "wf%05dxxxxxxxxxx" % i,
                          "targets": [{"node": "n1", "iface": "wdtt2", "ip": "", "type": "wdtt"}]}
        peers["w1"] = {"id": "w1", "user_id": None, "title": "", "pubkey": "", "psk": "", "wdtt_password": "ww00001xxxxxxxxxx",
                       "targets": [{"node": "n1", "iface": "wdtt1", "ip": "", "type": "wdtt"}]}
        json.dump({"version": 1, "users": users, "peers": peers}, open(users_p, "w"))
        fleet = os.path.join(tmp, "fleet.json")
        json.dump({"nodes_path": nodes_p, "roster_path": users_p, "stats_dir": stats}, open(fleet, "w"))
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        log = open(os.path.join(tmp, "panel.log"), "w+")
        env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")}
        proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                                env={**env, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                     "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                     "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

        def req(path, data=None):
            r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                                       headers={"Content-Type": "application/json"})
            try:
                with NOPROXY.open(r, timeout=30) as resp:
                    return resp.status, json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        try:
            for _ in range(200):
                try:
                    if req("/api/state")[0] == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            else:
                ok(False, "[2] the panel came up", open(log.name).read()[-600:])
                return fails
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "csqtt1"}]})
            ok(code == 200, "[2] the 248th user on a csqtt 2.5 server is taken", (code, r))
            before = open(users_p, "rb").read()
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "csqtt1"}]})
            ok(code == 409 and r.get("code") == "turn_full" and "csqtt1 on node-a is full — users: 248 of 248" in (r.get("error") or "")
               and r.get("error_key", "").startswith("{v1} on {v2} is full"),
               "[2] the 249th is refused, naming the server and the count", (code, r))
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt1"}, {"node": "n1", "iface": "csqtt1"}]})
            ok(code == 409 and r.get("code") == "turn_full", "[2] a create with a free server beside the full one is refused whole", (code, r))
            code, r = req("/api/peers/add-target", {"peer_id": "w1", "target": {"node": "n1", "iface": "csqtt1"}})
            ok(code == 409 and r.get("code") == "turn_full", "[2] add-target onto the full server is refused", (code, r))
            code, r = req("/api/csqtt-peer/create", {"node": "n1", "iface": "csqtt1"})
            ok(code == 409 and r.get("code") == "turn_full", "[2] the API-only /api/csqtt-peer/create refuses too (F1)", (code, r))
            code, r = req("/api/wdtt-peer/create", {"node": "n1", "iface": "wdtt2"})
            ok(code == 409 and r.get("code") == "turn_full", "[2] the API-only /api/wdtt-peer/create refuses too (F1)", (code, r))
            ok(open(users_p, "rb").read() == before, "[2] nothing written by a refusal")
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt9"}]})
            ok(code == 200, "[2] a server on a fork the table does not know is never refused (301 there)", (code, r))
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt1"}]})
            ok(code == 200, "[2] a server with room takes one", (code, r))

            print("[6] a save that shrinks a pool")
            nb, ub = open(nodes_p, "rb").read(), open(users_p, "rb").read()
            code, r = req("/api/wdtt/set", {"node": "n1", "iface": "wdtt9", "fork": "amurcanov"})
            ok(code == 409 and r.get("code") == "turn_shrink" and "wdtt9 on node-a is too small — users: 301, addresses: 249. Move 52 of them" in (r.get("error") or ""),
               "[6] /api/wdtt/set: an unknown fork's 301 users onto amurcanov's 249 → refused, naming how many to move", (code, r))
            ok(open(nodes_p, "rb").read() == nb and open(users_p, "rb").read() == ub, "[6] nothing written by the refusal")
            code, r = req("/api/wdtt/set", {"node": "n1", "iface": "wdtt2", "title": "full one"})
            ok(code == 200, "[6] a title edit of a FULL server goes through (its pool does not shrink)", (code, r))

            code, st = req("/api/state")
            nv = {n.get("id"): n for n in ((st.get("data") or {}).get("nodes") or [])}
            ok((nv.get("n1") or {}).get("turn_cap") == {"csqtt1": 248, "wdtt1": 249, "wdtt2": 249},
               "[3] the node view carries each known pool", (nv.get("n1") or {}).get("turn_cap"))
            ok("n2" in nv and "turn_cap" not in nv["n2"], "[3] no key on a node without a turn server")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    nd = {"n1": {"name": "node-a", "csqtt": {"csqtt1": {"line": "2.5"}}}}
    ro = {"peers": {"p%d" % i: {"targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]} for i in range(248)}}
    tq = {"node": "n1", "iface": "csqtt1", "type": "csqtt"}
    nd21 = {"n1": {"name": "node-a", "csqtt": {"csqtt1": {"line": "2.1"}}}}
    run = lambda ln: {"n1": {"csqtt": [{"iface": "csqtt1", "line": ln}]}}
    ok(P.turn_full(nd, {}, ro, tq) is not None and P.turn_full(nd21, {}, ro, tq) is None and P.turn_full(nd21, run("2.1"), ro, tq) is None,
       "[2] record 2.5 with no report → full at 248; record 2.1 running 2.1 → room at 248")
    ok(P.turn_full(nd21, run("2.5"), ro, tq) is not None,
       "[2] the RUNNING line counts: record 2.1, the node runs 2.5 (a switch back pending) → full at 248 (F2)")
    ok(P.turn_full(nd, run("2.1"), ro, tq) is not None,
       "[2] …and the record's: record 2.5, the node still runs 2.1 (the switch pending) → full at 248, so the user admitted now has an address once it lands (F9)")

    print("[6] turn_shrink in process")
    tmp6 = tempfile.mkdtemp(prefix="turn-shrink-")
    try:
        rp = os.path.join(tmp6, "users.json")
        def shrink(n_users, old, new, kind="csqtt", snaps=None):
            json.dump({"version": 1, "users": {}, "peers": {"p%d" % i: {"targets": [{"node": "n1", "iface": "x1", "type": kind}]}
                                                            for i in range(n_users)}}, open(rp, "w"))
            return P.turn_shrink({"n1": {"name": "node-a"}}, snaps or {}, rp, "n1", "x1", kind, old, new)
        ok(shrink(249, {"line": "2.1"}, {"line": "2.5"}) is not None and shrink(248, {"line": "2.1"}, {"line": "2.5"}) is None,
           "[6] csqtt 2.1 → 2.5: 249 users refused, 248 go through")
        ok(shrink(249, {"line": "2.5"}, {"line": "2.5", "title": "t"}) is None,
           "[6] a server already over its pool (249 on a 2.5, from before K6): an edit that does not shrink it is not refused")
        ok(shrink(300, {"line": "2.5"}, {"line": "2.1"}) is None and shrink(300, {"listen": "0.0.0.0:46000"}, {"line": "2.5"}) is not None
           and shrink(10, {"listen": "0.0.0.0:46000"}, {"line": "2.5"}) is None,
           "[6] a pool that grows is not refused; a new pool under the users is, one over them is not")
        ok(shrink(260, {"fork": "qwdtt", "wg_addr": "10.66.70.1/23"}, {"fork": "qwdtt", "wg_addr": "10.66.70.1/23", "raw_port": "56003"}, "wdtt") is not None
           and shrink(253, {"fork": "qwdtt", "wg_addr": "10.66.70.1/23"}, {"fork": "qwdtt", "wg_addr": "10.66.70.1/24"}, "wdtt") is None
           and shrink(254, {"fork": "qwdtt", "wg_addr": "10.66.70.1/23"}, {"fork": "qwdtt", "wg_addr": "10.66.70.1/24"}, "wdtt") is not None,
           "[6] qWDTT: RAW on over a /23 with 260 users refused; /23 → /24 refused past 253, not at it")
        ok(shrink(5, None, {"line": "2.5"}) is None, "[6] a new instance holds no one: never refused")
        ok(shrink(200, {"fork": "qwdtt", "wg_addr": "10.66.70.1/24"}, {"fork": "qwdtt", "wg_addr": "10.66.70.1/31"}, "wdtt") is not None,
           "[6] qWDTT /24 → /31 with 200 users: refused, as the /30 is (scale-k6d F1)")
        run21 = {"n1": {"csqtt": [{"iface": "x1", "line": "2.1"}]}}
        wide = {"n1": {"wdtt": [{"iface": "x1", "fork": "qwdtt", "wg_addr": "10.66.70.1/23", "raw_port": ""}]}}
        ok(shrink(249, {"line": "2.5"}, {"line": "2.5", "title": "t"}, "csqtt", run21) is None
           and shrink(260, {"fork": "qwdtt", "wg_addr": "10.66.70.1/24", "raw_port": "56003"},
                      {"fork": "qwdtt", "wg_addr": "10.66.70.1/24", "raw_port": "56003", "title": "t"}, "wdtt", wide) is None,
           "[6] a save that changes nothing about the pool is not refused, whatever the node still runs: a title during a "
           "pending 2.1 → 2.5 switch (249 users), a qWDTT record already narrower than its row (scale-k6d verify F5/F7)")
        # the csqtt door itself, in process: a node that can run 2.5, a 2.1 server holding 249
        np_ = os.path.join(tmp6, "nodes.json")
        json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {}, "csqtt": {"x1": {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24"}}}},
                  open(np_, "w"))
        shrink(249, None, None)                          # writes the roster: 249 peers on x1
        deps = {"fleet": {}, "nodes_path": np_, "roster_path": rp, "stats_dir": tmp6, "panel_settings": {},
                "node_snaps": {"n1": {"csqtt_lines": ["2.1", "2.5"], "csqtt": [{"iface": "x1", "line": "2.1"}]}}}
        nb = open(np_, "rb").read()
        try:
            code, r = P.api("POST", "/api/csqtt/set", {}, {"node": "n1", "iface": "x1", "line": "2.5"}, deps)
        except Exception as e:
            code, r = 0, {"error": repr(e)}
        ok(code == 409 and r.get("code") == "turn_shrink" and open(np_, "rb").read() == nb,
           "[6] /api/csqtt/set 2.1 → 2.5 on a server holding 249: refused, nothing written", (code, r))
    finally:
        shutil.rmtree(tmp6, ignore_errors=True)

    print("[4] the node's own report")

    def issues(c, snap):
        return [i.get("error_key") for i in P._node_issues(c, snap) if "addresses are in use" in (i.get("error_key") or "")]
    c25 = {"csqtt": {"csqtt1": {"line": "2.5"}}}
    full25 = {"pw%d" % i: {"ip": "10.66.67.%d" % (i + 3)} for i in range(248)}
    ok(issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(full25, x={"ip": ""}), "devices": {}}]})
       == ["{v1}: all {v3} addresses are in use — users who can't connect: {v2}"], "[4] 2.5: full, one waiting → the line")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": full25, "devices": {}}]}),
       "[4] 2.5: full, nobody waiting → nothing")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": {"a": {"ip": "10.66.67.3"}, "b": {"ip": ""}}}]}),
       "[4] 2.5: one waiting below the pool → nothing")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(list(full25.items())[:247], x={"ip": ""})}]}),
       "[4] 2.5: 248 passwords, one still without an address while one is free → nothing")
    ok(issues({"csqtt": {"csqtt1": {}}}, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(full25, x={"ip": ""})}]}),
       "[4] the RUNNING line decides (stored 2.1, the node runs 2.5)")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(
           full25, x={"ip": "", "is_deactivated": True}, y={"ip": "", "expires_at": NOW - 5})}]}),
       "[4] a blocked or expired user's password with no address is not waiting (F4)")
    devs = {"d%d" % i: {"ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    pw21 = {"p%d" % i: {"device_id": "d%d" % i, "ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    ok(issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
              {"wdtt": [{"iface": "wdtt1", "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}, y={"device_id": "", "ip": ""}), "devices": devs}]}),
       "[4] WDTT through its devices: 249 held, one bound and refused → the line")
    fdevs = {"pw:f%d" % i: {"ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    fpw = {"f%d" % i: {"device_id": "", "ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    ok(issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
              {"wdtt": [{"iface": "wdtt1", "passwords": dict(fpw, y={"device_id": "", "ip": ""}), "devices": fdevs}]}),
       "[4] WDTT under -fixed-config (device_id never set): 249 held, a live password with none → the line (F1)")
    ok(not issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
                  {"wdtt": [{"iface": "wdtt1", "passwords": dict(fpw, y={"device_id": "", "ip": "", "is_deactivated": True}), "devices": fdevs}]}),
       "[4] WDTT: a blocked password with none is not waiting")
    del fdevs["pw:f0"]; fpw["f0"]["ip"] = ""
    ok(not issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
                  {"wdtt": [{"iface": "wdtt1", "passwords": dict(fpw, y={"device_id": "", "ip": ""}), "devices": fdevs}]}),
       "[4] WDTT: below the pool (248 held), passwords not yet connected → nothing")
    ok(not issues({}, {"wdtt": [{"iface": "wdtt7", "fork": "qwdtt", "wg_addr": "10.66.70.1/24", "raw_port": "",
                                 "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}), "devices": devs}]})
       and issues({}, {"wdtt": [{"iface": "wdtt7", "fork": "amurcanov", "wg_addr": "10.66.70.1/24",
                                 "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}), "devices": devs}]}),
       "[4] the cap from the server's own row: a qWDTT /24 the panel has no record of has 4 left at 249 (F3)")
    ok(issues({"csqtt": {"csqtt1": {}}}, {"csqtt": [{"iface": "csqtt1", "line": "2.1", "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}), "devices": devs}]}),
       "[4] csqtt 2.1 through its devices")
    try:
        bad = [{"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": ["x"]}]}, {"csqtt": ["junk", {"iface": "csqtt1", "passwords": {"a": "s"}}]},
               {"wdtt": [{"iface": "wdtt1", "passwords": {"a": {"device_id": "d", "ip": ""}}, "devices": ["x"]}]},
               {"wdtt": [{"iface": ["wdtt1"], "passwords": {}}]}, {"csqtt": [{"iface": {"x": 1}, "line": "2.5", "passwords": {}}]}]
        for b in bad:
            issues({"csqtt": {"csqtt1": {}}, "wdtt": {"wdtt1": "junk"}}, b)
            issues({"csqtt": "junk"}, b)
        ok(True, "[4] a malformed report raises nothing (an iface that is a list or a dict too — F31)")
    except Exception as e:
        ok(False, "[4] a malformed report raises nothing", repr(e))

    print("[5] the VK pool's load")
    L = ["https://vk.ru/call/join/" + ch * 24 for ch in "ABCDEFGHIJ"]
    tg = lambda n, i, ty: {"node": n, "iface": i, "ip": "", "type": ty}
    roster = {"users": {
        "blocked": {"disabled": True, "vk_links": [L[0]]},
        "expired": {"expiry": NOW - 10, "vk_links": [L[1]]},
        "wgonly":  {"vk_links": [L[2]]},
        "allcut":  {"vk_links": [L[3]]},
        "nodev":   {"vk_links": [L[4]]},
        "csq":     {"vk_links": [L[5]]},
        "proxied": {"vk_links": [L[6]]},
        "mixed":   {"vk_links": [L[7]]}},
        "peers": {
        "a": {"user_id": "blocked", "targets": [tg("n1", "csqtt1", "csqtt")]},
        "b": {"user_id": "expired", "targets": [tg("n1", "csqtt1", "csqtt")]},
        "c": {"user_id": "wgonly", "targets": [tg("n1", "wg0", "wg")]},
        "d": {"user_id": "allcut", "disabled": True, "targets": [tg("n1", "csqtt1", "csqtt")]},
        "e": {"user_id": "csq", "targets": [tg("n1", "csqtt1", "csqtt")]},
        "f": {"user_id": "proxied", "targets": [tg("n1", "awg1", "awg")]},
        "g": {"user_id": "mixed", "disabled": True, "targets": [tg("n1", "wdtt1", "wdtt")]},
        "h": {"user_id": "mixed", "targets": [tg("n1", "wdtt1", "wdtt")]}}}
    for k, u in roster["users"].items():
        u["name"] = k
    snaps = {"n1": {"interfaces": {"wg0": {"meta": {"listen_port": 51820}}, "awg1": {"meta": {"listen_port": 51821}}},
                    "turn_proxies": [{"service": "tp1", "connect": "127.0.0.1:51821"}]}}
    got = P._vk_pool_counts(roster, snaps)
    ok(not any(got.get(L[i]) for i in (0, 1, 2, 3)), "[5] blocked, expired, plain-WireGuard-only, all-devices-cut users are not load", got)
    ok(all(got.get(L[i]) == 1 for i in (4, 5, 6, 7)),
       "[5] a user with no device yet, a csqtt one, a WireGuard one behind a turn-proxy, a blocked device beside a live turn one count", got)
    calls, real = [], P._vk_user_sync
    def spy(u, ps, counts=None, pool=None, also=None):
        calls.append((u.get("name"), id(counts), id(also) if also is not None else None))
        return real(u, ps, counts=counts, pool=pool, also=also)
    P._vk_user_sync = spy
    try:
        P._vk_pool_cascade(roster, {}, snaps)
    finally:
        P._vk_user_sync = real
    flag = {n: (c, a) for n, c, a in calls}
    load_id, spread_id = flag.get("csq", (0, 0))
    ok(spread_id and flag.get("nodev") == (load_id, spread_id) and flag.get("blocked") == (spread_id, None)
       and flag.get("wgonly") == (spread_id, None),
       "[5] the cascade: a counted user picks by the load and moves it and the spread; one not counted the spread alone (F5, F3)", calls)
    a, b = {"x": 3}, {"x": 3}
    real({"vk_links": [L[9]], "vk_pool": {"gone": L[9]}}, {"vk_pool": [{"id": "e1", "url": L[8]}]}, counts=a, also=b)
    ok(a == b == {"x": 3, L[8]: 1, L[9]: 0}, "[5] _vk_user_sync moves both counts it is given", (a, b))
    # a dead link's 6 blocked holders spread over the two live links, on top of the load: before F3 all six stacked on B
    A, B, E = L[0], L[1], L[2]
    ro3 = {"users": {}, "peers": {}}
    for i in range(2):
        ro3["users"]["c%d" % i] = {"name": "c%d" % i, "vk_links": [A], "vk_pool": {"a": A}}
        ro3["peers"]["pc%d" % i] = {"user_id": "c%d" % i, "targets": [tg("n1", "csqtt1", "csqtt")]}
    for i in range(6):
        ro3["users"]["b%d" % i] = {"name": "b%d" % i, "disabled": True, "vk_links": [E], "vk_pool": {"e": E}}
    ps3 = {"vk_pool": [{"id": "a", "url": A}, {"id": "b", "url": B}, {"id": "e", "url": E, "dead": True}]}
    P._vk_pool_cascade(ro3, ps3, {})
    onb = sum(1 for i in range(6) if ro3["users"]["b%d" % i]["vk_links"] == [B])
    ok(onb == 4, "[5] a dead link's 6 uncounted holders spread over A (load 2) and B (load 0): 4 on B, 2 on A (F3)", onb)
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
        for name, (a, b) in PLANTS.items():
            if only and name not in only:
                continue
            if PSRC.count(a) != 1:
                print("PLANT %-11s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(PSRC.replace(a, b))
            print("PLANT %-11s %s" % (name, ("RED  (" + f[0][:90] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC)
    print("turn_cap_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
