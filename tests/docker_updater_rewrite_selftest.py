#!/usr/bin/env python3
"""Self-test — AN UPDATE REWRITES A DOCKER BOX'S ONE-CLICK UPDATER WHEN AN OLDER RELEASE WROTE IT (N12).

A Docker panel's one-click update runs /usr/local/bin/swg-update (through swg-update-check, polled by swg-update.timer).
update.sh's ensure_update_unit_docker wrote those pieces only when one was MISSING — so a Docker box upgraded from 1.8.7
ran 1.8.7's wrapper for ever: no api.github.com door when raw is filtered, no fetch-then-run (1.8.8 qualification, round
10, N12). The bare path's install_update_unit rewrites its wrapper at every update. Now each Docker piece is compared with
this release's text (one text each, lib/common.sh) and the wiring is rewritten when one differs — following the ref the
box follows: SWG_REF when bootstrap exported it, else the one baked into the wrapper there, `main` only when neither says.

  [1] ensure_update_unit_docker (update.sh) + write_docker_updater (lib/common.sh), driven with their paths remapped:
      nothing there → written (as before); this release's texts there → nothing written, nothing said; an older wrapper
      → rewritten, one line naming what was stale, still following the ref baked into it (dev) when SWG_REF is unset,
      or SWG_REF when it is set; an older check / service / timer → rewritten; a dry run → said, nothing written; a
      node-only stack → nothing; and once rewritten, the next update finds nothing to rewrite (no churn)
  [2] write_docker_updater writes exactly the texts the comparison reads (one text each — no second copy to drift)

Run: python3 tests/docker_updater_rewrite_selftest.py        (0 = pass)
     --perturb   two plants, each on its own — each must turn its own check red
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {"UPDATE": os.environ.get("SWG_DU_UPDATE") or os.path.join(ROOT, "update.sh"),
         "COMMON": os.environ.get("SWG_DU_COMMON") or os.path.join(ROOT, "lib/common.sh")}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("present", "UPDATE", '    if [ -z "$_stale" ]; then\n', '    if true; then\n', "[1] an older wrapper → rewritten"),
    ("ref", "UPDATE", '  [ -n "$_ref" ] || _ref="$(sed -n \'s#^URL=.*/swg-panel/\\([^/]*\\)/bootstrap\\.sh}".*#\\1#p\' /usr/local/bin/swg-update 2>/dev/null | sed -n 1p || true)"\n',
     "", "[1] …still following the ref baked into it"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        if SRC[key].count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, SRC[key].count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(SRC[key].replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_DU_" + key: f.name}), capture_output=True, text=True, timeout=180)
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

C, U = SRC["COMMON"], SRC["UPDATE"]
TEXTS = "".join(fn(C, n) for n in ("swg_update_wrapper_text", "swg_update_check_docker_text", "swg_update_docker_service_text",
                                   "swg_update_docker_timer_text"))
BODY = fn(C, "write_docker_updater") + fn(U, "ensure_update_unit_docker")
FILES = ("/usr/local/bin/swg-update", "/usr/local/bin/swg-update-check", "/etc/systemd/system/swg-update.service",
         "/etc/systemd/system/swg-update.timer")

def render(root, what):
    """what this release writes, rendered by the shipped text functions"""
    r = subprocess.run(["bash", "-c", TEXTS + what], capture_output=True, text=True, timeout=30)
    return r.stdout

def run(root, prof="master", ref=None, dry=False):
    body = (BODY.replace("/usr/local/bin/", root + "/usr/local/bin/").replace("/etc/systemd/system/", root + "/etc/systemd/system/")
            .replace("/var/lib/swg-update.stamp", root + "/var/lib/swg-update.stamp"))
    script = ('set -euo pipefail\nDRYRUN=%s\n%s'
              'ok(){ echo "OK $*"; }; info(){ echo "INFO $*"; }; warn(){ echo "WARN $*"; }; note(){ echo "NOTE $*"; }; b(){ printf %%s "$*"; }\n'
              'systemctl(){ echo "systemctl $*" >> "%s/calls"; return 0; }\n%s%sensure_update_unit_docker %s\necho "RC=$?"\n') % (
        "true" if dry else "false", ("SWG_REF=%s\n" % ref) if ref else "unset SWG_REF\n", root, TEXTS, body, prof)
    env = dict(os.environ); env.pop("SWG_REF", None)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=env)
    return r.stdout + r.stderr

def box(pieces=None):
    root = tempfile.mkdtemp(prefix="du-")
    for d in ("/usr/local/bin", "/etc/systemd/system", "/var/lib"):
        os.makedirs(root + d, exist_ok=True)
    for path, text in (pieces or {}).items():
        open(root + path, "w").write(text)
        os.chmod(root + path, 0o755)
    return root

def read(root):
    return {p: (open(root + p).read() if os.path.exists(root + p) else None) for p in FILES}

def current(ref):
    return {FILES[0]: render(None, 'swg_update_wrapper_text "%s"\n' % ref), FILES[1]: render(None, "swg_update_check_docker_text\n"),
            FILES[2]: render(None, "swg_update_docker_service_text\n"), FILES[3]: render(None, "swg_update_docker_timer_text\n")}

def older_wrapper(ref):
    """a wrapper as an older release wrote it: this text without the API door and the fetch-then-run"""
    t = current(ref)[FILES[0]]
    t = re.sub(r"(?m)^API=.*\n", "", t)
    t = re.sub(r"(?s)if ! curl -fsSL.*?\nfi\nbash \"\$B\" update", 'curl -fsSL "$URL" | bash -s -- update', t)
    assert t != current(ref)[FILES[0]] and "/%s/bootstrap.sh" % ref in t
    return t

print("[1] ensure_update_unit_docker")
root = box()
out = run(root, ref="dev")
got = read(root)
check("[1] nothing there → written, as before (this release's texts, following SWG_REF)", got == current("dev") and "healed" in out, (out, {k: (v or "")[:60] for k, v in got.items()}))

root = box(current("dev"))
before = {p: os.stat(root + p).st_mtime_ns for p in FILES}
out = run(root)
check("[1] this release's texts there → nothing written, nothing said", "INFO" not in out and "OK" not in out
      and before == {p: os.stat(root + p).st_mtime_ns for p in FILES}, out)

old = dict(current("dev")); old[FILES[0]] = older_wrapper("dev")
root = box(old)
out = run(root)
got = read(root)
check("[1] an older wrapper → rewritten", got[FILES[0]] in (current("dev")[FILES[0]], current("main")[FILES[0]]),
      (out, (got[FILES[0]] or "")[-300:]))
check("[1] …still following the ref baked into it (dev) when SWG_REF is unset", got[FILES[0]] == current("dev")[FILES[0]], (out, (got[FILES[0]] or "")[:1200]))
check("[1] …and one line names what was stale and the ref it follows",
      "INFO rewriting the docker one-click self-update wiring — an older release's text (swg-update), following dev" in out, out)
out2 = run(root)
check("[1] once rewritten, the next update finds nothing to rewrite (no churn)", "rewriting" not in out2 and "healed" not in out2, out2)

root = box(old)
out = run(root, ref="main")
check("[1] an older wrapper with SWG_REF set → follows SWG_REF", read(root)[FILES[0]] == current("main")[FILES[0]], out)

for i, label in ((1, "swg-update-check"), (2, "swg-update.service"), (3, "swg-update.timer")):
    old = dict(current("dev")); old[FILES[i]] = old[FILES[i]].replace("30s", "20s") if i == 3 else old[FILES[i]] + "# an older release\n"
    root = box(old)
    out = run(root)
    check("[1] an older %s → rewritten" % label, read(root)[FILES[i]] == current("dev")[FILES[i]] and ("(%s)" % label) in out, out)

old = dict(current("dev")); old[FILES[0]] = older_wrapper("dev")
root = box(old)
out = run(root, dry=True)
check("[1] a dry run → said, nothing written", read(root)[FILES[0]] == older_wrapper("dev") and "[skip] rewrite swg-update" in out, out)
root = box(old)
out = run(root, prof="node")
check("[1] a node-only stack → nothing", read(root)[FILES[0]] == older_wrapper("dev") and "INFO" not in out, out)

print("\n[2] one text each")
W = fn(C, "write_docker_updater")
check("[2] write_docker_updater writes the check, the service and the timer through their text functions — no heredoc of its own",
      "swg_update_check_docker_text > /usr/local/bin/swg-update-check" in W and "swg_update_docker_service_text > /etc/systemd/system/swg-update.service" in W
      and "swg_update_docker_timer_text > /etc/systemd/system/swg-update.timer" in W and "<<" not in W, W[-600:])

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
