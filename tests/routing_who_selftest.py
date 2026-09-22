#!/usr/bin/env python3
"""Self-test for per-person smart rules on the panel (docs/ROUTING-PEERS-MESH-PLAN.md §2, §4.2–4.4, §8 P1).

A rule may carry `who` — users, groups and single devices — and then applies only to those devices on its own
interface. What the panel has to get right, each checked on the real functions:

  THE DOOR (`_validate_routing`)  — the guarded shape: stored `enabled: false`, the switch in `who.on`, so every older
      reader skips it (D7); unknown ids through the asymmetric door; nobody chosen refused; "everything else" is never
      per-person (D10); a rule without `who` stored exactly as before.
  THE READERS (`rule_on`)         — cascade_plan and mesh_need ask `rule_on`, never a raw `enabled`, so a live per-person
      rule is neither dropped from the plan nor has its mesh link retired (T11). A closed list, read from the source.
  THE PLAN (`cascade_plan`)       — carries a selection as an opaque 12-hex `src`, stable across re-orderings of the
      lists, never expanded; a plan with no `who` is byte-identical to one built by a copy without any of this.
  THE SYNC (`who_plan_for_node`)  — resolves the syncing node's selections to (device, /32) pairs in the rule's own
      subnet: users, their groups, single devices; a keyless device only through `keyless_sources` (vouched builds);
      blocked and expired devices left out; a selection with nobody withholds its entries; a node that does not
      report `src` gets no per-person entry at all (D4) and its card says so.
  THE OLD TAB (`_apply_egress_mode`) — a save without `routing_v: 2` over a stored `who` rule is refused, for
      interfaces and WDTT / csqtt alike (they share the helper); a list with no `who` still saves.

Run: python3 tests/routing_who_selftest.py   (0 = pass)
  --plant a|b|c|d|e|f|g   plant one defect and expect RED on its own check (exit 0 when caught):
     a  the door stores `who` with `enabled: true` (an older panel would route it for the whole subnet)
     b  mesh_need reads the raw `enabled` (a demand-mode link a live per-person rule needs is retired)
     c  resolution takes a keyless device's roster address instead of what `keyless_sources` vouches for
     d  the sync ignores the node's capability (an old node would widen the rule to the subnet)
     e  no `routing_v` refusal (an old tab re-saves the rule without its people)
     f  a roster address is trusted unparsed (an adopted "(none)" raises in the sync — the node's whole sync fails)
     g  the report ignores the node's capability (an old node's rows read "covered" while it withholds them all)
     h  a stored selection of the wrong shape is trusted (cascade_plan raises — every node's sync fails)
     i  the report trusts a selection's shape (a malformed body is a 500)
     j  the owner index forgets users (a selection's people resolve to nobody — the differential against the old loop is red)
"""
import copy, importlib.machinery, importlib.util, json, os, re, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "a": ('''            out["enabled"] = False                         # ← what every older reader sees: a rule that is off''',
          '''            pass'''),
    "b": ('''                    if rule_on(r) and r.get("action") == "exit":''',
          '''                    if isinstance(r, dict) and r.get("enabled", True) is not False and r.get("action") == "exit":'''),
    "c": ('''                prs, why = keyless_sources(p, t, idx)''',
          '''                prs, why = ([(str(t.get("iface")), str(t.get("ip") or "").split("/")[0] + "/32")] if t.get("ip") else []), ""'''),
    "d": ('''    if ((snap or {}).get("smartroute") or {}).get("src"):
        here = _who_here(roster, node_id, snap)''', '''    if True:
        here = _who_here(roster, node_id, snap)'''),
    "f": ('''            elif t.get("iface") and _who_addr_ok(str(t.get("ip") or "")):''',
          '''            elif (t.get("ip") or "").split("/")[0] and t.get("iface"):'''),
    "g": ('''    old = bool(snap) and not ((snap.get("smartroute") or {}).get("src"))''', '''    old = False'''),
    "h": ('''    canon = json.dumps({k: sorted(_who_ids(who.get(k))) for k in ("users", "groups", "peers")},   # the ids the resolver reads; a bad shape names nobody''',
          '''    canon = json.dumps({k: sorted({str(x) for x in (who.get(k) or [])}) for k in ("users", "groups", "peers")},'''),
    "i": ('''    return {x for x in v if isinstance(x, str)} if isinstance(v, list) else set()''', '''    return set(v or [])'''),
    "j": ('''            for pid in pids.intersection(here) | {q for u in uids for q in by_uid.get(u, ())}:''',
          '''            for pid in pids.intersection(here):'''),
    "e": ('''        return "This browser tab is older than the panel — reload it before saving routing.", None''',
          '''        pass'''),
}
path = PANEL
TMP = tempfile.mkdtemp(prefix="routing-who-")
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))

_l = importlib.machinery.SourceFileLoader("swgpanel_who", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_who", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

NOW = int(time.time())
ROSTER = {
    "users": {"u1": {"id": "u1", "name": "Alice"}, "u2": {"id": "u2", "name": "Bob"},
              "u3": {"id": "u3", "name": "Carol", "disabled": True}, "u4": {"id": "u4", "name": "Dan", "expiry": NOW - 60}},
    "groups": {"g1": {"name": "Family", "users": ["u2", "u4"]}},
    "peers": {
        "p1": {"id": "p1", "user_id": "u1", "title": "phone", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5"}]},
        "p2": {"id": "p2", "user_id": "u1", "title": "laptop", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.6"}]},
        "p3": {"id": "p3", "user_id": "u2", "title": "phone", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.7"}]},
        "p4": {"id": "p4", "user_id": "u3", "title": "phone", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.8"}]},
        "p5": {"id": "p5", "user_id": None, "title": "router", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.9"}]},
        "p6": {"id": "p6", "user_id": "u4", "title": "tablet", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.10"}]},
        "p7": {"id": "p7", "user_id": "u1", "title": "wdtt phone", "wdtt_password": "pwA",
               "targets": [{"node": "n1", "iface": "wdttA", "type": "wdtt", "ip": "10.20.0.99"}]},
        "p8": {"id": "p8", "user_id": "u1", "title": "wdtt old", "wdtt_password": "pwB",
               "targets": [{"node": "n1", "iface": "wdttB", "type": "wdtt", "ip": "10.21.0.99"}]},
        "p9": {"id": "p9", "user_id": "u1", "title": "elsewhere", "targets": [{"node": "n2", "iface": "wg0", "ip": "10.9.0.5"}]},
        "p10": {"id": "p10", "user_id": "u2", "title": "blocked", "disabled": True,
                "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.11"}]},
    }}
SNAP1 = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}},
         "wdtt": [{"iface": "wdttA", "fork": "qwdtt", "version": "1.4.3-2", "passwords": {"pwA": {"ip": "10.20.0.5"}}},
                  {"iface": "wdttB", "fork": "qwdtt", "version": "1.4.2", "passwords": {"pwB": {"ip": "10.21.0.5"}}}],
         "smartroute": {"mode": "kernel", "src": 1}}
SNAP2 = {"interfaces": {"wg0": {"meta": {"subnet": "10.9.0.0/24"}}}, "smartroute": {"mode": "kernel", "src": 1}}


def fleet(routing, wdtt_routing=None):
    nodes = {"n1": {"name": "node-one", "routing_mode": "kernel",
                    "ifaces": {"wg0": {"egress_mode": "smart", "routing": routing}},
                    "wdtt": {"wdttA": {"wg_addr": "10.20.0.1/24", "egress_mode": "smart", "routing": wdtt_routing or routing},
                             "wdttB": {"wg_addr": "10.21.0.1/24", "egress_mode": "smart", "routing": wdtt_routing or routing}},
                    "links": {"n2": {"iface": "swg_n2", "peer_address": "10.255.0.1"}}},
             "n2": {"name": "node-two", "routing_mode": "kernel", "ifaces": {"wg0": {}},
                    "links": {"n1": {"iface": "swg_n1", "peer_address": "10.255.0.0"}}}}
    return nodes


def door(rules, prev=(), roster=ROSTER, nodes=None):
    return P._validate_routing(rules, nodes or fleet([]), "n1", (), prev=prev, roster=roster)


R_ALICE = {"enabled": False, "category": "custom", "targets": "203.0.113.0/24", "action": "exit", "node": "n2",
           "who": {"on": True, "users": ["u1"], "groups": [], "peers": []}}
R_ALL = {"enabled": True, "category": "custom", "targets": "198.51.100.0/24", "action": "exit", "node": "n2"}

# ── 1. the door ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[the door]")
c, e, _ = door([R_ALICE, R_ALL])
check("a per-person rule and a rule for everyone are both accepted", e is None and c and len(c) == 2, (e, c))
g = (c or [{}])[0]
check("the per-person rule is STORED switched off — every older reader skips it (D7)", g.get("enabled") is False, g)
check("…with its real switch and its people in `who`", g.get("who") == {"on": True, "users": ["u1"], "groups": [], "peers": []}, g)
check("a rule an older panel sees: its released `enabled` test skips it (so it is never widened)",
      g.get("enabled", True) is False)
check("the rule for everyone is stored exactly as before — no `who`, enabled", c and c[1].get("enabled") is True and "who" not in c[1], c)
cE, eE, _ = door([dict(R_ALICE, enabled=True)])
check("the door forces the guard whatever the client sent: `enabled: true` + `who` is stored off, the switch in `who.on`",
      eE is None and cE[0].get("enabled") is False and cE[0]["who"]["on"] is True, (eE, cE))
cN, eN, _ = door([dict(R_ALICE, enabled=True, who={"users": ["u1"], "groups": [], "peers": []})])
check("…and a `who` without `on` takes its switch from `enabled`", eN is None and cN[0]["who"]["on"] is True
      and cN[0]["enabled"] is False, (eN, cN))
off = dict(R_ALICE, who=dict(R_ALICE["who"], on=False))
c2, e2, _ = door([off])
check("a per-person rule switched off keeps its people, `on: false`", e2 is None and c2[0]["who"]["on"] is False and c2[0]["enabled"] is False, (e2, c2))
check("rule_on reads `who.on`, and plain `enabled` otherwise",
      P.rule_on(c[0]) is True and P.rule_on(c2[0]) is False and P.rule_on(c[1]) is True
      and P.rule_on({"enabled": False}) is False and P.rule_on({}) is True)
_, e3, _ = door([dict(R_ALICE, who={"on": True, "users": [], "groups": [], "peers": []})])
check("nobody chosen is refused (who_empty)", e3 and e3.startswith("Choose at least one person"), e3)
_, e4, _ = door([dict(R_ALICE, who={"on": True, "users": ["u-gone"], "groups": [], "peers": []})])
check("a NEW id that does not exist is refused", e4 is not None and "no longer exists" in e4, e4)
prev = [dict(R_ALICE, who={"on": True, "users": ["u-gone", "u1"], "groups": [], "peers": []})]
c5, e5, _ = door([dict(R_ALICE, who={"on": True, "users": ["u-gone", "u1"], "groups": [], "peers": []})], prev=prev)
check("a STORED id that no longer exists is dropped quietly (the interface stays savable)",
      e5 is None and c5[0]["who"]["users"] == ["u1"], (e5, c5))
prev6 = [dict(R_ALICE, who={"on": True, "users": ["u-gone"], "groups": [], "peers": []})]
c6, e6, _ = door([dict(R_ALICE, who={"on": True, "users": ["u-gone"], "groups": [], "peers": []})], prev=prev6)
check("…and when that empties the selection, the rule is kept for nobody rather than refused", e6 is None and
      c6[0]["who"] == {"on": True, "users": [], "groups": [], "peers": []}, (e6, c6))
c7, e7, _ = door([dict(R_ALICE, who={"on": True, "users": [], "groups": [], "peers": []})], prev=c6)
check("…and the next save of that stored empty selection is not locked out", e7 is None, e7)
_, e8, _ = door([{"enabled": False, "category": "all", "action": "exit", "node": "n2",
                  "who": {"on": True, "users": ["u1"], "groups": [], "peers": []}}])
check("\"everything else\" cannot be per-person (D10)", e8 is not None and "Everything else" in e8, e8)
_, e9, _ = door([dict(R_ALICE, who="u1")])
check("a `who` that is not an object of lists is refused (shape)", e9 is not None, e9)
c10, e10, _ = door([dict(R_ALICE, who={"on": True, "users": ["u1", "u1"], "groups": ["g1"], "peers": ["p5"]})])
check("groups and single devices are kept, lists sorted and unique", e10 is None and
      c10[0]["who"] == {"on": True, "users": ["u1"], "groups": ["g1"], "peers": ["p5"]}, (e10, c10))

# ── 2. the readers ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[the readers — rule_on, a closed list]")
src = open(path, encoding="utf-8").read()
lines = src.splitlines()
raw = []
for i, ln in enumerate(lines):
    m = re.match(r"(\s*)for (\w+) in .*\.get\(\"routing\"\)", ln)
    if not m:
        continue
    ind, var = len(m.group(1)), m.group(2)
    for j in range(i + 1, min(i + 60, len(lines))):
        body = lines[j]
        if body.strip() and (len(body) - len(body.lstrip())) <= ind:
            break
        if re.search(r"\b%s\.get\(\"enabled\"|\b%s\[\"enabled\"\]" % (var, var), body):
            raw.append((j + 1, body.strip()[:90]))
check("no reader of a routing rule reads a raw `enabled` — they ask rule_on (T11)", not raw, raw)
check("…cascade_plan asks rule_on", "if not rule_on(r):" in src)
check("…mesh_need asks rule_on", "if rule_on(r) and r.get(\"action\") == \"exit\":" in src)
nodes = fleet([c[0]])
need = P.mesh_need(nodes, {"cas_legs": {}})
check("a live per-person exit rule keeps its demand-mode mesh link", frozenset(("n1", "n2")) in need, need)
nodes_off = fleet([c2[0]])
check("…and a switched-off one does not (it is off, not forgotten)",
      frozenset(("n1", "n2")) not in P.mesh_need(nodes_off, {"cas_legs": {}}))

# ── 3. the plan ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[the plan]")
SNAPS = {"n1": SNAP1, "n2": SNAP2}
plan = P.cascade_plan(fleet(c), SNAPS)
sm = [e for e in plan["n1"]["smart"] if e["subnet"] == "10.8.0.0/24"]
wid = P.who_wid("10.8.0.0/24", c[0]["who"])
check("the per-person entry carries its selection as `src` (12 hex)", sm and sm[0].get("src") == wid and re.fullmatch(r"[0-9a-f]{12}", wid), sm)
check("…the rule for everyone carries none", len(sm) == 2 and "src" not in sm[1], sm)
check("the selection id is stable when its lists are re-ordered, and per subnet",
      P.who_wid("10.8.0.0/24", {"users": ["u1", "u9"], "groups": ["g1"]}) == P.who_wid("10.8.0.0/24", {"groups": ["g1"], "users": ["u9", "u1"]})
      and P.who_wid("10.8.0.0/24", c[0]["who"]) != P.who_wid("10.20.0.0/24", c[0]["who"]))
check("…and the switch is not part of it (turning a row off and on keeps its set)",
      P.who_wid("10.8.0.0/24", dict(c[0]["who"], on=False)) == wid)
check("the fleet-wide plan never expands a selection — `_who` holds (subnet, who) only",
      plan["n1"].get("_who", {}).get(wid) == ("10.8.0.0/24", c[0]["who"]), plan["n1"].get("_who"))
check("a switched-off per-person rule produces no entry", not [e for e in (P.cascade_plan(fleet(c2), SNAPS).get("n1") or {}).get("smart", [])
                                                                if e["subnet"] == "10.8.0.0/24"])
plain = P.cascade_plan(fleet([c[1]]), SNAPS)
check("a plan with no `who` has no `_who` and no `src` anywhere",
      "_who" not in json.dumps({k: sorted(v) for k, v in plain.items()}) and '"src"' not in json.dumps(plain, default=str), plain["n1"].keys())

# ── 4. the sync: per-node resolution ───────────────────────────────────────────────────────────────────────────────────────
print("\n[the sync]")
def resolve(rules, snap=SNAP1, roster=ROSTER):
    pl = P.cascade_plan(fleet(rules), {"n1": snap, "n2": SNAP2})["n1"]
    return P.who_plan_for_node(pl, roster, "n1", snap) if pl.get("_who") else pl
def rule(**who):
    return dict(c[0], who={"on": True, "users": [], "groups": [], "peers": [], **who})
r_u1 = resolve([rule(users=["u1"]), c[1]])
w_wg = P.who_wid("10.8.0.0/24", rule(users=["u1"])["who"])
check("a user resolves to their devices on THIS interface, as (device, /32) pairs",
      r_u1["srcs"].get(w_wg) == [["wg0", "10.8.0.5/32"], ["wg0", "10.8.0.6/32"]], r_u1["srcs"])
check("…not their device on another node", "10.9.0.5/32" not in json.dumps(r_u1["srcs"]))
w_wA = P.who_wid("10.20.0.0/24", rule(users=["u1"])["who"])
w_wB = P.who_wid("10.21.0.0/24", rule(users=["u1"])["who"])
check("a keyless device on a VOUCHED build is its read-back address on the server's device",
      r_u1["srcs"].get(w_wA) == [["wdttA", "10.20.0.5/32"]], r_u1["srcs"].get(w_wA))
check("a keyless device on an UNVOUCHED build is in no set (it could send any source)",
      w_wB not in r_u1["srcs"] and "10.21.0." not in json.dumps(r_u1["srcs"]), r_u1["srcs"].get(w_wB))
check("…so that interface's per-person entry is withheld (it would reach nobody)",
      not [e for e in r_u1["smart"] if e.get("src") == w_wB], [e for e in r_u1["smart"] if e.get("src")])
w_g = P.who_wid("10.8.0.0/24", rule(groups=["g1"])["who"])
r_g = resolve([rule(groups=["g1"])])
check("a group resolves to its members' devices — an expired member left out",
      r_g["srcs"].get(w_g) == [["wg0", "10.8.0.7/32"]], r_g["srcs"])
check("…and a blocked device of a member left out too", "10.8.0.11" not in json.dumps(r_g["srcs"]))
r_p = resolve([rule(peers=["p5"])])
check("a single device resolves to itself", r_p["srcs"].get(P.who_wid("10.8.0.0/24", rule(peers=["p5"])["who"])) == [["wg0", "10.8.0.9/32"]],
      r_p["srcs"])
r_dis = resolve([rule(users=["u3"]), c[1]])
check("a selection of nobody here (a blocked user) withholds its entries — never everyone",
      not [e for e in r_dis["smart"] if e.get("src")] and [e for e in r_dis["smart"] if not e.get("src")] and not r_dis["srcs"], r_dis["smart"])
check("…and takes its category's CIDRs off the wire with it",
      all(cat in {e["category"] for e in r_dis["smart"]} for cat in (r_dis.get("cidrs") or {})), (r_dis.get("cidrs"), r_dis["smart"]))
new_dev = copy.deepcopy(ROSTER)
new_dev["peers"]["p11"] = {"id": "p11", "user_id": "u1", "title": "new phone", "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.12"}]}
check("a user's NEW device is covered on the next sync with no edit",
      ["wg0", "10.8.0.12/32"] in resolve([rule(users=["u1"])], roster=new_dev)["srcs"].get(w_wg, []))
old = dict(SNAP1, smartroute={"mode": "kernel"})
r_old = resolve([rule(users=["u1"]), c[1]], snap=old)
check("a node that does not report `src` gets NO per-person entry (D4) — it would build it for the whole subnet",
      not [e for e in r_old["smart"] if e.get("src")] and not r_old.get("srcs"), r_old["smart"])
check("…while the rule for everyone still reaches it", [e for e in r_old["smart"] if not e.get("src")], r_old["smart"])
iss = [x["error"] for x in P._node_issues(fleet([rule(users=["u1"])])["n1"], old)]
check("…and its card says it needs an update, naming it", any("node-one needs an update to route per person" in x for x in iss), iss)
check("a capable node's card says nothing of it",
      not any("route per person" in x["error"] for x in P._node_issues(fleet([rule(users=["u1"])])["n1"], SNAP1)))
check("a node that has not reported its smart status is not called old",
      not any("route per person" in x["error"] for x in P._node_issues(fleet([rule(users=["u1"])])["n1"], {})))
hsrc = open(path, encoding="utf-8").read()
# the window and the chip ask the SAME reader (`who_report`), per interface
nc = copy.deepcopy(SNAP1)
nc["wdtt"][0]["passwords"]["pwC"] = {}                         # a keyless device with no address yet
ro_c = copy.deepcopy(ROSTER)
ro_c["peers"]["p12"] = {"id": "p12", "user_id": "u1", "title": "wdtt new", "wdtt_password": "pwC",
                        "targets": [{"node": "n1", "iface": "wdttA", "type": "wdtt"}]}
rep_wg, rep_wA, rep_wB = (P.who_report(ro_c, "n1", nc, ifn, [{"users": ["u1"]}])[0] for ifn in ("wg0", "wdttA", "wdttB"))
check("the report counts a user's wg devices on THIS interface as in the set",
      rep_wg == {"devices": {"p1": "ok", "p2": "ok"}, "people": 1}, rep_wg)
check("…a vouched keyless device as in the set, one with no address yet as `soon`",
      rep_wA["devices"] == {"p7": "ok", "p12": "soon"}, rep_wA)
check("…and a device on an unvouched build as `no` (can't be told apart)", rep_wB["devices"] == {"p8": "no"}, rep_wB)
rep_g = P.who_report(ROSTER, "n1", SNAP1, "wg0", [{"groups": ["g1"]}, {"peers": ["p5", "p10"]}])
check("a group counts its live members' devices and names its existing people; a blocked device is not counted",
      rep_g[0] == {"devices": {"p3": "ok"}, "people": 2} and rep_g[1] == {"devices": {"p5": "ok"}, "people": 0}, rep_g)
rep_old = P.who_report(ROSTER, "n1", dict(SNAP1, smartroute={"mode": "kernel"}), "wg0", [{"users": ["u1"]}])[0]
check("on a node that reports without `src` the report says what the sync does: every device `no`, and why (D4)",
      rep_old == {"devices": {"p1": "no", "p2": "no"}, "people": 1, "node_old": True}, rep_old)
check("…a capable node's report carries no such flag, and a node not heard from yet is not called old",
      "node_old" not in rep_wg and "node_old" not in P.who_report(ROSTER, "n1", {}, "wg0", [{"users": ["u1"]}])[0])
bad = copy.deepcopy(ROSTER)
bad["peers"]["p13"] = {"id": "p13", "user_id": "u1", "title": "adopted", "targets": [{"node": "n1", "iface": "wg0", "ip": "(none)"}]}
bad["peers"]["p14"] = {"id": "p14", "user_id": "u1", "title": "spaced", "targets": [{"node": "n1", "iface": "wg0", "ip": " 10.8.0.14"}]}
try:
    r_bad, raised = resolve([rule(users=["u1"])], roster=bad), ""
except Exception as x:
    r_bad, raised = {}, "%s: %s" % (type(x).__name__, x)
check("a malformed roster address (an adopted \"(none)\") is no source — the sync does not raise",
      not raised and ["wg0", "10.8.0.5/32"] in (r_bad.get("srcs") or {}).get(w_wg, []) and "(none)" not in json.dumps(r_bad.get("srcs")),
      raised or r_bad.get("srcs"))
check("…and a padded one is read as its address", ["wg0", "10.8.0.14/32"] in (r_bad.get("srcs") or {}).get(w_wg, []), r_bad.get("srcs"))
check("the report is its own on-demand endpoint, not the poll path",
      'path == "/api/routing/who"' in hsrc and hsrc.count("who_report(") == 2)

# the wire: `smart.srcs` rides the reply only when non-empty
check("the reply carries `smart.srcs` only when something resolved",
      '**({"srcs": my_plan["srcs"]} if my_plan.get("srcs") else {})' in hsrc)
check("the handler resolves only when the slice names people (zero cost otherwise)",
      'if my_plan.get("_who"):' in hsrc and "my_plan = who_plan_for_node(my_plan, roster, nid, snap)" in hsrc)

# ── 5. the old tab ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[the old tab — routing_v]")
deps = {"panel_settings": {}, "node_snaps": SNAPS, "roster_path": os.path.join(TMP, "users.json")}
json.dump(ROSTER, open(deps["roster_path"], "w"))
def save(rec, body):
    rec = copy.deepcopy(rec)
    return P._apply_egress_mode(rec, body, fleet([]), "n1", deps), rec
stored = {"egress_mode": "smart", "routing": [c[0], c[1]]}
old_tab_rows = [{"enabled": False, "category": "custom", "targets": "203.0.113.0/24", "action": "exit", "node": "n2"}, R_ALL]
(err, _), after = save(stored, {"egress_mode": "smart", "routing": old_tab_rows})
check("an old tab's save over a stored per-person rule is refused (routing_stale)",
      err is not None and "older than the panel" in err and after["routing"] == stored["routing"], err)
(err, _), after = save(stored, {"routing": old_tab_rows})
check("…the rule-only save too", err is not None and "older than the panel" in err, err)
(err, _), after = save(stored, {"egress_mode": "smart", "routing": [c[0], c[1]], "routing_v": 2})
check("the new SPA's save (routing_v: 2) goes through and keeps the people", err is None and after["routing"][0].get("who"), err)
(err, _), after = save({"egress_mode": "smart", "routing": [c[1]]}, {"egress_mode": "smart", "routing": old_tab_rows})
check("a list with no `who` still saves from an old tab (a fleet not using this notices nothing)", err is None, err)
(err, _), after = save(stored, {"egress_mode": "direct"})
check("an old tab switching the mode away keeps the stored list, untouched", err is None and after["routing"] == stored["routing"], err)
check("WDTT and csqtt saves share the helper (so they are refused the same way)",
      hsrc.count("_eerr, _edrop = _apply_egress_mode(inst, body, nodes, nid, deps)") == 2)
check("every door caller hands `_validate_routing` the roster when rules name people",
      hsrc.count("roster=_routing_roster(body.get(\"routing\"), deps)") == 3)

# ── 6. a stored selection of the wrong shape (hand-edited, imported) names nobody — it never raises on the sync path ─────────
print("\n[a malformed stored selection]")
for bad in ({"on": True, "users": 5}, {"on": True, "users": [["u1"]], "groups": "g1"}, {"on": True, "peers": {"p1": 1}}):
    try:
        pl = P.cascade_plan(fleet([{"enabled": False, "category": "custom", "cidrs": ["203.0.113.0/24"], "action": "direct",
                                    "who": bad}]), SNAPS, {})
        my = pl.get("n1") or {}
        res = P.who_plan_for_node(my, ROSTER, "n1", SNAP1) if my.get("_who") else my
        ok = not [e for e in (res.get("smart") or []) if e.get("src")]
        err = ""
    except Exception as e:
        ok, err = False, "%s: %s" % (type(e).__name__, e)
    check("cascade_plan and the sync's resolution survive %s — and the rule reaches nobody" % json.dumps(bad), ok, err)
try:
    rep_ = P.who_report(ROSTER, "n1", SNAP1, "wg0", [{"users": 5}, {"groups": [["x"]]}])
    err = "" if all(r["devices"] == {} and r["people"] == 0 for r in rep_) else rep_
except Exception as e:
    err = "%s: %s" % (type(e).__name__, e)
check("the Rule settings report answers a malformed selection with nobody (no 500)", not err, err)

# ── 7. the owner index resolves exactly what walking every device did (random rosters, against the old loop) ──────────────
print("\n[the owner index against the old per-selection walk]")
import ipaddress, random
def ref_srcs(my, roster, node_id, snap):                        # the resolver as it was before the index — the reference
    srcs = {}
    if ((snap or {}).get("smartroute") or {}).get("src"):
        here = P._who_here(roster, node_id, snap)
        for wid, (S, who) in my["_who"].items():
            (uids, pids), net, got = P._who_names(roster, who), ipaddress.ip_network(S, strict=False), set()
            for pid, (uid, ts) in here.items():
                if pid in pids or (uid and uid in uids):
                    got |= {(d, a) for _ifn, prs, _why in ts for d, a in prs if ipaddress.ip_address(a.split("/")[0]) in net}
            if got:
                srcs[wid] = sorted([d, a] for d, a in got)
    return srcs
def ref_report(roster, node_id, snap, iface, whos):
    here, out = P._who_here(roster, node_id, snap), []
    old = bool(snap) and not ((snap.get("smartroute") or {}).get("src"))
    for who in whos:
        uids, pids = P._who_names(roster, who if isinstance(who, dict) else {})
        dev = {}
        for pid, (uid, ts) in here.items():
            if pid in pids or (uid and uid in uids):
                for ifn, prs, why in ts:
                    if ifn == iface:
                        dev[pid] = "no" if old else "ok" if prs else "no" if why in ("unenforced", "raw_excluded") else "soon"
        out.append(dev)
    return out
rng, bad = random.Random(7), []
for case in range(300):
    U, G, D = rng.randint(1, 12), rng.randint(0, 4), rng.randint(0, 40)
    users = {"u%d" % i: {"id": "u%d" % i, "name": "u", **({"disabled": True} if rng.random() < .1 else {})} for i in range(U)}
    groups = {"g%d" % i: {"name": "g", "users": rng.sample(sorted(users), rng.randint(0, U))} for i in range(G)}
    peers = {}
    for i in range(D):
        tg = [{"node": rng.choice(["n1", "n1", "n2"]), "iface": rng.choice(["wg0", "wg0", "awg1"]),
               "ip": rng.choice(["10.8.0.%d" % rng.randint(2, 250), "10.9.0.%d" % rng.randint(2, 250), "(none)", ""])}
              for _ in range(rng.randint(1, 2))]
        peers["p%d" % i] = {"id": "p%d" % i, **({"user_id": rng.choice(sorted(users))} if rng.random() < .85 else {}), "targets": tg,
                            **({"disabled": True} if rng.random() < .05 else {})}
    ro = {"users": users, "groups": groups, "peers": peers}
    whos = [{"users": rng.sample(sorted(users), rng.randint(0, min(3, U))), "groups": rng.sample(sorted(groups), rng.randint(0, G)),
             "peers": rng.sample(sorted(peers), rng.randint(0, min(3, D))) + (["gone"] if rng.random() < .2 else [])} for _ in range(4)]
    my = {"smart": [], "_who": {"%012x" % i: (rng.choice(["10.8.0.0/24", "10.8.0.0/16", "10.9.0.0/24"]), w) for i, w in enumerate(whos)}}
    snap = {"smartroute": {"src": 1}}
    try:                                                        # a raise is a mismatch, reported — not a crash that hides the rest
        got, want = P.who_plan_for_node(my, ro, "n1", snap)["srcs"], ref_srcs(my, ro, "n1", snap)
        rg = [r["devices"] for r in P.who_report(ro, "n1", snap, "wg0", whos)]
        rw = ref_report(ro, "n1", snap, "wg0", whos)
    except Exception as e:
        bad.append((case, "raised %s: %s" % (type(e).__name__, e))); continue
    if got != want or rg != rw or [list(x) for x in rg] != [list(x) for x in rw]:
        bad.append((case, got, want) if got != want else (case, rg, rw))
check("300 random rosters: the sync's sources and the report are exactly the old walk's (same pairs, same devices, same order)",
      not bad, bad[:1])

print()
if PLANT:
    print("PLANT %s — %d check(s) red: %s" % (PLANT, len(FAILS), FAILS[:4]))
    sys.exit(0 if FAILS else 1)
print(("FAILED (%d): " % len(FAILS) + ", ".join(FAILS)) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
