#!/usr/bin/env python3
"""Self-test: What's new is read on demand and by version (1.8.9) — the panel's half.

1.8.8's publish: raw's CDN served a fresh VERSION with a stale CHANGELOG, and the bubble put 1.8.7's notes under
"What's new in 1.8.8-beta". The hourly check no longer fetches notes at all; /api/changelog is read when a bubble opens,
with the badge's version as `want`, and a cached copy without that version is fetched again (at most once a minute).

Real functions: `_check_latest_remote`, `_changelog_entries`; the network is a stub of urllib.request.urlopen.

  [1] the version check reads VERSION only — no changelog, no GitHub API call (the commit pinning is gone) — and moves
      FORWARD only (a stale CDN edge must not take the badge back)
  [2] a stale copy (no `want` in it) is fetched again — but at most once a minute, not on every open
  [3] a copy that holds `want` is kept for the hour
  [4] /api/state no longer ships notes; /api/changelog passes the badge's version
  [5] a refetch answered 200 by a page with no headings (a captive or block page) keeps the cached entries — it answered []
      and both bubbles showed nothing (q189 PLO-10)

Run: python3 tests/changelog_by_version_selftest.py      --plant backward | keepstale | nowant | blank   (exit 0 when caught)
"""
import importlib.machinery, importlib.util, io, os, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"backward": ("[1]", "            if not LATEST_REMOTE.get(\"version\") or _vtuple(v) >= _vtuple(LATEST_REMOTE[\"version\"]):", "            if True:"),
          "keepstale": ("[2]", "(has or now - cache.get(\"tried\", 0) < CHANGELOG_RETRY_S)", "True"),
          "blank": ("[5]", "    return entries or cache[\"entries\"]", "    return entries"),
          "nowant": ("[4]", "\"entries\": _changelog_entries(_req_lang(), want)}}", "\"entries\": _changelog_entries(_req_lang())}}")}
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
loader = importlib.machinery.SourceFileLoader("swgpanel_cl", path)
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_cl", loader))
try:
    loader.exec_module(m)
except SystemExit:
    pass

OLD = "# Changelog\n\n## [1.8.8-beta] — 2026-09-29\n\n### Added\n\n- **Old.** notes\n\n## [1.8.7-beta] — 2026-09-17\n\n- **Older.**\n"
NEW = "# Changelog\n\n## [1.8.9-beta] — 2026-10-05\n\n### Added\n\n- **New.** notes\n\n" + OLD.split("\n\n", 1)[1]
NET = {"cl": OLD}
dials = []


class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _urlopen(req, *a, **k):
    u = req.full_url if hasattr(req, "full_url") else str(req)
    dials.append(u)
    if "api.github.com" in u:
        raise urllib.error.HTTPError(u, 403, "rate limit", {}, None)
    if "/VERSION" in u:
        return _R(b"1.8.9-beta\n")
    if "CHANGELOG" in u:
        return _R(NET["cl"].encode())
    raise AssertionError("unexpected dial " + u)


urllib.request.urlopen = _urlopen
m._http_retry = lambda fn, **k: fn()
m.REMOTE_VERSION_URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION"
m.REMOTE_CHANGELOG_URL = m.REMOTE_VERSION_URL.rsplit("/", 1)[0] + "/CHANGELOG.md"

SECTION[0] = "[1]"
print("\n[1] the version check")
m._check_latest_remote(budget=20)
check("the new version is known", m.LATEST_REMOTE.get("version") == "1.8.9-beta", m.LATEST_REMOTE)
check("…from VERSION alone: no changelog, no GitHub API call", all("/VERSION" in d for d in dials), dials)
check("…and no notes kept beside it", set(m.LATEST_REMOTE) <= {"version", "checked", "why"}, m.LATEST_REMOTE)
_ver = {"v": b"1.8.8-beta\n"}
_real_open = urllib.request.urlopen
def _stale_version(req, *a, **k):
    u = req.full_url if hasattr(req, "full_url") else str(req)
    return _R(_ver["v"]) if "/VERSION" in u else _real_open(req, *a, **k)
urllib.request.urlopen = _stale_version
m._check_latest_remote(budget=20)
check("a stale CDN edge answering the OLD version next hour does not take the badge back (forward only)",
      m.LATEST_REMOTE.get("version") == "1.8.9-beta", m.LATEST_REMOTE)
_ver["v"] = b"1.9.0-beta\n"; m._check_latest_remote(budget=20)
check("…a newer one still moves it forward", m.LATEST_REMOTE.get("version") == "1.9.0-beta", m.LATEST_REMOTE)
urllib.request.urlopen = _real_open
m.LATEST_REMOTE["version"] = "1.8.9-beta"

SECTION[0] = "[2]"
print("\n[2] a stale copy")
dials.clear()
es = m._changelog_entries("en", "1.8.9-beta")
check("the stale copy has no 1.8.9 (nothing else is dressed up as it)", es and es[0]["version"] == "1.8.8-beta"
      and not any(e["version"] == "1.8.9-beta" for e in es), es)
m._changelog_entries("en", "1.8.9-beta"); m._changelog_entries("en", "1.8.9-beta")
check("opened twice more within the minute → not fetched again", sum("CHANGELOG" in d for d in dials) == 1, dials)
NET["cl"] = NEW
m._CHANGELOG_CACHE["en"]["tried"] -= 61
es = m._changelog_entries("en", "1.8.9-beta")
check("a minute on → fetched again, and 1.8.9 is there", any(e["version"] == "1.8.9-beta" and e["date"] == "2026-10-05" for e in es), es)

SECTION[0] = "[3]"
print("\n[3] a copy that has it")
dials.clear()
m._CHANGELOG_CACHE["en"]["tried"] -= 600
m._changelog_entries("en", "1.8.9-beta")
check("kept — no fetch ten minutes later", not dials, dials)

SECTION[0] = "[4]"
print("\n[4] the wire")
src = open(path).read()
check("/api/state ships no notes any more", "latest_remote_notes" not in src and "latest_remote_date" not in src)
check("/api/changelog passes the badge's version", "\"entries\": _changelog_entries(_req_lang(), want)}}" in src
      and "want = _short_ver((qs.get(\"want\")" in src)

SECTION[0] = "[5]"
print("\n[5] a refetch answered by a page with no headings")
m._CHANGELOG_CACHE["en"] = {"at": int(time.time()), "tried": 0, "entries": [{"version": "1.8.8-beta", "date": "", "notes": ["x"]}]}
NET["cl"] = "<html><body>Access restricted by your provider</body></html>"
m._CHANGELOG_CACHE["en"]["tried"] -= 61
es = m._changelog_entries("en", "1.8.9-beta")                # wants the badge's version, the copy lacks it → refetched
check("the cached entries are kept and answered, not []", [e["version"] for e in es] == ["1.8.8-beta"], es)

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
