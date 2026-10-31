#!/usr/bin/env python3
"""Self-test (G0, docs/MOBILE-PLAN.md § Gates): the phone stylesheet cannot style a desktop.

m/m.css is loaded on every page, desktop included. What keeps a desktop byte-identical is its SHAPE: with comments
stripped, the file is ONE rule, html[data-ui="m"] { … } (everything else nested inside it), plus nothing at the top level
but @keyframes m-*, which style nothing by themselves. index.html's bootstrap sets data-ui="m" only on a phone, so no
selector of the file can match on a desktop. And index.html must load it as a plain render-blocking stylesheet right after
app.css: no media= flip (a sheet whose media did not match at parse time may paint the desktop layout first on a phone).

  [1] m/m.css: one html[data-ui="m"] block, then only @keyframes m-*; the block is not empty
  [2] index.html: <link rel="stylesheet" href="m/m.css"> straight after app.css's, no media=; the bootstrap sets data-ui="m"
      only after testing CSS nesting

Run: python3 tests/mobile_css_shape_selftest.py    (0 = pass)
     --plant unscoped   a rule appended outside the block; expects RED
     --plant twoblocks  a second html[data-ui="m"] block; expects RED
     --plant keyframes  an @keyframes not named m-*; expects RED
     --plant media      an @media wrapping the block; expects RED
     --plant linkmedia  the link given media="not all"; expects RED
     --plant nonest     the bootstrap no longer tests nesting; expects RED
"""
import os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PLANTS = ("unscoped", "twoblocks", "keyframes", "media", "linkmedia", "nonest")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
assert PLANT in ("",) + PLANTS, "unknown plant %r" % PLANT

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

css = open(os.path.join(ROOT, "m", "m.css"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
if PLANT == "unscoped":
    css += "\n.sheet{width:100%}\n"
elif PLANT == "twoblocks":
    css += '\nhtml[data-ui="m"] { & .x { color: red; } }\n'
elif PLANT == "keyframes":
    css += "\n@keyframes rise{from{opacity:0}to{opacity:1}}\n"
elif PLANT == "media":
    css = "@media (max-width: 9999px) {\n" + css + "\n}\n"
elif PLANT == "linkmedia":
    a = '<link rel="stylesheet" href="m/m.css">'
    assert html.count(a) == 1, "plant anchor"
    html = html.replace(a, '<link rel="stylesheet" href="m/m.css" media="not all">')
elif PLANT == "nonest":
    a = 'CSS.supports("selector(&)")'
    assert html.count(a) == 1, "plant anchor"
    html = html.replace(a, "true")


def top_level(src):
    """[(prelude, body)] of the top-level rules, comments stripped, strings respected."""
    out, i, n, depth, start, pre = [], 0, len(src), 0, 0, ""
    quote = None
    while i < n:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2; continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        elif c == "{":
            if depth == 0:
                pre, start = src[start:i], i + 1
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return out + [("<unbalanced }>", "")]
            if depth == 0:
                out.append((re.sub(r"/\*.*?\*/", "", pre, flags=re.S).strip(), src[start:i]))
                start = i + 1
        elif c == ";" and depth == 0:
            out.append((re.sub(r"/\*.*?\*/", "", src[start:i], flags=re.S).strip(), None))   # a bare statement (@import …)
            start = i + 1
        i += 1
    rest = re.sub(r"/\*.*?\*/", "", src[start:], flags=re.S).strip()
    if depth or rest:
        out.append(("<trailing: %s>" % rest[:60], None))
    return out


print("[1] m/m.css is one rule scoped to the phone UI")
rules = top_level(css)
scoped = [r for r in rules if r[0] == 'html[data-ui="m"]']
others = [r[0] for r in rules if r[0] != 'html[data-ui="m"]' and not re.fullmatch(r"@keyframes\s+m-[\w-]+", r[0])]
check('[1] exactly one html[data-ui="m"] block', len(scoped) == 1, "%d blocks" % len(scoped))
check("[1] nothing else at the top level but @keyframes m-*", not others, others[:4])
check("[1] the block holds the phone's rules", bool(scoped) and scoped[0][1] is not None and scoped[0][1].count("{") >= 20,
      "%d nested rules" % (scoped[0][1].count("{") if scoped and scoped[0][1] else 0))

print("\n[2] index.html loads it as a plain stylesheet, after app.css, and marks a phone only where nesting works")
links = re.findall(r"<link\b[^>]*>", html)
sheets = [l for l in links if 'rel="stylesheet"' in l]
i_app = next((k for k, l in enumerate(sheets) if 'href="app.css"' in l), -1)
i_m = next((k for k, l in enumerate(sheets) if 'href="m/m.css"' in l), -1)
check("[2] m/m.css is linked right after app.css", i_app >= 0 and i_m == i_app + 1, sheets)
check("[2] with no media= on it", i_m >= 0 and "media=" not in sheets[i_m], sheets[i_m] if i_m >= 0 else "")
boot = next((s for s in re.findall(r"<script>(.*?)</script>", html, re.S) if "dataset.ui" in s), "")
check('[2] the bootstrap sets data-ui="m"', 'd.dataset.ui="m"' in boot)
check("[2] …only after testing CSS nesting", 'CSS.supports("selector(&)")' in boot
      and boot.index('CSS.supports("selector(&)")') < boot.index('d.dataset.ui="m"'))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS[:6])))
    sys.exit(1)
print("ALL PASS")
