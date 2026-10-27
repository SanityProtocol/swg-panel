#!/usr/bin/env python3
"""Self-test — torrents via the device's own port (docs/P2P-OWN-ADDRESS-PLAN.md Part C; docs/RELEASE-1.8.11-PLAN.md § S12).

Where P2P leaves by the server's own address — node policy Direct, or an interface whose own choice is Direct — each
device gets an incoming port: `p2p_port` on the peer (pool 20000-29999, unique, stored), forwarded by the node's own
`ip swg_p2pfwd` table. A node without one keeps every table and sync reply it had.

  THE NODE (the REAL swg-noded)
    [1] _p2p_fwd_take — direct: every device outside the strict subnets; iface: only the Direct group's; block / route /
        legacy and a bridge-mode Docker node: none; v4 only, ports from 1024, one entry per device and per port
    [2] _p2p_nft's guard exemption (`ct status dnat iifname {wan} return`) under direct only while devices are forwarded —
        without them the text is today's (golden); iface and block never carry it
    [3] _ensure_p2p takes smart.p2p_fwd into _P2P["fwd"] and renders the exemption from it; reconcile_cascade hands the wire
        to it and then calls _ensure_p2pfwd with what it kept
    [4] _ensure_p2pfwd — each device's address is its interface's egress (SNAT source / MASQUERADE device / the WAN's); a
        port a listener holds on that address or a wildcard is left out and reported `taken`; the report by interface; the
        sig gates a second pass; nothing to forward deletes table and sig; a refused load deletes the old table
    [5] build_snapshot carries `p2p_fwd` only while something is reported
    [6] the real nft loads the table; on the real kernel (throwaway namespaces, `sudo -n`; SKIPPED without) beside the
        direct-mode guard: an inbound DHT query and a BitTorrent handshake reach the device, its replies leave from
        address:port by the WAN even where a whole-interface forward's `from S lookup T` would carry them into a mesh leg,
        and the device's own flow from its port leaves from that port
  THE PANEL
    [7] p2p_ports_fill — lowest free, sorted peer-id order, a duplicate or out-of-pool port reassigned, `first` claims first
    [8] (a REAL panel process) the start-up backfill; a create takes the lowest free; an update keeps it; a delete frees it
    [9] the wire: Block → no key (byte-identical); Direct → every wg/awg device here outside a Torrents-blocked interface,
        one per device (its primary target); per-interface → only a Direct interface's devices; keyless targets never
    [10] the pool is refused for a NEW listen port (interface create / port change), never for the one a record holds
  SWG-SUB
    [11] _p2p_fwd_of — the port only where the node reports the interface forwarded and not taken, on the device's chosen
        target (the panel's rule, twinned)

Run: python3 tests/p2p_fwd_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import ast, importlib.machinery, json, os, re, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2p_policy_selftest as base   # load, Box: the node's P2P gate harness

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PSRC = open(PANEL, encoding="utf-8").read()
SSRC = open(SUB, encoding="utf-8").read()
NSRC = base.SRC

PLANTS = {   # name: (file, old text, planted text)
    "take-strict":   ("node", "and (scope[0] is None or any(a in n for n in inn)) and not any(a in n for n in out)):",
                      "and (scope[0] is None or any(a in n for n in inn))):"),
    "take-anygroup": ("node", '[g["subnets"] for g in groups if g["name"] == "d"][:1]', '[[n for g in groups for n in g["subnets"]]]'),
    "take-block":    ("node", 'if mode == "iface" else [None] if mode == "direct" else [])', 'if mode == "iface" else [None])'),
    "take-dupport":  ("node", "a not in ips and p not in ports", "a not in ips"),
    "take-bridge":   ("node", '    if not scope or NODE_NET == "bridge" or not isinstance(fwd, list):', '    if not scope or not isinstance(fwd, list):'),
    "guard-always":  ("node", '        if fwdin and mode == "direct" and oif:', '        if mode == "direct" and oif:'),
    "guard-never":   ("node", '        if fwdin and mode == "direct" and oif:', '        if False:'),
    "fwd-unread":    ("node", '                fwd=(smart or {}).get("p2p_fwd"))', '                fwd=None)'),
    "fwd-uncalled":  ("node", '    _ensure_p2pfwd(_P2P["fwd"], node_cfg, res)\n', ''),
    "addr-wan":      ("node", '        addr = to.group(1) if to else v4.get(o.group(1) if o else "") or next(', '        addr = next('),
    "no-taken":      ("node", '                if any((h, p) in bound for h in (addr, "0.0.0.0", "*", "::")):', '                if False:'),
    "no-delete":     ("node", '                if run(["nft", "delete", "table", "ip", P2PFWD_TABLE]).returncode == 0:\n                    res["changed"] += 1',
                      '                if False:\n                    res["changed"] += 1'),
    "no-siggate":    ("node", '        if cur != sig or run(["nft", "-t", "list", "table", "ip", P2PFWD_TABLE]).returncode != 0:', '        if True:'),
    "fail-keeps":    ("node", '            if r.returncode != 0:                             # the old table would keep forwarding what it held: removed\n                run(["nft", "delete", "table", "ip", P2PFWD_TABLE])',
                      '            if r.returncode != 0:                             # the old table would keep forwarding what it held: removed\n                pass'),
    "snap-unsent":   ("node", '        snap["p2p_fwd"] = {i: dict(v) for i, v in _P2PFWD["report"].items()}', '        pass'),
    "no-rep":        ("node", '        "    ct direction reply ct status dnat ip saddr @fwds meta mark set %#x" % P2P_BIT, "  }",',
                      '        "    ct direction reply ct status dnat ip saddr @fwds", "  }",'),
    "no-post":       ("node", '        "    oifname { %s } meta l4proto { tcp, udp } snat to ip saddr . th sport map @out" % devs, "  }", "}"]',
                      '        "    oifname { %s } meta l4proto { tcp, udp } counter" % devs, "  }", "}"]'),
    "fill-dup":      ("panel", "        if type(v) is int and P2P_PORT_POOL[0] <= v <= P2P_PORT_POOL[1] and v not in used:",
                      "        if type(v) is int and P2P_PORT_POOL[0] <= v <= P2P_PORT_POOL[1]:"),
    "fill-first":    ("panel", "    for pid in sorted(peers, key=lambda k: (k not in first, k)):", "    for pid in sorted(peers):"),
    "fill-nostart":  ("panel", "        if p2p_ports_fill(_r):\n            roster_save(_rp, _r)", "        if False:\n            roster_save(_rp, _r)"),
    "set-dropped":   ("panel", '"routes", "share", "private", "router", "p2p_port"):', '"routes", "share", "private", "router"):'),
    "set-noalloc":   ("panel", "        if _free:                                             # pool full", "        if False:                                             # pool full"),
    "wire-block":    ("panel", '    d = ((plan or {}).get("_p2pi") or {}).get("direct") if pol == "iface" else None',
                      '    d = ((plan or {}).get("_p2pi") or {}).get("direct") if pol == "iface" else ["0.0.0.0/0"]'),
    "wire-strict":   ("panel", '        return ("direct", tuple(sorted(x for x, ids in (mech or {}).items() if "torrents" in (ids or ()))))',
                      '        return ("direct", ())'),
    "wire-both":     ("panel", "            out.append((min(ts)[2], port))", "            out += [(t_[2], port) for t_ in ts]"),
    "wire-firstif":  ("panel", '                    ts.append((_fp_role(t) != "primary", str(t.get("iface") or ""), a))',
                      '                    ts.append((False, str(t.get("iface") or ""), a))'),
    "wire-keyless":  ("panel", '            if not isinstance(t, dict) or t.get("node") != node_id or _is_self_contained_target(t):',
                      '            if not isinstance(t, dict) or t.get("node") != node_id:'),
    "wire-unwired":  ("panel", '**({"p2p_fwd": _fwd} if (_fwd := p2p_fwd_for_node(_rmark, roster, nid, p2p_fwd_scope(node, _blk_mech, my_plan))) else {}),', ''),
    "pool-open":     ("panel", "        if P2P_PORT_POOL[0] <= int(port) <= P2P_PORT_POOL[1] and str(port).strip() not in {str(k) for k in keep}:",
                      "        if False:"),
    "pool-nokeep":   ("panel", "        if P2P_PORT_POOL[0] <= int(port) <= P2P_PORT_POOL[1] and str(port).strip() not in {str(k) for k in keep}:",
                      "        if P2P_PORT_POOL[0] <= int(port) <= P2P_PORT_POOL[1]:"),
    "sub-taken":     ("sub", "    if type(port) is not int or not isinstance(e, dict) or port in (e.get(\"taken\") or ()):",
                      "    if type(port) is not int or not isinstance(e, dict):"),
    "sub-anytarget": ("sub", '    return {"p2p_port": port, "p2p_addr": str(e.get("addr") or "")} if mine and mine[1] == tg.get("iface") else {}',
                      '    return {"p2p_port": port, "p2p_addr": str(e.get("addr") or "")}'),
}


def key(c):
    return (c * 43)[:43] + "="


# [6] three throwaway namespaces: remote X 192.0.2.9 ──veth── this router R (eth0 192.0.2.1, the WAN) ──veth── device C
# 10.9.0.2. R holds the direct-mode swg_p2p ($1), this table ($2), rule 6880 (P2P_BIT → main) and a whole-interface forward's
# `from 10.9.0.0/24 lookup 7001` whose default is a mesh leg (a dummy, counting what it sends). None = could not set up.
WIRE_FWD = r'''
set -u
ip link set lo up
unshare -n sleep 30 & CPID=$!
unshare -n sleep 30 & XPID=$!
sleep 0.3
ip link add vr type veth peer name vc && ip link set vc netns $CPID && ip addr add 10.9.0.1/24 dev vr && ip link set vr up \
 && ip link add eth0 type veth peer name vx && ip link set vx netns $XPID && ip addr add 192.0.2.1/24 dev eth0 && ip link set eth0 up \
 && ip route add default via 192.0.2.9 dev eth0 && sysctl -qw net.ipv4.ip_forward=1 \
 && nsenter -t $CPID -n sh -c 'ip link set lo up; ip addr add 10.9.0.2/24 dev vc; ip link set vc up; ip route add default via 10.9.0.1' \
 && nsenter -t $XPID -n sh -c 'ip link set lo up; ip addr add 192.0.2.9/24 dev vx; ip link set vx up' \
 && ip rule add fwmark 0x40000000 lookup main pref 6880 \
 && ip rule add from 10.9.0.0/24 lookup 7001 pref 7001 \
 && ip link add mesh0 type dummy && ip link set mesh0 up && ip route add default dev mesh0 table 7001 \
 || { echo SETUP-FAILED net; kill $CPID $XPID; exit 0; }
sleep 1
nft -f "$1" || { echo SETUP-FAILED p2p; kill $CPID $XPID; exit 0; }
nft -f "$2" || { echo LOADED no; kill $CPID $XPID; exit 0; }
echo LOADED yes
OUT=$(mktemp)
nsenter -t $CPID -n timeout 6 python3 -u -c '
import socket, select, os, time
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("10.9.0.2", 20016))
t = socket.socket(); t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); t.bind(("10.9.0.2", 20016)); t.listen(4)
end = time.time() + 2.5
while time.time() < end:
    r, _, _ = select.select([u, t], [], [], 0.2)
    if u in r:
        d, a = u.recvfrom(2048); print("C_UDP", a[0]); u.sendto(b"d1:rd2:id20:" + os.urandom(20) + b"e1:t2:aa1:y1:re", a)
    if t in r:
        c, a = t.accept(); c.settimeout(1)
        try:
            d = c.recv(100); print("C_TCP", a[0]); c.sendall(b"\x13BitTorrent protocol" + b"\0" * 48)
        except Exception as e:
            print("C_TCPERR", type(e).__name__)
u.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"9:info_hash20:" + os.urandom(20) + b"e1:q9:get_peers1:t2:aa1:y1:qe", ("192.0.2.9", 5000))
' > "$OUT" 2>&1 &
sleep 0.5
nsenter -t $XPID -n timeout 6 python3 -c '
import socket, os
o = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); o.bind(("192.0.2.9", 5000)); o.settimeout(3)
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(1)
u.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"e1:q4:ping1:t2:aa1:y1:qe", ("192.0.2.1", 20016))
try:
    print("X_UDP %s:%d" % u.recvfrom(2048)[1])
except Exception:
    print("X_UDP none")
t = socket.socket(); t.settimeout(1.5)
try:
    t.connect(("192.0.2.1", 20016)); t.sendall(b"\x13BitTorrent protocol" + b"\0" * 48); print("X_TCP %d" % len(t.recv(100)))
except Exception as e:
    print("X_TCP none")
try:
    print("X_OWN %s:%d" % o.recvfrom(2048)[1])
except Exception:
    print("X_OWN none")
'
sleep 0.5
cat "$OUT"; rm -f "$OUT"
echo "DROPPED $(nft list counter inet swg_p2p dropped | grep -o 'packets [0-9]*' | grep -o '[0-9]*')"
kill $CPID $XPID 2>/dev/null
'''


def _wire(p2p, fwd):
    fs = []
    for t in (p2p, fwd):
        with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
            f.write(t)
        fs.append(f.name)
    try:
        r = subprocess.run(["sudo", "-n", "unshare", "-n", "bash", "-s"] + fs, input=WIRE_FWD, capture_output=True, text=True, timeout=90)
    except Exception:
        return None
    finally:
        for f in fs:
            os.unlink(f)
    out = {}
    for ln in (r.stdout or "").splitlines():
        if " " in ln:
            out.setdefault(ln.split(" ", 1)[0], ln.split(" ", 1)[1].strip())
    return out


class FwdBox:
    """The few reads _ensure_p2pfwd makes, and what it ran."""
    NAT = ['-A POSTROUTING -s 10.8.0.0/24 -o eth0 -m comment --comment swg-egress:wg0 -j SNAT --to-source 198.51.100.7',
           '-A POSTROUTING -s 10.9.0.0/24 -o eth1 -m comment --comment "swg-egress:wg1" -j MASQUERADE']
    ADDR = ("1: lo    inet 127.0.0.1/8 scope host lo\n2: eth0    inet 192.0.2.1/24 brd 192.0.2.255 scope global eth0\n"
            "2: eth0    inet 192.0.2.77/24 scope global secondary eth0\n3: eth1@if9    inet 203.0.113.5/24 scope global eth1\n")
    SS = ("udp   UNCONN 0 0 0.0.0.0:51820 0.0.0.0:*\nudp   UNCONN 0 0 0.0.0.0:20001 0.0.0.0:*\n"
          "tcp   LISTEN 0 4096 192.0.2.1:20003 0.0.0.0:*\ntcp   LISTEN 0 4096 192.0.2.77:20004 0.0.0.0:*\ntcp   LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*\n")

    def __init__(self, refuse=False):
        self.cmds, self.table, self.refuse = [], None, refuse

    def run(self, args, input_text=None, timeout=20):
        a = list(args); self.cmds.append((a, input_text)); out, rc = "", 0
        if a[:4] == ["iptables", "-t", "nat", "-S"]:
            out = "\n".join(self.NAT) + "\n"
        elif a[:4] == ["ip", "-4", "-o", "addr"]:
            out = self.ADDR
        elif a[:2] == ["ss", "-Hlntu"]:
            out = self.SS
        elif a[:4] == ["ip", "route", "show", "default"]:
            out = "default via 192.0.2.254 dev eth0 proto static\n"
        elif a[:2] == ["nft", "-f"]:
            if self.refuse:
                rc = 1
            else:
                self.table = input_text
        elif a[:4] == ["nft", "-t", "list", "table"]:
            rc = 0 if self.table else 1
        elif a[:3] == ["nft", "delete", "table"]:
            self.table = None
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="refused" if rc else "")

    def loads(self):
        return [i for a, i in self.cmds if a[:2] == ["nft", "-f"]]


def node_checks(src, ok):
    m = base.load(src)
    # [1]
    F = [["10.8.0.2", 20000], ["10.8.0.3", 20001], ["10.7.0.4", 20002], ["10.9.0.5", 20003], ["10.8.0.2", 20004],
         ["10.8.0.6", 20000], ["10.8.0.7", 80], ["fd00::7", 20005], "junk", ["10.8.0.9"], ["x", 1]]
    g = lambda d: [{"name": "d", "subnets": d, "mark": 0x40000000, "oif": ["eth0"], "table": None},
                   {"name": "r7001", "subnets": ["10.9.0.0/24"], "mark": 0x40001b59, "oif": ["wgx"], "table": 7001}]
    got = m._p2p_fwd_take(F, "direct", ["10.7.0.0/24"], [])
    ok(got == [("10.8.0.2", 20000), ("10.8.0.3", 20001), ("10.9.0.5", 20003)],
       "[1] direct: outside strict; one entry per device and per port; v4, ports from 1024; junk skipped (%s)" % got)
    got = m._p2p_fwd_take(F, "iface", [], g(["10.8.0.0/24"]))
    ok(got == [("10.8.0.2", 20000), ("10.8.0.3", 20001)], "[1] iface: only the Direct group's devices — not a route group's (%s)" % got)
    ok(m._p2p_fwd_take(F, "iface", [], g([])[1:]) == [], "[1] iface with no Direct group: none")
    ok(all(m._p2p_fwd_take(F, md, [], []) == [] for md in ("block", "route", "legacy")), "[1] block / route / legacy: none")
    ok(m._p2p_fwd_take(None, "direct", [], []) == [] and m._p2p_fwd_take("10.8.0.2", "direct", [], []) == [], "[1] absent / not a list: none")
    m.NODE_NET = "bridge"
    ok(m._p2p_fwd_take(F, "direct", [], []) == [], "[1] a bridge-mode Docker node: none (the host's address is not its own)")
    m.NODE_NET = "host"
    # [2]
    d0, d1 = m._p2p_nft("direct", [], ["eth0"], [], True), m._p2p_nft("direct", [], ["eth0"], [], True, fwdin=True)
    line = '    ct status dnat iifname { "eth0" } return'
    ok(line in d1 and line not in d0 and d1.replace(line + "\n", "") == d0,
       "[2] direct: the exemption only while devices are forwarded — otherwise today's text exactly")
    ok(line in d1 and d1.index(line) > d1.index("chain guard") and d1.index(line) == d1.index("    ct direction reply return", d1.index("chain guard")) + len("    ct direction reply return\n"),
       "[2] …right after the guard's `ct direction reply return`")
    grp = g(["10.8.0.0/24"])
    ok(m._p2p_nft("iface", [], [], [], True, groups=grp, fwdin=True) == m._p2p_nft("iface", [], [], [], True, groups=grp)
       and m._p2p_nft("block", [], [], [], True, fwdin=True) == m._p2p_nft("block", [], [], [], True),
       "[2] iface and block never carry it (iface's guard judges only its groups' sources)")
    # [3]
    def ensure(p2p, fwd, mech=None):
        mm = base.load(src); b = base.Box()
        mm.run = b.run; mm.GEO_DIR = tempfile.mkdtemp(); mm._relay_links = lambda cfg: ()
        mm._ensure_p2p(p2p, mech or {}, {}, {"changed": 0, "errors": []}, fwd=fwd)
        return mm._P2P["fwd"], b.tables.get("swg_p2p") or ""
    kept, tbl = ensure({"action": "direct"}, [["10.8.0.2", 20000]])
    ok(kept == [("10.8.0.2", 20000)] and line in tbl, "[3] direct + a device: kept, and the guard exempts DNAT'd arrivals (%s)" % kept)
    kept, tbl0 = ensure({"action": "direct"}, None)
    ok(kept == [] and line not in tbl0, "[3] direct, no wire: nothing kept, the text as before")
    kept, _ = ensure({"action": "block"}, [["10.8.0.2", 20000]])
    ok(kept == [], "[3] block: the wire is not taken")
    kept, _ = ensure({"action": "direct"}, [["10.8.0.2", 20000]], {"10.8.0.0/24": ["torrents"]})
    ok(kept == [], "[3] direct, the device on a Torrents-blocked interface: not taken")
    seen = []
    m2 = base.load(src)
    m2.run = lambda a, input_text=None, timeout=20: types.SimpleNamespace(returncode=0, stdout="", stderr="")
    m2.GEO_DIR = tempfile.mkdtemp()
    for fn in ("_ensure_fwd_iptables", "_ensure_sni_router", "_ensure_smart_xtstring", "reconcile_catk_chain", "_ensure_smart_dnsmasq",
               "_dnsmasq_refill", "_ensure_doh_block", "_ensure_mech_block", "_smart_geo_refresh", "_smart_load_cidrs",
               "_panel_list_refresh", "_apply_routing_reset", "_smart_domain_refresh"):
        setattr(m2, fn, (lambda *a, **k: ({}, {})) if fn == "_smart_domain_refresh" else (lambda *a, **k: None))
    m2._ensure_smart_nft = lambda *a, **k: {}
    m2._cascade_local_routes = lambda cfg, _proc=None: []
    def fake_p2p(*a, **k):
        seen.append(("p2p", k.get("fwd"))); m2._P2P["fwd"] = [("10.8.0.2", 20000)]
    m2._ensure_p2p = fake_p2p
    m2._ensure_p2pfwd = lambda fwd, cfg, res: seen.append(("fwd", fwd))
    m2.reconcile_cascade({"interfaces": {}}, {}, {"entries": [], "p2p": None, "p2p_fwd": [["10.8.0.2", 20000]]})
    ok(seen == [("p2p", [["10.8.0.2", 20000]]), ("fwd", [("10.8.0.2", 20000)])],
       "[3] reconcile_cascade hands smart.p2p_fwd to _ensure_p2p, then what it kept to _ensure_p2pfwd (%s)" % seen)
    # [4]
    def fwd_pass(fwd, box=None, mm=None):
        mm = mm or base.load(src); b = box or FwdBox()
        mm.run = b.run; mm.GEO_DIR = mm.GEO_DIR if mm.GEO_DIR.startswith(tempfile.gettempdir()) else tempfile.mkdtemp()
        subs = {"wg0": "10.8.0.0/24", "wg1": "10.9.0.0/24", "wg2": "10.10.0.0/24"}
        mm._iface_subnet = lambda cfg, i: subs.get(i, "")
        res = {"changed": 0, "errors": []}
        mm._ensure_p2pfwd(fwd, {"interfaces": {i: {} for i in subs}}, res)
        return mm, b, res
    FW = [("10.8.0.2", 20000), ("10.8.0.3", 20001), ("10.9.0.2", 20002), ("10.10.0.2", 20003), ("10.10.0.4", 20004), ("10.6.0.2", 20005)]
    mm, b, res = fwd_pass(FW)
    t = b.table or ""
    ok("10.8.0.2 . 20000 : 198.51.100.7 . 20000" in t and "203.0.113.5 . 20002 : 10.9.0.2" in t and "192.0.2.1 . 20004 : 10.10.0.4" in t,
       "[4] each device's address is its interface's egress: SNAT source, MASQUERADE device, else the WAN's first address")
    ok("20001" not in t and "20003" not in t and "20005" not in t,
       "[4] a port a listener holds (wildcard, or bound on that address) is left out; a device on no interface here too")
    ok("192.0.2.1 . 20004 : 10.10.0.4" in t, "[4] …a port bound on ANOTHER address of the box is not taken")
    ok(mm._P2PFWD["report"] == {"wg0": {"addr": "198.51.100.7", "taken": [20001]}, "wg1": {"addr": "203.0.113.5", "taken": []},
                                "wg2": {"addr": "192.0.2.1", "taken": [20003]}},
       "[4] the report by interface: the address and the ports taken (%s)" % mm._P2PFWD["report"])
    ok('iifname { "eth0" }' in t and 'oifname { "eth0" }' in t and "meta mark set 0x40000000" in t and not res["errors"],
       "[4] in by the WAN, out by the WAN, the replies marked for rule 6880 (%s)" % res["errors"])
    n = len(b.loads())
    fwd_pass(FW, b, mm)
    ok(n == 1 and len(b.loads()) == 1, "[4] the same set again: no reload (sig) (%d → %d)" % (n, len(b.loads())))
    fwd_pass([], b, mm)
    ok(b.table is None and not os.path.exists(os.path.join(mm.GEO_DIR, ".p2pfwd.sig")) and mm._P2PFWD["report"] == {},
       "[4] nothing to forward: the table and its sig deleted, nothing reported")
    mm2, b2, _ = fwd_pass(FW)
    b2.refuse = True
    mm2.GEO_DIR = tempfile.mkdtemp()                           # a new sig: the reload is asked, and refused
    res2 = fwd_pass(FW[:1], b2, mm2)[2]
    ok(b2.table is None and mm2._P2PFWD["report"] == {} and res2["errors"], "[4] a refused load deletes the old table — nothing stale forwarded")
    # [5]
    bs = src[src.index("\ndef build_snapshot("):src.index("\ndef ", src.index("\ndef build_snapshot(") + 10)]
    ok(re.search(r'if _P2PFWD\["report"\]:[^\n]*\n\s+snap\["p2p_fwd"\] = \{i: dict\(v\) for i, v in _P2PFWD\["report"\]\.items\(\)\}', bs),
       "[5] build_snapshot sends p2p_fwd, only while something is reported")
    # [6]
    if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
        print("  SKIPPED [6] real nft / kernel — no `sudo -n` here")
        return
    out = _wire(m._p2p_nft("direct", [], ["eth0"], [], True, fwdin=True), m._p2pfwd_nft([("10.9.0.2", 20016, "192.0.2.1")], ["eth0"]))
    if not out or out.get("LOADED") is None:
        print("  SKIPPED [6] real kernel — the throwaway namespaces could not be set up here (%s)" % out)
        return
    ok(out.get("LOADED") == "yes", "[6] the table loads on the real nft")
    ok(out.get("C_UDP") == "192.0.2.9" and out.get("X_UDP") == "192.0.2.1:20016",
       "[6] an inbound DHT query reaches the device; its answer leaves from address:port by the WAN, not the mesh leg (%s %s)"
       % (out.get("C_UDP"), out.get("X_UDP")))
    ok(out.get("C_TCP") == "192.0.2.9" and out.get("X_TCP") == "68", "[6] an inbound BitTorrent handshake reaches it and is answered (%s %s)"
       % (out.get("C_TCP"), out.get("X_TCP")))
    ok(out.get("X_OWN") == "192.0.2.1:20016", "[6] the device's own flow from its port leaves from that port (%s)" % out.get("X_OWN"))
    ok(out.get("DROPPED") == "0", "[6] the guard dropped nothing (%s)" % out.get("DROPPED"))


ROSTER = {"version": 1, "users": {"u1": {"id": "u1", "name": "anna"}}, "peers": {
    "pa": {"id": "pa", "user_id": "u1", "pubkey": key("a"), "psk": key("q"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.2/32", "type": "wg"}]},
    "pb": {"id": "pb", "user_id": "u1", "pubkey": key("b"), "psk": key("q"), "p2p_port": 20000,
           "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.3/32", "type": "wg"}]},
    "pc": {"id": "pc", "user_id": "u1", "pubkey": key("c"), "psk": key("q"), "p2p_port": 20000,
           "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.3/32", "type": "wg"}]},
    "pd": {"id": "pd", "user_id": "u1", "pubkey": key("d"), "psk": key("q"), "p2p_port": 5,
           "targets": [{"node": "n2", "iface": "wg0", "ip": "10.7.0.4/32", "type": "wg"}]},
    "pe": {"id": "pe", "user_id": "u1", "pubkey": key("e"), "psk": key("q"),
           "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5/32", "type": "wg"},
                       {"node": "n1", "iface": "wg1", "ip": "10.9.0.5/32", "type": "wg", "primary": "primary"}]},
    "pf": {"id": "pf", "user_id": "u1", "csqtt_password": "pw", "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt", "ip": "10.8.0.50"}]}}}
WANT = {"pa": 20001, "pb": 20000, "pc": 20002, "pd": 20003, "pe": 20004, "pf": 20005}


def unit_checks(src, ok):
    m = types.ModuleType("swgpanel_fwd"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    r = json.loads(json.dumps(ROSTER))
    ch = m.p2p_ports_fill(r)
    got = {k: v.get("p2p_port") for k, v in r["peers"].items()}
    ok(ch and got == WANT, "[7] lowest free, sorted peer-id order; the later duplicate and the out-of-pool port reassigned (%s)" % got)
    ok(not m.p2p_ports_fill(r), "[7] a second fill changes nothing")
    r2 = {"peers": {"a1": {"p2p_port": 20000}, "zz": {"p2p_port": 20000}}}
    m.p2p_ports_fill(r2, first={"zz"})
    ok(r2["peers"]["zz"]["p2p_port"] == 20000 and r2["peers"]["a1"]["p2p_port"] == 20001,
       "[7] `first` (this panel's own peers) keep their port; an arriving one is reassigned (%s)" % r2)
    full = {"peers": {"p%05d" % i: {"p2p_port": 20000 + i} for i in range(10000)}}
    full["peers"]["zzz"] = {}
    m.p2p_ports_fill(full)
    ok("p2p_port" not in full["peers"]["zzz"], "[7] the pool full: the device gets no port")


def panel_checks(src, ok):
    tmp = tempfile.mkdtemp(prefix="p2p-fwd-")
    server = os.path.join(tmp, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src)
    state = os.path.join(tmp, "state"); os.makedirs(state); stats = os.path.join(tmp, "stats"); os.makedirs(stats)
    nodes, users = os.path.join(state, "nodes.json"), os.path.join(state, "users.json")
    json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}, "wg1": {}}},
               "n2": {"id": "n2", "name": "node-b", "ifaces": {"wg0": {}}}}, open(nodes, "w"))
    json.dump(ROSTER, open(users, "w"))
    fleet = os.path.join(tmp, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": users, "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(os.path.join(tmp, "panel.log"), "w+")
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                 "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                 "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

    def req(path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                                   headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    meta = lambda sub, lp: {"subnet": sub, "listen_port": lp, "public_key": key("Z"), "address": sub.replace("0/24", "1/24")}
    snap1 = {"hostname": "node-a", "generated_at": 0, "noded_version": "t",
             "interfaces": {"wg0": {"peers": [], "meta": meta("10.8.0.0/24", 51820)}, "wg1": {"peers": [], "meta": meta("10.9.0.0/24", 51821)}}}
    snap2 = {"hostname": "node-b", "generated_at": 0, "noded_version": "t", "interfaces": {"wg0": {"peers": [], "meta": meta("10.7.0.0/24", 51820)}}}

    def wire(tok, snap):
        c, r = req("/api/node/sync", {"snapshot": dict(snap, generated_at=int(time.time()))}, tok)
        return (r.get("smart") or {}).get("p2p_fwd", "ABSENT") if c == 200 else "SYNC %s" % c

    ports = lambda: {k: v.get("p2p_port") for k, v in json.load(open(users))["peers"].items()}
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    ok(False, "the panel started (%s)" % open(log.name).read()[-600:]); return
                time.sleep(0.1)
        # [8]
        ok(ports() == WANT, "[8] the start-up backfill gave every device a port, the duplicate and the stray reassigned (%s)" % ports())
        t1 = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
        t2 = req("/api/nodes/rotate", {"id": "n2"})[1]["data"]["token"]
        # [9] Block (the default): no key
        ok(wire(t1, snap1) == "ABSENT" and wire(t2, snap2) == "ABSENT", "[9] Block: no p2p_fwd on the wire (byte-identical)")
        c, r = req("/api/peers/create", {"pubkey": key("g"), "user_id": "u1", "title": "g", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.7"}]})
        pg = ((r.get("data") or {}).get("peer") or r.get("data") or {}).get("id")
        ok(c == 200 and ports().get(pg) == 20006, "[8] a create takes the lowest free port (%s %s)" % (c, ports().get(pg)))
        req("/api/peers/update", {"peer_id": "pa", "title": "renamed"})
        req("/api/peers/update-target", {"peer_id": "pa", "node": "n1", "iface": "wg0", "overrides": {"mtu": 1380}})
        ok(ports().get("pa") == 20001, "[8] an update and a target's settings keep it (%s)" % ports().get("pa"))
        c0, _r = req("/api/peers/unassign", {"peer_id": "pb"})
        ok(c0 == 200 and ports().get("pb") == 20000, "[8] an unassign (a PSK rotation) keeps it (%s %s)" % (c0, ports().get("pb")))
        c, r = req("/api/peers/delete", {"peer_id": "pb"})
        req("/api/peers/update", {"peer_id": "pa", "title": "renamed again"})
        ok(ports().get("pa") == 20001, "[8] a save after a lower port came free keeps the device's own (%s)" % ports().get("pa"))
        c2, r2 = req("/api/peers/create", {"pubkey": key("h"), "user_id": "u1", "title": "h", "targets": [{"node": "n2", "iface": "wg0", "ip": "10.7.0.8"}]})
        ph = ((r2.get("data") or {}).get("peer") or r2.get("data") or {}).get("id")
        ok(c == 200 and ports().get(ph) == 20000, "[8] a delete frees its port for the next device (%s %s)" % (c, ports().get(ph)))
        # [9] Direct on n1
        c, r = req("/api/nodes/update", {"id": "n1", "p2p": {"action": "direct"}})
        got = wire(t1, snap1)
        ok(c == 200 and got == [["10.8.0.2", 20001], ["10.8.0.7", 20006], ["10.9.0.3", 20002], ["10.9.0.5", 20004]],
           "[9] Direct: every wg/awg device here, one per device (pe's primary wg1), the keyless one never (%s)" % (got,))
        ok(wire(t2, snap2) == "ABSENT", "[9] …only on the Direct node")
        c, r = req("/api/iface/update", {"node": "n1", "iface": "wg1", "block": ["torrents"]})
        got = wire(t1, snap1)
        ok(c == 200 and got == [["10.8.0.2", 20001], ["10.8.0.5", 20004], ["10.8.0.7", 20006]],
           "[9] wg1 blocks torrents: its devices left out — pe falls back to its wg0 target (%s %s)" % (c, got))
        # [9] per-interface: only wg0's own Direct choice
        req("/api/iface/update", {"node": "n1", "iface": "wg1", "block": []})
        c, r = req("/api/nodes/update", {"id": "n1", "p2p": {"action": "iface"}})
        ok(wire(t1, snap1) == "ABSENT", "[9] per-interface with no Direct record: no key")
        c, r = req("/api/iface/update", {"node": "n1", "iface": "wg0", "p2p": {"action": "direct"}})
        got = wire(t1, snap1)
        ok(c == 200 and got == [["10.8.0.2", 20001], ["10.8.0.5", 20004], ["10.8.0.7", 20006]],
           "[9] per-interface: only the Direct interface's devices (%s %s)" % (c, got))
        # [10]
        c, r = req("/api/iface/create", {"node": "n1", "iface": "wg5", "subnet": "10.55.0.0/24", "listen_port": 20500})
        ok(c == 400 and "20000–29999" in json.dumps(r, ensure_ascii=False), "[10] a new interface on a pool port is refused (%s %s)" % (c, str(r)[:120]))
        c, r = req("/api/iface/update", {"node": "n1", "iface": "wg0", "listen_port": 21000})
        ok(c == 400, "[10] moving an interface onto a pool port is refused (%s)" % c)
        _n = json.load(open(nodes)); _n["n1"]["ifaces"]["wg1"]["listen_port"] = 21001; json.dump(_n, open(nodes, "w"))
        req("/api/nodes/update", {"id": "n1", "name": "node-a"})   # (the panel re-reads its store on a save path)
        c, r = req("/api/iface/update", {"node": "n1", "iface": "wg0", "listen_port": 51820})
        ok(c == 200, "[10] a port outside the pool saves (%s %s)" % (c, str(r)[:120]))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


def keep_checks(src, ok):
    """[10] the one a record already holds: reserved_conflict with `keep` (the interface-update path passes its own)."""
    m = types.ModuleType("swgpanel_fwd2"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    rc = lambda p, keep=(): m.reserved_conflict({}, {}, {}, port=p, keep=keep)
    ok(rc(20500) and rc("29999") and not rc(19999) and not rc(30000), "[10] the pool is 20000-29999, nothing around it")
    ok(not rc(20500, keep=[20500, None]) and not rc("20500", keep=["20500"]), "[10] the port a record already holds is never refused")


def sub_checks(src, psrc, ok):
    S = types.ModuleType("swgsub_fwd"); S.__file__ = SUB
    exec(compile(src, SUB, "exec"), S.__dict__)
    P = types.ModuleType("swgpanel_fwd3"); P.__file__ = PANEL
    exec(compile(psrc, PANEL, "exec"), P.__dict__)
    peer = {"p2p_port": 20004, "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5/32"},
                                           {"node": "n1", "iface": "wg1", "ip": "10.9.0.5/32", "primary": "primary"},
                                           {"node": "n2", "iface": "wg0", "ip": "10.7.0.5/32"}]}
    tg = lambda n, i: {"node": n, "iface": i}
    d = {"n1": {"p2p_fwd": {"wg0": {"addr": "198.51.100.7", "taken": []}, "wg1": {"addr": "203.0.113.5", "taken": []}}},
         "n2": {"p2p_fwd": {"wg0": {"addr": "192.0.2.1", "taken": [20004]}}}}
    got = [S._p2p_fwd_of(peer, tg(n, i), d) for n, i in (("n1", "wg0"), ("n1", "wg1"), ("n2", "wg0"))]
    ok(got == [{}, {"p2p_port": 20004, "p2p_addr": "203.0.113.5"}, {}],
       "[11] the port on the device's chosen target (primary wg1), never its other one there, nor where it is taken (%s)" % got)
    d1 = {"n1": {"p2p_fwd": {"wg0": {"addr": "198.51.100.7", "taken": []}}}}
    got = [S._p2p_fwd_of(peer, tg("n1", i), d1) for i in ("wg0", "wg1")]
    ok(got == [{"p2p_port": 20004, "p2p_addr": "198.51.100.7"}, {}], "[11] wg1 not forwarded there: the wg0 target carries it (%s)" % got)
    ok(S._p2p_fwd_of(peer, tg("n1", "wg1"), {}) == {} and S._p2p_fwd_of({"targets": peer["targets"]}, tg("n1", "wg1"), d) == {},
       "[11] an older node (no report) or a device with no port: nothing")
    # the twin: the panel forwards the same target swg-sub names (node reports the interfaces of its scope)
    r = {"peers": {"p": dict(peer)}}
    for scope, rep in ((("direct", ()), d["n1"]["p2p_fwd"]), (("iface", ("10.8.0.0/24",)), d1["n1"]["p2p_fwd"])):
        w = P.p2p_fwd_for_node(None, r, "n1", scope)
        s_ = [i for i in ("wg0", "wg1") if S._p2p_fwd_of(peer, tg("n1", i), {"n1": {"p2p_fwd": rep}})]
        ip = {"wg0": "10.8.0.5", "wg1": "10.9.0.5"}
        ok(w == [[ip[s_[0]], 20004]] if len(s_) == 1 else False, "[11] the twin: the panel forwards the target the page names (%s | %s)" % (w, s_))


def run_checks(psrc, nsrc, ssrc):
    fails = []
    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
    node_checks(nsrc, ok)
    unit_checks(psrc, ok)
    keep_checks(psrc, ok)
    sub_checks(ssrc, psrc, ok)
    panel_checks(psrc, ok)
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
        for name, (which, old, new) in PLANTS.items():
            if only and name not in only:
                continue
            src = {"panel": PSRC, "node": NSRC, "sub": SSRC}[which]
            if src.count(old) != 1:
                print("PLANT %-14s anchor missing — fix the plant" % name); missed.append(name); continue
            p = src.replace(old, new)
            f = run_checks(*{"panel": (p, NSRC, SSRC), "node": (PSRC, p, SSRC), "sub": (PSRC, NSRC, p)}[which])
            print("PLANT %-14s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC, NSRC, SSRC)
    print("p2p_fwd_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
