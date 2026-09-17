#!/usr/bin/env python3
"""Self-test: every command swg-noded itself executes is on the NixOS native unit's PATH (nix/modules/node.nix `path`).

NixOS sets a unit's PATH to EXACTLY the packages its `path` lists, plus the five `apply` appends (coreutils, findutils,
gnugrep, gnused, systemd). A command missing there is not an error anyone sees: `run()` returns rc 127 and the caller reads it
as "nothing to report". Measured on the nixos fleet box (1.8.7 qualification PART 3): `ping` was absent, so the mesh probe
never produced a sample and every NixOS native node read "mesh 0/3" while its links carried traffic. It survived because
.campaign/nix-path-audit.mjs reads only docker/node-entrypoint.sh — never the daemon's own commands.

  [1] the module's `path` list parses (comments stripped) and names the packages this gate relies on
  [2] every command literal swg-noded hands to a process call maps to a package, and that package is in the path
  [3] a command this gate has never seen FAILS until someone maps it — a new binary is never silently assumed present
  [4] the fixture: `ping` is among the daemon's commands (the mesh probe) and `iputils` provides it
  [5] the CONTAINER image (Dockerfile.node, final stage — docker nodes and the NixOS podman arm): every command maps to a Debian
      package that stage installs, a binary it copies in, or the slim base's essentials. The same `ping` was missing there
      too (measured on svo-im: `command -v ping` → nothing), so every container node also read "mesh 0/N".
  [6] every command a `host_sh("…")` SHELL string runs on a native node is on that PATH too — or is a shell builtin, or sits
      where only a docker node can reach it. Measured (1.8.7 qualification PART 4, A3): `host_sh("docker stop <id>")` in the
      foreign WDTT/csqtt take-over ran through the native unit's shell, where no container CLI exists — rc 127, swallowed —
      and a csqtt server in a `restart: unless-stopped` container survived its own take-over. The literal list above never
      saw it: [2] only reads argv lists.
  [7] `docker` is no longer excused by NAME. Each `"docker"` argv literal and each `docker …` shell string must be PROVEN
      docker-only: lexically under `if NODE_KIND == "docker"` / `if TURN_DOCKER` (or the `else` of the `!=` test), or inside
      a function named below with the reason no native node reaches it. A new one anywhere else fails until someone proves it.

Hermetic. Run: python3 tests/nix_node_path_selftest.py            (0 = pass)
     --perturb     drops `iputils` from the parsed path and expects RED on [2] ("PERTURB OK", exit 0; exit 1 if nothing went red).
     --perturb-image  drops `iputils-ping` from the image's parsed package list and expects RED on [5] (same convention).
     --perturb-hostsh plants the old `host_sh("docker stop …")` into the take-over and expects RED on [7].
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
MODULE = os.environ.get("SWG_NODE_NIX") or os.path.join(ROOT, "nix", "modules", "node.nix")
PERTURB = "--perturb" in sys.argv
PERTURB_IMAGE = "--perturb-image" in sys.argv
PERTURB_HOSTSH = "--perturb-hostsh" in sys.argv
DOCKERFILE = os.environ.get("SWG_DOCKERFILE_NODE") or os.path.join(ROOT, "Dockerfile.node")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# command → the nixpkgs attribute that provides it. SYSTEMD_APPENDED: what NixOS adds to every unit's PATH on its own.
PROVIDES = {
    "ping": "iputils", "ip": "iproute2", "ss": "iproute2", "tc": "iproute2", "nft": "nftables",
    "iptables": "iptables", "iptables-save": "iptables", "iptables-restore": "iptables", "ipset": "ipset",
    "wg": "wireguard-tools", "awg": "amneziawg-tools", "curl": "curl", "dnsmasq": "dnsmasq", "conntrack": "conntrack-tools",
    "pgrep": "procps", "pkill": "procps", "kill": "procps", "sysctl": "procps", "ps": "procps",
    "sh": "bash", "bash": "bash", "id": "coreutils", "modprobe": "kmod", "tar": "gnutar", "openssl": "openssl",
    "systemctl": "systemd", "systemd-run": "systemd",
    "cat": "coreutils", "base64": "coreutils", "chmod": "coreutils", "mkdir": "coreutils", "sleep": "coreutils", "grep": "gnugrep",
    "rm": "coreutils", "tail": "coreutils", "journalctl": "systemd",
}
SYSTEMD_APPENDED = {"coreutils", "findutils", "gnugrep", "gnused", "systemd"}
# Named, not assumed: commands the native unit does not carry, each with the reason it is outside this gate. `docker` is NOT
# here any more — [7] proves every use of it docker-only instead of excusing the name.
EXCLUDED = {}
# Functions no native node reaches, each with the reason. [7] accepts a `docker` literal inside one of these.
DOCKER_ONLY_FUNCS = {
    "_relay_docker_running": "called only by _relay_supervise_docker",
    "_relay_supervise_docker": "called only from _relay_supervise's `if NODE_KIND == \"docker\"` branch",
    "_dturn_run": "turn proxies as sibling containers — every caller is under TURN_DOCKER (= NODE_KIND == \"docker\")",
    "_dturn_netns_current": "turn-on-docker only (see _dturn_run)",
    "_dturn_image_current": "turn-on-docker only (see _dturn_run)",
    "_dturn_verify": "turn-on-docker only (see _dturn_run)",
    "_dturn_delete": "turn-on-docker only (see _dturn_run)",
    "_dturn_attach_running": "called only under `if TURN_DOCKER`",
    "_dturn_ensure": "called only by _dturn_reconcile, which returns first when not TURN_DOCKER",
}
SHELL_BUILTINS = {"cd", "exit", "printf", "kill", "echo", "test", "true", "false", "read", "export", "set", "trap", "wait", "command"}

src_mod = open(MODULE).read()
m = re.search(r"path\s*=\s*with\s+pkgs;\s*\[(.*?)\];", src_mod, re.S)
check("[1] node.nix has a `path = with pkgs; [ … ];` list", bool(m))
pkgs = set()
if m:
    body = "\n".join(line.split("#", 1)[0] for line in m.group(1).splitlines())
    pkgs = set(re.findall(r"[A-Za-z][A-Za-z0-9_.\-]*", body))
if PERTURB:
    pkgs.discard("iputils")
check("[1] …and it names the packages this gate relies on", {"python3", "nftables", "iproute2", "procps", "bash"} <= pkgs, sorted(pkgs))

src = open(NODED).read()
if PERTURB_HOSTSH:
    _anchor = '        r = run([cli, "stop", cid], timeout=60)'
    if src.count(_anchor) != 1:
        print("PERTURB FAILED — the take-over's resolved-CLI stop is not in swg-noded exactly once; nothing to plant over")
        sys.exit(1)
    src = src.replace(_anchor, '        r = host_sh("docker stop " + shlex.quote(cid) + " >/dev/null 2>&1; :", timeout=60)')
cmds = set(re.findall(r'\b(?:run|_run|Popen|check_output|call)\(\s*\[\s*"([a-z][a-z0-9._\-]*)"', src))
check("[4] the fixture: the mesh probe's `ping` is among the daemon's commands", "ping" in cmds, sorted(cmds))
check("[4] …the parse found a realistic set (nft, ip, iptables, wg)", {"nft", "ip", "iptables", "wg"} <= cmds, sorted(cmds))

for c in sorted(cmds):
    if c == "docker":
        continue                                   # proven docker-only site by site in [7], never excused by name
    if c in EXCLUDED:
        print("  SKIP %-14s %s" % (c, EXCLUDED[c]))
        continue
    pkg = PROVIDES.get(c)
    if pkg is None:
        check("[3] `%s` is mapped to a package — a command this gate has never seen" % c, False, "add it to PROVIDES and to node.nix `path`")
        continue
    check("[2] `%s` → %s is on the native unit's PATH" % (c, pkg), pkg in pkgs or pkg in SYSTEMD_APPENDED, sorted(pkgs))

# [5] the container image. Debian names; what the python slim base already carries; what the build copies or installs by hand.
DEB = {"ping": "iputils-ping", "ip": "iproute2", "ss": "iproute2", "tc": "iproute2", "nft": "nftables", "iptables": "iptables",
       "iptables-save": "iptables", "iptables-restore": "iptables", "ipset": "ipset", "wg": "wireguard-tools", "curl": "curl",
       "dnsmasq": "dnsmasq", "pgrep": "procps", "pkill": "procps", "kill": "procps", "sysctl": "procps", "ps": "procps",
       "conntrack": "conntrack"}
SLIM_BASE = {"sh", "bash", "id", "tar"}              # dash, bash, coreutils, tar: essential in every Debian slim image
IMAGE_EXCLUDED = {
    "systemctl": "no systemd in a container — `run` returns 127 by design there; not measured per call by this gate",
    "systemd-run": "no systemd in a container — `run` returns 127 by design there; not measured per call by this gate",
}
df = open(DOCKERFILE).read()
final = df[df.rindex("\nFROM "):]                   # the runtime stage only — the build stage's packages never ship
apt = re.search(r"apt-get install -y --no-install-recommends\s*\\?\s*(.*?)(?:&&|$)", final, re.S)
debs = set(re.findall(r"[a-z0-9][a-z0-9.+\-]*", apt.group(1))) if apt else set()
if PERTURB_IMAGE:
    debs.discard("iputils-ping")
copied = set(re.findall(r"/usr/bin/([a-z0-9._\-]+)", final))
check("[5] the image's runtime stage installs packages and copies binaries (parse found them)",
      {"iproute2", "nftables", "iptables"} <= debs and {"awg", "docker"} <= copied, (sorted(debs), sorted(copied)))
for c in sorted(cmds):
    if c in IMAGE_EXCLUDED:
        print("  SKIP %-14s image: %s" % (c, IMAGE_EXCLUDED[c]))
        continue
    if c in copied or c in SLIM_BASE:
        check("[5] `%s` is in the image (copied in / slim base)" % c, True)
        continue
    pkg = DEB.get(c)
    if pkg is None:
        check("[5] `%s` is mapped to a Debian package — a command this gate has never seen" % c, False, "add it to DEB and to Dockerfile.node")
        continue
    check("[5] `%s` → %s is installed in the image" % (c, pkg), pkg in debs, sorted(debs))

# [6] + [7] — shell strings, and the proof behind every `docker`. Read from the AST, so only real calls count (a docstring that
# QUOTES host_sh("docker stop …") is not a call) and an early `if NODE_KIND != "docker": return` is seen as the guard it is.
import ast
TREE = ast.parse(src)
PARENT = {}
for _n in ast.walk(TREE):
    for _c in ast.iter_child_nodes(_n):
        PARENT[_c] = _n
def _seg(n):
    return ast.get_source_segment(src, n) or ""
DOCKER_TRUE = re.compile(r'^(NODE_KIND\s*==\s*"docker"|TURN_DOCKER)$')
DOCKER_FALSE = re.compile(r'^(NODE_KIND\s*!=\s*"docker"|not\s+TURN_DOCKER)$')
def _returns_early(ifn):
    return bool(ifn.body) and isinstance(ifn.body[-1], ast.Return) and not ifn.orelse
def docker_guarded(node):
    """(proven, how) — lexically in a docker-only branch, after a docker-only early return, or in a named function."""
    cur = node
    while cur in PARENT:
        par = PARENT[cur]
        if isinstance(par, ast.If):
            t = _seg(par.test).strip()
            if cur in par.body and DOCKER_TRUE.match(t):
                return True, "under `if %s`" % t
            if cur in par.orelse and DOCKER_FALSE.match(t):
                return True, "in the else of `if %s`" % t
        if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top = next((st for st in par.body if cur is st or any(cur is x for x in ast.walk(st))), None)
            for st in par.body:
                if st is top:
                    break
                if isinstance(st, ast.If) and DOCKER_FALSE.match(_seg(st.test).strip()) and _returns_early(st):
                    return True, "after `if %s: return`" % _seg(st.test).strip()
            if par.name in DOCKER_ONLY_FUNCS:
                return True, DOCKER_ONLY_FUNCS[par.name]
            return False, "no docker-only guard in %s" % par.name
        cur = par
    return False, "module level"
def fn_of(node):
    cur = node
    while cur in PARENT:
        cur = PARENT[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
    return "<module>"
def static_text(n):
    """The literal text of a shell-string expression; a computed piece becomes a neutral word."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else " X " for v in n.values)
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Mod)):
        return static_text(n.left) + (" X " if isinstance(n.op, ast.Mod) else static_text(n.right))
    return " X "
def shell_cmds(s):
    out = []
    s = re.sub(r"'[^']*'|\"[^\"]*\"", " X ", s)       # a quoted argument (a grep pattern with |, a message) is not a pipeline
    for seg in re.split(r"\|\||&&|;|\||\$\(|\(|\bthen\b|\bdo\b|\belse\b|\n", s):
        w = seg.strip().split()
        if not w:
            continue
        c = w[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", c) or c in ("fi", "done", "esac", "if", "while", "for", "until", "!", "{", "}", ":", "[", "]", ")", "'", "X"):
            continue
        if re.match(r"^[a-z][a-z0-9._\-]*$", c):
            out.append(c)
    return out
hostsh, docker_sites = [], []
for n in ast.walk(TREE):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "host_sh" and n.args:
        _dock_only = docker_guarded(n)[0]            # runs only on a docker node, in the HOST's namespace — not this PATH's concern
        for c in shell_cmds(static_text(n.args[0])):
            if c == "docker":
                docker_sites.append((n, "shell"))
            elif not _dock_only:
                hostsh.append((c, n))
    if isinstance(n, ast.List) and n.elts and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == "docker":
        docker_sites.append((n, "argv"))
check("[6] the host_sh shell strings parsed (systemctl, ip, cat among them)", {"systemctl", "ip", "cat"} <= {c for c, _ in hostsh}, sorted({c for c, _ in hostsh}))
for c, n in sorted(hostsh, key=lambda x: (x[0], x[1].lineno)):
    if c in SHELL_BUILTINS:
        continue
    pkg = PROVIDES.get(c)
    if pkg is None:
        check("[6] host_sh `%s` (line %d, %s) is mapped to a package — a command this gate has never seen" % (c, n.lineno, fn_of(n)), False, "add it to PROVIDES and to node.nix `path`")
        continue
    check("[6] host_sh `%s` → %s is on the native unit's PATH (line %d, %s)" % (c, pkg, n.lineno, fn_of(n)), pkg in pkgs or pkg in SYSTEMD_APPENDED, sorted(pkgs))
check("[7] the docker call sites were found (the relay and turn-on-docker sibling containers among them)", len(docker_sites) >= 8, len(docker_sites))
for n, how in sorted(docker_sites, key=lambda x: x[0].lineno):
    proven, why = docker_guarded(n)
    check("[7] `docker` (%s) at line %d in %s is docker-only — %s" % (how, n.lineno, fn_of(n), why), proven,
          "a native node can reach it: prove it (a guard, or DOCKER_ONLY_FUNCS with the reason) or resolve the CLI")
check("[7] the foreign take-over resolves its container CLI (no bare `docker` for a native node)",
      "def _ctr_stop_foreign" in src and 'r = run([cli, "stop", cid], timeout=60)' in src)

print()
if PERTURB or PERTURB_IMAGE or PERTURB_HOSTSH:
    ok = bool(FAILS)
    what = "the take-over's bare `docker stop` was planted back" if PERTURB_HOSTSH else "ping's package was removed"
    print(("PERTURB OK — %d check(s) went red: %s" % (len(FAILS), what)) if ok
          else "PERTURB FAILED — %s and every check still passed" % what)
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
