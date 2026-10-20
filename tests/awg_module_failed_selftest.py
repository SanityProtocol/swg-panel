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
      at all — is not a compile failure: not recorded (it was given up for good, even past `update -f`) — not even where the
      cut-short build left the compiler's own located `fatal error:` (a full disk, a killed assembler). (VERIFY1-B1) …but it
      is removed for now all the same, said as not finished: left half-configured while the fault lasted (a disk that stays
      full, a compiler OOM-killed on every try), every apt run on the box failed — and the next run tries it again.
      (FN-1) gcc's located `fatal error:` for a header the newer kernel dropped IS one: removed + recorded (`: error: `
      alone read it as transient, and the package stayed half-configured between updates)
  [4c] (1.8.9 qualification IN-12(a)) the give-up's removal waits for dpkg's lock (unattended-upgrades) and records
      the version only once amneziawg-dkms is really gone — one that lost the lock is said and tried again next run (it
      was recorded as given up and never retried: half-configured for good)
  [4d] (IN-12(e)) a stale amneziawg.ko for this kernel (an old `make install`, a source build beside the package) does not
      hide a package whose build failed: half-configured + the compiler's error = given up (it stayed half-configured,
      recompiled on every update)
  [4e] (1.8.9 qualification VERIFY2-VMB N4) what is said after a build the box cut short: the give-up's line says the package
      is removed for now and the next update tries again (it said "awg interfaces use the userspace datapath" while awg0 ran
      on the module still loaded), and tells its caller only once the package is gone; update.sh's heal then closes with
      that — not "AmneziaWG healed — running the slower USERSPACE datapath" and "install matching linux-headers", neither
      true there (the headers were installed, the compiler had run out of memory); the package follow's note, likewise
  [4f] (1.8.9 qualification R2 INST-4) a module that COMPILES and fails at modpost — a symbol this kernel does not export
      (`ERROR: modpost: "…" […] undefined!`), or exports in a namespace the module does not import — is a compile failure:
      removed + recorded, not built again (read as the box's, it was removed, never recorded and built again on every
      update and install). The make.log lines are kbuild's own, captured on 6.17.0-1032-oem. CONTROL: a full disk under
      modpost (its perror, `amneziawg.mod.c: No space left on device` — no `ERROR: modpost:`) is still the box's
  [5] awg_build_from_source, driven: upstream still at the commit that did not compile → no clone, no compile; moved on →
      it builds. (INST-4) Its own build failing at modpost: the commit recorded and the DKMS registration this run made
      dropped, as for the compiler's own error (CONTROL); a killed compiler is not recorded (CONTROL)
  [6] update.sh: the heal answers in one line when nothing new can be tried, and both routes ask the record

Run: python3 tests/awg_module_failed_selftest.py      (0 = pass)
     --perturb   awg_dkms_compile_failed judges without the build log again (52aa9c4) → RED on [4b] (and [4d]: it had both;
                 + [4f]'s full-disk CONTROL)
     --perturb-fatal   …drops gcc's located `fatal error:` again (84e36bf read `: error: ` alone) → RED on [4b]'s dropped header only
     --perturb-veto    …judges a located `fatal error:` without asking whether the box cut the build short → RED on [4b]
     --perturb-stale   …asks for no module file for this kernel again (e66018f) → RED on [4d] only
     --perturb-lock    the give-up as e66018f shipped it: no lock wait, the version recorded whatever the removal did → RED on [4c] only
     --perturb-transient  a half-configured build the box cut short is left as it is again (q189-int2) → RED on [4b] (+ [4e]'s
                       give-up checks and [4f]'s full-disk CONTROL, which drive that path)
     --perturb-words   the words as q189-int3 shipped them (lib's line, no AWG_GAVE_UP, the heal's usual close) → RED on [4e] only
     --perturb-modpost      awg_dkms_compile_failed without modpost's `ERROR: modpost:` again (6cd65eb9) → RED on [4f] only
     --perturb-modpost-src  the source route's matcher without it again (6cd65eb9) → RED on [5]'s modpost check only
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
C, UP = rd("lib/common.sh"), rd("update.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
_LIB = os.path.join(ROOT, "lib/common.sh")
if "--perturb-transient" in sys.argv[1:]:   # q189-int2: a half-configured build that was not a compile failure is left as it is
    _s = rd("lib/common.sh"); _a = "  if awg_dkms_pending; then awg_dkms_give_up transient; return 1; fi\n"
    assert _s.count(_a) == 2, "perturbation anchor missing — would FALSE-PASS"
    _fd, _LIB = tempfile.mkstemp(prefix="awgfail-lib-", suffix=".sh"); os.write(_fd, _s.replace(_a, "").encode()); os.close(_fd)
if "--perturb-lock" in sys.argv[1:]:   # the give-up as e66018f shipped it: no lock wait, the version recorded whatever the removal did
    _s = rd("lib/common.sh")
    _a = "run apt-get remove -y -o DPkg::Lock::Timeout=180 amneziawg-dkms amneziawg"
    _i = _s.find("  # Recorded only once it is gone:"); _j = _s.find("  esac\n", _i) + len("  esac\n")
    assert _s.count(_a) == 1 and _i > 0 and "could not be removed now" in _s[_i:_j], "perturbation anchor missing — would FALSE-PASS"
    _s = (_s[:_i] + _s[_j:]).replace(_a, "run apt-get remove -y amneziawg-dkms amneziawg")
    _fd, _LIB = tempfile.mkstemp(prefix="awgfail-lib-", suffix=".sh"); os.write(_fd, _s.encode()); os.close(_fd)
if "--perturb-words" in sys.argv[1:]:   # q189-int3's words: "userspace datapath" in the give-up, the heal's usual close
    _s = rd("lib/common.sh")
    _a = "so the package is removed for now, keeping the package manager usable, and the next update tries again."
    _b = '  [ "${1:-}" = transient ] && { AWG_GAVE_UP=transient; return 0; }\n'
    assert _s.count(_a) == 1 and _s.count(_b) == 1, "perturbation anchor missing — would FALSE-PASS"
    _s = _s.replace(_a, "so the package is removed, keeping the package manager usable; awg interfaces use the userspace datapath, and the next update tries again.")
    _s = _s.replace(_b, '  [ "${1:-}" = transient ] && return 0\n')
    _fd, _LIB = tempfile.mkstemp(prefix="awgfail-lib-", suffix=".sh"); os.write(_fd, _s.encode()); os.close(_fd)
    _c = ('  elif have awg && have awg-quick && have amneziawg-go && [ "${AWG_GAVE_UP:-}" = transient ]; then   # nothing healed (above)\n'
          '    DID_UPDATE=yes; note "AmneziaWG: the kernel module\'s package is removed for now — its build did not finish on this box; the next update tries again"\n')
    assert UP.count(_c) == 1, "perturbation anchor missing — would FALSE-PASS"
    UP = UP.replace(_c, "")
def grab_all(*names):
    """The functions as bash itself defines them: lib/common.sh sourced (definitions only), then `declare -f`."""
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f "${@:2}"', "_", _LIB] + list(names),
                       capture_output=True, text=True)
    assert r.returncode == 0 and all((n + " ()") in r.stdout for n in names), "could not read %s from lib/common.sh" % (names,)
    return r.stdout + "\n"

PERTURB = "--perturb" in sys.argv[1:]
PERTURB_FATAL = "--perturb-fatal" in sys.argv[1:]
PERTURB_VETO = "--perturb-veto" in sys.argv[1:]
PERTURB_STALE = "--perturb-stale" in sys.argv[1:]
PERTURB_LOCK = "--perturb-lock" in sys.argv[1:]
PERTURB_MODPOST = "--perturb-modpost" in sys.argv[1:]
PERTURB_MODPOST_SRC = "--perturb-modpost-src" in sys.argv[1:]
T = tempfile.mkdtemp(prefix="awgfail-")
os.makedirs(T + "/bin"); os.makedirs(T + "/mods/7.0.0-38-generic/build")
KV = "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1"
FUNCS = grab_all("awg_fail_get", "awg_fail_note", "awg_module_head", "awg_src_retry_due", "awg_pkg_retry_due", "awg_nothing_new", "awg_mod_built",
                 "_awg_kbuild", "awg_dkms_compile_failed", "awg_dkms_pending", "awg_dkms_give_up", "awg_ppa_module_install")
_LOGS = '"${SWG_DKMS_TREE:-/var/lib/dkms}"/amneziawg/*/build/make.log'
_ERR = "grep -qsE ': error: |:[0-9]+: fatal error: |^ERROR: modpost: ' " + _LOGS
_VETO = " && ! grep -qsE 'No space left on device|Killed signal|internal compiler error: Killed' " + _LOGS
if PERTURB:   # the judgement as 52aa9c4 shipped it: half-configured + no module file, whatever the build log says
    _old = _ERR + _VETO
    assert FUNCS.count(_old) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_old, "! awg_mod_built")
if PERTURB_STALE:   # as e66018f shipped it: a module file for this kernel, any module file, means "it compiled"
    assert FUNCS.count(_ERR + _VETO) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_ERR + _VETO, "! awg_mod_built && " + _ERR + _VETO)
if PERTURB_FATAL:   # gcc's located `fatal error:` dropped again (84e36bf read `: error: ` alone)
    assert FUNCS.count(_ERR) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_ERR, "grep -qsE ': error: |^ERROR: modpost: ' " + _LOGS)
if PERTURB_VETO:    # a located `fatal error:` counted even where the box cut the build short
    assert FUNCS.count(_VETO) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_VETO, "")
if PERTURB_MODPOST:   # as 6cd65eb9 shipped it: modpost's `ERROR: modpost:` is not a compile failure
    assert FUNCS.count(_ERR) == 1, "perturbation anchor missing — would FALSE-PASS"
    FUNCS = FUNCS.replace(_ERR, "grep -qsE ': error: |:[0-9]+: fatal error: ' " + _LOGS)
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
# It COMPILED, and modpost refused it (1.8.9 qualification R2 INST-4) — kbuild's own lines, captured on 6.17.0-1032-oem from a
# module calling udp_lib_get_port (declared in net/udp.h, not exported) and one calling crypto_cipher_setkey (exported in
# CRYPTO_INTERNAL) without importing the namespace; the paths are DKMS's
_MP = ("DKMS make.log for amneziawg-1.0.0 for kernel 7.0.0-38-generic (x86_64)\n"
       "make[1]: Entering directory '/var/lib/dkms/amneziawg/1.0.0/build'\n"
       "  CC [M]  socket.o\n  LD [M]  amneziawg.o\n  MODPOST Module.symvers\n"
       "WARNING: modpost: missing MODULE_DESCRIPTION() in amneziawg.o\n%s"
       "make[3]: *** [/usr/src/linux-headers-7.0.0-38-generic/scripts/Makefile.modpost:147: Module.symvers] Error 1\n"
       "make[2]: *** [/usr/src/linux-headers-7.0.0-38-generic/Makefile:1967: modpost] Error 2\n")
MODPOST = _MP % 'ERROR: modpost: "udp_lib_get_port" [amneziawg.ko] undefined!\n'
MODPOST_NS = _MP % "ERROR: modpost: module amneziawg uses symbol crypto_cipher_setkey from namespace CRYPTO_INTERNAL, but does not import it.\n"
MODPOST_NOSPACE = _MP % "amneziawg.mod.c: No space left on device\n"   # modpost's own write, the disk full: its perror, no ERROR
makelog(COMPILE_ERR)
def sh(body, kernel="7.0.0-38-generic", status="iF ", cand=KV, built=False, extra_env=None):
    stubs = ('have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
             'run(){ echo "RUN $*" >> "$T/calls"; case "$*" in *"apt-get remove"*|*"dpkg --remove"*) '
             '[ -e "$T/locked" ] && return 100; touch "$T/removed";; esac; }\n'   # the lock held (unattended-upgrades) → 100
             'uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
             'dpkg-query(){ case "$*" in *Status*) if [ -e "$T/removed" ]; then printf "rc "; else printf "%%s" "%s"; fi;; '
             '*Version*) printf "%%s" "%s";; esac; }\n'
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
    for f in ("awg-module-failed", "calls", "removed", "locked"):
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
check("…the half-configured packages are removed (dpkg left clean), the tools kept",
      re.search(r"RUN apt-get remove -y (-o \S+ )?amneziawg-dkms amneziawg", c), c)
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
check("CONTROL: no headers for this kernel is a missing prerequisite, not a compile failure — not recorded (a half-configured "
      "package is still not left behind: VERIFY1-B1)", "does not compile" not in r.stdout and not os.path.exists(T + "/awg-module-failed"),
      r.stdout + c)
os.makedirs(T + "/mods/7.0.0-38-generic/build")

print("\n[4b] a build the box cut short is not a compile failure (IN-15) — but it is not left half-configured either (VERIFY1-B1)")
for name, log in (("a full disk: the assembler's \"No space left on device\"", NOSPACE), ("a killed compiler (OOM)", KILLED),
                  ("no DKMS build log at all", None),
                  ("a full disk mid-compile: gcc's own located `fatal error: error writing … No space left on device`", NOSPACE_CC),
                  ("a killed assembler: a located `fatal error: … Broken pipe` beside gcc's `Killed signal`", KILLED_AS)):
    reset(); makelog(log)
    r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
    check("%s → removed for now (dpkg left clean), NOT recorded, said as not finished — never \"does not compile\"" % name,
          "RC1" in r.stdout and "apt-get remove -y" in c and not os.path.exists(T + "/awg-module-failed")
          and "does not compile" not in r.stdout and "did not finish on this box" in r.stdout, r.stdout + c)
    r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
    check("%s → …and the next run tries it again" % name, "RUN apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" in c, r.stdout + c)
reset(); makelog(FATAL_HDR)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("FN-1: a header the newer kernel dropped (gcc's `file:line:col: fatal error: … No such file or directory`) → a compile "
      "failure: said, the packages removed (dpkg left clean), the version recorded",
      "RC1" in r.stdout and "does not compile on kernel 7.0.0-38-generic" in r.stdout and "apt-get remove -y" in c
      and "pkg=" + KV in rec, r.stdout + c + rec)
reset(); makelog(COMPILE_ERR)
r = sh('awg_dkms_compile_failed && echo FAILED || echo NOT')
check("CONTROL: the compiler's own error in the log → a compile failure", "FAILED" in r.stdout, r.stdout + r.stderr)

print("\n[4c] the give-up waits for dpkg's lock, and records only what it removed (IN-12(a))")
reset(); makelog(COMPILE_ERR); open(T + "/locked", "w").close()
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
check("the removal waits for dpkg's lock (-o DPkg::Lock::Timeout=180)", "RUN apt-get remove -y -o DPkg::Lock::Timeout=180 amneziawg-dkms amneziawg" in c, c)
check("…lost it all the same (still half-configured) → NOT recorded as given up, and said: the next run tries again",
      not os.path.exists(T + "/awg-module-failed") and "could not be removed now" in r.stdout, r.stdout + c)
os.remove(T + "/locked")
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("…and the next run, the lock free, gives it up: removed, recorded", "apt-get install -y amneziawg amneziawg-dkms" in c
      and "remove" in c and "pkg=" + KV in rec, r.stdout + c + rec)

print("\n[4d] a stale module file for this kernel does not hide a package that did not compile (IN-12(e))")
reset(); makelog(COMPILE_ERR)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1', built=True); c = calls()
rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
check("half-configured + the compiler's error, an amneziawg.ko for this kernel on disk → given up: removed, recorded",
      "RC1" in r.stdout and re.search(r"RUN apt-get remove -y (-o \S+ )?amneziawg-dkms amneziawg", c) and "pkg=" + KV in rec,
      r.stdout + c + rec)
reset()
r = sh('awg_ppa_module_install && echo RC0 || echo RC1', status="ii ", built=True); c = calls()
check("CONTROL: the package built (ii) → kept, whatever the build log of an earlier attempt says",
      "RC0" in r.stdout and "remove" not in c, r.stdout + c)

print("\n[4e] what is said after a build the box cut short (VERIFY2-VMB N4)")
reset(); makelog(KILLED)
r = sh('awg_ppa_module_install; echo "GAVE=${AWG_GAVE_UP:-}"'); c = calls()
_gl = [l for l in r.stdout.splitlines() if "did not finish on this box" in l]
check("(N4) the give-up's line: removed for now, the next update tries again — no claim about the datapath",
      len(_gl) == 1 and "removed for now" in _gl[0] and "the next update tries again" in _gl[0] and "userspace" not in _gl[0], r.stdout)
check("(N4) …and it tells its caller (AWG_GAVE_UP=transient) once the package is gone", "GAVE=transient" in r.stdout and "apt-get remove" in c,
      r.stdout + c)
reset(); makelog(KILLED); open(T + "/locked", "w").close()
r = sh('awg_ppa_module_install; echo "GAVE=${AWG_GAVE_UP:-}"'); calls()
check("(N4) CONTROL: a removal that lost dpkg's lock tells it nothing (the package is still there)",
      "GAVE=\n" in r.stdout + "\n" and "could not be removed now" in r.stdout, r.stdout)
os.remove(T + "/locked")
_i = UP.index('  if modprobe amneziawg 2>/dev/null; then\n    DID_UPDATE=yes; ok "AmneziaWG healed — kernel datapath')
CLOSE = UP[_i:UP.index("\n  fi\n", _i) + len("\n  fi\n")]
def close(gave):
    body = ('set -uo pipefail\nDID_UPDATE=no; DID_FAIL=no\nok(){ echo "OK $*"; }\nnote(){ echo "NOTE $*"; }\nwarn(){ echo "WARN $*"; }\n'
            'modprobe(){ return 1; }\nhave(){ case "$1" in awg|awg-quick|amneziawg-go) return 0;; esac; return 1; }\n'
            'awg_key_refused_here(){ return 1; }\nawg_fail_get(){ return 1; }\nawg_tools_drive_3x(){ return 0; }\nawg_tools_old_why(){ echo old; }\n'
            'uname(){ echo 7.0.0-38-generic; }\n%s\n%secho "DID_UPDATE=$DID_UPDATE DID_FAIL=$DID_FAIL"\n') % ("AWG_GAVE_UP=transient" if gave else "", CLOSE)
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True)
r = close(True)
check("(N4) update.sh's heal after it: \"removed for now … the next update tries again\" — not \"healed\", not \"userspace\", not \"linux-headers\"",
      "NOTE AmneziaWG: the kernel module's package is removed for now" in r.stdout and "the next update tries again" in r.stdout
      and "healed" not in r.stdout and "userspace" not in r.stdout.lower() and "linux-headers" not in r.stdout
      and "DID_UPDATE=yes DID_FAIL=no" in r.stdout, r.stdout + r.stderr)
r = close(False)
check("(N4) CONTROL: no such give-up in this run → the usual close (userspace, and the headers advice where it fits)",
      "OK AmneziaWG healed — running the slower USERSPACE datapath" in r.stdout and "install matching linux-headers" in r.stdout, r.stdout + r.stderr)
_fl = [l for l in UP.splitlines() if "module build did not finish on this box" in l]
check("(N4) the package follow's note after it: removed for now, tried again — no \"userspace datapath\"",
      len(_fl) == 1 and "removed for now" in _fl[0] and "userspace" not in _fl[0], _fl)

print("\n[4f] a module that COMPILES and fails at modpost is a compile failure too (1.8.9 qualification R2 INST-4)")
for name, log in (("a symbol this kernel does not export (`ERROR: modpost: \"…\" […] undefined!`)", MODPOST),
                  ("a symbol in a namespace the module does not import", MODPOST_NS)):
    reset(); makelog(log)
    r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
    rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
    check("(INST-4) %s → said as not compiling here, the packages removed (dpkg left clean), the version recorded — never "
          "\"did not finish on this box\"" % name, "RC1" in r.stdout and "does not compile on kernel 7.0.0-38-generic" in r.stdout
          and "apt-get remove -y" in c and "pkg=" + KV in rec and "did not finish on this box" not in r.stdout, r.stdout + c + rec)
    r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
    check("(INST-4) %s → …and the next run does not build it again" % name,
          "RC1" in r.stdout and "amneziawg-dkms amneziawg-tools" not in c and "not rebuilding" in r.stdout, r.stdout + c)
reset(); makelog(MODPOST_NOSPACE)
r = sh('awg_ppa_module_install && echo RC0 || echo RC1'); c = calls()
check("CONTROL: the disk full under modpost (its perror, no `ERROR: modpost:`) → removed for now (dpkg left clean), NOT recorded, "
      "said as not finished", "RC1" in r.stdout and "apt-get remove -y" in c and not os.path.exists(T + "/awg-module-failed")
      and "does not compile" not in r.stdout and "did not finish on this box" in r.stdout, r.stdout + c)

print("\n[5] awg_build_from_source, driven")
SRCF = grab_all("awg_build_from_source")
_SRC_ERR = "grep -qE ': error: |^ERROR: modpost: ' \"$w/mod.log\""
if PERTURB_MODPOST_SRC:   # as 6cd65eb9 shipped it: the compiler's `: error: ` only
    assert SRCF.count(_SRC_ERR) == 1, "perturbation anchor missing — would FALSE-PASS"
    SRCF = SRCF.replace(_SRC_ERR, "grep -q ': error: ' \"$w/mod.log\"")
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
# (INST-4) its own build failing: the clone is there, DKMS's build of it failed (dkms says only where its log is), and the plain
# `make` beside it writes kbuild's lines into mod.log
def build_failed(log):
    open(T + "/kbuild.log", "w").write(log.split("\n", 1)[1])   # kbuild's lines, without DKMS's header
    body = ('awg_tools_drive_3x(){ return 0; }\nawg_tools_old_why(){ :; }\nmodprobe(){ return 1; }\nensure_awg_headers_follow(){ :; }\n'
            'have(){ case "$1" in git|make|awg|awg-quick|dkms|modprobe) return 0;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
            'awg_mod_key_rejected(){ return 1; }\nawg_compat_patch(){ :; }\ndkms(){ :; }\nawg_module_head(){ echo d00dfeed1234; }\n'
            'git_clone_depth1(){ echo "CLONE $1" >> "$T/calls"; mkdir -p "$2/src"; '
            'printf \'PACKAGE_NAME="amneziawg"\\nPACKAGE_VERSION="1.0.0"\\n\' > "$2/src/dkms.conf"; }\n'
            'awg_dkms_register_dir(){ echo "REGISTER $1" >> "$T/calls"; printf "Error! Bad return status for module build on kernel: '
            '7.0.0-38-generic (x86_64)\\nConsult /var/lib/dkms/amneziawg/1.0.0/build/make.log for more information.\\n"; return 10; }\n'
            'run(){ echo "RUN $*" >> "$T/calls"; case "$1" in make) cat "$T/kbuild.log"; return 2;; esac; }\n') + SRCF + \
           'awg_build_from_source && echo RC0 || echo RC1\n'
    return sh(body)
for name, log, recorded in (("(INST-4 src) its build failing at modpost (`ERROR: modpost: \"…\" […] undefined!`)", MODPOST, True),
                        ("CONTROL: its build failing on the compiler's own error", COMPILE_ERR, True),
                        ("CONTROL: its compiler killed (OOM)", KILLED, False)):
    reset(); r = build_failed(log); c = calls()
    rec = open(T + "/awg-module-failed").read() if os.path.exists(T + "/awg-module-failed") else ""
    if recorded:
        check("%s → the commit recorded, and the DKMS registration this run made dropped (no rebuild at every kernel install)" % name,
              "RC1" in r.stdout and "REGISTER" in c and "src=d00dfeed1234" in rec and "RUN dkms remove -m amneziawg -v 1.0.0 --all" in c,
              r.stdout + c + rec)
    else:
        check("%s → NOT recorded: tried again next time" % name, "RC1" in r.stdout and "REGISTER" in c and "src=d00dfeed1234" not in rec,
              r.stdout + c + rec)

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
if "--perturb-words" in sys.argv[1:]:
    _red = [f for f in FAILS if "(N4)" in f]
    print("perturb: %s" % ("RED as it must be (%d), all [4e]" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if "--perturb-transient" in sys.argv[1:]:   # [4e]'s give-up checks drive the same path: red with it
    _red = [f for f in FAILS if "removed for now" in f or f.startswith("(N4)")]
    print("perturb: %s" % ("RED as it must be (%d), all [4b] + [4e]'s give-up + [4f]'s CONTROL" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_STALE or PERTURB_LOCK:
    _want = (lambda f: f.startswith("half-configured + the compiler")) if PERTURB_STALE else (lambda f: "lock" in f or "lost it" in f)
    _red = [f for f in FAILS if _want(f)]
    print("perturb: %s" % ("RED as it must be (%d), all %s" % (len(_red), "[4d]" if PERTURB_STALE else "[4c]") if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_FATAL or PERTURB_VETO:
    _want = (lambda f: f.startswith("FN-1: a header")) if PERTURB_FATAL else (lambda f: ("NOT recorded" in f or "tries it again" in f) and "fatal error" in f)
    _red = [f for f in FAILS if _want(f)]
    print("perturb: %s" % ("RED as it must be (%d), all [4b]" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_MODPOST or PERTURB_MODPOST_SRC:
    _p = "(INST-4 src) " if PERTURB_MODPOST_SRC else "(INST-4) "
    _red = [f for f in FAILS if f.startswith(_p)]
    print("perturb: %s" % ("RED as it must be (%d), all %s" % (len(_red), "[5]'s modpost check" if PERTURB_MODPOST_SRC else "[4f]")
                           if _red and len(_red) == len(FAILS) else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB:   # 52aa9c4 had both defects: the build log unread ([4b]) and any module file read as "it compiled" ([4d])
    _red = [f for f in FAILS if "NOT recorded" in f or "tries it again" in f or f.startswith("half-configured + the compiler")
            or f.startswith("(N4)")]   # [4e]'s give-up checks drive the transient path this plant takes away
    print("perturb: %s" % ("RED as it must be (%d), all [4b] + [4d]'s stale module + [4e]'s give-up + [4f]'s CONTROL" % len(_red) if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
