#!/usr/bin/env python3
"""Self-test — on a box carrying BOTH panels, removing one leaves the other working.

guard_second_panel (lib/common.sh) parks one panel when a panel of the other method would answer beside it: a bare one
disabled + stopped, a docker one stopped with restart=no. Removing either side with the uninstaller then broke the one
that stayed (1.8.8 qualification, R8 on q5 — a bare host with a docker host installed beside it):

  N1  removing the (parked) BARE panel deleted the live DOCKER panel's one-click updater (swg-update, swg-update-check,
      swg-update.{service,timer}) and its address helper (swg-netctl-docker.*) — rm_panel removed both unconditionally;
      the docker panel's Update then wrote its trigger and nothing ran. The summary said only "Kept: Docker panel".
  N3  removing the DOCKER panel left the kept bare panel disabled + stopped — nothing answered on its ports — and
      docker_cleanup_if_last deleted the same shared updater. The summary said "Kept: Bare-metal swg-panel".
  e   a node sign-off that could not reach its panel printed python's raw `<urlopen error [Errno 111] …>` above the
      friendly warning; one the panel refused printed a bare "HTTP 401" and then "Couldn't reach the panel".

  [1] bare panel removed, docker panel still here → the updater and swg-netctl-docker.* stay, nothing disables them
  [2] bare panel removed, no docker → the updater and both helper families go (unchanged)
  [3] docker panel removed last, bare panel kept → the updater stays
  [4] docker panel removed last, no bare panel → the updater goes (unchanged)
  [5] which panel is parked is read before anything is removed (bare parked for docker, docker parked for bare)
  [6] the kept bare panel parked for the removed docker panel is started again (+ swg-sub), and the summary says so
  [7] …not while the docker panel is still here, and not a bare panel nobody parked
  [8] the kept docker panel parked for the removed bare panel is started again (restart policy back to unless-stopped)
  [9] a sign-off that cannot reach the panel says why in ONE line; one the panel refuses says it was refused

rm_panel, rm_updater_if_last, docker_cleanup_if_last, unpark_kept_panel, the parked-panel detection and _goodbye_post are
lifted out of uninstall.sh AS SHIPPED; absolute paths are moved under a temp root, systemctl / docker are stubs.

Run: python3 tests/uninstall_two_panels_selftest.py      (0 = pass)
     --perturb   the shipped behaviour planted back (updater + docker helper always removed, nothing un-parked,
                 the raw error printed) → RED
"""
import http.server, os, re, socket, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(a, b):
    global U
    assert U.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    U = U.replace(a, b)

if PERTURB:
    plant("  docker_running swg-panel || for _nc in swg-netctl-docker.path", "  for _nc in swg-netctl-docker.path")
    plant("  docker_running swg-panel || rmrf $SD/swg-netctl-docker.service", "  rmrf $SD/swg-netctl-docker.service")
    plant('  if { [ "${1:-}" != bare-gone ] && { [ -d /opt/swg-panel ] || [ -f "$SD/swg-panel-server.service" ]; }; } \\\n'
          '     || docker_running swg-panel || docker_running swg-node; then return 0; fi\n', "")
    plant('unpark_kept_panel(){\n  local _lbl="" _how="" _why=""\n', 'unpark_kept_panel(){\n  return 0\n')
    plant('    print(r[:1].lower() + r[1:]); sys.exit(1)', '    sys.stderr.write(str(e) + "\\n"); sys.exit(1)')
    plant('    print("HTTP %s" % e.code); sys.exit(3)', '    sys.stderr.write("HTTP %s\\n" % e.code); sys.exit(1)')

def fn(name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), U, re.M)
    assert m, "cannot extract " + name
    lines = U[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

DETECT = U[U.index("_ctr_parked(){"):U.index("# swg-netctl units lingering WITHOUT")]

def rooted(text, t):
    """Every absolute path the functions touch, moved under the temp root t (/dev/null stays where it is)."""
    for p in ("/opt/", "/etc/", "/var/", "/usr/local/bin/"):
        text = text.replace(p, t + p)
    return text

PRE = ('set -uo pipefail\nDRYRUN=false; DOMAIN=""\ninfo(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ :; }\n'
       'b(){ printf %s "$*"; }\nc(){ :; }\nrun(){ "$@"; }\nrmrf(){ local p; for p in "$@"; do [ -e "$p" ] || [ -L "$p" ] && rm -rf "$p"; done; return 0; }\n'
       'ask_yn(){ printf -v "$3" no; }\nufw_forget(){ :; }\ndocker_rm_project_networks(){ :; }\napply_full_data_fate(){ :; }\n'
       'docker_running(){ command -v docker >/dev/null 2>&1 && docker ps -a --format "{{.Names}}" 2>/dev/null | grep -qx "$1"; }\n')

UPDATER = ("sd/swg-update.service", "sd/swg-update.timer", "usr/local/bin/swg-update", "usr/local/bin/swg-update-check",
           "var/lib/swg-update.stamp")
DHELPER = ("sd/swg-netctl-docker.service", "sd/swg-netctl-docker.path", "sd/swg-netctl-docker.timer",
           "usr/local/bin/swg-netctl-docker")
BHELPER = ("sd/swg-netctl.service", "sd/swg-netctl.path", "sd/swg-netctl.timer", "usr/local/bin/swg-netctl")

def box(containers=(), inspect="true unless-stopped", enabled=False, files=()):
    """A temp root holding `files`, with docker reporting `containers` (inspect → `inspect`) and systemctl reporting
    swg-panel-server enabled or not. Every stub call is logged to <root>/calls."""
    t = tempfile.mkdtemp(prefix="twopanels-")
    for f in files:
        p = os.path.join(t, f)
        if f.endswith("/"):
            os.makedirs(p, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write("x\n")
    os.makedirs(os.path.join(t, "sd"), exist_ok=True)
    stub = os.path.join(t, "stub"); os.makedirs(stub)
    log = os.path.join(t, "calls")
    bodies = {
        "systemctl": 'case "$*" in *"is-enabled --quiet swg-panel-server"*) exit %d;; esac\nexit 0' % (0 if enabled else 1),
        # `docker ps` answers in ONE write, like the real client (strace: docker ps --format writes once). bash's own echo
        # and printf write a line at a time, and under pipefail a `grep -q` that has already matched can SIGPIPE the next
        # write — a flake of the stub, never of docker. cat writes once.
        "docker": ('case "$1" in\n  ps) cat <<\'CEOF\'\n%sCEOF\n  ;;\n  inspect) case "$*" in *-f*) echo "%s";; esac;;\n'
                   '  compose) exit 1;;\nesac\nexit 0') % ("".join(c + "\n" for c in containers), inspect),
        "nginx": "exit 0", "ufw": "exit 0", "userdel": "exit 0",
    }
    for n, b in bodies.items():
        p = os.path.join(stub, n)
        open(p, "w").write('#!/bin/bash\necho "%s $*" >> %s\n%s\n' % (n, log, b)); os.chmod(p, 0o755)
    return t

def run(t, script):
    r = subprocess.run(["bash", "-c", PRE + "SD=%s/sd; DOCKER_DIR=%s/opt/swg-panel-docker\n%s" % (t, t, script)],
                       capture_output=True, text=True, env=dict(os.environ, PATH=t + "/stub:" + os.environ["PATH"]))
    calls = open(os.path.join(t, "calls")).read() if os.path.exists(os.path.join(t, "calls")) else ""
    return r.stdout + r.stderr, calls

def present(t, rels):
    return [r for r in rels if os.path.exists(os.path.join(t, r))]

BARE = ("sd/swg-panel-server.service", "opt/swg-panel/", "sd/swg-sub.service") + BHELPER
RM_PANEL = lambda t: rooted(fn("rm_updater_if_last") + fn("rm_panel"), t) + "rm_panel\n"

print("[1] removing the bare panel while a docker panel is on the box keeps the docker panel's updater + helper")
t = box(containers=("swg-panel", "swg-sub"), files=BARE + UPDATER + DHELPER)
out, calls = run(t, RM_PANEL(t))
check("the bare panel itself is gone", not present(t, ("sd/swg-panel-server.service", "opt/swg-panel/")), out)
check("…the one-click updater stays (swg-update, swg-update-check, swg-update.{service,timer}, the stamp)",
      present(t, UPDATER) == list(UPDATER), present(t, UPDATER))
check("…the docker address helper stays (swg-netctl-docker.* + its binary)", present(t, DHELPER) == list(DHELPER), present(t, DHELPER))
check("…and neither was disabled on the way", "swg-update.timer" not in calls and "swg-netctl-docker" not in calls, calls)
check("…the bare panel's own helper goes as before", not present(t, BHELPER), present(t, BHELPER))

print("\n[2] removing the only panel on the box takes the updater and both helper families, as before")
t = box(files=BARE + UPDATER + DHELPER)
out, calls = run(t, RM_PANEL(t))
check("updater gone", not present(t, UPDATER), present(t, UPDATER))
check("…both helper families gone (a leftover docker pair from an earlier convert included)",
      not present(t, DHELPER + BHELPER), present(t, DHELPER + BHELPER))
check("…the updater timer disabled", "systemctl disable --now swg-update.timer" in calls, calls)

CLEAN = lambda t: rooted(fn("rm_updater_if_last") + fn("docker_cleanup_if_last"), t) + "docker_cleanup_if_last\n"
print("\n[3] the docker panel removed last while a bare panel stays keeps the updater — it is the bare panel's too")
t = box(files=("sd/swg-panel-server.service", "opt/swg-panel/") + UPDATER)
out, calls = run(t, CLEAN(t))
check("updater stays", present(t, UPDATER) == list(UPDATER), (present(t, UPDATER), out))
check("…not disabled", "swg-update.timer" not in calls, calls)

print("\n[4] the docker panel removed last with no bare panel takes the updater, as before")
t = box(files=UPDATER)
out, calls = run(t, CLEAN(t))
check("updater gone", not present(t, UPDATER), present(t, UPDATER))

print("\n[5] which panel is parked is read before anything is removed")
def detect(**kw):
    t = box(files=("sd/swg-panel-server.service",), **kw)
    out, _ = run(t, "DPANEL=%s\n%s\necho BARE=$_BARE_PARKED DOCKER=$_DOCKER_PARKED\n"
                 % ("true" if kw.get("containers") else "false", DETECT))
    return out.strip().splitlines()[-1] if out.strip() else out
for want, why, kw in (
        ("BARE=true DOCKER=false", "bare disabled beside a live docker panel → the bare one is parked",
         dict(containers=("swg-panel",), inspect="true unless-stopped", enabled=False)),
        ("BARE=false DOCKER=true", "docker stopped with restart=no beside an enabled bare panel → the docker one is parked",
         dict(containers=("swg-panel",), inspect="false no", enabled=True)),
        ("BARE=false DOCKER=false", "bare disabled with no docker panel → the operator's own stop, not a park",
         dict(containers=(), enabled=False)),
        ("BARE=false DOCKER=false", "both stopped → neither is un-parked by the other's removal",
         dict(containers=("swg-panel",), inspect="false no", enabled=False)),
        ("BARE=false DOCKER=false", "both live (kept both) → nothing parked",
         dict(containers=("swg-panel",), inspect="true unless-stopped", enabled=True))):
    check(why, detect(**kw) == want, detect(**kw))

UNPARK = lambda t: rooted(fn("unpark_kept_panel"), t)
print("\n[6] the kept bare panel parked for the removed docker panel is started again")
t = box(files=("sd/swg-panel-server.service", "sd/swg-sub.service"))
out, calls = run(t, UNPARK(t) + '_BARE_PARKED=true; _DOCKER_PARKED=false\nDID_KEEP=("Bare-metal swg-panel")\n'
                 'unpark_kept_panel\nprintf "KEPT=%s\\n" "${DID_KEEP[@]}"\n')
check("systemctl enable --now swg-panel-server", "systemctl enable --now swg-panel-server" in calls, calls)
check("…and its swg-sub (parked with it)", "systemctl enable --now swg-sub" in calls, calls)
check("…said when it happens", "Bare-metal swg-panel started again" in out and "that panel is gone now" in out, out)
check("…and in the summary's Kept line", "KEPT=Bare-metal swg-panel — started again (it had been stopped while the Docker panel answered at the same address)" in out, out)

print("\n[7] …but not while the docker panel is still here, and not a bare panel nobody parked")
t = box(containers=("swg-panel",), files=("sd/swg-panel-server.service",))
out, calls = run(t, UNPARK(t) + '_BARE_PARKED=true; _DOCKER_PARKED=false\nDID_KEEP=()\nunpark_kept_panel\n')
check("docker panel kept too → the bare panel stays parked", "enable" not in calls, calls)
t = box(files=("sd/swg-panel-server.service",))
out, calls = run(t, UNPARK(t) + '_BARE_PARKED=false; _DOCKER_PARKED=false\nDID_KEEP=()\nunpark_kept_panel\n')
check("not parked (the operator stopped it) → left alone", "enable" not in calls, calls)

print("\n[8] the kept docker panel parked for the removed bare panel is started again")
t = box(containers=("swg-panel", "swg-sub"), inspect="false no")
out, calls = run(t, UNPARK(t) + '_BARE_PARKED=false; _DOCKER_PARKED=true\nDID_KEEP=("Docker panel (swg-panel)")\n'
                 'unpark_kept_panel\nprintf "KEPT=%s\\n" "${DID_KEEP[@]}"\n')
for c in ("swg-panel", "swg-sub"):
    check("%s: restart policy back to unless-stopped, then started" % c,
          "docker update --restart=unless-stopped %s" % c in calls and "docker start %s" % c in calls, calls)
check("…said, in the run and in the summary", "Docker panel (swg-panel) started again" in out
      and "KEPT=Docker panel (swg-panel) — started again" in out, out)
t = box(containers=("swg-panel",), inspect="false no", files=("sd/swg-panel-server.service",))
out, calls = run(t, UNPARK(t) + '_BARE_PARKED=false; _DOCKER_PARKED=true\nDID_KEEP=()\nunpark_kept_panel\n')
check("…not while the bare panel is still here", "docker start" not in calls, calls)

print("\n[9] a node sign-off that fails says why in one line")
GB = fn("_goodbye_post")
def goodbye(url):
    t = box()
    out, _ = run(t, GB + '_goodbye_post "%s" tok-1234567890 no\n' % url)
    return out
s = socket.socket(); s.bind(("127.0.0.1", 0)); closed = s.getsockname()[1]; s.close()
out = goodbye("http://127.0.0.1:%d" % closed)
check("nothing reaches the panel → \"Couldn't reach the panel (connection refused)\"",
      "Couldn't reach the panel (connection refused)" in out, out)
check("…and python's raw error is not printed", "urlopen error" not in out and "Errno" not in out, out)
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers()
    def log_message(self, *a):
        pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
out = goodbye("http://127.0.0.1:%d" % srv.server_address[1])
srv.shutdown()
check("the panel answers 401 → it says the panel turned it down, not that it couldn't be reached",
      "The panel turned the sign-off down (HTTP 401)" in out and "Couldn't reach" not in out, out)
check("…with no bare \"HTTP 401\" line of its own", not any(l.strip() == "HTTP 401" for l in out.splitlines()), out)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
