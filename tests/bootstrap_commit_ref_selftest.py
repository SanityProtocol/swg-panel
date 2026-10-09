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

[4] (1.8.9 qualification SOAK-3) …and on Docker a commit moves the SCRIPTS, not the containers (they run the published
    `latest`; images are tagged sha-<7>): bootstrap also exports the commit (SWG_COMMIT), and install-docker.sh and
    update.sh say so plainly, naming SWG_IMAGE_TAG=sha-<7> — silent where a tag is pinned (.env or the environment) or
    built from source. (SWG_REF is the tracked branch, so the old "not main" warning never fired for a commit.)

Run: python3 tests/bootstrap_commit_ref_selftest.py            (0 = pass)
     --perturb        the commit branch taken back out → RED
     --perturb-track  the commit exported as the ref to track (the shipped 314b2e7 behaviour) → RED
     --perturb-commit no SWG_COMMIT, no commit warning (e66018f) → RED on [4] only
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_TRACK = "--perturb-track" in sys.argv
PERTURB_COMMIT = "--perturb-commit" in sys.argv
src = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
i = src.index('_fetched=""\n'); j = src.index('cd "$TMP/swg-panel"', i)
block = src[i:j]
if PERTURB_COMMIT:
    a = '  export SWG_COMMIT="$REF"'
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, "  :")
if PERTURB_TRACK:
    a = '  export SWG_REF="${_track:-main}"\n'
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, '  export SWG_REF="$REF"\n')
if PERTURB:
    a = "if printf '%s' \"$REF\" | grep -cE '^[0-9a-f]{7,40}$' >/dev/null; then"
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
              'echo "EXPORTED=$SWG_REF"; echo "COMMIT=${SWG_COMMIT:-}"; ls "$TMP"\n') % (ref, tmp, blk)
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

print("\n[4] a commit on Docker: the containers do not follow it, and that is said (SOAK-3)")
p, calls = run("df3bb45")
check("a commit → bootstrap exports it as SWG_COMMIT (beside the branch it tracks)", "COMMIT=df3bb45\n" in p.stdout, (p.stdout, p.stderr))
p, calls = run("dev")
check("…a branch → no SWG_COMMIT", "COMMIT=\n" in p.stdout, (p.stdout, p.stderr))
dk = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
a = dk.index("_pinned_tag(){"); b = dk.index("\nfi\n", dk.index("images are built from", a)) + 4
WARN = dk[a:b]
up = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
m = re.search(r'\n( *if \[ -n "\$\{SWG_COMMIT:-\}" \][^\n]*\n[^\n]*; fi)\n', up)
UWARN = m.group(1) if m else 'echo "UPDATE WARNING NOT FOUND"'
if PERTURB_COMMIT:
    assert WARN.count('[ -n "${SWG_COMMIT:-}" ]') == 1 and m, "perturbation anchor missing — would FALSE-PASS"
    WARN = WARN.replace('[ -n "${SWG_COMMIT:-}" ]', "false"); UWARN = ":"
def warnings(env, envfile=None, build="false"):
    d = tempfile.mkdtemp()
    if envfile is not None:
        open(os.path.join(d, ".env"), "w").write(envfile)
    script = ('set -euo pipefail\nBUILD=%s; INSTALL_DIR=%s; DOCKER_DIR=%s\nb(){ printf %%s "$*"; }\nwarn(){ echo "WARN $*"; }\n%s\n%s\n'
              % (build, d, d, WARN, UWARN))
    e = {k: v for k, v in os.environ.items() if k not in ("SWG_REF", "SWG_COMMIT", "SWG_IMAGE_TAG")}
    e.update(env)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e)
r = warnings({"SWG_REF": "main", "SWG_COMMIT": "df3bb458fa2855c72970441ada9e7f722dcd9d52"}, envfile="PANEL_DOMAIN=x\n")
w = [l for l in r.stdout.splitlines() if l.startswith("WARN")]
check("a commit, nothing pinned → install-docker.sh and update.sh each say the containers run latest, naming sha-df3bb45",
      len(w) == 2 and all("df3bb45" in l and "latest" in l for l in w) and "SWG_IMAGE_TAG=sha-df3bb45" in r.stdout, (r.stdout, r.stderr))
r = warnings({"SWG_REF": "main", "SWG_COMMIT": "df3bb45"}, envfile="SWG_IMAGE_TAG=sha-df3bb45\n")
check("…a tag pinned in .env → silent", "WARN" not in r.stdout and r.returncode == 0, (r.stdout, r.stderr))
r = warnings({"SWG_REF": "main", "SWG_COMMIT": "df3bb45", "SWG_IMAGE_TAG": "sha-df3bb45"}, envfile="")
check("…a tag pinned in the environment → silent", "WARN" not in r.stdout and r.returncode == 0, (r.stdout, r.stderr))
r = warnings({"SWG_REF": "main"}, envfile="")
check("CONTROL: main, no commit → silent", "WARN" not in r.stdout and r.returncode == 0, (r.stdout, r.stderr))
r = warnings({"SWG_REF": "dev"}, envfile="")
check("CONTROL: a branch → install-docker.sh's branch warning, as before", r.stdout.count("WARN") == 1 and "installing scripts from dev" in r.stdout,
      (r.stdout, r.stderr))

print()
if PERTURB_COMMIT:
    _red = [f for f in FAILS if f.startswith(("a commit", "…a branch"))]
    print("perturb-commit: %s" % ("RED as it must be (%d), all [4]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_TRACK) else ""))
sys.exit(2 if (PERTURB or PERTURB_TRACK) else 0)
