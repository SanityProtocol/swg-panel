#!/usr/bin/env python3
"""Self-test — bootstrap.sh fetches a COMMIT, because that is how a release is named.

Panel releases carry no git tag: each is one squashed commit on main. After the next release, going back to the
previous one means its commit (`SWG_REF=df3bb45` is 1.8.7-beta), and `git clone --branch` takes only a branch or a
tag — so a bare-metal box had no one-command way back (found by the 1.8.8 qualification's rollback section).
A 7–40 hex SWG_REF now comes from GitHub's archive of that commit; a branch or a tag still takes git first.

…and a commit is what to INSTALL, never what to TRACK: the scripts bake SWG_REF into the one-click wrapper and the
node's update_ref, and a box taken back to a commit had an Update button pinned to that commit's bootstrap, which
(1.8.7 and older) cannot fetch a commit — every later Update failed. Section [3] holds the exported SWG_REF to the
branch the box's wrapper already follows (main when none).

The fetch block is lifted out of bootstrap.sh as SHIPPED and run with `git`, `curl` and `tar` as stubs on PATH
that record their arguments. No network.

Run: python3 tests/bootstrap_commit_ref_selftest.py            (0 = pass)
     --perturb        the commit branch taken back out → RED
     --perturb-track  the commit exported as the ref to track (the shipped 314b2e7 behaviour) → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_TRACK = "--perturb-track" in sys.argv
src = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
i = src.index('_fetched=""\n'); j = src.index('cd "$TMP/swg-panel"', i)
block = src[i:j]
if PERTURB_TRACK:
    a = '  export SWG_REF="${_track:-main}"\n'
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, '  export SWG_REF="$REF"\n')
if PERTURB:
    a = "if printf '%s' \"$REF\" | grep -qE '^[0-9a-f]{7,40}$'; then"
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, "if false; then")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def run(ref, wrapper=None, track=None):
    d = tempfile.mkdtemp(); log = os.path.join(d, "log"); tmp = os.path.join(d, "tmp"); os.makedirs(tmp)
    wpath = os.path.join(d, "swg-update")         # the box's one-click wrapper, as update.sh writes it
    if wrapper is not None:
        open(wpath, "w").write('#!/usr/bin/env bash\n{\nURL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/'
                               'SanityProtocol/swg-panel/%s/bootstrap.sh}"\nexit\n}\n' % wrapper)
    blk = block.replace("/usr/local/bin/swg-update", wpath)
    def stub(name, body):
        p = os.path.join(d, name)
        open(p, "w").write('#!/bin/sh\necho "%s $*" >> %s\n%s\n' % (name, log, body)); os.chmod(p, 0o755)
    stub("git", 'exit 0')                               # a clone "succeeds"
    stub("curl", 'echo ARCHIVE; exit 0')
    # tar -xz -C <dir>: lay down what GitHub's archive of a commit unpacks to
    stub("tar", 'for a; do last="$a"; done; mkdir -p "$last/swg-panel-0123456789abcdef0123456789abcdef01234567"; exit 0')
    script = ('set -euo pipefail\nREF=%s\nexport SWG_REF="$REF"\nREPO=https://github.com/SanityProtocol/swg-panel\nTMP=%s\n'
              'need(){ command -v "$1" >/dev/null 2>&1; }\nwarn(){ echo "WARN $*" >&2; }\ninfo(){ echo "INFO $*" >&2; }\n'
              'b(){ printf %%s "$*"; }\ndie(){ echo "DIE $*" >&2; exit 9; }\n%s\necho "FETCHED=$_fetched"; '
              'echo "EXPORTED=$SWG_REF"; ls "$TMP"\n') % (ref, tmp, blk)
    env = dict(os.environ, PATH=d + ":" + os.environ["PATH"]); env.pop("SWG_TRACK", None)
    if track:
        env["SWG_TRACK"] = track
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    calls = open(log).read() if os.path.exists(log) else ""
    return p, calls

print("[1] a release's commit comes from GitHub's archive of that commit")
for ref in ("df3bb45", "df3bb458fa2855c72970441ada9e7f722dcd9d52"):
    p, calls = run(ref)
    check("%s → curl %s/archive/%s.tar.gz, never `git clone --branch`" % (ref[:12], "…", ref[:12]),
          "curl -fsSL https://github.com/SanityProtocol/swg-panel/archive/%s.tar.gz" % ref in calls
          and "git clone" not in calls, calls)
    check("%s → fetched, and the tree lands at $TMP/swg-panel" % ref[:12],
          "FETCHED=tar" in p.stdout and re.search(r"^swg-panel$", p.stdout, re.M), (p.stdout, p.stderr))

print("\n[2] a branch or a tag still takes git first, as before")
for ref in ("main", "dev", "wdtt-qwdtt-1.4.3-4", "cafe"):   # 4 hex chars is too short to be a commit
    p, calls = run(ref)
    check("%s → git clone --depth 1 --branch %s" % (ref, ref), "git clone --depth 1 --branch %s" % ref in calls
          and "archive/%s.tar.gz" % ref not in calls, calls)

print("\n[3] a commit is installed, but the box keeps TRACKING a branch (its Update button must keep working)")
for wrapper, track, want, why in ((None, None, "main", "no wrapper yet → main"),
                                  ("main", None, "main", "the wrapper follows main → main"),
                                  ("dev", None, "dev", "the wrapper follows dev → dev (a pre-release box stays on it)"),
                                  ("df3bb45", None, "main", "the wrapper names a commit (an earlier roll-back) → main"),
                                  ("dev", "main", "main", "SWG_TRACK wins over the wrapper")):
    p, calls = run("df3bb45", wrapper=wrapper, track=track)
    check(why, "EXPORTED=%s\n" % want in p.stdout and "FETCHED=tar" in p.stdout, (p.stdout, p.stderr))
p, calls = run("dev", wrapper="main")
check("a branch is untouched: SWG_REF=dev stays dev whatever the wrapper follows", "EXPORTED=dev\n" in p.stdout, (p.stdout, p.stderr))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_TRACK) else ""))
sys.exit(2 if (PERTURB or PERTURB_TRACK) else 0)
