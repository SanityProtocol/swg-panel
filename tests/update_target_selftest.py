#!/usr/bin/env python3
"""Self-test — WHICH VERSION A NODE IS BROUGHT TO, and why the latest release alone is the wrong answer.

`bootstrap.sh` deliberately installs a branch or a tag, and 1.8.6 adds two mechanisms whose only job is to
keep such a box updating ALONG that branch: the panel's wrapper bakes the ref, and the node records
`update_ref`. But the target both the fleet cascade and the per-node "outdated" flag measured against was
`LATEST_REMOTE` — what is published on `main` — falling back to the panel only when the remote check had
not run.

So on a fleet tracking a branch the machinery was inert. MEASURED on the qualification fleet: the panel had
updated itself to 1.8.6-beta along dev, three nodes were still on 1.8.5-beta, and `/api/host/update`
answered `"already current": ["nixos", "svo-im", "hel-fresh"]` — the exact split `_cascade_node_updates`'s
own docstring says it exists to prevent ("a fleet left on the old version").

⚠️ TWO READERS, ONE YARDSTICK. The cascade and the UI flag are different code paths and both must use it,
or the panel stages an update for a node it is simultaneously drawing as current.

⚠️ AND IT MUST NEVER BECOME A DOWNGRADE. Taking the higher of the two only ever raises the target, and both
readers test strictly-older — including the docker case where a node legitimately runs ahead of a panel
whose CI image lags.

Run: python3 tests/update_target_selftest.py      (0 = pass)
     --perturb   restores `LATEST_REMOTE or panel` and expects RED.
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

_SRC = open(PANEL, encoding="utf-8").read()
_ANCH = '    return _rel if _vtuple(_rel) >= _vtuple(_pan) else _pan'
assert _SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    _SRC = _SRC.replace(_ANCH, '    return _rel')          # the shipped behaviour: the release, full stop
    _fd, PANEL = tempfile.mkstemp(suffix=".py", prefix="upd-target-", dir=HERE)
    os.write(_fd, _SRC.encode()); os.close(_fd)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m

P = _load(PANEL, "swgpanel")
if PERTURB:
    os.unlink(PANEL)

def target(release, panel):
    P.LATEST_REMOTE.clear(); P.LATEST_REMOTE.update({"version": release} if release else {})
    P.VERSIONS["panel"] = panel
    return P._update_target()

print("[1] the target is the HIGHER of the latest release and the panel's own version")
cases = [
    # release        panel          want          why
    ("1.8.7-beta", "1.8.6-beta", "1.8.7-beta", "a real release is out — that is the target"),
    ("1.8.5-beta", "1.8.6-beta", "1.8.6-beta", "⚠️ the fleet case: the panel is ahead of main, on a branch"),
    ("1.8.6-beta", "1.8.6-beta", "1.8.6-beta", "in step"),
    ("",           "1.8.6-beta", "1.8.6-beta", "the remote check has not run yet"),
    ("1.8.7-beta", "",           "1.8.7-beta", "the panel does not know its own version"),
]
for rel, pan, want, why in cases:
    got = target(rel, pan)
    check("release=%-11r panel=%-11r -> %-11r  (%s)" % (rel or "-", pan or "-", want, why), got == want, got)

print("\n[2] TWO READERS, ONE YARDSTICK — the cascade and the UI flag must not disagree")
src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("the cascade uses the shared target", "    target = _update_target()" in src)
for field in ("outdated", "ahead", "latest"):
    check("the `%s` the UI reads uses it too" % field,
          ('"%s": _ver_behind(snap.get("noded_version"), _update_target())' % field) in src
          or ('"%s": _ver_ahead(snap.get("noded_version"), _update_target())' % field) in src
          or ('"%s": _update_target()' % field) in src)
check("nothing computes the old expression by hand any more",
      'LATEST_REMOTE.get("version") or VERSIONS.get("panel")' not in src.replace(
          '_rel = LATEST_REMOTE.get("version") or ""', ""),
      [l.strip()[:90] for l in src.splitlines() if 'LATEST_REMOTE.get("version") or VERSIONS' in l])

print("\n[3] it can never become a downgrade")
P.LATEST_REMOTE.clear(); P.LATEST_REMOTE.update({"version": "1.8.5-beta"}); P.VERSIONS["panel"] = "1.8.6-beta"
t = P._update_target()
check("a node ALREADY on the target is not offered anything", not P._ver_behind("1.8.6-beta", t))
check("…nor is one AHEAD of it (a docker node past a lagging-CI panel)", not P._ver_behind("1.9.0-beta", t))
check("…and it is correctly reported as ahead", P._ver_ahead("1.9.0-beta", t))
check("a node genuinely behind IS offered it", P._ver_behind("1.8.5-beta", t), t)

print("")
if PERTURB:
    ok = len(FAILS) > 0
    print(("perturbed: the release-only target was CAUGHT (%d red)" % len(FAILS)) if ok
          else "perturbed: NOTHING FAILED — the target is not actually gated")
    sys.exit(0 if ok else 1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
