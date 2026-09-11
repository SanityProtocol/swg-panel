#!/usr/bin/env python3
"""/api/state is compressed — but only for clients that explicitly ask, and never at the cost of a desync.

Measured before this was written (near-empty rig): 111,083 B -> 11,573 B, 9.6x, for 0.80 ms at level 6.
The response is `no-store` and already memoized for STATE_CACHE_TTL, so one compression amortizes over every
client and tab; the win scales with the fleet and the cost does not scale with the number of pollers.

The three things that could go wrong, and are asserted here:

  1. A compressed body sent with the UNCOMPRESSED Content-Length. On a keep-alive connection the next
     response is then read from the wrong offset — silent, intermittent, and on the path the SPA, /api/v1
     and /metrics all share. Checked on ONE connection with the encodings ALTERNATING, which is the only
     shape that catches it.
  2. Compressing for a client that never asked. `swg-noded` uses http.client and sends no Accept-Encoding
     at all, so an implicit default would change what the fleet receives. Opt-in must be explicit, and
     `gzip;q=0` means NO — substring matching gets that backwards.
  3. A stale compressed copy outliving the payload it was made from.

Run: python3 tests/gzip_state_selftest.py   (exit 0 = all pass)
"""
import gzip, http.client, importlib.machinery as mach, importlib.util as u, json, os, socket
import subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "swg-panel-server")
spec = u.spec_from_loader("swgp", mach.SourceFileLoader("swgp", SERVER))
P = u.module_from_spec(spec); spec.loader.exec_module(P)

fails = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "   " + str(detail)))
    if not cond: fails.append(name)

# ── 1. the header reader, on its own ──────────────────────────────────────────────────────────────
for hdr, want, why in [
    ("gzip", True, "the plain case"),
    ("gzip, deflate, br", True, "a real browser"),
    ("deflate, gzip;q=1.0, *;q=0.5", True, "q above zero"),
    ("gzip;q=0", False, "REFUSED — substring matching gets this backwards"),
    ("gzip;q=0.0", False, "refused, spelled the other way"),
    (None, False, "a node's http.client sends no header at all"),
    ("", False, "empty"),
    ("identity", False, "asked for no encoding"),
    ("br", False, "asked for a different one"),
    ("x-gzip", False, "not the token we emit"),
]:
    check("accepts_gzip(%-28s) is %-5s  %s" % (repr(hdr), want, why), P.accepts_gzip(hdr) is want)

# ── 2. on the wire, against a real server on an ephemeral port ────────────────────────────────────
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

tmp = tempfile.mkdtemp(prefix="gzstate-")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
json.dump({"nodes_path": os.path.join(tmp, "state", "nodes.json"),
           "roster_path": os.path.join(tmp, "state", "users.json"),
           "panel_settings_path": os.path.join(tmp, "state", "panel-settings.json"),
           "config_dir": os.path.join(tmp, "conf"), "stats_dir": os.path.join(tmp, "stats"),
           "store_configs": False}, open(os.path.join(tmp, "fleet.json"), "w"))

port = free_port()
env = {**os.environ, "SWG_PANEL_FLEET": os.path.join(tmp, "fleet.json"), "SWG_PANEL_WEB": os.path.join(HERE, ".."),
       "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "",
       "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": ""}
proc = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2); c.request("GET", "/api/state")
            c.getresponse().read(); c.close(); break
        except Exception:
            time.sleep(0.1)
    else:
        print("  FAIL server never came up"); sys.exit(1)

    # ONE connection, encodings ALTERNATING — the only shape a desync shows up in
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    seen, desync = [], None
    # A DESYNCED Content-Length does not return a wrong answer — it STALLS, because the client is still
    # waiting for bytes the server already stopped sending, and then the connection is poisoned for every
    # request after it. So the failure arrives as a timeout, and it has to be caught and NAMED here: an
    # unhandled traceback tells whoever runs this that the test broke, not that the server did.
    try:
        for ae, want_gz in [("gzip", True), (None, False), ("gzip", True), ("gzip;q=0", False), (None, False)]:
            conn.request("GET", "/api/state", headers={"Accept-Encoding": ae} if ae else {})
            r = conn.getresponse(); body = r.read()
            enc = (r.getheader("Content-Encoding") or "").lower()
            raw = gzip.decompress(body) if enc == "gzip" else body
            seen.append({"ae": ae, "enc": enc, "n": len(body), "want": want_gz,
                         "len_ok": len(body) == int(r.getheader("Content-Length")),
                         "json_ok": (json.loads(raw) or True) and True})
    except Exception as e:
        desync = "%s: %s" % (type(e).__name__, e)
    finally:
        with __import__("contextlib").suppress(Exception):
            conn.close()

    check("a client that asks gets gzip", all(s["enc"] == "gzip" for s in seen if s["want"]),
          json.dumps([s["enc"] for s in seen]))
    check("…and one that does not, does not", all(s["enc"] == "" for s in seen if not s["want"]),
          json.dumps([s["enc"] for s in seen]))
    check("Content-Length is the bytes actually written, every time", all(s["len_ok"] for s in seen))
    check("every body parses as JSON after decoding", all(s["json_ok"] for s in seen))
    check("NO DESYNC across five alternating requests on ONE keep-alive connection",
          desync is None and len(seen) == 5,
          desync or "stopped after %d of 5" % len(seen))
    _gz = [x["n"] for x in seen if x["want"]]; _rw = [x["n"] for x in seen if not x["want"]]
    check("and it is actually smaller" + (" (%.1fx)" % (_rw[0] / _gz[0]) if _gz and _rw else ""),
          bool(_gz and _rw) and _gz[0] * 3 < _rw[0], "gz=%s raw=%s" % (_gz[:1], _rw[:1]))
finally:
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()

# ── 3. the compressed copy never outlives its source ──────────────────────────────────────────────
src = open(SERVER).read()
check("rebuilding the state cache clears the compressed copy",
      'c["gz"] = None' in src and src.index('c["bytes"] = json.dumps(obj).encode()') < src.index('c["gz"] = None'),
      "the reset must sit with the rebuild")

print()
if fails:
    print("✗ gzip state: %d failed" % len(fails)); sys.exit(1)
print("✓ gzip state: compressed only on explicit request, length always matches the body, keep-alive intact")
