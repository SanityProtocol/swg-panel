#!/usr/bin/env python3
"""Self-test for user GROUPS — the model and its door (docs/GROUPS-PLAN.md G1–G3, G8, G9).

  [1] `group_name_clean`: control characters stripped, empty refused, 64 characters at most, unique case-insensitively —
      a group keeps its own name on a rename.
  [2] `group_set`: `{name, users}` only, members sorted and unique; a rename keeps the members and a member change keeps
      the name (a whitelist rebuild that carries what it is not given).
  [3] the door: create (with first members; an unknown user refused with nothing written), rename, add/remove as a DELTA
      (already in / not in: no-ops; a ghost can be removed), an update that changes nothing writes nothing and logs
      nothing, a duplicate name refused, an unknown group 404, delete — and every change in the activity log.
  [4] two operators' deltas compose: neither undoes the other.
  [5] the roster envelope: a user update leaves groups as they are; a user delete takes the id out of every group and
      every network grant in the same write, so the same id arriving later gets nothing back (G8); a save round trip
      keeps them.
  [6] a node transfer carries the groups its users are in, narrowed to them, and the receiver merges them after the users;
      an arriving name already taken here is suffixed. Ids that are not strings get a 404, never a crash ([3]).

Hermetic. Run: python3 tests/user_groups_selftest.py            (0 = pass)
     --perturb   has `group_set` rebuild without carrying what it was not given, and expects RED on [2], [3] and [4].
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
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
if PERTURB:
    def _bad_group_set(roster, gid, fields):
        if not isinstance(roster.get("groups"), dict):
            roster["groups"] = {}
        roster["groups"][gid] = {"name": fields.get("name", ""),
                                                "users": sorted({u for u in fields.get("users", []) if isinstance(u, str)})}
        return roster["groups"][gid]
    P.group_set = _bad_group_set

def base():
    return {"version": P.ROSTER_VERSION,
            "users": {"u1": {"id": "u1", "name": "Ivan"}, "u2": {"id": "u2", "name": "Maria"}, "u3": {"id": "u3", "name": "Oleg"}},
            "peers": {}, "groups": {"g1": {"name": "Family", "users": ["u1", "u2"]}}}

print("\n[1] group_name_clean")
R = base()
check("control characters stripped, spaces trimmed", P.group_name_clean(R, "  Work\x07 team ") == ("Work team", None))
check("empty refused", (P.group_name_clean(R, "   ")[1] or {}).get("error") == "name is required"
      and (P.group_name_clean(R, None)[1] or {}).get("error") == "name is required")
check("64 characters at most", len(P.group_name_clean(R, "x" * 100)[0]) == 64)
check("a duplicate name refused, case-insensitively", (P.group_name_clean(R, "fAMILY")[1] or {}).get("error") == "a group with this name already exists")
check("a group keeps its own name on a rename", P.group_name_clean(R, "family", "g1") == ("family", None))

print("\n[2] group_set")
R = base()
check("members sorted and unique, junk dropped", P.group_set(R, "g2", {"name": "Work", "users": ["u3", "u1", "u3", 7]}) == {"name": "Work", "users": ["u1", "u3"]})
P.group_set(R, "g1", {"name": "Ivanovs"})
check("a rename keeps the members", R["groups"]["g1"] == {"name": "Ivanovs", "users": ["u1", "u2"]}, R["groups"]["g1"])
P.group_set(R, "g1", {"users": ["u2"]})
check("a member change keeps the name", R["groups"]["g1"] == {"name": "Ivanovs", "users": ["u2"]}, R["groups"]["g1"])
R2 = {"users": {}, "peers": {}, "groups": "junk"}
check("a roster whose `groups` is not a dict gets one", P.group_set(R2, "g", {"name": "A"}) == {"name": "A", "users": []} and isinstance(R2["groups"], dict))

print("\n[3] the door")
TMP = tempfile.mkdtemp(prefix="groups-")
nodes_path, roster_path = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
json.dump({}, open(nodes_path, "w"))
json.dump(base(), open(roster_path, "w"))
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {}, "stats_dir": TMP, "fleet": {}}
api = lambda path, body: P.api("POST", path, {}, body, deps)
now_ = lambda: json.load(open(roster_path))
events = lambda: [json.loads(l) for l in open(os.path.join(TMP, "events.jsonl"))] if os.path.exists(os.path.join(TMP, "events.jsonl")) else []
try:
    c, b = api("/api/groups/create", {"name": "Work", "users": ["u3", "u1"]})
    gid = (b.get("data") or {}).get("id")
    check("create with first members: one write", c == 200 and now_()["groups"].get(gid) == {"name": "Work", "users": ["u1", "u3"]}, (c, b))
    check("…logged as Created group, the count as a counted noun",
          events()[-1].get("verb") == "Created group" and events()[-1].get("kind") == "group" and events()[-1].get("id") == gid
          and events()[-1].get("detail_vars") == {"count": {"n": 2, "noun": "member"}}, events()[-1:])
    n_ev, snap_ = len(events()), now_()
    c, b = api("/api/groups/create", {"name": "Friends", "users": ["u1", "nobody"]})
    check("an unknown user refused, nothing written or logged", c == 400 and now_() == snap_ and len(events()) == n_ev, (c, b))
    c, b = api("/api/groups/create", {"name": "work"})
    check("a duplicate name refused", c == 400 and b.get("error") == "a group with this name already exists", (c, b))
    c, b = api("/api/groups/update", {"id": "g1", "name": "Ivanovs"})
    check("rename: members kept, logged with the old name", c == 200 and now_()["groups"]["g1"] == {"name": "Ivanovs", "users": ["u1", "u2"]}
          and events()[-1].get("verb") == "Renamed group" and events()[-1].get("detail") == "Family", (c, b, events()[-1:]))
    c, b = api("/api/groups/update", {"id": "g1", "add": ["u3", "u1"], "remove": ["u2", "ghost"]})
    check("add/remove as a delta: Oleg in, Maria out, Ivan (already in) and a ghost are no-ops",
          c == 200 and now_()["groups"]["g1"] == {"name": "Ivanovs", "users": ["u1", "u3"]}
          and events()[-1].get("verb") == "Changed group members" and events()[-1].get("detail") == "+1 −1", (c, b, events()[-1:]))
    n_ev, snap_ = len(events()), now_()
    c, b = api("/api/groups/update", {"id": "g1", "name": "Ivanovs", "add": ["u1"], "remove": ["u2"]})
    check("an update that changes nothing writes nothing and logs nothing", c == 200 and now_() == snap_ and len(events()) == n_ev, (c, b))
    c, b = api("/api/groups/update", {"id": "g1", "add": ["nobody"]})
    check("adding an unknown user refused", c == 400 and now_() == snap_, (c, b))
    c, b = api("/api/groups/update", {"id": "g1", "add": "u2"})
    check("add must be a list", c == 400, (c, b))
    c, b = api("/api/groups/update", {"id": "nope", "name": "x"})
    check("an unknown group: 404", c == 404, (c, b))
    c1, _ = api("/api/groups/update", {"id": ["g1"], "name": "x"})
    c2, _ = api("/api/groups/delete", {"id": {"g1": 1}})
    check("an id that is not a string: 404, never a crash", c1 == 404 and c2 == 404, (c1, c2))
    c, b = api("/api/groups/delete", {"id": gid})
    check("delete: gone, logged", c == 200 and gid not in now_()["groups"] and events()[-1].get("verb") == "Deleted group"
          and events()[-1].get("name") == "Work", (c, b))
    c, b = api("/api/groups/delete", {"id": gid})
    check("deleting it twice: 404", c == 404)
except Exception as e:
    check("the door round trips ran", False, repr(e))

print("\n[4] two operators' deltas compose")
try:
    json.dump(base(), open(roster_path, "w"))
    api("/api/groups/update", {"id": "g1", "add": ["u3"]})           # operator A, who opened the group with Ivan and Maria
    api("/api/groups/update", {"id": "g1", "remove": ["u1"]})        # operator B, who opened the same view
    check("A's addition and B's removal both stand", now_()["groups"]["g1"]["users"] == ["u2", "u3"], now_()["groups"]["g1"])
except Exception as e:
    check("the concurrent deltas ran", False, repr(e))

print("\n[5] the roster envelope")
try:
    RB = base()
    RB["peers"] = {"gw": {"id": "gw", "user_id": "u1", "routes": ["192.168.1.0/24"], "targets": [],
                          "share": {"users": {"u2": 0, "u3": 0}, "groups": {"g1": 0}}},
                   "gw2": {"id": "gw2", "user_id": "u3", "routes": ["192.168.2.0/24"], "targets": [], "share": {"users": {"u2": 0}}}}
    json.dump(RB, open(roster_path, "w"))
    c, _ = api("/api/users/update", {"id": "u1", "name": "Ivan I."})
    check("a user update leaves groups as they are", c == 200 and now_()["groups"] == base()["groups"])
    c, _ = api("/api/users/delete", {"id": "u2"})
    _n = now_()
    check("a user delete takes their id out of every group in the same write (G8)",
          c == 200 and "u2" not in _n["users"] and _n["groups"]["g1"]["users"] == ["u1"], _n["groups"])
    check("…and out of every network grant, leaving a restricted share restricted",
          _n["peers"]["gw"]["share"] == {"users": {"u3": 0}, "groups": {"g1": 0}} and _n["peers"]["gw2"]["share"] == {"users": {}}, _n["peers"])
    _n["users"]["u2"] = {"id": "u2", "name": "Maria, back from a transfer"}
    check("…so the same id arriving again gets none of it back",
          P.share_grants(_n["peers"]["gw"], _n["users"], 0, _n["groups"]) == {"u1": 0, "u3": 0})
    r = P.roster_load(roster_path); P.roster_save(roster_path, r)
    check("a load/save round trip keeps them", P.roster_load(roster_path).get("groups") == now_()["groups"])
except Exception as e:
    check("the envelope round trips ran", False, repr(e))

print("\n[6] node transfer")
P.load_sub_escrow = lambda deps: {}
P.load_sub_users = lambda deps: {}
P.load_sub_blobs = lambda deps, uid: {}
RT = base()
RT["groups"]["g2"] = {"name": "Work", "users": ["u3"]}
RT["groups"]["g3"] = {"name": "Maria+Oleg", "users": ["u2", "u3"]}
RT["peers"] = {"p1": {"id": "p1", "user_id": "u1", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.0.0.2"}]},
               "p2": {"id": "p2", "user_id": "u2", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.0.0.3"}]},
               "p3": {"id": "p3", "user_id": "u3", "targets": [{"node": "n2", "iface": "wg0", "ip": "10.1.0.2"}]}}
NODES = {"n1": {"id": "n1", "name": "home"}, "n2": {"id": "n2", "name": "edge"}}
try:
    plan = P.transfer_plan({"now": lambda: 0}, NODES, "n1", {}, {}, RT)
    check("the groups its users are in travel, each narrowed to the users that move",
          plan.get("groups") == {"g1": {"name": "Family", "users": ["u1", "u2"]}, "g3": {"name": "Maria+Oleg", "users": ["u2"]}}, plan.get("groups"))
    P._panel_public_url = lambda deps: "https://a.example"
    bundle = P.transfer_bundle({}, NODES, "n1", plan)
    check("the bundle carries them", bundle.get("groups") == plan["groups"])
except Exception as e:
    check("transfer_plan ran", False, repr(e))
B = {"users": {"u1": {"name": "Ivan"}, "u2": {"name": "Maria"}, "x9": {"name": "Local"}}, "peers": {},
     "groups": {"g3": {"name": "Maria and friends", "users": ["x9"]}}}
n = P.transfer_merge_groups(B, {"g1": {"name": "Family\x07", "users": ["u1", "u2", "u7"]}, "g3": {"name": "Maria+Oleg", "users": ["u2"]},
                                "bad": "junk"})
check("a new group is inserted, with only the users this roster holds", B["groups"]["g1"] == {"name": "Family", "users": ["u1", "u2"]}, B["groups"])
check("a group already here gains the arriving members and keeps its own name",
      B["groups"]["g3"] == {"name": "Maria and friends", "users": ["u2", "x9"]} and n == 2, (B["groups"], n))
check("nothing arriving: nothing changes", P.transfer_merge_groups(B, None) == 0 and P.transfer_merge_groups(B, {}) == 0)
P.transfer_merge_groups(B, {"g8": {"name": "FAMILY", "users": ["u1"]}, "g9": {"name": "family", "users": ["u2"]}})
check("a new group whose name is taken arrives renamed — names stay unique (G2)",
      B["groups"]["g8"]["name"] == "FAMILY (2)" and B["groups"]["g9"]["name"] == "family (3)", {k: B["groups"][k]["name"] for k in ("g1", "g8", "g9")})
_src = open(PANEL).read()
_rx = _src[_src.index("roster[\"users\"][uid] = u; nu += 1"):]
check("the receiver merges groups right after the users they name, before the roster is saved",
      _rx.index("transfer_merge_groups(roster, b.get(\"groups\"))") < _rx.index("roster_save(deps[\"roster_path\"], roster)"))

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
