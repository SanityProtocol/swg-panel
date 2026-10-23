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
  [2] on the real kernel, in throwaway network namespaces, the real reconcile_cascade run inside the node's: through a
      router that forwards everything (Keenetic `private`), an internet host answers; the router's LAN and its tunnel
      address do not; a Network the node shares still does

[2] runs as root or through `sudo -n`; without either it is SKIPPED, and says so — never passed. The namespaces are named by
this process's pid and deleted on the way out; nothing leaves them (the "internet" is a TEST-NET address on a veth).
Run: python3 tests/dialin_lan_cut_selftest.py
     --perturb   the node without the cut (no device reads as dial-in) — [1] and [2] must turn red. Prints "PERTURB OK".
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
_ANCH = '    _dlv = set(_EXITS.get("dialin") or ())\n'

FAILS, SKIPS = [], []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def noded_src():
    src = open(NODED, encoding="utf-8").read()
    assert src.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
    return src.replace(_ANCH, "    _dlv = set()\n") if PERTURB else src

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

def lower(dev, dialin=(), state="up", nets=(), ks=False):
    calls = []
    N.run = lambda argv, **kw: (calls.append(argv if isinstance(argv, list) else [str(argv)]), _R(""))[1]
    N._dev_link_state = lambda d: state
    N._DEVEXIT["list"] = []
    N._EXITS["dialin"] = list(dialin)
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

# the signature: what is written reads back as the same token, or every pass rebuilds the band (a gap each time)
_cut = [("7000", p) for p in CUT]
_ws = N._cascade_want_sig([], [], [], cut=_cut)
check("the want-signature names each cut route", {"T|7000|prohibit:%s||" % p for p in CUT} <= _ws, sorted(_ws))
_show = "default dev wgx-aabbccdd scope link \n" + "".join("prohibit %s \n" % p for p in CUT) + \
        "prohibit default metric %d \n" % N.DEVEXIT_GUARD_METRIC
N.run = lambda argv, **kw: _R(_show if argv[:3] == ["ip", "route", "show"] else "")
_ls = N._cascade_live_sig({"7000"})
check("…the live reader reads them back as the same tokens", {"T|7000|prohibit:%s||" % p for p in CUT} <= _ls, sorted(_ls))
check("…and `prohibit default` keeps the kill-switch's own token (no rebuild on update)",
      "T|7000|prohibit||" in _ls and not any(t.startswith("T|7000|prohibit:default") for t in _ls), sorted(_ls))

# ── [2] the real kernel ──────────────────────────────────────────────────────────────────────────────────────────
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
for x in $NS; do ip netns add $P-$x; ip -n $P-$x link set lo up; done
pair() { ip link add "$2" netns $P-$1 type veth peer name "$4" netns $P-$3 && ip -n $P-$1 link set "$2" up && ip -n $P-$3 link set "$4" up; }
pair c c0 n up0;       ip -n $P-c addr add 10.17.0.5/24 dev c0;  ip -n $P-c route add default via 10.17.0.1
                       ip -n $P-n addr add 10.17.0.1/24 dev up0
# the tunnel: point-to-point like a WireGuard device (a multi-access one without a gateway is never routed into), over
# an underlay of its own — ipip, so no keys and no module beyond the kernel's own
pair n ul0 r ul1;      ip -n $P-n addr add 198.18.0.1/30 dev ul0; ip -n $P-r addr add 198.18.0.2/30 dev ul1
ip -n $P-n link add wgx-aabbccdd type ipip local 198.18.0.1 remote 198.18.0.2; ip -n $P-n link set wgx-aabbccdd up
ip -n $P-r link add rt0 type ipip local 198.18.0.2 remote 198.18.0.1;          ip -n $P-r link set rt0 up
ip -n $P-n addr add 10.254.0.0/31 dev wgx-aabbccdd;  ip -n $P-r addr add 10.254.0.1/31 dev rt0
pair n net0 k k0;      ip -n $P-n addr add 192.168.77.1/24 dev net0; ip -n $P-k addr add 192.168.77.10/24 dev k0
                       ip -n $P-k route add default via 192.168.77.1
pair r l0 l lan0;      ip -n $P-r addr add 192.168.1.1/24 dev l0; ip -n $P-l addr add 192.168.1.10/24 dev lan0
                       ip -n $P-l route add default via 192.168.1.1
pair r w0 i wan0;      ip -n $P-r addr add 203.0.113.1/24 dev w0; ip -n $P-i addr add 203.0.113.9/24 dev wan0
                       ip -n $P-i route add default via 203.0.113.1
ip -n $P-r route add 10.17.0.0/24 via 10.254.0.0
for x in n r; do ip netns exec $P-$x sysctl -qw net.ipv4.ip_forward=1; done
# the node: the real reconcile_cascade, a dial-in device exit for the client subnet, one shared Network
ip netns exec $P-n python3 - "$NODED" "$CONF" <<'PY' || { echo "cascade: FAILED"; exit 0; }
import importlib.machinery, importlib.util, sys
l = importlib.machinery.SourceFileLoader("n", sys.argv[1]); m = importlib.util.module_from_spec(importlib.util.spec_from_loader("n", l))
try: l.exec_module(m)
except SystemExit: pass
m._EXITS["dialin"] = ["wgx-aabbccdd"]
# the client interface as a node has it: its conf's Address is what puts 10.17.0.0/24 into the exit's table
# (_cascade_local_routes), so the node's own replies to its clients never follow the default into the tunnel
m.reconcile_cascade({"interfaces": {"up0": {"conf": sys.argv[2]}}}, {"devexit": [{"subnet": "10.17.0.0/24", "dev": "wgx-aabbccdd", "table": 7000,
                    "killswitch": False}]}, None, "", nets=[("192.168.77.0/24", "net0")])
PY
for d in 203.0.113.9 192.168.1.10 192.168.1.1 10.254.0.1 192.168.77.10; do
  ip netns exec $P-c ping -c1 -W1 -q $d >/dev/null 2>&1 && echo "$d: reached" || echo "$d: blocked"; done
'''

def rig():
    sd = sudo()
    if sd is None or not shutil.which("ip"):
        SKIPS.append("[2]"); print("  SKIPPED [2] — no root / `sudo -n` or no ip here; [1] still ran"); return
    tmp = tempfile.mkdtemp(prefix="swgnoded-cut-rig-", dir="/tmp")
    path, conf = os.path.join(tmp, "noded.py"), os.path.join(tmp, "up0.conf")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SRC)
    with open(conf, "w", encoding="utf-8") as f:
        f.write("[Interface]\nAddress = 10.17.0.1/24\nListenPort = 51999\n")
    for x in (tmp, path, conf):
        os.chmod(x, 0o755 if x == tmp else 0o644)
    try:
        r = subprocess.run(sd + ["env", "NODED=" + path, "CONF=" + conf, "bash", "-c", RIG], capture_output=True,
                           text=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = {ln.split(": ")[0]: ln.split(": ")[1] for ln in r.stdout.splitlines() if ": " in ln}
    check("the real reconcile_cascade ran in the node's namespace", "cascade" not in out, (r.stdout + r.stderr)[-400:])
    check("through a router that forwards everything: an internet host answers", out.get("203.0.113.9") == "reached", out)
    check("…the router's LAN does not (192.168.1.10)", out.get("192.168.1.10") == "blocked", out)
    check("…nor the router at its LAN address (192.168.1.1, the admin page)", out.get("192.168.1.1") == "blocked", out)
    check("…nor the router at its tunnel address (10.254.0.1)", out.get("10.254.0.1") == "blocked", out)
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
