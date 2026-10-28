#!/usr/bin/env python3
"""Self-test — A DOCKER PANEL'S Let's Encrypt CERTIFICATE KEEPS RENEWING, AND THE SUBSCRIPTION PAGE FOLLOWS IT (S9f).

A user's Docker panel (letsencrypt-ip, the sub page on the same IP) served a certificate that never renewed: the
entrypoint's cover test read DNS SANs only, so the sub took the Let's Encrypt branch, and its `--install-cert` on the
panel's own acme entry sent every renewal to the sub's directory with no reload (acme.sh keeps ONE target per entry).
The panel would have died at day 6.7; a start that reuses the cert on disk never put the entry back; a sub copy went
stale at the first renewal; the loop called a 6.7-day certificate "failing" from its first day; and a bare→Docker
convert left the host's copy of the same entries renewing (and failing on :80) for ever.

The entrypoint's own functions run (lifted out of docker/entrypoint.sh as they are) against real openssl certificates,
a fake acme.sh that records its calls and writes an entry conf, and temp dirs; swg-sub runs for real on loopback.
No root, no network, nothing outside the temp dir.

Run: python3 tests/docker_acme_entry_selftest.py      (0 = pass)
     --perturb   every plant below (each a fix taken back out) must turn ITS OWN check red ("N plants, N caught").
"""
import contextlib, importlib.machinery, importlib.util, json, os, shutil, socket, ssl, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
# every source this test reads, overridable so --perturb can hand it a planted copy
SRCS = {"ENTRY": "docker/entrypoint.sh", "NCD": "docker/swg-netctl-docker", "SUB": "swg-sub",
        "COMMON": "lib/common.sh", "IDOCKER": "install-docker.sh"}
PATHS = {k: os.environ.get("SWG_DAE_" + k) or os.path.join(ROOT, v) for k, v in SRCS.items()}

# (file key, anchor, replacement, the check that must go red)
PLANTS = [
    ("ENTRY", '  hip="$(ip_canon "$host")"\n', '  hip=""\n',
     "[1] an IP certificate covers its own IP (v4)"),
    ("NCD", '        for ip in re.findall(r"IP Address:([^,\\s]+)", out):', '        for ip in []:',
     "[1] swg-netctl-docker: an IP certificate covers its own IP"),
    ("ENTRY", '  elif acme_entry_is_panels "$SUB_DOMAIN"; then', '  elif false; then',
     "[2] the panel's file not there yet: the sub still never installs onto the panel's entry"),
    ("ENTRY", '  cmp -s "$SWG_PANEL_TLS_KEY" "$e/${PANEL_DOMAIN}.key" || return 0\n  [ "$(acme_target "$PANEL_DOMAIN")" = "$SWG_PANEL_TLS_CERT" ] && return 0',
     '  return 0',
     "[3] a hijacked entry is re-pointed at the panel's certificate"),
    ("ENTRY", '  log "using the certificate already present at $SWG_PANEL_TLS_CERT (mounted / previously issued)"\n  acme_reassert\n',
     '  log "using the certificate already present at $SWG_PANEL_TLS_CERT (mounted / previously issued)"\n',
     "[3] …on a start that reuses the certificate on disk"),
    ("ENTRY", '  cmp -s "$SWG_PANEL_TLS_CERT" "$SC" && return 0\n', '  return 0\n',
     "[4] a renewed panel certificate reaches the sub's copy"),
    ("ENTRY", '  cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && return 0     # a failed issuance\'s placeholder never replaces the sub\'s cert\n', '',
     "[4] …a self-signed panel placeholder never replaces the sub's certificate"),
    ("ENTRY", '  cmp -s "$SWG_PANEL_TLS_KEY" "$e/${PANEL_DOMAIN}.key" || return 0\n', '',
     "[3] …a certificate the operator mounted over the entry stays theirs"),
    ("ENTRY", '  case "${TLS:-}" in letsencrypt|letsencrypt-ip|cloudflare) ;; *) return 0 ;; esac\n  acme_has_cert || return 0\n',
     '  acme_has_cert || return 0\n',
     "[3] …only in an acme mode (selfsigned: nothing is re-pointed)"),
    ("ENTRY", '    [ -f "$f" ] && [ "$(sed -n', '    false && [ "$(sed -n',
     "[4] …a sub with its own acme entry installing to its files is left to that entry"),
    ("ENTRY", '  [ -n "$(ip_canon "$SUB_DOMAIN")" ] && san="IP:$(ip_canon "$SUB_DOMAIN")"', '  :',
     "[2] a self-signed sub on an IP writes an IP SAN, and is reused on the next start"),
    ("ENTRY", '  if [ -n "$pc" ] && cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && sub_pair_kept; then', '  if false; then',
     "[2] a self-signed panel certificate never replaces the sub's own self-signed pair"),
    ("ENTRY", '  if [ -n "$pc" ] && cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && sub_pair_kept; then', '  if [ -n "$pc" ] && sub_pair_kept; then',
     "[2] …a real panel certificate still replaces an older copy"),
    ("ENTRY", '  [ -n "$p" ] && [ "$p" = "$(openssl pkey -in "$SK" -pubout 2>/dev/null)" ] || return 1\n', '',
     "[2] …a torn sub pair, or one with no key, is written again, not kept"),
    ("ENTRY", '; else ! cert_is_selfsigned "$SC"; fi; }', '; else false; fi; }',
     "[2] …a CA mode: a self-signed panel placeholder never replaces the sub's real certificate"),
    ("ENTRY", '  if [ "${TLS:-selfsigned}" = selfsigned ]; then cert_is_selfsigned "$SC"; else', '  if [ "${TLS:-selfsigned}" = selfsigned ]; then :; else',
     "[2] …selfsigned: a CA-issued sub copy is replaced by the panel's covering certificate"),
    ("ENTRY", '    for dns in $(openssl x509 -in "$1" -noout -text 2>/dev/null | grep -oE \'DNS:[^,[:space:]]+\' | cut -d: -f2-); do\n      [ "$dns" = "$host" ] || [ "$(ip_canon "$dns")" = "$hip" ] && return 0\n    done\n    return 1',
     '    return 1',
     "[1] …an IP spelled as a DNS SAN (an earlier image's self-signed sub cert) still covers it"),
    ("ENTRY", 'cut -d: -f2-); do\n      [ "$dns" = "$host" ] || [ "$(ip_canon "$dns")" = "$hip" ] && return 0', 'cut -d: -f2); do\n      [ "$dns" = "$host" ] && return 0',
     "[1] …an IPv6 spelled as a DNS SAN covers it, bracketed or not"),
    ("ENTRY", '[ "$(ip_canon "$dns")" = "$hip" ] && return 0', '[ "$dns" = "$hip" ] && return 0',
     "[1] …an IPv6 DNS SAN spelled long covers the short form (review F4)"),
    ("ENTRY", ' | sed -n 1p | tr \'[:upper:]\' \'[:lower:]\')" = "$dl" ]', ' | sed -n 1p)" = "$d" ]',
     "[4] …the sub's own entry in another letter case is still its renewer (review F3)"),
    ("ENTRY", '      && { [ -z "$d" ] || [ "$(sed -n "s/^Le_Domain=', '      && { true || [ "$(sed -n "s/^Le_Domain=',
     "[4] …a stale entry for a host the sub had before does not stop the copy"),
    ("ENTRY", 'print(ipaddress.ip_address(sys.argv[1].strip("[]")))', 'print(ipaddress.ip_address(sys.argv[1]))',
     "[1] …a bracketed IPv6 host, as swg-netctl-docker reads it"),
    ("NCD", '                    shutil.copyfile(src, dst + ".new"); os.chmod(dst + ".new", mode); os.replace(dst + ".new", dst)',
     '                    shutil.copyfile(src, dst); os.chmod(dst, mode)',
     "[1] swg-netctl-docker copies the panel's pair into sub-tls by rename, key first"),
    ("COMMON", '    [ -d "$h" ] || continue                                 # the first that exists, as convert.sh copies (review F9)\n',
     '    [ -x "$h/acme.sh" ] || continue\n',
     "[7] the store convert.sh copied is the one retired, with or without an acme.sh in it"),
    ("IDOCKER", '  if [ "${SWG_FORCE_PORT80:-}" != 1 ] && ! $DRYRUN && have ss && [ "${_own80:-0}" = 0 ] &&',
     '  if [ "${SWG_FORCE_PORT80:-}" != 1 ] && ! $DRYRUN && have ss &&',
     "[8] a re-install does not read the panel's own docker-proxy on :80 as taken"),
    ("ENTRY", '        sub_follow_panel || true\n', '',
     "[4] …after every --cron of the renewal loop"),
    ("SUB", '        threading.Thread(target=_watch_cert, name="cert-watch", daemon=True).start()\n', '',
     "[5] swg-sub serves a certificate whose files changed, with no signal"),
    ("ENTRY", '  if [ "$life" -gt 0 ] && [ "$life" -le 864000 ]; then', '  if [ "$life" -gt 0 ] && [ "$life" -le 0 ]; then',
     "[6] a 7-day certificate with 5 days left is not failing"),
    ("ENTRY", '  if [ -s "$ACME_CFG/.port80-held" ] && [ "${TLS:-}" != cloudflare ]; then', '  if false; then',
     "[6] a failing renewal names who holds port 80 (letsencrypt-ip: no DNS-01 offer)"),
    ("ENTRY", 'echo ", or switch to Cloudflare DNS-01" || true)"', 'echo ", or switch to Cloudflare DNS-01")"',
     "[6] a failing renewal names who holds port 80 (letsencrypt-ip: no DNS-01 offer)"),
    ("COMMON", '      case "$rp" in /etc/swg-panel/tls/*|/etc/swg-sub/tls/*) ;; *) continue ;; esac\n', '',
     "[7] the user's own entry in the host store stays"),
    ("COMMON", '      [ -n "$d" ] && [ -d "$vol/$(basename "$dir")" ] || continue\n', '      [ -n "$d" ] || continue\n',
     "[7] an entry of ours with no copy in the container stays"),
    ("IDOCKER", '  [ "${SWG_CONVERT_KILL_PANEL:-}" = 1 ] && retire_carried_acme "$PREFIX$INSTALL_DIR/data/etc/acme"', '  :',
     "[7] the convert's switch retires the host's copies (after the bare panel is torn down)"),
    ("IDOCKER", '''    mkdir -p "${P80HELD%/*}" 2>/dev/null && printf '%s\\n' "${_p80who:-another program}" > "$P80HELD" 2>/dev/null || true\n''', '',
     "[8] the installer leaves who holds :80 for the renewal loop"),
]

if "--perturb" in sys.argv:
    import concurrent.futures as cf

    def _plant_run(plant):
        """One plant: a planted copy of its file, this whole gate run against it → (key, must, verdict or stale line)."""
        key, old, new, must = plant
        src = open(PATHS[key], encoding="utf-8").read()
        if src.count(old) != 1:
            return key, must, "%s: anchor found %d times (stale plant) — %s" % (key, src.count(old), must)
        src = src.replace(old, new)
        with tempfile.NamedTemporaryFile("w", suffix="-plant", delete=False) as f:
            f.write(src)
        try:
            r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_DAE_" + key: f.name}),
                               capture_output=True, text=True, timeout=300)
            red = ("  FAIL " + must) in r.stdout and r.returncode != 0
        except subprocess.TimeoutExpired as e:
            r = subprocess.CompletedProcess([], 1, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "")
            red = True
        os.unlink(f.name)
        return key, must, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")

    caught, bad = 0, []
    with cf.ThreadPoolExecutor(4) as ex:
        for key, must, v in ex.map(_plant_run, PLANTS):
            if v not in ("caught", "CRASHED", "NOT CAUGHT"):
                bad.append(v); continue
            print("  %-8s %s — %s" % (key, v, must[:80]))
            caught += v == "caught"
            if v != "caught":
                bad.append(must)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    for b_ in bad:
        print("  ✗ " + b_)
    sys.exit(0 if caught == len(PLANTS) and not bad else 1)

FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="dockeracme-")
IP, IP6, IP6C = "203.0.113.7", "2001:db8::7", "2001:DB8:0:0:0:0:0:7"


def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=60, **kw)


# ── certificates: a test CA and leaves signed by it (a self-signed leaf is not what Let's Encrypt hands out) ─────────
CA = os.path.join(TMP, "ca")
os.makedirs(CA)
sh("openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "3650",
   "-keyout", CA + "/ca.key", "-out", CA + "/ca.pem", "-subj", "/CN=test CA")


def leaf(name, san, days, key=None):
    """(cert path, key path) of a leaf for `san`, `days` long; the key reused when given (acme.sh's renewals keep it)."""
    d = os.path.join(TMP, "certs", name)
    os.makedirs(d, exist_ok=True)
    k = key or os.path.join(d, "key.pem")
    if not key:
        sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", k)
    sh("openssl", "req", "-new", "-key", k, "-subj", "/O=test", "-out", d + "/csr.pem")
    with open(d + "/ext", "w") as f:
        f.write("subjectAltName=%s\n" % san)
    sh("openssl", "x509", "-req", "-in", d + "/csr.pem", "-CA", CA + "/ca.pem", "-CAkey", CA + "/ca.key",
       "-CAcreateserial", "-days", str(days), "-extfile", d + "/ext", "-out", d + "/cert.pem")
    with open(d + "/cert.pem") as f1, open(CA + "/ca.pem") as f2, open(d + "/fullchain.pem", "w") as o:
        o.write(f1.read() + f2.read())
    return d + "/fullchain.pem", k


IPC, IPK = leaf("ip", "IP:" + IP, 7)
IP6CRT, _ = leaf("ip6", "IP:" + IP6, 7)
DNSC, _ = leaf("dns", "DNS:panel.example.com", 90)
WILD, _ = leaf("wild", "DNS:*.example.com", 90)
IPC2, _ = leaf("ip-renewed", "IP:" + IP, 7, key=IPK)       # the same key, a new certificate: a renewal
LONG, _ = leaf("long", "DNS:panel.example.com", 90)

# ── a fake acme.sh: records each call, keeps an entry conf the way acme.sh does (ONE install target per entry) ─────────
FAKE = os.path.join(TMP, "fake-acme.py")
CALLS = os.path.join(TMP, "acme-calls.jsonl")
with open(FAKE, "w") as f:
    f.write(r'''#!/usr/bin/env python3
import json, os, shutil, sys
a = sys.argv[1:]
def opt(k): return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else ""
home = opt("--config-home") or opt("--home")
with open(os.environ["FAKE_ACME_CALLS"], "a") as f:
    f.write(json.dumps(a) + "\n")
d = opt("-d")
if "--install-cert" in a:
    e = os.path.join(home, d + "_ecc"); conf = os.path.join(e, d + ".conf")
    keep = [l for l in (open(conf).read().splitlines() if os.path.exists(conf) else [])
            if not l.startswith(("Le_RealFullChainPath=", "Le_RealKeyPath=", "Le_ReloadCmd="))]
    keep += ["Le_RealFullChainPath='%s'" % opt("--fullchain-file"), "Le_RealKeyPath='%s'" % opt("--key-file"),
             "Le_ReloadCmd='%s'" % opt("--reloadcmd")]
    open(conf, "w").write("\n".join(keep) + "\n")
    shutil.copyfile(os.path.join(e, "fullchain.cer"), opt("--fullchain-file"))
    shutil.copyfile(os.path.join(e, d + ".key"), opt("--key-file"))
    sys.exit(0)
if "--issue" in a:
    print("Skipping. Next renewal time is: …"); sys.exit(2)
sys.exit(0)
''')
os.chmod(FAKE, 0o755)

# ── the entrypoint's functions, lifted out as they are ────────────────────────────────────────────────────────────────
EP = open(PATHS["ENTRY"], encoding="utf-8").read()


def cut(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


LIB = os.path.join(TMP, "lib.sh")
with open(LIB, "w") as f:
    f.write(cut(EP, "#!/bin/sh", 'PANEL_USER="${PANEL_USER:-admin}"') + "\n"          # under its own `set -eu`, as it runs
            + cut(EP, "acme_has_cert(){", "\n# A present cert is a SELF-SIGNED placeholder") + "\n"
            + cut(EP, "sub_domain_cfg(){", "\n_sub_dom_cfg=") + "\n"
            + cut(EP, "# 4a) A subscription page serving", "\n# 4) Auto-renewal") + "\n")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
REAL_DATE = shutil.which("date")
with open(os.path.join(BIN, "date"), "w") as f:            # `date +%s` reads FAKE_NOW when set; everything else is date
    f.write('#!/bin/sh\nif [ "$#" = 1 ] && [ "$1" = "+%%s" ] && [ -n "${FAKE_NOW:-}" ]; then echo "$FAKE_NOW"; exit 0; fi\n'
            'exec %s "$@"\n' % REAL_DATE)
os.chmod(os.path.join(BIN, "date"), 0o755)


def world(name, tls="letsencrypt-ip", dom=IP):
    """A fresh container layout: the acme store with the panel's entry, the panel's and the sub's TLS dirs."""
    w = os.path.join(TMP, name)
    acme, etc, sub = w + "/acme", w + "/etc/tls", w + "/subtls"
    for d in (acme + "/%s_ecc" % dom, etc, sub):
        os.makedirs(d, exist_ok=True)
    e = acme + "/%s_ecc" % dom
    shutil.copyfile(IPC, e + "/fullchain.cer"); shutil.copyfile(IPC, e + "/%s.cer" % dom); shutil.copyfile(IPK, e + "/%s.key" % dom)
    with open(e + "/%s.conf" % dom, "w") as f:
        f.write("Le_Domain='%s'\n" % dom)
    env = dict(os.environ, PATH=BIN + ":" + os.environ["PATH"], ACME_BIN=FAKE, ACME_CONFIG=acme, FAKE_ACME_CALLS=CALLS,
               TLS=tls, PANEL_DOMAIN=dom, SWG_PANEL_TLS_CERT=etc + "/fullchain.pem", SWG_PANEL_TLS_KEY=etc + "/key.pem",
               SUB_TLS_DIR=sub, PANEL_SETTINGS=w + "/panel-settings.json")
    return w, env


def run(env, script):
    return subprocess.run(["sh", "-c", '. "%s"; %s' % (LIB, script)], env=env, capture_output=True, text=True, timeout=60)


def conf_val(w, dom, key):
    with open(w + "/acme/%s_ecc/%s.conf" % (dom, dom)) as f:
        for l in f:
            if l.startswith(key + "="):
                return l.split("=", 1)[1].strip().strip("'")
    return ""


def same(a, b):
    try:
        return open(a, "rb").read() == open(b, "rb").read()
    except OSError:
        return False


def calls():
    try:
        return [json.loads(l) for l in open(CALLS)]
    except OSError:
        return []


print("[1] the cover test reads IP SANs (entrypoint and swg-netctl-docker)")
_, env = world("w1")
def covers(c, h):
    return run(env, 'cert_covers_host "%s" "%s"' % (c, h)).returncode == 0
check("[1] an IP certificate covers its own IP (v4)", covers(IPC, IP))
check("[1] …not another IP", not covers(IPC, "203.0.113.8"))
check("[1] …IPv6: a SAN openssl prints unabbreviated covers the short form", covers(IP6CRT, IP6))
check("[1] …a DNS name and a single-label wildcard still cover as before", covers(DNSC, "panel.example.com")
      and covers(WILD, "sub.example.com") and not covers(WILD, "a.b.example.com") and not covers(DNSC, IP))
_l = importlib.machinery.SourceFileLoader("ncd", PATHS["NCD"])
_s = importlib.util.spec_from_loader("ncd", _l)
NCD = importlib.util.module_from_spec(_s)
_l.exec_module(NCD)
check("[1] swg-netctl-docker: an IP certificate covers its own IP", NCD._cert_covers_host(IPC, IP)
      and NCD._cert_covers_host(IP6CRT, IP6) and NCD._cert_covers_host(IP6CRT, IP6C))
_dnsip, _ = leaf("dns-ip", "DNS:" + IP, 3650)
check("[1] …an IP spelled as a DNS SAN (an earlier image's self-signed sub cert) still covers it", covers(_dnsip, IP))
check("[1] …a bracketed IPv6 host, as swg-netctl-docker reads it", covers(IP6CRT, "[" + IP6 + "]"))
_dnsip6, _ = leaf("dns-ip6", "DNS:" + IP6, 3650)
check("[1] …an IPv6 spelled as a DNS SAN covers it, bracketed or not", covers(_dnsip6, IP6) and covers(_dnsip6, "[" + IP6 + "]")
      and not covers(_dnsip6, "2001:db8::8"))
_dnsip6l, _ = leaf("dns-ip6-long", "DNS:2001:0DB8:0:0:0:0:0:7", 3650)
check("[1] …an IPv6 DNS SAN spelled long covers the short form (review F4)", covers(_dnsip6l, IP6) and not covers(_dnsip6l, "2001:db8::8"))
_nsrc = open(PATHS["NCD"], encoding="utf-8").read()
_ic = _nsrc[_nsrc.index('if verb == "issue-cert":'):][:3000]
check("[1] swg-netctl-docker copies the panel's pair into sub-tls by rename, key first", 'os.replace(dst + ".new", dst)' in _ic
      and _ic.index("(panel_key, sk, 0o600)") < _ic.index("(panel_cert, sc, 0o644)"), _ic[:400])
check("[1] swg-netctl-docker: …not another IP, and DNS as before", not NCD._cert_covers_host(IPC, "203.0.113.8")
      and NCD._cert_covers_host(WILD, "sub.example.com") and not NCD._cert_covers_host(DNSC, IP))

print("[2] the start sequence: the panel's install, then the background sub step on the same IP")
w, env = world("w2")
r = run(env, 'SUB_DOMAIN=%s; acme_install; issue_sub_cert' % IP)
check("[2] the entry still installs to the panel's certificate", conf_val(w, IP, "Le_RealFullChainPath") == env["SWG_PANEL_TLS_CERT"]
      and conf_val(w, IP, "Le_ReloadCmd") == "kill -HUP 1", (conf_val(w, IP, "Le_RealFullChainPath"), r.stdout[-300:]))
check("[2] …and the sub serves the panel's certificate", same(env["SUB_TLS_DIR"] + "/fullchain.pem", env["SWG_PANEL_TLS_CERT"]))
w, env = world("w2b")
open(CALLS, "w").close()
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
_inst = [c for c in calls() if "--install-cert" in c]
check("[2] the panel's file not there yet: the sub still never installs onto the panel's entry", not _inst
      and same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC), (_inst, r.stdout[-300:]))

w, env = world("w2c", tls="selfsigned", dom="panel.example.com")
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert; cp "$SC" "$SC.first"; issue_sub_cert' % IP)
_t = sh("openssl", "x509", "-in", env["SUB_TLS_DIR"] + "/fullchain.pem", "-noout", "-text").stdout
check("[2] a self-signed sub on an IP writes an IP SAN, and is reused on the next start", ("IP Address:" + IP) in _t
      and same(env["SUB_TLS_DIR"] + "/fullchain.pem", env["SUB_TLS_DIR"] + "/fullchain.pem.first"), (r.stdout[-300:], _t[-300:]))
# the update from 1.8.10 (nightly docker-pristine, 10-25..10-28): a selfsigned IP panel, its own self-signed IP certificate,
# and the sub's self-signed pair an earlier image wrote (a DNS SAN spelling the IP) — the sub keeps its pair
def panel_selfsigned(env):
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-keyout", env["SWG_PANEL_TLS_KEY"],
       "-out", env["SWG_PANEL_TLS_CERT"], "-subj", "/CN=" + IP, "-addext", "subjectAltName=IP:" + IP)
w, env = world("w2d", tls="selfsigned")
panel_selfsigned(env)
sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-keyout", env["SUB_TLS_DIR"] + "/key.pem",
   "-out", env["SUB_TLS_DIR"] + "/fullchain.pem", "-subj", "/CN=" + IP, "-addext", "subjectAltName=DNS:" + IP)
_old = (open(env["SUB_TLS_DIR"] + "/fullchain.pem", "rb").read(), open(env["SUB_TLS_DIR"] + "/key.pem", "rb").read())
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
check("[2] a self-signed panel certificate never replaces the sub's own self-signed pair",
      _old == (open(env["SUB_TLS_DIR"] + "/fullchain.pem", "rb").read(), open(env["SUB_TLS_DIR"] + "/key.pem", "rb").read()), r.stdout[-300:])
# …a torn sub pair (a start killed between the copy's two `cp`s: the panel's certificate beside the sub's old key), or one
# with no key, is never kept: the panel's covering pair is copied again (review F1)
_torn, _out = [], []
for _case in ("torn", "nokey"):
    w, env = world("w2g-" + _case, tls="selfsigned")
    panel_selfsigned(env)
    shutil.copyfile(env["SWG_PANEL_TLS_CERT"], env["SUB_TLS_DIR"] + "/fullchain.pem")
    if _case == "torn":
        shutil.copyfile(IPK, env["SUB_TLS_DIR"] + "/key.pem")
    r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
    _sk = env["SUB_TLS_DIR"] + "/key.pem"
    _torn.append(os.path.exists(_sk) and same(_sk, env["SWG_PANEL_TLS_KEY"]))
    _out.append(_case + ": " + r.stdout[-200:])
check("[2] …a torn sub pair, or one with no key, is written again, not kept", all(_torn), (_torn, _out))
# …a real panel certificate still replaces an older copy of it (a renewal reaches the sub)
w, env = world("w2e")
shutil.copyfile(IPC2, env["SWG_PANEL_TLS_CERT"]); shutil.copyfile(IPK, env["SWG_PANEL_TLS_KEY"])
shutil.copyfile(IPC, env["SUB_TLS_DIR"] + "/fullchain.pem"); shutil.copyfile(IPK, env["SUB_TLS_DIR"] + "/key.pem")
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
check("[2] …a real panel certificate still replaces an older copy", same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC2), r.stdout[-300:])
# …in a CA mode the panel fell back to a self-signed placeholder: the sub keeps its real certificate
w, env = world("w2f")
panel_selfsigned(env)
shutil.copyfile(IPC, env["SUB_TLS_DIR"] + "/fullchain.pem"); shutil.copyfile(IPK, env["SUB_TLS_DIR"] + "/key.pem")
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
check("[2] …a CA mode: a self-signed panel placeholder never replaces the sub's real certificate",
      same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC) and same(env["SUB_TLS_DIR"] + "/key.pem", IPK), r.stdout[-300:])
# …but in selfsigned mode a CA-issued copy left from Let's Encrypt is never kept (nothing renews it there): the panel's
# self-signed certificate on the same IP replaces it
w, env = world("w2h", tls="selfsigned")
panel_selfsigned(env)
shutil.copyfile(IPC, env["SUB_TLS_DIR"] + "/fullchain.pem"); shutil.copyfile(IPK, env["SUB_TLS_DIR"] + "/key.pem")
r = run(env, 'SUB_DOMAIN=%s; issue_sub_cert' % IP)
check("[2] …selfsigned: a CA-issued sub copy is replaced by the panel's covering certificate",
      same(env["SUB_TLS_DIR"] + "/fullchain.pem", env["SWG_PANEL_TLS_CERT"]) and same(env["SUB_TLS_DIR"] + "/key.pem", env["SWG_PANEL_TLS_KEY"]),
      r.stdout[-300:])

print("[3] a start repairs an entry that installs elsewhere")
w, env = world("w3")
run(env, "acme_install")
with open(w + "/acme/%s_ecc/%s.conf" % (IP, IP), "w") as f:      # what the hijack left (the user's box, 10-23)
    f.write("Le_Domain='%s'\nLe_RealFullChainPath='%s/fullchain.pem'\nLe_RealKeyPath='%s/key.pem'\nLe_ReloadCmd='true'\n"
            % (IP, env["SUB_TLS_DIR"], env["SUB_TLS_DIR"]))
r = run(env, "acme_reassert")
check("[3] a hijacked entry is re-pointed at the panel's certificate", conf_val(w, IP, "Le_RealFullChainPath") == env["SWG_PANEL_TLS_CERT"]
      and conf_val(w, IP, "Le_ReloadCmd") == "kill -HUP 1", (conf_val(w, IP, "Le_RealFullChainPath"), r.stdout[-300:]))
_reuse = cut(EP, "elif reuse_present_cert; then", "\nelif ")
check("[3] …on a start that reuses the certificate on disk", "acme_reassert" in _reuse, _reuse)
w, env = world("w3b", tls="selfsigned")
run(env, "acme_install")
with open(w + "/acme/%s_ecc/%s.conf" % (IP, IP), "w") as f:
    f.write("Le_Domain='%s'\nLe_RealFullChainPath='/elsewhere'\n" % IP)
open(CALLS, "w").close()
run(env, "acme_reassert")
check("[3] …only in an acme mode (selfsigned: nothing is re-pointed)", not [c for c in calls() if "--install-cert" in c], calls())

w, env = world("w3c")
run(env, "acme_install")
_mc, _mk = leaf("mounted", "IP:" + IP, 90)                      # the operator's own pair, mounted over the managed path
shutil.copyfile(_mc, env["SWG_PANEL_TLS_CERT"]); shutil.copyfile(_mk, env["SWG_PANEL_TLS_KEY"])
with open(w + "/acme/%s_ecc/%s.conf" % (IP, IP), "w") as f:       # …and the entry installing elsewhere
    f.write("Le_Domain='%s'\nLe_RealFullChainPath='/elsewhere'\n" % IP)
open(CALLS, "w").close()
run(env, "acme_reassert")
check("[3] …a certificate the operator mounted over the entry stays theirs", same(env["SWG_PANEL_TLS_CERT"], _mc)
      and not [c for c in calls() if "--install-cert" in c], calls())
w, env = world("w3d")
shutil.move(w + "/acme/%s_ecc" % IP, w + "/acme/%s" % IP)          # an RSA-era entry: no _ecc dir
shutil.copyfile(IPC, env["SWG_PANEL_TLS_CERT"]); shutil.copyfile(IPK, env["SWG_PANEL_TLS_KEY"])
open(CALLS, "w").close()
r = run(env, "acme_reassert")
check("[3] …an RSA entry from an older store is not re-pointed with --ecc", not [c for c in calls() if "--install-cert" in c], (calls(), r.stdout))

print("[4] the sub's copy follows the panel's renewals")
w, env = world("w4")
run(env, 'SUB_DOMAIN=%s; acme_install; issue_sub_cert' % IP)
shutil.copyfile(IPC2, env["SWG_PANEL_TLS_CERT"])                  # acme's renewal reached the panel's file
r = run(env, "SUB_DOMAIN=%s; sub_follow_panel" % IP)
check("[4] a renewed panel certificate reaches the sub's copy", same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC2), r.stdout[-300:])
_loop = cut(EP, "( while :; do", "done ) &")
check("[4] …after every --cron of the renewal loop", "sub_follow_panel" in _loop.split("acme --cron", 1)[-1].split("renew_why", 1)[0], _loop[:300])
w, env = world("w4b")
run(env, "acme_install")
os.makedirs(env["SUB_TLS_DIR"], exist_ok=True)
_own, _ownk = leaf("sub-own", "DNS:sub.other.example", 90)
shutil.copyfile(_own, env["SUB_TLS_DIR"] + "/fullchain.pem"); shutil.copyfile(_ownk, env["SUB_TLS_DIR"] + "/key.pem")
run(env, "SUB_DOMAIN=sub.other.example; sub_follow_panel")
check("[4] …a sub with its own certificate for a host the panel's does not cover is left alone",
      same(env["SUB_TLS_DIR"] + "/fullchain.pem", _own))
w, env = world("w4c")
run(env, 'SUB_DOMAIN=%s; acme_install; issue_sub_cert' % IP)
_ss = os.path.join(TMP, "selfsigned.pem")
sh("openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "3650",
   "-keyout", os.path.join(TMP, "selfsigned.key"), "-out", _ss, "-subj", "/CN=" + IP, "-addext", "subjectAltName=IP:" + IP)
shutil.copyfile(_ss, env["SWG_PANEL_TLS_CERT"])                  # the panel fell back to self-signed (a failed issuance)
run(env, "SUB_DOMAIN=%s; sub_follow_panel" % IP)
check("[4] …a self-signed panel placeholder never replaces the sub's certificate", same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC))
w, env = world("w4d", tls="cloudflare", dom="panel.example.com")
_wc, _wk = leaf("wild-panel", "DNS:*.example.com", 90)
shutil.copyfile(_wc, env["SWG_PANEL_TLS_CERT"]); shutil.copyfile(_wk, env["SWG_PANEL_TLS_KEY"])
_sc, _sk = leaf("sub-entry", "DNS:sub.example.com", 90)
shutil.copyfile(_sc, env["SUB_TLS_DIR"] + "/fullchain.pem"); shutil.copyfile(_sk, env["SUB_TLS_DIR"] + "/key.pem")
os.makedirs(w + "/acme/sub.example.com_ecc")
with open(w + "/acme/sub.example.com_ecc/sub.example.com.conf", "w") as f:
    f.write("Le_Domain='sub.example.com'\nLe_RealFullChainPath='%s/fullchain.pem'\n" % env["SUB_TLS_DIR"])
run(env, "SUB_DOMAIN=sub.example.com; sub_follow_panel")
check("[4] …a sub with its own acme entry installing to its files is left to that entry", same(env["SUB_TLS_DIR"] + "/fullchain.pem", _sc))
with open(w + "/acme/sub.example.com_ecc/sub.example.com.conf", "w") as f:      # issued from SUB_DOMAIN=Sub.Example.com
    f.write("Le_Domain='Sub.Example.com'\nLe_RealFullChainPath='%s/fullchain.pem'\n" % env["SUB_TLS_DIR"])
run(env, "SUB_DOMAIN=sub.example.com; sub_follow_panel")
check("[4] …the sub's own entry in another letter case is still its renewer (review F3)", same(env["SUB_TLS_DIR"] + "/fullchain.pem", _sc))
w, env = world("w4e")
run(env, 'SUB_DOMAIN=%s; acme_install; issue_sub_cert' % IP)
os.makedirs(w + "/acme/old.example.com_ecc")                     # the renewer of a sub domain the panel had before
with open(w + "/acme/old.example.com_ecc/old.example.com.conf", "w") as f:
    f.write("Le_Domain='old.example.com'\nLe_RealFullChainPath='%s/fullchain.pem'\n" % env["SUB_TLS_DIR"])
shutil.copyfile(IPC2, env["SWG_PANEL_TLS_CERT"])
r = run(env, "SUB_DOMAIN=%s; sub_follow_panel" % IP)
check("[4] …a stale entry for a host the sub had before does not stop the copy", same(env["SUB_TLS_DIR"] + "/fullchain.pem", IPC2),
      r.stdout[-300:])

print("[5] swg-sub picks up a changed certificate on its own")
def free_port():
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); return s_.getsockname()[1]
def served(port):
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as s_, c.wrap_socket(s_) as t:
            return t.getpeercert(binary_form=True)
    return None
def der(p):
    return ssl.PEM_cert_to_DER_cert(open(p).read().split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n")
sd = os.path.join(TMP, "sub5")
os.makedirs(sd + "/subs")
shutil.copyfile(IPC, sd + "/fullchain.pem"); shutil.copyfile(IPK, sd + "/key.pem")
with open(sd + "/fleet.json", "w") as f:
    json.dump({"stats_dir": sd, "roster_path": sd + "/users.json"}, f)
with open(sd + "/subs/serve.json", "w") as f:              # the panel writes it at the end of its start; swg-sub waits for it
    json.dump({"serve": {"tls_mode": "letsencrypt-ip"}}, f)
port = free_port()
proc = subprocess.Popen([sys.executable, PATHS["SUB"]], env=dict(os.environ, SWG_SUB_FLEET=sd + "/fleet.json", SWG_SUB_HOST="127.0.0.1",
                        SWG_SUB_PORT=str(port), SWG_SUB_TLS_CERT=sd + "/fullchain.pem", SWG_SUB_TLS_KEY=sd + "/key.pem",
                        SWG_SUB_CERT_WATCH_S="1", SWG_NO_REEXEC="1"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    first = None
    for _ in range(50):
        first = served(port)
        if first:
            break
        time.sleep(0.2)
    check("[5] swg-sub serves its certificate (baseline)", first == der(IPC))
    shutil.copyfile(IPC2, sd + "/fullchain.pem.new"); os.replace(sd + "/fullchain.pem.new", sd + "/fullchain.pem")
    now_ = None
    for _ in range(25):
        time.sleep(0.4)
        now_ = served(port)
        if now_ == der(IPC2):
            break
    check("[5] swg-sub serves a certificate whose files changed, with no signal", now_ == der(IPC2))
finally:
    proc.terminate()
    with contextlib.suppress(Exception):
        proc.wait(5)

print("[6] the loop's verdict: a short-lived certificate by its life, a long one by days; who holds :80")
w, env = world("w6")
shutil.copyfile(IPC, env["SWG_PANEL_TLS_CERT"])
def nb_na(p):
    i = ssl._ssl._test_decode_cert(p)
    return ssl.cert_time_to_seconds(i["notBefore"]), ssl.cert_time_to_seconds(i["notAfter"])
_nb, _na = nb_na(IPC)
def why_at(left_s, cert=None, out="", tls=None, e=None):
    e2 = dict(e or env, FAKE_NOW=str(int(_na2 - left_s)) if cert else str(int(_na - left_s)))
    if tls:
        e2["TLS"] = tls
    if cert:
        shutil.copyfile(cert, e2["SWG_PANEL_TLS_CERT"])
    return run(e2, 'renew_why "%s"' % out).stdout.strip()
_na2 = nb_na(LONG)[1]
D = 86400
check("[6] a 7-day certificate with 5 days left is not failing", why_at(5 * D) == "", why_at(5 * D))
check("[6] …nor with 2.5 days left (inside its last third only below 2.33)", why_at(2.5 * D) == "", why_at(2.5 * D))
_w = why_at(2 * D)
check("[6] …with 2 days left it is, said in hours of its 7-day life", "48 hour(s) left of its 7-day life" in _w, _w)
shutil.copyfile(IPC, env["SWG_PANEL_TLS_CERT"])
check("[6] a 90-day certificate with 30 days left is not failing", why_at(30 * D, cert=LONG) == "", why_at(30 * D, cert=LONG))
check("[6] …with 19 days left it is", "19 day(s) left" in why_at(19 * D, cert=LONG), why_at(19 * D, cert=LONG))
shutil.copyfile(IPC, env["SWG_PANEL_TLS_CERT"])
_e = why_at(5 * D, out="[x] error: renew failed for %s: timeout" % IP)
check("[6] an error naming our domain is failing, whatever the date", "renew failed for %s" % IP in _e, _e)
with open(w + "/acme/.port80-held", "w") as f:
    f.write("nginx\n")
_h = why_at(2 * D)
check("[6] a failing renewal names who holds port 80 (letsencrypt-ip: no DNS-01 offer)", "port 80 held by nginx" in _h
      and "if that is still so" in _h
      and "Cloudflare" not in _h, _h)
_h2 = why_at(2 * D, tls="letsencrypt")
check("[6] …a domain certificate is offered Cloudflare DNS-01", "held by nginx" in _h2 and "Cloudflare DNS-01" in _h2, _h2)
check("[6] …a renewal that is fine says nothing about :80", why_at(5 * D) == "")

print("[7] a bare→Docker convert retires the host's copies of OUR entries only")
hh = os.path.join(TMP, "hosthome/.acme.sh")
vol = os.path.join(TMP, "vol-acme")
for name, target, carried in ((IP, "/etc/swg-panel/tls/fullchain.pem", True), ("sub.example.com", "/etc/swg-sub/tls/fullchain.pem", True),
                              ("mine.example.org", "/root/cert/mine.pem", True), ("old.example.net", "/etc/swg-panel/tls/fullchain.pem", False)):
    os.makedirs(hh + "/%s_ecc" % name)
    with open(hh + "/%s_ecc/%s.conf" % (name, name), "w") as f:
        f.write("Le_Domain='%s'\nLe_RealFullChainPath='%s'\n" % (name, target))
    if carried:
        os.makedirs(vol + "/%s_ecc" % name)
shutil.copyfile(FAKE, hh + "/acme.sh"); os.chmod(hh + "/acme.sh", 0o755)
CM = open(PATHS["COMMON"], encoding="utf-8").read()
_fn = cut(CM, "retire_carried_acme(){", "\n  done; }\n") + "\n  done; }\n"
open(CALLS, "w").close()
r = subprocess.run(["bash", "-c", _fn + '\nretire_carried_acme "%s" "%s"' % (vol, hh)], env=dict(os.environ, FAKE_ACME_CALLS=CALLS),
                   capture_output=True, text=True, timeout=60)
hh2 = os.path.join(TMP, "hosthome2/.acme.sh")              # the store convert.sh copied, with no acme.sh left in it
os.makedirs(hh2 + "/%s_ecc" % IP)
with open(hh2 + "/%s_ecc/%s.conf" % (IP, IP), "w") as f:
    f.write("Le_Domain='%s'\nLe_RealFullChainPath='/etc/swg-panel/tls/fullchain.pem'\n" % IP)
hh3 = os.path.join(TMP, "hosthome3/.acme.sh")              # a later home WITH an acme.sh: not the one convert.sh copied
os.makedirs(hh3 + "/%s_ecc" % IP)
with open(hh3 + "/%s_ecc/%s.conf" % (IP, IP), "w") as f:
    f.write("Le_Domain='%s'\nLe_RealFullChainPath='/etc/swg-panel/tls/fullchain.pem'\n" % IP)
shutil.copyfile(FAKE, hh3 + "/acme.sh"); os.chmod(hh3 + "/acme.sh", 0o755)
subprocess.run(["bash", "-c", _fn + '\nretire_carried_acme "%s" "%s" "%s"' % (vol, hh2, hh3)], env=dict(os.environ, FAKE_ACME_CALLS=CALLS),
               capture_output=True, text=True, timeout=60)
check("[7] the store convert.sh copied is the one retired, with or without an acme.sh in it",
      not os.path.exists(hh2 + "/%s_ecc" % IP) and os.path.isdir(hh3 + "/%s_ecc" % IP))
check("[7] the panel's and the sub's entries leave the host store", not os.path.exists(hh + "/%s_ecc" % IP)
      and not os.path.exists(hh + "/sub.example.com_ecc") and ["--home", hh, "--remove", "-d", IP, "--ecc"] in calls(), (r.stdout, calls()))
check("[7] the user's own entry in the host store stays", os.path.isdir(hh + "/mine.example.org_ecc"))
check("[7] an entry of ours with no copy in the container stays", os.path.isdir(hh + "/old.example.net_ecc"))
check("[7] …and acme.sh itself stays", os.path.exists(hh + "/acme.sh"))
ID = open(PATHS["IDOCKER"], encoding="utf-8").read()
_sw = cut(ID, 'info "Switching over — stopping the bare-metal services', "lc_teardown_baremetal")
check("[7] the convert's switch retires the host's copies (after the bare panel is torn down)",
      "retire_carried_acme" in _sw and _sw.index("teardown_bare_panel") < _sw.index("retire_carried_acme"), _sw[:300])

print("[8] the installer and :80")
_held = cut(ID, 'warn "host port 80 is already in use', "elif $DRYRUN; then")
_pub = cut(ID, 'cat > "$OVERRIDE" <<\'YAML\'', 'elif [ -f "$OVERRIDE" ]; then')
check("[8] the installer leaves who holds :80 for the renewal loop", '> "$P80HELD"' in _held, _held[-300:])
check("[8] …and takes it back when it publishes :80", 'rm -f "$P80HELD"' in _pub, _pub[-200:])
_hc = cut(ID, "_own80=0", 'warn "host port 80 is already in use')
check("[8] a re-install does not read the panel's own docker-proxy on :80 as taken", "name=^swg-panel$" in _hc
      and "':80->80/tcp'" in _hc and '[ "${_own80:-0}" = 0 ]' in _hc, _hc[:400])
check("[8] the marker sits where the loop reads it (the container's acme dir)", 'P80HELD="$PREFIX$INSTALL_DIR/data/etc/acme/.port80-held"' in ID
      and '"$ACME_CFG/.port80-held"' in EP)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if not FAILS else "\n%d FAILED: %s" % (len(FAILS), "; ".join(FAILS)))
sys.exit(1 if FAILS else 0)
