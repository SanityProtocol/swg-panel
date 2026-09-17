#!/usr/bin/env python3
"""Self-test: a node whose mesh links are named with ANOTHER prefix still closes its LAN to them and still measures them.

The panel lets a fleet (Settings → reserved `iface_prefix`) or a node (`mesh_prefix`) name its links other than `swg_`.
Two node-side behaviours matched the name only. Measured on a NixOS VM with the node's LAN closed and its links renamed
`mx_…` (1.8.7 qualification PART 4, A7):
  · swg_lan dropped `iifname "swg_*"` only — three pings sent over the link to a LAN address were forwarded onto the LAN
    (captured on the bridge) while the drop counter stood still; with `swg_` links the same pings were dropped (3/3)
  · the mesh probe measured `swg_*` only — the renamed node's `mesh_health` went empty while its peer kept measuring 2.2 ms

  [1] the LAN ruleset names the node's own mesh links alongside the `swg_*` wildcard, and never lists a `swg_` link twice
  [2] a name that could break out of its quotes never reaches nft
  [3] the block is rebuilt when the node's mesh links change (they are part of what the table was built from)
  [4] the sync loop hands reconcile_lan_block the node's mesh links, judged by `_relay_links` (the node's own test)
  [5] the probe measures a link with another prefix — a /31 link the node judges mesh — and still every `swg_*` link,
      and not a client interface

Hermetic. Run: python3 tests/mesh_prefix_selftest.py      (0 = pass)
     --perturb-lan     the ruleset ignores `mesh` again           → RED on [1] [3]
     --perturb-probe   the probe goes back to the prefix alone    → RED on [5]
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURBS = {
    "--perturb-lan": ('    if other:\n        L.append("    iifname { %s } ip daddr %s counter drop" % (", ".join(\'"%s"\' % m for m in other), dst))\n',
                      '    if False:\n        pass\n'),
    "--perturb-probe": ('    return sorted(n for n in (node_cfg.get("interfaces") or {}) if n.startswith("swg_") or n in links)\n',
                        '    return sorted(n for n in (node_cfg.get("interfaces") or {}) if n.startswith("swg_"))\n'),
}
PERTURB = [a for a in sys.argv[1:] if a in PERTURBS]

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED).read()
REAL_SRC = src
for flag in PERTURB:
    old, new = PERTURBS[flag]
    if src.count(old) != 1:
        print("PERTURB FAILED — anchor for %s is not in swg-noded exactly once" % flag)
        sys.exit(1)
    src = src.replace(old, new)
path = os.path.join(tempfile.mkdtemp(), "swg-noded")
open(path, "w").write(src)
ld = importlib.machinery.SourceFileLoader("noded_meshprefix", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_meshprefix", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
CP = N.subprocess.CompletedProcess
NETS = ["10.77.40.0/24"]

print("[1] the LAN ruleset names the node's own mesh links")
rs = N._lan_ruleset(NETS, ["awg0"], ("mx_2e52acf5", "swg_aae71d3e"))
check("the swg_* wildcard stays", 'iifname "swg_*" ip daddr { 10.77.40.0/24 } counter drop' in rs, rs)
check("⚠️ a link named mx_… is dropped too", 'iifname { "mx_2e52acf5" } ip daddr { 10.77.40.0/24 } counter drop' in rs, rs)
check("a swg_ link is not listed a second time", rs.count("swg_aae71d3e") == 0, rs)
check("no mesh links → exactly the ruleset it was", N._lan_ruleset(NETS, ["awg0"]) == N._lan_ruleset(NETS, ["awg0"], ()), "")

print("\n[2] names that could break out of their quotes")
rs = N._lan_ruleset(NETS, [], ('mx_"x', "mx_ok"))
check('mx_"x never reaches nft, mx_ok does', 'mx_"x' not in rs and '"mx_ok"' in rs, rs)

print("\n[3] rebuilt when the links change")
LOADED, CALLS = [""], []
def run(a, input_text=None, timeout=20):
    CALLS.append(list(a))
    if a[:2] == ["nft", "-f"]:
        LOADED[0] = input_text or ""
        return CP(a, 0, "", "")
    if a[:3] == ["nft", "list", "table"]:
        return CP(a, 0 if LOADED[0] else 1, LOADED[0], "")
    return CP(a, 0, "", "")
N.run = run
N._node_lan_nets = lambda *a: list(NETS)
N._CLIENT_DEVS["list"] = ["awg0"]
N._LAN.update(probed=False, installed=False, sig=None, status=None)
res = {"changed": 0, "errors": []}
N.reconcile_lan_block(True, res, owned=set(), mesh=("swg_2ddf745d",))
loads = lambda: [c for c in CALLS if c[:2] == ["nft", "-f"]]
check("installed", len(loads()) == 1 and 'iifname "swg_*"' in LOADED[0], CALLS)
N.reconcile_lan_block(True, res, owned=set(), mesh=("swg_2ddf745d",))
check("steady: not rebuilt", len(loads()) == 1, CALLS)
N.reconcile_lan_block(True, res, owned=set(), mesh=("mx_2e52acf5",))
check("⚠️ the links were renamed → rebuilt, naming the new link", len(loads()) == 2 and '"mx_2e52acf5"' in LOADED[0], LOADED[0])

print("\n[4] the sync loop passes the node's own mesh judgement")
check("reconcile_lan_block(..., mesh=_relay_links(node_cfg))",
      re.search(r"reconcile_lan_block\(reply\.get\(\"lan_share\"\) is False, nr, owned=_own_tunnel_devs\(node_cfg\),\s*"
                r"mesh=_relay_links\(node_cfg\)\)", REAL_SRC) is not None)

print("\n[5] the probe measures what the node judges mesh")
cfg = {"interfaces": {"mx_2e52acf5": {"conf": "/x/mx_2e52acf5.conf"}, "swg_aae71d3e": {"conf": "/x/swg_aae71d3e.conf"},
                      "awg0": {"conf": "/x/awg0.conf"}}}
SUBS = {"mx_2e52acf5": "10.255.0.0/31", "swg_aae71d3e": "10.255.0.6/31", "awg0": "10.60.0.0/24"}
N._iface_subnet = lambda node_cfg, n: SUBS.get(n, "")
N._RELAY_LINKS.update(key=None, links=())
got = N._mesh_probe_ifaces(cfg)
check("⚠️ mx_2e52acf5 is probed", "mx_2e52acf5" in got, got)
check("swg_aae71d3e still is, awg0 is not", "swg_aae71d3e" in got and "awg0" not in got, got)

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — %s undone and every check still passed" % PERTURB)
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
