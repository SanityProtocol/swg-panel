#!/usr/bin/env python3
"""Self-test — a module Secure Boot refuses is said with its steps and not rebuilt; dpkg's unfinished work reaches the panel.

Secure Boot (follow-up to the client report 2026-10-06): DKMS signs the AmneziaWG module with its own key, and the kernel
loads it only once that key is enrolled at the console. Until then `modprobe` answers "Key was rejected by service", the
module counts as BUILT (so no compile-failure record), and every heal rebuilt it twice — a --reinstall, then a source
build — to the same refusal, while the panel said "update the node to rebuild the module".

dpkg: a failed DKMS hook leaves packages half-configured and every later apt run on the box fails; the client's box sat
like that with nothing on the panel saying so.

  [1] awg_mod_key_rejected: both kernel answers ("Key was rejected", "Required key not available") → yes; any other
      refusal, a module that loads, or no module file → no
  [2] awg_key_refused_note: the warning names `mokutil --import <the key DKMS signs with>`, and the record holds this
      kernel and that key
  [3] awg_build_from_source, driven: a module refused for its key → no clone, no compile, the note; CONTROL: a plain
      "not loadable" still builds
  [4] build_awg_module (install-node AND install-host), driven: refused for its key → no --reinstall
  [5] the installers and update.sh go straight to userspace with the note, and update's closing line names Secure Boot
  [6] swg-noded node_datapath_health, driven: `why` = "key" (+ the key's path) or "compile" — only from a record for THIS
      kernel, never a guess; a bad path is dropped; a loaded module reports no `why`
  [7] swg-noded dpkg_health, driven: names parsed from `dpkg --audit` (C locale), only from the sections that stop apt —
      not "missing the md5sums file", which many boxes carry harmlessly; an apt run in the last ten minutes is not judged
      (the last settled answer stands); cached until dpkg writes again; an interrupted run's journal; a container and a
      box without dpkg report nothing; an unreadable answer keeps the last one
  [8] the panel: the Secure Boot and compile sentences (no "update the node" promise), the dpkg sentences (at most six
      names, only package-shaped ones), "repair node" not offered when the node recorded why — and every sentence has
      its Russian line
  [9] the master's own host check reads the compile record the same way
  [10] (1.8.9 qualification IN-16) update.sh's REAL ensure_awg_datapath, driven: a module refused for its key and no
      amneziawg-go to be had → a FAILED update saying awg interfaces cannot come up (it said "userspace datapath" and
      succeeded); CONTROLS: amneziawg-go present, or installed by that very run → the userspace note, not a failure

  [11] (1.8.9 qualification VERIFY1-B1) update.sh on a box whose operator BLACKLISTED amneziawg (modprobe.d) — the REAL
      ensure_awg_datapath and ensure_awg_back_on_kernel: no `modprobe amneziawg` by name, nothing healed or moved, one
      line saying why (the update loaded it by name and moved awg0 and the mesh back onto it); CONTROLS: no blacklist →
      both ask modprobe as before
  [6c] (1.8.9 qualification F11 / NLH-5) the probe never loads past a blacklist (`modprobe -b`) and is not asked at all
      where the kernel enforces no module signature (read from sysfs: module.sig_enforce, a lockdown) — nowhere else can
      it refuse a key; on a VM it loaded a module its operator had blacklisted, 0.7 s after swg-noded started

Run: python3 tests/secure_boot_dpkg_selftest.py      (0 = pass)
     --plant sbclaim   the branch as it shipped (the userspace note whatever is there) → RED on [10] (exit 0 when caught)
     --plant nlh5-noblacklist | nlh5-noenforce   the probe by name / on every kernel again → RED on [6c]
     --plant bl-heal | bl-back   update.sh's heal / its move back onto the kernel ask by name again (e66018f) → RED on [11]
     --plant bl-quiet   awg_blacklisted with grep -q (quits at the match; modprobe -c dies of SIGPIPE; pipefail) → RED on [11]
"""
import builtins, importlib.machinery, importlib.util, io, json, os, re, subprocess, sys, tempfile, time
from unittest import mock
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
def grab(path, *names):
    """Functions as bash itself defines them: the file sourced (definitions only), then `declare -f`."""
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f "${@:2}"', "_", os.path.join(ROOT, path)] + list(names),
                       capture_output=True, text=True)
    assert all((n + " ()") in r.stdout for n in names), "could not read %s from %s: %s" % (names, path, r.stderr[-300:])
    return r.stdout + "\n"
def grab_text(path, name):
    """One function by its text (for scripts that run on source): from `name(){` to the first line that is just `}`."""
    s = rd(path); a = s.index("\n" + name + "(){") + 1; b = s.index("\n}\n", a) + 3
    return s[a:b]

T = tempfile.mkdtemp(prefix="sbdpkg-")
open(T + "/mok.pub", "w").write("key")
KERN = "7.0.0-38-generic"
LIB = grab("lib/common.sh", "awg_mod_built", "awg_mod_key_rejected", "awg_mok_key", "_awg_boot_id", "awg_key_refused_here", "awg_key_refused_note")
STUBS = ('DRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\nnote(){ echo "NOTE $*"; }\n'
         'run(){ echo "RUN $*" >> "$T/calls"; }\n'
         'uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\n'
         'AWG_MOD_REFUSED="$T/awg-module-refused"; AWG_MOD_FAILED="$T/awg-module-failed"; SWG_MOK_CANDIDATES="${SWG_MOK_CANDIDATES:-$T/mok.pub}"\n') % KERN
SIGNED = 'case "$*" in *signer*) echo "host Secure Boot Module Signature key";; *sig_key*) echo "${SIGKEY:-}";; esac; return 0'
def sh(body, modinfo=SIGNED, modprobe_err="", modprobe_rc=1, env=None):
    mp = 'modprobe(){ [ -n "%s" ] && echo "%s" >&2; return %d; }\n' % (modprobe_err, modprobe_err, modprobe_rc)
    return subprocess.run(["bash", "-c", STUBS + "modinfo(){ %s; }\n" % modinfo + mp + LIB + body],
                          capture_output=True, text=True, env=dict(os.environ, T=T, **(env or {})))
def calls():
    p = T + "/calls"
    s = open(p).read() if os.path.exists(p) else ""
    open(p, "w").close()
    return s
def reset():
    for f in ("awg-module-refused", "awg-module-failed", "calls"):
        if os.path.exists(T + "/" + f):
            os.remove(T + "/" + f)
KEY = "modprobe: ERROR: could not insert 'amneziawg': Key was rejected by service"
NOKEY = "modprobe: ERROR: could not insert 'amneziawg': Required key not available"
EXEC = "modprobe: ERROR: could not insert 'amneziawg': Exec format error"
Q = 'awg_mod_key_rejected && echo YES || echo NO'

print("[1] awg_mod_key_rejected")
check("'Key was rejected by service' → yes", "YES" in sh(Q, modprobe_err=KEY).stdout)
check("'Required key not available' (lockdown) → yes", "YES" in sh(Q, modprobe_err=NOKEY).stdout)
check("CONTROL: another refusal (a build for another ABI) → no", "NO" in sh(Q, modprobe_err=EXEC).stdout)
check("CONTROL: the module loads → no", "NO" in sh(Q, modprobe_rc=0).stdout)
check("CONTROL: no module file for this kernel → no (that is a compile question)", "NO" in sh(Q, modinfo="return 1", modprobe_err=KEY).stdout)
check("CONTROL: an UNSIGNED module refused → no (there is no key to enrol for it)", "NO" in sh(Q, modinfo="return 0", modprobe_err=NOKEY).stdout)

print("\n[1b] awg_mok_key names the certificate that SIGNED the module (modinfo's sig_key = its serial), not a guess")
import shutil as _sh
colons = ""
if _sh.which("openssl"):
    for n in ("a", "b"):
        subprocess.run(["openssl", "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=key-" + n,
                        "-keyout", "%s/%s.key" % (T, n), "-outform", "DER", "-out", "%s/%s.der" % (T, n)], capture_output=True, check=True)
    ser = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", T + "/b.der", "-noout", "-serial"], capture_output=True, text=True).stdout.split("=")[1].strip()
    colons = ":".join(ser[i:i + 2] for i in range(0, len(ser), 2)).lower()      # how modinfo prints it
    cand = {"SWG_MOK_CANDIDATES": "%s/a.der %s/b.der" % (T, T)}
    r = sh('have(){ command -v "$1" >/dev/null 2>&1; }; awg_mok_key', env=dict(cand, SIGKEY=colons))
    check("two keys on the box, the module signed by the SECOND → the second is named", r.stdout == T + "/b.der", r.stdout + r.stderr)
    r = sh('have(){ command -v "$1" >/dev/null 2>&1; }; awg_mok_key && echo " FOUND" || echo NONE', env=dict(cand, SIGKEY="00:11:22"))
    check("signed by neither → none named (the message says 'the DKMS signing key', never a wrong path)", "NONE" in r.stdout, r.stdout)
    r = sh('have(){ command -v "$1" >/dev/null 2>&1; }; awg_mok_key', env=dict(cand, SIGKEY=""))
    check("no sig_key to match → the first that exists", r.stdout == T + "/a.der", r.stdout)
else:
    print("  SKIP no openssl on this box")

print("\n[2] awg_key_refused_note")
reset()
r = sh('awg_key_refused_note; awg_key_refused_here && echo HERE')
rec = open(T + "/awg-module-refused").read() if os.path.exists(T + "/awg-module-refused") else ""
check("the warning gives the enrolment steps with the key DKMS signs with", "sudo mokutil --import %s/mok.pub" % T in r.stdout
      and "Enroll MOK" in r.stdout and "rebuilding the module would not help" in r.stdout, r.stdout)
BOOT = open("/proc/sys/kernel/random/boot_id").read().strip()
check("the record: this kernel, this boot, and the key", rec == "kernel=%s\nboot=%s\nmok=%s/mok.pub\n" % (KERN, BOOT, T), repr(rec))
check("awg_key_refused_here reads it back for this kernel", "HERE" in r.stdout, r.stdout)
r = subprocess.run(["bash", "-c", STUBS.replace(KERN, "7.0.0-40-generic") + LIB + 'awg_key_refused_here && echo HERE || echo NOT'],
                   capture_output=True, text=True, env=dict(os.environ, T=T))
check("…and not for another kernel", "NOT" in r.stdout, r.stdout + r.stderr)

print("\n[3] awg_build_from_source, driven")
SRC = grab("lib/common.sh", "awg_build_from_source", "awg_fail_get", "awg_fail_note", "awg_src_retry_due", "_awg_kbuild")
def build(modprobe_err):
    body = ('awg_tools_drive_3x(){ return 0; }\nawg_tools_old_why(){ :; }\ndepmod(){ :; }\nensure_awg_headers_follow(){ :; }\n'
            'have(){ case "$1" in git|make|awg|awg-quick|dkms|modprobe) return 0;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
            'dkms(){ :; }\ngit_clone_depth1(){ echo "CLONE $1" >> "$T/calls"; return 1; }\nawg_module_head(){ echo b72bb7a; }\n'
            'SWG_LIB_MODULES="$T/mods"\n') + SRC + 'awg_build_from_source && echo RC0 || echo RC1\n'
    return sh(body, modprobe_err=modprobe_err)
reset(); r = build(KEY); c = calls()
check("refused for its key → no clone, no compile, rc 1, the steps said", "kernel-module" not in c and "RC1" in r.stdout
      and "mokutil --import" in r.stdout, r.stdout + c)
reset(); r = build(EXEC); c = calls()
check("CONTROL: another refusal → it is cloned and built", "CLONE https://github.com/amnezia-vpn/amneziawg-linux-kernel-module" in c, r.stdout + c)

print("\n[4] build_awg_module, driven")
# the --reinstall goes through lib's awg_dkms_reinstall (IN-10: its source fixed again, dpkg finished, a non-compiling build
# given up — driven in tests/awg_compat_patch_selftest.py [4c]); here only whether build_awg_module reaches it
REINST = grab("lib/common.sh", "awg_dkms_reinstall") + ('awg_compat_patch_installed(){ return 1; }\nawg_dpkg_recover(){ :; }\n'
                                                       'awg_dkms_compile_failed(){ return 1; }\nawg_dkms_give_up(){ :; }\n')
for f in ("install-node.sh", "install-host.sh"):
    fn = REINST + grab_text(f, "build_awg_module")
    for err, name, want in ((KEY, "refused for its key", False), (EXEC, "CONTROL: another refusal", True)):
        reset()
        r = sh('awg_dkms_build_all_kernels(){ :; }\n' + fn + 'build_awg_module; echo DONE', modprobe_err=err); c = calls()
        check("%s: %s → %s" % (f, name, "a --reinstall" if want else "no --reinstall"), ("--reinstall" in c) == want and "DONE" in r.stdout, c + r.stderr)

print("\n[5] the routes that would rebuild go to userspace instead")
for f in ("install-node.sh", "install-host.sh"):
    s = rd(f)
    check("%s: refused for its key → the note, then userspace, before any source build" % f,
          "  if have awg && awg_mod_key_rejected; then\n    awg_key_refused_note\n    ensure_awg_userspace && return 0" in s
          and s.index("awg_mod_key_rejected; then\n    awg_key_refused_note") < s.index("  awg_build_from_source && {"))
U = rd("update.sh")
check("update.sh: the heal stops at a refused key — the note, userspace, one closing line",
      'if [ "$_tools" = yes ] && awg_mod_key_rejected; then\n    awg_key_refused_note' in U
      and U.index("awg_mod_key_rejected; then\n    awg_key_refused_note") < U.index('info "healing the AmneziaWG kernel module'))
check("update.sh: Secure Boot is asked BEFORE 'nothing new to try' (an old compile record would give the wrong reason)",
      U.index('if [ "$_tools" = yes ] && awg_mod_key_rejected; then') < U.index('have amneziawg-go && awg_nothing_new; then'))
check("update.sh: the package route's retry skips the --reinstall for a refused key",
      "modprobe amneziawg 2>/dev/null || awg_mod_key_rejected || { awg_dkms_reinstall" in U)
check("update.sh: the closing userspace line names Secure Boot when it was recorded",
      'userspace (amneziawg-go); $(if awg_key_refused_here; then echo "Secure Boot refuses the kernel module' in U)

print("\n[10] update.sh's heal, DRIVEN: refused for its key and no userspace datapath either → a FAILED update (1.8.9 IN-16)")
FN = grab_text("update.sh", "ensure_awg_datapath")
if PLANT == "sbclaim":                                   # the shape that shipped: "userspace datapath", success, whatever is there
    _a = '    if have amneziawg-go; then\n      note "AmneziaWG: userspace datapath — Secure Boot'
    assert FN.count(_a) == 1, "plant anchor missing — this run would measure nothing"
    FN = FN.replace(_a, '    if true; then\n      note "AmneziaWG: userspace datapath — Secure Boot')
HEAL = ('set -euo pipefail\nHAVE_BNODE=yes; DID_UPDATE=no; DID_FAIL=no\nok(){ echo "OK $*"; }\n'
        'have(){ case "$1" in awg|awg-quick|dkms) return 0;; amneziawg-go) [ -e "$T/go" ];; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
        'awg_compat_patch_installed(){ return 1; }\nawg_go_needs_install(){ [ ! -e "$T/go" ]; }\n'
        'awg_go_pinned(){ return 1; }\n'                  # GitHub and every mirror unreachable
        'ensure_awg_userspace(){ [ -e "$T/go-builds" ] && touch "$T/go"; [ -e "$T/go" ]; }\nawg_nothing_new(){ return 1; }\n')
def heal(go=None):
    reset()
    for f in ("go", "go-builds"):
        if os.path.exists(T + "/" + f):
            os.remove(T + "/" + f)
    if go:
        open(T + "/" + go, "w").close()
    return sh(HEAL + FN + 'ensure_awg_datapath; echo "RC=$? DID_FAIL=$DID_FAIL GO=$(have amneziawg-go && echo yes || echo no)"\n',
              modprobe_err=KEY)
r = heal()
check("refused for its key, amneziawg-go absent and not to be had → DID_FAIL, said as 'cannot come up' — never 'userspace datapath'",
      "DID_FAIL=yes GO=no" in r.stdout and "awg interfaces cannot come up" in r.stdout
      and "NOTE AmneziaWG: userspace datapath" not in r.stdout and "mokutil --import" in r.stdout, r.stdout + r.stderr)
r = heal("go")
check("CONTROL: amneziawg-go there → the userspace note, not a failure",
      "DID_FAIL=no GO=yes" in r.stdout and "NOTE AmneziaWG: userspace datapath" in r.stdout, r.stdout + r.stderr)
r = heal("go-builds")
check("CONTROL: amneziawg-go installed by this very run → the userspace note, DID_UPDATE, not a failure",
      "DID_FAIL=no GO=yes" in r.stdout and "NOTE AmneziaWG: userspace datapath" in r.stdout, r.stdout + r.stderr)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
_NODED = os.path.join(ROOT, "swg-noded")
_NPLANTS = {"nlh5-noblacklist": ('r = run(["modprobe", "-b", "amneziawg"], timeout=30)', 'r = run(["modprobe", "amneziawg"], timeout=30)'),
            "nlh5-noenforce": ('run(["modinfo", "-F", "signer", "amneziawg"]).stdout.strip() and _awg_sig_enforced():',
                               'run(["modinfo", "-F", "signer", "amneziawg"]).stdout.strip():')}
if PLANT in _NPLANTS:
    _src = open(_NODED, encoding="utf-8").read(); _o, _n = _NPLANTS[PLANT]
    assert _src.count(_o) == 1, "plant anchor missing — this run would measure nothing"
    _NODED = os.path.join(tempfile.mkdtemp(prefix="sbplant-"), "swg-noded"); open(_NODED, "w", encoding="utf-8").write(_src.replace(_o, _n))
N = load("swgnoded", _NODED)
P = load("swgpanel", os.path.join(ROOT, "swg-panel-server"))
KR = os.uname().release

print("\n[11] update.sh on a box whose operator blacklisted the module (VERIFY1-B1)")
BLF = grab("lib/common.sh", "awg_blacklisted")
if PLANT == "bl-quiet":   # the first form of the fix: grep -q, which quits at the match
    assert BLF.count("grep -cE") == 1, "plant anchor missing — this run would measure nothing"
    BLF = BLF.replace("grep -cE", "grep -qE")
HEAL11 = grab_text("update.sh", "ensure_awg_datapath")
BACK11 = grab_text("update.sh", "ensure_awg_back_on_kernel")
if PLANT == "bl-heal":   # e66018f: the heal asks modprobe by name whatever modprobe.d says
    _a = '  if awg_blacklisted; then _bl=yes; else { $DRYRUN || modprobe amneziawg 2>/dev/null; } && _mod=yes; fi\n'
    assert HEAL11.count(_a) == 1, "plant anchor missing — this run would measure nothing"
    HEAL11 = HEAL11.replace(_a, '  { $DRYRUN || modprobe amneziawg 2>/dev/null; } && _mod=yes\n')
if PLANT == "bl-back":
    _a = '  awg_blacklisted && return 0   # the operator\'s own blacklist'
    assert BACK11.count(_a) == 1, "plant anchor missing — this run would measure nothing"
    BACK11 = BACK11.replace(_a, '  : # (the blacklist not asked)')
BACK11 = BACK11.replace("/sys/class/net", T + "/no-such-sys")   # nothing of this box's own devices is ever looked at
# modprobe as a PROCESS on PATH, and -c as the real one prints it: the modprobe.d directives first, then tens of thousands of
# alias lines — a consumer that quits at the match (grep -q) leaves it to die of SIGPIPE, and under update.sh's pipefail the
# blacklist then read as absent (the first form of this fix; the suite's pipefail linter caught it)
BLBIN = os.path.join(T, "blbin"); os.makedirs(BLBIN, exist_ok=True)
open(os.path.join(BLBIN, "modprobe"), "w").write('#!/bin/bash\nif [ "$1" = -c ]; then echo "options x y=1"\n'
                                                 '  [ -e "$T/blacklisted" ] && echo "blacklist amneziawg"\n'
                                                 "  exec seq -f 'alias pci:v%08g z' 1 60000\nfi\n"
                                                 'echo "MODPROBE $*" >> "$T/calls"; exit 0\n')
os.chmod(os.path.join(BLBIN, "modprobe"), 0o755)
def bl(body, blacklisted):
    if blacklisted:
        open(T + "/blacklisted", "w").close()
    elif os.path.exists(T + "/blacklisted"):
        os.remove(T + "/blacklisted")
    mp = ""
    script = ('set -euo pipefail\nHAVE_BNODE=yes; DID_UPDATE=no; DID_FAIL=no; DRYRUN=false\nok(){ echo "OK $*"; }; note(){ echo "NOTE $*"; }\n'
              'run(){ "$@"; }; have(){ case "$1" in awg|awg-quick|amneziawg-go) return 0;; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
              'awg_compat_patch_installed(){ return 1; }\nawg_go_needs_install(){ return 1; }\nensure_awg_headers_follow(){ return 1; }\n'
              'awg_dkms_build_all_kernels(){ :; }\nawg_headers_meta(){ :; }\ndkms(){ echo x; }\n' + mp + BLF + body)
    return subprocess.run(["bash", "-c", STUBS.replace("run(){", "_unused_run(){") + script], capture_output=True, text=True,
                          env=dict(os.environ, T=T, PATH=BLBIN + ":" + os.environ["PATH"]))
for blk, label in ((True, "blacklisted"), (False, "CONTROL: not blacklisted")):
    reset()
    r = bl(HEAL11 + 'ensure_awg_datapath; echo "RC=$? FAIL=$DID_FAIL"\n', blk)
    c = calls()
    if blk:
        check("the heal on a blacklisted box: no `modprobe amneziawg` by name, nothing healed, said once",
              "MODPROBE" not in c and "RC=0 FAIL=no" in r.stdout and "blacklisted on this box (modprobe.d)" in r.stdout, (c, r.stdout + r.stderr))
    else:
        check("%s: the heal asks modprobe for the module as before" % label, "MODPROBE amneziawg" in c, (c, r.stdout + r.stderr))
    reset()
    r = bl(BACK11 + 'ensure_awg_back_on_kernel; echo "RC=$?"\n', blk)
    c = calls()
    if blk:
        check("the move back onto the kernel on a blacklisted box: no `modprobe amneziawg` by name, nothing moved",
              "MODPROBE" not in c and "RC=0" in r.stdout, (c, r.stdout + r.stderr))
    else:
        check("%s: the move asks modprobe as before" % label, "MODPROBE amneziawg" in c, (c, r.stdout + r.stderr))

print("\n[6] swg-noded: why the module does not load — the KERNEL is asked (once per boot and module file), the record kept in step")
S = tempfile.mkdtemp(prefix="sbstate-"); N.STATE_DIR = S
BOOTS = {"id": "boot-1"}; N._boot_id = lambda: BOOTS["id"]
DEPS = {"stamp": "dep-1"}; N._modules_dep_stamp = lambda: DEPS["stamp"]
KK = {"signer": "host Secure Boot Module Signature key", "err": "modprobe: ERROR: could not insert 'amneziawg': Key was rejected by service",
      "rc": 1, "sigkey": "", "probes": 0}
_REAL_ENFORCED = N._awg_sig_enforced
N._awg_sig_enforced = lambda: True              # a Secure Boot box (lockdown), as the cells below model; [6c] reads the real one
def krun(args, timeout=20, **k):
    if args[:3] == ["modinfo", "-F", "signer"]:
        return subprocess.CompletedProcess(args, 0, KK["signer"] + "\n", "")
    if args[:3] == ["modinfo", "-F", "sig_key"]:
        return subprocess.CompletedProcess(args, 0, KK["sigkey"] + "\n", "")
    if args[:1] == ["modprobe"]:
        KK["probes"] += 1; KK["argv"] = list(args)
        return subprocess.CompletedProcess(args, KK["rc"], "", KK["err"] if KK["rc"] else "")
    return subprocess.CompletedProcess(args, 1, "", "")
N.run = krun
def rec(name, text):
    for f in ("awg-module-refused", "awg-module-failed"):
        if os.path.exists(os.path.join(S, f)):
            os.remove(os.path.join(S, f))
    if name:
        open(os.path.join(S, name), "w").write(text)
def readrec():
    p = os.path.join(S, "awg-module-refused")
    return open(p).read() if os.path.exists(p) else None
def fresh(**kw):
    N._AWG_KEY.update(k=None, v=False); KK.update(signer="host Secure Boot Module Signature key", rc=1, probes=0,
                                                  err="modprobe: ERROR: could not insert 'amneziawg': Key was rejected by service")
    KK.update(kw)
def health(modules="", built=False, fallback=True, tun=("awg0",)):
    ifaces = {"awg0": {"meta": {"tool": "awg"}}}
    exists = {"/usr/bin/awg"} | {"/sys/class/net/%s/tun_flags" % i for i in tun}
    real_open = builtins.open
    def fopen(p, *a, **k):
        return io.StringIO(modules) if p == "/proc/modules" else real_open(p, *a, **k)
    def flistdir(d):
        if built and d == "/lib/modules/%s/updates/dkms" % KR:
            return ["amneziawg.ko.zst"]
        raise FileNotFoundError(d)
    with mock.patch("builtins.open", fopen), mock.patch("os.path.exists", lambda p: p in exists), \
         mock.patch("os.access", lambda p, m: fallback and p == "/usr/local/bin/amneziawg-go"), mock.patch("os.listdir", flistdir), \
         mock.patch.object(N, "NODE_KIND", "bare"):
        return (N.node_datapath_health(ifaces) or {}).get("awg") or {}
rec("awg-module-refused", "kernel=%s\nboot=boot-0\nmok=/var/lib/dkms/mok.pub\n" % KR); fresh()
a = health(built=True)
check("built, the kernel refuses its key, interfaces on the fallback → why=key + the installer's key", a.get("ok") is False
      and a.get("why") == "key" and a.get("mok") == "/var/lib/dkms/mok.pub", a)
check("…the record is refreshed for THIS boot (the panel's host check reads it), its key kept",
      readrec() == "kernel=%s\nboot=boot-1\nmok=/var/lib/dkms/mok.pub\n" % KR, readrec())
health(built=True); health(built=True)
check("…asked ONCE: later syncs in the same boot do not run modprobe again", KK["probes"] == 1, KK["probes"])
BOOTS["id"] = "boot-2"; health(built=True)
check("…a reboot asks again (the code review's case: enrolled or not, the old record no longer says)", KK["probes"] == 2, KK["probes"])
DEPS["stamp"] = "dep-2"; health(built=True)
check("…and so does a new module file (DKMS rebuilt it)", KK["probes"] == 3, KK["probes"])
fresh(); a = health(built=True, fallback=False, tun=())
check("refused with NO fallback and nothing on userspace yet → not ok (built alone read as healthy, nothing came up)",
      a.get("ok") is False and a.get("why") == "key" and a.get("fallback") is False, a)
fresh(rc=0); rec("awg-module-refused", "kernel=%s\nboot=boot-2\nmok=/var/lib/dkms/mok.pub\n" % KR); a = health(built=True, tun=())
check("after enrolment the modprobe succeeds → no why, ok, and the record is removed", "why" not in a and a.get("ok") is True
      and readrec() is None, (a, readrec()))
fresh(signer=""); a = health(built=True)
check("an UNSIGNED module the kernel refuses → not a key refusal (no key to enrol), and modprobe is not even asked",
      a.get("why") != "key" and KK["probes"] == 0, (a, KK["probes"]))
fresh(err="modprobe: ERROR: could not insert 'amneziawg': Exec format error"); a = health(built=True)
check("another refusal (a build for another ABI) → not a key refusal", a.get("why") != "key", a)
fresh(); rec("awg-module-refused", "kernel=%s\nboot=boot-0\nmok=/var/lib/dkms/mok.pub; rm -rf /\n" % KR)
a = health(built=True)
check("a key path that is not a plain path is dropped (why stays)", a.get("why") == "key" and "mok" not in a, a)
print("\n[6c] the probe: never past a blacklist, never where no key can be refused (F11 / NLH-5)")
fresh(); a = health(built=True)
check("it asks `modprobe -b` — a blacklisted module is not loaded by asking (a by-name modprobe ignores `blacklist`)",
      KK.get("argv") == ["modprobe", "-b", "amneziawg"], KK.get("argv"))
_SYSD = tempfile.mkdtemp(prefix="sbsys-")
N.SIG_ENFORCE, N.LOCKDOWN = _SYSD + "/sig_enforce", _SYSD + "/lockdown"
def _reads(sig, lock):
    for f, v in ((N.SIG_ENFORCE, sig), (N.LOCKDOWN, lock)):
        if os.path.exists(f): os.remove(f)
        if v is not None: open(f, "w").write(v)
N._awg_sig_enforced = _REAL_ENFORCED                 # the module's own, reading the two files
for sig, lock, want, what in (("Y\n", "[none] integrity confidentiality\n", True, "module.sig_enforce=Y"),
                             ("N\n", "none [integrity] confidentiality\n", True, "a lockdown in integrity mode (Secure Boot)"),
                             ("N\n", "none integrity [confidentiality]\n", True, "a lockdown in confidentiality mode"),
                             ("N\n", "[none] integrity confidentiality\n", False, "no sig_enforce, no lockdown"),
                             ("N\n", None, False, "no sig_enforce and no lockdown file"),
                             (None, None, False, "no sig_enforce parameter at all (the kernel checks no signatures)")):
    _reads(sig, lock)
    check("_awg_sig_enforced: %s → %s" % (what, want), N._awg_sig_enforced() is want, N._awg_sig_enforced())
_reads("N\n", "[none] integrity confidentiality\n"); fresh(); a = health(built=True)
check("a kernel that enforces no signature → no modprobe at all (nothing loaded to find out), no key refusal",
      KK["probes"] == 0 and a.get("why") != "key", (KK["probes"], a))
N._awg_sig_enforced = lambda: True

if _sh.which("openssl"):
    fresh(sigkey=colons); rec("", ""); N.AWG_MOK_CANDIDATES = (T + "/a.der", T + "/b.der"); N.run = lambda args, timeout=20, **k: (
        subprocess.run(args, capture_output=True, text=True) if args[:1] == ["openssl"] else krun(args, timeout))
    a = health(built=True)
    check("no installer record → swg-noded names the certificate that signed the module itself (matched by serial)",
          a.get("mok") == T + "/b.der", a)
    N.run = krun
fresh(); rec("awg-module-failed", "kernel=%s\npkg=1.0.0\n" % KR)
check("no module file + the compile record → why=compile, and modprobe is not asked", health(built=False).get("why") == "compile"
      and KK["probes"] == 0, health(built=False))
fresh(rc=0)
check("the compile record, but a module file exists now (and loads) → no why", "why" not in health(built=True), health(built=True))
fresh()
check("CONTROL: the module is loaded → ok, no why, and the kernel is not asked", "why" not in health(modules="amneziawg 1 0 - Live\n", tun=())
      and health(modules="amneziawg 1 0 - Live\n", tun=()).get("ok") is True and KK["probes"] == 0)
rec("", ""); fresh()
check("CONTROL: no module file and no record → no why", "why" not in health(built=False))

print("\n[7] swg-noded: dpkg's unfinished work")
D = tempfile.mkdtemp(prefix="sbdpkg-db-"); os.makedirs(D + "/updates")
N.DPKG_STATUS = D + "/status"; N.DPKG_UPDATES = D + "/updates"; open(N.DPKG_STATUS, "w").write("x")
open(D + "/lock", "w").write(""); N.DPKG_LOCKS = (D + "/lock",); N.PROC_LOCKS = D + "/proc-locks"; open(N.PROC_LOCKS, "w").write("")
_st = os.stat(D + "/lock"); LOCKID = "%02x:%02x:%d" % (os.major(_st.st_dev), os.minor(_st.st_dev), _st.st_ino)
AUDIT = ("The following packages are only half configured, probably due to problems\nconfiguring them the first time.  The "
         "configuration should be retried using\ndpkg --configure <package> or the configure menu option in dselect:\n"
         " amneziawg-dkms       AmneziaWG kernel module\n linux-headers-7.0.0-38-generic Linux kernel headers\n"
         " evil;rm            not a package name\n"
         "The following packages are missing the md5sums control file in the database, they need to be reinstalled:\n"
         " vendor-agent         an old third-party package\n"
         "The following packages have been triggered, but the trigger processing has not yet been done.  Trigger\n"
         " man-db               on-line manual pager\n"
         "The following packages have been unpacked but not yet configured.  They must be configured using\n"
         "dpkg --configure or the configure menu option in dselect for them to work:\n"
         " amneziawg-tools      AmneziaWG tools\n")
AUD = {"out": AUDIT, "rc": 1, "n": 0}
def fake_run(args, timeout=20, env=None, **k):
    AUD["n"] += 1; AUD["args"] = list(args); AUD["env"] = env
    return subprocess.CompletedProcess(args, AUD["rc"], AUD["out"], "")
def dk(now, kind="bare", dpkg=True):
    with mock.patch.object(N, "run", fake_run), mock.patch.object(N, "NODE_KIND", kind), \
         mock.patch.object(N.shutil, "which", lambda b: "/usr/bin/dpkg" if dpkg and b == "dpkg" else None):
        return N.dpkg_health(now)
def fresh(age):
    t = time.time() - age; os.utime(N.DPKG_STATUS, (t, t)); os.utime(N.DPKG_UPDATES, (t, t)); N._DPKG.update(mtime=None, at=0.0, v=None, peek=0.0); AUD["n"] = 0
now = time.time()
fresh(3600)
v = dk(now)
check("settled for an hour → the packages in states that stop apt, by name (a malformed line dropped)",
      v == {"pending": ["amneziawg-dkms", "linux-headers-7.0.0-38-generic", "amneziawg-tools"], "interrupted": False}, v)
check("…not a package only missing its md5sums (harmless — apt runs fine for years with it)", "vendor-agent" not in v["pending"], v)
check("…not a package with triggers pending (apt processes them itself on its next run)", "man-db" not in v["pending"], v)
check("…asked in the C locale (the headers are read; a Russian box would answer in Russian)", AUD.get("args") == ["dpkg", "--audit"]
      and (AUD.get("env") or {}).get("LC_ALL") == "C", (AUD.get("args"), (AUD.get("env") or {}).get("LC_ALL")))
dk(now + 60)
check("…cached: the next sync does not run dpkg again", AUD["n"] == 0 or AUD["n"] == 1, AUD["n"])
fresh(120)
check("dpkg wrote two minutes ago (maybe still running) → not judged: nothing yet, and dpkg not asked",
      dk(now) == {"pending": [], "interrupted": False} and AUD["n"] == 0, AUD)
fresh(3600); dk(now); t = time.time() - 60; os.utime(N.DPKG_STATUS, (t, t)); AUD["rc"] = 2   # mid-run: no readable answer
check("…an apt run starts after a settled answer → the last settled answer stands meanwhile",
      dk(now)["pending"] == ["amneziawg-dkms", "linux-headers-7.0.0-38-generic", "amneziawg-tools"])
t = time.time() - 3600; os.utime(N.DPKG_STATUS, (t, t)); AUD.update(rc=0, out="")
check("…dpkg writes again and settles clean → nothing pending", dk(now) == {"pending": [], "interrupted": False})
fresh(3600); AUD.update(out=AUDIT, rc=1); open(N.PROC_LOCKS, "w").write("1: POSIX  ADVISORY  WRITE 4242 %s 0 EOF\n" % LOCKID)
check("status untouched for an hour but dpkg HOLDS its lock (a long postinst) → not judged, dpkg not asked",
      dk(now) == {"pending": [], "interrupted": False} and AUD["n"] == 0, AUD)
open(N.PROC_LOCKS, "w").write("1: POSIX  ADVISORY  WRITE 4242 00:00:1 0 EOF\n")
check("CONTROL: another file's lock → judged", dk(now)["pending"][:1] == ["amneziawg-dkms"])
open(N.PROC_LOCKS, "w").write("")
fresh(3600); t = time.time() - 60; os.utime(N.DPKG_UPDATES, (t, t))
check("its journal moved a minute ago (status itself untouched) → not judged", dk(now) == {"pending": [], "interrupted": False} and AUD["n"] == 0)
fresh(3600); AUD.update(out="", rc=0); open(D + "/updates/0003", "w").write("x"); t = time.time() - 3600; os.utime(N.DPKG_UPDATES, (t, t))
check("a run cut off mid-way (its journal in updates/) → interrupted", dk(now) == {"pending": [], "interrupted": True})
os.remove(D + "/updates/0003")
fresh(3600); AUD.update(out=AUDIT, rc=1); dk(now); t = time.time() - 3600 + 5; os.utime(N.DPKG_STATUS, (t, t)); AUD["rc"] = 2
check("an answer that cannot be read (rc 2) keeps the last one", dk(now)["pending"][:1] == ["amneziawg-dkms"])
fresh(3600)
fresh(3600); AUD.update(out=AUDIT, rc=1); dk(now)
t = time.time() - 30; os.utime(N.DPKG_STATUS, (t, t)); AUD.update(out="", rc=0)
check("the operator fixes it (`dpkg --configure -a` writes status) → cleared at once, not after ten more minutes",
      dk(now) == {"pending": [], "interrupted": False}, N._DPKG)
fresh(3600); AUD.update(out=AUDIT, rc=1); dk(now); t = time.time() - 30; os.utime(N.DPKG_STATUS, (t, t)); AUD["n"] = 0
v1 = dk(now); v2 = dk(now + 10)
check("…but a peek that still finds work keeps the issue (no flapping mid-run), at most one peek a minute",
      v1["pending"][:1] == ["amneziawg-dkms"] and v2 == v1 and AUD["n"] == 1, (v1, AUD["n"]))
check("…and nothing is peeked while no issue is shown (a healthy box is not audited mid-run)",
      (lambda: (fresh(3600), AUD.update(out="", rc=0), dk(now), os.utime(N.DPKG_STATUS, (time.time() - 30,) * 2),
                AUD.__setitem__("n", 0), dk(now), AUD["n"])[-1])() == 0)
check("a container (its packages are the image's) → None", dk(now, kind="docker") is None)
check("no dpkg (NixOS, a non-Debian box) → None", dk(now, dpkg=False) is None)
check("the snapshot carries it only where there is an answer",
      '            **_dpkg_part(),\n' in rd("swg-noded") and 'return {"dpkg": d} if d is not None else {}' in rd("swg-noded"))

print("\n[8] the panel")
def issues(snap):
    return [i["error"] for i in P._node_issues({"id": "n1", "name": "n1"}, snap)]
def dps(**awg):
    return {"datapath": {"awg": dict(needed=True, ok=False, **awg)}}
i = issues(dps(fallback=True, why="key", mok="/var/lib/shim-signed/mok/MOK.der"))
check("Secure Boot, fallback → the steps with the node's key, no 'update the node'", len(i) == 1 and "Secure Boot refuses" in i[0]
      and "sudo mokutil --import /var/lib/shim-signed/mok/MOK.der" in i[0] and "slower fallback" in i[0] and "update the node" not in i[0], i)
i = issues(dps(fallback=False, why="key", mok="/x; reboot"))
check("Secure Boot, no fallback → can't come up; a bad key path → a sentence of its own naming both distros' keys (no English fragment spliced into a translated one)",
      "can't come up" in i[0] and "/var/lib/shim-signed/mok/MOK.der on Ubuntu, /var/lib/dkms/mok.pub on Debian" in i[0] and "/x;" not in i[0]
      and P._node_issues({"id": "n", "name": "n"}, dps(fallback=False, why="key"))[0].get("error_vars") in (None, {}), i)
i = issues(dps(fallback=True, why="compile"))
check("does not compile → waits for a new kernel or build, no 'update the node to rebuild'", "does not compile" in i[0]
      and "rebuild" not in i[0], i)
check("CONTROL: no why → the old 'update the node to rebuild' sentence", "update the node to rebuild" in issues(dps(fallback=True))[0])
i = issues({"dpkg": {"pending": ["amneziawg-dkms", "bad name!", "linux-headers-7.0.0-38-generic"], "interrupted": False}})
check("dpkg: the package-shaped names, and the command", len(i) == 1 and "(amneziawg-dkms, linux-headers-7.0.0-38-generic)" in i[0]
      and "sudo dpkg --configure -a" in i[0], i)
i = issues({"dpkg": {"pending": ["p%d" % n for n in range(9)]}})
check("dpkg: at most six names, then +N", "(p0, p1, p2, p3, p4, p5 +3)" in i[0], i)
check("dpkg: only an interrupted run → its own sentence", "was interrupted" in issues({"dpkg": {"pending": [], "interrupted": True}})[0])
check("dpkg: nothing pending, or no report, or a malformed one → silent",
      issues({"dpkg": {"pending": [], "interrupted": False}}) == [] and issues({}) == [] and issues({"dpkg": "x"}) == []
      and issues({"dpkg": {"pending": "amneziawg-dkms"}}) == [])
PS = rd("swg-panel-server")
check("'repair node' is not offered for Secure Boot — and still is for a module that does not compile (an update retries when something moved)",
      '_awg_datapath(snap).get("needed") and _awg_datapath(snap).get("why") != "key"\n' in PS)
ru = rd("js/lang/ru.js")
keys = re.findall(r'(?:perr\(|if _dp\.get\("fallback"\) else\s+)("(?:AmneziaWG: Secure|AmneziaWG\'s kernel module does not|the package manager on|a package manager run)[^"]*")', PS)
keys += re.findall(r'T\(("An update cannot fix this — the key[^"]*")\)', rd("js/screen-overview.js"))
VS = rd("js/views.js")
vkeys = re.findall(r'T\(("(?:AmneziaWG runs on the slower fallback datapath — its kernel module does not|the AmneziaWG kernel module does not compile|Secure Boot refuses the AmneziaWG)[^"]*")', VS)
vkeys += ['"awg interfaces run on the slower fallback datapath"', '"awg interfaces can’t come up"']
check("the master's notice uses the two short halves as T() keys", all(("T(" + k + ")") in VS for k in vkeys[-2:]))
keys += vkeys
check("every new sentence (%d) has its Russian line" % len(keys), len(keys) == 15 and all(("  " + k + ":") in ru for k in keys),
      [k[:60] for k in keys if ("  " + k + ":") not in ru] or len(keys))

print("\n[9] the master's own host")
P2 = tempfile.mkdtemp(prefix="sbhost-")
open(P2 + "/awg-module-failed", "w").write("kernel=%s\nsrc=abc\n" % KR)
with mock.patch.dict(os.environ, {"SWG_NODED_STATE": P2}):
    got = P._host_awg_record("awg-module-failed")
    open(P2 + "/awg-module-failed", "w").write("kernel=4.19.0\nsrc=abc\n")
    other = P._host_awg_record("awg-module-failed")
check("the compile record for this kernel is read; another kernel's is not", bool(got) and other is None, (got, other))
with mock.patch.dict(os.environ, {"SWG_NODED_STATE": P2}):
    open(P2 + "/awg-module-refused", "w").write("kernel=%s\nboot=%s\nmok=/var/lib/shim-signed/mok/MOK.der\n" % (KR, P._host_boot_id()))
    ref = P._host_awg_record("awg-module-refused")
check("the Secure Boot record for this kernel is read, with this boot's id beside it", bool(ref) and ref.get("boot") == P._host_boot_id() != "", ref)
check("…and host_datapath_health turns a BUILT module refused in this boot into not-ok, why=key (+ the key)",
      '_key = bool(built and _ref and _ref.get("boot") and _ref.get("boot") == _host_boot_id())' in PS
      and '"ok": bool(loaded or (built and not _key))' in PS)
VS, OV, SN, AP = rd("js/views.js"), rd("js/screen-overview.js"), rd("js/screen-nodes.js"), rd("app.js")
check("master: the Secure Boot issue is marked as one no update repairs", '"secureboot", dp.mok' in VS and "}), false);" in VS)
check("master: the Fix button counts, and opens, only what an update repairs", "serviceIssues().filter(i => i.fix !== false).length" in AP
      and "issues=${serviceIssues().filter(i => i.fix !== false)}" in AP)
check("master: its hover bubble and the 'can be repaired' toast count only those too",
      "serviceIssues().filter(i => i.fix !== false); if (!iss.length)" in SN and "serviceIssues().some(i => i.fix !== false)" in SN)
check("master: the issue sheet offers no 'Run update' for it, and says why", "const noUpdate = list.every(i => i.id === \"subcert\" || i.fix === false);" in OV
      and "${noUpdate ? null" in OV and "An update cannot fix this" in OV)
check("the master's notice gives the steps for it", 'if (dp.why === "key") add("awg"' in rd("js/views.js"))
check("…and host_datapath_health reports why=compile from it",
      'if not out["awg"]["ok"] and _host_awg_record("awg-module-failed"):\n                out["awg"]["why"] = "compile"' in PS)
check("the master's notice words it without 'running Update rebuilds it'", 'if (dp.why === "compile") add("awg"' in rd("js/views.js"))

if PLANT:
    _pre = {"sbclaim": "refused for its key, amneziawg-go absent", "nlh5-noblacklist": "it asks `modprobe -b`",
            "nlh5-noenforce": "a kernel that enforces no signature", "bl-heal": "the heal on a blacklisted box",
            "bl-back": "the move back onto the kernel on a blacklisted box", "bl-quiet": "the "}[PLANT]
    caught = [f for f in FAILS if f.startswith(_pre)]
    print("\nplant %s: %s" % (PLANT, ("RED as it must be (%d)" % len(caught)) if caught and len(caught) == len(FAILS)
                                     else "NOT CAUGHT — the gate is blind to it" if not caught else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if caught and len(caught) == len(FAILS) else 1)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
sys.exit(1 if FAILS else 0)
