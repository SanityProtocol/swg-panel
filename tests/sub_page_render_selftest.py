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
  [6] a fork is named by its catalog label, never its id: the samosvalishe proxy's cell says hackdiaz (its repos moved,
      the id stays in every node's unit names), and no cell on any OS or language says samosvalishe
  [7] a WDTT fork's own app is its default (operator, 2026-10-14): the WDTT cell on Android hands out amurcanov's WDTT —
      XXcipherX's app, which stood in for it, is hidden with its deleted repository — and its Start shows the import steps
  [9] an app whose own tunnel is WireGuard only (VK TURN Proxy on iOS, `awg: false`) is never handed out for an AmneziaWG
      interface behind a proxy; the WireGuard interface's proxy still offers it; FreeTurn keeps the AmneziaWG one on Android
  [10] a proxy of a HIDDEN fork a node still runs (MYSOREZ) keeps its users' app: its Android cell offers the MYSOREZ app,
      hidden from every visible fork (hackdiaz's cells on the same interface do not offer it)
  [11] csqtt 2.1 and 2.5 do not speak to each other: a 2.5 server (Dana's csqtt2, line 2.5) is offered only an app of its
      line. The operator's Android default La Lune speaks both since S13a: it serves the 2.5 server one tap, as on 2.1 (Start
      fires the sealed link and copies it, no steps); ranked, the CSQTT app; on iOS nothing (VK TURN
      Proxy speaks 2.1); her 2.1 server keeps its app. Once the CSQTT app's release is of the other line (no 2.5 release yet),
      the 2.5 server is never offered it — La Lune serves it; the line reaches the page through swg-sub
  [12] torrents (1.8.11 S4b): q-node lets them through (Direct) and Boris's awg1 blocks them. Every one of Anna's cells, on every
      OS and in both languages, carries the torrent marker in its badge row, labelled with the client setting for full speed
      (in the page's language); a tap opens that text in a bubble and a second tap closes it; Boris's awg1 cell carries none
      while his csqtt1 cell does; Anna's blocked device's page carries none. The plain-mode turtle (a cacggghp proxy) opens its
      own text in the same bubble on a tap; the connection picker shows both icons, as icons, not buttons. The device's own
      incoming port (S12, Part C): where q-node reports forwarding awg0, Anna's AmneziaWG cells' bubble opens with port 20016
      and the address peers reach (in both languages); her WireGuard cell (wg0, not forwarded) and Boris's cells carry none
  [13] the 2.5 clients on the desktop (S13a): Dana's 2.5 server on Linux/Windows gets Rawline with no choice (one-tap, 1.8.12
      item 10) and La Lune where it is chosen for 2.5 (FOCSQ speaks 2.1 only) and its
      Start shows the CSQTTR step; with the operator's choice csq-socks serves both lines, with its download and its own
      terminal steps (EN, RU); Anna's 2.1 server still offers FOCSQ — csq-socks, a command-line client, ranks after the apps
  [14] a default per csqtt line (operator, 2026-10-29): with turn_client_default["csqtt@2.5"], Dana's 2.5 server gets 2.5's
      own choice (csq-socks on Linux; "none" on Windows hides only it) while her 2.1 server keeps 2.1's FOCSQ; a 2.1-only
      app stored under it is passed over (Rawline, as with no choice)
  [8] an app from the server's own repository follows the server's running version (operator, 2026-10-14): csqtt
      2.1.9-4 while v2.5.1 is the latest — the CSQTT app's bubble offers v2.1.9 (our csqtt-app-2.1.9) and says it matches; amurcanov's WDTT 1.2.4-3
      → v1.2.4 and the hackdiaz CLI on Linux → the proxy's v4.0.3 (both versions reach the page); FreeTurn on that proxy
      is not handed the CLI release's Android binary (another repository's app keeps its own versioning)
  [16] Rawline opens in one tap everywhere (1.8.12 item 10; operator, 2026-11-24: deep links, not instructions): with no default
      saved, hackdiaz on Linux hands out Rawline; on the desktop the first Start asks Open / Get, and once it is known
      installed Start opens rawline://add/ with the desktop's form (a JSON list holding the freeturn:// link); RawlineMobile
      on Android is fired at once with the app's form (the plain link) — never the import steps
  [17] the MRTT line (1.8.12 item 10): Eve's MRTT server gets the MRTT app on Android (chip MRTT, tag by ttrroyy; its own
       default — the fork's key "mrtt" — picks the app or hides it per OS, csqtt's "none" does not; Start fires an mrtt:// link
      MRTT's own decoder opens), Rawline on Linux (rawline://add/ around that mrtt:// link), nothing on iOS; Dana's 2.1 and
      2.5 servers are not offered the MRTT app

  [18] the visitor picks the app (1.8.12 item 24; operator, 2026-11-25): the badges read "<app> by <author>", a chip where
      there is a choice; the list puts the operator's default first (Recommended), then the other apps with their authors,
      and leaves the command-line client out on a phone (a desktop keeps it); a pick makes the card hand out that app — its
      badge and download — is kept on the device per server type, offers itself where it also works ("Use it there too"), and
      is cleared by picking the default again; a pick never moves a card (the order stays the operator's), a stale one falls
      back silently and is kept; on the desktop the tapped badge stays put through the rebuild; the connection list names a
      connection "<type or server author> · <app>" with no button inside its rows; the one-time roll plays once and lands
      back on the chip's own label, and under reduced motion a one-line hint stands in for it; two cards that would read alike
      keep their port only where it tells them apart (a Primary / Backup pair on one port has none), the port staying in
      the list row where the app repeats the type ("WDTT by amurcanov :56000"); an offer stays, under the list, while another
      list is only opened, and goes with the next pick
  [20] the PC and tablet layouts (operator, 2026-11-26): a phone (and a phone on its side) keeps its own; a PC lists the
      devices beside one card — Start named and above the fold, the QR's text beside it, Download saving that text, a row
      showing its card — and a tablet upright puts the devices as tabs above it; every full-screen pop-up is modal and
      named by its title as it changes; a toast is read out from a status region already in the page
  [19] the WG / AWG cards pick their app too (item 24, card B): "<protocol> · <app>" with a chip, the protocol dropped where
      the app repeats it ("WireGuard"); the list is AmneziaVPN (Recommended) then every app this OS has a link for, Linux
      without AmneziaWG, MCRF or WINGS V; a pick names the app's own download row and drives Start — RawlineMobile
      rawline://add/ around the plain .conf, Rawline on Windows a JSON list holding it, WINGS V its own AmneziaWG profile
      link (type 3, backend 8, the whole .conf) under a note to delete an old profile first, WireGuard the .conf saved and
      its import steps; a pick the list doesn't hold falls back; the connection list reads "AmneziaWG · AmneziaVPN"
  The turn cards name their server's author beside the badge (operator, 2026-11-25), not the interface: [9] tells the
  AmneziaWG and WireGuard proxies apart by count — one hackdiaz card on iOS, where only the WireGuard one has an app.

Needs google-chrome (or $CHROME) and node (seals the fixture secret). A missing browser is a FAIL, never a skip: a gate that
cannot run has not passed.

Run: python3 tests/sub_page_render_selftest.py        (0 = pass)
     --perturb-macos      serves a sub.js whose csqtt branch has no client-for-this-OS guard → RED on [1]
     --perturb-volline    serves a sub.js that shows no volume line and no "limit reached" page → RED on [15]
     --perturb-volday     serves a sub.js that shows a reset day as an instant in the browser's zone → RED on [15]
     --perturb-voldev     serves a sub.js whose cut device's page says EXPIRED, not its limit → RED on [15]
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
     --perturb-overscroll serves a sub.css whose bubble passes a fling at its end on to the page → RED on [12]
     --perturb-pickmark   serves a sub.js whose picker copies the badge rows with their marker buttons → RED on [12]
     --perturb-pickshort  serves a sub.js whose picker icons show the short label as their tooltip → RED on [12]
     --perturb-p2pall     serves a sub.js that draws the torrent marker on every cell, allowed or not → RED on [12]
     --perturb-p2pport    serves a sub.js whose torrent bubble leaves out the device's incoming port → RED on [12]
     --perturb-subport    runs a swg-sub that never puts the device's incoming port on a deployment → RED on [12]
     --perturb-csqrank    serves a sub.js that ranks csq-socks as an app (it sorts first on a 2.1 desktop) → RED on [13]
     --perturb-csqsteps   serves a sub.js whose csq-socks cell shows the generic app steps → RED on [13]
     --perturb-line25     serves a sub.js that ignores the 2.5 line's own default ("csqtt@2.5") → RED on [14]
     --perturb-linemrtt   serves a sub.js that resolves an MRTT server under csqtt's fork (its apps, defaults, name) → RED on [17]
     --perturb-mrttby     serves a sub.js that credits an MRTT server to csqtt's author (amurcanov) → RED on [17]
     --perturb-runfork    serves a sub.js that takes a csqtt server's fork from its record, not the line it runs → RED on [17]
     --perturb-ll25       serves a sub.js whose La Lune 2.5 cell shows the generic steps (no CSQTTR) → RED on [11]/[13]
     --perturb-llfire     serves a sub.js that shows the steps instead of firing a one-tap app's link (La Lune on Android) → RED on [11]
     --perturb-ll21       serves a catalog where La Lune speaks 2.1 only again → RED on [11]/[13]
     --perturb-pickrank   serves a sub.js whose card ranking follows the visitor's pick → RED on [18]
     --perturb-cliphone   serves a sub.js that lists the command-line client on a phone → RED on [18]
     --perturb-pickclone  serves a sub.js whose connection list copies the app chip as a button → RED on [18]
     --perturb-pickjump   serves a sub.js whose pick rebuild leaves the tapped badge where the rebuild puts it → RED on [18]
     --perturb-stalepick  serves a sub.js that hides a card whose saved pick the list no longer holds → RED on [18]
     --perturb-dupport    serves a sub.js whose two relays of one fork on two interfaces carry no port → RED on [18]
     --perturb-staleoffer serves a sub.js that leaves an earlier offer on screen after a pick → RED on [18]
     --perturb-sameport   serves a sub.js that gives a Primary / Backup pair on one port that port → RED on [18]
     --perturb-echoport   serves a sub.js whose type label keeps its port when the app repeats the type → RED on [18]
     --perturb-offeropen  serves a sub.js that drops the offer when a list only opens → RED on [18]
     --perturb-offertop   serves a sub.css that puts the offer over an open list → RED on [18]
     --perturb-wgstart    serves a sub.js whose WG / AWG Start always opens AmneziaVPN, whatever is picked → RED on [19]
     --perturb-wglist     serves a sub.js whose WG / AWG list offers an app with nothing for this OS → RED on [19]
     --perturb-wgcollapse serves a sub.js whose badge repeats a protocol the app's name already says → RED on [19]
     --perturb-wsvnote    serves a sub.js that drops WINGS V's old-profile note → RED on [19]
     --perturb-wgdl       serves a sub.js whose WG / AWG download row stays AmneziaVPN's after a pick → RED on [19]
     --perturb-wgnote     serves a sub.js whose WG / AWG download bubble shows a turn card's note (MCRF's engines) → RED on [19]
     --perturb-wgzoom     serves a sub.js whose enlarged WG / AWG QR names the protocol, not the app picked → RED on [19]
     --perturb-wgscan     serves a sub.js whose enlarged WG / AWG QR names an app that cannot scan it (MCRF on Windows) → RED on [19]
     --perturb-laywide    serves a sub.js with no PC / tablet layout (every window the phone's or the column) → RED on [20]
     --perturb-layphone   serves a sub.js that gives a phone the tablet layout → RED on [20]
     --perturb-navgo      serves a sub.js whose list rows show nothing → RED on [20]
     --perturb-onecard    serves a sub.css that shows every page under the PC card → RED on [20]
     --perturb-pcdl       serves a sub.js whose PC Download saves a picture of the QR → RED on [20]
     --perturb-sidetext   serves a sub.js with no text beside the PC's QR → RED on [20]
     --perturb-modal      serves a sub.js whose pop-ups leave the page behind them live → RED on [20]
     --perturb-startorb   serves a sub.js whose Start orbs share one gradient id → RED on [20]
     --perturb-pcgrid     serves a sub.css whose PC card is one column (Start below the fold) → RED on [20]
     --perturb-navnets    serves a sub.js whose networks card closes the device's connections on an upright tablet → RED on [20]
     --perturb-laynav     serves a sub.css that hides the header name though no list carries it → RED on [20]
     --perturb-dllabel    serves a sub.js that calls any text download a link → RED on [20]
     --perturb-dlgname    serves a sub.js whose dialogs have no name → RED on [20]
     --perturb-zoomfocus  serves a sub.js whose enlarged QR leaves the focus behind it → RED on [20]
     --perturb-netsrows   serves a sub.css whose networks card keeps the PC card's empty rows → RED on [20]
     --perturb-navrebuild serves a sub.js whose rebuild on the networks card (theme, a turn of the tablet) closes the device → RED on [20]
     --perturb-dlglevel   serves a sub.js whose dialogs keep the name they opened with → RED on [20]
     --perturb-backarrow  serves a sub.js whose back arrow is read as part of a device's name → RED on [20]
     --perturb-livepre    serves a sub.js whose status region arrives with the first toast → RED on [20]
     --perturb-xxsub      the catalog and sub.js of before 2026-10-14 (XXcipherX's app stands in for a WDTT fork's own) → RED on [7]
   A perturbation prints "PERTURB OK" and exits 0 when something went red, exits 1 when nothing did — or when its anchor is
   gone (a perturbation that cannot be applied proves nothing).
"""
import base64, fcntl, hashlib, importlib.machinery, importlib.util, json, os, re, secrets, select, shutil, socket, subprocess, sys
import tempfile, time, urllib.request, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
P_MACOS = "--perturb-macos" in sys.argv
P_VOLLINE = "--perturb-volline" in sys.argv
P_VOLDAY = "--perturb-volday" in sys.argv
P_VOLDEV = "--perturb-voldev" in sys.argv
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
P_OVERSCROLL = "--perturb-overscroll" in sys.argv
P_TURTLESPAN = "--perturb-turtlespan" in sys.argv
P_CSQRANK = "--perturb-csqrank" in sys.argv
P_CSQSTEPS = "--perturb-csqsteps" in sys.argv
P_LINE25 = "--perturb-line25" in sys.argv
P_LINEMRTT = "--perturb-linemrtt" in sys.argv
P_MRTTBY = "--perturb-mrttby" in sys.argv
P_RUNFORK = "--perturb-runfork" in sys.argv
P_LL25 = "--perturb-ll25" in sys.argv
P_LLFIRE = "--perturb-llfire" in sys.argv
P_LL21 = "--perturb-ll21" in sys.argv
P_PICKRANK = "--perturb-pickrank" in sys.argv
P_CLIPHONE = "--perturb-cliphone" in sys.argv
P_PICKCLONE = "--perturb-pickclone" in sys.argv
P_PICKJUMP = "--perturb-pickjump" in sys.argv
P_STALEPICK = "--perturb-stalepick" in sys.argv
P_DUPPORT = "--perturb-dupport" in sys.argv
P_STALEOFFER = "--perturb-staleoffer" in sys.argv
P_SAMEPORT = "--perturb-sameport" in sys.argv
P_ECHOPORT = "--perturb-echoport" in sys.argv
P_OFFEROPEN = "--perturb-offeropen" in sys.argv
P_OFFERTOP = "--perturb-offertop" in sys.argv
P_WGSTART = "--perturb-wgstart" in sys.argv
P_WGLIST = "--perturb-wglist" in sys.argv
P_WGCOLLAPSE = "--perturb-wgcollapse" in sys.argv
P_WSVNOTE = "--perturb-wsvnote" in sys.argv
P_WGDL = "--perturb-wgdl" in sys.argv
P_WGNOTE = "--perturb-wgnote" in sys.argv
P_LAYWIDE = "--perturb-laywide" in sys.argv
P_LAYPHONE = "--perturb-layphone" in sys.argv
P_NAVGO = "--perturb-navgo" in sys.argv
P_ONECARD = "--perturb-onecard" in sys.argv
P_PCDL = "--perturb-pcdl" in sys.argv
P_SIDETEXT = "--perturb-sidetext" in sys.argv
P_MODAL = "--perturb-modal" in sys.argv
P_STARTORB = "--perturb-startorb" in sys.argv
P_PCGRID = "--perturb-pcgrid" in sys.argv
P_NAVNETS = "--perturb-navnets" in sys.argv
P_LAYNAV = "--perturb-laynav" in sys.argv
P_DLLABEL = "--perturb-dllabel" in sys.argv
P_DLGNAME = "--perturb-dlgname" in sys.argv
P_ZOOMFOCUS = "--perturb-zoomfocus" in sys.argv
P_NETSROWS = "--perturb-netsrows" in sys.argv
P_NAVREBUILD = "--perturb-navrebuild" in sys.argv
P_DLGLEVEL = "--perturb-dlglevel" in sys.argv
P_BACKARROW = "--perturb-backarrow" in sys.argv
P_LIVEPRE = "--perturb-livepre" in sys.argv
P_WGZOOM = "--perturb-wgzoom" in sys.argv
P_WGSCAN = "--perturb-wgscan" in sys.argv
PERTURB = (P_VOLLINE or P_VOLDAY or P_VOLDEV or P_P2PALL or P_P2PPORT or P_SUBPORT or P_PICKMARK or P_PICKSHORT or P_SCROLLCLOSE or P_OVERSCROLL or P_TURTLESPAN or P_MACOS or P_BY or P_AUTO or P_TABS or P_COPY or P_NETSW or P_FORKNAME or P_XXSUB or P_PIN or P_AWGAPP or P_HIDDENMAP or P_GUARD
           or P_LINE or P_OWNLINE or P_CHIPLINE or P_CSQRANK or P_CSQSTEPS or P_LL25 or P_LLFIRE or P_LL21 or P_LINE25 or P_LINEMRTT or P_MRTTBY or P_RUNFORK
           or P_PICKRANK or P_CLIPHONE or P_PICKCLONE or P_PICKJUMP or P_STALEPICK or P_DUPPORT or P_STALEOFFER
           or P_SAMEPORT or P_ECHOPORT or P_OFFEROPEN or P_OFFERTOP
           or P_WGSTART or P_WGLIST or P_WGCOLLAPSE or P_WSVNOTE or P_WGDL or P_WGNOTE or P_WGZOOM or P_WGSCAN
           or P_LAYWIDE or P_LAYPHONE or P_NAVGO or P_ONECARD or P_PCDL or P_SIDETEXT or P_MODAL or P_STARTORB or P_PCGRID
           or P_NAVNETS or P_LAYNAV or P_DLLABEL or P_DLGNAME or P_ZOOMFOCUS or P_NETSROWS
           or P_NAVREBUILD or P_DLGLEVEL or P_BACKARROW or P_LIVEPRE)

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
# hackdiaz proxies' v4.0.3 → its CLI release (which also carries an Android binary)
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
if P_LL21:   # La Lune back on 2.1 alone (the catalog before S13a)
    if ((catalog.get("clients") or {}).get("lalune") or {}).get("csqtt_lines") != ["2.1", "2.5"]:
        print("PERTURB FAILED — La Lune does not list 2.5 in the catalog, so there is nothing to remove"); sys.exit(1)
    catalog["clients"]["lalune"]["csqtt_lines"] = ["2.1"]
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
                           "u4": {"name": "Dana", "vk_links": VK[:1]}, "u5": {"name": "Eve", "vk_links": VK[:1]},
                           "u6": {"name": "Finn", "vk_links": VK[:1]}, "u7": {"name": "Gina", "vk_links": VK[:1]},
                           "u8": {"name": "Hana"}},
                 "peers": {
                     "p1": {"id": "p1", "user_id": "u1", "title": "laptop", "csqtt_password": "pw1csqtt", "wdtt_password": "pw1wdtt", "p2p_port": 20016,
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"},
                                        {"node": "n1", "iface": "wdtt1", "type": "wdtt"},
                                        {"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.2/32"},
                                        # [9] a plain WireGuard interface behind a second hackdiaz proxy
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
                     # [17] a device on an MRTT server (the csqtt fork mrtt, its line mrtt — 1.8.12 item 10)
                     "p6": {"id": "p6", "user_id": "u5", "title": "phone", "csqtt_password": "pw6csqtt",
                            "targets": [{"node": "n1", "iface": "csqtt3", "type": "csqtt"}]},
                     # [18] a phone on WDTT at two nodes (Primary / Backup): on one port at both (Finn), on two ports (Gina)
                     "p7": {"id": "p7", "user_id": "u6", "title": "phone", "wdtt_password": "pw7wdtt",
                            "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt", "primary": "primary"},
                                        {"node": "n2", "iface": "wdtt1", "type": "wdtt", "primary": "backup"}]},
                     "p8": {"id": "p8", "user_id": "u7", "title": "phone", "wdtt_password": "pw8wdtt",
                            "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt", "primary": "primary"},
                                        {"node": "n2", "iface": "wdtt2", "type": "wdtt", "primary": "backup"}]},
                     # [20] one WireGuard config on a node with no networks: nothing to choose on a PC
                     "p9": {"id": "p9", "user_id": "u8", "title": "desktop", "targets": [{"node": "n3", "iface": "wg0", "type": "wg", "ip": "10.17.0.2/32"}]},
                     # [5] a blocked device: its page is a dead end with the device's name as the picker's trigger
                     "p4": {"id": "p4", "user_id": "u1", "title": "old tablet", "disabled": True,
                            "targets": [{"node": "n1", "iface": "awg0", "type": "awg", "ip": "10.8.0.9/32"}]}}})
# [12] torrents leave q-node directly, except from awg1, whose own Torrents / P2P block is on
J("nodes.json", {"n1": {"name": "q-node", "endpoint_host": "203.0.113.7", "p2p": {"action": "direct"}, "ifaces": {"awg1": {"block": ["torrents"]}},
                        "csqtt": {"csqtt1": {"listen": "0.0.0.0:56002"}, "csqtt2": {"listen": "0.0.0.0:56003"}, "csqtt3": {"listen": "0.0.0.0:56005", "fork": "mrtt", "line": "mrtt"}},
                        "wdtt": {"wdtt1": {"listen": "0.0.0.0:56000", "fork": "amurcanov", "wg_port": 56001}}},
                 "n2": {"name": "q-node2", "endpoint_host": "203.0.113.8",
                        "wdtt": {"wdtt1": {"listen": "0.0.0.0:56000", "fork": "amurcanov", "wg_port": 56001},
                                 "wdtt2": {"listen": "0.0.0.0:56010", "fork": "amurcanov", "wg_port": 56011}}},
                 "n3": {"name": "q-node3", "endpoint_host": "203.0.113.9"}})
J("stats/stats-n3.json", {"interfaces": {"wg0": {"meta": {"public_key": base64.b64encode(os.urandom(32)).decode(), "listen_port": 51830,
                                                             "endpoint": "203.0.113.9:51830", "subnet": "10.17.0.0/24"}}}})
J("stats/stats-n2.json", {"interfaces": {}, "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.2.4-3"},
                                                     {"iface": "wdtt2", "fork": "amurcanov", "version": "1.2.4-3"}]})
AWG = {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}
b64 = lambda n: base64.b64encode(os.urandom(n)).decode()
J("stats/stats-n1.json", {"interfaces": {
        "awg0": {"meta": {"public_key": b64(32), "listen_port": 51820, "endpoint": "203.0.113.7:51820", "subnet": "10.8.0.0/24", "awg_params": AWG}},
        "awg1": {"meta": {"public_key": b64(32), "listen_port": 51821, "endpoint": "203.0.113.7:51821", "subnet": "10.9.0.0/24", "awg_params": AWG}},
        "wg0": {"meta": {"public_key": b64(32), "listen_port": 51830, "endpoint": "203.0.113.7:51830", "subnet": "10.7.0.0/24"}}},
    "csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"},   # an older node's row: no line (2.1, filters nothing)
              {"iface": "csqtt2", "fork": "csqtt", "version": "2.5.1", "line": "2.5"},
              {"iface": "csqtt3", "fork": "mrtt", "version": "mrtt-1.0-1", "line": "mrtt"}],
    "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.2.4-3"}],
    "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-1", "listen": "0.0.0.0:56100", "connect": "127.0.0.1:51820", "wrap_key": "k" * 64, "version": "v4.0.3"},
                     {"service": "vk-turn-proxy-samosvalishe-2", "listen": "0.0.0.0:56101", "connect": "127.0.0.1:51830", "wrap_key": "j" * 64, "version": "v4.0.3"},
                     # [12] a plain fork's proxy (cacggghp: no obfuscation) — its cell carries the turtle
                     {"service": "vk-turn-proxy-cacggghp-4", "listen": "0.0.0.0:56104", "connect": "127.0.0.1:51830", "wrap_key": "", "version": "v1.0.0"},
                     # [10] a proxy of a HIDDEN fork a node still runs (MYSOREZ, hidden 2026-10-14)
                     {"service": "vk-turn-proxy-MYSOREZ-3", "listen": "0.0.0.0:56102", "connect": "127.0.0.1:51830", "wrap_key": "m" * 64, "version": "v4.0.3"}],
    "net_carried": ["192.168.50.0/24"],
    "p2p_fwd": {"awg0": {"addr": "45.67.89.10", "taken": []}}})   # [12] S12: q-node forwards awg0's devices' own ports

SEAL = r"""
const [k, pt] = process.argv.slice(1);
const key = await crypto.subtle.importKey('raw', Buffer.from(k, 'hex'), {name: 'AES-GCM'}, false, ['encrypt']);
const iv = crypto.getRandomValues(new Uint8Array(12));
const ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key, new TextEncoder().encode(pt)));
const all = new Uint8Array(12 + ct.length); all.set(iv); all.set(ct, 12);
console.log(Buffer.from(all).toString('base64'));
"""
users_sub, links = {}, {}
for uid, pid in (("u1", "p1"), ("u2", "p2"), ("u4", "p5"), ("u5", "p6"), ("u6", "p7"), ("u7", "p8"), ("u8", "p9")):
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
def perturbed_web(old, new, what, fname="sub.js"):
    global WEB
    src = open(os.path.join(ROOT, fname)).read()
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: its anchor is not in %s exactly once (%d), so the perturbation cannot be applied" % (what, fname, src.count(old)))
        sys.exit(1)
    WEB = os.path.join(D, "web")
    os.makedirs(os.path.join(WEB, "vendor"))
    for f in ("sub.html", "sub.css", "sub.js", "turn-artifacts.js", "VERSION", "vendor/qrcode.js"):
        if os.path.exists(os.path.join(ROOT, f)):
            shutil.copy(os.path.join(ROOT, f), os.path.join(WEB, f))
    with open(os.path.join(WEB, fname), "w") as f:
        f.write(src.replace(old, new))

if P_VOLLINE:
    perturbed_web('    if (vol && vol.limit) {', '    if (false) {', "the volume line")
    s2 = open(os.path.join(WEB, "sub.js")).read().replace('if (vol && vol.state === "cut") showState', 'if (false) showState')
    open(os.path.join(WEB, "sub.js"), "w").write(s2)
if P_VOLDAY:
    perturbed_web('return new Date(Date.UTC(y, m - 1, dd)).toLocaleDateString(LANG === "ru" ? "ru-RU" : undefined, { timeZone: "UTC" });',
                  'return new Date(Date.UTC(y, m - 1, dd) - 3 * 3600e3).toLocaleDateString(LANG === "ru" ? "ru-RU" : undefined);',
                  "the reset day as the panel's day (an MSK midnight shown in the browser's zone)")
if P_VOLDEV:
    perturbed_web('var volCut = expired && peer.vol_back != null;', 'var volCut = false;', "a device's own volume cut")
if P_MACOS:
    perturbed_web('if (!turnGetApp(csqttRunFork(tt.csqtt), (tt.csqtt || {}).version, false, (tt.csqtt || {}).line)) return;', "", "the csqtt client-for-this-OS guard")
if P_LINE:
    perturbed_web('      if (forkId === "csqtt" && (cl.csqtt_lines || ["2.1"]).indexOf(line || "2.1") < 0) return null;   // this app speaks another csqtt line\n', "",
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
if P_OVERSCROLL:
    perturbed_web("\n  overscroll-behavior: contain; }", " }", "the bubble's overscroll containment", "sub.css")
if P_PICKSHORT:
    perturbed_web('icon.title = x.getAttribute("data-note") || ', 'icon.title = ', "the picker icon's tooltip being the whole note")
if P_PICKMARK:
    perturbed_web('        x.replaceWith(icon);\n', "", "the picker's badge copies turning their marker buttons into icons")
if P_CSQRANK:
    perturbed_web(" || !!(clients[id] || {}).cli; };   // `cli`: csq-socks", "; };", "csq-socks ranked after the apps")
if P_LINE25:
    perturbed_web('    if (mode === "default" && forkId === "csqtt" && line && line !== "2.1") {',
                  '    if (mode === "default" && forkId === "csqtt" && line === "mrtt") {', "the 2.5 line's own default")
if P_LINEMRTT:
    perturbed_web('        var cga = turnGetApp(cfk, cd.version, false, cd.line);', '        var cga = turnGetApp("csqtt", cd.version, false, cd.line);', "the MRTT fork's own apps and defaults")
if P_RUNFORK:
    perturbed_web('        var cfk = csqttRunFork(cd);', '        var cfk = cd.fork || "csqtt";', "the fork the server runs, not its record's")
if P_MRTTBY:
    perturbed_web('cga ? appAuthor(cga) : forkLabel(cfk), cffork);', 'forkLabel("csqtt"), cffork);', "MRTT's own author on its tag")
if P_PICKRANK:
    perturbed_web('turnGetApp(forkId, null, awg, undefined, "default"); if (!ga) return 9;', 'turnGetApp(forkId, null, awg); if (!ga) return 9;',
                  "card ranking on the operator's default, never the pick")
if P_CLIPHONE:
    perturbed_web(' && !(phone && appIsCli(r.cid))) out.push(r);', ') out.push(r);', "no command-line client in a phone's list")
if P_PICKCLONE:
    perturbed_web('        x.classList.remove("scell-tag-pick"); x.removeAttribute("role"); x.removeAttribute("tabindex"); x.removeAttribute("aria-label");\n',
                  "", "the connection list's badge copy stripped of the chip's button")
if P_PICKJUMP:
    perturbed_web('var d = nt.getBoundingClientRect().top - top0; if (Math.abs(d) < 1) return;', 'return;', "the tapped badge kept in place")
if P_STALEPICK:
    perturbed_web('      return lst[0] || null;   // a stale pick', '      return pk ? null : lst[0] || null;   // a stale pick', "a stale pick falls back")
if P_DUPPORT:
    perturbed_web('x.dupFork = !!k && Object.keys(nport[k]).length > 1;', 'x.dupFork = false;', "two cards that read alike keep their port")
if P_STALEOFFER:
    perturbed_web('    if (_toastEl && _toastEl.classList.contains("ap-toast")) {', '    if (false) {', "a pick drops an earlier offer")
if P_SAMEPORT:
    perturbed_web('x.dupFork = !!k && Object.keys(nport[k]).length > 1;',
                  'x.dupFork = !!k && items.filter(function (y) { return same(y) === k; }).length > 1;', "a port only where it tells cards apart")
if P_ECHOPORT:
    perturbed_web('String(kind).replace(/ :\\d+$/, "").toUpperCase()', 'String(kind).toUpperCase()', "the repeat compared without its port")
if P_OFFEROPEN:
    perturbed_web('  function openAppPicker(info) {\n    closeAllHints();\n',
                  '  function openAppPicker(info) {\n    closeAllHints();\n    if (_toastEl) { try { _toastEl.remove(); } catch (_) {} _toastEl = null; }\n',
                  "an offer kept while a list only opens")
if P_OFFERTOP:
    perturbed_web('max-width: min(92vw, 440px); z-index: 89; }', 'max-width: min(92vw, 440px); z-index: 95; }', "the offer under an open list", fname="sub.css")
if P_WGSTART:
    perturbed_web('      var wcid = wga ? wga.cid : "";', '      var wcid = "amneziavpn";', "WG / AWG Start follows the pick")
if P_WGLIST:
    perturbed_web('if (!app || !app[os]) return;', 'if (!app) return;', "a WG / AWG app offered only where it has a link")
if P_WGCOLLAPSE:
    perturbed_web('    if (kind && !echo) {', '    if (kind) {', "the protocol dropped where the app repeats it")
if P_WSVNOTE:
    perturbed_web('      if (wga && wga.cid === "wingsv") node.appendChild(el("div", "scell-appnote", t("wingsvOld")));', '', "WINGS V's old-profile note")
if P_LAYWIDE:
    perturbed_web('function subLayout() { return _layWideMQ && _layWideMQ.matches ? "wide" : _layColMQ && _layColMQ.matches ? "col" : ""; }',
                  'function subLayout() { return ""; }', "the PC / tablet layouts")
if P_LAYPHONE:
    perturbed_web('matchMedia("(min-width: 640px) and (min-height: 600px)")', 'matchMedia("(min-width: 1px)")', "a phone left out of the layouts")
if P_NAVGO:
    perturbed_web("        r.onclick = function () { go(en.pi, en.ci); };", "        r.onclick = function () {};", "a row of the list shows its card")
if P_ONECARD:
    perturbed_web("body:is(.lay-wide, .lay-col) .ppage { display: none; }", "", "one card at a time", fname="sub.css")
if P_PCDL:
    perturbed_web('if (c.view === "qr" && c.qrUrl && subLayout() !== "wide") downloadImage(c.qrUrl, nm);',
                  'if (c.view === "qr" && c.qrUrl) downloadImage(c.qrUrl, nm);', "the PC's Download saves the config")
if P_SIDETEXT:
    perturbed_web('if (subLayout() !== "wide" || !ctrl.ready', 'if (true || !ctrl.ready', "the QR's text beside it")
if P_MODAL:
    perturbed_web("try { new MutationObserver(syncModal).observe(document.body, { childList: true }); } catch (_) {}", "", "modal pop-ups")
if P_STARTORB:
    perturbed_web('START_SVG.replace(/startorb/g, "startorb" + (++_startN))', "START_SVG", "each Start orb's own gradient")
if P_PCGRID:
    perturbed_web('grid-template-columns: auto minmax(260px, 1fr); grid-template-areas: "head head" "stage node" "stage vk" "stage bar" "stage side" "stage .";',
                  'grid-template-columns: minmax(0, 1fr); grid-template-areas: "head" "node" "vk" "stage" "side" "bar" ".";', "the PC card's two columns", fname="sub.css")
if P_NAVNETS:
    perturbed_web('      if (at < 0) at = Math.min(_layDev, peers.length - 1); else _layDev = at;', "      if (at >= 0) _layDev = at;", "the networks card keeps the device's connections open")
if P_NAVREBUILD:
    perturbed_web('      if (at < 0) at = Math.min(_layDev, peers.length - 1); else _layDev = at;', "      if (at < 0) return;", "a rebuild on the networks card keeps the device open")
if P_LAYNAV:
    perturbed_web("body.lay-nav .bar .who, body.lay-nav .bar .who-row { display: none; }",
                  "body:is(.lay-wide, .lay-col) .bar .who, body:is(.lay-wide, .lay-col) .bar .who-row { display: none; }", "the name kept where no list shows it", fname="sub.css")
if P_DLLABEL:
    perturbed_web('c.ext === "txt" ? t("dl") : t("download");', 'c.ext === "txt" ? t("dlLink") : t("download");', "Download link only for a link")
if P_DLGNAME:
    perturbed_web('        if (nm) { if (!nm.id) nm.id = "swg-dlg-" + (++_modalN); top.setAttribute("aria-labelledby", nm.id); }\n', "", "each dialog named")
if P_DLGLEVEL:
    perturbed_web('top.setAttribute("aria-labelledby", nm.id);', 'top.setAttribute("aria-label", nm.textContent.trim());', "a dialog's name follows its title")
if P_BACKARROW:
    perturbed_web(' ar.setAttribute("aria-hidden", "true");', "", "the back arrow kept out of the device's name")
if P_LIVEPRE:
    perturbed_web("    liveRegion();                                      // in the page before the first toast, so the toast is read out\n", "",
                  "the status region in the page before the first toast")
if P_ZOOMFOCUS:
    perturbed_web("if (!f) { top.tabIndex = -1; f = top; }", "if (!f) return;", "a dialog with no control takes the focus")
if P_NETSROWS:
    perturbed_web('grid-template-rows: none; justify-items: center;', 'justify-items: center;', "the networks card's three rows", fname="sub.css")
if P_WGNOTE:
    perturbed_web('                 note: (t("dlNotesWg") || {})[id + "@" + os] || "" });', '                 });', "a WG / AWG card's own download note")
if P_WGSCAN:
    perturbed_web("if (appScans(wcid)) ctrl.zoomTail = wga.app; }", "ctrl.zoomTail = wga.app; }", "the zoom caption names only an app that scans")
if P_WGZOOM:
    perturbed_web("if (appScans(wcid)) ctrl.zoomTail = wga.app; }", "}", "the enlarged QR names the card's app")
if P_WGDL:
    perturbed_web('      if (wga) node.appendChild(getAppRow(wga));   // under the server/app name line', '      if (wga) node.appendChild(getAppRow(wgAppList(tgt.type)[0]));   //',
                  "the WG / AWG download row follows the pick")
if P_CSQSTEPS:
    perturbed_web('cga.cid === "csqsocks" ? ((t("csqSocksSteps") || {})[subOs()] || null)', 'cga.cid === "csqsocks" ? null', "csq-socks's own steps")
if P_LL25:
    perturbed_web('(cga.cid === "lalune" && cd.line === "2.5") ? t("laluneSteps25") : null', 'null', "La Lune's 2.5 steps")
if P_LLFIRE:
    perturbed_web("ctrl.noAutoFire = !(cga && cga.autostart);", "ctrl.noAutoFire = !(cga && cga.autostart) || !!ctrl.stepList;", "a one-tap app handed the link")
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
    _wire = '                    tg.update(_p2p_fwd_of(p, tg, describe, roster.get("peers"), pid))\n'
    if _ss.count(_wire) != 1:
        print("PERTURB FAILED — the incoming port's wiring: its anchor is not in swg-sub exactly once"); sys.exit(1)
    SUB = os.path.join(D, "swg-sub")
    open(SUB, "w").write(_ss.replace(_wire, ""))
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
        tag: txt(c, ".scell-tag"), by: txt(c, ".scell-tag-by"), app: txt(c, ".scell-app"), chip: !!c.querySelector(".scell-tag-pick"), getapp: txt(c, ".scell-getapp"), role: txt(c, ".scell-role-if"),
        payload: txt(c, "pre.cfgtext"), fail: txt(c, ".cfg-fail"), text: c.textContent, p2p: (x => x ? x.getAttribute("aria-label") : null)(c.querySelector(".scell-p2p")),
        note: (x => x ? x.getAttribute("data-note") : null)(c.querySelector(".scell-p2p")),
        qr: !!c.querySelector(".qrbox img[src^='data:image']") })) })) };
})()"""

DESK_COL = (1280, 560, False)   # a desktop window too short for the PC layout: the scrolling column, its Connections picker
def render(uid, os_, lang, phone=False, desktop=False, ls=None, size=None):
    """Load `uid`'s subscription as a visitor on `os_` reading `lang`, the way the page's own selectors persist those. `phone`: a
    390×844 touch viewport (the narrow layout); `desktop`: 1280×800 (a PC: the devices listed beside one card); `size`:
    (width, height, touch) for any other. The browser's own window (780×493) is the landscape column."""
    tab = Tab(br)
    if phone or desktop or size:
        tab.br.send("Emulation.setDeviceMetricsOverride", dict({"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True} if phone
                    else {"width": size[0], "height": size[1], "deviceScaleFactor": 1, "mobile": size[2]} if size
                    else {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False}), session=tab.s)
    tab.goto(ORIGIN + "/healthz")                       # same origin, so the page's localStorage can be seeded before it loads
    for _ in range(50):
        if tab.ev("location.href").startswith(ORIGIN):
            break
        time.sleep(0.1)
    # Item 24's own keys start clean: no app picked, the one-time roll off (it would swap a badge's text for its labels while a check
    # reads it) — unless `ls` says otherwise ({key: value, or None to remove}); the tabs share one localStorage.
    seed = dict({"swgsub-os": os_, "swgsub-lang": lang, "swgsub-apphint": "1"}, **(ls or {}))
    tab.ev("Object.keys(localStorage).filter(k => k.startsWith('swgsub-app:')).forEach(k => localStorage.removeItem(k)); "
           + "; ".join(("localStorage.setItem(%s, %s)" % (json.dumps(k), json.dumps(v))) if v is not None else "localStorage.removeItem(%s)" % json.dumps(k)
                       for k, v in seed.items()) + "; true")
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
      // a relay's port (two relays of one fork on this device) is not part of what a probe names
      const i = cells.findIndex(c => ((c.querySelector('.scell-tag') || {}).textContent || '').replace(/ :\d+ · /, ' · ').includes(%s));
      if (i < 0) return 'no cell';
      pg._seek(i, null);""" % (json.dumps(mode), json.dumps(badge_has))

def seek_role_js(role):
    """seek_js's twin for a Turn cell found by its version chip (`CSQTT 2.5`) — the only thing apart when one app serves both."""
    return r"""const pg = [...document.querySelectorAll('section.ppage')].find(p => p.getAttribute('data-mode') === 'turn');
      if (!pg) return 'no page';
      const cells = [...pg.querySelectorAll('.scell')];
      const i = cells.findIndex(c => ((c.querySelector('.scell-role-if') || {}).textContent || '') === %s);
      if (i < 0) return 'no cell';
      pg._seek(i, null);""" % json.dumps(role)

def start_on(tab, mode, badge_has, seek=None):
    """Click Start on the cell of `mode` whose badge contains `badge_has` (or the one `seek` finds); return (clipboard writes,
    overlay steps, navigations)."""
    n0 = len(tab.mine("Page.frameRequestedNavigation"))
    c0 = len(tab.mine("Runtime.bindingCalled"))
    res = tab.ev(r"""(() => {
      %s
      pg.querySelector('.pbtn-start').click();
      // read the steps NOW: the handler shows them synchronously, and a one-tap fallback may replace this document soon after
      return {res: 'clicked', steps: [...document.querySelectorAll('.ph-overlay .ph-step')].map(s => s.textContent)};
    })()""" % (seek or seek_js(mode, badge_has)))
    steps = res.get("steps") if isinstance(res, dict) else []
    res = res.get("res") if isinstance(res, dict) else res
    tab.br.pump(1.6)                                     # past fireDeepLink's 1 s "did the app take over" beat
    clip = [e["params"].get("payload", "") for e in tab.mine("Runtime.bindingCalled")[c0:] if e["params"].get("name") == "__swgClip"]
    navs = [e["params"].get("url", "") for e in tab.mine("Page.frameRequestedNavigation")[n0:]]
    return res, clip, steps, navs

def start_on_role(tab, role):
    return start_on(tab, "turn", None, seek_role_js(role))

SHOTS = os.environ.get("SUB_SHOTS") or ""   # SUB_SHOTS=<dir> keeps screenshots of [13]'s import steps
def shot(tab, name):
    if SHOTS:
        with open(os.path.join(SHOTS, name + ".png"), "wb") as fh:
            fh.write(base64.b64decode(tab.br.send("Page.captureScreenshot", {"format": "png"}, session=tab.s)["data"]))

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
        got = [(p["mode"], PORT_WORDS[lang] in (c["note"] or "") and "45.67.89.10:20016" in (c["note"] or ""))
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
    nbos = tab.ev("(() => { const b=document.querySelector('.note-bubble'); return b ? getComputedStyle(b).overscrollBehaviorY : '' })()")
    check("[12] a fling past the end of the bubble's text stays in it — chained to the page, the scroll closed the bubble", nbos == "contain", nbos)
    inner = tab.ev("(() => { const b=document.querySelector('.note-bubble'); if (!b) return false; b.style.maxHeight='30px'; b.scrollTop=20;"
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
    # the Linux WDTT cell: Rawline (one-tap, 1.8.12 item 10) outranks PWDTT where no default is saved
    for os_, cell, author in (("windows", "CSQTT 2.1", "luminescq"), ("linux", "WDTT", "ttrroyy"), ("android", "CSQTT 2.1", "Endlad2")):
        en, ru = by_words(os_, "en").get(cell), by_words(os_, "ru").get(cell)
        check("[2] %s %s cell: EN badge says ' by %s'" % (os_, cell, author), en == " by " + author, by_words(os_, "en"))
        check("[2] %s %s cell: RU badge says ' от %s', no English" % (os_, cell, author), ru == " от " + author, by_words(os_, "ru"))
    # a turn proxy's card names its server's author beside the badge (operator, 2026-11-25), an interface's card its type
    is_proxy = lambda c: not (c["role"] or "").startswith(("CSQTT", "MRTT", "WDTT"))
    tp = [c for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if is_proxy(c) and c["by"]]
    check("[2] the turn-proxy cell's author word is translated wherever one renders (RU)", tp and all(" by " not in c["by"] for c in tp),
          [c["by"] for os_ in ALL_OS for c in turn_cells(renders[(os_, "ru")]) if c["by"]])

    # [10] a hidden fork a node still runs keeps its whole app map (operator, 2026-10-14: "hidden like cacggghp")
    an = turn_cells(renders[("android", "en")])
    check("[10] Android: the MYSOREZ proxy (hidden fork, still running) offers its users the MYSOREZ app",
          any((c["tag"] or "").startswith("MYSOREZ · VK TURN Proxy") for c in an), [c["tag"] for c in an])
    hd = [c for c in an if re.match(r"hackdiaz( :\d+)? · ", c["tag"] or "")]   # the label exactly: it is a prefix of its owner, hackdiaz-dev
    check("[10] …while hackdiaz's cells (a visible fork) do not offer that hidden app",
          hd and not [c for c in hd if "MYSOREZ" in (c["tag"] or "")], [c["tag"] for c in an])

    # [9] an app whose own tunnel is WireGuard only (anton48's VK TURN Proxy, `awg: false`) is never handed out for an AmneziaWG
    #     interface behind a proxy — the app itself warns that AmneziaWG keys cannot work (the review of 356a08f9, F3)
    ios = turn_cells(renders[("ios", "en")])
    # Anna has two hackdiaz proxies, one before awg0 and one before wg0; their cards name the server, not the interface, so they
    # are told apart by count: on iOS only the WireGuard one has an app
    ihd = [c for c in ios if c["role"] == "hackdiaz"]
    check("[9] iOS: no AmneziaWG cell offers VK TURN Proxy (the AWG proxy has no iOS app, so it shows no card): one hackdiaz card",
          len(ihd) == 1, [(c["role"], c["tag"]) for c in ios])
    check("[9] …while the WireGuard interface's proxy still does", len(ihd) == 1 and "VK TURN Proxy" in (ihd[0]["tag"] or ""),
          [(c["role"], c["tag"]) for c in ios])
    check("[9] control: on Android the AmneziaWG proxy keeps its cell (FreeTurn carries AmneziaWG): both hackdiaz cards, FreeTurn",
          [c["app"] for c in turn_cells(renders[("android", "en")]) if c["role"] == "hackdiaz"] == ["FreeTurn by hackdiaz"] * 2,
          [(c["role"], c["tag"]) for c in turn_cells(renders[("android", "en")])])

    # [6] a fork that changed hands is named by its catalog label: samosvalishe's repos are gone and hackdiaz (GitHub: hackdiaz-dev) carries them
    # on, but the id stays (it is in every node's unit names) — so the id must never reach the visitor
    fp = [(os_, lang, c) for os_ in ALL_OS for lang in ("en", "ru") for c in turn_cells(renders[(os_, lang)])
          if is_proxy(c) and not (c["tag"] or "").startswith(("MYSOREZ", "cacggghp"))]   # [10]'s and [12]'s proxies are other forks
    # the label as a word of its own: "hackdiaz" is a prefix of the owner, hackdiaz-dev, which must not pass for it
    check("[6] the samosvalishe-fronted cell's badge names hackdiaz on every OS and language",
          fp and all(re.search(r"(?<![\w-])hackdiaz(?![\w-])", c["tag"] or "") for _o, _l, c in fp), [(o, l, c["tag"]) for o, l, c in fp])
    leak = [(os_, lang, c["text"][:120]) for os_ in ALL_OS for lang in ("en", "ru") for p in renders[(os_, lang)]["pages"]
            for c in p["cells"] if "samosvalishe" in (c["text"] or "")]
    check("[6] …and no cell anywhere says samosvalishe", not leak, leak[:3])

    # [7] a WDTT fork's own app is its default: XXcipherX's one-tap app stood in for amurcanov's until its repository went
    #     (operator, 2026-10-14) — the WDTT cell on Android now hands out amurcanov's WDTT, which imports by paste
    tab, _ = render("u1", "android", "en")
    wc = [c for p in renders[("android", "en")]["pages"] for c in p["cells"] if "WDTT" in (c["tag"] or "")]
    check("[7] the WDTT cell's Android app is amurcanov's own WDTT (no cross-author app, never XXcipherX's)",
          wc and all((c["tag"] or "") == "WDTT by amurcanov" for c in wc), [(c["tag"], c["by"]) for c in wc])
    res, clip, steps, navs = start_on(tab, "turn", "WDTT")
    check("[7] …and its Start copies the wdtt:// link and shows the import steps (the app opens no scheme), firing nothing",
          res == "clicked" and steps and not navs and any(x.startswith("wdtt://") for x in clip), (res, navs, steps, [x[:20] for x in clip]))
    tab.close()
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    serve["turn_client_default"] = {"csqtt": {"android": "lalune"}, "amurcanov": {"android": "wdttplus"}}
    J("subs/serve.json", serve)
    # [8] an app from the server's own repository follows the server's running version
    def bubble(tab, badge_has, seek=None):
        return tab.ev(r"""(() => {
          %s
          const btn = cells[i].querySelector('.scell-getapp-btn') || pg.querySelector('.scell-getapp-btn');
          if (!btn) return 'no button';
          btn.click();
          const b = document.querySelector('.dl-bubble');
          return b ? {ver: (b.querySelector('.dl-bubble-ver') || {}).textContent || '', links: [...b.querySelectorAll('a')].map(a => a.href)} : 'no bubble';
        })()""" % (seek or seek_js("turn", badge_has)))
    bubble_role = lambda tab, role: bubble(tab, None, seek_role_js(role))
    pinned = lambda b, tag, url: isinstance(b, dict) and tag in b["ver"] and "matches this server" in b["ver"] and url in b["links"]
    serve = json.load(open(os.path.join(D, "subs", "serve.json")))
    keep_default = serve["turn_client_default"]
    serve["turn_client_default"] = {}   # the CSQTT app itself (the operator's Android default for csqtt is La Lune)
    J("subs/serve.json", serve)
    tab, _ = render("u1", "android", "en")
    bb = bubble(tab, "CSQTT")
    check("[8] the CSQTT app's bubble offers v2.1.9 — the release the server runs, from our csqtt-app-2.1.9, though v2.5.1 is the latest — and says it matches",
          pinned(bb, "v2.1.9", PIN_APK) and not any("csqtt-app-2.5.1" in u or "amurcanov" in u for u in bb["links"]), bb)
    wb = bubble(tab, "WDTT by amurcanov")
    check("[8] the WDTT cell (amurcanov 1.2.4-3) offers its own app's v1.2.4 — the WDTT server's version reaches the page",
          pinned(wb, "v1.2.4", WDTT_APK), wb)
    fb = bubble(tab, "hackdiaz · FreeTurn")
    check("[8] FreeTurn on a hackdiaz proxy is NOT handed the CLI release's Android binary: its repository is not the server's",
          isinstance(fb, dict) and "matches this server" not in fb["ver"] and CLI_AND not in fb["links"], fb)
    tab.close()
    serve["turn_client_default"] = keep_default
    J("subs/serve.json", serve)
    tab, _ = render("u1", "linux", "en")   # no Linux default saved for hackdiaz: an app outranks the CLI (1.8.12 item 10)
    check("[8] with no default saved, hackdiaz on Linux hands out Rawline, not the CLI", isinstance(bubble(tab, "hackdiaz · Rawline"), dict))
    tab.ev("document.querySelectorAll('.dl-bubble').forEach(b => b.remove()), localStorage.removeItem('swgsub-hasapp-rawline'), 1")
    res, clip, steps, navs = start_on(tab, "turn", "hackdiaz · Rawline")
    asked = tab.ev("!!document.querySelector('.start-choice')")
    check("[16] Rawline on the desktop (it registers rawline://): the first Start asks Open / Get — no import steps, nothing fired yet",
          res == "clicked" and asked and not steps and not navs, (res, asked, steps, navs))
    tab.ev("document.querySelectorAll('.start-choice').forEach(b => b.remove()), localStorage.setItem('swgsub-hasapp-rawline', '1'), 1")
    res, clip, steps, navs = start_on(tab, "turn", "hackdiaz · Rawline")
    def rl_payload(u):
        try:
            return base64.urlsafe_b64decode(u.split("rawline://add/", 1)[1] + "==").decode()
        except Exception:
            return ""
    pl = rl_payload(next((u for u in navs if u.startswith("rawline://add/")), ""))
    check("[16] …once it is known installed, Start opens rawline://add/ holding a JSON list with the freeturn:// link (the desktop's form)",
          not steps and pl.startswith('["freeturn://') and json.loads(pl)[0].startswith("freeturn://"), (steps, navs, pl[:60]))
    tab.close()
    serve["turn_client_default"] = dict(keep_default, samosvalishe={"android": "rawline"})   # RawlineMobile picked for hackdiaz on Android
    J("subs/serve.json", serve)
    tab, _ = render("u1", "android", "en")
    res, clip, steps, navs = start_on(tab, "turn", "hackdiaz · RawlineMobile")
    pl = rl_payload(next((u for u in navs if u.startswith("rawline://add/")), ""))
    check("[16] RawlineMobile on Android: Start fires rawline://add/ holding the plain freeturn:// link (the app's form), no steps",
          res == "clicked" and not steps and pl.startswith("freeturn://"), (res, steps, navs[:2], pl[:60]))
    tab.close()
    serve["turn_client_default"] = {"csqtt@2.5": {"android": "rawline"}}
    J("subs/serve.json", serve)
    tab, _ = render("u4", "android", "en")
    res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
    pl = rl_payload(next((u for u in navs if u.startswith("rawline://add/")), ""))
    check("[16] RawlineMobile on a csqtt 2.5 server: it opens rawline://add/ with the sealed link, and the clipboard keeps the plain sealed link (every app reads it)",
          pl.startswith("csqtt://") and not pl.startswith("csqtt://connect") and pl in clip and not any(x.startswith("rawline:") for x in clip),
          (res, [x[:30] for x in clip], [u[:30] for u in navs], pl[:40]))
    tab.close()
    serve["turn_client_default"] = {"csqtt@2.5": {"linux": "rawline"}}
    J("subs/serve.json", serve)
    tab, _ = render("u4", "linux", "en")
    tab.ev("localStorage.removeItem('swgsub-hasapp-rawline'), 1")
    res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
    asked = tab.ev("!!document.querySelector('.start-choice')")
    check("[16] Rawline on a desktop csqtt 2.5 server: the first Start asks Open / Get and copies the plain sealed link, firing nothing",
          asked and not steps and not navs and any(x.startswith("csqtt://") and not x.startswith("csqtt://connect") for x in clip)
          and not any(x.startswith("rawline:") for x in clip), (res, asked, [x[:30] for x in clip], navs[:2]))
    tab.close()
    serve["turn_client_default"] = keep_default
    J("subs/serve.json", serve)
    # [17] the MRTT line: its own app on Android (one-tap, the link sealed under MRTT's seed), Rawline on the desktop, none on iOS
    serve["turn_client_default"] = {}
    J("subs/serve.json", serve)
    UNSEAL_M = r"""const l = process.argv[1].slice(7), b = Buffer.from(l.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
      const kh = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('mrtt-chiper-key'));
      const k = await crypto.subtle.importKey('raw', kh, {name: 'AES-GCM'}, false, ['decrypt']);
      try { console.log(new TextDecoder().decode(await crypto.subtle.decrypt({name: 'AES-GCM', iv: b.subarray(0, 12)}, k, b.subarray(12)))); }
      catch (e) { console.log(''); }"""
    unseal_m = lambda link: subprocess.run(["node", "--input-type=module", "-e", UNSEAL_M, link], capture_output=True, text=True, timeout=30).stdout.strip()
    tab, rd = render("u5", "android", "en")
    cells = turn_cells(rd)
    check("[17] Android, an MRTT server: one cell, the MRTT app, its chip says MRTT",
          len(cells) == 1 and "MRTT" in (cells[0]["tag"] or "") and cells[0]["role"] == "MRTT", [(c["tag"], c["role"]) for c in cells])
    check("[17] …its tag credits MRTT's author, ttrroyy, not csqtt's (amurcanov)",
          len(cells) == 1 and cells[0]["tag"] == "MRTT by ttrroyy", [c["tag"] for c in cells])
    res, clip, steps, navs = start_on(tab, "turn", "MRTT")
    ml = next((u for u in navs if u.startswith("mrtt://")), "")
    check("[17] …Start fires the mrtt:// link one-tap, sealed under MRTT's seed (MRTT's own decoder opens it to the server)",
          not steps and unseal_m(ml).startswith("connect?v=2&host=203.0.113.7&peer=56005&password=pw6csqtt"), (res, steps, [u[:30] for u in navs]))
    tab.close()
    tab, rd = render("u5", "linux", "en")
    cells = turn_cells(rd)
    tab.ev("localStorage.setItem('swgsub-hasapp-rawline', '1'), 1")
    res, clip, steps, navs = start_on(tab, "turn", "Rawline")
    pl = rl_payload(next((u for u in navs if u.startswith("rawline://add/")), ""))
    check("[17] Linux, an MRTT server: Rawline, opened with rawline://add/ around the mrtt:// link",
          len(cells) == 1 and "Rawline" in (cells[0]["tag"] or "") and pl.startswith('["mrtt://')
          and unseal_m(json.loads(pl)[0]).startswith("connect?v=2&host=203.0.113.7&peer=56005"), ([c["tag"] for c in cells], pl[:40]))
    tab.close()
    tab, rd = render("u5", "ios", "en")
    check("[17] iOS, an MRTT server: no app exists, no cell", not turn_cells(rd), [c["tag"] for c in turn_cells(rd)])
    tab.close()
    # mrtt-fork review F4: a switch to MRTT that fell back to 2.5 — the record says fork mrtt, the node runs 2.5: the page
    # offers what RUNS (amurcanov's apps and name), never the MRTT app, which can't connect to a 2.5 server
    _sp = os.path.join(D, "stats", "stats-n1.json")
    _keep = open(_sp).read()
    _st = json.loads(_keep)
    _hit = [r.update(line="2.5", version="2.5.1") or r for r in _st.get("csqtt") or [] if r.get("iface") == "csqtt3"]
    J("stats/stats-n1.json", _st)
    time.sleep(3.2)                                     # swg-sub's read cache (_READ_TTL, 3 s)
    tab, rd = render("u5", "android", "en")
    cells = turn_cells(rd)
    check("[17] a switch to MRTT that fell back to 2.5 (record fork mrtt, the node runs 2.5): amurcanov's app and name, never the MRTT app",
          len(_hit) == 1 and _hit[0].get("fork") == "mrtt" and len(cells) == 1 and "MRTT" not in (cells[0]["tag"] or "")
          and (cells[0]["tag"] or "").startswith("CSQTT by amurcanov"), (len(_hit), [(c["tag"], c["role"]) for c in cells]))
    tab.close()
    open(_sp, "w").write(_keep)
    time.sleep(3.2)
    tab, rd = render("u4", "android", "en")
    check("[17] …and Dana's 2.1 and 2.5 servers are not offered the MRTT app", not any("MRTT" in (c["tag"] or "") for c in turn_cells(rd)),
          [c["tag"] for c in turn_cells(rd)])
    tab.close()
    serve["turn_client_default"] = {"csqtt": {"android": "none"}}   # amurcanov's csqtt not offered on Android: MRTT is another fork
    J("subs/serve.json", serve)
    tab, rd = render("u5", "android", "en")
    check("[17] csqtt's \"Don't offer\" on Android (a 2.1 choice) leaves the MRTT server offered",
          len(turn_cells(rd)) == 1 and "MRTT" in (turn_cells(rd)[0]["tag"] or ""), [c["tag"] for c in turn_cells(rd)])
    tab.close()
    tab, rd = render("u4", "android", "en")
    check("[17] …while it still hides Dana's 2.1 server there", not any(c["role"] == "CSQTT 2.1" for c in turn_cells(rd)),
          [(c["tag"], c["role"]) for c in turn_cells(rd)])
    tab.close()
    serve["turn_client_default"] = {"mrtt": {"android": "rawline", "linux": "none"}}   # MRTT's own key: the fork's (operator 2026-11-25)
    J("subs/serve.json", serve)
    tab, rd = render("u5", "android", "en")
    check("[17] MRTT's own default (its fork's key) on Android names Rawline: the MRTT server hands out RawlineMobile, not the MRTT app",
          len(turn_cells(rd)) == 1 and "Rawline" in (turn_cells(rd)[0]["tag"] or ""), [c["tag"] for c in turn_cells(rd)])
    tab.close()
    tab, rd = render("u5", "linux", "en")
    check("[17] …and its \"Don't offer\" on Linux hides the MRTT server there", not turn_cells(rd), [c["tag"] for c in turn_cells(rd)])
    tab.close()
    serve["turn_client_default"] = {}
    J("subs/serve.json", serve)
    serve["turn_client_default"] = dict(keep_default, samosvalishe={"linux": "sidecar@samosvalishe"})   # the operator picks the CLI
    J("subs/serve.json", serve)
    tab, _ = render("u1", "linux", "en")
    lb = bubble(tab, "hackdiaz · Sidecar")
    check("[8] the hackdiaz CLI on Linux offers v4.0.3, the proxy's own release — a turn proxy's version reaches the page",
          pinned(lb, "v4.0.3", CLI_LIN), lb)
    tab.close()
    serve["turn_client_default"] = keep_default
    J("subs/serve.json", serve)
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
    tab, _ = render("u1", "android", "en", size=(844, 390, True))
    dk = settled_sw(tab)
    check("[5] control — a phone on its side: the header's one Connections button shows", dk and dk["shown"] == ["pswitch pswitch-head"], dk)
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
    # La Lune speaks 2.5 too (S13a, 2026-10-28), so the operator's Android default La Lune serves Dana's 2.5 server as well —
    # one tap, as on 2.1: Start hands it the sealed link and copies it, no steps (operator, 2026-10-29: "just open the app
    # with the link like before on android"); the CSQTTR step is the desktop's ([13])
    tab, rd = render("u4", "android", "en")
    cells = turn_cells(rd)
    c25 = [c for c in cells if c["role"] == "CSQTT 2.5"]
    c21 = on(rd, "56002")
    check("[11] Android, the operator's default La Lune: it serves the 2.5 server too (it speaks 2.5)",
          len(cells) == 2 and len(c25) == 1 and "La Lune" in (c25[0]["tag"] or ""), [(c["tag"], c["role"]) for c in cells])
    check("[11] …and the 2.1 server beside it", len(c21) == 1 and "La Lune" in (c21[0]["tag"] or ""), [c["tag"] for c in c21])
    res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
    sealed = next((x for x in clip if x.startswith("csqtt://") and not x.startswith("csqtt://connect")), "")
    check("[11] …its Start fires the SEALED link, one tap as before, and copies it — no steps",
          res == "clicked" and sealed and any(u == sealed for u in navs) and not steps, (res, [x[:40] for x in clip], steps, [u[:40] for u in navs]))
    tab.close()
    # the ranked default (no operator choice): amurcanov's CSQTT app, native, first on Android for both lines
    serve["turn_client_default"] = {}
    J("subs/serve.json", serve)
    tab, rd = render("u4", "android", "en")
    cells = turn_cells(rd)
    c25 = [c for c in cells if c["role"] == "CSQTT 2.5"]
    c21 = on(rd, "56002")
    check("[11] Android, ranked: the 2.5 server gets the CSQTT app", len(cells) == 2 and len(c25) == 1 and "CSQTT" in (c25[0]["tag"] or "")
          and "La Lune" not in (c25[0]["tag"] or ""), [(c["tag"], c["role"]) for c in cells])
    check("[11] …the 2.5 server shown as a QR (the 2.5 app scans one), while the 2.1 server's plain link has none",
          len(c25) == 1 and c25[0]["qr"] and len(c21) == 1 and not c21[0]["qr"], [(c["tag"], c["qr"]) for c in cells])
    # 2.1 and 2.5 cards were alike until the app was downloaded (operator, 2026-10-20): the chip names the server's version,
    # the download its app's — and a node that reports no line is a 2.1 one
    check("[11] the 2.5 server's card says CSQTT 2.5, and its download CSQTT 2.5.1",
          len(c25) == 1 and "CSQTT 2.5.1" in (c25[0]["getapp"] or ""), [(c["role"], c["getapp"]) for c in c25])
    check("[11] …the 2.1 server's card (no line reported) says CSQTT 2.1",
          len(c21) == 1 and c21[0]["role"] == "CSQTT 2.1", [c["role"] for c in c21])
    res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
    sealed = next((x for x in list(clip) + list(navs) if x.startswith("csqtt://") and not x.startswith("csqtt://connect")), "")
    p25 = _unseal(sealed) if sealed else ""
    check("[11] its Start hands out the SEALED link (the 2.5 app takes no other), which opens to its connect payload",
          p25.startswith("connect?v=2&host=203.0.113.7&peer=56003&password=pw5csqtt"), (res, [x[:40] for x in clip], [x[:40] for x in navs], p25))
    tab.close()
    tab, rd = render("u4", "android", "en")
    b25 = bubble_role(tab, "CSQTT 2.5")
    check("[11] …and its download is our 2.5.1 build (csqtt-app-2.5.1), shown as v2.5.1 and matching the server",
          pinned(b25, "v2.5.1", PIN25_APK) and not any("amurcanov" in u for u in b25["links"]), b25)
    tab.close()
    tab, rd = render("u4", "ios", "en")
    cells = turn_cells(rd)
    check("[11] iOS: no cell for the 2.5 server (VK TURN Proxy speaks 2.1), while the 2.1 server keeps its iPhone cell",
          len(cells) == 1 and len(on(rd, "56002")) == 1, [(c["tag"], (c["text"] or "")[:60]) for c in cells])
    tab.close()

    # [13] the 2.5 clients on the desktop (S13a): La Lune, and csq-socks — ours, a command-line client ranked after the apps
    # (operator, 2026-10-28: "2.1 and 2.5, ranked last") — and nothing changes for a 2.1 subscriber
    for os_ in ("linux", "windows"):
        for lang in ("en", "ru"):
            a = [c["tag"] for c in turn_cells(renders[(os_, lang)]) if c["role"] == "CSQTT 2.1"]
            check("[13] %s/%s: Anna's 2.1 server still offers FOCSQ, not csq-socks (ranked last)" % (os_, lang),
                  len(a) == 1 and "FOCSQ" in (a[0] or ""), a)
    STEP25 = {"en": "choose the *CSQTTR* protocol".replace("*", ""), "ru": "выберите протокол *CSQTTR*".replace("*", "")}
    tab, rd = render("u4", "linux", "en")   # no choice: Rawline, one-tap, outranks La Lune on the desktop (1.8.12 item 10)
    r25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]
    check("[13] with no choice the 2.5 server on the desktop gets Rawline (it opens one-tap)", len(r25) == 1 and "Rawline" in (r25[0] or ""), r25)
    tab.close()
    serve["turn_client_default"] = {"csqtt@2.5": {"linux": "lalune", "windows": "lalune"}}   # La Lune by the operator's choice
    J("subs/serve.json", serve)
    SOCKS = {("linux", "en"): "Run csq-socks set", ("linux", "ru"): "Выполните csq-socks set",
             ("windows", "en"): "Run .\\csq-socks set", ("windows", "ru"): "Выполните .\\csq-socks set"}
    for os_ in ("linux", "windows"):
        for lang in ("en", "ru"):
            tab, rd = render("u4", os_, lang)
            r25 = [c for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]
            r21 = [c for c in turn_cells(rd) if c["role"] == "CSQTT 2.1"]
            check("[13] %s/%s: the 2.5 server gets a cell — La Lune, chosen for 2.5 (FOCSQ speaks 2.1 only)" % (os_, lang),
                  len(r25) == 1 and "La Lune" in (r25[0]["tag"] or ""), [(c["tag"], c["role"]) for c in turn_cells(rd)])
            check("[13] %s/%s: …and its 2.1 server keeps FOCSQ" % (os_, lang), len(r21) == 1 and "FOCSQ" in (r21[0]["tag"] or ""), [c["tag"] for c in r21])
            res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
            shot(tab, "lalune25-%s-%s" % (os_, lang))
            check("[13] %s/%s: La Lune's Start on the 2.5 server copies the sealed link and names CSQTTR in the page's language" % (os_, lang),
                  any(x.startswith("csqtt://") and not x.startswith("csqtt://connect") for x in clip)
                  and any(STEP25[lang] in x for x in steps) and not any(u.startswith("csqtt:") for u in navs), (res, [x[:30] for x in clip], steps))
            tab.close()
    serve["turn_client_default"] = {"csqtt": {"linux": "csqsocks", "windows": "csqsocks"}}
    J("subs/serve.json", serve)
    for os_ in ("linux", "windows"):
        for lang in ("en", "ru"):
            tab, rd = render("u4", os_, lang)
            tags = [(c["role"], c["tag"], c["getapp"]) for c in turn_cells(rd)]
            check("[13] %s/%s: the operator's choice csq-socks serves both lines, with its download" % (os_, lang),
                  len(tags) == 2 and all("csq-socks" in (t or "") and "csq-socks" in (g or "") for _r, t, g in tags), tags)
            res, clip, steps, navs = start_on_role(tab, "CSQTT 2.5")
            shot(tab, "csqsocks-%s-%s" % (os_, lang))
            check("[13] %s/%s: csq-socks's Start copies the sealed link and shows its own steps (%s), firing nothing" % (os_, lang, SOCKS[(os_, lang)]),
                  any(x.startswith("csqtt://") and not x.startswith("csqtt://connect") for x in clip)
                  and any(SOCKS[(os_, lang)] in x for x in steps) and not any(u.startswith("csqtt:") for u in navs), (res, [x[:30] for x in clip], steps))
            tab.close()
    # [14] a default per csqtt LINE (operator, 2026-10-29): "csqtt@2.5" is 2.5's own — csq-socks for Linux, "none" for
    # Windows — while 2.1 keeps FOCSQ; a 2.1-only app stored there anyway (macOS has none; on Linux FOCSQ) changes nothing
    serve["turn_client_default"] = {"csqtt": {"linux": "focsq", "windows": "focsq"}, "csqtt@2.5": {"linux": "csqsocks", "windows": "none"}}
    J("subs/serve.json", serve)
    for lang in ("en", "ru"):
        tab, rd = render("u4", "linux", lang)
        r25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]; r21 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.1"]
        check("[14] linux/%s: 2.5's own default csq-socks serves the 2.5 server, 2.1's FOCSQ the 2.1 one" % lang,
              len(r25) == 1 and "csq-socks" in (r25[0] or "") and len(r21) == 1 and "FOCSQ" in (r21[0] or ""), [r21, r25])
        tab.close()
        tab, rd = render("u4", "windows", lang)
        r25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]; r21 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.1"]
        check("[14] windows/%s: 2.5's \"none\" hides only the 2.5 server; the 2.1 one keeps FOCSQ" % lang,
              r25 == [] and len(r21) == 1 and "FOCSQ" in (r21[0] or ""), [r21, r25])
        tab.close()
    serve["turn_client_default"] = {"csqtt": {"linux": "focsq"}, "csqtt@2.5": {"linux": "focsq"}}
    J("subs/serve.json", serve)
    tab, rd = render("u4", "linux", "en")
    r25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]
    check("[14] a 2.1-only app under csqtt@2.5 is passed over: the 2.5 server gets Rawline, as with no choice", len(r25) == 1 and "Rawline" in (r25[0] or ""), r25)
    tab.close()
    serve["turn_client_default"] = {}
    J("subs/serve.json", serve)

    # the CSQTT app's release is of the other line (no 2.5 release out): the 2.5 server is never offered the 2.1 app — La Lune,
    # which speaks 2.5, serves it instead. No 2.5 release also means no pin for the 2.5 build (the pin hands it csqtt-app-2.5.1).
    ((serve["turn_catalog"].get("pins") or {}).get("amurcanov/csqtt") or {}).pop("2.5.1", None)
    ca = serve["turn_catalog"]["clients"]["csqttapp"]["platforms"]["android"]
    ca.update({"tag": "v2.1.9", "url": PIN_APK, "page": "https://github.com/amurcanov/csqtt/releases/tag/v2.1.9",
               "assets": [{"name": "csqtt-v2.1.9.apk", "url": PIN_APK}]})
    J("subs/serve.json", serve)
    tab, rd = render("u4", "android", "en")
    c25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]
    check("[11] with only a 2.1 release of the CSQTT app, the 2.5 server is not offered it — La Lune serves it",
          len(c25) == 1 and "La Lune" in (c25[0] or ""), [(c["tag"], c["role"]) for c in turn_cells(rd)])
    tab.close()
    # the release is not resolved yet (a cold cache, GitHub rate-limited): no tag — the latest is 2.1's until proven otherwise
    for k in ("tag", "url", "page", "assets"):
        ca.pop(k, None)
    J("subs/serve.json", serve)
    tab, rd = render("u4", "android", "en")
    c25 = [c["tag"] for c in turn_cells(rd) if c["role"] == "CSQTT 2.5"]
    check("[11] with the CSQTT release not resolved yet, the 2.5 server is still not offered it — La Lune serves it",
          len(c25) == 1 and "La Lune" in (c25[0] or ""), [(c["tag"], c["role"]) for c in turn_cells(rd)])
    tab.close()
    # [15] a volume limit (limits-l4): the panel's usage.json gives a user's page its used / left, and a user it cut off sees
    # LIMIT REACHED with the day access returns — never the plain EXPIRED, which says the subscription itself ran out
    _u = json.load(open(os.path.join(D, "users.json")))
    _u["users"]["u2"]["id"] = "u2"                     # every roster record carries its id (user_set); the cut keys on it
    J("users.json", _u)
    _until = int(time.time()) + 10 * 86400             # the instant (old pages); `day` is the panel's local day, what is shown
    J("subs/usage.json", {"users": {"u1": {"used": 12_500_000_000, "limit": 50_000_000_000, "dir": "c", "period": "m", "until": _until, "day": 20271201, "state": ""},
                                    "u2": {"used": 5_000_000_000, "limit": 5_000_000_000, "dir": "d", "period": "w", "until": _until, "day": 20271201, "state": "cut"}},
                          "cut": ["u2"], "back": {"u2": 20271201}})
    time.sleep(3.5)                                    # swg-sub's shared read lives 3 s
    tab, rd = render("u1", "android", "en")
    line = tab.ev("(document.querySelector('.usage-line') || {}).textContent || ''")
    check("[15] used / left above the devices, resetting on the panel's own day", "12.5 of 50 GB used this month" in line and "resets 12/1/2027" in line, line)
    tab.close()
    tab, rd = render("u1", "android", "ru")
    line = tab.ev("(document.querySelector('.usage-line') || {}).textContent || ''")
    check("[15] …in Russian", "Использовано 12.5 из 50 ГБ за месяц" in line, line)
    tab.close()
    tab = Tab(br)
    tab.br.send("Emulation.setTimezoneOverride", {"timezoneId": "America/Los_Angeles"}, session=tab.s)   # west of the panel: an
    tab.goto(ORIGIN + "/healthz")                       # instant would read as Nov 30; same origin: the language seeded first
    time.sleep(0.3)
    tab.ev("localStorage.setItem('swgsub-lang', 'en'); localStorage.setItem('swgsub-os', 'android'); true")
    tab.goto(ORIGIN + "/" + links["u2"])
    st = ""
    for _ in range(80):
        st = tab.ev("(document.getElementById('state') || {}).textContent || ''")
        if st and "…" not in st and st.strip():
            if "LIMIT" in st or "EXPIRED" in st:
                break
        time.sleep(0.1)
    check("[15] a user cut off by volume sees LIMIT REACHED and the day access returns, not EXPIRED",
          "LIMIT REACHED" in st and "Access returns on 12/1/2027" in st and "EXPIRED" not in st, st)
    tab.close()
    # …and one device cut by its own limit: its page says the limit and the day it returns, the user's other devices stay
    J("subs/usage.json", {"users": {}, "cut": ["p1"], "back": {"p1": 20271201}})
    time.sleep(3.5)
    tab, rd = render("u1", "android", "en")
    dead = tab.ev("[...document.querySelectorAll('.peer-dead')].map(b => b.textContent).join(' | ')")
    check("[15] a device cut by its own limit: LIMIT REACHED and its return day, on its own page", "LIMIT REACHED" in dead
          and "This device's data limit is used up" in dead and "12/1/2027" in dead, dead)
    tab.close()
    os.unlink(os.path.join(D, "subs", "usage.json"))
    # [18] the visitor picks the app (1.8.12 item 24; operator, 2026-11-25): the badge opens the list of the apps this OS can use
    #      for the connection; a pick lives on the device per server type × OS and the link / download follow it
    serve["turn_client_default"] = {}
    J("subs/serve.json", serve)
    time.sleep(3.2)                                     # swg-sub's read cache (_READ_TTL, 3 s)
    def sheet(tab, role):   # open the app list of the first Turn cell whose server chip says `role`: [(row text, chosen)]
        return tab.ev(r"""(() => {
          const pg = [...document.querySelectorAll('section.ppage')].find(p => p.getAttribute('data-mode') === 'turn');
          if (!pg) return 'no page';
          const cells = [...pg.querySelectorAll('.scell')];
          const i = cells.findIndex(c => ((c.querySelector('.scell-role-if') || {}).textContent || '') === %s);
          if (i < 0) return 'no cell';
          pg._seek(i, null);
          const t = cells[i].querySelector('.scell-tag-pick'); if (!t) return 'no chip';
          t.click();
          return [...document.querySelectorAll('.ap-row')].map(r => [r.innerText.replace(/\s+/g, ' ').trim(), r.classList.contains('on')]);
        })()""" % json.dumps(role))
    def pick(tab, name):    # tap the list row of the app `name`
        ok = tab.ev("(() => { const r = [...document.querySelectorAll('.ap-row')].find(r => r.querySelector('.cp-name').textContent === %s);"
                    " if (!r) return false; r.click(); return true; })()" % json.dumps(name))
        time.sleep(1.2)                                 # the page rebuilds (render is async)
        return ok
    def stored(tab, scope, os_="android"):
        return tab.ev("localStorage.getItem(%s)" % json.dumps("swgsub-app:%s:%s" % (scope, os_)))
    def cells_now(tab):
        return [{"role": c["role"], "app": c["app"], "getapp": c["getapp"]} for c in turn_cells(tab.ev(READ))]
    ROLES = lambda cs: [c["role"] for c in cs]
    CLI = "Runs from the command line"
    tab, r0 = render("u1", "android", "en", phone=True)
    fresh = turn_cells(r0)
    check("[18] Android: the badges read '<app> by <author>', a chip where there is a choice",
          [(c["role"], c["app"], c["chip"]) for c in fresh if c["role"] in ("CSQTT 2.1", "WDTT", "hackdiaz")]
          == [("CSQTT 2.1", "CSQTT by amurcanov", True), ("WDTT", "WDTT by amurcanov", True), ("hackdiaz", "FreeTurn by hackdiaz", True),
              ("hackdiaz", "FreeTurn by hackdiaz", True)], [(c["role"], c["app"], c["chip"]) for c in fresh])
    hdp = sorted(re.sub(r".*:(\d+)$", r"\1", c["tag"] or "") for c in fresh if c["role"] == "hackdiaz")
    check("[18] the two hackdiaz relays (before awg0 and before wg0) keep their ports after the badge, so their cards differ (review F2)",
          hdp == ["56100", "56101"], [c["tag"] for c in fresh if c["role"] == "hackdiaz"])
    rows = sheet(tab, "WDTT")
    check("[18] the WDTT list: the operator's default first, chosen and Recommended, then the other apps with their authors",
          isinstance(rows, list) and rows[0] == ["WDTT by amurcanov Paste the link in the app Recommended", True]
          and ["MCRF by vnenapravo7-source Opens with one tap", False] in rows and ["RawlineMobile by ttrroyy Opens with one tap", False] in rows, rows)
    rows_hd = sheet(tab, "hackdiaz")
    check("[18] Android: hackdiaz's list leaves out the command-line client (a phone runs it in Termux only)",
          isinstance(rows_hd, list) and [r[0] for r in rows_hd] == ["FreeTurn by hackdiaz Opens with one tap Recommended", "RawlineMobile by ttrroyy Opens with one tap"],
          rows_hd)
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
    sheet(tab, "WDTT")
    pick(tab, "MCRF")
    after = cells_now(tab)
    wd = [c for c in after if c["role"] == "WDTT"]
    check("[18] a pick: the WDTT card hands out MCRF — its badge and its download — and the device keeps it for amurcanov's servers",
          len(wd) == 1 and wd[0]["app"] == "MCRF by vnenapravo7-source" and "MCRF" in (wd[0]["getapp"] or "") and stored(tab, "amurcanov") == "mcrf",
          (wd, stored(tab, "amurcanov")))
    toast = tab.ev("(document.querySelector('.ap-toast') || {}).innerText || ''")
    check("[18] …and offers MCRF where it also works and the visitor kept the default (the CSQTT 2.1 server, the AmneziaWG and WireGuard cards)",
          toast.replace("\n", " ").startswith("MCRF also works for 3 more connections"), toast)
    tab.ev("(() => { const b = document.querySelector('.ap-toast-b'); if (b) b.click(); return !!b; })()"); time.sleep(1.2)
    after = cells_now(tab)
    check("[18] 'Use it there too' gives the CSQTT 2.1 server MCRF as well, and the AmneziaWG and WireGuard cards",
          stored(tab, "csqtt") == "mcrf" and [c["app"] for c in after if c["role"] == "CSQTT 2.1"] == ["MCRF by vnenapravo7-source"]
          and stored(tab, "awg") == "mcrf" and stored(tab, "wg") == "mcrf",
          (stored(tab, "csqtt"), stored(tab, "awg"), stored(tab, "wg"), [(c["role"], c["app"]) for c in after]))
    sheet(tab, "WDTT")
    pick(tab, "WDTT")
    check("[18] picking the default again clears the pick", stored(tab, "amurcanov") is None
          and [c["app"] for c in cells_now(tab) if c["role"] == "WDTT"] == ["WDTT by amurcanov"], stored(tab, "amurcanov"))
    # an offer stays while another list is only opened and closed — under that list while it is open (review F7) — and goes
    # with the next pick, which it would otherwise write over (review F3)
    sheet(tab, "WDTT"); pick(tab, "RawlineMobile")
    t1 = tab.ev("!!document.querySelector('.ap-toast')")
    sheet(tab, "hackdiaz")
    under = tab.ev("(() => { const t = document.querySelector('.ap-toast'); if (!t) return null; const b = t.getBoundingClientRect();"
                   " const was = t.inert; t.inert = false;"   # inert is not hit-tested: lifted to read the stacking alone
                   " const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); t.inert = was; return !!e && !t.contains(e); })()")
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true"); time.sleep(0.4)
    t2 = tab.ev("!!document.querySelector('.ap-toast')")
    check("[18] an offer stays while another list only opens and closes, under that list while it is open (review F7)",
          (t1, under, t2) == (True, True, True), (t1, under, t2))
    sheet(tab, "WDTT"); pick(tab, "WDTT")
    check("[18] …and the next pick drops it (it would write over that pick; review F3)",
          tab.ev("!!document.querySelector('.ap-toast')") is False and stored(tab, "amurcanov") is None, stored(tab, "amurcanov"))
    tab.close()
    # two cards that would read alike keep their port only where it tells them apart (review F5): Finn's Primary / Backup
    # WDTT servers share the default port, so neither card carries it; Gina's are on two ports, so both do — and where the
    # app repeats the type ("WDTT"), the list row keeps the port after the app, not "WDTT :56000 · WDTT" (review F6)
    tab, rf = render("u6", "android", "en", phone=True)
    ft = [c["tag"] for c in turn_cells(rf) if c["role"] == "WDTT"]
    check("[18] a Primary / Backup pair on one port: two WDTT cards, no port on either (the role chip tells them apart)",
          len(ft) == 2 and not any(re.search(r":\d+", x or "") for x in ft), ft)
    tab.close()
    tab, rg = render("u7", "android", "en", size=DESK_COL)
    gt = sorted((c["tag"] or "").replace(" ", "") for c in turn_cells(rg) if c["role"] == "WDTT")
    tab.ev("(() => { const b = [...document.querySelectorAll('[data-pick]')].find(x => x.offsetParent); if (b) b.click(); return !!b; })()"); time.sleep(0.6)
    gr = tab.ev(r"[...document.querySelectorAll('.cp-row')].map(r => r.innerText.replace(/\s+/g, ' ').trim())")
    check("[18] two ports: each card carries its own, and the list row (no author there) reads 'WDTT :<port>', never 'WDTT :<port> · WDTT'",
          gt == ["WDTTbyamurcanov:56000", "WDTTbyamurcanov:56010"] and isinstance(gr, list)
          and sorted(re.sub(r"\s*:", ":", r) for r in gr if r.startswith("WDTT")) == ["WDTT:56000 PRIMARY", "WDTT:56010 BACKUP"], (gt, gr))
    tab.close()
    # a pick never moves a card: the turn proxies keep the operator's ranking (a friendly app picked for hackdiaz would rank it
    # after the native apps of cacggghp's proxy)
    tab, r1 = render("u1", "android", "en", phone=True, ls={"swgsub-app:samosvalishe:android": "rawline"})
    c1 = turn_cells(r1)
    check("[18] a pick leaves the cards in place: RawlineMobile on both hackdiaz cards, the order as without it",
          ROLES(c1) == ROLES(fresh) and [c["app"] for c in c1 if c["role"] == "hackdiaz"] == ["RawlineMobile by ttrroyy"] * 2,
          (ROLES(fresh), [(c["role"], c["app"]) for c in c1]))
    tab.close()
    # a pick the list no longer holds (an app retired, a line switched) falls back to the default, silently, and is kept
    tab, r2 = render("u1", "android", "en", phone=True, ls={"swgsub-app:amurcanov:android": "xxcipher"})
    check("[18] a stale pick: the WDTT card shows the default app, and the pick stays on the device",
          [c["app"] for c in turn_cells(r2) if c["role"] == "WDTT"] == ["WDTT by amurcanov"] and stored(tab, "amurcanov") == "xxcipher",
          [(c["role"], c["app"]) for c in turn_cells(r2)])
    tab.close()
    # the desktop keeps the command-line client in the list; a pick there keeps the tapped badge where it was on the screen
    tab, _r = render("u1", "linux", "en", size=DESK_COL)
    rows_l = sheet(tab, "hackdiaz")
    check("[18] Linux: hackdiaz's list keeps the command-line client", isinstance(rows_l, list) and any(CLI in r[0] for r in rows_l), rows_l)
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
    FIND = "[...document.querySelectorAll('.scell-tag-pick')].find(x => (x.closest('.scell').querySelector('.scell-role-if') || {}).textContent === 'WDTT')"
    tab.ev("(() => { const t = %s; window.scrollBy(0, t.getBoundingClientRect().top - 430); return 1; })()" % FIND); time.sleep(0.5)
    top0 = tab.ev("Math.round((%s).getBoundingClientRect().top)" % FIND)
    tab.ev("(%s).click(), 1" % FIND); time.sleep(0.4)
    names = tab.ev("[...document.querySelectorAll('.ap-row .cp-name')].map(n => n.textContent)")
    alt = next((n for n in names[1:] if n != "WDTT"), None) if isinstance(names, list) else None
    pick(tab, alt)
    top1 = tab.ev("Math.round((%s).getBoundingClientRect().top)" % FIND)
    check("[18] desktop: a pick rebuilds the page and the tapped badge stays where it was (no jump)",
          alt and top0 is not None and top1 is not None and abs(top1 - top0) <= 1, (alt, top0, top1))
    # the connection list copies the badge: "<type or server author> · <app>", text there — no button inside its row button
    tab.ev("(() => { const b = [...document.querySelectorAll('[data-pick]')].find(x => x.offsetParent); if (b) b.click(); return !!b; })()"); time.sleep(0.6)
    tab.ev("(() => { const r = [...document.querySelectorAll('.cp-row')].find(r => (r.querySelector('.cp-name') || {}).textContent === 'laptop');"
           " if (r) r.click(); return !!r; })()"); time.sleep(0.4)   # Anna has more than one device: hers first, then its connections
    cp = tab.ev(r"""(() => ({ rows: [...document.querySelectorAll('.cp-row')].map(r => r.textContent.replace(/\s+/g, ' ').trim()),
                                nested: document.querySelectorAll('.cp-row [role=button], .cp-row [tabindex], .cp-row .scell-tag-pick').length }))()""")
    check("[18] the connection list names a connection '<type or server author> · <app>' and holds no button in its rows",
          isinstance(cp, dict) and cp["nested"] == 0 and any(r.startswith("WDTT · " + alt) for r in cp["rows"])
          and any(re.match(r"hackdiaz( :\d+)? · Rawline", r) for r in cp["rows"]), cp)
    tab.close()
    # once per device, the first chip in full view rolls through the other apps and lands back on its own; reduced motion: a hint
    tab, _r = render("u1", "android", "en", phone=True, ls={"swgsub-apphint": None})
    tab.ev("(() => { document.querySelector('.scell-tag-pick .scell-appchip').scrollIntoView({block: 'center'}); return 1; })()")
    seen, lbl0, deadline = set(), None, time.time() + 6
    while time.time() < deadline:
        st = tab.ev("(() => { const c = document.querySelector('.scell-tag-pick .scell-appchip'); return [!!c.querySelector('.ap-roll'),"
                    " c.textContent, localStorage.getItem('swgsub-apphint')]; })()")
        lbl0 = lbl0 or st[1]
        if st[0]:
            seen.add(st[1])
        if seen and not st[0] and st[2] == "1":
            break
        time.sleep(0.1)
    end = tab.ev("document.querySelector('.scell-tag-pick .scell-appchip').textContent")
    check("[18] the one-time roll plays once the chip is in view, through the other apps, back to its own label",
          bool(seen) and end == lbl0 and tab.ev("localStorage.getItem('swgsub-apphint')") == "1", (seen, lbl0, end))
    tab.close()
    tab = Tab(br)
    tab.br.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, session=tab.s)
    tab.goto(ORIGIN + "/healthz")
    for _ in range(50):                                 # the page's origin first, or its localStorage is about:blank's
        if tab.ev("location.href").startswith(ORIGIN):
            break
        time.sleep(0.1)
    tab.ev("Object.keys(localStorage).filter(k => k.startsWith('swgsub-app:')).forEach(k => localStorage.removeItem(k)); "
           "localStorage.removeItem('swgsub-apphint'); localStorage.setItem('swgsub-os', 'android'); localStorage.setItem('swgsub-lang', 'en'); true")
    tab.goto(ORIGIN + "/" + links["u1"]); time.sleep(2.5)
    tab.ev("(() => { document.querySelector('.scell-tag-pick .scell-appchip').scrollIntoView({block: 'center'}); return 1; })()")
    time.sleep(1.5)
    hint = tab.ev("(() => [(document.querySelector('.ap-hint') || {}).textContent || '', document.querySelectorAll('.ap-roll').length])()")
    why = tab.ev(r"""(() => { const c = document.querySelector('.scell-tag-pick .scell-appchip'), r = c && c.getBoundingClientRect();
      return {vp: [innerWidth, innerHeight], chip: r && [r.left, r.top, r.right, r.bottom].map(Math.round), seen: localStorage.getItem('swgsub-apphint'),
              reduce: matchMedia('(prefers-reduced-motion: reduce)').matches, chips: document.querySelectorAll('.scell-tag-pick').length}; })()""")
    check("[18] reduced motion: no roll, a one-line hint under the chip", hint == ["Tap to choose another app", 0], (hint, why))
    tab.close()
    # [19] the WG / AWG cards pick their app too (1.8.12 item 24, card B): the badge keeps the protocol in front of the app,
    #      the list is every WG_ORDER app this OS has a link for, and the pick drives the download row and Start
    def wsheet(tab, mode):  # open the app list of the first `mode` card: [(row text, chosen)]
        return tab.ev(r"""(() => {
          const pg = [...document.querySelectorAll('section.ppage')].find(p => p.getAttribute('data-mode') === %s);
          if (!pg) return 'no page';
          pg._seek(0, null);
          const t = pg.querySelector('.scell-tag-pick'); if (!t) return 'no chip';
          t.click();
          return [...document.querySelectorAll('.ap-row')].map(r => [r.innerText.replace(/\s+/g, ' ').trim(), r.classList.contains('on')]);
        })()""" % json.dumps(mode))
    def wcell(r, mode):     # the first `mode` card: (badge, getapp row, its note)
        cs = [c for p in (r or {}).get("pages", []) if p["mode"] == mode for c in p["cells"]]
        return cs[0] if cs else {}
    def wnote(tab, mode):
        return tab.ev("(() => { const pg = document.querySelector('section.ppage[data-mode=%s]'); const n = pg && pg.querySelector('.scell-appnote');"
                      " return n ? n.textContent : null; })()" % mode)
    def pb(b):              # protobuf wire → {field: int | bytes}
        out, i = {}, 0
        def vint():
            nonlocal i
            r = s_ = 0
            while True:
                x = b[i]; i += 1; r |= (x & 127) << s_; s_ += 7
                if not x & 128:
                    return r
        while i < len(b):
            k = vint(); f, wt = k >> 3, k & 7
            if wt == 0:
                out[f] = vint()
            else:
                n = vint(); out[f] = b[i:i + n]; i += n
        return out
    def wingsv(u):          # wingsv:// → its Config's fields, or None
        if not u.startswith("wingsv://"):
            return None
        raw = base64.urlsafe_b64decode(u[9:] + "=" * (-len(u[9:]) % 4))
        return pb(zlib.decompress(raw[1:])) if raw[:1] == b"\x12" else None
    def rawline(u):
        return base64.urlsafe_b64decode(u[14:] + "=" * (-len(u[14:]) % 4)).decode() if u.startswith("rawline://add/") else None
    tab, r0 = render("u1", "android", "en", phone=True)
    a0, w0 = wcell(r0, "awg"), wcell(r0, "wg")
    check("[19] Android: the AWG and WG badges read '<protocol> · AmneziaVPN', a chip on each",
          (a0.get("tag"), a0.get("chip"), w0.get("tag"), w0.get("chip")) == ("AmneziaWG · AmneziaVPN", True, "WireGuard · AmneziaVPN", True), (a0, w0))
    rows = wsheet(tab, "awg")
    check("[19] Android, AmneziaWG: AmneziaVPN first and Recommended, then AmneziaWG, MCRF, RawlineMobile and WINGS V, each with how it imports",
          isinstance(rows, list) and [x[0] for x in rows] == ["AmneziaVPN Opens with one tap Recommended", "AmneziaWG Import the config file in the app",
                                                             "MCRF by vnenapravo7-source Import the config file in the app",
                                                             "RawlineMobile by ttrroyy Opens with one tap", "WINGS V by WINGS-N Opens with one tap"], rows)
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
    rows = wsheet(tab, "wg")
    check("[19] …and the WireGuard card adds WireGuard after AmneziaWG", isinstance(rows, list)
          and [x[0].split(" ")[0] for x in rows] == ["AmneziaVPN", "AmneziaWG", "WireGuard", "MCRF", "RawlineMobile", "WINGS"], rows)
    tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
    # a pick: RawlineMobile on the AWG card — its badge, its own download row, Start = rawline://add/ around the plain .conf
    wsheet(tab, "awg"); pick(tab, "RawlineMobile")
    r1 = tab.ev(READ); a1 = wcell(r1, "awg")
    check("[19] a pick on the AWG card: 'AmneziaWG · RawlineMobile by ttrroyy', RawlineMobile's own download row, kept for every AWG card",
          a1.get("tag") == "AmneziaWG · RawlineMobile by ttrroyy" and (a1.get("getapp") or "").startswith("Get RawlineMobile by ttrroyy")
          and stored(tab, "awg") == "rawline" and wcell(r1, "wg").get("tag") == "WireGuard · AmneziaVPN", (a1, stored(tab, "awg")))
    toast = tab.ev("(document.querySelector('.ap-toast') || {}).innerText || ''")
    check("[19] …and offers RawlineMobile where it also works (the WireGuard card among them)", toast.replace("\n", " ").startswith("RawlineMobile also works for"), toast)
    tab.ev("(() => { const t = document.querySelector('.ap-toast'); if (t) t.remove(); return 1; })()")
    # the enlarged QR names the app it is scanned with, as a turn card's does (review item24-b F5)
    cap = tab.ev(r"""(() => { %s
      const box = cells[i].querySelector('.qrbox'); if (!box) return 'no qr'; box.click();
      const c = document.querySelector('.qz-cap'); const t = c ? c.textContent : null;
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); return t; })()""" % seek_js("awg", "AmneziaWG"))
    check("[19] the enlarged QR of the AWG card reads 'laptop · RawlineMobile', the app picked", cap == "laptop · RawlineMobile", cap)
    _res, _clip, _steps, navs = start_on(tab, "awg", "AmneziaWG")
    conf_r = next((rawline(u) for u in navs if rawline(u)), None)
    check("[19] Android: Start opens RawlineMobile with rawline://add/ around the plain .conf (AWG keys in it)",
          bool(conf_r) and conf_r.startswith("[Interface]") and "Jc = 4" in conf_r and "Endpoint = 203.0.113.7:51820" in conf_r, navs)
    tab.close()
    # MCRF on an AWG card: its download bubble says what MCRF needs on Android, not the turn cards' engine download (F4)
    tab, _r = render("u1", "android", "en", phone=True, ls={"swgsub-app:awg:android": "mcrf"})
    notes = tab.ev(r"""(() => { %s
      const btn = cells[i].querySelector('.scell-getapp-btn'); if (!btn) return 'no button'; btn.click();
      const b = document.querySelector('.dl-bubble'); if (!b) return 'no bubble';
      return [...b.querySelectorAll('.dl-bubble-ver')].map(x => x.textContent); })()""" % seek_js("awg", "AmneziaWG"))
    check("[19] MCRF's bubble on an AWG card: 'Needs Android 10 or newer.', no word of the CSQTT / WDTT engine",
          isinstance(notes, list) and "Needs Android 10 or newer." in notes and not any("11 MB" in x for x in notes), notes)
    tab.close()
    # …but only an app that scans it: MCRF on Windows imports a pasted link, so its AWG card's QR keeps the protocol's name
    # (item24-b verify F7)
    tab, _r = render("u1", "windows", "en", size=DESK_COL, ls={"swgsub-app:awg:windows": "mcrf"})
    capw = tab.ev(r"""(() => { %s
      const box = cells[i].querySelector('.qrbox'); if (!box) return 'no qr'; box.click();
      const c = document.querySelector('.qz-cap'); const t = c ? c.textContent : null;
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); return t; })()""" % seek_js("awg", "AmneziaWG"))
    check("[19] Windows, MCRF on the AWG card: the enlarged QR reads 'laptop · AmneziaWG' — MCRF there cannot scan it", capw == "laptop · AmneziaWG", capw)
    tab.close()
    # WINGS V on the AWG card: its own wingsv:// link — type AMNEZIAWG, backend AMNEZIAWG_TL, the whole .conf — and its note
    tab, r2 = render("u1", "android", "en", phone=True, ls={"swgsub-app:awg:android": "wingsv"})
    check("[19] WINGS V on the AWG card: its badge and, under the download row, the old-profile note",
          wcell(r2, "awg").get("tag") == "AmneziaWG · WINGS V by WINGS-N" and (wnote(tab, "awg") or "").startswith("Imported this server into WINGS V before?"),
          (wcell(r2, "awg").get("tag"), wnote(tab, "awg")))
    check("[19] …the note is WINGS V's alone (the WireGuard card, on AmneziaVPN, has none)", wnote(tab, "wg") is None, wnote(tab, "wg"))
    _res, _clip, _steps, navs = start_on(tab, "awg", "AmneziaWG")
    cfg = next((wingsv(u) for u in navs if wingsv(u)), None)
    awgm = pb(cfg[7]) if cfg and isinstance(cfg.get(7), bytes) else {}
    check("[19] Android: Start opens WINGS V with its AmneziaWG profile link — ver 1, type 3, backend 8, the whole .conf, titled",
          bool(cfg) and (cfg.get(1), cfg.get(2), cfg.get(5), 3 in cfg, 4 in cfg) == (1, 3, 8, False, False)
          and awgm.get(1, b"").decode().startswith("[Interface]") and b"Jc = 4" in awgm.get(1, b"") and awgm.get(2, b"").decode().startswith("laptop"),
          (navs, cfg and sorted(cfg)))
    tab.close()
    # WireGuard on the WG card: the protocol collapses into the app, and Start, with no link of the app's own, saves the .conf
    # and shows its import steps
    tab, r3 = render("u1", "android", "en", phone=True, ls={"swgsub-app:wg:android": "wireguard", "swgsub-app:awg:android": "wireguard"})
    check("[19] WireGuard picked on the WG card: the badge is the app alone ('WireGuard', not 'WireGuard · WireGuard')",
          wcell(r3, "wg").get("tag") == "WireGuard", wcell(r3, "wg"))
    check("[19] a pick the list doesn't hold (WireGuard on an AmneziaWG card) falls back to AmneziaVPN", wcell(r3, "awg").get("tag") == "AmneziaWG · AmneziaVPN", wcell(r3, "awg"))
    _res, _clip, steps, navs = start_on(tab, "wg", "WireGuard")
    done = tab.ev("(document.querySelector('.ph-overlay .ph-copied') || {}).textContent || ''")
    check("[19] Start with WireGuard: 'Config file saved' and its import steps, no scheme fired",
          done == "Config file saved" and len(steps) == 3 and steps[0] == "1. Open WireGuard" and steps[2].endswith(".conf in Downloads, then connect")
          and not [u for u in navs if "://" in u and not u.startswith("http")], (done, steps, navs))
    tab.close()
    # the OS gate: Linux lists only what it has a link for — no AmneziaWG (no Linux app), no MCRF, no WINGS V
    tab, _r = render("u1", "linux", "en", size=DESK_COL)
    rows = wsheet(tab, "awg")
    check("[19] Linux, AmneziaWG: AmneziaVPN and Rawline only", isinstance(rows, list) and [x[0] for x in rows]
          == ["AmneziaVPN Paste the link in the app Recommended", "Rawline by ttrroyy Opens with one tap"], rows)
    tab.close()
    # Windows: Rawline on the WG card opens with rawline://add/ around a JSON list holding the .conf (its desktop parser)
    tab, _r = render("u1", "windows", "en", size=DESK_COL, ls={"swgsub-app:wg:windows": "rawline", "swgsub-hasapp-rawline": "1"})
    _res, _clip, _steps, navs = start_on(tab, "wg", "WireGuard")
    doc = next((rawline(u) for u in navs if rawline(u)), None)
    try:
        lst = json.loads(doc) if doc else None
    except ValueError:
        lst = None
    check("[19] Windows: Start opens Rawline with rawline://add/ around a JSON list of the .conf",
          isinstance(lst, list) and len(lst) == 1 and lst[0].startswith("[Interface]") and "Endpoint = 203.0.113.7:51830" in lst[0], (navs, doc and doc[:80]))
    # the connection list names a WG / AWG connection '<protocol> · <app>' too
    tab.ev("(() => { const b = [...document.querySelectorAll('[data-pick]')].find(x => x.offsetParent); if (b) b.click(); return !!b; })()"); time.sleep(0.6)
    tab.ev("(() => { const r = [...document.querySelectorAll('.cp-row')].find(r => (r.querySelector('.cp-name') || {}).textContent === 'laptop');"
           " if (r) r.click(); return !!r; })()"); time.sleep(0.4)
    cp = tab.ev(r"""[...document.querySelectorAll('.cp-row')].map(r => r.textContent.replace(/\s+/g, ' ').trim())""")
    check("[19] the connection list: 'AmneziaWG · AmneziaVPN', 'WireGuard · Rawline by ttrroyy'",
          isinstance(cp, list) and any(x.startswith("AmneziaWG · AmneziaVPN") for x in cp) and any(x.startswith("WireGuard · Rawline by ttrroyy") for x in cp), cp)
    tab.ev("localStorage.removeItem('swgsub-hasapp-rawline'); true")
    tab.close()

    # [20] PC and tablet layouts (operator, 2026-11-26): a phone keeps its pager — no layout class, no list, every page in the
    #      flow; a PC (≥1024 × 600) lists the devices and their connections beside ONE card — QR left; the app, Start with what
    #      it does, the actions by name and the QR's text right, Start above the fold — and Download saves that text, not a
    #      picture of the QR; a tablet held upright (≥640 × 600) puts the devices as tabs above the card; every full-screen
    #      pop-up is modal (the page behind it inert, the focus inside, then back)
    LAY = r"""(() => { const vis = e => !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0;
      const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
      const pg = document.querySelector('.ppage.cur'), cell = pg && pg.querySelector('.scell.cur');
      const st = pg && pg.querySelector('.pbtn-start'), lbl = pg && pg.querySelector('.pbtn-start-lbl'), side = cell && cell.querySelector('.scell-side .cfgtext');
      return { cls: ['lay-wide', 'lay-col'].filter(c => document.body.classList.contains(c)), nav: !!document.querySelector('.wnav'),
               rows: [...document.querySelectorAll('.wnav-row')].filter(vis).map(txt), on: [...document.querySelectorAll('.wnav-row.on')].map(txt),
               tabs: [...document.querySelectorAll('.wnav-dev')].filter(vis).map(txt),
               pages: [...document.querySelectorAll('section.ppage')].filter(vis).map(p => p.getAttribute('data-mode')),
               stages: [...document.querySelectorAll('.scell-stage')].filter(vis).length,
               badge: cell && cell.querySelector('.scell-tag') ? txt(cell.querySelector('.scell-tag')) : null,
               lbl: vis(lbl) ? txt(lbl) : null, start: st ? st.title : null, startBottom: vis(st) ? Math.round(st.getBoundingClientRect().bottom) : null,
               vh: innerHeight, side: vis(side) ? side.textContent : null, dl: pg && (pg.querySelector('.pbar .pbtn.ico:nth-child(2)') || {}).title,
               conn: [...document.querySelectorAll('.pbtn-conn, .pswitch-head, .modebar')].filter(vis).length,
               orbs: [...document.querySelectorAll('.pbtn-start radialGradient')].map(g => g.id) }; })()"""
    def lay_click(tab, sel, has):   # click the visible `sel` whose text has `has`
        ok = tab.ev("(() => { const x = [...document.querySelectorAll(%s)].find(e => e.getClientRects().length && e.textContent.replace(/\\s+/g, ' ').includes(%s));"
                    " if (x) x.click(); return !!x; })()" % (json.dumps(sel), json.dumps(has)))
        time.sleep(0.5)
        return ok
    MODAL = r"""(async () => { const chip = document.querySelector('.ppage.cur .scell.cur .scell-tag-pick') || [...document.querySelectorAll('.scell-tag-pick')].find(c => c.getClientRects().length);
      if (!chip) return 'no chip';
      chip.focus(); chip.click(); await new Promise(r => setTimeout(r, 300));
      const ov = document.querySelector('.cp-overlay'), app = document.getElementById('app');
      const open = { role: ov && ov.getAttribute('role'), modal: ov && ov.getAttribute('aria-modal'), named: !!(ov && (ov.getAttribute('aria-label') || (document.getElementById(ov.getAttribute('aria-labelledby') || '') || {}).textContent)),
                     inert: app.inert, focus: !!(ov && ov.contains(document.activeElement)) };
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); await new Promise(r => setTimeout(r, 400));
      return { open: open, closed: { gone: !document.querySelector('.cp-overlay'), inert: app.inert, back: document.activeElement === chip } }; })()"""
    MODAL_OK = {"open": {"role": "dialog", "modal": "true", "named": True, "inert": True, "focus": True}, "closed": {"gone": True, "inert": False, "back": True}}
    # a phone: untouched — no layout class, no list, the pages in the pager's flow, Start alone
    tab, _r = render("u1", "android", "en", phone=True)
    lp = tab.ev(LAY)
    check("[20] a phone keeps its layout: no layout class, no list, every page in the flow, Start without a label",
          lp["cls"] == [] and not lp["nav"] and len(lp["pages"]) > 1 and lp["lbl"] is None and lp["side"] is None, lp)
    check("[20] …and its app list is modal too: a dialog with the focus, the page behind inert, the focus back on close", tab.ev(MODAL) == MODAL_OK, tab.ev(MODAL))
    # the Connections pop-up's name, as the accessibility tree computes it, follows the level: the devices, then the one opened (verify F8)
    def ax_dialogs(tab):
        tab.br.send("Accessibility.enable", session=tab.s)
        return [(n.get("name") or {}).get("value") for n in tab.br.send("Accessibility.getFullAXTree", session=tab.s).get("nodes", [])
                if not n.get("ignored") and (n.get("role") or {}).get("value") == "dialog"]
    lay_click(tab, ".pbtn-conn", "")
    d1 = ax_dialogs(tab)
    lay_click(tab, ".cp-overlay .cp-row", "laptop")
    d2 = ax_dialogs(tab)
    check("[20] the Connections pop-up is named by its level: 'Your devices', then the device opened in it (verify F8)",
          d1 == ["Your devices"] and d2 == ["laptop"], (d1, d2))
    tab.close()
    # a toast is read out from one status region, in the page before the first toast and live over a pop-up (verify F10)
    tab, _r = render("u1", "android", "en", phone=True)
    lv0 = tab.ev("(() => { const r = document.querySelectorAll('.sub-live[role=status]'); return [r.length, r.length ? r[0].textContent : null]; })()")
    start_on(tab, "turn", "WDTT")
    lv1 = tab.ev(r"""(async () => { const a = [...document.querySelectorAll('.ph-overlay .ph-dl')].find(x => x.textContent === 'Copy the link again');
      if (!a) return 'no copy row'; a.click(); await new Promise(r => setTimeout(r, 400));
      const r = document.querySelector('.sub-live'), t = document.querySelector('.sub-toast');
      return [r && r.textContent, r && r.inert, t && t.textContent, t && t.getAttribute('role')]; })()""")
    check("[20] a toast is read out from a status region in the page before it, live over a pop-up (verify F10)",
          lv0 == [1, ""] and lv1 == ["Connection link copied", False, "Connection link copied", None], (lv0, lv1))
    tab.close()
    # a phone on its side keeps the scrolling column
    tab, _r = render("u1", "android", "en", size=(844, 390, True))
    check("[20] a phone on its side keeps the scrolling column (no layout class)", tab.ev(LAY)["cls"] == [], tab.ev(LAY)["cls"])
    tab.close()
    # a PC: the list beside one card
    tab, _r = render("u1", "android", "en", desktop=True)
    tab.ev("window.__dl = []; HTMLAnchorElement.prototype.click = function () { if (this.download) window.__dl.push(this.download); }; true")
    lw = tab.ev(LAY)
    check("[20] PC: the devices' connections listed beside one card — one page, one card, the first row marked, no Connections button or tabs",
          lw["cls"] == ["lay-wide"] and lw["nav"] and len(lw["rows"]) >= 4 and lw["on"] == lw["rows"][:1] and lw["pages"] == ["wg"]
          and lw["stages"] == 1 and lw["conn"] == 0, lw)
    check("[20] PC: Start says what it does beside it and sits above the fold; the QR's text sits beside the QR",
          bool(lw["lbl"]) and lw["lbl"] == lw["start"] and lw["startBottom"] is not None and lw["startBottom"] <= lw["vh"]
          and (lw["side"] or "").startswith("[Interface]"), lw)
    tab.ev("(() => { const b = document.querySelector('.ppage.cur .pbar .pbtn.ico:nth-child(2)'); if (b) b.click(); return !!b; })()"); time.sleep(0.3)
    dl = tab.ev("window.__dl")
    check("[20] PC: Download saves the config beside the QR, not a picture of it — and says so",
          isinstance(dl, list) and len(dl) == 1 and dl[0].endswith(".conf") and lw["dl"] == "Download .conf", (dl, lw["dl"]))
    zq = tab.ev(r"""(async () => { const box = document.querySelector('.ppage.cur .scell.cur .qrbox'); if (!box) return 'no qr'; box.click();
      await new Promise(r => setTimeout(r, 300)); const ov = document.querySelector('.qz-overlay'), cap = ov && ov.querySelector('.qz-cap');
      const r = { named: !!ov && !!cap && (ov.getAttribute('aria-label') === cap.textContent || (!!cap.id && ov.getAttribute('aria-labelledby') === cap.id)), focus: !!ov && document.activeElement === ov };
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); await new Promise(r => setTimeout(r, 300));
      r.gone = !document.querySelector('.qz-overlay'); return r; })()""")
    check("[20] PC: the enlarged QR is a dialog named by its caption that takes the focus itself (it holds no control) (review F5)",
          zq == {"named": True, "focus": True, "gone": True}, zq)
    lay_click(tab, ".wnav-row", "WDTT")
    lw2 = tab.ev(LAY)
    check("[20] PC: a row of the list shows its card (the WDTT one) and is marked",
          lw2["pages"] == ["turn"] and "WDTT" in (lw2["badge"] or "") and len(lw2["on"]) == 1 and "WDTT" in lw2["on"][0] and lw2["stages"] == 1, lw2)
    check("[20] PC: every Start orb paints from a gradient of its own (a hidden page's id would leave it blank)",
          len(lw2["orbs"]) > 1 and len(set(lw2["orbs"])) == len(lw2["orbs"]), lw2["orbs"])
    check("[20] PC: the app list is modal — a named dialog with the focus, the page behind inert, the focus back on close", tab.ev(MODAL) == MODAL_OK, tab.ev(MODAL))
    who = tab.ev("[(document.querySelector('.bar .who') || {}).textContent, !!(document.querySelector('.bar .who') || {getClientRects: () => []}).getClientRects().length,"
                 " (document.querySelector('.wnav-who') || {}).textContent]")
    check("[20] PC: the name shows once — in the list, not the header", who == ["Anna", False, "Anna"], who)
    lay_click(tab, ".wnav-row", "MYSOREZ")
    lm = tab.ev(LAY)
    check("[20] PC: a VKTGZ paste token is saved by 'Download', not 'Download link' (it is no link) (review F4)",
          "MYSOREZ" in (lm["badge"] or "") and lm["dl"] == "Download", (lm["badge"], lm["dl"]))
    lay_click(tab, ".wnav-row", "Available networks")
    check("[20] PC: the networks row shows the networks page", tab.ev(LAY)["pages"] == ["nets"], tab.ev(LAY)["pages"])
    nrows = tab.ev("getComputedStyle(document.querySelector('.ppage.cur')).gridTemplateRows.split(' ').length")
    check("[20] PC: the networks card has its three rows, no empty ones under it (review F6)", nrows == 3, nrows)
    check("[4] console clean — the PC layout", not console_errors(tab), console_errors(tab)[:3])
    tab.close()
    # a tablet held upright: the devices as tabs, then the card
    tab, _r = render("u1", "android", "en", size=(820, 1180, True))
    lc = tab.ev(LAY)
    check("[20] tablet upright: the devices as tabs above one card", lc["cls"] == ["lay-col"] and lc["tabs"] == ["laptop", "old tablet"]
          and lc["pages"] == ["wg"] and lc["stages"] == 1 and bool(lc["lbl"]) and lc["side"] is None, lc)
    lay_click(tab, ".wnav-dev", "old tablet")
    check("[20] tablet upright: a device's tab shows its page (the blocked tablet's)", tab.ev(LAY)["pages"] == ["dead"], tab.ev(LAY)["pages"])
    tab.close()
    # one device and a networks page on an upright tablet (no tabs): the networks card keeps the device's connections open
    tab, _r = render("u2", "android", "en", size=(820, 1180, True))
    lay_click(tab, ".wnav-row", "Available networks")
    back = tab.ev(LAY)
    ok = back["pages"] == ["nets"] and any("Available networks" not in r for r in back["rows"])
    if ok:
        tab.ev("(() => { const r = [...document.querySelectorAll('.wnav-row:not(.cp-nets)')].find(x => x.getClientRects().length); if (r) r.click(); return !!r; })()")
        time.sleep(0.5)
    check("[20] tablet upright, one device: from the networks card its connections stay in reach (review F1)",
          ok and tab.ev(LAY)["pages"] not in (["nets"], []), (back, tab.ev(LAY)["pages"]))
    # …and after a rebuild that lands there: the theme changed on the networks card, or the tablet turned upright on it (verify F7)
    lay_click(tab, ".wnav-row", "Available networks")
    tab.ev("document.getElementById('theme-btn').click(); true"); time.sleep(1.0)
    rb7 = tab.ev(LAY)
    tab.ev("localStorage.removeItem('swgsub-theme'); true")
    check("[20] tablet upright, one device: the theme changed on the networks card keeps its connections in reach (verify F7)",
          rb7["pages"] == ["nets"] and any("Available networks" not in r for r in rb7["rows"]), rb7)
    tab.close()
    tab, _r = render("u2", "android", "en", size=(1180, 820, True))   # the tablet on its side: the PC layout
    lay_click(tab, ".wnav-row", "Available networks")
    tab.br.send("Emulation.setDeviceMetricsOverride", {"width": 820, "height": 1180, "deviceScaleFactor": 1, "mobile": True}, session=tab.s)
    time.sleep(1.0)
    rt7 = tab.ev(LAY)
    check("[20] …and so does turning the tablet upright on the networks card (verify F7)",
          rt7["cls"] == ["lay-col"] and rt7["pages"] == ["nets"] and any("Available networks" not in r for r in rt7["rows"]), rt7)
    tab.close()
    # one config and no networks page on a PC: no list, the card alone — and the name stays in the header (review F2)
    tab, _r = render("u8", "android", "en", desktop=True)
    lh = tab.ev(LAY)
    hn = tab.ev("[(document.querySelector('.bar .who') || {}).textContent, !!(document.querySelector('.bar .who') || {getClientRects: () => []}).getClientRects().length]")
    check("[20] PC, one config: the card alone, no list, and the name in the header (review F2)",
          lh["cls"] == ["lay-wide"] and not lh["nav"] and lh["pages"] == ["wg"] and hn == ["Hana", True], (lh, hn))
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
