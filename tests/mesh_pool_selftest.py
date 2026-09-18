#!/usr/bin/env python3
"""Self-test: a mesh pool that cannot place a link is refused at the door, never takes the sync down, and is SAID.

Every link is a /31 from the pool of its smaller-id end (that node's mesh subnet, else the panel's). Measured on the
shipped 1.8.7 code with a real panel process (.campaign/rigs/mesh-pool-repro.py, 2026-09-18):
  • a panel mesh subnet of /32 or IPv6 was SAVED, and from the next pair that needed a link every node's sync answered
    500 — reconcile_mesh raised inside _node_sync_apply (loose-ends D5);
  • a node's /29 anchoring six links placed four and left two pairs unlinked with no event and no issue;
  • a full pool was re-walked, taken-set rebuilt over every link, once per unlinked pair on every sync (~85–130 ms added
    to every sync at 65 nodes on a /20, laptop).

  [1] the one question both doors and the allocator ask (mesh_pool_refusal)
  [2] a stored pool the allocator cannot use never raises — it is recorded as "bad" on the anchoring node
  [3] a full pool: the pairs it cannot place are recorded on the anchor, and the node issue names pool + peers
  [4] a full pool costs one walk per reconcile, not one per pair — and "Rebuild links" right after it filled rebuilds
      what fits (a 60 s full-pool memo once made that rebuild place nothing; found in review)
  [5] one reconcile walks each pool once, and hands out exactly the /31s a walk-from-the-start would: a mass link over
      overlapping pools (40 nodes), and a half-link whose stale record frees its /31 when replaced
  [6] the doors: node + panel settings refuse a /32 and an IPv6 range (even for a node that anchors nothing), a node's
      subnet too small for the links it anchors is refused with the numbers, nothing saved — while a panel pool change
      that works today is accepted, and an UNCHANGED stored value never blocks an unrelated edit
  [7] /api/state carries the issue with the peers by NAME

Hermetic: no network, no panel process.
Run:  python3 tests/mesh_pool_selftest.py              (0 = pass)
      python3 tests/mesh_pool_selftest.py --perturb    every plant must go red on its own check ("N plants, N caught")
"""
import importlib.machinery, importlib.util, ipaddress, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

# One plant per guard: (name, the exact source text, what replaces it, the check that must go red).
PLANTS = [
    ("alloc-guard", "        why = mesh_pool_refusal(pool)\n        if why:",
     "        why = \"\"\n        if why:", "a /32 panel pool: reconcile does not raise"),
    ("record", "            unplaced.setdefault(_x, {",
     "            0 and unplaced.setdefault(_x, {", "the /29 anchor records its two unplaced peers"),
    ("issue", "    if unplaced and unplaced.get(\"peers\"):", "    if False:",
     "the node issue names the pool and both peers"),
    ("half-release", "            alloc.release(_stale)", "            pass",
     "a half-link: both pairs healed, exactly as a walk from the start (n1 .2/31, n2 .0/31)"),
    ("cursor", "        it = self.walk.get(key)\n", "        it = None\n",
     "one reconcile walks each pool at most once"),
    ("door-node",
     "                if _why:\n                    return 400, {\"ok\": False, \"error\": \"mesh subnet must be an IPv4 range of /31 or larger (or blank)\",",
     "                if False:\n                    return 400, {\"ok\": False, \"error\": \"mesh subnet must be an IPv4 range of /31 or larger (or blank)\",",
     "node door: the largest id (anchors nothing) is refused a /32 too"),
    ("door-panel",
     "                if _why:\n                    return 400, {\"ok\": False, \"error\": \"reserved mesh subnet must be an IPv4 range of /31 or larger\",",
     "                if False:\n                    return 400, {\"ok\": False, \"error\": \"reserved mesh subnet must be an IPv4 range of /31 or larger\",",
     "panel door: a /32 is refused, nothing saved"),
    ("size-node", "                if _need > _room:", "                if False:", "node door: a /29 for six anchored links is refused with 4 / 6"),
    ("unchanged", "            if ms and ms != (nodes[nid].get(\"mesh_subnet\") or \"\"):", "            if ms:",
     "an unchanged stored /32 does not block a rename"),
    ("names", "                _unp = dict(_unp, peers=[(nodes.get(p) or {}).get(\"name\") or p for p in _unp.get(\"peers\") or ()])",
     "                _unp = dict(_unp)", "/api/state names the unplaced peers by NAME"),
]
def perturb_all():
    src = open(SERVER).read()
    caught, bad = 0, []
    for name, old, new, must in PLANTS:
        if src.count(old) != 1:
            bad.append("%s: anchor found %d times (stale plant)" % (name, src.count(old)))
            continue
        with tempfile.NamedTemporaryFile("w", suffix="-swg-panel-server", delete=False) as f:
            f.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_PANEL_SERVER=f.name),
                           capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = "  FAIL " + must in r.stdout
        crashed = "Traceback" in r.stderr and not red
        print("  %-12s %s" % (name, "caught" if red and r.returncode else
                                ("CRASHED (not a catch)" if crashed else "NOT CAUGHT")))
        if red and r.returncode:
            caught += 1
        else:
            bad.append(name)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    for b in bad:
        print("  ✗ " + b)
    return 0 if caught == len(PLANTS) and not bad else 1


if "--perturb" in sys.argv:
    sys.exit(perturb_all())

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgpanel", SERVER)
spec = importlib.util.spec_from_loader("swgpanel", loader)
P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass

TMP = tempfile.mkdtemp(prefix="meshpool.")
ROSTER = os.path.join(TMP, "users.json")

# Count every walk of a pool into /31s — the cost the allocator exists to bound.
WALKS = []
_orig_subnets = ipaddress.IPv4Network.subnets
def _counting_subnets(self, prefixlen_diff=1, new_prefix=None):
    if new_prefix == 31:
        WALKS.append(str(self))
    return _orig_subnets(self, prefixlen_diff, new_prefix)
ipaddress.IPv4Network.subnets = _counting_subnets


def deps(panel_pool=None, fleet=None):
    return {"fleet": dict(fleet or {}), "roster_path": ROSTER,
            "panel_settings": ({"reserved": {"mesh_subnet": panel_pool}} if panel_pool else {})}

def fleet(n, **per_node_pool):
    return {"n%d" % i: {"id": "n%d" % i, "name": "node%d" % i,
                        **({"mesh_subnet": per_node_pool["n%d" % i]} if "n%d" % i in per_node_pool else {})}
            for i in range(n)}

def linked(nodes, a):
    return sorted((nodes[a].get("links") or {}))


print("[1] what a mesh pool must be")
for v, want in (("10.255.0.0/16", ""), ("10.77.0.0/29", ""), ("10.77.0.0/31", ""), ("10.77.0.1/32", "range"),
                ("fd00:77::/64", "range"), ("not-a-cidr", "cidr"), ("", "cidr"), (None, "cidr")):
    check("mesh_pool_refusal(%r) == %r" % (v, want), P.mesh_pool_refusal(v) == want, P.mesh_pool_refusal(v))
check("a /29 holds 4 links, a /31 one, the default /16 32768",
      (P.mesh_pool_room("10.77.0.0/29"), P.mesh_pool_room("10.77.0.0/31"), P.mesh_pool_room("10.255.0.0/16")) == (4, 1, 32768))


print("[2] a stored pool the allocator cannot use never raises")
for label, d, nodes in (("a /32 panel pool", deps(panel_pool="10.77.0.1/32"), fleet(4)),
                        ("an IPv6 pool from fleet.json", deps(fleet={"mesh_subnet": "fd00:77::/64"}), fleet(4)),
                        ("a node's own stored /32", deps(), fleet(4, n0="10.99.0.1/32"))):
    try:
        P.reconcile_mesh(nodes, {}, d)
        raised = None
    except Exception as e:          # the shipped code raised IndexError / ValueError here, in every node's sync
        raised = repr(e)
    check(label + ": reconcile does not raise", raised is None, raised)
    u = (d.get("mesh_unplaced") or {}).get("n0") or {}
    check(label + ": the anchor n0 records why = bad, for its three peers",
          u.get("why") == "bad" and sorted(u.get("peers") or []) == ["n1", "n2", "n3"], u)
nodes = fleet(4, n0="10.99.0.1/32"); d = deps(); P.reconcile_mesh(nodes, {}, d)
check("…the pairs that do not touch the bad pool still link (n1–n2, n1–n3, n2–n3)",
      linked(nodes, "n1") == ["n2", "n3"] and linked(nodes, "n2") == ["n1", "n3"], [linked(nodes, x) for x in nodes])


print("[3] a full pool is recorded on its anchor and said")
nodes = fleet(7, n0="10.77.0.0/29"); d = deps()
P.reconcile_mesh(nodes, {}, d)
u = (d.get("mesh_unplaced") or {}).get("n0") or {}
check("n0 (/29, anchors six) links four: n1–n4", linked(nodes, "n0") == ["n1", "n2", "n3", "n4"], linked(nodes, "n0"))
check("the /29 anchor records its two unplaced peers",
      u.get("why") == "full" and u.get("pool") == "10.77.0.0/29" and u.get("own") is True
      and sorted(u.get("peers") or []) == ["n5", "n6"], u)
check("…and nothing else is recorded (every other pair came from the panel pool)", list(d["mesh_unplaced"]) == ["n0"],
      d["mesh_unplaced"])
iss = P._node_issues(nodes["n0"], {}, "", (), dict(u, peers=["node5", "node6"]))
txt = json.dumps(iss, ensure_ascii=False)
check("the node issue names the pool and both peers",
      any(i.get("error_key", "").startswith("This node's mesh subnet {v1} has no free /31 left")
          and i.get("error_vars", {}).get("v1") == "10.77.0.0/29" and i.get("error_vars", {}).get("v2") == "node5, node6"
          for i in iss), txt)
iss = P._node_issues(nodes["n1"], {}, "", (), dict(u, own=False, peers=["x%d" % k for k in range(8)]))
check("…a panel pool is sent to Panel settings, and a long list is bounded (5 + count)",
      any(i.get("error_key", "").startswith("The panel's mesh subnet {v1} has no free /31 left")
          and i.get("error_vars", {}).get("v2") == "x0, x1, x2, x3, x4, … (+3)" for i in iss), json.dumps(iss))
check("control: no unplaced pairs → no mesh-pool issue",
      not any("mesh subnet" in (i.get("error_key") or "") for i in P._node_issues(nodes["n1"], {}, "", (), None)))


print("[4] a full pool: one walk per reconcile, and a rebuild right after it filled rebuilds what fits")
del WALKS[:]
P.reconcile_mesh(nodes, {}, d)
check("a full pool is walked once per reconcile, not once per unplaced pair", WALKS.count("10.77.0.0/29") == 1, WALKS)
check("…and its pairs are still recorded (the issue does not flicker)",
      sorted(((d.get("mesh_unplaced") or {}).get("n0") or {}).get("peers") or []) == ["n5", "n6"], d.get("mesh_unplaced"))
P.mesh_reprovision_node(nodes, "n0")                                 # "Rebuild links", right after the pool filled
P.reconcile_mesh(nodes, {}, d)
check("\"Rebuild links\" right after the pool filled rebuilds the four that fit",
      len(linked(nodes, "n0")) == 4 and sorted(d["mesh_unplaced"]["n0"]["peers"]) and len(d["mesh_unplaced"]["n0"]["peers"]) == 2,
      (linked(nodes, "n0"), d.get("mesh_unplaced")))
nodes["n0"]["mesh_subnet"] = "10.77.0.0/28"                          # the operator widened it
P.reconcile_mesh(nodes, {}, d)
check("widened: every pair linked, nothing recorded",
      linked(nodes, "n0") == ["n1", "n2", "n3", "n4", "n5", "n6"] and not d.get("mesh_unplaced"), d.get("mesh_unplaced"))


print("[5] a mass link: one walk per pool, and exactly the /31s a walk from the start would hand out")
pools = {"n03": "10.60.0.0/26", "n07": "10.60.0.0/27", "n11": "10.61.0.0/24"}     # two overlap on purpose
nodes = {("n%02d" % i): {"id": "n%02d" % i, "name": "node%02d" % i,
                          **({"mesh_subnet": pools["n%02d" % i]} if "n%02d" % i in pools else {})} for i in range(40)}
d = deps(panel_pool="10.62.0.0/20")
d["panel_settings"]["mesh_mode"] = "full"      # a mass link is what a switch to full does (40 nodes > auto's line)
del WALKS[:]
P.reconcile_mesh(nodes, {}, d)
check("one reconcile walks each pool at most once", len(WALKS) == len(set(WALKS)) and len(WALKS) <= 4, WALKS)
ids = list(nodes)
taken, ok, order = set(), True, []
for i, a in enumerate(ids):                     # replay the shipped allocator: first free /31 from the pool's start
    for b in ids[i + 1:]:
        x = min(a, b)
        pool = nodes[x].get("mesh_subnet") or "10.62.0.0/20"
        want = next((str(s) for s in _orig_subnets(ipaddress.ip_network(pool), new_prefix=31) if str(s) not in taken), None)
        got = ((nodes[a].get("links") or {}).get(b) or {}).get("subnet")
        if want is not None:
            taken.add(want)
        if got != want:
            ok = False; order.append((a, b, want, got))
check("all 780 pairs placed — or refused — exactly as a walk from the start would (%d links)"
      % (sum(len(n.get("links") or {}) for n in nodes.values()) // 2), ok, order[:4])
# A half-link: n0 lost its records while n1 still holds its half (a hand-restored store, a lost update); n0–n2 is gone.
# The shipped walk sees n1's stale /31 as taken for the pair it replaces, then free: n1 → .2/31, n2 → .0/31.
nodes = fleet(3, n0="10.70.0.0/30")
nodes["n1"]["links"] = {"n0": {"iface": "swg_old", "subnet": "10.70.0.0/31", "address": "10.70.0.1", "peer_address": "10.70.0.0",
                               "listen_port": 9999}}
d = deps()
P.reconcile_mesh(nodes, {}, d)
got = {p: (nodes["n0"].get("links") or {}).get(p, {}).get("subnet") for p in ("n1", "n2")}
check("a half-link: both pairs healed, exactly as a walk from the start (n1 .2/31, n2 .0/31)",
      got == {"n1": "10.70.0.2/31", "n2": "10.70.0.0/31"} and not (d.get("mesh_unplaced") or {}).get("n0"),
      (got, d.get("mesh_unplaced")))


print("[6] the doors")
NP = os.path.join(TMP, "nodes.json")
PSP = os.path.join(TMP, "panel-settings.json")
nodes = fleet(7); ad = dict(deps(), nodes_path=NP, panel_settings_path=PSP, node_snaps={})
P.reconcile_mesh(nodes, {}, ad)
P.nodes_save(NP, nodes)
def upd(body):
    return P.api("POST", "/api/nodes/update", "", body, ad)
def stored(nid):
    return P.nodes_load(NP)[nid]
st, r = upd({"id": "n0", "mesh_subnet": "10.77.0.1/32"})
check("node door: a /32 is refused (400, not 500), nothing saved",
      st == 400 and "IPv4 range" in (r.get("error") or "") and not stored("n0").get("mesh_subnet"), (st, r))
st, r = upd({"id": "n6", "mesh_subnet": "10.77.0.1/32"})
check("node door: the largest id (anchors nothing) is refused a /32 too",   # the size check alone would let this through
      st == 400 and "IPv4 range" in (r.get("error") or "") and not stored("n6").get("mesh_subnet"), (st, r))
st, r = upd({"id": "n0", "mesh_subnet": "fd00:77::/64"})
check("node door: an IPv6 range is refused", st == 400 and "IPv4 range" in (r.get("error") or ""), (st, r))
st, r = upd({"id": "n0", "mesh_subnet": "not-a-cidr"})
check("node door: not a CIDR keeps its old sentence", st == 400 and r.get("error") == "mesh subnet must be a CIDR (or blank)",
      (st, r))
st, r = upd({"id": "n0", "mesh_subnet": "10.77.0.0/29"})
ev = r.get("error_vars") or {}
check("node door: a /29 for six anchored links is refused with 4 / 6",
      st == 400 and (ev.get("v2"), ev.get("v3")) == ("4", "6") and not stored("n0").get("mesh_subnet")
      and len(stored("n0").get("links") or {}) == 6, (st, r))
st, r = upd({"id": "n0", "mesh_subnet": "10.77.0.0/28"})
check("node door: a /28 is accepted and all six links are rebuilt from it",
      st == 200 and stored("n0").get("mesh_subnet") == "10.77.0.0/28"
      and all(ipaddress.ip_network(lr["subnet"]).subnet_of(ipaddress.ip_network("10.77.0.0/28"))
              for lr in stored("n0")["links"].values()) and len(stored("n0")["links"]) == 6, (st, r))
s = P.nodes_load(NP); s["n6"]["mesh_subnet"] = "10.99.0.1/32"; P.nodes_save(NP, s)   # a value stored before the door
st, r = upd({"id": "n6", "name": "renamed", "mesh_subnet": "10.99.0.1/32"})
check("an unchanged stored /32 does not block a rename", st == 200 and stored("n6").get("name") == "renamed", (st, r))
def pset(v):
    return P.api("POST", "/api/panel/settings", "", {"reserved": {"mesh_subnet": v}}, ad)
before = json.dumps(ad.get("panel_settings"), sort_keys=True)
st, r = pset("10.77.0.1/32")
check("panel door: a /32 is refused, nothing saved",
      st == 400 and "IPv4 range" in (r.get("error") or "") and json.dumps(ad.get("panel_settings"), sort_keys=True) == before,
      (st, r))
st, r = pset("fd00:77::/64")
check("panel door: an IPv6 range is refused", st == 400 and "IPv4 range" in (r.get("error") or ""), (st, r))
st, r = pset("10.88.0.0/29")
check("panel door: a /29 is accepted although today's links would not all fit — changing the pool moves none of them",
      st == 200 and P.mesh_cfg(ad)["subnet"] == "10.88.0.0/29", (st, r))
st, r = pset("10.88.0.0/29")
check("…and saving it again unchanged is accepted", st == 200, (st, r))


print("[7] /api/state names the unplaced peers")
s = P.nodes_load(NP)
for nid in s:                                    # tear the fleet down to nothing and give n0 a pool too small again
    s[nid]["links"] = {}
    for ifn in [k for k, v in (s[nid].get("ifaces") or {}).items() if v.get("system")]:
        s[nid]["ifaces"].pop(ifn)
s["n0"]["mesh_subnet"] = "10.77.0.0/30"
P.reconcile_mesh(s, {}, ad)
P.nodes_save(NP, s)
P.Handler.deps = ad
try:
    st, r = P.api("GET", "/api/state", "", {}, dict(ad, stats_dir=TMP, node_seen={}))
    n0 = next((n for n in ((r.get("data") or r).get("nodes") or []) if n.get("id") == "n0"), {})
    blob = json.dumps(n0.get("issues") or n0.get("issue_list") or n0, ensure_ascii=False)
    err = None
except Exception as e:
    blob, err = "", repr(e)
check("/api/state names the unplaced peers by NAME",
      err is None and "10.77.0.0/30" in blob and "node3" in blob and "n3\"" not in blob, err or blob[:600])

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    sys.exit(1)
print("OK")
