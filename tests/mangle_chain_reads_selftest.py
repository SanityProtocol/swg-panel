#!/usr/bin/env python3
"""Self-test — the internet and Kernel SNI counters read their own chains, never a dump of mangle (CPU re-qualification
V2-O2, 2026-10-10).

mangle also holds every Kernel-SNI string rule (10 710 on msk-main in sni_kernel). The two samplers summed their counters
out of `iptables-save -c -t mangle`, which renders every one of those rules: 110 ms of CPU every 5 s at 10 825 rules, about
2.6 % of a core, where `iptables -S <chain> -v` of the 22-rule counting chain costs under 10 ms (iptables-nft fetches the
chain it is asked for; measured on swgt). A node without Kernel SNI has no SWG_CATK chain, and asks for none.

  [1] read_inet_bytes: the totals and the per-exit-device split out of `iptables -S SWG_INET -v` — the counter is the `-c`
      pair's bytes; a chain iptables says is not there (exit 1) counts nothing, as a dump without its lines did; a read
      that failed otherwise (a timeout, no iptables) is None — the sampler keeps the last rate, as it always has.
  [2] sample_catk with no Kernel-SNI category (reconcile_catk_chain([])): {} and no process at all.
  [3] sample_catk with categories: a baseline, then per-category up/dn rates out of `iptables -S SWG_CATK -v`; an
      unreadable chain (a timeout) leaves the last rates (a blip is not "the traffic stopped"); a chain another tool
      removed (exit 1) clears them, as the dump did, until the next pass rebuilds it; an empty chain clears them; a mode
      change (reconcile_catk_chain([])) clears them without a read. The first read once there is a chain is a baseline
      — the chain outlives a noded restart, and its accumulated total is no 5 s rate.
  [4] Neither ever spawns `iptables-save`.

Run: python3 tests/mangle_chain_reads_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     catkdump     sample_catk reads `iptables-save -c -t mangle` again
     inetdump     read_inet_bytes reads `iptables-save -c -t mangle` again
     alwaysread   sample_catk reads the chain on a node without Kernel SNI (a process every 5 s for nothing)
     nooff        reconcile_catk_chain never records that the chain is gone (a mode change keeps the last rates for ever)
     blipclears   an unreadable SWG_CATK clears the rates (a 5 s blip reads as "the traffic stopped", then a spike)
     rc1keeps     a SWG_CATK another tool removed keeps the last rates (they freeze until the next pass, ~65 s)
     inetrc1      a missing SWG_INET reads as unreadable, not as nothing counted (the rate freezes where it read 0)
     spike        no baseline after a node without the chain gets one: a restart in Kernel SNI reports the chain's whole
                  total as one 5 s rate
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
    "catkdump": ('r = run(["iptables", "-t", "mangle", "-S", SWG_CATK_CHAIN, "-v"])',
                 'r = run(["iptables-save", "-c", "-t", "mangle"])'),
    "inetdump": ('r = run(["iptables", "-t", SWG_INET_TABLE, "-S", SWG_INET_CHAIN, "-v"])',
                 'r = run(["iptables-save", "-c", "-t", SWG_INET_TABLE])'),
    "alwaysread": ('    if not _CATK["on"]:                                     # no Kernel-SNI category here',
                   '    if False:                                     # no Kernel-SNI category here'),
    "nooff": ('    _CATK["on"] = bool(want)                               # sample_catk reads the chain only while there is one\n',
              '    _CATK["on"] = _CATK["on"] or bool(want)\n'),
    "spike": ('        _CATK["cum"] = None; _CATK["rate"] = {}             # None: the first read once there is one is a baseline — the',
              '        _CATK["cum"] = {}; _CATK["rate"] = {}             # None: the first read once there is one is a baseline — the'),
    "blipclears": ('        return dict(_CATK["rate"])                          # a timeout / no iptables → leave last known',
                   '        _CATK["cum"] = {}; _CATK["rate"] = {}; return {}'),
    "rc1keeps": ('    if r.returncode == 1:                                   # iptables ran: no such chain (another tool removed it) → clear,',
                 '    if False:                                   # iptables ran: no such chain (another tool removed it) → clear,'),
    "inetrc1": ('    if r.returncode == 1:                              # iptables ran: no such chain — nothing counted, as a dump without',
                '    if False:                              # iptables ran: no such chain — nothing counted, as a dump without'),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="manglereads-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("mc_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("mc_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None
CP = subprocess.CompletedProcess

# What iptables-nft 1.8.10 prints for `-S <chain> -v` (swgt, 2026-10-10): the comment quoted, the counters last.
INET = ('-N SWG_INET\n'
        '-A SWG_INET -i awg2 -o eth0 -m comment --comment "swg-inet-up:awg2" -c 10 1000\n'
        '-A SWG_INET -i eth0 -o awg2 -m comment --comment "swg-inet-dn:awg2" -c 20 5000\n'
        '-A SWG_INET -i awg2 -o wgx-736a24bf -m comment --comment "swg-inet-up:awg2@wgx-736a24bf" -c 3 300\n'
        '-A SWG_INET -i wgx-736a24bf -o awg2 -m comment --comment "swg-inet-dn:awg2@wgx-736a24bf" -c 4 700\n')
DUMP = ('*mangle\n:SWG_INET - [0:0]\n'
        '[10:1000] -A SWG_INET -i awg2 -o eth0 -m comment --comment "swg-inet-up:awg2"\n'
        '[0:0] -A SWG_CATK -m set --match-set swgk_c1 dst -m comment --comment "swg-catk-up:c1"\nCOMMIT\n')


def catk(c1up, c1dn, c2up):
    return ('-N SWG_CATK\n'
            '-A SWG_CATK -m set --match-set swgk_c1 dst -m comment --comment "swg-catk-up:c1" -c 1 %d\n'
            '-A SWG_CATK -m set --match-set swgk_c1 src -m comment --comment "swg-catk-dn:c1" -c 1 %d\n'
            '-A SWG_CATK -m set --match-set swgk_c2 dst -m comment --comment "swg-catk-up:c2" -c 1 %d\n'
            '-A SWG_CATK -m set --match-set swgk_c2 src -m comment --comment "swg-catk-dn:c2" -c 0 0\n') % (c1up, c1dn, c2up)


CALLS = []
REPLY = {"inet": (0, INET), "catk": (0, catk(0, 0, 0))}


def fake(args, input_text=None, timeout=20, env=None):
    CALLS.append(list(args))
    if args[0] == "iptables-save":
        return CP(args, 0, DUMP, "")
    if args[:3] == ["iptables", "-t", "mangle"] and "-S" in args:
        ch = args[args.index("-S") + 1] if len(args) > args.index("-S") + 1 else ""
        if ch == "SWG_INET":
            rc, out = REPLY["inet"]
            return CP(args, rc, out if rc == 0 else "", "" if rc == 0 else "iptables: No chain/target/match by that name.")
        if ch == "SWG_CATK":
            rc, out = REPLY["catk"]
            return CP(args, rc, out if rc == 0 else "", "" if rc == 0 else "iptables: No chain/target/match by that name.")
        return CP(args, 0, "", "")
    if args[:3] == ["iptables", "-t", "mangle"] and "-nL" in args:
        return CP(args, 0, "", "")                    # the chain is there (reconcile_catk_chain's own probe)
    return CP(args, 0, "", "")


N.run = fake

# ── [1] read_inet_bytes ───────────────────────────────────────────────────────────────────────────────────────────────
print("[1] read_inet_bytes")
CALLS.clear()
got = N.read_inet_bytes()
check("[1] the node totals sum every swg-inet line, exit-tagged ones included (up 1000+300, down 5000+700)",
      got is not None and got["up"] == 1300 and got["down"] == 5700, got)
check("[1] …and the per-exit-device split carries the @-tagged half only",
      got is not None and got["dev"] == {"wgx-736a24bf": {"up": 300, "down": 700}}, got)
check("[1] one read, of the chain alone (`iptables -t mangle -S SWG_INET -v`)",
      CALLS == [["iptables", "-t", "mangle", "-S", "SWG_INET", "-v"]], CALLS)
REPLY["inet"] = (1, "")
check("[1] a chain iptables says is not there (exit 1) counts nothing, as a dump without its lines did",
      N.read_inet_bytes() == {"up": 0, "down": 0, "dev": {}}, N.read_inet_bytes())
REPLY["inet"] = (124, "")
check("[1] a read that failed otherwise (a timeout) is None (the sampler keeps its last rate)", N.read_inet_bytes() is None)
REPLY["inet"] = (0, INET)

# ── [2] no Kernel SNI here ────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] sample_catk on a node without Kernel SNI")
NOW = [1000.0]
N.time = type("T", (), {"time": staticmethod(lambda: NOW[0]), "monotonic": staticmethod(lambda: NOW[0]),
                        "sleep": staticmethod(lambda s: None)})
N.reconcile_catk_chain([])
CALLS.clear()
outs = []
for _ in range(4):
    NOW[0] += 6
    outs.append(N.sample_catk())
check("[2] four samples: {} each, and not one process spawned", outs == [{}] * 4 and CALLS == [], (outs, CALLS))

# ── [3] Kernel SNI categories ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] sample_catk with Kernel-SNI categories")
N.reconcile_catk_chain(["c1", "c2"])
REPLY["catk"] = (0, catk(1000, 2000, 0))
CALLS.clear()
NOW[0] += 6
first = N.sample_catk()
check("[3] the first read once there is a chain is a baseline — its accumulated total (a restart) is no rate",
      first == {}, first)
REPLY["catk"] = (0, catk(1000 + 5000, 2000 + 10000, 2500))
NOW[0] += 5
r = N.sample_catk()
check("[3] up/dn per category from the `-c` bytes: c1 1000/2000 B/s, c2 500/0 B/s over 5 s",
      r.get("c1") == {"up": 1000.0, "dn": 2000.0} and r.get("c2") == {"up": 500.0, "dn": 0.0}, r)
check("[3] each read is `iptables -t mangle -S SWG_CATK -v`, nothing else",
      CALLS and all(c == ["iptables", "-t", "mangle", "-S", "SWG_CATK", "-v"] for c in CALLS), CALLS)
REPLY["catk"] = (124, "")
NOW[0] += 5
check("[3] an unreadable chain (a timeout) leaves the last rates (a blip is not \"the traffic stopped\")", N.sample_catk() == r, N._CATK)
REPLY["catk"] = (0, catk(1000 + 10000, 2000 + 20000, 5000))
NOW[0] += 5
r2 = N.sample_catk()
check("[3] …and the next good read rates over the whole gap, with no spike (c1 up 5000 B over 10 s = 500 B/s)",
      r2.get("c1", {}).get("up") == 500.0, r2)
REPLY["catk"] = (0, "-N SWG_CATK\n")
NOW[0] += 5
check("[3] an empty chain (being rebuilt) clears the rates", N.sample_catk() == {}, N._CATK)
REPLY["catk"] = (0, catk(9000, 9000, 9000))
NOW[0] += 5
N.sample_catk()
REPLY["catk"] = (1, "")
NOW[0] += 5
check("[3] a chain another tool removed (exit 1) clears the rates, as the dump did", N.sample_catk() == {}, N._CATK)
REPLY["catk"] = (0, catk(500000, 500000, 500000))
NOW[0] += 5
check("[3] …and its return is a baseline: the next pass rebuilds it, its count is no 5 s rate", N.sample_catk() == {}, N._CATK)
REPLY["catk"] = (0, catk(7, 7, 7))
NOW[0] += 5
N.sample_catk()
N.reconcile_catk_chain([])
CALLS.clear()
NOW[0] += 5
check("[3] a mode change away from Kernel SNI clears them, without a read", N.sample_catk() == {} and CALLS == [], CALLS)

# ── [4] never a dump ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] never a dump of mangle")
CALLS.clear()
N.reconcile_catk_chain(["c1"])
for _ in range(3):
    NOW[0] += 6
    N.sample_catk(); N.read_inet_bytes()
check("[4] no `iptables-save` in a sampled minute", not any(c[0] == "iptables-save" for c in CALLS),
      [c for c in CALLS if c[0] == "iptables-save"])

print("")
if PLANT:
    print(("--plant %s: CAUGHT (%d red)" % (PLANT, len(FAILS))) if FAILS else "--plant %s: NOTHING FAILED" % PLANT)
    sys.exit(0 if FAILS else 1)
print("GREEN — 0 failed" if not FAILS else "RED — %d failed" % len(FAILS))
sys.exit(1 if FAILS else 0)
