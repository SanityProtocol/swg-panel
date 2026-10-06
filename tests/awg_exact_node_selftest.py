#!/usr/bin/env python3
"""Self-test — the node half of "an AmneziaWG field set to none" (docs/AWG-OMIT-AND-MESH-GEN-PLAN.md A4, phase P1), driven
through the REAL swg-agent ops and the REAL swg-noded functions with the system calls stubbed (the root rig
.campaign/rigs/awg-exact-netns.sh drives the same code on a kernel device).

  [1] agent create-iface with `awg_params_exact` writes exactly the keys given — no S3, no I line invented; without it a
      partial set is still filled (today's create, the control); exact + no key at all is `awg_empty_exact`, never a
      random set (an AmneziaWG device without parameters is what plain WireGuard is)
  [2] agent set-iface with `awg_params_exact` and a 2.0 key the conf has and the set lacks → a RECREATE (a live `awg set`
      cannot unset a key), and the readback proves the key is gone: `S3 = 0`, `H1 = 1` and a missing I line read as gone,
      `S3 = 72` still on the device is refused and the old conf put back. Without `exact` a partial set is today's live path
  [3] swg-noded: the set-iface diff with `exact` sees a 2.0 key the conf holds and the set lacks (only 3.x keys before);
      the create path passes `awg_params_exact` through (it dropped it); the node reports `datapath.awg.exact`

Run: python3 tests/awg_exact_node_selftest.py      (0 = pass)
     --perturb-create   the agent ignores `exact` on create (fills from its own set)  → RED in [1]
     --perturb-gone     a removal stays on the live path                              → RED in [2]
     --perturb-diff     noded compares only the 3.x keys for `exact` (the old diff)    → RED in [3]
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {
    "--perturb-create": ("[1]", AGENT, '        if supp and req.get("awg_params_exact"):\n            body +=',
                         '        if False:\n            body +='),
    "--perturb-gone": ("[2]", AGENT, " or any(k in awg for k in AWG3_KEYS) or gone):", " or any(k in awg for k in AWG3_KEYS)):"),
    "--perturb-diff": ("[3]", NODED, "any(k in cur_awg and k not in want_s for k in AWG_KEYS))):",
                       "any(k in cur_awg and k not in want_s for k in AWG3_KEYS))):"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:260]) if detail and not cond else ""))
    if not cond:
        FAILS.append((SECTION[0], name))


def load(path, name):
    if MODE and PLANTS[MODE][1] == path:
        src = open(path, encoding="utf-8").read()
        old, new = PLANTS[MODE][2:]
        assert src.count(old) == 1, "plant anchor matched %d times — this run would measure nothing" % src.count(old)
        fd, p = tempfile.mkstemp(suffix=".py", prefix="awgexact-"); os.write(fd, src.replace(old, new).encode()); os.close(fd)
    else:
        p = path
    l = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    if p != path:
        os.unlink(p)
    return m


A = load(AGENT, "agent_exact")
N = load(NODED, "noded_exact")

IF = "swgx%d" % (os.getpid() % 100000)
TMP = tempfile.mkdtemp(prefix="awgexact-")
CONF = os.path.join(TMP, IF + ".conf")
BASE = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "72", "S4": "33", "H1": "1000-1009",
        "H2": "2000-2009", "H3": "3000-3009", "H4": "4000-4009", "I1": "<r 64>", "I2": "<r 24>"}
lines = lambda d: "".join("%s = %s\n" % kv for kv in d.items())
def conf(awg):
    return "[Interface]\nPrivateKey = x\nAddress = 10.9.0.1/24\nListenPort = 51820\n" + lines(awg) + "\n[Peer]\nPublicKey = y\nAllowedIPs = 10.9.0.2/32\n"

# ── agent stubs ─────────────────────────────────────────────────────────────────────────────────────────────────────
CMDS, BOUNCES, WRITES = [], [], {}
DEV = {"up": True, "reads": None}
def fake_run(args, input_text=None, check=True):
    CMDS.append(list(args))
    if args[1:2] == ["showconf"]:
        return DEV["reads"] if DEV["reads"] is not None else open(CONF).read()
    if args[1:2] == ["genkey"]:
        return "cHJpdmF0ZWtleXByaXZhdGVrZXlwcml2YXRla2V5cHI="
    if args[1:2] == ["pubkey"]:
        return "cHVibGlja2V5cHVibGlja2V5cHVibGlja2V5cHVibGk="
    return ""
A.run = fake_run
A._unit_started = lambda tool, iface: False
A._bounce = lambda ic, iface, tool, by_unit: BOUNCES.append(A.parse_interface_section(open(ic["conf"]).read()))
A._ensure_tool = lambda tool: None
A._quick_up = lambda tool, iface, target="": None
A._iface_unit = lambda action, tool, iface: None
A._wan_iface = lambda: "eth0"
_real_write = A.write_conf_atomic
def fake_write(path, text):
    if path.startswith(TMP):
        return _real_write(path, text)
    WRITES[path] = text
A.write_conf_atomic = fake_write
A.os.makedirs = lambda *a, **k: None
_exists = os.path.exists
os.path.exists = lambda p: (DEV["up"] if p == "/sys/class/net/%s" % IF else (p in WRITES) if p.startswith("/etc/") else _exists(p))
A.shutil.which = lambda t: "/usr/bin/" + t

def create(awg, exact):
    WRITES.clear()
    req = {"iface": IF, "cmd": ["awg"], "subnet": "10.9.0.0/24", "listen_port": 51820, "awg_params": awg,
           **({"awg_params_exact": True} if exact else {})}
    try:
        A.op_create_iface({"interfaces": {}}, req)
    except A.AgentError as e:
        return None, e
    body = next(iter(WRITES.values()), "")
    return {k: v for k, v in A.parse_interface_section(body).items() if k in A.AWG_KEYS}, None

CFG = {"interfaces": {IF: {"cmd": ["awg"], "conf": CONF}}}
def set_iface(conf_awg, req_awg, exact=False, reads=None):
    open(CONF, "w").write(conf(conf_awg))
    CMDS.clear(); BOUNCES.clear(); DEV.update(up=True, reads=reads)
    req = {"iface": IF, "awg_params": req_awg, **({"awg_params_exact": True} if exact else {})}
    try:
        return A.op_set_iface(CFG, req), None
    except A.AgentError as e:
        return None, e

try:
    SECTION[0] = "[1]"
    print("[1] agent create-iface: an exact set is written as it is")
    part = {k: v for k, v in BASE.items() if k not in ("S3", "I2")}
    got, err = create(part, True)
    check("exact: the conf holds exactly the keys given (no S3, no I2)", err is None and got == part, (err, got))
    got, err = create({"S1": "28", "S2": "94"}, False)
    check("control — not exact: a partial set is filled (Jc, S3, H… from the agent's own set)",
          err is None and got.get("S1") == "28" and "S3" in got and "Jc" in got, (err, got))
    got, err = create({}, True)
    check("exact with no key at all → awg_empty_exact, nothing written", err is not None and err.code == "awg_empty_exact"
          and not WRITES, (err and err.code, WRITES))
    got, err = create({}, False)
    check("control — no set, not exact: a random set (a brand-new interface)", err is None and "S1" in (got or {}), (err, got))

    SECTION[0] = "[2]"
    print("\n[2] agent set-iface: a key the whole set leaves out comes off the device")
    want = {k: v for k, v in BASE.items() if k not in ("S3", "I1", "H1")}
    reads = conf({**want, "S3": "0", "H1": "1"})                  # what a 3.1 kernel prints once they are gone; I1 not at all
    out, err = set_iface(BASE, want, exact=True, reads=reads)
    after = A.parse_interface_section(open(CONF).read())
    check("exact removal of S3, I1, H1 → one recreate", err is None and len(BOUNCES) == 1, (err, len(BOUNCES)))
    check("…no live `awg set`", not any(c[:2] == ["awg", "set"] for c in CMDS), CMDS)
    check("…the conf is the set: S3, I1, H1 gone, the rest kept", not any(k in after for k in ("S3", "I1", "H1"))
          and all(after.get(k) == v for k, v in want.items()), after)
    out, err = set_iface(BASE, want, exact=True, reads=conf({**want, "S3": "72", "H1": "1"}))
    check("a device that comes up still holding S3 → awg_gen_refused naming it", err is not None
          and err.code == "awg_gen_refused" and "S3" in err.msg, err and err.msg)
    check("…and the old conf is back, byte for byte", open(CONF).read() == conf(BASE))
    out, err = set_iface(BASE, want, exact=False)
    check("control — the same set NOT marked whole: today's live path (no bounce)",
          err is None and BOUNCES == [] and any(c[:2] == ["awg", "set"] for c in CMDS), (err, BOUNCES))
    out, err = set_iface(BASE, {**BASE, "Jc": "5"}, exact=True)
    check("control — an exact set that removes nothing (a value change): the live path",
          err is None and BOUNCES == [] and any(c[:2] == ["awg", "set"] for c in CMDS), (err, BOUNCES))

    SECTION[0] = "[3]"
    print("\n[3] swg-noded: the diff, the create pass-through, the capability")
    open(CONF, "w").write(conf(BASE))
    calls = []
    N.run_agent = lambda agent, sudo, payload: (calls.append(payload), {"ok": True, "data": {}})[1]
    N.awg_gen_refusal = lambda iface, awg: ""
    N.current_listen_port = lambda node_cfg, iface: 51820
    ncfg = {"interfaces": {IF: {"cmd": ["awg"], "conf": CONF}}}
    want_n = {k: v for k, v in BASE.items() if k != "S3"}
    N.reconcile_ifaces(ncfg, {IF: {"awg_params": want_n, "awg_params_exact": True}}, "agent", False)
    sent = [c for c in calls if c.get("op") == "set-iface"]
    check("exact + S3 in the conf, not in the set → a set-iface, marked exact", len(sent) == 1
          and sent[0].get("awg_params_exact") is True and "S3" not in sent[0].get("awg_params", {}), sent)
    calls.clear()
    N.reconcile_ifaces(ncfg, {IF: {"awg_params": want_n}}, "agent", False)
    check("control — the same set not marked whole: no difference (today's compare)",
          not [c for c in calls if c.get("op") == "set-iface"], calls)
    calls.clear()
    N._live_wg_ifaces = lambda: set()
    N._persist_config = lambda cfg: None
    N.harvest_iface_backup = lambda *a, **k: None
    N.read_iface_backup = lambda *a, **k: None
    N.ensure_iface_backup = lambda *a, **k: None
    N.run_agent = lambda agent, sudo, payload: (calls.append(payload), {"ok": True, "data": {"conf": CONF, "cmd": ["awg"]}})[1]
    N.create_ifaces({"interfaces": {}}, {"swgn1": {"cmd": ["awg"], "subnet": "10.8.0.0/24", "awg_params": {"S1": "20"},
                                                    "awg_params_exact": True}}, "agent", False)
    N.create_ifaces({"interfaces": {}}, {"swgn2": {"cmd": ["awg"], "subnet": "10.8.1.0/24", "awg_params": {"S1": "20"}}},
                    "agent", False)
    cr = {c["iface"]: c for c in calls if c.get("op") == "create-iface"}
    check("create passes awg_params_exact through", (cr.get("swgn1") or {}).get("awg_params_exact") is True, cr.get("swgn1"))
    check("…and a create without it sends the request it always did (no key)", "awg_params_exact" not in (cr.get("swgn2") or {"x": 1}),
          cr.get("swgn2"))
    N.awg_gen_report = lambda: {"module": "3.1"}
    check("the node reports datapath.awg.exact", N._with_awg_gen({}).get("awg", {}).get("exact") == 1, N._with_awg_gen({}))
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
