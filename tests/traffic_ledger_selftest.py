#!/usr/bin/env python3
"""The per-peer traffic ledger (TRAFFIC-HISTORY-PLAN P1) — its rules, driven with explicit time.

Every number here is computed by hand from the readings fed in, and every rule is broken on purpose by a plant that
must turn its own check red. The rules (plan §2.3, §4, §5):

  [1] the delta rule   an opening balance only for a pid never seen, credited to no bucket; either direction dropping
                       is a restart credited as clamp(cur); the clamp floors elapsed at 5 s; a clock behind the newest
                       reading holds ingest, and the backlog is credited in full once it is right (monotonic elapsed)
  [2] slots            a known peer's new record is a zero-credit baseline; an owner change — a metadata edit or a
                       reassignment by rekey — closes the old slot, which keeps everything before; a deleted peer's
                       slot closes; a node that comes back is a baseline, never a second opening
  [3] the map          the same password on two instances credits each its own peer; two peers claiming one counter
                       credit neither; an empty pubkey and a mesh link's key never resolve; csqtt's up is rx
  [4] absent ≠ zero    a down interface, a dropped interface key, `passwords: {}` and an unreadable value are no
                       observation — never a zero, never a reset
  [5] durability       a crash loses nothing and doubles nothing; base.bin is never written past a failed index.json;
                       a corrupt base.bin falls back to its previous generation, then to the newest closed day, and
                       nothing opens twice; index.json recovers from its backup, and with none the ledger stays off
  [6] days             a day's row is C as it stood at midnight; a DST fall-back day has 25 hourly buckets that sum
                       to its total; bucket ids never go backwards; missed days close flat at startup
  [7] queries          total(A..B) = C(end of B) − C(end of A−1); by user it sums closed slots; a series sums to it
  [8] files            a torn tail is cut before the next append; a bucket at another resolution is dropped and
                       counted, never blocking the day rows behind it
  [9] the hook         a ledger that raises never fails the sync, is counted, and costs it none of its rings (V33)

Run: python3 tests/traffic_ledger_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     a  an opening balance is also credited to the current bucket
     b  only rx dropping counts as a restart
     c  the clamp's elapsed floor is gone
     d  the clock gate is gone
     e  the clamp measures elapsed on the wall clock, not the monotonic one
     f  a known peer's new record gets an opening balance
     g  an owner change does not open a new slot
     h  records of deployments that are gone are not pruned
     i  two peers claiming one counter: the first one wins
     j  keyless targets are resolved by pubkey
     k  base.bin is written after a failed index.json
     l  the day's row is taken after the first reading past midnight
     m  bucket ids may go backwards
     n  base.bin.prev is not read when base.bin is corrupt
     o  an unreadable counter reads as zero
     p  a torn tail is not cut before an append
     q  with both base generations lost, C is not taken from the newest closed day
     r  index.json is read without its backups
     s  an unreadable index.json with no good backup starts a fresh, empty ledger
     t  the ingest hook runs without its own guard
     u  base.bin is written before the closed day's row
     v  a zone change mid-day re-counts the rest of the day from the new zone's midnight
     w  a failed write is retried at once, on every sync
     x  a graceful shutdown leaves the open bucket unwritten
     y  a long series reads every day's fine file
     (z retired: once the pause moved into requeue(), an empty pass returning None arms nothing — its check stays)
     A  a requeued write is not retried unless something else happens
     B  at 1-day resolution a short series leaves today out
     C  readers ignore a closed day whose row is still pending
     D  a resolution changed to 1 day mid-day: today's whole-day point repeats what the fine file drew
     E  a bucket split by a restart is drawn as two points on one timestamp
     F  closed buckets still waiting for their write are left out of the series
     G  day rows are indexed without their checksums (a damaged row: totals skip it, the series reads it)
     H  the writer is woken on every sync before anything was observed
     I  a day kept in its old frame after a zone change records the new zone's offset
"""
import calendar, importlib.machinery, importlib.util, json, os, shutil, stat, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # name: ([(anchor, replacement), …], the check it must redden)
    "a": ([("                self.recs[key] = (rx, tx, now, mono)                # a node transferred in)\n                self.prompt = True\n                return\n",
            "                self.recs[key] = (rx, tx, now, mono)                # a node transferred in)\n                self.prompt = True\n                self.fine[self.open[pid]] = [rx, tx]\n                return\n")],
          "credited to no bucket"),
    "b": ([("        reset = rx < lrx or tx < ltx ", "        reset = rx < lrx ")], "tx dropping alone"),
    "c": ([("        cap = int(LEDGER_MAX_BPS * max(el, LEDGER_FLOOR_S))", "        cap = int(LEDGER_MAX_BPS * el)")], "floors elapsed"),
    "d": ([("            if now < self.newest - LEDGER_CLOCK_SLACK:  ", "            if False:  ")], "holds ingest"),
    "e": ([("        el = (mono - lmono) if lmono is not None else (now - lts)", "        el = now - lts")], "in full"),
    "f": ([("        if rec is None:                                        # a known pid's NEW record",
            "        if rec is None and False:                              # a known pid's NEW record"),
           ("        lrx, ltx, lts, lmono = rec\n", "        if rec is None:\n            self.slots[s][\"o\"][0] += rx; self.slots[s][\"o\"][1] += tx\n            self.recs[key] = (rx, tx, now, mono)\n            return\n        lrx, ltx, lts, lmono = rec\n")],
          "second opening"),
    "g": ([("            elif owners[pid] != self.slots[s].get(\"owner\"):", "            elif False:")], "owner change"),
    "h": ([("        gone = [k for k in self.recs if k not in deploys] ", "        gone = [] ")], "records go"),
    "i": ([("        self.map = {k: next(iter(v)) for k, v in claims.items() if len(v) == 1}",
            "        self.map = {k: sorted(v)[0] for k, v in claims.items()}")], "credits neither"),
    "j": ([("        cred = (p.get(\"wdtt_password\") if _is_wdtt_target(t)", "        cred = (p.get(\"pubkey\") if _is_wdtt_target(t)")],
          "own peer"),
    "k": ([("                self._err(\"index.json\", e)\n                return requeue(True, bool(snap), qf, qd)",
            "                self._err(\"index.json\", e)")], "past a failed index"),
    "l": ([("            self._advance(d, i, off, now, mid)\n            m = self.map\n",
            "            m = self.map\n"),
           ("            self._span(nid, now)\n            self.newest = max(self.newest, now)\n",
            "            self._advance(d, i, off, now, mid)\n            self._span(nid, now)\n            self.newest = max(self.newest, now)\n")],
          "as it stood at midnight"),
    "m": ([("        if (d, i) <= (self.day, self.idx):\n            return\n        self._close_bucket()", "        if (d, i) == (self.day, self.idx):\n            return\n        self._close_bucket()")],
          "never go backwards"),
    "n": ([("        for fn in (\"base.bin\", \"base.bin.prev\"):", "        for fn in (\"base.bin\",):")], "previous generation"),
    "o": ([("def _lnum(v):\n    \"\"\"A counter as a non-negative int, or None — a value that cannot be read is no observation, never a zero.\"\"\"\n",
            "def _lnum(v):\n    \"\"\"A counter as a non-negative int, or None — a value that cannot be read is no observation, never a zero.\"\"\"\n    if v is None:\n        return 0\n")],
          "no observation"),
    "q": ([("            row = self._newest_row()  ", "            row = None  ")], "newest closed day"),
    "r": ([("            idx = load_critical(self._p(\"index.json\"), None)", "            idx = load_json(self._p(\"index.json\"), None)")],
          "from its backup"),
    "s": ([("            self.on, self.why_off = False, \"index.json is unreadable and no backup is good (%s)\" % e\n            print(\"ledger: OFF — %s\" % self.why_off, flush=True)\n            return\n",
            "            idx = None\n")], "stays off"),
    "t": ([("        try:\n            LEDGER.ingest(nid, snap)\n        except Exception as e:\n            LEDGER.ingest_failed(e)\n",
            "        LEDGER.ingest(nid, snap)\n")], "never fails the sync"),
    "u": ([("        for n, dr in enumerate(qd):\n            try:\n                self._append_day(dr)\n            except Exception as e:\n                self._err(\"day\", e)\n                return requeue(False, bool(snap), qf, qd[n:])\n        if snap:\n            try:\n                self._write_base(snap)\n            except Exception as e:\n                self._err(\"base.bin\", e)\n                return requeue(False, True, qf, [])\n",
            "        if snap:\n            try:\n                self._write_base(snap)\n            except Exception as e:\n                self._err(\"base.bin\", e)\n                return requeue(False, True, qf, [])\n        for n, dr in enumerate(qd):\n            try:\n                self._append_day(dr)\n            except Exception as e:\n                self._err(\"day\", e)\n                return requeue(False, False, qf, qd[n:])\n")],
          "before base.bin"),
    "v": ([("            if d <= self.day:                                  # the day the ledger is in keeps its own frame",
            "            if False:                                          # the day the ledger is in keeps its own frame")],
          "keeps the frame"),
    "w": ([("                self._retry_at = time.monotonic() + max(30, min(self.step, 300))",
            "                self._retry_at = 0.0")], "not retried"),
    "x": ([("            if closing:                                        # in the same lock section as the snapshot: a sync landing\n                self._close_bucket() ",
            "            if closing:                                        # in the same lock section as the snapshot: a sync landing\n                pass ")], "graceful"),
    "y": ([("        fine_ok = (_ld_date(t) - _ld_date(f)).days < LEDGER_SERIES_FINE_DAYS",
            "        fine_ok = True")], "by day"),
    "A": ([("                self.prompt = True                             # retried after it even if nothing else happens\n", "")],
          "retried after the pause"),
    "B": ([("            if d == cur[0] and (not fine_ok or cur[2] >= 86400):", "            if d == cur[0] and not fine_ok:")],
          "1-day resolution"),
    "C": ([("        if pd and (got is None or got[0] < pd):", "        if False:")], "pending"),
    "D": ([("                lc = (sw(live[1]) - drawn[0], sw(live[2]) - drawn[1])", "                lc = (sw(live[1]), sw(live[2]))")],
          "drawn twice"),
    "E": ([("                if d == cur[0] and cur[4] and cur[2] == step:\n                    a = acc.setdefault(cur[1], [0, 0])",
            "                if d == cur[0] and cur[4] and cur[2] == step:\n                    a = acc.setdefault(cur[1] + 10 ** 6, [0, 0])")],
          "one point per bucket"),
    "F": ([("            qf = [(q[0], q[1], q[2], q[4], {s: q[5][s] for s in want if s in q[5]}) for q in self.q_fine if f <= q[0] <= t]",
            "            qf = []")], "waiting for their write"),
    "G": ([("                if _lzlib.crc32(data[o + _LD_ROW.size:p1]) == crc:", "                if True:")], "damaged day row"),
    "H": ([("            kick = self.observed and (self.prompt", "            kick = (self.prompt")], "before anything was observed"),
    "I": ([("                d, mid, off = self.day, self.fmid, self.off    # fine file", "                d, mid = self.day, self.fmid    # fine file")],
          "its own offset"),
    "p": ([("            if end < sz:\n                os.truncate(path, end)\n", "            if False:\n                os.truncate(path, end)\n"),
           ("            end = self._scan_end(path)\n", "            end = sz\n")], "torn tail"),
}

TMP = tempfile.mkdtemp(prefix="ledger-")
panel_path = PANEL
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    for old, new in PLANTS[PLANT][0]:
        assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:90]
        src = src.replace(old, new, 1)
    panel_path = os.path.join(TMP, "planted-panel.py")
    open(panel_path, "w", encoding="utf-8").write(src)

_l = importlib.machinery.SourceFileLoader("swgpanel_ledger", panel_path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_ledger", _l))
_l.exec_module(P)

os.environ["TZ"] = "UTC"
time.tzset()
MAX = P.LEDGER_MAX_BPS
T0 = calendar.timegm((2026, 9, 10, 10, 0, 0))    # 10:00 UTC, bucket 10 of 2026-09-10


def peer(pid, owner, pubkey="", targets=(), **kw):
    return {"id": pid, "user_id": owner, "title": "t-" + pid, "pubkey": pubkey, "psk": "",
            "targets": [{"node": n, "iface": i, "ip": "", "type": t} for n, i, t in targets], **kw}


def roster(*peers):
    return {"version": 1, "users": {"u1": {"id": "u1"}, "u2": {"id": "u2"}}, "peers": {p["id"]: p for p in peers}}


def fresh(tag, rost, now=T0):
    d = os.path.join(TMP, tag)
    os.makedirs(d)
    rp = os.path.join(d, "users.json")
    P.roster_save(rp, rost)
    L = P.TrafficLedger()
    L.start({"roster_path": rp, "panel_settings": {}}, now=now, writer=False)
    return L, rp


def reopen(rp, now):
    L = P.TrafficLedger()
    L.start({"roster_path": rp, "panel_settings": {}}, now=now, writer=False)
    return L


def wg(ifn, *peers):
    return {"interfaces": {ifn: {"peers": [{"public_key": k, "rx_bytes": rx, "tx_bytes": tx} for k, rx, tx in peers]}}}


def kl(kind, *insts):
    return {kind: [{"iface": ifn, "passwords": {pw: {"up_bytes": up, "down_bytes": dn} for pw, up, dn in pws}}
                   for ifn, pws in insts]}


def ing(L, nid, snap, t, mono=None):
    L.ingest(nid, snap, now=t, mono=t if mono is None else mono)


def slot_of(L, pid):
    return L.open.get(pid)


def C(L, s):
    return (L.C_rx[s], L.C_tx[s])


def life(L, pid):
    return tuple(L.dump()["pids"][pid]["lifetime"])


# ── [1] the delta rule ────────────────────────────────────────────────────────────────────────────────────────────
def section_1():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[1] the delta rule")
    L, rp = fresh("delta", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 1000, 500)), T0)
    s = slot_of(L, "p1")
    check("a never-seen pid's counter is an opening balance, credited to no bucket",
          s is not None and L.slots[s]["o"] == [1000, 500] and C(L, s) == (0, 0) and not L.fine and life(L, "p1") == (1000, 500),
          (L.slots, C(L, s) if s is not None else None, L.fine))
    ing(L, "n1", wg("awg0", ("K1", 1600, 700)), T0 + 5)
    check("a reading above the last is credited as the difference", C(L, s) == (600, 200) and L.fine.get(s) == [600, 200],
          (C(L, s), L.fine))
    ing(L, "n1", wg("awg0", ("K1", 100, 800)), T0 + 10)
    check("rx dropping is a restart: credited as the new reading", C(L, s) == (700, 1000), C(L, s))
    ing(L, "n1", wg("awg0", ("K1", 300, 10)), T0 + 15)
    check("tx dropping alone is a restart too", C(L, s) == (1000, 1010), C(L, s))
    ing(L, "n1", wg("awg0", ("K1", 300 + 5 * MAX + 10 ** 9, 10)), T0 + 15)
    check("the clamp floors elapsed at 5 s: a reading with no time behind it is capped at 5 s × 10 Gbit/s",
          C(L, s) == (1000 + 5 * MAX, 1010) and L.diag["ifaces"]["n1|awg0"]["clamps"] == 1, (C(L, s), L.diag["ifaces"]))
    last = L.recs[("n1", "awg0", "p1")]
    ing(L, "n1", wg("awg0", ("K1", 10 ** 12, 10 ** 12)), T0 + 15 - 3600, mono=T0 + 16)
    check("a clock behind the newest reading holds ingest — nothing credited, nothing advanced, counted",
          C(L, s) == (1000 + 5 * MAX, 1010) and L.recs[("n1", "awg0", "p1")] == last and L.diag["held_for_clock"] == 1,
          (C(L, s), L.diag["held_for_clock"]))
    big = 10 ** 11                                              # 100 GB: > 5 s × 10 Gbit/s, < 1 h of it
    r0 = last[0]
    ing(L, "n1", wg("awg0", ("K1", r0 + big, 1010)), T0 + 20, mono=T0 + 15 + 3600)
    check("once the clock is right the backlog is credited in full — elapsed is the monotonic hour, not the wall's 5 s",
          C(L, s)[0] == 1000 + 5 * MAX + big, C(L, s)[0] - (1000 + 5 * MAX))


try:
    section_1()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [1] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [2] slots ─────────────────────────────────────────────────────────────────────────────────────────────────────
def section_2():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[2] slots: owners, deletions, a node that comes back")
    R = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n1", "awg0", "awg")]),
               peer("p4", "u2", "K4", [("n1", "awg0", "awg"), ("n2", "awg0", "awg")]))
    L, rp = fresh("slots", R)
    ing(L, "n2", wg("awg0", ("K4", 9000, 1000)), T0)
    ing(L, "n1", wg("awg0", ("K1", 5000, 0), ("K2", 0, 0), ("K4", 3000, 3000)), T0 + 5)
    s4 = slot_of(L, "p4")
    check("a known peer's second deployment is a baseline, never a second opening",
          L.slots[s4]["o"] == [9000, 1000] and C(L, s4) == (0, 0)
          and L.diag["pids"]["p4"].get("not_imported") == [3000, 3000], (L.slots[s4], C(L, s4), L.diag["pids"].get("p4")))
    ing(L, "n1", wg("awg0", ("K1", 5000, 0), ("K2", 500, 500), ("K4", 3000, 3000)), T0 + 10)
    old2 = slot_of(L, "p2")
    R["peers"]["p2"]["user_id"] = "u2"                         # /api/peers/update: the owner as metadata only
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1", 5000, 0), ("K2", 600, 600), ("K4", 3000, 3000)), T0 + 15)
    new2 = slot_of(L, "p2")
    check("a metadata-only owner change closes the old slot with its owner and everything before; the new one starts at it",
          new2 != old2 and L.slots[old2]["until"] == T0 + 15 and L.slots[old2]["owner"] == "u1" and C(L, old2) == (500, 500)
          and L.slots[new2]["owner"] == "u2" and C(L, new2) == (100, 100) and L.slots[new2]["o"] == [0, 0],
          (L.slots, list(L.C_rx)))
    old1 = slot_of(L, "p1")
    R["peers"]["p1"]["pubkey"] = "K1b"; R["peers"]["p1"]["user_id"] = "u2"   # /api/peers/rekey: new key AND new owner
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1b", 50, 60), ("K2", 600, 600), ("K4", 3000, 3000)), T0 + 20)
    new1 = slot_of(L, "p1")
    check("a reassignment by rekey: the old owner keeps everything before; the new counter restarted, credited once, to the new owner",
          new1 != old1 and L.slots[old1]["owner"] == "u1" and C(L, old1) == (0, 0) and C(L, new1) == (50, 60)
          and L.slots[new1]["owner"] == "u2", (L.slots[old1], C(L, old1), C(L, new1)))
    tot = {r["id"]: (r["rx"], r["tx"]) for r in L.totals({"range": ["today"], "by": ["user"]}, now=T0 + 21)["rows"]}
    check("by user, each owner's total counts its own slots — closed ones included",
          tot.get("u1") == (500, 500) and tot.get("u2") == (150, 160), tot)
    del R["peers"]["p2"]                                        # any of the five delete paths: the pid leaves the roster
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1b", 50, 60), ("K4", 3000, 3000)), T0 + 25)
    check("a deleted peer's slot closes, keeps its owner, and its records go",
          "p2" not in L.open and L.slots[new2]["until"] == T0 + 25 and L.slots[new2]["owner"] == "u2"
          and not any(k[2] == "p2" for k in L.recs), (L.open, [k for k in L.recs if k[2] == "p2"]))
    R["peers"]["p4"]["targets"] = [t for t in R["peers"]["p4"]["targets"] if t["node"] != "n2"]   # node_remove: n2's targets go
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1b", 50, 60), ("K4", 3000, 3000)), T0 + 30)
    check("a removed node's records go at the next rebuild", ("n2", "awg0", "p4") not in L.recs, list(L.recs))
    R["peers"]["p4"]["targets"].append({"node": "n2", "iface": "awg0", "ip": "", "type": "awg"})
    P.roster_save(rp, R)
    ing(L, "n2", wg("awg0", ("K4", 9500, 1100)), T0 + 35)
    check("a node that comes back is a zero-credit baseline — never a second opening",
          L.slots[s4]["o"] == [9000, 1000] and C(L, s4) == (0, 0) and ("n2", "awg0", "p4") in L.recs, (L.slots[s4], C(L, s4)))


try:
    section_2()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [2] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [3] the map ───────────────────────────────────────────────────────────────────────────────────────────────────
def section_3():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[3] the map: (node, iface, credential) → pid")
    L, rp = fresh("map", roster(
        peer("p5", "u1", "", [("n1", "wdtt0", "wdtt")], wdtt_password="SHARED"),
        peer("p6", "u2", "", [("n1", "wdtt1", "wdtt")], wdtt_password="SHARED"),
        peer("p7", "u1", "K7", [("n1", "awg0", "awg")]), peer("p8", "u2", "K7", [("n1", "awg0", "awg")]),
        peer("p9", "u1", "", [("n1", "awg0", "awg")]),
        peer("p10", "u2", "", [("n1", "csqtt1", "csqtt")], csqtt_password="C10")))
    snap = {**kl("wdtt", ("wdtt0", [("SHARED", 100, 10)]), ("wdtt1", [("SHARED", 200, 20)])),
            **wg("awg0", ("K7", 70, 7), ("", 90, 9)), **kl("csqtt", ("csqtt1", [("C10", 300, 30)]))}
    snap["interfaces"]["swg_link"] = {"peers": [{"public_key": "FARKEY", "rx_bytes": 1, "tx_bytes": 1}]}
    ing(L, "n1", snap, T0)
    o = lambda pid: L.slots[slot_of(L, pid)]["o"] if slot_of(L, pid) is not None else None
    check("the same password on two instances credits each instance's own peer", o("p5") == [100, 10] and o("p6") == [200, 20],
          (o("p5"), o("p6")))
    check("two peers claiming one counter: the ledger credits neither, and counts it",
          o("p7") is None and o("p8") is None and L.diag["ambiguous"] == 1, (o("p7"), o("p8"), L.diag["ambiguous"]))
    check("an empty pubkey never resolves", o("p9") is None)
    check("a mesh link's peer — the far node's own key — is never credited", "FARKEY" not in json.dumps(L.dump()))
    check("csqtt: up is what the server received (rx), down what it sent", o("p10") == [300, 30], o("p10"))


try:
    section_3()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [3] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [4] absent is not zero ────────────────────────────────────────────────────────────────────────────────────────
def section_4():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[4] absent is not zero")
    L, rp = fresh("absent", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]),
                                   peer("p5", "u1", "", [("n1", "wdtt0", "wdtt")], wdtt_password="PW5")))
    ing(L, "n1", {**wg("awg0", ("K1", 1000, 1000)), **kl("wdtt", ("wdtt0", [("PW5", 500, 500)]))}, T0)
    r1, r5 = L.recs.get(("n1", "awg0", "p1")), L.recs.get(("n1", "wdtt0", "p5"))
    ing(L, "n1", {"interfaces": {"awg0": {"peers": []}}, "wdtt": [{"iface": "wdtt0", "passwords": {}}]}, T0 + 5)
    ing(L, "n1", {"interfaces": {}}, T0 + 10)
    ing(L, "n1", {"interfaces": {"awg0": {"peers": [{"public_key": "K1", "rx_bytes": None, "tx_bytes": "x"}]}},
                  "wdtt": [{"iface": "wdtt0", "passwords": {"PW5": {"up_bytes": None}}}]}, T0 + 15)
    same = bool(r1 and r5) and L.recs.get(("n1", "awg0", "p1")) == r1 and L.recs.get(("n1", "wdtt0", "p5")) == r5
    ing(L, "n1", {**wg("awg0", ("K1", 1100, 1100)), **kl("wdtt", ("wdtt0", [("PW5", 600, 600)]))}, T0 + 20)
    check("a down interface, a dropped key, `passwords: {}` and an unreadable value are no observation — the next reading is a plain difference",
          same and slot_of(L, "p5") is not None and C(L, slot_of(L, "p1")) == (100, 100) and C(L, slot_of(L, "p5")) == (100, 100)
          and not L.diag["ifaces"].get("n1|awg0", {}).get("resets"), (same, L.diag["ifaces"]))


try:
    section_4()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [4] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [5] durability ────────────────────────────────────────────────────────────────────────────────────────────────
def section_5():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[5] durability")
    L, rp = fresh("crash", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 1000, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 2000, 0)), T0 + 5)
    L.flush()
    ing(L, "n1", wg("awg0", ("K1", 3000, 0)), T0 + 10)       # credited in memory only — then the process dies
    L2 = reopen(rp, T0 + 20)
    ing(L2, "n1", wg("awg0", ("K1", 4000, 0)), T0 + 30)
    s = slot_of(L2, "p1")
    check("a crash loses nothing and doubles nothing: the next reading re-credits exactly cur − last",
          C(L2, s) == (3000, 0) and L2.slots[s]["o"] == [1000, 0], (C(L2, s), L2.slots[s]))
    hd = os.path.join(TMP, "crash", "history")
    base_before = open(os.path.join(hd, "base.bin"), "rb").read()
    real_save = P.save_critical


    def failing_save(path, text, mode=0o600, keep=8):
        if path.endswith("index.json"):
            raise OSError(28, "No space left on device")
        return real_save(path, text, mode, keep)


    P.save_critical = failing_save
    R = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n1", "awg0", "awg")]))
    P.roster_save(rp, R)
    ing(L2, "n1", wg("awg0", ("K1", 4100, 0), ("K2", 50, 0)), T0 + 35)   # p2 opens → index.json must be written first
    L2.flush()
    P.save_critical = real_save
    check("base.bin is never written past a failed index.json (a slot's C with no slot to name it)",
          open(os.path.join(hd, "base.bin"), "rb").read() == base_before and L2.d_index and L2.diag["write_errors"] >= 1,
          (L2.d_index, L2.diag["write_errors"]))
    L2.flush()
    check("…and the next pass writes both, in order", not L2.d_index and not L2.d_base and
          json.load(open(os.path.join(hd, "index.json")))["slots"][-1]["pid"] == "p2")
    ing(L2, "n1", wg("awg0", ("K1", 4200, 0), ("K2", 60, 0)), T0 + 40)
    L2.flush()                                                  # base.bin = this state, base.bin.prev = the one before
    good = C(L2, slot_of(L2, "p1"))
    with open(os.path.join(hd, "base.bin"), "r+b") as f:
        f.seek(70); b = f.read(1); f.seek(70); f.write(bytes([b[0] ^ 0xFF]))
    L3 = reopen(rp, T0 + 45)
    check("a corrupt base.bin falls back to its previous generation",
          L3.on and C(L3, slot_of(L3, "p1")) == (3100, 0) and "prev" in L3.diag["base_recovered"],
          (C(L3, slot_of(L3, "p1")), good, L3.diag["base_recovered"]))

    L, rp = fresh("lost", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 7000, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 7500, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 7800, 0)), calendar.timegm((2026, 9, 11, 0, 0, 30)))   # closes 10 Sep at C = 500
    L.flush()
    ing(L, "n1", wg("awg0", ("K1", 8000, 0)), calendar.timegm((2026, 9, 11, 1, 0, 0)))
    L.flush()
    hd = os.path.join(TMP, "lost", "history")
    for fn in ("base.bin", "base.bin.prev"):
        with open(os.path.join(hd, fn), "r+b") as f:
            f.seek(0); f.write(b"XXXX")
    L2 = reopen(rp, calendar.timegm((2026, 9, 11, 2, 0, 0)))
    s = slot_of(L2, "p1")
    ing(L2, "n1", wg("awg0", ("K1", 8100, 0)), calendar.timegm((2026, 9, 11, 2, 0, 5)))
    check("with both base generations lost, C comes back from the newest closed day, and nothing opens twice",
          C(L2, s) == (500, 0) and L2.slots[s]["o"] == [7000, 0] and len(L2.slots) == 1
          and L2.diag["pids"]["p1"].get("not_imported") == [8100, 0], (C(L2, s), L2.slots, L2.diag["pids"].get("p1")))
    ix = os.path.join(hd, "index.json")
    with open(ix, "w") as f:
        f.write("{not json")
    L3 = reopen(rp, calendar.timegm((2026, 9, 11, 3, 0, 0)))
    check("a corrupt index.json is recovered from its backup", L3.on and [x["pid"] for x in L3.slots] == ["p1"], (L3.on, L3.why_off))
    for b in [f for f in os.listdir(hd) if f.startswith("index.json.bak.")]:
        os.unlink(os.path.join(hd, b))
    with open(ix, "w") as f:
        f.write("{not json")
    L4 = reopen(rp, calendar.timegm((2026, 9, 11, 4, 0, 0)))
    ing(L4, "n1", wg("awg0", ("K1", 8200, 0)), calendar.timegm((2026, 9, 11, 4, 0, 5)))
    L4.flush()
    check("an unreadable index.json with no good backup: the ledger stays off, says why, and writes nothing",
          not L4.on and "index.json" in L4.why_off and open(ix).read() == "{not json" and not L4.slots,
          (L4.on, L4.why_off, L4.slots))


try:
    section_5()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [5] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [6] days ──────────────────────────────────────────────────────────────────────────────────────────────────────
def section_6():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[6] days: midnight, a DST fall-back, a clock stepped back, missed days")
    L, rp = fresh("days", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 10, 23, 50, 0)))
    t = calendar.timegm((2026, 9, 10, 23, 50, 0))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), t)
    ing(L, "n1", wg("awg0", ("K1", 1000, 0)), t + 590)        # 23:59:50
    ing(L, "n1", wg("awg0", ("K1", 1700, 0)), t + 620)        # 00:00:20 — 700 more, some of it before midnight
    L.flush()
    row = L._row_at_exact(20260910)
    check("a day's row is C as it stood at midnight — before the first reading past it", row is not None and row[1][0] == 1000,
          row and list(row[1]))
    ing(L, "n1", wg("awg0", ("K1", 1800, 0)), t + 600 + 3600 + 20, mono=t + 4300)    # 01:00:20 → bucket 1
    ing(L, "n1", wg("awg0", ("K1", 1900, 0)), t + 600 + 3600 - 20, mono=t + 4310)    # 00:59:40 — 40 s back across the
    ing(L, "n1", wg("awg0", ("K1", 2000, 0)), t + 600 + 3600 + 60, mono=t + 4320)    # boundary, inside the gate's slack
    ing(L, "n1", wg("awg0", ("K1", 2100, 0)), t + 600 + 3 * 3600, mono=t + 12000)
    L.flush()
    ids = [i for i, _n, _e, _c in L._fine_buckets(L._fine_path(20260911))]
    check("bucket ids never go backwards — no bucket written twice, none into the past",
          ids == sorted(set(ids)) and len(ids) == len(set(ids)), ids)
    os.environ["TZ"] = "Europe/Berlin"; time.tzset()
    d0 = int(time.mktime((2026, 10, 24, 23, 30, 0, 0, 0, -1)))   # the night before the fall-back (03:00 CEST → 02:00 CET)
    L, rp = fresh("dst", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=d0)
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), d0)
    v, t = 0, d0
    while t < d0 + 26 * 3600:                                   # every 30 min through the 25-hour day and into the next
        t += 1800; v += 100
        ing(L, "n1", wg("awg0", ("K1", v, 0)), t)
    L.flush()
    b = [(i, c[1][0]) for i, _n, _e, c in L._fine_buckets(L._fine_path(20261025))]
    r24, r25 = L._row_at_exact(20261024), L._row_at_exact(20261025)
    day_total = (r25[1][0] - r24[1][0]) if r24 and r25 else None
    check("a DST fall-back day has 25 hourly buckets, in order, and its total is their sum",
          [i for i, _ in b] == list(range(25)) and day_total == sum(x for _, x in b) == 5000, (b, day_total))
    os.environ["TZ"] = "UTC"; time.tzset()
    L, rp = fresh("missed", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 500, 0)), T0 + 60)
    L.flush()
    L2 = reopen(rp, T0 + 3 * 86400)                            # down for three days
    ing(L2, "n1", wg("awg0", ("K1", 900, 0)), T0 + 3 * 86400 + 5)
    L2.flush()
    rows = [L2._row_at_exact(d) for d in (20260910, 20260911, 20260912)]
    q2 = {r["id"]: r["rx"] for r in L2.totals({"range": ["custom"], "from": ["2026-09-11"], "to": ["2026-09-12"]}, now=T0 + 3 * 86400 + 6)["rows"]}
    check("a panel down across midnights closes the day it stopped in; the days with no reading get no row and read 0",
          rows[0] and rows[0][1][0] == 500 and rows[1] is None and rows[2] is None and q2.get("p1") == 0,
          ([r and list(r[1]) for r in rows], q2))


try:
    section_6()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [6] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [7] queries ───────────────────────────────────────────────────────────────────────────────────────────────────
def section_7():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[7] totals and series")
    L, rp = fresh("q", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n1", "awg0", "awg")])))
    days = [calendar.timegm((2026, 9, d, 12, 0, 0)) for d in (10, 11, 12, 13)]
    per = {10: (100, 10), 11: (200, 20), 12: (400, 40), 13: (800, 80)}
    v1 = [0, 0]
    ing(L, "n1", wg("awg0", ("K1", 0, 0), ("K2", 0, 0)), days[0] - 60)
    for dd, t in zip((10, 11, 12, 13), days):
        v1[0] += per[dd][0]; v1[1] += per[dd][1]
        ing(L, "n1", wg("awg0", ("K1", v1[0], v1[1]), ("K2", v1[0] * 2, v1[1] * 2)), t)
    L.flush()
    q = lambda **kw: {r["id"]: (r["rx"], r["tx"]) for r in L.totals({k: [v] for k, v in kw.items()}, now=days[3] + 60)["rows"]}
    check("total(A..B) = C(end of B) − C(end of A−1): 11–12 September",
          q(range="custom", **{"from": "2026-09-11", "to": "2026-09-12"}).get("p1") == (600, 60),
          q(range="custom", **{"from": "2026-09-11", "to": "2026-09-12"}))
    check("…a window ending today reads the live C", q(range="custom", **{"from": "2026-09-13", "to": "2026-09-13"}).get("p1") == (800, 80))
    check("…and by user it sums the user's peers", q(range="custom", by="user", **{"from": "2026-09-10", "to": "2026-09-13"}).get("u1")
          == (4500, 450), q(range="custom", by="user", **{"from": "2026-09-10", "to": "2026-09-13"}))
    sr = L.series({"id": ["p1"], "by": ["peer"], "from": ["2026-09-10"], "to": ["2026-09-13"]}, now=days[3] + 60)
    check("a peer's series sums to its total", sum(p[2] for p in sr["points"]) == 1500 and all(p[1] == 3600 for p in sr["points"]),
          sr["points"])


try:
    section_7()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [7] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [8] files ─────────────────────────────────────────────────────────────────────────────────────────────────────
def section_8():
    global L, rp, s, R, snap, o, same, r1, r5, L2, L3, L4, hd, t, v, d0, b, r24, r25, day_total, rows, days, per, v1, q, sr, fp, got, ids, tot, old1, old2, new1, new2, s4, last, big, r0, ix, row, good, base_before, real_save
    print("[8] files")
    L, rp = fresh("torn", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)
    L.flush()
    fp = L._fine_path(20260910)
    with open(fp, "ab") as f:
        f.write(b"\x0b\x00\x00\x00\x05\x00\x00\x00torn")            # a crash mid-append
    L2 = reopen(rp, T0 + 3700)
    ing(L2, "n1", wg("awg0", ("K1", 300, 0)), T0 + 3700)
    ing(L2, "n1", wg("awg0", ("K1", 400, 0)), T0 + 7200)
    L2.flush()
    got = [(i, c[1][0]) for i, _n, _e, c in L2._fine_buckets(fp)]
    # bucket 11 holds only what came after the restart: its first 100 was in C (base.bin) but not yet in the open bucket —
    # the fine tier may miss a bucket's part across a crash, never count it twice (plan §5.3)
    check("a torn tail is cut before the next append — every bucket after it stays readable", got == [(10, 100), (11, 100)], got)
    L, rp = fresh("step", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)       # closes bucket 10: the day file is created at 3600 s
    L.flush()
    L.step = 900                                                # the resolution changes under that day file
    ing(L, "n1", wg("awg0", ("K1", 300, 0)), T0 + 3600 + 1800)
    ing(L, "n1", wg("awg0", ("K1", 400, 0)), T0 + 86400)
    L.flush()
    check("a bucket at another resolution is dropped and counted — never blocking the day rows behind it",
          L.diag.get("fine_dropped", 0) >= 1 and L._row_at_exact(20260910) is not None and not L.q_day,
          (L.diag.get("fine_dropped"), L._row_at_exact(20260910), L.q_day))


try:
    section_8()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [8] ran to the end", False, "%s: %s" % (type(e).__name__, e))

# ── [9] the hook ──────────────────────────────────────────────────────────────────────────────────────────────────
print("[9] the hook: a ledger failure never costs a sync its rings")


def section_9():
    stats = os.path.join(TMP, "hook-stats")
    os.makedirs(stats)
    P.Handler.deps = {"stats_dir": stats, "node_snaps": {}, "live_samples": {}}
    boom = P.TrafficLedger()
    boom.on = True

    def raise_(*a, **k):
        raise RuntimeError("planted ledger failure")
    boom.ingest = raise_
    real, P.LEDGER = P.LEDGER, boom
    snap = {"interfaces": {"awg0": {"peers": [{"public_key": "K1", "rx_bytes": 1, "tx_bytes": 1, "rx_speed": 5000,
                                                "tx_speed": 5000, "online": True}]}}}
    try:
        P.Handler._node_sync_history(None, "n1", {"id": "n1"}, {"n1": {"id": "n1"}}, snap)
        raised = None
    except Exception as e:
        raised = e
    finally:
        P.LEDGER = real
    check("a ledger that raises never fails the sync, and is counted (V33)",
          raised is None and boom.diag.get("ingest_errors") == 1, (raised, boom.diag.get("ingest_errors")))
    check("…and that sync's rings are all written",
          os.path.exists(os.path.join(stats, "health-n1.rrd")) and os.path.exists(P.iface_rrd_path(stats, "n1", "awg0")))


try:
    section_9()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [9] ran to the end", False, "%s: %s" % (type(e).__name__, e))


# ── [10] the review's findings ────────────────────────────────────────────────────────────────────────────────────────
print("[10] a closed day before base.bin, a zone change mid-day, the retry backoff, shutdown, long series")


def section_10():
    global L, rp
    L, rp = fresh("dayfirst", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 10, 23, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 1000, 0)), calendar.timegm((2026, 9, 10, 23, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 5000, 0)), calendar.timegm((2026, 9, 10, 23, 30, 0)))
    L.flush()
    hd = os.path.join(TMP, "dayfirst", "history")
    base0 = open(os.path.join(hd, "base.bin"), "rb").read()
    ing(L, "n1", wg("awg0", ("K1", 9000, 0)), calendar.timegm((2026, 9, 11, 0, 1, 0)))   # closes 10 Sep at C = 4000
    real = L._append_day

    def fail(dr):
        raise OSError(5, "Input/output error")
    L._append_day = fail
    L.flush()
    L._append_day = real
    check("a closed day's row is written before base.bin: a failed day append leaves base.bin as it was, so a restart re-closes the day",
          open(os.path.join(hd, "base.bin"), "rb").read() == base0 and L.q_day, (len(L.q_day),))
    L2 = reopen(rp, calendar.timegm((2026, 9, 11, 0, 2, 0)))
    ing(L2, "n1", wg("awg0", ("K1", 9100, 0)), calendar.timegm((2026, 9, 11, 0, 2, 5)))
    L2.flush()
    r = L2._row_at_exact(20260910)
    check("…and after the restart that day still has its row", r is not None and r[1][0] >= 4000, r and list(r[1]))

    L, rp = fresh("tzmove", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 10, 8, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), calendar.timegm((2026, 9, 10, 8, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), calendar.timegm((2026, 9, 10, 8, 20, 0)))
    os.environ["TZ"] = "Europe/Moscow"; time.tzset()          # Settings: days are counted in Moscow from now on
    try:
        ing(L, "n1", wg("awg0", ("K1", 200, 0)), calendar.timegm((2026, 9, 10, 9, 10, 0)))
        ing(L, "n1", wg("awg0", ("K1", 300, 0)), calendar.timegm((2026, 9, 10, 10, 10, 0)))
        L.flush()
        pts = [(i, c[1][0]) for i, _n, _e, c in L._fine_buckets(L._fine_path(20260910))]
        mid = P._LF_FHEAD.unpack(open(L._fine_path(20260910), "rb").read(P._LF_FHEAD.size))[5]
        check("a zone change mid-day: the rest of that day keeps the frame its file started in — 09:10 UTC is bucket 9, not Moscow's 12",
              mid == calendar.timegm((2026, 9, 10, 0, 0, 0)) and pts == [(8, 100), (9, 100)], (mid, pts))
        ing(L, "n1", wg("awg0", ("K1", 400, 0)), calendar.timegm((2026, 9, 10, 21, 0, 30)))   # 00:00:30 in Moscow
        ing(L, "n1", wg("awg0", ("K1", 500, 0)), calendar.timegm((2026, 9, 10, 22, 30, 0)))
        L.flush()
        check("…and the next day starts in the new zone (its midnight is Moscow's)",
              L.day == 20260911 and L.fmid == calendar.timegm((2026, 9, 10, 21, 0, 0)), (L.day, L.fmid))
        hd10 = open(L._day_path(20260910), "rb").read()
        off10 = P._LD_ROW.unpack_from(hd10, P._LD_FHEAD.size)[1]
        check("…and the day kept in its old frame records its own offset, not the new zone's", off10 == 0, off10)
    finally:
        os.environ["TZ"] = "UTC"; time.tzset()

    L, rp = fresh("backoff", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)

    def nospace(*a, **k):
        raise OSError(28, "No space left on device")
    real_save, P.save_critical = P.save_critical, nospace
    try:
        L.flush()
    finally:
        P.save_critical = real_save
    check("a failed write is not retried at once on every sync — the next attempt waits (no storm)",
          L._retry_at > time.monotonic() + 20, (L._retry_at, time.monotonic()))
    L0 = P.TrafficLedger()
    L0.start({"roster_path": os.path.join(TMP, "backoff", "users.json"), "panel_settings": {}}, now=T0, writer=False)
    L0.flush()
    check("…while a pass with nothing observed is no failure: it arms no backoff", L0._retry_at == 0.0, L0._retry_at)
    check("…and what failed is retried after the pause even if nothing else happens (the writer is prompted)",
          L.prompt and L.d_index, (L.prompt, L.d_index))

    L, rp = fresh("oneday", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    L.step = 86400                                              # history resolution 1 day: no fine tier
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 400, 40)), T0 + 60)
    sr = L.series({"id": ["p1"], "by": ["peer"], "range": ["today"]}, now=T0 + 61)
    check("at 1-day resolution a short series still shows today, from the live C",
          [p[2:] for p in sr["points"]] == [[400, 40]], sr["points"])

    L, rp = fresh("pending", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 10, 22, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), calendar.timegm((2026, 9, 10, 22, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 700, 0)), calendar.timegm((2026, 9, 10, 23, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 750, 0)), calendar.timegm((2026, 9, 11, 0, 5, 0)))     # 10 Sep closes at C = 700

    def dayfail(dr):
        raise OSError(28, "No space left on device")
    L._append_day = dayfail
    L.flush()                                                   # the day's row stays pending
    q = {r["id"]: r["rx"] for r in L.totals({"range": ["today"]}, now=calendar.timegm((2026, 9, 11, 0, 6, 0)))["rows"]}
    q10 = {r["id"]: r["rx"] for r in L.totals({"range": ["custom"], "from": ["2026-09-10"], "to": ["2026-09-10"]},
                                               now=calendar.timegm((2026, 9, 11, 0, 6, 0)))["rows"]}
    check("a closed day whose row is still pending is read as closed: today does not absorb yesterday",
          q.get("p1") == 50 and q10.get("p1") == 700, (q, q10))

    L, rp = fresh("shutdown", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 700, 0)), T0 + 60)          # 700 in the open bucket 10
    L.shutdown()
    L2 = reopen(rp, T0 + 120)
    ing(L2, "n1", wg("awg0", ("K1", 1000, 0)), T0 + 180)      # 300 more, still bucket 10
    ing(L2, "n1", wg("awg0", ("K1", 1100, 0)), T0 + 3700)     # closes bucket 10
    L2.flush()
    got = [(i, c[1][0]) for i, _n, _e, c in L2._fine_buckets(L2._fine_path(20260910))]
    sr = L2.series({"id": ["p1"], "by": ["peer"], "range": ["today"]}, now=T0 + 3701)
    check("a graceful shutdown writes the open bucket: the graph misses nothing across the restart, and the bucket's two halves sum",
          got == [(10, 700), (10, 300)] and sum(p[2] for p in sr["points"]) == 1100, (got, sr["points"]))

    # (1) a resolution changed to 1 day mid-day: today's fine points plus the rest of the day, nothing twice
    L, rp = fresh("res1d", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 500, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 600, 0)), T0 + 3600)      # closes bucket 10 (500) into today's fine file
    L.flush()
    L.step = 86400                                              # the next start runs at 1 day
    ing(L, "n1", wg("awg0", ("K1", 900, 0)), T0 + 7200)
    sr = L.series({"id": ["p1"], "by": ["peer"], "range": ["today"]}, now=T0 + 7201)
    check("a resolution changed to 1 day mid-day: today's fine points and the rest of the day, nothing drawn twice",
          sum(p[2] for p in sr["points"]) == 900, sr["points"])

    # (4) + (5) a bucket split by a restart, and closed buckets whose write is paused
    L, rp = fresh("split", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 700, 0)), T0 + 60)
    L.shutdown()                                                # bucket 10's first half is written
    L2 = reopen(rp, T0 + 120)
    ing(L2, "n1", wg("awg0", ("K1", 1000, 0)), T0 + 180)       # the second half, still open
    sr = L2.series({"id": ["p1"], "by": ["peer"], "range": ["today"]}, now=T0 + 181)
    ts = [p[0] for p in sr["points"]]
    check("a bucket split by a restart is one point per bucket — its halves summed", ts == sorted(set(ts)) and
          [p[2] for p in sr["points"]] == [1000], sr["points"])

    def finefail(fb):
        raise OSError(28, "No space left on device")
    L2._append_fine = finefail
    ing(L2, "n1", wg("awg0", ("K1", 1200, 0)), T0 + 3700)      # closes bucket 10 (its second half): its write fails
    ing(L2, "n1", wg("awg0", ("K1", 1500, 0)), T0 + 7300)      # closes 11: waits too
    L2.flush()
    sr = L2.series({"id": ["p1"], "by": ["peer"], "range": ["today"]}, now=T0 + 7301)
    check("closed buckets still waiting for their write are in the series — the graph has no hole the totals lack",
          sum(p[2] for p in sr["points"]) == 1500 and L2.q_fine, (sr["points"], len(L2.q_fine)))

    # (6) a damaged day row: totals and series read the same (they skip it)
    L, rp = fresh("crcrow", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 10, 12, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), calendar.timegm((2026, 9, 10, 12, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), calendar.timegm((2026, 9, 10, 13, 0, 0)))
    ing(L, "n1", wg("awg0", ("K1", 300, 0)), calendar.timegm((2026, 9, 11, 13, 0, 0)))    # closes 10 Sep (C = 100)
    ing(L, "n1", wg("awg0", ("K1", 600, 0)), calendar.timegm((2026, 9, 12, 13, 0, 0)))    # closes 11 Sep (C = 300)
    L.flush()
    dp = L._day_path(20260911)
    raw = bytearray(open(dp, "rb").read())
    o11 = L._day_rows(dp)[20260911][0]
    raw[o11 + P._LD_ROW.size] ^= 0xFF                           # bit rot in 11 Sep's C table
    open(dp, "wb").write(bytes(raw))
    L._rowidx.clear()
    tot = {r["id"]: r["rx"] for r in L.totals({"range": ["custom"], "from": ["2026-09-12"], "to": ["2026-09-12"]},
                                              now=calendar.timegm((2026, 9, 12, 14, 0, 0)))["rows"]}
    sr = L.series({"id": ["p1"], "by": ["peer"], "from": ["2026-09-01"], "to": ["2026-09-12"]}, now=calendar.timegm((2026, 9, 12, 14, 0, 0)))
    check("a damaged day row is skipped by totals and series alike — the two never read two versions of one day",
          20260911 not in L._day_rows(dp) and sum(p[2] for p in sr["points"]) == 600 and tot.get("p1") == 500,
          (sorted(L._day_rows(dp)), sr["points"], tot))

    # (3) nothing to write before the first observation: the writer is not woken
    L, rp = fresh("nowake", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    L.d_index = L.prompt = True                                 # a rebuild closed a slot before anything was observed
    L._kick = False
    ing(L, "n1", {"interfaces": {}}, T0)
    check("before anything was observed, nothing wakes the writer (no no-op flush every sync)", not L._kick, L._kick)

    L, rp = fresh("long", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])), now=calendar.timegm((2026, 9, 1, 12, 0, 0)))
    v = 0
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), calendar.timegm((2026, 9, 1, 12, 0, 0)))
    for dd in range(1, 13):
        for hh in (12, 14):
            v += 100
            ing(L, "n1", wg("awg0", ("K1", v, 0)), calendar.timegm((2026, 9, dd, hh, 30, 0)))
    ing(L, "n1", wg("awg0", ("K1", v, 0)), calendar.timegm((2026, 9, 13, 0, 5, 0)))
    L.flush()
    sr = L.series({"id": ["p1"], "by": ["peer"], "from": ["2026-09-01"], "to": ["2026-09-12"]}, now=calendar.timegm((2026, 9, 13, 0, 6, 0)))
    check("a series longer than 8 days is answered by day, from the day rows — and still sums to the total",
          bool(sr["points"]) and all(p[1] == 86400 for p in sr["points"]) and sum(p[2] for p in sr["points"]) == v,
          (sr["points"][:3], v))


try:
    section_10()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [10] ran to the end", False, "%s: %s" % (type(e).__name__, e))

shutil.rmtree(TMP, ignore_errors=True)
if PLANT:
    want = PLANTS[PLANT][1]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
