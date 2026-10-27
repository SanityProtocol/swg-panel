#!/usr/bin/env python3
"""Self-test for the sub page's torrent line (1.8.11 S4b) — swg-sub `p2p_policy`, `torrents_allowed` and the `p2p` flag
read_data puts on a deployment. The page draws the line where the flag is (tests/sub_page_render_selftest.py [12]); this
holds the flag to the node's own rule: the node-wide policy is not Block AND the deployment's record does not block
"torrents" (strictest wins, P2P-POLICY §2.2).

  [1] parity with swg-panel-server: P2P_ACTIONS equal, p2p_policy answers the same on every node shape, and the two
      functions are the same statements (docstrings aside) — swg-sub copies the panel's reader, it cannot import it
  [2] torrents_allowed: Block (saved or absent) allows nothing; any other policy allows every deployment whose own record
      — the interface for wg/awg, the WDTT or csqtt server for those — does not block "torrents"; no record = allowed;
      junk shapes answer without an exception. What the node RUNS outranks what is saved: a node reporting mode block (a
      Route it could not lower) or its route down allows nothing (review F1). Where the policy hands P2P to another node —
      a Route to a node, or per-interface on an interface forwarded whole — that node must let arrivals' P2P out: Direct or
      per-interface, not Block, not a Route of its own, not reporting block (F2)
  [3] read_data: `"p2p": true` on exactly the allowed deployments of a live device; none on a blocked or expired device;
      and a fleet that blocks torrents serves no "p2p" key at all (its payload is the last release's)

Hermetic. Run: python3 tests/sub_p2p_hint_selftest.py            (0 = pass)
     --perturb          swg-sub's p2p_policy defaults to iface instead of block → RED on [1], [2] and [3]
     --perturb-record   torrents_allowed reads every deployment's record from the interfaces → RED on [2] and [3]
     --perturb-report   the node's own report is ignored (a Route run as Block reads as allowed) → RED on [2]
     --perturb-farnode  a Route to a node is allowed whatever that node runs → RED on [2]
     --perturb-own      an interface's own torrent choice is not read under per-interface (S11) → RED on [2]
     --perturb-routedown a routed interface is allowed while the node reports a route down (s11-pick F2) → RED on [2]
     --perturb-alldown  a named device down blocks every routed interface (backlog F48) → RED on [2]
"""
import ast, hashlib, importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
P_POLICY = "--perturb" in sys.argv
P_RECORD = "--perturb-record" in sys.argv
P_REPORT = "--perturb-report" in sys.argv
P_FAR = "--perturb-farnode" in sys.argv
P_OWN = "--perturb-own" in sys.argv
P_RDOWN = "--perturb-routedown" in sys.argv
P_ALLDOWN = "--perturb-alldown" in sys.argv
PERTURB = P_POLICY or P_RECORD or P_REPORT or P_FAR or P_OWN or P_RDOWN or P_ALLDOWN

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    m.__dict__["__file__"] = path
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m

src = open(SUB).read()
def plant(old, new, what):
    global src
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: its anchor is not in swg-sub exactly once (%d)" % (what, src.count(old)))
        sys.exit(1)
    src = src.replace(old, new)
if P_POLICY:
    plant('        return v["action"]\n    return "block"\n', '        return v["action"]\n    return "iface"\n', "p2p_policy's default")
if P_RECORD:
    plant('cfg.get(_P2P_RECS.get(t.get("type") or "", "ifaces"))', 'cfg.get("ifaces")', "the record a deployment lands on")
if P_REPORT:
    plant('rep.get("mode") == "block" or (rep.get("route") == "down" and pol in ("exit", "dev"))', 'False', "the node's own report")
if P_FAR:
    plant('        return _p2p_runs(nodes, describe, (cfg.get("p2p") or {}).get("node"), arrivals=True)', '        return True',
          "the far node of a Route")
if P_OWN:
    plant('    _rp = rec.get("p2p") if pol == "iface" and isinstance(rec.get("p2p"), dict) else {}', '    _rp = {}', "the record's own choice")
if P_RDOWN:
    plant('    if _rp.get("action") in ("exit", "dev") and _rep.get("route") == "down":',
          '    if False:', "a routed interface while a route is down")
if P_ALLDOWN:
    plant('        if not isinstance(_rep.get("down"), list) or _p2p_route_dev(cfg, _rp) in _rep["down"]:   # (no device: refused below)',
          '        if True:', "the routed interface's own device")
SUB_PATH = SUB
if PERTURB:
    fd, SUB_PATH = tempfile.mkstemp(prefix="swg-sub-perturbed-")
    with os.fdopen(fd, "w") as f:
        f.write(src)
S = load("swgsub_p2p", SUB_PATH)
P = load("swgpanel_p2p", PANEL)
if PERTURB:
    os.unlink(SUB_PATH)

# ── [1] parity ─────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] parity with swg-panel-server")
check("P2P_ACTIONS are the panel's", S.P2P_ACTIONS == P.P2P_ACTIONS, (S.P2P_ACTIONS, P.P2P_ACTIONS))
SHAPES = [{}, {"p2p": None}, {"p2p": "direct"}, {"p2p": []}, {"p2p": {}}, {"p2p": {"action": None}}, {"p2p": {"action": ""}},
          {"p2p": {"action": "DIRECT"}}, {"p2p": {"action": "route"}}] + [{"p2p": {"action": a}} for a in P.P2P_ACTIONS]
diff = [(n, S.p2p_policy(n), P.p2p_policy(n)) for n in SHAPES if S.p2p_policy(n) != P.p2p_policy(n)]
check("p2p_policy answers as the panel's on %d node shapes" % len(SHAPES), not diff, diff)
def body(text, fn):
    f = next(x for x in ast.parse(text).body if isinstance(x, ast.FunctionDef) and x.name == fn)
    stmts = f.body[1:] if f.body and isinstance(f.body[0], ast.Expr) and isinstance(getattr(f.body[0], "value", None), ast.Constant) else f.body
    return [ast.dump(s) for s in stmts]
check("p2p_policy is the panel's, statement for statement", body(src, "p2p_policy") == body(open(PANEL).read(), "p2p_policy"))
check("_p2p_route_dev is the panel's p2p_route_dev, statement for statement (the node names these devices in `down`)",
      body(src, "_p2p_route_dev") == body(open(PANEL).read(), "p2p_route_dev"))

# ── [2] torrents_allowed ───────────────────────────────────────────────────────────────────────────────────────────────
print("[2] torrents_allowed")
RECS = {"ifaces": {"wg0": {"block": ["ads", "torrents"]}, "wg1": {"block": ["ads"]}, "awg0": {"block": [" torrents "]}},
        "wdtt": {"w1": {"block": ["torrents"]}, "w2": {}, "wg1": {"block": ["torrents"]}},
        "csqtt": {"c1": {"block": ["torrents"]}, "c2": {"block": None}}}
T = lambda iface, ty="wg": {"node": "n1", "iface": iface, "type": ty}
WANT = [(T("wg0"), False), (T("wg1"), True), (T("wg9"), True), (T("awg0", "awg"), False), (T("wg1", "awg"), True),
        (T("w1", "wdtt"), False), (T("w2", "wdtt"), True), (T("wg1", "wdtt"), False),   # a WDTT server's record, not wg1's
        (T("c1", "csqtt"), False), (T("c2", "csqtt"), True), (T("wg0", "csqtt"), True)]
def allowed(n1, n2=None, d1=None, d2=None, tgs=None):
    nodes = {"n1": n1, **({"n2": n2} if n2 is not None else {})}
    desc = {"n1": {"p2p": d1 or {}}, "n2": {"p2p": d2 or {}}}
    return [tg for tg, _ in (tgs or WANT) if S.torrents_allowed(nodes, desc, tg)]
for pol in (None, "block"):
    got = allowed(dict(RECS, **({"p2p": {"action": pol}} if pol else {})))
    check("policy %s: no deployment allowed" % (pol or "absent (= block)"), not got, got)
FAR = {"p2p": {"action": "direct"}}
for pol in ("direct", "iface", "exit", "dev"):
    node = dict(RECS, p2p={"action": pol, **({"node": "n2"} if pol == "exit" else {})})
    got = allowed(node, FAR)
    bad = [(tg["type"], tg["iface"], want) for tg, want in WANT if (tg in got) != want]
    check("policy %s: allowed exactly where the deployment's own record does not block torrents" % pol, not bad, bad)
DIRECT = dict(RECS, p2p={"action": "direct"})
check("F1: a node REPORTING mode block (a Route it could not lower) allows nothing", not allowed(DIRECT, d1={"mode": "block"}))
check("F1: …nor one whose route is down", not allowed(dict(RECS, p2p={"action": "exit", "node": "n2"}), FAR, d1={"mode": "route", "route": "down"}))
check("F1: a node reporting what it was told (direct) is as saved", allowed(DIRECT, d1={"mode": "direct", "state": "ok"}) == allowed(DIRECT))
TO2 = dict(RECS, p2p={"action": "exit", "node": "n2"})
for far, d2, ok in (({}, None, False), ({"p2p": {"action": "block"}}, None, False), ({"p2p": {"action": "exit", "node": "n1"}}, None, False),
                    ({"p2p": {"action": "dev", "exit_id": "x"}}, None, False), ({"p2p": {"action": "direct"}}, {"mode": "block"}, False),
                    ({"p2p": {"action": "direct"}}, None, True), ({"p2p": {"action": "iface"}}, None, True)):
    got = allowed(TO2, far, d2=d2)
    check("F2: a Route to n2 that %s — %s" % (json.dumps(far.get("p2p") or "no policy") + (" reporting block" if d2 else ""),
                                              "allowed by the records" if ok else "allows nothing"),
          bool(got) == ok and (not ok or got == allowed(DIRECT)), got)
FWD = {"p2p": {"action": "iface"}, "ifaces": {"wgf": {"egress_mode": "forward", "egress_node": "n2"}, "wgd": {}}}
TF = [(T("wgf"), None), (T("wgd"), None)]
check("F2: per-interface, an interface forwarded whole to a node under Block: no; the direct one beside it: yes",
      allowed(FWD, {}, tgs=TF) == [T("wgd")], allowed(FWD, {}, tgs=TF))
check("F2: …forwarded to a node under Direct: both", allowed(FWD, FAR, tgs=TF) == [T("wgf"), T("wgd")], allowed(FWD, FAR, tgs=TF))
# S11 (review F4): under per-interface, the record's own choice decides; one interface's route down is not the node's
IF = lambda **r: {"p2p": {"action": "iface"}, "links": {"n2": {"iface": "swg_b"}},
                  "exits": [{"id": "e1", "enabled": True}, {"id": "e2", "enabled": False}], "ifaces": {"wgr": r}}
TR = [(T("wgr"), None)]
for name, rec, far, want in (("its own route to a node letting arrivals out", {"p2p": {"action": "exit", "node": "n2"}}, FAR, True),
                             ("its own route to a node under Block", {"p2p": {"action": "exit", "node": "n2"}}, {}, False),
                             ("its own route to a node it has no link to", {"p2p": {"action": "exit", "node": "n3"}}, FAR, False),
                             ("its own route through an exit that is on", {"p2p": {"action": "dev", "exit_id": "e1"}}, {}, True),
                             ("its own route through an exit switched off", {"p2p": {"action": "dev", "exit_id": "e2"}}, {}, False),
                             ("Direct, though forwarded whole to a node under Block", {"p2p": {"action": "direct"}, "egress_mode": "forward", "egress_node": "n2"}, {}, True)):
    check("S11: per-interface, %s → %s" % (name, "allowed" if want else "not"), bool(allowed(IF(**rec), far, tgs=TR)) == want)
check("S11: per-interface, one interface's route down (the node reports route down) is not the node's — a Direct one is allowed",
      bool(allowed(IF(p2p={"action": "direct"}), FAR, d1={"mode": "iface", "route": "down"}, tgs=TR)))
check("S11 (pick F2): …but a ROUTED one is not (the node names no group; fail closed)",
      not allowed(IF(p2p={"action": "dev", "exit_id": "e1"}), FAR, d1={"mode": "iface", "route": "down"}, tgs=TR)
      and not allowed(IF(p2p={"action": "exit", "node": "n2"}), FAR, d1={"mode": "iface", "route": "down"}, tgs=TR))
# backlog F48: the node names the devices down (`down`) — only an interface whose own route leaves by one is not allowed
IF2 = {"p2p": {"action": "iface"}, "links": {"n2": {"iface": "swg_b"}}, "exits": [{"id": "e1", "enabled": True, "device": "wgx-e1"}],
       "ifaces": {"wgx": {"p2p": {"action": "dev", "exit_id": "e1"}}, "wgn": {"p2p": {"action": "exit", "node": "n2"}}}}
T2 = [(T("wgx"), None), (T("wgn"), None)]
check("F48: the exit's device down → the interface routed through it is not allowed, the one through a node is",
      allowed(IF2, FAR, d1={"mode": "iface", "route": "down", "down": ["wgx-e1"]}, tgs=T2) == [T("wgn")],
      allowed(IF2, FAR, d1={"mode": "iface", "route": "down", "down": ["wgx-e1"]}, tgs=T2))
check("F48: the link to the node down → the other way round",
      allowed(IF2, FAR, d1={"mode": "iface", "route": "down", "down": ["swg_b"]}, tgs=T2) == [T("wgx")],
      allowed(IF2, FAR, d1={"mode": "iface", "route": "down", "down": ["swg_b"]}, tgs=T2))
IF3 = dict(IF2, exits=[{"id": "e1", "enabled": False, "device": "wgx-e1"}])
check("F48 (review F1): a route through a disabled exit — no device to leave by — is not allowed, whatever device is down",
      T("wgx") not in allowed(IF3, FAR, d1={"mode": "iface", "route": "down", "down": ["swg_b"]}, tgs=T2))
IF4 = dict(IF2, exits=[{"id": "e1", "enabled": True, "device": " wgx-e1 "}])
check("F48 (review F1): a device stored with stray spaces is the node's name for it (resolve_exit strips)",
      T("wgx") not in allowed(IF4, FAR, d1={"mode": "iface", "route": "down", "down": ["wgx-e1"]}, tgs=T2))
check("F48: a node that names no device → neither (fail closed, as before)",
      allowed(IF2, FAR, d1={"mode": "iface", "route": "down"}, tgs=T2) == [])
JUNK = [None, [], "x", {"p2p": {"action": "direct"}, "ifaces": []}, {"p2p": {"action": "direct"}, "ifaces": {"wg0": "x"}},
        {"p2p": {"action": "direct"}, "ifaces": {"wg0": {"block": "torrents"}}}, {"p2p": {"action": "direct"}, "wdtt": None}]
errs = []
for n in JUNK:
    for tg in (T("wg0"), T("w1", "wdtt"), {"iface": None}, {}):
        try:
            S.torrents_allowed({"n1": n}, {"n1": {"p2p": n}}, tg)
        except Exception as e:
            errs.append((n, tg, repr(e)))
check("junk node / record / target shapes answer without an exception", not errs, errs[:3])

# ── [3] read_data ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] read_data")
TOKEN = "tok-p2p-hint"
USERS = {"u1": {"enabled": True, "token_sha": hashlib.sha256(TOKEN.encode()).hexdigest()}}
ROSTER = {"users": {"u1": {"name": "Anna"}},
          "peers": {"live": {"id": "live", "user_id": "u1", "title": "laptop",
                             "targets": [{"node": "n1", "iface": "wg0", "type": "wg", "ip": "10.8.0.2/32"},
                                         {"node": "n1", "iface": "wg1", "type": "wg", "ip": "10.7.0.2/32"},
                                         {"node": "n1", "iface": "w2", "type": "wdtt"},
                                         {"node": "n1", "iface": "c1", "type": "csqtt"},
                                         {"node": "n1", "iface": "c2", "type": "csqtt"}]},
                    "off": {"id": "off", "user_id": "u1", "title": "old tablet", "disabled": True,
                            "targets": [{"node": "n1", "iface": "wg1", "type": "wg", "ip": "10.7.0.9/32"}]},
                    "late": {"id": "late", "user_id": "u1", "title": "old phone", "expiry": 1,
                             "targets": [{"node": "n1", "iface": "wg1", "type": "wg", "ip": "10.7.0.8/32"}]}}}
DESC = {"n1": {"ifaces": {"wg0": {"subnet": "10.8.0.0/24"}, "wg1": {"subnet": "10.7.0.0/24"}}, "turn": [], "pub_host": "203.0.113.7",
               "tver": {}, "tline": {}, "net_carried": []}}

class State:
    def enabled(self): return True
    def subscriptions(self): return {"enabled": True}
    def sub_blobs(self, uid): return {}

def read(nodes):
    S._shared_read = lambda st: (ROSTER, DESC, USERS, nodes)
    return S.read_data(State(), TOKEN)

check("fixture: the expired device reads as expired (its date is in the past)", S.is_expired(ROSTER["peers"]["late"], 2))
d = read({"n1": dict(RECS, name="q-node", p2p={"action": "direct"})})
by = {po["title"]: {(tg["type"], tg["iface"]): tg.get("p2p") for tg in po["targets"]} for po in (d or {}).get("peers", [])}
check("a live device: p2p on wg1 and the WDTT w2 and csqtt c2, absent on wg0 and csqtt c1 (their records block torrents)",
      by.get("laptop") == {("wg", "wg0"): None, ("wg", "wg1"): True, ("wdtt", "w2"): True, ("csqtt", "c1"): None, ("csqtt", "c2"): True},
      by.get("laptop"))
check("a blocked device and an expired one: no p2p on their deployments (the page draws no line on a dead end)",
      by.get("old tablet") == {("wg", "wg1"): None} and by.get("old phone") == {("wg", "wg1"): None}, (by.get("old tablet"), by.get("old phone")))
blocking = json.dumps(read({"n1": dict(RECS, name="q-node")}))
check("a node that blocks torrents (no policy saved): no \"p2p\" key anywhere in the payload", '"p2p"' not in blocking,
      blocking[:200])

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red" % len(FAILS)) if ok else "PERTURB FAILED — the plant was served and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
