#!/usr/bin/env python3
"""Self-test — the panel's half of "Load now" (docs/AWG31-LOAD-PLAN.md D2, D4, D5). A real panel on a scratch port, no
auth; the nodes are played by POSTing snapshots to /api/node/sync.

  [1] "installed, not loaded" (disk 3.1, module 2.0, tools 3.1) is offered the button and told so; a node with 2.0 on disk,
      a Docker node and an older node (no report) are not
  [2] the press: refused for a node with nothing to load; a counter for one that has
  [3] the sync hands the node {n, age} — the age on the panel's clock
  [4] pending until the node reports THAT press (its id, not only its counter); then its result, worded (done / partial /
      busy)
  [5] a press the node never answers reads as lost once the node would no longer act on it (11 min); the next press is n + 1
  [6] nothing to fall back on (q189 HE-4): a node with no userspace AmneziaWG (`gen.fallback` null) is not offered the button
      and is told why, its press is refused with that reason; the node's own refusal (`no_fallback`) is worded; a load that
      failed names the interfaces that are down instead of promising they run on the fallback

Run: python3 tests/awg_load_panel_selftest.py
     --plant anyload | noage | nodisk | pidmatch | partial | nofb | nofbwhy | nofbcode | downword   (exit 0 when caught)
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"pidmatch": ("[4]", "    if (str(got.get(\"id\")) != pid) if got.get(\"id\") else (_awg_int(got.get(\"n\")) != n):",
                       "    if _awg_int(got.get(\"n\")) != n:"),
          "partial": ("[4]", "(\"partial\" if us or dn else \"done\") if got.get(\"ok\")", "\"done\" if got.get(\"ok\")"),
          "anyload": ("[2]", "        if not awg_loadable(snap):\n            return 409,", "        if False:\n            return 409,"),
          "noage": ("[3]", "\"age\": max(0, int(time.time()) - _awg_int((node.get(\"awg_load\") or {}).get(\"at\")))}}",
                    "\"age\": 0}}"),
          "nodisk": ("[1]", "    return g.get(\"disk\") == \"3.1\" and g.get(\"module\") in (\"2.0\", \"3.0\") and g.get(\"tools\") == \"3.1\"",
                     "    return g.get(\"module\") in (\"2.0\", \"3.0\") and g.get(\"tools\") == \"3.1\""),
          # q189 HE-4: the button offered with nothing to fall back on · the switch's reason says "load it now" anyway ·
          # the node's no_fallback refusal left to the generic sentence · a failed load promising the fallback to every interface
          "nofb": ("[6]", "    return _awg_31_waiting(snap) and isinstance(_awg_datapath(snap)[\"gen\"].get(\"fallback\"), str)",
                   "    return _awg_31_waiting(snap)"),
          "nofbwhy": ("[6]", "        if _awg_31_waiting(snap):", "        if False:"),
          "nofbcode": ("[6]", "    elif code == \"no_fallback\":", "    elif False:"),
          "downword": ("[6]", "    elif code == \"load_failed\" and not dn:", "    elif code == \"load_failed\":")}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="awg-load-panel-")
server = SERVER
if PLANT:
    _s, old, new = PLANTS[PLANT]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new))

GENS = {"ld": {"module": "2.0", "fallback": "3.1", "tools": "3.1", "disk": "3.1"},
        "nd": {"module": "2.0", "fallback": "3.1", "tools": "3.1", "disk": "2.0"},
        "dk": {"module": "2.0", "fallback": "3.1", "tools": "3.1", "disk": "3.1"},
        "nf": {"module": "2.0", "fallback": None, "tools": "3.1", "disk": "3.1"},   # 3.1 waiting, and no amneziawg-go (HE-4)
        "old": None}
state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in GENS}, open(NODES, "w"))
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


for _ in range(150):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
    except Exception:
        if proc.poll() is not None:
            sys.exit("panel exited: " + open(log.name).read()[-2000:])
        time.sleep(0.1)
TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in GENS}


def sync(nid, load=None):
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
            **({"kind": "docker"} if nid == "dk" else {})}
    if GENS[nid] is not None:
        snap["datapath"] = {"awg": {"gen": GENS[nid], **({"load": load} if load else {})}}
    code, r = req("/api/node/sync", {"snapshot": snap}, TOK[nid])
    assert code == 200, (code, r)
    return r


def rec(nid):
    """The node's record in /api/state — wherever the state nests it: the dict carrying `awg31_no` for this node."""
    def walk(v):
        if isinstance(v, dict):
            if "awg31_no" in v and (v.get("id") == nid or v.get("name") == nid or v.get("node") == nid):
                return v
            for k, x in v.items():
                if k == nid and isinstance(x, dict) and "awg31_no" in x:
                    return x
                r = walk(x)
                if r is not None:
                    return r
        elif isinstance(v, list):
            for x in v:
                r = walk(x)
                if r is not None:
                    return r
        return None
    return walk(req("/api/state")[1]) or {}


def key(m):
    return (m or {}).get("error_key") or (m or {}).get("error") or ""


try:
    for n in GENS:
        sync(n)
    SECTION[0] = "[1]"
    print("[1] who is offered the button")
    check("disk 3.1, module 2.0, tools 3.1 → offered", rec("ld").get("awg31_loadable") is True, rec("ld"))
    check("…and told it is installed, not loaded", "is installed, but the kernel module in use" in key(rec("ld").get("awg31_no")),
          rec("ld").get("awg31_no"))
    check("2.0 on disk → not offered, told the module is 2.0", rec("nd").get("awg31_loadable") is False
          and "its AmneziaWG kernel module is" in key(rec("nd").get("awg31_no")), rec("nd"))
    check("a Docker node → not offered (its module is the host's)", rec("dk").get("awg31_loadable") is False, rec("dk"))
    check("an older node → not offered", rec("old").get("awg31_loadable") is False, rec("old"))

    SECTION[0] = "[2]"
    print("\n[2] the press")
    c, r = req("/api/node/awg-load", {"id": "nd"})
    check("nothing to load → 409, nothing stored", c == 409 and "awg_load" not in json.load(open(NODES))["nd"], (c, r))
    c, r = req("/api/node/awg-load", {"id": "ld"})
    check("a node that has one → 200, n = 1", c == 200 and (r.get("data") or {}).get("n") == 1, (c, r))

    SECTION[0] = "[3]"
    print("\n[3] the sync")
    time.sleep(2)
    d = sync("ld").get("awg_load") or {}
    check("the node is handed {n, id, age}", d.get("n") == 1 and isinstance(d.get("age"), int) and str(d.get("id", "")).startswith("1:"), d)
    PID1 = d.get("id")
    check("…the age on the panel's clock (seconds since the press)", 1 <= (d.get("age") or 0) <= 30, d)

    SECTION[0] = "[4]"
    print("\n[4] pending, then the result")
    check("pending until the node reports this press", (rec("ld").get("awg_load") or {}).get("state") == "pending", rec("ld").get("awg_load"))
    sync("ld", {"n": 1, "id": "1:1600000000", "ok": True, "code": "done", "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel"}})
    check("a result for the same n but an OLD press (a re-created record) is not taken as this press's answer",
          (rec("ld").get("awg_load") or {}).get("state") == "pending", rec("ld").get("awg_load"))
    sync("ld", {"n": 1, "id": PID1, "ok": True, "code": "done", "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel", "swg_ab": "kernel"}})
    a = rec("ld").get("awg_load") or {}
    check("done, worded", a.get("state") == "done" and "every AmneziaWG interface is back on the kernel module" in key(a.get("msg")), a)
    sync("ld", {"n": 1, "ok": True, "code": "done", "loaded": "3.1.20260812", "ifaces": {"awg0": "kernel", "awg1": "userspace"}})
    a = rec("ld").get("awg_load") or {}
    check("not every interface back → named, and the state says so (partial, shown as a problem)", "not every interface came back" in key(a.get("msg"))
          and "awg1" in json.dumps(a.get("msg")) and a.get("state") == "partial", a)
    sync("ld", {"n": 1, "ok": False, "code": "busy", "ifaces": {}})
    a = rec("ld").get("awg_load") or {}
    check("busy → failed, worded", a.get("state") == "failed" and "could not be unloaded" in key(a.get("msg")), a)

    SECTION[0] = "[5]"
    print("\n[5] lost, and the next press")
    c, r = req("/api/node/awg-load", {"id": "ld"})
    check("the next press is n = 2", c == 200 and (r.get("data") or {}).get("n") == 2, (c, r))
    n = json.load(open(NODES)); n["ld"]["awg_load"]["at"] = int(time.time()) - 3600
    json.dump(n, open(NODES + ".tmp", "w")); os.replace(NODES + ".tmp", NODES)
    a = rec("ld").get("awg_load") or {}
    check("unanswered for an hour → lost, worded", a.get("state") == "lost" and "has not answered" in key(a.get("msg")), a)

    SECTION[0] = "[6]"
    print("\n[6] nothing to fall back on (q189 HE-4)")
    check("3.1 waiting but no userspace AmneziaWG (gen.fallback null) → not offered", rec("nf").get("awg31_loadable") is False, rec("nf"))
    w = key(rec("nf").get("awg31_no"))
    check("…and told why: 3.1 is installed, loads at the next reboot, cannot be loaded now — no amneziawg-go to fall back on",
          "is installed, but the kernel module in use" in w and "cannot be loaded now" in w and "amneziawg-go" in w
          and "load it now" not in w, rec("nf").get("awg31_no"))
    c, r = req("/api/node/awg-load", {"id": "nf"})
    check("…its press → 409 with that reason, nothing stored", c == 409 and "cannot be loaded now" in key(r)
          and "awg_load" not in json.load(open(NODES))["nf"], (c, r))
    check("a node WITH one is still offered (the control)", rec("ld").get("awg31_loadable") is True, rec("ld"))
    c, r = req("/api/node/awg-load", {"id": "ld"})
    check("the next press is n = 3", c == 200 and (r.get("data") or {}).get("n") == 3, (c, r))
    PID3 = (sync("ld").get("awg_load") or {}).get("id")
    sync("ld", {"n": 3, "id": PID3, "ok": False, "code": "no_fallback", "error": "no amneziawg-go to fall back on if the new module would not load", "ifaces": {}})
    a = rec("ld").get("awg_load") or {}
    check("the node's own refusal (no_fallback) → failed, worded: nothing was changed, no userspace AmneziaWG",
          a.get("state") == "failed" and key(a.get("msg")) == "{v1}: nothing was changed — this node has no userspace AmneziaWG "
          "(amneziawg-go) to fall back on if the new module did not load", a)
    sync("ld", {"n": 3, "id": PID3, "ok": False, "code": "load_failed", "loaded": "", "ifaces": {"awg0": "down", "swg_ab": "userspace", "swg_cd": "down"}})
    a = rec("ld").get("awg_load") or {}
    m = json.dumps(a.get("msg"))
    check("a failed load with interfaces down names them, and which run on the fallback — no promise for the ones that do not",
          a.get("state") == "failed" and "run on the userspace fallback until" not in m and "awg0, swg_cd" in m and "swg_ab" in m
          and "down" in key(a.get("msg")), a)
    sync("ld", {"n": 3, "id": PID3, "ok": False, "code": "load_failed", "loaded": "", "ifaces": {"awg0": "down"}})
    a = rec("ld").get("awg_load") or {}
    check("…every one down: none is said to run on the fallback", "run on the userspace fallback until" not in json.dumps(a.get("msg"))
          and "awg0" in json.dumps(a.get("msg")), a)
    sync("ld", {"n": 3, "id": PID3, "ok": False, "code": "load_failed", "loaded": "", "ifaces": {"awg0": "userspace", "swg_ab": "userspace"}})
    a = rec("ld").get("awg_load") or {}
    check("…every one on the fallback: the sentence that says so (unchanged)", "its interfaces run on the userspace fallback until the "
          "next reboot" in key(a.get("msg")), a)
finally:
    proc.terminate()
    with __import__("contextlib").suppress(Exception):
        proc.wait(5)

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
