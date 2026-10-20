#!/usr/bin/env python3
"""Self-test — a node re-install never takes a CHANGED panel certificate silently (bare metal, and the Docker path too).

A bare-metal node re-install re-decided its trust from scratch: a panel presenting a DIFFERENT certificate from the one
the node had pinned was re-pinned with one info line ("pinning it (sha256 …)"); the Docker installer warned and then
did the same (1.8.8 qualification, round 4). A machine intercepting the node's traffic presents a different certificate
too, and the node would hand it its panel token and take its peer set from it. Now, on both paths (panel_pin_changed,
lib/common.sh): at a terminal the operator is asked, No by default; with no terminal it is refused, with the way to
accept it (TLS_FINGERPRINT=<the new one>). An unchanged or unreachable panel keeps the pin, as the Docker path did.

  THE BARE NODE (install-node.sh's re-install block and _panel_fp, lifted as shipped; a live self-signed listener)
    [1] same certificate → the pin is kept, and it says so
    [2] a CHANGED certificate, no terminal → the OLD pin is kept, with a CHANGED warning and TLS_FINGERPRINT=<new>
    [3] …at a terminal: y → re-pinned to the new one; Enter (the default) → the old pin is kept
    [4] the panel unreachable → the pin is kept (a panel outage must not cost a node its pin)
    [5] a re-install pointed at ANOTHER panel URL, or one with no pin: not this block's decision (a fresh one follows)
  THE DOCKER NODE (install-docker.sh node_panel_trust, lifted as shipped)
    [6] a CHANGED certificate, no terminal → the old pin is kept (it used to re-pin with a warning)
  ROUND 6 → 7 (1.8.8 qualification)
    [2][3][6] a KEPT old pin now STOPS the run right there (pin_kept_stop): nothing on the box changed, the token went
        nowhere — the run used to carry on, and post its lifecycle with the token past the pin it had just kept
    [7] the question is SEEN at a terminal: panel_pin_changed printed it with `read -rp … 2>/dev/null`, i.e. to /dev/null
        — the operator saw the warning, then silence (round 6, a Docker node at a pty)
    [8] a new certificate that a public CA vouches for is offered as CA VERIFICATION, never pinned: y → TLS_VERIFY=yes and
        no pin (a pinned CA certificate stops the node at its first renewal); unattended → refused, pointing at
        TLS_VERIFY=yes; both paths (bare + Docker)
    [9] a bare node that VERIFIES its panel through its CA is never re-pinned by a re-install (the fresh decision's probe
        read a now-self-signed panel as "self-signed — pinning it": trust on first use, on a second use); the Docker
        path already keeps CA verification
    [10] a dry run's trust question claims no detection it never made: it said "(auto-detected default: yes)" without
        probing anything (round 6) — now "(not probed in a dry run — default: yes)"
  ROUND 8
    [11] a pin on record that is not a sha256 is said to be one, not "CHANGED (was 56f1d0c2…, now 56f1d0c2…)" — the same
        sixteen characters twice; the decision is the same (refused unattended, the run stops)

Run: python3 tests/panel_pin_change_selftest.py      (0 = pass)
     --plant <bare|silent|docker|goon|invisible|ca|tofu|dryq|malformed>   plant one old behaviour → RED (exit 0 when caught);
     --perturb plants all of them
"""
import hashlib, http.server, os, re, socket, ssl, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
ALL = ("bare", "silent", "docker", "goon", "invisible", "ca", "tofu", "dryq", "malformed")
PLANTS = set(ALL) if "--perturb" in sys.argv else ({sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[-500:]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

BARE_A = "# ⚠️ A RE-INSTALL KEEPS THE PIN IT HAS."
BARE_B = 'if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ]; then\n  # Verify the panel\'s TLS certificate by DEFAULT (secure).'
if "bare" in PLANTS:      # the shipped bare path: no re-install block — every run decided afresh (and TOFU re-pinned)
    a = N.index(BARE_A); b = N.index("# ⚠️ …AND ONE THAT VERIFIES THIS PANEL THROUGH ITS CA KEEPS DOING SO.")   # (the pin block only)
    N = N[:a] + N[b:]
if "silent" in PLANTS:    # a changed certificate taken without a word
    C = plant(C, 'panel_pin_changed(){ local old="$1" new="$2" url="${3:-}" v="" ca=no q _on\n', 'panel_pin_changed(){ return 0\n')
if "docker" in PLANTS:    # the shipped Docker path: warn, then decide afresh
    D = plant(D, '    panel_pin_changed "$_old" "$_fp" "$PANEL_URL" || pin_kept_stop\n'
                 '    if [ "${PIN_TO_CA:-}" = yes ]; then TLS_VERIFY=yes; TLS_FINGERPRINT=""; else TLS_FINGERPRINT="$_fp"; TLS_VERIFY=no; fi\n'
                 '    return 0\n',
              '    warn "the panel\'s certificate CHANGED since this node pinned it — deciding afresh"\n')

if "goon" in PLANTS:      # the round-6 shape: a kept pin carries on with the run
    C = plant(C, '  exit 1; }\n# panel_ca_ok', '  return 0; }\n# panel_ca_ok')
if "invisible" in PLANTS: # the round-6 prompt: read -p's prompt sent to /dev/null with its stderr
    C = plant(C, "    printf '  %s' \"$q\" 2>/dev/null >/dev/tty\n    read -r v <\"${SWG_TTY:-/dev/tty}\" 2>/dev/null || v=\"\"\n",   # SWG_TTY: 80d5f71
              '    read -rp "  $q" v <"${SWG_TTY:-/dev/tty}" 2>/dev/null || v=""\n')
if "ca" in PLANTS:        # a CA-valid new certificate asked (and pinned) like a self-signed one
    C = plant(C, '  [ -n "$url" ] && panel_ca_ok "$url" && ca=yes\n', '')
if "tofu" in PLANTS:      # the bare fresh decision re-probes a CA-verified node's panel (and pins a self-signed one)
    N = plant(N, 'if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ] && [ "$EXISTING" = yes ] && [ "$EXIST_VERIFY" = yes ] && [ -z "$EXIST_FP" ] \\\n',
              'if false && [ -z "$TLS_FINGERPRINT" ] && [ "$EXISTING" = yes ] && [ "$EXIST_VERIFY" = yes ] && [ -z "$EXIST_FP" ] \\\n')
if "malformed" in PLANTS:  # round 8's text: a damaged pin read as a changed certificate
    C = plant(C, """  if ! printf '%s' "$_on" | grep -cxE '[0-9a-f]{64}' >/dev/null; then""", "  if false; then")
if "dryq" in PLANTS:      # the round-6 dry-run question: an "auto-detected default" nothing detected
    N = plant(N, '_TLS_DRY_UNPROBED=1; _tls_why="not probed in a dry run — default"; fi', '_TLS_DRY_UNPROBED=1; fi')

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

T = tempfile.mkdtemp(prefix="pinchg-")
CERT, KEY = os.path.join(T, "c.pem"), os.path.join(T, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", KEY, "-out", CERT], check=True, capture_output=True)
SERVED = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(CERT).read())).hexdigest()
OLD = "ab" * 32

class Hd(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a):
        pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(CERT, KEY)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
LIVE = "https://127.0.0.1:%d" % srv.server_address[1]
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); DEAD = "https://127.0.0.1:%d" % _s.getsockname()[1]; _s.close()

COMMON = fn(C, "panel_pin_changed") + fn(C, "pin_kept_stop") + fn(C, "panel_ca_ok")
PRE = ('set -euo pipefail\nDRYRUN=false; BOLD=""; RESET=""\nok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ echo "SUB $*"; }\n'
       'info(){ echo "INFO $*"; }; b(){ printf %s "$*"; }\n')
a = N.index(BARE_A) if "bare" not in PLANTS else None
BLOCK = N[a:N.index("# ⚠️ …AND ONE THAT VERIFIES THIS PANEL THROUGH ITS CA KEEPS DOING SO.")] if a is not None else ""   # (round 7: the CA-verified block sits between)

def run(script, answer):
    f = os.path.join(T, "s.sh"); open(f, "w").write(script)
    if answer is None:
        r = subprocess.run(["bash", f], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, start_new_session=True)
    else:
        r = subprocess.run(["script", "-qec", "bash " + f, "/dev/null"], input=answer, capture_output=True, text=True,
                           timeout=120, start_new_session=True)
    out = r.stdout + r.stderr
    m = re.search(r"RESULT verify=(\S*) fp=(\S*)", out)
    return ((m.group(1), m.group(2)) if m else (None, None)), out

def bare(url, exist_url, exist_fp, answer=None):
    return run(PRE + fn(N, "_panel_fp") + COMMON + 'PANEL_URL="%s"; EXIST_URL="%s"; EXIST_FP="%s"; TLS_VERIFY=""; TLS_FINGERPRINT=""\n%s\n'
               'echo "RESULT verify=$TLS_VERIFY fp=$TLS_FINGERPRINT"\n' % (url, exist_url, exist_fp, BLOCK), answer)

STOP = "stopped before changing anything"
print("[1]–[5] the bare-metal node's re-install")
(v, fp), out = bare(LIVE, LIVE, SERVED)
check("[1] same certificate → the pin is kept", (v, fp) == ("no", SERVED), out)
check("[1] …and it says the panel still presents it", "still presents" in out, out)
(v, fp), out = bare(LIVE, LIVE, OLD)
check("[2] a CHANGED certificate, no terminal → the OLD pin is kept and the run STOPS there",
      (v, fp) == (None, None) and "kept the old pin" in out and STOP in out, out)
check("[2] …with a CHANGED warning and the way to accept the new one", "CHANGED" in out and ("TLS_FINGERPRINT=" + SERVED) in out, out)
(v, fp), out = bare(LIVE, LIVE, OLD, "y\n")
check("[3] at a terminal, y → re-pinned to the new certificate", (v, fp) == ("no", SERVED), out)
(v, fp), out = bare(LIVE, LIVE, OLD, "\n")
check("[3] at a terminal, Enter (the default) → the old pin is kept and the run stops", (v, fp) == (None, None) and STOP in out, out)
check("[7] …and the question was ON the terminal (the operator can see what Enter answers)",
      "Trust the new certificate? (y/N)" in out, out)
(v, fp), out = bare(DEAD, DEAD, OLD)
check("[4] the panel unreachable → the pin is kept", (v, fp) == ("no", OLD), out)
(v, fp), out = bare(LIVE, DEAD, OLD)
check("[5] another panel URL → not this block's decision (the fresh one after it decides)", (v, fp) == ("", ""), out)
(v, fp), out = bare(LIVE, LIVE, "")
check("[5] no pin on record → not this block's decision either", (v, fp) == ("", ""), out)

BAD = SERVED[:40] + "zz" + SERVED[42:]                     # a damaged pin: the same first sixteen characters
(v, fp), out = bare(LIVE, LIVE, BAD)
check("[11] a pin on record that is not a sha256 → said so (not \"CHANGED\" between two identical prefixes)",
      "is not a sha256 fingerprint" in out and "CHANGED" not in out, out)
check("[11] …and the decision is the same: refused unattended, the run stops", (v, fp) == (None, None) and STOP in out, out)

print("\n[6] the Docker node's re-install")
DFN = "\n".join(fn(D, n) for n in ("_docker_panel_fp", "ask_tty", "ask_yn_tty", "node_panel_trust"))
def docker(url, old, answer=None):
    return run(PRE + 'HAVE_TTY=no; _SWG_NL=""; C_BLUE=""; C_GREEN=""; C_BL=""; C_BROWN=""; _nlguard(){ :; }\n' + COMMON
               + 'panel_cert_expired(){ return 1; }\n' + DFN
               + '\nPANEL_URL="%s"; TLS_VERIFY=""; TLS_FINGERPRINT=""\nnode_panel_trust "%s"\n'
               'echo "RESULT verify=$TLS_VERIFY fp=$TLS_FINGERPRINT"\n' % (url, old), answer)
(v, fp), out = docker(LIVE, OLD)
check("[6] a CHANGED certificate, no terminal → the OLD pin is kept and the run STOPS (it used to re-pin with a warning)",
      (v, fp) == (None, None) and "kept the old pin" in out and STOP in out, out)
(v, fp), out = docker(LIVE, OLD, "y\n")
check("[6] …at a terminal, y → re-pinned", (v, fp) == ("no", SERVED), out)
(v, fp), out = docker(LIVE, OLD, "\n")
check("[7] …at a terminal the question is ON the terminal (Docker path too), and Enter stops the run",
      "Trust the new certificate? (y/N)" in out and (v, fp) == (None, None) and STOP in out, out)

print("\n[8] a new certificate a public CA vouches for — CA verification, never a pin")
CAK, CAC = os.path.join(T, "ca.key"), os.path.join(T, "ca.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=swg test CA",
                "-keyout", CAK, "-out", CAC], check=True, capture_output=True)
SK, SCSR, SC = os.path.join(T, "s.key"), os.path.join(T, "s.csr"), os.path.join(T, "s.pem")
subprocess.run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=127.0.0.1", "-keyout", SK, "-out", SCSR],
               check=True, capture_output=True)
open(os.path.join(T, "san.ext"), "w").write("subjectAltName=IP:127.0.0.1\n")
subprocess.run(["openssl", "x509", "-req", "-in", SCSR, "-CA", CAC, "-CAkey", CAK, "-CAcreateserial", "-days", "30",
                "-extfile", os.path.join(T, "san.ext"), "-out", SC], check=True, capture_output=True)
CASERVED = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(SC).read())).hexdigest()
casrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hd)
cactx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); cactx.load_cert_chain(SC, SK)
casrv.socket = cactx.wrap_socket(casrv.socket, server_side=True)
threading.Thread(target=casrv.serve_forever, daemon=True).start()
CALIVE = "https://127.0.0.1:%d" % casrv.server_address[1]
os.environ["SSL_CERT_FILE"] = CAC      # the test CA is "a public CA" for the probes below (python's default context reads it)
(v, fp), out = bare(CALIVE, CALIVE, OLD, "y\n")
check("[8] bare, at a terminal: offered as CA verification, and y → TLS_VERIFY=yes with NO pin",
      "Verify the panel through its CA from now on? (y/N)" in out and (v, fp) == ("yes", ""), out)
(v, fp), out = bare(CALIVE, CALIVE, OLD)
check("[8] bare, no terminal → refused and stopped, pointing at TLS_VERIFY=yes (not a pin)",
      (v, fp) == (None, None) and STOP in out and "TLS_VERIFY=yes" in out and ("TLS_FINGERPRINT=" + CASERVED) not in out, out)
(v, fp), out = docker(CALIVE, OLD, "y\n")
check("[8] Docker, at a terminal: y → TLS_VERIFY=yes with NO pin", (v, fp) == ("yes", ""), out)
(v, fp), out = bare(LIVE, LIVE, OLD, "y\n")
check("[8] …while a self-signed new one is still the pin question (y → the pin)",
      "Trust the new certificate? (y/N)" in out and (v, fp) == ("no", SERVED), out)
del os.environ["SSL_CERT_FILE"]
casrv.shutdown()

print("\n[9] a bare node that verifies its panel through its CA keeps doing so")
FRESH = N[N.index("# ⚠️ …AND ONE THAT VERIFIES THIS PANEL THROUGH ITS CA KEEPS DOING SO."):
          N.index("\n# RE-INSTALL: signal \"re-installing\" now that the node's trust is decided")] + "\n"
def fresh(url, exist_url, exist_verify, answer=None, dry=False, ca_answer=""):
    return run(PRE.replace("DRYRUN=false", "DRYRUN=%s" % ("true" if dry else "false")) + fn(N, "_panel_fp") + COMMON
               + 'panel_cert_expired(){ return 1; }\nask_yn(){ local v="$2"; case "$1" in *"through its CA"*) v="${CA_ANSWER:-$v}";; esac; '
               + 'printf -v "$3" "%s" "$([ "$v" = y ] && echo yes || echo no)"; echo "ASKED $1"; }\nCA_ANSWER="' + ca_answer + '"\n'
               'EXISTING=yes; PANEL_URL="%s"; EXIST_URL="%s"; EXIST_FP=""; EXIST_VERIFY="%s"; TLS_VERIFY=""; TLS_FINGERPRINT=""\n%s\n'
               'echo "RESULT verify=$TLS_VERIFY fp=$TLS_FINGERPRINT"\n' % (url, exist_url, exist_verify, FRESH), answer)
(v, fp), out = fresh(LIVE, LIVE, "yes")
check("[9] a CA-verified node, the panel now self-signed → keeps CA verification, pins nothing", (v, fp) == ("yes", ""), out)
check("[9] …and the question says why its default is yes", "this node verifies it through its CA" in out, out)
(v, fp), out = fresh(LIVE, LIVE, "yes", ca_answer="n")
check("[9] …an operator who answers n (the panel moved to a self-signed certificate) → decided afresh: that one pinned, as the Docker node does",
      (v, fp) == ("no", SERVED), out)
(v, fp), out = fresh(LIVE, LIVE, "no")
check("[9] a node that verified nothing → the fresh decision as before (self-signed → pinned)", (v, fp) == ("no", SERVED), out)
(v, fp), out = fresh(LIVE, DEAD, "yes")
check("[9] a CA-verified node pointed at ANOTHER panel → the fresh decision (that panel is decided afresh)", (v, fp) == ("no", SERVED), out)

print("\n[10] a dry run's question")
(v, fp), out = fresh(LIVE, LIVE, "no", dry=True)
check("[10] says the panel was not probed, not that a default was \"auto-detected\"",
      "ASKED Verify the panel's TLS certificate? (not probed in a dry run — default: yes)" in out and "auto-detected" not in out, out)

srv.shutdown()
print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
