#!/usr/bin/env python3
"""Self-test — a call that carries the NODE TOKEN goes only to the panel the node trusts, checked on that very connection.

1.8.8 qualification, round 6: every installer → panel call carrying the node token used `curl -k` whenever the node did
not CA-verify — i.e. on EVERY pinned node. A re-install that had just "kept the old pin" (the panel presented a different
certificate: the interceptor its own warning named) had already posted "reinstalling" with the token to it, and did it
again at exit; whoami / rename, the uninstaller's sign-off and "uninstalling", update.sh's status and the recovery menu's
lookup did the same. panel_req (lib/common.sh, with byte-identical twins in uninstall.sh and bootstrap.sh, which cannot
source it) replaced them all: the certificate is checked ON THE CONNECTION THE TOKEN THEN TRAVELS ON, as swg-noded's
post_json does — a pin must match sha256(DER), verify=yes means CA verification with the hostname, and a failure sends
NOTHING (exit 4).

  [1] pin == the served certificate → answered (2xx body), the listener got the token and the body
  [2] pin != the served certificate → exit 4, one line, and the listener received NOTHING — no request, no token;
      a pin on record that is not a sha256 at all is never read as "no pin" (that would be unverified): exit 4 too
  [3] verify=yes against a self-signed certificate → exit 4, nothing received
  [4] verify=yes against a CA-signed one (the test CA trusted) → answered; …for a host the certificate does not name → 4
  [5] neither (the node's own unverified posture, e.g. TLS_VERIFY=no) → answered, as the node itself syncs; http:// too
  [6] an HTTP error → exit 3 "HTTP 401"; a closed port → exit 1 "connection refused"; a panel that hangs → given up
      within the timeout it was handed
  [7] the token is on no process's argv while a call is in flight (/proc/<pid>/cmdline is world-readable)
  [8] lib/common.sh, uninstall.sh and bootstrap.sh carry ONE program text
  [9] every call site in the shipped scripts that names /api/node/ sends through panel_req — none through curl, and
      auth_curl (the curl -k wrapper) is gone; the sites found cover the known floor (a refactor that hides one from
      this scan fails instead of passing short). WHAT each site passes — the node's own pin / verify — is not read here:
      tests/token_trust_sites_selftest.py drives every one of them against a panel it must refuse (round 8, I19).
      Round 10 (I19) closed three ways past it: it reads EVERY shell file of the tree (the Docker entrypoints,
      nix/adopt.sh, any lib file), not a list; a comment is a # that starts a word outside quotes (a `_n=" #"; ` before a
      curl hid it); and a token next to ANY sender — curl, wget, a python urllib / http.client / socket program, openssl,
      nc — is refused, whatever path it names (one assembled from pieces names no /api/node/ at all)

Run: python3 tests/panel_req_selftest.py     (0 = pass)
     --perturb-pin    the pin comparison dropped from the program → RED on [2]
     --perturb-malformed   a malformed pin cleaned down to nothing (= no pin, unverified) → RED on [2]
     --perturb-ca     CA verification dropped (always unverified) → RED on [3]/[4]
     --perturb-twin   uninstall.sh's copy drifts → RED on [8]
     --perturb-curl   a whoami through curl -k planted back into install-node.sh → RED on [9]
     --perturb-py     a python urllib whoami with the token, its path assembled, behind a quoted " #" → RED on [9]
"""
import glob, hashlib, http.server, os, re, socket, ssl, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PERTURBED = any(a.startswith("--perturb") for a in ARGS)
# ⚠️ EVERY SHELL FILE OF THE TREE — a token sent from the Docker entrypoints, nix/adopt.sh or a new lib file was never read
# (1.8.8 qualification, round 10, I19 class 4)
SCAN = sorted(set(("lib/common.sh", "uninstall.sh", "bootstrap.sh", "install-node.sh", "install-docker.sh", "install-host.sh",
                   "update.sh", "convert.sh")) | {os.path.relpath(q, ROOT) for g in ("*.sh", "lib/*.sh", "docker/*.sh", "nix/*.sh")
                                                   for q in glob.glob(os.path.join(ROOT, g))})
SRC = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in SCAN}

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(f, a, b):
    assert SRC[f].count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    SRC[f] = SRC[f].replace(a, b)

PROG_RE = re.compile(r"panel_req\(\)\{ python3 - \"\$@\" <<'PANELREQ'\n(.*?)\nPANELREQ\n\}\n", re.S)
if "--perturb-pin" in ARGS:
    plant("lib/common.sh", "        if got != fp:\n", "        if False:\n")
if "--perturb-malformed" in ARGS:
    plant("lib/common.sh", 'fp = a[3].strip().replace(":", "").lower()\n', 'fp = "".join(c for c in a[3].lower() if c in "0123456789abcdef")\n')
    plant("lib/common.sh", 'if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):', 'if False:')
if "--perturb-ca" in ARGS:
    plant("lib/common.sh", '        ctx = ssl.create_default_context() if (verify and not fp) else ssl._create_unverified_context()\n',
          '        ctx = ssl._create_unverified_context()\n')
if "--perturb-twin" in ARGS:
    plant("uninstall.sh", '    hdr = {"Authorization": "Bearer " + tok, "User-Agent": "swg-noded"}\n',
          '    hdr = {"Authorization": "Bearer " + tok}\n')
if "--perturb-py" in ARGS:
    plant("install-node.sh", 'step "Datapath tooling"\necho\n',
          'step "Datapath tooling"\necho\n_n=" #"; SWG_T="$NODE_TOKEN" U="$PANEL_URL" python3 -c \'import os,ssl,urllib.request as u;'
          'u.urlopen(u.Request(os.environ["U"]+"/api/node"+"/whoami",headers={"Authorization":"Bearer "+os.environ["SWG_T"]}),'
          'context=ssl._create_unverified_context(),timeout=8)\' >/dev/null 2>&1 || true\n')
if "--perturb-curl" in ARGS:
    # the whoami install-node.sh asks before it keeps a node's name (moved into `if _wj="$(…)"` in 9ac5f41 — the old anchor
    # matched nothing from then on and this plant raised instead of planting: round 10)
    plant("install-node.sh", '  if _wj="$(SWG_TOK="$NODE_TOKEN" panel_req GET "${PANEL_URL%/}/api/node/whoami" "${TLS_VERIFY:-no}" "${TLS_FINGERPRINT:-}" 8 2>/dev/null)"; then',
          '  if _wj="$(curl -fsSk -H "Authorization: Bearer $NODE_TOKEN" --max-time 8 "${PANEL_URL%/}/api/node/whoami" 2>/dev/null)"; then')

T = tempfile.mkdtemp(prefix="panelreq-")
def sh(path, text):
    open(path, "w").write(text); return path

# ── the program under test: lib/common.sh's panel_req, lifted as shipped ──────────────────────────────────────────
m = PROG_RE.search(SRC["lib/common.sh"])
assert m, "cannot lift panel_req from lib/common.sh"
FN = "panel_req(){ python3 - \"$@\" <<'PANELREQ'\n" + m.group(1) + "\nPANELREQ\n}\n"
LIB = sh(os.path.join(T, "panel_req.sh"), FN)

def call(meth, url, verify, fp, tok, body="", tmo="6", env=None):
    e = dict(os.environ, SWG_TOK=tok, SWG_BODY=body, **(env or {}))
    t0 = time.time()
    r = subprocess.run(["bash", "-c", '. "%s"; panel_req "$@"' % LIB, "x", meth, url, verify, fp, tmo],
                       capture_output=True, text=True, env=e, timeout=60)
    return r.returncode, r.stdout.strip(), time.time() - t0

# ── listeners: every request they get is logged (method, path, Authorization, body) ─────────────────────────────
LOG = []
class H(http.server.BaseHTTPRequestHandler):
    def _h(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = self.rfile.read(n).decode() if n else ""
        LOG.append((self.command, self.path, self.headers.get("Authorization") or "", b))
        code = 401 if "reject" in (self.headers.get("Authorization") or "") else 200
        self.send_response(code); self.send_header("Content-Length", "13"); self.end_headers(); self.wfile.write(b'{"ok": "yes"}')
    do_GET = do_POST = _h
    def log_message(self, *a):
        pass

def tls_listener(cert, key):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def openssl(*a):
    subprocess.run(["openssl", *a], check=True, capture_output=True)

SSC, SSK = os.path.join(T, "ss.pem"), os.path.join(T, "ss.key")          # self-signed, as a panel mints it
openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=127.0.0.1",
        "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", SSK, "-out", SSC)
SERVED = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(SSC).read())).hexdigest()
CAC, CAK = os.path.join(T, "ca.pem"), os.path.join(T, "ca.key")          # a CA the test trusts (SSL_CERT_FILE)
openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=swg test CA", "-keyout", CAK, "-out", CAC)
CSC, CSK, CSR = os.path.join(T, "cs.pem"), os.path.join(T, "cs.key"), os.path.join(T, "cs.csr")
openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=127.0.0.1", "-keyout", CSK, "-out", CSR)
sh(os.path.join(T, "san.ext"), "subjectAltName=IP:127.0.0.1\n")
openssl("x509", "-req", "-in", CSR, "-CA", CAC, "-CAkey", CAK, "-CAcreateserial", "-days", "30",
        "-extfile", os.path.join(T, "san.ext"), "-out", CSC)
ss_srv, SSP = tls_listener(SSC, SSK)
ca_srv, CAP = tls_listener(CSC, CSK)
http_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=http_srv.serve_forever, daemon=True).start()
HTP = http_srv.server_address[1]
hang = socket.socket(); hang.bind(("127.0.0.1", 0)); hang.listen(8); HGP = hang.getsockname()[1]   # accepts, never answers
_c = socket.socket(); _c.bind(("127.0.0.1", 0)); CLP = _c.getsockname()[1]; _c.close()
TRUST_CA = {"SSL_CERT_FILE": CAC}
got = lambda tok: [l for l in LOG if tok in l[2]]

print("[1] the pinned certificate")
rc, out, _ = call("POST", "https://127.0.0.1:%d/api/node/proc-status" % SSP, "no", SERVED, "tok-one", '{"state":"reinstalling"}')
check("pin == served → answered", rc == 0 and '"ok"' in out, (rc, out))
check("…the panel got the token and the body", got("tok-one") == [("POST", "/api/node/proc-status", "Bearer tok-one", '{"state":"reinstalling"}')], LOG)
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % SSP, "no", ":".join(SERVED[i:i + 2] for i in range(0, 64, 2)).upper(), "tok-colon")
check("…a pin written AB:CD:… is the same pin", rc == 0 and got("tok-colon"), (rc, out))

print("\n[2] a certificate other than the pinned one")
n0 = len(LOG)
rc, out, _ = call("POST", "https://127.0.0.1:%d/api/node/proc-status" % SSP, "no", "ab" * 32, "tok-two", '{"state":"reinstalling"}')
check("exit 4, one line saying so", rc == 4 and out.count("\n") == 0 and "other than the pinned one" in out and "nothing was sent" in out, (rc, out))
check("⚠️ the listener received NOTHING — no request, no token", len(LOG) == n0 and not got("tok-two"), LOG[n0:])
# ⚠️ NOT ONE HEX DIGIT IN IT. The sample was `zz-not-a-pin`, whose `a` survives any hex-only cleaning — so
# --perturb-malformed (the pin cleaned down to hex digits) left the pin `a`, the certificate was compared with it and
# refused, and the check went red only on the wording, never on "nothing received" (1.8.8 qualification, round 8). A pin
# with no hex digit at all cleans down to NOTHING — "no pin", unverified — which is exactly the failure this is named for.
BADPIN = "zz-not-pin"
assert not set(BADPIN.lower()) & set("0123456789abcdef"), "the malformed pin must clean down to nothing"
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % SSP, "no", BADPIN, "tok-two-b")
check("a pin that is not a sha256: the listener received NOTHING (never read as \"no pin\", i.e. unverified)",
      len(LOG) == n0 and not got("tok-two-b"), LOG[n0:])
check("…exit 4, and the line says the pin on record is not a sha256", rc == 4 and "not a sha256" in out, (rc, out))

print("\n[3] CA verification against a self-signed certificate")
n0 = len(LOG)
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % SSP, "yes", "", "tok-three")
check("exit 4, nothing received", rc == 4 and "did not verify" in out and len(LOG) == n0 and not got("tok-three"), (rc, out, LOG[n0:]))

print("\n[4] CA verification against a CA-signed certificate")
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % CAP, "yes", "", "tok-four", env=TRUST_CA)
check("the CA vouches for it → answered", rc == 0 and got("tok-four"), (rc, out))
n0 = len(LOG)
rc, out, _ = call("GET", "https://localhost:%d/api/node/whoami" % CAP, "yes", "", "tok-four-b", env=TRUST_CA)
check("…for a host name the certificate does not carry → exit 4, nothing received (the hostname is checked too)",
      rc == 4 and len(LOG) == n0, (rc, out))

print("\n[5] the node's own unverified posture, and plain loopback HTTP")
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % SSP, "no", "", "tok-five")
check("neither verify nor pin → answered, as the node itself syncs", rc == 0 and got("tok-five"), (rc, out))
rc, out, _ = call("POST", "http://127.0.0.1:%d/api/node/proc-status" % HTP, "no", "", "tok-http", '{"state":"updated"}')
check("http:// (a co-located node's loopback) → answered", rc == 0 and got("tok-http"), (rc, out))

print("\n[6] the answers it gives back")
rc, out, _ = call("GET", "https://127.0.0.1:%d/api/node/whoami" % SSP, "no", SERVED, "reject-me")
check("the panel says 401 → exit 3, \"HTTP 401\"", rc == 3 and out == "HTTP 401", (rc, out))
rc, out, _ = call("GET", "https://127.0.0.1:%d/x" % CLP, "no", SERVED, "tok-six")
check("a closed port → exit 1, \"connection refused\"", rc == 1 and out == "connection refused", (rc, out))
rc, out, dt = call("GET", "https://127.0.0.1:%d/x" % HGP, "no", SERVED, "tok-hang", tmo="2")
check("a panel that never answers → given up within the 2 s it was handed (+1 s)", rc == 1 and dt < 3.5, (rc, out, round(dt, 2)))

print("\n[7] the token is on no argv")
TOK = "tok-secret-%d" % os.getpid()
p = subprocess.Popen(["bash", "-c", '. "%s"; panel_req GET "https://127.0.0.1:%d/x" no "" 4' % (LIB, HGP)],
                     env=dict(os.environ, SWG_TOK=TOK), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
on_argv, in_env = [], []
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        if TOK.encode() in open("/proc/%s/cmdline" % pid, "rb").read():
            on_argv.append(pid)
        if b"SWG_TOK=" + TOK.encode() in open("/proc/%s/environ" % pid, "rb").read():
            in_env.append(pid)
    except OSError:
        pass
p.wait(timeout=30)
check("while the call is in flight no /proc/<pid>/cmdline holds the token", not on_argv, on_argv)
check("…it is in the environment of the call (so the scan looked at the right processes)", bool(in_env), in_env)

print("\n[8] one program, three copies")
progs = {f: (PROG_RE.search(SRC[f]).group(1) if PROG_RE.search(SRC[f]) else None) for f in ("lib/common.sh", "uninstall.sh", "bootstrap.sh")}
check("uninstall.sh carries lib/common.sh's program exactly", progs["uninstall.sh"] == progs["lib/common.sh"])
check("bootstrap.sh carries lib/common.sh's program exactly", progs["bootstrap.sh"] == progs["lib/common.sh"])

print("\n[9] every call that names /api/node/ sends through panel_req")
FLOOR = {("install-node.sh", "whoami"), ("install-node.sh", "rename"), ("install-docker.sh", "whoami"), ("install-docker.sh", "rename"),
         ("install-host.sh", "whoami"), ("install-host.sh", "rename"), ("uninstall.sh", "goodbye"), ("uninstall.sh", "proc-status"),
         ("bootstrap.sh", "whoami"), ("lib/common.sh", "proc-status")}
def code_of(line):
    """the line without its comment: a # that starts a word OUTSIDE quotes (`_n=" #"; curl …` is code — round 10, 5c)"""
    j, n, q = 0, len(line), None
    while j < n:
        c = line[j]
        if q == "'":
            if c == "'": q = None
        elif q == '"':
            if c == "\\": j += 1
            elif c == '"': q = None
        elif c == "\\": j += 1
        elif c in "'\"": q = c
        elif c == "#" and (j == 0 or line[j - 1] in " \t;|&("):
            return line[:j]
        j += 1
    return line
# a node token on the line, and a sender on it that is not panel_req (the program panel_req runs is the one sender allowed)
TOKEN_RE = re.compile(r"TOKEN|_tok\b|\$tok\b|\bNTOK\b|SWG_TOK|SWG_T=|panel-token|Authorization|Bearer")
SENDER_RE = re.compile(r"\bcurl\b|\bwget\b|urllib|http\.client|\brequests\.|socket\.|\bopenssl\s+s_client\b|\bn(?:c|cat)\s|/dev/tcp/")
PANELREQ_PROG = re.compile(r"panel_req\(\)\{ python3 - \"\$@\" <<'PANELREQ'\n.*?\nPANELREQ\n", re.S)
sites, bad = set(), []
for f, text in SRC.items():
    prog = [(m.start(), m.end()) for m in PANELREQ_PROG.finditer(text)]      # panel_req's own program: the sender itself
    off = 0
    for i, line in enumerate(text.splitlines(), 1):
        at, off = off, off + len(line) + 1
        if any(a <= at < b for a, b in prog):
            continue
        code = code_of(line)
        said = re.match(r"\s*(?:echo|printf|info|warn|sub|ok|note|die)\b", code) and not SENDER_RE.search(code)   # a message naming a path
        for ep in re.findall(r"/api/node/([a-z-]+)", code):
            if said:
                continue
            sites.add((f, ep))
            if "panel_req" not in code:
                bad.append("%s:%d %s" % (f, i, line.strip()[:120]))
        if TOKEN_RE.search(code) and SENDER_RE.search(code):
            bad.append("%s:%d a token beside a sender that is not panel_req: %s" % (f, i, line.strip()[:120]))
check("no call site sends the token any other way", not bad, bad)
check("…read from every shell file of the tree (%d), the Docker entrypoints and nix/adopt.sh among them" % len(SCAN),
      {"docker/node-entrypoint.sh", "docker/entrypoint.sh", "nix/adopt.sh"} <= set(SCAN), SCAN)
left = ["%s:%d" % (f, i) for f, t in SRC.items() for i, l in enumerate(t.splitlines(), 1)
        if not l.lstrip().startswith("#") and re.search(r"\bauth_curl\b", l.split(" #")[0])]
check("auth_curl (the curl -k wrapper) is gone from every script — defined or called", not left, left)
check("the sites found cover the known floor", FLOOR <= sites, sorted(FLOOR - sites))

for srv in (ss_srv, ca_srv, http_srv):
    srv.shutdown()
hang.close()
print()
if PERTURBED:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see it"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
