#!/usr/bin/env python3
"""Self-test: the most destructive script here must not silently ignore the flag that means "don't".

`convert.sh` read `$1 $2 $3` and dropped everything after them. So

    convert.sh baremetal docker node --dry-run

printed the conversion banner and then CONVERTED — the one flag every sibling script honours
(install-host, install-node, install-docker, uninstall all take `--dry-run`), silently ignored by the one
script whose work cannot be undone: a convert tears the old method down before the new one is up.

⚠️ AND IT IS NOT A TYPO AN OPERATOR HAS TO INVENT. `bootstrap.sh` collects unrecognised flags into `PASS`
and hands them straight to convert.sh at BOTH of its call sites, and its `run_script` sets `_keep_tmp=1` the
moment it sees `--dry-run` — so the documented front door printed "dry-run preview kept at …" about a
conversion that had already happened.

The answer is a refusal, not an implementation: rendering a convert under a $PREFIX would be a second,
unexercised path through the most destructive script in the tree. `--check` is the rehearsal it has.

Run: python3 tests/convert_arg_guard_selftest.py     (0 = pass)
     --perturb  drops the guard, the way it shipped, and expects the refusals to stop.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
# ⚠️ A SECOND, NARROWER PERTURBATION. `--perturb` deletes the whole guard, which makes `-y` accepted again —
# so it can never show that [3b] is doing any work. This one restores exactly the shipped regression: the
# guard present, the `-y` arm gone.
PERTURB_YES = "--perturb-yes" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

SRC = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
GUARD_RE = re.compile(r'for _x in "\$\{@:4\}"; do case "\$_x" in[\s\S]*?esac; done\n')
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves the tree intact and reads as a pass.
assert GUARD_RE.search(SRC), "guard not found in convert.sh — this run would FALSE-PASS"
if PERTURB:
    SRC = GUARD_RE.sub("", SRC, count=1)
if PERTURB_YES:
    _arm = "  -y|--yes) ASSUME_YES=yes ;;\n"
    assert _arm in SRC, "the -y arm is not where this expects it — this run would FALSE-PASS"
    SRC = SRC.replace(_arm, "", 1)

script = os.path.join(ROOT, "convert.sh")
if PERTURB or PERTURB_YES:
    _fd, script = tempfile.mkstemp(suffix=".sh", prefix="convarg-", dir=ROOT)
    os.write(_fd, SRC.encode()); os.close(_fd); os.chmod(script, 0o755)

def run(*args):
    r = subprocess.run(["bash", script, *args], capture_output=True, text=True, cwd=ROOT)
    return r.returncode, (r.stdout + r.stderr)

print("[1] the flag that means 'don't' is refused, not dropped")
rc, out = run("baremetal", "docker", "node", "--dry-run")
check("`--dry-run` exits non-zero instead of converting", rc != 0, rc)
check("…and says convert has no dry run", "no dry run" in out, out.strip()[-200:])
check("…and names the rehearsal it DOES have", "--check" in out, out.strip()[-200:])
# ⚠️ THE BANNER IS THE TELL. Refusing after "SWG BARE-METAL → DOCKER CONVERSION" would still read, to
# somebody watching a terminal, as a conversion that started.
check("…before the conversion banner, not after it", "CONVERSION" not in out, out.strip()[:200])

print("\n[2] and so is anything else it does not understand")
rc, out = run("baremetal", "docker", "node", "--wat")
check("an unknown option is refused", rc != 0 and "isn't an option" in out, (rc, out.strip()[-160:]))
check("…with the usage line, so there is a way forward", "usage: convert.sh" in out, out.strip()[-160:])

print("\n[3] ⚠️ …and the paths that were always valid still are")
# ⚠️ THESE RUN AS AN ORDINARY USER, so they get as far as the root check and stop there — which is the
# POINT: they got PAST argument parsing. A guard that refused them would be worse than the bug it fixes.
# (Arguments are validated BEFORE root deliberately: answering "run as root" to a command that is also
# misspelled costs two round trips for one mistake, and hides the more important sentence behind a sudo.)
for args, what in ((("--check", "baremetal", "docker", "node"), "--check <from> <to> <role>"),
                   (("baremetal", "docker", "node"), "<from> <to> <role>")):
    rc, out = run(*args)
    check("`%s` gets past argument parsing" % what,
          "isn't an option" not in out and "no dry run" not in out, out.strip()[-160:])

print("\n[3b] ⚠️ …INCLUDING the flag bootstrap.sh itself forwards")
# The first version of this guard refused every word it did not recognise, and `-y` is a word it did not
# recognise. But `-y`/`--yes` is the documented unattended form of update.sh and uninstall.sh, and
# bootstrap.sh puts every flag it does not parse into `PASS` and hands it to BOTH convert call sites — so
# `bootstrap.sh node -y` on a box with the other method installed died at argument parsing, AFTER the
# operator had answered the method menu and the "proceed with the conversion" confirm. Silently dropping it
# (the pre-guard behaviour) was harmless; refusing it was not.
for _f in ("-y", "--yes"):
    rc, out = run("baremetal", "docker", "node", _f)
    check("`%s` gets past argument parsing" % _f, "isn't an option" not in out, out.strip()[-160:])
# Honoured, not merely tolerated — this script asks its own yes/no questions (the turn-proxy transfer), and
# a flag that is accepted and then ignored is the same class of bug as one that is dropped.
check("…and `cyn` answers yes for it instead of reading the tty",
      '[ "${ASSUME_YES:-no}" = yes ]' in SRC.split("cyn(){")[1].split("\n")[0])
check("…and the flag is what sets that, not the environment",
      "-y|--yes) ASSUME_YES=yes" in SRC and "\nASSUME_YES=no\n" in SRC)
# The forwarding is the reason any of this matters; assert it still happens.
_boot = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
check("…and bootstrap still hands PASS to convert.sh at BOTH call sites",
      _boot.count('run_script convert.sh') == 2
      and all('${PASS[@]+"${PASS[@]}"}' in _l for _l in _boot.splitlines() if "run_script convert.sh" in _l))

print("\n[4] ⚠️ …and a plain forgot-my-sudo is answered with SUDO, not with NixOS advice")
# `declarative_host`'s write probe fails for every non-root process on every box in the world, and this
# script had no root check at all — so an Ubuntu laptop was reported as "managed declaratively" and the
# operator was told to describe swg-panel in their NixOS configuration. install-node.sh and update.sh
# reached the same refusal first for the same reason; install-docker.sh and uninstall.sh said "run as
# root", which is the true answer. Fixed in the probe, so all five agree.
rc, out = run("baremetal", "docker", "node")
check("convert.sh asks for root", "run as root" in out, out.strip()[-160:])
check("…and does NOT call this box declarative", "declaratively" not in out, out.strip()[-200:])
_cs = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
check("the probe is only evidence when we could have written",
      '[ "$(id -u)" = 0 ] || return 1' in _cs.split("declarative_host(){")[1].split("\n}")[0])
check("…while a real NixOS marker still decides outright, at any privilege",
      "/etc/NIXOS" in _cs.split("declarative_host(){")[1].split('[ "$(id -u)" = 0 ]')[0])

print("\n[5] the front door does not announce a preview that was never rendered")
boot = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
check("bootstrap keeps the tmp tree only when a dryrun directory actually exists",
      '[ -d "${TMP:-}/swg-panel/dryrun" ]' in boot)
check("…and it still passes unrecognised flags through, which is how this reached convert.sh",
      'PASS+=("$1")' in boot)

if PERTURB or PERTURB_YES:
    os.unlink(script)
print()
if PERTURB_YES:
    _y = [f for f in FAILS if "-y" in f or "--yes" in f or "cyn" in f or "sets that" in f]
    print(("PERTURB-YES OK — %d checks went red, and they are the RIGHT ones: %s"
           % (len(FAILS), ", ".join(_y)[:200])) if _y
          else "PERTURB-YES FAILED — the -y arm was removed and [3b] still passed")
    sys.exit(0 if _y else 1)
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the guard is gone and --dry-run converts again" % len(FAILS))
          if ok else "PERTURB FAILED — the guard was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
