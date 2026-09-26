#!/usr/bin/env python3
"""Self-test — a Kernel SNI chain rebuild is ONE transaction, and the chain stays hooked through it.

The rebuild used to unhook SWGK from PREROUTING, add its rules with one `iptables` process each, and hook it again
last. Measured on msk-main (1.8.8 qualification, 10 240 rules): 211 s, all of it unhooked — a destination Kernel SNI
had learned for an exit left DIRECTLY for three and a half minutes after every rule edit, while one vCPU spawned ten
thousand processes. Now `iptables-restore --noflush` declares the chain and writes every rule in one transaction (a
declared chain is emptied and refilled atomically, referenced or not — measured on iptables-nft 1.8.10); the hook is
added in the same transaction only if it was missing. A refused restore falls back to the rule-by-rule path and says so.

The real `_ensure_smart_xtstring` runs against a recording `run` stub. No root, no iptables.

Run: python3 tests/ksni_atomic_rebuild_selftest.py            (0 = pass)
     --perturb   the transaction taken out (the shipped rule-by-rule rebuild) → RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _iptrestore import restore_to_calls  # noqa: E402
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_SPLIT = "--perturb-split" in sys.argv

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    a = "    if entries or arr_ents:\n        # ⚠️ ONE TRANSACTION, THE HOOK LEFT IN PLACE."
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    if False:\n        # ⚠️ ONE TRANSACTION, THE HOOK LEFT IN PLACE.")
if PERTURB_SPLIT:                                        # one flat chain again (every packet walks every source's rules)
    a = "    rules, subs = _xts_split(rules, CHAIN)"
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    subs = []")
path = os.path.join(tempfile.mkdtemp(prefix="ksni-atomic-"), "noded.py")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded_atomic", path)
spec = importlib.util.spec_from_loader("swgnoded_atomic", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err

def build(hooked, restore_rc=0):
    calls, texts = [], []
    def run(cmd, input_text=None, timeout=20, **kw):
        calls.append(list(cmd))
        if cmd[:1] == ["iptables-restore"]:
            texts.append(input_text)
            return R(restore_rc, "", "iptables-restore: line 3 failed" if restore_rc else "")
        if cmd[:1] == ["iptables"] and "-C" in cmd:
            return R(0 if hooked else 1)
        if cmd[:2] == ["ipset", "list"]:
            return R(0, "")
        return R(0)
    N.run = run
    N._kernel_sni_ok = lambda: True
    N.GEO_DIR = tempfile.mkdtemp(prefix="geo-")          # no signature on disk → this pass rebuilds
    res = {"errors": [], "changed": 0}
    N._ensure_smart_xtstring([{"subnet": "10.15.0.0/24", "category": "custom_a", "table": "7000"},
                              {"subnet": "10.16.0.0/24", "category": "custom_b", "table": "7001"}],
                             {"custom_a": ["alpha.example", "beta.example"], "custom_b": ["gamma example"]},
                             0x9999, res, ttl=3600)
    return calls, texts, res

def unhooks(calls):
    return [c for c in calls if c[:1] == ["iptables"] and "-D" in c and "PREROUTING" in c]

print("[1] a chain that is hooked is refilled in one transaction and never unhooked")
calls, texts, res = build(hooked=True)
check("exactly one iptables-restore", len(texts) == 1, calls[:6])
check("…the chain never leaves PREROUTING (no -D, no -F/-X of SWGK)",
      not unhooks(calls) and not [c for c in calls if c[:1] == ["iptables"] and ("-F" in c or "-X" in c)], calls)
check("…not one rule added by its own process", not [c for c in calls if c[:1] == ["iptables"] and "-A" in c], calls)
tx = texts[0] if texts else ""
got = restore_to_calls(tx)
check("…it declares SWGK (--noflush empties and refills it) and holds every rule",
      ["iptables", "-t", "mangle", "-F", "SWGK"] in got
      and sum(1 for c in got if "-A" in c and any(str(x).startswith("SWGK") for x in c)) >= 7, tx[:400])
check("…the window rule first, the operand with a space quoted back into ONE argument",
      next((c for c in got if "-A" in c), [])[-1:] == ["RETURN"] and any("gamma example" in c for c in got), got[:3])
check("…and no second hook", not any("PREROUTING" in c for c in got), tx[-200:])

print("\n[2] a chain that is not hooked yet is hooked in the same transaction")
calls, texts, res = build(hooked=False)
got = restore_to_calls(texts[0] if texts else "")
check("the hook is the transaction's last rule", bool(got) and got[-1][-2:] == ["-j", "SWGK"] and "PREROUTING" in got[-1], got[-2:])

print("\n[3] a refused transaction falls back to the rule-by-rule path, and says so")
calls, texts, res = build(hooked=True, restore_rc=1)
check("the fallback adds the rules one by one", sum(1 for c in calls if c[:1] == ["iptables"] and "-A" in c) >= 7, calls[-3:])
check("…and the refusal is reported", any("one-transaction rebuild refused" in e for e in res["errors"]), res["errors"])

print("\n[4] SWGK dispatches: a packet walks its own source's rules, not every source's")
calls, texts, res = build(hooked=True)
got = [c[3:] for c in restore_to_calls(texts[0] if texts else "") if "-A" in c]
head = [r for r in got if r[1] == "SWGK"]
subs = sorted({r[1] for r in got if r[1].startswith("SWGK_")})
check("SWGK holds the window rule and one jump per source — no scan of its own",
      len(head) == 1 + len(subs) and not any("--string" in r for r in head) and len(subs) == 2, head)
check("each source's chain holds that source's rules alone",
      all(len({r[r.index("-s") + 1] for r in got if r[1] == c and "-s" in r}) == 1 for c in subs), got[:4])
for c in subs:
    src_ = next(r[r.index("-s") + 1] for r in got if r[1] == c and "-s" in r)
    walked = len(head) + sum(1 for r in got if r[1] == c)
    check("a packet from %s walks %d rules, not all %d" % (src_, walked, len(got)), walked < len(got), walked)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_SPLIT) else ""))
sys.exit(2 if (PERTURB or PERTURB_SPLIT) else 0)
