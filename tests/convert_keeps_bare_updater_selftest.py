#!/usr/bin/env python3
"""Self-test: a docker → bare-metal convert leaves the box with a WORKING one-click updater.

Measured in the 1.8.8-beta VM upgrade re-run (docker master → bare): after the convert there was no
/usr/local/bin/swg-update, no swg-update-check and no swg-update.timer, so the panel's Update button wrote a trigger
nothing read and the header sat on "updating". The docker updater and a bare-metal PANEL's updater are the SAME five
paths (swg-update, swg-update-check, swg-update.service, swg-update.timer, the stamp) — one updater per box, by design
— and convert.sh called retire_docker_updater AFTER install-host.sh had written the bare panel's: it removed the new
updater, not the old one. The node-only branch had the mirror case: it retired the updater unconditionally, although
on a box that keeps a panel (a docker panel staying put in a co-located split, or a bare-metal panel beside the node)
those files are that panel's updater.

  [1] panel branch (host + master): retire_docker_updater runs BEFORE install-host.sh, and nowhere after it
  [2] …consequence: replaying the branch's own order of those two steps against a temp root leaves the bare updater
  [3] node branch: the updater is retired only when no panel remains — kept beside a bare panel or a docker panel

retire_docker_updater is run as shipped with its system paths pointed into a temp root; `systemctl` is a stub.

Run: python3 tests/convert_keeps_bare_updater_selftest.py      (0 = pass)
     --perturb   re-plants the shipped order (retire after install-host) and the unconditional node retire → RED
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
if PERTURB:
    m = re.search(r"\n  # ⚠️ RETIRE THE DOCKER UPDATER BEFORE install-host.*?\n  retire_docker_updater\n", src, re.S)
    assert m, "perturbation anchor missing (early retire) — this run would FALSE-PASS"
    src = src[:m.start()] + "\n" + src[m.end():]
    a = "  # (the docker updater was retired BEFORE install-host — the files it would remove here are the bare panel's now)\n"
    assert src.count(a) == 1, "perturbation anchor missing (late retire) — this run would FALSE-PASS"
    src = src.replace(a, "  retire_docker_updater   # the docker-only one-click updater has no meaning on a bare box — see above\n")
    m = re.search(r"  if ! bare_panel_present && ! docker ps --format '\{\{\.Names\}\}' 2>/dev/null \| grep -qx swg-panel; then\n    retire_docker_updater\n  fi\n", src)
    assert m, "perturbation anchor missing (node guard) — this run would FALSE-PASS"
    src = src[:m.start()] + "  retire_docker_updater\n" + src[m.end():]

panel = re.search(r"# ── PANEL host/master: docker → bare-metal ──.*?\n(if .*?\nfi)\n", src, re.S)
node = re.search(r"# ── NODE: docker → bare-metal ──\n(if .*?\nfi)\n", src, re.S)
fn = re.search(r"^retire_docker_updater\(\)\{\n.*?\n\}\n", src, re.S | re.M)
assert panel and node and fn, "convert.sh blocks missing — this run would FALSE-PASS"
PANEL, NODE, FN = panel.group(1), node.group(1), fn.group(0)

print("[1] the panel branch retires the docker updater BEFORE install-host.sh")
i_host = PANEL.find('bash "$SRC/install-host.sh"')
calls = [m.start() for m in re.finditer(r"^\s*retire_docker_updater\b", PANEL, re.M)]
check("install-host.sh is invoked in the branch", i_host > 0)
check("⚠️ a retire happens before it", any(c < i_host for c in calls), calls)
check("⚠️ …and none after it (it would remove the bare panel's own updater)", not any(c > i_host for c in calls), calls)

# a temp root for the real function
T = tempfile.mkdtemp(prefix="updretire-")
BIN, SD, LIB, STUB = (os.path.join(T, d) for d in ("bin", "sd", "lib", "stub"))
for d in (BIN, SD, LIB, STUB):
    os.makedirs(d)
FNT = FN.replace("/etc/systemd/system", SD).replace("/usr/local/bin", BIN).replace("/var/lib", LIB)
assert "/etc/systemd" not in FNT and "/usr/local/bin" not in FNT
open(os.path.join(STUB, "systemctl"), "w").write("#!/bin/sh\nexit 0\n"); os.chmod(os.path.join(STUB, "systemctl"), 0o755)
FILES = [os.path.join(BIN, "swg-update"), os.path.join(BIN, "swg-update-check"),
         os.path.join(SD, "swg-update.service"), os.path.join(SD, "swg-update.timer")]


def put(tag):
    for f in FILES:
        open(f, "w").write(tag + "\n")


def retire():
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n%s\nretire_docker_updater\n" % FNT],
                       env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


print("\n[2] replaying the branch's own order leaves the bare panel an updater")
put("docker-updater")
for pos, step in sorted([(c, "retire") for c in calls] + [(i_host, "install-host")]):
    if step == "retire":
        retire()
    else:
        put("bare-updater")                                  # what install-host.sh's mk_update_unit writes
check("⚠️ every updater file exists after the convert", all(os.path.exists(f) for f in FILES), [f for f in FILES if not os.path.exists(f)])
check("…and it is the bare panel's", all(os.path.exists(f) and open(f).read() == "bare-updater\n" for f in FILES))

print("\n[3] the node branch retires it only when no panel is left here")
guard = re.search(r"\n(  if ! bare_panel_present .*?\n    retire_docker_updater\n  fi\n)", NODE, re.S)


def node_retire(bare_panel, docker_panel):
    put("updater")
    snippet = guard.group(1) if guard else "  retire_docker_updater\n"
    if not guard:                                            # the shipped shape: an unconditional call
        m = re.search(r"^\s*retire_docker_updater\b.*$", NODE, re.M)
        snippet = m.group(0) + "\n" if m else ""
    script = ("set -euo pipefail\n%s\nbare_panel_present(){ return %d; }\n"
              "docker(){ [ \"$1\" = ps ] && { %s }; return 0; }\n%s") % (
        FNT, 0 if bare_panel else 1, "echo swg-panel;" if docker_panel else ":;", snippet)
    r = subprocess.run(["bash", "-c", script], env=dict(os.environ, PATH=STUB + os.pathsep + os.environ["PATH"]),
                       capture_output=True, text=True)
    return r.returncode, all(os.path.exists(f) for f in FILES)


rc, kept = node_retire(False, False)
check("no panel left: the docker updater is retired", rc == 0 and not kept, (rc, kept))
rc, kept = node_retire(True, False)
check("⚠️ a bare-metal panel beside the node keeps its updater", rc == 0 and kept, (rc, kept))
rc, kept = node_retire(False, True)
check("⚠️ a docker panel staying put (co-located split) keeps its updater", rc == 0 and kept, (rc, kept))

shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
