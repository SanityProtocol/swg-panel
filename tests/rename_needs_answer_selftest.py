#!/usr/bin/env python3
"""Self-test — A RE-INSTALL NEVER RENAMES A NODE WITH A NAME THE PANEL DID NOT GIVE, UNASKED.

1.8.8 qualification, round 8: when whoami gave no name — refused (a certificate the node does not trust), a 404, a
timeout, an answer that names no node — the name offered was this box's hostname, and an unattended re-install then
POSTed /api/node/rename with it (R21-E-q2-ca-rightname: one rename among the requests the stand-in panel received). The
twins did the same: install-docker.sh's convert branch compared with the empty answer, install-host.sh's master rename
with nothing at all. The default is still the name known here; a rename goes out only when it differs from what was
offered — typed at a terminal, given, or the panel's own name changed.

Each block is lifted from the shipped script; panel_req is a stub that answers whoami as told and records every call.
  [1] install-node.sh (a bare node re-install): the panel names it → offered, unchanged → nothing pushed; typed → pushed
  [2] …no name from the panel (refused / 404 / timeout / an answer without one), NO TERMINAL → no rename, one line says why
  [3] …the same at a terminal, a new name typed → pushed; Enter (the offered name) → nothing
  [4] install-docker.sh (a convert's node step, ask_node_conn + the push): the same three
  [5] install-host.sh (a master's local node): no answer + the offered name kept → no rename; a different one → pushed

Run: python3 tests/rename_needs_answer_selftest.py     (0 = pass)
     --perturb          install-node.sh's shipped rule (a default is pushed when the panel named nothing) → RED on [2]
     --perturb-docker   install-docker.sh's shipped rule → RED on [4]
     --perturb-host     install-host.sh's shipped rule (compared with nothing) → RED on [5]
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
MODE = next((a for a in sys.argv[1:] if a in ("--perturb", "--perturb-docker", "--perturb-host")), None)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if MODE == "--perturb":
    N = plant(N, '  [ "$PUSH_NAME" = "${_cur:-$NODE_NAME}" ] && PUSH_NAME=""    # what was offered → nothing to push\n',
              '  [ -n "$_cur" ] && [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""\n')
if MODE == "--perturb-docker":
    D = plant(D, '    [ "$PUSH_NAME" = "$_dflt" ] && PUSH_NAME=""\n    return 0\n', '    [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""\n    return 0\n')
if MODE == "--perturb-host":
    H = plant(H, '[ "$HOST_NODE_NAME" != "${_cur:-${_HOST_NAME_DEFAULT:-}}" ]', '[ "$HOST_NODE_NAME" != "$_cur" ]')

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

def block(src, a, b, incl=True):
    assert src.count(a) == 1, "block anchor missing — would FALSE-PASS: " + a[:80]
    i = src.index(a); j = src.index(b, i) + (len(b) if incl else 0)
    return src[i:j] + "\n"

T = tempfile.mkdtemp(prefix="rename-")
LOG = os.path.join(T, "calls")
# panel_req, as told: WHOAMI=name → answers it; WHOAMI=- → an answer that names no node; WHOAMI=refused|404|timeout
STUB = r'''panel_req(){ echo "$1 $2 ${SWG_BODY:-}" >> "%s"
  case "$2" in
    */whoami) case "${WHOAMI:-}" in
        refused) echo "the panel presents a certificate other than the pinned one (sha256 ab…, pinned cd…) — nothing was sent"; return 4;;
        404)     echo "HTTP 404"; return 3;;
        timeout) echo "timed out"; return 1;;
        -)       echo '{"ok": true, "data": {}}';;
        *)       printf '{"ok": true, "data": {"name": "%%s"}}' "$WHOAMI";; esac;;
    *) echo '{"ok": true}';; esac; }
''' % LOG
PRE = ('set -u\ninfo(){ echo "INFO $*"; }; warn(){ echo "WARN $*" >&2; }; step(){ :; }; b(){ printf %s "$*"; }\n'
       'col(){ shift; printf %s "$*"; }; _pnl(){ :; }; _SWG_NL=""; DRYRUN=false\n'
       'hostname(){ echo box-host; }\nv_name(){ case "$1" in ""|*[!A-Za-z0-9_-]*) return 1;; esac; return 0; }\n')
REAL_ASK = fn(N, "_tty") + fn(N, "_notty") + fn(N, "_given") + fn(N, "ask_valid")   # no terminal → the default is taken
TYPED = lambda name: 'ask_valid(){ printf -v "$3" %%s "%s"; }\n' % name            # a terminal, a name typed
ENTER = 'ask_valid(){ printf -v "$3" %s "$2"; }\n'                                   # a terminal, Enter

def run(script, whoami):
    open(LOG, "w").close()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, WHOAMI=whoami), start_new_session=True)
    calls = [l for l in open(LOG).read().splitlines()]
    assert any("/api/node/whoami" in c for c in calls), "the block never asked whoami — this run would FALSE-PASS: %r" % (r.stdout + r.stderr)[-300:]
    return [c for c in calls if "/api/node/rename" in c], r.stdout + r.stderr

NBLK = block(N, 'NODE_NAME="${NODE_NAME:-$(hostname -s 2>/dev/null || hostname)}"', '\nstep "Datapath tooling"\n', False)
def node(ask, whoami):
    return run(PRE + STUB + ask + 'EXISTING=yes; SWG_CONVERT=""; NODE_TOKEN=tok; PANEL_URL=https://p:2087; TLS_VERIFY=no; TLS_FINGERPRINT=""\n'
               + NBLK, whoami)

print("[1] install-node.sh: the panel names the node")
ren, out = node(REAL_ASK, "q2n")
check("[1] no terminal, the panel says q2n → nothing pushed", ren == [], (ren, out))
ren, out = node(TYPED("q2-new"), "q2n")
check("[1] a new name typed → one rename, with it", len(ren) == 1 and '"q2-new"' in ren[0], (ren, out))

print("\n[2] install-node.sh: no name from the panel, no terminal")
for w in ("refused", "404", "timeout", "-"):
    ren, out = node(REAL_ASK, w)
    check("[2] whoami %s → NO rename (the hostname is never pushed unasked)" % w, ren == [], (ren, out[-300:]))
    check("[2] …and one line says the panel did not name it, and why", "did not say what it calls this node" in out, out[-300:])

print("\n[3] install-node.sh: no name from the panel, at a terminal")
ren, out = node(TYPED("q2-typed"), "refused")
check("[3] a new name typed → pushed (the operator asked for it)", len(ren) == 1 and '"q2-typed"' in ren[0], (ren, out))
ren, out = node(ENTER, "404")
check("[3] Enter on the offered name (this box's) → nothing pushed", ren == [], (ren, out))

print("\n[4] install-docker.sh: a convert's node step")
DBLK = fn(D, "ask_node_conn") + "ask_node_conn\n" + block(D, "# push a box-name change once ask_node_conn has it",
                                                          "\n# ───────────────────────── ensure Docker", False)
def docker(ask, whoami):
    return run(PRE + STUB + ask + 'SWG_CONVERT_DIR=convert-docker; NODE_TOKEN=tok; PANEL_URL=https://p:2087; TLS_VERIFY=no; '
               'TLS_FINGERPRINT=""; PUSH_NAME=""; NODE_NAME=""\n' + DBLK, whoami)
ren, out = docker(REAL_ASK, "q4n")
check("[4] the panel says q4n, no terminal → nothing pushed", ren == [], (ren, out))
for w in ("refused", "404", "-"):
    ren, out = docker(REAL_ASK, w)
    check("[4] whoami %s, no terminal → NO rename" % w, ren == [], (ren, out[-300:]))
ren, out = docker(TYPED("q4-typed"), "timeout")
check("[4] no answer, a new name typed → pushed", len(ren) == 1 and '"q4-typed"' in ren[0], (ren, out))

print("\n[5] install-host.sh: a master's local node")
HBLK = block(H, 'if [ "$EXISTING_HOST" = yes ] && ! $DRYRUN && [ "$HOST_HAS_WG" = yes ] && [ -n "${LC_URL:-}" ] && [ -n "${LC_TOKEN:-}" ]; then', "\nfi\n")
def host(name, dflt, whoami):
    return run(PRE + STUB + 'EXISTING_HOST=yes; HOST_HAS_WG=yes; LC_URL=http://127.0.0.1:8088; LC_TOKEN=tok; LC_VERIFY=no; LC_FP=""\n'
               'HOST_NODE_NAME="%s"; _HOST_NAME_DEFAULT="%s"\n' % (name, dflt) + HBLK, whoami)
ren, out = host("q5m", "q5m", "404")
check("[5] whoami 404, the offered name kept → NO rename", ren == [], (ren, out))
ren, out = host("q5m", "q5m", "timeout")
check("[5] whoami timed out, the offered name kept → NO rename", ren == [], (ren, out))
ren, out = host("q5-new", "q5m", "404")
check("[5] no answer, a different name (typed or given) → pushed", len(ren) == 1 and '"q5-new"' in ren[0], (ren, out))
ren, out = host("q5m", "q5m", "q5-old")
check("[5] the panel says q5-old, q5m chosen → pushed (the panel's name changes to it)", len(ren) == 1 and '"q5m"' in ren[0], (ren, out))
ren, out = host("q5m", "q5m", "q5m")
check("[5] the panel already says q5m → nothing pushed", ren == [], (ren, out))

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
