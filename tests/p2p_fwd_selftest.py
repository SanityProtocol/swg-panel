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
    "addr-wan":      ("node", '                    addr_of[ifn] = to.group(1) if to else v4.get(o.group(1) if o else "") or wa', '                    addr_of[ifn] = wa'),
    "addr-oldparse": ("node", '            for d, a in _node_addrs():\n                if not a.startswith("169.254."):',
                      '            for d, a in re.findall(r"\\d+:\\s+([^\\s@]+)\\S*\\s+inet\\s+([\\d.]+)/", run(["ip", "-4", "-o", "addr", "show"]).stdout or ""):\n                if True:'),
    "addr-sorted":   ("node", '            wa = v4.get(_detect_wan()) or next(', '            wa = next('),
    "ifdown":        ("node", '                    if _dev_link_state(ifn) == "up":\n', '                    if True:\n'),
    "no-taken":      ("node", '                if any((h, p) in bound for h in (addr_of[ifn], "0.0.0.0", "*", "::")):', '                if False:'),
    "no-delete":     ("node", '            if _P2PFWD["loaded"] or os.path.exists(sigf):     # forwarded asks nothing', '            if False:     # forwarded asks nothing'),
    "no-retry":      ("node", '                if r.returncode == 0 or "No such file" in (r.stderr or ""):', '                if True:'),
    "no-siggate":    ("node", '        if cur_sig != sig or have.returncode != 0 or not re.search(', '        if True or not re.search('),
    "exists-only":   ("node", '        if cur_sig != sig or have.returncode != 0 or not re.search(', '        if cur_sig != sig or have.returncode != 0 or False and not re.search('),
    "fail-keeps":    ("node", '            if r.returncode != 0:                             # the old table would keep forwarding what it held: removed\n                run(["nft", "delete", "table", "ip", P2PFWD_TABLE])',
                      '            if r.returncode != 0:                             # the old table would keep forwarding what it held: removed\n                pass'),
    "snap-unsent":   ("node", '        snap["p2p_fwd"] = {i: dict(v) for i, v in _P2PFWD["report"].items()}', '        pass'),
    "no-rep":        ("node", '        L.append("    ct direction reply ct status dnat ip saddr @fwds meta mark set %#x" % P2P_BIT)',
                      '        L.append("    ct direction reply ct status dnat ip saddr @fwds")'),
    "no-post":       ("node", '              "    oifname { %s } meta l4proto { tcp, udp } snat to ip saddr . th sport map @out" % devs, "  }"]',
                      '              "    oifname { %s } meta l4proto { tcp, udp } counter" % devs, "  }"]'),
    "rep-prio":      ("node", '"    type filter hook prerouting priority mangle + 7; policy accept;"]', '"    type filter hook prerouting priority mangle + 6; policy accept;"]'),
    "prio-first":    ("node", '"    type nat hook prerouting priority dstnat + 5; policy accept;",', '"    type nat hook prerouting priority dstnat - 5; policy accept;",'),
    "map-type":      ("node", '"  map in { typeof ip daddr . th dport : ip daddr; elements', '"  map in { type ipv4_addr . inet_service : ipv4_addr; elements'),
    "state-unread":  ("node", '        if not _P2PFWD["read"]:                               # once a process', '        if False:                               # once a process'),
    "state-failforget": ("node", '                _p2pfwd_keep(statef, (), {**gone, **{k: now + P2PFWD_DRAIN_S for k in _P2PFWD["rows"] | cur}})',
                      '                _p2pfwd_keep(statef, (), {})'),
    "fail-twice":    ("node", '{k: now + P2PFWD_DRAIN_S for k in _P2PFWD["rows"] | cur}', '{k: now + P2PFWD_DRAIN_S for k in _P2PFWD["rows"]}'),
    "inforce-anydnat": ("node", 'r"\\bdnat (?:ip )?to |\\bdrop\\b" if not rows else r"\\bdnat (?:ip )?to "', 'r" drop" if not rows else r" dnat "'),
    "drain-none":    ("node", '        gone.update({k: now + P2PFWD_DRAIN_S for k in _P2PFWD["rows"] - cur})\n', ''),
    "drain-pass":    ("node", '        L.append("    ct direction reply ct status dnat meta l4proto { tcp, udp } ip saddr . th sport @gone drop")',
                      '        L.append("    ct direction reply ct status dnat meta l4proto { tcp, udp } ip saddr . th sport @gone counter")'),
    "drain-stays":   ("node", '        gone = {k: t for k, t in _P2PFWD["gone"].items() if t > now and k not in cur}', '        gone = {k: t for k, t in _P2PFWD["gone"].items() if t > now}'),
    "fill-dup":      ("panel", "        if type(v) is int and P2P_PORT_POOL[0] <= v <= P2P_PORT_POOL[1] and v not in used:",
                      "        if type(v) is int and P2P_PORT_POOL[0] <= v <= P2P_PORT_POOL[1]:"),
    "fill-first":    ("panel", "    for pid in sorted(peers, key=lambda k: (k not in first, k)):", "    for pid in sorted(peers):"),
    "fill-fullrewrite": ("panel", '        if x != q.get("p2p_port"):\n', '        if True:\n'),
    "fill-keyless":  ("panel", '        elif p2p_port_wanted(q):\n            todo.append(q)', '        else:\n            todo.append(q)'),
    "fill-noseed":   ("panel", '    if used and roster.get("p2p_next") is None:', '    if False:'),
    "set-keyless":   ("panel", '    if "p2p_port" not in rec and p2p_port_wanted(rec):       # a WDTT', '    if "p2p_port" not in rec:       # a WDTT'),
    "set-takeback":  ("panel", '    if "p2p_port" not in rec and p2p_port_wanted(rec):       # a WDTT',
                      '    if not p2p_port_wanted(rec):\n        rec.pop("p2p_port", None)\n    if "p2p_port" not in rec and p2p_port_wanted(rec):       # a WDTT'),
    "lowest-first":  ("panel", '        nx = min(max([u for u in used if type(u) is int and lo <= u <= hi], default=lo - 1) + 1, hi)', '        nx = lo'),
    "mark-ignored":  ("panel", '    if not (type(nx) is int and lo <= nx <= hi):', '    if True:'),
    "mark-still":    ("panel", '        _p2p_mark(roster, x)\n    return x', '        pass\n    return x'),
    "fill-floatown": ("panel", '            if not isinstance(v, (bool, int)) and float(v) == int(float(v)):', '            if False:'),
    "create-nokeep": ("panel", '                               keep=(_prev.get("desired_port"), _prev.get("listen_port"), (_prev.get("_lastcfg") or {}).get("listen_port")))',
                      '                               keep=())'),
    "fill-nostart":  ("panel", "        p2p_ports_at_start(_rp)", "        pass"),
    "set-dropped":   ("panel", '"routes", "share", "private", "router", "p2p_port"):', '"routes", "share", "private", "router"):'),
    "set-noalloc":   ("panel", "        if _free:                                             # pool full", "        if False:                                             # pool full"),
    "wire-block":    ("panel", '    d = ((plan or {}).get("_p2pi") or {}).get("direct") if pol == "iface" else None',
                      '    d = ((plan or {}).get("_p2pi") or {}).get("direct") if pol == "iface" else ["0.0.0.0/0"]'),
    "wire-strict":   ("panel", '        return ("direct", tuple(sorted(x for x, ids in (mech or {}).items() if "torrents" in (ids or ()))))',
                      '        return ("direct", ())'),
    "wire-both":     ("panel", "            out.append((min(ts)[2], port))", "            out += [(t_[2], port) for t_ in ts]"),
    "wire-firstif":  ("panel", '                    ts.append((_fp_role(t) != "primary", str(t.get("iface") or ""), a))',
                      '                    ts.append((False, str(t.get("iface") or ""), a))'),
    "wire-keyless":  ("panel", '            if not isinstance(t, dict) or t.get("node") != node_id or _is_self_contained_target(t):\n                continue                                      # (the node first',
                      '            if not isinstance(t, dict) or t.get("node") != node_id:\n                continue                                      # (the node first'),
    "wire-unwired":  ("panel", '**({"p2p_fwd": _fwd} if (_fwd := p2p_fwd_for_node(_rmark, roster, nid, p2p_fwd_scope(node, _blk_mech, my_plan))) else {}),', ''),
    "pool-wdtt":     ("panel", '            if _p and (_pr := p2p_pool_refusal(_p, keep=_own + _ran)):\n                return 400, {"ok": False, "error": _pr, "code": "bad_request"}\n', ''),
    "pool-csqtt":    ("panel", '        if _dtls and (_pr := p2p_pool_refusal(_dtls, keep=_own + _running_ports(deps, nid, "csqtt", iface))):   # (+ what it runs on)\n            return 400, {"ok": False, "error": _pr, "code": "bad_request"}\n', ''),
    "pool-manage":   ("panel", '                        _pr = p2p_pool_refusal(_np, keep=[_cp, _port_of(turn_listen_now(deps, nid, svc))])', '                        _pr = None'),
    "manage-namekeep": ("panel", 'keep=[_cp, _port_of(turn_listen_now(deps, nid, svc))])', 'keep=[_cp])'),
    "wdtt-noran":    ("panel", '(_pr := p2p_pool_refusal(_p, keep=_own + _ran))', '(_pr := p2p_pool_refusal(_p, keep=_own))'),
    "dialin-drawpool": ("panel", ' - {51820} - set(range(P2P_PORT_POOL[0], P2P_PORT_POOL[1] + 1)))', ' - {51820})'),
    "pool-dialin":   ("panel", '        if (_pr := p2p_pool_refusal(port)):                   # (a kept exit', '        if (_pr := None):                   # (a kept exit'),
    "pool-nokeep2":  ("panel", '        if P2P_PORT_POOL[0] <= p <= P2P_PORT_POOL[1] and str(p) not in {str(k).strip() for k in keep if k is not None}:',
                      '        if P2P_PORT_POOL[0] <= p <= P2P_PORT_POOL[1]:'),
    "pool-open":     ("panel", "        return p2p_pool_refusal(port, keep)\n    return None", "        return None\n    return None"),
    "sub-taken":     ("sub", ' or port in (e.get("taken") if isinstance(e.get("taken"), list) else ()):', ':'),
    "sub-takenjunk": ("sub", 'port in (e.get("taken") if isinstance(e.get("taken"), list) else ())', 'port in (e.get("taken") or ())'),
    "sub-privaddr":  ("sub", "        if ipaddress.ip_address(str(e.get(\"addr\") or \"\")).is_global:", "        if True:"),
    "sub-anytarget": ("sub", '    if not mine or mine[1] != tg.get("iface"):\n        return {}', '    if not mine:\n        return {}'),
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
 && nft add table ip keepnat && nft add chain ip keepnat pre '{ type nat hook prerouting priority dstnat; }' \
 || { echo SETUP-FAILED net; kill $CPID $XPID; exit 0; }
# (keepnat: a node's iptables NAT keeps the kernel's NAT hook registered, so an open flow keeps its binding when ours goes)
sleep 1
nft -f "$1" || { echo SETUP-FAILED p2p; kill $CPID $XPID; exit 0; }
nft -f "$2" || { echo LOADED no; kill $CPID $XPID; exit 0; }
echo LOADED yes
OUT=$(mktemp)
nsenter -t $CPID -n timeout 9 python3 -u -c '
import socket, select, os, time
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("10.9.0.2", 20016))
t = socket.socket(); t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); t.bind(("10.9.0.2", 20016)); t.listen(4)
end = time.time() + 4.0
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
if [ -s "${3:-}" ]; then (sleep 1.0; nft -f "$3" || echo "SWAP failed") & fi
nsenter -t $XPID -n timeout 9 python3 -c '
import socket, os, time
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
time.sleep(1.5)                                   # the router may swap the table here ($3): the same flow again
u.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"e1:q4:ping1:t2:ab1:y1:qe", ("192.0.2.1", 20016))
try:
    print("X_UDP2 %s:%d" % u.recvfrom(2048)[1])
except Exception:
    print("X_UDP2 none")
o.settimeout(4)
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


def _wire(p2p, fwd, swap=""):
    fs = []
    for t in (p2p, fwd, swap):
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
            k, v = ln.split(" ", 1)
            out[k] = v.strip() if k not in out else out[k] + " " + v.strip()   # a repeated key keeps every value
    return out


class FwdBox:
    """The few reads _ensure_p2pfwd makes, and what it ran."""
    NAT = ['-A POSTROUTING -s 10.8.0.0/24 -o eth0 -m comment --comment swg-egress:wg0 -j SNAT --to-source 198.51.100.7',
           '-A POSTROUTING -s 10.9.0.0/24 -o eth1 -m comment --comment "swg-egress:wg1" -j MASQUERADE',
           '-A POSTROUTING -s 10.11.0.0/24 -o ppp0 -m comment --comment swg-egress:wg3 -j MASQUERADE']
    ADDR = ("1: lo    inet 127.0.0.1/8 scope host lo\n2: eth0    inet 169.254.7.7/16 scope link eth0\n"
            "2: eth0    inet 192.0.2.1/24 brd 192.0.2.255 scope global eth0\n"
            "2: eth0    inet 192.0.2.77/24 scope global secondary eth0\n3: eth1@if9    inet 203.0.113.5/24 scope global eth1\n"
            "4: ppp0    inet 100.64.7.9 peer 100.64.0.1/32 scope global ppp0\n")
    SS = ("udp   UNCONN 0 0 0.0.0.0:51820 0.0.0.0:*\nudp   UNCONN 0 0 0.0.0.0:20001 0.0.0.0:*\n"
          "tcp   LISTEN 0 4096 192.0.2.1:20003 0.0.0.0:*\ntcp   LISTEN 0 4096 192.0.2.77:20004 0.0.0.0:*\ntcp   LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*\n")

    def __init__(self, refuse=False):
        self.cmds, self.table, self.refuse, self.delfail = [], None, refuse, 0

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
            rc, out = (0, self.table) if self.table else (1, "")
        elif a[:3] == ["nft", "delete", "table"]:
            if self.delfail:
                self.delfail -= 1
                return types.SimpleNamespace(returncode=1, stdout="", stderr="Error: busy")
            rc = 0 if self.table else 1
            self.table = None
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="" if rc == 0 else "Error: No such file or directory")
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
    def fwd_pass(fwd, box=None, mm=None, down=(), wan="eth0"):
        mm = mm or base.load(src); b = box or FwdBox()
        mm.run = b.run; mm.GEO_DIR = mm.GEO_DIR if mm.GEO_DIR.startswith(tempfile.gettempdir()) else tempfile.mkdtemp()
        subs = {"wg0": "10.8.0.0/24", "wg1": "10.9.0.0/24", "wg2": "10.10.0.0/24", "wg3": "10.11.0.0/24", "wg4": "10.12.0.0/24"}
        mm._iface_subnet = lambda cfg, i: subs.get(i, "")
        mm._dev_link_state = lambda d: "absent" if d in down else "up"
        mm._detect_wan = lambda: wan
        mm._LOOP["n"] += 1                                     # a new pass (the address read is cached per pass)
        res = {"changed": 0, "errors": []}
        mm._ensure_p2pfwd(fwd, {"interfaces": {i: {} for i in subs}}, res)
        return mm, b, res
    FW = [("10.8.0.2", 20000), ("10.8.0.3", 20001), ("10.9.0.2", 20002), ("10.10.0.2", 20003), ("10.10.0.4", 20004), ("10.6.0.2", 20005),
          ("10.11.0.2", 20006), ("10.12.0.2", 20007)]
    mm, b, res = fwd_pass(FW, down=("wg4",))
    t = b.table or ""
    ok("10.8.0.2 . 20000 : 198.51.100.7 . 20000" in t and "203.0.113.5 . 20002 : 10.9.0.2" in t and "192.0.2.1 . 20004 : 10.10.0.4" in t,
       "[4] each device's address is its interface's egress: SNAT source, MASQUERADE device, else the WAN's (not a link-local first)")
    ok("100.64.7.9 . 20006 : 10.11.0.2" in t, "[4] a point-to-point WAN's address (`inet A peer B/32`) is read (review F9)")
    ok("20007" not in t and "wg4" not in mm._P2PFWD["report"], "[4] a device on an interface that is not up is left out (review F4)")
    ok("20001" not in t and "20003" not in t and "20005" not in t,
       "[4] a port a listener holds (wildcard, or bound on that address) is left out; a device on no interface here too")
    ok("192.0.2.1 . 20004 : 10.10.0.4" in t, "[4] …a port bound on ANOTHER address of the box is not taken")
    ok(mm._P2PFWD["report"] == {"wg0": {"addr": "198.51.100.7", "taken": [20001]}, "wg1": {"addr": "203.0.113.5", "taken": []},
                                "wg2": {"addr": "192.0.2.1", "taken": [20003]}, "wg3": {"addr": "100.64.7.9", "taken": []}},
       "[4] the report by interface: the address and the ports taken (%s)" % mm._P2PFWD["report"])
    ok('iifname { "eth0" }' in t and 'oifname { "eth0" }' in t and "meta mark set 0x40000000" in t and not res["errors"],
       "[4] in by the WAN, out by the WAN, the replies marked for rule 6880 (%s)" % res["errors"])
    ok("priority mangle + 7;" in t, "[4] the replies' mark at its own priority, not swg_s5x's mangle + 6 (review F44)")
    ok("priority dstnat + 5;" in t and "typeof ip daddr . th dport : ip daddr" in t,
       "[4] the DNAT runs after iptables/Docker/remnanode's (the first binding wins — theirs); the map by expression (review F10, F1)")
    n = len(b.loads())
    fwd_pass(FW, b, mm, down=("wg4",))
    ok(n == 1 and len(b.loads()) == 1, "[4] the same set again: no reload (sig) (%d → %d)" % (n, len(b.loads())))
    b.table = "table ip swg_p2pfwd {\n}\n"                  # flushed in place: it lists, with no rule
    fwd_pass(FW, b, mm, down=("wg4",))
    ok(len(b.loads()) == 2 and " dnat " in (b.table or ""), "[4] a table flushed in place is rebuilt — in force, not only there (review F14)")
    mw = fwd_pass(FW[3:5], wan="eth1")[0]
    ok(mw._P2PFWD["report"].get("wg2", {}).get("addr") == "203.0.113.5", "[4] the WAN's address is the default route's device (_detect_wan), "
       "not the first by name (review F8) (%s)" % mw._P2PFWD["report"])
    # the drain (review F2): a forward that ends drops its device's replies on flows still DNAT'd to it
    fwd_pass(FW[:2], b, mm)
    t2 = b.table or ""
    ok("set gone" in t2 and "10.9.0.2 . 20002" in t2 and "ip saddr . th sport @gone drop" in t2 and "10.8.0.2 . 20000 :" in t2,
       "[4] a device whose forward ended is drained while the others forward")
    fwd_pass([], b, mm)
    t3 = b.table or ""
    ok("set gone" in t3 and "10.8.0.2 . 20000" in t3 and "chain pre" not in t3 and "chain post" not in t3 and mm._P2PFWD["report"] == {},
       "[4] nothing forwarded any more (a switch to Block): the table holds the drain alone, nothing reported")
    fwd_pass([("10.8.0.2", 20000)], b, mm)
    ok("10.8.0.2 . 20000 :" in (b.table or "") and "10.8.0.2 . 20000," not in (b.table or "") and "10.8.0.2 . 20000 }" not in (b.table or ""),
       "[4] a device forwarded again leaves the drain")
    mm._P2PFWD["gone"] = {k: 0 for k in mm._P2PFWD["gone"]}
    fwd_pass([], b, mm)
    fwd_pass([], b, mm)
    mm._P2PFWD["gone"] = {k: 0 for k in mm._P2PFWD["gone"]}
    fwd_pass([], b, mm)
    ok(b.table is None and not os.path.exists(os.path.join(mm.GEO_DIR, ".p2pfwd.sig")) and mm._P2PFWD["report"] == {},
       "[4] once the drain has run its time: the table and its sig deleted, nothing reported")
    # a restart (review F47): the new process reads what the last one had in force — a forward that ended is still drained
    mr, br, _ = fwd_pass(FW[:2])
    m3 = base.load(src); m3.GEO_DIR = mr.GEO_DIR
    fwd_pass([], br, m3)
    ok("set gone" in (br.table or "") and "10.8.0.2 . 20000" in (br.table or ""), "[4] after a noded restart a forward that ended is still drained (review F47)")
    # a refused load (review F52): what was in force is drained once a load goes in
    mf, bf, _ = fwd_pass([FW[0], FW[2]])
    bf.refuse = True
    fwd_pass(FW[:1], bf, mf)
    bf.refuse = False
    fwd_pass(FW[:1], bf, mf)
    t5 = bf.table or ""
    ok("set gone" in t5 and "10.9.0.2 . 20002" in t5 and "10.8.0.2 . 20000 :" in t5,
       "[4] a refused load forgets nothing: the next load drains what was in force (review F52)")
    mf2, bf2, _ = fwd_pass([FW[0]])
    bf2.refuse = True
    mf2.GEO_DIR = tempfile.mkdtemp(); fwd_pass([FW[0], FW[2]], bf2, mf2)   # refused (a new sig)
    fwd_pass([FW[0], FW[2]], bf2, mf2)                                     # refused again
    bf2.refuse = False
    fwd_pass([FW[2]], bf2, mf2)                                            # 10.8.0.2's forward ended: it must be drained
    ok("10.8.0.2 . 20000" in (bf2.table or "") and "set gone" in (bf2.table or ""),
       "[4] two refused loads in a row still drain what was in force (s12-backlog F3)")
    # in force (review F50): the DNAT chain gone, the reply chain's `ct status dnat` left — rebuilt
    mi, bi, _ = fwd_pass(FW[:2])
    bi.table = re.sub(r"\n  chain pre \{.*?\n  \}", "", bi.table, flags=re.S)
    n0 = len(bi.loads())
    fwd_pass(FW[:2], bi, mi)
    ok("chain pre" in (bi.table or "") and len(bi.loads()) == n0 + 1, "[4] a table whose DNAT chain is gone is rebuilt — the reply chain's `ct status dnat` is not it (review F50)")
    mb, bb, _ = fwd_pass(FW[:1])
    mb._P2PFWD["gone"] = {}; mb._P2PFWD["rows"] = set()
    bb.delfail = 1
    r1 = fwd_pass([], bb, mb)[2]
    r2 = fwd_pass([], bb, mb)[2]
    ok(r1["errors"] and bb.table is None and not r2["errors"] and not os.path.exists(os.path.join(mb.GEO_DIR, ".p2pfwd.sig")),
       "[4] a delete that failed is tried again on the next pass (review F15)")
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
    p2pt, fwdt = m._p2p_nft("direct", [], ["eth0"], [], True, fwdin=True), m._p2pfwd_nft([("10.9.0.2", 20016, "192.0.2.1")], ["eth0"])
    out = _wire(p2pt, fwdt)
    if not out or out.get("LOADED") is None:
        print("  SKIPPED [6] real kernel — the throwaway namespaces could not be set up here (%s)" % out)
        return
    ok(out.get("LOADED") == "yes", "[6] the table loads on the real nft")
    ok((out.get("C_UDP") or "").split()[:1] == ["192.0.2.9"] and out.get("X_UDP") == "192.0.2.1:20016" and out.get("X_UDP2") == "192.0.2.1:20016",
       "[6] an inbound DHT query reaches the device; its answers leave from address:port by the WAN, not the mesh leg (%s %s %s)"
       % (out.get("C_UDP"), out.get("X_UDP"), out.get("X_UDP2")))
    ok(out.get("C_TCP") == "192.0.2.9" and out.get("X_TCP") == "68", "[6] an inbound BitTorrent handshake reaches it and is answered (%s %s)"
       % (out.get("C_TCP"), out.get("X_TCP")))
    ok(out.get("X_OWN") == "192.0.2.1:20016", "[6] the device's own flow from its port leaves from that port (%s)" % out.get("X_OWN"))
    ok(out.get("DROPPED") == "0", "[6] the guard dropped nothing (%s)" % out.get("DROPPED"))
    out = _wire(p2pt, fwdt, m._p2pfwd_nft([], [], [("10.9.0.2", 20016)]))
    ok(out and out.get("C_UDP") == "192.0.2.9 192.0.2.9" and out.get("X_UDP") == "192.0.2.1:20016" and out.get("X_UDP2") == "none"
       and "SWAP" not in out,
       "[6] the forward ended (the table swapped for its drain): the next packet of the open flow still reaches the device, its "
       "answer is dropped — an open connection ends too (review F2) (%s)" % ({k: out.get(k) for k in ("C_UDP", "X_UDP", "X_UDP2", "SWAP")} if out else out))


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
    "pf": {"id": "pf", "user_id": "u1", "csqtt_password": "pw", "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt", "ip": "10.8.0.50"}]},
    "pz": {"id": "pz", "user_id": "u1", "pubkey": key("z"), "psk": key("q"), "csqtt_password": "pwz",
           "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt", "ip": "10.8.0.51"}, {"node": "n2", "iface": "wg0", "ip": "10.7.0.9/32", "type": "wg"}]}}}
WANT = {"pa": 20001, "pb": 20000, "pc": 20002, "pd": 20003, "pe": 20004, "pf": None, "pz": 20005}   # pf: csqtt only — no port (review F38)


def unit_checks(src, ok):
    m = types.ModuleType("swgpanel_fwd"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    W = lambda **kw: dict(kw, targets=[{"node": "n1", "iface": "wg0", "ip": "10.8.0.9", "type": "wg"}])   # a wg device
    r = json.loads(json.dumps(ROSTER))
    ch = m.p2p_ports_fill(r)
    got = {k: v.get("p2p_port") for k, v in r["peers"].items()}
    ok(ch and got == WANT, "[7] next free, sorted peer-id order; the later duplicate and the out-of-pool port reassigned; a csqtt-only "
       "device takes none (review F38) (%s)" % got)
    ok(r.get("p2p_next") == 20006, "[7] the high-water mark moves past what was handed out (%s)" % r.get("p2p_next"))
    ok(not m.p2p_ports_fill(r), "[7] a second fill changes nothing")
    r2 = {"peers": {"a1": W(p2p_port=20000), "zz": W(p2p_port=20000)}}
    m.p2p_ports_fill(r2, first={"zz"})
    ok(r2["peers"]["zz"].get("p2p_port") == 20000 and r2["peers"]["a1"].get("p2p_port") == 20001,
       "[7] `first` (this panel's own peers) keep their port; an arriving one is reassigned (%s)" % r2)
    rf = {"peers": {"a": W(p2p_port=20000.0), "b": W(p2p_port="20001")}, "p2p_next": 20050}
    m.p2p_ports_fill(rf)
    ok([v.get("p2p_port") for v in rf["peers"].values()] == [20000, 20001] and [type(v.get("p2p_port")) for v in rf["peers"].values()] == [int, int],
       "[7] a port stored as a float or text keeps its own value, as an int (review F18, s12-backlog F2) (%s)" % rf)
    up = {"peers": {"h%02d" % i: W(p2p_port=20000 + i) for i in range(11) if i != 3}}
    ok(m.p2p_port_take(up, "new") == 20011, "[7] a roster from before the mark: the next device gets the port past the highest held, "
       "not a deleted device's gap (s12-backlog F1) (%s)" % up.get("p2p_next"))
    ps = {"peers": {"d": W(p2p_port=20003)}}
    m.peer_set(ps, "d", {"targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]}, 0)
    m.peer_set(ps, "d", {"targets": [{"node": "n2", "iface": "wg0", "ip": "10.7.0.3", "type": "wg"}]}, 0)
    kh = {"peers": {"k": {"targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}], "p2p_port": 20009}}}
    m.p2p_ports_fill(kh)
    ok(ps["peers"]["d"].get("p2p_port") == 20003 and kh["peers"]["k"].get("p2p_port") == 20009,
       "[7] a port is never taken back: a device left csqtt-only by one save and given a wg target by the next keeps the port its "
       "client listens on, and so does one across the start-up fill (s12-backlog F11) (%s %s)" % (ps["peers"]["d"].get("p2p_port"), kh["peers"]["k"].get("p2p_port")))
    pre = {"peers": {"h%02d" % i: W(p2p_port=20000 + i) for i in range(11)}}
    m.p2p_ports_fill(pre)
    pre["peers"].pop("h10")
    ok(pre.get("p2p_next") == 20011 and m.p2p_port_take(pre, "new") == 20011,
       "[7] a roster from before the mark gets one at the start-up fill: the deleted highest port is not reused (s12-backlog F10) (%s)" % pre.get("p2p_next"))
    full = {"peers": {"p%05d" % i: W(p2p_port=20000 + i) for i in range(10000)}}
    full["peers"]["zzz"] = W()
    m.p2p_ports_fill(full)
    ok("p2p_port" not in full["peers"]["zzz"] and not m.p2p_ports_fill(full),
       "[7] the pool full: the device gets no port, and the next fill reports no change (no rewrite every start, review F53)")
    # the hand-out: from the high-water mark, wrapping once (review F41)
    hw = {"peers": {"a": W(p2p_port=20000), "b": W(p2p_port=20001)}, "p2p_next": 20002}
    hw["peers"].pop("a")                                      # a deleted device's port …
    x1 = m.p2p_port_take(hw, "c")
    ok(x1 == 20002 and hw["p2p_next"] == 20003, "[7] … is not handed to the next device: it gets the next above the mark (%s %s)" % (x1, hw["p2p_next"]))
    hw["p2p_next"] = 29999
    x2, x3 = m.p2p_port_take(hw, "d"), m.p2p_port_take(hw, "e")
    ok((x2, x3) == (29999, 20000), "[7] at the top of the pool it comes round from the bottom (%s %s)" % (x2, x3))
    ok(m.p2p_port_wanted({"targets": [{"type": "csqtt", "iface": "csqtt1"}, {"type": "wdtt", "iface": "wdtt0"}]}) is False
       and m.p2p_port_wanted({"targets": [{"type": "csqtt", "iface": "csqtt1"}, {"type": "awg", "iface": "awg0"}]}) is True
       and m.p2p_port_wanted({"targets": []}) is False, "[7] a port is wanted by a device with a wg/awg target only (review F38)")


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
        ok(c == 200 and ports().get(pg) == 20006, "[8] a create takes the next free port above the mark (%s %s)" % (c, ports().get(pg)))
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
        ok(c == 200 and ports().get(ph) == 20007, "[8] a deleted device's port is not handed to the next device (review F41) (%s %s)" % (c, ports().get(ph)))
        c, r = req("/api/peers/create", {"title": "k", "user_id": "u1", "csqtt_password": "pwk", "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]})
        pk = ((r.get("data") or {}).get("peer") or r.get("data") or {}).get("id")
        ok(pk and ports().get(pk) is None, "[8] a csqtt-only device takes no port (review F38) (%s %s %s)" % (c, pk, str(r)[:100]))
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
        # [10] a turn-proxy moved into the pool before the doors refused it stays editable; a new move into it is refused
        TP = {"service": "vk-turn-proxy-WINGS-N-5000", "listen": "0.0.0.0:25000", "connect": "127.0.0.1:51820", "wrap_key": "k" * 64,
              "params": "-wrap-mode on -wrap-key " + "k" * 64}
        req("/api/node/sync", {"snapshot": dict(snap1, generated_at=int(time.time()), turn_proxies=[TP])}, t1)
        c, r = req("/api/turn/manage", {"node": "n1", "service": TP["service"], "listen": TP["listen"], "connect": TP["connect"], "params": TP["params"]})
        ok("20000–29999" not in json.dumps(r, ensure_ascii=False), "[10] a proxy already listening in the pool: an edit that re-sends its listen is "
           "not refused (pool-doors F1) (%s %s)" % (c, str(r)[:120]))
        c, r = req("/api/turn/manage", {"node": "n1", "service": TP["service"], "listen": "0.0.0.0:25500", "connect": TP["connect"]})
        ok(c == 400 and "20000–29999" in json.dumps(r, ensure_ascii=False), "[10] a proxy moved to a new pool port is refused (%s %s)" % (c, str(r)[:120]))
        # [10]
        c, r = req("/api/iface/create", {"node": "n1", "iface": "wg5", "subnet": "10.55.0.0/24", "listen_port": 20500})
        ok(c == 400 and "20000–29999" in json.dumps(r, ensure_ascii=False), "[10] a new interface on a pool port is refused (%s %s)" % (c, str(r)[:120]))
        c, r = req("/api/iface/update", {"node": "n1", "iface": "wg0", "listen_port": 21000})
        ok(c == 400, "[10] moving an interface onto a pool port is refused (%s)" % c)
        _n = json.load(open(nodes)); _n["n1"]["ifaces"]["wg7"] = {"listen_port": 25000}; json.dump(_n, open(nodes, "w"))
        c, r = req("/api/iface/create", {"node": "n1", "iface": "wg7", "subnet": "10.77.0.0/24", "listen_port": 25000})
        ok("20000–29999" not in json.dumps(r, ensure_ascii=False), "[10] an interface recreated on its own pool port is not refused (review F5) (%s %s)" % (c, str(r)[:120]))
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
    # every other door that takes a listen port (pool review F6): one helper, the record's own port kept
    pr = m.p2p_pool_refusal
    ok(pr(25000) and pr("25000 ") and not pr(25000, keep=["25000"]) and not pr(19999) and not pr(30000) and not pr("x") and not pr(None),
       "[10] p2p_pool_refusal: a new port in the pool refused; its own, one outside, junk not")
    di = lambda port, kept=None: m._dialin_refusal({"provider": "profile", "profile": {"listen_port": port, "address": "10.66.0.1/30"}},
                                                    {"listen_port": kept, "address": "10.66.0.1/30"} if kept else None, "", {"ports": {}})
    ok("20000–29999" in json.dumps(di(25500), ensure_ascii=False) and not di(25500, kept=25500) and not di(42850),
       "[10] a dial-in exit's typed or pasted port in the pool is refused; a kept exit's own port is not (%s)" % di(25500))
    deps = {"node_snaps": {"n1": {"wdtt": [{"iface": "wdtt1", "listen": "0.0.0.0:25100", "wg_port": 25101}], "csqtt": [{"iface": "csqtt1", "listen": "0.0.0.0:25200"}]}}}
    ok(m._running_ports(deps, "n1", "wdtt", "wdtt1") == ["25100", "25101"] and m._running_ports(deps, "n1", "csqtt", "csqtt1") == ["25200"]
       and m._running_ports(deps, "n1", "csqtt", "csqtt9") == [], "[10] what the node runs a WDTT / csqtt instance on is kept too (pool-doors F3)")
    src_gen = next((ast.unparse(n) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and "random.choice(free)" in ast.unparse(n)), "")
    ok("set(range(P2P_PORT_POOL[0], P2P_PORT_POOL[1] + 1))" in src_gen, "[10] a dial-in exit's drawn port never falls in the pool (pool-doors F2)")
    tree = ast.parse(src)
    def calls_in(handler_path):
        for n in ast.walk(tree):
            if isinstance(n, ast.If) and handler_path in ast.unparse(n.test):
                u = ast.unparse(n)                          # asked, with what the node runs the instance on kept
                return bool(re.search(r"p2p_pool_refusal\([^)]*keep=_own \+ (_ran|_running_ports\()", u))
        return None
    doors = {d: calls_in(d) for d in ("'/api/wdtt/set'", "'/api/csqtt/set'")}   # (ast.unparse quotes with ')
    tm = next((ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.If) and "path.endswith('/manage')" in ast.unparse(n.test)), "")
    ok(all(doors.values()) and "p2p_pool_refusal(_np, keep=[_cp, " in tm,
       "[10] the WDTT and csqtt saves and a turn-proxy's listen move ask it (%s, manage %s)" % (doors, "p2p_pool_refusal(_np" in tm))


def sub_checks(src, psrc, ok):
    S = types.ModuleType("swgsub_fwd"); S.__file__ = SUB
    exec(compile(src, SUB, "exec"), S.__dict__)
    P = types.ModuleType("swgpanel_fwd3"); P.__file__ = PANEL
    exec(compile(psrc, PANEL, "exec"), P.__dict__)
    peer = {"p2p_port": 20004, "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5/32"},
                                           {"node": "n1", "iface": "wg1", "ip": "10.9.0.5/32", "primary": "primary"},
                                           {"node": "n2", "iface": "wg0", "ip": "10.7.0.5/32"}]}
    tg = lambda n, i: {"node": n, "iface": i}
    d = {"n1": {"p2p_fwd": {"wg0": {"addr": "45.67.89.10", "taken": []}, "wg1": {"addr": "45.67.89.20", "taken": []}}},
         "n2": {"p2p_fwd": {"wg0": {"addr": "192.0.2.1", "taken": [20004]}}}}
    got = [S._p2p_fwd_of(peer, tg(n, i), d) for n, i in (("n1", "wg0"), ("n1", "wg1"), ("n2", "wg0"))]
    ok(got == [{}, {"p2p_port": 20004, "p2p_addr": "45.67.89.20"}, {}],
       "[11] the port on the device's chosen target (primary wg1), never its other one there, nor where it is taken (%s)" % got)
    d1 = {"n1": {"p2p_fwd": {"wg0": {"addr": "45.67.89.10", "taken": []}}}}
    got = [S._p2p_fwd_of(peer, tg("n1", i), d1) for i in ("wg0", "wg1")]
    ok(got == [{"p2p_port": 20004, "p2p_addr": "45.67.89.10"}, {}], "[11] wg1 not forwarded there: the wg0 target carries it (%s)" % got)
    try:
        junk = S._p2p_fwd_of(peer, tg("n1", "wg1"), {"n1": {"p2p_fwd": {"wg1": {"addr": "45.67.89.20", "taken": 20004}}}})
    except Exception as e:
        junk = "raised %s" % type(e).__name__
    ok(junk == {"p2p_port": 20004, "p2p_addr": "45.67.89.20"}, "[11] a `taken` that is not a list never fails the page (review F19) (%s)" % junk)
    pv = S._p2p_fwd_of(peer, tg("n1", "wg1"), {"n1": {"p2p_fwd": {"wg1": {"addr": "10.0.0.5", "taken": []}}}})
    ok(pv == {"p2p_port": 20004}, "[11] a private address (a node behind 1:1 NAT) is never named; the port still is (review F37) (%s)" % pv)
    ok(S._p2p_fwd_of(peer, tg("n1", "wg1"), {}) == {} and S._p2p_fwd_of({"targets": peer["targets"]}, tg("n1", "wg1"), d) == {},
       "[11] an older node (no report) or a device with no port: nothing")
    # the twin: the panel forwards the same target swg-sub names (node reports the interfaces of its scope)
    r = {"peers": {"p": dict(peer)}}
    for scope, rep in ((("direct", ()), d["n1"]["p2p_fwd"]), (("iface", ("10.8.0.0/24",)), d1["n1"]["p2p_fwd"])):
        w = P.p2p_fwd_for_node(None, r, "n1", scope)
        s_ = [i for i in ("wg0", "wg1") if S._p2p_fwd_of(peer, tg("n1", i), {"n1": {"p2p_fwd": rep}})]
        ip = {"wg0": "10.8.0.5", "wg1": "10.9.0.5"}
        ok(w == [[ip[s_[0]], 20004]] if len(s_) == 1 else False, "[11] the twin: the panel forwards the target the page names (%s | %s)" % (w, s_))


def run_checks(psrc, nsrc, ssrc, which=None):
    """`which`: a plant's program — only the checks that read it run (the panel's twin parity reads swg-sub too), so the
    sweep of every plant fits the runner's time box."""
    fails = []
    class Caught(Exception):
        pass
    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
            if which:                                         # a plant is caught at its first red check: the rest is not run
                raise Caught()
    try:
        if which in (None, "node"):
            node_checks(nsrc, ok)
        if which in (None, "panel", "sub"):
            unit_checks(psrc, ok)
            keep_checks(psrc, ok)
            sub_checks(ssrc, psrc, ok)
        if which in (None, "panel"):
            panel_checks(psrc, ok)
    except Caught:
        pass
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
            f = run_checks(*{"panel": (p, NSRC, SSRC), "node": (PSRC, p, SSRC), "sub": (PSRC, NSRC, p)}[which], which=which)
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
