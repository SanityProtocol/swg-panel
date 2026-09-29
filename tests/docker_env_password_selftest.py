#!/usr/bin/env python3
"""Self-test — A DOCKER PANEL'S PASSWORD LEAVES .env ONCE THE PANEL HOLDS IT, AND A PLACEHOLDER NEVER BECOMES A LOGIN.

A fresh Docker install left the panel password in /opt/swg-panel-docker/.env in plain text (0600, root) until the next
re-install replaced it with the placeholder "(preserved)" (1.8.8 qualification, round 9b). Once the login in data/etc/auth
verifies against it, it goes. That is only safe if a placeholder can never be taken for a password — so the entrypoint
refuses to mint a login from one, and a re-install with no login to keep generates a new password instead.

  [1] docker_env_forget_password: the login verifies against .env's value (plain, "quoted", 'quoted') → the line is
      "PANEL_PASSWORD=(preserved)", mode 0600, every other line byte for byte; one line says so; the password is never printed
  [2] the login does not hold it (yet) → .env untouched, one line says it stays
  [3] a placeholder or an empty value → nothing at all
  [4] install-docker.sh forgets it after compose up, only for a login this run applied (NEW_LOGIN), before the summary
  [5] install-docker.sh: a placeholder with no login kept → a NEW password (never the placeholder)
  [6] update.sh forgets it for a running Docker panel (a box installed before)
  [7] docker/entrypoint.sh: no login file and a placeholder → refuses to start, writes no login; a real password → a login,
      as before; a login file that exists → untouched
  [8] install-docker.sh: a login file that is GONE is a new login even when the certificate is reused (REUSE_TLS) — the
      summary shows it and it leaves .env; a login file that exists is kept (round 9b, the recovery re-install)

Run: python3 tests/docker_env_password_selftest.py          (0 = pass)
     --perturb   six plants (no forget after the install; a verification that always passes, or passes with no login
                 file; the entrypoint mints from a placeholder; a placeholder kept as the password; a lost login file under a
                 reused certificate not called a new login) — each turns its own check red
"""
import os, re, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {"COMMON": os.environ.get("SWG_DEP_COMMON") or os.path.join(ROOT, "lib", "common.sh"),
         "IDOCK": os.environ.get("SWG_DEP_IDOCK") or os.path.join(ROOT, "install-docker.sh"),
         "UPD": os.environ.get("SWG_DEP_UPD") or os.path.join(ROOT, "update.sh"),
         "ENTRY": os.environ.get("SWG_DEP_ENTRY") or os.path.join(ROOT, "docker", "entrypoint.sh")}
PLANTS = [
    ("no-forget", "IDOCK", '  docker_env_forget_password "$INSTALL_DIR" 90\n',
     "  :\n", "[4] install-docker.sh forgets it after compose up, for a login this run applied, before the summary"),
    ("verify-true", "COMMON", '    ok = scheme == "pbkdf2_sha256" and hmac.compare_digest(', '    ok = True or scheme == "pbkdf2_sha256" and hmac.compare_digest(',
     "[2] the login does not hold it → .env untouched"),
    ("verify-noauth", "COMMON", "    ok = False\nsys.exit(0 if ok else 1)\nPYPW\n    if [", "    ok = True\nsys.exit(0 if ok else 1)\nPYPW\n    if [",
     "[2] …no login file yet → untouched too"),
    ("entry-mints", "ENTRY", '    exit 1;;\n  esac\n  if [ -n "${PANEL_PASSWORD:-}" ]; then', '    :;;\n  esac\n  if [ -n "${PANEL_PASSWORD:-}" ]; then',
     "[7] no login file and a placeholder → the entrypoint refuses, writes no login"),
    ("reuse-no-new", "IDOCK", '    [ -s "$PREFIX$INSTALL_DIR/data/etc/auth" ] || { $DRYRUN || NEW_LOGIN=yes; }\n', "\n",
     "[8] a login file that is GONE is a new login even when the certificate is reused"),
    ("keep-placeholder", "IDOCK", '  [ "$KEEP_AUTH" != yes ] && docker_pw_placeholder "$PANEL_PASSWORD" && PANEL_PASSWORD="$(rand_pw)"\n', "\n",
     "[5] a placeholder with no login kept → a NEW password"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = open(PATHS[key], encoding="utf-8").read()
        if src.count(old) != 1:
            print("  %-16s STALE ANCHOR (%d)" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_DEP_" + key: f.name}), capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-16s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

COMMON = open(PATHS["COMMON"], encoding="utf-8").read()
IDOCK = open(PATHS["IDOCK"], encoding="utf-8").read()
UPD = open(PATHS["UPD"], encoding="utf-8").read()
ENTRY = open(PATHS["ENTRY"], encoding="utf-8").read()
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n     " + str(detail)[:600]))
    if not ok:
        fails.append(name)


FN = COMMON[COMMON.index("DOCKER_PW_PLACEHOLDERS="):COMMON.index("# ── docker: pre-create the secret files")]
PRE = 'info(){ echo "INFO $*"; }; warn(){ echo "WARN $*"; }; have(){ command -v "$1" >/dev/null 2>&1; }\n'
SECRET = "Given-Pa55-q6x"
MKAUTH = r'''import sys, os, hashlib, base64
u, pw = sys.argv[1], sys.argv[2]
salt = os.urandom(16); it = 1000
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
print("%s:pbkdf2_sha256$%d$%s$%s" % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
'''


def box(env_line, auth_pw):
    d = tempfile.mkdtemp(prefix="dep-")
    os.makedirs(os.path.join(d, "data", "etc"))
    open(os.path.join(d, ".env"), "w").write("# generated by install-docker.sh — profile: host\nPANEL_USER=admin46\n%s\nSUB_PORT=8444\n" % env_line)
    os.chmod(os.path.join(d, ".env"), 0o640)
    if auth_pw is not None:
        a = subprocess.run([sys.executable, "-", "admin46", auth_pw], input=MKAUTH, capture_output=True, text=True).stdout
        open(os.path.join(d, "data", "etc", "auth"), "w").write(a)
    return d


def forget(d, wait="0"):
    r = subprocess.run(["bash", "-c", PRE + FN + 'docker_env_forget_password "%s" %s' % (d, wait)], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


for label, line in (("plain", "PANEL_PASSWORD=" + SECRET), ("double-quoted", 'PANEL_PASSWORD="%s"' % SECRET), ("single-quoted", "PANEL_PASSWORD='%s'" % SECRET)):
    d = box(line, SECRET)
    before = open(os.path.join(d, ".env")).read()
    out = forget(d)
    after = open(os.path.join(d, ".env")).read()
    check("[1] %s: the line becomes PANEL_PASSWORD=(preserved), every other line byte for byte" % label,
          after == before.replace(line, "PANEL_PASSWORD=(preserved)"), (before, after, out))
    check("[1] %s: …mode 0600, one line says so, the password is never printed" % label,
          stat.S_IMODE(os.stat(os.path.join(d, ".env")).st_mode) == 0o600 and "no longer kept" in out and SECRET not in out, out)

d = box("PANEL_PASSWORD=" + SECRET, "a-different-password")
out = forget(d)
check("[2] the login does not hold it → .env untouched", open(os.path.join(d, ".env")).read().count("PANEL_PASSWORD=" + SECRET) == 1
      and "stays there" in out and SECRET not in out, out)
d = box("PANEL_PASSWORD=" + SECRET, None)
out = forget(d)
check("[2] …no login file yet → untouched too", "PANEL_PASSWORD=" + SECRET in open(os.path.join(d, ".env")).read(), out)

outs = []
for v in ("(preserved)", "converted-login-preserved", "unused-on-node-only", ""):
    d = box("PANEL_PASSWORD=" + v, SECRET)
    b = open(os.path.join(d, ".env")).read()
    outs.append((forget(d), open(os.path.join(d, ".env")).read() == b))
check("[3] a placeholder or an empty value → nothing at all", all(o == "" and same for o, same in outs), outs)

i_up = IDOCK.find('on_tty $COMPOSE --profile "$PROFILE" up -d $RECREATE $BUILDFLAG )')
i_fg = IDOCK.find('if [ "${NEW_LOGIN:-no}" = yes ] && ! $DRYRUN; then\n  _pw_was=')
i_fg = IDOCK.find('  docker_env_forget_password "$INSTALL_DIR" 90\n', i_fg) if i_fg > 0 else -1   # inside that block (F94 re-creates after it)
i_sum = IDOCK.find('\nprint_summary "$(')
check("[4] install-docker.sh forgets it after compose up, for a login this run applied, before the summary",
      0 < i_up < i_fg < i_sum, (i_up, i_fg, i_sum))

m = re.search(r'\n  \[ -z "\$PANEL_PASSWORD" \] && PANEL_PASSWORD="\$\(rand_pw\)".*?\n(.*?)\n  return 0', IDOCK, re.S)
tail = (m.group(0) if m else "").replace("\n  return 0", "")
run5 = lambda keep, pw: subprocess.run(["bash", "-c", PRE + FN + 'rand_pw(){ echo NEWRANDOM; }; KEEP_AUTH=%s; PANEL_PASSWORD="%s"\n%s\necho "PW=[$PANEL_PASSWORD]"' % (keep, pw, tail)],
                                        capture_output=True, text=True).stdout.strip()
check("[5] a placeholder with no login kept → a NEW password", bool(m) and run5("no", "(preserved)") == "PW=[NEWRANDOM]"
      and run5("no", "converted-login-preserved") == "PW=[NEWRANDOM]", (run5("no", "(preserved)"), tail[:300]))
check("[5] …a kept login keeps its placeholder, and a real password stays as given", run5("yes", "(preserved)") == "PW=[(preserved)]"
      and run5("no", "Real-Pw-1") == "PW=[Real-Pw-1]", (run5("yes", "(preserved)"), run5("no", "Real-Pw-1")))

check("[6] update.sh forgets it for a running Docker panel (a box installed before)",
      'grep -cx swg-panel >/dev/null; then\n  docker_env_forget_password "$DOCKER_DIR" 60\nfi' in UPD)

blk = re.search(r'\nif \[ -n "\$\{SWG_PANEL_AUTH:-\}" \] && \[ ! -s "\$SWG_PANEL_AUTH" \]; then\n.*?\nfi\n', ENTRY, re.S)
def entry(pw, auth_exists=False):
    d = tempfile.mkdtemp(prefix="dep-entry-")
    a = os.path.join(d, "auth")
    if auth_exists:
        open(a, "w").write("admin46:pbkdf2_sha256$1$AA==$AA==\n")
    r = subprocess.run(["bash", "-c", 'log(){ echo "LOG $*"; }\nSWG_PANEL_AUTH="%s"; PANEL_USER=admin46; PANEL_PASSWORD="%s"\n%s\necho "REACHED-THE-PANEL"' % (a, pw, blk.group(0) if blk else "exit 9")],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, (open(a).read() if os.path.exists(a) else None)
rc, out, auth = entry("(preserved)")
check("[7] no login file and a placeholder → the entrypoint refuses, writes no login",
      rc == 1 and "REACHED-THE-PANEL" not in out and "refusing to start without a login" in out and not auth, (rc, out, auth))
rc2, out2, auth2 = entry("converted-login-preserved")
check("[7] …the convert's placeholder too", rc2 == 1 and not auth2, (rc2, out2))
rc, out, auth = entry("Real-Pw-1")
check("[7] a real password → a login, as before", rc == 0 and "REACHED-THE-PANEL" in out and (auth or "").startswith("admin46:pbkdf2_sha256$"), (rc, out, auth))
rc, out, auth = entry("(preserved)", auth_exists=True)
check("[7] a login file that exists → untouched, the panel starts", rc == 0 and "REACHED-THE-PANEL" in out and auth == "admin46:pbkdf2_sha256$1$AA==$AA==\n", (rc, out, auth))

a8 = IDOCK.index("NEW_LOGIN=no\nif [ \"$PROFILE\" != node ]; then")
b8 = IDOCK.index("\nfi\n", IDOCK.index("    $DRYRUN || NEW_LOGIN=yes   # a dry run deleted nothing", a8)) + 4
BLK = IDOCK[a8:b8]
def nl(auth):
    d = tempfile.mkdtemp(prefix="dep-nl-"); os.makedirs(os.path.join(d, "data", "etc"))
    if auth is not None:
        open(os.path.join(d, "data", "etc", "auth"), "w").write(auth)
    r = subprocess.run(["bash", "-c", 'PREFIX=""; INSTALL_DIR="%s"; DRYRUN=false; PROFILE=host; REUSE_TLS=yes; KEEP_AUTH=no\n%s\necho "NEW_LOGIN=$NEW_LOGIN"' % (d, BLK)],
                       capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr
check("[8] a login file that is GONE is a new login even when the certificate is reused",
      nl(None) == "NEW_LOGIN=yes" and nl("") == "NEW_LOGIN=yes", (nl(None), nl("")))
check("[8] …a login file that exists is kept (no new login)", nl("admin46:pbkdf2_sha256$1$AA==$AA==\n") == "NEW_LOGIN=no", nl("x:y\n"))

print("\n%s" % ("PASS — all checks" if not fails else "FAIL — %d check(s) failed" % len(fails)))
sys.exit(1 if fails else 0)
