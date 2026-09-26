#!/usr/bin/env python3
"""Self-test — two small readings that were wrong on every Docker panel / every sheet-saved AWG interface.

  [1] an EMPTY SWG_LATEST_URL is unset: docker-compose passes the variable as "" when .env names none, and
      `environ.get(name, default)` returned that "", so every Docker panel's release check failed (VM re-run D4)
  [2] `awg_pending` is gone: read by nothing, and wrong (the sheet's strings against the node's integers — O3)

The panel module is loaded as shipped with SWG_LATEST_URL set to "".
Run: python3 tests/panel_env_and_awg_pending_selftest.py      (0 = pass)
     --perturb   the old SWG_LATEST_URL reading back → RED on [1]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB = "--perturb" in sys.argv
src = open(SERVER, encoding="utf-8").read()
if PERTURB:
    a = 'REMOTE_VERSION_URL = (os.environ.get("SWG_LATEST_URL") or "").strip() \\\n    or "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION"'
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, 'REMOTE_VERSION_URL = os.environ.get("SWG_LATEST_URL", "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/VERSION")')
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
print("\n[2] awg_pending is gone — it was computed on every poll and read by nothing")
live = open(SERVER, encoding="utf-8").read()
check("the describe builder no longer sets it", 'ifc["awg_pending"]' not in live)
check("…and nothing in the SPA reads it", not any("awg_pending" in open(os.path.join(HERE, "..", "js", f), encoding="utf-8").read()
                                                  for f in os.listdir(os.path.join(HERE, "..", "js")) if f.endswith(".js")))
print(("\nFAIL (%d)" % len(FAILS)) if FAILS else ("\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else "")))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
