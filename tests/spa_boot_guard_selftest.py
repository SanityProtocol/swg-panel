#!/usr/bin/env python3
"""Behavioural gate for index.html's boot guard in a REAL browser (headless Chrome over tests/cdp_pipe.py) — 1.8.12 item 6.

A user's Docker master stopped loading its panel for the clients of an interface with an exit: the packets for the panel
left by the exit and nothing ever answered. The boot screen then said a module was "missing or damaged, which usually means
an interrupted update" and sent them to re-run an update that was never broken. A request with NO answer is a connection
problem; only an HTTP error is a missing file.

  [1] every ES module hangs (the route case as the user saw it: the stylesheets and the two classic scripts arrive, as from
      the browser's cache — one of those that hangs blocks the parser before the guard, and the page stays blank; backlog):
      after the 10 s backstop and the probes' 15 s timeout the screen says the files did not arrive, names the connection (and a VPN interface's exit or rule), and no longer tells the
      user to re-run the update.
  [2] the control — one module answers 404 (the interrupted-update case): the screen names that file and keeps the update
      advice.

The page is served by a small local server from this checkout (the panel's API is not needed: the guard runs before it).
Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
Run: python3 tests/spa_boot_guard_selftest.py      (0 = pass)
     --perturb-<name>  serves index.html with one part undone and expects RED:
                       silent     a no-answer is reported as missing files again ([1] RED)
                       notimeout  the probes wait for ever, so the screen never says what happened ([1] RED)
"""
import http.server, json, os, re, socket, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)
PLANTS = {
    "silent": ("        if (missing.length && silent === missing.length) {\n", "        if (false) {\n"),
    "notimeout": ("      r.timeout = 15000;\n", ""),
}
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

if not CHROME:
    print("  FAIL no Chrome/Chromium (set $CHROME) — this gate cannot run, which is not a pass")
    sys.exit(1)
if PERTURB and PERTURB not in PLANTS:
    print("  FAIL unknown perturbation %r" % PERTURB)
    sys.exit(2)

HTML = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
if PERTURB:
    a, b = PLANTS[PERTURB]
    assert HTML.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a.strip()
    HTML = HTML.replace(a, b)
HTML = HTML.encode("utf-8")
MODE = {"m": "hang"}
MODULES = set(re.findall(r'<link rel="modulepreload" href="([^"?]+)', HTML.decode("utf-8"))) | {"app.js"}
STOP = threading.Event()


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(HTML)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(HTML)
            return
        if MODE["m"] == "hang" and path.lstrip("/") in MODULES:
            STOP.wait(90)                              # never answers while the test looks: the route case
            return
        if path == "/js/util.js":
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class S(http.server.ThreadingHTTPServer):
    daemon_threads = True


s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = S(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
br = Browser()


def screen(mode, secs):
    """Open the page with the server in `mode`; the guard's text once it settles (it stops changing for 2 s after the
    'Checking which…' line is gone), or what it shows at `secs`."""
    MODE["m"] = mode
    tab = Tab(br)
    try:
        tab.goto("http://127.0.0.1:%d/?m=%s" % (PORT, mode))
        t0, last, same = time.time(), None, 0
        while time.time() - t0 < secs:
            time.sleep(1)
            try:
                txt = tab.ev("(document.getElementById('view') || {}).innerText || ''", timeout=10)
            except Exception:
                continue
            if txt and "Checking which" not in txt and txt == last:
                same += 1
                if same >= 2:
                    return txt
            else:
                same = 0
            last = txt
        return last or ""
    finally:
        tab.close()


try:
    print("\n[1] nothing answers (an exit or a route took the packets): a connection problem, not an update")
    t = screen("hang", 45)
    check("it says the files did not arrive", "files didn't arrive" in t, t or "(blank)")
    check("it names the connection and a VPN interface's exit or rule", "connection between this device and the panel" in t
          and "an exit or a routing rule" in t, t)
    check("it no longer tells the user to re-run the update", "re-run the update" not in t.lower()
          and "interrupted" not in t, t)

    print("\n[2] the control: one module answers 404 — that is a missing file, and the update advice stays")
    t = screen("404", 30)
    check("it names js/util.js as not loaded", "did not load" in t and "js/util.js" in t, t)
    check("it keeps the update advice", "re-run the update" in t.lower() and "interrupted or partial update" in t, t)
finally:
    STOP.set()
    br.close()
    srv.shutdown()

if PERTURB:
    print("\nperturb %s: %s" % (PERTURB, "RED (caught)" if FAILS else "GREEN — NOT caught"))
    sys.exit(0 if FAILS else 1)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
