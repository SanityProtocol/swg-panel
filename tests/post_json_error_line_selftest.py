#!/usr/bin/env python3
"""Self-test — A NODE LOGS A PANEL OR PROXY ERROR PAGE AS ONE LINE, NOT ONE ROW PER LINE OF ITS HTML.

Production, 2026-10-20/21: hel-relay and hel-flux reach the panel through Cloudflare. Each Cloudflare 502 (the panel
restarting, or the Cloudflare → panel hop failing) came back as a whole HTML page; swg-noded's post_json kept its first
200 characters raw, the sync loop logged `sync HTTP 502: <that>`, and log() writes every `\n`-line as its own entry —
about six 502s in a day were 31 red `err` rows in Live Logs. post_json's error on a status of 400 or more is now one
short line: an HTML page's <title> (else its first <h1>), anything else with its whitespace squeezed, cut at 200. The
panel's JSON `code` is still read from the RAW body (`_panel_busy`: a 503 with `code == "busy"`).

Real HTTP on 127.0.0.1, swg-noded's post_json as shipped. No root.
Run: python3 tests/post_json_error_line_selftest.py     (0 = pass)
     --perturb-raw    keeps the first 200 characters raw (the 1.8.8 shape) and expects RED
     --perturb-noh1   reads only <title>, so a page with an <h1> alone falls back to its markup, and expects RED
"""
import http.server, importlib.machinery, importlib.util, json, os, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
ARGS = set(sys.argv[1:])

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + repr(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(NODED, encoding="utf-8").read()
def plant(old, new):
    global SRC
    assert SRC.count(old) == 1, "plant anchor missing — would FALSE-PASS: %r" % old[:60]
    SRC = SRC.replace(old, new)
LINE = '            out = {"error": (line or " ".join(data.split()))[:200]}\n'
assert SRC.count(LINE) == 1, "anchor missing — post_json's error line changed; this run would test the wrong code"
if "--perturb-raw" in ARGS:
    plant(LINE, '            out = {"error": data[:200]}\n')
if "--perturb-noh1" in ARGS:
    plant(' or re.search(r"(?is)<h1\\b[^>]*>(.*?)</h1>", data)', "")

with tempfile.TemporaryDirectory(prefix="postjson-") as tmp:
    path = os.path.join(tmp, "noded.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SRC)
    loader = importlib.machinery.SourceFileLoader("swgnoded_pj", path)
    N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_pj", loader))
    try:
        loader.exec_module(N)
    except SystemExit:
        pass

# A Cloudflare 502 as it reaches a node: a whole page, the reason in <title> and again, split over spans, in <h1>.
CF502 = """<!DOCTYPE html>
<!--[if lt IE 7]> <html class="no-js ie6 oldie" lang="en-US"> <![endif]-->
<!--[if gt IE 8]><!--> <html class="no-js" lang="en-US"> <!--<![endif]-->
<head>
<title>panel.example.net | 502: Bad gateway</title>
<meta charset="UTF-8" />
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<link rel="stylesheet" id="cf_styles-css" href="/cdn-cgi/styles/main.css" />
</head>
<body>
<div id="cf-wrapper">
  <h1 class="inline-block md:block mr-2 md:mb-2 font-light text-60 md:text-3xl text-black-dark leading-tight">
    <span class="inline-block">Bad gateway</span>
    <span class="code-label">Error code 502</span>
  </h1>
</div>
</body>
</html>
"""
H1ONLY = "<html>\n<body>\n<h1>\n  <b>503</b> Service\n  Unavailable\n</h1>\n<p>The server is busy.</p>\n</body>\n</html>\n"
BUSY = {"ok": False, "error": "busy — another sync is running", "code": "busy"}
REPLIES = {
    "/cf": (502, "text/html", CF502),
    "/h1": (503, "text/html", H1ONLY),
    "/plain": (502, "text/plain", "error code: 502"),
    "/busy": (503, "application/json", json.dumps(BUSY)),
    "/busy-pretty": (503, "application/json", json.dumps(BUSY, indent=2)),
    "/401": (401, "application/json", json.dumps({"error": "unauthorized"})),
    "/long": (500, "text/plain", "x " * 400),
    "/ok": (200, "application/json", json.dumps({"desired": {}})),
}

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        st, ct, body = REPLIES[self.path]
        b = body.encode()
        self.send_response(st); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a):
        pass

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
def post(p):
    return N.post_json(BASE + p, "T", {"a": 1}, {})

print("[1] a proxy's HTML error page is one line: its <title>, else its first <h1>")
st, r = post("/cf")
check("Cloudflare 502: `sync HTTP 502: panel.example.net | 502: Bad gateway`",
      st == 502 and r.get("error") == "panel.example.net | 502: Bad gateway", (st, r))
st, r = post("/h1")
check("a page with an <h1> and no <title>: its text, tags and line breaks gone", r.get("error") == "503 Service Unavailable", r)

print("[2] anything else keeps its text, whitespace squeezed, cut at 200")
check("Cloudflare's plain `error code: 502` as it is", post("/plain")[1].get("error") == "error code: 502")
st, r = post("/long")
check("a long body: one line, at most 200 characters", "\n" not in r["error"] and len(r["error"]) == 200, r)
st, r = post("/401")
check("the panel's JSON 401: its text unchanged", st == 401 and r.get("error") == json.dumps({"error": "unauthorized"}), (st, r))

print("[3] the panel's machine-readable `code` is read from the raw body, as before")
for p in ("/busy", "/busy-pretty"):
    st, r = post(p)
    check("%s: a 503 with code busy (what _panel_busy reads)" % p, st == 503 and r.get("code") == "busy", (st, r))
    check("%s: …and its error is one line" % p, "\n" not in r.get("error", "\n"), r)
check("_panel_busy still recognises it", N._panel_busy(*post("/busy-pretty")))

print("[4] every error is one line; a 200 is untouched")
for p in ("/cf", "/h1", "/plain", "/busy", "/busy-pretty", "/401", "/long"):
    check("%s: no line break in the error" % p, "\n" not in post(p)[1].get("error", ""))
check("a 200 returns the panel's JSON as it was", post("/ok") == (200, {"desired": {}}))
srv.shutdown()

print()
if FAILS:
    print("RED — %d failed: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("GREEN")
