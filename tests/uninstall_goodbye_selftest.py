#!/usr/bin/env python3
"""Self-test — a node's uninstall signs off to its panel exactly when there is a panel left to hear it, and never
from a dry run.

  [1] A bare-metal MASTER's full uninstall removes the panel first, then the node — whose goodbye then went to
      http://127.0.0.1:8088, a panel that no longer existed, and ended with "! Couldn't reach the panel; the node will
      just go offline there" (1.8.8 qualification, q1). Now skipped when the node's panel is THIS box's own and no
      panel of either method is left — the docker path's rule, shared.
  [2] …and still SENT for "uninstall the node, keep the panel" (that panel must show it Uninstalled), for a node of a
      remote panel, and for a docker node whose loopback panel is a BARE one (the docker path's old container-only
      test skipped that goodbye while the panel was alive).
  [3] `--dry-run` sent the goodbye for real: the panel flagged the node "uninstalled" and logged "Node uninstalled —
      kept for re-install" (measured, q1) — and for a node marked for removal a received sign-off completes it.

node_goodbye / docker_node_goodbye / _goodbye_post / _proc_post and their helpers are lifted out of uninstall.sh AS
SHIPPED; the POST itself is recorded by a stub (or, for the dry-run case, by a `python3` stub that must stay unused).

Run: python3 tests/uninstall_goodbye_selftest.py     (0 = pass)
     --perturb          the skip and the dry-run guard taken out → RED
     --perturb-docker   the docker path's old container-only "panel left?" test put back → RED
"""
import os, re, subprocess, sys, tempfile, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_DOCKER = "--perturb-docker" in sys.argv
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b):
    global U
    assert U.count(a) >= 1, "perturbation anchor missing — would FALSE-PASS: " + a[:80]
    U = U.replace(a, b)

if PERTURB:
    plant('  _goodbye_nobody "$url" && { _goodbye_skipped; return 0; }\n  _goodbye_post "$url" "$tok" "$verify"\n}',
          '  _goodbye_post "$url" "$tok" "$verify"\n}')                                           # [1] both paths
    plant('  if $DRYRUN; then echo "    [dry] sign off from the panel ($url)"; return 0; fi\n', '')  # [3]
if PERTURB_DOCKER:   # separate: with the skip gone (above) every case posts, and this one could not go red
    plant('_panel_left_here(){ [ -f "$SD/swg-panel-server.service" ] || docker_running swg-panel; }',
          '_panel_left_here(){ docker_running swg-panel; }')                                        # [2] old docker test

def fn(name):
    """`name(){ … }` as shipped: header to the first closing line at which the text parses (`bash -n`)."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), U, re.M)
    assert m, "cannot extract " + name
    lines = U[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

T = tempfile.mkdtemp(prefix="bye-")
CFG = os.path.join(T, "config.json")
FNS = "".join(fn(n) for n in ("_url_is_this_box", "_panel_left_here", "_goodbye_nobody", "_goodbye_skipped",
                              "node_goodbye", "docker_node_goodbye")).replace("/etc/swg-agent/config.json", CFG)

def case(kind, url, bare_unit=False, docker_panel=False, own_host="", own_ips="10.0.2.15 192.168.77.1"):
    d = tempfile.mkdtemp(prefix="bye-c-"); sd = os.path.join(d, "systemd"); os.makedirs(sd)
    if bare_unit:
        open(os.path.join(sd, "swg-panel-server.service"), "w").write("[Unit]\n")
    dd = os.path.join(d, "docker"); os.makedirs(dd)
    if kind == "bare":
        json.dump({"panel": {"url": url, "token": "tok", "verify": False}}, open(CFG, "w"))
    else:
        open(os.path.join(dd, ".env"), "w").write("PANEL_URL=%s\nNODE_TOKEN=tok\nTLS_VERIFY=no\n" % url)
    for n, body in (("ip", 'printf "%s\\n" ' + " ".join("'2: eth0    inet %s/24 brd x scope global eth0'" % a for a in own_ips.split())),
                    ("hostname", "echo %s" % own_ips)):
        p = os.path.join(d, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    script = ('set -uo pipefail\nDRYRUN=false; SD=%s; DOCKER_DIR=%s; _OWN_PANEL_HOST=%s\n'
              'info(){ echo "INFO $*"; }\ndocker_running(){ %s; }\n_goodbye_post(){ echo "POST $1"; }\n%s%s\n') % (
        sd, dd, own_host or '""', "return 0" if docker_panel else "return 1", FNS,
        "node_goodbye" if kind == "bare" else "docker_node_goodbye")
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    return p.stdout + p.stderr

print("[1] nobody left to tell → no sign-off, and no 'Couldn't reach the panel'")
out = case("bare", "http://127.0.0.1:8088")
check("bare MASTER, panel removed earlier in this run → skipped, said once", "POST" not in out and "No sign-off to send" in out, out)
out = case("bare", "https://127.0.0.1:2087/swg")
check("…an older master that dialled https://127.0.0.1:<public port><base> → skipped too", "POST" not in out, out)
out = case("bare", "https://192.168.77.1:2087")
check("…a node enrolled to this box's panel by one of the box's OWN addresses → skipped", "POST" not in out, out)
out = case("bare", "https://panel.example.com", own_host="panel.example.com")
check("…or by the panel's own domain (install.conf PANEL_DOMAIN, read before it is removed) → skipped", "POST" not in out, out)
out = case("docker", "http://127.0.0.1:8088")
check("docker MASTER, no panel of either method left → skipped (the docker path's case, same rule)", "POST" not in out, out)

print("\n[2] a panel is still there → the sign-off is sent")
out = case("bare", "http://127.0.0.1:8088", bare_unit=True)
check("'uninstall the node, KEEP the panel' → sent to it (it must show the node Uninstalled)", "POST http://127.0.0.1:8088" in out, out)
out = case("bare", "https://10.9.9.9:2087")
check("a node of a REMOTE panel → sent", "POST https://10.9.9.9:2087" in out, out)
out = case("bare", "http://127.0.0.1:8088", docker_panel=True)
check("a bare node beside a DOCKER panel still running → sent", "POST" in out, out)
out = case("docker", "http://127.0.0.1:8088", bare_unit=True)
check("a docker node beside a BARE panel still installed → sent (the old container-only test skipped it)", "POST" in out, out)

print("\n[3] --dry-run never sends a sign-off (or a status) to the panel")
d = tempfile.mkdtemp(prefix="bye-dry-"); log = os.path.join(d, "calls")
p = os.path.join(d, "python3"); open(p, "w").write('#!/bin/bash\necho "python3 $*" >> %s\nexit 0\n' % log); os.chmod(p, 0o755)
out = subprocess.run(["bash", "-c", 'DRYRUN=true\ninfo(){ echo "INFO $*"; }; ok(){ :; }; warn(){ :; }\n%s%s'
                      '_goodbye_post http://127.0.0.1:8088 tok no\n_proc_post http://127.0.0.1:8088 tok no uninstalling\n'
                      % (fn("_goodbye_post"), fn("_proc_post"))],
                     capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
calls = open(log).read() if os.path.exists(log) else ""
check("a dry run describes the sign-off ([dry] …) and posts NOTHING", "[dry] sign off" in out.stdout and calls == "", (out.stdout, calls))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if (PERTURB or PERTURB_DOCKER) else ""))
sys.exit(2 if (PERTURB or PERTURB_DOCKER) else 0)
