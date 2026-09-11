#!/usr/bin/env python3
"""Self-test — A DOCKER UPDATE MUST NOT DESTROY A WORKING STACK IT CANNOT REBUILD.

`update.sh`'s prebuilt-image branch removes swg-panel/swg-node with `docker rm -f` BEFORE `compose up`, so
that `up` cannot hit "container name already in use". That makes a port conflict total: the old container is
gone, the new one cannot bind, and the box is left with a container in `Created` that never starts.

MEASURED on svo-im 2026-09-10 07:49. `PANEL_PORT=` (blank) resolves through compose's `${PANEL_PORT:-443}`
to 0.0.0.0:443 — a value latent since the container was last created — and the host's own nginx had held
that port since 2026-09-08 00:02. The one-click update took the panel down: `failed to bind host port
0.0.0.0:443/tcp: address already in use`.

The rule was not new. `docker/swg-netctl-docker`'s `dryrun` verb already refuses an address change whose
target port is taken ("a recreate can't publish a port another service already holds"). It was enforced in
one of the two places that recreate containers. This is the other one, using the same `ss` probe.

⚠️ THREE OUTCOMES, NOT TWO, and this file exists mostly for the third. The checker was first written as
`python3 -c '…'`, and the shell quoting mangled its one regex into a SyntaxError: it exited non-zero with an
empty stdout — indistinguishable from "could not determine" — and the caller passed the host straight
through, on the very box where the conflict was sitting in plain sight. So: 0 = clear, 3 = conflict,
4 = could not determine, and anything else is reported rather than assumed benign.

Run: python3 tests/docker_port_preflight_selftest.py      (0 = pass)
     --perturb   collapses "could not determine" into "clear" and expects RED.
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
UPDATE = os.environ.get("SWG_UPDATE_SH") or os.path.join(ROOT, "update.sh")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(UPDATE, encoding="utf-8").read()
m = re.search(r"<<'PYPORT'\n(.*?)\nPYPORT\n", SRC, re.S)
assert m, "anchor missing — the embedded checker is gone; this run would FALSE-PASS"
CHECKER = m.group(1)
if PERTURB:                                   # the shape that shipped: a crash looks exactly like "clear"
    CHECKER = CHECKER.replace("    sys.exit(4)", "    sys.exit(0)")

print("[1] the embedded checker is valid Python — a SyntaxError here is INVISIBLE at runtime")
try:
    compile(CHECKER, "PYPORT", "exec"); ok = True; why = ""
except SyntaxError as e:
    ok, why = False, str(e)
check("it compiles", ok, why)

TMP = tempfile.mkdtemp(prefix="pfgate-")
BIN = os.path.join(TMP, "bin"); os.makedirs(BIN)
CHK = os.path.join(TMP, "checker.py"); open(CHK, "w").write(CHECKER)

def fake_ss(busy_ports):
    """A stand-in `ss -lntpH 'sport = :N'`: prints a listener line only for the ports we say are taken."""
    open(os.path.join(BIN, "ss"), "w").write(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "port = sys.argv[-1].split(':')[-1].strip()\n"
        "busy = %r\n"
        "if port in busy:\n"
        "    print('LISTEN 0 511 0.0.0.0:%%s 0.0.0.0:* users:((\"%%s\",pid=1,fd=1))' %% (port, busy[port]))\n"
        % busy_ports)
    os.chmod(os.path.join(BIN, "ss"), 0o755)

def run(cfg, busy, ours="", with_ss=True):
    if with_ss:
        fake_ss(busy)
    f = os.path.join(TMP, "cfg.json"); open(f, "w").write(json.dumps(cfg))
    # With no stub, PATH must hold NO `ss` at all — inheriting the caller's found the real one and reported a
    # listener on this machine's own port 8088, which is a true answer to a question the test was not asking.
    path = (BIN + os.pathsep + os.environ["PATH"]) if with_ss else BIN
    env = dict(os.environ, PATH=path, OURS=ours)
    r = subprocess.run([sys.executable, CHK, f], capture_output=True, env=env)
    return r.returncode, (r.stdout or b"").decode().strip()

CFG = {"services": {
    "swg-panel": {"ports": [{"host_ip": "0.0.0.0", "published": "443", "target": 8443},
                            {"host_ip": "127.0.0.1", "published": "8088", "target": 8088}]},
    "swg-sub":   {"ports": [{"host_ip": "0.0.0.0", "published": "8444", "target": 8444}]},
    "swg-node":  {}}}

print("\n[2] a foreign holder is a CONFLICT — and the message names it")
rc, out = run(CFG, {"443": "nginx"})
check("exit 3 = refuse", rc == 3, (rc, out))
check("it names the service, the address and the holder",
      out.split("\t") == ["swg-panel", "0.0.0.0:443", "nginx"], out)
check("a free port is NOT flagged (8444 and 8088 are quiet)", out.count("\n") == 0, out)

print("\n[3] every port free → clear")
rc, out = run(CFG, {})
check("exit 0", rc == 0, (rc, out))
check("nothing reported", out == "", out)

print("\n[4] a port OUR OWN container publishes is not a conflict — the recreate frees it")
rc, out = run(CFG, {"443": "docker-proxy"}, ours="0.0.0.0:443->8443/tcp, 0.0.0.0:8444->8444/tcp")
check("exit 0", rc == 0, (rc, out))

print("\n[5] ⚠️ COULD NOT DETERMINE IS NOT CLEAR — the bug this file is really about")
rc, out = run("not json at all", {"443": "nginx"})
check("unreadable config → exit 4, never 0", rc == 4, (rc, out))
if os.path.exists(os.path.join(BIN, "ss")):   # no `ss` on the box at all — and do NOT let the stub come back
    os.remove(os.path.join(BIN, "ss"))
rc, out = run(CFG, {}, with_ss=False)
check("no `ss` to probe with → exit 4, never 0", rc == 4, (rc, out))

print("\n[6] the caller: PRE-flight, and it maps the three outcomes apart")
i_fn = SRC.index("docker_ports_preflight(){")
check("0 returns clear", "0) rm -f \"$_pf\"; return 0 ;;" in SRC[i_fn:])
check("3 falls through to the refusal", "\n    3) ;;\n" in SRC[i_fn:])
check("anything else is REPORTED, not assumed benign",
      "port pre-flight could not run (exit $rc) — proceeding unchecked" in SRC)
# Each guard must be an `elif` that short-circuits BEFORE the `else` branch which does the work — so for
# every call site, the acting command has to come AFTER it. Walk the sites rather than guessing offsets.
_calls = [m.start() for m in re.finditer(r'elif ! docker_ports_preflight "\$prof"', SRC)]
check("both recreate paths are guarded", len(_calls) == 2, len(_calls))
for _i, (label, anchor) in zip(_calls, (("build", "up -d --build"), ("pull+recreate", "docker rm -f"))):
    _act = SRC.find(anchor, _i)
    check("the %s path pre-flights BEFORE it acts" % label, _act > _i, (_i, _act))
check("neither guard is an `if` that could be skipped by an earlier branch",
      all(SRC[i:i + 4] == "elif" for i in _calls))
check("the destructive rm is inside the guarded branch, after the pre-flight",
      SRC.index('elif ! docker_ports_preflight "$prof"; then DID_FAIL=yes; note "docker ($prof): REFUSED')
      < SRC.index("EVERYTHING BELOW THIS LINE IS DESTRUCTIVE"))

print("\n[7] TWO ENFORCERS, ONE RULE — netctl's dryrun already refused this; they must probe alike")
net = open(os.path.join(ROOT, "docker", "swg-netctl-docker"), encoding="utf-8").read()
check("netctl still probes with ss on the target port", '"sport = :%s" % port' in net)
check("…and the update path probes the same way", '"sport = :" + pub' in CHECKER)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
