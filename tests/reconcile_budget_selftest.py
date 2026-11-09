#!/usr/bin/env python3
"""Self-test — the node's peer ops have a time budget (docs/SCALE-PLAN.md N1, "K5 — design").

`reconcile()` spawned one `swg-agent` per peer op and posted no snapshot until it was done: 2,500 new peers were ONE pass of
112 s on a laptop (K0, §1.4) and minutes on a 1-vCPU box, so the panel read the node offline (30 s) and fired its webhook.
Now reconcile stops STARTING ops once RECONCILE_BUDGET_S has passed since its own start; the rest is counted in `deferred`
and the next pass (which skips its sleep) takes them — the panel re-sends the whole desired set every sync.

  [1] Under the budget nothing changes: the real reconcile against a17e56e0's (the code before N1) on 200 random interfaces —
      adds, strays, retirements, AllowedIPs / PSK / endpoint drift, stale mesh links, a .conf naming an old endpoint, agent
      failures and `peer_exists` — the same agent calls in the same order, the same result, the same mesh-eps.json, over two
      passes each; `deferred` 0.
  [2] Budget 0: no op starts; `deferred` counts the ops due (a PSK bounce — remove + add — is one); no error; no backoff
      step (an op not started is not a failure).
  [3] A budget that runs out mid-interface: the removes come first, and once they are cut none of that interface's adds
      starts (an add must never meet an address a deferred remove still holds).
  [4] A pair is never split: PSK bounces cut by the budget leave remove + add pairs only.
  [5] A deferred persist-peer-endpoint is asked again the next pass (its once-per-change marker is not set).
  [6] Progress: with the default budget every pass starts at least one op (the budget counts from reconcile's own start).

Hermetic: the agent and the interface read are stubbed; nothing shells out.

Run: python3 tests/reconcile_budget_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     pairsplit   the budget asked between a PSK bounce's remove and its add
     deferr      a deferred op counted as an error
     passstart   the budget counted as if the pass had already spent 10 s before reconcile
     psknobudget the PSK bounce ignores the budget
"""
import importlib.machinery, importlib.util, json, os, random, shutil, subprocess, sys, tempfile, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.path.join(ROOT, "swg-noded")
BASE = "a17e56e0"                     # the last commit before N1
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PSK_REMOVE = ('''                            run_agent(agent, sudo, {"op": "remove-peer", "iface": iface, "public_key": pk})
                            r = run_agent(agent, sudo, {"op": "add-peer", "iface": iface, "public_key": pk,''')
PLANTS = {
    "pairsplit": (PSK_REMOVE, PSK_REMOVE.replace('"public_key": pk})\n', '"public_key": pk})\n                            if not go(): continue\n', 1)),
    "deferr": ('''        res["deferred"] += 1
        return False''', '''        res["deferred"] += 1
        res["errors"].append("deferred")
        return False'''),
    "passstart": ("    _end = time.monotonic() + budget\n", "    _end = time.monotonic() + budget - 10\n"),
    "psknobudget": ('''                            res["errors"].append(f"psk {pk[:8]}: retrying later (repeated failure)")
                        elif go():''', '''                            res["errors"].append(f"psk {pk[:8]}: retrying later (repeated failure)")
                        elif True:'''),
}


def load(src, name):
    tmp = os.path.join(HERE, ".budget-%s.py" % name)
    open(tmp, "w", encoding="utf-8").write(src)
    try:
        spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, tmp))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        return mod
    finally:
        os.unlink(tmp)


src = open(NODED, encoding="utf-8").read()
if PLANT:
    cut, new = PLANTS[PLANT]
    assert src.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
    src = src.replace(cut, new, 1)
N = load(src, "swgnoded_budget_new")
O = load(subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-noded"], capture_output=True, text=True, check=True).stdout,
         "swgnoded_budget_old")
TMP = tempfile.mkdtemp(prefix="reconcile-budget-")
NOW = int(time.time())


def key(rnd):
    return "".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for _ in range(43)) + "="


class World:
    """One node's live interfaces + .conf files + mesh-eps.json, served to a module's reconcile."""

    def __init__(self, live, confs, eps, fail_pct=0, sleep=0.0):
        self.live, self.confs, self.eps, self.fail_pct, self.sleep = live, confs, eps, fail_pct, sleep
        self.calls = []

    def bind(self, M, tag):
        sd = os.path.join(TMP, tag); shutil.rmtree(sd, ignore_errors=True); os.makedirs(sd)
        M.STATE_DIR = sd
        M.IFACE_STOPPED_FILE = os.path.join(sd, "iface-stopped.json")
        json.dump(self.eps, open(os.path.join(sd, "mesh-eps.json"), "w"))
        cfg = {"interfaces": {}}
        for ifn, (ic, peers) in self.live.items():
            cp = os.path.join(sd, ifn + ".conf"); open(cp, "w").write(self.confs.get(ifn, ""))
            cfg["interfaces"][ifn] = {**ic, "conf": cp}
        M._iface_dump = lambda c, ifn: (["dev", "key", "51820"], [dict(p) for p in self.live[ifn][1]])
        M.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out here"))
        M._OP_BACKOFF.clear(); M._OP_LASTCFG.clear(); M._OP_LASTERR.clear(); M._EP_CONF.clear()
        self.calls = []

        def agent(a, s, payload):
            self.calls.append(json.dumps(payload, sort_keys=True))
            if self.sleep:
                time.sleep(self.sleep)
            h = int(hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:6], 16) % 100
            if h < self.fail_pct:
                return {"ok": False, "error": "refused", "code": "peer_exists" if h % 2 else "internal"}
            return {"ok": True}
        M.run_agent = agent
        return cfg, sd


def scenario(rnd):
    live, confs, eps, desired, remove = {}, {}, {}, {}, {}
    for ifn in rnd.sample(["wg0", "awg2", "swg_ab12"], rnd.randint(1, 3)):
        ic = {"cmd": ["wg"] if ifn == "wg0" else ["awg"], **({"onboarded": True} if rnd.random() < 0.3 else {})}
        keys = [key(rnd) for _ in range(rnd.randint(0, 12))]
        lv, ds, conf = [], [], ["[Interface]", "PrivateKey = x"]
        for k in keys:
            n = rnd.randint(2, 250)
            mesh = rnd.random() < 0.3
            ep = "203.0.113.%d:%d" % (rnd.randint(1, 9), rnd.randint(1000, 1003)) if mesh else None
            here, want = rnd.random() < 0.7, rnd.random() < 0.7
            if here:
                lv.append({"public_key": k, "preshared_key": rnd.choice([None, "P" * 43 + "=", "Q" * 43 + "="]),
                           "endpoint": rnd.choice([ep, None, "198.51.100.1:5"]), "allowed_ips": "10.9.0.%d/32" % n,
                           "last_handshake": rnd.choice([0, NOW - 10, NOW - 2000]), "rx_bytes": 0, "tx_bytes": 0})
                conf += ["[Peer]", "PublicKey = " + k] + (["Endpoint = " + rnd.choice([ep or "", "192.0.2.9:1"])] if mesh else [])
            if want:
                p = {"public_key": k, "allowed_ips": rnd.choice(["10.9.0.%d/32" % n, "0.0.0.0/0", "10.9.0.%d/32" % n]),
                     "name": "d%d" % n}
                r = rnd.random()
                if r < 0.6:
                    p["preshared_key"] = rnd.choice(["P" * 43 + "=", "Q" * 43 + "=", "none"])
                if ep:
                    p["endpoint"] = ep; p["persistent_keepalive"] = 25
                    if rnd.random() < 0.5:
                        eps[ifn + "|" + k] = rnd.choice([ep, "192.0.2.9:1"])
                ds.append(p)
            elif here and rnd.random() < 0.4:
                remove.setdefault(ifn, []).append(k)
        live[ifn] = (ic, lv); desired[ifn] = ds; confs[ifn] = "\n".join(conf) + "\n"
    return live, confs, eps, desired, remove


# ── [1] the differential ──────────────────────────────────────────────────────────────────────────────────────────────
print("[1] under the budget, reconcile is a17e56e0's")
rnd, bad, ops_seen = random.Random(1912), [], 0
for i in range(200):
    live, confs, eps, desired, remove = scenario(rnd)
    fail = rnd.choice([0, 0, 15])
    wn, wo = World(live, confs, eps, fail), World(live, confs, eps, fail)
    cn, sn = wn.bind(N, "new"); co, so = wo.bind(O, "old")
    for pas in (1, 2):
        rn = N.reconcile(cn, desired, "/a", False, remove)
        ro = O.reconcile(co, desired, "/a", False, remove)
        d = rn.pop("deferred", None)
        mn = open(os.path.join(sn, "mesh-eps.json")).read(); mo = open(os.path.join(so, "mesh-eps.json")).read()
        if wn.calls != wo.calls or rn != ro or d != 0 or mn != mo:
            bad.append((i, pas, wn.calls[:3], wo.calls[:3], rn, ro, d))
        ops_seen += len(wn.calls)
        wn.calls, wo.calls = [], []
check("[1] 200 random nodes × 2 passes: the same agent calls, result and mesh-eps.json; nothing deferred",
      not bad, bad[:1])
check("[1] …and the scenarios really drove ops (agent calls seen: %d)" % ops_seen, ops_seen > 1000, ops_seen)

# ── [2] budget 0 ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] budget 0: nothing starts, everything is counted, nothing fails")
K = [key(random.Random(7 + j)) for j in range(8)]
lv = [{"public_key": K[0], "preshared_key": "P" * 43 + "=", "endpoint": None, "allowed_ips": "10.9.0.2/32",
       "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0},                                         # PSK drift (a pair)
      {"public_key": K[1], "preshared_key": None, "endpoint": None, "allowed_ips": "10.9.0.3/32",
       "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0},                                         # a stray
      {"public_key": K[2], "preshared_key": None, "endpoint": None, "allowed_ips": "10.9.0.4/32",
       "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0}]                                         # AllowedIPs drift
want = {"wg0": [{"public_key": K[0], "allowed_ips": "10.9.0.2/32", "preshared_key": "Q" * 43 + "="},
                {"public_key": K[2], "allowed_ips": "10.9.0.4/32,10.9.1.0/24"},
                {"public_key": K[3], "allowed_ips": "10.9.0.5/32"}, {"public_key": K[4], "allowed_ips": "10.9.0.6/32"}]}
w = World({"wg0": ({"cmd": ["wg"]}, lv)}, {}, {})
cfg, _sd = w.bind(N, "zero")
r = N.reconcile(cfg, want, "/a", False, {}, budget=0)
check("[2] no agent call", w.calls == [], w.calls)
check("[2] deferred = 5 (a PSK bounce, a stray, an AllowedIPs, two adds)", r.get("deferred") == 5, r)
check("[2] no error and no change counted", r["errors"] == [] and r["added"] == 0 and r["removed"] == 0, r)
check("[2] no backoff step", N._OP_BACKOFF == {}, N._OP_BACKOFF)
r2 = N.reconcile(cfg, want, "/a", False, {})
check("[2] the next pass with its budget does it all", len(w.calls) == 6 and r2["deferred"] == 0, (w.calls, r2))

# ── [3] cut mid-interface: removes first, then no add ─────────────────────────────────────────────────────────────────
print("\n[3] a cut during the removes starts none of that interface's adds")
strays = [{"public_key": key(random.Random(100 + j)), "preshared_key": None, "endpoint": None,
           "allowed_ips": "10.9.1.%d/32" % j, "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0} for j in range(6)]
adds = [{"public_key": key(random.Random(200 + j)), "allowed_ips": "10.9.1.%d/32" % j} for j in range(6)]
w = World({"wg0": ({"cmd": ["wg"]}, strays)}, {}, {}, sleep=0.05)
cfg, _sd = w.bind(N, "mid")
r = N.reconcile(cfg, {"wg0": adds}, "/a", False, {}, budget=0.12)
ops = [json.loads(c)["op"] for c in w.calls]
check("[3] some removes ran, then the budget ran out", 1 <= len(ops) < 6 and set(ops) == {"remove-peer"}, ops)
check("[3] every op not started is counted (12 due)", r["deferred"] == 12 - len(ops), (r, ops))

# ── [4] a pair is never split ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] PSK bounces cut by the budget leave whole pairs")
lv = [{"public_key": key(random.Random(300 + j)), "preshared_key": "P" * 43 + "=", "endpoint": None,
       "allowed_ips": "10.9.2.%d/32" % j, "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0} for j in range(8)]
want = {"wg0": [{"public_key": p["public_key"], "allowed_ips": p["allowed_ips"], "preshared_key": "Q" * 43 + "="} for p in lv]}
w = World({"wg0": ({"cmd": ["wg"]}, lv)}, {}, {}, sleep=0.04)   # the deadline falls inside the 2nd pair's remove
cfg, _sd = w.bind(N, "pairs")
r = N.reconcile(cfg, want, "/a", False, {}, budget=0.1)
ops = [(json.loads(c)["op"], json.loads(c)["public_key"]) for c in w.calls]
pairs = all(ops[i][0] == "remove-peer" and ops[i + 1][0] == "add-peer" and ops[i][1] == ops[i + 1][1]
            for i in range(0, len(ops) - 1, 2)) and len(ops) % 2 == 0
check("[4] remove + add of the same key, never one without the other", pairs and 0 < len(ops) < 16, ops)
check("[4] the rest counted, one a pair", r["deferred"] == 8 - len(ops) // 2, (r, len(ops)))

# ── [5] a deferred persist-peer-endpoint is asked again ───────────────────────────────────────────────────────────────
print("\n[5] a deferred .conf endpoint write is asked again next pass")
k = key(random.Random(400)); ep = "203.0.113.5:9999"
lv = [{"public_key": k, "preshared_key": None, "endpoint": ep, "allowed_ips": "10.255.0.2/32", "last_handshake": NOW - 5,
       "rx_bytes": 0, "tx_bytes": 0}]
w = World({"swg_ab12": ({"cmd": ["awg"]}, lv)}, {"swg_ab12": "[Interface]\nPrivateKey = x\n[Peer]\nPublicKey = %s\nEndpoint = 192.0.2.9:1\n" % k},
          {"swg_ab12|" + k: ep})
cfg, _sd = w.bind(N, "persist")
want = {"swg_ab12": [{"public_key": k, "allowed_ips": "10.255.0.2/32", "endpoint": ep, "persistent_keepalive": 25}]}
r = N.reconcile(cfg, want, "/a", False, {}, budget=0)
check("[5] budget 0: not written, counted", w.calls == [] and r["deferred"] == 1, (w.calls, r))
r = N.reconcile(cfg, want, "/a", False, {})
check("[5] the next pass writes it", [json.loads(c)["op"] for c in w.calls] == ["persist-peer-endpoint"], w.calls)

# ── [6] progress with the default budget ──────────────────────────────────────────────────────────────────────────────
print("\n[6] the default budget starts ops at once")
w = World({"wg0": ({"cmd": ["wg"]}, [])}, {}, {})
cfg, _sd = w.bind(N, "progress")
r = N.reconcile(cfg, {"wg0": adds}, "/a", False, {})
check("[6] every add started, nothing deferred", len(w.calls) == 6 and r["deferred"] == 0, (len(w.calls), r))
check("[6] the budget is 10 s", N.RECONCILE_BUDGET_S == 10, N.RECONCILE_BUDGET_S)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS))))
if PLANT:
    print("plant %s: %s" % (PLANT, "RED (caught)" if FAILS else "GREEN — NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
