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

Run: python3 tests/awg_exit_profile_selftest.py      (0 = pass)
     --perturb   drops the AWG fields at the parser and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

PSRC = open(PANEL, encoding="utf-8").read()
_ANCH = '    _awg = sanitize_awg_params({k: iface.get(k.lower()) for k in AWG_FIELDS})'
assert PSRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    PSRC = PSRC.replace(_ANCH, "    _awg = {}")
ppath = PANEL
if PERTURB:
    _fd, ppath = tempfile.mkstemp(suffix=".py", prefix="awgexit-", dir=HERE)
    os.write(_fd, PSRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

P = _load(ppath, "swgpanel")
N = _load(NODED, "swgnoded")
if PERTURB:
    os.unlink(ppath)

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
check("they sit in [Interface], before [Peer]", txt.index("Jc = ") < txt.index("[Peer]"), txt)
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
check("the bring-up asks _exit_tool", 'run([_exit_tool(rec), "up", conf])' in nsrc)
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
check("…with the other tool as a fallback", "for cmd in (_first, _other):" in nsrc)
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
check("…accepting only OUR echo reply, not any ICMP that arrives", "if typ == 0 and rid == ident:" in nsrc)
check("…and caching the endpoint's DNS instead of resolving per exit per sync", "_EXIT_EP_IP" in nsrc)
check("select and struct are imported (a NameError here would read as 'cannot measure')",
      bool(re.search(r"^import select$", nsrc, re.M)) and bool(re.search(r"^import struct$", nsrc, re.M)))
check("it is reported to the panel", '"ping_ms": (_exit_ping(rec.get("endpoint")) if _live else None)' in nsrc)
check("the through-tunnel request time is still measured", '"rtt_ms": int((time.monotonic() - _t0) * 1000)' in nsrc)
check("the exits table has a Latency column", 'T("Latency")' in ss)
check("…and it shows the UNDERLAY hop", "Number.isFinite(l.ping_ms)\n              ? T(\"{v1} ms\", { v1: l.ping_ms })" in ss)
check("…with the through-tunnel figure moved to the hover, saying what it includes",
      "which also includes however far that site is" in ss)
css = open(os.path.join(ROOT, "app.css"), encoding="utf-8").read()
g8 = re.search(r"\.exgrid\.g8\{grid-template-columns:([^}]*)\}", css)
check("the grid grew to 9 columns to match the header", g8 and len(g8.group(1).split()) == 9,
      g8 and g8.group(1).split())

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
