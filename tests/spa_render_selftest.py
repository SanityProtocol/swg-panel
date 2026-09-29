#!/usr/bin/env python3
"""Behavioural harness for the operator app: the REAL SPA, served by the REAL swg-panel-server, rendered by a REAL browser.

tests/spa_env.mjs gates the SPA's LOGIC under node and says plainly what it cannot: rendering, layout and events. The operator's
UI items after the 1.8.7 qualification (docs/UI-ADJUSTMENTS-SESSION-PROMPT.md) are all of that kind — which count a sheet shows,
where a bubble lands at a small window, which cursor a control wears — so they get a browser: headless Chrome over its
DevTools pipe (tests/cdp_pipe.py, no dependency), a panel on an ephemeral port with no login, and a fixture built through the
panel's OWN API (a node enrolled and syncing snapshots, users, devices, groups, access levels, Private) so the roster is shaped
exactly as the panel writes it. Views are opened by calling the app's own openers on the module instance the page loaded;
hovers are real mouse moves; the viewport is emulated.

Fixture — node q-node (enforces device access: net_deps.reach 2, syncing every 3 s), interfaces awg0 at Everyone, awg1 at
"Same user and their groups", awg2 at Nobody; users:
  tester  9 devices — awg0 ×4 (one Private) + gw (awg0, carrying 192.168.50.0/24), awg1 ×2, awg2 ×2 → 6 the group reaches
  anna    1 device on awg0 · boris 7 devices on awg0 · carol 9 devices on awg0 · p01…p10 one device each on awg0
  dora    1 device on awg2 — reachable by nobody · zed 200 devices on awg1
  groups: family = anna, tester, dora · work = boris, dora · big = zed, dora

  [B1] the group sheet counts a member's devices the group can REACH (tester: 6, not 9; dora: none), and the count opens a
       bubble naming exactly those, with the rest explained
  [B2] a capped bubble list never says "1 more": boris's 7 devices all show; carol's 9 show 6 and "+3 more", which opens
       all 9 in place and folds back; the people list (13) shows 8 and "+5 more"; and at 200 (zed, a 1024×640 window) the
       group bubble shows 6 and "+194 more", which lists all 200 scrolling inside the window
  [B3] "Add to a group": the pointing hand over the whole pill while closed (its field included), the text cursor once open;
       the hand on the button form too (a user already in every group)
  [B4] the networks count chips carry the coloured numbers only — no neutral total — in the user's sheet and the device's
       Networks window; and a count of nothing is one quiet 0, never an empty pill
  [B5] at a small window (900×520) the user configs window's footer bubble opens on screen — above its trigger — not below
       the fold; a right-aligned bubble near the left edge stays inside it too
  [B6] the node page's Local network text uses the panel's full width
  [B9] the Networks window's connection test: its button is a panel button (not the browser's), as tall as the fields beside it
  [B10] the peers grid's networks chip opens the device's Networks window — and only that, not the peer view — and its bubble
        carries a View that opens it too
  [B11] "Add to a group" is as wide as its words in English and in Russian, with the same room either side, and grows with a
        longer query
  [B12] the users grid's reach and networks chips stand at the end of the name cell, just before the Peers column
  [B13] a footer is one row of equals: in the device view and the user sheet, Block / Unassign / Delete / Rotate all keys are
        as tall as the buttons beside them, and in Russian the device view's six buttons stay on one row
  [i18n] B1's words in Russian; [console] no error or exception on any view

Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
Run: python3 tests/spa_render_selftest.py      (0 = pass)
     --perturb-<name>  serves a copy of the SPA with one fix undone and expects RED: group-count | cap | cursor | total | flip | grow | netonline | netbubble | icons | lanwidth
                       | probebtn | gwclick | pillwidth | chipsend | footsize | footwidth
"""
import base64, http.client, json, os, shutil, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

if not CHROME:
    bail("no Chrome/Chromium (set $CHROME) — this gate cannot run, which is not a pass")

# ── the web root: the repo's SPA, or a copy with one fix undone ─────────────────────────────────────────────────────────────
PERTURBATIONS = {
    "group-count": ("js/peer-ui.js", "  const devs = reachableByGroup(uid);", "  const devs = Store.peersByUser(uid).map(p => ({ peer: p, node: (p.targets[0] || {}).node, online: false }));"),
    "cap": ("js/ui.js", "export const capShown = (n, cap) => (n <= cap + 1 ? n : cap);", "export const capShown = (n, cap) => Math.min(n, cap);"),
    "cursor": ("app.css", ".usercombo.ugroup-combo,.ugroup-combo .uc-input{cursor:pointer}", ".usercombo.ugroup-combo{cursor:text}"),
    "total": ("js/sheets-crud.js", "      ${ok ? html`<span class=\"n ok\">${ok}</span>` : null}${soon ?", "      <span class=\"n all\">${ok + soon + no}</span>${ok ? html`<span class=\"n ok\">${ok}</span>` : null}${soon ?"),
    "flip": ("js/ui.js", "    const flip = ph > below && above > below;", "    const flip = false;"),
    "grow": ("js/ui.js", "      const ro = new ResizeObserver(() => place()); ro.observe(el); roRef.current = { ro, el };", "      roRef.current = { ro: { disconnect() {} }, el };"),
    "netonline": ("js/views.js", "  const online = rows.filter(netRowOnline).length;", "  const online = 0;"),
    "icons": ("app.css", ".grp-n.lit svg{color:var(--online)}\n.grp-n.lit-net svg{color:var(--brand)}", ""),
    "netbubble": ("js/peer-ui.js", "  const all = pick == null ? !anyOnline : pick;", "  const all = pick == null ? true : pick;"),
    "lanwidth": ("app.css", ".lanmsg{margin:0 0 8px;font-size:13px;color:var(--ink-2)}", ".lanmsg{margin:0 0 8px;font-size:13px;color:var(--ink-2);max-width:78ch}"),
    "probebtn": ("js/sheets-crud.js", '<button class="btn btn-ghost" disabled=${pending || !addr.trim()}', '<button class="btn" disabled=${pending || !addr.trim()}'),
    "gwclick": ("js/grids.js", 'role="button" tabIndex="0" onClick=${() => openPeerNetworks(p)}', 'role="button" tabIndex="0"'),
    "pillwidth": ("app.css", "min-width:0;width:auto;height:28px;padding:0 10px;border-radius:999px;", "min-width:0;width:170px;height:28px;padding:0 10px;border-radius:999px;"),
    "chipsend": ("app.css", ".u-name>.ucounts{margin-left:auto;margin-right:10px}", ".u-name>.ucounts{}"),
    "footsize": ("app.css", ".sheet-foot :is(.btn-danger,.btn-warn,.btn-exp),.editfoot :is(.btn-danger,.btn-warn,.btn-exp){padding:8px 13px;font-size:13px;border-radius:var(--r-sm);gap:7px}", ""),
    "footwidth": ("js/sheets-crud.js", 'width=${760} headExtra=${headExtra} subject=${{ kind: "peer", id: pid }}', 'width=${640} headExtra=${headExtra} subject=${{ kind: "peer", id: pid }}'),
}
WEB = ROOT
if PERTURB:
    if PERTURB not in PERTURBATIONS:
        bail("unknown perturbation %r (one of: %s)" % (PERTURB, ", ".join(PERTURBATIONS)))
    f, old, new = PERTURBATIONS[PERTURB]
    src = open(os.path.join(ROOT, f)).read()
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: the anchor is not in %s exactly once (%d), so it cannot be undone" % (PERTURB, f, src.count(old)))
        sys.exit(1)
    WEB = tempfile.mkdtemp(prefix="spa-perturb-")
    for item in ("js", "vendor", "fonts", "img", "icons"):
        if os.path.isdir(os.path.join(ROOT, item)):
            shutil.copytree(os.path.join(ROOT, item), os.path.join(WEB, item))
    for item in os.listdir(ROOT):
        p = os.path.join(ROOT, item)
        if os.path.isfile(p) and item.endswith((".html", ".js", ".css", ".svg", ".png", ".ico", ".json", ".woff2")) or item == "VERSION":
            shutil.copy(p, os.path.join(WEB, item))
    with open(os.path.join(WEB, f), "w") as fh:
        fh.write(src.replace(old, new))

# ── the panel ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
D = tempfile.mkdtemp(prefix="spa-render-")
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

def call(method, path, body=None, token=None, timeout=120):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try:
        return r.status, json.loads(raw or b"{}")
    except ValueError:
        return r.status, {"raw": raw[:200]}

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

    def must(r, what):
        st, o = r
        if st != 200 or not o.get("ok", True) is True:
            bail("fixture: %s refused — %s %s" % (what, st, json.dumps(o)[:300]))
        return o
    node = must(call("POST", "/api/nodes/create", {"name": "q-node", "endpoint_host": "203.0.113.7"}), "node create")["data"]
    NID, TOKEN = node["id"], node["token"]
    IFACES = {"awg0": ("10.60.0", 51820), "awg1": ("10.61.0", 51821), "awg2": ("10.62.0", 51822)}
    PEERS = {}                                  # pubkey -> (iface, ip) — what the node reports serving
    OFFLINE, NOLAN = set(), [False]             # pubkeys the node reports as long silent · the node reports no LAN
    def peer_rec(pk, ip, now):
        age = 100000 if pk in OFFLINE else 20
        return {"public_key": pk, "allowed_ips": ip + "/32", "endpoint": "198.51.100.9:40000", "rx_bytes": 1000, "tx_bytes": 1000,
                "rx_speed": 0, "tx_speed": 0, "last_handshake": now - age, "handshake_age": age, "online": pk not in OFFLINE}
    def snapshot():
        now = int(time.time())
        ifs = {}
        for ifn, (net, port) in IFACES.items():
            peers = [peer_rec(pk, ip, now) for pk, (i, ip) in PEERS.items() if i == ifn]
            ifs[ifn] = {"peers": peers, "meta": {"listen_port": port, "address": net + ".1/24", "subnet": net + ".0/24",
                        "public_key": base64.b64encode((ifn * 11)[:32].encode()).decode(), "endpoint": "203.0.113.7:%d" % port,
                        "type": "awg", "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}}}
        return {"hostname": "q-node", "generated_at": now, "noded_version": "1.8.7-beta", "kind": "baremetal", "interfaces": ifs,
                "turn_proxies": [], "node_ips": ["203.0.113.7", "192.168.1.5"], "node_ifaces": ["eth0"],
                "lans": [] if NOLAN[0] else [{"ip": "192.168.1.5", "iface": "eth0"}],
                "net_deps": {"panel": "127.0.0.1", "resolvers": ["1.1.1.1"], "resolvers_known": True, "share": 1, "carried": 1, "reach": 2},
                "net_carried": ["192.168.50.0/24", "192.168.60.0/24"], "dev_reach": {"ok": True, "ifaces": ["awg1", "awg2"]}}
    def sync():
        return call("POST", "/api/node/sync", {"snapshot": snapshot()}, token=TOKEN, timeout=180)
    must(sync(), "first sync")
    must(call("POST", "/api/iface/update", {"node": NID, "iface": "awg0", "reach": "everyone"}), "awg0 → Everyone")
    must(call("POST", "/api/iface/update", {"node": NID, "iface": "awg2", "reach": "none"}), "awg2 → Nobody")
    uid = {}
    for name in ["tester", "anna", "boris", "carol", "dora", "zed"] + ["p%02d" % i for i in range(1, 11)]:
        uid[name] = must(call("POST", "/api/users/create", {"name": name}), "user " + name)["data"]["id"]
    nextip = {k: 10 for k in IFACES}
    PID, PK = {}, {}
    def device(user, ifn, title, private=False, routes=None):
        pk = base64.b64encode(os.urandom(32)).decode()
        net = IFACES[ifn][0]; ip = "%s.%d" % (net, nextip[ifn]); nextip[ifn] += 1
        o = must(call("POST", "/api/peers/create", {"pubkey": pk, "title": title, "user_id": uid[user], "targets": [{"node": NID, "iface": ifn, "ip": ip}]}),
                 "device " + title)
        pid = o["data"]["id"]; PID[title] = pid; PEERS[pk] = (ifn, ip); PK[title] = pk
        if private or routes:
            body = {"peer_id": pid}
            if private: body["private"] = True
            if routes: body["routes"] = routes
            must(call("POST", "/api/peers/update", body), "update " + title)
        return pid
    for i in range(4):
        device("tester", "awg0", "tester e%d" % i, private=(i == 3))
    for i in range(2):
        device("tester", "awg1", "tester u%d" % i)
    for i in range(2):
        device("tester", "awg2", "tester n%d" % i)
    device("tester", "awg0", "gw", routes=["192.168.50.0/24"])
    device("anna", "awg0", "anna phone")
    for i in range(7):
        device("boris", "awg0", "boris d%d" % i)
    for i in range(9):
        device("carol", "awg0", "carol d%d" % i)
    device("dora", "awg2", "dora phone")
    for i in range(200):                                   # "works for 2 and for 200": at "Same user and their groups", so
        device("zed", "awg1", "zed d%03d" % i)              # nobody outside zed's own group reaches them (anna's counts hold)
    for i in range(1, 11):
        device("p%02d" % i, "awg0", "p%02d phone" % i)
    device("p01", "awg0", "gw2", routes=["192.168.60.0/24"])   # a second gateway, silent from the start
    OFFLINE.add(PK["gw2"])
    GID = {}
    GID["family"] = must(call("POST", "/api/groups/create", {"name": "family", "users": [uid["anna"], uid["tester"], uid["dora"]]}), "group family")["data"]["id"]
    GID["work"] = must(call("POST", "/api/groups/create", {"name": "work", "users": [uid["boris"], uid["dora"]]}), "group work")["data"]["id"]
    GID["big"] = must(call("POST", "/api/groups/create", {"name": "big", "users": [uid["zed"], uid["dora"]]}), "group big")["data"]["id"]
    must(sync(), "sync with every device")

    def keep_syncing():
        while not stop.wait(3):
            try:
                sync()
            except Exception:
                pass
    threading.Thread(target=keep_syncing, daemon=True).start()

    br = Browser()

    def open_app(lang="en", viewport=None):
        tab = Tab(br)
        if viewport:
            br.send("Emulation.setDeviceMetricsOverride", {"width": viewport[0], "height": viewport[1], "deviceScaleFactor": 1, "mobile": False}, session=tab.s)
        br.send("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('swg-lang', %s); } catch (_) {}" % json.dumps(lang)}, session=tab.s)
        tab.goto(ORIGIN + "/#/users")
        for _ in range(200):
            try:
                if tab.ev("!!(document.querySelector('.urow') && window.performance.getEntriesByType('resource').some(r => /peer-ui\\.js\\?v=/.test(r.name)))"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        tab.ev("new Promise(r => setTimeout(r, 1500))", timeout=10)
        return tab

    MOD = "(async n => import(performance.getEntriesByType('resource').map(r => r.name).find(u => new RegExp('/js/' + n + '\\\\.js\\\\?v=').test(u))))"
    def ev_mod(tab, module, body, timeout=30):
        return tab.ev("(async () => { const M = await %s(%s); %s })()" % (MOD, json.dumps(module), body), timeout=timeout)
    def settle(tab, ms=700):
        tab.ev("new Promise(r => setTimeout(r, %d))" % ms, timeout=10)
    def hover(tab, selector_js):
        box = tab.ev("(() => { const e = %s; if (!e) return null; e.scrollIntoView({block:'nearest'}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()" % selector_js)
        if not box:
            return False
        br.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": box[0], "y": box[1]}, session=tab.s)
        settle(tab, 600)
        return {"at": box, "under": tab.ev("(() => { const e = document.elementFromPoint(%f, %f); return e ? e.className + ' <' + (e.parentElement||{}).className : null; })()" % (box[0], box[1])),
                "on": tab.ev("document.querySelectorAll('.on').length")}
    def unhover(tab):
        br.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 2, "y": 2}, session=tab.s)
        settle(tab, 400)
    def close_modals(tab):
        ev_mod(tab, "ui", "M.closeAllModals(); return true;")
        settle(tab, 300)
    def console_bad(tab):
        bad = [json.dumps(e.get("params", {}).get("exceptionDetails", {}))[:200] for e in tab.mine("Runtime.exceptionThrown")]
        bad += [json.dumps(e.get("params", {}).get("args", []))[:200] for e in tab.mine("Runtime.consoleAPICalled") if e.get("params", {}).get("type") == "error"]
        return bad

    # ── [B1] the group sheet ────────────────────────────────────────────────────────────────────────────────────────────────
    for lang in ("en", "ru"):
        tab = open_app(lang)
        ev_mod(tab, "peer-ui", "M.openGroup(%s); return true;" % json.dumps(GID["family"]))
        settle(tab, 900)
        rows = tab.ev("[...document.querySelectorAll('.gmembers .sharegrid-r')].map(r => ({nm: r.querySelector('.nm').textContent, dev: (r.querySelector('.gmem-dev') || {}).textContent || ''}))")
        by = {r["nm"]: r["dev"] for r in (rows or [])}
        if lang == "en":
            check("[B1] tester: the group reaches 6 of 9 devices — the sheet says 6", by.get("tester") == "6 devices", rows)
            check("[B1] anna: 1 device", by.get("anna") == "1 device", rows)
            check("[B1] dora (only a device at Nobody): says none the group can reach", by.get("dora") == "none the group can reach", rows)
        else:
            check("[i18n] B1 in Russian: tester «6 устройств», dora «нет доступных группе» — no English",
                  by.get("tester") == "6 устройств" and by.get("dora") == "нет доступных группе", rows)
        if lang == "en":
            ok = hover(tab, "[...document.querySelectorAll('.gmembers .sharegrid-r')].find(r => r.querySelector('.nm').textContent === 'tester').querySelector('.gmem-dev')")
            bub = tab.ev("(() => { const b = document.querySelector('.deppop.netroute-bub'); return b ? {h: (b.querySelector('.netroute-h')||{}).textContent, devs: [...b.querySelectorAll('.rb-d b')].map(x => x.textContent.replace(/ \\(.*\\)$/, '')), foot: (b.querySelector('.foot')||{}).textContent || ''} : null; })()")
            check("[B1] hovering the count opens a bubble naming exactly the reachable devices (Private and Nobody left out)",
                  ok and bub and sorted(bub["devs"]) == sorted(["gw", "tester e0", "tester e1", "tester e2", "tester u0", "tester u1"]), bub)
            check("[B1] …and says what is not counted (3: Private, or closed to others)", bub and bub["foot"].startswith("3 devices not counted"), bub)
            unhover(tab)
        check("[console] (%s) group sheet: clean" % lang, not console_bad(tab), console_bad(tab)[:3])
        close_modals(tab)
        tab.close()

    # ── [B2 · 200] a member with 200 devices the group reaches, at a small window ───────────────────────────────────────────
    tab = open_app("en", viewport=(1024, 640))
    ev_mod(tab, "peer-ui", "M.openGroup(%s); return true;" % json.dumps(GID["big"]))
    settle(tab, 900)
    rows = tab.ev("[...document.querySelectorAll('.gmembers .sharegrid-r')].map(r => ({nm: r.querySelector('.nm').textContent, dev: (r.querySelector('.gmem-dev') || {}).textContent || ''}))")
    check("[B2·200] zed: '200 devices'", any(r["nm"] == "zed" and r["dev"] == "200 devices" for r in (rows or [])), rows)
    ok = hover(tab, "[...document.querySelectorAll('.gmembers .sharegrid-r')].find(r => r.querySelector('.nm').textContent === 'zed').querySelector('.gmem-dev')")
    def big_bubble():
        return tab.ev("""(() => { const b = document.querySelector('.deppop.netroute-bub'); if (!b) return null; const r = b.getBoundingClientRect();
          return {n: b.querySelectorAll('.rb-d').length, more: (b.querySelector('.bub-more')||{}).textContent || '', top: r.top, bottom: r.bottom,
                  vh: innerHeight, scrolls: b.scrollHeight > b.clientHeight + 1}; })()""")
    bb = big_bubble()
    check("[B2·200] the bubble shows 6 and '+194 more'", ok and bb and bb["n"] == 6 and bb["more"] == "+194 more", bb)
    if bb and bb["more"]:
        tab.ev("document.querySelector('.deppop.netroute-bub .bub-more').click()")
        settle(tab, 500)
        bb2 = big_bubble()
        check("[B2·200] '+194 more' lists all 200 inside the window, scrolling rather than running off it",
              bb2 and bb2["n"] == 200 and bb2["more"] == "show fewer" and bb2["top"] >= 0 and bb2["bottom"] <= bb2["vh"] and bb2["scrolls"], bb2)
    unhover(tab)
    check("[console] 200-device bubble: clean", not console_bad(tab), console_bad(tab)[:3])
    close_modals(tab)
    tab.close()

    # ── [B2] the users grid reach bubble, [B5] the configs window at a small window ────────────────────────────────────────
    probe = open_app("en", viewport=(800, 600))
    NARROW = probe.ev("""(() => { const r = [...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === 'anna');
      const c = r && r.querySelector('.ucounts .grp-n'); if (!c) return null; const b = c.getBoundingClientRect();
      const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return {chip: [b.left, b.right], under: e ? e.className : null, covered: !(e && c.contains(e))}; })()""")
    print("       probe — users grid at 800×600:", NARROW)
    probe.close()
    tab = open_app("en", viewport=(1400, 900))
    ok = hover(tab, "(([...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === 'anna')) || document).querySelector('.urow .un') && [...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === 'anna').querySelector('.ucounts .grp-n')")
    def reach_bubble():
        return tab.ev("""(() => { const b = document.querySelector('.deppop.netroute-bub'); if (!b) return null;
          const grps = [...b.querySelectorAll('.rb-grp')].map(g => ({u: (g.querySelector('.rb-u b')||{}).textContent, n: g.querySelectorAll('.rb-d').length,
            more: (g.querySelector('.bub-more')||{}).textContent || ''}));
          const top = [...b.children].filter(c => c.classList.contains('bub-more')).map(c => c.textContent);
          return {grps, top}; })()""")
    rb = reach_bubble()
    check("[B2] anna's reach bubble opened", ok and rb and rb["grps"],
          {"hovered": ok, "bubble": rb, "row": tab.ev("(() => { const r = [...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === 'anna'); return r ? r.querySelector('.u-name').innerHTML.slice(0, 400) : [...document.querySelectorAll('.urow .un')].map(x => x.textContent); })()")})
    if rb and rb["grps"]:
        bg = {g["u"]: g for g in rb["grps"]}
        check("[B2] 13 people → 8 shown and '+5 more' (the rule applies to the people list too)", len(rb["grps"]) == 8 and rb["top"] == ["+5 more"], rb)
        b, c = bg.get("boris"), bg.get("carol")
        check("[B2] boris, 7 devices: all 7 shown, no 'more' line (never '1 more')", b and b["n"] == 7 and not b["more"], b)
        check("[B2] carol, 9 devices: 6 shown and '+3 more'", c and c["n"] == 6 and c["more"] == "+3 more", c)
        if c:
            tab.ev("[...document.querySelectorAll('.deppop.netroute-bub .rb-grp')].find(g => (g.querySelector('.rb-u b')||{}).textContent === 'carol').querySelector('.bub-more').click()")
            settle(tab, 300)
            c2 = {g["u"]: g for g in (reach_bubble() or {}).get("grps", [])}.get("carol")
            check("[B2] '+3 more' opens all 9 in place, offering to fold back", c2 and c2["n"] == 9 and c2["more"] == "show fewer", c2)
    unhover(tab)
    check("[console] users grid: clean", not console_bad(tab), console_bad(tab)[:3])
    tab.close()

    tab = open_app("en", viewport=(900, 520))
    ev_mod(tab, "peer-ui", "M.openUserConfigs(M.__q4user || (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store.user(%s)); return true;" % json.dumps(uid["anna"]))
    settle(tab, 1000)
    ok = hover(tab, "document.querySelector('.qrfoot-ucounts .grp-n')")
    geo = tab.ev("(() => { const b = document.querySelector('.deppop.netroute-bub'), t = document.querySelector('.qrfoot-ucounts .grp-n'); if (!b || !t) return null; const r = b.getBoundingClientRect(), q = t.getBoundingClientRect(); return {vh: innerHeight, vw: innerWidth, top: r.top, bottom: r.bottom, left: r.left, right: r.right, trig: q.top}; })()")
    check("[B5] 900×520: the configs window's footer bubble opened", ok and geo, geo)
    check("[B5] …wholly on screen (top ≥ 0, bottom ≤ the viewport)", geo and geo["top"] >= 0 and geo["bottom"] <= geo["vh"] + 0.5 and geo["left"] >= 0 and geo["right"] <= geo["vw"] + 0.5, geo)
    check("[B5] …above its trigger, which sits at the bottom", geo and geo["bottom"] <= geo["trig"] + 0.5, geo)
    unhover(tab)
    check("[console] configs window at 900×520: clean", not console_bad(tab), console_bad(tab)[:3])
    tab.close()

    # ── [B3] the add-to-group control, [B4] the networks chips ────────────────────────────────────────────────────────────
    tab = open_app("en")
    ev_mod(tab, "peer-ui", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; M.openUserEdit(S.user(%s)); return true;" % json.dumps(uid["anna"]))
    settle(tab, 900)
    cur = tab.ev("(() => { const w = document.querySelector('.ugroup-combo'), i = w && w.querySelector('.uc-input'); return w ? {pill: getComputedStyle(w).cursor, field: getComputedStyle(i).cursor} : null; })()")
    check("[B3] groups left to join: the pointing hand over the pill AND its field", cur and cur["pill"] == "pointer" and cur["field"] == "pointer", cur)
    tab.ev("document.querySelector('.ugroup-combo .uc-input').click()")
    settle(tab, 300)
    cur2 = tab.ev("(() => { const w = document.querySelector('.ugroup-combo'); return w ? {open: w.classList.contains('open'), field: getComputedStyle(w.querySelector('.uc-input')).cursor, list: !!document.querySelector('.uc-list.uc-groups')} : null; })()")
    check("[B3] …once open, the text cursor in the field (it takes typing)", cur2 and cur2["open"] and cur2["field"] == "text" and cur2["list"], cur2)
    close_modals(tab)
    ev_mod(tab, "peer-ui", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; M.openUserEdit(S.user(%s)); return true;" % json.dumps(uid["dora"]))
    settle(tab, 900)
    cur3 = tab.ev("(() => { const b = document.querySelector('.ugroup-add-btn'); return b ? getComputedStyle(b).cursor : null; })()")
    check("[B3] no group left (dora is in every group): the button wears the same hand", cur3 == "pointer", cur3)
    close_modals(tab)
    ev_mod(tab, "peer-ui", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; M.openUserEdit(S.user(%s)); return true;" % json.dumps(uid["tester"]))
    chips = None
    for _ in range(40):                                    # the networks list is worked out when the sheet opens
        settle(tab, 300)
        chips = tab.ev("[...document.querySelectorAll('.unets .netcount')].map(c => [...c.querySelectorAll('.n')].map(n => n.className + ':' + n.textContent))")
        if chips:
            break
    check("[B4] the user's networks: count chips render", bool(chips), chips)
    check("[B4] …carrying only coloured numbers, no neutral total", chips and all(c and not any(x.startswith("n all") for x in c) for c in chips), chips)
    close_modals(tab)
    ev_mod(tab, "sheets-crud", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; const p = S.recon.peers.find(x => x.id === %s); (M.openPeerNetworks || (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/peer-ui\\.js\\?v=/.test(u)))).openPeerNetworks)(p); return !!p;" % json.dumps(PID["gw"]))
    chips2 = None
    for _ in range(40):
        settle(tab, 300)
        chips2 = tab.ev("[...document.querySelectorAll('.netcount')].map(c => [...c.querySelectorAll('.n')].map(n => n.className + ':' + n.textContent))")
        if chips2:
            break
    check("[B4] the device's Networks window: count chips render", bool(chips2), chips2)
    check("[B4] …no neutral total there either, and never an empty pill", chips2 and all(c and not any(x.startswith("n all") for x in c) for c in chips2), chips2)
    check("[console] user sheet + Networks window: clean", not console_bad(tab), console_bad(tab)[:3])
    close_modals(tab)

    # ── [B6] the node page's Local network text ──────────────────────────────────────────────────────────────────────────
    tab.goto(ORIGIN + "/#/node/" + NID)
    lan = None
    for _ in range(40):
        settle(tab, 300)
        lan = tab.ev("(() => { const m = document.querySelector('.lanmsg'); if (!m) return null; const p = m.parentElement, cs = getComputedStyle(p); return {mw: getComputedStyle(m).maxWidth, w: m.getBoundingClientRect().width, pw: p.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)}; })()")
        if lan:
            break
    check("[B6] the node page shows its Local network panel", bool(lan), {"hash": tab.ev("location.hash"), "titles": tab.ev("[...document.querySelectorAll('.panel-title, .ptitle, h3')].map(x => x.textContent).slice(0, 12)"), "lans": tab.ev("(async () => { const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; return JSON.stringify((S.nodes || []).map(n => [n.name, n.lans, n.lan_share])).slice(0, 300); })()")})
    check("[B6] …and its text takes the panel's full width", lan and lan["mw"] == "none" and lan["w"] >= lan["pw"] - 1, lan)
    check("[console] node page: clean", not console_bad(tab), console_bad(tab)[:3])
    tab.close()

    # ── [N] the users grid networks chip: online first, like the reach chip ─────────────────────────────────────────────────
    # anna reaches gw's 192.168.50.0/24 (gw online), gw2's 192.168.60.0/24 (silent) and the node's LAN (node live): 3 rows, 2 live.
    def nets_chip(tab, who):
        return tab.ev("""(() => { const r = [...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === %s);
          const c = r && r.querySelector('.ucounts .grp-n[data-chip="networks"]');
          const tone = v => { const probe = document.createElement('span'); probe.style.color = 'var(' + v + ')'; document.body.appendChild(probe);
            const c = getComputedStyle(probe).color; probe.remove(); return c; };
          const re = r && r.querySelector('.ucounts .grp-n[data-chip=reach]');
          const ico = x => (x && x.querySelector('svg')) ? getComputedStyle(x.querySelector('svg')).color : null;
          return c ? {n: c.textContent.trim(), lit: c.classList.contains('lit-net'), label: c.getAttribute('aria-label'),
                      color: getComputedStyle(c).color, icon: ico(c), brand: tone('--brand'), faint: tone('--faint'),
                      reachLit: !!(re && re.classList.contains('lit')), reachIcon: ico(re), online: tone('--online')} : null; })()""" % json.dumps(who))
    def nets_bubble(tab):
        return tab.ev("""(() => { const b = document.querySelector('.deppop.netroute-bub'); if (!b || !b.querySelector('.nb-row, .netbub-row')) return null;
          const on = b.querySelector('.rb-sw button.on');
          return {rows: [...b.querySelectorAll('.nb-row')].map(x => x.querySelector('b.mono').textContent), live: b.querySelectorAll('.nb-row .nb-dot2.on').length,
                  sw: !!b.querySelector('.rb-sw'), mode: on ? on.textContent : null}; })()""")
    def open_nets(tab, who):
        hover(tab, "(() => { const r = [...document.querySelectorAll('.urow')].find(r => (r.querySelector('.un') || {}).textContent === %s); return r && r.querySelector('.ucounts .grp-n[data-chip=networks]'); })()" % json.dumps(who))
        got = None
        for _ in range(30):
            got = nets_bubble(tab)
            if got and got["rows"]:
                break
            settle(tab, 300)
        return got
    tab = open_app("en", viewport=(1400, 900))
    chip = None
    for _ in range(40):
        chip = nets_chip(tab, "anna")
        if chip and chip["lit"]:
            break
        settle(tab, 300)
    check("[N1] anna's networks chip: 2 of 3 live → says 2, lit in the connection colour", chip and chip["n"] == "2" and chip["lit"], chip)
    check("[N1] …its label says online now", chip and chip["label"] == "Reaches 2 networks online now", chip)
    check("[N1] …and its colour is the connection colour (--brand), as the peers grid's network chip", chip and chip["color"] == chip["brand"], chip)
    check("[N1] …its icon lights with it (--brand)", chip and chip["icon"] == chip["brand"], chip)
    check("[N1] the reach chip beside it, lit: its icon is green (--online) too", chip and chip["reachLit"] and chip["reachIcon"] == chip["online"], chip)
    bub = open_nets(tab, "anna")
    check("[N1] the bubble opens on the live ones — the 2 the chip counts, every dot live", bub and len(bub["rows"]) == 2 and bub["live"] == 2
          and "192.168.60.0/24" not in bub["rows"], bub)
    check("[N1] …with the Online / All switch, on Online", bub and bub["sw"] and bub["mode"] == "Online", bub)
    if bub and bub["sw"]:
        tab.ev("[...document.querySelectorAll('.deppop.netroute-bub .rb-sw button')].find(b => b.textContent === 'All').click()")
        settle(tab, 300)
        b2 = nets_bubble(tab)
        check("[N1] All lists all 3, the silent gateway's network included, not live", b2 and len(b2["rows"]) == 3 and "192.168.60.0/24" in b2["rows"] and b2["live"] == 2, b2)
    unhover(tab)
    check("[console] networks chip (live): clean", not console_bad(tab), console_bad(tab)[:3])
    tab.close()
    tab = open_app("ru", viewport=(1400, 900))
    chip = None
    for _ in range(40):
        chip = nets_chip(tab, "anna")
        if chip and chip["lit"]:
            break
        settle(tab, 300)
    check("[i18n] the chip's label in Russian: «Сейчас доступно 2 сети»", chip and chip["label"] == "Сейчас доступно 2 сети", chip)
    tab.close()

    # ── [B9] the connection test row · [B10] the peers grid's networks chip · [B11] the group pill · [B12] users grid chips ───
    tab = open_app("en", viewport=(1400, 900))
    ev_mod(tab, "sheets-crud", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; const p = S.recon.peers.find(x => x.id === %s); M.openPeerNetworks(p); return !!p;" % json.dumps(PID["gw"]))
    row = None
    for _ in range(40):
        settle(tab, 300)
        tab.ev("(() => { const b = [...document.querySelectorAll('button.disc')].find(x => x.textContent.includes('Connection test')); if (b && !b.classList.contains('open')) b.click(); return !!b; })()")
        row = tab.ev("""(() => { const r = document.querySelector('.netprobe .netrow'); if (!r) return null;
          return [...r.children].map(e => { const c = getComputedStyle(e), b = e.getBoundingClientRect(); return {tag: e.tagName, cls: e.className, h: Math.round(b.height), bg: c.backgroundColor, bc: c.borderTopColor, bw: c.borderTopWidth}; }); })()""")
        if row:
            break
    btn = next((x for x in (row or []) if x["tag"] == "BUTTON"), None)
    ins = [x for x in (row or []) if x["tag"] == "INPUT"]
    check("[B9] the connection test row renders: two fields and a button", btn is not None and len(ins) == 2, row)
    check("[B9] …the button is a panel button, not the browser's default", btn and "btn-ghost" in btn["cls"].split() and btn["bw"] == "1px"
          and btn["bc"] != "rgba(0, 0, 0, 0)", btn)
    check("[B9] …as tall as the fields beside it", btn and ins and all(abs(btn["h"] - x["h"]) <= 1 for x in ins), row)
    close_modals(tab)
    tab.goto(ORIGIN + "/#/peers")
    for _ in range(40):
        settle(tab, 300)
        if tab.ev("!!document.querySelector('.tg-gw')"):
            break
    def click_at(xy):
        for t_ in ("mouseMoved", "mousePressed", "mouseReleased"):
            br.send("Input.dispatchMouseEvent", {"type": t_, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}, session=tab.s)
        settle(tab, 900)
    at = tab.ev("(() => { const e = document.querySelector('.tg-gw'); if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    check("[B10] the peers grid shows the gateway's networks chip", bool(at), at)
    if at:
        settle(tab, 300)
        at = tab.ev("(() => { const r = document.querySelector('.tg-gw').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        click_at(at)
        check("[B10] a click on the chip opens the device's Networks window", tab.ev("!!document.querySelector('.netfield')"), tab.ev("location.hash"))
        check("[B10] …and not the peer view the row itself opens", not tab.ev("!!document.querySelector('.badge.b-nets')") and tab.ev("document.querySelectorAll('.netfield').length") == 1)
        close_modals(tab)
        hover(tab, "document.querySelector('.tg-gw')")
        vb = None
        for _ in range(20):
            vb = tab.ev("(() => { const b = [...document.querySelectorAll('.deppop.netroute-bub .rb-head button')].find(x => x.textContent.trim() === 'View'); if (!b) return null; const r = b.getBoundingClientRect(), h = b.closest('.rb-head').getBoundingClientRect(); return {xy: [r.left + r.width / 2, r.top + r.height / 2], right: Math.round(h.right - r.right)}; })()")
            if vb:
                break
            settle(tab, 200)
        check("[B10] its bubble's header carries View, at the right", vb and vb["right"] <= 1, vb)
        if vb:
            click_at(vb["xy"])
            check("[B10] …and View opens the Networks window", tab.ev("!!document.querySelector('.netfield')"))
            close_modals(tab)
        unhover(tab)
    check("[console] Networks window, peers grid chip and View: clean", not console_bad(tab), console_bad(tab)[:3])
    # [B12] on the users grid, at a width where the name cell has room
    tab.goto(ORIGIN + "/#/users")
    ends = None
    for _ in range(40):
        settle(tab, 300)
        ends = tab.ev("""(() => { const rows = [...document.querySelectorAll('.urow')].filter(r => r.querySelector('.u-name>.ucounts')); if (!rows.length) return null;
          return rows.slice(0, 6).map(r => { const n = r.querySelector('.u-name'), c = n.querySelector(':scope>.ucounts'), pc = r.querySelector('.u-counts');
            return {last: n.lastElementChild === c, gap: Math.round(pc.getBoundingClientRect().left - c.getBoundingClientRect().right), nameEnd: Math.round(n.getBoundingClientRect().right - c.getBoundingClientRect().right)}; }); })()""")
        if ends:
            break
    check("[B12] the chips are the last thing in the name cell", ends and all(e["last"] for e in ends), ends)
    check("[B12] …at its right end, just before Peers, with room between them", ends and all(e["nameEnd"] <= 12 and 12 <= e["gap"] <= 60 for e in ends), ends)
    tab.close()
    for lang in ("en", "ru"):
        tab = open_app(lang, viewport=(1400, 900))
        ev_mod(tab, "peer-ui", "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; M.openUserEdit(S.user(%s)); return true;" % json.dumps(uid["anna"]))
        m = "(() => { const p = document.querySelector('.ugroup-combo'); if (!p) return null; const i = p.querySelector('.uc-input'), ic = p.querySelector('.ic'); const P = p.getBoundingClientRect(), I = i.getBoundingClientRect(), C = ic.getBoundingClientRect(); const c = document.createElement('canvas').getContext('2d'); const cs = getComputedStyle(i); c.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily; const tw = c.measureText(i.value || i.placeholder).width; return {pill: P.width, input: I.width, text: tw, left: C.left - P.left, right: P.right - (I.left + tw), label: i.placeholder}; })()"
        pill = None
        for _ in range(30):
            settle(tab, 300)
            pill = tab.ev(m)
            if pill:
                break
        check("[B11] %s: the group pill is as wide as its words (%s)" % (lang, pill and pill["label"]), pill and abs(pill["input"] - pill["text"]) <= 2, pill)
        check("[B11] %s: …with the same room either side — its padding, nothing more (a fixed width centred would add slack)" % lang,
              pill and abs(pill["left"] - pill["right"]) <= 1.5 and abs(pill["left"] - 11) <= 1.5, pill)
        if pill:
            tab.ev("(() => { const i = document.querySelector('.ugroup-combo .uc-input'); i.focus(); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(i, 'a much longer query than the label'); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
            settle(tab, 400)
            grown = tab.ev(m)
            check("[B11] %s: …and a longer query widens it rather than scrolling inside it" % lang, grown and grown["pill"] > pill["pill"] + 20 and abs(grown["input"] - grown["text"]) <= 2, grown)
        check("[console] %s: user sheet group pill: clean" % lang, not console_bad(tab), console_bad(tab)[:3])
        tab.close()

    # [B13] footers: one height, one row
    FOOT = """(() => { const f = [...document.querySelectorAll('.sheet-foot, .editfoot')].filter(x => x.querySelector('.btn')).pop(); if (!f) return null;
      const b = [...f.querySelectorAll(':scope > .btn')].map(e => { const r = e.getBoundingClientRect(); return {t: e.textContent.trim(), cls: e.className, h: Math.round(r.height * 10) / 10, mid: r.top + r.height / 2}; });
      return b.length ? b : null; })()"""
    def foot_of(tab):
        got = None
        for _ in range(30):
            settle(tab, 250)
            got = tab.ev(FOOT)
            if got:
                break
        return got or []
    STORE_JS = "const S = (await import(performance.getEntriesByType('resource').map(r => r.name).find(u => /\\/js\\/store\\.js\\?v=/.test(u)))).Store; "
    for lang in ("en", "ru"):
        tab = open_app(lang, viewport=(1400, 900))
        ev_mod(tab, "sheets-crud", "M.openPeerView(%s); return true;" % json.dumps(PID["tester e0"]))
        fv = foot_of(tab)
        tinted = [b for b in fv if "btn-danger" in b["cls"]]
        plain = [b for b in fv if "btn-ghost" in b["cls"]]
        check("[B13] %s: the device view's Block and Unassign are as tall as QR and Edit beside them" % lang,
              len(tinted) == 2 and plain and all(abs(t["h"] - plain[0]["h"]) <= 0.5 for t in tinted), fv)
        if lang == "ru":
            check("[B13] ru: …and its six buttons stay on one row", len(fv) == 6 and max(b["mid"] for b in fv) - min(b["mid"] for b in fv) <= 2, fv)
        close_modals(tab)
        ev_mod(tab, "peer-ui", STORE_JS + "M.openUserEdit(S.user(%s)); return true;" % json.dumps(uid["anna"]))
        fu = foot_of(tab)
        tinted = [b for b in fu if any(c in b["cls"] for c in ("btn-danger", "btn-warn"))]
        plain = [b for b in fu if "btn-ghost" in b["cls"]]
        check("[B13] %s: the user sheet's Delete user, Rotate all keys and Block are as tall as Cancel" % lang,
              len(tinted) == 3 and plain and all(abs(t["h"] - plain[0]["h"]) <= 0.5 for t in tinted), fu)
        check("[console] %s: footers: clean" % lang, not console_bad(tab), console_bad(tab)[:3])
        tab.close()

    OFFLINE.add(PK["gw"]); NOLAN[0] = True        # nothing anna reaches is live any more
    must(sync(), "sync with gw silent and no LAN")
    time.sleep(4)
    tab = open_app("en", viewport=(1400, 900))
    chip = None
    for _ in range(40):
        chip = nets_chip(tab, "anna")
        if chip and not chip["lit"] and chip["n"] == "2":
            break
        settle(tab, 300)
    check("[N2] nothing live: the chip says the total (2), unlit", chip and chip["n"] == "2" and not chip["lit"], chip)
    check("[N2] …its label says none online", chip and chip["label"] == "Reaches 2 networks, none online", chip)
    check("[N2] …and an unlit chip keeps its quiet icon (--faint)", chip and chip["icon"] == chip["faint"], chip)
    bub = open_nets(tab, "anna")
    check("[N2] the bubble opens on all of them, with no switch to offer", bub and len(bub["rows"]) == 2 and bub["live"] == 0 and not bub["sw"], bub)
    unhover(tab)
    check("[console] networks chip (nothing live): clean", not console_bad(tab), console_bad(tab)[:3])
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
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d check(s) went red" % (PERTURB, len(FAILS))) if ok else "PERTURB FAILED — the fix was undone and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
