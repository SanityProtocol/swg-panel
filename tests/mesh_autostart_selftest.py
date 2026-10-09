#!/usr/bin/env python3
"""Self-test — a mesh link whose device is lost while its conf remains is started again (q189 MESH-1). A real panel on a
scratch port, no auth; the nodes are played by POSTing snapshots to /api/node/sync.

The panel's bounded auto-start (three tries, an event each) skipped `system` (mesh) links because "they self-heal", and the
mesh self-heal re-creates only a link the node STOPS reporting — so a link reported down (a module unload, a failed boot
start, an outside `ip link del`) came back by nothing, for ever, every route through it refused (V-AWG §1.14, measured).

  [1] a mesh link reported down is started (the reply's iface_start, the attempt counted); a peer interface down is, as before
  [2] a link that is up is not; one with a delete staged (the mesh retiring it) is not; one with a create staged (the mesh
      re-creating it) is not

Run: python3 tests/mesh_autostart_selftest.py
     --plant system | pending   (exit 0 when caught)
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"system": ("            if not _e.get(\"down\") or _e.get(\"stopped\"):\n",
                     "            if not _e.get(\"down\") or _e.get(\"stopped\") or _ov.get(\"system\"):\n"),
          "pending": ("            if _mig or _ifn in _pending or (_ov.get(\"system\") and (_ifn in (node.get(\"create\") or {}) or _ifn in (node.get(\"delete\") or {}))):",
                      "            if _mig or _ifn in _pending:")}
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="mesh-autostart-")
server = SERVER
if PLANT:
    old, new = PLANTS[PLANT]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new))


def link(peer, ifc, sub, port):
    return {"iface": ifc, "subnet": sub, "address": sub.split("/")[0], "listen_port": port, "proto": "wg"}


now = int(time.time())
NODESET = {
    # a↔b: a's device lost (reported down), its conf kept; a's awg0 down too (the control: started as before); b's up
    "a": {"links": {"b": link("b", "swg_ab", "10.200.0.0/31", 10001)},
          "ifaces": {"swg_ab": {"system": True, "link_node": "b"}, "awg0": {}}},
    "b": {"links": {"a": link("a", "swg_ab", "10.200.0.0/31", 10001)}, "ifaces": {"swg_ab": {"system": True, "link_node": "a"}}},
    # c↔d: the mesh is retiring c's end (a delete staged), and it reads down while it goes
    "c": {"links": {"d": link("d", "swg_cd", "10.200.0.2/31", 10002)},
          "ifaces": {"swg_cd": {"system": True, "link_node": "d"}}, "delete": {"swg_cd": {"at": now}}},
    "d": {"links": {"c": link("c", "swg_cd", "10.200.0.2/31", 10002)}, "ifaces": {"swg_cd": {"system": True, "link_node": "c"}}},
    # e↔f: the mesh is re-creating e's end (a create staged)
    "e": {"links": {"f": link("f", "swg_ef", "10.200.0.4/31", 10003)},
          "ifaces": {"swg_ef": {"system": True, "link_node": "f"}},
          "create": {"swg_ef": {"cmd": ["wg"], "subnet": "10.200.0.4/31", "address": "10.200.0.4/31", "listen_port": 10003,
                                "mtu": 1420, "table": "off"}}},
    "f": {"links": {"e": link("e", "swg_ef", "10.200.0.4/31", 10003)}, "ifaces": {"swg_ef": {"system": True, "link_node": "e"}}},
}
state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({n: {"id": n, "name": n, **r} for n, r in NODESET.items()}, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw, code = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw or b"{}")
    except Exception:
        return code, {"raw": raw[:200]}


try:
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in NODESET}

    def sync(nid, ifs):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t",
                "interfaces": {k: {"down": dn, "peers": [], "meta": {}} for k, dn in ifs.items()}}
        code, r = req("/api/node/sync", {"snapshot": snap}, TOK[nid])
        assert code == 200, (code, r)
        return r

    def starts(r):
        return set(r.get("iface_start") or ((r.get("data") or {}).get("iface_start")) or [])

    print("[1] a mesh link reported down is started")
    ra = sync("a", {"swg_ab": True, "awg0": True})
    check("[1] a's lost link swg_ab is handed back to start", "swg_ab" in starts(ra), sorted(starts(ra)))
    check("[1] …and the peer interface awg0, as before (the control)", "awg0" in starts(ra), sorted(starts(ra)))
    auto = (json.load(open(NODES)).get("a") or {}).get("iface_autostart") or {}
    check("[1] the attempt is counted against the same bound (1 of 3)", (auto.get("swg_ab") or {}).get("n") == 1, auto)

    print("\n[2] and only that")
    rb = sync("b", {"swg_ab": False})
    check("[2] b's end, up, is not started", "swg_ab" not in starts(rb), sorted(starts(rb)))
    rc = sync("c", {"swg_cd": True})
    check("[2] a link the mesh is retiring (a delete staged) is not started", "swg_cd" not in starts(rc), sorted(starts(rc)))
    re_ = sync("e", {"swg_ef": True})
    check("[2] a link the mesh is re-creating (a create staged) is not started", "swg_ef" not in starts(re_), sorted(starts(re_)))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print()
if PLANT:
    print("PLANT %s: %s" % (PLANT, ("caught — %d red" % len(FAILS)) if FAILS else "NOT CAUGHT")); sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS")
