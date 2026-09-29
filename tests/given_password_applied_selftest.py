#!/usr/bin/env python3
"""Self-test — A PASSWORD GIVEN TO A RE-INSTALL IS SET, AND IT NEVER STAYS IN A CONTAINER'S ENVIRONMENT (F91, F94).

F91: a Docker re-install with -pass that reused its certificate — the unattended default — kept the old login (NEW_LOGIN
was set only when the login file was gone), said nothing, and left the new password in .env in plain text; the installer's
own lines promise "-pass to set a new one". The bare re-install ignored a given BASIC_PASS (or -pass) the same way.
F94: an update (and install-docker.sh after a new login) took the password out of .env only after `compose up`, so the
container kept it — `docker inspect`, config.v2.json — until the next compose up.

  [1] install-docker.sh, driven (the kept-login decisions and the login/certificate block, lifted as shipped): a given
      password the kept login does not hold replaces it whatever the TLS step did — reuse keeps the certificate, a new
      TLS choice re-issues it as before — and an Encryption Vault gets the reconnect marker; a given password it holds,
      or none given, keeps the login untouched
  [2] install-docker.sh: the password leaves .env BEFORE `compose up` when the login already holds it, and after a new
      login (which cannot hold it before) the panel's container is re-created once it has left
  [3] update.sh: the password leaves .env BEFORE the containers are recreated — before every `up` of the image branch —
      and the "nothing recreated" line says so when the panel's container was re-created for it
  [4] install-host.sh, driven: a re-install with BASIC_PASS (or -pass) the kept login does not hold mints the new login
      under the kept user name; one it holds, or none, keeps it; the summary names a given password without printing it
  [5] --dry-run is honoured wherever it stands (install-host.sh, install-node.sh), and -pass / -user reach the bare login
  [6] login_holds (lib/common.sh): the user AND the pbkdf2 hash, nothing else

Run: python3 tests/given_password_applied_selftest.py        (0 = pass)
     --perturb   seven plants, each on its own — each must turn its own check red
"""
import base64, hashlib, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {k: os.environ.get("SWG_GP_" + k) or os.path.join(ROOT, f) for k, f in
         (("COMMON", "lib/common.sh"), ("DOCKER", "install-docker.sh"), ("UPDATE", "update.sh"), ("HOST", "install-host.sh"),
          ("NODE", "install-node.sh"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("reuse", "DOCKER", '    if [ "$SET_GIVEN_PW" = yes ] && ! $DRYRUN; then rm -f "$PREFIX$INSTALL_DIR/data/etc/auth"; _vault_reset_marker; NEW_LOGIN=yes; fi\n',
     "", "[1] reuse: a given password the kept login does not hold replaces it — the certificate stays"),
    ("vault", "DOCKER", '  printf \'reset\\n\' > "$s/vault.reset" 2>/dev/null && chmod 640 "$s/vault.reset" 2>/dev/null || true\n',
     "  true\n", "[1] …and an Encryption Vault gets the reconnect marker"),
    ("preup", "DOCKER", 'if [ "$PROFILE" != node ] && ! $DRYRUN && [ "${NEW_LOGIN:-no}" != yes ]; then docker_env_forget_password "$INSTALL_DIR" 0; fi\n', "",
     "[2] install-docker.sh: the password leaves .env before `compose up` when the login already holds it"),
    ("update", "UPDATE", '      docker_env_forget_password "$DOCKER_DIR" 0\n', '      :\n',
     "[3] update.sh: the password leaves .env before the containers are recreated"),
    ("bare", "HOST", 'if [ "$KEEP_AUTH" = yes ] && [ "${SET_PASS:-no}" != yes ]; then ok "keeping existing login',
     'if [ "$KEEP_AUTH" = yes ]; then ok "keeping existing login', "[4] a given password the kept login does not hold → a new login"),
    ("dryrun", "NODE", 'DRYRUN=false; for _a in "$@"; do case "$_a" in --dry-run) DRYRUN=true;; esac; done\n',
     'DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true\n', "[5] install-node.sh: --dry-run after another flag is a dry run"),
    ("user", "COMMON", '    ok = u == os.environ["SWG_LU"] and scheme == "pbkdf2_sha256" and hmac.compare_digest(',
     '    ok = scheme == "pbkdf2_sha256" and hmac.compare_digest(', "[6] login_holds: the right password under another user → no"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_GP_" + key: f.name}),
                           capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-8s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

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

def span(src, start, end, incl_end_line=True):
    """src from `start` to the end of the line that `end` ends on (or up to `end`, without it)"""
    i = src.index(start); j = src.index(end, i)
    if not incl_end_line:
        return src[i:j]
    k = j + len(end)
    return src[i:k] if src[k - 1] == "\n" else src[i:src.index("\n", k) + 1]

def pbkdf2_line(user, pw):
    salt = os.urandom(16); it = 1000
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
    return "%s:pbkdf2_sha256$%d$%s$%s\n" % (user, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode())

def bash(script, env=None):
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})), timeout=120)
    return r.returncode, r.stdout + r.stderr

C, D, UP, H = SRC["COMMON"], SRC["DOCKER"], SRC["UPDATE"], SRC["HOST"]
HELP = ('info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; b(){ printf %s "$*"; }\n'
        'have(){ command -v "$1" >/dev/null 2>&1; }\n')

print("[1] install-docker.sh: the kept login and a given password")
DECIDE = span(D, "KEPT_LOGIN=no\n", "  warn \"an Encryption Vault is kept here, wrapped under the OLD panel password.")
RESET = span(D, "NEW_LOGIN=no\n", "# always recreate (incl. node)", incl_end_line=False)
PH = fn(C, "docker_pw_placeholder") + "DOCKER_PW_PLACEHOLDERS=\"(preserved) converted-login-preserved unused-on-node-only\"\n"
def docker_run(given, env_pw, reuse, vault=True, user="admin46"):
    d = tempfile.mkdtemp(prefix="gp-dk-")
    os.makedirs(os.path.join(d, "data/etc/tls")); os.makedirs(os.path.join(d, "data/lib/subs"))
    open(os.path.join(d, "data/etc/auth"), "w").write(pbkdf2_line("admin46", "old-pass-1"))
    for f in ("fullchain.pem", "key.pem"):
        open(os.path.join(d, "data/etc/tls", f), "w").write("CERT")
    if vault:
        open(os.path.join(d, "data/lib/subs/vault.json"), "w").write('{"wrapped": "x"}')
    script = (HELP + PH + 'PREFIX=""; DRYRUN=false; PROFILE=host; EXISTING_DOCKER=yes; KEEP_AUTH=no; KEEP_CERT=no\n'
              'INSTALL_DIR=%s; PANEL_USER=%s; _GIVEN_PANEL_PASSWORD="%s"; PANEL_PASSWORD="%s"; REUSE_TLS=%s\n%s%s'
              'echo "KEEP_AUTH=$KEEP_AUTH SET_GIVEN_PW=$SET_GIVEN_PW NEW_LOGIN=$NEW_LOGIN"\n'
              % (d, user, given, given or env_pw, reuse, DECIDE, RESET))
    rc, out = bash(script)
    st = lambda rel: os.path.exists(os.path.join(d, rel))
    return rc, out, st("data/etc/auth"), st("data/etc/tls/key.pem") and st("data/etc/tls/fullchain.pem"), st("data/lib/subs/vault.reset")
rc, out, auth, cert, marker = docker_run("new-pass-2", "", "yes")
check("[1] reuse: a given password the kept login does not hold replaces it — the certificate stays",
      rc == 0 and not auth and cert and "NEW_LOGIN=yes" in out and "Setting a new panel login" in out, (rc, out))
check("[1] …and an Encryption Vault gets the reconnect marker", marker, out)
rc, out, auth, cert, marker = docker_run("new-pass-2", "", "no")
check("[1] a new TLS choice: the given password replaces the login and the certificate is re-issued, as before",
      rc == 0 and not auth and not cert and "NEW_LOGIN=yes" in out and marker, (rc, out))
rc, out, auth, cert, marker = docker_run("old-pass-1", "", "yes")
check("[1] a given password the kept login already holds: nothing changes, nothing is re-set",
      rc == 0 and auth and cert and "NEW_LOGIN=no" in out and not marker and "Setting a new" not in out, (rc, out))
rc, out, auth, cert, marker = docker_run("", "(preserved)", "yes")
check("[1] none given (.env holds the placeholder): the login is kept", rc == 0 and auth and cert and "NEW_LOGIN=no" in out
      and "KEEP_AUTH=yes" in out, (rc, out))
rc, out, auth, cert, marker = docker_run("new-pass-2", "", "yes", vault=False)
check("[1] no vault: no marker", rc == 0 and not auth and not marker, (rc, out))

print("\n[2] install-docker.sh: the password and the container")
i_pre = D.find('if [ "$PROFILE" != node ] && ! $DRYRUN && [ "${NEW_LOGIN:-no}" != yes ]; then docker_env_forget_password "$INSTALL_DIR" 0; fi\n')
i_up = D.find('( cd "$INSTALL_DIR" && on_tty $COMPOSE --profile "$PROFILE" up -d $RECREATE $BUILDFLAG ); fi')
check("[2] install-docker.sh: the password leaves .env before `compose up` when the login already holds it",
      0 < i_pre < i_up, (i_pre, i_up))
post = span(D, 'if [ "${NEW_LOGIN:-no}" = yes ] && ! $DRYRUN; then\n  _pw_was=', '\nfi\n')
check("[2] …a new login: after the forget, the panel's container is re-created when the password left .env",
      i_up < D.find(post) and 'docker_env_forget_password "$INSTALL_DIR" 90' in post
      and re.search(r'!= "\$_pw_was" \]; then\n\s*if \( cd "\$INSTALL_DIR" && \$COMPOSE --profile "\$PROFILE" up -d swg-panel', post) is not None, post)

print("\n[3] update.sh: the password leaves .env first")
i_fg = UP.find('      docker_env_forget_password "$DOCKER_DIR" 0\n')
i_first_up = min(i for i in (UP.find('on_tty $COMPOSE --profile "$prof" up -d )'), UP.find('on_tty $COMPOSE --profile "$prof" up -d --force-recreate )'),
                             UP.find('on_tty $COMPOSE --profile "$prof" up -d --build )')) if i > 0)
check("[3] update.sh: the password leaves .env before the containers are recreated", 0 < i_fg < i_first_up, (i_fg, i_first_up))
seg = UP[UP.rfind('case "$prof" in host|master|host-node)', 0, i_fg):i_fg]
check("[3] …for the panel's profiles, and never on a dry run", 'case "$prof" in host|master|host-node)' in seg and "if ! $DRYRUN; then" in seg, seg[-300:])
# (round 12, on q6: it said "re-created" while the container already held the placeholder and nothing was)
check("[3] …and the unchanged-image line says when the panel's container was re-created for it — and only then",
      "only the panel's container re-created, without the password" in UP and '[ "${ENV_PW_LEFT:-no}" = yes ] && [ "$_pc0" != "$_pc1" ]' in UP
      and "nothing recreated (the panel's container did not hold the password)" in UP)

print("\n[4] install-host.sh: a re-install given a password")
SETP = span(H, "SET_PASS=no\n", "  else info \"Setting a new panel login ($(b \"$BASIC_USER\")) — the password given is not the one it has; it replaces it.\"; fi\nfi")
_k = H.index('ok "keeping existing login ($BASIC_USER)"')
LOGIN = span(H, H[H.rindex("\n", 0, _k) + 1:_k], "else mk_auth_file; fi")   # the login step's own line, whatever its test
SUMM = span(H, 'if [ "$KEEP_AUTH" != yes ] || [ "${SET_PASS:-no}" = yes ]; then\n', "\nfi\n")
def bare_run(given, pw, user="admin45"):
    d = tempfile.mkdtemp(prefix="gp-bare-"); auth = os.path.join(d, "auth")
    open(auth, "w").write(pbkdf2_line("admin45", "old-pass-1"))
    script = (HELP + fn(C, "login_holds") + 'DRYRUN=false; KEEP_AUTH=yes; ETC_DIR=%s; BASIC_USER=%s; BASIC_PASS="%s"; _PASS_GIVEN=%s\n'
              'run(){ "$@"; }; chown(){ :; }; mk_auth_file(){ echo "MINTED $BASIC_USER"; }\n%s%s%s'
              'echo "SET_PASS=$SET_PASS GIVEN_FLAG=${SWG_SUMMARY_PASS_GIVEN:-} PRINTED=${SWG_SUMMARY_PASS:-}"\n'
              % (d, user, pw, given, SETP, LOGIN, SUMM))
    return bash(script)
rc, out = bare_run("yes", "new-pass-2")
check("[4] a given password the kept login does not hold → a new login, under the kept user name",
      rc == 0 and "MINTED admin45" in out and "SET_PASS=yes" in out, (rc, out))
check("[4] …and the summary says it was given, never prints it", out.rstrip().endswith("SET_PASS=yes GIVEN_FLAG=1 PRINTED="), out)
rc, out = bare_run("yes", "old-pass-1")
check("[4] a given password the kept login already holds: kept, nothing minted", rc == 0 and "keeping existing login" in out
      and "MINTED" not in out and "SET_PASS=no" in out, (rc, out))
rc, out = bare_run("no", "")
check("[4] none given: kept, as before", rc == 0 and "keeping existing login" in out and "MINTED" not in out, (rc, out))

print("\n[5] --dry-run wherever it stands, and -pass / -user on bare metal")
hp = span(H, 'DRYRUN=false; _prev=""\n', "\ndone\n")
rc, out = bash('BASIC_PASS=""; BASIC_USER=admin; _PASS_GIVEN=no\nset -- --yes -pass "p w" -user ops --dry-run\n%s'
               'echo "DRYRUN=$DRYRUN PASS=[$BASIC_PASS] USER=$BASIC_USER GIVEN=$_PASS_GIVEN"\n' % hp)
check("[5] install-host.sh: --dry-run after other flags is a dry run", rc == 0 and "DRYRUN=true" in out, (rc, out))
check("[5] install-host.sh: -pass / -user set the login it mints (BASIC_PASS / BASIC_USER)",
      "PASS=[p w] USER=ops GIVEN=yes" in out, out)
np_ = [l for l in SRC["NODE"].splitlines() if l.startswith("DRYRUN=false")]
rc, out = bash('set -- --yes --dry-run\n%s\necho "DRYRUN=$DRYRUN"\n' % (np_[0] if np_ else "false"))
check("[5] install-node.sh: --dry-run after another flag is a dry run", rc == 0 and "DRYRUN=true" in out, (rc, out, np_))

print("\n[6] login_holds")
LH = fn(C, "login_holds")
d6 = tempfile.mkdtemp(prefix="gp-lh-"); a6 = os.path.join(d6, "auth"); open(a6, "w").write(pbkdf2_line("admin45", "s3cret"))
def lh(user, pw, path=a6):
    return bash(HELP + LH + 'login_holds "%s" "%s" "%s" && echo YES || echo NO\n' % (path, user, pw))[1].strip()
check("[6] login_holds: the user and the password → yes", lh("admin45", "s3cret") == "YES")
check("[6] login_holds: another password → no", lh("admin45", "wrong") == "NO")
check("[6] login_holds: the right password under another user → no", lh("root", "s3cret") == "NO")
open(os.path.join(d6, "plain"), "w").write("admin45:s3cret\n")
check("[6] login_holds: not a pbkdf2 hash, an empty or a missing file → no",
      lh("admin45", "s3cret", os.path.join(d6, "plain")) == "NO" and lh("admin45", "s3cret", os.path.join(d6, "missing")) == "NO")

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
