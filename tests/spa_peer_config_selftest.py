#!/usr/bin/env python3
"""Self-test — a lookup that finds nothing for ONE deployment says nothing about the PEER (js/crypto.js getConfig), and an
address nobody edited is not an edit (js/sheets-crud.js EditPeerSheet). A real panel, a simulated node, the real sheets in
headless Chrome over its DevTools pipe (tests/cdp_pipe.py): a sheet's banner, QR button and Save are what the operator sees.

Reported from a live panel: a peer on awg1 + csqtt25, Edit, log out, log in, Edit → "The client's private key isn't available"
and no QR, with the key on the panel and the vault open. A csqtt deployment has no config, so its lookup missed, and that miss
marked the whole peer "no config" in localStorage, which the next lookup read before it asked anything. The operator then
pressed Rotate, the one action that breaks a client's working config, and Save lit up by itself: a csqtt deployment's live
address is the read-back keyed by its password, which a Rotate blanks.

  [1] the report: a peer on awg1 + csqtt25 made in the New peer sheet, Edit, log out, sign in — Edit still has the config, its
      QR and its gear, twice over, and no mark is left
  [2] the same with WDTT, and no logout: a reload and two opens
  [3] an interface the node stopped reporting takes nothing from the peer's other deployment; its own QR card says so, not
      re-issue, and has its QR again the moment the interface is back
  [4] one failed read of the escrow leaves no mark, and the QR card says the panel couldn't be reached, not re-issue; the QR is
      back once the read works, and after a reload
  [5] the banner still tells the truth: a peer with nothing stored shows it, offers no unlock on an open vault, and leaves it the
      moment the key reaches the panel; its QR card says re-issue, the one case here where that is the answer
  [6] a mark an older build left is dropped at load
  [7] the backfill's own note does not stop a lookup, and a lookup that finds the config clears it
  [8] Rotate on a mixed peer: Save stays off while the csqtt address is blank and when it comes back different — and a real
      address change on the WireGuard deployment still lights Save and saves
  [9] a locked vault: the sheet has the unlock, next to the warning that stays true. No mark; Enter in its password field unlocks,
      the open sheet gets its config back, and the password was no edit of the peer. That Enter is the unlock's alone: an edit
      waiting on the sheet stays waiting, whichever password it was given
  [10] adding a target on a locked vault: a keyless target draws no warning, one with a key draws no advice to rotate; it saves with
       the same key, the QR card says locked, and the unlock gives the new target its config
  [11] a peer with no key (csqtt only) adds WireGuard: no warning, and on Save it gets a key and a PSK, its csqtt password as it
       was; the key is kept encrypted, the QR is there at once and after a reload with the same key; a second key is refused
  [12] the unlock follows the vault, not the setting: no vault, none; store_configs off, a config kept from before still opens

Run: python3 tests/spa_peer_config_selftest.py    (0 = pass; needs google-chrome / chromium, or $CHROME)
     --perturb-<name>   serves a copy of the SPA with one change undone and expects RED; a plant stops at its first FAIL
       --perturb-orig     the reported bug back: a lookup reads the mark, and a miss writes it        → RED [1]
       --perturb-write    a miss writes the mark                                                      → RED [1]
       --perturb-read     a lookup reads the mark before it asks                                      → RED [7]
       --perturb-ver      the old marks are kept                                                      → RED [6]
       --perturb-hit      a lookup that finds the config leaves the note                              → RED [7]
       --perturb-banner   the sheet never says the key is missing, and has no unlock                  → RED [4]
       --perturb-addr     a csqtt deployment's read-back counts as an edit                            → RED [8]
       --perturb-addrall  no deployment's address counts as an edit                                   → RED [8]
       --perturb-door     the sheet has no unlock                                                     → RED [9]
       --perturb-doorepoch  an unlock leaves the open sheet as it was                                 → RED [9]
       --perturb-nodirty  the password counts as an edit of the peer                                  → RED [9]
       --perturb-enter    Enter in the password is the sheet's Enter too                              → RED [9]
       --perturb-unlocked the unlock is offered on an open vault                                      → RED [5]
       --perturb-unread   a failed read of the records reads as nothing kept                          → RED [4]
       --perturb-gonecard the QR card of a gone interface says re-issue                               → RED [3]
       --perturb-gonemiss a gone interface is remembered as a miss                                    → RED [3]
       --perturb-advice   the Targets sheet tells the operator to rotate                              → RED [10]
       --perturb-keyless  a keyless target draws the warning                                          → RED [10]
       --perturb-firstkey the panel refuses a keyless peer its first key (served from a copy of it)   → RED [11]
       --perturb-keyguard the panel takes a second key for a peer quietly                             → RED [11]
       --perturb-freshwarn the sheet warns of a missing key that Save is about to make                → RED [11]
       --perturb-freshkeep the new key is never kept                                                  → RED [11]
       --perturb-novault  the unlock is offered with no vault                                         → RED [12]
       --perturb-need     the unlock is hidden with store_configs off                                 → RED [12]
"""
import base64, hashlib, http.client, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VERSION = open(os.path.join(ROOT, "VERSION")).read().strip()   # the fixture node runs this build, so it never reads as outdated
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

SERVER = os.path.join(ROOT, "swg-panel-server")
PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)
_MISS = 'const miss = () => { _configMiss.set(mk, { epoch: Store.configEpoch, at: Date.now() }); };'
_MISSW = 'const miss = () => { _configMiss.set(mk, { epoch: Store.configEpoch, at: Date.now() }); if (peer) subNoConfSet(peer.id, pubkey); };'
_MK = '  const mk = pubkey + "|" + node + "|" + iface;\n  if (_configMissFresh(mk))'
_READ = '  if (peer && subNoConfHas(peer.id, pubkey)) return Promise.resolve(null);\n' + _MK
_ADDR = 'const ipChangedFor = t => { if (isSelfContainedKind(targetType(t))) return false; const v'
_DOOR = '${(hasKeyed && loaded && !editable) ? html`<${VaultUnlockPanel}/><div class="notice warn">'
_GONE = "if (need === false || ready || subSKCached() || !exists) return null;"
PERTURBS = {
    "orig": [("js/crypto.js", _MK, _READ), ("js/crypto.js", _MISS, _MISSW)],
    "write": [("js/crypto.js", _MISS, _MISSW)],
    "read": [("js/crypto.js", _MK, _READ)],
    "ver": [("js/crypto.js", 'const _NOCONF_V = "3";', 'const _NOCONF_V = "2";')],
    "hit": [("js/crypto.js", "const hit = () => { _configMiss.delete(mk); if (peer) subNoConfClear(peer.id); };", "const hit = () => { _configMiss.delete(mk); };")],
    "banner": [("js/sheets-crud.js", _DOOR, '${false ? html`<div class="notice warn">')],
    "addr": [("js/sheets-crud.js", _ADDR, "const ipChangedFor = t => { const v")],
    "addrall": [("js/sheets-crud.js", _ADDR, "const ipChangedFor = t => { if (t) return false; const v")],
    "door": [("js/sheets-crud.js", _DOOR, '${(hasKeyed && loaded && !editable) ? html`<div class="notice warn">')],
    "doorepoch": [("js/peer-ui.js", 'try { await subUnlock(pw); subSetPersist(keep); setPw(""); setReady(true); Store.configEpoch++; bus.emit(); }\n    catch (e) { toast((e && e.message) || T("That password didn’t unlock',
                   'try { await subUnlock(pw); subSetPersist(keep); setPw(""); setReady(true); bus.emit(); }\n    catch (e) { toast((e && e.message) || T("That password didn’t unlock')],
    "nodirty": [("js/peer-ui.js", '<div class="unlockpanel" data-nodirty>', '<div class="unlockpanel">')],
    "enter": [("js/ui.js", '[role=tab], [data-nodirty]")) return;', '[role=tab]")) return;')],
    "unlocked": [("js/peer-ui.js", "useEffect(() => { if (subSKCached()) { setReady(true); return; }\n    let ok", "useEffect(() => { let ok"),
                 ("js/peer-ui.js", _GONE, "if (need === false || !exists) return null;")],
    "novault": [("js/peer-ui.js", _GONE, "if (need === false || ready || subSKCached() || exists === null) return null;")],
    "unread": [("js/crypto.js", "if (users === SUB_USERS_UNREAD) return CONF_UNREACHABLE;", "if (false) return CONF_UNREACHABLE;")],
    "gonecard": [("js/peer-ui.js", ': !Store.ifaceMeta(t.node, t.iface) ? T("The node no longer reports interface', ': false ? T("The node no longer reports interface')],
    "gonemiss": [("js/crypto.js", "  if (!Store.ifaceMeta(node, iface)) return Promise.resolve(null);\n  if (_configMissFresh(mk))", "  if (_configMissFresh(mk))")],
    "firstkey": [("swg-panel-server", '            _key = {"pubkey": nk, "psk": body.get("psk") or gen_psk()}', '            return 400, {"ok": False, "error": "planted", "code": "bad_request"}')],
    "keyguard": [("swg-panel-server", 'if nk and p.get("pubkey") and nk != p["pubkey"]:', "if False:")],
    "freshwarn": [("js/sheets-crud.js", "&& !srcConf && (Store.peer(peer.id) || peer).pubkey ? html`", "&& !srcConf ? html`")],
    "freshkeep": [("js/sheets-crud.js", "    if (freshKept) await subPublishOrPrompt(", "    if (false) await subPublishOrPrompt(")],
    "advice": [("js/sheets-crud.js", "but a fresh QR / config can't be generated.\")", "but a fresh QR / config can't be generated. Re-issue (rotate keys) for a downloadable config.\")")],
    "keyless": [("js/sheets-crud.js", "${added.some(c => !isSelfContainedKind(kindFor(c))) && !srcConf ?", "${added.length && !srcConf ?")],
    "need": [("js/sheets-crud.js", _DOOR, _DOOR.replace("<${VaultUnlockPanel}/>", "<${VaultUnlockPanel} need=${Store.storeConfigs}/>"))],
}
assert PERTURB in (None,) + tuple(PERTURBS), "unknown perturbation %r" % PERTURB

FAILS = []
class Done(Exception):
    """A plant went red: nothing after its first FAIL can change the verdict, and a plant is the whole gate's length otherwise."""

def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
        if PERTURB:
            raise Done()

class guard:
    """A check section that throws (a page that never drew what it looks for) is a FAIL of that section, not a crash: a plant
    that crashes the gate would measure nothing."""
    def __init__(self, label):
        self.label = label
    def __enter__(self):
        return self
    def __exit__(self, typ, val, tb):
        if typ is not None and issubclass(typ, Exception) and not issubclass(typ, Done):
            check("%s did not run to its end — %s: %s" % (self.label, typ.__name__, str(val).split("\n")[0][:200]), False)
            return True

def bail(msg):
    print("  FAIL " + msg)
    sys.exit(1)

if not CHROME:
    bail("no headless Chrome (google-chrome / chromium, or $CHROME)")

WEB = ROOT
if PERTURB:
    WEB = tempfile.mkdtemp(prefix="peer-config-perturb-")
    for item in ("js", "m", "vendor"):
        shutil.copytree(os.path.join(ROOT, item), os.path.join(WEB, item))
    for item in os.listdir(ROOT):
        p = os.path.join(ROOT, item)
        if os.path.isfile(p) and item.endswith((".html", ".js", ".css", ".webmanifest")) or item == "VERSION":
            shutil.copy(p, os.path.join(WEB, item))
    if any(f == "swg-panel-server" for f, _, _ in PERTURBS[PERTURB]):   # a plant in the panel itself: it runs from the copy
        shutil.copy(SERVER, os.path.join(WEB, "swg-panel-server"))
        SERVER = os.path.join(WEB, "swg-panel-server")
    for f, old, new in PERTURBS[PERTURB]:
        src = open(os.path.join(WEB, f), encoding="utf-8").read()
        if src.count(old) != 1:
            bail("PERTURB %s: the anchor is not in %s exactly once (%d), so it cannot be undone" % (PERTURB, f, src.count(old)))
        open(os.path.join(WEB, f), "w", encoding="utf-8").write(src.replace(old, new))

# ── the panel and its fixture ─────────────────────────────────────────────────────────────────────────────────────────────
D = tempfile.mkdtemp(prefix="peer-config-")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
USER, PW = "qadmin", "peer-config-pw-1"
json.dump({"roster_path": D + "/state/users.json", "nodes_path": D + "/state/nodes.json", "stats_dir": D + "/stats",
           "store_configs": True, "config_dir": D + "/conf", "node_interval": 5}, open(D + "/fleet.json", "w"))
salt = os.urandom(16)
fd = os.open(D + "/auth", os.O_WRONLY | os.O_CREAT, 0o600)
os.write(fd, ("%s:pbkdf2_sha256$120000$%s$%s\n" % (USER, base64.b64encode(salt).decode(), base64.b64encode(
    hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, 120000)).decode())).encode())
os.close(fd)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=WEB, SWG_PANEL_HOST="127.0.0.1", SWG_PANEL_PORT=str(PORT),
           SWG_PANEL_AUTH=D + "/auth", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="", SWG_NFT_CLI_ONLY="1", SWG_PANEL_UNITS="",
           SWG_LATEST_URL="http://127.0.0.1:9/VERSION", HOME=D)
srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
ORIGIN = "http://127.0.0.1:%d" % PORT
COOKIE = ""

def call(method, path, body=None, token=None, timeout=60):
    global COOKIE
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = {"Content-Type": "application/json"}
    if COOKIE:
        h["Cookie"] = COOKIE
    if token:
        h["Authorization"] = "Bearer " + token
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    m = re.match(r"\s*(swgsess=[^;]+)", r.getheader("Set-Cookie") or "")
    if m:
        COOKIE = m.group(1)
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
            if call("GET", "/api/state", timeout=2)[0] in (200, 401):
                break
        except Exception:
            time.sleep(0.1)
    else:
        bail("the panel never came up: " + (srv.stderr.read(2000) if srv.poll() is not None else b"").decode("utf-8", "replace"))
    must(call("POST", "/api/login", {"username": USER, "password": PW}), "sign in")
    node = must(call("POST", "/api/nodes/create", {"name": "m-node", "endpoint_host": "203.0.113.9"}), "node create")["data"]
    NID, TOKEN = node["id"], node["token"]
    IFACES = {"awg1": ("10.8.0", 51820), "awg2": ("10.71.0", 51821)}
    GONE = set()                                # interfaces the node has stopped reporting
    MINT = {}                                   # (iface, password) -> ip: what a csqtt / WDTT server mints, as its read-back says

    def roster():
        return (must(call("GET", "/api/state"), "state").get("data") or {}).get("roster", {}).get("peers", {})
    def snapshot():
        now = int(time.time()); peers = roster(); ifs = {}; back = {"csqtt": {}, "wdtt": {}}
        for ifn, (net, port) in IFACES.items():
            if ifn not in GONE:
                ifs[ifn] = {"peers": [{"public_key": p["pubkey"], "allowed_ips": t["ip"].split("/")[0] + "/32", "endpoint": "", "rx_bytes": 0, "tx_bytes": 0,
                                       "rx_speed": 0, "tx_speed": 0, "last_handshake": 0, "handshake_age": None, "online": False}
                                      for p in peers.values() for t in p.get("targets", []) if t.get("iface") == ifn and t.get("ip")],
                            "meta": {"listen_port": port, "address": net + ".1/24", "subnet": net + ".0/24", "type": "awg", "tool": "awg",
                                     "public_key": base64.b64encode((ifn * 11)[:32].encode()).decode(), "endpoint": "203.0.113.9:%d" % port,
                                     "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}}}
        for p in peers.values():
            for t in p.get("targets", []):
                pw = p.get("%s_password" % t.get("type")) or ""
                if t.get("type") in back and pw:
                    ip = MINT.setdefault((t["iface"], pw), "10.9.0.%d" % (15 + len(MINT)))
                    back[t["type"]].setdefault(t["iface"], {})[pw] = {"ip": ip, "online": False, "rx_speed": 0, "tx_speed": 0}
        return {"hostname": "m-node", "generated_at": now, "noded_version": VERSION, "kind": "baremetal", "interfaces": ifs,
                "turn_proxies": [], "node_ips": ["203.0.113.9"], "node_ifaces": ["eth0"], "lans": [], "csqtt_lines": ["2.1", "2.5"],
                "csqtt": [{"iface": "csqtt25", "fork": "csqtt", "line": "2.5", "port": 53478, "passwords": back["csqtt"].get("csqtt25", {})}],
                "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "port": 53479, "passwords": back["wdtt"].get("wdtt1", {})}],
                "health": {"cpu_pct": 12, "mem_used": 1 << 30, "mem_total": 4 << 30, "disk_used": 10 << 30, "disk_total": 40 << 30, "ncpu": 2, "uptime": 99999}}
    def sync():
        return call("POST", "/api/node/sync", {"snapshot": snapshot()}, token=TOKEN, timeout=60)
    must(sync(), "first sync")
    must(call("POST", "/api/csqtt/set", {"node": NID, "iface": "csqtt25", "listen": "0.0.0.0:53478", "tun_addr": "10.9.0.1/24", "line": "2.5"}), "csqtt server")
    must(call("POST", "/api/wdtt/set", {"node": NID, "iface": "wdtt1", "listen": "0.0.0.0:53479", "wg_addr": "10.10.0.1/24"}), "WDTT server")
    must(sync(), "second sync")
    def keep_syncing():
        while not stop.wait(1):
            try:
                sync()
            except Exception:
                pass
    threading.Thread(target=keep_syncing, daemon=True).start()

    br = Browser()
    tab = Tab(br)
    br.send("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False}, session=tab.s)
    br.send("Page.addScriptToEvaluateOnNewDocument", {"source": "try { localStorage.setItem('swg-lang', 'en'); } catch (_) {}"}, session=tab.s)
    MOD = "(async n => import(performance.getEntriesByType('resource').map(r => r.name).find(u => new RegExp('/js/' + n + '\\\\.js\\\\?v=').test(u))))"
    def ev(module, body, timeout=40):
        return tab.ev("(async () => { const M = await %s(%s), S = await %s('store'), C = await %s('crypto'); %s })()"
                      % (MOD, json.dumps(module), MOD, MOD, body), timeout=timeout)
    def until(expr, secs, what):
        end = time.time() + secs
        while time.time() < end:
            try:
                if tab.ev(expr, timeout=10):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise TimeoutError(what)
    def app_up():
        until("!!(window.__swgBooted && !window.__was && !document.body.classList.contains('loggedout') && document.querySelector('#view > .screen'))", 40, "the app")
        # __swgBooted is set right after the first render, and App registers its modal renderer in an effect after the first frame: a
        # sheet opened in between is on the stack, not drawn. Measured 9 ms, 39 at 6x CPU: too short for a person, not for this script.
        tab.ev("new Promise(r => setTimeout(r, 250))")
        ev("store", "await S.Store.poll(); return 1;")
    def reload():
        tab.ev("window.__was = 1")               # the page being left: a boot flag read from it would be no boot at all
        br.send("Page.reload", {}, session=tab.s)
        app_up()
    def field(sel, val):
        tab.ev("document.querySelector(%s).focus()" % json.dumps(sel))
        br.send("Input.insertText", {"text": val}, session=tab.s)
    def sign_in():
        tab.goto(ORIGIN + "/")
        until("!!document.querySelector('.login-card input[autocomplete=username]')", 30, "the sign-in card")
        field(".login-card input[autocomplete=username]", USER)
        field(".login-card input[type=password]", PW)
        tab.ev("window.__was = 1; document.querySelector('.login-card button[type=submit]').click()")   # it reloads the page
        app_up()
    def log_out():
        tab.ev("document.querySelector('#acct-btn').click()")
        until("[...document.querySelectorAll('.overlay.show button')].some(b => b.textContent.trim() === 'Log out')", 10, "the log out confirm")
        tab.ev("[...document.querySelectorAll('.overlay.show button')].find(b => b.textContent.trim() === 'Log out').click()")
        until("!!document.querySelector('.login-card')", 20, "the sign-in card after logging out")
    SHEET = "[...document.querySelectorAll('.overlay.show .sheet')].pop()"
    def sheet():
        return tab.ev("""(() => { const s = %s; if (!s) return null;
          const bs = [...s.querySelectorAll('button')], sv = bs.find(b => b.textContent.trim() === 'Save');
          return {banner: s.textContent.includes("private key isn't available"), door: !!s.querySelector('.unlockpanel'),
                  qr: bs.some(b => b.textContent.trim() === 'QR'),
                  gear: !!s.querySelector('.topt-gear'), save: !!sv && !sv.disabled}; })()""" % SHEET)
    def settled():
        # the unlock draws itself once the server has said a vault exists: before that, a sheet without it proves nothing
        tab.ev("fetch('/api/sub/vault').then(() => new Promise(r => setTimeout(r, 250)))")
        return sheet()
    SAVE_ON = "(() => { const sv = [...%s.querySelectorAll('button')].find(b => b.textContent.trim() === 'Save'); return !!sv && !sv.disabled; })()" % SHEET
    ACT = "%s.querySelector('.sheet-foot .btn-primary')" % SHEET
    WARN = "([...%s.querySelectorAll('.notice.warn')].map(n => n.textContent).find(t => t.includes('private key')) || '')" % SHEET
    def watch_toasts():
        tab.ev("window.__toasts = []; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => window.__toasts.push(n.textContent)))).observe(document.querySelector('#toasts'), {childList: true}); 1")
    ENTER = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
    def unlock(password):
        tab.ev("(() => { const i = %s.querySelector('.unlockpanel input[type=password]'); i.focus(); i.select(); })()" % SHEET)
        br.send("Input.insertText", {"text": password}, session=tab.s)
        br.send("Input.dispatchKeyEvent", dict(ENTER, type="keyDown", text="\r"), session=tab.s)
        br.send("Input.dispatchKeyEvent", dict(ENTER, type="keyUp"), session=tab.s)
    def close_all():
        ev("ui", "M.closeAllModals(); return 1;")
    def qr_cards(pid):
        """The peer's QR sheet: each WireGuard deployment's card by interface, "QR" or what it says instead."""
        ev("peer-ui", "M.openPeerConfigs(S.Store.peer(%s)); return 1;" % json.dumps(pid))
        until("(() => { const s = %s; return !!s && !!s.querySelector('.deploy') && ![...s.querySelectorAll('.qr-none')].some(n => n.textContent.includes('loading')); })()" % SHEET, 15, "the QR cards")
        out = tab.ev("""(() => Object.fromEntries([...%s.querySelectorAll('.deploy')].map(d => [(d.querySelector('.deploy-head .tg, .tg') || {}).textContent.trim(),
            d.querySelector('.qr-none') ? d.querySelector('.qr-none').textContent : 'QR'])))()""" % SHEET)
        close_all()
        return out
    def open_edit(pid, stay=False):
        ev("sheets-crud", "M.openEditPeer(S.Store.peer(%s)); return 1;" % json.dumps(pid))
        until("(() => { const s = %s; return !!s && (!!s.querySelector('.topt-gear') || s.textContent.includes(\"private key isn't available\")); })()" % SHEET, 15, "the edit sheet's lookup")
        st = sheet()
        if not stay:
            close_all()
        return st
    def good(st):
        return bool(st) and not st["banner"] and st["qr"] and st["gear"]
    def marked(pid):
        return pid in json.loads(tab.ev("localStorage.getItem('swg-sub-noconf') || '{}'"))
    def stored(pid):
        return bool((must(call("GET", "/api/sub/blob?peer_id=" + pid), "blob").get("data") or {}).get("sec"))
    def tick(ifn):
        tab.ev("[...document.querySelectorAll('.overlay.show .targetopt')].find(r => r.querySelector('.tp').textContent.trim() === %s).querySelector('.topt-main').click()" % json.dumps(ifn))
    def addresses_in(keyed=True):
        if keyed:
            until("(() => { const f = [...document.querySelectorAll('.overlay.show input.topt-ip')]; return f.length && f.every(i => i.value); })()", 10, "an address")
        # The row shows the address one effect before the sheet holds it (a click in between reads "Invalid address"), and Preact
        # flushes effects within 100 ms: a timer set here, on the page's own event loop, fires after that one.
        tab.ev("new Promise(r => setTimeout(r, 250))")
    def new_peer(name, ifaces, kept=True):
        """Through the New peer sheet: the browser mints the key and publishes it, as it does for an operator. kept=False: a peer
        with no key (csqtt / WDTT only), so there is nothing published to wait for."""
        uid = must(call("POST", "/api/users/create", {"name": name}), "user")["data"]["id"]
        ev("sheets-crud", "await S.Store.poll(); M.openCreatePeer({user_id: %s}); return 1;" % json.dumps(uid))
        until("!!document.querySelector('.overlay.show .targetopt')", 15, "the target rows")
        for ifn in ifaces:
            tick(ifn)
        addresses_in(kept)
        tab.ev("[...document.querySelectorAll('.overlay.show button')].find(b => b.textContent.trim() === 'Create peer').click()")
        pid = None
        for _ in range(150):
            pid = next((p["id"] for p in roster().values() if p.get("user_id") == uid), None)
            if pid and (stored(pid) or not kept):
                break
            time.sleep(0.1)
        if not (pid and (stored(pid) or not kept)):
            raise TimeoutError("the new peer's key on the panel")
        until("(async () => { const S = await %s('store'); await S.Store.poll(); const p = S.Store.peer(%s); return !!p && !String(p.id).startsWith('tmp_'); })()" % (MOD, json.dumps(pid)), 15, "the peer in the store")
        return uid, pid
    def blobs_of(uid):
        return D + "/state/subs/blobs/%s.json" % uid

    # A panel's first sign-in creates the vault and shows its key once
    sign_in()
    until("!!document.querySelector('.overlay.show .vaultprompt')", 20, "the new vault's key")
    tab.ev("document.querySelector('.overlay.show .sheet-foot .btn-primary, .overlay.show .btn-primary').click()")
    until("!document.querySelector('.overlay.show')", 10, "the key sheet closing")

    print("\n[1] the report: awg1 + csqtt25, Edit, log out, sign in, Edit")
    with guard("[1]"):
        uid, pid = new_peer("report", ["awg1", "csqtt25"])
        check("[1] before logging out the sheet has the config", good(open_edit(pid)))
        log_out(); sign_in()
        check("[1] the vault is open after signing in, as the report's panel was", ev("store", "return !!C.subSKCached();"))
        st = open_edit(pid)
        check("[1] after signing in: no banner, the QR, the gear", good(st), st)
        # right after the first open: on the next, the deployment that hit clears a mark and the 30 s memory keeps the miss from writing one
        check("[1] no \"no config\" mark on the peer", not marked(pid))
        st = open_edit(pid)
        check("[1] …and on the next open", good(st), st)
        check("[1] the key was on the panel all along", stored(pid))

    print("\n[2] WDTT, and no logout: a reload and two opens")
    with guard("[2]"):
        uid, pid = new_peer("wdtt", ["awg1", "wdtt1"])
        reload()
        check("[2] the first open has the config", good(open_edit(pid)))
        check("[2] no mark on the peer", not marked(pid))
        st = open_edit(pid)
        check("[2] the second too", good(st), st)

    print("\n[3] an interface the node stopped reporting")
    with guard("[3]"):
        uid, pid = new_peer("gone", ["awg1", "awg2"])
        GONE.add("awg2")
        until("(async () => { const S = await %s('store'); await S.Store.poll(); return !S.Store.ifaceMeta(%s, 'awg2'); })()" % (MOD, json.dumps(NID)), 15, "the node dropping awg2")
        reload()
        check("[3] its other deployment's config is still read", good(open_edit(pid)))
        check("[3] no mark on the peer", not marked(pid))
        st = open_edit(pid)
        check("[3] …on the next open as well", good(st), st)
        c = qr_cards(pid)
        check("[3] the gone one's QR card says the node no longer reports it, not re-issue", "no longer reports" in c.get("awg2", "") and c.get("awg1") == "QR", c)
        GONE.discard("awg2")
        until("(async () => { const S = await %s('store'); await S.Store.poll(); return !!S.Store.ifaceMeta(%s, 'awg2'); })()" % (MOD, json.dumps(NID)), 15, "awg2 back")
        c = qr_cards(pid)
        check("[3] back, and reopened at once: its QR", c.get("awg2") == "QR", c)

    print("\n[4] one failed read of the escrow")
    with guard("[4]"):
        uid, pid = new_peer("blip", ["awg1"])
        reload()
        ev("store", "C.subUsersForget(); return 1;")   # its 4 s cache would answer instead
        tab.ev("(() => { const f = window.fetch; window.__fetch = f; window.fetch = (u, ...a) => String(u.url || u).includes('/api/sub/users') ? Promise.reject(new Error('blip')) : f(u, ...a); })()")
        open_edit(pid)
        c = qr_cards(pid)
        tab.ev("window.fetch = window.__fetch; 1")
        check("[4] it leaves no mark on the peer", not marked(pid))
        check("[4] the QR card says the panel couldn't be reached, not re-issue", "Couldn't reach the panel" in c.get("awg1", ""), c)
        tab.ev("new Promise(r => setTimeout(r, 4200))")   # the records' 4 s cache holds the failed read, and the card says so till then
        c = qr_cards(pid)
        check("[4] once the read works, the QR is back, with no reload", c.get("awg1") == "QR", c)
        reload()
        st = open_edit(pid)
        check("[4] after a reload the config is back", good(st), st)

    print("\n[5] a peer with nothing stored")
    with guard("[5]"):
        uid, pid = new_peer("nokey", ["awg1"])
        kept = json.load(open(blobs_of(uid)))
        json.dump({k: v for k, v in kept.items() if k != pid}, open(blobs_of(uid), "w"))
        reload()
        open_edit(pid, stay=True)
        st = settled()
        close_all()
        check("[5] the banner says so, no QR, and no unlock on a vault that is open", bool(st) and st["banner"] and not st["qr"] and not st["door"], st)
        c = qr_cards(pid)
        check("[5] its QR card says re-issue: here that is the answer", "No stored config" in c.get("awg1", ""), c)
        json.dump(kept, open(blobs_of(uid), "w"))      # another browser publishes the key, a later unlock does
        reload()
        st = open_edit(pid)
        check("[5] the key reaches the panel: the sheet has the config", good(st), st)

    print("\n[6] a mark an older build left")
    with guard("[6]"):
        uid, pid = new_peer("oldmark", ["awg1", "csqtt25"])
        pk = roster()[pid]["pubkey"]
        tab.ev("localStorage.setItem('swg-sub-noconf', %s); localStorage.setItem('swg-sub-noconf-v', '2'); 1" % json.dumps(json.dumps({pid: pk})))
        reload()
        check("[6] it is dropped at load", not marked(pid))

    print("\n[7] the backfill's own note")
    with guard("[7]"):
        uid, pid = new_peer("note", ["awg1"])
        pk = roster()[pid]["pubkey"]
        tab.ev("localStorage.setItem('swg-sub-noconf', %s); 1" % json.dumps(json.dumps({pid: pk})))
        reload()
        check("[7] the note is there", ev("store", "return C.subNoConfHas(%s, %s);" % (json.dumps(pid), json.dumps(pk))))
        st = open_edit(pid)
        check("[7] a lookup asks anyway, and has the config", good(st), st)
        check("[7] …and clears the note", not marked(pid))

    print("\n[8] Rotate on a mixed peer: Save is the operator's")
    with guard("[8]"):
        uid, pid = new_peer("rotate", ["awg1", "csqtt25"])
        LIVE = "(async () => { const S = await %s('store'); await S.Store.poll(); const t = S.Store.peer(%s).targets.find(t => t.iface === 'csqtt25'); return t.ip; })()" % (MOD, json.dumps(pid))
        until(LIVE, 15, "the csqtt read-back")
        addr0 = tab.ev(LIVE)
        reload()
        st = open_edit(pid, stay=True)
        check("[8] Save is off on a sheet nobody touched", not st["save"], st)
        watch_toasts()
        ROT = "[...%s.querySelectorAll('button')].find(b => b.textContent.trim() === 'Rotate credentials')" % SHEET
        pk = roster()[pid]["pubkey"]
        tab.ev(ROT + ".click()")
        until("(() => { const s = %s; return !!s && !s.querySelector('.topt-main, .topt-gear'); })()" % SHEET, 10, "the Rotate confirm")
        tab.ev(ROT + ".click()")
        for _ in range(100):
            if roster()[pid]["pubkey"] != pk:
                break
            time.sleep(0.1)
        until("window.__toasts.some(t => t.includes('Credentials rotated'))", 15, "the rotate finishing")
        check("[8] the rotate was real: a new key", roster()[pid]["pubkey"] != pk)
        ip = ev("store", "return S.Store.peer(%s).targets.find(t => t.iface === 'csqtt25').ip;" % json.dumps(pid))
        st = sheet()
        check("[8] the csqtt address is blank or new, and Save stays off", ip != addr0 and bool(st) and not st["save"], [ip, st])
        until("(async () => { const a = await %s; return !!a && a !== %s; })()" % (LIVE, json.dumps(addr0)), 15, "the new read-back")
        time.sleep(0.2)
        st = sheet()
        check("[8] …and when it comes back different", bool(st) and not st["save"], st)
        ip0 = roster()[pid]["targets"][0]["ip"].split("/")[0]
        tab.ev("(() => { const i = [...%s.querySelectorAll('input')].find(x => x.value === %s); i.value = '10.8.0.77'; i.dispatchEvent(new Event('input', {bubbles: true})); })()" % (SHEET, json.dumps(ip0)))
        until(SAVE_ON, 5, "Save after a real edit")
        tab.ev("[...%s.querySelectorAll('button')].find(b => b.textContent.trim() === 'Save').click()" % SHEET)
        until("window.__toasts.some(t => t.startsWith('Peer updated') || t.startsWith('Saved'))", 10, "the save's toast")
        toasts = tab.ev("window.__toasts")
        check("[8] a real address change saves, with no failure", any(t.startswith("Peer updated") for t in toasts) and not any("couldn't be persisted" in t for t in toasts), toasts)
        check("[8] …and is in the roster", roster()[pid]["targets"][0]["ip"].split("/")[0] == "10.8.0.77", roster()[pid]["targets"])
        close_all()

    print("\n[9] a locked vault")
    with guard("[9]"):
        uid, pid = new_peer("locked", ["awg1", "csqtt25"])
        def locked_sheet():
            reload()
            ev("store", "C.lockVault(); return 1;")
            open_edit(pid, stay=True)
            until("!!%s.querySelector('.unlockpanel')" % SHEET, 10, "the unlock on the sheet")
        locked_sheet()
        st = sheet()
        check("[9] the sheet has the unlock, next to the warning, and no QR yet", st["door"] and st["banner"] and not st["qr"], st)
        check("[9] no mark on the peer", not marked(pid))
        unlock(PW)
        until("!!%s.querySelector('.topt-gear')" % SHEET, 10, "the open sheet's config after the unlock")
        st = sheet()
        check("[9] Enter unlocks, and the open sheet has its config: no banner, the QR, the gear", good(st) and not st["door"], st)
        tab.ev("%s.querySelector('.sheet-head .x').click()" % SHEET)
        until("!document.querySelector('.overlay.show') || !!document.querySelector('.overlay.show .discard-msg')", 5, "the sheet closing")
        check("[9] the password was no edit: the sheet closes without asking", not tab.ev("!!document.querySelector('.overlay.show .discard-msg')"))
        locked_sheet()
        watch_toasts()
        title = roster()[pid].get("title")
        field(".overlay.show .sheet input[maxlength]", "typed, not saved")
        until(SAVE_ON, 5, "Save after the edit")
        unlock("not-the-password")
        until("window.__toasts.some(t => t.includes('unlock the Encryption Vault'))", 15, "the refusal")
        st = sheet()
        check("[9] a wrong password is refused, and saves nothing: the sheet is open, the edit still waits", bool(st) and st["door"] and st["save"] and roster()[pid].get("title") == title, [st, tab.ev("window.__toasts")])
        unlock(PW)
        until("!!%s.querySelector('.topt-gear')" % SHEET, 15, "the config after the right password")
        st = sheet()
        check("[9] the right one unlocks, and saves nothing either", good(st) and st["save"] and roster()[pid].get("title") == title, [st, tab.ev("window.__toasts")])
        close_all()

    print("\n[10] adding a target on a locked vault")
    with guard("[10]"):
        uid, pid = new_peer("targets", ["awg1"])
        pk = roster()[pid]["pubkey"]
        reload()
        ev("store", "C.lockVault(); return 1;")
        ev("sheets-crud", "M.openAddTarget(S.Store.peer(%s)); return 1;" % json.dumps(pid))
        # the picker seeds the deployed targets in an effect, over any row clicked before it: the deployed row picked is that seed
        until("!!document.querySelector('.overlay.show .targetopt.sel')", 15, "the deployed target seeded")
        tick("csqtt25")
        until("!%s.disabled" % ACT, 5, "the keyless row ticked")   # Save lit and the warning are one render: no wait after this
        check("[10] a keyless target has no key to miss: no warning", not tab.ev(WARN), tab.ev(WARN))
        tick("awg2")
        until(WARN, 5, "the warning")
        addresses_in()
        w = tab.ev(WARN)
        check("[10] a target with a key: the warning, with no advice to rotate", "otate" not in w and "e-issue" not in w, w)
        watch_toasts()
        tab.ev(ACT + ".click()")
        until("window.__toasts.some(t => t.startsWith('Peer targets updated'))", 10, "the save")
        # it closes itself after its refresh, which takes a while under load, and a sheet opened before that is the one it closes
        until("!document.querySelector('.overlay.show')", 15, "the Targets sheet closing itself")
        p = roster()[pid]
        check("[10] it saves on a locked vault: the targets, the same key", p["pubkey"] == pk and {t["iface"] for t in p["targets"]} == {"awg1", "awg2", "csqtt25"}, p["targets"])
        ev("peer-ui", "M.openPeerConfigs(S.Store.peer(%s)); return 1;" % json.dumps(pid))
        until("(() => { const s = %s; return !!s && !!s.querySelector('.unlockpanel'); })()" % SHEET, 10, "the QR sheet's unlock")
        check("[10] the QR card says locked, not re-issue", tab.ev("(s => s.includes('The Encryption Vault is locked') && !s.includes('No stored config'))(%s.textContent)" % SHEET))
        unlock(PW)
        until("!%s.querySelector('.unlockpanel')" % SHEET, 10, "the QR sheet after the unlock")
        check("[10] the unlock gives the new target its config, and nothing was rotated",
              ev("store", "return !!(await C.getConfig(%s, %s, 'awg2'));" % (json.dumps(pk), json.dumps(NID))) and roster()[pid]["pubkey"] == pk)
        close_all()

    print("\n[11] a peer with no key adds WireGuard")
    with guard("[11]"):
        uid, pid = new_peer("keyless", ["csqtt25"], kept=False)
        pw0 = roster()[pid].get("csqtt_password")
        reload()
        ev("sheets-crud", "M.openAddTarget(S.Store.peer(%s)); return 1;" % json.dumps(pid))
        until("!!document.querySelector('.overlay.show .targetopt.sel')", 15, "the deployed target seeded")
        tick("awg2")
        addresses_in()
        check("[11] no warning: Save makes the key, as for a new peer", not tab.ev(WARN), tab.ev(WARN))
        watch_toasts()
        tab.ev(ACT + ".click()")
        until("window.__toasts.some(t => t.startsWith('Peer targets updated'))", 10, "the save")
        until("!document.querySelector('.overlay.show')", 15, "the Targets sheet closing itself")
        p = roster()[pid]
        check("[11] it saves: a key and a PSK now, and the csqtt password as it was",
              bool(p.get("pubkey") and p.get("psk")) and p.get("csqtt_password") == pw0 and {t["iface"] for t in p["targets"]} == {"csqtt25", "awg2"}, p)
        check("[11] its private key went to the panel encrypted", stored(pid))
        GET = "return (await C.getConfig(%s, %s, 'awg2')) || '';" % (json.dumps(p.get("pubkey", "")), json.dumps(NID))
        shown = ev("store", GET)
        c = qr_cards(pid)
        check("[11] the new deployment has its QR at once", c.get("awg2") == "QR", c)
        reload()
        key = lambda conf: next((l for l in conf.splitlines() if l.startswith("PrivateKey")), None)
        check("[11] after a reload, the QR from the kept key: the key shown", bool(key(shown)) and key(ev("store", GET)) == key(shown))
        st, o = call("POST", "/api/peers/add-target", {"peer_id": pid, "target": {"node": NID, "iface": "awg1", "ip": "10.8.0.99"},
                                                       "pubkey": base64.b64encode(os.urandom(32)).decode()})
        check("[11] a second key for it is refused, not dropped", st == 409 and o.get("code") == "key_changed", [st, o])

    print("\n[12] the unlock follows the vault, not the setting")
    with guard("[12]"):
        VAULT = D + "/state/subs/vault.json"
        uid, pid = new_peer("nodoor", ["awg1"])
        reload()
        ev("store", "C.lockVault(); return 1;")
        os.rename(VAULT, VAULT + ".gone")
        open_edit(pid, stay=True)
        st = settled()
        close_all()
        os.rename(VAULT + ".gone", VAULT)
        check("[12] no vault: the warning alone", bool(st) and st["banner"] and not st["door"], st)
        must(call("POST", "/api/panel/settings", {"store_configs": "off"}), "store_configs off")
        reload()
        ev("store", "C.lockVault(); return 1;")
        open_edit(pid, stay=True)
        st = settled()
        check("[12] store_configs off, a config kept from before: the sheet has the unlock", bool(st) and st["banner"] and st["door"], st)
        unlock(PW)
        until("!!%s.querySelector('.topt-gear')" % SHEET, 15, "the kept config after the unlock")
        st = sheet()
        check("[12] …and the unlock brings it back", good(st) and not st["door"], st)
        close_all()
except Done:
    pass
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
