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
  [5] the VK pool's load (T4): a blocked user, an expired one, a user whose devices are all plain WireGuard or all cut off
      → not counted; a user with no device yet, a csqtt one, a WireGuard one behind a turn-proxy, one with a blocked device
      beside a live turn one → counted

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
    "blocked":    ("    used = sum(1 for _pid, p in _peers_on(roster, nid)\n               if any(",
                   "    used = sum(1 for _pid, p in _peers_on(roster, nid)\n               if not p.get(\"disabled\") and any("),
    "addtarget":  ("        full = turn_full(nodes, roster, target)\n        if full:\n", "        full = None\n        if full:\n"),
    "issuebelow": ("            if _wait and _use >= _cap:\n", "            if _wait:\n"),
    "storedline": ("            _tl = str(e.get(\"line\") or _ti.get(\"line\") or CSQTT_DEFAULT_LINE)\n",
                   "            _tl = str(_ti.get(\"line\") or CSQTT_DEFAULT_LINE)\n"),
    "capkey":     ("**({\"turn_cap\": _tcap} if", "**({\"turn_caps\": _tcap} if"),
    "t4old":      ("        if not isinstance(u, dict) or (uid in has_dev and uid not in serves) or access_cut({}, u, nowv):\n",
                   "        if not isinstance(u, dict):\n"),
    "t4nodev":    ("(uid in has_dev and uid not in serves)", "(uid not in serves)"),
}

NOW = int(time.time())


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
                with urllib.request.urlopen(r, timeout=30) as resp:
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
            ok(code == 409 and r.get("code") == "turn_full" and "csqtt1 on node-a is full — 248 of 248 users" in (r.get("error") or "")
               and r.get("error_key", "").startswith("{v1} on {v2} is full"),
               "[2] the 249th is refused, naming the server and the count", (code, r))
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt1"}, {"node": "n1", "iface": "csqtt1"}]})
            ok(code == 409 and r.get("code") == "turn_full", "[2] a create with a free server beside the full one is refused whole", (code, r))
            code, r = req("/api/peers/add-target", {"peer_id": "w1", "target": {"node": "n1", "iface": "csqtt1"}})
            ok(code == 409 and r.get("code") == "turn_full", "[2] add-target onto the full server is refused", (code, r))
            ok(open(users_p, "rb").read() == before, "[2] nothing written by a refusal")
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt9"}]})
            ok(code == 200, "[2] a server on a fork the table does not know is never refused (301 there)", (code, r))
            code, r = req("/api/peers/create", {"targets": [{"node": "n1", "iface": "wdtt1"}]})
            ok(code == 200, "[2] a server with room takes one", (code, r))

            code, st = req("/api/state")
            nv = {n.get("id"): n for n in ((st.get("data") or {}).get("nodes") or [])}
            ok((nv.get("n1") or {}).get("turn_cap") == {"csqtt1": 248, "wdtt1": 249},
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

    print("[4] the node's own report")

    def issues(c, snap):
        return [i.get("error_key") for i in P._node_issues(c, snap) if "addresses are in use" in (i.get("error_key") or "")]
    c25 = {"csqtt": {"csqtt1": {"line": "2.5"}}}
    full25 = {"pw%d" % i: {"ip": "10.66.67.%d" % (i + 3)} for i in range(248)}
    ok(issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(full25, x={"ip": ""}), "devices": {}}]})
       == ["{v1}: {v2} users can't connect — all {v3} addresses are in use"], "[4] 2.5: full, one waiting → the line")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": full25, "devices": {}}]}),
       "[4] 2.5: full, nobody waiting → nothing")
    ok(not issues(c25, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": {"a": {"ip": "10.66.67.3"}, "b": {"ip": ""}}}]}),
       "[4] 2.5: one waiting below the pool → nothing")
    ok(issues({"csqtt": {"csqtt1": {}}}, {"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": dict(full25, x={"ip": ""})}]}),
       "[4] the RUNNING line decides (stored 2.1, the node runs 2.5)")
    devs = {"d%d" % i: {"ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    pw21 = {"p%d" % i: {"device_id": "d%d" % i, "ip": "10.66.70.%d" % (i + 2)} for i in range(249)}
    ok(issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
              {"wdtt": [{"iface": "wdtt1", "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}, y={"device_id": "", "ip": ""}), "devices": devs}]}),
       "[4] WDTT through its devices: 249 held, one bound and refused → the line")
    ok(not issues({"wdtt": {"wdtt1": {"fork": "amurcanov"}}},
                  {"wdtt": [{"iface": "wdtt1", "passwords": dict(pw21, y={"device_id": "", "ip": ""}), "devices": devs}]}),
       "[4] WDTT: a password never connected is not waiting")
    ok(issues({"csqtt": {"csqtt1": {}}}, {"csqtt": [{"iface": "csqtt1", "line": "2.1", "passwords": dict(pw21, x={"device_id": "dx", "ip": ""}), "devices": devs}]}),
       "[4] csqtt 2.1 through its devices")
    try:
        bad = [{"csqtt": [{"iface": "csqtt1", "line": "2.5", "passwords": ["x"]}]}, {"csqtt": ["junk", {"iface": "csqtt1", "passwords": {"a": "s"}}]},
               {"wdtt": [{"iface": "wdtt1", "passwords": {"a": {"device_id": "d", "ip": ""}}, "devices": ["x"]}]}]
        for b in bad:
            issues({"csqtt": {"csqtt1": {}}, "wdtt": {"wdtt1": "junk"}}, b)
            issues({"csqtt": "junk"}, b)
        ok(True, "[4] a malformed report raises nothing")
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
    snaps = {"n1": {"interfaces": {"wg0": {"meta": {"listen_port": 51820}}, "awg1": {"meta": {"listen_port": 51821}}},
                    "turn_proxies": [{"service": "tp1", "connect": "127.0.0.1:51821"}]}}
    got = P._vk_pool_counts(roster, snaps)
    ok(not any(got.get(L[i]) for i in (0, 1, 2, 3)), "[5] blocked, expired, plain-WireGuard-only, all-devices-cut users are not load", got)
    ok(all(got.get(L[i]) == 1 for i in (4, 5, 6, 7)),
       "[5] a user with no device yet, a csqtt one, a WireGuard one behind a turn-proxy, a blocked device beside a live turn one count", got)
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
