#!/usr/bin/env python3
"""Self-test — the fast lane under pressure (docs/DATAPATH-PLAN.md D3; §11 decisions 9, 10 and 11).

A node out of CPU hands established flows to the kernel's flowtable fast path. Each beat drops `ip swg_fast` (every flow
back on the rules), holds 0.5 s to read the statistics and what the normal path costs, and loads it again. It starts at
the panel's `fast_lane` (% CPU, default 70, 0 = Off) and stops 20 points lower, and only when conntrack's count rose.

  [1] the table: a flowtable on the node's own tunnels and its WAN, each once and only if it exists, names nft can quote;
      `open` by `typeof iifname`, every element on a timeout of max(30 s, 3 intervals); the rule offloads past packet 32,
      original direction, established, after every verdict chain; `table ip`; nothing to offload raises
  [2] the start: three beats in a row at or above the start with 2,000+ forwarded packets/s, and conntrack's count rose
      since the beat before; never before the panel's first answer, never at Off, never without the rise (entries outlive
      their user), never on a node whose nft could not drop the table at start, never in the 10 minutes after a failure;
      at most a beat every 4 s
  [3] a beat: the drop first, then the hold — the statistics read at both ends, the CPU across the sleep only (noded's own
      spawns stay out of it) — then the load
  [4] the stop: 12 holds in a row below the start − 20 (one at or above starts the count again), then no load and the
      statistics from a baseline; a start of 90 stops below 70; Off in the panel drops it at the next beat, with no hold
  [5] failures land on the safe side: a refused load → dropped, off, no start for 10 minutes; a refused drop keeps it on,
      and the next beat drops again and turns it off — no hold and no load after a failure
  [6] the statistics: between holds the held rate, with no read and no spawn; in a hold every reader reads whatever its
      5 s gate says, the first read a baseline and the second the rate; Top destinations from the counters as they are
      now, not the loop's render (none to read: the last rate stands); off: the next ordinary read is a baseline
  [7] the wiring: the startup drop before the loop (its rc is `ok`), `snap = None` at the top of each loop, the setting
      read on a valid sync, the beat after the relay watchdog in a try of its own; the steer keeps pps; the setting is
      read defensively
  [8] the panel: /api/nodes/update takes 0, 50, 60, 70, 80, 90 as an exact int and stores none at 70; the sync reply
      carries `fast_lane` only when it is not 70 — a node left alone gets the reply's keys the build before gave it

Hermetic (a panel on 127.0.0.1 for [8]). Run: python3 tests/fast_lane_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     nowan      the WAN is left off the device list                                     [1]
     noexist    a device that is not there goes on the list (the load is refused)        [1]
     opentype   `open` declared by type, not `typeof iifname`                            [1]
     norise     the start without conntrack's rise (leftover entries pass it)             [2]
     nosetting  the start before the panel's first answer, and at Off                     [2] [4]
     nopps      the start on CPU alone, with light traffic                                [2]
     noretry    a new start inside the 10 minutes after a failure                         [2]
     okgate     a start on a node whose nft could not drop the table at start             [2]
     nofour     a beat on every loop (a 1 s turn-job loop holds half the time)            [2]
     heldcpu    the hold's CPU read across the statistics' spawns                         [3]
     nodrop     the beat loads without dropping first                                     [3]
     stop1      off after one quiet hold                                                  [4]
     nogap      off below the start itself, not 20 points under it                        [4]
     offload    the table loaded again after the stop                                     [4]
     panelstay  Off in the panel leaves the lane on                                       [4]
     failstay   a failure sets no 10 minutes (a load after it)                            [5]
     failon     a refused drop turns it off (a table left that no beat drops)             [5]
     heldread   between holds the internet lane reads its counters                        [6]
     gate5      in a hold the internet lane's 5 s gate applies (no rate from the hold)    [6]
     nobaseline the hold's first read is no baseline (a rate spans the offloaded seconds) [6]
     catrender  in a hold Top destinations read the loop's render (no rate)               [6]
     nosnapnone `snap` kept from the pass before                                          [7]
     panelint   the panel takes False and 50.0 (an int's equals)                          [8]
     panel70    the panel stores 70                                                       [8]
     panelwire  the reply carries `fast_lane` at the default too                          [8]
"""
import atexit, importlib.machinery, importlib.util, json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL") or os.path.join(ROOT, "swg-panel-server")
REF = "35f1cc88"                     # the build before the fast lane (DP2b + dp2a-v6)

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


DROPLINE = "    _fast_nft(_FAST_DROP)                                    # the beat: every flow is back on the rules\n"
HOLD = ("        _fast_samples(node_cfg)\n        a = _cpu_fields()\n"
        "        time.sleep(0.5)                                      # every flow on the normal path: the node as it is without the lane\n"
        "        b = _cpu_fields()\n        _fast_samples(node_cfg)\n")
PLANTS = {
    "nowan": ("[1]", NODED, "_own_tunnel_devs(node_cfg) | {wan}", "_own_tunnel_devs(node_cfg)"),
    "noexist": ("[1]", NODED, ' and os.path.exists("/sys/class/net/" + d))', ")"),
    "opentype": ("[1]", NODED, "set open { typeof iifname;", "set open { type ifname;"),
    "norise": ("[2]", NODED, '\n                or _FAST["ct"] <= c):', "):"),
    "nosetting": ("[2] [4]", NODED, '    start = _FAST["start"]\n', '    start = _FAST["start"] or FAST_DEFAULT\n'),
    "nopps": ("[2]", NODED, ' and _STEER.get("pps", 0) >= FAST_PPS else 0', " else 0"),
    "noretry": ("[2]", NODED, 'not _FAST["ok"] or now < _FAST["retry"] or c is None', 'not _FAST["ok"] or c is None'),
    "okgate": ("[2]", NODED, '_FAST["n"] < 3 or not _FAST["ok"] or now', '_FAST["n"] < 3 or now'),
    "nofour": ("[2]", NODED, '    if now - _FAST["t"] < 4:', "    if False:"),
    "heldcpu": ("[3]", NODED, HOLD, HOLD.replace("        _fast_samples(node_cfg)\n        a = _cpu_fields()\n",
                                                 "        a = _cpu_fields()\n        _fast_samples(node_cfg)\n")
                                       .replace("        b = _cpu_fields()\n        _fast_samples(node_cfg)\n",
                                                "        _fast_samples(node_cfg)\n        b = _cpu_fields()\n")),
    "nodrop": ("[3]", NODED, DROPLINE, "    pass\n"),
    "stop1": ("[4]", NODED, '    if _FAST["n"] >= 12:', '    if _FAST["n"] >= 1:'),
    "nogap": ("[4]", NODED, "busy < start - FAST_GAP else 0", "busy < start else 0"),
    "offload": ("[4]", NODED, '        _fast_off("the normal path below %d %% CPU for a minute" % (start - FAST_GAP))\n        return\n',
                '        _fast_off("the normal path below %d %% CPU for a minute" % (start - FAST_GAP))\n'),
    "panelstay": ("[4]", NODED, '    if not start or now < _FAST["retry"]:', '    if now < _FAST["retry"]:'),
    "failstay": ("[5]", NODED, '    _FAST["retry"] = time.time() + FAST_RETRY_S\n', "    pass\n"),
    "failon": ("[5]", NODED, '(%s): again at the next beat" % (e, e2))\n        return\n',
               '(%s): again at the next beat" % (e, e2))\n        _FAST["on"] = False\n        return\n'),
    "heldread": ("[6]", NODED, '    if _FAST["on"] and not _FAST["held"]:              # the fast lane carries most flows past the counters: the hold\'s rate\n'
                               '        return dict(_INET["rate"])\n', ""),
    "gate5": ("[6]", NODED, '    if not _FAST["held"] and _INET["cum"] is not None and', '    if _INET["cum"] is not None and'),
    "nobaseline": ("[6]", NODED, "        _stats_baseline()                                    # the statistics' slice starts here\n", ""),
    "catrender": ("[6]", NODED, "        cum = _smart_cat_bytes((c, v[1]) for c, v in nl.items())\n", ""),
    "nosnapnone": ("[7]", NODED, "        snap = None                                 # …and the fast lane", "        pass                                        # …and the fast lane"),
    "panelint": ("[8]", PANEL, "if type(_fl) is not int or _fl not in FAST_LANE_STEPS:", "if _fl not in FAST_LANE_STEPS:"),
    "panel70": ("[8]", PANEL, "            if _fl == FAST_LANE_DEFAULT:\n                nodes[nid].pop", "            if False:\n                nodes[nid].pop"),
    "panelwire": ("[8]", PANEL, '**({"fast_lane": node["fast_lane"]}       # the fast lane\'s start (D3), only when not 70\n'
                                '                                   if node.get("fast_lane", FAST_LANE_DEFAULT) != FAST_LANE_DEFAULT else {})',
                  '**({"fast_lane": node.get("fast_lane", FAST_LANE_DEFAULT)}       # the fast lane\'s start (D3), only when not 70\n'
                  '                                   if True else {})'),
}
TMP = tempfile.mkdtemp(prefix="fast-lane-")
atexit.register(shutil.rmtree, TMP, True)
srcs = {NODED: NODED, PANEL: PANEL}
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _sec, target, old, new = PLANTS[PLANT]
    text = open(target, encoding="utf-8").read()
    assert text.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, text.count(old))
    srcs[target] = os.path.join(TMP, "planted-" + os.path.basename(target))
    open(srcs[target], "w", encoding="utf-8").write(text.replace(old, new, 1))
os.environ["SWG_NODED_STATE"] = os.path.join(TMP, "state")
_l = importlib.machinery.SourceFileLoader("swgnoded_fast", srcs[NODED])
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_fast", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
CP = subprocess.CompletedProcess
SRC = open(srcs[NODED], encoding="utf-8").read()


# ── the harness: a clock, the kernel's answers, the events in order ──────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    monotonic = time

    def sleep(self, s):
        EV.append("sleep")
        self.t += s


EV, LOGS = [], []
RC = {"drop": 0, "load": 0}
CT = [100]
BUSY = [90.0]
CPUQ = []
DEVS = {"wg1", "awg2", "swg_4d548000", "wdtt1", "csqtt2", "wgx-ab12cd34"}
REAL_RUN, REAL = N.run, {k: getattr(N, k) for k in ("sample_inet", "sample_catk", "sample_cats", "_smart_table", "_nft_counters",
                                                    "_nft_gate", "read_inet_bytes", "inet_managed_ifaces")}
N.time = Clock()


def fake_run(args, input_text=None, timeout=20, env=None):
    if input_text == N._FAST_DROP:
        EV.append("drop")
        return CP(args, RC["drop"], "", "" if RC["drop"] == 0 else "Error: drop refused")
    if "flowtable" in (input_text or ""):
        EV.append("load")
        return CP(args, RC["load"], "", "" if RC["load"] == 0 else "Error: load refused")
    EV.append("run:" + " ".join(args[:3]))
    return CP(args, 0, "", "")


def fake_cpu(proc_root="/proc"):
    EV.append("cpu")
    if not CPUQ:                                             # a hold's two reads: BUSY % across them
        CPUQ.extend([{"cpu": (1000, 10000, 0)}, {"cpu": (1000 + BUSY[0], 10100, 0)}])
    return CPUQ.pop(0)


N.run = fake_run
N.log = lambda prio, msg, *a: LOGS.append((prio, msg % a if a else msg))
N._cpu_fields = fake_cpu
N._ct_count = lambda: CT[0]
N._own_tunnel_devs = lambda node_cfg=None: set(DEVS)
_real_exists = os.path.exists
os.path.exists = lambda p: (p[len("/sys/class/net/"):] in DEVS | {"eth0"}) if str(p).startswith("/sys/class/net/") else _real_exists(p)
for k in ("sample_inet", "sample_catk", "sample_cats"):
    setattr(N, k, (lambda name: (lambda *a, **kw: EV.append("sample:" + name)))(k))
CFG = {"interfaces": {}}


def reset(start=70, ok=True):
    EV.clear(); LOGS.clear(); CPUQ.clear()
    RC.update(drop=0, load=0)
    BUSY[0] = 90.0
    N._FAST.update(on=False, held=False, ok=ok, t=0.0, n=0, ct=None, retry=0.0, start=start, wan="eth0")
    N._STEER["pps"] = 3000


def beat(cpu=80, pps=3000, rise=True, snap=True, busy=None, dt=5.0):
    """One loop's beat as main runs it: the snapshot's CPU, the steer's pps, conntrack's count (rising or not)."""
    N.time.t += dt
    if rise:
        CT[0] += 7
    if busy is not None:
        BUSY[0] = busy
    N._STEER["pps"] = pps
    s = {"health": {"cpu_pct": cpu}, "wan_iface": "eth0"} if snap else None
    try:
        N._fast_beat(CFG, s, 5)
    except Exception as e:
        N._fast_failed(e)


def turn_on():
    reset()
    for _ in range(3):
        beat()
    assert N._FAST["on"], LOGS


# ── [1] the table ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the table")
DEVS = {"wg1", "awg2", "swg_4d548000", "wdtt1", "csqtt2", "wgx-ab12cd34", "gone0", 'bad"q', ""}
_present = {"wg1", "awg2", "swg_4d548000", "wdtt1", "csqtt2", "wgx-ab12cd34", 'bad"q'}
os.path.exists = lambda p: (p[len("/sys/class/net/"):] in _present | {"eth0"}) if str(p).startswith("/sys/class/net/") else _real_exists(p)
t5 = N._fast_table(CFG, "eth0", 5)
devs = re.findall(r'"([^"]+)"', (re.search(r"devices = \{ ([^}]*) \}", t5) or [None, ""])[1])
want = sorted(_present - {'bad"q'} | {"eth0"})
check("[1] the flowtable's devices: the node's own tunnels and the WAN, sorted", devs == want, (devs, want))
DEVS.add("eth0")
_d2 = re.findall(r'"([^"]+)"', (re.search(r"devices = \{ ([^}]*) \}", N._fast_table(CFG, "eth0", 5)) or [None, ""])[1])
check("[1] …a WAN that is also among the node's devices appears once (a duplicate refuses the load)", _d2 == want, _d2)
check("[1] …a device that is not there stays off it (it would refuse the whole load)", "gone0" not in t5, t5)
check("[1] …and a name nft could not quote", 'bad"q' not in t5 and '""' not in t5, t5)
els = re.search(r"set open \{ typeof iifname; flags timeout; elements = \{ ([^}]*) \}; \}", t5)
check("[1] `open` by `typeof iifname`, its elements the same devices, each on a 30 s timeout at a 5 s interval",
      els is not None and re.findall(r'"([^"]+)" timeout 30s', els.group(1)) == want, els and els.group(1))
check("[1] …3 intervals at a 20 s interval (it must not lapse between beats)",
      re.findall(r'"([^"]+)" timeout 60s', N._fast_table(CFG, "eth0", 20)) == want)
check("[1] the rule: both devices in `open`, original direction, established, past packet 32 → the flowtable",
      "    iifname @open oifname @open ct direction original ct state established ct original packets > 32 flow add @ft\n" in t5, t5)
check("[1] `table ip swg_fast`, its chain after every verdict chain (filter + 10), the flowtable on ingress",
      t5.startswith("table ip swg_fast {\n") and "type filter hook forward priority filter + 10; policy accept;" in t5
      and "flowtable ft { hook ingress priority filter; devices = {" in t5, t5[:300])
_present, DEVS = set(), {"gone0"}                  # (eth0 always exists here: it is passed as no WAN instead)
try:
    N._fast_table(CFG, "", 5)
    _raised = False
except RuntimeError:
    _raised = True
check("[1] nothing to offload raises (never `devices = { }`, which nft refuses)", _raised)
DEVS = {"wg1", "awg2", "swg_4d548000", "wdtt1", "csqtt2", "wgx-ab12cd34"}
_present = set(DEVS)

# ── [2] the start ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[2] the start")
reset()
for i in range(3):
    beat()
    if i < 2:
        check("[2] beat %d at 80 %% with the count rising: not yet" % (i + 1), not N._FAST["on"] and "load" not in EV, EV)
check("[2] the third beat in a row at or above 70 %, 2,000+ packets/s and a rise: on, dropped first, loaded",
      N._FAST["on"] and EV.count("drop") == 1 and EV[-1] == "load", (N._FAST, EV))
check("[2] …and says so once", sum("fast lane: on" in m for _, m in LOGS) == 1, LOGS)
reset()
for _ in range(8):
    beat(rise=False)
check("[2] no rise in conntrack's count: never on (leftover entries prove nothing; conntrack may be unhooked)",
      not N._FAST["on"] and "load" not in EV, (N._FAST, EV))
reset(start=None)
for _ in range(8):
    beat()
check("[2] before the panel's first answer: never on (a node set to Off must not start while the panel is away)",
      not N._FAST["on"] and not EV, EV)
reset(start=0)
for _ in range(8):
    beat()
check("[2] Off: never on", not N._FAST["on"] and not EV, EV)
reset()
for _ in range(8):
    beat(pps=1999)
check("[2] below 2,000 packets/s: never on (a CPU spike with light traffic)", not N._FAST["on"], N._FAST)
reset()
for c in (80, 80, 69, 80, 80):
    beat(cpu=c)
check("[2] a beat below the start in between counts the three again", not N._FAST["on"], N._FAST)
beat()
check("[2] …the third in a row after it: on", N._FAST["on"])
reset()
for _ in range(8):
    beat(snap=False)
check("[2] no snapshot (a pass that raised): no CPU read, never on", not N._FAST["on"], N._FAST)
reset(start=90)
for _ in range(5):
    beat(cpu=85)
check("[2] a start of 90: 85 % never starts it", not N._FAST["on"])
for _ in range(3):
    beat(cpu=90)
check("[2] …90 % does", N._FAST["on"])
reset(ok=False)
for _ in range(8):
    beat()
check("[2] a node whose nft could not drop the table at start: never on", not N._FAST["on"] and "load" not in EV, EV)
reset()
N._FAST["retry"] = N.time.t + 600
for _ in range(10):
    beat()
check("[2] inside the 10 minutes after a failure: never on", not N._FAST["on"], N._FAST)
beat(dt=600)
check("[2] …after them, on at the next beat", N._FAST["on"], N._FAST)
turn_on()
EV.clear()
beat(dt=1.0)
beat(dt=1.0)
check("[2] a beat at most every 4 s (a 1 s turn-job loop must not hold half the time)", EV.count("drop") == 0, EV)
beat(dt=3.0)
check("[2] …the next one after 4 s", EV.count("drop") == 1, EV)

# ── [3] a beat ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] a beat")
turn_on()
EV.clear()
beat(busy=95)
S3 = ["sample:sample_inet", "sample:sample_catk", "sample:sample_cats"]
check("[3] drop, the statistics, CPU, the 0.5 s sleep, CPU, the statistics, load — in that order",
      EV == ["drop"] + S3 + ["cpu", "sleep", "cpu"] + S3 + ["load"], EV)
check("[3] …the hold is over when it loads", N._FAST["held"] is False)

# ── [4] the stop ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[4] the stop")
turn_on()
for i in range(11):
    beat(busy=40)
check("[4] 11 holds below 50 %: still on, loaded each time", N._FAST["on"] and EV[-1] == "load", EV[-3:])
EV.clear()
beat(busy=40)
check("[4] the 12th: off, dropped, not loaded again", not N._FAST["on"] and "drop" in EV and "load" not in EV, EV)
check("[4] …the statistics start again from a baseline", N._INET["cum"] is None and N._CATK["cum"] is None and N._CATS["cum"] == {})
check("[4] …and it says so", any("fast lane: off" in m for _, m in LOGS), LOGS)
turn_on()
LOGS.clear()
for b in [40] * 11 + [55] + [40] * 11:
    beat(busy=b)
check("[4] one hold at 55 % starts the count again: on all through 11 + 1 + 11", N._FAST["on"]
      and not any("fast lane: off" in m for _, m in LOGS), LOGS)
turn_on()
LOGS.clear()
for _ in range(14):
    beat(busy=60)
check("[4] holds at 60 % with a start of 70: no stop (the stop is 20 points lower)", N._FAST["on"]
      and not any("fast lane: off" in m for _, m in LOGS), LOGS)
reset(start=90)
for _ in range(3):
    beat(cpu=95)
for _ in range(12):
    beat(busy=65)
check("[4] a start of 90 stops below 70", not N._FAST["on"], N._FAST)
turn_on()
N._FAST["start"] = 0
EV.clear()
beat()
check("[4] Off in the panel: the next beat drops it and turns it off — no hold, no load",
      not N._FAST["on"] and EV == ["drop"], EV)

# ── [5] failures ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[5] failures")
turn_on()
RC["load"] = 1
EV.clear()
beat()
check("[5] a refused load: dropped again, off, logged as an error", not N._FAST["on"] and EV[-1] == "drop"
      and any(p == N.LOG_ERR and "fast lane" in m for p, m in LOGS), (EV, LOGS[-2:]))
RC["load"] = 0
EV.clear()
for _ in range(20):
    beat()
check("[5] …no start for 10 minutes", not N._FAST["on"] and "load" not in EV, EV)
for _ in range(110):
    beat()
check("[5] …and after them it starts again", N._FAST["on"], N._FAST)
turn_on()
RC["drop"] = 1
EV.clear()
beat()
check("[5] a refused drop: it stays on (its table may still be there), logged", N._FAST["on"] and EV == ["drop", "drop"]
      and any("could not be dropped" in m for _, m in LOGS), (EV, LOGS[-2:]))
RC["drop"] = 0
EV.clear()
beat()
check("[5] …the next beat drops it and turns it off: no hold, no load", not N._FAST["on"] and EV == ["drop"], EV)
turn_on()
RC["drop"] = 1
for _ in range(3):
    beat()
check("[5] a drop refused beat after beat: never a hold or a load, still trying", N._FAST["on"] and "load" not in EV[-6:]
      and "sleep" not in EV[-6:], EV[-6:])
RC["drop"] = 0

# ── [6] the statistics ──────────────────────────────────────────────────────────────────────────────────────────────
print("[6] the statistics")
for k in ("sample_inet", "sample_catk", "sample_cats", "_smart_table", "_nft_counters", "_nft_gate", "read_inet_bytes",
          "inet_managed_ifaces"):
    setattr(N, k, REAL[k])
READS = {"inet": 0, "render": 0, "nl": 0}
INQ, NLQ = [], []


def _rib():
    READS["inet"] += 1
    v = INQ.pop(0) if INQ else None
    return None if v is None else {"up": v[0], "down": v[1], "dev": {}, "g": None}


def _nlc(table, family=1):
    READS["nl"] += 1
    return NLQ.pop(0) if NLQ else None


def _render():
    READS["render"] += 1
    return {"rc": 0, "out": "", "bytes": {"web": {"up": 1, "dn": 1}}}   # the loop's render: what a hold must NOT read


def web(up, dn):
    return {"c_web_up": (1, up), "c_web_dn": (1, dn), "c_bk": (9, 900)}


N.read_inet_bytes = _rib
N.inet_managed_ifaces = lambda cfg: ["wg1"]
N._nft_counters = _nlc
N._smart_table = _render
N._nft_gate = lambda out, c: (None, None)
N._CATK["on"] = False
reset()
N._FAST.update(on=True)
N._INET.update(cum={"up": 5, "down": 5, "g": None}, t=N.time.t, rate={"up": 11.0, "down": 22.0})
N._CATS.update(cum={"web": {"up": 1, "dn": 1}}, t=N.time.t, rate={"web": {"up": 3.0, "dn": 4.0}}, g=(1, 1))
N.time.t += 10
EV.clear()
r_in, r_cat = N.sample_inet(CFG, N.time.t), N.sample_cats()
check("[6] lane on, between holds: the held rates, no read, no spawn",
      r_in == {"up": 11.0, "down": 22.0} and r_cat == {"web": {"up": 3.0, "dn": 4.0}} and READS == {"inet": 0, "render": 0, "nl": 0}
      and not EV, (r_in, r_cat, READS, EV))
INQ[:] = [(1000, 2000), (1500, 3000)]
NLQ[:] = [web(100, 200), web(600, 1200)]
beat()
check("[6] a beat's hold: the internet lane's rate over its 0.5 s, read inside the 5 s gate",
      N._INET["rate"] == {"up": 1000.0, "down": 2000.0} and READS["inet"] == 2, (N._INET["rate"], READS))
check("[6] …Top destinations from the counters as they are now, not the loop's render",
      N._CATS["rate"] == {"web": {"up": 1000.0, "dn": 2000.0}} and READS["nl"] == 2, (N._CATS["rate"], READS))
_r0 = dict(READS)
check("[6] …which the next snapshot reports without a read", N.sample_inet(CFG, N.time.t) == {"up": 1000.0, "down": 2000.0}
      and N.sample_cats() == {"web": {"up": 1000.0, "dn": 2000.0}} and READS == _r0, READS)
INQ[:] = [(1600, 3100), None]                       # 4.5 s of offloaded traffic barely moved the counters; the 2nd read fails
NLQ[:] = [web(650, 1250), None]
beat()
check("[6] a hold whose second read fails: the last hold's rates stand, never one spanning the offloaded seconds",
      N._INET["rate"] == {"up": 1000.0, "down": 2000.0} and N._CATS["rate"] == {"web": {"up": 1000.0, "dn": 2000.0}},
      (N._INET["rate"], N._CATS["rate"]))
N._fast_off("test")
N.time.t += 5
INQ[:] = [(9000, 9000)]
N.sample_inet(CFG, N.time.t)
check("[6] off: the next ordinary read is a baseline (the rate holds, no spike from the offloaded seconds)",
      N._INET["rate"] == {"up": 1000.0, "down": 2000.0}, N._INET["rate"])

# ── [7] the wiring ──────────────────────────────────────────────────────────────────────────────────────────────────
print("[7] the wiring")
M = SRC[SRC.index("\ndef main():"):]
i_ok = M.find('_FAST["ok"] = run(["nft", "-f", "-"], input_text=_FAST_DROP).returncode == 0')
check("[7] the startup drop before the loop, through run, its rc the lane's `ok`", 0 < i_ok < M.find("\n    while True:"), i_ok)
i_none, i_snap = M.find("\n        snap = None"), M.find("snap = build_snapshot(")
check("[7] `snap = None` at the top of each loop, before the sync's try builds it", 0 < i_none < i_snap, (i_none, i_snap))
i_ok200 = M.find('if status == 200 and isinstance(reply.get("desired"), dict):')
i_set = M.find('_FAST["start"] = _fast_setting(reply.get("fast_lane", FAST_DEFAULT))')
check("[7] the setting read on a valid sync, before the pass's reconcile", 0 < i_ok200 < i_set < M.find("reconcile(", i_ok200)
      and i_set < M.find("elif status == 0:"), (i_ok200, i_set))
i_rel, i_beat = M.find("reconcile_relay("), M.find("_fast_beat(node_cfg, snap, interval)")
check("[7] the beat after the relay watchdog, outside the sync's try, in a try of its own that lands a failure safe",
      0 < i_rel < i_beat < M.find("with _TURN_JOBS_LOCK:")
      and re.search(r"\n        try: [^\n]*\n            _fast_beat\(node_cfg, snap, interval\)[^\n]*\n        except Exception as _e:\n"
                    r"            _fast_failed\(_e\)\n", M) is not None, (i_rel, i_beat))
check("[7] the steer keeps the forwarded packets/s the start reads", "_STEER.update(n=n, low=low, pps=pps)" in SRC)
fs = N._fast_setting
check("[7] the setting, read defensively: 0 Off, a step kept, out of range clamped, anything else the default",
      (fs(0), fs(70), fs(50), fs(90), fs(40), fs(120), fs(True), fs(False), fs("70"), fs(None), fs(-5), fs(50.0))
      == (0, 70, 50, 90, 50, 95, 70, 70, 70, 70, 70, 70),
      (fs(0), fs(70), fs(50), fs(90), fs(40), fs(120), fs(True), fs(False), fs("70"), fs(None), fs(-5), fs(50.0)))

# ── [8] the panel ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[8] the panel")
os.path.exists = _real_exists


def start_panel(src_path, tag):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    nodes = os.path.join(state, "nodes.json")
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {}}}, open(nodes, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    fleet = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                sys.exit("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return p, port, state


def req(port, path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw, code = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    return code, json.loads(raw or b"{}")


def sync(port, tok):
    snap = {"hostname": "n1", "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


ref_src = os.path.join(TMP, "ref-swg-panel-server")
open(ref_src, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True,
                                         check=True).stdout)
procs = []
try:
    pr, port_r, _ = start_panel(ref_src, "ref"); procs.append(pr)
    pn, port_n, state_n = start_panel(srcs[PANEL], "new"); procs.append(pn)
    tok_r = req(port_r, "/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    tok_n = req(port_n, "/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    rr, rn = sync(port_r, tok_r), sync(port_n, tok_n)
    check("[8] a node left alone: the reply's keys are the build before's, no `fast_lane`",
          sorted(rr) == sorted(rn) and "fast_lane" not in rn, (sorted(rr), sorted(rn)))
    bad = [v for v in (55, 100, -1, "70", True, False, 70.0, 50.0, None)
           if req(port_n, "/api/nodes/update", {"id": "n1", "fast_lane": v})[0] != 400]
    stored = json.load(open(os.path.join(state_n, "nodes.json")))["n1"]
    check("[8] refused with 400 and nothing stored: 55, 100, -1, \"70\", True, False, 70.0, 50.0, None",
          not bad and "fast_lane" not in stored, (bad, stored.get("fast_lane")))
    c, _r = req(port_n, "/api/nodes/update", {"id": "n1", "fast_lane": 50})
    check("[8] 50: stored, and the node is sent `fast_lane: 50`", c == 200 and sync(port_n, tok_n).get("fast_lane") == 50,
          (c, _r))
    req(port_n, "/api/nodes/update", {"id": "n1", "ip_learning": False})
    check("[8] …a save of another field on the node keeps it", sync(port_n, tok_n).get("fast_lane") == 50)
    req(port_n, "/api/nodes/update", {"id": "n1", "fast_lane": 0})
    check("[8] Off: the node is sent 0", sync(port_n, tok_n).get("fast_lane") == 0)
    req(port_n, "/api/nodes/update", {"id": "n1", "fast_lane": 70})
    stored = json.load(open(os.path.join(state_n, "nodes.json")))["n1"]
    check("[8] back to 70: not stored, and the key is gone from the reply",
          "fast_lane" not in stored and "fast_lane" not in sync(port_n, tok_n), stored.get("fast_lane"))
finally:
    for p in procs:
        p.terminate()
        p.wait(10)

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    caught = [f for f in FAILS if any(f.startswith(s) for s in sec.split())]
    print(("CAUGHT" if caught else "MISSED") + " plant %s (%s): %d check(s) red in its section%s" % (
        PLANT, sec, len(caught), "" if caught else "; red elsewhere: %s" % FAILS[:3]))
    sys.exit(0 if caught else 1)
print("FAIL: %d check(s)" % len(FAILS) if FAILS else "PASS: the fast lane — the table, the start, a beat, the stop, "
      "failures, the statistics, the wiring and the panel's setting")
sys.exit(1 if FAILS else 0)
