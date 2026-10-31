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
     --perturb-kinds     drops `socks5` from the SPA's EXIT_KINDS and expects RED in [4] alone.
     --perturb-vkhash    lets the browser take a 15-character VK hash and expects RED in [5] alone.
     --perturb-awg <n>   drops one key from AmneziaWG key list <n> (0-5, see [3]; 6 = swg-sub's 3.x tail) and expects RED
                         in [3] alone. Without <n>, each of the seven in turn (a bare flag died on an IndexError, which a
                         sweep of every --perturb* reads as a perturbation that never ran).
"""
import ast, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_KINDS = "--perturb-kinds" in sys.argv
PERTURB_VKHASH = "--perturb-vkhash" in sys.argv
_AWG_ARG = sys.argv[sys.argv.index("--perturb-awg") + 1:][:1] if "--perturb-awg" in sys.argv else None
if _AWG_ARG is not None and not (_AWG_ARG and _AWG_ARG[0].isdigit()):
    import subprocess
    _bad = []
    for _n in range(7):
        _r = subprocess.run([sys.executable, os.path.abspath(__file__), "--perturb-awg", str(_n)], capture_output=True, text=True)
        print("  --perturb-awg %d: %s" % (_n, ((_r.stdout.strip().splitlines() or ["(no output)"])[-1])[:200]))
        if _r.returncode != 0:
            _bad.append(_n)
    print("\nPERTURB OK — each of the seven lists went red on its own" if not _bad
          else "\nPERTURB FAILED — list(s) %s did not go red on their own" % _bad)
    sys.exit(1 if _bad else 0)
PERTURB_AWG = int(_AWG_ARG[0]) if _AWG_ARG else None

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
    # ⚠️ asserted: without "|nerdctl" in the filter this nudge plants nothing, and [1]'s nudge alone would carry the run
    assert sh_re.count("|nerdctl") == 1, "perturbation anchor missing (|nerdctl) — this run would FALSE-PASS"
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
if PERTURB_AWG is not None and PERTURB_AWG < len(LISTS):
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
# swg-sub needs only the 3.x half — its apply_iface_meta takes those from the record alone, like the panel's — so it holds
# that tail and nothing else.
_sub3 = _list("swg-sub", r'^AWG3_FIELDS = (\(.*?"\))$')
if PERTURB_AWG == 6:
    _sub3.remove("RekeyTimeout")
check("swg-sub AWG3_FIELDS == the 3.x tail of %s" % _ref_name, _sub3 == _ref[len(AWG20):], _sub3)
check("…the retired copies stay gone (panel AWG_PARAM_KEYS, noded _AWG_CONF_KEYS, swg-sub AWG_PARAM_KEYS)",
      not re.search(r"^AWG_PARAM_KEYS\s*=", src("swg-panel-server"), re.M)
      and not re.search(r"^_AWG_CONF_KEYS\s*=", src("swg-noded"), re.M)
      and not re.search(r"^AWG_PARAM_KEYS\s*=", src("swg-sub"), re.M))
check("…and js/iface.js derives its 2.0 set from AWG_ORDER instead of holding a copy (moved from screen-settings.js, plan §8 "
      "round 13), and screen-settings.js holds no copy of its own",
      bool(re.search(r"^export const AWG_KEYS = AWG_ORDER\.slice\(0, AWG_ORDER\.indexOf\(\"HeaderProtectionKey\"\)\);$",
                     src("js/iface.js"), re.M))
      and not re.search(r"^(export )?const AWG_KEYS\s*=", src("js/screen-settings.js"), re.M))

print("\n[4] the exit kinds — the panel makes, the node runs, the SPA offers the same ones, by name (s9a F28)")
_pk = ast.literal_eval(one("swg-panel-server", r"^EXIT_PROVIDERS = (\(.*\))$", "EXIT_PROVIDERS"))
_nk = ast.literal_eval(one("swg-noded", r"^EXIT_KINDS = (\(.*\))$", "EXIT_KINDS"))
_sk = ast.literal_eval(one("js/routing.js", r"^export const EXIT_KINDS = (\[.*\]);$", "EXIT_KINDS"))
if PERTURB_KINDS:
    _sk = [k for k in _sk if k != "socks5"]
check("panel EXIT_PROVIDERS == noded EXIT_KINDS == SPA EXIT_KINDS", list(_pk) == list(_nk) == list(_sk), (_pk, _nk, _sk))

print("\n[5] a bare VK call hash → its link — the panel's _vk_link_norm and the browser's normVkLink (S12b)")
# The pool, a user's QR-modal field and their Manage sheet take a hash on its own. The browser turns it into the link
# before it validates and sends; the server does the same for whatever reaches the API. If the two disagree on what a
# hash IS, a field the browser accepts is refused on save, or one shape is stored for some links and another for others.
import json as _json, subprocess as _sp
_minlen = one("swg-panel-server", r"^_CSQTT_VK_MAX, _CSQTT_VK_MINLEN, _CSQTT_VK_MAXLEN = \d+, (\d+), \d+$", "_CSQTT_VK_MINLEN")
_pyre = one("swg-panel-server", r'^_VK_HASH_RE = re\.compile\(r"(\[A-Za-z0-9_-\]\{)%d,\}" % _CSQTT_VK_MINLEN\)$', "_VK_HASH_RE")
_pyjoin = one("swg-panel-server", r'^VK_JOIN_URL = "([^"]+)"$', "VK_JOIN_URL")
_pyfn = one("swg-panel-server", r"^(def _vk_link_norm\(s\):\n(?:    .*\n)+)", "_vk_link_norm")
_ns = {"re": re, "VK_JOIN_URL": _pyjoin, "_VK_HASH_RE": re.compile(_pyre + _minlen + ",}")}
exec(_pyfn, _ns)
_jsjoin = one("js/peer-ui.js", r'^export const VK_JOIN_URL = "([^"]+)";$', "VK_JOIN_URL")
_jsfn = one("js/peer-ui.js", r"^export (function normVkLink\(s\) \{.*\n.*\}\s*)$", "normVkLink")
if PERTURB_VKHASH:
    assert _jsfn.count("{16,}") == 1, "perturbation anchor missing ({16,}) — this run would FALSE-PASS"
    _jsfn = _jsfn.replace("{16,}", "{15,}")
_vec = ["A" * 16, "A" * 15, "  aB3_-xY9zQ8wE7rT6  ", "aB3_-xY9zQ8wE7rT6uI5oP4", "a" * 300, "abc def ghi jkl mno",
        "ééééééééééééééééé", "aaaaaaaaaaaaaaa,b", "https://vk.ru/call/join/aB3_-xY9zQ8wE7rT6", "https://vk.com/call/join/QQQQQQQQQQQQQQQQ?x=1", ""]
_js = _sp.run(["node", "-e", "const VK_JOIN_URL = %s;\n%s\nconsole.log(JSON.stringify(%s.map(normVkLink)))"
               % (_json.dumps(_jsjoin), _jsfn, _json.dumps(_vec))], capture_output=True, text=True)
_jo = _json.loads(_js.stdout or "null") if _js.returncode == 0 else None
check("the browser twin ran", isinstance(_jo, list) and len(_jo) == len(_vec), _js.stderr[-300:])
_po = [_ns["_vk_link_norm"](x) for x in _vec]
check("both turn a hash into the same link", _pyjoin == _jsjoin == "https://vk.ru/call/join/", (_pyjoin, _jsjoin))
if isinstance(_jo, list):
    for x, p, j in zip(_vec, _po, _jo):
        is_link = lambda v: v.startswith(_pyjoin) and v[len(_pyjoin):] == x.strip()
        check("…and agree on %r" % (x[:24],), is_link(p) == is_link(j) and (not is_link(p) or p == j)
              and (not x.strip().startswith("https://") or p == j), "panel=%r browser=%r" % (p[:60], j[:60]))

print()
if PERTURB_VKHASH:
    _red = [f for f in FAILS if "agree" in f]
    print("PERTURB OK — %s went red" % _red if _red and len(_red) == len(FAILS)
          else "PERTURB FAILED — the browser took a 15-character hash and [5] stayed green (or something else went red: %s)" % FAILS)
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_KINDS:
    _red = [f for f in FAILS if "EXIT_KINDS" in f]
    print("PERTURB OK — %s went red" % _red if _red and len(_red) == len(FAILS)
          else "PERTURB FAILED — the SPA's kinds lost socks5 and [4] stayed green (or something else went red: %s)" % FAILS)
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB_AWG is not None:
    _red = [f for f in FAILS if "AWG" in f or "==" in f]
    print("PERTURB OK — %s went red" % _red if _red and len(_red) == len(FAILS)
          else "PERTURB FAILED — dropping a key from %s left [3] green (or reddened something else: %s)" % (LISTS[PERTURB_AWG][0] if PERTURB_AWG < len(LISTS) else "swg-sub AWG3_FIELDS", FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS
          else "PERTURB FAILED — both pairs were nudged out of step and every check still passed")
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
