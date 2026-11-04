#!/usr/bin/env python3
"""Self-test — the Protection card's rates from a node's cumulative blocking counters (`_blk_rates`).

A node reports torrent, blocked and mech as LIFETIME counts; the panel turns each into a per-hour rate for the block ring.
noded sends its first report after a start before its first P2P pass, so that report carries no `torrent`. Read as 0, the
next report's lifetime count became one interval's rise: 230k–480k torrents an hour on the card at every noded start, every
version (msk-main, 2026-11-04).

  [1] the rule: a first reading reads 0; a field's rise since its own last reading, spread over the time since then; a
      field no key carries reads 0 and keeps its last reading and its time; a counter that went back reads 0 and starts
      over; a clock that went back starts over; a second report in the same second keeps the first and its rise counts at
      the next; fields sum across keys
  [2] the sync: a noded stop of an hour with thousands of counts, replayed through the real history writer
      (`_node_sync_history`) — no burst when the node comes back, and every field reads the stop the same way: its rise
      spread over it, whether the first report after the start carried it or not

Run: python3 tests/block_rate_selftest.py      (0 = pass)
     --plant absent0    a field the report does not carry reads as 0 (before the fix)            → RED on [1] [2]
     --plant packed     a field the report does not carry keeps its value but takes the report's time: its whole rise
                        packed into the next report, a burst after a stop                                → RED on [1] [2]
     --plant clockwait  a clock that went back waits for the old time (rates 0 until then)            → RED on [1]
     --plant synczero   the sync hands the rule its report with the missing fields filled with 0 → RED on [2]
"""
import importlib.machinery, importlib.util, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "absent0": ("[1] [2]", "        if not any(isinstance(v, dict) and f in v for v in (blk or {}).values()):\n",
                "        if False:\n"),
    "packed": ("[1] [2]", "            if p:\n                keep[f] = p\n            continue\n",
               "            if p:\n                keep[f] = (p[0], now)\n            continue\n"),
    "clockwait": ("[1]", "        if p and now == p[1]:\n", "        if p and now <= p[1]:\n"),
    "synczero": ("[2]", "_rt, _bl[nid] = _blk_rates(_bl.get(nid), _blk, now_i)",
                 "_rt, _bl[nid] = _blk_rates(_bl.get(nid), {k: {\"torrent\": 0, \"blocked\": 0, \"mech\": 0, **v} for k, v in _blk.items()}, now_i)"),
}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="block-rate-")
server = os.path.abspath(SERVER)
if PLANT:
    _s, old, new = PLANTS[PLANT]
    src = open(server).read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    server = os.path.join(TMP, "planted-server.py")
    open(server, "w").write(src.replace(old, new, 1))
loader = importlib.machinery.SourceFileLoader("swgpanel", server)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

try:
    SECTION[0] = "[1]"
    print("[1] the rule")
    R = P._blk_rates
    r, k = R(None, {"*": {"torrent": 40000, "blocked": 10}, "10.9.0.0/24": {"mech": 5}}, 1000)
    check("a first reading reads 0 for every field", r == {"torrent": 0, "blocked": 0, "mech": 0}, r)
    r, k = R(k, {"*": {"torrent": 40010, "blocked": 12}, "10.9.0.0/24": {"mech": 6}}, 1005)
    check("a rise over the time since: 10 in 5 s = 7200 an hour", r == {"torrent": 7200, "blocked": 1440, "mech": 720}, r)
    r, k = R(k, {"*": {"blocked": 12}, "10.9.0.0/24": {"mech": 6}}, 1605)
    check("a report without `torrent` reads it 0 …", r["torrent"] == 0, r)
    check("… and keeps its last reading and its time", k.get("torrent") == (40010, 1005), k)
    r, k = R(k, {"*": {"torrent": 40030, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1610)
    check("the next report: the rise since its own last reading, spread over the time since (20 in 605 s)",
          r["torrent"] == int(20 * 3600 / 605), r)
    check("… not the lifetime count, and no burst", r["torrent"] < 1000, r)
    check("`blocked` read through the report without `torrent` (1 in 5 s)", r["blocked"] == 720, r)
    r, k = R(k, {"*": {"torrent": 7, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1615)
    check("a counter that went back (a table made again) reads 0 …", r["torrent"] == 0, r)
    check("… and starts over from its new value", k["torrent"] == (7, 1615), k)
    r, k = R(k, {"*": {"torrent": 9, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1615)
    check("a second report in the same second reads 0 and keeps the first", r["torrent"] == 0 and k["torrent"] == (7, 1615), (r, k))
    r, k = R(k, {"*": {"torrent": 12, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1620)
    check("… its rise counted at the next one (5 in 5 s)", r["torrent"] == 3600, r)
    r, k = R(k, {"*": {"torrent": 12, "blocked": 13}, "10.9.0.0/24": {"mech": 6}, "10.19.0.0/24": {"mech": 4}}, 1625)
    check("a field sums across keys (a second subnet's mech counted)", r["mech"] == int(4 * 3600 / 5), r)
    r, k = R(k, {"*": {"torrent": 20, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1000)
    check("a clock that went back reads 0 and starts over from now (never waits for the old time)",
          r["torrent"] == 0 and k["torrent"] == (20, 1000), (r, k))
    r, k = R(k, {"*": {"torrent": 25, "blocked": 13}, "10.9.0.0/24": {"mech": 6}}, 1005)
    check("… and the next report reads as usual (5 in 5 s)", r["torrent"] == 3600, r)
    r, k = R(None, {}, 1000)
    check("nothing reported: zeros, nothing kept", r == {"torrent": 0, "blocked": 0, "mech": 0} and k == {}, (r, k))
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [1] ran to the end", False, "%s: %s" % (type(e).__name__, e))

try:
    SECTION[0] = "[2]"
    print("[2] the sync: a noded start, through the real history writer")
    stats = os.path.join(TMP, "stats")
    os.makedirs(stats)
    P.Handler.deps = {"stats_dir": stats, "node_snaps": {}, "live_samples": {}}
    clock = [int(time.time()) // 3600 * 3600 - 7200]          # two hours back, on a bucket edge: every write lands in ring0
    real_time = time.time
    time.time = lambda: clock[0]

    def report(t, blk):
        clock[0] = t
        P.Handler._node_sync_history(None, "n1", {"id": "n1"}, {"n1": {"id": "n1"}},
                                     {"interfaces": {}, "smartroute": {"block": blk}})
    try:
        t0 = clock[0]                                         # one report per 15-s bucket: each bucket holds its rate as is
        report(t0, {"*": {"torrent": 40000, "blocked": 100}, "10.9.0.0/24": {"mech": 50}})
        report(t0 + 15, {"*": {"torrent": 40010, "blocked": 101}, "10.9.0.0/24": {"mech": 50}})
        # noded stopped for an hour while its counters kept counting; its first report after the start comes before its
        # first P2P pass: no torrent
        report(t0 + 3615, {"*": {"blocked": 3101}, "10.9.0.0/24": {"mech": 1850}})
        report(t0 + 3630, {"*": {"torrent": 43010, "blocked": 3102}, "10.9.0.0/24": {"mech": 1850}})
        report(t0 + 3645, {"*": {"torrent": 43011, "blocked": 3102}, "10.9.0.0/24": {"mech": 1850}})
    finally:
        time.time = real_time
    d = P.hrrd_read(P.block_rrd_path(stats, "n1"), ring=0, want=250) or {}
    tor = dict(zip(d.get("t") or [], d.get("rx") or []))
    blk = dict(zip(d.get("t") or [], d.get("tx") or []))
    mech = dict(zip(d.get("t") or [], d.get("arx") or []))
    check("the ring holds the five reports", len(tor) == 5, tor)
    check("no burst when the node comes back: no 15-s bucket above 10,000 torrents an hour", max(tor.values() or [0]) < 10000, tor)
    check("before the stop: 10 in 15 s = 2400 an hour", tor.get(t0 + 15) == 2400, tor)
    check("the report without `torrent`: 0 torrents", tor.get(t0 + 3615) == 0, tor)
    check("torrent's rise over the stop spread over it (3000 in 3615 s = %d an hour)" % int(3000 * 3600 / 3615),
          tor.get(t0 + 3630) == int(3000 * 3600 / 3615), tor)
    check("…as `blocked`'s is, which the first report carried (3000 in 3600 s = 3000 an hour)", blk.get(t0 + 3615) == 3000, blk)
    check("…and `mech`'s (1800 in 3600 s = 1800 an hour)", mech.get(t0 + 3615) == 1800, mech)
    check("after it, as before (1 in 15 s = 240 an hour)", tor.get(t0 + 3645) == 240, tor)
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [2] ran to the end", False, "%s: %s" % (type(e).__name__, e))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
