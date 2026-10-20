#!/usr/bin/env python3
"""Self-test — A REBUILD RESETS THE ADDRESSES OTHER SERVERS PINNED ON THE OLD BOX.

P2's exit IP lets a rule that forwards to a far server choose which of that server's addresses the traffic leaves
by. The choice is stored on the SENDING server — `routing_exit_ips[far]` per interface / WDTT / csqtt server and
`default_routing_exit_ips[far]` for its default list — and names the far server's OWN address. Rebuild moves the far
server to a new box and resets every address of the old box in the far server's own record (`bind_swap`), but these
pins live on other servers' records, and nothing touched them: after a rebuild every pinned rule had the new box SNAT
to an address it does not own, which the kernel accepts and no reply ever comes back to (found by the 1.8.8
qualification's migration-box-fields audit).

The plan now lists them with the same rule as the node's own sources (kept only when the rebuild names the new box's
address), the preflight shows them in its Addresses section, and the rebuild clears exactly those. Driven through the
REAL `api()` handler on a temp fleet — no text matching.

Run: python3 tests/rebuild_pin_reset_selftest.py     (0 = pass)
     --perturb        the handler applies nothing (the preview still lists them)        → RED
     --perturb-plan   the plan does not look at other servers' pins                     → RED
     --perturb-dial   the rebuild keeps every parked mesh dial setting (plan §8 round 14)  → RED [4]
  [5] q189 PR-1 / PR-5 — a turn server's DIAL host survives a rebuild (4eec67e made `listen` what clients dial, and the
      node binds only what lands on the box): a WDTT dialled at a DDNS name, a csqtt at a NAT front the box never
      reported and a vk-turn-proxy at the DDNS name are KEPT, only the old box's own address resets — and the proxy's
      "Listen on" pin (`bind_ip`) is captured and re-issued, kept when the rebuilt box reports that address, Auto when not.
     --perturb-turnhost   the wdtt/csqtt `listen` rows take the bind rule again                     → RED [5]
     --perturb-proxyhost  the captured proxy `listen` takes the bind rule again                     → RED [5]
     --perturb-proxypin   the capture drops the proxy's `bind_ip`                                   → RED [5]
     --perturb-reissuepin the re-issue drops it                                                     → RED [5]
     --perturb-pinkeep    the re-issue keeps a pin the rebuilt box does not have                    → RED [5]
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANTS = {
    "--perturb": ('''            if isinstance(_m, dict) and str(_m.get(nid) or "") == _p["from"]:
                _m.pop(nid, None)''', '''            pass'''),
    "--perturb-plan": ('''            if _v and _bind_swap_transform(_v, ctx) != _v:
                pin_resets.append''', '''            if False:
                pin_resets.append'''),
    "--perturb-dial": ('''                mesh_link_unpark(nodes, _d["node"], _d["peer"], _d["key"])''', '''                pass'''),
    "--perturb-turnhost": ('''        ("residue.wdtt.*.listen",      "host_swap",''', '''        ("residue.wdtt.*.listen",      "bind_swap",'''),
    "--perturb-proxyhost": ('''        _tp_now = _host_swap_transform(_tp_was, ctx) or''', '''        _tp_now = _bind_swap_transform(_tp_was, ctx) or'''),
    "--perturb-proxypin": ('''"title": tp.get("title") or "", **({"bind_ip": _bip} if _bip and bind_ip_ok(_bip) else {})})''',
                           '''"title": tp.get("title") or ""})'''),
    "--perturb-reissuepin": ('''                                           **({"bind_ip": _bp} if _bp else {}), "at": int(time.time())})''',
                             '''                                           "at": int(time.time())})'''),
    "--perturb-pinkeep": ('''                _bp = _bind_swap_transform(_t.get("bind_ip") or "", {"after_ips": list(snap.get("node_ips") or [])})''',
                          '''                _bp = _t.get("bind_ip") or ""'''),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="rebuild-pins-")
path = PANEL
if MODE:
    src = open(PANEL, encoding="utf-8").read()
    old, new = PLANTS[MODE]
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    path = os.path.join(TMP, "planted-panel.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
_l = importlib.machinery.SourceFileLoader("swgpanel_rbp", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_rbp", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

X, N, Y = "a0a0a0a0a0a0", "b1b1b1b1b1b1", "c2c2c2c2c2c2"      # X is rebuilt; N pins addresses on X and on Y


def fixture(tag):
    d = os.path.join(TMP, tag); os.makedirs(os.path.join(d, "stats"), exist_ok=True)
    nodes = {
        X: {"id": X, "name": "far", "endpoint_host": "198.51.100.10", "token_hash": "x", "token_sha": "x",
            "stats_file": "stats-%s.json" % X, "ifaces": {}},
        Y: {"id": Y, "name": "other", "endpoint_host": "198.51.100.30", "token_hash": "y", "token_sha": "y",
            "stats_file": "stats-%s.json" % Y, "ifaces": {}},
        N: {"id": N, "name": "near", "endpoint_host": "198.51.100.20", "token_hash": "n", "token_sha": "n",
            "stats_file": "stats-%s.json" % N,
            "ifaces": {"wg0": {"egress_mode": "smart", "routing": [], "routing_exit_ips": {X: "198.51.100.10", Y: "198.51.100.30"}},
                       "wg1": {"egress_mode": "smart", "routing": [], "routing_exit_ips": {X: "198.51.100.11"}}},
            "wdtt": {"wdtt1": {"egress_mode": "smart", "routing": [], "routing_exit_ips": {X: "198.51.100.10"}}},
            "default_routing": [{"enabled": True, "category": "all", "action": "exit", "node": X}],
            "default_routing_exit_ips": {X: "198.51.100.11", Y: "198.51.100.30"}},
    }
    np_ = os.path.join(d, "nodes.json"); rp = os.path.join(d, "users.json")
    json.dump(nodes, open(np_, "w")); json.dump({"version": 1, "users": {}, "peers": {}}, open(rp, "w"))
    deps = {"fleet": {"nodes_path": np_, "roster_path": rp, "stats_dir": os.path.join(d, "stats")},
            "roster_path": rp, "nodes_path": np_, "stats_dir": os.path.join(d, "stats"),
            "panel_settings_path": os.path.join(d, "panel-settings.json"), "panel_settings": {},
            "node_snaps": {X: {"node_ips": ["198.51.100.10", "198.51.100.11"], "interfaces": {}},
                           N: {"node_ips": ["198.51.100.20"], "interfaces": {}},
                           Y: {"node_ips": ["198.51.100.30"], "interfaces": {}}},
            "node_seen": {}, "live_samples": {}, "now": lambda: int(time.time())}
    return deps


def pins(deps):
    n = json.load(open(deps["nodes_path"]))[N]
    return {"wg0": n["ifaces"]["wg0"].get("routing_exit_ips"), "wg1": n["ifaces"]["wg1"].get("routing_exit_ips"),
            "wdtt1": n["wdtt"]["wdtt1"].get("routing_exit_ips"), "default": n.get("default_routing_exit_ips")}


print("[1] the preview lists what the act clears — the old box's addresses, and only those")
deps = fixture("a")
st, r = P.api("GET", "/api/nodes/rebuild/preflight", {"node": [X]}, {}, deps)
rows = [a for a in ((r.get("data") or {}).get("address") or []) if str(a.get("path", "")).startswith("pin.")]
got = sorted((a["path"], a.get("from"), a.get("to")) for a in rows)
want = sorted([("pin.%s.wg0" % N, "198.51.100.10", ""), ("pin.%s.wg1" % N, "198.51.100.11", ""),
               ("pin.%s.wdtt1" % N, "198.51.100.10", ""), ("pin.%s.default" % N, "198.51.100.11", "")])
check("preflight 200", st == 200, (st, r.get("error")))
check("four pin rows: wg0, wg1, the WDTT server and the default list — each 'old address → auto'", got == want, got)
check("the pin on ANOTHER server (Y) is not listed", not any(Y in str(a.get("path")) for a in rows), rows)

print("\n[2] the rebuild clears exactly those")
st, r = P.api("POST", "/api/nodes/rebuild", {}, {"node": X, "supersede": False}, deps)
check("rebuild 200", st == 200, (st, r.get("error")))
after = pins(deps)
check("wg0: the pin on the rebuilt node is gone, the pin on Y is kept", after["wg0"] == {Y: "198.51.100.30"}, after["wg0"])
check("wg1: gone", after["wg1"] == {}, after["wg1"])
check("WDTT server: gone", after["wdtt1"] == {}, after["wdtt1"])
check("default list: gone, the pin on Y kept", after["default"] == {Y: "198.51.100.30"}, after["default"])
rows2 = [a for a in ((r.get("data") or {}).get("address") or []) if str(a.get("path", "")).startswith("pin.")]
check("the act's answer lists the same four rows as the preview", sorted((a["path"], a.get("from"), a.get("to")) for a in rows2) == want, rows2)

print("\n[3] a rebuild that names the new box's address keeps the pin on that address")
deps = fixture("b")
st, r = P.api("POST", "/api/nodes/rebuild", {}, {"node": X, "supersede": False, "assume": "198.51.100.10"}, deps)
after = pins(deps)
check("rebuild 200", st == 200, (st, r.get("error")))
check("wg0 and the WDTT server pinned 198.51.100.10 — the new box has it, so it stands",
      after["wg0"] == {X: "198.51.100.10", Y: "198.51.100.30"} and after["wdtt1"] == {X: "198.51.100.10"}, after)
check("wg1 and the default list pinned 198.51.100.11 — the new box does not, so back to Auto",
      after["wg1"] == {} and after["default"] == {Y: "198.51.100.30"}, after)

print("\n[4] a mesh link's dial settings naming the OLD box go back to Auto; every other one survives the rebuild (plan §8 round 14)")
deps = fixture("c")
nodes = json.load(open(deps["nodes_path"]))
P.reconcile_mesh(nodes, deps["node_snaps"], deps)
nodes[X]["links"][N]["dial_src"] = "198.51.100.10"        # X's own address — the new box has it (assume below): kept
nodes[X]["links"][Y]["dial_src"] = "198.51.100.11"        # X's own address the new box will NOT have: reset
nodes[X]["links"][Y]["dial_endpoint"] = "198.51.100.30"   # Y's address, dialled from X: not the old box's, kept
nodes[N]["links"][X]["dial_endpoint"] = "198.51.100.11"   # N dials the old box's .11: reset
nodes[N]["links"][X]["relay"] = {"mode": "relay"}          # N's relay on that leg: kept
nodes[Y]["links"][X]["dial_src"] = "198.51.100.30"        # Y's own address: kept
nodes[Y]["links"][X]["dial_endpoint"] = "203.0.113.5"     # X's NAT front, which X never reports: the endpoint rule keeps it
P.mesh_link_park(nodes, X, Y)                              # X's half to Y torn down earlier: its dial_src .11 is PARKED, not live
json.dump(nodes, open(deps["nodes_path"], "w"))
st, r = P.api("GET", "/api/nodes/rebuild/preflight", {"node": [X], "assume": ["198.51.100.10"]}, {}, deps)
mrows = sorted((a["path"], a.get("from")) for a in ((r.get("data") or {}).get("address") or []) if str(a.get("path", "")).startswith("mesh."))
check("the preview lists the two dial settings on the old box's .11, and only those",
      mrows == sorted([("mesh.%s.%s.dial_src" % (X, Y), "198.51.100.11"), ("mesh.%s.%s.dial_endpoint" % (N, X), "198.51.100.11")]), mrows)
st, r = P.api("POST", "/api/nodes/rebuild", {}, {"node": X, "supersede": False, "assume": "198.51.100.10"}, deps)
nn = json.load(open(deps["nodes_path"]))
g = lambda a, b, k: ((nn[a].get("links") or {}).get(b) or {}).get(k)
check("rebuild 200, links rebuilt", st == 200 and N in (nn[X].get("links") or {}) and Y in (nn[X].get("links") or {}), (st, r.get("error")))
check("reset: X's dial_src .11 toward Y (it was parked, not live), N's dial_endpoint .11 toward X",
      g(X, Y, "dial_src") is None and g(N, X, "dial_endpoint") is None, (g(X, Y, "dial_src"), g(N, X, "dial_endpoint")))
check("kept: X's dial_src .10 (the new box has it), X's dial_endpoint to Y, N's relay, Y's dial_src, and Y's dial_endpoint "
      "on X's NAT front (an address X never reported — the endpoint rule, review of f17cc1d)",
      g(X, N, "dial_src") == "198.51.100.10" and g(X, Y, "dial_endpoint") == "198.51.100.30"
      and g(N, X, "relay") == {"mode": "relay"} and g(Y, X, "dial_src") == "198.51.100.30" and g(Y, X, "dial_endpoint") == "203.0.113.5",
      (g(X, N, "dial_src"), g(X, Y, "dial_endpoint"), g(N, X, "relay"), g(Y, X, "dial_src"), g(Y, X, "dial_endpoint")))
check("nothing left parked", all("link_keep" not in nn[k] for k in nn), {k: nn[k].get("link_keep") for k in nn})

print("\n[5] a turn server's dial host survives a rebuild; a vk-turn-proxy's Listen-on pin is carried (q189 PR-1 / PR-5)")
SVC = "vk-turn-proxy-cacggghp-56010"


def fixture_turn(tag):
    deps = fixture(tag)
    nodes = json.load(open(deps["nodes_path"]))
    nodes[X].update(endpoint_host="myhome.ddns.net",
                    wdtt={"wdtt1": {"listen": "myhome.ddns.net:56000"}, "wdtt2": {"listen": "198.51.100.11:56200"}},
                    csqtt={"csqtt1": {"listen": "203.0.113.7:56100"}})       # a NAT front: never one of X's addresses
    json.dump(nodes, open(deps["nodes_path"], "w"))
    deps["node_snaps"][X]["turn_proxies"] = [{"service": SVC, "listen": "myhome.ddns.net:56010", "bind": "198.51.100.10:56010",
                                              "bind_ip": "198.51.100.10", "connect": "127.0.0.1:51820", "params": "",
                                              "title": "home"}]
    P.Handler.deps = deps
    return deps


class _Sync:            # the sync handler's `self`: the re-issue reads nothing of it but the request's headers
    headers = {}


def reissue(deps, node_ips):
    """The rebuilt box's first sync, through the real _node_sync_apply: it reports its addresses and no proxies."""
    snap = {"node_ips": node_ips, "interfaces": {}, "turn_proxies": []}
    deps["node_snaps"][X] = snap
    nodes = json.load(open(deps["nodes_path"]))
    try:
        P.Handler._node_sync_apply(_Sync(), X, nodes[X], nodes, snap, None)
    except Exception as e:
        return "raised %s: %s" % (type(e).__name__, e)
    return (json.load(open(deps["nodes_path"]))[X].get("turn") or {}).get(SVC)


deps = fixture_turn("t1")
st, r = P.api("GET", "/api/nodes/rebuild/preflight", {"node": [X]}, {}, deps)
arows = sorted((a["path"], a.get("from"), a.get("to")) for a in ((r.get("data") or {}).get("address") or [])
               if str(a.get("path", "")).startswith(("wdtt.", "csqtt.", "turn.")))
check("the preview resets only the old box's own address (wdtt2) — not the DDNS name, the NAT front or the proxy's name",
      st == 200 and arows == [("wdtt.wdtt2.listen", "198.51.100.11:56200", "0.0.0.0:56200")], (st, arows))
st, r = P.api("POST", "/api/nodes/rebuild", {}, {"node": X, "supersede": False}, deps)
rec = json.load(open(deps["nodes_path"]))[X]
got = ({k: v.get("listen") for k, v in (rec.get("wdtt") or {}).items()}, (rec.get("csqtt") or {}).get("csqtt1", {}).get("listen"))
check("the record keeps the WDTT's DDNS name and the csqtt's NAT front; the old box's address goes to every address",
      st == 200 and got == ({"wdtt1": "myhome.ddns.net:56000", "wdtt2": "0.0.0.0:56200"}, "203.0.113.7:56100"), (st, got))
cap = ((rec.get("rebuild") or {}).get("turn") or [{}])[0]
check("the captured vk-turn-proxy keeps its dial host and its Listen-on pin",
      cap.get("listen") == "myhome.ddns.net:56010" and cap.get("bind_ip") == "198.51.100.10", cap)
req = reissue(deps, ["198.51.100.10", "198.51.100.11"])
check("the same box back: the re-issued install dials the same host and binds the pinned address",
      isinstance(req, dict) and req.get("listen") == "myhome.ddns.net:56010" and req.get("bind_ip") == "198.51.100.10", req)
deps = fixture_turn("t2")
P.api("POST", "/api/nodes/rebuild", {}, {"node": X, "supersede": False}, deps)
req = reissue(deps, ["192.0.2.50"])
check("a new box without that address: the re-issue leaves the pin out — Auto (a pin the box does not carry is ignored "
      "by the node, and would show a stale address on the card)",
      isinstance(req, dict) and req.get("listen") == "myhome.ddns.net:56010" and "bind_ip" not in req, req)

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but %s was planted and should have gone RED" % MODE if MODE else ""))
sys.exit(2 if MODE else 0)
