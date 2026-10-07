#!/usr/bin/env python3
"""Self-test — PR #218's udp_tunnel signature detection is put on the AmneziaWG module source, exactly once, only where needed.

amneziawg-linux-kernel-module picks the old (struct socket *) or new (struct sock *) setup_udp_tunnel_sock /
udp_tunnel_sock_release by kernel VERSION ("below 7.1.5 is old"). Ubuntu backported the new setup_udp_tunnel_sock into
7.0.0-38 — 26.04, and 24.04's HWE kernel — under an unchanged version, with udp_tunnel_sock_release left old. The module
stopped compiling there, and on an ordinary kernel upgrade the failed DKMS hook left linux-headers / linux-generic
unconfigured: apt broken for the whole box (bivlked/amneziawg-installer#325). PR #218 asks the compiler which signature
the kernel DECLARES, per function. Measured (tests/awg_compat_build_matrix.sh, real headers in containers, 2026-10-07):

  kernel                     header (setup / release)   unpatched   patched   detection == header
  Ubuntu 26.04 7.0.0-14      socket / socket            builds      builds    yes
  Ubuntu 26.04 7.0.0-38      sock   / socket            FAILS       builds    yes
  Ubuntu 24.04 6.8.0-146     socket / socket            builds      builds    yes
  Ubuntu 24.04 7.0.0-38 HWE  sock   / socket            FAILS       builds    yes
  Debian 13 6.12.111         socket / socket            builds      builds    yes
  Debian 12 6.1.0-53         socket / socket            builds      builds    yes
  Ubuntu 6.17.0-1030/1032    socket / socket            builds      builds    yes   (oem, the workstation)

What this drives:
  [1] the exact version-gated block is replaced by the detecting one (both functions, the defines) and marked
  [2] never twice (rc 2, file unchanged); a file whose block upstream already changed is left alone (rc 1)
  [3] awg_compat_patch_installed fixes every /usr/src/amneziawg-* tree that needs it, says so, and only in the run it did
  [4] the package route: a postinst build that failed on the shipped source is rebuilt after the fix (dpkg finished),
      and is NOT given up on; a build that still fails after the fix is (the record of tests/awg_module_failed_selftest)
  [5] the fix is applied on every path that builds: the package route, the source build, the update's source
      registration, the installers' "already working" return, every update, and after a package upgrade

Run: python3 tests/awg_compat_patch_selftest.py      (0 = pass)
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
C, UP, H, N = rd("lib/common.sh"), rd("update.sh"), rd("install-host.sh"), rd("install-node.sh")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
def grab_all(*names):
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -p AWG_COMPAT_MARK; declare -f "${@:2}"', "_",
                        os.path.join(ROOT, "lib/common.sh")] + list(names), capture_output=True, text=True)
    assert r.returncode == 0 and all((n + " ()") in r.stdout for n in names), "could not read %s" % (names,)
    return r.stdout + "\n"

OLD_BLOCK = ("#if LINUX_VERSION_CODE < KERNEL_VERSION(7, 1, 5)\n"
             "#include <net/udp_tunnel.h>\n"
             "#define setup_udp_tunnel_sock(net, sk, sock_cfg) setup_udp_tunnel_sock(net, sk->sk_socket, sock_cfg)\n"
             "#define udp_tunnel_sock_release(sk) udp_tunnel_sock_release(sk->sk_socket)\n"
             "#endif\n")
COMPAT = "/* upstream compat.h, abridged */\n#endif\n\n" + OLD_BLOCK + "\n#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 18, 0)\n#define WQ_PERCPU 0\n#endif\n"
T = tempfile.mkdtemp(prefix="awgcompat-")
FUNCS = grab_all("awg_compat_patch", "awg_compat_patch_installed", "awg_dpkg_recover", "awg_fail_get", "awg_fail_note",
                 "awg_pkg_retry_due", "awg_mod_built", "_awg_kbuild", "awg_dkms_compile_failed", "awg_dkms_give_up",
                 "awg_ppa_module_install")
STUBS = 'have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
def sh(body, env=None):
    return subprocess.run(["bash", "-c", STUBS + FUNCS + body], capture_output=True, text=True, env=dict(os.environ, T=T, **(env or {})))
def tree(name, text):
    d = os.path.join(T, "src", name, "compat"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "compat.h"), "w").write(text); return os.path.dirname(d)

print("[1] the block is replaced by the detecting one")
d = tree("one", COMPAT)
r = sh('awg_compat_patch "%s"; echo "rc=$?"' % d)
out = open(d + "/compat/compat.h").read()
check("patched now (rc 0)", "rc=0" in r.stdout, r.stdout + r.stderr)
check("…the version gate is gone", "KERNEL_VERSION(7, 1, 5)" not in out, out)
check("…each function asks the compiler which signature the kernel declares",
      "__builtin_types_compatible_p(typeof(&udp_tunnel_sock_release), void (*)(struct sock *))" in out
      and "__builtin_types_compatible_p(typeof(&setup_udp_tunnel_sock),\n\t\t\t\t\t  void (*)(struct net *, struct sock *, struct udp_tunnel_sock_cfg *))" in out, out)
check("…both old-form calls are kept for the kernels that declare them",
      "((void (*)(struct socket *))udp_tunnel_sock_release)(sk->sk_socket);" in out
      and "setup_udp_tunnel_sock)(net, sk->sk_socket, cfg);" in out, out)
check("…the module's calls are routed through it", "#define udp_tunnel_sock_release(sk) __compat_udp_tunnel_sock_release(sk)" in out
      and "#define setup_udp_tunnel_sock(net, sk, cfg) __compat_setup_udp_tunnel_sock(net, sk, cfg)" in out, out)
check("…marked, and the rest of the file untouched", "PR #218" in out and out.startswith("/* upstream compat.h, abridged */")
      and out.endswith("#define WQ_PERCPU 0\n#endif\n"), out)

print("\n[2] never twice; never over a block upstream changed")
before = open(d + "/compat/compat.h").read()
r = sh('awg_compat_patch "%s"; echo "rc=$?"' % d)
check("already patched → rc 2, file byte-identical", "rc=2" in r.stdout and open(d + "/compat/compat.h").read() == before, r.stdout)
fixed = COMPAT.replace("KERNEL_VERSION(7, 1, 5)", "KERNEL_VERSION(7, 2, 0)")   # upstream moved the gate (or fixed it)
d2 = tree("upstream", fixed)
r = sh('awg_compat_patch "%s"; echo "rc=$?"' % d2)
check("a block upstream changed → rc 1, file untouched", "rc=1" in r.stdout and open(d2 + "/compat/compat.h").read() == fixed, r.stdout)
r = sh('awg_compat_patch "%s/nonexistent"; echo "rc=$?"' % T)
check("no compat.h → rc 1", "rc=1" in r.stdout, r.stdout)
r = sh('DRYRUN=true; awg_compat_patch "%s"; echo "rc=$?"' % tree("dry", COMPAT))
check("a dry run says it would and writes nothing", "[skip] patch" in r.stdout and "KERNEL_VERSION(7, 1, 5)" in open(os.path.join(T, "src/dry/compat/compat.h")).read(), r.stdout)

print("\n[3] awg_compat_patch_installed over /usr/src")
shutil.rmtree(os.path.join(T, "usr"), ignore_errors=True)
for n, text in (("amneziawg-1.0.0", COMPAT), ("amneziawg-1.0.9", fixed)):
    p = os.path.join(T, "usr", n, "compat"); os.makedirs(p); open(p + "/compat.h", "w").write(text)
r = sh('awg_compat_patch_installed; echo "rc=$?"', {"SWG_USR_SRC": T + "/usr"})
check("the tree that needs it is fixed, and said", "rc=0" in r.stdout and "PR #218" in open(T + "/usr/amneziawg-1.0.0/compat/compat.h").read()
      and "INFO AmneziaWG: the module source now asks the kernel" in r.stdout, r.stdout + r.stderr)
check("…a tree upstream already changed is left alone", open(T + "/usr/amneziawg-1.0.9/compat/compat.h").read() == fixed)
r = sh('awg_compat_patch_installed; echo "rc=$?"', {"SWG_USR_SRC": T + "/usr"})
check("…and the next run has nothing to do (rc 1, silent)", "rc=1" in r.stdout and "INFO" not in r.stdout, r.stdout)

print("\n[4] the package route: a build that failed on the shipped source is rebuilt after the fix")
KV = "7.0.0-38-generic"
os.makedirs(T + "/mods/%s/build" % KV, exist_ok=True)
def ppa(builds_after_fix):
    shutil.rmtree(os.path.join(T, "usr"), ignore_errors=True)
    p = os.path.join(T, "usr", "amneziawg-1.0.0", "compat"); os.makedirs(p); open(p + "/compat.h", "w").write(COMPAT)
    for f in ("state", "awg-module-failed", "calls"):
        if os.path.exists(T + "/" + f): os.remove(T + "/" + f)
    body = ('uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
            'run(){ echo "RUN $*" >> "$T/calls"; case "$*" in *"dpkg --configure -a"*) %s;; esac; }\n'
            'dpkg(){ case "$1" in --audit) [ -f "$T/state" ] || echo "amneziawg-dkms half-configured";; esac; }\n'
            'dpkg-query(){ case "$*" in *Status*) [ -f "$T/state" ] && printf "ii " || printf "iF ";; *Version*) printf "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1";; esac; }\n'
            'apt-cache(){ printf "  Candidate: 1.0.0-0~202609140848+4569c4c~ubuntu26.04.1\\n"; }\n'
            'modinfo(){ [ -f "$T/state" ]; }\n'
            'AWG_MOD_FAILED="$T/awg-module-failed"; SWG_LIB_MODULES="$T/mods"; SWG_USR_SRC="$T/usr"\n'
            'awg_ppa_module_install && echo RC0 || echo RC1\n') % (KV, 'touch "$T/state"' if builds_after_fix else ':')
    r = sh(body)
    c = open(T + "/calls").read() if os.path.exists(T + "/calls") else ""
    return r, c
r, c = ppa(True)
check("fixed source, dpkg finished → the module builds and nothing is given up on",
      "RC0" in r.stdout and "dpkg --configure -a" in c and "remove" not in c and not os.path.exists(T + "/awg-module-failed"), r.stdout + r.stderr + c)
r, c = ppa(False)
check("still failing after the fix → given up on (packages removed, record kept)",
      "RC1" in r.stdout and "apt-get remove -y amneziawg-dkms amneziawg" in c and os.path.exists(T + "/awg-module-failed"), r.stdout + c)

print("\n[5] every path that builds applies it")
fb = C[C.index("\nawg_build_from_source(){"):]
check("the source build fixes its clone before building it",
      'awg_compat_patch "$w/mod/src"' in fb[:fb.index("\n}\n")])
fr = C[C.index("\nawg_dkms_register_source(){"):]
check("the update's source registration fixes its clone before registering it",
      'awg_compat_patch "$w/mod/src"' in fr[:fr.index("\n}\n")] and fr.index('awg_compat_patch "$w/mod/src"') < fr.index("awg_dkms_register_dir"))
for f, s in (("install-host.sh", H), ("install-node.sh", N)):
    check("%s: a module that works today still gets its source fixed for the next kernel" % f,
          "awg_compat_patch_installed >/dev/null || true          # …its source fixed for the NEXT kernel (PR #218)" in s)
check("update.sh: every update fixes the source and finishes dpkg", "if ! $DRYRUN && awg_compat_patch_installed; then\n    DID_UPDATE=yes; awg_dpkg_recover || true" in UP)
check("update.sh: a package upgrade is judged only after the fix", "&& ! { awg_compat_patch_installed && awg_dpkg_recover; }; then" in UP)

print("")
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
