#!/usr/bin/env python3
"""Self-test for swg_reach's per-interface counters when an interface LEAVES device access (docs/SWG-REACH-COUNTER-PLAN.md).

Before the fix a swap re-declared the current interfaces' counters and never deleted the counter of one that had left, so each
left one named, unreferenced counter in `inet swg_reach` until the table was next declared whole (found on the fleet 2026-09-24:
msk-main wg77/79/80, svo-im wg78). Now the swap is unchanged, and AFTER it — when no rule names the leaving counter, so the
value the post-swap read returns is final — that counter is deleted by its own `nft -f` and its count kept in the base.

Loads run against `nft_guarded_model`, which refuses — as nft 1.0.2–1.1.5 measured — deleting a counter a rule still names, or
one that is not there.

  [1] G1 a leave: the swap is HEAD's text (never refused into the declare fallback); then ONE load deletes exactly the leaving
      interface's counter; the kernel keeps `gc` and the plan's counters.
  [2] G2 recorded: what a declare, a swap and a routing-pass rebuild declared is what may be deleted next.
  [3] G3 no wildcard: a counter the node never declared survives.
  [4] G4 the count is exact: drops after the last read are kept, and it reads the same when the interface comes back.
  [5] G4b once, never twice: a leave swap nft 1.0.2 refuses is declared and folded once; a refused delete folds nothing, says so,
      and leaves the counter as before the fix (standing, counted); one refused delete holds back no other; a delete that
      committed but reported failure is never folded (no double when it comes back); a routing-pass rebuild or a fault after a
      refused delete keeps the count; a leaving counter the read did not return is not deleted; a failed read deletes nothing.
  [6] G5 small fleets feel nothing: with no interface leaving, no extra nft call — the same loads and reads as before the fix.
  [7] G6 the swap text is HEAD's for both tables; swg_share records no counter.
  [8] G7 an orphan left before the update is gone after the first load — the upgrade rule, true before the fix too (a new process
      always declares); pinned so it stays true.

Plants — each must turn the run RED; the section named is the one that must catch it (a broad plant may redden others too):
  --perturb-inswap  the delete put INSIDE the swap, before the chains that name it → [1]
  --perturb-record  nothing recorded → [1] [2]
  --perturb-wild    every read counter not in the plan deleted → [3]
  --perturb-nofold  the counter deleted, its count not kept → [4]
  --perturb-double  folded whatever nft answered → [5]
  --perturb-unread  a counter deleted whether or not its count was read → [5]
  --perturb-always  every recorded counter offered for deletion on every swap → [6]
  --perturb-fault   a fault in the delete left to the reconciler's handler → [5]

Hermetic. Run: python3 tests/reach_counter_selftest.py            (0 = pass)
"""
import importlib.machinery, importlib.util, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nft_guarded_model import Kernel  # noqa: E402

NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
ARGS = sys.argv[1:]
FAILS = []
TMP = tempfile.mkdtemp(prefix="reachctr-")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "   " + repr(detail)[:300]))
    if not cond:
        FAILS.append(name)


def load(src_patch=()):
    src = open(NODED, encoding="utf-8").read()
    for a, b in src_patch:
        assert src.count(a) == 1, "plant anchor not found once: %r" % a[:80]
        src = src.replace(a, b)
    path = os.path.join(TMP, "swg-noded-under-test")
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    l = importlib.machinery.SourceFileLoader("swgnoded_rc", path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_rc", l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


# The swap before the fix (ea883fe), verbatim: the fix must leave it exactly this.
def HEAD_SWAP(table, old_guard, guard, counters, gen, old):
    L = ["table inet %s {" % table] + ["  counter %s { }" % c for c in counters] + gen["lines"] + ["}"]
    gone, fresh = [x for x in old_guard if x not in guard], [x for x in guard if x not in old_guard]
    if gone:
        L.append("delete element inet %s guard { %s }" % (table, ", ".join(gone)))
    if fresh:
        L.append("add element inet %s guard { %s }" % (table, ", ".join(fresh)))
    L += ["flush chain inet %s sel" % table, "add rule inet %s sel ip daddr vmap @%s" % (table, gen["map"]),
          "delete map inet %s %s" % (table, old["map"])]
    L += ["delete chain inet %s %s" % (table, c) for c in old["chains"]]
    L += ["delete set inet %s %s" % (table, x) for x in old["sets"]]
    return "\n".join(L) + "\n"


FOLD = '_REACH["base"][n] = _REACH["base"].get(n, 0) + v\n            _REACH["live"].pop(n, None)'
PATCH = []
if "--perturb-record" in ARGS:
    PATCH.append(('"counters": list(gen.get("counters", ()))}', '"counters": []}'))
if "--perturb-wild" in ARGS:
    PATCH.append(("gone = [c for c in old if c not in keep]", "gone = [_reach_counter(n) for n in (now_counts or {}) if _reach_counter(n) not in keep]"))
if "--perturb-nofold" in ARGS:
    PATCH.append((FOLD, '_REACH["live"].pop(n, None)'))
if "--perturb-double" in ARGS:
    PATCH.append(("        if r.returncode == 0:\n            _REACH[\"base\"][n]", "        if True:\n            _REACH[\"base\"][n]"))
if "--perturb-unread" in ARGS:
    PATCH.append(("        if n is None:\n            continue\n", "        n = n or bytes.fromhex(c[1:]).decode(); now.setdefault(n, 0)\n"))
if "--perturb-fault" in ARGS:
    PATCH.append(("        except Exception as e:\n            r = subprocess.CompletedProcess", "        except ZeroDivisionError as e:\n            r = subprocess.CompletedProcess"))
if "--perturb-always" in ARGS:
    PATCH.append(("gone = [c for c in old if c not in keep]", "gone = list(old)"))
N = load(PATCH)
T = "swg_reach"
if "--perturb-inswap" in ARGS:
    _sw = N._gtable_swap
    def _inswap(table, og, g, counters, gen, old):
        L = _sw(table, og, g, counters, gen, old).rstrip("\n").split("\n")
        k = next(i for i, x in enumerate(L) if x.startswith("delete map"))
        dc = ["delete counter inet %s %s" % (table, c) for c in old.get("counters", ()) if c not in counters]
        return "\n".join(L[:k] + dc + L[k:]) + "\n"
    N._gtable_swap = _inswap


def conf(name, addr):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\nListenPort = 51820\n" % addr)
    return p


CFG = {"interfaces": {"wg0": {"conf": conf("wg0", "10.8.0.1/24")}, "wg1": {"conf": conf("wg1", "10.9.0.1/24")},
                      "wg2": {"conf": conf("wg2", "10.10.0.1/24")}, "wg3": {"conf": conf("wg3", "10.11.0.1/24")}}}
N._wdtt_load = lambda: {}
N._csqtt_load = lambda: {}
W = lambda *ifs: {"ifaces": list(ifs), "users": [[["wg0", "10.8.0.5/32"]]], "zones": [{"to": ["10.8.0.6"], "users": [0]}]}
WA, WB = W("wg0", "wg1", "wg2"), W("wg0", "wg2")
C = N._reach_counter
DECLARE = "table inet swg_reach\ndelete table inet swg_reach\ntable inet swg_reach {"
SWAP = "table inet swg_reach {"
DEL1 = "delete counter inet swg_reach %s\n" % C("wg1")
READ = ["nft", "-j", "list", "counters", "table", "inet", T]


def fresh(**kw):
    N._REACH.update(probed=False, installed=False, sig=None, plan=None, status=None, seen={}, loaded=[], base={}, live={}, since=0,
                    skipped={}, stale=None, declared=False, gen="a", names=None)
    k = Kernel(**kw)
    N.run = k
    return k


def go(wire):
    r = {"changed": 0, "errors": []}
    N.reconcile_dev_reach(CFG, wire, r)
    return r


def verify():
    N.dev_reach_verify({"changed": 0, "errors": []})


def drops(k, n, iif, saddr, daddr):
    for _ in range(n):
        assert k.m.packet(T, iif, saddr, daddr)[0] == "drop", (iif, saddr, daddr)


def blocked(n):
    return ((N._REACH["status"] or {}).get("blocked") or {}).get(n)


print("[1] G1 a leave: the swap as before, then its counter deleted on its own")
K = fresh()
go(WA)
check("the first load declares all three counters", K.names(T, "counters") == {"gc", C("wg0"), C("wg1"), C("wg2")}, K.names(T, "counters"))
i0 = len(K.loads)
r = go(WB)
new = K.loads[i0:]
check("⚠️ the leave SWAPPED — not refused into the declare fallback", bool(new) and new[0].startswith(SWAP) and not new[0].startswith(DECLARE)
      and N._REACH["gen"] == "b" and not r["errors"], ([x[:40] for x in new], r))
check("…with no counter delete inside the swap", bool(new) and "delete counter" not in new[0], new[:1])
check("…then ONE load deleting exactly wg1's counter", new[1:] == [DEL1], new[1:])
check("the kernel keeps gc and the plan's counters only", K.names(T, "counters") == {"gc", C("wg0"), C("wg2")}, K.names(T, "counters"))

print("[2] G2 what was declared is what is recorded")
check("after a swap", N._REACH["names"]["counters"] == [C("wg0"), C("wg2")], N._REACH["names"])
K = fresh()
go(WA)
check("after a declare", N._REACH["names"]["counters"] == [C("wg0"), C("wg1"), C("wg2")], N._REACH["names"])
go(W("wg0", "wg1"))                               # a swap: generation b records wg0 + wg1
K.flush_rules(T)
verify()                                          # rebuilt as generation a — it must record its own names, not keep b's
check("after a routing-pass rebuild", K.loads[-1].startswith(DECLARE) and N._REACH["names"]["map"] == "dmap_a"
      and N._REACH["names"]["counters"] == [C("wg0"), C("wg1")], N._REACH["names"])
go(W("wg0"))
check("…and the next leave deletes from it", K.names(T, "counters") == {"gc", C("wg0")} and not K.loads[-2].startswith(DECLARE),
      (K.names(T, "counters"), [x[:30] for x in K.loads[-2:]]))

print("[3] G3 never a wildcard")
K = fresh()
go(WA)
K.m.tables[T]["counters"][C("wg9")] = 9          # a counter named like ours that this node never declared
go(WB)
check("a counter the node never declared survives a leave", K.m.tables[T]["counters"].get(C("wg9")) == 9 and C("wg1") not in K.names(T, "counters"),
      K.m.tables[T]["counters"])

print("[4] G4 the count is exact")
K = fresh()
go(WA)
drops(K, 4, "wg1", "10.9.0.9", "10.9.0.77")
verify()                                          # the routing pass reads 4
drops(K, 2, "wg1", "10.9.0.9", "10.9.0.77")      # two more after that read
c0 = len(K.calls)
go(WB)
check("a leave costs the post-swap read (as before) and one delete — nothing read before the swap",
      [c[:3] for c in K.calls[c0:]] == [["nft", "-f", "-"], READ[:3], ["nft", "-f", "-"]], K.calls[c0:])
check("wg1's six drops are in the base, none in live", N._REACH["base"].get("wg1") == 6 and "wg1" not in N._REACH["live"],
      (N._REACH["base"], N._REACH["live"]))
go(WA)
check("it comes back: kernel counter fresh at 0, the panel reads 6", K.m.tables[T]["counters"].get(C("wg1")) == 0 and blocked("wg1") == 6,
      (K.m.tables[T]["counters"], N._REACH["status"]))
drops(K, 1, "wg1", "10.9.0.9", "10.9.0.77")
verify()
check("…and counts on: 7", blocked("wg1") == 7, N._REACH["status"])
check("the others untouched", blocked("wg0") == 0 and blocked("wg2") == 0, N._REACH["status"])

print("[5] G4b once, never twice")
K = fresh(nft102=True)
go(WA)
drops(K, 3, "wg1", "10.9.0.9", "10.9.0.77")
verify()
conf("wg0", "10.8.0.1/23")                        # the guard grows in place: 1.0.2 refuses the swap, the declare loads
r = go(WB)
conf("wg0", "10.8.0.1/24")
check("a leave swap 1.0.2 refuses is declared in the same pass, no delete after it", K.loads[-1].startswith(DECLARE) and not r["errors"],
      (K.loads[-1][:60], r))
go(WA)
check("…its count folded once: 3 when it comes back", blocked("wg1") == 3, N._REACH["status"])

K = fresh()
go(WA)
drops(K, 5, "wg1", "10.9.0.9", "10.9.0.77")
def _refuse_delete(args, input_text=None, timeout=20):
    """The current kernel K, refusing any delete-counter load (nothing changes, as nft refuses)."""
    if args[:2] == ["nft", "-f"] and (input_text or "").startswith("delete counter"):
        K.calls.append(list(args))
        return subprocess.CompletedProcess(args, 1, "", "Error: refused")
    return K(args, input_text, timeout)
N.run = _refuse_delete
r = go(WB)
N.run = K
check("a refused delete is said, not silent", any("wg1" in e and "stays until the next reload" in e for e in r["errors"]), r)
check("a refused delete folds nothing: the counter stands, counted where it was", C("wg1") in K.names(T, "counters")
      and "wg1" not in N._REACH["base"] and N._REACH["live"].get("wg1") == 5, (K.names(T, "counters"), N._REACH["base"], N._REACH["live"]))
go(WA)
check("…and when it comes back it reads 5, not 10", blocked("wg1") == 5, N._REACH["status"])

K = fresh()
go(WA)
drops(K, 5, "wg1", "10.9.0.9", "10.9.0.77")
drops(K, 2, "wg2", "10.10.0.9", "10.10.0.77")
def _refuse_wg1(args, input_text=None, timeout=20):
    if args[:2] == ["nft", "-f"] and (input_text or "") == "delete counter inet swg_reach %s\n" % C("wg1"):
        K.calls.append(list(args))
        return subprocess.CompletedProcess(args, 1, "", "Error: refused")
    return K(args, input_text, timeout)
N.run = _refuse_wg1
go(W("wg0"))                                      # wg1 AND wg2 leave; wg1's delete is refused
N.run = K
check("one refused delete holds back no other: wg2's counter gone, its 2 kept; wg1's stands",
      C("wg2") not in K.names(T, "counters") and N._REACH["base"].get("wg2") == 2 and C("wg1") in K.names(T, "counters")
      and "wg1" not in N._REACH["base"], (K.names(T, "counters"), N._REACH["base"]))
check("…and the record stays exactly what the load declared", N._REACH["names"]["counters"] == [C("wg0")], N._REACH["names"])

K = fresh()
go(WA)
drops(K, 4, "wg1", "10.9.0.9", "10.9.0.77")
def _commit_then_fail(args, input_text=None, timeout=20):
    r = K(args, input_text, timeout)
    if args[:2] == ["nft", "-f"] and (input_text or "").startswith("delete counter"):
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    return r
N.run = _commit_then_fail
go(WB)
N.run = K
check("a delete that committed but reported failure is not folded (it may as well not have committed)",
      C("wg1") not in K.names(T, "counters") and "wg1" not in N._REACH["base"], (K.names(T, "counters"), N._REACH["base"]))
go(WA)
check("…so when it comes back it reads 0 — the stated cost of a timed-out commit: under, never over", blocked("wg1") == 0,
      N._REACH["status"])

K = fresh(); N.run = _refuse_delete
go(WA)
drops(K, 5, "wg1", "10.9.0.9", "10.9.0.77")
go(WB)
N.run = K
K.flush_rules(T)
verify()                                          # the routing pass finds it emptied and declares — the standing counter folded
go(WA)
check("a routing-pass rebuild after a refused delete keeps the count: 5", blocked("wg1") == 5 and C("wg1") in K.names(T, "counters"),
      N._REACH["status"])

K = fresh()
go(WA)
drops(K, 6, "wg1", "10.9.0.9", "10.9.0.77")
def _crash(args, input_text=None, timeout=20):
    if args[:2] == ["nft", "-f"] and (input_text or "").startswith("delete counter"):
        raise RuntimeError("boom")
    return K(args, input_text, timeout)
N.run = _crash
r = go(WB)
N.run = K
check("a fault at the delete is reported", any("boom" in e for e in r["errors"]), r)
check("…without calling the NEW table stale: it loaded and is enforcing", (N._REACH["status"] or {}).get("ok") is True
      and not (N._REACH["status"] or {}).get("stale") and N._REACH["declared"] is True and N._REACH["gen"] == "b", N._REACH["status"])
go(WA)
check("…and the count survives it: 6", blocked("wg1") == 6, N._REACH["status"])

K = fresh()
go(WA)
drops(K, 2, "wg1", "10.9.0.9", "10.9.0.77")
_rc = N._reach_read_counters
N._reach_read_counters = lambda: {k: v for k, v in (_rc() or {}).items() if k != "wg1"}
go(WB)
N._reach_read_counters = _rc
check("a leaving counter the read did not return is not deleted (its count unknown)", C("wg1") in K.names(T, "counters"), K.names(T, "counters"))

K = fresh()
go(WA)
N._reach_read_counters = lambda: None
c0 = len(K.calls)
go(WB)
N._reach_read_counters = _rc
check("a failed read deletes nothing", sum(1 for c in K.calls[c0:] if c[:2] == ["nft", "-f"]) == 1 and C("wg1") in K.names(T, "counters"),
      K.calls[c0:])

print("[6] G5 no interface leaves → no extra nft call")
K = fresh()
go(WA)
drops(K, 2, "wg0", "10.8.0.9", "10.8.0.77")
go(dict(WA, zones=[{"to": ["10.8.0.7"], "users": [0]}]))        # a device change
go(W("wg0", "wg1", "wg2", "wg3"))                               # an interface added
conf("wg2", "10.10.0.1/23")
go(W("wg0", "wg1", "wg2", "wg3"))                               # a subnet grown
conf("wg2", "10.10.0.1/24")
verify()
loads = [c for c in K.calls if c[:2] == ["nft", "-f"]]
check("four loads — one declare, three swaps — and nothing else", len(K.loads) == 4 and len(loads) == 4 and K.loads[0].startswith(DECLARE)
      and all(x.startswith(SWAP) and not x.startswith(DECLARE) for x in K.loads[1:]), [x[:30] for x in K.loads])
check("four counter reads — one after each swap, one for the routing pass — as before", sum(1 for c in K.calls if c == READ) == 4,
      [c[:4] for c in K.calls])
check("the counts carried as before", blocked("wg0") == 2, N._REACH["status"])

print("[7] G6 the swap text is HEAD's; swg_share records no counter")
g = N._reach_generation(N._reach_plan(CFG, WB)[0], "b")
old = {"map": "dmap_a", "chains": ["n0_a"], "sets": ["f0_a"], "counters": [C("wg0"), C("wg1"), C("wg2")]}
check("a reach leave swap is HEAD's text", N._gtable_swap(T, ["10.9.0.0/24"], [], g["counters"], g, old)
      == HEAD_SWAP(T, ["10.9.0.0/24"], [], g["counters"], g, old))
s = {"lines": [], "map": "m_a", "chains": ["x_a"], "sets": ["s_a"]}
check("swg_share names carry an empty counter list", N._gen_names(s)["counters"] == [], N._gen_names(s))
check("…and its swap is HEAD's text", N._gtable_swap(N.SHARE_NFT_TABLE, ["10.1.0.0/24"], ["10.1.0.0/24"], [], dict(s, map="m_b"), N._gen_names(s))
      == HEAD_SWAP(N.SHARE_NFT_TABLE, ["10.1.0.0/24"], ["10.1.0.0/24"], [], dict(s, map="m_b"), N._gen_names(s)))

print("[8] G7 an orphan left before the update is gone after the first load")
K = fresh()
go(WA)
K.m.tables[T]["counters"][C("wg77")] = 3         # an orphan a pre-fix process left (msk-main carried wg77/79/80)
N._REACH.update(probed=False, installed=False, sig=None, plan=None, status=None, seen={}, loaded=[], base={}, live={}, since=0,
                skipped={}, stale=None, declared=False, gen="a", names=None)   # a restart: a new process, the same kernel
go(WB)
check("declared over, the orphan and wg1's counter gone", K.loads[-1].startswith(DECLARE) and K.names(T, "counters") == {"gc", C("wg0"), C("wg2")},
      K.names(T, "counters"))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
