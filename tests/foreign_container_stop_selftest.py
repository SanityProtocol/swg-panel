#!/usr/bin/env python3
"""Self-test: taking over a foreign WDTT / csqtt server that a CONTAINER supervises stops the container — or refuses.

Measured on a fresh NixOS native node (1.8.7 qualification PART 4, item A3): a csqtt server in a `restart: unless-stopped`
docker container, adopted from the panel. The take-over ran `host_sh("docker stop <id> >/dev/null 2>&1; :")`, and a
native NixOS unit's PATH carries no container CLI — rc 127, swallowed. It then SIGKILLed the process, read "gone" in the
instant before docker's restart policy relaunched it (0.7 s), reported success and installed ours beside it: two csqtt
servers on one port and one TUN name, the foreign one back on every boot. The WDTT take-over had the identical branch.
Podman made it worse: `libpod-<id>` cgroups did not read as a container at all, so nothing was even tried.

  [1] native node: the stop runs through the RESOLVED CLI (run([<abs>/docker, "stop", id])), never a bare `docker` in a
      shell; a podman container is stopped with podman; no CLI anywhere → a refusal that names the missing command
  [2] csqtt: a container whose stop FAILS is never signalled — a restart policy would hand the process straight back —
      and the take-over answers (False, why) with the CLI's own error; the caller's reconcile error carries it
  [3] csqtt: a stop that works → (True, ""), the TUN dropped, no signal sent
  [4] WDTT (_wdtt_adopt_seed): the same two outcomes — a failed container stop returns a refusal before any signal, a
      working one returns "" without a signal
  [5] a DOCKER node still stops it on the host (host_sh "docker stop …"), and a failure there is reported, not swallowed
  [6] _ctr_cli() does not cache a miss: a runtime installed after the node started is found on the next call

Hermetic: swg-noded is imported, every process call, signal and /proc read is stubbed. No root, no docker.
Run: python3 tests/foreign_container_stop_selftest.py      (0 = pass)
     --perturb=<name>  restores one part of the old code and expects RED: path | failsafe | wdtt | podman | cache
     --perturb         all of them at once ("PERTURB OK" exit 0 when something went red, exit 1 when nothing did)
"""
import importlib.machinery, importlib.util, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PERTURBATIONS = {
    # the stop goes back to a bare `docker` through the host shell, output swallowed
    "path": ('''        r = run([cli, "stop", cid], timeout=60)''',
             '''        r = host_sh("docker stop " + shlex.quote(cid) + " >/dev/null 2>&1; :", timeout=60)'''),
    # csqtt falls through to TERM/KILL when the container would not stop
    "failsafe": ('''        return False, why or ("container %s was stopped but the server is still running" % cid[:12])''', ""),
    # WDTT falls through to TERM/KILL when the container would not stop
    "wdtt": ('''        return ("couldn't stop the container that runs the existing WDTT server (" + (_why or "it kept running") +
                ") — nothing was taken over; adopt again once it is down")''', ""),
    # podman cgroups are not containers again
    "podman": ('''m = re.search(r"(docker|libpod)[-/]([0-9a-f]{12,64})", txt)''', '''m = re.search(r"(docker)[-/]([0-9a-f]{12,64})", txt)'''),
    # a miss is cached for the life of the process again
    "cache": ('''    if not _CTR_CLI["v"]:''', '''    if _CTR_CLI["v"] is None:'''),
}
ASKED = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--perturb=")]
WANT = list(PERTURBATIONS) if "--perturb" in sys.argv else ASKED
src, path = open(NODED).read(), NODED
if WANT:
    for name in WANT:
        frm, to = PERTURBATIONS[name]
        if src.count(frm) != 1:
            print("PERTURB FAILED — perturbation %r matched %d times, not 1: the anchor moved" % (name, src.count(frm)))
            sys.exit(1)
        src = src.replace(frm, to, 1)
    if "cache" in WANT:      # the old code also cached the fallback value itself
        src = src.replace('''            if found:
                _CTR_CLI["v"] = found
                break
    return _CTR_CLI["v"] or "docker"''', '''            if found:
                _CTR_CLI["v"] = found
                break
        _CTR_CLI["v"] = _CTR_CLI["v"] or "docker"
    return _CTR_CLI["v"] or "docker"''', 1)
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded_ctrstop", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_ctrstop", loader))
try:
    loader.exec_module(N)
except SystemExit:
    pass

CID = "f8be5385e878" + "0" * 52
R = lambda rc=0, out="", err="": types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

class Box:
    """One simulated node: which CLIs exist where, what the container runtime does on `stop`, whether the foreign
    server process is alive, and every call the code makes."""
    def __init__(self, kind="baremetal", clis=("/run/current-system/sw/bin/docker",), runtime="docker", stop_rc=0,
                 stop_err="", restart_policy=True):
        self.kind, self.clis, self.runtime, self.stop_rc, self.stop_err = kind, set(clis), runtime, stop_rc, stop_err
        self.restart_policy = restart_policy
        self.alive, self.runs, self.shs, self.kills = True, [], [], []
    def install(self):
        N.NODE_KIND = self.kind
        N._CTR_CLI["v"] = None
        N.shutil.which = lambda c: None                                   # the unit's PATH has no container CLI
        N.os.access = lambda p, m: p in self.clis
        def run(args, input_text=None, timeout=20):
            self.runs.append(list(args))
            if len(args) >= 3 and args[1] == "stop" and args[0] in self.clis:
                if self.stop_rc == 0:
                    self.alive = False
                return R(self.stop_rc, "", self.stop_err)
            if args[:3] == ["ip", "link", "delete"]:
                return R(0)
            return R(127, "", "%s: not found" % args[0])
        N.run = run
        def host_sh(cmd, timeout=90):
            self.shs.append(cmd)
            if cmd.startswith("docker stop"):
                if self.kind == "docker" and self.stop_rc == 0:
                    self.alive = False
                    return R(0)
                if self.kind == "docker":
                    return R(self.stop_rc, "", self.stop_err)
                return R(127, "", "sh: docker: command not found")         # a native unit's shell has no docker
            return R(0)
        N.host_sh = host_sh
        def kill(pid, sig):
            self.kills.append((pid, sig))
            self.alive = False
            if self.restart_policy:                                        # the container's restart policy relaunches it
                self.alive = True
        N.os.kill = kill
        N._pid_alive = lambda pid: self.alive
        N.time.sleep = lambda s: None
        cg = ("0::/system.slice/docker-%s.scope\n" % CID) if self.runtime == "docker" else \
             ("0::/machine.slice/libpod-%s.scope/container\n" % CID)
        real_open = open
        N.open = lambda p, *a, **k: (types.SimpleNamespace(read=lambda: cg, __enter__=None) if False else _Txt(cg)) \
            if str(p).startswith("/proc/") and str(p).endswith("/cgroup") else real_open(p, *a, **k)
        return self

class _Txt:
    def __init__(self, t): self.t = t
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.t

# ── csqtt: _csqtt_stop_foreign ────────────────────────────────────────────────────────────────────────────────────
def csqtt_box(**kw):
    b = Box(**kw).install()
    N._wdtt_hostproc_flush = lambda: None
    N._csqtt_scan_ok = lambda: True
    N._wdtt_unit_of_pid = lambda pid, host=False: ""
    N._csqtt_procs = lambda: [(4557, {"iface": "csqtf0", "config-dir": "/cfg"})] if b.alive else []
    return b

b = csqtt_box()
ok, why = N._csqtt_stop_foreign("csqtf0", "/cfg")
stops = [a for a in b.runs if a[1:2] == ["stop"]]
check("[1] native: the container is stopped through the resolved CLI, not a shell's `docker`",
      stops == [["/run/current-system/sw/bin/docker", "stop", CID]] and not any(s.startswith("docker") for s in b.shs), (b.runs, b.shs))
check("[3] csqtt: a working stop → (True, ''), no signal, the TUN dropped",
      (ok, why) == (True, "") and not b.kills and ["ip", "link", "delete", "dev", "csqtf0"] in b.runs, (ok, why, b.kills, b.runs))

b = csqtt_box(runtime="podman", clis=("/run/current-system/sw/bin/podman",))
ok, why = N._csqtt_stop_foreign("csqtf0", "/cfg")
check("[1] native: a podman container (libpod cgroup) is stopped with podman",
      ok and [a for a in b.runs if a[1:2] == ["stop"]] == [["/run/current-system/sw/bin/podman", "stop", CID]], (ok, why, b.runs))

b = csqtt_box(clis=())
ok, why = N._csqtt_stop_foreign("csqtf0", "/cfg")
check("[1] native: no container CLI anywhere → a refusal naming the missing command, no signal",
      ok is False and "no docker command" in why and not b.kills, (ok, why, b.kills))

b = csqtt_box(stop_rc=1, stop_err="Error response from daemon: permission denied")
ok, why = N._csqtt_stop_foreign("csqtf0", "/cfg")
check("[2] csqtt: a failed container stop is never followed by a signal (its restart policy would relaunch it)", not b.kills, b.kills)
check("[2] csqtt: …and the take-over answers False with the CLI's own error", ok is False and "permission denied" in why, (ok, why))
check("[2] csqtt: the foreign server is still the one running (nothing was taken over behind its back)", b.alive)

# the reconcile's error line carries the reason (the caller's text, read from source — the call site is not reachable hermetically)
check("[2] csqtt: reconcile reports WHY it could not stop the server",
      'couldn\'t stop the existing csqtt server (" + _why + ")' in src, "the reconcile error line no longer names the reason")

# ── WDTT: _wdtt_adopt_seed's stop step ─────────────────────────────────────────────────────────────────────────────
def wdtt_run(**kw):
    b = Box(**kw).install()
    root = tempfile.mkdtemp(prefix="ctrstop-wdtt-")
    srcdir = os.path.join(root, "foreign"); os.makedirs(srcdir)
    with open(os.path.join(srcdir, "wg-keys.dat"), "w") as f:
        f.write("\n".join(["QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWY="] * 4) + "\n")
    N.WDTT_ROOT = os.path.join(root, "ours")
    flags = {"iface": "wdtt7", "password": "ownerpw", "listen": "0.0.0.0:56070", "wg-port": "56071", "_server": True}
    N.wdtt_foreign_probe = lambda iface: {"pid": 5150, "config_dir": srcdir, "has_identity": True}
    N._wdtt_stage_foreign = lambda d, pid=None: ""
    N._wdtt_identity_ok = lambda p: os.path.isfile(p)
    N._wdtt_valid = lambda inst: True
    N._wdtt_fork = lambda inst: "amurcanov"
    binp = os.path.join(root, "server"); open(binp, "w").close()
    N._wdtt_bin_shared = lambda fk: binp
    N._wdtt_adopted_users = lambda d: {}
    N._wdtt_cmdline_flags = lambda pid: dict(flags) if b.alive else {}
    N._wdtt_flags_host = lambda pid: dict(flags) if b.alive else {}
    N._wdtt_is_server = lambda fl: bool(fl.get("_server"))
    N._wdtt_iface_of = lambda fl: fl.get("iface") or "wdtt0"
    N._wdtt_unit_of_pid = lambda pid, host=False: ""
    N._wdtt_hostproc_flush = lambda: None
    inst = {"iface": "wdtt7", "fork": "amurcanov"}
    return b, N._wdtt_adopt_seed(inst)

b, err = wdtt_run(stop_rc=125, stop_err="Error: No such container")
check("[4] WDTT: a failed container stop returns a refusal before any signal", err and "nothing was taken over" in err and not b.kills,
      (err, b.kills))
check("[4] WDTT: …naming the CLI's error", "No such container" in (err or ""), err)
b, err = wdtt_run()
check("[4] WDTT: a working stop → '' with no signal, via the resolved CLI",
      err == "" and not b.kills and ["/run/current-system/sw/bin/docker", "stop", CID] in b.runs, (err, b.kills, b.runs))

# ── a docker node stops it on the host ─────────────────────────────────────────────────────────────────────────────
b = Box(kind="docker").install()
okd, whyd = N._ctr_stop_foreign(CID, "docker")
check("[5] docker node: `docker stop` runs on the HOST through host_sh", okd and b.shs == ["docker stop " + CID], (okd, whyd, b.shs))
b = Box(kind="docker", stop_rc=1, stop_err="Cannot connect to the Docker daemon").install()
okd, whyd = N._ctr_stop_foreign(CID, "docker")
check("[5] docker node: a failed host-side stop is reported, not swallowed", okd is False and "Cannot connect" in whyd, (okd, whyd))

# ── _ctr_cli does not cache a miss ─────────────────────────────────────────────────────────────────────────────────
b = Box(clis=()).install()
first = N._ctr_cli()
b.clis.add("/run/current-system/sw/bin/docker")
second = N._ctr_cli()
check("[6] a container CLI installed after the first lookup is found on the next one (a miss is not cached)",
      first == "docker" and second == "/run/current-system/sw/bin/docker", (first, second))

print()
if WANT:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d check(s) went red" % (",".join(WANT), len(FAILS))) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
