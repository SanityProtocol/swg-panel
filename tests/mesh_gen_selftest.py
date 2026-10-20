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
  [11] a link that kept what it was made with (q189 PR-4: a node enrolled after 3.1 was set has its links made at 2.0, and
      nothing rebuilds them when it reports) says what is true and how to rebuild THAT link from its card — following the
      default, its own type with the fleet's the same, its own type with the fleet's another — and each remedy, applied the
      way /api/connection/update applies it, rebuilds that one link as said and no other; the "-" case the same way.

Hermetic: no network, no panel process. The baseline tree is read with `git show` (SWG_MESH_GEN_BASE, default cba8e22).
Run: python3 tests/mesh_gen_selftest.py            (0 = pass)
     python3 tests/mesh_gen_selftest.py --perturb  (must FAIL: the type setting is ignored)
     --perturb-reprov  the reasons send the operator to re-provision the pair's anchor again (the copy before PR-4) — [11] must FAIL
     --perturb-own     the remedy ignores a link's own type (always "pick {type}") — [11] must FAIL
     --perturb-wait    a pair is made before an end has reported (the PR-4 behaviour) — [12] must FAIL
     --perturb-partial-link   a link made from part of a template is not named — [13] must FAIL
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
if "--perturb-merge" in sys.argv:     # the template read WHOLE (before the round-13 review): a link's own set beats the fleet's entirely
    def _whole(deps, node):
        v, om = P.awg_template((node or {}).get("mesh_awg"))
        return (v, om) if (v or om) else P.awg_template((deps.get("panel_settings") or {}).get("mesh_awg"))
    P.mesh_template = _whole
    print("(perturbed: a link's template is read whole, not over the fleet's field by field — [9] must FAIL)")
if "--perturb-keep" in sys.argv:      # the tree before round 14: a teardown drops the link's own settings with its record
    _park = P.mesh_link_park
    def _drop(nodes, who, other, **kw):
        lr = ((nodes.get(who) or {}).get("links") or {}).get(other)
        if lr:
            for k in P.MESH_LINK_KEEP:
                lr.pop(k, None)
        _park(nodes, who, other, **kw)
    P.mesh_link_park = _drop
    print("(perturbed: a teardown parks nothing — [10] must FAIL)")
if "--perturb-reprov" in sys.argv:   # the copy before q189 PR-4: a reason about one link re-provisions the pair's anchor
    P._mesh_relink_how = lambda deps, nodes, a, b, want: P.perr("re-provision {v1} to rebuild it",
                                                                v1=(nodes.get(min(a, b)) or {}).get("name") or min(a, b))
    print("(perturbed: the reasons re-provision a node — [11] must FAIL)")
if "--perturb-own" in sys.argv:      # a remedy that ignores the link's own type: "pick X" is no change when X is its type already
    P._mesh_relink_how = lambda deps, nodes, a, b, want: P.perr(
        "to rebuild this link alone, pick {v1} as its type on its card under Node connections and Save", v1=P.MESH_GEN_LABEL[want])
    print("(perturbed: the remedy ignores a link's own type — [11] must FAIL)")
if "--perturb-wait" in sys.argv:     # the tree before q189 PR-4's fix: a pair is made whatever its ends have reported
    P.mesh_link_waits = lambda deps, nodes, snaps, a, b: False
    print("(perturbed: no pair waits for its ends' reports — [12] must FAIL)")
if "--perturb-partial-link" in sys.argv:   # the tree before q189 PR-11: such a link goes unnamed
    P.mesh_link_partial = lambda ov: []
    print("(perturbed: a link made from part of a template is not named — [13] must FAIL)")
if "--perturb-link-awg" in sys.argv:  # the tree without a link's own params: the builder never reads them, nothing moves
    P.mesh_link_layer = lambda nodes, a, b: {"mesh_awg": {}}
    P.mesh_link_awg_migrate = lambda nodes: False
    print("(perturbed: a link's own AWG params are never read, a node's never moved — [0] and [9] must FAIL)")

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
                # a node's template now lives on the pairs it anchors (round 13): where it sits is the one difference
                if mawg and (a["n00"].get("mesh_link") != {y: {"awg": mawg} for y in a if y > "n00"} or "mesh_awg" in a["n00"]
                             or any("mesh_link" in a[x] for x in a if x != "n00")):   # fleet(): n00 holds the template
                    same = False
                    print("    template not moved onto every pair: n=%d" % n)
                a = {x: {k: v for k, v in r.items() if k not in ("mesh_awg", "mesh_link")} for x, r in a.items()}
                b = {x: {k: v for k, v in r.items() if k not in ("mesh_awg", "mesh_link")} for x, r in b.items()}
                if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                    same = False
                    print("    differs: n=%d mtu=%d mesh_awg=%s panel=%s" % (n, mtu, mawg, panel))
check("%d fleets (empty or full mesh templates): links, interfaces and creates byte-identical to %s; a node's template moved onto "
      "each pair it anchors" % (tried, BASE), same)
_strip = lambda t: {x: {k: v for k, v in r.items() if k not in ("mesh_awg", "mesh_link")} for x, r in t.items()}   # where it is stored
_pl = [_strip(run(M, fleet(3, {"Jc": "3", "S1": "20", "S4": "90"}), deps(1320), seed=3)) for M in (P, B)]
check("plant: a PARTIAL node template is the one deliberate difference (the fix in [8])",
      json.dumps(_pl[0], sort_keys=True) != json.dumps(_pl[1], sort_keys=True))
_r = run(P, fleet(4), deps())
check("…and no node has a reasons list", all(P.mesh_gen_reasons(deps(), _r, {}, nid) == [] for nid in _r))
check("…and the reasons are not even computed for it (mesh_types_in_play is false)", not P.mesh_types_in_play(deps(), _r))
check("…but are once anything is set: a panel type, a link's own type, a \"-\" in either template",
      P.mesh_types_in_play(deps(1320, {"mesh_awg_gen": "wg"}), _r)
      and P.mesh_types_in_play(deps(1320, {"mesh_awg": {"I1": "-"}}), _r)
      and P.mesh_types_in_play(deps(), {**_r, "zz": {"mesh_link": {"zy": {"type": "3.1"}}}})
      and P.mesh_types_in_play(deps(), {**_r, "zz": {"mesh_link": {"zy": {"awg": {"S3": "-"}}}}}))
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
f["n00"]["mesh_link"] = {"n02": {"type": "wg"}}    # stored on the pair's anchor (smaller id)
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
check("mesh_gen_of is the fleet's default only", (P.mesh_gen_of(d), P.mesh_gen_of(deps()),
      P.mesh_gen_of(deps(1320, {"mesh_awg_gen": "bogus"}))) == ("3.1", "2.0", "2.0"))
check("no reason on any card: every link is what it was asked to be", all(P.mesh_gen_reasons(d, t, sn, x) == [] for x in t),
      {x: P.mesh_gen_reasons(d, t, sn, x) for x in t})
P.mesh_relink_pair(t, "n02", "n00")
check("mesh_relink_pair tears the ONE link down on both ends (create cancelled, delete staged), the others untouched",
      "n02" not in t["n00"]["links"] and "n00" not in t["n02"]["links"] and "n01" in t["n00"]["links"]
      and len(t["n00"].get("delete") or {}) == 1 and len(t["n02"].get("delete") or {}) == 1, (t["n00"].get("delete"), t["n02"].get("delete")))
P.reconcile_mesh(t, sn, d)
check("…and the rebuild comes back under a fresh interface name, still WG",
      "n02" in t["n00"]["links"] and t["n00"]["links"]["n02"]["iface"] not in t["n00"]["delete"]
      and P.mesh_link_gen(t["n00"], t["n00"]["links"]["n02"]) == "wg", t["n00"]["links"].get("n02"))
check("mesh_types_in_play: a per-link choice anywhere counts", P.mesh_types_in_play(deps(), {"a": {"mesh_link": {"b": {"type": "wg"}}}})
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
    tv = (((f["n00"].get("mesh_link") or {}).get("n01") or {}).get("awg") or d["panel_settings"].get("mesh_awg") or {"Jc": "5"})   # a node's moved onto its pair
    check(label + ": every 2.0 field on both ends, the same set", a == b and all(k in a for k in P.AWG_FIELDS[:16]), (sorted(a), a == b))
    check(label + ": the template's own values kept", all(str(a[k]) == v for k, v in tv.items()), {k: a.get(k) for k in tv})
    check(label + ": S4 inside the MTU's room, no awg_exact (nothing omitted)",
          P.mesh_s4_fits(a.get("S4"), 1320) and "awg_exact" not in links(t)[0][4])
t = run(P, fleet(2, {"Jc": "5", "Jmin": "50", "Jmax": "80"}), deps(1420))
check("at MTU 1420 the drawn S4 is refitted into the room (20)", int(links(t)[0][4]["awg_params"].get("S4", 999)) <= 20, links(t)[0][4]["awg_params"].get("S4"))

# ── [9] a link's own AWG params (plan §8 round 13 — params belong to the pair, like its type) ───────────────────────────────
print("[9] a link's own AWG params beat the fleet's; a node's old template moves onto the pairs it anchors")
OWN = dict(FULLT, Jc="6", S4="30")
f = fleet(3); f["n00"]["mesh_link"] = {"n02": {"awg": dict(OWN)}}
d = deps(1320, {"mesh_awg": dict(FULLT, Jc="5")})
t = run(P, f, d)
pa = {(a, b): la for a, b, la, *_ in links(t)}
gp = lambda a, b: t[a]["ifaces"][t[a]["links"][b]["iface"]]["awg_params"]
check("n00↔n02 is made from its own params on both ends; n00↔n01 and n01↔n02 from the fleet's",
      gp("n00", "n02") == gp("n02", "n00") and gp("n00", "n02")["Jc"] == "6" and gp("n00", "n01")["Jc"] == "5" and gp("n01", "n02")["Jc"] == "5",
      (gp("n00", "n02").get("Jc"), gp("n00", "n01").get("Jc")))
FLEET = dict(FULLT, Jc="5", H1="100-115", I1="<r 9>")
f = fleet(2); f["n00"]["mesh_link"] = {"n01": {"awg": {"Jc": "6", "Jmin": "60", "Jmax": "90", "I2": "-"}}}
t2 = run(P, f, deps(1320, {"mesh_awg": FLEET}), {"n00": {}, "n01": {}})   # both have reported — neither can hold an omission
a2, b2 = (t2["n00"]["ifaces"][t2["n00"]["links"]["n01"]["iface"]]["awg_params"],
          t2["n01"]["ifaces"][t2["n01"]["links"]["n00"]["iface"]]["awg_params"])
check("a link that sets only some fields takes the FLEET's for the rest, field by field — H1 and I1 the fleet's, not the "
      "generator's (code review of round 13: the sheet shows them as the blank cells' background text)",
      a2 == b2 and a2["Jc"] == "6" and a2["H1"] == "100-115" and a2["I1"] == "<r 9>" and a2["S1"] == FLEET["S1"], a2)
check("…and its own \"-\" stands over the fleet's value (I2 omitted: no exact capability here, so the generator's value is kept "
      "and the card says so)", P.mesh_template(deps(1320, {"mesh_awg": FLEET}), P.mesh_link_layer(t2, "n00", "n01"))[1] == {"I2"})
check("mesh_template: a fleet \"-\" a link gives a value is no longer omitted; a fleet \"-\" it leaves blank still is",
      P.mesh_template(deps(1320, {"mesh_awg": {"S3": "-", "I1": "-"}}), {"mesh_awg": {"S3": "40"}})
      == ({"S3": "40"}, frozenset({"I1"})))
check("mesh_link_awg_set reads the pair from either end", P.mesh_link_awg_set(t, "n02", "n00") == OWN and P.mesh_link_awg_set(t, "n01", "n02") == {})
f = fleet(3); t = run(P, f, deps(1320))                                    # an existing fleet…
t["n01"]["mesh_awg"] = dict(OWN); t["n02"]["mesh_awg"] = {}                # …with a node template from before round 13, and an empty one
before = json.dumps(t["n01"]["links"], sort_keys=True)
moved = P.mesh_link_awg_migrate(t)
check("migration: n01's template moves onto every pair it anchors (n02), leaves the node; n00 anchors n01, so that pair has none",
      moved and t["n01"].get("mesh_link") == {"n02": {"awg": OWN}} and "mesh_awg" not in t["n01"] and "mesh_link" not in t["n00"], t["n01"])
check("…an empty template is not touched (a fleet that never used it keeps every byte), and no link is rebuilt by the move",
      t["n02"].get("mesh_awg") == {} and "mesh_link" not in t["n02"] and json.dumps(t["n01"]["links"], sort_keys=True) == before)
check("…and a second pass moves nothing", P.mesh_link_awg_migrate(t) is False)
t["n00"]["mesh_link"] = {"n02": {"type": "wg", "awg": dict(OWN)}, "n01": {"awg": dict(OWN)}}
P.mesh_unlink_node(t, "n02")
check("removing a node forgets its pairs' own type and params on their anchors, and keeps the others",
      t["n00"]["mesh_link"] == {"n01": {"awg": OWN}} and "mesh_link" not in t["n01"], (t["n00"].get("mesh_link"), t["n01"].get("mesh_link")))
check("a \"-\" in a link's own params counts as a setting", P.mesh_types_in_play(deps(), {"a": {"mesh_link": {"b": {"awg": {"I1": "-"}}}}})
      and not P.mesh_types_in_play(deps(), {"a": {"mesh_link": {"b": {"awg": {"Jc": "5"}}}}}))

# ── [10] a rebuild keeps what the operator set on the link (plan §8 round 14) ─────────────────────────────────────────────
print("[10] a rebuild — a node's re-provision or one link's — keeps each end's relay and dial settings")
ext = lambda t, a, b: {k: ((t[a].get("links") or {}).get(b) or {}).get(k) for k in P.MESH_LINK_KEEP}
def seed(t):
    t["n00"]["links"]["n01"].update(dial_endpoint="203.0.113.9", relay={"mode": "relay"})
    t["n01"]["links"]["n00"]["dial_src"] = "198.51.100.7"
want0 = {"relay": {"mode": "relay"}, "dial_endpoint": "203.0.113.9", "dial_src": None}
want1 = {"relay": None, "dial_endpoint": None, "dial_src": "198.51.100.7"}
t = run(P, fleet(3), deps(1320)); seed(t); if0 = t["n00"]["links"]["n01"]["iface"]
P.mesh_reprovision_node(t, "n01"); P.reconcile_mesh(t, {}, deps(1320))
check("a node re-provision rebuilds the link under a new name and puts both ends' settings back",
      t["n00"]["links"]["n01"]["iface"] != if0 and ext(t, "n00", "n01") == want0 and ext(t, "n01", "n00") == want1,
      (ext(t, "n00", "n01"), ext(t, "n01", "n00")))
check("…and nothing stays parked once the rebuild has them", all("link_keep" not in t[x] for x in t), {x: t[x].get("link_keep") for x in t})
if0 = t["n00"]["links"]["n01"]["iface"]
P.mesh_relink_pair(t, "n01", "n00"); P.reconcile_mesh(t, {}, deps(1320))
check("one link's rebuild (its sheet) does the same", t["n00"]["links"]["n01"]["iface"] != if0
      and ext(t, "n00", "n01") == want0 and ext(t, "n01", "n00") == want1 and all("link_keep" not in t[x] for x in t))
t = run(P, fleet(3), deps(1320))
P.mesh_reprovision_node(t, "n00"); P.reconcile_mesh(t, {}, deps(1320))
check("a re-provision with nothing set parks nothing (no new key in the store)", all("link_keep" not in t[x] and
      all(set(lr) & set(P.MESH_LINK_KEEP) == set() for lr in t[x]["links"].values()) for x in t))
dd = deps(1320, {"mesh_mode": "demand"})
t = run(P, fleet(2), deps(1320)); seed(t)
P.mesh_reprovision_node(t, "n00"); P.reconcile_mesh(t, {}, dd)
check("on demand, a pair needed only by its own dial / relay settings is rebuilt after a re-provision — the parked settings "
      "count as needing it", "n01" in t["n00"].get("links", {}) and ext(t, "n00", "n01") == want0, t["n00"].get("links"))
t = run(P, fleet(3), deps(1320)); seed(t)
P.mesh_link_park(t, "n00", "n01"); P.mesh_link_park(t, "n01", "n00")
P.mesh_unlink_node(t, "n01")
check("removing a node forgets what was parked for it", "link_keep" not in t["n00"], t["n00"].get("link_keep"))
# code review of round 14
t = run(P, fleet(2), deps(1320)); t["n00"]["links"]["n01"]["relay"] = {"mode": "forward"}   # what every sheet save writes
P.mesh_reprovision_node(t, "n00"); P.reconcile_mesh(t, {}, dd)
check("an inert relay {mode: forward} is neither parked nor needing the pair: on demand that link is not rebuilt",
      "n01" not in t["n00"].get("links", {}) and all("link_keep" not in t[x] for x in t), (t["n00"].get("links"), t["n00"].get("link_keep")))
t = run(P, fleet(2), deps(1320)); t["n00"]["links"]["ghost"] = {"iface": "swg_dead", "dial_src": "198.51.100.7"}
P.mesh_reprovision_node(t, "n00")
check("a half-link to a node no longer in the store is torn down but nothing is parked for it",
      "ghost" not in t["n00"]["links"] and "ghost" not in (t["n00"].get("link_keep") or {}), t["n00"].get("link_keep"))
t = run(P, fleet(2), deps(1320)); seed(t)
P.mesh_link_park(t, "n00", "n01", park=False)              # n00's half gone, n01 still holds its half, with its settings
P.reconcile_mesh(t, {}, deps(1320))
check("a half-link's leftover record is replaced keeping its own settings", ext(t, "n01", "n00") == want1, ext(t, "n01", "n00"))
t = run(P, fleet(3), deps(1320)); ifc = t["n00"]["links"]["n02"]["iface"]; t["n00"].setdefault("create", {})[ifc] = {"cmd": ["awg"]}
P.mesh_unlink_node(t, "n02")
check("removing a node also cancels a survivor's pending create for the link to it (no create + delete left staged)",
      ifc not in (t["n00"].get("create") or {}) and ifc in (t["n00"].get("delete") or {}))
t = run(P, fleet(3), deps(1320))
t["n00"]["mesh_link_gen"] = {"n01": "wg"}; t["n00"]["mesh_link_awg"] = {"n01": dict(OWN), "n02": dict(OWN)}
P.mesh_link_awg_migrate(t)
check("the two maps of the unreleased dev build fold into mesh_link, once", t["n00"].get("mesh_link") ==
      {"n01": {"type": "wg", "awg": OWN}, "n02": {"awg": OWN}} and "mesh_link_gen" not in t["n00"] and "mesh_link_awg" not in t["n00"],
      t["n00"].get("mesh_link"))
t = run(P, fleet(3), deps(1320)); seed(t); t["n00"]["mesh_link"] = {"n02": {"type": "wg"}}
cur = json.loads(json.dumps(t["n00"])); newrec = {"name": "node0"}
P.transfer_homecoming_keep(t, "n00", cur, newrec)
check("a node coming home keeps this panel's pair settings it anchors and parks its own halves' relay / dial",
      newrec.get("mesh_link") == {"n02": {"type": "wg"}} and newrec.get("link_keep") == {"n01": {"dial_endpoint": "203.0.113.9", "relay": {"mode": "relay"}}},
      newrec)
rec = {"name": "x", "links": {"a": {}}, "mesh_link": {"b": {"type": "wg"}}, "link_keep": {"b": {"dial_src": "1.2.3.4"}}, "ifaces": {}}
clean = P.transfer_strip(rec)[0]
check("a transfer carries neither the pairs' own settings nor parked ones (keyed by this fleet's ids)",
      not ({"links", "mesh_link", "link_keep"} & set(clean)), sorted(clean))

# ── [11] what a link that kept what it was made with says, and how to rebuild THAT link (q189 PR-4) ────────────────────
print("[11] a link that kept its type says so, and how to rebuild that one link — never \"re-provision\" a node")
PICK = "to rebuild this link alone, pick {v1} as its type on its card under Node connections and Save"
DFLT = "to rebuild this link alone, pick Default as its type on its card under Node connections and Save"
DFLT2 = "to rebuild this link alone, pick Default as its type on its card under Node connections and Save, then {v1} and Save again"
TYPE = "it should be {v1}, but a link keeps the type it was made with until it is rebuilt — {v2}"


def relink(t, d, sn, a, b, typ):
    """What /api/connection/update does with a type change: store it on the pair, tear the ONE link down, reconcile."""
    P.mesh_link_cfg_put(t, a, b, type=typ, awg=P.mesh_template_clean(P.mesh_link_awg_set(t, a, b))[0] or {})
    P.mesh_relink_pair(t, a, b)
    return run(P, t, d, sn)


def ids(t):
    return {(a, b): (la["iface"], json.dumps(ia.get("awg_params"), sort_keys=True)) for a, b, la, _, ia, *_ in links(t)}


def how(m):
    v2 = ((m or {}).get("error_vars") or {}).get("v2") or {}
    return v2.get("error_key"), (v2.get("error_vars") or {}).get("v1")


sn = {"n00": gen_snap(), "n01": gen_snap(), "n02": gen_snap()}
t = run(P, fleet(3), deps(1320), sn)             # a 2.0 fleet, every pair made…
d = deps(1320, {"mesh_awg_gen": "3.1"})
t = run(P, t, d, sn)                            # …then the fleet's type is set to 3.1: nothing rebuilds a working link
gens = {(a, b): P.mesh_link_gen(t[a], la) for a, b, la, *_ in links(t)}
check("a fleet whose type became 3.1 after its links were made: they stay 2.0 (nothing rebuilds a working link)",
      gens == {("n00", "n01"): "2.0", ("n00", "n02"): "2.0", ("n01", "n02"): "2.0"}, gens)
r = P.mesh_gen_reasons(d, t, sn, "n02")
check("n02's card names both its links", [x["peer"] for x in r] == ["node0", "node1"], r)
check("…saying what is true: it should be AWG 3.1, and a link keeps the type it was made with",
      all(x["msg"].get("error_key") == TYPE and x["msg"]["error_vars"]["v1"] == "AWG 3.1" for x in r), [x["msg"] for x in r])
check("…and how to rebuild that one link: pick AWG 3.1 as its type on its card",
      all(how(x["msg"]) == (PICK, "AWG 3.1") for x in r), [how(x["msg"]) for x in r])
check("…never a type change that did not happen, nor re-provisioning a node (that rebuilds every link it has)",
      not any("re-provision" in x["msg"]["error"] or "changed" in x["msg"]["error"] for x in r), [x["msg"]["error"] for x in r])
before = ids(t)
t = relink(t, d, sn, "n02", "n00", "3.1")
after = ids(t)
check("the remedy, applied as the card applies it: n00↔n02 is rebuilt at 3.1, under a new name",
      P.mesh_link_gen(t["n00"], t["n00"]["links"]["n02"]) == "3.1" and after[("n00", "n02")][0] != before[("n00", "n02")][0], after)
check("…and no other link moved (n00↔n01 and n01↔n02 are as they were)",
      all(after[k] == before[k] for k in (("n00", "n01"), ("n01", "n02"))), (before, after))
check("…and n02's card now names only its link still at 2.0", [x["peer"] for x in P.mesh_gen_reasons(d, t, sn, "n02")] == ["node1"])

# a link with a type of its own: "pick AWG 3.1" would be no change there (Save stays dark) — Default is the change
for fleet_gen, want_how in (("3.1", (DFLT, None)), (None, (DFLT2, "AWG 3.1"))):
    d = deps(1320, {"mesh_awg_gen": fleet_gen} if fleet_gen else {})
    sn = {"n00": gen_snap(), "n01": gen_snap(), "n02": gen_snap(module="2.0", tools="2.0")}
    f = fleet(3); P.mesh_link_cfg_put(f, "n01", "n02", type="3.1")
    t = run(P, f, d, sn)                        # n02 runs a 2.0 module: the pair is made at 2.0, and says why…
    sn["n02"] = gen_snap()
    t = run(P, t, d, sn)                        # …then its module is updated to 3.1
    r = {x["peer"]: x for x in P.mesh_gen_reasons(d, t, sn, "n02")}
    tag = "fleet's type %s" % (fleet_gen or "2.0 (unset)")
    check("%s, n01↔n02 set to 3.1 on its own, made at 2.0 while n02 ran a 2.0 module: told it should be AWG 3.1, and %s" % (tag, "pick Default" if
          fleet_gen else "pick Default, then AWG 3.1 again"), "node1" in r and r["node1"]["msg"].get("error_key") == TYPE
          and how(r["node1"]["msg"]) == want_how, r.get("node1"))
    before = ids(t)
    t = relink(t, d, sn, "n01", "n02", "")      # Default
    if not fleet_gen:
        check("%s: Default rebuilds it at the fleet's 2.0 — no reason left, so the second step is the operator's own" % tag,
              P.mesh_link_gen(t["n01"], t["n01"]["links"]["n02"]) == "2.0" and P.mesh_gen_reasons(d, t, sn, "n02") == [])
        t = relink(t, d, sn, "n01", "n02", "3.1")
    after = ids(t)
    check("%s: the remedy as said leaves n01↔n02 at 3.1, and only that link moved" % tag,
          P.mesh_link_gen(t["n01"], t["n01"]["links"]["n02"]) == "3.1"
          and all(after[k] == before[k] for k in after if k != ("n01", "n02")), (before, after))

# the "-" case: values generated because an end could not hold an omission when the link was made, and it can now
ex = lambda: {"datapath": {"awg": {"gen": {"module": "3.1", "tools": "3.1"}, "exact": 1}}}
d = deps(1320, {"mesh_awg": {"I1": "-", "I2": "-", "Jc": "5", "Jmin": "50", "Jmax": "80"}})
sn = {"n00": ex(), "n01": ex(), "n02": {}}
t = run(P, fleet(3), d, sn)
sn["n02"] = ex()
t = run(P, t, d, sn)
r = P.mesh_gen_reasons(d, t, sn, "n02")
OMIT = "{v1} has generated values where its AWG params say none — a link keeps the values it was made with until it is rebuilt; {v2}"
check("\"-\" fields made with generated values, the end able to hold none now: both links say so, with the one-link remedy",
      len(r) == 2 and all(x["msg"].get("error_key") == OMIT and x["msg"]["error_vars"]["v1"] == "I1, I2"
                          and how(x["msg"]) == (PICK, "AWG 2.0") for x in r), [x["msg"] for x in r])
check("…never re-provisioning a node", not any("re-provision" in x["msg"]["error"] for x in r))
before = ids(t)
t = relink(t, d, sn, "n00", "n02", "2.0")
L = {(a, b): ia for a, b, _, _, ia, *_ in links(t)}
after = ids(t)
check("…and the remedy as said rebuilds n00↔n02 without I1/I2, exact, and moves no other link",
      "I1" not in L[("n00", "n02")]["awg_params"] and L[("n00", "n02")].get("awg_exact") is True
      and all(after[k] == before[k] for k in after if k != ("n00", "n02")), (L[("n00", "n02")], before, after))

# ── [12] a pair whose type needs both ends' reports waits for them (q189 PR-4, the behaviour) ──────────────────────────
print("[12] a node enrolled after 3.1 (or a \"-\" template) was set gets its links once it has reported — at the type in force")
d = deps(1320, {"mesh_awg_gen": "3.1"})
sn = {"n00": gen_snap(), "n01": gen_snap()}
t = run(P, fleet(3), d, sn)                     # n02 enrolled, no report yet
lk = {(a, b) for a, b, *_ in links(t)}
check("3.1 fleet: no pair is made with the node that has not reported; the reported pair is made at 3.1",
      lk == {("n00", "n01")} and P.mesh_link_gen(t["n00"], t["n00"]["links"]["n01"]) == "3.1", lk)
check("…and no card names a reason meanwhile", all(P.mesh_gen_reasons(d, t, sn, x) == [] for x in t), {x: P.mesh_gen_reasons(d, t, sn, x) for x in t})
sn["n02"] = gen_snap()
t = run(P, t, d, sn)                            # its first sync stores its report, then reconciles
gens = {(a, b): P.mesh_link_gen(t[a], la) for a, b, la, *_ in links(t)}
check("its first report made its pairs — at 3.1, as the fleet asks", gens == {("n00", "n01"): "3.1", ("n00", "n02"): "3.1", ("n01", "n02"): "3.1"}, gens)
check("…and no card names a reason (the PR-4 mismatch no longer arises)", all(P.mesh_gen_reasons(d, t, sn, x) == [] for x in t))
t0 = run(P, fleet(3), deps(1320), {"n00": gen_snap(), "n01": gen_snap()})
check("a 2.0 fleet with no \"-\" makes every pair at once, reported or not (as before — small fleets feel nothing)",
      {(a, b) for a, b, *_ in links(t0)} == {("n00", "n01"), ("n00", "n02"), ("n01", "n02")})
dm = deps(1320, {"mesh_awg": {"I1": "-", "I2": "-", "Jc": "5", "Jmin": "50", "Jmax": "80"}})
sx = {"n00": ex(), "n01": ex()}
t = run(P, fleet(3), dm, sx)
check("a \"-\" template: the node that has not reported waits too", {(a, b) for a, b, *_ in links(t)} == {("n00", "n01")})
sx["n02"] = ex()
t = run(P, t, dm, sx)
L = {(a, b): ia for a, b, _, _, ia, *_ in links(t)}
check("…and once it reports it can hold an omission, its links are whole and exact — no generated I1/I2, no card reason",
      all("I1" not in L[k]["awg_params"] and L[k].get("awg_exact") is True for k in (("n00", "n02"), ("n01", "n02")))
      and P.mesh_gen_reasons(dm, t, sx, "n02") == [], {k: (sorted(v["awg_params"]), v.get("awg_exact")) for k, v in L.items()})
before = ids(t)
del sx["n02"]                                   # its report gone (a panel restart without its mirror)…
t = run(P, t, dm, sx)
check("an existing link is never touched by the wait: an end that loses its report keeps its links as they are", ids(t) == before)

# ── [13] a link 1.8.8 made from part of a template (q189 PR-11) ──────────────────────────────────────────────────────
print("[13] a mesh link made from part of a template is named on its card, with the one-link rebuild")
sn = {"n00": gen_snap(), "n01": gen_snap(), "n02": gen_snap()}
d = deps(1320)                                   # no type, no "-": the reasons are otherwise never computed
t = run(P, fleet(3), d, sn)
ifc = t["n00"]["links"]["n01"]["iface"]; ifc2 = t["n01"]["links"]["n00"]["iface"]
for nid, i in (("n00", ifc), ("n01", ifc2)):     # what 1.8.8 stored from a template that set only Jc/Jmin/Jmax
    t[nid]["ifaces"][i]["awg_params"] = {"Jc": "5", "Jmin": "50", "Jmax": "80"}
check("the card's reasons are computed although no mesh type is set", P.mesh_types_in_play(d, t))
r = {x["peer"]: x for x in P.mesh_gen_reasons(d, t, sn, "n00")}
m = (r.get("node1") or {}).get("msg") or {}
check("n00's card names the link to n01 with the keys it lacks, and how to rebuild that one link",
      m.get("error_key", "").startswith("made from part of a template") and m.get("error_vars", {}).get("v1") == "S1, S2, H1, H2, H3, H4"
      and how(m) == (PICK, "AWG 2.0"), m)
check("…and only that link (n00↔n02 is whole)", list(r) == ["node1"], list(r))
t[ "n00"]["ifaces"][ifc]["awg_exact"] = True
check("an exact link (a template's \"-\") omits keys on purpose and is not named", "node1" not in {x["peer"] for x in P.mesh_gen_reasons(d, t, sn, "n00")})
t["n00"]["ifaces"][ifc].pop("awg_exact")
t = relink(t, d, sn, "n00", "n01", "2.0")
check("the rebuild as said gives the link a whole set on both ends, and the card names nothing",
      not P.mesh_link_partial(t["n00"]["ifaces"][t["n00"]["links"]["n01"]["iface"]]) and P.mesh_gen_reasons(d, t, sn, "n00") == [])
check("a fleet with no such link computes no reasons (the gate's cost unchanged)", not P.mesh_types_in_play(d, run(P, fleet(3), d, sn)))

print()
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("All checks passed.")
