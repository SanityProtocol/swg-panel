"""Self-test — AN UNREAD REQUEST BODY POISONS THE NEXT REQUEST ON A KEEP-ALIVE CONNECTION.

The panel speaks HTTP/1.1 with keep-alive, so bytes a handler does not read stay in the socket and the NEXT
request on that connection is parsed starting from them. `_logout` answers with a cookie and nothing else,
never touching the 2-byte `{}` the SPA posts — so the browser's very next request arrived as

    {}GET / HTTP/1.1

and the panel answered `501 Unsupported method ('{}GET')`. Reported by an operator who pressed **Log out**
and got an error page instead of the login form, and reproduced on the wire against the live panel with one
POST and one GET on one connection.

⚠️ IT IS THE SHAPE, NOT THE HANDLER. The door's `send_error(404)`, the 413 refusal in `_body_len`, and every
future endpoint that answers without reading all leave the same residue — so the drain is hooked ONCE, at
`handle_one_request`, and this gate drives several different shapes through it rather than testing `_logout`
twice.

⚠️ AND NOT THE METHOD EITHER, which is where the first fix stopped. It wrapped `do_POST`, because that is
where the report came from, and left `do_GET` — which never reads a body at all — with the identical hole.
Measured against this tree after that fix: `GET /healthz` with `Content-Length: 7` and `{"x":1}` was answered
200, and the next request on the same connection came back

    501 Unsupported method ('{"x":1}GET')

A client can only poison itself that way — until the panel sits behind a reverse proxy that pools upstream
connections across clients (nginx `keepalive`, HAProxy, Caddy), where one client's leftover is parsed as the
NEXT client's request. Section [2] drives GET, and section [5] asserts the drain is not per-method, so a
future `do_PUT` cannot reopen it.

⚠️ AND THE DRAIN IS BOUNDED. A body refused BECAUSE it was oversized must not then be read to be tidy: that
hands an attacker the exact read the cap exists to prevent. Past `DRAIN_CAP` the connection is closed instead,
which is always a correct answer to a stream that can no longer be trusted.

`_send_bytes` has carried the mirror-image warning for the RESPONSE side for a while — "on a keep-alive
connection the next response is then read from the wrong offset". This is the request side of one invariant.

Run: python3 tests/keepalive_body_drain_selftest.py      (0 = pass)
     --perturb   removes the drain, the way it shipped, and expects the 501 back.
"""
import http.client, json, os, re, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(SERVER, encoding="utf-8").read()
_CALL = "                self._drain_request_body()\n"
assert SRC.count(_CALL) == 1, "drain anchor missing — this run would FALSE-PASS"
server = SERVER
if PERTURB:
    SRC = SRC.replace(_CALL, "                pass\n")
    fd, server = tempfile.mkstemp(suffix=".py", prefix="kadrain-", dir=HERE)
    os.write(fd, SRC.encode()); os.close(fd)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


tmp = tempfile.mkdtemp(prefix="kadrain-")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
json.dump({"nodes_path": os.path.join(tmp, "state", "nodes.json"),
           "roster_path": os.path.join(tmp, "state", "users.json"),
           "panel_settings_path": os.path.join(tmp, "state", "panel-settings.json"),
           "config_dir": os.path.join(tmp, "conf"), "stats_dir": os.path.join(tmp, "stats"),
           "store_configs": False}, open(os.path.join(tmp, "fleet.json"), "w"))

port = free_port()
env = {**os.environ, "SWG_PANEL_FLEET": os.path.join(tmp, "fleet.json"), "SWG_PANEL_WEB": ROOT,
       "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "",
       "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": ""}
# ⚠️ ONE PID, RECORDED, AND ONLY THAT PID IS EVER SIGNALLED. Never a name match.
proc = subprocess.Popen([sys.executable, server], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def read_response(f):
    """Frame one response by hand — http.client would hide the desync this test exists to see."""
    hdr = b""
    while b"\r\n\r\n" not in hdr:
        c = f.read(1)
        if not c:
            return None, b""
        hdr += c
    m = re.search(rb"Content-Length: (\d+)", hdr, re.I)
    return hdr.split(b"\r\n")[0].decode(errors="replace"), (f.read(int(m.group(1))) if m else b"")


def conversation(first):
    """Send `first` (a POST with a body), then two plain GETs on the SAME connection."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    f = s.makefile("rwb")
    try:
        f.write(first); f.flush()
        out = [read_response(f)[0]]
        for _ in range(2):
            f.write(b"GET /healthz HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n"); f.flush()
            line, _b = read_response(f)
            out.append(line)
            if line is None:
                break
        return out
    finally:
        s.close()


def req(method: bytes, path: bytes, body: bytes):
    return (method + b" " + path + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: keep-alive\r\n\r\n" + body)


def post(path, body: bytes):
    return req(b"POST", path, body)


try:
    for _ in range(150):
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/healthz"); c.getresponse().read(); c.close(); break
        except Exception:
            time.sleep(0.1)
    else:
        print("  FAIL server never came up:", (proc.stderr.read() or b"")[-400:]); sys.exit(1)

    print("[1] log out, then keep using the connection — the reported bug")
    r = conversation(post(b"/api/logout", b"{}"))
    check("the logout itself answers", r[0] and " 200 " in r[0], r[0])
    check("…and the NEXT request is not parsed out of its leftover body",
          r[1] is not None and "501" not in r[1], r[1])
    check("…nor the one after that", r[2] is not None and "501" not in r[2], r[2])

    print("\n[2] the same residue, from other shapes — and other METHODS")
    r = conversation(post(b"/api/definitely-not-a-route", b'{"a":"bbbbbbbbb"}'))
    check("an unknown POST leaves the connection usable", r[1] is not None and "501" not in r[1], r[1])
    r = conversation(post(b"/api/logout", b'{"padding":"' + b"x" * 500 + b'"}'))
    check("a LARGER unread body leaves it usable too", r[1] is not None and "501" not in r[1], r[1])
    # ⚠️ THE HALF THE FIRST FIX LEFT OPEN. `do_GET` reads no body on ANY route, so every one of them was a
    # `do_POST`-shaped hole until the drain moved to the request loop. `/healthz` needs no session, which
    # makes it the shape an unauthenticated client (or the proxy in front of it) can actually drive.
    r = conversation(req(b"GET", b"/healthz", b'{"x":1}'))
    check("a GET carrying a body still answers", r[0] and " 200 " in r[0], r[0])
    check("⚠️ …and does NOT poison the next request on that connection",
          r[1] is not None and "501" not in r[1], r[1])
    r = conversation(req(b"GET", b"/api/state", b'{"padding":"' + b"x" * 500 + b'"}'))
    check("…nor does a GET to an authenticated route", r[1] is not None and "501" not in r[1], r[1])

    print("\n[3] …but an oversized body is never read just to be tidy")
    # Content-Length past the cap: `_body_len` refuses it, and the drain must NOT then read it. Closing is
    # the correct answer, so what must NOT happen is a 501 — a successfully parsed request made of body.
    big = post(b"/api/logout", b"{}")
    big = big.replace(b"Content-Length: 2", b"Content-Length: 40000000")
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    f = s.makefile("rwb")
    f.write(big); f.flush()
    line, _ = read_response(f)
    check("an oversized body is refused, not swallowed", line is None or "501" not in (line or ""), line)
    s.close()

    print("\n[4] the invariant is stated where it is enforced")
    live = open(SERVER, encoding="utf-8").read()
    check("the drain runs in a finally", "finally:\n            try:\n                self._drain_request_body()" in live)
    check("…and a drain that FAILS closes rather than continuing",
          re.search(r"try:\n                self\._drain_request_body\(\)\n\s+except Exception:\n(?:\s*#.*\n)*\s+self\.close_connection = True", live) is not None)
    check("…and is bounded rather than unbounded", "if left > DRAIN_CAP:" in live)
    check("…closing instead of reading past the bound", "self.close_connection = True" in live)

    print("\n[5] ONE hook, not one per method — so a method added later cannot reopen this")
    # Said as a rule about the SHAPE of the code, because the three checks above can only ever test the
    # methods that exist today. `handle_one_request` is the single place every `do_*` is reached through.
    check("the drain hangs off the request loop, not off a handler",
          re.search(r"def handle_one_request\(self\):\n(?:.*\n)*?\s+self\.rfile = _CountedRfile\(_raw\)", live)
          is not None)
    check("…and no do_* method wraps it for itself",
          re.search(r"def do_[A-Z]+\(self\):\n\s+_raw = self\.rfile", live) is None)
    # The counter has to be zeroed after the headers or every handler looks like it already read its body.
    check("the body count starts at the body, not at the request line",
          "if ok and isinstance(self.rfile, _CountedRfile):\n            self.rfile.n = 0" in live)
    # Every read path _CountedRfile does NOT count would under-report and silently restore the bug.
    _uncounted = [m for m in re.findall(r"self\.rfile\.(\w+)\(", live) if m not in ("read", "readline", "n")]
    check("nothing reads a body through a path the counter cannot see", not _uncounted, _uncounted)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    if PERTURB:
        os.unlink(server)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
