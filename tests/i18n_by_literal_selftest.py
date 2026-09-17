#!/usr/bin/env python3
"""Self-test: the author word "by" is never glued into display text as an English literal.

"<app> by <author>" was spelled with a literal " by " in six places — three turn cells on the subscription page (sub.js) and
three pickers/bubbles in the operator app (js/turn.js AppDropdown and the per-OS client bubble, js/screen-settings.js's
platform bubble) — while the catalogs already carried the phrase ("by {v1}" in js/lang/ru.js, "от {v1}"). A literal cannot
follow the language selector, so every one of them read English on a Russian page. Measured: the RU subscription page's badges
("FOCSQ by luminescq", 1.8.7 qualification P3-C) and the RU operator app's client dropdown.

The rendered sub page is gated behaviourally by tests/sub_page_render_selftest.py [2]. This one covers the whole class in
source, SPA included, where no browser gate reaches: it scans code (comments masked) for a string literal or a template text
node whose words are exactly "by" — `" by "`, `"by "`, `> by <`.

  [1] the scan reads every shipped front-end file (sub.js, app.js, js/*.js) and finds the translated phrase in use
  [2] no literal "by" author word remains in display text
  [3] the catalogs carry the phrase in both languages: sub.js STR en/ru `by`, js/lang/ru.js "by {v1}"

Hermetic. Run: python3 tests/i18n_by_literal_selftest.py      (0 = pass)
     --perturb   plants the old AppDropdown literal back into a copy of js/turn.js and expects RED on [2] ("PERTURB OK", exit 0).
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def mask_comments(src):
    """Blank out // and /* */ comments without moving any offsets (strings and template literals are left alone)."""
    out, i, n = list(src), 0, len(src)
    quote = None
    while i < n:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2; continue
            if c == quote:
                quote = None
            i += 1; continue
        if c in "\"'`":
            quote = c; i += 1; continue
        if src.startswith("//", i) and (i == 0 or src[i - 1] not in ":\\"):
            j = src.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j): out[k] = " "
            i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n": out[k] = " "
            i = j; continue
        i += 1
    return "".join(out)

files = [os.path.join(ROOT, "sub.js"), os.path.join(ROOT, "app.js")] + sorted(glob.glob(os.path.join(ROOT, "js", "*.js")))
# a space on at least one side: the bare "by" is the catalog KEY sub.js looks the phrase up by (t("by")), not display text
LIT = re.compile(r'''"(?:\s+by\s*|\s*by\s+)"|'(?:\s+by\s*|\s*by\s+)'|>\s*by\s*<''')
hits, uses, srcs = [], 0, {}
for f in files:
    src = open(f, encoding="utf-8").read()
    if PERTURB and f.endswith(os.path.join("js", "turn.js")):
        anchor = '<span class="app-by">${Trich("by {v1}", { v1: html`<span class="app-by-who" style=${"color:" + o.color}>${o.author || "—"}</span>` })}</span>'
        if anchor not in src:
            print("PERTURB FAILED — the AppDropdown anchor is gone, so the old literal cannot be planted back")
            sys.exit(1)
        src = src.replace(anchor, '<span class="app-by"> by </span><span style=${"color:" + o.color}>${o.author || "—"}</span>')
    srcs[f] = src
    code = mask_comments(src)
    uses += len(re.findall(r'Trich\("by \{v1\}"|t\("by"\)', code))
    for m in LIT.finditer(code):
        ln = code.count("\n", 0, m.start()) + 1
        hits.append("%s:%d %s" % (os.path.relpath(f, ROOT), ln, m.group(0)))

check("[1] the scan read the shipped front-end files", len(files) > 20 and os.path.join(ROOT, "sub.js") in srcs, len(files))
check("[1] …and sees the translated phrase in use (sub.js t(\"by\") + the operator app's Trich(\"by {v1}\"))", uses >= 5, uses)
check("[2] no literal English \"by\" author word in display text", not hits, hits)
sub = srcs[os.path.join(ROOT, "sub.js")]
check("[3] sub.js STR carries `by` in English and Russian", ' by: " by {author}"' in sub and ' by: " от {author}"' in sub)
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("[3] js/lang/ru.js translates \"by {v1}\"", '"by {v1}": "от {v1}"' in ru)

print()
if PERTURB:
    ok = bool(FAILS)
    print("PERTURB OK — %d check(s) went red" % len(FAILS) if ok else "PERTURB FAILED — the literal was planted back and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
