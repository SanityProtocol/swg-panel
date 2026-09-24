#!/usr/bin/env python3
"""Custom windows on the Overview's charts (TRAFFIC-HISTORY-PLAN P3, §8) — the resolver and the endpoints behind it.

Driven with explicit time over rings written by hand, so every figure is computed from the samples fed in. The rules:

  [1] named ranges     answer byte-identically to 4c700c7 (the build before P3) on every ranged endpoint — a small fleet
                       that never opens Custom sees nothing change
  [2] RANGE_SPEC       is never extended: the rings' GC age (_rings_dead_after) is the same before and after any custom call
  [3] the resolver     whole panel days, from's midnight to the midnight after to (capped at now); the finest ring that
                       still reaches back; a window older than the charts keep is refused, typed, naming the first day
  [4] the window       a window that ended in the past holds no bucket after it; a day 25 days back reads its 12 buckets,
                       never 0, and its volume (Σ mean × step) equals the traffic fed in
  [6] presence         a custom window's bars are the server's own (hours / quarter-days / days); a peer seen only before
                       the window is not counted in it
  [7] offenders        the Protection bubble's "who" holds only offenders seen inside the window

Run: python3 tests/chart_range_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     a  a custom window adds its entry to RANGE_SPEC
     b  the until filter is gone (a window that ended keeps today's buckets)
     c  every custom window reads the coarsest ring
     d  a window older than the charts keep is answered from what is left, not refused
     f  presence ignores the custom window's end
     g  a past window names offenders first seen after it ended
     i  the resolver strips the range the endpoints then index RANGE_SPEC by (a 500)
     j  offenders are dropped before a custom window's reach
     h  a named reply carries the axis too
  SWG_BASE_REV (default 4c700c7) is the build the named replies are compared with.
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.path.join(ROOT, "swg-panel-server")
BASE = os.environ.get("SWG_BASE_REV") or "4c700c7"
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "a": ([("    since, until = _ld_midnight(f), min(int(now), _ld_midnight(_ld_next(t)))\n",
            "    since, until = _ld_midnight(f), min(int(now), _ld_midnight(_ld_next(t)))\n    RANGE_SPEC[\"custom\"] = (3, 400, int(now - since))\n")],
          "never extended"),
    "b": ([("    if until is not None:                                    # a custom window that ended in the past (resolve_range)\n        rows = [r for r in rows if _bucket_epoch(r[0], step) < until]",
            "    if False:\n        rows = [r for r in rows if _bucket_epoch(r[0], step) < until]")], "holds no bucket after it"),
    "c": ([("    ring = next((i for i, (st, n) in enumerate(HRRD_RINGS) if since >= now - (n - 1) * st), len(HRRD_RINGS) - 1)",
            "    ring = len(HRRD_RINGS) - 1")], "finest ring"),
    "d": ([("    if f < first:\n        raise ValueError(", "    if False:\n        raise ValueError(")], "older than the charts keep"),
    "f": ([("            for ep, bm in pres_scan(pres_path(stats_dir, nid), ring, since=floor, until=hi):",
            "            for ep, bm in pres_scan(pres_path(stats_dir, nid), ring, since=floor):"),
           ("                if ep >= lo and (hi is None or ep < hi):    # range totals use the FULL window …",
            "                if ep >= lo:                                # range totals use the FULL window …")], "seen only after"),
    "g": ([("        _in = lambda first, last: last >= _t0 and first < _t1", "        _in = lambda first, last: last >= _t0")],
          "who"),
    "i": ([("    rng = (qs.get(\"range\") or [dflt])[0]                    # read exactly", "    rng = g(\"range\") or dflt                    # read exactly")],
          "malformed range"),
    "j": ([("OFFENDER_TTL = RANGE_CUSTOM_DAYS * 86400 + 3600", "OFFENDER_TTL = 30 * 86400 + 3600")], "kept as long"),
    "h": ([("        if axis:                                             # custom only: a named reply stays byte-identical\n            data[\"axis\"] = axis",
            "        data[\"axis\"] = axis or {}")], "byte-identical"),
}

TMP = tempfile.mkdtemp(prefix="chartrange-")


def load(name, path):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    ld.exec_module(m)
    return m


src = open(PANEL, encoding="utf-8").read()
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    for old, new in PLANTS[PLANT][0]:
        assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:90]
        src = src.replace(old, new, 1)
open(os.path.join(TMP, "panel.py"), "w", encoding="utf-8").write(src)
base_src = subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-panel-server"], capture_output=True, text=True, check=True).stdout
open(os.path.join(TMP, "base.py"), "w", encoding="utf-8").write(base_src)

os.environ["TZ"] = "Europe/Moscow"
time.tzset()
P = load("swgpanel_p3", os.path.join(TMP, "panel.py"))
H = load("swgpanel_base", os.path.join(TMP, "base.py"))

# ── the fixture: two nodes, 33 days of health rings, three days of the rest ──────────────────────────────────────────
NOW = P._ld_midnight(20260924) + 14 * 3600 + 37 * 60 + 20      # 24 Sep 14:37:20 Moscow
_real_time = time.time
time.time = lambda: NOW
stats = os.path.join(TMP, "stats"); os.makedirs(stats)
nodes_path = os.path.join(TMP, "nodes.json"); roster_path = os.path.join(TMP, "users.json")
json.dump({"n1": {"name": "one", "links": {"n2": {}}, "exits": [{"id": "x1", "device": "tun-x"}]},
           "n2": {"name": "two", "links": {"n1": {}}}}, open(nodes_path, "w"))
PEERS = {"p%d" % i: {"id": "p%d" % i, "user_id": "u1", "pubkey": "K%d" % i, "targets": [{"node": "n1", "iface": "awg0", "ip": "10.0.0.%d" % i}]}
         for i in range(1, 4)}
json.dump({"version": 1, "users": {"u1": {"id": "u1", "name": "one"}}, "peers": PEERS}, open(roster_path, "w"))

rate = lambda day: 1000 * (day % 31 + 1)                        # B/s — steady for a whole local day, so any bucket's mean is it
M = lambda day: [10, 20, 30, rate(day), rate(day) // 2, 0, 0, 0, 0, 0, 0, 1, 3, 0, 0]
t0 = NOW - 34 * 86400
t = t0 - t0 % 300
while t <= NOW:
    dd = P._ld_day(t)[0]
    P.hrrd_update(os.path.join(stats, "health-n1.rrd"), t, M(dd))
    if t >= NOW - 3 * 86400:
        for f in ("cat-n1-video.rrd", "turn-n1-main.rrd", "exitd-n1-tun-x.rrd", "block-n1.rrd", "mesh-n1-n2.rrd",
                  "peer-n1-" + P.hashlib.sha256(b"K1").hexdigest()[:16] + ".rrd", "iface-n1-awg0.rrd"):
            P.hrrd_update(os.path.join(stats, f), t, M(dd))
    t += 300
bits = P.pres_bits_for(["K1", "K2", "K3"], stats)
P.pres_feed(P.pres_path(stats, "n1"), NOW - 5 * 86400, [bits["K2"]], P.pres_width(3))   # K2: only five days back
P.pres_feed(P.pres_path(stats, "n1"), NOW - 600, [bits["K3"]], P.pres_width(3))         # K3: today
offenders = {"scan": {"10.0.0.1": [NOW - 6 * 86400, NOW - 6 * 86400 + 60], "10.0.0.2": [NOW - 3600, NOW - 60],
                      "10.0.0.3": [NOW - 25 * 86400, NOW - 86400],     # .3: a span straddling the window below
                      "10.0.0.4": [NOW - 2 * 86400, NOW - 3600]}, "torrent": {}}     # .4: first seen after it


def deps():
    return {"fleet": {}, "roster_path": roster_path, "nodes_path": nodes_path, "stats_dir": stats, "panel_settings": {},
            "panel_settings_path": os.path.join(TMP, "ps.json"), "_offenders": offenders}


for mod in (P, H):
    mod.Handler.deps = deps()


def call(mod, url):
    path, _, q = url.partition("?")
    qs = {}
    for kv in filter(None, q.split("&")):
        k, _, v = kv.partition("=")
        qs.setdefault(k, []).append(v)
    return mod.api("GET", path, qs, None, deps())


# ── [1] named ranges answer byte-identically ─────────────────────────────────────────────────────────────────────────
print("[1] named ranges answer byte-identically to %s" % BASE)
urls = []
for r in ("live", "hour", "day", "week", "month"):
    urls += ["/api/node-history?node=n1&range=" + r, "/api/mesh-history?range=" + r, "/api/category-history?range=" + r,
             "/api/turn-history?range=" + r, "/api/exit-history?range=" + r, "/api/block-stats?range=" + r,
"/api/iface-series?node=n1&iface=awg0&range=" + r,
             "/api/presence?range=" + r + "&blocks=24&step=3600"]
urls += ["/api/node-history?node=n1", "/api/presence?range=day"]
diff = [u for u in urls if json.dumps(call(P, u), sort_keys=True) != json.dumps(call(H, u), sort_keys=True)]
check("every named range on every ranged endpoint answers byte-identically (%d replies)" % len(urls), not diff, diff[:3])
st, rsp = call(P, "/api/node-history?node=n1&range=year")
check("…and a range that is not one is still a 400 (its sentence now names custom too)", st == 400 and "custom" in rsp.get("error", ""), rsp)

# ── [2] RANGE_SPEC is never extended ────────────────────────────────────────────────────────────────────────────────
print("[2] RANGE_SPEC")
dead0 = P._rings_dead_after()
for w in ("2026-09-24", "2026-09-01", "2026-08-23"):
    call(P, "/api/node-history?node=n1&range=custom&from=%s&to=2026-09-24" % w)
check("RANGE_SPEC is never extended — the rings' GC age is the same after custom windows",
      P.RANGE_SPEC == H.RANGE_SPEC and P._rings_dead_after() == dead0 == H._rings_dead_after(), sorted(P.RANGE_SPEC))

# ── [3] the resolver ────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] the resolver")
rq = lambda f, t: {"range": ["custom"], "from": [f], "to": [t]}
ring, want, since, until, axis = P.resolve_range(rq("2026-09-24", "2026-09-30"))
check("a window is whole panel days: from's midnight to now (a `to` after today is today)",
      since == P._ld_midnight(20260924) and until == NOW and axis["rangeKey"] == "custom:20260924-20260924", axis)
steps = [P.resolve_range(rq(f, "2026-09-24"))[4]["step"] for f in ("2026-09-24", "2026-09-23", "2026-09-17", "2026-08-23")]
check("the finest ring that still reaches back: today 5 min, two days 30 min, eight days and more 2 h", steps == [300, 1800, 7200, 7200], steps)
try:
    P.resolve_range(rq("2026-08-22", "2026-09-01")); refused = None
except ValueError as e:
    refused = e.args[0]
check("a window older than the charts keep is refused, typed, naming the first day it can start on",
      isinstance(refused, dict) and refused.get("error_vars", {}).get("v2") == "2026-08-23", refused)
st, rsp = call(P, "/api/category-history?range=custom&from=2026-09-10&to=2026-09-01")
check("…and a window whose start is after its end is a 400", st == 400 and rsp.get("code") == "bad_request", rsp)

# ── [4] the window ──────────────────────────────────────────────────────────────────────────────────────────────────
print("[4] the window")
_, rsp = call(P, "/api/node-history?node=n1&range=custom&from=2026-09-10&to=2026-09-23")
d = rsp["data"]
check("a window that ended in the past holds no bucket after it", d["t"] and max(d["t"]) < P._ld_midnight(20260924)
      and min(d["t"]) >= P._ld_midnight(20260910), (d["t"][:1], d["t"][-1:]))
_, rsp = call(P, "/api/node-history?node=n1&range=custom&from=2026-08-30&to=2026-08-30")
d = rsp["data"]
vol = sum(d["rx"]) * d["axis"]["step"]
check("a day 25 days back reads its 12 buckets, never 0, and Σ mean × step equals the day's traffic",
      len(d["t"]) == 12 and vol == rate(20260830) * 86400, (len(d["t"]), vol, rate(20260830) * 86400))
_, rsp = call(P, "/api/category-history?range=custom&from=2026-09-23&to=2026-09-23")
c = (rsp["data"]["cats"] or [{}])[0]
check("a custom volume is the server's (category: one whole day at its ring's step)",
      c.get("up") == rate(20260923) * 86400 and rsp["data"]["axis"]["step"] == 1800, (c, rsp["data"].get("axis")))

# ── [6] presence ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[6] presence")
_, rsp = call(P, "/api/presence?range=custom&from=2026-09-23&to=2026-09-24&blocks=30&step=30")
d = rsp["data"]
check("a custom window's bars are the server's own: hours for two days (the caller's blocks/step ignored)",
      d["step"] == 3600 and len(d["blocks"]) == 39 and d["start"] == P._ld_midnight(20260923), (d["step"], len(d["blocks"]), d["start"]))
check("a peer seen only before the window is not counted in it (K1 moved bytes in it, K3 was online; K2 only earlier)",
      d["total"]["peers"] == 2, d["total"])
_, rsp = call(P, "/api/presence?range=custom&from=2026-09-01&to=2026-09-20")
d = rsp["data"]
check("…days for a long window; a peer seen only after it is not counted", d["step"] == 86400 and len(d["blocks"]) == 20
      and d["total"]["peers"] == 1, (d["step"], len(d["blocks"]), d["total"]))

# ── [7] offenders ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[7] the Protection bubble's who")
_, rsp = call(P, "/api/block-stats?range=custom&from=2026-09-17&to=2026-09-19")
check("the who holds the offenders whose span overlaps the window — like a named range — and none first seen after it",
      rsp["data"]["scan"] == 2 and [r["n"] for r in rsp["data"]["who"].get("scan", [])] == [2], (rsp["data"]["scan"], rsp["data"]["who"]))

_, rsp = call(P, "/api/block-stats?range=day")
check("…while a rolling window still names every offender last seen inside it", rsp["data"]["scan"] == 3, rsp["data"]["scan"])
check("offenders are kept as long as a custom window reaches back", P.OFFENDER_TTL >= P.RANGE_CUSTOM_DAYS * 86400, P.OFFENDER_TTL)
try:
    st, rsp = call(P, "/api/presence?range=day ")
except Exception as e:                                          # the request handler answers an exception with a 500
    st, rsp = 500, repr(e)
check("a malformed range is a 400, never a 500 — the resolver reads it exactly as the endpoint does", st == 400, (st, rsp))

time.time = _real_time
shutil.rmtree(TMP, ignore_errors=True)
if PLANT:
    want = PLANTS[PLANT][1]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
