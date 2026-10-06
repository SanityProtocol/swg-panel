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
_SRV = SERVER
if "--perturb-partial" in sys.argv:   # the tree before the partial-template fix: the elif never runs
    _src = open(SERVER).read()
    _anchor = "    elif _tv and any(k not in _tv for k in AWG_FIELDS if k not in AWG3_FIELDS):\n"
    assert _src.count(_anchor) == 1, "plant anchor missing — this run would measure nothing"
    _SRV = os.path.join(TMP, "swg-panel-server.perturbed"); open(_SRV, "w").write(_src.replace(_anchor, "    elif False:\n"))
    print("(perturbed: a partial mesh template is not filled — [8] must FAIL)")
P = load(_SRV, "swgpanel_new")
_base_src = os.path.join(TMP, "swg-panel-server.base")
open(_base_src, "w").write(subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-panel-server"], capture_output=True,
                                          text=True, check=True).stdout)
B = load(_base_src, "swgpanel_base")

if "--perturb" in sys.argv:          # the tree without the setting: every link is 2.0 whatever is chosen
    P.mesh_gen_for = lambda deps, nodes, a, b: "2.0"
    print("(perturbed: mesh_gen_for ignores every type setting — this run must FAIL)")

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
FULLT = {k: str(v) for k, v in P.gen_awg_params().items()}                          # a full template ("Generate a set")
for n in (2, 3, 4, 6):
    for mtu in (1320, 1420):
        for mawg in (None, dict(FULLT, S4="90")):
            for panel in ({}, {"mesh_awg": dict(FULLT, Jc="5")}):
                a = run(P, fleet(n, mawg), deps(mtu, panel), seed=n * 7 + mtu)
                b = run(B, fleet(n, mawg), deps(mtu, panel), seed=n * 7 + mtu)
                tried += 1
                if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                    same = False
                    print("    differs: n=%d mtu=%d mesh_awg=%s panel=%s" % (n, mtu, mawg, panel))
check("%d fleets (empty or full mesh templates): nodes byte-identical to %s" % (tried, BASE), same)
_pl = [run(P, fleet(3, {"Jc": "3", "S1": "20", "S4": "90"}), deps(1320), seed=3), run(B, fleet(3, {"Jc": "3", "S1": "20", "S4": "90"}), deps(1320), seed=3)]
check("plant: a PARTIAL node template is the one deliberate difference (the fix in [8])",
      json.dumps(_pl[0], sort_keys=True) != json.dumps(_pl[1], sort_keys=True))
_r = run(P, fleet(4), deps())
check("…and no node has a reasons list", all(P.mesh_gen_reasons(deps(), _r, {}, nid) == [] for nid in _r))
check("…and the reasons are not even computed for it (mesh_types_in_play is false)", not P.mesh_types_in_play(deps(), _r))
check("…but are once anything is set: a panel type, a link's own type, a \"-\" in either template",
      P.mesh_types_in_play(deps(1320, {"mesh_awg_gen": "wg"}), _r)
      and P.mesh_types_in_play(deps(1320, {"mesh_awg": {"I1": "-"}}), _r)
      and P.mesh_types_in_play(deps(), {**_r, "zz": {"mesh_link_gen": {"zy": "3.1"}}})
      and P.mesh_types_in_play(deps(), {**_r, "zz": {"mesh_awg": {"S3": "-"}}}))
check("…and a malformed panel mesh_awg (a list) is no setting, never an exception in the poll",
      P.mesh_types_in_play(deps(1320, {"mesh_awg": ["-"]}), _r) is False)
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

# ── [5] a per-LINK type (plan §8 round 12 — a type belongs to the pair, not to a node) ─────────────────────────────────────
print("[5] a link's own type beats the fleet's default; a node has no type of its own")
f = fleet(3)
f["n00"]["mesh_link_gen"] = {"n02": "wg"}          # stored on the pair's anchor (smaller id)
f["n01"]["mesh_awg_gen"] = "wg"                    # a per-node type from an unreleased build: never read
d = deps(1320, {"mesh_awg_gen": "3.1"})
sn = {k: gen_snap() for k in f}
t = run(P, f, d, sn)
gens = {(a, b): P.mesh_link_gen(t[a], la) for a, b, la, *_ in links(t)}
check("n00↔n02 is WG (its own choice); n00↔n01 and n01↔n02 take the fleet's 3.1 (n01's per-node type ignored)",
      gens == {("n00", "n01"): "3.1", ("n00", "n02"): "wg", ("n01", "n02"): "3.1"}, gens)
check("mesh_link_override reads the pair from either end; mesh_gen_for falls back to the fleet's default",
      (P.mesh_link_override(t, "n02", "n00"), P.mesh_link_override(t, "n00", "n02"), P.mesh_gen_for(d, t, "n01", "n02"),
       P.mesh_gen_for(deps(), t, "n01", "n02")) == ("wg", "wg", "3.1", "2.0"))
check("mesh_gen_of is the fleet's default only", (P.mesh_gen_of(d, {"mesh_awg_gen": "wg"}), P.mesh_gen_of(deps()),
      P.mesh_gen_of(deps(1320, {"mesh_awg_gen": "bogus"}))) == ("3.1", "2.0", "2.0"))
check("no reason on any card: every link is what it was asked to be", all(P.mesh_gen_reasons(d, t, sn, x) == [] for x in t),
      {x: P.mesh_gen_reasons(d, t, sn, x) for x in t})
keep = P.mesh_relink_pair(t, "n02", "n00")
check("mesh_relink_pair tears the ONE link down on both ends (create cancelled, delete staged), the others untouched",
      "n02" not in t["n00"]["links"] and "n00" not in t["n02"]["links"] and "n01" in t["n00"]["links"]
      and len(t["n00"].get("delete") or {}) == 1 and len(t["n02"].get("delete") or {}) == 1, (t["n00"].get("delete"), t["n02"].get("delete")))
P.reconcile_mesh(t, sn, d)
check("…and the rebuild comes back under a fresh interface name, still WG",
      "n02" in t["n00"]["links"] and t["n00"]["links"]["n02"]["iface"] not in t["n00"]["delete"]
      and P.mesh_link_gen(t["n00"], t["n00"]["links"]["n02"]) == "wg", t["n00"]["links"].get("n02"))
check("mesh_types_in_play: a per-link choice anywhere counts", P.mesh_types_in_play(deps(), {"a": {"mesh_link_gen": {"b": "wg"}}})
      and not P.mesh_types_in_play(deps(), {"a": {"mesh_awg_gen": "wg"}}))

# ── [6] a mesh template with a field set to none (Part A, A4) ─────────────────────────────────────────────────────────
print("[6] a mesh template with \"-\": whole and exact where both ends can hold it, generated values otherwise")
ex = lambda: {"datapath": {"awg": {"gen": {"module": "3.1", "tools": "3.1"}, "exact": 1}}}
d = deps(1320, {"mesh_awg": {"I1": "-", "I2": "-", "Jc": "5", "Jmin": "50", "Jmax": "80"}})
t = run(P, fleet(3), d, {"n00": ex(), "n01": ex(), "n02": {}})
L = {(a, b): (ia, ib) for a, b, _, _, ia, ib, _, _ in links(t)}
ia, ib = L[("n00", "n01")]
check("both ends exact-capable: no I1/I2, the template's Jc, generator S/H — the same whole set on both ends",
      ia.get("awg_params") == ib.get("awg_params") and "I1" not in ia["awg_params"] and "I2" not in ia["awg_params"]
      and ia["awg_params"].get("Jc") == "5" and "S1" in ia["awg_params"] and "H4" in ia["awg_params"], ia)
check("…and awg_exact on both link records", ia.get("awg_exact") is True and ib.get("awg_exact") is True)
ia, ib = L[("n00", "n02")]
check("one end cannot hold an omission: I1/I2 keep the generator's values, no awg_exact",
      "I1" in ia["awg_params"] and "I2" in ia["awg_params"] and "awg_exact" not in ia, ia)
r = P.mesh_gen_reasons(d, t, {"n00": ex(), "n01": ex(), "n02": {}}, "n02")
check("…and n02's card says why, naming the keys and the node", len(r) == 2 and all("I1, I2" in x["msg"]["error"]
      and "node2" in x["msg"]["error"] for x in r), r)
check("n00↔n01 is not on any card", all(x["peer"] != "node1" for x in P.mesh_gen_reasons(d, t, {"n00": ex(), "n01": ex(), "n02": {}}, "n00")))
d = deps(1320, {"mesh_awg": {"S4": "-"}, "mesh_awg_gen": "3.1"})
t = run(P, fleet(2), d, {"n00": ex(), "n01": ex()})
lk = links(t)[0]
check("3.1 with S4 none in the template (a stored state the save refuses): the link falls back to 2.0, with the reason",
      P.mesh_link_gen(t["n00"], lk[2]) == "2.0" and any("S4" in x["msg"]["error"] for x in P.mesh_gen_reasons(d, t, {"n00": ex(), "n01": ex()}, "n00")),
      P.mesh_gen_reasons(d, t, {"n00": ex(), "n01": ex()}, "n00"))
check("…and no S4 on it (the omission held, no refit adds one)", "S4" not in lk[4]["awg_params"], lk[4]["awg_params"])

# ── [7] the six 3.1 fields of a 3.1 link, field by field (plan §8 round 11, operator 2026-10-06) ──────────────────────────
print("[7] a 3.1 link's 3.1 fields: node template, else panel template, else interface 3.1 defaults, else Amnezia's set")
f = fleet(2)
f["n00"]["mesh_awg"] = {"ContentPaddingAddition": "20-40"}
d = deps(1320, {"mesh_awg_gen": "3.1", "mesh_awg": {"RekeyTimeout": "4-8"},
                "interface_defaults": {"awg3_params": {"KeepaliveTimeout": "6-12", "RekeyTimeout": "2-3"}}})
t = run(P, f, d, {"n00": gen_snap(), "n01": gen_snap()})
pa = links(t)[0][4]["awg_params"]
check("node CPA 20-40, panel RekeyTimeout 4-8 (over the interface default 2-3), interface KeepaliveTimeout 6-12, the rest Amnezia's",
      pa.get("ContentPaddingAddition") == "20-40" and pa.get("RekeyTimeout") == "4-8" and pa.get("KeepaliveTimeout") == "6-12"
      and pa.get("RekeyAfterTime") == P.AWG31_SET["RekeyAfterTime"] and P.awg3_check(pa)[1] is None, pa)
ex2 = lambda: {"datapath": {"awg": {"gen": {"module": "3.1", "tools": "3.1"}, "exact": 1}}}
f = fleet(2); f["n00"]["mesh_awg"] = {"ContentPaddingAddition": "-"}
d = deps(1320, {"mesh_awg_gen": "3.1", "interface_defaults": {"awg3_params": {"MaxHandshakeAttempts": "-"}}})
t = run(P, f, d, {"n00": ex2(), "n01": ex2()})
lk = links(t)[0]
check("\"-\" (node CPA, interface MaxHandshakeAttempts) where both ends can hold it: no such line, the link whole",
      "ContentPaddingAddition" not in lk[4]["awg_params"] and "MaxHandshakeAttempts" not in lk[4]["awg_params"]
      and lk[4].get("awg_exact") is True and lk[5].get("awg_exact") is True, lk[4])
f = fleet(2); f["n00"]["mesh_awg"] = {"ContentPaddingAddition": "-"}   # a fresh pair: an existing link is never re-made
t = run(P, f, d, {"n00": gen_snap(), "n01": gen_snap()})
lk = links(t)[0]
check("…and where they cannot: Amnezia's values, no awg_exact", lk[4]["awg_params"].get("ContentPaddingAddition") == P.AWG31_SET["ContentPaddingAddition"]
      and "awg_exact" not in lk[4], lk[4])
check("mesh_template_clean keeps the six (value and \"-\") beside the 2.0 fields, and is awg_template_clean without them",
      P.mesh_template_clean({"Jc": "4", "S3": "-", "RekeyTimeout": " 4-8 ", "KeepaliveTimeout": "-", "HeaderProtectionKey": "x"})[0]
      == {"Jc": "4", "S3": "-", "RekeyTimeout": "4-8", "KeepaliveTimeout": "-"}
      and P.mesh_template_clean({"Jc": "4", "I1": "-"})[0] == P.awg_template_clean({"Jc": "4", "I1": "-"}))
check("…and refuses timings that cross", P.mesh_template_clean({"RekeyAfterTime": "170-180"})[1] is not None)
f = fleet(2); f["n00"]["mesh_awg"] = {"RekeyAfterTime": "100-128"}           # passes alone (128 + 7 + 15 ≤ 150) …
d = deps(1320, {"mesh_awg_gen": "3.1", "interface_defaults": {"awg3_params": {"RejectAfterTime": "110-180"}}})   # … crosses here
t = run(P, f, d, {"n00": gen_snap(), "n01": gen_snap()})
r = P.mesh_gen_reasons(d, t, {"n00": gen_snap(), "n01": gen_snap()}, "n00")
check("timings that cross only once the layers resolve: the link is made at 2.0, never one that drops data, and the card says why",
      P.mesh_link_gen(t["n00"], t["n00"]["links"]["n01"]) == "2.0" and len(r) == 1 and "RejectAfterTime" in r[0]["msg"]["error"], r)

# ── [8] a mesh template that sets SOME fields (repro .campaign/rigs/mesh-partial-template-repro.py) ─────────────────────
print("[8] a partial mesh template: both ends get ONE whole set — the template's fields, the generator's for the rest")
for label, f, d in (("node template {Jc, Jmin, Jmax}", fleet(2, {"Jc": "5", "Jmin": "50", "Jmax": "80"}), deps(1320)),
                    ("panel template {S1, H1}", fleet(2), deps(1320, {"mesh_awg": {"S1": "20", "H1": "100-115"}}))):
    t = run(P, f, d)
    a, b = links(t)[0][4]["awg_params"], links(t)[0][5]["awg_params"]
    tv = (f["n00"].get("mesh_awg") or d["panel_settings"].get("mesh_awg"))
    check(label + ": every 2.0 field on both ends, the same set", a == b and all(k in a for k in P.AWG_FIELDS[:16]), (sorted(a), a == b))
    check(label + ": the template's own values kept", all(str(a[k]) == v for k, v in tv.items()), {k: a.get(k) for k in tv})
    check(label + ": S4 inside the MTU's room, no awg_exact (nothing omitted)",
          P.mesh_s4_fits(a.get("S4"), 1320) and "awg_exact" not in links(t)[0][4])
t = run(P, fleet(2, {"Jc": "5", "Jmin": "50", "Jmax": "80"}), deps(1420))
check("at MTU 1420 the drawn S4 is refitted into the room (20)", int(links(t)[0][4]["awg_params"].get("S4", 999)) <= 20, links(t)[0][4]["awg_params"].get("S4"))

print()
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("All checks passed.")
