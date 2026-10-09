#!/usr/bin/env python3
"""Self-test — an AmneziaWG kernel module that does not COMPILE is remembered, not retried, and dpkg is left clean.

Ubuntu 26.04, kernel 7.0.0-38 (client report 2026-10-06): upstream's module did not build on that kernel at all. The
installer compiled it four or five times per pass (the package's postinst, `dkms autoinstall` twice, a --reinstall, every
kernel, then from source), every update did all of it again, and the failed amneziawg-dkms was left half-configured —
every later `apt install` on the box ended in "E: Sub-process /usr/bin/dpkg returned an error code (1)".

  [1] the record: one per kernel — a fact for this kernel is kept with the others, another kernel's record is no record
  [2] awg_pkg_retry_due: retried only when apt would install a newer amneziawg-dkms, or on another kernel
  [3] awg_src_retry_due: retried only when upstream's head has moved (an unknown head is not a reason to compile)
  [4] awg_ppa_module_install, driven: a compile failure (headers here, package half-configured, no module file, and the
      COMPILER's error in DKMS's make.log) removes the two packages, keeps the tools, records the version AND the commit the
      PPA built — and the next run does not install it again; a newer package does. CONTROLS: a build that succeeded, and
      one that failed for want of headers, are not given up on
  [4b] (1.8.9 qualification IN-15) a build the BOX cut short — "No space left on device", a killed compiler, no build log
      at all — is not a compile failure: not removed, not recorded (it was given up for good, even past `update -f`) — not
      even where the cut-short build left the compiler's own located `fatal error:` (a full disk, a killed assembler).
      (FN-1) gcc's located `fatal error:` for a header the newer kernel dropped IS one: removed + recorded (`: error: `
      alone read it as transient, and the package stayed half-configured between updates)
  [5] awg_build_from_source, driven: upstream still at the commit that did not compile → no clone, no compile; moved on →
      it builds
  [6] update.sh: the heal answers in one line when nothing new can be tried, and both routes ask the record

Run: python3 tests/awg_module_failed_selftest.py      (0 = pass)
     --perturb   awg_dkms_compile_failed judges without the build log again (52aa9c4) → RED on [4b]
     --perturb-fatal   …reads `: error: ` alone again (84e36bf) → RED on [4b]'s dropped header only
     --perturb-veto    …judges a located `fatal error:` without asking whether the box cut the build short → RED on [4b]
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
C, UP = rd("lib/common.sh"), rd("update.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
def grab_all(*names):
    """The functions as bash itself defines them: lib/common.sh sourced (definitions only), then `declare -f`."""
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f "${@:2}"', "_", os.path.join(ROOT, "lib/common.sh")] + list(names),
                       capture_output=True, text=True)
    assert r.returncode == 0 and all((n + " ()") in r.stdout for n in names), "could not read %s from lib/common.sh" % (names,)
    return r.stdout + "\n"

PERTURB = "--perturb" in sys.argv[1:]
PERTURB_FATAL = "--perturb-fatal" in sys.argv[1:]
PERTURB_VETO = "--perturb-veto" in sys.argv[1:]
T = tempfile.mkdtemp(prefix="awgfail-")
os.makedirs(T + "/bin"); os.makedirs(T + "/mods/7.0.0-38-generic/build")
KV = "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1"
FUNCS = grab_all("awg_fail_get", "awg_fail_note", "awg_module_head", "awg_src_retry_due", "awg_pkg_retry_due", "awg_nothing_new", "awg_mod_built",
                 "_awg_kbuild", "awg_dkms_compile_failed", "awg_dkms_give_up", "awg_ppa_module_install")
_LOGS = '"${SWG_DKMS_TREE:-/var/lib/dkms}"/amneziawg/*/build/make.log'
_ERR = "grep -qsE ': error: |:[0-9]+: fatal error: ' " + _LOGS
_VETO = " && ! grep -qsE 'No space left on device|Killed signal|internal compiler error: Killed' " + _LOGS
if PERTURB:   # the judgement as 52aa9c4 shipped it: half-configured + no module file, whatever the build log says
    _old = "! awg_mod_built && " + _ERR + _VETO
    assert FUNCS.count(_old) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_old, "! awg_mod_built")
if PERTURB_FATAL:   # as 84e36bf shipped it: `: error: ` alone
    assert FUNCS.count(_ERR) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_ERR, "grep -qsE ': error: ' " + _LOGS)
if PERTURB_VETO:    # a located `fatal error:` counted even where the box cut the build short
    assert FUNCS.count(_VETO) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_VETO, "")
MAKELOG = T + "/dkms/amneziawg/1.0.0/build/make.log"
def makelog(text):
    """DKMS's build log for the last attempt (None: there is none)."""
    if text is None:
        if os.path.exists(MAKELOG): os.remove(MAKELOG)
        return
    os.makedirs(os.path.dirname(MAKELOG), exist_ok=True); open(MAKELOG, "w").write(text)
COMPILE_ERR = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"
               "/var/lib/dkms/amneziawg/1.0.0/build/compat/compat.h:812:9: error: too many arguments to function 'setup_udp_tunnel_sock'\n"
               "make[2]: *** [scripts/Makefile.build:243: socket.o] Error 1\n")
NOSPACE = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"
           "{standard input}: Assembler messages:\n"
           "{standard input}:4211: Fatal error: can't write 3904 bytes to section .debug_abbrev of /var/lib/dkms/amneziawg/1.0.0/build/send.o: 'No space left on device'\n"
           "make[2]: *** [scripts/Makefile.build:243: send.o] Error 1\n")
KILLED = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"
          "gcc-13: fatal error: Killed signal terminated program cc1\ncompilation terminated.\n")
FATAL_HDR = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"   # a header the newer kernel dropped
             "/var/lib/dkms/amneziawg/1.0.0/build/socket.c:14:10: fatal error: net/udp_tunnel.h: No such file or directory\n"
             "   14 | #include <net/udp_tunnel.h>\n      |          ^~~~~~~~~~~~~~~~~~\ncompilation terminated.\n"
             "make[2]: *** [scripts/Makefile.build:243: socket.o] Error 1\n")
NOSPACE_CC = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"   # the disk filled while cc1 wrote its .s
              "/var/lib/dkms/amneziawg/1.0.0/build/send.c:412:1: fatal error: error writing to /tmp/ccQ2xV1a.s: No space left on device\n"
              "compilation terminated.\nmake[2]: *** [scripts/Makefile.build:243: send.o] Error 1\n")
KILLED_AS = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"   # the OOM killer took the assembler
             "/var/lib/dkms/amneziawg/1.0.0/build/device.c:530:1: fatal error: error writing to -: Broken pipe\n"
             "compilation terminated.\ngcc-13: fatal error: Killed signal terminated program as\n"
             "make[2]: *** [scripts/Makefile.build:243: device.o] Error 1\n")
makelog(COMPILE_ERR)
def sh(body, kernel="7.0.0-38-generic", status="iF ", cand=KV, built=False, extra_env=None):
    stubs = ('have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
             'run(){ echo "RUN $*" >> "$T/calls"; }\n'
             'uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
             'dpkg-query(){ case "$*" in *Status*) printf "%%s" "%s";; *Version*) printf "%%s" "%s";; esac; }\n'
             'apt-cache(){ printf "amneziawg-dkms:\\n  Installed: (none)\\n  Candidate: %s\\n"; }\n'
             'modinfo(){ %s; }\n'
             'AWG_MOD_FAILED="$T/awg-module-failed"; SWG_LIB_MODULES="$T/mods"; SWG_DKMS_TREE="$T/dkms"\n') % (kernel, status, KV, cand, "return 0" if built else "return 1")
    env = dict(os.environ, T=T, **(extra_env or {}))
    return subprocess.run(["bash", "-c", stubs + FUNCS + body], capture_output=True, text=True, env=env)
def calls():
    try:
        return open(T + "/calls").read() if os.path.exists(T + "/calls") else ""   # nothing run = no file
    finally:
        open(T + "/calls", "w").close()
def reset():
    for f in ("awg-module-failed", "calls"):
        if os.path.exists(T + "/" + f): os.remove(T + "/" + f)

print("[1] the record")
reset()
r = sh('awg_fail_note pkg V1; awg_fail_note src abc1234; awg_fail_note pkg V2; echo "pkg=$(awg_fail_get pkg) src=$(awg_fail_get src)"')
check("a fact for this kernel is kept with the others (pkg replaced, src kept)", "pkg=V2 src=abc1234" in r.stdout, r.stdout + r.stderr)
r = sh('awg_fail_get pkg && echo HAVE || echo NONE', kernel="7.0.0-40-generic")
check("another kernel's record is no record", "NONE" in r.stdout, r.stdout + r.stderr)

print("\n[2] awg_pkg_retry_due")
reset()
check("nothing recorded → due", "DUE" in sh('awg_pkg_retry_due && echo DUE || echo WAIT').stdout)
sh('awg_fail_note pkg %s' % KV)
check("the same version apt would install → not due", "WAIT" in sh('awg_pkg_retry_due && echo DUE || echo WAIT').stdout)
check("a newer amneziawg-dkms in the PPA → due", "DUE" in sh('awg_pkg_retry_due && echo DUE || echo WAIT', cand=KV.replace("0848", "0999")).stdout)
check("another kernel → due", "DUE" in sh('awg_pkg_retry_due && echo DUE || echo WAIT', kernel="7.0.0-40-generic").stdout)

print("\n[3] awg_src_retry_due")
reset(); sh('awg_fail_note src 4569c4c')
check("upstream still at that commit (full sha) → not due", "WAIT" in sh('awg_src_retry_due 4569c4c6abcdef0123456789 && echo DUE || echo WAIT').stdout)
check("upstream moved on → due", "DUE" in sh('awg_src_retry_due b72bb7a6aaaa && echo DUE || echo WAIT').stdout)
check("upstream cannot be asked (empty head) → not a reason to compile", "WAIT" in sh('awg_src_retry_due "" && echo DUE || echo WAIT').stdout)
reset()
check("nothing recorded → due", "DUE" in sh('awg_src_retry_due 4569c4c6 && echo DUE || echo WAIT').stdout)

print("\n[3b] awg_nothing_new — asked over the kinds that HAVE a record (code review: both were required)")
reset()
check("no record at all → something to try", "TRY" in sh('awg_nothing_new && echo NOTHING || echo TRY').stdout)
sh('awg_fail_note src 4569c4c')
check("a source build's record only (src), upstream unmoved → nothing new", "NOTHING" in sh('awg_module_head(){ echo 4569c4c6ff; }; awg_nothing_new && echo NOTHING || echo TRY').stdout)
check("…upstream moved → something to try", "TRY" in sh('awg_module_head(){ echo b72bb7a6; }; awg_nothing_new && echo NOTHING || echo TRY').stdout)
reset(); sh('awg_fail_note pkg %s' % KV)
check("a package record only (pkg), same candidate → nothing new", "NOTHING" in sh('awg_nothing_new && echo NOTHING || echo TRY').stdout)
check("…a newer candidate → something to try", "TRY" in sh('awg_nothing_new && echo NOTHING || echo TRY', cand=KV.replace("0848", "0999")).stdout)
reset()
r = sh('set -e; awg_fail_note src OLD; awg_fail_note src NEW; echo "SURVIVED src=$(awg_fail_get src)"')
check("awg_fail_note under set -e, nothing else left in the record (grep -v exits 1) — the run survives", "SURVIVED src=NEW" in r.stdout, r.stdout + r.stderr)

print("\n[4] awg_ppa_module_install, driven")
reset()
r = sh('awg_ppa_module_install && echo RC0 || echo RC1')
c = calls()
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("a compile failure is given up on (rc 1) and said in one line", "RC1" in r.stdout and "does not compile on kernel 7.0.0-38-generic" in r.stdout, r.stdout + r.stderr)
check("…the half-configured packages are removed (dpkg left clean), the tools kept", "RUN apt-get remove -y amneziawg-dkms amneziawg" in c, c)
check("…and the version AND the commit the PPA built are recorded", "pkg=" + KV in rec and "src=4569c4c" in rec, rec)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
check("the next run does not install (and compile) it again", "RC1" in r.stdout and "amneziawg-dkms amneziawg-tools" not in c and "not rebuilding" in r.stdout, r.stdout + c)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1', cand=KV.replace("0848", "0999")); c = calls()
check("a newer amneziawg-dkms is tried", "RUN apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" in c, c)
reset()
r = sh('awg_ppa_module_install && echo RC0 || echo RC1', status="ii ", built=True); c = calls()
check("CONTROL: a build that succeeded is not given up on", "RC0" in r.stdout and "remove" not in c and not os.path.exists(T + "/awg-module-failed"), r.stdout + c)
os.rmdir(T + "/mods/7.0.0-38-generic/build")
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
check("CONTROL: no headers for this kernel is a missing prerequisite, not a compile failure", "RC0" in r.stdout and "remove" not in c, r.stdout + c)
os.makedirs(T + "/mods/7.0.0-38-generic/build")

print("\n[4b] a build the box cut short is not a compile failure (IN-15)")
for name, log in (("a full disk: the assembler's \"No space left on device\"", NOSPACE), ("a killed compiler (OOM)", KILLED),
                  ("no DKMS build log at all", None),
                  ("a full disk mid-compile: gcc's own located `fatal error: error writing … No space left on device`", NOSPACE_CC),
                  ("a killed assembler: a located `fatal error: … Broken pipe` beside gcc's `Killed signal`", KILLED_AS)):
    reset(); makelog(log)
    r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
    check("%s → not removed, not recorded, not said as \"does not compile\"" % name,
          "remove" not in c and not os.path.exists(T + "/awg-module-failed") and "does not compile" not in r.stdout, r.stdout + c)
reset(); makelog(FATAL_HDR)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("FN-1: a header the newer kernel dropped (gcc's `file:line:col: fatal error: … No such file or directory`) → a compile "
      "failure: said, the packages removed (dpkg left clean), the version recorded",
      "RC1" in r.stdout and "does not compile on kernel 7.0.0-38-generic" in r.stdout and "RUN apt-get remove -y amneziawg-dkms amneziawg" in c
      and "pkg=" + KV in rec, r.stdout + c + rec)
reset(); makelog(COMPILE_ERR)
r = sh('awg_dkms_compile_failed && echo FAILED || echo NOT')
check("CONTROL: the compiler's own error in the log → a compile failure", "FAILED" in r.stdout, r.stdout + r.stderr)

print("\n[5] awg_build_from_source, driven")
SRCF = grab_all("awg_build_from_source")
def build(head):
    body = ('awg_tools_drive_3x(){ return 0; }\nawg_tools_old_why(){ :; }\nmodprobe(){ return 1; }\ndepmod(){ :; }\nensure_awg_headers_follow(){ :; }\n'
            'have(){ case "$1" in git|make|awg|awg-quick|dkms|modprobe) return 0;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
            'dkms(){ :; }\ngit_clone_depth1(){ echo "CLONE $1" >> "$T/calls"; return 1; }\n'
            'awg_module_head(){ echo %s; }\n' % head) + SRCF + 'awg_build_from_source && echo RC0 || echo RC1\n'
    return sh(body)
reset(); sh('awg_fail_note src 4569c4c')
r = build("4569c4c6aaaabbbb"); c = calls()
check("upstream still at the commit that did not compile → no clone, no compile", "kernel-module" not in c and "not building it again" in r.stdout, r.stdout + c)
r = build("b72bb7a6cccc"); c = calls()
check("upstream moved on → it is cloned and built", "CLONE https://github.com/amnezia-vpn/amneziawg-linux-kernel-module" in c, r.stdout + c)
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("a clone that failed (a slow link cut it off) is NOT recorded as a commit that does not compile",
      "src=b72bb7a6cccc" not in rec, rec)

print("\n[6] update.sh")
check("the heal answers in one line when nothing new can be tried",
      "the kernel module does not compile on $(uname -r) yet; tried again when a new kernel or a newer AmneziaWG build arrives" in UP)
check("the heal's one-line answer asks awg_nothing_new", "have amneziawg-go && awg_nothing_new; then" in UP)
check("the package follow never re-tries a version that did not compile here, and gives a failed upgrade up",
      "awg_pkg_retry_due || return 0   # this very version already did not compile" in UP and "if awg_dkms_compile_failed; then\n      awg_dkms_give_up; DID_UPDATE=yes" in UP)
check("its package route goes through awg_ppa_module_install (no install that leaves dpkg broken)", "if awg_ppa_module_install; then" in UP
      and "run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" not in UP)
for f in ("install-host.sh", "install-node.sh"):
    s = rd(f)
    check("%s: its package route goes through awg_ppa_module_install" % f, "awg_ppa_module_install && build_awg_module" in s
          and "run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" not in s)

print("")
if PERTURB_FATAL or PERTURB_VETO:
    _want = (lambda f: f.startswith("FN-1: a header")) if PERTURB_FATAL else (lambda f: "not removed, not recorded" in f and "fatal error" in f)
    _red = [f for f in FAILS if _want(f)]
    print("perturb: %s" % ("RED as it must be (%d), all [4b]" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB:
    _red = [f for f in FAILS if "not removed, not recorded" in f]
    print("perturb: %s" % ("RED as it must be (%d), all [4b]" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
