#!/usr/bin/env python3
"""Self-test: the free abuse tier (`swg_mech`) is rebuilt when its table is FLUSHED in place, not only when it is deleted.

_ensure_mech_block's steady-state gate accepted a table that existed, matched the stored signature and carried the prerouting
hook. `nft flush table inet swg_mech` keeps the chain and its hook line and deletes the rules, so it passed as converged while
blocking nothing. Measured on msk-main (1.8.7 qualification PART 4, A7): six drop rules flushed in place stayed at zero through
four minutes of reconciles (SMTP / QUIC / torrent port-hint / port-scan meter off), while a DELETED table was rebuilt in 40 s.

  [1] intact table (hook + drop rules), signature current → no reload (steady state stays a no-op)
  [2] the same table FLUSHED (hook kept, rules gone) → rebuilt: one `nft -f` carrying the drop rules
  [3] the table DELETED → rebuilt (the path that always worked — the control)
  [4] a table hooked elsewhere (the pre-v3 forward hook) → rebuilt (the older guard still holds)

Hermetic: swg-noded imported, `run` stubbed as a tiny nft that holds one table's text. Run: python3 tests/mech_flush_selftest.py
     --perturb   restores the hook-only gate and expects RED on [2] ("PERTURB OK", exit 0; exit 1 if nothing went red).
"""
import importlib.machinery, importlib.util, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src, path = open(NODED).read(), NODED
if PERTURB:
    anchor = ' and MECH_HOOK in (have.stdout or "") and " drop" in (have.stdout or ""):'
    if src.count(anchor) != 1:
        print("PERTURB FAILED — the flushed-table gate is not in swg-noded exactly once")
        sys.exit(1)
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src.replace(anchor, ' and MECH_HOOK in (have.stdout or ""):'))

ld = importlib.machinery.SourceFileLoader("noded_mech", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_mech", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = tempfile.mkdtemp(prefix="mechgeo-")

class FakeNft:
    """Holds the text `nft list table inet swg_mech` would print; records every load."""
    def __init__(self):
        self.table, self.loads = None, []
    def run(self, args, input_text=None, timeout=20):
        if args[:5] == ["nft", "list", "table", "inet", "swg_mech"]:
            return types.SimpleNamespace(returncode=0 if self.table is not None else 1, stdout=self.table or "", stderr="")
        if args[:2] == ["nft", "-f"]:
            text = open(args[2]).read()
            self.loads.append(text)
            body = text.split("table inet swg_mech {", 1)[1] if "table inet swg_mech {" in text else ""
            self.table = "table inet swg_mech {" + body.replace(" counter drop", " counter packets 0 bytes 0 drop")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:5] == ["nft", "delete", "table", "inet", "swg_mech"]:
            self.table = None
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

nft = FakeNft()
N.run = nft.run
MECH = {"10.8.0.0/24": ["smtp", "quic", "torrents", "portscan"]}

res = {"changed": 0, "errors": []}
N._ensure_mech_block(MECH, res)
check("[0] first converge loads the table", len(nft.loads) == 1 and " drop" in nft.table and N.MECH_HOOK in nft.table, (nft.loads, res))

res = {"changed": 0, "errors": []}
N._ensure_mech_block(MECH, res)
check("[1] intact + current signature → no reload", len(nft.loads) == 1 and res["changed"] == 0, (len(nft.loads), res))

# `nft flush table`: the chain and its hook line stay, every rule goes (sets keep their declarations, lose their elements)
lines = nft.table.splitlines()
nft.table = "\n".join(l for l in lines if " drop" not in l)
check("[2] (fixture) the flushed table still carries the hook and no drop", N.MECH_HOOK in nft.table and " drop" not in nft.table, nft.table)
res = {"changed": 0, "errors": []}
N._ensure_mech_block(MECH, res)
check("[2] flushed in place → rebuilt", len(nft.loads) == 2 and " drop" in nft.table, (len(nft.loads), nft.table[-300:]))

nft.table = None
res = {"changed": 0, "errors": []}
N._ensure_mech_block(MECH, res)
check("[3] deleted → rebuilt (control)", len(nft.loads) == 3 and " drop" in (nft.table or ""), len(nft.loads))

nft.table = nft.table.replace(N.MECH_HOOK, "hook forward priority filter")
res = {"changed": 0, "errors": []}
N._ensure_mech_block(MECH, res)
check("[4] hooked in the wrong place → rebuilt", len(nft.loads) == 4 and N.MECH_HOOK in nft.table, len(nft.loads))

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — the gate was undone and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
