#!/usr/bin/env python3
"""Self-test — a fresh Docker master's swg-sub waits for the panel's serve.json before it decides HTTP or HTTPS
(1.8.8 deferred #17, 1.8.9 qualification U22-1).

swg-sub starts beside the panel and reads its listener config as soon as the entrypoint has written fleet.json; serve.json
(which carries the TLS mode) is written by the panel at the END of its start, and swg-sub's certificate by the entrypoint's
BACKGROUND openssl. Read before serve.json, the mode was unknown, so a missing certificate meant plain HTTP with no wait —
until the next restart, every https subscription link failed the handshake (Ubuntu 22.04: 1 fresh Docker master in 4).

  [1] the REAL swg-sub started with fleet.json only; the certificate and serve.json (a direct-TLS mode) arrive seconds
      later, in either order → HTTPS from its first listen, never plain HTTP
  [2] serve.json saying reverse-proxy (TLS terminated upstream) → plain HTTP once it is there, no certificate waited for
  [3] CONTROL: serve.json and the certificate there at start → HTTPS at once, nothing waited for
  [4] the wait is bounded: a panel that never writes serve.json still gets a listener (as before: plain HTTP) — the
      bound lowered to one look in this copy

Run: python3 tests/sub_tls_late_selftest.py      --plant noservewait | unbounded   (exit 0 when caught)
     SWG_SUB=<swg-sub of an older build> python3 tests/sub_tls_late_selftest.py   (that build, unplanted)
     (SKIPPED without openssl to make the certificate)
"""
import json, os, shutil, socket, ssl, subprocess, sys, tempfile, time, types, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")   # SWG_SUB=<an older build>: see it red
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
WAIT = '''        log(LOG_INFO, "swg-sub: waiting for the panel's %s …" % _LOG_SERVE["path"])\n        for _ in range(30):\n'''
PLANTS = {   # name: (sections that must go red, anchor, planted text)
    "noservewait": (("[1]",), '''    if not os.path.exists(_LOG_SERVE["path"]):\n        log(LOG_INFO, "swg-sub: waiting for the panel''',
                    '''    if False:\n        log(LOG_INFO, "swg-sub: waiting for the panel'''),
    "unbounded":   (("[4]",), WAIT, WAIT.replace("for _ in range(30):", "while True:")),
}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))


if not shutil.which("openssl"):
    print("SKIPPED — no openssl here to make a certificate")
    sys.exit(0)
T = tempfile.mkdtemp(prefix="sub-tls-late-")
src = open(SUB, encoding="utf-8").read()
if PLANT:
    _secs, old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    src = src.replace(old, new)
PROGS = {"real": os.path.join(T, "swg-sub")}
open(PROGS["real"], "w", encoding="utf-8").write(src)
if src.count(WAIT) == 1 and PLANT != "unbounded":          # [4]'s copy: the serve.json wait cut to one look
    PROGS["one-look"] = os.path.join(T, "swg-sub-one-look")
    open(PROGS["one-look"], "w", encoding="utf-8").write(src.replace(WAIT, WAIT.replace("range(30)", "range(1)")))
else:
    assert os.environ.get("SWG_SUB") or PLANT == "unbounded", "the serve.json wait anchor is missing — [4] would measure nothing"
    PROGS["one-look"] = PROGS["real"]
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
DIRECT = {"enabled": False, "serve": {"host": "0.0.0.0", "port": 8444, "tls_mode": "selfsigned", "cert_path": "", "key_path": ""}}
RP = {"enabled": False, "serve": {"host": "0.0.0.0", "port": 8444, "tls_mode": "reverse-proxy", "cert_path": "", "key_path": ""}}


def make_pair(d):
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1",
                    "-subj", "/CN=sub.example", "-keyout", d + "/key.pem.tmp", "-out", d + "/fullchain.pem.tmp"],
                   capture_output=True, check=True)
    os.replace(d + "/fullchain.pem.tmp", d + "/fullchain.pem"); os.replace(d + "/key.pem.tmp", d + "/key.pem")


def start(prog="real", serve=None, pair=False):
    """The real swg-sub over a fresh state where the entrypoint has written fleet.json; serve.json and the pair only if asked."""
    d = tempfile.mkdtemp(dir=T); os.makedirs(d + "/subs"); os.makedirs(d + "/stats"); os.makedirs(d + "/tls")
    J = lambda rel, o: json.dump(o, open(os.path.join(d, rel), "w"))
    J("fleet.json", {"roster_path": d + "/users.json", "nodes_path": d + "/nodes.json", "stats_dir": d + "/stats", "sub_dir": d + "/subs"})
    J("users.json", {"users": {}, "peers": {}}); J("nodes.json", {"nodes": {}})
    if serve is not None:
        J("subs/serve.json", serve)
    if pair:
        make_pair(d + "/tls")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, SWG_SUB_FLEET=d + "/fleet.json", SWG_SUB_WEB=ROOT, SWG_SUB_HOST="127.0.0.1", SWG_SUB_PORT=str(port),
               SWG_SUB_TLS_DIR=d + "/tls")
    for k in ("JOURNAL_STREAM", "SWG_SUB_TLS_CERT", "SWG_SUB_TLS_KEY"):
        env.pop(k, None)
    log = open(d + "/log", "w")
    p = subprocess.Popen([sys.executable, PROGS[prog]], env=env, stdout=log, stderr=log)
    srv = types.SimpleNamespace(p=p, d=d, port=port, serve=lambda o: J("subs/serve.json", o), pair=lambda: make_pair(d + "/tls"))
    srv.log = lambda: open(d + "/log").read()
    return srv


def wait(cond, secs):
    end = time.monotonic() + secs
    while not cond() and time.monotonic() < end:
        time.sleep(0.1)
    return cond()


def answers(srv, scheme):
    try:
        urllib.request.urlopen("%s://127.0.0.1:%d/healthz" % (scheme, srv.port), timeout=2, context=CTX if scheme == "https" else None)
        return True
    except urllib.error.HTTPError:
        return True                                       # it answered (an error page is still that scheme speaking)
    except Exception:
        return False


RUNNING = []
try:
    SECTION[0] = "[1]"; print("[1] the fresh master's ordering: the pair and serve.json arrive after swg-sub started", flush=True)
    for first, then, gap in (("pair", "serve", 3), ("serve", "pair", 4)):
        s = start(); RUNNING.append(s)
        time.sleep(1)
        (s.pair if first == "pair" else lambda: s.serve(DIRECT))()
        time.sleep(gap)
        (s.pair if then == "pair" else lambda: s.serve(DIRECT))()
        wait(lambda: answers(s, "https") or " on http://" in s.log(), 12)
        check("%s first, %s %ds later → HTTPS from its first listen" % (first, then, gap), answers(s, "https"), s.log()[-400:])
        check("…never plain HTTP", " on http://" not in s.log() and not answers(s, "http"), s.log()[-400:])

    SECTION[0] = "[2]"; print("\n[2] serve.json says reverse-proxy", flush=True)
    s = start(); RUNNING.append(s)
    time.sleep(1)
    s.serve(RP)
    check("plain HTTP once serve.json is there, no certificate waited for",
          wait(lambda: answers(s, "http"), 8) and "no certificate yet" not in s.log() and " on http://" in s.log(), s.log()[-300:])

    SECTION[0] = "[3]"; print("\n[3] CONTROL: serve.json and the pair there at start", flush=True)
    s = start(serve=DIRECT, pair=True); RUNNING.append(s)
    check("HTTPS at once, nothing waited for", wait(lambda: answers(s, "https"), 5) and "waiting" not in s.log(), s.log()[-300:])

    SECTION[0] = "[4]"; print("\n[4] the wait is bounded", flush=True)
    s = start("one-look"); RUNNING.append(s)
    check("a panel that never writes serve.json: a listener anyway once the wait is over (plain HTTP, as before)",
          wait(lambda: answers(s, "http"), 8) and s.p.poll() is None, s.log()[-300:])
finally:
    for s in RUNNING:
        if s.p.poll() is None:
            s.p.terminate()
            try:
                s.p.wait(5)
            except subprocess.TimeoutExpired:
                s.p.kill()
    shutil.rmtree(T, ignore_errors=True)

print()
if PLANT:
    want = PLANTS[PLANT][0]
    red = sorted({sec for sec, _n in FAILS})
    ok = bool(red) and all(sec in want for sec in red)
    print("plant %s: %s — red in %s (expected %s)" % (PLANT, "RED as it must be" if ok else "NOT caught as it must be", red, list(want)))
    sys.exit(0 if ok else 1)
print("FAIL: %d — %s" % (len(FAILS), FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
