#!/usr/bin/env python3
"""Self-test for `inet_managed_ifaces` — WHICH devices the internet counter chain covers.

The bug this locks down: `reconcile_inet_chain` built its own device set as "node interfaces +
`_wdtt_load().keys()`" while `reconcile_egress` — which NATs the very same traffic — had grown explicit csqtt
and qWDTT-RAW legs. Two sets, one grammar, and the narrower one decided what got counted. Measured on
msk-main 2026-09-08: csqtt1 2.34 GB in / 3.04 GB out, csqtt2 1.5 MB / 12.2 MB, wdttraw2 2.0 MB / 53.3 MB of
live client internet, and `iptables -t mangle -S SWG_INET | grep -c csqtt` = 0.

The RAW case is the one a `.keys()` test can never catch: a raw instance owns TWO devices and only the wg one
is the record's key — the second TUN is a FIELD (`raw_iface`). So the interesting assertions here are the
ones about a device that is not a key.

Hermetic: no network, no iptables, no state dir — the two stores are monkeypatched. The wdtt/csqtt loaders
are the ONLY things stubbed, so `_wdtt_raw`'s real validation still runs (a malformed raw record must read as
OFF, not as a half-configured device).

Run: python3 tests/inet_managed_selftest.py (0 = pass).  --perturb re-runs with the fix backed out and
expects the checks to FAIL — a green run means nothing unless the red one is reachable.
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded", NODED)
spec = importlib.util.spec_from_loader("swgnoded", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

# ── the fleet shape that actually exists on msk-main ────────────────────────────────────────────────
NODE_CFG = {"interfaces": {"wg1": {}, "awg2": {}, "awg3": {}, "swg_1d430ded": {}}}
WDTT = {
    "wdtt1":     {"fork": "amurcanov"},                                                   # no raw
    "qwdtt1":    {"fork": "qwdtt"},                                                       # raw-capable, raw OFF
    "ildarm1":   {"fork": "ildarmaga", "raw_port": "56003",                               # raw ON → a SECOND device
                  "raw_iface": "wdttraw2", "raw_addr": "10.70.1.1/24", "listen": "1.2.3.4:56000"},
    "wdttbad1":  {"fork": "qwdtt", "raw_port": "56004",                                   # malformed → must read as OFF
                  "raw_iface": "not a device", "raw_addr": "nonsense"},
}
CSQTT = {"csqtt1": {}, "csqtt2": {}}

N._wdtt_load = lambda: dict(WDTT)
N._csqtt_load = lambda: dict(CSQTT)

if PERTURB:
    # Back the fix out FAITHFULLY — the pre-fix body verbatim, suppressor included. A stub without the
    # suppressor would raise on the store-failure checks below, and a perturbation that CRASHES cannot be
    # told apart from one that CAUGHT: both leave a non-zero exit and no verdict.
    import contextlib as _c
    def _prefix(cfg):
        managed = set((cfg.get("interfaces") or {}).keys())
        with _c.suppress(Exception):
            managed |= set(N._wdtt_load().keys())
        return sorted(managed)
    N.inet_managed_ifaces = _prefix

got = set(N.inet_managed_ifaces(NODE_CFG))
print("managed =", sorted(got))

check("node interfaces are covered", {"wg1", "awg2", "awg3", "swg_1d430ded"} <= got, sorted(got))
check("WDTT instances are covered", {"wdtt1", "qwdtt1", "ildarm1"} <= got, sorted(got))
check("csqtt instances are covered (the miscount)", {"csqtt1", "csqtt2"} <= got, sorted(got))
check("a RAW instance's SECOND device is covered (not a store key)", "wdttraw2" in got, sorted(got))
check("a malformed raw record reads as OFF, not as a device",
      not any(d.startswith("not") or d == "nonsense" for d in got), sorted(got))
check("exact set — raw-capable-but-OFF adds nothing, nothing else creeps in",
      len(got) == 4 + 4 + 2 + 1, sorted(got))
check("sorted, deduped", N.inet_managed_ifaces(NODE_CFG) == sorted(got), N.inet_managed_ifaces(NODE_CFG))

# A store that cannot be read must cost ITS OWN devices and nobody else's — one suppressor each.
def boom():
    raise OSError("store unreadable")
N._csqtt_load = boom
half = set(N.inet_managed_ifaces(NODE_CFG))
check("an unreadable csqtt store does not take WDTT/RAW down with it",
      {"wdtt1", "ildarm1", "wdttraw2"} <= half and not (half & {"csqtt1", "csqtt2"}), sorted(half))
N._csqtt_load = lambda: dict(CSQTT)
N._wdtt_load = boom
half2 = set(N.inet_managed_ifaces(NODE_CFG))
check("an unreadable WDTT store does not take csqtt down with it",
      {"csqtt1", "csqtt2"} <= half2 and not (half2 & {"wdtt1", "wdttraw2"}), sorted(half2))

# `read_inet_bytes` must take no arguments — it summed the WHOLE chain while advertising a filter.
import inspect
check("read_inet_bytes advertises no filter it does not apply",
      not inspect.signature(N.read_inet_bytes).parameters, str(inspect.signature(N.read_inet_bytes)))

if PERTURB:
    if FAILS:
        print("\nperturbed: the pre-fix set was CAUGHT (%d checks failed) — the test can go red" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this test does not actually test the fix")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
