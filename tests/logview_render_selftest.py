#!/usr/bin/env python3
"""Behavioural gate for the log viewer in a REAL browser: the real SPA, served by the real swg-panel-server, in headless Chrome
over its DevTools pipe (tests/cdp_pipe.py) — q189 SPA-1 and SPA-4, both of which only show with the app's layout and its
mount/unmount order, so the text checks of tests/log_range_selftest.py could not see them.

  [1] SPA-1 — "Stop live log" stops: Settings → Logs is open and NOT started; the header's Logs button opens the full-screen
      viewer over it, and its "Stop live log (Esc)" button is pressed. Not one poll of /api/logs/live follows, and the card
      underneath says "Start live log" again. Before the fix the card kept the viewer mounted, so the stop never ran: it
      switched to "Live" and polled every 1.5 s until the operator left the screen.
      [1b] the control: the CARD's own full screen ("Leave full screen") still only leaves it — the card streams on.
  [2] SPA-4 — the level chips (Errors / Warnings / Info / Debug, with three-digit counts) are each whole on screen and the card
      fits the screen, at 360 and 390 px, in English and in Russian, in the Settings card and in the full-screen viewer —
      before the fix one row needed 380–460 px: "Debug" was cut and «Отладка» hidden, and the card ran off the screen.

Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
Run: python3 tests/logview_render_selftest.py      (0 = pass)
     --perturb-<name>  serves a copy of the SPA with one fix undone and expects RED: stopcard | chipwrap
"""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

def guarded(name, fn):
    """Run one section; a step that raises (a fix undone can leave a button missing) fails ITS check, never the whole run."""
    try:
        fn()
    except Exception as e:
        check(name + " (raised)", False, "%s: %s" % (type(e).__name__, str(e)[:300]))

if not CHROME:
    bail("no Chrome/Chromium (set $CHROME) — this gate cannot run, which is not a pass")

# ── the web root: the repo's SPA, or a copy with one fix undone ─────────────────────────────────────────────────────────────
PERTURBATIONS = {
    "stopcard": ("js/logview.js", "const closeLogOverlay = () => { if (!LV.card) { closeReq(); LV.live = false; }\n  LV.overlay = false;",
                 "const closeLogOverlay = () => {\n  LV.overlay = false;"),
    "chipwrap": ("app.css", "  .lv-levels{flex-wrap:wrap;gap:6px;border:0;border-radius:0;overflow:visible}\n"
                            "  .lv-lvb{border:1px solid var(--line-solid);border-radius:var(--r-sm)}\n", ""),
}
WEB = ROOT
if PERTURB:
    if PERTURB not in PERTURBATIONS:
        bail("unknown perturbation %r (one of: %s)" % (PERTURB, ", ".join(PERTURBATIONS)))
    f, old, new = PERTURBATIONS[PERTURB]
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: the anchor is not in %s exactly once (%d), so it cannot be undone" % (PERTURB, f, src.count(old)))
        sys.exit(1)
    WEB = tempfile.mkdtemp(prefix="logview-perturb-")
    for item in ("js", "vendor", "fonts", "img", "icons"):
        if os.path.isdir(os.path.join(ROOT, item)):
            shutil.copytree(os.path.join(ROOT, item), os.path.join(WEB, item))
    for item in os.listdir(ROOT):
        p = os.path.join(ROOT, item)
        if os.path.isfile(p) and item.endswith((".html", ".js", ".css", ".svg", ".png", ".ico", ".json", ".woff2")) or item == "VERSION":
            shutil.copy(p, os.path.join(WEB, item))
    with open(os.path.join(WEB, f), "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))

# ── the panel: no nodes, no login — the viewer's own server is the Panel ─────────────────────────────────────────────────
D = tempfile.mkdtemp(prefix="logview-render-")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
json.dump({"nodes_path": D + "/state/nodes.json", "roster_path": D + "/state/users.json",
           "panel_settings_path": D + "/state/panel-settings.json", "config_dir": D + "/conf", "stats_dir": D + "/stats",
           "store_configs": False}, open(os.path.join(D, "fleet.json"), "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=WEB, SWG_PANEL_HOST="127.0.0.1", SWG_PANEL_PORT=str(PORT),
           SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="")
srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
ORIGIN = "http://127.0.0.1:%d" % PORT

def up():
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
        c.request("GET", "/api/state"); ok = c.getresponse().status == 200; c.close()
        return ok
    except Exception:
        return False

# Every fetch the page makes, recorded before the app's own code runs (the app calls the global fetch at call time).
RECORD = """(() => { window.__calls = []; const of = window.fetch;
  window.fetch = function (u, o) { window.__calls.push({ url: String(u), method: (o && o.method) || 'GET', t: Date.now() });
                                   return of.apply(this, arguments); }; })();"""
# The measure of one chip row: each chip's px inside the card and the screen, the rows it takes, the card against the screen.
MEASURE = """(sel => { const g = document.querySelector(sel); if (!g) return null;
  g.querySelectorAll('.lv-n').forEach(n => { n.textContent = '999'; });           // three-digit counts: the widest chips
  g.scrollIntoView({block: 'center'});
  const card = g.closest('.card').getBoundingClientRect();
  const L = Math.max(0, card.left), R = Math.min(innerWidth, card.right);
  const chips = [...g.querySelectorAll('.lv-lvb')].map(b => { const r = b.getBoundingClientRect();
    const vis = Math.max(0, Math.min(r.right, R) - Math.max(r.left, L));
    const hit = document.elementFromPoint(Math.min(innerWidth - 1, r.left + r.width / 2), r.top + r.height / 2);
    return { t: b.textContent.replace(/\\s+/g, ' ').trim(), vis: Math.round(vis), w: Math.round(r.width), tap: !!hit && b.contains(hit) }; });
  return { chips, card: [Math.round(card.left), Math.round(card.right)], vw: innerWidth }; })"""

br = None
try:
    for _ in range(150):
        if up():
            break
        if srv.poll() is not None:
            bail("the panel exited: " + srv.stderr.read(2000).decode("utf-8", "replace"))
        time.sleep(0.1)
    else:
        bail("the panel never came up")
    br = Browser()

    def open_app(lang, w, h):
        tab = Tab(br)
        br.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False}, session=tab.s)
        br.send("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('swg-lang', %s); } catch (_) {}\n%s"
                                                                     % (json.dumps(lang), RECORD)}, session=tab.s)
        tab.goto(ORIGIN + "/#/panel/settings")
        for _ in range(200):
            try:
                if tab.ev("!!document.querySelector('button.setrail-i')"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        tab.ev("new Promise(r => setTimeout(r, 1200))", timeout=10)
        quiet(tab)
        tab.ev("[...document.querySelectorAll('button.setrail-i')].find(b => /^(Logs|Логи)$/.test(b.textContent.trim())).click()")
        tab.ev("new Promise(r => setTimeout(r, 1200))", timeout=10)
        quiet(tab)
        return tab

    def quiet(tab):
        """Close whatever the app opened by itself (a critical service alert on a dev box) — it would cover the viewer."""
        tab.ev("(async () => { for (let i = 0; i < 4 && document.querySelector('.overlay.show'); i++) {"
               " document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
               " await new Promise(r => setTimeout(r, 300)); } })()", timeout=10)

    def header_logs(tab):
        return tab.ev("(() => { const b = [...document.querySelectorAll('button')].find(b => /^(Logs|Логи)$/.test(b.getAttribute('aria-label') || '')"
                      " && !b.closest('.card')); if (b) b.click(); return !!b; })()")

    def wait(tab, ms):
        tab.ev("new Promise(r => setTimeout(r, %d))" % ms, timeout=ms / 1000 + 10)

    polls = lambda tab, t0: tab.ev("window.__calls.filter(c => c.t >= %d && c.method === 'GET' && c.url.includes('/api/logs/live?')).length" % t0)
    card_start = "[...document.querySelectorAll('.card.lv:not(.lv-full) button')].some(b => /Start live log|Запустить логи/.test(b.textContent))"

    # ── [1] SPA-1 ───────────────────────────────────────────────────────────────────────────────────────────────────────
    print("[1] Stop live log, with Settings → Logs open underneath")

    def sec1(tab):
        check("[1] Settings → Logs: the card is shown, not started", tab.ev(card_start), tab.ev("document.body.innerText.slice(0, 300)"))
        check("[1] the header's Logs button opens the full-screen viewer", header_logs(tab))
        wait(tab, 2500)
        lbl = tab.ev("(document.querySelector('.lv-full .lv-x') || {getAttribute: () => null}).getAttribute('aria-label')")
        t_open = tab.ev("Date.now()")
        wait(tab, 1600)
        check("[1] …which streams (it polls) and offers \"Stop live log (Esc)\"", lbl == "Stop live log (Esc)" and polls(tab, t_open - 5000) > 0,
              (lbl, polls(tab, t_open - 5000)))
        tab.ev("document.querySelector('.lv-full .lv-x').click()")
        t_stop = tab.ev("Date.now()")
        wait(tab, 4500)
        n_after = polls(tab, t_stop)
        check("[1] after Stop: not one poll of /api/logs/live in 4.5 s (before the fix: one every 1.5 s, for as long as the card stayed open)",
              n_after == 0, n_after)
        check("[1] …and the card says \"Start live log\" again, with no Live status",
              tab.ev(card_start) and not tab.ev("!!document.querySelector('.card.lv:not(.lv-full) .lv-live')"),
              tab.ev("(document.querySelector('.card.lv .lv-live') || {}).textContent || null"))
        # [1b] the control: the card's own full screen only leaves full screen — the card streams on
        tab.ev("([...document.querySelectorAll('.card.lv button')].find(b => /Start live log/.test(b.textContent)) || {click() {}}).click()")
        wait(tab, 2000)
        tab.ev("(document.querySelector('.card.lv .lv-fs') || {click() {}}).click()")
        wait(tab, 800)
        lbl2 = tab.ev("(document.querySelector('.lv-full .lv-x') || {getAttribute: () => null}).getAttribute('aria-label')")
        tab.ev("(document.querySelector('.lv-full .lv-x') || {click() {}}).click()")
        t_leave = tab.ev("Date.now()")
        wait(tab, 3500)
        check("[1b] the card's own full screen: \"Leave full screen (Esc)\" leaves it, and the started card streams on",
              lbl2 == "Leave full screen (Esc)" and polls(tab, t_leave) >= 1 and not tab.ev(card_start), (lbl2, polls(tab, t_leave)))

    tab = open_app("en", 1280, 900)
    guarded("[1]", lambda: sec1(tab))
    tab.close()

    # ── [2] SPA-4 ───────────────────────────────────────────────────────────────────────────────────────────────────────
    print("[2] the level chips on a phone")

    def sec2(tab, lang, w):
        for where, sel in (("card", ".card.lv:not(.lv-full) .lv-levels:not(.lv-rng-pre)"), ("full screen", ".lv-full .lv-levels:not(.lv-rng-pre)")):
            if where == "full screen":
                header_logs(tab)
                wait(tab, 1200)
            m = tab.ev(MEASURE + "(%s)" % json.dumps(sel))
            whole = m and len(m["chips"]) == 4 and all(c["vis"] >= c["w"] - 1 and c["tap"] for c in m["chips"])
            fits = m and m["card"][0] >= 0 and m["card"][1] <= m["vw"]
            check("[2] %s %d px, %s: all four chips whole and tappable, the card inside the screen" % (lang.upper(), w, where),
                  whole and fits, m)
        tab.ev("(document.querySelector('.lv-full .lv-x') || {click() {}}).click()")

    for lang, w in (("en", 360), ("ru", 360), ("en", 390), ("ru", 390)):
        tab = open_app(lang, w, 800)
        guarded("[2] %s %d" % (lang, w), lambda: sec2(tab, lang, w))
        tab.close()
finally:
    if br:
        br.close()
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    shutil.rmtree(D, ignore_errors=True)
    if WEB != ROOT:
        shutil.rmtree(WEB, ignore_errors=True)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d check(s) went red" % (PERTURB, len(FAILS))) if ok else "PERTURB FAILED — the fix was undone and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
