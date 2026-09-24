#!/usr/bin/env python3
"""What the panel tells a node to block, per interface (`_resolve_iface_blocks`).

  1. a list's tier is the LIST's provider's, not its category's kind — a custom category (always saved as "content")
     holding an IP list puts it in the IP union, and a domain list in an "ip" category still reaches the domain union
  2. domain unions are skipped where the node cannot fill them (IP-only, Kernel SNI); IP unions ship in every mode
  3. a category switched off for this node (enabled_nodes) enforces nothing here, and switching it back restores it
  4. identical feed sets share one union; a disabled provider's lists are left out

Run:  python3 tests/block_plan_selftest.py   (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
spec = importlib.util.spec_from_loader("swgpanel", loader); m = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(m)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

PS = {"block_catalog": {"providers": {"stevenblack": False},
      "categories": {
        "cl_mix":  {"label": "Mix", "kind": "content", "enabled_nodes": ["n1"],
                    "sources": [{"provider": "oisd", "list": "big"}, {"provider": "firehol", "list": "firehol_level1"}]},
        "malware_ip": {"enabled_nodes": ["n1"], "sources": [{"provider": "firehol", "list": "firehol_level3"},
                                                            {"provider": "hagezi", "list": "tif"}]},
        "ads":     {"enabled_nodes": ["n2"]},
        "adult":   {"enabled_nodes": ["n1"], "sources": [{"provider": "stevenblack", "list": "alternates/porn/hosts"},
                                                         {"provider": "hagezi", "list": "nsfw"}]}}}}
NODE = {"ifaces": {"wg0": {"block": ["cl_mix", "malware_ip", "ads", "adult", "torrents"]},
                   "wg1": {"block": ["cl_mix", "malware_ip", "adult"]}}}
SNAP = {"interfaces": {"wg0": {"meta": {"subnet": "10.0.0.0/24"}}, "wg1": {"meta": {"subnet": "10.0.1.0/24"}}}}

def plan(mode, nid="n1", ps=PS):
    m._BLKU_REG.clear()
    ents, srcs, mech = m._resolve_iface_blocks(NODE, SNAP, ps, mode, nid)
    per = {}
    for e in ents:
        per.setdefault(e["subnet"], {})[srcs[e["category"]]] = sorted(m._BLKU_REG[e["category"]])
    return per, mech, ents

print("1. the tier is the list's")
per, mech, ents = plan("sni")
w0 = per.get("10.0.0.0/24", {})
check("the IP list of a custom (content) category is in the IP union",
      "blk:firehol:firehol_level1" in w0.get("ip", []), w0)
check("…and not in the domain union", "blk:firehol:firehol_level1" not in w0.get("host", []), w0)
check("a domain list in an ip-kind category is in the domain union", "blk:hagezi:tif" in w0.get("host", []), w0)
check("every entry is a block", all(e["action"] == "block" for e in ents))

print("2. domain unions only where the node can fill them")
for mode in ("kernel", "sni_kernel"):
    per_k, _, _ = plan(mode)
    check("%s: no domain union" % mode, all("host" not in v for v in per_k.values()), per_k)
    check("%s: the IP union still ships" % mode, "blk:firehol:firehol_level1" in per_k.get("10.0.0.0/24", {}).get("ip", []), per_k)
per_f, _, _ = plan("forcedns")
check("forcedns: domain union ships", "blk:oisd:big" in per_f.get("10.0.0.0/24", {}).get("host", []), per_f)

print("3. availability per node")
check("a category enabled only on n2 blocks nothing on n1", all("blk:hagezi:light" not in l for v in per.values() for l in v.values()), per)
per2, mech2, _ = plan("sni", nid="n2")
check("on n2 that category enforces", "blk:hagezi:light" in per2.get("10.0.0.0/24", {}).get("host", []), per2)
check("on n2 the categories enabled only on n1 do not", all("blk:oisd:big" not in l for v in per2.values() for l in v.values()), per2)
check("mechanisms are not gated by availability", mech2.get("10.0.0.0/24") == ["torrents"], mech2)

print("4. sharing + disabled providers")
check("identical feed sets share one union", per["10.0.0.0/24"] == per["10.0.1.0/24"] and
      len({e["category"] for e in ents}) == 2, ents)
check("a disabled provider's list is left out", all("blk:stevenblack:alternates/porn/hosts" not in l for v in per.values() for l in v.values()))
check("…its category's other list is not", "blk:hagezi:nsfw" in w0.get("host", []), w0)

print("5. coverage counts exactly what the datapath enforces")
NODE2 = {"ifaces": dict(NODE["ifaces"], wg9={"system": True, "block": ["malware_ip"]}),
         "wdtt": {"w1": {"wg_addr": "10.9.0.1/24", "block": ["adult"]}}, "csqtt": {"c1": {"tun_addr": "10.8.0.1/24", "block": ["cl_mix"]}}}
SNAP2 = {"interfaces": SNAP["interfaces"]}
bc, bpe = m.block_catalog(PS), m.block_providers_enabled(PS)
for mode in ("sni", "kernel"):
    m._BLKU_REG.clear()
    ents, srcs, _ = m._resolve_iface_blocks(NODE2, SNAP2, PS, mode, "n1")
    datapath = {sid for e in ents for sid in m._BLKU_REG[e["category"]]}
    counted = set()
    for b in m._node_block_lists(NODE2):
        feeds, _ = m._block_feeds(bc, bpe, "n1", mode, m._validate_block(b, PS))
        counted |= {sid for pairs in feeds.values() for sid, _t in pairs}
    check("%s: coverage lists == datapath lists (WDTT + csqtt included, system links not)" % mode, counted == datapath, (counted ^ datapath))
check("a system (mesh) interface's block[] is not walked", all(b != ["malware_ip"] for b in m._node_block_lists({"ifaces": {"s": {"system": True, "block": ["malware_ip"]}}})))
src = open(SERVER).read()
i = src.index('if method == "GET" and path == "/api/block-stats":'); blk = src[i:i + 6000]
check("/api/block-stats coverage is computed through _block_feeds", "_block_feeds(" in blk and "_node_block_lists(" in blk)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
