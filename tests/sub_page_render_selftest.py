#!/usr/bin/env python3
"""Behavioural harness for the subscription page: the REAL sub.js, served by the REAL swg-sub, rendered by a REAL browser.

Until this existed every sub-page fix was proven once, by hand, in a browser — and prevented nothing afterwards. Why a browser
and not a fake DOM (tests/spa_env.mjs explains the same choice for the SPA's logic): sub.js is DOM construction from end to
end, and its defects have all been in what it RENDERS for a visitor's OS and language, or in what its Start button DOES. A fake
DOM agrees with whatever it is told. Headless Chrome over --remote-debugging-pipe needs no dependency — the DevTools protocol
is NUL-delimited JSON on fds 3/4 — and the page runs under its real CSP and real WebCrypto. The payload is swg-sub's own
read_data over a fixture state whose turn catalog is swg-panel-server's turn_catalog_view(), so a catalog change reaches the
page exactly as it does in production (serve.json).

Fixture — node q-node, three deployments per device:
  Anna  laptop: csqtt1 (csqtt) · wdtt1 (WDTT, amurcanov) · awg0 (AmneziaWG) fronted by a samosvalishe turn proxy
  Boris phone:  csqtt1 · awg0 with NO turn proxy — so on an OS with no csqtt client his Turn group is empty
  operator default: csqtt on Android → La Lune (Anna/Boris), everything else ranked. The device secret is AES-GCM sealed
  under the link's fragment key the way the panel seals it; the OS and language are the page's OWN persisted choices
  (localStorage swgsub-os / swgsub-lang, what its selectors write).

  [0] harness: the page renders, the sealed secret decrypts (the AWG cell carries a config), each OS/language took effect
  [1] csqtt: a cell on every OS a csqtt client ships for, NONE on macOS (no client exists there — P3-C's dead-end cell),
      and a subscription whose only turn-family deployment is hidden shows no Turn tab and no Turn page
  [2] the badge's author word follows the page language — " by " in EN, " от " in RU — in the csqtt, WDTT and turn cells
  [3] Start on the csqtt cell: La Lune on Android fires the csqtt:// link (one tap, like the CSQTT app — the reference, measured
      in the same run) with no import steps, and copies the link so it outlives an install detour; desktop csqtt apps (La
      Lune/FOCSQ on Linux, FOCSQ on Windows) copy the link and show the steps, firing nothing (a desktop scheme dead-ends).
      A control proves the probe SEES a scheme link fire (the WDTT cell's one-tap Android app)
  [4] the console is clean on every render (no exception, no console.error)
  [5] Connections is a desktop button only (operator, 2026-09-17). On a phone no page carries one — not the networks page
      (Cara's office router carries 192.168.50.0/24 on the node, open to everyone there), not a blocked device's page (Anna's
      old tablet) — and the networks page's heading opens the picker instead, as a device's title does. Control: the same
      subscription on a desktop window shows the one Connections button in its header

Needs google-chrome (or $CHROME) and node (seals the fixture secret). A missing browser is a FAIL, never a skip: a gate that
cannot run has not passed.

Run: python3 tests/sub_page_render_selftest.py        (0 = pass)
     --perturb-macos      serves a sub.js whose csqtt branch has no client-for-this-OS guard → RED on [1]
     --perturb-by         serves a sub.js with the badge's " by " hard-coded again → RED on [2]
     --perturb-autostart  serves a catalog where La Lune on Android does not autostart → RED on [3]
     --perturb-tabs       serves a sub.js that builds a tab for every group, page or not → RED on [1]'s Turn-tab check
     --perturb-copy       serves a sub.js whose one-tap csqtt Start no longer copies the link → RED on [3]
     --perturb-netswitch  serves a sub.js whose networks page carries a Connections button again → RED on [5]
   A perturbation prints "PERTURB OK" and exits 0 when something went red, exits 1 when nothing did — or when its anchor is
   gone (a perturbation that cannot be applied proves nothing).
"""
import base64, fcntl, hashlib, importlib.machinery, importlib.util, json, os, secrets, select, shutil, socket, subprocess, sys
import tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
P_MACOS = "--perturb-macos" in sys.argv
P_BY = "--perturb-by" in sys.argv
P_AUTO = "--perturb-autostart" in sys.argv
P_TABS = "--perturb-tabs" in sys.argv
P_COPY = "--perturb-copy" in sys.argv
P_NETSW = "--perturb-netswitch" in sys.argv
PERTURB = P_MACOS or P_BY or P_AUTO or P_TABS or P_COPY or P_NETSW

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

if not CHROME:
    bail("no Chrome/Chromium to render the page with (set $CHROME) — this gate cannot run, which is not a pass")
if not shutil.which("node"):
    bail("no node to seal the fixture secret with — this gate cannot run, which is not a pass")


from cdp_pipe import Browser, Tab   # the shared DevTools-pipe client (tests/cdp_pipe.py)


# ── the fixture state ─────────────────────────────────────────────────────────────────────────────────────────────────
def load(name, path):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    m.__dict__["__file__"] = path
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m

P = load("swgpanel_subrender", PANEL)
catalog = P.turn_catalog_view()
if P_AUTO:
    _ll = ((catalog.get("clients") or {}).get("lalune") or {}).get("platforms", {}).get("android")
    if not isinstance(_ll, dict) or not _ll.get("autostart"):
        print("PERTURB FAILED — La Lune on Android does not autostart in the catalog, so there is nothing to remove")
        sys.exit(1)
    _ll["autostart"] = False

D = tempfile.mkdtemp(prefix="subrender-")
os.makedirs(os.path.join(D, "subs", "blobs"))
os.makedirs(os.path.join(D, "stats"))
def J(rel, obj):
    with open(os.path.join(D, rel), "w") as f:
        json.dump(obj, f)

J("fleet.json", {"roster_path": D + "/users.json", "nodes_path": D + "/nodes.json", "stats_dir": D + "/stats", "sub_dir": D + "/subs"})
J("subs/serve.json", {"enabled": True, "turn_enabled": True, "turn_catalog": catalog, "wg_catalog": P.wg_catalog_view(),
                      "turn_client_default": {"csqtt": {"android": "lalune"}},
                      "languages": {"enabled": ["en", "ru"], "default": "en"}})
VK = ["https://vk.ru/call/join/AAAAbbbbCCCCddddEEEEffffGGGGhhhh1234567890", "https://vk.ru/call/join/ZZZZyyyyXXXXwwwwVVVVuuuuTTTTssss0987654321"]
J("users.json", {"users": {"u1": {"name": "Anna", "vk_links": VK}, "u2": {"name": "Boris", "vk_links": VK[:1]}, "u3": {"name": "Cara"}},
                 "peers": {
                     "p1": {"id": "p1", "user_id": "u1", "title": "laptop", "csqtt_password": "pw1csqtt", "wdtt_password": "pw1wdtt",
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "wdtt1", "type": "wdtt"},
                                        {"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.2/32"}]},
                     "p2": {"id": "p2", "user_id": "u2", "title": "phone", "csqtt_password": "pw2csqtt",
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "awg1", "type": "awg", "ip": "10.9.0.2/32"}]},
                     # [5] a router fronting a LAN, open to everyone on the node — Anna and Boris each get a networks page
                     "p3": {"id": "p3", "user_id": "u3", "title": "office router", "created_at": 1, "routes": ["192.168.50.0/24"],
                            "targets": [{"node": "n1", "iface": "awg1", "type": "awg", "ip": "10.9.0.5/32"}]},
                     # [5] a blocked device: its page is a dead end with the device's name as the picker's trigger
                     "p4": {"id": "p4", "user_id": "u1", "title": "old tablet", "disabled": True,
                            "targets": [{"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.9/32"}]}}})
J("nodes.json", {"n1": {"name": "q-node", "endpoint_host": "203.0.113.7",
                        "csqtt": {"csqtt1": {"listen": "0.0.0.0:56002"}},
                        "wdtt": {"wdtt1": {"listen": "0.0.0.0:56000", "fork": "amurcanov", "wg_port": 56001}}}})
AWG = {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}
b64 = lambda n: base64.b64encode(os.urandom(n)).decode()
J("stats/stats-n1.json", {"interfaces": {
        "awg0": {"meta": {"public_key": b64(32), "listen_port": 51820, "endpoint": "203.0.113.7:51820", "subnet": "10.8.0.0/24", "awg_params": AWG}},
        "awg1": {"meta": {"public_key": b64(32), "listen_port": 51821, "endpoint": "203.0.113.7:51821", "subnet": "10.9.0.0/24", "awg_params": AWG}}},
    "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-1", "listen": "0.0.0.0:56100", "connect": "127.0.0.1:51820", "wrap_key": "k" * 64}],
    "net_carried": ["192.168.50.0/24"]})

SEAL = r"""
const [k, pt] = process.argv.slice(1);
const key = await crypto.subtle.importKey('raw', Buffer.from(k, 'hex'), {name: 'AES-GCM'}, false, ['encrypt']);
const iv = crypto.getRandomValues(new Uint8Array(12));
const ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key, new TextEncoder().encode(pt)));
const all = new Uint8Array(12 + ct.length); all.set(iv); all.set(ct, 12);
console.log(Buffer.from(all).toString('base64'));
"""
users_sub, links = {}, {}
for uid, pid in (("u1", "p1"), ("u2", "p2")):
    key, token = os.urandom(32), secrets.token_urlsafe(24)
    sec = subprocess.run(["node", "--input-type=module", "-e", SEAL, key.hex(), json.dumps({"k": b64(32), "p": b64(32)})],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    if not sec:
        bail("could not seal the fixture secret with node")
    users_sub[uid] = {"enabled": True, "token_sha": hashlib.sha256(token.encode()).hexdigest()}
    J("subs/blobs/%s.json" % uid, {pid: {"sec": sec}})
    links[uid] = "%s#%s" % (token, base64.urlsafe_b64encode(key).decode().rstrip("="))
J("subs/users.json", users_sub)

# ── what the browser loads: the repo's page, or a perturbed copy of it ────────────────────────────────────────────────
WEB = ROOT
def perturbed_web(old, new, what):
    global WEB
    src = open(os.path.join(ROOT, "sub.js")).read()
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: its anchor is not in sub.js exactly once (%d), so the perturbation cannot be applied" % (what, src.count(old)))
        sys.exit(1)
    WEB = os.path.join(D, "web")
    os.makedirs(os.path.join(WEB, "vendor"))
    for f in ("sub.html", "sub.css", "turn-artifacts.js", "VERSION", "vendor/qrcode.js"):
        if os.path.exists(os.path.join(ROOT, f)):
            shutil.copy(os.path.join(ROOT, f), os.path.join(WEB, f))
    with open(os.path.join(WEB, "sub.js"), "w") as f:
        f.write(src.replace(old, new))

if P_MACOS:
    perturbed_web('if (!turnGetApp("csqtt")) return;', "", "the csqtt client-for-this-OS guard")
if P_TABS:
    perturbed_web("groups = groups.filter(function (m) { return firstOf[m]; });", "", "the tabs-only-for-groups-with-a-page filter")
if P_COPY:
    perturbed_web("        ctrl.copyOnOpen = true;", "", "the csqtt one-tap copy")
if P_NETSW:
    perturbed_web("""    // No Connections button either (operator, 2026-09-17): the phone layout has no per-page Connections buttons — a page's title
    // opens the picker, and here the heading does. The wide layout keeps its one button in the header.
    return page;""", """    var switchEl = el("button", "pswitch", t("connections")); switchEl.type = "button"; switchEl.hidden = true;
    switchEl.setAttribute("data-pick", "");
    page.appendChild(switchEl);
    return page;""", "the networks page without a Connections button")
if P_BY:
    perturbed_web('function tagBy(author) { return el("span", "scell-tag-by", t("by").replace("{author}", author)); }',
                  'function tagBy(author) { return el("span", "scell-tag-by", " by " + author); }', "the badge's translated author word")

sock = socket.socket(); sock.bind(("127.0.0.1", 0)); PORT = sock.getsockname()[1]; sock.close()
env = dict(os.environ, SWG_SUB_FLEET=D + "/fleet.json", SWG_SUB_WEB=WEB, SWG_SUB_HOST="127.0.0.1", SWG_SUB_PORT=str(PORT),
           SWG_SUB_TLS_DIR=D + "/no-tls")
srv = subprocess.Popen([sys.executable, SUB], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
ORIGIN = "http://127.0.0.1:%d" % PORT
for _ in range(100):
    try:
        urllib.request.urlopen(ORIGIN + "/healthz", timeout=1)
        break
    except Exception:
        time.sleep(0.1)
else:
    srv.kill()
    bail("swg-sub did not come up: " + (srv.communicate()[0] or "")[-400:])

br = Browser()

# What one render looks like, read out of the live DOM: the mode tabs, and per page its cells' badge / author word / app row /
# role / payload. An `.scell` with no `.scell-tag` is a WG/AWG row, which the checks below simply don't look at.
READ = r"""(() => {
  const txt = (el, sel) => { const x = el.querySelector(sel); return x ? x.textContent : null; };
  return {
    lang: document.documentElement.lang,
    state: (document.getElementById("state") || {}).textContent || "",
    tabs: [...document.querySelectorAll(".modetab")].map(b => b.className.replace(/.*mtab-(\w+).*/, "$1")),
    pages: [...document.querySelectorAll("section.ppage")].map(pg => ({
      mode: pg.getAttribute("data-mode"),
      cells: [...pg.querySelectorAll(".scell")].map(c => ({
        tag: txt(c, ".scell-tag"), by: txt(c, ".scell-tag-by"), getapp: txt(c, ".scell-getapp"), role: txt(c, ".scell-role-if"),
        payload: txt(c, "pre.cfgtext"), fail: txt(c, ".cfg-fail"),
        qr: !!c.querySelector(".qrbox img[src^='data:image']") })) })) };
})()"""

def render(uid, os_, lang, phone=False, desktop=False):
    """Load `uid`'s subscription as a visitor on `os_` reading `lang`, the way the page's own selectors persist those. `phone`: a
    390×844 touch viewport (the narrow layout); `desktop`: 1280×800 (the wide one, whose header carries the Connections button)."""
    tab = Tab(br)
    if phone or desktop:
        tab.br.send("Emulation.setDeviceMetricsOverride", dict({"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True} if phone
                    else {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False}), session=tab.s)
    tab.goto(ORIGIN + "/healthz")                       # same origin, so the page's localStorage can be seeded before it loads
    for _ in range(50):
        if tab.ev("location.href").startswith(ORIGIN):
            break
        time.sleep(0.1)
    tab.ev("localStorage.setItem('swgsub-os', %s); localStorage.setItem('swgsub-lang', %s); true" % (json.dumps(os_), json.dumps(lang)))
    # Record what Start hands to the clipboard, and every navigation the page asks for (a scheme link included), before
    # sub.js runs — Page.addScriptToEvaluateOnNewDocument installs it into the document the next navigation creates.
    tab.br.send("Page.addScriptToEvaluateOnNewDocument", {"source": r"""
      try { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: t => { try { __swgClip(String(t)); } catch (_) {} return Promise.resolve(); } } }); } catch (_) {}
    """}, session=tab.s)
    tab.goto(ORIGIN + "/" + links[uid])
    out, deadline = None, time.time() + 40
    while time.time() < deadline:
        try:
            out = tab.ev(READ)
        except Exception:
            out = None
        if out and out["pages"] and all(c["tag"] is not None or c["payload"] or c["fail"] for p in out["pages"] if p["mode"] not in ("nets", "dead") for c in p["cells"]):
            time.sleep(0.4)                              # let the async artifact builders settle, then read the settled DOM
            out = tab.ev(READ)
            break
        time.sleep(0.2)
    return tab, out

def turn_cells(r):
    return [c for p in (r or {}).get("pages", []) if p["mode"] == "turn" for c in p["cells"]]

def console_errors(tab):
    bad = []
    for e in tab.mine("Runtime.exceptionThrown"):
        bad.append("exception: " + json.dumps(e.get("params", {}).get("exceptionDetails", {}))[:200])
    for e in tab.mine("Runtime.consoleAPICalled"):
        if e.get("params", {}).get("type") == "error":
            bad.append("console.error: " + json.dumps(e.get("params", {}).get("args", []))[:200])
    for e in tab.mine("Log.entryAdded"):
        ent = e.get("params", {}).get("entry", {})
        if ent.get("level") == "error" and "favicon" not in (ent.get("url") or ""):
            bad.append("log: %s %s" % (ent.get("source"), (ent.get("text") or "")[:160]))
    return bad

def start_on(tab, mode, badge_has):
    """Click Start on the cell of `mode` whose badge contains `badge_has`; return (clipboard writes, overlay steps, navigations)."""
    n0 = len(tab.mine("Page.frameRequestedNavigation"))
    c0 = len(tab.mine("Runtime.bindingCalled"))
    res = tab.ev(r"""(() => {
      const pg = [...document.querySelectorAll('section.ppage')].find(p => p.getAttribute('data-mode') === %s);
      if (!pg) return 'no page';
      const cells = [...pg.querySelectorAll('.scell')];
      const i = cells.findIndex(c => ((c.querySelector('.scell-tag') || {}).textContent || '').includes(%s));
      if (i < 0) return 'no cell';
      pg._seek(i, null);
      pg.querySelector('.pbtn-start').click();
      // read the steps NOW: the handler shows them synchronously, and a one-tap fallback may replace this document soon after
      return {res: 'clicked', steps: [...document.querySelectorAll('.ph-overlay .ph-step')].map(s => s.textContent)};
    })()""" % (json.dumps(mode), json.dumps(badge_has)))
    steps = res.get("steps") if isinstance(res, dict) else []
    res = res.get("res") if isinstance(res, dict) else res
    tab.br.pump(1.6)                                     # past fireDeepLink's 1 s "did the app take over" beat
    clip = [e["params"].get("payload", "") for e in tab.mine("Runtime.bindingCalled")[c0:] if e["params"].get("name") == "__swgClip"]
    navs = [e["params"].get("url", "") for e in tab.mine("Page.frameRequestedNavigation")[n0:]]
    return res, clip, steps, navs

ALL_OS = ("android", "ios", "linux", "windows", "macos")
try:
    renders = {}
    for os_ in ALL_OS:
        for lang in ("en", "ru"):
            tab, r = render("u1", os_, lang)
            renders[(os_, lang)] = r
            bad = console_errors(tab)
            check("[4] %s/%s: the console is clean" % (os_, lang), not bad, bad[:3])
            tab.close()

    # [0] the harness itself
    r = renders[("android", "en")]
    check("[0] the page rendered a Turn page and an AWG page (android/en)", r and {"turn", "awg"} <= {p["mode"] for p in r["pages"]}, r)
    awg = [c for p in (r or {}).get("pages", []) if p["mode"] == "awg" for c in p["cells"]]
    check("[0] the sealed device secret decrypted: the AWG cell draws its config QR, no failure line", awg and all(c["qr"] and not c["fail"] for c in awg), awg)
    check("[0] the language is the page's persisted choice", renders[("android", "ru")]["lang"] == "ru" and renders[("android", "en")]["lang"] == "en",
          (renders[("android", "ru")]["lang"], renders[("android", "en")]["lang"]))
    check("[0] the OS is the page's persisted choice (the csqtt app differs by OS)",
          any("La Lune" in (c["tag"] or "") for c in turn_cells(renders[("android", "en")]))
          and any("FOCSQ" in (c["tag"] or "") for c in turn_cells(renders[("windows", "en")])),
          ([c["tag"] for c in turn_cells(renders[("android", "en")])], [c["tag"] for c in turn_cells(renders[("windows", "en")])]))

    # [1] csqtt: a cell wherever a client ships, none on macOS
    for os_ in ALL_OS:
        cs = [c for c in turn_cells(renders[(os_, "en")]) if (c["role"] or "") == "CSQTT"]
        if os_ == "macos":
            check("[1] macOS: no csqtt cell — no csqtt client exists for macOS", not cs, [c["tag"] for c in cs])
        else:
            # iOS's csqtt client is anton48's VK TURN Proxy: it is handed its own vkturnproxy:// link, because it keeps only
            # the first hash of a csqtt:// one. Every other OS's csqtt app takes the csqtt:// link.
            want = "vkturnproxy://" if os_ == "ios" else "csqtt://"
            check("[1] %s: the csqtt cell is offered (%s)" % (os_, want), len(cs) == 1 and (cs[0]["payload"] or "").startswith(want), cs)
            if os_ == "ios" and len(cs) == 1 and (cs[0]["payload"] or "").startswith(want):
                _b = cs[0]["payload"].split("data=")[1]
                _st = json.loads(base64.urlsafe_b64decode(_b + "=" * (-len(_b) % 4)))["settings"]
                check("[1] ios: …in csqtt mode, carrying every VK call link", _st.get("useCsqtt") is True and len(_st.get("vkLink", "").split("\n")) >= 2, _st)
    wd = [c for c in turn_cells(renders[("macos", "en")]) if (c["role"] or "") == "WDTT"]
    check("[1] macOS: the WDTT cell stays (a WDTT client ships for every OS) — the rule hides only what has no client", len(wd) == 1, wd)
    tab, rb = render("u2", "macos", "en")
    check("[1] macOS, a device whose only turn-family deployment is csqtt: no Turn page", not turn_cells(rb) and rb["pages"], rb)
    check("[1] …and no Turn tab left pointing at nothing", "turn" not in (rb or {}).get("tabs", []), (rb or {}).get("tabs"))
    tab.close()
    tab, rb = render("u2", "android", "en")
    check("[1] control: the same device on Android has its Turn page and tab",
          len(turn_cells(rb)) == 1 and "turn" in rb["tabs"], (rb or {}).get("tabs"))
    tab.close()

    # [2] the author word, per language, in all three turn cells
    def by_words(os_, lang):
        return {(c["role"] or "?"): c["by"] for c in turn_cells(renders[(os_, lang)]) if c["by"]}
    for os_, cell, author in (("windows", "CSQTT", "luminescq"), ("linux", "WDTT", "luminescq"), ("android", "CSQTT", "Endlad2")):
        en, ru = by_words(os_, "en").get(cell), by_words(os_, "ru").get(cell)
        check("[2] %s %s cell: EN badge says ' by %s'" % (os_, cell, author), en == " by " + author, by_words(os_, "en"))
        check("[2] %s %s cell: RU badge says ' от %s', no English" % (os_, cell, author), ru == " от " + author, by_words(os_, "ru"))
    tp = [c for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if (c["role"] or "") in ("AWG", "WG") and c["by"]]
    check("[2] the turn-proxy cell's author word is translated wherever one renders (RU)", tp and all(" by " not in c["by"] for c in tp),
          [c["by"] for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if c["by"]])

    # [3] Start on the csqtt cell
    tab, _ = render("u1", "android", "en")
    res, clip, steps, navs = start_on(tab, "turn", "WDTT")
    check("[3] control: Start on a one-tap app (the WDTT cell's Android default) is SEEN firing its scheme link — the probe can pass",
          res == "clicked" and any(u.startswith("vkturnproxy://") for u in navs) and not steps, (res, navs, steps))
    tab.close()
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    serve["turn_client_default"] = {}                   # the reference: Android's own csqtt app, amurcanov's CSQTT (autostart)
    J("subs/serve.json", serve)
    tab, _ = render("u1", "android", "en")
    res, clip, steps, navs = start_on(tab, "turn", "CSQTT")
    REF = {"fires": any(u.startswith("csqtt://connect") for u in navs), "steps": bool(steps), "copies": any(c.startswith("csqtt://") for c in clip)}
    print("       reference — Android · CSQTT app Start: %s" % REF)
    check("[3] reference: the CSQTT app on Android fires csqtt:// with no import steps", res == "clicked" and REF["fires"] and not REF["steps"], (res, navs, steps))
    tab.close()
    serve["turn_client_default"] = {"csqtt": {"android": "lalune"}}
    J("subs/serve.json", serve)
    tab, _ = render("u1", "android", "en")
    res, clip, steps, navs = start_on(tab, "turn", "La Lune")
    check("[3] Android · La Lune: Start was clicked", res == "clicked", res)
    check("[3] Android · La Lune: Start fires the csqtt:// link — one tap, like the CSQTT app", any(u.startswith("csqtt://connect") for u in navs), navs)
    check("[3] Android · La Lune: no import steps are shown", not steps, steps)
    check("[3] Android · La Lune: the link is copied too, so it survives an install detour", any(c.startswith("csqtt://connect") for c in clip), clip)
    tab.close()
    tab, _ = render("u1", "linux", "en")
    res, clip, steps, navs = start_on(tab, "turn", "La Lune")
    if res == "no cell":                                 # Linux ranks FOCSQ first; La Lune there is reached through FOCSQ's cell rule below
        res, clip, steps, navs = start_on(tab, "turn", "FOCSQ")
    check("[3] Linux · desktop csqtt app: copies the link and shows the import steps", any(c.startswith("csqtt://connect") for c in clip) and steps, (res, clip, steps))
    check("[3] Linux · desktop csqtt app: fires no scheme link (it would dead-end on a desktop)", not any(u.startswith("csqtt:") for u in navs), navs)
    tab.close()
    tab, _ = render("u1", "windows", "en")
    res, clip, steps, navs = start_on(tab, "turn", "FOCSQ")
    check("[3] Windows · FOCSQ: copies the link and shows the import steps", res == "clicked" and any(c.startswith("csqtt://connect") for c in clip) and steps, (res, clip, steps))
    tab.close()

    # [5] Connections: a desktop button only
    SW = """(() => ({pages: [...document.querySelectorAll('section.ppage')].map(pg => ({mode: pg.getAttribute('data-mode'),
        pick: !!pg.querySelector('.netbox-h.pickable[role=button]')})),
      shown: [...document.querySelectorAll('.pswitch')].filter(b => !b.hidden && getComputedStyle(b).display !== 'none' && b.getBoundingClientRect().width > 0)
        .map(b => b.className)}))()"""
    def settled_sw(tab):
        got = None
        for _ in range(40):
            got = tab.ev(SW)
            if got and any(x["mode"] == "nets" for x in got["pages"]) and any(x["mode"] == "dead" for x in got["pages"]):
                break
            time.sleep(0.3)
        return got
    tab, _ = render("u1", "android", "en", desktop=True)
    dk = settled_sw(tab)
    check("[5] control — desktop: the header's one Connections button shows", dk and dk["shown"] == ["pswitch pswitch-head"], dk)
    tab.close()
    tab, _ = render("u1", "android", "en", phone=True)
    ph = settled_sw(tab)
    check("[5] Anna's subscription has its networks page and her blocked tablet's page", ph and {"nets", "dead"} <= {x["mode"] for x in ph["pages"]}, ph)
    check("[5] phone: no Connections button shows on any page — the networks page and the blocked device's included", ph and ph["shown"] == [], ph)
    check("[5] phone: the networks page's heading opens the picker, as a device's title does", ph and any(x["pick"] for x in ph["pages"] if x["mode"] == "nets"), ph)
    if ph and any(x["pick"] for x in ph["pages"] if x["mode"] == "nets"):
        tab.ev("document.querySelector('.netbox-h.pickable').click(); true")
        time.sleep(0.6)
        check("[5] …and a tap on it opens the picker", tab.ev("!!document.querySelector('.cp-overlay .cp-panel')"),
              tab.ev("[...document.body.children].map(e => e.className).slice(-4)"))
    check("[4] console clean — phone and desktop renders with a networks page", not console_errors(tab), console_errors(tab)[:3])
    tab.close()
finally:
    br.close()
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    shutil.rmtree(D, ignore_errors=True)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red" % len(FAILS)) if ok else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
