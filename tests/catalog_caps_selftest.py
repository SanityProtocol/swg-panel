#!/usr/bin/env python3
"""Self-test: a node's category caps when the panel holds NO provider catalog (q189 D12-OBS-1 / LC DEB-1).

The provider catalog is built from api.github.com — unauthenticated, 60 requests an hour per address, and unreachable for many
panels where this product is used. Without catalog-index.json the sync used to omit the WHOLE `cat_caps` key as soon as any
category in a node's plan was outside SMART_CAPS and the block sources — and the catch-all `all` of every Smart interface (or
any custom rule) is one. A fresh or restarted node then had no host cap for its block union, its pulled `.doms` never entered
the name map, and Hybrid SNI (and Force-DNS, which reads the same `_host_cats`) blocked nothing — measured on Debian 13: the
tracker answered 200, "swg-sni: loaded 0 domains" — while the Overview counted 54 269 names as filtering.

  [1] sync_cat_caps, the real function: the measured plan (a block union + the catch-all + a custom rule, no catalog) gets the
      union's host cap and nothing to keep; curated caps ride along; a provider list the panel already holds is sent with the
      tiers it holds; a provider category it cannot look up is named in `cat_caps_keep` to a node that keeps caps for it, and
      to a node that would clear them the key is omitted as before (nothing it holds is lost); with a catalog, nothing changes
  [2] end to end, a real panel with no catalog and no way to fetch one: a node on Hybrid SNI whose interface blocks "Ads &
      Trackers" (its list already held) behind a custom routing rule — its sync carries the union's host cap, and the list
      in its manifest; the same on Force-DNS
  [3] the node half, swg-noded's own _cat_caps_take: a partial dict keeps the caps of the categories named in `cat_caps_keep`
      and replaces the rest; an older panel's full dict (no keep) replaces as before; an absent key keeps everything; a name
      the node never had invents nothing; the node says it keeps them (`caps_keep: 1` in smart_status) and the panel reads that
      (node_keeps_caps) — an older node's report has no flag, so it is sent no partial dict (mixed versions safe both ways)

Hermetic (the panel's fetches go to a dead proxy). Run: python3 tests/catalog_caps_selftest.py   (0 = pass)
     --perturb        the old rule (anything outside SMART_CAPS and the block sources withholds every cap) → RED
     --perturb-node   the node ignores `cat_caps_keep` (clears every cap a partial dict leaves out) → RED in [3]
     --perturb-cov    the Overview counts a node's block lists though its caps were withheld → RED in [2b]
"""
import http.client, importlib.machinery, importlib.util, json, os, re, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_NODE = "--perturb-node" in sys.argv
PERTURB_COV = "--perturb-cov" in sys.argv
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="catcaps-")
SRV = SERVER
if PERTURB:   # the rule before the fix: a plan category outside SMART_CAPS and the block sources made the caps unresolvable
    src = open(SERVER, encoding="utf-8").read()
    a = '            if c in caps or ":" not in c or c.startswith(("blk:", "blku:")):\n'
    if src.count(a) != 1:
        print("PERTURB FAILED — the anchor is not in the panel exactly once"); sys.exit(1)
    SRV = os.path.join(TMP, "swg-panel-server.perturbed")
    open(SRV, "w", encoding="utf-8").write(src.replace(a, '            if c in caps:\n'))
    print("(perturbed: the catch-all and custom rules count as catalog-dependent again — this run must FAIL)")
if PERTURB_COV:   # the coverage before the fix: what is configured, whatever the node was sent
    src = open(SERVER, encoding="utf-8").read()
    a = "                if _CAPS_WITHHELD.get(_nid):            # its sync carried no caps: these lists filter nothing there yet\n"
    if src.count(a) != 1:
        print("PERTURB FAILED — the coverage anchor is not in the panel exactly once"); sys.exit(1)
    SRV = os.path.join(TMP, "swg-panel-server.perturbed-cov")
    open(SRV, "w", encoding="utf-8").write(src.replace(a, "                if False:\n"))

loader = importlib.machinery.SourceFileLoader("swgpanel_catcaps", SRV)
spec = importlib.util.spec_from_loader("swgpanel_catcaps", loader)
M = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(M)
except SystemExit:
    pass

# ── [1] the real function ─────────────────────────────────────────────────────────────────────────────────────────
print("[1] sync_cat_caps with no catalog")
LD = os.path.join(TMP, "lists"); os.makedirs(LD)
M.LIST_DIR = LD; M._LIST_META.clear()
def hold(cat, tier, n=3):
    open(M._list_path(cat, tier), "w").write("\n".join("d%d.example" % i for i in range(n)) + "\n")
    json.dump({"v": "t1", "n": n, "at": int(time.time())}, open(M._list_metapath(cat, tier), "w"))
U = "blku:host:4fe45fc4b8fa"
cur = next(c for c in M.SMART_CAPS if c != "all")
old, new = {}, {"smartroute": {"caps_keep": 1}}
if not hasattr(M, "sync_cat_caps"):   # the tree before the fix decided inline — [1] cannot run there; [2] says what it did
    check("[1] sync_cat_caps exists (the caps decision as one function)", False, "missing")
    M.sync_cat_caps = lambda *a: ("missing", "missing")
caps, keep = M.sync_cat_caps({U, "all", "custom_1a2b3c4d"}, {}, False, {U: "host"}, old)
check("[1] the measured plan (block union + catch-all + custom rule): the union's host cap is sent, nothing waits",
      caps == {U: {"host": True}} and keep == [], [caps, keep])
caps, keep = M.sync_cat_caps({U, "all", cur}, {}, False, {U: "host"}, old)
check("[1] a curated category rides along with its caps", caps == {U: {"host": True}, cur: M.SMART_CAPS[cur]} and keep == [], [caps, keep])
hold("mcx:geosite-test", "host")
caps, keep = M.sync_cat_caps({U, "all", "mcx:geosite-test"}, {}, False, {U: "host"}, old)
check("[1] a provider list the panel already holds is sent with the tier it holds", isinstance(caps, dict) and caps.get("mcx:geosite-test") == {"host": True} and keep == [],
      [caps, keep])
caps, keep = M.sync_cat_caps({U, "all", "mcx:geosite-unheld"}, {}, False, {U: "host"}, new)
check("[1] a provider category the panel cannot look up waits — named in cat_caps_keep to a node that keeps caps for it",
      caps == {U: {"host": True}} and keep == ["mcx:geosite-unheld"], [caps, keep])
caps, keep = M.sync_cat_caps({U, "all", "mcx:geosite-unheld"}, {}, False, {U: "host"}, old)
check("[1] …and to a node that would clear its caps, the key is omitted as before (it keeps what it has)", caps is None and keep == [], [caps, keep])
caps, keep = M.sync_cat_caps({U, "all", "mcx:x"}, {"mcx:x": {"ip": True, "host": True}}, True, {U: "host"}, old)
check("[1] with a catalog nothing changes: the provider's caps come from it, nothing waits",
      caps == {U: {"host": True}, "mcx:x": {"ip": True, "host": True}} and keep == [], [caps, keep])

# ── [2] end to end, a real panel with no catalog ───────────────────────────────────────────────────────────────────
print("\n[2] end to end: a real panel with no catalog")
D = os.path.join(TMP, "panel")
for d in ("state", "conf", "stats"):
    os.makedirs(os.path.join(D, d))
json.dump({"nodes_path": D + "/state/nodes.json", "roster_path": D + "/state/users.json",
           "panel_settings_path": D + "/state/panel-settings.json", "config_dir": D + "/conf", "stats_dir": D + "/stats",
           "store_configs": False}, open(os.path.join(D, "fleet.json"), "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
env = dict(os.environ, SWG_PANEL_FLEET=D + "/fleet.json", SWG_PANEL_WEB=ROOT, SWG_PANEL_HOST="127.0.0.1", SWG_PANEL_PORT=str(PORT),
           SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="",
           HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9",
           NO_PROXY="", no_proxy="")   # every fetch the panel makes fails at once: no catalog, ever
def call(method, path, body=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse(); raw = r.read(); c.close()
    try:
        return r.status, json.loads(raw or b"{}")
    except ValueError:
        return r.status, {"raw": raw[:200]}
def find(o, key):
    """the first value under `key` anywhere in a reply"""
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = find(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v, key)
            if r is not None:
                return r
    return None

srv = subprocess.Popen([sys.executable, SRV], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(150):
        try:
            if call("GET", "/api/state")[0] == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        sys.exit("the panel never came up: " + srv.stderr.read(2000).decode("utf-8", "replace"))
    st, o = call("POST", "/api/nodes/create", {"name": "cc-node", "endpoint_host": "203.0.113.20"})
    NID, TOK = o["data"]["id"], o["data"]["token"]
    # "Ads & Trackers" enabled on this node; its feed's list already held by the panel (as on a panel that fetched it once)
    call("POST", "/api/block-catalog/save", {"categories": {"ads": {"enabled_nodes": [NID]}}})
    cat = M.block_catalog({"block_catalog": {"categories": {"ads": {"enabled_nodes": [NID]}}}})
    feeds, _m = M._block_feeds(cat, M.block_providers_enabled({}), NID, "sni", ["ads"])
    members = [sid for pairs in feeds.values() for sid, tier in pairs if tier == "host"]
    check("[2] the fixture: Ads & Trackers has a domain feed on this node", bool(members), feeds)
    os.makedirs(D + "/state/lists", exist_ok=True)
    M.LIST_DIR = D + "/state/lists"
    for sid in members:
        hold(sid, "host", 54)
    snap = lambda: {"hostname": "cc-node", "generated_at": int(time.time()), "noded_version": "1.8.9-beta", "kind": "baremetal",
                    "node_ips": ["203.0.113.20"], "node_ifaces": ["eth0"], "turn_proxies": [],
                    "interfaces": {"awg0": {"peers": [], "meta": {"listen_port": 51820, "address": "10.70.0.1/24", "subnet": "10.70.0.0/24",
                                                                  "type": "awg", "public_key": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
                                                                  "awg_params": {"Jc": 4, "Jmin": 40, "Jmax": 70}}}}}
    call("POST", "/api/node/sync", {"snapshot": snap()}, TOK)
    for mode in ("sni", "forcedns"):
        call("POST", "/api/nodes/update", {"id": NID, "routing_mode": mode})
        st, r = call("POST", "/api/iface/update", {"node": NID, "iface": "awg0", "block": ["ads"], "egress_mode": "smart", "routing_v": 2,
                                                   "routing": [{"category": "custom", "action": "block", "targets": "tracker.example"}]})
        check("[2] %s: the interface blocks Ads & Trackers behind a custom routing rule" % mode, st == 200, r)
        st, r = call("POST", "/api/node/sync", {"snapshot": snap()}, TOK)
        st, r = call("POST", "/api/node/sync", {"snapshot": snap()}, TOK)   # the union is built on the first; served on the next
        caps, cats, man = find(r, "cat_caps"), find(r, "categories") or [], find(r, "list_manifest") or {}
        unions = [c for c in cats if c.startswith("blku:host:")]
        check("[2] %s: the plan holds the block union and a category outside SMART_CAPS (the custom rule)" % mode,
              bool(unions) and any(c.startswith("custom") or c == "all" for c in cats), cats)
        check("[2] %s: the sync carries cat_caps with the union's host cap — no catalog, and none needed" % mode,
              isinstance(caps, dict) and all((caps.get(u) or {}).get("host") for u in unions) and bool(unions), caps)
        check("[2] %s: …and the union in its list manifest, so the node pulls the names it blocks" % mode,
              all(u in man for u in unions) and bool(unions), list(man))
    # [2b] a provider routing list the panel cannot look up, beside the block list: an older node is sent no caps (its own
    # would be stripped) — so the Overview must not count its block list as filtering; a node that keeps caps gets the rest
    st, r = call("POST", "/api/iface/update", {"node": NID, "iface": "awg0", "block": ["ads"], "egress_mode": "smart", "routing_v": 2,
                                               "routing": [{"category": "mcx:geosite-unheld", "action": "block"},
                                                           {"category": "custom", "action": "block", "targets": "tracker.example"}]})
    check("[2b] the interface also routes a provider list the panel cannot look up", st == 200, r)
    for label, sr in (("an older node (no caps_keep)", None), ("a node that keeps caps", {"caps_keep": 1})):
        sn = snap()
        if sr:
            sn["smartroute"] = sr
        call("POST", "/api/node/sync", {"snapshot": sn}, TOK)
        st, r = call("POST", "/api/node/sync", {"snapshot": sn}, TOK)
        caps, keep, cats = find(r, "cat_caps"), find(r, "cat_caps_keep"), find(r, "categories") or []
        st, bs = call("GET", "/api/block-stats")
        cov = find(bs, "coverage") or {}
        waiting = cov.get("waiting") or []
        if sr is None:
            check("[2b] %s: no caps are sent (its own would be stripped)" % label, caps is None and "mcx:geosite-unheld" in cats, [caps, cats])
            check("[2b] %s: the Overview does not count its block list as filtering, and says it is waiting there" % label,
                  not cov.get("domains") and any(w.get("label") == "Ads & Trackers" and "cc-node" in (w.get("nodes") or []) for w in waiting), cov)
        else:
            check("[2b] %s: the rest is sent, the provider list named in cat_caps_keep" % label,
                  isinstance(caps, dict) and any(k.startswith("blku:host:") for k in caps) and keep == ["mcx:geosite-unheld"], [caps, keep])
            check("[2b] %s: the Overview counts its block list again, nothing waiting" % label, cov.get("domains") and not waiting, cov)
    check("[2] the panel never got a catalog (the dead proxy held)", not os.path.exists(D + "/state/catalog-index.json"))
finally:
    srv.terminate()
    try:
        srv.wait(5)
    except Exception:
        srv.kill()

# ── [3] the node half ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the node keeps the caps of the categories the panel names in cat_caps_keep")
NSRC = open(NODED, encoding="utf-8").read()
NP = NODED
if PERTURB_NODE:
    a = "    _CAT_CAPS.update(kept)\n"
    if NSRC.count(a) != 1:
        print("PERTURB FAILED — the node anchor is not there exactly once"); sys.exit(1)
    NP = os.path.join(TMP, "swg-noded.perturbed")
    open(NP, "w", encoding="utf-8").write(NSRC.replace(a, "    pass\n"))
nl = importlib.machinery.SourceFileLoader("swgnoded_catcaps", NP)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_catcaps", nl))
try:
    nl.exec_module(N)
except SystemExit:
    pass
if not hasattr(N, "_cat_caps_take"):
    check("[3] swg-noded has _cat_caps_take", False, "missing")
else:
    P1, P2, B = "mcx:geosite-a", "mcx:geosite-b", "blku:host:aaaa"
    N._CAT_CAPS.clear(); N._cat_caps_take({"cat_caps": {P1: {"host": True}, P2: {"ip": True, "host": True}}})   # from a catalog, once
    N._cat_caps_take({"cat_caps": {B: {"host": True}}, "cat_caps_keep": [P1, P2]})                               # the panel lost it
    check("[3] a partial dict keeps the named categories' caps and takes the rest",
          N._CAT_CAPS == {B: {"host": True}, P1: {"host": True}, P2: {"ip": True, "host": True}}, N._CAT_CAPS)
    N._cat_caps_take({"cat_caps": {B: {"host": True}, P1: {"ip": True}}})                                           # an older panel
    check("[3] an older panel's full dict (no keep) replaces as before", N._CAT_CAPS == {B: {"host": True}, P1: {"ip": True}}, N._CAT_CAPS)
    N._cat_caps_take({})
    check("[3] an absent key keeps everything", N._CAT_CAPS == {B: {"host": True}, P1: {"ip": True}}, N._CAT_CAPS)
    N._cat_caps_take({"cat_caps": {B: {"host": True}}, "cat_caps_keep": ["mcx:never-had", 7]})
    check("[3] a name the node never had (or no name at all) invents nothing", N._CAT_CAPS == {B: {"host": True}}, N._CAT_CAPS)
    check("[3] the node says it keeps them: smart_status's base carries caps_keep 1",
          re.search(r'"arr": 1,\s+#[^\n]*\n\s+"caps_keep": 1\}', NSRC) is not None, "")
    check("[3] …and the panel reads it: a report with the flag may get a partial dict, an older node's never does",
          M.node_keeps_caps({"smartroute": {"caps_keep": 1}}) and not M.node_keeps_caps({"smartroute": {"arr": 1}})
          and not M.node_keeps_caps({"smartroute": "x"}) and not M.node_keeps_caps({}), "")

print()
if PERTURB or PERTURB_NODE or PERTURB_COV:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS else "PERTURB FAILED — the undone fix passed every check")
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS")
