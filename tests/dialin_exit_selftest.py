"""Self-test — A DIAL-IN EXIT (docs/LISTEN-EXIT-PLAN.md), AND EVERY EXIT KIND BY NAME (docs/SOCKS5-EXIT-PLAN.md T6).

A home router behind NAT cannot be dialled, so the node holds a SERVER config and the router dials it: a pasted profile
with a `ListenPort` and no `Endpoint`. One new mode of the imported `profile` exit — the device, cfg_sig, health judge,
routing and SNAT are reused — so what this gate pins is the handful of places that had to learn it, and that a DIAL-OUT
profile reads, signs and writes exactly as it did (compared against `eb25bad7`, the base S9 was built on, loaded from git).

  [1] node conf: a dial-in conf byte-exact (ListenPort, no Endpoint/keepalive, 0.0.0.0/0 forced); a dial-out conf
      byte-identical to eb25bad7's for a matrix of profiles
  [2] node pass: the record check takes a port instead of an endpoint; the row reports the LEARNED endpoint and the
      port; every row shape of a dial-in exit carries the port (the panel's old-node test); an unknown kind is refused,
      never registered as WARP
  [3] health: a device that nothing answers through reads False (dead), not "can't tell"; three probes over 30 s → dead;
      no endpoint name is ever looked up for a dial-in exit, so redial cannot fire (closed by the code — no plant)
  [3b] the latency through the tunnel (S9e): the trace's TCP handshake alone, the name resolved before the clock starts —
      a real _exit_trace against a local TLS server, pinned to lo, its resolver held up 200 ms
  [4] adoption: a dial-in device before its first handshake is not offered for adoption, and the exit-candidate list is
      identical with and without the skip
  [5] panel parse: Endpoint → dial-out, the dict identical to eb25bad7's; ListenPort alone → dial-in; neither, two peers,
      a bad port → refused
  [6] panel save: dial_src refused; a port another holder has, RAW-IP's, or another dial-in exit's → refused, an
      unchanged stored one tolerated; an address inside an interface subnet or the mesh pool → refused; the ports are
      counted for everything else on the node; an unknown kind refused, not coerced — and kept when already stored
  [7] generate (S9b, S9e): a random free port of 42821–42899, never outside it (full → refused); on a node that declares its
      firewall without that range, a free port inside what it declares, never 51820 nor the system mesh band; never another
      stored dial-in exit's port; a /31 of 10.254.0.0/16 clear of
      the node's subnets and its other exits; the AmneziaWG set per protocol (3.1 refused on a 2.0 node); stored in the
      paste's shape, the request field never stored; Regenerate keeps port, address and AmneziaWG and takes the new keys
  [7b] what the operator typed (S9e): a port used (one another holder has, one outside a declared firewall, one in the
      mesh band, or no ASCII number → refused, never a 500); an MTU used (outside 576–1500 → refused, never clamped);
      AmneziaWG cells over the template and the generator — a value used, "-" no such line, blank drawn; a typed value beats
      a template "-"; an I-line no app reads refused; the set it makes keeps the rules (Jc/Jmin/Jmax together); 3.1 S1–S4
      ≥ 12, a template's S under 12 never re-draws the typed ones; a template value no app reads is drawn; WireGuard takes no cells
  [7c] the node's port inventory (S9e): a port the host listens on is not a holder at any door — not refused to a typed
      port nor to an interface create, RAW-IP's own listener included — but never drawn; a dial-in exit's own live port is
      named after the exit; the mesh link allocator asks the same inventory (WDTT and its internal WG port, csqtt, a
      created interface, RAW-IP, the host's listeners), a WDTT report sent as an object of objects included; a udp_listen
      that is no list of numbers is dropped at the sync door
  [8] the router's key in the config store (S9c): a node's bucket takes an encryption key only for a known node; a key is
      kept only against the router key and the node-key digest the exit's record holds (a ciphertext that is no string is
      refused); it is read back — with its bucket key and router key, one request — while the exit stands, a read that
      began before a Regenerate's save prunes nothing it kept (the prune reads the record under the lock), and it is gone
      once the router or the node key changes, the exit turns dial-out or is removed (the save prunes it on disk), or the
      node is deleted (bucket and key); the bucket lists as the node's; a Transfer carries none of it (the far panel's
      vault cannot open it) and names the exits whose router config stays

Run: python3 tests/dialin_exit_selftest.py      (0 = pass)
     --perturb-endpoint   the dial-in conf keeps an `Endpoint =` line                     → RED [1]
     --perturb-portout    ListenPort is written for any record that has one (dial-out too) → RED [1]
     --perturb-needep     the node's record check requires an endpoint again              → RED [2]
     --perturb-stamp      the port is not stamped on every row                            → RED [2]
     --perturb-nodewarp   the node's unknown-kind guard removed (registers WARP)          → RED [2]
     --perturb-reach      a timed-out reach reads None ("can't tell")                     → RED [3]
     --perturb-adopt      the adoption skip removed                                       → RED [4]
     --perturb-cand       the skip moved above the exit-candidate branch                  → RED [4]
     --perturb-peers      two peers accepted                                              → RED [5]
     --perturb-dialsrc    dial_src no longer refused                                      → RED [6]
     --perturb-clash      the port holders not asked                                      → RED [6]
     --perturb-overlap    the address not checked                                         → RED [6]
     --perturb-count      the node's port table does not count dial-in exits               → RED [6]
     --perturb-coerce     the panel's "not profile ⇒ WARP" coercion back                   → RED [6]
     --perturb-bound      generate allocates past 42899 (unbounded, as _alloc_port is)      → RED [7]
     --perturb-meshband   the draw may take a port of the system mesh band                 → RED [7b]
     --perturb-dinrange   generate draws from 51820–51899 again                            → RED [7]
     --perturb-fwfall     a declared firewall without 42821–42899 gets no port             → RED [7]
     --perturb-no51820    the declared fallback may draw 51820                             → RED [7]
     --perturb-typedport  a typed port is ignored                                          → RED [7b]
     --perturb-typedmtu   a typed MTU is ignored                                           → RED [7b]
     --perturb-typedawg   the typed AmneziaWG cells are ignored                            → RED [7b]
     --perturb-awgref     the typed cells are not checked (an I-line no app reads)          → RED [7b]
     --perturb-awgrules   the set Generate makes is not held to the rules (Jc trio)        → RED [7b]
     --perturb-s3tpl      a 3.1 template S under 12 makes awg3_full re-draw the typed S     → RED [7b]
     --perturb-rawphrase  the holder is flattened to its English text inside the sentence     → RED [6]
     --perturb-s3omit     a 3.1 template S of "-" is kept as no line, so the create is refused → RED [7b]
     --perturb-tplbad     a template I-line no app reads refuses Generate                  → RED [7b]
     --perturb-meshref    a typed port in the system mesh band is accepted                 → RED [7b]
     --perturb-s4fit      a drawn S4 is not fitted to a typed MTU                          → RED [7b]
     --perturb-asciiport  a typed port is read with str.isdigit() ("²" → a 500)            → RED [7b]
     --perturb-s3min      a 3.1 S under 12 is not refused (awg3_full re-draws it silently) → RED [7b]
     --perturb-fwref      a changed port outside a declared firewall is accepted           → RED [7b]
     --perturb-udplisten  the draw does not steer clear of the host's listeners            → RED [7c]
     --perturb-typedlisten  a typed port the host listens on is refused (or re-drawn)     → RED [7c]
     --perturb-shape      udp_listen is not in the snapshot shape table                    → RED [7c]
     --perturb-ents       a WDTT report sent as an object of objects is walked as a list   → RED [7c]
     --perturb-entsname   …and its holder named by an `iface` field it does not carry      → RED [7c]
     --perturb-meshinv    the mesh allocator keeps its own short list again                → RED [7c]
     --perturb-listenall  the node reports connected sockets (outbound ports) as listeners → RED [7c]
     --perturb-tcpdns     the tunnel latency's clock starts before the name is resolved   → RED [3b]
     --perturb-tcpms      the trace reports no tunnel latency                              → RED [3b]
     --perturb-pair       generate takes the first /31 without the overlap test             → RED [7]
     --perturb-regen      Regenerate draws a new port/address/set like a new exit           → RED [7]
     --perturb-fleet      the pair is unique on this node only                             → RED [7]
     --perturb-xesc       a node's bucket is refused an encryption key                      → RED [8]
     --perturb-xpub       a key is kept against any node key                                → RED [8]
     --perturb-xgate      the read-time gate ignores the router key                         → RED [8]
     --perturb-xnkh       the read-time gate ignores the node key                           → RED [8]
     --perturb-xsave      an exits save leaves a removed exit's key on disk                 → RED [8]
     --perturb-xdrop      a node delete leaves its bucket and key                           → RED [8]
     --perturb-xlock      the prune reads the record outside the lock                       → RED [8]
     --perturb-xsec       a ciphertext that is no string is kept as its repr                → RED [8]
     --perturb-xstay      the pre-flight does not name the exits whose router config stays  → RED [8]
"""
import importlib.machinery, importlib.util, ipaddress, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
BASE = "eb25bad7"
PLANT = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), "")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def _plant(src, old, new):
    assert src.count(old) == 1, "anchor missing — this run would FALSE-PASS: " + old[:70]
    return src.replace(old, new)

PSRC = open(PANEL, encoding="utf-8").read()
NSRC = open(NODED, encoding="utf-8").read()
PLANTS = {
    "endpoint": ("n", '    if _in:\n        return "\\n".join(L) + "\\n"\n', ""),
    "portout": ("n", '    if _in:\n        L.append("ListenPort = "', '    if rec.get("listen_port"):\n        L.append("ListenPort = "'),
    "needep": ("n", 'rec["peer_key"] and (rec["endpoint"] or rec.get("listen_port"))):', 'rec["peer_key"] and rec["endpoint"]):'),
    "stamp": ("n", '        if _lps.get(str(_o.get("id") or "")):\n', '        if False:\n'),
    "nodewarp": ("n", '            if prov not in ("warp", "profile"):\n                res["errors"]', '            if False:\n                res["errors"]'),
    "reach": ("n", "                    return True\n        return False\n    except OSError:", "                    return True\n        return None\n    except OSError:"),
    "adopt": ("n", "        if name in own_exits:\n            continue\n", ""),
    "peers": ("p", "        if npeer != 1:\n", "        if False:\n"),
    "dialsrc": ("p", "    if dial_src:\n        return \"a dial-in exit dials nothing", "    if False:\n        return \"a dial-in exit dials nothing"),
    "clash": ("p", "        held = (ctx.get(\"ports\") or {}).get(port)\n", "        held = None\n"),
    "overlap": ("p", "                if net.version == 4 and a in net:\n", "                if False:\n"),
    "count": ("p", "    if not skip_exits:                                 # last:", "    if False:                                 # last:"),
    "bound": ("p", "            free = [p for p in DIALIN_PORTS if p not in _no and",
              "            free = [p for p in range(42821, 65536) if p not in _no and"),
    "dinrange": ("p", "DIALIN_PORTS = range(42821, 42900)", "DIALIN_PORTS = range(51820, 51900)"),
    "fwfall": ("p", "            if not free and _fw:\n", "            if False:\n"),
    "no51820": ("p", "- _no - {51820})", "- _no)"),
    "typedport": ("p", "        if _tp:                  # typed:", "        if False:                  # typed:"),
    "typedmtu": ("p", "        if _tm:\n            if not re.fullmatch", "        if False:\n            if not re.fullmatch"),
    "typedawg": ("p", '        _typed = g.get("awg") if isinstance(g.get("awg"), dict) and proto != "wg" else {}', '        _typed = {}'),
    "awgref": ("p", '        _ref = awg_template_refusal(_typed, perr("this exit"), gen3=proto == "awg3", was=None) if _typed else None', "        _ref = None"),
    "awgrules": ("p", '        _ref = awg_rules(awg, perr("this exit"), gen3=proto == "awg3") if proto != "wg" else None', "        _ref = None"),
    "rawphrase": ("p", '            return perr("UDP port {v1} is already used on this node by {v2}", v1=str(port), v2=held)', '            return perr("UDP port {v1} is already used on this node by {v2}", v1=str(port), v2=str(held))'),
    "s3omit": ("p", '            _tom = _tom - {"S1", "S2", "S3", "S4"}', '            pass'),
    "tplbad": ("p", "        _tv = {k: v for k, v in _tv.items() if not awg_value_refusal(k, v)}\n", ""),
    "s3tpl": ("p", '        if proto == "awg3":      # a 2.0 template', '        if False:      # a 2.0 template'),
    "meshband": ("p", "            _no = used | set(ctx.get(\"listen\") or ()) | set(ctx.get(\"mesh_band\") or ())",
                 "            _no = used | set(ctx.get(\"listen\") or ())"),
    "s4fit": ("p", '        if "S4" in awg and "S4" not in _uv and not mesh_s4_fits(awg["S4"], mtu):', '        if False:'),
    "meshref": ("p", "        if port in _mb:\n", "        if False:\n"),
    "asciiport": ("p", '            if not re.fullmatch(r"[0-9]{1,5}", _tp)', '            if not _tp.isdigit()'),
    "shape": ("p", '    "udp_listen": (list, int),', ''),
    "ents": ("p", '    for ifn, w in ents(snap.get("wdtt")):', '    for ifn, w in [((x or {}).get("iface") or "", x) for x in (snap.get("wdtt") or [])]:'),
    "entsname": ("p", '        return [(e.get("iface") or (k if isinstance(v, dict) else "") or "", e)', '        return [(e.get("iface") or "", e)'),
    "s3min": ("p", '        if proto == "awg3" and any(not str(_uv[k]).isdigit()', '        if False and any(not str(_uv[k]).isdigit()'),
    "fwref": ("p", "        if _fw and not any(a <= port <= b for a, b in _fw):\n            return perr(\"UDP port {v1} is outside",
              "        if False:\n            return perr(\"UDP port {v1} is outside"),
    "udplisten": ("p", '            _no = used | set(ctx.get("listen") or ())', '            _no = used | set()'),
    "typedlisten": ("p", "        if _tp:                  # typed:", "        if _tp and not (_tp.isdigit() and int(_tp) in ctx.get(\"listen\", ())):                  # typed:"),
    "listenall": ("n", '                    if len(f_) > 3 and f_[3] == "07":', '                    if len(f_) > 3:'),
    "tcpdns": ("n", "            _a = socket.getaddrinfo(s2.host, s2.port, socket.AF_INET, socket.SOCK_STREAM)[0][4]\n            _t = time.monotonic()\n",
               "            _t = time.monotonic()\n            _a = socket.getaddrinfo(s2.host, s2.port, socket.AF_INET, socket.SOCK_STREAM)[0][4]\n"),
    "tcpms": ("n", '"tcp_ms": getattr(c, "tcp_ms", None)}', '"tcp_ms": None}'),
    "meshinv": ("p", '    return set(_node_ports({"node_snaps": snaps or {}}, nodes, nid)) | {WDTT_RAW_PORT} | _host_listen((snaps or {}).get(nid))',
                '    return ({int((b.get("meta") or {}).get("listen_port")) for b in (((snaps or {}).get(nid) or {}).get("interfaces") or {}).values()'
                ' if str((b.get("meta") or {}).get("listen_port")).isdigit()} | {p for _x, p in _dialin_ports(nodes.get(nid) or {})})'),
    "pair": ("p", "if not any(n.overlaps(t) for t in taken)), None)", "), None)"),
    "regen": ("p", "    if exit_is_dialin({\"provider\": \"profile\", \"profile\": kept}):\n        port, node, awg, mtu",
              "    if False:\n        port, node, awg, mtu"),
    "fleet": ("p", "+ list(ctx.get(\"dialin_addrs\") or [])", ""),
    "coerce": ("p", '            _pv = str(e.get("provider") or "warp")\n', '            _pv = "warp" if str(e.get("provider") or "warp") != "profile" else "profile"\n'),
    "xesc": ("p", "                and sub_exit_node(uid) not in nodes:", "                and True:"),
    "xpub": ("p", "        if (pub, nkh) != live[eid]:\n", "        if pub != live[eid][0]:\n"),
    "xgate": ("p", "if isinstance(v, dict) and eid in live and (v.get(\"pub\"), v.get(\"nkh\")) == live[eid]}",
              "if isinstance(v, dict) and eid in live and v.get(\"nkh\") == live[eid][1]}"),
    "xnkh": ("p", "if isinstance(v, dict) and eid in live and (v.get(\"pub\"), v.get(\"nkh\")) == live[eid]}",
             "if isinstance(v, dict) and eid in live and v.get(\"pub\") == live[eid][0]}"),
    "xlock": ("p", "    with _api_lock:\n        live = sub_live_exits(nodes_load(", "    if True:\n        live = sub_live_exits(nodes_load("),
    "xsec": ("p", '("node", "exit", "pub", "nkh"))\n        sec = body.get("sec")\n', '("node", "exit", "pub", "nkh"))\n        sec = str(body.get("sec") or "")\n'),
    "xstay": ("p", 'for x in (nodes[nid].get("exits") or []) if isinstance(x, dict) and str(x.get("id")) in _xk]', 'for x in []]'),
    "xsave": ("p", '        if "exits" in body and os.path.exists(_sub_blob_path(deps, sub_exit_bucket(nid))):', "        if False:"),
    "xdrop": ("p", "        drop_sub_blobs(deps, sub_exit_bucket(nid))\n        _esc = load_sub_escrow(deps)\n        if _esc.pop(sub_exit_bucket(nid), None) is not None:",
              "        _esc = {}\n        if False:"),
}
if PLANT == "cand":
    _blk = NSRC[NSRC.index("        # ⚠️ ONE OF OUR OWN EXITS' DEVICES IS NEVER ADOPTABLE."):NSRC.index("        if name in own_exits:\n            continue\n") + len("        if name in own_exits:\n            continue\n")]
    NSRC = NSRC.replace(_blk, "")
    NSRC = _plant(NSRC, "        if _outbound_client_tunnel(conf, addr, ent_peers):\n", _blk + "        if _outbound_client_tunnel(conf, addr, ent_peers):\n")
elif PLANT in PLANTS:
    w, a, b = PLANTS[PLANT]
    if w == "n":
        NSRC = _plant(NSRC, a, b)
    else:
        PSRC = _plant(PSRC, a, b)
elif PLANT:
    sys.exit("unknown plant --perturb-" + PLANT)

_tmp = []
def _file(src, tag):
    fd, path = tempfile.mkstemp(suffix=".py", prefix="dialin-%s-" % tag, dir=HERE)
    os.write(fd, src.encode()); os.close(fd); _tmp.append(path)
    return path
def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m
def _git(path):
    r = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (BASE, path)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("cannot read %s:%s from git — this gate compares against it" % (BASE, path))
    return r.stdout
try:
    P = _load(_file(PSRC, "p"), "swgpanel")
    N = _load(_file(NSRC, "n"), "swgnoded")
    _REAL_TRACE = N._exit_trace          # [3b] runs the real one; the node pass below stubs it
    P0 = _load(_file(_git("swg-panel-server"), "p0"), "swgpanel0")
    N0 = _load(_file(_git("swg-noded"), "n0"), "swgnoded0")
finally:
    for _t in _tmp:
        os.unlink(_t)

REAL_REACH = N._exit_reach          # [2]'s harness stubs it; [3] asks the real one
K1, K2, K3 = ("QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=", "ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc=",
              "b3B0aW9uYWwtcHNrLWZvci10aGUtZGlhbC1pbi1leGk=")
AWG = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "76", "S2": "39", "H1": "1234567890", "H2": "1122334455",
       "H3": "2233445566", "H4": "3344556677"}

print("[1] the node's conf: a dial-in one byte-exact, a dial-out one unchanged")
DIN = {"priv": "PRIV", "address": "10.254.0.0", "mtu": 1420, "listen_port": 51820, "peer_key": "ROUTER", "psk": "PSK",
       "keepalive": 25, "endpoint": "", "awg": dict(AWG)}
want = ("[Interface]\nPrivateKey = PRIV\nAddress = 10.254.0.0/32\nMTU = 1420\nListenPort = 51820\nTable = off\n"
        + "".join("%s = %s\n" % (k, AWG[k]) for k in N.AWG_KEYS if k in AWG)
        + "\n[Peer]\nPublicKey = ROUTER\nPresharedKey = PSK\nAllowedIPs = 0.0.0.0/0\n")
got = N._exit_conf_text(DIN)
check("a dial-in conf is exactly the server side: ListenPort, 0.0.0.0/0, no Endpoint, no keepalive", got == want, got)
check("…a WireGuard one too (no AWG lines)", N._exit_conf_text(dict(DIN, awg={})) ==
      "[Interface]\nPrivateKey = PRIV\nAddress = 10.254.0.0/32\nMTU = 1420\nListenPort = 51820\nTable = off\n\n"
      "[Peer]\nPublicKey = ROUTER\nPresharedKey = PSK\nAllowedIPs = 0.0.0.0/0\n")
OUT = {"priv": "PRIV", "address": "10.9.0.4", "mtu": 1280, "peer_key": "SRV", "endpoint": "203.0.113.9:51820"}
matrix = [OUT, dict(OUT, psk="PSK"), dict(OUT, keepalive=25), dict(OUT, awg=dict(AWG)),
          dict(OUT, awg=dict(AWG, S3="10", S4="20", HeaderProtectionKey="HPK", RandomTrailers="1"), psk="P", keepalive=21),
          dict(OUT, endpoint="engage.cloudflareclient.com:2408", mtu=None),
          dict(OUT, listen_port=51820)]      # a port beside an Endpoint is dial-out, as eb25bad7 read it
for i, r in enumerate(matrix):
    check("dial-out conf #%d identical to %s's" % (i, BASE), N._exit_conf_text(r) == N0._exit_conf_text(r),
          (N._exit_conf_text(r), N0._exit_conf_text(r)))

print("\n[2] the node's pass: the record, the row, an unknown kind")
class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc
CALLS = {"run": [], "warp": 0, "redial": 0, "gai": 0}
def harness(desired, learned=""):
    d = tempfile.mkdtemp()
    N.EXIT_DIR = d
    CALLS.update(run=[], warp=0, redial=0, gai=0)
    def _run(a, **k):
        CALLS["run"].append(" ".join(map(str, a)))
        if len(a) > 1 and a[1] == "up":
            open(os.path.join(d, ".up"), "w").close()
        return _R("")
    N.run = _run
    N._scoped_up = lambda tool, conf: _run([tool, "up", conf])
    N._dev_link_state = lambda dev: "up" if os.path.exists(os.path.join(d, ".up")) else "absent"
    N._link_kind = lambda dev: "wg"
    N._exit_trace = lambda dev: {}
    N._exit_reach = lambda dev, *a, **k: False
    N._exit_ping = lambda *a, **k: None
    N._pass_forget = lambda *a, **k: None
    def _warp():
        CALLS["warp"] += 1
        return None, "registration refused (test)"
    N._warp_register = _warp
    def _redial(*a, **k):
        CALLS["redial"] += 1
    N._exit_redial = _redial
    real_gai = N.socket.getaddrinfo
    def _gai(*a, **k):
        CALLS["gai"] += 1
        return real_gai(*a, **k)
    N.socket.getaddrinfo = _gai
    dump = "PRIV\tPUB\t51820\toff\nROUTER\t(none)\t%s\t0.0.0.0/0\t%d\t0\t0\toff\n" % (learned or "(none)", 1 if learned else 0)
    N._dump_of = lambda cmd, dev: _R(dump)
    res = {"changed": 0, "errors": []}
    try:
        N.reconcile_exits(desired, res)
    finally:
        N.socket.getaddrinfo = real_gai
    return res, {x["id"]: x for x in N._EXITS["list"]}, d
PR = {"private_key": K1, "address": "10.254.0.0", "mtu": 1420, "peer_key": K2, "endpoint": "", "psk": "",
      "keepalive": 0, "awg": {}, "listen_port": 51820}
DX = {"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "profile", "profile": PR, "cfg_sig": "s1"}
res, rows, d = harness([DX], learned="198.51.100.7:40123")
row = rows.get("aabbccdd") or {}
check("a dial-in record is brought up, no error", row.get("up") is True and not row.get("error"), (row, res["errors"]))
_cp = os.path.join(d, "wgx-aabbccdd.conf")
conf = open(_cp).read() if os.path.exists(_cp) else ""
check("…its conf listens and dials nothing", "\nListenPort = 51820\n" in conf and "Endpoint" not in conf, conf)
check("…the row reports the router's learned endpoint", row.get("endpoint") == "198.51.100.7:40123", row)
check("…and the port", row.get("listen_port") == 51820, row)
res, rows, d = harness([DX])
check("before the router dials, the learned endpoint is empty", (rows.get("aabbccdd") or {}).get("endpoint") == "", rows)
res, rows, d = harness([dict(DX, profile=dict(PR, private_key=""))])
row = rows.get("aabbccdd") or {}
check("a dial-in record the node refuses still carries its port (so the panel does not read 'too old')",
      bool(row.get("error")) and row.get("listen_port") == 51820, row)
check("…and does not say an endpoint is missing (a dial-in exit has none)", "endpoint" not in str(row.get("error")), row)
res, rows, d = harness([dict(DX, profile=dict(PR, endpoint="203.0.113.9:51820", listen_port=None))])
row = rows.get("aabbccdd") or {}
check("a dial-out row carries no listen_port and reports its own endpoint",
      "listen_port" not in row and row.get("endpoint") == "203.0.113.9:51820", row)
res, rows, d = harness([dict(DX, provider="socks5", profile=None)])
row = rows.get("aabbccdd") or {}
check("an unknown kind is refused on the row", row.get("up") is False and "does not know" in str(row.get("error")), row)
check("…and no WARP account is registered for it", CALLS["warp"] == 0, CALLS["warp"])
res, rows, d = harness([dict(DX, provider="socks5", profile=None, down=True)])
row = rows.get("aabbccdd") or {}
check("…a paused one reads paused, not failed", row.get("paused") is True and not row.get("error"), row)
res, rows, d = harness([dict(DX, provider="", profile=None)])
check("an EMPTY provider is still the legacy WARP default (it tries to register)", CALLS["warp"] == 1, CALLS["warp"])

print("\n[3] health: nothing answers through a no-endpoint device → dead, never 'can't tell'")
r = REAL_REACH("lo", targets=[("192.0.2.1", 443)], timeout=0.5)
check("a reach nothing answers reads False", r is False, r)
N._EXIT_HEALTH.clear()
st = None
for t in (0, 10, 20, 31):
    st = N._exit_judge("wgx-aabbccdd", {}, now=1000 + t, reach=lambda dev: REAL_REACH("lo", targets=[("192.0.2.1", 443)], timeout=0.3))
check("three failed probes over 30 s → dead", bool(st and st["dead"]), st)
res, rows, d = harness([DX])
check("a dial-in pass looks no endpoint name up and never redials", CALLS["gai"] == 0 and CALLS["redial"] == 0, CALLS)

print("\n[3b] the latency through the tunnel (S9e)")
import ssl as _ssl, socket as _so, threading as _th, time as _tm, http.server as _hs
_cd = tempfile.mkdtemp(prefix="tcpms-")
subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1",
                "-subj", "/CN=www.cloudflare.com", "-keyout", os.path.join(_cd, "k.pem"), "-out", os.path.join(_cd, "c.pem")],
               capture_output=True, check=True)
class _H(_hs.BaseHTTPRequestHandler):
    def do_GET(self):
        b = b"ip=198.51.100.7\nloc=XX\nwarp=off\n"
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
_srv = _hs.HTTPServer(("127.0.0.1", 0), _H)
_sc = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER); _sc.load_cert_chain(os.path.join(_cd, "c.pem"), os.path.join(_cd, "k.pem"))
_srv.socket = _sc.wrap_socket(_srv.socket, server_side=True)
_th.Thread(target=_srv.serve_forever, daemon=True).start()
_gai = _so.getaddrinfo
def _slow_gai(host, port, *a, **k):          # the node's resolver, held up: a clock that includes it reads ≥ 200 ms
    if host == "www.cloudflare.com":
        _tm.sleep(0.2)
        return _gai("127.0.0.1", _srv.server_address[1], *a, **k)
    return _gai(host, port, *a, **k)
_cli = _ssl.create_default_context(); _cli.check_hostname = False; _cli.verify_mode = _ssl.CERT_NONE
_saved_tls = N._exit_tls
_so.getaddrinfo, N._exit_tls = _slow_gai, (lambda: _cli)
try:
    _tr = _REAL_TRACE("lo")
finally:
    _so.getaddrinfo, N._exit_tls = _gai, _saved_tls
    _srv.shutdown(); _srv.server_close()
    import shutil as _shu; _shu.rmtree(_cd, ignore_errors=True)   # its key with it (S9e review F27)
check("the trace through the device still reads the exit's IP", _tr.get("ip") == "198.51.100.7", _tr)
check("…and times the TCP handshake alone — a number, the 200 ms resolver not in it", isinstance(_tr.get("tcp_ms"), (int, float))
      and 0 <= _tr["tcp_ms"] < 100, _tr)
check("…while the whole request (rtt_ms) still includes it", (_tr.get("rtt_ms") or 0) >= 200, _tr)

print("\n[4] adoption: our own dial-in device is never offered, and the exit candidates are unchanged")
def cands(exit_dir_confs):
    d = tempfile.mkdtemp()
    for f in exit_dir_confs:
        open(os.path.join(d, f), "w").close()
    N.EXIT_DIR = d
    N._pass_cached = lambda key, fn: fn()
    N._wdtt_load = lambda: {}
    N._csqtt_load = lambda: {}
    N._wdtt_procs = lambda: []
    N._awg_conf_dirs = lambda: []
    N.WG_CONF_DIRS = []
    N.WG_SOCK_DIRS = []
    N._cand_conf = lambda name: None
    N._all_links = lambda: {}
    N.wdtt_foreign_probe = lambda name: None
    N._add_tun_exit_cands = lambda seen: None
    dumps = {   # a dial-in device before its first handshake; a dial-out exit; a server the operator runs
        "wgx-aabbccdd": "PRIV\tPUB\t51820\toff\nROUTER\t(none)\t(none)\t0.0.0.0/0\t0\t0\t0\toff\n",
        "wgx-11223344": "PRIV\tPUB\t0\toff\nSRV\t(none)\t203.0.113.9:51820\t0.0.0.0/0\t5\t10\t10\toff\n",
        "wg-home": "PRIV\tPUB\t51900\toff\nCLI\t(none)\t198.51.100.2:5000\t10.66.0.2/32\t5\t10\t10\toff\n"}
    def _run(a, **k):
        if a[-2:] == ["show", "interfaces"] and a[0] == "wg":
            return _R(" ".join(sorted(dumps)))
        if a[:4] == ["ip", "-4", "-o", "addr"]:
            return _R("5: wgx-aabbccdd    inet 10.254.0.0/32 scope global\n6: wgx-11223344    inet 172.16.0.2/32 scope global\n"
                      "7: wg-home    inet 10.66.0.1/24 scope global\n")
        return _R("", 1)
    N.run = _run
    N._wgcmd = lambda tool: list(tool)
    N._dump_of = lambda cmd, name: _R(dumps.get(name, ""), 0 if name in dumps and cmd == ["wg"] else 1)
    out = N.iface_candidates({"interfaces": {}})
    return [x["name"] for x in out], [x.get("name") for x in N._EXIT_CAND["list"]]
names, ec = cands(["wgx-aabbccdd.conf", "wgx-11223344.conf"])
names0, ec0 = cands([])
check("the dial-in device before its first handshake is not offered for adoption", "wgx-aabbccdd" not in names, names)
check("…a server the operator runs still is", "wg-home" in names, names)
check("the exit-candidate list is identical with and without the skip", ec == ec0 and "wgx-11223344" in ec, (ec, ec0))

print("\n[5] the panel's parser: dial-out exactly as before, dial-in from a server config")
def conf(iface_extra="", peers=1, endpoint=True, ka=""):
    t = "[Interface]\nPrivateKey = %s\nAddress = 10.254.0.0/31, fd00::1/64\nMTU = 1420\n%s" % (K1, iface_extra)
    for i in range(peers):
        t += "\n[Peer]\nPublicKey = %s\nPresharedKey = %s\nAllowedIPs = 10.254.0.1/32\n" % (K2 if i == 0 else K3, K3)
        if endpoint:
            t += "Endpoint = 203.0.113.9:51820\n"
        if ka:
            t += "PersistentKeepalive = %s\n" % ka
    return t
OUTS = [conf(), conf(ka="25"), conf(ka="25-35"), conf("ListenPort = 51820\n"), conf("Jc = 4\nS1 = 76\nH1 = 1\n"),
        conf(peers=2)]
for i, t in enumerate(OUTS):
    a, b = P.parse_wg_profile(t), P0.parse_wg_profile(t)
    check("dial-out profile #%d parses to %s's dict exactly" % (i, BASE), a == b, (a, b))
pr, e = P.parse_wg_profile(conf("ListenPort = 51820\n", endpoint=False, ka="25"))
check("ListenPort without Endpoint → a dial-in profile", e == "" and pr and pr.get("listen_port") == 51820
      and pr.get("endpoint") == "" and pr.get("keepalive") == 0, (pr, e))
check("…the peer's AllowedIPs is not stored", pr and "allowed" not in str(pr).lower(), pr)
pr2, e2 = P.parse_wg_profile(conf(endpoint=False))
check("neither Endpoint nor ListenPort → today's refusal", pr2 is None and e2 == P0.parse_wg_profile(conf(endpoint=False))[1], e2)
check("two peers on a dial-in config → refused", P.parse_wg_profile(conf("ListenPort = 51820\n", peers=2, endpoint=False))[1]
      == "a dial-in exit has exactly one peer — the upstream")
check("a ListenPort that is not a port → refused", P.parse_wg_profile(conf("ListenPort = 70000\n", endpoint=False))[1]
      == "the profile's ListenPort is not a usable port")
check("…a non-ASCII digit too, refused rather than raising", P.parse_wg_profile(conf("ListenPort = \u00b2\n", endpoint=False))[1]
      == "the profile's ListenPort is not a usable port")

print("\n[6] the panel's save")
NID = "n1"
SUBNET = "10.254.4.0/24"
def world(exits=()):
    nodes = {NID: {"name": "lab", "exits": list(exits), "links": {}, "ifaces": {}}}
    deps = {"node_snaps": {NID: {"interfaces": {"wg0": {"meta": {"listen_port": 51821, "subnet": SUBNET}}}}},
            "panel_settings": {}}
    return deps, nodes
def save(xs, stored=(), **kw):
    deps, nodes = world(stored)
    return P._validate_exits(xs, nodes[NID], prev=list(stored), gen_snap={}, dialin=P._dialin_ctx(deps, nodes, NID), **kw)
def din(port=51820, addr="10.254.0.0", xid="aabbccdd", **o):
    t = ("[Interface]\nPrivateKey = %s\nAddress = %s/31\nListenPort = %d\n\n[Peer]\nPublicKey = %s\n" % (K1, addr, port, K2))
    return dict({"id": xid, "producer": "imported", "provider": "profile", "profile_text": t}, **o)
ok, e = save([din()])
check("a dial-in paste is saved, its port in the profile", e is None and ok and ok[0]["profile"].get("listen_port") == 51820, e)
c, e = save([din(dial_src="192.0.2.10")])
check("dial_src on a dial-in exit → refused", c is None and "dials nothing" in str(e), e)
c, e = save([din(port=51821)])
check("a port an interface holds → refused, naming it", c is None and "wg0" in str((e or {}).get("error")), e)
c, e = save([din(port=P.WDTT_RAW_PORT)])
check("RAW-IP's reserved port → refused", c is None and "RAW-IP" in str((e or {}).get("error")), e)
_rv = ((e or {}).get("error_vars") or {}).get("v2")
_ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("…its holder travels as a phrase the browser translates, and RU has it (no English inside a RU sentence)",
      isinstance(_rv, dict) and _rv.get("error_key") == "RAW-IP (reserved)" and '"RAW-IP (reserved)":' in _ru, _rv)
c, e = save([din(), din(xid="11223344", addr="10.254.0.2")])
check("two dial-in exits on one port → refused", c is None and "one port" in str((e or {}).get("error")), e)
c, e = save([din(), din(xid="11223344", port=51830)])
check("two dial-in exits on one address → refused", c is None and "one address" in str((e or {}).get("error")), e)
c, e = save([din(addr="10.254.4.9")])
check("an address inside an interface subnet → refused, naming it", c is None and "wg0" in str((e or {}).get("error")), e)
_deps, _ = world()
_pool = str(P.node_mesh_cfg(_deps, {}).get("subnet") or "")
_pa = str(next(ipaddress.ip_network(_pool, strict=False).hosts())) if _pool else ""
c, e = save([din(addr=_pa)]) if _pa else (None, {"error": "mesh pool"})
check("an address inside the mesh pool → refused", c is None and "mesh pool" in str((e or {}).get("error")), (e, _pool))
stored = [dict(ok[0])]
deps, nodes = world(stored)
deps["node_snaps"][NID]["interfaces"]["wg9"] = {"meta": {"listen_port": 51820}}   # something took the port since
c, e = P._validate_exits([{k: v for k, v in din().items() if k != "profile_text"} | {"label": "renamed"}], nodes[NID],
                         prev=stored, gen_snap={}, dialin=P._dialin_ctx(deps, nodes, NID))
check("a stored dial-in exit stays savable when its port is taken later", e is None, e)
deps, nodes = world(stored)
check("the node's port table names the dial-in exit", "dial-in exit" in str(P._node_ports(deps, nodes, NID).get(51820)),
      P._node_ports(deps, nodes, NID))
check("…an interface create on its port is refused", bool(P._port_conflict(deps, nodes, NID, 51820)))
check("…and a mesh link never takes it", 51820 in P._used_ports(nodes, deps["node_snaps"], NID))
c, e = save([{"id": "aabbccdd", "producer": "imported", "provider": "socks5"}])
check("an unknown kind is refused, not coerced to WARP", c is None and "does not know" in str((e or {}).get("error")), (c, e))
odd = {"id": "aabbccdd", "producer": "imported", "provider": "socks5", "device": "wgx-aabbccdd", "label": "x", "socks": {"h": 1}}
c, e = save([dict(odd)], stored=[dict(odd)])
check("…but one already stored is kept (the list stays savable)", e is None and c and {k: c[0].get(k) for k in odd} == odd, (c, e))
c, e = save([dict(odd, enabled=False, label="y")], stored=[dict(odd)])
check("…and the grid's switch and title still apply to it", e is None and c[0]["enabled"] is False and c[0]["label"] == "y"
      and c[0].get("socks") == {"h": 1} and c[0]["cfg_sig"] == P.exit_cfg_sig(c[0]), (c, e))
dout = {"id": "aabbccdd", "producer": "imported", "provider": "profile",
        "profile": {"private_key": K1, "address": "10.254.4.9", "peer_key": K2, "endpoint": "203.0.113.9:51820", "mtu": 1280,
                    "psk": "", "keepalive": 0, "awg": {}}}
c, e = save([din(addr="10.254.4.9")], stored=[dout])
check("a stored dial-OUT exit re-pasted as dial-in with the same address is checked like a new one", c is None
      and "wg0" in str((e or {}).get("error")), (c, e))
deps, nodes = world([dict(ok[0], label="home", profile=dict(ok[0]["profile"], listen_port=13231))])
deps["node_snaps"][NID]["udp_ports"] = "51820-51899"
iss = [str((x or {}).get("error") if isinstance(x, dict) else x) for x in P._node_issues(nodes[NID], deps["node_snaps"][NID])]
check("a dial-in port outside the node's declared firewall range is a node issue", any("dial-in exit" in x and "13231" in x for x in iss), iss)
w, e = save([{"id": "aabbccdd", "producer": "imported", "provider": "warp"}, {"id": "11223344", "producer": "imported"}])
check("warp and an empty provider are WARP", e is None and [x["provider"] for x in w] == ["warp", "warp"], (w, e))

print("\n[7] generate (S9b)")
def _p(c): return (c or [{}])[-1].get("profile") or {}
import base64 as _b64
_k = lambda: _b64.b64encode(os.urandom(32)).decode()
S31 = {"datapath": {"awg": {"gen": {"module": "3.1", "fallback": None, "tools": "3.1"}}}}
S20 = {"datapath": {"awg": {"gen": {"module": "2.0", "fallback": None, "tools": "3.1"}}}}
def gen(proto, xid="aabbccdd", stored=(), snap=S31, ports=None, nets=None, keys=None, prep=None, typed=None):
    deps, nodes = world(stored)
    if prep:
        prep(deps, nodes)
    ctx = P._dialin_ctx(deps, nodes, NID)
    if ports is not None:
        ctx["ports"] = ports
    if nets is not None:
        ctx["nets"] = nets
    kk = keys or {"private_key": _k(), "peer_key": _k(), "psk": _k()}
    xs = [dict(x) for x in stored if x.get("id") != xid] + [{"id": xid, "producer": "imported", "provider": "profile",
                                                             "dialin_gen": dict(kk, proto=proto, **(typed or {}))}]
    return P._validate_exits(xs, nodes[NID], prev=list(stored), gen_snap=snap, dialin=ctx), kk
(c, e), kk = gen("wg")
g = (c or [{}])[-1].get("profile") or {}
check("a generated exit gets a free port of 42821–42899 — not WireGuard's 51820", e is None and 42821 <= g.get("listen_port", 0) <= 42899, (e, g))
_drawn = {(gen("wg")[0][0] or [{}])[-1].get("profile", {}).get("listen_port") for _ in range(12)}
check("…drawn at random, not the first free one", len(_drawn) > 1 and all(isinstance(x, int) and 42821 <= x <= 42899 for x in _drawn), _drawn)
check("…a /31's .0 clear of wg0's 10.254.4.0/24", g.get("address") == "10.254.0.0", g)
check("…the keys sent, a WireGuard set, MTU 1280", g.get("private_key") == kk["private_key"] and g.get("peer_key") == kk["peer_key"]
      and g.get("psk") == kk["psk"] and g.get("awg") == {} and g.get("mtu") == 1280, g)
check("…and the request field is never stored", "dialin_gen" not in (c or [{}])[-1], (c or [{}])[-1])
_txt = P._dialin_generate(dict(kk, proto="wg", listen_port=g.get("listen_port")), {}, "aabbccdd", [], {}, P._dialin_ctx(world()[0], world()[1], NID))[0]
check("…in the paste's shape: what it stored is exactly what its own server config parses to", P.parse_wg_profile(_txt)[0] == g,
      (P.parse_wg_profile(_txt)[0], g))
(c, e), _ = gen("wg", ports={p: "x" for p in range(42821, 42900)})
check("a full 42821–42899 → refused, never a port outside it", c is None and "42821–42899" in str(e), (c and c[-1].get("profile"), e))
(c, e), _ = gen("wg", nets=[("wg0", ipaddress.ip_network("10.254.0.0/17"))])
check("the pair skips a subnet the node holds", e is None and c[-1]["profile"]["address"] == "10.254.128.0", (e, c and c[-1]["profile"]))
first = dict(ok[0])                                     # [6]'s stored paste: port 51820, address 10.254.0.0
(c, e), _ = gen("wg", xid="11223344", stored=[first])
g2 = (c or [{}])[-1].get("profile") or {}
check("a second generated exit takes another port and another pair", e is None and 42821 <= g2.get("listen_port", 0) <= 42899
      and g2.get("address") == "10.254.0.2", (e, g2))
_in = dict(first, profile=dict(first["profile"], listen_port=42850))       # another dial-in exit INSIDE the range (review F15)
(c, e), _ = gen("wg", xid="11223344", stored=[_in], ports={p: "x" for p in range(42821, 42900) if p not in (42850, 42851)})
check("…never the port another stored dial-in exit holds (42850 taken, 42851 the one left)",
      e is None and _p(c).get("listen_port") == 42851, (e, _p(c)))
(c, e), _ = gen("awg2")
check("AmneziaWG 2.0: the interfaces' generator set, no header protection", e is None and (c[-1]["profile"]["awg"] or {}).get("S1")
      and "HeaderProtectionKey" not in c[-1]["profile"]["awg"], (e, c and c[-1]["profile"]["awg"]))
(c, e), _ = gen("awg3")
check("AmneziaWG 3.1 on a 3.1 node: a HeaderProtectionKey", e is None and (c[-1]["profile"]["awg"] or {}).get("HeaderProtectionKey"), e)
(c, e), _ = gen("awg3", snap=S20)
check("…refused on a 2.0 node, as a 3.1 paste is", c is None and isinstance(e, dict), e)
(c, e), _ = gen("socks")
check("an unknown protocol → refused", c is None and "choose WireGuard" in str(e), e)
(c, e), _ = gen("wg", keys={"private_key": "x", "peer_key": _k(), "psk": ""})
check("a key that is not a key → refused", c is None and "not usable keys" in str(e), e)
def _other_node(deps, nodes):          # another node's dial-in exit already holds 10.254.0.0 (one router may serve both)
    nodes["n2"] = {"name": "far", "exits": [{"id": "99999999", "provider": "profile", "producer": "imported",
                                             "profile": {"address": "10.254.0.0", "listen_port": 51820, "endpoint": ""}}]}
(c, e), _ = gen("wg", prep=_other_node)
check("the pair is unique across the fleet, not only this node", e is None and c[-1]["profile"]["address"] == "10.254.0.2",
      (e, c and c[-1]["profile"]))
def _unadopted(deps, nodes):          # servers the operator runs by hand, not adopted, on all of 42821–42898
    deps["node_snaps"][NID]["iface_candidates"] = [{"name": "wg-hand%d" % p, "listen_port": p} for p in range(42821, 42899)]
(c, e), _ = gen("wg", prep=_unadopted)
check("an unadopted server's port is taken too", e is None and c[-1]["profile"]["listen_port"] == 42899, (e, c and c[-1]["profile"]))
def _declared(spec):                  # a NixOS node that opens only what its module declares
    return lambda deps, nodes: deps["node_snaps"][NID].__setitem__("udp_ports", spec)
(c, e), _ = gen("wg", prep=_declared("42821-42899,56000-56099"))
check("a port is drawn inside the node's declared firewall range", e is None and 42821 <= c[-1]["profile"]["listen_port"] <= 42899,
      (e, c and c[-1]["profile"]))
(c, e), _ = gen("wg", prep=_declared("51820-51830"))
check("a declared firewall without 42821–42899 (set up before it): a free port inside what it declares — not 51820, not wg0's",
      e is None and 51822 <= c[-1]["profile"]["listen_port"] <= 51830, (e, c and c[-1]["profile"]))
(c, e), _ = gen("wg", prep=_declared("51820-51821"))
check("…and none left there (51821 is wg0's, 51820 is never drawn) → refused", c is None and "42821–42899" in str(e), (e, c and c[-1]["profile"]))
def _tpl(deps, nodes):                # the operator's interface defaults: Jc 7, and no I1–I5 (their router cannot take them)
    deps["panel_settings"] = {"interface_defaults": {"awg_params": {"Jc": "7", **{k: "-" for k in ("I1", "I2", "I3", "I4", "I5")}}}}
(c, e), _ = gen("awg2", prep=_tpl)
_a = (c or [{}])[-1].get("profile", {}).get("awg") or {}
check("AmneziaWG 2.0 follows the interface-defaults template: its values, and its '-' keys left out", e is None
      and str(_a.get("Jc")) == "7" and not any(k in _a for k in ("I1", "I2", "I3", "I4", "I5")) and _a.get("S1"), (e, _a))
_pasted = dict(first, profile=dict(first["profile"], address="10.254.0.0"))        # its router is 10.254.0.1
(c, e), _ = gen("wg", xid="11223344", stored=[_pasted])
check("a new pair avoids another exit's router address too", e is None and c[-1]["profile"]["address"] == "10.254.0.2", (e, c and c[-1]["profile"]))
import time as _time
_t0 = _time.monotonic()
(c, e), _ = gen("wg", nets=[("big", ipaddress.ip_network("10.0.0.0/8"))])
check("a subnet covering 10.254.0.0/16 is refused at once, not after 32768 tests", c is None and "address pair" in str(e)
      and _time.monotonic() - _t0 < 0.5, (e, _time.monotonic() - _t0))
_edge = dict(first, profile=dict(first["profile"], address="255.255.255.255"))
(c, e), _ = gen(None, stored=[_edge])
check("Regenerate on a pasted exit at 255.255.255.255 is not a 500", e is None, e)
_mid = dict(first, profile=dict(first["profile"], listen_port=51877, address="10.254.200.6"))   # not what a fresh draw yields
(c, e), _ = gen(None, stored=[_mid])
check("Regenerate keeps a port and an address a fresh draw would not pick", e is None
      and (c[-1]["profile"]["listen_port"], c[-1]["profile"]["address"]) == (51877, "10.254.200.6"), (e, c and c[-1]["profile"]))
(c3, e3), _ = gen("awg3")
st3 = c3[-1]
(c, e), kk2 = gen(None, stored=[st3])
r = (c or [{}])[-1].get("profile") or {}
check("Regenerate keeps the port, the address, the MTU and the AmneziaWG set", e is None and all(
      r.get(x) == st3["profile"].get(x) for x in ("listen_port", "address", "mtu", "awg")), (e, r, st3["profile"]))
check("…and takes the new keys", r.get("private_key") == kk2["private_key"] and r.get("peer_key") == kk2["peer_key"]
      and r.get("psk") == kk2["psk"], r)

print("\n[7b] what the operator typed (S9e)")
(c, e), _ = gen("wg", typed={"listen_port": "443", "mtu": "1380"})
check("a typed port and MTU are used", e is None and _p(c).get("listen_port") == 443 and _p(c).get("mtu") == 1380, (e, _p(c)))
(c, e), _ = gen("wg", typed={"listen_port": "51821"})
check("a typed port another holder has → refused, naming it (wg0)", c is None and "wg0" in str(e), e)
(c, e), _ = gen("wg", typed={"listen_port": "443"}, prep=_declared("42821-42899"))
check("a typed port outside the node's declared firewall → refused", c is None and "outside this node's declared firewall" in str(e), e)
(c, e), _ = gen("wg", typed={"listen_port": "42850"}, prep=_declared("42821-42899"))
check("…one inside it is used", e is None and _p(c).get("listen_port") == 42850, (e, _p(c)))
(c, e), _ = gen("wg", typed={"listen_port": "port"})
check("a port that is no number → refused", c is None and "1 to 65535" in str(e), e)
(c, e), _ = gen("wg", typed={"mtu": "50"})
check("an MTU out of range → refused", c is None and "576 to 1500" in str(e), e)
(c, e), _ = gen("wg", typed={"mtu": "1501"})
check("…and one past what the parser keeps (1500) → refused, never clamped in silence", c is None and "576 to 1500" in str(e), e)
try:                                  # "²" is str.isdigit() and int() refuses it: a 500, not a refusal (review F10)
    (c, e), _ = gen("wg", typed={"listen_port": "²"})
except Exception as _x:
    c, e = None, "raised %r" % _x
check("a port of a non-ASCII digit → refused, not a 500", c is None and "1 to 65535" in str(e), e)
(c, e), _ = gen("wg", typed={"listen_port": "10000"})
check("a typed port in the system mesh band → refused, as an interface's is", c is None and "reserved system mesh range" in str(e), e)
_fb = {_p(gen("wg", prep=_declared("9999-10098,51830-51831"))[0][0]).get("listen_port") for _ in range(6)}
check("…and the declared-firewall fallback never draws from it", _fb <= {51830, 51831}, _fb)
_s4 = {int((_p(gen("awg2", typed={"mtu": "1400"})[0][0]).get("awg") or {}).get("S4") or 999) for _ in range(8)}
check("a drawn S4 fits the typed MTU (1400: room %s), as a mesh link's does (review F3)" % P.mesh_s4_room(1400),
      all(x <= P.mesh_s4_room(1400) for x in _s4), _s4)
(c, e), _ = gen("awg2", typed={"mtu": "1400", "awg": {"S4": "90"}})
check("…a typed S4 is kept as typed", e is None and str((_p(c).get("awg") or {}).get("S4")) == "90", (e, _p(c).get("awg")))
def _tpl_nojc(deps, nodes):           # a template with Jc/Jmin/Jmax none (a valid one)
    deps["panel_settings"] = {"interface_defaults": {"awg_params": {"Jc": "-", "Jmin": "-", "Jmax": "-"}}}
(c, e), _ = gen("awg2", typed={"awg": {"Jc": "5"}}, prep=_tpl_nojc)
check("the set it makes keeps the rules: a typed Jc beside the template's '-' Jmin/Jmax → refused (review F13)",
      c is None and "go together" in str(e), (e, _p(c).get("awg")))
def _tpl_s3(deps, nodes):             # a 2.0 template's S3 under 12
    deps["panel_settings"] = {"interface_defaults": {"awg_params": {"S3": "5"}}}
(c, e), _ = gen("awg3", typed={"awg": {"S1": "20", "S2": "30"}}, prep=_tpl_s3)
_a = _p(c).get("awg") or {}
check("3.1: a template's S under 12 does not re-draw the typed S1/S2 (review F8)", e is None and str(_a.get("S1")) == "20"
      and str(_a.get("S2")) == "30" and int(_a.get("S3") or 0) >= 12, (e, _a))
def _tpl_s1none(deps, nodes):          # a 2.0 template with S1 as none — a 3.1 exit needs all four (verify F58)
    deps["panel_settings"] = {"interface_defaults": {"awg_params": {"S1": "-"}}}
(c, e), _ = gen("awg3", prep=_tpl_s1none)
_a = _p(c).get("awg") or {}
check("3.1: a template S1 of '-' is drawn, not kept as no line (header protection needs all four) — not refused",
      e is None and str(_a.get("S1") or "").isdigit() and int(_a["S1"]) >= 12, (e, _a))
def _tpl_badi(deps, nodes):           # a template I1 no app reads, stored before template saves were checked
    deps["panel_settings"] = {"interface_defaults": {"awg_params": {"Jc": "7", "I1": "<c>"}}}
(c, e), _ = gen("awg2", prep=_tpl_badi)
_a = _p(c).get("awg") or {}
check("a template I1 no app reads is drawn, as a blank is — Generate is not refused over a cell the sheet does not show",
      e is None and _a.get("I1") != "<c>" and str(_a.get("Jc")) == "7", (e, _a))
(c, e), _ = gen("awg2", typed={"awg": {"Jc": "9", "S1": "33", "I1": "-"}})
_a = _p(c).get("awg") or {}
check("AmneziaWG cells: a value used, '-' no such line, a blank drawn", e is None and str(_a.get("Jc")) == "9" and str(_a.get("S1")) == "33"
      and "I1" not in _a and _a.get("S2") and _a.get("H1"), (e, _a))
(c, e), _ = gen("awg2", typed={"awg": {"I1": "<r 16>"}}, prep=_tpl)
_a = _p(c).get("awg") or {}
check("…a typed value beats the template's '-' (I1), the template's other '-' keys stay out", e is None and _a.get("I1") == "<r 16>"
      and not any(k in _a for k in ("I2", "I3", "I4", "I5")) and str(_a.get("Jc")) == "7", (e, _a))
(c, e), _ = gen("awg2", typed={"awg": {"Jc": "-"}})
check("…Jc, Jmin and Jmax go together → refused", c is None and "go together" in str(e), e)
(c, e), _ = gen("awg2", typed={"awg": {"I1": "<c>"}})
check("…an I-line no app reads (<c>) → refused, naming I1", c is None and str((e or {}).get("error") if isinstance(e, dict) else e).startswith("I1"), e)
(c, e), _ = gen("awg3", typed={"awg": {"S1": "5"}})
check("…AmneziaWG 3.1: an S under 12 → refused, not re-drawn behind the operator's back", c is None and "at least 12" in str(e), e)
(c, e), _ = gen("awg3", typed={"awg": {"S1": "40", "RekeyTimeout": "7"}})
_a = _p(c).get("awg") or {}
check("…3.1: typed cells kept, the 3.1 set and a key around them", e is None and str(_a.get("S1")) == "40"
      and str(_a.get("RekeyTimeout")) == "7" and _a.get("HeaderProtectionKey"), (e, _a))
(c, e), _ = gen("wg", typed={"awg": {"Jc": "9"}})
check("WireGuard takes no AmneziaWG cells", e is None and _p(c).get("awg") == {}, (e, _p(c)))
_st = dict(first, profile=dict(first["profile"], listen_port=42850))
(c, e), _ = gen(None, stored=[_st], prep=_declared("51820-51899"))
check("Regenerate keeps a stored port outside a declared firewall (unchanged: tolerated)", e is None and _p(c).get("listen_port") == 42850, e)

print("\n[7c] the node's port inventory (S9e)")
def _listen(ports):
    return lambda deps, nodes: deps["node_snaps"][NID].__setitem__("udp_listen", ports)
deps, nodes = world()
deps["node_snaps"][NID]["udp_listen"] = [53, 443, 51821, P.WDTT_RAW_PORT]
_inv = P._node_ports(deps, nodes, NID)
check("a port the host listens on is not a holder in the inventory every door asks (only wg0's own)", 443 not in _inv
      and P.WDTT_RAW_PORT not in _inv and _inv.get(51821) == "wg0", _inv)
check("…an interface create there is not refused for it (a listener may be a client socket, or ours just moved)",
      not P._port_conflict(deps, nodes, NID, 443))
(c, e), _ = gen("wg", typed={"listen_port": "443"}, prep=_listen([443]))
check("…nor a typed dial-in port", e is None and _p(c).get("listen_port") == 443, e)
def _busy(deps, nodes):
    deps["node_snaps"][NID]["iface_candidates"] = [{"name": "h%d" % p, "listen_port": p} for p in range(42821, 42899)]
    deps["node_snaps"][NID]["udp_listen"] = [42899]
(c, e), _ = gen("wg", prep=_busy)
check("…and never drawn (42899, the only one left, is a listener)", c is None and "42821–42899" in str(e), (e, c and _p(c)))
deps, nodes = world([dict(ok[0])])                      # a stored dial-in exit on 51820, live: its socket is a listener too
deps["node_snaps"][NID]["udp_listen"] = [51820]
check("a dial-in exit's own live port is named after the exit",
      "dial-in exit" in str(P._node_ports(deps, nodes, NID).get(51820))
      and P._dialin_ctx(deps, nodes, NID)["ports"].get(51820) is None, P._dialin_ctx(deps, nodes, NID)["ports"])
deps, nodes = world()
nodes[NID]["wdtt"] = {"wdtt1": {"listen": "0.0.0.0:10001", "wg_port": 10002}}
nodes[NID]["csqtt"] = {"csqtt1": {"listen": "0.0.0.0:10003"}}
nodes[NID]["ifaces"] = {"awg9": {"desired_port": 10004}}
deps["node_snaps"][NID]["udp_listen"] = [10005]
_u = P._used_ports(nodes, deps["node_snaps"], NID)
check("the mesh link allocator asks the same inventory: WDTT and its internal WG port, csqtt, a created interface, a listener, RAW-IP",
      {10001, 10002, 10003, 10004, 10005, P.WDTT_RAW_PORT} <= _u, sorted(_u))
check("…so the first link port off 10000 skips them", P._alloc_port(_u, 10000) == 10000 and P._alloc_port(_u, 10001) == 10006, sorted(_u))
deps["node_snaps"][NID]["wdtt"] = {"w1": {"listen": "0.0.0.0:10007", "wg_port": 10008}}   # an object of objects, keyed by iface
try:
    _u = P._used_ports(nodes, deps["node_snaps"], NID)
except Exception as _x:
    _u = "raised %r" % _x
check("…a WDTT report sent as an object of objects (sanitise takes it) is walked, not raised on inside reconcile_mesh",
      isinstance(_u, set) and {10007, 10008} <= _u, _u)
_np = P._node_ports(deps, nodes, NID) if isinstance(_u, set) else {}
check("…and the conflict names the holder by its key (verify F67)", _np.get(10007) == "w1 (WDTT)", _np.get(10007))
_sn = {"udp_listen": {"a": 1}}; P._snap_sanitise(_sn, "t1")
_sl = {"udp_listen": [53, "x", [1]]}; P._snap_sanitise(_sl, "t2")
check("a udp_listen that is not a list of numbers is dropped or cleaned at the sync door (review F4)",
      "udp_listen" not in _sn and _sl.get("udp_listen") == [53], (_sn, _sl))

import io as _io
_PROC = {"/proc/net/udp": "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops\n"
         "  1: 00000000:01BB 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 11 2 0000 0\n"      # *:443 listening
         "  2: 0100007F:A7A2 0100007F:CB2C 01 00000000:00000000 00:00000000 00000000     0        0 12 2 0000 0\n",     # connected, ESTABLISHED
         "/proc/net/udp6": "  sl  local_address rem_address st\n"
         "  4: 00000000000000000000000000000000:CA6C 00000000000000000000000000000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 14 2 0 0\n"}
_saved_open = N.__dict__.get("open")
N.open = lambda path, *a, **k: _io.StringIO(_PROC[path])
try:
    _ul = N.udp_listen_ports()
finally:
    if _saved_open is None:
        del N.open
    else:
        N.open = _saved_open
check("the node reports the ports it LISTENS on (v4 and v6), never a connected socket's port", _ul == [443, 51820], _ul)

print("\n[8] the router's key in the config store (S9c)")
import json as _json, shutil as _sh
_D = tempfile.mkdtemp(prefix="dialin-store-")
try:
    _rk, _nk = _k(), _k()
    _ex = {"id": "aabbccdd", "producer": "imported", "provider": "profile", "label": "home",
           "profile": {"private_key": _nk, "address": "10.254.0.0", "mtu": 1280, "listen_port": 51820, "endpoint": "",
                       "peer_key": _rk, "psk": "", "keepalive": 0, "awg": {}}}
    _deps = {"fleet": {}, "roster_path": os.path.join(_D, "users.json"), "nodes_path": os.path.join(_D, "nodes.json"),
             "sub_dir": os.path.join(_D, "subs"), "node_snaps": {}, "node_seen": {}, "panel_settings": {}, "now": lambda: 1}
    _json.dump({"users": {}, "peers": {}}, open(_deps["roster_path"], "w"))
    def _nodes(exits):
        P.nodes_save(_deps["nodes_path"], {NID: {"name": "lab", "id": NID, "exits": exits, "links": {}, "ifaces": {}}})
    def _api(m, path, body=None, qs=None):
        return P.api(m, path, qs or {}, body or {}, _deps)
    _nodes([_ex])
    B = P.sub_exit_bucket(NID)
    st, r = _api("POST", "/api/sub/escrow", {"user_id": B, "unlock_by_sk": "WRAPPED"})
    check("a known node's bucket takes an encryption key", st == 200, (st, r))
    st, r = _api("POST", "/api/sub/escrow", {"user_id": P.sub_exit_bucket("nosuchnode"), "unlock_by_sk": "W"})
    check("…an unknown node's does not", st == 404, (st, r))
    _nkh = P._exit_nkh(_ex["profile"])
    st, r = _api("POST", "/api/sub/exitblob", {"node": NID, "exit": "aabbccdd", "pub": _k(), "nkh": _nkh, "sec": "CT"})
    check("a key made against another router key is refused (409)", st == 409, (st, r))
    st, r = _api("POST", "/api/sub/exitblob", {"node": NID, "exit": "aabbccdd", "pub": _rk, "nkh": "0" * 16, "sec": "CT"})
    check("…and one sealed against another node key (a re-paste between the save and the keep), 409", st == 409, (st, r))
    st, r = _api("POST", "/api/sub/exitblob", {"node": NID, "exit": "eeeeeeee", "pub": _rk, "nkh": _nkh, "sec": "CT"})
    check("…a key for an exit the node has not, 404", st == 404, (st, r))
    st, r = _api("POST", "/api/sub/exitblob", {"node": NID, "exit": "aabbccdd", "pub": _rk, "nkh": _nkh, "sec": {"a": 1}})
    check("…a ciphertext that is not a string, 400 (never its repr kept over a good key)", st == 400, (st, r))
    st, r = _api("POST", "/api/sub/exitblob", {"node": NID, "exit": "aabbccdd", "pub": _rk, "nkh": _nkh, "sec": "CT"})
    _ent = P.load_sub_blobs(_deps, B).get("aabbccdd") or {}
    check("the router's key is kept, its node-key digest the record's", st == 200
          and _ent.get("sec") == "CT" and _ent.get("pub") == _rk and _ent.get("nkh") == _nkh, (st, r, _ent))
    check("…the digest names nothing of the key", _nk not in _json.dumps(_ent), _ent)
    def _get():
        return _api("GET", "/api/sub/exitblob", qs={"node": [NID], "exit": ["aabbccdd"]})
    st, r = _get()
    check("it is read back while the exit stands, from the node's bucket, with its bucket key and router key in the one answer",
          st == 200 and r["data"] == {"sec": "CT", "pub": _rk, "user_id": B, "unlock_by_sk": "WRAPPED"}, (st, r))
    # a GET runs outside the lock with a nodes snapshot from its start: a Regenerate that saved and kept a new router key
    # meanwhile must not read as stale against it. Reads outside the lock see the old record here; the prune must not.
    _real_load, _old = P.nodes_load, {NID: {"name": "lab", "id": NID, "exits": [dict(_ex, profile=dict(_ex["profile"], peer_key=_k()))]}}
    P.nodes_load = lambda path: _real_load(path) if P._api_lock._is_owned() else _old
    try:
        _get(); _api("GET", "/api/sub/users")
    finally:
        P.nodes_load = _real_load
    check("a read that started before a Regenerate's save does not prune the key it kept", "aabbccdd" in P.load_sub_blobs(_deps, B),
          P.load_sub_blobs(_deps, B))
    _su = _api("GET", "/api/sub/users")[1]["data"]["users"].get(B) or {}
    check("the bucket lists as the node's: one dial-in exit, one kept", (_su.get("peers"), _su.get("provisioned")) == (1, 1), _su)
    _tp = P.transfer_plan(_deps, P.nodes_load(_deps["nodes_path"]), NID, {}, {}, P.roster_load(_deps["roster_path"]))
    check("a Transfer carries no router key (the far panel's vault cannot open it) and no bucket key (it would refuse new ones)",
          B not in (_tp.get("blobs") or {}) and B not in (_tp.get("escrow") or {}) and _tp.get("blob_count") == 0,
          {k: _tp.get(k) for k in ("blobs", "escrow", "blob_count")})
    check("…and names the exit whose router config stays here", _tp.get("router_keys") == [{"title": "home", "port": 51820}],
          _tp.get("router_keys"))
    def _after(change, name):
        _nodes([change])
        P.save_sub_blobs(_deps, B, {"aabbccdd": dict(_ent)})
        st, r = _get()
        check(name, (st == 200 and r["data"]["sec"] == "" or st == 404) and "aabbccdd" not in P.load_sub_blobs(_deps, B), (st, r))
    _after(dict(_ex, profile=dict(_ex["profile"], peer_key=_k())), "a regenerated or re-pasted router: the kept key is gone")
    _after(dict(_ex, profile=dict(_ex["profile"], private_key=_k())), "a pasted new node key: the kept key is gone")
    _after(dict(_ex, profile=dict(_ex["profile"], endpoint="203.0.113.9:51820")), "the exit turned dial-out: the kept key is gone")
    _nodes([_ex]); P.save_sub_blobs(_deps, B, {"aabbccdd": dict(_ent)})
    st, r = _api("POST", "/api/nodes/update", {"id": NID, "exits": []})
    check("an exits save that removes the exit takes its key off the disk at once", st == 200
          and "aabbccdd" not in P.load_sub_blobs(_deps, B), (st, r, P.load_sub_blobs(_deps, B)))
    _nodes([_ex]); P.save_sub_blobs(_deps, B, {"aabbccdd": dict(_ent)})
    P.node_remove(_deps, NID)
    check("a node delete drops its bucket and the key it was sealed under",
          not os.path.exists(P._sub_blob_path(_deps, B)) and B not in P.load_sub_escrow(_deps), P.load_sub_escrow(_deps))
finally:
    _sh.rmtree(_D, ignore_errors=True)

ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
for k in ("a dial-in exit has exactly one peer — the upstream", "the profile's ListenPort is not a usable port",
          "UDP port {v1} is already used on this node by {v2}", "this panel does not know exits of kind {v1}",
          "this node does not know this kind of exit — update the node",
          "the address {v1} is inside {v2} ({v3}) on this node — use another one",
          "no free port in 42821–42899 on this node, nor in its declared firewall range — type a port",
          "the port must be a number from 1 to 65535", "the MTU must be a number from 576 to 1500",
          "UDP port {v1} is in the reserved system mesh range ({v2})",
          "S1–S4 must be at least 12 for AmneziaWG 3.1 — header protection refuses less", "this exit",
          "UDP port {v1} is outside this node's declared firewall ranges ({v2}) — the router could never reach it; pick a port inside them, or add it to udpPortRanges",
          "choose WireGuard, AmneziaWG 2.0 or AmneziaWG 3.1", "the generated keys are not usable keys",
          "no dial-in exit with this id on this node", "the exit's router key has changed since this config was made",
          "no encryption key for this node — set up config encryption first"):
    check("RU has %r" % k[:50], '"%s"' % k in ru)

print("")
if PLANT:
    print("PERTURB OK (%s) — %d checks went red" % (PLANT, len(FAILS)) if FAILS else
          "PERTURB FAILED (%s) — the fix was removed and every check still passed" % PLANT)
    sys.exit(0 if FAILS else 1)
print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
