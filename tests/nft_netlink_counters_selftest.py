#!/usr/bin/env python3
"""Self-test — named nft counters read over netlink (docs/CPU-PLAN.md B5a).

`nft -j list counters table T` cost 66–90 ms on swgt whatever T held (the CLI loads every set first), every pass for P2P's
torrent count and every routing pass for device access. One NFT_MSG_GETOBJ dump reads the same objects in ~0.1 ms (measured
equal on swgt's kernel, 2026-10-10: same names, the CLI's values between two netlink reads).

  [1] The request: NFT_MSG_GETOBJ (19) on NFNL_SUBSYS_NFTABLES, a dump, NFTA_OBJ_TABLE = the table, NFTA_OBJ_TYPE = counter.
  [2] The reply, built here as the kernel sends it (several messages per datagram, nested NFTA_OBJ_DATA, NLMSG_DONE): every
      counter's name, packets and bytes, as u64 INTEGERS (a float anywhere in the sync body could be refused by the panel).
  [3] Anything unexpected is None — and the callers then read with nft exactly as before: no socket (EPERM), an error reply,
      a table that answers with no counters (missing), a truncated message. Said once.
  [4] The callers: P2P's torrent sum and device access's per-interface packets are the same numbers from netlink as from the
      nft JSON; device access still answers None for a missing table (through nft).

Run: python3 tests/nft_netlink_counters_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     float        the counters are read as doubles
     emptyok      a table that answers with no counters is taken as "no counters" (a missing table never reads None)
     swap         bytes and packets read the other way round
"""
import importlib.machinery, importlib.util, json, os, struct, subprocess, sys, tempfile, threading

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
    "float": ('''                                by = struct.unpack(">Q", v2[:8])[0]                            # NFTA_COUNTER_BYTES''',
              '''                                by = struct.unpack(">d", v2[:8])[0]                            # NFTA_COUNTER_BYTES'''),
    "emptyok": ('''                if typ == 3:                                                                   # NLMSG_DONE
                    return out or None''', '''                if typ == 3:                                                                   # NLMSG_DONE
                    return out'''),
    "swap": ('''                            if t2 == 1:
                                by = struct.unpack(">Q", v2[:8])[0]''', '''                            if t2 == 2:
                                by = struct.unpack(">Q", v2[:8])[0]'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="nlcounters-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("nl_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("nl_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
LOGS = []
N.log = lambda prio, msg, *a: LOGS.append(msg % a if a else msg)


def nla(t, data, nested=False):
    a = struct.pack("=HH", 4 + len(data), t | (0x8000 if nested else 0)) + data
    return a + b"\0" * ((4 - len(a) % 4) % 4)


def obj_msg(name, packets, bytes_, table="swg_p2p"):
    data = nla(1, struct.pack(">Q", bytes_)) + nla(2, struct.pack(">Q", packets)) + nla(3, b"\0" * 8)   # BYTES, PACKETS, PAD
    body = struct.pack("=BBH", 1, 0, 0) + nla(1, table.encode() + b"\0") + nla(2, name.encode() + b"\0") \
        + nla(3, struct.pack(">I", 1)) + nla(4, data, nested=True) + nla(5, struct.pack(">I", 1))
    return struct.pack("=LHHLL", 16 + len(body), (10 << 8) | 18, 0x2, 1, 0) + body          # NFT_MSG_NEWOBJ, NLM_F_MULTI


DONE = struct.pack("=LHHLL", 20, 3, 0x2, 1, 0) + struct.pack("=i", 0)


def err(code):
    return struct.pack("=LHHLL", 36, 2, 0, 1, 0) + struct.pack("=i", code) + b"\0" * 16


class FakeSock:
    """A netlink socket that answers the one request with `datagrams`."""
    sent = []

    def __init__(self, datagrams, fail=None):
        self.d, self.fail = list(datagrams), fail

    def __call__(self, family, kind, proto):
        if self.fail:
            raise self.fail
        FakeSock.sent.append((family, kind, proto))
        return self

    def settimeout(self, t):
        pass

    def sendto(self, msg, addr):
        FakeSock.sent.append(msg)

    def recv(self, n):
        return self.d.pop(0)

    def close(self):
        pass


def with_sock(fake):
    N.socket = type("S", (), {"socket": fake, "AF_NETLINK": 16, "SOCK_RAW": 3})
    return fake


# ── [1] the request ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the request")
FakeSock.sent = []
with_sock(FakeSock([obj_msg("dht", 3, 300) + obj_msg("bt_tcp", 5, 500), DONE]))
got = N._nft_counters("swg_p2p")
req = [x for x in FakeSock.sent if isinstance(x, bytes)][0]
ln, typ, flags = struct.unpack_from("=LHH", req)
check("[1] NFT_MSG_GETOBJ on the nftables subsystem, a dump, on a NETLINK_NETFILTER socket",
      typ == (10 << 8) | 19 and flags & 0x300 == 0x300 and (16, 3, 12) in FakeSock.sent, (hex(typ), hex(flags), FakeSock.sent[:1]))
attrs = dict(N._nl_attrs(req, 20, ln))
check("[1] filtered to the table and the counter type", attrs.get(1) == b"swg_p2p\0" and attrs.get(3) == struct.pack(">I", 1), attrs)

# ── [2] the reply ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the reply")
check("[2] every counter of a multi-message datagram, packets and bytes", got == {"dht": (3, 300), "bt_tcp": (5, 500)}, got)
check("[2] u64 integers, never floats", all(isinstance(v, int) for pb in (got or {}).values() for v in pb), got)
big = 2 ** 64 - 1
with_sock(FakeSock([obj_msg("fan_flag", big, big), DONE]))
g2 = N._nft_counters("swg_p2p")
check("[2] the largest u64 reads exactly", g2 == {"fan_flag": (big, big)}, g2)
with_sock(FakeSock([obj_msg("a", 1, 10), obj_msg("b", 2, 20) + DONE]))
check("[2] a dump spread over datagrams", N._nft_counters("swg_p2p") == {"a": (1, 10), "b": (2, 20)})

# ── [3] anything unexpected is None ───────────────────────────────────────────────────────────────────────────────────
print("\n[3] anything unexpected → None (the caller reads with nft)")
with_sock(FakeSock([], fail=PermissionError(1, "Operation not permitted")))
LOGS.clear()
check("[3] no socket (EPERM)", N._nft_counters("swg_p2p") is None)
check("[3] …said once", sum("netlink could not read" in l for l in LOGS) == 1, LOGS)
N._nft_counters("swg_p2p")
check("[3] …and only once", sum("netlink could not read" in l for l in LOGS) == 1, LOGS)
with_sock(FakeSock([err(-1)]))
check("[3] an error reply", N._nft_counters("swg_p2p") is None)
with_sock(FakeSock([DONE]))
check("[3] a table that answers with no counters (a missing one) — nft decides", N._nft_counters("no_such") is None)
with_sock(FakeSock([obj_msg("dht", 1, 1)[:30]]))
check("[3] a truncated message", N._nft_counters("swg_p2p") is None)

# ── [4] the callers ───────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the callers")
P2P = {"bt_tcp": (7, 1), "bt_utp": (11, 1), "dht": (13, 1), "udptrk": (17, 1), "fan_flag": (19, 1), "dropped": (99, 1), "held": (5, 1)}
CLI = json.dumps({"nftables": [{"counter": {"family": "inet", "name": n, "table": "swg_p2p", "handle": 1, "packets": p, "bytes": b}}
                               for n, (p, b) in P2P.items()]})


def fake_run(args, input_text=None, timeout=20, env=None):
    RUNS.append(" ".join(args))
    if args[:5] == ["nft", "-j", "list", "counters", "table"]:
        if args[-1] == "swg_p2p":
            return subprocess.CompletedProcess(args, 0, CLI, "")
        if args[-1] == N.REACH_NFT_TABLE and REACH_CLI is not None:
            return subprocess.CompletedProcess(args, 0, REACH_CLI, "")
        return subprocess.CompletedProcess(args, 1, "", "Error: No such file or directory")
    return subprocess.CompletedProcess(args, 0, "", "")


RUNS, REACH_CLI = [], None
N.run = fake_run
N._P2P["on"] = True
with_sock(FakeSock([b"".join(obj_msg(n, p, b) for n, (p, b) in P2P.items()) + DONE]))
a = N._block_activity().get("*", {}).get("torrent")
with_sock(FakeSock([], fail=PermissionError(1, "x")))
RUNS.clear()
b = N._block_activity().get("*", {}).get("torrent")
check("[4] P2P's torrent sum: the same number from netlink as from nft's JSON (the five classified counters)",
      a == b == 7 + 11 + 13 + 17 + 19, (a, b))
check("[4] …netlink spared the nft process, the fallback ran it", any("list counters" in r for r in RUNS), RUNS)
cname = lambda ifn: "c" + ifn.encode().hex()
with_sock(FakeSock([obj_msg(cname("wg1"), 42, 1, N.REACH_NFT_TABLE) + obj_msg(cname("awg2"), 7, 1, N.REACH_NFT_TABLE)
                    + obj_msg("gc", 3, 1, N.REACH_NFT_TABLE) + DONE]))
r1 = N._reach_read_counters()
REACH_CLI = json.dumps({"nftables": [{"counter": {"name": cname("wg1"), "packets": 42, "bytes": 1}},
                                     {"counter": {"name": cname("awg2"), "packets": 7, "bytes": 1}},
                                     {"counter": {"name": "gc", "packets": 3, "bytes": 1}}]})
with_sock(FakeSock([DONE]))
r2 = N._reach_read_counters()
check("[4] device access: the same per-interface packets from netlink as from nft", r1 == r2 == {"wg1": 42, "awg2": 7}, (r1, r2))
REACH_CLI = None
with_sock(FakeSock([DONE]))
check("[4] …and a missing table is still None (nft says so)", N._reach_read_counters() is None)

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
