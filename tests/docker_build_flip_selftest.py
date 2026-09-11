#!/usr/bin/env python3
"""Self-test: after `install-docker.sh --build`, the image the box BUILDS is the image it RUNS.

`--build` exists for one reason: running code GHCR does not publish. CI builds
`ghcr.io/sanityprotocol/swg-{panel,node}:latest` on push to `main` and nowhere else, so a branch has no
image and `--build` is the only way a docker box can run one.

⚠️ THE FLIP MUST LEAVE `image:` ALONE, AND THAT IS NOT AN OVERSIGHT — IT IS THE CONTRACT.
Compose names a built image with the service's `image:` value. Comment it out and the build is named
`<project>-swg-node` instead. That matters because ONE consumer outside compose reads that name:
`swg-noded` runs every turn-proxy container from `SWG_TURN_IMAGE`, which the node service resolves to
`ghcr.io/sanityprotocol/swg-node:${SWG_IMAGE_TAG:-latest}`. Break the naming and SWG_TURN_IMAGE points at an
image this box never built — docker pulls MAIN's published image to run the proxies, or fails with no
network. That is the "reverted to published code" failure --build exists to prevent, moved one layer down.

MEASURED on docker 29.7.2 / compose v5.2.0, `docker compose build` on the two shapes:
    image: + build:  ->  ghcr.io/sanityprotocol/swg-node:latest   (SWG_TURN_IMAGE resolves to this)
    build: only      ->  cmpxb-swg-node:latest                    (SWG_TURN_IMAGE resolves to nothing local)

The hazard that once motivated commenting `image:` out — a stray `docker compose pull` replacing a local
build with `latest` — is answered by the TAG instead: a --build install pins `SWG_IMAGE_TAG` to a name GHCR
does not publish, so the pull fails loudly rather than silently overwriting. (`update.sh` never pulls on a
build install at all: it greps for an active `build:` and takes the rebuild branch. This gate asserts that,
because it is the reason the pull hazard is a stray command and not the normal path.)

Run: python3 tests/docker_build_flip_selftest.py    (0 = pass)
     --perturb        comments the image lines out again and expects the naming checks to go red.
     --perturb-tag    drops the --build tag pin and expects the masquerade check to go red.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_TAG = "--perturb-tag" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

inst = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
# The real line, taken from the installer — not retyped, or this tests a copy of itself.
m = re.search(r"^\s*sed -i -E '(.*build: \\\..*)' \"\$PREFIX\$INSTALL_DIR/docker-compose\.yml\"", inst, re.M)
check("the flip was found in install-docker.sh", bool(m), "it moved or was renamed — this gate is blind")
if not m:
    print("\nFAILED: " + ", ".join(FAILS)); sys.exit(1)
script = m.group(1)
if PERTURB:
    # exactly the shipped regression: put the image-commenting half back on the front
    script = (r's@^( *)image: (ghcr.io/[^:]*/swg-(panel|node):[^[:space:]]+)@\1# image: \2@; ') + script

compose_p = os.path.join(ROOT, "docker-compose.yml")
before = open(compose_p, encoding="utf-8").read()
img_lines = lambda t: [l for l in t.splitlines() if re.match(r"^\s*image:\s*ghcr\.io/", l)]
builds = lambda t: len([l for l in t.splitlines() if re.match(r"^\s*build:", l)])

print("[1] the shipped compose is the un-flipped shape")
check("it has GHCR image lines", len(img_lines(before)) >= 3, len(img_lines(before)))
check("…and its build blocks start out commented", builds(before) == 0, builds(before))

with tempfile.TemporaryDirectory() as td:
    tmp = os.path.join(td, "docker-compose.yml")
    open(tmp, "w").write(before)
    subprocess.run(["sed", "-i", "-E", script, tmp], check=True)
    after = open(tmp, encoding="utf-8").read()

print("\n[2] ⚠️ after the flip, every service both BUILDS and is NAMED")
check("every build block is uncommented", builds(after) == len(img_lines(before)),
      "%d of %d" % (builds(after), len(img_lines(before))))
check("⚠️ …and every `image:` line SURVIVES, so compose names what it builds",
      len(img_lines(after)) == len(img_lines(before)),
      "%d of %d survive — a build compose names is `<project>-<service>`, which SWG_TURN_IMAGE cannot find"
      % (len(img_lines(after)), len(img_lines(before))))

print("\n[3] ⚠️ …and the name the node BUILDS is the name swg-noded RUNS ITS PROXIES FROM")
# The whole point. Read both out of the flipped file — not out of this docstring.
_node = after.split("\n  swg-node:\n", 1)[-1]
_img = re.search(r"^\s*image:\s*(\S+)", _node, re.M)
# ⚠️ THE VALUE IS NESTED — `"${SWG_TURN_IMAGE:-ghcr.io/…:${SWG_IMAGE_TAG:-latest}}"` — so a lazy
# `[^}]+` stops at the INNER brace and reports a mismatch against a string that in fact matches. Take the
# whole quoted value and peel the outer default off by name.
_traw = re.search(r'^\s*SWG_TURN_IMAGE:\s*"(.*)"\s*(?:#.*)?$', _node, re.M)
_turn = None
if _traw:
    _v = _traw.group(1)
    if _v.startswith("${SWG_TURN_IMAGE:-") and _v.endswith("}"):
        _turn = re.match(r"(.*)", _v[len("${SWG_TURN_IMAGE:-"):-1])
check("the node service still names an image", bool(_img), _node[:160])
check("…and still tells the node which image to run turn-proxies from", bool(_turn), _node[:400])
if _img and _turn:
    check("⚠️ …and they are the SAME name",
          _img.group(1).strip() == _turn.group(1).strip(),
          "builds %s, runs proxies from %s" % (_img.group(1), _turn.group(1)))
# swg-noded is the reader; assert it still reads that variable and has no fallback of its own.
noded = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
check("…and swg-noded takes that name from the environment with NO default",
      'SWG_TURN_IMAGE = os.environ.get("SWG_TURN_IMAGE") or ""' in noded)

print("\n[4] ⚠️ a locally built image must not wear the published name")
# Otherwise `docker images` cannot tell a local build from what CI publishes from main, and one
# `docker compose pull` silently replaces it.
_tag = re.search(r'if \$BUILD; then _IMAGE_TAG_LINE="SWG_IMAGE_TAG=\$\{SWG_IMAGE_TAG:-([^}]+)\}', inst)
if PERTURB_TAG:
    _tag = None
check("a --build install pins SWG_IMAGE_TAG", bool(_tag),
      "unpinned: the build is tagged :latest, indistinguishable from main's published image")
if _tag:
    check("…to something GHCR does not publish", _tag.group(1).strip() not in ("latest", "main"), _tag.group(1))
    check("…while an explicit SWG_IMAGE_TAG still wins", "${SWG_IMAGE_TAG:-" in _tag.group(0))
    check("…and the line reaches .env", "$_IMAGE_TAG_LINE" in inst.split("<<EOF", 1)[1].split("\nEOF", 1)[0]
          if "<<EOF" in inst else False)

print("\n[5] …and the supported updater rebuilds rather than pulls, which is why a pull is a stray command")
upd = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
check("update.sh branches on an active `build:` in the installed compose",
      "grep -qE '^[[:space:]]*build:' \"$DOCKER_DIR/docker-compose.yml\"" in upd)
_bblock = upd.split("grep -qE '^[[:space:]]*build:'", 1)[1].split("  else\n", 1)[0]
check("…and that branch rebuilds from source", "up -d --build" in _bblock)
check("…and never pulls", "pull" not in _bblock.replace("pull_policy", ""))

print("\n[6] …and a branch install still says which code it is about to run")
_w = re.search(r"if ! \$BUILD && ! _pinned_tag && \[ -n \"\$\{SWG_REF:-\}\" \] && \[ \"\$\{SWG_REF\}\" != main \]; then\n([\s\S]*?)\nfi", inst)
check("a branch install warns that the containers run the published image", bool(_w),
      "installing from a branch silently gives you main's code")
if _w:
    check("…and names --build, the one flag that does run the branch", "--build" in _w.group(1))
# ⚠️ AND IT ASKS THE FILE, NOT ONLY THE SHELL. `.env.example` documents the pin as an .env line, so a
# re-install over an .env pinning a real image was told, falsely, that it would run `latest`.
check("…and a pin in .env counts as a pin",
      "_pinned_tag(){" in inst and "sed -n 's/^SWG_IMAGE_TAG=//p' \"$INSTALL_DIR/.env\"" in inst)
check("…and .env.example still documents it as an .env line",
      "SWG_IMAGE_TAG=" in open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read())

print()
if PERTURB or PERTURB_TAG:
    # ⚠️ NAME THE WHOLE FAMILY, NOT ONE STRING. Commenting `image:` out makes the node service carry no
    # image at all, so the SAME-name comparison never runs — it is skipped, not failed. A reporter that
    # looked only for that one check read "the regression was restored and every check still passed" while
    # two checks were sitting red on the screen above it. [[harness-cannot-report-green]]
    want = ("`image:` line SURVIVES", "still names an image", "SAME name") if PERTURB else ("pins SWG_IMAGE_TAG",)
    hit = [f for f in FAILS if any(w in f for w in want)]
    print(("PERTURB OK — %d checks went red, and they include the one that matters: %s"
           % (len(FAILS), "; ".join(hit)[:200])) if hit
          else "PERTURB FAILED — the regression was restored and the naming checks still passed")
    sys.exit(0 if hit else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
