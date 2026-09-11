#!/usr/bin/env python3
"""Self-test — THE UNINSTALL FIX MUST REACH THE BOX THAT ALREADY RAN THE OLD UNINSTALL.

`rm_node` learned to remove `swg-relay.slice` (21d33d6), which fixes every box uninstalled from then on. It
does nothing for the box that was uninstalled by an OLDER build: `rm_node` only runs when a node component
is still detected, and that box has none — so its slice stays on disk and ACTIVE, and re-running the new
uninstaller walks straight past it. A fix with no heal path is half a fix, and this tree has shipped that
shape before (a list zeroed by an old parser; a panel whose stamp said "already current").

`rm_leftovers` is the component that exists for exactly this: remnants with no owner left, reached by the
"re-run this uninstaller" the sweep message already promises. So the relay units go there too — idempotent
beside `rm_node`, because stopping a stopped slice is a no-op and both delete the same paths.

Run: python3 tests/uninstall_relay_leftover_selftest.py      (0 = pass)
     --perturb   removes the relay lines from rm_leftovers and expects RED.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
UNINST = os.environ.get("SWG_UNINSTALL_SH") or os.path.join(ROOT, "uninstall.sh")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(UNINST, encoding="utf-8").read()
_ANCH_RM = '  rmrf "$SD/swg-relay@.service" "$SD/swg-relay.slice" /etc/swg-panel/relay'
_ANCH_HAS = '  || [ -e "$SD/swg-relay.slice" ] || [ -e "$SD/swg-relay@.service" ] || [ -d /etc/swg-panel/relay ] \\'
assert SRC.count(_ANCH_RM) == 1, "rm anchor missing — this run would FALSE-PASS"
assert SRC.count(_ANCH_HAS) == 1, "detect anchor missing — this run would FALSE-PASS"
if PERTURB:
    # SURGICAL, both of them. Deleting the detect line outright breaks the `\`-continued condition and the
    # harness dies of a bash syntax error — which is red, but red for the wrong reason: a gate that cannot
    # tell "not detected" from "did not parse" is not measuring what it claims to. Substitute a clause that
    # is valid and always false instead, and leave the rm as a valid no-op.
    SRC = SRC.replace(_ANCH_RM, "  :")
    SRC = SRC.replace(_ANCH_HAS, "  || false \\")

def extract(name):
    m = re.search(r"^%s\(\)\{(.*?)^\}" % re.escape(name), SRC, re.S | re.M)
    if m:
        return name + "(){" + m.group(1) + "}"
    m = re.search(r"^%s\(\)\{.*?;\s*\}$" % re.escape(name), SRC, re.S | re.M)
    assert m, "cannot extract " + name
    return m.group(0)

RM = extract("rm_leftovers")
HAS = extract("_has_leftovers")

def run_case(plant, want_detect):
    """Plant files in a fake systemd dir, then ask _has_leftovers and run rm_leftovers over it."""
    tmp = tempfile.mkdtemp(prefix="unrelay-")
    sd = os.path.join(tmp, "systemd"); os.makedirs(sd)
    etc = os.path.join(tmp, "etc-swg-panel-relay")
    for f in plant:
        if f == "relaydir":
            os.makedirs(etc, exist_ok=True)
        else:
            open(os.path.join(sd, f), "w").write("x\n")
    script = f"""#!/bin/bash
SD={sd!r}
REMOVED_LEFTOVERS=false; NEED_NETOBJ_SWEEP=false
info(){{ :; }}; ok(){{ :; }}; warn(){{ :; }}
run(){{ :; }}                       # never actually talk to systemd or userdel
id(){{ return 1; }}; getent(){{ return 1; }}; userdel(){{ :; }}
rmrf(){{ for p in "$@"; do rm -rf -- "$p" 2>/dev/null || true; done; }}
{HAS}
{RM}
# /etc/swg-panel/relay is an absolute path in the script; point the test's copy at ours instead
_has_leftovers && echo DETECT=yes || echo DETECT=no
rm_leftovers
echo "LEFT=$(ls {sd!r} 2>/dev/null | tr '\\n' ',')"
"""
    p = os.path.join(tmp, "t.sh"); open(p, "w").write(script)
    r = subprocess.run(["bash", p], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    detect = "DETECT=yes" in out
    left = re.search(r"LEFT=([^\n]*)", out)
    return detect, (left.group(1) if left else "?"), out

print("[1] a stale relay slice is DETECTED as a leftover")
d, left, out = run_case(["swg-relay.slice"], True)
check("_has_leftovers says yes for a lone swg-relay.slice", d, out[-300:])
check("…and rm_leftovers removes it", "swg-relay.slice" not in left, left)

print("\n[2] the service template too")
d, left, _ = run_case(["swg-relay@.service"], True)
check("detected", d)
check("removed", "swg-relay@.service" not in left, left)

print("\n[3] both together, as a real leftover box has them")
d, left, _ = run_case(["swg-relay.slice", "swg-relay@.service"], True)
check("detected", d)
check("both removed", "swg-relay" not in left, left)

print("\n[4] a clean box is still clean — no false positive")
d, left, _ = run_case([], False)
check("_has_leftovers says no on an empty dir", not d)

print("\n[5] the same units are removed by BOTH owners, so neither path can be the only one")
src = open(UNINST, encoding="utf-8").read()
node_blk = src[src.index("rm_node(){"):src.index("rm_node(){") + 4000]
check("rm_node still removes the slice", "swg-relay.slice" in node_blk)
check("rm_leftovers removes it as well", _ANCH_RM in src)
check("…and detection covers it", _ANCH_HAS in src)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
