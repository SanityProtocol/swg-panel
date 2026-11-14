#!/usr/bin/env python3
"""Self-test — failover nodes, the panel core and awareness (docs/FAILOVER-PLAN.md §4, §8; refresh 2026-11-14; card failover-p1p2).

  [1] Census: every setting /api/nodes/update and /api/iface/update accept is classified followed, cloned or local, so a new
      field cannot silently miss; `p2p_portok_none` followed, `fast_lane` and `endpoint_host` local (refresh R5, §4.2).
  [2] The mirror pass: identity cloned once and never followed (an Adopt on A never reaches B); settings followed, `egress_ip`
      only in forward mode; a restore staged only with a vault key source; steady state writes nothing; a key mismatch, a
      stale A, a box's own interface delete nothing; a record A dropped with A reporting is dropped on B.
  [3] `rid`: B's roster-derived reply equals A's field by field, `limits` included; the two `p2p_*` memos keep separate slots;
      a router peer's arrival from B is named A; a block category enabled on A and a list switched off on A hold on B.
  [4] The planner: the idle member walked last — no clash card, its local block rule kept, the serving member forwards and the
      exit at C keeps A's `egress_ip`; flips with A stale and clients on B, not with none; an even split is stable.
  [5] Mesh: in full mode B is linked only where its rules ask; `auto` does not count mirrors; `_fleet_user_networks` skips B.
  [6] The ledger: B's bytes land in the device's slot (volume included); a roster save keeps B's baseline; a pair set or
      cleared rebuilds the map; with no pair the mark is today's.
  [7] Read-only: a POST naming B is refused (an iface edit, /api/peers/targets' lists, a node edit beyond name and colour);
      the allow-list passes (rotate, update, detach, a link's own settings).
  [8] Take-over and removal: targets move, `p2p_yield` follows (each port keeps its holder), A's interface dropped, B takes
      A's host; an interface B lacks stays on A with its peers; node_remove(A) keeps every held peer; detach-keep refused
      with A offline; a transfer of A refused.
  [9] reconcile.js: A stale, B online → online, no orphans; A stale, B without the interface → unknown, no Restore; no
      mirrors → unchanged.
  [10] Real panels: with no failover node the sync reply is byte-identical to the reference build's (7c7987e8); with one,
      B's reply equals A's (desired, limits, remove) and the doors work end to end.

Run: python3 tests/failover_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     follow-key   the pass follows `public_key` (an Adopt on A reaches B)
     endpoint     the pass follows `endpoint_host`
     nokeysrc     a restore is staged without a vault key source
     stale-del    a stale A's missing record deletes B's
     rid          B's sync reads its own id, not its primary's
     limits-rid   limits_for_node is asked with B's id
     memo         the p2p memos share one slot
     arrivals     an arrival from B is not mapped to A
     idle-first   the idle member is walked first
     clash        the idle member's clash is noted
     mesh-all     a failover node is linked to every node in full mode
     auto-count   `auto` counts failover nodes
     ledger-dep   the ledger claims B's counters but not B's deployments
     ledger-mark  the ledger's mark ignores the pairs
     guard-lists  the read-only guard does not read /api/peers/targets' lists
     yield        a take-over leaves `p2p_yield` naming A
     remove       node_remove purges a primary's peers without a take-over
     served       reconcile.js reads the target's own node only
     portok       `p2p_portok_none` is not followed
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
RECON = os.path.join(ROOT, "reconcile.js")
REF = "7c7987e8"                                  # origin/dev before failover: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # (file, anchor, replacement)
    "follow-key": ("panel", '''FO_IF_FOLLOW = ("listen_port", ''', '''FO_IF_FOLLOW = ("public_key", "listen_port", '''),
    "endpoint": ("panel", '''FO_IF_FOLLOW = ("listen_port", ''', '''FO_IF_FOLLOW = ("endpoint_host", "listen_port", '''),
    "nokeysrc": ("panel", '''                or n in (w.get("delete") or {}) or _iface_key_source(bov, None, ivk) != "vault"):''',
                 '''                or n in (w.get("delete") or {})):'''),
    "stale-del": ("panel", '''    if _fo_live(seen, aid, now):
        arep = ''', '''    if True:
        arep = '''),
    "rid": ("panel", '''        _rid = failover_rid(nodes, nid)
        # The shared parsed roster (P2): READ-ONLY.''', '''        _rid = nid
        # The shared parsed roster (P2): READ-ONLY.'''),
    "limits-rid": ("panel", '''(_lims := limits_for_node(roster, _rid, desired, snap))''', '''(_lims := limits_for_node(roster, nid, desired, snap))'''),
    "memo": ("panel", '''    slot = node_id if slot is None else slot
    hit = _P2P_FWD.get(slot)''', '''    slot = node_id
    hit = _P2P_FWD.get(slot)'''),
    "arrivals": ("panel", '''    return [(S, failover_rid(nodes, o)) for S, o in out] if nodes else out''', '''    return out'''),
    "idle-first": ("panel", '''(sorted(nodes.items(), key=lambda kv: kv[0] in idle) if idle else nodes.items())''',
                   '''(sorted(nodes.items(), key=lambda kv: kv[0] not in idle) if idle else nodes.items())'''),
    "clash": ("panel", '''        if nid in idle:
            return
        slot(nid).setdefault("_clash", {})''', '''        slot(nid).setdefault("_clash", {})'''),
    "mesh-all": ("panel", '''        if _fo:
            _fneed = mesh_need(nodes, deps)''', '''        if False:
            _fneed = mesh_need(nodes, deps)'''),
    "auto-count": ("panel", '''    n = sum(1 for c in nodes.values() if not (isinstance(c, dict) and c.get("failover_of")))''', '''    n = len(nodes)'''),
    "ledger-dep": ("panel", '''                    deploys.add((fo[t["node"]], t["iface"], pid))''', '''                    pass'''),
    "ledger-mark": ("panel", '''        if pairs:                                              # …or a failover pair''', '''        if False:                                              # …or a failover pair'''),
    "guard-lists": ("panel", '''    for k in ("targets", "base", "add", "address", "remove"):''', '''    for k in ("targets",):'''),
    "yield": ("panel", '''        if aid in ys:
            ys = (ys | {bid})''', '''        if False:
            ys = (ys | {bid})'''),
    "remove": ("panel", '''    _fo_b = failover_pairs(nodes).get(nid)
    _fo_moved''', '''    _fo_b = None
    _fo_moved'''),
    "served": ("recon", '''      const mb = cfg.mirrors ? cfg.mirrors[t.node] : null;''', '''      const mb = null;'''),
    "portok": ("panel", '''"lan_share", "ip_learning", "p2p", "p2p_portok", "p2p_portok_none", "catalog_cats")''',
               '''"lan_share", "ip_learning", "p2p", "p2p_portok", "catalog_cats")'''),
}

TMP = tempfile.mkdtemp(prefix="swg-failover-")
SRC = open(PANEL, encoding="utf-8").read()
RSRC = open(RECON, encoding="utf-8").read()
if PLANT:
    f, cut, new = PLANTS[PLANT]
    if f == "panel":
        assert SRC.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
        SRC = SRC.replace(cut, new, 1)
    else:
        assert RSRC.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
        RSRC = RSRC.replace(cut, new, 1)
NEW = os.path.join(TMP, "swg-panel-server")
open(NEW, "w", encoding="utf-8").write(SRC)
os.symlink(os.path.join(ROOT, "js"), os.path.join(TMP, "js"))   # reconcile.js imports ./js/i18n.js
NEWR = os.path.join(TMP, "reconcile.mjs")
open(NEWR, "w", encoding="utf-8").write(RSRC)


def load(path, name):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


P = load(NEW, "swgpanel_failover")
IVK = "V" * 43 + "="
P._current_ivk_pub = lambda deps: IVK
KA, KB, KX = "A" * 43 + "=", "B" * 43 + "=", "X" * 43 + "="
PK = ["%s" % (chr(ord("a") + i) * 43 + "=") for i in range(8)]
NOW = 1_800_000_000


def guarded(name, fn):
    try:
        fn()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(name + " ran", False, repr(e))


def a_iface(**kw):
    ov = {"public_key": KA, "key_blob": {"pub": KA, "ct": "c", "eph": "e", "mac": "m", "vault": IVK},
          "_lastcfg": {"subnet": "10.8.0.0/24", "listen_port": 443, "address": "10.8.0.1/24"},
          "listen_port": 443, "mtu": 1380, "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70},
          "endpoint_host": "vpn.example.com", "block": ["ads"], "egress_mode": "forward", "egress_node": "nc",
          "egress_ip": "7.7.7.7", "_synced": {"listen_port": 443}}
    ov.update(kw)
    return ov


def fleet():
    return {"na": {"id": "na", "name": "hel-1", "endpoint_host": "a.example.com", "routing_mode": "kernel",
                   "p2p_portok_none": True, "fast_lane": 50, "ifaces": {"awg0": a_iface()}, "links": {}},
            "nb": {"id": "nb", "name": "hel-2", "failover_of": "na", "endpoint_host": "", "ifaces": {}, "links": {}},
            "nc": {"id": "nc", "name": "exit", "ifaces": {}, "links": {}}}


def snap_iface(key=KA, subnet="10.8.0.0/24", peers=(), port=443):
    return {"meta": {"public_key": key, "subnet": subnet, "listen_port": port, "address": "10.8.0.1/24"},
            "peers": [{"public_key": k, "online": on, "rx_bytes": rx, "tx_bytes": tx} for k, on, rx, tx in peers]}


DEPS = {"panel_settings": {}, "roster_path": os.path.join(TMP, "users.json")}


# ── [1] census ───────────────────────────────────────────────────────────────────────────────────────────────────────
LOCAL_NODE = {"id", "name", "color", "endpoint_host", "endpoint_hosts", "default_egress_ip", "panel_ip", "mesh_egress_ip",
              "log_mb", "relay", "fast_lane", "mesh_subnet", "mesh_port", "mesh_prefix", "iface_order", "turn_order",
              "ignore_ifaces", "links", "link_keep", "exits", "mesh_type", "mesh_awg", "mesh_mtu"}
LOCAL_IFACE = {"endpoint_host", "drops_reset", "mesh_reset"}
NOT_STORED = {"awg_gen", "routing_v"}            # an intent (a recreate) and a client version: never a record field


def door_keys(path, helpers=()):
    import re
    a = SRC.index('method == "POST" and path == "%s"' % path)
    e = re.compile(r'\n\s*if method == "[A-Z]+" and path').search(SRC, a + 10).start()   # the next door, at any depth
    blk = SRC[a:e]
    for h in helpers:                                # the setters the door hands its body to
        ha = SRC.index("\ndef %s(" % h)
        blk += SRC[ha:SRC.index("\ndef ", ha + 5)]
    return set(re.findall(r'"([a-z_]+)" in body', blk)) | set(re.findall(r'body\.get\("([a-z_]+)"', blk))


def sec1():
    print("[1] census")
    nk = door_keys("/api/nodes/update") - {"id", "routing_reset", "routing_reset_learned"} - NOT_STORED
    ik = door_keys("/api/iface/update", ("_apply_egress_mode", "_apply_iface_p2p", "reach_level_set")) - {"node", "iface", "id"} - NOT_STORED
    nf, ifo = set(P.FO_NODE_FOLLOW), set(P.FO_IF_FOLLOW) | set(P.FO_IF_FWD) | set(P.FO_IF_CLONE)
    check("[1] every node setting is followed or local", not (nk - nf - LOCAL_NODE), sorted(nk - nf - LOCAL_NODE))
    check("[1] every interface setting is followed, cloned or local", not (ik - ifo - LOCAL_IFACE), sorted(ik - ifo - LOCAL_IFACE))
    check("[1] p2p_portok_none followed, fast_lane local", "p2p_portok_none" in nf and "fast_lane" not in nf)
    check("[1] endpoint_host and the identity are never followed",
          not ({"endpoint_host", "public_key", "key_blob", "_lastcfg"} & set(P.FO_IF_FOLLOW)))


# ── [2] the mirror pass ──────────────────────────────────────────────────────────────────────────────────────────────
def sec2():
    print("[2] the mirror pass")
    n = fleet()
    seen = {"na": NOW, "nb": NOW}
    snaps = {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}
    ch = P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    b = n["nb"]
    bo = (b.get("ifaces") or {}).get("awg0") or {}
    check("[2] the identity is cloned", ch and bo.get("public_key") == KA and bo.get("key_blob", {}).get("pub") == KA
          and bo.get("_lastcfg", {}).get("subnet") == "10.8.0.0/24", bo)
    check("[2] settings followed", bo.get("listen_port") == 443 and bo.get("awg_params") == {"Jc": 4, "Jmin": 40, "Jmax": 70}
          and bo.get("block") == ["ads"] and bo.get("egress_node") == "nc", bo)
    check("[2] egress_ip followed in forward mode", bo.get("egress_ip") == "7.7.7.7", bo)
    check("[2] endpoint_host not followed (B's own)", "endpoint_host" not in bo and b.get("endpoint_host") == "", (bo, b.get("endpoint_host")))
    check("[2] node settings: p2p_portok_none followed, fast_lane local", b.get("p2p_portok_none") is True and "fast_lane" not in b, b)
    cr = (b.get("create") or {}).get("awg0") or {}
    check("[2] a restore staged, holding for the vault key", cr.get("hold_key") is True and cr.get("subnet") == "10.8.0.0/24"
          and cr.get("listen_port") == 443, cr)
    check("[2] _synced is not cloned", "_synced" not in bo or not bo["_synced"], bo.get("_synced"))
    check("[2] steady state writes nothing", P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW) is False)
    # B now reports the interface
    snaps["nb"] = {"interfaces": {"awg0": snap_iface()}}
    b.pop("create", None)
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] a reported interface is not re-staged", "awg0" not in (b.get("create") or {}), b.get("create"))
    # an Adopt on A: A's blessed key moves
    n["na"]["ifaces"]["awg0"]["public_key"] = KX
    n["na"]["ifaces"]["awg0"]["key_blob"] = {"pub": KX, "ct": "z", "vault": IVK}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] an Adopt on A never reaches B", b["ifaces"]["awg0"]["public_key"] == KA and b["ifaces"]["awg0"]["key_blob"]["pub"] == KA,
          b["ifaces"]["awg0"].get("public_key"))
    # follow a change; port change clears _synced
    n["na"]["ifaces"]["awg0"]["public_key"] = KA
    n["na"]["ifaces"]["awg0"]["key_blob"] = {"pub": KA, "ct": "c", "vault": IVK}
    b["ifaces"]["awg0"]["_synced"] = {"listen_port": 443}
    n["na"]["ifaces"]["awg0"]["listen_port"] = 8443
    n["na"]["ifaces"]["awg0"]["egress_mode"] = "direct"
    n["na"]["ifaces"]["awg0"]["egress_ip"] = "1.2.3.4"
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    bo = b["ifaces"]["awg0"]
    check("[2] a port change follows and clears its _synced", bo["listen_port"] == 8443 and "listen_port" not in bo.get("_synced", {}), bo)
    check("[2] direct mode: A's own egress_ip is not B's (Auto there)", "egress_ip" not in bo, bo)
    # a key mismatch on B deletes nothing
    snaps["nb"] = {"interfaces": {"awg0": snap_iface(key=KX)}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] a key mismatch deletes nothing", "awg0" in b["ifaces"] and "awg0" not in (b.get("delete") or {}), b.get("delete"))
    # A drops awg0 while stale, its last snapshot without it: nothing deleted
    rec = n["na"]["ifaces"].pop("awg0")
    snaps["na"] = {"interfaces": {}}
    P.failover_mirror(DEPS, n, "nb", snaps, {"na": NOW - 3600, "nb": NOW}, now=NOW)
    check("[2] a stale A removes nothing from B", "awg0" in b["ifaces"] and not (b.get("delete") or {}), b.get("delete"))
    # A live, still reporting it: nothing
    snaps["na"] = {"interfaces": {"awg0": snap_iface()}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] A live but still reporting it: kept", "awg0" in b["ifaces"], b.get("delete"))
    # A live, not reporting it: deleted
    snaps["na"] = {"interfaces": {}}
    P.failover_mirror(DEPS, n, "nb", snaps, seen, now=NOW)
    check("[2] record and box agree on A: dropped on B", "awg0" not in b["ifaces"] and "awg0" in (b.get("delete") or {}), b)
    # never a create without a key source
    n2 = fleet()
    n2["na"]["ifaces"]["awg0"]["key_blob"]["vault"] = "other"
    P.failover_mirror(DEPS, n2, "nb", {"na": {}, "nb": {"interfaces": {}}}, seen, now=NOW)
    check("[2] no vault key source: nothing staged", not (n2["nb"].get("create") or {}), n2["nb"].get("create"))
    # a box's own interface on B: neither recorded (T-17 off, see [10]) nor deleted
    n3 = fleet()
    n3["nb"]["ifaces"] = {"wg9": {"system": True}}
    P.failover_mirror(DEPS, n3, "nb", {"na": {"interfaces": {"awg0": snap_iface()}}, "nb": {"interfaces": {}}}, seen, now=NOW)
    check("[2] a link record of B's own is untouched", n3["nb"]["ifaces"]["wg9"] == {"system": True} and "wg9" not in (n3["nb"].get("delete") or {}))
    _ = rec


# ── [3] rid, memos, arrivals, blocks ─────────────────────────────────────────────────────────────────────────────────
def roster():
    r = {"users": {"u1": {"name": "ann", "limits": {"c": 30}}, "u2": {"name": "bob"}}, "groups": {},
         "peers": {"p1": {"id": "p1", "user_id": "u1", "pubkey": PK[0], "psk": PK[5], "title": "phone", "p2p_port": 20001,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.2"}]},
                   "p2": {"id": "p2", "user_id": "u2", "pubkey": PK[1], "psk": PK[6], "title": "laptop", "router": True,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.3", "limits": {"d": 8}}]},
                   "p3": {"id": "p3", "user_id": "u2", "pubkey": PK[2], "psk": PK[7], "title": "tab", "disabled": True,
                          "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.4"}]}}}
    return r


def sec3():
    print("[3] rid")
    n = fleet()
    r = roster()
    check("[3] failover_rid: B → A, A → A, C → C", P.failover_rid(n, "nb") == "na" and P.failover_rid(n, "na") == "na"
          and P.failover_rid(n, "nc") == "nc")
    n2 = fleet(); n2["nb"]["failover_of"] = "gone"
    check("[3] a primary no longer in the store: B is itself", P.failover_rid(n2, "nb") == "nb")
    dA = P.desired_for_node(r, "na")
    check("[3] B's desired through rid is A's", P.desired_for_node(r, P.failover_rid(n, "nb")) == dA and dA.get("awg0"), dA)
    lA = P.limits_for_node(r, "na", dA)
    check("[3] B's limits through rid are A's", lA and P.limits_for_node(r, P.failover_rid(n, "nb"), dA) == lA, lA)
    # memos: A and B keep separate slots
    P._P2P_FWD.clear()
    sc = ("direct", ["10.99.0.0/16"])
    P.p2p_fwd_for_node(1, r, "na", sc)
    P.p2p_fwd_for_node(1, r, "na", sc, slot="nb")
    check("[3] p2p_fwd memo: one slot each", set(P._P2P_FWD) == {"na", "nb"}, set(P._P2P_FWD))
    P._P2P_ROUTERS.clear()
    P.p2p_routers_cached(1, r, "na", ())
    P.p2p_routers_cached(1, r, "na", (), slot="nb")
    check("[3] p2p_routers memo: one slot each", set(P._P2P_ROUTERS) == {"na", "nb"}, set(P._P2P_ROUTERS))
    # arrivals at C from B are named A
    nc = {"links": {"nb": {"iface": "swg_b"}, "na": {"iface": "swg_a"}}}
    plan = {"exit": [{"subnet": "10.8.0.0/24", "via_iface": "swg_b"}]}
    arr = P.p2p_arrivals(nc, plan, n)
    check("[3] an arrival from B is named A", arr == [("10.8.0.0/24", "na")], arr)
    check("[3] the router peer keeps its never-flag entry at the exit with B serving",
          P.p2p_routers_for_node(r, "nc", arr) == ["10.8.0.3/32"], P.p2p_routers_for_node(r, "nc", arr))
    check("[3] no nodes given: arrivals unchanged", P.p2p_arrivals(nc, plan) == [("10.8.0.0/24", "nb")])
    # a block category enabled on A only → enforces on B through rid
    cat = {"ads": {"id": "ads", "enabled": True, "enabled_nodes": ["na"], "default_on": False, "predefined": False,
                   "sources": [{"id": "x"}]}}
    fa = P._block_feeds(cat, {}, "na", "kernel", ["ads"])
    fb = P._block_feeds(cat, {}, P.failover_rid(n, "nb"), "kernel", ["ads"])
    check("[3] a category enabled on A is read for B as for A", fa == fb, (fa, fb))


# ── [4] the planner ──────────────────────────────────────────────────────────────────────────────────────────────────
def plan_fleet():
    n = fleet()
    n["na"]["ifaces"]["awg0"]["routing"] = []
    n["nb"]["ifaces"]["awg0"] = dict(n["na"]["ifaces"]["awg0"])
    for x, y in (("na", "nc"), ("nb", "nc")):
        n[x]["links"][y] = {"iface": "swg_%s%s" % (x, y), "subnet": "10.255.0.0/31", "address": "10.255.0.0",
                            "peer_address": "10.255.0.1"}
        n[y]["links"][x] = {"iface": "swg_%s%s" % (y, x), "subnet": "10.255.0.0/31", "address": "10.255.0.1",
                            "peer_address": "10.255.0.0"}
    return n


def plan_snaps(on_a=0, on_b=0, a_live=True):
    mk = lambda k: snap_iface(peers=[(PK[i], i < k, 0, 0) for i in range(3)])
    s = {"na": {"interfaces": {"awg0": mk(on_a)}}, "nb": {"interfaces": {"awg0": mk(on_b)}}, "nc": {"interfaces": {}}}
    for x in ("na", "nb", "nc"):
        for y, lk in fleet_links(x).items():
            s[x]["interfaces"][lk] = {"meta": {"subnet": "10.255.0.0/31", "system": True}, "peers": []}
    return s


_PF = None


def fleet_links(x):
    return {y: lk["iface"] for y, lk in _PF[x]["links"].items()}


def sec4():
    global _PF
    print("[4] the planner")
    n = plan_fleet(); _PF = n
    seen = {"na": NOW, "nb": NOW, "nc": NOW}
    s0 = plan_snaps(2, 0)
    idle = P.failover_idle(n, s0, seen, now=NOW)
    check("[4] clients on A: B idle", idle == frozenset({"nb"}), idle)
    pl = P.cascade_plan(n, s0, idle=idle)
    fa, fb = (pl.get("na") or {}).get("forward") or [], (pl.get("nb") or {}).get("forward") or []
    check("[4] the serving member forwards, the idle one does not", fa and not fb, (fa, fb))
    check("[4] the idle member carries no clash card", not (pl.get("nb") or {}).get("_clash"), (pl.get("nb") or {}).get("_clash"))
    ex = (pl.get("nc") or {}).get("exit") or []
    check("[4] one exit record at C, with A's egress_ip", len(ex) == 1 and ex[0].get("egress_ip") == "7.7.7.7", ex)
    s1 = plan_snaps(0, 2)
    idle1 = P.failover_idle(n, s1, {"na": NOW - 3600, "nb": NOW, "nc": NOW}, now=NOW)
    check("[4] A stale and clients on B: A idle", idle1 == frozenset({"na"}), idle1)
    pl1 = P.cascade_plan(n, s1, idle=idle1)
    check("[4] …and B forwards, A does not, no clash on A", (pl1.get("nb") or {}).get("forward") and not (pl1.get("na") or {}).get("forward")
          and not (pl1.get("na") or {}).get("_clash"), (pl1.get("na"), pl1.get("nb")))
    ex1 = (pl1.get("nc") or {}).get("exit") or []
    check("[4] B serving: the exit at C keeps A's egress_ip", len(ex1) == 1 and ex1[0].get("egress_ip") == "7.7.7.7", ex1)
    check("[4] A stale, no clients on B: nothing flips",
          P.failover_idle(n, plan_snaps(0, 0), {"na": NOW - 3600, "nb": NOW, "nc": NOW}, now=NOW) == frozenset({"nb"}))
    check("[4] an even split is stable (A serves)", P.failover_idle(n, plan_snaps(2, 2), seen, now=NOW) == frozenset({"nb"}))
    check("[4] no pairs: frozenset() and the plan is today's", P.failover_idle({"nc": {}}, {}, {}) == frozenset()
          and json.dumps(P.cascade_plan(n, s0), sort_keys=True, default=str) == json.dumps(P.cascade_plan(n, s0, idle=()), sort_keys=True, default=str))


# ── [5] mesh ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def sec5():
    print("[5] mesh")
    n = {"na": {"id": "na", "name": "a", "ifaces": {}, "links": {}}, "nc": {"id": "nc", "name": "c", "ifaces": {}, "links": {}},
         "nd": {"id": "nd", "name": "d", "ifaces": {}, "links": {}},
         "nb": {"id": "nb", "name": "b", "failover_of": "na", "ifaces": {}, "links": {}}}
    deps = {"panel_settings": {"mesh_mode": "full"}, "roster_path": os.path.join(TMP, "m-users.json"),
            "nodes_path": os.path.join(TMP, "m-nodes.json")}
    P.reconcile_mesh(n, {}, deps)
    pairs = {frozenset((a, b)) for a, c in n.items() for b in (c.get("links") or {})}
    check("[5] full mode, nothing asks: B linked to nobody", not any("nb" in p for p in pairs) and frozenset(("na", "nc")) in pairs, pairs)
    n["nb"]["ifaces"]["awg0"] = {"egress_mode": "forward", "egress_node": "nc"}
    P.reconcile_mesh(n, {}, deps)
    pairs = {frozenset((a, b)) for a, c in n.items() for b in (c.get("links") or {})}
    check("[5] a mirrored forward to C: B↔C linked, B↔D not", frozenset(("nb", "nc")) in pairs and frozenset(("nb", "nd")) not in pairs, pairs)
    big = {("n%d" % i): {"id": "n%d" % i} for i in range(P.MESH_AUTO_FULL_MAX)}
    big.update({("f%d" % i): {"id": "f%d" % i, "failover_of": "n%d" % i} for i in range(P.MESH_AUTO_FULL_MAX)})
    check("[5] auto: mirrors do not count", P.mesh_mode_effective({"panel_settings": {}}, big) == "full")
    nets = P._fleet_user_networks({"node_snaps": {}}, {"nb": {"failover_of": "na", "wdtt": {"wdtt0": {"wg_addr": "10.66.0.1/24"}}}})
    check("[5] _fleet_user_networks skips a failover node", nets == [], nets)


# ── [6] the ledger ───────────────────────────────────────────────────────────────────────────────────────────────────
def sec6():
    print("[6] the ledger")
    d = os.path.join(TMP, "ledger"); os.makedirs(d)
    rp = os.path.join(d, "users.json")
    json.dump(roster(), open(rp, "w"))
    L = P.TrafficLedger()
    L.start({"roster_path": rp, "panel_settings": {}}, now=NOW, writer=False)
    pairs = (("na", "nb"),)
    s = lambda rx: {"interfaces": {"awg0": {"peers": [{"public_key": PK[0], "rx_bytes": rx, "tx_bytes": rx}]}}}
    L.ingest("nb", s(1000), now=NOW, mono=1.0, pairs=pairs)
    L.ingest("nb", s(5000), now=NOW + 5, mono=6.0, pairs=pairs)
    slot = L.open.get("p1")
    got = (L.C_rx[slot], L.C_tx[slot]) if slot is not None else None
    check("[6] B's counter lands in the device's slot", got == (4000, 4000), got)
    check("[6] B's deployment is a deployment", ("nb", "awg0", "p1") in L.deploys, sorted(L.deploys))
    time.sleep(0.01)
    r2 = roster(); r2["users"]["u2"]["name"] = "bobby"
    P.roster_save(rp, r2)
    L.ingest("nb", s(9000), now=NOW + 10, mono=11.0, pairs=pairs)
    got = (L.C_rx[slot], L.C_tx[slot])
    check("[6] a roster save keeps B's baseline (no zero-credit gap)", got == (8000, 8000), got)
    m0 = L.mark
    L.ingest("na", {"interfaces": {}}, now=NOW + 15, mono=16.0, pairs=())
    check("[6] the pair cleared: the map is rebuilt without B", ("nb", "awg0", PK[0]) not in L.map and L.mark != m0, L.mark)
    check("[6] no pair: the mark is the roster's own", L.mark == P.roster_mark(rp), L.mark)
    L.ingest("na", {"interfaces": {}}, now=NOW + 20, mono=21.0, pairs=pairs)
    check("[6] the pair set again: B claimed at once", L.map.get(("nb", "awg0", PK[0])) == "p1", L.map)


# ── [7] read-only ────────────────────────────────────────────────────────────────────────────────────────────────────
def sec7():
    print("[7] read-only")
    n = fleet()
    f = lambda path, body: P.failover_ro_refusal(path, body, n)
    check("[7] an interface edit on B is refused", (f("/api/iface/update", {"node": "nb", "iface": "awg0", "mtu": 1400}) or [0])[0] == 409)
    check("[7] /api/peers/targets adding on B is refused", (f("/api/peers/targets", {"peer_id": "p1", "add": [{"node": "nb", "iface": "awg0"}]}) or [0])[0] == 409)
    check("[7] /api/peers/targets' base naming B is refused", (f("/api/peers/targets", {"peer_id": "p1", "base": [{"node": "nb", "iface": "awg0"}]}) or [0])[0] == 409)
    check("[7] add-target on B is refused", (f("/api/peers/add-target", {"peer_id": "p1", "target": {"node": "nb", "iface": "awg0"}}) or [0])[0] == 409)
    check("[7] a node edit beyond name and colour is refused", (f("/api/nodes/update", {"id": "nb", "routing_mode": "sni"}) or [0])[0] == 409)
    check("[7] a rename is allowed", f("/api/nodes/update", {"id": "nb", "name": "x", "color": None}) is None)
    for p, b in (("/api/nodes/rotate", {"id": "nb"}), ("/api/node/update", {"node": "nb"}), ("/api/nodes/failover/detach", {"id": "nb"}),
                 ("/api/connection/update", {"node": "nb"}), ("/api/iface/recreate", {"node": "nb", "iface": "awg0"}),
                 ("/api/iface/escrow/verified", {"node": "nb"})):
        check("[7] allowed: " + p, f(p, b) is None)
    check("[7] the primary is not read-only", f("/api/iface/update", {"node": "na", "iface": "awg0"}) is None)
    check("[7] a fleet with none: nothing read", P.failover_ro_refusal("/api/iface/update", {"node": "nb"}, {"nb": {}}) is None)
    check("[7] a peer id on a peer door is not a node", f("/api/peers/update", {"id": "nb"}) is None)


# ── [8] take-over and removal ────────────────────────────────────────────────────────────────────────────────────────
def to_fleet():
    n = fleet()
    n["na"]["ifaces"]["wg1"] = a_iface(public_key=KX, key_blob={"pub": KX, "ct": "c", "vault": IVK}, endpoint_host="")
    n["nb"]["ifaces"]["awg0"] = {"public_key": KA, "listen_port": 443, "_synced": {"listen_port": 443}}
    return n


def sec8():
    print("[8] take-over and removal")
    n = to_fleet()
    r = roster()
    r["peers"]["p4"] = {"id": "p4", "user_id": "u2", "pubkey": PK[3], "psk": PK[6], "title": "pc", "p2p_port": 20001,
                        "p2p_yield": ["na"], "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.9"}]}
    r["peers"]["p5"] = {"id": "p5", "user_id": "u2", "pubkey": PK[4], "psk": PK[6], "title": "nas",
                        "targets": [{"node": "na", "iface": "wg1", "ip": "10.9.0.2"}]}
    snaps = {"na": {"interfaces": {"awg0": snap_iface(), "wg1": snap_iface(key=KX)}}, "nb": {"interfaces": {"awg0": snap_iface()}}}
    owner_before = {q: o for q, o in [(e[1], e[0]) for e in P.p2p_fwd_for_node(None, r, "na", ("direct", ["10.99.0.0/16"]))]}
    moved, left = P.failover_takeover(DEPS, n, r, "na", "nb", snaps)
    check("[8] the interface B holds moves; the one it lacks stays", moved == ["awg0"] and left == ["wg1"], (moved, left))
    check("[8] targets moved A→B", all(t["node"] == "nb" for p in ("p1", "p2", "p3", "p4") for t in r["peers"][p]["targets"])
          and r["peers"]["p5"]["targets"][0]["node"] == "na")
    check("[8] p2p_yield follows (A dropped, B added)", r["peers"]["p4"].get("p2p_yield") == ["nb"], r["peers"]["p4"].get("p2p_yield"))
    owner_after = {q: o for q, o in [(e[1], e[0]) for e in P.p2p_fwd_for_node(None, r, "nb", ("direct", ["10.99.0.0/16"]))]}
    check("[8] each port keeps its holder", owner_before == owner_after and owner_before, (owner_before, owner_after))
    check("[8] A's interface dropped as a delete; B takes A's host", "awg0" not in n["na"]["ifaces"] and "awg0" in n["na"]["delete"]
          and n["nb"]["ifaces"]["awg0"].get("endpoint_host") == "vpn.example.com", (n["na"].get("delete"), n["nb"]["ifaces"]["awg0"]))
    check("[8] the flag goes", "failover_of" not in n["nb"])
    # node_remove(A) keeps every held peer
    d = os.path.join(TMP, "rm"); os.makedirs(d)
    deps = {"nodes_path": os.path.join(d, "nodes.json"), "roster_path": os.path.join(d, "users.json"), "stats_dir": d,
            "node_snaps": {"na": snaps["na"], "nb": snaps["nb"]}, "node_seen": {}, "panel_settings": {}}
    json.dump(to_fleet(), open(deps["nodes_path"], "w"))
    rr = roster()
    rr["peers"]["p5"] = {"id": "p5", "user_id": "u2", "pubkey": PK[4], "psk": PK[6], "title": "nas",
                         "targets": [{"node": "na", "iface": "wg1", "ip": "10.9.0.2"}]}
    json.dump(rr, open(deps["roster_path"], "w"))
    P.node_remove(deps, "na")
    after = json.load(open(deps["roster_path"]))
    nn = json.load(open(deps["nodes_path"]))
    check("[8] node_remove(A): the held peers are on B", all(t["node"] == "nb" for p in ("p1", "p2", "p3") for t in after["peers"][p]["targets"]),
          {k: v["targets"] for k, v in after["peers"].items()})
    check("[8] node_remove(A): the interface B lacked goes with A", "p5" not in after["peers"])
    check("[8] node_remove(A): B is an ordinary node", "na" not in nn and "failover_of" not in nn["nb"], nn.get("nb"))


# ── [9] reconcile.js ─────────────────────────────────────────────────────────────────────────────────────────────────
def sec9():
    print("[9] reconcile.js")
    if not shutil.which("node"):
        check("[9] node is installed", False)
        return
    now = NOW * 1000
    roster_ = {"users": {"u1": {"name": "ann"}}, "peers": {"p1": {"user_id": "u1", "pubkey": PK[0], "created_at": NOW - 9999,
                                                            "targets": [{"node": "na", "iface": "awg0", "ip": "10.8.0.2"}]}}}
    hs = {"public_key": PK[0], "online": True}
    cases = {
        "stale_b_online": ({"na": {"generated_at": NOW - 3600, "interfaces": {"awg0": snap_iface()}},
                            "nb": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}, "peers": [hs]}}}},
                           {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}),
        "stale_b_noif": ({"na": {"generated_at": NOW - 3600, "interfaces": {"awg0": snap_iface()}},
                          "nb": {"generated_at": NOW, "interfaces": {}}}, {"na": NOW - 3600, "nb": NOW}, {"na": "nb"}),
        "nomirror": ({"na": {"generated_at": NOW, "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}, "peers": [hs]}}}},
                     {"na": NOW}, None),
    }
    js = """
await import(%s);
const { reconcile } = await import(%s);
const cases = %s, roster = %s, now = %d;
const out = {};
for (const [k, [stats, seen, mirrors]] of Object.entries(cases)) {
  const r = reconcile(roster, stats, now, { nodeSeen: seen, nodeStaleMs: 30000, graceMs: 60000, restoreGraceMs: 0, probSince: {},
                                           ...(mirrors ? { mirrors } : {}) });
  const p = r.peers[0], t = p.targets[0];
  out[k] = { status: p.status, t: t.status, served: t.served || null, node: t.node, restorable: t.restorable, orphans: r.orphans.length,
             keys: Object.keys(t).sort() };
}
console.log(JSON.stringify(out));
""" % (json.dumps("file://" + os.path.join(HERE, "spa_env.mjs")), json.dumps("file://" + NEWR), json.dumps(cases), json.dumps(roster_), now)
    f = os.path.join(TMP, "rc.mjs"); open(f, "w").write(js)
    o = subprocess.run(["node", f], capture_output=True, text=True)
    if o.returncode:
        check("[9] reconcile ran", False, o.stderr[-800:])
        return
    out = json.loads(o.stdout)
    a = out["stale_b_online"]
    check("[9] A stale, B online: online, served by B, door names A, no orphans",
          a["status"] == "online" and a["served"] == "nb" and a["node"] == "na" and a["orphans"] == 0, a)
    b = out["stale_b_noif"]
    check("[9] A stale, B without the interface: unknown, no Restore", b["t"] == "unknown" and not b["restorable"], b)
    c = out["nomirror"]
    check("[9] no mirrors: no `served` key", "served" not in c["keys"] and c["status"] == "online", c)


# ── [10] real panels ─────────────────────────────────────────────────────────────────────────────────────────────────
def start_panel(src_path, tag, nodes, users):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    npath = os.path.join(state, "nodes.json")
    json.dump(nodes, open(npath, "w"))
    json.dump(users, open(os.path.join(state, "users.json"), "w"))
    fleetp = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": npath, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleetp, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleetp, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1"})
    PROCS.append(p)
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                raise RuntimeError("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return port, d


def req(port, path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            out, code = resp.read(), resp.status
            if resp.headers.get("Content-Encoding") == "gzip":
                out = gzip.decompress(out)
    except urllib.error.HTTPError as e:
        out, code = e.read(), e.code
    return code, json.loads(out or b"{}")


def sync(port, tok, nid, ifaces=None):
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": ifaces or {},
            "net_deps": {"limits": True}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


PROCS = []
VOLATILE = {"panel_url", "panel_url_next", "panel_local_port", "server_time", "now", "t"}


def sec10():
    print("[10] real panels")
    plain = {k: {kk: vv for kk, vv in v.items() if kk != "failover_of"} for k, v in fleet().items()}
    plain["nb"]["ifaces"] = {}
    ref = os.path.join(TMP, "ref-swg-panel-server")
    open(ref, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True, check=True).stdout)
    ports = []
    for src, tag in ((ref, "refa"), (ref, "refb"), (NEW, "new")):
        ports.append(start_panel(src, tag, plain, roster())[0])
    toks = {port: {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")} for port in ports}
    ifs = {"awg0": snap_iface(peers=[(PK[0], True, 10, 10)])}
    for nid in ("na", "nb", "nc"):
        for port in ports:
            sync(port, toks[port][nid], nid, ifs if nid == "na" else None)
    ra, rb, rn = (sync(port, toks[port]["na"], "na", ifs) for port in ports)
    vol = {k for k in set(ra) | set(rb) if json.dumps(ra.get(k), sort_keys=True) != json.dumps(rb.get(k), sort_keys=True)}
    diff = [k for k in set(ra) | set(rn) if k not in vol and json.dumps(ra.get(k), sort_keys=True) != json.dumps(rn.get(k), sort_keys=True)]
    check("[10] no failover node: the sync reply is byte-identical to %s's (but what its own instances disagree on: %s)" % (REF, sorted(vol)),
          list(rn) == list(ra) and not diff and rn.get("desired"), (diff, set(rn) ^ set(ra)))
    # with a failover node
    port, d = start_panel(NEW, "fo", fleet(), roster())
    tk = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("na", "nb", "nc")}
    vault = {"ivk_enabled": True, "ivk_pub": IVK}
    c, o = req(port, "/api/nodes/failover/preflight?node=na")
    check("[10] preflight answers", c == 200 and "refused" in (o.get("data") or {}), (c, o))
    sync(port, tk["na"], "na", ifs)
    rA = sync(port, tk["na"], "na", ifs)
    rB = sync(port, tk["nb"], "nb", ifs)
    same = {k: (json.dumps(rA.get(k), sort_keys=True) == json.dumps(rB.get(k), sort_keys=True)) for k in ("desired", "limits", "remove", "p2p_routers")}
    check("[10] B's roster-derived reply equals A's (desired, limits, remove)", all(same.values()) and rA.get("desired", {}).get("awg0"), same)
    check("[10] the limits are in B's reply", bool(rB.get("limits")), rB.get("limits"))
    rC = sync(port, tk["nc"], "nc")
    check("[10] a third node gets none of them", not (rC.get("desired") or {}).get("awg0"), rC.get("desired"))
    c, o = req(port, "/api/iface/update", {"node": "nb", "iface": "awg0", "mtu": 1400})
    check("[10] an edit on B is refused at the door", c == 409 and o.get("code") == "failover_read_only", (c, o))
    c, o = req(port, "/api/nodes/failover/detach", {"id": "nb"})
    check("[10] detach-keep with A reporting is allowed", c == 200, (c, o))
    nn = json.load(open(os.path.join(d, "state", "nodes.json")))
    check("[10] …B is an ordinary node", "failover_of" not in nn["nb"], nn["nb"])
    rB2 = sync(port, tk["nb"], "nb", ifs)
    check("[10] …and its reply no longer carries A's peers", not (rB2.get("desired") or {}).get("awg0"), rB2.get("desired"))
    _ = vault


def main():
    for name, fn in (("[1]", sec1), ("[2]", sec2), ("[3]", sec3), ("[4]", sec4), ("[5]", sec5), ("[6]", sec6), ("[7]", sec7),
                     ("[8]", sec8), ("[9]", sec9), ("[10]", sec10)):
        guarded(name, fn)
    for p in PROCS:
        p.terminate()
    for p in PROCS:
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
    shutil.rmtree(TMP, ignore_errors=True)
    if PLANT:
        print("plant %s: %s" % (PLANT, "RED (caught)" if FAILS else "GREEN — NOT caught"))
        sys.exit(0 if FAILS else 1)
    print("FAIL: %d" % len(FAILS) if FAILS else "PASS")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
