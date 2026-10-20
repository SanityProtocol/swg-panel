#!/usr/bin/env python3
"""Self-test — NO CONSUMER IN A PIPE STOPS READING EARLY IN THE INSTALLERS, WHICH ALL RUN UNDER PIPEFAIL.

install-host, install-node, install-docker, update, convert and bootstrap run `set -euo pipefail`, uninstall and
nix/adopt.sh `set -uo pipefail`, lib/common.sh is sourced by them and the swg-update wrapper text sets it too. A consumer
that stops reading after its first match or line — grep -q / -m / -l, head, sed q, awk … exit — closes the pipe; a
producer that writes again after that dies of SIGPIPE (141), and pipefail fails the whole pipeline although the match
was found. So `docker ps --format '{{.Names}}' | grep -qx swg-panel` could read "no swg-panel" on a master whenever
the listing arrived in more than one write (1.8.8 qualification, round 11): lc_teardown_docker then ran `compose down`
on a stack it took for node-only, lc_clear_convert_leftover (and bootstrap.sh's twin of it) rm -rf'd a live Docker
install directory it took for a convert's leftover, and node_reconfig_block told a master to `--profile node up -d`
(installer_lines [h] flaked on it: bash's printf writes a line at a time). Inside `$(…)` under `set -e` the same race
aborts the script. Every such consumer now reads all of its input: `grep -c … >/dev/null` for grep -q, `sed -n 1p` for
head -1, `sed -n 1,4p` for head -4, `cut -c1-16` for head -c16 on its one line, awk with a done flag for awk … exit.
⚠️ `-c`, NOT A BARE `grep … >/dev/null`. That was the first fix, and it rested on GNU grep: with its output on /dev/null
it stops matching at the first hit but drains the pipe to EOF. POSIX promises no such thing — a grep that exits at its
first match whenever its output is discarded is a correct grep (round 10, N14). A count cannot be known before the
last line, so `-c` reads everything whatever grep it is; its exit status is grep's (0 = a line matched).

  [0] the linter itself: it flags each early-exit form planted in a pipe (one per line, a pipe at the end of a line,
      a `\\` continuation, a wrapper, an env prefix), and none of the full-reading forms, a `||`, a comment, a
      here-string or a file argument
  [1] lint: no early-exit consumer after a `|` in the scripts above — heredoc'd scripts included, as every line of the
      file is read — unless its line carries `# pipefail-ok: <why>` (kept rare; each one is listed)
  [2] behaviour: lc_teardown_docker, lc_clear_convert_leftover, bootstrap.sh's twin of it and node_reconfig_block,
      lifted as shipped, run under `set -euo pipefail` against a docker stub whose `ps` writes its listing a line at
      a time — the match first, the rest after a pause (the window the race needs, made certain) — many times each:
      the right decision every time; then pause-free, many more times, the same
  [3] the environment can show the race at all: `grep -qx` behind a producer that writes again reads 141 under
      pipefail (else [2] would measure nothing), and `grep -cx … >/dev/null` reads the match (0) — and it does so behind a
      grep that does NOT drain (a stand-in on PATH that exits at its first match whenever its output is /dev/null, as
      POSIX allows): there the bare `grep -x … >/dev/null` reads 141 and `-c` still 0; the functions of [2] are run
      under that grep too, and decide right every time

Run: python3 tests/pipefail_early_exit_selftest.py            (0 = pass)
     --perturb            re-plants the old `| grep -q…` at every site [2] drives → [1] and [2] RED
     --perturb-teardown   re-plants only `| grep -qx swg-panel` in lc_teardown_docker → [1] and [2] RED
     --perturb-nodrain    re-plants the first fix's bare `| grep -x… >/dev/null` (no -c) at every site [2] drives → [1] RED,
                          and [3]'s run of the functions under a grep that does not drain RED
     SWG_PF_ROOT=<tree>   read the scripts from another tree (e.g. a `git archive` of an older commit)
"""
import concurrent.futures as cf, os, re, shlex, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SWG_PF_ROOT") or os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = ("install-host.sh", "install-node.sh", "install-docker.sh", "update.sh", "convert.sh", "bootstrap.sh",
           "uninstall.sh", "lib/common.sh", "nix/adopt.sh")
MARK = "# pipefail-ok:"
PERTURB = "--perturb" in sys.argv
PERTURB_TEARDOWN = "--perturb-teardown" in sys.argv
PERTURB_NODRAIN = "--perturb-nodrain" in sys.argv
RUNS_NODRAIN = int(os.environ.get("SWG_PF_RUNS_NODRAIN", "15"))   # per case, under the grep that does not drain
RUNS = int(os.environ.get("SWG_PF_RUNS", "25"))           # per case, with the pause
RUNS_FAST = int(os.environ.get("SWG_PF_RUNS_FAST", "200"))  # per case, pause-free

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

SRC = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in SCRIPTS}

def plant(f, a, b):
    assert SRC[f].count(a) == 1, "perturbation anchor missing — this run would FALSE-PASS: " + a[:100]
    SRC[f] = SRC[f].replace(a, b)

TEARDOWN_NEW = "  if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cx swg-panel >/dev/null; then   # node-only"
TEARDOWN_OLD = "  if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-panel; then   # node-only"
TEARDOWN_F89 = "  if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -x swg-panel >/dev/null; then   # node-only"
LEFT_NEW = "2>/dev/null | grep -cxE 'swg-(node|panel)' >/dev/null; then\n"
FOOT_NEW = "2>/dev/null | grep -cx swg-panel >/dev/null && prof=master || prof=node; }"
TWIN_NEW = "       && ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -cxE 'swg-(node|panel)' >/dev/null; then\n    if [ ! -f"
def plant_all(f, a, b, n):
    assert SRC[f].count(a) == n, "perturbation anchor missing — this run would FALSE-PASS: %s (%d, not %d)" % (a[:100], SRC[f].count(a), n)
    SRC[f] = SRC[f].replace(a, b)
if PERTURB or PERTURB_TEARDOWN:
    plant("lib/common.sh", TEARDOWN_NEW, TEARDOWN_OLD)
if PERTURB:
    plant_all("lib/common.sh", LEFT_NEW, "2>/dev/null | grep -qxE 'swg-(node|panel)'; then\n", 2)
    plant("lib/common.sh", FOOT_NEW, "2>/dev/null | grep -qx swg-panel && prof=master || prof=node; }")
    plant("bootstrap.sh", TWIN_NEW, TWIN_NEW.replace("grep -cxE 'swg-(node|panel)' >/dev/null", "grep -qxE 'swg-(node|panel)'"))
if PERTURB_NODRAIN:     # the first fix's form: output discarded, no count — right only on a grep that drains
    plant("lib/common.sh", TEARDOWN_NEW, TEARDOWN_F89)
    plant_all("lib/common.sh", LEFT_NEW, LEFT_NEW.replace("grep -cxE", "grep -xE"), 2)
    plant("lib/common.sh", FOOT_NEW, FOOT_NEW.replace("grep -cx", "grep -x"))
    plant("bootstrap.sh", TWIN_NEW, TWIN_NEW.replace("grep -cxE", "grep -xE"))

# ── the linter ────────────────────────────────────────────────────────────────────────────────────────────────────────
PIPE = re.compile(r"(?<![|>])\|(?![|])&?")          # a pipe (| or |&) — not ||, not the >| redirection
PREFIX = re.compile(r"(?:(?:command|builtin|exec|nice|env)\s+|(?:timeout|stdbuf)\s+\S+\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*")

def code_of(line):
    """the line without its trailing comment: a # that starts a word outside quotes (an open quote → no comment)"""
    j, n, q = 0, len(line), None
    while j < n:
        c = line[j]
        if q == "'":
            if c == "'": q = None
        elif q == '"':
            if c == "\\": j += 1
            elif c == '"': q = None
        elif c == "\\": j += 1
        elif c in "'\"": q = c
        elif c == "#" and (j == 0 or line[j - 1] in " \t;|&("):
            return line[:j]
        j += 1
    return line

def words(cmd):
    try:
        return shlex.split(cmd, comments=False, posix=True)
    except ValueError:
        return cmd.split()

def this_command(cmd):
    """`cmd` up to the end of its simple command: an unquoted ; | & ) or a closing " (a $(…) inside "…" ends there)"""
    j, n, q, depth = 0, len(cmd), None, 0
    while j < n:
        c = cmd[j]
        if q == "'":
            if c == "'": q = None
        elif q == '"':
            if c == "\\": j += 1
            elif c == '"': q = None
        elif c == "\\": j += 1
        elif c == "'": q = c
        elif c == '"':
            if depth == 0 and j and cmd[j - 1] not in " \t=": return cmd[:j]   # the "…" this $(…) sits in closes
            q = c
        elif c == "(": depth += 1
        elif c == ")":
            if depth == 0: return cmd[:j]
            depth -= 1
        elif c == "&" and ((j and cmd[j - 1] == ">") or cmd[j + 1:j + 2] == ">"): pass   # >&, &> — a redirection
        elif c in ";|&" and depth == 0: return cmd[:j]
        j += 1
    return cmd

def early_exit(cmd):
    """the kind of early-exit consumer `cmd` (the text after a pipe) starts with, or None"""
    cmd = cmd.lstrip()
    if cmd.startswith("&"):
        cmd = cmd[1:].lstrip()
    cmd = this_command(cmd[PREFIX.match(cmd).end():])
    m = re.match(r"(\\?(?:[ef]?grep|head|sed|awk|gawk|mawk|read|cmp))\b", cmd)
    if not m:
        return None
    tool = m.group(1).lstrip("\\")
    if tool in ("head", "read", "cmp"):
        return tool
    if tool.endswith("grep"):
        w = words(cmd)[1:]
        skip, counts = False, False
        for x in w:
            if skip: skip = False; continue
            if x in ("-e", "-f", "--regexp", "--file"): skip = True; continue
            if x == "--": break
            if x.startswith("--"):
                if x.split("=")[0] in ("--quiet", "--silent", "--max-count", "--files-with-matches", "--files-without-match"):
                    return "grep " + x
                counts = counts or x == "--count"
            elif x.startswith("-") and len(x) > 1 and re.match(r"-[A-Za-z]*[qmlL]", x):
                return "grep " + x
            elif x.startswith("-") and len(x) > 1 and re.match(r"-[A-Za-z]*c", x):
                counts = True
        # its output DISCARDED and nothing counted: a grep may stop at its first match (N14) — only -c must read it all
        if not counts and re.search(r"(?:^|[\s;])(?:[1&]?>|>>)\s*/dev/null(?![^\s;|&])", cmd):
            return "grep >/dev/null without -c"
        return None
    if tool == "sed":
        prog = cmd[len(m.group(0)):]
        return "sed q" if re.search(r"(?:^|[\s'\";{}/0-9$])[qQ]\d*\s*(?:[;}'\"]|$)", prog) else None
    return "awk exit" if re.search(r"\bexit\b", cmd) else None

def lint(text):
    """[(line number, kind, line)] for each early-exit consumer after a pipe; a line marked pipefail-ok is skipped"""
    lines = text.split("\n")
    out = []
    for i, raw in enumerate(lines):
        if raw.lstrip().startswith("#"):
            continue
        code = code_of(raw)
        for m in PIPE.finditer(code):
            rest, at = code[m.end():], i
            if not rest.strip() or rest.strip() == "\\":        # the consumer is on the next code line
                k = i + 1
                while k < len(lines) and (not lines[k].strip() or lines[k].lstrip().startswith("#")):
                    k += 1
                if k >= len(lines):
                    continue
                rest, at = code_of(lines[k]), k
            kind = early_exit(rest)
            if kind and MARK not in lines[at]:
                out.append((at + 1, kind, lines[at].strip()))
    return out

print("[0] the linter flags every early-exit form in a pipe, and none of the full-reading ones")
BAD = ["x | grep -q y", "x | grep -qx y", "x|grep -Eq 'a|b'", "x | grep -m1 y", "x | grep --max-count=1 y", "x | grep -l y",
       "x | grep --quiet y", "x | head -1", "x | head -n1", "x | head", "x | head -c16", "x | sed 1q", "x | sed -n '/y/{p;q}'",
       "x | awk '{print $2; exit}'", "x | read -r v", "x | command grep -qx y", "x | LC_ALL=C grep -qi y",
       "x |& grep -q y", "v=\"$(x | head -1)\"", "if ! x | grep -qx y; then :; fi", "x |\n  grep -q y", "x \\\n  | head -1",
       "x | timeout 5 grep -q y", "{ x | grep -qx y && a=1; }",
       "x | grep -x y >/dev/null", "x | grep y > /dev/null 2>&1", "x | grep -E 'a|b' &>/dev/null", "x | grep -v y 1>/dev/null",
       "if x | grep -xE 'a' >/dev/null; then :; fi"]
GOOD = ["x | grep -cx y >/dev/null", "x | grep -c y", "x | grep --count y >/dev/null", "x | grep -cxE 'a|b' >/dev/null 2>&1",
        "v=\"$(x | grep y)\"", "x | grep y > /tmp/out", "x | grep y 2>/dev/null | sort",
        "x | sed -n 1p", "x | sed -n 1,4p", "x | awk 'NR==1{print $2}'",
        "x | cut -c1-16", "x || grep -q y f", "grep -q y file", "grep -qx y <<< \"$x\"", "x  # … | head -1",
        "x | tr -d q", "x | sed 's/q//'", "x | grep -v q", "x | while read -r l; do :; done", "x | sort -u | tail -1",
        "x | sed -n 's/^Q=//p'", "echo a >| f"]
_miss = [b for b in BAD if not lint(b)]
_false = [g for g in GOOD if lint(g)]
check("[0] each of %d early-exit forms is flagged" % len(BAD), not _miss, _miss)
check("[0] none of %d full-reading / non-pipe forms is" % len(GOOD), not _false, [(g, lint(g)) for g in _false])
check("[0] a line marked `%s …` is not flagged" % MARK, not lint("x | head -1   %s the producer is one printf of one line" % MARK))

print("\n[1] lint: no early-exit consumer after a pipe in the installers")
marked = []
for f in SCRIPTS:
    hits = lint(SRC[f])
    check("%s: none" % f, not hits, ["%d: %s: %s" % (n, k, l[:160]) for n, k, l in hits])
    marked += ["%s:%d" % (f, i + 1) for i, l in enumerate(SRC[f].split("\n")) if MARK in l and not l.lstrip().startswith("#")]
print("  (%d line(s) marked %s%s)" % (len(marked), MARK, (": " + ", ".join(marked)) if marked else ""))

# ── the behaviour ─────────────────────────────────────────────────────────────────────────────────────────────────────
def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

C = SRC["lib/common.sh"]
B = SRC["bootstrap.sh"]
_a = B.index('if [ "${CHOICE:-}" != convert ]; then\n  if [ "$METHOD" = baremetal ]')
_b = B.index('\nexport STEP_BASE="$STEP"', _a)
TWIN = B[_a:_b]
assert subprocess.run(["bash", "-n"], input=TWIN, capture_output=True, text=True).returncode == 0, "bootstrap twin not lifted whole"

PRE = ('set -euo pipefail\n'
       'info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; b(){ printf %s "$*"; }\n')
STUBS = tempfile.mkdtemp(prefix="pf-stub-")
# `docker ps` answers a line at a time, as bash's printf does: the listing's FIRST line is the match, the rest come
# after $PF_PAUSE — the moment a reader that stopped early has closed the pipe. `compose` / `rm` are only logged.
open(os.path.join(STUBS, "docker"), "w").write(
    '#!/bin/bash\n'
    'case "$1" in\n'
    '  ps) first=1; for l in $PF_PS; do printf \'%s\\n\' "$l" || exit 141\n'
    '        [ -n "$first" ] && [ -n "${PF_PAUSE:-}" ] && sleep "$PF_PAUSE"; first=""; done;;\n'
    '  compose|rm) echo "docker $*" >> "$PF_LOG";;\n'
    'esac\nexit 0\n')
os.chmod(os.path.join(STUBS, "docker"), 0o755)

def bash(script, ps, pause, log):
    env = dict(os.environ, PATH=STUBS + ":" + os.environ["PATH"], PF_PS=ps, PF_PAUSE=pause, PF_LOG=log)
    r = subprocess.run(["bash", "-c", PRE + script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout + r.stderr

MASTER = "swg-panel swg-node swg-sub"     # the match first: the reader has what it needs after one line

def case_teardown(ps, pause):
    d = tempfile.mkdtemp(prefix="pf-td-"); open(os.path.join(d, "docker-compose.yml"), "w").write("services: {}\n")
    log = os.path.join(d, "log")
    # lc_node_nft_sweep rides along (round 12d): the teardown calls it first, and this stub names no image, so it returns;
    # lc_del_node_ifaces too (round 12e): the teardown deletes the node's interfaces through it (none here)
    rc, out = bash(fn(C, "lc_node_nft_sweep") + fn(C, "lc_del_node_ifaces") + fn(C, "lc_teardown_docker")
                   + 'lc_teardown_docker "%s"\necho RC=$?\n' % d, ps, pause, log)
    downs = open(log).read().count("compose down") if os.path.exists(log) else 0
    return rc, out, downs

def case_leftover(ps, pause, twin=False):
    d = tempfile.mkdtemp(prefix="pf-lo-"); open(os.path.join(d, "docker-compose.yml"), "w").write("services: {}\n")
    if twin:
        s = 'CHOICE=install; METHOD=baremetal; DOCKER_DIR="%s"; _dryrun_flag=no\n%s\necho RC=$?\n' % (d, TWIN)
    else:
        s = fn(C, "lc_clear_convert_leftover") + 'lc_clear_convert_leftover baremetal "%s"\necho RC=$?\n' % d
    rc, out = bash(s, ps, pause, os.path.join(d, "log"))
    return rc, out, os.path.isdir(d)

def case_footer(ps, pause):
    rc, out = bash(fn(C, "node_reconfig_block") + 'node_reconfig_block docker /opt/swg-panel-docker\n', ps, pause, "/dev/null")
    return rc, out, "--profile master up -d" in out

def many(fnc, args, n):
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(lambda _: fnc(*args), range(n)))

print("\n[2] the real functions, a docker whose `ps` writes a line at a time, set -euo pipefail — %d runs each (+%d pause-free)" % (RUNS, RUNS_FAST))
for pause, n, how in (("0.2", RUNS, "the match first, the rest 0.2 s later"), ("", RUNS_FAST, "pause-free")):
    res = many(case_teardown, (MASTER, pause), n)
    bad = [r for r in res if r[2] or "RC=0" not in r[1]]
    check("lc_teardown_docker on a master (%s): the stack is never taken down as node-only — %d/%d right" % (how, n - len(bad), n),
          not bad, bad[:1])
    res = many(case_leftover, (MASTER, pause), n)
    bad = [r for r in res if not r[2] or "removing a stale docker leftover" in r[1] or "RC=0" not in r[1]]
    check("lc_clear_convert_leftover beside a live Docker install (%s): the directory is never removed — %d/%d right" % (how, n - len(bad), n),
          not bad, bad[:1])
    res = many(case_leftover, (MASTER, pause, True), n)
    bad = [r for r in res if not r[2] or "stale docker leftover" in r[1] or "RC=0" not in r[1]]
    check("bootstrap.sh's twin beside a live Docker install (%s): the directory is never removed — %d/%d right" % (how, n - len(bad), n),
          not bad, bad[:1])
    res = many(case_footer, (MASTER, pause), n)
    bad = [r for r in res if not r[2]]
    check("node_reconfig_block on a master (%s): `--profile master up -d` — %d/%d right" % (how, n - len(bad), n), not bad, bad[:1])

# …and the decisions still go the other way when they should (a gate that can only say "keep" proves nothing)
rc, out, downs = case_teardown("swg-node", "0.2")
check("lc_teardown_docker on a node-only box still takes the stack down", downs == 1 and "RC=0" in out, (downs, out[-300:]))
rc, out, kept = case_leftover("", "0.2")
check("lc_clear_convert_leftover with no swg container still removes a convert's leftover", not kept and "removing a stale docker leftover" in out, out[-300:])
rc, out, kept = case_leftover("", "0.2", True)
check("…and so does bootstrap.sh's twin", not kept and "removing a stale docker leftover" in out, out[-300:])
rc, out, master = case_footer("swg-node", "0.2")
check("node_reconfig_block on a node still says `--profile node up -d`", not master and "--profile node up -d" in out, out[-300:])

print("\n[3] this environment shows the race, and the replacement reads the match — on any grep")
# ⚠️ A CONSUMER THAT STOPS AT ITS MATCH IS WAITED FOR, NOT GIVEN 0.2 s. Its 141 needs it gone before the producer's second
# line; a fixed sleep was outrun under load (the grep — or the stand-in below, a bash script — still starting), both
# lines sat in the pipe, nothing broke and the control read 0 (1.8.9 qualification: a three-run stress of the suite). So
# the producer waits (≤ 10 s) until the reader — the pipeline's other child of the shell — has exited. A reader that
# drains never exits first: the expected 0 there needs no wait, and keeps the 0.2 s.
_GONE = ('c=""; for _ in $(seq 500); do for p in $(cat /proc/$$/task/$$/children 2>/dev/null); do [ "$p" != "$BASHPID" ] && c=$p; done; '
         '[ -n "$c" ] && break; sleep 0.02; done; '
         'for _ in $(seq 500); do case "$(cut -d" " -f3 /proc/$c/stat 2>/dev/null)" in ""|Z|X) break;; esac; sleep 0.02; done')
def probe(consumer, path=None, stops=False):
    env = dict(os.environ, PATH=path) if path else None
    return subprocess.run(["bash", "-c", "set -o pipefail; { printf 'swg-panel\\n'; %s; printf 'swg-node\\n'; } | %s; echo $?"
                           % (_GONE if stops else "sleep 0.2", consumer)],
                          capture_output=True, text=True, env=env).stdout.strip()
q, full = probe("grep -qx swg-panel", stops=True), probe("grep -cx swg-panel >/dev/null")
check("`grep -qx` behind a producer that writes again: 141 under pipefail (the race [2] must survive)", q == "141", q)
check("`grep -cx … >/dev/null`: 0 — the count read every line", full == "0", full)
# A grep that stops at its first match whenever its output is discarded — POSIX allows it, a busybox or a future GNU
# may do it: -q semantics unless it counts. It hands every other case to the real grep, flags and all.
REAL_GREP = __import__("shutil").which("grep")
NODRAIN = tempfile.mkdtemp(prefix="pf-nodrain-")
open(os.path.join(NODRAIN, "grep"), "w").write(
    '#!/bin/bash\n'
    '# a grep that does not drain: its output discarded and nothing counted, it stops at the first match (as -q does)\n'
    'count=no; for a in "$@"; do case "$a" in --count) count=yes;; --*) ;; -*c*) count=yes;; esac; done\n'
    'if [ "$count" = no ] && [ "$(readlink -f /proc/$$/fd/1 2>/dev/null)" = /dev/null ]; then exec %s -q "$@"; fi\n'
    'exec %s "$@"\n' % (REAL_GREP, REAL_GREP))
os.chmod(os.path.join(NODRAIN, "grep"), 0o755)
ND_PATH = NODRAIN + ":" + os.environ["PATH"]
nd_bare, nd_count = probe("grep -x swg-panel >/dev/null", ND_PATH, stops=True), probe("grep -cx swg-panel >/dev/null", ND_PATH)
nd_none = probe("grep -cx swg-sub >/dev/null", ND_PATH)
check("the stand-in grep does not drain: a bare `grep -x … >/dev/null` behind it reads 141 (else this [3] proves nothing)",
      nd_bare == "141", nd_bare)
check("`grep -cx … >/dev/null` behind it: still 0 — the fix does not rest on how a grep treats /dev/null", nd_count == "0", nd_count)
check("…and still 1 when nothing matches (the count is a real answer, not a blanket 0)", nd_none == "1", nd_none)
print("  the functions of [2] under that grep — %d runs each, the match first and the rest 0.2 s later" % RUNS_NODRAIN)
STUBS_ND = STUBS + ":" + NODRAIN
def bash_nd(script, ps, pause, log):
    env = dict(os.environ, PATH=STUBS_ND + ":" + os.environ["PATH"], PF_PS=ps, PF_PAUSE=pause, PF_LOG=log)
    r = subprocess.run(["bash", "-c", PRE + script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout + r.stderr
_bash_real = bash
bash = bash_nd
try:
    res = many(case_teardown, (MASTER, "0.2"), RUNS_NODRAIN)
    bad = [r for r in res if r[2] or "RC=0" not in r[1]]
    check("…lc_teardown_docker on a master: never taken down as node-only — %d/%d right" % (RUNS_NODRAIN - len(bad), RUNS_NODRAIN), not bad, bad[:1])
    res = many(case_leftover, (MASTER, "0.2"), RUNS_NODRAIN)
    bad = [r for r in res if not r[2] or "removing a stale docker leftover" in r[1] or "RC=0" not in r[1]]
    check("…lc_clear_convert_leftover beside a live Docker install: never removed — %d/%d right" % (RUNS_NODRAIN - len(bad), RUNS_NODRAIN), not bad, bad[:1])
    res = many(case_leftover, (MASTER, "0.2", True), RUNS_NODRAIN)
    bad = [r for r in res if not r[2] or "stale docker leftover" in r[1] or "RC=0" not in r[1]]
    check("…bootstrap.sh's twin beside a live Docker install: never removed — %d/%d right" % (RUNS_NODRAIN - len(bad), RUNS_NODRAIN), not bad, bad[:1])
    res = many(case_footer, (MASTER, "0.2"), RUNS_NODRAIN)
    bad = [r for r in res if not r[2]]
    check("…node_reconfig_block on a master: `--profile master up -d` — %d/%d right" % (RUNS_NODRAIN - len(bad), RUNS_NODRAIN), not bad, bad[:1])
finally:
    bash = _bash_real

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_TEARDOWN or PERTURB_NODRAIN) else ""))
sys.exit(2 if (PERTURB or PERTURB_TEARDOWN or PERTURB_NODRAIN) else 0)
