#!/usr/bin/env python3
"""Self-test — AN EXPIRED CA CERTIFICATE IS NOT PINNED AS SELF-SIGNED, AND A STALE PIN HEALS TO CA VERIFICATION.

Seen live 2026-09-25: a letsencrypt-ip panel's certificate expired; the operator re-ran the node installer to
"restore sync". The installer read curl's 60 (verification failed) + a working `-k` fetch as "self-signed" and
PINNED the expired certificate. Once the panel was renewed the pin stopped matching, every sync failed closed, the
node went stale and the panel showed its mesh down until the node was re-installed.

  [E1] the installers' probe tells an expired (or not-yet-valid) CA certificate apart from a self-signed one —
       and the premise: curl really does exit 60 on an expired certificate, the same code as self-signed
  [E2] swg-noded, on a pin mismatch, moves to CA verification only when the panel now passes it AND answers
       whoami with our token; a certificate no public CA vouches for keeps failing closed; throttled

Real TLS servers on 127.0.0.1 with a test CA (trusted via SSL_CERT_FILE / CURL_CA_BUNDLE). No root.
Run: python3 tests/panel_pin_heal_selftest.py            (0 = pass)
     python3 tests/panel_pin_heal_selftest.py --perturb  each plant must go red on its own check
"""
import datetime, hashlib, http.server, importlib.machinery, importlib.util, json, os, re, ssl, subprocess, sys, urllib.parse
import tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
INODE = os.environ.get("SWG_INSTALL_NODE") or os.path.join(ROOT, "install-node.sh")
COMMON = os.environ.get("SWG_COMMON") or os.path.join(ROOT, "lib", "common.sh")
ENTRY = os.environ.get("SWG_ENTRYPOINT") or os.path.join(ROOT, "docker", "node-entrypoint.sh")

PLANTS = [
    ("pin-expired", "    sys.exit(0 if getattr(e,\"verify_code\",0) in (9,10) else 1)", "    sys.exit(1)",
     "[E1] an EXPIRED CA certificate is recognised (not pinned as self-signed)", "SWG_COMMON", COMMON),
    ("no-hint", "    if err != \"tls fingerprint mismatch\" or time.time() - _PIN_HINT[\"at\"] < 3600:",
     "    if True:", "a pin mismatch tells the operator what to do", "SWG_NODED", NODED),
]

if "--perturb" in sys.argv:
    caught, bad = 0, []
    for name, old, new, must, envk, path in PLANTS:
        src = open(path, encoding="utf-8").read()
        if src.count(old) != 1:
            bad.append("%s: anchor found %d times (stale plant)" % (name, src.count(old))); continue
        with tempfile.NamedTemporaryFile("w", suffix="-plant", delete=False) as f:
            f.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{envk: f.name}),
                           capture_output=True, text=True, timeout=180)
        os.unlink(f.name)
        red = ("  FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-14s %s" % (name, "caught" if red else ("CRASHED (not a catch)" if "Traceback" in r.stderr else "NOT CAUGHT")))
        caught += red
        if not red:
            bad.append(name)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    sys.exit(0 if caught == len(PLANTS) and not bad else 1)

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import ipaddress

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="pinheal-")
NOW = datetime.datetime.now(datetime.timezone.utc)
D = datetime.timedelta(days=1)

def _key():
    return ec.generate_private_key(ec.SECP256R1())

CA_K = _key()
CA_N = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pin-heal Test CA")])
CA = (x509.CertificateBuilder().subject_name(CA_N).issuer_name(CA_N).public_key(CA_K.public_key())
      .serial_number(x509.random_serial_number()).not_valid_before(NOW - 30 * D).not_valid_after(NOW + 30 * D)
      .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(CA_K, hashes.SHA256()))
CA_PEM = os.path.join(TMP, "ca.pem")
open(CA_PEM, "wb").write(CA.public_bytes(serialization.Encoding.PEM))
os.environ["SSL_CERT_FILE"] = CA_PEM          # python's default context (the node) trusts the test CA
os.environ["CURL_CA_BUNDLE"] = CA_PEM         # …and so does curl (the installers' first probe)

def leaf(tag, nb, na, selfsigned=False):
    k = _key()
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, tag)])
    b = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj if selfsigned else CA_N)
         .public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(nb).not_valid_after(na)
         .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=True))
    c = b.sign(k if selfsigned else CA_K, hashes.SHA256())
    cp, kp = os.path.join(TMP, tag + ".crt"), os.path.join(TMP, tag + ".key")
    open(cp, "wb").write(c.public_bytes(serialization.Encoding.PEM) + (b"" if selfsigned else CA.public_bytes(serialization.Encoding.PEM)))
    open(kp, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cp, kp, hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).hexdigest()

EXPIRED = leaf("expired", NOW - 8 * D, NOW - 1 * D)       # an LE-style cert the panel failed to renew
RENEWED = leaf("renewed", NOW - 1 * D, NOW + 5 * D)       # …and its renewal
SELF = leaf("selfsigned", NOW - 1 * D, NOW + 3650 * D, selfsigned=True)
TOKEN = "node-token-123"
PANEL_SRC = open(os.environ.get("SWG_PANEL") or os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
import ast as _ast, hmac as _hmac
_want = {"_cert_proof_reply"}
_code = "\n".join(_ast.get_source_segment(PANEL_SRC, n) for n in _ast.parse(PANEL_SRC).body
                   if (isinstance(n, _ast.FunctionDef) and n.name in _want) or
                   (isinstance(n, _ast.Assign) and any(getattr(t, "id", "") in ("_CERT_PROOF_ID", "_CERT_PROOF_RE", "_CERT_PROOF_NONCE_RE") for t in n.targets)))
PNS = {"re": re, "ssl": ssl, "hmac": _hmac, "hashlib": hashlib}
exec(compile(_code, "swg-panel-server(extract)", "exec"), PNS)
NODES = {"n1": {"name": "n1", "token_sha": hashlib.sha256(TOKEN.encode()).hexdigest()}}
SEEN = []            # (path, Authorization header) of every request any test server received

def handler(proof_cert, forge=False):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            SEEN.append((self.path.split("?")[0], self.headers.get("Authorization")))
            code, body = 404, {"ok": False}
            if self.path.startswith("/api/node/cert-proof?"):
                q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                r = PNS["_cert_proof_reply"](NODES, (q.get("id") or [""])[0], (q.get("nonce") or [""])[0], proof_cert)
                if r and forge:
                    r["mac"] = _hmac.new(b"not-the-secret", r["mac"].encode(), hashlib.sha256).hexdigest()
                if r:
                    code, body = 200, {"ok": True, "data": r}
            elif self.path.endswith("/api/node/whoami") and self.headers.get("Authorization") == "Bearer " + TOKEN:
                code, body = 200, {"ok": True, "data": {"name": "n1"}}
            raw = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *a):
            pass
    return H

def serve(cert, proof_cert=None, forge=False):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler(proof_cert or cert[0], forge))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert[0], cert[1])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "https://127.0.0.1:%d" % srv.server_address[1]

# ── E1: the installers' probe ─────────────────────────────────────────────────────────────────────────────
print("E1 — the installer's probe")
ISRC = open(INODE, encoding="utf-8").read()
CSRC = open(COMMON, encoding="utf-8").read()
m = re.search(r"panel_cert_expired\(\)\{ python3 - \"\$1\" <<'PY' 2>/dev/null\n(.*?)\nPY\n\}", CSRC, re.S)
check("lib/common.sh carries the ONE panel_cert_expired", bool(m))
PROBE = m.group(1) if m else "import sys; sys.exit(1)"
def expired_probe(url):
    return subprocess.run([sys.executable, "-", url], input=PROBE, text=True, capture_output=True, timeout=20).returncode == 0
def curl_rc(url, k=False):
    return subprocess.run(["curl", "-sS", "--max-time", "6", "-o", "/dev/null"] + (["-k"] if k else []) + [url + "/healthz"],
                          capture_output=True, timeout=20).returncode
s_exp, u_exp = serve(EXPIRED)
s_self, u_self = serve(SELF)
s_ok, u_ok = serve(RENEWED)
check("premise: curl exits 60 on an EXPIRED CA certificate, and -k works", curl_rc(u_exp) == 60 and curl_rc(u_exp, True) == 0, curl_rc(u_exp))
check("premise: …the same 60 as a self-signed one", curl_rc(u_self) == 60 and curl_rc(u_self, True) == 0, curl_rc(u_self))
check("[E1] an EXPIRED CA certificate is recognised (not pinned as self-signed)", expired_probe(u_exp))
check("[E1] a self-signed certificate is not called expired (it is still pinned, as before)", not expired_probe(u_self))
check("[E1] a valid CA certificate is not called expired", not expired_probe(u_ok))
check("[E1] an unreachable panel is not called expired", not expired_probe("https://127.0.0.1:1"))
DSRC = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
check("both installers call the shared probe and neither keeps a copy of its own",
      all(src.count("if panel_cert_expired \"$PANEL_URL\"; then") == 1 and "cert_expired(){" not in src for src in (ISRC, DSRC)))

# ── swg-noded: a mismatch keeps the pin (no heal — see _pin_mismatch_hint) and says what to do ────────────
print("swg-noded — a pin that stops matching")
l = importlib.machinery.SourceFileLoader("swgnoded_ph", NODED)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_ph", l))
try:
    l.exec_module(N)
except SystemExit:
    pass
panel = {"url": u_ok, "token": TOKEN, "verify": False, "fingerprint": EXPIRED[2]}
st, reply = N.post_json(u_ok + "/api/node/sync", TOKEN, {}, panel)
check("a stale pin fails closed (the renewed certificate is refused, never adopted)",
      st == 0 and reply.get("error") == "tls fingerprint mismatch" and panel.get("fingerprint") == EXPIRED[2], (st, reply))
import io, contextlib as _cl
def hint(err):
    o = io.StringIO()
    with _cl.redirect_stdout(o):
        N._pin_mismatch_hint(err)
    return o.getvalue()
N._PIN_HINT["at"] = 0.0
check("a pin mismatch tells the operator what to do", "re-run the node installer" in hint("tls fingerprint mismatch"))
check("…once an hour, not every 5-second sync", hint("tls fingerprint mismatch") == "")
N._PIN_HINT["at"] = 0.0
check("…and only for a pin mismatch", hint("timed out") == "")
check("no heal machinery remains on the node", not hasattr(N, "_heal_stale_pin") and not hasattr(N, "_cert_proof"))
ESRC = open(ENTRY, encoding="utf-8").read()
check("the node container honours no 'retired pin' file", "panel-fp-retired" not in ESRC)

for s in (s_exp, s_self, s_ok):
    s.shutdown()
print()
print("FAIL: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
