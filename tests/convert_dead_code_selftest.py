#!/usr/bin/env python3
"""Self-test — convert.sh carries no second, dead migration path (1.8.9 qualification IN-5).

convert.sh held a whole turn-proxy migration of its own — turn_to_bare, turn_to_docker, turn_predownload,
turn_install_host, turn_unit_lc, turn_row, fwd_iface_for, its yes/no `cyn` and the MIGRATED_TURNS → SWG_CONVERT_TURNS
hand-off — that nothing had called since 9b9b37a: the live migrations are install-node.sh's migrate_docker_turns and
install-docker.sh's migrate_baremetal_turns. It already misled one fix (1814913 put the dial-host change there, not in
the live copy: IN-3). Deleted; this keeps it from growing back.

  [1] every function convert.sh defines is used in convert.sh (swg_tty_ok excepted: it is one of the seven byte-identical
      copies of the terminal snippet, held to one text by tests/tty_background_selftest.py)
  [2] nothing in convert.sh, install-docker.sh or lib/common.sh names the removed path any more

Run: python3 tests/convert_dead_code_selftest.py      (0 = pass)
     --plant-dead   a turn_to_bare nothing calls, put back → RED on [1] and [2]
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
PLANT = "--plant-dead" in sys.argv[1:]
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = rd("convert.sh")
if PLANT:
    _a = "\nCHECK=no; "
    assert SRC.count(_a) == 1, "plant anchor missing — would FALSE-PASS"
    SRC = SRC.replace(_a, "\nturn_to_bare(){ :; }\nCHECK=no; ")

print("[1] every function convert.sh defines is used")
defs = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", SRC, re.M)
CODE = re.sub(r"(^|\s)#[^\n]*", r"\1", SRC)   # comments are not calls (a mention in one kept turn_to_bare looking alive)
unused = [d for d in defs if d != "swg_tty_ok" and not re.search(r"(?<![\w-])%s(?![\w(-])" % re.escape(d), CODE)]
check("%d functions, none defined and never called" % len(defs), len(defs) > 20 and not unused, unused)

print("\n[2] the removed migration path is named nowhere")
GONE = ("turn_to_bare", "turn_to_docker", "turn_predownload", "turn_install_host", "turn_unit_lc", "turn_row", "cyn",
        "ASSUME_YES", "SWG_CONVERT_TURNS")
for f, s in (("convert.sh", SRC), ("install-docker.sh", rd("install-docker.sh")), ("lib/common.sh", rd("lib/common.sh"))):
    left = [g for g in GONE if re.search(r"(?<![\w-])%s(?![\w-])" % g, s)]
    check("%s: none of %s" % (f, ", ".join(GONE[:3]) + ", …"), not left, left)
check("convert.sh: fwd_iface_for is install-docker.sh's own again (one copy in the tree)",
      "fwd_iface_for(){" not in SRC and rd("install-docker.sh").count("fwd_iface_for(){") == 1)

print("")
if PLANT:
    ok = bool(FAILS) and any(f.startswith("convert.sh: none") for f in FAILS) and any("functions, none defined" in f for f in FAILS)
    print("plant: %s" % ("RED as it must be (%d), [1] and [2]" % len(FAILS) if ok else "NOT CAUGHT: %s" % FAILS))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
