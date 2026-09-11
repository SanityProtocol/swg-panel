#!/usr/bin/env python3
"""Self-test: every plan key the panel BUILDS must actually leave on the wire.

`cascade_plan` fills a per-node slot — forward / exit / devexit / smart / allowed / domains / cidrs /
patterns — and the sync reply picks those apart by hand. `devexit` was built, consumed by the node, and
carried by NOBODY: the whole device-exit datapath was unreachable end to end for three commits.

It survived three review passes for one reason: every other gate feeds `reconcile_cascade` a hand-built
plan dict. Each SIDE was tested against a fixture and the SEAM between them against nothing. This is the
seam.

Structural, from the source, because that is the only place the answer lives — the reply is assembled
inside a request handler that cannot be called without a live server.

Run: python3 tests/cascade_wire_selftest.py (0 = pass)
     --perturb  drops `devexit` from the reply, the way it shipped, and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(PANEL, encoding="utf-8").read()
if PERTURB:
    cut = '"devexit": my_plan.get("devexit") or []},   # Phase 2'
    assert cut in src, "perturbation anchor missing — this run would FALSE-PASS"
    src = src.replace(cut, '},   # Phase 2', 1)

# 1) what does cascade_plan BUILD? read the slot() literal, not a guess.
m = re.search(r'return plans\.setdefault\(nid, \{(.*?)\}\)', src, re.S)
assert m, "slot() literal not found"
built = set(re.findall(r'"([a-z_]+)":', m.group(1)))
public = {k for k in built if not k.startswith("_")}
check("slot()'s public keys were read", len(public) >= 6, sorted(public))

# 2) which of them does the reply actually READ? `my_plan.get("x")` / `my_plan["x"]`
carried = set(re.findall(r'my_plan(?:\.get\(|\[)"([a-z_]+)"', src))
check("the reply's plan reads were found", len(carried) >= 4, sorted(carried))

missing = public - carried
check("every plan key the panel builds is read on the way out",
      not missing, "built and never carried: " + str(sorted(missing)))
check("devexit specifically reaches the wire", "devexit" in carried)

# 3) …and the NODE reads the same key off the cascade payload, so the two ends agree on the name.
nsrc = open(NODED, encoding="utf-8").read()
node_reads = set(re.findall(r'plan\.get\("([a-z_]+)"\)', nsrc)) | set(re.findall(r'cascade or \{\}\)\.get\("([a-z_]+)"', nsrc))
check("the node reads `devexit` off the plan it is sent", "devexit" in node_reads, sorted(node_reads))
# the cascade payload the panel sends is exactly {forward, exit, devexit}; the node must not expect more
_cas = re.search(r'"cascade": \{(.*?)\},\s*#', src, re.S)
sent = set(re.findall(r'"([a-z_]+)":', _cas.group(1))) if _cas else set()
check("the node expects nothing the cascade payload does not send",
      not ({"forward", "exit", "devexit"} - sent), sorted(sent))

if PERTURB:
    if FAILS:
        print("\nperturbed: a plan key built and never carried was CAUGHT (%d red) — the datapath it feeds "
              "would be unreachable end to end" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually test the seam")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
