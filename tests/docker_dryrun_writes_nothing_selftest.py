#!/usr/bin/env python3
"""Self-test: `install-docker.sh --dry-run` renders under ./dryrun and writes NOTHING into the install directory.

Measured on a pristine Ubuntu 24.04 box (1.8.7 qualification S7): a docker dry run left four real, empty files in
/opt/swg-panel-docker — data/etc/auth, data/lib/panel-settings.json, data/lib/subs/{vault,escrow}.json. The block that
pre-creates the files swg-sub /dev/null-masks was guarded by `! $DRYRUN`; the helper call on the line after it was not,
and it ran for the node profile too, which never starts swg-sub.

  [1] a `host` dry run (the profile that runs swg-sub) creates nothing at SWG_DOCKER_DIR, and says it rendered
  [2] a `node` dry run creates nothing at SWG_DOCKER_DIR either
  [3] the mask files are still pre-created for a real host/master install: the helper is called, inside the guard

Run: python3 tests/docker_dryrun_writes_nothing_selftest.py (0 = pass)
     --perturb   moves the helper call back out of the guard → RED on [1]
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


T = tempfile.mkdtemp(prefix="dockerdry-")
SRC = os.path.join(T, "src")
shutil.copytree(ROOT, SRC, ignore=shutil.ignore_patterns(".git", "dryrun", "node_modules", "*.png", "scratchpad", "docs", ".campaign", "__pycache__", "forks", "screenshots"))
inst = open(os.path.join(SRC, "install-docker.sh"), encoding="utf-8").read()
GUARDED = '''if [ "$PROFILE" != node ] && ! $DRYRUN; then
  mkdir -p "$INSTALL_DIR/data/lib/configs" "$INSTALL_DIR/data/etc/tls" 2>/dev/null || true
  ensure_docker_mask_files "$INSTALL_DIR"'''
if PERTURB:
    # the shipped shape: the helper called on its own line AFTER the guarded block
    blk = GUARDED + "   # auth, panel-settings, vault, escrow — the four files swg-sub /dev/null-masks\nfi\n"
    assert inst.count(blk) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    inst = inst.replace(blk, blk.replace('  ensure_docker_mask_files "$INSTALL_DIR"', "  :") + 'ensure_docker_mask_files "$INSTALL_DIR"\n', 1)
    open(os.path.join(SRC, "install-docker.sh"), "w", encoding="utf-8").write(inst)


def dry(args, label):
    target = os.path.join(T, "inst-" + label)
    env = dict(os.environ, SWG_DOCKER_DIR=target)
    r = subprocess.run(["bash", "install-docker.sh", *args, "--dry-run"], cwd=SRC, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300)
    made = []
    if os.path.exists(target):
        for dp, dn, fn in os.walk(target):
            made += [os.path.relpath(os.path.join(dp, f), target) for f in fn]
            if not fn and not dn:
                made.append(os.path.relpath(dp, target) + "/")
    return r, made, os.path.exists(target)


print("[1] a host dry run writes nothing where it would install")
r, made, exists = dry(["host", "-pass", "dry-run-pass", "-domain", "panel.example.net", "-tls", "selfsigned"], "host")
check("the dry run completed", r.returncode == 0 and "DRY RUN done" in (r.stdout + r.stderr), (r.returncode, (r.stdout + r.stderr)[-300:]))
check("⚠️ nothing at SWG_DOCKER_DIR", not exists, made or "the directory itself was created")

print("\n[2] a node dry run writes nothing where it would install")
r, made, exists = dry(["node", "-key", "dryrunnodetoken0123456789", "-host", "https://panel.example.net", "-endpoint", "203.0.113.7"], "node")
check("the dry run completed", r.returncode == 0 and "DRY RUN done" in (r.stdout + r.stderr), (r.returncode, (r.stdout + r.stderr)[-300:]))
check("nothing at SWG_DOCKER_DIR", not exists, made or "the directory itself was created")

print("\n[3] a real host/master install still pre-creates the files swg-sub masks")
src = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
check("the helper is called inside the `! $DRYRUN`, non-node block", GUARDED in src)
check("…and nowhere else in install-docker.sh", src.count("ensure_docker_mask_files") == 1, src.count("ensure_docker_mask_files"))

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
