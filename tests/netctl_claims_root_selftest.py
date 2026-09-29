#!/usr/bin/env python3
"""Self-test — swg-netctl's claims/ AND status/ STAY ROOT'S, SO NO INSTALL LEAVES AN "untrusted" DIRECTORY BEHIND (F96).

swg-netctl keeps its own claims/ (0700) and status/ (0750, group swg) and proves them root's before it trusts them
(_root_child: owned by root, no group/other write — anything else is moved aside as <name>.untrusted.<ts>.<pid>). The
installer's `chown -R $PANEL_USER:swg $STATE_DIR` handed both to the panel, and only status/ was put back — so every
install left a claims.untrusted.* directory, and a docker → bare convert's own chown -R did the same to both (1.8.8
qualification, round 10).

  [1] netctl_dirs_heal (lib/common.sh), driven: claims/ → root:root 0700 (recursively, a symlink never followed),
      status/ → root:swg 0750, the EMPTY untrusted directories removed and a non-empty one kept
  [2] install-host.sh heals right after its chown -R of the state — before the panel starts and queues requests the helper
      would run against a claims/ and status/ that chown just handed away (round 12: a status.untrusted.* left on q5) —
      and again where it puts status/ back (write_netctl); never on a dry run
  [3] update.sh heals at every update of a bare panel (ensure_netctl_helper, before its "already complete" return)
  [4] convert.sh heals right after the docker → bare chown -R of the state
  [5] swg-netctl still demands both be root's (the check the heal satisfies)

Run: python3 tests/netctl_claims_root_selftest.py        (0 = pass)
     --perturb   five plants, each on its own — each must turn its own check red
"""
import os, re, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {k: os.environ.get("SWG_NC_" + k) or os.path.join(ROOT, f) for k, f in
         (("COMMON", "lib/common.sh"), ("HOST", "install-host.sh"), ("UPDATE", "update.sh"), ("CONVERT", "convert.sh"), ("NETCTL", "swg-netctl"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("claims", "COMMON", '    chown -R -h root:root "$st/netctl/claims" 2>/dev/null || true; chmod 700 "$st/netctl/claims" 2>/dev/null || true\n',
     "    true\n", "[1] claims/ → root:root 0700"),
    ("rmdir", "COMMON", '    if [ -d "$d" ] && [ ! -L "$d" ]; then rmdir "$d" 2>/dev/null || true; fi\n', "    true\n",
     "[1] the empty untrusted directories are removed"),
    ("host", "HOST", '  $DRYRUN || netctl_dirs_heal "$STATE_DIR"   # claims/ back to root', '  : "$STATE_DIR"   # claims/ back to root',
     "[2] install-host.sh heals right after it puts status/ back"),
    ("early", "HOST", 'run chown -R "$PANEL_USER:swg" "$STATE_DIR"\n# ⚠️ …BUT swg-netctl', 'run chown -R "$PANEL_USER:swg" "$STATE_DIR"\n: # ⚠️ …BUT swg-netctl',
     "[2] …and at once after the chown -R of the state, before the panel starts"),
    ("convert", "CONVERT", '  netctl_dirs_heal "$STATE"   # …but swg-netctl\'s claims/ stays root\'s (F96)\n', "",
     "[4] convert.sh heals right after the docker → bare chown -R"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_NC_" + key: f.name}), capture_output=True, text=True, timeout=120)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-8s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot lift " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

print("[1] netctl_dirs_heal, driven")
st = tempfile.mkdtemp(prefix="nc-")
n = os.path.join(st, "netctl")
for d in ("claims", "status", "queue", "claims.untrusted.1790526510379709216.505291", "status.untrusted.1790526510379709217.505292",
          "claims.untrusted.1790526510379709218.505293"):
    os.makedirs(os.path.join(n, d))
open(os.path.join(n, "claims.untrusted.1790526510379709218.505293", "c-1"), "w").write("x")   # a non-empty one stays
open(os.path.join(n, "claims", "c-2"), "w").write("x")
os.chmod(os.path.join(n, "claims"), 0o750); os.chmod(os.path.join(n, "status"), 0o770)
stub = tempfile.mkdtemp(prefix="nc-s-"); log = os.path.join(stub, "log")
for tool in ("chown", "chgrp"):
    p = os.path.join(stub, tool); open(p, "w").write('#!/bin/bash\necho "%s $*" >> %s\n' % (tool, log)); os.chmod(p, 0o755)
r = subprocess.run(["bash", "-c", "set -euo pipefail\n%snetctl_dirs_heal %s\n" % (fn(SRC["COMMON"], "netctl_dirs_heal"), st)],
                   capture_output=True, text=True, env=dict(os.environ, PATH=stub + ":" + os.environ["PATH"]), timeout=60)
calls = open(log).read() if os.path.exists(log) else ""
mode = lambda p: stat.S_IMODE(os.lstat(p).st_mode)
check("[1] claims/ → root:root 0700", r.returncode == 0 and ("chown -R -h root:root %s/claims" % n) in calls and mode(os.path.join(n, "claims")) == 0o700,
      (r.returncode, r.stderr, calls, oct(mode(os.path.join(n, "claims")))))
check("[1] status/ → root:swg 0750", ("chown root:swg %s/status" % n) in calls and mode(os.path.join(n, "status")) == 0o750, (calls, oct(mode(os.path.join(n, "status")))))
left = sorted(x for x in os.listdir(n) if ".untrusted." in x)
check("[1] the empty untrusted directories are removed, a non-empty one kept", left == ["claims.untrusted.1790526510379709218.505293"], left)
r = subprocess.run(["bash", "-c", "set -euo pipefail\n%snetctl_dirs_heal %s\nnetctl_dirs_heal ''\necho OK\n"
                    % (fn(SRC["COMMON"], "netctl_dirs_heal"), tempfile.mkdtemp())], capture_output=True, text=True, timeout=60)
check("[1] no netctl dir, or no state dir: nothing, and set -e holds", r.returncode == 0 and r.stdout.strip() == "OK", (r.returncode, r.stderr))

print("\n[2]–[4] where it runs")
H = SRC["HOST"]
i_st = H.find('  run chown root:swg "$STATE_DIR/netctl/status"; run chmod 750 "$STATE_DIR/netctl/status"\n')
i_heal = H.find('  $DRYRUN || netctl_dirs_heal "$STATE_DIR"   # claims/ back to root')
i_chr = H.find('run chown -R "$PANEL_USER:swg" "$STATE_DIR"\n')
check("[2] install-host.sh heals right after it puts status/ back", 0 < i_chr < i_st < i_heal and i_heal - i_st < 200, (i_chr, i_st, i_heal))
_after = H[i_chr + len('run chown -R "$PANEL_USER:swg" "$STATE_DIR"\n'):]
_first = next((ln for ln in _after.split("\n") if ln.strip() and not ln.lstrip().startswith("#")), "")
i_start = H.find("run systemctl restart swg-panel-server")
check("[2] …and at once after the chown -R of the state, before the panel starts", _first == '$DRYRUN || netctl_dirs_heal "$STATE_DIR"'
      and 0 < i_chr < i_start, (_first, i_chr, i_start))
U = SRC["UPDATE"]
en = fn(U, "ensure_netctl_helper")
i_h = en.find('$DRYRUN || netctl_dirs_heal "$st"'); i_ret = en.find("# already complete?")
check("[3] update.sh heals at every update of a bare panel, before its early return", 0 < i_h < i_ret, (i_h, i_ret))
C = SRC["CONVERT"]
i_c = C.find('  chown -R "$_owner" "$STATE" 2>/dev/null || true\n')
check("[4] convert.sh heals right after the docker → bare chown -R",
      i_c > 0 and C.find('  netctl_dirs_heal "$STATE"   # …but swg-netctl\'s claims/ stays root\'s (F96)\n', i_c) == i_c + len('  chown -R "$_owner" "$STATE" 2>/dev/null || true\n'))

print("\n[5] swg-netctl's own check")
N = SRC["NETCTL"]
check("[5] swg-netctl still demands claims/ and status/ be root's (_root_child)",
      'sfd = _root_child(nfd, "status", 0o750)' in N and 'cfd = _root_child(nfd, "claims", 0o700)' in N
      and "st.st_uid == os.geteuid() and not (st.st_mode & 0o022)" in N)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
