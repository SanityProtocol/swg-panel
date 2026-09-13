"""Self-test — `swg-update` REWRITES ITSELF, and bash reads a script incrementally.

The one-click update re-bakes `/usr/local/bin/swg-update` as part of the update it is running. Bash does
not slurp a script; it reads, executes, then returns to the file for the next command **at the byte offset
it had reached**. So when the pipeline returned, bash read on into the NEW file, landed mid-line, and ran
the tail of a comment.

MEASURED on swgt, at the end of a completely successful panel update (§5 L7):

    telling the panel this finished (it may still be restarting) — up to 25s…
    panel reached — status recorded.
    /usr/local/bin/swg-update: line 15: pass: command not found

`pass` is the last word of `# extra flags (e.g. --node-only) pass through`, in a file that is **14 lines
long**. Under `set -euo pipefail` that is a NON-ZERO EXIT after the update has already reported success —
a real update ends by announcing a failure that did not happen, and anything keying on the wrapper's exit
status reads a good update as a bad one.

⚠️ IT FIRES ONLY WHEN SOMETHING IS ACTUALLY INSTALLED. Run the wrapper again with nothing to do and the
file is not rewritten, so it exits 0 and looks perfect — which is why every dry run and every second run
missed it, and why it took a real update on a real panel to see it once.

THREE WRITERS, ONE GRAMMAR: `update.sh`, `install-host.sh` and `lib/common.sh` each bake this file, so each
is rendered and tested here rather than trusting that they agree.

Run: python3 tests/update_wrapper_selfrewrite_selftest.py      (0 = pass)
     --perturb   strips the brace/exit guard, the way it shipped, and expects RED.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

WRITERS = {
    "update.sh":      r"cat > /usr/local/bin/swg-update\.new <<WRAP\n(.*?)\nWRAP\n",
    "install-host.sh": r"writef_atomic /usr/local/bin/swg-update 755 <<WRAP\n(.*?)\nWRAP\n",
    "lib/common.sh":  r"cat > /usr/local/bin/swg-update\.new <<WRAP\n(.*?)\nWRAP\n",
}
# ⚠️ AND THE WRITER MUST INSTALL BY RENAME. Section [4] is the half the first fix missed entirely: the
# braces + `exit` protect a wrapper that already has them, and can do nothing for the single press of Update
# that INSTALLS them — the script running at that moment is the OLD, unguarded one. Each writer is therefore
# checked twice: that it BAKES a self-rewrite-proof wrapper, and that it LANDS it at a new inode.
RENAMERS = {
    "update.sh":       "mv -f /usr/local/bin/swg-update.new /usr/local/bin/swg-update",
    "lib/common.sh":   "mv -f /usr/local/bin/swg-update.new /usr/local/bin/swg-update",
    "install-host.sh": 'mv -f "$full.new" "$full"',      # inside writef_atomic, so $PREFIX/dry-run still holds
}

def render(fname):
    """The wrapper exactly as the installer writes it — heredoc escapes resolved, ref substituted."""
    src = open(os.path.join(ROOT, fname), encoding="utf-8").read()
    m = re.search(WRITERS[fname], src, re.S)
    assert m, "no wrapper heredoc found in " + fname
    body = m.group(1).replace("\\$", "$").replace("\\`", "`").replace("${_swg_ref}", "dev")
    if PERTURB:
        # exactly how it shipped: no compound-command guard, no exit
        body = "\n".join(l for l in body.splitlines() if l.strip() not in ("{", "}", "exit"))
    return body + "\n"


def run_with_self_rewrite(body):
    """Run the wrapper while its own file is replaced underneath it — the real failure mode.

    The stub stands in for running the fetched bootstrap: it rewrites the script with a LONGER file whose tail
    is nothing but poison, so whatever offset bash resumes at lands on a command that must never run."""
    d = tempfile.mkdtemp(prefix="wrapsr-")
    path = os.path.join(d, "swg-update")
    # ⚠️ NO RUN OF THIS GATE MAY REACH THE NETWORK. A curl on PATH answers every fetch with an empty file. When
    # the plant below stopped matching (see the anchor note), the REAL wrapper ran here, fetched the real
    # bootstrap.sh from GitHub and executed it — stopped only because the test was not root.
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    with open(os.path.join(bindir, "curl"), "w") as fh:
        fh.write('#!/usr/bin/env bash\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && { : > "$2"; shift; }; shift; done\nexit 0\n')
    os.chmod(os.path.join(bindir, "curl"), 0o755)
    # neuter the network call and make it do what the real update does: re-bake this very file
    # The poison is an UNKNOWN COMMAND, not an echo: that is what the real one was (`pass through`, the tail
    # of a comment), and it is what makes `set -e` turn a successful update into a non-zero exit. With an
    # echo the run still exits 0 and the exit-code check below can never go red — a check that cannot fail.
    # ⚠️ `cat >`, NEVER `mv`. The installers TRUNCATE AND REWRITE IN PLACE, so bash's open fd sees the new
    # bytes. A `mv` swaps the inode and bash's fd keeps pointing at the old, unlinked file — it reads EOF,
    # stops, and the bug cannot reproduce. The first version of this gate did exactly that and stayed GREEN
    # under --perturb: a reproduction that does not reproduce is a gate that measures nothing.
    stub = ("REWRITE_TARGET=\"$0\"\n"
            "{ cat \"$REWRITE_TARGET.orig\"; for i in $(seq 1 400); do echo 'POISONED_$i through'; done; } > \"$REWRITE_TARGET\"\n"
            "echo update-ok\n")
    # ⚠️ ANCHOR ON THE LINE THAT RUNS THE UPDATE, AND ASSERT IT MATCHED. This used to replace `^curl -fsSL .*$`.
    # When the wrapper stopped piping curl into bash (it now downloads to "$B" and runs that), the pattern matched
    # nothing, `re.sub` said nothing, and [2]'s "nothing from the REWRITTEN file is executed" stayed green over a
    # plant that was never planted. A miss is fatal here, not a quiet skip.
    body, n = re.subn(r'^bash "\$B" update .*$', stub, body, count=1, flags=re.M)
    assert n == 1, "the line that runs the update was not found in the rendered wrapper — this run would test nothing"
    open(path, "w").write(body)
    open(path + ".orig", "w").write(body)      # what the rewrite starts from, so offsets line up
    os.chmod(path, 0o755)
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run(["bash", path], capture_output=True, text=True, timeout=60, env=env)
    return r


print("[1] the wrapper each writer bakes is valid bash")
bodies = {}
for f in WRITERS:
    bodies[f] = render(f)
    p = subprocess.run(["bash", "-n", "-"], input=bodies[f], capture_output=True, text=True)
    check("%s renders a parseable script" % f, p.returncode == 0, p.stderr.strip()[:120])

print("\n[2] …and survives being replaced underneath itself")
for f in WRITERS:
    r = run_with_self_rewrite(bodies[f])
    out = (r.stdout or "") + (r.stderr or "")
    check("%s: the update itself still runs" % f, "update-ok" in out, out.strip()[:160])
    check("%s: nothing from the REWRITTEN file is executed" % f, "POISONED" not in out, out.strip()[:200])
    check("%s: …and it exits 0, so a good update is not reported as a bad one" % f,
          r.returncode == 0, "rc=%s %s" % (r.returncode, out.strip()[:160]))

print("\n[3] the guard is stated in the source, not left to a reader to notice")
for f in WRITERS:
    b = bodies[f]
    if not PERTURB:
        check("%s: the body is one compound command" % f,
              re.search(r"^\{$", b, re.M) is not None and re.search(r"^\}$", b, re.M) is not None)
        check("%s: …and never returns to the file" % f, re.search(r"^exit$", b, re.M) is not None)

print("\n[4] ⚠️ THE TRANSITION — the press of Update that INSTALLS the guard, on a box that has none")
# The braces + `exit` are baked into the NEW wrapper. The script executing while they are installed is the
# OLD one, which has neither — so on every existing box the release that fixes this bug would reproduce it
# one last time, and `swg-update.service` (Type=oneshot → exec swg-update) would record a FAILED unit at the
# end of a completely successful update. The writer must therefore land the new file at a NEW INODE.
OLD_WRAPPER = ("#!/usr/bin/env bash\n"
               "# swg-update — fixed root entrypoint for one-click in-place update (swg programs only).\n"
               "set -euo pipefail\n"
               'URL="${SWG_BOOTSTRAP_URL:-https://example.invalid/bootstrap.sh}"\n'
               'export SWG_BOOTSTRAP_URL="$URL"\n'
               'curl -fsSL "$URL" | bash -s update -y --no-components "$@"   '
               "# extra flags (e.g. --node-only) pass through\n")


def run_transition(new_body, rename):
    """The OLD unguarded wrapper runs; the update it performs installs `new_body` the way the writer does."""
    d = tempfile.mkdtemp(prefix="wraptr-")
    path = os.path.join(d, "swg-update")
    # ⚠️ THE NEW BODY MUST BE LONGER THAN THE OLD, or bash's resume offset is past EOF either way and the
    # in-place arm cannot go red — a reproduction that does not reproduce. The real one grows 14 → 30+ lines.
    payload = new_body + "".join("# padding %d pass through\n" % i for i in range(120))
    assert len(payload) > len(OLD_WRAPPER) * 3, "the replacement is not longer than what it replaces"
    with open(os.path.join(d, "payload"), "w") as fh:
        fh.write(payload)
    # ⚠️ ONE LINE, like the real `curl … | bash -s update` it stands in for. Split across two lines the
    # in-place arm never reaches the second, because bash re-reads the file at its old offset the moment the
    # first returns — so "did the update run" would go red for a reason that has nothing to do with the
    # wrapper, and the exit-code check would stop being the thing that distinguishes the two arms.
    install = ('cp "$0.payload" "$0.new"; chmod 755 "$0.new"; mv -f "$0.new" "$0"' if rename
               else 'cat "$0.payload" > "$0"')
    stub = install + "; echo update-ok\n"
    open(path, "w").write(re.sub(r"^curl -fsSL .*$", stub, OLD_WRAPPER, count=1, flags=re.M))
    open(path + ".payload", "w").write(payload)
    os.chmod(path, 0o755)
    return subprocess.run(["bash", path], capture_output=True, text=True, timeout=60)


for f in WRITERS:
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if not PERTURB:
        check("%s: installs the wrapper by rename, not by truncating it in place" % f,
              RENAMERS[f] in src, "expected: " + RENAMERS[f])
    r = run_transition(bodies[f], rename=(RENAMERS[f] in src) and not PERTURB)
    out = (r.stdout or "") + (r.stderr or "")
    check("%s: the update itself still runs" % f, "update-ok" in out, out.strip()[:160])
    check("%s: ⚠️ the OLD wrapper exits 0 while being replaced by the new one" % f,
          r.returncode == 0, "rc=%s %s" % (r.returncode, out.strip()[:200]))

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
