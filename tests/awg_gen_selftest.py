#!/usr/bin/env python3
"""Self-test — the node's AmneziaWG GENERATION report, and the gate that uses it (docs/AWG3-PLAN.md §4.2, §7.2; G2, G2b).

Every version string lies (amneziawg-go --version, awg --version, /sys/module/amneziawg/version — all measured wrong), so
swg-noded asks the parts: the kernel's generic-netlink family for the module, the UAPI keys compiled into the amneziawg-go
awg-quick would start, the parser keys compiled into `awg`. The panel refuses a switch below 3.1 from that report; noded
refuses — BEFORE calling the agent — any set-iface / create-iface whose dict needs more than the datapath or the tools
it would land on, because a failed set-iface is retried every ≤ 300 s and the agent's recreate-and-rollback would bounce
a WORKING interface on every retry.

  [1] a binary is classified by the keys it contains; a missing one is None, never a guess
  [2] the genl answer maps exactly (2·25 = 2.0, 3·32 = 3.0, 3·34 = 3.1); anything else — another family's numbers, a
      future version — is "unknown", never rounded up; not loaded is None
  [3] the real netlink path works on this machine (nlctrl answers, a made-up family is None)
  [4] the report rides every snapshot, a docker node's too, and is cached (300 s) — not probed per sync
  [5] what a dict needs, and why a node refuses it (the datapath the interface runs on, then the tools)
  [6] through the REAL reconcile_ifaces / create_ifaces: a refused 3.x set never reaches the agent and is reported;
      a port change beside it still goes; a 2.0 set is exactly today's call; a capable node gets the call
  [7] the panel's datapath consumers read a node with `gen` exactly as one without (issues, datapath_broken, repairable)
  [8] the presence compare (a 3.x key the conf has and the panel dropped) fires ONLY when the panel says its set is
      whole (`awg_params_exact`), and that word is passed on to the agent — so an older panel's 2.0-only set never
      strips a 3.x interface (review of 9f40ac2)
  [9] a conf carrying what a 3.1 kernel prints for "unset" (`= 0` / `= off`) reads as the 2.0 interface it is: no 3.x
      key reported, no set-iface for them
  [10] a recreate the agent answers `awg_gen_refused` is NOT retried with the same set (each retry is a double bounce);
      the refusal stays reported; a changed set tries again at once

Hermetic: the agent, the conf read and the report are stubbed where a test needs a node other than this machine.

Run: python3 tests/awg_gen_selftest.py      (0 = pass)
     --perturb-gate     noded no longer refuses a set-iface         → RED in [6]
     --perturb-create   …nor a create-iface                         → RED in [6]
     --perturb-map      a 3.0 module is read as 3.1                 → RED in [2]
     --perturb-exact    the presence compare ignores the flag        → RED in [8]
     --perturb-fwd      the flag is not passed to the agent          → RED in [8]
     --perturb-zero     `= 0` / `= off` lines count as 3.x keys      → RED in [9]
     --perturb-hold     a refused recreate is retried on the backoff → RED in [10]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb-gate": ("[6]", "                refused = awg_gen_refusal(iface, awg)\n", "                refused = \"\"\n"),
    "--perturb-create": ("[6]", "        _no3 = awg_gen_refusal(iface, (want or {}).get(\"awg_params\"))   # an AmneziaWG 3 set this node cannot bring up\n",
                         "        _no3 = \"\"\n"),
    "--perturb-map": ("[2]", '("3.1" if v == 3 and m >= 34 else', '("3.1" if v == 3 and m >= 32 else'),
    "--perturb-exact": ("[8]", "or (want.get(\"awg_params_exact\") and any(k in cur_awg and k not in want_s for k in AWG3_KEYS))):",
                        "or any(k in cur_awg and k not in want_s for k in AWG3_KEYS)):"),
    "--perturb-fwd": ("[8]", "                    if want.get(\"awg_params_exact\"):\n                        payload[\"awg_params_exact\"] = True",
                      "                    if False:\n                        payload[\"awg_params_exact\"] = True"),
    "--perturb-zero": ("[9]", "    return k in AWG3_KEYS and k != \"HeaderProtectionKey\" and str(v).strip().lower() in (\"0\", \"off\")\n",
                       "    return False\n"),
    "--perturb-hold": ("[10]", "                _OP_BACKOFF[akey][1] = float(\"inf\")\n", "                pass\n"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:240]) if detail and not cond else ""))
    if not cond:
        FAILS.append((SECTION[0], name))

def _load(path, name, plant=None):
    if plant:
        src = open(path, encoding="utf-8").read()
        assert src.count(plant[0]) == 1, "plant anchor matched %d times — this run would measure nothing" % src.count(plant[0])
        fd, path = tempfile.mkstemp(suffix=".py", prefix="awggen-")
        os.write(fd, src.replace(plant[0], plant[1]).encode()); os.close(fd)
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    if plant:
        os.unlink(path)
    return mod

N = _load(NODED, "noded_gen", PLANTS[MODE][1:] if MODE else None)
TMP = tempfile.mkdtemp(prefix="awggen-")

SECTION[0] = "[1]"
print("[1] binaries are classified by the keys compiled into them")
def fake(name, data):
    p = os.path.join(TMP, name); open(p, "wb").write(b"\x7fELF...." + data + b"....")
    os.chmod(p, 0o755); return p
GO = ("random_trailers", "header_protection")
TOOLS = ("RandomTrailers", "HeaderProtectionKey")
for label, data, want in (("go 3.1", b"header_protection random_trailers", "3.1"), ("go 3.0", b"header_protection", "3.0"),
                          ("go 2.0", b"jc jmin s1 h1", "2.0")):
    check("amneziawg-go %s → %s" % (label, want), N._bin_gen(fake("g" + want, data), *[k.encode() for k in GO]) == want)
for label, data, want in (("tools 3.1", b"HeaderProtectionKey RandomTrailers", "3.1"), ("tools 3.0", b"HeaderProtectionKey", "3.0"),
                          ("tools 2.0", b"Jc Jmin S1 H1", "2.0")):
    check("awg %s → %s" % (label, want), N._bin_gen(fake("t" + want, data), *[k.encode() for k in TOOLS]) == want)
check("a binary that is not there → None (not a guess)", N._bin_gen(os.path.join(TMP, "nope"), b"x", b"y") is None
      and N._bin_gen("", b"x", b"y") is None)

SECTION[0] = "[2]"
print("\n[2] the genl answer maps exactly; nothing is rounded up")
_real = N._genl_family
for vm, want in (((2, 25), "2.0"), ((3, 32), "3.0"), ((3, 34), "3.1"), ((3, 36), "3.1"), ((1, 8), "unknown"),
                 ((2, 0), "unknown"), ((4, 40), "unknown"), ((3, 20), "unknown"), (None, None)):
    N._genl_family = lambda name, vm=vm: vm
    check("genl %s → %s" % (vm, want), N._awg_module_gen() == want, N._awg_module_gen())
def _boom(name):
    raise OSError(13, "denied")
N._genl_family = _boom
check("a netlink error → unknown, never absent (a loaded module must not read as missing)", N._awg_module_gen() == "unknown")
N._genl_family = _real

SECTION[0] = "[3]"
print("\n[3] the real netlink path on this machine")
nl = N._genl_family("nlctrl")
check("the generic-netlink controller answers with (version, maxattr)", isinstance(nl, tuple) and isinstance(nl[0], int), nl)
check("a family that does not exist → None (names are ≤ 15 bytes: GENL_NAMSIZ)", N._genl_family("swgnofamily") is None)

SECTION[0] = "[4]"
print("\n[4] the report rides every snapshot and is cached")
calls = []
N._awg_module_gen = lambda: calls.append(1) or "3.1"
N._AWG_GEN.update(at=0.0, v=None)
r1 = N.awg_gen_report(now=1000.0); r2 = N.awg_gen_report(now=1200.0); r3 = N.awg_gen_report(now=1400.0)
check("probed once in 300 s, again after", len(calls) == 2 and r1 == r2 == r3, calls)
check("the report has exactly module / fallback / tools", set(r1) == {"module", "fallback", "tools"}, r1)
check("a docker node (no health report) still carries gen", set(N._with_awg_gen({})) == {"awg"}
      and set(N._with_awg_gen({})["awg"]) == {"gen"})
_h = {"awg": {"needed": True, "ok": False, "fallback": True, "userspace": ["awg0"]}}
check("…and a bare-metal node's health report is kept as it was, gen beside it",
      {k: v for k, v in N._with_awg_gen(_h)["awg"].items() if k != "gen"} == _h["awg"])

SECTION[0] = "[5]"
print("\n[5] what a dict needs, and why a node refuses it")
check("a 2.0 dict needs nothing", N.awg_need({"Jc": "4", "S1": "20"}) is None)
check("RandomTrailers → 3.1", N.awg_need({"RandomTrailers": "1"}) == "3.1")
check("HeaderProtectionKey alone → 3.0", N.awg_need({"HeaderProtectionKey": "k"}) == "3.0")
check("a 3.x key at zero still counts (a 2.0 module refuses it)", N.awg_need({"ContentPaddingAddition": "0"}) == "3.0")
IF = "swgtest%d" % os.getpid()            # a device that does not exist here → the datapath awg-quick would pick
D31 = {"Jc": "4", "HeaderProtectionKey": "k", "RandomTrailers": "1"}
def refusal(gen, awg=D31, iface=IF):
    N.awg_gen_report = lambda now=None, g=gen: dict(g)
    return N.awg_gen_refusal(iface, awg)
check("a 3.1 node takes a 3.1 dict", refusal({"module": "3.1", "fallback": "3.0", "tools": "3.1"}) == "")
check("a 2.0 module refuses it, naming the module", "kernel module" in refusal({"module": "2.0", "fallback": "3.1", "tools": "3.1"}))
check("no module: the fallback decides, and names itself", "amneziawg-go" in refusal({"module": None, "fallback": "3.0", "tools": "3.1"}))
check("2.0 tools refuse it, naming the tools", "awg tools" in refusal({"module": "3.1", "fallback": "3.1", "tools": "2.0"}))
check("an unknown module is below everything", "kernel module" in refusal({"module": "unknown", "fallback": "3.1", "tools": "3.1"}))
check("a 2.0 dict is never refused, whatever the node", refusal({"module": "2.0", "fallback": None, "tools": "2.0"}, {"Jc": "4"}) == "")
check("a HPK-only (3.0) dict on a 3.0 datapath is let through", refusal({"module": "3.0", "fallback": None, "tools": "3.1"},
                                                                         {"HeaderProtectionKey": "k"}) == "")

SECTION[0] = "[6]"
print("\n[6] through the REAL reconcile_ifaces / create_ifaces")
AGENT_CALLS = []
N.run_agent = lambda agent, sudo, payload: AGENT_CALLS.append(payload) or {"ok": True, "data": {}}
N.current_listen_port = lambda cfg, iface: 51820
N.iface_mtu = lambda iface, info=None: 1280
CUR = {"Jc": "4"}
N.current_awg = lambda cfg, iface: dict(CUR)
N._conf_text = lambda cfg, iface: ""
cfg = {"interfaces": {IF: {"cmd": ["awg"], "conf": "/nonexistent"}}}
N.awg_gen_report = lambda now=None: {"module": "2.0", "fallback": "3.1", "tools": "3.1"}
N._OP_BACKOFF.clear()
for rnd in range(3):                       # three passes: a refusal must be the same, cheap, no-call answer every time
    r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4", **D31}}}, "agent", False)
check("a 3.1 set on a 2.0 module: the agent is NEVER called, three passes running", AGENT_CALLS == [], AGENT_CALLS)
check("…and the refusal is reported (it rides cmd_errors, keyed by the interface)",
      len(r["errors"]) == 1 and r["errors"][0].startswith("set-iface %s: not applied" % IF), r["errors"])
AGENT_CALLS.clear()
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4", **D31}, "listen_port": 51999}}, "agent", False)
check("a port change beside the refused set still goes — without the AWG part",
      len(AGENT_CALLS) == 1 and AGENT_CALLS[0].get("listen_port") == 51999 and "awg_params" not in AGENT_CALLS[0], AGENT_CALLS)
AGENT_CALLS.clear()
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "5"}}}, "agent", False)
check("control: a 2.0 set on the same node is today's call, unchanged",
      AGENT_CALLS == [{"op": "set-iface", "iface": IF, "awg_params": {"Jc": "5"}}] and not r["errors"], (AGENT_CALLS, r))
AGENT_CALLS.clear()
N.awg_gen_report = lambda now=None: {"module": "3.1", "fallback": "3.1", "tools": "3.1"}
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4", **D31}}}, "agent", False)
check("control: a 3.1 node gets the 3.1 set", len(AGENT_CALLS) == 1 and AGENT_CALLS[0].get("awg_params", {}).get("RandomTrailers") == "1",
      AGENT_CALLS)
AGENT_CALLS.clear()
N.awg_gen_report = lambda now=None: {"module": None, "fallback": "3.0", "tools": "3.1"}
N._persist_config = lambda cfg: None
cr = N.create_ifaces({"interfaces": {}}, {IF: {"cmd": ["awg"], "subnet": "10.63.0.0/24", "awg_params": {"Jc": "4", **D31}}},
                     "agent", False)
check("a 3.1 create on a 3.0 fallback: the agent is never called, the refusal is reported",
      AGENT_CALLS == [] and len(cr["errors"]) == 1 and "amneziawg-go" in cr["errors"][0], (AGENT_CALLS, cr))
cr = N.create_ifaces({"interfaces": {}}, {IF: {"cmd": ["awg"], "subnet": "10.63.0.0/24"}}, "agent", False)
check("control: a 2.0 create is sent as before", len(AGENT_CALLS) == 1 and AGENT_CALLS[0]["op"] == "create-iface", AGENT_CALLS)

SECTION[0] = "[7]"
print("\n[7] the panel reads a node with `gen` exactly as one without")
P = _load(PANEL, "panel_gen")
G = {"module": "3.1", "fallback": "3.1", "tools": "3.1"}
SHAPES = {"docker": ({"kind": "docker", "datapath": {}}, {"kind": "docker"}),
          "bare ok": ({"datapath": {"awg": {"needed": True, "ok": True}}}, {}),
          "degraded": ({"datapath": {"awg": {"needed": True, "ok": False, "fallback": True, "userspace": ["awg0"]}}}, {}),
          "broken": ({"datapath": {"awg": {"needed": True, "ok": False, "fallback": False}}}, {}),
          "no awg": ({"datapath": {}}, {})}
for name, (snap, c) in SHAPES.items():
    s1 = {"interfaces": {}, **snap}
    s2 = {"interfaces": {}, **snap, "datapath": {**snap["datapath"], "awg": {**(snap["datapath"].get("awg") or {}), "gen": G}}}
    same_issues = P._node_issues(c, s1) == P._node_issues(c, s2)
    a1, a2 = P._awg_datapath(s1), P._awg_datapath(s2)
    same_flags = all(a1.get(k) == a2.get(k) for k in ("needed", "ok", "fallback", "userspace"))
    check("%s: same issues and the same datapath flags" % name, same_issues and same_flags, (P._node_issues(c, s1), P._node_issues(c, s2)))

SECTION[0] = "[8]"
print("\n[8] the presence compare needs the panel's word, and passes it on")
N.awg_gen_report = lambda now=None: {"module": "3.1", "fallback": "3.1", "tools": "3.1"}
CUR.clear(); CUR.update({"Jc": "4", "HeaderProtectionKey": "k", "RandomTrailers": "1"})
AGENT_CALLS.clear(); N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4"}}}, "agent", False)
check("an older panel's 2.0-only set that matches on its keys → no set-iface (the 3.x keys stay)", AGENT_CALLS == [], AGENT_CALLS)
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4"}, "awg_params_exact": True}}, "agent", False)
check("the same set marked whole → set-iface (a switch back)", len(AGENT_CALLS) == 1, AGENT_CALLS)
check("…carrying awg_params_exact, so the agent drops the 3.x keys", (AGENT_CALLS[:1] or [{}])[0].get("awg_params_exact") is True, AGENT_CALLS)
AGENT_CALLS.clear()
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "5"}}}, "agent", False)
check("an older panel's Jc edit is sent WITHOUT the flag (the agent then keeps the 3.x keys)",
      len(AGENT_CALLS) == 1 and "awg_params_exact" not in AGENT_CALLS[0], AGENT_CALLS)

SECTION[0] = "[9]"
print("\n[9] a conf with a 3.1 kernel's unset lines reads as 2.0")
ZCONF = ("[Interface]\nPrivateKey = x\nAddress = 10.9.0.1/24\nJc = 4\nS1 = 20\nContentPaddingAddition = 0\nRekeyAfterTime = 0\n"
         "RekeyTimeout = 0\nRejectAfterTime = 0\nKeepaliveTimeout = 0\nMaxHandshakeAttempts = 0\nRandomTrailers = off\n"
         "DisableCookies = off\n\n[Peer]\nPublicKey = y\n")
rep9 = N.awg_params(N.parse_interface_section(ZCONF))
check("the report carries no 3.x key", not any(k in rep9 for k in N.AWG3_KEYS), rep9)
check("…and every 2.0 key", rep9 == {"Jc": 4, "S1": 20}, rep9)
check("a real setting is still one (HPK, RandomTrailers = 1)", set(N.awg_params({"HeaderProtectionKey": "k", "RandomTrailers": "1"})) ==
      {"HeaderProtectionKey", "RandomTrailers"})
CUR.clear(); CUR.update(rep9)
AGENT_CALLS.clear(); N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "4", "S1": "20"}, "awg_params_exact": True}}, "agent", False)
check("the same 2.0 set, even marked whole → no set-iface", AGENT_CALLS == [], AGENT_CALLS)

SECTION[0] = "[10]"
print("\n[10] a refused recreate is not retried with the same set")
CUR.clear(); CUR.update({"Jc": "4", "HeaderProtectionKey": "k", "RandomTrailers": "1"})
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear(); AGENT_CALLS.clear()
N.run_agent = lambda agent, sudo, payload: AGENT_CALLS.append(payload) or {"ok": False, "code": "awg_gen_refused",
                                                                           "error": "this node's AmneziaWG refused the change"}
_t = [1000.0]
N.time.monotonic = lambda: _t[0]
want10 = {IF: {"awg_params": {"Jc": "9", "HeaderProtectionKey": "k", "RandomTrailers": "1"}}}
for _ in range(4):                          # well past the backoff's first steps (10 s, 20 s, 40 s …)
    r = N.reconcile_ifaces(cfg, want10, "agent", False)
    _t[0] += 400
check("the agent is called once for the refused set, not on every backoff step", len(AGENT_CALLS) == 1, len(AGENT_CALLS))
check("…and the refusal is still reported, without promising a retry",
      r["errors"] and "refused the change" in r["errors"][0] and "retrying" not in r["errors"][0], r["errors"])
N.run_agent = lambda agent, sudo, payload: AGENT_CALLS.append(payload) or {"ok": True, "data": {}}
r = N.reconcile_ifaces(cfg, {IF: {"awg_params": {"Jc": "8", "HeaderProtectionKey": "k", "RandomTrailers": "1"}}}, "agent", False)
check("a changed set is tried at once", len(AGENT_CALLS) == 2 and not r["errors"], (len(AGENT_CALLS), r["errors"]))

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
