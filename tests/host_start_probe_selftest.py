#!/usr/bin/env python3
"""Self-test — the install's "did the panel come up?" check asks a door the unit ACTUALLY serves.

install-host.sh probed `http://127.0.0.1:${LOCAL_PORT}/` on every install. That listener is the co-located node's
plain-HTTP loopback and exists only when the unit carries SWG_PANEL_LOCAL_PORT — a MASTER. A HOST-role panel has none,
so every bare-metal host install ended "! the panel did NOT start … port :2087 is already held by python3 … Give the
panel a free port" and "! Host install finished, but the panel is NOT running" — over a panel serving on :2087 with
/healthz 200 (1.8.8 qualification, q5). The "held by" line blamed the panel's own process for holding its own port.

The probe block and its two helpers are lifted out of install-host.sh AS SHIPPED and run against stubs: `curl`
answers only the URL the case's panel serves, `ss` names who holds the port, and /proc/<pid>/cgroup is a temp file.

Run: python3 tests/host_start_probe_selftest.py          (0 = pass)
     --perturb         the probe aimed back at the loopback on every role (the shipped behaviour) → RED
     --perturb-blame   the own-panel check taken out of the diagnosis → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_BLAME = "--perturb-blame" in sys.argv
src = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def fn(name):
    m = re.search(r"^%s\(\)\{.*?; \}\n" % re.escape(name), src, re.S | re.M)
    assert m, "cannot extract " + name + " — this run would FALSE-PASS"
    return m.group(0)

i = src.index('if [ "${SWG_DEFER_START:-}" != 1 ] && ! $DRYRUN; then\n')
j = src.index('if [ -f "$PREFIX$SUB_DIR/swg-sub" ]; then write_sub_unit', i)
block = src[i:j]
helpers = fn("panel_owns_port") + fn("panel_probe_url")
if PERTURB:
    a = "  if [ \"$_HAS_LOCAL_NODE\" = yes ]; then printf 'http://127.0.0.1:%s/' \"$LOCAL_PORT\"; return 0; fi\n"
    assert helpers.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    helpers = helpers.replace(a, "  printf 'http://127.0.0.1:%s/' \"$LOCAL_PORT\"; return 0\n")
if PERTURB_BLAME:
    a = '    if panel_owns_port "$_bp"; then\n'
    assert block.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    block = block.replace(a, '    if false; then\n')

def run(role, serve, cert, serving_url, holder=None, own=False, base=""):
    """role: master|host · serving_url: the one URL curl answers · holder: (comm, pid) that `ss` reports on :PORT."""
    d = tempfile.mkdtemp(prefix="probe-"); log = os.path.join(d, "curl.log")
    proc = os.path.join(d, "proc")
    def stub(name, body):
        p = os.path.join(d, name); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    stub("curl", 'u="${@: -1}"; echo "$u" >> %s; [ "$u" = "$OK_URL" ]' % log)
    hold = ""
    if holder:
        comm, pid = holder
        hold = 'LISTEN 0 5 0.0.0.0:2087 0.0.0.0:* users:(("%s",pid=%d,fd=3))' % (comm, pid)
        os.makedirs(os.path.join(proc, str(pid)))
        open(os.path.join(proc, str(pid), "cgroup"), "w").write(
            "0::/system.slice/%s.service\n" % ("swg-panel-server" if own else "nginx"))
    stub("ss", "echo '%s'" % hold if hold else "exit 0")
    stub("sleep", "exit 0")
    h = helpers.replace('"/proc/$pid/cgroup"', '"%s/$pid/cgroup"' % proc)
    script = ("set -euo pipefail\nDRYRUN=false\nRESET=''; C_YEL=''\nhave(){ command -v \"$1\" >/dev/null 2>&1; }\n"
              "col(){ local _c=\"$1\"; shift; printf '%%s' \"$*\"; }\nwarn(){ echo \"WARN $*\"; }\n"
              "_HAS_LOCAL_NODE=%s; LOCAL_PORT=8088; PORT=2087; URL_PORT=''; SERVE_MODE=%s; PANEL_BASE='%s'\n"
              "PANEL_DOMAIN=192.168.77.5; CERT_FULLCHAIN='%s'; CERT_KEY='%s'\n%s\n%s\necho \"PANEL_UP=${PANEL_UP:-yes}\"\n") % (
        "yes" if role == "master" else "no", serve, base, cert, cert, h, block)
    env = dict(os.environ, PATH=d + ":" + os.environ["PATH"], OK_URL=serving_url)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    urls = open(log).read().split() if os.path.exists(log) else []
    return p.stdout + p.stderr, urls

print("[1] a HOST-role panel (no co-located node) is probed where it serves — the shipped false failure")
out, urls = run("host", "internal", "/etc/swg-panel/tls/fullchain.pem", "https://127.0.0.1:2087/healthz")
check("internal + its own TLS → https://127.0.0.1:2087/healthz, and the install calls it running",
      "PANEL_UP=yes" in out and "did NOT start" not in out and urls[:1] == ["https://127.0.0.1:2087/healthz"], (out, urls))
out, urls = run("host", "internal", "", "http://127.0.0.1:2087/healthz")
check("internal, TLS skipped → plain http on the same port", "PANEL_UP=yes" in out and "did NOT start" not in out, (out, urls))
out, urls = run("host", "nginx", "", "http://127.0.0.1:2087/swg/healthz", base="/swg")
check("behind nginx with a base path → http://127.0.0.1:<loopback port>/swg/healthz", "PANEL_UP=yes" in out
      and "did NOT start" not in out, (out, urls))

print("\n[2] a MASTER keeps asking the co-located node's loopback, exactly as before")
out, urls = run("master", "internal", "/etc/swg-panel/tls/fullchain.pem", "http://127.0.0.1:8088/")
check("master → http://127.0.0.1:8088/ and it is running", "PANEL_UP=yes" in out and urls[:1] == ["http://127.0.0.1:8088/"], (out, urls))

print("\n[3] the diagnosis never blames our own panel for holding its own port")
out, urls = run("host", "internal", "/x", "https://nothing/", holder=("python3", 4242), own=True)
check("the port is held by swg-panel-server's own process → NOT 'did NOT start', NOT 'held by'",
      "PANEL_UP=yes" in out and "did NOT start" not in out and "held by" not in out and "is running" in out, out)
out, urls = run("host", "internal", "/x", "https://nothing/", holder=("nginx", 777))
check("held by somebody else (nginx) → did NOT start, names nginx, suggests a free port",
      "PANEL_UP=no" in out and "did NOT start" in out and "held by nginx" in out and ":8443" in out, out)
out, urls = run("host", "nginx", "", "http://nothing/", holder=("caddy", 778))
check("proxy mode, loopback port held → advice is a free loopback PORT, not a new public URL",
      "PANEL_UP=no" in out and "PORT=<free port>" in out and "PANEL_DOMAIN=" not in out, out)
out, urls = run("host", "internal", "/x", "https://nothing/")
check("nothing holds it and nothing answers → did NOT start, no 'held by' line", "PANEL_UP=no" in out
      and "held by" not in out, out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but a perturbation was planted and should have gone RED" if (PERTURB or PERTURB_BLAME) else ""))
sys.exit(2 if (PERTURB or PERTURB_BLAME) else 0)
