#!/usr/bin/env python3
"""Self-test — the node's config.json (it holds the panel token) keeps its mode across the daemon's rewrites.

`_persist_config` wrote through a temp file created with the process umask, so the first interface change turned the
installer's 0640 into 0644 — the bearer token readable by every local user (1.8.8 VM re-run, D5, q1 and q4).

The real `_persist_config` runs against a temp CONFIG_PATH under umask 022 (the systemd default).
Run: python3 tests/node_config_mode_selftest.py      (0 = pass)
     --perturb   the umask-default write back → RED
"""
import importlib.machinery, importlib.util, json, os, stat, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
PERTURB = "--perturb" in sys.argv
src = open(NODED, encoding="utf-8").read()
if PERTURB:
    a = "    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n    with os.fdopen(fd, \"w\") as f:\n        os.fchmod(f.fileno(), mode or 0o600)\n"
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    with open(tmp, \"w\") as f:\n")
path = os.path.join(tempfile.mkdtemp(prefix="cfgmode-"), "noded.py"); open(path, "w").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded_cfgmode", path)
spec = importlib.util.spec_from_loader("swgnoded_cfgmode", loader); N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok: FAILS.append(name)
os.umask(0o022)
d = tempfile.mkdtemp(prefix="cfg-"); cfg = os.path.join(d, "config.json")
N.CONFIG_PATH = cfg
open(cfg, "w").write("{}"); os.chmod(cfg, 0o640)
N._persist_config({"panel": {"token": "t"}})
m = stat.S_IMODE(os.stat(cfg).st_mode)
check("an installer's 0640 stays 0640 after the daemon rewrites it", m == 0o640, oct(m))
check("…and the content is the new one", json.load(open(cfg)) == {"panel": {"token": "t"}})
os.chmod(cfg, 0o644)
N._persist_config({"panel": {"token": "t2"}})
m = stat.S_IMODE(os.stat(cfg).st_mode)
check("a file an older build left 0644 heals: no world bits", not (m & 0o007), oct(m))
os.unlink(cfg)
N._persist_config({"a": 1})
m = stat.S_IMODE(os.stat(cfg).st_mode)
check("a missing file is created 0600", m == 0o600, oct(m))
print(("\nFAIL (%d)" % len(FAILS)) if FAILS else ("\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else "")))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
