#!/usr/bin/env python3
"""Self-test: the uninstaller must not call an ordinary host declarative just because it is not root.

`uninstall.sh` refuses to run where a `systemctl disable --now` could not take, and it decided that by
WRITING A FILE into $SD. That probe answers "could *this process* write here" — and as the non-root
`--dry-run` the script's own root check deliberately allows (`id -u = 0 || $DRYRUN || die`), the answer is
no on every ordinary systemd host, because /etc/systemd/system is root-owned everywhere. So an ordinary
Ubuntu user running the documented `--dry-run` was told:

    $SD is read-only — this host's services are managed declaratively (NixOS?)

Nothing was read-only and nothing was declarative, and the `--dry-run` that the root check offers was
unreachable for the only people who need it. Found by the 1.8.7 release qualification (I1, finding 5) as a
PRE-EXISTING defect — the range's own uninstall.sh change was the AppArmor grant revert, not this.

The fix keeps the write probe where it means something — as root — and otherwise asks the HOST, with two
signals that need no privilege: it says it is NixOS, or the mount holding $SD reports `ro`. Measured:
`rw,relatime,…` on Ubuntu, `ro,nosuid,nodev,relatime` on NixOS.

⚠️ THE REFUSAL MUST SURVIVE FOR A NON-ROOT RUN ON A DECLARATIVE HOST. Weakening the probe is only safe
because the host-owned signals replace it; if they stopped answering, a non-root run on NixOS would sail
past a refusal that exists to stop a half-completed, destructive uninstall.

Run: python3 tests/uninstall_unitdir_selftest.py          (0 = pass)
     python3 tests/uninstall_unitdir_selftest.py --perturb-probeonly   (and the other flags — all MUST be 1)
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []

# ── perturbations ──────────────────────────────────────────────────────────────────────────────
# ⚠️ An anchor that no longer matches is a FALSE PASS, not a skipped edit, so it is a hard error.
_EDITS = {
    # the defect itself, put back: the write probe is the whole condition again
    "--perturb-probeonly": ('&& { [ "$(id -u)" = 0 ] || unit_dir_immutable; }; then', '; then'),
    # the host stops being asked whether the mount is read-only
    "--perturb-mount":     ('case ",$o," in *,ro,*) return 0 ;; esac', 'case ",$o," in *,noSuchOption,*) return 0 ;; esac'),
    # …and whether it is NixOS
    "--perturb-nixos":     ('[ -e /etc/NIXOS ] && return 0', '[ -e /etc/NO-SUCH-MARKER ] && return 0'),
}
PERTURB = [a for a in sys.argv[1:] if a.startswith("--perturb")]
for f in PERTURB:
    if f not in _EDITS:
        sys.exit("unknown perturbation %s (have: %s)" % (f, " ".join(sorted(_EDITS))))

SRC = open(os.path.join(ROOT, "uninstall.sh")).read()
for f in PERTURB:
    old, new = _EDITS[f]
    if old not in SRC:
        sys.exit("PERTURBATION %s FOUND NO ANCHOR — it would have passed for the wrong reason" % f)
    SRC = SRC.replace(old, new, 1)


def check(label, got, want):
    if got != want:
        FAIL.append(f"{label}: got {got!r}, want {want!r}")


def fn(name):
    """The body of one shell function, lifted out of uninstall.sh."""
    m = re.search(r"^%s\(\)\s*\{.*?^\}" % re.escape(name), SRC, re.S | re.M)
    if not m:
        sys.exit("could not find %s() in uninstall.sh" % name)
    return m.group(0)


GATE = next((ln for ln in SRC.splitlines() if "unit_dir_writable" in ln and ln.strip().startswith("if ")), "")


def _shim_bin(with_findmnt):
    """A PATH holding the tools the function needs — and, unless asked for, NOT findmnt.

    ⚠️ PREPENDING A NONEXISTENT DIRECTORY DOES NOT HIDE A TOOL. The first version of this harness did
    exactly that, `command -v findmnt` still found the real one, it answered for the real path, and the
    read-only fixtures silently tested nothing while reporting a clean skip."""
    d = tempfile.mkdtemp()
    for tool in ("bash", "awk", "gawk", "mawk", "readlink", "grep", "rm", "id", "cat", "sed"):
        src = shutil.which(tool)
        if src:
            os.symlink(src, os.path.join(d, tool))
    if with_findmnt:
        src = shutil.which("findmnt")
        if src:
            os.symlink(src, os.path.join(d, "findmnt"))
    return d


def decide(sd, mounts, with_findmnt=False):
    """Run the REAL functions and the REAL gate line in bash. Returns (writable, immutable, refuse)."""
    with tempfile.NamedTemporaryFile("w", suffix=".mounts", delete=False) as mf:
        mf.write(mounts)
        mpath = mf.name
    binp = _shim_bin(with_findmnt)
    script = f"""
set -u
export PATH={binp!r}
SD={sd!r}
export PROC_MOUNTS={mpath!r}
{fn('unit_dir_writable')}
{fn('unit_dir_immutable')}
w=no; unit_dir_writable && w=yes
i=no; unit_dir_immutable && i=yes
g=skip
{GATE.strip()}
  g=REFUSE
fi
echo "$w $i $g"
"""
    out = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
    os.unlink(mpath)
    shutil.rmtree(binp, ignore_errors=True)
    if not out.stdout.split():
        sys.exit("harness failed: " + (out.stderr[-400:] or "no output"))
    return tuple(out.stdout.split())


RW = "/dev/root / ext4 rw,relatime 0 0\n"
RO = "/dev/root / ext4 ro,relatime 0 0\n"
NESTED = "/dev/root / ext4 rw,relatime 0 0\n/dev/store /etc squashfs ro,nosuid,nodev,relatime 0 0\n"

writable = tempfile.mkdtemp()
unwritable = "/etc/systemd/system" if os.path.isdir("/etc/systemd/system") else "/proc/sys"

# ── the four host shapes, decided by the real gate line ────────────────────────────────────────
check("writable dir, rw mount",        decide(writable, RW),   ("yes", "no", "skip"))
# ⚠️ THE REPORTED CASE. Root-owned unit dir, ordinary read-write host, and we are not root.
check("root-owned dir, rw mount",      decide(unwritable, RW), ("no", "no", "skip"))
# and the two that must still refuse, with no privilege anywhere in sight
check("root-owned dir, RO mount",      decide(unwritable, RO), ("no", "yes", "REFUSE"))
check("RO mount found by longest match", decide(unwritable, NESTED), ("no", "yes", "REFUSE"))
# …and the same two, with findmnt PRESENT — it answers for the resolved path, so on this (read-write)
# host it must say "not immutable" and the fixture must not be able to override a real answer.
check("findmnt present beats the fixture", decide(unwritable, RO, with_findmnt=True), ("no", "no", "skip"))

# ── the shape of the decision, not just today's answers ────────────────────────────────────────
check("the gate no longer rests on the probe alone",
      bool(re.search(r"unit_dir_writable.*id -u.*unit_dir_immutable", GATE)), True)
imm = fn("unit_dir_immutable")
check("immutable asks /etc/NIXOS",     "/etc/NIXOS" in imm, True)
check("immutable asks os-release",     "os-release" in imm, True)
check("immutable asks the mount",      ("findmnt" in imm and "PROC_MOUNTS" in imm), True)
# the root check above it is what makes a non-root dry run legal in the first place — if that goes, this
# whole cell is about a mode nobody can reach
check("a non-root --dry-run is still offered",
      bool(re.search(r'\[ "\$\(id -u\)" = 0 \] \|\| \$DRYRUN \|\| die', SRC)), True)
# and the generic message must not assert a cause it did not observe
check("generic refusal does not claim read-only outright",
      "is read-only — this host's services are managed declaratively" in SRC, False)

if FAIL:
    print("RED — %d check(s) failed:" % len(FAIL))
    for f in FAIL:
        print("  ·", f)
    sys.exit(1)
print("GREEN — the probe is trusted only as root; a declarative host still refuses without it")
