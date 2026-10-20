#!/usr/bin/env python3
"""Self-test: an edit of a blocked user keeps the block — and keeps the user's devices off the nodes.

`user_set` rebuilds the user record from a whitelist. `disabled` / `disabled_at` / `unblock_at` were not on it, so
every rename, note, expiry or VK-link edit of a blocked user dropped the block: access_cut turned False and the
user's devices went back onto every node at the next sync, while the subscription page still said "disabled".
Drives the REAL panel over HTTP, then asks the real desired_for_node about the saved roster:

  [1] block a user, then each edit the SPA sends (note; name + tag; expiry; VK links) → still disabled, disabled_at
      unchanged
  [2] the consequence: the blocked user's device is in no node's desired set after the edits
  [3] CONTROL: unblock, then edit → stays unblocked, unblock_at kept, the device is back in desired
  [4] CONTROL: a user never blocked, edited → no block field appears

Run: python3 tests/user_block_kept_selftest.py
     --perturb   drops the carry (the old behaviour) — expects RED in [1] [2].
"""
import http.client, importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
FAILS = []

def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

D = tempfile.mkdtemp(prefix="userblock-")
if PERTURB:
    src = open(SERVER).read()
    old = 'for k in ("disabled", "disabled_at", "unblock_at"):'
    if src.count(old) != 1:
        print("ANCHOR MISSING OR NOT UNIQUE — this run would FALSE-PASS"); sys.exit(1)
    SERVER = os.path.join(D, "swg-panel-server")
    open(SERVER, "w").write(src.replace(old, "for k in ():"))

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m

for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
NID = "n1"
now = int(time.time())
json.dump({NID: {"id": NID, "name": "rig", "stats_file": "stats-n1.json", "created": now}},
          open(D + "/state/nodes.json", "w"))
def peer(pid, uid, ip):
    return {"id": pid, "user_id": uid, "title": "phone", "pubkey": (pid * 43)[:43] + "=", "psk": "",
            "targets": [{"node": NID, "iface": "wg1", "ip": ip, "type": "wg"}], "created_at": now, "modified_at": now}
def user(uid, name):
    return {"id": uid, "name": name, "tag": "", "note": "", "vk_link": "", "vk_links": [], "expiry": 0,
            "created_at": now, "modified_at": now}
json.dump({"version": 1, "users": {"ub": user("ub", "Blocked"), "uc": user("uc", "Control")},
           "peers": {"pb": peer("b", "ub", "10.8.0.16"), "pc": peer("c", "uc", "10.8.0.17")}},
          open(D + "/state/users.json", "w"))
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

def users():
    return json.load(open(D + "/state/users.json"))["users"]

try:
    for _ in range(150):
        try:
            if call("GET", "/api/state")[0] == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        print("the panel never came up"); sys.exit(1)
    P = load("swgpanel", SERVER)
    def in_desired(ip):
        r = json.load(open(D + "/state/users.json"))
        return any(ip + "/32" == (q.get("allowed_ips") or "").split(",")[0]
                   for lst in P.desired_for_node(r, NID).values() for q in lst)

    print("[1] a blocked user stays blocked through every edit")
    code, r = call("POST", "/api/user/block", {"user_id": "ub"})
    check("block accepted", code == 200, r)
    at = users()["ub"].get("disabled_at")
    check("blocked: disabled + disabled_at written", users()["ub"].get("disabled") is True and bool(at), users()["ub"])
    check("blocked: the device left desired", not in_desired("10.8.0.16"))
    VK = "https://vk.ru/call/join/" + "A" * 24
    edits = [("note", {"note": "moved to a new phone"}), ("name + tag", {"name": "Blocked2", "tag": "t"}),
             ("expiry", {"expiry": now + 30 * 86400}), ("VK links", {"vk_links": [VK], "vk_link": VK})]
    for label, body in edits:
        code, r = call("POST", "/api/users/update", dict(body, id="ub"))
        u = users()["ub"]
        check("edit %s: accepted" % label, code == 200, r)
        check("edit %s: still disabled, disabled_at unchanged" % label,
              u.get("disabled") is True and u.get("disabled_at") == at, {k: u.get(k) for k in ("disabled", "disabled_at")})

    print("[2] the device stays off the node")
    check("after the edits: the blocked user's device is not in desired", not in_desired("10.8.0.16"))
    check("the control user's device is in desired", in_desired("10.8.0.17"))

    print("[3] CONTROL: unblock, then edit")
    code, r = call("POST", "/api/user/unblock", {"user_id": "ub"})
    ua = users()["ub"].get("unblock_at")
    check("unblock accepted, unblock_at written", code == 200 and bool(ua), r)
    code, r = call("POST", "/api/users/update", {"id": "ub", "note": "back"})
    u = users()["ub"]
    check("edit after unblock: not disabled, unblock_at kept",
          code == 200 and not u.get("disabled") and "disabled_at" not in u and u.get("unblock_at") == ua, u)
    check("after unblock: the device is back in desired", in_desired("10.8.0.16"))

    print("[4] CONTROL: a user never blocked")
    code, r = call("POST", "/api/users/update", {"id": "uc", "note": "n"})
    u = users()["uc"]
    check("edit: no block field appears", code == 200 and not any(k in u for k in ("disabled", "disabled_at", "unblock_at")), u)
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    shutil.rmtree(D, ignore_errors=True)

print()
print(("RED — %d failed: %s" % (len(FAILS), ", ".join(FAILS))) if FAILS else "GREEN — all checks passed")
sys.exit(1 if FAILS else 0)
