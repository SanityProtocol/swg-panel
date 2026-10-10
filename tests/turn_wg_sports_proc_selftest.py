#!/usr/bin/env python3
"""Self-test — a turn proxy's loopback source ports, read from /proc, not `ss -Hnp` (docs/CPU-PLAN.md C1).

`wg_sports` tells the panel WHICH proxy a client came through: a wg peer reached through a proxy has the endpoint
127.0.0.1:<a source port of that proxy's connection to wg>. `ss -Hnp -t|-u state established` walks every fd of every
process on the box to name each socket's owner — 16 ms of CPU a pass on swgt, for two proxies. The unit's own cgroup names
its pids, their fds name their sockets, /proc/net/tcp and udp give each socket's addresses.

  [1] The same answer as the ss path, on one box: an established TCP pair and a connected UDP socket on loopback (counted);
      an unconnected UDP socket, a connection to a non-loopback peer, another process's loopback socket (not counted);
      the ports as the same sorted strings.
  [2] A unit that is not running has no cgroup: no ports, and no `ss`.
  [3] No unified cgroup hierarchy (cgroup v1, a container's own namespace): `ss`, exactly as before.
  [4] 127.0.0.1 as a big-endian host prints it.

Run: python3 tests/turn_wg_sports_proc_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     anystate     a socket in any state counts (an unconnected UDP socket included)
     anypeer      a loopback source port counts whatever the peer
     stoppedss    a unit that is not running sends the caller to `ss`
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
    "anystate": ("""                    if (len(c) > 9 and c[3] == "01" and c[9] in owner""", """                    if (len(c) > 9 and c[9] in owner"""),
    "anypeer": ("""and c[1][:8] in _LOOP4 and c[2][:8] in _LOOP4""", """and c[1][:8] in _LOOP4"""),
    "stoppedss": ("""            continue                                         # not running: no cgroup, no sockets""",
                  """            return None"""),
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


def hexip(ip, big=False):
    o = [int(x) for x in ip.split(".")]
    return ("%02X%02X%02X%02X" % tuple(o)) if big else ("%02X%02X%02X%02X" % tuple(reversed(o)))


def box(big=False):
    """A box: two proxy units, their pids and sockets, and one other process. sockets: inode → (proto, local, peer, state)."""
    socks = {
        "1001": ("tcp", ("127.0.0.1", 41234), ("127.0.0.1", 51820), "01"),    # A → wg over TCP, established   ✓
        "1002": ("udp", ("127.0.0.1", 50000), ("127.0.0.1", 51820), "01"),    # A → wg over UDP, connected     ✓
        "1003": ("udp", ("0.0.0.0", 56004), ("0.0.0.0", 0), "07"),            # A's listener: unconnected      ✗
        "1004": ("tcp", ("127.0.0.1", 6000), ("127.0.0.1", 51820), "06"),     # A: TIME_WAIT                   ✗
        "2001": ("udp", ("127.0.0.1", 50123), ("127.0.0.1", 51821), "01"),    # B → wg                         ✓
        "2002": ("tcp", ("127.0.0.1", 39999), ("203.0.113.9", 443), "01"),    # B → a remote peer              ✗
        "9001": ("udp", ("127.0.0.1", 50555), ("127.0.0.1", 51820), "01"),    # another process's loopback     ✗
    }
    fds = {"300": ["1001", "1002", "1003", "1004"], "301": [], "400": ["2001", "2002"], "900": ["9001"]}
    procs = {A: ["300", "301"], B: ["400"]}
    files, links, dirs = {}, {}, {"/sys/fs/cgroup/system.slice"}
    for svc, pids in procs.items():
        files["/sys/fs/cgroup/system.slice/%s.service/cgroup.procs" % svc] = "".join(p + "\n" for p in pids)
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
    # what `ss -Hnp -t|-u state established` prints for the same box (state filter: no State column)
    owner = {ino: pid for pid, inos in fds.items() for ino in inos}
    ss = {"-t": "", "-u": ""}
    for ino, (pr, lo, pe, st) in sorted(socks.items()):
        if st == "01":
            ss["-t" if pr == "tcp" else "-u"] += "0      0      %s:%d      %s:%d users:((\"proxy\",pid=%s,fd=5))\n" % (lo[0], lo[1], pe[0], pe[1], owner[ino])
    cg = {pid: "0::/system.slice/%s.service\n" % svc for svc, pids in procs.items() for pid in pids}
    cg["900"] = "0::/system.slice/other.service\n"
    return files, links, dirs, ss, cg


SS_CALLS = []


def install(files, links, dirs, ss, cg):
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
    fos.path = types.SimpleNamespace(**{k: getattr(os.path, k) for k in dir(os.path) if not k.startswith("__")})
    fos.path.isdir = lambda p: p in dirs
    N.open, N.os = fake_open, fos

    def fake_run(args, input_text=None, timeout=20, env=None):
        SS_CALLS.append(" ".join(args))
        return subprocess.CompletedProcess(args, 0, ss.get(args[2], "") if args[0] == "ss" else "", "")
    N.run = fake_run


def sports(svcs=(A, B)):
    tp = [{"service": s} for s in svcs]
    SS_CALLS.clear()
    N._attach_turn_wg_sports(tp)
    return {t["service"]: t.get("wg_sports") for t in tp}


# ── [1] the same answer as ss ─────────────────────────────────────────────────────────────────────────────────────────
print("[1] the same answer as the ss path, on one box")
files, links, dirs, ss, cg = box()
install(files, links, dirs, ss, cg)
fast = sports()
check("[1] read from /proc: no `ss`", not SS_CALLS, SS_CALLS)
install(files, links, set(), ss, cg)                          # the same box, the ss path forced
slow = sports()
check("[1] CONTROL: the ss path ran", len(SS_CALLS) == 2, SS_CALLS)
check("[1] the same ports per proxy as ss gives — sorted strings", fast == slow == {A: ["41234", "50000"], B: ["50123"]}, (fast, slow))

# ── [2] a unit that is not running ────────────────────────────────────────────────────────────────────────────────────
print("\n[2] a unit that is not running")
install(files, links, dirs, ss, cg)
got = sports((A, B, "vk-turn-proxy-stopped-56010"))
check("[2] no cgroup: no ports for it, the others as before, and no `ss`", got == {A: ["41234", "50000"], B: ["50123"],
      "vk-turn-proxy-stopped-56010": None} and not SS_CALLS, (got, SS_CALLS))

# ── [3] no unified hierarchy ──────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] no unified cgroup hierarchy")
install(files, links, set(), ss, cg)
got = sports()
check("[3] `ss`, exactly as before", len(SS_CALLS) == 2 and got == {A: ["41234", "50000"], B: ["50123"]}, (got, SS_CALLS))

# ── [4] a big-endian host ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] a big-endian host")
install(*box(big=True))
got = sports()
check("[4] 127.0.0.1 printed big-endian is loopback too", got == {A: ["41234", "50000"], B: ["50123"]} and not SS_CALLS, got)

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
