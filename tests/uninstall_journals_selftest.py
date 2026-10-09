#!/usr/bin/env python3
"""Self-test — a FULL uninstall takes swg's own journals and every trace of its logging; kept data keeps the journals.

1.8.9 qualification, LC-24 L8-a / L8-c (Ubuntu 24.04 VMs): every FULL uninstall — a pure bare box too — left
/var/log/journal/<machine-id>.swg-panel and .swg-node: swg's whole log history (logins, netctl, updates) on a box the
operator asked to wipe, never rotated again once no journald@swg-* runs. rm_log_ns did `rm -rf` them, but their journald
was left running (and socket-activated), so the directory came back. The Docker removal path never ran rm_log_ns at all:
a converted box kept four bare-era swg-ns.conf template drop-ins, an empty swg-update.service.d, the Docker-era
swg-update.service.d/swg-log.conf and swg-logs.

The REAL functions of uninstall.sh (rm_log_ns, _swg_left, _data_kept, rm_log_journals) run in a sandbox root: every path
they touch is rewritten under a temp dir, systemctl and docker are stubs, and a journald model writes the namespace's
journal again after the run for as long as its journald is still loaded — what the VMs showed.

  [1] a pure bare node, FULL: rm_node's rm_log_ns, then the end of the run — the swg-node journal is gone and STAYS gone
      (journald@swg-node's two sockets and its service stopped before the directory goes), every swg-ns / swg-log drop-in,
      the restart back-off swg-noded writes beside them on systemd < 254 (swg-restart.conf, 1.8.9 qualification D12-1), the
      size file and swg-logs gone; the box's MAIN journal untouched; the summary names it under Removed
  [2] a converted box, the Docker removal path, FULL (no rm_log_ns): the bare-era template drop-ins, the Docker-era
      swg-log.conf, the empty swg-update.service.d, swg-logs, both namespaces' journals and their journald@ config — gone
  [3] keep-data (a bare master's, a Docker data dir's): the journals stay WITH their history and their journald is not
      stopped; the summary says so under Kept; the drop-ins of the removed units still go
  [4] something of swg's is kept (a turn proxy still logs into swg-node): nothing is touched
  [5] a dry run removes nothing

Run: python3 tests/uninstall_journals_selftest.py        (0 = pass)
     SWG_UNINSTALL=<file>   run it against another uninstall.sh (the shipped one: red on [1] [2] [3])
     --perturb-ns     the namespace directories are not removed → RED on [1] [2]
     --perturb-stop   their journald is not stopped first → RED on [1] [2]
     --perturb-keep   kept data does not keep the journals → RED on [3]
     --perturb-left   a kept swg component does not hold the teardown back → RED on [4]
     --perturb-restart  swg-noded's swg-restart.conf (systemd < 254's back-off, D12-1) is left → RED on [1] [2] [3]
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = open(os.environ.get("SWG_UNINSTALL") or os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
FLAGS = {f: f in sys.argv[1:] for f in ("--perturb-ns", "--perturb-stop", "--perturb-keep", "--perturb-left", "--perturb-restart")}
PERTURBED = any(FLAGS.values())

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# The functions AS SHIPPED: rm_log_ns through the end of rm_log_journals (a file without rm_log_journals: rm_log_ns alone).
i = SRC.index("\nrm_log_ns(){") + 1
j = SRC.index("\n}\n", SRC.index("\nrm_log_journals(){") if "\nrm_log_journals(){" in SRC else i) + 3
FN = SRC[i:j]
if "\nrm_log_journals(){" not in SRC:
    FN += '_swg_left(){ return 1; }\nrm_log_journals(){ :; }   # (this uninstall.sh has no end-of-run step)\n'
for flag, old, new in (("--perturb-ns", '      [ -n "$mid" ] && rmrf "/var/log/journal/$mid.$ns" "/run/log/journal/$mid.$ns"\n', '      :\n'),
                       ("--perturb-stop", '      [ -n "$u" ] && { run systemctl stop $u 2>/dev/null || true; }', '      :'),
                       ("--perturb-keep", '_data_kept(){ [ "${KEEP_OWN_DROPINS:-no}" = yes ]', '_data_kept(){ return 1; [ "${KEEP_OWN_DROPINS:-no}" = yes ]'),
                       ("--perturb-left", '_swg_left(){ local f\n', '_swg_left(){ local f; return 1\n'),
                       ("--perturb-restart", ' "$SD"/*.d/swg-restart.conf \\\n', ' \\\n')):
    if FLAGS[flag]:
        assert FN.count(old) == 1, "perturbation anchor missing — would FALSE-PASS: " + old.strip()[:60]
        FN = FN.replace(old, new)

def sandbox(files, loaded=(), docker=()):
    """A root with these files (path → content; a path ending in / is an empty dir), these journald units loaded."""
    t = tempfile.mkdtemp(prefix="unj-")
    ur = os.path.join(t, "root")
    for p, c in files.items():
        full = os.path.join(ur, p)
        if p.endswith("/"):
            os.makedirs(full, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(full), exist_ok=True); open(full, "w").write(c)
    open(os.path.join(t, "loaded"), "w").write("".join(u + "\n" for u in loaded))
    open(os.path.join(t, "docker"), "w").write("".join(c + "\n" for c in docker))
    return t, ur

def run_uninstall(t, ur, body, dry=False, env=""):
    fn = FN
    for a in ("/run/", "/etc/systemd/journald@", "/etc/machine-id", "/etc/swg-panel", "/var/lib/swg-panel", "/var/log/journal",
              "/usr/local/bin/swg-logs"):   # /run/ first: the root itself may sit under /run (a TMPDIR there)
        fn = fn.replace(a, ur + a)
    sh = ('set -uo pipefail\nT=%s\nDRYRUN=%s\nSD=%s/etc/systemd/system\nDOCKER_DIR=%s/opt/swg-panel-docker\n%s\n'
          'DID_REMOVE=(); DID_KEEP=()\n'
          'run(){ echo "RUN $*" >> "$T/calls"; if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }\n'
          'rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then run rm -rf "$p"; fi; done; }\n'
          'rmdir_if_empty(){ local d="$1"; [ -d "$d" ] || return 0; [ -n "$(ls -A "$d" 2>/dev/null)" ] && return 0; run rmdir "$d"; }\n'
          'info(){ :; }; ok(){ :; }; warn(){ :; }; b(){ printf %%s "$*"; }\n'
          'docker_running(){ grep -qx "$1" "$T/docker"; }\n'
          'systemctl(){ case "$1" in\n'
          '  list-units) shift; local p u; for u in $(cat "$T/loaded"); do for p in "$@"; do case "$p" in -*) continue;; esac\n'
          '      case "$u" in $p) echo "$u loaded active running x"; break;; esac; done; done;;\n'
          '  stop) shift; local u; for u in "$@"; do echo "STOP $u" >> "$T/calls"; grep -vxF "$u" "$T/loaded" > "$T/l2"; mv "$T/l2" "$T/loaded"; done;;\n'
          '  *) echo "SYSTEMCTL $*" >> "$T/calls";; esac; return 0; }\n'
          '%s\n%s\n'
          'printf "REMOVED=%%s\\n" "${DID_REMOVE[@]-}"; printf "KEPT=%%s\\n" "${DID_KEEP[@]-}"\n') % (
        t, "true" if dry else "false", ur, ur, env, fn, body)
    r = subprocess.run(["bash", "-c", sh], capture_output=True, text=True)
    # the journald model: one still loaded keeps (or writes again) its namespace's journal after the run
    for ns in ("swg-panel", "swg-node"):
        if ("systemd-journald@%s.service" % ns) in open(os.path.join(t, "loaded")).read().split():
            d = os.path.join(ur, "var/log/journal/MID.%s" % ns); os.makedirs(d, exist_ok=True)
            f = os.path.join(d, "system.journal")
            if not os.path.exists(f): open(f, "w").write("NEW")
    calls = open(os.path.join(t, "calls")).read() if os.path.exists(os.path.join(t, "calls")) else ""
    return r, calls

def left(ur):
    """Every file left, and every EMPTY directory of ours (a drop-in dir, a namespace journal or its config) — the box's
    own directories (/etc/systemd/system, /usr/local/bin …) exist on every box and are not ours to remove."""
    ours = lambda d: d.endswith(".d") or d.endswith((".swg-panel", ".swg-node")) or d.startswith("journald@")
    return sorted(os.path.relpath(os.path.join(dp, x), ur) for dp, ds, fs in os.walk(ur) for x in fs + [d + "/" for d in ds
                  if ours(d) and not os.listdir(os.path.join(dp, d))])

JD = lambda ns: ("systemd-journald@%s.service" % ns, "systemd-journald@%s.socket" % ns, "systemd-journald-varlink@%s.socket" % ns)
MAIN = {"etc/machine-id": "MID\n", "var/log/journal/MID/system.journal": "MAIN", "var/log/journal/MID/user-1000.journal": "MAIN"}
NODE_TRACES = {"etc/systemd/system/swg-noded.service.d/swg-ns.conf": "x", "etc/systemd/system/vk-turn-proxy-.service.d/swg-ns.conf": "x",
               "etc/systemd/system/swg-relay@.service.d/swg-ns.conf": "x", "etc/systemd/system/swg-wdtt-.service.d/swg-ns.conf": "x",
               "etc/systemd/system/swg-csqtt-.service.d/swg-ns.conf": "x",
               # the flat restart back-off swg-noded writes on systemd < 254 (1.8.9 qualification D12-1) — two of its three families
               "etc/systemd/system/vk-turn-proxy-.service.d/swg-restart.conf": "x", "etc/systemd/system/swg-csqtt-.service.d/swg-restart.conf": "x",
               "run/systemd/system/vk-turn-proxy-.service.d/swg-log.conf": "x", "run/systemd/system/awg-quick@awg0.service.d/swg-log.conf": "x",
               "run/systemd/journald@swg-node.conf.d/swg.conf": "x", "var/log/journal/MID.swg-node/system.journal": "HISTORY",
               "usr/local/bin/swg-logs": "x"}
RM_NODE = 'rm_log_ns swg-node swg-noded.service swg-relay@.service vk-turn-proxy-.service swg-wdtt-.service swg-csqtt-.service\n'
RM_PANEL = 'rm_log_ns swg-panel swg-panel-server.service swg-sub.service swg-netctl.service swg-update.service\n'
swg_left = lambda ur: [p for p in left(ur) if not p.startswith(("etc/machine-id", "var/log/journal/MID/"))]

print("[1] a pure bare node, FULL uninstall")
t, ur = sandbox(dict(MAIN, **NODE_TRACES), loaded=JD("swg-node"))
r, calls = run_uninstall(t, ur, RM_NODE + "rm_log_journals\n")
check("the swg-node journal is gone, and stays gone after the run (its journald does not write it again)",
      not os.path.exists(os.path.join(ur, "var/log/journal/MID.swg-node")), swg_left(ur))
st = [l for l in calls.splitlines() if l.startswith("STOP ")]
rm_at = calls.find("MID.swg-node")
check("journald@swg-node's two sockets and its service were stopped — before its journal was removed",
      sorted(l[5:] for l in st) == sorted(JD("swg-node")) and rm_at > calls.rfind("STOP "), calls[-600:])
check("every swg-ns / swg-log drop-in, the size file and swg-logs are gone — nothing of swg's logging is left",
      [p for p in swg_left(ur) if not p.startswith("var/log/journal/")] == [], swg_left(ur))
check("the box's MAIN journal is untouched", open(os.path.join(ur, "var/log/journal/MID/system.journal")).read() == "MAIN"
      and os.path.exists(os.path.join(ur, "var/log/journal/MID/user-1000.journal")), left(ur))
check("the summary names it under Removed", "REMOVED=swg's own journals (swg-node)" in r.stdout, r.stdout + r.stderr)
shutil.rmtree(t, ignore_errors=True)

print("\n[2] a converted box, the Docker removal path (rm_log_ns never runs), FULL")
CONV = dict(MAIN, **{k: v for k, v in NODE_TRACES.items() if not k.startswith("etc/systemd/system/swg-noded")})
CONV.update({"etc/systemd/system/swg-update.service.d/": "", "etc/systemd/system/swg-netctl-docker.service.d/swg-log.conf": "x",
             "run/systemd/system/swg-update.service.d/swg-log.conf": "x", "run/systemd/journald@swg-panel.conf.d/swg.conf": "x",
             "var/log/journal/MID.swg-panel/system.journal": "HISTORY"})
t, ur = sandbox(CONV, loaded=JD("swg-node") + JD("swg-panel"))
r, calls = run_uninstall(t, ur, "rm_log_journals\n", env="DOCKER_DATA_DEL=yes; DOCKER_KEEP_CONFS=no")
check("the four bare-era template drop-ins, the Docker-era swg-log.conf drop-ins and the empty swg-update.service.d are gone",
      not [p for p in left(ur) if p.startswith(("etc/systemd/system/", "run/systemd/system/"))], left(ur))
check("…swg-logs and both namespaces' journald@ config are gone",
      not [p for p in left(ur) if "swg-logs" in p or "journald@" in p], left(ur))
check("both namespaces' journals are gone and stay gone (swg-panel's journald stopped too)",
      not any(os.path.exists(os.path.join(ur, "var/log/journal/MID." + ns)) for ns in ("swg-panel", "swg-node"))
      and all(("STOP " + u) in calls for u in JD("swg-panel")), swg_left(ur))
check("the box's MAIN journal is untouched", open(os.path.join(ur, "var/log/journal/MID/system.journal")).read() == "MAIN")
shutil.rmtree(t, ignore_errors=True)

print("\n[3] keep-data: the journals stay, with their history")
for name, env, extra, body in (("a bare master that keeps the panel's data", "KEEP_OWN_DROPINS=yes", {"var/lib/swg-panel/users.json": "{}"},
                                RM_NODE + RM_PANEL),
                               ("a Docker install whose data dir is kept", "DOCKER_DATA_DEL=no", {"opt/swg-panel-docker/data/lib/x": "x"}, "")):
    files = dict(MAIN, **NODE_TRACES, **extra)
    files.update({"var/log/journal/MID.swg-panel/system.journal": "HISTORY", "run/systemd/journald@swg-panel.conf.d/swg.conf": "x"})
    t, ur = sandbox(files, loaded=JD("swg-node") + JD("swg-panel"))
    r, calls = run_uninstall(t, ur, body + "rm_log_journals\n", env=env)
    kept = [open(os.path.join(ur, "var/log/journal/MID.%s/system.journal" % ns)).read()
            if os.path.exists(os.path.join(ur, "var/log/journal/MID.%s/system.journal" % ns)) else None for ns in ("swg-panel", "swg-node")]
    check("%s: both journals stay WITH their history, their journald not stopped" % name,
          kept == ["HISTORY", "HISTORY"] and "STOP " not in calls, (kept, calls[-300:]))
    check("%s: the summary says so (Kept)" % name, "KEPT=swg's own journals (swg-panel, swg-node) — kept with the data" in r.stdout,
          r.stdout + r.stderr)
    check("%s: the removed units' drop-ins and swg-logs still go" % name,
          not [p for p in left(ur) if p.startswith(("etc/systemd/system/", "run/systemd/system/")) or "swg-logs" in p], left(ur))
    shutil.rmtree(t, ignore_errors=True)

print("\n[4] a kept swg component still logs into the namespace: nothing is touched")
files = dict(MAIN, **NODE_TRACES); files["etc/systemd/system/vk-turn-proxy-anton48-56000.service"] = "[Service]\n"
t, ur = sandbox(files, loaded=JD("swg-node"))
r, calls = run_uninstall(t, ur, "rm_log_journals\n")
_j = os.path.join(ur, "var/log/journal/MID.swg-node/system.journal")
check("its journal, the drop-ins and swg-logs stay, its journald is not stopped",
      os.path.exists(_j) and open(_j).read() == "HISTORY" and "STOP " not in calls
      and os.path.exists(os.path.join(ur, "etc/systemd/system/vk-turn-proxy-.service.d/swg-ns.conf"))
      and os.path.exists(os.path.join(ur, "usr/local/bin/swg-logs")), (calls[-300:], left(ur)))
shutil.rmtree(t, ignore_errors=True)

print("\n[5] a dry run")
t, ur = sandbox(dict(MAIN, **NODE_TRACES), loaded=JD("swg-node"))
before = left(ur)
r, calls = run_uninstall(t, ur, "rm_log_journals\n", dry=True)
check("removes nothing, stops nothing, and says what it would do",
      left(ur) == before and "STOP " not in calls and ("[dry] rm -rf " + ur + "/usr/local/bin/swg-logs" in r.stdout
                                                       or "\nrm_log_journals(){" not in SRC),
      (r.stdout[-400:], calls[-200:]))
shutil.rmtree(t, ignore_errors=True)

print("")
if PERTURBED:
    sect = {"--perturb-ns": ("the swg-node journal is gone", "journald@swg-node's two sockets", "both namespaces' journals"),
            "--perturb-stop": ("the swg-node journal is gone", "journald@swg-node's two sockets", "both namespaces' journals"),
            "--perturb-keep": ("a bare master", "a Docker install"), "--perturb-left": ("its journal, the drop-ins",),
            "--perturb-restart": ("every swg-ns / swg-log drop-in", "the four bare-era", "a bare master", "a Docker install")}
    want = tuple(p for f, on in FLAGS.items() if on for p in sect[f])
    red = [f for f in FAILS if f.startswith(want)]
    ok = bool(red) and len(red) == len(FAILS)
    print("perturb: %s" % ("RED as it must be (%d), all in the targeted sections" % len(red) if ok
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % [f for f in FAILS if f not in red]))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
