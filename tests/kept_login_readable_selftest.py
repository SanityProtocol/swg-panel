#!/usr/bin/env python3
"""Self-test: a re-install or a docker→bare-metal convert that KEEPS the panel login leaves it readable by the panel.

Measured on a fresh Ubuntu 24.04 box (1.8.7 qualification S4): `convert.sh docker baremetal master` staged
/etc/swg-panel/auth out of a container whose panel ran as root — root:root 0600 — and install-host's "keeping existing
login … untouched" left it that way. The panel runs as swgpanel, could not read it, and refused every request ("LOGIN IS
CLOSED") while the convert reported the login kept. The graph history came across root-owned too, and the panel threw
it away ("not writable (owned by another user) — recreated").

  [1] with an auth file already there (KEEP_AUTH), the installer sets it 640 root:swg — what mk_auth_file sets a new one
  [2] …and without one, it still writes a new login (mk_auth_file), not a keep
  [3] the stats directory is re-chowned recursively, as the state directory is

Driven through `install-host.sh --dry-run` with ETC_DIR pointed at a scratch directory, so the keep branch really runs
and every command it would execute is read back from its `[skip]` lines.

Run: python3 tests/kept_login_readable_selftest.py (0 = pass)
     --perturb   the keep branch goes back to touching nothing → RED on [1]
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


T = tempfile.mkdtemp(prefix="keptlogin-")
SRC = os.path.join(T, "src")
shutil.copytree(ROOT, SRC, ignore=shutil.ignore_patterns(".git", "dryrun", "node_modules", "*.png", "scratchpad", "docs",
                                                         ".campaign", "__pycache__", "forks", "screenshots"))
host = os.path.join(SRC, "install-host.sh")
src = open(host, encoding="utf-8").read()
KEEP = '''run chmod 640 "$ETC_DIR/auth"; run chown root:swg "$ETC_DIR/auth"'''
if PERTURB:
    assert src.count(KEEP) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    open(host, "w", encoding="utf-8").write(src.replace(KEEP, ":", 1))


def dry(with_auth):
    etc = os.path.join(T, "etc-" + ("keep" if with_auth else "new"))
    os.makedirs(etc, exist_ok=True)
    if with_auth:
        open(os.path.join(etc, "auth"), "w").write("admin347:pbkdf2_sha256$200000$c2FsdA==$aGFzaA==\n")
        os.chmod(os.path.join(etc, "auth"), 0o600)
    env = dict(os.environ, ETC_DIR=etc, ROLE="host", SERVE_MODE="internal", TLS_MODE="selfsigned", BASIC_PASS="dry-run-pass",
               PANEL_DOMAIN="127.0.0.1", PORT="2087")
    r = subprocess.run(["bash", "install-host.sh", "--dry-run"], cwd=SRC, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300)
    return r, etc


print("[1] a kept login is made readable by the panel")
r, etc = dry(True)
out = r.stdout + r.stderr
check("the dry run completed", r.returncode == 0 and "DRY RUN done" in out, (r.returncode, out[-300:]))
check("the keep branch ran", "keeping existing login" in out, out[-400:])
check("⚠️ it sets the kept file 640", "[skip] chmod 640 %s/auth" % etc in out, [l for l in out.splitlines() if "auth" in l][:6])
check("⚠️ …and root:swg", "[skip] chown root:swg %s/auth" % etc in out, [l for l in out.splitlines() if "auth" in l][:6])

print("\n[2] no login there → a new one is written, not kept")
r, etc = dry(False)
out = r.stdout + r.stderr
check("the dry run completed", r.returncode == 0 and "DRY RUN done" in out, (r.returncode, out[-300:]))
check("mk_auth_file ran", "write %s/auth (pbkdf2 login" % etc in out and "keeping existing login" not in out, [l for l in out.splitlines() if "auth" in l][:6])

print("\n[3] the stats directory is re-chowned recursively")
live = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
check("chown -R $PANEL_USER:swg $STATS_DIR", re.search(r'run chown -R "\$PANEL_USER:swg" "\$STATS_DIR"', live) is not None)

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
