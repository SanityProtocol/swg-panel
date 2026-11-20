#!/usr/bin/env python3
"""Self-test — `master` on a box that holds ONLY a node (1.8.12 item 12, a user's report 2026-11-10).

The report: a Docker node, no panel anywhere on the box; `bootstrap.sh … -- master` to move it to bare-metal. The
convert question was right ("A docker node is already installed"), but ROLE stayed `master`, so convert.sh took the
panel path: its pre-flight passed on the node's .env alone and promised a panel, the run wrote a ROLE=master recovery
marker and empty panel dirs, and died on "couldn't stage the panel state". Every later run offered to Resume it — the
same failure. Fixed in three places, each checked here on the scripts AS SHIPPED, run with stubs:

  [1] bootstrap.sh's convert branch: master on a node-only box converts the node only (a panel is never installed
      there — the node answers to another panel), says so before the pre-flight, and after a convert that succeeded
      says no panel was installed. Both methods. Unchanged: `node`, and a real master.
  [2] convert.sh docker→bare host/master: no swg-panel container and no resume state → refused (the pre-flight too).
  [3] bootstrap.sh's Resume block: a master/host marker on a box with no panel on either method and no staged login
      is dropped, not offered (a genuine interrupted convert still is).

Run: python3 tests/master_on_node_box_selftest.py     (0 = pass)
     --perturb   takes each of the three out → RED
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
B, C = rd("bootstrap.sh"), rd("convert.sh")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:80]
    return src.replace(a, b)

if PERTURB:
    B = plant(B, 'if [ "$ROLE" = master ] && ! has_comp "$OTHER" panel && ! has_comp "$METHOD" panel; then',
              'if false; then')                                                                                  # [1]
    C = plant(C, '  docker_panel_present || [ -n "${SWG_RV_URL:-}" ] || die "no Docker panel on this box', '  true || die "')  # [2]
    B = plant(B, '  elif case "${SWG_RV_ROLE:-}" in master|host) true;; *) false;; esac', '  elif false')             # [3]

def fn(src, name):
    """`name(){ … }` as shipped: from its header to the first closing line at which the text parses."""
    m = re.search(r"^%s\(\)\{" % re.escape(name), src, re.M)
    assert m, "cannot extract " + name
    lines = src[m.start():].split("\n")
    for k, l in enumerate(lines):
        if not l.split("  #")[0].rstrip().endswith("}"):
            continue
        text = "\n".join(lines[:k + 1]) + "\n"
        if subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True).returncode == 0:
            return text
    raise AssertionError("unterminated " + name)

def between(src, a, b):
    i = src.index(a); j = src.index(b, i)
    return src[i:j]

def bash(script, cwd, env=None):
    e = dict(os.environ); e.update(env or {})
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, cwd=cwd,
                       stdin=subprocess.DEVNULL, start_new_session=True, timeout=30)   # no controlling terminal
    return p.returncode, p.stdout, p.stderr

PRE = ('set -euo pipefail\nRESET=""; BOLD=""; C_BLUE=""; C_BROWN=""; C_RED=""; C_BL=""\ncol(){ shift; printf %s "$*"; }\n'
       'b(){ printf %s "$*"; }\n_nlguard(){ :; }\n_pnl(){ :; }\nwarn(){ echo "WARN $*" >&2; }\ninfo(){ echo "INFO $*"; }\n'
       'die(){ echo "DIE $*" >&2; exit 9; }\nmenu(){ :; }\nmlabel(){ [ "$1" = baremetal ] && echo bare-metal || echo "$1"; }\n'
       'has_comp(){ case "$1-$2" in baremetal-panel) [ "$BARE_PANEL" = yes ];; baremetal-node) [ "$BARE_NODE" = yes ];;\n'
       '  docker-panel) [ "$DOCK_PANEL" = yes ];; docker-node) [ "$DOCK_NODE" = yes ];; *) return 1;; esac; }\n')
ASK = fn(B, "ask_choice") + fn(B, "ask_yn") + fn(B, "run_script")

# ── [1] the convert branch ────────────────────────────────────────────────────────────────────────────────────────
cross = between(B, 'ROLE_COMPS=""; case "$ROLE"', "\n# A plain (re-)install clears")
def boot(method, role, box, conv_rc=0, url="https://panel.example:8443"):
    """box = 'dnode' (Docker node only) | 'bnode' (bare node only) | 'dmaster' (Docker panel + node)."""
    d = tempfile.mkdtemp(prefix="mnb-"); dd = os.path.join(d, "dd"); os.makedirs(dd)
    open(os.path.join(dd, ".env"), "w").write("PANEL_URL=%s     # the panel this node dials\nNODE_TOKEN=x\n" % url)
    open(os.path.join(d, "convert.sh"), "w").write(
        '#!/bin/bash\nif [ "$1" = --check ]; then echo "CHECK $*"; exit 0; fi\necho "CONVERT $*"; exit %d\n' % conv_rc)
    flags = {"dnode": "no no no yes", "bnode": "no yes no no", "dmaster": "no no yes yes"}[box].split()
    body = ('BARE_PANEL=%s; BARE_NODE=%s; DOCK_PANEL=%s; DOCK_NODE=%s\n' % tuple(flags) +
            'METHOD=%s; ROLE=%s; ON_CONFLICT=convert; PASS=(); DOCKER_DIR=%s\n' % (method, role, dd) + cross +
            '\necho "FELL THROUGH ROLE=$ROLE"\n')
    return bash(PRE + ASK + body, d)

print("[1] bootstrap.sh: master on a node-only box converts the node only")
rc, out, err = boot("baremetal", "master", "dnode")
check("Docker node only + `master -on-conflict convert` → the pre-flight AND the convert are the NODE's",
      "CHECK --check docker baremetal node" in out and "CONVERT docker baremetal node" in out
      and "master" not in "".join(l for l in out.splitlines() if l.startswith(("CHECK", "CONVERT"))), (rc, out, err))
check("…it says why, naming the panel the node is enrolled to (the .env's comment left out)",
      "This box has only a node (enrolled to https://panel.example:8443)" in out and "would add a new panel" in out, out)
check("…and once the convert succeeded: no panel was installed, `host` adds one",
      rc == 0 and "No panel was installed" in out and '"host"' in out
      and out.index("No panel was installed") > out.index("CONVERT docker"), (rc, out))
rc, out, err = boot("baremetal", "master", "dnode", conv_rc=1)
check("a convert that FAILED says nothing about the result (no 'No panel was installed'), keeps its exit code",
      rc == 1 and "No panel was installed" not in out, (rc, out, err))
rc, out, err = boot("docker", "master", "bnode")
check("the mirror: bare node only + `docker master` → convert.sh baremetal docker node",
      "CHECK --check baremetal docker node" in out and "CONVERT baremetal docker node" in out and "No panel was installed" in out,
      (rc, out, err))
rc, out, err = boot("baremetal", "node", "dnode")
check("unchanged: `node` on the same box → the node convert, no new line before or after it",
      "CONVERT docker baremetal node" in out and "only a node" not in out and "No panel was installed" not in out, (rc, out, err))
rc, out, err = boot("baremetal", "master", "dmaster")
check("unchanged: a real Docker master + `master` → the master convert, nothing narrowed",
      "CHECK --check docker baremetal master" in out and "CONVERT docker baremetal master" in out
      and "only a node" not in out and "No panel was installed" not in out, (rc, out, err))

# ── [2] convert.sh's docker→bare panel path ───────────────────────────────────────────────────────────────────────
print("\n[2] convert.sh docker→bare host/master: no swg-panel container, no resume state → refused")
blk = between(C, 'if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then',
              '  getv(){')
check("the refusal sits before anything in that block is read or written",
      "mkdir" not in blk and "write_recovery" not in blk and "docker_panel_present" in blk or PERTURB, blk[-400:])
def conv(containers, rv_url=""):
    d = tempfile.mkdtemp(prefix="mnb-c-"); bd = os.path.join(d, "bin"); os.makedirs(bd)
    open(os.path.join(bd, "docker"), "w").write('#!/bin/bash\n[ "$1" = ps ] && printf "%%s\\n" %s\nexit 0\n' % containers)
    os.chmod(os.path.join(bd, "docker"), 0o755)
    s = (PRE + fn(C, "docker_panel_present") + 'FROM=docker; TO=baremetal; ROLE=master; DOCKER_DIR=%s; SWG_RV_URL=%s\n' % (d, rv_url)
         + blk + '\necho REACHED-SETTINGS\nfi\n')
    open(os.path.join(d, ".env"), "w").write("PANEL_URL=https://x\n")
    return bash(s, d, {"PATH": bd + ":" + os.environ["PATH"]})
rc, out, err = conv("swg-node")
check("a Docker node alone → refused, and the refusal names the role that works",
      rc == 9 and "no Docker panel on this box" in err and "node" in err and "REACHED" not in out, (rc, out, err))
rc, out, err = conv("swg-node swg-panel")
check("a Docker master (swg-panel container) → goes on as before", rc == 0 and "REACHED-SETTINGS" in out, (rc, out, err))
rc, out, err = conv("swg-node", rv_url="https://resumed")
check("a resume (the marker's state, container already gone) → goes on as before", rc == 0 and "REACHED-SETTINGS" in out, (rc, out, err))

# ── [3] the Resume block ──────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] bootstrap.sh's Resume: a master/host marker with no panel anywhere is dropped, not offered")
resume = between(B, "if [ -f /var/lib/swg-recovery ]; then", '\nif [ -z "$METHOD" ]; then')
def marker(role, panel="none", staged=False):
    d = tempfile.mkdtemp(prefix="mnb-m-"); dd = os.path.join(d, "dd"); os.makedirs(dd)
    rec = os.path.join(d, "swg-recovery"); etc = os.path.join(d, "etc-swg-panel"); os.makedirs(etc)
    open(rec, "w").write("SWG_RV_FROM='docker'\nSWG_RV_TO='baremetal'\nSWG_RV_ROLE='%s'\nSWG_RV_URL='localhost'\n" % role)
    if staged:
        open(os.path.join(etc, "auth"), "w").write("admin:pbkdf2_sha256$x\n")
    dl, de, dw = (os.path.join(d, x) for x in ("lib-swg-panel", "etc-empty", "www-wgstats"))
    os.makedirs(dl); os.makedirs(de); os.makedirs(dw)
    open(os.path.join(dl, "host_proc"), "w").write("convert-failed")        # what the old attempt leaves
    open(os.path.join(dw, "keep.txt"), "w").write("not ours")               # anything else: never removed
    trio = "/var/lib/swg-panel /etc/swg-panel /var/www/wgstats"
    assert resume.count(trio) == 1, "dir cleanup anchor moved"
    src = (resume.replace("/var/lib/swg-recovery", rec).replace("/etc/swg-panel/auth", os.path.join(etc, "auth"))
           .replace(trio, " ".join((dl, de, dw))))
    s = (PRE + 'ask_yn(){ echo "ASKED $1"; eval "$3=yes"; }\nrun_script(){ echo "RESUME $*"; }\n'
         + 'BARE_PANEL=%s; DOCK_PANEL=%s; DOCKER_DIR=%s; SD=%s; PASS=()\n' % (
             "yes" if panel == "bare" else "no", "yes" if panel == "docker" else "no", dd, d)
         + src + '\n[ -e %s ] && echo MARKER-KEPT || echo MARKER-GONE\nfor x in %s %s %s; do [ -e "$x" ] && echo "DIR-KEPT $x" || echo "DIR-GONE $x"; done\n' % (rec, dl, de, dw))
    return bash(s, d)
rc, out, err = marker("master")
check("ROLE=master marker, no panel on either method, nothing staged → dropped, said, no Resume",
      "MARKER-GONE" in out and "RESUME" not in out and "dropped an unfinished master conversion" in out
      and "Resume" not in err, (rc, out, err))
check("…and the dirs the old attempt left go when empty or holding only its host_proc; a dir with anything else stays",
      re.search(r"DIR-GONE \S*lib-swg-panel", out) and re.search(r"DIR-GONE \S*etc-empty", out)
      and re.search(r"DIR-KEPT \S*www-wgstats", out), out)
rc, out, err = marker("node")
check("…a node marker touches none of them", out.count("DIR-KEPT") == 3, out)
rc, out, err = marker("master", staged=True)
check("…the same with a staged login (an interrupted genuine master convert) → Resume offered as before",
      "RESUME convert.sh docker baremetal master" in out, (rc, out, err))
rc, out, err = marker("master", panel="docker")
check("…the same with a Docker panel still running → Resume offered as before", "RESUME convert.sh docker baremetal master" in out, (rc, out, err))
rc, out, err = marker("node")
check("a node marker → Resume offered as before", "RESUME convert.sh docker baremetal node" in out, (rc, out, err))

print()
if FAILS:
    print("RED — %d failed" % len(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
