#!/usr/bin/env python3
"""Self-test — a public key is derived once per private key, not once per pass.

`<tool> pubkey` is pure key math, yet a down interface's meta (`derive_pubkey`) and every Docker WDTT server's report
(`_wdtt_server_pub`: the UAPI's private key → `wg pubkey`) spawned it on every pass — three a pass on svo-im.

  [1] One private key: derived once over many calls, the same answer every time.
  [2] Another key is derived on its own; both are kept.
  [3] A derivation that failed is not kept: asked again the next time.
  [4] No private key is kept — only a digest of it.
  [5] A Docker WDTT server's key: once over many passes.

Run: python3 tests/pubkey_memo_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     nomemo       every call derives again
     keepfail     a failed derivation is kept
"""
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "nomemo": ("""    pub = _PUBKEYS.get(h)
    if pub is None:""", """    pub = None
    if pub is None:"""),
    "keepfail": ("""        if pub:
            if len(_PUBKEYS) >= 64:""", """        if True:
            if len(_PUBKEYS) >= 64:"""),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="pubkey-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("pk_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("pk_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None

CALLS, FAIL = [], {"on": False}
PRIV1, PRIV2 = "cHJpdmF0ZS1rZXktb25lLWZvci10aGUtdGVzdC0wMDA=", "cHJpdmF0ZS1rZXktdHdvLWZvci10aGUtdGVzdC0wMDA="


def fake_run(args, input_text=None, timeout=20, env=None):
    CALLS.append((" ".join(args), input_text))
    if args[-1] == "pubkey":
        if FAIL["on"]:
            return subprocess.CompletedProcess(args, 1, "", "Key is not the correct length or format")
        return subprocess.CompletedProcess(args, 0, "PUB(%s)\n" % (input_text or "").strip()[:8], "")
    return subprocess.CompletedProcess(args, 0, "", "")


N.run = fake_run


def derives():
    return sum(c.endswith("pubkey") for c, _ in CALLS)


# ── [1] once per key ──────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] one private key")
got = [N.derive_pubkey(["awg"], PRIV1) for _ in range(5)]
check("[1] derived once over five calls, the same answer every time", derives() == 1 and got == ["PUB(cHJpdmF0)"] * 5, (derives(), got))

# ── [2] another key ───────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] another key")
CALLS.clear()
a, b = N._pubkey_of(["wg"], PRIV2), N._pubkey_of(["wg"], PRIV2)
c = N.derive_pubkey(["awg"], PRIV1)
check("[2] derived on its own once; the first is still kept", derives() == 1 and a == b and c == "PUB(cHJpdmF0)", CALLS)

# ── [3] a failed derivation ───────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] a derivation that failed")
CALLS.clear()
FAIL["on"] = True
check("[3] it answers None (as before)", N.derive_pubkey(["awg"], "bm90LWEta2V5") is None)
FAIL["on"] = False
check("[3] …and is asked again the next time, which derives it", N.derive_pubkey(["awg"], "bm90LWEta2V5") == "PUB(bm90LWEt)" and derives() == 2,
      CALLS)

# ── [4] no private key kept ───────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] what is kept")
check("[4] digests only — no private key in the memo", N._PUBKEYS and all(isinstance(k, bytes) and len(k) == 32 for k in N._PUBKEYS)
      and not any(p in repr(N._PUBKEYS) for p in (PRIV1, PRIV2)), list(N._PUBKEYS)[:2])

# ── [5] a Docker WDTT server ──────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] a Docker WDTT server's key")
N.NODE_KIND = "docker"
N._wdtt_uapi = lambda iface: ("a1" * 32, {})
CALLS.clear()
keys = [N._wdtt_server_pub("wdtt1") for _ in range(6)]
check("[5] once over six passes, the same key", derives() == 1 and len(set(keys)) == 1 and keys[0], (derives(), keys))

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
