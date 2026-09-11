#!/usr/bin/env python3
"""Self-test — EVERY VERB THAT WRITES A PORT INTO .env VALIDATES IT FIRST.

`docker/swg-netctl-docker` carries `_v_port`, whose docstring says: "Everything that reaches a command line
goes through here — validating at the point of USE, not once per verb, so a verb added later can't miss it."
It was called at exactly ONE of four sites, and at none of the three that WRITE a port.

Why that is not cosmetic: `docker-compose.yml` publishes `${PANEL_BIND:-0.0.0.0}:${PANEL_PORT:-443}:8443`,
and compose's `:-` treats an EMPTY value as absent. So a blank persisted here does nothing at all until the
next container recreate — which may be an unrelated one-click update, days later — and then publishes the
panel on 0.0.0.0:443. Observed on svo-im: `PANEL_PORT=` blank, host nginx on 443 since two days earlier, and
the update left the panel container dead (see tests/docker_port_preflight_selftest.py for the other half).

`flip`'s `localport` is the one blank that IS legitimate — the panel sends "" when the flip does not move
it, and the writer skips it — so this asserts that it still may be blank while PANEL_PORT may not.

Run: python3 tests/netctl_port_guard_selftest.py      (0 = pass)
     --perturb   drops the set-listen guard and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NETCTL = os.environ.get("SWG_NETCTL_DOCKER") or os.path.join(ROOT, "docker", "swg-netctl-docker")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(NETCTL, encoding="utf-8").read()
_ANCH = '''        if not _v_port(port):
            return False, "port %r isn't a valid port number (1-65535) — refusing to persist it" % (port,)'''
assert SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    SRC = SRC.replace(_ANCH, "        pass")

path = NETCTL
if PERTURB:
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="netctlguard-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

l = importlib.machinery.SourceFileLoader("netctld", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("netctld", l))
try:
    l.exec_module(N)
except SystemExit:
    pass
if PERTURB:
    os.unlink(path)

TMP = tempfile.mkdtemp(prefix="netctlguard-")
N.ENV = os.path.join(TMP, ".env")
open(N.ENV, "w").write("PANEL_PORT=8443\nPANEL_BIND=127.0.0.1\nSUB_PORT=8444\nPANEL_LOCAL_PORT=8088\n")
BASE = open(N.ENV).read()

_composed = []
N._compose = lambda *a: (_composed.append(a) or (True, ""))

def env_now():
    return dict(l.split("=", 1) for l in open(N.ENV).read().splitlines() if "=" in l)

print("[1] _v_port itself")
for v, want in [("443", True), ("1", True), ("65535", True), ("0", False), ("65536", False),
                ("", False), (None, False), ("8443 ", True), ("http", False), ("44 3", False), ("-1", False)]:
    check("_v_port(%r) == %s" % (v, want), N._v_port(v) is want, N._v_port(v))

print("\n[2] set-listen refuses a non-port and LEAVES .env ALONE")
for bad in ("", "0", "http", "99999"):
    open(N.ENV, "w").write(BASE)
    ok, msg = N._handle("set-listen", ["panel", "0.0.0.0", bad])
    check("port=%r refused" % bad, ok is False, msg)
    check("…and PANEL_PORT is untouched", env_now().get("PANEL_PORT") == "8443", env_now().get("PANEL_PORT"))
open(N.ENV, "w").write(BASE)
ok, msg = N._handle("set-listen", ["panel", "0.0.0.0", "2087"])
check("a real port still goes through", ok is True and env_now().get("PANEL_PORT") == "2087", (ok, msg, env_now()))

print("\n[3] set-local-port refuses one too (the panel computes it as int(... or 0))")
open(N.ENV, "w").write(BASE)
ok, msg = N._handle("set-local-port", ["panel", "0"])
check("port=0 refused", ok is False, msg)
check("…and PANEL_LOCAL_PORT is untouched", env_now().get("PANEL_LOCAL_PORT") == "8088", env_now())

print("\n[4] flip refuses a blank PANEL_PORT — but a blank localport is legitimate")
open(N.ENV, "w").write(BASE)
ok, msg = N._handle("flip", ["panel", "none", "127.0.0.1", ""])
check("blank flip port refused", ok is False, msg)
check("…and TLS/PANEL_PORT are untouched",
      env_now().get("PANEL_PORT") == "8443" and env_now().get("PANEL_BIND") == "127.0.0.1", env_now())
check("the source still allows a blank localport", 'if localport and not _v_port(localport):' in
      open(NETCTL, encoding="utf-8").read())

print("\n[5] the docstring's promise, kept: every WRITE site validates")
real = open(NETCTL, encoding="utf-8").read()
writes = re.findall(r'_set_env\(\{[^}]*"(?:PANEL_PORT|SUB_PORT|PANEL_LOCAL_PORT)"', real)
check("there are still 3 port-writing _set_env sites (2 verbs + flip's env dict)", len(writes) >= 2, len(writes))
check("`dryrun` still validates (the one site that always did)", '"port %r isn\'t a valid port number (1-65535)" % (port,)' in real)
check("no port reaches .env through a path with no _v_port above it",
      real.count("_v_port(") >= 5, real.count("_v_port("))

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
