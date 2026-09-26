#!/usr/bin/env python3
"""Self-test — four installer lines that read wrong in the 1.8.8 qualification's third VM round now read right.

  [a] a bare master RE-installed over a kept state dir (the uninstall kept the panel's data and the interfaces, and
      removed the node) listed every live interface as "NOT managed by the panel — adopt them from the panel", then
      "No local interfaces yet" — although the panel's record for this node still owns them and the node takes them back
      on its first sync (q1). Now those are listed as the panel's; a stranger is still a candidate, and so is one of the
      panel's that is not up (the node's self-heal takes only a live one).
  [b] a Docker → bare-metal convert ended with "Node 'q4' is up" — the box's hostname — while the panel calls the node
      q4n. The final lines now name the node as the panel does whenever this run asked it (a re-install or a convert).
  [c] …and in the same convert: "Step 1. Node name for THIS box" was printed with no answer under it in an unattended
      run (the bare installers took the default silently, the Docker one says so), and "Found 3 … interface(s)" was
      printed over two rows — the mesh link was counted but, rightly, not listed.

  [d] during a convert, the installers greeted the state the conversion had just staged as someone's existing install:
      "Existing docker install detected … To start fresh, uninstall first" (bare → Docker, once per stage) and
      "Existing panel install detected … To start fresh, run the uninstaller first" (Docker → bare). A plain
      re-install still says it.

choose_ifaces (install-host.sh), the prompt helpers of both bare installers, the local-interface listing of
install-node.sh and its final-name line, and both installers' existing-install blocks are lifted out AS SHIPPED;
detection, `ip` and the terminal are stubbed.

Run: python3 tests/installer_lines_selftest.py      (0 = pass)
     --perturb   the shipped lines planted back → RED
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    H = plant(H, '      case "$_kept" in *" $n "*) ip link show "$n" >/dev/null 2>&1 && { BACK+=("$n"); continue; };; esac\n', '')
    N = plant(N, '_PNAME="${PUSH_NAME:-${_cur:-$NODE_NAME}}"', '_PNAME="$NODE_NAME"')
    for _src in ("N", "H"):   # both prompt helpers of both bare installers: the default taken silently again
        _t = globals()[_src]
        assert _t.count('rc=1; v=""; _tty || _notty "$p" "$d"; fi') == 2, "perturbation anchor missing in " + _src
        globals()[_src] = _t.replace('rc=1; v=""; _tty || _notty "$p" "$d"; fi', 'rc=1; v=""; fi')
    N = plant(N, "awk 'NF && !s[$0]++' | drop_sys_ifaces)", "awk 'NF && !s[$0]++')")
    D = plant(D, '  if [ -n "${SWG_CONVERT_DIR:-}" ]; then :\n  elif [ "$PROFILE" = node ]; then', '  if [ "$PROFILE" = node ]; then')
    H = plant(H, '  [ -n "${SWG_CONVERT_DIR:-}" ] || info "Existing panel install detected', '  info "Existing panel install detected')

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

COMMON = 'SWG_SYS_PREFIX=swg_\n' + fn(C, "is_sys_iface") + fn(C, "drop_sys_ifaces")
PRE = ('set -euo pipefail\nDRYRUN=false; BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_BL=""; C_BROWN=""; _SWG_NL=""\n'
       'info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ :; }; die(){ echo "DIE $*"; exit 1; }\n'
       'b(){ printf %s "$*"; }; bb(){ printf %s "$*"; }; col(){ shift; printf %s "$*"; }; have(){ command -v "$1" >/dev/null 2>&1; }\n'
       '_pnl(){ echo; _SWG_NL=1; }; _nlguard(){ _SWG_NL=""; }\n') + COMMON

def stubs(live):
    d = tempfile.mkdtemp(prefix="instl-")
    p = os.path.join(d, "ip")
    open(p, "w").write('#!/bin/bash\ncase " %s " in *" $3 "*) exit 0;; esac\nexit 1\n' % " ".join(live)); os.chmod(p, 0o755)
    return d

def run(script, stubdir=None, setsid=False):
    env = dict(os.environ, PATH=(stubdir + ":" if stubdir else "") + os.environ["PATH"])
    cmd = (["setsid", "-w"] if setsid else []) + ["bash", "-c", PRE + script]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    return r.stdout + r.stderr

print("[a] a bare master re-installed over the panel's kept state")
def choose(kept_ifaces, live, name="q1m"):
    t = tempfile.mkdtemp(prefix="instl-st-")
    if kept_ifaces is not None:
        json.dump({"n1": {"name": name, "ifaces": kept_ifaces}, "n2": {"name": "other", "ifaces": {"wg9": {}}}},
                  open(os.path.join(t, "nodes.json"), "w"))
    script = ('STATE_DIR=%s; HOST_NODE_NAME=q1m; MANAGE_IFACES=""; HOST_ENDPOINT_IP=192.168.77.1\n'
              'declare -A IF_CMD=() IF_CONF=() IF_ENDPOINT=() SPEC_CMD=()\n'
              'detect_wg(){ IF_CMD=([awg0]=awg [wg0]=wg [wg9]=wg [swg_c8]=awg); }\nmanage_ifaces_resolve(){ :; }\napply_specs(){ :; }\n'
              'local_ifaces(){ :; }\nwdtt_local(){ :; }\niface_row(){ echo "ROW $1"; }\n%s%s'
              'choose_ifaces\n') % (t, fn(H, "kept_panel_ifaces"), fn(H, "choose_ifaces"))
    return run(script, stubs(live))
out = choose({"awg0": {}, "wg0": {}, "swg_c8": {"system": True}}, live=("awg0", "wg0", "wg9", "swg_c8"))
check("the panel's own live interfaces are listed as the panel's — it takes them back on the node's first sync",
      "Found 2 wg/awg interface(s) the panel already manages for this node — it takes them back on its first sync:" in out
      and "ROW awg0" in out and "ROW wg0" in out, out)
check("…a stranger on the box is still an adoption candidate",
      "Found 1 wg/awg/wdtt interface(s) NOT managed by the panel" in out and "ROW wg9" in out, out)
check("…no \"No local interfaces yet\" above interfaces the panel is about to take back", "No local interfaces yet" not in out, out)
check("…and the mesh link is in neither list", "ROW swg_c8" not in out, out)
out = choose({"awg0": {}, "wg0": {}}, live=("wg0", "wg9"))
check("one of the panel's that is NOT up stays a candidate (the node's self-heal takes only a live one)",
      "Found 1 wg/awg interface(s) the panel already manages" in out and "Found 2 wg/awg/wdtt interface(s) NOT managed" in out, out)
out = choose(None, live=("awg0", "wg0", "wg9"))
check("a first install (no kept state): every interface is a candidate, as before",
      "Found 3 wg/awg/wdtt interface(s) NOT managed by the panel" in out and "already manages" not in out, out)

print("\n[b] the final line names the node as the panel does")
line = next(l for l in N.splitlines() if l.startswith("_PNAME="))
for want, pre in (("q4n", 'PUSH_NAME=""; _cur=q4n; NODE_NAME=q4'), ("edge-1", 'PUSH_NAME=edge-1; _cur=q4n; NODE_NAME=q4'),
                  ("q4", 'PUSH_NAME=""; NODE_NAME=q4')):
    out = run('%s\n%s\necho "NAME=$_PNAME"\n' % (pre, line))
    check("%s → %s" % (pre, want), out.strip().endswith("NAME=" + want), out)
check("both final lines use it (\"is up — fully converted\" and \"install complete\")",
      N.count("ok \"Node '$(bb \"$_PNAME\")'") == 2, N.count("ok \"Node '$(bb \"$_PNAME\")'"))

print("\n[c] an unattended run says which default it took, and counts only what it lists")
for src, label in ((N, "install-node.sh"), (H, "install-host.sh")):
    out = run('_tty(){ { : </dev/tty; } 2>/dev/null; }\nv_name(){ [ -n "$1" ]; }\n%s%s'
              'step(){ echo "Step 1. $1"; }\nstep "Node name for THIS box"\nPUSH_NAME=""\n'
              'ask_valid "Node name for THIS box" q4n PUSH_NAME v_name "1-40 chars"\necho "GOT=$PUSH_NAME"\n'
              'ask_choice "Select protocol" a PROTO "a w"\necho "PROTO=$PROTO"\n'
              % (("_notty(){ :; }\n" if "_notty(){" not in src else fn(src, "_notty")), fn(src, "ask_valid") + fn(src, "ask_choice")),
              setsid=True)
    check("%s: the node-name prompt with no terminal prints the default it took" % label,
          "Node name for THIS box: q4n  (no terminal — default taken)" in out and "GOT=q4n" in out, out)
    check("%s: …and so does a menu choice" % label, "Select protocol: a  (no terminal — default taken)" in out and "PROTO=a" in out, out)
a = N.index("  local _l _li _lls _lsub; local -a _loc=()\n")
b = N.index('ok "Managing: ', a); b = N.index("\n", b) + 1
LISTING = N[a:b]
out = run('declare -A IF_CMD=([awg0]=awg [wg0]=wg [swg_c8]=awg)\nSELECTED=(awg0 swg_c8 wg0)\nlocal_ifaces(){ :; }\n'
          'detect_wg(){ :; }\niface_row(){ is_sys_iface "$1" && return 0; echo "ROW $1"; }\nwdtt_local(){ :; }\n'
          'listing(){\n%s}\nlisting\n' % LISTING)
check("a convert carrying a mesh link: \"Found 2\" over the two rows it prints",
      "Found 2 wg/awg/wdtt local interface(s)" in out and out.count("ROW ") == 2, out)
check("…and \"Managing:\" names the same two", "OK Managing: awg0 wg0" in out, out)

print("\n[d] a convert does not greet its own staging as an existing install")
a = D.index('if [ -f "$INSTALL_DIR/.env" ]; then\n  EXISTING_DOCKER=yes')
b = D.index("\n\n# RE-INSTALL: signal", a)
DBLOCK = D[a:b] + "\n"
def docker_greet(profile, convert):
    t = tempfile.mkdtemp(prefix="instl-d-"); open(os.path.join(t, ".env"), "w").write("PANEL_URL=https://p:2087\nNODE_TOKEN=tok\n")
    return run('INSTALL_DIR=%s; PROFILE=%s; SWG_CONVERT_DIR="%s"; HAVE_TTY=no; EXISTING_DOCKER=no; EXIST_TLS=""\n%s%s' % (
        t, profile, convert, fn(D, "_env_val"), DBLOCK))
for prof in ("host", "node"):
    out = docker_greet(prof, "convert-docker")
    check("install-docker.sh (%s stage of a convert): no \"Existing … install detected\"" % prof, "Existing" not in out, out)
    out = docker_greet(prof, "")
    check("install-docker.sh (%s re-install): still says it" % prof, "INFO Existing" in out and "to start fresh" in out.lower(), out)
a = H.index('EXISTING_HOST=no; KEEP_AUTH=no\n')   # with the defaults it initialises
b = H.index("\nfi\n", H.index('if [ -f "$ETC_DIR/auth" ] || [ -f "$_unit" ]; then', a)) + 4
HBLOCK = H[a:b]
def host_greet(convert):
    t = tempfile.mkdtemp(prefix="instl-h-"); open(os.path.join(t, "auth"), "w").write("admin1:hash\n")
    return run('ETC_DIR=%s; BASIC_USER=admin; SUB_DOMAIN=""; SWG_CONVERT_DIR="%s"\n%s' % (t, convert, HBLOCK.replace("/etc/systemd/system/swg-panel-server.service", t + "/none")))
out = host_greet("convert-bare")
check("install-host.sh (Docker → bare-metal convert): no \"Existing panel install detected\"", "Existing" not in out, out)
out = host_greet("")
check("install-host.sh (re-install): still says it", "INFO Existing panel install detected" in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
