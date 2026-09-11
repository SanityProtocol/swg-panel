#!/usr/bin/env python3
"""Self-test — AN UNQUOTED HEREDOC EXECUTES ITS OWN COMMENTS.

`cat > file <<WRAP` (delimiter NOT quoted) is expanded by the shell before it is written: `$VAR` interpolates
and `` `cmd` `` RUNS. That is exactly what a heredoc writing a script wants for the values it bakes in — and
exactly what it does not want for the English prose around them.

MEASURED on hel-fresh 2026-09-10, during a bare→docker conversion. `write_docker_updater`'s comments carried
`` `compose pull && up` `` and `` `bootstrap.sh` ``, so the installer ran both:

    /tmp/swgconv/lib/common.sh: line 957: compose: command not found
    /tmp/swgconv/lib/common.sh: line 957: bootstrap.sh: command not found
    ✓ one-click update wired — the Update button runs a swg-only update on the host

…and then reported success. Their empty output was substituted into the file it wrote, so the installed
wrapper reads "on a docker box this is . A container can't" — a sentence with a hole in it. The functional
lines were correctly escaped and worked; what shipped wrong was the prose, and what RAN was the prose.

⚠️ On a box where a command named `compose` is on root's PATH, that comment is not a typo — it is
`compose pull && up`, executed as root, at install time, from a sentence explaining what the file does.

⚠️ ESCAPED BACKTICKS ARE FINE, and telling the two apart is the point. `\\`main\\`` inside an unquoted
heredoc is a literal backtick — verified on the same box, where the installed file reads "fell back to
`main`". A checker that flags both reports 5 findings where 3 are real, and 40% noise is how a report stops
being read (the i18n count went the same way — see tests/i18n_do_not_translate.json).

Run: python3 tests/heredoc_expansion_selftest.py      (0 = pass)
     --perturb   un-escapes one backtick and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SHELL = [f for f in sorted(os.listdir(ROOT)) if f.endswith(".sh")]
SHELL += [os.path.join("lib", f) for f in sorted(os.listdir(os.path.join(ROOT, "lib")))
          if f.endswith(".sh")] if os.path.isdir(os.path.join(ROOT, "lib")) else []

# `<<WORD` / `<<-WORD` with the delimiter UNQUOTED is expanding; `<<'WORD'` / `<<"WORD"` is literal.
OPEN = re.compile(r"<<-?\s*(?P<q>['\"])?(?P<w>[A-Za-z_][A-Za-z0-9_]*)(?(q)(?P=q))")

def unescaped_backticks(line):
    """Backticks that the shell will act on: a ` not preceded by a backslash."""
    return [m.start() for m in re.finditer(r"(?<!\\)`", line)]

def scan(path, src):
    """Unquoted-heredoc COMMENT lines carrying a live backtick or a live $( ).

    ⚠️ COMMENT lines only, and that narrowing is the difference between a gate and noise. A `$(hostname)`
    in the BODY of an unquoted heredoc is the whole reason the delimiter is unquoted — install-docker.sh
    bakes the host's name into the .env it writes exactly that way, and so do eight other places. Flagging
    those reported 10 findings for 3 real ones, which is a report nobody finishes reading. Prose is the
    thing that is never meant to execute, so prose is what this looks at."""
    out, delim = [], None
    for n, line in enumerate(src.splitlines(), 1):
        if delim is not None:
            if line.strip() == delim:
                delim = None
                continue
            if line.lstrip().startswith("#") and (len(unescaped_backticks(line)) >= 2
                                                  or re.search(r"(?<!\\)\$\(", line)):
                out.append((n, line.rstrip()))
            continue
        m = OPEN.search(line)
        if m and not m.group("q"):
            delim = m.group("w")
    return out

print("[1] no unquoted heredoc carries a LIVE backtick or $( ) — it would be executed at install time")
total = 0
for rel in SHELL:
    p = os.path.join(ROOT, rel)
    src = open(p, encoding="utf-8").read()
    if PERTURB and rel == "lib/common.sh":                # un-escape one, as it shipped
        src = src.replace("on a docker box this is \\`compose pull && up\\`.",
                          "on a docker box this is `compose pull && up`.")
    hits = scan(p, src)
    total += len(hits)
    if hits:
        for n, line in hits[:4]:
            print("       %s:%d  %s" % (rel, n, line.strip()[:110]))
check("no live expansions in any heredoc-written script", total == 0, total)

print("\n[2] the ESCAPED form is not flagged — 40% noise is how a report stops being read")
sample = r"# fell back to \`main\`. The"
check("an escaped pair is inert", len(unescaped_backticks(sample)) == 0, sample)
check("an unescaped pair is live", len(unescaped_backticks("# this is `compose pull` here")) == 2)
check("one lone escaped tick is inert", len(unescaped_backticks(r"a \` b")) == 0)

print("\n[3] a quoted delimiter is literal and needs no escaping at all")
lit = "cat > f <<'WRAP'\n# `anything goes` here\nWRAP\n"
check("<<'WRAP' bodies are skipped", scan("x", lit) == [], scan("x", lit))
exp = "cat > f <<WRAP\n# `anything goes` here\nWRAP\n"
check("<<WRAP bodies are scanned", len(scan("x", exp)) == 1, scan("x", exp))

print("\n[4] the wrapper this was found in still bakes its ref correctly")
common = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
check("the URL default is escaped so the WRAPPER expands it, not the installer",
      r'URL="\${SWG_BOOTSTRAP_URL:-' in common)
check("…and the ref itself IS expanded at write time (that one is deliberate)",
      "swg-panel/${_swg_ref}/bootstrap.sh" in common)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
