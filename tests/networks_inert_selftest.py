#!/usr/bin/env python3
"""THE D1 GATE for the networks capability (docs/NETWORKS-PLAN.md §9 — "the most important gate here").

Every feature in that plan is INERT WHEN UNUSED. With no network declared anywhere:

  [1] `desired_for_node()` emits BYTE-IDENTICAL output to what it emitted before networks existed — checked
      against a frozen copy of that function, key order included, over a roster built to hit every branch it
      had (blocked user, expired peer, unassigned, keyless, several targets, a slash in a stored ip).
  [2] …and the new planning is never even entered — `node_networks` is booby-trapped.
  [3] a roster that DOES declare networks is still byte-identical for a node too old to guard itself, and for a
      caller holding no snapshot (the transfer fingerprint). And a control: onto a node that can guard itself,
      it is NOT identical — otherwise [1]–[3] would pass on a function that ignored networks entirely.
  [4] on the node, the half a datapath-only test misses (§4.12): the ACL filter hands back the very object it
      was given and the route reconciler executes NO SUBPROCESS AT ALL, and the cascade's signature and
      rebuild are exactly what they were.

Hermetic. Run: python3 tests/networks_inert_selftest.py            (0 = pass)
     --perturb   drops the presence gate (a node without net_deps is treated as able to guard itself) and
                 expects RED on [3].
     --perturb-probe   has the panel put a reachability test in every sync reply and expects RED on [5].
     --perturb-share   has the panel restrict every carried network and expects RED on [6].
     --perturb-reach   has the panel guard an interface on a node where every level is Everyone and expects RED on [7].

  [5] P4: with no reachability test asked for, the panel's reply carries no `net_probe`, the node starts no thread
      and forks nothing, and the snapshot carries no answer.
  [6] P5: with no network restricted, the panel computes and sends no `net_share`, and the node asks the kernel ONCE
      per process whether a table is left over, then forks nothing — not in the ACL pass, not in the routing pass —
      hands `reconcile` the very object it was given, and reports nothing.
"""
import importlib.machinery, importlib.util, ipaddress, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_PROBE = "--perturb-probe" in sys.argv
PERTURB_SHARE = "--perturb-share" in sys.argv
PERTURB_REACH = "--perturb-reach" in sys.argv

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
N = load("swgnoded", NODED)

if PERTURB:
    _ref = P.network_subnet_refusal
    P.network_subnet_refusal = lambda *a, **k: (lambda r: (None, "") if r[0] == "node_too_old" else r)(_ref(*a, **k))


def FROZEN_desired_for_node(roster, node_id):
    """`desired_for_node` exactly as it was at dev 1b00aeb, before networks. Do not edit: it is the reference."""
    users = roster.get("users") or {}
    nowv = int(time.time())
    out = {}
    for p in (roster.get("peers") or {}).values():
        if not isinstance(p, dict):
            continue
        u = users.get(p.get("user_id")) or {}
        if p.get("disabled") or u.get("disabled") or P.is_expired(p, nowv) or P.is_expired(u, nowv):
            continue
        uname = u.get("name", "")
        name = " · ".join(x for x in (uname, p.get("title", "")) if x)
        for t in p.get("targets", []):
            if t.get("node") != node_id:
                continue
            if P._is_self_contained_target(t):
                continue
            iface = t.get("iface") or ""
            if not iface:
                continue
            ip = (t.get("ip") or "").split("/")[0]
            out.setdefault(iface, []).append({
                "public_key": p.get("pubkey"),
                "allowed_ips": (ip + "/32") if ip else "",
                "preshared_key": p.get("psk") or "none",
                "name": name,
            })
    return out


PAST = int(time.time()) - 86400
ROSTER = {"users": {"u1": {"name": "Alice"}, "u2": {"name": "Bob", "disabled": True},
                    "u3": {"name": "Carol", "expiry": PAST}},
          "peers": {
              "p1": {"id": "p1", "user_id": "u1", "pubkey": "a" * 43 + "=", "psk": "k1", "title": "laptop",
                     "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.2", "type": "awg"},
                                 {"node": "n1", "iface": "wg1", "ip": "10.9.0.2/32", "type": "wg"},
                                 {"node": "n2", "iface": "awg0", "ip": "10.8.1.2", "type": "awg"}]},
              "p2": {"id": "p2", "user_id": "u2", "pubkey": "b" * 43 + "=", "targets": [
                     {"node": "n1", "iface": "awg0", "ip": "10.8.0.3", "type": "awg"}]},                    # blocked user
              "p3": {"id": "p3", "user_id": "u3", "pubkey": "c" * 43 + "=", "targets": [
                     {"node": "n1", "iface": "awg0", "ip": "10.8.0.4", "type": "awg"}]},                    # expired user
              "p4": {"id": "p4", "user_id": None, "pubkey": "d" * 43 + "=", "expiry": PAST, "targets": [
                     {"node": "n1", "iface": "awg0", "ip": "10.8.0.5", "type": "awg"}]},                    # expired peer
              "p5": {"id": "p5", "user_id": None, "pubkey": "e" * 43 + "=", "title": "router", "targets": [
                     {"node": "n1", "iface": "awg0", "ip": "10.8.0.6", "type": "awg"}]},                    # unassigned
              "p6": {"id": "p6", "user_id": "u1", "wdtt_password": "x", "targets": [
                     {"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},                                    # keyless
              "p7": {"id": "p7", "user_id": "u1", "pubkey": "f" * 43 + "=", "targets": [
                     {"node": "n1", "iface": "", "ip": "10.8.0.8", "type": "awg"},                          # no iface
                     {"node": "n1", "iface": "awg0", "ip": "", "type": "awg"}]},                            # no ip
              "p8": "not a dict",
          }}
SNAP = {"node_ips": ["203.0.113.5"], "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}},
                                                    "wg1": {"meta": {"subnet": "10.9.0.0/24"}}},
        "ether_gws": {"eth0": "203.0.113.1"},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True}}
OLD = {k: v for k, v in SNAP.items() if k != "net_deps"}
b = lambda x: json.dumps(x, ensure_ascii=False)          # key order MATTERS: that is what "byte-identical" means

print("\n[1] no network anywhere: byte-identical to the pre-networks function")
ref = b(FROZEN_desired_for_node(ROSTER, "n1"))
check("with no snapshot", b(P.desired_for_node(ROSTER, "n1")) == ref)
check("with a snapshot from a node that CAN guard itself", b(P.desired_for_node(ROSTER, "n1", SNAP)) == ref)
check("with a snapshot from an old node", b(P.desired_for_node(ROSTER, "n1", OLD)) == ref)
check("…and for the other node too", b(P.desired_for_node(ROSTER, "n2", SNAP)) == b(FROZEN_desired_for_node(ROSTER, "n2")))

print("\n[2] the planning is never entered")
_nn = P.node_networks
def _trap(*a, **k):
    raise AssertionError("node_networks entered with no network declared")
P.node_networks = _trap
try:
    P.desired_for_node(ROSTER, "n1", SNAP)
    check("desired_for_node with no routes never calls node_networks", True)
except AssertionError as e:
    check("desired_for_node with no routes never calls node_networks", False, e)
P.node_networks = _nn

print("\n[3] a roster WITH networks: identical where nothing may lower, different where it may")
RN = json.loads(json.dumps(ROSTER))
RN["peers"]["p5"]["routes"] = ["192.168.50.0/24"]
ref_n = b(FROZEN_desired_for_node(RN, "n1"))
check("an OLD node (no net_deps) — byte-identical, ACL included", b(P.desired_for_node(RN, "n1", OLD)) == ref_n)
check("no snapshot (the transfer fingerprint) — byte-identical", b(P.desired_for_node(RN, "n1")) == ref_n)
check("CONTROL: a node that can guard itself DOES receive the network",
      b(P.desired_for_node(RN, "n1", SNAP)) != ref_n and
      any(x["allowed_ips"] == "10.8.0.6/32,192.168.50.0/24" for x in P.desired_for_node(RN, "n1", SNAP)["awg0"]))

print("\n[4] the node: nothing forked, nothing different")
TMP = tempfile.mkdtemp(prefix="netinert-")
def conf(name, addr):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\n" % addr)
    return p
CFG = {"interfaces": {"awg0": {"conf": conf("awg0", "10.8.0.1/24")}, "wg1": {"conf": conf("wg1", "10.9.0.1/24")}}}
def hexle(ip):
    a = [int(x) for x in ip.split(".")]
    return "%02X%02X%02X%02X" % (a[3], a[2], a[1], a[0])
route = os.path.join(TMP, "route")
with open(route, "w") as f:
    f.write("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n")
    for dev, pre in (("eth0", "0.0.0.0/0"), ("eth0", "203.0.113.0/24"), ("awg0", "10.8.0.0/24"), ("wg1", "10.9.0.0/24")):
        n = ipaddress.ip_network(pre)
        f.write("%s\t%s\t00000000\t0001\t0\t0\t0\t%s\t0\t0\t0\n" % (dev, hexle(str(n.network_address)), hexle(str(n.netmask))))
FORKS = []
N.run = lambda a, input_text=None, timeout=20: FORKS.append(a) or N.subprocess.CompletedProcess(a, 0, "", "")
N.current_allowed = lambda *a, **k: FORKS.append(["<wg show dump>"]) or {}
desired = P.desired_for_node(ROSTER, "n1", SNAP)
check("net_filter_desired returns the SAME object", N.net_filter_desired(CFG, desired) is desired)
res = {"changed": 0, "errors": []}
check("reconcile_net_routes returns nothing", N.reconcile_net_routes(CFG, desired, res, _proc=route) == [] and res == {"changed": 0, "errors": []}, res)
check("…and executed NO subprocess at all (§4.12)", FORKS == [], FORKS)
FWD = [{"table": N.SWG_RT_BASE + 50, "subnet": "10.8.0.0/24", "via_iface": "swg_ab12"}]
check("the cascade want-signature is identical with no networks",
      N._cascade_want_sig(FWD, [], [], ()) == N._cascade_want_sig(FWD, [], [], (), nets=[], net_tables=[]))
check("the node's refusal state is empty, so the snapshot carries no net_refused key", N._NET["refused"] == {})

print("\n[5] P4, the reachability test: nobody asked, so nothing is sent — in either direction")
import inspect
if PERTURB_PROBE:
    P.net_probe_reply = lambda nid, now=None: {"id": "0" * 16, "iface": "awg0", "pubkey": "a" * 43 + "=", "addr": "192.168.50.5"}
P._NET_PROBES.clear()
check("the panel: with no test armed the sync reply's `net_probe` helper returns None", P.net_probe_reply("n1") is None)
check("…and a snapshot carrying no answer changes nothing", P.net_probe_absorb("n1", SNAP) is False and P._NET_PROBES == {})
_psrc = open(PANEL).read()
check("…and the reply names `net_probe` exactly once, behind that helper's result",
      _psrc.count('"net_probe":') == 1 and '**({"net_probe": _nprobe} if _nprobe else {})' in _psrc)
def _no_thread(*a, **k):
    raise AssertionError("a probe thread was started with no test requested")
_thr = N.threading.Thread
N.threading.Thread = _no_thread
N._PROBE.update(id="", result=None, at=0.0)
del FORKS[:]
try:
    for _r in (None, {}, {"id": ""}):
        N.net_probe_take(CFG, _r, desired)
    check("the node: no test in the reply ⇒ no thread, no fork", FORKS == [], FORKS)
except AssertionError as e:
    check("the node: no test in the reply ⇒ no thread, no fork", False, e)
N.threading.Thread = _thr
check("…nothing waits for the snapshot", N.net_probe_status() is None)
_bs = inspect.getsource(N.build_snapshot)
check("…and the snapshot adds `net_probe` only under that answer", 'if _probe:' in _bs and 'snap["net_probe"] = _probe' in _bs
      and _bs.count('"net_probe"') == 1)

print("\n[6] P5, sharing: nothing restricted, so nothing computed, sent, installed or forked")
if PERTURB_SHARE:
    P.net_share_for_node = lambda roster, nid, carry: [{"peer": pid, "from": []} for pid in carry]
check("the panel: a roster with networks but no share yields no `net_share` for the node",
      P.net_share_for_node(RN, "n1", P.node_networks(RN, "n1", SNAP)["carry"]) == [])
check("…and the reply names `net_share` only behind that result, computed only when a peer restricts one",
      '**({"net_share": _nshare} if _nshare else {})' in _psrc and _psrc.count('"net_share":') == 1
      and 'q.get("routes") and isinstance(q.get("share"), dict)' in _psrc)
N._SHARE.update(probed=False, installed=False, sig=None, plan=None, status=None)
N.run = lambda a, input_text=None, timeout=20: FORKS.append(a) or N.subprocess.CompletedProcess(a, 1, "", "")
del FORKS[:]
_d = P.desired_for_node(RN, "n1", SNAP)
res = {"changed": 0, "errors": []}
check("the node, first pass: the SAME object handed on to reconcile",
      N.reconcile_net_share(CFG, N.net_filter_desired(CFG, desired), None, res) is desired)
check("…after exactly ONE kernel look (a restriction lifted while the daemon was down must not keep dropping)",
      FORKS == [["nft", "list", "table", "inet", "swg_share"]], FORKS)
del FORKS[:]
for _ in range(3):
    N.reconcile_net_share(CFG, desired, None, res)
    N.net_share_verify(res)
check("…every later pass, ACL and routing alike: NO subprocess", FORKS == [], FORKS)
check("…nothing to report", N._SHARE["status"] is None and res == {"changed": 0, "errors": []}, (N._SHARE, res))
check("…and the snapshot adds `net_share` only under a status", 'if _SHARE["status"]:' in _bs and _bs.count('"net_share"') == 1)

print("\n[7] DEVICE ACCESS: every level an explicit Everyone, so nothing computed, sent, installed or forked (docs/DEVICE-ACCESS-PLAN.md §10)")
if PERTURB_REACH:
    P.dev_reach_guarded = lambda node_rec, snap: {"wg0": "user"}
_SNAP_R = dict(SNAP, net_deps=dict(SNAP.get("net_deps") or {}, reach=1))
_ALL_EVERYONE = {"ifaces": {"wg0": {"reach": "everyone"}, "awg0": {"reach": "everyone"}, "swg_x": {"system": True}},
                 "wdtt": {"wdtt1": {"reach": "everyone"}}, "csqtt": {"csqtt1": {"reach": "everyone"}}}
_groups_real = P.roster_groups
def _groups_trap(roster):
    raise AssertionError("the device-access pass walked the roster with every level at Everyone")
P.roster_groups = _groups_trap
try:
    check("the panel: every level an explicit Everyone ⇒ no `dev_reach` — and the roster is never walked",
          P.dev_reach_for_node(RN, _ALL_EVERYONE, "n1", _SNAP_R, {}) == {})
except AssertionError as e:
    check("the panel: every level an explicit Everyone ⇒ no `dev_reach` — and the roster is never walked", False, e)
try:
    check("…and a node that cannot enforce it gets none either, whatever its levels (A10)",
          P.dev_reach_for_node(RN, {"ifaces": {"wg0": {}}}, "n1", SNAP, {}) == {})
except AssertionError as e:
    check("…and a node that cannot enforce it gets none either, whatever its levels (A10)", False, e)
P.roster_groups = _groups_real
check("…and the reply names `dev_reach` exactly once, behind that result",
      _psrc.count('"dev_reach":') == 1 and '**({"dev_reach": _dreach} if _dreach else {})' in _psrc)
N._REACH.update(probed=False, installed=False, sig=None, plan=None, status=None, seen={}, loaded=[], base={}, live={}, since=0)
del FORKS[:]
res = {"changed": 0, "errors": []}
N.reconcile_dev_reach(CFG, None, res)
check("the node, first pass: exactly ONE kernel look (a protection lifted while the daemon was down must not keep dropping)",
      FORKS == [["nft", "list", "table", "inet", "swg_reach"]], FORKS)
del FORKS[:]
for _ in range(3):
    N.reconcile_dev_reach(CFG, None, res)
    N.dev_reach_verify(res)
check("…every later pass, reply and routing alike: NO subprocess", FORKS == [], FORKS)
check("…nothing to report", N._REACH["status"] is None and res == {"changed": 0, "errors": []}, (N._REACH["status"], res))
check("…and the snapshot adds `dev_reach` only under a status", 'if _REACH["status"]:' in _bs and _bs.count('"dev_reach"') == 1)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
