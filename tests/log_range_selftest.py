#!/usr/bin/env python3
"""Self-test for LOGS-PLAN P3 — a time range downloaded as one file: the `logrange` leg, the parts on POST /api/node/logs,
the spool and the merge, the download route, redaction, the reader both programs run (docs/LOGS-PLAN.md §3, §5, §6, §26).

  [1] The wire, against real panels: an idle fleet's sync reply is byte-identical to the build before P3 (ef9c309); a range
      reaches only the nodes it names, under `logrange` and never under P2's `logs` (a P2 node would follow it live), and
      only while it waits on that node.
  [2] The parts: a node's progress, then numbered parts with the request's key, from the node token its sync came with
      (q189 F1: the panel reads a log post's body only from a token a reply handed a request's key to); a repeat is kept
      once, a part out of order is 409, a new part 0 starts that server afresh; a wrong key 403, a gone request 404; at
      most 4 range posts at a time (503); the download: an attachment, gzip on the wire to a browser that takes it, the
      same text unpacked otherwise, 404 for an unknown id, never through api() and never on a node door.
  [3] The store: at most 2 in progress (a 3rd 429); each server's share is the total divided; a server the panel has not
      heard from is asked and reads "offline"; an old node "old", a silent one "noanswer", a stalled one "failed", a request
      past its life "timeout"; "make the file now" leaves the rest out; an unpolled request goes, a made file goes after
      its keep, 4 files at most; the spool is emptied at start.
  [4] The file: every server's lines merged by time on the panel's clock (a skewed node corrected); the §5 header with
      what is not whole and why; redaction of 32-byte keys (exactly), Bearer and swgp_ tokens, and none when unticked;
      a message's newlines kept.
  [5] The reader (one block, byte-identical in swg-noded and swg-panel-server): the ring keeps the NEWEST share and counts
      what it cut; journalctl once (no -f) between two times, -p for the levels, OR-ed matches; a file's .1 first, both
      filtered by time; sources merged in time order, levels and sources filtered; a container read with since/until and
      no follow; the oldest line kept.
  [6] The node: a thread per range (never the sync loop), niced; a range the reply drops stops; a finished one is not read
      again; parts numbered with `done` last; a 409 starts the parts again from 0; the read is shifted by the clock offset;
      the snapshot says `log.range`.
  [7] The SPA: the file is saved from a plain link to the download route (no Blob); every string has its Russian.

Run: python3 tests/log_range_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     replyidle    an idle reply carries `logrange`               inlogs       a range rides P2's `logs`
     replydone    a server that is done is still asked           nokey        any key is accepted
     noorder      a part out of order is taken                   repeatdup    a repeated part is written twice
     norestart    a new part 0 is appended, not a fresh start    noslots      range posts are not bounded
     maxreq       a 3rd download is taken                        evenshare    one server gets the whole total
     unknowndrop  a node the panel has not heard from is dropped nostall      a stalled server is waited on for ever
     nolife       a request past its life is not made            noabandon    an unpolled request stays
     nokeep       a made file stays for ever                     nowipe       the spool survives a restart
     unsorted     the merge is not by time                       noskew       a skewed node's lines are not corrected
     noredact     nothing is masked                              keyloose     a 44-char string that is no 32-byte key is masked
     redactalways an unticked box still masks                    nowhy        the header does not say what is missing
     dlattach     the download is not an attachment              dlplainlen   the unpacked download states the gzip length
     ringoldest   the ring keeps the oldest part                 ringcount    the ring does not count what it cut
     follow       the range journalctl follows (-f)              nodotone     a file's .1 is not read
     timefilter   lines outside the range are kept               levelfilter  the level chips are not applied
     ctrfollow    a container is followed, not read to `until`   nodedone     a finished range is read again
     node409      a 409 is not answered by starting again        nodenice     the node's read is not niced
     nodeclock    the read is not shifted by the clock offset    nodeflag     the snapshot does not say `log.range`
     nodestop     a range the reply drops reads on               spablob      the SPA builds the file as a Blob
   the code review's fixes ([8]):
     nodepartcap  a part of short lines passes the panel's line cap    silentcap  lines past the cap are not counted
     makerace     the make reads a part still being written            paneltrunc the panel's own read writes after a make
     nobeat       a long scan posts no progress (read as "failed")     makeleak   a stopped make leaves its .part
     onelock      one server's write holds every other server's        droplocked the sync reply deletes files under the lock
     unitmix      the disk guard counts bytes against the node's characters
     spatotal     the progress counts the servers chosen now           spaclose   Close shows the form again
   the re-check's fixes ([9]):
     beatslot     a progress post waits for an upload slot (and is refused) dropnowait a close deletes under a writer
     lateread     a late progress post overwrites a finished server's count  panelrevive the panel's read revives a skipped entry
     beatgone     a "gone" heartbeat does not stop the read            spaoff     a range tells you to pick a level for the past
   the source dropdowns ([7]):
     mpnowild     a whole group is written as its items, not its wildcard (200 nodes: one source becomes hundreds)
     mpclobber    a choice in one dropdown drops the others' choices
   the redesign's review ([10]):
     nomigrate    a remembered iface:* / iface:swg_… is kept as it was (mesh lines silently stop)
     popunder     Escape in a dropdown also leaves full screen
     popbubble    the shared hook's Escape listens in the bubble phase (the gate read a Sheet's line instead)
   the refactor's re-check ([11]):
     nofocusin    focus moving on (where a click focuses no button) leaves the list open
     imeesc       Escape ends an IME composition's list too
     keepesc      Escape in a form the list owns leaves the list open
   the header's Logs button ([12]):
     overlayeager the viewer is mounted (and polls) before the button is clicked
     rowkey       a row's key is node + seq: a reopen (seq from 1 again) repeats keys still on screen
     tieseq       lines at the same time are ordered by seq, which restarts with each request
     cardstop     the Settings card's full screen offers Stop, not "leave full screen" (the card streams on)
   one viewer, asked for ([10], [13]; the whole-feature analysis §32 and the header button's review):
     lvzabove     the full-screen viewer covers the app's sheets and confirms (z above the modal layer)
     autostart    opening Settings → Logs streams before "Start live log"
     deepnav      a deep link navigates to Settings under the viewer instead of opening over its page
     notrap       Tab walks out of the full-screen viewer into the page hidden under it
     nofocusback  Exit drops the focus on <body>
   q189 F1 ([2]):
     rangetok     a range's sync reply does not hand its node token to the request (every range post refused 401)
"""
import gzip, importlib.machinery, importlib.util, io, json, os, re, socket, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROG = {k: os.path.join(ROOT, f) for k, f in (("noded", "swg-noded"), ("panel", "swg-panel-server"),
                                              ("spa", "js/logview.js"), ("ru", "js/lang/ru.js"), ("ui", "js/ui.js"),
                                              ("css", "app.css"))}
REF = "ef9c309"                                  # the last build before P3: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
TMP = tempfile.mkdtemp(prefix="logrange-")
os.environ["SWG_LOG_LEVEL_FILE"] = os.path.join(TMP, "none", "log-level")
KEY = "x8Yk3mZrJ1o2bS6c9w0tQyFvHn5LdPqWaE7uRgTzKjI="          # a 32-byte key's shape: the 43rd character ends in 00
NOTKEY = "x8Yk3mZrJ1o2bS6c9w0tQyFvHn5LdPqWaE7uRgTzKjB="       # 44 characters, but no 32 bytes encode to it


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""),
          flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {   # (program, anchor, replacement)
    "replyidle": ("panel", '''                                **({"logrange": _lrange} if _lrange else {}),''',
                  '''                                "logrange": _lrange or [],'''),
    "inlogs": ("panel", '''                                **({"logs": _live} if _live else {}),''',
               '''                                **({"logs": (_live or []) + (_lrange or [])} if _live or _lrange else {}),'''),
    "replydone": ("panel", '''ns["state"] not in ("waiting", "reading", "sending"):''', '''ns["state"] not in ("waiting", "reading", "sending", "done"):'''),
    "nokey": ("panel", '''        nid = _log_post_node(rec, key)
        if nid is None:
            return 403, {"ok": False, "error": "not this request's key", "code": "forbidden"}
        ns = rec["ns"][nid]''', '''        nid = key.split(".", 1)[0]
        if nid not in rec["nodeset"]:
            return 403, {"ok": False, "error": "not this request's key", "code": "forbidden"}
        ns = rec["ns"][nid]'''),
    "noorder": ("panel", '''            if seq > want:
                return 409,''', '''            if False:
                return 409,'''),
    "repeatdup": ("panel", '''            if 0 < seq < want or (seq == 0 and want and ns["state"] == "done"):''', '''            if False:'''),
    "norestart": ("panel", '''    with open(os.path.join(rec["dir"], nid + ".gz"), "wb" if first else "ab") as f:''',
                  '''    with open(os.path.join(rec["dir"], nid + ".gz"), "ab") as f:'''),
    "rangetok": ("panel", '''            if tok:\n                rec["toks"].add(tok)\n            out.append({"id": rec["id"], "key": _live_key(rec, nid),''',
                 '''            out.append({"id": rec["id"], "key": _live_key(rec, nid),'''),
    "noslots": ("panel", '''                if not RANGE_POST_SLOTS.acquire(blocking=False):''', '''                if not RANGE_POST_SLOTS.acquire(blocking=False) and False:'''),
    "maxreq": ("panel", '''if r["phase"] in ("reading", "making")) >= RANGE_REQ_MAX\n''', '''if r["phase"] in ("reading", "making")) >= RANGE_REQ_MAX + 9\n'''),
    "evenshare": ("panel", '''"label": label, "share": RANGE_TOTAL // len(nodes),''', '''"label": label, "share": RANGE_TOTAL,'''),
    "unknowndrop": ("panel", '''                                                                           or RANGE_NODE_RE.match(n))))[:2000]''',
                    '''                                                                           )))[:2000]'''),
    "nostall": ("panel", '''        elif now - ns.get("last", now) > RANGE_STALL:''', '''        elif False:'''),
    "nolife": ("panel", '''    late = now - rec["at"] > RANGE_LIFE''', '''    late = False'''),
    "noabandon": ("panel", '''           or (r["phase"] in ("reading", "making") and now - r["polled"] > RANGE_ABANDON)]]''', ''']]'''),
    "nokeep": ("panel", '''           if (r["phase"] in ("ready", "failed") and now - max(r["made"], r["read"]) > RANGE_KEEP)''',
               '''           if False'''),
    "nowipe": ("panel", '''    d = os.path.join(state_dir or ".", "logspool")
    with contextlib.suppress(OSError):
        shutil.rmtree(d)''', '''    d = os.path.join(state_dir or ".", "logspool")'''),
    "unsorted": ("panel", '''heapq.merge(*(it(n, f) for n, f in files), key=lambda x: x[0])''', '''itertools.chain(*(it(n, f) for n, f in files))'''),
    "noskew": ("panel", '''                off = (ns_all[nid].get("off") or 0) * 1000000''', '''                off = 0'''),
    "noredact": ("panel", '''def range_redact(text):
    for rx, rep, need in _RANGE_REDACT:''', '''def range_redact(text):
    for rx, rep, need in ():'''),
    "keyloose": ("panel", '''(re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=(?![A-Za-z0-9+/=])"), "[key]", "="),''',
                 '''(re.compile(r"[A-Za-z0-9+/]{43}="), "[key]", "="),'''),
    "redactalways": ("panel", '''"redact": body.get("redact") is not False,''', '''"redact": True,'''),
    "nowhy": ("panel", '''        gaps = [(n, w) for n, w in gaps if w]''', '''        gaps = []'''),
    "dlattach": ("panel", '''            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)''', '''            pass'''),
    "dlplainlen": ("panel", '''            self.send_header("Content-Length", str(size if gz else raw))''', '''            self.send_header("Content-Length", str(size))'''),
    "ringoldest": ("block", '''        while self.size > self.share and self.segs:
            n, size, last_t, _z = self.segs.pop(0)''', '''        while self.size > self.share and self.segs:
            n, size, last_t, _z = self.segs.pop()'''),
    "ringcount": ("block", '''            self.cut += n
            self.cut_t = last_t''', '''            self.cut_t = last_t'''),
    "follow": ("block", '''    a = list(base) + ["--no-pager", "-o", "json", "--output-fields=" + LIVE_FIELDS, "--since=@%d" % since,''',
               '''    a = list(base) + ["-f", "--no-pager", "-o", "json", "--output-fields=" + LIVE_FIELDS, "--since=@%d" % since,'''),
    "nodotone": ("block", '''    for p in (path + ".1", path):
        try:
            f = open(p, "rb")''', '''    for p in (path,):
        try:
            f = open(p, "rb")'''),
    "timefilter": ("block", '''                if since_us <= t < until_us:
                    yield [t, src(text) if callable(src) else src, prio, text[:LIVE_TEXT_MAX]]''',
                   '''                if True:
                    yield [t, src(text) if callable(src) else src, prio, text[:LIVE_TEXT_MAX]]'''),
    "levelfilter": ("block", '''            if ln[2] in prios and live_want(ln[1], want):''', '''            if live_want(ln[1], want):'''),
    "ctrfollow": ("block", '''q="stdout=1&stderr=1&timestamps=1&since=%d&until=%d"''',
                  '''q="follow=1&stdout=1&stderr=1&timestamps=1&since=%d&x=%d"'''),
    "nodedone": ("noded", '''            if rid in _RANGE or rid in _RANGE_DONE:''', '''            if rid in _RANGE:'''),
    "node409": ("noded", '''            if r != "order":
                return''', '''            return'''),
    "nodenice": ("noded", '''        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)   # this thread only; journalctl inherits it''',
                 '''        pass'''),
    "nodeclock": ("noded", '''        since, end = rq["since"] + rq["off"], rq["until"] + rq["off"]''', '''        since, end = rq["since"], rq["until"]'''),
    "nodeflag": ("noded", '''dict(_LOG_BUDGET["status"], live=1, range=1)''', '''dict(_LOG_BUDGET["status"], live=1)'''),
    "nodestop": ("noded", '''        for rid in [k for k in _RANGE if k not in want]:
            _RANGE.pop(rid)["stop"].set()''', '''        for rid in []:
            _RANGE.pop(rid)["stop"].set()'''),
    "nodepartcap": ("noded", '''            n = min(_live_chunk(seg), RANGE_PART_LINES)''', '''            n = _live_chunk(seg)'''),
    "silentcap": ("panel", '''            ns["over"] = ns.get("over", 0) + len(lines) - len(keep)''',
                  '''            ns["over"] = ns.get("over", 0) + len(good) - len(keep)'''),
    "makerace": ("panel", '''        for lk in rec["locks"].values():                    # a part being written when the phase moved: let it finish
            with lk:                                        # (every later one sees "making" and is refused)
                pass''', '''        pass'''),
    "paneltrunc": ("panel", '''                if rec["stop"].is_set() or rec["phase"] != "reading" or ns["state"] in RANGE_FINAL:
                    return''', '''                if rec["stop"].is_set():
                    return'''),
    "nobeat": ("noded", '''        threading.Thread(target=beat, daemon=True, name="swg-range-beat-" + rq["id"]).start()''', '''        pass'''),
    "makeleak": ("panel", '''        if rec["stop"].is_set():                            # closed or dropped meanwhile: nothing stays behind
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            return''', '''        if rec["stop"].is_set():                            # closed or dropped meanwhile: nothing stays behind
            return'''),
    "onelock": ("panel", '''    with rec["locks"][nid]:                                # one server's parts in order; a retried part waits here''',
                '''    with rec["locks"][rec["nodes"][0]]:'''),
    "droplocked": ("panel", '    with _RANGE_LOCK:\n        gone = _range_expire(now)\n    for r in gone:\n        _range_drop(r)',
        '    with _RANGE_LOCK:\n        gone = _range_expire(now)\n        for r in gone:\n            _range_drop(r)'),
    "unitmix": ("panel", '        for ln in good:\n            if size + RANGE_LINE_OVER + len(ln[3]) > room:\n                break\n            size += RANGE_LINE_OVER + len(ln[3])',
        '        for ln in good:\n            if size + RANGE_LINE_OVER + len(ln[3].encode()) > room:\n                break\n            size += RANGE_LINE_OVER + len(ln[3].encode())'),
    "spatotal": ("spa", '''  const total = v ? Object.keys(v.nodes || {}).length : ids.length, done''', '''  const total = ids.length, done'''),
    "spaclose": ("spa", '''  Object.assign(RG, { id: null, v: null, err: "", saved: false, open: false });''',
                 '''  Object.assign(RG, { id: null, v: null, err: "", saved: false });'''),
    "beatslot": ("panel", '''            if body.get("id") in _RANGE_REQS and "seq" not in body:   # a range's progress: memory only, never refused''',
                 '''            if False:'''),
    "dropnowait": ("panel", '''    rec["stop"].set()
    for lk in (rec.get("locks") or {}).values():
        with lk:
            pass''', '''    rec["stop"].set()'''),
    "lateread": ("panel", '''            if ns["state"] in ("waiting", "reading"):      # began, changes nothing)
                ns["state"] = "reading"
                rd = body.get("read")''', '''            if True:
                rd = body.get("read")'''),
    "panelrevive": ("panel", '''            if ns["state"] in RANGE_FINAL:                 # "make the file now" came first: it is left out, as said
                return''', '''            pass'''),
    "beatgone": ("noded", '''                if _logs_post(rq, {"read": read[0]}) == "gone":      # never retried; "gone" stops the read
                    rq["stop"].set()''', '''                if _logs_post(rq, {"read": read[0]}) == "gone":      # never retried; "gone" stops the read
                    pass'''),
    "spaoff": ("spa", '''    off: [T("Logging is off"), T("Logging is off, so nothing is stored to read."), "warn"],   // a past range: no level brings it back''', ''''''),
    "mpnowild": ("spa", '''    if (g.wild && g.items.length && g.items.every(i => on.has(i.id))) out.push(g.wild);''',
                 '''    if (false) out.push(g.wild);'''),
    "mpclobber": ("spa", '''  const out = [...sel].filter(x => !mine.has(x)), all = ddItems(dd);''', '''  const out = [], all = ddItems(dd);'''),
    "nomigrate": ("spa", '''s.v === 2 ? s.src : migrate(s.src)''', '''s.src'''),
    "popunder": ("ui", '''      if (ours) { e.preventDefault(); close(true); } else''', '''      if (ours) { close(true); } else'''),
    "popbubble": ("ui", '''document.addEventListener("pointerdown", onDoc, true); document.addEventListener("keydown", onKey, true);''',
                  '''document.addEventListener("pointerdown", onDoc, true); document.addEventListener("keydown", onKey);'''),
    "nofocusin": ("ui", '''    document.addEventListener("focusin", onFocus, true);''', ''''''),
    "imeesc": ("ui", '''    const onKey = e => { if (e.key !== "Escape" || e.isComposing) return; const t = e.target;''',
               '''    const onKey = e => { if (e.key !== "Escape") return; const t = e.target;'''),
    "keepesc": ("ui", ''' else if (keep && keep(t)) close(false); };''', ''' };'''),
    "rowkey": ("spa", "<${Row} key=${l.id} l=${l} q=${q}/>", "<${Row} key=${l.nid + l.seq} l=${l} q=${q}/>"),
    "tieseq": ("spa", "a.k - b.k || a.id - b.id", "a.k - b.k || a.seq - b.seq"),
    "cardstop": ("spa", "onClick=${() => showOverlay(true)}>", "onClick=${openLogOverlay}>"),
    "overlayeager": ("spa", '''  return LV.overlay ? html`<${LogViewer} overlay/>` : null;''', '''  return html`<${LogViewer} overlay/>`;'''),
    "lvzabove": ("css", ".lv-full{position:fixed;inset:0;z-index:49;", ".lv-full{position:fixed;inset:0;z-index:950;"),
    "autostart": ("spa", "if (LV.busy || !LV.mounted || !LV.live || document.hidden) return;",
                  "if (LV.busy || !LV.mounted || document.hidden) return;"),
    "deepnav": ("spa", "  LV.gen++; remember();\n  openLogOverlay();\n", "  LV.gen++; remember();\n  goSettings(\"logs\");\n"),
    "notrap": ("spa", 'document.addEventListener("keydown", k); document.addEventListener("focusin", f);',
               'document.addEventListener("keydown", k);'),
    "nofocusback": ("spa", "if (el) el.focus(); }, 0); };", "}, 0); };"),
    "spablob": ("spa", '''  a.href = "api/logs/download/" + RG.id; a.download''', '''  downloadConf("", "x", "log"); a.href = "api/logs/download/" + RG.id; a.download'''),
}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PROG.items()}
if PLANT:
    f, a, b = PLANTS[PLANT]
    for f in (("noded", "panel") if f == "block" else (f,)):   # "block": the reader, planted in BOTH copies alike
        assert SRC[f].count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
        SRC[f] = SRC[f].replace(a, b)


def write_prog(key, name=None):
    p = os.path.join(tempfile.mkdtemp(prefix="logrange-prog-", dir=TMP), name or os.path.basename(PROG[key]))
    open(p, "w", encoding="utf-8").write(SRC[key])
    os.chmod(p, 0o755)
    return p


def load(key, env=None):
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    ld = importlib.machinery.SourceFileLoader("lr_" + key + str(time.monotonic_ns()), write_prog(key))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    m._LOG_STREAM = io.StringIO()
    m._LOG_JOURNAL = False
    return m


def guarded(name, fn):
    """Run one section's body; a plant that makes it raise fails ITS check rather than crashing the gate."""
    try:
        fn()
    except Exception as e:
        import traceback
        check(name + " (raised)", False, "%s: %s %s" % (type(e).__name__, e, traceback.format_exc()[-600:]))


def start_panel(src_path, tag, env=None):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    nodes = os.path.join(state, "nodes.json")
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {}},
               "n2": {"id": "n2", "name": "n2", "links": {}, "ifaces": {}},
               "n3": {"id": "n3", "name": "n3", "links": {}, "ifaces": {}}}, open(nodes, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    os.makedirs(os.path.join(state, "logspool", "leftover"))      # a crash's leftovers: gone at start
    open(os.path.join(state, "logspool", "leftover.log.gz"), "w").write("x")
    fleet = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", **(env or {})})
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                sys.exit("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return p, port, state


def req(port, path, data=None, token=None, raw=None, hdrs=None, whole=False):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {}), **(hdrs or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            out, code, h = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as e:
        out, code, h = e.read(), e.code, e.headers
    if whole:
        return code, out, h
    if h.get("Content-Encoding") == "gzip":
        out = gzip.decompress(out)
    return code, json.loads(out or b"{}")


LAST_SYNC = {}


def sync(port, tok, nid="n1", rng=True):
    w = LAST_SYNC.get((port, nid), 0) + 1.15 - time.monotonic()      # two signed syncs within a second: a replay (401)
    if w > 0:
        time.sleep(w)
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
            "log": {"mb": 100, "used_mb": 1.0, "live": 1, **({"range": 1} if rng else {})}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    LAST_SYNC[(port, nid)] = time.monotonic()
    assert code == 200, (code, r)
    return r


def post(port, body, tok):
    """A node's post as swg-noded makes it (_logs_post → post_json): its own node token in Authorization."""
    return req(port, "/api/node/logs", raw=gzip.compress(json.dumps(body).encode()), token=tok,
               hdrs={"Content-Encoding": "gzip"})


def wait_phase(port, rid, want=("ready", "failed"), secs=30):
    v = {}
    for _ in range(int(secs * 5)):
        c, o = req(port, "/api/logs/range?id=" + rid)
        v = o.get("data") or {}
        if v.get("phase") in want:
            break
        time.sleep(0.2)
    return v


def download(port, rid, gz=True):
    return req(port, "/api/logs/download/" + rid, hdrs={"Accept-Encoding": "gzip"} if gz else {}, whole=True)


ref_src = os.path.join(TMP, "ref-swg-panel-server")
open(ref_src, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True,
                                         check=True).stdout)
procs = []
CTX = {}
RANGE_BODY = {"src": ["noded"], "lv": ["err", "warn", "info"], "span": 3600, "tz": 180, "label": "1h"}

# ── [1] the wire, against real panels ────────────────────────────────────────────────────────────────────────────────
print("[1] the wire")


def sec1():
    pa, port_a, _ = start_panel(ref_src, "refa"); procs.append(pa)
    pb, port_b, _ = start_panel(ref_src, "refb"); procs.append(pb)
    pn, port_n, state_n = start_panel(write_prog("panel"), "new"); procs.append(pn)
    toks = {}
    for port in (port_a, port_b, port_n):
        toks[port] = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("n1", "n2", "n3")}
    ra, rb, rn = (sync(port, toks[port]["n1"]) for port in (port_a, port_b, port_n))
    ra, rb, rn = (sync(port, toks[port]["n1"]) for port in (port_a, port_b, port_n))
    vol = {k for k in set(ra) | set(rb) if json.dumps(ra.get(k), sort_keys=True) != json.dumps(rb.get(k), sort_keys=True)}
    diff = [k for k in set(ra) | set(rn) if k not in vol and json.dumps(ra.get(k)) != json.dumps(rn.get(k))]
    check("[1] an idle fleet's sync reply is byte-identical to the build before P3 (but what the old build's own instances "
          "disagree on: %s)" % sorted(vol), list(rn) == list(ra) and not diff, (diff, set(rn) ^ set(ra)))
    c, o = req(port_n, "/api/logs/range", {"nodes": ["n1"], **RANGE_BODY})
    check("[1] a range download opens", c == 200 and re.match(r"^[0-9a-f]{16}$", o["data"]["id"]), (c, o))
    rid = o["data"]["id"]
    r1, r2 = sync(port_n, toks[port_n]["n1"]), sync(port_n, toks[port_n]["n2"], "n2")
    e = (r1.get("logrange") or [{}])[0]
    now = time.time()
    check("[1] the node it names gets `logrange` [{id, key, src, lv, since, until, share, iv, now}]",
          e.get("id") == rid and e.get("key", "").startswith("n1.") and e.get("src") == ["noded"]
          and e.get("lv") == ["err", "warn", "info"] and e.get("until", 0) - e.get("since", 0) == 3600
          and abs(e.get("until", 0) - now) < 5 and e.get("share") == 50 << 20 and e.get("iv") == 1
          and abs(e.get("now", 0) - now) < 5, r1.get("logrange"))
    check("[1] never under P2's `logs` (a P2 node would follow it live), and not to a node it does not name",
          "logs" not in r1 and "logrange" not in r2 and "logs" not in r2, (r1.get("logs"), r2.get("logrange")))
    k = e["key"]
    post(port_n, {"id": rid, "key": k, "now": time.time(), "st": {"noded": "ok"}}, toks[port_n]["n1"])
    post(port_n, {"id": rid, "key": k, "now": time.time(), "seq": 0, "lines": [], "done": {"read": 0}}, toks[port_n]["n1"])
    r1 = sync(port_n, toks[port_n]["n1"])
    check("[1] a server that is done is no longer asked", "logrange" not in r1, r1.get("logrange"))
    req(port_n, "/api/logs/range/close", {"id": rid})
    CTX.update(port=port_n, toks=toks[port_n], state=state_n)
    check("[3] the spool is emptied at start: a crash's leftovers are gone",
          os.listdir(os.path.join(state_n, "logspool")) == [], os.listdir(os.path.join(state_n, "logspool")))


try:
    guarded("[1]", sec1)

    # ── [2] the parts and the download ───────────────────────────────────────────────────────────────────────────────
    print("[2] the parts and the download")

    def sec2():
        port, toks = CTX["port"], CTX["toks"]
        c, o = req(port, "/api/logs/range", {"nodes": ["n1", "n2"], **RANGE_BODY, "names": {"n1": "alpha", "n2": "beta"}})
        rid = o["data"]["id"]
        k1 = sync(port, toks["n1"])["logrange"][0]["key"]
        k2 = sync(port, toks["n2"], "n2")["logrange"][0]["key"]
        c, o = post(port, {"id": rid, "key": "n1." + "0" * 32, "now": time.time(), "st": {}}, toks["n1"])
        c2, _ = post(port, {"id": rid, "key": k2.replace("n2.", "n1."), "now": time.time(), "st": {}}, toks["n1"])
        check("[2] a wrong key, or another node's, is 403", c == 403 and c2 == 403, (c, c2))
        c, o = post(port, {"id": rid, "key": k1, "now": time.time(), "st": {"noded": "ok"}}, toks["n1"])
        c, o = post(port, {"id": rid, "key": k1, "now": time.time(), "read": 5000}, toks["n1"])
        v = req(port, "/api/logs/range?id=" + rid)[1]["data"]
        check("[2] the node's first word and its progress: \"reading\", lines read so far",
              c == 200 and v["nodes"]["n1"]["state"] == "reading" and v["nodes"]["n1"].get("read") == 5000, v["nodes"])
        t = int(time.time() * 1e6) - 600 * 10 ** 6
        part = lambda i: [[t + i * 1000 + j, "noded", 6, "n1 part %d line %d" % (i, j)] for j in range(3)]
        c0, _ = post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 0, "lines": part(0)}, toks["n1"])
        c1, _ = post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 1, "lines": part(1)}, toks["n1"])
        cr, orr = post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 1, "lines": part(1)}, toks["n1"])
        cg, og = post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 5, "lines": part(5)}, toks["n1"])
        check("[2] parts in order are taken; a repeat is answered 200; one out of order is 409 with the next it wants",
              (c0, c1, cr) == (200, 200, 200) and cg == 409 and og.get("next") == 2, (c0, c1, cr, cg, og))
        # n2: a part 0, then the node restarted — a new part 0 starts it afresh
        post(port, {"id": rid, "key": k2, "now": time.time(), "st": {"noded": "ok"}}, toks["n2"])
        post(port, {"id": rid, "key": k2, "now": time.time(), "seq": 0, "lines": [[t + 5, "noded", 6, "n2 first read"]]},
             toks["n2"])
        post(port, {"id": rid, "key": k2, "now": time.time(), "seq": 0, "lines": [[t + 6, "noded", 6, "n2 second read"]],
                    "done": {"read": 1}}, toks["n2"])
        post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 2, "lines": part(2), "done": {"read": 9}}, toks["n1"])
        v = wait_phase(port, rid)
        check("[2] every server done → the file is made", v.get("phase") == "ready" and v.get("lines") == 10, v)
        c, b, h = download(port, rid)
        c2, b2, h2 = download(port, rid, gz=False)
        txt = gzip.decompress(b).decode() if h.get("Content-Encoding") == "gzip" else ""
        check("[2] the download is an attachment named for the range",
              c == 200 and re.match(r'^attachment; filename="swg-logs-1h-\d{8}-\d{4}\.log"$', h.get("Content-Disposition") or "")
              and h.get("Cache-Control") == "no-store", (c, h.get("Content-Disposition")))
        check("[2] gzip on the wire to a browser that takes it; the same text unpacked otherwise, its length exact",
              txt and h2.get("Content-Encoding") is None and b2.decode() == txt and int(h2.get("Content-Length")) == len(b2)
              and int(h.get("Content-Length")) == len(b), (len(b), h.get("Content-Length"), len(b2), h2.get("Content-Length")))
        body = [ln for ln in txt.splitlines() if ln and not ln.startswith("#")]
        check("[2] a repeated part is kept once; a server's new part 0 replaced its earlier read",
              sum("n1 part 1 line 0" in ln for ln in body) == 1 and not any("n2 first read" in ln for ln in body)
              and any("n2 second read" in ln for ln in body), body)
        c, o = download(port, "f" * 16)[:2]
        check("[2] an unknown download is 404", c == 404, c)
        c, o = post(port, {"id": rid, "key": k1, "now": time.time(), "seq": 3, "lines": []}, toks["n1"])
        check("[2] a part for a request that is made is 404 (the node stops)", c == 404, (c, o))
        req(port, "/api/logs/range/close", {"id": rid})
        check("[2] closed: the file is gone", download(port, rid)[0] == 404 and not os.listdir(os.path.join(CTX["state"], "logspool")),
              os.listdir(os.path.join(CTX["state"], "logspool")))
        # in-process: the route never parses the node store, never takes _api_lock, and is closed on a node door
        P = load("panel")
        calls = []
        P.nodes_load = lambda path, _n=P.nodes_load: (calls.append(path), _n(path))[1]
        P.range_init(os.path.join(TMP, "inproc-spool"))
        rid2 = P.range_open({"nodes": ["n1"], **RANGE_BODY}, {"n1"})[1]["data"]["id"]
        rec = P._RANGE_REQS[rid2]
        k = P._live_key(rec, "n1")
        P.range_reply("n1", tok=P._log_tok("Bearer T1"))          # what the sync reply records (_node_sync_apply)
        sent = []

        class H:
            pass

        def handler(body):
            h = H()
            raw = gzip.compress(json.dumps(body).encode())
            h.headers = {"Content-Length": str(len(raw)), "Content-Encoding": "gzip", "Authorization": "Bearer T1"}
            h.rfile = io.BytesIO(raw)
            h._send = lambda code, obj: sent.append((code, obj))
            h._body_len = lambda cap=0: P.Handler._body_len(h, cap)
            h.send_error = lambda *a: sent.append(a)
            return h
        P._api_lock.acquire()
        try:
            th = threading.Thread(target=P.Handler._node_logs, args=(handler({"id": rid2, "key": k, "now": time.time(), "st": {}}),))
            th.start(); th.join(10)
        finally:
            P._api_lock.release()
        check("[2] a range post never parses the node store and never waits on _api_lock",
              not th.is_alive() and sent and sent[-1][0] == 200 and not calls, (sent, calls))
        held = []
        for _ in range(4):
            if P.RANGE_POST_SLOTS.acquire(blocking=False):
                held.append(1)
        P.Handler._node_logs(handler({"id": rid2, "key": k, "now": time.time(), "seq": 0, "lines": []}))
        part = sent[-1]
        P.Handler._node_logs(handler({"id": rid2, "key": k, "now": time.time(), "read": 1}))
        prog = sent[-1]
        for _ in held:
            P.RANGE_POST_SLOTS.release()
        check("[2] at most 4 range parts at a time: a 5th is 503 (the node sends it again)", part[0] == 503, part)
        check("[9] a progress post never waits for an upload slot (memory only): 200 with every slot busy", prog[0] == 200, prog)
        P._REQ.listener_role = "node"
        check("[2] the download route is closed on a node door (404)", not P._door_ok("GET", "/api/logs/download/" + rid2)
              and not P._door_ok("GET", "/api/logs/range"), "")
        P._REQ.listener_role = "full"
        src = SRC["panel"]
        i = src.index("            if path.startswith(\"/api/logs/download/\"):")
        j = src.index("            try:\n                code, obj = api(\"GET\", path, parse_qs(u.query), {}, self.deps)")
        k_auth = src.index("        if not self._require_auth():       # everything else (data) needs a session")
        check("[2] the download is dispatched after the session check and before api()", k_auth < i < j, (k_auth, i, j))

    guarded("[2]", sec2)

    # ── [3] the store ──────────────────────────────────────────────────────────────────────────────────────────────
    print("[3] the store")

    def sec3():
        P = load("panel")
        sp = os.path.join(TMP, "store-spool")
        P.range_init(sp)
        known = {"n1", "n2", "n3"}
        a = P.range_open({"nodes": ["n1"], **RANGE_BODY}, known)
        b = P.range_open({"nodes": ["n1"], **RANGE_BODY}, known)
        c = P.range_open({"nodes": ["n1"], **RANGE_BODY}, known)
        check("[3] at most 2 in progress: a 3rd is refused (429)", a[0] == 200 and b[0] == 200 and c[0] == 429, (a, b, c))
        for r in list(P._RANGE_REQS):
            P.range_api_post("/api/logs/range/close", {"id": r}, {})
        st, o = P.range_open({"nodes": ["panel", "n1", "n2", "n3", "ghost1"], **RANGE_BODY, "src": ["noded"]}, known)
        rec = P._RANGE_REQS[o["data"]["id"]]
        check("[3] each server's share is the total divided between them (5 servers: 10 MB)",
              rec["share"] == (50 << 20) // 5 and o["data"]["share"] == rec["share"], rec["share"])
        now = time.time()
        snaps = {"n1": {"log": {"live": 1, "range": 1}}, "n2": {"log": {"live": 1}}, "n3": {"log": {"live": 1, "range": 1}}}
        seen = {"n1": now, "n2": now, "n3": now}
        P._range_tick(rec, snaps, seen, 30, now)
        ns = rec["ns"]
        check("[3] a node the panel has not heard from is asked and reads \"offline\"; one without `log.range` \"old\"",
              ns.get("ghost1", {}).get("state") == "offline" and ns["n2"]["state"] == "old", ns)
        P.range_reply("n1", now=now - 30); P.range_reply("n3", now=now)
        P._range_tick(rec, snaps, seen, 30, now)
        check("[3] asked over 20 s ago with no word: \"noanswer\"; asked just now: still waiting",
              ns["n1"]["state"] == "noanswer" and ns["n3"]["state"] == "waiting", ns)
        ns["n3"].update(state="reading", last=now - 130)
        P._range_tick(rec, snaps, seen, 30, now)
        check("[3] a server silent 2 min after it said it reads: \"failed\"", ns["n3"]["state"] == "failed", ns["n3"])
        rec2 = P._RANGE_REQS[P.range_open({"nodes": ["n1", "n3"], **RANGE_BODY}, known)[1]["data"]["id"]]
        ns2 = rec2["ns"]
        ns2["n1"].update(state="done")
        ns2["n3"].update(state="reading", last=now)
        fin = P._range_tick(rec2, snaps, seen, 30, rec2["at"] + 601)
        check("[3] a request past its 10 min: the rest \"timeout\", and the file is made", fin and ns2["n3"]["state"] == "timeout",
              (fin, ns2))
        for r in list(P._RANGE_REQS):
            P.range_api_post("/api/logs/range/close", {"id": r}, {})
        st, o = P.range_open({"nodes": ["n1", "n3"], **RANGE_BODY}, known)
        rec3 = P._RANGE_REQS[o["data"]["id"]]
        rec3["ns"]["n1"]["state"] = "done"
        P.range_api_post("/api/logs/range/make", {"id": rec3["id"]}, {})
        check("[3] \"make the file now\": the rest are left out (\"skipped\")",
              rec3["ns"]["n3"]["state"] == "skipped" and rec3["phase"] in ("making", "ready"), (rec3["phase"], rec3["ns"]))
        for _ in range(50):
            if rec3["phase"] == "ready":
                break
            time.sleep(0.1)
        st, o = P.range_open({"nodes": ["n1"], **RANGE_BODY}, known)
        rec4 = P._RANGE_REQS[o["data"]["id"]]
        rec4["polled"] = time.time() - 121
        P.range_reply("n9")
        check("[3] a request nobody polls for 2 min goes (a tab closed)", rec4["id"] not in P._RANGE_REQS, list(P._RANGE_REQS))
        path3 = rec3["dir"] + ".log.gz"
        had = os.path.exists(path3)
        rec3["made"] = rec3["read"] = time.time() - 601
        P.range_reply("n9")
        check("[3] a made file goes 10 min after its making or its last download, from disk too",
              had and rec3["id"] not in P._RANGE_REQS and not os.path.exists(path3), (had, os.path.exists(path3)))
        for i in range(6):
            r = {"id": "%016x" % i, "phase": "ready", "made": time.time() - 100 + i, "read": 0, "polled": time.time(),
                 "dir": os.path.join(sp, "%016x" % i), "stop": threading.Event(), "ns": {}}
            P._RANGE_REQS[r["id"]] = r
        P.range_reply("n9")
        check("[3] 4 made files at most: the oldest go", sorted(P._RANGE_REQS) == ["%016x" % i for i in range(2, 6)],
              sorted(P._RANGE_REQS))
        P._RANGE_REQS.clear()
        os.makedirs(os.path.join(sp, "logspool", "stale"), exist_ok=True)
        P.range_init(sp)
        check("[3] range_init empties the spool", os.listdir(os.path.join(sp, "logspool")) == [],
              os.listdir(os.path.join(sp, "logspool")))

    guarded("[3]", sec3)

    # ── [4] the file ──────────────────────────────────────────────────────────────────────────────────────────────
    print("[4] the file")

    def make(P, redact=True, lines=None):
        st, o = P.range_open({"nodes": ["n1", "n2"], **RANGE_BODY, "redact": redact, "names": {"n1": "alpha", "n2": "beta"}},
                             {"n1", "n2"})
        rec = P._RANGE_REQS[o["data"]["id"]]
        base = rec["since"] * 10 ** 6 + 10 ** 6
        n1 = lines or [[base + 0, "noded", 6, "first"], [base + 2000000, "noded", 4, "third " + KEY],
                       [base + 4000000, "noded", 3, "fifth\nsecond line of it"]]
        n2 = [[base + 1000000 + 90 * 10 ** 6, "noded", 6, "second (n2 clock 90 s ahead)"],
              [base + 3000000 + 90 * 10 ** 6, "noded", 6, "fourth Authorization: Bearer abc.def-123456 x " + NOTKEY
               + " swgp_0123456789abcdef0123"]]
        for nid, ln, off in (("n1", n1, 0), ("n2", n2, 90)):
            k = P._live_key(rec, nid)
            P.range_absorb({"id": rec["id"], "key": k, "now": time.time() + off, "st": {"noded": "ok"}})
            P.range_absorb({"id": rec["id"], "key": k, "now": time.time() + off, "seq": 0, "lines": ln,
                            "done": {"read": len(ln), **({"cut": 7, "cut_t": base - 5 * 10 ** 6} if nid == "n1" else {})}})
        rec["phase"] = "making"
        P._range_make(rec)
        return rec, gzip.open(rec["dir"] + ".log.gz", "rt").read()

    def sec4():
        P = load("panel")
        P.range_init(os.path.join(TMP, "file-spool"))
        rec, txt = make(P)
        body = [ln for ln in txt.splitlines() if ln and not ln.startswith("#")]
        words = [ln.split()[-1] if "Bearer" not in ln and "[key]" not in ln else ln.split()[6] for ln in body]
        order = [w for w in ("first", "second", "third", "fourth", "fifth") if any((" " + w + " ") in (ln + " ") for ln in body)]
        idx = [next(i for i, ln in enumerate(body) if (" " + w + " ") in (ln + " ")) for w in order]
        check("[4] every server's lines merged by time, a skewed node on the panel's clock",
              len(order) == 5 and idx == sorted(idx), (order, idx, body))
        check("[4] each line: time with the browser's offset, server name, source, level, message",
              re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \+03:00  alpha  noded +INFO +first$", body[0] or ""), body[:1])
        check("[4] a message's newlines are kept (the next line indented)",
              any(ln == "    second line of it" for ln in txt.splitlines()), txt[-300:])
        head = [ln for ln in txt.splitlines() if ln.startswith("#")]
        hs = "\n".join(head)
        check("[4] the header: range, made by, servers, sources, levels, redaction",
              "# swg logs — last 1 h" in hs and "# servers (2): alpha, beta" in hs and "# sources: noded" in hs
              and "# levels: err, warn, info" in hs and "# redacted:" in hs and "# range: " in hs and "by panel" in hs, hs)
        check("[4] the header says what is not whole and why (a share that was full, a clock corrected)",
              re.search(r"#   alpha — 7 earlier lines, up to .*its share", hs) and "#   beta — clock 90 s ahead — corrected" in hs, hs)
        check("[4] redaction: a 32-byte key, a Bearer token, an swgp_ token",
              KEY not in txt and "third [key]" in txt and "Bearer [redacted]" in txt and "swgp_[redacted]" in txt, body)
        check("[4] a 44-character string that no 32 bytes encode to is left alone", NOTKEY in txt, body)
        rec, txt = make(P, redact=False)
        check("[4] unticked: nothing is masked, and the header says so", KEY in txt and "Bearer abc.def-123456" in txt
              and "# not redacted" in txt, txt[:600])
        rec, txt = make(P, lines=[])
        check("[4] a server with nothing: the file is still made", "second (n2" in txt, txt[-300:])

    guarded("[4]", sec4)

    # ── [5] the reader ─────────────────────────────────────────────────────────────────────────────────────────────
    print("[5] the reader")

    def blk(s):
        a = "# ── the live log reader (docs/LOGS-PLAN.md §3, §23)"
        return s[s.index(a):s.index("# ── end of the live log reader")]

    def sec5():
        check("[5] the reader block is byte-identical in swg-noded and swg-panel-server", blk(SRC["noded"]) == blk(SRC["panel"]))
        N = load("noded")
        ring = N.RangeRing(40000)
        for i in range(3000):
            ring.add([i, "noded", 6, "x" * 60])
        kept = [ln for part in ring.parts() for ln in part]
        check("[5] the ring keeps the NEWEST part of its share, oldest first", kept and kept[-1][0] == 2999
              and [l[0] for l in kept] == list(range(kept[0][0], 3000)) and len(kept) * 124 <= 40000 + 4096, (len(kept), kept[:1]))
        check("[5] and counts what it cut: how many, and the newest of them", ring.cut == 3000 - len(kept)
              and ring.cut_t == kept[0][0] - 1 and ring.lines == len(kept), (ring.cut, ring.cut_t, len(kept)))
        a = N.range_journal_argv(["journalctl", "--namespace=+swg-node"], ["swg-noded.service"], True, 1000, 2000, 4)
        check("[5] journalctl once (no -f) between two times, -p for the levels, OR-ed matches",
              "-f" not in a and "--since=@1000" in a and "--until=@2000" in a and a[a.index("-p") + 1] == "0..4"
              and a.count("+") == 2 and "_TRANSPORT=kernel" in a, a)
        d = tempfile.mkdtemp(dir=TMP)
        lf = os.path.join(d, "swg-noded.log")
        T0 = 1_800_000_000
        fmt = lambda t, l, m: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) + " %s %s\n" % (l, m)
        open(lf + ".1", "w").write("".join(fmt(T0 + i, "I", "old %d" % i) for i in range(0, 100, 10)))
        open(lf, "w").write("".join(fmt(T0 + 100 + i, "W" if i % 20 else "E", "new %d" % i) for i in range(0, 100, 10))
                            + fmt(T0 + 150, "I", "swg-sni: host.example"))
        # a fake journalctl: prints entries between --since and --until, in order
        fj = os.path.join(d, "journalctl")
        open(fj, "w").write("#!/usr/bin/env python3\nimport json,sys\na=sys.argv\ns=int([x for x in a if x.startswith('--since=@')][0][9:])\n"
                            "u=int([x for x in a if x.startswith('--until=@')][0][9:])\nfor t in range(%d, %d, 7):\n"
                            "    if s <= t <= u: print(json.dumps({'__REALTIME_TIMESTAMP': str(t*1000000), 'PRIORITY': '6', '_SYSTEMD_UNIT': 'swg-wdtt-w1.service', 'MESSAGE': 'j %%d' %% t}))\n"
                            % (T0, T0 + 200))
        os.chmod(fj, 0o755)
        # a fake docker socket: answers one logs query with framed lines, and records the query
        sp, got = os.path.join(d, "docker.sock"), []
        srv = socket.socket(socket.AF_UNIX); srv.bind(sp); srv.listen(4)

        def serve():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                q = c.recv(4096).decode().split(" ")[1]
                got.append(q)
                out = b"HTTP/1.0 200 OK\r\nContent-Type: application/vnd.docker.raw-stream\r\n\r\n"
                for t in range(T0 + 5, T0 + 200, 50):
                    ln = (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000000000Z ctr %d\n" % t).encode()
                    out += bytes([1, 0, 0, 0]) + len(ln).to_bytes(4, "big") + ln
                c.sendall(out)
                c.close()
        threading.Thread(target=serve, daemon=True).start()
        ring = N.RangeRing(1 << 20)
        n = N.range_read(ring, ["noded", "turn:*", "relay:*"], ["err", "warn", "info"], T0 + 40, T0 + 160, threading.Event(),
                         journal=lambda s, u, pm: N.range_journal_argv([fj], ["swg-wdtt-w1.service"], False, s, u, pm),
                         files=[(lf, N.live_noded_src, "ours")], ctrs=[("swg-relay-awg0", "relay:awg0")], sock=sp)
        got_lines = [ln for part in ring.parts() for ln in part]
        ts = [l[0] for l in got_lines]
        srcs = {l[1] for l in got_lines}
        check("[5] the sources are merged in time order: journal, file (its .1 first) and container",
              ts == sorted(ts) and {"noded", "turn:w1", "relay:awg0"} <= srcs and any(l[3] == "old 40" for l in got_lines)
              and any(l[3] == "new 50" for l in got_lines), (srcs, got_lines[:4]))
        check("[5] only the range: nothing before `since` or after `until`",
              all((T0 + 40) * 10 ** 6 <= t < (T0 + 160) * 10 ** 6 for t in ts) and not any(l[3] == "old 30" for l in got_lines)
              and not any(l[3] == "new 70" for l in got_lines), [l for l in got_lines if not (T0 + 40) * 10 ** 6 <= l[0] < (T0 + 160) * 10 ** 6][:3])
        ring = N.RangeRing(1 << 20)
        N.range_read(ring, ["noded", "sni"], ["err"], T0, T0 + 200, threading.Event(), files=[(lf, N.live_noded_src, "ours")])
        lv = [ln for part in ring.parts() for ln in part]
        check("[5] the level chips are applied (errors only), the sources too (sni's line is not noded's)",
              lv and all(l[2] <= 3 for l in lv) and not any(l[1] == "sni" for l in lv), lv[:3])
        check("[5] a container is read from `since` to `until`, not followed",
              got and "follow" not in got[0] and "since=%d" % (T0 + 40) in got[0] and "until=%d" % (T0 + 161) in got[0], got)
        srv.close()
        check("[5] no claim that a server's budget cut the range's start (its first line of a source is not its budget's "
              "reach: a source younger than the range read as one — plan §32 #2)", not hasattr(N, "range_first"), "")

    guarded("[5]", sec5)

    # ── [6] the node ───────────────────────────────────────────────────────────────────────────────────────────────
    print("[6] the node")

    def sec6():
        port, toks = CTX["port"], CTX["toks"]
        N = load("noded")
        d = tempfile.mkdtemp(dir=TMP)
        N.NODE_KIND, N.LOG_DIR_DOCKER = "docker", d
        N._host_sh_available = lambda: False
        now = int(time.time())
        open(os.path.join(d, "swg-noded.log"), "w").write("".join(
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 1000 + i)) + " I node line %d\n" % i for i in range(0, 1000, 5)))
        nice, seen, plans = [], [], []
        N.os.setpriority = lambda *a: nice.append(a)
        lp = N._live_plan
        N._live_plan = lambda *a, **k: (plans.append(a), lp(*a, **k))[1]   # each read starts with its source plan
        rr = N.range_read
        N.range_read = lambda *a, **k: (seen.append((a[3], a[4])), rr(*a, **k))[1]
        rid = req(port, "/api/logs/range", {"nodes": ["n1"], **RANGE_BODY})[1]["data"]["id"]
        rep = sync(port, toks["n1"])
        lr = rep["logrange"]
        lr[0]["now"] = lr[0]["now"] - 100                      # this box's clock is 100 s ahead of the panel's
        url = "http://127.0.0.1:%d/api/node/sync" % port
        n_threads = threading.active_count()
        N.range_logs_take(lr, url, {"token": toks["n1"]}, {})
        thr = [t for t in threading.enumerate() if t.name == "swg-range-" + rid]
        v = wait_phase(port, rid)
        check("[6] a thread per range, never the sync loop's time; the file is made from its parts",
              thr and v.get("phase") == "ready" and v.get("lines") == 200, (thr, v))
        check("[6] the read is niced (the thread itself; journalctl inherits it)",
              any(a[2] == 19 for a in nice), nice)
        check("[6] the read is shifted by the clock offset (this box 100 s ahead)",
              seen and abs(seen[0][0] - lr[0]["since"] - 100) <= 1 and seen[0][1] - seen[0][0] == 3600,
              (seen, lr[0]["since"]))   # the reply's `now` is whole seconds: the offset is 100 or 101
        n_reads = len(plans)
        N.range_logs_take(lr, url, {"token": toks["n1"]}, {})
        time.sleep(1)
        check("[6] a range the node has finished is not read again when a reply still names it", n_reads == 1
              and len(plans) == n_reads, (len(plans), n_reads))
        req(port, "/api/logs/range/close", {"id": rid})
        # a slow read the reply drops: stopped
        N.range_read = lambda ring, want, lv, s, u, stop, **k: (stop.wait(30), 0)[1]
        rid = req(port, "/api/logs/range", {"nodes": ["n1"], **RANGE_BODY})[1]["data"]["id"]
        lr = sync(port, toks["n1"])["logrange"]
        N.range_logs_take(lr, url, {"token": toks["n1"]}, {})
        time.sleep(0.5)
        rq = N._RANGE.get(rid)
        N.range_logs_take(None, url, {"token": toks["n1"]}, {})
        time.sleep(0.5)
        check("[6] a range the reply no longer names stops reading", rq is not None and rq["stop"].is_set()
              and rid not in N._RANGE, rq and rq["stop"].is_set())
        req(port, "/api/logs/range/close", {"id": rid})
        # a 409: the parts again from 0
        N.range_read = rr
        sent, first = [], [True]

        def fake_post(rq, extra):
            sent.append(extra.get("seq"))
            if extra.get("seq") == 1 and first[0]:
                first[0] = False
                return "order"
            return "ok"
        N._logs_post = fake_post
        N.LIVE_POST_BYTES = 2000                              # small parts: several of them
        rq = {"id": "a" * 16, "stop": threading.Event(), "key": "k", "src": ["noded"], "lv": ["info"], "since": now - 2000,
              "until": now, "share": 1 << 20, "iv": 1, "off": 0, "url": "", "panel": {}}
        N._range_run(rq, [])
        parts = [s for s in sent if s is not None]
        check("[6] parts are numbered from 0; a 409 starts them again from 0; `done` with the last",
              parts[:2] == [0, 1] and parts[2] == 0 and parts[2:] == list(range(len(parts) - 2)) and len(parts) > 4, parts)
        check("[6] the snapshot says the node takes ranges (`log.range`)",
              'dict(_LOG_BUDGET["status"], live=1, range=1)' in SRC["noded"], "")

    guarded("[6]", sec6)

    # ── [7] the SPA ────────────────────────────────────────────────────────────────────────────────────────────────
    print("[7] the SPA")

    def sec7():
        s = SRC["spa"]
        u = SRC["ui"]
        u = u[u.index("export function usePopup("):u.index("export function Dropdown(")]   # the hook itself, not a Sheet's own listener
        i = s.index("function rangeSave()")
        body = s[i:s.index("\n}", i)]
        check("[7] the file is saved from a plain link to the download route, never built as a Blob",
              'a.href = "api/logs/download/" + RG.id' in body and "Blob" not in body and "downloadConf" not in body
              and 'href=${"api/logs/download/" + RG.id}' in s, body)
        keys = list(dict.fromkeys(re.findall(r'\bT\("((?:[^"\\]|\\.)*)"', s)))
        missing = [k for k in keys if '"%s":' % k not in SRC["ru"]]
        check("[7] every string of the viewer has its Russian", not missing, missing)
        # the source dropdowns' choice (pure functions, run as they are in the SPA): a whole group or list is written back
        # as its wildcard, one item off expands it, and another list's choices are never touched
        fn = "\n".join(s[s.index(a):s.index(b)] for a, b in (("const ddItems =", "const tickOf ="),))
        js = fn + """
const dd = { wild: "turn:*", groups: [{ id: "vk", items: [{ id: "turn:a" }, { id: "turn:b" }] }, { id: "w", items: [{ id: "turn:w1" }] }] };
const node = { groups: [{ id: "svc", items: [{ id: "noded" }] }, { id: "mesh", wild: "mesh:*", items: [{ id: "mesh:swg_1" }, { id: "mesh:swg_2" }] }] };
const sel = new Set(["noded", "turn:*", "mesh:*"]);
const r = {};
r.on = [...mpOn(dd, sel)].sort();
let on = mpOn(dd, sel); on.delete("turn:b"); r.offOne = mpWrite(dd, sel, on).sort();
on = mpOn(node, sel); on.delete("mesh:swg_2"); r.meshOne = mpWrite(node, sel, on).sort();
on = mpOn(node, new Set(["noded", "mesh:swg_1"])); on.add("mesh:swg_2"); r.meshAll = mpWrite(node, new Set(["noded", "mesh:swg_1", "turn:*"]), on).sort();
console.log(JSON.stringify(r));
"""
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        r = json.loads(out.stdout or "{}") if out.returncode == 0 else {"err": out.stderr[-300:]}
        mg = s[s.index("const migrate ="):s.index("\n", s.index("const migrate ="))]
        out = subprocess.run(["node", "-e", mg + '; console.log(JSON.stringify(migrate(["noded", "iface:*", "iface:awg0", "iface:swg_ab"])))'],
                             capture_output=True, text=True)
        check("[10] a choice remembered before mesh links were a source keeps them: iface:* adds mesh:*, iface:swg_… becomes mesh:",
              out.returncode == 0 and json.loads(out.stdout) == ["noded", "iface:*", "mesh:*", "iface:awg0", "mesh:swg_ab"]
              and "s.v === 2 ? s.src : migrate(s.src)" in s, (out.stdout, out.stderr[-200:]))
        def z(sel):                                  # the z-index of the rule that starts with this selector
            m = re.search(r"(?m)^" + re.escape(sel) + r"\{[^}]*?z-index:(\d+)", SRC["css"])
            return int(m.group(1)) if m else None
        zs = {k: z(k) for k in (".appbar", ".lv-full", ".overlay", ".ddpop", ".deppop")}
        check("[10] the full-screen viewer covers the header, sits UNDER the modal layer (a sheet or confirm opened over it "
              "shows), and its lists and bubbles open over it",
              None not in zs.values() and zs[".appbar"] < zs[".lv-full"] < zs[".overlay"]
              and zs[".lv-full"] < zs[".ddpop"] and zs[".lv-full"] < zs[".deppop"], zs)
        u = SRC["ui"]
        u = u[u.index("export function usePopup("):u.index("export function Dropdown(")]   # the hook itself, not a Sheet's own listener
        check("[10] Escape in an open dropdown closes it, not the full-screen viewer (the shared usePopup: capture phase, "
              "marked; the viewer and its lists use it)",
              'document.addEventListener("keydown", onKey, true)' in u and 'if (ours) { e.preventDefault(); close(true); }' in u
              and 'e.key === "Escape" && !e.defaultPrevented' in s and s.count("usePopup({") == 2 and "function usePop(" not in s, "")
        check("[11] a list closes when focus moves anywhere not its own (watched on the document: Safari focuses no button); "
              "an IME composition keeps its Escape; a form the list owns closes it without stealing the focus",
              'document.addEventListener("focusin", onFocus, true)' in u and "const onFocus = e => { if (!inside(e.target)) shut(); };" in u
              and 'if (e.key !== "Escape" || e.isComposing) return;' in u and "else if (keep && keep(t)) close(false);" in u
              and "if (e.isComposing) return;" in u, "")
        idx, appjs = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read(), open(os.path.join(ROOT, "app.js"), encoding="utf-8").read()
        check("[12] the header's Logs button opens the viewer over any screen, and nothing mounts (so nothing is asked) until "
              "it is clicked; Exit closes it",
              'id="logs-btn"' in idx and idx.index('id="logs-btn"') < idx.index('id="panel-settings-btn"')
              and "${h(LogOverlay)}" in appjs and "lg.onclick = openLogOverlay" in appjs
              and "return LV.overlay ? html`<${LogViewer} overlay/>` : null;" in s and "onClick=${closeLogOverlay}" in s, "")
        tk = s[s.index("async function tick()"):s.index("\n}", s.index("async function tick()"))]
        ol = s[s.index("export function openLogs("):s.index("\n}", s.index("export function openLogs("))]
        check("[13] Settings → Logs asks nothing until Start; the header button and a deep link are the ask, and a deep link "
              "opens over the page it was on (never Settings underneath)",
              "!LV.live" in tk and "LV.overlay = LV.live = true" in s and "openLogOverlay();" in ol and "goSettings" not in s
              and 'T("Start live log")' in s, (tk[:160], ol))
        check("[13] full screen keeps the focus: Tab or a click cannot reach the page under it (a sheet, list or bubble over "
              "it can), and Exit gives the focus back to what opened it",
              'document.addEventListener("focusin", f);' in s and 'e.target.closest(".lv-full,.overlay,.ddpop,.deppop' in s
              and "const el = b && b.isConnected ? b : document.querySelector(\".lv-fs\"); if (el) el.focus();" in s, "")
        check("[7] the source dropdowns: a whole group is written as its wildcard, one item off expands it, other lists untouched",
              r.get("on") == ["turn:a", "turn:b", "turn:w1"] and r.get("offOne") == ["mesh:*", "noded", "turn:a", "turn:w1"]
              and r.get("meshOne") == ["mesh:swg_1", "noded", "turn:*"] and r.get("meshAll") == ["mesh:*", "noded", "turn:*"], r)

    guarded("[7]", sec7)
    # ── [8] the code review's fixes ───────────────────────────────────────────────────────────────────────────────────
    print("[8] the code review's fixes")

    def sec8():
        N = load("noded")
        ring = N.RangeRing(50 << 20)
        for i in range(30000):                               # 1-character lines: a segment holds ~8 000 of them,
            ring.add([i, "dns", 6, "q"])                     # and bytes alone would put them all in one part
        sizes = [len(x) for x in N._range_parts(ring)]
        check("[8] a part of short lines is capped by lines too (RANGE_PART_LINES), not bytes alone",
              sizes and max(sizes) <= N.RANGE_PART_LINES and sum(sizes) == 30000, sizes[:4])
        P = load("panel")
        P.range_init(os.path.join(TMP, "fix-spool"))
        st, o = P.range_open({"nodes": ["n1", "n2", "panel"], **RANGE_BODY}, {"n1", "n2"})
        rec = P._RANGE_REQS[o["data"]["id"]]
        k1, k2 = P._live_key(rec, "n1"), P._live_key(rec, "n2")
        base = rec["since"] * 10 ** 6 + 10 ** 6
        many = [[base + i, "dns", 6, "q"] for i in range(P.RANGE_PART_LINES + 500)]
        P.range_absorb({"id": rec["id"], "key": k1, "now": time.time(), "seq": 0, "lines": many})
        check("[8] lines past a part's cap are counted (\"refused\"), never dropped silently",
              rec["ns"]["n1"].get("over") == 500 and rec["ns"]["n1"].get("kept") == P.RANGE_PART_LINES, rec["ns"]["n1"])
        # a server's write in progress: another server's part is not held behind it
        res = []
        rec["locks"]["n1"].acquire()
        th = threading.Thread(target=lambda: res.append(P.range_absorb({"id": rec["id"], "key": k2, "now": time.time(),
                                                                         "seq": 0, "lines": [[base + 7, "noded", 6, "n2 line"]]})))
        th.start(); th.join(5)
        check("[8] one server's write never holds another's (a lock per server)", res and res[0][0] == 200, res)
        # a make started while n1's part is being written waits for it, and has its lines
        rec["phase"] = "making"
        mk = threading.Thread(target=P._range_make, args=(rec,))
        mk.start(); time.sleep(0.4)
        early = rec["phase"]
        P._range_spool(rec, "n1", [(base + 9, "noded", 6, "written while the make waited")], False)
        rec["locks"]["n1"].release()
        mk.join(20)
        txt = gzip.open(rec["dir"] + ".log.gz", "rt").read() if rec["phase"] == "ready" else ""
        check("[8] a make waits for a part being written, and the part is in the file",
              early == "making" and "written while the made waited".replace("made", "make") in txt, (early, rec["phase"], txt[-200:]))
        # the panel's own read finishing after the make started writes nothing
        P._RANGE_REQS.clear()
        run, P._range_panel_run = P._range_panel_run, lambda rec: None   # not the open's own read: under load it could
        st, o = P.range_open({"nodes": ["panel"], **RANGE_BODY, "src": ["panel"]}, set())   # finish before "making" below
        P._range_panel_run = run
        rec2 = P._RANGE_REQS[o["data"]["id"]]
        rec2["phase"] = "making"
        P._live_panel_plan = lambda srcs, rng=False: ({"files": []}, {"panel": "ok"})
        P._range_panel_run(rec2)
        check("[8] the panel's own read, finishing after a make started, writes nothing",
              not os.path.exists(os.path.join(rec2["dir"], "panel.gz")), os.listdir(rec2["dir"]))
        # a make stopped (closed) leaves nothing behind
        st, o = P.range_open({"nodes": ["n1"], **RANGE_BODY}, {"n1"})
        rec3 = P._RANGE_REQS[o["data"]["id"]]
        P.range_absorb({"id": rec3["id"], "key": P._live_key(rec3, "n1"), "now": time.time(), "seq": 0,
                        "lines": [[base + i, "noded", 6, "x"] for i in range(10)], "done": {}})
        rec3["phase"] = "making"
        rec3["stop"].set()
        P._range_make(rec3)
        left = [f for f in os.listdir(P._RANGE_DIR["path"]) if f.startswith(rec3["id"]) and f != rec3["id"]]
        check("[8] a make that is stopped leaves no .part and no file", not left, left)
        # files are deleted outside the store's lock (a sync reply never does disk work under it)
        P._RANGE_REQS.clear()                                # this section's earlier requests: out of the 2-in-progress count
        held = []
        P._range_drop = lambda r, _d=P._range_drop: (held.append(P._RANGE_LOCK.locked()), _d(r))[1]
        st, o = P.range_open({"nodes": ["n1"], **RANGE_BODY}, {"n1"})
        P._RANGE_REQS[o["data"]["id"]]["polled"] = time.time() - 300
        P.range_reply("n1")
        check("[8] an expired request's files are deleted outside the store's lock", held and not any(held), held)
        # the disk guard in the node's units: Cyrillic lines just within the share are all kept
        P._RANGE_REQS.clear()
        st, o = P.range_open({"nodes": ["n1"], **RANGE_BODY}, {"n1"})
        rec4 = P._RANGE_REQS[o["data"]["id"]]
        rec4["share"] = 8 << 20                               # large enough that the guard's 1 MiB slack is not what saves it
        k = P._live_key(rec4, "n1")
        text = "строка " * 20
        per = P.RANGE_LINE_OVER + len(text)
        n = rec4["share"] // per
        for seq, i in enumerate(range(0, n, P.RANGE_PART_LINES)):
            P.range_absorb({"id": rec4["id"], "key": k, "now": time.time(), "seq": seq,
                            "lines": [[base + j, "noded", 6, text] for j in range(i, min(n, i + P.RANGE_PART_LINES))]})
        check("[8] the panel's disk guard counts what the node counts: a server within its share loses nothing",
              not rec4["ns"]["n1"].get("over"), rec4["ns"]["n1"])
        # the node's progress is on a clock: a long scan that yields nothing still says it is alive
        N2 = load("noded")
        posts = []
        N2.RANGE_HB_S = 0.5
        N2._logs_post = lambda rq, extra: (posts.append(extra), "ok")[1]
        N2._live_plan = lambda *a, **k: ({"files": []}, {"noded": "ok"})
        N2.range_read = lambda ring, want, lv, s, u, stop, **k: (time.sleep(2.2), 0)[1]
        N2._range_run({"id": "b" * 16, "stop": threading.Event(), "key": "k", "src": ["noded"], "lv": ["info"],
                       "since": 1, "until": 2, "share": 1 << 20, "iv": 0.5, "off": 0, "url": "", "panel": {}}, [])
        beats = [x for x in posts if "read" in x and "seq" not in x]
        check("[8] a long scan posts its progress on a clock (no false \"failed\" after 2 min)", len(beats) >= 3, posts)
        s = SRC["spa"]
        check("[8] the SPA: the progress counts the request's own servers; Close collapses the panel",
              "const total = v ? Object.keys(v.nodes || {}).length : ids.length" in s
              and 'Object.assign(RG, { id: null, v: null, err: "", saved: false, open: false });' in s, "")

    guarded("[8]", sec8)

    # ── [9] the re-check's fixes ──────────────────────────────────────────────────────────────────────────────────────
    print("[9] the re-check's fixes")

    def sec9():
        P = load("panel")
        P.range_init(os.path.join(TMP, "fix9-spool"))
        st, o = P.range_open({"nodes": ["n1", "panel"], **RANGE_BODY}, {"n1"})
        rec = P._RANGE_REQS[o["data"]["id"]]
        k = P._live_key(rec, "n1")
        base = rec["since"] * 10 ** 6 + 10 ** 6
        P.range_absorb({"id": rec["id"], "key": k, "now": time.time(), "seq": 0, "lines": [[base, "noded", 6, "x"]],
                        "done": {"read": 12345}})
        P.range_absorb({"id": rec["id"], "key": k, "now": time.time(), "read": 5000})
        check("[9] a progress post that lands after a server's parts changes nothing",
              rec["ns"]["n1"]["state"] == "done" and rec["ns"]["n1"]["read"] == 12345, rec["ns"]["n1"])
        rec["ns"]["panel"]["state"] = "skipped"
        P._live_panel_plan = lambda srcs, rng=False: ({"files": []}, {"panel": "ok"})
        P._range_panel_run(rec)
        check("[9] the panel's own read does not revive an entry \"make the file now\" left out",
              rec["ns"]["panel"]["state"] == "skipped", rec["ns"]["panel"])
        # a close while a server's part is being written: the delete waits for it, and nothing stays behind
        rec["locks"]["n1"].acquire()
        th = threading.Thread(target=P.range_api_post, args=("/api/logs/range/close", {"id": rec["id"]}, {}))
        th.start(); time.sleep(0.4)
        waited = th.is_alive()
        P._range_spool(rec, "n1", [(base + 1, "noded", 6, "late")], False)
        rec["locks"]["n1"].release()
        th.join(10)
        check("[9] a close waits for a part being written, then deletes everything (nothing created behind it)",
              waited and not os.path.exists(rec["dir"]) and rec["phase"] == "gone", (waited, os.path.exists(rec["dir"])))
        N = load("noded")
        N._logs_post = lambda rq, extra: "ok" if "st" in extra else "gone"
        N._live_plan = lambda *a, **k: ({"files": []}, {"noded": "ok"})
        stopped = []
        N.range_read = lambda ring, want, lv, s, u, stop, **k: (stopped.append(stop.wait(5)), 0)[1]
        N.RANGE_HB_S = 0.3
        N._range_run({"id": "c" * 16, "stop": threading.Event(), "key": "k", "src": ["noded"], "lv": ["info"],
                      "since": 1, "until": 2, "share": 1 << 20, "iv": 0.3, "off": 0, "url": "", "panel": {}}, [])
        check("[9] a heartbeat the panel answers \"gone\" stops the read", stopped == [True], stopped)
        s = SRC["spa"]
        i = s.index("function stateSay(range)")
        body = s[s.index("return range ?", i):s.index("} : s;", i)]
        check("[9] a range's \"logging is off\" does not tell the operator to pick a level (nothing of the past comes back)",
              'off: [T("Logging is off"), T("Logging is off, so nothing is stored to read."), "warn"]' in body, body[-300:])
        add = s[s.index("function addLines(raw)"):s.index("async function tick()")]
        rows = re.findall(r"<\$\{Row\} key=\$\{([^}]*)\}", s)
        check("[9] a row's key is the line's own id, not node + seq (seq restarts with each request; a reopen keeps the old "
              "lines on screen) — and a tie in time keeps arrival order by it (review §35 #3)",
              rows == ["l.id"] and "id: ++LV.uid" in add and "a.k - b.k || a.id - b.id" in add, (rows, add[-600:]))
        ov = s[s.index("const showOverlay = card =>"):s.index("export function LogOverlay()")]
        hd = s[s.index('<div class="lv-head">'):s.index("<${Facets}/>")]
        check("[9] full screen from the Settings card leaves full screen (the card streams on); from the header or a deep link "
              "it stops the live log (red on hover)", "export const openLogOverlay = () => showOverlay(false);" in ov
              and "onClick=${() => showOverlay(true)}" in hd and '(LV.card ? "" : " warn")' in hd
              and 'LV.card ? T("Leave full screen (Esc)") : T("Stop live log (Esc)")' in hd, hd[:400])

    guarded("[9]", sec9)
finally:
    for p in procs:
        p.terminate()

if PLANT:
    print("\nplant %s: %s" % (PLANT, "CAUGHT (%d red)" % len(FAILS) if FAILS else "NOT caught"))
    sys.exit(0 if FAILS else 1)
print("\nFAIL: %d" % len(FAILS) if FAILS else "\nOK")
sys.exit(1 if FAILS else 0)
