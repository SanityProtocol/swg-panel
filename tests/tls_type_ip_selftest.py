#!/usr/bin/env python3
"""Self-test — a panel on a certificate by IP knows its TLS type (card tls-type-ip; found on alb-onyx, 2026-11-27).

A bare-metal panel's first start is plain HTTP: its certificate does not exist yet. The boot reconcile therefore clears
the type the installer seeded, and the next start reads it off the certificate (swg-panel-server _infer_tls_mode). That
reading could not say "by IP": the box's install.conf said letsencrypt-ip, its settings letsencrypt. A Docker panel
started by hand with compose has no installer to seed anything: with the placeholder on the socket it read
"selfsigned", and was healed later to "letsencrypt", by IP too.

  [1] _cert_ip_only: a certificate that names addresses and no DNS name — and only that; _cert_is_letsencrypt: its
      issuer's organisation (the staging CA's too), and no other CA's
  [2] _infer_tls_mode on a public CA's certificate: Let's Encrypt's by IP → letsencrypt-ip, whatever token or address
      is stored; another CA's by IP → as before this card (review F4); by name → letsencrypt, or cloudflare with a
      token; Cloudflare's Origin CA → cf15, as before
  [3] …with the placeholder on the socket: a container reads the Let's Encrypt or self-signed type it was started with
      (after the token test, before the address guess); a Cloudflare type is not read from it — its token is the
      settings', and a container started without one is where the entrypoint fell back (review F3); `none` and
      anything unknown read as before; bare-metal reads no such record
  [4] the sequence alb-onyx walked, through _reconcile_saved_ahead as shipped: the seeded type, a plain-HTTP start that
      clears it, an HTTPS start on a certificate by IP → letsencrypt-ip (by name → letsencrypt)
  [5] a stored type is never rewritten: a panel that already says letsencrypt over a certificate by IP keeps it
  [6] the type follows the address (validate_access, review F2): a panel by IP that moves to a name is saved as
      letsencrypt — the root helper issues nothing in letsencrypt-ip, so the move failed at the apply; one that stays
      by IP keeps its type; nothing is mapped the other way

Certificates are made here with openssl (test CAs named as Let's Encrypt, its staging CA, another CA and Cloudflare's
Origin CA; leaves by IP, by name, by both; a self-signed placeholder).

Run: python3 tests/tls_type_ip_selftest.py      (0 = pass)
     --perturb   each change taken back out must turn ITS OWN check red ("N plants, N caught")
"""
import atexit, contextlib, io, json, os, shutil, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_TTI_PANEL") or os.path.join(ROOT, "swg-panel-server")
SRC = open(PANEL, encoding="utf-8").read()

# (name, anchor, replacement, the check that must go red)
IP_LINES = '        if _cert_ip_only(TLS_CERT) and _cert_is_letsencrypt(TLS_CERT):\n            return "letsencrypt-ip"\n'
GIVEN = '        if _given in ("letsencrypt", "letsencrypt-ip", "selfsigned"):\n'
FOLLOW = '    if mode == "letsencrypt-ip" and _ph and not _is_ip(_ph):\n        mode = "letsencrypt"\n'
PLANTS = [
    ("ip", IP_LINES, "", "[2] Let's Encrypt's certificate by IP reads letsencrypt-ip"),
    ("ip-token", IP_LINES, IP_LINES.replace("(TLS_CERT):", '(TLS_CERT) and not str(tls.get("cf_token") or "").strip():'),
     "[2] …whatever Cloudflare token or address is stored"),
    ("ip-dns", '        return "IP Address" in kinds and "DNS" not in kinds\n', '        return "IP Address" in kinds\n',
     "[1] a certificate that also carries a DNS name is not one by IP"),
    ("issuer", IP_LINES, IP_LINES.replace(" and _cert_is_letsencrypt(TLS_CERT)", ""),
     "[2] another CA's certificate by IP reads as it did before this card"),
    ("issuer-any", '        return "let\'s encrypt" in str(iss.get("organizationName", "")).lower()\n',
     '        return bool(iss.get("organizationName"))\n', "[1] _cert_is_letsencrypt: Let's Encrypt and its staging CA, no other"),
    ("docker", "    if IN_DOCKER:\n        _given = (os.environ.get(\"TLS\") or \"\").strip()\n", "    if False:\n        _given = \"\"\n",
     "[3] a container, the placeholder on the socket: the TLS it was started with"),
    ("bare", "    if IN_DOCKER:\n        _given = (os.environ.get(\"TLS\") or \"\").strip()\n",
     "    if True:\n        _given = (os.environ.get(\"TLS\") or \"\").strip()\n", "[3] bare-metal reads no such record"),
    ("none", GIVEN, "        if _given:\n", "[3] `none` and an unknown value read as before"),
    ("cf-env", GIVEN, '        if _given in TLS_MODES and _given not in ("", "skip"):\n',
     "[3] a container started with a Cloudflare type reads as before: its token is the settings' to hold"),
    ("follow", FOLLOW, "", "[6] a panel by IP that moves to a name is saved as letsencrypt"),
    ("follow-all", FOLLOW, FOLLOW.replace(" and not _is_ip(_ph)", ""), "[6] a panel that stays by IP keeps its type"),
    ("follow-sub", FOLLOW, FOLLOW.replace("    if mode", '    _ph = _ph if _ph and not _is_ip(_ph) else _url_host(sub["url"])\n    if mode'),
     "[6] a subscription page on a name of its own does not change the panel's type"),
]

if "--perturb" in sys.argv:
    bad = 0
    for name, old, new, must in PLANTS:
        if SRC.count(old) != 1:
            print("  %-9s STALE ANCHOR (%d) — this plant would plant nothing" % (name, SRC.count(old))); bad += 1; continue
        d = tempfile.mkdtemp(prefix="tti-plant-")
        f = os.path.join(d, "swg-panel-server")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(SRC.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, SWG_TTI_PANEL=f), capture_output=True, text=True, timeout=300)
        shutil.rmtree(d, ignore_errors=True)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-9s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:900]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


SB = tempfile.mkdtemp(prefix="tti-")
atexit.register(shutil.rmtree, SB, True)


def ossl(*a, **kw):
    r = subprocess.run(("openssl",) + a, capture_output=True, text=True, timeout=60, cwd=SB, **kw)
    assert r.returncode == 0, (a, r.stderr[-400:])


def ca(name, subj):
    ossl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", name + ".key",
         "-out", name + ".pem", "-subj", subj, "-days", "2")


def leaf(name, issuer, subj, san):
    with open(os.path.join(SB, name + ".ext"), "w") as f:
        f.write("subjectAltName=%s\n" % san)
    ossl("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", name + ".key",
         "-out", name + ".csr", "-subj", subj)
    ossl("x509", "-req", "-in", name + ".csr", "-CA", issuer + ".pem", "-CAkey", issuer + ".key", "-CAcreateserial",
         "-out", name + ".pem", "-days", "2", "-extfile", name + ".ext")
    return os.path.join(SB, name + ".pem")


ca("ca", "/C=US/O=Let's Encrypt/CN=YE1")                       # the issuer of the certificate by IP seen on alb-onyx
ca("stg", "/C=US/O=(STAGING) Let's Encrypt/CN=(STAGING) YE1")
ca("other", "/C=US/O=Test Trust Services/CN=T1")                # another CA: an operator's own certificate
ca("cfca", "/C=US/O=CloudFlare, Inc./CN=CloudFlare Origin CA")
BY_IP = leaf("ip", "ca", "/", "critical,IP:203.0.113.77")
BY_IP_STG = leaf("ipstg", "stg", "/", "critical,IP:203.0.113.77")
BY_IP_OTHER = leaf("ipother", "other", "/", "critical,IP:203.0.113.77")
BY_NAME = leaf("name", "ca", "/CN=panel.example.org", "DNS:panel.example.org")
BY_NAME_OTHER = leaf("nameother", "other", "/CN=panel.example.org", "DNS:panel.example.org")
BY_BOTH = leaf("both", "ca", "/CN=panel.example.org", "DNS:panel.example.org,IP:203.0.113.77")
CF_ORIGIN = leaf("cf", "cfca", "/CN=panel.example.org", "DNS:panel.example.org")
ossl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", "ph.key", "-out",
     "ph.pem", "-subj", "/CN=203.0.113.77", "-days", "2")
PLACEHOLDER = os.path.join(SB, "ph.pem")

M = types.ModuleType("p"); M.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(SRC.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), M.__dict__)
M.BIND_PORT = 443; M.BIND_HOST = "0.0.0.0"; M.PANEL_BASE = ""


def infer(cert, tls=None, docker=None):
    M.TLS_CERT = cert
    M.IN_DOCKER = docker is not None
    os.environ.pop("TLS", None)
    if docker:
        os.environ["TLS"] = docker
    try:
        return M._infer_tls_mode({"panel_settings": {"access": {"tls": dict(tls or {})}}})
    finally:
        os.environ.pop("TLS", None)


# ── [1] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] _cert_ip_only, _cert_is_letsencrypt")
check("[1] a certificate by IP: yes", M._cert_ip_only(BY_IP) is True)
check("[1] a certificate by name: no", M._cert_ip_only(BY_NAME) is False)
check("[1] a certificate that also carries a DNS name is not one by IP", M._cert_ip_only(BY_BOTH) is False)
check("[1] the placeholder (a name in its subject, no SAN), a missing file, no path: no",
      [M._cert_ip_only(PLACEHOLDER), M._cert_ip_only(os.path.join(SB, "nope.pem")), M._cert_ip_only("")] == [False] * 3)
got = [M._cert_is_letsencrypt(c) for c in (BY_IP, BY_NAME, BY_IP_STG, BY_IP_OTHER, BY_NAME_OTHER, CF_ORIGIN, PLACEHOLDER,
                                           os.path.join(SB, "nope.pem"), "")]
check("[1] _cert_is_letsencrypt: Let's Encrypt and its staging CA, no other", got == [True] * 3 + [False] * 6, got)

# ── [2] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] _infer_tls_mode on a public CA's certificate")
check("[2] Let's Encrypt's certificate by IP reads letsencrypt-ip", infer(BY_IP) == "letsencrypt-ip", infer(BY_IP))
got = [infer(BY_IP_OTHER), infer(BY_IP_OTHER, {"cf_token": "x" * 40}), infer(BY_NAME_OTHER)]
check("[2] another CA's certificate by IP reads as it did before this card", got == ["letsencrypt", "cloudflare", "letsencrypt"], got)
got = [infer(BY_IP, {"cf_token": "x" * 40}), infer(BY_IP, {"email": "ops@example.org"}), infer(BY_IP, docker="letsencrypt")]
check("[2] …whatever Cloudflare token or address is stored", got == ["letsencrypt-ip"] * 3, got)
got = [infer(BY_NAME), infer(BY_NAME, {"cf_token": "x" * 40}), infer(BY_BOTH), infer(CF_ORIGIN)]
check("[2] by name: letsencrypt, cloudflare with a token; by both names: letsencrypt; Cloudflare's Origin CA: cf15",
      got == ["letsencrypt", "cloudflare", "letsencrypt", "cf15"], got)

# ── [3] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the placeholder on the socket")
got = {v: infer(PLACEHOLDER, docker=v) for v in ("letsencrypt-ip", "letsencrypt", "selfsigned")}
check("[3] a container, the placeholder on the socket: the TLS it was started with", all(k == v for k, v in got.items()), got)
got = [infer(PLACEHOLDER, docker="cloudflare"), infer(PLACEHOLDER, docker="cf15"),
       infer(PLACEHOLDER, {"email": "ops@example.org"}, docker="cloudflare"),
       infer(PLACEHOLDER, {"cf_token": "x" * 40}, docker="cloudflare"),
       infer(PLACEHOLDER, {"cf_origin_token": "x" * 40}, docker="cf15")]
check("[3] a container started with a Cloudflare type reads as before: its token is the settings' to hold",
      got == ["selfsigned", "selfsigned", "letsencrypt", "cloudflare", "selfsigned"], got)
got = [infer(PLACEHOLDER, docker="none"), infer(PLACEHOLDER, docker="skip"), infer(PLACEHOLDER, docker="bogus"),
       infer(PLACEHOLDER, {"email": "ops@example.org"}, docker="none")]
check("[3] `none` and an unknown value read as before", got == ["selfsigned", "selfsigned", "selfsigned", "letsencrypt"], got)
got = infer(PLACEHOLDER, {"cf_token": "x" * 40}, docker="letsencrypt")
check("[3] a stored Cloudflare token still decides first", got == "cloudflare", got)
M.TLS_CERT = PLACEHOLDER; M.IN_DOCKER = False; os.environ["TLS"] = "letsencrypt-ip"
got = [M._infer_tls_mode({"panel_settings": {"access": {"tls": {}}}}),
       M._infer_tls_mode({"panel_settings": {"access": {"tls": {"email": "ops@example.org"}}}})]
os.environ.pop("TLS", None)
check("[3] bare-metal reads no such record", got == ["selfsigned", "letsencrypt"], got)

# ── [4] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the sequence a bare-metal install walks")


def start(settings, cert):
    t = tempfile.mkdtemp(prefix="boot-", dir=SB)
    deps = {"panel_settings": json.loads(json.dumps(settings)), "panel_settings_path": os.path.join(t, "panel-settings.json"),
            "nodes_path": os.path.join(t, "nodes.json")}
    M.TLS_CERT = cert; M.IN_DOCKER = False
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        M._reconcile_saved_ahead(deps, None)
    return deps["panel_settings"], buf.getvalue()


def seeded(mode, host):
    return {"access": {"panel": {"url": "https://" + host, "port": 443, "host": "0.0.0.0", "base": "/"},
                       "tls": {"mode": mode, "email": ""}}}


s1, out1 = start(seeded("letsencrypt-ip", "203.0.113.77"), "")
check("[4] the first start is plain HTTP: the seeded type is cleared, as it always was",
      s1["access"]["tls"]["mode"] == "" and "it is 'None' (reverse proxy) again" in out1, (s1["access"]["tls"], out1))
s2, out2 = start(s1, BY_IP)
check("[4] the start on the issued certificate by IP reads letsencrypt-ip",
      s2["access"]["tls"]["mode"] == "letsencrypt-ip" and "it is 'letsencrypt-ip' again" in out2, (s2["access"]["tls"], out2))
s3, _ = start(start(seeded("letsencrypt", "panel.example.org"), "")[0], BY_NAME)
check("[4] …and letsencrypt for a panel by name, as before", s3["access"]["tls"]["mode"] == "letsencrypt", s3["access"]["tls"])

# ── [5] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] a stored type stays")
s4, out4 = start(seeded("letsencrypt", "203.0.113.77"), BY_IP)
check("[5] a panel that already says letsencrypt over a certificate by IP keeps it, and nothing is said",
      s4["access"]["tls"]["mode"] == "letsencrypt" and "TLS type" not in out4, (s4["access"]["tls"], out4))

# ── [6] ──────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the type follows the address")
IP_URL, NAME_URL = "https://203.0.113.77", "https://panel.example.org"


def save(cur_mode, cur_url, inc, docker=False, sub_url=""):
    M.IN_DOCKER = docker
    cur = {"panel": {"url": cur_url, "host": "0.0.0.0", "port": 443},
           "sub": {"url": sub_url, "host": "0.0.0.0", "port": 8444}, "tls": {"mode": cur_mode, "email": ""}}
    clean, errs, _warn = M.validate_access(inc, cur)
    M.IN_DOCKER = False
    return clean["tls"]["mode"], errs


def to(url, port=443, **more):
    return dict({"panel": {"url": url, "host": "0.0.0.0", "port": port}}, **more)


got = [save("letsencrypt-ip", IP_URL, to(NAME_URL)), save("letsencrypt-ip", IP_URL, to(NAME_URL), docker=True),
       save("letsencrypt-ip", IP_URL, to(NAME_URL, tls={"mode": "letsencrypt-ip"})),      # as the screen sends it
       save("letsencrypt-ip", IP_URL, to("https://panel.example.org:8443/swg", 8443))]
check("[6] a panel by IP that moves to a name is saved as letsencrypt", got == [("letsencrypt", [])] * 4, got)
check("[6] …and the certificate by IP does not cover that name, so the apply orders one — in a type the helper issues",
      M._cert_needs_issue(BY_IP, "panel.example.org", "letsencrypt") is True)
got = [save("letsencrypt-ip", IP_URL, to("https://203.0.113.77:8443", 8443)), save("letsencrypt-ip", IP_URL, to("https://203.0.113.78")),
       save("letsencrypt-ip", IP_URL, to("https://[2001:db8::7]")), save("letsencrypt-ip", IP_URL, {"sub": {"port": 8445}}),
       save("letsencrypt-ip", "", {"sub": {"port": 8445}})]
check("[6] a panel that stays by IP keeps its type", got == [("letsencrypt-ip", [])] * 5, got)
got = save("letsencrypt-ip", IP_URL, {"sub": {"url": "https://sub.example.org:8444", "host": "0.0.0.0", "port": 8444}})
check("[6] a subscription page on a name of its own does not change the panel's type", got == ("letsencrypt-ip", []), got)
mode, errs = save("letsencrypt", NAME_URL, to(IP_URL))
check("[6] nothing is mapped the other way: letsencrypt with an address is refused, as before",
      mode == "letsencrypt" and errs == ["Panel: letsencrypt needs a domain URL, not an IP address."], (mode, errs))
got = [save(m, IP_URL, to(NAME_URL))[0] for m in ("selfsigned", "letsencrypt", "", "skip")]
check("[6] every other type is saved as sent", got == ["selfsigned", "letsencrypt", "", "skip"], got)
mode, errs = save("letsencrypt-ip", IP_URL, to(NAME_URL), sub_url="https://203.0.113.77:8444")
check("[6] a subscription page left on the address is then refused as for any letsencrypt panel",
      mode == "letsencrypt" and errs == ["Subscription: letsencrypt needs a domain URL, not an IP address."], (mode, errs))

print("\n" + ("ALL PASS" if not FAILS else "FAILED: %d\n  " % len(FAILS) + "\n  ".join(FAILS)))
sys.exit(1 if FAILS else 0)
