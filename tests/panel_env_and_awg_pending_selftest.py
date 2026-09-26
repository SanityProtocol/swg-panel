#!/usr/bin/env python3
"""Self-test — two small readings that were wrong on every Docker panel / every sheet-saved AWG interface.

  [1] an EMPTY SWG_LATEST_URL is unset: docker-compose passes the variable as "" when .env names none, and
      `environ.get(name, default)` returned that "", so every Docker panel's release check failed (VM re-run D4)
  [2] `awg_pending` compares values the way the sync does: the panel stores the sheet's strings ("94"), the node reports
      integers (94), and the raw dict comparison held the flag true for good (qualification O3)

The panel module is loaded as shipped with SWG_LATEST_URL set to "".
Run: python3 tests/panel_env_and_awg_pending_selftest.py      (0 = pass)
     --perturb   both old readings back → RED on both
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB = "--perturb" in sys.argv
src = open(SERVER, encoding="utf-8").read()
if PERTURB:
    a = 'REMOTE_VERSION_URL = (os.environ.get("SWG_LATEST_URL") or "").strip() \\\n    or "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION"'
    b = 'return set(want) != set(rep) or any(str(want[k]) != str(rep[k]) for k in want)'
    assert src.count(a) == 1 and src.count(b) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, 'REMOTE_VERSION_URL = os.environ.get("SWG_LATEST_URL", "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION")')
    src = src.replace(b, "return want != rep")
path = os.path.join(tempfile.mkdtemp(prefix="envawg-"), "panel.py"); open(path, "w").write(src)
os.environ["SWG_LATEST_URL"] = ""
loader = importlib.machinery.SourceFileLoader("swgpanel_envawg", path)
spec = importlib.util.spec_from_loader("swgpanel_envawg", loader); P = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(P)
except SystemExit:
    pass
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok: FAILS.append(name)
print("[1] SWG_LATEST_URL=\"\" (what compose passes)")
check("the release check asks main's VERSION", P.REMOTE_VERSION_URL.endswith("/swg-panel/main/VERSION"), P.REMOTE_VERSION_URL)
check("…and the changelog sits beside it", P.REMOTE_CHANGELOG_URL.endswith("/swg-panel/main/CHANGELOG.md"), P.REMOTE_CHANGELOG_URL)
print("\n[2] awg_pending")
want = {"Jc": "4", "S1": "28", "RandomTrailers": "1", "KeepaliveTimeout": "5-15"}
rep = {"Jc": 4, "S1": 28, "RandomTrailers": 1, "KeepaliveTimeout": "5-15"}
check("the sheet's strings against the node's integers: not pending", P.awg_params_differ(want, rep) is False)
check("a value that really differs: pending", P.awg_params_differ(dict(want, Jc="5"), rep) is True)
check("a key the node does not report yet: pending", P.awg_params_differ(dict(want, S3="65"), rep) is True)
check("the describe builder asks it", "ifc[\"awg_pending\"] = awg_params_differ(ifc[\"awg_params\"], rep_awg)" in open(SERVER).read())
print(("\nFAIL (%d)" % len(FAILS)) if FAILS else ("\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else "")))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
