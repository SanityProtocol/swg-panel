#!/usr/bin/env python3
"""Self-test: a new user is handed `vk_pool_per_user` links from the shared VK pool (default 3), not one.

Each VK call link is its own pool of TURN streams in every client that takes a list, so a user created with one
link got a fraction of the throughput. Drives the REAL panel over HTTP:

  [1] default: a new user gets 3 DISTINCT live links, primary = vk_links[0] = vk_link, provenance recorded
  [2] spread: with 7 live links, users 1-2 hold six different links between them; after 7 users of 3 each (21
      assignments) every link is held by exactly 3 — least-loaded, not stacked
  [3] dead links are never handed out; a pool with fewer live links than N gives what it has
  [4] the setting: /api/vk-pool/per-user saves, 0 hands out none, out-of-range and junk are refused; it
      changes nobody who already exists
  [5] CONTROL: "Add from pool" still adds exactly one

Run: python3 tests/vk_pool_per_user_selftest.py
     --perturb   hands out one link again (the old behaviour) — expects RED in [1] [2].
"""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
FAILS = []

def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

D = tempfile.mkdtemp(prefix="vkpool-")
if PERTURB:
    src = open(SERVER).read()
    old = "picks = _vk_pool_pick_many(ps, _vk_pool_per_user(ps), _vk_pool_counts(roster))"
    if src.count(old) != 1:
        print("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS"); sys.exit(1)
    SERVER = os.path.join(D, "swg-panel-server")
    open(SERVER, "w").write(src.replace(old, "picks = _vk_pool_pick_many(ps, 1, _vk_pool_counts(roster))"))
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
json.dump({"nodes_path": D + "/state/nodes.json", "roster_path": D + "/state/users.json",
           "panel_settings_path": D + "/state/panel-settings.json", "config_dir": D + "/conf", "stats_dir": D + "/stats",
           "store_configs": False}, open(os.path.join(D, "fleet.json"), "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=ROOT, SWG_PANEL_HOST="127.0.0.1", SWG_PANEL_PORT=str(PORT),
           SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="")
srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); c.close()
    return r.status, json.loads(raw or b"{}")

J = "https://vk.ru/call/join/"
URLS = [J + (ch * 24) for ch in "ABCDEFG"]

try:
    for _ in range(150):
        try:
            if call("GET", "/api/state")[0] == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        print("the panel never came up"); sys.exit(1)
    rev = [0]
    def save_pool(pool):
        code, r = call("POST", "/api/vk-pool", {"pool": pool, "rev": rev[0]})
        assert code == 200, r
        rev[0] = r["data"]["rev"]
        return r["data"]["pool"]
    def mk(name):
        code, r = call("POST", "/api/users/create", {"name": name})
        assert code == 200, r
        return r["data"]
    def roster_users():
        return json.load(open(D + "/state/users.json"))["users"]

    pool = save_pool([{"url": u} for u in URLS])
    live = set(URLS)
    check("a fresh panel reports the default 3 in /api/state",
          call("GET", "/api/state")[1].get("data", {}).get("panel_settings", {}).get("vk_pool_per_user") == 3)

    print("[1] default: a new user gets three distinct live links")
    u1 = mk("u1")
    L = u1.get("vk_links") or []
    check("three links", len(L) == 3, L)
    check("all distinct, all from the pool", len(set(L)) == 3 and set(L) <= live, L)
    check("primary is vk_links[0]", u1.get("vk_link") == (L[0] if L else None), u1.get("vk_link"))
    check("provenance recorded for each", sorted((u1.get("vk_pool") or {}).values()) == sorted(L), u1.get("vk_pool"))

    print("[2] least-loaded spread")
    u2 = mk("u2")
    check("u1 and u2 hold six different links", len(set(L) | set(u2.get("vk_links") or [])) == 6, (L, u2.get("vk_links")))
    for i in range(3, 8):
        mk("u%d" % i)
    counts = {}
    for u in roster_users().values():
        for x in u.get("vk_links") or []:
            counts[x] = counts.get(x, 0) + 1
    check("21 assignments over 7 links = 3 each", sorted(counts.values()) == [3] * 7, counts)

    print("[3] dead links are skipped; a short pool gives what it has")
    pool = save_pool([{**e, "dead": e["url"] != URLS[0]} for e in pool])
    u8 = mk("u8")
    check("only one live link → the user gets exactly that one", (u8.get("vk_links") or []) == [URLS[0]], u8.get("vk_links"))

    print("[4] the setting")
    pool = save_pool([{**e, "dead": False} for e in pool])
    code, r = call("POST", "/api/vk-pool/per-user", {"n": 5})
    check("n=5 saves", code == 200 and r["data"]["vk_pool_per_user"] == 5, (code, r))
    check("…and is in panel_settings", call("GET", "/api/state")[1].get("data", {}).get("panel_settings", {}).get("vk_pool_per_user") == 5)
    before = {k: v.get("vk_links") for k, v in roster_users().items()}
    u9 = mk("u9")
    check("a new user now gets five", len(set(u9.get("vk_links") or [])) == 5, u9.get("vk_links"))
    after = {k: v.get("vk_links") for k, v in roster_users().items() if k in before}
    check("existing users unchanged", before == after)
    evs = open(D + "/state/events.jsonl").read() if os.path.exists(D + "/state/events.jsonl") else ""
    verbs = [json.loads(l).get("verb") for l in evs.splitlines() if l.strip()]
    check("the change is in the activity log", "VK links per new user: 3 → 5" in verbs, verbs[-3:])
    code, r = call("POST", "/api/vk-pool/per-user", {"n": 0})
    u10 = mk("u10")
    check("n=0 → no links", code == 200 and not u10.get("vk_links"), u10)
    for bad in (-1, 17, "x", None, True, 2.9, "3"):
        code, _ = call("POST", "/api/vk-pool/per-user", {"n": bad})
        check("n=%r refused" % (bad,), code == 400, code)
    check("a refused value leaves the saved one", call("GET", "/api/state")[1].get("data", {}).get("panel_settings", {}).get("vk_pool_per_user") == 0)

    print("[5] CONTROL: Add from pool adds one")
    code, r = call("POST", "/api/user/vk-pool-add", {"id": u10["id"]})
    check("one link added", code == 200 and len(r["data"]["vk_links"]) == 1, (code, r))
finally:
    srv.terminate()
    try:
        err = srv.communicate(timeout=10)[1].decode("utf-8", "replace")
    except Exception:
        err = ""
    check("no Traceback in the panel log", "Traceback" not in err, err[-1500:])
    shutil.rmtree(D, ignore_errors=True)

print("")
if PERTURB:
    print(("PERTURB OK — %d checks went red" % len(FAILS)) if FAILS else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if FAILS else 1)
print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
