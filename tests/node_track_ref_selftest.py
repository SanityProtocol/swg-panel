#!/usr/bin/env python3
"""Self-test — a NODE keeps the branch its self-update follows, and a changed ref reaches the running daemon.

  [1] bootstrap.sh, taking a box back to a commit (SWG_REF=df3bb45), keeps it tracking the branch it followed —
      read from the panel's one-click wrapper, which a node-only box does not have. Its node records that branch in
      /etc/swg-agent/config.json (node.update_ref); reading only the wrapper re-pointed a dev node at `main` (1.8.8
      qualification, q2: "✓ node self-update now tracks main").
  [2] update.sh, when only the ref changes: "✓ Update finished — nothing changed." and no restart — swg-noded reads
      config.json only at startup, so the running daemon kept the old branch. Now it counts as a change and the
      daemon is restarted; on a version update the ref is written BEFORE the restart (it used to be written after,
      under the daemon that had just started on the old one), and the daemon is restarted once, not twice.

The fetch block (bootstrap.sh) and the node section + ensure_node_update_ref (update.sh) are lifted out AS SHIPPED
and run over temp files, with git/curl/tar/systemctl stubs. No network.

Run: python3 tests/node_track_ref_selftest.py      (0 = pass)
     --perturb   the agent-config fallback, the ref-change restart and the write-before-restart order taken out → RED
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
B = open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8").read()
UP = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
N = open(os.path.join(ROOT, "install-node.sh"), encoding="utf-8").read()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:500]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    B = plant(B, '  if [ -z "$_track" ] && [ -f /etc/swg-agent/config.json ] && need python3; then\n',
              '  if false; then\n')                                                                   # [1]
    UP = plant(UP, '  if [ "$NODE_REF_CHANGED" = yes ] && [ "$_noded_restarted" = no ] && ! $DRYRUN',
               '  if false && [ "$NODE_REF_CHANGED" = yes ] && [ "$_noded_restarted" = no ] && ! $DRYRUN')   # [2] no restart
    UP = plant(UP, '  NODE_REF_CHANGED=no; _noded_restarted=no\n  ensure_node_update_ref # HEAL: record the ref this box tracks, so the node\'s self-update doesn\'t fall to main\n',
               '  NODE_REF_CHANGED=no; _noded_restarted=no\n')
    UP = plant(UP, '  fi\n  ensure_noded_unit      # HEAL: recreate the swg-noded unit',
               '  fi\n  ensure_node_update_ref\n  ensure_noded_unit      # HEAL: recreate the swg-noded unit')   # [2] written AFTER the restart again
    N = plant(N, '_swg_ref="${SWG_REF:-${EXIST_REF:-main}}"\n', '_swg_ref="${SWG_REF:-main}"\n')                  # [3]

def fn(src, name):
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if l.split("  #")[0].rstrip().endswith("}"):
            text = "\n".join(lines[:k + 1]) + "\n"
            if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
                return text
    raise AssertionError("unterminated " + name)

# ── [1] bootstrap.sh ──────────────────────────────────────────────────────────────────────────────────────────
i = B.index('_fetched=""\n'); j = B.index('cd "$TMP/swg-panel"', i)
fetch = B[i:j]

def boot(ref, wrapper=None, agent_ref=None, track=None):
    d = tempfile.mkdtemp(prefix="trk-"); tmp = os.path.join(d, "tmp"); os.makedirs(tmp)
    wpath = os.path.join(d, "swg-update"); cpath = os.path.join(d, "config.json")
    if wrapper is not None:
        open(wpath, "w").write('URL="https://raw.githubusercontent.com/SanityProtocol/swg-panel/%s/bootstrap.sh"\n' % wrapper)
    if agent_ref is not None:
        json.dump({"panel": {"url": "https://192.168.77.5:2087"}, "node": {"update_ref": agent_ref}}, open(cpath, "w"))
    blk = fetch.replace("/usr/local/bin/swg-update", wpath).replace("/etc/swg-agent/config.json", cpath)
    for name, body in (("git", "exit 0"), ("curl", "exit 0"),
                       ("tar", 'for a; do last="$a"; done; mkdir -p "$last/swg-panel-0123456789abcdef0123456789abcdef01234567"')):
        p = os.path.join(d, name); open(p, "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(p, 0o755)
    script = ('set -euo pipefail\nREF=%s\nexport SWG_REF="$REF"\nREPO=https://github.com/SanityProtocol/swg-panel\nTMP=%s\n'
              'need(){ command -v "$1" >/dev/null 2>&1; }\nwarn(){ :; }\ninfo(){ :; }\nb(){ printf %%s "$*"; }\n'
              'die(){ echo "DIE $*"; exit 9; }\n%s\necho "EXPORTED=$SWG_REF"\n') % (ref, tmp, blk)
    env = dict(os.environ, PATH=d + ":" + os.environ["PATH"]); env.pop("SWG_TRACK", None)
    if track:
        env["SWG_TRACK"] = track
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    m = re.search(r"^EXPORTED=(.*)$", r.stdout, re.M)
    return (m.group(1) if m else "?"), r.stdout + r.stderr

print("[1] bootstrap.sh: a commit is installed, the node keeps tracking its branch")
got, out = boot("df3bb45", agent_ref="dev")
check("node-only box (no wrapper), node.update_ref=dev → keeps following dev", got == "dev", out)
got, out = boot("df3bb45", agent_ref="df3bb45")
check("…a commit recorded there is never tracked → main", got == "main", out)
got, out = boot("df3bb45", agent_ref="dev; rm -rf /")
check("…nor anything that is not a plain ref name → main", got == "main", out)
got, out = boot("df3bb45", wrapper="main", agent_ref="dev")
check("a panel box: its wrapper still decides (main), before the node's record", got == "main", out)
got, out = boot("df3bb45", agent_ref="dev", track="main")
check("SWG_TRACK still wins", got == "main", out)
got, out = boot("df3bb45")
check("nothing recorded anywhere → main, as before", got == "main", out)

# ── [2] update.sh ─────────────────────────────────────────────────────────────────────────────────────────────
a = UP.index("# ───────────────────────── bare-metal node daemon (node or master)")
b = UP.index("# ───────────────────────── Docker (host / node / master)", a)
node_block = UP[a:b]
ref_fn = fn(UP, "ensure_node_update_ref")

def upd(have_ref, want_ref, version_moves):
    d = tempfile.mkdtemp(prefix="upd-"); log = os.path.join(d, "calls")
    cfg = os.path.join(d, "config.json")
    json.dump({"panel": {"url": "https://192.168.77.5:2087", "token": "t"}, "node": {"update_ref": have_ref}}, open(cfg, "w"))
    noded = os.path.join(d, "noded"); agent = os.path.join(d, "agent"); src = os.path.join(d, "src")
    for x in (noded, agent, src):
        os.makedirs(x)
    open(os.path.join(noded, "swg-noded"), "w").write("x"); open(os.path.join(noded, "VERSION"), "w").write("1.8.7-beta\n")
    # systemctl logs, at the moment of each call, the ref the daemon would read if it (re)started now
    p = os.path.join(d, "systemctl")
    open(p, "w").write('#!/bin/bash\n[ "$1" = is-active ] && exit 0\n'
                       'echo "systemctl $* REF=$(python3 -c \'import json,sys;print(json.load(open(sys.argv[1]))["node"]["update_ref"])\' %s)" >> %s\n'
                       'exit 0\n' % (cfg, log))
    os.chmod(p, 0o755)
    body = (ref_fn + node_block).replace("/etc/swg-agent/config.json", cfg)
    script = ('set -euo pipefail\nDRYRUN=false; DID_UPDATE=no; DID_FAIL=no; NEW_VER=1.8.8-beta\nNODED_DIR=%s; AGENT_DIR=%s; SRC=%s\n'
              'RESULTS=(); note(){ RESULTS+=("$*"); }\nrun(){ "$@"; }\nok(){ echo "OK $*"; }\ninfo(){ :; }\nwarn(){ echo "WARN $*"; }\n'
              'col_v(){ printf %%s "$*"; }\noldver(){ cat "$1/VERSION" 2>/dev/null || echo "?"; }\nstamp(){ :; }\n'
              'should_update(){ %s; }\n'
              'ensure_noded_unit(){ :; }; ensure_noded_no_nnp(){ :; }; ensure_noded_reach_sweep(){ :; }; ensure_wg_apparmor(){ :; }\n'
              'ensure_awg_datapath(){ :; }; ensure_awg_quick_unit(){ :; }; ensure_awg_back_on_kernel(){ :; }\n'
              'export SWG_REF=%s\n%s\necho "DID_UPDATE=$DID_UPDATE"\n') % (
        noded, agent, src, "return 0" if version_moves else "return 1", want_ref, body)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, PATH=d + ":" + os.environ["PATH"]))
    calls = open(log).read() if os.path.exists(log) else ""
    return r.stdout + r.stderr, [l for l in calls.splitlines() if "restart swg-noded" in l]

print("\n[2] update.sh: a ref change is a change, and the running daemon follows it")
out, restarts = upd("main", "dev", version_moves=False)
check("same version, ref main → dev: counted (DID_UPDATE=yes), not 'nothing changed'", "DID_UPDATE=yes" in out, out)
check("…and swg-noded is restarted ONCE, on the new ref", len(restarts) == 1 and restarts[0].endswith("REF=dev"), (restarts, out))
out, restarts = upd("main", "dev", version_moves=True)
check("version update AND ref change: the ref is written BEFORE the restart (it starts on dev)",
      len(restarts) >= 1 and restarts[0].endswith("REF=dev"), (restarts, out))
check("…and the daemon is restarted exactly once", len(restarts) == 1, restarts)
out, restarts = upd("dev", "dev", version_moves=False)
check("nothing moved (same version, same ref) → no restart, nothing counted", not restarts and "DID_UPDATE=no" in out, (restarts, out))

print("\n[3] install-node.sh re-run by hand (no bootstrap → no SWG_REF) keeps the branch the node follows")
blk = N[N.index('printf \'%s\' "$EXIST_REF" | grep -qE \'^[0-9a-f]{7,40}$\' && EXIST_REF=""'):]
blk = blk[:blk.index("\n", blk.index("_swg_ref=")) + 1]
def ref_default(exist, swg_ref=None):
    env = dict(os.environ); env.pop("SWG_REF", None)
    if swg_ref:
        env["SWG_REF"] = swg_ref
    r = subprocess.run(["bash", "-c", 'set -euo pipefail\nEXIST_REF="%s"\n%secho "REF=$_swg_ref"' % (exist, blk)],
                       capture_output=True, text=True, env=env)
    return r.stdout + r.stderr
check("the node follows dev, re-run with no SWG_REF → stays dev", "REF=dev\n" in ref_default("dev"), ref_default("dev"))
check("…SWG_REF given (bootstrap) still wins", "REF=main\n" in ref_default("dev", "main"))
check("…a commit on record is never tracked → main", "REF=main\n" in ref_default("df3bb45"))
check("…nothing on record (a fresh install) → main, as before", "REF=main\n" in ref_default(""))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(2 if PERTURB else 0)
