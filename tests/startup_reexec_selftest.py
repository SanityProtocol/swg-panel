#!/usr/bin/env python3
"""Self-test — the startup re-exec that stops swg-panel-server and swg-noded keeping their own AST for life.

CPython frees a script's parse arena only when the script finishes, and main() never returns, so each daemon kept
its whole AST resident (~80 MB of the panel's ~130). Both files now open with the same prologue: a plain script run
replaces itself, in place, with `python3 -c <_SWG_LOADER> <sys.path[0]> <file> [args]`, which loads the file through
compile() (runpy.run_path) and drops the AST. Startup then trims the freed heap (_release_startup_memory).

Every probe here is the SHIPPED prologue (cut from the file, up to its `_swg_reexec(...)` call) followed by a body that
reports what the program would see; each result is compared with the same body run as a plain script — CPython's own
answer. A probe is started the way systemd starts the daemons: its path exec'd, the shebang naming the interpreter.

  [1] the prologue is the same text in both files
  [2] the re-exec keeps the PID, argv (spaces, empty args), __file__, sys.path[0] (symlinks too), __main__
  [3] anything unusual keeps the old way, byte for byte: interpreter options, SWG_NO_REEXEC, a failed exec
  [4] it cannot loop, and the cwd is never on sys.path while the loader imports
  [5] the panel's server start holds SIGHUP across the exec (an acme reload in that window used to kill it)
  [6] _release_startup_memory gives the compile heap back, and does nothing where it cannot
  [7] noded's lock message still names another swg-noded — old command line and new
  [8] the real panel: re-exec'd, serving, under 90 MB, a second one refused by name, SWG_NO_REEXEC serves too

Run: python3 tests/startup_reexec_selftest.py           (0 = pass)
     SWG_TEST_PYTHON=/path/to/python3 …    the probes with another interpreter (default: this one)
     --perturb-path0     the loader leaves the cwd first on sys.path → RED
     --perturb-loop      the second load loses both marks → RED (it would exec forever)
     --perturb-exec      a failed exec is not caught → RED
     --perturb-sighup    the panel no longer holds SIGHUP across the exec → RED
     --perturb-options   interpreter options no longer keep the old way → RED
"""
import ast, json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MODE = next((a for a in sys.argv[1:] if a.startswith("--perturb")), "")
PY = os.environ.get("SWG_TEST_PYTHON") or sys.executable
PYV = tuple(json.loads(subprocess.run([PY, "-c", "import sys,json;print(json.dumps(sys.version_info[:2]))"],
                                      capture_output=True, text=True, check=True).stdout))
SRC = {p: open(os.path.join(ROOT, p), encoding="utf-8").read() for p in ("swg-panel-server", "swg-noded")}

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

START = "# ── Run through compile(), not the script runner"
def prologue(prog):
    """The shipped file from its first line through the prologue's own `_swg_reexec(...)` call."""
    s = SRC[prog]
    m = re.search(r'^_swg_reexec\(.*\n', s[s.index(START):], re.M)
    assert m, "cannot find the prologue's call in " + prog
    return s[:s.index(START) + m.end()]

def perturbed(text):
    if MODE == "--perturb-path0":
        text = plant(text, "\"sys.path[:1]=[d]if sys.path[:1]==['']else sys.path[:1];\"", '""')
    if MODE == "--perturb-loop":
        text = plant(text, "{'_SWG_REEXEC':1}", "{}")
        text = plant(text, 'if globals().get("_SWG_REEXEC") or _SWG_LOADER in getattr(sys, "orig_argv", ()):',
                     "if False:")
    if MODE == "--perturb-exec":
        text = plant(text, "    except OSError:\n        if held is not None:", "    except ZeroDivisionError:\n        if held is not None:")
    if MODE == "--perturb-sighup":
        text = plant(text, "        signal.signal(signal.SIGHUP, signal.SIG_IGN)\n", "")
    if MODE == "--perturb-options":
        text = plant(text, "        if sys.orig_argv[1:] != sys.argv:\n            return\n", "        pass\n")
        text = plant(text, "            if subprocess._args_from_interpreter_flags():\n                return\n",
                     "            pass\n")
    return text

BODY = r'''
import json as _j, signal as _s
_h = _s.getsignal(_s.SIGHUP)
print(_j.dumps({
    "argv": sys.argv, "file": __file__, "path0": sys.path[0] if sys.path else None, "name": __name__,
    "reexec": bool(globals().get("_SWG_REEXEC")), "pid": os.getpid(),
    "loader": b"runpy.run_path" in open("/proc/self/cmdline", "rb").read(),
    "hup": int(_h) if isinstance(_h, int) else str(_h),
    "main_ok": sys.modules["__main__"].__dict__ is globals(),
    "flags": [sys.flags.optimize, sys.flags.dont_write_bytecode, sys.flags.verbose, sys.flags.no_user_site,
              sys.flags.ignore_environment, sys.flags.isolated, sys.flags.bytes_warning],
    "warn": sys.warnoptions,
    "unbuf": bool(getattr(sys.stdout, "write_through", False)),
}))
'''

T = tempfile.mkdtemp(prefix="reexec-")
REAL = os.path.join(T, "real"); os.mkdir(REAL)
os.symlink(REAL, os.path.join(T, "linkdir"))                           # a symlinked DIRECTORY
NOWHERE = os.path.join(T, "cwd"); os.mkdir(NOWHERE)                     # a cwd with planted stdlib names
for mod in ("pkgutil", "runpy"):
    with open(os.path.join(NOWHERE, mod + ".py"), "w") as f:
        f.write("open(%r, 'a').write(%r)\nraise ImportError('shadow')\n" % (os.path.join(T, "SHADOWED"), mod + " "))

def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o755)
    return path

SHEBANG = "#!" + PY + "\n"
def make(prog, text_fn=lambda t: t):
    """probe-<prog> (the shipped prologue + BODY) and plain-<prog> (BODY alone), side by side in REAL."""
    pro = prologue(prog).split("\n", 1)[1]                              # drop the shipped shebang: ours names PY
    probe = write(os.path.join(REAL, "probe-" + prog), SHEBANG + text_fn(perturbed(pro)) + BODY)
    plain = write(os.path.join(REAL, "plain-" + prog), SHEBANG + "import os, sys\n" + BODY)
    return probe, plain

def dfl_hup():
    signal.signal(signal.SIGHUP, signal.SIG_DFL)                       # whatever ran this test, start the probe clean

def run(argv, cwd=NOWHERE, env=None, timeout=5 if MODE == "--perturb-loop" else 30):
    e = dict(os.environ); e.pop("SWG_NO_REEXEC", None); e.update(env or {})
    p = subprocess.Popen(argv, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         preexec_fn=dfl_hup)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill(); p.communicate()
        return None, p.pid, "TIMEOUT (it kept exec-ing, or hung)"
    try:
        return json.loads(out.strip().splitlines()[-1]), p.pid, err
    except Exception:
        return None, p.pid, "rc=%s out=%r err=%r" % (p.returncode, out[-300:], err[-600:])

def same_as_plain(r, g, probe, plain, strict_argv0=True):
    """r (probe) matches g (plain) once each one's own file name is swapped for the other."""
    if r is None or g is None:
        return False, "no result: %r / %r" % (r, g)
    sub = lambda v: json.loads(json.dumps(v).replace(os.path.basename(plain), os.path.basename(probe)))
    g = sub(g); diffs = []
    for k in ("file", "path0", "name", "main_ok", "flags", "warn", "unbuf"):
        if r[k] != g[k]:
            diffs.append("%s: %r != %r" % (k, r[k], g[k]))
    if r["argv"][1:] != g["argv"][1:]:
        diffs.append("argv[1:]: %r != %r" % (r["argv"][1:], g["argv"][1:]))
    a0_ok = r["argv"][0] == g["argv"][0] or (not strict_argv0 and r["argv"][0] == r["file"])
    if not a0_ok:
        diffs.append("argv[0]: %r != %r" % (r["argv"][0], g["argv"][0]))
    return not diffs, "; ".join(diffs)

print("python %d.%d (%s)" % (PYV + (PY,)))

# ── [1] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] one prologue")
blocks = {p: prologue(p)[SRC[p].index(START):] for p in SRC}
body = {p: re.sub(r'^_swg_reexec\(.*\n', "", b, flags=re.M) for p, b in blocks.items()}
check("[1] the prologue (loader + _swg_reexec) is the same text in the panel and noded",
      body["swg-panel-server"] == body["swg-noded"])
check("[1] the panel holds SIGHUP only for the server start (no arguments); noded never",
      "_swg_reexec(hold_sighup=len(sys.argv) == 1)" in blocks["swg-panel-server"]
      and "\n_swg_reexec()\n" in blocks["swg-noded"])
check("[1] the files keep ONE `if __name__ == \"__main__\":` — the line test loaders cut the source at",
      all(SRC[p].count("\nif __name__ ==") == 1 and SRC[p].rstrip().endswith("main()") for p in SRC))
check("[1] nothing but the shebang and the docstring runs before the prologue",
      all(not [n for n in ast.parse(SRC[p][:SRC[p].index(START)]).body
               if not (isinstance(n, ast.Expr) and isinstance(n.value, (ast.Constant, getattr(ast, "Str", ast.Constant))))]
          for p in SRC))

# ── [2] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[2] the re-exec keeps what the program sees")
for prog in SRC:
    probe, plain = make(prog)
    args = ["a b", "", "--x=1", "ü"]
    r, pid, err = run([probe] + args, cwd="/")
    g, _, _ = run([plain] + args, cwd="/")
    ok, why = same_as_plain(r, g, probe, plain)
    check("[2] %s: absolute launch — argv (a space, an empty arg, non-ASCII), __file__, sys.path[0], __main__" % prog,
          ok, why or err)
    check("[2] %s: it re-exec'd, in place (same PID, the loader in its command line)" % prog,
          bool(r) and r["reexec"] and r["loader"] and r["pid"] == pid, (r, pid, err))
    r, _, err = run(["./" + os.path.basename(probe), "x"], cwd=REAL)
    g, _, _ = run(["./" + os.path.basename(plain), "x"], cwd=REAL)
    ok, why = same_as_plain(r, g, probe, plain, strict_argv0=False)
    check("[2] %s: relative launch from its own dir" % prog, ok and r["reexec"], why or err)
    lp = os.path.join(T, "linkdir", os.path.basename(probe)); lg = os.path.join(T, "linkdir", os.path.basename(plain))
    os.symlink(lp, os.path.join(T, "l-probe-" + prog)); os.symlink(lg, os.path.join(T, "l-plain-" + prog))
    r, _, err = run([os.path.join(T, "l-probe-" + prog)])
    g, _, _ = run([os.path.join(T, "l-plain-" + prog)])
    ok, why = same_as_plain(r, g, "l-probe-" + prog, "l-plain-" + prog)
    check("[2] %s: a symlink to the script in a symlinked dir — sys.path[0] is CPython's own (realpath)" % prog,
          ok and r["reexec"], why or err)

# ── [3] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[3] anything unusual keeps the old way")
for prog in SRC:
    probe, plain = make(prog)
    for opts in (["-O"], ["-W", "ignore"], ["-u"], ["-B"]):
        r, _, err = run([PY] + opts + [probe, "x"])
        g, _, _ = run([PY] + opts + [plain, "x"])
        ok, why = same_as_plain(r, g, probe, plain)
        check("[3] %s: interpreter option %s → the plain script run, same flags" % (prog, " ".join(opts)),
              ok and not r["reexec"] and not r["loader"], why or (r, err))
    r, _, err = run([probe, "x"], env={"PYTHONDONTWRITEBYTECODE": "1"})
    g, _, _ = run([plain, "x"], env={"PYTHONDONTWRITEBYTECODE": "1"})
    ok, why = same_as_plain(r, g, probe, plain)
    check("[3] %s: an option from the ENVIRONMENT reaches the program either way (3.10+ re-execs, older keeps the old way)"
          % prog, ok and r["reexec"] == (PYV >= (3, 10)), why or (r, err))
    r, _, err = run([probe, "x"], env={"SWG_NO_REEXEC": "1"})
    g, _, _ = run([plain, "x"])
    ok, why = same_as_plain(r, g, probe, plain)
    check("[3] %s: SWG_NO_REEXEC=1 → the plain script run" % prog, ok and not r["reexec"] and not r["loader"], why or err)
    fp, _ = make(prog, lambda t: t.replace("os.execv(sys.executable,", "os.execv(%r," % os.path.join(T, "no-such-python")))
    r, pid, err = run([fp], cwd="/")                                   # no arguments: the panel holds SIGHUP first
    g, _, _ = run([plain], cwd="/")
    ok, why = same_as_plain(r, g, fp, plain)
    check("[3] %s: an exec that fails → this process carries on, unchanged (SIGHUP back at its default)" % prog,
          ok and not r["reexec"] and r["hup"] == 0 and r["pid"] == pid, why or (r, err))

# ── [4] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[4] no loop, no cwd on sys.path")
for prog in SRC:
    if PYV >= (3, 10):
        lp, _ = make(prog, lambda t: t.replace("{'_SWG_REEXEC':1}", "{}"))
        r, _, err = run([lp, "x"])
        check("[4] %s: with the globals mark gone, sys.orig_argv alone stops a second exec" % prog,
              bool(r) and r["loader"] and not r["reexec"], (r, err))
    probe, _ = make(prog)
    r, _, err = run([probe, "x"])
    check("[4] %s: one exec, then the program" % prog, bool(r) and r["reexec"], (r, err))
    if os.path.exists(os.path.join(T, "SHADOWED")):
        os.unlink(os.path.join(T, "SHADOWED"))
    r, _, err = run([probe, "x"], cwd=NOWHERE)
    shadowed = open(os.path.join(T, "SHADOWED")).read() if os.path.exists(os.path.join(T, "SHADOWED")) else ""
    check("[4] %s: a pkgutil.py/runpy.py in the cwd is never imported (the script's dir replaces '' first)" % prog,
          bool(r) and r["reexec"] and not shadowed, (shadowed, r, err))

# ── [5] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[5] SIGHUP across the exec")
probe, _ = make("swg-panel-server")
r, _, err = run([probe])
check("[5] the panel's server start: SIGHUP ignored until main() installs its handler", bool(r) and r["hup"] == 1, (r, err))
r, _, err = run([probe, "passwd"])
check("[5] `swg-panel-server passwd`: SIGHUP left at its default (swg-passwd inherits nothing new)",
      bool(r) and r["hup"] == 0, (r, err))
probe, _ = make("swg-noded")
r, _, err = run([probe])
check("[5] noded: SIGHUP left at its default (its children inherit nothing new)", bool(r) and r["hup"] == 0, (r, err))
main_src = SRC["swg-panel-server"][SRC["swg-panel-server"].index("\ndef main():"):]
check("[5] the panel's main() still installs its SIGHUP handler right after the passwd check",
      main_src.index("signal.signal(signal.SIGHUP, _sighup_reload)") < main_src.index("_assert_node_door()"))

# ── [6] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[6] _release_startup_memory")
for prog in SRC:
    m = re.search(r"^def _release_startup_memory\(\):\n.*?(?=^\S)", SRC[prog], re.M | re.S)
    helper = m.group(0)                                                 # (no ast: the panel's source needs 3.8 to parse)
    code = helper + r'''
import gc, sys
def rss():
    for l in open("/proc/self/status"):
        if l.startswith("VmRSS"): return int(l.split()[1]) // 1024
c = compile(open(sys.argv[1]).read(), sys.argv[1], "exec"); gc.collect()
b = rss(); _release_startup_memory(); print(b, rss())
'''
    r = subprocess.run([PY, "-c", code, os.path.join(ROOT, "swg-noded")], capture_output=True, text=True)
    try:
        before, after = map(int, r.stdout.split())
    except Exception:
        before = after = 0
    try:
        glibc = (os.confstr("CS_GNU_LIBC_VERSION") or "").startswith("glibc")
    except (AttributeError, ValueError, OSError):
        glibc = False
    check("[6] %s: the compile heap goes back (RSS %s → %s MB)" % (prog, before, after),
          (0 < after < before * 0.8) if glibc else r.returncode == 0, r.stderr[-400:])
    r = subprocess.run([PY, "-c", "import sys; sys.modules['ctypes'] = None\n" + helper +
                        "\n_release_startup_memory(); print('ok')"], capture_output=True, text=True)
    check("[6] %s: without ctypes it does nothing and raises nothing" % prog, r.stdout.strip() == "ok", r.stderr[-400:])
    check("[6] %s: malloc_trim is called with its real signature (size_t pad → int)" % prog,
          "trim.argtypes, trim.restype = (ctypes.c_size_t,), ctypes.c_int" in helper)

# ── [7] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[7] noded names the holder of its state lock")
LD = tempfile.mkdtemp(prefix="reexec-lock-")
LOCKER = ("import fcntl,os,sys,time;fd=os.open(%r,os.O_WRONLY|os.O_CREAT,0o600);fcntl.flock(fd,fcntl.LOCK_EX);"
          "print('ready',flush=True);time.sleep(60)") % os.path.join(LD, ".noded.lock")
oldform = write(os.path.join(LD, "swg-noded"), "#!" + PY + "\n" + LOCKER.replace(";", "\n") + "\n")
holders = [("the re-exec's command line", [PY, "-c", LOCKER, "/opt/swg-noded", "/opt/swg-noded/swg-noded"], True),
           ("the plain script run", [PY, oldform], True),
           ("a stranger", [PY, "-c", LOCKER, "/srv/other-tool"], False)]
probe_code = r'''
import importlib.machinery, importlib.util, os, sys
os.environ["SWG_NODED_STATE"] = sys.argv[1]
spec = importlib.util.spec_from_loader("noded_reexec_t", importlib.machinery.SourceFileLoader("noded_reexec_t", sys.argv[2]))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
try:
    m._lock_state_dir(); print("TOOK THE LOCK")
except SystemExit as e:
    print(e)
'''
for label, argv, ours in holders:
    h = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
    h.stdout.readline()
    r = subprocess.run([PY, "-c", probe_code, LD, os.path.join(ROOT, "swg-noded")], capture_output=True, text=True)
    h.kill(); h.wait()
    want = ("another swg-noded (pid %d)" % h.pid) if ours else ("pid %d (`" % h.pid)
    check("[7] held by %s → %s" % (label, "named as another swg-noded" if ours else "named by its command line"),
          want in r.stdout, (r.stdout.strip()[-300:], r.stderr[-300:]))

# ── [8] ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[8] the real panel")
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def panel(state, port, env=None):
    os.makedirs(state, exist_ok=True)
    fleet = os.path.join(state, "fleet.json")
    with open(fleet, "w") as f:
        json.dump({"nodes_path": state + "/nodes.json", "roster_path": state + "/users.json",
                   "panel_settings_path": state + "/panel-settings.json", "stats_dir": state + "/stats",
                   "config_dir": state + "/configs"}, f)
    e = dict(os.environ, SWG_PANEL_FLEET=fleet, SWG_PANEL_WEB=ROOT, SWG_PANEL_HOST="127.0.0.1",
             SWG_PANEL_PORT=str(port), SWG_PANEL_AUTH="", SWG_PANEL_TLS_CERT="", SWG_PANEL_TLS_KEY="")
    e.pop("SWG_NO_REEXEC", None); e.update(env or {})
    return subprocess.Popen([os.path.join(ROOT, "swg-panel-server")], cwd=state, env=e,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, preexec_fn=dfl_hup)

def healthz(port, wait=40):
    import urllib.request
    end = time.time() + wait
    while time.time() < end:
        try:
            return urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2).status
        except Exception:
            time.sleep(0.3)
    return None

def rss_of(pid):
    try:
        return next(int(l.split()[1]) // 1024 for l in open("/proc/%d/status" % pid) if l.startswith("VmRSS"))
    except Exception:
        return -1

if PYV < (3, 8):
    print("  (skipped: the panel needs Python >= 3.8)")
elif PY != sys.executable and os.path.realpath(shutil.which("python3") or "") != os.path.realpath(PY):
    print("  (skipped: the panel's shebang runs PATH's python3, not SWG_TEST_PYTHON)")
else:
    PS = tempfile.mkdtemp(prefix="reexec-panel-")
    port = free_port()
    a = panel(os.path.join(PS, "a"), port)
    try:
        code = healthz(port)
        time.sleep(1.0)
        cmd = open("/proc/%d/cmdline" % a.pid, "rb").read() if a.poll() is None else b""
        check("[8] the panel starts, re-exec'd in place, and answers /healthz", code == 200 and b"runpy.run_path" in cmd,
              (code, cmd[:200]))
        mb = rss_of(a.pid)
        check("[8] the started panel is under 90 MB (it held ~130 with its AST)", 0 < mb < 90, mb)
        b = panel(os.path.join(PS, "a"), free_port())
        out = b.communicate(timeout=40)[0]
        check("[8] a second panel on the same state dir is refused, the holder named as a swg-panel-server",
              "another swg-panel-server (pid %d)" % a.pid in out, out[-400:])
    finally:
        a.terminate()
        try:
            a.wait(timeout=10)
        except Exception:
            a.kill()
    port = free_port()
    c = panel(os.path.join(PS, "c"), port, {"SWG_NO_REEXEC": "1"})
    try:
        code = healthz(port)
        cmd = open("/proc/%d/cmdline" % c.pid, "rb").read() if c.poll() is None else b""
        check("[8] SWG_NO_REEXEC=1: the panel starts the old way and serves (%d MB)" % rss_of(c.pid),
              code == 200 and b"runpy" not in cmd and cmd.split(b"\0")[1:2] == [os.path.join(ROOT, "swg-panel-server").encode()],
              (code, cmd[:200]))
    finally:
        c.terminate()
        try:
            c.wait(timeout=10)
        except Exception:
            c.kill()
    shutil.rmtree(PS, ignore_errors=True)

shutil.rmtree(T, ignore_errors=True); shutil.rmtree(LD, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if MODE else ""))
sys.exit(2 if MODE else 0)
