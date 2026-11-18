#!/usr/bin/env python3
"""Self-test — a csqtt take-over keeps the old server's MAIN password (1.8.12 item 16, docs/RELEASE-1.8.12-PLAN.md).

The csqtt app's deploy saves the server's main password as the deploying profile's connection password, and the server
serves it beside its `passwords` rows. Our server starts with its own --password, which replaces it — so the take-over
must hand it up as one more adopted user, or the person who deployed the server is cut off (reproduced on the rig
.campaign/rigs/csqtt-adopt-main.sh, 2.5 and 2.1, 2026-11-18).

swg-noded is loaded as a module with its csqtt roots in a temp dir; the take-over runs through reconcile_csqtt with the
process walk, the stop and the install stubbed. Store schemas are the real ones, dumped from stores the 2.5.3 and
2.1.9-4 servers wrote on that rig.

  [1] 2.5 store   main password + one row → both in adopt_users (main titled, flagged), both in the set the new server
                  is installed with (the served set) and in its desired.json
  [2] 2.1 store   the same
  [3] no main     a store without one → only its rows, nothing extra
  [4] legacy      a <=2.0.1 passwords.json with a top-level main_password → handed up too
  [5] ours        a store of OUR OWN (an instance the panel starts managing without a take-over): its main password is
                  our node-made owner password — its rows are handed up, the main password never

Run: python3 tests/csqtt_adopt_main_selftest.py   (0 = pass)
     --perturb <name>  plants one regression and expects RED on its section:
                       mainread [1] [2] · legacy [4] · ours [5]
"""
import importlib.machinery, importlib.util, json, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {   # name: (sections, anchor, replacement)
    "mainread": (("[1]", "[2]"), "                if _m and str(_m[0] or \"\").strip() not in out:\n", "                if False:\n"),
    "legacy": ("[4]", "            if src is not data and str(data.get(\"main_password\") or \"\").strip() not in out:", "            if False:"),
    "ours": ("[5]", '                _pre = {k: v for k, v in _csqtt_adopted_users(_csqtt_dir(iface)).items() if not (v or {}).get("main")}\n',
             "                _pre = _csqtt_adopted_users(_csqtt_dir(iface))\n"),
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

TMP = tempfile.mkdtemp(prefix="csqtt-adopt-main-")
src = open(NODED, encoding="utf-8").read()
if MODE:
    _sec, old, new = PLANTS[MODE]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    src = src.replace(old, new)
p = os.path.join(TMP, "swg-noded"); open(p, "w", encoding="utf-8").write(src)
os.environ["SWG_NO_REEXEC"] = "1"
ld = importlib.machinery.SourceFileLoader("swgnoded_csqtt_adopt_main", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_csqtt_adopt_main", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass

META = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
PW25 = """CREATE TABLE passwords (
    password TEXT PRIMARY KEY, ip TEXT NOT NULL DEFAULT '', expires_at INTEGER NOT NULL DEFAULT 0,
    down_bytes INTEGER NOT NULL DEFAULT 0, up_bytes INTEGER NOT NULL DEFAULT 0, vk_hash TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '', is_deactivated INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
    vk_hashes TEXT NOT NULL DEFAULT '', vk_token_enabled INTEGER NOT NULL DEFAULT 0, dtls_port INTEGER NOT NULL DEFAULT 0,
    wg_port INTEGER NOT NULL DEFAULT 0, local_port INTEGER NOT NULL DEFAULT 0, group_id TEXT NOT NULL DEFAULT '',
    routing_rule_id TEXT NOT NULL DEFAULT '', sub_uuid TEXT NOT NULL DEFAULT '', workers INTEGER)"""
PW21 = """CREATE TABLE passwords (
    password TEXT PRIMARY KEY, device_id TEXT NOT NULL DEFAULT '', expires_at INTEGER NOT NULL DEFAULT 0,
    down_bytes INTEGER NOT NULL DEFAULT 0, up_bytes INTEGER NOT NULL DEFAULT 0, vk_hash TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '', is_deactivated INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '',
    vk_hashes TEXT NOT NULL DEFAULT '', dtls_port INTEGER NOT NULL DEFAULT 0, wg_port INTEGER NOT NULL DEFAULT 0,
    local_port INTEGER NOT NULL DEFAULT 0)"""
MAIN, ROW = "MAINdeployPw0001", "ROWuserPw0000001"

def store(d, schema, main=True, meta_extra=()):
    os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(os.path.join(d, "csqtt.db"))
    c.execute(META); c.execute(schema)
    c.execute("INSERT INTO meta VALUES ('dns', '77.88.8.8')")
    if main:
        c.execute("INSERT INTO meta VALUES ('main_password', ?)", (MAIN,))
    for k, v in meta_extra:
        c.execute("INSERT INTO meta VALUES (?, ?)", (k, v))
    c.execute("INSERT INTO passwords (password, vk_hash, name) VALUES (?, 'vk1', 'alice')", (ROW,))
    c.commit(); c.close()
    return d

# ── the sandbox ────────────────────────────────────────────────────────────────────────────────────────────────
N.NODE_KIND = "baremetal"
os.makedirs(os.path.join(TMP, "units")); N.turn_unit_dir = lambda: os.path.join(TMP, "units")
N.CSQTT_ROOT = os.path.join(TMP, "opt"); N.CSQTT_RECORD = os.path.join(TMP, "csqtt.json")
N._csqtt_procs = lambda *a, **k: []
N._csqtt_scan_ok = lambda: True
N._csqtt_foreign_pid = lambda *a, **k: None
N._csqtt_stop_foreign = lambda iface, src: (True, "")
INSTALLED = []
def _install(inst):
    INSTALLED.append(json.loads(json.dumps(inst)))
    d = N._csqtt_dir(inst["iface"]); os.makedirs(d, exist_ok=True)
    open(d + "/desired.json", "w").write(N._csqtt_desired_body(inst) + "\n")
    return ""
N._csqtt_install = _install
N._csqtt_present = lambda iface: os.path.isfile(N._csqtt_dir(iface) + "/desired.json")
N.host_sh = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

def take_over(iface, src, line):
    del INSTALLED[:]
    with open(N.CSQTT_RECORD, "w") as f: json.dump({}, f)
    shutil.rmtree(N._csqtt_dir(iface), ignore_errors=True)
    r = N.reconcile_csqtt({iface: {"listen": "0.0.0.0:46000", "tun_addr": "10.66.70.1/24", "line": line, "passwords": {},
                                   "adopt_foreign": True, "adopt_config_dir": src}})
    rec = N._csqtt_load().get(iface) or {}
    served = set((INSTALLED[-1].get("passwords") or {}) if INSTALLED else ())
    try:
        body = json.loads(open(N._csqtt_dir(iface) + "/desired.json").read())
        desired = {e.get("password") for e in (body.get("passwords") if isinstance(body, dict) else body) or []}
    except Exception:
        desired = set()
    return r, rec.get("adopt_users") or {}, served, desired

try:
    for sec, schema, line in (("[1] 2.5 store", PW25, "2.5"), ("[2] 2.1 store", PW21, "2.1")):
        section(sec)
        src = store(os.path.join(TMP, "etc-" + line), schema, meta_extra=(("main_device_id", "dev0"),) if line == "2.1" else ())
        r, au, served, desired = take_over("csqtt1", src, line)
        check("no error", not r["errors"], r["errors"])
        check("the main password is in adopt_users", MAIN in au, sorted(k[:4] for k in au))
        check("…titled for the operator", (au.get(MAIN) or {}).get("comment") == N.CSQTT_MAIN_COMMENT, (au.get(MAIN) or {}).get("comment"))
        check("…and its row too", ROW in au and (au.get(ROW) or {}).get("comment") == "alice")
        check("the new server is installed serving both", MAIN in served and ROW in served, sorted(x[:4] for x in served))
        check("…its desired.json holds both", MAIN in desired and ROW in desired, sorted((x or "")[:4] for x in desired))
        check("the owner password stays node-made", (N._csqtt_load().get("csqtt1") or {}).get("password") not in ("", MAIN, None))

    section("[3] a store without a main password")
    src = store(os.path.join(TMP, "etc-nomain"), PW25, main=False)
    r, au, served, desired = take_over("csqtt1", src, "2.5")
    check("only its row is handed up", set(au) == {ROW}, sorted(k[:4] for k in au))
    check("…and served", served == {ROW}, sorted(x[:4] for x in served))

    section("[4] a <=2.0.1 passwords.json")
    d = os.path.join(TMP, "etc-legacy"); os.makedirs(d)
    json.dump({"main_password": MAIN, "passwords": {ROW: {"name": "alice", "vk_hash": "vk1"}}}, open(d + "/passwords.json", "w"))
    r, au, served, desired = take_over("csqtt1", d, "2.1")
    check("main and row handed up", MAIN in au and ROW in au, sorted(k[:4] for k in au))
    check("…main titled", (au.get(MAIN) or {}).get("comment") == N.CSQTT_MAIN_COMMENT)
    d2 = os.path.join(TMP, "etc-legacy-flat"); os.makedirs(d2)
    json.dump({ROW: {"name": "alice"}}, open(d2 + "/passwords.json", "w"))
    r, au, served, desired = take_over("csqtt1", d2, "2.1")
    check("a flat password map: its row only", set(au) == {ROW}, sorted(k[:4] for k in au))

    section("[5] a store of our own")
    with open(N.CSQTT_RECORD, "w") as f: json.dump({}, f)
    own = N._csqtt_dir("csqtt2"); store(own, PW25)
    open(own + "/desired.json", "w").write('{"passwords": []}\n')
    N.reconcile_csqtt({"csqtt2": {"listen": "0.0.0.0:46001", "tun_addr": "10.66.71.1/24", "line": "2.5", "passwords": {}}})
    au = (N._csqtt_load().get("csqtt2") or {}).get("adopt_users") or {}
    check("its rows are handed up", ROW in au, sorted(k[:4] for k in au))
    check("its main password (our owner password) is not", MAIN not in au, sorted(k[:4] for k in au))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][0]; secs = (secs,) if isinstance(secs, str) else secs
    hit = [s for s, _ in FAILS if s.split()[0] in secs]
    print("PLANT %s: %s" % (MODE, "RED as expected" if hit else "NOT CAUGHT"))
    sys.exit(0 if hit else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
