#!/usr/bin/env python3
"""Self-test — AFTER A RE-INSTALL THE SUBSCRIPTION SERVER'S BIND IS BACK WHEN THE RUN FINISHES, NOT AT THE NEXT PANEL START.

1.8.8 qualification, round 8: after an uninstall that kept the data, the re-install came back without swg-sub's
10-access.conf (swg-netctl's drop-in carrying the bind the panel's settings hold) until the panel's NEXT start. The panel
re-asserts that bind when it starts (_reconcile_sub_listen_at_boot) — but only when swg-sub is installed, and
install-host.sh wrote swg-sub's unit at its very end, after every point where it starts the panel. The first start found
no swg-sub and left the bind out.

  [1] install-host.sh writes swg-sub's unit (when there is none) BEFORE every line that starts the panel, and runs
      daemon-reload with it — only when missing: a unit that exists is left to the final write, as before
  [2] …the final write (its real bind values) and its start stay at the end, as before — the one panel restart after it
      is the one that follows swg-sub moving (round 12, 434205d: its start records swg-sub's new address), and it does
  [3] the queue the panel filled at its start (the set-listen, the restart) is drained before the run ends — bounded
  [4] the panel still re-asserts the bind only when swg-sub is present (the reason [1] must come first) — its guard is read

Run: python3 tests/sub_bind_at_reinstall_selftest.py     (0 = pass)
     --perturb         no early unit (the shipped order) → RED on [1]
     --perturb-drain   the queue left to the path watch → RED on [3]
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
P = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
MODE = next((a for a in sys.argv[1:] if a in ("--perturb", "--perturb-drain")), None)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

EARLY = 'if [ -f "$PREFIX$SUB_DIR/swg-sub" ] && [ ! -e "$PREFIX/etc/systemd/system/swg-sub.service" ]; then write_sub_unit; run systemctl daemon-reload; fi\n'
DRAIN = 'if ! $DRYRUN && [ -n "$(ls -A "$STATE_DIR/netctl/queue" 2>/dev/null)" ]; then run timeout 60 systemctl start swg-netctl.service 2>/dev/null || true; fi\n'
if MODE == "--perturb":
    assert H.count(EARLY) == 1, "perturbation anchor missing — would FALSE-PASS"
    H = H.replace(EARLY, "")
if MODE == "--perturb-drain":
    assert H.count(DRAIN) == 1, "perturbation anchor missing — would FALSE-PASS"
    H = H.replace(DRAIN, "")

def code_lines(src):
    out = []
    for i, l in enumerate(src.splitlines(), 1):
        c = l.split(" #")[0] if not l.lstrip().startswith("#") else ""
        out.append((i, c))
    return out

L = code_lines(H)
starts = [i for i, c in L if re.search(r"systemctl (enable[^\n]*\$_NOW|restart|start) [^\n]*swg-panel-server", c)
          and "record swg-sub's new address" not in c]
record = [i for i, c in L if re.search(r"systemctl restart swg-panel-server", c) and "record swg-sub's new address" in c]
early = [i for i, c in L if "write_sub_unit" in c and "! -e" in c and "swg-sub.service" in c]
final = [i for i, c in L if "write_sub_unit" in c and "enable" in c and "swg-sub" in c]
defn = [i for i, c in L if re.match(r"write_sub_unit\(\)\{", c)]

print("[1] swg-sub's unit exists before the panel first starts")
check("[1] there are panel start points to be before (the census found %d)" % len(starts), len(starts) >= 3, starts)
check("[1] the unit is written when missing, after its function is defined and before EVERY panel start",
      len(early) == 1 and defn and defn[0] < early[0] and all(early[0] < s for s in starts), (early, defn, starts))
check("[1] …only when there is none, with a daemon-reload so systemd knows it (the panel asks systemd)",
      len(early) == 1 and "daemon-reload" in dict(L)[early[0]], early)

print("\n[2] the final write and the start stay at the end")
check("[2] write_sub_unit + enable swg-sub after every panel start", len(final) == 1 and all(final[0] > s for s in starts), (final, starts))
check("[2] …and the one restart after it is the one that records swg-sub's new address (it follows the final write)",
      len(record) == 1 and final and record[0] > final[0], (record, final))

print("\n[3] the panel's first-start queue is drained before the run ends")
drain = [i for i, c in L if "systemctl start swg-netctl.service" in c]
wn = [i for i, c in L if re.match(r"write_netctl\s", c)]
check("[3] after write_netctl (the helper exists), bounded by a timeout, only when the queue holds something",
      len(drain) == 1 and wn and drain[0] > wn[-1] and "timeout" in dict(L)[drain[0]] and "netctl/queue" in dict(L)[drain[0]], (drain, wn))

print("\n[4] the reason: the panel re-asserts the bind only when swg-sub is installed")
m = re.search(r"def _reconcile_sub_listen_at_boot\(deps\):.*?\n(?=def )", P, re.S)
check("[4] _reconcile_sub_listen_at_boot returns early when swg-sub is not present",
      m is not None and 'if not (panel_service_health().get("sub") or {}).get("present"):' in m.group(0), m.group(0)[:200] if m else None)
check("[4] …and the panel runs it at start", "_reconcile_sub_listen_at_boot(Handler.deps)" in P)

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
