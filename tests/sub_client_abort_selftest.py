#!/usr/bin/env python3
"""Self-test — a client that goes away is not an error on the public subscription page (1.8.9 qualification HE-1).

swg-sub shares the `swg-panel` journal namespace with the panel (its logins, swg-netctl's results, the update output),
capped at the panel's log budget (16 MB at the least). Every client abort was an ERR traceback (~20 lines, kept at every
level but Off), and on the plain-HTTP server a bare connect + RST printed the stdlib's ~20-line block to stderr before any
limiter — so any client could rotate the panel's history out of that journal in minutes. Measured on 52aa9c4, 50 of each:
plain — aborted fetches 950 ERR lines, mid-body resets 950 stderr lines, bare RSTs 950 stderr lines; TLS — 375 ERR lines.

  [1] the REAL swg-sub, plain HTTP: N fetches of /_a/sub.js reset before the reply, N reset mid-body, N bare connect + RST
      → not one line written; /healthz still answers
  [2] the same with swg-sub's own TLS (a throwaway self-signed certificate; SKIPPED without openssl)
  [3] at Debug, an abort is ONE Debug line naming what broke — never a traceback, never at err
  [4] do_GET itself: a client abort raised from inside a reply (a reset, a broken pipe, a timeout, a TLS EOF) is one Debug
      line and no 500; any OTHER fault keeps its ERR traceback and its 500 — but at most one traceback a minute, the next
      one saying how many were held back

Idle connections (1.8.9 qualification R2 HELPERS-2): each held a thread and an fd — plain HTTP for ever (no socket timeout),
TLS 60 s — and at the soft fd limit (1024 on the bare unit) accept() failed with EMFILE: the serve loop spun a core and
/healthz and every link stopped answering. Measured on d0bad281 (limit 1024, 1100 idle): 1021 threads, 1024 fds, 99 % CPU,
/healthz timed out — plain still so 65 s later.

  [5] the REAL swg-sub, its fd limit the bare unit's 1024, 1100 idle connections (plain, then TLS): it holds at most its
      bound (one thread each) and closes every other one at once; its fds stay under half the limit, it does not spin, and
      once the attacker is gone the page answers
  [6] plain HTTP: each connection's socket timeout is the TLS server's 60 s (read from the program); lowered to 2 s in this
      run, 300 idle connections — the bound's worth held, the rest closed at once — are all let go, and /healthz answers
      while the attacker still holds every one of its sockets

Run: python3 tests/sub_client_abort_selftest.py      --plant abort-err | plain-loud | no-ratelimit | nobound | notimeout
                                                     (exit 0 when caught)
     SWG_SUB=<swg-sub of an older build> python3 tests/sub_client_abort_selftest.py   (that build, unplanted)
"""
import importlib.machinery, importlib.util, json, os, re, resource, shutil, socket, ssl, struct, subprocess, sys, tempfile, time
import types, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")   # SWG_SUB=<an older build>: see it red
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {   # name: (sections that must go red, anchor, planted text)
    "abort-err":    (("[1]", "[2]", "[3]", "[4]"), "        except (ConnectionError, TimeoutError, socket.timeout, ssl.SSLError) as e:\n",
                     "        except () as e:\n"),
    # the stdlib's own server in plain mode: loud again (HE-1), and without the connection bound (HELPERS-2) — [5] plain
    "plain-loud":   (("[1]", "[3]", "[5]"), "        srv = _QuietServer((host, port), Handler)\n",
                     "        srv = ThreadingHTTPServer((host, port), Handler)\n"),
    "no-ratelimit": (("[4]",), "                due = now - last >= 60\n", "                due = True\n"),
    "nobound":      (("[5]",), "        return threading.active_count() <= self.max_conns", "        return True"),
    "notimeout":    (("[6]",), "\n    timeout = 60\n", "\n    timeout = None\n"),
}
FAILS, SECTION = [], [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

T = tempfile.mkdtemp(prefix="sub-abort-")
src = open(SUB, encoding="utf-8").read()
if PLANT:
    _secs, old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    src = src.replace(old, new)
SUBP = os.path.join(T, "swg-sub"); open(SUBP, "w", encoding="utf-8").write(src)
N = 20
REQ = b"GET /_a/sub.js HTTP/1.1\r\nHost: x\r\n\r\n"
FDS = 1024        # [5][6]: swg-sub's fd limit — the bare unit's soft limit (its unit sets no LimitNOFILE)
# [6]: the same program run with its handler's socket timeout lowered — only ever LOWERED: a copy that sets none keeps none
LOWER = ("import importlib.machinery as m, importlib.util as u, sys\n"
         "ld = m.SourceFileLoader('swgsub', sys.argv[1]); M = u.module_from_spec(u.spec_from_loader('swgsub', ld)); ld.exec_module(M)\n"
         "if M.Handler.timeout is not None:\n    M.Handler.timeout = float(sys.argv[2])\n"
         "M.main()\n")


def serve(tls, debug=False, nofile=None, lower=None):
    d = tempfile.mkdtemp(dir=T); os.makedirs(d + "/subs/blobs"); os.makedirs(d + "/stats")
    J = lambda rel, o: json.dump(o, open(os.path.join(d, rel), "w"))
    J("fleet.json", {"roster_path": d + "/users.json", "nodes_path": d + "/nodes.json", "stats_dir": d + "/stats", "sub_dir": d + "/subs"})
    J("subs/serve.json", {"enabled": True, **({"log": {"level": "info", "debug_until": -1}} if debug else {})})
    J("users.json", {"users": {}, "peers": {}}); J("nodes.json", {"nodes": {}})
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, SWG_SUB_FLEET=d + "/fleet.json", SWG_SUB_WEB=ROOT, SWG_SUB_HOST="127.0.0.1", SWG_SUB_PORT=str(port),
               SWG_SUB_TLS_DIR=d + "/no-tls")
    env.pop("JOURNAL_STREAM", None)
    if tls:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1",
                        "-subj", "/CN=127.0.0.1", "-keyout", d + "/key.pem", "-out", d + "/cert.pem"], capture_output=True, check=True)
        env.update(SWG_SUB_TLS_CERT=d + "/cert.pem", SWG_SUB_TLS_KEY=d + "/key.pem")
    out, err = open(d + "/stdout", "w"), open(d + "/stderr", "w")
    p = subprocess.Popen([sys.executable, SUBP] if lower is None else [sys.executable, "-I", "-c", LOWER, SUBP, str(lower)],
                         env=env, stdout=out, stderr=err,
                         preexec_fn=(lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))) if nofile else None)
    ctx = None
    if tls:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    origin = ("https" if tls else "http") + "://127.0.0.1:%d" % port
    for _ in range(100):
        try:
            urllib.request.urlopen(origin + "/healthz", timeout=1, context=ctx); break
        except Exception:
            time.sleep(0.1)
    srv = types.SimpleNamespace(p=p, d=d, port=port, ctx=ctx, origin=origin)
    srv.lines = lambda: (open(d + "/stdout").read().splitlines(), open(d + "/stderr").read().splitlines())
    srv.healthz = lambda: urllib.request.urlopen(origin + "/healthz", timeout=2, context=ctx).status
    time.sleep(0.3)
    return srv


def _rst(c):
    c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)); c.close()


def clients(srv, kind):
    for _ in range(N):
        try:
            if kind == "rst":
                c = socket.create_connection(("127.0.0.1", srv.port)); _rst(c); continue
            c = socket.socket(); c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096); c.connect(("127.0.0.1", srv.port))
            if srv.ctx:
                c = srv.ctx.wrap_socket(c, server_hostname="127.0.0.1")
            c.send(REQ)
            if kind == "mid":
                c.recv(4096); time.sleep(0.02)
            _rst(c)
        except Exception:
            pass
        time.sleep(0.01)
    time.sleep(0.8)


def run_server_cases(tls, label):
    srv = serve(tls)
    try:
        o0, e0 = srv.lines()
        for kind, what in (("early", "fetches of sub.js reset before the reply"), ("mid", "fetches reset mid-body"),
                           ("rst", "bare connect + RST, no request at all")):
            a0, b0 = srv.lines()
            clients(srv, kind)
            a1, b1 = srv.lines()
            new = a1[len(a0):] + b1[len(b0):]
            check("%s: %d %s → not one line written" % (label, N, what), not new, new[:6])
        check("%s: …and the page still answers" % label, srv.healthz() == 200)
    finally:
        srv.p.terminate(); srv.p.wait(5)


def attack(srv, n):
    # n idle connections, as an attacker holds them: connected, not one byte sent. Paced 0.5 ms apart with a 5 s connect
    # timeout — swg-sub listens with the stdlib's backlog of 5, and a connector that outruns its accept loop has its SYN
    # dropped and retried a second later. One that still fails: the listener stopped accepting (its fds ran out), and the
    # rest would only wait the same.
    socks = []
    for _ in range(n):
        c = socket.socket(); c.settimeout(5)
        try:
            c.connect(("127.0.0.1", srv.port))
        except OSError:
            c.close(); break
        c.setblocking(False); socks.append(c)
        time.sleep(0.0005)
    return socks


def closed(socks):
    # how many of them the server has closed (its FIN, or a reset) — peeked, never waited for
    k = 0
    for c in socks:
        try:
            k += c.recv(1, socket.MSG_PEEK) == b""
        except BlockingIOError:
            pass
        except OSError:
            k += 1
    return k


def proc(pid):
    # the server's threads, open fds and CPU seconds so far
    thr = int(re.search(r"^Threads:\s+(\d+)", open("/proc/%d/status" % pid).read(), re.M).group(1))
    f = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
    return thr, len(os.listdir("/proc/%d/fd" % pid)), (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")


def until(cond, secs):
    end = time.monotonic() + secs
    while not cond():
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)
    return True


def hz(srv):
    try:
        return srv.healthz()
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


try:
    SECTION[0] = "[1]"; print("[1] the real swg-sub, plain HTTP", flush=True)
    run_server_cases(False, "plain")

    SECTION[0] = "[2]"; print("\n[2] the real swg-sub, its own TLS", flush=True)
    if shutil.which("openssl"):
        run_server_cases(True, "TLS")
    else:
        print("  SKIPPED [2] — no openssl here to make a certificate")

    SECTION[0] = "[3]"; print("\n[3] at Debug", flush=True)
    srv = serve(False, debug=True)
    try:
        a0, b0 = srv.lines()
        clients(srv, "early")
        a1, b1 = srv.lines()
        new = a1[len(a0):] + b1[len(b0):]
        dbg = [l for l in new if "a client went away" in l]
        check("an abort is one Debug line naming what broke (%d aborts → %d lines)" % (N, len(dbg)),
              dbg and len(dbg) <= N and all(l.startswith("D sub: a client went away before its reply was written (") for l in dbg), new[:4])
        check("…and nothing else: no traceback, nothing at err", len(new) == len(dbg) and not any(l.startswith("E ") for l in new), new[:6])
    finally:
        srv.p.terminate(); srv.p.wait(5)

    SECTION[0] = "[4]"; print("\n[4] do_GET, driven", flush=True)
    os.environ["SWG_SUB_FLEET"] = os.path.join(T, "none.json")
    ld = importlib.machinery.SourceFileLoader("swgsub_abort", SUBP)
    M = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgsub_abort", ld))
    ld.exec_module(M)
    LOGS, CLOCK = [], [1000.0]
    M.log = lambda prio, msg, *a: LOGS.append((prio, (msg % a) if a else msg))
    M.time = types.SimpleNamespace(monotonic=lambda: CLOCK[0], time=time.time)
    def get(exc):
        h = M.Handler.__new__(M.Handler)
        sent = []
        def route():
            raise exc
        h._route, h._send = route, (lambda code, *a, **k: sent.append(code))
        h.do_GET()
        return sent
    for exc in (ConnectionResetError(104, "Connection reset by peer"), BrokenPipeError(32, "Broken pipe"),
                TimeoutError("The write operation timed out"), socket.timeout("timed out"),
                ssl.SSLEOFError(8, "EOF occurred in violation of protocol")):
        del LOGS[:]
        sent = get(exc)
        check("a client abort (%s) → one Debug line, no traceback, no 500" % type(exc).__name__,
              LOGS == [(M.LOG_DEBUG, "sub: a client went away before its reply was written (%s)" % type(exc).__name__)] and sent == [],
              (LOGS, sent))
    del LOGS[:]
    sent = []
    for i in range(5):                                   # five faults inside one minute
        CLOCK[0] = 2000.0 + i * 10
        sent += get(RuntimeError("a fault #%d" % i))
    errs = [m for p, m in LOGS if p == M.LOG_ERR]
    check("a real fault keeps its traceback and its 500 — five in one minute → ONE traceback, five 500s",
          len(errs) == 1 and "RuntimeError: a fault #0" in errs[0] and "Traceback" in errs[0] and sent == [500] * 5, (len(errs), sent))
    CLOCK[0] = 2061.0
    get(RuntimeError("a fault #5"))
    errs = [m for p, m in LOGS if p == M.LOG_ERR]
    check("…a minute on, the next one is written, saying how many were held back",
          len(errs) == 2 and "RuntimeError: a fault #5" in errs[1] and "(4 more since the last one were not written)" in errs[1],
          errs[1:][:1])

    SECTION[0] = "[5]"; print("\n[5] 1100 idle connections, swg-sub's fd limit the bare unit's %d" % FDS, flush=True)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)        # room for the attacker's own 1100 sockets
    if soft < 4096 and (hard == resource.RLIM_INFINITY or hard >= 4096):
        resource.setrlimit(resource.RLIMIT_NOFILE, (4096, hard))
    room = resource.getrlimit(resource.RLIMIT_NOFILE)[0] >= 1600
    BOUND = getattr(M._QuietServer, "max_conns", 0)               # the program's own bound (0: a build without one)
    for tls, label in ((False, "plain"), (True, "TLS")):
        if not room or (tls and not shutil.which("openssl")):
            print("  SKIPPED [5] %s — %s" % (label, "no openssl here to make a certificate" if room else
                                               "this gate cannot hold 1100 sockets here (its own fd limit)"))
            continue
        srv, socks = serve(tls, nofile=FDS), []
        try:
            socks = attack(srv, 1100)
            until(lambda: len(socks) - closed(socks) <= BOUND, 15)   # those above the bound: at once (none timed out in 60 s)
            held = len(socks) - closed(socks)
            thr0, fds0, cpu0 = proc(srv.p.pid); time.sleep(2); thr1, fds1, cpu1 = proc(srv.p.pid)
            check("%s: all 1100 connected" % label, len(socks) == 1100, "%d — the listener stopped accepting" % len(socks))
            check("%s: …it holds its bound (%d), one thread each — every other one closed at once" % (label, BOUND),
                  BOUND and BOUND // 2 <= held <= BOUND and max(thr0, thr1) <= BOUND + 1,
                  "held %d, threads %d/%d" % (held, thr0, thr1))
            check("%s: …its fds under half the limit (%d of %d): accept() cannot meet EMFILE" % (label, max(fds0, fds1), FDS),
                  max(fds0, fds1) <= FDS // 2)
            check("%s: …and it does not spin (%.2f s of CPU in 2 s)" % (label, cpu1 - cpu0), cpu1 - cpu0 < 1.0)
            for c in socks:
                c.close()
            check("%s: the attacker gone, /healthz answers" % label, until(lambda: hz(srv) == 200, 10), hz(srv))
        finally:
            for c in socks:
                c.close()
            srv.p.terminate(); srv.p.wait(5)

    SECTION[0] = "[6]"; print("\n[6] plain HTTP: an idle connection is let go after the socket timeout", flush=True)
    check("each connection's socket timeout is the TLS server's 60 s, plain HTTP included (Handler.timeout)",
          M.Handler.timeout == 60, M.Handler.timeout)
    srv, socks = serve(False, nofile=FDS, lower=2), []             # the same program, its timeout lowered to 2 s in this run
    try:
        socks = attack(srv, 300)
        check("300 idle connections (the bound's worth held, the rest closed at once): all let go after the timeout",
              len(socks) == 300 and until(lambda: closed(socks) == len(socks), 20),
              "%d connected, %d let go" % (len(socks), closed(socks)))
        check("…the server's threads: its serve loop's alone again", until(lambda: proc(srv.p.pid)[0] == 1, 5), proc(srv.p.pid)[0])
        check("…and /healthz answers while the attacker still holds every one of its sockets", hz(srv) == 200, hz(srv))
    finally:
        for c in socks:
            c.close()
        srv.p.terminate(); srv.p.wait(5)
finally:
    shutil.rmtree(T, ignore_errors=True)

print()
if PLANT:
    secs = PLANTS[PLANT][0]
    red = [n for s, n in FAILS if s in secs]
    stray = sorted({s for s, n in FAILS if s not in secs})
    print("plant %s: %s" % (PLANT, ("NOT CAUGHT — the gate is blind to it" if not red else
                                     ("ALSO red outside its sections: " + ", ".join(stray)) if stray else "RED as it must be (%d)" % len(red))))
    sys.exit(0 if red and not stray else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
