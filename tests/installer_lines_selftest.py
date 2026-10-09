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
  [f] the convert's "Interfaces to migrate" list (both directions) sized its name column for 10 characters, so a mesh
      link (swg_<8 hex>, 12) pushed its own row two columns right of the others (q4). The column is now as wide as the
      longest name; a list without a long name prints exactly as before.
  [e] an answer the caller already GAVE (-flag / env) left its step empty: a master installed with HOST_NODE_NAME set
      printed "Step 4. Node name for THIS box" and then the next step. Every prompt helper of both bare installers now
      says it — "<prompt>: <value>  (given — not asked)", the twin of the no-terminal line — except a value the script
      derived itself (the panel's port, from its URL), and a given value that fails validation is still asked for.

choose_ifaces (install-host.sh), the prompt helpers of both bare installers, the local-interface listing of
install-node.sh and its final-name line, and both installers' existing-install blocks are lifted out AS SHIPPED;
detection, `ip` and the terminal are stubbed.

  [g]–[n] round 4's misleading lines: the Docker installer's helpers took a given answer in silence (M1) — and name a
      value read back from .env as that, not as given; its footer told a master to `--profile node up -d` (M2); a given
      domain was asked anyway and read "(no terminal — default taken)" (M3, both installers); the two-panel answer
      given by SWG_OTHER_PANEL was taken under a menu saying "(default)" abort (M4); a dry run said it "issued" a
      certificate (M8); a secret prompt with no terminal ended in a blank line (M9); a refused convert pre-flight
      printed the convert menu again before stopping (M10); a Docker re-install with the password the login already has
      deleted it, wrote it back and called it a new login (M6).
  [o] a bare NODE re-install wrote config.json without its mesh links (node_ifaces dropped them — since before 1.8.7), so
      the links went unmanaged until the node's self-heal took them back from the panel, i.e. never while the panel was
      unreachable (round 5, the DEF-E cell). They are kept now; a mesh link is still no turn-proxy forward target.
  [p] a bare dry run printed the summary of the LIVE box: "Host install complete", "INSTALL COMPLETE … new login — save
      the password now", and beside a Docker panel that panel's user with this run's password as its login; a node's dry
      run said "install complete" over the Docker panel's summary (round 5, q6). Both bare installers now say what a dry
      run did, as install-docker.sh already does; a real run still prints the summary.
  [r] round 5's leftovers: a bare node's dry run said "CA-verified" although a dry run never probes the panel, a Docker
      node's dry run said "certificate NOT verified" for a self-signed panel the real run pins, and the uninstaller's
      yes/no questions took a given answer or the no-terminal default in silence.
  [q] the other prompts with no terminal ended in a blank line, as the secret prompt did (M9): a port that is not
      Cloudflare-proxyable ("…type proceed, or enter a new URL"), a port already in use ("…type force"), both installers;
      the bootstrap's re-enroll pick (convert.sh's yes/no, cyn, went with the dead migration path it served — 1.8.9
      qualification IN-5, tests/convert_dead_code_selftest.py). Each says the answer it took now. So do
      the bare installers' ask / ask_yn helpers, which with no terminal printed nothing at all (a node's dry run took
      "Verify the panel's TLS certificate?" in silence); their ask_valid / ask_choice and the Docker helpers already did.

  [s] (1.8.9 qualification FN-2(a)) the summary lists a bare host turn proxy by the address its clients DIAL (SWG_DIAL —
      a DDNS name, an address behind NAT), not its bind ("0.0.0.0:56000"); one with no SWG_DIAL by its listen, as before

  [t] (1.8.8 deferred #5(b)) dnsmasq is masked BEFORE its package is installed, in both installers: its postinst started
      it, the start failed on :53 (systemd-resolved) and the first install printed an error for a unit masked right after

Run: python3 tests/installer_lines_selftest.py      (0 = pass)
     --perturb   the shipped lines planted back → RED
     --perturb-mask   dnsmasq masked only after its install again (e66018f) → RED on [t] only
     --perturb-dial   the summary reads SWG_LISTEN alone again (e66018f) → RED on [s] only
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_DIAL = "--perturb-dial" in sys.argv
PERTURB_MASK = "--perturb-mask" in sys.argv
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
B = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
CV = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

DT = None   # [n]'s "had none to set" check reads its own copy: the [n] plant below switches the whole block off
if PERTURB:
    DT = plant(D, '  KEEP_AUTH=yes; PANEL_PASSWORD="(preserved)"\n  info "Keeping the existing panel login ($(b "$PANEL_USER")) — its password is the one it already has.',
               '  KEEP_AUTH=yes; KEPT_LOGIN=yes; PANEL_PASSWORD="(preserved)"\n  info "Keeping the existing panel login ($(b "$PANEL_USER")) — its password is the one it already has.')
    H = plant(H, '      case "$_kept" in *" $n "*) ip link show "$n" >/dev/null 2>&1 && { BACK+=("$n"); continue; };; esac\n', '')
    N = plant(N, '_PNAME="${PUSH_NAME:-${_cur:-$NODE_NAME}}"', '_PNAME="$NODE_NAME"')
    N = plant(N, "Description=swg-noded (HTTPS sync to panel) — ${_PNAME}\n", "Description=swg-noded (HTTPS sync to panel) — ${NODE_NAME}\n")
    for _src in ("N", "H"):   # both prompt helpers of both bare installers: the default taken silently again
        _t = globals()[_src]
        assert _t.count('rc=1; v=""; _tty || _notty "$p" "$d"; fi') == 2, "perturbation anchor missing in " + _src
        globals()[_src] = _t.replace('rc=1; v=""; _tty || _notty "$p" "$d"; fi', 'rc=1; v=""; fi')
    N = plant(N, "awk 'NF && !s[$0]++' | drop_sys_ifaces)", "awk 'NF && !s[$0]++')")
    D = plant(D, '  if [ -n "${SWG_CONVERT_DIR:-}" ]; then :\n  elif [ "$PROFILE" = node ]; then', '  if [ "$PROFILE" = node ]; then')
    H = plant(H, '  if [ -n "${SWG_CONVERT_DIR:-}" ]; then :\n  elif [ -f "$_unit" ]; then info "Existing panel install detected',
              '  if false; then :\n  elif [ -f "$_unit" ]; then info "Existing panel install detected')
    N = plant(N, "printf '    %s%-*s%s %-9s  %s:%-6s %s\\n' \"$C_GREEN\" \"$_w\" \"$n\"", "printf '    %s%-10s%s %-9s  %s:%-6s %s\\n' \"$C_GREEN\" \"$n\"")
    D = plant(D, "printf '    %s%-*s%s %-9s  %s:%-6s %s\\n' \"$C_GREEN\" \"$_w\" \"$n\"", "printf '    %s%-10s%s %-9s  %s:%-6s %s\\n' \"$C_GREEN\" \"$n\"")
    for _src in ("N", "H"):   # a given answer taken silently again, in all four helpers
        _t = globals()[_src]
        _t = plant(_t, 'for o in $opts; do [ "${!var}" = "$o" ] && { _given "$p" "${!var}"; _pnl; return; }; done', 'for o in $opts; do [ "${!var}" = "$o" ] && return; done')
        _t = plant(_t, '"$fn" "${!var}" && { [ "${6:-}" = derived ] || { [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; _given "$p" "${!var}"; _pnl; }; return; }', '"$fn" "${!var}" && return')
        _t = plant(_t, 'ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; _given "$p" "${!3}"; _pnl; return; fi', 'ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi')
        _t, _n = re.subn(r'(ask\(\)\{ local v p="\$1" d="\$\{2:-\}"; if \[ -n "\$\{!3:-\}" \]; then )[^\n]*?_given "\$p" "\$\{!3\}";[^\n]*?return; fi', r'\1return; fi', _t, count=1)
        assert _n == 1, "perturbation anchor missing in " + _src + " — would FALSE-PASS: ask()"
        globals()[_src] = _t
    # [g] the Docker installer's helpers took a given answer in silence
    D = plant(D, 'for o in $opts; do [ "${!var}" = "$o" ] && { _given "$p" "${!var}" "$var"; _pnl; return; }; done; fi', 'for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi')
    D = plant(D, '"$fn" "${!var}" && { [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; _given "$p" "${!var}" "$var"; _pnl; return; }; fi', '"$fn" "${!var}" && return; fi')
    # [h] the footer's profile defaulted to node
    C = plant(C, "  [ -n \"$prof\" ] || { docker ps --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null && prof=master || prof=node; }\n", "  [ -n \"$prof\" ] || prof=node\n")
    # [i] a given domain asked anyway (and "default taken")
    H = plant(H, 'if [ -n "$_URL_GIVEN" ]; then PANEL_DOMAIN="$DEF_URL"; else PANEL_DOMAIN=""; fi\n', 'PANEL_DOMAIN=""\n')
    D = plant(D, '  if [ -n "${_GIVEN_PANEL_DOMAIN:-}" ]; then PANEL_DOMAIN="$def"; else PANEL_DOMAIN=""; fi\n', '  PANEL_DOMAIN=""\n')
    # [j] the two-panel answer taken in silence
    C = plant(C, '  [ -n "$ans" ] && echo "  Abort, stop the other, or keep both [a/s/k]: $(b "$ans")  (given by SWG_OTHER_PANEL — not asked)"\n', '')
    # [k] a dry run's certificate lines
    H = plant(H, 'if $DRYRUN; then ok "dry run — would create a self-signed certificate for ${PANEL_DOMAIN} (10y)"; else ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; fi; }',
              'ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; }')
    H = plant(H, 'if $DRYRUN; then ok "dry run — would issue + install a certificate via $TLS_MODE (auto-renews)"; else ok "issued + installed certificate via $TLS_MODE (auto-renews)"; fi;;',
              'ok "issued + installed certificate via $TLS_MODE (auto-renews)";;')
    # [o] a node re-install dropped its mesh links from config.json
    N = plant(N, "    if isinstance(ic, dict) and os.path.exists(ic.get(\"conf\", \"\")): print(n)' 2>/dev/null || true\n}",
              "    if isinstance(ic, dict) and os.path.exists(ic.get(\"conf\", \"\")): print(n)' 2>/dev/null | drop_sys_ifaces || true\n}")
    # [l] a secret prompt with no terminal ended blank
    C = plant(C, '      if [ -n "$d" ]; then echo "(no terminal — the saved one is kept)"; else echo "(no terminal — nothing given)"; fi; fi\n', '      echo; fi\n')
    # [m] the convert menu printed again under a refused pre-flight
    _a = '    [ -n "${_conflict_used:-}" ] && [ -n "$ON_CONFLICT" ] && die "the conversion did not go ahead (see above) — nothing was changed. Fix the conflicts, or pass keep / abort instead of $ON_CONFLICT."\n'
    B = plant(B, _a, "")
    B = plant(B, '    CHOICE="$ON_CONFLICT"; _conflict_used=1\n', _a + '    CHOICE="$ON_CONFLICT"; _conflict_used=1\n')
    # [n] a Docker re-install with the password the login already has called it new
    D = plant(D, 'if [ "$KEEP_AUTH" != yes ] && [ "$PROFILE" != node ] && [ "$EXISTING_DOCKER" = yes ] && [ "$_pw_unknown" = no ] \\\n',
              'if false && [ "$PROFILE" != node ] && [ "$EXISTING_DOCKER" = yes ] && [ "$_pw_unknown" = no ] \\\n')
    # [r] the dry runs claim a verdict again, and the uninstaller's questions go silent again
    N = plant(N, '[ -n "${_TLS_DRY_UNPROBED:-}" ] && echo "its certificate is not checked in a dry run — the real run verifies a CA one or pins a self-signed one" || ', '')
    D = plant(D, '[ -n "${_TLS_DRY_WOULD_PIN:-}" ] && echo "self-signed — the real run pins its certificate" || ', '')
    U = plant(U, '    echo "$p ${!3}  (given — not asked)"; return; fi', '    return; fi')
    U = plant(U, '    echo "$p ${!3}  (no terminal — default taken)"; return; fi', '    return; fi')
    # [p] a dry run printed the live box's summary again (both bare installers)
    H = plant(H, 'if $DRYRUN; then\n  _dsch=https;', 'if false; then\n  _dsch=https;')
    N = plant(N, 'if $DRYRUN; then\n  echo; ok "Dry run of the bare-metal node', 'if false; then\n  echo; ok "Dry run of the bare-metal node')
    # [q] the unattended prompts ended blank again
    H = plant(H, '    read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { _url_ans=force; echo "$(b force)  (no terminal — default taken)"; }', '    read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || _url_ans=force')
    H = plant(H, '  read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { _url_ans=proceed; echo "$(b proceed)  (no terminal — default taken)"; }', '  read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || _url_ans=proceed')
    D = plant(D, '      read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { _url_ans=force; echo "$(b force)  (no terminal — default taken)"; }', '      read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || _url_ans=force')
    D = plant(D, '    read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { _url_ans=proceed; echo "$(b proceed)  (no terminal — default taken)"; }', '    read -r _url_ans 2>/dev/null <"${SWG_TTY:-/dev/tty}" || _url_ans=proceed')
    B = plant(B, 'read -r _pick 2>/dev/null <"${SWG_TTY:-/dev/tty}" || { _pick=""; echo "(no terminal — skipped)"; }', 'read -r _pick 2>/dev/null <"${SWG_TTY:-/dev/tty}" || _pick=""')
    B = plant(B, '_pnl(){ printf \'\\n\' 2>/dev/null >/dev/tty || echo; _SWG_NL=1; }', '_pnl(){ printf \'\\n\' >/dev/tty 2>/dev/null || echo; _SWG_NL=1; }')
    B = plant(B, '[ "${!var}" = "$o" ] && { echo "  $p: $(b "$o")  (given — not asked)"; _pnl; return; }; done; fi', '[ "${!var}" = "$o" ] && return; done; fi')
    for _src in ("N", "H"):   # the bare ask / ask_yn took a default in silence again
        _t = globals()[_src]
        _t = plant(_t, 'if _tty; then read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v <"${SWG_TTY:-/dev/tty}" || true; else _notty "$p" "$d"; fi;',
                   '_tty && read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v <"${SWG_TTY:-/dev/tty}" || true;')
        _t = plant(_t, 'if _tty; then read -rp "  $p ($([ "$d" = y ] && echo \'Y/n\' || echo \'y/N\')): " v <"${SWG_TTY:-/dev/tty}" || true; else _notty "$p" "$([ "$d" = y ] && echo yes || echo no)"; fi',
                   '_tty && read -rp "  $p ($([ "$d" = y ] && echo \'Y/n\' || echo \'y/N\')): " v <"${SWG_TTY:-/dev/tty}" || true')
        globals()[_src] = _t

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
_iu = N.find("Description=swg-noded (HTTPS sync to panel) — ${_PNAME}\n")
check("…and so does swg-noded's unit: a convert or a re-install labels it with the panel's name, not the hostname "
      "(round 9b), set before the unit is written", _iu > 0 and N.find(line) < _iu and "— ${NODE_NAME}\n" not in N,
      (_iu, N.find(line)))

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
    # (the block reads what a node LEARNED about its panel through lib/common.sh's docker_node_panel)
    return run('INSTALL_DIR=%s; PROFILE=%s; SWG_CONVERT_DIR="%s"; HAVE_TTY=no; EXISTING_DOCKER=no; EXIST_TLS=""\n%s%s%s' % (
        t, profile, convert, fn(D, "_env_val"), fn(C, "docker_node_panel"), DBLOCK))
for prof in ("host", "node"):
    out = docker_greet(prof, "convert-docker")
    check("install-docker.sh (%s stage of a convert): no \"Existing … install detected\"" % prof, "Existing" not in out, out)
    out = docker_greet(prof, "")
    check("install-docker.sh (%s re-install): still says it" % prof, "INFO Existing" in out and "to start fresh" in out.lower(), out)
a = H.index('EXISTING_HOST=no; KEEP_AUTH=no\n')   # with the defaults it initialises
b = H.index("\nfi\n", H.index('if [ -f "$ETC_DIR/auth" ] || [ -f "$_unit" ]; then', a)) + 4
HBLOCK = H[a:b]
def host_greet(convert, unit=True):
    t = tempfile.mkdtemp(prefix="instl-h-"); open(os.path.join(t, "auth"), "w").write("admin1:hash\n")
    if unit:
        open(os.path.join(t, "unit"), "w").write("[Unit]\n")
    return run('ETC_DIR=%s; STATE_DIR=%s/state; BASIC_USER=admin; SUB_DOMAIN=""; SWG_CONVERT_DIR="%s"\n%s' % (
        t, t, convert, HBLOCK.replace("/etc/systemd/system/swg-panel-server.service", t + "/unit")))
out = host_greet("convert-bare")
check("install-host.sh (Docker → bare-metal convert): no \"Existing panel install detected\"", "Existing" not in out, out)
out = host_greet("")
check("install-host.sh (re-install): still says it", "INFO Existing panel install detected" in out, out)
out = host_greet("", unit=False)   # an uninstall kept the data (login, certificate, install.conf) and removed the panel
check("install-host.sh onto data an uninstall kept: says so, and that it re-installs it as it was",
      "INFO Found this panel's kept data" in out and "Existing panel install detected" not in out, out)

print("\n[e] an answer given in advance is said, not left out")
for src, label in ((N, "install-node.sh"), (H, "install-host.sh")):
    HELPERS = fn(src, "_notty") + fn(src, "_given") + fn(src, "ask_valid") + fn(src, "ask_choice") + fn(src, "ask") + fn(src, "ask_yn")
    out = run('_tty(){ { : </dev/tty; } 2>/dev/null; }\nv_name(){ case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; }\n'
              'v_port(){ case "$1" in ""|*[!0-9]*) return 1;; esac; }\n%s'
              'step(){ [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; echo "Step $1"; }\n'
              'step "4. Node name for THIS box"\nHOST_NODE_NAME=q1m; ask_valid "Node name for THIS box" q4n HOST_NODE_NAME v_name "1-40 chars"\n'
              'step "5. Web server"\nSERVE_MODE=internal; ask_choice "Select web server" i SERVE_MODE "internal nginx i n"\n'
              'SUB_DOMAIN=sub.example.com; ask "Subscription page hostname" "" SUB_DOMAIN\n'
              'VERIFY=no; ask_yn "Verify the panel\'s TLS certificate?" y VERIFY\n'
              'PORT=2087; ask_valid "Public HTTPS port for the panel" "$PORT" PORT v_port "1-65535" derived\n'
              'step "6. Datapath tooling"\nBAD="no spaces!"; ask_valid "Other name" okname BAD v_name "1-40 chars"; echo "BAD=$BAD"\n' % HELPERS,
              setsid=True)
    blk = out.split("Step 4. Node name for THIS box", 1)[-1].split("Step 5.", 1)[0]
    check("%s: the node-name step says the given name — the header is not left empty" % label,
          "Node name for THIS box: q1m  (given — not asked)" in blk, out)
    check("%s: …and so do a given menu choice, a given free-text answer and a given yes/no" % label,
          "Select web server: internal  (given — not asked)" in out and "Subscription page hostname: sub.example.com  (given — not asked)" in out
          and "Verify the panel's TLS certificate?: no  (given — not asked)" in out, out)
    check("%s: a value the script derived itself (the port, from the panel URL) is not presented as given" % label,
          "Public HTTPS port" not in out, out)
    check("%s: a given value that fails validation is still refused and asked for (here: no terminal → the default, said as such)" % label,
          "ignoring invalid BAD" in out and "Other name: okname  (no terminal — default taken)" in out and "BAD=okname" in out, out)
    check("%s: one blank line around each answer, none doubled before the next step" % label, "\n\n\nStep" not in out and "\n\n\n  " not in out, repr(out[:400]))

print("\n[f] the convert's migrate list lines up, a mesh link included")
def migrate_rows(src, fname, names, pre):
    t = tempfile.mkdtemp(prefix="instl-mig-"); awgd, wgd = os.path.join(t, "awg"), os.path.join(t, "wg")
    os.makedirs(awgd); os.makedirs(wgd)
    for n, (proto, port, addr) in names.items():
        open(os.path.join(awgd if proto == "awg" else wgd, n + ".conf"), "w").write(
            "[Interface]\nAddress = %s\nListenPort = %s\n%s" % (addr, port, "Jc = 4\n" if proto == "awg" else ""))
    body = fn(src, fname).replace("/etc/amnezia/amneziawg", awgd).replace("/etc/wireguard", wgd)
    out = run('detect_public_ip(){ echo 192.168.77.4; }\nmigrate_wdtt(){ :; }\nmigrate_csqtt(){ :; }\nmigrate_node_state(){ :; }\n'
              'INSTALL_DIR=%s\n%s\n%s%s\n' % (t, pre, body, fname))
    return [l for l in out.splitlines() if l.startswith("    ") and ("AmneziaWG" in l or "WireGuard" in l)]
MESH = {"awg0": ("awg", 51821, "10.64.2.1/24"), "swg_cac8a245": ("awg", 9999, "10.255.0.0/31"), "wg0": ("wg", 51820, "10.64.1.1/24")}
for src, fname, pre, label in ((N, "migrate_docker_ifaces", "SWG_CONVERT=1; ENDPOINT_IP=192.168.77.4", "install-node.sh (Docker → bare)"),
                               (D, "migrate_baremetal_ifaces", "SWG_CONVERT_DIR=convert-docker; NODE_ENDPOINT=192.168.77.4", "install-docker.sh (bare → Docker)")):
    rows = migrate_rows(src, fname, MESH, pre)
    cols = {(l.index("AmneziaWG") if "AmneziaWG" in l else l.index("WireGuard"), l.index("192.168.77.4")) for l in rows}
    check("%s: all three rows, the mesh link's included, share their columns" % label, len(rows) == 3 and len(cols) == 1, "\n" + "\n".join(rows))
    rows = migrate_rows(src, fname, {"awg0": MESH["awg0"], "wg0": MESH["wg0"]}, pre)
    check("%s: a list without a long name prints exactly as before" % label,
          rows == ["    awg0       AmneziaWG  192.168.77.4:51821  10.64.2.1/24", "    wg0        WireGuard  192.168.77.4:51820  10.64.1.1/24"],
          "\n" + "\n".join(rows))

print("\n[g] the Docker installer says a given answer — and names one read back from .env as that")
DH = fn(D, "_notty") + fn(D, "_given") + fn(D, "ask_valid") + fn(D, "ask_choice")
out = run('HAVE_TTY=no; INSTALL_DIR=/opt/swg-panel-docker\nv_name(){ [ -n "$1" ]; }\nv_email(){ case "$1" in *@*) return 0;; esac; return 1; }\n' + DH +
          'step(){ [ -n "${_SWG_NL:-}" ] || echo; _SWG_NL=""; echo "Step $1"; }\nstep "3. Node name for THIS box"\n'
          'NODE_NAME=q3m; ask_valid "Node name for THIS box" x NODE_NAME v_name "1-40"\nstep "4. TLS certificate"\n'
          '_GIVEN_ACME_EMAIL=""; ACME_EMAIL=ops@example.com; ask_valid "ACME account email" "" ACME_EMAIL v_email "an email"\n'
          '_GIVEN_TLS_VERIFY=yes; TLS_VERIFY=yes; ask_choice "Verify" y TLS_VERIFY "yes no"\nROLE=master; ask_choice "Select role" m ROLE "master host m h"\n',
          setsid=True)
check("[g] a given node name is said under its step (the step is not left empty)",
      "Node name for THIS box: q3m  (given — not asked)" in out.split("Step 3.", 1)[-1].split("Step 4.", 1)[0], out)
check("[g] …a value this re-install read back from .env is named as that, not as given",
      "ACME account email: ops@example.com  (kept from /opt/swg-panel-docker/.env — not asked)" in out, out)
check("[g] …and a given menu answer is said, tracked or not",
      "Verify: yes  (given — not asked)" in out and "Select role: master  (given — not asked)" in out, out)

print("\n[h] the Docker footer names the stack this box runs")
def footer(names):
    st = tempfile.mkdtemp(prefix="instl-dk-"); open(os.path.join(st, "docker"), "w").write("#!/bin/bash\nprintf '%s'\n" % names); os.chmod(os.path.join(st, "docker"), 0o755)
    return run(fn(C, "node_reconfig_block") + "node_reconfig_block docker /opt/swg-panel-docker\n", st)
cfg = lambda out: next((l.strip() for l in out.splitlines() if "--profile" in l), out)   # the line judged, else all of it
out = footer("swg-panel\\nswg-node\\nswg-sub\\n")   # each check prints the output it judged — not a second run's
check("[h] a master (panel + node containers): `--profile master up -d`", "--profile master up -d" in out, cfg(out))
out = footer("swg-node\\n")
check("[h] a node: `--profile node up -d`", "--profile node up -d" in out, cfg(out))

print("\n[i] a given panel domain is said, not asked (both installers)")
a = H.index('DEF_URL="${PANEL_DOMAIN:-}"; _URL_GIVEN=')
b = H.index("\n", H.index('ask_valid "Enter panel URL (https://…)" "$DEF_URL" PANEL_DOMAIN', a)) + 1
HURL = H[a:b]
def bare_url(given):
    return run('_tty(){ { : </dev/tty; } 2>/dev/null; }\nv_url(){ [ -n "$1" ]; }\ndetect_public_ip(){ echo 10.0.2.15; }\n' + fn(H, "_notty") + fn(H, "_given") + fn(H, "ask_valid") +
               'PANEL_DOMAIN="%s"; PORT=2087; PANEL_BASE=""; DOM_SAVED=""; PORT_SAVED=""; BASE_SAVED=""\n%s\necho "URL=$PANEL_DOMAIN"\n' % (given, HURL), setsid=True)
out = bare_url("192.168.77.1")
check("[i] bare: a given -domain (with its port) is said as given, and used",
      "Enter panel URL (https://…): 192.168.77.1:2087  (given — not asked)" in out and "URL=192.168.77.1:2087" in out and "default taken" not in out, out)
out = bare_url("")
check("[i] bare: none given → the default, said as the default", "(no terminal — default taken)" in out and "URL=10.0.2.15\n" in out, out)
a = D.index('  local def="${PANEL_DOMAIN:-$(detect_public_ip)}"')
b = D.index("\n", D.index('ask_valid "Enter panel URL (https://…)" "$def" PANEL_DOMAIN', a)) + 1
DURL = D[a:b]
def docker_url(given, envd):
    return run('HAVE_TTY=no; INSTALL_DIR=/opt/swg-panel-docker\nv_url(){ [ -n "$1" ]; }\ndetect_public_ip(){ echo 10.0.2.15; }\n' + fn(D, "_notty") + fn(D, "_given") + fn(D, "ask_valid") +
               '_GIVEN_PANEL_DOMAIN="%s"; PANEL_DOMAIN="%s"; PANEL_PORT=2087; PANEL_BASE=""\nf(){\n%s}\nf\necho "URL=$PANEL_DOMAIN"\n' % (given, given or envd, DURL), setsid=True)
out = docker_url("192.168.77.3", "")
check("[i] docker: a given -domain is said as given", "Enter panel URL (https://…): 192.168.77.3:2087  (given — not asked)" in out and "URL=192.168.77.3:2087" in out, out)
out = docker_url("", "192.168.77.3")
check("[i] docker: a re-install's .env domain is the prompt's default (asked, not given)", "(no terminal — default taken)" in out and "given" not in out, out)

print("\n[j] the two-panel answer SWG_OTHER_PANEL gave is said")
st = tempfile.mkdtemp(prefix="instl-2p-")
open(os.path.join(st, "docker"), "w").write('#!/bin/bash\ncase "$1" in ps) echo swg-panel;; esac\nexit 0\n'); os.chmod(os.path.join(st, "docker"), 0o755)
out = run("SWG_OTHER_PANEL=stop\n" + fn(C, "guard_second_panel") + "guard_second_panel baremetal\n", st, setsid=True)
check("[j] the menu's question is answered on screen: stop, given by SWG_OTHER_PANEL",
      "Abort, stop the other, or keep both [a/s/k]: stop  (given by SWG_OTHER_PANEL — not asked)" in out and "stopped a Docker panel" in out, out)

print("\n[k] a dry run says what it WOULD do with the certificate")
t = tempfile.mkdtemp(prefix="instl-dry-")
out = run('DRYRUN=true; PREFIX=%s; TLS_DIR=/etc/swg-panel/tls; PANEL_DOMAIN=example.com\nrun(){ echo "[skip] $*"; }\n' % t
          + fn(H, "san_for") + fn(H, "cert_perms") + fn(H, "mk_selfsigned") + "mk_selfsigned\n")
check("[k] self-signed: \"dry run — would create…\", not a certificate it never made",
      "OK dry run — would create a self-signed certificate for example.com (10y)" in out, out)
out = run('DRYRUN=true; PREFIX=%s; TLS_DIR=/etc/swg-panel/tls; PANEL_DOMAIN=example.com; TLS_MODE=cloudflare; REUSE_TLS=no\n'
          'CF_TOKEN=x; CF_ACCOUNT_ID=""; ACME_EMAIL=a@example.com; ACME_HOME=/root/.acme.sh\nrun(){ echo "[skip] $*"; }\nacme(){ echo "[skip] acme $*"; }\n'
          'ensure_acme(){ :; }; acme_has_cert(){ return 1; }; prune_stale_acme_installs(){ :; }; acme_foreign_target(){ :; }; cert_perms(){ :; }\n'
          'acme_clear_unusable(){ :; }; heal_acme_reloadcmd(){ :; }; acme_copy_foreign(){ :; }; mk_selfsigned(){ echo SELFSIGNED-FALLBACK; }\n' % t
          + fn(H, "obtain_cert_internal") + "obtain_cert_internal\n")
check("[k] cloudflare: \"dry run — would issue + install…\", not \"issued + installed\"",
      "OK dry run — would issue + install a certificate via cloudflare" in out and "OK issued" not in out, out)

print("\n[l] a secret prompt with no terminal says what happened, instead of a blank line")
v = 'v_tok(){ [ -n "$1" ]; }\n' + fn(C, "ask_secret")
out = run(v + 'ask_secret "Cloudflare API token" "saved-token-xyz" CF_TOKEN v_tok "a token"\necho "GOT=${#CF_TOKEN}"\n', setsid=True)
check("[l] a saved one: \"(no terminal — the saved one is kept)\" on the prompt line, and never printed",
      "Cloudflare API token: (no terminal — the saved one is kept)" in out and "saved-token-xyz" not in out and "GOT=15" in out, out)
out = run(v + 'ask_secret "Cloudflare API token" "" CF_TOKEN v_tok "a token"\n', setsid=True)
check("[l] none: \"(no terminal — nothing given)\", then the refusal", "Cloudflare API token: (no terminal — nothing given)" in out and "DIE" in out, out)

print("\n[m] a refused convert pre-flight does not print the convert menu again")
a = B.index("if [ -n \"$CONFLICT\" ]; then\n  while :; do\n"); b = B.index("\n  done\nfi\n", a) + len("\n  done\nfi\n")
LOOP = B[a:b]
bd = tempfile.mkdtemp(prefix="instl-bs-")
open(os.path.join(bd, "convert.sh"), "w").write('#!/bin/bash\necho "PREFLIGHT: an interface name clash"; exit 1\n')
r = subprocess.run(["bash", "-c", PRE + 'mlabel(){ echo "$1"; }\nmenu(){ printf "  %s\\n      %s\\n\\n" "$1" "$2"; }\nkey(){ printf %s "$*"; }\n'
                    'col(){ shift; printf %s "$*"; }\nrun_script(){ echo "RUN $*"; }\nask_yn(){ :; }\n' + fn(B, "ask_choice") +
                    'CONFLICT=yes; OTHER=docker; METHOD=baremetal; OTHER_ROLE=node; ROLE=node; ON_CONFLICT=convert\n' + LOOP],
                   cwd=bd, capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True)
out = r.stdout + r.stderr
check("[m] with `convert` preset and the pre-flight refusing: the menu once, then the stop",
      out.count("is already installed on this box") == 1 and "PREFLIGHT" in out and "the conversion did not go ahead" in out, out)
check("[m] …and the preset answer is said under the menu, once (the bootstrap's own ask_choice)",
      out.count("Convert, keep, or abort (number, letter or name): convert  (given — not asked)") == 1, out)
_m = re.search(r"_pnl\(\)\{[^\n]*?_SWG_NL=1; \}", B); assert _m, "cannot extract bootstrap's _pnl"
r = subprocess.run(["bash", "-c", PRE + _m.group(0) + "\n" + fn(B, "ask_choice") + 'CHOICE=keep; ask_choice "Convert, keep, or abort" convert CHOICE "convert keep abort"\n'],
                   capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True)
check("[m] …with no terminal, and no raw \"/dev/tty: No such device\" from the bootstrap's own blank line",
      "Convert, keep, or abort: keep  (given — not asked)" in r.stdout and "No such device" not in r.stdout + r.stderr, r.stdout + r.stderr)

print("\n[n] a Docker re-install keeps a login whose password it already has")
import base64 as _b64, hashlib as _hl
a = D.index("KEPT_LOGIN=no\ncase \"${PANEL_PASSWORD:-}\" in"); b = D.index("\nfi\n", D.index("# ⚠️ …AND ONE THAT KNOWS IT KEEPS IT TOO.", a)) + 4
M6 = D[a:b]   # both kept-login branches: the one with no password, and the one whose password the hash verifies
TAIL = next(l for l in D.splitlines() if l.startswith('[ "${KEPT_LOGIN:-no}" = yes ] && '))   # the run's last word on a kept login
_DT = DT or D; a = _DT.index("KEPT_LOGIN=no\ncase \"${PANEL_PASSWORD:-}\" in"); b = _DT.index("\nfi\n", _DT.index("# ⚠️ …AND ONE THAT KNOWS IT KEEPS IT TOO.", a)) + 4
M6T = _DT[a:b]
def relogin(pw, block=None):
    d = tempfile.mkdtemp(prefix="instl-m6-"); os.makedirs(os.path.join(d, "data", "etc"))
    salt = b"0123456789abcdef"
    open(os.path.join(d, "data", "etc", "auth"), "w").write("admin613:pbkdf2_sha256$1000$%s$%s\n" % (
        _b64.b64encode(salt).decode(), _b64.b64encode(_hl.pbkdf2_hmac("sha256", b"the-real-pw", salt, 1000)).decode()))
    return run('INSTALL_DIR=%s; KEEP_AUTH=no; PROFILE=master; EXISTING_DOCKER=yes; SWG_CONVERT_DIR=""\n'
               'PANEL_USER=admin613; PANEL_PASSWORD="%s"\n%s\necho "KEEP=$KEEP_AUTH KEPT=$KEPT_LOGIN PW=$PANEL_PASSWORD"\n%s\n' % (d, pw, block or M6, TAIL))
out = relogin("the-real-pw")
check("[n] .env holds the password the login already has → the login is kept, nothing to print",
      "KEEP=yes KEPT=no PW=(preserved)" in out and "its password is the one it already has" in out, out)
out = relogin("the-real-pw", M6T)
check("[n] …and the run does not end saying it \"had none to set\" (it had it — round 5, q6)",
      "its password is the one it already has" in out and "had none to set" not in out, out)
out = relogin("a-new-pw")
check("[n] a different password → applied, as asked", "KEEP=no KEPT=no PW=a-new-pw" in out, out)
out = relogin("")
check("[n] no password at all (after an uninstall) → kept, and the run's last line says why and how to reset it",
      "KEEP=yes KEPT=yes PW=(preserved)" in out and "this re-install had none to set" in out, out)

print("\n[o] a node re-install writes its mesh links back into config.json")
t = tempfile.mkdtemp(prefix="instl-ni-")
for n in ("wg0", "swg_ab"):
    open(os.path.join(t, n + ".conf"), "w").write("[Interface]\nListenPort = 51820\n")
cfg = os.path.join(t, "config.json")
json.dump({"interfaces": {"wg0": {"cmd": ["wg"], "conf": os.path.join(t, "wg0.conf")},
                          "swg_ab": {"cmd": ["awg"], "conf": os.path.join(t, "swg_ab.conf")},
                          "wgGONE": {"cmd": ["wg"], "conf": os.path.join(t, "gone.conf")}}}, open(cfg, "w"))
a = N.index('    SELECTED=(); while IFS= read -r n; do [ -n "$n" ] && SELECTED+=("$n"); done < <(node_ifaces)\n')
SEL = N[a:N.index("\n", a) + 1]
out = run(fn(N, "node_ifaces").replace("/etc/swg-agent/config.json", cfg) + 'f(){\n' + SEL + '}\nf\necho "SELECTED=${SELECTED[*]}"\n'
          'declare -A IF_CONF=([wg0]=%s/wg0.conf [swg_ab]=%s/swg_ab.conf)\n' % (t, t) + fn(N, "turn_wg_ports") + 'echo "PORTS=$(turn_wg_ports | tr "\\n" " ")"\n')
check("[o] the managed set a re-install writes back keeps the mesh link (and still skips a ghost whose conf is gone)",
      "SELECTED=wg0 swg_ab\n" in out, out)
check("[o] …and a mesh link is not offered as a turn-proxy forward target", "PORTS=wg0:51820 \n" in out, out)

print("\n[p] a dry run says what it did — not the live box's summary")
a = H.index("# ⚠️ A DRY RUN HAS NOTHING TO SUMMARISE — install-docker.sh's rule, here too.")
a = H.rindex('if [ -z "${SWG_CONVERT_DIR:-}" ]; then\n', 0, a)
b = H.index('if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun"; fi', a); b = H.index("\n", b) + 1
HSUM = H[a:b]
def host_sum(dry, tls="selfsigned", port="2097"):
    return run('DRYRUN=%s; TLS_MODE=%s; CERT_FULLCHAIN=""; PORT=%s; PANEL_DOMAIN=192.168.77.6; PANEL_BASE=""; ROLE_SEL=host\n'
               'EXISTING_HOST=no; PANEL_UP=yes; KEEP_AUTH=no; BASIC_PASS=dryrun-pass-1; _PASS_GIVEN=no; SWG_CONVERT_DIR=""\n'
               'print_summary(){ echo "PRINT_SUMMARY $* login-pass=${SWG_SUMMARY_PASS:-}"; }\n%s' % (dry, tls, port, HSUM))
out = host_sum("true")
check("[p] install-host.sh --dry-run: \"Dry run … finished — nothing was installed or changed\", and where it would serve",
      "OK Dry run of the bare-metal host install finished — nothing was installed or changed." in out
      and "The panel would be served at https://192.168.77.6:2097/ (TLS selfsigned)." in out and "DRY RUN done" in out, out)
check("[p] …no \"Host install complete\", no live-box summary, and never this run's password under a login",
      "PRINT_SUMMARY" not in out and "install complete" not in out.lower() and "dryrun-pass-1" not in out, out)
out = host_sum("true", tls="skip", port="443")
check("[p] …plain HTTP on 443 reads as such", "The panel would be served at http://192.168.77.6/ (TLS skip)." in out, out)
out = host_sum("false")
check("[p] a real install still prints the summary, with the login it minted",
      "OK Host install complete." in out and "PRINT_SUMMARY INSTALL login-pass=dryrun-pass-1" in out and "Dry run" not in out, out)
a = N.index('# ⚠️ A DRY RUN HAS NOTHING TO SUMMARISE (install-host.sh / install-docker.sh)')
b = N.index('if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun"; fi', a); b = N.index("\n", b) + 1
NSUM = N[a:b]
def node_sum(dry, fp):
    return run('DRYRUN=%s; EXISTING=no; PANEL_URL=https://192.168.77.3:2087; TLS_FINGERPRINT="%s"; VERIFY_JSON=false; _PNAME=q6n\n'
               'print_summary(){ echo "PRINT_SUMMARY $*"; }\n%s' % (dry, fp, NSUM))
out = node_sum("true", "abcdef0123456789ffff")
check("[p] install-node.sh --dry-run: says it did nothing, and what the node would sync to, with the pin",
      "OK Dry run of the bare-metal node install finished — nothing was installed or changed." in out
      and "The node would sync to https://192.168.77.3:2087 (panel cert pinned, sha256 abcdef0123456789…)." in out
      and "PRINT_SUMMARY" not in out and "install complete" not in out, out)
out = node_sum("true", "")
check("[p] …an unpinned, unverified one says so", "(certificate NOT verified)." in out, out)
out = node_sum("false", "abcdef0123456789ffff")
check("[p] a real node install still prints \"install complete\" and the summary",
      "OK Node 'q6n' install complete." in out and "PRINT_SUMMARY INSTALL" in out and "panel cert pinned (sha256 abcdef0123456789…)" in out, out)

print("\n[q] every prompt with no terminal says the answer it took (not a blank line)")
def pair(src, needle):
    i = src.index(needle); j = src.index("\n", i); k = src.index("\n", j + 1)
    return src[src.rindex("\n", 0, i) + 1:k + 1]
for src, label in ((H, "install-host.sh"), (D, "install-docker.sh")):
    for needle, ans, pre in (("type %s, or enter a new URL to change: '", "proceed", "URL_PORT=2097"),
                             ("anyway: ' \"$(bb force)\" \"$_pp\"", "force", "_pp=443")):
        out = run('%s\n%secho "ANS=$_url_ans"\n' % (pre, pair(src, needle)), setsid=True)
        line = next((l for l in out.splitlines() if "anyway:" in l or "to change:" in l), "")
        check("[q] %s: the %s prompt ends in its answer" % (label, ans),
              line.rstrip().endswith(": %s  (no terminal — default taken)" % ans) and "ANS=%s" % ans in out, out)
for src, label in ((N, "install-node.sh"), (H, "install-host.sh")):
    out = run('_tty(){ { : </dev/tty; } 2>/dev/null; }\n' + fn(src, "_notty") + fn(src, "_given") + fn(src, "ask") + fn(src, "ask_yn") +
              'ask "Subscription page hostname" "" SUB_DOMAIN\necho "SUB=[$SUB_DOMAIN]"\n'
              'ask_yn "Verify the panel\'s TLS certificate? (auto-detected default: yes)" y TLS_VERIFY\necho "V=$TLS_VERIFY"\n', setsid=True)
    check("[q] %s: ask and ask_yn say the default they took" % label,
          "Subscription page hostname: (blank)  (no terminal — default taken)" in out and "SUB=[]" in out
          and "Verify the panel's TLS certificate? (auto-detected default: yes): yes  (no terminal — default taken)" in out and "V=yes" in out, out)
i = B.index("Number to re-enroll with"); PICK = B[B.rindex("\n", 0, i) + 1:B.index("\n", i) + 1]
out = run(PICK + 'echo "PICK=[$_pick]"\n', setsid=True)
check("[q] bootstrap.sh: the re-enroll pick says it skipped", "to skip and set up a new node" in out
      and "): (no terminal — skipped)" in out and "PICK=[]" in out, out)

print("\n[r] a dry run claims no verdict it never reached; the uninstaller says the answers it took")
out = run('DRYRUN=true; EXISTING=no; PANEL_URL=https://192.168.77.3:2087; TLS_FINGERPRINT=""; VERIFY_JSON=true; _TLS_DRY_UNPROBED=1; _PNAME=q6n\n'
          'print_summary(){ echo "PRINT_SUMMARY $*"; }\n' + NSUM)
check("[r] install-node.sh --dry-run: an unprobed panel is not called CA-verified",
      "(its certificate is not checked in a dry run — the real run verifies a CA one or pins a self-signed one)." in out
      and "CA-verified" not in out, out)
a = D.index('elif $DRYRUN; then\n  echo; ok "Dry run of the docker'); b = D.index('\nelse\necho; ok "Docker install complete', a)
DSUM = "if false; then :\n" + D[a:b] + "\nfi\n"
out = run('DRYRUN=true; PROFILE=node; EXISTING_DOCKER=no; PANEL_URL=https://192.168.77.3:2087; TLS_FINGERPRINT=""; TLS_VERIFY=no; _TLS_DRY_WOULD_PIN=1\n' + DSUM)
check("[r] install-docker.sh --dry-run: a self-signed panel reads as \"the real run pins its certificate\"",
      "(self-signed — the real run pins its certificate)." in out and "NOT verified" not in out, out)
out = run('DRYRUN=true; PROFILE=node; EXISTING_DOCKER=no; PANEL_URL=https://192.168.77.3:2087; TLS_FINGERPRINT=""; TLS_VERIFY=yes\n' + DSUM)
check("[r] …and a CA panel still reads CA-verified", "(CA-verified)." in out, out)
i = U.index("ask_yn(){"); j = U.index("echo; }   # one trailing blank after the prompt", i); j = U.index("\n", j) + 1
AYN = U[i:j]
out = run(AYN + 'ask_yn "  Delete the data dir?" n DEL; echo "DEL=$DEL"\n', setsid=True)
check("[r] uninstall.sh: with no terminal a question says the default it took",
      "  Delete the data dir? no  (no terminal — default taken)" in out and "DEL=no" in out, out)
out = run(AYN + 'KEEP=y; ask_yn "  Keep the configs?" n KEEP; echo "KEEP=$KEEP"\n', setsid=True)
check("[r] …and a given answer is said as given", "  Keep the configs? yes  (given — not asked)" in out and "KEEP=yes" in out, out)

print("\n[s] the summary names a host turn proxy by what its clients dial (FN-2(a))")
SNB = fn(C, "summary_node_block")
_dial = ("        lis=\"$(sed -n 's/^SWG_DIAL=//p' \"/opt/vk-turn-proxy/$inst/turn.env\" 2>/dev/null | sed -n 1p || true)\"\n"
         "        [ -n \"$lis\" ] || lis=")
assert SNB.count(_dial) == 1, "the dial read is not where [s] reads it — would FALSE-PASS"
if PERTURB_DIAL:
    SNB = SNB.replace(_dial, "        lis=")
_st = tempfile.mkdtemp(prefix="instl-sum-")
for _n, _env in (("wings-56000", "SWG_LISTEN=0.0.0.0:56000\nSWG_DIAL=home.ddns.net:56000\nSWG_CONNECT=127.0.0.1:51820\n"),
                 ("anton-56001", "SWG_LISTEN=203.0.113.7:56001\nSWG_CONNECT=127.0.0.1:51821\n")):
    os.makedirs(os.path.join(_st, "units"), exist_ok=True); os.makedirs(os.path.join(_st, "opt", _n))
    open(os.path.join(_st, "units", "vk-turn-proxy-%s.service" % _n), "w").write("x")
    open(os.path.join(_st, "opt", _n, "turn.env"), "w").write(_env)
_snb = SNB.replace("/etc/systemd/system/vk-turn-proxy-", _st + "/units/vk-turn-proxy-").replace("/opt/vk-turn-proxy/", _st + "/opt/")
out = run('_sum_node_ep(){ :; }; _sum_node_purl(){ :; }; _sum_note(){ :; }; _sum_iface_row(){ :; }; _sum_wdtt_block(){ :; }\n'
          '_sum_csqtt_block(){ :; }; node_reconfig_block(){ :; }; _sum_fwd_iface(){ :; }; _SUM_DDIR=/nonexistent\n%s%s'
          'summary_node_block baremetal no\n' % (fn(C, "_sum_turn_row"), _snb))
check("[s] a proxy behind NAT / on a DDNS name: listed by the name its clients dial, not its bind",
      "vk-turn-proxy-wings-56000 home.ddns.net:56000 → 127.0.0.1:51820" in out and "0.0.0.0:56000" not in out, out)
check("[s] …one with no dial host of its own: by its listen, as before", "vk-turn-proxy-anton-56001 203.0.113.7:56001 → 127.0.0.1:51821" in out, out)

print("\n[t] dnsmasq is masked before its package is installed (1.8.8 deferred #5(b))")
for f, src in (("install-node.sh", N), ("install-host.sh", H)):
    est = fn(src, "ensure_smart_tools")
    _m = "run systemctl mask dnsmasq 2>/dev/null || true; run apt-get install -y dnsmasq"
    assert est.count(_m) == 1, "the mask is not where [t] reads it"
    if PERTURB_MASK:
        est = est.replace(_m, "run apt-get install -y dnsmasq")
    out = run('C=$(mktemp)\nhave(){ case "$1" in dnsmasq|nft|ipset) return 1;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
              'run(){ echo "RUN $*" >> "$C"; }\n%sensure_smart_tools\ncat "$C"\n' % est)
    calls = [l for l in out.splitlines() if l.startswith("RUN ")]
    im = next((i for i, l in enumerate(calls) if l.startswith("RUN apt-get install -y dnsmasq")), -1)
    mm = next((i for i, l in enumerate(calls) if l == "RUN systemctl mask dnsmasq"), -1)
    check("[t] %s: masked before its package is installed" % f, 0 <= mm < im, calls)

print()
if PERTURB_MASK:
    _red = [x for x in FAILS if x.startswith("[t]")]
    print("perturb-mask: %s" % ("RED as it must be (%d), all [t]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_DIAL:
    _red = [f for f in FAILS if f.startswith("[s]")]
    print("perturb-dial: %s" % ("RED as it must be (%d), all [s]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
