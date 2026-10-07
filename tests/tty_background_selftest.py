#!/usr/bin/env python3
"""Self-test — a script running in the BACKGROUND of its terminal does not freeze at its first question.

Ubuntu 26.04's sudo is sudo-rs. Under `curl … | sudo bash -s node -key … -host …` (our documented one-liner) it runs the
script in the background of its own terminal: /dev/tty still opens, so every "is there a terminal?" probe said yes, and
the first `read … </dev/tty` stopped the process (SIGTTIN, state T) with nothing on screen. On a client's home box that
was "the installer hangs at the TLS question" — what he typed was only echoed (client report 2026-10-06).

Each script now decides SWG_TTY up front: /dev/tty while its process group is the terminal's foreground, /dev/null
otherwise (an EOF, which every question already answers with its no-terminal default). This drives every script's OWN
copy of that snippet in a real pseudo-terminal, in both positions:

  [1] background (a process group that is not the terminal's foreground): SWG_TTY=/dev/null, swg_tty_ok says no, and a
      question READS without stopping — before, the same read stopped the process
  [2] CONTROL, foreground: SWG_TTY=/dev/tty, and a question still reads what is typed
  [3] no question in any script reads /dev/tty directly any more (they read "${SWG_TTY:-/dev/tty}")
  [4] bootstrap.sh in the background warns before anything asks, and hands back the same arguments as
      `sudo bash -c "$(curl -fsSL …/bootstrap.sh)" -- …`, the form that works under sudo-rs and classic sudo alike
  [5] the snippet is byte-identical in all seven scripts (each needs it before lib/common.sh is loaded)
  [6] bootstrap.sh is one brace group: a download cut off mid-way is a syntax error that runs nothing, in either form

Run: python3 tests/tty_background_selftest.py      (0 = pass)
"""
import os, pty, re, select, signal, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = ("bootstrap.sh", "install-node.sh", "install-host.sh", "install-docker.sh", "update.sh", "uninstall.sh", "convert.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def snippet(src):
    a = src.index("_swg_tty_fg(){"); b = src.index("swg_tty_ok(){", a); b = src.index("\n", b) + 1
    return src[a:b]

def run_in_pty(script, background, typed=b""):
    """Run `bash -c script` on a fresh pty — in the terminal's foreground, or in a process group of its own (the
    background). → (output, stopped?)"""
    pid, fd = pty.fork()
    if pid == 0:                                   # the session leader: owns the pty, its group is the foreground
        if background:
            c = os.fork()
            if c == 0:
                os.setpgid(0, 0)                   # a new group, not the terminal's foreground: what sudo-rs does
                os.execvp("bash", ["bash", "-c", script])
            _, st = os.waitpid(c, os.WUNTRACED)
            os._exit(99 if os.WIFSTOPPED(st) else 0)
        os.execvp("bash", ["bash", "-c", script])
    out = b""; end = time.time() + 6
    if typed:
        time.sleep(0.5); os.write(fd, typed)
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                d = os.read(fd, 4096)
            except OSError:                        # EIO: the child closed the pty — it has exited
                d = b""
            if not d:
                _, st = os.waitpid(pid, 0)
                return out.decode(errors="replace"), (os.WIFEXITED(st) and os.WEXITSTATUS(st) == 99)
            out += d
        wp, st = os.waitpid(pid, os.WNOHANG)
        if wp:
            return out.decode(errors="replace"), (os.WIFEXITED(st) and os.WEXITSTATUS(st) == 99)
    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
    return out.decode(errors="replace") + "<TIMEOUT>", True

BODY = ('echo "TTY=$SWG_TTY"; if swg_tty_ok; then echo OK=yes; else echo OK=no; fi; '
        'v=""; read -r v <"${SWG_TTY:-/dev/tty}" && echo "READ=[$v]" || echo "READ=eof"')
for f in SCRIPTS:
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    snip = snippet(src)
    print("== %s" % f)
    out, stopped = run_in_pty(snip + BODY, background=True)
    check("[1] background: SWG_TTY is /dev/null and swg_tty_ok says no", "TTY=/dev/null" in out and "OK=no" in out, out)
    check("[1] background: the question reads (EOF → its default) instead of stopping", "READ=eof" in out and not stopped, out)
    out, stopped = run_in_pty(snip + BODY, background=False, typed=b"yes\n")
    check("[2] foreground: SWG_TTY is /dev/tty and the answer typed is read", "TTY=/dev/tty" in out and "READ=[yes]" in out and not stopped, out)

print("== the old probe, for the record")
out, stopped = run_in_pty('{ : </dev/tty; } 2>/dev/null && echo OPENS; read -r v </dev/tty; echo "READ=$?"', background=True)
check("[1] CONTROL: in the background /dev/tty still opens and a direct read STOPS the process", "OPENS" in out and stopped, out)

print("== [3] no question reads /dev/tty directly")
for f in SCRIPTS + ("lib/common.sh",):
    bad = []
    for i, ln in enumerate(open(os.path.join(ROOT, f), encoding="utf-8").read().splitlines(), 1):
        if ln.lstrip().startswith("#"):
            continue
        if re.search(r"\bread\b[^#]*</dev/tty\b", ln):
            bad.append(i)
    check("%s: every read goes through SWG_TTY" % f, not bad, bad)

print("== [4] bootstrap.sh, run in the background, says so — with the command that works")
import tempfile
D = tempfile.mkdtemp(prefix="ttybg-")
open(D + "/id", "w").write('#!/bin/sh\n[ "$1" = -u ] && echo 0 || command id "$@"\n')   # past the root check
open(D + "/curl", "w").write("#!/bin/sh\nexit 7\n"); open(D + "/git", "w").write("#!/bin/sh\nexit 7\n")    # and no fetch
for n in ("id", "curl", "git"):
    os.chmod(D + "/" + n, 0o755)
BS = ('cd %s && PATH=%s:$PATH bash bootstrap.sh node -key "abc 123" -host https://panel.example.net' % (ROOT, D))
out, stopped = run_in_pty(BS, background=True)
check("[4] it warns that the terminal cannot be read", "this terminal cannot be read" in out, out[:600])
check("[4] …and hands back the same arguments in the form sudo-rs can run",
      'sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/' in out
      and '/bootstrap.sh)" -- node -key abc\\ 123 -host https://panel.example.net' in out, out[:600])
check("[4] …and does not stop", not stopped, out[-300:])
out, stopped = run_in_pty(BS, background=False)
check("[4] CONTROL: in the foreground it says nothing of the kind", "this terminal cannot be read" not in out, out[:300])

print("== [5] one snippet, seven copies (each script decides before lib/common.sh is loaded) — never drifting apart")
snips = {f: snippet(open(os.path.join(ROOT, f), encoding="utf-8").read()) for f in SCRIPTS}
ref = snips["bootstrap.sh"]
for f, sn in snips.items():
    check("%s: byte-identical to bootstrap.sh's" % f, sn == ref, f)

print("== [6] a download cut off mid-way runs nothing (bootstrap.sh is one brace group)")
import subprocess
bs = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
# Cut at a clean TOP-LEVEL line boundary (the root check), so that WITHOUT the group every command before it would run and
# then the probe — a mid-line cut would be a syntax error with or without the guard, and prove nothing.
cut = bs[: bs.index('[ "$(id -u)" = 0 ] || die "run with sudo')]
probe = "\necho RAN-SOMETHING\n"
r = subprocess.run(["bash", "-c", cut + probe, "--", "node"], capture_output=True, text=True, timeout=30)
check("[6] `bash -c \"$(curl …)\"` of a truncated script: a syntax error, and not one command run",
      "syntax error" in r.stderr and "RAN-SOMETHING" not in r.stdout and r.stdout.strip() == "", (r.stdout + r.stderr)[-300:])
r = subprocess.run(["bash", "-s", "--", "node"], input=cut + probe, capture_output=True, text=True, timeout=30)
check("[6] `curl … | bash` of a truncated script: the same", "syntax error" in r.stderr and r.stdout.strip() == "", (r.stdout + r.stderr)[-300:])
unguarded = cut.replace("\n{\nset -euo pipefail\n", "\nset -euo pipefail\n", 1)
r = subprocess.run(["bash", "-c", unguarded + probe, "--", "node"], capture_output=True, text=True, timeout=30)
check("[6] CONTROL: the same cut WITHOUT the group runs the first half (and the probe) — what the group prevents",
      "RAN-SOMETHING" in r.stdout, (r.stdout + r.stderr)[-300:])
check("[6] …and the whole script is one group: opened before `set -euo pipefail`, closed on its last line",
      "\n{\nset -euo pipefail\n" in bs and bs.rstrip("\n").splitlines()[-1].startswith("}"), bs[-200:])

print("")
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
