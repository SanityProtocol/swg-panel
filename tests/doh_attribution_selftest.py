#!/usr/bin/env python3
"""Self-test: a device is named "on encrypted DNS" only where its encrypted lookup got PAST a Force-DNS node.

The panel badges every address in a node's `doh_peers`: "the node can't see this client's lookups, so its hostname
rules don't apply". `swg_doh` records into one `doh_seen` set from two tiers — Force-DNS's observe blanket, where the
lookup goes through, and the interface's own DoH / DoT / DoQ block, where it is refused. Measured on msk-main (1.8.7
qualification §R): Hybrid SNI with the block on, the device was listed within a minute while its hostname rule kept
exiting by nixos — a warning that was false twice over (nothing bypassed, and SNI never needed the lookup).

  [1] Force-DNS, no block: every client seen on the observed subnet is named
  [2] Force-DNS with the block on ONE interface: that interface's clients are not named, the other's are
  [3] an SNI node with the block on: nobody is named — and the table is still built with its verdict rules
  [4] a subnet or an address that does not parse is skipped, never raised (this runs before the table is rebuilt)

Run: python3 tests/doh_attribution_selftest.py (0 = pass)
     --perturb   every address in the set is named again   → RED
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
PERTURB = "--perturb" in sys.argv

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    cut = '''        _DOH_SEEN.update(_doh_seen_observed(_parse_doh_seen(have.stdout or ""), observe))'''
    assert src.count(cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    src = src.replace(cut, '''        _DOH_SEEN.update(_parse_doh_seen(have.stdout or ""))''', 1)
os.environ["SWG_NODED_STATE"] = tempfile.mkdtemp(prefix="dohattr-")
path = os.path.join(tempfile.mkdtemp(), "swg-noded")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", loader))
try:
    loader.exec_module(N)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:260]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class R:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


# the element shape as nft renders it back on a live node (msk-main, 2026-09-16)
LIVE = """table inet swg_doh {
	set doh4 {
		type ipv4_addr
		flags interval
		auto-merge
		elements = { 1.0.0.1, 1.1.1.1, 8.8.8.8 }
	}

	set doh_seen {
		type ipv4_addr
		size 65535
		flags dynamic,timeout
		counter
		timeout 15m
		elements = { 10.141.0.10 counter packets 12 bytes 720 timeout 15m expires 14m59s812ms, 10.142.0.50 counter packets 3 bytes 180 timeout 15m expires 13m2s4ms }
	}
}
"""
CALLS = []
def fake_run(argv, input_text=None, timeout=20):
    CALLS.append(list(argv))
    if argv[:4] == ["nft", "list", "table", "inet"]:
        return R(0, LIVE)
    return R(0, "")
N.run = fake_run


def seen(observe, strict):
    del CALLS[:]
    res = {"changed": 0, "errors": []}
    N._ensure_doh_block(observe, strict, res)
    return dict(N._DOH_SEEN), res


print("[1] Force-DNS, no block — the observed clients are named")
s, res = seen(["10.141.0.0/24", "10.142.0.0/24"], [])
check("both clients named, with their attempt counts", s == {"10.141.0.10": 12, "10.142.0.50": 3}, s)

print("\n[2] Force-DNS with the block on wgn2 — its clients refused, so not named")
s, res = seen(["10.141.0.0/24"], ["10.142.0.0/24"])
check("wgn1's client named", s.get("10.141.0.10") == 12, s)
check("⚠️ wgn2's client (blocked) not named", "10.142.0.50" not in s, s)

print("\n[3] an SNI node with the block on — nobody is named, the block still applies")
s, res = seen([], ["10.141.0.0/24", "10.142.0.0/24"])
check("⚠️ nobody is named", s == {}, s)
nft_f = [c for c in CALLS if c[:2] == ["nft", "-f"]]
check("…and the table is still (re)built", bool(nft_f), CALLS)
check("…with no error", not res["errors"], res["errors"])

print("\n[4] unparseable input is skipped, never raised")
s, res = seen(["not-a-subnet", "10.141.0.0/24"], [])
check("a bad subnet is skipped, the good one still names its client", s == {"10.141.0.10": 12}, s)
check("…and nothing was raised into the pass", not res["errors"], res["errors"])
check("a bad address in the render is skipped", N._doh_seen_observed({"999.1.1.1": 1, "10.141.0.10": 2}, ["10.141.0.0/24"]) == {"10.141.0.10": 2})

print()
if PERTURB:
    print("--perturb: %d check(s) RED" % len(FAILS))
    sys.exit(1 if FAILS else 0)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
