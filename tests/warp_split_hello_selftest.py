#!/usr/bin/env python3
"""Self-test — WARP registration through an SNI block (1.8.12 item 17a, msk-forge 2026-11-20).

Measured on msk-forge (FirstVDS, Moscow): api.cloudflareclient.com is blocked by its server name — the TLS handshake
times out — while the WireGuard tunnel itself works, so a WARP exit could never be created there. A ClientHello split
into TWO TLS RECORDS cut inside the name got through; split into TCP segments it did not (the DPI reassembles TCP).

  [1] _split_hello: one handshake record → two, the cut inside the name; a non-handshake record or one without the name
      is unchanged; the two bodies together are the original.
  [2] _SplitHTTPS against a local TLS server behind a stand-in DPI that drops any connection whose FIRST record carries
      the whole name: the plain request is dropped (status 0), the split one completes (200, certificate verified), its
      first byte sent alone on a TCP_NODELAY socket (msk-forge needed both halves).
  [3] _warp_api: no HTTP answer → one split retry, which sets the flag (the next call goes split first); an HTTP answer
      (403) is never retried; both failing → the blocked-network sentence; _warp_register passes it on whole.

Run: python3 tests/warp_split_hello_selftest.py     (0 = pass)
     --perturb   _split_hello returns the record unchanged → RED on [1] and [2]
"""
import importlib.machinery, importlib.util, json, os, socket, ssl, struct, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if PERTURB:
    a = "    if len(rec) < 6 or rec[0] != 0x16:\n        return rec\n    body, name = rec[5:], host.encode()"
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    return rec\n" + a)
p = os.path.join(tempfile.mkdtemp(prefix="wsplit-"), "swg-noded"); open(p, "w").write(src)
os.environ["SWG_NO_REEXEC"] = "1"
ld = importlib.machinery.SourceFileLoader("swgnoded_wsplit", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_wsplit", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass

def records(b):
    out, i = [], 0
    while i + 5 <= len(b):
        n = struct.unpack("!H", b[i + 3:i + 5])[0]
        out.append(b[i:i + 5 + n]); i += 5 + n
    return out

print("[1] _split_hello")
host = "api.cloudflareclient.com"
body = b"\x01\x00\x01\x00" + os.urandom(40) + b"\x00\x00" + host.encode() + os.urandom(30)
rec = b"\x16\x03\x01" + struct.pack("!H", len(body)) + body
out = N._split_hello(rec, host)
rs = records(out)
check("a handshake record carrying the name → two handshake records", len(rs) == 2 and all(r[0] == 0x16 for r in rs), rs)
check("…neither carries the whole name", all(host.encode() not in r for r in rs), rs)
check("…and their bodies together are the original", b"".join(r[5:] for r in rs) == body)
check("a record without the name → unchanged", N._split_hello(b"\x16\x03\x01\x00\x03abc", host) == b"\x16\x03\x01\x00\x03abc")
check("an application-data record → unchanged", N._split_hello(b"\x17\x03\x03" + struct.pack("!H", len(body)) + body, host)[0] == 0x17
      and len(records(N._split_hello(b"\x17\x03\x03" + struct.pack("!H", len(body)) + body, host))) == 1)

print("\n[2] _SplitHTTPS through a stand-in DPI")
d = tempfile.mkdtemp(prefix="wsplit-tls-")
cert, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost", "-keyout", key, "-out", cert], check=True, capture_output=True)
sctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH); sctx.load_cert_chain(cert, key)
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", 0)); srv.listen(8)
PORT = srv.getsockname()[1]
SEEN = []
def serve(c):
    try:
        c.settimeout(3); buf, t0 = b"", time.time()
        while time.time() - t0 < 2:                       # peek until the first record is whole
            buf = c.recv(4096, socket.MSG_PEEK)
            if len(buf) >= 5 and len(buf) >= 5 + struct.unpack("!H", buf[3:5])[0]:
                break
            time.sleep(0.02)
        first = records(buf)[0] if records(buf) else buf
        SEEN.append(first)
        if b"localhost" in first:                        # the DPI: the whole name in the first record → silence
            time.sleep(3); c.close(); return
        t = sctx.wrap_socket(c, server_side=True)
        req = b""
        while b"\r\n\r\n" not in req:
            req += t.recv(4096)
        hd, _, rest = req.partition(b"\r\n\r\n")
        n = int(next((l.split(b":")[1] for l in hd.split(b"\r\n") if l.lower().startswith(b"content-length")), b"0"))
        while len(rest) < n:
            rest += t.recv(4096)
        out = json.dumps({"ok": True, "got": json.loads(rest or b"{}")}).encode()
        t.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(out) + out)
        t.close()
    except Exception:
        with __import__("contextlib").suppress(Exception):
            c.close()
def accept():
    while True:
        c, _ = srv.accept(); threading.Thread(target=serve, args=(c,), daemon=True).start()
threading.Thread(target=accept, daemon=True).start()
cctx = ssl.create_default_context(cafile=cert)
url = "https://localhost:%d/v0a2158/reg" % PORT
hdr = {"Content-Type": "application/json"}
st, dd = N._warp_call(url, b'{"key":"k"}', "POST", hdr, False, timeout=1.5, ctx=cctx)
check("plain request: the DPI drops it — no HTTP answer (status 0)", st == 0, (st, dd))
st, dd = N._warp_call(url, b'{"key":"k"}', "POST", hdr, True, timeout=3, ctx=cctx)
check("split request: answered 200 with the server's JSON (the body went through)",
      st == 200 and isinstance(dd, dict) and dd.get("got") == {"key": "k"}, (st, dd))
check("…its first record on the wire did not carry the whole name", bool(SEEN) and b"localhost" not in SEEN[-1], SEEN[-1:] and SEEN[-1][:80])
SENDS, NODELAY = [], []
_cc = socket.create_connection
class Rec:
    def __init__(s, so): s.so = so
    def sendall(s, b): SENDS.append(len(b)); return s.so.sendall(b)
    def setsockopt(s, *a):
        if a[:2] == (socket.IPPROTO_TCP, socket.TCP_NODELAY): NODELAY.append(a[2])
        return s.so.setsockopt(*a)
    def __getattr__(s, k): return getattr(s.so, k)
socket.create_connection = lambda *a, **k: Rec(_cc(*a, **k))
try:
    st, dd = N._warp_call(url, b'{"key":"k"}', "POST", hdr, True, timeout=3, ctx=cctx)
finally:
    socket.create_connection = _cc
check("…its first byte leaves alone, ahead of the rest, on a TCP_NODELAY socket (msk-forge: the record split alone is blocked)",
      st == 200 and SENDS[:1] == [1] and len(SENDS) >= 2 and NODELAY == [1], (st, SENDS[:4], NODELAY))
bad = ssl.create_default_context()                       # no trust in the test CA: the split must not weaken the check
st, dd = N._warp_call(url, b"{}", "POST", hdr, True, timeout=3, ctx=bad)
check("CONTROL: an untrusted certificate still fails through the split", st == 0 and "CERTIFICATE" in str(dd).upper(), (st, dd))

print("\n[3] _warp_api's retry")
calls = []
def fake(results):
    it = iter(results)
    def f(url, body, method, h, split, **kw):
        calls.append(split); return next(it)
    return f
N._WARP_SPLIT["on"] = False; calls.clear(); N._warp_call = fake([(0, "timed out"), (200, {"id": "x"})])
st, dd = N._warp_api("/reg", {}, "POST")
check("no answer → retried once, split, and its answer returned", calls == [False, True] and st == 200 and dd == {"id": "x"}, (calls, st, dd))
check("…and the flag is set", N._WARP_SPLIT["on"] is True)
calls.clear(); N._warp_call = fake([(200, {"id": "y"})])
N._warp_api("/reg", {}, "POST")
check("the next call goes split first, no wait on the plain one", calls == [True], calls)
N._WARP_SPLIT["on"] = False; calls.clear(); N._warp_call = fake([(403, {"errors": []})])
st, dd = N._warp_api("/reg", {}, "POST")
check("an HTTP answer (403) is never retried", calls == [False] and st == 403 and N._WARP_SPLIT["on"] is False, (calls, st))
calls.clear(); N._warp_call = fake([(0, "timed out"), (0, "timed out")])
st, dd = N._warp_api("/reg", {}, "POST")
check("both fail → status 0 with the blocked-network sentence, flag not set",
      st == 0 and str(dd).startswith("Cloudflare's WARP registration address is blocked") and N._WARP_SPLIT["on"] is False, (st, dd))
N.run = lambda *a, **k: type("R", (), {"stdout": "a2V5\n", "returncode": 0})()
N._warp_call = fake([(0, "timed out"), (0, "timed out")])
reg, err = N._warp_register()
check("_warp_register passes that sentence on whole (not 'registration failed (0)' cut at 120)",
      reg is None and err.startswith("Cloudflare's WARP registration address is blocked") and "registration failed" not in err, err)

print()
if FAILS:
    print("RED — %d failed" % len(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
