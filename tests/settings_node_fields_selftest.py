#!/usr/bin/env python3
"""Self-test: a per-node setting must be named in EVERY list that handles it — SPA and server.

This is the whitelist-rebuild shape, and it bit twice while wiring the exits UI, in two different files:

  server   `exit_id` was written by the save path and published by NOBODY. Three record builders each
           rebuild from a key list (the interface meta, `wdtt_cfg`, `csqtt_cfg`) and a field absent from
           them simply never reaches the browser — after which `egressInit` reads the mode off a record
           with no id, opens the editor on "Auto", and the next Save rewrites a working exit interface to
           direct with the operator having changed nothing.

  SPA      a per-node field is named in FOUR places, and each failure is different:
             nFields          absent → the field is not in the draft at all; edits do not stick
             SECF             absent → the section never reads dirty; Save stays greyed out
             api.nodeUpdate   absent → Save runs and silently does not send it
             diffList         absent → Save LIGHTS UP and then says "No changes to save" and writes
                              nothing. An enabled button that does nothing, edits still on screen.
           The last one is the one that shipped in this session's first pass, and no other check could see
           it: `anyDirty` reads SECF, so every other signal said the edit was live.

Structural, from the source — it cannot be satisfied by a comment or a test fixture.

Run: python3 tests/settings_node_fields_selftest.py (0 = pass)
     --perturb  drops `exits` from diffList, the way the first pass shipped it, and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SETTINGS = os.path.join(ROOT, "js", "screen-settings.js")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(SETTINGS, encoding="utf-8").read()


def block(text, start_pat, open_ch="{", close_ch="}"):
    """The balanced region opened by the LAST character of `start_pat`, so a nested object cannot end the
    scan early AND an anchor that itself contains brackets (`ov.get(k) for k in (`) cannot start it on the
    wrong one. Every pattern here therefore ends WITH its opening bracket: the first version searched from
    `m.start()`, captured `(k)`, and reported six fields that are plainly there as missing."""
    m = re.search(start_pat, text)
    assert m, "anchor not found: " + start_pat
    i = m.end() - 1
    assert text[i] == open_ch, "anchor must end with " + open_ch + ": " + start_pat
    depth, j = 0, i
    while j < len(text):
        if text[j] == open_ch:
            depth += 1
        elif text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    raise AssertionError("unbalanced block after " + start_pat)


def top_keys(blk):
    """`key:` at brace-depth 1 only — a nested literal's keys are not this record's fields."""
    out, depth, i = [], 0, 0
    while i < len(blk):
        c = blk[i]
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif depth == 1:
            m = re.match(r"([A-Za-z_]\w*)\s*:", blk[i:])
            if m and (i == 0 or blk[i - 1] in "{,\n \t"):
                out.append(m.group(1))
                i += m.end() - 1
        i += 1
    return out


nfields = set(top_keys(block(src, r"const nFields = n => \(\{")))
secf_blk = block(src, r"const SECF = \{")
secf = set(re.findall(r'"([a-z_]+)"', secf_blk))
body = set(top_keys(block(src, r"await api\.nodeUpdate\(\{"))) - {"id"}
diff_blk = block(src, r"const diffList = \(\) => \{")
if PERTURB:
    _cut = 'if (!eq(e.exits, o.exits)) fl.push(T("external exits"));'
    assert _cut in diff_blk, "perturbation anchor missing — this run would FALSE-PASS"
    diff_blk = diff_blk.replace(_cut, "")
diffed = set(re.findall(r"\be\.([a-z_]+)", diff_blk))

check("nFields was read at all (%d fields)" % len(nfields), len(nfields) >= 10, sorted(nfields))
check("SECF was read at all", len(secf) >= 10, sorted(secf))
check("the nodeUpdate body was read at all", len(body) >= 10, sorted(body))
check("diffList was read at all", len(diffed) >= 10, sorted(diffed))

check("every drafted per-node field belongs to a SECTION, or nothing marks it dirty",
      not (nfields - secf), sorted(nfields - secf))
check("every drafted per-node field is SENT, or Save quietly drops it",
      not (nfields - body), sorted(nfields - body))
check("every drafted per-node field is NAMED IN THE DIFF, or Save says 'no changes' and writes nothing",
      not (nfields - diffed), sorted(nfields - diffed))
check("nothing is sent that was never drafted", not (body - nfields), sorted(body - nfields))
check("exits reached all four lists",
      {"exits"} <= nfields and {"exits"} <= secf and {"exits"} <= body and {"exits"} <= diffed,
      {"nFields": "exits" in nfields, "SECF": "exits" in secf, "body": "exits" in body, "diff": "exits" in diffed})

# ── the INNER whitelist: an exit record is rebuilt from a key list TWICE ─────────────────────────
# The outer gate above proves `exits` reaches all four per-node lists. It cannot see INSIDE the objects —
# and `nFields` rebuilds each exit from its own key list, so a field the server stores and the SPA does not
# copy is dropped on the next save. `dial_src` shipped that way: stored, rendered as "Auto", and wiped by
# the first unrelated Save. Same shape as the outer bug, one level down.
_pan = open(PANEL, encoding="utf-8").read()
# ⚠️ SCOPED TO THE VALIDATOR'S BODY. The first version searched `out["..."]` across the WHOLE panel and
# reported two dozen unrelated keys — a check that fails for the wrong reason teaches you to skim it.
_vs = _pan.index("def _validate_exits(")
_ve = _pan.index("\ndef ", _vs)
_body = _pan[_vs:_ve]
_out = re.search(r'out = \{"id": eid, "label": lbl.*?\}\n', _body, re.S)
assert _out, "the validator's exit record literal was not found"
_srv_keys = set(re.findall(r'"([a-z_]+)":', _out.group(0))) | set(re.findall(r'out\["([a-z_]+)"\]', _body))
_nf = block(src, r"exits: \(n\.exits \|\| \[\]\)\.map\(x => \(\{", "{", "}")
_spa_keys = set(re.findall(r"([a-z_]+):", _nf))
# `key_blob`/`key_restore`/`why_not`/`live`/`profile`/`cfg_sig` are panel-owned or derived — the operator
# never edits them, so the draft deliberately does not carry them. `cfg_sig` in particular is DERIVED from
# the rest of the record on every save (`exit_cfg_sig`), so a copy carried up from the browser could only
# ever be stale or invented; the panel recomputes it and ignores whatever arrives.
_owned = {"key_blob", "key_restore", "why_not", "live", "profile", "cfg_sig"}
_lost = (_srv_keys - _spa_keys - _owned)
check("every operator-editable exit field survives the SPA's own rebuild",
      not _lost, "stored by the server, dropped by nFields: " + str(sorted(_lost)))

# ── the server half: the three record builders that hand an interface's egress to the browser ────
psrc = open(PANEL, encoding="utf-8").read()
meta = re.search(r'ifc\["exit_id"\]', psrc)
wd = block(psrc, r'"wdtt_cfg": \{ifn: \{k: ov\.get\(k\) for k in \(', "(", ")")
cs = block(psrc, r'"csqtt_cfg": \{ifn: \{k: ov\.get\(k\) for k in \(', "(", ")")
check("the interface meta publishes exit_id", bool(meta))
check("wdtt_cfg publishes exit_id", '"exit_id"' in wd, wd[:120])
check("csqtt_cfg publishes exit_id", '"exit_id"' in cs, cs[:120])
# …and they must agree about the whole egress quartet, since one ladder serves all three kinds.
for k in ("egress_mode", "egress_node", "egress_ip", "wan_iface", "routing", "exit_id"):
    check("both self-contained kinds publish %s" % k, ('"%s"' % k) in wd and ('"%s"' % k) in cs)

if PERTURB:
    if FAILS:
        print("\nperturbed: a per-node field missing from diffList was CAUGHT (%d red) — Save would have "
              "lit up and then written nothing" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually read diffList")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
