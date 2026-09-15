#!/usr/bin/env python3
"""Self-test for NETWORKS P0 — the stranding guard on the node (docs/NETWORKS-PLAN.md §4.1, D7).

A route to a declared network is `ip route replace <prefix> dev <tunnel>`, and `replace` takes a prefix a
connected route already owns, silently. Measured on .campaign/rigs/home-node-netns.sh: a node handed its own
LAN keeps its default route and loses everything addressed ON the LAN — its resolver with it — so a panel it
knows by hostname can never be resolved again and the node never hears the correction. A site visit.

So the node refuses from its own kernel, and then checks its work. This gate covers the parts of that which
a plausible implementation gets wrong without anything on screen saying so:

  [1] THE RESOLVER READ. /etc/resolv.conf alone is blind on both live nodes measured (msk-main, svo-im): it
      names the systemd-resolved stub 127.0.0.53, and the real servers are in a second file — which is not
      mounted at all inside svo-im's host-net container. A read that finds nothing must say it found nothing
      it could trust (`known` False), or "no resolver" waves through the route that deafens the box.
  [2] the default-gateway read, every device, and a read that failed is None, not [].
  [3] the refusal table, one case per token — including OVERLAP for the box's own networks (half a LAN is
      as wrong as all of it) and CONTAINMENT for what it reaches out to.
  [4] the `ip -batch route get` parser, including the kernel's own shapes: a `local` route, a `cache`
      continuation line, an address that has no route at all.
  [5] VERIFY-AFTER-APPLY, against a small kernel model: a route that moves the path to a dependency comes
      straight back out; a foreign exact route is never replaced; a refusal issues no `replace` at all.
  [6] D1 — the snapshot half (`net_deps`) forks nothing.

Hermetic: `run()` is replaced by a routing-table model. Nothing touches the network or the host.

Run: python3 tests/network_guard_selftest.py            (0 = pass)
     --perturb    makes the after-read a no-op (`_route_paths` answers {} both times) and expects RED on [5]:
                  a stranding route then stays in, which is exactly the failure the net exists to catch.
"""
import importlib.machinery, importlib.util, ipaddress, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="netguard-")
def f(name, text):
    p = os.path.join(TMP, name)
    with open(p, "w") as fh:
        fh.write(text)
    return p

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[1] resolvers — what the box's lookups actually depend on")
up = f("upstream", "nameserver 85.193.93.193\nnameserver 2a03:6f00:1:2::5c35:7468\nnameserver 85.193.93.194\n")
cases = [
    ("plain LAN resolver, v6 ignored",
     f("plain", "nameserver 192.168.1.1\nnameserver 2001:db8::1\n"), up, (["192.168.1.1"], True)),
    ("resolved stub → the upstream file (msk-main / svo-im host, measured)",
     f("stub", "nameserver 127.0.0.53\noptions edns0 trust-ad\nsearch .\n"), up, (["85.193.93.193", "85.193.93.194"], True)),
    ("resolved stub, upstream NOT readable (svo-im's container, measured) → unknown",
     f("stub2", "nameserver 127.0.0.53\n"), os.path.join(TMP, "absent"), ([], False)),
    ("docker 127.0.0.11, host(…) servers are asked from the HOST namespace → no dependency",
     f("dock", "nameserver 127.0.0.11\noptions ndots:0\n\n# ExtServers: [host(1.1.1.1) host(8.8.8.8)]\n"), up, ([], True)),
    ("docker 127.0.0.11, a bare server is asked from the container → a dependency",
     f("dock2", "nameserver 127.0.0.11\n# ExtServers: [10.0.0.2 host(1.1.1.1)]\n"), up, (["10.0.0.2"], True)),
    ("docker 127.0.0.11 with no ExtServers line → unknown",
     f("dock3", "nameserver 127.0.0.11\n"), up, ([], False)),
    ("a local dnsmasq / unbound / pi-hole → unknown",
     f("local", "nameserver 127.0.0.1\n"), up, ([], False)),
    ("no nameserver line (glibc asks 127.0.0.1) → unknown",
     f("empty", "search lan\n"), up, ([], False)),
    ("v6-only servers → known, nothing a v4 route can shadow",
     f("v6", "nameserver 2001:db8::53\n"), up, ([], True)),
    ("resolv.conf unreadable → unknown", os.path.join(TMP, "nope"), up, ([], False)),
]
for name, path, ups, want in cases:
    got = N._resolvers(path, ups)
    check(name, got == want, (got, want))

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] default gateways — every device, and a failed read is None")
def hexle(ip):
    a = [int(x) for x in ip.split(".")]
    return "%02X%02X%02X%02X" % (a[3], a[2], a[1], a[0])
rt = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
      "lan0\t00000000\t%s\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
      "ppp0\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"          # gatewayless default: not a gateway
      "eth1\t00000000\t%s\t0003\t0\t0\t200\t00000000\t0\t0\t0\n"
      "lan0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n") % (hexle("192.168.1.1"), hexle("10.0.9.1"))
got = N._default_gateways(f("route", rt))
check("both gateways, host byte order decoded, the gatewayless default skipped",
      got == ["192.168.1.1", "10.0.9.1"], got)
check("an unreadable table is None — not 'no gateway'", N._default_gateways(os.path.join(TMP, "x")) is None)

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] refusal table")
LOCAL = [("lan0", "192.168.1.50", "192.168.1.0/24"),
         ("awg0", "10.8.0.1", "10.8.0.0/24"),
         ("swg_ab12cd34", "10.255.0.6", "10.255.0.6/31"),
         ("docker0", "172.17.0.1", "172.17.0.0/16")]
DEPS = dict(local=LOCAL, gateways=["192.168.1.1", "100.64.0.1"], panel=["203.0.113.10"],
            resolvers=["10.20.0.53"], resolvers_known=True)
table = [
    ("garbage", {}, ("invalid", "")),
    ("2001:db8::/64", {}, ("not_v4", "")),
    ("0.0.0.0/0", {}, ("default_route", "")),
    ("169.254.169.254/32", {}, ("reserved", "")),
    ("127.0.0.0/8", {}, ("reserved", "")),
    ("224.0.0.0/24", {}, ("reserved", "")),
    ("192.168.1.0/24", {}, ("node_lan", "192.168.1.50")),
    ("192.168.1.128/25", {}, ("node_lan", "192.168.1.50")),          # OVERLAP: half the LAN, no address inside
    ("172.17.5.0/24", {}, ("node_lan", "172.17.0.1")),              # a docker bridge the containers live on
    ("10.8.0.128/25", {}, ("iface_subnet", "10.8.0.1")),            # a slice of a tunnel strands that slice
    ("10.0.0.0/8", {}, ("iface_subnet", "10.8.0.1")),
    ("10.255.0.6/32", {}, ("mesh", "10.255.0.6")),
    ("100.64.0.0/24", {}, ("node_gateway", "100.64.0.1")),          # a gateway on no LAN the box sits on
    ("203.0.113.0/24", {}, ("node_panel", "203.0.113.10")),
    ("10.20.0.0/24", {}, ("node_resolver", "10.20.0.53")),
    ("10.50.0.0/24", {"panel": None}, ("panel_unknown", "")),
    ("10.50.0.0/24", {"resolvers_known": False}, ("resolver_unknown", "")),
    ("10.50.0.0/24", {}, (None, "")),
    ("10.50.0.5/32", {}, (None, "")),
]
for prefix, over, want in table:
    got = N.network_route_refusal(prefix, **dict(DEPS, **over))
    check("%-19s %s → %s" % (prefix, ("(" + ",".join(over) + ")") if over else "", want[0]), got == want, got)

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
class Kernel:
    """A main table and a longest-prefix `route get` — enough to show whether a route moves a path."""
    def __init__(self, routes):
        self.routes = dict(routes)                  # prefix → "via X dev D" | "dev D"
        self.calls = []
        self.batch_ok = True
    def get(self, a):
        best = None
        for p, path in self.routes.items():
            n = ipaddress.ip_network(p)
            if ipaddress.ip_address(a) in n and (best is None or n.prefixlen > best[0].prefixlen):
                best = (n, path)
        return best[1] if best else None
    def run(self, args, input_text=None, timeout=20):
        self.calls.append(list(args))
        CP = N.subprocess.CompletedProcess
        if args[:2] == ["ip", "-4"] and "-batch" in args:
            if not self.batch_ok:
                return CP(args, 1, "", "boom")
            out = []
            for ln in (input_text or "").splitlines():
                a = ln.split()[-1]
                path = self.get(a)
                if path:
                    out.append("%s %s src 192.168.1.50 uid 0 \n    cache " % (a, path))
            return CP(args, 0, "\n".join(out) + "\n", "")
        if args[:5] == ["ip", "-4", "route", "show", "exact"]:
            p = args[5]
            return CP(args, 0, ("%s %s\n" % (p, self.routes[p])) if p in self.routes else "", "")
        if args[:3] == ["ip", "route", "replace"]:
            self.routes[args[3]] = "dev " + args[5]
            return CP(args, 0, "", "")
        if args[:3] == ["ip", "route", "del"]:
            self.routes.pop(args[3], None)           # like the kernel: what `replace` displaced does NOT come back
            return CP(args, 0, "", "")
        if args[:3] == ["ip", "route", "add"]:
            if args[3] in self.routes:
                return CP(args, 2, "", "RTNETLINK answers: File exists")
            self.routes[args[3]] = " ".join(args[4:])
            return CP(args, 0, "", "")
        if args[:4] == ["ip", "-4", "-o", "addr"]:
            return CP(args, 0, "2: lan0    inet 192.168.1.50/24 brd 192.168.1.255 scope global lan0\n"
                               "3: wg0    inet 10.8.0.1/24 scope global wg0\n", "")
        return CP(args, 0, "", "")

print("\n[4] `ip -batch route get` parser")
K = Kernel({"0.0.0.0/0": "via 192.168.1.1 dev lan0", "192.168.1.0/24": "dev lan0"})
N.run = K.run
got = N._route_paths(["192.168.1.1", "203.0.113.10", "198.51.100.7"])
check("each address gets its path, `cache` continuation lines ignored",
      got.get("192.168.1.1") == "dev lan0" and got.get("203.0.113.10") == "via 192.168.1.1 dev lan0", got)
K.routes.pop("0.0.0.0/0")
got = N._route_paths(["198.51.100.7"])
check("an address with no route reads 'unreachable'", got == {"198.51.100.7": "unreachable"}, got)
_orig_run = N.run
N.run = lambda a, input_text=None, timeout=20: N.subprocess.CompletedProcess(
    a, 0, "local 192.168.1.50 dev lo table local src 192.168.1.50 uid 0 \n    cache <local> \n", "")
got = N._route_paths(["192.168.1.50"])
check("a `local` route is read past its type word", got == {"192.168.1.50": "local dev lo"}, got)
N.run = lambda a, input_text=None, timeout=20: N.subprocess.CompletedProcess(a, 1, "", "Cannot find device")
check("nothing readable at all → None, never 'every path unchanged'", N._route_paths(["192.168.1.1"]) is None)
check("no addresses → {} and no fork", N._route_paths([]) == {})

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] net_route_install — refuse, leave foreign routes alone, verify after apply")
RIG = {"0.0.0.0/0": "via 192.168.1.1 dev lan0", "192.168.1.0/24": "dev lan0", "10.8.0.0/24": "dev wg0"}
N._resolvers = lambda *a, **k: (["10.20.0.53"], True)
N._default_gateways = lambda *a, **k: ["192.168.1.1"]
N._PANEL_PEER["addr"] = "203.0.113.10"
if PERTURB:
    N._route_paths = lambda addrs: {}

def fresh(extra=None):
    k = Kernel(dict(RIG, **(extra or {})))
    N.run = k.run
    return k

k = fresh()
got = N.net_route_install("10.50.0.0/24", "wg0")
check("a harmless network installs and stays", got == (True, None, "") and k.routes.get("10.50.0.0/24") == "dev wg0", (got, k.routes))

k = fresh()
got = N.net_route_install("192.168.1.0/24", "wg0")
check("the node's own LAN is refused by the guard", got == (False, "node_lan", "192.168.1.50"), got)
check("…and no `replace` was ever issued", not any(c[:3] == ["ip", "route", "replace"] for c in k.calls), k.calls)

k = fresh({"10.60.0.0/24": "via 192.168.1.9 dev lan0"})
got = N.net_route_install("10.60.0.0/24", "wg0")
check("an exact route to ANOTHER device is left alone (`add` semantics for what is not ours)",
      got == (False, "route_exists", "lan0") and k.routes["10.60.0.0/24"] == "via 192.168.1.9 dev lan0", (got, k.routes))
k = fresh({"10.61.0.0/24": "dev wg0"})
got = N.net_route_install("10.61.0.0/24", "wg0")
check("…but one already on OUR device is re-asserted (wg-quick installs the same route, §4.4)", got[0] is True, got)

k = fresh()
got = N.net_route_install("192.168.1.0/24", "wg0", _guard=False)
check("GUARD BYPASSED: the stranding route is rolled back", got[:2] == (False, "rolled_back"), got)
check("…and the `del` that took it out was issued on wg0",
      ["ip", "route", "del", "192.168.1.0/24", "dev", "wg0"] in k.calls, k.calls)
check("…and the LAN route `replace` displaced is PUT BACK — `del` alone leaves it gone (measured on the rig)",
      k.routes.get("192.168.1.0/24") == "dev lan0", k.routes)
k2 = fresh()
N.net_route_install("10.20.0.0/24", "wg0", _guard=False)
check("GUARD BYPASSED: a route that only moves the RESOLVER is rolled back too",
      "10.20.0.0/24" not in k2.routes, k2.routes)
k3 = fresh()
N.net_route_install("203.0.113.10/32", "wg0", _guard=False)
check("GUARD BYPASSED: …and one that only moves the PANEL", "203.0.113.10/32" not in k3.routes, k3.routes)

k = fresh()
k.batch_ok = False
got = N.net_route_install("10.50.0.0/24", "wg0")
check("paths unreadable BEFORE → refused, nothing installed", got == (False, "verify_unreadable", "")
      and "10.50.0.0/24" not in k.routes, (got, k.routes))

# ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] D1 — the snapshot half forks nothing")
forks = []
N.run = lambda a, input_text=None, timeout=20: forks.append(a) or N.subprocess.CompletedProcess(a, 0, "", "")
d = N.net_deps()
check("net_deps() ran no subprocess", forks == [], forks)
check("net_deps() carries panel + resolvers + known + share (P5: this node enforces a restricted network) + reach (device access)",
      set(d) == {"panel", "resolvers", "resolvers_known", "share", "carried", "reach"} and d["share"] == 1 and d["carried"] == 1
      and d["reach"] == 1, d)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
