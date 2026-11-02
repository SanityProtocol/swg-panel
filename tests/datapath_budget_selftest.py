#!/usr/bin/env python3
"""Self-test — a packet pays only for the rules that can match it (docs/DATAPATH-PLAN.md §8 item 1). DP1: the statistics.

`catcount` and `catany` were written per SUBNET × category: every forwarded packet walked 8·S·C + 4·S rules (1,452 on
msk-main, ~106 µs of a 157 µs packet). They now hold the subnets as one anonymous set and open with a sampling gate,
`numgen random mod N != 0 return`; SWG_INET and SWG_CATK open with the same gate in iptables. N is steered from forwarded
packets a second, lives only in the rule, and multiplies each DELTA a reader takes, never the cumulative value.

  [1] shape (real `_ensure_smart_nft`, nft transaction model): the gate heads both chains at N = 1, one subnet set per
      rule, no rule names one subnet alone; five times the subnets is the same rules, the same text but the set
  [2] the walk: a client packet, a reply, a transit packet — rules read in catcount + catany do not grow with subnets; a
      packet the gate skips reads 1 rule a chain, at any fleet size; a sampled packet still counts in the right counter,
      from every subnet, and a cross-subnet byte with no category counts as "up"
  [3] no empty set: an arrivals-only node (no local subnet) and a plan whose only subnet is not IPv4 render no `{ }`,
      and no batch is refused; a second pass over its own render rebuilds nothing
  [4] numgen refused: no gate, exact, the chains still built and signed apart (a later probe that takes it rebuilds)
  [5] the steer: raise at once, lower only after 12 samples at a quarter or less; the nft gates replaced by handle, the
      iptables gates by `-R 1` — only over a rule that IS the gate; a chain with no gate is never written; a refused
      step is retried on the next sample, and a step is a baseline for every reader (the rate holds, no spike)
  [6] the readers: delta × N, the cumulative values as counted; the gate's own bytes are no traffic and no category
  [7] iptables reconcile: a 1.8.11 chain gets the gate by -I (pairs kept), a rebuild writes it first at N = 1, a chain
      with two gates or one astray is rebuilt

Hermetic. Run: python3 tests/datapath_budget_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     ungated    catcount is built without its gate                                              [1]
     subloop    catcount goes back to one rule per subnet                                       [2]
     emptyset   the subnet set is written even when it is empty                                  [3]
     anygate    the steer writes `-R 1` whatever rule 1 is                                       [5]
     nobase     a step in N is not a baseline (the delta across it is multiplied by the new N)   [5]
     cumscale   sample_inet multiplies the cumulative value instead of the delta                 [6]
     gatebytes  read_inet_bytes counts the gate's bytes as traffic                               [6]
"""
import importlib.machinery, importlib.util, os, re, shutil, subprocess, sys, tempfile
os.environ["SWG_NFT_CLI_ONLY"] = "1"   # the kernel is this test's model, read through run(): nftables via the CLI only

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
sys.path.insert(0, HERE)
from nft_guarded_model import NftError, SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
SECTION = [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


PLANTS = {
    "ungated": ("[1]", '                bat.add("add", "rule", "inet", SMART_NFT_TABLE, "catcount", *_NFT_GATE)', "                pass"),
    "subloop": ("[2]", '            S = "{ " + ", ".join(subnets) + " }"                # collapsed: an interval set refuses a prefix inside another\n'
                       '            for c in count_cats:                                # no `return` → a byte counts in EVERY category it matches',
                '            for S, c in [(S, c) for S in subnets for c in count_cats]:'),
    "emptyset": ("[3]", "        catw = [subnets, count_cats] if subnets and count_cats else []", "        catw = [subnets, count_cats] if count_cats else []"),
    "anygate": ("[5]", "        if g and g != n:", "        if g != n:"),
    "nobase": ("[5]", "    if moved:\n        _stats_rebase()", "    if moved:\n        pass"),
    "cumscale": ("[6]", '        _INET["rate"] = {"up": max(0.0, (cur["up"] - prev["up"]) * k),',
                 '        _INET["rate"] = {"up": max(0.0, (cur["up"] * (cur.get("g") or 1) - prev["up"]) / dt),'),
    "gatebytes": ("[6]", '        if c.group(2).startswith("__"):               # the sampling gate (D1): its bytes are the packets it skipped\n'
                         '            continue\n', ""),
}
TMP = tempfile.mkdtemp(prefix="dp-budget-")
path = NODED
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _sec, old, new = PLANTS[PLANT]
    src = open(NODED, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    path = os.path.join(TMP, "planted-noded.py")
    open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
os.environ["SWG_NODED_STATE"] = TMP
_l = importlib.machinery.SourceFileLoader("swgnoded_budget", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_budget", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = os.path.join(TMP, "geo")
T = N.SMART_NFT_TABLE
CP = subprocess.CompletedProcess


def fleet(ns, nc):
    """ns client subnets, nc categories each routed somewhere: the node's plan."""
    subs = ["10.%d.0.0/24" % (8 + i) for i in range(ns)]
    cats = ["custom_c%d" % j for j in range(nc)]
    ents = [{"subnet": s, "category": c, "action": "exit", "via_iface": "swg_h", "table": 7001} for s in subs for c in cats]
    ents += [{"subnet": s, "category": "all", "action": "direct"} for s in subs]
    return subs, cats, ents


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    K = SmartKernel()
    N.run = K
    N._NUMGEN["ok"] = None
    return K


def npass(K, ents, cats, **kw):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    try:
        N._ensure_smart_nft([dict(e) for e in ents], cats, res, pin=False, queue=False, **kw)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    return res


def build(ns, nc, fill=True, **kw):
    """Two passes: the first makes the sets, a fill between them (what _smart_geo_refresh does), the second counts them."""
    K = fresh()
    subs, cats, ents = fleet(ns, nc)
    r = [npass(K, ents, cats, **kw)]
    if fill:
        for j, c in enumerate(cats):
            K.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
    r.append(npass(K, ents, cats, **kw))
    return K, subs, cats, ents, r


def rules(K, chain):
    return [r["text"] for r in ((K.m.tables.get(T) or {}).get("chains", {}).get(chain) or {}).get("rules", [])]


def walked(K, src, dst, rnd=0):
    """Rules a forwarded packet reads in the two counting chains (both hang on the forward hook)."""
    return sum(K.m.chain_walk(T, c, "awg0", src, dst, rnd=rnd)["walked"] for c in ("catcount", "catany"))


# ── [1] shape ───────────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[1]"
print("\n[1] catcount and catany: one subnet set, a gate on top")
Ks, subs_s, cats_s, _, rs = build(2, 3)
check("two passes, no error, nothing refused", not any(x["errors"] for x in rs) and not Ks.refused, (rs, Ks.refused[:2]))
for c in ("catcount", "catany"):
    check("%s opens with the gate at N = 1" % c, rules(Ks, c)[:1] == [" ".join(N._NFT_GATE)], rules(Ks, c)[:2])
check("no rule names one subnet alone (`ip saddr 10.x` with no set)",
      not any(re.search(r"ip [sd]addr 10\.\d+\.0\.0/24", t) for c in ("catcount", "catany") for t in rules(Ks, c)),
      [t for t in rules(Ks, "catcount")][:3])
check("catcount: 1 + 2·C rules (C = 3, no queue)", len(rules(Ks, "catcount")) == 1 + 2 * 3, len(rules(Ks, "catcount")))
check("catany: 1 + 2·C + 4 rules", len(rules(Ks, "catany")) == 1 + 2 * 3 + 4, len(rules(Ks, "catany")))
Kb, subs_b, _, _, rb = build(10, 3)
check("five times the subnets: the same number of rules in both chains",
      [len(rules(Kb, c)) for c in ("catcount", "catany")] == [len(rules(Ks, c)) for c in ("catcount", "catany")],
      ([len(rules(Kb, c)) for c in ("catcount", "catany")], [len(rules(Ks, c)) for c in ("catcount", "catany")]))
check("…and their set is every subnet, collapsed", all("{ " + ", ".join(N._collapse4(subs_b)) + " }" in t
                                                     for t in rules(Kb, "catcount")[1:]), rules(Kb, "catcount")[1:2])

# ── [2] the walk ────────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[2]"
print("\n[2] rules a packet reads")
pk = {"client→cat": ("10.9.0.5", "198.51.1.7"), "reply": ("198.51.1.7", "10.9.0.5"), "transit": ("192.0.2.1", "203.0.113.9"),
      "client→uncat": ("10.9.0.5", "203.0.113.9")}
for k, (s, d) in pk.items():
    ws, wb = walked(Ks, s, d), walked(Kb, s, d)
    check("%s: the same rules with 2 subnets and with 10 (%d)" % (k, ws), ws == wb, (ws, wb))
for k, (s, d) in pk.items():
    for K_, n in ((Ks, 2), (Kb, 10)):
        for c in ("catcount", "catany"):                       # the gate at a high N, a packet it skips: one rule, whatever the fleet
            K_.m.tables[T]["chains"][c]["rules"][0]["ops"][0] = ("numgen", 256)
        w = walked(K_, s, d, rnd=1)
        check("%s, %d subnets, skipped by the gate at N = 256: 1 rule a chain" % (k, n), w == 2, w)
        for c in ("catcount", "catany"):
            K_.m.tables[T]["chains"][c]["rules"][0]["ops"][0] = ("numgen", 1)
cnt = lambda K_, n: K_.m.tables[T]["counters"].get(n, 0)
b0 = cnt(Kb, "c_custom_c1_up")
for s in ("10.8.0.5", "10.17.0.5"):                            # the first and the last subnet
    Kb.m.chain_walk(T, "catcount", "awg0", s, "198.51.1.7")
check("a sampled packet from every subnet counts in its category", cnt(Kb, "c_custom_c1_up") == b0 + 2, cnt(Kb, "c_custom_c1_up") - b0)
u0, d0 = cnt(Kb, "c_uncat_up"), cnt(Kb, "c_uncat_dn")
Kb.m.chain_walk(T, "catany", "awg0", "10.17.0.5", "10.8.0.9")
check("client to client, no category: counted once, as up", (cnt(Kb, "c_uncat_up") - u0, cnt(Kb, "c_uncat_dn") - d0) == (1, 0),
      (cnt(Kb, "c_uncat_up") - u0, cnt(Kb, "c_uncat_dn") - d0))

# ── [3] no empty set; a second pass ─────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[3]"
print("\n[3] never `{ }`; a pass over its own render")
K3 = fresh()
_, cats3, _ = fleet(0, 2)
arr = {"subnets": ["10.28.0.0/24"], "legs": ["swg_n"],
       "entries": [{"category": c, "action": "exit", "via_iface": "swg_h", "table": 7001} for c in cats3]}
r3 = [npass(K3, [], cats3, arrivals=arr) for _ in range(2)]
for j, c in enumerate(cats3):
    if N._smart_setname(c) in K3.m.tables.get(T, {}).get("sets", {}):
        K3.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
r3.append(npass(K3, [], cats3, arrivals=arr))
check("an arrivals-only node: no error, nothing refused, no `{ }` anywhere",
      not any(x["errors"] for x in r3) and not K3.refused and not any("{ }" in s for s in K3.scripts), (r3, K3.refused[:2]))
check("…and no counting chain (nothing local to count)", not rules(K3, "catcount"), rules(K3, "catcount")[:2])
K6 = fresh()
ent6 = [{"subnet": "fd00:8::/64", "category": "custom_c0", "action": "exit", "via_iface": "swg_h", "table": 7001}]
r6 = [npass(K6, ent6, ["custom_c0"]) for _ in range(2)]
check("a plan whose only subnet is not IPv4: nothing refused, no `{ }`",
      not K6.refused and not any("{ }" in s for s in K6.scripts), (K6.refused[:2], [x["errors"] for x in r6]))
Kp, _, cats_p, ents_p, _ = build(4, 3)
n0 = len(Kp.scripts)
rp = npass(Kp, ents_p, cats_p)
check("a third pass over its own render rebuilds nothing", rp["changed"] == 0 and len(Kp.scripts) == n0 and not rp["errors"],
      (rp, Kp.scripts[n0:][:1]))

# ── [4] numgen refused ──────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[4]"
print("\n[4] a kernel or nft without numgen")
K4 = fresh()
_m4 = K4.m._rule


def _no_numgen(text):
    if "numgen" in text:                                       # as a kernel without nft_numgen answers
        raise NftError("Could not process rule: No such file or directory")
    return _m4(text)


K4.m._rule = _no_numgen
_, cats4, ents4 = fleet(3, 2)
r4 = [npass(K4, ents4, cats4)]
for j, c in enumerate(cats4):
    K4.load_set(T, N._smart_setname(c), ["198.51.%d.0/24" % j])
r4.append(npass(K4, ents4, cats4))
check("asked once; no gate; the chains built and nothing in the smart batch refused",
      N._NUMGEN["ok"] is False and rules(K4, "catcount") and not any("numgen" in t for t in rules(K4, "catcount") + rules(K4, "catany"))
      and not any(x["errors"] for x in r4), (N._NUMGEN, r4, rules(K4, "catcount")[:1]))
probes = [c for c in K4.calls if c[:3] == ["nft", "-c", "-f"]]
sig_off = open(os.path.join(N.GEO_DIR, ".catcount-sig")).read()
K4.m._rule = _m4
N._NUMGEN["ok"] = None
npass(K4, ents4, cats4)
check("…a later process that can take it rebuilds with the gate (the sig tells them apart)",
      rules(K4, "catcount")[:1] == [" ".join(N._NFT_GATE)] and open(os.path.join(N.GEO_DIR, ".catcount-sig")).read() != sig_off,
      rules(K4, "catcount")[:1])

# ── [5] the steer ───────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[5]"
print("\n[5] steering N")
NOW = [1000.0]
N.time = type("T", (), {"time": staticmethod(lambda: NOW[0]), "monotonic": staticmethod(lambda: NOW[0]),
                        "sleep": staticmethod(lambda s: None)})
PK = [0]
N._dev_packets = lambda dev: PK[0] if dev == "eth0" else 0
IPT = {"SWG_INET": None, "SWG_CATK": None}   # chain text as `-S -v` prints it, None = no chain
IPTW = []


def ipt_chain(name, gate_n, extra=True):
    p = "%.11f" % (1 - 1.0 / gate_n) if gate_n else None
    tag = "swg-inet" if name == "SWG_INET" else "swg-catk"
    ln = ["-N " + name]
    if p:
        ln.append('-A %s -m statistic --mode random --probability %s -m comment --comment "%s-up:__gate" -c 900 90000 -j RETURN' % (name, p, tag))
    if extra:
        ln.append('-A %s -i awg2 -o eth0 -m comment --comment "%s-up:awg2" -c 10 1000' % (name, tag))
        ln.append('-A %s -i eth0 -o awg2 -m comment --comment "%s-dn:awg2" -c 20 2000' % (name, tag))
    return "\n".join(ln) + "\n"


Kn, _, cats5, ents5, _ = build(3, 2)
_nft = Kn


def run5(args, input_text=None, timeout=20, env=None):
    a = [str(x) for x in args]
    if a[:1] == ["iptables"]:
        ch = a[a.index("-S") + 1] if "-S" in a else (a[a.index("-R") + 1] if "-R" in a else "")
        if "-R" in a:
            IPTW.append(a)
            n = int(round(1 / (1 - float(a[a.index("--probability") + 1]))))
            IPT[ch] = re.sub(r"--probability \S+", "--probability %.11f" % (1 - 1.0 / n), IPT[ch], count=1)
            return CP(a, 0, "", "")
        if "-S" in a:
            return CP(a, 0 if IPT.get(ch) else 1, IPT.get(ch) or "", "")
        return CP(a, 0, "", "")
    return _nft(args, input_text=input_text, timeout=timeout)


N.run = run5
N._INET.update(t=0.0, cum=None, rate={"up": 0.0, "down": 0.0}, drate={})
N._CATK.update(t=0.0, cum=None, rate={}, on=True)
N._CATS.update(t=0.0, cum={}, rate={})
N._STEER.clear(); N._STEER["pps"] = 0
IPT["SWG_INET"], IPT["SWG_CATK"] = ipt_chain("SWG_INET", 1), ipt_chain("SWG_CATK", None)   # SWG_CATK: a chain with no gate
CFG = {"interfaces": {"awg2": {}}}


def sample(pps):
    """One snapshot's samplers and steer, 5 s later, at `pps` forwarded packets a second."""
    N._LOOP["n"] += 1
    NOW[0] += 5
    PK[0] += int(pps * 2 * 5)
    N.sample_inet(CFG, NOW[0]); N.sample_cats(); N.sample_catk()
    N._stats_steer("eth0")
    return N._STEER.get("n", 1)


gates = lambda: [N._nft_gate_n(Kn.m.render(T), c) for c in ("catcount", "catany")]
sample(0)
n1 = sample(500)
check("below 1000 packets/s: N = 1, nothing written", n1 == 1 and not IPTW and gates() == [1, 1], (n1, IPTW, gates()))
n2 = sample(64000)
check("64,000 packets/s: raised at once to 256", n2 == 256, n2)
check("…the nft gates replaced in place (same handle, first rule)", gates() == [256, 256]
      and all(rules(Kn, c)[0] == "numgen random mod 256 != 0 return" for c in ("catcount", "catany")), (gates(), rules(Kn, "catcount")[:1]))
check("…SWG_INET's gate by `-R SWG_INET 1`", any(w[w.index("-R") + 1:w.index("-R") + 3] == ["SWG_INET", "1"] for w in IPTW)
      and N._ipt_gate_n(IPT["SWG_INET"]) == 256, (IPTW, IPT["SWG_INET"][:200]))
check("…and SWG_CATK, whose rule 1 is a counting rule, is never written", not any("SWG_CATK" in w for w in IPTW)
      and "__gate" not in IPT["SWG_CATK"], IPTW)
check("the step is a baseline for every reader", N._INET["cum"] is None and N._CATK["cum"] is None and N._CATS["cum"] == {},
      (N._INET["cum"], N._CATS["cum"]))
w0 = len(IPTW)
lows = [sample(1500) for _ in range(11)]
check("11 samples at a quarter or less: still 256", set(lows) == {256} and len(IPTW) == w0, (lows, len(IPTW) - w0))
check("…the 12th lowers it (to 8 at 1,500 packets/s)", sample(1500) == 8 and gates() == [8, 8], (N._STEER, gates()))
mid = [sample(1500 * 3) for _ in range(20)]                    # 4,500/s wants 32 > 8: raised at once
check("a rise between lowers is taken at once, and a steady load does not move it", mid[0] == 32 and set(mid) == {32}, mid[:3])
_bad = [True]


def run5_refuse(args, input_text=None, timeout=20, env=None):
    if _bad[0] and [str(x) for x in args][:2] == ["nft", "-f"]:
        return CP(args, 1, "", "Error: refused")
    return run5(args, input_text=input_text, timeout=timeout)


N.run = run5_refuse
sample(64000)
check("a refused nft step leaves the gates where they were", gates() == [32, 32], gates())
_bad[0] = False
sample(64000)
check("…and the next sample retries it by itself", gates() == [256, 256], gates())
N.run = run5

# ── [6] the readers ─────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[6]"
print("\n[6] the readers: delta × N")
sample(64000)                                                  # a baseline after the step above
IPT["SWG_INET"] = IPT["SWG_INET"].replace("-c 10 1000", "-c 30 6000")     # +5,000 bytes up in 5 s, sampled 1 in 256
N._LOOP["n"] += 1
NOW[0] += 5
r = N.sample_inet(CFG, NOW[0])
check("the internet lane: 5,000 sampled bytes in 5 s at N = 256 read 256,000 B/s", abs(r["up"] - 256000.0) < 1e-6, r)
check("…the cumulative value kept as counted (the next delta subtracts it)", N._INET["cum"]["up"] == 6000, N._INET["cum"])
got = N.read_inet_bytes()
check("the gate's own bytes are no traffic (90,000 on it)", got["up"] == 6000 and got["down"] == 2000, got)
IPT["SWG_CATK"] = ipt_chain("SWG_CATK", 256)
N._CATK.update(cum=None)
NOW[0] += 5
N.sample_catk()
IPT["SWG_CATK"] = IPT["SWG_CATK"].replace("-c 10 1000", "-c 11 1100")
NOW[0] += 5
rk = N.sample_catk()
check("Kernel SNI's categories: 100 sampled bytes in 5 s at N = 256 read 5,120 B/s, and no `__gate` category",
      abs(rk.get("awg2", {}).get("up", 0) - 5120.0) < 1e-6 and not any(k.startswith("__") for k in rk), rk)
N._LOOP["n"] += 1
NOW[0] += 5
N.sample_cats()
Kn.m.tables[T]["counters"]["c_custom_c0_up"] = Kn.m.tables[T]["counters"].get("c_custom_c0_up", 0) + 10   # +600 bytes (60 a packet)
N._LOOP["n"] += 1
NOW[0] += 5
rc = N.sample_cats()
check("Top destinations: 600 sampled bytes in 5 s at N = 256 read 30,720 B/s", abs(rc.get("custom_c0", {}).get("up", 0) - 30720.0) < 1e-6, rc)

SECTION[0] = "[5]"                                             # the step's baseline is the steer's job: its plant is [5]'s
lows = [sample(100) for _ in range(13)]
check("quiet again: back to N = 1 after 12 samples", lows[-1] == 1 and N._ipt_gate_n(IPT["SWG_INET"]) == 1, (lows, IPT["SWG_INET"][:160]))
sample(100)
held = N._INET["rate"]["up"]
N._LOOP["n"] += 1                                              # one snapshot by hand: the readers, then 20,000 bytes counted
NOW[0] += 5                                                    # EXACTLY between their read and the step, then the step to 256
PK[0] += 64000 * 10
N.sample_inet(CFG, NOW[0]); N.sample_cats(); N.sample_catk()
held = N._INET["rate"]["up"]
IPT["SWG_INET"] = re.sub(r'(swg-inet-up:awg2" -c \d+ )(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + 20000), IPT["SWG_INET"])
N._stats_steer("eth0")
check("(the step happened)", N._STEER["n"] == 256 and N._ipt_gate_n(IPT["SWG_INET"]) == 256, N._STEER)
N._LOOP["n"] += 1
NOW[0] += 5
r2 = N.sample_inet(CFG, NOW[0])
check("the sample after a step is a baseline: its rate holds, no ×256 of bytes counted exactly (1,024,000 B/s)",
      r2["up"] == held, (r2, held))

# ── [7] iptables reconcile ──────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[7]"
print("\n[7] SWG_INET reconcile and the gate")
CH = {"rules": [], "calls": []}


def run7(args, input_text=None, timeout=20, env=None):
    a = [str(x) for x in args]
    CH["calls"].append(a)
    if a[:1] != ["iptables"]:
        return CP(a, 0, "", "")
    if "-S" in a:
        if a[a.index("-S") + 1] == "FORWARD":
            return CP(a, 0, "-A FORWARD -j SWG_INET\n", "")
        return CP(a, 0, "-N SWG_INET\n" + "".join("-A SWG_INET " + " ".join(('"%s"' % x) if i and r[i - 1] == "--comment" else x
                                                                        for i, x in enumerate(r)) + "\n" for r in CH["rules"]), "")
    if "-nL" in a:
        return CP(a, 0 if "mangle" in a else 1, "", "")
    if "-F" in a:
        CH["rules"] = []
    elif "-A" in a:
        CH["rules"].append(a[a.index("-A") + 2:])
    elif "-I" in a and a[a.index("-I") + 1] == "SWG_INET":
        CH["rules"].insert(int(a[a.index("-I") + 2]) - 1, a[a.index("-I") + 3:])
    return CP(a, 0, "", "")


N.run = run7
N._detect_wan = lambda: "eth0"
pairs = [["-i", "awg2", "-o", "eth0", "-m", "comment", "--comment", "swg-inet-up:awg2"],
         ["-i", "eth0", "-o", "awg2", "-m", "comment", "--comment", "swg-inet-dn:awg2"]]
CH["rules"] = [list(p) for p in pairs]                          # as 1.8.11 left it
N.reconcile_inet_chain(CFG)
check("a 1.8.11 chain: the gate inserted on top, the pairs untouched (no flush)",
      not any("-F" in c for c in CH["calls"]) and CH["rules"][1:] == pairs and "swg-inet-up:__gate" in CH["rules"][0], CH["rules"][:1])
CH["calls"].clear()
N.reconcile_inet_chain(CFG)
check("…and the next pass changes nothing", not any(("-F" in c or "-I" in c or "-A" in c) for c in CH["calls"]), CH["calls"])
CH["rules"] = [list(p) for p in pairs] + [CH["rules"][0]]       # the gate astray: below the pairs
N.reconcile_inet_chain(CFG)
check("a gate that is not the first rule: rebuilt, the gate first at N = 1",
      "swg-inet-up:__gate" in CH["rules"][0] and "0.00000000000" in CH["rules"][0] and CH["rules"][1:] == pairs, CH["rules"])
CH["rules"] = [CH["rules"][0], CH["rules"][0]] + [list(p) for p in pairs]
N.reconcile_inet_chain(CFG)
check("two gates: rebuilt with one", sum("swg-inet-up:__gate" in r for r in CH["rules"]) == 1, CH["rules"])
N.reconcile_inet_chain({"interfaces": {"awg2": {}, "wg1": {}}})
check("a new interface: rebuilt, the gate first", "swg-inet-up:__gate" in CH["rules"][0] and len(CH["rules"]) == 5, CH["rules"])

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    red = [f for f in FAILS if f.split()[0] in sec.split()]
    print("plant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(red), sec)) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
