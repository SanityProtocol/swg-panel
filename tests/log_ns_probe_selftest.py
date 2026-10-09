#!/usr/bin/env python3
"""Self-test — a LogNamespace= drop-in is written only where a unit can actually RUN in a journal namespace.

1.8.9 qualification IN-11 (V-LOGS F-3, nspawn with `--system-call-filter=~unshare`): where systemd runs but mount
namespaces are refused (an OpenVZ/Virtuozzo-like container, an LXC that denies unshare), a unit given the 1.8.9 drop-in
`[Service] LogNamespace=swg-…` exits 226/NAMESPACE while the same unit with 1.8.8's settings runs. Every writer only asked
whether journald's namespace TEMPLATE exists — it does there — so an update would have written the drop-ins and the
panel, noded, sub, netctl and update units (and every relay / turn / WDTT / csqtt unit from its next start) would not run.

Now a throwaway unit is run with LogNamespace=swg-probe once per boot (lib/common.sh, swg-noded, swg-netctl share the
answer in /run/swg-log-ns, under one lock); refused, no drop-in is written and any already there goes. Driven here on the
REAL functions with stubbed systemd-run / systemctl in a sandbox root (a refusal cannot be made on a normal host; the real
success path is measured in the qualification record):

  [1] lib/common.sh: refused → swg_log_ns_heal writes nothing and removes every swg-ns.conf there is (an operator's own
      drop-in stays), the answer is kept (a second ask starts no unit), the probe namespace is cleaned up (its journald
      stopped, its directory gone); ok → the drop-ins as before; no template → no probe; a dry run starts no unit
  [2] update.sh ensure_log_ns, refused: daemon-reload, a long-running unit the drop-in had failed is restarted, a oneshot
      only reset (its next tick runs), and it is said
  [3] install-host.sh / install-node.sh: every site that writes a drop-in clears them instead where the probe refuses
  [4] swg-noded: refused → log_ns_ok() False, the prefix drop-ins an earlier run wrote are removed (daemon-reload), the
      budget row reads unsupported with the reason; ok → the drop-ins are written as before
  [5] swg-netctl: refused → the budget is unsupported with the reason, no size file, no journald restart; ok → as before

Run: python3 tests/log_ns_probe_selftest.py        (0 = pass)
     SWG_SRC_ROOT=<dir>   run it against other copies of the files (the shipped ones: red on [1]–[5])
     --perturb-lib     lib/common.sh answers by the template alone again → RED on [1] [2]
     --perturb-noded   swg-noded answers by the template alone again → RED on [4]
     --perturb-netctl  swg-netctl answers by the template alone again → RED on [5]
     --perturb-clear   a refusal removes nothing (lib, noded) → RED on [1] [2] [4]
"""
import json, os, re, shutil, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SWG_SRC_ROOT") or os.path.abspath(os.path.join(HERE, ".."))
FLAGS = {f: f in sys.argv[1:] for f in ("--perturb-lib", "--perturb-noded", "--perturb-netctl", "--perturb-clear")}
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
FAILS = []
SEC = [""]
def section(tag, title):
    SEC[0] = tag; print(("\n" if tag != "[1]" else "") + tag + " " + title)
def check(name, cond, detail=""):
    name = SEC[0] + " " + name
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)
def plant(src, old, new, flag):
    if FLAGS[flag]:
        assert src.count(old) == 1, "perturbation anchor missing — would FALSE-PASS: " + old.strip()[:70]
        return src.replace(old, new)
    return src

T = tempfile.mkdtemp(prefix="lnsprobe-")
BIN = os.path.join(T, "bin"); os.makedirs(BIN)
open(os.path.join(BIN, "systemd-run"), "w").write("""#!/bin/sh
echo "SYSTEMD-RUN $*" >> "$T/calls"
mkdir -p "$SR/var/log/journal/MID.swg-probe"; : > "$SR/var/log/journal/MID.swg-probe/system.journal"
printf 'systemd-journald@swg-probe.service\\nsystemd-journald@swg-probe.socket\\nsystemd-journald-varlink@swg-probe.socket\\n' >> "$T/loaded"
[ "${PROBE_RC:-1}" = 0 ] && exit 0
echo "Job for run-u4.service failed because of unavailable resources or another system error." >&2
echo "run-u4.service: Failed to set up mount namespacing: Operation not supported (status=226/NAMESPACE)" >&2
exit 1
""")
open(os.path.join(BIN, "systemctl"), "w").write("""#!/bin/bash
echo "SYSTEMCTL $*" >> "$T/calls"
case "$1" in
  list-units) shift; for u in $(cat "$T/loaded" 2>/dev/null); do for p in "$@"; do case "$p" in -*) continue;; esac
      case "$u" in $p) echo "$u loaded active running x"; break;; esac; done; done;;
  stop) shift; for u in "$@"; do grep -vxF "$u" "$T/loaded" > "$T/l2"; mv "$T/l2" "$T/loaded"; done;;
  is-failed) for u in $FAILED; do [ "$u" = "${@: -1}" ] && exit 0; done; exit 1;;
esac
exit 0
""")
for f in ("systemd-run", "systemctl"):
    os.chmod(os.path.join(BIN, f), 0o755)

def sandbox(name, template=True):
    sr = os.path.join(T, name)
    for d in ("etc/systemd/system", "run/systemd/system", "usr/lib/systemd/system", "var/log/journal", "run/log/journal"):
        os.makedirs(os.path.join(sr, d), exist_ok=True)
    open(os.path.join(sr, "etc/machine-id"), "w").write("MID\n")
    if template:
        open(os.path.join(sr, "usr/lib/systemd/system/systemd-journald@.service"), "w").write("[Service]\n")
    for f in ("calls", "loaded"):
        open(os.path.join(T, f), "w").close()
    return sr
def put(sr, rel, text="x"):
    p = os.path.join(sr, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)
def calls():
    return open(os.path.join(T, "calls")).read()
def dropins(sr):
    return sorted(os.path.relpath(os.path.join(dp, f), sr) for dp, _d, fs in os.walk(sr) for f in fs if f == "swg-ns.conf")
def sandboxed(text, sr):
    for a in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/etc/machine-id", "/var/log/journal",
              "/run/log/journal"):
        text = re.sub(r"(?<![\w/.-])" + re.escape(a), sr + a, text)
    return re.sub(r"(?<![\w/.-])/lib/systemd/system", sr + "/lib/systemd/system", text)

# ── the lib functions, as bash defines them ──────────────────────────────────────────────────────────────────────────
LIBF = ["swg_log_ns_ok", "_swg_log_ns_run_probe", "swg_log_ns_clear", "swg_log_ns_text", "swg_log_ns_heal"]
r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; for f in "${@:2}"; do declare -f "$f"; done; echo "SWG_LOG_NS_DROPIN=$SWG_LOG_NS_DROPIN"',
                    "_", os.path.join(ROOT, "lib/common.sh")] + LIBF, capture_output=True, text=True)
LIB = r.stdout
LIB = LIB.replace('[ "$(id -u)" != 0 ]', 'false')          # the gate is not root: the probe path must run
LIB = plant(LIB, '    [ -n "$t" ] || return 1;\n', '    [ -n "$t" ] || return 1;\n    return 0;\n', "--perturb-lib")
LIB = plant(LIB, '    swg_log_ns_ok || { \n        swg_log_ns_clear;\n        return 0\n    };\n', '    swg_log_ns_ok || return 0;\n', "--perturb-clear")
def lib_sh(sr, body, env=""):
    sh = ('set -uo pipefail\nhave(){ command -v "$1" >/dev/null 2>&1; }\nnote(){ echo "NOTE $*"; }\nwarn(){ echo "WARN $*"; }\n'
          'ok(){ echo "OK $*"; }\nDRYRUN=false\nSWG_LOG_NS_PROBE=%s/run/swg-log-ns\n%s\n%s\n%s\n') % (sr, env, sandboxed(LIB, sr), body)
    return subprocess.run(["bash", "-c", sh], capture_output=True, text=True,
                          env=dict(os.environ, PATH=BIN + ":" + os.environ["PATH"], T=T, SR=sr))

section("[1]", "lib/common.sh")
sr = sandbox("lib-refused")
for u in ("swg-panel-server.service", "swg-sub.service"):
    put(sr, "etc/systemd/system/" + u, "[Service]\n")
put(sr, "etc/systemd/system/swg-panel-server.service.d/swg-ns.conf", "[Service]\nLogNamespace=swg-panel\n")
put(sr, "etc/systemd/system/swg-panel-server.service.d/my-own.conf", "[Service]\nEnvironment=X=1\n")
put(sr, "etc/systemd/system/swg-noded.service.d/swg-ns.conf", "[Service]\nLogNamespace=swg-node\n")
put(sr, "run/systemd/system/vk-turn-proxy-.service.d/swg-ns.conf", "[Service]\nLogNamespace=swg-node\n")
r = lib_sh(sr, 'swg_log_ns_heal swg-panel swg-panel-server.service swg-sub.service; echo "CHANGED=$SWG_LOG_NS_CHANGED CLEARED=${SWG_LOG_NS_CLEARED:-}"')
check("refused: no drop-in written, every swg-ns.conf there was removed (in /etc and /run)",
      dropins(sr) == [] and "CHANGED=0" in r.stdout, (dropins(sr), r.stdout + r.stderr))
check("…an operator's own drop-in beside them stays", os.path.exists(os.path.join(sr, "etc/systemd/system/swg-panel-server.service.d/my-own.conf")))
check("…counted (SWG_LOG_NS_CLEARED=3) for the caller", "CLEARED=3" in r.stdout, r.stdout)
check("…the answer is kept (refused) for the boot", open(os.path.join(sr, "run/swg-log-ns")).read().strip() == "refused"
      if os.path.exists(os.path.join(sr, "run/swg-log-ns")) else False)
c = calls()
check("…the probe namespace is cleaned up: its journald units stopped, its directory gone",
      "SYSTEMCTL stop " in c and not os.path.exists(os.path.join(sr, "var/log/journal/MID.swg-probe"))
      and open(os.path.join(T, "loaded")).read().strip() == "", c[-400:])
open(os.path.join(T, "calls"), "w").close()
r = lib_sh(sr, 'swg_log_ns_ok && echo YES || echo NO')
check("…a second ask starts no unit (the kept answer)", "NO" in r.stdout and "SYSTEMD-RUN" not in calls(), r.stdout + calls())
sr = sandbox("lib-ok")
for u in ("swg-panel-server.service", "swg-sub.service"):
    put(sr, "etc/systemd/system/" + u, "[Service]\n")
r = lib_sh(sr, 'swg_log_ns_heal swg-panel swg-panel-server.service swg-sub.service; echo "CHANGED=$SWG_LOG_NS_CHANGED"', env="PROBE_RC=0; export PROBE_RC")
check("CONTROL ok: the drop-ins are written as before",
      dropins(sr) == ["etc/systemd/system/swg-panel-server.service.d/swg-ns.conf", "etc/systemd/system/swg-sub.service.d/swg-ns.conf"]
      and "CHANGED=2" in r.stdout, (dropins(sr), r.stdout + r.stderr))
sr = sandbox("lib-notemplate", template=False)
r = lib_sh(sr, 'swg_log_ns_ok && echo YES || echo NO')
check("no namespace template: no, and no unit started", "NO" in r.stdout and "SYSTEMD-RUN" not in calls(), r.stdout + calls())
sr = sandbox("lib-dry")
r = lib_sh(sr, 'swg_log_ns_ok && echo YES || echo NO', env="DRYRUN=true")
check("a dry run starts no unit (the template answers)", "YES" in r.stdout and "SYSTEMD-RUN" not in calls(), r.stdout + calls())

section("[2]", "update.sh ensure_log_ns, refused")
U = rd("update.sh")
m = re.search(r"^ensure_log_ns\(\)\{.*?^\}\n", U, re.S | re.M)
ELN = m.group(0) if m else ""
sr = sandbox("upd")
for u in ("swg-panel-server.service", "swg-netctl.service"):
    put(sr, "etc/systemd/system/" + u, "[Service]\n")
    put(sr, "etc/systemd/system/%s.d/swg-ns.conf" % u, "[Service]\nLogNamespace=swg-panel\n")
os.makedirs(os.path.join(sr, "src")); open(os.path.join(sr, "src/swg-logs"), "w").write("x")
r = lib_sh(sr, 'SRC=%s/src; DID_UPDATE=no\ninstall(){ :; }\n%s\nensure_log_ns swg-panel swg-panel-server.service swg-netctl.service\necho "DID_UPDATE=$DID_UPDATE"\n'
           % (sr, ELN.replace("/usr/local/bin/swg-logs", sr + "/swg-logs")), env="FAILED='swg-panel-server.service swg-netctl.service'; export FAILED")
c = calls()
check("the drop-ins go, systemd reloads", dropins(sr) == [] and "SYSTEMCTL daemon-reload" in c, (dropins(sr), c[-300:]))
check("…the panel the drop-in had failed is restarted; the oneshot netctl is only reset (its next tick runs)",
      "SYSTEMCTL restart swg-panel-server.service" in c and "SYSTEMCTL reset-failed swg-netctl.service" in c
      and "restart swg-netctl" not in c, c[-500:])
check("…and it is said (a warning, an update note)", "WARN this box cannot run a unit in a journal namespace" in r.stdout
      and "DID_UPDATE=yes" in r.stdout, r.stdout + r.stderr)

section("[3]", "the installers")
for f, n in (("install-host.sh", 5), ("install-node.sh", 1)):
    s = rd(f)
    sites = re.findall(r"if swg_log_ns_ok; then swg_log_ns_text swg-(?:node|panel) \| writef [^\n]*", s)
    check("%s: all %d drop-in sites clear them where the probe refuses" % (f, n),
          len(sites) == n and all(x.endswith("; else swg_log_ns_clear; fi") for x in sites), sites)

_geteuid = os.geteuid

section("[4]", "swg-noded")
src = rd("swg-noded")
src = plant(src, '                                               "/lib/systemd/system"))\n                             and _log_ns_probe())',
            '                                               "/lib/systemd/system")))', "--perturb-noded")
src = plant(src, '        if _LOG_BUDGET.get("ns_refused"):\n', '        if False:\n', "--perturb-clear")
def noded(rc, sr):
    os.environ["SWG_LOG_NS_PROBE"] = os.path.join(sr, "run/swg-log-ns-noded")
    N = types.ModuleType("n"); N.__dict__.update({"__name__": "n", "__file__": "swg-noded"})
    exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)
    N.LOG_NS_PROBE = os.environ["SWG_LOG_NS_PROBE"]
    N.NODE_KIND = "baremetal"; N.UNIT_DIR_PERSIST = os.path.join(sr, "etc/systemd/system")
    N.UNIT_DIR_RUNTIME = os.path.join(sr, "run/systemd/system"); N.unit_dir_persists = lambda: True
    N._journal_dirs = lambda ns: [os.path.join(sr, "var/log/journal/MID." + ns)]
    N.LOG_NS_CONF = os.path.join(sr, "run/systemd/journald@swg-node.conf.d/swg.conf")
    log = []
    def run(cmd, *a, **k):
        log.append(" ".join(cmd))
        if cmd[0] == "systemd-run":
            os.makedirs(os.path.join(sr, "var/log/journal/MID.swg-probe"), exist_ok=True)
            return subprocess.CompletedProcess(cmd, rc, "", "" if rc == 0 else "run-u4.service: Failed to set up mount namespacing (226/NAMESPACE)")
        if cmd[:2] == ["systemctl", "list-units"]:
            return subprocess.CompletedProcess(cmd, 0, "systemd-journald@swg-probe.service loaded active running x\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    N.run = run
    return N, log
os.geteuid = lambda: 0                               # the probe runs as root in life
try:
    sr = sandbox("noded-refused")
    for u in ("swg-relay@.service", "vk-turn-proxy-.service", "swg-wdtt-.service", "swg-csqtt-.service"):
        put(sr, "etc/systemd/system/%s.d/swg-ns.conf" % u, "[Service]\nLogNamespace=swg-node\n")
    N, log = noded(1, sr)
    N._log_ns_dropins()
    check("refused: log_ns_ok() is False", N.log_ns_ok() is False, log)
    check("…the prefix drop-ins an earlier run wrote are removed, systemd reloads",
          dropins(sr) == [] and "systemctl daemon-reload" in log, (dropins(sr), log))
    check("…the probe namespace is cleaned up (its journald stopped, its directory gone)",
          any(l.startswith("systemctl stop systemd-journald@swg-probe") for l in log)
          and not os.path.exists(os.path.join(sr, "var/log/journal/MID.swg-probe")), log)
    N._log_budget()
    st = N._LOG_BUDGET.get("status") or {}
    check("…the budget row reads unsupported, with the reason", st.get("unsupported") is True
          and "cannot run in a journal namespace" in str(st.get("err")), st)
    N2, log2 = noded(1, sr)
    check("…a restarted noded starts no unit to ask again (the kept answer)", N2.log_ns_ok() is False
          and not any(l.startswith("systemd-run") for l in log2), log2)
    sr = sandbox("noded-ok")
    N, log = noded(0, sr)
    N._log_ns_dropins()
    check("CONTROL ok: the four prefix drop-ins are written as before", len(dropins(sr)) == 4 and N.log_ns_ok() is True, (dropins(sr), log))
finally:
    os.geteuid = _geteuid

section("[5]", "swg-netctl")
nsrc = rd("swg-netctl")
nsrc = plant(nsrc, '               for d in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")) \\\n        and log_ns_probe()\n',
             '               for d in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"))\n',
             "--perturb-netctl")
def netctl(rc, sr):
    os.environ.update({"SWG_LOG_NS_PROBE": os.path.join(sr, "run/swg-log-ns-netctl"), "SWG_STATE_DIR": os.path.join(sr, "pst"),
                       "SWG_LOG_NS_CONF": os.path.join(sr, "run/systemd/journald@swg-panel.conf.d/swg.conf"),
                       "SWG_PANEL_USER": "nobody-here", "SWG_PANEL_GROUP": "nogroup-here"})
    os.makedirs(os.path.join(sr, "pst"), exist_ok=True)
    M = types.ModuleType("m"); M.__dict__.update({"__name__": "m", "__file__": "swg-netctl"})
    exec(compile(nsrc.split("\nif __name__ ==")[0], "swg-netctl", "exec"), M.__dict__)
    M.LOG_NS_PROBE = os.environ["SWG_LOG_NS_PROBE"]; M.LOG_NS_CONF = os.environ["SWG_LOG_NS_CONF"]
    log, docs = [], []
    def run(argv, env=None, timeout=None):
        log.append(" ".join(argv))
        if argv[0] == "systemd-run":
            return rc, "" if rc == 0 else "run-u4.service: Failed to set up mount namespacing (226/NAMESPACE)"
        if argv[:2] == ["systemctl", "list-units"]:
            return 0, "systemd-journald@swg-probe.service loaded active running x\n"
        return 0, ""
    M.run = run; M._read_log_status = lambda: {}; M._write_log_status = docs.append
    M.log_budget_mb = lambda ps: 100; M.log_level = lambda: M.LOG_INFO
    return M, log, docs
os.geteuid = lambda: 0
try:
    sr = sandbox("netctl-refused")
    M, log, docs = netctl(1, sr)
    M.log_budget({})
    d = docs[-1] if docs else {}
    check("refused: the panel's budget is unsupported, with the reason", d.get("unsupported") is True
          and "cannot run in a journal namespace" in str(d.get("err")), (d, log))
    check("…no size file, no journald restart", not os.path.exists(M.LOG_NS_CONF) and not any("try-restart" in l for l in log), log)
    sr = sandbox("netctl-ok")
    M, log, docs = netctl(0, sr)
    M.log_budget({})
    check("CONTROL ok: the size file is written and its journald restarted, as before",
          os.path.exists(M.LOG_NS_CONF) and any("try-restart systemd-journald@swg-panel.service" in l for l in log), (docs, log))
finally:
    os.geteuid = _geteuid

shutil.rmtree(T, ignore_errors=True)
print("")
if any(FLAGS.values()):
    named = {"--perturb-lib": ("[1]", "[2]"), "--perturb-noded": ("[4]",), "--perturb-netctl": ("[5]",),
             "--perturb-clear": ("[1]", "[2]", "[4]")}
    want = tuple(t for f, v in FLAGS.items() if v for t in named[f])
    stray = [f for f in FAILS if not f.startswith(want)]
    print("perturb: %s" % ("NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % stray if stray
                           else "RED as it must be (%d), all in %s" % (len(FAILS), " ".join(sorted(set(f[:3] for f in FAILS))))))
    sys.exit(0 if FAILS and not stray else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
