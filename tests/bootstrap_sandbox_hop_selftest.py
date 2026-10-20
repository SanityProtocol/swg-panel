#!/usr/bin/env python3
"""Self-test — an update started inside swg-noded's sandbox runs again outside it (1.8.9 qualification F3b, IN-13's hole).

A 1.8.8 swg-noded starts the panel's Update with `systemd-run --scope`: another cgroup, but still swg-noded's mount
namespace, where ProtectSystem=true leaves /usr read-only and PrivateTmp's /tmp goes away when the update restarts
swg-noded. Round 1 fixed the NEW swg-noded's launcher (a transient service) — but on release day the launcher is the OLD
one, and what it fetches new is bootstrap.sh: the first hop of every 1.8.8 bare node failed exactly as before (EROFS
installing swg-logs, the module-source patch's traceback, mktemp failing, dpkg half-installed — "Update complete").
bootstrap.sh now notices the sandbox and runs itself again, same arguments and environment, as a transient service PID 1
starts, and exits with its code.

The REAL bootstrap.sh is run as shipped, with three hermetic substitutions (each anchor asserted): `[ -w /usr ]` and
`[ -d /run/systemd/system ]` point at the gate's own dirs, `command -v systemd-run` at the gate's name for it; and `id` / `readlink` / `stat` / `mktemp` / `git` /
`systemd-run` are stubs on PATH — readlink and stat answer only for the namespace and /tmp questions, mktemp only for the
hop dir, git lays down a probe update.sh that records how it was run, systemd-run runs the hop under `env -i` (a service
starts with PID 1's environment, not this one's) with the caller's stdio (--pipe).

  [1] in 1.8.8 swg-noded's sandbox (its own mount namespace, /usr read-only, a private /tmp): ONE systemd-run — a
      transient service (never --scope), the one unit name, collected, waited for, the caller's stdio; nothing to expand
      (no `$` in its argv: PID 1 substitutes ${…} / $$ in a service's command line) and no environment on it (--setenv
      is readable by every local user over D-Bus): the run file is 0600 in a 0700 dir. The run again: the same
      arguments, the guard set, the environment carried byte for byte (the panel's turn mirror with quotes, `$`, `&`, a
      newline; a proxy; SWG_REF) — the service's own INVOCATION_ID kept; update.sh ran ONCE, outside; its exit code is the
      caller's; its output reached the caller's stdout; the hop dir is gone
  [2] PrivateTmp alone (/usr writable, /tmp not PID 1's) is a sandbox too
  [3] `bash -c <text>` (no script file): the text itself is what runs again
  [4] runs in place: the guard already set · the same namespace as PID 1 · a namespace that only routes the journal
      (swg-update.service's LogNamespace=: /usr writable, the host's /tmp) · an uninstall
  [5] no systemd-run (or no systemd): it says so and goes on in place

Run: python3 tests/bootstrap_sandbox_hop_selftest.py        (0 = pass)
     --perturb        the hop taken out (q189-int2) → RED on [1] [2] [3] and [5]'s sentence only
     --perturb-env    the run file without this run's environment → RED on [1]'s environment only
     --perturb-guard  the guard not asked → RED on [4]'s guard case only
"""
import os, re, shlex, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv[1:]
PERTURB_ENV = "--perturb-env" in sys.argv[1:]
PERTURB_GUARD = "--perturb-guard" in sys.argv[1:]
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
def sub(s, old, new):
    assert s.count(old) == 1, "anchor missing or not unique — would FALSE-PASS: %r" % old
    return s.replace(old, new)
src = sub(src, '[ -w /usr ] || return 0', '[ -w "$GATE_USR" ] || return 0')
src = sub(src, '[ -d /run/systemd/system ]', '[ -d "$GATE_SYSD" ]')
src = sub(src, 'command -v systemd-run >/dev/null', 'command -v "$GATE_SR" >/dev/null')   # [5]: never this box's own
if PERTURB:   # the hop taken out: q189-int2's bootstrap ran the update wherever it was started
    src = sub(src, 'if [ "$ACTION" = update ] && [ -z "${SWG_UPDATE_HOP:-}" ] && _swg_sandboxed; then',
              'if false; then')
if PERTURB_ENV:
    src = sub(src, "        if [ -n \"${!_k+x}\" ]; then printf '[ -n \"${%s+x}\" ] || export %s=%q\\n' \"$_k\" \"$_k\" \"${!_k}\"; fi\n", "")
if PERTURB_GUARD:
    src = sub(src, '[ "$ACTION" = update ] && [ -z "${SWG_UPDATE_HOP:-}" ] && _swg_sandboxed', '[ "$ACTION" = update ] && _swg_sandboxed')

T = tempfile.mkdtemp(prefix="sbhop-")
BIN, RUN, LOG = T + "/bin", T + "/run", T + "/log"
for d in (BIN, RUN, T + "/sysd", T + "/usr-ro", T + "/usr-rw"):
    os.makedirs(d)
os.chmod(T + "/usr-ro", 0o555)
open(T + "/bootstrap.sh", "w").write(src)
def stub(name, body):
    p = os.path.join(BIN, name)
    open(p, "w").write("#!/bin/bash\n" + body + "\n")
    os.chmod(p, 0o755)
REAL = lambda n: subprocess.run(["bash", "-c", "command -v " + n], capture_output=True, text=True).stdout.strip()
stub("id", '[ "${1:-}" = -u ] && { echo 0; exit 0; }; exec %s "$@"' % REAL("id"))
stub("readlink", 'case "$*" in /proc/self/ns/mnt) echo "$GATE_SELF_NS";; /proc/1/ns/mnt) echo "$GATE_PID1_NS";; '
                 '*) exec %s "$@";; esac' % REAL("readlink"))
stub("stat", 'case "${@: -1}" in /tmp) echo "$GATE_TMP_ID";; /proc/1/root/tmp) echo "$GATE_PID1_TMP";; *) exec %s "$@";; esac' % REAL("stat"))
stub("mktemp", 'if [ "$*" = "-d /run/swg-update-hop.XXXXXX" ]; then exec %s -d "$GATE_RUN/swg-update-hop.XXXXXX"; fi; exec %s "$@"'
     % (REAL("mktemp"), REAL("mktemp")))
# git clone … <dest>: the "repo" is a probe update.sh / uninstall.sh that records how it ran, and exits with GATE_PROBE_RC
PROBE = ('{ printf "ARGS=%s\\0" "$*"; for v in SWG_UPDATE_HOP GATE_SELF_NS SWG_TURN_MIRROR http_proxy SWG_REF INVOCATION_ID; do '
         'printf "%s=%s\\0" "$v" "${!v-}"; done; } > "$(mktemp "$GATE_LOG/ran.XXXXXX")"\n'
         'echo "probe output line"\nexit "${GATE_PROBE_RC:-0}"\n')
stub("git", 'for a; do d="$a"; done; mkdir -p "$d"; printf %%s %s > "$d/update.sh"; cp "$d/update.sh" "$d/uninstall.sh"' % shlex.quote(PROBE))
# systemd-run: what PID 1 would do — the run file under env -i (a service's own environment: PATH, its INVOCATION_ID, and
# the namespace PID 1 gives it), the caller's stdio (--pipe), its exit code (--wait). The run file's modes are noted first.
# (the gate's own GATE_* plumbing is handed over here, so that only the product's environment depends on the carry)
stub("systemd-run", 'printf "%s\\n" "$@" > "$GATE_LOG/argv"; r="${@: -1}"; '
                    'stat -c "%a" "$(dirname "$r")" "$r" > "$GATE_LOG/modes"; cp "$r" "$GATE_LOG/runfile"; '
                    'g=(); for v in $(compgen -e); do case "$v" in GATE_*) g+=("$v=${!v}");; esac; done; '
                    'env -i PATH="$PATH" INVOCATION_ID=service-own "${g[@]}" GATE_SELF_NS="$GATE_PID1_NS" bash "$r"')

SANDBOX = dict(GATE_SELF_NS="mnt:[4026532984]", GATE_PID1_NS="mnt:[4026531832]", GATE_TMP_ID="2049:777", GATE_PID1_TMP="2049:12",
               GATE_USR=T + "/usr-ro")
MIRROR = "https://mirror.example/gh?a='b'&c=$x \"q\"\nline2"
def run(args, env_extra, text_form=False, sysd=True, sr="systemd-run"):
    for f in os.listdir(LOG) if os.path.isdir(LOG) else []:
        os.remove(os.path.join(LOG, f))
    os.makedirs(LOG, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SWG_", "GATE_"))}
    env.update(PATH=BIN + ":" + os.environ.get("PATH", ""), GATE_LOG=LOG, GATE_RUN=RUN, GATE_SR=sr,
               GATE_SYSD=T + "/sysd" if sysd else T + "/nosysd", SWG_REPO="https://example.invalid/swg-panel",
               SWG_TURN_MIRROR=MIRROR, http_proxy="http://user:p%40ss@proxy:3128", INVOCATION_ID="swg-noded-invocation",
               GATE_PROBE_RC="5")
    env.pop("SWG_UPDATE_HOP", None)
    env.update(env_extra)
    if text_form:
        argv = ["bash", "-c", open(T + "/bootstrap.sh").read(), "--"] + args
    else:
        argv = ["bash", T + "/bootstrap.sh"] + args
    p = subprocess.run(argv, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    rans = []   # one dict per run of update.sh: its arguments and the environment it saw
    for f in sorted(os.listdir(LOG)):
        if f.startswith("ran."):
            rans.append(dict(x.split("=", 1) for x in open(os.path.join(LOG, f)).read().split("\0") if x))
    rd = lambda n: open(os.path.join(LOG, n)).read() if os.path.exists(os.path.join(LOG, n)) else None
    return p, rans, rd("argv"), rd("modes"), rd("runfile")
ARGS = ["update", "-y", "--no-components", "--node-only"]

print("[1] in 1.8.8 swg-noded's sandbox the update runs again, as a service, outside it")
p, rans, argv, modes, runfile = run(ARGS, dict(SANDBOX, SWG_REF="dev"))   # not main: main is also what an uncarried run infers
av = (argv or "").splitlines()
check("one systemd-run: a transient service (no --scope), unit swg-self-update, --collect --wait --pipe --quiet",
      argv is not None and "--scope" not in av and av[:2] == ["--unit", "swg-self-update"]
      and all(o in av for o in ("--collect", "--wait", "--pipe", "--quiet")) and av[-2] == "bash", av)
check("…nothing in its argv for PID 1 to expand (no `$`) and no environment on it (no --setenv / -E / Environment=)",
      argv is not None and "$" not in argv and not any(a in ("-E", "--setenv") or a.startswith(("--setenv=", "-pEnvironment"))
                                                      for a in av), av)
check("…the run file 0600 in a 0700 dir (only root reads the environment it carries)",
      (modes or "").split() == ["700", "600"], modes)
r0 = rans[0] if len(rans) == 1 else {}
check("update.sh ran ONCE — in the service, outside the sandbox (PID 1's namespace), the guard set",
      r0.get("GATE_SELF_NS") == "mnt:[4026531832]" and r0.get("SWG_UPDATE_HOP") == "1", rans)
check("…with the same arguments", r0.get("ARGS") == "-y --no-components --node-only", r0)
check("…the panel's turn mirror carried byte for byte (quotes, `$`, `&`, a newline) — env -i started it empty",
      r0.get("SWG_TURN_MIRROR") == MIRROR, r0)
check("…a proxy carried, SWG_REF carried", r0.get("http_proxy") == "http://user:p%40ss@proxy:3128" and r0.get("SWG_REF") == "dev", r0)
check("…the service's own INVOCATION_ID kept (the carried environment fills only what it lacks)",
      r0.get("INVOCATION_ID") == "service-own", r0)
check("its exit code is the caller's (5 → 5: the old launcher's verdict stays true)", p.returncode == 5, (p.returncode, p.stderr[-300:]))
check("its output reached the caller's stdout (--pipe), after the line that says why it runs again",
      "probe output line" in p.stdout and p.stdout.find("running it again as a service") < p.stdout.find("probe output line")
      and p.stdout.find("running it again as a service") >= 0, p.stdout[-600:])
check("the hop dir is gone", os.listdir(RUN) == [], os.listdir(RUN))

print("\n[2] PrivateTmp alone is a sandbox too")
p, rans, argv, _, _ = run(ARGS, dict(SANDBOX, GATE_USR=T + "/usr-rw"))
check("/usr writable, /tmp not PID 1's → run again as a service", argv is not None and len(rans) == 1
      and rans[0].get("GATE_SELF_NS") == "mnt:[4026531832]", (argv, rans))

print("\n[3] `bash -c <text>`: the text itself runs again")
p, rans, argv, _, runfile = run(ARGS, SANDBOX, text_form=True)
check("no script file → the hop runs the text it was given; update.sh ran once, outside, rc 5",
      argv is not None and len(rans) == 1 and rans[0].get("GATE_SELF_NS") == "mnt:[4026531832]" and p.returncode == 5,
      (argv, rans, p.returncode, p.stderr[-300:]))

print("\n[4] where it runs in place")
cases = (("the guard already set (the run again itself)", dict(SANDBOX, SWG_UPDATE_HOP="1"), ARGS),
         ("the same namespace as PID 1 (a root shell, the new swg-noded's service)",
          dict(SANDBOX, GATE_SELF_NS="mnt:[4026531832]"), ARGS),
         ("a namespace that only routes the journal (LogNamespace=: /usr writable, the host's /tmp)",
          dict(SANDBOX, GATE_USR=T + "/usr-rw", GATE_TMP_ID="2049:12"), ARGS),
         ("an uninstall (only an update is started from swg-noded)", SANDBOX, ["uninstall", "-y"]))
for name, env, args in cases:
    p, rans, argv, _, _ = run(args, env)
    check("%s → no systemd-run; it ran once, in place" % name,
          argv is None and len(rans) == 1 and rans[0].get("GATE_SELF_NS") == env["GATE_SELF_NS"] and p.returncode == 5,
          (argv, rans, p.returncode, p.stderr[-300:]))

print("\n[5] no systemd-run")
for name, kw in (("no systemd-run on PATH", dict(sr="no-such-systemd-run")), ("no systemd (/run/systemd/system)", dict(sysd=False))):
    p, rans, argv, _, _ = run(ARGS, SANDBOX, **kw)
    check("%s → it says so and goes on in place" % name,
          argv is None and len(rans) == 1 and rans[0].get("GATE_SELF_NS") == SANDBOX["GATE_SELF_NS"]
          and "cannot be run again outside it" in p.stderr,
          (argv, rans, p.stderr[-300:]))

print("")
for on, label, pick in ((PERTURB, "[1] [2] [3] [5]", lambda f: not f.startswith(("the guard", "the same", "a namespace", "an uninstall"))),
                        (PERTURB_ENV, "[1]'s environment", lambda f: "carried" in f),
                        (PERTURB_GUARD, "[4]'s guard case", lambda f: f.startswith("the guard"))):
    if on:
        print("perturb: %s" % ("RED as it must be (%d), all %s" % (len(FAILS), label) if FAILS and all(pick(f) for f in FAILS)
                               else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % [f for f in FAILS if not pick(f)]))
        sys.exit(0 if FAILS and all(pick(f) for f in FAILS) else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
