"""Self-test — A SETTLED NODE DOES NOT REWRITE ITS RECORDS EVERY PASS.

`_wdtt_save`, `_csqtt_save` and the exit loop's record save ran on every sync pass (every 5 s) and replaced
their file each time with the same bytes: measured on swgt 2026-10-17, 7 files, 84 replacements a minute,
~0.7 MiB/min of writes from a node with nothing to do. They now go through `_replace_if_changed`, which writes
only when the text differs. This proves the file is left alone (same inode, same mtime) when nothing changed,
is still written when something did, when it is missing, and when it is unreadable — and that an exit record
keeps its 0600 mode, including one found looser with the right bytes (each rewrite used to tighten it).

Run: python3 tests/record_rewrite_selftest.py      (0 = pass)
     --perturb        _replace_if_changed writes unconditionally again, and expects RED in [1] [2] [3].
     --perturb-mode   its skip path no longer tightens a looser mode, and expects RED in [3].
"""
import atexit, importlib.machinery, importlib.util, json, os, shutil, stat, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_MODE = "--perturb-mode" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

NSRC = open(NODED, encoding="utf-8").read()
# ⚠️ ASSERT THE ANCHOR EXISTS BEFORE TOUCHING IT, or a perturbation that matches nothing reads as a clean PASS.
_SKIP = """            if f.read() == text:
                # the bytes are right but"""
_MODE = """                    os.chmod(path, mode)
                return"""
assert NSRC.count(_SKIP) == 1, "_replace_if_changed's skip anchor missing — this run would FALSE-PASS"
assert NSRC.count(_MODE) == 1, "_replace_if_changed's mode anchor missing — this run would FALSE-PASS"
if PERTURB:
    NSRC = NSRC.replace(_SKIP, """            if False:
                # the bytes are right but""")
if PERTURB_MODE:
    NSRC = NSRC.replace(_MODE, """                    pass
                return""")

npath = NODED
if PERTURB or PERTURB_MODE:
    _fd, npath = tempfile.mkstemp(suffix=".py", prefix="recrw-", dir=HERE)
    os.write(_fd, NSRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

N = _load(npath, "swgnoded")
if PERTURB or PERTURB_MODE:
    os.unlink(npath)

def ident(p):
    st = os.stat(p)
    return (st.st_ino, st.st_mtime_ns)

tmp = tempfile.mkdtemp(prefix="recrw-")
atexit.register(shutil.rmtree, tmp, True)          # it holds a sample private key

print("[1] the WDTT and csqtt records")
N.WDTT_RECORD = os.path.join(tmp, "wdtt.json")
N.CSQTT_RECORD = os.path.join(tmp, "csqtt.json")
W = {"wdtt1": {"iface": "wdtt1", "listen": "0.0.0.0:56000", "panel_managed": True}}
C = {"csqtt1": {"iface": "csqtt1", "listen": "0.0.0.0:46000", "line": "2.5"}}
check("a missing WDTT record is written", N._wdtt_save(W) and json.load(open(N.WDTT_RECORD)) == {"wdtt": list(W.values())})
check("a missing csqtt record is written", N._csqtt_save(C) and json.load(open(N.CSQTT_RECORD)) == C)
os.utime(N.WDTT_RECORD, ns=(1, 1)); os.utime(N.CSQTT_RECORD, ns=(1, 1))   # a stale mtime a rewrite would move
w0, c0 = ident(N.WDTT_RECORD), ident(N.CSQTT_RECORD)
check("saving the same WDTT set leaves the file alone", N._wdtt_save(W) and ident(N.WDTT_RECORD) == w0,
      (w0, ident(N.WDTT_RECORD)))
check("saving the same csqtt set leaves the file alone", N._csqtt_save(C) and ident(N.CSQTT_RECORD) == c0,
      (c0, ident(N.CSQTT_RECORD)))
check("…and nothing is left behind", sorted(os.listdir(tmp)) == ["csqtt.json", "wdtt.json"], os.listdir(tmp))
C2 = {"csqtt1": dict(C["csqtt1"], line="2.1")}
check("a changed csqtt set IS written", N._csqtt_save(C2) and json.load(open(N.CSQTT_RECORD)) == C2
      and ident(N.CSQTT_RECORD) != c0)
open(N.WDTT_RECORD, "w").write('{"wdtt": [')                                 # torn by something else
check("an unreadable record is rewritten whole", N._wdtt_save(W) and json.load(open(N.WDTT_RECORD)) == {"wdtt": list(W.values())})

print("\n[2] the bytes the old json.dump wrote compare equal — the first pass after an update skips too")
for name, obj in (("wdtt", {"wdtt": list(W.values())}), ("csqtt", C2)):
    p = os.path.join(tmp, name + "-old.json")
    with open(p, "w") as f:
        json.dump(obj, f)                       # how every earlier build wrote it
    os.utime(p, ns=(1, 1)); before = ident(p)
    N._replace_if_changed(p, json.dumps(obj))
    check("a %s record written by an earlier build is not rewritten" % name, ident(p) == before, (before, ident(p)))
    os.unlink(p)

print("\n[3] an exit's record, through reconcile_exits")
class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err
xdir = os.path.join(tmp, "exits")
N.EXIT_DIR = xdir
N.run = lambda cmd, **kw: R(0, "", "")
N._dev_link_state = lambda d: "up"
N._link_kind = lambda d: "wg"
N._exit_down = lambda dev, rec: None
N._exit_probe_all = lambda devs: {}               # no real trace/reach threads from a gate
XID = "aabbccdd"
EX = [{"id": XID, "device": "wgx-" + XID, "provider": "profile", "cfg_sig": "s1",
       "profile": {"private_key": "QFm3Jt5Rrn6f0aX1sVYQK0lZ2p8vJcU7dHwEbNqTsGk=", "address": "10.77.0.2/32",
                   "peer_key": "ZtVPNeJM8Gsneelu4sijDrDz3AVt7uZb9IbtK71Q6xc=", "endpoint": "203.0.113.9:51820"}}]
def pass_once():
    res = {"errors": [], "changed": 0}
    N._EXITS["list"] = []
    N.reconcile_exits(EX, res)
    return res
pass_once()
sp = os.path.join(xdir, XID + ".json")
check("the first pass writes the exit's record", os.path.isfile(sp), os.listdir(xdir) if os.path.isdir(xdir) else "no dir")
if os.path.isfile(sp):
    check("…private to root (0600)", stat.S_IMODE(os.stat(sp).st_mode) == 0o600, oct(os.stat(sp).st_mode))
    check("…naming its device", json.load(open(sp)).get("device") == "wgx-" + XID, json.load(open(sp)))
    os.utime(sp, ns=(1, 1)); x0 = ident(sp)
    pass_once(); pass_once()
    check("two more passes with nothing new leave it alone", ident(sp) == x0, (x0, ident(sp)))
    os.chmod(sp, 0o644)                          # a restore or a cp without -p
    pass_once()
    check("a record found 0644 with the right bytes is tightened to 0600", stat.S_IMODE(os.stat(sp).st_mode) == 0o600,
          oct(os.stat(sp).st_mode))
    check("…without being rewritten", ident(sp)[0] == x0[0], (x0, ident(sp)))
    os.unlink(sp)
    pass_once()
    check("a record deleted under the node is written again", os.path.isfile(sp))

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
