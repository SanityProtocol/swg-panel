#!/usr/bin/env python3
"""Self-test for the sub page's torrent line (1.8.11 S4b) — swg-sub `p2p_policy`, `torrents_allowed` and the `p2p` flag
read_data puts on a deployment. The page draws the line where the flag is (tests/sub_page_render_selftest.py [12]); this
holds the flag to the node's own rule: the node-wide policy is not Block AND the deployment's record does not block
"torrents" (strictest wins, P2P-POLICY §2.2).

  [1] parity with swg-panel-server: P2P_ACTIONS equal, p2p_policy answers the same on every node shape, and the two
      functions are the same statements (docstrings aside) — swg-sub copies the panel's reader, it cannot import it
  [2] torrents_allowed: Block (saved or absent) allows nothing; any other policy allows every deployment whose own record
      — the interface for wg/awg, the WDTT or csqtt server for those — does not block "torrents"; no record = allowed;
      junk shapes answer without an exception
  [3] read_data: `"p2p": true` on exactly the allowed deployments of a live device; none on a blocked or expired device;
      and a fleet that blocks torrents serves no "p2p" key at all (its payload is the last release's)

Hermetic. Run: python3 tests/sub_p2p_hint_selftest.py            (0 = pass)
     --perturb          swg-sub's p2p_policy defaults to iface instead of block → RED on [1], [2] and [3]
     --perturb-record   torrents_allowed reads every deployment's record from the interfaces → RED on [2] and [3]
"""
import ast, hashlib, importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
P_POLICY = "--perturb" in sys.argv
P_RECORD = "--perturb-record" in sys.argv
PERTURB = P_POLICY or P_RECORD

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
    plant('node_cfg.get({"wdtt": "wdtt", "csqtt": "csqtt"}.get(t.get("type") or "", "ifaces"))', 'node_cfg.get("ifaces")',
          "the record a deployment lands on")
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

# ── [2] torrents_allowed ───────────────────────────────────────────────────────────────────────────────────────────────
print("[2] torrents_allowed")
RECS = {"ifaces": {"wg0": {"block": ["ads", "torrents"]}, "wg1": {"block": ["ads"]}, "awg0": {"block": [" torrents "]}},
        "wdtt": {"w1": {"block": ["torrents"]}, "w2": {}, "wg1": {"block": ["torrents"]}},
        "csqtt": {"c1": {"block": ["torrents"]}, "c2": {"block": None}}}
T = lambda iface, ty="wg": {"node": "n1", "iface": iface, "type": ty}
WANT = [(T("wg0"), False), (T("wg1"), True), (T("wg9"), True), (T("awg0", "awg"), False), (T("wg1", "awg"), True),
        (T("w1", "wdtt"), False), (T("w2", "wdtt"), True), (T("wg1", "wdtt"), False),   # a WDTT server's record, not wg1's
        (T("c1", "csqtt"), False), (T("c2", "csqtt"), True), (T("wg0", "csqtt"), True)]
for pol in (None, "block"):
    node = dict(RECS, **({"p2p": {"action": pol}} if pol else {}))
    got = [tg for tg, _ in WANT if S.torrents_allowed(node, tg)]
    check("policy %s: no deployment allowed" % (pol or "absent (= block)"), not got, got)
for pol in ("direct", "iface", "exit", "dev"):
    node = dict(RECS, p2p={"action": pol})
    bad = [(tg["type"], tg["iface"], want) for tg, want in WANT if S.torrents_allowed(node, tg) != want]
    check("policy %s: allowed exactly where the deployment's own record does not block torrents" % pol, not bad, bad)
JUNK = [None, [], "x", {"p2p": {"action": "direct"}, "ifaces": []}, {"p2p": {"action": "direct"}, "ifaces": {"wg0": "x"}},
        {"p2p": {"action": "direct"}, "ifaces": {"wg0": {"block": "torrents"}}}, {"p2p": {"action": "direct"}, "wdtt": None}]
errs = []
for n in JUNK:
    for tg in (T("wg0"), T("w1", "wdtt"), {"iface": None}, {}):
        try:
            S.torrents_allowed(n, tg)
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
