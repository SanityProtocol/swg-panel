#!/usr/bin/env python3
"""Self-test: every read-modify-write of nodes.json runs on the store as it is NOW — a node sync included — and the lock
that makes it so never costs a node its liveness, its signature check or its answer.

THE BUG (seen on swgt 2026-09-18, proven from its own nodes.json.bak files): `_node_sync` loaded the whole store before
it even read the snapshot body, processed it, and saved that copy without _api_lock — so an operator edit landing in
between was written away (an interface's S4 set 22 s after its create came back as the old value in the same second).
Steady state a sync writes nothing, so this only bites in the seconds after something new appears — which is exactly
"create, then adjust". The live end-to-end proof is .campaign/rigs/nodes-lost-update.py; this pins the parts in-process:

  • a sync waits for _api_lock and RE-READS under it: an edit made while it waited survives (the bug itself);
  • it is stamped live BEFORE the lock, bounded (10 s → 503 busy), and a node removed / a token rotated while it waited
    gets 401 and leaves no stale stamp — while a 503 for a node that still exists keeps it live;
  • a legacy node (no token_sha — the installers strip it on a re-install) is never refused its signature because the
    one-time index upgrade could not take the lock;
  • the GET that closes a transfer, and the turn auto-update, write onto a fresh read — never over a Cancel, a pending
    delete/stop, a rollback hold, or a proxy that updated meanwhile;
  • the read-only POSTs that run WITHOUT the lock (_LOCKLESS_POST) really write neither store.

Hermetic: no network, no panel process. Run: python3 tests/rmw_lock_selftest.py            (0 = pass)
                                           python3 tests/rmw_lock_selftest.py --perturb  (each guard planted out, one per run:
                                                                                          every run must go red; 0 = all caught)
"""
import hashlib, hmac, importlib.machinery, importlib.util, io, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

PERTURB = [   # the tree before each guard, one at a time — each must turn its checks red
    ("the sync keeps _node_token's stale copy (the bug)",
     "            if _mk is None or nodes_mark(Handler.deps[\"nodes_path\"]) != _mk:",
     "            if False:"),
    ("the re-read is never skipped (the second parse is back)",
     "            if _mk is None or nodes_mark(Handler.deps[\"nodes_path\"]) != _mk:",
     "            if True:"),
    ("reuse trusts the file alone — no save counter",
     "    return (_NODES_SAVES[0], st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)",
     "    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)"),
    ("reuse trusts the save counter alone — a write from outside the panel is missed",
     "    return (_NODES_SAVES[0], st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)",
     "    return (_NODES_SAVES[0],)"),
    ("reuse trusts the inode alone — an in-place rewrite is missed",
     "    return (_NODES_SAVES[0], st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)",
     "    return (_NODES_SAVES[0], st.st_dev, st.st_ino)"),
    ("the mark is taken AFTER the auth read",
     "        self._nodes_mark = nodes_mark(Handler.deps[\"nodes_path\"])   # before the read — see nodes_mark\n        nodes = nodes_load(Handler.deps[\"nodes_path\"])\n",
     "        nodes = nodes_load(Handler.deps[\"nodes_path\"])\n        self._nodes_mark = nodes_mark(Handler.deps[\"nodes_path\"])\n"),
    ("a waiting sync no longer re-checks the credential",
     "            elif not _node_cred_same(tnode, node):", "            elif False:"),
    ("a timed-out sync keeps a removed node's stamps",
     "            if not _serr and nid not in nodes_load(Handler.deps[\"nodes_path\"]):", "            if False:"),
    ("the legacy token index is set only if it could be saved",
     "            node[\"token_sha\"] = hashlib.sha256(token.encode()).hexdigest()\n            if _api_lock.acquire(timeout=2):",
     "            if _api_lock.acquire(timeout=2):"),
    ("a transfer poll writes back its pre-call copy",
     "                _mine = (_cur.get(\"state\") != \"done\" and _cur.get(\"at\") == x.get(\"at\")\n",
     "                _mine = nid in _nn or (_cur.get(\"state\") != \"done\" and _cur.get(\"at\") == x.get(\"at\")\n"),
    ("the turn auto-update overrides a pending action again",
     "                if (nodes[nid].get(\"turn\") or {}).get(svc):\n                    continue\n                if _turn_hold_get",
     "                if ((nodes[nid].get(\"turn\") or {}).get(svc) or {}).get(\"action\") == \"reinstall\":\n                    continue\n                if _turn_hold_get"),
    ("the turn auto-update reinstalls a proxy already on the tag",
     "                if svc not in _now_v or _now_v[svc] == tag:", "                if svc not in _now_v:"),
]
if "--perturb" in sys.argv:        # ONE plant per run — together they can mask each other
    import subprocess
    src = open(SERVER, encoding="utf-8").read()
    tmp, caught = tempfile.mkdtemp(prefix="rmw-pert."), 0
    for name, old, new in PERTURB:
        if src.count(old) != 1:
            print("  ??   %-52s ANCHOR MISSING — the guard moved or went" % name); continue
        alt = os.path.join(tmp, "swg-panel-server")
        open(alt, "w", encoding="utf-8").write(src.replace(old, new, 1))
        r = subprocess.run([sys.executable, os.path.abspath(__file__)], env={**os.environ, "SWG_PANEL_SERVER": alt},
                           capture_output=True, text=True, timeout=300)
        red = [l.strip()[5:] for l in r.stdout.splitlines() if l.startswith("  FAIL ")]
        print("  %-4s %-52s %s" % ("RED" if red else "GREEN", name, (red[0][:70] if red else "")))
        caught += bool(red)
    print("\n%d of %d planted regressions caught" % (caught, len(PERTURB)))
    sys.exit(0 if caught == len(PERTURB) else 1)

loader = importlib.machinery.SourceFileLoader("swgpanel", SERVER)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="rmw.")
NP, RP = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
with P._api_lock:
    P.nodes_save(NP, {}); P.roster_save(RP, {"peers": {}, "users": {}})


print("[rmw] a sync that waited for the lock")
TOK = "tok-" + "x" * 40
def sha(t): return hashlib.sha256(t.encode()).hexdigest()
def signed(raw, tok):                                    # exactly what swg-noded's _sig_headers sends
    ts = str(int(time.time())); key = sha(tok)
    mac = hmac.new(key.encode(), (ts + "." + hashlib.sha256(raw).hexdigest()).encode(), hashlib.sha256).hexdigest()
    return {"X-SWG-TS": ts, "X-SWG-MAC": mac}
class Req:                                               # just enough of a request for Handler._node_sync
    def __init__(self, tok, sign):
        raw = json.dumps({"snapshot": {"kind": "baremetal", "interfaces": {}}}).encode()
        self.headers = {"Authorization": "Bearer " + tok, "Content-Length": str(len(raw)), **(signed(raw, tok) if sign else {})}
        self.rfile = io.BytesIO(raw); self.out = []
def run_sync(tok, sign=False):
    h = P.Handler.__new__(P.Handler); r = Req(tok, sign)
    h.headers, h.rfile = r.headers, r.rfile
    h._send = lambda code, obj: r.out.append((code, obj))
    try:
        h._node_sync()
    except Exception as e:
        r.out.append((500, {"error": "%s: %s" % (type(e).__name__, e)}))
    return r.out[-1] if r.out else None
def sync_while(held_do, wait=None, record=None, sign=False):
    """Hold the lock, start a sync, do `held_do` while it waits, then let go (or let it time out)."""
    SDEPS = {"fleet": {}, "nodes_path": NP, "roster_path": RP, "node_snaps": {}, "node_seen": {}, "panel_settings": {}}
    P.Handler.deps = SDEPS
    with P._api_lock:
        P.nodes_save(NP, {"n1": record or {"name": "edge", "token_sha": sha(TOK)}})
    res, old_wait = [], P.SYNC_LOCK_WAIT
    if wait is not None:
        P.SYNC_LOCK_WAIT = wait
    P._api_lock.acquire()
    try:
        th = threading.Thread(target=lambda: res.append(run_sync(TOK, sign))); th.start()
        time.sleep(0.3 if record is None else 2.6)       # stamped and queued on the lock (a legacy one waits out its 2 s upgrade)
        stamped = "n1" in SDEPS["node_seen"]
        with P._api_lock:                                # re-entrant: what another request does while the sync waits
            held_do()
        if wait is not None:
            th.join(wait + 3)
    finally:
        P._api_lock.release()
    th.join(15); P.SYNC_LOCK_WAIT = old_wait
    return (res[0] if res else None), stamped, "n1" in SDEPS["node_snaps"], "n1" in SDEPS["node_seen"]

def edit():                                              # an operator edit, made while the sync waits
    n = P.nodes_load(NP); n["n1"]["name"] = "edited-while-waiting"; P.nodes_save(NP, n)
got, stamped, has_snap, _ = sync_while(edit)
check("control: the sync is stamped live BEFORE the lock", stamped)
check("THE BUG: an edit made while a sync waited survives that sync (it re-reads under the lock)",
      (got or (0,))[0] == 200 and P.nodes_load(NP)["n1"].get("name") == "edited-while-waiting",
      (got and got[0], P.nodes_load(NP)["n1"].get("name")))
check("…and the sync really wrote (its own bookkeeping landed on the same record)",
      P.nodes_load(NP)["n1"].get("kind") == "baremetal", P.nodes_load(NP)["n1"])
def rotate():
    n = P.nodes_load(NP); n["n1"]["token_sha"] = sha("tok-new"); P.nodes_save(NP, n)
def remove():
    P.nodes_save(NP, {})
got, _s, has_snap, _ = sync_while(rotate)
check("a token ROTATED while the sync waited gets 401 — nothing for the old token", (got or (0,))[0] == 401, got)
check("…and its snapshot is not left standing as the node's state", not has_snap, has_snap)
got, _s, has_snap, has_seen = sync_while(remove)
check("a node REMOVED while the sync waited gets 401 and leaves no stale stamp",
      (got or (0,))[0] == 401 and not has_snap and not has_seen, (got, has_snap, has_seen))
got, _s, has_snap, has_seen = sync_while(remove, wait=0.5)
check("…and when the wait TIMES OUT (503), still no stale stamp (no false node.offline later)",
      (got or (0,))[0] == 503 and not has_snap and not has_seen, (got, has_snap, has_seen))
got, _s, has_snap, has_seen = sync_while(lambda: None, wait=0.5)
check("control: a 503 for a node that still exists keeps it live (liveness is the point)",
      (got or (0,))[0] == 503 and has_snap and has_seen, (got, has_snap, has_seen))
LEGACY = {"name": "edge", "token_hash": P.make_token_hash(TOK)}   # a re-installed local node: token_sha stripped
got, _s, _hs, _ = sync_while(lambda: None, wait=0.5, record=LEGACY, sign=True)
check("a SIGNED sync from a legacy node while the panel is busy gets 503 busy — never 401 bad_signature",
      (got or (0,))[0] == 503, got)


print("[rmw] the re-read is skipped only when nothing has written nodes.json since the auth read")
# A sync parses the store to authenticate and must see it as it is NOW under the lock (the bug above). Parsing is most of
# a sync's cost at scale (85 % at 200 nodes), so when nothing has written the store since, the auth parse is reused —
# judged by nodes_mark: this process's save counter AND the file's identity, taken before the read.
_real_load, _real_stat = P.nodes_load, os.stat
def loads_during(fn):
    n = [0]
    def counting(path):
        if path == NP:
            n[0] += 1
        return _real_load(path)
    P.nodes_load = counting
    try:
        out = fn()
    finally:
        P.nodes_load = _real_load
    return out, n[0]
def fresh(record=None):
    P.Handler.deps = {"fleet": {}, "nodes_path": NP, "roster_path": RP, "node_snaps": {}, "node_seen": {}, "panel_settings": {}}
    with P._api_lock:
        P.nodes_save(NP, {"n1": record or {"name": "edge", "token_sha": sha(TOK), "kind": "baremetal"}})
fresh(); run_sync(TOK)                                   # settle: the first sync writes its bookkeeping
got, n = loads_during(lambda: run_sync(TOK))
check("steady state: a sync with nothing written since its auth read parses nodes.json ONCE", (got or (0,))[0] == 200 and n == 1, (got and got[0], n))
def external(name):                                      # a writer outside the panel: its own rename, no nodes_save
    cur = _real_load(NP); cur["n1"]["name"] = name
    tmp = NP + ".ext"; open(tmp, "w").write(json.dumps(cur)); os.replace(tmp, NP)
got, *_ = sync_while(lambda: external("written-outside-the-panel"))
check("a write from OUTSIDE the panel while the sync waited is re-read, not saved over",
      (got or (0,))[0] == 200 and P.nodes_load(NP)["n1"].get("name") == "written-outside-the-panel", (got and got[0], P.nodes_load(NP)["n1"].get("name")))
def in_place(name):                                      # an outside writer that rewrites the SAME inode (install-host.sh writef)
    cur = _real_load(NP); cur["n1"]["name"] = name
    with open(NP, "r+") as f:
        f.seek(0); f.write(json.dumps(cur, indent=4)); f.truncate()
got, *_ = sync_while(lambda: in_place("rewritten-in-place"))
check("a write IN PLACE from outside the panel (same inode) while the sync waited is re-read, not saved over",
      (got or (0,))[0] == 200 and P.nodes_load(NP)["n1"].get("name") == "rewritten-in-place", (got and got[0], P.nodes_load(NP)["n1"].get("name")))
frozen = [None]
def frozen_stat(path, *a, **k):                          # the file LOOKS unchanged (same inode, size and time)
    if path == NP and frozen[0] is not None:
        return frozen[0]
    return _real_stat(path, *a, **k)
fresh(); frozen[0] = _real_stat(NP); os.stat = frozen_stat
try:
    got, *_ = sync_while(edit)
finally:
    os.stat = _real_stat; frozen[0] = None
check("a save by the panel while the sync waited is re-read even when the file looks unchanged (the save counter)",
      (got or (0,))[0] == 200 and P.nodes_load(NP)["n1"].get("name") == "edited-while-waiting", (got and got[0], P.nodes_load(NP)["n1"].get("name")))
fresh({"name": "edge", "token_sha": sha(TOK)})          # no `kind` yet: this sync WRITES — a stale copy would be saved over the edit
def racing(path):                                        # the auth read parses the old store, and a write lands right after it
    out = _real_load(path)
    if path == NP and not racing.done:
        racing.done = True; external("written-during-the-auth-read")
    return out
racing.done = False; P.nodes_load = racing
try:
    got = run_sync(TOK)
finally:
    P.nodes_load = _real_load
check("a write landing during the auth read is re-read (the mark is taken BEFORE that read)",
      (got or (0,))[0] == 200 and P.nodes_load(NP)["n1"].get("name") == "written-during-the-auth-read"
      and P.nodes_load(NP)["n1"].get("kind") == "baremetal", (got and got[0], P.nodes_load(NP)["n1"]))


print("[rmw] a transfer poll marks done only the transfer it asked about")
# GET /api/nodes/transfer/status runs OUTSIDE _api_lock and asks the far panel (seconds) between its read and its write.
DEPS = {"fleet": {}, "nodes_path": NP, "roster_path": RP, "panel_settings": {}}
def events_named(what):
    p = os.path.join(TMP, "events.jsonl")
    return sum(1 for l in open(p) if l.strip() and what in l) if os.path.exists(p) else 0
PENDING = {"state": "pending", "at": 100, "url": "https://far.example", "token": "far-token"}
def poll(during=None):
    with P._api_lock:
        P.nodes_save(NP, {"n1": {"name": "edge", "transfer": dict(PENDING)}})
    def far(url, token, path, obj=None, timeout=25, pin=""):
        if during:
            during()                                     # what another request does while the far panel answers
        return 200, {"data": {"last_seen": 200}}, {}
    P.transfer_call = far
    before = events_named("Transferred")
    code, obj = P.api("GET", "/api/nodes/transfer/status", {"node": ["n1"]}, {}, DEPS)
    return code, obj, P.nodes_load(NP)["n1"].get("transfer"), events_named("Transferred") - before
code, obj, rec, ev = poll()
check("control: a transfer the far panel confirms is marked done, token dropped, logged once",
      (rec or {}).get("state") == "done" and "token" not in (rec or {}) and ev == 1, (rec, ev))
def cancel():
    with P._api_lock:
        n = P.nodes_load(NP); n["n1"].pop("transfer", None); P.nodes_save(NP, n)
code, obj, rec, ev = poll(cancel)
check("a transfer CANCELLED while the far panel answered is not brought back as done", rec is None and ev == 0, (rec, ev))
check("…and the poll answers 'no transfer' rather than a stale 'done'", code == 404, (code, obj))
def restart():
    with P._api_lock:
        n = P.nodes_load(NP); n["n1"]["transfer"] = dict(PENDING, at=150, token="new-token"); P.nodes_save(NP, n)
code, obj, rec, ev = poll(restart)
check("a NEW transfer started meanwhile is left as it is, and reported as pending",
      (rec or {}).get("at") == 150 and (rec or {}).get("state") == "pending" and ev == 0
      and code == 200 and obj["data"].get("at") == 150, (rec, ev, obj))


print("[rmw] the turn auto-update never overrides the operator")
# Pass 1 asks GitHub and fetches pins OUTSIDE the lock; pass 2 re-reads and stages. What the operator did in between wins.
SVC = "vk-turn-proxy-anton48-56000"
PSP = os.path.join(TMP, "panel-settings.json")
open(PSP, "w").write('{"turn_update": {"every_days": 1}}')
holds, during_pin = {}, [None]
P._turn_update_due = lambda sched, last, now: True
P._resolve_turn_tag = lambda owner: "v2"
P._turn_hold_get = lambda nid, key: holds.get((nid, key), "")
def pin(owner, arches=None, wait=25, force=False):
    if during_pin[0]:
        during_pin[0]()                                  # what the operator does while pass 1 waits on GitHub
    return {"tag": "v2"}
P.turn_pin = pin
def tick(turn=None, during=None):
    holds.clear(); during_pin[0] = during
    with P._api_lock:
        P.nodes_save(NP, {"n1": {"name": "edge", **({"turn": turn} if turn else {})}})
    P.Handler.deps = {"fleet": {}, "nodes_path": NP, "roster_path": RP, "panel_settings_path": PSP,
                      "node_snaps": {"n1": {"turn_proxies": [{"service": SVC, "version": "v1", "params": ""}]}}}
    P._turn_autoupdate_tick()
    return ((P.nodes_load(NP)["n1"].get("turn") or {}).get(SVC) or {})
got = tick()
check("control: an out-of-date proxy with nothing pending is staged for an auto-reinstall",
      got.get("action") == "reinstall" and got.get("auto") is True, got)
got = tick(turn={SVC: {"action": "delete", "at": 1}})
check("a pending DELETE is not overwritten by an auto-reinstall (it resurrected the proxy)", got.get("action") == "delete", got)
got = tick(turn={SVC: {"action": "stop", "at": 1}})
check("…nor a pending STOP", got.get("action") == "stop", got)
def stage_delete():
    with P._api_lock:
        n = P.nodes_load(NP); n["n1"]["turn"] = {SVC: {"action": "delete", "at": 2}}; P.nodes_save(NP, n)
got = tick(during=stage_delete)
check("a DELETE staged WHILE pass 1 fetched is not overwritten (pass 2 re-reads)", got.get("action") == "delete", got)
def edit_elsewhere():
    with P._api_lock:
        n = P.nodes_load(NP); n["n1"]["name"] = "edited-during-lookup"; P.nodes_save(NP, n)
tick(during=edit_elsewhere)
check("an edit made anywhere during pass 1's GitHub lookups survives the stage (no minutes-old copy saved)",
      P.nodes_load(NP)["n1"].get("name") == "edited-during-lookup", P.nodes_load(NP)["n1"].get("name"))
got = tick(during=lambda: holds.__setitem__(("n1", "fork:anton48"), "v1"))
check("a rollback HOLD placed while pass 1 fetched is honoured", not got, got)
got = tick(during=lambda: P.Handler.deps["node_snaps"]["n1"].__setitem__("turn_proxies", []))
check("a proxy the node stopped reporting meanwhile is not staged", not got, got)
got = tick(during=lambda: P.Handler.deps["node_snaps"]["n1"].__setitem__(
    "turn_proxies", [{"service": SVC, "version": "v2", "params": ""}]))
check("a proxy that reached the tag meanwhile is not reinstalled again", not got, got)


print("[rmw] a lock-free POST writes neither store")
# _LOCKLESS_POST runs without _api_lock — a promise that the handler saves nothing. Run each one, lock NOT held, with its
# network stubbed: a 200 (it really reached its network call) and both stores byte-for-byte as they were.
with P._api_lock:
    P.nodes_save(NP, {"n1": {"name": "edge"}}); P.roster_save(RP, {"peers": {}, "users": {}})
P._check_latest_remote = lambda budget=120: True
P._check_turn_latest = lambda deps: True
P.catalog_index = lambda force=False: {}
P._webhook_post = lambda url, secret, body, timeout=8: 200
P.transfer_call = lambda url, token, path, obj=None, timeout=25, pin="": (200, {"data": {"name": "far"}}, {"fp": "", "verified": False})
LDEPS = {"fleet": {}, "nodes_path": NP, "roster_path": RP, "node_snaps": {}, "node_seen": {},
         "panel_settings": {"api": {"webhooks": [{"id": "w1", "url": "https://hook.example/x"}]}}}
BODIES = {"/api/turn/check-updates": {"forks": [{"id": "anton48", "owner": "anton48/vk-turn-proxy"}]},
          "/api/integrations/webhook/test": {"id": "w1"},
          "/api/nodes/transfer/preflight": {"node": "n1", "paste": "bash bootstrap.sh node -key " + "k" * 32
                                                                   + " -host https://far.example"}}
for path in sorted(P._LOCKLESS_POST):
    before = (open(NP).read(), open(RP).read())
    try:
        c, o = P.api("POST", path, {}, BODIES.get(path, {}), LDEPS)
        err = "" if c == 200 else "HTTP %s %s" % (c, str(o)[:160])
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    check("%s, run without the lock, saves neither store" % path,
          not err and (open(NP).read(), open(RP).read()) == before, err or "a store changed")


print("[rmw] the sync bound")
check("SYNC_LOCK_WAIT answers well inside noded's 20 s request timeout", 0 < P.SYNC_LOCK_WAIT <= 15, P.SYNC_LOCK_WAIT)
check("SYNC_LOCK_WAIT is well under NODE_OFFLINE (a 503 is not an outage)",
      P.SYNC_LOCK_WAIT < P.NODE_OFFLINE, (P.SYNC_LOCK_WAIT, P.NODE_OFFLINE))

print("\n" + ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
