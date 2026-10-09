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

[2] (1.8.8 deferred #6) an ACME issuance that FAILED (letsencrypt-ip with :80 closed) is recorded as what is served: the
    REAL obtain_cert_internal → its self-signed fallback rewrites install.conf's TLS_MODE and the panel's Access & TLS mode
    (seed_access_settings, the real one) to selfsigned and says how to ask again — they said letsencrypt-ip / letsencrypt
    while a self-signed certificate was served, and every update promised renewals; CONTROL: an issuance that worked
    leaves both as asked

Run: python3 tests/selfsigned_keep_selftest.py     (0 = pass)
     --perturb   the keep taken back out (mk_selfsigned every time, the shipped behaviour) → RED
     --perturb-fallback   the fallback records nothing (e66018f's bare mk_selfsigned) → RED on [2] only
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

print("\n[2] a failed issuance is recorded as what is served (1.8.8 deferred #6)")
import json
PF = "--perturb-fallback" in sys.argv
lib = open(os.path.join(ROOT, "lib/common.sh"), encoding="utf-8").read()
m = re.search(r"^seed_access_settings\(\)\{.*?^PYACC\n  return 0; \}\n", lib, re.S | re.M)
assert m, "seed_access_settings not found in lib/common.sh"
OBT = fn("obtain_cert_internal")
if PF:
    a = 'falling back to a self-signed cert."; tls_fallback_selfsigned; return'
    assert OBT.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    OBT = OBT.replace(a, 'falling back to a self-signed cert."; mk_selfsigned; return')
def issue(acme_rc):
    d = tempfile.mkdtemp(prefix="ssk-fb-", dir=T)
    for x in ("etc", "state", "tls"):
        os.makedirs(os.path.join(d, x))
    open(os.path.join(d, "etc/install.conf"), "w").write("PANEL_DOMAIN=203.0.113.7\nTLS_MODE=letsencrypt-ip\nSERVE_MODE=internal\n")
    json.dump({"access": {"panel": {"url": "https://203.0.113.7:2097"}, "tls": {"mode": "letsencrypt-ip", "email": "a@b.c"}}},
              open(os.path.join(d, "state/panel-settings.json"), "w"))
    script = ('set -euo pipefail\nDRYRUN=false; PREFIX=""; TLS_DIR=%s/tls; ETC_DIR=%s/etc; STATE_DIR=%s/state; PANEL_USER=nobody\n'
              'PANEL_DOMAIN=203.0.113.7; PANEL_BASE=""; PORT=2097; TLS_MODE=letsencrypt-ip; SERVE_MODE=internal; REUSE_TLS=no\n'
              'ACME_EMAIL=""; CF_TOKEN=""; CF_ACCOUNT_ID=""\n'
              'run(){ "$@"; }; have(){ case "$1" in ss) return 1;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
              'info(){ :; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; b(){ printf %%s "$*"; }; col(){ shift; printf %%s "$*"; }\n'
              'ensure_acme(){ :; }; acme_has_cert(){ return 1; }; acme_clear_unusable(){ :; }; cert_perms(){ :; }\n'
              'acme(){ return %d; }; prune_stale_acme_installs(){ :; }; acme_foreign_target(){ :; }\n'
              '%s%s%s%s%s'
              'obtain_cert_internal\necho "TLS_MODE_NOW=$TLS_MODE"\n') % (d, d, d, acme_rc, m.group(0), fn("san_for"), fn("mk_selfsigned"),
                                                                   fn("tls_fallback_selfsigned") if "tls_fallback_selfsigned(){" in src else "",
                                                                   OBT)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    conf = open(os.path.join(d, "etc/install.conf")).read()
    ps = json.load(open(os.path.join(d, "state/panel-settings.json")))
    return r, conf, ps, d
r, conf, ps, d = issue(1)
check("issuance failed → install.conf says TLS_MODE=selfsigned, as served", "TLS_MODE=selfsigned\n" in conf and "letsencrypt" not in conf,
      (conf, r.stdout + r.stderr))
check("…the panel's Access & TLS mode too (its email kept), and the run's TLS_MODE", ps["access"]["tls"]["mode"] == "selfsigned"
      and ps["access"]["tls"].get("email") == "a@b.c" and "TLS_MODE_NOW=selfsigned" in r.stdout, (ps, r.stdout))
check("…a self-signed certificate is what was made, and the warning says how to ask again",
      os.path.getsize(os.path.join(d, "tls/fullchain.pem")) > 0 and "to try letsencrypt-ip again" in r.stdout, r.stdout + r.stderr)
r, conf, ps, d = issue(0)
check("CONTROL: an issuance that worked → install.conf and Settings keep letsencrypt-ip", "TLS_MODE=letsencrypt-ip\n" in conf
      and ps["access"]["tls"]["mode"] == "letsencrypt-ip", (conf, ps, r.stdout + r.stderr))

print()
if PF:
    _red = [f for f in FAILS if f.startswith(("issuance failed", "…the panel's Access", "…a self-signed certificate"))]
    print("perturb-fallback: %s" % ("RED as it must be (%d), all [2]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
