#!/usr/bin/env python3
"""Self-test — a bare → Docker convert deletes the bare WDTT units, as it deletes the csqtt ones (1.8.9 qualification,
FIXER-U's note).

The convert's switch (install-docker.sh, past the point of no return) only DISABLED the bare WDTT servers
(`systemctl disable --now` over list-unit-files) while stop_bare_csqtt deleted csqtt's units. The unit files left behind
are what a later uninstall lists as "WDTT (service + interface) swg-wdtt-<iface>", and removing that component runs
rm_wdtt — `ip link delete dev <iface>`, the UAPI socket, the SNAT rules by that name: the Docker node's LIVE WDTT, which
took the same interface names (host network).

  [1] install-docker.sh's REAL switch block, a node / master convert, over a sandbox unit dir: every bare
      swg-wdtt-*.service is stopped and its file deleted (one daemon-reload), csqtt's as before (and its raw TUN), nothing
      else touched — so uninstall.sh's own WDTT scan (its `$SD/swg-wdtt-*.service`, read from uninstall.sh) finds nothing
  [2] CONTROL: a HOST-only convert (the bare node stays) touches no WDTT / csqtt unit; a node with none says nothing

Run: python3 tests/convert_wdtt_units_selftest.py          (0 = pass)
     --perturb-loop   the switch block as shipped (disable --now only) → RED on [1]
     --perturb-rm     stop_bare_wdtt disables only (no rm)             → RED on [1]
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MODE = next((a for a in sys.argv[1:] if a in ("--perturb-loop", "--perturb-rm")), None)
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

DK = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f stop_bare_wdtt stop_bare_csqtt', "_",
                    os.path.join(ROOT, "lib/common.sh")], capture_output=True, text=True)
LIB = r.stdout
CALL = "    stop_bare_wdtt    # stopped and deleted"
OLD = ("    for _wu in $(systemctl list-unit-files --no-legend 2>/dev/null | grep -oE 'swg-wdtt-[^ ]+\\.service'); do "
       "systemctl disable --now \"$_wu\" >/dev/null 2>&1 || true; done   # stopped and deleted")
RM = '        rm -f "$unit";\n        n=$((n+1));\n'
assert DK.count(CALL) == 1 and "stop_bare_wdtt ()" in LIB and LIB.count(RM) == 2, \
    "the switch block / stop_bare_wdtt are not where this gate reads them — would FALSE-PASS"
if MODE == "--perturb-loop":
    DK = DK.replace(CALL, OLD)
if MODE == "--perturb-rm":
    k = LIB.index("stop_bare_wdtt ()")
    LIB = LIB[:k] + LIB[k:].replace(RM, "        n=$((n+1));\n", 1)

# the switch block: from the bare node's teardown's guard to its `fi`
i = DK.index('  if [ "$PROFILE" != host ]; then\n', DK.index("lc_teardown_baremetal ${MIGRATED_TURNS:-}"))
j = DK.index("\n  fi\n", i) + len("\n  fi\n")
BLK = DK[i:j]
m = re.search(r'for unit in \$\(ls \$SD/swg-wdtt-\*\.service 2>/dev/null \|\| true\); do[^\n]*\n\s*add "WDTT \(service \+ interface\)', U)
assert m, "uninstall.sh's WDTT scan is not where this gate reads it — would FALSE-PASS"
SCAN = 'ls $SD/swg-wdtt-*.service 2>/dev/null || true'          # what uninstall.sh lists its WDTT components from

T = tempfile.mkdtemp(prefix="cvwdtt-")
BIN = os.path.join(T, "bin"); os.makedirs(BIN)
open(os.path.join(BIN, "systemctl"), "w").write('#!/bin/bash\necho "systemctl $*" >> "$T/calls"\n'
    'case "$1" in list-unit-files) for f in "$SD"/*.service; do [ -e "$f" ] && echo "$(basename "$f") disabled enabled"; done;; esac\n'
    'exit 0\n')
open(os.path.join(BIN, "ip"), "w").write('#!/bin/bash\necho "ip $*" >> "$T/calls"\nexit 0\n')
for f in ("systemctl", "ip"):
    os.chmod(os.path.join(BIN, f), 0o755)

def convert(name, profile, units):
    sd = os.path.join(T, name, "etc/systemd/system"); os.makedirs(sd)
    for u in units:
        open(os.path.join(sd, u), "w").write("[Service]\n")
    open(os.path.join(T, "calls"), "w").close()
    sh = 'set -euo pipefail\nPROFILE=%s; SYSTEMD_DIR=%s\n%s\n%s\necho END\nSD=%s; echo "SCAN=$(%s)"\n' % (profile, sd, LIB, BLK, sd, SCAN)
    p = subprocess.run(["bash", "-c", sh], capture_output=True, text=True,
                       env=dict(os.environ, PATH=BIN + ":" + os.environ["PATH"], T=T, SD=sd))
    return p, sorted(os.listdir(sd)), open(os.path.join(T, "calls")).read()

UNITS = ("swg-wdtt-wdtt0.service", "swg-wdtt-wdtt1.service", "swg-csqtt-csqtt0.service", "swg-noded.service", "my-own.service")
print("[1] a node / master convert's switch: the bare WDTT units are stopped AND deleted, as csqtt's are")
for profile in ("node", "master"):
    p, left, calls = convert("conv-" + profile, profile, UNITS)
    check("[1] %s: the switch block ran to its end" % profile, p.returncode == 0 and "END" in p.stdout, (p.returncode, p.stderr[-300:]))
    check("[1] %s: no swg-wdtt-* unit is left — nothing for a later uninstall to list as \"WDTT (service + interface)\"" % profile,
          not [u for u in left if u.startswith("swg-wdtt-")] and "SCAN=\n" in p.stdout + "\n", (left, p.stdout))
    check("[1] %s: …each was stopped first (disable --now), then one daemon-reload, and the run says so" % profile,
          "disable --now swg-wdtt-wdtt0" in calls and "disable --now swg-wdtt-wdtt1" in calls
          and calls.index("disable --now swg-wdtt-wdtt1") < calls.index("daemon-reload")
          and "stopped 2 bare-metal WDTT server(s)" in p.stdout, (calls, p.stdout))
    check("[1] %s: csqtt's as before — stopped, its raw TUN deleted, its unit gone" % profile,
          "disable --now swg-csqtt-csqtt0" in calls and "ip link delete dev csqtt0" in calls
          and "swg-csqtt-csqtt0.service" not in left, (calls, left))
    check("[1] %s: …and no WDTT interface is touched by the switch, nothing else removed" % profile,
          "dev wdtt" not in calls and left == ["my-own.service", "swg-noded.service"], (calls, left))

print("\n[2] CONTROL")
p, left, calls = convert("conv-host", "host", UNITS)
check("[2] a HOST-only convert (the bare node stays up) touches no WDTT / csqtt unit",
      p.returncode == 0 and sorted(UNITS) == left and calls == "", (left, calls))
p, left, calls = convert("conv-none", "node", ("swg-noded.service",))
check("[2] a node with no WDTT / csqtt server: nothing said, stopped or reloaded",
      p.returncode == 0 and "stopped" not in p.stdout and not re.search(r"disable|daemon-reload|^ip ", calls, re.M), (p.stdout, calls))

print("")
if MODE:
    ok = bool(FAILS) and all(f.startswith("[1]") for f in FAILS) and any("no swg-wdtt-* unit is left" in f for f in FAILS)
    print("perturb (%s): %s" % (MODE, "RED as it must be (%d), all in [1]" % len(FAILS) if ok else "NOT CAUGHT / WRONG: %s" % FAILS))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
