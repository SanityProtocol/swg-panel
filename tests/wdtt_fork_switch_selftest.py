#!/usr/bin/env python3
"""Self-test — switching a WDTT server's fork after it is created (1.8.12 item 23, docs/RELEASE-1.8.12-PLAN.md
"Switching a WDTT server's fork").

The node's half: swg-noded loaded as a module in its docker shape, where a server is a supervised CHILD PROCESS — so a
"binary" here is a shell script that really runs, really dies and really writes its store (an "ildarmaga" makes its SQLite
schema on its first start, as the real one does). The interface the stable check reads is `lo`; nothing reaches systemd,
the network or a real TUN, and a link delete fails the test. The panel's half: a REAL panel process (temp state, scratch
port, no auth), the node played by POSTing snapshots to /api/node/sync.

  node
  [1] switch     amurcanov → qwdtt: only the `server` link and wdtt.env move; the address, ports and owner password stay;
                 passwords.json and wg-keys.dat are untouched; the store was copied first; the marker is gone; bare-metal
                 rewrites the unit for the target; qwdtt's store (no main_password) is completed for wdttplus, which
                 refuses to start without it (seen on the rig, 2026-11-27)
  [2] carry      → ildarmaga: every device row lands in panel.db (the target made the schema on a first start that
                 listened on 127.0.0.1 with RAW off), the JSON store is gone; ildarmaga → amurcanov: the rows are
                 passwords.json's devices again, panel.db is gone
  [3] fallback   a target that rewrites the store and dies 2 s in: back on the old fork with the old store, running;
                 memoed in the record and the snapshot; not retried next sync; the operator's Restart retries it; a
                 request back to the running fork clears it
  [4] cut        a switch a noded crash cut (marker left) is rolled back onto the copy, never resumed; the still-asked
                 switch then runs again, whole
  [5] reconcile  the record keeps the running fork until a switch is verified; one switch per pass; the pass that
                 switches restarts the server once (its cleared params are no second restart); a fork this node does not
                 know is refused, never read as amurcanov; a version update restarts the servers RUNNING its fork
  [6] snapshot   the node lists the forks it can switch to, and reports the fork that runs
  panel
  [7] reply      a capable node gets the record's fork, its build and `cur_ver` for what runs; an older node (no
                 `wdtt_forks`) and a node that does not list the target get the fork they report; a server not reported
                 yet gets the record's; while a switch waits the address pool is the smaller of both forks' (as csqtt's line)
  [8] door       an existing server's `fork` moves only with `fork_switch`; a target with no build is refused; a node
                 that cannot run it is `node_too_old`; a switch clears the extra flags, drops RAW for a target without
                 it (never turns it on), and is logged
  [9] unchanged  a server never switched gets the same reply as before the feature (the snap-less path), and a node
                 pass over it writes nothing and restarts nothing
  SWG_WFS_BASE=<commit> also compares, for never-switched servers, the node's unit and env (every fork, RAW on and off)
  and the panel's reply against that commit's programs (the docker argv is untouched by the change: _wdtt_argv).

Run: python3 tests/wdtt_fork_switch_selftest.py   (0 = pass)
     --perturb <name>  plants one regression and expects RED:
                       keepenv / unitfork / mainpw [1] · keepkeys [1] [2] · copy [1] [3] · carry-in / carry-out / seedaddr [2] · stable / revert [3] ·
                       memo [3] · cut [4] · recfork / onepass / restartonce / unknown / ifaces [5] · advert [6] ·
                       g1 / curver / runcap [7] · flag / notbuilt / tooold / params / rawoff [8] · same [9]
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {   # name: (file, section, anchor, replacement)
    "unitfork": ("n", "[1]", "        with open(_wdtt_unit_path(iface), \"w\") as f: f.write(_wdtt_unit_text(iface, cfgdir + \"/server\", cfgdir, fork))\n        host_sh(\"systemctl daemon-reload >/dev/null 2>&1\")\n\ndef _wdtt_paneldb_ready",
                 "        with open(_wdtt_unit_path(iface), \"w\") as f: f.write(_wdtt_unit_text(iface, cfgdir + \"/server\", cfgdir, _wdtt_fork(inst)))\n        host_sh(\"systemctl daemon-reload >/dev/null 2>&1\")\n\ndef _wdtt_paneldb_ready"),
    "keepenv": ("n", "[1]", "    with open(cfgdir + \"/wdtt.env.tmp\", \"w\") as f: f.write(text)\n    os.replace(cfgdir + \"/wdtt.env.tmp\", cfgdir + \"/wdtt.env\")\n", ""),
    "keepkeys": ("n", ("[1]", "[2]"), "_WDTT_STORE_FILES = (\"passwords.json\", \"passwords.json.previous\",", "_WDTT_STORE_FILES = (\"wg-keys.dat\", \"passwords.json\", \"passwords.json.previous\","),
    "copy": ("n", ("[1]", "[3]"), "        _csqtt_store_copy(_wdtt_dir(iface), \"wdtt\", _WDTT_STORE_FILES)\n    except Exception as e:", "        pass\n    except Exception as e:"),
    "carry-in": ("n", "[2]", "        c.executemany(\"INSERT OR REPLACE INTO wdtt_devices (device_id, ip, priv_key, pub_key) VALUES (?,?,?,?)\", rows)\n", ""),
    "carry-out": ("n", "[2]", "            json.dump({\"main_password\": \"\", \"passwords\": {},\n                       \"devices\": {r[0]: {\"device_id\": r[0], \"ip\": r[1], \"priv_key\": r[2], \"pub_key\": r[3]} for r in rows}}, f)",
                  "            json.dump({\"main_password\": \"\", \"passwords\": {},\n                       \"devices\": {}}, f)"),
    "mainpw": ("n", "[1]", "            if isinstance(d, dict) and not all(k in d for k in (\"main_password\", \"passwords\", \"devices\")):", "            if False:"),
    "seedaddr": ("n", "[2]", "    seed.update(fork=to, listen=\"127.0.0.1:%d\" % seed_port)", "    seed.update(fork=to)"),
    "stable": ("n", "[3]", "    err = err or _wdtt_start_one(dict(inst, fork=to)) or _wdtt_verify_stable(iface)", "    err = err or _wdtt_start_one(dict(inst, fork=to))"),
    "revert": ("n", ("[3]", "[4]", "[5]"), "    werr = _wdtt_back_to(back, frm)\n    return (err", "    werr = \"\"\n    return (err"),
    "backrec": ("n", "[3]", "    werr = _wdtt_back_to(back, frm)\n    return (err", "    werr = _wdtt_back_to(inst, frm)\n    return (err"),
    "keepown": ("n", ("[3]", "[5]"), "            if _wfork != _cur and prev:\n                # What RUNS keeps", "            if False:\n                # What RUNS keeps"),
    "memmemo": ("n", "[3]", "            _ff = prev.get(\"fork_failed\") or _WDTT_SWITCH_MEMO.get(iface) or {}", "            _ff = prev.get(\"fork_failed\") or {}"),
    "restartfetch": ("n", "[5]", "                _CSQTT_FETCH_LATER.pop((\"wdtt:\" + _wfork, (inst.get(\"ver\") or \"\").strip()), None)   # Restart", "                pass   # Restart"),
    "reinstallcur": ("n", "[5]", "                _ifk = _cutf or (_cur if _cur in WDTT_FORK_OWNER else _wfork)", "                _ifk = _cutf or _wfork"),
    "seedbind": ("n", "[2]", "    if str(inst[\"listen\"]).startswith(\"127.0.0.1:\"):", "    if False:"),
    "seedraw": ("n", "[2]", "    seed = {k: v for k, v in inst.items() if k not in (\"raw_port\", \"raw_iface\", \"raw_addr\", \"bind_ip\")}", "    seed = {k: v for k, v in inst.items() if k not in (\"bind_ip\",)}"),
    "seedenv": ("n", "[2]", "    with open(envp + \".tmp\", \"w\") as f: f.write(env0)", "    with open(envp + \".tmp\", \"w\") as f: f.write(_wdtt_env_text(seed))"),
    "memo": ("n", "[3]", "                inst[\"fork_failed\"] = _ff    # would not run here", "                pass    # would not run here"),
    "cut": ("n", "[4]", "    _cur = _cutf or _wdtt_running_fork(iface) or", "    _cutf = \"\"\n            _cur = _wdtt_running_fork(iface) or"),
    "recfork": ("n", ("[3]", "[5]"), "                if (inst.get(\"fork\") or \"amurcanov\") != _cur:\n                    inst[\"fork\"] = _cur      # what runs", "                if False:\n                    inst[\"fork\"] = _cur      # what runs"),
    "onepass": ("n", "[5]", "                        _sw_pass[0] or time.monotonic() < _CSQTT_FETCH_LATER.get((\"wdtt:\" + _wfork, _want_ver), 0)):", "                        time.monotonic() < _CSQTT_FETCH_LATER.get((\"wdtt:\" + _wfork, _want_ver), 0)):"),
    "restartonce": ("n", "[5]", "                elif not _switched and (_drifted or _wdtt_params_changed(prev, inst)", "                elif (_drifted or _wdtt_params_changed(prev, inst)"),
    "unknown": ("n", "[5]", "            _wfork = (inst.get(\"fork\") or \"amurcanov\").strip()", "            _wfork = _wdtt_fork(inst)"),
    "ifaces": ("n", "[5]", "if (_wdtt_running_fork(i) or _wdtt_fork(inst)) == fork]", "if _wdtt_fork(inst) == fork]"),
    "advert": ("n", "[6]", "    snap[\"wdtt_forks\"] = sorted(WDTT_FORK_OWNER)", "    pass"),
    "g1": ("p", ("[7]", "[9]"), "        if _run != _wfork and _wfork not in _forks:\n", "        if False:\n"),
    "curver": ("p", "[7]", "        if _run != _wfork and _run in WDTT_BUILDS:\n", "        if False:\n"),
    "flag": ("p", "[8]", "            elif body.get(\"fork_switch\") and _to and _to != _ofork:", "            elif _to and _to != _ofork:"),
    "notbuilt": ("p", "[8]", "                if _to not in WDTT_BUILDS:\n                    return 400", "                if False:\n                    return 400"),
    "tooold": ("p", "[8]", "                if _to not in ((_wsnap.get(\"wdtt_forks\")) or []):", "                if False:"),
    "params": ("p", "[8]", "                if not _pch:\n                    inst[\"params\"] = \"\"", "                if False:\n                    inst[\"params\"] = \"\""),
    "typedflags": ("p", "[8]", "                if not _pch:\n                    inst[\"params\"] = \"\"", "                if True:\n                    inst[\"params\"] = \"\""),
    "pickback": ("p", "[8]", "            if body.get(\"fork_switch\") and _to and _to != _ofork and _to == _run:", "            if False:"),
    "runfork": ("p", "[7]", "        fork = _wdtt_run_fork((deps.get(\"node_snaps\") or {}).get(nid), iface, inst)   # the board lists what RUNS", "        fork = inst.get(\"fork\") or \"amurcanov\""),
    "rawoff": ("p", "[8]", "                    body = {**body, \"raw\": False}        # the RAW step below", "                    pass        # the RAW step below"),
    "runcap": ("p", "[7]", "        if run and run != (rec.get(\"fork\") or \"amurcanov\"):\n            caps = [c for c in (turn_cap(kind, rec), turn_cap(kind, dict(rec, fork=run))) if c is not None]",
               "        if False:\n            caps = [c for c in (turn_cap(kind, rec), turn_cap(kind, dict(rec, fork=run))) if c is not None]"),
    "same": ("p", ("[7]", "[9]"), "        _run = str(_rows[iface].get(\"fork\") or \"amurcanov\") if iface in _rows else _wfork", "        _run = str(_rows[iface].get(\"fork\") or \"amurcanov\") if iface in _rows else \"\""),
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

TMP = tempfile.mkdtemp(prefix="wdtt-fork-switch-")
def planted(path, which):
    src = open(path, encoding="utf-8").read()
    if MODE and PLANTS[MODE][0] == which:
        old, new = PLANTS[MODE][2], PLANTS[MODE][3]
        assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
        src = src.replace(old, new)
    p = os.path.join(TMP, os.path.basename(path) + "-" + which + ".py"); open(p, "w", encoding="utf-8").write(src)
    return p
def load(path, name):
    os.environ["SWG_NO_REEXEC"] = "1"
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m

NODED_P = planted(NODED, "n")
SERVER_P = planted(SERVER, "p")
N = load(NODED_P, "swgnoded_wfs")

# ── the node's sandbox ─────────────────────────────────────────────────────────────────────────────────────────────
def sandbox(M, sub):
    M.NODE_KIND = "docker"
    M.WDTT_ROOT = os.path.join(TMP, sub); M.WDTT_BIN_DIR = M.WDTT_ROOT + "/.bin"
    M.WDTT_RECORD = os.path.join(TMP, sub + ".json")
    M._turn_arch = lambda: "amd64"
    M._turn_arch_ok = lambda: True
    M._wdtt_argv = lambda inst, binp: [binp, M._wdtt_dir(inst["iface"])]
    M._wdtt_takes_dns = lambda fork, force=False: None
    M._wdtt_adopted_users = lambda *a, **k: {}
    M._wdtt_env_drifted = lambda *a, **k: False
    M.bind_heal_due = lambda *a, **k: False
    M._csqtt_scan_ok = lambda: True
    M._wdtt_foreign_pid = lambda iface: None
    def _guard(cmd, *a, **k):
        if "link" in str(cmd) and "del" in str(cmd):
            raise AssertionError("the test reached a link delete: " + str(cmd))
        class R: returncode, stdout, stderr = 0, "", ""
        return R()
    M.host_sh = _guard
sandbox(N, "wdtt")
GOOD = "#!/bin/sh\ntrap '' HUP\nexec sleep 300\n"   # a real server reloads desired.json on SIGHUP — it does not die of it
# ildarmaga makes its own schema on a first start, for a missing panel.db only (our patch's ensurePanelDB)
ILDAR = ("#!/bin/sh\ntrap '' HUP\n[ -f \"$1/panel.db\" ] || python3 -I -c \"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
         "c.execute('CREATE TABLE wdtt_devices (device_id TEXT PRIMARY KEY, ip TEXT NOT NULL DEFAULT \\'\\', "
         "priv_key TEXT NOT NULL DEFAULT \\'\\', pub_key TEXT NOT NULL DEFAULT \\'\\')'); c.commit()\" \"$1/panel.db\"\nexec sleep 300\n")
DIES = "#!/bin/sh\necho MIGRATED > \"$1/passwords.json\"\nsleep 2\nexit 1\n"
BUILD = {"amurcanov": GOOD, "qwdtt": GOOD, "wdttplus": GOOD, "ildarmaga": ILDAR, "xxcipherx": GOOD}
FETCHES = []
def fake_fetch(fork, inst, binshared, ver=None):
    FETCHES.append((fork, ver))
    os.makedirs(os.path.dirname(binshared), exist_ok=True)
    open(binshared, "w").write(BUILD[fork]); os.chmod(binshared, 0o755)
    return ""
N._wdtt_fetch_bin = fake_fetch
STARTS = []
_real_start = N._wdtt_docker_start
def rec_start(inst):
    STARTS.append((inst["iface"], N._wdtt_fork(inst), inst.get("listen"), bool(N._wdtt_raw(inst))))
    return _real_start(inst)
N._wdtt_docker_start = rec_start

DEVS = {"pw:pw1": {"device_id": "pw:pw1", "ip": "10.66.70.2", "priv_key": "PRIV1", "pub_key": "PUB1"},
        "pw:pw2": {"device_id": "pw:pw2", "ip": "10.66.70.3", "priv_key": "PRIV2", "pub_key": "PUB2"}}
KEYS = b"A" * 44 + b"\n" + b"B" * 44 + b"\n" + b"C" * 44 + b"\n" + b"D" * 44 + b"\n"
def base_inst(iface, fork, **kw):
    return dict({"iface": iface, "fork": fork, "wg_addr": "10.66.70.1/24", "listen": "0.0.0.0:56000", "wg_port": 56001,
                 "max_passwords": 200, "panel_managed": True, "pw_seen": True, "password": "owner-pw",
                 "passwords": {"pw1": {}, "pw2": {}}, "ver": "v-" + fork}, **kw)
def lay(iface, fork, store=True, **kw):
    """A running server of ours on `fork`, with two devices in passwords.json and an identity."""
    d = N._wdtt_dir(iface); N._wdtt_docker_stop(iface); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    slot = N._wdtt_bin_shared(fork)
    if not os.path.exists(slot):
        fake_fetch(fork, {}, slot); N._wdtt_write_ver(fork, "v-" + fork)
    N._csqtt_relink(d + "/server", slot)
    if store:
        json.dump({"main_password": "owner-pw", "passwords": {"pw1": {}, "pw2": {}}, "devices": DEVS}, open(d + "/passwords.json", "w"))   # amurcanov's shape
    open(d + "/wg-keys.dat", "wb").write(KEYS)
    inst = base_inst(iface, fork, **kw)
    open(d + "/wdtt.env", "w").write(N._wdtt_env_text(inst))
    open(d + "/desired.json", "w").write(N._wdtt_desired_body(inst["passwords"]) + "\n")
    N._wdtt_docker_start(inst)
    return inst
def want_of(inst, **kw):
    w = {k: v for k, v in inst.items() if k not in ("panel_managed", "pw_seen", "password", "iface")}
    w.update(kw); return w
def save(*insts):
    N._wdtt_save({i["iface"]: dict(i) for i in insts})
def pid(iface):
    return N._wdtt_docker_pid(iface)
def jdevs(iface):
    try:
        return (json.load(open(N._wdtt_dir(iface) + "/passwords.json")) or {}).get("devices")
    except Exception:
        return None
def dbrows(iface):
    p = N._wdtt_dir(iface) + "/panel.db"
    if not os.path.exists(p):
        return None
    c = sqlite3.connect(p)
    try: return {r[0]: {"device_id": r[0], "ip": r[1], "priv_key": r[2], "pub_key": r[3]}
                 for r in c.execute("SELECT device_id, ip, priv_key, pub_key FROM wdtt_devices")}
    finally: c.close()
def keys(iface):
    try:
        return open(N._wdtt_dir(iface) + "/wg-keys.dat", "rb").read()
    except OSError:
        return None
def stop_all():
    for i in list(N._WDTT_PROCS):
        N._wdtt_docker_stop(i)
def rec(iface):
    return N._wdtt_load().get(iface) or {}

PANEL = {"proc": None}
try:
    section("[1] switch amurcanov → qwdtt")
    a = lay("lo", "amurcanov", params="-old-flag")
    env0 = open(N._wdtt_dir("lo") + "/wdtt.env").read()
    pj0 = open(N._wdtt_dir("lo") + "/passwords.json").read()
    a = dict(a, params="")                                    # the door cleared them with the switch
    err, memo = N._wdtt_switch_fork(dict(a), "amurcanov", "qwdtt", "1.4.4-2")
    check("the switch reports success", err == "" and memo is False, (err, memo))
    check("the server's link points into qwdtt's slot", N._wdtt_running_fork("lo") == "qwdtt", os.readlink(N._wdtt_dir("lo") + "/server"))
    check("qwdtt's slot is stamped with the build the panel named", N._wdtt_installed_ver("qwdtt") == "1.4.4-2", N._wdtt_installed_ver("qwdtt"))
    env1 = open(N._wdtt_dir("lo") + "/wdtt.env").read()
    check("wdtt.env is the target's, rendered from the same record (its cleared flags gone)",
          env1 == N._wdtt_env_text(dict(a, fork="qwdtt")) and "SWG_PARAMS=\n" in env1 and "-old-flag" in env0, env1)
    keep = ("SWG_IFACE=lo", "SWG_WGADDR=10.66.70.1/24", "SWG_WGPORT=56001", "SWG_PASSWORD=owner-pw", "SWG_MAXPW=200")
    check("…the interface, its address, ports and owner password kept", all(k in env1 for k in keep) and env0.split("SWG_LISTEN")[1].split("\n")[0] == env1.split("SWG_LISTEN")[1].split("\n")[0], env1)
    check("passwords.json untouched (the JSON forks share it)", open(N._wdtt_dir("lo") + "/passwords.json").read() == pj0)
    check("wg-keys.dat untouched", keys("lo") == KEYS)
    bk = N._csqtt_store_bak(N._wdtt_dir("lo"), "wdtt")
    check("the store was copied before the repoint", os.path.exists(bk + "/passwords.json") and open(bk + "/passwords.json").read() == pj0)
    check("…and wg-keys.dat is not part of the copy (never moved)", not os.path.exists(bk + "/wg-keys.dat"))
    stop_all()
    q = lay("lo", "qwdtt")                                    # qwdtt saves no main_password; wdttplus refuses a file without it
    json.dump({"passwords": {"pw1": {}, "pw2": {}}, "devices": DEVS}, open(N._wdtt_dir("lo") + "/passwords.json", "w"))
    err, memo = N._wdtt_switch_fork(dict(q), "qwdtt", "wdttplus", "20-1")
    pjw = json.load(open(N._wdtt_dir("lo") + "/passwords.json"))
    check("qwdtt → wdttplus: the store gains the keys wdttplus requires, its users and devices kept",
          err == "" and all(k in pjw for k in ("main_password", "passwords", "devices")) and pjw["devices"] == DEVS
          and pjw["passwords"] == {"pw1": {}, "pw2": {}}, (err, sorted(pjw)))
    check("the marker is gone and the server runs", not os.path.exists(N._wdtt_cut_path("lo")) and bool(pid("lo")))
    UNIT = os.path.join(TMP, "unit-lo")                       # bare-metal / NixOS: the unit is rewritten for the target too
    _kind, _up = N.NODE_KIND, N._wdtt_unit_path
    N.NODE_KIND, N._wdtt_unit_path = "bare", (lambda i: UNIT)
    try:
        N._wdtt_put_fork(dict(a, fork="amurcanov"), "ildarmaga")
    finally:
        N.NODE_KIND, N._wdtt_unit_path = _kind, _up
    ut = open(UNIT).read() if os.path.exists(UNIT) else ""
    check("bare-metal: the unit is the target's (its flag tail and owner)", ut == N._wdtt_unit_text("lo", N._wdtt_dir("lo") + "/server", N._wdtt_dir("lo"), "ildarmaga")
          and "-max-users" in ut and "ildarmaga" in ut, ut[:200])
    N._wdtt_put_fork(dict(a, fork="ildarmaga"), "qwdtt")      # (back on qwdtt's slot for the docker run)

    section("[2] carry the devices to and from ildarmaga")
    stop_all(); STARTS.clear()
    RAW0 = {"raw_port": 56003, "raw_iface": "wdttraw0", "raw_addr": "10.70.0.1/24"}
    a = lay("lo", "qwdtt", **RAW0)                            # RAW on both sides: only the seed start goes without it
    err, memo = N._wdtt_switch_fork(dict(a), "qwdtt", "ildarmaga", "1.5.0-4")
    check("qwdtt (RAW) → ildarmaga succeeds", err == "", err)
    envi = open(N._wdtt_dir("lo") + "/wdtt.env").read()
    check("…its wdtt.env is the real one again, not the seed's (its own address, RAW on)",
          "SWG_LISTEN=0.0.0.0:56000\n" in envi and "-listen-raw" in envi, envi)
    se = N._wdtt_env_text(dict(a, fork="ildarmaga", listen="127.0.0.1:41234"))
    check("a loopback listen (the seed's) is bound as written — turn_bind would make it every address",
          "SWG_LISTEN=127.0.0.1:41234\n" in se and N._wdtt_listen_bind({"listen": "127.0.0.1:41234"}, "/x") == "127.0.0.1:41234", se)
    check("every device row is in panel.db", dbrows("lo") == DEVS, dbrows("lo"))
    check("the JSON store is gone (its copy is in the .bak)", not os.path.exists(N._wdtt_dir("lo") + "/passwords.json"))
    seed = [s for s in STARTS if s[0] == "lo" and s[1] == "ildarmaga"]
    check("ildarmaga's first start (its schema) listened on 127.0.0.1 with RAW off, and its real one has RAW",
          len(seed) == 2 and str(seed[0][2]).startswith("127.0.0.1:") and seed[0][3] is False and seed[1][3] is True, seed)
    check("…and the real start is on the server's own address", len(seed) == 2 and seed[1][2] == "0.0.0.0:56000", seed)
    check("the server runs ildarmaga", N._wdtt_running_fork("lo") == "ildarmaga" and bool(pid("lo")))
    a = {k: v for k, v in a.items() if k not in RAW0}         # the door drops RAW for amurcanov
    err, memo = N._wdtt_switch_fork(dict(a, fork="ildarmaga"), "ildarmaga", "amurcanov", "1.2.4-3")
    check("ildarmaga → amurcanov succeeds", err == "", err)
    check("passwords.json's devices are panel.db's rows again", jdevs("lo") == DEVS, jdevs("lo"))
    check("panel.db is gone", not os.path.exists(N._wdtt_dir("lo") + "/panel.db"))
    check("wg-keys.dat untouched through both", keys("lo") == KEYS)

    section("[3] a target that will not run")
    stop_all()
    a = lay("lo", "amurcanov")
    shutil.rmtree(os.path.dirname(N._wdtt_bin_shared("qwdtt")), ignore_errors=True)
    BUILD["qwdtt"] = DIES
    err, memo = N._wdtt_switch_fork(dict(a), "amurcanov", "qwdtt", "9.9-dies")
    check("the switch fails and says it is memoed", bool(err) and memo is True, (err, memo))
    check("…naming an exit", "exited" in err or "didn't stay up" in err or "rc=" in err, err)
    check("back on amurcanov", N._wdtt_running_fork("lo") == "amurcanov")
    check("…with amurcanov's store, not the one qwdtt wrote", jdevs("lo") == DEVS, jdevs("lo"))
    check("…running", bool(pid("lo")))
    stop_all()
    a = lay("lo", "amurcanov")
    save(a)
    w3 = {"lo": want_of(a, fork="qwdtt", ver="9.9-dies", cur_ver=N._wdtt_installed_ver("amurcanov"))}   # what runs: no build update
    N.reconcile_wdtt(w3)
    check("through the reconcile: the record keeps amurcanov and memos the failure",
          rec("lo").get("fork") == "amurcanov" and (rec("lo").get("fork_failed") or {}).get("fork") == "qwdtt", rec("lo"))
    snap3 = {r["iface"]: r for r in N.wdtt_snapshot()}
    check("the snapshot reports it", (snap3.get("lo") or {}).get("fork_failed", {}).get("fork") == "qwdtt"
          and snap3["lo"]["fork"] == "amurcanov", snap3.get("lo"))
    n0, p0 = len(STARTS), pid("lo")
    N.reconcile_wdtt(w3)
    check("not retried on the next sync (nothing restarted)", len(STARTS) == n0 and pid("lo") == p0 and N._wdtt_running_fork("lo") == "amurcanov", STARTS[n0:])
    BUILD["qwdtt"] = GOOD
    shutil.rmtree(os.path.dirname(N._wdtt_bin_shared("qwdtt")), ignore_errors=True)
    N.reconcile_wdtt({"lo": dict(w3["lo"], restart=1)})
    check("the operator's Restart retries it (and a good build now runs)", N._wdtt_running_fork("lo") == "qwdtt"
          and rec("lo").get("fork") == "qwdtt" and not rec("lo").get("fork_failed"), rec("lo"))
    stop_all()
    q = lay("lo", "qwdtt", params="-old-flag", **RAW0); save(q)
    envq = open(N._wdtt_dir("lo") + "/wdtt.env").read()
    shutil.rmtree(os.path.dirname(N._wdtt_bin_shared("wdttplus")), ignore_errors=True)
    BUILD["wdttplus"] = DIES
    wq = want_of(q, fork="wdttplus", ver="9.9-dies", params="", cur_ver=N._wdtt_installed_ver("qwdtt"))
    for k in RAW0: wq.pop(k)                                  # the door's record: the flags cleared, RAW dropped
    N.reconcile_wdtt({"lo": wq})
    check("a failed switch puts it back as it ran: its flags and RAW (the record already names the target's)",
          N._wdtt_running_fork("lo") == "qwdtt" and open(N._wdtt_dir("lo") + "/wdtt.env").read() == envq
          and rec("lo").get("params") == "-old-flag" and rec("lo").get("raw_port") == 56003, (rec("lo"), open(N._wdtt_dir("lo") + "/wdtt.env").read()))
    n0, p0 = len(STARTS), pid("lo")
    N.reconcile_wdtt({"lo": wq})
    check("…and the next pass restarts nothing (no reconfigure onto the target's cleared flags)", len(STARTS) == n0 and pid("lo") == p0, STARTS[n0:])
    save(dict(rec("lo"), fork_failed=None))                   # its record write never landed (a full disk)
    N.reconcile_wdtt({"lo": wq})
    check("…nor when the record lost its memo: the node remembers it", len(STARTS) == n0 and pid("lo") == p0, STARTS[n0:])
    BUILD["wdttplus"] = GOOD; N._WDTT_SWITCH_MEMO.clear()
    shutil.rmtree(os.path.dirname(N._wdtt_bin_shared("wdttplus")), ignore_errors=True)
    stop_all()
    a = lay("lo", "amurcanov"); save(dict(a, fork_failed={"fork": "qwdtt", "ver": "x", "why": "y"}))
    N.reconcile_wdtt({"lo": want_of(a)})
    check("a request back to the running fork clears the memo", not rec("lo").get("fork_failed"), rec("lo"))

    section("[4] a switch a crash cut")
    stop_all()
    a = lay("lo", "amurcanov"); save(a)
    d = N._wdtt_dir("lo")
    N._csqtt_store_copy(d, "wdtt", N._WDTT_STORE_FILES); N._wdtt_cut_mark("lo", "amurcanov")
    N._csqtt_relink(d + "/server", N._wdtt_bin_shared("qwdtt"))   # the cut pass repointed, then qwdtt ran and rewrote the store
    open(d + "/passwords.json", "w").write("REWRITTEN\n")
    w4 = {"lo": want_of(a, fork="qwdtt", ver=N._wdtt_installed_ver("qwdtt"), cur_ver="v-amurcanov")}
    N.reconcile_wdtt(w4)
    check("rolled back to amurcanov", N._wdtt_running_fork("lo") == "amurcanov", os.readlink(d + "/server"))
    check("…onto the copy, not the store qwdtt rewrote", jdevs("lo") == DEVS, open(d + "/passwords.json").read()[:80])
    check("…the marker is gone and it runs", not os.path.exists(N._wdtt_cut_path("lo")) and bool(pid("lo")))
    N.reconcile_wdtt(w4)
    check("the next pass runs the still-asked switch, whole", N._wdtt_running_fork("lo") == "qwdtt" and rec("lo").get("fork") == "qwdtt", rec("lo").get("fork"))

    section("[5] the reconcile")
    stop_all()
    a = lay("lo", "amurcanov", params="-old-flag"); s = lay("wdttsib", "amurcanov", store=True)
    save(a, s)
    STARTS.clear()
    N._CSQTT_FETCH_LATER[("wdtt:qwdtt", "9.9-wait")] = time.monotonic() + 600   # a build whose fetch failed: the switch waits
    N.reconcile_wdtt({"lo": want_of(a, fork="qwdtt", ver="9.9-wait", params="", cur_ver="v-amurcanov"), "wdttsib": want_of(s)})
    check("while a switch waits, the record keeps the fork that runs", rec("lo").get("fork") == "amurcanov", rec("lo").get("fork"))
    check("…and its ver is the running fork's build (cur_ver)", rec("lo").get("ver") == "v-amurcanov", rec("lo").get("ver"))
    check("…and its own flags: nothing restarts it onto the target's cleared ones",
          not [x for x in STARTS if x[0] == "lo"] and rec("lo").get("params") == "-old-flag", (STARTS, rec("lo").get("params")))
    N.reconcile_wdtt({"lo": want_of(a, fork="qwdtt", ver="9.9-wait", params="", cur_ver="v-amurcanov", restart=7), "wdttsib": want_of(s)})
    check("the operator's Restart retries a waiting fetch at once (the switch runs)", N._wdtt_running_fork("lo") == "qwdtt"
          and rec("lo").get("fork") == "qwdtt" and rec("lo").get("params") == "", (N._wdtt_running_fork("lo"), rec("lo").get("params")))
    N._CSQTT_FETCH_LATER.pop(("wdtt:qwdtt", "9.9-wait"), None)
    stop_all()
    a = lay("lo", "amurcanov"); save(a); stop_all()
    INST = []; _pr, _in = N._wdtt_present, N._wdtt_install
    N._wdtt_present, N._wdtt_install = (lambda i: False), (lambda i: INST.append(N._wdtt_fork(i)) or "")
    try:
        N.reconcile_wdtt({"lo": want_of(a, fork="qwdtt", ver=N._wdtt_installed_ver("qwdtt"), cur_ver="v-amurcanov")})
    finally:
        N._wdtt_present, N._wdtt_install = _pr, _in
    check("its unit gone (a NixOS reboot), a server asked for another fork is re-installed on the one that ran, never the "
          "asked one straight over its store", INST == ["amurcanov"] and rec("lo").get("fork") == "amurcanov", (INST, rec("lo").get("fork")))
    stop_all()
    a = lay("lo", "amurcanov", params="-old-flag"); s = lay("wdttsib", "amurcanov")
    save(a, s)
    STARTS.clear()
    vq = N._wdtt_installed_ver("qwdtt")
    N.reconcile_wdtt({"lo": want_of(a, fork="qwdtt", ver=vq, params="", cur_ver="v-amurcanov"),
                      "wdttsib": want_of(s, fork="qwdtt", ver=vq, params="", cur_ver="v-amurcanov")})
    moved = [i for i in ("lo", "wdttsib") if N._wdtt_running_fork(i) == "qwdtt"]
    tried = sorted({x[0] for x in STARTS if x[1] == "qwdtt"})
    check("two servers asking in one pass: one switches, the other is not even tried", moved == ["lo"] and tried == ["lo"], (moved, tried))
    lo_starts = [x for x in STARTS if x[0] == moved[0]] if moved else []
    check("the switching pass restarted it once (cleared params are no second restart)", len(lo_starts) == 1, lo_starts)
    stop_all()
    a = lay("lo", "qwdtt"); save(a)
    N.reconcile_wdtt({"lo": want_of(a, fork="zzfuture", ver="1")})
    check("a fork this node does not know: refused, the server stays on qwdtt (never read as amurcanov)",
          N._wdtt_running_fork("lo") == "qwdtt" and rec("lo").get("fork") == "qwdtt", (N._wdtt_running_fork("lo"), rec("lo").get("fork")))
    stop_all()
    a = lay("lo", "amurcanov"); s = lay("wdttsib", "qwdtt"); save(a, s)
    w5 = {"lo": want_of(a, fork="qwdtt"), "wdttsib": want_of(s)}
    check("a version update's servers are the ones RUNNING the fork, not the ones asked for it",
          sorted(N._wdtt_fork_ifaces("qwdtt", w5)) == ["wdttsib"], N._wdtt_fork_ifaces("qwdtt", w5))

    section("[6] the snapshot")
    src_n = open(NODED_P, encoding="utf-8").read()
    check("the node lists the forks it can switch to (snap[\"wdtt_forks\"])", "snap[\"wdtt_forks\"] = sorted(WDTT_FORK_OWNER)" in src_n)
    rows = {r["iface"]: r for r in N.wdtt_snapshot()}
    check("…and reports the fork that runs", rows.get("lo", {}).get("fork") == "amurcanov", rows.get("lo"))

    # ── the panel ──────────────────────────────────────────────────────────────────────────────────────────────────
    stop_all()
    P = load(SERVER_P, "swgpanel_wfs")
    BUILDS = {f: P._wdtt_current_version(f) for f in ("amurcanov", "ildarmaga", "qwdtt", "wdttplus")}
    def free_port():
        so = socket.socket(); so.bind(("127.0.0.1", 0)); p = so.getsockname()[1]; so.close(); return p
    state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
    NODES = os.path.join(state, "nodes.json")
    W = lambda fork, port, sub, **kw: dict({"fork": fork, "listen": "0.0.0.0:%d" % port, "wg_addr": "10.66.%d.1/24" % sub,
                                             "wg_port": port + 1, "max_passwords": 200, "title": ""}, **kw)
    json.dump({"nnew": {"id": "nnew", "name": "nnew", "links": {}, "ifaces": {},
                        "wdtt": {"wdtt1": W("amurcanov", 56100, 81), "wdtt2": W("qwdtt", 56110, 82, raw_port=56003, raw_iface="wdttraw2", raw_addr="10.70.2.1/24"),
                                 "wdtt3": W("amurcanov", 56120, 83, params="-x 1")}},
               "nold": {"id": "nold", "name": "nold", "links": {}, "ifaces": {}, "wdtt": {"wdtt1": W("amurcanov", 56130, 84)}}},
              open(NODES, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    fleet = os.path.join(TMP, "fleet.json")
    json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    PORT = free_port()
    log = open(os.path.join(TMP, "panel.log"), "w+")
    PANEL["proc"] = subprocess.Popen([sys.executable, SERVER_P], stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT,
                                          "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "",
                                          "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
    def req(path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
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
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if PANEL["proc"].poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("nnew", "nold")}
    def nodes():
        return json.load(open(NODES))
    RUN = {"nnew": {"wdtt1": "amurcanov", "wdtt2": "qwdtt", "wdtt3": "amurcanov"}, "nold": {"wdtt1": "amurcanov"}}
    def snapshot(nid, forks=True):
        recs = nodes()[nid].get("wdtt") or {}
        s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
             "wdtt": [{"iface": i, "fork": RUN[nid].get(i, r.get("fork")), "active": "active", "listen": r.get("listen"),
                       "wg_addr": r.get("wg_addr"), "wg_port": r.get("wg_port"), "max_passwords": r.get("max_passwords"),
                       "params": r.get("params") or "", "dns": "", "version": BUILDS.get(RUN[nid].get(i, r.get("fork")), ""),
                       "passwords": {}, "devices": {}} for i, r in recs.items()]}
        if forks and nid == "nnew":
            s["wdtt_forks"] = ["amurcanov", "ildarmaga", "qwdtt", "wdttplus", "xxcipherx"]
        return s
    def sync(nid, forks=True):
        code, r = req("/api/node/sync", {"snapshot": snapshot(nid, forks)}, TOK[nid])
        assert code == 200, (code, r)
        return r.get("wdtt") or {}
    sync("nnew"); sync("nold")

    section("[8] the door")
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt1", "fork": "ildarmaga", "listen": "0.0.0.0:56100", "wg_addr": "10.66.81.1/24", "title": "t"})
    check("a save that sends another fork without fork_switch (every older tab's save) changes no fork",
          code == 200 and nodes()["nnew"]["wdtt"]["wdtt1"]["fork"] == "amurcanov", (code, r, nodes()["nnew"]["wdtt"]["wdtt1"].get("fork")))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt1", "fork": "xxcipherx", "fork_switch": True})
    check("a target with no published build is refused", code == 400 and nodes()["nnew"]["wdtt"]["wdtt1"]["fork"] == "amurcanov", (code, r))
    code, r = req("/api/wdtt/set", {"node": "nold", "iface": "wdtt1", "fork": "qwdtt", "fork_switch": True})
    check("a node that cannot run it: node_too_old", code == 400 and r.get("code") == "node_too_old"
          and nodes()["nold"]["wdtt"]["wdtt1"]["fork"] == "amurcanov", (code, r))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt3", "fork": "ildarmaga", "fork_switch": True, "params": "-x 1"})
    w3r = nodes()["nnew"]["wdtt"]["wdtt3"]
    check("a switch is accepted and stored", code == 200 and w3r.get("fork") == "ildarmaga", (code, r, w3r))
    check("…its extra flags are cleared (they were amurcanov's)", not w3r.get("params"), w3r.get("params"))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt3", "fork": "amurcanov", "fork_switch": True, "params": ""})
    w3r = nodes()["nnew"]["wdtt"]["wdtt3"]
    check("back to amurcanov while the node still runs it: its flags come back, and the door forgets the switch",
          code == 200 and w3r.get("fork") == "amurcanov" and w3r.get("params") == "-x 1" and "switch_from" not in w3r, (code, r, w3r))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt3", "fork": "ildarmaga", "fork_switch": True, "params": "-y 2"})
    w3r = nodes()["nnew"]["wdtt"]["wdtt3"]
    check("flags typed in the switch's own save are the target's and stay", code == 200 and w3r.get("fork") == "ildarmaga"
          and w3r.get("params") == "-y 2", (code, r, w3r))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt2", "fork": "amurcanov", "fork_switch": True, "raw": True})
    w2r = nodes()["nnew"]["wdtt"]["wdtt2"]
    check("qwdtt with RAW → amurcanov: accepted with RAW off", code == 200 and w2r.get("fork") == "amurcanov"
          and not any(k in w2r for k in ("raw_port", "raw_iface", "raw_addr")), (code, r, w2r))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt2", "fork": "qwdtt", "fork_switch": True, "raw": False})
    w2r = nodes()["nnew"]["wdtt"]["wdtt2"]
    check("…back to qwdtt while the node still runs it: RAW comes back as it was", code == 200 and w2r.get("fork") == "qwdtt"
          and w2r.get("raw_port") == 56003 and w2r.get("raw_iface") and "switch_from" not in w2r, (code, r, w2r))
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt2", "fork": "amurcanov", "fork_switch": True})
    RUN["nnew"]["wdtt2"] = "amurcanov"; sync("nnew")          # this time the node switched it
    code, r = req("/api/wdtt/set", {"node": "nnew", "iface": "wdtt2", "fork": "qwdtt", "fork_switch": True})
    w2r = nodes()["nnew"]["wdtt"]["wdtt2"]
    check("…and back to qwdtt once amurcanov runs does not turn RAW on by itself", code == 200 and w2r.get("fork") == "qwdtt" and not w2r.get("raw_port"), w2r)
    code, ev = req("/api/events?limit=50")
    check("a switch is in the activity log", "Switching a WDTT server's fork" in json.dumps(ev, ensure_ascii=False), str(ev)[:200])

    section("[7] the reply")
    RUN["nnew"]["wdtt3"] = "amurcanov"                          # asked ildarmaga, still runs amurcanov
    r7 = sync("nnew")
    w3 = r7.get("wdtt3") or {}
    check("a capable node: the record's fork and its build", w3.get("fork") == "ildarmaga" and w3.get("ver") == BUILDS["ildarmaga"], w3)
    check("…and cur_ver for the fork it still runs", w3.get("cur_ver") == BUILDS["amurcanov"], w3)
    code, r = req("/api/wdtt/version", {"node": "nnew", "iface": "wdtt3", "ver": BUILDS["amurcanov"]})
    code2, v = req("/api/wdtt/versions?node=nnew&iface=wdtt3")
    check("the version board acts on the fork that runs, not the one asked for", code == 200 and code2 == 200
          and (v.get("data") or {}).get("fork") == "amurcanov" and (v.get("data") or {}).get("held") == BUILDS["amurcanov"], (code, r, v))
    req("/api/wdtt/version", {"node": "nnew", "iface": "wdtt3", "ver": ""})
    n = nodes(); n["nold"]["wdtt"]["wdtt1"]["fork"] = "qwdtt"   # a record carried to an older node (a downgrade, a copy)
    json.dump(n, open(NODES + ".tmp", "w")); os.replace(NODES + ".tmp", NODES)
    o1 = sync("nold").get("wdtt1") or {}
    check("an older node (no wdtt_forks): the fork it reports and that fork's build, never the record's",
          o1.get("fork") == "amurcanov" and o1.get("ver") == BUILDS["amurcanov"] and "cur_ver" not in o1, o1)
    n = nodes(); n["nnew"]["wdtt"]["wdtt1"]["fork"] = "zzfuture"
    json.dump(n, open(NODES + ".tmp", "w")); os.replace(NODES + ".tmp", NODES)
    z1 = sync("nnew").get("wdtt1") or {}
    check("a fork the node does not list: the fork it reports", z1.get("fork") == "amurcanov" and z1.get("ver") == BUILDS["amurcanov"], z1)
    big = W("qwdtt", 56210, 97); big["wg_addr"] = "10.66.0.1/23"        # 509 addresses asked; amurcanov still runs (249)
    check("while a switch waits, the pool is the smaller of the asked fork's and the running one's (a failed switch keeps "
          "every user admitted meanwhile)", P.turn_run_cap("wdtt", big, {"wdtt": [{"iface": "wbig", "fork": "amurcanov"}]}, "wbig") == 249
          and P.turn_run_cap("wdtt", big, {"wdtt": [{"iface": "wbig", "fork": "qwdtt"}]}, "wbig") == 509)
    roster = {}
    nn = {"x": {"wdtt": {"wnew": W("qwdtt", 56200, 90)}}}
    check("a server the node does not report yet: the record's fork", (P._wdtt_reply(roster, nn, "x", "", None, {"wdtt": [], "wdtt_forks": []}).get("wnew") or {}).get("fork") == "qwdtt")

    section("[9] a server never switched")
    nn = {"x": {"wdtt": {"wa": W("amurcanov", 56300, 91), "wq": W("qwdtt", 56310, 92, raw_port=56003, raw_iface="wdttraw9", raw_addr="10.70.9.1/24"),
                         "wi": W("ildarmaga", 56320, 93), "wp": W("wdttplus", 56330, 94), "wx": W("xxcipherx", 56340, 95), "wn": {"listen": "0.0.0.0:56350", "wg_addr": "10.66.96.1/24"}}}}
    rows9 = [{"iface": i, "fork": (r.get("fork") or "amurcanov")} for i, r in nn["x"]["wdtt"].items()]
    for forks in ([], ["amurcanov", "ildarmaga", "qwdtt", "wdttplus", "xxcipherx"]):
        same = P._wdtt_reply(roster, nn, "x", "", None, {"wdtt": rows9, **({"wdtt_forks": forks} if forks else {})}) == P._wdtt_reply(roster, nn, "x", "", None)
        check("the reply is exactly the snap-less one (old node: %s)" % (not forks), same)
    stop_all()
    a = lay("lo", "qwdtt", raw_port=56003, raw_iface="wdttraw0", raw_addr="10.70.0.1/24"); save(a)
    w9 = {"lo": want_of(a)}
    N.reconcile_wdtt(w9)
    p9 = pid("lo"); env9 = open(N._wdtt_dir("lo") + "/wdtt.env").read(); m9 = os.path.getmtime(N._wdtt_dir("lo") + "/wdtt.env")
    STARTS.clear(); time.sleep(0.05)
    N.reconcile_wdtt(w9)
    check("a node pass over it restarts nothing", pid("lo") == p9 and not STARTS, STARTS)
    check("…rewrites no env", open(N._wdtt_dir("lo") + "/wdtt.env").read() == env9 and os.path.getmtime(N._wdtt_dir("lo") + "/wdtt.env") == m9)
    check("…and records no switch state", not any(k in rec("lo") for k in ("fork_failed",)) and rec("lo").get("fork") == "qwdtt", rec("lo"))

    BASE = os.environ.get("SWG_WFS_BASE")
    if BASE and not MODE:
        section("[B] never-switched servers vs %s" % BASE)
        d = tempfile.mkdtemp(prefix="wfs-base-")
        for f in ("swg-noded", "swg-panel-server"):
            open(os.path.join(d, f + ".py"), "w").write(subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (BASE, f)],
                                                                       capture_output=True, text=True, check=True).stdout)
        NB = load(os.path.join(d, "swg-noded.py"), "swgnoded_wfs_base"); sandbox(NB, "wdtt")
        PB = load(os.path.join(d, "swg-panel-server.py"), "swgpanel_wfs_base")
        for f in ("amurcanov", "ildarmaga", "qwdtt", "wdttplus", "xxcipherx"):
            for raw in ({}, {"raw_port": 56003, "raw_iface": "wdttraw0", "raw_addr": "10.70.0.1/24"}):
                i = base_inst("lo", f, **raw)
                check("%s%s: the unit alike" % (f, " RAW" if raw else ""), N._wdtt_unit_text("lo", "/x/server", "/x", f) == NB._wdtt_unit_text("lo", "/x/server", "/x", f))
                check("%s%s: the env alike" % (f, " RAW" if raw else ""), N._wdtt_env_text(i) == NB._wdtt_env_text(i))
        rows9 = [{"iface": i, "fork": (r.get("fork") or "amurcanov")} for i, r in nn["x"]["wdtt"].items()]
        check("the panel's reply alike", P._wdtt_reply(roster, nn, "x", "", None, {"wdtt": rows9, "wdtt_forks": sorted(P.WDTT_BUILDS)})
              == PB._wdtt_reply(roster, nn, "x", "", None))
finally:
    with __import__("contextlib").suppress(Exception):
        stop_all()
    if PANEL["proc"]:
        PANEL["proc"].terminate()
        with __import__("contextlib").suppress(Exception): PANEL["proc"].wait(timeout=10)
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][1] if isinstance(PLANTS[MODE][1], tuple) else (PLANTS[MODE][1],)
    hit = [n for s, n in FAILS if s.startswith(secs)]
    stray = sorted({s.split(" ")[0] for s, n in FAILS if not s.startswith(secs)})
    print("\nperturb %s: %s" % (MODE, ("NOT caught by " + "/".join(secs)) if not hit
          else ("ALSO red outside its section(s): " + ", ".join(stray)) if stray else ("RED on " + "/".join(secs) + " as expected")))
    sys.exit(0 if hit and not stray else 1)
print("\n" + ("ALL PASS" if not FAILS else "%d FAIL: %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)
