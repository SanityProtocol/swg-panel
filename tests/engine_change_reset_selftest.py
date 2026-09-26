#!/usr/bin/env python3
"""Self-test — a node that changes routing ENGINE starts the new one from its own learning.

The sets a previous engine filled — addresses Force-DNS resolved, what swg-sni or the in-kernel scanner learned —
carry no expiry the new engine reads. After a mode switch they went on giving their old verdicts: measured on
msk-main (1.8.8 qualification), a node switched from Force-DNS to Kernel SNI kept blocking a site by the address its
resolver had seen, which Kernel SNI cannot do by name — a rule the list calls inert there looked as if it worked.
The first pass on a different engine now runs the reset 'Reset learned IPs' runs, once.

The real functions from swg-noded, with `run` stubbed to record commands and GEO_DIR in a temp dir. No root.

Run: python3 tests/engine_change_reset_selftest.py            (0 = pass)
     --perturb   the change check taken out (the shipped behaviour: never reset) → RED
"""
import os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    a = '    _learned_reset_now(res, "(engine %s → %s)" % (prev, host_engine))\n'
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "")
N = types.ModuleType("n"); N.__dict__.update({"__name__": "n", "__file__": NODED})
exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="engine-reset-")
N.GEO_DIR = TMP
N._ENGINE_STAMP = os.path.join(TMP, ".host-engine")
CALLS = []
class _R: stdout = ""; returncode = 0
def _run(argv, *a, **k):
    CALLS.append(list(argv))
    r = _R()
    if argv[:3] == ["ipset", "list", "-name"]:
        r.stdout = "swgk_custom_1\nswgk_meta\nother_set\n"
    return r
N.run = _run
resets = lambda: [c for c in CALLS if c[:4] == ["nft", "delete", "table", "inet"]]

print("[1] the first pass after an update records the engine and resets nothing")
res = {"changed": 0}
check("no stamp yet → no reset", N._engine_change_reset("dns", res) is False and not resets() and res["changed"] == 0, CALLS)
check("…and the engine is recorded", open(N._ENGINE_STAMP).read() == "dns")

print("\n[2] the same engine again — a restart, an ordinary pass — resets nothing")
del CALLS[:]
check("dns → dns: nothing", N._engine_change_reset("dns", res) is False and not resets(), CALLS)

print("\n[3] a mode switch runs the learned reset ONCE")
del CALLS[:]
r = N._engine_change_reset("sni_kernel", res)
check("dns → sni_kernel: the reset ran", r is True and len(resets()) == 1, CALLS)
check("…it flushed the in-kernel learned sets (swgk_ only)",
      ["ipset", "flush", "swgk_custom_1"] in CALLS and ["ipset", "flush", "swgk_meta"] in CALLS
      and ["ipset", "flush", "other_set"] not in CALLS, CALLS)
check("…and recorded the new engine", open(N._ENGINE_STAMP).read() == "sni_kernel")
del CALLS[:]
check("the next pass on it resets nothing", N._engine_change_reset("sni_kernel", res) is False and not resets(), CALLS)

print("\n[4] an operator reset in the same pass already cleared it — record only")
del CALLS[:]
check("sni_kernel → sni with already=True: no second reset", N._engine_change_reset("sni", res, already=True) is False
      and not resets() and open(N._ENGINE_STAMP).read() == "sni", CALLS)

print("\n[5] wired where the engine is decided, after the operator's resets")
i = src.index('_SMART_MODE["engine"] = host_engine')
w = src[i:i + 900]
check("the reconcile calls it with the operator reset's result",
      "_reset_ran = _apply_routing_reset(" in w and "_engine_change_reset(host_engine, res, already=_reset_ran)" in w
      and w.index("_reset_ran = _apply_routing_reset(") < w.index("_engine_change_reset(host_engine"), w[:400])

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
