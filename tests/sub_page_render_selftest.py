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
      A control proves the probe SEES a scheme link fire (the WDTT cell's one-tap Android app, WDTT-Plus by the operator's choice)
  [4] the console is clean on every render (no exception, no console.error)
  [5] Connections is a desktop button only (operator, 2026-09-17). On a phone no page carries one — not the networks page
      (Cara's office router carries 192.168.50.0/24 on the node, open to everyone there), not a blocked device's page (Anna's
      old tablet) — and the networks page's heading opens the picker instead, as a device's title does. Control: the same
      subscription on a desktop window shows the one Connections button in its header
  [6] a fork is named by its catalog label, never its id: the samosvalishe proxy's cell says hack-diaz (its repos moved,
      the id stays in every node's unit names), and no cell on any OS or language says samosvalishe
  [7] a WDTT fork's own app is its default (operator, 2026-10-14): the WDTT cell on Android hands out amurcanov's WDTT —
      XXcipherX's app, which stood in for it, is hidden with its deleted repository — and its Start shows the import steps
  [9] an app whose own tunnel is WireGuard only (VK TURN Proxy on iOS, `awg: false`) is never handed out for an AmneziaWG
      interface behind a proxy; the WireGuard interface's proxy still offers it; FreeTurn keeps the AmneziaWG one on Android
  [10] a proxy of a HIDDEN fork a node still runs (MYSOREZ) keeps its users' app: its Android cell offers the MYSOREZ app,
      hidden from every visible fork (hack-diaz's cells on the same interface do not offer it)
  [11] csqtt 2.1 and 2.5 do not speak to each other: a 2.5 server (Dana's csqtt2, line 2.5) is offered only an app of its
      line — on Android the CSQTT app, though the operator's default is La Lune (2.1 only), and on iOS nothing (VK TURN Proxy
      speaks 2.1); her 2.1 server keeps both. Once the CSQTT app's release is of the other line (no 2.5 release yet), the
      2.5 server offers no app at all rather than one that cannot connect; the line reaches the page through swg-sub
  [12] torrents (1.8.11 S4b): q-node lets them through (Direct) and Boris's awg1 blocks them. Every one of Anna's cells, on every
      OS and in both languages, carries the torrent marker in its badge row, labelled with the client setting for full speed
      (in the page's language); a tap opens that text in a bubble and a second tap closes it; Boris's awg1 cell carries none
      while his csqtt1 cell does; Anna's blocked device's page carries none. The plain-mode turtle (a cacggghp proxy) opens its
      own text in the same bubble on a tap; the connection picker shows both icons, as icons, not buttons. The device's own
      incoming port (S12, Part C): where q-node reports forwarding awg0, Anna's AmneziaWG cells' bubble opens with port 20016
      and the address peers reach (in both languages); her WireGuard cell (wg0, not forwarded) and Boris's cells carry none
  [8] an app from the server's own repository follows the server's running version (operator, 2026-10-14): csqtt
      2.1.9-4 while v2.5.1 is the latest — the CSQTT app's bubble offers v2.1.9 (our csqtt-app-2.1.9) and says it matches; amurcanov's WDTT 1.2.4-3
      → v1.2.4 and the hack-diaz CLI on Linux → the proxy's v4.0.3 (both versions reach the page); FreeTurn on that proxy
      is not handed the CLI release's Android binary (another repository's app keeps its own versioning)

Needs google-chrome (or $CHROME) and node (seals the fixture secret). A missing browser is a FAIL, never a skip: a gate that
cannot run has not passed.

Run: python3 tests/sub_page_render_selftest.py        (0 = pass)
     --perturb-macos      serves a sub.js whose csqtt branch has no client-for-this-OS guard → RED on [1]
     --perturb-by         serves a sub.js with the badge's " by " hard-coded again → RED on [2]
     --perturb-autostart  serves a catalog where La Lune on Android does not autostart → RED on [3]
     --perturb-tabs       serves a sub.js that builds a tab for every group, page or not → RED on [1]'s Turn-tab check
     --perturb-copy       serves a sub.js whose one-tap csqtt Start no longer copies the link → RED on [3]
     --perturb-netswitch  serves a sub.js whose networks page carries a Connections button again → RED on [5]
     --perturb-forkname   serves a sub.js that names a fork by its internal id again → RED on [6]
     --perturb-awgapp     serves a sub.js that hands VK TURN Proxy to an AmneziaWG interface again → RED on [9]
     --perturb-hiddenmap  serves a catalog where a hidden fork drops its hidden apps too → RED on [10]
     --perturb-pin        serves a sub.js that hands out the latest release whatever the server runs → RED on [8]
     --perturb-guard      serves a sub.js that pins any app of a server, its repository or not → RED on [8]
     --perturb-line       serves a sub.js that offers a csqtt server an app of another line → RED on [11]
     --perturb-ownline    serves a sub.js that offers the CSQTT app of the other line when no release of the server's is out → RED on [11]
     --perturb-chipline   serves a sub.js whose csqtt card no longer names the server's version → RED on [11]
     --perturb-turtlespan serves a sub.js whose turtle is the old span with a title again → RED on [12]
     --perturb-scrollclose serves a sub.js whose bubble closes on its own scroll → RED on [12]
     --perturb-pickmark   serves a sub.js whose picker copies the badge rows with their marker buttons → RED on [12]
     --perturb-pickshort  serves a sub.js whose picker icons show the short label as their tooltip → RED on [12]
     --perturb-p2pall     serves a sub.js that draws the torrent marker on every cell, allowed or not → RED on [12]
     --perturb-p2pport    serves a sub.js whose torrent bubble leaves out the device's incoming port → RED on [12]
     --perturb-subport    runs a swg-sub that never puts the device's incoming port on a deployment → RED on [12]
     --perturb-xxsub      the catalog and sub.js of before 2026-10-14 (XXcipherX's app stands in for a WDTT fork's own) → RED on [7]
   A perturbation prints "PERTURB OK" and exits 0 when something went red, exits 1 when nothing did — or when its anchor is
   gone (a perturbation that cannot be applied proves nothing).
"""
import base64, fcntl, hashlib, importlib.machinery, importlib.util, json, os, re, secrets, select, shutil, socket, subprocess, sys
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
P_FORKNAME = "--perturb-forkname" in sys.argv
P_XXSUB = "--perturb-xxsub" in sys.argv
P_PIN = "--perturb-pin" in sys.argv
P_AWGAPP = "--perturb-awgapp" in sys.argv
P_HIDDENMAP = "--perturb-hiddenmap" in sys.argv
P_GUARD = "--perturb-guard" in sys.argv
P_LINE = "--perturb-line" in sys.argv
P_OWNLINE = "--perturb-ownline" in sys.argv
P_CHIPLINE = "--perturb-chipline" in sys.argv
P_P2PALL = "--perturb-p2pall" in sys.argv
P_P2PPORT = "--perturb-p2pport" in sys.argv
P_SUBPORT = "--perturb-subport" in sys.argv
P_PICKMARK = "--perturb-pickmark" in sys.argv
P_PICKSHORT = "--perturb-pickshort" in sys.argv
P_SCROLLCLOSE = "--perturb-scrollclose" in sys.argv
P_TURTLESPAN = "--perturb-turtlespan" in sys.argv
PERTURB = (P_P2PALL or P_P2PPORT or P_SUBPORT or P_PICKMARK or P_PICKSHORT or P_SCROLLCLOSE or P_TURTLESPAN or P_MACOS or P_BY or P_AUTO or P_TABS or P_COPY or P_NETSW or P_FORKNAME or P_XXSUB or P_PIN or P_AWGAPP or P_HIDDENMAP or P_GUARD
           or P_LINE or P_OWNLINE or P_CHIPLINE)

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
if P_HIDDENMAP:   # a hidden fork loses its hidden apps too (its running proxy's users lose theirs)
    P.TURN_GONE_CLIENTS = set(P.TURN_HIDDEN_CLIENTS)
if P_XXSUB:   # the app back in every WDTT fork's compat (the catalog before 2026-10-14) — the sub's substitution below needs it
    P.TURN_HIDDEN_CLIENTS = set()
# [8] each server's own release, as _turn_warm_pins leaves it (csqtt's latest is our v2.5.1): csqtt 2.1.9-4 → our
# csqtt-app-2.1.9 shown as v2.1.9, Dana's 2.5.1 → our csqtt-app-2.5.1 (v2.5.1), amurcanov's WDTT 1.2.4-3 → v1.2.4, the
# hack-diaz proxies' v4.0.3 → its CLI release (which also carries an Android binary)
PIN_APK = "https://github.com/SanityProtocol/swg-panel/releases/download/csqtt-app-2.1.9/CSQTT-universal.apk"
PIN25_APK = "https://github.com/SanityProtocol/swg-panel/releases/download/csqtt-app-2.5.1/CSQTT-2.5.1-universal.apk"
WDTT_APK = "https://github.com/amurcanov/proxy-turn-vk-android/releases/download/v1.2.4/WDTT-universal.apk"
CLI_LIN = "https://github.com/hackdiaz-dev/free-turn-proxy/releases/download/v4.0.3/client-linux-amd64"
CLI_AND = "https://github.com/hackdiaz-dev/free-turn-proxy/releases/download/v4.0.3/client-android-arm64"
P._RELEASE_INFO[("amurcanov", "csqtt")] = {"tag": "v2.5.1", "page": "https://github.com/SanityProtocol/swg-panel/releases/tag/csqtt-app-2.5.1",
    "assets": [{"name": "CSQTT-2.5.1-universal.apk", "url": PIN25_APK}]}
P._PLATFORM_ASSET[("amurcanov", "csqtt", "android")] = P._RELEASE_INFO[("amurcanov", "csqtt")]["assets"][0]["url"]
def _pin(tag, page, urls):
    return {"tag": tag, "page": page, "assets": [{"name": u.rsplit("/", 1)[1], "url": u} for u in urls.values()], "url": urls}
P._RELEASE_PIN[("amurcanov", "csqtt", "2.1.9-4")] = dict(_pin("v2.1.9", "https://github.com/SanityProtocol/swg-panel/releases/tag/csqtt-app-2.1.9", {"android": PIN_APK}),
                                                         src="SanityProtocol/swg-panel@csqtt-app-2.1.9")
P._RELEASE_PIN[("amurcanov", "csqtt", "2.5.1")] = dict(_pin("v2.5.1", "https://github.com/SanityProtocol/swg-panel/releases/tag/csqtt-app-2.5.1", {"android": PIN25_APK}),
                                                       src="SanityProtocol/swg-panel@csqtt-app-2.5.1")
P._RELEASE_PIN[("amurcanov", "proxy-turn-vk-android", "1.2.4-3")] = _pin("v1.2.4", "https://github.com/amurcanov/proxy-turn-vk-android/releases/tag/v1.2.4", {"android": WDTT_APK})
P._RELEASE_PIN[("hackdiaz-dev", "free-turn-proxy", "v4.0.3")] = _pin("v4.0.3", "https://github.com/hackdiaz-dev/free-turn-proxy/releases/tag/v4.0.3",
                                                                     {"linux": CLI_LIN, "android": CLI_AND})
P._PIN_WANTED = {("amurcanov", "csqtt"): {"2.1.9-4", "2.5.1"}, ("amurcanov", "proxy-turn-vk-android"): {"1.2.4-3"},
                 ("hackdiaz-dev", "free-turn-proxy"): {"v4.0.3"}}
catalog = P.turn_catalog_view(pins=True)   # serve.json's catalog, as write_sub_serve builds it
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
J("users.json", {"users": {"u1": {"name": "Anna", "vk_links": VK}, "u2": {"name": "Boris", "vk_links": VK[:1]}, "u3": {"name": "Cara"},
                           "u4": {"name": "Dana", "vk_links": VK[:1]}},
                 "peers": {
                     "p1": {"id": "p1", "user_id": "u1", "title": "laptop", "csqtt_password": "pw1csqtt", "wdtt_password": "pw1wdtt", "p2p_port": 20016,
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "wdtt1", "type": "wdtt"},
                                        {"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.2/32"},
                                        # [9] a plain WireGuard interface behind a second hack-diaz proxy
                                        {"node": "n1", "iface": "wg0", "type": "wg", "ip": "10.7.0.2/32"}]},
                     "p2": {"id": "p2", "user_id": "u2", "title": "phone", "csqtt_password": "pw2csqtt",
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "awg1", "type": "awg", "ip": "10.9.0.2/32"}]},
                     # [5] a router fronting a LAN, open to everyone on the node — Anna and Boris each get a networks page
                     "p3": {"id": "p3", "user_id": "u3", "title": "office router", "created_at": 1, "routes": ["192.168.50.0/24"],
                            "targets": [{"node": "n1", "iface": "awg1", "type": "awg", "ip": "10.9.0.5/32"}]},
                     # [11] a device on a 2.1 server (csqtt1) and a 2.5 one (csqtt2)
                     "p5": {"id": "p5", "user_id": "u4", "title": "tablet", "csqtt_password": "pw5csqtt",
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "csqtt2", "type": "csqtt"}]},
                     # [5] a blocked device: its page is a dead end with the device's name as the picker's trigger
                     "p4": {"id": "p4", "user_id": "u1", "title": "old tablet", "disabled": True,
                            "targets": [{"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.9/32"}]}}})
# [12] torrents leave q-node directly, except from awg1, whose own Torrents / P2P block is on
J("nodes.json", {"n1": {"name": "q-node", "endpoint_host": "203.0.113.7", "p2p": {"action": "direct"}, "ifaces": {"awg1": {"block": ["torrents"]}},
                        "csqtt": {"csqtt1": {"listen": "0.0.0.0:56002"}, "csqtt2": {"listen": "0.0.0.0:56003"}},
                        "wdtt": {"wdtt1": {"listen": "0.0.0.0:56000", "fork": "amurcanov", "wg_port": 56001}}}})
AWG = {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}
b64 = lambda n: base64.b64encode(os.urandom(n)).decode()
J("stats/stats-n1.json", {"interfaces": {
        "awg0": {"meta": {"public_key": b64(32), "listen_port": 51820, "endpoint": "203.0.113.7:51820", "subnet": "10.8.0.0/24", "awg_params": AWG}},
        "awg1": {"meta": {"public_key": b64(32), "listen_port": 51821, "endpoint": "203.0.113.7:51821", "subnet": "10.9.0.0/24", "awg_params": AWG}},
        "wg0": {"meta": {"public_key": b64(32), "listen_port": 51830, "endpoint": "203.0.113.7:51830", "subnet": "10.7.0.0/24"}}},
    "csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"},   # an older node's row: no line (2.1, filters nothing)
              {"iface": "csqtt2", "fork": "csqtt", "version": "2.5.1", "line": "2.5"}],
    "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.2.4-3"}],
    "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-1", "listen": "0.0.0.0:56100", "connect": "127.0.0.1:51820", "wrap_key": "k" * 64, "version": "v4.0.3"},
                     {"service": "vk-turn-proxy-samosvalishe-2", "listen": "0.0.0.0:56101", "connect": "127.0.0.1:51830", "wrap_key": "j" * 64, "version": "v4.0.3"},
                     # [12] a plain fork's proxy (cacggghp: no obfuscation) — its cell carries the turtle
                     {"service": "vk-turn-proxy-cacggghp-4", "listen": "0.0.0.0:56104", "connect": "127.0.0.1:51830", "wrap_key": "", "version": "v1.0.0"},
                     # [10] a proxy of a HIDDEN fork a node still runs (MYSOREZ, hidden 2026-10-14)
                     {"service": "vk-turn-proxy-MYSOREZ-3", "listen": "0.0.0.0:56102", "connect": "127.0.0.1:51830", "wrap_key": "m" * 64, "version": "v4.0.3"}],
    "net_carried": ["192.168.50.0/24"],
    "p2p_fwd": {"awg0": {"addr": "203.0.113.7", "taken": []}}})   # [12] S12: q-node forwards awg0's devices' own ports

SEAL = r"""
const [k, pt] = process.argv.slice(1);
const key = await crypto.subtle.importKey('raw', Buffer.from(k, 'hex'), {name: 'AES-GCM'}, false, ['encrypt']);
const iv = crypto.getRandomValues(new Uint8Array(12));
const ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key, new TextEncoder().encode(pt)));
const all = new Uint8Array(12 + ct.length); all.set(iv); all.set(ct, 12);
console.log(Buffer.from(all).toString('base64'));
"""
users_sub, links = {}, {}
for uid, pid in (("u1", "p1"), ("u2", "p2"), ("u4", "p5")):
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
    perturbed_web('if (!turnGetApp("csqtt", (tt.csqtt || {}).version, false, (tt.csqtt || {}).line)) return;', "", "the csqtt client-for-this-OS guard")
if P_LINE:
    perturbed_web('      if (lineGate && (cl.csqtt_lines || ["2.1"]).indexOf(line) < 0) return null;   // this app speaks another csqtt line\n', "",
                  "the csqtt line filter")
if P_OWNLINE:
    perturbed_web('      if (lineGate && own && srv && own[1] === srv.owner && !links.pinned && relLine !== line) return null;\n', "",
                  "the own app's release-line guard")
if P_TURTLESPAN:
    perturbed_web('srvRow.appendChild(noteMarker("scell-slow", TURTLE_SVG, t("slowMark"), t("slowPlain")));',
                  '{ var slow = el("span", "scell-slow"); slow.title = t("slowPlain"); slow.innerHTML = TURTLE_SVG; srvRow.appendChild(slow); }',
                  "the turtle as a marker")
if P_SCROLLCLOSE:
    perturbed_web("function _nbScroll(e) { if (_noteBubble && !_noteBubble.contains(e.target)) closeNoteBubble(); }",
                  "function _nbScroll(e) { closeNoteBubble(); }", "a scroll inside the bubble leaves it open")
if P_PICKSHORT:
    perturbed_web('icon.title = x.getAttribute("data-note") || ', 'icon.title = ', "the picker icon's tooltip being the whole note")
if P_PICKMARK:
    perturbed_web('            x.replaceWith(icon);\n', "", "the picker's badge copies turning their marker buttons into icons")
if P_P2PPORT:
    perturbed_web("      var fp = it.tgt.p2p_port, fd", "      var fp = 0, fd", "the device's incoming port in the torrent bubble")
if P_P2PALL:
    perturbed_web("      var srv = it.tgt.p2p && cc.el", "      var srv = true && cc.el", "the torrent marker only where torrents are allowed")
if P_CHIPLINE:
    perturbed_web('"CSQTT " + (cd.line || "2.1")', '"CSQTT"', "the csqtt chip's server version")
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
    perturbed_web('function tagBy(author) { return el("span", "scell-tag-by", t("by").replace("{author}", forkLabel(author))); }',
                  'function tagBy(author) { return el("span", "scell-tag-by", " by " + forkLabel(author)); }', "the badge's translated author word")
if P_FORKNAME:
    perturbed_web("function forkLabel(f) { var s = turnServer(f); return (s && s.label) || f; }",
                  "function forkLabel(f) { return f; }", "a fork named by its catalog label")
if P_AWGAPP:
    perturbed_web("      if (!has(links) || (awg && cl.awg === false)) return null;", "      if (!has(links)) return null;",
                  "a WireGuard-only app kept off an AmneziaWG interface")
if P_PIN:
    perturbed_web("      var u = pin && pin.url && pin.url[os];", "      var u = null;", "a server's own app following its version")
if P_GUARD:
    perturbed_web("      if (!ver || !m || !srv || m[1] !== srv.owner) return links;", "      if (!ver || !m || !srv) return links;",
                  "only an app from the server's own repository follows it")
if P_XXSUB:
    perturbed_web("""    // A WDTT fork's system default is its own app, the top of this rank (until 2026-10-14 XXcipherX's one-tap app
    // stood in where a fork's own could not open one-tap; its repository is gone — the panel's picker agrees).
""", """    if (srv && srv.kind === "wdtt" && ranked.length && !autostartOf(ranked[0]) && ranked.indexOf("xxcipher") >= 0) {
      var xcd = build("xxcipher"); if (xcd) return xcd;
    }
""", "a WDTT fork's own app as its default")

if P_SUBPORT:   # the page's own copy of swg-sub, the port's wiring removed
    _ss = open(SUB).read()
    if _ss.count("                    tg.update(_p2p_fwd_of(p, tg, describe))\n") != 1:
        print("PERTURB FAILED — the incoming port's wiring: its anchor is not in swg-sub exactly once"); sys.exit(1)
    SUB = os.path.join(D, "swg-sub")
    open(SUB, "w").write(_ss.replace("                    tg.update(_p2p_fwd_of(p, tg, describe))\n", ""))
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
      mode: pg.getAttribute("data-mode"), p2pn: pg.querySelectorAll(".scell-p2p").length,
      cells: [...pg.querySelectorAll(".scell")].map(c => ({
        tag: txt(c, ".scell-tag"), by: txt(c, ".scell-tag-by"), getapp: txt(c, ".scell-getapp"), role: txt(c, ".scell-role-if"),
        payload: txt(c, "pre.cfgtext"), fail: txt(c, ".cfg-fail"), text: c.textContent, p2p: (x => x ? x.getAttribute("aria-label") : null)(c.querySelector(".scell-p2p")),
        note: (x => x ? x.getAttribute("data-note") : null)(c.querySelector(".scell-p2p")),
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

def seek_js(mode, badge_has):
    """The page script both probes open with: find the `mode` page and seek it to the cell whose badge contains `badge_has`."""
    return r"""const pg = [...document.querySelectorAll('section.ppage')].find(p => p.getAttribute('data-mode') === %s);
      if (!pg) return 'no page';
      const cells = [...pg.querySelectorAll('.scell')];
      const i = cells.findIndex(c => ((c.querySelector('.scell-tag') || {}).textContent || '').includes(%s));
      if (i < 0) return 'no cell';
      pg._seek(i, null);""" % (json.dumps(mode), json.dumps(badge_has))

def start_on(tab, mode, badge_has):
    """Click Start on the cell of `mode` whose badge contains `badge_has`; return (clipboard writes, overlay steps, navigations)."""
    n0 = len(tab.mine("Page.frameRequestedNavigation"))
    c0 = len(tab.mine("Runtime.bindingCalled"))
    res = tab.ev(r"""(() => {
      %s
      pg.querySelector('.pbtn-start').click();
      // read the steps NOW: the handler shows them synchronously, and a one-tap fallback may replace this document soon after
      return {res: 'clicked', steps: [...document.querySelectorAll('.ph-overlay .ph-step')].map(s => s.textContent)};
    })()""" % seek_js(mode, badge_has))
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
        cs = [c for c in turn_cells(renders[(os_, "en")]) if (c["role"] or "") == "CSQTT 2.1"]   # Anna's csqtt1: no line → 2.1
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

    # [12] the torrent marker: where swg-sub says torrents may leave, and nowhere else
    P2P_WORDS = {"en": "Torrents work here", "ru": "Торренты здесь работают"}   # the marker's label; the bubble holds the setting
    for (os_, lang), r in sorted(renders.items()):
        live = [c for p in r["pages"] if p["mode"] not in ("nets", "dead") for c in p["cells"]]
        check("[12] %s/%s: every one of Anna's cells carries the torrent marker, labelled in the page's language" % (os_, lang),
              live and all(P2P_WORDS[lang] in (c["p2p"] or "") for c in live), [(c["tag"], (c["p2p"] or "")[:40]) for c in live])
    PORT_WORDS = {"en": "Incoming port 20016", "ru": "Входящий порт 20016"}
    for (os_, lang), r in sorted(renders.items()):
        got = [(p["mode"], PORT_WORDS[lang] in (c["note"] or "") and "203.0.113.7:20016" in (c["note"] or ""))
               for p in r["pages"] if p["mode"] in ("awg", "wg") for c in p["cells"]]
        check("[12] %s/%s: Anna's AmneziaWG cell's torrent note opens with her incoming port and the address peers reach; her "
              "WireGuard cell's (not forwarded) carries none" % (os_, lang),
              ("awg", True) in got and all(v == (m == "awg") for m, v in got), got)
    dead = [p for p in renders[("android", "en")]["pages"] if p["mode"] == "dead"]
    check("[12] …and her blocked device's page none", len(dead) == 1 and dead[0]["p2pn"] == 0, [(p["mode"], p["p2pn"]) for p in dead])
    awg1 = [c for p in rb["pages"] if p["mode"] == "awg" for c in p["cells"]]
    check("[12] Boris's awg1, which blocks torrents: no marker", len(awg1) == 1 and awg1[0]["p2p"] is None, [(c["tag"], c["p2p"]) for c in awg1])
    check("[12] …while his csqtt1 cell on the same node carries it", len(turn_cells(rb)) == 1 and turn_cells(rb)[0]["p2p"],
          [(c["tag"], c["p2p"]) for c in turn_cells(rb)])
    tab, _r = render("u1", "android", "en", phone=True)
    # A TAP AS A FINGER MAKES IT: pointerdown on the marker first (the outside-press handler must not take it for one), then click.
    TAP = r"""(() => { const m=[...document.querySelectorAll('.scell-p2p')].find(x => { const r=x.getBoundingClientRect();
      return r.width && r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight; });
      if (!m) return 'no marker in view'; m.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); m.click();
      const b=document.querySelector('.note-bubble'); return b ? b.textContent + '|' + m.getAttribute('aria-expanded') : ''; })()"""
    NB = "(() => (document.querySelector('.note-bubble') || {}).textContent || '')()"
    first = tab.ev(TAP); time.sleep(0.3); second = tab.ev(TAP); time.sleep(0.3)
    check("[12] a tap on the marker opens the setting in a bubble (expanded); a second tap closes it",
          "Prefer TCP" in (first or "") and (first or "").endswith("|true") and second == "", (first, second))
    tab.ev(TAP); time.sleep(0.3)
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true"); time.sleep(0.2)
    esc = tab.ev(NB)
    tab.ev(TAP); time.sleep(0.3)
    tab.ev("document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); true"); time.sleep(0.2)
    out = tab.ev(NB)
    check("[12] Escape closes it, and so does a press anywhere else", esc == "" and out == "", (esc, out))
    nport = tab.ev("(() => { const m = document.querySelector('section.ppage[data-mode=awg] .scell-p2p'); if (!m) return 'no marker';"
                   " m.click(); return [...document.querySelectorAll('.note-bubble .note-port b')].map(b => b.textContent); })()")
    time.sleep(0.2); tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true"); time.sleep(0.2)
    check("[12] the bubble of Anna's AmneziaWG cell (forwarded) shows the port as one number of its own", nport == ["20016"], nport)
    tab.ev(TAP); time.sleep(0.3)
    inner = tab.ev("(() => { const b=document.querySelector('.note-bubble'); b.style.maxHeight='30px'; b.scrollTop=20;"
                   " b.dispatchEvent(new Event('scroll')); return !!document.querySelector('.note-bubble') })()"); time.sleep(0.2)
    tab.ev("document.dispatchEvent(new Event('scroll')); true"); time.sleep(0.2)
    page = tab.ev(NB)
    stale = tab.ev("[...document.querySelectorAll('.scell-p2p')].filter(m => m.hasAttribute('aria-describedby')).length")
    check("[12] scrolling the bubble's own capped text keeps it open; a page scroll closes it; no closed marker still points at a bubble",
          inner is True and page == "" and stale == 0, (inner, page, stale))
    tab.ev(TAP); time.sleep(0.3)
    tab.ev("document.querySelector('[data-pick]').click(); true"); time.sleep(0.6)
    # Anna has two devices: the picker opens on them, and a device's connections — the badge copies — are one level down
    tab.ev("(() => { const r=[...document.querySelectorAll('.cp-row')].find(x => x.textContent.includes('laptop')); if (r) r.click(); return 1 })()")
    time.sleep(0.6)
    pick = tab.ev("(() => ({marks: document.querySelectorAll('.cp-row .scell-mark').length, rows: document.querySelectorAll('.cp-row .scell-srv').length,"
                  " turtles: [...document.querySelectorAll('.cp-row span.scell-slow[role=img]')].filter(x => x.querySelector('svg') && x.getAttribute('aria-label')"
                  " && x.title.length > x.getAttribute('aria-label').length).length,"
                  " magnets: [...document.querySelectorAll('.cp-row span.scell-p2p[role=img]')].filter(x => x.querySelector('svg') && x.getAttribute('aria-label')).length}))()")
    check("[12] the connection picker's copies of the badge rows carry no marker button (a dead button inside a row button), "
          "and keep the turtle and the magnet as labelled icons — the turtle's tooltip its whole note (no bubble there)",
          pick and pick["rows"] and pick["marks"] == 0 and pick["turtles"] >= 1 and pick["magnets"] >= 1, pick)
    tab.close()
    tab, _r = render("u1", "android", "en", phone=True)
    tab.ev("(() => { const b=document.querySelector('.mtab-turn'); if (b) b.click(); return 1 })()"); time.sleep(0.8)
    seek = tab.ev("(() => { " + seek_js("turn", "cacggghp") + " return 'ok'; })()"); time.sleep(0.8)
    tt = tab.ev(TAP.replace(".scell-p2p", ".scell-slow"))   # the cacggghp cell is the one in view after the seek
    check("[12] a tap on the plain-mode turtle (the cacggghp cell) opens its own text in the same bubble",
          seek == "ok" and (tt or "").startswith("Plain — no obfuscation") and (tt or "").endswith("|true"), (seek, tt))
    tab.close()

    # [2] the author word, per language, in all three turn cells
    def by_words(os_, lang):
        return {(c["role"] or "?"): c["by"] for c in turn_cells(renders[(os_, lang)]) if c["by"]}
    for os_, cell, author in (("windows", "CSQTT 2.1", "luminescq"), ("linux", "WDTT", "luminescq"), ("android", "CSQTT 2.1", "Endlad2")):
        en, ru = by_words(os_, "en").get(cell), by_words(os_, "ru").get(cell)
        check("[2] %s %s cell: EN badge says ' by %s'" % (os_, cell, author), en == " by " + author, by_words(os_, "en"))
        check("[2] %s %s cell: RU badge says ' от %s', no English" % (os_, cell, author), ru == " от " + author, by_words(os_, "ru"))
    tp = [c for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if (c["role"] or "") in ("AWG", "WG") and c["by"]]
    check("[2] the turn-proxy cell's author word is translated wherever one renders (RU)", tp and all(" by " not in c["by"] for c in tp),
          [c["by"] for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if c["by"]])

    # [10] a hidden fork a node still runs keeps its whole app map (operator, 2026-10-14: "hidden like cacggghp")
    an = turn_cells(renders[("android", "en")])
    check("[10] Android: the MYSOREZ proxy (hidden fork, still running) offers its users the MYSOREZ app",
          any((c["tag"] or "").startswith("MYSOREZ · VK TURN Proxy") for c in an), [c["tag"] for c in an])
    check("[10] …while hack-diaz's cells (a visible fork) do not offer that hidden app",
          not [c for c in an if (c["tag"] or "").startswith("hack-diaz") and "MYSOREZ" in (c["tag"] or "")], [c["tag"] for c in an])

    # [9] an app whose own tunnel is WireGuard only (anton48's VK TURN Proxy, `awg: false`) is never handed out for an AmneziaWG
    #     interface behind a proxy — the app itself warns that AmneziaWG keys cannot work (the review of 356a08f9, F3)
    ios = turn_cells(renders[("ios", "en")])
    check("[9] iOS: no AmneziaWG cell offers VK TURN Proxy (the AWG proxy has no iOS app, so it shows no card)",
          not [c for c in ios if (c["role"] or "") == "AWG" and "VK TURN Proxy" in (c["tag"] or "")], [(c["role"], c["tag"]) for c in ios])
    check("[9] …while the WireGuard interface's proxy still does", any((c["role"] or "") == "WG" and "VK TURN Proxy" in (c["tag"] or "") for c in ios),
          [(c["role"], c["tag"]) for c in ios])
    check("[9] control: on Android the AmneziaWG proxy keeps its cell (FreeTurn carries AmneziaWG)",
          any((c["role"] or "") == "AWG" and "FreeTurn" in (c["tag"] or "") for c in turn_cells(renders[("android", "en")])),
          [(c["role"], c["tag"]) for c in turn_cells(renders[("android", "en")])])

    # [6] a fork that changed hands is named by its catalog label: samosvalishe's repos are gone and hack-diaz (GitHub: hackdiaz-dev) carries them
    # on, but the id stays (it is in every node's unit names) — so the id must never reach the visitor
    fp = [(os_, lang, c) for os_ in ALL_OS for lang in ("en", "ru") for c in turn_cells(renders[(os_, lang)])
          if (c["role"] or "") in ("AWG", "WG") and not (c["tag"] or "").startswith(("MYSOREZ", "cacggghp"))]   # [10]'s and [12]'s proxies are other forks
    check("[6] the samosvalishe-fronted cell's badge names hack-diaz on every OS and language",
          fp and all("hack-diaz" in (c["tag"] or "") for _o, _l, c in fp), [(o, l, c["tag"]) for o, l, c in fp])
    leak = [(os_, lang, c["text"][:120]) for os_ in ALL_OS for lang in ("en", "ru") for p in renders[(os_, lang)]["pages"]
            for c in p["cells"] if "samosvalishe" in (c["text"] or "")]
    check("[6] …and no cell anywhere says samosvalishe", not leak, leak[:3])

    # [7] a WDTT fork's own app is its default: XXcipherX's one-tap app stood in for amurcanov's until its repository went
    #     (operator, 2026-10-14) — the WDTT cell on Android now hands out amurcanov's WDTT, which imports by paste
    tab, _ = render("u1", "android", "en")
    wc = [c for p in renders[("android", "en")]["pages"] for c in p["cells"] if "WDTT" in (c["tag"] or "")]
    check("[7] the WDTT cell's Android app is amurcanov's own WDTT (no cross-author app, never XXcipherX's)",
          wc and all((c["tag"] or "") == "amurcanov · WDTT" and not c["by"] for c in wc), [(c["tag"], c["by"]) for c in wc])
    res, clip, steps, navs = start_on(tab, "turn", "WDTT")
    check("[7] …and its Start copies the wdtt:// link and shows the import steps (the app opens no scheme), firing nothing",
          res == "clicked" and steps and not navs and any(x.startswith("wdtt://") for x in clip), (res, navs, steps, [x[:20] for x in clip]))
    tab.close()
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    serve["turn_client_default"] = {"csqtt": {"android": "lalune"}, "amurcanov": {"android": "wdttplus"}}
    J("subs/serve.json", serve)
    # [8] an app from the server's own repository follows the server's running version
    def bubble(tab, badge_has):
        return tab.ev(r"""(() => {
          %s
          const btn = cells[i].querySelector('.scell-getapp-btn') || pg.querySelector('.scell-getapp-btn');
          if (!btn) return 'no button';
          btn.click();
          const b = document.querySelector('.dl-bubble');
          return b ? {ver: (b.querySelector('.dl-bubble-ver') || {}).textContent || '', links: [...b.querySelectorAll('a')].map(a => a.href)} : 'no bubble';
        })()""" % seek_js("turn", badge_has))
    pinned = lambda b, tag, url: isinstance(b, dict) and tag in b["ver"] and "matches this server" in b["ver"] and url in b["links"]
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    keep_default = serve["turn_client_default"]
    serve["turn_client_default"] = {}   # the CSQTT app itself (the operator's Android default for csqtt is La Lune)
    J("subs/serve.json", serve)
    tab, _ = render("u1", "android", "en")
    bb = bubble(tab, "CSQTT")
    check("[8] the CSQTT app's bubble offers v2.1.9 — the release the server runs, from our csqtt-app-2.1.9, though v2.5.1 is the latest — and says it matches",
          pinned(bb, "v2.1.9", PIN_APK) and not any("csqtt-app-2.5.1" in u or "amurcanov" in u for u in bb["links"]), bb)
    wb = bubble(tab, "amurcanov · WDTT")
    check("[8] the WDTT cell (amurcanov 1.2.4-3) offers its own app's v1.2.4 — the WDTT server's version reaches the page",
          pinned(wb, "v1.2.4", WDTT_APK), wb)
    fb = bubble(tab, "hack-diaz · FreeTurn")
    check("[8] FreeTurn on a hack-diaz proxy is NOT handed the CLI release's Android binary: its repository is not the server's",
          isinstance(fb, dict) and "matches this server" not in fb["ver"] and CLI_AND not in fb["links"], fb)
    tab.close()
    serve["turn_client_default"] = keep_default
    J("subs/serve.json", serve)
    tab, _ = render("u1", "linux", "en")
    lb = bubble(tab, "hack-diaz · Sidecar")
    check("[8] the hack-diaz CLI on Linux offers v4.0.3, the proxy's own release — a turn proxy's version reaches the page",
          pinned(lb, "v4.0.3", CLI_LIN), lb)
    tab.close()
    # [3] Start on the csqtt cell
    tab, _ = render("u1", "android", "en")
    res, clip, steps, navs = start_on(tab, "turn", "WDTT-Plus")
    check("[3] control: Start on a one-tap app (the WDTT cell's operator-chosen WDTT-Plus) is SEEN firing its scheme link — the probe can pass",
          res == "clicked" and any(u.startswith("wdtt://") for u in navs) and not steps, (res, navs, steps))
    tab.close()
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

    # [11] csqtt 2.1 and 2.5 do not speak to each other: a server is offered only apps of its line
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    serve["turn_client_default"] = {"csqtt": {"android": "lalune"}}
    J("subs/serve.json", serve)
    UNSEAL = r"""const l = process.argv[1].slice(8), b = Buffer.from(l.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
      const kh = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('csqtt-chiper-key'));
      const k = await crypto.subtle.importKey('raw', kh, {name: 'AES-GCM'}, false, ['decrypt']);
      try { console.log(new TextDecoder().decode(await crypto.subtle.decrypt({name: 'AES-GCM', iv: b.subarray(0, 12)}, k, b.subarray(12)))); }
      catch (e) { console.log(''); }"""
    def _unseal(link):   # a csqtt 2.5 link → its payload: the 2.5 app's decoder, in node's Web Crypto ("" = it does not open)
        return subprocess.run(["node", "--input-type=module", "-e", UNSEAL, link], capture_output=True, text=True, timeout=30).stdout.strip()
    def _plain(c):   # the cell's text + link; an iOS vkturnproxy:// link carries the server inside base64, a 2.5 csqtt:// one sealed
        t = (c["text"] or "") + (c["payload"] or "")
        for sl in set(re.findall(r"csqtt://(?!connect)[A-Za-z0-9_-]{40,}", t)):
            t += " " + _unseal(sl)
        for b in re.findall(r"vkturnproxy://import\?data=([A-Za-z0-9_-]+)", t):
            try:
                t += base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "replace")
            except Exception:
                pass
        return t
    on = lambda r, port: [c for c in turn_cells(r) if port in _plain(c)]
    # Dana's device has two csqtt servers: csqtt1 (no line reported → 2.1) and csqtt2 (2.5). A 2.5 cell is a QR, so its link is not
    # in the DOM as text: cells are told apart by their app, and "no cell for the 2.5 server" is a COUNT (one cell, the 2.1 one) —
    # never the absence of a port in text a QR cell does not carry.
    tab, rd = render("u4", "android", "en")
    cells = turn_cells(rd)
    c25 = [c for c in cells if "CSQTT" in (c["tag"] or "")]
    c21 = on(rd, "56002")
    check("[11] Android, the 2.5 server: the CSQTT app, not the operator's default La Lune (it speaks 2.1)",
          len(cells) == 2 and len(c25) == 1 and "La Lune" not in (c25[0]["tag"] or ""), [(c["tag"], (c["text"] or "")[:60]) for c in cells])
    check("[11] …the 2.1 server beside it keeps La Lune", len(c21) == 1 and "La Lune" in (c21[0]["tag"] or ""), [c["tag"] for c in c21])
    check("[11] …the 2.5 server shown as a QR (the 2.5 app scans one), while the 2.1 server's plain link has none",
          len(c25) == 1 and c25[0]["qr"] and len(c21) == 1 and not c21[0]["qr"], [(c["tag"], c["qr"]) for c in cells])
    # 2.1 and 2.5 cards were alike until the app was downloaded (operator, 2026-10-20): the chip names the server's version,
    # the download its app's — and a node that reports no line is a 2.1 one
    check("[11] the 2.5 server's card says CSQTT 2.5, and its download CSQTT 2.5.1",
          len(c25) == 1 and c25[0]["role"] == "CSQTT 2.5" and "CSQTT 2.5.1" in (c25[0]["getapp"] or ""),
          [(c["role"], c["getapp"]) for c in c25])
    check("[11] …the 2.1 server's card (no line reported) says CSQTT 2.1",
          len(c21) == 1 and c21[0]["role"] == "CSQTT 2.1", [c["role"] for c in c21])
    res, clip, steps, navs = start_on(tab, "turn", "amurcanov · CSQTT")
    sealed = next((x for x in list(clip) + list(navs) if x.startswith("csqtt://") and not x.startswith("csqtt://connect")), "")
    p25 = _unseal(sealed) if sealed else ""
    check("[11] its Start hands out the SEALED link (the 2.5 app takes no other), which opens to its connect payload",
          p25.startswith("connect?v=2&host=203.0.113.7&peer=56003&password=pw5csqtt"), (res, [x[:40] for x in clip], [x[:40] for x in navs], p25))
    b25 = bubble(tab, "CSQTT")
    check("[11] …and its download is our 2.5.1 build (csqtt-app-2.5.1), shown as v2.5.1 and matching the server",
          pinned(b25, "v2.5.1", PIN25_APK) and not any("amurcanov" in u for u in b25["links"]), b25)
    tab.close()
    tab, rd = render("u4", "ios", "en")
    cells = turn_cells(rd)
    check("[11] iOS: no cell for the 2.5 server (VK TURN Proxy speaks 2.1), while the 2.1 server keeps its iPhone cell",
          len(cells) == 1 and len(on(rd, "56002")) == 1, [(c["tag"], (c["text"] or "")[:60]) for c in cells])
    tab.close()
    # the CSQTT app's release is of the other line (no 2.5 release out): the 2.5 server is offered nothing, not a 2.1 app.
    # No 2.5 release also means no pin for the 2.5 build — the pin is what normally hands it our csqtt-app-2.5.1.
    ((serve["turn_catalog"].get("pins") or {}).get("amurcanov/csqtt") or {}).pop("2.5.1", None)
    ca = serve["turn_catalog"]["clients"]["csqttapp"]["platforms"]["android"]
    ca.update({"tag": "v2.1.9", "url": PIN_APK, "page": "https://github.com/amurcanov/csqtt/releases/tag/v2.1.9",
               "assets": [{"name": "csqtt-v2.1.9.apk", "url": PIN_APK}]})
    J("subs/serve.json", serve)
    tab, rd = render("u4", "android", "en")
    check("[11] with only a 2.1 release of the CSQTT app, the 2.5 server has no cell (no app of its line), the 2.1 one keeps La Lune",
          len(turn_cells(rd)) == 1 and len(on(rd, "56002")) == 1, [(c["tag"], (c["text"] or "")[:60]) for c in turn_cells(rd)])
    tab.close()
    # the release is not resolved yet (a cold cache, GitHub rate-limited): no tag — the latest is 2.1's until proven otherwise
    for k in ("tag", "url", "page", "assets"):
        ca.pop(k, None)
    J("subs/serve.json", serve)
    tab, rd = render("u4", "android", "en")
    check("[11] with the CSQTT release not resolved yet, the 2.5 server still has no cell — its releases page leads to the 2.1 app",
          len(turn_cells(rd)) == 1 and len(on(rd, "56002")) == 1, [(c["tag"], (c["text"] or "")[:60]) for c in turn_cells(rd)])
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
