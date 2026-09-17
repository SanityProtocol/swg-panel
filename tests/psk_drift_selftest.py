#!/usr/bin/env python3
"""Self-test for PRESHARED-KEY DRIFT — the one peer-config change `reconcile` used to ignore.

The panel owns the PSK. WireGuard mixes it into every handshake, so a peer whose stored key has moved on
cannot complete one — and NOTHING says so: the server cannot authenticate the handshake and stays silent,
the client's app sits on "connected". `reconcile` re-applied a changed AllowedIPs and a changed endpoint,
never a changed PSK, so such a peer stayed stranded for ever with `errors=[]` on every sync.

Measured on a live node 2026-09-16 (a client's box): panel PSK for one device had moved on 09-13, awg2 still
held the old one, three days of "connected but no traffic". Its twin on the same box's `wg1` — same device,
same public key, key in step — worked throughout, which is what isolated it.

What this drives, through the REAL `reconcile`:
  [1] no drift → the agent is not called at all (a healthy peer is never bounced)
  [2] drift → remove-peer THEN add-peer carrying the panel's key verbatim, plus the peer's other fields
  [3] the panel did not send the field (an older panel) → NOTHING happens — "I was not told" must never read
      as "take the key away" ([[lesson-detection-failure-fail-safe]])
  [4] the panel says "none" and the interface has one → also drift, re-asserted keyless
  [5] a peer the live read does not cover → no action
  [6] a key that does NOT stick is retried with backoff, not bounced every sync — success is proven by the
      NEXT read of the interface, never by the agent's "ok"
  [7] …and a corrected desired key retries at once instead of waiting out that backoff
  [8] once the interface confirms the new key, the peer is left alone

Hermetic: the agent and the interface read are stubbed; nothing shells out, no network, no state written
outside a temp dir.

Run: python3 tests/psk_drift_selftest.py          (0 = pass)
     --perturb        drops the "did the panel tell us?" guard — expects RED in [3]
     --perturb-churn  counts the agent's "ok" as proof — expects RED in [6]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {
    "--perturb": ('if "preshared_key" in p and pk in live_psk:', "if pk in live_psk:"),
    "--perturb-churn": ('_op_fail(kk, err="applied; awaiting confirmation")', "_op_ok(kk)"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod

if MODE:
    src = open(NODED, encoding="utf-8").read()
    cut, new = PLANTS[MODE]
    assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
    tmp = os.path.join(HERE, ".perturbed-noded-psk.py")
    open(tmp, "w", encoding="utf-8").write(src.replace(cut, new, 1))
    N = _load(tmp, "swgnoded")
    os.unlink(tmp)
else:
    N = _load(NODED, "swgnoded")

N.STATE_DIR = tempfile.mkdtemp()            # reconcile persists mesh endpoints there
IFACE = "awg2"
PK = "5dYQ79ynisVEC8XyQgXamgfpZe38PN6KihtEV6kpGjk="
NEWKEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
OLDKEY = "cHJpdmF0ZS1rZXktcHJpdmF0ZS1rZXktcHJpdmF0ZS0="
CFG = {"interfaces": {IFACE: {"cmd": ["awg"], "conf": "/tmp/awg2.conf"}}}

calls = []
def stub_agent(ok=True, code=None):
    def f(agent, sudo, payload):
        calls.append(payload)
        return {"ok": ok} if ok else {"ok": False, "error": "refused", "code": code}
    N.run_agent = f
N.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out in this test"))

def live(psk, pubkey=PK):
    """One live peer on the interface, with `psk` as its preshared key (None = keyless)."""
    peers = [{"public_key": pubkey, "preshared_key": psk, "endpoint": None,
              "allowed_ips": "10.11.0.2/32", "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0}]
    N._iface_dump = lambda cfg, ifn: (["dev", "key", "51822"], peers)

def want(psk="__set__", **over):
    p = {"public_key": PK, "allowed_ips": "10.11.0.2/32", "name": "Bazzite"}
    if psk != "__omit__":
        p["preshared_key"] = NEWKEY if psk == "__set__" else psk
    p.update(over)
    return {IFACE: [p]}

def run_once():
    calls.clear()
    return N.reconcile(CFG, want(), "/opt/swg-agent/swg-agent", False)

# ── [1] no drift — a healthy peer is never touched ────────────────────────────────────────────────
stub_agent()
live(NEWKEY)
res = run_once()
check("[1] key in step: the agent is never called", calls == [], calls)
check("[1] …and nothing is counted as a change", res["added"] == 0 and not res["errors"], res)

# ── [2] drift — remove then re-add with the panel's key ───────────────────────────────────────────
live(OLDKEY)
res = run_once()
ops = [c.get("op") for c in calls]
check("[2] drift is acted on: remove-peer then add-peer", ops == ["remove-peer", "add-peer"], ops)
add = next((c for c in calls if c.get("op") == "add-peer"), {})
check("[2] …the add carries the PANEL's key verbatim", add.get("preshared_key") == NEWKEY, add.get("preshared_key"))
check("[2] …and the peer's other fields ride along, so nothing else changes",
      add.get("allowed_ips") == "10.11.0.2/32" and add.get("name") == "Bazzite", add)
check("[2] …counted as a change so the sync says so", res["added"] == 1, res)

# ── [3] the panel never sent the field — DO NOTHING ───────────────────────────────────────────────
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
live(OLDKEY)
calls.clear()
res = N.reconcile(CFG, want("__omit__"), "/opt/swg-agent/swg-agent", False)
check("[3] an older panel that sends no key leaves the peer alone", calls == [], calls)

# ── [4] the panel says 'none' while the interface holds one ───────────────────────────────────────
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
live(OLDKEY)
calls.clear()
res = N.reconcile(CFG, want("none"), "/opt/swg-agent/swg-agent", False)
add = next((c for c in calls if c.get("op") == "add-peer"), {})
check("[4] 'none' is a value too: the peer is re-asserted keyless",
      [c.get("op") for c in calls] == ["remove-peer", "add-peer"] and add.get("preshared_key") == "none", calls)

# ── [5] a peer the live read does not cover ───────────────────────────────────────────────────────
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
live(OLDKEY, pubkey="someoneelse=")
calls.clear()
N.reconcile(CFG, want(), "/opt/swg-agent/swg-agent", False)
# ⚠️ ASSERT ON THIS PEER'S OWN CALLS. The reconcile ALSO reaps a live peer the panel does not list, so the
# fixture's invented stray contributes a remove-peer of its own — comparing the whole call list made this
# check fail for a reason that has nothing to do with preshared keys.
check("[5] a pubkey the interface never reported is ADDED, never 'drift-fixed'",
      [c.get("op") for c in calls if c.get("public_key") == PK] == ["add-peer"], calls)
check("[5] …and the stray it does not list is still reaped, as before",
      [c.get("op") for c in calls if c.get("public_key") == "someoneelse="] == ["remove-peer"], calls)

# ── [6] a key that does not stick: backoff, not a bounce every sync ───────────────────────────────
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
stub_agent()
live(OLDKEY)                      # the interface KEEPS reporting the old key — the apply never took
first = run_once()
check("[6] first pass applies it", [c.get("op") for c in calls] == ["remove-peer", "add-peer"], calls)
second = run_once()
check("[6] the very next sync does NOT bounce the peer again — success is the next READ, not the agent's ok",
      calls == [], calls)
check("[6] …and it says why rather than going quiet",
      any("psk" in e for e in second["errors"]), second["errors"])

# ── [7] a corrected desired key retries at once ───────────────────────────────────────────────────
calls.clear()
N.reconcile(CFG, want("Dk9nOTJ3aGF0ZXZlci1hLXRoaXJkLWtleS12YWx1ZT0="), "/opt/swg-agent/swg-agent", False)
check("[7] a CHANGED desired key clears the backoff and is applied immediately",
      [c.get("op") for c in calls] == ["remove-peer", "add-peer"], calls)

# ── [8] once the interface confirms it, the peer is left alone ────────────────────────────────────
N._OP_BACKOFF.clear(); N._OP_LASTCFG.clear()
live(NEWKEY)
res = run_once()
check("[8] the confirmed key ends the retries — no churn", calls == [] and res["added"] == 0, (calls, res))

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
