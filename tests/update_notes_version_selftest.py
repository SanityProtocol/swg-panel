#!/usr/bin/env python3
"""Self-test: the update bubble never shows another release's notes under the new version's heading.

1.8.8's publish (2026-09-29): an operator's 1.8.7 panel read "What's new in 1.8.8-beta" above 1.8.7's notes and date.
The version check pins VERSION and CHANGELOG to one commit only when the GitHub API answers; when it does not, both come
from the mutable ref, and right after a push raw's CDN serves a fresh VERSION with a stale CHANGELOG. The guard refused
the stale notes — and kept "the last good ones", which were the previous release's.

Real functions: the panel's `_check_latest_remote` and `_latest_notes`, with the network answered by a stub of
`urllib.request.urlopen` (API refused → the ref fallback; raw returns what the CDN would).

  [1] a new VERSION with a stale CHANGELOG: the previous release's notes are not shown under it
  [2] the next check, CDN caught up: this version's notes and date
  [3] a failed changelog fetch does not blank this version's good notes
  [4] another language: a stale fetch returns nothing, not the previous release's notes

Run: python3 tests/update_notes_version_selftest.py      --plant keepold | rucache   (exit 0 when caught)
"""
import importlib.machinery, importlib.util, io, os, sys, tempfile, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"keepold": ("[1]", "            elif LATEST_REMOTE.get(\"notes_ver\") != v:", "            elif False:"),
          "rucache": ("[4]", "    if cur and _short_ver(_cv or \"\") != cur:", "    if False:")}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


path = os.path.abspath(SERVER)
if PLANT:
    _s, old, new = PLANTS[PLANT]
    src = open(path).read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    path = os.path.join(tempfile.mkdtemp(), "planted-server.py")
    open(path, "w").write(src.replace(old, new, 1))
loader = importlib.machinery.SourceFileLoader("swgpanel_notes", path)
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_notes", loader))
try:
    loader.exec_module(m)
except SystemExit:
    pass

OLD = b"# Changelog\n\n## [1.8.7-beta] \xe2\x80\x94 2026-09-17\n\n### Added\n\n- **Networks behind a device.** old notes\n"
NEW = b"# Changelog\n\n## [1.8.8-beta] \xe2\x80\x94 2026-09-29\n\n### Added\n\n- **AmneziaWG 3.1.** new notes\n"
NET = {"version": b"1.8.8-beta\n", "changelog": OLD, "changelog_ok": True}


class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _urlopen(req, *a, **k):
    u = req.full_url if hasattr(req, "full_url") else str(req)
    if "api.github.com" in u:
        raise urllib.error.HTTPError(u, 403, "rate limit exceeded", {}, None)   # no sha, no API door
    if "raw.githubusercontent.com" in u and "/VERSION" in u:
        return _R(NET["version"])
    if "raw.githubusercontent.com" in u and "CHANGELOG" in u:
        if not NET["changelog_ok"]:
            raise urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
        return _R(NET["changelog"])
    raise AssertionError("unexpected dial " + u)


urllib.request.urlopen = _urlopen
m._http_retry = lambda fn, **k: fn()
m.REMOTE_VERSION_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION"
m.REMOTE_CHANGELOG_URL = m.REMOTE_VERSION_URL.rsplit("/", 1)[0] + "/CHANGELOG.md"
m.LATEST_REMOTE.update(version="1.8.7-beta", date="2026-09-17", notes=["Networks behind a device. old notes"], notes_ver="1.8.7-beta")
m._REF_SHA.update(at=0, ref="", sha="", bad_at=0)

SECTION[0] = "[1]"
print("\n[1] fresh VERSION, stale CHANGELOG (the API refused, the CDN lagged)")
m._check_latest_remote(budget=20)
check("the new version is announced", m.LATEST_REMOTE.get("version") == "1.8.8-beta", m.LATEST_REMOTE.get("version"))
d, n = m._latest_notes("en")
check("…with no notes, not 1.8.7's", n == [] and d == "", (d, n))

SECTION[0] = "[2]"
print("\n[2] the next check, the CDN caught up")
NET["changelog"] = NEW
m._REF_SHA.update(bad_at=0)
m._check_latest_remote(budget=20)
d, n = m._latest_notes("en")
check("1.8.8's notes and date", d == "2026-09-29" and n and "AmneziaWG 3.1" in n[0], (d, n))

SECTION[0] = "[3]"
print("\n[3] a failed changelog fetch keeps this version's notes")
NET["changelog_ok"] = False
m._REF_SHA.update(bad_at=0)
m._check_latest_remote(budget=20)
d, n = m._latest_notes("en")
check("still 1.8.8's", d == "2026-09-29" and n and "AmneziaWG 3.1" in n[0], (d, n))

SECTION[0] = "[4]"
print("\n[4] Russian: a stale fetch gives nothing")
NET.update(changelog_ok=True, changelog=OLD.replace(b"# Changelog", "# История изменений".encode()))
m._LATEST_NOTES.clear()
d, n = m._latest_notes("ru")
check("no notes rather than 1.8.7's", n == [] and d == "", (d, n))
NET["changelog"] = NEW
d, n = m._latest_notes("ru")
check("…and once the CDN has 1.8.8's changelog, they come (not an hour's cache of nothing)", d == "2026-09-29" and n, (d, n))

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
