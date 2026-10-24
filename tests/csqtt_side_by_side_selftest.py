#!/usr/bin/env python3
"""Self-test — a csqtt 2.5 server deployed NEXT TO a 2.1.9 one on the same box is seen, told apart, and taken over
on its own line.

The csqtt app 2.5.2 deploys our 2.5 server beside a stock 2.1.9 (its own --iface/--tun-addr/--config-dir, unit and
ports). The box then runs TWO foreign csqtt servers, and the two lines do not speak to each other: a 2.5 server taken
over as 2.1 cuts off every client it serves. Before this, a candidate carried no version (the adopt installed 2.1), and
the stop and the stale-TUN guard matched a server by its bare --iface — a stock server passes none, so the take-over of
csqtt1 read it as already gone and the guard pulled its live TUN.

  node (swg-noded imported; hermetic but for [2], which reads a real running process's binary):
  [1] candidates  a stock 2.1.9 (no --iface, /etc/csqtt) and our 2.5 beside it (--iface csqtt25) are two candidates with
                  their own iface, subnet and line; our own supervised instance is not one
  [2] version     the version is read from the binary of a REAL running process (/proc/<pid>/exe): 2.5.0, 2.5.0-rc1 and
                  2.5 are line 2.5; 2.1.9 and 2.0.0 are 2.1; 2.3.0 and 2.6.0 their own (refused); no label is "" (every
                  csqtt build carries one — a wrapper's binary does not); an unreadable binary is None, kept a minute
  [3] stop        the take-over of csqtt1 stops the stock server and never the 2.5 one, and the reverse; the config
                  dir compares normalised (a trailing slash)
  [4] staletun    a new csqtt1 of ours never deletes the TUN a live stock server holds; with none live it does
  [7] noinstall  a server of ours is never installed over a foreign one live on its name (the unit's first step deletes
                  that TUN), and removing ours never deletes a TUN a foreign server holds — the state a take-over the
                  panel gave up on, or Remove pressed during one, left; with nothing foreign live both go ahead as before;
                  a take-over that cannot stop the server is not recorded (so not reported, so not read as done)
  panel (a real panel on 127.0.0.1, snapshots pushed over /api/node/sync):
  [5] adopt       the 2.5 candidate is adopted with line 2.5 and the next reply asks for 2.5's build; the 2.1 one with no
                  line (2.1 stays the absent value); a candidate from a node older than the report (no field) as today
  [6] refuse      line "" (binary unread) and a line the panel does not offer are refused; 2.5 on a node that cannot
                  run it is refused node_too_old
  [8] giveup      a csqtt take-over the panel gives up on drops its record (the node never reported it, so nothing of it
                  is ours) and says so; a take-over still inside its window keeps it

Run: python3 tests/csqtt_side_by_side_selftest.py      (0 = pass)
     --perturb <name>  plants one regression and expects RED:  noline [1] [5] · bareiface [3] [4] · nocfg [3] ·
                       rawcfg [3] ·
                       nocache / failttl / nolabel21 / strictre / mid21 [2] · adopt21 [5] · nocheck [6] ·
                       installover / rmtun / keepfail [7] · keeprec [8]
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SERVER = os.environ.get("SWG_PANEL") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {   # name: (sections, file, anchor, replacement)
    "noline": (("[1]", "[5]"), "noded", '''                    "version": ver or "", "line": _csqtt_line_of_version(ver),''', ""),
    "bareiface": (("[3]", "[4]"), "noded", '''    return (fl.get("iface") or "").strip() or CSQTT_DEFAULT_IFACE''', '''    return (fl.get("iface") or "").strip()'''),
    "nocfg": ("[3]", "noded", '''                     and (not cfgdir or os.path.normpath((f.get("config-dir") or "").strip() or "/") == os.path.normpath(cfgdir))\n''', ""),
    "rawcfg": ("[3]", "noded", '''                     and (not cfgdir or os.path.normpath((f.get("config-dir") or "").strip() or "/") == os.path.normpath(cfgdir))''',
               '''                     and (not cfgdir or (f.get("config-dir") or "").strip() == cfgdir)'''),
    "nocache": ("[2]", "noded", '''    _CSQTT_EXEVER[pid] = (now, ver)\n    return ver''', '''    if ver:\n        _CSQTT_EXEVER[pid] = (now, ver)\n    return ver'''),
    "failttl": ("[2]", "noded", '''(_CSQTT_EXEVER_TTL if hit[1] is not None else _CSQTT_EXEVER_FAIL_TTL)''', '''_CSQTT_EXEVER_TTL'''),
    "nolabel21": ("[2]", "noded", '''    if not m:\n        return ""\n    mm = ''', '''    if not m:\n        return CSQTT_DEFAULT_LINE\n    mm = '''),
    "strictre": ("[2]", "noded", r"""rb'aria-label="v(\d{1,3}\.\d{1,3}[0-9A-Za-z.+~-]{0,24}) by amurcanov"'""", r"""rb'aria-label="v(\d{1,3}\.\d{1,3}\.\d{1,4}) by amurcanov"'"""),
    "mid21": ("[2]", "noded", '''    return CSQTT_DEFAULT_LINE if mm in ("2.0", "2.1") else mm''', '''    return CSQTT_DEFAULT_LINE if mm < "2.5" else mm'''),
    "adopt21": ("[5]", "panel", '''                    return 400, {"ok": False, **perr("this node can't run csqtt {v1} yet — update the node first (its page offers \\"update node to …\\")", v1=_ln), "code": "node_too_old"}
                inst["line"] = _ln''', '''                    return 400, {"ok": False, **perr("this node can't run csqtt {v1} yet — update the node first (its page offers \\"update node to …\\")", v1=_ln), "code": "node_too_old"}
                pass'''),
    "installover": ("[7]", "noded", '''    _fp = _csqtt_foreign_pid(iface)\n    if _fp:''', '''    _fp = None\n    if _fp:'''),
    "keepfail": ("[7]", "noded", '''                    if prev:\n                        have[iface] = inst\n                    continue''', '''                    have[iface] = inst\n                    continue'''),
    "rmtun": ("[7]", "noded",'''    _theirs = _csqtt_foreign_pid(iface) is not None or not _csqtt_scan_ok()''', '''    _theirs = False'''),
    "keeprec": ("[8]", "panel", '''                    if _kind == "csqtt":\n                        _st.pop(_ifn, None)''', '''                    pass'''),
    "nocheck": ("[6]", "panel",'''            if _ln not in CSQTT_LINES:
                return 400, {"ok": False, **perr("this server runs csqtt {v1}''', '''            if False:
                return 400, {"ok": False, **perr("this server runs csqtt {v1}'''),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else ""
SECTION = [""]
FAILS = []
def section(s):
    SECTION[0] = s; print(s, flush=True)
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="csqtt-side-")
noded, server = NODED, SERVER
if MODE:
    _sec, which, old, new = PLANTS[MODE]
    orig = NODED if which == "noded" else SERVER
    src = open(orig, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    planted = os.path.join(TMP, os.path.basename(orig))
    open(planted, "w", encoding="utf-8").write(src.replace(old, new))
    if which == "noded":
        noded = planted
    else:
        server = planted

ld = importlib.machinery.SourceFileLoader("swgnoded_side", noded)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_side", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
N.NODE_KIND = "baremetal"
R = lambda rc=0, out="", err="": types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)
_REAL_KILL, _REAL_SLEEP = os.kill, time.sleep

STOCK = (101, N._wdtt_flags_from_argv(["/usr/local/bin/csqtt", "--listen", "0.0.0.0:46000", "--web-port", "46002",
                                        "--config-dir", "/etc/csqtt"]))
SIDE = (202, N._wdtt_flags_from_argv(["/usr/local/bin/csqtt25", "--listen", "0.0.0.0:46100", "--web-port", "46102",
                                       "--config-dir", "/etc/csqtt25", "--iface", "csqtt25", "--tun-addr", "10.66.68.1/24"]))
OURS = (303, N._wdtt_flags_from_argv([N.CSQTT_ROOT + "/csqtt2/server", "--iface", "csqtt2", "--tun-addr", "10.31.0.1/24",
                                       "--config-dir", N.CSQTT_ROOT + "/csqtt2", "--no-web", "--desired"]))
VERS = {101: "2.1.9", 202: "2.5.0", 303: "2.5.0"}

try:
    # ── [1] ──────────────────────────────────────────────────────────────────────────────────────────────────────
    section("[1] candidates — two foreign servers side by side")
    N._csqtt_procs = lambda: [STOCK, SIDE, OURS]
    N._csqtt_load = lambda: {"csqtt2": {}}
    N._csqtt_store_probe = lambda cfg, fresh=False, pid=None: ({"pw" + cfg[-2:]: {"comment": "", "vk_hash": "",
                                                                                 "expires_at": 0, "is_deactivated": False}}, True)
    N._proc_container = lambda pid: ""
    N._csqtt_exe_version = lambda pid: VERS.get(pid)
    cands = {c["iface"]: c for c in N.csqtt_candidates()}
    check("two candidates, csqtt1 (stock) and csqtt25 (beside it); our supervised instance is not one",
          sorted(cands) == ["csqtt1", "csqtt25"], sorted(cands))
    c1, c25 = cands.get("csqtt1") or {}, cands.get("csqtt25") or {}
    check("the stock 2.1.9: stock subnet, its own store, line 2.1",
          c1.get("tun_addr") == "10.66.67.1/24" and c1.get("config_dir") == "/etc/csqtt" and c1.get("line") == "2.1"
          and c1.get("version") == "2.1.9", c1)
    check("the 2.5 beside it: its own subnet, store and port, line 2.5",
          c25.get("tun_addr") == "10.66.68.1/24" and c25.get("config_dir") == "/etc/csqtt25"
          and c25.get("listen") == "0.0.0.0:46100" and c25.get("line") == "2.5", c25)
    N._csqtt_exe_version = lambda pid: None
    cands = {c["iface"]: c for c in N.csqtt_candidates()}
    check("a binary the node could not read reports line \"\" (the panel refuses), never a guessed 2.1",
          (cands.get("csqtt25") or {}).get("line") == "", cands.get("csqtt25"))

    # ── [2] ──────────────────────────────────────────────────────────────────────────────────────────────────────
    section("[2] version — read from a real running binary")
    ld2 = importlib.machinery.SourceFileLoader("swgnoded_side2", noded)   # a clean copy: [1] stubbed the reader in N
    N2 = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_side2", ld2))
    try:
        ld2.exec_module(N2)
    except SystemExit:
        pass
    N2.NODE_KIND = "baremetal"
    sleep = shutil.which("sleep")
    procs = []
    def spawn(label):
        p = os.path.join(TMP, "csqtt-%d" % len(procs))
        shutil.copy2(sleep, p)
        if label:
            with open(p, "ab") as f:      # trailing bytes after an ELF are ignored by the loader, as in csqtt's .rodata
                f.write(b"\0<svg class=\"version-logo\" role=\"img\" aria-label=\"v" + label.encode() + b" by amurcanov\" fill>\0")
        os.chmod(p, 0o755)
        pr = subprocess.Popen([p, "30"]); procs.append(pr)
        return pr.pid
    want = {"2.5.0": ("2.5.0", "2.5"), "2.1.9": ("2.1.9", "2.1"), "2.0.0": ("2.0.0", "2.1"), "": ("", ""),
            "2.6.0": ("2.6.0", "2.6"), "2.5.0-rc1": ("2.5.0-rc1", "2.5"), "2.5": ("2.5", "2.5"), "2.3.0": ("2.3.0", "2.3")}
    pids = {lab: spawn(lab) for lab in want}
    time.sleep(0.2)
    for lab, (ver, line) in want.items():
        got = N2._csqtt_exe_version(pids[lab])
        check("label %-7r → version %r, line %s" % (lab, ver, line),
              got == ver and N2._csqtt_line_of_version(got) == line, (got, N2._csqtt_line_of_version(got or "")))
    dead = subprocess.Popen(["true"]); dead.wait()
    check("an unreadable binary (no such process) is None, and its line \"\" (refused)",
          N2._csqtt_exe_version(dead.pid) is None and N2._csqtt_line_of_version(None) == "")
    at0 = (N2._CSQTT_EXEVER.get(dead.pid) or (None,))[0]
    check("…kept a minute, not asked again every snapshot (a privileged hop on docker)",
          at0 is not None and N2._csqtt_exe_version(dead.pid) is None and N2._CSQTT_EXEVER[dead.pid][0] == at0, N2._CSQTT_EXEVER.get(dead.pid))
    if at0 is not None:
        N2._CSQTT_EXEVER[dead.pid] = (at0 - N2._CSQTT_EXEVER_FAIL_TTL - 1, None)
        N2._csqtt_exe_version(dead.pid)
        check("…and asked again after it (a failed read is no answer)", N2._CSQTT_EXEVER[dead.pid][0] >= at0, N2._CSQTT_EXEVER.get(dead.pid))
    for pr in procs:
        pr.kill()

    # ── [3] ──────────────────────────────────────────────────────────────────────────────────────────────────────
    section("[3] stop — the take-over of one never touches the other")
    def box():
        b = types.SimpleNamespace(alive={101, 202}, kills=[], runs=[])
        N._csqtt_procs = lambda: [p for p in (STOCK, SIDE, OURS) if p[0] in b.alive or p[0] == 303]
        N._wdtt_hostproc_flush = lambda: None
        N._csqtt_scan_ok = lambda: True
        N._wdtt_unit_of_pid = lambda pid, host=False: ""
        N._csqtt_container_of = lambda pid: ("", "")
        N.run = lambda args, *a, **k: (b.runs.append(list(args)), R())[1]
        N.host_sh = lambda *a, **k: R()
        def kill(pid, sig):
            b.kills.append(pid); b.alive.discard(pid)
        N.os.kill = kill
        N._pid_alive = lambda pid: pid in b.alive
        N.time.sleep = lambda s: None
        return b
    b = box()
    ok, why = N._csqtt_stop_foreign("csqtt1", "/etc/csqtt")
    check("csqtt1: the stock server (no --iface) is found and stopped", ok and b.kills and set(b.kills) == {101}, (ok, why, b.kills))
    check("csqtt1: the 2.5 beside it still runs", 202 in b.alive, b.alive)
    b = box()
    ok, why = N._csqtt_stop_foreign("csqtt25", "/etc/csqtt25")
    check("csqtt25: the 2.5 server is stopped, the stock 2.1.9 still runs",
          ok and set(b.kills) == {202} and 101 in b.alive, (ok, why, b.kills, b.alive))
    b = box()
    ok, why = N._csqtt_stop_foreign("csqtt25", "/etc/csqtt25/")
    check("the same dir spelled with a trailing slash still finds it", ok and set(b.kills) == {202}, (ok, why, b.kills))
    b = box()
    ok, why = N._csqtt_stop_foreign("csqtt1", "/etc/other")
    check("a stop for a store this server does not serve signals nothing", not b.kills, (ok, why, b.kills))

    # ── [4] ──────────────────────────────────────────────────────────────────────────────────────────────────────
    section("[4] staletun — a live stock server's TUN is never pulled")
    b = box()
    N._csqtt_clear_stale_tun("csqtt1")
    check("csqtt1 held by the live stock server: no `ip link delete`", ["ip", "link", "delete", "dev", "csqtt1"] not in b.runs, b.runs)
    b = box(); b.alive.clear()
    N._csqtt_clear_stale_tun("csqtt1")
    check("nothing foreign live on csqtt1: the stale TUN is deleted", ["ip", "link", "delete", "dev", "csqtt1"] in b.runs, b.runs)

    # ── [7] ──────────────────────────────────────────────────────────────────────────────────────────────────────
    section("[7] noinstall — never over, never under a foreign server's TUN")
    class _Wrote(Exception):
        pass
    def _wrote(*a, **k):
        raise _Wrote()
    N._csqtt_fork_unknown = lambda inst: ""
    N._csqtt_write_cfgdir = _wrote
    N._csqtt_bin_shared = lambda line: HERE           # exists: past the guard the install goes straight on to writing
    def install(iface):   # "WROTE" = past the guard: the install reached its config-dir write (which it reports as failed)
        got = N._csqtt_install({"iface": iface, "listen": "0.0.0.0:46100", "tun_addr": "10.66.68.1/24"})
        return "WROTE" if got.startswith("cfgdir write failed") else got
    b = box()
    got = install("csqtt25")
    check("csqtt25 held by the live 2.5 server beside 2.1.9: ours is not installed over it, and the error says why",
          got != "WROTE" and "202" in got and "not installed over it" in got, got)
    check("csqtt1 held by the live stock server (no --iface): refused too", install("csqtt1") != "WROTE")
    b.alive.clear()
    got = install("csqtt25")
    check("nothing foreign live on csqtt25: the install goes ahead as before", got == "WROTE", got)
    check("our own supervised instance on its name is no foreign server (csqtt2)", install("csqtt2") == "WROTE")
    sh = []
    b = box(); N.host_sh = lambda cmd, *a, **k: (sh.append(cmd), R())[1]
    N._csqtt_remove("csqtt25")
    check("removing csqtt25 while the foreign 2.5 server holds it: its TUN stays, our unit and dir go",
          bool(sh) and "ip link del" not in sh[-1] and "rm -rf" in sh[-1], sh)
    N._csqtt_scan_ok = lambda: False
    sh.clear(); b.alive.clear(); N._csqtt_remove("csqtt25")
    check("…nor when the process scan could not say (fail safe, as the stale-TUN guard)", bool(sh) and "ip link del" not in sh[-1], sh)
    N._csqtt_scan_ok = lambda: True
    sh.clear(); N._csqtt_remove("csqtt25")
    check("with nothing foreign live the TUN is deleted, as before", bool(sh) and "ip link del csqtt25" in sh[-1], sh)

    saved = []
    N._csqtt_load = lambda: {}
    N._csqtt_save = lambda insts: (saved.append(dict(insts)), True)[1]
    N._csqtt_stop_foreign = lambda iface, src: (False, "it is still running after TERM and KILL")
    N._csqtt_adopted_users = lambda *a, **k: {}
    r7 = N.reconcile_csqtt({"csqtt25": {"adopt_foreign": True, "adopt_config_dir": "/etc/csqtt25", "line": "2.5",
                                        "listen": "0.0.0.0:46100", "tun_addr": "10.66.68.1/24", "password": "x"}})
    check("a take-over that cannot stop the server reports why", any("couldn't stop the existing csqtt server" in e for e in r7["errors"]), r7)
    check("…and does not record it: a recorded instance is reported, which the panel reads as the take-over done",
          bool(saved) and "csqtt25" not in saved[-1], saved[-1:] or r7)
    N._csqtt_load = lambda: {"csqtt25": {"iface": "csqtt25", "panel_managed": True, "line": "2.5"}}
    saved.clear(); N.reconcile_csqtt({"csqtt25": {"adopt_foreign": True, "adopt_config_dir": "/etc/csqtt25", "line": "2.5",
                                                  "listen": "0.0.0.0:46100", "tun_addr": "10.66.68.1/24", "password": "x"}})
    check("an instance of ours from before keeps its record through the same failure", bool(saved) and "csqtt25" in saved[-1], saved[-1:])

    N.os.kill, N.time.sleep = _REAL_KILL, _REAL_SLEEP   # N.os / N.time ARE the os / time modules: the panel half needs them back

    # ── panel ────────────────────────────────────────────────────────────────────────────────────────────────────
    ldp = importlib.machinery.SourceFileLoader("swgpanel_side", server)
    P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_side", ldp))
    try:
        ldp.exec_module(P)
    except SystemExit:
        pass
    V25 = P.CSQTT_LINES["2.5"][0][0]
    state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
    NODES = os.path.join(state, "nodes.json")
    json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}, "endpoint_host": "203.0.113.%d" % (i + 1)}
               for i, n in enumerate(("nnew", "nold"))}, open(NODES, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    fleet = os.path.join(TMP, "fleet.json")
    json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
    log = open(os.path.join(TMP, "panel.log"), "w+")
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT,
                                 "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "",
                                 "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
    def req(path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                   data=json.dumps(data).encode() if data is not None else None,
                                   headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw = resp.read(); code = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read(); code = e.code
        try:
            return code, json.loads(raw or b"{}")
        except Exception:
            return code, {"raw": raw[:200]}
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    sys.exit("panel exited: " + open(log.name).read()[-2000:])
                time.sleep(0.1)
        TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("nnew", "nold")}
        def cand(iface, tun, port, cfg, **kw):
            return {"iface": iface, "pid": 1, "config_dir": cfg, "container": "", "store_found": True,
                    "listen": "0.0.0.0:%d" % port, "tun_addr": tun, "max_passwords": "", "users": [], "adoptable": True, **kw}
        def sync(nid, cands, lines=("2.1", "2.5")):
            s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
                 "csqtt": [], "csqtt_candidates": cands}
            if lines is not None:
                s["csqtt_lines"] = list(lines)
            code, r = req("/api/node/sync", {"snapshot": s}, TOK[nid])
            assert code == 200, (code, r)
            return r.get("csqtt") or {}
        def nodes():
            return json.load(open(NODES))

        section("[5] adopt — each on its own line")
        sync("nnew", [cand("csqtt1", "10.66.67.1/24", 46000, "/etc/csqtt", version="2.1.9", line="2.1"),
                      cand("csqtt25", "10.66.68.1/24", 46100, "/etc/csqtt25", version="2.5.0", line="2.5"),
                      cand("csqtt30", "10.66.70.1/24", 46200, "/etc/csqtt30")])
        code, r = req("/api/csqtt/adopt", {"node": "nnew", "iface": "csqtt25"})
        rec = (nodes()["nnew"].get("csqtt") or {}).get("csqtt25") or {}
        check("the 2.5 candidate is adopted with line 2.5", code == 200 and rec.get("line") == "2.5", (code, r, rec))
        code, r = req("/api/csqtt/adopt", {"node": "nnew", "iface": "csqtt1"})
        rec1 = (nodes()["nnew"].get("csqtt") or {}).get("csqtt1") or {}
        check("the 2.1.9 candidate is adopted with no line (2.1 is the absent value)", code == 200 and "line" not in rec1, (code, r, rec1))
        code, r = req("/api/csqtt/adopt", {"node": "nnew", "iface": "csqtt30"})
        rec30 = (nodes()["nnew"].get("csqtt") or {}).get("csqtt30") or {}
        check("a candidate from a node older than the report is adopted as today (no line)", code == 200 and "line" not in rec30, (code, r, rec30))
        rep = sync("nnew", [])
        check("the next reply asks for csqtt25 on line 2.5 with 2.5's build",
              (rep.get("csqtt25") or {}).get("line") == "2.5" and (rep.get("csqtt25") or {}).get("ver") == V25, rep.get("csqtt25"))
        check("…and csqtt1 on 2.1", (rep.get("csqtt1") or {}).get("line") == "2.1", rep.get("csqtt1"))

        section("[6] refuse — never a guessed line")
        sync("nnew", [cand("csqtt40", "10.66.71.1/24", 46300, "/etc/csqtt40", version="", line=""),
                      cand("csqtt41", "10.66.72.1/24", 46400, "/etc/csqtt41", version="2.6.0", line="2.6")])
        code, r = req("/api/csqtt/adopt", {"node": "nnew", "iface": "csqtt40"})
        check("a binary the node could not read: refused", code == 400 and "csqtt40" not in (nodes()["nnew"].get("csqtt") or {}), (code, r))
        code, r = req("/api/csqtt/adopt", {"node": "nnew", "iface": "csqtt41"})
        check("a line the panel does not offer: refused, naming the version",
              code == 400 and "2.6.0" in json.dumps(r) and "csqtt41" not in (nodes()["nnew"].get("csqtt") or {}), (code, r))
        sync("nold", [cand("csqtt25", "10.66.68.1/24", 46100, "/etc/csqtt25", version="2.5.0", line="2.5")], lines=("2.1",))
        code, r = req("/api/csqtt/adopt", {"node": "nold", "iface": "csqtt25"})
        check("2.5 on a node that cannot run it: node_too_old", code == 400 and r.get("code") == "node_too_old", (code, r))

        section("[8] giveup — a take-over that never landed leaves nothing of the panel's behind")
        sync("nnew", [])                                  # starts every pending take-over's clock (adopt_at)
        nd = nodes()
        cs = nd["nnew"].get("csqtt") or {}
        check("before: csqtt30 and csqtt1 are pending take-overs",
              (cs.get("csqtt30") or {}).get("adopt_foreign") and (cs.get("csqtt1") or {}).get("adopt_foreign"), cs)
        if "csqtt30" in cs:
            cs["csqtt30"]["adopt_at"] = int(time.time()) - P.PROC_GRACE - 60   # its window is over
            json.dump(nd, open(NODES + ".t", "w")); os.replace(NODES + ".t", NODES)
        rep = sync("nnew", [])                             # the node still does not report csqtt30
        cs = nodes()["nnew"].get("csqtt") or {}
        ps = nodes()["nnew"].get("proc_status") or {}
        check("its record is dropped, so the node is not asked to install over the server still running",
              "csqtt30" not in cs and "csqtt30" not in rep, (sorted(cs), sorted(rep)))
        check("…and the panel says nothing was taken over", ps.get("state") == "adopt-failed" and "csqtt30" in json.dumps(ps), ps)
        check("a take-over still inside its window keeps its record and marker",
              (cs.get("csqtt1") or {}).get("adopt_foreign"), cs.get("csqtt1"))
    finally:
        proc.terminate()
        with __import__("contextlib").suppress(Exception):
            proc.wait(timeout=10)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][0] if isinstance(PLANTS[MODE][0], tuple) else (PLANTS[MODE][0],)
    hit = [s for s, _n in FAILS if s.split()[0] in secs]
    print("\nperturb %s: %s" % (MODE, ("caught by " + "/".join(sorted({h.split()[0] for h in hit}))) if hit
                                 else ("NOT caught by " + "/".join(secs))))
    sys.exit(0 if hit else 1)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL(S)" % len(FAILS)))
sys.exit(1 if FAILS else 0)
