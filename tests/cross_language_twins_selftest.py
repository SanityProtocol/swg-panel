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
     --perturb           nudges pairs [1] and [2] out of step and expects RED.
     --perturb-awg <n>   drops one key from AmneziaWG key list <n> (0-5, see [3]) and expects RED in [3] alone.
"""
import ast, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_AWG = int(sys.argv[sys.argv.index("--perturb-awg") + 1]) if "--perturb-awg" in sys.argv else None

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

print("\n[3] the AmneziaWG key lists — one per program, all the same keys in the same order (docs/AWG3-PLAN.md §5, §7.5)")
# Six programs name the AmneziaWG parameters; each one's list decides what it keeps. A key missing from ONE of them is
# dropped in silence at that hop: the panel would store a HeaderProtectionKey the node never reports (re-pushed every
# sync), the node would report one the agent strips from the conf, a config would render without it. There used to be
# ten such lists, four of them same-file duplicates; those are asserted gone, so a fifth copy is not quietly reborn.
def _list(rel, pat):
    """The literal a statement assigns, from its opening bracket to the closing one right after the LAST quoted key — the
    comments inside these lists carry brackets of their own. Parsed as Python (comments are legal there; a JS `//` one is
    blanked first), and found exactly once, so a rename fails loudly instead of matching nothing."""
    hits = re.findall(pat, src(rel), re.M | re.S)
    assert len(hits) == 1, "%s: expected exactly one AmneziaWG key list, found %d — this run would measure nothing" % (
        rel, len(hits))
    return list(ast.literal_eval(re.sub(r"//[^\n]*", "", hits[0]) if rel.endswith(".js") else hits[0]))
LISTS = [("swg-panel-server AWG_FIELDS", _list("swg-panel-server", r'^AWG_FIELDS = (\(.*?"\))$')),
         ("swg-noded AWG_KEYS", _list("swg-noded", r'^AWG_KEYS = (\[.*?"\])$')),
         ("swg-agent AWG_KEYS", _list("swg-agent", r'^AWG_KEYS  = (\[.*?"\])$')),
         ("js/crypto.js AWG_ORDER", _list("js/crypto.js", r'^export const AWG_ORDER = (\[.*?"\]);')),
         ("sub.js AWG_ORDER", _list("sub.js", r'^  var AWG_ORDER = (\[.*?"\]);')),
         ("turn-artifacts.js AWG_ORDER", _list("turn-artifacts.js", r'^  var AWG_ORDER = (\[.*?"\]);'))]
if PERTURB_AWG is not None:
    LISTS[PERTURB_AWG][1].remove("RekeyTimeout")
_ref_name, _ref = LISTS[0]
# Named here, not taken from any one list: equality alone would stay green if a key vanished from all six at once.
AWG20 = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"]
AWG3 = ["HeaderProtectionKey", "RandomTrailers", "ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout",
        "RejectAfterTime", "KeepaliveTimeout", "MaxHandshakeAttempts", "DisableCookies"]
check("%s is the 2.0 keys then the 3.x keys" % _ref_name, _ref == AWG20 + AWG3, _ref)
for _name, _lst in LISTS[1:]:
    check("%s == %s" % (_name, _ref_name), _lst == _ref,
          "missing %s, extra %s" % (sorted(set(_ref) - set(_lst)), sorted(set(_lst) - set(_ref))) if set(_lst) != set(_ref)
          else "same keys, another order")
check("…the retired copies stay gone (panel AWG_PARAM_KEYS, noded _AWG_CONF_KEYS, swg-sub AWG_PARAM_KEYS)",
      not re.search(r"^AWG_PARAM_KEYS\s*=", src("swg-panel-server"), re.M)
      and not re.search(r"^_AWG_CONF_KEYS\s*=", src("swg-noded"), re.M)
      and not re.search(r"^AWG_PARAM_KEYS\s*=", src("swg-sub"), re.M))
check("…and js/screen-settings.js derives its 2.0 set from AWG_ORDER instead of holding a copy",
      bool(re.search(r"^export const AWG_KEYS = AWG_ORDER\.slice\(0, AWG_ORDER\.indexOf\(\"HeaderProtectionKey\"\)\);$",
                     src("js/screen-settings.js"), re.M)))

print()
if PERTURB_AWG is not None:
    _red = [f for f in FAILS if "AWG" in f or "==" in f]
    print("PERTURB OK — %s went red" % _red if _red and len(_red) == len(FAILS)
          else "PERTURB FAILED — dropping a key from %s left [3] green (or reddened something else: %s)" % (LISTS[PERTURB_AWG][0], FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS
          else "PERTURB FAILED — both pairs were nudged out of step and every check still passed")
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
