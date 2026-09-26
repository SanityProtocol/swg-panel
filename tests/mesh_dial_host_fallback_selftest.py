#!/usr/bin/env python3
"""Self-test — a mesh link between nodes with only private addresses gets its peers.

A node's mesh peer is emitted only once the REMOTE end's dial host is known (desired_mesh_for_node), and that host was
the remote's `endpoint_host` (the operator's ingress address, or the panel's fill from a PUBLIC address it reports),
else its first public IP. A node whose every address is private — a LAN, a NAT'd cloud VM, the qualification lab — had
none unless an operator typed it, and one blank end takes the whole link down: WireGuard drops a handshake from a key
it does not hold. Measured in the 1.8.8 qualification on q3m ↔ q4n (a Docker master and a Docker node, 192.168.77.x):
both ends peerless, no issue raised; the master's endpoint set → the node dialled it and was ignored; both set →
handshake within seconds. Nothing any installer does can fill the NODE's record — its panel is elsewhere.

The last resort is now the host the remote advertises on that very link (what its clients are handed, reported as the
link interface's `meta.endpoint`).

  [1] two private-address nodes, both records blank → each end gets the other as a peer, dialling its advertised host
  [2] the order is unchanged: a per-connection dial_endpoint, then endpoint_host, then a public IP, then the advertised host
  [3] a fleet that meshes today is byte-identical (every link resolves before the new rung) — differential against the
      function as it shipped, over fleets with public IPs, explicit endpoints and overrides
  [4] no usable advertised host (link not reported yet, a wildcard, a loopback, an IPv6 literal) → no peer, as before

desired_mesh_for_node / mesh_endpoint_host / mesh_advertised_host run from swg-panel-server AS SHIPPED; the "before"
side of [3] is the same source with the shipped mesh_endpoint_host planted back.

Run: python3 tests/mesh_dial_host_fallback_selftest.py     (0 = pass)
     --perturb   the shipped mesh_endpoint_host (no advertised-host rung) planted back → RED
"""
import copy, importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

NEW = open(SERVER, encoding="utf-8").read()
OLD_FN = ('def mesh_endpoint_host(node, snap, iface=None):\n'
          '    return (node.get("endpoint_host") or "").strip() or node_public_ip(snap)\n')
_a = NEW.index("def mesh_endpoint_host(node, snap, iface=None):\n")
_b = NEW.index("\n\n\ndef desired_mesh_for_node(", _a)
OLD = NEW[:_a] + OLD_FN + NEW[_b:]

def load(src, name):
    p = os.path.join(tempfile.mkdtemp(prefix="meshdial-"), "swg-panel-server")
    open(p, "w").write(src)
    ld = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m

P = load(OLD if PERTURB else NEW, "swgpanel_meshdial")
B = load(OLD, "swgpanel_meshdial_before")

def fleet(a_ep="", b_ep="", a_ips=("192.168.77.3", "10.0.2.15"), b_ips=("192.168.77.4", "10.0.2.15"),
          a_adv="192.168.77.3:9999", b_adv="192.168.77.4:9999", dial=None):
    """q3m (a) ↔ q4n (b), linked on swg_c8, as the panel stores them; the snapshots as the nodes report them."""
    la = {"iface": "swg_c8", "peer_address": "10.255.0.0", "listen_port": 9999, "psk": "PSK="}
    lb = {"iface": "swg_c8", "peer_address": "10.255.0.1", "listen_port": 9999, "psk": "PSK="}
    if dial:
        la["dial_endpoint"] = dial
    nodes = {"a": {"name": "q3m", "endpoint_host": a_ep, "links": {"b": la}, "ifaces": {"swg_c8": {"public_key": "APUB=", "system": True}}},
             "b": {"name": "q4n", "endpoint_host": b_ep, "links": {"a": lb}, "ifaces": {"swg_c8": {"public_key": "BPUB=", "system": True}}}}
    def snap(ips, adv):
        s = {"node_ips": list(ips), "interfaces": {}}
        if adv is not None:
            s["interfaces"]["swg_c8"] = {"peers": [], "meta": {"endpoint": adv, "listen_port": 9999}}
        return s
    return nodes, {"a": snap(a_ips, a_adv), "b": snap(b_ips, b_adv)}

def peer(mod, nodes, snaps, nid):
    out = mod.desired_mesh_for_node(nodes, nid, 25, None, snaps)
    ps = (out or {}).get("swg_c8") or []
    return ps[0] if ps else None

print("[1] two nodes with only private addresses, both records blank")
nodes, snaps = fleet()
pa, pb = peer(P, nodes, snaps, "a"), peer(P, nodes, snaps, "b")
check("q3m's end gets q4n as a peer, dialling the host q4n advertises (192.168.77.4:9999)",
      pa is not None and pa["endpoint"] == "192.168.77.4:9999" and pa["public_key"] == "BPUB=", pa)
check("q4n's end gets q3m, dialling 192.168.77.3:9999", pb is not None and pb["endpoint"] == "192.168.77.3:9999", pb)
check("…the rest of the peer is the link's as before (allowed /32, psk, keepalive)",
      pa is not None and pa["allowed_ips"] == "10.255.0.0/32" and pa["preshared_key"] == "PSK=" and pa["persistent_keepalive"] == 25, pa)
nodes, snaps = fleet(a_ep="192.168.77.3")
pa = peer(P, nodes, snaps, "a")
check("only the master's endpoint set (a Docker master given -endpoint) → its end still gets the node's peer",
      pa is not None and pa["endpoint"] == "192.168.77.4:9999", pa)

print("\n[2] the order is unchanged — the new rung is the last")
for why, kw, want in (
        ("a per-connection dial_endpoint wins", dict(dial="198.51.100.7", b_ep="vpn.example.com"), "198.51.100.7:9999"),
        ("the remote's endpoint_host beats everything reported", dict(b_ep="vpn.example.com", b_ips=("95.216.1.9",)), "vpn.example.com:9999"),
        ("a reported public IP beats the advertised host", dict(b_ips=("192.168.77.4", "95.216.1.9")), "95.216.1.9:9999"),
        ("…and the advertised host is used only with neither", dict(), "192.168.77.4:9999")):
    nodes, snaps = fleet(**kw)
    pa = peer(P, nodes, snaps, "a")
    check(why, pa is not None and pa["endpoint"] == want, pa)

print("\n[3] a fleet that meshes today gets byte-identical peers")
same = 0
for kw in (dict(a_ips=("95.216.1.1",), b_ips=("95.216.1.2",)), dict(a_ep="a.example", b_ep="b.example"),
           dict(a_ep="192.168.77.3", b_ep="192.168.77.4"), dict(dial="198.51.100.7", b_ips=("95.216.1.2",), a_ips=("95.216.1.1",)),
           dict(a_ips=("95.216.1.1", "10.0.0.1"), b_ep="b.example", b_adv="0.0.0.0:9999")):
    nodes, snaps = fleet(**kw)
    for nid in ("a", "b"):
        before = B.desired_mesh_for_node(copy.deepcopy(nodes), nid, 25, None, copy.deepcopy(snaps))
        after = P.desired_mesh_for_node(copy.deepcopy(nodes), nid, 25, None, copy.deepcopy(snaps))
        ok = json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True) and before.get("swg_c8")
        same += bool(ok)
        check("identical to the shipped function (%s, %s's end)" % (", ".join("%s=%s" % i for i in sorted(kw.items())), nid), ok, (before, after))

print("\n[4] no usable advertised host → no peer, as before")
for why, adv in (("the remote has not reported the link yet", None), ("a wildcard", "0.0.0.0:9999"),
                 ("a loopback", "127.0.0.1:9999"), ("an IPv6 literal (the mesh is sized for IPv4)", "fd00::4:9999"),
                 ("no endpoint reported at all", "")):
    nodes, snaps = fleet(b_adv=adv)
    check(why, peer(P, nodes, snaps, "a") is None, peer(P, nodes, snaps, "a"))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
