#!/usr/bin/env python3
"""Self-test — the VK link pool with no size limit, bare hashes, the pool out of the poll, and the alive check (S12b).

Drives the REAL panel over HTTP against a stub of VK's API (SWG_PANEL_VK_API), with the check's timings shortened:

  [1]  a pool of 100 links is saved and read back whole — no 64 cap
  [2]  a bare hash becomes https://vk.ru/call/join/<hash> on every server entry path (pool save, user vk_link, user
       vk_links); a 15-character one is refused on both; a full link is stored as typed
  [3]  the poll carries no vk_pool, but vk_pool_rev and the live count; GET /api/vk-pool carries the list
  [4]  a row check against the stub: alive → nothing marked; dead twice → marked `dead_by: "check"` and its holders
       moved; dead once then alive → not marked
  [5]  "Check all" and the automatic run never ask about a dead link; a row check does
  [6]  a row check revives a link the CHECK marked dead, and leaves one the OPERATOR marked dead as it is
  [7]  the editor's save keeps `dead_by` on a link still dead under its URL, drops it on an un-mark, and never takes
       it from the body
  [8]  a run racing an edit: a link edited while VK was being asked about it is not marked
  [9]  a run's dead marks are saved together: one event for three links, their holders moved
  [10] golden: an empty pool asks VK nothing and writes nothing across the settle and a whole period
  [17] "Check all" runs at once, even in the minute after a start (the settle delays only the automatic run)
  [11] the switch off: no automatic run; [12] switched off mid-run: the run stops
  [13] captcha and flood control stop a run ("limited"), no answer stops it ("failed"); later links are not asked
  [14] "Check all" while a run is going starts nothing; with no live link it starts nothing
  [15] a link's answer is shown only while it still holds the URL that was asked about
  [16] a row check waits on VK WITHOUT holding the panel's lock: another save goes through meanwhile

Run: python3 tests/vk_pool_check_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
FIRST_FAIL = os.environ.get("VKCHK_FIRST_FAIL") == "1"     # a plant's run stops at its first FAIL

PLANTS = {   # name: (old text, planted text)
    "limit": ('    return out\n\n\ndef _vk_pool_live', '    return out[:64]\n\n\ndef _vk_pool_live'),
    "norm-off": ('    return VK_JOIN_URL + s if _VK_HASH_RE.fullmatch(s) else s', '    return s'),
    "poll-pool": ('    out = {k: v for k, v in ps.items() if k != "vk_pool"}', '    out = dict(ps)'),
    "one-ask": ('    v = _vk_ask(h)\n    if v != "dead":\n        return v', '    v = _vk_ask(h)\n    if True:\n        return v'),
    "captcha-dead": ('    if code in (951, 954) or 9000', '    if code in (951, 954, 14) or 9000'),
    "no-stop": ('            elif v in ("limited", "neterr"):', '            elif v in ():'),
    "skip-off": ('    todo = [(e["id"], e["url"]) for e in _vk_pool_live(deps.get("panel_settings") or {})]',
                 '    todo = [(e["id"], e["url"]) for e in _vk_pool_list(deps.get("panel_settings") or {})]'),
    "revive-any": ('        if not dead and e.get("dead") and e.get("dead_by") == "check":', '        if not dead and e.get("dead"):'),
    "body-deadby": ('if dead and prev.get("dead_by") == "check" and prev.get("url") == url else {})',
                    'if dead and (e.get("dead_by") == "check" or prev.get("dead_by") == "check") else {})'),
    "keep-off": ('if dead and prev.get("dead_by") == "check" and prev.get("url") == url else {})', 'if False else {})'),
    "commit-by-id": ('            return False                              # edited while it was being asked about\n',
                     '            pass\n'),
    "commit-per-link": ('            if v == "dead":\n                dead.append((eid, url))',
                        '            if v == "dead":\n                with _api_lock:\n                    _ps = deps.get("panel_settings") or {}\n'
                        '                    if _vk_mark(_ps, eid, url, True):\n'
                        '                        _ps["vk_pool_rev"] = int(_ps.get("vk_pool_rev") or 0) + 1\n'
                        '                        _vk_check_save(deps, _ps, roster_path, 1)'),
    "empty-runs": ('            due = (ps.get("vk_check_auto") is not False and time.time() >= int(last.get("at") or 0) + VK_CHECK_EVERY\n'
                   '                   and _vk_pool_live(ps))',
                   '            due = (ps.get("vk_check_auto") is not False and time.time() >= int(last.get("at") or 0) + VK_CHECK_EVERY)'),
    "auto-ignored": ('            due = (ps.get("vk_check_auto") is not False and time.time()', '            due = (True and time.time()'),
    "switch-midrun": ('            if not manual and ps.get("vk_check_auto") is False:', '            if False:'),
    "running-guard": ('            if _VK_CHECK["running"]:\n                return 200, {"ok": True, "data": {"started": False, "running": True}}\n', ''),
    "nolive-guard": ('            if not _vk_pool_live(deps.get("panel_settings") or {}):\n'
                     '                return 200, {"ok": True, "data": {"started": False, "running": False}}\n', ''),
    "res-anyurl": ('if at >= cut and urls.get(k) == u}', 'if at >= cut and k in urls}'),
    "settle-sleep": ('    wait = VK_CHECK_SETTLE ', '    time.sleep(VK_CHECK_SETTLE); wait = VK_CHECK_TICK '),
    "lock-held": ('            if path in _LOCKLESS_POST or path in _SELF_LOCKING_POST:', '            if path in _LOCKLESS_POST:'),
}

J = "https://vk.ru/call/join/"
def H(kind, n):
    """A stub hash: the first two letters say how the stub answers, the rest make it unique and long enough."""
    return "%s%s%04d" % (kind, "x" * 14, n)


# ── the stub of VK's API ──────────────────────────────────────────────────────────────────────────────────────
class Stub:
    def __init__(self):
        self.log = []                                 # (method, hash) of every request, in order
        self.previews = {}                            # hash → getCallPreview count
        self.flipped = set()                          # FP hashes that now answer alive
        self.hold = {}                                # hash → (reached Event, release Event): block on that preview
        self.lock = threading.Lock()

    def answer(self, method, h):
        kind = h[:2]
        with self.lock:
            self.log.append((method, h))
        if kind == "NE":
            return 500, {}
        if method == "auth.getAnonymToken":
            if kind == "CP":
                return 200, {"error": {"error_code": 14, "error_msg": "Captcha needed"}}
            if kind == "FL":
                return 200, {"error": {"error_code": 9, "error_msg": "Flood control"}}
            return 200, {"response": {"token": "tok-" + h}}
        with self.lock:
            self.previews[h] = n = self.previews.get(h, 0) + 1
        held = self.hold.get(h)
        if held and (kind == "HA" or n == 2):         # HA: its first preview; HD: the confirming second one
            held[0].set()
            held[1].wait(30)
        alive = {"response": {"user_id": 7, "secret": "s3cr3t"}}
        dead = {"error": {"error_code": 954, "error_msg": "Invalid join link"}}
        if kind in ("AL", "HA"):
            return 200, alive
        if kind in ("DX", "HD"):
            return 200, dead
        if kind == "D1":
            return 200, dead if n == 1 else alive
        if kind == "FP":
            return 200, alive if h in self.flipped else dead
        return 200, {"response": {}}

    def asked(self, h):
        with self.lock:
            return any(x == h for _, x in self.log)


def start_stub(stub):
    class Hd(BaseHTTPRequestHandler):
        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            link = (q.get("link") or [""])[0]
            code, obj = stub.answer(u.path.rsplit("/", 1)[-1], link.rsplit("/", 1)[-1])
            raw = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def run(server):
    """One full pass against `server`; returns the names of the failed checks."""
    fails = []
    def check(name, cond, detail=""):
        print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""), flush=True)
        if not cond:
            fails.append(name)
            if FIRST_FAIL:
                raise SystemExit(1)

    D = tempfile.mkdtemp(prefix="vkchk-")
    for d in ("state", "conf", "stats"):
        os.makedirs(os.path.join(D, d))
    json.dump({"nodes_path": D + "/state/nodes.json", "roster_path": D + "/state/users.json",
               "panel_settings_path": D + "/state/panel-settings.json", "config_dir": D + "/conf", "stats_dir": D + "/stats",
               "store_configs": False}, open(os.path.join(D, "fleet.json"), "w"))
    stub = Stub(); ss = start_stub(stub)
    PORT = free_port()
    EVERY, SETTLE = 4.0, 6.0
    env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=ROOT, SWG_PANEL_HOST="127.0.0.1",
               SWG_PANEL_PORT=str(PORT), SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="", SWG_NO_REEXEC="1",
               SWG_PANEL_VK_API="http://127.0.0.1:%d/method/" % ss.server_address[1],
               SWG_PANEL_VK_CHECK_GAP="0.05", SWG_PANEL_VK_CHECK_AGAIN="0.2",
               SWG_PANEL_VK_CHECK_EVERY=str(EVERY), SWG_PANEL_VK_CHECK_SETTLE=str(SETTLE))
    srv = subprocess.Popen([sys.executable, server], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def call(method, path, body=None, timeout=60):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
        r = c.getresponse(); raw = r.read(); c.close()
        return r.status, json.loads(raw or b"{}")
    def get_pool():
        return call("GET", "/api/vk-pool")[1]["data"]
    def save_pool(pool):
        return call("POST", "/api/vk-pool", {"pool": pool, "rev": get_pool()["rev"]})
    def by_url(url):
        return next((e for e in get_pool()["pool"] if e["url"] == url), None)
    def ps_poll():
        return call("GET", "/api/state")[1]["data"]["panel_settings"]
    def users():
        return json.load(open(D + "/state/users.json"))["users"]
    def holders(url):
        return [u for u in users().values() if url in (u.get("vk_links") or [])]
    def settings_file():
        try:
            return json.load(open(D + "/state/panel-settings.json"))
        except FileNotFoundError:
            return {}
    def row_check(url):
        e = by_url(url)
        return call("POST", "/api/vk-pool/check", {"id": e["id"]})[1].get("data") or {}
    def check_all_and_wait():
        before = (ps_poll().get("vk_check") or {}).get("at") or 0
        r = call("POST", "/api/vk-pool/check", {})[1]["data"]
        for _ in range(300):
            ck = ps_poll().get("vk_check") or {}
            if not ck.get("running") and (ck.get("at") or 0) and ((ck.get("at") or 0) > before or time.time() - (ck.get("at") or 0) < 2):
                if not ck.get("running"):
                    break
            time.sleep(0.1)
        time.sleep(0.2)
        return r, ps_poll().get("vk_check") or {}
    def events(verb):
        try:
            return [x for x in (json.loads(l) for l in open(D + "/state/events.jsonl") if l.strip()) if x.get("verb") == verb or x.get("action") == verb]
        except FileNotFoundError:
            return []

    try:
        for _ in range(200):
            try:
                if call("GET", "/api/state", timeout=5)[0] == 200:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            check("the panel came up", False); return fails

        # [17] "Check all" inside the settle runs at once
        t0 = time.time()
        save_pool([{"url": J + H("AL", 1)}])
        call("POST", "/api/vk-pool/check", {})
        for _ in range(40):
            if (settings_file().get("vk_check") or {}).get("at"):
                break
            time.sleep(0.1)
        check("[17] \"Check all\" runs at once after a start", stub.asked(H("AL", 1)) and time.time() - t0 < SETTLE - 1, time.time() - t0)
        # [10] golden: an empty pool, the switch on by default — the settle and a whole period pass, nothing is asked
        save_pool([])
        n_log, ck0 = len(stub.log), settings_file().get("vk_check")
        time.sleep(SETTLE + EVERY + 1.5)
        check("[10] an empty pool asks VK nothing", len(stub.log) == n_log, stub.log[n_log:n_log + 3])
        check("[10] …and writes no check state", settings_file().get("vk_check") == ck0, (ck0, settings_file().get("vk_check")))
        check("[11] the switch is on by default", ps_poll().get("vk_check_auto") is True)
        code, r = call("POST", "/api/vk-pool/check-auto", {"on": False})
        check("[11] the switch saves", code == 200 and settings_file().get("vk_check_auto") is False, r)
        check("[14] \"Check all\" with no live link starts nothing", call("POST", "/api/vk-pool/check", {})[1]["data"].get("started") is False)

        # [1] no size limit
        code, r = save_pool([{"url": J + H("AL", i)} for i in range(100)])
        check("[1] a pool of 100 links is accepted", code == 200, r)
        check("[1] …and read back whole", len(get_pool()["pool"]) == 100, len(get_pool()["pool"]))

        # [2] a bare hash on every server entry path
        a, b, c, d, e = H("AL", 1001), H("DX", 1002), H("D1", 1003), H("AL", 1004), H("FP", 1005)
        code, r = save_pool([{"url": a}, {"url": J + b}, {"url": J + c}, {"url": J + d, "dead": True}, {"url": J + e}])
        urls = [x["url"] for x in get_pool()["pool"]]
        check("[2] a bare hash in the pool becomes its link", code == 200 and J + a in urls and a not in urls, (code, r, urls[:2]))
        check("[2] a full link is stored as typed", J + b in urls)
        check("[2] a 15-character hash is refused in the pool", save_pool([{"url": "A" * 15}])[0] == 400)
        for n in ("u1", "u2", "u3", "u4"):
            call("POST", "/api/users/create", {"name": n})
        uid = sorted(users())[0]
        h1, h2 = H("ZZ", 1), H("ZZ", 2)
        code, r = call("POST", "/api/users/update", {"id": uid, "vk_link": h1})
        check("[2] a bare hash as a user's link becomes its link", code == 200 and users()[uid].get("vk_link") == J + h1, (code, r))
        code, r = call("POST", "/api/users/update", {"id": uid, "vk_links": [h2, J + h1]})
        check("[2] a bare hash in a user's links becomes its link", code == 200 and users()[uid].get("vk_links") == [J + h2, J + h1], users()[uid].get("vk_links"))
        check("[2] a 15-character hash is refused for a user", call("POST", "/api/users/update", {"id": uid, "vk_link": "B" * 15})[0] == 400)

        # [3] the poll
        ps = ps_poll()
        check("[3] the poll carries no vk_pool", "vk_pool" not in ps, list(ps)[:5])
        check("[3] …but the live count and the rev", ps.get("vk_pool_live") == 4 and ps.get("vk_pool_rev") == get_pool()["rev"],
              (ps.get("vk_pool_live"), ps.get("vk_pool_rev")))

        # [4] row checks against the stub
        r = row_check(J + a)
        check("[4] alive → nothing marked", r.get("verdict") == "alive" and not by_url(J + a)["dead"], r)
        r = row_check(J + c)
        check("[4] dead once then alive → not marked", r.get("verdict") == "alive" and not by_url(J + c)["dead"]
              and stub.previews.get(c) == 2, (r, stub.previews.get(c)))
        had = len(holders(J + b))
        r = row_check(J + b)
        eb = by_url(J + b)
        check("[4] dead twice → marked dead by the check", r.get("verdict") == "dead" and eb["dead"] and eb.get("dead_by") == "check", (r, eb))
        check("[4] …and its holders moved off", had > 0 and not holders(J + b) and r.get("moved") == had, (had, r))

        # [5] [6] the operator's dead link: a row check asks (a run would not), and does not revive it
        r = row_check(J + d)
        ed = by_url(J + d)
        check("[5] a row check asks about a dead link", stub.asked(d))
        check("[6] alive on an operator-dead link leaves it dead", r.get("verdict") == "alive" and ed["dead"] and "dead_by" not in ed
              and r.get("operator_dead") is True, (r, ed))
        r = row_check(J + e)
        check("[6] (the check marks the flip link dead)", by_url(J + e).get("dead_by") == "check", r)

        # [7] dead_by through the editor's whole-pool save
        code, _ = save_pool(get_pool()["pool"])
        check("[7] the editor's save keeps dead_by on a link still dead", code == 200 and by_url(J + e).get("dead_by") == "check"
              and by_url(J + b).get("dead_by") == "check", by_url(J + e))
        stub.flipped.add(e)
        r = row_check(J + e)
        ee = by_url(J + e)
        check("[6] alive on a check-dead link revives it", r.get("revived") is True and not ee["dead"] and "dead_by" not in ee, (r, ee))
        pool = get_pool()["pool"]
        for x in pool:
            if x["url"] == J + b:
                x["dead"] = False
        save_pool(pool)
        check("[7] un-marked by the operator → dead_by is gone", not by_url(J + b)["dead"] and "dead_by" not in by_url(J + b), by_url(J + b))
        pool = get_pool()["pool"]
        for x in pool:
            if x["url"] in (J + b, J + a):
                x["dead"], x["dead_by"] = x["url"] == J + b, "check"
        save_pool(pool)
        check("[7] a link the operator marks dead carries no dead_by, whatever the body says",
              by_url(J + b)["dead"] and "dead_by" not in by_url(J + b) and "dead_by" not in by_url(J + a), (by_url(J + b), by_url(J + a)))

        # [15] an answer is shown only while the link holds the URL asked about
        res = get_pool()["res"]
        ida, idb = by_url(J + a)["id"], by_url(J + b)["id"]
        check("[15] the pool read carries each link's answer", (res.get(ida) or {}).get("v") == "alive", res)
        pool = get_pool()["pool"]
        for x in pool:
            if x["id"] == ida:
                x["url"] = J + H("AL", 1999)
        save_pool(pool)
        check("[15] an edited link's answer is no longer shown", ida not in get_pool()["res"], get_pool()["res"].get(ida))

        # [16] a row check does not hold the panel's lock while VK answers
        ha = H("HA", 1)
        stub.hold[ha] = (threading.Event(), threading.Event())
        pool = get_pool()["pool"] + [{"url": J + ha}]
        save_pool(pool)
        t = threading.Thread(target=row_check, args=(J + ha,)); t.start()
        stub.hold[ha][0].wait(10)
        t0 = time.time()
        try:
            code, _ = call("POST", "/api/vk-pool/per-user", {"n": 3}, timeout=3)
        except Exception:
            code = 0
        check("[16] another save goes through while a row check waits on VK", code == 200 and time.time() - t0 < 2.5, (code, time.time() - t0))
        stub.hold[ha][1].set(); t.join(30)

        # [13] [5] runs that stop: captcha, flood, no answer — and a run never asks about a dead link
        for kind, st in (("CP", "limited"), ("FL", "limited"), ("NE", "failed")):
            first, stopper, after, opd = H("AL", 2000 + ord(kind[0])), H(kind, 1), H("AL", 2100 + ord(kind[0])), H("AL", 2200 + ord(kind[0]))
            save_pool([{"url": J + first}, {"url": J + opd, "dead": True}, {"url": J + stopper}, {"url": J + after}])
            r, ck = check_all_and_wait()
            check("[13] %s stops the run: %s" % (kind, st), r.get("started") is True and ck.get("state") == st and stub.asked(first)
                  and stub.asked(stopper) and not stub.asked(after), (r, ck, stub.asked(after)))
            check("[5] \"Check all\" skips a dead link (%s)" % kind, not stub.asked(opd))
            check("[13] …and marks nothing (%s)" % kind, not any(x["dead"] for x in get_pool()["pool"] if x["url"] != J + opd))

        # [14] "Check all" while a run is going
        hb = H("HA", 2)
        stub.hold[hb] = (threading.Event(), threading.Event())
        save_pool([{"url": J + hb}, {"url": J + H("AL", 2300)}])
        r1 = call("POST", "/api/vk-pool/check", {})[1]["data"]
        stub.hold[hb][0].wait(10)
        r2 = call("POST", "/api/vk-pool/check", {})[1]["data"]
        check("[14] \"Check all\" while a run is going starts nothing", r1.get("started") is True and r2.get("started") is False
              and r2.get("running") is True and ps_poll()["vk_check"].get("running") is True, (r1, r2))
        stub.hold[hb][1].set()
        for _ in range(100):
            if not ps_poll()["vk_check"].get("running"):
                break
            time.sleep(0.1)

        # [8] [9] one run, three dead links and one edited while VK was asked about it
        x2, x3, x4, hd = H("DX", 2), H("DX", 3), H("DX", 4), H("HD", 1)
        stub.hold[hd] = (threading.Event(), threading.Event())
        save_pool([{"url": J + x2}, {"url": J + x3}, {"url": J + hd}, {"url": J + x4}])
        for n in ("v1", "v2", "v3", "v4", "v5"):
            call("POST", "/api/users/create", {"name": n})
        held_before = sum(len(holders(J + x)) for x in (x2, x3, x4))
        n_ev = len(events("VK check marked links dead"))
        threading.Thread(target=check_all_and_wait).start()
        stub.hold[hd][0].wait(15)
        pool = get_pool()["pool"]
        for x in pool:
            if x["url"] == J + hd:
                x["url"] = J + H("AL", 2400)
        save_pool(pool)
        stub.hold[hd][1].set()
        for _ in range(200):
            time.sleep(0.1)
            if not ps_poll()["vk_check"].get("running"):
                break
        time.sleep(0.3)
        pl = get_pool()["pool"]
        dx = [x for x in pl if x["url"] in (J + x2, J + x3, J + x4)]
        check("[9] the run marked its three dead links", len(dx) == 3 and all(x["dead"] and x.get("dead_by") == "check" for x in dx), dx)
        check("[8] a link edited while VK was asked about it is not marked", not by_url(J + H("AL", 2400))["dead"])
        check("[9] …saved together: one event", len(events("VK check marked links dead")) == n_ev + 1,
              len(events("VK check marked links dead")) - n_ev)
        check("[9] …and the holders moved off", held_before > 0 and not any(holders(J + x) for x in (x2, x3, x4)), held_before)

        # [11] the switch off: no automatic run over a whole period
        save_pool([{"url": J + H("AL", 2500)}])
        n_log, ck0 = len(stub.log), settings_file().get("vk_check")
        time.sleep(EVERY + 4.5)
        check("[11] switched off, no automatic run", len(stub.log) == n_log, stub.log[n_log:n_log + 3])
        check("[11] …and no run's state written", settings_file().get("vk_check") == ck0, (ck0, settings_file().get("vk_check")))

        # [12] [5] an automatic run: skips a dead link, and stops when switched off mid-run
        hc, a8, a9, opd = H("HA", 3), H("AL", 2508), H("AL", 2509), H("AL", 2510)
        stub.hold[hc] = (threading.Event(), threading.Event())
        save_pool([{"url": J + opd, "dead": True}, {"url": J + hc}, {"url": J + a8}, {"url": J + a9}])
        call("POST", "/api/vk-pool/check-auto", {"on": True})
        reached = stub.hold[hc][0].wait(EVERY + 6)
        check("[12] switched on, the automatic run comes", reached)
        check("[5] the automatic run skips a dead link", not stub.asked(opd))
        call("POST", "/api/vk-pool/check-auto", {"on": False})
        stub.hold[hc][1].set()
        time.sleep(1.0)
        check("[12] switched off mid-run, the run stops", not stub.asked(a8) and not stub.asked(a9))
    finally:
        srv.terminate()
        try:
            srv.wait(5)
        except Exception:
            srv.kill()
        ss.shutdown()
        shutil.rmtree(D, ignore_errors=True)
    return fails


def plant_one(item):
    name, (old, new) = item
    src = open(SERVER, encoding="utf-8").read()
    if src.count(old) != 1:
        return name, "anchor missing — fix the plant"
    d = tempfile.mkdtemp(prefix="vkplant-")
    path = os.path.join(d, "swg-panel-server")
    open(path, "w").write(src.replace(old, new))
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=dict(os.environ, SWG_PANEL_SERVER=path, VKCHK_FIRST_FAIL="1"),
                       capture_output=True, text=True, timeout=600)
    shutil.rmtree(d, ignore_errors=True)
    failed = [l.strip()[5:] for l in r.stdout.splitlines() if l.strip().startswith("FAIL ")]
    return name, ("RED  (" + failed[0][:90] + ")") if failed else "GREEN — NOT CAUGHT"


def main():
    if "--perturb" in sys.argv:
        with ThreadPoolExecutor(4) as ex:
            out = list(ex.map(plant_one, PLANTS.items()))
        missed = [n for n, v in out if not v.startswith("RED")]
        for n, v in out:
            print("PLANT %-16s %s" % (n, v))
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run(SERVER)
    print("vk_pool_check_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
