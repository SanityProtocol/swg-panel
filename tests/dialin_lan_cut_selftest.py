#!/usr/bin/env python3
"""Self-test: a dial-in exit leads to the internet, never into the home network behind it (1.8.11, backlog A).

A dial-in exit's far side is a home router, and the one Keenetic level that forwards the tunnel at all
(`security-level private`, S9c K2) also trusts it like the LAN. The node routes an exit's clients by `default dev <exit>`,
so a VPN user's packet to 192.168.x (the router's admin page, a printer, a NAS) or to the router's own tunnel address went
straight in. swg-noded now prohibits the private ranges (EXIT_PRIVATE_CUT) in every table whose default leaves by a
dial-in exit device — a route, so swg-relay's re-dialled connections are cut too — while the node's own networks and
client subnets, more specific routes in the same table, still win.

  [1] hermetic (`run()` stubbed, the argv read): which devices are dial-in; the cut in a dial-in exit's table and nowhere
      else (a WARP / dial-out exit, a device that is down, a node with none — byte-identical); a Network holding a cut
      prefix exactly is left alone; the signature reads the routes back as written, and the kill-switch keeps its token
      — and the review's round: a Network covering a cut prefix and another node's exit subnet are left alone; the router's
      public address is cut; the cut is installed before any rule points into the table; the devices are known before
      reconcile_exits' loop; a change in them re-runs the routing reconcile
  [2] on the real kernel, in throwaway network namespaces, the real reconcile_cascade run inside the node's: through a
      router that forwards everything (Keenetic `private`), an internet host answers; the router's LAN, its tunnel address
      and its public address do not; a Network the node shares still does

[2] runs as root or through `sudo -n`; without either it is SKIPPED, and says so — never passed. The namespaces are named by
this process's pid and deleted on the way out; nothing leaves them (the "internet" is a TEST-NET address on a veth).
Run: python3 tests/dialin_lan_cut_selftest.py
     --perturb   the node without the cut (no device reads as dial-in) — [1] and [2] must turn red. Prints "PERTURB OK".
     --perturb-early | -trigger | -order | -cover | -exitsub | -wan   one fix of the review's round undone each (F1 F2 F3 F4
                 F5 F8) — each must turn its check red
"""
import contextlib, signal, importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
_ANCH = '    dl, wan = set(_EXITS.get("dialin") or ()), _EXITS.get("dialin_wan") or {}\n'
# the named plants (review F1–F5, F8): each fix undone on its own
PLANT = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), "")
PLANTS = {
    "early": ('    _EXITS["dialin"] = _dialin_devices(want)\n    _slots = []', '    _slots = []'),
    "trigger": ('                                         _EXITS.get("dialin"), _EXITS.get("dialin_wan"),', ''),
    "order": ('        for T, p in _cut:\n            run(["ip", "route", "replace", "prohibit", p, "table", T])\n        for e in fwd:',
              '        for e in fwd:'),
    "cover": ('if not any(n.version == h.version and n.subnet_of(h) for h in nets):', 'if not any(n == h for h in nets):'),
    "exitsub": ('        held += [x["subnet"] for x in exit_ if str(x.get("table")) == T]\n', ''),
    "wan": ('list(EXIT_PRIVATE_CUT) + sorted(wan[d] + "/32" for d in tdev[T] if wan.get(d))', 'list(EXIT_PRIVATE_CUT)'),
}

FAILS, SKIPS = [], []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def noded_src():
    src = open(NODED, encoding="utf-8").read()
    assert src.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
    if PLANT:
        a, b = PLANTS[PLANT]
        assert src.count(a) == 1, "plant anchor missing — this run would FALSE-PASS: " + a[:60]
        return src.replace(a, b)
    return src.replace(_ANCH, "    dl, wan = set(), {}\n") if PERTURB else src

def load(src):
    fd, path = tempfile.mkstemp(suffix=".py", prefix="swgnoded-cut-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(src)
    l = importlib.machinery.SourceFileLoader("swgnoded_cut", path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_cut", l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    os.unlink(path)
    return mod

SRC = noded_src()
N = load(SRC)
CUT = list(N.EXIT_PRIVATE_CUT)

# ── [1] hermetic ─────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the cut, as the node builds it")
DIALIN = {"listen_port": 42850, "endpoint": "", "address": "10.254.0.0"}
DIALOUT = {"listen_port": None, "endpoint": "203.0.113.7:51820", "address": "10.66.0.2"}
want = {"aabbccdd": {"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "profile", "profile": DIALIN},
        "11223344": {"id": "11223344", "device": "wgx-11223344", "provider": "profile", "profile": DIALOUT},
        "55667788": {"id": "55667788", "device": "wgx-55667788", "provider": "warp"}}
check("a dial-in exit's device is dial-in; a dial-out profile and WARP are not",
      N._dialin_devices(want) == ["wgx-aabbccdd"], N._dialin_devices(want))
check("…nothing asked for, nothing dial-in", N._dialin_devices({}) == [] and N._dialin_devices(None) == [])

class _R:
    def __init__(s, out=""): s.stdout, s.stderr, s.returncode = out, "", 0

def lower(dev, dialin=(), state="up", nets=(), ks=False, wan=None):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: state
    N._DEVEXIT["list"] = []
    N._EXITS["dialin"] = list(dialin)
    N._EXITS["dialin_wan"] = dict(wan or {})
    N.reconcile_cascade({"interfaces": {}}, {"devexit": [{"subnet": "10.17.0.0/24", "dev": dev, "table": 7000,
                                                           "killswitch": ks}]}, None, "", nets=list(nets))
    return [" ".join(map(str, c)) for c in calls if c and c[0] == "ip"]

ROUTES = ["ip route replace prohibit %s table 7000" % p for p in CUT]
c = lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"])
check("a dial-in exit's table prohibits every private range (%s)" % ", ".join(CUT), all(r in c for r in ROUTES),
      [x for x in c if "prohibit" in x])
check("…beside its default route out the tunnel", "ip route replace default dev wgx-aabbccdd table 7000" in c, c)
_base = lower("wgx-55667788")
check("a WARP / dial-out exit's table: no cut (byte-identical — not one more command)",
      not any("prohibit" in x for x in _base) and lower("wgx-55667788", dialin=["wgx-aabbccdd"]) == _base, _base)
check("a dial-in exit whose device is down: no cut (its traffic is not sent into it)",
      not any("prohibit" in x for x in lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"], state="down")))
_ks = lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"], ks=True)
check("…with the kill-switch on: its backstop and the cut stand together",
      "ip route replace prohibit default metric %d table 7000" % N.DEVEXIT_GUARD_METRIC in _ks and all(r in _ks for r in ROUTES), _ks)
_nt = lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"], nets=[("192.168.77.0/24", "lan1"), ("10.0.0.0/8", "office0")])
check("a Network the node shares goes in as a more specific route, untouched by the cut",
      "ip route replace 192.168.77.0/24 dev lan1 table 7000" in _nt and ROUTES[-1] in _nt, [x for x in _nt if "table 7000" in x])
check("…and a prefix a Network holds EXACTLY is not overwritten by a prohibit",
      "ip route replace prohibit 10.0.0.0/8 table 7000" not in _nt and "ip route replace 10.0.0.0/8 dev office0 table 7000" in _nt, _nt)

_bn = lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"], nets=[("10.0.0.0/7", "office0")])
check("…nor one a broader Network covers (10.0.0.0/7 holds 10/8: the node's network wins, review F4)",
      "ip route replace prohibit 10.0.0.0/8 table 7000" not in _bn and ROUTES[-1] in _bn, [x for x in _bn if "table 7000" in x])
_xs = N._dialin_cut([{"via_iface": "wgx-aabbccdd", "table": 7000}], [{"subnet": "100.64.0.0/10", "table": 7000}], (), set())
check("…nor another node's exit subnet in the same table (replace would overwrite it, review F5)",
      ("7000", "100.64.0.0/10") not in _xs and ("7000", "10.0.0.0/8") in _xs, _xs)
_wn = lower("wgx-aabbccdd", dialin=["wgx-aabbccdd"], wan={"wgx-aabbccdd": "203.0.113.1"})
check("the router's public address (its learned endpoint, the users' egress address) is cut too (review F8)",
      "ip route replace prohibit 203.0.113.1/32 table 7000" in _wn, [x for x in _wn if "prohibit" in x])
_fp = next((i for i, x in enumerate(_wn) if x.startswith("ip route replace prohibit 10.0.0.0/8")), 10 ** 6)
_fr = next((i for i, x in enumerate(_wn) if x.startswith("ip rule add") or x.startswith("ip route replace default")), -1)
check("…the cut goes in before any rule points into the table and before its default (no window, review F3)",
      0 <= _fr and _fp < _fr, _wn)
check("which router address: the endpoint a dial-in row reports, kept while it reports none, gone with its device",
      N._dialin_wan([{"device": "wgx-a", "endpoint": "198.51.100.7:4500"}, {"device": "wgx-b", "endpoint": "198.51.100.8:1"}], {}, ["wgx-a"])
      == {"wgx-a": "198.51.100.7"}
      and N._dialin_wan([{"device": "wgx-a", "endpoint": ""}], {"wgx-a": "198.51.100.7"}, ["wgx-a"]) == {"wgx-a": "198.51.100.7"}
      and N._dialin_wan([], {"wgx-a": "198.51.100.7"}, []) == {})
# reconcile_exits knows the dial-in devices before its loop: a pass that raises half-way still cuts (review F1)
_xd = tempfile.mkdtemp(prefix="swgcut-exits-")
N.EXIT_DIR = _xd
N._EXITS.pop("dialin", None)
_orig_conf = N._exit_conf_text
N._exit_conf_text = lambda rec: (_ for _ in ()).throw(RuntimeError("a pass that raises"))
try:
    N.reconcile_exits([dict(want["aabbccdd"], profile=dict(DIALIN, priv="k", peer_key="p", pub="q"))], {"changed": 0, "errors": []})
except Exception:
    pass
N._exit_conf_text = _orig_conf
shutil.rmtree(_xd, ignore_errors=True)
check("…a pass of reconcile_exits that raises still leaves its dial-in device known", N._EXITS.get("dialin") == ["wgx-aabbccdd"],
      N._EXITS.get("dialin"))
_rs = SRC.split("_route_sig = json.dumps(", 1)[1].split("sort_keys=True", 1)[0]
check("a change in which devices are dial-in, or in a router's address, re-runs the routing reconcile (review F2)",
      '_EXITS.get("dialin")' in _rs and '_EXITS.get("dialin_wan")' in _rs, _rs[-300:])

# the signature: what is written reads back as the same token, or every pass rebuilds the band (a gap each time)
_cut = [("7000", p) for p in CUT + ["203.0.113.1/32"]]
_ws = N._cascade_want_sig([], [], [], cut=_cut)
_tok = {"T|7000|prohibit:%s||" % p for p in CUT} | {"T|7000|prohibit:203.0.113.1||"}
check("the want-signature names each cut route (a /32 spelled as `ip route show` prints it)", _tok <= _ws, sorted(_ws))
_show = "default dev wgx-aabbccdd scope link \n" + "".join("prohibit %s \n" % p for p in CUT) + "prohibit 203.0.113.1 \n" + \
        "prohibit default metric %d \n" % N.DEVEXIT_GUARD_METRIC
N.run = lambda argv, **kw: _R(_show if argv[:3] == ["ip", "route", "show"] else "")
_ls = N._cascade_live_sig({"7000"})
check("…the live reader reads them back as the same tokens", _tok <= _ls, sorted(_ls))
check("…and `prohibit default` keeps the kill-switch's own token (no rebuild on update)",
      "T|7000|prohibit||" in _ls and not any(t.startswith("T|7000|prohibit:default") for t in _ls), sorted(_ls))

# ── [2] the real kernel ──────────────────────────────────────────────────────────────────────────────────────────
def run_rig(cmd, timeout):
    """→ (stdout, stderr). On a timeout the whole session gets TERM — `sudo` passes it on, and the rig's trap deletes its
    namespaces; killing only the child left them behind (s9d-f8-lan F10)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        return p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGTERM)
        try:
            return p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            return p.communicate()

def sudo():
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo") and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        return ["sudo", "-n"]
    return None

RIG = r'''
set -u
P=swgcut$$
NS="c n r l i k"
cleanup() { for x in $NS; do ip netns del $P-$x 2>/dev/null; done; }
trap cleanup EXIT
trap 'exit 1' INT TERM     # …and on a timeout's TERM too: the EXIT trap then deletes the namespaces
for x in $NS; do ip netns add $P-$x; ip -n $P-$x link set lo up; done
pair() { ip link add "$2" netns $P-$1 type veth peer name "$4" netns $P-$3 && ip -n $P-$1 link set "$2" up && ip -n $P-$3 link set "$4" up; }
pair c c0 n up0;       ip -n $P-c addr add 10.17.0.5/24 dev c0;  ip -n $P-c route add default via 10.17.0.1
                       ip -n $P-n addr add 10.17.0.1/24 dev up0
# the tunnel: a real WireGuard pair, point-to-point as a dial-in exit is (a multi-access device without a gateway is never
# routed into), over an underlay of its own. ⚠️ NOT ipip: loading that module puts a `tunl0` into EVERY namespace made after
# it, and the cells' isolation checks then refuse to run (measured: mech-behaviour and per-packet-ab, 2026-10-23).
pair n ul0 r ul1;      ip -n $P-n addr add 198.18.0.1/30 dev ul0; ip -n $P-r addr add 198.18.0.2/30 dev ul1
KN=$(wg genkey); KR=$(wg genkey)
ip -n $P-n link add wgx-aabbccdd type wireguard; ip -n $P-r link add rt0 type wireguard
ip netns exec $P-n wg set wgx-aabbccdd private-key <(echo "$KN") listen-port 51901 \
  peer "$(echo "$KR" | wg pubkey)" endpoint 198.18.0.2:51902 allowed-ips 0.0.0.0/0
ip netns exec $P-r wg set rt0 private-key <(echo "$KR") listen-port 51902 \
  peer "$(echo "$KN" | wg pubkey)" endpoint 198.18.0.1:51901 allowed-ips 0.0.0.0/0
ip -n $P-n addr add 10.254.0.0/32 dev wgx-aabbccdd;  ip -n $P-r addr add 10.254.0.1/32 dev rt0
ip -n $P-n link set wgx-aabbccdd up;                 ip -n $P-r link set rt0 up
pair n net0 k k0;      ip -n $P-n addr add 192.168.77.1/24 dev net0; ip -n $P-k addr add 192.168.77.10/24 dev k0
                       ip -n $P-k route add default via 192.168.77.1
pair r l0 l lan0;      ip -n $P-r addr add 192.168.1.1/24 dev l0; ip -n $P-l addr add 192.168.1.10/24 dev lan0
                       ip -n $P-l route add default via 192.168.1.1
pair r w0 i wan0;      ip -n $P-r addr add 203.0.113.1/24 dev w0; ip -n $P-i addr add 203.0.113.9/24 dev wan0
                       ip -n $P-i route add default via 203.0.113.1
ip -n $P-r route add 10.254.0.0/32 dev rt0; ip -n $P-r route add 10.17.0.0/24 dev rt0
for x in n r; do ip netns exec $P-$x sysctl -qw net.ipv4.ip_forward=1; done
# the node: the real reconcile_cascade, a dial-in device exit for the client subnet, one shared Network
ip netns exec $P-n python3 - "$NODED" "$CONF" <<'PY' || { echo "cascade: FAILED"; exit 0; }
import importlib.machinery, importlib.util, sys
l = importlib.machinery.SourceFileLoader("n", sys.argv[1]); m = importlib.util.module_from_spec(importlib.util.spec_from_loader("n", l))
try: l.exec_module(m)
except SystemExit: pass
m._EXITS["dialin"] = ["wgx-aabbccdd"]
m._EXITS["dialin_wan"] = {"wgx-aabbccdd": "203.0.113.1"}   # what the node learns from the router's packets
# the client interface as a node has it: its conf's Address is what puts 10.17.0.0/24 into the exit's table
# (_cascade_local_routes), so the node's own replies to its clients never follow the default into the tunnel
m.reconcile_cascade({"interfaces": {"up0": {"conf": sys.argv[2]}}}, {"devexit": [{"subnet": "10.17.0.0/24", "dev": "wgx-aabbccdd", "table": 7000,
                    "killswitch": False}]}, None, "", nets=[("192.168.77.0/24", "net0")])
PY
for d in 203.0.113.9 192.168.1.10 192.168.1.1 10.254.0.1 203.0.113.1 192.168.77.10; do
  ip netns exec $P-c ping -c1 -W1 -q $d >/dev/null 2>&1 && echo "$d: reached" || echo "$d: blocked"; done
'''

def rig():
    sd = sudo()
    if sd is None or not shutil.which("ip") or not shutil.which("wg"):
        SKIPS.append("[2]"); print("  SKIPPED [2] — no root / `sudo -n`, ip or wg here; [1] still ran"); return
    tmp = tempfile.mkdtemp(prefix="swgnoded-cut-rig-", dir="/tmp")
    path, conf = os.path.join(tmp, "noded.py"), os.path.join(tmp, "up0.conf")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SRC)
    with open(conf, "w", encoding="utf-8") as f:
        f.write("[Interface]\nAddress = 10.17.0.1/24\nListenPort = 51999\n")
    for x in (tmp, path, conf):
        os.chmod(x, 0o755 if x == tmp else 0o644)
    try:
        r = subprocess.CompletedProcess([], 0, *run_rig(sd + ["env", "NODED=" + path, "CONF=" + conf, "bash", "-c", RIG], 120))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = {ln.split(": ")[0]: ln.split(": ")[1] for ln in r.stdout.splitlines() if ": " in ln}
    check("the real reconcile_cascade ran in the node's namespace", "cascade" not in out, (r.stdout + r.stderr)[-400:])
    check("through a router that forwards everything: an internet host answers", out.get("203.0.113.9") == "reached", out)
    check("…the router's LAN does not (192.168.1.10)", out.get("192.168.1.10") == "blocked", out)
    check("…nor the router at its LAN address (192.168.1.1, the admin page)", out.get("192.168.1.1") == "blocked", out)
    check("…nor the router at its tunnel address (10.254.0.1)", out.get("10.254.0.1") == "blocked", out)
    check("…nor the router at its public address (203.0.113.1, the users' egress address)", out.get("203.0.113.1") == "blocked", out)
    check("a Network the node shares is still reached (192.168.77.10, a more specific route)",
          out.get("192.168.77.10") == "reached", out)

print("[2] on the real kernel")
rig()

print()
if PERTURB:
    if FAILS:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    print("PERTURB FAILED — the node without the cut stayed green"); sys.exit(1)
print(("ALL PASS" + (" — SKIPPED: %s (needs root or `sudo -n`)" % ", ".join(SKIPS) if SKIPS else "")) if not FAILS
      else "FAILED: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
