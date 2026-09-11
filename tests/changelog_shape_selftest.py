#!/usr/bin/env python3
"""Self-test: the published changelogs still have the shape a reader arrives expecting.

⚠️ THIS EXISTS BECAUSE A SCRIPTED EDIT DELETED BOTH FILE TITLES AND NOBODY NOTICED FOR THREE COMMITS.
A helper sliced the file at the release heading —

    head = s.index("## [1.8.6-beta]"); body, rest = s[head:tail], s[tail:]
    open(path, "w").write(body + rest)          # s[:head] is gone

— so `# Changelog` / `# История изменений`, the paragraph under it and the EN<->RU cross-link vanished.
Both files then opened straight on a release heading and would have rendered on GitHub with no title.
`readme-audit.mjs` cannot see this: it scores What's-new bullet VOCABULARY against the release sections and
has no opinion about the file having a heading at all. A file that is published and has a required shape
needs a gate for the SHAPE, not only for the contents. [[changelog-edit-ate-the-title]]

It also checks the two languages stay structurally parallel — same releases, same section count per
release — because the other half of that incident was bullets moving between sections in one file only.

Run: python3 tests/changelog_shape_selftest.py    (0 = pass)
     --perturb  lops the header off a copy, the way the helper did, and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

FILES = {
    "CHANGELOG.md":    {"title": "# Changelog",         "other": "CHANGELOG.ru.md",
                        "secs": ("Added", "Changed", "Fixed", "Removed", "Security")},
    "CHANGELOG.ru.md": {"title": "# История изменений", "other": "CHANGELOG.md",
                        "secs": ("Добавлено", "Изменено", "Исправлено", "Удалено", "Безопасность")},
}
src = {}
for f in FILES:
    t = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if PERTURB:                       # exactly what the helper did: drop everything above the first release
        t = t[t.index("## ["):]
    src[f] = t

print("[1] each file still introduces itself")
for f, meta in FILES.items():
    t = src[f]
    check("%s opens with its title" % f, t.lstrip().startswith(meta["title"]),
          "starts with %r" % t.lstrip()[:40])
    # the paragraph under the title: present, and before the first release heading
    head = t[:t.index("## [")] if "## [" in t else t
    check("…with an intro above the first release", len(head.strip().splitlines()) >= 3,
          "%d line(s) above the first release heading" % len(head.strip().splitlines()))
    check("…and a link to the other language", meta["other"] in head,
          "no link to %s above the first release" % meta["other"])

print("\n[2] the releases are well formed, newest first")
rel = {}
for f in FILES:
    hits = re.findall(r"(?m)^## \[([^\]]+)\] — (\d{4}-\d{2}-\d{2})\s*$", src[f])
    rel[f] = hits
    check("%s has dated release headings" % f, len(hits) >= 2, hits[:3])
    vers = [v for v, _ in hits]
    check("…no release appears twice", len(vers) == len(set(vers)),
          [v for v in vers if vers.count(v) > 1])
    dates = [d for _, d in hits]
    check("…and they run newest-first", dates == sorted(dates, reverse=True), dates[:4])

print("\n[3] ⚠️ …and the two languages describe the SAME releases")
# One file losing a release, or gaining one the other does not have, is the same silent-truncation class.
check("both files list the same versions, in the same order",
      [v for v, _ in rel["CHANGELOG.md"]] == [v for v, _ in rel["CHANGELOG.ru.md"]],
      "%s vs %s" % ([v for v, _ in rel["CHANGELOG.md"]][:4], [v for v, _ in rel["CHANGELOG.ru.md"]][:4]))
check("…and give each one the same date",
      [d for _, d in rel["CHANGELOG.md"]] == [d for _, d in rel["CHANGELOG.ru.md"]])

print("\n[4] the newest release has sections, and both languages have as many")
def sections(text, ver, names):
    blk = text[text.index("## [%s]" % ver):]
    nxt = blk.find("\n## [", 1)
    blk = blk[:nxt] if nxt != -1 else blk
    found = re.findall(r"(?m)^### (\S+)\s*$", blk)
    bullets = {s: 0 for s in found}
    cur = None
    for line in blk.splitlines():
        m = re.match(r"^### (\S+)\s*$", line)
        if m:
            cur = m.group(1); continue
        if cur and line.startswith("- **"):
            bullets[cur] += 1
    return found, bullets

top = rel["CHANGELOG.md"][0][0] if rel["CHANGELOG.md"] else None
check("there is a newest release to inspect", bool(top), top)
if top:
    shape = {}
    for f, meta in FILES.items():
        found, bullets = sections(src[f], top, meta["secs"])
        shape[f] = (found, bullets)
        check("%s — %s has at least one section" % (f, top), len(found) >= 1, found)
        check("…every section is one this project uses", all(x in meta["secs"] for x in found),
              [x for x in found if x not in meta["secs"]])
        check("…and none of them is empty", all(v > 0 for v in bullets.values()), bullets)
    check("⚠️ …and the two languages have the SAME number of sections",
          len(shape["CHANGELOG.md"][0]) == len(shape["CHANGELOG.ru.md"][0]),
          "%s vs %s" % (shape["CHANGELOG.md"][0], shape["CHANGELOG.ru.md"][0]))
    check("⚠️ …with the same number of entries in each",
          list(shape["CHANGELOG.md"][1].values()) == list(shape["CHANGELOG.ru.md"][1].values()),
          "%s vs %s" % (shape["CHANGELOG.md"][1], shape["CHANGELOG.ru.md"][1]))

print("\n[5] …and the version it leads with is the one this tree builds")
ver = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
check("VERSION matches the newest changelog release", top == ver, "VERSION=%s, changelog=%s" % (ver, top))

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: the title and the cross-link are gone again" % len(FAILS))
          if ok else "PERTURB FAILED — the header was lopped off and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
