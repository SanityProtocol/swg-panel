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
  [B14] the app bar on a phone (q189): at 390 px it wraps — every visible header control on the screen and tappable, the bar
        adding no width (it ran to 1 257 px, so every screen scrolled sideways) — and scrolls away with the page; at 1 280 px it
        is the one sticky 56 px row it was. English and Russian. And with every header control shown (an update pill, the
        deployment badge, the vault lock, the logs button) Log out stays on the screen at 1 280 px in Russian — its parts sit closer
        together there (it ran to 1 308 px) — while English keeps its one 56 px row as it was
  [B15] the grids' traffic rail covers no row action (OE, 1.8.9): at 1 280×900 it sat over the last action of every row in its
        band (a click on Delete peer opened the rail's Custom dates); at 1 366 it never did (the control)
  [B16] the Add-node command names the panel's confirmed address (OE, 1.8.9): opened through a tunnel or another name, it was
        built from this tab's address and pointed nowhere; with no address set, this tab's own as before
  [B17] a csqtt 2.5 server's App routing exceptions (1.8.11 S7): a row per exception in order (whom, what they get), the summary
        counts them, an older node is said to need an update and an updated one is not; a row's sheet lists its person with the
        devices on this server (the routing rules' "For whom" picker, lifted) and its rule; a click edit there asks before it
        is discarded, a search typed alone does not; Own rule opens the form, Apply puts it on the row; a new exception waits
        for a person; a removed row asks before the server sheet discards it; Save sends and the panel stores the list. Rows inside the sheet at 1280 and 390 px, in
        English and Russian. SPA_SHOTS=<dir> keeps screenshots of the list, the edit and the add sheets
  [B18] a dial-in exit (1.8.11 S9, docs/LISTEN-EXIT-PLAN.md §2.4): the section reads "WARP & exits"; the row wears "Dial-in" and
        waits for the router naming its port; "Add a dial-in exit" opens a sheet asking for the server config with no "Connect
        from", Cancel and Save on one line at 390 px; the stored one's box shows ListenPort and no Endpoint; a server config
        pasted there and saved is stored as a dial-in exit. (S9b) It opens Generate first — three protocols, Cancel and
        Create on one line; Create shows the router's config once (Endpoint = the node's host and the port it got, a QR, one
        Done), and the panel's peer is the X25519 public half of the router's key; Regenerate keeps the port and address
        and shows a new config; a port change marks that row's QR button (what changed in its hover), no banner, and an
        untitled exit is named by its port. (S9c) With the store
        off the row's QR button says nothing is kept and offers Regenerate; Regenerate sits in the router config's footer beside
        Done, not in the edit sheet; with it on and a vault, Create says the config is
        kept, closes like any sheet, and the row's QR button shows the same router key again. English and Russian, 1280 and
        390 px. SPA_SHOTS keeps the shots
  [i18n] B1's words in Russian; [console] no error or exception on any view

Needs google-chrome (or $CHROME). A missing browser is a FAIL, never a skip.
A tab whose app did not boot (a module the page imports failed to fetch — seen under load, six lanes beside VM cells: "Failed
to fetch dynamically imported module peer-ui.js") is opened again, once, and says so; the browser caches a failed module, so
only a fresh tab can load it. A second failure stands.
Run: python3 tests/spa_render_selftest.py      (0 = pass)
     --flake-first-load  blocks js/peer-ui.js in the first tab only and expects GREEN, with one retry line
     --perturb-<name>  serves a copy of the SPA with one fix undone and expects RED: group-count | cap | cursor | total | flip | grow | netonline | netbubble | icons | lanwidth | phonebar | rutight | railclear | cmdhost | rqr | rkeep | rregen | rmark | rguard | rcancel | rfit | rside | rkind | rwhy | rlocked | rfwd | rlan | rrest | rinput | rstack | dintyped | dinedit | dinphone | tcplat | latbub
                       | probebtn | gwclick | pillwidth | chipsend | footsize | footwidth | arxguard | arxtyped | csqguard | arpw
"""
import base64, http.client, json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time
os.environ["SWG_NFT_CLI_ONLY"] = "1"   # the kernel is this test's model, read through run(): nftables via the CLI only

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from cdp_pipe import Browser, Tab, CHROME   # noqa: E402

SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), None)

P_AR_NONE = {"apps_mode": "all", "packages": [], "domains_mode": "direct", "domains": [], "template_domains": False, "ips_mode": "direct", "ips": []}
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
    "phonebar": ("app.css", "  .appbar{flex-wrap:wrap;height:auto;gap:8px 6px;padding:8px 14px;position:static}.brand{margin-right:auto}\n",
                 "  .appbar{gap:14px;padding:0 14px}\n"),
    "rutight": ("app.css", '@media (min-width:1280px) and (max-width:1365px){html[lang="ru"] .appbar{gap:14px}html[lang="ru"] .appbar-right,'
                           'html[lang="ru"] .updslot{gap:8px}\n  html[lang="ru"] .tabs a{padding:8px 7px}}\n', ""),
    "railclear": ("app.css", "@media (min-width:901px) and (max-width:1352px){:root:has(.trafficrail) .view{padding-right:70px}}\n", ""),
    "cmdhost": ("js/sheets-crud.js", 'const host = String(Store.panelPublicUrl || "").trim().replace(/\\/+$/, "") || `${location.origin}${BASE}`;',
                "const host = `${location.origin}${BASE}`;"),
    "footwidth": ("js/sheets-crud.js", 'width=${760} headExtra=${headExtra} subject=${{ kind: "peer", id: pid }}', 'width=${640} headExtra=${headExtra} subject=${{ kind: "peer", id: pid }}'),
    "arxguard": ("js/turn.js", 'width=${680} dirtyRef=${dirtyRef} closeRef=${closeRef} cleanRef=${cleanRef}\n    foot=${footRow({ onCancel: () => (closeRef.current ? closeRef.current() : closeModal()), onAction: apply, action: T("Apply")',
                 'width=${680}\n    foot=${footRow({ onCancel: () => (closeRef.current ? closeRef.current() : closeModal()), onAction: apply, action: T("Apply")'),
    "arxtyped": ("js/turn.js", "cell=${cell} onTyped=${typedOnly} empty=", "cell=${cell} empty="),
    "csqguard": ("js/turn.js", 'width=${720} dirtyRef=${dirtyRef} closeRef=${closeRef}\n', 'width=${720}\n'),
    "arpw": ("js/turn.js", "snap && !snap.csqtt_ar_pw ?", "snap && !snap.csqtt_arpw ?"),
    # [B18]: the dial-in sheet offers "Connect from" (a source for an exit that dials nothing), as a dial-out one does
    "dialsrc": ("js/screen-settings.js", '      ${isDialin ? null : html`<div class="field"><label>${T("Connect from")}</label>',
                '      ${false ? null : html`<div class="field"><label>${T("Connect from")}</label>'),
    # [B18]: the edit box prints a dial-in profile as a dial-out one (`Endpoint = `), as it did before 1.8.11
    "dinbox": ("js/screen-settings.js", '  const din = !!p.listen_port && !p.endpoint;', '  const din = false;'),
    # [B18] (S9c): the dial-in row has no QR button; Generate keeps nothing
    "rqr": ("js/screen-settings.js", '${exitIsDialin(stored(ex.id)) ? html`<button class=${"exg-qr"', '${false ? html`<button class=${"exg-qr"'),
    "rregen": ("js/screen-settings.js", "                     left: onRegen ? html`<button", "                     left: false ? html`<button"),
    "rmark": ("js/screen-settings.js", '(DIALIN_NOTE[ex.id] ? " chg" : "")', '("")'),
    "rguard": ("js/screen-settings.js", "  const keep = useRef(kept !== true);", "  const keep = useRef(false);"),
    "rcancel": ("js/screen-settings.js", "<button class=\"btn btn-ghost\" onClick=${onRegen}>", "<button class=\"btn btn-ghost\" onClick=${() => { closeModal(); onRegen(); }}>"),
    # [B18] (S9d): the config's font is not fitted to its box (a long line wraps); Download/Copy beside the QR, not under
    # it; the Keenetic steps lose `security-level private` (the router lets nothing in)
    "rfit": ("app.css", "font-size:clamp(9px, calc((100cqi - 26px) / (var(--rconf-cols) * 0.6)), 13px)", "font-size:15px"),
    "rside": ("app.css", ".rconf-side{display:flex;flex-direction:column;gap:8px}", ".rconf-side{display:flex;flex-direction:row;gap:8px}"),
    "rkind": ("js/screen-settings.js", '"interface WireguardN security-level private\\nip nat WireguardN', '"ip nat WireguardN'),
    # [B18] (S9d fix round): the not-kept notice no longer says why (store off) / that a later unlock keeps it (vault
    # locked); the Linux steps lose their FORWARD accept (a router whose FORWARD policy is DROP passes nothing)
    "rwhy": ("js/screen-settings.js", 'kept === false ? T("Not kept — keeping', 'false ? T("Not kept — keeping'),
    "rlocked": ("js/screen-settings.js", ': kept === EXIT_KEEP_LOCKED ?', ': false ?'),
    # [B18] (batch C): the open sheet follows a queued keep that an unlock kept (s9d F11); Regenerate asks once (s9c F59/F61)
    "rfollow": ("js/screen-settings.js", '  const kept = kept0 !== EXIT_KEEP_LOCKED ? kept0 : ks === null ? true : ks === "queued" ? EXIT_KEEP_LOCKED : ks;', '  const kept = kept0;'),
    "rbusy": ("js/screen-settings.js", "    if (REGEN_BUSY.on) return;\n", ""),
    "rfwd": ("js/screen-settings.js", "+ `iptables -C FORWARD -i ${tag} -j ${tag}-fwd 2>/dev/null || iptables -I FORWARD -i ${tag} -j ${tag}-fwd\\n`", "+ ``"),
    # [B18] (S9d verify F8 + s9d-f8-lan F3–F5): the tunnel's own chain drops the private ranges (a one-NIC box's LAN is
    # behind the uplink itself), lets out the uplink only and drops the rest (a tailnet, a second NIC); new connections
    # from the tunnel to the box itself are dropped
    "rlan": ("js/screen-settings.js", "-d 10.0.0.0/8,100.64.0.0/10,169.254.0.0/16,172.16.0.0/12,192.168.0.0/16 -j DROP", "-d 198.51.100.0/24 -j DROP"),
    "rrest": ("js/screen-settings.js", "-A ${tag}-fwd -j DROP\\nCOMMIT", "-A ${tag}-fwd -j ACCEPT\\nCOMMIT"),
    "rinput": ("js/screen-settings.js", "+ `iptables -C INPUT -i ${tag} -m conntrack ! --ctstate RELATED,ESTABLISHED -j DROP 2>/dev/null || iptables -I INPUT -i ${tag} -m conntrack ! --ctstate RELATED,ESTABLISHED -j DROP\\n`", "+ ``"),
    # [B18] (S9e, operator 10-23): Download and Copy one per row at the QR's width in every language, not side by side in EN
    "rstack": ("app.css", ".rconf-acts{display:flex;flex-direction:column;gap:6px}", ".rconf-acts{display:flex;flex-wrap:wrap;gap:6px}"),
    # [B18] (S9e): what was typed on create never reaches the generator; an edit-sheet field never reaches the text saved
    "dintyped": ("js/screen-settings.js", "psk, ...(typed || {}) } };", "psk } };"),
    # [B18] (S9e): an exit with no ping shows "—" again although the tunnel's time is measured
    "tcplat": ("js/screen-settings.js", '              : tcp\n              ? T("~{v1} ms"', '              : false\n              ? T("~{v1} ms"'),
    "latbub": ("js/screen-settings.js", 'return html`<${Popover} hoverOnly cls="exlat-pop" popCls="netroute-bub exlat-bub" trigger=${html`<span class="exlat">${v}</span>`}>${why}<//>`;',
               'return html`<span class="exlat" title=${why}>${v}</span>`;'),
    "dinphone": ("app.css", ".row2.dinrow>.field:first-child{flex:1 0 100%}", ".row2.dinrow>.field:first-child{flex:1}"),
    "dinedit": ("js/screen-settings.js", "    setTxt(t => confIfSet(t, k, val));\n  };", "    0;\n  };"),
    # [B18] (S9e review F12/F9/F7): a cleared "-" cell is no change; a trailing space is trimmed away; a cleared cell drawn by
    # the generator alone, the interface-defaults template ignored
    "dinclear": ("js/screen-settings.js", " || Object.values(dinBlank).some(Boolean)", ""),
    "dinspace": ("js/screen-settings.js", 'val = String(v ?? "").replace(/^[ \\t]+/, "");', 'val = String(v ?? "").trim();'),
    "dindraw": ("js/screen-settings.js", "out[k] = tpl[k] || String(g[k]);", "out[k] = String(g[k]);"),
    # [B18] (dial-in batch B, verify F59): a drawn S4 is fitted to the MTU in the browser too — a cleared S4 at MTU 1420
    "dins4fit": ("js/screen-settings.js", 'out.S4 = dialinS4(out.S4, mtu || 1280, proto === "awg3" ? 12 : 0);', '0;'),
    "rkeep": ("js/screen-settings.js", "    const kept = await exitKeepRouter(node.id, rec.id, rk.pub, rk.priv, nk.pub, nk.priv);", "    const kept = false;"),
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
    DXR = []                                    # [B18]: the exit rows the node reports (none before, so B1–B17 see what they always did)
    CSQ = [0]                                   # [B17]: 1 the node can run csqtt 2.5, 2 it runs a 2.5 server, 3 it reports csqtt_ar_pw (0 before, so B1–B16 see the fleet they always did)
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
                "net_carried": ["192.168.50.0/24", "192.168.60.0/24"], "dev_reach": {"ok": True, "ifaces": ["awg1", "awg2"]},
                **({"exits": list(DXR)} if DXR else {}),
                **({"csqtt_lines": ["2.1", "2.5"]} if CSQ[0] else {}), **({"csqtt_ar_pw": 1} if CSQ[0] > 2 else {}),
                **({"csqtt": [{"iface": "csqtt1", "kind": "csqtt", "fork": "csqtt", "active": "active", "line": "2.5",
                               "listen": "0.0.0.0:46000", "tun_addr": "10.66.80.1/24"}]} if CSQ[0] > 1 else {})}
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

    first_load = [True]
    def open_app(lang="en", viewport=None, retry=True):
        tab = Tab(br)
        if "--flake-first-load" in sys.argv and first_load[0]:   # the load flake, made to order: this tab cannot fetch peer-ui.js
            br.send("Network.enable", session=tab.s)
            br.send("Network.setBlockedURLs", {"urls": ["*/js/peer-ui.js*"]}, session=tab.s)
        first_load[0] = False
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
        booted = tab.ev("(async () => { if (!document.querySelector('.urow')) return 'no users grid'; try { await %s('peer-ui'); return ''; }"
                        " catch (e) { return String(e).slice(0, 160); } })()" % MOD)
        if booted and retry:
            print("  (retry: the app did not load in this tab — %s; a fresh tab, once)" % booted)
            tab.close()
            return open_app(lang, viewport, retry=False)
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

    # ── [B14] the app bar on a phone ─────────────────────────────────────────────────────────────────────────────────────────
    FULL = """(() => { const u = document.getElementById('updslot');
      if (u && !u.querySelector('.updpill')) u.insertAdjacentHTML('afterbegin', '<button class="livepill updpill">'
        + (document.documentElement.lang === 'ru' ? 'обновить до <b>1.8.10-beta</b>' : 'update to <b>1.8.10-beta</b>') + '</button>');
      for (const id of ['host-tport', 'vaultlock-btn', 'logs-btn']) { const e = document.getElementById(id); if (e) e.hidden = false; } })()"""
    BAR = """(() => { const bar = document.querySelector('.appbar'), br = bar.getBoundingClientRect();
      const ctl = [...bar.querySelectorAll('a,button,.livepill,.tport')].filter(e => !e.hidden && e.getClientRects().length)
        .map(e => { const r = e.getBoundingClientRect(), hit = document.elementFromPoint(Math.min(innerWidth - 1, r.left + r.width / 2), r.top + r.height / 2);
          return { t: (e.getAttribute('aria-label') || e.textContent).trim().slice(0, 20), l: Math.round(r.left), r: Math.round(r.right),
                   ok: r.left >= 0 && r.right <= innerWidth && !!hit && (hit === e || e.contains(hit)) }; });
      return { vw: innerWidth, right: Math.max(...[...bar.querySelectorAll('*')].map(e => e.getBoundingClientRect().right)), h: Math.round(br.height),
               pos: getComputedStyle(bar).position, ctl, n: ctl.length }; })()"""
    for lang in ("en", "ru"):
        tab = open_app(lang, viewport=(390, 844))
        m = tab.ev(BAR)
        bad = [c for c in m["ctl"] if not c["ok"]]
        check("[B14] %s 390 px: all %d visible header controls on the screen and tappable (before: the right cluster from x≈560 on)" % (lang, m["n"]),
              m["n"] >= 10 and not bad, bad or m)
        check("[B14] %s 390 px: the bar adds no width (its content ends inside 390 px; before: 1 257 px) and scrolls with the page" % lang,
              m["right"] <= m["vw"] and m["pos"] == "static", {k: m[k] for k in ("vw", "right", "pos", "h")})
        tab.close()
        tab = open_app(lang, viewport=(1280, 900))
        m = tab.ev(BAR)
        bad = [c for c in m["ctl"] if not c["ok"]]
        if lang == "en":
            check("[B14] en 1280 px: the one sticky 56 px row it was, everything on the screen", m["h"] == 56 and m["pos"] == "sticky" and not bad,
                  bad or {k: m[k] for k in ("h", "pos")})
        else:
            check("[B14] ru 1280 px: the one sticky 56 px row, every header control on the screen and tappable",
                  m["h"] == 56 and m["pos"] == "sticky" and not bad and m["right"] <= m["vw"], bad or {k: m[k] for k in ("vw", "right", "h", "pos")})
        # every header control on — the widest the bar gets — and measured in the same task: the header repaints its slots on the poll
        m = tab.ev("(" + FULL + ", " + BAR + ")")
        bad = [c for c in m["ctl"] if not c["ok"]]
        if lang == "ru":
            check("[B14] ru 1280 px, every header control on: still one 56 px row, Log out and the rest on the screen and tappable (before: Log out at 1 272–1 308 px)",
                  m["n"] >= 12 and not bad and m["right"] <= m["vw"] and m["h"] == 56, bad or {k: m[k] for k in ("vw", "right", "h")})
        else:
            check("[B14] en 1280 px, every header control on: still the one 56 px row, everything on the screen", m["n"] >= 12 and not bad and m["h"] == 56,
                  bad or {k: m[k] for k in ("vw", "right", "h")})
        tab.close()

    # ── [B15] the traffic rail and the rows' actions ────────────────────────────────────────────────────────────────────────
    RAIL = """(() => { const rail = document.querySelector('.trafficrail .railpanel'); if (!rail) return null;
      const btn = [...document.querySelectorAll('tbody tr button, .urow button')].map(b => { const r = b.getBoundingClientRect();
        if (r.top < 0 || r.bottom > innerHeight || !r.width) return null;
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return { x: Math.round(r.left), y: Math.round(r.top), ok: !!hit && (hit === b || b.contains(hit)) }; }).filter(Boolean);
      return { n: btn.length, covered: btn.filter(b => !b.ok) }; })()"""
    for w in (1280, 1366):
        for route in ("#/peers", "#/users"):
            tab = open_app("en", viewport=(w, 900))
            tab.goto(ORIGIN + "/" + route); settle(tab, 2500)
            m = tab.ev(RAIL)
            check("[B15] %d×900 %s: the rail covers none of the %s row buttons on screen%s" % (w, route, (m or {}).get("n"), " (before: the last action of each row in its band)" if w == 1280 else " (the control)"),
                  bool(m) and m["n"] >= 10 and not m["covered"], m)
            tab.close()

    # ── [B16] the Add-node command's address ────────────────────────────────────────────────────────────────────────────────
    tab = open_app("en", viewport=(1400, 900))
    for pub, want in (("https://panel.example.net:2087", "-host https://panel.example.net:2087"), ("", "-host " + ORIGIN)):
        txt = ev_mod(tab, "sheets-crud", STORE_JS + "S.panelPublicUrl = %s; const { h } = await import('preact'); const UI = await %s('ui');"
                     " UI.openModal(h(M.NodeTokenSheet, { name: 'q-new', token: 'TOKEN-B16', isNew: true }));"
                     " await new Promise(r => setTimeout(r, 900)); const sh = document.querySelector('.overlay.show .sheet');"
                     " const t = sh ? sh.textContent : ''; UI.closeAllModals(); return t;" % (json.dumps(pub), MOD))
        cmds = [c for c in (txt or "").split("sudo bash")[1:] if "TOKEN-B16" in c]   # each install command (bare metal, Docker)
        check("[B16] %s: the command says %s" % ("the panel's confirmed address set" if pub else "none set", want),
              len(cmds) == 2 and all(want in c for c in cmds), cmds or (txt or "")[:300])
        settle(tab, 400)
    tab.close()

    # ── [B17] csqtt App routing exceptions (docs/CSQTT-APP-ROUTING-WHO-PLAN.md §5) ───────────────────────────────────────────
    CSQ[0] = 1
    must(sync(), "sync from a node that runs csqtt 2.5")
    must(call("POST", "/api/csqtt/set", {"node": NID, "iface": "csqtt1", "listen": "0.0.0.0:46000", "tun_addr": "10.66.80.1/24", "line": "2.5",
                                         "app_routing": {"domains": ["ya.ru"]}}), "csqtt1 on 2.5")
    CSQ[0] = 2
    for who in ("anna", "tester", "tester", "boris"):
        must(call("POST", "/api/peers/create", {"title": who + " csqtt", "user_id": uid[who], "targets": [{"node": NID, "iface": "csqtt1", "type": "csqtt"}]}),
             "csqtt device for " + who)
    must(call("POST", "/api/csqtt/set", {"node": NID, "iface": "csqtt1", "app_routing_except": [
        {"who": {"groups": [GID["family"]]}, "app_routing": {"apps_mode": "except", "packages": ["org.telegram.messenger"]}},
        {"who": {"users": [uid["anna"]]}, "app_routing": None}]}), "exceptions")
    must(sync(), "sync with the csqtt devices")
    SHOTS = os.environ.get("SPA_SHOTS")
    def shot(tab, name):
        if SHOTS:
            with open(os.path.join(SHOTS, name + ".png"), "wb") as fh:
                fh.write(base64.b64decode(br.send("Page.captureScreenshot", {"format": "png"}, session=tab.s)["data"]))
    ROWS = ("[...document.querySelectorAll('.arx-row')].map(r => [[...r.querySelector('.arx-who').childNodes].filter(n => !(n.classList && n.classList.contains('arx-n')))"
            ".map(n => n.textContent).join(''), r.querySelector('.arx-rule').textContent])")
    TOP = "[...document.querySelectorAll('.overlay.show .sheet')].pop()"
    ESC = "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))"
    ASKS = "((%s || document).querySelector('.discard-msg') || {}).textContent || ''" % TOP
    def open_ar(tab):
        ev_mod(tab, "turn", "M.openEditCsqtt(%s, 'csqtt1'); return true;" % json.dumps(NID))
        settle(tab, 900)
        tab.ev("[...document.querySelectorAll('.overlay.show button.disc')].find(b => /App routing|Маршрутизация приложений/.test(b.textContent)).click()")
        settle(tab, 500)
    def click_text(tab, sel, rx):
        return tab.ev("(() => { const b = [...document.querySelectorAll(%s)].filter(e => %s.test(e.textContent) || %s.test(e.getAttribute('aria-label') || '')).pop();"
                      " if (!b) return false; b.click(); return true; })()" % (json.dumps(sel), rx, rx))
    for lang, vp in (("ru", (1280, 900)), ("en", (390, 844)), ("en", (1280, 900))):   # the last one edits and saves
        if lang == "en" and vp[0] == 1280:
            CSQ[0] = 3
            must(sync(), "sync from a node that reports csqtt_ar_pw")
        tab = open_app(lang, viewport=vp)
        open_ar(tab)
        rows = tab.ev(ROWS)
        tag = "%s %dpx" % (lang, vp[0])
        if lang == "en":
            check("[B17] %s: a row per exception, in order — whom it names, what they get" % tag,
                  rows == [["family", "Own rule: Apps"], ["anna", "No App routing"]], rows)
            check("[B17] %s: the summary counts them" % tag, "+ 2 exceptions" in (tab.ev("[...document.querySelectorAll('.overlay.show .disc-sum')].map(e => e.textContent).join('|')") or ""))
            need = "Exceptions need a node update" in (tab.ev("document.querySelector('.arx').textContent") or "")
            if vp[0] == 1280:
                check("[B17] %s: a node that reports csqtt_ar_pw is not said to need an update" % tag, not need)
            else:
                check("[B17] %s: a node that does not report csqtt_ar_pw is said to need an update" % tag, need)
            check("[B17] %s: the rows are numbered (the order decides; the panel names a refused one by its number)" % tag,
                  tab.ev("[...document.querySelectorAll('.arx-row .arx-n')].map(e => e.textContent)") == ["1.", "2."])
        else:
            check("[B17] ru: the rows in Russian", rows == [["family", "Своё правило: Приложения"], ["anna", "Без маршрутизации приложений"]], rows)
        fit = tab.ev("(() => { const sh = document.querySelector('.overlay.show .sheet').getBoundingClientRect();"
                     " return [...document.querySelectorAll('.arx-row, .arx-row *')].every(e => { const r = e.getBoundingClientRect(); return r.right <= sh.right + 0.5 && r.left >= sh.left - 0.5; }); })()")
        check("[B17] %s: every row and its controls inside the sheet" % tag, fit is True, fit)
        tab.ev("document.querySelector('.arx').scrollIntoView({block: 'center'})"); settle(tab, 300)
        shot(tab, "b17-list-" + tag.replace(" ", "-"))
        if lang == "en" and vp[0] == 1280:
            # edit the second row: its person is listed in the picker with the devices on this server, its rule is "No App routing"
            tab.ev("document.querySelectorAll('.arx-row')[1].querySelector('button[aria-label=\"Edit exception\"]').click()"); settle(tab, 700)
            ed = tab.ev("(() => { const sh = [...document.querySelectorAll('.overlay.show .sheet')].pop(); return { title: sh.querySelector('.sheet-head, h2, .sheet-title') ? sh.querySelector('.sheet-head, h2, .sheet-title').textContent : '',"
                        " who: [...sh.querySelectorAll('.gmembers .sharegrid-r')].map(r => [r.querySelector('.nm').textContent, r.children[1].textContent]),"
                        " rule: (sh.querySelector('[role=radio][aria-checked=true]') || {}).textContent, add: !!sh.querySelector('.sharebar-add') }; })()")
            check("[B17] the exception's sheet lists its person with the devices on this server, its rule picked, and the picker to add more",
                  ed and ed["who"] == [["anna", "1"]] and ed["rule"] == "No App routing" and ed["add"], ed)
            click_text(tab, ".overlay.show [role=radio]", "/^Own rule$/"); settle(tab, 400)
            tab.ev(ESC); settle(tab, 300)
            check("[B17] a click edit (Own rule) asks before Esc discards it", "Discard unsaved changes?" in tab.ev(ASKS), tab.ev(ASKS))
            click_text(tab, ".overlay.show .sheet-foot button", "/^Keep editing$/"); settle(tab, 300)
            check("[B17] Own rule opens the App routing form", tab.ev("[...document.querySelectorAll('.overlay.show .sheet')].pop().textContent.includes('Every app uses the tunnel')"))
            tab.ev("(() => { const ta = [...[...document.querySelectorAll('.overlay.show .sheet')].pop().querySelectorAll('textarea')][0];"
                   " const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; set.call(ta, 'vk.com'); ta.dispatchEvent(new Event('input', {bubbles: true})); })()")
            settle(tab, 300)
            shot(tab, "b17-edit")
            click_text(tab, ".overlay.show .sheet-foot button", "/^Apply$/"); settle(tab, 600)
            check("[B17] Apply puts the edited rule on its row", tab.ev(ROWS) == [["family", "Own rule: Apps"], ["anna", "Own rule: Domains"]], tab.ev(ROWS))
            click_text(tab, ".overlay.show button", "/Add exception/"); settle(tab, 700)
            add = tab.ev("(() => { const sh = [...document.querySelectorAll('.overlay.show .sheet')].pop(); const ap = [...sh.querySelectorAll('.sheet-foot button')].pop();"
                         " return { empty: (sh.querySelector('.sharegrid-empty') || {}).textContent, disabled: ap.disabled }; })()")
            check("[B17] a new exception names nobody yet: Apply waits for a person", add and add["disabled"] and "Choose at least one" in (add["empty"] or ""), add)
            shot(tab, "b17-add")
            tab.ev("(() => { const i = %s.querySelector('.sharebar-add input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                   " set.call(i, 'zz'); i.dispatchEvent(new Event('input', {bubbles: true})); })()" % TOP); settle(tab, 300)
            n0 = tab.ev("document.querySelectorAll('.overlay.show .sheet').length")
            click_text(tab, ".overlay.show .sheet-foot button", "/^Cancel$/"); settle(tab, 400)
            check("[B17] a search typed alone is no change: Cancel closes the new exception's sheet without asking",
                  tab.ev("document.querySelectorAll('.overlay.show .sheet').length") == n0 - 1 and "Discard" not in tab.ev(ASKS), (n0, tab.ev(ASKS)))
            tab.ev("document.querySelectorAll('.arx-row')[0].querySelector('button[aria-label=\"Remove exception\"]').click()"); settle(tab, 300)
            tab.ev(ESC); settle(tab, 300)
            check("[B17] a removed row asks before Esc discards the server sheet", "Discard unsaved changes?" in tab.ev(ASKS), tab.ev(ASKS))
            click_text(tab, ".overlay.show .sheet-foot button", "/^Keep editing$/"); settle(tab, 300)
            tab.ev("window.__arx = null; const of = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/api/csqtt/set')) window.__arx = o && o.body; return of(u, o); };")
            click_text(tab, ".overlay.show .sheet-foot button", "/^Save$/"); settle(tab, 1500)
            sent = json.loads(tab.ev("window.__arx") or "{}")
            check("[B17] Save sends the list as the rows hold it", sent.get("app_routing_except") == [{"who": {"users": [uid["anna"]]}, "app_routing": {
                "apps_mode": "all", "packages": [], "domains_mode": "direct", "domains": ["vk.com"], "template_domains": False, "ips_mode": "direct", "ips": []}}],
                  sent.get("app_routing_except"))
            st, o = call("GET", "/api/state")
            cfg = ((next((n for n in (o.get("data") or o).get("nodes") or [] if n.get("id") == NID), {}) or {}).get("csqtt_cfg") or {}).get("csqtt1") or {}
            check("[B17] …and the panel stores it", cfg.get("app_routing_except") == [{"who": {"users": [uid["anna"]]}, "app_routing": dict(
                P_AR_NONE, domains=["vk.com"])}], cfg.get("app_routing_except"))
        check("[console] (%s) App routing exceptions: clean" % tag, not console_bad(tab), console_bad(tab)[:3])
        close_modals(tab)
        tab.close()

    # ── [B18] a dial-in exit (docs/LISTEN-EXIT-PLAN.md §2.4) ────────────────────────────────────────────────────────────────────
    _K = ("QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=", "ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc=")
    def din_conf(port, addr):
        return "[Interface]\nPrivateKey = %s\nAddress = %s/31\nListenPort = %d\n\n[Peer]\nPublicKey = %s\nAllowedIPs = 10.254.0.1/32\n" % (_K[0], addr, port, _K[1])
    must(call("POST", "/api/nodes/update", {"id": NID, "exits": [{"id": "d1a1d1a1", "producer": "imported", "provider": "profile",
                                                                   "profile_text": din_conf(51830, "10.254.0.0")}]}), "a dial-in exit")
    _sig = next((x.get("cfg_sig") for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID
                 for x in (n.get("exits") or []) if x.get("id") == "d1a1d1a1"), "")
    DXR.append({"id": "d1a1d1a1", "device": "wgx-d1a1d1a1", "provider": "profile", "up": True, "handshake": 0, "listen_port": 51830,
                "cfg_sig": _sig, "endpoint": "", "error": "", "trace": {"tcp_ms": 53.3}, "address": "10.254.0.0", "awg": False, "ping_ms": None})
    must(sync(), "sync with the dial-in exit's row")
    time.sleep(3.5)                          # the background sync may have built its snapshot before the row existed
    must(sync(), "sync with the dial-in exit's row, again")
    SEC = "[...document.querySelectorAll('.setrail-i')].map(b => b.textContent.trim())"
    def x25519_pub(priv_b64):        # the public half of a WireGuard private key, by node's crypto (no Python dependency)
        r = subprocess.run(["node", "-e", "const c = require('crypto'); const k = Buffer.from(process.argv[1], 'base64');"
                            " const p = c.createPublicKey(c.createPrivateKey({key: Buffer.concat([Buffer.from('302e020100300506032b656e04220420', 'hex'), k]),"
                            " format: 'der', type: 'pkcs8'})); process.stdout.write(p.export({format: 'der', type: 'spki'}).subarray(-32).toString('base64'))",
                            priv_b64], capture_output=True, text=True, timeout=20)
        return r.stdout.strip()
    def open_exits(tab):
        ev_mod(tab, "ui", "M.setPendingSection('exits'); return true;")
        tab.ev("location.hash = '#/panel/settings'")
        settle(tab, 1200)
    for lang, vp in (("ru", (1280, 900)), ("en", (390, 844)), ("en", (1280, 900))):   # the last one pastes and saves
        tag = "%s %dpx" % (lang, vp[0])
        tab = open_app(lang, viewport=vp)
        open_exits(tab)
        ru = lang == "ru"
        check("[B18] %s: the section reads %s" % (tag, "«ВАРП и выходы»" if ru else "WARP & exits"),
              ("ВАРП и выходы" if ru else "WARP & exits") in (tab.ev(SEC) or []), tab.ev(SEC))
        row = tab.ev("(() => { const r = [...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes('wgx-d1a1d1a1'));"
                     " if (!r) return null; return {text: r.textContent, dot: (r.querySelector('.exg-dot') || {}).title || ''}; })()")
        check("[B18] %s: the row wears %s and waits for the router on UDP 51830" % (tag, "«Обратный»" if ru else "Dial-in"),
              bool(row) and ("Обратный" if ru else "Dial-in") in row["text"] and "51830" in row["dot"]
              and ("роутера" if ru else "router") in row["dot"], row)
        LATC = "[...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes('wgx-d1a1d1a1')).querySelector('.exg-c.c.mono .exlat')"
        lat = tab.ev("(() => { const c = %s; return c ? {text: c.textContent.trim(), title: c.closest('.exg-c').title || ''} : null; })()" % LATC) or {}
        _hv = hover(tab, LATC)
        settle(tab, 400)
        lat["bubble"] = tab.ev("(document.querySelector('.deppop.exlat-bub') || {}).textContent || ''") or ""
        shot(tab, "b18-latbub-%s-%d" % (lang, vp[0]))
        unhover(tab)
        check("[B18] (S9e) %s: no server to ping, so the latency is the tunnel's — ~53.3 %s, and its BUBBLE (not a native title) says it is measured through the router" % (tag, "мс" if ru else "ms"),
              lat.get("text") == ("~53.3 мс" if ru else "~53.3 ms") and not lat.get("title") and _hv
              and ("через роутер" if ru else "through the router") in lat.get("bubble", ""), lat)
        shot(tab, "b18-row-%s-%d" % (lang, vp[0]))
        clicked = click_text(tab, ".exadd button", "/Add a dial-in exit|Добавить обратный выход/")
        settle(tab, 600)
        SHEET = ("(() => { const s = %s; if (!s) return null; const b = [...s.querySelectorAll('.sheet-foot button')]; const sr = s.getBoundingClientRect();"
                 " return {title: (s.querySelector('.sheet-head') || {}).textContent || '', protos: [...s.querySelectorAll('.awgsw button')].map(x => x.textContent),"
                 " tops: b.map(x => Math.round(x.getBoundingClientRect().top)), inside: b.every(x => x.getBoundingClientRect().right <= sr.right + 1),"
                 " conf: (s.querySelector('pre.rconf-text') || {}).textContent || '', qr: !!s.querySelector('.qr img')}; })()" % TOP)
        gs = tab.ev(SHEET)
        check("[B18] %s: Add a dial-in exit opens Generate — WireGuard, AmneziaWG 2.0, AmneziaWG 3.1; Cancel and Create on one line" % tag,
              bool(clicked and gs) and ("Обратный выход" if ru else "Dial-in exit") in gs["title"]
              and gs["protos"] == ["WireGuard", "AmneziaWG 2.0", "AmneziaWG 3.1"] and len(gs["tops"]) == 2
              and max(gs["tops"]) - min(gs["tops"]) <= 3 and gs["inside"], gs)
        DROW = ("(() => { const s = %s; const f = s && [...s.querySelectorAll('.dinrow > .field')].map(x => x.getBoundingClientRect()); if (!f || f.length !== 3) return null;"
                " return {n: f.length, one: Math.abs(f[0].top - f[1].top) < 2 && Math.abs(f[1].top - f[2].top) < 2,"
                " phone: f[1].top >= f[0].bottom - 1 && Math.abs(f[1].top - f[2].top) < 2 && Math.abs(f[0].width - (f[2].right - f[1].left)) < 2,"
                " labels: [...s.querySelectorAll('.dinrow > .field > label')].map(l => l.textContent.trim())}; })()" % TOP)
        dr = tab.ev(DROW) or {}
        check("[B18] (S9e) %s: Title, Port and MTU at the top — %s" % (tag, "on one line" if vp[0] > 600 else "the title alone, then Port and MTU on the next line"),
              dr.get("labels", [])[1:] == (["Порт", "MTU"] if ru else ["Port", "MTU"]) and (dr.get("one") if vp[0] > 600 else dr.get("phone")), dr)
        shot(tab, "b18-gen-%s-%d" % (lang, vp[0]))
        if lang == "en" and vp[0] == 1280:          # Create: the router's config, shown once, from what the panel stored
            click_text(tab, ".overlay.show .sheet-foot button", "/^Create/")
            settle(tab, 3000)
            rs = tab.ev(SHEET)
            _gm = re.search(r"\nEndpoint = 203\.0\.113\.7:(\d+)\n", (rs or {}).get("conf", ""))
            gport = int(_gm.group(1)) if _gm else 0
            check("[B18] Create shows the router's config: Endpoint the node's host and the port it got (42821–42899, S9e), a QR; Regenerate and Done on one line",
                  bool(rs) and "Router config" in rs["title"] and 42821 <= gport <= 42899
                  and "PrivateKey = " in rs["conf"] and rs["qr"] and len(rs["tops"]) == 2
                  and max(rs["tops"]) - min(rs["tops"]) <= 3 and rs["inside"], rs)
            st = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            # The KEYS GO THE RIGHT WAY ROUND: the panel's peer for this exit is the PUBLIC half of the private key the router
            # config carries (X25519, by node's own crypto) — a swap would store the router's private key on the panel and
            # every text check above would still pass.
            gx = next((x for x in st if (x.get("profile") or {}).get("listen_port") == gport), {})
            rpriv = next((l.split(" = ", 1)[1] for l in rs["conf"].splitlines() if l.startswith("PrivateKey = ")), "")
            rpub = x25519_pub(rpriv) if rpriv else ""
            check("[B18] …the panel's peer for it is the public half of the router's key, and the router's peer is not itself",
                  bool(rpub) and (gx.get("profile") or {}).get("peer_key") == rpub
                  and ("\nPublicKey = " + rpub + "\n") not in rs["conf"], {"stored": (gx.get("profile") or {}).get("peer_key"), "derived": rpub})
            shot(tab, "b18-rconf-%s-%d" % (lang, vp[0]))
            # (S9d) the config whole, no scroll: every line on one row at a font between 9 and 13 px; Download and Copy
            # under the QR; the router's address a /31
            fit = tab.ev("(() => { const s = %s; const p = s && s.querySelector('pre.rconf-text'); if (!p) return null;"
                         " const cs = getComputedStyle(p), lh = parseFloat(cs.lineHeight), fs = parseFloat(cs.fontSize);"
                         " const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom), n = p.textContent.replace(/\\n+$/, '').split('\\n').length;"
                         " const q = s.querySelector('.rconf .qr img').getBoundingClientRect();"
                         " const b = [...s.querySelectorAll('.rconf-acts button')].map(x => x.getBoundingClientRect());"
                         " return {fs, rows: Math.round((p.clientHeight - pad) / lh), n, sx: p.scrollWidth - p.clientWidth, sy: p.scrollHeight - p.clientHeight,"
                         " under: b.length === 2 && b.every(r => r.top >= q.bottom - 1 && r.left >= q.left - 1 && r.right <= q.right + 1),"
                         " stacked: b.length === 2 && b[1].top >= b[0].bottom - 1 && b.every(r => Math.abs(r.width - q.width) <= 2)"
                         " && getComputedStyle(s.querySelector('.rconf-acts')).flexDirection === 'column'}; })()" % TOP) or {}
            check("[B18] (S9d) the router config is shown whole — one row a line, no scroll, its font fitted (9–13 px)",
                  fit.get("n") and fit.get("rows") == fit.get("n") and fit.get("sx", 1) <= 0 and fit.get("sy", 1) <= 0
                  and 9 <= fit.get("fs", 0) <= 13, fit)
            check("[B18] (S9d) …Download and Copy under the QR, in its column", fit.get("under"), fit)
            check("[B18] (S9e) …one per row, each the QR's width, in every language", fit.get("stacked"), fit)
            check("[B18] (S9d) …the router's address the other half of a /31", "\nAddress = " in rs["conf"]
                  and re.search(r"\nAddress = 10\.254\.\d+\.\d*[13579]/31\n", rs["conf"]) is not None, rs["conf"][:200])
            STEPS = ("(() => { const s = %s; return s ? {kinds: [...s.querySelectorAll('.rkind .seg')].map(b => b.textContent.trim()),"
                     " on: (s.querySelector('.rkind .seg.on') || {}).textContent || '', steps: (s.querySelector('.rsteps') || {}).textContent || ''} : null; })()" % TOP)
            ks = tab.ev(STEPS) or {}
            check("[B18] (S9d) On the router: Keenetic, OpenWrt, Other router — Keenetic's numbered steps carry its own commands",
                  ks.get("kinds") == ["Keenetic", "OpenWrt", "Other router"] and ks.get("on") == "Keenetic"
                  and "security-level private" in ks.get("steps", "") and "ip nat WireguardN" in ks.get("steps", "")
                  and ("swg-" + str(gx.get("id"))) in ks.get("steps", ""), ks)
            click_text(tab, ".overlay.show .rkind .seg", "/^OpenWrt$/")
            settle(tab, 300)
            ko = tab.ev(STEPS) or {}
            check("[B18] (S9d) …OpenWrt shows its own steps instead", ko.get("on") == "OpenWrt" and "Load configuration" in ko.get("steps", "")
                  and "security-level" not in ko.get("steps", ""), ko)
            click_text(tab, ".overlay.show .rkind .seg", "/^Other router$/")
            settle(tab, 300)
            kl = tab.ev(STEPS) or {}
            _cmd = tab.ev("[...document.querySelectorAll('.overlay.show .rsteps pre')].map(p => p.textContent).join('\\n')") or ""
            _ln = [l.strip() for l in _cmd.splitlines() if l.strip()]
            _ch = [l for l in _ln if re.match(r"-A swg-\S+-fwd ", l)]
            check("[B18] (S9d) …Other router: wg-quick, and the tunnel's own chain in the order it applies — the private ranges "
                  "dropped, out the uplink only, the rest dropped — jumped to from FORWARD, the replies let back, new "
                  "connections to the box itself dropped, the uplink named once, the node's address masqueraded",
                  "wg-quick up" in kl.get("steps", "")
                  and [re.sub(r"^-A swg-\S+-fwd ", "", l) for l in _ch] == [
                      "-d 10.0.0.0/8,100.64.0.0/10,169.254.0.0/16,172.16.0.0/12,192.168.0.0/16 -j DROP",
                      "-o $UPLINK -j ACCEPT", "-j DROP"]
                  # (s9d-f8-lan F7, backlog D review F3/F4) safe to paste again: the chain declared in one restore transaction,
                  # each other rule added once (-C), spelled out whole — no rule in a variable
                  and "iptables-restore --noflush <<EOF" in _ln and "COMMIT" in _ln and any(re.fullmatch(r":swg-\S+-fwd - \[0:0\]", l) for l in _ln)
                  and any(re.fullmatch(r"iptables -C FORWARD -i (swg-\S+) -j \1-fwd 2>/dev/null \|\| iptables -I FORWARD -i \1 -j \1-fwd", l) for l in _ln)
                  and any(re.fullmatch(r"iptables -C FORWARD (-o swg-\S+ -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT) 2>/dev/null \|\| iptables -I FORWARD \1", l) for l in _ln)
                  and any(re.fullmatch(r"iptables -C INPUT (-i swg-\S+ -m conntrack ! --ctstate RELATED,ESTABLISHED -j DROP) 2>/dev/null \|\| iptables -I INPUT \1", l) for l in _ln)
                  and _cmd.count("eth0") == 1 and "UPLINK=eth0" in _ln
                  and any(re.fullmatch(r"iptables -t nat -C POSTROUTING (-s 10\.254\.\S+ -o \$UPLINK -j MASQUERADE) 2>/dev/null \|\| iptables -t nat -A POSTROUTING \1", l) for l in _ln)
                  and not any(re.match(r"iptables -[AI] FORWARD -i swg-\S+ .*-j ACCEPT", l) for l in _ln), {"cmd": _cmd})
            _off = tab.ev("(() => { const s = %s; return s ? s.textContent : ''; })()" % TOP) or ""
            check("[B18] (S9d) the store off: the notice says why nothing is kept, and where to turn it on",
                  "keeping encrypted client configs is off (Settings → Client configs)" in _off, _off[:300])
            click_text(tab, ".overlay.show .rkind .seg", "/^Keenetic$/")
            settle(tab, 300)
            # not kept (the store is off), it is the only copy: Esc asks before it drops it
            tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
            settle(tab, 400)
            _g = tab.ev("(() => { const s = %s; return s ? [...s.querySelectorAll('.sheet-foot button')].map(b => b.textContent.trim()) : null; })()" % TOP) or []
            check("[B18] …not kept, Esc asks first instead of dropping the only copy", "Keep editing" in _g, _g)
            click_text(tab, ".overlay.show .sheet-foot button", "/Keep editing/")
            settle(tab, 300)
            # Regenerate's confirm opens over the sheet: Cancel comes back to the same config, not to a lost one
            click_text(tab, ".overlay.show .sheet-foot button", "/Regenerate router config/")
            settle(tab, 600)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Cancel$/")
            settle(tab, 500)
            rsc = tab.ev(SHEET)
            check("[B18] …Regenerate, then Cancel: the same router config is still open", bool(rsc) and rsc.get("conf") == rs["conf"],
                  (rsc or {}).get("title"))
            # Regenerate from the router config's own sheet: new keys both sides, the port and the address kept, shown again
            click_text(tab, ".overlay.show .sheet-foot button", "/Regenerate router config/")
            settle(tab, 600)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Regenerate$/")
            settle(tab, 3500)
            rs2 = tab.ev(SHEET)
            st2 = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            gx2 = next((x for x in st2 if x.get("id") == gx.get("id")), {})
            r2priv = next((l.split(" = ", 1)[1] for l in (rs2 or {}).get("conf", "").splitlines() if l.startswith("PrivateKey = ")), "")
            check("[B18] Regenerate shows a new router config on the same port and address, the stored peer its new key",
                  bool(rs2) and ("\nEndpoint = 203.0.113.7:%d\n" % gport) in rs2["conf"] and r2priv and r2priv != rpriv
                  and (gx2.get("profile") or {}).get("listen_port") == gport
                  and (gx2.get("profile") or {}).get("address") == (gx.get("profile") or {}).get("address")
                  and (gx2.get("profile") or {}).get("peer_key") == x25519_pub(r2priv), {"rs2": rs2, "stored": gx2.get("profile")})
            close_modals(tab)
            # …and a save the router has to follow says so, with Regenerate beside it (a view note, not stored)
            tab.ev("[...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes('wgx-d1a1d1a1')).querySelector('.exg-ed').click()")
            settle(tab, 600)
            _eb = tab.ev("(() => { const s = %s; return s ? [...s.querySelectorAll('button')].map(b => b.textContent.trim()) : null; })()" % TOP) or []
            check("[B18] the exit's edit sheet has no Regenerate — it lives with the router config", _eb and not any("Regenerate" in b for b in _eb), _eb)
            tab.ev("(() => { const t = %s.querySelector('textarea.exprof'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;"
                   " set.call(t, t.value.replace('ListenPort = 51830', 'ListenPort = 51832')); t.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % TOP)
            settle(tab, 300)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Save/")
            settle(tab, 2500)
            note = tab.ev("(() => { const r = [...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes('wgx-d1a1d1a1'));"
                          " const b = r && r.querySelector('.exg-qr'); return {chg: !!(b && b.classList.contains('chg')), title: b ? b.title : '',"
                          " row: r ? r.textContent : '', banner: [...document.querySelectorAll('.notice')].some(n => /router config changed/.test(n.textContent))}; })()") or {}
            check("[B18] a port change marks THAT row's QR button — the router config changed, port 51830 → 51832 — and no banner under the list",
                  note.get("chg") and "port 51830 → 51832" in note.get("title", "") and not note.get("banner"), note)
            check("[B18] …and the untitled exit is named by its port", "Dial-in exit :51832" in note.get("row", ""), note.get("row"))
            shot(tab, "b18-note-%s-%d" % (lang, vp[0]))
            # (S9c) the store off: the row's QR button says nothing is kept, and offers Regenerate
            QRBTN = ("(() => { const r = [...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes(%s));"
                     " const b = r && r.querySelector('.exg-qr'); if (b) b.click(); return !!b; })()")
            _qb = tab.ev(QRBTN % json.dumps(gx.get("device") or "wgx-?"))
            settle(tab, 800)
            _cf = tab.ev("(() => { const s = %s; return s ? s.textContent : ''; })()" % TOP) or ""
            check("[B18] the store off: the row's QR button says no router config is kept, and offers Regenerate",
                  _qb and "No router config is kept" in _cf and "Keeping encrypted client configs is off" in _cf and "Regenerate" in _cf,
                  {"button": _qb, "sheet": _cf[:300]})
            close_modals(tab)
            # …on, with a vault: Create keeps it, and the row's QR button shows the same router key again
            must(call("POST", "/api/panel/settings", {"store_configs": "encrypted"}), "keep encrypted configs")
            ev_mod(tab, "crypto", "await M.subVaultCreate('b18-vault-pass'); return true;")
            ev_mod(tab, "store", "await M.Store.poll(); return M.Store.storeMode;")
            settle(tab, 600)
            click_text(tab, ".exadd button", "/Add a dial-in exit/")
            settle(tab, 600)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Create/")
            settle(tab, 3500)
            ks = tab.ev(SHEET) or {}
            _ktxt = tab.ev("(() => { const s = %s; return s ? s.textContent : ''; })()" % TOP) or ""
            kpriv = next((l.split(" = ", 1)[1] for l in ks.get("conf", "").splitlines() if l.startswith("PrivateKey = ")), "")
            kport = next((l.rsplit(":", 1)[1] for l in ks.get("conf", "").splitlines() if l.startswith("Endpoint = ")), "")
            check("[B18] the store on: Create says the router config is kept, not shown once",
                  bool(kpriv) and "Kept encrypted with your client configs" in _ktxt and "Shown once" not in _ktxt, _ktxt[:300])
            shot(tab, "b18-kept-%s-%d" % (lang, vp[0]))
            tab.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
            settle(tab, 600)
            check("[B18] …and it closes on Esc like any sheet (it opens again from the row)", not tab.ev(SHEET), tab.ev(SHEET))
            close_modals(tab)
            st3 = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            kx = next((x for x in st3 if str((x.get("profile") or {}).get("listen_port")) == kport), {})
            _qb = tab.ev(QRBTN % json.dumps(kx.get("device") or "wgx-?"))
            settle(tab, 2000)
            rs3 = tab.ev(SHEET) or {}
            check("[B18] …the row's QR button shows the same router config again: its key, the node's host and port",
                  _qb and "Router config" in (rs3.get("title") or "") and ("PrivateKey = " + kpriv + "\n") in (rs3.get("conf") or "")
                  and ("\nEndpoint = 203.0.113.7:%s\n" % kport) in (rs3.get("conf") or "") and rs3.get("qr"),
                  {"button": _qb, "exit": kx.get("device"), "sheet": rs3})
            shot(tab, "b18-again-%s-%d" % (lang, vp[0]))
            close_modals(tab)
            # (S9d) the vault left locked: Create asks to unlock; skipped, the sheet says a later unlock in this tab keeps it
            ev_mod(tab, "crypto", "M.subForget(); return true;")
            click_text(tab, ".exadd button", "/Add a dial-in exit/")
            settle(tab, 600)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Create/")
            settle(tab, 1200)
            click_text(tab, ".overlay.show button", "/^Skip$/")
            settle(tab, 3500)
            _ltxt = tab.ev("(() => { const s = %s; return s ? s.textContent : ''; })()" % TOP) or ""
            check("[B18] (S9d) the vault left locked: the sheet says an unlock before a reload keeps it — not \"not kept anywhere\"",
                  "Not kept yet — the encryption key is locked" in _ltxt and "not kept anywhere" not in _ltxt, _ltxt[:300])
            # (s9d F11) unlocked now, in this tab, with the sheet still open: the queued key is kept, and the sheet says so
            ev_mod(tab, "crypto", "await M.subUnlock('b18-vault-pass'); return true;")
            settle(tab, 2500)
            _ltxt2 = tab.ev("(() => { const s = %s; return s ? s.textContent : ''; })()" % TOP) or ""
            check("[B18] (s9d F11) …unlocked with the sheet open: it now says the config is kept, not \"Not kept yet\"",
                  "Kept encrypted with your client configs" in _ltxt2 and "Not kept yet" not in _ltxt2, _ltxt2[:300])
            # (s9c F59/F61) a double click on Regenerate asks once
            tab.ev("(() => { const s = %s; const b = s && [...s.querySelectorAll('.sheet-foot button')].find(b => /Regenerate router config/.test(b.textContent));"
                   " if (b) { b.click(); b.click(); } })()" % TOP)
            settle(tab, 900)
            _nrc = tab.ev("[...document.querySelectorAll('.overlay.show')].filter(o => /Regenerate the router config\\?/.test(o.textContent)).length")
            check("[B18] (s9c F59/F61) a double click on Regenerate opens ONE confirm", _nrc == 1, _nrc)
            close_modals(tab)
            # (S9e) the port and the parameters typed on create reach the router config; the edit sheet shows them as fields.
            # 43860/43861: outside 42821–42899, so no exit an earlier block drew sits there (review F11: ~7% of runs collided)
            SETIN = ("(() => { const s = %s; const i = s && (%s); if (!i) return false; const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                     " set.call(i, %s); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
            CELL = "[...s.querySelectorAll('.awg-f')].map(l => (l.querySelector('span') || {}).textContent === %s ? l.querySelector('input') : null).find(Boolean)"
            click_text(tab, ".exadd button", "/Add a dial-in exit/")
            settle(tab, 600)
            _t1 = tab.ev(SETIN % (TOP, "s.querySelector('.dinport input')", json.dumps("43860")))
            click_text(tab, ".overlay.show .awgsw button", "/^AmneziaWG 2.0$/")
            click_text(tab, ".overlay.show .dinparams .advtoggle", "/Parameters/")
            settle(tab, 300)
            _t2 = [tab.ev(SETIN % (TOP, "s.querySelector('.dinmtu input')", json.dumps("1380"))),
                   tab.ev(SETIN % (TOP, CELL % json.dumps("S1"), json.dumps("33"))), tab.ev(SETIN % (TOP, CELL % json.dumps("I1"), json.dumps("-")))]
            settle(tab, 300)
            shot(tab, "b18-params-%s-%d" % (lang, vp[0]))
            click_text(tab, ".overlay.show .sheet-foot button", "/^Create/")
            settle(tab, 1200)
            click_text(tab, ".overlay.show button", "/^Skip$/")
            settle(tab, 3500)
            ts = tab.ev(SHEET) or {}
            check("[B18] (S9e) a port and parameters typed on create reach the router config: the port, the MTU, S1, no I1 line",
                  _t1 and all(_t2) and "\nEndpoint = 203.0.113.7:43860\n" in ts.get("conf", "") and "\nMTU = 1380\n" in ts.get("conf", "")
                  and "\nS1 = 33\n" in ts.get("conf", "") and "\nI1 = " not in ts.get("conf", "") and "\nS2 = " in ts.get("conf", ""),
                  {"typed": [_t1, _t2], "conf": ts.get("conf", "")[:400]})
            close_modals(tab)
            st4 = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            tx = next((x for x in st4 if (x.get("profile") or {}).get("listen_port") == 43860), {})
            tab.ev("(() => { const r = [...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes(%s)); r && r.querySelector('.exg-ed').click(); })()"
                   % json.dumps(tx.get("device") or "wgx-?"))
            settle(tab, 600)
            click_text(tab, ".overlay.show .dinparams .advtoggle", "/Parameters/")
            settle(tab, 300)
            EDV = ("(() => { const s = %s; if (!s) return null; const c = k => { const i = %s; return i ? i.value : null; };"
                   " return {port: (s.querySelector('.dinport input') || {}).value, mtu: (s.querySelector('.dinmtu input') || {}).value,"
                   " s1: c('S1'), i1: c('I1'), box: (s.querySelector('textarea.exprof') || {}).value || ''}; })()" % (TOP, CELL.replace("%s", "k")))
            ev0 = tab.ev(EDV) or {}
            check("[B18] (S9e) the edit sheet shows them as fields: the port beside the title, the MTU, S1, and I1 as - (no such line)",
                  ev0.get("port") == "43860" and ev0.get("mtu") == "1380" and ev0.get("s1") == "33" and ev0.get("i1") == "-", ev0)
            tab.ev(SETIN % (TOP, "s.querySelector('.dinport input')", json.dumps("43861")))
            tab.ev(SETIN % (TOP, CELL % json.dumps("S1"), json.dumps("44")))
            settle(tab, 300)
            ev1 = tab.ev(EDV) or {}
            check("[B18] (S9e) …editing a field rewrites its line in \"This node's end\"",
                  "\nListenPort = 43861\n" in ev1.get("box", "") and "\nS1 = 44\n" in ev1.get("box", "") and "\nI1 = " not in ev1.get("box", ""), ev1.get("box"))
            shot(tab, "b18-edit-params-%s-%d" % (lang, vp[0]))
            click_text(tab, ".overlay.show .sheet-foot button", "/^Save/")
            settle(tab, 2500)
            st5 = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            tx5 = next((x for x in st5 if x.get("id") == tx.get("id")), {})
            check("[B18] (S9e) …and Save stores them (port 43861, S1 44)",
                  (tx5.get("profile") or {}).get("listen_port") == 43861 and str(((tx5.get("profile") or {}).get("awg") or {}).get("S1")) == "44",
                  tx5.get("profile"))
            close_modals(tab)
            # (S9e review F7/F9/F12) a second edit: clearing a "-" cell alone is a change Save draws; a cleared cell is drawn as
            # create draws it (the interface-defaults template's Jc 7 here, not the generator's 4); a trailing space survives typing
            _sg = call("GET", "/api/state")[1]
            _ps0 = ((_sg.get("data", _sg) or {}).get("panel_settings") or {}).get("interface_defaults") or {}
            must(call("POST", "/api/panel/settings", {"interface_defaults": {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25, **_ps0,
                                                                             "awg_params": {"Jc": "7"}}}), "an interface-defaults template")
            settle(tab, 6000)                    # the next poll carries it to the browser
            tab.ev("(() => { const r = [...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes(%s)); r && r.querySelector('.exg-ed').click(); })()"
                   % json.dumps(tx.get("device") or "wgx-?"))
            settle(tab, 600)
            click_text(tab, ".overlay.show .dinparams .advtoggle", "/Parameters/")
            settle(tab, 300)
            SAVEOFF = "(() => { const s = %s; const b = s && [...s.querySelectorAll('.sheet-foot button')].find(b => /^Save/.test(b.textContent)); return b ? b.disabled : null; })()" % TOP
            CELLV = "(() => { const s = %s; const i = s && (%s); return i ? i.value : null; })()"
            _off0 = tab.ev(SAVEOFF)
            tab.ev(SETIN % (TOP, CELL % json.dumps("I1"), json.dumps("")))
            settle(tab, 200)
            _off1 = tab.ev(SAVEOFF)
            check("[B18] (S9e) clearing a cell that reads - (no such line) is a change: Save is enabled", _off0 is True and _off1 is False, (_off0, _off1))
            tab.ev(SETIN % (TOP, CELL % json.dumps("I2"), json.dumps("<r ")))
            settle(tab, 200)
            _sp = tab.ev(CELLV % (TOP, CELL % json.dumps("I2")))
            check("[B18] (S9e) …a trailing space typed into a cell stays (\"<r \" on the way to \"<r 32>\")", _sp == "<r ", repr(_sp))
            tab.ev(SETIN % (TOP, CELL % json.dumps("I2"), json.dumps("<r 32>")))
            tab.ev(SETIN % (TOP, CELL % json.dumps("Jc"), json.dumps("")))
            tab.ev(SETIN % (TOP, CELL % json.dumps("S4"), json.dumps("")))         # …and a cleared S4 at MTU 1420: room for 20
            tab.ev(SETIN % (TOP, "s.querySelector('.dinmtu input')", json.dumps("1420")))
            settle(tab, 300)
            click_text(tab, ".overlay.show .sheet-foot button", "/^Save/")
            settle(tab, 2500)
            st6 = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            a6 = (next((x for x in st6 if x.get("id") == tx.get("id")), {}).get("profile") or {}).get("awg") or {}
            check("[B18] (S9e) …Save draws the cleared cells as create does: I1 drawn, Jc the template's 7, I2 as typed",
                  str(a6.get("I1") or "").strip() != "" and str(a6.get("Jc")) == "7" and a6.get("I2") == "<r 32>", a6)
            check("[B18] (dial-in B, verify F59) …and a cleared S4 is drawn to fit MTU 1420 (at most 20: a full-size packet stays in 1500)",
                  str(a6.get("S4") or "").isdigit() and int(a6["S4"]) <= 20, a6.get("S4"))
            close_modals(tab)
            must(call("POST", "/api/panel/settings", {"interface_defaults": {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25, **_ps0,
                                                                             "awg_params": _ps0.get("awg_params") or {}}}), "the template back")
            click_text(tab, ".exadd button", "/Add a dial-in exit/")
            settle(tab, 600)
        click_text(tab, ".overlay.show .linkbtn", "/Paste the server config instead|Вставьте серверный конфиг/")
        settle(tab, 600)
        sh = tab.ev("(() => { const s = %s; if (!s) return null; const lab = [...s.querySelectorAll('.field label')].map(l => l.textContent.trim());"
                    " const b = [...s.querySelectorAll('.sheet-foot button')];"
                    " const sr = s.getBoundingClientRect();"
                    " return {title: (s.querySelector('.sheet-head') || {}).textContent || '', labels: lab,"
                    " tops: b.map(x => Math.round(x.getBoundingClientRect().top)), inside: b.every(x => x.getBoundingClientRect().right <= sr.right + 1)}; })()" % TOP)
        check("[B18] %s: …and its paste link the sheet for the server config, no Connect from" % tag,
              bool(sh) and ("Обратный выход" if ru else "Dial-in exit") in sh["title"] and ("Свой" if ru else "Custom") not in sh["title"]
              and ("Сторона ноды" if ru else "This node's end") in sh["labels"]
              and not any(l in sh["labels"] for l in ("Connect from", "Подключаться с")), sh)
        check("[B18] %s: Cancel and Save share the bottom line, inside the sheet" % tag,
              bool(sh) and len(sh["tops"]) >= 2 and max(sh["tops"]) - min(sh["tops"]) <= 3 and sh["inside"], sh)
        shot(tab, "b18-add-%s-%d" % (lang, vp[0]))
        if lang == "en" and vp[0] == 1280:
            tab.ev("(() => { const t = %s.querySelector('textarea.exprof'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;"
                   " set.call(t, %s); t.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % (TOP, json.dumps(din_conf(51831, "10.254.9.0"))))
            settle(tab, 300)
            _sv = click_text(tab, ".overlay.show .sheet-foot button", "/^Save/")
            settle(tab, 2500)
            _said = tab.ev("[...document.querySelectorAll('.overlay.show .err, .toast')].map(e => e.textContent).join(' | ')")
            st = [x for n in call("GET", "/api/nodes")[1].get("data", {}).get("nodes", []) if n.get("id") == NID for x in (n.get("exits") or [])]
            check("[B18] a server config pasted in the sheet and saved is stored as a dial-in exit",
                  any((x.get("profile") or {}).get("listen_port") == 51831 and not (x.get("profile") or {}).get("endpoint") for x in st),
                  {"clicked": _sv, "said": _said, "stored": st})
        close_modals(tab)
        tab.ev("[...document.querySelectorAll('.exgrid .exg-r')].find(r => r.textContent.includes('wgx-d1a1d1a1')).querySelector('.exg-ed').click()")
        settle(tab, 600)
        box = tab.ev("(%s.querySelector('textarea.exprof') || {}).value || ''" % TOP)
        check("[B18] %s: the stored dial-in exit's box is a server config — ListenPort, no Endpoint" % tag,
              ("ListenPort = %d" % (51832 if (lang, vp[0]) == ("en", 1280) else 51830)) in box and "Endpoint" not in box, box)   # en 1280 moved it
        shot(tab, "b18-edit-%s-%d" % (lang, vp[0]))
        check("[console] (%s) dial-in exit: clean" % tag, not console_bad(tab), console_bad(tab)[:3])
        close_modals(tab)
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
