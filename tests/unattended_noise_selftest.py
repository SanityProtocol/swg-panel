#!/usr/bin/env python3
"""Self-test — an unattended run (no terminal, `</dev/null`) says only true things, and every question it can meet
has a real way to be answered without one. All found in one qualification pass (1.8.8, bare-metal VMs):

  [1] `./install-host.sh: line 203: /dev/tty: No such device or address` — a raw bash error from every prompt's
      `read … </dev/tty`, printed before the default was taken. install-host.sh + install-node.sh + ask_secret.
  [2] bootstrap.sh's convert / keep / abort question died with "…or pass it as a flag (one of: convert keep abort)",
      and no such flag existed. It does now (the bare words, or -on-conflict / SWG_ON_CONFLICT), a `convert` answer
      also answers the "proceed?" confirm, and a refused convert does not spin on its own preset answer.
  [3] update.sh printed "✓ Update finished — nothing changed." right after "✓ docker address helper healed".
  [4] "usermod: no changes" on every re-install.
  [5] the two-panel guard said it stopped "a bare-metal panel (swg-panel-server.service)" — it stops swg-sub too.

Each piece is lifted out of the scripts AS SHIPPED and run with stubs, in a NEW SESSION (no controlling terminal —
opening /dev/tty fails exactly as it does under `setsid … </dev/null`).

Run: python3 tests/unattended_noise_selftest.py     (0 = pass)
     --perturb   re-plants all five shipped behaviours → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
H, N, B, UP, C = rd("install-host.sh"), rd("install-node.sh"), rd("bootstrap.sh"), rd("update.sh"), rd("lib/common.sh")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b, count=1):
    assert src.count(a) == count, "perturbation anchor missing — would FALSE-PASS: " + a[:80]
    return src.replace(a, b)

if PERTURB:
    H = plant(H, "_tty && read -rp", "read -rp", 4)                                                          # [1]
    N = plant(N, "_tty && read -rp", "read -rp", 4)
    C = plant(C, "'keep current')]}\" 2>/dev/null >/dev/tty", "'keep current')]}\" >/dev/tty 2>/dev/null")
    B = plant(B, "    convert|keep|abort)          ON_CONFLICT=\"$1\"; shift;;\n", "")                        # [2]
    UP = plant(UP, '  DID_UPDATE=yes; note "docker address helper: healed (was missing)"\n', "")             # [3]
    H = plant(H, 'usermod_to(){ [ "$(getent passwd "$1" 2>/dev/null | cut -d: -f6)" = "$2" ] && [ "$(id -gn "$1" 2>/dev/null)" = "$3" ] && return 0\n',
              "usermod_to(){ \n")                                                                             # [4]
    C = plant(C, 'echo "  ✓ stopped $what and its subscription server (swg-sub) — its data is still on disk"',
              'echo "  ✓ stopped $what — its data is still on disk"')                                          # [5]

def fn(src, name):
    """The function `name(){ … }` exactly as shipped: from its header to the FIRST closing line at which the text
    parses (`bash -n`) — so a `…; }` inside the body (an inline `{ …; }` group) is never mistaken for the end, and
    the top-level code after a function that closes with `; }` is never swallowed with it."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if not l.split("  #")[0].rstrip().endswith("}"):
            continue
        text = "\n".join(lines[:k + 1]) + "\n"
        if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
            return text
    raise AssertionError("unterminated " + name)

def between(src, a, b, skip=False):
    i = src.index(a); j = src.index(b, i)
    return src[i + (len(a) if skip else 0):j]

def bash(script, stubs=None, env=None, timeout=20):
    d = tempfile.mkdtemp(prefix="noise-"); log = os.path.join(d, "calls")
    for name, body in (stubs or {}).items():
        p = os.path.join(d, name)
        open(p, "w").write('#!/bin/bash\necho "%s $*" >> %s\n%s\n' % (name, log, body)); os.chmod(p, 0o755)
    e = dict(os.environ, PATH=d + ":" + os.environ["PATH"], T=d); e.update(env or {})
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL,
                       start_new_session=True, timeout=timeout)   # NEW SESSION: no controlling terminal, like setsid
    return p.returncode, p.stdout, p.stderr, (open(log).read() if os.path.exists(log) else ""), d

PRE = ('set -euo pipefail\nRESET=""; BOLD=""; C_BLUE=""; C_BROWN=""; C_RED=""; C_BL=""\ncol(){ shift; printf %s "$*"; }\n'
       'b(){ printf %s "$*"; }\n_pnl(){ :; }\nwarn(){ echo "WARN $*" >&2; }\ninfo(){ echo "INFO $*"; }\n'
       'die(){ echo "DIE $*" >&2; exit 9; }\nv_ok(){ [ -n "$1" ]; }\n')

print("[1] no terminal → the prompt takes its default WITHOUT a raw '/dev/tty' error")
for label, src in (("install-host.sh", H), ("install-node.sh", N)):
    helpers = fn(src, "_tty") + fn(src, "_notty") + fn(src, "ask") + fn(src, "ask_yn") + fn(src, "ask_choice") + fn(src, "ask_valid")
    rc, out, err, _, _ = bash(PRE + helpers + 'ask "Name" dflt A; ask_yn "Sure" y Y; ask_choice "Pick" one C "one two"; '
                              'ask_valid "Port" 8443 V v_ok "need one"\necho "A=$A Y=$Y C=$C V=$V"\n')
    check("%s: ask / ask_yn / ask_choice / ask_valid all take their default" % label, "A=dflt Y=yes C=one V=8443" in out, (out, err))
    check("%s: …and not one '/dev/tty: No such device' line" % label, "/dev/tty" not in err, err)
rc, out, err, _, _ = bash(PRE + fn(C, "ask_secret") + 'ask_secret "Token" keepme S v_ok "need one"\necho "S=$S"\n')
check("lib/common.sh ask_secret: same, no raw '/dev/tty' line", "S=keepme" in out and "/dev/tty" not in err, (out, err))

print("\n[2] bootstrap.sh's convert / keep / abort has a flag, and the refusal names it")
parse = between(B, "PASS=()\n", '[ "$METHOD" = bare-metal ] && METHOD=baremetal')
cross = between(B, 'ROLE_COMPS=""; case "$ROLE"', "\n# A plain (re-)install clears")
ask = fn(B, "ask_choice") + fn(B, "ask_yn")
def boot(args, env=None, check_ok=True):
    body = ('ACTION=""; METHOD="${METHOD:-}"; ROLE="${ROLE:-}"; ROLE_EXPLICIT=no; HAVE_KEY=no\nON_CONFLICT="${SWG_ON_CONFLICT:-}"\n'
            'set -- %s\n' % args + "PASS=()\n" + parse +
            '[ -n "$METHOD" ] || METHOD=baremetal\n'
            'has_comp(){ case "$1-$2" in docker-panel|docker-node) return 0;; *) return 1;; esac; }\n'
            'mlabel(){ echo "$1"; }\nmenu(){ :; }\n'
            'run_script(){ echo "RUN_SCRIPT $*"; exit 0; }\n' + cross + '\necho "METHOD=$METHOD ROLE=$ROLE"\n')
    conv = os.path.join(tempfile.mkdtemp(prefix="cv-"), "convert.sh")
    open(conv, "w").write("#!/bin/bash\nexit %d\n" % (0 if check_ok else 1))
    return bash(PRE + ask + "cd %s\n" % os.path.dirname(conv) + body, env=env)
rc, out, err, _, _ = boot("master keep")
check("`master keep` → keeps the existing docker install, re-installs it as it is — no prompt",
      rc == 0 and "METHOD=docker ROLE=master" in out and "keeping the existing" in out, (rc, out, err))
rc, out, err, _, _ = boot("master -on-conflict abort")
check("`-on-conflict abort` → aborted, nothing changed", rc == 0 and "aborted" in out, (rc, out, err))
rc, out, err, _, _ = boot("master", env={"SWG_ON_CONFLICT": "convert"})
check("SWG_ON_CONFLICT=convert → pre-flight, then straight into convert.sh (the flag answers the confirm too)",
      "RUN_SCRIPT convert.sh docker baremetal master" in out and "no interactive input" not in err, (rc, out, err))
rc, out, err, _, _ = boot("master convert", check_ok=False)
check("a convert whose pre-flight refuses → stops with a reason, does not spin on its own preset answer",
      rc == 9 and "did not go ahead" in err, (rc, out, err))
rc, out, err, _, _ = boot("master")
check("no flag, no terminal → refused, and the refusal names a flag that EXISTS (-on-conflict)",
      rc == 9 and "-on-conflict" in err and "one of: convert keep abort)" not in err, (rc, err))

print("\n[3] update.sh: a heal is a change — 'nothing changed' is not said after one")
t = tempfile.mkdtemp(prefix="heal-"); sd = os.path.join(t, "systemd"); bindir = os.path.join(t, "bin"); os.makedirs(sd); os.makedirs(bindir)
os.makedirs(os.path.join(t, "src", "docker")); open(os.path.join(t, "src", "docker", "swg-netctl-docker"), "w").write("#!/bin/sh\n")
heal = fn(UP, "ensure_netctl_docker").replace("/etc/systemd/system", sd).replace("/usr/local/bin", bindir)
rc, out, err, calls, _ = bash('set -uo pipefail\nDRYRUN=false; DID_UPDATE=no; SRC=%s/src; DOCKER_DIR=%s/dd\nRESULTS=(); note(){ RESULTS+=("$*"); }\n'
                              'ok(){ echo "OK $*"; }; info(){ :; }; warn(){ :; }\n%sensure_netctl_docker host\n'
                              'echo "DID_UPDATE=$DID_UPDATE"; printf "NOTE %%s\\n" "${RESULTS[@]}"\n' % (t, t, heal),
                              {"systemctl": "exit 0", "install": 'cp "$3" "$4" && chmod 755 "$4"'})
check("the docker address helper is healed (it was missing)", "docker address helper healed" in out, (out, err))
check("…and that COUNTS: DID_UPDATE=yes and it is listed under the changes", "DID_UPDATE=yes" in out and "NOTE docker address helper" in out, out)

print("\n[4] usermod only when it would change something")
um = fn(H, "usermod_to")
for home, grp, want in (("/var/lib/swg-panel", "swg", False), ("/home/old", "swg", True), ("/var/lib/swg-panel", "users", True)):
    rc, out, err, calls, _ = bash('run(){ "$@"; }\n%susermod_to swgpanel /var/lib/swg-panel swg\n' % um,
                                  {"getent": 'echo "swgpanel:x:998:998::%s:/usr/sbin/nologin"' % home,
                                   "id": 'echo %s' % grp, "usermod": 'echo "usermod: no changes" >&2'})
    check("home %s, group %s → usermod %s" % (home, grp, "runs" if want else "is NOT run (no 'usermod: no changes')"),
          ("usermod " in calls) == want, calls)

print("\n[5] the two-panel guard says it stopped swg-sub too")
unit = os.path.join(t, "swg-panel-server.service"); open(unit, "w").write("[Unit]\n")
g = fn(C, "guard_second_panel").replace("/etc/systemd/system/swg-panel-server.service", unit)
rc, out, err, calls, _ = bash('%sguard_second_panel docker\n' % g, {"systemctl": "exit 0"}, env={"SWG_OTHER_PANEL": "stop"})
check("it stops both units…", "disable --now swg-panel-server swg-sub" in calls, calls)
check("…and says so: the ✓ line names swg-sub", re.search(r"✓ stopped .*swg-sub", out) is not None, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
