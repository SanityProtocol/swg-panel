#!/usr/bin/env python3
"""Self-test — a turn proxy's loopback source ports, read from /proc, not `ss -Hnp` (docs/CPU-PLAN.md B9).

`wg_sports` tells the panel WHICH proxy a client came through: a wg peer reached through a proxy has the endpoint
127.0.0.1:<a source port of that proxy's connection to wg>. That connection is UDP whatever the proxy's own transport —
WireGuard speaks nothing else; a TCP-mode proxy's TCP is to VK's relay — and the panel looks the ports up as WireGuard
endpoints. `ss -Hnp state established` walked every fd of every process on the box to name each socket's owner — 16 ms of
CPU a pass on swgt, for two proxies. Now: the processes whose cgroup names the unit (1.8.8's attribution, `_service_of_pid`,
in any cgroup layout), their fds, /proc/net/udp.

  [1] The ports per proxy on one box: a connected UDP socket on loopback (counted); a TCP connection on loopback (not a
      WireGuard endpoint), a DNS query to 127.0.0.53, an unconnected UDP socket, a connection to a remote peer, another
      process's loopback socket (not counted); the ports as the same sorted strings; no `ss`.
  [2] A unit that is not running has no process: no ports.
  [3] Any cgroup layout (code review): a unit in a slice of its own, a cgroup v1 box, a container whose hierarchy is the
      host's (lxc.payload…) — each found by its cgroup path, as 1.8.8 found it.
  [4] 127.0.0.1 as a big-endian host prints it.
  [5] A Docker node: its proxies are sibling containers in their own pid namespaces, so no socket's owner can be named
      from noded's container — nothing is asked (it was always empty there).

Run: python3 tests/turn_wg_sports_proc_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught). (No plant drops the connected-state
  test: a UDP socket has a peer only while connected, so the loopback-peer test already holds it.)
     anypeer      a loopback source port counts whatever the peer
     tcpfile      TCP sockets are read (a port that is never a WireGuard endpoint is reported)
     oneslice     the owner is looked for in systemd's system.slice of a v2 hierarchy only (a unit elsewhere goes unseen)
     dockerss     a Docker node asks `ss` again
"""
import builtins, importlib.machinery, importlib.util, io, os, subprocess, sys, tempfile, threading, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "anypeer": ("""and c[1][:8] in _LO4_HEX and c[2][:8] in _LO4_HEX""", """and c[1][:8] in _LO4_HEX"""),
    "tcpfile": ("""        with open("/proc/net/udp") as f:""", """        with open("/proc/net/tcp") as f:"""),
    "oneslice": ("""            m = re.search(r"(vk-turn-proxy-[^/\\s.]+)", f.read())""",
                 """            m = re.search(r"^0::/system\\.slice/(vk-turn-proxy-[^/\\s.]+)", f.read())"""),
    "dockerss": ('''        if not tp or TURN_DOCKER:''', '''        if not tp:'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="wgsports-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("ws_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("ws_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None

A, B = "vk-turn-proxy-WINGS-N-56004", "vk-turn-proxy-samosvalishe-56007"
C, V1, LX = "vk-turn-proxy-own-56010", "vk-turn-proxy-v1-56011", "vk-turn-proxy-lxc-56012"


def hexip(ip, big=False):
    o = [int(x) for x in ip.split(".")]
    return ("%02X%02X%02X%02X" % tuple(o)) if big else ("%02X%02X%02X%02X" % tuple(reversed(o)))


def box(big=False):
    """A box: proxy units, their processes (by cgroup) and sockets, and one other process."""
    socks = {
        "1001": ("tcp", ("127.0.0.1", 41234), ("127.0.0.1", 51820), "01"),    # A: a TCP pair on loopback       ✗ (not wg)
        "1002": ("udp", ("127.0.0.1", 50000), ("127.0.0.1", 51820), "01"),    # A → wg over UDP, connected     ✓
        "1003": ("udp", ("0.0.0.0", 56004), ("0.0.0.0", 0), "07"),            # A's listener: unconnected      ✗
        "1004": ("tcp", ("127.0.0.1", 6000), ("127.0.0.1", 51820), "06"),     # A: TIME_WAIT                   ✗
        "1005": ("udp", ("127.0.0.1", 50777), ("127.0.0.53", 53), "01"),     # A asks systemd-resolved (DNS)  ✗
        "2001": ("udp", ("127.0.0.1", 50123), ("127.0.0.1", 51821), "01"),    # B → wg                         ✓
        "2002": ("tcp", ("127.0.0.1", 39999), ("203.0.113.9", 443), "01"),    # B → a remote peer              ✗
        "5001": ("udp", ("127.0.0.1", 50501), ("127.0.0.1", 51822), "01"),    # C (its own slice) → wg         ✓
        "6001": ("udp", ("127.0.0.1", 50601), ("127.0.0.1", 51823), "01"),    # V1 (cgroup v1 box) → wg        ✓
        "7001": ("udp", ("127.0.0.1", 50701), ("127.0.0.1", 51824), "01"),    # LX (lxc, host hierarchy) → wg  ✓
        "9001": ("udp", ("127.0.0.1", 50555), ("127.0.0.1", 51820), "01"),    # another process's loopback     ✗
    }
    fds = {"300": ["1001", "1002", "1003", "1004", "1005"], "301": [], "400": ["2001", "2002"], "500": ["5001"],
           "600": ["6001"], "700": ["7001"], "900": ["9001"]}
    cg = {"300": "0::/system.slice/%s.service\n" % A, "301": "0::/system.slice/%s.service\n" % A,
          "400": "0::/system.slice/%s.service\n" % B, "500": "0::/swg-turn.slice/%s.service\n" % C,
          "600": "12:pids:/system.slice/%s.service\n1:name=systemd:/system.slice/%s.service\n" % (V1, V1),
          "700": "0::/lxc.payload.c1/system.slice/%s.service\n" % LX, "900": "0::/system.slice/other.service\n"}
    files, links = {}, {"/proc": {p: None for p in list(fds) + ["self", "net", "sys"]}}
    for pid, inos in fds.items():
        links["/proc/%s/fd" % pid] = {str(i + 3): "socket:[%s]" % ino for i, ino in enumerate(inos)}
        links["/proc/%s/fd" % pid]["0"] = "/dev/null"
    for proto in ("tcp", "udp"):
        rows = ["  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"]
        for k, (ino, (pr, lo, pe, st)) in enumerate(sorted(socks.items())):
            if pr == proto:
                rows.append("%4d: %s:%04X %s:%04X %s 00000000:00000000 00:00000000 00000000     0        0 %s 2 0000000000000000 0"
                            % (k, hexip(lo[0], big), lo[1], hexip(pe[0], big), pe[1], st, ino))
        files["/proc/net/%s" % proto] = "\n".join(rows) + "\n"
    return files, links, cg


SS_CALLS = []


def install(files, links, cg):
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if isinstance(path, str) and (path.startswith("/proc/") or path.startswith("/sys/")):
            if path in files:
                return io.StringIO(files[path])
            if path.endswith("/cgroup") and path.split("/")[2] in cg:
                return io.StringIO(cg[path.split("/")[2]])
            raise FileNotFoundError(2, "No such file or directory", path)
        return real_open(path, *a, **k)

    def listdir(path):
        if path in links:
            return list(links[path])
        raise FileNotFoundError(2, "No such file or directory", path)

    def readlink(path):
        d, fd = path.rsplit("/", 1)
        if d in links and fd in links[d]:
            return links[d][fd]
        raise FileNotFoundError(2, "No such file or directory", path)

    fos = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    fos.listdir, fos.readlink = listdir, readlink
    N.open, N.os = fake_open, fos

    def fake_run(args, input_text=None, timeout=20, env=None):
        SS_CALLS.append(" ".join(args))
        return subprocess.CompletedProcess(args, 0, "", "")
    N.run = fake_run


def sports(svcs=(A, B)):
    tp = [{"service": s} for s in svcs]
    SS_CALLS.clear()
    N._attach_turn_wg_sports(tp)
    return {t["service"]: t.get("wg_sports") for t in tp}


# ── [1] one box ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the ports per proxy on one box")
install(*box())
got = sports()
check("[1] each proxy's connected UDP sockets to wg on loopback — sorted strings", got == {A: ["50000"], B: ["50123"]}, got)
check("[1] a TCP pair on loopback is no WireGuard endpoint, nor a DNS query to 127.0.0.53: not reported",
      "41234" not in str(got) and "50777" not in str(got), got)
check("[1] another process's loopback socket is not a proxy's", "50555" not in str(got), got)
check("[1] no `ss`", not SS_CALLS, SS_CALLS)

# ── [2] a unit that is not running ────────────────────────────────────────────────────────────────────────────────────
print("\n[2] a unit that is not running")
got = sports((A, B, "vk-turn-proxy-stopped-56020"))
check("[2] no process: no ports for it, the others as before", got == {A: ["50000"], B: ["50123"], "vk-turn-proxy-stopped-56020": None},
      got)

# ── [3] any cgroup layout ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] any cgroup layout")
got = sports((C, V1, LX))
check("[3] a unit in a slice of its own, on a cgroup v1 box, in a container on the host's hierarchy: each found",
      got == {C: ["50501"], V1: ["50601"], LX: ["50701"]}, got)

# ── [4] a big-endian host ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] a big-endian host")
install(*box(big=True))
got = sports()
check("[4] 127.0.0.1 printed big-endian is loopback too", got == {A: ["50000"], B: ["50123"]}, got)

# ── [5] a Docker node ─────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] a Docker node")
N.TURN_DOCKER = True
got = sports()
check("[5] nothing asked, nothing attached (it never could be)", not SS_CALLS and got == {A: None, B: None}, (got, SS_CALLS))
N.TURN_DOCKER = False

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
