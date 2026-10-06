#!/usr/bin/env python3
"""Self-test — on a slow link to GitHub the installers say what they are doing, give up fast, and do not repeat it.

A home box in Russia, enrolling as a node of a panel in Germany (client report 2026-10-06): after the TLS question the
installer "just hung". It was the next step — AmneziaWG: a SILENT download of amneziawg-go from GitHub (four 180 s attempts),
then on Ubuntu 26.04 a source build whose two `git clone`s had no time limit and wrote only to a log — and install-node.sh
ran that whole chain twice. On a VPS abroad all of it takes seconds, which is why nobody had seen it.

  [1] awg_go_pinned says it is downloading, before it does, and its curl aborts a transfer under 20 KB/s for 20 s
  [2] git_clone_depth1 aborts a clone under 10 KB/s for 30 s and caps the whole clone (timeout 300) where `timeout` exists
  [3] ensure_wg_tools_once runs ensure_wg_tools once per tool per run and hands back its answer, a failure included —
      and every install step in both installers goes through it
  [4] a kernel module that does not build says why (the work dir and its log are deleted right after)

Run: python3 tests/installer_slow_link_selftest.py      (0 = pass)
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
lib, node, host = rd("lib/common.sh"), rd("install-node.sh"), rd("install-host.sh")
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
check("…and the 5-minute cap where timeout exists", all(" timeout 300 git " in l for l in runs), runs)
check("…and never ask for a login", all("GIT_TERMINAL_PROMPT=0" in l for l in runs), runs)

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

print("\n[4] a module that does not build says why")
body = grab(lib, "awg_build_from_source")
check("the failure path warns with a line from the build log", 'warn "the AmneziaWG kernel module did not build for $(uname -r): ${_why:-' in body, "")
check("…before the work dir (and its log) is deleted", body.find("did not build for") < body.rfind('rm -rf "$w"'), "")

print("")
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
