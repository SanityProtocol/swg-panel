#!/usr/bin/env python3
"""A Docker node's turn-proxy download — a transfer cut mid-body (1.8.9 qualification NODED-2).

_dturn_download fetched the fork binary with curl straight onto the SHARED per-fork file (…/turn/.bin/<fork>/server). A
transfer cut mid-body left a partial — or, after curl's --retry, empty — 0644 file there; the next install of that fork (the
operator's retry, another instance) found it ("already have this fork's binary"), reused it and ran its container on it: a
crash-loop the install reported ok, for every instance of the fork until a manual Reinstall. Now the download lands beside
the binary and is renamed in whole once checked, and the reuse test asks for an executable file, so the partial file an
older build left is fetched again.

REAL: swg-noded's _dturn_install, the real curl with its own flags and retries, against a loopback server that cuts every
transfer mid-body or serves the whole binary; `docker` is a stub on PATH (records its argv, says Running=true). Nothing
leaves 127.0.0.1; everything is written under a temp dir.

  [1] cut     a transfer cut mid-body leaves NOTHING at the shared binary and nothing beside it; the install says why
  [2] full    the next install of the fork fetches it and installs the whole binary, executable, as pinned
  [3] heal    a partial 0644 file a box already holds (an older build's cut download) is fetched again, not reused
  [4] reuse   control: an executable binary already there (another instance's) is reused — no fetch

Run: python3 tests/turn_download_cut_selftest.py      (0 = pass; SWG_NODED=<file> runs another swg-noded, e.g. an older one)
     --perturb-direct    curl writes onto the shared binary again, nothing cleaned → RED on [1]
     --perturb-reuse     the reuse test is "the file exists" again → RED on [3]
     --perturb-leftover  a failed download leaves its temp file beside the binary → RED on [1]
   A perturbation exits 0 when it is red on its section and nowhere else; 1 when it is not — or when its anchor is gone
   ("PLANT … anchor missing": a perturbation that cannot be applied proves nothing).
"""
import hashlib, importlib.machinery, importlib.util, os, shutil, socket, stat, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

_CLEAN = "    with contextlib.suppress(OSError): os.remove(tmp)    # what a cut transfer left\n"
PLANTS = {   # name: (section, [(anchor, replacement), …]) — every anchor must match exactly once
    "direct": ("[1]", [('    err, tmp = "binary download failed", binp + ".dl." + _turn_inst(svc)\n',
                        '    err, tmp = "binary download failed", binp\n'), (_CLEAN, "")]),
    "reuse": ("[3]", [("    if os.access(binp, os.X_OK):   # already have this fork's binary",
                       "    if os.path.exists(binp):   # already have this fork's binary")]),
    "leftover": ("[1]", [(_CLEAN, "")]),
}
MODE = next((a[len("--perturb-"):] for a in sys.argv[1:] if a.startswith("--perturb-")), "")
if MODE and MODE not in PLANTS:
    sys.exit("unknown perturbation: " + MODE)
FAILS = []
def check(sec, name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + sec + " " + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(sec)

T = tempfile.mkdtemp(prefix="turn-dl-cut-")
src = open(NODED, encoding="utf-8").read()
if MODE:
    for old, new in PLANTS[MODE][1]:
        if src.count(old) != 1:
            print("PLANT %s anchor missing (%d matches): %r" % (MODE, src.count(old), old.strip()[:90]))
            shutil.rmtree(T, ignore_errors=True)
            sys.exit(1)
        src = src.replace(old, new)
p = os.path.join(T, "swg-noded"); open(p, "w", encoding="utf-8").write(src)
os.environ["SWG_NO_REEXEC"] = "1"
ld = importlib.machinery.SourceFileLoader("swgnoded_turn_dl_cut", p)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_turn_dl_cut", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass

# ── the "release": a loopback server that cuts every transfer mid-body, or serves it whole ──────────────────────────
BODY = b"\x7fELF" + os.urandom(1 << 20)
SHA = hashlib.sha256(BODY).hexdigest()
SRV = {"cut": True, "hits": 0}
lsn = socket.socket(); lsn.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); lsn.bind(("127.0.0.1", 0)); lsn.listen(16)
PORT = lsn.getsockname()[1]
def serve():
    while True:
        try:
            c, _ = lsn.accept()
        except OSError:
            return
        with c:
            try:
                c.recv(65536); SRV["hits"] += 1
                head = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(BODY)
                c.sendall(head + (BODY[:4096] if SRV["cut"] else BODY))   # cut: 4 KiB of 1 MiB, then the connection closes
            except OSError:
                pass
threading.Thread(target=serve, daemon=True).start()

# ── the sandbox: docker is a stub, every path under T, the download URL is the loopback server ─────────────────────
BIN = os.path.join(T, "bin"); os.makedirs(BIN)
DLOG = os.path.join(T, "docker.log")
with open(os.path.join(BIN, "docker"), "w") as f:
    f.write('#!/bin/sh\necho "$*" >> "$SWG_TEST_DOCKER_LOG"\n[ "$1" = inspect ] && echo true\nexit 0\n')
os.chmod(os.path.join(BIN, "docker"), 0o755)
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")
os.environ["SWG_TEST_DOCKER_LOG"] = DLOG
N.TURN_DOCKER = True
N.SWG_TURN_IMAGE = "swg-node:test"; N.SWG_HOST_NODE_DIR = T          # the container's mount names the same file here
N._turn_arch = lambda: "amd64"
N._TURN_PANEL = {}                                                   # no panel mirror: straight to the direct download
N._turn_bin_local = lambda svc: os.path.join(T, "turn", ".bin", N._turn_fork(svc), "server")
N._turn_bin_local_legacy = lambda svc: os.path.join(T, "turn", N._turn_inst(svc), "server")
N._turn_dl_urls = lambda owner, arch, tag=None: ["http://127.0.0.1:%d/%s/releases/download/%s/server-linux-%s" % (PORT, owner, tag, arch)]

def req(port, fork):
    return {"owner": fork + "/vk-turn-proxy", "listen": "0.0.0.0:%d" % port, "connect": "127.0.0.1:51820",
            "params": "-wrap-key " + "a" * 64, "pin": {"tag": "v9.9.9", "sums": {"amd64": SHA}}}
def whole(path):   # the whole pinned binary, executable
    try:
        st = os.stat(path)
        return st.st_mode & 0o111 and hashlib.sha256(open(path, "rb").read()).hexdigest() == SHA
    except OSError:
        return False
def state(path):
    if not os.path.lexists(path):
        return "absent"
    st = os.stat(path)
    return "%d bytes, %s" % (st.st_size, stat.filemode(st.st_mode))
def runs():
    try:
        return [ln for ln in open(DLOG).read().splitlines() if ln.startswith("run ")]
    except OSError:
        return []

try:
    print("[1] cut — every transfer is cut mid-body (the real curl, its retries)")
    svc = "vk-turn-proxy-WINGS-N-56100"; binp = N._turn_bin_local(svc)
    SRV["cut"] = True; h0 = SRV["hits"]
    err, tp = N._dturn_install(svc, req(56100, "WINGS-N"))
    check("[1]", "the install fails and says why (curl's error), keeping no record", bool(err) and "curl" in err and tp is None, (err, tp))
    check("[1]", "the transfer was really tried", SRV["hits"] > h0, SRV["hits"] - h0)
    check("[1]", "NOTHING is left at the shared fork binary", not os.path.lexists(binp), state(binp))
    _left = sorted(os.listdir(os.path.dirname(binp))) if os.path.isdir(os.path.dirname(binp)) else []
    check("[1]", "…and nothing beside it", _left == [], _left)
    check("[1]", "no container was started", runs() == [], runs())

    print("[2] full — the next install of the fork, the server now serving the whole binary")
    svc2 = "vk-turn-proxy-WINGS-N-56101"
    SRV["cut"] = False; h0 = SRV["hits"]
    err, tp = N._dturn_install(svc2, req(56101, "WINGS-N"))
    check("[2]", "it fetches the binary (the server is asked)", SRV["hits"] - h0 == 1, SRV["hits"] - h0)
    check("[2]", "the shared binary is the whole pinned one, executable", whole(binp), state(binp))
    check("[2]", "the install is ok and its container runs that file", err == "" and tp is not None
          and any((" -v " + binp + ":/turn-server:ro ") in r for r in runs()), (err, runs()))

    print("[3] heal — a partial 0644 file an older build's cut download left")
    svc3 = "vk-turn-proxy-cacggghp-56200"; b3 = N._turn_bin_local(svc3)
    os.makedirs(os.path.dirname(b3)); open(b3, "wb").write(BODY[:4096]); os.chmod(b3, 0o644)
    h0 = SRV["hits"]
    err, tp = N._dturn_install(svc3, req(56200, "cacggghp"))
    check("[3]", "it is fetched again, not reused", SRV["hits"] - h0 == 1, SRV["hits"] - h0)
    check("[3]", "…and replaced by the whole pinned binary, executable; the install is ok", whole(b3) and err == "", (state(b3), err))

    print("[4] reuse — control: an executable binary already there (another instance's)")
    svc4 = "vk-turn-proxy-MYSOREZ-56300"; b4 = N._turn_bin_local(svc4)
    os.makedirs(os.path.dirname(b4)); open(b4, "wb").write(BODY); os.chmod(b4, 0o755)
    h0 = SRV["hits"]
    err, tp = N._dturn_install(svc4, req(56300, "MYSOREZ"))
    check("[4]", "it is reused — no fetch — and the install is ok", SRV["hits"] == h0 and err == "" and tp is not None and whole(b4),
          (SRV["hits"] - h0, err, state(b4)))
finally:
    lsn.close()
    shutil.rmtree(T, ignore_errors=True)

print()
if MODE:
    sec = PLANTS[MODE][0]
    stray = sorted({s for s in FAILS if s != sec})
    ok = sec in FAILS and not stray
    print("perturb %s: %s" % (MODE, ("RED on " + sec + " as expected") if ok else ("NOT caught by " + sec) if sec not in FAILS
                                    else ("ALSO red outside " + sec + ": " + ", ".join(stray))))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL: %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
