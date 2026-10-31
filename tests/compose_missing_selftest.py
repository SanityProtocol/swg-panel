#!/usr/bin/env python3
"""Self-test — a Docker without its Compose plugin stops the install before anything changes, naming what to install.

A user's Docker node install ended in docker's own "unknown flag: --profile" (2026-10-31): their Docker came from the
distribution's docker.io without the Compose v2 plugin, and install-docker.sh only warned and carried on to
`docker compose --profile node up`. On a bare→Docker conversion that path reaches the switch-over that tears the bare
install down before the containers start. Now install-docker.sh (after the daemon is proven, before the staging) and
convert.sh (before the master / host path's recovery marker, and before the node path moves a leftover aside, signals
"converting" or writes its marker) stop with lib/common.sh compose_missing: the command for THIS Docker (docker-ce →
docker-compose-plugin; docker.io on Ubuntu or a derivative → docker-compose-v2; a held package counts), or Docker's
install page and both commands. The installers never run apt for it (operator, 2026-10-31).

The shipped code is lifted out of lib/common.sh, install-docker.sh and convert.sh and run under bash with stubs on PATH.

Run: python3 tests/compose_missing_selftest.py                 (0 = pass)
     --perturb-<name>  one fix undone, expects RED:
                       warnonly | nodeskip | hold | derivative | enginepick | aptinstall | daemonlast
"""
import atexit, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = {f: open(os.path.join(ROOT, f), encoding="utf-8").read() for f in ("lib/common.sh", "install-docker.sh", "convert.sh")}
BASE = tempfile.mkdtemp(prefix="compose-missing-")
atexit.register(shutil.rmtree, BASE, True)                # every stub world goes with the run (the gate /tmp leak class)

STOP = ('else COMPOSE="$(compose_probe)" || die "$(compose_missing) — nothing has been changed${SWG_CONVERT_DIR:+, and your '
        'bare-metal install is still serving}."\n')
CBLK_HEAD = "# …and Compose, which nothing below can start without"
DAEMON_HEAD = "# The client binary existing says NOTHING about the daemon being up"
def _daemonlast(s):         # Compose asked before the daemon is proven
    i = s.index(CBLK_HEAD); j = s.index("\n\n", i) + 1
    blk = s[i:j]; s = s[:i] + s[j:]
    k = s.index(DAEMON_HEAD)
    return s[:k] + blk + s[k:]
PLANTS = {
    "warnonly": ("install-docker.sh", lambda s: s.replace(STOP, 'else COMPOSE="$(compose_probe)" || { COMPOSE="docker compose"; warn "docker compose plugin not detected"; }\n')),
    "nodeskip": ("convert.sh", lambda s: s.replace('  need_compose          # before the leftover is moved aside', '  :          # before the leftover is moved aside')),
    "hold": ("lib/common.sh", lambda s: s.replace('docker-ce 2>/dev/null)" in *"ok installed")', 'docker-ce 2>/dev/null)" in *"install ok installed")')),
    "derivative": ("lib/common.sh", lambda s: s.replace('case " ${ID:-} ${ID_LIKE:-} " in', 'case " ${ID:-} " in')),
    "enginepick": ("lib/common.sh", lambda s: s.replace('''  case "$(dpkg-query -W -f='${Status}' docker-ce 2>/dev/null)" in *"ok installed") echo docker-compose-plugin; return 0;; esac\n''', "")),
    "aptinstall": ("lib/common.sh", lambda s: s.replace("compose_probe(){                 # the Compose command that answers, on stdout, or exit 1 — read-only\n",
                                                        "compose_probe(){                 # the Compose command that answers, on stdout, or exit 1 — read-only\n  apt-get install -y docker-compose-v2 >/dev/null 2>&1\n")),
    "daemonlast": ("install-docker.sh", _daemonlast),
}
for a in sys.argv[1:]:
    if a.startswith("--perturb-"):
        f, fx = PLANTS[a[len("--perturb-"):]]
        new = fx(SRC[f])
        assert new != SRC[f], "plant %s changed nothing — its anchor is stale" % a
        SRC[f] = new

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def cut(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]

LIB = cut(SRC["lib/common.sh"], "compose_probe(){", "# installed_sum")      # compose_probe … compose_missing, as shipped

def world(compose=False, standalone=False, engine="docker.io", status="install ok installed", osr="ID=ubuntu\n", daemon=True):
    """A PATH of stubs: `docker compose version` answers when `compose`; dpkg-query reports `engine` with `status`; an
    apt-get that only records being called (it must never be); os-release as `osr`."""
    d = tempfile.mkdtemp(dir=BASE); log = os.path.join(d, "log")
    def stub(name, body):
        p = os.path.join(d, name)
        open(p, "w").write("#!/bin/bash\necho \"%s $*\" >> %s\n%s\n" % (name, log, body)); os.chmod(p, 0o755)
    stub("docker", ('if [ "$1 $2" = "compose version" ]; then exit %d; fi\nif [ "$1" = info ]; then exit %d; fi\nexit 0')
         % (0 if compose else 1, 0 if daemon else 1))
    if standalone:
        stub("docker-compose", "exit 0")
    stub("dpkg-query", '[ "${@: -1}" = %s ] && { printf "%s"; exit 0; }; exit 1' % (engine, status))
    stub("apt-get", "exit 0"); stub("systemctl", "exit 0"); stub("sleep", "exit 0")
    f = os.path.join(d, "os-release"); open(f, "w").write(osr)
    for t in ("grep", "tail", "python3"):                 # the real tools the shipped code pipes through
        os.symlink(shutil.which(t), os.path.join(d, t))
    return d, log, f

def bash(d, osr, script):
    p = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d, SWG_OS_RELEASE=osr))
    return p.returncode, p.stdout + p.stderr

def calls(log):
    return open(log).read() if os.path.exists(log) else ""

HDR = ('set -uo pipefail\nb(){ printf %%s "$*"; }\ninfo(){ echo "INFO $*"; }\nsub(){ echo "SUB $*"; }\nwarn(){ echo "WARN $*"; }\n'
       'die(){ echo "DIE $*"; exit 1; }\nhave(){ command -v "$1" >/dev/null 2>&1; }\nrun(){ "$@"; }\n%s\n')

def missing(**kw):
    d, log, osr = world(**kw)
    rc, out = bash(d, osr, (HDR % LIB) + 'if c="$(compose_probe)"; then echo "OK $c"; else compose_missing; fi')
    return out, calls(log)

print("[1] what it says for THIS Docker — and that it never installs anything itself")
out, c = missing(compose=True)
check("[1] Compose present: used", "OK docker compose" in out, out)
out, c = missing(standalone=True)
check("[1] only the standalone docker-compose: used, as before", "OK docker-compose" in out, out)
out, c = missing(engine="docker-ce")
check("[1] docker-ce: apt install docker-compose-plugin", "Install it with: apt install docker-compose-plugin" in out, out)
out, c = missing(engine="docker-ce", status="hold ok installed")
check("[1] …a held docker-ce too (apt-mark hold)", "Install it with: apt install docker-compose-plugin" in out, out)
out, c = missing(engine="docker.io", osr="ID=ubuntu\n")
check("[1] Ubuntu's docker.io: apt install docker-compose-v2", "Install it with: apt install docker-compose-v2" in out, out)
out, c = missing(engine="docker.io", osr='ID=linuxmint\nID_LIKE="ubuntu debian"\n')
check("[1] …a derivative's (ID_LIKE=ubuntu, Linux Mint) too", "Install it with: apt install docker-compose-v2" in out, out)
out, c = missing(engine="docker.io", osr="ID=debian\n")
check("[1] Debian's docker.io: no package guessed — Docker's install page and both commands",
      "Install it with" not in out and "docs.docker.com/compose/install" in out and "docker-compose-plugin" in out, out)
out, c = missing(engine="none")
check("[1] an engine dpkg does not know: the same general advice", "docs.docker.com/compose/install" in out, out)
calls_all = "".join(missing(**kw)[1] for kw in ({}, {"engine": "docker-ce"}, {"osr": "ID=debian\n"}))
check("[1] apt is never run — the installers say what to install, they do not install it", "apt-get" not in calls_all, calls_all)

print("\n[2] install-docker.sh: the daemon, then Compose — a stop before the staging while nothing is changed")
BLOCK = cut(SRC["install-docker.sh"], "# ───────────────────────── ensure Docker", "# ───────────────────────── stage project")
def install(dry=False, convert=False, **kw):
    d, log, osr = world(**kw)
    rc, out = bash(d, osr, (HDR % LIB) + 'DRYRUN=%s\n%s%s\necho "REACHED-STAGING with $COMPOSE"\n'
                   % ("true" if dry else "false", "SWG_CONVERT_DIR=/x\n" if convert else "", BLOCK))
    return rc, out, calls(log)
rc, out, c = install()
check("[2] no Compose: it stops before the staging", rc == 1 and "REACHED-STAGING" not in out and "DIE Docker Compose is missing" in out, out)
check("[2] …naming this Docker's package and that nothing has been changed", "apt install docker-compose-v2" in out and "nothing has been changed" in out, out)
rc, out, c = install(convert=True)
check("[2] …on a conversion, that the bare-metal install is still serving", "still serving" in out, out)
rc, out, c = install(daemon=False)
check("[2] a dead daemon is reported first (it is the first thing to fix)", rc == 1 and "daemon isn't running" in out and "Compose is missing" not in out, out)
rc, out, c = install(compose=True)
check("[2] Compose present: the install goes on with docker compose", rc == 0 and "REACHED-STAGING with docker compose" in out, out)
rc, out, c = install(dry=True)
check("[2] a dry run only reads", rc == 0 and "REACHED-STAGING" in out and "apt-get" not in c, (out, c))

print("\n[3] convert.sh: a stop before the conversion touches anything, on every path")
NEED = cut(SRC["convert.sh"], "need_compose(){", "\n# ")
CB = cut(SRC["convert.sh"], "  # ⚠️ DOCKER IS INSTALLED HERE, NOT REFUSED.", '  info "Converting the bare-metal $(b "$ROLE") → docker')
def convert(**kw):
    d, log, osr = world(**kw)
    rc, out = bash(d, osr, (HDR % LIB) + "%s\nROLE=master\n%s\necho REACHED-RECOVERY\n" % (NEED, CB))
    return rc, out
rc, out = convert()
check("[3] master / host: no Compose — the conversion stops before its recovery marker, the bare install serving",
      rc == 1 and "REACHED-RECOVERY" not in out and "still serving" in out, out)
rc, out = convert(compose=True)
check("[3] master / host: Compose present — the conversion goes on", rc == 0 and "REACHED-RECOVERY" in out, out)
cs = SRC["convert.sh"]
node = cs[cs.index('if docker_node_present; then die "a docker node (swg-node container) already exists'):]
nc = node.find("\n  need_compose")
check("[3] node: Compose is asked before the leftover is moved aside, \"converting\" signalled and the recovery marker written",
      nc != -1 and all(nc < node.index(m) for m in ('mv "$DOCKER_DIR" "$_bak"', "lc_init convert-docker lc_emit_post", 'write_recovery "$names"')), nc)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS[:6])))
    sys.exit(1)
print("ALL PASS")
