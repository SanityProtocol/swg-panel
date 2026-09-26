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
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANTS = {
    "--perturb": ('''            if isinstance(_m, dict) and str(_m.get(nid) or "") == _p["from"]:
                _m.pop(nid, None)''', '''            pass'''),
    "--perturb-plan": ('''            if _v and _bind_swap_transform(_v, ctx) != _v:''', '''            if False:'''),
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

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but %s was planted and should have gone RED" % MODE if MODE else ""))
sys.exit(2 if MODE else 0)
