"""Self-test — the console's poll carries the roster's revision, not the roster (docs/SCALE-PLAN.md K4, U1).

At 10,000 users the roster was 6 of the 12.9 MB every /api/state carried to every open tab every 5 s, though it changes only
on a save. /api/state now names its revision (`roster_rev`); the browser fetches GET /api/roster?rev=<it> only when that
moves (js/store.js; its half is spa_scale_selftest [8]). The roster is serialised once per revision, and the /api/state build
pins the roster it walked, so a tab never pairs one moment's nodes with a later roster.

  A REAL panel process (temp state, scratch port, no auth, SWG_ROSTER_GUARD=1):
    [1] /api/state carries a string `roster_rev` and no `roster`
    [2] /api/roster?rev=<that> answers that revision, with users.json's content; a repeat gives the same bytes
    [3] gzip: Content-Encoding gzip, inflating to the plain body
    [4] a save moves the revision, and the new roster holds the record
    [5] the pin: a state read, then a save, then ?rev=<the state's> gives the state's roster (no new record); a bare
        /api/roster and an unknown rev give the current one; the body's rev is the roster's, never the request's; and
        those asks do not move the pin (scale-k4 F6) — only an /api/state build does

Run: python3 tests/roster_rev_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import gzip, json, os, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PSRC = open(PANEL, encoding="utf-8").read()

PLANTS = {   # name: (old text, planted text) — each re-introduces a defect the checks exist for
    "inline":    ('            "roster_rev": roster_bytes(roster_path, _rview)["rev"],',
                  '            "roster_rev": roster_bytes(roster_path, _rview)["rev"], "roster": _roster,'),
    "unkeyed":   ('    if c is None or m is None or (c["path"], c["mark"]) != (path, m):', '    if c is None:'),
    "unpinned":  ('        if c is None or c["path"] != rp or c["rev"] != (parse_qs(u.query).get("rev") or [""])[0]:', '        if True:'),
    "stuck":     ('        if c is None or c["path"] != rp or c["rev"] != (parse_qs(u.query).get("rev") or [""])[0]:', '        if c is None:'),
    "echo":      ('             "bytes": json.dumps({"ok": True, "rev": rev, "data": r}).encode()}',
                  '             "bytes": json.dumps({"ok": True, "rev": "0", "data": r}).encode()}'),
    "pinall":    ('                c = roster_bytes(rp, roster_view(rp), pin=False)', '                c = roster_bytes(rp, roster_view(rp))'),
    "nogzip":    ('            if path == "/api/roster":      # the roster of the revision /api/state named (`?rev=`), else the current one (U1)\n'
                  '                return self._send_roster(u)',
                  '            if path == "/api/roster":      # the roster of the revision /api/state named (`?rev=`), else the current one (U1)\n'
                  '                self.headers.replace_header("Accept-Encoding", "identity") if "Accept-Encoding" in self.headers else 0\n'
                  '                return self._send_roster(u)'),
}

NOW = int(time.time())


def roster():
    return {"version": 1, "users": {"u1": {"id": "u1", "name": "carol", "created_at": NOW - 100}},
            "peers": {"pa": {"id": "pa", "pubkey": "A" * 43 + "=", "psk": "P" * 43 + "=", "user_id": "u1", "title": "phone",
                             "targets": [{"node": "n1", "iface": "wg0", "type": "wg", "ip": "10.8.0.2"}],
                             "created_at": NOW - 100, "modified_at": NOW - 100}}}


def run_checks(src):
    fails = []

    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)

    tmp = tempfile.mkdtemp(prefix="roster-rev-")
    server = os.path.join(tmp, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src)
    state = os.path.join(tmp, "state"); os.makedirs(state); stats = os.path.join(tmp, "stats"); os.makedirs(stats)
    nodes, users = os.path.join(state, "nodes.json"), os.path.join(state, "users.json")
    json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}}}}, open(nodes, "w"))
    json.dump(roster(), open(users, "w"))
    fleet = os.path.join(tmp, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": users, "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(os.path.join(tmp, "panel.log"), "w+")
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")}
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**env, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                 "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                 "SWG_PANEL_TLS_KEY": "", "SWG_ROSTER_GUARD": "1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def raw(path, data=None, gz=False):
        hdr = {"Content-Type": "application/json", **({"Accept-Encoding": "gzip"} if gz else {})}
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers=hdr,
                                   data=json.dumps(data).encode() if data is not None else None)
        try:
            with opener.open(r, timeout=30) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def req(path, data=None):
        c, _, b = raw(path, data)
        return c, json.loads(b or b"{}")

    try:
        for _ in range(300):
            try:
                if raw("/healthz")[0] == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)

        print("[1] /api/state names the roster's revision")
        c, st = req("/api/state")
        d = st.get("data") or {}
        rev = d.get("roster_rev")
        ok(c == 200 and isinstance(rev, str) and rev, "[1] /api/state carries a string roster_rev (%r)" % rev)
        ok("roster" not in d, "[1] …and no roster")

        print("[2] /api/roster?rev= answers that revision")
        c, h, b = raw("/api/roster?rev=" + str(rev))
        ro = json.loads(b or b"{}")
        ok(c == 200 and ro.get("ok") is True and ro.get("rev") == rev, "[2] ok, and its rev is the state's (%r)" % ro.get("rev"))
        ok(ro.get("data") == json.load(open(users)), "[2] the data is users.json's content")
        ok((h.get("Cache-Control") or "") == "no-store", "[2] never cached (it carries PSKs)")
        ok(raw("/api/roster?rev=" + str(rev))[2] == b, "[2] a repeat gives the same bytes")

        print("[3] gzip")
        c, h, bz = raw("/api/roster?rev=" + str(rev), gz=True)
        ok(c == 200 and (h.get("Content-Encoding") or "") == "gzip", "[3] Content-Encoding gzip (%r)" % h.get("Content-Encoding"))
        try:
            same = gzip.decompress(bz) == b
        except Exception:
            same = False
        ok(same, "[3] …inflating to the plain body")

        print("[4] a save moves the revision")
        c, made = req("/api/users/create", {"name": "dmitri"})
        uid = ((made.get("data") or {}).get("id")) or ""
        ok(c == 200 and uid, "[4] the save went through (%s)" % c)
        c, st2 = req("/api/state")
        rev2 = (st2.get("data") or {}).get("roster_rev")
        ok(isinstance(rev2, str) and rev2 != rev, "[4] the revision moved (%r → %r)" % (rev, rev2))
        c, ro2 = req("/api/roster?rev=" + str(rev2))
        ok(ro2.get("rev") == rev2 and uid in ((ro2.get("data") or {}).get("users") or {}), "[4] the new roster holds the record")

        print("[5] the pin: the roster of the state just read")
        c, made = req("/api/users/create", {"name": "elena"})
        uid3 = ((made.get("data") or {}).get("id")) or ""
        ok(c == 200 and uid3, "[5] a second save went through")
        c, pin = req("/api/roster?rev=" + str(rev2))
        ok(pin.get("rev") == rev2 and uid3 not in ((pin.get("data") or {}).get("users") or {}),
           "[5] ?rev= the state's revision gives the state's roster, without the later record (rev %r)" % pin.get("rev"))
        for q in ("", "?rev=", "?rev=nonesuch"):
            c, cur = req("/api/roster" + q)
            ok(c == 200 and isinstance(cur.get("rev"), str) and cur.get("rev") not in (rev, rev2, "nonesuch")
               and uid3 in ((cur.get("data") or {}).get("users") or {}),
               "[5] /api/roster%s gives the current roster, labelled with its own rev (%r)" % (q, cur.get("rev")))
        c, again = req("/api/roster?rev=" + str(rev2))
        ok(again.get("rev") == rev2 and uid3 not in ((again.get("data") or {}).get("users") or {}),
           "[5] …and those asks did not move the pin: ?rev= the state's revision still gives the state's roster (F6)")
        c, st3 = req("/api/state")
        ok((st3.get("data") or {}).get("roster_rev") == cur.get("rev"), "[5] …the revision the next state names")
        ok(proc.poll() is None, "[*] the panel is still up (SWG_ROSTER_GUARD: no reader wrote the shared roster)")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
    if fails:
        log.seek(0)
        print("".join(log.readlines()[-15:]))
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if PSRC.count(old) != 1:
                print("PLANT %-10s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(PSRC.replace(old, new))
            print("PLANT %-10s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC)
    print("roster_rev_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
