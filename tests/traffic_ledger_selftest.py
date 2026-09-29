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
  [11] the retrospective  a snapshot older than its node's newest is dropped (never a restart that re-credits the whole
                       counter); a missing index.json is recovered from its backup and, beside history with none, the
                       ledger stays off, as it does for an index older than the files it indexes; a record cut short
                       is cut back, a failed fsync rewrites in place; at a new ledger's first start every deployment
                       imports once; a deleted peer keeps its last name

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
     s  an unreadable index.json with no good backup starts a fresh, empty ledger (a lone one: nothing else to guard it)
     t  the ingest hook runs without its own guard
     u  base.bin is written before the closed day's row
     v  a zone change mid-day re-counts the rest of the day from the new zone's midnight
     w  a failed write is retried at once, on every sync
     x  a graceful shutdown leaves the open bucket unwritten
     y  a long series reads every day's fine file
     (z retired: once the pause moved into requeue(), an empty pass returning None arms nothing — its check stays)
     (r retired — "index.json read without its backups": a corrupt primary then reads as missing, and the missing-index
      fallback (plant N) recovers it from the same backups, so the defect loses nothing — its check stays)
     A  a requeued write is not retried unless something else happens
     B  at 1-day resolution a short series leaves today out
     C  readers ignore a closed day whose row is still pending
     D  a resolution changed to 1 day mid-day: today's whole-day point repeats what the fine file drew
     E  a bucket split by a restart is drawn as two points on one timestamp
     F  closed buckets still waiting for their write are left out of the series
     G  day rows are indexed without their checksums (a damaged row: totals skip it, the series reads it)
     H  the writer is woken on every sync before anything was observed
     I  a day kept in its old frame after a zone change records the new zone's offset
     J  at a new ledger's first start only the first deployment a pid is seen on imports its counter
     K  a snapshot older than its node's newest is ingested (its smaller counters read as a restart)
     L  the sync hook drops the arrival number
     M  a missing index.json with no backup, beside the history, starts a fresh ledger
     N  a missing index.json is not recovered from its backups
     O  an index.json narrower than base.bin / the day rows is accepted
     P  a short os.write is taken as the whole record
     Q  a failed fsync forgets the end, so the retry appends a second copy
     R  an open slot's name does not follow its peer's title
     S  a custom range may start in year 1
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
    "a": ([("                self.recs[key] = (rx, tx, now, mono)                # a node transferred in)\n                self.prompt = True\n",
            "                self.recs[key] = (rx, tx, now, mono)                # a node transferred in)\n                self.prompt = True\n                self.fine[self.open[pid]] = [rx, tx]\n")],
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
    "l": ([("            self._advance(d, i, off, now, mid, step)\n            m = self.map\n",
            "            m = self.map\n"),
           ("            self._span(nid, now)\n            self.newest = max(self.newest, now)\n",
            "            self._advance(d, i, off, now, mid, step)\n            self._span(nid, now)\n            self.newest = max(self.newest, now)\n")],
          "as it stood at midnight"),
    "m": ([("        if (d, i) <= (self.day, self.idx):\n            return\n        self._close_bucket()", "        if (d, i) == (self.day, self.idx):\n            return\n        self._close_bucket()")],
          "never go backwards"),
    "n": ([("        for fn in (\"base.bin\", \"base.bin.prev\"):", "        for fn in (\"base.bin\",):")], "previous generation"),
    "o": ([("def _lnum(v):\n    \"\"\"A counter as a non-negative int, or None — a value that cannot be read is no observation, never a zero.\"\"\"\n",
            "def _lnum(v):\n    \"\"\"A counter as a non-negative int, or None — a value that cannot be read is no observation, never a zero.\"\"\"\n    if v is None:\n        return 0\n")],
          "no observation"),
    "q": ([("            if row is not None:                                # a lost base.bin",
            "            if False:                                          # a lost base.bin")], "newest closed day"),
    "s": ([("            self.on, self.why_off = False, \"index.json is unreadable and no backup is good (%s)\" % e\n            print(\"ledger: OFF — %s\" % self.why_off, flush=True)\n            return\n",
            "            idx = None\n")], "lone corrupt index.json"),
    "t": ([("        try:\n            LEDGER.ingest(nid, snap, seq=seq)\n        except Exception as e:\n            LEDGER.ingest_failed(e)\n",
            "        LEDGER.ingest(nid, snap, seq=seq)\n")], "never fails the sync"),
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
    "F": ([("        qf = [q for q in qf_all if f <= q[0] <= t]  ", "        qf = []  ")], "waiting for their write"),
    "G": ([("            if _lzlib.crc32(data[o + _LD_ROW.size:p1]) == crc:   # a damaged C table", "            if True:   # a damaged C table")], "damaged day row"),
    "H": ([("            kick = self.observed and (self.prompt", "            kick = (self.prompt")], "before anything was observed"),
    "I": ([("                d, mid, off = self.day, self.fmid, self.off    # fine file", "                d, mid = self.day, self.fmid    # fine file")],
          "its own offset"),
    "p": ([("            elif end < sz:\n                os.truncate(path, end)\n", "            elif False:\n                os.truncate(path, end)\n"),
           ("                end = self._scan_end(path)\n", "                end = sz\n")], "torn tail"),
    "J": ([("            if key in self.imports:                            # — unless",
            "            if False:                                          # — unless")], "BOTH counters"),
    "K": ([("                if seq < self.seqs.get(nid, 0):", "                if False:")], "never read as a restart"),
    "L": ([("            LEDGER.ingest(nid, snap, seq=seq)\n", "            LEDGER.ingest(nid, snap)\n")], "arrival number"),
    "M": ([("            if idx is None and any(f.startswith((\"base.bin\", \"day-\", \"fine-\")) for f in os.listdir(self.dir)):",
            "            if False:")], "never a new table"),
    "N": ([("            for b in _state_backups(self._p(\"index.json\")):    # takes a missing primary",
            "            for b in []:    # takes a missing primary")], "recovered from its newest backup"),
    "O": ([("        if wide > n:                                           # base.bin, every day row",
            "        if False:                                              # base.bin, every day row")], "older than the history"),
    "P": ([("                    mv = mv[n:]\n", "                    mv = mv[len(mv):]\n")], "cut short"),
    "Q": ([("                self._tails[path] = end                        # record IN PLACE",
            "                self._tails.pop(path, None)                    # record IN PLACE")], "retried in place"),
    "R": ([("            if t is not None and self.slots[s].get(\"name\") != t:", "            if False:")], "LAST name"),
    "S": ([("            f, t = max(f, 19700101), min(t, today)", "            f, t = f, min(t, today)")], "before 1970"),
    # [12] the review of the retrospective
    "T": ([("                    if not _ledger_index_ok(got):              # and a backup", "                    if False:                                  # and a backup")],
          "holds no slot table"),
    "U": ([("                   self._fine_width())", "                   0)")], "newest fine buckets"),
    "V": ([("                if not isinstance(t, dict) or not isinstance(t.get(\"node\"), str) or not isinstance(t.get(\"iface\"), str) \\\n                        or not t[\"node\"] or not t[\"iface\"]:",
            "                if not isinstance(t, dict) or not t.get(\"node\") or not t.get(\"iface\"):")], "not a string"),
    "W": ([("            if valid is not None and not valid(data):", "            if False:")], "CORRUPT index.json"),
    "X": ([("            if sz < len(magic):                                # its first write never finished",
            "            if False:                                          # its first write never finished")], "first write"),
    "Y": ([("            self._tails.pop(self._day_path(d), None)           # and a row written whole", "            pass  # and a row written whole")],
          "never lands on"),
    "Z": ([("            if f > t:\n                raise ValueError(perr(\"from and to must include", "            if False:\n                raise ValueError(perr(\"from and to must include")],
          "inverted window"),
    "a2": ([("        elif not nslots:                                       # an empty ledger walks no day before today\n            f = t",
             "        elif not nslots:                                       # an empty ledger walks no day before today\n            f = f")], "empty ledger"),
    "c2": ([("                step = self.step_next\n", "                step = self.step\n")], "next day"),
    "d2": ([("        if fh:                                                 # thousands). The day keeps its file's frame",
             "        if False:                                              # thousands). The day keeps its file's frame"),
            ("        elif d == bday and bstep and not env:", "        elif False:")], "or a restart after it"),
    "e2": ([("            if on is not None and self.slots[s].get(\"on\") != on:", "            if False:")], "owner's LAST name"),
    "f2": ([("                if since_ >= (r.get(\"_last\") or 0):", "                if False:")], "pair names it"),
    "j2": ([("                if d < cutoff:\n                    with contextlib.suppress(FileNotFoundError):",
             "                if d <= cutoff:\n                    with contextlib.suppress(FileNotFoundError):")], "exactly what"),
    "k2": ([("                sz = e.stat(follow_symlinks=False).st_size\n                led += sz", "                sz = e.stat(follow_symlinks=False).st_size\n                led += sz if not e.name.startswith(\"index\") else 0")],
           "equals du"),
    "o2": ([("        day = self._sweep_ok() if self._sweep_due and not self.infinite and self.on and self.observed and not closing else 0",
             "        day = 0")], "full disk"),
    "p2": ([("        return mono >= self._sweep_at and self.day == today and mono - self._day_mono >= LEDGER_SWEEP_HOLD_S",
             "        return mono >= self._sweep_at and mono - self._day_mono >= LEDGER_SWEEP_HOLD_S")], "jumped ahead"),
    "u2": ([("        return mono >= self._sweep_at and self.day == today and mono - self._day_mono >= LEDGER_SWEEP_HOLD_S",
             "        return mono >= self._sweep_at and self.day == today")], "held for ten minutes"),
    "q2": ([(" and self.on and self.observed and not closing else 0", " and self.on and not closing else 0")], "observed nothing"),
    "w3": ([("        except FileNotFoundError:                              # deleted by the OFF sweep since the caller looked\n            return None",
             "        except ZeroDivisionError:                              # deleted by the OFF sweep since the caller looked\n            return None")],
           "under a series read"),
    "w2": ([("                except FileNotFoundError:\n                    head = None", "                except ZeroDivisionError:\n                    head = None")],
           "between its header"),
    "y2": ([("            if (not kick and self._sweep_due and not self.infinite and self.observed and mono >= self._retry_at\n                    and self._sweep_ready(today, mono)):",
             "            if False:")], "held back"),
    "y3": ([(" and self.observed and mono >= self._retry_at\n                    and self._sweep_ready(today, mono)):",
             "\n                    and self._sweep_ready(today, mono)):")], "wakes nothing"),
    "z2": ([("            if _lzlib.crc32(data[o + _LD_ROW.size:p1]) == crc:   # a damaged C table",
             "            if _lzlib.crc32(data[o + _LD_ROW.size:p1]) != crc:\n                return rows, o, \"torn\"\n            if True:   # a damaged C table")],
           "damaged day row"),
    "z3": ([("            if (ym is not None and d // 100 != ym) or ns < prev or ns > max(prev, len(self.slots)) + LEDGER_ROW_GROWTH:",
             "            if False:")], "cannot be ours"),
    "z4": ([("            if verdict == \"corrupt\":", "            if False:")], "cannot be ours"),
    "z6": ([("        if ym is None:\n            return False\n        for day in range(1, 32):", "        return True\n        for day in range(1, 32):")],
           "real torn tail"),
    "z5": ([("                return rows, o, (\"corrupt\" if self._row_after(data, o, ym) else \"torn\")",
             "                return rows, o, \"torn\"")], "cannot be ours (nsflip)"),
    "x2": ([("        if gone:\n            self._usage = (0.0, None)",
             "        for f in sorted(x for x in os.listdir(self.dir) if x.startswith(\"day-\"))[:1]:\n            os.unlink(self._p(f))\n        if gone:\n            self._usage = (0.0, None)")],
           "never a day row"),
    "b2": ([("            f = min(max(f, _ld_day(first)[0]), t)", "            f = max(f, _ld_day(first)[0])")], "before the ledger began"),
    # [14] P3: the rolling window (Top talkers)
    "a3": ([("        inside = (lambda i: i >= k) if tail else (lambda i: i < k)", "        inside = (lambda i: i >= k) if tail else (lambda i: i <= k)")],
           "summed from the day's end"),
    "b3": ([("            if qstep == step and inside(qi):", "            if False:")], "waiting for their write"),
    "c3": ([("        row = self._row_at_or_before(_ld_prev(d))\n        rx = _larr.array", "        row = self._row_at_or_before(d)\n        rx = _larr.array")],
           "the day before"),
    "g3": ([("            if not s0 % 2:\n                try:", "            if True:\n                try:"),
            ("                if self._fseq == s0:\n                    return out", "                if True:\n                    return out")],
           "never read as missing"),
    "m3": ([("                    if (e.args and isinstance(e.args[0], dict)) or self._fseq == s0:", "                    if True:")],
           "cut short under it"),
    "h3": ([("(now - max(0, int(g(\"window\"))) if g(\"window\") else None)", "None")], "the panel's own clock"),
    "i3": ([("            if first and since < first:  ", "            if False:  ")], "where history does"),
    "l3": ([("        return self._consistent(lambda: self._series(qs, now))   # the same gap as totals()",
             "        with self._flush_lock:\n            return self._series(qs, now)")], "never holds the writer up"),
    "k3": ([("            if n == 5:  ", "            if False:  "), ("            if n < 4:\n                time.sleep(0.05)\n        raise _LedgerBusy()",
             "            if n < 4:\n                time.sleep(0.05)\n        return read()")], "a slow disk"),
    "p3": ([("                    if (e.args and isinstance(e.args[0], dict)) or self._fseq == s0:", "                    if self._fseq == s0:")],
           "races a flush"),
    "n3": ([("        sgn = -1 if tail else 1", "        sgn = 1")], "summed from the day's end"),
    "o3": ([("        inside = (lambda i: i >= k) if tail else (lambda i: i < k)", "        inside = (lambda i: i > k) if tail else (lambda i: i < k)")], "summed from the day's end"),
    "e3": ([("            return rx, tx, _ld_midnight(d)\n        k = max(0,", "            return rx, tx, int(ts)\n        k = max(0,")], "no detail starts at its midnight"),
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
    check("at the ledger's first start a peer on two servers opens with BOTH counters — every deployment it found imports once",
          L.slots[s4]["o"] == [12000, 4000] and C(L, s4) == (0, 0) and not L.imports
          and not L.diag["pids"].get("p4", {}).get("not_imported"), (L.slots[s4], C(L, s4), L.imports, L.diag["pids"].get("p4")))
    R["peers"]["p4"]["targets"].append({"node": "n3", "iface": "awg0", "ip": "", "type": "awg"})   # a deployment added later
    P.roster_save(rp, R)
    ing(L, "n3", wg("awg0", ("K4", 700, 70)), T0 + 6)
    check("a known peer's deployment added after the ledger started is a baseline, never a second opening",
          L.slots[s4]["o"] == [12000, 4000] and C(L, s4) == (0, 0)
          and L.diag["pids"]["p4"].get("not_imported") == [700, 70], (L.slots[s4], C(L, s4), L.diag["pids"].get("p4")))
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
          L.slots[s4]["o"] == [12000, 4000] and C(L, s4) == (0, 0) and ("n2", "awg0", "p4") in L.recs, (L.slots[s4], C(L, s4)))


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
    lone = os.path.join(TMP, "lone")
    os.makedirs(os.path.join(lone, "history"))
    P.roster_save(os.path.join(lone, "users.json"), roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    with open(os.path.join(lone, "history", "index.json"), "w") as f:
        f.write("{not json")
    L5 = reopen(os.path.join(lone, "users.json"), T0)
    check("a lone corrupt index.json — no backup, no other file beside it — stays off too: the openings in it ARE history",
          not L5.on and "unreadable" in L5.why_off, (L5.on, L5.why_off))


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


# ── [11] the retrospective's findings ───────────────────────────────────────────────────────────────────────────────
print("[11] snapshot order, a missing or older index, a record cut short, a deleted peer's name")


def section_11():
    global L, rp
    L, rp = fresh("order", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n2", "awg0", "awg")])))
    L.ingest("n1", wg("awg0", ("K1", 1000, 100)), now=T0, mono=T0, seq=1)
    L.ingest("n1", wg("awg0", ("K1", 5000, 500)), now=T0 + 25, mono=T0 + 25, seq=3)    # the node's next sync overtook…
    L.ingest("n1", wg("awg0", ("K1", 3000, 300)), now=T0 + 26, mono=T0 + 26, seq=2)    # …the one it gave up on
    L.ingest("n2", wg("awg0", ("K2", 70, 7)), now=T0 + 27, mono=T0 + 27, seq=2)        # another node's order is its own
    L.ingest("n2", wg("awg0", ("K2", 90, 9)), now=T0 + 28, mono=T0 + 28, seq=4)
    L.ingest("n1", wg("awg0", ("K1", 6000, 600)), now=T0 + 30, mono=T0 + 30, seq=5)
    s1, s2 = slot_of(L, "p1"), slot_of(L, "p2")
    check("a snapshot older than its node's newest is dropped — never read as a restart that credits the whole counter again",
          C(L, s1) == (5000, 500) and C(L, s2) == (20, 2) and L.diag["stale_snapshots"] == 1
          and not L.diag["pids"].get("p1", {}).get("resets"), (C(L, s1), C(L, s2), L.diag["stale_snapshots"], L.diag["pids"]))

    got = []

    class Rec:
        on = True

        def ingest(self, nid, snap, now=None, mono=None, seq=None):
            got.append(seq)

        def ingest_failed(self, e):
            got.append(("failed", str(e)))
    stats = os.path.join(TMP, "order-stats")
    os.makedirs(stats)
    P.Handler.deps = {"stats_dir": stats, "node_snaps": {}, "live_samples": {}}
    real, P.LEDGER = P.LEDGER, Rec()
    try:
        P.Handler._node_sync_history(None, "n1", {"id": "n1"}, {"n1": {"id": "n1"}}, {"interfaces": {}}, 7)
    finally:
        P.LEDGER = real
    src = open(panel_path, encoding="utf-8").read()
    check("every sync carries its arrival number to the ledger — taken as its body is read",
          got == [7] and "seq = next(_SYNC_SEQ)" in src and "self._node_sync_history(nid, node, nodes, snap, seq)" in src, got)

    L, rp = fresh("noindex", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)
    L.flush()
    hd = os.path.join(TMP, "noindex", "history")
    ix = os.path.join(hd, "index.json")
    os.unlink(ix)
    L2 = reopen(rp, T0 + 3700)
    check("a MISSING index.json is recovered from its newest backup — missing is not new when the history is there",
          L2.on and [x["pid"] for x in L2.slots] == ["p1"], (L2.on, L2.why_off))
    for b in [f for f in os.listdir(hd) if f.startswith("index.json")]:
        os.unlink(os.path.join(hd, b))
    L3 = reopen(rp, T0 + 3800)
    ing(L3, "n1", wg("awg0", ("K1", 300, 0)), T0 + 3805)
    L3.flush()
    check("…and with no backup either, beside the history it indexes, the ledger stays off — never a new table over old rows",
          not L3.on and "missing" in L3.why_off and not os.path.exists(ix), (L3.on, L3.why_off))

    L, rp = fresh("oldindex", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0)
    L.flush()
    ix = os.path.join(TMP, "oldindex", "history", "index.json")
    one = open(ix).read()
    ing(L, "n1", wg("awg0", ("K1", 100, 0), ("K2", 50, 0)), T0 + 5)
    L.flush()
    with open(ix, "w") as f:
        f.write(one)                                            # an older slot table: 1 slot under a 2-slot base.bin
    L2 = reopen(rp, T0 + 10)
    check("an index.json older than the history it indexes stays off — new slots would reuse numbers the old rows hold",
          not L2.on and "older" in L2.why_off, (L2.on, L2.why_off))

    L, rp = fresh("shortw", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)       # closes bucket 10
    L.flush()
    ing(L, "n1", wg("awg0", ("K1", 350, 0)), T0 + 7200)       # closes bucket 11
    real_write, calls = P.os.write, []

    def half(fd, b):
        calls.append(len(b))
        if len(calls) == 1:
            return real_write(fd, bytes(b[:len(b) // 2]))      # the disk fills mid-record…
        raise OSError(28, "No space left on device")           # …and then refuses
    P.os.write = half
    try:
        L.flush()
    finally:
        P.os.write = real_write
    ing(L, "n1", wg("awg0", ("K1", 500, 0)), T0 + 10800)      # closes bucket 12
    L.flush()
    got = [(i, c[1][0]) for i, _n, _e, c in L._fine_buckets(L._fine_path(20260910))]
    check("a record cut short by a filling disk is cut back before the next append — every bucket after it stays readable",
          got == [(10, 100), (11, 100), (12, 150)], got)

    L, rp = fresh("badsync", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)       # closes bucket 10
    real_af = L._append_fine

    def af_badsync(fb):
        real_fsync = P.os.fsync

        def boom(fd):
            raise OSError(5, "Input/output error")
        P.os.fsync = boom
        try:
            return real_af(fb)
        finally:
            P.os.fsync = real_fsync
    L._append_fine = af_badsync
    L.flush()                                                   # written whole, then the fsync fails: requeued
    L._append_fine = real_af
    L.flush()
    got = [(i, c[1][0]) for i, _n, _e, c in L._fine_buckets(L._fine_path(20260910))]
    check("a failed fsync is retried in place — the bucket is on disk once, never twice", got == [(10, 100)], got)

    R = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]))
    L, rp = fresh("names", R)
    ing(L, "n1", wg("awg0", ("K1", 10, 0)), T0)
    s = slot_of(L, "p1")
    R["peers"]["p1"]["title"] = "Alice's phone"
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1", 20, 0)), T0 + 5)
    del R["peers"]["p1"]
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0"), T0 + 10)
    L.flush()
    kept = json.load(open(os.path.join(TMP, "names", "history", "index.json")))["slots"][s]
    check("a deleted peer's slot keeps its LAST name — the one it was known by — not the one it was created with",
          kept["name"] == "Alice's phone" and kept["until"] == T0 + 10, kept)

    check("a custom range never walks from before 1970 (a series goes day by day)",
          L._window({"from": ["0001-01-01"], "to": ["2026-09-10"]}, T0)[0] == 19700101, L._window({"from": ["0001-01-01"], "to": ["2026-09-10"]}, T0))
    check("the debug dump goes out compressed too", "/api/traffic-ledger" in P._LEDGER_GZ, P._LEDGER_GZ)


try:
    section_11()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [11] ran to the end", False, "%s: %s" % (type(e).__name__, e))


print("[12] the review of the retrospective: backups, today's buckets, imports, a file's first write, a rewrite, the window")


def section_12():
    global L, rp
    L, rp = fresh("badbak", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)
    L.flush()
    hd = os.path.join(TMP, "badbak", "history")
    ix = os.path.join(hd, "index.json")
    good = open(ix).read()
    for b in [f for f in os.listdir(hd) if f.startswith("index.json")]:
        os.unlink(os.path.join(hd, b))
    open(ix + ".bak.100", "w").write(good)                      # an older, good backup…
    open(ix + ".bak.200", "w").write("null")                    # …under a newer one that parses and holds nothing
    L2 = reopen(rp, T0 + 3700)
    check("a missing index.json skips a backup that parses but holds no slot table, and takes the good one under it",
          L2.on and [x["pid"] for x in L2.slots] == ["p1"], (L2.on, L2.why_off))

    for b in [f for f in os.listdir(hd) if f.startswith("index.json")]:
        os.unlink(os.path.join(hd, b))
    open(ix, "w").write("{not json")                            # a CORRUPT primary this time…
    open(ix + ".bak.100", "w").write(good)
    open(ix + ".bak.200", "w").write("{}")                      # …under a newest backup that parses and holds nothing
    L2 = reopen(rp, T0 + 3700)
    check("a CORRUPT index.json is recovered from its newest GOOD backup — one that parses but holds no slot table is skipped",
          L2.on and [x["pid"] for x in L2.slots] == ["p1"], (L2.on, L2.why_off))

    L, rp = fresh("finewide", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0)
    L.flush()
    hd = os.path.join(TMP, "finewide", "history")
    ix = os.path.join(hd, "index.json")
    one = open(ix).read()                                      # one slot
    ing(L, "n1", wg("awg0", ("K1", 100, 0), ("K2", 50, 0)), T0 + 5)
    ing(L, "n1", wg("awg0", ("K1", 150, 0), ("K2", 90, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 160, 0), ("K2", 95, 0)), T0 + 3600)   # closes bucket 10: slot 1 is in today's fine file
    L.flush()
    open(ix, "w").write(one)
    for f in os.listdir(hd):
        if f.startswith("base.bin"):
            os.unlink(os.path.join(hd, f))                     # no base.bin, no day row yet: only today's buckets name slot 1
    L2 = reopen(rp, T0 + 3700)
    check("an index.json older than the newest fine buckets stays off too — and says what to do when no newer one exists",
          not L2.on and "older" in L2.why_off and "aside" in L2.why_off, (L2.on, L2.why_off))
    L3 = reopen(rp, T0 + 86400)
    check("…and after midnight, before the day's row is written, the newest fine buckets are yesterday's: still off",
          not L3.on and "older" in L3.why_off, (L3.on, L3.why_off))

    R = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [(5, "awg0", "awg")]),
               peer("p3", "u1", "K3", [("n1", "awg1", "awg")]), peer("p4", "u1", "K4", [(["n1"], "awg0", "awg")]))
    L, rp = fresh("oddnode", R)
    err = None
    try:
        ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0)           # a list is unhashable: the map build raised in every sync
        L.flush()                                              # …and an int beside a string stopped the imports sort
    except Exception as e:
        err = e
    ix = os.path.join(TMP, "oddnode", "history", "index.json")
    check("a roster target whose node is not a string names no counter — the ledger keeps reading and writing",
          err is None and os.path.exists(ix) and not L.diag.get("ingest_errors") and C(L, slot_of(L, "p1")) == (0, 0)
          and all(isinstance(v, str) for k in L.imports for v in k), (err, L.diag, L.imports))

    L, rp = fresh("firstw", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)       # closes bucket 10
    fp = L._fine_path(20260910)
    open(fp, "wb").close()                                     # its first write never finished: an empty file
    L._tails.pop(fp, None)
    L.flush()
    hd = os.path.join(TMP, "firstw", "history")
    got = [(i, c[1][0]) for i, _n, _e, c in L._fine_buckets(fp)]
    check("a file whose first write never finished starts again — not moved aside as corrupt at every retry",
          got == [(10, 100)] and not [f for f in os.listdir(hd) if ".corrupt." in f], (got, os.listdir(hd)))

    L, rp = fresh("dayfsync", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 86400)     # 2026-09-11: day 10's row is queued
    L.flush()
    ing(L, "n1", wg("awg0", ("K1", 300, 0)), T0 + 2 * 86400)  # 2026-09-12: day 11's row is queued
    real_ad = L._append_day

    def ad_badsync(dr):
        real_fsync = P.os.fsync

        def boom(fd):
            raise OSError(5, "Input/output error")
        P.os.fsync = boom
        try:
            return real_ad(dr)
        finally:
            P.os.fsync = real_fsync
    L._append_day = ad_badsync
    L.flush()                                                   # day 11's row written whole, its fsync fails: requeued
    L._append_day = real_ad
    L.flush()                                                   # the retry finds the row on disk and writes nothing
    ing(L, "n1", wg("awg0", ("K1", 400, 0)), T0 + 3 * 86400)  # 2026-09-13: day 12's row
    L.flush()
    got = sorted(L._day_rows(L._day_path(20260910)))
    check("a day row whose fsync failed stays on disk — the next day's row never lands on it",
          got == [20260910, 20260911, 20260912], got)

    err = None
    try:
        L._window({"from": ["0001-01-01"], "to": ["1969-12-31"]}, T0)
    except ValueError as e:
        err = e
    err2 = None
    try:
        L._window({"from": ["2030-01-01"], "to": ["2030-01-31"]}, T0)
    except ValueError as e:
        err2 = e
    check("a custom range with no day between 1970 and today is refused — never an inverted window", err is not None and err2 is not None,
          (err, err2))

    r = L.series({"range": ["custom"], "from": ["2026-08-01"], "to": ["2026-08-15"], "id": ["p1"]}, T0 + 3 * 86400)
    check("a series of a window before the ledger began is empty — never an inverted window",
          r["from"] <= r["to"] and r["since"] <= r["until"] and r["points"] == [], (r["from"], r["to"], r["points"]))

    L, rp = fresh("empty", roster())
    r = L.series({"range": ["all"], "id": ["p1"]}, T0)
    check("an empty ledger's series walks no day before today (not 20,000 days from 1970)",
          r["from"] == 20260910 and r["points"] == [], (r["from"], r["points"]))


try:
    section_12()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [12] ran to the end", False, "%s: %s" % (type(e).__name__, e))


print("[13] P2's server half: the resolution from the next day, owner names, rows per (peer, owner), the OFF sweep, usage")


def section_13():
    global L, rp
    # the resolution: saved mid-day, today keeps its step; the next day takes the new one; a restart today keeps today's
    L, rp = fresh("resol", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 100, 0)), T0 + 60)
    L.configure({"history_resolution": 900, "infinite_history": True})
    ing(L, "n1", wg("awg0", ("K1", 200, 0)), T0 + 3600)        # closes 10:00–11:00 at 1 h
    ing(L, "n1", wg("awg0", ("K1", 300, 0)), T0 + 7200)
    L.flush()
    L2 = P.TrafficLedger()                                      # a restart with the new resolution already saved
    L2.start({"roster_path": rp, "panel_settings": {"history_resolution": 900}}, now=T0 + 7300, writer=False)
    check("a resolution saved mid-day, or a restart after it, keeps today's step — nothing of today's graph is dropped",
          L.step == 3600 and L2.step == 3600 and not L.diag.get("fine_dropped") and L2.step_next == 900, (L.step, L2.step, L.diag.get("fine_dropped")))
    ing(L, "n1", wg("awg0", ("K1", 400, 0)), T0 + 86400)       # 2026-09-11, 10:00
    ing(L, "n1", wg("awg0", ("K1", 500, 0)), T0 + 86400 + 1000)
    L.flush()
    hd = L._fine_head(L._fine_path(20260911)) if os.path.exists(L._fine_path(20260911)) else None
    check("…the next day starts at the new one", L.step == 900 and hd and hd[0] == 900 and L.idx == 41, (L.step, hd, L.idx))

    # owner names and rows per (peer, owner)
    R = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u2", "K2", [("n1", "awg0", "awg")]))
    R["users"] = {"u1": {"id": "u1", "name": "Anna"}, "u2": {"id": "u2", "name": "Boris"}}
    L, rp = fresh("owners", R)
    ing(L, "n1", wg("awg0", ("K1", 0, 0), ("K2", 0, 0)), T0)
    ing(L, "n1", wg("awg0", ("K1", 1000, 100), ("K2", 50, 5)), T0 + 60)
    R["users"]["u1"]["name"] = "Anna K"
    R["peers"]["p1"]["user_id"] = "u2"                           # p1 handed to Boris
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1", 1500, 150), ("K2", 60, 6)), T0 + 120)
    ing(L, "n1", wg("awg0", ("K1", 1700, 170), ("K2", 60, 6)), T0 + 180)
    del R["users"]["u1"]
    P.roster_save(rp, R)
    ing(L, "n1", wg("awg0", ("K1", 1700, 170), ("K2", 60, 6)), T0 + 240)
    s0 = [x for x in L.slots if x["pid"] == "p1"][0]
    check("a slot keeps its owner's LAST name — renamed, then the user deleted", s0.get("on") == "Anna K", s0)
    q = {"range": ["today"]}
    by_slot = L.totals({**q, "by": ["slot"]}, T0 + 240)["rows"]
    by_user = {r["id"]: (r["rx"], r["tx"]) for r in L.totals({**q, "by": ["user"]}, T0 + 240)["rows"]}
    by_peer = {r["id"]: (r["rx"], r["tx"]) for r in L.totals({**q, "by": ["peer"]}, T0 + 240)["rows"]}
    sl = {(r["id"], r["owner"]): r for r in by_slot}
    agg_u, agg_p = {}, {}
    for r in by_slot:
        u = agg_u.setdefault(r["owner"], [0, 0]); u[0] += r["rx"]; u[1] += r["tx"]
        pp = agg_p.setdefault(r["id"], [0, 0]); pp[0] += r["rx"]; pp[1] += r["tx"]
    check("rows per (peer, owner) add up to the per-user and the per-peer rows — the grids and the user view agree",
          {k: tuple(v) for k, v in agg_u.items()} == by_user and {k: tuple(v) for k, v in agg_p.items()} == by_peer
          and sl[("p1", "u1")]["rx"] == 1000 and sl[("p1", "u2")]["rx"] == 700 and sl[("p1", "u1")]["until"] == T0 + 120
          and sl[("p1", "u1")]["owner_name"] == "Anna K" and sl[("p1", "u2")]["until"] is None, (by_slot, by_user, by_peer))
    check("every row says since when it is counted", all(r.get("since") for r in by_slot)
          and sl[("p1", "u2")]["since"] == T0 + 120, [(r["id"], r["owner"], r["since"]) for r in by_slot])

    # a group's graph is its members' graphs added together (the route resolves `members` from the roster)
    ssum = lambda sr_: (sum(x[2] for x in sr_["points"]), sum(x[3] for x in sr_["points"]))
    su1 = ssum(L.series({**q, "by": ["user"], "id": ["u1"]}, T0 + 240))
    su2 = ssum(L.series({**q, "by": ["user"], "id": ["u2"]}, T0 + 240))
    sg = ssum(L.series({**q, "by": ["group"], "id": ["g1"], "members": ["u1,u2"]}, T0 + 240))
    s0g = L.series({**q, "by": ["group"], "id": ["g0"], "members": [""]}, T0 + 240)
    su1m = ssum(L.series({**q, "by": ["user"], "id": ["u1"], "members": ["u2"]}, T0 + 240))
    check("a group's graph is its members' added together; an empty group draws nothing; `members` means nothing to by=user",
          sg == (su1[0] + su2[0], su1[1] + su2[1]) and sg[0] > 0 and not s0g["points"] and su1m == su1, (su1, su2, sg, s0g["points"], su1m))

    # the newest slot of a (peer, owner) pair names it: unassign and back
    R2 = roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]))
    L, rp = fresh("reowned", R2)
    ing(L, "n1", wg("awg0", ("K1", 10, 0)), T0)
    R2["peers"]["p1"]["user_id"] = None; R2["peers"]["p1"]["title"] = "phone"
    P.roster_save(rp, R2)
    ing(L, "n1", wg("awg0", ("K1", 20, 0)), T0 + 60)
    R2["peers"]["p1"]["user_id"] = "u1"; R2["peers"]["p1"]["title"] = "Anna's phone"
    P.roster_save(rp, R2)
    ing(L, "n1", wg("awg0", ("K1", 30, 0)), T0 + 120)
    r = [x for x in L.totals({"range": ["today"], "by": ["slot"]}, T0 + 130)["rows"] if x["owner"] == "u1"][0]
    check("the newest slot of a pair names it, and says it is open", r["name"] == "Anna's phone" and r["until"] is None
          and r["slots"] == 2, r)

    # the OFF sweep: 75 days of history (10 Sep – 23 Nov), then off on 24 Nov: the cutoff is 22 Oct — the DETAIL of every
    # day before it goes; no day row is touched, so every total for every window stays exactly what it was
    L, rp = fresh("sweep", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
    L._sweep_ok = lambda: True                                  # a synthetic calendar: the clock-held gate has its own checks
    t = T0
    ing(L, "n1", wg("awg0", ("K1", 0, 0)), t)
    v = 0
    for day in range(75):
        for h in (0, 3600):
            v += 100
            ing(L, "n1", wg("awg0", ("K1", v, 0)), t + day * 86400 + h)
        L.flush()
    now = t + 75 * 86400                                        # 2026-11-24
    ing(L, "n1", wg("awg0", ("K1", v + 100, 0)), now)
    L.flush()
    hd = os.path.join(TMP, "sweep", "history")
    life0 = life(L, "p1")
    L._usage = (0.0, None)
    u0 = L.usage(now=now)
    wins = [("2026-09-10", "2026-09-10"), ("2026-09-12", "2026-09-20"), ("2026-09-20", "2026-10-10"), ("2026-10-21", "2026-10-23"),
            ("2026-09-01", "2026-11-24"), ("2026-11-01", "2026-11-24")]
    tot = lambda f_, t_: {r["id"]: (r["rx"], r["tx"]) for r in L.totals({"from": [f_], "to": [t_]}, now)["rows"]}.get("p1")
    tot0 = {w: tot(*w) for w in wins}
    ser0 = L.series({"from": ["2026-09-12"], "to": ["2026-09-18"], "id": ["p1"]}, now)["points"]
    before = {f: os.path.getsize(os.path.join(hd, f)) for f in os.listdir(hd)}
    days0 = {f: open(os.path.join(hd, f), "rb").read() for f in before if f.startswith("day-")}
    L.configure({"infinite_history": False, "history_resolution": 3600})
    L.flush()
    after = set(os.listdir(hd))
    removed = {f: b for f, b in before.items() if f not in after}
    cutoff = P._ld_of(P._ld_date(20261124) - P._ldt.timedelta(days=P.LEDGER_KEEP_DAYS))
    check("the OFF sweep deletes exactly what the read-out named — the fine files of the days before the cutoff, bytes and days",
          cutoff == 20261022 and removed and sum(removed.values()) == u0["sweep_bytes"] and u0["sweep_days"] == len(removed)
          and all(f.startswith("fine-") and int(f[5:15].replace("-", "")) < cutoff for f in removed)
          and not any(f.startswith("fine-") and int(f[5:15].replace("-", "")) < cutoff for f in after),
          (sorted(removed)[:3], len(removed), u0["sweep_bytes"], u0["sweep_days"]))
    check("…and never a day row: every day file is byte-for-byte what it was",
          all(os.path.exists(os.path.join(hd, f)) and open(os.path.join(hd, f), "rb").read() == b for f, b in days0.items()),
          sorted(days0))
    check("every total for every window is exactly what it was — a week months back included",
          {w: tot(*w) for w in wins} == tot0, ({w: tot(*w) for w in wins}, tot0))
    check("the lifetime survives the sweep", life(L, "p1") == life0, (life(L, "p1"), life0))
    ser1 = L.series({"from": ["2026-09-12"], "to": ["2026-09-18"], "id": ["p1"]}, now)["points"]
    check("an old week's graph still draws — a bar a day from the day rows, the same bytes as its hours drew",
          ser1 and all(pt[1] >= 86000 for pt in ser1) and sum(pt[2] for pt in ser1) == sum(pt[2] for pt in ser0),
          (ser1[:2], sum(pt[2] for pt in ser1), sum(pt[2] for pt in ser0)))
    L._usage = (0.0, None)
    u1 = L.usage(now=now)
    du = sum(os.path.getsize(os.path.join(hd, f)) for f in os.listdir(hd))
    check("the size read-out equals du of the history directory", u1["bytes_ledger"] == du, (u1["bytes_ledger"], du))


def section_13b():
    def history(tag, days):
        L, rp = fresh(tag, roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")])))
        v = 0
        ing(L, "n1", wg("awg0", ("K1", 0, 0)), T0)
        for day in range(days):
            v += 100
            ing(L, "n1", wg("awg0", ("K1", v, 0)), T0 + day * 86400)
            ing(L, "n1", wg("awg0", ("K1", v + 50, 0)), T0 + day * 86400 + 3600)
            v += 50
            L.flush()
        return L, rp, os.path.join(TMP, tag, "history"), v

    # a full disk does not hold the sweep back — it is the case the switch is most needed for
    L, rp, hd, v = history("fulldisk", 75)
    L._sweep_ok = lambda: True
    L.configure({"infinite_history": False})
    real_ok = P.stats_disk_ok
    P.stats_disk_ok = lambda d: False
    try:
        L.flush()
    finally:
        P.stats_disk_ok = real_ok
    left = [f for f in os.listdir(hd) if f.startswith("fine-2026-09")]
    check("a full disk does not hold the OFF sweep back — it is the case the switch is most needed for", not left, left)

    # a fine file deleted while a series reads it: the day draws from its row, nothing raises
    fp = L._fine_path(20260915)
    real_exists = P.os.path.exists
    P.os.path.exists = lambda x: True if x == fp else real_exists(x)
    err = None
    try:
        sr = L.series({"from": ["2026-09-14"], "to": ["2026-09-16"], "id": ["p1"]}, T0 + 75 * 86400)
    except Exception as e:
        err, sr = e, None
    finally:
        P.os.path.exists = real_exists
    check("a fine file the sweep deleted under a series read is no error — that day draws from its row",
          err is None and sr and len(sr["points"]) == 3, (err, sr and sr["points"]))
    real_head = L._fine_head
    L._fine_head = lambda x: (3600, 0, P._ld_midnight(20260915)) if x == fp else real_head(x)   # the header read, then the file went
    P.os.path.exists = lambda x: True if x == fp else real_exists(x)
    err = None
    try:
        sr = L.series({"from": ["2026-09-14"], "to": ["2026-09-16"], "id": ["p1"]}, T0 + 75 * 86400)
    except Exception as e:
        err, sr = e, None
    finally:
        L._fine_head = real_head
        P.os.path.exists = real_exists
    tt = {r["id"]: r["rx"] for r in L.totals({"from": ["2026-09-14"], "to": ["2026-09-16"]}, T0 + 75 * 86400)["rows"]}.get("p1")
    check("…and one deleted between its header and its buckets draws that day from its row — the graph still equals the total",
          err is None and sr and sum(pt[2] for pt in sr["points"]) == tt and len(sr["points"]) == 3, (err, sr and sr["points"], tt))

    # a sweep held back (a new day, a restart) is kicked once the day has held — at 1-day resolution nothing else wakes it
    L._sweep_due, L.infinite, L._kick = True, False, False
    L._sweep_ready = lambda d, m: True
    L.q_fine, L.q_day, L.prompt, L.d_index = [], [], False, False
    ing(L, "n1", wg("awg0", ("K1", v, 0)), T0 + 74 * 86400 + 3600 + 10)   # inside the same bucket: nothing else to write
    check("a sweep held back is kicked once the day has held — nothing else would wake the writer", L._kick, L._kick)
    L._kick, L.observed = False, False
    ing(L, "n1", wg("awg0"), T0 + 74 * 86400 + 3600 + 12)          # nothing read: this process has observed nothing
    k1 = L._kick
    L.observed, L._retry_at = True, T0 + 74 * 86400 + 3600 + 14 + 300    # the ingest's monotonic clock here is the test's
    ing(L, "n1", wg("awg0", ("K1", v, 0)), T0 + 74 * 86400 + 3600 + 14)   # …or a failed write's pause is running
    k2 = L._kick
    L._retry_at = 0.0
    check("…and wakes nothing in a process that observed nothing, or during a failed write's pause", not k1 and not k2, (k1, k2))

    # a damaged day row is skipped — never the place a month file is cut (day rows are the totals)
    dp = L._day_path(20260915)
    L.flush()
    rows = L._day_rows(dp)
    o, ns = rows[20260915]
    raw = bytearray(open(dp, "rb").read())
    raw[o + P._LD_ROW.size + 3] ^= 0xFF                         # a bit flip inside day 15's row
    open(dp, "wb").write(bytes(raw))
    L._tails.pop(dp, None); L._rowidx.pop(dp, None)
    end = L._valid_end(dp, P._LD_MAGIC)
    later = sorted(d for d in L._day_rows(dp) if d > 20260915)
    L._append_day((20260931 if False else 20260930, 0, 0, P._larr.array("Q"), P._larr.array("Q")))   # a re-close: skipped
    L._rowidx.pop(dp, None)
    check("a damaged day row is skipped, never the place the month is cut — every later day's row stays",
          end == len(raw) and later and later[0] == 20260916 and later[-1] == 20260930
          and 20260915 not in L._day_rows(dp), (end, len(raw), later[:2], later[-1:]))

    # a flipped width (the row header carries no checksum) and a zero-filled tail: not ours — kept aside, never cut
    for tag, mutate in (("nsflip", lambda b, o: b.__setitem__(slice(o + 16, o + 20), (70000).to_bytes(4, "little"))),
                        ("zerotail", None)):
        L2, rp2, hd2, v2 = history(tag, 40)
        dp2 = L2._day_path(20260915)
        raw2 = bytearray(open(dp2, "rb").read())
        rows2 = L2._day_rows(dp2)
        if mutate:
            mutate(raw2, rows2[20260920][0])                    # day 20's nslots → far past the file's end
        else:
            raw2 += bytes(P._LD_ROW.size + 16)                  # a crash left zeros where a row would be
        open(dp2, "wb").write(bytes(raw2))
        L2._tails.pop(dp2, None); L2._rowidx.pop(dp2, None)
        L2._valid_end(dp2, P._LD_MAGIC)
        kept = [f for f in os.listdir(hd2) if f.startswith("day-2026-09.bin.corrupt.")]
        got = sorted(L2._day_rows(dp2))
        want = [d for d in sorted(rows2) if d < 20260920] if mutate else sorted(rows2)
        check("a row that cannot be ours (%s) is never cut past: the file is kept aside, its readable rows go on, no row 0" % tag,
              kept and got == want and 0 not in got and len(open(os.path.join(hd2, kept[0]), "rb").read()) == len(raw2),
              (kept, got[-2:], want[-2:]))
    L2, rp2, hd2, v2 = history("torntail", 40)                      # …while a real torn tail (a crash mid-append) is still cut
    dp2 = L2._day_path(20260915)
    raw2 = open(dp2, "rb").read()
    rows2 = L2._day_rows(dp2)
    open(dp2, "wb").write(raw2[:len(raw2) - 5])                   # the last row's payload cut short
    L2._tails.pop(dp2, None); L2._rowidx.pop(dp2, None)
    end2 = L2._valid_end(dp2, P._LD_MAGIC)
    check("…and a real torn tail is still cut back, nothing kept aside",
          end2 == rows2[max(rows2)][0] and not [f for f in os.listdir(hd2) if ".corrupt." in f]
          and sorted(L2._day_rows(dp2)) == sorted(rows2)[:-1], (end2, rows2[max(rows2)][0]))

    # a clock that jumped 60 days ahead for one sync: nothing is deleted until real time reaches the ledger's day
    L, rp, hd, v = history("jump", 40)
    before = sorted(os.listdir(hd))
    L.configure({"infinite_history": False})
    ing(L, "n1", wg("awg0", ("K1", v + 10, 0)), T0 + 100 * 86400)   # the clock jumps 60 days ahead for one sync
    L._day_mono = time.monotonic() - P.LEDGER_SWEEP_HOLD_S - 1        # …and that day has "held": only the real clock objects
    L.flush()
    kept = [f for f in before if f.startswith("fine-")]
    check("a clock that jumped ahead never deletes: the sweep waits for a day the real clock has held",
          all(f in os.listdir(hd) for f in kept) and L._sweep_due, (len(kept), L._sweep_due))
    real_today = P._ld_day(time.time())[0]
    L.day, L._day_mono, L._sweep_at = real_today, time.monotonic(), 0.0
    held_short = L._sweep_ok()
    L._day_mono = time.monotonic() - P.LEDGER_SWEEP_HOLD_S - 1
    check("…the day must equal the real clock's AND have held for ten minutes", not held_short and L._sweep_ok(), held_short)

    # a second panel process on the same state dir never deletes (it observed nothing)
    L, rp, hd, v = history("second", 75)
    L2 = reopen(rp, T0 + 75 * 86400)
    L2._sweep_ok = lambda: True
    L2.configure({"infinite_history": False})
    before = sorted(os.listdir(hd))
    L2.flush()
    check("a process that observed nothing never sweeps (a second panel on the state dir)", sorted(os.listdir(hd)) == before, "")


# ── [14] P3: a rolling window over the ledger (the Overview's Top talkers) ────────────────────────────────────────
print("[14] P3: a rolling window — whole days from the rows, the first day's part from its buckets, nodes, top")


def section_14():
    L, rp = fresh("roll", roster(peer("p1", "u1", "K1", [("n1", "awg0", "awg")]), peer("p2", "u1", "K2", [("n2", "awg0", "awg")]),
                                  peer("p3", "u2", "K3", [("n1", "awg0", "awg")]), peer("p4", "u2", "K4", [("n2", "awg0", "awg"), ("n3", "awg0", "awg")])))
    day0 = calendar.timegm((2026, 9, 10, 0, 0, 0))
    ing(L, "n1", wg("awg0", ("K1", 0, 0), ("K3", 0, 0)), day0 + 30 * 60)
    ing(L, "n2", wg("awg0", ("K2", 0, 0), ("K4", 0, 0)), day0 + 30 * 60)   # p4 is on n2 and n3; n3 never reports
    per = {}                                       # hour index from day0 → (p1 rx, p2 rx); p1 tx = rx // 10; p3 never moves
    c1 = c2 = 0
    for h in range(1, 44):                         # a reading at hh:30 credits bucket hh
        d1, d2 = 1000 * h, 7 * h
        per[h] = (d1, d2); c1 += d1; c2 += d2
        t = day0 + h * 3600 + 30 * 60
        ing(L, "n1", wg("awg0", ("K1", c1, c1 // 10), ("K3", 0, 0)), t)
        ing(L, "n2", wg("awg0", ("K2", c2, 0)), t)
        if h == 30:
            L.flush()                               # hours 31.. stay queued: closed buckets waiting for their write
    now = day0 + 43 * 3600 + 40 * 60              # 11 Sep 19:40
    tot = lambda **kw: L.totals({k: [str(v)] for k, v in kw.items()}, now=now)
    r = tot(since=now - 3600)                       # 18:40 → the bucket holding it, 18:00
    rows = {x["id"]: (x["rx"], x["tx"]) for x in r["rows"]}
    want = sum(per[h][0] for h in (42, 43))
    check("[14] a rolling window starts at the bucket holding `since` — widened, never cut — and says where",
          r["since"] == day0 + 42 * 3600 and rows.get("p1", (0,))[0] == want, (r["since"] - day0, rows.get("p1"), want))
    check("[14] …closed buckets still waiting for their write are in it", rows.get("p2", (0,))[0] == sum(per[h][1] for h in (42, 43)),
          rows.get("p2"))
    for sn in (now - 3600, now - 5 * 3600, day0 + 20 * 3600 + 10 * 60, day0 + 3 * 3600):   # late and early starts, both days
        a_ = {x["id"]: (x["rx"], x["tx"]) for x in tot(since=sn)["rows"]}
        L._tail_ok = False
        b_ = {x["id"]: (x["rx"], x["tx"]) for x in tot(since=sn)["rows"]}
        L._tail_ok = True
        check("[14] a window start summed from the day's end equals it summed from the day before (since −%d s)" % (now - sn), a_ == b_, (a_, b_))
    r = tot(since=day0 + 20 * 3600 + 10 * 60)      # 10 Sep 20:10 → 20:00 yesterday, then all of today
    rows = {x["id"]: x["rx"] for x in r["rows"]}
    check("[14] a window reaching into the day before: its part from its buckets, the rest from the day before's row",
          rows.get("p1") == sum(per[h][0] for h in range(20, 44)), (rows.get("p1"), sum(per[h][0] for h in range(20, 44))))
    ref = {x["id"]: x["rx"] for x in L.totals({"range": ["custom"], "from": ["2026-09-11"], "to": ["2026-09-11"]}, now=now)["rows"]}
    r = tot(since=day0 + 86400)
    check("[14] …and from a midnight it equals the day's total", {x["id"]: x["rx"] for x in r["rows"]} == ref, (r["rows"], ref))
    r = tot(since=now - 86400, by="slot"); rp_ = tot(since=now - 86400)
    byp = {}
    for x in r["rows"]:
        byp.setdefault(x["id"], [0, 0]); byp[x["id"]][0] += x["rx"]; byp[x["id"]][1] += x["tx"]
    check("[14] a rolling window by (peer, owner) — the Overview's Top talkers read these — adds up to it by peer",
          byp == {x["id"]: [x["rx"], x["tx"]] for x in rp_["rows"]} and r["since"] == rp_["since"], (byp, rp_["rows"]))
    r = tot(window=3600)
    check("[14] window=: a rolling window up to the panel's own clock (never the browser's), and the reply says what was asked",
          r.get("asked") == now - 3600 and r["since"] == day0 + 42 * 3600, (r.get("asked"), r["since"] - day0))
    r = tot(window=40 * 86400)
    check("[14] a rolling window reaching before the ledger's history starts where history does, and says so",
          r["since"] == day0 and r["from"] == 20260910, (r["since"] - day0, r["from"]))
    rost = P.roster_load(rp); del rost["peers"]["p2"]; P.roster_save(rp, rost)   # p2 deleted: its slot closes, its bytes stay
    ing(L, "n1", wg("awg0", ("K1", c1, c1 // 10), ("K3", 0, 0)), now - 30)
    r = tot(since=now - 86400, by="slot")
    check("[14] a deleted peer keeps its bytes in a rolling window (its owner's figure keeps them)",
          any(x["id"] == "p2" and x["rx"] > 0 and x["until"] for x in r["rows"]), [(x["id"], x["rx"], x["until"]) for x in r["rows"]])
    # a flush in flight has taken the closed day out of its queue and not yet written it: a read in that gap must not miss it
    import threading as _th
    G, _grp = fresh("gap", roster(peer("g1", "u1", "KG", [("n1", "awg0", "awg")])))
    ing(G, "n1", wg("awg0", ("KG", 0, 0)), day0 + 3600)
    ing(G, "n1", wg("awg0", ("KG", 5000, 500)), day0 + 7200)
    ing(G, "n1", wg("awg0", ("KG", 5100, 510)), day0 + 86400 + 600)   # past midnight: 10 Sep closes, its row queued
    gate = _th.Event(); real = G._append_day
    G._append_day = lambda dr: (gate.wait(10), real(dr))[1]
    fl = _th.Thread(target=G.flush); fl.start()
    while G._fseq % 2 == 0:
        time.sleep(0.01)
    got = {}
    rd = _th.Thread(target=lambda: got.update(r=G.api("/api/traffic-totals", {"range": ["custom"], "from": ["2026-09-10"],
                                                                                 "to": ["2026-09-10"], "by": ["peer"]})))
    rd.start(); time.sleep(0.6); gate.set(); rd.join(); fl.join()
    st, rsp = got["r"]
    rows = {x["id"]: x["rx"] for x in ((rsp.get("data") or {}).get("rows") or [])}
    check("[14] a read while a flush holds a closed day out of its queue waits for it — the day is never read as missing",
          st == 200 and rows.get("g1") == 5000, (st, rows))
    gate.clear()
    ing(G, "n1", wg("awg0", ("KG", 5200, 520)), day0 + 2 * 86400 + 600)
    fl = _th.Thread(target=G.flush); fl.start()
    while G._fseq % 2 == 0:
        time.sleep(0.01)
    st, rsp = G.api("/api/traffic-totals", {"range": ["custom"], "from": ["2026-09-11"], "to": ["2026-09-11"], "by": ["peer"]})
    st2, _r2 = G.api("/api/traffic-series", {"id": ["g1"], "by": ["peer"], "range": ["month"]})
    gate.set(); fl.join()
    check("[14] …and one the writer keeps in the way (a slow disk) is a 503 (being written), a series too — never a guess",
          st == 503 and rsp.get("code") == "busy" and st2 == 503, (st, st2))
    calls = {"n": 0}
    real_s0 = G._series
    def torn(qs, now=None):                                        # a flush replaced the file under the first read
        calls["n"] += 1
        if calls["n"] == 1:
            G._fseq += 2
            raise ValueError("bytes length not a multiple of item size")   # array.frombytes on a file cut short
        return real_s0(qs, now)
    G._series = torn
    try:
        st, rsp = G.api("/api/traffic-series", {"id": ["g1"], "by": ["peer"], "range": ["month"]})
    except Exception as e:                                         # the request handler answers it with a 500
        st, rsp = 500, repr(e)
    G._series = real_s0
    check("[14] a read a flush cut short under it is read again — never a 500 or a 400", st == 200 and calls["n"] == 2, (st, calls))
    st, rsp = G.api("/api/traffic-series", {"id": [""], "by": ["peer"], "range": ["month"]})
    check("[14] …while a refusal of the query itself is still answered at once (400)", st == 400, (st, rsp))
    real_s1 = G._series
    def racing(qs, now=None):                                      # a refusal that races a flush: the count moves under it
        G._fseq += 2
        return real_s1(qs, now)
    G._series = racing
    t0_ = time.monotonic()
    st, rsp = G.api("/api/traffic-series", {"id": [""], "by": ["peer"], "range": ["month"]})
    G._series = real_s1
    check("[14] …even when it races a flush — a refusal is never re-read into a 503", st == 400 and time.monotonic() - t0_ < 0.2,
          (st, round(time.monotonic() - t0_, 2)))
    real_s = G._series
    G._series = lambda qs, now=None: (time.sleep(1.5), real_s(qs, now))[1]   # a slow read (8 fine files of a big fleet)
    rd = _th.Thread(target=lambda: G.series({"id": ["g1"], "by": ["peer"], "range": ["month"]})); rd.start()
    time.sleep(0.2)
    ing(G, "n1", wg("awg0", ("KG", 5300, 530)), day0 + 3 * 86400 + 600)
    t0_ = time.monotonic(); G.flush(); took = time.monotonic() - t0_
    rd.join(); G._series = real_s
    check("[14] a slow read never holds the writer up — a restart's last write is never starved by a graph being drawn",
          took < 0.5, round(took, 2))
    os.unlink(L._fine_path(20260910))               # a day with no detail (1-day resolution, swept by OFF)
    r = tot(since=day0 + 20 * 3600 + 10 * 60)
    rows = {x["id"]: x["rx"] for x in r["rows"]}
    check("[14] a day with no detail starts at its midnight: the whole day, from the rows",
          r["since"] == day0 and rows.get("p1") == sum(per[h][0] for h in range(1, 44)), (r["since"] - day0, rows.get("p1")))


try:
    section_14()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [14] ran to the end", False, "%s: %s" % (type(e).__name__, e))

try:
    section_13b()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [13b] ran to the end", False, "%s: %s" % (type(e).__name__, e))

try:
    section_13()
except Exception as e:
    import traceback; traceback.print_exc()
    check("section [13] ran to the end", False, "%s: %s" % (type(e).__name__, e))

shutil.rmtree(TMP, ignore_errors=True)
if PLANT:
    want = PLANTS[PLANT][1]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
