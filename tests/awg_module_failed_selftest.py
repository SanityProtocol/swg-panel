#!/usr/bin/env python3
"""Self-test — an AmneziaWG kernel module that does not COMPILE is remembered, not retried, and dpkg is left clean.

Ubuntu 26.04, kernel 7.0.0-38 (client report 2026-10-06): upstream's module did not build on that kernel at all. The
installer compiled it four or five times per pass (the package's postinst, `dkms autoinstall` twice, a --reinstall, every
kernel, then from source), every update did all of it again, and the failed amneziawg-dkms was left half-configured —
every later `apt install` on the box ended in "E: Sub-process /usr/bin/dpkg returned an error code (1)".

  [1] the record: one per kernel — a fact for this kernel is kept with the others, another kernel's record is no record
  [2] awg_pkg_retry_due: retried only when apt would install a newer amneziawg-dkms, or on another kernel
  [3] awg_src_retry_due: retried only when upstream's head has moved (an unknown head is not a reason to compile)
  [4] awg_ppa_module_install, driven: a compile failure (headers here, package half-configured, no module file) removes
      the two packages, keeps the tools, records the version AND the commit the PPA built — and the next run does not
      install it again; a newer package does. CONTROLS: a build that succeeded, and one that failed for want of headers,
      are not given up on
  [5] awg_build_from_source, driven: upstream still at the commit that did not compile → no clone, no compile; moved on →
      it builds
  [6] update.sh: the heal answers in one line when nothing new can be tried, and both routes ask the record

Run: python3 tests/awg_module_failed_selftest.py      (0 = pass)
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

T = tempfile.mkdtemp(prefix="awgfail-")
os.makedirs(T + "/bin"); os.makedirs(T + "/mods/7.0.0-38-generic/build")
KV = "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1"
FUNCS = grab_all("awg_fail_get", "awg_fail_note", "awg_module_head", "awg_src_retry_due", "awg_pkg_retry_due", "awg_mod_built",
                 "_awg_kbuild", "awg_dkms_compile_failed", "awg_dkms_give_up", "awg_ppa_module_install")
def sh(body, kernel="7.0.0-38-generic", status="iF ", cand=KV, built=False, extra_env=None):
    stubs = ('have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
             'run(){ echo "RUN $*" >> "$T/calls"; }\n'
             'uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
             'dpkg-query(){ case "$*" in *Status*) printf "%%s" "%s";; *Version*) printf "%%s" "%s";; esac; }\n'
             'apt-cache(){ printf "amneziawg-dkms:\\n  Installed: (none)\\n  Candidate: %s\\n"; }\n'
             'modinfo(){ %s; }\n'
             'AWG_MOD_FAILED="$T/awg-module-failed"; SWG_LIB_MODULES="$T/mods"\n') % (kernel, status, KV, cand, "return 0" if built else "return 1")
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

print("\n[6] update.sh")
check("the heal answers in one line when nothing new can be tried", "&& ! awg_pkg_retry_due && ! awg_src_retry_due; then" in UP
      and "the kernel module does not compile on $(uname -r) yet; tried again when a new kernel or a newer AmneziaWG build arrives" in UP)
check("its package route goes through awg_ppa_module_install (no install that leaves dpkg broken)", "if awg_ppa_module_install; then" in UP
      and "run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" not in UP)
for f in ("install-host.sh", "install-node.sh"):
    s = rd(f)
    check("%s: its package route goes through awg_ppa_module_install" % f, "awg_ppa_module_install && build_awg_module" in s
          and "run apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" not in s)

print("")
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
