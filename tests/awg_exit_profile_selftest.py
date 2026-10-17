"""Self-test — AN AmneziaWG PROFILE PASTED AS AN EXIT MUST BECOME AN AmneziaWG DEVICE.

Every field the exit parser used to keep is common to WireGuard and AmneziaWG, so an AWG config parsed
cleanly, stored cleanly and came up as a plain `wireguard` device with the obfuscation silently dropped. The
peer — an AmneziaWG server — ignores an unobfuscated handshake, so nothing ever crossed the tunnel.

⚠️ AND THE PANEL SHOWED IT GREEN, which is the half that made it invisible. An exit's health was
`_dev_link_state(dev) == "up"`, true the moment the interface exists whatever is at the other end. Reported
from the field exactly that way: a working AWG config, green status, no traffic.

MEASURED on msk-main. Before: `ip -d link` said `wireguard`, the conf had no `Jc`/`S1`/`H1`, and
`latest-handshakes` read **0** while the panel drew it healthy. After, pasting the same shape: the conf
carries all nine parameters, `ip -d link` says **amneziawg**, and an exit that never handshakes reports
`handshake: 0` and renders amber instead of green. The four working WARP exits alongside it read 51–118 s
since handshake and 109–126 ms round trip, so the new fields distinguish rather than blanket-warn.

There is no tooling obstacle: `wg`, `wg-quick`, `awg` and `awg-quick` are all present on every arm this
fleet runs — bare-metal, docker, podman and NixOS native — checked on each rather than assumed.

AND A 3.1 PROFILE IS NOT A 2.0 ONE (2026-10-17). The parser kept only the 2.0 keys, so a profile with a
HeaderProtectionKey — a client config of one of our own 3.1 interfaces — became an exit with S/H/Jc and no header
protection: green, and the 3.1 server ignored every handshake. [6]–[9]: the 3.x keys kept (as an interface reads
them), a 2.0 profile unchanged, the edit box round-trips, the panel refuses a 3.1 paste a node cannot run, and the
node never brings one up on a datapath older than 3.1.

Run: python3 tests/awg_exit_profile_selftest.py      (0 = pass)
     --perturb          drops the AWG fields at the parser and expects RED.
     --perturb-gen3     the parser drops a 3.1 profile's 3.x keys again (gen3=False) — RED in [6] [7].
     --perturb-refuse   the exits save no longer asks whether the node can run 3.1 — RED in [8].
     --perturb-node     the node brings a 3.1 exit up on a 2.0 datapath — RED in [9].
     --perturb-spa      the edit box renders the stored keys raw (DisableCookies, RandomTrailers = on) — RED in [7].
"""
import importlib.machinery, importlib.util, json, os, random, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PLANT = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), "")
SPA = os.path.join(ROOT, "js", "screen-settings.js")
CRYPTO = os.path.join(ROOT, "js", "crypto.js")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def _plant(src, old, new):
    assert src.count(old) == 1, "anchor missing — this run would FALSE-PASS: " + old[:60]
    return src.replace(old, new)

PSRC = open(PANEL, encoding="utf-8").read()
NSRC = open(NODED, encoding="utf-8").read()
SSRC = open(SPA, encoding="utf-8").read()
_ANCH = '    _awg = sanitize_awg_params({k: iface.get(k.lower()) for k in AWG_FIELDS}, gen3=_g3)'
assert PSRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    PSRC = PSRC.replace(_ANCH, "    _awg = {}")
if PLANT == "gen3":
    PSRC = _plant(PSRC, _ANCH, _ANCH.replace("gen3=_g3", "gen3=False"))
elif PLANT == "refuse":
    PSRC = _plant(PSRC, 'if gen_snap is not None and _pr["awg"].get("HeaderProtectionKey")', 'if False and _pr["awg"]')
elif PLANT == "node":
    NSRC = _plant(NSRC, "_no3 = awg_gen_refusal(dev, _exit_awg(rec))", '_no3 = ""')
elif PLANT == "spa":
    SSRC = _plant(SSRC, "...awgConfLines(p.awg),",
                  '...AWG_ORDER.filter(k => (p.awg || {})[k] != null).map(k => k + " = " + p.awg[k]),')
elif PLANT:
    sys.exit("unknown plant --perturb-" + PLANT)
_tmp = []
def _mod(src, real):
    if src == open(real, encoding="utf-8").read():
        return real
    fd, path = tempfile.mkstemp(suffix=".py", prefix="awgexit-", dir=HERE)
    os.write(fd, src.encode()); os.close(fd); _tmp.append(path)
    return path
ppath, npath = _mod(PSRC, PANEL), _mod(NSRC, NODED)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(ppath, "swgpanel")
N = _load(npath, "swgnoded")
for _t in _tmp:
    os.unlink(_t)

AWG_CONF = """[Interface]
PrivateKey = QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=
Address = 10.77.0.2/32
MTU = 1280
Jc = 4
Jmin = 40
Jmax = 70
S1 = 76
S2 = 39
H1 = 1234567890
H2 = 1122334455
H3 = 2233445566
H4 = 3344556677

[Peer]
PublicKey = ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc=
AllowedIPs = 0.0.0.0/0
Endpoint = 203.0.113.9:51820
"""
WG_CONF = "\n".join(l for l in AWG_CONF.splitlines()
                    if not re.match(r"^(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4)\s*=", l)) + "\n"

print("[1] the parser keeps the obfuscation, and only for a profile that has it")
pa, ea = P.parse_wg_profile(AWG_CONF)
check("an AWG profile parses", pa is not None, ea)
check("all nine parameters survive", pa and len(pa.get("awg") or {}) == 9, pa and pa.get("awg"))
check("values are carried verbatim", pa and (pa["awg"].get("Jc"), pa["awg"].get("H4")) == ("4", "3344556677"),
      pa and pa.get("awg"))
pw, ew = P.parse_wg_profile(WG_CONF)
check("a plain WireGuard profile still parses", pw is not None, ew)
check("…and gains no AWG fields", pw and pw.get("awg") == {}, pw and pw.get("awg"))
check("the shared fields are unchanged either way",
      pa and pw and (pa["peer_key"], pa["endpoint"]) == (pw["peer_key"], pw["endpoint"]))

print("\n[2] the node writes them into the conf, in a byte-stable order")
rec_a = {"priv": "k", "address": "10.77.0.2", "mtu": 1280, "peer_key": "p", "endpoint": "e:1",
         "awg": dict(pa["awg"]) if pa else {}}
txt = N._exit_conf_text(rec_a)
for k in ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"):
    check("conf carries %s" % k, ("\n%s = " % k) in txt, txt)
check("they sit in [Interface], before [Peer]", "Jc = " in txt and txt.index("Jc = ") < txt.index("[Peer]"), txt)
check("`Table = off` is still there — the route hazard is untouched", "\nTable = off\n" in txt)
import random
shuffled = dict(sorted(rec_a["awg"].items(), key=lambda kv: random.random()))
check("a reordered dict produces the SAME text (or the tunnel bounces every sync)",
      N._exit_conf_text({**rec_a, "awg": shuffled}) == txt)
rec_w = {**rec_a, "awg": {}}
check("a WireGuard exit's conf gains nothing", "Jc = " not in N._exit_conf_text(rec_w))

print("\n[3] the TOOL follows the config — wg-quick on an AWG conf makes a plain wireguard device")
check("AWG exit -> awg-quick", N._exit_tool(rec_a) == "awg-quick", N._exit_tool(rec_a))
check("WG exit -> wg-quick", N._exit_tool(rec_w) == "wg-quick", N._exit_tool(rec_w))
check("junk keys cannot smuggle a tool switch", N._exit_tool({"awg": {"Nope": "1"}}) == "wg-quick")
nsrc = open(NODED, encoding="utf-8").read()
check("no bare wg-quick invocation is left for exits", 'run(["wg-quick"' not in nsrc)
# The bring-up runs inside a systemd scope on hosts that have one (swg-noded:_scoped_up — an AWG exit on a module-less node
# would otherwise die with every restart of the daemon). What this pins is unchanged: the TOOL comes from _exit_tool, and
# _scoped_up hands that tool through as the command it runs.
check("the bring-up asks _exit_tool", '_scoped_up(_exit_tool(rec), conf)' in nsrc and 'plain = [tool, "up", target]' in nsrc)
# ⚠️ TEARING DOWN GOES THROUGH `_exit_down`, WHICH ASKS THE KERNEL, not `_exit_tool`. Re-pasting a
# WireGuard exit's profile as AmneziaWG rewrites the conf, so a tear-down keyed on the NEW config runs
# `awg-quick down` against a still-`wireguard` device and is refused ("is not a WireGuard interface").
# The device survives, the `up` branch never runs because the device is not absent, and nothing is even
# attempted — so there is no error either. The exit sits on the old datapath while the panel shows the new
# settings, which is what an operator sees as "I saved it and nothing happened".
check("every tear-down goes through _exit_down", nsrc.count("_exit_down(") >= 4, nsrc.count("_exit_down("))
check("_exit_down picks the tool from the KERNEL's answer", 'kind = _link_kind(dev)' in nsrc)
check("…and falls back to `ip link del`, which both kinds obey", 'run(["ip", "link", "del", dev])' in nsrc)
check("a device whose kind no longer matches the profile is rebuilt",
      '_have_kind not in ("", _want_kind)' in nsrc)

print("\n[4] health stops meaning 'the interface exists'")
check("the node reports a handshake age", '"handshake": (_exit_handshake(rec, dev) if _live else None)' in nsrc)
# Asked by what the device IS, with the other tool as a fallback. Keyed off the RECORD it returned nothing
# the moment record and device disagreed — exactly the case worth reporting — and `None` reads as "cannot
# say", so the panel fell through to `ok` and the broken exit went GREEN again with no IP and no latency.
check("…asked by the device's own kind", '_first = ["awg"] if (_kind == "awg" or (not _kind and _exit_awg(rec))) else _wgcmd(["wg"])' in nsrc)
check("…with the other tool as a fallback (one helper, _exit_clis, shared with the DDNS re-point)",
      "return (_first, _other)" in nsrc and "for cmd in _exit_clis(rec, dev):" in nsrc)
# ⚠️ AND THE AGE FLOORS AT 1, or the sentinel has two meanings. `max(0, now - ts)` IS 0 for the whole
# second after every rekey, so a healthy exit reported "never answered" about once every two minutes.
# See tests/exit_cfg_rev_selftest.py, which measures it.
check("…and 0 means NEVER, not missing", "return 0 if ts == 0 else max(1" in nsrc)
rj = open(os.path.join(ROOT, "js", "routing.js"), encoding="utf-8").read()
check("the panel has a state for up-but-never-answered", '"nohandshake"' in rj)
check("…triggered on === 0 so an older node is not blanket-warned", "l.handshake === 0" in rj)
check("…and it is a warning, not an ok", re.search(r'"nohandshake", tone: "warn"', rj) is not None)

print("\n[5] the latency the operator sees is the hop to the EXIT, not a request made through it")
# The first version showed a full HTTPS request to cloudflare.com via the tunnel: 179 ms for a Moscow exit
# ONE HOP AWAY, because ~169 ms of it is what a TLS handshake to Cloudflare costs from that node with no
# tunnel involved at all. Measured on msk-main — underlay 0.8-10.9 ms · direct request 169 ms · through the
# exit 266 ms — so the column was a near-constant offset with the interesting part buried in it.
ss = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
check("the node measures the underlay hop", "def _exit_ping(endpoint" in nsrc)
check("…with raw ICMP (the datagram kind is EACCES here, and `ping` is not in the node image)",
      "socket.SOCK_RAW, socket.IPPROTO_ICMP" in nsrc)
check("…accepting only OUR echo reply, from the server pinged, not any ICMP that arrives",
      "if typ == 0 and rid == ident and frm[0] == ip:" in nsrc and "ident = secrets.randbelow(0xFFFF) + 1" in nsrc)
check("…and caching the endpoint's DNS instead of resolving per exit per sync", "_EXIT_EP_IP" in nsrc)
check("select and struct are imported (a NameError here would read as 'cannot measure')",
      bool(re.search(r"^import select$", nsrc, re.M)) and bool(re.search(r"^import struct$", nsrc, re.M)))
check("it is reported to the panel (measured with the other probes, all devices at once — _exit_probe_all)",
      'res[dev] = (tr, rch, _exit_ping(rec.get("endpoint")))' in nsrc and '"ping_ms": (ping if _live else None),' in nsrc)
check("the through-tunnel request time is still measured", '"rtt_ms": int((time.monotonic() - _t0) * 1000)' in nsrc)
check("the exits table has a Latency column", 'T("Latency")' in ss)
check("…and it shows the UNDERLAY hop", "Number.isFinite(l.ping_ms)\n              ? T(\"{v1} ms\", { v1: l.ping_ms })" in ss)
check("…with the through-tunnel figure moved to the hover, saying what it includes",
      "which also includes however far that site is" in ss)
css = open(os.path.join(ROOT, "app.css"), encoding="utf-8").read()
g8 = re.search(r"\.exgrid\.g8\{grid-template-columns:([^}]*)\}", css)
check("the grid grew to 9 columns to match the header", g8 and len(g8.group(1).split()) == 9,
      g8 and g8.group(1).split())

print("\n[6] an AmneziaWG 3.1 profile keeps its 3.x keys; a 2.0 profile reads exactly as before")
HPK = "q83vEjRWeJCrze8SNFZ4kKvN7xI0VniQq83vEjRWeJA="
AWG31_CONF = AWG_CONF.replace("S2 = 39\n", "S2 = 39\nS3 = 25\nS4 = 18\n").replace(
    "H4 = 3344556677\n", "H4 = 3344556677\nHeaderProtectionKey = %s\nRandomTrailers = on\nContentPaddingAddition = 10-100\n"
    "RekeyAfterTime = 0\nMaxHandshakeAttempts = 15-20\nDisableCookies = 1\n" % HPK)
p3, e3 = P.parse_wg_profile(AWG31_CONF)
a3 = (p3 or {}).get("awg") or {}
check("a 3.1 profile parses", p3 is not None, e3)
check("…and keeps its HeaderProtectionKey", a3.get("HeaderProtectionKey") == HPK, a3)
check("…RandomTrailers written `1`, the one spelling every parser takes", a3.get("RandomTrailers") == "1", a3)
check("…its ranged keys verbatim", (a3.get("ContentPaddingAddition"), a3.get("MaxHandshakeAttempts")) == ("10-100", "15-20"), a3)
check("…a key at its 'unset' 0 left out", "RekeyAfterTime" not in a3, a3)
check("…DisableCookies never kept (D-cookies)", "DisableCookies" not in a3, a3)
check("…and every 2.0 key beside them", all(k in a3 for k in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H4")), a3)
_bad, _be = P.parse_wg_profile(AWG31_CONF.replace(HPK, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
check("an all-zero HeaderProtectionKey is refused (amneziawg-go reads it as off — never a handshake)",
      _bad is None and "HeaderProtectionKey" in str((_be or {}).get("error")), _be)
_low, _le = P.parse_wg_profile(AWG31_CONF.replace("S4 = 18\n", "S4 = 8\n"))
check("S1–S4 under 12 with header protection is refused (the kernel refuses it)",
      _low is None and "S4" in str((_le or {}).get("error")), _le)
# A 2.0 profile, and one carrying 3.x keys with no HeaderProtectionKey (not 3.1, §7.1): the parser of the base commit
# gives the same dict — the 3.x branch is reached only by a profile that has the key.
BASE = "3f224a62"
_bs = subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-panel-server"], capture_output=True, text=True)
check("the base commit's parser can be read (git)", _bs.returncode == 0, _bs.stderr[:200])
if _bs.returncode == 0:
    fd, bpath = tempfile.mkstemp(suffix=".py", prefix="awgexit-base-", dir=HERE)
    os.write(fd, _bs.stdout.encode()); os.close(fd)
    try:
        B = _load(bpath, "swgpanel_base")
    finally:
        os.unlink(bpath)
    NOHPK = AWG_CONF.replace("H4 = 3344556677\n", "H4 = 3344556677\nRandomTrailers = 1\nContentPaddingAddition = 10-100\n")
    for nm, conf in (("an AWG 2.0 profile", AWG_CONF), ("a WireGuard profile", WG_CONF), ("3.x keys without a key", NOHPK)):
        check("%s: identical to %s" % (nm, BASE), P.parse_wg_profile(conf) == B.parse_wg_profile(conf),
              (P.parse_wg_profile(conf), B.parse_wg_profile(conf)))
    check("(the defect: %s dropped the 3.1 profile's header protection)" % BASE,
          "HeaderProtectionKey" not in ((B.parse_wg_profile(AWG31_CONF)[0] or {}).get("awg") or {}))

print("\n[7] the edit box renders a stored profile back as the parser stores it — a round trip changes nothing")
if not shutil.which("node"):
    check("node on PATH (profileText is JavaScript — no node is not a pass)", False)
else:
    _cr = open(CRYPTO, encoding="utf-8").read()
    _order = re.search(r"export const AWG_ORDER = \[.*?\];", _cr, re.S)
    _lines = re.search(r"const AWG3_FROM = .*?\nexport function awgConfLines\(awg\) \{.*?\n\}\n", _cr, re.S)
    _pt = re.search(r"\nfunction profileText\(ex\) \{.*?\n\}\n", SSRC, re.S)
    check("profileText and awgConfLines found", bool(_order and _lines and _pt))
    if _order and _lines and _pt:
        STORED_ODD = dict(a3, DisableCookies="1", RandomTrailers="on")   # a record not written by this parser
        cases = {"awg20": pa, "wg": pw, "awg31": p3, "odd": dict(p3, awg=STORED_ODD)}
        js = ("const Store = {};\n" + _order.group(0).replace("export ", "") + "\n" + _lines.group(0).replace("export ", "")
              + _pt.group(0) + "\nconst C = " + json.dumps(cases) + ";\nconst out = {};\n"
              "for (const k in C) { Store.exitKeyKeep = C[k].private_key; Store.exitPskKeep = C[k].psk; out[k] = profileText({ profile: C[k] }); }\n"
              "console.log(JSON.stringify({ out, odd: awgConfLines(C.odd.awg) }));\n")
        r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
        check("node ran it", r.returncode == 0, r.stderr[:300])
        if r.returncode == 0:
            got = json.loads(r.stdout)
            for k in ("awg20", "wg", "awg31"):
                check("%s: profileText → parse_wg_profile gives the stored profile back" % k,
                      P.parse_wg_profile(got["out"][k]) == (cases[k], ""), (got["out"][k], P.parse_wg_profile(got["out"][k])))
            check("a 3.1 box carries its HeaderProtectionKey and `RandomTrailers = 1`",
                  "HeaderProtectionKey = " + HPK in got["out"]["awg31"] and "\nRandomTrailers = 1\n" in got["out"]["awg31"], got["out"]["awg31"])
            _odd = got["out"]["odd"]
            check("a stored set with DisableCookies / RandomTrailers = on renders as a client config does (awgConfLines)",
                  all(l in _odd for l in got["odd"]) and "DisableCookies" not in _odd and "RandomTrailers = on" not in _odd, _odd)

print("\n[8] the exits save refuses a 3.1 profile the node cannot run — and only a 3.1 profile it changes")
def snap(module=None, fallback=None, tools=None, gen=True):
    return {"datapath": {"awg": ({"gen": {"module": module, "fallback": fallback, "tools": tools}} if gen else {})}}
S31, S20MOD = snap("3.1", None, "3.1"), snap("2.0", None, "3.1")
S20GO, SOLD = snap(None, "2.0", "2.0"), snap(gen=False)
NODE = {"name": "lab"}
X31 = {"id": "aabbccdd", "producer": "imported", "provider": "profile", "profile_text": AWG31_CONF}
X20 = dict(X31, profile_text=AWG_CONF)
V = lambda xs, sn, prev=(): P._validate_exits(xs, NODE, prev=list(prev), gen_snap=sn)
ok31, e = V([X31], S31)
check("a 3.1 node takes it, its 3.x keys stored", e is None and ok31 and ok31[0]["profile"]["awg"].get("HeaderProtectionKey") == HPK, e)
for nm, sn, key in (("a 2.0 kernel module", S20MOD, "{v1}: its AmneziaWG kernel module is {v2}"),
                    ("a 2.0 amneziawg-go and tools", S20GO, "{v1}: its userspace AmneziaWG (amneziawg-go)"),
                    ("a node that reports no generation (older)", SOLD, "{v1}: this node does not report its AmneziaWG version"),
                    ("a node with no snapshot (offline — the panel cannot know)", {}, "{v1}: this node does not report")):
    c, e = V([X31], sn)
    check("%s: refused with the reason, as a perr" % nm,
          c is None and isinstance(e, dict) and str(e.get("error_key") or "").startswith(key) and (e.get("error_vars") or {}).get("v1") == "lab", e)
check("a 2.0 profile on a 2.0 node: taken", V([X20], S20MOD)[1] is None)
check("a caller that saves no profile (gen_snap None) asks nothing", V([X31], None)[1] is None)
check("the stored 3.1 exit re-sent unchanged on a node now 2.0: taken (a stored exit stays savable)",
      V([X31], S20MOD, ok31)[1] is None)
check("…and renamed with no paste: taken", V([{k: v for k, v in X31.items() if k != "profile_text"}], S20MOD, ok31)[1] is None)
c, e = V([dict(X31, profile_text=AWG31_CONF.replace("10-100", "20-80"))], S20MOD, ok31)
check("…but a CHANGED 3.1 profile on it: refused", c is None and isinstance(e, dict), e)
check("the node update passes its snapshot and answers a perr as one",
      "wan=(_sn.get(\"wan_iface\") or \"\"), gen_snap=_sn)" in PSRC and
      'if isinstance(_err, dict):                   # a perr' in PSRC)
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
for e2 in (V([X31], S20MOD)[1], V([X31], S20GO)[1], V([X31], SOLD)[1]):
    check("RU has %r" % (e2 or {}).get("error_key", "")[:50], json.dumps((e2 or {}).get("error_key") or "-", ensure_ascii=False)[1:-1] in ru)

print("\n[9] the node writes a 3.1 exit's keys in order, stably — and never brings one up on a datapath older than 3.1")
rec31 = {"priv": "k", "address": "10.77.0.2", "mtu": 1280, "peer_key": "p", "endpoint": "e:1", "awg": dict(a3)}
t31 = N._exit_conf_text(rec31)
_ix = [t31.find("\n%s = " % k) for k in N.AWG_KEYS if k in a3]
check("the conf carries every kept key, in AWG_KEYS order", all(i > 0 for i in _ix) and _ix == sorted(_ix), t31)
check("…the same text from a reordered dict", N._exit_conf_text(dict(rec31, awg=dict(sorted(a3.items(), key=lambda kv: random.random())))) == t31)
check("…`RandomTrailers = 1`, and no DisableCookies", "\nRandomTrailers = 1\n" in t31 and "DisableCookies" not in t31, t31)
class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc
def lower(prof, gen, d=None):
    calls = []
    N.EXIT_DIR = d or tempfile.mkdtemp()
    N.run = lambda a, **k: (calls.append(" ".join(map(str, a))), _R(""))[1]
    N._dev_link_state = lambda dev: "up" if os.path.exists(os.path.join(N.EXIT_DIR, ".up")) else "absent"
    _run = N.run
    def _r(a, **k):
        r = _run(a, **k)
        if " ".join(map(str, a)).endswith("up " + os.path.join(N.EXIT_DIR, "wgx-aabbccdd.conf")):
            open(os.path.join(N.EXIT_DIR, ".up"), "w").close()
        return r
    N.run = _r
    N._link_kind = lambda dev: "awg"
    N._exit_trace = lambda dev: {"ip": "198.51.100.31"}
    N._exit_ping = lambda *a, **k: None
    N.awg_gen_report = lambda now=None: dict(gen)
    res = {"changed": 0, "errors": []}
    N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "profile", "profile": prof, "cfg_sig": "s"}], res)
    row = next((x for x in N._EXITS["list"] if x.get("id") == "aabbccdd"), {})
    return calls, res, row, N.EXIT_DIR
G20 = {"module": "2.0", "fallback": None, "tools": "3.1", "disk": None}
G31 = {"module": "3.1", "fallback": None, "tools": "3.1", "disk": None}
calls, res, row, d = lower(p3, G20)
check("a 2.0 module: no bring-up", not any(" up " in c for c in calls), calls)
check("…the row says why, and is not up", row.get("up") is False and "AmneziaWG 3.1 needs" in str(row.get("error")), row)
check("…and the node's errors carry it", any("not applied" in x for x in res["errors"]), res)
calls, res, row, d = lower(p3, G31)
check("a 3.1 node: awg-quick up", any(re.search(r"(^|\s)awg-quick up ", c) for c in calls), calls)
check("…up, no error", row.get("up") is True and not row.get("error"), row)
c1 = open(os.path.join(d, "wgx-aabbccdd.conf")).read()
calls, res, row, d = lower(p3, G31, d)
check("a second sync: nothing rewritten, nothing bounced", res["changed"] == 0 and not any(" down " in c or "link del" in c for c in calls)
      and open(os.path.join(d, "wgx-aabbccdd.conf")).read() == c1, (res, calls))
calls, res, row, d = lower(pa, G20)
check("a 2.0 profile on a 2.0 node: brought up (the floor asks nothing of 2.0)", any(re.search(r"(^|\s)awg-quick up ", c) for c in calls), calls)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
