#!/usr/bin/env python3
"""Self-test for LOGS-PLAN P1a — the two node logs nothing bounded (docs/LOGS-PLAN.md §0, §7 P1a).

  [1] A supervised WDTT / csqtt server that STAYS UP is bounded. A rename cannot bound a running server (it keeps
      appending to the renamed inode), so `_rotate_serverlog` copies the last `cap` bytes to `.1` and truncates in
      place, which works because the server's descriptor is O_APPEND. Measured against a real child process writing
      through an "ab" descriptor, as the server does.
  [2] Only the TAIL is copied (a log written before the cap existed costs `cap` to rotate, not a copy of itself),
      `.1` is replaced whole, and the truncate runs even when the copy fails (a bounded disk outranks the tail).
  [3] It runs from the loop tick (`_cap_serverlogs`), for every instance directory under both docker roots, and not
      at all on bare metal.
  [4] swg-sni's output joins noded's own stream instead of /var/lib/swg-noded/swg-sni.log; noded removes the old file.
  [5] swg-sni's say(): a stream that blocks or raises can neither block nor raise on the packet path, and a burst
      is bounded and counted.
  [6] A failed WDTT start reads only the end of its log.

Run: python3 tests/node_log_bounds_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     rename     rotation renames the file (the running server writes on into `.1`)
     fullcopy   rotation copies the whole file to `.1`
     nofinally  the truncate runs only when the copy succeeded
     nowire     the loop tick does not call _cap_serverlogs
     snilog     swg-sni's output goes back to the unrotated file
     sayblock   say() writes synchronously, as print() did
     nodrain    nothing writes the queue out at exit
"""
import importlib.machinery, importlib.util, io, os, re, subprocess, sys, tempfile, threading, time, tokenize, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # (file, anchor, replacement)
    "rename": ("noded", "        tmp = path + \".1.tmp\"\n        try:\n",
               "        os.replace(path, path + \".1\"); return\n        tmp = path + \".1.tmp\"\n        try:\n"),
    "fullcopy": ("noded", "                at = max(0, os.fstat(src.fileno()).st_size - cap)\n", "                at = 0\n"),
    "nofinally": ("noded", "            os.replace(tmp, path + \".1\")\n        except OSError:\n            with contextlib.suppress(OSError):\n                os.remove(tmp)\n        finally:\n            os.truncate(path, 0)\n",
                  "            os.replace(tmp, path + \".1\")\n            os.truncate(path, 0)\n        except OSError:\n            with contextlib.suppress(OSError):\n                os.remove(tmp)\n"),
    "nowire": ("noded", "        _cap_serverlogs()                           # docker: bound each supervised server's log, panel or no panel\n", ""),
    "snilog": ("noded", "\"--reset-mark\", hex(SNI_RESET_MARK), \"--learn-ttl\", str(learn_ttl)])",
               "\"--reset-mark\", hex(SNI_RESET_MARK), \"--learn-ttl\", str(learn_ttl)],"
               " stdout=open(\"/var/lib/swg-noded/swg-sni.log\", \"a\"))"),
    "nodrain": ("sni", "                    atexit.register(_say_drain)\n", ""),
    "sayblock": ("sni", "        if len(_SAY[\"q\"]) >= SAY_MAX:\n",
                 "        sys.stdout.write(_say_text(prio, fmt, args)); sys.stdout.flush(); return\n        if len(_SAY[\"q\"]) >= SAY_MAX:\n"),
}
# swg-sni follows swg-noded's level through this file (LOGS P1b); none here, so it logs at Info whatever the box says.
os.environ["SWG_LOG_LEVEL_FILE"] = os.path.join(tempfile.mkdtemp(prefix="logbounds-lvl-"), "log-level")
SRC = {"noded": open(NODED, encoding="utf-8").read(), "sni": open(SNI, encoding="utf-8").read()}
if PLANT:
    f, a, b = PLANTS[PLANT]
    assert SRC[f].count(a) == 1, "plant anchor not unique/absent: " + PLANT
    SRC[f] = SRC[f].replace(a, b)


def load(src, name):
    p = os.path.join(tempfile.mkdtemp(prefix="logbounds-"), name)
    open(p, "w", encoding="utf-8").write(src)
    ld = importlib.machinery.SourceFileLoader(name.replace("-", "_") + "_logbounds", p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


N = load(SRC["noded"], "swg-noded")
D = tempfile.mkdtemp(prefix="logbounds-")
CAP = 64 << 10


def size(p):
    return os.path.getsize(p) if os.path.exists(p) else 0


# ── [1] a running server is bounded ─────────────────────────────────────────────────────────────────────────────────
print("[1] rotation against a running writer")
log = os.path.join(D, "server.log")
WRITER = ("import sys,time\n"
          "f=open(sys.argv[1],'ab',buffering=0)\n"     # exactly how _wdtt_docker_start / _csqtt_docker_start open it
          "i=0\n"
          "while True:\n"
          "    i+=1; f.write(b'line %08d ' % i + b'x'*100 + b'\\n'); time.sleep(0.0005)\n")
w = subprocess.Popen([sys.executable, "-c", WRITER, log])
try:
    deadline = time.time() + 20
    while time.time() < deadline and size(log) < CAP:
        time.sleep(0.02)
    before = size(log)
    N._rotate_serverlog(log, cap=CAP)
    time.sleep(0.3)                                     # the writer keeps going
    after = size(log)
    gen1 = size(log + ".1")
    head = open(log, "rb").read(16) if os.path.exists(log) else b""
    check("[1] the file was over the cap before", before >= CAP, before)
    check("[1] `.1` holds the previous output", gen1 > 0, gen1)
    check("[1] the running server's file restarted small, and is still being written", 0 < after < before, (before, after))
    check("[1] new output starts at offset 0 — no hole of NULs (the descriptor is O_APPEND)", head.startswith(b"line "), head)
    for _ in range(6):                                  # several more caps of output: the pair stays bounded
        t = time.time() + 10
        while time.time() < t and size(log) < CAP:
            time.sleep(0.02)
        N._rotate_serverlog(log, cap=CAP)
    total = size(log) + size(log + ".1")
    check("[1] after 6 more caps of output the pair stays within ~2× the cap", total <= 2 * CAP + (32 << 10), total)
finally:
    w.kill(); w.wait()

# ── [2] tail only, whole replace, truncate even when the copy fails ─────────────────────────────────────────────────
print("[2] tail copy and failure")
big = os.path.join(D, "big.log")
with open(big, "wb") as f:
    for i in range(3 * CAP // 50):
        f.write(b"old line %06d ......................................\n" % i)
total_big = size(big)
N._rotate_serverlog(big, cap=CAP)
g = open(big + ".1", "rb").read() if os.path.exists(big + ".1") else b""
check("[2] a log of 3× the cap: `.1` holds at most the cap (its tail), not a copy of the whole", 0 < len(g) <= CAP, (total_big, len(g)))
check("[2] …starting at a whole line", g.startswith(b"old line "), g[:20])
check("[2] …ending with the newest line", g.endswith(b"old line %06d ......................................\n" % (3 * CAP // 50 - 1)), g[-60:])
check("[2] …and the log is emptied", size(big) == 0, size(big))
check("[2] no temp file left", not os.path.exists(big + ".1.tmp"))
fail = os.path.join(D, "fail.log")
open(fail, "wb").write(b"F" * (CAP + 10))
open(fail + ".1", "wb").write(b"previous generation")
os.mkdir(fail + ".1.tmp")                               # the copy cannot be written
N._rotate_serverlog(fail, cap=CAP)
check("[2] a copy that fails still empties the log (a bounded disk outranks the tail)", size(fail) == 0, size(fail))
check("[2] …and leaves the previous `.1` whole", open(fail + ".1", "rb").read() == b"previous generation")
os.rmdir(fail + ".1.tmp")
small = os.path.join(D, "small.log")
open(small, "wb").write(b"B" * 10)
N._rotate_serverlog(small, cap=CAP)
check("[2] under the cap → untouched", open(small, "rb").read() == b"B" * 10 and not os.path.exists(small + ".1"))
N._rotate_serverlog(os.path.join(D, "absent.log"), cap=CAP)
check("[2] a missing file is not an error", True)

# ── [3] the loop tick covers every instance, docker only ────────────────────────────────────────────────────────────
print("[3] _cap_serverlogs")
W, C = os.path.join(D, "wdtt"), os.path.join(D, "csqtt")
for r in (W, C):
    for i in ("a", "b"):
        os.makedirs(os.path.join(r, i))
        open(os.path.join(r, i, "server.log"), "wb").write(b"z" * (N.SERVERLOG_MAX + 1))
open(os.path.join(W, "stray-file"), "w").write("not an instance")
N.WDTT_ROOT, N.CSQTT_ROOT = W, C
N.NODE_KIND = "baremetal"
N._cap_serverlogs()
check("[3] bare metal: nothing touched (its servers log to the journal)",
      all(size(os.path.join(r, i, "server.log")) == N.SERVERLOG_MAX + 1 for r in (W, C) for i in ("a", "b")))
N.NODE_KIND = "docker"
N._cap_serverlogs()
check("[3] docker: every instance under both roots bounded",
      all(size(os.path.join(r, i, "server.log")) == 0 for r in (W, C) for i in ("a", "b")))


def body(src, name):
    m = re.search(r"^def " + name + r"\(.*?(?=^def |^if __name__|\Z)", src, re.S | re.M)
    return m.group(0) if m else ""


mn = body(SRC["noded"], "main")
loop = mn[mn.find("    while True:"):]
check("[3] the loop tick calls it before the sync, whatever the panel answers",
      "_cap_serverlogs()" in loop[:loop.find("post_json(")])
check("[3] the reconciles no longer carry their own copy", "_rotate_serverlog(" not in body(SRC["noded"], "reconcile_wdtt")
      and "_rotate_serverlog(" not in body(SRC["noded"], "reconcile_csqtt"))

# ── [4] swg-sni's output and the old file ───────────────────────────────────────────────────────────────────────────
print("[4] swg-sni output")
sni = body(SRC["noded"], "_ensure_sni_router")
launch = sni[sni.find("_SNI_PROC[\"p\"] = subprocess.Popen("):]
launch = launch[:launch.find("\n            _SNI_PROC[\"ttl\"]")]
check("[4] the classifier is launched with noded's own stdout/stderr (no redirect)",
      "stdout=" not in launch and "stderr=" not in launch, launch[-160:])
check("[4] nothing opens swg-sni.log for writing any more", re.search(r'open\("/var/lib/swg-noded/swg-sni\.log", *"a', SRC["noded"]) is None)
check("[4] noded removes the file an older build left", 'os.remove("/var/lib/swg-noded/swg-sni.log")' in mn)

# ── [5] swg-sni's say() ─────────────────────────────────────────────────────────────────────────────────────────────
print("[5] swg-sni say()")
_toks = [t for t in tokenize.generate_tokens(io.StringIO(SRC["sni"]).readline) if t.type in (tokenize.NAME, tokenize.OP)]
_calls = [t.start[0] for t, n in zip(_toks, _toks[1:]) if t.string == "print" and n.string == "("]
check("[5] swg-sni calls print() nowhere any more (comments and docstrings aside)", not _calls, _calls)
S = load(SRC["sni"], "swg-sni")


class Blocking(io.TextIOBase):
    def write(self, s):
        threading.Event().wait()                        # a journald that never reads


class Raising(io.TextIOBase):
    def write(self, s):
        raise BrokenPipeError(32, "Broken pipe")


S.sys = types.SimpleNamespace(stdout=Blocking())   # this module's stdout only — never the test's own
res = {}


def burst():
    t0 = time.time()
    for i in range(S.SAY_MAX + 500):
        S.say(S.LOG_INFO, "swg-sni: host%d.example → cat", i)
    res["t"] = time.time() - t0


th = threading.Thread(target=burst, daemon=True)
th.start(); th.join(3.0)
check("[5] a stream that blocks for ever does not block the caller", not th.is_alive() and res.get("t", 99) < 1.0, res)
check("[5] …and the backlog is bounded, the excess counted", len(S._SAY["q"]) <= S.SAY_MAX and S._SAY["dropped"] >= 400,
      (len(S._SAY["q"]), S._SAY["dropped"]))
S2 = load(SRC["sni"], "swg-sni")
S2.sys = types.SimpleNamespace(stdout=Raising())
try:
    S2.say(S2.LOG_INFO, "swg-sni: x → y")
    time.sleep(0.2)
    ok = True
except Exception as e:
    ok = False
check("[5] a stream that raises does not raise into the caller", ok)
S3 = load(SRC["sni"], "swg-sni")
buf = io.StringIO()
S3.sys = types.SimpleNamespace(stdout=buf)
S3.say(S3.LOG_ERR, "swg-sni: map reload failed: %s", ValueError("bad"))
time.sleep(1.3)
check("[5] lines still reach the stream, formatted by the writer, with their level (E outside journald)",
      "E swg-sni: map reload failed: bad\n" in buf.getvalue(), buf.getvalue()[:120])

S4 = load(SRC["sni"], "swg-sni")
rfd, wfd = os.pipe()
S4.sys = types.SimpleNamespace(stdout=os.fdopen(wfd, "w"))   # a real descriptor: the path production takes (os.write)
S4.say(S4.LOG_WARNING, "swg-sni: example.org → blocked (ads)")
time.sleep(1.3)
os.set_blocking(rfd, False)
try:
    got = os.read(rfd, 4096)
except BlockingIOError:
    got = b""
check("[5] through a real descriptor (os.write, no buffered-writer lock)", got == "W swg-sni: example.org → blocked (ads)\n".encode(), got)

SNI_TMP = os.path.join(tempfile.mkdtemp(prefix="logbounds-sni-"), "swg-sni")
open(SNI_TMP, "w", encoding="utf-8").write(SRC["sni"])
CHILD = ("import importlib.machinery, importlib.util, sys\n"
         "ld = importlib.machinery.SourceFileLoader('sni', sys.argv[1])\n"
         "m = importlib.util.module_from_spec(importlib.util.spec_from_loader('sni', ld)); ld.exec_module(m)\n"
         "for i in range(int(sys.argv[2])): m.say(m.LOG_INFO, 'swg-sni: line %d ' % i + 'x' * 90)\n"
         "raise SystemExit('NFQueue bind failed')\n")
r = subprocess.run([sys.executable, "-c", CHILD, SNI_TMP, "3"], capture_output=True, timeout=30)
check("[5] lines queued just before a crash are still written at exit",
      all(("swg-sni: line %d " % i).encode() in r.stdout for i in range(3)), r.stdout[:200])
rfd2, wfd2 = os.pipe()                                  # a stream nobody reads: 1 000 lines overfill the pipe
t0 = time.time()
pc = subprocess.Popen([sys.executable, "-c", CHILD, SNI_TMP, "1000"], stdout=wfd2, stderr=subprocess.DEVNULL)
os.close(wfd2)
try:
    pc.wait(timeout=10)
    took = time.time() - t0
except subprocess.TimeoutExpired:
    pc.kill(); took = 99
os.close(rfd2)
check("[5] …and a stream that is stuck cannot hold the exit (the drain is bounded)", took < 5, round(took, 1))

# ── [6] a failed WDTT start reads only the end of its log ───────────────────────────────────────────────────────────
print("[6] WDTT start-failure tail")
ws = body(SRC["noded"], "_wdtt_docker_start")
check("[6] the tail is read after a seek, never the whole file", "f.read()[-240:]" not in ws and "st_size - 240" in ws)

print()
if PLANT:
    print("PLANT %s: %s" % (PLANT, "caught (RED) ✓" if FAILS else "NOT caught ✗"))
    sys.exit(0 if FAILS else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
