#!/usr/bin/env python3
"""Self-test — a bare-metal re-install reports "re-installed and updated" only when it updated something, and a run
without a terminal does not fill its log with debconf's complaints.

  [1] install-host.sh and install-node.sh set the lifecycle success to "reinstalled-updated" on EVERY re-install, so
      the panel announced an update after re-installing the very same build. Now the installed programs are hashed
      before and after (lib/common.sh installed_sum — the version stamp cannot tell, a dev build keeps one VERSION
      across many commits); unchanged → "reinstalled". (install-docker.sh compares image ids for the same reason.)
  [2] tty-less installs / converts / updates printed apt's "debconf: (This frontend requires a controlling tty.)",
      four lines per package. With no terminal DEBIAN_FRONTEND=noninteractive is exported — never over a value
      already set.

The pieces are lifted out of the scripts AS SHIPPED and run in a NEW SESSION (no controlling terminal).

Run: python3 tests/reinstall_state_selftest.py     (0 = pass)
     --perturb   "reinstalled" never chosen, and the debconf line taken out → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
H, N, UP, C = rd("install-host.sh"), rd("install-node.sh"), rd("update.sh"), rd("lib/common.sh")
DEB = "if [ -z \"${DEBIAN_FRONTEND:-}\" ] && ! { : </dev/tty; } 2>/dev/null; then export DEBIAN_FRONTEND=noninteractive; fi\n"

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

if PERTURB:
    for v in ("H", "N"):
        src = globals()[v]
        a = "  LC_SUCCESS=reinstalled\nfi\n"
        assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS (%s)" % v
        globals()[v] = src.replace(a, "  :\nfi\n")
    for v in ("H", "N", "UP"):
        assert globals()[v].count(DEB) == 1, "perturbation anchor missing — would FALSE-PASS (%s)" % v
        globals()[v] = globals()[v].replace(DEB, "")

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)
SUM = fn(C, "installed_sum")

print("[1] 're-installed AND updated' only when the installed programs changed")
def after_block(src):
    i = src.index('if [ "${LC_SUCCESS:-}" = reinstalled-updated ] && [ -n "${_SUM_BEFORE:-}" ]')
    return src[i:src.index("\nfi\n", i) + 4]
def args_of(text):
    m = re.search(r'installed_sum (.*?)\)', text)
    return m.group(1) if m else None
for label, src, before_anchor in (("install-host.sh", H, '_SUM_BEFORE="$(installed_sum '), ("install-node.sh", N, '_SUM_BEFORE="$(installed_sum ')):
    blk = after_block(src)
    before_line = src[src.index(before_anchor):src.index("\n", src.index(before_anchor))]
    check("%s: the before and after hashes cover the SAME paths (else the comparison means nothing)" % label,
          args_of(before_line) == args_of(blk), (before_line, blk))
    for changed, want in ((False, "reinstalled"), (True, "reinstalled-updated")):
        d = tempfile.mkdtemp(prefix="rst-")
        for sub in ("panel", "sub", "noded", "agent"):
            os.makedirs(os.path.join(d, sub)); open(os.path.join(d, sub, "prog"), "w").write("v1\n")
        script = ('set -euo pipefail\n%sPANEL_DIR=%s/panel; SUB_DIR=%s/sub; NODED_DIR=%s/noded; AGENT_DIR=%s/agent\n'
                  'LC_SUCCESS=reinstalled-updated\n%s\n%s%s\necho "LC_SUCCESS=$LC_SUCCESS"\n') % (
            SUM, d, d, d, d, before_line.strip(),
            ("echo v2 > %s/noded/prog\n" % d) if changed else "", blk)
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        check("%s: %s → %s" % (label, "a program changed" if changed else "the same build re-installed", want),
              ("LC_SUCCESS=%s\n" % want) in r.stdout, r.stdout + r.stderr)
d = tempfile.mkdtemp(prefix="rst0-")
r = subprocess.run(["bash", "-c", SUM + "installed_sum %s/none; echo \"[$?]\"" % d], capture_output=True, text=True)
check("installed_sum over nothing installed prints nothing and never fails (a first install)", r.stdout.strip() == "[0]", r.stdout)

print("\n[2] no terminal → DEBIAN_FRONTEND=noninteractive, never over a value already set")
for label, src in (("install-host.sh", H), ("install-node.sh", N), ("update.sh", UP)):
    line = DEB if DEB in src else ":\n"
    for preset, want in (("", "noninteractive"), ("readline", "readline")):
        env = dict(os.environ); env.pop("DEBIAN_FRONTEND", None)
        if preset:
            env["DEBIAN_FRONTEND"] = preset
        r = subprocess.run(["bash", "-c", line + 'echo "DF=${DEBIAN_FRONTEND:-}"'], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, start_new_session=True)
        check("%s: %s → DEBIAN_FRONTEND=%s" % (label, "preset " + preset if preset else "unset", want), ("DF=%s\n" % want) in r.stdout, r.stdout)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
