#!/usr/bin/env python3
"""Self-test — csqtt version LINES, the node's half (docs/CSQTT-LINES-PLAN.md §4.2, gates G3–G8).

swg-noded is loaded as a module with its csqtt roots in a temp dir and run in its docker shape, where a server is a
supervised CHILD PROCESS — so a "binary" here is a shell script that really runs, really dies, and really writes the
store. Nothing reaches systemd, the network or a real TUN: the one interface the stable-verify needs to see is `lo`,
and every command that could delete a link is refused by a guard (the test fails rather than touch it).

  [1] slots      2.1 keeps the path every node already has; another line gets its own dir; a line is a path
                 component, so "../x" and an unknown line are refused
  [2] switch     2.1 → 2.5 repoints only this server's symlink, copies 2.1's store first, and leaves a sibling
                 server on 2.1 running untouched (same pid)          (G3)
  [3] revert     a 2.5 build that writes the store and dies 2 s after starting passes today's _csqtt_verify — the
                 stable verify catches it, the server is back on 2.1 with 2.1's store, and the result is memoed (G4)
  [4] rollback   a switch a noded crash cut (its `.switching` marker left) is ROLLED BACK onto 2.1's store copy —
                 never resumed — and the still-wanted switch runs again, whole, on the next pass (G8)
  [5] reconfigure a param change on a 2.5 server relinks the 2.5 slot, not 2.1's (G6)
  [6] absent     a request with no `line` keeps a 2.5 server on 2.5 and does not apply a 2.1 `ver` to it (G7)
  [7] memo       a switch that would not run is not retried every sync; the operator's Restart retries it, and a
                 request back to the running line clears it
  [8] build      a build update on 2.5 restarts only the 2.5 servers (G5)
  [9] sibling    a switch that brings a NEW build into the 2.5 slot restarts the server already on 2.5 onto it — a
                 stamp saying "current" over an old inode would leave it on the old build for good
  [10] copyfail  a store copy that fails (a full disk) never leaves the server stopped: it runs on 2.1 again, the
                 failure is memoed
  code review (2026-10-08):
  [11] markorder a cut switch the panel wants undone lands on 2.1's store copy; a crash INSIDE the copy leaves no
                 marker (copy, then mark, then relink), so no pass ever rolls back onto an older copy
  [12] onepass   two servers asking for a switch in one pass: one switches, the other waits a sync
  [13] restart   a Restart that retries a failed switch restarts the server once, not twice
  [14] curver    while a switch is memoed, the line the server RUNS still takes the panel's `cur_ver`
  [15] nover     a versionless fetch never lands in another line's slot (it would be 2.1's build)
  [16] ifaces    a server not installed yet is not "running" any line, so a build swap does not restart it
  review of the fixes (2026-10-08):
  [17] fetchswitched  a switch whose fetch failed restarted nothing: Restart still restarts, cur_ver still applies
  [18] unknowncur     a request for a line this node does not know keeps the running line's cur_ver
  [19] runver         while a switch waits, the record's ver is the running line's build (what a self-heal fetches)
  [20] notpresent     a server whose unit or binary is gone: a memoed switch re-installs what ran with its build; a cut
                      switch rolls the store back to its copy and re-installs the line it was leaving
  [21] snapcut        the snapshot reports a cut switch's marker line, the same line the reconcile treats as running
  [12] also: a switch whose fetch failed spends the pass budget (budget)

Run: python3 tests/csqtt_lines_node_selftest.py   (0 = pass)
     --perturb <name>  plants one regression and expects RED on its section:
                       reconfigure [5] · absent [6] · stable [3] · rollback [4] · memo [7] · build [8] · sibling [9] ·
                       copyfail [10] · markorder [11] · onepass [12] · restart [13] · curver [14] · nover [15] · ifaces [16] · fetchswitched [17] · unknowncur [18] · runver [19] · budget [12] ·
                       notpresent-ver / notpresent-cut [20] · snapcut [21]
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {   # name: (section, anchor, replacement)
    "reconfigure": ("[5]", "    line = _csqtt_line_of(inst)\n    binshared = _csqtt_bin_shared(line)\n    if not os.path.exists(binshared):        # same-arch",
                    "    line = _csqtt_line_of(inst)\n    binshared = _csqtt_bin_shared()\n    if not os.path.exists(binshared):        # same-arch"),
    "absent": ("[6]", "            if not _line:\n                _line = _cur\n", "            if not _line:\n                _line = CSQTT_DEFAULT_LINE\n"),
    "stable": (("[3]", "[11]"), "    err = _csqtt_start_one(dict(inst, line=to)) or _csqtt_verify_stable(iface)\n",
               "    err = _csqtt_start_one(dict(inst, line=to)) or _csqtt_verify(iface)\n"),
    "rollback": (("[4]", "[11]"), "                if _cut:\n                    # A switch away from", "                if False:\n                    # A switch away from"),
    "memo": (("[7]", "[14]", "[19]", "[20]"), "                inst[\"line_failed\"] = _lf\n", "                pass\n"),
    "sibling": ("[9]", "        others = [i for i in siblings if i != iface]\n", "        others = []\n"),
    "copyfail": ("[10]", "        _csqtt_start_one(dict(inst, line=frm)) if not inst.get(\"stopped\") else None\n", "        pass\n"),
    "markorder": ("[11]", "        _csqtt_store_copy(cfgdir, frm)\n        _csqtt_cut_mark(iface, frm)\n", "        _csqtt_cut_mark(iface, frm)\n        _csqtt_store_copy(cfgdir, frm)\n"),
    "fetchswitched": ("[17]", "                    _switched = (not err) or _memo", "                    _switched = True"),
    "unknowncur": ("[18]", "                inst[\"ver\"] = (inst.get(\"cur_ver\") or \"\").strip()   # the panel's build for what runs, or none", "                inst.pop(\"ver\", None)"),
    "budget": ("[12]", "                    _sw_pass[0] = True\n                    _switched = (not err) or _memo", "                    _sw_pass[0] = _switched = (not err) or _memo"),
    "notpresent-ver": ("[20]", "                if inst[\"line\"] != _line:\n                    inst[\"ver\"] = (inst.get(\"cur_ver\") or \"\").strip()   # installing what ran", "                if False:\n                    inst[\"ver\"] = (inst.get(\"cur_ver\") or \"\").strip()   # installing what ran"),
    "notpresent-cut": ("[20]", "                    _csqtt_store_restore(_csqtt_dir(iface), _cut)\n                    _csqtt_cut_clear(iface)\n                elif", "                    _csqtt_cut_clear(iface)\n                elif"),
    "snapcut": ("[21]", "        _rl = _csqtt_cut_line(iface) or _csqtt_running_line(iface)", "        _rl = _csqtt_running_line(iface)"),
    "runver": ("[19]", "                if inst.get(\"line\") == _cur:\n", "                if False:\n"),
    "onepass": ("[12]", "                elif _line != _cur and not inst.get(\"line_failed\") and _sw_pass[0]:", "                elif False:"),
    "restart": ("[13]", "and not inst.get(\"stopped\") and not _switched:\n                if NODE_KIND == \"docker\":\n                    _csqtt_docker_start(inst)", "and not inst.get(\"stopped\"):\n                if NODE_KIND == \"docker\":\n                    _csqtt_docker_start(inst)"),
    "curver": (("[14]", "[17]", "[19]"), "                _run_ver = _want_ver if _line == _cur else (inst.get(\"cur_ver\") or \"\").strip()", "                _run_ver = _want_ver if _line == _cur else \"\""),
    "nover": ("[15]", "    if not ver and line != CSQTT_DEFAULT_LINE:\n", "    if False:\n"),
    "ifaces": ("[16]", "    return [i for i in (want or {}) if _csqtt_running_line(i) == line]", "    return [i for i, r in (want or {}).items() if (_csqtt_running_line(i) or _csqtt_line_of(r)) == line]"),
    "build": (("[8]", "[16]"), "    return [i for i in (want or {}) if _csqtt_running_line(i) == line]", "    return list(want or {})"),   # one function, two sections
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

TMP = tempfile.mkdtemp(prefix="csqtt-lines-node-")
src = open(NODED, encoding="utf-8").read()
if MODE:
    _sec, old, new = PLANTS[MODE]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    src = src.replace(old, new)
p = os.path.join(TMP, "swg-noded"); open(p, "w", encoding="utf-8").write(src)
os.environ["SWG_NO_REEXEC"] = "1"
ld = importlib.machinery.SourceFileLoader("swgnoded_csqtt_lines", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_csqtt_lines", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass

# ── the sandbox ────────────────────────────────────────────────────────────────────────────────────────────────
N.NODE_KIND = "docker"
N.CSQTT_ROOT = os.path.join(TMP, "csqtt"); N.CSQTT_BIN_DIR = N.CSQTT_ROOT + "/.bin"
N.CSQTT_RECORD = os.path.join(TMP, "csqtt.json")
N._turn_arch = lambda: "amd64"
N._csqtt_clear_stale_tun = lambda iface: None
N._csqtt_argv = lambda inst, binp: [binp, N._csqtt_dir(inst["iface"])]
N._csqtt_adopted_users = lambda *a, **k: {}
N._csqtt_env_drifted = lambda *a, **k: False
N.bind_heal_due = lambda *a, **k: False
def _guard(cmd, *a, **k):
    if "link" in str(cmd) and "del" in str(cmd):
        raise AssertionError("the test reached a link delete: " + str(cmd))
    class R: returncode, stdout, stderr = 0, "", ""
    return R()
N.host_sh = _guard
GOOD = "#!/bin/sh\ntrap '' HUP\nexec sleep 300\n"   # a real csqtt reloads desired.json on SIGHUP — it does not die of it
DIES = "#!/bin/sh\necho MIGRATED-BY-2.5 > \"$1/csqtt.db\"\nsleep 2\nexit 1\n"
BUILD = {"2.1": GOOD, "2.5": GOOD}
FETCHES = []
def fake_fetch(inst, dest, line="2.1"):
    FETCHES.append((line, inst.get("ver")))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w").write(BUILD[line]); os.chmod(dest, 0o755)
    N._csqtt_write_ver(inst.get("ver") or "", line)
    return ""
REAL_FETCH = N._csqtt_fetch_bin
N._csqtt_fetch_bin = fake_fetch

def lay(iface, line, store="A"):
    """A running instance of ours on `line`, its store holding `store`."""
    d = N._csqtt_dir(iface); os.makedirs(d, exist_ok=True)
    slot = N._csqtt_bin_shared(line)
    if not os.path.exists(slot):
        fake_fetch({"ver": "v" + line}, slot, line)
    N._csqtt_relink(d + "/server", slot)
    open(d + "/csqtt.db", "w").write(store + "\n")
    inst = {"iface": iface, "listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "line": line, "panel_managed": True,
            "pw_seen": True, "passwords": {"pw1": {}}, "password": "owner", "web_pass": "w"}
    N._csqtt_docker_start(inst)
    return inst
def db(iface):
    return open(N._csqtt_dir(iface) + "/csqtt.db").read().strip()
def bak(iface, line):
    f = N._csqtt_store_bak(N._csqtt_dir(iface), line) + "/csqtt.db"
    return open(f).read().strip() if os.path.exists(f) else None
def pid(iface):
    return N._csqtt_docker_pid(iface)

try:
    section("[1] slots")
    a = N._csqtt_bin_shared("2.1"); b = N._csqtt_bin_shared("2.5")
    check("2.1 keeps the legacy path .bin/<arch>/csqtt-server", a == N.CSQTT_BIN_DIR + "/amd64/csqtt-server", a)
    check("2.5 gets .bin/<arch>/2.5/csqtt-server", b == N.CSQTT_BIN_DIR + "/amd64/2.5/csqtt-server", b)
    check("a line that is not a dotted version is refused", not N._csqtt_line_ok("../x") and not N._csqtt_line_ok("2.5/..") and not N._csqtt_line_ok(""))
    check("a well-formed line this node does not know is refused", not N._csqtt_line_ok("9.9"))
    check("an absent line reads as 2.1", N._csqtt_line_of({}) == "2.1" and N._csqtt_line_of({"line": "../x"}) == "2.1")

    section("[2] switch 2.1 → 2.5")
    inst = lay("lo", "2.1", "A")
    sib = lay("csqttsib", "2.1", "S")
    sib_pid = pid("csqttsib")
    err, memo = N._csqtt_switch_line(dict(inst), "2.1", "2.5", "2.1.9-3")
    check("the switch reports success", err == "" and memo is False, err)
    check("this server now runs the 2.5 slot", N._csqtt_running_line("lo") == "2.5", os.readlink(N._csqtt_dir("lo") + "/server"))
    check("2.5's slot is stamped with the build the panel named", N._csqtt_installed_ver("2.5") == "2.1.9-3", N._csqtt_installed_ver("2.5"))
    check("2.1's store was copied before the repoint", bak("lo", "2.1") == "A", bak("lo", "2.1"))
    check("the sibling server on 2.1 still runs, same pid", pid("csqttsib") == sib_pid and sib_pid, (sib_pid, pid("csqttsib")))
    check("the sibling still points at 2.1", N._csqtt_running_line("csqttsib") == "2.1")

    section("[3] revert — a 2.5 that writes the store and dies 2 s in")
    N._csqtt_docker_stop("lo")
    inst = lay("lo", "2.1", "A")
    shutil.rmtree(os.path.dirname(N._csqtt_bin_shared("2.5")), ignore_errors=True)
    BUILD["2.5"] = DIES
    t0 = time.time()
    err, memo = N._csqtt_switch_line(dict(inst), "2.1", "2.5", "2.5.0-1")
    check("the switch fails and says it is memoed", bool(err) and memo is True, (err, memo))
    check("…and names an exit, not a timeout", "exited" in err or "did not stay up" in err, err)
    check("the server is back on the 2.1 slot", N._csqtt_running_line("lo") == "2.1")
    check("2.1's store is back — not the one 2.5 wrote", db("lo") == "A", db("lo"))
    check("the server runs again on 2.1", bool(pid("lo")))
    check("the sibling was never touched", pid("csqttsib") == sib_pid)
    BUILD["2.5"] = GOOD

    section("[4] a switch a crash cut is rolled back, then runs again whole")
    N._csqtt_docker_stop("lo")
    inst = lay("lo", "2.1", "A")
    json.dump({"lo": dict(inst)}, open(N.CSQTT_RECORD, "w"))
    fake_fetch({"ver": "2.1.9-3"}, N._csqtt_bin_shared("2.5"), "2.5")
    N._csqtt_store_copy(N._csqtt_dir("lo"), "2.1"); N._csqtt_cut_mark("lo", "2.1")   # the cut pass: copy, mark, relink —
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.5"))      # — then 2.5 ran and rewrote the store
    open(N._csqtt_dir("lo") + "/csqtt.db", "w").write("MIGRATED-BY-2.5\n")
    w4 = {"lo": {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "passwords": {"pw1": {}}, "line": "2.5", "ver": "2.1.9-3"}}
    N.reconcile_csqtt(w4)
    check("the cut switch is rolled back to 2.1", N._csqtt_running_line("lo") == "2.1", os.readlink(N._csqtt_dir("lo") + "/server"))
    check("…onto 2.1's own store copy, not the one 2.5 rewrote", db("lo") == "A", db("lo"))
    check("…the marker is gone and the server runs", not os.path.exists(N._csqtt_cut_path("lo")) and bool(pid("lo")),
          (os.path.exists(N._csqtt_cut_path("lo")), pid("lo"), (N._csqtt_load().get("lo") or {}).get("stopped")))
    N.reconcile_csqtt(w4)
    check("the next pass runs the still-wanted switch, whole", N._csqtt_running_line("lo") == "2.5" and not os.path.exists(N._csqtt_cut_path("lo")),
          os.readlink(N._csqtt_dir("lo") + "/server"))
    check("…with a fresh copy of 2.1's store behind it", bak("lo", "2.1") == "A", bak("lo", "2.1"))

    section("[5] reconfigure keeps the line")
    i25 = dict(inst, line="2.5", params="--x")
    N._csqtt_reconfigure(i25)
    check("the symlink still points at the 2.5 slot", N._csqtt_running_line("lo") == "2.5", os.readlink(N._csqtt_dir("lo") + "/server"))

    section("[9] a new build in the slot reaches the server already on it")
    N._csqtt_docker_stop("lo"); N._csqtt_docker_stop("csqttsib")
    shutil.rmtree(os.path.dirname(N._csqtt_bin_shared("2.5")), ignore_errors=True)
    sib25 = lay("csqttsib", "2.5", "S")                      # on 2.5, build "v2.5"
    inst = lay("lo", "2.1", "A")
    json.dump({"lo": dict(inst), "csqttsib": dict(sib25)}, open(N.CSQTT_RECORD, "w"))
    p_before = pid("csqttsib")
    err, memo = N._csqtt_switch_line(dict(inst), "2.1", "2.5", "2.5.0-9", ["csqttsib", "lo"])
    check("the switch succeeds", err == "", err)
    check("the slot carries the new build", N._csqtt_installed_ver("2.5") == "2.5.0-9", N._csqtt_installed_ver("2.5"))
    check("the server already on 2.5 was restarted onto it", pid("csqttsib") and pid("csqttsib") != p_before, (p_before, pid("csqttsib")))

    section("[10] a store copy that fails")
    N._csqtt_docker_stop("lo")
    inst = lay("lo", "2.1", "A")
    real_copy = N._csqtt_store_copy
    def boom(*a): raise OSError(28, "No space left on device")
    N._csqtt_store_copy = boom
    err, memo = N._csqtt_switch_line(dict(inst), "2.1", "2.5", "2.5.0-9")
    N._csqtt_store_copy = real_copy
    check("it reports the copy and memoes it", "copy the store" in err and memo is True, (err, memo))
    check("the server is still on 2.1", N._csqtt_running_line("lo") == "2.1")
    check("…and running, not left stopped", bool(pid("lo")))

    # ── the reconcile ─────────────────────────────────────────────────────────────────────────────────────────
    SWITCHES, UPDATES = [], []
    real_switch, real_update = N._csqtt_switch_line, N._csqtt_update_binary
    def rec_switch(inst, frm, to, ver, siblings=(), stopped=()):
        SWITCHES.append((inst["iface"], frm, to, ver)); return SWITCH_RESULT[0]
    def rec_update(inst, ver, ifaces, line="2.1"):
        UPDATES.append((ver, tuple(sorted(ifaces)), line)); N._csqtt_write_ver(ver, line); return ""
    N._csqtt_switch_line = rec_switch; N._csqtt_update_binary = rec_update
    SWITCH_RESULT = [("", False)]
    def record(**insts):
        json.dump(insts, open(N.CSQTT_RECORD, "w"))
    def want(iface, **kw):
        base = {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "passwords": {"pw1": {}}}
        base.update(kw); return base
    rec_lo = dict(inst, line="2.5")
    rec_lo.pop("params", None)

    section("[6] a request with no line")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.5"))   # committed AND running 2.5
    record(lo=rec_lo)
    N._csqtt_write_ver("2.1.9-3", "2.5")
    del SWITCHES[:], UPDATES[:]
    N.reconcile_csqtt({"lo": want("lo", ver="2.1.9-4")})
    check("no switch is attempted", SWITCHES == [], SWITCHES)
    check("the 2.1 ver is not applied to the 2.5 server", UPDATES == [], UPDATES)
    check("the record keeps line 2.5", (N._csqtt_load().get("lo") or {}).get("line") == "2.5", N._csqtt_load().get("lo"))

    section("[7] a failed switch is memoed")
    rec21 = dict(rec_lo, line="2.1"); N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.1"))
    record(lo=rec21)
    SWITCH_RESULT[0] = ("the server exited", True)
    del SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-1")})
    r1 = N._csqtt_load().get("lo") or {}
    check("the first sync tries the switch", len(SWITCHES) == 1, SWITCHES)
    check("…records line_failed and stays committed on 2.1", (r1.get("line_failed") or {}).get("line") == "2.5" and r1.get("line") == "2.1", r1)
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-1")})
    check("the next sync does not retry the same build", len(SWITCHES) == 1, SWITCHES)
    snaprow = next((c for c in N.csqtt_snapshot() if c.get("iface") == "lo"), {})
    check("the snapshot reports what runs (2.1) and why the switch failed", snaprow.get("line") == "2.1" and (snaprow.get("line_failed") or {}).get("line") == "2.5", snaprow)
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2")})
    check("a new build is tried", len(SWITCHES) == 2, SWITCHES)
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", restart=12345)})
    check("the operator's Restart retries the same build", len(SWITCHES) == 3, SWITCHES)
    N.reconcile_csqtt({"lo": want("lo", line="2.1", ver="2.1.9-4", restart=12345)})
    check("a request back to the running line clears line_failed", not (N._csqtt_load().get("lo") or {}).get("line_failed"), N._csqtt_load().get("lo"))
    SWITCH_RESULT[0] = ("", False)
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", restart=12345)})
    check("a switch that works commits line 2.5", (N._csqtt_load().get("lo") or {}).get("line") == "2.5", N._csqtt_load().get("lo"))

    section("[8] a build update stays inside its line")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.5"))
    N._csqtt_relink(N._csqtt_dir("csqttsib") + "/server", N._csqtt_bin_shared("2.1"))
    record(lo=dict(rec_lo, line="2.5"), csqttsib=dict(sib, line="2.1"))
    N._csqtt_write_ver("2.5.0-1", "2.5"); N._csqtt_write_ver("2.1.9-4", "2.1")
    del UPDATES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2"), "csqttsib": want("csqttsib", line="2.1", ver="2.1.9-4", tun_addr="10.66.68.1/24")})
    check("one update, on line 2.5, restarting only the 2.5 server", UPDATES == [("2.5.0-2", ("lo",), "2.5")], UPDATES)

    section("[11] a cut switch the panel now wants undone; the marker always has a fresh copy behind it")
    N._csqtt_switch_line, N._csqtt_update_binary = real_switch, real_update
    N._csqtt_docker_stop("lo")
    BUILD["2.5"] = GOOD
    lay("lo", "2.1", "A")
    N._csqtt_store_copy(N._csqtt_dir("lo"), "2.1"); N._csqtt_cut_mark("lo", "2.1")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.5"))
    open(N._csqtt_dir("lo") + "/csqtt.db", "w").write("MIGRATED-BY-2.5\n")
    record(lo=dict(rec_lo, line="2.1"))
    N.reconcile_csqtt({"lo": want("lo", line="2.1", ver="2.1.9-4")})
    r11 = N._csqtt_load().get("lo") or {}
    check("asked for 2.1: back on 2.1, on 2.1's store copy", N._csqtt_running_line("lo") == "2.1" and db("lo") == "A", (os.readlink(N._csqtt_dir("lo") + "/server"), db("lo")))
    check("…committed 2.1, nothing memoed, running", r11.get("line") == "2.1" and not r11.get("line_failed") and bool(pid("lo")), r11)
    # a crash INSIDE the copy: no marker may exist yet, or the next pass would roll back onto an older copy
    N._csqtt_docker_stop("lo")
    inst11 = lay("lo", "2.1", "STALE"); N._csqtt_store_copy(N._csqtt_dir("lo"), "2.1")   # an old copy from some earlier switch
    open(N._csqtt_dir("lo") + "/csqtt.db", "w").write("LIVE\n")
    class Crash(BaseException):
        pass
    real_copy = N._csqtt_store_copy
    def crash_copy(*a): raise Crash()
    N._csqtt_store_copy = crash_copy
    try:
        N._csqtt_switch_line(dict(inst11), "2.1", "2.5", "2.1.9-3")
    except Crash:
        pass
    N._csqtt_store_copy = real_copy
    record(lo=dict(rec_lo, line="2.1"))
    N.reconcile_csqtt({"lo": want("lo", line="2.1", ver="2.1.9-4")})
    check("a crash inside the copy leaves no marker — the live store is untouched", db("lo") == "LIVE", db("lo"))
    N._csqtt_switch_line, N._csqtt_update_binary = rec_switch, rec_update

    section("[12] one switch per pass")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.1"))
    N._csqtt_relink(N._csqtt_dir("csqttsib") + "/server", N._csqtt_bin_shared("2.1"))
    record(lo=dict(rec_lo, line="2.1"), csqttsib=dict(sib, line="2.1"))
    SWITCH_RESULT[0] = ("", False)
    del SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2"), "csqttsib": want("csqttsib", line="2.5", ver="2.5.0-2", tun_addr="10.66.68.1/24")})
    check("two asked, one switched this pass", [x[0] for x in SWITCHES] == ["lo"], SWITCHES)
    r12 = N._csqtt_load().get("csqttsib") or {}
    check("the one that waits keeps 2.1, with no failure memoed", r12.get("line") == "2.1" and not r12.get("line_failed"), r12)
    del SWITCHES[:]
    N.reconcile_csqtt({"csqttsib": want("csqttsib", line="2.5", ver="2.5.0-2", tun_addr="10.66.68.1/24")})
    check("…and switches on the next pass", [x[0] for x in SWITCHES] == ["csqttsib"], SWITCHES)
    record(lo=dict(rec_lo, line="2.1"), csqttsib=dict(sib, line="2.1"))
    SWITCH_RESULT[0] = ("the panel's mirror had no build", False)
    del SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2"), "csqttsib": want("csqttsib", line="2.5", ver="2.5.0-2", tun_addr="10.66.68.1/24")})
    check("a switch whose fetch failed spends the pass too (one fetch walk per pass)", len(SWITCHES) == 1, SWITCHES)
    SWITCH_RESULT[0] = ("", False)

    section("[13] a Restart that retries a failed switch restarts once")
    N._csqtt_docker_stop("lo"); lay("lo", "2.1", "A")       # alive, so supervision has nothing to relaunch
    STARTS = []
    real_start = N._csqtt_docker_start
    N._csqtt_docker_start = lambda inst: (STARTS.append(inst.get("iface")), real_start(inst))[1]
    record(lo=dict(rec_lo, line="2.1", restart=1, line_failed={"line": "2.5", "ver": "2.5.0-2", "why": "x"}))
    SWITCH_RESULT[0] = ("", False)
    del SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", restart=2)})
    N._csqtt_docker_start = real_start
    check("the switch was retried", len(SWITCHES) == 1, SWITCHES)
    check("…and the restart stamp did not restart it a second time", STARTS.count("lo") == 0, STARTS)

    section("[14] cur_ver while a switch is memoed")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.1"))
    N._csqtt_write_ver("2.1.9-3", "2.1")
    record(lo=dict(rec_lo, line="2.1", line_failed={"line": "2.5", "ver": "2.5.0-2", "why": "x"}))
    del UPDATES[:], SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", cur_ver="2.1.9-4")})
    check("no switch (memoed)", SWITCHES == [], SWITCHES)
    check("the 2.1 line it runs takes cur_ver", UPDATES == [("2.1.9-4", ("lo",), "2.1")], UPDATES)

    section("[15] a versionless fetch into another line's slot")
    N._turn_arch_ok = lambda: True
    real_pf = N._csqtt_panel_fetch
    N._csqtt_panel_fetch = lambda dest, sha, tag="csqtt": (open(dest, "w").write("2.1.9-4 binary"), True)[1]   # a mirror that serves its "csqtt" (2.1) build
    e15 = REAL_FETCH({"ver": ""}, N._csqtt_bin_shared("2.5") + ".probe", "2.5")
    N._csqtt_panel_fetch = real_pf
    check("refused, naming the line", "named no csqtt 2.5" in (e15 or ""), e15)
    check("…and the mirror's 2.1 build did not land in the 2.5 slot", not os.path.exists(N._csqtt_bin_shared("2.5") + ".probe"))

    section("[17] a switch whose fetch fails restarted nothing")
    N._csqtt_docker_stop("lo"); lay("lo", "2.1", "A"); N._csqtt_write_ver("2.1.9-3", "2.1")
    record(lo=dict(rec_lo, line="2.1", restart=1))
    STARTS = []
    real_start = N._csqtt_docker_start
    N._csqtt_docker_start = lambda inst: (STARTS.append(inst.get("iface")), real_start(inst))[1]
    SWITCH_RESULT[0] = ("the panel's mirror had no build", False)
    del UPDATES[:], SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", cur_ver="2.1.9-4", restart=2)})
    N._csqtt_docker_start = real_start
    check("the switch was tried", len(SWITCHES) == 1, SWITCHES)
    check("…so the operator's Restart still restarts it", STARTS.count("lo") == 1, STARTS)
    check("…and the 2.1 it runs still takes cur_ver", UPDATES == [("2.1.9-4", ("lo",), "2.1")], UPDATES)
    SWITCH_RESULT[0] = ("", False)

    section("[18] a line the node does not know keeps cur_ver for what runs")
    N._csqtt_write_ver("2.1.9-3", "2.1")
    record(lo=dict(rec_lo, line="2.1"))
    del UPDATES[:], SWITCHES[:]
    N.reconcile_csqtt({"lo": want("lo", line="2.6", ver="2.6.0-1", cur_ver="2.1.9-4")})
    check("no switch", SWITCHES == [], SWITCHES)
    check("the 2.1 it runs takes cur_ver", UPDATES == [("2.1.9-4", ("lo",), "2.1")], UPDATES)

    section("[19] while a switch waits, the record names the RUNNING line's build")
    record(lo=dict(rec_lo, line="2.1", line_failed={"line": "2.5", "ver": "2.5.0-2", "why": "x"}))
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", cur_ver="2.1.9-4")})
    r19 = N._csqtt_load().get("lo") or {}
    check("its ver is 2.1's build (a self-heal fetch into the 2.1 slot names it)", r19.get("ver") == "2.1.9-4" and r19.get("line") == "2.1", r19)

    section("[20] a server whose unit or binary is gone")
    INSTALLS = []
    real_install = N._csqtt_install
    N._csqtt_install = lambda inst: (INSTALLS.append((inst.get("line"), inst.get("ver"))), "")[1]
    N._csqtt_docker_stop("lo")
    os.remove(N._csqtt_dir("lo") + "/server")                                   # not present
    record(lo=dict(rec_lo, line="2.1", line_failed={"line": "2.5", "ver": "2.5.0-2", "why": "x"}))
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2", cur_ver="2.1.9-4")})
    check("a memoed switch: re-installs what ran (2.1) with ITS build, not the asked 2.5 build", INSTALLS[-1:] == [("2.1", "2.1.9-4")], INSTALLS)
    os.makedirs(N._csqtt_dir("lo"), exist_ok=True)
    open(N._csqtt_dir("lo") + "/csqtt.db", "w").write("A\n"); N._csqtt_store_copy(N._csqtt_dir("lo"), "2.1")
    N._csqtt_cut_mark("lo", "2.1"); open(N._csqtt_dir("lo") + "/csqtt.db", "w").write("MIGRATED-BY-2.5\n")
    record(lo=dict(rec_lo, line="2.5"))
    N.reconcile_csqtt({"lo": want("lo", line="2.5", ver="2.5.0-2")})
    check("a cut switch: the store is rolled back to 2.1's copy all the same", db("lo") == "A", db("lo"))
    check("…the marker is gone and it re-installs the line it was leaving", not os.path.exists(N._csqtt_cut_path("lo")) and INSTALLS[-1][0] == "2.1", INSTALLS)
    N._csqtt_install = real_install

    section("[21] the snapshot during a cut switch")
    lay("lo", "2.1", "A")
    N._csqtt_relink(N._csqtt_dir("lo") + "/server", N._csqtt_bin_shared("2.5")); N._csqtt_cut_mark("lo", "2.1")
    row = next((c for c in N.csqtt_snapshot() if c.get("iface") == "lo"), {})
    check("it reports the line being rolled back to (2.1), as the reconcile does", row.get("line") == "2.1", row.get("line"))
    N._csqtt_cut_clear("lo")

    section("[16] a server not installed yet runs no line")
    check("_csqtt_ifaces leaves it out", N._csqtt_ifaces({"csqttnew": {"line": "2.5"}}, "2.5") == [], N._csqtt_ifaces({"csqttnew": {"line": "2.5"}}, "2.5"))
finally:
    for i in ("lo", "csqttsib"):
        try: N._csqtt_docker_stop(i)
        except Exception: pass
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][0] if isinstance(PLANTS[MODE][0], tuple) else (PLANTS[MODE][0],)
    hit = [n for s, n in FAILS if s.startswith(secs)]
    stray = sorted({s.split(" ")[0] for s, n in FAILS if not s.startswith(secs)})
    print("\nperturb %s: %s" % (MODE, ("NOT caught by " + "/".join(secs)) if not hit
          else ("ALSO red outside its section(s): " + ", ".join(stray)) if stray else ("RED on " + "/".join(secs) + " as expected")))
    sys.exit(0 if hit and not stray else 1)
print("\n" + ("ALL PASS" if not FAILS else "%d FAIL: %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)
