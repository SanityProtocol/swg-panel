#!/usr/bin/env python3
"""Self-test — a script running in the BACKGROUND of its terminal does not freeze at its first question.

Ubuntu 26.04's sudo is sudo-rs. Under `curl … | sudo bash -s node -key … -host …` (our documented one-liner) it runs the
script in the background of its own terminal: /dev/tty still opens, so every "is there a terminal?" probe said yes, and
the first `read … </dev/tty` stopped the process (SIGTTIN, state T) with nothing on screen. On a client's home box that
was "the installer hangs at the TLS question" — what he typed was only echoed (client report 2026-10-06).

Each script now decides SWG_TTY up front: /dev/tty while its process group is the terminal's foreground, /dev/null
otherwise (an EOF, which every question already answers with its no-terminal default). This drives every script's OWN
copy of that snippet in a real pseudo-terminal, in both positions:

  [1] background under sudo-rs (a process group that is not the terminal's foreground, whose supervisor never brings it
      forward — modelled by a supervisor process whose binary is a sudo-rs): SWG_TTY=/dev/null, swg_tty_ok says no, and a
      question READS without stopping — before, the same read stopped the process
  [2] CONTROL, foreground: SWG_TTY=/dev/tty, and a question still reads what is typed
  [3] no question in any script reads /dev/tty directly any more (they read "${SWG_TTY:-/dev/tty}")
  [4] bootstrap.sh in the background warns before anything asks, and hands back the same arguments as
      `sudo bash -c "$(curl -fsSL …/bootstrap.sh)" -- …`, the form that works under sudo-rs and classic sudo alike
  [5] the snippet is byte-identical in all seven scripts (each needs it before lib/common.sh is loaded)
  [6] bootstrap.sh is one brace group: a download cut off mid-way is a syntax error that runs nothing, in either form
  [8] (1.8.9 qualification IN-2) background under CLASSIC sudo (≥ 1.9.13 with use_pty: Ubuntu 24.04, Debian 12/13), which
      brings a stopped command to the foreground at its first terminal read — modelled by a supervisor named sudo that
      does exactly that: SWG_TTY=/dev/tty and the question reads what is typed (1.8.8 asked there; the candidate took every
      background start for sudo-rs and asked nothing, printing the sudo-rs warning); no sudo above at all (a job put in the
      background) → the terminal too; no terminal at all → /dev/null; and, where `sudo -n` is the classic sudo, the REAL
      `cat … | sudo -n bash -s` in a pseudo-terminal reads the answer typed

Run: python3 tests/tty_background_selftest.py      (0 = pass)
     --perturb   every copy decides by the foreground alone again (52aa9c4) → RED on [8]
"""
import os, pty, re, select, shutil, signal, sys, tempfile, time
PERTURB = "--perturb" in sys.argv[1:]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = ("bootstrap.sh", "install-node.sh", "install-host.sh", "install-docker.sh", "update.sh", "uninstall.sh", "convert.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

OLD_FN = ('''_swg_tty_fg(){ local s f IFS=' '; { read -r s </proc/$$/stat; } 2>/dev/null || return 0; read -ra f <<< "${s##*) }"; '''
          '''[ "${f[2]:-}" = "${f[5]:-}" ]; }\n''')
def snippet(src):
    a = src.index("_swg_tty_fg(){"); b = src.index("swg_tty_ok(){", a); b = src.index("\n", b) + 1
    sn = src[a:b]
    if PERTURB:                                    # the decision as 52aa9c4 shipped it: the foreground, or nothing
        e = sn.index("done; return 0; }\n") + len("done; return 0; }\n")
        sn = OLD_FN + sn[e:]
    return sn

# The supervisors: what sudo does with a command whose stdin is not a terminal — runs it in a process group of its own, in
# the background of the terminal. Each is a copy of this Python named `sudo` (the script looks at its parent's binary):
# under cargo/bin/ — the path Ubuntu's sudo-rs package installs — it never brings a stopped command forward (sudo-rs);
# under bin/ it does (classic sudo: a command stopped by SIGTTIN becomes the foreground and is continued).
SUPD = tempfile.mkdtemp(prefix="ttysup-")
SUP_RS, SUP_CLASSIC = os.path.join(SUPD, "cargo", "bin", "sudo"), os.path.join(SUPD, "bin", "sudo")
for _s in (SUP_RS, SUP_CLASSIC):
    os.makedirs(os.path.dirname(_s)); shutil.copy2(os.path.realpath(sys.executable), _s)
SUP = r'''
import os, signal, sys
script, mode = sys.argv[1], sys.argv[2]
c = os.fork()
if c == 0:
    os.setpgid(0, 0)
    os.execvp("bash", ["bash", "-c", script])
while True:
    _, st = os.waitpid(c, os.WUNTRACED)
    if not os.WIFSTOPPED(st):
        os._exit(0)
    if mode == "rs":
        os._exit(99)                              # stopped, and nobody brings it forward
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    os.tcsetpgrp(0, os.getpgid(c)); os.kill(c, signal.SIGCONT)   # classic sudo: the foreground, then on
'''

def run_in_pty(script, background, typed=b"", sup=None):
    """Run `bash -c script` on a fresh pty — in the terminal's foreground, or in a process group of its own (the
    background): under a sudo model (`sup`), or under a plain parent. → (output, stopped?)"""
    pid, fd = pty.fork()
    if pid == 0:                                   # the session leader: owns the pty, its group is the foreground
        if background and sup:
            os.execv(sup, [sup, "-c", SUP, script, "rs" if sup == SUP_RS else "classic"])
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
        if wp:                                     # exited: what it wrote last may still sit in the pty — read it all
            while select.select([fd], [], [], 0.2)[0]:
                try:
                    d = os.read(fd, 4096)
                except OSError:
                    break
                if not d:
                    break
                out += d
            return out.decode(errors="replace"), (os.WIFEXITED(st) and os.WEXITSTATUS(st) == 99)
    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
    return out.decode(errors="replace") + "<TIMEOUT>", True

BODY = ('echo "TTY=$SWG_TTY"; if swg_tty_ok; then echo OK=yes; else echo OK=no; fi; '
        'v=""; read -r v <"${SWG_TTY:-/dev/tty}" && echo "READ=[$v]" || echo "READ=eof"')
for f in SCRIPTS:
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    snip = snippet(src)
    print("== %s" % f)
    out, stopped = run_in_pty(snip + BODY, background=True, sup=SUP_RS)
    check("[1] background under sudo-rs: SWG_TTY is /dev/null and swg_tty_ok says no", "TTY=/dev/null" in out and "OK=no" in out, out)
    check("[1] background under sudo-rs: the question reads (EOF → its default) instead of stopping", "READ=eof" in out and not stopped, out)
    out, stopped = run_in_pty(snip + BODY, background=True, typed=b"yes\n", sup=SUP_CLASSIC)
    check("[8] background under CLASSIC sudo (it foregrounds at the first read): SWG_TTY is /dev/tty and the answer typed is read",
          "TTY=/dev/tty" in out and "READ=[yes]" in out and not stopped, out)
    out, stopped = run_in_pty(snip + 'echo "TTY=$SWG_TTY"', background=True)
    check("[8] no sudo above (a job put in the background): the terminal, as ever", "TTY=/dev/tty" in out, out)
    import subprocess as _sp
    r = _sp.run(["setsid", "-w", "bash", "-c", snip + 'echo "TTY=$SWG_TTY"'], stdin=_sp.DEVNULL, capture_output=True, text=True, timeout=20)
    check("[8] no terminal at all (a service, cron): /dev/null", "TTY=/dev/null" in r.stdout, r.stdout + r.stderr)
    out, stopped = run_in_pty(snip + BODY, background=False, typed=b"yes\n")
    check("[2] foreground: SWG_TTY is /dev/tty and the answer typed is read", "TTY=/dev/tty" in out and "READ=[yes]" in out and not stopped, out)

print("== the old probe, for the record")
out, stopped = run_in_pty('{ : </dev/tty; } 2>/dev/null && echo OPENS; read -r v </dev/tty; echo "READ=$?"', background=True, sup=SUP_RS)
check("[1] CONTROL: under sudo-rs /dev/tty still opens and a direct read STOPS the process", "OPENS" in out and stopped, out)
out, stopped = run_in_pty('{ : </dev/tty; } 2>/dev/null && echo OPENS; read -r v </dev/tty; echo "READ=[$v]"', background=True,
                          typed=b"yes\n", sup=SUP_CLASSIC)
check("[8] CONTROL: under the classic-sudo model the same direct read gets the answer (what 1.8.8 relied on)",
      "OPENS" in out and "READ=[yes]" in out and not stopped, out)

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
out, stopped = run_in_pty(BS, background=True, sup=SUP_RS)
check("[4] it warns that the terminal cannot be read", "this terminal cannot be read" in out, out[:600])
check("[4] …and hands back the same arguments in the form sudo-rs can run",
      'sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/' in out
      and '/bootstrap.sh)" -- node -key abc\\ 123 -host https://panel.example.net' in out, out[:600])
check("[4] …and does not stop", not stopped, out[-300:])
out, stopped = run_in_pty(BS, background=False)
check("[4] CONTROL: in the foreground it says nothing of the kind", "this terminal cannot be read" not in out, out[:300])
out, stopped = run_in_pty(BS, background=True, sup=SUP_CLASSIC)
check("[8] under classic sudo it says nothing of the kind either (no sudo-rs warning where the questions are asked)",
      "this terminal cannot be read" not in out, out[:300])

out, stopped = run_in_pty("cd %s && SWG_REF=dev PATH=%s:$PATH bash bootstrap.sh node -key K" % (ROOT, D), background=True, sup=SUP_RS)
check("[4] a ref other than main rides inside the handed-back command (sudo drops SWG_REF; the dev bootstrap must not install main)",
      'sudo bash -c "SWG_REF=dev; $(curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/bootstrap.sh)" -- node -key K' in out, out[:600])

print("== [4b] no prompt left hanging where the terminal cannot be read (code review)")
dsrc = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
a = dsrc.index("ask_tty(){"); b = dsrc.index("\nask_yn_tty(){", a)
out, stopped = run_in_pty(snippet(dsrc) + dsrc[a:b] + '\nv="$(ask_tty "Domain" "panel.example")"; echo "GOT=[$v]"', background=True, sup=SUP_RS)
check("[4b] install-docker ask_tty: the default is said as taken, and returned — no bare prompt", "(no terminal — default taken)" in out
      and "GOT=[panel.example]" in out and not stopped, out)
usrc = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
a = usrc.index("confirm(){"); b = usrc.index("\n}\n", a) + 3
out, stopped = run_in_pty(snippet(usrc) + "ASSUME_YES=false; C_BL=; RESET=\n" + usrc[a:b] + '\nconfirm "Update the panel?" && echo YES || echo NO', background=True, sup=SUP_RS)
check("[4b] update.sh confirm: yes, with no prompt printed", "YES" in out and "Update the panel?" not in out and not stopped, out)

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

print("== [7] bootstrap.sh stays far under the kernel's per-argument limit (it is ONE argv string in `bash -c \"$(curl …)\"`)")
size = len(bs.encode("utf-8"))
check("[7] %d bytes < 96 KiB (MAX_ARG_STRLEN is 128 KiB: past it every handed-out command fails 'Argument list too long')" % size,
      size < 96 * 1024, size)

print("== [8] the REAL sudo, where it is the classic one and needs no password: `cat … | sudo -n bash -s` in a pseudo-terminal")
import subprocess as _sp8
_v = _sp8.run(["sudo", "-V"], capture_output=True, text=True, stdin=_sp8.DEVNULL) if shutil.which("sudo") else None   # -V asks no password
if _v is not None and _v.returncode == 0 and _v.stdout.startswith("Sudo version") and _sp8.run(["sudo", "-n", "true"]).returncode == 0:
    _probe = os.path.join(SUPD, "probe.sh")
    open(_probe, "w").write(snippet(open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()) + BODY + "\n")
    out, stopped = run_in_pty("cat %s | sudo -n bash -s" % _probe, background=False, typed=b"yes\n")
    check("[8] %s, the script in the background of its pty: SWG_TTY=/dev/tty and the answer typed is read"
          % _v.stdout.splitlines()[0], "TTY=/dev/tty" in out and "READ=[yes]" in out and not stopped, out)
else:
    print("  SKIPPED [8] real sudo — not a classic sudo answering `sudo -n` here")
shutil.rmtree(SUPD, ignore_errors=True)

print("")
if PERTURB:
    _red = [f for f in FAILS if f.startswith("[8]")]
    print("perturb: %s" % ("RED as it must be (%d), all [8]" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red outside [8]: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
