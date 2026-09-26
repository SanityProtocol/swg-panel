#!/usr/bin/env python3
"""Self-test — only an interface that was ADOPTED is add-only; the panel's own interfaces and its mesh links never are.

Add-only (`#swg:onboarded` in the conf → `onboarded` in the node's config) means the node keeps peers it is merely not
sent: right for an interface adopted with peers of its own, wrong for one the panel made, where every peer is the
panel's. Two paths stamped it on interfaces the panel made (1.8.8 qualification):
  · a Docker → bare-metal CONVERT stamped every migrated interface "that arrived without a marker" — which is exactly
    the ones the panel created, and its mesh links (q4: wg0, awg0, swg_cac8a245). Since 1.6.0; before it, this branch
    skipped conversion imports because their confs already carry the right marker.
  · the node's SELF-HEAL (taking back a live interface the panel owns when the node lost its record — a master
    re-installed over kept state, a container recreated) stamped everything it took back (q1: wg0, awg0, wg1). Since 1.7.12.

  THE CONVERT (install-node.sh, lifted out as shipped; detection stubbed)
    [1] the migrated confs are carried as they are: the panel's interfaces and a mesh link gain no mark, an adopted one
        keeps its own, and the config the installer writes says the same
    [2] a migrated interface whose conf has to be rebuilt from the device is stamped add-only (the device cannot say;
        keeping peers is the side that can be undone) — but never a mesh link
  THE SELF-HEAL (swg-noded onboard_ifaces + the sync's own call, the datapath stubbed)
    [3] taken back with its conf on disk: add-only exactly when that conf says so; nothing is written into it
    [4] taken back with no conf: rebuilt and stamped add-only (fail safe) — a mesh link rebuilt without the stamp
    [5] adopted by the operator: add-only, stamped — also when the self-heal found the same interface (an onboard with an
        endpoint gives it a panel record, so the self-heal sees it too)
  THE LINKS (swg-noded)
    [6] a mesh link is never add-only, whatever its conf says (converts before 1.8.8 stamped them): reconcile removes a
        stale key from it, while an adopted interface keeps its stranger — and the snapshot reports what reconcile does

Run: python3 tests/add_only_marking_selftest.py        (0 = pass)
     --plant <convert|rebuild|heal|precedence|mesh|rebuildmark>   plant one old behaviour → RED (exit 0 when caught)
     --perturb                                                    plant them all → RED
"""
import importlib.machinery, importlib.util, json, os, re, subprocess, sys, tempfile, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
N_SH = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
C_SH = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
NODED_SRC = open(NODED, encoding="utf-8").read()
PLANTS_ALL = ("convert", "rebuild", "heal", "precedence", "mesh", "rebuildmark")
PLANTS = set(PLANTS_ALL) if "--perturb" in sys.argv else (
    {sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())
assert PLANTS <= set(PLANTS_ALL), "unknown plant"

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if "convert" in PLANTS:     # the shipped convert branch: stamp every migrated interface that arrived without a marker
    N_SH = plant(N_SH, '    IFS=\', \' read -ra SELECTED <<< "$ADOPTED_IFACES"\n  else\n',
                 '    IFS=\', \' read -ra SELECTED <<< "$ADOPTED_IFACES"\n'
                 '    local n _nodeifs; _nodeifs="$(node_ifaces | tr \'\\n\' \' \')"\n'
                 '    for n in ${SELECTED[@]+"${SELECTED[@]}"}; do n="${n// /}"; [ -z "$n" ] && continue\n'
                 '      _in "$n" "$_nodeifs" && continue\n      _in "$n" "${CREATED[*]:-}" && continue\n'
                 '      c="${IF_CONF[$n]:-}"; [ -f "$c" ] && { grep -q \'^#swg:onboarded\' "$c" || sed -i \'1i #swg:onboarded\' "$c"; }\n'
                 '    done\n  else\n')
if "rebuild" in PLANTS:
    N_SH = plant(N_SH, "{ is_sys_iface \"$n\" || echo '#swg:onboarded'; printf", "{ echo '#swg:onboarded'; printf")
if "heal" in PLANTS:
    NODED_SRC = plant(NODED_SRC, "_onb = _mark and (iface not in heal or _t is None or bool(_ONBOARDED_RE.search(_t)))", "_onb = _mark")
if "precedence" in PLANTS:
    NODED_SRC = plant(NODED_SRC, "heal=set(_heal) - set(_obreq))", "heal=set(_heal))")
if "mesh" in PLANTS:
    NODED_SRC = plant(NODED_SRC, 'return bool((ic or {}).get("onboarded")) and not str(iface).startswith("swg_")',
                      'return bool((ic or {}).get("onboarded"))')
if "rebuildmark" in PLANTS:
    NODED_SRC = plant(NODED_SRC, '(("#swg:onboarded\\n" if mark else "") + "#swg:cmd "', '("#swg:onboarded\\n" + "#swg:cmd "')


def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

PRE = ('set -euo pipefail\nDRYRUN=false; BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_BL=""\n'
       'info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ :; }; b(){ printf %s "$*"; }\n'
       'SWG_SYS_PREFIX=swg_\n' + fn(C_SH, "is_sys_iface") + fn(C_SH, "drop_sys_ifaces") + fn(N_SH, "iface_onboarded")
       + fn(N_SH, "_in"))

def bash(script, path_prefix=None):
    env = dict(os.environ, PATH=(path_prefix + ":" if path_prefix else "") + os.environ["PATH"])
    r = subprocess.run(["bash", "-c", PRE + script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr

# ── [1] the convert carries confs as they are ────────────────────────────────────────────────────────────────────────
print("[1] a Docker → bare-metal convert carries each interface as it was")
T = tempfile.mkdtemp(prefix="addonly-")
CONFS = {"wg0": "#swg:cmd wg\n[Interface]\nAddress = 10.64.1.1/24\nListenPort = 51820\n\n[Peer]\nPublicKey = AAA=\nAllowedIPs = 10.64.1.2/32\n",
         "awg0": "[Interface]\nAddress = 10.64.2.1/24\nJc = 4\n",
         "swg_cac8a245": "#swg:cmd awg\n[Interface]\nAddress = 10.255.0.1/31\nTable = off\n",
         "adop0": "#swg:onboarded\n#swg:cmd wg\n[Interface]\nAddress = 10.70.0.1/24\n\n[Peer]\nPublicKey = OWN=\nAllowedIPs = 10.70.0.5/32\n"}
paths = {}
for n, body in CONFS.items():
    paths[n] = os.path.join(T, n + ".conf"); open(paths[n], "w").write(body)
detect = "detect_wg(){ %s; }\n" % "; ".join("IF_CMD[%s]=%s; IF_CONF[%s]=%s" % (n, "awg" if n in ("awg0", "swg_cac8a245") else "wg", n, paths[n])
                                            for n in CONFS)
a = N_SH.index("# ───────────────────────── config.json (pull-only HTTPS) ─────────────────────────\n")
b = N_SH.index("; done\n", a) + len("; done\n")
WRITER = N_SH[a:b]
out = bash('declare -A IF_CMD=() IF_CONF=() IF_ENDPOINT=(); SELECTED=(); CREATED=()\nSWG_CONVERT=1; ADOPTED_IFACES="wg0 awg0 swg_cac8a245 adop0"\n'
           'MANAGE_IFACES=""\nreconstruct_live_orphans(){ :; }\nmigrate_docker_ifaces(){ :; }\nmanage_ifaces_resolve(){ :; }\n'
           'apply_node_switch(){ echo SWITCH; }\nnode_ifaces(){ :; }\nlocal_ifaces(){ :; }\n' + detect + fn(N_SH, "choose_ifaces")
           + 'choose_ifaces\necho "SELECTED=${SELECTED[*]}"\n' + WRITER + 'printf "{%s}\\n" "$IFJSON" > ' + os.path.join(T, "ifjson") + '\n')
check("[1] the convert carries all four", "SELECTED=wg0 awg0 swg_cac8a245 adop0" in out, out)
same = {n: open(paths[n]).read() == CONFS[n] for n in CONFS}
check("[1] …every conf byte-identical: the panel's wg0/awg0 and the mesh link gain no mark, the adopted one keeps its own",
      all(same.values()), same)
try:
    ifj = json.loads(open(os.path.join(T, "ifjson")).read())
except Exception as e:
    ifj = {"error": str(e)}
check("[1] …and the node's config says the same: only the adopted interface is add-only",
      {n: bool((ifj.get(n) or {}).get("onboarded")) for n in CONFS} == {"wg0": False, "awg0": False, "swg_cac8a245": False, "adop0": True}, ifj)

print("\n[2] a migrated interface rebuilt from the device")
R = tempfile.mkdtemp(prefix="addonly-rb-"); ST = tempfile.mkdtemp(prefix="addonly-stub-")
WGD, AWGD = os.path.join(R, "wireguard"), os.path.join(R, "amneziawg")
def stub(name, body):
    p = os.path.join(ST, name); open(p, "w").write("#!/bin/bash\n" + body); os.chmod(p, 0o755)
stub("wg", 'case "$1 $2" in "show interfaces") echo "wg5 swg_ab";; "showconf wg5"|"showconf swg_ab") '
           'printf "[Interface]\\nListenPort = 51825\\nPrivateKey = KEY=\\n\\n[Peer]\\nPublicKey = P=\\nAllowedIPs = 10.5.0.2/32\\n";; esac\n')
stub("awg", 'exit 0\n')
stub("ip", 'case "$*" in "route show default") echo "default via 10.0.0.1 dev eth0";; *"addr show wg5") echo "5: wg5    inet 10.5.0.1/24 scope global wg5";;'
           ' *"addr show swg_ab") echo "6: swg_ab    inet 10.255.0.4/31 scope global swg_ab";; esac\n')
rlo = fn(N_SH, "reconstruct_live_orphans").replace("/etc/amnezia/amneziawg", AWGD).replace("/etc/wireguard", WGD)
out = bash('SWG_CONVERT=1; ADOPTED_IFACES="wg5 swg_ab"\n' + rlo + 'reconstruct_live_orphans\n', ST)
rb = {n: (open(os.path.join(WGD, n + ".conf")).read() if os.path.exists(os.path.join(WGD, n + ".conf")) else None) for n in ("wg5", "swg_ab")}
check("[2] both are rebuilt", all(v is not None and "[Peer]" in v for v in rb.values()), (out, rb))
check("[2] …the user interface stamped add-only (the device cannot say what it was)", (rb["wg5"] or "").startswith("#swg:onboarded\n"), rb["wg5"])
check("[2] …the mesh link never", "#swg:onboarded" not in (rb["swg_ab"] or "#swg:onboarded"), rb["swg_ab"])

# ── the node ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def load_noded():
    p = os.path.join(tempfile.mkdtemp(prefix="addonly-nd-"), "swg-noded")
    open(p, "w", encoding="utf-8").write(NODED_SRC)
    ld = importlib.machinery.SourceFileLoader("swgnoded_addonly", p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_addonly", ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m
N = load_noded()
D = tempfile.mkdtemp(prefix="addonly-heal-")
N.WG_CONF_DIRS = (os.path.join(D, "wireguard"),); N.AWG_CONF_DIRS = (os.path.join(D, "amneziawg"),)
N._awg_conf_dirs = lambda: list(N.AWG_CONF_DIRS)
N.NODE_KIND = "baremetal"
N._persist_config = lambda cfg: None
for d in N.WG_CONF_DIRS + N.AWG_CONF_DIRS:
    os.makedirs(d, exist_ok=True)
LIVE = {"wg0": "wg", "wg1": "wg", "wg2": "wg", "awg0": "awg", "swg_ab": "awg", "wg9": "wg", "wg8": "wg"}

class R_(object):
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""
def fake_run(args, input_text=None, timeout=20):
    a = list(args)
    if a[0] in ("wg", "awg") and len(a) >= 3 and a[1] == "showconf":
        return R_(0, "[Interface]\nListenPort = 51820\nPrivateKey = K=\n" + ("Jc = 4\n" if a[0] == "awg" else "")
                  + "\n[Peer]\nPublicKey = LIVE=\nAllowedIPs = 10.9.0.2/32\n") if LIVE.get(a[2]) == a[0] else R_(1)
    if a[0] in ("wg", "awg") and len(a) >= 4 and a[1] == "show" and a[3] == "dump":
        return R_(0, "K=\tPUB=\t51820\toff\n") if LIVE.get(a[2]) == a[0] else R_(1)
    if a[:2] == ["ip", "-4"]:
        return R_(0, "9: %s    inet 10.9.0.1/24 scope global %s\n" % (a[-1], a[-1]))
    if a[:3] == ["ip", "-o", "link"]:
        return R_(0, "9: %s: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 qdisc noqueue\n" % a[-1])
    return R_(1)
N.run = fake_run

def put(dirname, name, body):
    p = os.path.join(D, dirname, name + ".conf"); open(p, "w").write(body); return p
created = put("wireguard", "wg0", "#swg:cmd wg\n[Interface]\nAddress = 10.64.1.1/24\n")              # the panel made it
adopted = put("wireguard", "wg1", "#swg:onboarded\n#swg:cmd wg\n[Interface]\nAddress = 10.70.0.1/24\n")  # adopted earlier
bare_created = put("amneziawg", "awg0", "[Interface]\nAddress = 10.64.2.1/24\nJc = 4\n")                # no #swg:cmd yet
BEFORE = {p: open(p).read() for p in (created, adopted)}

print("\n[3]–[4] the self-heal takes interfaces back")
cfg = {"interfaces": {}}
reply = {"onboard": {}}
_heal = {n: {"cmd": [LIVE[n]], "conf": ""} for n in ("wg0", "wg1", "awg0", "wg2", "swg_ab")}
m = re.search(r'\n(\s*)_obreq = reply\.get\("onboard"\) or \{\}\n\s*ob = onboard_ifaces\([^\n]*\)\n', NODED_SRC)
CALL = textwrap.dedent(m.group(0).strip("\n") + "\n") if m else ""
check("[3] the sync's own onboard call is found", bool(CALL), "")
def sync_call(reply, heal, cfg):
    ns = {"reply": reply, "_heal": heal, "node_cfg": cfg, "onboard_ifaces": N.onboard_ifaces}
    exec(CALL, ns)
    return ns.get("ob") or {}
ob = sync_call(reply, _heal, cfg)
ifs = cfg["interfaces"]
check("[3] every live interface is taken back", sorted(ifs) == sorted(_heal), (sorted(ifs), ob))
check("[3] the panel's own wg0 (conf on disk, no mark) is NOT add-only", not ifs.get("wg0", {}).get("onboarded"), ifs.get("wg0"))
check("[3] …and nothing is written into its conf", open(created).read() == BEFORE[created], open(created).read())
check("[3] the adopted wg1 (its conf says so) stays add-only, its conf untouched",
      ifs.get("wg1", {}).get("onboarded") is True and open(adopted).read() == BEFORE[adopted], ifs.get("wg1"))
check("[3] awg0 (the panel's, no mark, no protocol line) gains its protocol line but no mark",
      not ifs.get("awg0", {}).get("onboarded") and open(bare_created).read().startswith("#swg:cmd awg\n")
      and "#swg:onboarded" not in open(bare_created).read(), open(bare_created).read())
wg2 = os.path.join(D, "wireguard", "wg2.conf"); link = os.path.join(D, "amneziawg", "swg_ab.conf")
check("[4] wg2 (no conf anywhere): rebuilt from the device and stamped add-only — the device cannot say",
      ifs.get("wg2", {}).get("onboarded") is True and open(wg2).read().startswith("#swg:onboarded\n"),
      (ifs.get("wg2"), os.path.exists(wg2) and open(wg2).read()[:40]))
check("[4] the mesh link (no conf): rebuilt without the stamp, not add-only",
      os.path.exists(link) and "#swg:onboarded" not in open(link).read() and not ifs.get("swg_ab", {}).get("onboarded"),
      (ifs.get("swg_ab"), os.path.exists(link) and open(link).read()[:40]))

print("\n[5] the operator adopts")
put("wireguard", "wg9", "[Interface]\nAddress = 10.99.0.1/24\n\n[Peer]\nPublicKey = OWN=\nAllowedIPs = 10.99.0.5/32\n")
put("wireguard", "wg8", "[Interface]\nAddress = 10.98.0.1/24\n")
cfg2 = {"interfaces": {}}
sync_call({"onboard": {"wg9": {"cmd": ["wg"], "conf": os.path.join(D, "wireguard", "wg9.conf")}}}, {}, cfg2)
check("[5] an adopted interface is add-only and stamped",
      cfg2["interfaces"].get("wg9", {}).get("onboarded") is True and open(os.path.join(D, "wireguard", "wg9.conf")).read().startswith("#swg:onboarded\n"),
      cfg2["interfaces"].get("wg9"))
cfg3 = {"interfaces": {}}
sync_call({"onboard": {"wg8": {"cmd": ["wg"], "conf": os.path.join(D, "wireguard", "wg8.conf")}}},
          {"wg8": {"cmd": ["wg"], "conf": ""}}, cfg3)
check("[5] …also when the self-heal found the same interface in the same pass (an onboard with an endpoint)",
      cfg3["interfaces"].get("wg8", {}).get("onboarded") is True and "#swg:onboarded" in open(os.path.join(D, "wireguard", "wg8.conf")).read(),
      cfg3["interfaces"].get("wg8"))

print("\n[6] a mesh link is never add-only")
N.STATE_DIR = D
K = lambda c: (c * 43)[:43] + "="
M_NEW, M_OLD, A, S = K("M"), K("O"), K("A"), K("S")
WIRE = {"swg_ab": [M_NEW, M_OLD], "wg7": [A, S]}
calls = []
def dump(cfg, ifn):
    return (["dev", "key", "9999"], [{"public_key": k, "preshared_key": None, "endpoint": "192.168.77.3:9999" if k in (M_NEW, M_OLD) else None,
                                      "allowed_ips": "10.255.0.0/32" if k == M_NEW else ("10.255.0.8/32" if k == M_OLD else "10.7.0.2/32"),
                                      "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0} for k in WIRE.get(ifn, [])])
N._iface_dump = dump
N.run_agent = lambda _a, _s, payload: (calls.append(payload), {"ok": True})[1]
CFG = {"interfaces": {"swg_ab": {"cmd": ["awg"], "conf": link, "onboarded": True},     # stamped by an old convert
                      "wg7": {"cmd": ["wg"], "conf": wg2, "onboarded": True}}}         # a genuinely adopted interface
desired = {"swg_ab": [{"public_key": M_NEW, "allowed_ips": "10.255.0.0/32", "preshared_key": "none", "endpoint": "192.168.77.3:9999",
                       "persistent_keepalive": 25, "name": "mesh:q3m"}],
           "wg7": [{"public_key": A, "allowed_ips": "10.7.0.2/32", "preshared_key": "none", "name": "carol"}]}
N.reconcile(CFG, desired, "/opt/swg-agent/swg-agent", False, {})
gone = [(c.get("iface"), c.get("public_key")) for c in calls if c.get("op") == "remove-peer"]
check("[6] the stamped mesh link loses its stale key", ("swg_ab", M_OLD) in gone, gone)
check("[6] …while the adopted interface keeps its stranger", ("wg7", S) not in gone, gone)
check("[6] the one test: a link is never add-only, an adopted interface is, an unmarked one is not",
      (N._add_only("swg_ab", {"onboarded": True}), N._add_only("wg7", {"onboarded": True}), N._add_only("wg0", {})) == (False, True, False))
_bs = NODED_SRC[NODED_SRC.index("def build_snapshot("):NODED_SRC.index("\ndef ", NODED_SRC.index("def build_snapshot(") + 10)]
_rep = re.findall(r'"onboarded":\s*(\w+\([^)]*\)|[^,}\n]+)', _bs)
check("[6] …and every add-only flag the snapshot reports is that same test", len(_rep) == 3 and all(r.strip() == "_add_only(iface, ic)" for r in _rep), _rep)

print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
