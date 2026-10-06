#!/usr/bin/env python3
"""Self-test for LOGS-PLAN P1c — the disk budget: swg's own journals, an MB per node and for the panel (docs/LOGS-PLAN.md
§2, §7, §18).

  [1] The wire and the stored fields, against a real panel: a default fleet's `panel` block is byte-identical to the build
      before levels (4248d11); a node's budget rides as `panel.log.mb` and only then; budgets are stored only when not 100,
      at least 16; `log_mb` is PUBLISHED and survives a save of another field on the node; the node's report and the
      panel's (netctl's status file) reach /api/state; a NixOS panel says it has no budget of its own.
  [2] The node's size file: nothing before a panel reply; written once, journald restarted once, then nothing on a steady
      pass or a restart with the same budget; Off is Storage=none and removes what was stored; a failing restart is said
      once and reported as `err`.
  [3] The status: used bytes on disk, the oldest ARCHIVED file's head time (a damaged `~` file skipped, nothing while only
      the active file exists).
  [4] The namespace on the units the node writes: prefix drop-ins beside them, written once; the unit texts the drift checks
      compare carry no LogNamespace (a changed text would restart a datapath unit).
  [5] docker: our own log file (timestamped, two files of half the budget, removed at Off); a launched container's share,
      or no log at all at Off; the supervised logs emptied at Off.
  [6] swg-netctl, the panel box's writer: the size file from panel-settings.json, the status file only when it changes and
      kept out of the 1-hour sweep, Off removes the stored files.
  [7] The verify readers read the namespace and give the unit's own reason even when systemd's line sorts after it.
  [8] Uninstall removes the drop-ins, the size file, the journal and swg-logs (the last only with the last unit); an
      operator's own drop-in stays.
  [9] swg-logs maps a source to journalctl over the right namespace and refuses a name with shell characters; update.sh
      writes the drop-ins before it restarts anything.

Run: python3 tests/log_budget_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     mbalways     the wire carries `log` at the defaults (a default fleet's reply is no longer byte-identical)
     mbdropped    a node's budget never reaches it while the level is at its default
     unpublished  the panel does not publish the node's `log_mb`
     store100     a budget of 100 is stored instead of dropped
     nopersist    the node forgets its budget at a restart (after a reboot it runs at journald's defaults until the panel answers)
     jdchurn      the node restarts journald on every pass
     offkeeps     Off stores nothing new but keeps what is on disk
     tilde        the oldest-file parser takes a damaged `….journal~`
     unittext     LogNamespace goes into the relay's unit text (every relay restarts at the update)
     dockeroff    a container launched at Off still logs
     norotate     the docker log file is never rotated
     sweeplog     netctl's status sweep removes the budget's status file
     headold      nothing rotated yet: the node reports no oldest line (Holds stays blank)
     ncheadold    …the same in netctl's copy (the panel's row)
     dockold      docker: the oldest line read from the newer half, not `.1`
     paneloldest  the docker panel's row reports no oldest line
     holdsfull    the SPA says how far back only once the budget is full
     barfull      the used bar changes colour with the fill
     netctlrc     netctl reads its run() as a CompletedProcess (Off then never removes the files)
     noretry      netctl leaves the new size file in place when journald does not restart (never retried, reads as applied)
     noderetry    swg-noded leaves the new size file in place when journald does not restart (a restart reads it as applied)
     pid1last     the verify reader takes systemd's own line as the reason
     pid1all      the verify reader drops every systemd line, the exec failure's reason among them
     stickyerr    a failed restart's error stays after the budget is put back to the size in force
     uninstkeep   uninstall leaves the journal on disk
"""
import importlib.machinery, importlib.util, io, json, os, re, shutil, socket, stat, struct, subprocess, sys, tempfile, threading
import time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROG = {k: os.path.join(ROOT, f) for k, f in (("noded", "swg-noded"), ("panel", "swg-panel-server"), ("netctl", "swg-netctl"),
                                              ("uninstall", "uninstall.sh"), ("logs", "swg-logs"), ("update", "update.sh"),
                                              ("spa", "js/screen-settings.js"), ("css", "app.css"))}
REF = "4248d11"                                  # the last build before levels: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
TMP = tempfile.mkdtemp(prefix="logbudget-")
os.environ["SWG_LOG_LEVEL_FILE"] = os.path.join(TMP, "none", "log-level")


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""),
          flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {   # (program, anchor, replacement)
    "mbalways": ("panel", '''    if base == "info" and not left and mb == LOG_MB_DEFAULT:\n        return None\n''', ""),
    "mbdropped": ("panel", '''    if base == "info" and not left and mb == LOG_MB_DEFAULT:''', '''    if base == "info" and not left:'''),
    "unpublished": ("panel", '''                        "log_mb": log_mb(c.get("log_mb")),\n''', ""),
    "store100": ("panel", '''            if _lmb == LOG_MB_DEFAULT:\n                nodes[nid].pop("log_mb", None)\n            else:\n                nodes[nid]["log_mb"] = _lmb''',
                 '''            nodes[nid]["log_mb"] = _lmb'''),
    "nopersist": ("noded", '''        if _mb != _LOG_BUDGET["mb"] or not os.path.exists(LOG_BUDGET_FILE):''', '''        if False:'''),
    "jdchurn": ("noded", '''    if _LOG_BUDGET["conf"] != want and (now >= _LOG_BUDGET["retry_at"] or want != _LOG_BUDGET["retry_want"]):''', '''    if now >= _LOG_BUDGET["retry_at"]:'''),
    "offkeeps": ("noded", '''                        if ".journal" in n:\n                            with contextlib.suppress(OSError):\n                                os.remove(os.path.join(d, n))''',
                 '''                        pass'''),
    "tilde": ("noded", r'''-([0-9a-f]{16})\.journal$")''', r'''-([0-9a-f]{16})\.journal~?$")'''),
    "unittext": ("noded", '''RELAY_UNIT_TMPL = """[Unit]''', '''RELAY_UNIT_TMPL = """[Service]\nLogNamespace=swg-node\n[Unit]'''),
    "dockeroff": ("noded", '''    if not cap:\n        return ["--log-driver", "none"]\n''', ""),
    "norotate": ("noded", '''            if _LOG_FILE["size"] >= _LOG_FILE["cap"] // 2:''', '''            if False:'''),
    "headold": ("noded", '''    if journal and oldest is None:\n        oldest = _journal_head(os.path.join(d, "system.journal"))\n''', ""),
    "ncheadold": ("netctl", '''    if oldest is None:\n        oldest = _journal_head(os.path.join(d, "system.journal"))\n''', ""),
    "dockold": ("noded", '''    for p in (path + ".1", path):\n        with contextlib.suppress(OSError, ValueError, UnicodeDecodeError):\n            with open(p, "rb") as f:\n                return _live_cal''',
                '''    for p in (path, path + ".1"):\n        with contextlib.suppress(OSError, ValueError, UnicodeDecodeError):\n            with open(p, "rb") as f:\n                return _live_cal'''),
    "paneloldest": ("panel", '''        for p in (PANEL_LOG_FILE["path"] + ".1", PANEL_LOG_FILE["path"]):''', '''        for p in ():'''),
    "holdsfull": ("spa", '''  if (!(st.used_mb >= st.mb * 0.85)) {''', '''  if (!(st.used_mb >= st.mb * 0.85)) return null;\n  if (false) {'''),
    "barfull": ("css", ".lb-meter i{display:block;height:100%;background:var(--online)", ".lb-meter i{display:block;height:100%;background:var(--brand)"),
    "sweeplog": ("netctl", '''_sweep(sfd, 3600, keep=lambda n: n == LOG_STATUS)''', '''_sweep(sfd, 3600)'''),
    "netctlrc": ("netctl", '''    rc, out = run(["systemctl", "try-restart", "systemd-journald@%s.service" % LOG_NS], timeout=20)\n    if rc != 0:''',
                 '''    r = run(["systemctl", "try-restart", "systemd-journald@%s.service" % LOG_NS], timeout=20)\n    rc, out = r.returncode, ""\n    if rc != 0:'''),
    "noretry": ("netctl", '''            if have is None:\n                os.remove(LOG_NS_CONF)\n            else:\n                with open(LOG_NS_CONF + ".tmp", "w") as f:\n                    f.write(have)\n                os.replace(LOG_NS_CONF + ".tmp", LOG_NS_CONF)\n''', "            pass\n"),
    "noderetry": ("noded", '''                    if not _LOG_BUDGET["conf"]:           # it as applied while journald runs the old size\n                        os.remove(LOG_NS_CONF)\n                    else:\n                        with open(LOG_NS_CONF + ".tmp", "w") as f:\n                            f.write(_LOG_BUDGET["conf"])\n                        os.replace(LOG_NS_CONF + ".tmp", LOG_NS_CONF)\n''', "                    pass\n"),
    "pid1all": ("noded", '''JOURNAL_SKIP_PID1 = ("grep -vE '\\\\.service: (Failed with result|Main process exited|Control process exited|Unit entered failed"''',
                '''JOURNAL_SKIP_PID1 = ("grep -vE '\\\\.service: (.*|"'''),
    "stickyerr": ("noded", '''    if _LOG_BUDGET["conf"] == want and _LOG_BUDGET["err"]:   # back to the size in force: nothing is pending any more\n        _LOG_BUDGET["err"], _LOG_BUDGET["retry_want"], _LOG_BUDGET["at"] = None, None, 0.0\n''', ""),
    "pid1last": ("noded", '''-n 8 --no-pager -o cat 2>/dev/null | " + JOURNAL_SKIP_PID1\n                + "grep -iE 'error|invalid|fail|panic|bind|denied|seccomp' | tail -1")''',
                 '''-n 8 --no-pager -o cat 2>/dev/null | "\n                + "grep -iE 'error|invalid|fail|panic|bind|denied|seccomp' | tail -1")'''),
    "uninstkeep": ("uninstall", '''  [ -n "$mid" ] && rmrf "/var/log/journal/$mid.$ns" "/run/log/journal/$mid.$ns"\n''', ""),
}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PROG.items()}
if PLANT:
    f, a, b = PLANTS[PLANT]
    assert SRC[f].count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC[f] = SRC[f].replace(a, b)


def write_prog(key, name=None):
    p = os.path.join(tempfile.mkdtemp(prefix="logbudget-prog-", dir=TMP), name or os.path.basename(PROG[key]))
    open(p, "w", encoding="utf-8").write(SRC[key])
    os.chmod(p, 0o755)
    return p


def load(key, env=None):
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    ld = importlib.machinery.SourceFileLoader("lb_" + key + str(time.monotonic_ns()), write_prog(key))
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
    return m


def quiet(m):
    m._LOG_STREAM = io.StringIO()
    m._LOG_JOURNAL = False
    return m._LOG_STREAM


# ── [1] the wire and the stored fields, against a real panel ─────────────────────────────────────────────────────────
print("[1] the wire and the stored fields")


def start_panel(src_path, tag, env=None):
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


def sync(port, tok, log=None):
    snap = {"hostname": "n1", "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
            **({"log": log} if log else {})}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


def state_of(port):
    st = req(port, "/api/state")[1]
    return st.get("data") or st


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
    check("[1] a default fleet: the `panel` block is byte-identical to the build before levels",
          json.dumps(rr.get("panel")) == json.dumps(rn.get("panel")), (rr.get("panel"), rn.get("panel")))
    c, r = req(port_n, "/api/nodes/update", {"id": "n1", "log_mb": 15})
    check("[1] a budget below 16 MB is refused, translatably", c == 400 and r.get("error_key"), (c, r))
    req(port_n, "/api/nodes/update", {"id": "n1", "log_mb": 200})
    check("[1] a node's budget reaches it as panel.log.mb", sync(port_n, tok_n)["panel"].get("log") == {"level": "info", "mb": 200},
          sync(port_n, tok_n)["panel"].get("log"))
    req(port_n, "/api/nodes/update", {"id": "n1", "ip_learning": False, "routing_mode": "kernel"})
    nd = [n for n in state_of(port_n).get("nodes") or [] if n.get("id") == "n1"]
    check("[1] log_mb is PUBLISHED, and a save of another field on the node keeps it",
          nd and nd[0].get("log_mb") == 200, nd and nd[0].get("log_mb"))
    req(port_n, "/api/nodes/update", {"id": "n1", "log_mb": 100})
    stored = json.load(open(os.path.join(state_n, "nodes.json")))["n1"]
    check("[1] back to 100: not stored, and the key is gone from the reply",
          "log_mb" not in stored and "log" not in sync(port_n, tok_n)["panel"], stored.get("log_mb"))
    rep = {"mb": 100, "used_mb": 91.4, "oldest": int(time.time()) - 3 * 86400}
    sync(port_n, tok_n, rep)
    nd = [n for n in state_of(port_n).get("nodes") or [] if n.get("id") == "n1"]
    check("[1] the node's report reaches /api/state", nd and nd[0].get("log") == rep, nd and nd[0].get("log"))
    c, r = req(port_n, "/api/panel/settings", {"log_mb_panel": "x"})
    check("[1] a panel budget that is not a number is refused", c == 400, (c, r))
    req(port_n, "/api/panel/settings", {"log_mb_panel": 64})
    ps = json.load(open(os.path.join(state_n, "panel-settings.json")))
    req(port_n, "/api/panel/settings", {"log_mb_panel": 100})
    ps2 = json.load(open(os.path.join(state_n, "panel-settings.json")))
    check("[1] the panel's budget: stored when not 100, dropped at 100", ps.get("log_mb_panel") == 64 and "log_mb_panel" not in ps2,
          (ps.get("log_mb_panel"), ps2.get("log_mb_panel")))
    check("[1] the panel row: nothing reported yet is None", state_of(port_n)["panel_settings"].get("log_panel") is None)
    os.makedirs(os.path.join(state_n, "netctl", "status"), exist_ok=True)
    json.dump({"mb": 100, "used_mb": 12.4, "err": "x", "unsupported": True, "junk": [1], "retry": 5},
              open(os.path.join(state_n, "netctl", "status", "_log.json"), "w"))
    check("[1] the panel row reads netctl's status file (known keys only, `unsupported` among them)",
          state_of(port_n)["panel_settings"].get("log_panel") == {"mb": 100, "used_mb": 12.4, "err": "x", "unsupported": True},
          state_of(port_n)["panel_settings"].get("log_panel"))
    px, port_x, _ = start_panel(write_prog("panel"), "nix", {"SWG_PANEL_PLATFORM": "nixos"}); procs.append(px)
    check("[1] a NixOS panel says it has no budget of its own", state_of(port_x)["panel_settings"].get("log_panel") == {"err": "nixos"})
finally:
    for p in procs:
        p.terminate()

# ── [2] the node's size file, [3] the status ─────────────────────────────────────────────────────────────────────────
print("[2] the node's size file")
NSTATE = os.path.join(TMP, "noded-state"); os.makedirs(NSTATE)
N = load("noded", {"SWG_NODED_STATE": NSTATE})
quiet(N)
JD = os.path.join(TMP, "journal-node"); os.makedirs(JD)
N.LOG_NS_CONF = os.path.join(TMP, "run", "journald@swg-node.conf.d", "swg.conf")
N.log_ns_ok = lambda: True
N._log_ns_dir = lambda: JD
N.NODE_KIND = "baremetal"
CALLS = []
RC = {"rc": 0}


def fake_run(args, input_text=None, timeout=20):
    CALLS.append(list(args))
    return subprocess.CompletedProcess(args, RC["rc"], "", "boom" if RC["rc"] else "")


N.run = fake_run
N.log_set(N.LOG_INFO)
N._log_budget()
check("[2] a new node holds its journal to the default from its first pass, before any panel reply",
      "SystemMaxUse=100M" in open(N.LOG_NS_CONF).read() and len(CALLS) == 1, CALLS)
CALLS.clear()
N.apply_panel_settings({"log": {"mb": 48}})
N._log_budget()
want = "[Journal]\nStorage=persistent\nSystemMaxUse=48M\nRuntimeMaxUse=48M\n"
check("[2] after a reply: persistent, the budget in both caps", open(N.LOG_NS_CONF).read() == want, open(N.LOG_NS_CONF).read())
check("[2] …and one try-restart of journald@swg-node", CALLS == [["systemctl", "try-restart", "systemd-journald@swg-node.service"]], CALLS)
CALLS.clear()
for _ in range(3):
    N.apply_panel_settings({"log": {"mb": 48}})
    N._log_budget()
check("[2] steady passes touch nothing", not CALLS, CALLS)
N2 = load("noded", {"SWG_NODED_STATE": NSTATE}); quiet(N2)
N2.LOG_NS_CONF, N2.log_ns_ok, N2._log_ns_dir, N2.NODE_KIND, N2.run = N.LOG_NS_CONF, (lambda: True), (lambda: JD), "baremetal", fake_run
N2.log_set(N2.LOG_INFO)
N2._log_budget()
st0 = N2._LOG_BUDGET["status"] or {}
N2.apply_panel_settings({"log": {"mb": 48}}); N2._log_budget()
check("[2] a restarted node reports the budget in force and restarts nothing", not CALLS and st0.get("mb") == 48, (CALLS, st0))
os.remove(N.LOG_NS_CONF)                                     # a reboot: /run is empty, and the panel is not answering
N3 = load("noded", {"SWG_NODED_STATE": NSTATE}); quiet(N3)
N3.LOG_NS_CONF, N3.log_ns_ok, N3._log_ns_dir, N3.NODE_KIND, N3.run = N.LOG_NS_CONF, (lambda: True), (lambda: JD), "baremetal", fake_run
N3.log_set(N3.LOG_INFO)
N3._log_budget()
check("[2] after a reboot with the panel unreachable, the node holds its journal to the budget it was last given",
      os.path.exists(N.LOG_NS_CONF) and "SystemMaxUse=48M" in open(N.LOG_NS_CONF).read() and len(CALLS) == 1,
      (CALLS, os.path.exists(N.LOG_NS_CONF) and open(N.LOG_NS_CONF).read()))
CALLS.clear()
for v, exp in ((None, 100), (8, 16), ("x", 100)):
    N.apply_panel_settings({"log": {"mb": v}} if v is not None else {})
    check("[2] panel.log.mb %r reads as %d" % (v, exp), N._LOG_BUDGET["mb"] == exp, N._LOG_BUDGET["mb"])
open(os.path.join(JD, "system.journal"), "wb").write(b"x" * 4096)
open(os.path.join(JD, "system@" + "a" * 32 + "-" + "0" * 15 + "1-" + "%016x" % (1_700_000_000 * 10**6) + ".journal"), "wb").write(b"y" * 4096)
N.apply_panel_settings({"log": {"level": "off", "mb": 48}})
N._log_budget()
check("[2] Off: Storage=none", "Storage=none\n" in open(N.LOG_NS_CONF).read(), open(N.LOG_NS_CONF).read())
check("[2] Off: what was stored is removed (journald's Storage=none keeps it)", not [n for n in os.listdir(JD) if ".journal" in n],
      os.listdir(JD))
CALLS.clear(); RC["rc"] = 1
b = quiet(N)
for _ in range(3):
    N.apply_panel_settings({"log": {"mb": 64}})
    N._log_budget()
check("[2] a failing journald restart is retried once a minute, not every pass (each try can block the loop)",
      len(CALLS) == 1, CALLS)
for _ in range(2):
    N._LOG_BUDGET["retry_at"] = 0.0
    N._log_budget()
check("[2] a failing journald restart is said once, however often it is retried",
      len(CALLS) == 3 and b.getvalue().count("did not restart") == 1, (len(CALLS), b.getvalue()))
check("[2] …and the old size file is back in place, so a restarted node does not read the change as applied",
      "SystemMaxUse=64M" not in open(N.LOG_NS_CONF).read(), open(N.LOG_NS_CONF).read())
check("[2] …and reported as `err`", "did not restart" in (N._LOG_BUDGET["status"] or {}).get("err", ""), N._LOG_BUDGET["status"])
N.apply_panel_settings({"log": {"level": "off", "mb": 48}}); N._log_budget()   # exactly the file in force (Off, 48 MB)
check("[2] back to the size in force after a failure: the error clears (the row no longer reads Not applied)",
      not (N._LOG_BUDGET["status"] or {}).get("err"), N._LOG_BUDGET["status"])
RC["rc"] = 0

print("[3] the status")
for n in os.listdir(JD):
    os.remove(os.path.join(JD, n))
open(os.path.join(JD, "system.journal"), "wb").write(b"x" * 100000)
used, oldest = N._log_dir_usage(JD, True)
check("[3] only the active file, not a journal (no signature): no oldest", oldest is None and used >= 100000, (used, oldest))


def jhead(path, t):
    """A journal file whose header says its first entry is at `t` (head_entry_realtime, µs at byte 184)."""
    h = bytearray(b"LPKSHHRH" + bytes(8192 - 8))
    struct.pack_into("<Q", h, 184, t * 10**6)
    open(path, "wb").write(bytes(h))


t0 = 1_790_250_000
jhead(os.path.join(JD, "system.journal"), t0)
used, oldest = N._log_dir_usage(JD, True)
check("[3] only the active file (nothing rotated yet): its first entry, from its header (review §35 Holds)", oldest == t0, oldest)
open(os.path.join(JD, "system.journal"), "wb").write(b"x" * 100000)
t1, t2 = 1_790_000_000, 1_790_500_000
for t in (t1, t2):
    open(os.path.join(JD, "system@%s-%016x-%016x.journal" % ("b" * 32, 7, t * 10**6)), "wb").write(b"z" * 1000)
open(os.path.join(JD, "system@%s-%016x-%016x.journal~" % ("c" * 32, 1, 1_000_000_000 * 10**6)), "wb").write(b"d")
used, oldest = N._log_dir_usage(JD, True)
check("[3] the oldest ARCHIVED file's head time; a damaged `~` file is skipped", oldest == t1, oldest)
st = os.stat(os.path.join(JD, "system.journal"))
check("[3] used = blocks on disk, not apparent size", used >= st.st_blocks * 512, used)

# ── [4] the namespace on the units the node writes ───────────────────────────────────────────────────────────────────
print("[4] the namespace on the units the node writes")
UD = os.path.join(TMP, "units"); os.makedirs(UD)
N.UNIT_DIR_PERSIST = UD
N.unit_dir_persists = lambda: True
CALLS.clear()
N._log_ns_dropins()
files = sorted(os.path.relpath(os.path.join(dp, f), UD) for dp, _d, fs in os.walk(UD) for f in fs)
check("[4] four prefix drop-ins beside the units", files == sorted(u + ".d/swg-ns.conf" for u in N.LOG_NS_UNITS), files)
check("[4] …each LogNamespace=swg-node, one daemon-reload",
      all(open(os.path.join(UD, f)).read() == "[Service]\nLogNamespace=swg-node\n" for f in files)
      and CALLS == [["systemctl", "daemon-reload"]], CALLS)
CALLS.clear(); N._log_ns_dropins()
check("[4] a second start writes and reloads nothing", not CALLS, CALLS)
texts = {"relay": N._relay_unit_text(), "wdtt": N._wdtt_unit_text("wdtt1", "/x/server", "/x", "amurcanov"),
         "csqtt": N._csqtt_unit_text("csq1", "/x/server", "/x"), "turn": N.TURN_UNIT_HARDENING}
check("[4] the unit texts the drift checks compare carry no LogNamespace", not [k for k, t in texts.items() if "LogNamespace" in t],
      [k for k, t in texts.items() if "LogNamespace" in t])

# ── [5] docker ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("[5] docker")
LF = os.path.join(TMP, "dlog", "swg-noded.log")
N.log_set(N.LOG_INFO)
N.log_file(LF, 4000)
for i in range(60):
    N.log(N.LOG_INFO, "line %d %s", i, "x" * 40)
lines = open(LF).read().splitlines()
check("[5] our file: each line timestamped, with its level", lines and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ I line ", lines[0]), lines[:1])
check("[5] …rotated into .1 at half the cap: two files, bounded",
      os.path.exists(LF + ".1") and os.path.getsize(LF) <= 2000 + 200 and os.path.getsize(LF + ".1") <= 2000 + 200,
      (os.path.exists(LF + ".1"), os.path.getsize(LF)))
OD = os.path.join(TMP, "dlog-old"); os.makedirs(OD)
OL = os.path.join(OD, "swg-noded.log")
open(OL, "w").write("2026-10-01T08:00:00Z I newer half\n"); open(OL + ".1", "w").write("2026-09-30T07:00:00Z I older half\n")
T930 = __import__("calendar").timegm((2026, 9, 30, 7, 0, 0))   # the older half's stamp
check("[5] the oldest line: the first stamp of `.1` (the older half), else of the file; none without a file (review §35 Holds)",
      N._log_file_oldest(OL) == T930 and N._log_file_oldest(os.path.join(TMP, "nope.log")) is None, N._log_file_oldest(OL))
PP = load("panel")
PP.PANEL_LOG_FILE["path"] = OL
check("[5] the docker panel's row says its oldest line the same way (review §35 Holds)",
      (PP.panel_log_status({"panel_settings": {}}) or {}).get("oldest") == T930, PP.panel_log_status({"panel_settings": {}}))
PP.PANEL_LOG_FILE["path"] = None
N.log_file(LF, 0)
check("[5] at Off (cap 0) both files are removed and nothing is written",
      not os.path.exists(LF) and not os.path.exists(LF + ".1"), os.listdir(os.path.dirname(LF)))
N.log(N.LOG_ERR, "after off")
check("[5] …and stays so", not os.path.exists(LF))
N.log_file(None, 0)
N.NODE_KIND = "docker"
N._turn_record_raw = lambda: [{"service": "a"}, {"service": "b"}]
N.WDTT_ROOT, N.CSQTT_ROOT = os.path.join(TMP, "wd"), os.path.join(TMP, "cq")
os.makedirs(os.path.join(N.WDTT_ROOT, "w1"))
N._LOG_BUDGET["mb"] = 100
N.log_set(N.LOG_INFO)
opts = N.docker_log_opts()
check("[5] a launched container's share: 100 MB over 5 logs, two files of 10 MB", opts == ["--log-opt", "max-size=10240k", "--log-opt", "max-file=2"], opts)
N.log_set(N.LOG_OFF)
check("[5] at Off a launched container keeps no log", N.docker_log_opts() == ["--log-driver", "none"], N.docker_log_opts())
sl = os.path.join(N.WDTT_ROOT, "w1", "server.log")
open(sl, "w").write("x" * 500); open(sl + ".1", "w").write("old")
N.DNSMASQ_LOG = os.path.join(TMP, "dnsmasq.log")
N._cap_serverlogs()
check("[5] at Off the supervised logs are emptied and their .1 removed", os.path.getsize(sl) == 0 and not os.path.exists(sl + ".1"))
N.log_set(N.LOG_INFO)
N.LOG_DIR_DOCKER = os.path.join(TMP, "dlog2")
N._LOG_BUDGET["mb"] = 100; N._log_budget()
N._LOG_BUDGET["mb"] = 200; N._log_budget()
check("[5] a docker node reports a new budget in the pass that applies it", (N._LOG_BUDGET["status"] or {}).get("mb") == 200,
      N._LOG_BUDGET["status"])
N.log_file(None, 0); N.NODE_KIND = "baremetal"
check("[5] dnsmasq gets a log file in docker only", 'if NODE_KIND == "docker":' in SRC["noded"]
      and 'conf.append("log-facility=" + DNSMASQ_LOG)' in SRC["noded"])

# ── [6] swg-netctl ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[6] swg-netctl")
PST = os.path.join(TMP, "panel-state"); os.makedirs(os.path.join(PST, "netctl", "queue"))
JP = os.path.join(TMP, "journal-panel"); os.makedirs(JP)
M = load("netctl", {"SWG_STATE_DIR": PST, "SWG_PANEL_USER": "nobody-here", "SWG_PANEL_GROUP": "nogroup-here",
                    "SWG_LOG_NS_CONF": os.path.join(TMP, "run", "journald@swg-panel.conf.d", "swg.conf")})
quiet(M)
MC = []
JN = os.path.join(TMP, "journal-netctl"); os.makedirs(JN)
jhead(os.path.join(JN, "system.journal"), 1_790_260_000)
check("[6] netctl: only the active file — its first entry from its header (review §35 Holds)",
      M._log_dir_usage(JN)[1] == 1_790_260_000, M._log_dir_usage(JN))


MRC = {"rc": 0}


def mrun(argv, env=None, timeout=None):
    MC.append(list(argv))
    return MRC["rc"], ("boom" if MRC["rc"] else "")


M.run, M.log_ns_ok, M._log_ns_dir = mrun, (lambda: True), (lambda: JP)


def tick():
    """As main() runs it: an exception in the budget never stops the queue (and is not seen)."""
    try:
        M.log_budget()
    except Exception:
        pass
json.dump({"log_level": "info", "log_mb_panel": 48}, open(os.path.join(PST, "panel-settings.json"), "w"))
M.log_from_settings(); tick()
SF = os.path.join(PST, "netctl", "status", "_log.json")
check("[6] the size file from panel-settings.json", "SystemMaxUse=48M" in open(M.LOG_NS_CONF).read() and
      MC == [["systemctl", "try-restart", "systemd-journald@swg-panel.service"]], MC)
def sf():
    try:
        return json.load(open(SF))
    except (OSError, ValueError):
        return {}


check("[6] the status file for the panel", sf().get("mb") == 48, sf())
if os.path.exists(SF):
    os.utime(SF, (1, 1))
MC.clear()
tick()
check("[6] a steady tick: no restart, the status not rewritten", not MC and os.path.exists(SF) and os.stat(SF).st_mtime == 1, MC)
open(os.path.join(PST, "netctl", "queue", "r1.json"), "w").write("{}")
M.process_queue()
check("[6] the 1-hour status sweep keeps the budget's status", os.path.exists(SF))
open(os.path.join(JP, "system.journal"), "wb").write(b"x")
json.dump({"log_level": "off", "log_mb_panel": 48}, open(os.path.join(PST, "panel-settings.json"), "w"))
M.log_from_settings(); tick()
MRC["rc"] = 1; MC.clear()
json.dump({"log_level": "off", "log_mb_panel": 72}, open(os.path.join(PST, "panel-settings.json"), "w"))
M.log_from_settings(); tick(); tick()
check("[6] a failed journald restart is not retried on every tick (each try can take its timeout)", len(MC) == 1, MC)
d = sf(); d["retry"] = 1; json.dump(d, open(SF, "w"))          # its minute is up
tick()
check("[6] …it is retried once its minute is up, and never reported as applied",
      len(MC) == 2 and sf().get("mb") != 72 and "did not restart" in sf().get("err", ""), (MC, sf()))
MC.clear()
json.dump({"log_level": "off", "log_mb_panel": 80}, open(os.path.join(PST, "panel-settings.json"), "w"))
M.log_from_settings(); tick()
check("[6] a new budget after a failure is tried at once", len(MC) == 1, MC)
MRC["rc"] = 0
json.dump({"log_level": "off", "log_mb_panel": 48}, open(os.path.join(PST, "panel-settings.json"), "w"))
M.log_from_settings(); tick()
check("[6] Off: Storage=none and the stored files removed", "Storage=none" in open(M.LOG_NS_CONF).read() and not os.listdir(JP),
      os.listdir(JP))

# ── [7] the verify readers ───────────────────────────────────────────────────────────────────────────────────────────
spa, css = SRC["spa"], SRC["css"]
lh = spa[spa.index("export function logHolds(st)"):spa.index("function LogBudgetTable(")]
check("[6] the SPA: before the budget is full the Holds cell says since when (the first line's date); once full, N days "
      "(review §35 Holds)", 'if (!(st.used_mb >= st.mb * 0.85)) {' in lh and 'T("since {v1}"' in lh and "full: true" in lh, lh[:300])
check("[6] …the used bar stays green at any fill (full is the steady state)",
      ".lb-meter i{display:block;height:100%;background:var(--online)" in css and ".lb-meter.full" not in css
      and '"lb-meter" + (' not in spa)
print("[7] the verify readers")
FB = os.path.join(TMP, "fakebin"); os.makedirs(FB)
open(os.path.join(FB, "systemctl"), "w").write("#!/bin/sh\necho failed\n")
open(os.path.join(FB, "journalctl"), "w").write(
    "#!/bin/sh\necho \"$*\" > %s/jargs\n"
    "echo 'wdtt: bind 1.2.3.4:56000: cannot assign requested address'\n"
    "echo 'swg-wdtt-x.service: Main process exited, code=exited, status=3/NOTIMPLEMENTED'\n"
    "echo \"swg-wdtt-x.service: Failed with result 'exit-code'.\"\n" % TMP)
open(os.path.join(FB, "sleep"), "w").write("#!/bin/sh\nexit 0\n")
for f in os.listdir(FB):
    os.chmod(os.path.join(FB, f), 0o755)
os.environ["PATH"] = FB + ":" + os.environ["PATH"]
N.host_sh = lambda cmd, timeout=90, probe=False: subprocess.run(["sh", "-c", cmd], capture_output=True, text=True)
N.log_set(N.LOG_INFO)
r = N._wdtt_verify("swg-wdtt-x")
check("[7] WDTT verify reads the swg-node journal merged with the main one",
      "--namespace=+swg-node" in open(os.path.join(TMP, "jargs")).read(), open(os.path.join(TMP, "jargs")).read())
check("[7] …and gives the unit's own reason though systemd's line sorts after it", "cannot assign" in r, r)
r = N._turn_verify("vk-turn-proxy-x")
check("[7] turn verify too", "cannot assign" in r, r)
open(os.path.join(FB, "journalctl"), "w").write(
    "#!/bin/sh\necho 'swg-wdtt-x.service: Failed at step EXEC spawning /opt/x/server: Exec format error'\n"
    "echo \"swg-wdtt-x.service: Failed with result 'exit-code'.\"\necho 'Failed to start swg-wdtt-x.service - WDTT.'\n")
r = N._wdtt_verify("swg-wdtt-x")
check("[7] an exec failure keeps systemd's line that says why (it is the only reason there is)", "Exec format error" in r, r)

# ── [8] uninstall ────────────────────────────────────────────────────────────────────────────────────────────────────
print("[8] uninstall")
UR = os.path.join(TMP, "uroot")
fn = re.search(r"^rm_log_ns\(\)\{.*?^\}\n", SRC["uninstall"], re.S | re.M).group(0)
fn = fn.replace("/run/", UR + "/run/").replace("/var/log/journal", UR + "/var/log/journal").replace("/etc/machine-id", UR + "/mid") \
       .replace("/usr/local/bin/swg-logs", UR + "/bin/swg-logs")
SD = os.path.join(UR, "etc")
for p in ("etc/swg-noded.service.d/swg-ns.conf", "etc/swg-noded.service.d/my-own.conf", "etc/vk-turn-proxy-.service.d/swg-ns.conf",
          "run/systemd/system/vk-turn-proxy-.service.d/swg-log.conf", "run/systemd/journald@swg-node.conf.d/swg.conf",
          "var/log/journal/MID.swg-node/system.journal", "bin/swg-logs", "etc/swg-panel-server.service"):
    os.makedirs(os.path.dirname(os.path.join(UR, p)), exist_ok=True); open(os.path.join(UR, p), "w").write("x")
open(os.path.join(UR, "mid"), "w").write("MID\n")
sh = ('DRYRUN=false; SD=%s\nrun(){ "$@"; }\nb(){ printf %%s "$*"; }\ninfo(){ :; }\n'
      'rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then rm -rf "$p"; fi; done; }\n'
      'rmdir_if_empty(){ [ -d "$1" ] && [ -z "$(ls -A "$1")" ] && rmdir "$1"; return 0; }\n%s\n'
      'rm_log_ns swg-node swg-noded.service swg-relay@.service vk-turn-proxy-.service swg-wdtt-.service swg-csqtt-.service\n') % (SD, fn)
subprocess.run(["bash", "-c", sh], check=True)
left = sorted(os.path.relpath(os.path.join(dp, f), UR) for dp, _d, fs in os.walk(UR) for f in fs)
check("[8] the drop-ins, the size file and the journal are gone; the operator's own drop-in stays",
      left == ["bin/swg-logs", "etc/swg-noded.service.d/my-own.conf", "etc/swg-panel-server.service", "mid"], left)
check("[8] swg-logs stays while the panel is still installed", os.path.exists(os.path.join(UR, "bin/swg-logs")))
os.remove(os.path.join(SD, "swg-panel-server.service"))
subprocess.run(["bash", "-c", sh], check=True)
check("[8] …and goes with the last of them", not os.path.exists(os.path.join(UR, "bin/swg-logs")))

# ── [9] swg-logs, update.sh's order ──────────────────────────────────────────────────────────────────────────────────
print("[9] swg-logs and update.sh")
open(os.path.join(FB, "journalctl"), "w").write("#!/bin/sh\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done\n")
lg = write_prog("logs")
ns = any(os.path.exists(os.path.join(d, "systemd-journald@.service")) for d in
         ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"))
o = subprocess.run([lg, "noded", "-f"], capture_output=True, text=True).stdout
check("[9] swg-logs noded -f", o == ("[--namespace=+swg-node]" if ns else "") + "[-u][swg-noded.service][-f]", o)
o = subprocess.run([lg, "turn", "wdtt1", "--since", "-1h"], capture_output=True, text=True).stdout
check("[9] swg-logs turn wdtt1: every turn unit kind of that name",
      "[-u][vk-turn-proxy-wdtt1.service][-u][swg-wdtt-wdtt1.service][-u][swg-csqtt-wdtt1.service][--since][-1h]" in o, o)
o = subprocess.run([lg, "sni"], capture_output=True, text=True).stdout
check("[9] swg-logs sni: noded's stream, its prefix", "[-u][swg-noded.service][--grep][^swg-sni:]" in o, o)
p = subprocess.run([lg, "turn", "a;b"], capture_output=True, text=True)
check("[9] a name with shell characters is refused", p.returncode == 2 and not p.stdout, (p.returncode, p.stdout))
U = SRC["update"]
pb = U.index("# ───────────────────────── bare-metal panel (host or master)")
check("[9] update.sh writes the panel's drop-ins before it restarts the panel",
      pb < U.index("ensure_log_ns swg-panel", pb) < U.index("restart_panel_seeding_node_ep; then", pb))
nb = U.index("# ───────────────────────── bare-metal node daemon")
check("[9] …and swg-noded's before it restarts the node",
      nb < U.index("ensure_log_ns swg-node", nb) < U.index("if run systemctl restart swg-noded", nb))
check("[9] …each only inside an upgrade that goes ahead (a declined one keeps the old build, which never sizes the journal)",
      U.index('if should_update "bare-metal swg-panel"', pb) < U.index("ensure_log_ns swg-panel", pb)
      and U.index('if should_update "bare-metal swg-node"', nb) < U.index("ensure_log_ns swg-node", nb))

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    print("plant %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT caught"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
