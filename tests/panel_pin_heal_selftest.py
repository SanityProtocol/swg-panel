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
  [E3] a pin on record that is not a sha256 (round 9b): swg-noded's sync fails closed before connecting, a list pull sends
       nothing either, and the hint says what it is — not "the certificate no longer matches"; colons / upper case: a pin
  [E4] on a NixOS node (q189 round 3) both hints say what holds there — services.swg-node.panelTlsFingerprint /
       verifyPanelTls, nixos-rebuild switch, and restart swg-noded on the native arm only — never "re-run the node
       installer", which a NixOS node does not have; every other node keeps today's two sentences byte for byte

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
    ("no-hint", "    if err not in (\"tls fingerprint mismatch\", \"tls pin malformed\") or time.time() - _PIN_HINT[\"at\"] < 3600:",
     "    if True:", "a pin mismatch tells the operator what to do", "SWG_NODED", NODED),
    # round 9b: a pin on record that is not a sha256 is told apart — it fails closed, sends nothing, and says what it is
    ("malformed-sync", "    if u.scheme == \"https\" and _pin_malformed(fp):\n        return 0, {\"error\": \"tls pin malformed\"}",
     "    if False:\n        return 0, {\"error\": \"tls pin malformed\"}",
     "[E3] a pin that is not a sha256 is told apart from a changed certificate — and nothing is sent", "SWG_NODED", NODED),
    ("malformed-hint", "    if err == \"tls pin malformed\":\n        fp = str((panel or {}).get(\"fingerprint\") or \"\")",
     "    if False:\n        fp = str((panel or {}).get(\"fingerprint\") or \"\")",
     "[E3] …and its hint says the pin on record is not a sha256 fingerprint (not that the certificate changed)", "SWG_NODED", NODED),

    ("stale-hint", "at a terminal and accept the new certificate when it asks",
     "— it re-detects the certificate", "…and what the installer does NOW (round 7): it asks at a terminal; unattended it takes TLS_FINGERPRINT / TLS_VERIFY — never \"re-detects\"",
     "SWG_NODED", NODED),
    # q189 round 3: a NixOS node is told the NixOS way, on both hints; every other node keeps today's sentences
    ("nixos-gone", "    fix = (\"this NixOS node's pin is \" + nixos(\"the new sha256\") if NODE_PLATFORM == \"nixos\" else",
     "    fix = (\"this NixOS node's pin is \" + nixos(\"the new sha256\") if False else",
     "[E4] on a NixOS node a pin mismatch says what holds there — panelTlsFingerprint / verifyPanelTls, nixos-rebuild "
     "switch, restart swg-noded — and names no installer", "SWG_NODED", NODED),
    ("nixos-gone-malformed",
     "        fix = (\"On this NixOS node the pin is \" + nixos(\"the panel's sha256\") if NODE_PLATFORM == \"nixos\" else",
     "        fix = (\"On this NixOS node the pin is \" + nixos(\"the panel's sha256\") if False else",
     "[E4] …and so does a pin that is not a sha256 (its own prefix, the panel's sha256, no installer)", "SWG_NODED", NODED),
    ("nixos-arm", "% (sha, \"\" if NODE_KIND == \"docker\" else \" and restart swg-noded\"))",
     "% (sha, \" and restart swg-noded\"))",
     "[E4] …on the container arm the rebuild alone (it restarts the container's unit) — no swg-noded to restart",
     "SWG_NODED", NODED),
    ("nixos-leak", "    fix = (\"this NixOS node's pin is \" + nixos(\"the new sha256\") if NODE_PLATFORM == \"nixos\" else",
     "    fix = (\"this NixOS node's pin is \" + nixos(\"the new sha256\") if True else",
     "[E4] every other node keeps today's two sentences byte for byte (bare metal, Docker, a Debian label)",
     "SWG_NODED", NODED),
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
        def do_POST(self):
            SEEN.append((self.path.split("?")[0], self.headers.get("Authorization")))
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            raw = b'{"ok": false}'
            self.send_response(404); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
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
_h = hint("tls fingerprint mismatch")
check("a pin mismatch tells the operator what to do", "re-run the node installer" in _h)
check("…and what the installer does NOW (round 7): it asks at a terminal; unattended it takes TLS_FINGERPRINT / TLS_VERIFY — never \"re-detects\"",
      "at a terminal" in _h and "TLS_FINGERPRINT=" in _h and "TLS_VERIFY=yes" in _h and "re-detect" not in _h, _h)
check("…once an hour, not every 5-second sync", hint("tls fingerprint mismatch") == "")
N._PIN_HINT["at"] = 0.0
check("…and only for a pin mismatch", hint("timed out") == "")
print("swg-noded — a pin on record that is not a sha256 (round 9b)")
_bad = RENEWED[2][:63]                                     # the real certificate's sha256, one digit short
_n0 = len(SEEN)
st, reply = N.post_json(u_ok + "/api/node/sync", TOKEN, {}, dict(panel, fingerprint=_bad))
check("[E3] a pin that is not a sha256 is told apart from a changed certificate — and nothing is sent",
      st == 0 and reply.get("error") == "tls pin malformed" and len(SEEN) == _n0, (st, reply, SEEN[_n0:]))
gs = N._panel_get(u_ok + "/api/node/list", TOKEN, dict(panel, fingerprint=_bad))
check("[E3] …a list pull against it sends nothing either (it can match no certificate: the pin check refuses)",
      gs == (0, b"", "") and len(SEEN) == _n0, (gs, SEEN[_n0:]))
st, reply = N.post_json(u_ok + "/api/node/sync", TOKEN, {}, dict(panel, fingerprint=":".join(RENEWED[2][i:i + 2].upper() for i in range(0, 64, 2))))
check("[E3] …a sha256 written with colons / upper case is a pin, not a malformed one (it matches, the request goes out)",
      st == 404 and len(SEEN) == _n0 + 1, (st, reply))
N._PIN_HINT["at"] = 0.0
_o = io.StringIO()
with _cl.redirect_stdout(_o):
    N._pin_mismatch_hint("tls pin malformed", {"fingerprint": _bad})
_hm = _o.getvalue()
check("[E3] …and its hint says the pin on record is not a sha256 fingerprint (not that the certificate changed)",
      "is not a sha256 fingerprint" in _hm and _bad[:24] in _hm and "no longer matches" not in _hm
      and "TLS_FINGERPRINT=" in _hm and "at a terminal" in _hm, _hm)
print("swg-noded — the hint on a NixOS node (q189 round 3): there is no installer to re-run")
# Today's two sentences, frozen: every node that is not NixOS keeps them byte for byte.
_TODAY = {
    "tls fingerprint mismatch":
        "panel TLS: the panel's certificate no longer matches this node's pin, so every sync is refused. If the panel's "
        "certificate was renewed or replaced on purpose, re-run the node installer on this box at a terminal and accept "
        "the new certificate when it asks (one a public CA vouches for is then verified, not pinned); unattended it never "
        "takes a changed certificate — give it TLS_FINGERPRINT=<the new sha256>, or TLS_VERIFY=yes for a CA one. Anything "
        "else may be an impersonator.",
    "tls pin malformed":
        "panel TLS: the pin on record for the panel is not a sha256 fingerprint (\"%s…\"), so every sync is refused and "
        "nothing is sent — it names no certificate at all. Re-run the node installer on this box at a terminal: it shows "
        "the certificate the panel presents and asks before pinning it. Unattended, give it TLS_FINGERPRINT=<the panel's "
        "sha256>, or TLS_VERIFY=yes for one a public CA vouches for." % _bad[:24],
}
_plat0 = (N.NODE_PLATFORM, N.NODE_KIND)
def hint_on(err, platform, kind):
    N.NODE_PLATFORM, N.NODE_KIND = platform, kind
    N._PIN_HINT["at"] = 0.0
    o = io.StringIO()
    with _cl.redirect_stdout(o):
        N._pin_mismatch_hint(err, {"fingerprint": _bad})
    return re.sub(r"^(<\d>|[A-Z] )", "", o.getvalue()).rstrip("\n")
_NIX = ("services.swg-node.panelTlsFingerprint in its configuration.nix", "verifyPanelTls = true", "nixos-rebuild switch")
_hn = hint_on("tls fingerprint mismatch", "nixos", "baremetal")
check("[E4] on a NixOS node a pin mismatch says what holds there — panelTlsFingerprint / verifyPanelTls, nixos-rebuild "
      "switch, restart swg-noded — and names no installer",
      all(k in _hn for k in _NIX) and "set it to the new sha256" in _hn and "nixos-rebuild switch and restart swg-noded." in _hn
      and "no longer matches" in _hn and _hn.endswith("Anything else may be an impersonator.")
      and "installer" not in _hn and "TLS_FINGERPRINT" not in _hn and "TLS_VERIFY" not in _hn, _hn)
_hnm = hint_on("tls pin malformed", "nixos", "baremetal")
check("[E4] …and so does a pin that is not a sha256 (its own prefix, the panel's sha256, no installer)",
      all(k in _hnm for k in _NIX) and "is not a sha256 fingerprint" in _hnm and _bad[:24] in _hnm
      and "set it to the panel's sha256" in _hnm and "nixos-rebuild switch and restart swg-noded." in _hnm
      and "installer" not in _hnm and "TLS_FINGERPRINT" not in _hnm and "TLS_VERIFY" not in _hnm, _hnm)
_hc = [hint_on(e, "nixos", "docker") for e in _TODAY]
check("[E4] …on the container arm the rebuild alone (it restarts the container's unit) — no swg-noded to restart",
      all(all(k in h for k in _NIX) and "then run nixos-rebuild switch." in h and "restart swg-noded" not in h
          and "installer" not in h for h in _hc), _hc)
_odd = [(e, p, k) for e in _TODAY for p in ("", "debian") for k in ("baremetal", "docker")
        if hint_on(e, p, k) != _TODAY[e]]
check("[E4] every other node keeps today's two sentences byte for byte (bare metal, Docker, a Debian label)",
      not _odd, [(o, hint_on(*o)) for o in _odd[:1]])
N.NODE_PLATFORM, N.NODE_KIND = _plat0
check("no heal machinery remains on the node", not hasattr(N, "_heal_stale_pin") and not hasattr(N, "_cert_proof"))
ESRC = open(ENTRY, encoding="utf-8").read()
check("the node container honours no 'retired pin' file", "panel-fp-retired" not in ESRC)

for s in (s_exp, s_self, s_ok):
    s.shutdown()
print()
print("FAIL: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
