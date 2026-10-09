#!/usr/bin/env python3
"""Self-test — on a slow link to GitHub the installers say what they are doing, give up fast, and do not repeat it.

A home box in Russia, enrolling as a node of a panel in Germany (client report 2026-10-06): after the TLS question the
installer "just hung". It was the next step — AmneziaWG: a SILENT download of amneziawg-go from GitHub (four 180 s attempts),
then on Ubuntu 26.04 a source build whose two `git clone`s had no time limit and wrote only to a log — and install-node.sh
ran that whole chain twice. On a VPS abroad all of it takes seconds, which is why nobody had seen it.

  [1] awg_go_pinned says it is downloading, before it does, and its curl aborts a transfer under 20 KB/s for 20 s
  [2] git_clone_depth1 aborts a clone under 10 KB/s for 30 s and caps the whole clone (timeout 300) where `timeout` exists
  [2b] (1.8.9 qualification IN-4) a Ctrl-C during the clone or the upstream ls-remote ends the run at once — run in a pty,
      the real functions, a stub git that takes 8 s: before, timeout took git into a process group of its own, the Ctrl-C
      never reached it, and the run carried on once the clone ended (the ls-remote's pipeline died only when it ended)
  [2c] (IN-21) a clone that hit the cap is not tried again over HTTP/1.1 (that doubled a slow link's wait); a clone that
      failed fast (the HTTP/2 401) still is
  [3] ensure_wg_tools_once runs ensure_wg_tools once per tool per run and hands back its answer, a failure included —
      and every install step in both installers goes through it
  [3b] (1.8.9 qualification IN-18) …except where an interface is STARTED (`again`): a tool that failed earlier in the run
      (a dpkg lock held at the tooling step, unattended-upgrades) is tried once more there — kept, an adopted wg0 stayed
      DOWN after an rc-0 Docker → bare convert; once per tool per run, so a chain that really fails is not repeated per
      interface; the switch's bring-up and both installers' create loops ask it
  [3c] (1.8.9 qualification F21, a regression vs 1.8.8) the REAL ensure_wg_tools awg on a pristine Docker-first box whose dpkg
      lock is held through the tooling step (the PPA locked out, no make/gcc for the source build, amneziawg-go downloads):
      the userspace fallback is a DATAPATH, not the tools — with no awg / awg-quick that is a failure, so the switch's
      `again` tries once more and installs them once the lock is free. It returned success, the memo kept it, `again`
      never retried, and awg0 + both mesh links were DOWN after an rc-0 convert ("awg-quick: command not found")
  [4] a kernel module that does not build says why (the work dir and its log are deleted right after)

Run: python3 tests/installer_slow_link_selftest.py      (0 = pass)
     --perturb        a failure is final again, `again` or not (52aa9c4) → RED on [3b]
     --perturb-fg     timeout without --foreground at both sites (e66018f) → RED on [2b] only
     --perturb-retry  a timed-out clone is tried again over HTTP/1.1 (e66018f) → RED on [2c] only
     --perturb-f21    the userspace fallback counted as the tools again (q189-int2) → RED on [3c] only
"""
import os, pty, re, select, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
PERTURB = "--perturb" in sys.argv[1:]
PERTURB_FG = "--perturb-fg" in sys.argv[1:]
PERTURB_RETRY = "--perturb-retry" in sys.argv[1:]
PERTURB_F21 = "--perturb-f21" in sys.argv[1:]
lib, node, host = rd("lib/common.sh"), rd("install-node.sh"), rd("install-host.sh")
if PERTURB_FG:
    assert lib.count("timeout --foreground 300") == 1 and lib.count("timeout --foreground 30\"") == 1, \
        "perturbation anchor missing — would FALSE-PASS"
    lib = lib.replace("timeout --foreground 300", "timeout 300").replace("timeout --foreground 30\"", "timeout 30\"")
if PERTURB_RETRY:
    _a = '  [ "$_rc" != 124 ] || return 124\n'
    assert lib.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    lib = lib.replace(_a, "")
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
def grab(src, name):
    i = src.index("\n" + name + "(){") + 1
    return src[i:src.index("\n}\n", i) + 3]
T = tempfile.mkdtemp(prefix="slowlink-")
os.makedirs(T + "/bin")
def sh(script, **env_extra):
    env = dict(os.environ, PATH=T + "/bin:" + os.environ.get("PATH", ""), T=T, **env_extra)
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
STUBS = 'have(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'

print("[1] awg_go_pinned")
open(T + "/bin/curl", "w").write('#!/bin/sh\necho "CURL $*" >> "$T/curl.log"\nexit 28\n')   # a link that crawls: "operation too slow"
os.chmod(T + "/bin/curl", 0o755)
r = sh(STUBS + 'AWG_GO_TAG=t; AWG_GO_SHA256_amd64=x; AWG_GO_SHA256_arm64=x\n' + grab(lib, "awg_go_pinned")
       + 'awg_go_pinned && echo rc=0 || echo rc=$?\n')
out = r.stdout
cl = open(T + "/curl.log").read() if os.path.exists(T + "/curl.log") else ""
check("it says it is downloading, before the download", out.find("INFO downloading the AmneziaWG userspace fallback") != -1
      and out.find("INFO downloading") < out.find("rc="), out + r.stderr)
check("…and the download aborts on a crawl (--speed-limit 20480 --speed-time 20)", "--speed-limit 20480 --speed-time 20" in cl, cl)
check("…with two retries, not three", "--retry 2 " in cl and "--retry 3" not in cl, cl)
check("a failed download is not installed (rc 1)", "rc=1" in out, out)

print("\n[2] git_clone_depth1")
r = sh(STUBS + 'run(){ echo "RUN $*"; return 1; }\n' + grab(lib, "git_clone_depth1") + 'git_clone_depth1 https://github.com/x/y /tmp/none || true\n')
runs = [l for l in r.stdout.splitlines() if l.startswith("RUN ")]
check("both attempts carry the low-speed abort", len(runs) == 2 and all("http.lowSpeedLimit=10240" in l and "http.lowSpeedTime=30" in l for l in runs), runs)
check("…and the 5-minute cap where timeout exists", all(re.search(r" timeout (--foreground )?300 git ", l) for l in runs), runs)
check("…and never ask for a login", all("GIT_TERMINAL_PROMPT=0" in l for l in runs), runs)

print("\n[2b] a Ctrl-C during the clone or the ls-remote ends the run at once (IN-4)")
def grab_line_fn(src, name):   # a one-statement function closed by `; }` (awg_module_head)
    i = src.index("\n" + name + "(){") + 1
    return src[i:src.index("; }\n", i) + 4]
def ctrl_c(fn_src, call):
    """the script in a pty (its own session, the foreground group of its terminal), a Ctrl-C once the stub git runs"""
    G = tempfile.mkdtemp(prefix="ctrlc-", dir=T)
    os.makedirs(G + "/bin")
    open(G + "/bin/git", "w").write('#!/bin/bash\necho "GIT $*" >> "$G/git.log"\nsleep 8\n')
    os.chmod(G + "/bin/git", 0o755)
    open(G + "/s.sh", "w").write('set -euo pipefail\nhave(){ command -v "$1" >/dev/null 2>&1; }\nrun(){ "$@"; }\n' + fn_src
                                 + call + '\necho CONTINUED\n')
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(PATH=G + "/bin:" + os.environ.get("PATH", ""), G=G)
        os.execvp("bash", ["bash", G + "/s.sh"])
    out, sent, st, t0 = b"", None, None, time.time()
    while st is None:
        if sent is None and os.path.exists(G + "/git.log"):
            time.sleep(0.3)
            os.write(fd, b"\x03"); sent = time.time()
        if time.time() - t0 > 30:
            os.kill(pid, 9)
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                d = os.read(fd, 4096)
            except OSError:
                d = b""
            out += d
            if d:
                continue
        p, s_ = os.waitpid(pid, os.WNOHANG) if r == [] else os.waitpid(pid, 0)
        if p:
            st = s_
    os.close(fd)
    took = time.time() - sent if sent else 99.0
    runs = open(G + "/git.log").read().count("GIT ") if os.path.exists(G + "/git.log") else 0
    return dict(took=took, sigint=os.WIFSIGNALED(st) and os.WTERMSIG(st) == 2, runs=runs,
                out=out.decode(errors="replace").replace("\r", ""))
for name, fn_src, call in (
        ("the clone (git_clone_depth1)", grab(lib, "git_clone_depth1"), 'git_clone_depth1 https://github.com/x/y "$G/d" || echo "rc=$?"'),
        ("the upstream ls-remote (awg_module_head)", grab_line_fn(lib, "awg_module_head"), 'h="$(awg_module_head)"; echo "head=[$h]"')):
    r = ctrl_c(fn_src, call)
    check("%s: the run ends within 3 s of the Ctrl-C, killed by it, nothing after it runs" % name,
          r["took"] < 3 and r["sigint"] and "CONTINUED" not in r["out"] and r["runs"] == 1,
          "%.1f s after the Ctrl-C, SIGINT=%s, git runs %d, output %r" % (r["took"], r["sigint"], r["runs"], r["out"][-200:]))

print("\n[2c] a clone that hit the cap is not tried again; one that failed fast is (IN-21)")
_fn = grab(lib, "git_clone_depth1")
_short = re.sub(r"timeout (--foreground )?300", lambda m: "timeout " + (m.group(1) or "") + "2", _fn)
assert _short != _fn, "the cap's anchor is missing"
open(T + "/bin/git", "w").write('#!/bin/bash\necho "GIT $*" >> "$T/git.log"\n[ -n "${FAST:-}" ] && exit 128\nexec sleep 6\n')
os.chmod(T + "/bin/git", 0o755)
for fast in ("", "1"):
    if os.path.exists(T + "/git.log"):
        os.unlink(T + "/git.log")
    r = sh(STUBS + 'run(){ "$@"; }\n' + _short + 'git_clone_depth1 https://github.com/x/y "$T/d" && echo rc=0 || echo rc=$?\n', FAST=fast)
    gl = open(T + "/git.log").read().splitlines() if os.path.exists(T + "/git.log") else []
    if not fast:
        check("a clone that hit the cap: one attempt, rc 124 (the timeout's)", len(gl) == 1 and "rc=124" in r.stdout,
              "%s %s" % (gl, r.stdout + r.stderr))
    else:
        check("a clone that failed fast: tried again over HTTP/1.1", len(gl) == 2 and "http.version=HTTP/1.1" in gl[1]
              and "http.version" not in gl[0] and "rc=128" in r.stdout, "%s %s" % (gl, r.stdout + r.stderr))
os.unlink(T + "/bin/git")

print("\n[3] ensure_wg_tools_once")
for f, src in (("install-node.sh", node), ("install-host.sh", host)):
    once = grab(src, "ensure_wg_tools_once")
    r = sh('set -euo pipefail\nN=0\nensure_wg_tools(){ N=$((N+1)); echo "RUN $1" >&2; [ "$1" = wg ]; }\n' + once
           + 'ensure_wg_tools_once awg && echo a1=0 || echo a1=$?\nensure_wg_tools_once awg && echo a2=0 || echo a2=$?\n'
           + 'ensure_wg_tools_once wg && echo w1=0 || echo w1=$?\nensure_wg_tools_once wg && echo w2=0 || echo w2=$?\necho N=$N\n')
    check("%s: one run per tool (awg + wg = 2)" % f, "N=2" in r.stdout, r.stdout + r.stderr)
    check("%s: a failure is handed back the second time too" % f, "a1=1" in r.stdout and "a2=1" in r.stdout, r.stdout)
    check("%s: a success likewise" % f, "w1=0" in r.stdout and "w2=0" in r.stdout, r.stdout)
    bare = [l for l in src.splitlines() if re.search(r"(?<![_\w])ensure_wg_tools (awg|wg|\"\$)", l) and "ensure_wg_tools_once" not in l
            and not l.lstrip().startswith("#") and "ensure_wg_tools \"$1\" && _rc" not in l]
    check("%s: every install step goes through it" % f, not bare, bare)

print("\n[3b] a failure is tried once more where an interface is started (IN-18)")
for f, src in (("install-node.sh", node), ("install-host.sh", host)):
    once = grab(src, "ensure_wg_tools_once")
    if PERTURB:
        _c = '{ [ "${!_v}" = 0 ] || [ -z "${2:-}" ] || [ -n "${!_a:-}" ]; }'
        assert once.count(_c) == 1, "perturbation anchor missing — would FALSE-PASS"
        once = once.replace(_c, "true")
    r = sh('set -euo pipefail\nN=0\nLOCK=1\nensure_wg_tools(){ N=$((N+1)); [ "$LOCK" = 0 ]; }\n' + once
           + 'ensure_wg_tools_once wg && echo t=0 || echo t=$?\n'                   # Datapath tooling: dpkg's lock held
           + 'LOCK=0\nensure_wg_tools_once wg again && echo s1=0 || echo s1=$?\n'   # the switch: the lock is gone
           + 'ensure_wg_tools_once wg again && echo s2=0 || echo s2=$?\nensure_wg_tools_once wg && echo e=0 || echo e=$?\necho N=$N\n')
    check("%s: the tooling step fails on dpkg's lock; the switch's bring-up tries again and the tool is there" % f,
          "t=1" in r.stdout and "s1=0" in r.stdout and "s2=0" in r.stdout and "e=0" in r.stdout and "N=2" in r.stdout, r.stdout + r.stderr)
    r = sh('set -euo pipefail\nN=0\nensure_wg_tools(){ N=$((N+1)); return 1; }\n' + once
           + 'ensure_wg_tools_once awg || true\nfor i in 1 2 3; do ensure_wg_tools_once awg again || true; done\necho N=$N\n')
    check("%s: a chain that really fails is tried once more, not once per interface" % f, "N=2" in r.stdout, r.stdout + r.stderr)
check("install-node.sh: the switch's bring-up of adopted interfaces asks `again`",
      'ensure_wg_tools_once "$_c" again || continue' in node)
check("install-node.sh: the closing \"for future interface creation\" check asks `again` for wg (apt only), not for awg "
      "(its GitHub chain is what the memo is for)",
      'ensure_wg_tools_once wg again || warn "wireguard tools not installed' in node
      and 'ensure_wg_tools_once awg || warn "amneziawg tools not installed' in node)
check("both installers' create loops ask `again`",
      node.count('if ! ensure_wg_tools_once "$cmd" again; then') == 1 and host.count('if ! ensure_wg_tools_once "$cmd" again; then') == 1)

print("\n[3c] the userspace fallback is not the tools: a box left without awg / awg-quick is a failure, tried `again` (F21)")
F21 = "    have awg && have awg-quick || return 1   # a datapath, not the tools"
STUB = ('set -euo pipefail\nDRYRUN=false\ninfo(){ :; }\nwarn(){ echo "WARN $*"; }\nrun(){ "$@"; }\n'
        'have(){ case "$1" in awg|awg-quick) [ -e "$T/f21/tools" ];; amneziawg-go) [ -e "$T/f21/go" ];; apt-get) return 0;; '
        '*) command -v "$1" >/dev/null 2>&1;; esac; }\n'
        'modprobe(){ [ -e "$T/f21/tools" ]; }\nawg_go_needs_install(){ return 1; }\nawg_ppa_suite(){ echo noble; }\napt-get(){ :; }\n'
        'awg_ppa_add(){ :; }\nensure_awg_headers_follow(){ :; }\nawg_dkms_drop_unowned(){ :; }\nbuild_awg_module(){ :; }\n'
        'awg_mod_key_rejected(){ return 1; }\nawg_tools_drive_3x(){ return 1; }\n'
        'awg_ppa_module_install(){ echo PPA >> "$T/f21/calls"; [ -e "$T/f21/locked" ] && return 1; touch "$T/f21/tools"; }\n'   # dpkg's lock held → nothing installed
        'awg_build_from_source(){ echo SRC >> "$T/f21/calls"; return 1; }\n'          # no make / gcc on a Docker-first box
        'ensure_awg_userspace(){ touch "$T/f21/go"; }\n')                             # the pinned amneziawg-go downloads
for f, src in (("install-node.sh", node), ("install-host.sh", host)):
    fn = grab(src, "ensure_wg_tools")
    if PERTURB_F21:
        assert fn.count(F21) == 1, "perturbation anchor missing — would FALSE-PASS"
        fn = fn.replace(F21 + "\n", "")
    import shutil
    shutil.rmtree(T + "/f21", ignore_errors=True); os.makedirs(T + "/f21"); open(T + "/f21/locked", "w").close()
    r = sh(STUB + fn + grab(src, "ensure_wg_tools_once")
           + 'ensure_wg_tools_once awg && echo T=0 || echo T=$?\n'                          # Datapath tooling: dpkg's lock held
           + 'echo "TOOLS1=$(have awg-quick && echo yes || echo no)"\nrm -f "$T/f21/locked"\n'
           + 'ensure_wg_tools_once awg again && echo S=0 || echo S=$?\n'                    # the switch's bring-up: the lock is gone
           + 'echo "TOOLS2=$(have awg-quick && echo yes || echo no)"\n')
    calls = open(T + "/f21/calls").read().split()
    check("%s: locked out at the tooling step, amneziawg-go there, no awg / awg-quick → a FAILURE, not the userspace datapath" % f,
          "T=1" in r.stdout and "TOOLS1=no" in r.stdout and "SLOWER userspace datapath" not in r.stdout, r.stdout + r.stderr)
    check("%s: …so the switch's `again` tries once more and installs the tools once the lock is free" % f,
          "S=0" in r.stdout and "TOOLS2=yes" in r.stdout and calls.count("PPA") == 2, (r.stdout, calls))
    shutil.rmtree(T + "/f21", ignore_errors=True); os.makedirs(T + "/f21"); open(T + "/f21/tools", "w").close()
    r = sh(STUB.replace('modprobe(){ [ -e "$T/f21/tools" ]; }', 'modprobe(){ return 1; }')
           .replace('touch "$T/f21/tools"; }', 'return 1; }') + fn + 'ensure_wg_tools awg && echo R=0 || echo R=$?\n')
    check("%s: CONTROL — the tools there, no module: the userspace datapath, a success, said as such" % f,
          "R=0" in r.stdout and "SLOWER userspace datapath" in r.stdout, r.stdout + r.stderr)

print("\n[4] a module that does not build says why")
body = grab(lib, "awg_build_from_source")
check("the failure path warns with a line from the build log", 'warn "the AmneziaWG kernel module did not build for $(uname -r): ${_why:-' in body, "")
check("…before the work dir (and its log) is deleted", body.find("did not build for") < body.rfind('rm -rf "$w"'), "")

print("")
for _on, _sec, _pick in ((PERTURB, "[3b]", lambda f: "tries again" in f or "tried once more" in f),
                         (PERTURB_F21, "[3c]", lambda f: "locked out at the tooling step" in f or "`again` tries once more" in f),
                         (PERTURB_FG, "[2b]", lambda f: "the Ctrl-C" in f),
                         (PERTURB_RETRY, "[2c]", lambda f: "hit the cap" in f)):
    if _on:
        _red = [f for f in FAILS if _pick(f)]
        print("perturb: %s" % ("RED as it must be (%d), all %s" % (len(_red), _sec) if _red and len(_red) == len(FAILS)
                               else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
        sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
