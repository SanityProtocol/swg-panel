#!/usr/bin/env python3
"""Self-test: the mesh link type — AmneziaWG 2.0 (default), AmneziaWG 3.1, plain WireGuard (docs/AWG-OMIT-AND-MESH-GEN-PLAN.md
Part B).

What is pinned here, and why each matters:
  [0] SMALL FLEETS FEEL NOTHING: with no type set anywhere, reconcile_mesh writes byte-identical nodes (links, creates,
      interface records) to the tree before this feature, over fleets of 2–6 nodes, with and without mesh_awg, at MTU
      1320 and 1420 — same random draws, same order — and no node has a reasons list;
  [1] `wg` is a REAL WireGuard link: `cmd: ["wg"]`, no params on either end, `proto: "wg"` on both link records — never an
      AmneziaWG device without params (the agent would obfuscate it on its own); the re-stage of a lost device reads
      `proto`, and the S4 refit leaves it alone;
  [2] `3.1` where both ends can: one whole 3.1 set on both ends (a HeaderProtectionKey, S1–S4 ≥ 12, S4 inside the MTU's
      room), and awg3_check takes it as it is;
  [3] `3.1` where one end cannot (a 2.0 kernel module) → that link is made at 2.0, and BOTH nodes' reasons name why;
      a mesh MTU that leaves no room for S4 ≥ 12 → 2.0 with the MTU reason;
  [4] the S4 refit on a 3.1 link stays ≥ 12, and where a raised MTU leaves no room for 12 it leaves the link alone (no event,
      no change, every pass) instead of drawing a value header protection refuses;
  [5] the per-node override beats the panel's, and the X end decides; a node whose override the far end overrules is told so.

Hermetic: no network, no panel process. The baseline tree is read with `git show` (SWG_MESH_GEN_BASE, default cba8e22).
Run: python3 tests/mesh_gen_selftest.py            (0 = pass)
     python3 tests/mesh_gen_selftest.py --perturb  (must FAIL: the type setting is ignored)
"""
import copy, importlib.machinery, importlib.util, json, os, random, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
BASE = os.environ.get("SWG_MESH_GEN_BASE") or "cba8e22"

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m


TMP = tempfile.mkdtemp(prefix="meshgen.")
P = load(SERVER, "swgpanel_new")
_base_src = os.path.join(TMP, "swg-panel-server.base")
open(_base_src, "w").write(subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-panel-server"], capture_output=True,
                                          text=True, check=True).stdout)
B = load(_base_src, "swgpanel_base")

if "--perturb" in sys.argv:          # the tree without the setting: every link is 2.0 whatever is chosen
    P.mesh_gen_of = lambda deps, node: "2.0"
    print("(perturbed: mesh_gen_of ignores the setting — this run must FAIL)")

# Deterministic keys in both trees: gen_psk and the HeaderProtectionKey read os.urandom.
_ctr = [0]
def _urandom(n):
    _ctr[0] += 1
    return random.Random(_ctr[0]).randbytes(n)
for M in (P, B):
    M.os.urandom = _urandom


def deps(mtu=1320, panel=None):
    return {"fleet": {"mesh_mtu": mtu}, "panel_settings": dict(panel or {}), "roster_path": os.path.join(TMP, "users.json")}


def gen_snap(module="3.1", tools="3.1"):
    return {"datapath": {"awg": {"gen": {"module": module, "tools": tools, "disk": module}}}}


def fleet(n, mesh_awg=None):
    nodes = {}
    for i in range(n):
        nid = "n%02d" % i
        nodes[nid] = {"name": "node%d" % i}
        if mesh_awg and i == 0:
            nodes[nid]["mesh_awg"] = dict(mesh_awg)
    return nodes


def links(nodes):
    """[(a, b, link record a, link record b, iface rec a, iface rec b, create a, create b)] per linked pair, a < b."""
    out = []
    for a, n in sorted(nodes.items()):
        for b, lr in sorted((n.get("links") or {}).items()):
            if a < b:
                back = nodes[b]["links"][a]
                out.append((a, b, lr, back, n["ifaces"][lr["iface"]], nodes[b]["ifaces"][back["iface"]],
                            (n.get("create") or {}).get(lr["iface"]), (nodes[b].get("create") or {}).get(back["iface"])))
    return out


def run(M, nodes, d, snaps=None, seed=1):
    random.seed(seed); _ctr[0] = 0
    M._MESH_IDLE.clear()
    M.reconcile_mesh(nodes, snaps or {}, d)
    return nodes


# ── [0] byte-identical with no type set ─────────────────────────────────────────────────────────────────────────────────
print("[0] no type set ⇒ the same nodes as the tree before (%s)" % BASE)
same, tried = True, 0
for n in (2, 3, 4, 6):
    for mtu in (1320, 1420):
        for mawg in (None, {"Jc": "3", "S1": "20", "S4": "90"}):
            for panel in ({}, {"mesh_awg": {"Jc": "5", "Jmin": "50", "Jmax": "80"}}):
                a = run(P, fleet(n, mawg), deps(mtu, panel), seed=n * 7 + mtu)
                b = run(B, fleet(n, mawg), deps(mtu, panel), seed=n * 7 + mtu)
                tried += 1
                if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                    same = False
                    print("    differs: n=%d mtu=%d mesh_awg=%s panel=%s" % (n, mtu, mawg, panel))
check("%d fleets: nodes byte-identical to %s" % (tried, BASE), same)
_r = run(P, fleet(4), deps())
check("…and no node has a reasons list", all(P.mesh_gen_reasons(deps(), _r, {}, nid) == [] for nid in _r))
check("…and the 2.0 default is 2.0 (control: a 2.0 link reads as one)",
      all(P.mesh_link_gen(_r[a], la) == "2.0" for a, b, la, *_ in links(_r)))

# ── [1] wg ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] wg is a real WireGuard link")
d = deps(1420, {"mesh_awg_gen": "wg"})
w = run(P, fleet(3), d)
L = links(w)
check("every pair linked (3)", len(L) == 3, len(L))
check("create cmd is [\"wg\"] on both ends", all(ca["cmd"] == ["wg"] and cb["cmd"] == ["wg"] for *_, ca, cb in L),
      [(ca or {}).get("cmd") for *_, ca, cb in L])
check("no awg_params on either end", all("awg_params" not in ia and "awg_params" not in ib for _, _, _, _, ia, ib, _, _ in L))
check("proto \"wg\" on both link records", all(la.get("proto") == "wg" and lb.get("proto") == "wg" for _, _, la, lb, *_ in L))
check("mesh_link_gen reads wg", all(P.mesh_link_gen(w[a], la) == "wg" for a, b, la, *_ in L))
# the node reports its links, then loses one device: the re-stage must rebuild it as wg
for nid in w:
    w[nid].pop("create", None)
snaps = {nid: {"interfaces": {lr["iface"]: {} for lr in n["links"].values()}} for nid, n in w.items()}
lost = L[0][2]["iface"]
snaps[L[0][0]]["interfaces"].pop(lost)
P.reconcile_mesh(w, snaps, d)
rs = (w[L[0][0]].get("create") or {}).get(lost) or {}
check("a lost wg link is re-staged with cmd [\"wg\"]", rs.get("cmd") == ["wg"], rs)
check("…and its record gains no params", "awg_params" not in w[L[0][0]]["ifaces"][lost])
before = json.dumps(w, sort_keys=True)
w[L[0][0]].pop("create", None); snaps[L[0][0]]["interfaces"][lost] = {}
before = json.dumps(w, sort_keys=True)
P.reconcile_mesh(w, snaps, deps(1440, {"mesh_awg_gen": "wg"}))   # room 0: an awg link would be refitted
check("the S4 refit leaves a wg link alone (MTU raised)", all("awg_params" not in ia for _, _, _, _, ia, ib, _, _ in links(w)))

# ── [2] 3.1 where both ends can ─────────────────────────────────────────────────────────────────────────────────────────
print("[2] 3.1 where both ends can")
for mtu in (1320, 1420, 1428):
    d = deps(mtu, {"mesh_awg_gen": "3.1"})
    t = run(P, fleet(3), d, {f"n{i:02d}": gen_snap() for i in range(3)})
    L = links(t)
    room = P.mesh_s4_room(mtu)
    ok = True
    for a, b, la, lb, ia, ib, ca, cb in L:
        pa, pb = ia.get("awg_params") or {}, ib.get("awg_params") or {}
        if not (pa == pb and pa.get("HeaderProtectionKey") and all(int(pa[k]) >= 12 for k in ("S1", "S2", "S3", "S4"))
                and int(pa["S4"]) <= room and ca["cmd"] == ["awg"] and "proto" not in la):
            ok = False; print("    bad link", mtu, pa)
        if P.awg3_check(pa)[1] is not None:
            ok = False; print("    awg3_check refuses", P.awg3_check(pa)[1])
    check("MTU %d: whole, identical 3.1 sets, S1–S4 ≥ 12, S4 ≤ %d, awg3_check passes" % (mtu, room), ok and len(L) == 3)
    check("MTU %d: no reasons" % mtu, all(P.mesh_gen_reasons(d, t, {f"n{i:02d}": gen_snap() for i in range(3)}, n) == [] for n in t))
_hpk = {(ia.get("awg_params") or {}).get("HeaderProtectionKey") for _, _, _, _, ia, ib, _, _ in L}
check("a fresh HeaderProtectionKey per link", len(_hpk) == len(L), len(_hpk))
_d3 = deps(1320, {"mesh_awg_gen": "3.1", "interface_defaults": {"awg3_params": {"ContentPaddingAddition": "20-40"}}})
t = run(P, fleet(2), _d3, {"n00": gen_snap(), "n01": gen_snap()})
check("3.x values come from the interface defaults (awg3_defaults)",
      links(t)[0][4]["awg_params"].get("ContentPaddingAddition") == "20-40", links(t)[0][4]["awg_params"])

# ── [3] fallbacks ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] a pair that cannot run 3.1 is made at 2.0, and says why")
d = deps(1320, {"mesh_awg_gen": "3.1"})
sn = {"n00": gen_snap(), "n01": gen_snap(module="2.0", tools="2.0"), "n02": gen_snap()}
t = run(P, fleet(3), d, sn)
gens = {(a, b): P.mesh_link_gen(t[a], la) for a, b, la, *_ in links(t)}
check("n00↔n02 at 3.1, both pairs with n01 at 2.0", gens == {("n00", "n01"): "2.0", ("n00", "n02"): "3.1", ("n01", "n02"): "2.0"}, gens)
r1 = P.mesh_gen_reasons(d, t, sn, "n01")
check("n01's card names both links, with its module as the reason",
      len(r1) == 2 and all("kernel module is 2.0" in x["msg"]["error"] for x in r1), r1)
r0 = P.mesh_gen_reasons(d, t, sn, "n00")
check("n00's card names its link to n01 only", [x["peer"] for x in r0] == ["node1"], r0)
check("an older node (no generation report) falls back too",
      P.mesh_31_refusal(d, t, {"n00": gen_snap(), "n01": {}}, "n00", "n01", 1320) is not None)
d = deps(1430, {"mesh_awg_gen": "3.1"})
t = run(P, fleet(2), d, {"n00": gen_snap(), "n01": gen_snap()})
r = P.mesh_gen_reasons(d, t, {"n00": gen_snap(), "n01": gen_snap()}, "n00")
check("MTU 1430 (S4 room 10) → 2.0, and the MTU is the reason",
      P.mesh_link_gen(t["n00"], t["n00"]["links"]["n01"]) == "2.0" and len(r) == 1 and "1428" in r[0]["msg"]["error"], r)

# ── [4] the refit on a 3.1 link ─────────────────────────────────────────────────────────────────────────────────────────
print("[4] the S4 refit keeps a 3.1 link ≥ 12")
d = deps(1320, {"mesh_awg_gen": "3.1"})
sn = {"n00": gen_snap(), "n01": gen_snap()}
t = run(P, fleet(2), d, sn)
for nid in t:
    t[nid].pop("create", None)
rsn = {nid: {"interfaces": {lr["iface"]: {} for lr in n["links"].values()}} for nid, n in t.items()}
ia, ib = links(t)[0][4], links(t)[0][5]
ia["awg_params"]["S4"] = ib["awg_params"]["S4"] = "60"
random.seed(5)
P.reconcile_mesh(t, rsn, deps(1425, {"mesh_awg_gen": "3.1"}))          # room 15
check("MTU 1425: refitted to 12–15 on both ends", ia["awg_params"]["S4"] == ib["awg_params"]["S4"]
      and 12 <= int(ia["awg_params"]["S4"]) <= 15, (ia["awg_params"]["S4"], ib["awg_params"]["S4"]))
low = P.mesh_s4_draw(1426, 12)
check("a draw with floor 12 in a room of 14 is 12–14", 12 <= low <= 14, low)
ia["awg_params"]["S4"] = ib["awg_params"]["S4"] = "60"
ev = os.path.join(TMP, "events.jsonl"); n_ev = len(open(ev).read().splitlines()) if os.path.exists(ev) else 0
P.reconcile_mesh(t, rsn, deps(1432, {"mesh_awg_gen": "3.1"}))          # room 8 < 12 (this pass records the new MTU)
snap0 = json.dumps(t, sort_keys=True)
for _ in range(2):
    P.reconcile_mesh(t, rsn, deps(1432, {"mesh_awg_gen": "3.1"}))
check("MTU 1432 (room 8): the 3.1 link keeps S4 60 on both ends, and later passes change nothing",
      ia["awg_params"]["S4"] == ib["awg_params"]["S4"] == "60" and json.dumps(t, sort_keys=True) == snap0, ia["awg_params"]["S4"])
check("…and no refit event", (len(open(ev).read().splitlines()) if os.path.exists(ev) else 0) == n_ev)
t2 = run(P, fleet(2), deps(1320), {})
a2, b2 = links(t2)[0][4], links(t2)[0][5]
a2["awg_params"]["S4"] = b2["awg_params"]["S4"] = 60
for nid in t2:
    t2[nid].pop("create", None)
P.reconcile_mesh(t2, {nid: {"interfaces": {lr["iface"]: {} for lr in n["links"].values()}} for nid, n in t2.items()}, deps(1432))
check("control: a 2.0 link at the same MTU IS refitted (to ≤ 8)", int(a2["awg_params"]["S4"]) <= 8, a2["awg_params"]["S4"])

# ── [5] per-node override ───────────────────────────────────────────────────────────────────────────────────────────────
print("[5] the per-node override, decided by the X end")
f = fleet(3)
f["n00"]["mesh_awg_gen"] = "wg"
d = deps(1320, {"mesh_awg_gen": "3.1"})
sn = {k: gen_snap() for k in f}
t = run(P, f, d, sn)
gens = {(a, b): P.mesh_link_gen(t[a], la) for a, b, la, *_ in links(t)}
check("n00's override (wg) decides its links; n01↔n02 take the panel's 3.1",
      gens == {("n00", "n01"): "wg", ("n00", "n02"): "wg", ("n01", "n02"): "3.1"}, gens)
t["n02"]["mesh_awg_gen"] = "2.0"
r = P.mesh_gen_reasons(d, t, sn, "n02")
check("n02 (override 2.0) is told which links the other end decides",
      sorted(x["peer"] for x in r) == ["node0", "node1"] and all("other end" in x["msg"]["error"] for x in r), r)
check("mesh_gen_of: node override > panel > 2.0",
      (P.mesh_gen_of(d, {"mesh_awg_gen": "wg"}), P.mesh_gen_of(d, {}), P.mesh_gen_of(deps(), {}),
       P.mesh_gen_of(deps(1320, {"mesh_awg_gen": "bogus"}), {"mesh_awg_gen": "x"})) == ("wg", "3.1", "2.0", "2.0"))

print()
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("All checks passed.")
