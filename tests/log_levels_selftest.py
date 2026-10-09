#!/usr/bin/env python3
"""Self-test for LOGS-PLAN P1b — log levels: Off · Errors · Warnings · Info · Debug (docs/LOGS-PLAN.md §1, §3, §13).

  [1] The helper (swg-noded's copy): a line above the level is dropped BEFORE it is formatted; `<N>` under journald, a
      letter elsewhere, on every line of a multi-line message; Off drops errors too; Debug is capped per second and the
      excess counted; Debug on top of a base level ends by itself; a crash traceback is written at err.
  [2] The wire, against a real panel: a default fleet's sync reply carries the same `panel` block, byte for byte, as the
      build before levels (4248d11); a level or a Debug shows up as `panel.log`; Debug's deadline is the panel's, a
      save that does not touch the card keeps it, and a stored base level is never Debug.
  [3] The node: an absent key is the defaults; `debug_left` counts down on the node's clock; the level reaches its
      children through one file, written only when it changes; a restart reads it back with Debug as Info.
  [4] The units' drop-ins (noded on a node, netctl on the panel box): none at Info, `warning` below it, `emerg` at Off,
      one daemon-reload per change and none on a steady pass; netctl and update keep `notice` at Info.
  [5] The P2P guard's nft rules lose their `log` below Info — through the real apply path.
  [6] The "why it failed" readers say so when the level is why: turn verify, WDTT verify, the agent's unit start, the
      netctl status tail.
  [7] swg-sni drops a line above the level before queueing it, and its per-host lines are Debug. A full queue's line names
      its cause and keeps to the level (1.8.9 qualification HE-9: "more than 100 a second", written at Errors too).
      Its crash output is its own (HE-5): every traceback line starts "swg-sni: " (what the viewer and `swg-logs sni` file
      it by), a thread's too, and the learned-set flusher outlives a write that raises (a fork refused under memory
      pressure ended it for good, and learning with it).

Run: python3 tests/log_levels_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     eagerfmt     the helper formats a line before deciding to drop it
     nocap        Debug lines are not capped
     (the wire at the defaults is planted by tests/log_budget_selftest.py mbalways)
     nocountdown  the node ignores `debug_left`
     bootdebug    a restart keeps Debug on with no panel to end it
     churn        the drop-ins are rewritten (and systemd reloaded) on every pass
     floor        below Info a unit's cap is `err`, which drops systemd's crash lines
     timercap     netctl and update lose their `notice` cap at Info
     p2plog       the P2P rules keep `log` whatever the level
     nohonest     turn verify gives a bare reason below Info
     snilevel     swg-sni queues a line above the level
     snithread    swg-sni starts its writer (the level re-reader) only for a line that passes
     bootbase     a restart reads the level in force back (Debug over Off comes back as Info)
     agentenv     the agent gets the level only from the environment (sudo strips it)
     updatelog    swg-update's own output is capped away at Info
     hostshwarn   a probe's non-zero exit is a warning (a stopped server, asked every sync)
     hostshquiet  a failed host command nobody checks is only Debug
     latelevel    the panel applies the fleet's level only after its start-up migrations have logged
     debugfile    docker: Debug's end back to Off leaves the panel's file on disk
     nofollow     docker: the panel never starts the loop that checks for Debug's end
     dryquiet     a netctl dry run follows the fleet's level (and prints nothing below Info)
     reverifyinfo the 30-minute reverify counts as "the desired routing moved" (its re-assert pass logged at Info)
     reverifyskip the routing pass is gated on the log line's signature, so the reverify no longer forces a pass
     subfixed     swg-sub logs at Info whatever the fleet's level
     subserve     the panel leaves the level out of swg-sub's serve.json
     relaydst     the relay's --dst test reads the node's level at start
     relaydstloop the relay's --dst test reads the node's level again at its first report
     snidropcause swg-sni's full-queue line blames a rate again ("more than 100 a second")
     snidroplevel swg-sni writes its full-queue line (a warning) whatever the level
     sniprefix    swg-sni's crash traceback is queued without its "swg-sni: " prefix
     snithreadhook swg-sni sets no thread hook (a thread's crash goes out bare, filed at info, unprefixed)
     sniflusher   swg-sni's flusher thread runs the loop bare again (one write that raises ends it)
  [8] swg-sub follows the fleet's level from subs/serve.json (it cannot read panel-settings.json).
  [9] swg-relay's hand-run --dst test prints all it measures — the probe, the listening line, --report's counters — at
      any node level, as 1.8.8 did (1.8.9 qualification HE-10: at Errors only its error line, at Off nothing); the
      relay unit (no --dst) still follows the node's level.
"""
import importlib.machinery, importlib.util, io, json, os, re, socket, subprocess, sys, tempfile, threading, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROG = {k: os.path.join(ROOT, f) for k, f in (("noded", "swg-noded"), ("panel", "swg-panel-server"), ("sni", "swg-sni"),
                                              ("netctl", "swg-netctl"), ("agent", "swg-agent"), ("sub", "swg-sub"),
                                              ("relay", "swg-relay"))}
REF = "4248d11"                                  # the last build before levels: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
TMP = tempfile.mkdtemp(prefix="loglevels-")
os.environ["SWG_LOG_LEVEL_FILE"] = os.path.join(TMP, "none", "log-level")   # nothing from this box leaks in


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""),
          flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {   # (program, anchor, replacement)
    "eagerfmt": ("noded", '''    if prio > _LOG["level"] and prio > log_level():\n        return\n''',
                 '''    _pre = (msg % args) if args else str(msg)\n    if prio > _LOG["level"] and prio > log_level():\n        return\n'''),
    "nocap": ("noded", '''            if _LOG["n"] > LOG_DEBUG_RATE:''', '''            if False:'''),
    "nocountdown": ("noded", '''log_set(min(LOG_LEVELS.get(_lg.get("level"), LOG_INFO), LOG_INFO), _left)''',
                    '''log_set(min(LOG_LEVELS.get(_lg.get("level"), LOG_INFO), LOG_INFO), 0)'''),
    "bootdebug": ("noded", '''        log_set(min(v, LOG_INFO))''', '''        log_set(v, -1 if v == LOG_DEBUG else 0)'''),
    "churn": ("noded", '''        if have == target:\n            continue\n''', ""),
    "floor": ("noded", '''"warning" if lvl < LOG_INFO else None''', '''"err" if lvl < LOG_INFO else None'''),
    "timercap": ("netctl", '''"notice" if lvl == LOG_INFO else None''', '''None'''),
    "p2plog": ("noded", '''logged=log_level() >= LOG_INFO)''', '''logged=True)'''),
    "nohonest": ("noded", '''    return "service didn't stay up: " + reason[:150] + (" — " + nd if nd else "")''',
                 '''    return "service didn't stay up: " + reason[:150]'''),
    "snilevel": ("sni", '''        if prio > _SAY["level"]:\n            return\n''', ""),
    "snithread": ("sni", '''        if _SAY["thread"] is None:                   # BEFORE the level check''',
                  '''        if prio > _SAY["level"]:\n            return\n        if _SAY["thread"] is None:                   # BEFORE the level check'''),
    "bootbase": ("noded", '''            v = int(f.read().split()[-1])''', '''            v = int(f.read().split()[0])'''),
    "agentenv": ("noded", '''    payload = {**payload, "log_level": log_level()}\n''', ""),
    "hostshwarn": ("noded", '''log(LOG_DEBUG if probe else LOG_WARNING, "host_sh rc=%s''', '''log(LOG_WARNING, "host_sh rc=%s'''),
    "hostshquiet": ("noded", '''log(LOG_DEBUG if probe else LOG_WARNING, "host_sh rc=%s''', '''log(LOG_DEBUG, "host_sh rc=%s'''),
    "latelevel": ("panel", '''        panel_log_apply(load_json(fleet.get("panel_settings_path")''', '''        (lambda *a: None)(load_json(fleet.get("panel_settings_path")'''),
    "reverifyinfo": ("noded", '''                _route_moved = _route_sig != last_desired_sig''',
                     '''                _route_moved = _route_sig != last_route_sig'''),
    "reverifyskip": ("noded", '''                if (_route_sig != last_route_sig or _iface_churn''',
                     '''                if (_route_moved or _iface_churn'''),
    "dryquiet": ("netctl", '''    if not DRYRUN:                                   # a dry run''', '''    if True:                                   # a dry run'''),
    "subfixed": ("sub", '''    if not _LOG_SERVE["path"] or time.monotonic()''', '''    if True or time.monotonic()'''),
    "subserve": ("panel", '''           "log": {"level": ps.get("log_level") if ps.get("log_level") in LOG_BASE_LEVELS else "info",''',
                 '''           "_log": {"level": ps.get("log_level") if ps.get("log_level") in LOG_BASE_LEVELS else "info",'''),
    "debugfile": ("panel", '''        if _LOG_FILE["path"] and log_level() == LOG_OFF:''', '''        if False:'''),
    "nofollow": ("panel", '''        threading.Thread(target=_panel_log_follow_loop, name="log-follow", daemon=True).start()''',
                 '''        pass'''),
    "updatelog": ("netctl", '''        caps["swg-update.service"] += "SyslogLevel=%s\\n" % cap\n''', "        pass\n"),
    "relaydst": ("relay", '''        _LOG["level"] = LOG_DEBUG                # counters)''', '''        log_reread()                # counters)'''),
    "snidropcause": ("sni", '''"swg-sni: %d lines not written (queue full, %d waiting)",\n                                     (dropped, SAY_MAX)''',
                     '''"swg-sni: %d lines not written (more than %d a second)",\n                                     (dropped, SAY_RATE)'''),
    "snidroplevel": ("sni", '''        if dropped and LOG_WARNING <= _SAY["level"]:''', '''        if dropped:'''),
    "sniprefix": ("sni", '''    say(LOG_ERR, "\\n".join("swg-sni: " + ln for ln in text.split("\\n")))''', '''    say(LOG_ERR, text)'''),
    "snithreadhook": ("sni", '''threading.excepthook = lambda a: _say_excepthook(a.exc_type, a.exc_value, a.exc_traceback)\n''', ""),
    "sniflusher": ("sni", '''target=self._flush_forever, name="swg-sni-flush"''', '''target=self._flush_loop, name="swg-sni-flush"'''),
    "relaydstloop": ("relay", '''            if not a.dst:\n                log_reread()                     # the level may have moved''',
                     '''            if True:\n                log_reread()                     # the level may have moved'''),
}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PROG.items()}
if PLANT:
    f, a, b = PLANTS[PLANT]
    assert SRC[f].count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC[f] = SRC[f].replace(a, b)


def write_prog(key, name=None):
    p = os.path.join(tempfile.mkdtemp(prefix="loglevels-prog-"), name or os.path.basename(PROG[key]))
    open(p, "w", encoding="utf-8").write(SRC[key])
    return p


def load(key, env=None):
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    p = write_prog(key)
    ld = importlib.machinery.SourceFileLoader("ll_" + key + str(time.monotonic_ns()), p)
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
    return m


class Buf(io.StringIO):
    pass


def capture(m):
    """Point the module's log stream at a buffer, outside journald (letters)."""
    b = Buf()
    m._LOG_STREAM = b
    m._LOG_JOURNAL = False
    return b


NSTATE = os.path.join(TMP, "noded-state")
os.makedirs(NSTATE)
N = load("noded", {"SWG_NODED_STATE": NSTATE})
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__   # the module set its own

# ── [1] the helper ──────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the helper")


class Counted:
    n = 0

    def __str__(self):
        Counted.n += 1
        return "x"


b = capture(N)
N.log_set(N.LOG_INFO)
N.log(N.LOG_DEBUG, "dbg %s", Counted())
check("[1] a Debug line at Info is dropped before it is formatted", Counted.n == 0 and b.getvalue() == "", Counted.n)
N.log(N.LOG_WARNING, "two\nlines %s", Counted())
check("[1] outside journald: a letter on every line", b.getvalue() == "W two\nW lines x\n", repr(b.getvalue()))
N._LOG_JOURNAL = True
b.truncate(0); b.seek(0)
N.log(N.LOG_ERR, "a\nb")
check("[1] under journald: `<N>` on every line", b.getvalue() == "<3>a\n<3>b\n", repr(b.getvalue()))
N._LOG_JOURNAL = False
b.truncate(0); b.seek(0)
N.log_set(N.LOG_OFF)
N.log(N.LOG_ERR, "an error")
check("[1] Off drops errors too", b.getvalue() == "")
N.log_set(N.LOG_INFO, 1)
check("[1] Debug for n seconds on top of the base", N.log_level() == N.LOG_DEBUG)
time.sleep(1.1)
check("[1] …and it ends by itself, back to the base", N.log_level() == N.LOG_INFO)
N.log_set(N.LOG_ERR, -1)
check("[1] Debug until changed (-1)", N.log_level() == N.LOG_DEBUG)
while int(time.monotonic() * 10) % 10 > 3:      # start the burst early in a second, so it stays inside one
    time.sleep(0.02)
b.truncate(0); b.seek(0)
for i in range(N.LOG_DEBUG_RATE + 50):
    N.log(N.LOG_DEBUG, "d%d", i)
written = b.getvalue().count("\n")
check("[1] Debug is capped per second", written == N.LOG_DEBUG_RATE, written)
time.sleep(1.05)
N.log(N.LOG_INFO, "next")
check("[1] …and the excess is counted in one line", "50 debug lines not written" in b.getvalue(), b.getvalue()[-200:])
N.log_set(N.LOG_ERR)
b.truncate(0); b.seek(0)
try:
    raise RuntimeError("boom")
except RuntimeError:
    N._log_excepthook(*sys.exc_info())
check("[1] a crash traceback is written at err, every line", b.getvalue().startswith("E Traceback")
      and all(ln.startswith("E ") for ln in b.getvalue().splitlines()), b.getvalue()[:200])
N.log_set(N.LOG_INFO)

# ── [2] the wire, against a real panel ──────────────────────────────────────────────────────────────────────────────
print("[2] the wire")


def start_panel(src_path, tag, settings=None):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    if settings is not None:
        json.dump(settings, open(os.path.join(state, "panel-settings.json"), "w"))
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
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
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
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {})})
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
    pn, port_n, state_n = start_panel(write_prog("panel"), "new"); procs.append(pn)
    tok_r = req(port_r, "/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    tok_n = req(port_n, "/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    rr, rn = sync(port_r, tok_r), sync(port_n, tok_n)
    check("[2] a default fleet: the `panel` block is byte-identical to the build before levels",
          json.dumps(rr.get("panel")) == json.dumps(rn.get("panel")), (rr.get("panel"), rn.get("panel")))
    check("[2] …and so is the reply's set of keys", list(rr) == list(rn), (list(rr), list(rn)))

    def setlog(body):
        return req(port_n, "/api/panel/settings", body)

    c, _r = setlog({"log_level": "debug"})
    check("[2] Debug is never a stored base level", c == 400, (c, _r))
    setlog({"log_level": "error"})
    _sv = json.load(open(os.path.join(state_n, "subs", "serve.json")))
    check("[2] …and swg-sub's serve.json carries it", (_sv.get("log") or {}).get("level") == "error", _sv.get("log"))
    check("[2] a level reaches the node as panel.log", sync(port_n, tok_n)["panel"].get("log") == {"level": "error"},
          sync(port_n, tok_n)["panel"].get("log"))
    setlog({"log_level": "error", "log_debug": 3600})
    lg = sync(port_n, tok_n)["panel"].get("log") or {}
    check("[2] Debug for an hour: the base stays, debug_left counts on the panel's clock",
          lg.get("level") == "error" and 3590 <= (lg.get("debug_left") or 0) <= 3600, lg)
    until = json.load(open(os.path.join(state_n, "panel-settings.json"))).get("log_debug_until")
    setlog({"top_talkers": 12})
    check("[2] a save that does not touch the card keeps Debug's deadline",
          json.load(open(os.path.join(state_n, "panel-settings.json"))).get("log_debug_until") == until)
    st = req(port_n, "/api/state")[1]
    left = ((st.get("data") or st).get("panel_settings") or {}).get("log_debug_left")
    check("[2] /api/state carries the time left on the panel's clock", isinstance(left, int) and 3590 <= left <= 3600, left)
    setlog({"log_level": "warning", "log_debug": -1})
    check("[2] Debug until changed is -1", sync(port_n, tok_n)["panel"].get("log") == {"level": "warning", "debug_left": -1})
    setlog({"log_level": "info", "log_debug": 0})
    check("[2] back to the defaults: the key is gone again", "log" not in sync(port_n, tok_n)["panel"])
    c, _r = setlog({"log_debug": 120})
    check("[2] a Debug duration that is not offered is refused", c == 400, (c, _r))
    # A FRESH state with Off already set: its first start runs the one-time migrations and repairs, which log before
    # the settings store is loaded — the lines the early apply exists for.
    po, _po, _so = start_panel(write_prog("panel"), "off", {"log_level": "off", "log_debug_until": 0}); procs.append(po)
    time.sleep(0.5)
    out = open(os.path.join(TMP, "panel-off", "panel.log")).read()
    check("[2] a panel started at Off writes nothing, its start-up migrations and repairs included", out == "", out[:300])
finally:
    for p in procs:
        p.terminate()
        with __import__("contextlib").suppress(Exception):
            p.wait(5)

P = load("panel")
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
pb = capture(P)
P.panel_log_apply({"log_level": "off", "log_debug_until": 0})
P.log(P.LOG_ERR, "panel error")
check("[2] the panel's own lines follow the level: Off", pb.getvalue() == "" and P.log_level() == P.LOG_OFF, pb.getvalue())
P.panel_log_apply({"log_level": "error", "log_debug_until": int(time.time()) + 60})
check("[2] …and Debug on top of a base while its time runs", P.log_level() == P.LOG_DEBUG)
P.panel_log_apply({"log_level": "warning", "log_debug_until": int(time.time()) - 1})
check("[2] …and the base once it has passed", P.log_level() == P.LOG_WARNING)
# docker: Debug on top of Off writes the panel's file; when Debug's time is up the file goes, as a save to Off removes it
_plf = os.path.join(TMP, "plog", "swg-panel.log")
P.PANEL_LOG_FILE["path"] = _plf
P.panel_log_apply({"log_level": "off", "log_debug_until": int(time.time()) + 2})
P.log(P.LOG_DEBUG, "panel debug line")
P.panel_log_follow()                                   # Debug still on: kept
_had = os.path.exists(_plf)
while P.log_level() != P.LOG_OFF:
    time.sleep(0.1)
P.panel_log_follow()
check("[2] docker: Debug's end back to Off removes the panel's file — kept while Debug runs (review §35 #2)",
      _had and not os.path.exists(_plf), (_had, os.path.exists(_plf)))
check("[2] …checked by a loop the docker panel starts",
      re.search(r'if PANEL_LOG_FILE\["path"\]:[^\n]*\n\s+threading\.Thread\(target=_panel_log_follow_loop', SRC["panel"])
      is not None and "panel_log_follow()" in SRC["panel"][SRC["panel"].index("def _panel_log_follow_loop"):])
P.PANEL_LOG_FILE["path"] = None
P.log_file(None, 0)

# ── [3] the node ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] the node")
N.apply_panel_settings({"geo_epoch": 0})
check("[3] an absent `log` is the defaults", N.log_level() == N.LOG_INFO)
N.apply_panel_settings({"geo_epoch": 0, "log": {"level": "off"}})
check("[3] Off", N.log_level() == N.LOG_OFF)
N.apply_panel_settings({"geo_epoch": 0, "log": {"level": "error", "debug_left": 1}})
check("[3] debug_left: Debug now…", N.log_level() == N.LOG_DEBUG)
time.sleep(1.1)
check("[3] …and the base once the node's own clock has run it out", N.log_level() == N.LOG_ERR)
N.apply_panel_settings({"geo_epoch": 0, "log": {"level": "debug"}})
check("[3] a base level of debug from the wire is read as Info", N.log_level() == N.LOG_INFO)

N.NODE_KIND = "docker"                              # [3] is the file only; the drop-ins are [4]
lf = N.LOG_LEVEL_FILE
N.log_set(N.LOG_WARNING)
N._log_follow({})
check("[3] the children's file holds the level in force, then the base", open(lf).read() == "4 4\n", open(lf).read())
os.utime(lf, (1, 1))
N._log_follow({})
check("[3] …written only when it changes", os.stat(lf).st_mtime == 1)
for v, want in (("7\n", N.LOG_INFO), ("-1\n", N.LOG_OFF), ("3\n", N.LOG_ERR), ("7 -1\n", N.LOG_OFF), ("7 4\n", N.LOG_WARNING)):
    open(lf, "w").write(v)
    N.log_set(N.LOG_INFO)
    N._log_boot()
    check("[3] a restart reads the base back (%s → %d); Debug never comes back" % (v.strip(), want), N.log_level() == want,
          N.log_level())

# ── [4] the drop-ins ────────────────────────────────────────────────────────────────────────────────────────────────
print("[4] drop-ins")
DD = os.path.join(TMP, "run-systemd-system"); os.makedirs(DD)
N.LOG_DROPIN_DIR = DD
N.NODE_KIND = "baremetal"
RELOADS = []
_real_run = N.run
N.run = lambda args, **kw: (RELOADS.append(args) if args[:2] == ["systemctl", "daemon-reload"] else None) or \
    types.SimpleNamespace(returncode=0, stdout="", stderr="")
CFG = {"interfaces": {"awg0": {"cmd": ["awg"]}, "wg1": {"cmd": ["wg"]}}}


def dropins():
    out = {}
    for root, _d, files in os.walk(DD):
        for f in files:
            out[os.path.relpath(os.path.join(root, f), DD)] = open(os.path.join(root, f)).read()
    return out


N._LOG_FOLLOWED.update(lvl=None, units=None)
N.log_set(N.LOG_INFO)
N._log_follow(CFG)
check("[4] Info: no drop-in at all, no reload", dropins() == {} and not RELOADS, (dropins(), RELOADS))
N.log_set(N.LOG_ERR)
N._log_follow(CFG)
d = dropins()
want = {u + ".d/swg-log.conf" for u in N.LOG_DROPIN_UNITS} | {"awg-quick@awg0.service.d/swg-log.conf",
                                                              "wg-quick@wg1.service.d/swg-log.conf"}
check("[4] Errors: third-party prefix drop-ins + one per interface of ours, none for our own long-running units",
      set(d) == want and not any(k.startswith(("swg-noded", "swg-relay")) for k in d), sorted(set(d) ^ want))
check("[4] …capped at warning, never err (systemd's crash lines)",
      all(v == "[Service]\nLogLevelMax=warning\n" for v in d.values()), set(d.values()))
check("[4] …and one daemon-reload", len(RELOADS) == 1, RELOADS)
N._LOG_FOLLOWED["units"] = None                     # as after a restart of noded: the files are already right
N._log_follow(CFG)
check("[4] a steady pass rewrites nothing and reloads nothing", len(RELOADS) == 1, RELOADS)
N.log_set(N.LOG_OFF)
N._log_follow({"interfaces": {"awg0": {"cmd": ["awg"]}}})
d = dropins()
check("[4] Off: emerg; a deleted interface's drop-in goes", all(v.endswith("LogLevelMax=emerg\n") for v in d.values())
      and "wg-quick@wg1.service.d/swg-log.conf" not in d and len(RELOADS) == 2, (sorted(d), RELOADS))
os.makedirs(os.path.join(DD, "awg-quick@awg0.service.d"), exist_ok=True)
open(os.path.join(DD, "awg-quick@awg0.service.d", "operator.conf"), "w").write("[Service]\n")
N.log_set(N.LOG_DEBUG)
N._log_follow({"interfaces": {"awg0": {"cmd": ["awg"]}}})
d = dropins()
check("[4] Debug: ours removed, an operator's own drop-in beside it kept",
      d == {"awg-quick@awg0.service.d/operator.conf": "[Service]\n"} and len(RELOADS) == 3, (d, RELOADS))
N.run = _real_run

NC = load("netctl")
NC.log_set(NC.LOG_INFO)
caps = NC.log_unit_caps(NC.LOG_INFO)
check("[4] netctl at Info: only the two timer units, at notice (the panel and swg-sub filter themselves)",
      set(caps) == {"swg-netctl.service", "swg-update.service"} and caps["swg-netctl.service"] == "LogLevelMax=notice\n", caps)
check("[4] …and swg-update's own output is filed at notice, so the cap keeps why an update failed",
      caps.get("swg-update.service") == "LogLevelMax=notice\nSyslogLevel=notice\n", caps)
check("[4] netctl at Debug: nothing capped", set(NC.log_unit_caps(NC.LOG_DEBUG).values()) == {None})
check("[4] netctl at Errors: warning — and swg-update's output filed at warning, so a failed update still shows",
      NC.log_unit_caps(NC.LOG_ERR) == {"swg-netctl.service": "LogLevelMax=warning\n",
                                       "swg-update.service": "LogLevelMax=warning\nSyslogLevel=warning\n"},
      NC.log_unit_caps(NC.LOG_ERR))
check("[4] netctl at Off: emerg, nothing kept", set(NC.log_unit_caps(NC.LOG_OFF).values()) == {"LogLevelMax=emerg\n"})
PS = os.path.join(TMP, "netctl-state"); os.makedirs(PS)
NC.STATE_DIR = PS
json.dump({"log_level": "warning", "log_debug_until": int(time.time()) + 600}, open(os.path.join(PS, "panel-settings.json"), "w"))
NC.log_from_settings()
check("[4] netctl reads the level from the settings: Debug while its time runs", NC.log_level() == NC.LOG_DEBUG)
json.dump({"log_level": "warning", "log_debug_until": int(time.time()) - 5}, open(os.path.join(PS, "panel-settings.json"), "w"))
NC.log_from_settings()
check("[4] …and the base once it has passed, with nothing written at expiry", NC.log_level() == NC.LOG_WARNING)
ND = os.path.join(TMP, "netctl-run"); os.makedirs(ND)
NC.LOG_DROPIN_DIR = ND
NR = []
NC.run = lambda argv, **kw: (NR.append(argv), (0, ""))[1]
NC.log_dropins()
NC.log_dropins()
nfiles = sorted(os.listdir(ND))
check("[4] netctl writes the timer units' two, once, and reloads once",
      nfiles == sorted(u + ".d" for u in caps) and NR == [["systemctl", "daemon-reload"]], (nfiles, NR))

PSD = os.path.join(TMP, "netctl-dry"); os.makedirs(PSD)
json.dump({"log_level": "warning"}, open(os.path.join(PSD, "panel-settings.json"), "w"))
r = subprocess.run([sys.executable, write_prog("netctl"), "set-listen", "sub", "127.0.0.1", "9444"], capture_output=True,
                   text=True, timeout=60, env={**os.environ, "SWG_NETCTL_DRYRUN": "1", "SWG_STATE_DIR": PSD,
                                                "SWG_UNIT_DIR": os.path.join(PSD, "units")})
check("[4] a netctl dry run prints what it would do, whatever the fleet's level", "would write" in r.stderr,
      (r.returncode, r.stderr[-300:]))

# ── [5] P2P ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[5] P2P guard")
NFT = []


def fake_run(args, input_text=None, timeout=20):
    if args[:2] == ["nft", "-f"]:
        NFT.append(input_text)
    rc = 1 if args[:3] == ["nft", "list", "table"] else 0
    return types.SimpleNamespace(returncode=rc, stdout="", stderr="")


N.run = fake_run
N._p2p_ih_ok = lambda: True
N.GEO_DIR = os.path.join(TMP, "geo"); os.makedirs(N.GEO_DIR)
for lvl in (N.LOG_INFO, N.LOG_WARNING):
    N.log_set(lvl)
    N._P2P.update(tbl=None)
    with __import__("contextlib").suppress(OSError):
        os.unlink(os.path.join(N.GEO_DIR, ".p2p.sig"))
    N._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
check("[5] the rules are applied", len(NFT) == 2, len(NFT))
check("[5] at Info the hit lines are logged", len(NFT) == 2 and "log prefix" in NFT[0])
check("[5] below Info no `log` statement is left", len(NFT) == 2 and "log prefix" not in NFT[1] and " drop" in NFT[1],
      NFT[1][:300] if len(NFT) == 2 else "")
N.run = _real_run
loop = SRC["noded"][SRC["noded"].find("_route_sig = json.dumps("):]
check("[5] crossing Info re-runs the routing pass (the level is in its signature)",
      "log_level() >= LOG_INFO" in loop[:loop.find("sort_keys=True")])

# ── [6] honest readers ──────────────────────────────────────────────────────────────────────────────────────────────
print("[6] why it failed")
REAL_HOST_SH = N.host_sh
N.host_sh = lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="failed\n", stderr="")
N.log_set(N.LOG_INFO)
check("[6] turn verify at Info: the usual reason", "logging" not in N._turn_verify("vk-turn-proxy-x"))
N.log_set(N.LOG_OFF)
check("[6] turn verify at Off: says the level is why", "its own lines are not kept (logging is off)" in N._turn_verify("vk-turn-proxy-x"),
      N._turn_verify("vk-turn-proxy-x"))
N.log_set(N.LOG_ERR)
N.host_sh = lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="failed\nx.service: Failed with result 'exit-code'.\n",
                                                    stderr="")
check("[6] …at Errors too, beside systemd's own bare line",
      N._turn_verify("x").endswith("its own lines are not kept (logging is set to errors)"), N._turn_verify("x"))
N.host_sh = lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="failed\n", stderr="")
check("[6] WDTT verify below Info", "its own lines are not kept (logging is set to errors)" in N._wdtt_verify("swg-wdtt-x"),
      N._wdtt_verify("swg-wdtt-x"))
A = load("agent")
for env, want in (("-1", "logging is off"), ("4", "logging is set to warnings"), ("6", "")):
    os.environ["SWG_LOG_LEVEL"] = env
    got = A._log_no_detail()
    check("[6] agent unit start at %s" % env, (want in got) if want else got == "", got)
os.environ.pop("SWG_LOG_LEVEL", None)
NC.log_set(NC.LOG_OFF)
# NRestarts before · restart · is-active (down) · NRestarts after · status
_seq = iter([(0, "0"), (0, ""), (3, "inactive"), (0, "1"), (0, "● swg-sub.service\n   Active: failed")])
NC.run = lambda argv, **kw: next(_seq)
NC.DRYRUN = False
NC.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time, monotonic=time.monotonic)
try:
    NC.do_restart("sub")
    msg = ""
except NC.Reject as e:
    msg = str(e)
check("[6] netctl status tail at Off says why it shows no lines", msg.endswith("its own lines are not kept (logging is off)"), msg)
SENT = []
N.run = lambda args, input_text=None, timeout=20: (SENT.append(json.loads(input_text)),
                                                    types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr=""))[1]
N.log_set(N.LOG_OFF)
N.run_agent("/x/swg-agent", True, {"op": "list-peers"})
N.run = _real_run
check("[6] the level reaches the agent in its request (sudo -n strips the environment)",
      SENT and SENT[0].get("log_level") == N.LOG_OFF, SENT)

N.NODE_KIND = "baremetal"
N.host_sh = REAL_HOST_SH
hb = capture(N)
N.log_set(N.LOG_WARNING)
N.host_sh("exit 3", probe=True)
check("[6] a probe's non-zero exit (the answer, asked every sync) is not a warning", hb.getvalue() == "", hb.getvalue())
N.host_sh("exit 3")
check("[6] …a failed host command that nobody checks is one", "W host_sh rc=3" in hb.getvalue(), hb.getvalue())
N.log_set(N.LOG_DEBUG)
hb.truncate(0); hb.seek(0)
N.host_sh("exit 3", probe=True)
check("[6] …and the probe's is Debug", "D host_sh rc=3" in hb.getvalue(), hb.getvalue())
N.log_set(N.LOG_INFO)
probes = re.findall(r'host_sh\("systemctl is-active [^\n]*', SRC["noded"])
check("[6] every per-sync `systemctl is-active` probe is marked a probe (the two verifies end in `| tail`, rc 0)",
      all("probe=True" in p for p in probes if "sleep 1.5" not in p) and len(probes) >= 5, probes)
rl = SRC["noded"][SRC["noded"].find("_errs = (r['errors']"):]
rl = rl[:rl.find("reconcile: +%s")]
check("[6] reconcile summary: an interface re-set, and routing applied for a MOVED desired state, are Info",
      'ri["changed"]' in rl and "_route_moved and" in rl)
mv = re.search(r"_route_moved = _route_sig != (\w+)", SRC["noded"])
rv = SRC["noded"][SRC["noded"].find("_force_reverify(); last_route_sig = None"):][:200]
check("[6] …'moved' is judged against what the last pass APPLIED, which the reverify does not clear",
      bool(mv) and mv.group(1) not in ("last_route_sig",) and mv.group(1) not in rv, mv.group(1) if mv else None)
check("[6] …and the routing pass is still triggered by last_route_sig, which the reverify clears to force it",
      "if (_route_sig != last_route_sig or" in SRC["noded"])
wg = re.findall(r'host_sh\("wg show [^\n]*', SRC["noded"])
check("[6] reads of a server's device (gone while it is stopped) are probes", wg and all("probe=True" in w for w in wg), wg)
ap = SRC["noded"][SRC["noded"].find('apply_panel_settings(reply.get("panel"))'):]
check("[6] a new level is followed in the same pass the sync applied it", ap[:400].count("_log_follow(node_cfg)") == 1)

# ── [7] swg-sni ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("[7] swg-sni")
lvl_file = os.path.join(TMP, "sni-level")
open(lvl_file, "w").write("6\n")
S = load("sni", {"SWG_LOG_LEVEL_FILE": lvl_file})
S.sys = types.SimpleNamespace(stdout=io.StringIO())   # its writer thread writes there, not into this test's output
check("[7] it starts at the level in the file", S._SAY["level"] == 6)
open(lvl_file, "w").write("4 4\n")
S0 = load("sni", {"SWG_LOG_LEVEL_FILE": lvl_file})
S0.sys = types.SimpleNamespace(stdout=io.StringIO())
S0.say(S0.LOG_INFO, "swg-sni: bound queue …")
check("[7] started below Info, its first line dropped, the writer that re-reads the level runs anyway",
      S0._SAY["level"] == 4 and S0._SAY["thread"] is not None and len(S0._SAY["q"]) == 0)
open(lvl_file, "w").write("6 6\n")
S.say(S.LOG_DEBUG, "swg-sni: %s → %s  (+%s)", "example.org", S._Join(["ads"]), "1.2.3.4")
check("[7] a Debug line at Info is not even queued", len(S._SAY["q"]) == 0, list(S._SAY["q"]))
open(lvl_file, "w").write("7\n")
S._say_level()
S.say(S.LOG_DEBUG, "swg-sni: %s → %s  (+%s)", "example.org", S._Join(["ads", "trk"]), "1.2.3.4")
check("[7] at Debug it is, formatted only when written",
      S._say_text(*S._SAY["q"][0]) == "D swg-sni: example.org → ads, trk  (+1.2.3.4)\n" if S._SAY["q"] else False)
per_host = re.findall(r'say\((LOG_\w+), "swg-sni: %s → ', SRC["sni"])
check("[7] both per-host lines are Debug (users' visited hosts stay out of the default level)",
      per_host == ["LOG_DEBUG", "LOG_DEBUG"], per_host)


def sni_at(level):
    """A fresh swg-sni whose level file says `level`; what its writer writes lands in its own buffer."""
    open(lvl_file, "w").write(level + "\n")
    m = load("sni", {"SWG_LOG_LEVEL_FILE": lvl_file})
    m.sys = types.SimpleNamespace(stdout=io.StringIO())
    return m


def written(m, until=lambda o: False, secs=3.0):
    """What `m`'s writer has written, once `until` holds or `secs` have passed."""
    end = time.monotonic() + secs
    while not until(m.sys.stdout.getvalue()) and time.monotonic() < end:
        time.sleep(0.05)
    return m.sys.stdout.getvalue()


for lv, what in (("3 3", "Errors"), ("6 6", "Info")):
    S9 = sni_at(lv)
    for i in range(S9.SAY_MAX + 500):                  # more than the queue holds, at once
        S9.say(S9.LOG_ERR, "swg-sni: err %d", i)
    o = written(S9, (lambda o: "not written" in o) if what == "Info" else (lambda o: False), 2.5)
    full = [l for l in o.splitlines() if "not written" in l]
    if what == "Errors":
        check("[7] at Errors a full queue's line (a warning) is not written; the errors are",
              not full and "E swg-sni: err 0" in o, full[:2])
    else:
        check("[7] at Info it is, naming its cause — the queue was full (not a rate)",
              len(full) == 1 and re.fullmatch(r"W swg-sni: \d+ lines not written \(queue full, %d waiting\)" % S9.SAY_MAX, full[0]),
              full[:2])

S5 = sni_at("6 6")
try:
    raise OSError(98, "NFQUEUE bind: Address already in use")
except OSError:
    sys.excepthook(*sys.exc_info())                     # the hook the module set: a crash at start
o = written(S5, lambda o: "OSError" in o)
tb = [l for l in o.splitlines() if l.startswith("E ")]
check("[7] a crash's traceback: at err, every line starting \"swg-sni: \" (swg-logs sni and the viewer file it by that)",
      len(tb) >= 3 and all(l.startswith("E swg-sni: ") for l in tb) and "E swg-sni: Traceback (most recent call last):" in tb,
      tb[:3])
threading.Thread(target=lambda: 1 / 0, name="t-he5").start()
o = written(S5, lambda o: "ZeroDivisionError" in o)
check("[7] …a thread's crash too: through swg-sni's own hook, prefixed, at err",
      "E swg-sni: ZeroDivisionError: division by zero" in o and "E swg-sni: Traceback" in o.split("OSError")[-1], o[-300:])
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
NFT5 = []


def nft5(argv, input=None, **kw):
    NFT5.append(input)
    if len(NFT5) == 1:
        raise BlockingIOError(11, "Resource temporarily unavailable")    # fork refused under memory pressure
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


S5.subprocess = types.SimpleNamespace(run=nft5)
C5 = S5.Classifier(os.path.join(TMP, "no-map", "sni-map.json"), "swg_smart")   # the real constructor starts the real flusher
for ip in ("192.0.2.1", "192.0.2.2"):
    with C5._lock:
        C5._pending.append(("c1", ip))
    C5._wake.set()
    end = time.monotonic() + 3
    while C5._pending and time.monotonic() < end:
        time.sleep(0.05)
    time.sleep(0.2)
o = written(S5, lambda o: "BlockingIOError" in o)
check("[7] the learned-set flusher outlives a write that raises: the next learn is written, the pending list drained",
      len(NFT5) == 2 and "192.0.2.2" in (NFT5[-1] or "") and not C5._pending, (len(NFT5), C5._pending))
check("[7] …and what it raised is said at err, prefixed", "E swg-sni: BlockingIOError: [Errno 11]" in o, o[-300:])

# ── [8] swg-sub ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("[8] swg-sub")
U = load("sub")
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
ub = capture(U)
sv = os.path.join(TMP, "serve.json")
U._LOG_SERVE["path"] = sv
json.dump({"enabled": True, "log": {"level": "off", "debug_until": 0}}, open(sv, "w"))
U.log(U.LOG_ERR, "swg-sub: config reload failed: x")
check("[8] Off in serve.json: swg-sub writes nothing", ub.getvalue() == "", ub.getvalue())
json.dump({"enabled": True, "log": {"level": "off", "debug_until": int(time.time()) + 60}}, open(sv, "w"))
U._LOG_SERVE["at"] = -99
U.log(U.LOG_DEBUG, "swg-sub: dbg")
check("[8] Debug over Off while its time runs", "D swg-sub: dbg" in ub.getvalue(), ub.getvalue())
json.dump({"enabled": True}, open(sv, "w"))
U._LOG_SERVE["at"] = -99
U.log(U.LOG_INFO, "swg-sub: serving")
check("[8] a serve.json from before levels: Info", "I swg-sub: serving" in ub.getvalue(), ub.getvalue())

# ── [9] swg-relay's --dst test ──────────────────────────────────────────────────────────────────────────────────────
print("[9] swg-relay's hand-run --dst test")
RL = write_prog("relay")


def relay_run(level, *args):
    """The real swg-relay for ~2.5 s on a node whose level file says `level`: what it wrote."""
    lf = os.path.join(TMP, "relay-level"); open(lf, "w").write(level + "\n")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, SWG_LOG_LEVEL_FILE=lf); env.pop("JOURNAL_STREAM", None)
    p = subprocess.Popen([sys.executable, RL, "--host", "127.0.0.1", "--port", str(port)] + list(args), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2.5)
    p.terminate()
    return p.communicate(timeout=10)[0]


for lv, what in (("3 3", "Errors"), ("-1 -1", "Off")):
    o = relay_run(lv, "--dst", "127.0.0.1:9", "--report", "1")
    check("[9] at %s the --dst test prints its probe and its listening line" % what,
          "I relay: pipe requested=" in o and "I relay: cc requested=" in o and "I relay: listening " in o, o[-400:])
    check("[9] …and --report's counters, as 1.8.8 did", o.count("D relay: accepted=") >= 1, o[-400:])
o = relay_run("3 3")
check("[9] the relay unit (no --dst) still follows the node's level: at Errors its error line alone",
      "relay: IP_TRANSPARENT" in o and "relay: pipe requested=" not in o and "relay: listening" not in o
      if os.geteuid() else "relay: pipe requested=" not in o and "relay: listening" not in o, o[-400:])

print()
if PLANT:
    print("PLANT %s: %s" % (PLANT, "caught (RED) ✓" if FAILS else "NOT caught ✗"))
    sys.exit(0 if FAILS else 1)
print("FAIL: %d — %s" % (len(FAILS), FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
