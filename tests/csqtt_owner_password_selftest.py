#!/usr/bin/env python3
"""Self-test — a csqtt owner password that leads with `-` (1.8.12 item 15, docs/RELEASE-1.8.12-PLAN.md).

The node mints each csqtt server's owner password and passes it on the server's command line (`--password
${SWG_PASSWORD}` in the unit, `["--password", pw]` in the docker argv). It was URL-safe base64, so it led with `-` about
1 time in 64; clap then read it as a flag, the server exited 2 and restarted for ever (hit live 2026-11-16).

swg-noded is loaded as a module with its csqtt roots in a temp dir; nothing reaches systemd, docker or the network.

  [1] mint      many draws: letters and digits only, never a leading `-`, the old length (24)
  [2] heal      bare-metal: a record whose owner password leads with `-` gets a new one, csqtt.env carries it, the
                server is restarted exactly once; the next pass restarts nothing
  [3] normal    a normal record: the password kept, the env untouched, no restart
  [4] docker    the docker shape heals too: one respawn, and its argv (_csqtt_argv) carries the new password
  [5] stopped   a stopped server is not started by the heal; its record and env are re-minted all the same, so it
                starts on the new password, by its own start only (no second restart)
  [6] order     review F1/F2: the env is healed BEFORE anything else in the pass can restart the server — a build
                update in the same pass starts it from the healed file

Run: python3 tests/csqtt_owner_password_selftest.py   (0 = pass)
     --perturb <name>  plants one regression and expects RED on its section:
                       mint [1] · heal [2] [4] [5] [6] · earlyenv [5] [6] · restart [2] [4]
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {   # name: (sections, anchor, replacement)
    "mint": ("[1]", '    return "".join(secrets.choice(_WDTT_PW_CHARS) for _ in range(24))\n',
             '    return base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")\n'),
    "heal": (("[2]", "[4]", "[5]", "[6]"), '            if not inst["password"] or _pw_heal:\n', '            if not inst["password"]:\n'),
    "earlyenv": (("[5]", "[6]"), '            if _pw_heal and os.path.isfile(_csqtt_dir(iface) + "/csqtt.env"):\n',
                 '            if False:\n'),
    "restart": (("[2]", "[4]"), '                        or (_pw_heal and not inst.get("stopped") and not _switched)\n', ""),
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

TMP = tempfile.mkdtemp(prefix="csqtt-owner-pw-")
src = open(NODED, encoding="utf-8").read()
if MODE:
    _sec, old, new = PLANTS[MODE]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    src = src.replace(old, new)
p = os.path.join(TMP, "swg-noded"); open(p, "w", encoding="utf-8").write(src)
os.environ["SWG_NO_REEXEC"] = "1"
ld = importlib.machinery.SourceFileLoader("swgnoded_csqtt_owner_pw", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_csqtt_owner_pw", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass

# ── the sandbox ────────────────────────────────────────────────────────────────────────────────────────────────
N.CSQTT_ROOT = os.path.join(TMP, "csqtt"); N.CSQTT_BIN_DIR = N.CSQTT_ROOT + "/.bin"
N.CSQTT_RECORD = os.path.join(TMP, "csqtt.json")
UNITS = os.path.join(TMP, "units"); os.makedirs(UNITS)
N.turn_unit_dir = lambda: UNITS
N._turn_arch = lambda: "amd64"
N._csqtt_adopted_users = lambda *a, **k: {}
N.bind_heal_due = lambda *a, **k: False
N._csqtt_verify = lambda iface: ""
N._csqtt_reconcile_desired = lambda iface, body: ""
N._csqtt_desired_changed = lambda iface, body: False
N._unit_active = lambda svc: "active"
SH, STARTS = [], []
def _sh(cmd, *a, **k):
    SH.append(str(cmd))
    class R: returncode, stdout, stderr = 0, "", ""
    return R()
N.host_sh = _sh
def _dstart(inst):
    STARTS.append(N._csqtt_argv(inst, N._csqtt_dir(inst["iface"]) + "/server")); return ""
N._csqtt_docker_start = _dstart
N._csqtt_docker_pid = lambda iface: 4242
N._csqtt_docker_stop = lambda iface: None
def restarts(iface):
    return [c for c in SH if "restart" in c and N._csqtt_svc(iface) in c]

BAD = "-eX2kPq9vL0aZ7mN3bC5dF8g"   # 24 chars, leads with `-`, as base64 minted it
OK = "Zr8XkPq9vL0aZ7mN3bC5dF8g"

def lay(iface, password, stopped=False):
    """An installed server of ours as an older build left it: record, cfgdir + env, the unit, the slot binary."""
    slot = N._csqtt_bin_shared("2.1")
    os.makedirs(os.path.dirname(slot), exist_ok=True)
    if not os.path.exists(slot):
        open(slot, "w").write("#!/bin/sh\n"); os.chmod(slot, 0o755)
    d = N._csqtt_dir(iface)
    inst = {"iface": iface, "listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "line": "2.1", "panel_managed": True,
            "pw_seen": True, "passwords": {"pw1": {}}, "password": password, "web_pass": "w" * 48, "web_port": 47000}
    if stopped:
        inst["stopped"] = True
    N._csqtt_write_cfgdir(inst, slot, d + "/server", d)
    with open(N._csqtt_unit_path(iface), "w") as f:
        f.write(N._csqtt_unit_text(iface, d + "/server", d))
    rec = N._csqtt_load() if os.path.exists(N.CSQTT_RECORD) else {}
    rec[iface] = inst; json.dump(rec, open(N.CSQTT_RECORD, "w"))
    return inst
def want(stopped=False, **kw):
    w = {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "passwords": {"pw1": {}}, "line": "2.1"}
    w.update(kw)
    if stopped:
        w["stopped"] = True
    return w
def env_pw(iface):
    return N._env_line(N._csqtt_dir(iface) + "/csqtt.env", "SWG_PASSWORD")
def rec_pw(iface):
    return (N._csqtt_load().get(iface) or {}).get("password")
def env_bytes(iface):
    return open(N._csqtt_dir(iface) + "/csqtt.env", "rb").read()

try:
    section("[1] mint")
    draws = [N._gen_csqtt_password() for _ in range(20000)]
    check("no draw leads with '-'", not any(d.startswith("-") for d in draws), [d for d in draws if d.startswith("-")][:3])
    check("letters and digits only", all(d.isalnum() and d.isascii() for d in draws), [d for d in draws if not d.isalnum()][:3])
    check("24 characters, as before", all(len(d) == 24 for d in draws), {len(d) for d in draws})
    check("draws differ", len(set(draws)) == len(draws))

    section("[2] heal (bare-metal)")
    N.NODE_KIND = "baremetal"
    lay("csqtt1", BAD)
    del SH[:]
    r = N.reconcile_csqtt({"csqtt1": want()})
    npw = rec_pw("csqtt1")
    check("no error", not r["errors"], r["errors"])
    check("the record has a new owner password", npw and npw != BAD, npw and npw[:1])
    check("…that does not lead with '-'", bool(npw) and not npw.startswith("-"))
    check("csqtt.env carries it", env_pw("csqtt1") == npw, (env_pw("csqtt1") or "")[:1])
    check("the server was restarted exactly once", len(restarts("csqtt1")) == 1, restarts("csqtt1"))
    del SH[:]
    N.reconcile_csqtt({"csqtt1": want()})
    check("the next pass restarts nothing", restarts("csqtt1") == [], restarts("csqtt1"))
    check("…and keeps the healed password", rec_pw("csqtt1") == npw)

    section("[3] normal record untouched")
    lay("csqtt2", OK)
    before = env_bytes("csqtt2")
    del SH[:]
    N.reconcile_csqtt({"csqtt1": want(), "csqtt2": want()})
    check("the password is kept", rec_pw("csqtt2") == OK)
    check("csqtt.env is untouched", env_bytes("csqtt2") == before)
    check("no restart", restarts("csqtt2") == [], restarts("csqtt2"))

    section("[4] docker")
    N.NODE_KIND = "docker"
    os.remove(N.CSQTT_RECORD)
    lay("csqtt3", BAD)
    del STARTS[:]
    r = N.reconcile_csqtt({"csqtt3": want()})
    npw = rec_pw("csqtt3")
    check("no error", not r["errors"], r["errors"])
    check("the record has a new owner password, no leading '-'", bool(npw) and npw != BAD and not npw.startswith("-"))
    check("csqtt.env carries it", env_pw("csqtt3") == npw)
    check("respawned exactly once", len(STARTS) == 1, len(STARTS))
    argv = STARTS[0] if STARTS else []
    pw_arg = argv[argv.index("--password") + 1] if "--password" in argv else None
    check("…with the new password on its argv", pw_arg == npw, (pw_arg or "")[:1])
    del STARTS[:]
    N.reconcile_csqtt({"csqtt3": want()})
    check("the next pass respawns nothing", STARTS == [], len(STARTS))

    section("[5] stopped")
    N.NODE_KIND = "baremetal"
    os.remove(N.CSQTT_RECORD)
    lay("csqtt4", BAD, stopped=True)
    del SH[:]
    N.reconcile_csqtt({"csqtt4": want(stopped=True)})
    npw = rec_pw("csqtt4")
    check("a stopped server is not restarted", restarts("csqtt4") == [] and not [c for c in SH if "enable" in c], SH)
    check("…its record is re-minted all the same", bool(npw) and not npw.startswith("-"))
    check("…and its csqtt.env carries it already", env_pw("csqtt4") == npw, (env_pw("csqtt4") or "")[:1])
    del SH[:]
    N.reconcile_csqtt({"csqtt4": want()})
    check("started again: csqtt.env still carries the new password", env_pw("csqtt4") == npw, (env_pw("csqtt4") or "")[:1])
    check("…started by its own start only, no heal restart", restarts("csqtt4") == [] and [c for c in SH if "enable" in c], SH)

    section("[6] order — the env is healed before a build update restarts the server")
    os.remove(N.CSQTT_RECORD)
    lay("csqtt5", BAD)
    SEEN = []
    real_upd, real_iv = N._csqtt_update_binary, N._csqtt_installed_ver
    N._csqtt_installed_ver = lambda line: "old"
    N._csqtt_update_binary = lambda inst, ver, ifaces, line="2.1": SEEN.append(env_pw(inst["iface"])) or ""
    try:
        N.reconcile_csqtt({"csqtt5": want(ver="new")})
    finally:
        N._csqtt_update_binary, N._csqtt_installed_ver = real_upd, real_iv
    npw = rec_pw("csqtt5")
    check("the build update ran", len(SEEN) == 1, len(SEEN))
    check("…and saw the healed csqtt.env, not the `-` one", bool(SEEN) and SEEN[0] == npw and not (SEEN[0] or "-").startswith("-"),
          [(x or "")[:1] for x in SEEN])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][0]; secs = (secs,) if isinstance(secs, str) else secs
    hit = [s for s, _ in FAILS if s.split()[0] in secs]
    print("PLANT %s: %s" % (MODE, "RED as expected" if hit else "NOT CAUGHT"))
    sys.exit(0 if hit else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
