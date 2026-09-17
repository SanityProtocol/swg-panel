#!/usr/bin/env python3
"""Self-test: a container node's host helper runs from the node's OWN image, not `swg-node:latest`.

host_sh on a docker node is a privileged `docker run --rm --pid=host --entrypoint nsenter <HELPER_IMAGE> …` — every host read,
foreign-server scan and unit write. HELPER_IMAGE defaulted to `ghcr.io/sanityprotocol/swg-node:latest` and nothing passed it,
so a node pinned to a build ran helpers from an image the operator never chose. Measured on svo-im pinned to sha-56e2b4d (1.8.7
qualification PART 4, A7): 31 helper containers in 30 minutes from `swg-node:latest`, a two-week-old main build; a host that
has never pulled `:latest` fetches it on the first helper, or cannot reach the host at all where the registry is slow.

  [1] HELPER_IMAGE unset, SWG_TURN_IMAGE set → the helper image IS the node's own image
  [2] an explicit HELPER_IMAGE still wins; neither set (a bare process) → the published default
  [3] the node's own image really is what arrives as SWG_TURN_IMAGE: docker-compose.yml derives it from SWG_IMAGE_TAG, and the
      NixOS module sets it from `turnImage`, which defaults to `image`
  [4] the docker run in host_sh uses HELPER_IMAGE (the variable this gate is about is the one the helper runs)

Hermetic (loads swg-noded in child processes with chosen environments). Run: python3 tests/helper_image_selftest.py  (0 = pass)
     --perturb   loads a swg-noded whose default ignores SWG_TURN_IMAGE again and expects RED on [1] ("PERTURB OK", exit 0).
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED).read()
path = NODED
if PERTURB:
    anchor = 'HELPER_IMAGE = os.environ.get("HELPER_IMAGE") or os.environ.get("SWG_TURN_IMAGE") or "ghcr.io/sanityprotocol/swg-node:latest"'
    if src.count(anchor) != 1:
        print("PERTURB FAILED — the HELPER_IMAGE default is not in swg-noded exactly once")
        sys.exit(1)
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src.replace(anchor, 'HELPER_IMAGE = os.environ.get("HELPER_IMAGE") or "ghcr.io/sanityprotocol/swg-node:latest"'))

LOAD = r"""
import importlib.machinery, importlib.util, json, sys
ld = importlib.machinery.SourceFileLoader("noded_helper", sys.argv[1])
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_helper", ld))
try:
    ld.exec_module(m)
except SystemExit:
    pass
print(json.dumps({"helper": m.HELPER_IMAGE, "turn": m.SWG_TURN_IMAGE}))
"""
def helper(env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("HELPER_IMAGE", "SWG_TURN_IMAGE")}
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", LOAD, path], env=env, capture_output=True, text=True, timeout=60)
    line = [l for l in r.stdout.splitlines() if l.startswith("{")]
    return json.loads(line[-1]) if line else {"error": r.stderr[-300:]}

PIN = "ghcr.io/sanityprotocol/swg-node:sha-56e2b4d"
a = helper({"SWG_TURN_IMAGE": PIN})
check("[1] a node pinned to %s runs its helper from that image" % PIN.split(":")[1], a.get("helper") == PIN, a)
b = helper({"SWG_TURN_IMAGE": PIN, "HELPER_IMAGE": "registry.example/custom:1"})
check("[2] an explicit HELPER_IMAGE wins", b.get("helper") == "registry.example/custom:1", b)
c = helper({})
check("[2] nothing set → the published default", c.get("helper") == "ghcr.io/sanityprotocol/swg-node:latest", c)

compose = open(os.path.join(ROOT, "docker-compose.yml")).read()
check("[3] docker-compose.yml hands the node SWG_TURN_IMAGE derived from SWG_IMAGE_TAG",
      re.search(r'SWG_TURN_IMAGE:\s*"\$\{SWG_TURN_IMAGE:-ghcr\.io/sanityprotocol/swg-node:\$\{SWG_IMAGE_TAG:-latest\}\}"', compose) is not None)
nix = open(os.path.join(ROOT, "nix", "modules", "node.nix")).read()
check("[3] the NixOS module sets SWG_TURN_IMAGE from turnImage, which defaults to image",
      "SWG_TURN_IMAGE = cfg.turnImage;" in nix and re.search(r"turnImage = mkOption \{\s*type = types\.str; default = cfg\.image;", nix) is not None)
check("[4] host_sh's docker run uses HELPER_IMAGE", re.search(r'"--entrypoint", "nsenter",\s*HELPER_IMAGE,', src) is not None)

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — the default was undone and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
