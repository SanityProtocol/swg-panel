#!/usr/bin/env python3
"""The shadow-set index must be sized per NAME, because a content-filter union is a keyed category too.

`_smart_shadows` (swg-noded) indexes every operand of every keyed category once any shadow pair exists — which is the
case the moment a node with a host-tier block union on one interface has a second audience with other host rules
(another interface's list, a per-person row, arrivals). A union is hundreds of thousands of names. The index used a
Python set per name: +182 MB measured for one 400k-name union, on nodes that have 1 GB. This asserts:

  1. the memory bound: a 100k-name union costs under 20 MB peak (the set-per-name index cost ~47 MB here)
  2. the answer is unchanged: a fixed seeded corpus of mixed configurations (both engines, patterns, per-person rows,
     arrivals) produces exactly the pinned signature digest recorded from the set-based implementation

Run:  python3 tests/shadow_index_memory_selftest.py   (exit 0 = all pass). SWG_NODED= points it at another build.
"""
import importlib.machinery, importlib.util, os, sys, random, json, hashlib, tracemalloc, gc

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
l = importlib.machinery.SourceFileLoader("noded", os.path.abspath(NODED))
sp = importlib.util.spec_from_loader("noded", l); N = importlib.util.module_from_spec(sp); l.exec_module(N)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

print("1. memory is bounded per name")
random.seed(7)
union = sorted({"d%d-%x.example%d.com" % (i, random.getrandbits(24), i % 50) for i in range(100000)} | {"example.com"})
doms = {"blku:host:aaaa": union, "custom_r": ["sh.example.com", "x.example.org"]}
ents = [{"subnet": "10.0.0.0/24", "category": "blku:host:aaaa", "action": "block"},
        {"subnet": "10.0.1.0/24", "category": "custom_r", "action": "exit"}]
for eng in ("dns", "sni_user"):
    N._SHADOW.update(k=None, v={}); gc.collect(); tracemalloc.start()
    out = N._smart_shadows([dict(e) for e in ents], doms, {}, eng)
    peak = tracemalloc.get_traced_memory()[1] / 1e6; tracemalloc.stop()
    check("%s: 100k-name union indexes in < 20 MB" % eng, peak < 20, "%.0f MB" % peak)
    check("%s: …and the claimed name is shadowed into the union" % eng,
          (out.get("domains") or {}) and ["sh.example.com"] in (out.get("domains") or {}).values(), out)

print("2. the answer is the set-based implementation's, exactly")
random.seed(1)
labels = ["example", "google", "mail", "sh", "h2", "ads", "cdn", "com", "org", "ru", "net", "x", "Mail", "EXAMPLE"]
def dom(): return ".".join(random.choice(labels) for _ in range(random.randint(1, 4))) + random.choice(["", ".", ""])
h = hashlib.sha1(); nonempty = 0
for it in range(600):
    cats = ["blku:host:%d" % i for i in range(random.randint(0, 2))] + ["custom_%d" % i for i in range(random.randint(1, 4))]
    es = []
    for c in cats:
        for _ in range(random.randint(1, 2)):
            e = {"subnet": random.choice(["10.0.0.0/24", "10.0.1.0/24", "@arr"]), "category": c,
                 "action": random.choice(["block", "exit", "direct"])}
            if random.random() < 0.3:
                e["src"] = random.choice(["w1", "w2"])
            es.append(e)
    ds = {c: [dom() for _ in range(random.randint(0, 6))] for c in cats if random.random() < 0.9}
    ps = {}
    for kd in ("first", "zone", "any", "starts", "ends", "contains"):
        if random.random() < 0.4:
            ps[kd] = {c: [random.choice(labels + ["", "ma", "om", ".com"]) for _ in range(random.randint(1, 3))]
                      for c in cats if random.random() < 0.5}
    for eng in ("dns", "sni_user"):
        N._SHADOW.update(k=None, v={})
        a = N._smart_shadows([dict(e) for e in es], ds, ps, eng)
        nonempty += bool(a)
        h.update(json.dumps(a, sort_keys=True).encode())
check("the corpus exercises shadows", nonempty > 300, nonempty)
PINNED = "537a3352422819ad"   # recorded from the set-based implementation (HEAD 985aa54) before the rewrite
check("corpus digest matches the set-based implementation", h.hexdigest()[:16] == PINNED, h.hexdigest()[:16])

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
