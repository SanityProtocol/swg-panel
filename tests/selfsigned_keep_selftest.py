#!/usr/bin/env python3
"""Self-test — an unattended bare-metal panel re-install with TLS_MODE=selfsigned KEEPS the self-signed cert already
there, instead of minting a new one that strands every node pinned to the old.

Each node PINS the certificate it enrolled against. A re-install that says TLS_MODE=selfsigned (because that is what
the box uses) called mk_selfsigned — same host, NEW key — and every node then failed its TLS pin until re-installed: the
node's pin heal only ever moves a pin to CA verification, never to another self-signed cert.

Kept only when ALL hold: re-install (or convert) with the cert on disk covering this host (`_reuse_avail`), selfsigned
GIVEN in the environment, and the cert is ITSELF self-signed (issuer == subject). Typed at the prompt, a CA-issued cert,
a cert for another host, or another mode: unchanged.

The decision block, cert_self_signed and cert_covers_host are lifted out of install-host.sh AS SHIPPED and run over
real certificates made here with openssl.

Run: python3 tests/selfsigned_keep_selftest.py     (0 = pass)
     --perturb   the keep taken back out (mk_selfsigned every time, the shipped behaviour) → RED
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
src = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
if not shutil.which("openssl"):
    print("SKIP — no openssl"); sys.exit(0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def fn(name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

i = src.index("REUSE_TLS=no\n"); j = src.index("\n# ", src.index('(remove $TLS_DIR first to issue a new one)"', i))
block = src[i:j] + "\n"
assert '_TLS_GIVEN="$TLS_MODE"' in src, "the GIVEN capture is gone — would FALSE-PASS"
if PERTURB:
    a = "  REUSE_TLS=yes\n  ok \"keeping the existing self-signed certificate"
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, "  :\n  ok \"keeping the existing self-signed certificate")
helpers = fn("cert_covers_host") + fn("cert_self_signed")

T = tempfile.mkdtemp(prefix="ssk-")
def sh(*a):
    subprocess.run(a, check=True, capture_output=True)
def selfsigned(name, host):
    d = os.path.join(T, name); os.makedirs(d)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-keyout", d + "/key.pem",
       "-out", d + "/fullchain.pem", "-subj", "/CN=" + host, "-addext", "subjectAltName=IP:" + host)
    return d
def ca_issued(name, host):
    d = os.path.join(T, name); os.makedirs(d)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-keyout", d + "/ca.key",
       "-out", d + "/ca.pem", "-subj", "/CN=Test CA")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", d + "/key.pem", "-out", d + "/leaf.csr",
       "-subj", "/CN=" + host, "-addext", "subjectAltName=IP:" + host)
    open(d + "/ext", "w").write("subjectAltName=IP:%s\n" % host)
    sh("openssl", "x509", "-req", "-in", d + "/leaf.csr", "-CA", d + "/ca.pem", "-CAkey", d + "/ca.key",
       "-CAcreateserial", "-days", "30", "-out", d + "/fullchain.pem", "-extfile", d + "/ext")
    return d

def run(tlsdir, given, chosen, host="192.168.77.5"):
    """given = TLS_MODE from the environment; chosen = what TLS_MODE is after the prompt loop."""
    script = ('set -euo pipefail\nPREFIX=""; TLS_DIR=%s; PANEL_DOMAIN=%s; TLS_SAVED=selfsigned\n_TLS_GIVEN="%s"; TLS_MODE="%s"\n'
              'b(){ printf %%s "$*"; }\nok(){ echo "OK $*"; }\n%s'
              '_reuse_avail=no; cert_covers_host "$TLS_DIR/fullchain.pem" "$PANEL_DOMAIN" && _reuse_avail=yes\n'
              '%secho "REUSE_TLS=$REUSE_TLS TLS_MODE=$TLS_MODE"\n') % (tlsdir, host, given, chosen, helpers, block)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return p.stdout + p.stderr

ss = selfsigned("ss", "192.168.77.5")
out = run(ss, "selfsigned", "selfsigned")
check("unattended TLS_MODE=selfsigned + a self-signed cert covering the host → KEPT (REUSE_TLS=yes), and said",
      "REUSE_TLS=yes TLS_MODE=selfsigned" in out and "keeping the existing self-signed certificate" in out, out)
out = run(ss, "", "selfsigned")
check("selfsigned TYPED at the prompt (nothing given) → a new one, as before", "REUSE_TLS=no" in out, out)
out = run(ca_issued("ca", "192.168.77.5"), "selfsigned", "selfsigned")
check("the cert on disk is CA-issued (issuer ≠ subject) → not kept by this rule", "REUSE_TLS=no" in out, out)
out = run(selfsigned("other", "10.9.9.9"), "selfsigned", "selfsigned")
check("a self-signed cert for ANOTHER host → not kept (it would not serve this one)", "REUSE_TLS=no" in out, out)
out = run(ss, "letsencrypt", "letsencrypt")
check("another mode given (letsencrypt) → unchanged", "REUSE_TLS=no TLS_MODE=letsencrypt" in out, out)
out = run(ss, "reuse", "reuse")
check("`reuse` still reuses, through its own branch", "REUSE_TLS=yes" in out and "keeping the existing self-signed" not in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
