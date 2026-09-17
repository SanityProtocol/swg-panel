#!/usr/bin/env python3
"""Self-test: a node's declared firewall range — what the panel says about a port outside it, per kind of interface.

A NixOS node declares `services.swg-node.udpPortRanges`; the node reports it (`udp_ports`) and the panel raises a node issue for
every interface listening outside it, because the firewall is fixed at build time while the panel picks ports at run time.
Measured on a fresh NixOS 26.05 node that followed nix/README's example range (1.8.7 qualification PART 4, A1): its own
MESH LINK (port 9999, from the system mesh band) raised "clients cannot reach it until the range covers that port, or the
interface moves inside it" — wrong on both counts for a link no client dials and nobody moves. What a closed mesh port does
cost is the other node: it cannot open the link to this one.

  [1] a user interface outside the range: the interface sentence (clients cannot reach it)
  [2] a mesh link outside the range: the mesh sentence (other nodes cannot open the link), never the client one
  [3] inside the range — the mesh band declared — nothing; no range declared — nothing (the module warns at build time)
  [4] both sentences are translated (js/lang/ru.js carries each key)

Hermetic. Run: python3 tests/firewall_range_issue_selftest.py      (0 = pass)
     --perturb   drops the mesh branch (every outside port gets the interface sentence again) and expects RED on [2].
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src, path = open(PANEL).read(), PANEL
if PERTURB:
    anchor = "                if ifn in _mesh:\n"
    if src.count(anchor) != 1:
        print("PERTURB FAILED — the mesh branch is not in swg-panel-server exactly once")
        sys.exit(1)
    src = src.replace(anchor, "                if False:\n")
    path = os.path.join(tempfile.mkdtemp(), "swg-panel-server")
    open(path, "w").write(src)

ld = importlib.machinery.SourceFileLoader("swgpanel_fwrange", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_fwrange", ld))
P.__dict__["__file__"] = path
try:
    ld.exec_module(P)
except SystemExit:
    pass

MESH_KEY = ("{v1}: this mesh link listens on UDP {v2}, outside this node's declared firewall range ({v3}) — other nodes "
            "cannot open the link to this one; it only comes up while this node dials out. Add the mesh port band to the range")
IFACE_KEY = ("{v1}: listens on UDP {v2}, outside this node's declared firewall range ({v3}) — clients cannot reach it until "
             "the range covers that port, or the interface moves inside it")

node = {"id": "n1", "name": "q4nix", "links": {"n2": {"iface": "swg_2ddf745d"}}}
def snap(udp):
    s = {"interfaces": {"swg_2ddf745d": {"meta": {"listen_port": 9999}},
                        "awg0": {"meta": {"listen_port": 51821}},
                        "wg9": {"meta": {"listen_port": 52000}}}}
    if udp is not None:
        s["udp_ports"] = udp
    return s
def keys(issues, subject):
    return [i.get("error_key") for i in issues if isinstance(i, dict) and ((i.get("error_vars") or {}).get("v1") == subject)]

iss = P._node_issues(node, snap("51820-51899"))
check("[1] a user interface outside the range gets the interface sentence", keys(iss, "wg9") == [IFACE_KEY], iss)
check("[1] an interface inside the range gets nothing", keys(iss, "awg0") == [], iss)
check("[2] the mesh link outside the range gets the mesh sentence", keys(iss, "swg_2ddf745d") == [MESH_KEY], iss)
check("[2] …and never the one about clients", IFACE_KEY not in keys(iss, "swg_2ddf745d"), iss)

iss = P._node_issues(node, snap("51820-51899,56000-56099,9999-10098"))
check("[3] the mesh band declared: nothing about the mesh link", keys(iss, "swg_2ddf745d") == [], iss)
iss = P._node_issues(node, snap(None))
check("[3] no range declared: no firewall sentence at all", not keys(iss, "swg_2ddf745d") and not keys(iss, "wg9"), iss)

ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("[4] js/lang/ru.js translates the mesh sentence", '"%s":' % MESH_KEY in ru)
check("[4] js/lang/ru.js translates the interface sentence", '"%s":' % IFACE_KEY in ru)

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — the mesh branch was removed and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
