#!/usr/bin/env python3
"""Self-test — on a docker node, finding dormant WDTT installs costs no host helper of its own.

wdtt_dormant() looks for a stopped WDTT install in each of WDTT_CFG_DIRS. On a docker node every look is a host_sh call,
which is a privileged one-shot container, and the four dirs were probed one helper each, every TTL — for directories
that almost never exist. Traced on svo-im 10-05: 8 of its 13 helper containers in 4 minutes were these probes. The host
/proc walk already runs one helper per TTL; it now also prints `CFG <dir>` for every WDTT_CFG_DIR holding a wg-keys.dat,
and wdtt_dormant gives the full probe only to those.

The walk's command is run for real (sh -c) against sandbox directories; host_sh calls are counted by kind.

  [1] the walk: CFG lists exactly the dirs with an identity; missing dirs keep the status 0 (the walk is trusted);
      a failed walk keeps the last answer
  [2] wdtt_dormant on docker: no identity anywhere → one helper per TTL (the walk), no probe; an identity → one probe,
      for that dir only, and the install is reported; a walk that never completed → nothing probed, nothing reported
  [3] bare metal is unchanged: every dir checked locally, no host_sh at all

Run: python3 tests/wdtt_dormant_probe_selftest.py        (0 = pass)
     --plant alldirs|status|forget    the defect it names, planted → RED
"""
import importlib.machinery, importlib.util, io, os, shutil, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "alldirs": ("        dirs = [d for d in WDTT_CFG_DIRS if d in (_WDTT_HOSTPROC.get(\"cfg\") or ())]\n",
                "        dirs = WDTT_CFG_DIRS\n"),
    "status":  ("echo \\\"CFG $d\\\"; done; :\")", "echo \\\"CFG $d\\\"; done\")"),
    "forget":  ("    if ok:\n        _WDTT_HOSTPROC[\"cfg\"] = cfg\n", "    _WDTT_HOSTPROC[\"cfg\"] = cfg\n"),
}
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if PLANT:
    a, b = PLANTS[PLANT]
    assert src.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    src = src.replace(a, b)
TMP = tempfile.mkdtemp(prefix="dormant-")
prog = os.path.join(TMP, "swg-noded"); open(prog, "w", encoding="utf-8").write(src)
os.environ["SWG_NODED_STATE"] = os.path.join(TMP, "state")

def load():
    ld = importlib.machinery.SourceFileLoader("dormant_noded_%d" % len(os.listdir(TMP)), prog)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
    ld.exec_module(m)
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    m._LOG_STREAM = io.StringIO(); m._LOG_JOURNAL = False
    return m

def sandbox(with_identity):
    d = tempfile.mkdtemp(prefix="cfg-", dir=TMP)
    dirs = tuple(os.path.join(d, p) for p in ("etc/wdtt", "opt/wdtt", "var/lib/wdtt", "usr/local/etc/wdtt"))
    os.makedirs(dirs[1])                                    # exists, holds nothing
    if with_identity:
        os.makedirs(dirs[0]); open(os.path.join(dirs[0], "wg-keys.dat"), "w").write("key")
        open(os.path.join(dirs[0], "passwords.json"), "w").write("{}")
    return dirs                                             # [2] and [3] never exist

CALLS = []; FAIL = {"rc": None}
def host_sh(cmd, timeout=30, probe=False):
    kind = "walk" if cmd.startswith("for p in /proc") else "probe" if cmd.startswith("R=''") else "other"
    CALLS.append(kind)
    if FAIL["rc"] is not None:
        return subprocess.CompletedProcess(cmd, FAIL["rc"], "", "docker: boom")
    return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=60)

def docker_node(dirs):
    m = load()
    m.NODE_KIND = "docker"; m.host_sh = host_sh; m.WDTT_CFG_DIRS = dirs
    return m

print("[1] the walk")
dirs = sandbox(True)
N = docker_node(dirs); CALLS.clear()
N._wdtt_host_procs()
check("[1] CFG lists exactly the dirs holding a wg-keys.dat (not the empty one, not the missing two)",
      N._WDTT_HOSTPROC["cfg"] == {dirs[0]}, N._WDTT_HOSTPROC["cfg"])
check("[1] missing dirs keep the status at 0: the walk is trusted", N._WDTT_HOSTPROC["ok"] is True, N._LOG_STREAM.getvalue()[-200:])
N._WDTT_HOSTPROC["at"] = N._WDTT_HOSTPROC["walked"] = 0.0; FAIL["rc"] = 125
N._wdtt_host_procs()
check("[1] a failed walk keeps the last answer (a dormant install does not blink out)",
      N._WDTT_HOSTPROC["ok"] is False and N._WDTT_HOSTPROC["cfg"] == {dirs[0]}, N._WDTT_HOSTPROC)
FAIL["rc"] = None

print("[2] wdtt_dormant on a docker node")
N = docker_node(sandbox(False)); CALLS.clear()
out = N.wdtt_dormant()
check("[2] no identity anywhere: ONE helper (the walk) and no probe — it was one probe per dir, four per TTL",
      CALLS == ["walk"] and out == [], (CALLS, out))
CALLS.clear(); N.wdtt_dormant()
check("[2] …and nothing at all within the TTL", CALLS == [], CALLS)
dirs = sandbox(True)
N = docker_node(dirs); CALLS.clear()
out = N.wdtt_dormant()
check("[2] an identity in one dir: one walk + ONE probe, for that dir only", sorted(CALLS) == ["probe", "walk"], CALLS)
check("[2] …and that install is reported, from the probe's answer", [o.get("config_dir") for o in out] == [dirs[0]], out)
N = docker_node(sandbox(True)); CALLS.clear(); FAIL["rc"] = 125
out = N.wdtt_dormant()
check("[2] a walk that never completed: nothing probed, nothing reported", "probe" not in CALLS and out == [], (CALLS, out))
FAIL["rc"] = None

print("[3] bare metal")
dirs = sandbox(True)
B = load(); B.NODE_KIND = "baremetal"; B.host_sh = host_sh; B.WDTT_CFG_DIRS = dirs; CALLS.clear()
out = B.wdtt_dormant()
check("[3] every dir checked locally, no host_sh at all, the install found",
      CALLS == [] and [o.get("config_dir") for o in out] == [dirs[0]], (CALLS, out))

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but plant %r was planted and should have gone RED" % PLANT if PLANT else ""))
sys.exit(2 if PLANT else 0)
