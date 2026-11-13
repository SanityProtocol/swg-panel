#!/usr/bin/env python3
"""Self-test — volume limits on the panel (docs/LIMITS-PLAN.md §3.5–§3.6, "limits-l4 design"; card limits-l4).

  [1] volume_clean: {d, u} or {c} in bytes (10^8..10^15) with a period (d w m n) and "at" (cut | slow, cut by default);
      {} / None = none; a missing period, `c` beside `d`, an unknown key, a bool, an amount out of range are refused.
  [2] Periods, in the zone the ledger counts days in: a day, a week from MONDAY, a calendar month (December → January),
      and "n" with no start (everything the ledger holds).
  [3] The tick over a ledger with known rows: used = C now − C at the end of the day before the period began; a device's
      own over its slots, a user's over every slot they own (a closed one too), a group's ONE budget over all its members;
      d is what the node sent (C_tx), u what it received (C_rx), c both; every level applies, "cut" beats "slow".
  [4] The effects: a cut id is expired (is_expired, access_cut → desired_for_node drops the device), the WDTT and csqtt
      builders deactivate it (R9), a slow id gets 1 Mbit/s on the speed wire — never above a lower limit already there —
      even when no record carries a speed limit; an event when a record reaches its limit and when it is lifted.
  [5] Nothing with no volume: no state, no wire, no usage file; the ledger off → nothing is cut.
  [6] usage.json (0640): the users' rows (a group's for its members, the tighter one), the ids cut off; swg-sub's own
      is_expired honours a cut and its page carries used / left; /api/state's `vol` only when not empty (source).
  [7] Review limits-l4: the base waits for the ledger to reach the period (no yesterday charged to today), an unreadable
      history or roster keeps the last verdicts, a restart logs nothing again, a slowed person shares ONE 1 Mbit/s pool, a cut
      alone builds no wire, a stale usage.json goes, a {d, u} row by the direction that tripped, a slow written at once, the
      return day (several limits: the last to reset), swg-sub's date-passed and device pages, /api/volume for a drafted
      period, a transferred group keeps its volume.

Run: python3 tests/limits_volume_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     week       a week starts on Sunday
     base       the period's base is ignored (lifetime used for every period)
     groupone   a group's budget counts its first member only
     dirswap    a download limit is measured on what the node received
     cutexp     is_expired ignores a volume cut
     keyless    the WDTT / csqtt builders ignore a volume cut
     slowwire   a slowed device gets no 1 Mbit/s entry when no speed limit exists
     slowup     slow replaces a lower limit with 1 Mbit/s
     subcut     swg-sub's is_expired ignores usage.json's cut
     novol      /api/state carries `vol` always
     openday    the period's base read before the ledger has reached its first day (yesterday charged to today)
     strict     an unreadable history directory reads as "no row" (a whole lifetime counted)
     rostergone an unreadable roster lifts every cut
     restartev  a restart logs every limit already reached again
     slowpool   a slowed person gets 1 Mbit/s per device (no shared pool)
     cutwire    a cut alone builds the speed wire
     staleusage a usage.json the last process left stays when nothing is limited
     updir      a {d, u} row reports download even when upload is the one at its limit
     slowlate   a slow (no change to who is cut) waits for the 5-minute throttle
     datepassed a page whose date has passed still promises access back on the reset
     devback    a device cut by its own limit carries no return day
     apiperiod  /api/volume ignores the period asked for
     grouptransfer  a transferred group arrives without its volume limit
"""
import array, importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time

os.environ["TZ"] = "UTC"
time.tzset()
os.environ["SWG_NO_REEXEC"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def _show(d):
    try:
        return json.dumps(d, default=str)[:500]
    except (TypeError, ValueError):
        return repr(d)[:500]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + _show(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # name: (file, anchor, replacement)
    "week": ("swg-panel-server", "        a = d - _ldt.timedelta(days=d.weekday())", "        a = d - _ldt.timedelta(days=(d.weekday() + 1) % 7)"),
    "base": ("swg-panel-server", "    brx, btx = base if base else ((), ())", "    brx, btx = ((), ())"),
    "groupone": ("swg-panel-server", "[n for m in members for n in snap[3].get(m, ())]", "[n for m in members[:1] for n in snap[3].get(m, ())]"),
    "openday": ("swg-panel-server", "    if lday < first:\n        return \"none\"\n", ""),
    "strict": ("swg-panel-server", "            if strict:\n                raise\n            return None", "            return None"),
    "rostergone": ("swg-panel-server", "    if roster is None:\n        raise ValueError(\"the roster could not be read — the last verdicts stand\")", "    roster = roster or {}"),
    "restartev": ("swg-panel-server", "    if _VOL_HIT is not None and hit != _VOL_HIT:", "    _VOL_HIT = _VOL_HIT or {}\n    if hit != _VOL_HIT:"),
    "slowpool": ("swg-panel-server", "lim, pool, src = VOL_SLOW, spool, \"s\"", "lim, pool, src = VOL_SLOW, \"\", \"s\""),
    "staleusage": ("swg-panel-server", "    if old is not None and (text == old or", "    if (text == (old or \"\") or"),
    "updir": ("swg-panel-server", "            dirn = max((k for k in (\"d\", \"u\") if k in v), key=lambda k: u[\"used\"][k] / v[k])", "            dirn = \"d\" if \"d\" in v else \"u\""),
    "slowlate": ("swg-panel-server", "    key = json.dumps([back, {m: [r[\"limit\"], r[\"dir\"], r[\"period\"], r[\"day\"], r[\"state\"]] for m, r in body.items()}],", "    key = json.dumps([back, {}],"),
    "datepassed": ("swg-sub", "        if vol and _date_passed(user, nowv):", "        if False:"),
    "devback": ("swg-sub", "**(_vol_back(pid) if _exp and not _date_passed(p, nowv) else {})})", "})"),
    "apiperiod": ("swg-panel-server", "        per = per or (cur[\"vol\"][\"period\"] if cur else \"m\")", "        per = cur[\"vol\"][\"period\"] if cur else \"m\""),
    "grouptransfer": ("swg-panel-server", "            if _gv:                                   # and its volume limit (§3.5; review limits-l4 F5)\n                groups[gid][\"volume\"] = _gv\n", ""),
    "dirswap": ("swg-panel-server", '("d" in v and dn >= v["d"])', '("d" in v and up >= v["d"])'),
    "cutexp": ("swg-panel-server", '    if _VOL_STATE and isinstance(rec, dict) and _VOL_STATE.get(rec.get("id")) == "cut":\n        return True\n', ""),
    "keyless": ("swg-panel-server", 'return bool(_VOL_STATE) and "cut" in (', 'return False and "cut" in ('),
    "slowwire": ("swg-panel-server", "    if not li[\"any\"] and not slowing:\n        return []", "    if not li[\"any\"]:\n        return []"),
    "cutwire": ("swg-panel-server", "    slowing = bool(vs) and \"slow\" in vs.values()", "    slowing = bool(vs)"),
    "slowup": ("swg-panel-server", "if slow and (not lim or _lim_key(VOL_SLOW) < _lim_key(lim)):", "if slow:"),
    "subcut": ("swg-sub", '    if _READ_CACHE["cut"] and isinstance(rec, dict) and rec.get("id") in _READ_CACHE["cut"]:\n        return True\n', ""),
    "novol": ("swg-panel-server", '**({"vol": dict(_VOL_STATE)} if _VOL_STATE else {}),', '"vol": dict(_VOL_STATE),'),
}
TMP = tempfile.mkdtemp(prefix="swg-volume-")


def src_of(f):
    s = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if PLANT:
        pf, a, b = PLANTS[PLANT]
        if pf == f:
            assert s.count(a) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
            s = s.replace(a, b, 1)
    return s


def load(f, name):
    path = os.path.join(TMP, f)
    open(path, "w", encoding="utf-8").write(src_of(f))
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


try:
    P = load("swg-panel-server", "swgpanel_volume")
    S = load("swg-sub", "swgsub_volume")
    GB = 10 ** 9

    print("[1] volume_clean")
    vc = lambda r: P.volume_clean(r)
    check("download + upload, a month, cut by default", vc({"d": 10 * GB, "u": 2 * GB, "period": "m"})[0] == {"d": 10 * GB, "u": 2 * GB, "period": "m", "at": "cut"})
    check("combined, a week, slow", vc({"c": 5 * GB, "period": "w", "at": "slow"})[0] == {"c": 5 * GB, "period": "w", "at": "slow"})
    check("{} and None are none", vc({}) == ({}, None) and vc(None) == ({}, None))
    bad = [{"d": GB}, {"c": GB, "d": GB, "period": "m"}, {"d": GB, "period": "y"}, {"d": True, "period": "m"}, {"d": 10, "period": "m"},
           {"d": 2 * 10 ** 15, "period": "m"}, {"d": GB, "period": "m", "x": 1}, {"d": GB, "period": "m", "at": "drop"}, "5GB", {"period": "m"}]
    check("refused: no period, c beside d, a bad period, a bool, too small, too big, an unknown key, a bad at, not a dict, no amount",
          all(vc(b)[1] and vc(b)[0] == {} for b in bad), [b for b in bad if not vc(b)[1]])
    check("a fractional amount is whole bytes", vc({"d": 1.5 * GB, "period": "d"})[0]["d"] == 1500000000)

    print("[2] periods (UTC here)")
    T = lambda y, mo, d, h=12: int(time.mktime((y, mo, d, h, 0, 0, 0, 0, -1)))
    check("a day", P._vol_period("d", T(2026, 11, 13)) == (20261113, 20261114))
    check("a week starts on Monday (Fri 13 Nov → Mon 9 Nov)", P._vol_period("w", T(2026, 11, 13)) == (20261109, 20261116), P._vol_period("w", T(2026, 11, 13)))
    check("…a Monday is its own week's first day", P._vol_period("w", T(2026, 11, 9))[0] == 20261109)
    check("…a Sunday is the end of the week before", P._vol_period("w", T(2026, 11, 15))[0] == 20261109)
    check("a month, and December into January", P._vol_period("m", T(2026, 11, 13)) == (20261101, 20261201)
          and P._vol_period("m", T(2026, 12, 31)) == (20261201, 20270101))
    check("never resets: no start", P._vol_period("n", T(2026, 11, 13)) == (None, None))

    print("[3] the tick")
    NOW = T(2026, 11, 13)
    # slots: 0 pa (anna's phone), 1 pa2 (anna's laptop), 2 pa-old (anna's, closed), 3 pb (boris), 4 pc (carol), 5 pd (dora)
    SLOTS = [{"pid": "pa", "owner": "ua"}, {"pid": "pa2", "owner": "ua"}, {"pid": "pz", "owner": "ua", "until": 1},
             {"pid": "pb", "owner": "ub"}, {"pid": "pc", "owner": "uc"}, {"pid": "pd", "owner": "ud"}]
    C_RX = [1 * GB, 1 * GB, 1 * GB, 1 * GB, 0, 0]          # what the node received (each device's upload), now
    C_TX = [9 * GB, 4 * GB, 2 * GB, 6 * GB, 7 * GB, 1 * GB]  # what it sent (each device's download), now
    BASE = {20261031: ([0] * 6, [1 * GB, 1 * GB, 1 * GB, 1 * GB, 1 * GB, 0]),     # end of the day before November
            20261108: ([0] * 6, [8 * GB, 3 * GB, 2 * GB, 5 * GB, 6 * GB, 1 * GB])}   # end of the day before this week
    asked = []

    def row(d, strict=False):
        asked.append(d)
        k = max((x for x in BASE if x <= d), default=None)
        return (k, array.array("Q", BASE[k][0]), array.array("Q", BASE[k][1])) if k else None
    L = P.LEDGER
    L.on, L.slots, L.C_rx, L.C_tx = True, SLOTS, array.array("Q", C_RX), array.array("Q", C_TX)
    L.day = 20261113                                   # the day the ledger is in: today (a sync since midnight)
    L._row_at_or_before = row
    EV = []
    P.ev_append = lambda rp, kind, ident, verb, name, *a, **k: EV.append((kind, ident, verb))
    RP = os.path.join(TMP, "users.json")
    DEPS = {"roster_path": RP, "sub_dir": os.path.join(TMP, "subs")}
    os.makedirs(DEPS["sub_dir"])
    ROSTER = {"users": {"ua": {"id": "ua", "name": "anna"}, "ub": {"id": "ub", "name": "boris"}, "uc": {"id": "uc", "name": "carol"},
                        "ud": {"id": "ud", "name": "dora"}},
              "groups": {}, "peers": {}}
    MARK = [0]
    P.roster_view = lambda path, repair=True: (ROSTER, MARK[0])

    def tick(r):
        ROSTER.clear(); ROSTER.update(r)
        MARK[0] += 1                                   # a new roster revision
        P._VOL_BASE.clear()
        P._vol_tick(DEPS, NOW)
        return dict(P._VOL_STATE)
    usr = lambda **kw: {"ua": {"id": "ua", "name": "anna", **kw.get("ua", {})}, "ub": {"id": "ub", "name": "boris", **kw.get("ub", {})},
                         "uc": {"id": "uc", "name": "carol", **kw.get("uc", {})}, "ud": {"id": "ud", "name": "dora", **kw.get("ud", {})}}
    # anna: this month she downloaded (9-1)+(4-1)+(2-1) = 12 GB over three slots (one closed); a 12 GB month cuts her
    P._VOL_HIT = None                                  # a fresh process: its first tick
    st = tick({"users": usr(ua={"volume": {"d": 12 * GB, "period": "m"}}), "groups": {}, "peers": {}})
    check("a user's month counts every slot she owns, a closed one too (12 GB of 12 → cut)", st == {"ua": "cut"}, st)
    check("…a fresh process's first tick logs no event for a limit already reached (a restart)", EV == [], EV)
    u = P._VOL_USE.get(("user", "ua"), {})
    check("…used is C now − C at the end of the day before the month (download 12, upload 3 GB)", u.get("used") == {"d": 12 * GB, "u": 3 * GB}, u)
    check("…the period's base is read once, from the day before it began", 20261031 in asked, asked)
    check("…and it says when the month ends", u.get("until") == int(time.mktime((2026, 12, 1, 0, 0, 0, 0, 0, -1))), u.get("until"))
    st = tick({"users": usr(ua={"volume": {"d": 13 * GB, "period": "m"}}), "groups": {}, "peers": {}})
    check("…13 GB is not reached", st == {}, st)
    st = tick({"users": usr(ua={"volume": {"d": 3 * GB, "period": "w"}}), "groups": {}, "peers": {}})
    check("a week from Monday: (9-8)+(4-3)+(2-2) = 2 GB, under 3", st == {} and P._VOL_USE[("user", "ua")]["used"]["d"] == 2 * GB, P._VOL_USE.get(("user", "ua")))
    st = tick({"users": usr(ua={"volume": {"u": 3 * GB, "period": "n"}}), "groups": {}, "peers": {}})
    check("upload is what the node received; never resets counts everything (3 GB of 3 → cut)", st == {"ua": "cut"}, st)
    st = tick({"users": usr(), "groups": {}, "peers": {"pb": {"id": "pb", "user_id": "ub", "volume": {"c": 6 * GB, "period": "m", "at": "slow"}}}})
    check("a device's own over its slots, combined (5 + 1 = 6 GB of 6 → slowed)", st == {"pb": "slow"}, st)
    G = {"g1": {"name": "Family", "users": ["ub", "uc"], "volume": {"d": 11 * GB, "period": "m"}}}
    st = tick({"users": usr(), "groups": G, "peers": {}})
    check("a group is ONE budget over all its members: boris 5 + carol 6 = 11 GB of 11 → both cut, dora not", st == {"ub": "cut", "uc": "cut"}, st)
    st = tick({"users": usr(ub={"volume": {"d": 50 * GB, "period": "m", "at": "slow"}}), "groups": G,
               "peers": {"pc": {"id": "pc", "user_id": "uc", "volume": {"d": 1 * GB, "period": "m", "at": "slow"}}}})
    check("every level applies, and cut beats slow (carol: her device slowed, her group cut)", st == {"ub": "cut", "uc": "cut", "pc": "slow"}, st)
    check("…an event for each record that reached its limit", ("group", "g1", "Volume limit reached — cut off") in EV
          and ("peer", "pc", "Volume limit reached — slowed") in EV, EV)
    EV.clear()
    st = tick({"users": usr(), "groups": {}, "peers": {}})
    check("…and one when it is lifted", ("group", "g1", "Volume limit lifted") in EV and st == {}, EV)
    try:                                               # as the panel calls it: its own clock (a tick that raised cut nobody)
        P._vol_tick(DEPS)
        check("a tick on the panel's own clock runs", True)
    except Exception as e:
        check("a tick on the panel's own clock runs", False, repr(e))

    print("[4] the effects")
    R = {"users": usr(ua={"volume": {"d": 12 * GB, "period": "m"}}), "groups": {},
         "peers": {"pa": {"id": "pa", "user_id": "ua", "pubkey": "a" * 43 + "=", "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.2"}]},
                   "pb": {"id": "pb", "user_id": "ub", "pubkey": "b" * 43 + "=", "volume": {"c": 6 * GB, "period": "m", "at": "slow"},
                          "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.3"}]},
                   "pc": {"id": "pc", "user_id": "uc", "pubkey": "c" * 43 + "=", "volume": {"c": 6 * GB, "period": "m", "at": "slow"},
                          "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.4"}]},
                   "pw": {"id": "pw", "user_id": "ua", "wdtt_password": "WPW", "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
                   "pq": {"id": "pq", "user_id": "ua", "csqtt_password": "CPW", "targets": [{"node": "n1", "iface": "csqtt0", "type": "csqtt"}]}}}
    st = tick(R)
    check("(anna cut; boris's laptop slowed)", st.get("ua") == "cut" and st.get("pb") == "slow", st)
    check("a cut user is expired; a slowed device is not", P.is_expired(R["users"]["ua"], NOW) and not P.is_expired(R["peers"]["pb"], NOW))
    des = P.desired_for_node(R, "n1")
    keys = {e.get("public_key") for lst in des.values() for e in lst}
    check("desired_for_node leaves her device out, keeps boris's", ("a" * 43 + "=") not in keys and ("b" * 43 + "=") in keys, keys)
    nodes = {"n1": {"wdtt": {"wdtt1": {"listen": "0.0.0.0:56000"}}, "csqtt": {"csqtt0": {"listen": "0.0.0.0:443"}}}}
    dw = P.desired_wdtt_for_node(R, nodes, "n1").get("wdtt1", {}).get("WPW", {})
    dc = P.desired_csqtt_for_node(R, nodes, "n1").get("csqtt0", {}).get("CPW", {})
    check("WDTT and csqtt keep her password and deny it (R9)", dw.get("is_deactivated") is True and dc.get("is_deactivated") is True, [dw, dc])
    w = {tuple(e[1]): e for e in P.limits_for_node(R, "n1", des)}
    check("a slowed device gets 1 Mbit/s on the wire though no record carries a speed limit … ", w.get(("10.9.0.3/32",), [None] * 5)[4] == 1, w)
    R["peers"]["pc"]["limits"] = {"d": 1, "u": 1}
    P._VOL_STATE["pc"] = "slow"
    w = {tuple(e[1]): e for e in P.limits_for_node(R, "n1", P.desired_for_node(R, "n1"))}
    check("…and a lower limit already there stays (1 down, 1 up is tighter than 1 both ways)", w.get(("10.9.0.4/32",), [None] * 5)[2:5] == [1, 1, 0], w)

    print("[5] nothing with no volume, and the ledger off")
    st = tick({"users": usr(), "groups": {}, "peers": {k: {x: y for x, y in v.items() if x != "volume"} for k, v in R["peers"].items()}})
    check("no volume anywhere: no state, no wire for a fleet with no speed limit", st == {} and P.limits_for_node(
        {"users": usr(), "groups": {}, "peers": {"pa": R["peers"]["pa"]}}, "n1", {}) == [], st)
    check("…and no usage file", not os.path.exists(os.path.join(DEPS["sub_dir"], "usage.json")))
    L.on = False
    st = tick(R)
    check("the ledger off: nothing is cut", st == {}, st)
    L.on = True

    print("[6] usage.json and swg-sub")
    P._VOL_USAGE.update(at=0.0, body=None)
    st = tick({"users": usr(ub={"volume": {"d": 50 * GB, "period": "m"}}), "groups": G, "peers": {"pc": {"id": "pc", "user_id": "uc", "volume": {"d": 7 * GB, "period": "n"}}}})
    up = os.path.join(DEPS["sub_dir"], "usage.json")
    body = json.load(open(up)) if os.path.exists(up) else {}
    check("written 0640", os.path.exists(up) and (os.stat(up).st_mode & 0o777) == 0o640)
    check("the ids cut off (users and devices)", body.get("cut") == ["pc", "ub", "uc"], body.get("cut"))
    ub = (body.get("users") or {}).get("ub", {})
    check("boris's row is the tighter of his own (5 of 50) and his group's (11 of 11)", ub.get("limit") == 11 * GB and ub.get("used") == 11 * GB
          and ub.get("state") == "cut" and ub.get("period") == "m", ub)
    S._READ_CACHE.update(cut=frozenset(body.get("cut") or []), usage=body.get("users") or {})
    check("swg-sub's is_expired honours a cut user and a cut device", S.is_expired({"id": "ub"}, NOW) and S.is_expired({"id": "pc"}, NOW)
          and not S.is_expired({"id": "ud"}, NOW))
    ss = src_of("swg-sub")
    check("swg-sub's page carries the user's used / left", '"user": {"name": user.get("name") or "", **vol}, "peers": peers_out' in ss
          and 'return {"expired": True, "user": {"name": user.get("name") or "", **vol}, **theme}' in ss)
    sp = src_of("swg-panel-server")
    check("/api/state carries `vol` only when it is not empty", '**({"vol": dict(_VOL_STATE)} if _VOL_STATE else {}),' in sp)
    check("the first verdicts come before the listener (right after the ledger starts)",
          sp.index("    LEDGER.start(Handler.deps)\n") < sp.index("        _vol_tick(Handler.deps)\n") < sp.index("    LISTENERS.add(BIND_HOST, BIND_PORT,"))
    print("[7] review limits-l4")
    RA = {"users": usr(ua={"volume": {"d": 3 * GB, "period": "d"}}), "groups": {}, "peers": {}}
    asked.clear()
    L.day = 20261112                                   # just past midnight, no sync yet: the ledger is still in yesterday
    st = tick(RA)
    check("before the ledger reaches the period's first day nothing is used yet, and no base is read", st == {}
          and P._VOL_USE[("user", "ua")]["used"] == {"d": 0, "u": 0} and asked == [], [P._VOL_USE.get(("user", "ua")), asked])
    check("…and nothing is kept: once it has, the day before's row is read", 20261113 not in P._VOL_BASE, P._VOL_BASE)
    L.day = 20261113
    P._vol_tick(DEPS, NOW)
    check("…read then (the day before today)", 20261112 in asked, asked)

    L._row_at_or_before, keep = (lambda d, strict=False: P.TrafficLedger._row_at_or_before(L, d, strict)), L._row_at_or_before
    L._pending_rows, kdir = (lambda: {}), L.dir
    L.dir = os.path.join(TMP, "no-such-history")       # listdir fails, as on EMFILE
    P._VOL_STATE = {"ua": "cut"}
    ROSTER.update(RA); MARK[0] += 1; P._VOL_BASE.clear()
    try:
        P._vol_tick(DEPS, NOW)
        raised = False
    except Exception:
        raised = True
    check("an unreadable history directory raises: the last verdicts stand, no lifetime counted", raised and P._VOL_STATE == {"ua": "cut"}, P._VOL_STATE)
    L._row_at_or_before, L.dir = keep, kdir
    del L._pending_rows
    rv = P.roster_view
    P.roster_view = lambda path, repair=True: (None, 99)
    try:
        P._vol_tick(DEPS, NOW)
        raised = False
    except Exception:
        raised = True
    check("an unreadable roster raises: the cuts stand", raised and P._VOL_STATE == {"ua": "cut"}, P._VOL_STATE)
    P.roster_view = rv

    RS = {"users": usr(ub={"volume": {"d": 1 * GB, "period": "m", "at": "slow"}}), "groups": {},
          "peers": {"pb": {"id": "pb", "user_id": "ub", "pubkey": "b" * 43 + "=", "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.3"},
                                                                                              {"node": "n1", "iface": "wg1", "ip": "10.8.0.3"}]},
                    "pe": {"id": "pe", "user_id": "ub", "pubkey": "e" * 43 + "=", "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.5"}]}}}
    st = tick(RS)
    w = P.limits_for_node(RS, "n1", P.desired_for_node(RS, "n1"))
    pools = {e[5] for e in w}
    check("a slowed person's devices and paths share ONE 1 Mbit/s pool on the node", st == {"ub": "slow"} and len(w) == 3 and len(pools) == 1
          and next(iter(pools)).startswith("s:"), w)
    P._VOL_STATE = {"ua": "cut"}
    walked, po, dsr = [], P._peers_on, P.desired_for_node(RS, "n1")
    P._peers_on = lambda r, n: walked.append(n) or po(r, n)
    check("a cut alone builds no speed wire, and walks no peer (the device is absent from desired)",
          P.limits_for_node(RS, "n1", dsr) == [] and walked == [], walked)
    P._peers_on = po

    up = os.path.join(DEPS["sub_dir"], "usage.json")
    open(up, "w").write('{"cut":["ua"],"users":{}}')
    P._VOL_USAGE.update(at=0.0, body=None, key=None)   # a fresh process
    tick({"users": usr(), "groups": {}, "peers": {}})
    check("a usage.json the last process left goes when nothing is limited", not os.path.exists(up))
    st = tick({"users": usr(ua={"volume": {"d": 100 * GB, "u": 3 * GB, "period": "m"}}, ub={"volume": {"d": 2 * GB, "period": "d"}}), "groups": G,
               "peers": {"pc": {"id": "pc", "user_id": "uc", "volume": {"d": 1 * GB, "period": "m"}}}})
    body = json.load(open(up)) if os.path.exists(up) else {}
    ua = (body.get("users") or {}).get("ua", {})
    check("a {d, u} row reports the direction that tripped (upload 3 of 3, not download 12 of 100)", ua.get("dir") == "u" and ua.get("state") == "cut"
          and ua.get("used") == 3 * GB, ua)
    ubr = (body.get("users") or {}).get("ub", {})
    check("cut by its day (back tomorrow) and its group's month: access returns on the 1st, the last to reset", ubr.get("state") == "cut"
          and ubr.get("day") == 20261201 and (body.get("back") or {}).get("ub") == 20261201, [ubr, body.get("back")])
    check("…a device cut by its own month: its return day", (body.get("back") or {}).get("pc") == 20261201, body.get("back"))
    for at, upl in (("cut", 4), ("slow", 3)):          # anna under her limit, then slowed: who is cut does not change
        tick({"users": usr(ua={"volume": {"d": 100 * GB, "u": upl * GB, "period": "m", "at": at}}, ub={"volume": {"d": 2 * GB, "period": "d"}}),
              "groups": G, "peers": {"pc": {"id": "pc", "user_id": "uc", "volume": {"d": 1 * GB, "period": "m"}}}})
    body = json.load(open(up)) if os.path.exists(up) else {}
    check("a row turning slow is written at once, not after the 5-minute throttle", ((body.get("users") or {}).get("ua") or {}).get("state") == "slow", body.get("users"))

    S._READ_CACHE.update(cut=frozenset(["ua", "pc"]), back={"ua": 20261201, "pc": 20261201}, usage={"ua": {"used": 3, "limit": 3, "dir": "u", "period": "m", "day": 20261201, "state": "cut"}})
    class St:
        sub_dir = TMP
        def enabled(self):
            return True
        def subscriptions(self):
            return {}
    S._shared_read = lambda st: ({"users": {"ua": {"id": "ua", "name": "anna", "expiry": NOW - 60}},
                                   "peers": {}}, {}, {"tok": {"enabled": True}}, {})
    S.token_lookup_rec = lambda users, tok: ("ua", users["tok"]) if tok == "tok" else None
    S.time.time = lambda: NOW
    try:
        d = S.read_data(St(), "tok")
    except Exception as e:
        d = {"err": repr(e)}
    check("swg-sub: a user whose date has passed too is plain EXPIRED, never 'access returns'", (d or {}).get("expired") is True
          and (((d or {}).get("user") or {}).get("volume") or {}).get("state") == "", d)
    S.time.time = time.time
    ss = src_of("swg-sub")
    check("swg-sub: a device cut by its own limit carries the day it returns", "**(_vol_back(pid) if _exp and not _date_passed(p, nowv) else {})})" in ss
          and S._vol_back("pc") == {"vol_back": 20261201} and S._vol_back("zz") == {})

    P._VOL_USE.clear()
    try:
        r = P.api("GET", "/api/volume", {"kind": ["user"], "id": ["ua"], "period": ["w"]}, {},
                  {"fleet": {}, "roster_path": RP, "nodes_path": os.path.join(TMP, "nodes.json")})
    except Exception as e:
        r = (0, {"err": repr(e)})
    dd = (r[1] or {}).get("data") or {}
    check("/api/volume: what a record without a limit used in the period asked (the week: 2 GB down)", r[0] == 200 and dd.get("period") == "w"
          and dd.get("used", {}).get("d") == 2 * GB and dd.get("day") == 20261116, r)
    sp = src_of("swg-panel-server")
    check("a transferred group keeps its volume limit", '                groups[gid]["volume"] = _gv\n' in sp
          and '"volume": volume_clean(g.get("volume"))[0]})' in sp)
    check("the doors wake the tick when a verdict's input changed", sp.count("_VOL_WAKE.set()") == 3 and "_VOL_WAKE.wait(VOL_TICK_S)" in sp)
finally:
    shutil.rmtree(TMP, True)

print("\n%s — %d failure(s)" % ("FAIL" if FAILS else "PASS", len(FAILS)))
if PLANT:
    print("PLANT %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
