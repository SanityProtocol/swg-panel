#!/usr/bin/env python3
"""Self-test for exit-candidate discovery — WHICH devices a node offers as "this box dials out here".

Why this exists: measured on the real fleet 2026-09-08, 17 of 55 devices reached the panel and **none** was
a wg/awg tunnel. `_node_addrs()` drops every `wg*`/`awg*`/`swg_*`/bridge/veth name, and the 17 that arrive
are the WAN NIC plus turn instances' own client-facing tunnels — every one of them a wrong answer for an
exit. The only thing on the node that identifies a real exit device is `_outbound_client_tunnel`, and it was
wired to SUPPRESS. This gate covers turning it into a reporter without turning it into an offer to adopt.

The two pieces of grammar, tested directly rather than through the /proc walk they run inside:
  · `_outbound_client_tunnel` — is this box dialling OUT here? (host /32 + a peer with an Endpoint whose
    AllowedIPs take the default route). All three are required, so a server can never match.
  · `_exit_cand_entry`        — the record. Facts only; `boot_persist` must pass through TRI-STATE.

Hermetic: no /proc, no wg, no systemctl — `iface_boot_persists` is stubbed so the tri-state can be driven.

Run: python3 tests/exit_candidates_selftest.py (0 = pass)
     --perturb  re-runs with the fix backed out and expects RED — a green gate proves nothing until seen red.
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded", NODED)
spec = importlib.util.spec_from_loader("swgnoded", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

# ── 1. the classifier: what IS an outbound tunnel ────────────────────────────────────────────────
WARP_PEER = [{"endpoint": "162.159.192.1:2408", "allowed_ips": "0.0.0.0/0, ::/0",
              "public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="}]
SERVER_PEER = [{"endpoint": "", "allowed_ips": "10.8.0.2/32", "public_key": "clientkeyclientkeyclientkey="}]

check("a WDTT-Plus/WARP exit tunnel is recognised (host /32 + endpoint + default route)",
      N._outbound_client_tunnel(None, "172.16.0.2/32", WARP_PEER) is True)
check("a SERVER is never an exit (holds a subnet, peer has no endpoint)",
      N._outbound_client_tunnel(None, "10.8.0.1/24", SERVER_PEER) is False)
check("a /32 with a peer that does NOT take the default route is not an exit",
      N._outbound_client_tunnel(None, "172.16.0.2/32",
                                [{"endpoint": "1.2.3.4:51820", "allowed_ips": "10.9.0.0/24"}]) is False)
check("a /32 whose peer has no endpoint is not an exit (we are not dialling it)",
      N._outbound_client_tunnel(None, "172.16.0.2/32", [{"endpoint": "", "allowed_ips": "0.0.0.0/0"}]) is False)
check("a mesh /31 is not an exit",
      N._outbound_client_tunnel(None, "10.255.0.1/31", WARP_PEER) is False)

# ── 2. the record ────────────────────────────────────────────────────────────────────────────────
_bp = {"v": None}
N.iface_boot_persists = lambda iface, cmd, now=None: _bp["v"]

e = N._exit_cand_entry("wgcf", "wg", None, "172.16.0.2/32", True, WARP_PEER)
check("record carries the far end's endpoint", e["endpoint"] == "162.159.192.1:2408", e)
check("record carries the far end's PUBLIC key (the WARP positive ID)",
      e["peer_key"] == WARP_PEER[0]["public_key"], e)
check("record carries name/proto/up/address", (e["name"], e["proto"], e["up"], e["address"])
      == ("wgcf", "wg", True, "172.16.0.2/32"), e)

# TRI-STATE: None must survive as None. Collapsing it to False tells a NixOS/container operator their
# healthy exit vanishes on reboot; collapsing to True promises persistence nobody checked (plan §11.4).
for want in (True, False, None):
    _bp["v"] = want
    got = N._exit_cand_entry("wgcf", "wg", None, "172.16.0.2/32", True, WARP_PEER)["boot_persist"]
    check("boot_persist passes through as %r (tri-state, not a boolean)" % (want,), got is want, repr(got))

# a DOWN tunnel has no live peers — the conf is the fallback, and it must still be a usable record
import tempfile
with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
    f.write("[Interface]\nAddress = 172.16.0.2/32\n\n[Peer]\n"
            "PublicKey = confpubkeyconfpubkeyconfpubkey=\nEndpoint = engage.cloudflareclient.com:2408\n"
            "AllowedIPs = 0.0.0.0/0\n")
    CONF = f.name
_bp["v"] = None
d = N._exit_cand_entry("wgcf", "wg", CONF, "172.16.0.2/32", False, [])
check("a DOWN tunnel still yields endpoint + peer key, read from the conf",
      d["endpoint"] == "engage.cloudflareclient.com:2408" and d["peer_key"].startswith("confpubkey"), d)
check("…and is reported as down, not omitted", d["up"] is False, d)
os.unlink(CONF)

# ── 3. the list is REBUILT per call, never appended across syncs ──────────────────────────────────
if not PERTURB:
    N._EXIT_CAND["list"] = [{"name": "stale-from-last-sync"}]
    src = open(NODED).read()
    check("iface_candidates resets the list before walking (else it grows every 5s and reports deleted devices)",
          '_EXIT_CAND["list"] = []' in src)
    check("the snapshot reads the list AFTER iface_candidates fills it",
          src.index('snap["iface_candidates"] = iface_candidates(') < src.index('snap["exit_candidates"] ='))
    check("exit candidates are a SEPARATE key, never merged into the adoption list",
          'snap["exit_candidates"] = list(_EXIT_CAND["list"])' in src)

# ── 4. the panel's ROLE verdict (plan §11.1 tier 3) ──────────────────────────────────────────────
# The node reports facts; only the panel knows whether a device is this node's own ingress. Each of these
# is a loop or a black hole rather than a slow path, so they are refusals, not warnings.
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
_pl = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _pl))
try:
    _pl.exec_module(P)
except SystemExit:
    pass

NODE = {"ifaces": {"awg0": {}, "swg_aa": {}},
        "wdtt": {"wdtt1": {"raw_iface": "wdttraw2"}},      # a RAW instance owns TWO devices
        "csqtt": {"csqtt1": {}}}
def why(dev, iface=None):
    return P.exit_device_refusal(NODE, dev, mesh_prefix="swg_", link_ifaces={"swg_aa"}, iface=iface)

check("a real outbound tunnel is offerable", why("wgcf") is None, why("wgcf"))
check("lo is refused", why("lo") == "loopback", why("lo"))
check("a blank device is refused, not passed through", why("") == "empty", why(""))
check("a mesh link by NAME is refused", why("swg_aa") == "mesh", why("swg_aa"))
check("a mesh link by PREFIX is refused (a node we have no link record for)", why("swg_zz") == "mesh", why("swg_zz"))
check("this node's own managed interface is refused", why("awg0") == "managed", why("awg0"))
check("a WDTT server's device is refused (ingress)", why("wdtt1") == "ingress", why("wdtt1"))
check("a csqtt server's device is refused (ingress)", why("csqtt1") == "ingress", why("csqtt1"))
# THE REGRESSION THIS EXISTS FOR: the RAW device is a FIELD, not a store key, so a `.keys()` test cannot
# see it. That is exactly how `wdttraw2` reached the egress picker as `Direct — wdttraw2` and replaced a
# working `-o eth0` MASQUERADE with one that can never match, silently killing the interface's NAT.
check("a qWDTT RAW second TUN is refused, though it is a FIELD and not a key",
      why("wdttraw2") == "ingress", why("wdttraw2"))
check("an interface may not exit via ITSELF", why("awg0", iface="awg0") == "self", why("awg0", iface="awg0"))
check("…and `self` needs the pairing — listing alone must not claim it",
      why("wgcf") is None and why("wgcf", iface="wgcf") == "self")
# Ordering: a mesh link is ALSO a managed iface. `mesh` must win, because it is the reason with a real
# alternative to offer ("that is Exit via node → P, which installs the return half too").
check("mesh beats managed for a device that is both", why("swg_aa") == "mesh", why("swg_aa"))
check("a device name Linux could never give is refused, not stored", why("a" * 20) == "name", why("a" * 20))
check("…and so is one with a slash or a space", why("wg/cf") == "name" and why("a b") == "name")
# ⚠️ NARROWER THAN THE KERNEL, and it has to be. Linux allows `tun"x` — nothing downstream can carry it:
# iptables quotes a comment and does not escape a device field, so `iptables-save` cannot round-trip that
# name, and the SWG_INET counter reader stops at the quote and files the exit's bytes under a TRUNCATED
# device. The exit silently under-reports. The `wan_iface` save paths have always applied this same regex;
# the two device-name fields that both end up in an iptables rule disagreeing was the defect.
for _bad in ('tun"x', "tun'x", "tun`x", "tun$x", "tun;x", "tun|x", "tun\\x", "tun*x", "tun@x"):
    check("a device name an iptables rule cannot carry is refused: %r" % _bad, why(_bad) == "name", why(_bad))
check("…while every shape a real device actually has still passes",
      all(why(d) is None for d in ("wgcf", "tun0", "eth0.100", "br-1a2b3c", "enp3s0", "ppp_0", "a" * 15)),
      [d for d in ("wgcf", "tun0", "eth0.100", "br-1a2b3c", "enp3s0", "ppp_0", "a" * 15) if why(d)])
check("`.` and `..` are still refused, which the regex alone would accept",
      why(".") == "name" and why("..") == "name", (why("."), why("..")))
# ⚠️ A NIC IS NOT AN EXIT. `default dev <D>` is a scope-link route: down a tunnel it is right, down a NIC it
# replaces `via <gw>` with a gatewayless route and the box ARPs the internet on the LAN — measured in a
# netns, both ways. This is `Direct — wdttraw2` in a new place: a picker offering a device that can only
# break the interface. The right control for a second NIC already exists (egress `direct` + `wan_iface`).
check("the node's own network card is refused",
      P.exit_device_refusal(NODE, "eth0", nics=["eth0", "ens3"]) == "nic")
check("…and a real exit tunnel is NOT caught by it",
      P.exit_device_refusal(NODE, "wgcf", nics=["eth0", "ens3"]) is None)
# ⚠️ THE REGRESSION THE FIRST VERSION OF THIS REFUSAL SHIPPED. It sourced `nics` from `node_ifaces`, which
# is filtered by NAME — and `tun0`, the sing-box/tun2socks device this feature advertises as v1's "bring
# your own device" producer (§11.6), carries an IPv4 and matches none of `_node_addrs`'s prefixes. So the
# one non-WireGuard producer the plan promises was refused. The kernel knows the difference (ARPHRD_ETHER
# vs point-to-point) and the node reports it as `ether_ifaces`; a name can never answer it.
check("a proxy's TUN is NOT refused — it is point-to-point, and §11.6's own answer",
      P.exit_device_refusal(NODE, "tun0", nics=["eth0"]) is None)
# …proven against the kernel rather than asserted: the node's own reader must agree about the two types.
_ether = N.list_ether_ifaces([("eth-probe", "1.2.3.4")])
check("list_ether_ifaces reports only what sysfs calls ARPHRD_ETHER (a name it cannot read is dropped)",
      _ether == [], _ether)

# ── THREE READERS, ONE LIST. The tuple, the function, and the SPA's sentences (§11.3's whole point). A code
# the function returns but the SPA has no sentence for falls through to "this node doesn't report a device
# by that name", which for `nic` or `name` is not merely unhelpful, it is false.
_fn = P.exit_device_refusal.__code__
_src = open(PANEL, encoding="utf-8").read()
_body = _src[_src.index("def exit_device_refusal("):]
_body = _body[:_body.index("\ndef ", 1)]
# ⚠️ THE ALPHABET IS PART OF THE GATE. This was `[a-z]+`, which cannot see `nic_nogw` or `nic_wan` — so
# a code the function returns would have been invisible to BOTH checks below and to the SPA-sentence one,
# and a new refusal could ship with no sentence anywhere. Only the second check caught it.
_returns = set(re.findall(r'return "([a-z_]+)"', _body))
check("the function returns nothing the tuple does not declare", not (_returns - set(P._EXIT_REFUSALS)),
      sorted(_returns - set(P._EXIT_REFUSALS)))
check("the tuple declares nothing the function cannot return", not (set(P._EXIT_REFUSALS) - _returns),
      sorted(set(P._EXIT_REFUSALS) - _returns))
_ui = open(os.path.join(ROOT, "js", "ui.js"), encoding="utf-8").read()
# ⚠️ ANCHORED ON THE EXPORTED MAP, not on the closure it used to live in. The sentences were lifted out of
# `ExitDevicePick` so the SAVE path could show them too (a refused save reached the operator as the raw
# code in a toast). This anchor moved with them; the assert below is what stops it going quietly missing.
_ANCH = "export const exitRefusalSentences = (value) => ({"
assert _ui.count(_ANCH) == 1, "refusal-sentence anchor missing or duplicated — this run would FALSE-PASS"
_why = _ui[_ui.index(_ANCH):]
_why = _why[:_why.index("\n});")]
_sent = set(re.findall(r"^\s{4}([a-z_]+):", _why, re.M))
assert _sent, "no refusal sentences parsed — the anchor matched but the shape changed"
# `self` has its own sentence too; `empty` never reaches the picker (the field is simply blank).
check("every refusal the operator can hit has a SENTENCE in the picker",
      not (_returns - _sent - {"empty"}), sorted(_returns - _sent - {"empty"}))
check("…and the picker has no sentence for a code that cannot happen",
      not (_sent - _returns), sorted(_sent - _returns))

if PERTURB:
    # Back the fix out: the classifier that only ever suppressed, and a boolean boot_persist.
    N._outbound_client_tunnel = lambda conf, addr, peers: False          # nothing is ever an exit
    N._exit_cand_entry = lambda *a, **k: {"name": a[0], "proto": a[1], "up": bool(a[4]), "address": a[3],
                                          "endpoint": "", "peer_key": "", "conf": "",
                                          "boot_persist": bool(_bp["v"])}   # tri-state collapsed
    # …and the refusal set reduced to a name-prefix test, which is what every previous version of this
    # question in the tree actually was — and what let the RAW device through.
    P.exit_device_refusal = lambda c, dev, mesh_prefix="swg_", link_ifaces=(), iface=None, nics=(): (
        "mesh" if str(dev or "").startswith("swg_") else None)
    FAILS.clear()
    check("perturbed: exit tunnel recognised", N._outbound_client_tunnel(None, "172.16.0.2/32", WARP_PEER) is True)
    _bp["v"] = None
    check("perturbed: boot_persist stays None",
          N._exit_cand_entry("wgcf", "wg", None, "1.2.3.4/32", True, WARP_PEER)["boot_persist"] is None)
    check("perturbed: RAW device still refused", why("wdttraw2") == "ingress", why("wdttraw2"))
    check("perturbed: own managed iface still refused", why("awg0") == "managed", why("awg0"))
    check("perturbed: self still refused", why("wgcf", iface="wgcf") == "self", why("wgcf", iface="wgcf"))
    if FAILS:
        print("\nperturbed: the pre-fix behaviour was CAUGHT (%d red) — this gate can fail" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not test what it claims")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
