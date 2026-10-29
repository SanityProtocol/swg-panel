#!/usr/bin/env python3
"""Behavioural gate for the phone UI (docs/MOBILE-PLAN.md, 1.8.11 S13): the real SPA, served by the real swg-panel-server,
in headless Chrome over its DevTools pipe (tests/cdp_pipe.py), with a phone's viewport, screen and touch emulated.

tests/mobile_css_shape_selftest.py proves m/m.css cannot match on a desktop; this proves what the phone UI DOES — the JS hooks,
each behind isMobile(), and the layout rules they rely on. Fixture: node m-node syncing every 3 s (awg0, awg1), users anna (a
device on awg0 + awg1, one on awg0) and boris (one on awg0).

  [1] detection (the bootstrap): a touch phone gets the phone UI; a tablet, a desktop, and a phone browser showing the desktop
      site (a ~980 px layout) do not; localStorage "swg-ui" overrides it both ways
  [2] the shell: the five tabs fixed at the bottom of the screen; the header shows the brand, the live pill and More, nothing
      else; More holds its eight actions and the version line; Desktop view stores "d"; on a desktop More and Mobile view
      are hidden
  [3] a sheet takes no field's focus as it opens (no keyboard); swipe down closes a sheet; a dirty sheet asks "Discard?" and stays; a touch that starts on a field never closes; a sheet
      that shows a secret once ignores the swipe; on a stacked sheet only the top one goes
  [4] a sheet's footer: Cancel and Save share the bottom line, Cancel left; the other actions sit in rows above it
  [5] render gates: the Overview draws no rail, charts, doughnuts or flow map and fetches no history; Users and Peers draw no
      traffic rail
  [6] Settings opens on its list of sections, a section hides the list, its Back goes up to the list
  [7] a node's page: Check / Settings / Logs / More as labelled cells; More holds the four lifecycle doors
  [8] the device editor's role toggle shows its word on a phone (no hover for its title)
  [9] a tap on a value that only lives in a title= shows it in the bottom bubble
  [10] Users: scrolled to the end, nothing of the list sits under the tab bar; a row's actions sit past its right edge and
       a swipe brings them on screen, labelled

Run: python3 tests/mobile_ui_selftest.py    (0 = pass; needs google-chrome / chromium, or $CHROME)
     --perturb-<name>  serves a copy of the SPA with one hook undone and expects RED:
                       nodetect | desktopsite | noswipe | swipeguard | swipefield | swipesecret | footorder | gate |
                       drill | nodemore | roleword | titletap | rowswipe | tabpad | autofocus
"""
import base64, http.client, json, os, shutil, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

SERVER = os.path.join(ROOT, "swg-panel-server")
PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)
PERTURBS = {
    "nodetect": ("index.html", 'u=matchMedia("(pointer: coarse)").matches&&', 'u=false&&'),
    "desktopsite": ("index.html", '&&d.clientWidth<=Math.max(screen.width,screen.height)+40', ''),
    "noswipe": ("js/ui.js", "    const unswipe = isMobile() ? attachSheetSwipe(", "    const unswipe = false ? attachSheetSwipe("),
    "swipeguard": ("js/ui.js", "    if (wantsGuard()) { reset(true); close(); return; }", "    if (false) { reset(true); close(); return; }"),
    "swipefield": ("js/ui.js", 'if (t && t.closest && t.closest("input, textarea, select, [contenteditable], .ddpop")) return;', ''),
    "swipesecret": ("js/ui.js", "if (e.touches.length !== 1 || !canSwipe()) return;", "if (e.touches.length !== 1) return;"),
    "footorder": ("m/m.css", "  & :is(.sheet-foot, .editfoot) > .btn-dismiss { order: 3; grid-column: 1 / span 3; }\n", ""),
    "gate": ("js/screen-overview.js", "  const m = isMobile();\n", "  const m = false;\n"),
    "drill": ("js/screen-settings.js", '(isMobile() ? null : "display")', '"display"'),
    "nodemore": ("js/screen-nodes.js", "        ${isMobile() ? html`<button class=\"iconbtn\" data-lbl=${T(\"More\")}", "        ${false ? html`<button class=\"iconbtn\" data-lbl=${T(\"More\")}"),
    "roleword": ("js/sheets-crud.js", "<${RoleToggle} peer=${peer} t=${t} compact=${!isMobile()}/>", "<${RoleToggle} peer=${peer} t=${t} compact=${true}/>"),
    "titletap": ("app.js", "  if (isMobile()) attachTitleTaps();", "  if (false) attachTitleTaps();"),
    "tabpad": ("m/m.css", "  & .view { padding: 12px var(--m-gutter) calc(var(--m-tabbar) + var(--m-safe-b) + 28px); }\n", ""),
    "autofocus": ("js/ui.js", "    if (first && !isMobile()) setTimeout(", "    if (first) setTimeout("),
    "rowswipe": ("m/m.css", "    position: absolute; top: 0; bottom: 0; left: calc(100% + 14px); display: flex; gap: 0; scroll-snap-align: end;", "    display: flex;"),
}
assert PERTURB in (None,) + tuple(PERTURBS), "unknown perturbation %r" % PERTURB

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

class guard:
    """A check section that throws (a page that never drew what it looks for) is a FAIL of that section, not a crash: a plant
    that crashes the gate would measure nothing."""
    def __init__(self, label):
        self.label = label
    def __enter__(self):
        return self
    def __exit__(self, typ, val, tb):
        if typ is not None and issubclass(typ, Exception):
            check("%s did not run to its end — %s: %s" % (self.label, typ.__name__, str(val).split("\n")[0][:200]), False)
            return True

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

if not CHROME:
    bail("no headless Chrome (google-chrome / chromium, or $CHROME)")

WEB = ROOT
if PERTURB:
    f, old, new = PERTURBS[PERTURB]
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if src.count(old) != 1:
        bail("PERTURB %s: the anchor is not in %s exactly once (%d), so it cannot be undone" % (PERTURB, f, src.count(old)))
    WEB = tempfile.mkdtemp(prefix="mobile-perturb-")
    for item in ("js", "m", "vendor"):
        shutil.copytree(os.path.join(ROOT, item), os.path.join(WEB, item))
    for item in os.listdir(ROOT):
        p = os.path.join(ROOT, item)
        if os.path.isfile(p) and item.endswith((".html", ".js", ".css")) or item == "VERSION":
            shutil.copy(p, os.path.join(WEB, item))
    open(os.path.join(WEB, f), "w", encoding="utf-8").write(src.replace(old, new))

# ── the panel and its fixture ─────────────────────────────────────────────────────────────────────────────────────────────
D = tempfile.mkdtemp(prefix="mobile-ui-")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
json.dump({"nodes_path": D + "/state/nodes.json", "roster_path": D + "/state/users.json", "panel_settings_path": D + "/state/panel-settings.json",
           "config_dir": D + "/conf", "stats_dir": D + "/stats", "store_configs": False}, open(os.path.join(D, "fleet.json"), "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=WEB, SWG_PANEL_HOST="127.0.0.1", SWG_PANEL_PORT=str(PORT),
           SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="", SWG_NFT_CLI_ONLY="1", SWG_PANEL_UNITS="")
srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
ORIGIN = "http://127.0.0.1:%d" % PORT

def call(method, path, body=None, token=None, timeout=60):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try:
        return r.status, json.loads(raw or b"{}")
    except ValueError:
        return r.status, {}

def must(r, what):
    st, o = r
    if st != 200 or o.get("ok") is False:
        bail("fixture: %s refused — %s %s" % (what, st, json.dumps(o)[:300]))
    return o

stop = threading.Event()
br = None
try:
    for _ in range(150):
        try:
            if call("GET", "/api/state", timeout=2)[0] == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        bail("the panel never came up: " + (srv.stderr.read(2000) if srv.poll() is not None else b"").decode("utf-8", "replace"))
    node = must(call("POST", "/api/nodes/create", {"name": "m-node", "endpoint_host": "203.0.113.9"}), "node create")["data"]
    NID, TOKEN = node["id"], node["token"]
    IFACES = {"awg0": ("10.70.0", 51820), "awg1": ("10.71.0", 51821)}
    PEERS = {}                                  # (pubkey, iface) -> ip: what the node reports serving
    def snapshot():
        now = int(time.time())
        ifs = {}
        for ifn, (net, port) in IFACES.items():
            ifs[ifn] = {"peers": [{"public_key": pk, "allowed_ips": ip + "/32", "endpoint": "198.51.100.9:40000", "rx_bytes": 5000, "tx_bytes": 3000,
                                   "rx_speed": 1200, "tx_speed": 300, "last_handshake": now - 20, "handshake_age": 20, "online": True}
                                  for (pk, i), ip in PEERS.items() if i == ifn],
                        "meta": {"listen_port": port, "address": net + ".1/24", "subnet": net + ".0/24", "type": "awg",
                                 "public_key": base64.b64encode((ifn * 11)[:32].encode()).decode(), "endpoint": "203.0.113.9:%d" % port,
                                 "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}}}
        return {"hostname": "m-node", "generated_at": now, "noded_version": "1.8.10-beta", "kind": "baremetal", "interfaces": ifs,
                "turn_proxies": [], "node_ips": ["203.0.113.9"], "node_ifaces": ["eth0"], "lans": [],
                "health": {"cpu_pct": 12, "mem_used": 1 << 30, "mem_total": 4 << 30, "disk_used": 10 << 30, "disk_total": 40 << 30, "ncpu": 2, "uptime": 99999}}
    def sync():
        return call("POST", "/api/node/sync", {"snapshot": snapshot()}, token=TOKEN, timeout=120)
    must(sync(), "first sync")
    uid = {n: must(call("POST", "/api/users/create", {"name": n}), "user " + n)["data"]["id"] for n in ("anna", "boris")}
    nextip = {k: 10 for k in IFACES}
    PID = {}
    def device(user, ifns, title):
        pk = base64.b64encode(os.urandom(32)).decode()
        tg = []
        for ifn in ifns:
            ip = "%s.%d" % (IFACES[ifn][0], nextip[ifn]); nextip[ifn] += 1
            tg.append({"node": NID, "iface": ifn, "ip": ip}); PEERS[(pk, ifn)] = ip
        PID[title] = must(call("POST", "/api/peers/create", {"pubkey": pk, "title": title, "user_id": uid[user], "targets": tg}), "device " + title)["data"]["id"]
    device("anna", ["awg0", "awg1"], "anna-laptop")
    device("anna", ["awg0"], "anna-phone")
    device("boris", ["awg0"], "boris-phone")
    must(sync(), "sync with the devices")
    def keep_syncing():
        while not stop.wait(3):
            try:
                sync()
            except Exception:
                pass
    threading.Thread(target=keep_syncing, daemon=True).start()

    br = Browser()
    MOD = "(async n => import(performance.getEntriesByType('resource').map(r => r.name).find(u => new RegExp('/js/' + n + '\\\\.js\\\\?v=').test(u))))"
    PREACT = "(async () => import(performance.getEntriesByType('resource').map(r => r.name).find(u => /vendor\\/preact\\.module\\.js/.test(u))))()"
    def ev_mod(tab, module, body, timeout=30):
        return tab.ev("(async () => { const M = await %s(%s); %s })()" % (MOD, json.dumps(module), body), timeout=timeout)
    def settle(tab, ms=600):
        tab.ev("new Promise(r => setTimeout(r, %d))" % ms, timeout=10)

    def open_app(hash_="#/", w=390, h=844, mobile=True, touch=True, screen=None, ui=None, lang="en"):
        tab = Tab(br)
        sw, sh = screen or (w, h)
        br.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": mobile,
                                                       "screenWidth": sw, "screenHeight": sh}, session=tab.s)
        if touch:
            br.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=tab.s)
        br.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, session=tab.s)
        # once per tab (the tabs share one profile's storage), so a reload keeps what the page itself stored
        pre = "try { if (!sessionStorage.getItem('__mset')) { sessionStorage.setItem('__mset', '1'); localStorage.setItem('swg-lang', %s); %s } } catch (_) {}" % (json.dumps(lang),
              ("localStorage.setItem('swg-ui', %s);" % json.dumps(ui)) if ui else "localStorage.removeItem('swg-ui');")
        br.send("Page.addScriptToEvaluateOnNewDocument", {"source": pre}, session=tab.s)
        tab.goto(ORIGIN + "/" + hash_)
        for _ in range(200):
            try:
                if tab.ev("!!(window.__swgBooted && document.querySelector('#view > .screen'))"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        settle(tab, 1200)
        return tab
    def ui_of(tab):
        return tab.ev("document.documentElement.dataset.ui || ''")
    def box(tab, sel_js):
        return tab.ev("(() => { const e = %s; if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height, b: r.bottom, r: r.right}; })()" % sel_js)
    def touch_drag(tab, x, y, dx, dy, steps=8):
        br.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]}, session=tab.s)
        for i in range(1, steps + 1):
            br.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + dx * i / steps, "y": y + dy * i / steps}]}, session=tab.s)
            time.sleep(0.02)
        br.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}, session=tab.s)
        settle(tab, 600)
    def tap(tab, x, y):
        br.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]}, session=tab.s)
        br.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}, session=tab.s)
        settle(tab, 500)
    def sheets(tab):
        return tab.ev("document.querySelectorAll('.overlay.show .sheet').length")
    def swipe_sheet(tab, from_sel=".sheet-head h3"):
        b = box(tab, "[...document.querySelectorAll('.overlay.show .sheet')].pop().querySelector(%s)" % json.dumps(from_sel))
        if not b:
            return False
        touch_drag(tab, b["x"] + min(30, b["w"] / 2), b["y"] + b["h"] / 2, 0, 380)
        return True
    def close_all(tab):
        ev_mod(tab, "ui", "M.closeAllModals(); return true;"); settle(tab, 300)

    # ── [1] detection ──
    with guard("[1]"):
        print("[1] the phone UI is chosen by the device, before first paint")
        for what, kw, want in [("a touch phone (390×844)", {}, "m"),
                               ("a phone in landscape (844×390)", {"w": 844, "h": 390}, "m"),
                               ("a tablet (820×1180)", {"w": 820, "h": 1180}, ""),
                               ("a desktop (1280×800, a mouse)", {"w": 1280, "h": 800, "mobile": False, "touch": False}, ""),
                               ("a phone showing the desktop site (980 px layout, 390 px screen)", {"w": 980, "h": 1700, "screen": (390, 844)}, ""),
                               ("a desktop with swg-ui=m", {"w": 1280, "h": 800, "mobile": False, "touch": False, "ui": "m"}, "m"),
                               ("a phone with swg-ui=d", {"ui": "d"}, "")]:
            t = open_app(**kw)
            got = ui_of(t)
            check("[1] %s → %s" % (what, "phone UI" if want else "desktop UI"), got == want, got)
            t.close()

    # ── [2] the shell ──
    with guard("[2]"):
        print("\n[2] the shell")
        tab = open_app("#/")
        tb = tab.ev("(() => { const t = document.querySelector('#tabs'); const r = t.getBoundingClientRect(); return {pos: getComputedStyle(t).position, bottom: r.bottom, h: innerHeight, n: t.querySelectorAll('a').length}; })()")
        check("[2] the five tabs are fixed at the bottom of the screen", tb["pos"] == "fixed" and abs(tb["bottom"] - tb["h"]) < 1 and tb["n"] == 5, tb)
        vis = tab.ev("[...document.querySelectorAll('.appbar-right > *')].filter(e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0).map(e => e.id || e.className)")
        check("[2] the header keeps the live pill and More, nothing else of its right side", sorted(vis) == ["livepill", "more-btn"], vis)
        check("[2] the version is not in the header", tab.ev("getComputedStyle(document.querySelector('#appver')).display") == "none")
        b = box(tab, "document.querySelector('#more-btn')")
        tap(tab, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)
        items = tab.ev("[...document.querySelectorAll('.overlay.show .msheet-it')].length")
        ver = tab.ev("(document.querySelector('.overlay.show .msheet-ver') || {}).textContent || ''")
        check("[2] More holds its eight actions and the version line", items == 8 and "beta" in ver, (items, ver[:80]))
        tab.ev("setTimeout(() => [...document.querySelectorAll('.overlay.show .msheet-it')].find(b => /Desktop view/.test(b.textContent)).click(), 50), true")
        time.sleep(1.0)
        for _ in range(100):                           # it reloads: evaluating into a page mid-navigation throws
            try:
                if tab.ev("!!(window.__swgBooted && document.querySelector('#view > .screen'))"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        check("[2] Desktop view stores swg-ui=d and reloads into the desktop UI", tab.ev("localStorage.getItem('swg-ui')") == "d" and ui_of(tab) == "", ui_of(tab))
        tab.close()
        t = open_app("#/", w=1280, h=800, mobile=False, touch=False)
        check("[2] on a desktop More and Mobile view stay hidden",
              t.ev("['more-btn', 'mview-btn'].every(id => getComputedStyle(document.getElementById(id)).display === 'none')"))
        t.close()

    # ── [3] swipe down ──
    with guard("[3]"):
        print("\n[3] swipe down to close a sheet")
        tab = open_app("#/users")
        ev_mod(tab, "peer-ui", "M.openUserEdit(Store_user()); return true;".replace("Store_user()", "(await %s('store')).Store.user(%s)" % (MOD, json.dumps(uid["boris"]))))
        settle(tab)
        swipe_sheet(tab)
        check("[3] a clean sheet closes on a swipe down", sheets(tab) == 0, sheets(tab))
        ev_mod(tab, "peer-ui", "M.openUserEdit((await %s('store')).Store.user(%s)); return true;" % (MOD, json.dumps(uid["boris"]))); settle(tab)
        check("[3] a sheet that opens takes no field's focus (no keyboard until a tap)",
              not tab.ev("!!(document.activeElement && document.activeElement.matches('input, textarea, select'))"), tab.ev("(document.activeElement || {}).tagName"))
        b = box(tab, "document.querySelector('.overlay.show .sheet input')")
        touch_drag(tab, b["x"] + 20, b["y"] + b["h"] / 2, 0, 380)
        check("[3] a touch that starts on a field never closes the sheet", sheets(tab) == 1, sheets(tab))
        tab.ev("(() => { const i = document.querySelector('.overlay.show .sheet input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
               " set.call(i, i.value + 'x'); i.dispatchEvent(new Event('input', {bubbles: true})); i.blur(); })()"); settle(tab, 300)
        tab.ev("(() => { const sh = document.querySelector('.overlay.show .sheet'); window.__tx = [];"
               " new MutationObserver(() => window.__tx.push(sh.style.transform)).observe(sh, {attributes: true, attributeFilter: ['style']}); })()")
        swipe_sheet(tab)
        tx = tab.ev("window.__tx")
        check("[3] a dirty sheet springs back — it never leaves the screen", bool(tx) and not any("100%" in x for x in tx), tx)
        check("[3] a dirty sheet asks Discard? and stays", sheets(tab) == 1 and "Discard unsaved changes?" in (tab.ev("(document.querySelector('.overlay.show .discard-msg') || {}).textContent || ''")),
              (sheets(tab), tab.ev("(document.querySelector('.overlay.show .discard-msg') || {}).textContent || ''")))
        close_all(tab)
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); U.openModal(P.h(U.Sheet, {title: 'Shown once', noSwipe: true}, P.h('p', null, 'secret'))); })()" % (PREACT, MOD)); settle(tab)
        swipe_sheet(tab)
        check("[3] a sheet that shows a secret once ignores the swipe", sheets(tab) == 1, sheets(tab))
        close_all(tab)
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); U.openModal(P.h(U.Sheet, {title: 'Parent'}, P.h('p', null, 'p')));"
               " setTimeout(() => U.pushModal(P.h(U.Sheet, {title: 'Child', onBack: U.closeModal}, P.h('p', null, 'c'))), 200); })()" % (PREACT, MOD)); settle(tab, 900)
        swipe_sheet(tab)
        titles = tab.ev("[...document.querySelectorAll('.overlay.show .sheet-head h3')].map(h => h.textContent)")
        check("[3] on a stacked sheet only the top one goes (Back to its parent)", titles == ["Parent"], titles)
        close_all(tab)

    # ── [4] the footer rule ──
    with guard("[4]"):
        print("\n[4] a sheet's footer: the dismiss and the main action on the bottom line")
        ev_mod(tab, "sheets-crud", "M.openEditPeer((await %s('store')).Store.peer(%s)); return true;" % (MOD, json.dumps(PID["anna-laptop"]))); settle(tab, 900)
        ft = tab.ev("(() => { const f = [...document.querySelectorAll('.overlay.show .sheet-foot')].pop(); const bs = [...f.querySelectorAll(':scope > button, :scope > .btn')].filter(b => b.getBoundingClientRect().width > 0);"
                    " const r = b => b.getBoundingClientRect(); const d = f.querySelector('.btn-dismiss'), p = f.querySelector('.btn-primary');"
                    " return {d: d && {y: r(d).top, x: r(d).left, w: r(d).width}, p: p && {y: r(p).top, x: r(p).left, w: r(p).width},"
                    " others: bs.filter(b => b !== d && b !== p).map(b => r(b).top)}; })()")
        ok = ft and ft["d"] and ft["p"] and abs(ft["d"]["y"] - ft["p"]["y"]) < 1 and ft["d"]["x"] < ft["p"]["x"] and abs(ft["d"]["w"] - ft["p"]["w"]) < 2 \
             and ft["others"] and max(ft["others"]) < ft["d"]["y"]
        check("[4] Cancel and Save share the bottom line in halves, Cancel left; the other actions sit above", bool(ok), ft)
    # ── [8] the role word ──
    with guard("[8]"):
        word = tab.ev("[...document.querySelectorAll('.overlay.show .primtog')].map(b => b.textContent.trim())")
        check("[8] the device editor's role toggle shows its word", bool(word) and all(len(w) > 1 for w in word), word)
        close_all(tab)
        tab.close()

    # ── [5] render gates ──
    with guard("[5]"):
        print("\n[5] what a phone does not draw is not rendered")
        tab = open_app("#/")
        settle(tab, 1500)
        gone = tab.ev("['.dashrail', '.trends', '.donutgrid', '.fm2', '.rankcard', '.fnode-health'].filter(s => document.querySelector(s))")
        check("[5] the Overview draws no rail, charts, doughnuts, flow map, ranked lists or node health graphs", gone == [], gone)
        hist = tab.ev("performance.getEntriesByType('resource').map(r => r.name).filter(u => /history|presence/.test(u))")
        check("[5] …and fetches no history", hist == [], hist)
        kept = tab.ev("['[data-sec=attention]', '.statgrid', '.fleet2', '.actlist'].filter(s => !document.querySelector(s))")
        check("[5] the Overview keeps Needs attention, the tiles, the fleet and the recent activity", kept == [], kept)
        for h_ in ("#/users", "#/peers"):
            tab.ev("location.hash = %s" % json.dumps(h_)); settle(tab, 1200)
            check("[5] %s draws no traffic rail" % h_, not tab.ev("!!document.querySelector('.trafficrail')"))
    # ── [10] the row swipe ──
    with guard("[10]"):
        tab.ev("location.hash = '#/users'"); settle(tab, 1200)
        # a phone with a home indicator: headless Chrome has no safe-area inset, so the check gives the page one (40 px)
        tab.ev("document.documentElement.style.setProperty('--m-safe-b', '40px'); window.scrollTo(0, document.documentElement.scrollHeight)"); settle(tab, 400)
        ub = tab.ev("(() => { const t = document.querySelector('#tabs').getBoundingClientRect().top; const els = [...document.querySelectorAll('#view .screen > *')]"
                    ".filter(e => e.getBoundingClientRect().height > 0 && getComputedStyle(e).position !== 'fixed'); return {tabs: t, last: els.length ? els[els.length - 1].getBoundingClientRect().bottom : null}; })()")
        check("[10] scrolled to the end, nothing of the list sits under the tab bar (with a 40 px home-indicator inset)", ub["last"] is not None and ub["last"] <= ub["tabs"] + 0.5, ub)
        pad = tab.ev("(() => { const v = parseFloat(getComputedStyle(document.querySelector('#view')).paddingBottom); const t = document.querySelector('#tabs').getBoundingClientRect(); return {pad: v, bar: t.height}; })()")
        check("[10] …the view's bottom padding clears the tab bar and the inset, whatever the list's length", pad["pad"] >= pad["bar"], pad)
        tab.ev("document.documentElement.style.removeProperty('--m-safe-b'); window.scrollTo(0, 0)"); settle(tab, 300)
        rw = tab.ev("(() => { const h = document.querySelector('.urow-head'), a = h.querySelector('.u-acts'); const vw = innerWidth;"
                    " const before = a.getBoundingClientRect().left; h.scrollLeft = 9999; const r = a.getBoundingClientRect();"
                    " const lbl = [...a.querySelectorAll('.iconbtn')].map(b => getComputedStyle(b, '::after').content);"
                    " h.scrollLeft = 0; return {before, after: r.left, right: r.right, vw, lbl}; })()")
        check("[10] a user row's actions sit past its right edge, and a swipe brings them on screen, labelled",
              rw and rw["before"] >= rw["vw"] - 20 and rw["right"] <= rw["vw"] and all(l not in ("none", "normal", '""') for l in rw["lbl"]), rw)
        tab.close()

    # ── [6] the Settings drill-down ──
    with guard("[6]"):
        print("\n[6] Settings: a list of sections, then one")
        tab = open_app("#/panel/settings")
        st0 = tab.ev("({list: !!document.querySelector('.setbody.m-list'), rail: getComputedStyle(document.querySelector('.setrail')).display})")
        check("[6] it opens on the list of sections", st0["list"] and st0["rail"] != "none", st0)
        tab.ev("document.querySelectorAll('.setrail-i')[1].click()"); settle(tab)
        st1 = tab.ev("({back: !!document.querySelector('.m-setback'), rail: getComputedStyle(document.querySelector('.setrail')).display, cur: (document.querySelector('.m-setcur') || {}).textContent})")
        check("[6] a section hides the list and says where it is", st1["back"] and st1["rail"] == "none" and st1["cur"] == "Authentication", st1)
        tab.ev("document.querySelector('.setfoot .btn-dismiss').click()"); settle(tab)
        check("[6] its Back goes up to the list", tab.ev("!!document.querySelector('.setbody.m-list') && location.hash === '#/panel/settings'"))
        tab.close()

    # ── [7] the node's page ──
    with guard("[7]"):
        print("\n[7] a node's page")
        tab = open_app("#/node/" + NID)
        cells = tab.ev("[...document.querySelectorAll('.dh-ver > .iconbtn')].map(b => b.dataset.lbl)")
        check("[7] Check, Settings, Logs and More as labelled cells", cells == ["Check", "Settings", "Logs", "More"], cells)
        tab.ev("[...document.querySelectorAll('.dh-ver > .iconbtn')].find(b => b.dataset.lbl === 'More').click()"); settle(tab)
        rows = tab.ev("[...document.querySelectorAll('.overlay.show .msheet-it')].map(b => b.textContent.trim())")
        check("[7] More holds Rotate token, Migrate, Transfer and Remove", rows == ["Rotate token", "Migrate", "Transfer", "Remove node"], rows)
        close_all(tab)

    # ── [9] the title tap ──
    with guard("[9]"):
        print("\n[9] a value that only lives in a title=")
        # a value with a title and no action of its own (the mechanism is one delegated listener, whatever carries the title)
        tab.ev("(() => { const e = document.createElement('span'); e.id = 'mtt'; e.title = 'Reported by the node 3 minutes ago';"
               " e.textContent = 'v1.8.10'; e.style.cssText = 'display:inline-block;padding:10px'; document.querySelector('#view .screen').prepend(e); })()")
        tgt = box(tab, "document.getElementById('mtt')")
        tap(tab, tgt["x"] + tgt["w"] / 2, tgt["y"] + tgt["h"] / 2)
        shown = tab.ev("(document.querySelector('.deppop.m-titletap') || {}).textContent || ''")
        check("[9] a tap shows the title in the bottom bubble", shown == "Reported by the node 3 minutes ago", shown)
        b2 = box(tab, "[...document.querySelectorAll('.dh-ver > .iconbtn')].find(b => b.dataset.lbl === 'Settings')")
        tap(tab, b2["x"] + 5, b2["y"] + 5); close_all(tab)
        check("[9] a tap on a button is the button's, not a bubble's", not tab.ev("!!document.querySelector('.deppop.m-titletap')"))
    tab.close()
finally:
    stop.set()
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
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS[:8])))
    sys.exit(1)
print("ALL PASS")
