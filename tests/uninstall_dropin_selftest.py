#!/usr/bin/env python3
"""Self-test: an uninstall must take a unit's DROP-IN DIRECTORY with the unit.

A `.service.d/` drop-in OVERRIDES the unit it sits beside, and it outlives it: systemd simply ignores a
drop-in whose unit is gone, and puts it straight back into force the moment a unit of that name returns.

`uninstall.sh` already reaps `swg-panel-server.service.d` and `swg-sub.service.d`. It did NOT reap
`swg-netctl.service.d` — the one unit here that actually gets a drop-in written to it, by `update.sh`'s
`ensure_acme_home`, which pins `LE_WORKING_DIR` because acme.sh otherwise follows `$HOME` and a systemd
helper has none.

MEASURED on a scratch box, not reasoned about: a full uninstall, then a fresh install from nothing, and

    stat  /etc/systemd/system/swg-netctl.service.d/acme-home.conf   20:25:39   ← the OLD install
    stat  /etc/systemd/system/swg-netctl.service                    20:34:17   ← the NEW one
    systemctl show -p Environment swg-netctl  →  … LE_WORKING_DIR=/root/.acme.sh   ← from the drop-in

Benign only because both installs happened to canonicalise the same store. A drop-in beats the unit, so the
day one does not, the previous install's pin silently wins — and `ensure_acme_home` skips its heal whenever
it finds ANY `LE_WORKING_DIR` in that directory, so the residue suppresses the correction for it.
([[acme-store-split-and-arms]] is what that costs: certificates renewed into a store nothing reads.)

Run: python3 tests/uninstall_dropin_selftest.py     (0 = pass)
     --perturb  drops `swg-netctl.service.d` from the reap lists, the way it shipped, and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert "$SD/swg-netctl.service.d" in src, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    src = src.replace(" $SD/swg-netctl.service.d", "").replace(" $SD/swg-netctl-docker.service.d", "")

# ⚠️ DERIVED FROM THE WRITERS, NOT FROM THE REAPERS. The first version of this asserted that EVERY unit
# fragment in an `rmrf` list has a `.service.d` beside it, and immediately reported three more —
# `swg-noded`, `swg-relay@`, `swg-update`. Nothing in this tree writes a drop-in for any of them, so that
# would have been three directories reaped to satisfy a gate rather than a defect, and it would silently
# sweep an operator's OWN override for a unit we never touch. Over-engineering is a finding too.
#
# The invariant that IS supported: every drop-in this tree writes must be reaped by the uninstaller. Both
# ends are read from source, so a new writer added later fails here rather than shipping a new leftover.
WRITERS = ("update.sh", "lib/common.sh", "install-host.sh", "install-node.sh", "install-docker.sh", "convert.sh")
written = set()
for f in WRITERS:
    fp = os.path.join(ROOT, f)
    if not os.path.exists(fp):
        continue
    for m in re.finditer(r"/etc/systemd/system/([A-Za-z0-9@.-]+)\.service\.d", open(fp, encoding="utf-8").read()):
        written.add(m.group(1))
check("some drop-in writer was found at all — otherwise this gate is measuring nothing",
      len(written) >= 2, sorted(written))
rmrf = " ".join(m.group(0) for m in re.finditer(r"rmrf[\s\S]*?(?=\n\s*(?:#|[a-z_]+\b))", src))
for u in sorted(written):
    check("a drop-in is written for `%s` — so the uninstaller reaps it" % u,
          ("$SD/%s.service.d" % u) in rmrf or ("%s.service.d" % u) in src,
          "a .service.d survives its unit and overrides the NEXT install of that name")

print()
# …and the one that motivated this, named, so a rename cannot quietly drop it.
check("⚠️ swg-netctl — the one unit that is actually given a drop-in — is covered",
      "$SD/swg-netctl.service.d" in src)
check("…in BOTH paths: the full uninstall and the leftover sweeper `rm_netctl`",
      src.count("$SD/swg-netctl.service.d") >= 2, src.count("$SD/swg-netctl.service.d"))
# the writer this is about — if it moves, this test is aimed at nothing
upd = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
check("…and the thing that writes it is still there and still writes THAT path",
      "swg-netctl.service.d" in upd and "acme-home.conf" in upd)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the drop-in outlives the unit again" % len(FAILS)) if ok
          else "PERTURB FAILED — the reap was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
