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

Run: python3 tests/panel_pin_change_selftest.py      (0 = pass)
     --plant <bare|silent|docker>   plant one old behaviour → RED (exit 0 when caught);  --perturb plants all three
"""
import hashlib, http.server, os, re, socket, ssl, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()
D = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
ALL = ("bare", "silent", "docker")
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
    a = N.index(BARE_A); b = N.index(BARE_B)
    N = N[:a] + N[b:]
if "silent" in PLANTS:    # a changed certificate taken without a word
    C = plant(C, 'panel_pin_changed(){ local old="$1" new="$2" v=""\n', 'panel_pin_changed(){ return 0\n')
if "docker" in PLANTS:    # the shipped Docker path: warn, then decide afresh
    D = plant(D, '    if panel_pin_changed "$_old" "$_fp"; then TLS_FINGERPRINT="$_fp"; else TLS_FINGERPRINT="$_old"; fi\n    TLS_VERIFY=no; return 0\n',
              '    warn "the panel\'s certificate CHANGED since this node pinned it — deciding afresh"\n')

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

COMMON = fn(C, "panel_pin_changed")
PRE = ('set -euo pipefail\nDRYRUN=false; BOLD=""; RESET=""\nok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ echo "SUB $*"; }\n'
       'info(){ echo "INFO $*"; }; b(){ printf %s "$*"; }\n')
a = N.index(BARE_A) if "bare" not in PLANTS else None
BLOCK = N[a:N.index(BARE_B)] if a is not None else ""

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

print("[1]–[5] the bare-metal node's re-install")
(v, fp), out = bare(LIVE, LIVE, SERVED)
check("[1] same certificate → the pin is kept", (v, fp) == ("no", SERVED), out)
check("[1] …and it says the panel still presents it", "still presents" in out, out)
(v, fp), out = bare(LIVE, LIVE, OLD)
check("[2] a CHANGED certificate, no terminal → the OLD pin is kept", (v, fp) == ("no", OLD), out)
check("[2] …with a CHANGED warning and the way to accept the new one", "CHANGED" in out and ("TLS_FINGERPRINT=" + SERVED) in out, out)
(v, fp), out = bare(LIVE, LIVE, OLD, "y\n")
check("[3] at a terminal, y → re-pinned to the new certificate", (v, fp) == ("no", SERVED), out)
(v, fp), out = bare(LIVE, LIVE, OLD, "\n")
check("[3] at a terminal, Enter (the default) → the old pin is kept", (v, fp) == ("no", OLD), out)
(v, fp), out = bare(DEAD, DEAD, OLD)
check("[4] the panel unreachable → the pin is kept", (v, fp) == ("no", OLD), out)
(v, fp), out = bare(LIVE, DEAD, OLD)
check("[5] another panel URL → not this block's decision (the fresh one after it decides)", (v, fp) == ("", ""), out)
(v, fp), out = bare(LIVE, LIVE, "")
check("[5] no pin on record → not this block's decision either", (v, fp) == ("", ""), out)

print("\n[6] the Docker node's re-install")
DFN = "\n".join(fn(D, n) for n in ("_docker_panel_fp", "ask_tty", "ask_yn_tty", "node_panel_trust"))
def docker(url, old, answer=None):
    return run(PRE + 'HAVE_TTY=no; _SWG_NL=""; C_BLUE=""; C_GREEN=""; C_BL=""; C_BROWN=""; _nlguard(){ :; }\n' + COMMON
               + 'panel_cert_expired(){ return 1; }\n' + DFN
               + '\nPANEL_URL="%s"; TLS_VERIFY=""; TLS_FINGERPRINT=""\nnode_panel_trust "%s"\n'
               'echo "RESULT verify=$TLS_VERIFY fp=$TLS_FINGERPRINT"\n' % (url, old), answer)
(v, fp), out = docker(LIVE, OLD)
check("[6] a CHANGED certificate, no terminal → the OLD pin is kept (it used to re-pin with a warning)", (v, fp) == ("no", OLD), out)
(v, fp), out = docker(LIVE, OLD, "y\n")
check("[6] …at a terminal, y → re-pinned", (v, fp) == ("no", SERVED), out)

srv.shutdown()
print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
