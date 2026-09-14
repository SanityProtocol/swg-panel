#!/usr/bin/env python3
"""Self-test for sharing a network with a GROUP (docs/GROUPS-PLAN.md G4–G7).

A grant can name a group; it is expanded to the group's existing members at plan time, everywhere grants are read, and
nothing on the node changes shape. What this holds:

  [1] `share_grants`: a group grant reaches its existing members and nobody else; a deleted member, a deleted group and a
      lapsed group grant grant nothing; a user covered twice gets the widest date (no end beats a date, else the latest);
      the owner always no end; junk ignored; a share without groups answers exactly what the pre-groups function did;
      `groups` is a REQUIRED argument, and every caller in swg-panel-server and swg-sub passes it.
  [2] `share_clean`: groups stored only when named (a users-only share keeps its bytes); a NEW unknown group or passed date
      refused, a STORED one dropped quietly; users + groups share the one cap; ⚠️ a body without `groups` while groups are
      stored is refused `groups_missing` — nothing written.
  [3] through the real door: a group grant saved and kept across an unrelated edit; the old-tab body refused and nothing
      written; deleting the group rewrites no peer and the grant then reaches nobody; `groups: {}` clears them.
  [4] `net_share_for_node`: a group grant yields EXACTLY the elements of granting its members by name; a date combines;
      a removed member and a member's blocked device are not sources.
  [5] `network_report`: members listed with their devices, non-members cut off, a lapsed group grant named; a person whose
      own grant lapsed is not named as cut off while a group still lets them in.
  [6] `user_networks`: a member sees the restricted network, with the group grant's date; a removed member does not.
  [7] D1: groups in the roster and no share naming one — no `net_share`, and `desired_for_node` byte-identical.

Hermetic. Run: python3 tests/share_groups_selftest.py            (0 = pass)
     --perturb   has share_grants ignore group grants and expects RED on [1], [4], [5] and [6].
"""
import ast, copy, importlib.machinery, importlib.util, inspect, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel", PANEL)
_sg = P.share_grants
if PERTURB:
    P.share_grants = lambda p, users, nowv, groups: _sg(p, users, nowv, None)

NOW = int(time.time())
DAY = 86400
K = lambda c: c * 43 + "="
def roster(share=None, members=("boris", "carol", "ghost")):
    r = {"users": {"anna": {"name": "Anna"}, "boris": {"name": "Boris"}, "carol": {"name": "Carol"},
                   "dora": {"name": "Dora", "disabled": True}},
         "peers": {
        "office": {"id": "office", "user_id": "anna", "pubkey": K("O"), "created_at": 1, "routes": ["192.168.1.0/24"],
                   "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.2", "type": "awg"}]},
        "anna-phone": {"id": "anna-phone", "user_id": "anna", "pubkey": K("A"),
                       "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.3", "type": "awg"}]},
        "boris-phone": {"id": "boris-phone", "user_id": "boris", "pubkey": K("B"),
                        "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.4", "type": "wg"}]},
        "boris-site": {"id": "boris-site", "user_id": "boris", "pubkey": K("S"), "created_at": 2, "routes": ["192.168.7.0/24"],
                       "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.5", "type": "wg"}]},
        "carol-phone": {"id": "carol-phone", "user_id": "carol", "pubkey": K("C"),
                        "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.6", "type": "awg"}]},
        "dora-phone": {"id": "dora-phone", "user_id": "dora", "pubkey": K("D"),
                       "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.7", "type": "awg"}]}},
         "groups": {"fam": {"name": "Ivanov family", "users": list(members)}, "empty": {"name": "Empty", "users": []}}}
    if share is not None:
        r["peers"]["office"]["share"] = share
    return r
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg1": {"meta": {"subnet": "10.9.0.0/24"}}},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1}}
grants = lambda r: P.share_grants(r["peers"]["office"], r["users"], NOW, r.get("groups"))

def FROZEN_share_grants(p, users, nowv):          # the function as it was before groups (fe09f54), for [1]'s control
    sh = p.get("share") if isinstance(p, dict) else None
    if not isinstance(sh, dict):
        return None
    out = {}
    for uid, until in (sh.get("users") if isinstance(sh.get("users"), dict) else {}).items():
        if uid not in users or isinstance(until, bool) or not isinstance(until, int) or until < 0:
            continue
        if until and until <= nowv:
            continue
        out[uid] = until
    if p.get("user_id") in users:
        out[p["user_id"]] = 0
    return out

print("\n[1] share_grants")
check("a group grant reaches its existing members — a deleted one is not — and a name grant for good beats its date",
      grants(roster({"users": {"boris": 0}, "groups": {"fam": NOW + DAY}})) == {"anna": 0, "boris": 0, "carol": NOW + DAY},
      grants(roster({"users": {"boris": 0}, "groups": {"fam": NOW + DAY}})))
check("two dates: the later one wins, whichever grant it came from",
      grants(roster({"users": {"carol": NOW + 2 * DAY}, "groups": {"fam": NOW + DAY}})) == {"anna": 0, "boris": NOW + DAY, "carol": NOW + 2 * DAY})
check("a lapsed group grant grants nothing", grants(roster({"users": {}, "groups": {"fam": NOW - 5}})) == {"anna": 0})
check("…nor does a live name grant lapse because a group grant did",
      grants(roster({"users": {"boris": NOW + DAY}, "groups": {"fam": NOW - 5}})) == {"anna": 0, "boris": NOW + DAY})
_rd = roster({"users": {}, "groups": {"fam": 0}}); del _rd["groups"]["fam"]
check("a group that no longer exists grants nothing", grants(_rd) == {"anna": 0}, grants(_rd))
check("a member removed from the group: not in", grants(roster({"users": {}, "groups": {"fam": 0}}, members=["boris"])) == {"anna": 0, "boris": 0})
check("an empty group grants nothing", grants(roster({"users": {}, "groups": {"empty": 0}})) == {"anna": 0})
_rj = roster({"users": {}, "groups": {"fam": 0, "x": True, "y": -1, "junk": 0}}); _rj["groups"]["junk"] = "no"
check("junk grants and junk records ignored", grants(_rj) == {"anna": 0, "boris": 0, "carol": 0}, grants(_rj))
check("a roster whose `groups` is not a dict: only names count",
      P.share_grants(roster({"users": {"boris": 0}, "groups": {"fam": 0}})["peers"]["office"], roster()["users"], NOW, "junk") == {"anna": 0, "boris": 0})
_same = True
for sh in (None, {"users": {}}, {"users": {"boris": 0, "carol": NOW + 5, "dora": NOW - 1, "ghost": 0, "anna": 7, "x": True, "y": -2}}, {"x": 1}, "open"):
    for owner in ("anna", None, "gone"):
        p = dict(roster()["peers"]["office"], share=sh, user_id=owner)
        for groups in (roster()["groups"], None, {}):
            _same = _same and P.share_grants(p, roster()["users"], NOW, groups) == FROZEN_share_grants(p, roster()["users"], NOW)
check("a share without groups answers exactly what the pre-groups function did", _same)
check("`groups` is a REQUIRED argument — a caller that forgets it fails loudly",
      inspect.signature(_sg).parameters["groups"].default is inspect.Parameter.empty)
calls = []
for path in (PANEL, SUB):
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "share_grants":
            calls.append((os.path.basename(path), n.lineno, len(n.args) + len(n.keywords)))
check("every call in swg-panel-server and swg-sub passes the groups (4 arguments)",
      len(calls) >= 4 and all(c[2] == 4 for c in calls), calls)

print("\n[2] share_clean")
clean = lambda r, raw, peer=None: P.share_clean(r, peer if peer is not None else r["peers"]["office"], raw, NOW)
R = roster()
check("a group grant is stored", clean(R, {"users": {}, "groups": {"fam": 0}}) == ({"users": {}, "groups": {"fam": 0}}, None))
check("no groups named: no `groups` key — a users-only share keeps its bytes",
      clean(R, {"users": {"boris": 0}, "groups": {}}) == ({"users": {"boris": 0}}, None) and clean(R, {"users": {"boris": 0}}) == ({"users": {"boris": 0}}, None))
check("a NEW unknown group is refused", clean(R, {"users": {}, "groups": {"gone": 0}}) == (None, "unknown_group"))
check("a NEW passed date on a group is refused", clean(R, {"users": {}, "groups": {"fam": NOW - 5}}) == (None, "date_passed"))
check("a bad date on a group is refused", clean(R, {"users": {}, "groups": {"fam": True}}) == (None, "bad_date"))
check("`groups` not a dict / an unknown key: bad_shape",
      clean(R, {"users": {}, "groups": ["fam"]}) == (None, "bad_shape") and clean(R, {"users": {}, "teams": {}}) == (None, "bad_shape"))
_ps = dict(R["peers"]["office"], share={"users": {}, "groups": {"gone": 0, "fam": NOW - 5}})
check("a STORED unknown group and a STORED lapsed group grant are dropped quietly",
      clean(R, {"users": {}, "groups": {"gone": 0, "fam": NOW - 5}}, _ps) == ({"users": {}}, None))
_pg = dict(R["peers"]["office"], share={"users": {"boris": 0}, "groups": {"fam": 0}})
check("⚠️ a body without `groups` while groups are stored: refused, nothing to store",
      clean(R, {"users": {"boris": 0}}, _pg) == (None, "groups_missing"))
check("…the same body with `groups: {}` clears them", clean(R, {"users": {"boris": 0}, "groups": {}}, _pg) == ({"users": {"boris": 0}}, None))
check("…and null still clears the whole share", clean(R, None, _pg) == (None, None))
RB = roster()
for i in range(P.NET_SHARE_MAX):
    RB["users"]["u%03d" % i] = {"name": "u%d" % i}
check("users + groups share the one cap",
      clean(RB, {"users": {"u%03d" % i: 0 for i in range(P.NET_SHARE_MAX)}, "groups": {"fam": 0}}) == (None, "too_many")
      and clean(RB, {"users": {"u%03d" % i: 0 for i in range(P.NET_SHARE_MAX - 1)}, "groups": {"fam": 0}})[1] is None)

print("\n[3] through the real door")
TMP = tempfile.mkdtemp(prefix="sharegroups-")
nodes_path, roster_path = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
json.dump({"n1": {"id": "n1", "name": "home"}}, open(nodes_path, "w"))
RD = roster(); RD["version"] = P.ROSTER_VERSION
json.dump(RD, open(roster_path, "w"))
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {"n1": SNAP}, "stats_dir": TMP, "fleet": {}}
now_ = lambda: json.load(open(roster_path))
try:
    c1, b1 = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "share": {"users": {}, "groups": {"fam": 0}}}, deps)
    check("a group grant saved", c1 == 200 and now_()["peers"]["office"].get("share") == {"users": {}, "groups": {"fam": 0}}, (c1, b1))
    c2, _ = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "title": "Office"}, deps)
    check("an unrelated edit keeps it", c2 == 200 and now_()["peers"]["office"].get("share") == {"users": {}, "groups": {"fam": 0}})
    c3, b3 = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "routes": ["192.168.1.0/24"], "share": {"users": {}}}, deps)
    check("⚠️ an old tab's body (no `groups`) is refused, and nothing is written",
          c3 == 400 and b3.get("why") == "groups_missing" and now_()["peers"]["office"].get("share") == {"users": {}, "groups": {"fam": 0}}, (c3, b3))
    c4, b4 = P.api("POST", "/api/peers/networks", {}, {"peer_id": "office", "share": {"users": {}, "groups": {"fam": 0}}}, deps)
    _g4 = [g["user_id"] for t in b4["data"]["targets"] for g in (t.get("share") or {}).get("grants", [])]
    check("the draft preview expands the group", c4 == 200 and _g4 == ["anna", "boris", "carol"], _g4)
    _before = copy.deepcopy(now_()["peers"])
    c5, _ = P.api("POST", "/api/groups/delete", {}, {"id": "fam"}, deps)
    check("deleting the group rewrites no peer — the share still names it", c5 == 200 and now_()["peers"] == _before and "fam" not in now_()["groups"])
    _r5 = now_()
    check("…and the grant then reaches nobody but the owner", P.share_grants(_r5["peers"]["office"], _r5["users"], NOW, _r5.get("groups")) == {"anna": 0})
    c6, _ = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "share": {"users": {}, "groups": {"fam": 0}}}, deps)
    check("saving back the dead id it was shown drops it quietly", c6 == 200 and now_()["peers"]["office"].get("share") == {"users": {}})
except Exception as e:
    check("the door round trips ran", False, repr(e))

print("\n[4] net_share_for_node")
def ns(r):
    return P.net_share_for_node(r, "n1", P.node_networks(r, "n1", SNAP)["carry"])
by_name = ns(roster({"users": {"boris": NOW + DAY, "carol": NOW + DAY}}))
by_group = ns(roster({"users": {}, "groups": {"fam": NOW + DAY}}))
check("a group grant = granting its members by name, element for element", by_group == by_name and len(by_group[0]["from"]) == 7, by_group)
_mix = {e[1]: e[2] for e in ns(roster({"users": {"boris": NOW + DAY}, "groups": {"fam": 0}}))[0]["from"]}
check("a date combines: Boris by name until tomorrow, in the family for good — for good",
      _mix.get("10.9.0.4/32") == 0 and _mix.get("192.168.7.0/24") == 0 and _mix.get("10.8.0.6/32") == 0, _mix)
_rm = [e[1] for e in ns(roster({"users": {}, "groups": {"fam": 0}}, members=["boris"]))[0]["from"]]
check("a member removed is no source", "10.8.0.6/32" not in _rm and "10.9.0.4/32" in _rm, _rm)
_bl = [e[1] for e in ns(roster({"users": {}, "groups": {"fam": 0}}, members=["dora"]))[0]["from"]]
check("a blocked member's device is no source", _bl == ["10.8.0.2/32", "10.8.0.3/32", "192.168.1.0/24"], _bl)

print("\n[5] network_report")
rep = P.network_report(roster({"users": {}, "groups": {"fam": NOW + DAY}}), "office", {"n1": SNAP})
sh = rep["targets"][0].get("share") or {}
check("members listed with their devices here", [(g["user_id"], g["until"], g["devices"]) for g in sh.get("grants", [])]
      == [("anna", 0, 1), ("boris", NOW + DAY, 2), ("carol", NOW + DAY, 1)], sh.get("grants"))
check("nobody else on the node is left to cut off (Dora is blocked)", (sh.get("cut_off") or {}).get("peers") == 0, sh.get("cut_off"))
rep2 = P.network_report(roster({"users": {}, "groups": {"fam": NOW + DAY}}, members=["boris"]), "office", {"n1": SNAP})
check("Carol out of the group: cut off", (rep2["targets"][0]["share"]["cut_off"]).get("users") == 1, rep2["targets"][0]["share"]["cut_off"])
_lc = P.network_report(roster({"users": {"boris": NOW - 5, "anna": NOW - 5}, "groups": {"fam": 0}}, members=["boris"]), "office", {"n1": SNAP})
check("a person whose own grant lapsed but who is still in a granted group is NOT named as cut off",
      _lc["targets"][0]["share"].get("lapsed") == [], _lc["targets"][0]["share"].get("lapsed"))
_lx = P.network_report(roster({"users": {"carol": NOW - 5}, "groups": {"fam": 0}}, members=["boris"]), "office", {"n1": SNAP})
check("…one with nothing else letting them in is", _lx["targets"][0]["share"].get("lapsed") == ["carol"], _lx["targets"][0]["share"].get("lapsed"))
_rl = roster({"users": {}, "groups": {"fam": NOW - 5, "gone": NOW - 5, "empty": NOW + 5}})
check("a lapsed group grant is named — a deleted group's is not",
      P.network_report(_rl, "office", {"n1": SNAP})["targets"][0]["share"].get("lapsed_groups") == ["fam"])

print("\n[6] user_networks")
un = P.user_networks(roster({"users": {}, "groups": {"fam": NOW + DAY}}), "carol", {"n1": SNAP})
_cn = [(n["prefix"], n.get("restricted"), n.get("until")) for pr in un["peers"] for t in pr["targets"] for n in t["networks"]]
check("a member sees the restricted network, with the group grant's date", ("192.168.1.0/24", True, NOW + DAY) in _cn, _cn)
un2 = P.user_networks(roster({"users": {}, "groups": {"fam": NOW + DAY}}, members=["boris"]), "carol", {"n1": SNAP})
check("a removed member does not", not any(n["prefix"] == "192.168.1.0/24" for pr in un2["peers"] for t in pr["targets"] for n in t["networks"]))

print("\n[7] D1 — groups nobody's share names")
RG, RN = roster(), roster()
del RN["groups"]
check("no share anywhere: no net_share", ns(RG) == [])
b = lambda x: json.dumps(x, sort_keys=False)
check("desired_for_node byte-identical with and without `groups` in the roster",
      b(P.desired_for_node(RG, "n1", SNAP)) == b(P.desired_for_node(RN, "n1", SNAP)))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
