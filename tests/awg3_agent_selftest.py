#!/usr/bin/env python3
"""Self-test — swg-agent's AmneziaWG 3 apply path, hermetically (docs/AWG3-PLAN.md §7.4; the root rigs
.campaign/rigs/awg3-p1-agent.py / -g8.sh / -unit.sh drive the same code on real devices).

An AWG edit on an interface whose conf or request holds a 3.x key is a RECREATE: the full dict into the conf, the device
down and up the way it was started, the 3.x keys read back — or the old conf back up and `awg_gen_refused`. Everything
else keeps today's live `awg set`. Driven through the REAL op_set_iface with the system calls stubbed:

  [1] a conf carrying a 3.1 kernel's "unset" lines (`= 0` / `= off`) is a 2.0 interface: the live path, no bounce — and
      the edit drops those lines, which no 2.0 datapath accepts
  [2] a set that does not say it is WHOLE keeps the 3.x keys the conf has (an older panel's 2.0-only edit must not switch
      a 3.1 interface back — review of 9f40ac2); one marked `awg_params_exact` drops them
  [3] a stopped / down interface gets its conf and is NOT brought up
  [4] a refusal — a bring-up that fails, or a device that comes up without the keys — puts the old conf back, brings it
      up again, and answers awg_gen_refused with the reason

Run: python3 tests/awg3_agent_selftest.py      (0 = pass)
     --perturb-zero       the unset lines count as 3.x keys            → RED in [1]
     --perturb-keep       a 2.0-only set drops the conf's 3.x keys     → RED in [2]
     --perturb-down       a down interface is brought up               → RED in [3]
     --perturb-rollback   the old conf is not put back                 → RED in [4]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")

PLANTS = {
    "--perturb-zero": ("[1]", '    return k in AWG3_KEYS and k != "HeaderProtectionKey" and str(v).strip().lower() in ("0", "off")\n',
                       "    return False\n"),
    "--perturb-keep": ("[2]", "        if awg and cur3 and not req.get(\"awg_params_exact\"):\n", "        if False:\n"),
    "--perturb-down": ("[3]", '    if not os.path.exists(f"/sys/class/net/{iface}"):\n        # Stopped, or down',
                       '    if False:\n        # Stopped, or down'),
    "--perturb-rollback": ("[4]", '    write_conf_atomic(ic["conf"], before)\n    try:\n', "    try:\n"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:260]) if detail and not cond else ""))
    if not cond:
        FAILS.append((SECTION[0], name))

path = AGENT
if MODE:
    src = open(AGENT, encoding="utf-8").read()
    old, new = PLANTS[MODE][1:]
    assert src.count(old) == 1, "plant anchor matched %d times — this run would measure nothing" % src.count(old)
    fd, path = tempfile.mkstemp(suffix=".py", prefix="awg3agent-"); os.write(fd, src.replace(old, new).encode()); os.close(fd)
l = importlib.machinery.SourceFileLoader("agent_awg3", path)
A = importlib.util.module_from_spec(importlib.util.spec_from_loader("agent_awg3", l))
try:
    l.exec_module(A)
except SystemExit:
    pass
if MODE:
    os.unlink(path)

IF = "swgt%d" % (os.getpid() % 100000)
TMP = tempfile.mkdtemp(prefix="awg3agent-")
CONF = os.path.join(TMP, IF + ".conf")
BASE = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33", "H1": "1-9", "H2": "10-19",
        "H3": "20-29", "H4": "30-39"}
SET31 = {"HeaderProtectionKey": "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0=", "RandomTrailers": "1",
         "ContentPaddingAddition": "10-100", "RekeyAfterTime": "100-120", "RekeyTimeout": "3-7", "RejectAfterTime": "150-180",
         "KeepaliveTimeout": "5-15", "MaxHandshakeAttempts": "15-20"}
ZERO = {"ContentPaddingAddition": "0", "RekeyAfterTime": "0", "RandomTrailers": "off", "DisableCookies": "off"}
lines = lambda d: "".join("%s = %s\n" % kv for kv in d.items())
def conf(awg):
    return "[Interface]\nPrivateKey = x\nAddress = 10.9.0.1/24\nListenPort = 51820\n" + lines(awg) + "\n[Peer]\nPublicKey = y\nAllowedIPs = 10.9.0.2/32\n"

# ── stubs: the commands, the device, the bounce ─────────────────────────────────────────────────────────────────
CMDS, BOUNCES = [], []
DEV = {"up": True, "reads": None, "fail_up": ""}
def fake_run(args, input_text=None, check=True):
    CMDS.append(list(args))
    if args[1:2] == ["showconf"]:
        body = DEV["reads"] if DEV["reads"] is not None else open(CONF).read()
        return body
    return ""
A.run = fake_run
A._unit_started = lambda tool, iface: False
def fake_bounce(ic, iface, tool, by_unit):
    BOUNCES.append(A.parse_interface_section(open(ic["conf"]).read()).get("HeaderProtectionKey"))
    if DEV["fail_up"] and len(BOUNCES) == 1:
        raise A.AgentError("up_failed", DEV["fail_up"])
A._bounce = fake_bounce
_exists = os.path.exists
os.path.exists = lambda p: (DEV["up"] if p == "/sys/class/net/%s" % IF else _exists(p))
CFG = {"interfaces": {IF: {"cmd": ["awg"], "conf": CONF}}}

def run_op(conf_awg, req_awg, exact=False, up=True, reads=None, fail_up=""):
    open(CONF, "w").write(conf(conf_awg))
    CMDS.clear(); BOUNCES.clear(); DEV.update(up=up, reads=reads, fail_up=fail_up)
    req = {"iface": IF, "awg_params": req_awg, **({"awg_params_exact": True} if exact else {})}
    try:
        return A.op_set_iface(CFG, req), None
    except A.AgentError as e:
        return None, e

try:
    SECTION[0] = "[1]"
    print("[1] a conf with a 3.1 kernel's unset lines is a 2.0 interface")
    out, err = run_op({**BASE, **ZERO}, {**BASE, "Jc": "5"})
    after = A.parse_interface_section(open(CONF).read())
    check("the edit succeeds", err is None and out, err)
    check("…on the LIVE path: one `awg set`, no bounce", BOUNCES == [] and any(c[:2] == ["awg", "set"] for c in CMDS), (BOUNCES, CMDS))
    check("…the conf has Jc 5 and none of the unset lines", after.get("Jc") == "5" and not any(k in after for k in ZERO), after)

    SECTION[0] = "[2]"
    print("\n[2] a set that is not marked whole keeps the conf's 3.x keys")
    out, err = run_op({**BASE, **SET31}, {**BASE, "Jc": "5"})
    after = A.parse_interface_section(open(CONF).read())
    check("an older panel's 2.0-only Jc edit on a 3.1 interface succeeds", err is None, err)
    check("…as a recreate", len(BOUNCES) == 1, BOUNCES)
    check("…and the interface is still 3.1: every key kept, Jc 5", after.get("Jc") == "5" and all(after.get(k) == v for k, v in SET31.items()), after)
    out, err = run_op({**BASE, **SET31}, dict(BASE), exact=True)
    after = A.parse_interface_section(open(CONF).read())
    check("marked whole (the panel's switch back) → no 3.x key left", err is None and not any(k in after for k in SET31), (err, after))

    SECTION[0] = "[3]"
    print("\n[3] a stopped / down interface is not brought up")
    out, err = run_op({**BASE, **SET31}, {**BASE, **SET31, "Jc": "6"}, up=False)
    after = A.parse_interface_section(open(CONF).read())
    check("the edit succeeds, the conf takes it", err is None and after.get("Jc") == "6", (err, after))
    check("…and nothing is bounced", BOUNCES == [], BOUNCES)

    SECTION[0] = "[4]"
    print("\n[4] a refusal puts the old conf back up")
    before = conf(dict(BASE))
    out, err = run_op(dict(BASE), {**BASE, **SET31}, fail_up="Unable to modify interface: Invalid argument")
    check("a bring-up the datapath refuses → awg_gen_refused, naming the tool's words",
          err is not None and err.code == "awg_gen_refused" and "Invalid argument" in err.msg, err and err.msg)
    check("…the old conf is back, byte for byte", open(CONF).read() == before)
    check("…and brought up again (two bounces: the try, the rollback)", len(BOUNCES) == 2 and BOUNCES[1] is None, BOUNCES)
    out, err = run_op(dict(BASE), {**BASE, **SET31}, reads=conf(dict(BASE)))       # the device comes up without the keys
    check("a device that comes up without the keys → awg_gen_refused naming them",
          err is not None and err.code == "awg_gen_refused" and "HeaderProtectionKey" in err.msg, err and err.msg)
    check("…and the old conf is back", open(CONF).read() == before)
    out, err = run_op(dict(BASE), {**BASE, **SET31})
    check("control: a device that takes the keys → ok, one bounce", err is None and len(BOUNCES) == 1, (err, BOUNCES))
finally:
    os.path.exists = _exists

print()
if MODE:
    want = PLANTS[MODE][0]
    red = sorted({s for s, _ in FAILS})
    ok = red == [want]
    print(("PERTURB OK — %s went red on %s only" if ok else "PERTURB FAILED — %s: red sections %s, wanted exactly %s")
          % ((MODE, want) if ok else (MODE, red, want)))
    sys.exit(0 if ok else 1)
if FAILS:
    print("FAILED: " + "; ".join("%s %s" % f for f in FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
