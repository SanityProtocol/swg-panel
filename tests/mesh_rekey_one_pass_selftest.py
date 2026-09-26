#!/usr/bin/env python3
"""Self-test — a peer that takes over a stray's address comes up in ONE reconcile pass, with no "already assigned".

After a master's re-install (its node component removes the mesh links, the panel re-creates them with new keys), the
FAR end's link still held the old key on 10.255.0.0/32. reconcile added the desired peers first and removed strays at the
end of the pass, so the new key's add was refused ("10.255.0.0 already assigned" — swg-agent keeps one owner per address),
went into backoff, and the link stayed down until the retry: 15 s to a minute of "retrying later" (1.8.8 qualification,
rounds 4–5). It was not the panel re-creating a link it already had — the link was really gone on the re-installed end.
Strays of a panel-managed interface now go before the adds, as the panel's explicit retirements always did.

  [1] a mesh link re-keyed: one pass removes the old key and adds the new one — no error, nothing held in backoff
  [2] a managed user interface: a stray holding the address a new device is given — the same, one pass
  [3] an ADD-ONLY interface keeps its stray (it removes only what `remove` names), and a device the stray blocks waits
  [4] a stray that blocks nothing is still removed (as before), and a peer already in place is never touched

The REAL swg-noded reconcile; the agent is a stub that refuses an address another peer holds, as swg-agent does, and the
interface read is a model the stub keeps in step.

Run: python3 tests/mesh_rekey_one_pass_selftest.py      (0 = pass)
     --perturb   the shipped order (strays removed after the adds) planted back → RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
SRC = open(NODED, encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

if PERTURB:   # strays after the adds, as shipped
    a = SRC.index("        # …and on an interface the panel manages, every STRAY goes before the adds too")
    b = SRC.index("        for pk, p in desired.items():\n            if pk in current:\n", a)
    moved = SRC[a:b]
    SRC = SRC[:a] + SRC[b:]
    anchor = "        # (An onboarded interface is ADD-ONLY: the panel never removes peers it didn't create"
    assert SRC.count(anchor) == 1, "perturbation anchor missing — would FALSE-PASS"
    SRC = SRC.replace(anchor, moved + anchor, 1)

p = os.path.join(tempfile.mkdtemp(prefix="rekey-"), "swg-noded"); open(p, "w").write(SRC)
ld = importlib.machinery.SourceFileLoader("swgnoded_rekey", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_rekey", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
N.STATE_DIR = tempfile.mkdtemp(prefix="rekey-st-")
N.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out in this test"))
K = lambda c: (c * 43)[:43] + "="

WIRE = {}      # iface -> {pubkey: allowed_ips}
CALLS = []
def dump(cfg, ifn):
    return (["dev", "key", "9999"], [{"public_key": k, "preshared_key": None, "endpoint": "192.168.77.1:9999" if ifn.startswith("swg_") else None,
                                      "allowed_ips": a, "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0} for k, a in WIRE.get(ifn, {}).items()])
def agent(_a, _s, req):
    CALLS.append(req)
    ifn, pk = req.get("iface"), req.get("public_key")
    if req.get("op") == "remove-peer":
        WIRE.get(ifn, {}).pop(pk, None); return {"ok": True}
    if req.get("op") == "add-peer":
        want = set((req.get("allowed_ips") or "").split(","))
        for other, a in WIRE.get(ifn, {}).items():
            if other != pk and want & set(a.split(",")):
                return {"ok": False, "error": "%s already assigned" % sorted(want & set(a.split(",")))[0].split("/")[0], "code": "ip_in_use"}
        WIRE.setdefault(ifn, {})[pk] = req.get("allowed_ips") or ""; return {"ok": True}
    return {"ok": True}
N._iface_dump = dump
N.run_agent = agent

def one_pass(cfg, desired):
    CALLS.clear()
    return N.reconcile(cfg, desired, "/opt/swg-agent/swg-agent", False, {})

OLD, NEW, A, B, S = K("O"), K("N"), K("A"), K("B"), K("S")
CFG = {"interfaces": {"swg_ab": {"cmd": ["awg"], "conf": "/tmp/swg_ab.conf"},
                      "wg0": {"cmd": ["wg"], "conf": "/tmp/wg0.conf"},
                      "wg5": {"cmd": ["wg"], "conf": "/tmp/wg5.conf", "onboarded": True}}}

print("[1] a mesh link re-created with new keys")
WIRE.clear(); WIRE["swg_ab"] = {OLD: "10.255.0.0/32"}
res = one_pass(CFG, {"swg_ab": [{"public_key": NEW, "allowed_ips": "10.255.0.0/32", "preshared_key": "none",
                                 "endpoint": "192.168.77.1:9999", "persistent_keepalive": 25, "name": "mesh:q1m"}]})
check("[1] one pass: the old key goes, the new one is up", WIRE["swg_ab"] == {NEW: "10.255.0.0/32"}, (WIRE, res))
check("[1] …no error, and nothing waiting in backoff", not res.get("errors") and not [k for k in N._OP_BACKOFF if NEW in k], res)

print("\n[2] a managed interface: a stray holds the address a new device is given")
WIRE.clear(); WIRE["wg0"] = {S: "10.8.0.2/32", A: "10.8.0.3/32"}
res = one_pass(CFG, {"wg0": [{"public_key": A, "allowed_ips": "10.8.0.3/32", "preshared_key": "none", "name": "a"},
                             {"public_key": B, "allowed_ips": "10.8.0.2/32", "preshared_key": "none", "name": "b"}]})
check("[2] one pass: the stray goes, the device is up, no error",
      WIRE["wg0"] == {A: "10.8.0.3/32", B: "10.8.0.2/32"} and not res.get("errors"), (WIRE, res))
check("[4] the peer already in place is never touched", not [c for c in CALLS if c.get("public_key") == A], CALLS)

print("\n[3] an add-only interface")
WIRE.clear(); WIRE["wg5"] = {S: "10.65.0.9/32"}
res = one_pass(CFG, {"wg5": [{"public_key": B, "allowed_ips": "10.65.0.2/32", "preshared_key": "none", "name": "b"}]})
check("[3] its stray stays (it removes only what `remove` names); a free address is still added",
      WIRE["wg5"] == {S: "10.65.0.9/32", B: "10.65.0.2/32"} and not res.get("errors"), (WIRE, res))

print("\n[4] a stray that blocks nothing")
WIRE.clear(); WIRE["wg0"] = {S: "10.8.0.99/32", A: "10.8.0.3/32"}
res = one_pass(CFG, {"wg0": [{"public_key": A, "allowed_ips": "10.8.0.3/32", "preshared_key": "none", "name": "a"}]})
check("[4] is still removed, as before", WIRE["wg0"] == {A: "10.8.0.3/32"} and res.get("removed") == 1, (WIRE, res))

print()
if PERTURB:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
