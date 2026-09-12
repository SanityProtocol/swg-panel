#!/usr/bin/env python3
"""Self-test for UPDATE-RESILIENCE Phase 0a — the second door onto the version check.

`raw.githubusercontent.com` resolves to Fastly (185.199.108-111.x), which is the range actually filtered in
the networks this product is most used in. `api.github.com` is Azure, and in those same networks it is
frequently not filtered. Same repo, same commit, same TLS — so reading the file through the API's contents
endpoint when raw cannot be had adds no party to trust, which is why it ships ahead of the signing work
every other mirror would need first (docs/UPDATE-RESILIENCE-PLAN.md, Phase 0a).

The master case is what makes it urgent: a `master` is the panel AND a node on one box, so when that box is
the filtered one there is no healthy control plane to fall back on.

Four things have to hold, and each is a place a plausible implementation goes wrong:

  1. THE URL IS TRANSLATED, NOT GUESSED. owner/repo/ref/path come out of the raw URL; the `?cb=` buster is
     dropped, because it exists to fight raw's CDN and the API is not that CDN. A URL that is NOT github raw
     — an operator's own `SWG_LATEST_URL` mirror — has no second door, and inventing one would be inventing
     a source.
  2. ⚠️ THE FALLBACK IS NOT TRIED WHEN RAW WORKS. This is the whole cost control. The API allows 60
     unauthenticated requests an hour per address, shared with `_resolve_release_sha` and the routing
     catalogue builder; a fallback that fires on every check instead of every failure triples the spend for
     nothing and can exhaust the quota that the failure path depends on.
  3. ⚠️ WHEN BOTH DOORS FAIL, THE RAW ERROR IS WHAT SURFACES. Raw is the primary source and its cause is the
     one an operator can act on — "the connection was reset" names a middlebox. Report the API's failure
     instead and every blocked box would be told its problem is our own API quota.
  4. IT IS BOUNDED BY THE SAME DEADLINE. A second door opened after the answer was due helps nobody, and an
     operator is watching a spinner.

Hermetic: no network. `urllib.request.urlopen` is stubbed and every call recorded, so "did it ask the API?"
is answered by what was actually dialled rather than by whether the result looked right.

Run: python3 tests/update_api_fallback_selftest.py      (0 = pass)
     --perturb   removes the fallback at its source (`alt = _api_contents_url(url)` → `alt = ""`) and
                 expects RED on [3] and [7] — the checks that say a blocked box recovers.
"""
import importlib.machinery, importlib.util, errno, io, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# The perturbation is applied to the SOURCE rather than by stubbing the helper: what it removes is the
# decision to consult the second door at all, and a stub would prove only that the stub works. The anchor is
# asserted present exactly once — an anchor that has drifted would perturb NOTHING and report a clean pass
# over an untested fix.
_src = open(PANEL, encoding="utf-8").read()
if PERTURB:
    _anchor = "    alt = _api_contents_url(url)\n"
    assert _src.count(_anchor) == 1, "perturbation anchor drifted (%d hits) — fix the test" % _src.count(_anchor)
    _src = _src.replace(_anchor, '    alt = ""\n', 1)

os.environ.setdefault("SWG_PANEL_FLEET", "/dev/null")
_spec = importlib.util.spec_from_loader("swgp", importlib.machinery.SourceFileLoader("swgp", PANEL))
m = importlib.util.module_from_spec(_spec)
exec(compile(_src, PANEL, "exec"), m.__dict__)

RAW = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION"
SHAURL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/abc1234/VERSION?cb=99"

# ── [1] the URL is translated, not guessed ───────────────────────────────────────────────────────────────
got = m._api_contents_url(SHAURL)
check("[1] raw URL → API contents URL, ref preserved",
      got == "https://api.github.com/repos/SanityProtocol/swg-panel/contents/VERSION?ref=abc1234", got)
check("[1b] the ?cb= CDN buster is dropped", "cb=" not in got, got)
check("[1c] a nested path survives",
      m._api_contents_url("https://raw.githubusercontent.com/o/r/main/docs/a/b.md")
      == "https://api.github.com/repos/o/r/contents/docs/a/b.md?ref=main")
check("[1d] a non-github mirror gets NO invented second door",
      m._api_contents_url("https://mirror.example.org/swg/VERSION") == "",
      m._api_contents_url("https://mirror.example.org/swg/VERSION"))

# ── the stub: every dialled URL recorded ─────────────────────────────────────────────────────────────────
class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

dialled = []
def stub(raw_ok=True, api_ok=True, body=b"1.9.0-beta\n"):
    def f(req, *a, **k):
        u = req.full_url if hasattr(req, "full_url") else str(req)
        dialled.append(u)
        if "api.github.com" in u and "/contents/" in u:
            if not api_ok:
                raise urllib.error.HTTPError(u, 403, "rate limit exceeded", {}, None)
            return _R(body)
        if "raw.githubusercontent.com" in u:
            if not raw_ok:
                raise urllib.error.URLError(ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"))
            return _R(body)
        if "api.github.com" in u:                      # the sha resolve — always fine here
            return _R(b"abc1234def5678")
        raise AssertionError("unexpected dial " + u)
    return f

def run(fn, **kw):
    dialled.clear()
    urllib.request.urlopen = stub(**kw)
    try:
        return fn()
    finally:
        urllib.request.urlopen = _real

_real = urllib.request.urlopen
api_hits = lambda: len([u for u in dialled if "/contents/" in u])

# ── [2] raw works → the API is NEVER consulted (the whole cost control) ──────────────────────────────────
out = run(lambda: m._gh_get(RAW, {"User-Agent": "swg-panel"}, 64, time.time() + 20))
check("[2] raw succeeds → correct bytes", out.strip() == b"1.9.0-beta", out)
check("[2b] ⚠️ raw succeeds → API not dialled at all", api_hits() == 0, dialled)

# ── [3] raw blocked → the API door carries it ────────────────────────────────────────────────────────────
try:
    out = run(lambda: m._gh_get(RAW, {"User-Agent": "swg-panel"}, 64, time.time() + 20), raw_ok=False)
    ok3, why3 = out.strip() == b"1.9.0-beta", out
except Exception as e:
    ok3, why3 = False, "raised %s" % type(e).__name__
check("[3] raw blocked → recovered through the API door", ok3, why3)
check("[3b] …and it really did dial the API", api_hits() >= 1, dialled)

# ── [4] both doors shut → the RAW cause surfaces, not the API's ──────────────────────────────────────────
try:
    run(lambda: m._gh_get(RAW, {"User-Agent": "swg-panel"}, 64, time.time() + 20), raw_ok=False, api_ok=False)
    check("[4] both shut → raises", False, "returned instead of raising")
except Exception as e:
    said = m._why_fetch_failed(RAW, e)["error"]
    check("[4] both shut → the RAW cause is what surfaces", "reset" in said, said)
    check("[4b] …and it names raw's host, not the API's",
          "raw.githubusercontent.com" in said and "api.github.com" not in said, said)

# ── [5] no budget left → the second door is not opened ───────────────────────────────────────────────────
run(lambda: None)
try:
    run(lambda: m._gh_get(RAW, {"User-Agent": "swg-panel"}, 64, time.time() - 1), raw_ok=False)
except Exception:
    pass
check("[5] deadline already passed → API not dialled", api_hits() == 0, dialled)

# ── [6] a mirror source falls back to nothing (no invented door) ─────────────────────────────────────────
MIRROR = "https://mirror.example.org/swg/VERSION"
def _mirror_stub(req, *a, **k):
    u = req.full_url if hasattr(req, "full_url") else str(req)
    dialled.append(u)
    raise urllib.error.URLError(ConnectionResetError(errno.ECONNRESET, "reset"))
dialled.clear(); urllib.request.urlopen = _mirror_stub
try:
    m._gh_get(MIRROR, {"User-Agent": "swg-panel"}, 64, time.time() + 20)
except Exception:
    pass
urllib.request.urlopen = _real
check("[6] a non-github source dials only itself",
      all("github" not in u for u in dialled) and len(dialled) >= 1, dialled)

# ── [7] end to end: the CHECK itself survives a blocked raw ──────────────────────────────────────────────
m._REF_SHA.update(at=0, bad_at=0)
m.LATEST_REMOTE["version"] = None
ok7 = run(lambda: m._check_latest_remote(budget=20), raw_ok=False)
check("[7] ⚠️ blocked raw → the version check still reaches an answer", bool(ok7), m.LATEST_REMOTE.get("why"))
check("[7b] …and stored a real version", m.LATEST_REMOTE.get("version") == "1.9.0-beta",
      m.LATEST_REMOTE.get("version"))

# ── [8] the changelog fetch got the same door ────────────────────────────────────────────────────────────
NOTES = b"## [1.9.0-beta] - 2026-09-12\n\n### Fixed\n\n- **A thing.** It was fixed.\n"
cv, cdate, cnotes = run(lambda: m._fetch_latest_changelog(sha="abc1234"), raw_ok=False, body=NOTES)
check("[8] blocked raw → changelog notes still arrive", cv == "1.9.0-beta" and len(cnotes) == 1,
      (cv, cdate, cnotes))

print()
if FAILS:
    print("FAILED (%d): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all checks passed")
