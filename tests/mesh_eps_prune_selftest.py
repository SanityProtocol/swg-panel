#!/usr/bin/env python3
"""Self-test: the node's mesh endpoint memory (mesh-eps.json) keeps exactly what the panel still wants — no more.

`reconcile` remembers, per `iface|peer-key`, the endpoint it last pushed, so a changed endpoint is re-dialled once
instead of fighting WireGuard's roaming. An entry used to leave that map only when its peer was removed from an
interface that is still there, so every deleted interface's entries stayed for ever — 6 of msk-main's 10 on swgt
(2026-09-19), left by rebuilt and transferred links; an on-demand mesh retires links routinely. Harmless to routing (a
recreated link has new keys; an add never reads the map) but unbounded.

Through the REAL `reconcile`, with the agent and the interface read stubbed:
  [1] an entry for a deleted interface is dropped, and so is one for a link's OLD peer key on an interface still here
  [2] the entry the panel still wants is kept, and a steady pass rewrites nothing
  [3] an interface that could not be read this pass keeps its entries (the keep-set comes from the reply, not the loop)
  [4] losing the file costs nothing: the peer is re-adopted from the live interface with no agent call

Hermetic: nothing shells out, no network, state in a temp dir.
Run: python3 tests/mesh_eps_prune_selftest.py            (0 = pass)
     python3 tests/mesh_eps_prune_selftest.py --perturb  every plant must go red on its own check ("N plants, N caught")
"""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = [
    ("no-prune", "    for _k in [k for k in applied_ep if k not in _want_ep]:", "    for _k in []:",
     "[1] a deleted interface's entry is dropped"),
    ("iface-only", "    for _k in [k for k in applied_ep if k not in _want_ep]:",
     "    for _k in [k for k in applied_ep if k.split('|')[0] not in (node_cfg.get('interfaces') or {})]:",
     "[1] a link's OLD peer key on a live interface is dropped"),
    ("from-the-loop", "    _want_ep = {i + \"|\" + p[\"public_key\"] for i in (node_cfg.get(\"interfaces\") or {})",
     "    _want_ep = {i + \"|\" + p[\"public_key\"] for i in (node_cfg.get(\"interfaces\") or {}) if _iface_dump(node_cfg, i) is not None",
     "[3] an interface that could not be read keeps its entry"),
]

if "--perturb" in sys.argv:
    src = open(NODED, encoding="utf-8").read()
    caught, bad = 0, []
    for name, old, new, must in PLANTS:
        if src.count(old) != 1:
            bad.append("%s: anchor found %d times (stale plant)" % (name, src.count(old))); continue
        with tempfile.NamedTemporaryFile("w", suffix="-swg-noded", delete=False) as f:
            f.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_NODED=f.name),
                           capture_output=True, text=True, timeout=120)
        os.unlink(f.name)
        red = ("  FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-14s %s" % (name, "caught" if red else ("CRASHED (not a catch)" if "Traceback" in r.stderr else "NOT CAUGHT")))
        caught += red
        if not red:
            bad.append(name)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    for b in bad:
        print("  ✗ " + b)
    sys.exit(0 if caught == len(PLANTS) and not bad else 1)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

l = importlib.machinery.SourceFileLoader("swgnoded", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", l))
try:
    l.exec_module(N)
except SystemExit:
    pass

N.STATE_DIR = tempfile.mkdtemp()
EPF = os.path.join(N.STATE_DIR, "mesh-eps.json")
PEER, OLDPEER, GONE, DARKPEER = "PEERkey" + "A" * 36 + "=", "OLDpeer" + "B" * 36 + "=", "GONEkey" + "C" * 36 + "=", "DARKkey" + "D" * 36 + "="
EP, DARKEP = "203.0.113.5:9999", "198.51.100.7:10001"
CFG = {"interfaces": {"swg_live": {"cmd": ["awg"]}, "swg_dark": {"cmd": ["awg"]}}}

calls = []
N.run_agent = lambda agent, sudo, payload: (calls.append(payload), {"ok": True})[1]
N.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out in this test"))
# swg_live answers with its one peer, dialled to the desired endpoint and handshaking; swg_dark cannot be read.
N._iface_dump = lambda cfg, ifn: ((["dev", "key", "9999"], [{"public_key": PEER, "preshared_key": None, "endpoint": EP,
                                                             "allowed_ips": "10.255.0.1/32", "last_handshake": int(time.time()),
                                                             "rx_bytes": 0, "tx_bytes": 0}])
                                  if ifn == "swg_live" else None)
WANT = {"swg_live": [{"public_key": PEER, "allowed_ips": "10.255.0.1/32", "endpoint": EP, "preshared_key": "none",
                      "persistent_keepalive": 25, "name": "mesh:peer"}],
        "swg_dark": [{"public_key": DARKPEER, "allowed_ips": "10.255.0.3/32", "endpoint": DARKEP, "preshared_key": "none",
                      "persistent_keepalive": 25, "name": "mesh:dark"}]}

def eps():
    try:
        return json.load(open(EPF))
    except OSError:
        return None

json.dump({"swg_live|" + PEER: EP, "swg_live|" + OLDPEER: "203.0.113.5:9998", "swg_gone|" + GONE: "192.0.2.9:10002",
           "swg_dark|" + DARKPEER: DARKEP}, open(EPF, "w"))

print("[1] entries the panel no longer wants are dropped")
calls.clear()
N.reconcile(CFG, WANT, "/opt/swg-agent/swg-agent", False)
e = eps()
check("[1] a deleted interface's entry is dropped", "swg_gone|" + GONE not in e, e)
check("[1] a link's OLD peer key on a live interface is dropped", "swg_live|" + OLDPEER not in e, e)
check("[1] …and the tunnel was not touched (no agent call)", calls == [], calls)

print("[2] what the panel still wants is kept, and a steady pass writes nothing")
check("[2] the wanted entry is kept, with its endpoint", e.get("swg_live|" + PEER) == EP, e)
m0 = os.stat(EPF).st_mtime_ns
time.sleep(0.02)
N.reconcile(CFG, WANT, "/opt/swg-agent/swg-agent", False)
check("[2] a second, steady pass does not rewrite the file", os.stat(EPF).st_mtime_ns == m0 and eps() == e, eps())

print("[3] an interface that could not be read this pass keeps its entries")
check("[3] an interface that could not be read keeps its entry", eps().get("swg_dark|" + DARKPEER) == DARKEP, eps())

print("[4] losing the file costs nothing")
os.unlink(EPF)
calls.clear()
N.reconcile(CFG, WANT, "/opt/swg-agent/swg-agent", False)
check("[4] the live peer is re-adopted from the interface — no agent call", calls == [], calls)
check("[4] …and remembered again", (eps() or {}).get("swg_live|" + PEER) == EP, eps())

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("OK")
