#!/usr/bin/env python3
"""Self-test: an interface name that names nothing must be refused at install time, not five seconds later.

`MANAGE_IFACES` is the unattended way to say which interfaces a node manages. Nothing checked the names
against the box: an unrecognised one fell through to the wg default and was written into config.json as a
managed interface —

    "none": {"cmd": ["wg"], "conf": "/etc/wireguard/none.conf", "endpoint_host": "172.17.0.3"}

— and the node then reported, on EVERY pass, for ever, while the install printed a green summary:

    reconcile: +0 -0 ifaces~0 … errors=['none: cannot read interface']

MEASURED on a scratch box by installing a node with `MANAGE_IFACES=none`. The operator's only clue arrives
five seconds later, on a different screen, and never mentions the word they typed. Only reachable
unattended — the interactive path picks from a list — which is exactly where a typo has nothing to catch it.

⚠️ THE LINE IS "NAMES NOTHING", NOT "IS NOT RUNNING". `detect_wg` walks every conventional wg/awg location
and `reconstruct_live_orphans` runs before it, rebuilding a conf for any live interface that had none — so a
name absent from `IF_CMD` matches no conf and no interface anywhere on the machine. A conf that exists but
cannot come up is a DIFFERENT thing and must still install: that is a broken interface, which is the node's
to report, not the installer's to refuse. Verified both ways on a real box.

Run: python3 tests/manage_ifaces_guard_selftest.py    (0 = pass)
     --perturb  removes the guard and expects RED.
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

# ⚠️ ONE READER, TWO INSTALLERS. The guard first shipped inside install-node.sh's own `choose_ifaces`, and
# install-host.sh — which is what `bootstrap master` runs, the more common first install — kept the defect
# untouched: it read MANAGE_IFACES straight into SELECTED and carried the identical "unknown name → wg
# default" fallback. So the check lives in lib/common.sh now and BOTH are asserted to call it.
src = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
GUARD = '[ -n "${IF_CMD[$_n]:-}" ] || _bad+=("$_n")'
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert GUARD in src, "anchor missing — this run would FALSE-PASS"

print("[1] the guard exists, and is asked AFTER the box has been walked")
check("names are checked against what the box actually has", GUARD in src)
check("…it refuses rather than silently managing fewer interfaces than asked",
      re.search(r'die "MANAGE_IFACES names', src) is not None)
check("…and the message names what the box DOES have", "Found here:" in src)
check("…including when it has none at all",
      "(no wg/awg interfaces at all)" in src and '[ "${#IF_CMD[@]}" -gt 0 ]' in src,
      "an empty associative array still expands to one empty word, so a ${x:-default} never fires")

print("\n[1b] ⚠️ …by BOTH installers, node and master")
for _f in ("install-node.sh", "install-host.sh"):
    _t = open(os.path.join(ROOT, _f), encoding="utf-8").read()
    _blk = _t[_t.index("choose_ifaces(){"):]
    _blk = _blk[:_blk.index('IFS=\',\' read -ra SELECTED <<< "$MANAGE_IFACES"')]
    check("%s calls manage_ifaces_resolve" % _f, "manage_ifaces_resolve" in _blk,
          "reads MANAGE_IFACES into SELECTED unchecked — `MANAGE_IFACES=none` becomes a permanent per-sync error")
    check("…after detect_wg, or IF_CMD is empty and everything reads as 'missing'",
          "detect_wg" in _blk.split("manage_ifaces_resolve")[0], _blk[-200:])
    # ⚠️ NOT IN A COMMAND SUBSTITUTION. `X="$(manage_ifaces_resolve …)"` runs it in a SUBSHELL, so `die`'s
    # `exit 1` kills only that subshell: the parent assigns "" and installs as if nothing had been asked
    # for — the refusal prints its message and then lets the install do the thing it refused.
    # ⚠️ MATCH THE CALL, NOT THE WORD. The first version also rejected a BACKTICKED mention, which is how
    # every comment in this tree names a function — so it fired on the comment that explains the rule.
    check("…and NOT inside $( ), where a `die` would only kill the subshell",
          "$(manage_ifaces_resolve" not in _t and "`manage_ifaces_resolve " not in _t.replace("`manage_ifaces_resolve` ", ""))
check("…and the function assigns MANAGE_IFACES itself, which is what makes that safe",
      'MANAGE_IFACES="$_raw"' in src)

print("\n[2] ⚠️ the guard runs the SAME shell logic the installer does")
# Extract the guard block and run it against fixtures, so this is not a reading of the source.
# ⚠️ CUT AT THE `if`, NOT AT THE `die`. Cutting just before the die leaves `if …; then` dangling, bash
# refuses the whole script, `_bad` reads empty and three checks go red against an installer that is
# provably correct — a harness reporting a defect in code it had truncated. Caught only because the
# behaviour had already been measured on a real box first.
blk = src[src.index("  local _raw="):src.index('  if [ "${#_bad[@]}" -gt 0 ]; then')]
blk = blk[blk.index("  for _n in"):]   # the detection loop only — the normalise half is measured in [3]
if PERTURB:
    blk = blk.replace(GUARD, ':')
def run(names, have):
    sh = ("declare -A IF_CMD\n" +
          "".join('IF_CMD[%s]=wg\n' % h for h in have) +
          "_bad=()\n_want=(%s)\n" % " ".join(names) +
          blk.replace("local ", "").replace("${_want[@]+\"${_want[@]}\"}", '"${_want[@]}"') +
          '\nprintf "%s\\n" "${_bad[*]:-}"\n')
    r = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
    return r.stdout.strip()
check("a name the box does not have is caught", run(["typo9"], ["wg7"]) == "typo9", run(["typo9"], ["wg7"]))
check("…a name it DOES have is not", run(["wg7"], ["wg7"]) == "", run(["wg7"], ["wg7"]))
check("…every bad name is named, not just the first", run(["a", "wg7", "b"], ["wg7"]) == "a b", run(["a", "wg7", "b"], ["wg7"]))
check("…and a box with nothing at all refuses any name", run(["wg7"], []) == "wg7", run(["wg7"], []))

print("\n[3] ⚠️ …and the whole function, end to end, refuses and normalises")
# [2] runs the detection loop; this runs the REAL function, so the exit status and the normalisation are
# measured rather than read. A blank-ish value must not become a blank array entry: `MANAGE_IFACES=" "` is
# non-empty, takes the explicit-list branch, and every later loop then indexes IF_* with an empty
# subscript — the install died at `IF_CMD: bad array subscript` in the middle of Step 1.
_fn = src[src.index("manage_ifaces_resolve(){"):]
_fn = _fn[:_fn.index("\n}\n") + 3]
if PERTURB:
    _fn = _fn.replace(GUARD, ':')
def whole(value, have):
    sh = ('C_RED=""; RESET=""\ndie(){ echo "REFUSED: $*" >&2; exit 1; }\nb(){ printf "%s" "$1"; }\n'
          "declare -A IF_CMD\n" + "".join('IF_CMD[%s]=wg\n' % h for h in have) + _fn +
          '\nMANAGE_IFACES=%s\nmanage_ifaces_resolve\nprintf "OK:%%s\\n" "$MANAGE_IFACES"\n' % ("'" + value + "'"))
    r = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip().replace("\n", " | ")
rc, out = whole("none", ["awg0", "wg0"])
check("`MANAGE_IFACES=none` on a box with awg0/wg0 exits non-zero", rc != 0, (rc, out))
check("…naming the word the operator typed", "names none" in out, out)
check("…and listing what the box does have", "awg0" in out and "wg0" in out, out)
rc, out = whole("awg0", ["awg0", "wg0"])
check("a real name installs", rc == 0 and out.endswith("OK:awg0"), (rc, out))
rc, out = whole("awg0, wg0 ", ["awg0", "wg0"])
check("…a spaced list is normalised, not turned into blank entries", rc == 0 and out.endswith("OK:awg0,wg0"), (rc, out))
rc, out = whole(" ", ["awg0"])
check("…and a value that is only whitespace means 'blank', not one empty interface name",
      rc == 0 and out.endswith("OK:"), (rc, out))

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: a typo becomes a permanent per-sync error again" % len(FAILS))
          if ok else "PERTURB FAILED — the guard was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
