#!/usr/bin/env python3
"""Self-test: `swg-passwd` ends every signed-in session when it changes the password, as the in-panel change does.

The in-panel password change rotates the session-signing secret ("a captured cookie dies"). swg-passwd — the tool for a
password that is lost or leaked — restarted the panel, which reloaded the SAME secret, so a cookie signed before the reset
stayed valid for its full week. Measured on a throwaway 1.8.7 panel (qualification PART 4, A2): a browser session opened
before `swg-passwd` still answered /api/state with 200 afterwards.

The REAL swg-passwd runs in a pty (it reads passwords with getpass) against a temp auth file and state dir, with `systemctl`
stubbed on PATH so nothing on this machine is restarted. Cookies are minted and checked with swg-panel-server's own
make_session / verify_session against whatever session.key holds.

  [1] a password change: a cookie minted before it no longer verifies; one minted with the new secret does
  [2] the secret is rewritten IN PLACE — same inode, mode 0600 kept (a root-owned replacement would lock the panel out
      of its own secret on a real box)
  [3] the vault marker is still written and the new password verifies against the auth file
  [4] a username-only change keeps sessions (the in-panel change rotates only on a new password); the tool says so in its
      summary either way
  [5] no session.key yet (a panel that never started): the reset still completes

Run: python3 tests/passwd_ends_sessions_selftest.py      (0 = pass)
     --perturb   runs a swg-passwd that never rewrites session.key and expects RED on [1] ("PERTURB OK", exit 0).
"""
import importlib.machinery, importlib.util, os, pty, re, select, stat, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PASSWD = os.environ.get("SWG_PASSWD") or os.path.join(ROOT, "swg-passwd")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

ld = importlib.machinery.SourceFileLoader("swgpanel_passwd", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_passwd", ld))
P.__dict__["__file__"] = PANEL
try:
    ld.exec_module(P)
except SystemExit:
    pass

tool = PASSWD
if PERTURB:
    src = open(PASSWD).read()
    anchor = "        revoked = _revoke_sessions()"
    if src.count(anchor) != 1:
        print("PERTURB FAILED — the session revocation call is not in swg-passwd exactly once")
        sys.exit(1)
    tool = os.path.join(tempfile.mkdtemp(), "swg-passwd")
    open(tool, "w").write(src.replace(anchor, '        revoked = "ok"'))

def box(with_key=True):
    d = tempfile.mkdtemp(prefix="passwd-")
    etc, state, bindir = os.path.join(d, "etc"), os.path.join(d, "state"), os.path.join(d, "bin")
    for x in (etc, state, os.path.join(state, "subs"), bindir):
        os.makedirs(x)
    with open(os.path.join(etc, "auth"), "w") as f:
        f.write("admin:" + P.make_pw_hash("old-password-123") + "\n")
    if with_key:
        with open(os.path.join(state, "session.key"), "wb") as f:
            f.write(b"A" * 64)
        os.chmod(os.path.join(state, "session.key"), 0o600)
    with open(os.path.join(bindir, "systemctl"), "w") as f:
        f.write("#!/bin/sh\necho \"$@\" >> \"%s/systemctl.calls\"\nexit 0\n" % d)
    os.chmod(os.path.join(bindir, "systemctl"), 0o755)
    return d, etc, state, bindir

def run_passwd(d, etc, state, bindir, argv, answers):
    env = dict(os.environ, SWG_PANEL_AUTH=os.path.join(etc, "auth"), SWG_PANEL_STATE=state,
               SWG_PANEL_SUBS=os.path.join(state, "subs"), PATH=bindir + ":" + os.environ.get("PATH", ""))
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, tool] + argv, env)
    out, pending, end, answered = b"", list(answers), time.time() + 30, 0
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                c = os.read(fd, 4096)
            except OSError:
                break
            if not c:
                break
            out += c
            # Answer each prompt ONCE, when a new one has appeared. Keying on "the buffer ends with a colon" answered the
            # retype prompt early — the chunk after an answer can be a bare newline, so the OLD prompt still ended the
            # buffer — and getpass sets up its terminal with TCSAFLUSH, which discards input typed before the prompt.
            asked = len(re.findall(rb"(?i)(?:password|username)[^\n]*: ", out))
            while pending and answered < asked:
                os.write(fd, pending.pop(0).encode() + b"\n")
                answered += 1
    if time.time() >= end:
        os.kill(pid, 9)                                  # a stuck prompt must fail the run, not hang it
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")

def secret(state):
    with open(os.path.join(state, "session.key"), "rb") as f:
        return f.read().strip()

# [1]–[3] a password change
d, etc, state, bindir = box()
kp = os.path.join(state, "session.key")
before = os.stat(kp)
cookie = P.make_session("admin", secret(state))
check("[0] the cookie verifies before the reset (the fixture is real)", P.verify_session(cookie, secret(state)) == "admin")
rc, out = run_passwd(d, etc, state, bindir, ["admin"], ["new-password-456", "new-password-456"])
check("[0] swg-passwd completed", rc == 0 and "Applied" in out, (rc, out[-400:]))
check("[1] a cookie signed before the reset no longer verifies", P.verify_session(cookie, secret(state)) is None, secret(state)[:12])
check("[1] …and a cookie signed after it does", P.verify_session(P.make_session("admin", secret(state)), secret(state)) == "admin")
after = os.stat(kp)
check("[2] session.key rewritten in place — same inode", after.st_ino == before.st_ino, (before.st_ino, after.st_ino))
check("[2] …mode 0600 kept", stat.S_IMODE(after.st_mode) == 0o600, oct(stat.S_IMODE(after.st_mode)))
check("[2] …and a usable secret (≥ 32 bytes)", len(secret(state)) >= 32, len(secret(state)))
check("[3] the vault marker is written", os.path.exists(os.path.join(state, "subs", "vault.reset")))
with open(os.path.join(etc, "auth")) as f:
    user, _, h = f.readline().strip().partition(":")
check("[3] the new password verifies against the auth file", user == "admin" and P.verify_password(h, "new-password-456"), user)
check("[4] the summary says signed-in sessions were ended", "Signed-in sessions:  ended" in out, out[-600:])

# [4] a username-only change
d, etc, state, bindir = box()
cookie = P.make_session("admin", secret(state))
key_before = secret(state)
rc, out = run_passwd(d, etc, state, bindir, ["root2"], [""])
check("[4] username-only change completed", rc == 0 and "Password:  unchanged" in out, (rc, out[-300:]))
check("[4] …and kept the session secret (as the in-panel change does)", secret(state) == key_before)

# [5] no session.key yet
d, etc, state, bindir = box(with_key=False)
rc, out = run_passwd(d, etc, state, bindir, ["admin"], ["new-password-789", "new-password-789"])
check("[5] no session.key: the reset still completes and does not create one (the panel mints it on start)",
      rc == 0 and "Applied" in out and not os.path.exists(os.path.join(state, "session.key")), (rc, out[-300:]))

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — sessions were not revoked and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
