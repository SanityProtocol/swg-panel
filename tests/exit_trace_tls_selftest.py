#!/usr/bin/env python3
"""Self-test — the exit trace's TLS context is built once an hour, not once per probe (docs/CPU-PLAN.md B8).

`ssl.create_default_context()` parses the whole system CA bundle each time it is called — 121 certificates, 15.5 ms of CPU
on swgt — and the trace built one per exit per pass: with four exits, a quarter of the node's own CPU (perf, 2026-10-10).

  [1] Passes of probes over several exits build ONE context, and every probe's connection is handed that context.
  [2] It is the context the trace always had: the certificate and the host name are verified, so a probe still proves a
      real TLS path through the tunnel.
  [3] An hour on, the next pass builds a fresh one (a CA bundle the box updated is in use within the hour).
  [4] It is built on the caller's thread, before the probes start: concurrent probes never race to build it.

Run: python3 tests/exit_trace_tls_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     perprobe     the trace builds its own context again
     forever      the context is never rebuilt
"""
import http.client, importlib.machinery, importlib.util, os, ssl, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "perprobe": ('''        c = _Bound("www.cloudflare.com", 443, timeout=10, context=_exit_tls())''',
                 '''        c = _Bound("www.cloudflare.com", 443, timeout=10, context=ssl.create_default_context())'''),
    "forever": ('''    if _EXIT_TLS["ctx"] is None or now - _EXIT_TLS["at"] >= 3600:''', '''    if _EXIT_TLS["ctx"] is None:'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="exittls-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("et_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("et_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None

BUILT, HANDED = [], []
_real_cdc = ssl.create_default_context


def counting_cdc(*a, **k):
    BUILT.append(threading.current_thread().name)
    return _real_cdc(*a, **k)


ssl.create_default_context = counting_cdc
_real_init = http.client.HTTPSConnection.__init__


def recording_init(self, *a, **k):
    HANDED.append(k.get("context"))
    _real_init(self, *a, **k)


http.client.HTTPSConnection.__init__ = recording_init
# The probes, hermetic: the trace's connect fails at SO_BINDTODEVICE (no such device / not root) and is reported as `err`;
# the reach probe and the endpoint's re-resolve are not this gate's subject.
N._exit_reach = lambda dev: None
N._exit_resolve = lambda dev, rec: None
DEVS = [("swgtst%d" % i, {}) for i in range(4)]

# ── [1] one context for every probe ───────────────────────────────────────────────────────────────────────────────────
print("[1] passes of probes over four exits")
for _ in range(3):
    got = N._exit_probe_all(DEVS)
check("[1] CONTROL: every probe ran and reported (a failed trace is `err`, not silence)",
      len(got) == 4 and all((v[0] or {}).get("err") for v in got.values()), got)
check("[1] three passes × four exits built ONE context", len(BUILT) == 1, BUILT)
check("[1] …and all twelve connections were handed it", len(HANDED) == 12 and all(c is HANDED[0] for c in HANDED) and HANDED[0] is not None,
      len(HANDED))

# ── [2] the same kind of context ──────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the context the trace always had")
ctx = HANDED[0]
check("[2] the certificate is verified, against the system's CA bundle",
      ctx.verify_mode == ssl.CERT_REQUIRED and ctx.cert_store_stats() == _real_cdc().cert_store_stats(), ctx.cert_store_stats())
check("[2] …and the host name", ctx.check_hostname is True)

# ── [3] rebuilt hourly ────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] an hour on")
N._EXIT_TLS["at"] -= 3600
N._exit_probe_all(DEVS)
check("[3] the next pass builds a fresh context", len(BUILT) == 2 and HANDED[-1] is not ctx, BUILT)
N._exit_probe_all(DEVS)
check("[3] …and keeps that one", len(BUILT) == 2, BUILT)

# ── [4] built on the caller's thread ──────────────────────────────────────────────────────────────────────────────────
print("\n[4] built on the caller's thread")
check("[4] every build ran on the thread that started the probes", set(BUILT) == {threading.current_thread().name}, BUILT)
BUILT.clear()
N._exit_probe_all([])
check("[4] a pass with no exits builds nothing", not BUILT, BUILT)

ssl.create_default_context, http.client.HTTPSConnection.__init__ = _real_cdc, _real_init
import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
