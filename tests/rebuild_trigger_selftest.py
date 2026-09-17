#!/usr/bin/env python3
"""Self-test: the NixOS self-update script rebuilds on a REQUEST, never on the empty trigger an install lays down.

nix/modules/rebuild.nix renders the script behind the panel's Update button on a NixOS panel or node. The container arm polls
it every 30 s (inotify does not cross the bind mount the daemon writes the trigger through). Its idempotence test was "the
stamp exists and the trigger is not newer" — but tmpfiles creates the trigger EMPTY at activation and a fresh install has no
stamp, so the first tick ran a full update nobody asked for: pull, flake update, rebuild, a restart of the node container and
an "updated" result sent to the panel. Measured on a fresh NixOS 26.05 podman node (1.8.7 qualification PART 4, A1): the
container went down 37 s after the install finished. Every real request writes a timestamp (swg-noded and the panel both do).

The block under test is cut out of rebuild.nix itself — from `set -u` to `touch ${stampFile}` — with the two Nix
interpolations substituted, and run by bash against real files, followed by a marker standing in for the rebuild.

  [1] a fresh install (empty trigger, no stamp): no rebuild, and no stamp written (the first real request must still fire)
  [2] a request (a timestamp in the trigger), no stamp: rebuilds and stamps
  [3] the same request again (stamp newer): no rebuild
  [4] a NEW request written after the stamp: rebuilds
  [5] an empty trigger touched after a stamp exists (a re-activation): no rebuild

Hermetic. Run: python3 tests/rebuild_trigger_selftest.py      (0 = pass)
     --perturb   removes the empty-trigger test and expects RED on [1] ("PERTURB OK", exit 0; exit 1 if nothing went red).
"""
import os, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NIX = os.environ.get("SWG_REBUILD_NIX") or os.path.join(ROOT, "nix", "modules", "rebuild.nix")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NIX).read()
m = re.search(r'script = pkgs\.writeShellScript "swg-rebuild-\$\{name\}" \'\'\n(.*?touch \$\{stampFile\}\n)', src, re.S)
check("[0] the script's idempotence block is found in rebuild.nix", bool(m))
if not m:
    sys.exit(1)
block = m.group(1)
if PERTURB:
    guard = "    if [ ! -s ${triggerFile} ]; then\n      exit 0\n    fi\n"
    if guard not in block:
        print("PERTURB FAILED — the empty-trigger test is not in the block, so there is nothing to remove")
        sys.exit(1)
    block = block.replace(guard, "")

D = tempfile.mkdtemp(prefix="rebuild-trigger-")
TRIG, STAMP = os.path.join(D, ".update-request"), os.path.join(D, ".update-stamp")
script = block.replace("${stampFile}", STAMP).replace("${triggerFile}", TRIG)
script = re.sub(r"\$\{lib\.makeBinPath \[ pkgs\.coreutils \]\}", "/usr/bin:/bin", script)
if "${" in script:
    print("  FAIL [0] an unsubstituted Nix interpolation is left in the block: %s" % re.findall(r"\$\{[^}]*\}", script))
    sys.exit(1)
script += "\necho WOULD-REBUILD\n"

def run():
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    return "WOULD-REBUILD" in r.stdout, r

def later(path, text=None):
    """Write `path` with an mtime strictly after everything else here (1 s resolution on some filesystems)."""
    time.sleep(1.1)
    with open(path, "w") as f:
        if text is not None:
            f.write(text)

open(TRIG, "w").close()                                  # what tmpfiles lays down: `f <trigger> 0600 root root -`
did, r = run()
check("[1] fresh install — empty trigger, no stamp: no rebuild", not did, (r.returncode, r.stdout, r.stderr))
check("[1] …and no stamp written, so the first real request still fires", not os.path.exists(STAMP))

later(TRIG, "%d\n" % int(time.time()))                   # what swg-noded / the panel write
did, r = run()
check("[2] a request, no stamp yet: rebuilds", did, (r.returncode, r.stdout, r.stderr))
check("[2] …and stamps", os.path.exists(STAMP))

did, r = run()
check("[3] the same request again: no rebuild", not did, (r.returncode, r.stdout))

later(TRIG, "%d\n" % int(time.time()))
did, r = run()
check("[4] a new request written after the stamp: rebuilds", did, (r.returncode, r.stdout))

later(TRIG, "")                                          # re-activation truncating it, or a hand `: >` — still not a request
did, r = run()
check("[5] an empty trigger touched after a stamp exists: no rebuild", not did, (r.returncode, r.stdout))

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — the empty-trigger test was removed and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
