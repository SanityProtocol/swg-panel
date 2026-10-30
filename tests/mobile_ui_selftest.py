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
  [3] a sheet takes no field's focus as it opens (no keyboard), a field's own autofocus included; swipe down closes a sheet; a dirty sheet asks "Discard?" and stays; a touch that starts on a field never closes; a sheet
      that shows a secret once ignores the swipe; on a stacked sheet only the top one goes
  [4] a sheet's footer: Cancel and Save share the bottom line, Cancel left; the other actions sit in rows above it
  [5] render gates: the Overview draws no rail, charts, doughnuts or flow map and fetches no history; Users and Peers draw no
      traffic rail
  [6] Settings opens on its list of sections, a section hides the list, its "Panel settings" line goes up to the list, the
       footer's Back leaves Settings for where it was opened from
  [7] a node's page: Check / Settings / Logs / More as labelled cells; More holds the four lifecycle doors
  [8] the device editor's role toggle shows its word on a phone (no hover for its title)
  [9] a tap on a value that only lives in a title= shows it in the bottom bubble
  [11] a tap outside an open list (the peer card's Assign to…) only closes it: nothing under the finger opens
  [10] Users: scrolled to the end, nothing of the list sits under the tab bar; a row's actions sit past its right edge and
       a swipe brings them on screen, labelled; the row shows a ⋮, and a tap on it opens the row's actions (not the row)
  [15] review F65–F85: a device's Rotate tries each credential on its own (a refused turn rotate still rotates the keypair, keeps
       the row Rotating, and the toast names what was replaced, once punctuated); a refused rekey is never called replaced; an
       accepted one whose config never reached the subscription says so, for 9 s; with the vault key not cached the outcome shows
       while the unlock prompt is open and after it is skipped; a device with nothing to rotate says so and opens no
       confirm; a group editor's Traffic → Edit group returns to that editor, not a second one; a phone's Turn IPs header opens
       its sheet, which fetches its own list, and follows the poll
  [16] the Live grid's Endpoint, phone and desktop: a csqtt or WDTT device online says "turn-proxy" in its server's fork
       colour with the "Connected via <fork>" bubble (the csqtt line named, 2.1 when none is reported); a ready one is dimmed
       and names its server with no claim it ever connected; one still being created shows the dash; an unreported server
       is "a turn-proxy"; a typeless target on a WDTT interface counts as WDTT; an AWG device still prints its address and
       a relayed WG one keeps "Last connected via"; ready with no address (never reported) and an explicitly AWG-typed
       target on a wdtt-named interface show what they did before; online, the status badge is the fork-coloured turn
       badge, but a pinned action failure still shows over it

Run: python3 tests/mobile_ui_selftest.py    (0 = pass; needs google-chrome / chromium, or $CHROME)
     --perturb-<name>  serves a copy of the SPA with one hook undone and expects RED:
                       nodetect | desktopsite | noswipe | swipeguard | swipefield | swipesecret | footorder | gate |
                       drill | nodemore | roleword | titletap | tagtap | bubdrag | bubtap | backclose | backguard | tfsearch | donetake | rotkeyed | rotpartial | rotnone | rotrekey | rotdot | rotunpub | rotlong | rotwait | rotspin | kwep | kwbadge | kwready | kwverb | kwerr | kwtyped | kwip | grpedit | tiptap | tipfetch | tiplive | rowswipe | tabpad | autofocus | nativefocus | settingsback | tapguard | dots | dotstap
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
    "rotkeyed": ("js/peer-actions.js", "const kr = hasKeyed ? await step(", "const kr = hasKeyed && !why.length ? await step("),
    "rotpartial": ("js/peer-actions.js", "toast(done.length ? T(\"Not everything", "toast(false ? T(\"Not everything"),
    "rotnone": ("js/peer-actions.js", "  if (none) return toast(", "  if (false) return toast("),
    "grpedit": ("js/sheets-crud.js", "closeModal(); if (!child) openGroup(gid);", "closeModal(); openGroup(gid);"),
    "rotrekey": ("js/peer-actions.js", 'await step(T("the keypair"), () => rotatePeerKeys(p)) : null;', 'await step(T("the keypair"), () => rotatePeerKeys(p).then(() => ({ ok: true }))) : null;'),
    "rotunpub": ("js/peer-actions.js", "        if (kr && kr.published) kr.published.then(", "        if (false) kr.published.then("),
    "rotlong": ("js/peer-actions.js", 'show it to the user from here.", { why: e.replace(/[.\\s]+$/, "") }), "err", 9000);', 'show it to the user from here.", { why: e.replace(/[.\\s]+$/, "") }), "err");'),
    "rotwait": ("js/peer-actions.js", "        await Store.poll();\n        if (why.length) return toast(", "        if (kr && kr.published) await kr.published;\n        await Store.poll();\n        if (why.length) return toast("),
    "kwbadge": ("js/ui.js", "  const kv = t.online && !t.viaTurn && !re ? keylessVia(t) : null;", "  const kv = null;"),
    "kwerr": ("js/ui.js", "  const kv = t.online && !t.viaTurn && !re ? keylessVia(t) : null;", "  const kv = t.online && !t.viaTurn ? keylessVia(t) : null;"),
    "kwtyped": ("js/ui.js", "  const k = t.type || targetType(t);", "  const k = targetType(t);"),
    "kwip": ("js/ui.js", " || (t.status === \"ready\" && !!t.ip)) ? kv : null;", " || t.status === \"ready\") ? kv : null;"),
    "kwready": ("js/ui.js", "ks = kv && (t.status === \"online\" || (t.status === \"ready\" && !!t.ip)) ? kv : null;", "ks = kv;"),
    "kwverb": ("js/ui.js", "const verb = t.online ? T(\"Connected via\") : ks ? \"\" : T(\"Last connected via\");", "const verb = t.online ? T(\"Connected via\") : T(\"Last connected via\");"),
    "kwep": ("js/ui.js", "  if (t.via === \"turn\" || ks) {", "  if (t.via === \"turn\") {"),
    "rotspin": ("js/peer-actions.js", "        if (!(kr && kr.ok)) delete Store.rotating[p.id];", "        if (!hasKeyed || why.length) delete Store.rotating[p.id];"),
    "tiptap": ("js/turn.js", 'role="button" onClick=${() => pushModal(html`<${TurnIpsSheet}', 'role="button" onClick=${() => null && pushModal(html`<${TurnIpsSheet}'),
    "tipfetch": ("js/turn.js", "  useEffect(() => { load(); }, [node]);\n  const _snap", "  const _snap"),
    "tiplive": ("js/turn.js", "function useTurnIps(node, svc) {\n  useStore();\n", "function useTurnIps(node, svc) {\n"),
    "rotdot": ("js/peer-actions.js", '(srvText(r) || T("Rotate failed.")).replace(/[.\\s]+$/, "")', '(srvText(r) || T("Rotate failed."))'),
    "donetake": ("js/routing.js", "if (q.trim() && rows.length === 1) {", "if (false) {"),
    "tfsearch": ("js/routing.js", '(open && isMobile() ? " m-tfsearch" : "")', '(false ? " m-tfsearch" : "")'),
    "backguard": ("js/ui.js", "if (top && top.close) top.close(); else closeModal();", "closeModal();"),
    "backclose": ("app.js", "attachToastSwipe(); attachBackCloses(); attachViewportVars(); }", "attachToastSwipe(); attachViewportVars(); }"),
    "bubdrag": ("js/ui.js", 'if (d.dy) d.pop.style.setProperty("transform", "translateY(" + d.dy + "px)", "important");', 'if (d.dy) d.pop.style.transform = "translateY(" + d.dy + "px)";'),
    "bubtap": ("js/ui.js", "onClick=${hoverOnly && !isMobile() ? null :", "onClick=${hoverOnly ? null :"),
    "tagtap": ("js/ui.js", '    if (el.matches(".tg, .iftype, .tag, .capb, .ce-tag")) return;\n', ''),
    "titletap": ("app.js", "  if (isMobile()) { attachTitleTaps(); attachOutsideTapGuard();", "  if (isMobile()) { attachOutsideTapGuard();"),
    "tabpad": ("m/m.css", "  & .view { padding: 12px var(--m-gutter) calc(var(--m-tabbar) + var(--m-safe-b) + 28px); }\n", ""),
    "nativefocus": ("app.js", "  options.vnode = v => { const p = v.props; if (typeof v.type === \"string\" && p && p.autofocus) delete p.autofocus; if (prev) prev(v); };",
                    "  options.vnode = v => { if (prev) prev(v); };"),
    "settingsback": ("js/screen-settings.js", "<button class=\"btn btn-ghost btn-dismiss\" onClick=${leaveSettings}>${T(\"Back\")}</button>",
                     "<button class=\"btn btn-ghost btn-dismiss\" onClick=${isMobile() && section ? () => setSection(null) : leaveSettings}>${T(\"Back\")}</button>"),
    "autofocus": ("js/ui.js", "    if (first && !isMobile()) setTimeout(", "    if (first) setTimeout("),
    "tapguard": ("app.js", "attachTitleTaps(); attachOutsideTapGuard(); attachSwipePeek();", "attachTitleTaps(); attachSwipePeek();"),
    "dots": ("m/m.css", '    content: "\\22EE"; position: absolute;', '    content: none; position: absolute;'),
    "dotstap": ("js/ui.js", '  document.addEventListener("click", e => {\n    const row = e.target && e.target.closest && e.target.closest(SWIPE_ROW);',
                '  document.addEventListener("click-off", e => {\n    const row = e.target && e.target.closest && e.target.closest(SWIPE_ROW);'),
    "rowswipe": ("m/m.css", "    position: absolute; top: 0; bottom: 0; left: calc(100% + 22px); display: flex; gap: 0; scroll-snap-align: end;", "    display: flex;"),
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
    pk_spare = base64.b64encode(os.urandom(32)).decode(); PEERS[(pk_spare, "awg0")] = "10.70.0.40"
    must(call("POST", "/api/peers/create", {"pubkey": pk_spare, "title": "spare", "targets": [{"node": NID, "iface": "awg0", "ip": "10.70.0.40"}]}), "an unassigned device")
    must(sync(), "sync with the devices")
    GID = must(call("POST", "/api/groups/create", {"name": "crew", "users": [uid["anna"]]}), "group crew")["data"]["id"]
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
        tab.ev("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        ev_mod(tab, "sheets-crud", "M.openNodeEdit((await %s('store')).Store.nodes[0]); return true;" % MOD); settle(tab, 900)
        af = tab.ev("({sheet: !!document.querySelector('.overlay.show .sheet input'), focus: (document.activeElement || {}).tagName})")
        check("[3] a field that asks for autofocus (node settings' name) takes no focus on a phone", af["sheet"] and af["focus"] not in ("INPUT", "TEXTAREA", "SELECT"), af)
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
        tab.ev("try { localStorage.setItem('swg-peek', '9'); } catch (_) {}")   # the first-visit slide is not what is measured
        dt = tab.ev("(async () => { const h = document.querySelector('.urow-head'); h.scrollLeft = 0; await new Promise(r => setTimeout(r, 200));"
                    " const dots = getComputedStyle(h, '::after').content; const b = h.getBoundingClientRect(), x = b.right - 10, y = b.top + b.height / 2;"
                    " const el = document.elementFromPoint(x, y); el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: x, clientY: y}));"
                    " await new Promise(r => setTimeout(r, 900)); const row = h.closest('.urow');"
                    " return {dots, sl: h.scrollLeft, max: h.scrollWidth - h.clientWidth, body: !!row.querySelector('.urow-body'), sheet: !!document.querySelector('.overlay.show')}; })()")
        check("[10] a row with actions shows a ⋮ at its right edge", dt and "\u22ee" in (dt.get("dots") or ""), dt)
        check("[10] a tap on the ⋮ slides the row open to its actions, and neither opens the row nor a sheet",
              dt and dt["sl"] >= dt["max"] - 2 and dt["max"] > 40 and not dt["body"] and not dt["sheet"], dt)
        tab.close()

    # ── [6] the Settings drill-down ──
    with guard("[6]"):
        print("\n[6] Settings: a list of sections, then one")
        tab = open_app("#/peers")
        tab.ev("location.hash = '#/panel/settings'"); settle(tab, 900)
        st0 = tab.ev("({list: !!document.querySelector('.setbody.m-list'), rail: getComputedStyle(document.querySelector('.setrail')).display})")
        check("[6] it opens on the list of sections", st0["list"] and st0["rail"] != "none", st0)
        tab.ev("document.querySelectorAll('.setrail-i')[1].click()"); settle(tab)
        st1 = tab.ev("({back: !!document.querySelector('.m-setback'), rail: getComputedStyle(document.querySelector('.setrail')).display, cur: (document.querySelector('.m-setcur') || {}).textContent})")
        check("[6] a section hides the list and says where it is", st1["back"] and st1["rail"] == "none" and st1["cur"] == "Authentication", st1)
        tab.ev("document.querySelector('.m-setback').click()"); settle(tab)
        check("[6] the \"Panel settings\" line above it goes up to the list", tab.ev("!!document.querySelector('.setbody.m-list') && location.hash === '#/panel/settings'"))
        tab.ev("document.querySelectorAll('.setrail-i')[1].click()"); settle(tab)
        tab.ev("document.querySelector('.setfoot .btn-dismiss').click()"); settle(tab, 900)
        check("[6] the footer's Back leaves Settings for where it was opened from (Peers), as on a desktop", tab.ev("location.hash") == "#/peers", tab.ev("location.hash"))
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
        tab.ev("(() => { const e = document.createElement('span'); e.id = 'mtg'; e.className = 'tg tg-awg'; e.title = 'AmneziaWG 3.1';"
               " e.textContent = 'AWG 3.1'; e.style.cssText = 'display:inline-block;padding:10px'; document.querySelector('#view .screen').prepend(e); })()")
        tg = box(tab, "document.getElementById('mtg')")
        tap(tab, tg["x"] + tg["w"] / 2, tg["y"] + tg["h"] / 2)
        check("[9] a tag that names itself (an interface's protocol badge) opens no bubble", not tab.ev("!!document.querySelector('.deppop.m-titletap')"))
    tab.close()

    # ── [15] review F65–F85 ──
    with guard("[15]"):
        print("\n[15] a device's Rotate, a group editor's Traffic, the Turn IPs header")
        tab = open_app("#/users")
        # a keyed device that also holds a WDTT password the server refuses to rotate: the keypair still goes (F66), and the toast
        # says what was replaced (F68)
        ok = tab.ev("(async () => { const S = await %s('store'); const PA = await %s('peer-actions'); const p = S.Store.peer(%s); if (!p) return false;"
                    " const fake = Object.assign({}, p, {wdtt_password: 'x'}); const o = S.Store.peer; S.Store.peer = function (id) { return id === p.id ? fake : o.call(this, id); };"
                    " S.api.wdttPeerRotate = async () => ({ok: false, error: 'not a WDTT peer.'}); S.api.peerRekey = async b => { window.__rk = b; return {ok: true}; };"
                    " PA.rotateOnePeerKeys(fake); return true; })()" % (MOD, MOD, json.dumps(PID["anna-phone"]))); settle(tab, 700)
        check("[15] the mixed device's Rotate asks first", ok and sheets(tab) == 1)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].find(b => /Rotate credentials/.test(b.textContent) && !b.closest('.sheet-head')).click()")
        st = tab.ev("(async () => { const S = await %s('store'); const t0 = Date.now(); while (!document.querySelector('#toasts .toast') && Date.now() - t0 < 3000) await new Promise(r => setTimeout(r, 25));"
                    " return {rk: !!window.__rk, spin: !!S.Store.rotating[%s], t: [...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')}; })()"
                    % (MOD, json.dumps(PID["anna-phone"])))
        check("[15] a refused WDTT rotate still rotates the keypair", st["rk"], st)
        check("[15] …and the row stays Rotating until the new key is live (F85)", st["spin"], st)
        check("[15] …and the toast names what was already replaced", "Already replaced" in st["t"] and "keypair" in st["t"], st)
        check("[15] …each reason ending once (no '..')", st["t"] and ".." not in st["t"], st)
        close_all(tab); tab.ev("document.getElementById('toasts').replaceChildren()")
        # the panel refuses the rekey, the WDTT rotate goes through: the keypair is never called replaced (F77)
        tab.ev("(async () => { const S = await %s('store'); const PA = await %s('peer-actions');"
               " S.api.wdttPeerRotate = async () => ({ok: true}); S.api.peerRekey = async () => ({ok: false, error: 'conflict'});"
               " PA.rotateOnePeerKeys(S.Store.peer(%s)); })()" % (MOD, MOD, json.dumps(PID["anna-phone"]))); settle(tab, 700)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].find(b => /Rotate credentials/.test(b.textContent) && !b.closest('.sheet-head')).click()"); settle(tab, 3500)
        st = tab.ev("[...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')")
        check("[15] a refused rekey is named, and only the WDTT link is called replaced", "conflict" in st and "Already replaced: the WDTT link" in st and "keypair" not in st.split("Already replaced")[-1], st)
        close_all(tab); tab.ev("document.getElementById('toasts').replaceChildren()")
        # the rekey is accepted, the new config never reaches the subscription: replaced, and said why (F83)
        tab.ev("(async () => { const S = await %s('store'); const PA = await %s('peer-actions'); const C = await %s('crypto');"
               " try { sessionStorage.setItem('swg_ck', btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))); } catch (_) {}"
               " const sv = S.api.subVault; S.api.subVault = async () => ({ok: true, data: {exists: true}}); await C.subBootRestore(); S.api.subVault = sv; S.api.subEscrow = async () => ({ok: false, error: 'no'});"
               " S.api.wdttPeerRotate = async () => ({ok: true}); S.api.csqttPeerRotate = async () => ({ok: true}); S.api.peerRekey = async () => ({ok: true});"
               " PA.rotateOnePeerKeys(S.Store.peer(%s)); })()" % (MOD, MOD, MOD, json.dumps(PID["anna-phone"]))); settle(tab, 700)
        tab.ev("new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.dataset) n.dataset.at = Date.now(); }))).observe(document.getElementById('toasts'), {childList: true})")
        tab.ev("(async () => { const S = await %s('store'); Object.defineProperty(S.Store, 'storeMode', {get: () => 'encrypted', set() {}, configurable: true});"
               " [...document.querySelectorAll('.overlay.show .sheet button')].find(b => /Rotate (credentials|keys)/.test(b.textContent) && !b.closest('.sheet-head')).click(); })()" % MOD); settle(tab, 3500)
        st = tab.ev("[...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')")
        check("[15] an accepted rekey whose config was not published says so in a toast of its own", "keypair was replaced, but its config wasn't published" in st and "only in this tab" in st, st)
        check("[15] …beside the rotate's own outcome, not as a partial rotate", "rotated" in st and "Not everything" not in st, st)
        # it asks the operator to act, so it stays up 9 s like a routing save's warning — the default 5.5 s is gone by 7 s (F93)
        st = tab.ev("(async () => { const el = [...document.querySelectorAll('#toasts .toast')].find(t => /only in this tab/.test(t.textContent)); if (!el || !el.dataset.at) return 'no toast';"
                    " const w = +el.dataset.at + 7000 - Date.now(); if (w > 0) await new Promise(r => setTimeout(r, w)); return el.isConnected && !el.classList.contains('out'); })()")
        check("[15] …and it is still up 7 s after it appeared (9 s, F93)", st is True, st)
        close_all(tab); tab.close()
        # the vault key is NOT cached: the rekey's publish opens the unlock prompt, and the rotate's outcome is shown while that
        # prompt is open and stays after it is skipped — it never waits on the prompt (F86, F92)
        tab = open_app("#/users")
        tab.ev("(async () => { const S = await %s('store'); const PA = await %s('peer-actions');"
               " S.api.wdttPeerRotate = async () => ({ok: true}); S.api.csqttPeerRotate = async () => ({ok: true}); S.api.peerRekey = async () => ({ok: true});"
               " Object.defineProperty(S.Store, 'storeMode', {get: () => 'encrypted', set() {}, configurable: true});"
               " PA.rotateOnePeerKeys(S.Store.peer(%s)); })()" % (MOD, MOD, json.dumps(PID["anna-phone"]))); settle(tab, 700)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].find(b => /Rotate (credentials|keys)/.test(b.textContent) && !b.closest('.sheet-head')).click()"); settle(tab, 2500)
        st = tab.ev("(async () => { const C = await %s('crypto'); return {cached: !!C.subSKCached(),"
                    " prompt: [...document.querySelectorAll('.overlay.show .sheet')].some(s => /Unlock to publish this config/.test(s.textContent)),"
                    " t: [...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')}; })()" % MOD)
        check("[15] with the vault key not cached, the rekey's publish asks to unlock it", not st["cached"] and st["prompt"], st)
        check("[15] …and the rotate's outcome is already shown while that prompt is open (F92)", "rotated" in st["t"], st)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].find(b => b.textContent.trim() === 'Skip').click()"); settle(tab, 800)
        st = tab.ev("({prompt: [...document.querySelectorAll('.overlay.show .sheet')].some(s => /Unlock to publish this config/.test(s.textContent)),"
                    " t: [...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')})")
        check("[15] …and after it is skipped: still shown, no partial rotate, no publish error", not st["prompt"] and "rotated" in st["t"] and "Not everything" not in st["t"] and "keypair was replaced, but" not in st["t"], st)
        close_all(tab); tab.close()
        tab = open_app("#/users")
        # nothing to rotate: no confirm, no "rotated" (F67)
        tab.ev("(async () => { const PA = await %s('peer-actions'); PA.rotateOnePeerKeys({id: 'mnone', targets: []}); })()" % MOD); settle(tab, 600)
        st = tab.ev("({n: document.querySelectorAll('.overlay.show .sheet').length, t: [...document.querySelectorAll('#toasts .toast')].map(t => t.textContent).join(' | ')})")
        check("[15] a device with nothing to rotate opens no confirm and says so", st["n"] == 0 and "nothing to rotate" in st["t"], st)
        tab.close()
        # a group editor → Traffic → Edit group: back to that editor, one sheet (F65)
        tab = open_app("#/users")
        ev_mod(tab, "peer-ui", "M.openGroup(%s); return true;" % json.dumps(GID)); settle(tab, 700)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].find(b => b.textContent.trim() === 'Traffic').click()"); settle(tab, 800)
        n2 = sheets(tab)
        tab.ev("[...document.querySelectorAll('.overlay.show .sheet button')].reverse().find(b => /Edit group/.test(b.textContent)).click()"); settle(tab, 800)
        check("[15] Traffic opens over the group editor", n2 == 2, n2)
        check("[15] its Edit group returns to that editor — no second one over it", sheets(tab) == 1, sheets(tab))
        close_all(tab); tab.close()
        # a phone's Turn IPs header: its tap opens the sheet, which fetches its own list (F74, F75), and it follows the poll (F78)
        tab = open_app("#/users")
        tab.ev("(async () => { const P = await %s; const S = await %s('store'); const TU = await %s('turn'); window.__tips = 0;"
               " S.api.turnIps = async () => { window.__tips++; return {ok: true, data: {nodes: {}}}; };"
               " const c = document.createElement('div'); c.id = 'mtip'; document.querySelector('#view .screen').prepend(c);"
               " P.render(P.h(TU.TurnIpsHeader, {node: %s, svc: 'swg-turn-x'}), c); })()" % (PREACT, MOD, MOD, json.dumps(NID))); settle(tab, 700)
        tab.ev("(async () => { const S = await %s('store'); S.Store.poll = async () => {}; S.Store.stats[%s] = Object.assign({}, S.Store.stats[%s], {turn_proxies: [{service: 'swg-turn-x', src_ips: ['198.51.100.7']}]}); S.Store.apply(); })()"
               % (MOD, json.dumps(NID), json.dumps(NID))); settle(tab, 300)
        live = tab.ev("document.querySelector('#mtip .turnips-hd').textContent")
        check("[15] the Turn IPs header follows the store (F78)", "· 1" in live, live)
        tab.ev("document.querySelector('#mtip .turnips-hd').click()"); settle(tab, 800)
        st = tab.ev("({n: document.querySelectorAll('.overlay.show .sheet').length, f: window.__tips})")
        check("[15] the Turn IPs header's tap opens its sheet", st["n"] == 1, st)
        check("[15] …which fetches its own list (F74, F75)", st["f"] == 2, st)
        close_all(tab); tab.close()
    # ── [16] the Live grid's Endpoint for a keyless deployment (operator, 2026-10-30) ──
    with guard("[16]"):
        print("\n[16] the Endpoint cell: a csqtt or WDTT device says turn-proxy in its server's fork colour, a WG one its address")
        for w, mob, where in ((390, True, "phone"), (1280, False, "desktop")):
            tab = open_app("#/users", w=w, h=844 if mob else 900, mobile=mob, touch=mob)
            st = tab.ev("(async () => { const P = await %s; const S = await %s('store'); const U = await %s('ui'); const TC = await %s('turn-catalog');"
                        " const nid = %s; S.Store.stats[nid] = Object.assign({}, S.Store.stats[nid], {csqtt: [{iface: 'csqk0', fork: 'csqtt', line: '2.5'}, {iface: 'csqk1', fork: 'csqtt'}],"
                        "   wdtt: [{iface: 'wdtk0', fork: 'qwdtt'}]});"
                        " const rows = [{type: 'csqtt', node: nid, iface: 'csqk0', online: true, status: 'online'}, {type: 'wdtt', node: nid, iface: 'wdtk0', online: true, status: 'online'},"
                        "               {type: 'wdtt', node: nid, iface: 'wdtk0', online: false, status: 'ready', ip: '10.66.0.5'}, {type: 'awg', node: nid, iface: 'awg0', online: true, status: 'online', observed: {endpoint: '203.0.113.7:51820'}},"
                        "               {type: 'csqtt', node: nid, iface: 'csqk0', online: false, status: 'creating'}, {type: 'csqtt', node: nid, iface: 'csqk1', online: true, status: 'online'},"
                        "               {type: 'wdtt', node: nid, iface: 'wdtk9', online: true, status: 'online'}, {node: nid, iface: 'wdtk0', online: true, status: 'online'},"
                        "               {type: 'awg', node: nid, iface: 'awg0', online: false, status: 'ready', via: 'turn', viaTurn: 'vk-turn-proxy-wingsv-56000', observed: {endpoint: '127.0.0.1:40000'}},"
                        "               {type: 'wdtt', node: nid, iface: 'wdtk0', online: false, status: 'ready', ip: ''},"
                        "               {type: 'awg', node: nid, iface: 'wdtk0', online: true, status: 'online', observed: {endpoint: '203.0.113.9:51820'}}];"
                        " const col = c => { const d = document.createElement('i'); d.style.color = c; return d.style.color; };"
                        " const out = rows.map(t => { const c = document.createElement('div'); document.body.append(c); P.render(U.endpointCell(t), c);"
                        "   const ep = c.querySelector('.turnep'), r = {text: c.querySelector('.addr').textContent, color: ep ? ep.style.color : '', off: !!(ep && ep.classList.contains('off')),"
                        "   bub: (c.querySelector('.turnbub') || {}).textContent || ''}; P.render(null, c); c.remove(); return r; });"
                        " return {out, csq: col(TC.turnColor('csqtt')), qw: col(TC.turnColor('qwdtt')), csql: TC.forkLabel('csqtt'), qwl: TC.forkLabel('qwdtt')}; })()"
                        % (PREACT, MOD, MOD, MOD, json.dumps(NID)))
            csq, wd, wdready, awg, creating, csqdef, unrep, untyped, wgoff, unreported, typedwg = st["out"]
            check("[16] %s: a csqtt device online says turn-proxy, in its fork's colour" % where, csq["text"] == "turn-proxy" and csq["color"] == st["csq"], st)
            check("[16] %s: …and its bubble names the server it came through, with the line" % where, "Connected via" in csq["bub"] and (st["csql"] + " 2.5") in csq["bub"], csq)
            check("[16] %s: a WDTT device online says turn-proxy, in its fork's colour, named in the bubble" % where,
                  wd["text"] == "turn-proxy" and wd["color"] == st["qw"] and "Connected via" in wd["bub"] and st["qwl"] in wd["bub"], [wd, st["qw"], st["qwl"]])
            check("[16] %s: ready (idle or never connected): dimmed, its server named, no claim it ever connected (F1)" % where,
                  wdready["text"] == "turn-proxy" and wdready["off"] and st["qwl"] in wdready["bub"] and "onnected" not in wdready["bub"], wdready)
            check("[16] %s: still being created: no path to name, the dash (F1)" % where, creating["text"] == "—" and not creating["bub"], creating)
            check("[16] %s: a csqtt server that reports no line is on the default one (F11)" % where, (st["csql"] + " 2.1") in csqdef["bub"], csqdef)
            check("[16] %s: a server its node does not report: turn-proxy through 'a turn-proxy' (F11)" % where, unrep["text"] == "turn-proxy" and "a turn-proxy" in unrep["bub"], unrep)
            check("[16] %s: a target with no type on a WDTT interface is read as WDTT, as its tag is (F6)" % where, untyped["text"] == "turn-proxy" and st["qwl"] in untyped["bub"], untyped)
            check("[16] %s: ready, but the server never reported it (no address): the dash (F14)" % where, unreported["text"] == "—" and not unreported["bub"], unreported)
            check("[16] %s: an explicitly AWG-typed target is never keyless, whatever its interface's name (F15)" % where, typedwg["text"] == "203.0.113.9" and not typedwg["bub"], typedwg)
            check("[16] %s: control — an AWG device still prints its address" % where, awg["text"] == "203.0.113.7" and not awg["bub"], awg)
            check("[16] %s: control — a WG peer that came through a turn-proxy, now offline, says Last connected via" % where,
                  wgoff["text"] == "turn-proxy" and wgoff["off"] and "Last connected via" in wgoff["bub"], wgoff)
            # the peer grids' status badge: online through a csqtt / WDTT server is the fork-coloured turn badge, as through a turn-proxy
            st = tab.ev("(async () => { const P = await %s; const U = await %s('ui'); const TC = await %s('turn-catalog'); const nid = %s;"
                        " const rows = [{type: 'csqtt', node: nid, iface: 'csqk0', online: true, status: 'online'}, {type: 'wdtt', node: nid, iface: 'wdtk0', online: true, status: 'online'},"
                        "               {type: 'wdtt', node: nid, iface: 'wdtk0', online: false, status: 'ready'}, {type: 'awg', node: nid, iface: 'awg0', online: true, status: 'online'},"
                        "               {type: 'awg', node: nid, iface: 'awg0', online: true, status: 'online', via: 'turn', viaTurn: 'vk-turn-proxy-wingsv-56000'},"
                        "               {type: 'wdtt', node: nid, iface: 'wdtk0', online: true, status: 'online', re: {msg: 'rig: rotate refused'}}];"
                        " const col = c => { const d = document.createElement('i'); d.style.setProperty('--x', c); return d.style.getPropertyValue('--x'); };"
                        " const out = rows.map(t => { const c = document.createElement('div'); document.body.append(c); P.render(U.gridStatusBadge(t, {status: t.status}, t.re || null), c);"
                        "   const b = c.querySelector('.badge'), r = {turn: !!(b && b.classList.contains('b-turn')), tfc: b ? b.style.getPropertyValue('--tfc').trim() : '',"
                        "   bub: (c.querySelector('.turnbub') || {}).textContent || ''}; P.render(null, c); c.remove(); return r; });"
                        " return {out, csq: col(TC.turnColor('csqtt')).trim(), qw: col(TC.turnColor('qwdtt')).trim()}; })()"
                        % (PREACT, MOD, MOD, json.dumps(NID)))
            bcsq, bwd, bwdoff, bawg, bturn, berr = st["out"]
            check("[16] %s: an online csqtt device's status badge is the turn badge, its fork's colour, naming it" % where,
                  bcsq["turn"] and bcsq["tfc"] == st["csq"] and "Connected via" in bcsq["bub"] and "2.5" in bcsq["bub"], [bcsq, st["csq"]])
            check("[16] %s: …and a WDTT one's" % where, bwd["turn"] and bwd["tfc"] == st["qw"] and "Connected via" in bwd["bub"], [bwd, st["qw"]])
            check("[16] %s: control — an offline WDTT device and a direct AWG device keep the plain badge" % where, not bwdoff["turn"] and not bawg["turn"], [bwdoff, bawg])
            check("[16] %s: control — an AWG device through a turn-proxy keeps its turn badge" % where, bturn["turn"] and "Connected via" in bturn["bub"], bturn)
            check("[16] %s: an online WDTT device with a pinned action failure shows the failure, not the turn badge (F12)" % where,
                  not berr["turn"] and "rig: rotate refused" in berr["bub"], berr)
            tab.close()
    # ── [14] a routing field's search on a phone: a mode of its own, docked to the visible page ──
    with guard("[14]"):
        print("\n[14] a routing field's search: the input pinned on top, the catalog under it, a scroll moves neither, Back closes it")
        # the rig runs no routing, so the field is the component itself (the one Settings → Network and an interface's rules use)
        tab = open_app("#/users")
        tab.ev("(async () => { const P = await %s; const R = await %s('routing'); const c = document.createElement('div'); c.id = 'mtf';"
               " c.style.cssText = 'margin-top:500px'; document.querySelector('#view .screen').append(c);"
               " P.render(P.h(R.TargetField, {row: {badges: []}, mode: 'smart', node: %s, onChange: b => { window.__tfb = b; }}), c); })()" % (PREACT, MOD, json.dumps(NID))); settle(tab, 600)
        has = tab.ev("!!document.querySelector('#mtf .tf-in')")
        check("[14] the routing field rendered", has)
        if has:
            tab.ev("(() => { const i = document.querySelector('.tfield .tf-in'); i.scrollIntoView({block: 'center'}); i.focus();"
                   " i.value = 'ya'; i.dispatchEvent(new Event('input', {bubbles: true})); })()"); settle(tab, 1200)
            r = lambda sel: tab.ev("(() => { const e = document.querySelector(%s); if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.top), Math.round(b.height), Math.round(b.width)]; })()" % json.dumps(sel))
            fbox, fpop = r(".tfield.m-tfsearch > .tf-box"), r(".catpick-pop")
            check("[14] the input is pinned to the top, the full width", bool(fbox) and fbox[0] == 0 and fbox[2] == 390, fbox)
            check("[14] the catalog fills the rest of the screen under it", bool(fpop) and fpop[0] == 64 and fpop[0] + fpop[1] >= 840, fpop)
            tab.ev("window.scrollBy(0, 300)"); settle(tab, 500)
            check("[14] a scroll moves neither", r(".catpick-pop") == fpop and r(".tfield.m-tfsearch > .tf-box") == fbox)
            tab.ev("history.back()"); settle(tab, 900)
            st = tab.ev("({pop: !!document.querySelector('.catpick-pop'), hash: location.hash})")
            check("[14] Back closes the search and keeps the page (its own history entry, the page the first in its tab)", not st["pop"] and st["hash"] == "#/users", st)
            # one result is not a choice: Done takes it and closes
            tab.ev("(() => { const i = document.querySelector('#mtf .tf-in'); i.focus(); i.value = 'telegram'; i.dispatchEvent(new Event('input', {bubbles: true})); })()"); settle(tab, 900)
            tab.ev("document.querySelector('.m-tfdone').click()"); settle(tab, 700)
            st = tab.ev("({pop: !!document.querySelector('.catpick-pop'), b: JSON.stringify(window.__tfb || null)})")
            check("[14] Done with one result takes it and closes", not st["pop"] and "telegram" in st["b"], st)
        tab.close()

    # ── [13] the phone's Back closes the top sheet, the page stays ──
    with guard("[13]"):
        print("\n[13] Back with a sheet open closes the sheet and keeps the page")
        tab = open_app("#/peers")
        tab.ev("location.hash = '#/users'"); settle(tab, 900)
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); U.openModal(P.h(U.Sheet, {title: 'On top'}, P.h('p', null, 'x'))); })()" % (PREACT, MOD)); settle(tab, 600)
        check("[13] the sheet is open", sheets(tab) == 1)
        tab.ev("history.back()"); settle(tab, 900)
        st = tab.ev("({n: document.querySelectorAll('.overlay.show .sheet').length, hash: location.hash, users: !!document.querySelector('.urows, .urow')})")
        check("[13] Back closed the sheet", st["n"] == 0, st)
        check("[13] …and the page is still the one under it", st["hash"] == "#/users" and st["users"], st)
        tab.ev("history.back()"); settle(tab, 900)
        check("[13] with nothing open, Back is the browser's", tab.ev("location.hash") == "#/peers")
        tab.close()
        # nested, and the page the first one in its tab — no earlier entry to borrow: each Back closes one
        tab = open_app("#/users")
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); U.openModal(P.h(U.Sheet, {title: 'Parent'}, P.h('p', null, 'x')));"
               " setTimeout(() => U.pushModal(P.h(U.Sheet, {title: 'Child', onBack: U.closeModal}, P.h('p', null, 'c'))), 200); })()" % (PREACT, MOD)); settle(tab, 900)
        check("[13] two sheets open, one over the other", sheets(tab) == 2)
        tab.ev("history.back()"); settle(tab, 800)
        check("[13] the first Back closes the child only", sheets(tab) == 1)
        tab.ev("history.back()"); settle(tab, 800)
        st = tab.ev("({n: document.querySelectorAll('.overlay.show .sheet').length, hash: location.hash})")
        check("[13] the second Back closes the parent, the page stays", st["n"] == 0 and st["hash"] == "#/users", st)
        # an edit in it: Back goes through the sheet's guarded close and asks, as the X, the swipe and Esc do (review F51)
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); U.openModal(P.h(U.Sheet, {title: 'Edit'}, P.h('input', {id: 'mbk'}))); })()" % (PREACT, MOD)); settle(tab, 700)
        tab.ev("(() => { const i = document.getElementById('mbk'); i.value = 'x'; i.dispatchEvent(new Event('input', {bubbles: true})); })()"); settle(tab, 200)
        tab.ev("history.back()"); settle(tab, 800)
        st = tab.ev("({n: document.querySelectorAll('.overlay.show .sheet').length, ask: !!document.querySelector('.discard-msg'), hash: location.hash})")
        check("[13] Back on an edited sheet asks before discarding it, and the sheet stays", st["n"] == 1 and st["ask"] and st["hash"] == "#/users", st)
        tab.close()

    # ── [12] a hover-only bubble on a phone: a tap's, swiped away, opened again ──
    with guard("[12]"):
        print("\n[12] a hover-only bubble: a tap opens it, a swipe down drags and closes it, the next tap opens it again")
        # the rig has no blocking stats or groups, so the bubble is the component itself: a hover-only Popover as the
        # Protection tiles and the grid chips use it, rendered into the page
        tab = open_app("#/users")
        tab.ev("(async () => { const P = await %s; const U = await %s('ui'); const c = document.createElement('div'); c.id = 'mhov';"
               " document.querySelector('#view .screen').prepend(c);"
               " P.render(P.h(U.Popover, {hoverOnly: true, cls: 'mhov-t', trigger: P.h('span', {style: 'display:inline-block;padding:16px 40px'}, 'tile')},"
               " P.h('div', {style: 'height:220px'}, 'who')), c); })()" % (PREACT, MOD)); settle(tab, 500)
        b = box(tab, "document.querySelector('.mhov-t')")
        found = ("#/users", "mhov-t") if b else None
        check("[12] the test bubble rendered", bool(found))
        if found:
            pops = "document.querySelectorAll('.deppop:not(.m-titletap)').length"
            tap(tab, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2); settle(tab, 400)
            check("[12] a tap opens it", tab.ev(pops) == 1, found)
            pb = box(tab, "document.querySelector('.deppop')")
            x0, y0 = pb["x"] + 40, pb["y"] + 14
            br.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]}, session=tab.s)
            for i in range(1, 7):
                br.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0, "y": y0 + 20 * i}]}, session=tab.s); time.sleep(0.03)
            moved = tab.ev("Math.round(document.querySelector('.deppop').getBoundingClientRect().top - %f)" % pb["y"])
            br.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}, session=tab.s); settle(tab, 700)
            check("[12] the bubble follows the finger down", moved >= 100, moved)
            check("[12] the swipe closes it", tab.ev(pops) == 0)
            tap(tab, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2); settle(tab, 400)
            check("[12] the next tap opens it again", tab.ev(pops) == 1)
            tab.close()

    # ── [11] a tap outside an open list ──
    with guard("[11]"):
        print("\n[11] a tap outside an open list only closes it")
        tab = open_app("#/peers")
        tab.ev("document.querySelector('table.peergrid .assigncell input').scrollIntoView({block: 'center'})"); settle(tab, 300)
        b = box(tab, "document.querySelector('table.peergrid .assigncell input')")
        tap(tab, b["x"] + 20, b["y"] + b["h"] / 2); settle(tab, 600)
        check("[11] the Assign to… list opens", tab.ev("!!document.querySelector('.uc-pop')"))
        c = box(tab, "[...document.querySelectorAll('table.peergrid tr.clk td.c-name')].find(e => { const r = e.getBoundingClientRect();"
                     " return !e.closest('tr').querySelector('.assigncell') && r.top > 60 && r.bottom < innerHeight - 80 && !document.querySelector('.uc-pop').contains(document.elementFromPoint(r.left + 10, r.top + r.height / 2)); })")
        tap(tab, c["x"] + 10, c["y"] + c["h"] / 2); settle(tab, 800)
        st = tab.ev("({list: !!document.querySelector('.uc-pop'), sheet: !!document.querySelector('.overlay.show .sheet'), focus: (document.activeElement || {}).tagName})")
        check("[11] a tap on another card closes the list, drops the field's focus, and opens nothing", not st["list"] and not st["sheet"] and st["focus"] != "INPUT", st)
        tap(tab, c["x"] + 10, c["y"] + c["h"] / 2); settle(tab, 800)
        check("[11] …and the next tap on it does open it", tab.ev("!!document.querySelector('.overlay.show .sheet')"))
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
