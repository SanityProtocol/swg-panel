#!/usr/bin/env python3
"""Self-test — nft reads made every pass, kept while the ruleset's generation id is unchanged (docs/CPU-PLAN.md B4).

The turn capture's table and its @ports (only noded writes them) were listed every pass; so were the telemetry chains of
tables a node does not have (swgt: the relay's input chain; svo-im: the whole smart table and its chains). Live-checked on
both (2026-10-10): the same answers as nft, one process instead of one a pass.

  [1] A structural read is kept while the id is the one read before it; the id moves → read again; no id → every pass.
  [2] A telemetry read (structural=False) of a table that is there is fresh every pass — its counters move with traffic,
      not with the id; of a table that is not there, the absence is kept until the id moves.
  [3] Only nft's "No such file or directory" is absence: another error, a timeout, nft missing are never kept.
  [4] The callers: the turn capture reads its table and @ports once while the id holds and again after it moves, and
      @peers (the datapath's) every pass; _block_activity reads a present chain every pass and an absent one once.
  [5] A node with no smart table renders `swg_smart` once, not every pass, and reports the same thing.

Run: python3 tests/nft_kept_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     keepcounters   a telemetry read of a present table is kept
     anyerror       any rc 1 is taken for absence
     peerskept      the turn capture's @peers is kept like @ports
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
    "keepcounters": ("""    if gen is not None and ((structural and r.returncode == 0) or _nft_absent(r)):""",
                     """    if gen is not None and (r.returncode == 0 or _nft_absent(r)):"""),
    "anyerror": ("""    return r.returncode == 1 and "No such file or directory" in (r.stderr or "")""", """    return r.returncode == 1"""),
    "peerskept": ("""    out = _pass_cached("turn-peers", lambda: run(["nft", "list", "set", "inet", TURN_CAP_TABLE, "peers"])).stdout or \"\"""",
                  """    out = _nft_kept(["nft", "list", "set", "inet", TURN_CAP_TABLE, "peers"]).stdout or \"\""""),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="nftkept-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("nk_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("nk_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None
N.STATE_DIR = os.path.join(T, "state")
os.makedirs(N.STATE_DIR, exist_ok=True)

ENOENT = "Error: No such file or directory\nlist chain inet swg_relay inp\n                ^^^^^^^^^\n"
# the kernel: what exists, and what each listing prints (counters move with every read, as traffic would move them)
K = {"gen": 5, "tables": {"swg_turn", "swg_smart"}, "pk": 0, "ports": [56004], "peers": ["203.0.113.9 . 56004"], "err": None}
CALLS = []


def fake_run(args, input_text=None, timeout=20, env=None):
    c = " ".join(args)
    CALLS.append(c)
    if K["err"] is not None:
        return subprocess.CompletedProcess(args, K["err"][0], "", K["err"][1])
    w = args[1] if len(args) > 1 else ""
    if w in ("add", "flush", "delete"):
        K["gen"] += 1                                          # every committed change bumps the generation id
        if args[1:5] == ["add", "element", "inet", N.TURN_CAP_TABLE]:
            K["ports"] = [int(x) for x in args[-1].strip("{} ").split(",")]
        if args[1:5] == ["flush", "set", "inet", N.TURN_CAP_TABLE]:
            K["ports"] = []
        return subprocess.CompletedProcess(args, 0, "", "")
    if args[:2] == ["nft", "list"]:
        table = args[4]
        if table not in K["tables"]:
            return subprocess.CompletedProcess(args, 1, "", ENOENT)
        K["pk"] += 1
        if args[2] == "set" and args[-1] == "ports":
            return subprocess.CompletedProcess(args, 0, "table inet swg_turn {\n\tset ports {\n\t\ttypeof th dport\n\t\telements = { %s }\n\t}\n}\n"
                                               % ", ".join(map(str, K["ports"])), "")
        if args[2] == "set" and args[-1] == "peers":
            return subprocess.CompletedProcess(args, 0, "table inet swg_turn {\n\tset peers {\n\t\telements = { %s }\n\t}\n}\n"
                                               % ", ".join(e + " expires 1m" for e in K["peers"]), "")
        return subprocess.CompletedProcess(args, 0, "table inet %s {\n\tchain x {\n\t\tip saddr 10.8.0.0/24 ip daddr @cat_blku_a counter "
                                           "packets %d bytes 1 drop\n\t}\n}\n" % (table, K["pk"]), "")
    return subprocess.CompletedProcess(args, 0, "", "")


N.run = fake_run
N._nft_genid = lambda: K["gen"]
open(os.path.join(N.STATE_DIR, ".turn-cap-sig"), "w").write(N.TURN_CAP_SIG)


def n(c):
    return sum(x == c for x in CALLS)


# ── [1] structural ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] a structural read")
TT = ["nft", "list", "table", "inet", "swg_turn"]
CALLS.clear()
a, b = N._nft_kept(TT), N._nft_kept(TT)
check("[1] kept while the generation id holds: one process for two reads, the same answer", n(" ".join(TT)) == 1 and a is b)
K["gen"] += 1
N._nft_kept(TT)
check("[1] the id moved: read again", n(" ".join(TT)) == 2)
_g, N._nft_genid = N._nft_genid, lambda: None
N._nft_kept(TT); N._nft_kept(TT)
check("[1] no id: read every time", n(" ".join(TT)) == 4)
N._nft_genid = _g

# ── [2] telemetry ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] a telemetry read")
PR = ["nft", "list", "chain", "inet", "swg_smart", "prerouting"]
CALLS.clear()
p1, p2 = N._nft_kept(PR, structural=False).stdout, N._nft_kept(PR, structural=False).stdout
check("[2] a table that is there: fresh every read — its counters move without the id", n(" ".join(PR)) == 2 and p1 != p2, (p1, p2))
RI = ["nft", "list", "chain", "inet", "swg_relay", "inp"]
CALLS.clear()
r1, r2 = N._nft_kept(RI, structural=False), N._nft_kept(RI, structural=False)
check("[2] a table that is not there: the absence is kept (one process for two reads)", n(" ".join(RI)) == 1 and r2.returncode == 1 and not r2.stdout)
K["tables"].add("swg_relay"); K["gen"] += 1                      # the relay comes up: a transaction
r3 = N._nft_kept(RI, structural=False)
check("[2] …until the id moves: then it is read, and found", n(" ".join(RI)) == 2 and r3.returncode == 0 and "packets" in r3.stdout)
K["tables"].discard("swg_relay"); K["gen"] += 1

# ── [3] only ENOENT is absence ────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] what counts as absence")
for what, err in (("another nft error", (1, "Error: Could not receive tables from kernel: Interrupted system call\n")),
                  ("a timeout", (124, "timeout")), ("nft missing", (127, "No such file or directory: 'nft'"))):
    K["err"] = err
    CALLS.clear()
    N._nft_kept(RI, structural=False); N._nft_kept(RI, structural=False)
    check("[3] %s is never kept" % what, n(" ".join(RI)) == 2, CALLS)
K["err"] = None

# ── [4] the callers ───────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the callers")
CALLS.clear()
for _ in range(4):
    N._LOOP["n"] += 1
    N._ensure_turn_capture([56004])
    N._turn_peer_ips()
check("[4] the turn capture: its table and @ports read once over four passes", n("nft list table inet swg_turn") <= 1
      and n("nft list set inet swg_turn ports") <= 1, CALLS)
check("[4] …@peers (the datapath fills it) every pass", n("nft list set inet swg_turn peers") == 4, CALLS)
CALLS.clear()
N._LOOP["n"] += 1
N._ensure_turn_capture([56004, 56007])                        # a new proxy: @ports is rewritten (the id moves)
N._LOOP["n"] += 1
N._ensure_turn_capture([56004, 56007])
_add = next((i for i, c in enumerate(CALLS) if c.startswith("nft add element")), None)
check("[4] …a new port is written once (the kept @ports said what was there), and @ports is read again after it",
      K["ports"] == [56004, 56007] and sum(c.startswith("nft add element") for c in CALLS) == 1
      and [i for i, c in enumerate(CALLS) if c == "nft list set inet swg_turn ports"] == [i for i, c in enumerate(CALLS)
                                                                                         if c == "nft list set inet swg_turn ports" and i > _add] != [], CALLS)
CALLS.clear()
for _ in range(3):
    N._LOOP["n"] += 1
    N._block_activity()
check("[4] _block_activity: a present chain read every pass, an absent table's chain once",
      n("nft list chain inet swg_smart prerouting") == 3 and n("nft list chain inet swg_relay inp") == 1, CALLS)

# ── [5] no smart table ────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] a node with no smart table")
K["tables"].discard("swg_smart"); K["gen"] += 1
N._dnsmasq_running, N._route_localnet_ok, N._blk_domains_read = (lambda: False), (lambda: True), (lambda: {})
CALLS.clear()
outs = []
for _ in range(3):
    N._LOOP["n"] += 1
    outs.append(N.smart_status())
check("[5] `swg_smart` rendered once over three passes", n("nft list table inet swg_smart") == 1, CALLS)
check("[5] …and the same report every pass (no table: active false, no sets)", outs[0] == outs[1] == outs[2]
      and outs[0]["active"] is False and outs[0]["sets"] == {}, outs)

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
