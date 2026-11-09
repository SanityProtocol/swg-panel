#!/usr/bin/env python3
"""Self-test — compressed node uploads (docs/SCALE-PLAN.md N3, "K5 — design").

Settings → Network → Node uploads → Compress (`node_gzip`, off by default). While it is on, the sync reply carries
`gz_sync: true` and the node gzips the snapshot it posts each pass; the panel takes a gzip sync body always.

  THE PANEL (a REAL panel process: temp state, scratch port, no auth; the node's requests made by the REAL swg-noded
  post_json, so the body is signed the way a node signs it — over the bytes sent)
    [1] off (the default): the reply has no `gz_sync`; a compressed sync gets the same reply as a plain one
    [2] a compressed body that unpacks past MAX_SYNC_BODY → 413; one that does not unpack → 400; nothing stored from either
    [3] on: the reply carries `gz_sync: true`; off again: the key is gone
  THE NODE (the REAL swg-noded _sync_post)
    [4] it compresses only after a reply asked for it, and stops when a reply no longer does
    [5] against a REAL HTTP door (its replies read by the real post_json — card scale-k5 F12): any 4xx to a compressed POST
        — a panel's JSON 400 "bad body", a proxy's HTML 403, a 401 bad_signature — is sent again plain in the same pass, and
        compression is held off for an hour, then tried again; no answer at all (0) and a 503 are not retried plain
  THE CONSOLE (js/screen-settings.js, the settings idiom's halves — as panel_tz_selftest [5])
    [6] the switch's state starts from the stored setting, the Save carries it, the Network arm of glDirty sees it, a
        switch-only change reaches the confirm list; its words have Russian

Run: python3 tests/sync_gzip_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     nocap      the inflate is not capped
     flagoff    the flag is sent while the setting is off
     noretry    a refused compressed POST is not retried plain
     nohold     compression is not held off after a refusal (every pass would post twice)
     spadirty   the Network arm of glDirty does not see the switch (Save stays grey)
     spasave    the Save payload does not carry it
"""
import gzip, http.client, importlib.machinery, importlib.util, json, os, socket, subprocess, sys, tempfile, time
import threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PANEL_PLANTS = {
    "nocap": ("                raw = d.decompress(raw, MAX_SYNC_BODY)\n                if d.unconsumed_tail:",
              "                raw = d.decompress(raw)\n                if False:"),
    "flagoff": ('''**({"gz_sync": True} if _ps.get("node_gzip") is True''',
                '''**({"gz_sync": True} if True'''),
}
NODED_PLANTS = {
    "noretry": ("    if gz and 400 <= status < 500:\n", "    if False:\n"),
    "nohold": ('        _SYNC_GZ["off_until"] = time.monotonic() + SYNC_GZ_HOLD_S\n', '        pass\n'),
}
SPA_PLANTS = {
    "spadirty": (" || nodeGz !== (ps.node_gzip === true) || normScanAllow", " || normScanAllow"),
    "spasave": ("\n        node_gzip: nodeGz,\n", "\n"),
}
TMP = tempfile.mkdtemp(prefix="sync-gzip-")


def src_of(name, plants):
    s = open(os.path.join(ROOT, name), encoding="utf-8").read()
    if PLANT in plants:
        a, b = plants[PLANT]
        assert s.count(a) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
        s = s.replace(a, b, 1)
    p = os.path.join(TMP, name)
    open(p, "w", encoding="utf-8").write(s)
    return p


server = src_of("swg-panel-server", PANEL_PLANTS)
spa = open(os.path.join(ROOT, "js", "screen-settings.js"),
           encoding="utf-8").read()
if PLANT in SPA_PLANTS:
    assert spa.count(SPA_PLANTS[PLANT][0]) == 1, "plant anchor for %s missing or not unique" % PLANT
    spa = spa.replace(SPA_PLANTS[PLANT][0], SPA_PLANTS[PLANT][1], 1)
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
noded = src_of("swg-noded", NODED_PLANTS)
spec = importlib.util.spec_from_loader("swgnoded_gz", importlib.machinery.SourceFileLoader("swgnoded_gz", noded))
N = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(N)
except SystemExit:
    pass
N.log = lambda *a, **k: None
sys.excepthook = sys.__excepthook__              # the module installs its own (to its log)
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open   # never a desktop proxy for 127.0.0.1

state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json"); USERS = os.path.join(state, "users.json")
json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}}}}, open(NODES, "w"))
json.dump({"users": {"u1": {"name": "ann"}}, "peers": {"p1": {"name": "ph", "user_id": "u1", "public_key": "A" * 43 + "=",
                                                            "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.2"}]}}},
          open(USERS, "w"))
fleet_cfg = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": USERS, "stats_dir": stats}, open(fleet_cfg, "w"))
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
log = open(os.path.join(TMP, "panel.log"), "w+")
env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")}
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**env, "SWG_PANEL_FLEET": fleet_cfg, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
URL = "http://127.0.0.1:%d/api/node/sync" % PORT
NOW = int(time.time())


def req(path, data=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json"})
    try:
        with OPEN(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


SEQ = [0]


def snapshot(n=50):
    """A node's snapshot — each one different: the panel refuses a signed body it saw this second (replay, by MAC)."""
    SEQ[0] += 1
    peers = [{"public_key": "A" * 43 + "=", "allowed_ips": "10.8.0.2/32", "endpoint": None, "last_handshake": NOW - 5,
              "rx_bytes": 1000, "tx_bytes": 1000, "preshared_key": None}]
    peers += [{"public_key": ("%043d" % i) + "=", "allowed_ips": "10.8.1.%d/32" % (i % 250), "endpoint": "198.51.100.%d:%d" % (i % 250, 1024 + i),
               "last_handshake": NOW - i, "rx_bytes": i * 997, "tx_bytes": i * 991, "preshared_key": None} for i in range(n)]
    return {"hostname": "node-a", "generated_at": NOW + SEQ[0], "noded_version": "t",
            "interfaces": {"wg0": {"peers": peers, "meta": {"subnet": "10.8.0.0/24", "listen_port": 51820,
                                                              "public_key": "Z" * 43 + "=", "address": "10.8.0.1/24"}}}}


def raw_post(body, token, enc="gzip"):
    """POST raw bytes signed the node's way (the REAL _sig_headers over the bytes sent)."""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    c.request("POST", "/api/node/sync", body=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                                                             "Content-Encoding": enc, **N._sig_headers(token, body)})
    r = c.getresponse(); data = r.read(); c.close()
    return r.status, json.loads(data or b"{}")


def keys(reply):
    return sorted(k for k in reply if k not in ("update",))


try:
    for _ in range(150):
        try:
            OPEN("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    PANEL = {"url": "http://127.0.0.1:%d" % PORT, "token": TOK}

    print("[1] off: no flag, and a compressed sync is answered as a plain one")
    c1, r1 = N.post_json(URL, TOK, {"snapshot": snapshot()}, PANEL)
    c2, r2 = N.post_json(URL, TOK, {"snapshot": snapshot()}, PANEL, gz=True)
    check("[1] the plain sync answered, with no gz_sync", c1 == 200 and "desired" in r1 and "gz_sync" not in r1, (c1, str(r1)[:200]))
    check("[1] the compressed sync answered 200", c2 == 200, (c2, r2))
    check("[1] …with the same reply (desired, remove, keys)",
          r2.get("desired") == r1.get("desired") and r2.get("remove") == r1.get("remove") and keys(r2) == keys(r1),
          (keys(r1), keys(r2)))
    check("[1] …and a desired set for wg0 (the roster's device)", len((r1.get("desired") or {}).get("wg0", [])) == 1,
          r1.get("desired"))

    print("\n[2] what the inflate refuses")
    big = b'{"snapshot": {"x": "' + b"0" * (64 * 1024 * 1024 + 10) + b'"}}'
    c, r = raw_post(gzip.compress(big, 9), TOK)
    check("[2] a body that unpacks past MAX_SYNC_BODY → 413 (it is %d KB on the wire)" % (len(gzip.compress(big, 9)) // 1024), c == 413, (c, r))
    c, r = raw_post(b"\x1f\x8b\x08\x00garbage-not-a-stream", TOK)
    check("[2] a body that does not unpack → 400", c == 400, (c, r))
    c, r = raw_post(gzip.compress(b'{"snapshot": {"interfaces": '), TOK)
    check("[2] a stream that unpacks to broken JSON → 400", c == 400, (c, r))

    print("\n[3] on, then off")
    c, _ = req("/api/panel/settings", {"node_gzip": True})
    check("[3] the setting saves", c == 200, c)
    _c, r = N.post_json(URL, TOK, {"snapshot": snapshot()}, PANEL)
    check("[3] on: the reply carries gz_sync: true", r.get("gz_sync") is True, r.get("gz_sync"))
    c, _ = req("/api/panel/settings", {"node_gzip": False})
    _c, r = N.post_json(URL, TOK, {"snapshot": snapshot()}, PANEL)
    check("[3] off again: the key is gone", "gz_sync" not in r, r.get("gz_sync"))
    _ps = json.load(open(os.path.join(state, "panel-settings.json")))
    check("[3] …and off is stored as no key at all (a fleet that never turns it on reads as before)", "node_gzip" not in _ps,
          _ps.get("node_gzip"))

    print("\n[4] the node follows the reply")
    seen = []
    real = N.post_json
    N.post_json = lambda url, tok, obj, panel, **kw: (seen.append(kw.get("gz", False)), real(url, tok, obj, panel, **kw))[1]
    N._SYNC_GZ.update(on=False, off_until=0.0)
    req("/api/panel/settings", {"node_gzip": True})
    N._sync_post(URL, PANEL, snapshot(), ""); N._sync_post(URL, PANEL, snapshot(), "")
    check("[4] plain until a reply asks, then compressed", seen == [False, True], seen)
    req("/api/panel/settings", {"node_gzip": False})
    seen.clear(); N._sync_post(URL, PANEL, snapshot(), ""); N._sync_post(URL, PANEL, snapshot(), "")
    check("[4] a reply without the flag turns it off", seen == [True, False], seen)

    print("\n[5] a refused compressed POST, through a real HTTP door")
    N.post_json = real
    DOOR = {"gz": (400, "application/json", b'{"error": "bad body"}'), "seen": []}

    class Door(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            gz = (self.headers.get("Content-Encoding") or "") == "gzip"
            DOOR["seen"].append("gz" if gz else "plain")
            code, ctype, body = DOOR["gz"] if gz else (200, "application/json", b'{"desired": {}, "gz_sync": true}')
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    door = ThreadingHTTPServer(("127.0.0.1", 0), Door)
    threading.Thread(target=door.serve_forever, daemon=True).start()
    DURL = "http://127.0.0.1:%d/api/node/sync" % door.server_address[1]

    def one(answer):
        DOOR["gz"], DOOR["seen"] = answer, []
        N._SYNC_GZ.update(on=True, off_until=0.0)
        st, _r, _f = N._sync_post(DURL, PANEL, snapshot(), "")
        return st, list(DOOR["seen"])
    for what, answer in (("a panel's JSON 400 \"bad body\" (one from before N3)", (400, "application/json", b'{"error": "bad body"}')),
                         ("a proxy's HTML 403 page", (403, "text/html", b"<html><title>403 Forbidden</title></html>")),
                         ("a 401 bad_signature (a body rewritten on the way)",
                          (401, "application/json", b'{"error": "bad request signature (mismatch)", "code": "bad_signature"}')),
                         ("a 415", (415, "text/plain", b"unsupported"))):
        st, seen = one(answer)
        check("[5] %s: sent again plain in the same pass, answered" % what, seen == ["gz", "plain"] and st == 200, (seen, st))
        check("[5] …and compression held off for about an hour", 3500 < N._SYNC_GZ["off_until"] - time.monotonic() <= 3600,
              N._SYNC_GZ["off_until"] - time.monotonic())
    DOOR["seen"] = []
    N._sync_post(DURL, PANEL, snapshot(), ""); N._sync_post(DURL, PANEL, snapshot(), "")
    check("[5] the next passes post once each, uncompressed, though the reply still asks", DOOR["seen"] == ["plain", "plain"],
          DOOR["seen"])
    N._SYNC_GZ["off_until"] = time.monotonic() - 1; DOOR["gz"], DOOR["seen"] = (200, "application/json", b'{"desired": {}}'), []
    N._sync_post(DURL, PANEL, snapshot(), "")
    check("[5] an hour on, it compresses again (the reply asked)", DOOR["seen"] == ["gz"], DOOR["seen"])
    st, seen = one((503, "application/json", b'{"ok": false, "code": "busy"}'))
    check("[5] a 503 (a busy panel) is not retried plain", seen == ["gz"] and st == 503, (seen, st))
    door.shutdown(); door.server_close()
    N._SYNC_GZ.update(on=True, off_until=0.0)
    st, _r, _f = N._sync_post(DURL, PANEL, snapshot(), "")
    check("[5] no answer at all (0) is not retried plain, and holds nothing", st == 0 and N._SYNC_GZ["off_until"] == 0.0,
          (st, N._SYNC_GZ))
    N.post_json = real

    print("\n[6] the console's switch")
    check("[6] its state starts from the stored setting (off unless stored true)",
          "const [nodeGz, setNodeGz] = useState(ps.node_gzip === true);" in spa)
    check("[6] the Save carries it", "\n        node_gzip: nodeGz,\n" in spa)
    check("[6] the Network arm of glDirty sees it",
          'sec === "mesh" ? (showLans !== (ps.show_node_lans !== false) || nodeGz !== (ps.node_gzip === true) ||' in spa)
    check("[6] a switch-only change reaches the confirm list", "    if (nodeGz !== (ps.node_gzip === true)) out.push(" in spa)
    check("[6] the switch is on screen", "<${Switch} on=${nodeGz} onChange=${v => setNodeGz(v)}" in spa)
    words = ["Node uploads", "Compress", "Node uploads — compressed", "Node uploads — sent uncompressed",
             "Nodes gzip the state they send each sync"]
    check("[6] its words have Russian", all(('\n  "%s": "' % w) in ru for w in words), [w for w in words if ('\n  "%s": "' % w) not in ru])
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except Exception:
        proc.kill()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS))))
if PLANT:
    print("plant %s: %s" % (PLANT, "RED (caught)" if FAILS else "GREEN — NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
