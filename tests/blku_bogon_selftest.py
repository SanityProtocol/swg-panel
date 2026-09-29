#!/usr/bin/env python3
"""Self-test — a block IP union never holds the ranges a client's own peers, LAN and tunnel live in (1.8.8 qualification §K).

FireHOL level1 (the malware_ip category's source) lists 0/8, 10/8, 100.64/10, 127/8, 172.16/12 and 192.168/16. The panel put
them into the union, and a node drops the union by destination for its clients: measured on msk-main (2026-09-28), with
malware_ip on an interface a client could reach neither its peers nor the LAN behind its gateway (the union's counter +20).

Real functions: the panel's `_resolve_iface_blocks` (registers the union), `list_ensure` (resolves the member through the
real IP normaliser from a file:// feed) and `_blku_store` (builds the union).

  [1] the union holds the feed's public networks and none of the never-routable ranges
  [2] a network AROUND a never-routable range keeps the rest of itself (96.0.0.0/4 minus 100.64/10), one INSIDE goes
  [3] an ip union built with the cut has a NEW name (a node loads a new list at once, a changed one only in its nightly
      window); a host union keeps its name

Run: python3 tests/blku_bogon_selftest.py      --plant nocut | norename   (exit 0 when caught)
"""
import importlib.machinery, importlib.util, ipaddress, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"nocut": ("[1] [2]", "        items = [str(n) for n in ipaddress.collapse_addresses(_blku_public(nets))]",
                    "        items = [str(n) for n in ipaddress.collapse_addresses(nets)]"),
          "norename": ("[3]", '(("nb;" if tier == "ip" else "") + ";".join(', '(";".join(')}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="blku-bogon-")
path = os.path.abspath(SERVER)
if PLANT:
    _s, old, new = PLANTS[PLANT]
    src = open(path).read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    path = os.path.join(TMP, "planted-server.py")
    open(path, "w").write(src.replace(old, new, 1))
loader = importlib.machinery.SourceFileLoader("swgpanel_bogon", path)
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_bogon", loader))
try:
    loader.exec_module(m)
except SystemExit:
    pass


def settle(t=10):
    t0 = time.time()
    while time.time() - t0 < t:
        with m._LIST_LOCK:
            if not m._LIST_INFLIGHT:
                return True
        time.sleep(0.05)
    return False


m.LIST_DIR = os.path.join(TMP, "lists")
feeds = os.path.join(TMP, "feeds"); os.makedirs(feeds)
m._http_retry = lambda fn, **k: fn()
m.BLOCK_PROVIDERS["ti"] = {"label": "T", "tier": "ip", "raw": "file://" + feeds + "/{id}.txt"}
NEVER = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
         "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4"]
PUBLIC = ["5.188.10.0/24", "45.9.20.0/22", "185.220.101.1/32"]
open(os.path.join(feeds, "lvl1.txt"), "w").write("# FireHOL-like\n" + "\n".join(NEVER + PUBLIC + ["96.0.0.0/4", "10.20.0.0/16"]) + "\n")
PS = {"block_catalog": {"categories": {"mw": {"label": "M", "kind": "ip", "enabled_nodes": ["n1"],
      "sources": [{"provider": "ti", "list": "lvl1"}]}}}}
NODE = {"ifaces": {"wg0": {"block": ["mw"]}}}
SNAP = {"interfaces": {"wg0": {"meta": {"subnet": "10.0.0.0/24"}}}}
m._resolve_iface_blocks(NODE, SNAP, PS, "sni", "n1"); settle()
m.list_ensure("blk:ti:lvl1", "ip"); settle()
ents = m._resolve_iface_blocks(NODE, SNAP, PS, "sni", "n1")[0]; settle()
cat = [e["category"] for e in ents if str(e["category"]).startswith("blku:ip:")]
meta, st = m._blku_store(cat[0], "ip") if cat else (None, "no union")
nets = [ipaddress.ip_network(l) for l in (open(m._list_path(cat[0], "ip")).read().split() if cat and st == "ok" else [])]

SECTION[0] = "[1]"
print("\n[1] public in, never-routable out")
check("the union was built from the feed", st == "ok" and nets, (cat, st, meta))
for p in PUBLIC:
    check("keeps %s" % p, any(ipaddress.ip_network(p).subnet_of(n) for n in nets), [str(n) for n in nets])
for b in NEVER:
    bad = [str(n) for n in nets if n.overlaps(ipaddress.ip_network(b))]
    check("holds nothing of %s" % b, not bad, bad)
probe = ["10.141.0.3", "192.168.141.10", "100.64.0.1", "127.0.0.1", "172.16.0.1"]
check("a client's peer, its LAN, CGNAT, loopback: none in the union",
      not [a for a in probe if any(ipaddress.ip_address(a) in n for n in nets)], [a for a in probe if any(ipaddress.ip_address(a) in n for n in nets)])

SECTION[0] = "[2]"
print("\n[2] a network around one keeps the rest; one inside goes")
check("96.0.0.0/4's public part stays (100.0.0.1, 104.16.0.1 blocked)",
      all(any(ipaddress.ip_address(a) in n for n in nets) for a in ("100.0.0.1", "104.16.0.1", "111.1.1.1")))
check("…its 100.64/10 does not", not any(ipaddress.ip_address("100.100.0.1") in n for n in nets))
check("10.20.0.0/16 (inside 10/8) is gone", not any(ipaddress.ip_address("10.20.1.1") in n for n in nets))

SECTION[0] = "[3]"
print("\n[3] a new name for an ip union, the same for a host union")
import hashlib
old_key = lambda tier, ids: "blku:" + tier + ":" + hashlib.sha1(";".join(sorted(set(ids))).encode()).hexdigest()[:12]
check("the ip union's name is not the one it had before the cut", m._blku_key("ip", ["blk:ti:lvl1"]) != old_key("ip", ["blk:ti:lvl1"]),
      m._blku_key("ip", ["blk:ti:lvl1"]))
check("…and the plan names it that way", cat and cat[0] == m._blku_key("ip", ["blk:ti:lvl1"]), cat)
check("a host union keeps its name (no reload for lists the cut never touched)",
      m._blku_key("host", ["blk:tp:a", "blk:tp:b"]) == old_key("host", ["blk:tp:a", "blk:tp:b"]))

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
