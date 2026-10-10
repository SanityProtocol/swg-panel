#!/usr/bin/env python3
"""Self-test — a routing pass with nothing to change writes nothing (docs/CPU-PLAN.md, B1: D1 and D2).

  [1] D1, Kernel SNI's teardown on a node not running it: `_ensure_smart_xtstring(active=False)` ran on every routing pass of
      every such node and tore everything down every time — `-D PREROUTING`, `-F` / `-X SWGK`, `iptables -S`, `ipset list`
      twice — because the teardown removed its own stamp, so the next pass read "drift". Now gone is stamped like any other
      state: the first pass tears down, the next ones do not; a teardown that fails (the chain still there) keeps the stamp
      away, so the next pass tries again; a later rebuild (Kernel SNI switched on) still happens.
  [2] D2, a custom rule's raw CIDRs: the set is `interval; auto-merge`, so adjacent ones merge into fewer elements than the
      list has, and a gate on the list's length added them again on every routing pass. Now the gate is the count the last
      add left, read back: added once; again when the list changes or the set lost elements (a reboot); never on a refused
      add's say-so (it is retried); a restart's first pass trusts a set that covers the list.

Reproduced on a real kernel first (swgt, a throwaway netns, nft 1.0.9 / iptables-nft, 2026-10-10): 3 CIDRs merged into
10.99.0.0/23 were added on all 3 passes; the teardown wrote 3 times on all 3 passes. This gate runs the REAL functions
against a model of that kernel state (CI has no netns).

Run: python3 tests/steady_routing_writes_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     d1stamp     the teardown removes its stamp again (it repeats on every routing pass)
     d1blind     the teardown stamps "gone" without looking (a failed teardown is never retried)
     d2length    the old gate on the list's length (a merging list is added on every pass)
     d2refused   a refused add records the read-back count (the list is never loaded)
"""
import importlib.machinery, importlib.util, ipaddress, os, re, subprocess, sys, tempfile, threading

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
    "d1stamp": ('''            if run(["iptables", "-t", "mangle", "-S", CHAIN]).returncode != 0:
                os.makedirs(GEO_DIR, exist_ok=True); open(sigf, "w").write(sig)
            else:
                os.remove(sigf)''', '''            os.remove(sigf)'''),
    "d1blind": ('''            if run(["iptables", "-t", "mangle", "-S", CHAIN]).returncode != 0:''', '''            if True:'''),
    "d2length": ('''        if done and done[0] == sig:
            if have >= done[1]:
                continue                                       # what our last add left is all still there
        elif not done and have >= len(cl):''', '''        if have >= len(cl):'''),
    "d2refused": ('''        if ok:                                                 # a refused add records nothing''',
                  '''        if True:                                                 # a refused add records nothing'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="steadywrites-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("sw_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("sw_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.STATE_DIR = os.path.join(T, "state")
N.GEO_DIR = os.path.join(T, "state", "geo")
N.log = lambda *a, **k: None

# ── the kernel model ───────────────────────────────────────────────────────────────────────────────────────────────────
K = {"chains": set(), "hooked": False, "x_fails": False, "sets": {}, "add_rc": 0}
CALLS = []
WRITES = re.compile(r"^iptables -t mangle -(D|F|X) |^ipset (destroy|create|flush|swap|restore)|^nft (add|delete|flush|-f)")


def cp(rc, out=""):
    return subprocess.CompletedProcess([], rc, out, "")


def model(args, input_text=None, timeout=20, env=None):
    c = " ".join(args)
    CALLS.append(c)
    if c.startswith("iptables -t mangle -C PREROUTING"):
        return cp(0 if K["hooked"] else 1)
    if c.startswith("iptables -t mangle -D PREROUTING"):
        ok = K["hooked"]; K["hooked"] = False
        return cp(0 if ok else 1)
    if c == "iptables -t mangle -F SWGK":
        return cp(0 if "SWGK" in K["chains"] else 1)
    if c == "iptables -t mangle -X SWGK":
        if "SWGK" in K["chains"] and not K["x_fails"]:
            K["chains"].discard("SWGK"); return cp(0)
        return cp(1)
    if c == "iptables -t mangle -S SWGK":
        return cp(0, "-N SWGK\n") if "SWGK" in K["chains"] else cp(1)
    if c == "iptables -t mangle -S":
        return cp(0, "".join("-N %s\n" % ch for ch in sorted(K["chains"])))
    if c == "ipset list -name":
        return cp(0, "")
    m = re.match(r"^nft add element inet \S+ (\S+) \{ (.*) \}$", c)
    if m:
        if K["add_rc"]:
            return cp(K["add_rc"])
        cur = K["sets"].setdefault(m.group(1), [])
        nets = [ipaddress.ip_network(x.strip(), strict=False) for x in m.group(2).split(",")]
        K["sets"][m.group(1)] = list(ipaddress.collapse_addresses(cur + nets))   # interval; auto-merge
        return cp(0)
    m = re.match(r"^nft list set inet \S+ (\S+)$", c)
    if m:
        el = K["sets"].get(m.group(1), [])
        return cp(0, "table inet swg_smart {\n\tset %s {\n\t\telements = { %s }\n\t}\n}\n" % (m.group(1), ", ".join(map(str, el)))
                  if el else "table inet swg_smart {\n\tset %s {\n\t}\n}\n" % m.group(1))
    return cp(0)


N.run = model


def teardown_pass():
    CALLS.clear()
    res = {"changed": 0, "errors": []}
    N._ensure_smart_xtstring([], {}, 0, res, active=False)
    return [c for c in CALLS if WRITES.search(c)], list(CALLS)


# ── [1] D1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] Kernel SNI's teardown on a node not running it")
w1, c1 = teardown_pass()
check("[1] CONTROL: the first pass tears down (a node never seen before: no stamp)",
      any("-D PREROUTING" in c for c in c1) and any("-X SWGK" in c for c in c1), c1)
w2, c2 = teardown_pass()
w3, c3 = teardown_pass()
check("[1] the next passes write nothing — no -D / -F / -X, no destroy", not w2 and not w3, (w2, w3))
check("[1] …and cost two reads (-C PREROUTING, ipset list), not seven", len(c2) <= 2 and len(c3) <= 2, (c2, c3))
# a node that ran Kernel SNI: the chain is there, and -X refuses (still referenced)
for f in (os.listdir(N.GEO_DIR) if os.path.isdir(N.GEO_DIR) else []):
    os.remove(os.path.join(N.GEO_DIR, f))
K.update(chains={"SWGK"}, hooked=True, x_fails=True)
wf, cf = teardown_pass()
wr, cr = teardown_pass()
check("[1] a teardown that fails (SWGK still there) is tried again on the next pass", any("-X SWGK" in c for c in wr), cr)
K.update(x_fails=False)
teardown_pass()
wd, cd = teardown_pass()
check("[1] …and once it succeeds, the passes after it write nothing", not wd and "SWGK" not in K["chains"], (wd, K["chains"]))

# ── [2] D2 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] a custom rule's raw CIDRs")
SN = N._smart_setname("custom_t")
CL = ["10.99.0.0/25", "10.99.0.128/25", "10.99.1.0/24"]          # merge into 10.99.0.0/23: one element for three CIDRs


def cidr_pass(cl=CL, sn=SN):
    CALLS.clear()
    res = {"changed": 0, "errors": []}
    N._smart_load_cidrs({"custom_t": cl}, {sn: len(K["sets"].get(sn, []))}, res)
    return sum(c.startswith("nft add element") for c in CALLS)


a1 = cidr_pass()
check("[2] CONTROL: the first pass adds the list, and the set merges it (3 CIDRs → 1 element)", a1 == 1 and len(K["sets"][SN]) == 1,
      (a1, K["sets"].get(SN)))
a2, a3 = cidr_pass(), cidr_pass()
check("[2] the next passes add nothing (the merged count is what the last add left)", a2 == 0 and a3 == 0, (a2, a3))
K["sets"][SN] = K["sets"][SN] + [ipaddress.ip_network("203.0.113.7/32")]   # dnsmasq adds the domain half's addresses
check("[2] more elements than the add left (dnsmasq's) is normal — nothing added", cidr_pass() == 0)
check("[2] the list changes → added again", cidr_pass(CL + ["10.99.4.0/24"]) == 1)
K["sets"][SN] = []                                                            # a reboot / a flush emptied the set
check("[2] the set lost its elements → added again", cidr_pass(CL + ["10.99.4.0/24"]) == 1)
SN2 = N._smart_setname("custom_r")
K["add_rc"] = 1
N._smart_load_cidrs({"custom_r": CL}, {SN2: 0}, {"changed": 0, "errors": []})
K["add_rc"] = 0
CALLS.clear()
N._smart_load_cidrs({"custom_r": CL}, {SN2: 0}, {"changed": 0, "errors": []})
check("[2] a refused add is retried on the next pass (it recorded nothing)", any(c.startswith("nft add element") for c in CALLS), CALLS)
N._CIDR_LOADED.clear()                                                        # a restart: nothing recorded
CALLS.clear()
N._smart_load_cidrs({"x": ["10.98.0.0/24", "10.98.2.0/24", "10.98.4.0/24"]}, {N._smart_setname("x"): 3}, {"changed": 0, "errors": []})
check("[2] a restart's first pass trusts a set that already covers the list", not CALLS, CALLS)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
