#!/usr/bin/env python3
"""Self-test — the panel side of a turn server's "Listen on" (`bind_ip`), through a REAL panel process.

On a box with several IPv4 addresses a turn server that listens on all of them can reply from an address clients did not
dial, and the VK relay drops it (behind NAT: one the router does not forward). "Listen on" names the one address to bind;
the node honours it (tests/turn_bind_selftest.py [7]). This drives what the panel must do with it — and the lesson behind
[3]: a field the panel stores but one of its record builders does not copy is written once and then lost.

  [1] /api/wdtt/set and /api/csqtt/set take an IPv4 address, refuse anything else, and "" removes it; a save that does
      not carry the key keeps it (the routing / title saves of the same record)
  [2] /api/state hands it to the edit sheets (wdtt_cfg / csqtt_cfg) and to the vk-turn-proxy install/manage requests
  [3] a record the panel MIRRORS from a node's report keeps it — otherwise the next sync reads as a parameter change
      and restarts the server on the wildcard
  [4] the node's `turn_bind_any` capability reaches /api/state (the field is offered only where it is honoured)

Run: python3 tests/turn_listen_on_panel_selftest.py      (0 = pass)
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="listen-on-")
state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({"home": {"id": "home", "name": "home", "links": {}, "ifaces": {}, "endpoint_host": "abcd1234.sn.mynetname.net"}}, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
SHIM = os.path.join(TMP, "shim"); os.makedirs(SHIM)
open(os.path.join(SHIM, "curl"), "w").write("#!/bin/sh\nexit 6\n"); os.chmod(os.path.join(SHIM, "curl"), 0o755)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, SERVER], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "PATH": SHIM + os.pathsep + os.environ.get("PATH", ""), "SWG_PANEL_FLEET": fleet,
                             "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT),
                             "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def store():
    return json.load(open(NODES))["home"]

try:
    for _ in range(200):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            time.sleep(0.1)
    tok = req("/api/nodes/rotate", {"id": "home"})[1]["data"]["token"]
    SNAP = {"hostname": "home", "generated_at": int(time.time()), "noded_version": "t", "turn_manage": True, "turn_capable": True,
            "turn_bind_any": True, "node_ips": ["192.168.88.10", "192.168.88.11"], "interfaces": {},
            "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-57000", "listen": "abcd1234.sn.mynetname.net:57000",
                              "connect": "127.0.0.1:51820", "bind": "0.0.0.0:57000"}]}
    req("/api/node/sync", {"snapshot": SNAP}, tok)

    print("[1] /api/wdtt/set and /api/csqtt/set")
    c, r = req("/api/wdtt/set", {"node": "home", "iface": "wdtt0", "wg_addr": "10.66.66.1/24",
                                 "listen": "abcd1234.sn.mynetname.net:56000", "wg_port": 56001, "bind_ip": "192.168.88.11"})
    check("an address is stored (%d)" % c, c == 200 and (store().get("wdtt") or {}).get("wdtt0", {}).get("bind_ip") == "192.168.88.11", [c, r])
    for bad in ("not-an-ip", "192.168.88.11:56000", "2a02:6b8::10", "192.168.088.11"):
        c, r = req("/api/wdtt/set", {"node": "home", "iface": "wdtt0", "bind_ip": bad})
        check("%r is refused (%d)" % (bad, c), c == 400 and store()["wdtt"]["wdtt0"].get("bind_ip") == "192.168.88.11", [c, r])
    c, r = req("/api/wdtt/set", {"node": "home", "iface": "wdtt0", "title": "home"})
    check("a save without the key keeps it", c == 200 and store()["wdtt"]["wdtt0"].get("bind_ip") == "192.168.88.11", [c, store()["wdtt"]["wdtt0"]])
    c, r = req("/api/wdtt/set", {"node": "home", "iface": "wdtt0", "bind_ip": ""})
    check('"" removes it (Auto)', c == 200 and "bind_ip" not in store()["wdtt"]["wdtt0"], store()["wdtt"]["wdtt0"])
    c, r = req("/api/csqtt/set", {"node": "home", "iface": "csqtt0", "tun_addr": "10.66.67.1/24",
                                  "listen": "abcd1234.sn.mynetname.net:46000", "bind_ip": "192.168.88.10"})
    check("csqtt stores it too (%d)" % c, c == 200 and (store().get("csqtt") or {}).get("csqtt0", {}).get("bind_ip") == "192.168.88.10", [c, r])
    c, r = req("/api/csqtt/set", {"node": "home", "iface": "csqtt0", "bind_ip": "nope"})
    check("csqtt refuses a non-address (%d)" % c, c == 400, [c, r])

    print("\n[2] what the sheets and the node get")
    req("/api/wdtt/set", {"node": "home", "iface": "wdtt0", "bind_ip": "192.168.88.11"})
    st = (req("/api/state")[1].get("data") or {})
    home = next((n for n in st.get("nodes") or [] if n.get("id") == "home"), {})
    check("wdtt_cfg carries it to the WDTT sheet", (home.get("wdtt_cfg") or {}).get("wdtt0", {}).get("bind_ip") == "192.168.88.11", home.get("wdtt_cfg"))
    check("csqtt_cfg carries it to the csqtt sheet", (home.get("csqtt_cfg") or {}).get("csqtt0", {}).get("bind_ip") == "192.168.88.10", home.get("csqtt_cfg"))
    c, r = req("/api/turn/manage", {"node": "home", "service": "vk-turn-proxy-samosvalishe-57000", "bind_ip": "192.168.88.11"})
    check("a vk-turn-proxy edit carries it to the node (%d)" % c, c == 200
          and (store().get("turn") or {}).get("vk-turn-proxy-samosvalishe-57000", {}).get("bind_ip") == "192.168.88.11", [c, store().get("turn")])
    c, r = req("/api/turn/manage", {"node": "home", "service": "vk-turn-proxy-samosvalishe-57000", "bind_ip": ""})
    check('…and "" (back to Auto) too', c == 200 and store()["turn"]["vk-turn-proxy-samosvalishe-57000"].get("bind_ip") == "", store()["turn"])
    c, r = req("/api/turn/manage", {"node": "home", "service": "vk-turn-proxy-samosvalishe-57000", "bind_ip": "x;y"})
    check("a vk-turn-proxy edit refuses a non-address (%d)" % c, c == 400, [c, r])

    print("\n[3] a record mirrored from the node's report keeps it")
    SNAP2 = dict(SNAP, generated_at=int(time.time()),
                 wdtt=[{"iface": "wdtt9", "service": "swg-wdtt-wdtt9", "active": "active", "listen": "abcd1234.sn.mynetname.net:56100",
                        "bind": "192.168.88.11:56100", "bind_ip": "192.168.88.11", "wg_addr": "10.66.70.1/24", "wg_port": 56101,
                        "fork": "amurcanov", "max_passwords": 200, "params": ""}])
    req("/api/node/sync", {"snapshot": SNAP2}, tok)
    w9 = (store().get("wdtt") or {}).get("wdtt9") or {}
    check("the mirrored WDTT record has bind_ip", w9.get("bind_ip") == "192.168.88.11", w9)

    print("\n[4] the capability")
    check("turn_bind_any reaches /api/state", home.get("turn_bind_any") is True, {k: home.get(k) for k in ("turn_manage", "turn_bind_any")})
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("")
if FAILS:
    log.seek(0); print(log.read()[-2000:])
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
