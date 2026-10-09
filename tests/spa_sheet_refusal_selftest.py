#!/usr/bin/env python3
"""Behavioural gate: a sheet's Save waits for the panel, and a refusal stays in the sheet with every edit (q189 SPA-3, the root).
The real SPA, served by the real swg-panel-server, in headless Chrome over its DevTools pipe (tests/cdp_pipe.py).

Before: the interface Edit sheet, the mesh-link sheet, the turn / WDTT / csqtt sheets, the user editor and the node settings
sheet closed on Save and sent the change afterwards — a refusal was a toast over a closed sheet, and every edit in it was
gone. Round 1 papered over four "-" rules by copying the panel's rules into the SPA (awgSaveRule, meshSNone); those copies are
gone now — the panel judges, the sheet reports.

  [1] the interface Edit sheet: a DNS change with an MTU the panel refuses (100) → the sheet stays open, says the panel's own
      sentence ("mtu must be 576–9200"; «MTU — от 576 до 9200» in Russian), and keeps both edits; the panel stored nothing
  [2] …the control: the same edits with a valid MTU close the sheet, and the panel stored the DNS
  [3] the mesh-link sheet: AWG 3.1 picked with S4 set to none in the link's own params — Save is pressed (no copy of the rule
      holds it), the panel refuses (mesh_omit_s_refusal), the sheet stays open with that sentence, the type pick and the cell
  [4] every other Save sheet sends first (sheetSend) — none closes before the panel answers (source)
  [5] the WDTT and csqtt MANAGE sheets, run (q189 F22: the root's conversion passed `setBusy` there and never declared it —
      a ReferenceError, so a valid title, ExecStart-params or listen-port Save made no POST, said nothing and stored nothing):
      a title with a control character is sent, refused, and the sheet stays with the panel's sentence and the edit; valid
      ExecStart params are sent, stored, and the sheet closes — no page exception on either

Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
Run: python3 tests/spa_sheet_refusal_selftest.py      (0 = pass)
     --perturb-<name>  serves a copy of the SPA with one fix undone and expects RED: iface-close | link-close | err-slot |
                       wdtt-busy | csqtt-busy
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
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str, ensure_ascii=False)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

def guarded(name, fn):
    try:
        fn()
    except Exception as e:
        check(name + " (raised)", False, "%s: %s" % (type(e).__name__, str(e)[:300]))

if not CHROME:
    bail("no Chrome/Chromium (set $CHROME) — this gate cannot run, which is not a pass")

PERTURBATIONS = {   # the served SPA with one fix undone
    "iface-close": ("js/iface.js", "    const r = switched ? await api.ifaceUpdate({ ...body, awg_gen: gen }) : await sheetSend(() => api.ifaceUpdate(body), setSaveErr, setBusy);",
                    "    closeAllModals(); const r = switched ? await api.ifaceUpdate({ ...body, awg_gen: gen }) : await sheetSend(() => api.ifaceUpdate(body), setSaveErr, setBusy);"),
    "link-close": ("js/iface.js", "    const r = await sheetSend(() => api.connectionUpdate({",
                   "    closeModal(); const r = await sheetSend(() => api.connectionUpdate({"),
    "err-slot": ("js/ui.js", '${err ? html`<div class="formmsg err" role="alert">${err}</div>` : null}', ""),
    # F22: each manage sheet's `busy` declaration taken out again (the line is the same in both; the next one tells them apart)
    "wdtt-busy": ("js/turn.js", "  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);   // sheetSend holds Save while it sends (q189 F22)\n"
                                "  // RAW-IP mode", "  const [msg, setMsg] = useState(null); const busy = false;\n  // RAW-IP mode"),
    "csqtt-busy": ("js/turn.js", "  const [msg, setMsg] = useState(null); const [busy, setBusy] = useState(false);   // sheetSend holds Save while it sends (q189 F22)\n"
                                 "  const newListen = (ipPickerVal(", "  const [msg, setMsg] = useState(null); const busy = false;\n  const newListen = (ipPickerVal("),
}
WEB = ROOT
if PERTURB:
    if PERTURB not in PERTURBATIONS:
        bail("unknown perturbation %r (one of: %s)" % (PERTURB, ", ".join(PERTURBATIONS)))
    f, old, new = PERTURBATIONS[PERTURB]
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: the anchor is not in %s exactly once (%d)" % (PERTURB, f, src.count(old)))
        sys.exit(1)
    WEB = tempfile.mkdtemp(prefix="sheet-refusal-perturb-")
    for item in ("js", "vendor", "fonts", "img", "icons"):
        if os.path.isdir(os.path.join(ROOT, item)):
            shutil.copytree(os.path.join(ROOT, item), os.path.join(WEB, item))
    for item in os.listdir(ROOT):
        p = os.path.join(ROOT, item)
        if os.path.isfile(p) and item.endswith((".html", ".js", ".css", ".svg", ".png", ".ico", ".json", ".woff2")) or item == "VERSION":
            shutil.copy(p, os.path.join(WEB, item))
    with open(os.path.join(WEB, f), "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))

# ── [4] first: the source — every Save sheet sends before it closes ──────────────────────────────────────────────────
print("[4] every Save sheet sends first")
SRC = {f: open(os.path.join(WEB, "js", f), encoding="utf-8").read() for f in ("iface.js", "turn.js", "peer-ui.js", "sheets-crud.js", "ui.js")}
SENDS = {   # the sheet → its send, which must go through sheetSend
    "interface Edit sheet": ("iface.js", "sheetSend(() => api.ifaceUpdate(body)"),
    "mesh-link sheet": ("iface.js", "sheetSend(() => api.connectionUpdate({"),
    "turn-proxy sheet (title)": ("turn.js", "sheetSend(() => api.turnTitle({"),
    "WDTT sheets (manage, title, edit)": ("turn.js", "sheetSend(() => api.wdttSet({"),
    "csqtt sheets (manage, title, edit)": ("turn.js", "sheetSend(() => api.csqttSet({"),
    "user editor": ("peer-ui.js", "sheetSend(() => api.userUpdate({"),
    "node settings sheet": ("sheets-crud.js", "sheetSend(() => api.nodeUpdate({"),
}
WANT = {"WDTT sheets (manage, title, edit)": 3, "csqtt sheets (manage, title, edit)": 3}
for name, (f, needle) in SENDS.items():
    check("[4] %s sends through sheetSend (%d×)" % (name, WANT.get(name, 1)), SRC[f].count(needle) == WANT.get(name, 1), SRC[f].count(needle))
OLD = [   # the shapes that closed first
    ("turn.js", "Store.apply(); closeAllModals();\n    const fail = m =>"),
    ("iface.js", "closeModal();\n    mutate({\n      key: \"conn:\""),
    ("peer-ui.js", "done();   // close the editor immediately"),
    ("sheets-crud.js", "closeAllModals();   // close the sheet AND any re-provision confirm stacked on top; optimistic"),
    ("turn.js", "      closeModal();\n      if (!titleChanged)"),
]
check("[4] none of the close-first shapes is left", not [o for f, o in OLD if o in SRC[f]], [o[:60] for f, o in OLD if o in SRC[f]])
check("[4] the round-1 copies of the panel's rules are gone (awgSaveRule, meshSNone)",
      not any(w in SRC["iface.js"] for w in ("awgSaveRule", "meshSNone", "omitRule", "awgRule")), "")

# ── the panel and its fixture: two nodes (their mesh link made by the panel), node A with awg0 ─────────────────────────────
D = tempfile.mkdtemp(prefix="sheet-refusal-")
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
        return r.status, {"raw": raw[:200]}

def nodes():
    return json.load(open(D + "/state/nodes.json"))

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
        bail("the panel never came up")
    def must(r, what):
        st, o = r
        if st != 200 or o.get("ok") is False:
            bail("fixture: %s refused — %s %s" % (what, st, json.dumps(o)[:300]))
        return o
    A = must(call("POST", "/api/nodes/create", {"name": "qa-a", "endpoint_host": "203.0.113.10"}), "node A")["data"]
    B = must(call("POST", "/api/nodes/create", {"name": "qa-b", "endpoint_host": "203.0.113.11"}), "node B")["data"]
    LINK = (nodes()[A["id"]].get("links") or {}).get(B["id"], {}).get("iface")
    if not LINK:
        bail("fixture: the panel made no mesh link between the two nodes")
    def snapshot(nid, name, ip, own):
        ifs = dict(own)
        n = nodes()[nid]
        for _p, l in (n.get("links") or {}).items():
            rec = (n.get("ifaces") or {}).get(l["iface"]) or {}
            ifs[l["iface"]] = {"peers": [], "meta": {"listen_port": rec.get("listen_port") or 9999, "address": rec.get("address") or "10.255.0.0/31",
                                                     "type": "awg", "public_key": base64.b64encode(nid.encode().ljust(32, b"k")[:32]).decode(),
                                                     "awg_params": rec.get("awg_params") or {}}}
        return {"hostname": name, "generated_at": int(time.time()), "noded_version": "1.8.9-beta", "kind": "baremetal", "interfaces": ifs,
                "turn_proxies": [], "node_ips": [ip], "node_ifaces": ["eth0"],
                "datapath": {"awg": {"gen": {"module": "3.1", "fallback": "3.1", "tools": "3.1", "disk": "3.1"}, "exact": 1}},
                **(EXTRA if nid == A["id"] else {})}
    EXTRA = {}   # [5]: the WDTT and csqtt servers node A reports, once the panel holds them
    AWG0 = {"awg0": {"peers": [], "meta": {"listen_port": 51820, "address": "10.60.0.1/24", "subnet": "10.60.0.0/24", "type": "awg",
                                           "public_key": base64.b64encode(b"a" * 32).decode(), "endpoint": "203.0.113.10:51820",
                                           "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 20, "S2": 30, "H1": 1, "H2": 2, "H3": 3, "H4": 4}}}}
    def sync():
        call("POST", "/api/node/sync", {"snapshot": snapshot(A["id"], "qa-a", "203.0.113.10", AWG0)}, token=A["token"])
        call("POST", "/api/node/sync", {"snapshot": snapshot(B["id"], "qa-b", "203.0.113.11", {})}, token=B["token"])
    sync()
    def keep_syncing():
        while not stop.wait(3):
            try:
                sync()
            except Exception:
                pass
    threading.Thread(target=keep_syncing, daemon=True).start()
    if "awg0" not in (nodes()[A["id"]].get("ifaces") or {}):
        bail("fixture: awg0 was not recorded from node A's report")
    # [5]'s servers on node A, made the way the Turn proxies card makes them, then reported by the node
    must(call("POST", "/api/wdtt/set", {"node": A["id"], "iface": "wdtt1", "listen": "203.0.113.10:56000", "wg_port": 56001, "fork": "amurcanov",
                                        "wg_addr": "10.11.0.1/24", "title": "", "params": "", "raw": False, "block": []}), "WDTT server")
    must(call("POST", "/api/csqtt/set", {"node": A["id"], "iface": "csqtt1", "listen": "203.0.113.10:56002", "tun_addr": "10.10.0.1/24",
                                         "title": "", "params": "", "block": []}), "csqtt server")
    _w, _c = nodes()[A["id"]]["wdtt"]["wdtt1"], nodes()[A["id"]]["csqtt"]["csqtt1"]
    EXTRA.update(wdtt=[{"iface": "wdtt1", "service": "swg-wdtt-wdtt1", "active": "active", "listen": _w["listen"], "bind": _w["listen"],
                        "wg_addr": _w.get("wg_addr") or "10.11.0.1/24", "wg_port": 56001, "fork": "amurcanov", "version": "1.2.4-3",
                        "stopped": False, "params": "", "passwords": {}}],
                 csqtt=[{"iface": "csqtt1", "service": "swg-csqtt-csqtt1", "active": "active", "listen": _c["listen"], "bind": _c["listen"],
                         "tun_addr": "10.10.0.1/24", "kind": "csqtt", "fork": "csqtt", "version": "2.1.9-4", "line": "2.1", "stopped": False,
                         "params": "", "passwords": {}}])
    sync()

    br = Browser()
    MOD = "(async n => import(performance.getEntriesByType('resource').map(r => r.name).find(u => new RegExp('/js/' + n + '\\\\.js\\\\?v=').test(u))))"
    def open_app(lang):
        tab = Tab(br)
        br.send("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False}, session=tab.s)
        br.send("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('swg-lang', %s); } catch (_) {}" % json.dumps(lang)}, session=tab.s)
        tab.goto(ORIGIN + "/#/node/" + A["id"])
        for _ in range(200):
            try:
                if tab.ev("!!(document.querySelector('.ifcard') && performance.getEntriesByType('resource').some(r => /iface\\.js\\?v=/.test(r.name)))"):
                    break
            except Exception:
                pass
            time.sleep(0.1)
        tab.ev("new Promise(r => setTimeout(r, 1500))", timeout=10)
        return tab
    def ev_mod(tab, module, body, timeout=30):
        return tab.ev("(async () => { const M = await %s(%s); %s })()" % (MOD, json.dumps(module), body), timeout=timeout)
    HELP = """
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const sheet = () => document.querySelector('.overlay.show .sheet');
      const typeInto = (el, v) => { const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true })); };
      const field = (sh, label) => [...sh.querySelectorAll('.field')].find(f => ((f.querySelector('label') || {}).textContent || '').trim() === label);
      const openDisc = async (sh, re) => { const d = [...sh.querySelectorAll('button')].find(b => /^▸/.test(b.textContent.trim()) && re.test(b.textContent)); if (d) { d.click(); await sleep(500); } };
      const save = () => sheet().querySelector('.sheet-foot .btn-primary');
    """
    def iface_round(tab, mtu):
        return ev_mod(tab, "iface", HELP + """
          M.openEditIface(%s, 'awg0'); await sleep(1500);
          let sh = sheet(); if (!sh) return { err: 'no sheet' };
          await openDisc(sh, /MTU/);
          const dnsI = field(sh, 'DNS').querySelector('input'), mtuI = field(sh, 'MTU').querySelector('input');
          typeInto(dnsI, '9.9.9.9'); typeInto(mtuI, %s); await sleep(300);
          save().click(); await sleep(2500);
          sh = sheet();
          return { open: !!sh && /awg0/.test((sh.querySelector('h3') || {}).textContent || ''),
                   msg: sh ? [...sh.querySelectorAll('.formmsg.err')].map(e => e.textContent.trim()) : [],
                   dns: sh && field(sh, 'DNS') ? field(sh, 'DNS').querySelector('input').value : null,
                   mtu: sh && field(sh, 'MTU') ? field(sh, 'MTU').querySelector('input').value : null };""" % (json.dumps(A["id"]), json.dumps(mtu)), timeout=60)
    def close_all(tab):
        ev_mod(tab, "ui", "M.closeAllModals(); return true;")
        tab.ev("new Promise(r => setTimeout(r, 400))", timeout=10)

    tab = open_app("en")
    # ── [1] the interface Edit sheet refuses and keeps ────────────────────────────────────────────────────────────────
    print("\n[1] the interface Edit sheet: the panel refuses MTU 100 — the sheet stays, says so, and keeps both edits")
    def s1():
        before = dict(nodes()[A["id"]]["ifaces"]["awg0"])
        o = iface_round(tab, "100")
        check("[1] the sheet is still open after the refusal", o.get("open") is True, o)
        check("[1] …saying the panel's own sentence: \"mtu must be 576–9200\"", "mtu must be 576–9200" in (o.get("msg") or []), o)
        check("[1] …with the DNS edit and the MTU still in their fields", o.get("dns") == "9.9.9.9" and o.get("mtu") == "100", o)
        after = nodes()[A["id"]]["ifaces"]["awg0"]
        check("[1] …and the panel stored nothing", after.get("dns") == before.get("dns") and after.get("mtu") == before.get("mtu"),
              [before.get("dns"), after.get("dns")])
        close_all(tab)
    guarded("[1]", s1)
    # ── [2] the control: accepted, the sheet closes ─────────────────────────────────────────────────────────────────
    print("\n[2] the control: a valid MTU — the save is accepted and the sheet closes")
    def s2():
        o = iface_round(tab, "1300")
        check("[2] the sheet closed on the accepted save", o.get("open") is False, o)
        rec = nodes()[A["id"]]["ifaces"]["awg0"]
        check("[2] …and the panel stored the DNS and the MTU", "9.9.9.9" in json.dumps(rec.get("dns")) and str(rec.get("mtu")) == "1300",
              {k: rec.get(k) for k in ("dns", "mtu")})
        close_all(tab)
    guarded("[2]", s2)
    # ── [3] the mesh-link sheet ───────────────────────────────────────────────────────────────────────────────────────
    print("\n[3] the mesh-link sheet: AWG 3.1 with S4 none — the panel refuses, the sheet stays with the pick and the cell")
    def s3():
        o = ev_mod(tab, "iface", HELP + """
          M.openConnectionEdit(%s, %s); await sleep(1500);
          let sh = sheet(); if (!sh) return { err: 'no sheet' };
          const t31 = [...sh.querySelectorAll('.meshgen button[role=radio]')].find(b => b.textContent.trim() === 'AWG 3.1');
          if (t31) { t31.click(); await sleep(400); }
          const s4 = [...sh.querySelectorAll('label.awg-f')].find(l => (l.querySelector('span') || {}).textContent === 'S4');
          if (s4) typeInto(s4.querySelector('input'), '-');
          await sleep(400);
          const b = save(); const enabled = !!b && !b.disabled;
          if (enabled) b.click();
          await sleep(2500);
          sh = sheet();
          const t31b = sh && [...sh.querySelectorAll('.meshgen button[role=radio]')].find(b => b.textContent.trim() === 'AWG 3.1');
          const s4b = sh && [...sh.querySelectorAll('label.awg-f')].find(l => (l.querySelector('span') || {}).textContent === 'S4');
          return { enabled, open: !!sh && /Connection to/.test((sh.querySelector('h3') || {}).textContent || ''),
                   msg: sh ? [...sh.querySelectorAll('.formmsg.err')].map(e => e.textContent.trim()) : [],
                   pick: t31b ? t31b.getAttribute('aria-checked') : null, s4: s4b ? s4b.querySelector('input').value : null };""" % (json.dumps(A["id"]), json.dumps(LINK)), timeout=60)
        check("[3] Save is pressable — no copy of the panel's rule holds it", o.get("enabled") is True, o)
        check("[3] the sheet is still open after the refusal", o.get("open") is True, o)
        check("[3] …saying the panel's own sentence (AmneziaWG 3.1 links need S1–S4)",
              any("AmneziaWG 3.1 links need S1–S4" in m and "S4" in m for m in (o.get("msg") or [])), o)
        check("[3] …with the AWG 3.1 pick and the S4 cell kept", o.get("pick") == "true" and o.get("s4") == "-", o)
        close_all(tab)
    guarded("[3]", s3)
    # ── [1ru] the same refusal in Russian ─────────────────────────────────────────────────────────────────────────────
    print("\n[1ru] the refusal in Russian")
    def s1ru():
        t2 = open_app("ru")
        o = iface_round(t2, "100")
        check("[1ru] «MTU — от 576 до 9200», in the open sheet", o.get("open") is True and "MTU — от 576 до 9200" in (o.get("msg") or []), o)
    guarded("[1ru]", s1ru)
    # ── [5] the WDTT and csqtt manage sheets, run ──────────────────────────────────────────────────────────────────
    print("\n[5] the WDTT and csqtt MANAGE sheets: a refused save stays with its edit, a valid one is stored and closes (F22)")
    def manage_round(tab, rid, setjs):
        """Open the manage sheet from its card, apply `setjs`, press Save; → what was sent, the sheet, and the page's exceptions."""
        n0 = len(br.events)
        o = tab.ev("(async () => {" + HELP + r"""
          const calls = []; const of = window.fetch;
          window.fetch = function (u, opt) { const c = { url: String(u), method: (opt && opt.method) || 'GET' }; calls.push(c);
            return of.apply(this, arguments).then(r => { c.status = r.status; return r; }); };
          try {
            const card = document.querySelector('.ifcard.tp[data-rid="%s"]'); if (!card) return { err: 'no card' };
            card.click(); await sleep(1200);
            let sh = sheet(); if (!sh) return { err: 'no sheet' };
            const lab = f => ((f.querySelector('label') || {}).textContent || '').replace(/\s+/g, ' ').trim();
            const fieldRx = (sh, re) => [...sh.querySelectorAll('.field')].find(f => re.test(lab(f)));
            const disc = re => { const b = [...sheet().querySelectorAll('button')].find(b => re.test(b.textContent) && !/^(Save|Cancel|Delete)/.test(b.textContent.trim())); if (b) b.click(); return !!b; };
            %s
            await sleep(400);
            const b = save(); const enabled = !!b && !b.disabled; if (enabled) b.click();
            await sleep(2500);
            sh = sheet();
            const ti = sh && fieldRx(sh, /^Title/), pa = sh && fieldRx(sh, /ExecStart/);
            return { enabled, open: !!sh && /proxy/.test((sh.querySelector('h3') || {}).textContent || ''),
                     msg: sh ? [...sh.querySelectorAll('.formmsg.err')].map(e => e.textContent.trim()) : [],
                     title: ti ? ti.querySelector('input').value : null, params: pa ? (pa.querySelector('input, textarea') || {}).value : null,
                     posts: calls.filter(c => c.method === 'POST').map(c => [c.url.replace(/^.*?(\/api\/)/, '/api/'), c.status]) };
          } finally { window.fetch = of; }
        })()""" % (rid, setjs), timeout=60)
        exc = [((e["params"]["exceptionDetails"].get("exception") or {}).get("description") or e["params"]["exceptionDetails"].get("text", "")).split("\n")[0]
               for e in br.events[n0:] if e.get("method") == "Runtime.exceptionThrown" and e.get("sessionId") == tab.s]
        return o, exc
    SET_TITLE = "const t = fieldRx(sh, /^Title/); typeInto(t.querySelector('input'), 'gate\\u0001title');"
    SET_PARAMS = ("disc(/Server parameters/); await sleep(500); sh = sheet(); const p = fieldRx(sh, /ExecStart/); "
                  "const pi = p.querySelector('input, textarea'); const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(pi), 'value'); "
                  "d.set.call(pi, '-v'); pi.dispatchEvent(new Event('input', { bubbles: true }));")
    def s5():
        t5 = open_app("en")
        for kind, rid, ep in (("WDTT", "wdtt:wdtt1", "/api/wdtt/set"), ("csqtt", "csqtt:csqtt1", "/api/csqtt/set")):
            key, iface = kind.lower(), rid.split(":")[1]
            o, exc = manage_round(t5, rid, SET_TITLE)
            check("[5] %s: a title with a control character is sent (one POST, refused)" % kind, o.get("posts") == [[ep, 400]], [o, exc])
            check("[5] …the sheet stays, saying the panel's own sentence", o.get("open") is True and "control characters are not allowed" in (o.get("msg") or []), o)
            check("[5] …with the title as typed", o.get("title") == "gate\u0001title", o.get("title"))
            check("[5] …nothing stored, and no page exception", not nodes()[A["id"]][key][iface].get("title") and not exc, [nodes()[A["id"]][key][iface].get("title"), exc])
            close_all(t5)
            o, exc = manage_round(t5, rid, SET_PARAMS)
            check("[5] %s: valid ExecStart params are sent and accepted (one POST, 200)" % kind, o.get("posts") == [[ep, 200]], [o, exc])
            check("[5] …the sheet closes, the panel stored them, and no page exception",
                  o.get("open") is False and nodes()[A["id"]][key][iface].get("params") == "-v" and not exc,
                  [o.get("open"), nodes()[A["id"]][key][iface].get("params"), exc])
            close_all(t5)
    guarded("[5]", s5)
finally:
    stop.set()
    if br:
        try:
            br.close()
        except Exception:
            pass
    srv.terminate()
    try:
        srv.wait(5)
    except Exception:
        srv.kill()

print()
if PERTURB:
    if FAILS:
        print("PERTURB OK (%s) — %d checks went red" % (PERTURB, len(FAILS))); sys.exit(0)
    print("PERTURB FAILED — %s undone and every check still passed" % PERTURB); sys.exit(1)
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS")
