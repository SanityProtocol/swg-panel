#!/usr/bin/env python3
"""Self-test — a removed node's LIVE buffer goes with it (docs/SCALE-PLAN.md K8 D4).

The panel mirrors each node's 5 s LIVE buffer to `<stats_dir>/live-<nid>.json` on every sync and reads it back at start, so
the LIVE chart survives a restart. Removing a node unlinked its `stats-` and `health-` files and never this one: three of
them sat on swgt for nodes deleted long ago (1.8.9 CPU re-qualification). On the real panel, on temp state:

  [1] a start removes `live-<x>.json` for every x not in nodes.json, and keeps a known node's.
  [2] /api/nodes/delete removes the node's `live-<nid>.json`; the other node's stays.
  [3] a start against a store that reads EMPTY removes nothing (an unreadable nodes.json must not take the LIVE charts).

Run: python3 tests/node_live_file_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     keepfile    node_remove leaves the live file again        [2]
     nosweep     the start sweeps nothing                      [1]
     sweepall    the start sweeps against an empty store too   [3]
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {
    "keepfile": ('            os.unlink(os.path.join(sd, f"live-{nid}.json"))\n', '            pass\n'),
    "nosweep": ('    if Handler.deps["nodes"] and Handler.deps.get("stats_dir"):\n', '    if False:\n'),
    "sweepall": ('    if Handler.deps["nodes"] and Handler.deps.get("stats_dir"):\n', '    if Handler.deps.get("stats_dir"):\n'),
}
TMP = tempfile.mkdtemp(prefix="node-live-")
server = SERVER
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    old, new = PLANTS[PLANT]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new, 1))

state = os.path.join(TMP, "state"); os.makedirs(state)
stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
SAMPLE = json.dumps([[int(time.time()), 1, 2, 3, 4, 5]])
PROC = {}


def put_live(nid):
    open(os.path.join(stats, "live-%s.json" % nid), "w").write(SAMPLE)


def live():
    return sorted(f for f in os.listdir(stats) if f.startswith("live-"))


def start():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(os.path.join(TMP, "panel.log"), "a")
    p = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": ""})
    PROC.update(p=p, port=port)
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            return
        except Exception:
            if p.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    sys.exit("panel did not answer")


def stop():
    PROC["p"].terminate()
    PROC["p"].wait(10)


def post(path, data):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PROC["port"], path), data=json.dumps(data).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


try:
    json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in ("n1", "n2")}, open(NODES, "w"))
    for n in ("n1", "n2", "gone1", "gone2"):
        put_live(n)
    print("[1] a start")
    start()
    check("[1] the live files of nodes not in nodes.json are removed, the known nodes' kept",
          live() == ["live-n1.json", "live-n2.json"], live())

    print("\n[2] a node deleted")
    code = post("/api/nodes/delete", {"id": "n1"})
    check("[2] /api/nodes/delete answers 200", code == 200, code)
    check("[2] its live file is gone, the other node's stays", live() == ["live-n2.json"], live())
    stop()

    print("\n[3] a store that reads empty")
    json.dump({}, open(NODES, "w"))
    put_live("x9")
    start()
    check("[3] nothing is swept", live() == ["live-n2.json", "live-x9.json"], live())
    stop()
finally:
    if PROC.get("p") and PROC["p"].poll() is None:
        PROC["p"].kill()
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
