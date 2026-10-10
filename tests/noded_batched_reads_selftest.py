#!/usr/bin/env python3
"""Self-test — every link and every interface dump, one read each per pass (docs/CPU-PLAN.md B3).

Each reader asked per device — the kind, the MTU, the candidates' probe, `<tool> show <dev> dump` per interface,
`latest-handshakes` per exit, `wg show <dev> dump` / `public-key` per WDTT server: ~50 processes a pass on swgt. One
`ip -d -o link show` and one `<tool> show all dump` per pass now carry all of it (live-compared on swgt 2026-10-10: 14 dumps
and 22 links, no difference).

  [1] An interface's slice of `show all dump` is byte for byte what `<tool> show <dev> dump` prints — interface line, peer
      lines, AmneziaWG's longer interface line, an interface with no peers.
  [2] An interface the batch does not hold is read on its own, so a down interface's error text (`down`, which the panel's
      mesh auto-start acts on) is the same; a batch that cannot be read sends every reader to its own read.
  [3] Links: kind and MTU from a device's line equal the per-device answers; a veth's `name@peer` is named right; a device
      that is not there reads "" and the MTU falls back to the .conf, as before.
  [4] The exit's handshake age comes from the dump's peer lines (what `latest-handshakes` printed); the WDTT server's public
      key from the dump's first line.
  [5] One pass: any number of readers, one `show all dump` per tool and one `ip -d -o link show`.

Run: python3 tests/noded_batched_reads_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     keepname     the slice keeps the `all` form's name column
     emptydown    an interface missing from the batch reads as an empty, successful dump (its `down` text is lost)
     vethname     the link parser keeps the `@peer` suffix in the name
"""
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile, threading

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
    "keepname": ('''            lines.setdefault(name, []).append(rest)''', '''            lines.setdefault(name, []).append(ln)'''),
    "emptydown": ('''    if d is not None and iface in d:
        return subprocess.CompletedProcess(cmd + ["show", iface, "dump"], 0, d[iface], "")''',
                  '''    if d is not None:
        return subprocess.CompletedProcess(cmd + ["show", iface, "dump"], 0, d.get(iface, ""), "")'''),
    "vethname": ('''        m = re.match(r"^\\d+:\\s+([^:@\\s]+)(?:@\\S*)?:\\s", ln)''', '''        m = re.match(r"^\\d+:\\s+([^:\\s]+):\\s", ln)'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="batched-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("br_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("br_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None

# the kernel, as the tools print it
WG1 = "cHJpdg==\tUFVC\t51820\toff\nUEVFUjE=\t(none)\t1.2.3.4:5\t10.0.0.2/32\t1791600000\t100\t200\toff\nUEVFUjI=\tUFNL\t(none)\t10.0.0.3/32\t0\t0\t0\t25\n"
AWG2 = "cHJpdjI=\tUFVCMg==\t51821\toff\t4\t40\t70\t0\t0\t1\t2\t3\t4\nUEVFUjM=\t(none)\t5.6.7.8:9\t10.1.0.2/32\t1791600100\t5\t6\toff\n"
EMPTY = "cHJpdjM=\tUFVCMw==\t51822\toff\n"
PER = {("wg", "wg1"): WG1, ("awg", "awg2"): AWG2, ("wg", "wg9"): EMPTY}
ALL = {"wg": "".join("%s\t%s" % (i, l) for (t, i), d in PER.items() if t == "wg" for l in d.splitlines(True)),
       "awg": "".join("%s\t%s" % (i, l) for (t, i), d in PER.items() if t == "awg" for l in d.splitlines(True))}
LINKS = ("1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\\    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00 promiscuity 0\n"
         "5: wg1: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\\    link/none  promiscuity 0 \\    wireguard addrgenmode none numtxqueues 1\n"
         "6: awg2: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1376 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\\    link/none  promiscuity 0 \\    amneziawg addrgenmode none\n"
         "9: veth1a2b@if8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue master docker0 state UP mode DEFAULT\\    link/ether 02:42:ac:11:00:02 brd ff:ff:ff:ff:ff:ff link-netnsid 0 \\    veth\n")
CALLS = []
STATE = {"all_rc": 0, "links_rc": 0}


def fake(args, input_text=None, timeout=20, env=None):
    CALLS.append(" ".join(args))
    if args[1:] == ["show", "all", "dump"]:
        return subprocess.CompletedProcess(args, STATE["all_rc"], ALL[args[0]] if not STATE["all_rc"] else "", "")
    if len(args) == 4 and args[1] == "show" and args[3] == "dump":
        d = PER.get((args[0], args[2]))
        return subprocess.CompletedProcess(args, 0, d, "") if d is not None else \
            subprocess.CompletedProcess(args, 1, "", "Unable to access interface: No such device\n")
    if args == ["ip", "-d", "-o", "link", "show"]:
        return subprocess.CompletedProcess(args, STATE["links_rc"], LINKS if not STATE["links_rc"] else "", "")
    if args[:4] == ["ip", "-d", "link", "show"] or args[:5] == ["ip", "-o", "link", "show", "dev"]:
        dev = args[-1]
        for ln in LINKS.splitlines():
            if (": %s:" % dev) in ln or (": %s@" % dev) in ln:
                return subprocess.CompletedProcess(args, 0, ln.replace("\\", "\n"), "")
        return subprocess.CompletedProcess(args, 1, "", 'Device "%s" does not exist.\n' % dev)
    return subprocess.CompletedProcess(args, 0, "", "")


N.run = fake
N._LOOP["n"] = 1

# ── [1] slices ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] an interface's slice of `show all dump`")
for (tool, iface), want in PER.items():
    got = N._dump_of([tool], iface)
    check("[1] %s %s: byte for byte what `%s show %s dump` prints" % (tool, iface, tool, iface),
          got.returncode == 0 and got.stdout == want, (got.stdout, want))

# ── [2] not in the batch ──────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] an interface the batch does not hold")
got = N._dump_of(["wg"], "swg_down0")
check("[2] read on its own — the same error text (a down interface's `down`)",
      got.returncode == 1 and "No such device" in (got.stderr or ""), (got.returncode, got.stderr))
N._LOOP["n"] = 2; STATE["all_rc"] = 1; CALLS.clear()
got = N._dump_of(["wg"], "wg1")
check("[2] a batch that cannot be read: each reader reads on its own", got.stdout == WG1 and "wg show wg1 dump" in CALLS, CALLS)
STATE["all_rc"] = 0

# ── [3] links ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] links")
N._LOOP["n"] = 3
links = N._all_links()
check("[3] every device named — a veth's `name@peer` as `name`", set(links or {}) == {"lo", "wg1", "awg2", "veth1a2b"}, sorted(links or {}))
check("[3] the kind from the device's line", (N._link_kind("wg1"), N._link_kind("awg2"), N._link_kind("veth1a2b")) == ("wg", "awg", ""))
check("[3] the MTU from the device's line", (N.iface_mtu("wg1"), N.iface_mtu("awg2"), N.iface_mtu("veth1a2b")) == (1420, 1376, 1500))
check("[3] a device that is not there: no kind, the .conf's MTU", N._link_kind("gone0") == "" and N.iface_mtu("gone0", {"MTU": "1280"}) == 1280)
N._LOOP["n"] = 4; STATE["links_rc"] = 1
check("[3] links that cannot be read: each reader asks per device, the same answers",
      (N._link_kind("wg1"), N.iface_mtu("awg2")) == ("wg", 1376))
STATE["links_rc"] = 0

# ── [4] exits, WDTT ───────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the exit's handshake, the WDTT server's key")
N._LOOP["n"] = 5
N._exit_clis = lambda rec, dev: (["wg"], ["awg"])
N._exit_trace = lambda *a, **k: None
age = N._exit_handshake({}, "wg1")
check("[4] the exit's handshake age from the dump's peer lines (what `latest-handshakes` printed)",
      isinstance(age, int) and age >= 1, age)
N.NODE_KIND = "bare"
check("[4] the WDTT server's public key: the dump's first line, second field", N._wdtt_server_pub("wg9") == "UFVCMw==",
      N._wdtt_server_pub("wg9"))
check("[4] …and \"\" for a server that is not up", N._wdtt_server_pub("wdtt7") == "")

# ── [5] one read per pass ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] one pass, many readers")
N._LOOP["n"] = 6; CALLS.clear()
for _ in range(3):
    N._dump_of(["wg"], "wg1"); N._dump_of(["wg"], "wg9"); N._dump_of(["awg"], "awg2")
    N._link_kind("wg1"); N.iface_mtu("awg2"); N._link_kind("awg2")
check("[5] one `show all dump` per tool and one `ip -d -o link show`, however many readers",
      sorted(CALLS) == sorted(["wg show all dump", "awg show all dump", "ip -d -o link show"]), CALLS)

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
