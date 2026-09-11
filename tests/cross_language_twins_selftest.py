"""Self-test — A CONSTANT COPIED INTO ANOTHER LANGUAGE MUST BE EQUAL, NOT MERELY COMMENTED.

Three programs and a browser SPA cannot import each other, so a handful of values are written out twice with
a comment as the only glue: "must match X", "MIRRORS Y — keep the two in step". A comment is a promise, and
this repository has already been bitten by both halves of the pattern within one week —

  • the panel's `_send_bytes` warned about the RESPONSE side of HTTP keep-alive framing for months while the
    REQUEST side went unguarded, and the request side is what broke;
  • `_missing_ifaces` and `iface_restore_req` each answered "what config does this lost interface come back
    with", differently, and only one of them was right.

So the twins that CAN be compared mechanically are compared here. This gate deliberately does not try to
find twins on its own — that would be a heuristic that goes quiet. Each pair is named, and each is asserted
to exist before it is compared, so a rename fails loudly instead of silently matching nothing.

⚠️ IT ALSO CHECKS THAT THE COMMENT POINTS AT A REAL FILE. `CPU_SAT_PCT`'s note said "must match SAT_PCT in
app.js" — and app.js was split into js/*.js, taking SAT_PCT to js/screen-nodes.js. The values still agreed;
the direction to the other half had rotted, which is how a twin stops being maintained.

Run: python3 tests/cross_language_twins_selftest.py      (0 = pass)
     --perturb   nudges each pair out of step and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()

def one(rel, pat, what):
    """The single capture of `pat` in `rel` — asserted to be unique, so a rename cannot pass as a match."""
    # ⚠️ `re.M`, or an `^`-anchored pattern matches only at byte 0 and finds nothing — which the assertion
    # below then reports as "would measure nothing" rather than passing. That is the assertion earning its keep.
    hits = re.findall(pat, src(rel), re.M)
    assert len(hits) == 1, "%s: expected exactly one %s, found %d — this run would measure nothing" % (
        rel, what, len(hits))
    return hits[0]


print("[1] the CPU saturation threshold — the panel raises the alert, the browser draws it")
# Both sides must agree or a core reads "hot" on one screen and fine on the other, for the same number.
py = one("swg-panel-server", r"^CPU_SAT_PCT = (\d+)", "CPU_SAT_PCT")
js = one("js/screen-nodes.js", r"^export const SAT_PCT = (\d+);", "SAT_PCT")
if PERTURB:
    js = str(int(js) + 5)
check("CPU_SAT_PCT == SAT_PCT", py == js, "panel=%s browser=%s" % (py, js))
# …and the pointer to the other half still resolves. This is the half that actually rotted.
_note = one("swg-panel-server", r"^CPU_SAT_PCT = \d+\s+# .*must match SAT_PCT in (\S+?)\)", "CPU_SAT_PCT note")
check("…and the comment names a file that exists", os.path.exists(os.path.join(ROOT, _note)), _note)
check("…which is where SAT_PCT actually lives", "export const SAT_PCT" in src(_note), _note)

print("\n[2] the bindable-address filter — the panel's picker and the installer's must hide the same NICs")
# The installer offers "Listen IP" choices before the panel exists; the panel offers them afterwards. A NIC
# one hides and the other offers is how a panel ends up bound to a VPN tunnel's own address.
py_re = one("swg-panel-server", r'_IFACE_SKIP_RE = re\.compile\(r"\^\(([^"]+)\)"\)', "_IFACE_SKIP_RE")
sh_re = one("lib/common.sh", r'\$2 !~ /\^\(([^)]+)\)/', "the awk name filter")
if PERTURB:
    sh_re = sh_re.replace("|nerdctl", "")
# `\d` in Python, `[0-9]` in awk — the same class written in each dialect. Normalise, then compare as SETS:
# order is irrelevant to an alternation, and demanding it would make the gate fail on a harmless reorder.
norm = lambda s: {p.replace("[0-9]", r"\d").strip() for p in s.split("|") if p.strip()}
a, b = norm(py_re), norm(sh_re)
check("both filters are non-trivial", len(a) > 5 and len(b) > 5, (len(a), len(b)))
check("the panel hides nothing the installer offers", not (a - b), "panel-only: " + str(sorted(a - b)))
check("the installer hides nothing the panel offers", not (b - a), "installer-only: " + str(sorted(b - a)))

print()
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS
          else "PERTURB FAILED — both pairs were nudged out of step and every check still passed")
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
