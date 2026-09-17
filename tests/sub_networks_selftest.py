#!/usr/bin/env python3
"""Self-test for the subscription page's "Networks you can reach" (docs/NETWORKS-PLAN.md §18) — swg-sub `sub_networks`.

  [1] an open network: listed for every user with a device on that node; `covered` from that device's own config, the
      device that routes it winning; a keyless-only user's is unknown (None), never assumed
  [2] a restricted network: its owner and live grantees only, through a KEYED device only; `via` names the provider
  [3] only what the node REPORTS routing: nothing from a node without net_carried, nothing it doesn't list
  [4] a device's own networks aren't listed for it; the owner's other devices reach them
  [5] a blocked provider, an expired provider's owner, a blocked user: nothing
  [6] one prefix on two providers: the one the panel's node_networks picks (earliest created_at) is the one judged
  [7] parity with swg-panel-server: share_grants and _allowed_covers answer the same on every fixture
  [8] read_data carries the list
  [9] a network shared with a GROUP (docs/GROUPS-PLAN.md G5, G10): its members (through a keyed device) and nobody else; a
      member removed, a group deleted, a group grant lapsed — nothing; a member also granted by name keeps the widest date
      [7] also compares the two share_grants' SOURCE, statement for statement (docstrings aside), with groups in the fixtures

Hermetic. Run: python3 tests/sub_networks_selftest.py            (0 = pass)
     --perturb          makes every network open (share_grants → None) and expects RED on [2] and [6].
     --perturb-groups   has swg-sub's share_grants ignore group grants and expects RED on [7] and [9].
"""
import ast, importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_GROUPS = "--perturb-groups" in sys.argv

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
S = load("swgsub", SUB)
P = load("swgpanel", PANEL)
_real_grants = S.share_grants
if PERTURB:
    S.share_grants = lambda p, users, nowv, groups: None
if PERTURB_GROUPS:
    S.share_grants = lambda p, users, nowv, groups: _real_grants(p, users, nowv, None)

NOW = 1_000_000
T = lambda ip, node="n1", **k: dict({"node": node, "iface": "wg0", "ip": ip, "type": "wg"}, **k)
def roster(share=None, **edits):
    r = {"users": {"u1": {"name": "Alice"}, "u2": {"name": "Bob"}, "u3": {"name": "Carol"}, "u4": {"name": "Dave"},
                   "u5": {"name": "Eve"}, "u6": {"name": "Frank"}},
         "peers": {
             "gw": {"id": "gw", "user_id": "u1", "created_at": 10, "title": "office router", "targets": [T("10.8.0.10")],
                    "routes": ["192.168.50.0/24"]},
             "aPhone": {"id": "aPhone", "user_id": "u1", "created_at": 11, "targets": [T("10.8.0.20")]},
             "bPhone": {"id": "bPhone", "user_id": "u2", "created_at": 12, "targets": [T("10.8.0.21")]},
             "bLaptop": {"id": "bLaptop", "user_id": "u2", "created_at": 13, "targets": [T("10.8.0.22", overrides={"allowed": "10.8.0.0/24"})]},
             "cPhone": {"id": "cPhone", "user_id": "u3", "created_at": 14, "targets": [T("10.8.0.23")]},
             "dPhone": {"id": "dPhone", "user_id": "u4", "created_at": 15, "targets": [T("10.8.0.24")]},
             "eTurn": {"id": "eTurn", "user_id": "u5", "created_at": 16, "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
             "fLaptop": {"id": "fLaptop", "user_id": "u6", "created_at": 17, "targets": [T("10.8.0.26", overrides={"allowed": "10.8.0.0/24"})]},
         }}
    if share is not None:
        r["peers"]["gw"]["share"] = share
    for pid, fields in edits.items():
        if fields is None:
            r["peers"].pop(pid, None)
        elif pid.startswith("user:"):
            r["users"][pid[5:]].update(fields)
        else:
            r["peers"].setdefault(pid, {"id": pid}).update(fields)
    return r
DESC = {"n1": {"ifaces": {"wg0": {"subnet": "10.8.0.0/24"}}, "net_carried": ["192.168.50.0/24"]},
        "n2": {"ifaces": {"wg0": {"subnet": "10.9.0.0/24"}}, "net_carried": []}}
NODES = {"n1": {"name": "home-node"}, "n2": {"name": "edge"}}
nets = lambda r, uid, desc=DESC: S.sub_networks(r, uid, desc, NODES, NOW)
ROW = lambda covered, via="": [{"prefix": "192.168.50.0/24", "node_name": "home-node", "via": via, "covered": covered}]

print("\n[1] an open network")
R = roster()
check("Bob (full-tunnel phone + narrowed laptop): one row, covered — the device that routes it wins", nets(R, "u2") == ROW(True), nets(R, "u2"))
check("Carol, not the owner: an open network is everyone's on the node, and names no provider", nets(R, "u3") == ROW(True), nets(R, "u3"))
check("Eve, a keyless device only: listed, covered unknown (None)", nets(R, "u5") == ROW(None), nets(R, "u5"))
check("Frank, a narrowed device only: listed, covered False", nets(R, "u6") == ROW(False), nets(R, "u6"))

print("\n[2] a restricted network")
R = roster(share={"users": {"u2": 0, "u4": NOW - 1, "u5": 0, "ghost": 0}})
check("the owner's other device: listed, via the router", nets(R, "u1") == ROW(True, "office router"), nets(R, "u1"))
check("a grantee: listed, via the router", nets(R, "u2") == ROW(True, "office router"), nets(R, "u2"))
check("a non-grantee: nothing", nets(R, "u3") == [], nets(R, "u3"))
check("a grant whose date has passed: nothing", nets(R, "u4") == [], nets(R, "u4"))
check("a grantee whose only device is keyless: nothing (never promised)", nets(R, "u5") == [], nets(R, "u5"))
check("owner only ({users: {}}): the owner's phone yes, Bob no",
      nets(roster(share={"users": {}}), "u1") == ROW(True, "office router") and nets(roster(share={"users": {}}), "u2") == [])

print("\n[3] only what the node reports routing")
R = roster()
check("a node without net_carried (old, or routing nothing): nothing", nets(R, "u2", dict(DESC, n1=dict(DESC["n1"], net_carried=[]))) == [])
check("a node that routes something else: nothing", nets(R, "u2", dict(DESC, n1=dict(DESC["n1"], net_carried=["10.20.0.0/16"]))) == [])
check("a device on another node reaches nothing there", nets(roster(bPhone={"targets": [T("10.9.0.21", node="n2")]}, bLaptop=None), "u2") == [])
check("a /32 stored bare still matches the node's spelling", nets(roster(gw={"routes": ["172.30.9.9"]}), "u2",
      dict(DESC, n1=dict(DESC["n1"], net_carried=["172.30.9.9/32"])))[0]["prefix"] == "172.30.9.9/32")

print("\n[4] a device's own networks")
check("the router's owner with only the router: nothing listed for it", nets(roster(aPhone=None), "u1") == [], nets(roster(aPhone=None), "u1"))

print("\n[5] blocked and expired")
check("a blocked provider: nothing", nets(roster(gw={"disabled": True}), "u2") == [])
check("a provider whose owner has expired: nothing", nets(roster(**{"user:u1": {"expiry": NOW - 5}}), "u2") == [])
check("a blocked user's own list: nothing", nets(roster(**{"user:u2": {"disabled": True}}), "u2") == [])

print("\n[6] one prefix, two providers")
R = roster(gw2={"id": "gw2", "user_id": "u3", "created_at": 5, "title": "carol's box", "targets": [T("10.8.0.30")],
                "routes": ["192.168.50.0/24"], "share": {"users": {}}})
check("the earlier provider is the one the node routes: its owner sees it via their box", nets(R, "u3") == ROW(True, "carol's box"), nets(R, "u3"))
check("…and Bob, not granted on THAT provider, sees nothing — the open later one is never judged", nets(R, "u2") == [], nets(R, "u2"))
check("…and it matches the panel's own pick", list(P.node_networks(R, "n1", {"interfaces": {}, "node_ips": [], "net_deps": {
      "panel": "", "resolvers": [], "resolvers_known": True, "share": 1}})["carry"]) == ["gw2"])

print("\n[7] parity with swg-panel-server")
USERS = roster()["users"]
GROUPS = {"g1": {"name": "family", "users": ["u3", "u4", "ghost"]}, "g2": {"name": "work", "users": ["u3", 7]}, "gx": "junk",
          "g3": {"name": "bad", "users": "u2"}}
for sh in (None, {"users": {}}, {"users": {"u2": 0, "u3": NOW + 50, "u4": NOW - 1, "ghost": 0, "u5": True, "u6": -3}}, {"x": 1}, "open",
           {"users": {"u3": NOW + 50}, "groups": {"g1": 0}}, {"users": {"u4": 0}, "groups": {"g1": NOW - 1, "g2": NOW + 9}},
           {"users": {}, "groups": {"g1": NOW + 9, "g2": NOW + 20, "gone": 0, "gx": 0, "g3": 0}}, {"users": {}, "groups": "bad"}):
    for owner in ("u1", None, "gone"):
        for groups in (GROUPS, None, {}):
            p = {"user_id": owner, "share": sh}
            check("share_grants(%r, owner=%r, groups=%s)" % (sh, owner, "set" if groups else groups),
                  S.share_grants(p, USERS, NOW, groups) == P.share_grants(p, USERS, NOW, groups),
                  (S.share_grants(p, USERS, NOW, groups), P.share_grants(p, USERS, NOW, groups)))
def _body(path, name):
    """A function's AST with its docstring cut — what it DOES, not how it explains itself."""
    fn = next(n for n in ast.parse(open(path).read()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) and isinstance(fn.body[0].value.value, str):
        fn.body = fn.body[1:]
    return ast.dump(fn)
check("share_grants: swg-sub's copy is the panel's, statement for statement (docstrings aside)",
      _body(SUB, "share_grants") == _body(PANEL, "share_grants"))
for allowed in ("0.0.0.0/0, ::/0", "10.8.0.0/24", "192.168.0.0/16,10.0.0.0/8", "junk, 192.168.50.0/24", ""):
    for pre in ("192.168.50.0/24", "10.8.0.0/24", "172.30.9.9/32"):
        check("_allowed_covers(%r, %s)" % (allowed, pre), S._allowed_covers(allowed, pre) == P._allowed_covers(allowed, pre))

print("\n[8] read_data carries it")
src = open(SUB).read()
body = src[src.index("def read_data("):]
check('read_data returns "networks" from sub_networks', bool(re.search(r'"networks":\s*sub_networks\(roster, uid, describe, nodes, nowv\)', body)))
check("describe mirrors the node's net_carried", '"net_carried": snap.get("net_carried")' in src)

print("\n[9] a network shared with a group")
def groups_roster(share, members):
    r = roster(share=share)
    if members is not None:
        r["groups"] = {"g1": {"name": "family", "users": members}}
    return r
R = groups_roster({"users": {}, "groups": {"g1": 0}}, ["u3", "u4", "u5", "ghost"])
check("a member: listed, via the router", nets(R, "u3") == ROW(True, "office router"), nets(R, "u3"))
check("another member: listed", nets(R, "u4") == ROW(True, "office router"), nets(R, "u4"))
check("not a member: nothing", nets(R, "u2") == [], nets(R, "u2"))
check("a member whose only device is keyless: nothing (never promised)", nets(R, "u5") == [], nets(R, "u5"))
check("the owner still: listed", nets(R, "u1") == ROW(True, "office router"), nets(R, "u1"))
R = groups_roster({"users": {}, "groups": {"g1": 0}}, ["u4"])
check("a member removed from the group: nothing", nets(R, "u3") == [], nets(R, "u3"))
R = groups_roster({"users": {}, "groups": {"g1": 0}}, None)
check("the group deleted (its id still in the share): nothing", nets(R, "u4") == [], nets(R, "u4"))
R = groups_roster({"users": {}, "groups": {"g1": NOW - 1}}, ["u3", "u4"])
check("a group grant whose date has passed: nothing", nets(R, "u4") == [], nets(R, "u4"))
R = groups_roster({"users": {"u3": NOW - 1}, "groups": {"g1": NOW + 99}}, ["u3"])
check("a lapsed grant by name and a live one through the group: listed — the widest wins", nets(R, "u3") == ROW(True, "office router"), nets(R, "u3"))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
