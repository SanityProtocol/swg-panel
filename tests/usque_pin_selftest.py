#!/usr/bin/env python3
"""Self-test — the pinned usque build (1.8.12 item 17b P1, docs/WARP-MASQUE-PLAN.md §1.4, §4.2).

swg-noded will fetch usque only when its bytes hash to USQ_SHA256, so the pin, the recipe that makes those bytes and the
CI step that refuses a build which does not make them must agree. The bytes themselves are proven by CI (two runs per
arch, plan §6 P1); this checks the parts that can drift without a build.

  [1] the pin: USQ_TAG names the recipe's upstream commit, USQ_OWNER is set, a 64-hex sha256 for amd64 and arm64.
  [2] the recipe: forks/usque/build.sh pins a full upstream commit and go1.27.1 — the workflow's GO_PIN — with the
      reproducible flags, and refuses any other Go before it fetches anything.
  [3] the workflow: a `usque` choice, its resolve row (forks/usque/build.sh, asset usque-linux, kind go), and the
      upstream licence named for the release notes.
  [4] the verify step, run as written (GitHub expressions filled in): a build matching USQ_SHA256 passes on both arches;
      a wrong pin, a missing arch and a missing USQ_SHA256 fail it; amneziawg-go is still checked against lib/common.sh.
  [5] publishing usque: the release tag must be USQ_TAG; another fork's tag is not held to it.

Run: python3 tests/usque_pin_selftest.py    (0 = pass)
     --perturb   makes the verify step read the pin it is handed as always right, and drops the publish step's tag
                 check; expects RED on [4] and [5].
"""
import ast, os, re, shutil, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PERTURB = "--perturb" in sys.argv
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond: FAILS.append(name)
rd = lambda p: open(os.path.join(ROOT, p)).read()
noded, build, wf, lib = rd("swg-noded"), rd("forks/usque/build.sh"), rd(".github/workflows/fork-binaries.yml"), rd("lib/common.sh")

# [1] the pin
tag = re.search(r'^USQ_TAG = "usque-(\d{8})-([0-9a-f]{7})(?:-[2-9]|-[1-9]\d+)?"$', noded, re.M)   # -2, -3… = a rebuild
owner = re.search(r'^USQ_OWNER = "([\w.-]+/[\w.-]+)"$', noded, re.M)
pins = re.search(r'^USQ_SHA256 = (\{.*?\})', noded, re.S | re.M)
pins = ast.literal_eval(pins.group(1)) if pins else {}
sha = re.search(r'^UPSTREAM_SHA="([0-9a-f]{40})"', build, re.M)
check("[1] USQ_TAG names the recipe's upstream commit", bool(tag and sha and sha.group(1).startswith(tag.group(2))),
      (tag and tag.groups(), sha and sha.group(1)))
check("[1] USQ_OWNER is an owner/repo", bool(owner))
check("[1] USQ_SHA256: a 64-hex sha256 for amd64 and arm64",
      sorted(pins) == ["amd64", "arm64"] and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in pins.values()), pins)

# [2] the recipe
gov = re.search(r'^GO_VERSION="(go[\d.]+)"', build, re.M)
gopin = re.search(r'^  GO_PIN: "([\d.]+)"', wf, re.M)
check("[2] the recipe pins go1.27.1, the workflow's GO_PIN", bool(gov and gopin and gov.group(1) == "go1.27.1"
      and gov.group(1) == "go" + gopin.group(1)), (gov and gov.group(1), gopin and gopin.group(1)))
check("[2] the reproducible flags", all(f in build for f in ("CGO_ENABLED=0", "GOFLAGS=-buildvcs=false",
      'go build -trimpath -ldflags="-s -w"', 'UPSTREAM_REPO="https://github.com/Diniboy1123/usque"')))
tmp = tempfile.mkdtemp(prefix="usqpin.")
try:
    fake = os.path.join(tmp, "bin"); os.makedirs(fake)
    for name, body in (("go", 'echo go1.27.0\n'), ("git", 'touch "%s/git-ran"; exit 1\n' % tmp)):
        p = os.path.join(fake, name); open(p, "w").write("#!/bin/sh\n" + body); os.chmod(p, 0o755)
    r = subprocess.run(["bash", os.path.join(ROOT, "forks/usque/build.sh"), os.path.join(tmp, "out")],
                       env=dict(os.environ, PATH=fake + ":/usr/bin:/bin"), capture_output=True, text=True)
    check("[2] another Go is refused before anything is fetched", r.returncode != 0 and "needs go1.27.1" in r.stderr
          and not os.path.exists(os.path.join(tmp, "git-ran")), (r.returncode, r.stderr[-200:]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# [3] the workflow
opts = re.search(r'^        options: \[([^\]]*)\]', wf, re.M)
check("[3] `usque` is a choice", bool(opts and "usque" in [o.strip() for o in opts.group(1).split(",")]))
check("[3] its resolve row", bool(re.search(r'^\s+usque\)\s+script=forks/usque/build.sh;\s+asset=usque-linux\s*;\s+kind=go\s*;;',
                                             wf, re.M)))
check("[3] the release notes carry upstream's licence", "lic=forks/usque/LICENSE.md" in wf
      and os.path.isfile(os.path.join(ROOT, "forks/usque/LICENSE.md"))
      and "MIT License" in rd("forks/usque/LICENSE.md"))

# [4] the verify step, as written
def step_body(text, name):
    lines = text.split("\n")
    i = next(k for k, l in enumerate(lines) if l.strip() == "- name: " + name)
    j = next(k for k in range(i, len(lines)) if lines[k].strip() == "run: |")
    ind = len(lines[j + 1]) - len(lines[j + 1].lstrip())
    out = []
    for l in lines[j + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) < ind:
            break
        out.append(l[ind:])
    return "\n".join(out)
body = step_body(wf, "verify against the installer's pin")
if PERTURB:
    body = body.replace('[ "$want" = "$got" ]', '[ "$want" = "$want" ]')
def verify(fork, arch, got, noded_text=noded, lib_text=lib):
    asset = {"usque": "usque-linux", "amneziawg-go": "amneziawg-go-linux"}[fork] + "-" + arch
    run = re.sub(r"\$\{\{ ([^}]+) \}\}", lambda m: {"inputs.fork": fork, "matrix.arch": arch,
                                                     "steps.f.outputs.asset": asset}[m.group(1)], body)
    t = tempfile.mkdtemp(prefix="usqpin.")
    try:
        os.makedirs(os.path.join(t, "out")); os.makedirs(os.path.join(t, "lib"))
        open(os.path.join(t, "swg-noded"), "w").write(noded_text)
        open(os.path.join(t, "lib", "common.sh"), "w").write(lib_text)
        open(os.path.join(t, "out", asset + ".sha256"), "w").write("%s  out/%s\n" % (got, asset))
        return subprocess.run(["bash", "-c", run], cwd=t, capture_output=True, text=True).returncode
    finally:
        shutil.rmtree(t, ignore_errors=True)
for a in ("amd64", "arm64"):
    check("[4] %s: the pinned bytes pass" % a, verify("usque", a, pins.get(a, "")) == 0)
    wrong = pins.get(a, "0" * 64)[:-1] + ("0" if pins.get(a, "")[-1:] != "0" else "1")
    check("[4] %s: a build that is not the pin fails" % a, verify("usque", a, wrong) != 0)
check("[4] a missing arch fails", verify("usque", "arm64", pins.get("arm64", ""),
                                        noded.replace('"arm64": "%s"' % pins.get("arm64"), '"arm6x": "x"')) != 0)
check("[4] no USQ_SHA256 fails", verify("usque", "amd64", pins.get("amd64", ""),
                                       noded.replace("USQ_SHA256 = {", "USQ_SHA = {")) != 0)
awg = re.search(r'^AWG_GO_SHA256_amd64="([0-9a-f]{64})"', lib, re.M)
check("[4] amneziawg-go: its pin still passes, a wrong one fails", bool(awg)
      and verify("amneziawg-go", "amd64", awg.group(1)) == 0 and verify("amneziawg-go", "amd64", "f" * 64) != 0)

# [5] publishing: usque's release tag must be USQ_TAG — swg-noded downloads from exactly that tag (review F3)
pub = step_body(wf, "the tag is required to publish")
if PERTURB:
    pub = pub.replace('[ "${{ inputs.tag }}" = "$want" ]', 'true')
def publish_check(fork, tag_in):
    run = re.sub(r"\$\{\{ ([^}]+) \}\}", lambda m: {"inputs.fork": fork, "inputs.tag": tag_in}[m.group(1)], pub)
    t = tempfile.mkdtemp(prefix="usqpin.")
    try:
        os.makedirs(os.path.join(t, "bin"))
        open(os.path.join(t, "bin", "gh"), "w").write("#!/bin/sh\nexit 1\n")    # "no such release yet"
        os.chmod(os.path.join(t, "bin", "gh"), 0o755)
        open(os.path.join(t, "swg-noded"), "w").write(noded)
        return subprocess.run(["bash", "-c", run], cwd=t, capture_output=True, text=True,
                              env=dict(os.environ, PATH=os.path.join(t, "bin") + ":/usr/bin:/bin")).returncode
    finally:
        shutil.rmtree(t, ignore_errors=True)
usq_tag = (re.search(r'^USQ_TAG = "([^"]+)"', noded, re.M) or [None, ""])[1]
check("[5] usque published under USQ_TAG passes", publish_check("usque", usq_tag) == 0)
check("[5] usque under any other tag is refused", publish_check("usque", usq_tag[:-1]) != 0
      and publish_check("usque", usq_tag + "-2") != 0)
check("[5] another fork's tag is not held to USQ_TAG", publish_check("qwdtt", "wdtt-qwdtt-9.9.9") == 0)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS))); sys.exit(1 if FAILS else 0)
