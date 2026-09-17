#!/usr/bin/env python3
"""Self-test: when a set Force-DNS's dnsmasq fills is emptied, the node clears dnsmasq's cache so the set fills again.

dnsmasq adds an address to a set only when the answer comes from UPSTREAM; a name answered from its cache fills nothing.
Measured on msk-main (1.8.7 qualification §R): after Reset learned IPs deleted `swg_smart`, ifconfig.me left by msk-main
for ~2.5 minutes while its rule pointed at nixos — every plain lookup answered, from cache, and the set stayed empty until
the name's upstream TTL ran out (commonly hours for other names). A model on dnsmasq 2.91 showed the cached answers
filling nothing and the first lookup after SIGHUP filling the set.

  [1] recreating the table (a reset, or a table deleted from outside) flags the refill; a pass over a standing table does not
  [2] a dual-tier category whose list CHANGED is replaced — flushed — and flags it; an unchanged floor, a floor reloaded
      additively, and a category dnsmasq never fills do not
  [3] the refill sends ONE SIGHUP to the running dnsmasq and clears the flag; nothing is sent when nothing was emptied;
      no dnsmasq running clears the flag without a signal; a failed signal keeps the flag and says so
  [4] reconcile_cascade calls the refill AFTER every engine branch and every set load (so the sets exist before the first
      upstream answer), and before it returns

Run: python3 tests/forcedns_cache_refill_selftest.py (0 = pass)
     --perturb-table    table recreation no longer flags                     → RED on [1]
     --perturb-replace  a dual-tier replace no longer flags                   → RED on [2]
     --perturb-hup      the refill clears the flag without signalling         → RED on [3]
     --perturb-order    the refill runs before the set loads                  → RED on [4]
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
MODE = next((a[len("--perturb-"):] for a in sys.argv[1:] if a.startswith("--perturb-")), "")

src = open(NODED, encoding="utf-8").read()
PLANTS = {
    "table": ('''        _DNSMASQ_SETS_EMPTIED["v"] = True                      # every set dnsmasq filled is gone with it — see _dnsmasq_refill\n''', ""),
    "replace": ('''                if rc == 0 and is_add and content_changed:\n                    _DNSMASQ_SETS_EMPTIED["v"] = True\n''', ""),
    "hup": ('''        if run(["kill", "-HUP", str(pid)]).returncode != 0:''', '''        if False:'''),
}
if MODE == "order":
    call = '''    _dnsmasq_refill(res)                                      # after every set is back: cached names must ask upstream again\n'''
    anchor = '''    domains = dict((smart or {}).get("domains") or {})'''
    assert src.count(call) == 1 and src.count(anchor) == 1, "perturbation anchor missing (order) — this run would FALSE-PASS"
    src = src.replace(call, "", 1).replace(anchor, call + anchor, 1)
elif MODE:
    frm, to = PLANTS[MODE]
    assert src.count(frm) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % MODE
    src = src.replace(frm, to, 1)
STATE = tempfile.mkdtemp(prefix="refill-")
os.environ["SWG_NODED_STATE"] = STATE
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


CALLS = []
TABLE = {"rc": 1, "out": ""}
def fake_run(argv, input_text=None, timeout=20):
    CALLS.append(list(argv))
    if argv[:4] == ["nft", "list", "table", "inet"]:
        return R(TABLE["rc"], TABLE["out"])
    if argv[:2] == ["kill", "-HUP"]:
        return R(HUP["rc"])
    return R(0, "")
N.run = fake_run
HUP = {"rc": 0}
SMART_E = [{"subnet": "10.141.0.0/24", "category": "custom_926d8c7de4", "action": "exit", "table": 7000}]


def flag():
    return N._DNSMASQ_SETS_EMPTIED["v"]


def fresh_loop():
    N._LOOP["n"] = N._LOOP.get("n", 0) + 1                     # the shared table render is per loop
    N._DNSMASQ_SETS_EMPTIED["v"] = False
    del CALLS[:]


print("[1] recreating swg_smart flags the refill")
fresh_loop()
TABLE.update(rc=1, out="")                                     # table absent: a reset deleted it, or someone else did
N._ensure_smart_nft(SMART_E, ["custom_926d8c7de4"], {"changed": 0, "errors": []})
check("the table is created", ["nft", "add", "table", "inet", N.SMART_NFT_TABLE] in CALLS, CALLS[:4])
check("⚠️ …and the refill is flagged", flag())
# the same pass again, over the table it just built: a standing table must not flag
_render = "table inet swg_smart {\n\tset cat_custom_926d8c7de4 {\n\t\ttype ipv4_addr\n\t\tflags interval\n\t\tauto-merge\n\t\telements = { 34.160.111.145 }\n\t}\n\tchain prerouting {\n\t\ttype filter hook prerouting priority mangle; policy accept;\n\t\tip saddr 10.141.0.0/24 ip daddr @cat_custom_926d8c7de4 meta mark set 0x00001b58 return\n\t}\n}\n"
fresh_loop()
TABLE.update(rc=0, out=_render)
N._ensure_smart_nft(SMART_E, ["custom_926d8c7de4"], {"changed": 0, "errors": []})
check("a pass over a standing table does not flag", not flag(), [c for c in CALLS if c[:2] != ["nft", "list"]][:3])

print("\n[2] a dual-tier category's floor replaced after its list changed flags it; nothing else does")
geo = os.path.join(STATE, "geo")
STAMP = {"t": 1_780_000_000}
os.makedirs(geo, exist_ok=True)


def geo_pass(cat, lines, additive, live):
    fp = os.path.join(geo, cat + ".txt")
    open(fp, "w").write("\n".join(lines) + "\n")
    STAMP["t"] += 60
    os.utime(fp, (STAMP["t"], STAMP["t"]))                     # a pull a minute later — the node's change signal is mtime:size
    fresh_loop()
    res = {"changed": 0, "errors": []}
    N._smart_geo_refresh([cat], {N._smart_setname(cat): live}, res, additive=additive)
    return flag(), res


N._nft_set_count = lambda sn: 2
f1, _ = geo_pass("telegram", ["91.108.4.0/22", "149.154.160.0/20"], {"telegram"}, 0)
check("the first load of a dual-tier category replaces (no marker yet) — dnsmasq may already have filled it — and flags", f1)
f2, _ = geo_pass("telegram", ["91.108.4.0/22", "149.154.160.0/20"], {"telegram"}, 2)
check("an unchanged floor does not flag", not f2)
f2b, _ = geo_pass("telegram", ["91.108.4.0/22", "149.154.160.0/20"], {"telegram"}, 1)
check("a floor MISSING with its list unchanged (a reboot) is re-added, not flushed, and does not flag", not f2b)
f3, _ = geo_pass("telegram", ["91.108.4.0/22", "149.154.172.0/22"], {"telegram"}, 5)
check("⚠️ a CHANGED list on a dual-tier category flags (the replace flushed dnsmasq's entries)", f3)
f4, _ = geo_pass("ru", ["5.8.0.0/21"], set(), 0)
f5, _ = geo_pass("ru", ["5.8.0.0/21", "5.16.0.0/14"], set(), 1)
check("a category dnsmasq never fills does not flag, loaded or replaced", not f4 and not f5)

print("\n[3] the refill: one SIGHUP to the running dnsmasq, only when a set was emptied")
N._dnsmasq_running = lambda: 4242
fresh_loop()
res = {"changed": 0, "errors": []}
N._dnsmasq_refill(res)
check("nothing emptied → no signal", not any(c[:1] == ["kill"] for c in CALLS), CALLS)
fresh_loop()
N._DNSMASQ_SETS_EMPTIED["v"] = True
N._dnsmasq_refill(res)
check("⚠️ emptied → exactly one `kill -HUP 4242`", [c for c in CALLS if c[:1] == ["kill"]] == [["kill", "-HUP", "4242"]], CALLS)
check("…and the flag clears", not flag())
N._dnsmasq_refill(res)
check("…so the next pass sends nothing", len([c for c in CALLS if c[:1] == ["kill"]]) == 1, CALLS)
fresh_loop()
N._DNSMASQ_SETS_EMPTIED["v"] = True
N._dnsmasq_running = lambda: 0
N._dnsmasq_refill(res)
check("no dnsmasq running → no signal, flag clears (a starting dnsmasq has an empty cache)",
      not any(c[:1] == ["kill"] for c in CALLS) and not flag(), CALLS)
fresh_loop()
N._DNSMASQ_SETS_EMPTIED["v"] = True
N._dnsmasq_running = lambda: 4242
HUP["rc"] = 1
res = {"changed": 0, "errors": []}
N._dnsmasq_refill(res)
check("a failed signal keeps the flag for the next pass", flag())
check("…and says so", any("cache could not be cleared" in e for e in res["errors"]), res["errors"])
HUP["rc"] = 0

print("\n[4] reconcile_cascade refills after every set is back, and on every path to its end")
body = src[src.index("def reconcile_cascade("):]
body = body[:re.search(r"\n(?:def |class )", body[1:]).start() + 1]
pos = lambda s: [m.start() for m in re.finditer(re.escape(s), body)]
refill = pos("_dnsmasq_refill(res)")
check("called exactly once", len(refill) == 1, refill)
if refill:
    r0 = refill[0]
    for what in ("_ensure_smart_nft(", "_smart_geo_refresh(", "_smart_load_cidrs(", "_ensure_smart_dnsmasq(",
                 "_ensure_sni_router(", "_ensure_smart_xtstring(", "_apply_routing_reset("):
        check("…after every %s" % what, pos(what) and max(pos(what)) < r0, (what, pos(what), r0))
    early = [m.start() for m in re.finditer(r"\n\s+return\b", body) if pos("_ensure_smart_nft(") and min(pos("_ensure_smart_nft(")) < m.start() < r0]
    check("…with no return between the set rebuild and the refill", not early, early)

print()
if MODE:
    print("--perturb-%s: %d check(s) RED" % (MODE, len(FAILS)))
    sys.exit(1 if FAILS else 0)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
