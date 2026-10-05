#!/usr/bin/env python3
"""Self-test — units that still write the MAIN journal are moved in the update window; a docker node's host helper has no
network of its own.

1. noded writes `LogNamespace=swg-node` drop-ins for the families it runs (swg-relay@, vk-turn-proxy-, swg-wdtt-,
   swg-csqtt-) and restarts nothing (LOGS-PLAN: never cut the datapath at the update). A running process keeps the stream
   it was started with, so a server started before its drop-in wrote the main journal — outside the budget — until its
   next start: weeks for a turn proxy / WDTT / csqtt (msk-main 10-05: five servers since 10-02, 23 % of the main journal).
   _log_ns_move restarts exactly those, once, inside the operator's update window (panel `geo_update`).
2. host_sh on a docker node is a one-shot privileged helper container per host command. On the default bridge each one
   cost a veth pair, and the kernel/networkd/udev/dockerd lines of that churn were ~60 % of svo-im's main journal. nsenter
   -n enters the host's network anyway, so the helper runs with --network none.

  [1] _log_ns_unmoved: running, started before its family's drop-in → listed; started after, or a family without a
      drop-in → not; no namespaces on this system → nothing asked
  [2] _log_ns_move: outside the window nothing; inside one restart of exactly the unmoved units, once per window (a
      failed restart waits for the next window); nothing unmoved → no restart; a continuous schedule is a daily window
  [3] the window arrives with the panel's settings (apply_panel_settings → _LOG_NS_MOVE["sched"])
  [4] host_sh on a docker node: --network none, still nsenter -n into PID 1

Run: python3 tests/log_ns_move_selftest.py        (0 = pass)
     --plant nowindow|everypass|order|continuous|bridge    the defect it names, planted → RED
"""
import datetime, importlib.machinery, importlib.util, io, os, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "nowindow":   ("    if _LOG_NS_MOVE[\"day\"] == day or not _in_quiet_window(sched):\n",
                   "    if _LOG_NS_MOVE[\"day\"] == day:\n"),
    "everypass":  ("    if _LOG_NS_MOVE[\"day\"] == day or not _in_quiet_window(sched):\n",
                   "    if not _in_quiet_window(sched):\n"),
    "order":      ("                if started < written[fam] - 1:", "                if started > written[fam] - 1:"),
    "continuous": ("    if str(sched.get(\"every_days\", 1)) == \"0\":\n        sched[\"every_days\"] = 1\n", ""),
    "bridge":     ("\"--pid=host\", \"--network\", \"none\", \"--entrypoint\"", "\"--pid=host\", \"--entrypoint\""),
}
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if PLANT:
    a, b = PLANTS[PLANT]
    assert src.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    src = src.replace(a, b)
TMP = tempfile.mkdtemp(prefix="lnsmove-")
prog = os.path.join(TMP, "swg-noded"); open(prog, "w", encoding="utf-8").write(src)
os.environ["SWG_NODED_STATE"] = os.path.join(TMP, "state")
ld = importlib.machinery.SourceFileLoader("lnsmove_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
ld.exec_module(N)
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N._LOG_STREAM = io.StringIO(); N._LOG_JOURNAL = False

UD = os.path.join(TMP, "units")
N.UNIT_DIR_PERSIST = UD
N.unit_dir_persists = lambda: True
N.log_ns_ok = lambda: True
NOW = time.time()
def dropin(fam, age_s):
    p = os.path.join(UD, fam + ".d", N.LOG_NS_DROPIN)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("[Service]\nLogNamespace=swg-node\n")
    os.utime(p, (NOW - age_s, NOW - age_s))
dropin("swg-wdtt-.service", 3600)            # written an hour ago
dropin("swg-csqtt-.service", 3600)
dropin("vk-turn-proxy-.service", 3600)
#                                             (no swg-relay@ drop-in: that family must never be asked about)
UNITS = {"swg-wdtt-wdtt1.service": 7200,      # started 2 h ago → before its drop-in → unmoved
         "swg-wdtt-wdtt2.service": 600,       # started 10 min ago → after → moved
         "swg-csqtt-csqtt1.service": 86400,   # a day ago → unmoved
         "vk-turn-proxy-x-1.service": 3601.5, # 1.5 s before the drop-in: past the 1 s slack → unmoved
         "vk-turn-proxy-y-2.service": 3600.5}  # 0.5 s before: inside the slack (started in the pass that wrote it)
CALLS = []; RC = {"restart": 0}
def fake_run(args, input_text=None, timeout=20):
    CALLS.append(list(args))
    if args[:2] == ["systemctl", "list-units"]:
        pats = [a[:-len("*.service")] for a in args if a.endswith("*.service")]
        out = "".join("%s loaded active running x\n" % u for u in UNITS if any(u.startswith(p) for p in pats))
        return subprocess.CompletedProcess(args, 0, out, "")
    if args[:2] == ["systemctl", "show"]:
        mono = time.monotonic()
        blocks = ["Id=%s\nActiveEnterTimestampMonotonic=%d\n" % (u, int((mono - UNITS[u]) * 1e6)) for u in args if u in UNITS]
        return subprocess.CompletedProcess(args, 0, "\n".join(blocks), "")
    if args[:2] == ["systemctl", "restart"]:
        return subprocess.CompletedProcess(args, RC["restart"], "", "boom" if RC["restart"] else "")
    return subprocess.CompletedProcess(args, 0, "", "")
N.run = fake_run

print("[1] _log_ns_unmoved")
got = sorted(N._log_ns_unmoved())
check("[1] started before its family's drop-in → listed; after it, or inside the 1 s slack → not",
      got == ["swg-csqtt-csqtt1.service", "swg-wdtt-wdtt1.service", "vk-turn-proxy-x-1.service"], got)
lu = next((c for c in CALLS if c[:2] == ["systemctl", "list-units"]), [])
check("[1] only the families that HAVE a drop-in are asked about (no swg-relay@ pattern)",
      lu and not any(a.startswith("swg-relay@") for a in lu) and "swg-wdtt-*.service" in lu, lu)
CALLS.clear(); N.log_ns_ok = lambda: False
check("[1] a system without journald namespaces: nothing listed, nothing asked", N._log_ns_unmoved() == [] and not CALLS, CALLS)
N.log_ns_ok = lambda: True

print("[2] _log_ns_move")
_n = datetime.datetime.now()
if _n.hour * 60 + _n.minute < 15:                    # a window that opened before midnight is not one noded can express
    print("  (00:00–00:15: the in-window checks need a window opened today — waiting it out)")
    time.sleep((15 - _n.minute) * 60 - _n.second + 1)
def hhmm(delta_min):
    t = datetime.datetime.now() + datetime.timedelta(minutes=delta_min)
    return "%02d:%02d" % (t.hour, t.minute)
def move(sched):
    CALLS.clear(); N._LOG_NS_MOVE["at"] = 0.0; N._LOG_NS_MOVE["sched"] = sched
    N._log_ns_move()
    return [c for c in CALLS if c[:2] == ["systemctl", "restart"]]
N._LOG_NS_MOVE["day"] = None
check("[2] outside the window: nothing restarted", move({"every_days": 1, "at": hhmm(120)}) == [])
r = move({"every_days": 1, "at": hhmm(-10)})
check("[2] inside the window: ONE restart of exactly the unmoved units",
      r == [["systemctl", "restart", "swg-wdtt-wdtt1.service", "swg-csqtt-csqtt1.service", "vk-turn-proxy-x-1.service"]]
      or (len(r) == 1 and sorted(r[0][2:]) == ["swg-csqtt-csqtt1.service", "swg-wdtt-wdtt1.service", "vk-turn-proxy-x-1.service"]), r)
check("[2] …and once per window: the next minute restarts nothing", move({"every_days": 1, "at": hhmm(-10)}) == [])
N._LOG_NS_MOVE["day"] = None; RC["restart"] = 1
move({"every_days": 1, "at": hhmm(-10)})
check("[2] a failed restart is said, and waits for the next window",
      "failed" in N._LOG_STREAM.getvalue() and move({"every_days": 1, "at": hhmm(-10)}) == [], N._LOG_STREAM.getvalue()[-200:])
RC["restart"] = 0
saved = dict(UNITS); UNITS.clear(); UNITS["swg-wdtt-wdtt2.service"] = 600
N._LOG_NS_MOVE["day"] = None
check("[2] nothing unmoved: no restart, and the window is not used up",
      move({"every_days": 1, "at": hhmm(-10)}) == [] and N._LOG_NS_MOVE["day"] is None, N._LOG_NS_MOVE)
UNITS.clear(); UNITS.update(saved)
for ev in (0, "0"):
    N._LOG_NS_MOVE["day"] = None
    check("[2] a continuous schedule (every_days %r) is a daily window: outside its `at`, nothing" % (ev,),
          move({"every_days": ev, "at": hhmm(120)}) == [])
    N._LOG_NS_MOVE["day"] = None
    check("[2] …and inside it, the move", len(move({"every_days": ev, "at": hhmm(-5)})) == 1)

print("[3] the window comes with the panel's settings")
N._LOG_NS_MOVE["sched"] = {}
N.apply_panel_settings({"geo_update": {"every_days": 2, "at": "03:30"}})
check("[3] apply_panel_settings stores geo_update for the move", N._LOG_NS_MOVE["sched"] == {"every_days": 2, "at": "03:30"},
      N._LOG_NS_MOVE["sched"])
N.apply_panel_settings({})
check("[3] a reply without one → the default window again", N._LOG_NS_MOVE["sched"] == {}, N._LOG_NS_MOVE["sched"])

print("[4] host_sh on a docker node")
N.NODE_KIND = "docker"; N._host_sh_available = lambda: True; CALLS.clear()
N.host_sh("true")
a = CALLS[-1] if CALLS else []
check("[4] the helper runs with --network none (no veth pair per host command)",
      a[:2] == ["docker", "run"] and "--network" in a and a[a.index("--network") + 1] == "none"
      and a.index("--network") < a.index(N.HELPER_IMAGE), a[:12])
check("[4] …and still enters PID 1's namespaces, the network among them", a[a.index("nsenter") - 1:] and
      a[a.index(N.HELPER_IMAGE) + 1:a.index(N.HELPER_IMAGE) + 8] == ["-t", "1", "-m", "-u", "-i", "-n", "-p"], a)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but plant %r was planted and should have gone RED" % PLANT if PLANT else ""))
sys.exit(2 if PLANT else 0)
