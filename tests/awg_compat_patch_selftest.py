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
      and is NOT given up on; a build that still fails after the fix is (the record of tests/awg_module_failed_selftest).
      (1.8.9 qualification IN-12(b)) dpkg --configure -a runs with no terminal (stdin /dev/null) and keeps a changed
      config file (--force-confdef --force-confold): a pending package's conffile question waited unseen
  [4c] (1.8.9 qualification IN-10) the --reinstall fallback — build_awg_module (install-node AND install-host, driven) and
      update.sh's heal: a patched module that built but will not load (an LXC guest) is reinstalled, which puts the source
      back AS SHIPPED and fails its build on 7.0.0-38 — the source is fixed again, dpkg finished (configured), and a build
      that still does not compile is given up (removed, recorded; build_awg_module says 1). It was left half-configured
  [5] the fix is applied on every path that builds: the package route, the source build, the update's source
      registration, the installers' "already working" return, every update, and after a package upgrade

Run: python3 tests/awg_compat_patch_selftest.py      (0 = pass)
     --perturb-reinstall the fallback as e66018f shipped it (a bare --reinstall) → RED on [4c] only
     --perturb-confold   awg_dpkg_recover as e66018f shipped it (the terminal as stdin, no conffile answer) → RED on [4]'s dpkg line only
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
PERTURB_CONFOLD = "--perturb-confold" in sys.argv[1:]
PERTURB_REINSTALL = "--perturb-reinstall" in sys.argv[1:]
_LIB = os.path.join(ROOT, "lib/common.sh")
if PERTURB_CONFOLD or PERTURB_REINSTALL:
    if PERTURB_CONFOLD:
        _a, _b = "dpkg --force-confdef --force-confold --configure -a </dev/null >/dev/null", "dpkg --configure -a >/dev/null"
    else:   # the bare --reinstall: nothing after it to fix the source, recover or give up — the tail awg_dkms_reinstall
        # shares with awg_ppa_module_install (so anchored on its own reinstall line), with 2ed03500's pending give-up
        _a = ("  run apt-get install --reinstall -y amneziawg-dkms 2>/dev/null || true\n"
              "  $DRYRUN && return 0\n  if awg_compat_patch_installed; then awg_dpkg_recover || true; fi\n"
              "  if awg_dkms_compile_failed; then awg_dkms_give_up; return 1; fi\n"
              "  if awg_dkms_pending; then awg_dkms_give_up transient; return 1; fi\n  return 0; }\n")
        _b = "  run apt-get install --reinstall -y amneziawg-dkms 2>/dev/null || true\n  return 0; }\n"
    assert C.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    _fd, _LIB = tempfile.mkstemp(prefix="awgcompat-lib-", suffix=".sh")
    os.write(_fd, C.replace(_a, _b).encode()); os.close(_fd)
def grab_all(*names):
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -p AWG_COMPAT_MARK; declare -f "${@:2}"', "_",
                        _LIB] + list(names), capture_output=True, text=True)
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
                 "awg_ppa_module_install", "awg_dkms_reinstall", "awg_mod_key_rejected")
STUBS = 'have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
def sh(body, env=None):   # stdin a pipe, never a terminal or /dev/null: what a command ran with is then what it was given
    return subprocess.run(["bash", "-c", STUBS + FUNCS + body], capture_output=True, text=True, env=dict(os.environ, T=T, **(env or {})),
                          input="")
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
    for f in ("state", "awg-module-failed", "calls", "removed"):
        if os.path.exists(T + "/" + f): os.remove(T + "/" + f)
    # DKMS's build log of the attempt that failed: the COMPILER's error, which is what makes it "does not compile" (IN-15)
    os.makedirs(T + "/dkms/amneziawg/1.0.0/build", exist_ok=True)
    open(T + "/dkms/amneziawg/1.0.0/build/make.log", "w").write(
        "/var/lib/dkms/amneziawg/1.0.0/build/compat/compat.h:812:9: error: too many arguments to function 'setup_udp_tunnel_sock'\n")
    body = ('uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
            'run(){ echo "RUN $* <$(readlink /proc/self/fd/0)" >> "$T/calls"; case "$*" in *"dpkg "*"--configure -a"*) %s;; '
            '*"apt-get remove"*) touch "$T/removed";; esac; }\n'
            'dpkg(){ case "$1" in --audit) [ -f "$T/state" ] || [ -f "$T/removed" ] || echo "amneziawg-dkms half-configured";; esac; }\n'
            'dpkg-query(){ case "$*" in *Status*) if [ -f "$T/removed" ]; then printf "rc "; elif [ -f "$T/state" ]; then printf "ii "; '
            'else printf "iF "; fi;; *Version*) printf "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1";; esac; }\n'
            'apt-cache(){ printf "  Candidate: 1.0.0-0~202609140848+4569c4c~ubuntu26.04.1\\n"; }\n'
            'modinfo(){ [ -f "$T/state" ]; }\n'
            'AWG_MOD_FAILED="$T/awg-module-failed"; SWG_LIB_MODULES="$T/mods"; SWG_USR_SRC="$T/usr"; SWG_DKMS_TREE="$T/dkms"\n'
            'awg_ppa_module_install && echo RC0 || echo RC1\n') % (KV, 'touch "$T/state"' if builds_after_fix else ':')
    r = sh(body)
    c = open(T + "/calls").read() if os.path.exists(T + "/calls") else ""
    return r, c
r, c = ppa(True)
check("fixed source, dpkg finished → the module builds and nothing is given up on",
      "RC0" in r.stdout and "--configure -a" in c and "remove" not in c and not os.path.exists(T + "/awg-module-failed"), r.stdout + r.stderr + c)
_dl = [l for l in c.splitlines() if "--configure -a" in l]
check("…dpkg finished with no terminal and the old config file kept (IN-12(b)): a conffile question cannot wait unseen",
      _dl == ["RUN env DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold --configure -a </dev/null"], _dl)
r, c = ppa(False)
check("still failing after the fix → given up on (packages removed, record kept)",
      "RC1" in r.stdout and "apt-get remove -y" in c and "amneziawg-dkms amneziawg" in c and os.path.exists(T + "/awg-module-failed"), r.stdout + c)

print("\n[4c] the --reinstall fallback fixes the source again, finishes dpkg, gives up a build that does not compile (IN-10)")
def reinstall(f, builds_after_fix):
    shutil.rmtree(os.path.join(T, "usr"), ignore_errors=True)
    p = os.path.join(T, "usr", "amneziawg-1.0.0", "compat"); os.makedirs(p); open(p + "/compat.h", "w").write(COMPAT)
    sh('awg_compat_patch_installed >/dev/null', {"SWG_USR_SRC": T + "/usr"})   # the box before: the patched source built…
    for x in ("awg-module-failed", "calls", "removed"):
        if os.path.exists(T + "/" + x): os.remove(T + "/" + x)
    open(T + "/state", "w").close()                                          # …the package configured, the module built
    os.makedirs(T + "/dkms/amneziawg/1.0.0/build", exist_ok=True)
    fn = H[H.index("\nbuild_awg_module(){") + 1:] if f == "install-host.sh" else N[N.index("\nbuild_awg_module(){") + 1:]
    fn = fn[:fn.index("\n}\n") + 3]
    body = ('uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
            'modprobe(){ echo "modprobe: ERROR: could not insert amneziawg: Operation not permitted" >&2; return 1; }\n'   # LXC: no key
            'modinfo(){ case "$*" in *-F*) return 0;; esac; [ -f "$T/state" ]; }\nawg_dkms_build_all_kernels(){ :; }\n'
            'run(){ echo "RUN $*" >> "$T/calls"; case "$*" in '
            '*"--reinstall -y amneziawg-dkms"*) printf %%s "$SHIPPED" > "$T/usr/amneziawg-1.0.0/compat/compat.h"; rm -f "$T/state"; '
            'echo "compat.h:812:9: error: too many arguments to function setup_udp_tunnel_sock" > "$T/dkms/amneziawg/1.0.0/build/make.log";; '
            '*"dpkg "*"--configure -a"*) %s;; *"apt-get remove"*) touch "$T/removed";; esac; }\n'
            'dpkg(){ case "$1" in --audit) [ -f "$T/state" ] || [ -f "$T/removed" ] || echo "amneziawg-dkms half-configured";; esac; }\n'
            'dpkg-query(){ case "$*" in *Status*) if [ -f "$T/removed" ]; then printf "rc "; elif [ -f "$T/state" ]; then printf "ii "; '
            'else printf "iF "; fi;; *Version*) printf "1.0.0-0~202609140848+4569c4c~ubuntu26.04.1";; esac; }\n'
            'AWG_MOD_FAILED="$T/awg-module-failed"; SWG_LIB_MODULES="$T/mods"; SWG_USR_SRC="$T/usr"; SWG_DKMS_TREE="$T/dkms"\n'
            ) % (KV, ('grep -q "PR #218" "$T/usr/amneziawg-1.0.0/compat/compat.h" && touch "$T/state"') if builds_after_fix else ':')
    r = sh(body + fn + 'build_awg_module && echo RC0 || echo RC1\n', {"SHIPPED": COMPAT})
    c = open(T + "/calls").read() if os.path.exists(T + "/calls") else ""
    return r, c, "PR #218" in open(p + "/compat.h").read()
for f in ("install-node.sh", "install-host.sh"):
    r, c, patched = reinstall(f, True)
    check("%s: reinstalled (the shipped source back, its build failed) → fixed again, dpkg finished, configured, not given up" % f,
          "--reinstall -y amneziawg-dkms" in c and patched and c.find("--reinstall") < c.find("--configure -a")
          and os.path.exists(T + "/state") and "remove" not in c and not os.path.exists(T + "/awg-module-failed"), r.stdout + r.stderr + c)
    r, c, patched = reinstall(f, False)
    check("%s: …still not compiling after the fix → given up: removed, recorded, build_awg_module says 1 (no rebuild after)" % f,
          "RC1" in r.stdout and "apt-get remove -y" in c and os.path.exists(T + "/awg-module-failed")
          and "dkms autoinstall" not in c[c.find("--reinstall"):], r.stdout + r.stderr + c)
check("update.sh: its heal's --reinstall is the same fallback, and a give-up skips the rebuild after it",
      "|| awg_mod_key_rejected || { awg_dkms_reinstall \\\n                                          && run dkms autoinstall" in UP)

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
if PERTURB_CONFOLD or PERTURB_REINSTALL:
    _red = [f for f in FAILS if (("no terminal and the old config file kept" in f) if PERTURB_CONFOLD
                                 else ("reinstalled" in f or "still not compiling" in f))]
    print("perturb: %s" % ("RED as it must be (%d), all %s" % (len(_red), "[4]'s dpkg line" if PERTURB_CONFOLD else "[4c]") if _red and len(_red) == len(FAILS)
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
