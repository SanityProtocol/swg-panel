#!/usr/bin/env python3
"""Self-test: no script or stylesheet the panel or the subscription page serves has a name a tracker blocker blocks.

⚠️ THIS EXISTS BECAUSE 1.8.9 SHIPPED js/logview.js. EasyPrivacy — on by default in uBlock Origin, AdGuard and Brave —
carries the rule `/logview.js`, so for anyone with one of those the module never loaded and the panel stayed blank
("The panel's files didn't load … js/logview.js"). The server answered 200 the whole time; only the browser refused it.
It is js/journal.js now.

The block lists themselves are not copied here (their licences, and they change weekly). What they block by NAME is
tracker-shaped words — log, track, stat, analytics, beacon, pixel, metrics, telemetry, collect, counter, banner, ad(s),
fingerprint — so a served .js / .css whose name holds one is refused here, whatever a list says today. A name is split
into words on - _ . and camelCase (trackerList → tracker, list; an acronym ends before the next word: UIStats → ui,
stats); the strongest stems (track, analytic, telemetr, beacon,
logview, …) are refused inside a word too (trackerlist), the short ones (log, ad, stat) only as whole words, so
turn-catalog.js and dialog names stay clean. A name a list does not block but that trips this is listed in ALLOW, with why.

Run: python3 tests/served_names_selftest.py    (0 = pass)
     --plant logview   serves the 1.8.9 name again; expects RED
     --plant nojs      the scan skips js/ (a blind gate); expects RED
     --plant joined    serves js/trackerList.js (camelCase, one word lowercased); expects RED
     --plant stem      serves js/trackerlist.js (one all-lowercase word: only the in-word stem check sees it); expects RED
     --plant acronym   serves js/UIStats.js (an acronym before the word); expects RED
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANTS = {"logview": "serve js/logview.js again", "nojs": "skip js/ in the scan", "joined": "serve js/trackerList.js",
          "stem": "serve js/trackerlist.js", "acronym": "serve js/UIStats.js"}
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
assert PLANT in ("",) + tuple(PLANTS), "unknown plant %r" % PLANT

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

# A name's words (split on - _ . and case) that a blocker list matches as a path segment or filename.
BAD = re.compile(r"^(?:log|logs|logger|logging|logview|syslog|track|tracker|tracking|stat|stats|statistic|statistics|"
                 r"analytic|analytics|beacon|pixel|metric|metrics|telemetry|collect|collector|counter|banner|ad|ads|"
                 r"advert|adverts|fingerprint|spy)$")
STEM = re.compile(r"track|analytic|telemetr|beacon|logview|syslog|fingerprint|adserv|advert|pixel|metric")
ALLOW = {}   # "<file name>": "why a list does not block it" — none today

def served():
    """Every .js / .css the two servers hand a browser: the root assets, js/ (with js/lang/), vendor/."""
    out = [f for f in os.listdir(ROOT) if f.endswith((".js", ".css")) and os.path.isfile(os.path.join(ROOT, f))]
    for d in ("js", "vendor"):
        if d == "js" and PLANT == "nojs":
            continue
        for root, _dirs, files in os.walk(os.path.join(ROOT, d)):
            out += [os.path.relpath(os.path.join(root, f), ROOT) for f in files if f.endswith((".js", ".css"))]
    if PLANT == "logview":
        out.append("js/logview.js")
    if PLANT in ("joined", "stem", "acronym"):
        out.append(PLANTS[PLANT].split()[-1])
    return sorted(out)

names = served()
print("[1] the served scripts and stylesheets (%d)" % len(names))
check("[1] the scan sees the SPA's modules (js/ has 30+ of them)", sum(n.startswith("js/") for n in names) >= 30,
      "%d under js/" % sum(n.startswith("js/") for n in names))
for n in names:
    base = os.path.basename(n)
    stem = os.path.splitext(base)[0]
    words = [w.lower() for w in re.split(r"[-_.]|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", stem) if w]
    hit = [w for w in words if BAD.match(w) or STEM.search(w)]
    if hit and base not in ALLOW:
        check("[1] %s has no tracker-shaped word" % n, False, "%s — a blocker list refuses names like it" % hit)
print("  PASS [1] no other name holds one" if not FAILS else "")

print("\n[2] index.html preloads only files that exist")
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
pre = re.findall(r'<link rel="modulepreload" href="([^"?]+)', html)
check("[2] index.html preloads the SPA's modules", len(pre) >= 20, "%d preloads" % len(pre))
missing = [p for p in pre if not os.path.isfile(os.path.join(ROOT, p))]
check("[2] every preloaded module is on disk", not missing, missing)
check("[2] the live log viewer is preloaded under its new name", "js/journal.js" in pre and "js/logview.js" not in pre)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS[:6])))
    sys.exit(1)
print("ALL PASS")
