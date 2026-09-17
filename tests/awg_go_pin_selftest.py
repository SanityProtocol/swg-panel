#!/usr/bin/env python3
"""Self-test — one pinned userspace AmneziaWG datapath, on every bare-metal AWG box (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D1).

A reboot onto a kernel with no amneziawg module took every awg interface down on a box whose module had worked at
install: the userspace fallback awg-quick uses by itself was only ever installed when the module failed THEN.

  [1] one ref: Dockerfile.node's AWG_GO_REF is the version lib/common.sh's AWG_GO_TAG names; the image builds that ref,
      statically, not upstream HEAD.
  [2] the pin is a pin: a 64-hex sha256 per published arch; run for real in a sandbox, a tampered asset is refused, the
      pinned one installs, our earlier pins are replaced and an operator's own binary is kept.
  [3] both installers install the fallback BEFORE the "module already works" return, download only (no Go build).
  [4] update.sh installs it before ensure_awg_datapath's "already working" return, and runs ensure_awg_back_on_kernel
      after ensure_awg_quick_unit.
  [5] ensure_awg_userspace tries the pinned download before any source build.
  [6] forks/amneziawg-go/build.sh reproduces the pin: a full upstream commit for lib's tag, and the Go toolchain lib names.

Run: python3 tests/awg_go_pin_selftest.py    (0 = pass)
     --perturb   moves install-node.sh's fallback line after the early return and lets awg_go_pinned skip its sha256 check; expects RED on [2], [3].
"""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PERTURB = "--perturb" in sys.argv
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond: FAILS.append(name)
rd = lambda p: open(os.path.join(ROOT, p)).read()
lib, dock, upd = rd("lib/common.sh"), rd("Dockerfile.node"), rd("update.sh")
inst = {f: rd(f) for f in ("install-host.sh", "install-node.sh")}
FB = '  awg_go_needs_install && { awg_go_pinned || warn "'
EARLY = "  if have awg && modprobe amneziawg 2>/dev/null; then return 0; fi"
if PERTURB:
    s = inst["install-node.sh"]; i = s.index(FB); e = s.index("\n", i) + 1; line = s[i:e]; s = s[:i] + s[e:]
    j = s.index(EARLY); j = s.index("\n", j) + 1
    inst["install-node.sh"] = s[:j] + line + s[j:]

tag = re.search(r'^AWG_GO_TAG="amneziawg-go-([0-9.]+)"', lib, re.M)
ref = re.search(r'^ARG AWG_GO_REF=v([0-9.]+)$', dock, re.M)
check("[1] Dockerfile ref == lib tag", bool(tag and ref and tag.group(1) == ref.group(1)), (tag and tag.group(1), ref and ref.group(1)))
check("[1] the image clones that ref, statically", '--branch "$AWG_GO_REF"' in dock and "CGO_ENABLED=0 go build" in dock)
for arch in ("amd64", "arm64"):
    m = re.search(r'^AWG_GO_SHA256_%s="([0-9a-f]*)"' % arch, lib, re.M)
    check("[2] sha256 pinned for " + arch, bool(m and re.fullmatch(r"[0-9a-f]{64}", m.group(1))), m and m.group(1))
# [2] BEHAVIOURAL, not a text order: the real awg_go_pinned / awg_go_needs_install run in a sandbox — curl serves a chosen
#     file, /usr/local/bin is a temp dir. A tampered asset must never be installed; our older pin is replaced; an
#     operator's own binary is never touched.
import subprocess, tempfile, hashlib, shutil as _sh
def grab(name):
    i = lib.index(name + "(){"); return lib[i:lib.index("\n}\n", i) + 3]
T = tempfile.mkdtemp()
os.makedirs(T + "/bin"); os.makedirs(T + "/usrlocal"); os.makedirs(T + "/path")
good = T + "/good.bin"; open(good, "wb").write(b"pinned build\n")
bad = T + "/bad.bin"; open(bad, "wb").write(b"tampered\n")
old = T + "/old.bin"; open(old, "wb").write(b"an earlier pinned build\n")
mine = T + "/operator.bin"; open(mine, "wb").write(b"the operator's own amneziawg-go\n")
H = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()
open(T + "/bin/curl", "w").write('#!/bin/sh\nout=""; url=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; http*) url="$1";; esac; shift; done\n'
                                 'case "$url" in https://github.com/*) [ -n "${GH_BLOCKED:-}" ] && exit 7;; esac\ncp "$SERVE" "$out"\n')
os.chmod(T + "/bin/curl", 0o755)
# A PATH without any real amneziawg-go — on a box that has one, "nothing on PATH" would otherwise be false.
CLEAN_PATH = ":".join(d for d in os.environ.get("PATH", "").split(":") if d and not os.path.exists(os.path.join(d, "amneziawg-go")))
fns = (grab("awg_go_pinned") + grab("awg_go_needs_install")).replace("/usr/local/bin/amneziawg-go", T + "/usrlocal/amneziawg-go")
if PERTURB: fns = fns.replace("| sha256sum -c - >/dev/null 2>&1", "| cat >/dev/null")   # the pin stops verifying
def sh(body, serve=good, onpath=None, **env_extra):
    for f in os.listdir(T + "/path"): os.remove(T + "/path/" + f)
    if onpath: _sh.copy(onpath, T + "/path/amneziawg-go"); os.chmod(T + "/path/amneziawg-go", 0o755)
    script = ('set -euo pipefail\nhave(){ command -v "$1" >/dev/null 2>&1; }\nDRYRUN=false\n'
              'AWG_GO_TAG=test; AWG_GO_SHA256_amd64=%s; AWG_GO_SHA256_arm64=%s; AWG_GO_REPLACES="%s"\n%s\n%s\n'
              % (H(good), H(good), H(old), fns, body))
    env = dict(os.environ, PATH=T + "/bin:" + T + "/path:" + CLEAN_PATH, SERVE=serve, **env_extra)
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
r = sh("awg_go_pinned && echo rc=0 || echo rc=$?", serve=bad)
check("[2] a tampered asset is refused and never installed", "rc=1" in r.stdout and not os.path.exists(T + "/usrlocal/amneziawg-go"), r.stdout + r.stderr)
r = sh("awg_go_pinned && echo rc=0 || echo rc=$?", serve=good)
check("[2] the pinned asset installs", "rc=0" in r.stdout and os.path.exists(T + "/usrlocal/amneziawg-go") and H(T + "/usrlocal/amneziawg-go") == H(good), r.stdout + r.stderr)
def fresh():
    if os.path.exists(T + "/usrlocal/amneziawg-go"): os.remove(T + "/usrlocal/amneziawg-go")
fresh(); r = sh("awg_go_pinned && echo rc=0 || echo rc=$?", GH_BLOCKED="1")
check("[2] GitHub blocked, no mirror → not installed", "rc=1" in r.stdout and not os.path.exists(T + "/usrlocal/amneziawg-go"), r.stdout + r.stderr)
fresh(); r = sh("awg_go_pinned && echo rc=0 || echo rc=$?", GH_BLOCKED="1", SWG_TURN_MIRROR="https://ghproxy.example/")
check("[2] GitHub blocked, the operator's mirror serves the pin → installed", "rc=0" in r.stdout and os.path.exists(T + "/usrlocal/amneziawg-go"), r.stdout + r.stderr)
fresh(); r = sh("awg_go_pinned && echo rc=0 || echo rc=$?", serve=bad, GH_BLOCKED="1", SWG_TURN_MIRROR="https://ghproxy.example/")
check("[2] a mirror serving something else → refused", "rc=1" in r.stdout and not os.path.exists(T + "/usrlocal/amneziawg-go"), r.stdout + r.stderr)
nd = lambda onpath: sh("if awg_go_needs_install; then echo NEEDS; else echo KEEP; fi", onpath=onpath).stdout.strip()
check("[2] needs install: nothing on PATH", nd(None) == "NEEDS", nd(None))
check("[2] needs install: one of OUR earlier pins", nd(old) == "NEEDS", nd(old))
check("[2] keeps: the operator's own binary", nd(mine) == "KEEP", nd(mine))
check("[2] keeps: the current pin", nd(good) == "KEEP", nd(good))
for f, s in inst.items():
    body = s[s.index("ensure_wg_tools(){"):]
    body = body[:body.index("\n}\n")]
    check("[3] %s: fallback before the early return" % f, FB in body and EARLY in body and body.index(FB) < body.index(EARLY))
d = upd[upd.index("ensure_awg_datapath(){"):]; d = d[:d.index("\n}\n")]
check("[4] update.sh: pinned install before the 'already working' return",
      "awg_go_pinned" in d and d.index("awg_go_pinned") < d.index('[ "$_tools" = yes ] && [ "$_mod" = yes ] && return 0'))
check("[4] update.sh: back-on-kernel runs after the quick-unit heal",
      re.search(r"^  ensure_awg_quick_unit .*\n  ensure_awg_back_on_kernel", upd, re.M) is not None)
u = lib[lib.index("ensure_awg_userspace(){"):]; u = u[:u.index("\n}\n")]
rec_p = os.path.join(ROOT, "forks", "amneziawg-go", "build.sh")
rec = open(rec_p).read() if os.path.exists(rec_p) else ""
sha = re.search(r'^UPSTREAM_SHA="([0-9a-f]{40})"\s*#\s*tag v([0-9.]+)', rec, re.M)
gov = re.search(r'^GO_VERSION="go([0-9.]+)"', rec, re.M)
check("[6] the recipe pins a full commit whose tag is lib's tag", bool(sha and tag and sha.group(2) == tag.group(1)), sha and sha.groups())
check("[6] lib/common.sh states the recipe's Go toolchain", bool(gov and ("Go " + gov.group(1)) in lib), gov and gov.group(1))
check("[5] pinned download before any source build", "awg_go_pinned" in u and u.index("awg_go_pinned") < u.index("go build"))
# [7] THE BUMP ITSELF. [2] proves the REPLACES MECHANISM works — but it injects its own AWG_GO_REPLACES into the
# sandbox, so it cannot see whether the REAL lib/common.sh has been kept up to date. That is the half that goes
# wrong silently: `awg_go_needs_install` leaves an existing binary alone unless its sha is listed, so bumping the
# pin without moving the superseded sha256s into AWG_GO_REPLACES reaches FRESH INSTALLS ONLY, and every node
# already carrying our previous build keeps it forever. Nothing errors; the upgrade simply does not happen.
# KNOWN_TAG is the fixture: it moves in the same change as the pin, and moving it is the reminder.
KNOWN_TAG = "amneziawg-go-3.1.20260828"          # ⚠️ bump me WITH AWG_GO_TAG, and fill in AWG_GO_REPLACES
_tag_full = re.search(r'^AWG_GO_TAG="([^"]+)"', lib, re.M)
_repl = (re.search(r'^AWG_GO_REPLACES="([^"]*)"', lib, re.M) or [None, ""])[1].split()
_cur = {m.group(1) for m in re.finditer(r'^AWG_GO_SHA256_\w+="([0-9a-f]{64})"', lib, re.M)}
if PERTURB:
    _tag_full = re.match(r'(.*)', "amneziawg-go-9.9.99999999")   # a bump nobody paired with a REPLACES entry
if _tag_full and _tag_full.group(1) == KNOWN_TAG:
    check("[7] the tag is the one this fixture knows — nothing superseded yet", True)
    check("[7] …and no CURRENT pin is listed as replaceable (that would re-install every pass)",
          not (set(_repl) & _cur), _repl)
else:
    check("[7] ⚠️ AWG_GO_TAG moved from %s — the superseded sha256s must be in AWG_GO_REPLACES (else nodes that "
          "already have the old binary keep it forever), and KNOWN_TAG in this file must move with it"
          % KNOWN_TAG, len(_repl) > 0, {"tag": _tag_full and _tag_full.group(1), "replaces": _repl})
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS))); sys.exit(1 if FAILS else 0)
