#!/usr/bin/env python3
"""Self-test — WHAT AN UNINSTALL KEEPS NEVER HOLDS AN ID IT FREES, AND A RECOVERY ARCHIVE IS ROOT'S ALONE (F90).

A convert moves the panel's state aside WITH its owners (/var/lib/swg-panel.converted-*: swgpanel, group swg;
/etc/swg-panel.converted-*: 2775 root:swg). The uninstall kept those archives by default and deleted swgpanel, swgsub and
group swg, so the archives held a uid and a gid that belonged to nobody — and the next accounts created on the box took
them: a `useradd -m -U` account read the archived login hash and the LIVE panel's TLS key and could write into the
archive, a `useradd -r` account read the LIVE session.key (a forged operator session), the settings, the vault and every
PSK (1.8.8 qualification, round 10; 1.8.7 too).

  [1] seal_archive (lib/common.sh): the archive and everything in it → root:root (chown -R -h: a symlink inside is
      never followed), no group write, no setgid, nothing writable by others, the archive itself 700; a symlinked
      archive name is left alone; seal_archives finds every archive the globs name (and a moved SWG_DOCKER_DIR's)
  [2] teardown_bare_panel seals each state dir it moves aside, as it moves it
  [3] convert.sh seals every Docker dir it moves aside, and heals the old archives at the start of a real run;
      install-host.sh, install-node.sh, install-docker.sh and update.sh heal them too (never on a dry run)
  [4] uninstall.sh carries lib/common.sh's globs and seal exactly (its twin)
  [5] uninstall.sh: every userdel / groupdel comes after a hand_ids_to_root naming that account
  [6] hand_ids_to_root, driven: every path under what swg owns that carries the account's uid (or the group's gid)
      goes to root — a symlink as a link, never its target — and nothing outside those roots is touched (a
      container's storage, an operator's home); the recovery archives are sealed with it
  [7] the group goes only when it can: while a kept account still has swg as its group, nothing is handed to root and
      groupdel is not run (a kept panel would lose its own login and certificate)
  [8] the Docker node's recovery copy (.uninstalled-*) is sealed when it is made
  [9] the convert's recovery marker (the node token) is 0600 from its first byte

Run: python3 tests/orphan_ids_selftest.py        (0 = pass)
     --perturb   six plants, each run on its own: no hand-over before rm_panel's userdel · teardown moves without sealing ·
                 seal keeps the group bits · no heal in update.sh · hand_ids_to_root searches outside swg's roots · the
                 group handed over while a kept account still uses it — each must turn its own check red
"""
import os, re, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {k: os.environ.get("SWG_OI_" + k) or os.path.join(ROOT, f) for k, f in
         (("COMMON", "lib/common.sh"), ("UNINST", "uninstall.sh"), ("CONVERT", "convert.sh"), ("HOST", "install-host.sh"),
          ("NODE", "install-node.sh"), ("DOCKER", "install-docker.sh"), ("UPDATE", "update.sh"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("rmpanel", "UNINST", "  hand_ids_to_root swgpanel swgsub   # …and every other kept path", "  : swgpanel swgsub   # …and every other kept path",
     "[5] rm_panel: hand_ids_to_root names swgpanel swgsub before their userdel"),
    ("teardown", "COMMON", 'mv "$_d" "$_d.converted-$_ts" 2>/dev/null && seal_archive "$_d.converted-$_ts"; done',
     'mv "$_d" "$_d.converted-$_ts" 2>/dev/null; done', "[2] teardown_bare_panel seals each state dir it moves aside"),
    ("seal", "COMMON", "    chmod -R g-ws,o-w \"$p\" 2>/dev/null || true\n    if [ -d \"$p\" ]; then chmod 700 \"$p\" 2>/dev/null || true; fi\n",
     "    true\n", "[1] seal_archive: no group write, no setgid, nothing writable by others, the archive 700"),
    ("heal", "UPDATE", 'if $DRYRUN; then info "DRY RUN — nothing will change."; else seal_archives; fi',
     'if $DRYRUN; then info "DRY RUN — nothing will change."; fi', "[3] update.sh heals the archives (not on a dry run)"),
    ("scope", "UNINST", "           /opt/swg* /srv/swg* /var/www/wgstats* /var/log/swg* /etc/wireguard /etc/amnezia \"$DOCKER_DIR\" \"$DOCKER_DIR\".*; do",
     "           /opt/swg* /srv/swg* /var/www/wgstats* /var/log/swg* /etc/wireguard /etc/amnezia \"$DOCKER_DIR\" \"$DOCKER_DIR\".* /var/lib/docker /home; do",
     "[6] …and nothing outside those roots is touched"),
    ("groupdel", "UNINST", "  if ! $DRYRUN && [ -n \"$(getent passwd | awk -F: -v g=\"$_sg\" '$4 == g {print $1}' || true)\" ]; then",
     "  if false; then", "[7] a group still some kept account's own: nothing handed to root, no groupdel"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-10s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_OI_" + key: f.name}),
                           capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-10s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
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

def var(src, name):
    m = re.search(r"^%s='([^']*)'" % re.escape(name), src, re.M)
    assert m, "no " + name
    return m.group(1)

def stubdir(**scripts):
    d = tempfile.mkdtemp(prefix="oi-stub-")
    for n, body in scripts.items():
        p = os.path.join(d, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    return d

def bash(script, stubs=None, env=None):
    e = dict(os.environ, **(env or {}))
    if stubs:
        e["PATH"] = stubs + ":" + e["PATH"]
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True, text=True, env=e, timeout=120)
    return r.returncode, r.stdout + r.stderr

def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)

C, U = SRC["COMMON"], SRC["UNINST"]
# chown as a stub (the gate runs unprivileged): it logs, and never changes a thing — the modes are real chmod
CHOWN_LOG = 'echo "$(basename "$0") $*" >> "$OI_LOG"'

def archive(t):
    """an archive as a convert leaves it: 2775 / 750 dirs, 640 / 600 / 644 / 660 files, a symlink to a live file outside"""
    a = os.path.join(t, "etc/swg-panel.converted-20260927-162839"); os.makedirs(os.path.join(a, "tls"))
    live = os.path.join(t, "live-key.pem"); open(live, "w").write("LIVE"); os.chmod(live, 0o644)
    for rel, m in (("auth", 0o640), ("install.conf", 0o600), ("tls/key.pem", 0o640), ("tls/fullchain.pem", 0o644), (".update-request", 0o660)):
        open(os.path.join(a, rel), "w").write("x"); os.chmod(os.path.join(a, rel), m)
    os.symlink(live, os.path.join(a, "tls/current.pem"))
    os.chmod(os.path.join(a, "tls"), 0o2755); os.chmod(a, 0o2775)
    return a, live

print("[1] seal_archive / seal_archives (lib/common.sh)")
t = tempfile.mkdtemp(prefix="oi-seal-"); a, live = archive(t)
log = os.path.join(t, "log"); st = stubdir(chown=CHOWN_LOG, chgrp=CHOWN_LOG)
rc, out = bash(fn(C, "seal_archive") + 'seal_archive "%s"\n' % a, st, {"OI_LOG": log})
calls = open(log).read() if os.path.exists(log) else ""
check("[1] seal_archive: the archive and everything in it → root:root, a symlink inside never followed (chown -R -h)",
      rc == 0 and ("chown -R -h root:root %s" % a) in calls, (rc, out, calls))
bad = []
for dp, dns, fns in os.walk(a):
    for n in [dp] + [os.path.join(dp, x) for x in fns + dns]:
        if os.path.islink(n):
            continue
        m = mode(n)
        if m & (stat.S_IWGRP | stat.S_ISGID | stat.S_IWOTH):
            bad.append((n[len(t):], oct(m)))
check("[1] seal_archive: no group write, no setgid, nothing writable by others, the archive 700",
      not bad and mode(a) == 0o700, (bad, oct(mode(a))))
check("[1] …and the live file a symlink inside points at is untouched", mode(live) == 0o644, oct(mode(live)))
link = os.path.join(t, "etc/swg-panel.converted-20990101-000000"); os.symlink(live, link)
open(log, "w").close()
rc, out = bash(fn(C, "seal_archive") + 'seal_archive "%s"\n' % link, st, {"OI_LOG": log})
check("[1] a symlinked archive name is left alone", rc == 0 and open(log).read() == "" and mode(live) == 0o644, (rc, out, open(log).read()))

t2 = tempfile.mkdtemp(prefix="oi-glob-")
globs = var(C, "SWG_ARCHIVE_GLOBS")
want = ["etc/swg-panel.converted-1", "etc/swg-panel-dropins.converted-2", "etc/swg-panel-confs.converted-3.from-docker",
        "var/lib/swg-panel.converted-4", "var/lib/swg-panel.uninstalled-5", "opt/swg-panel-docker.converted-6",
        "opt/swg-panel-docker.uninstalled-7", "opt/swg-panel-docker.pre-convert-8", "srv/mydocker.converted-9"]
for w in want:
    os.makedirs(os.path.join(t2, w)); os.chmod(os.path.join(t2, w), 0o2775)
os.makedirs(os.path.join(t2, "var/lib/swg-panel")); os.chmod(os.path.join(t2, "var/lib/swg-panel"), 0o750)   # live: never sealed
tglobs = " ".join(t2 + g for g in globs.split())
rc, out = bash("SWG_ARCHIVE_GLOBS='%s'\n%s%sseal_archives\n" % (tglobs, fn(C, "seal_archive"), fn(C, "seal_archives")), st,
               {"OI_LOG": log, "SWG_DOCKER_DIR": os.path.join(t2, "srv/mydocker")})
unsealed = [w for w in want if mode(os.path.join(t2, w)) != 0o700]
check("[1] seal_archives finds every archive the globs name — .converted, .uninstalled, .pre-convert, dropins, confs, a moved Docker dir",
      rc == 0 and not unsealed, (rc, out, unsealed))
check("[1] …and never the live state dir", mode(os.path.join(t2, "var/lib/swg-panel")) == 0o750, oct(mode(os.path.join(t2, "var/lib/swg-panel"))))

print("\n[2] teardown_bare_panel")
td = fn(C, "teardown_bare_panel")
check("[2] teardown_bare_panel seals each state dir it moves aside",
      re.search(r'mv "\$_d" "\$_d\.converted-\$_ts" 2>/dev/null && seal_archive "\$_d\.converted-\$_ts"', td) is not None, td[-400:])

print("\n[3] the moves and the heals")
CV = SRC["CONVERT"]
moves = re.findall(r'mv "\$DOCKER_DIR" "\$_bak" 2>/dev/null[^\n]*', CV)
check("[3] convert.sh seals every Docker dir it moves aside (%d moves)" % len(moves),
      len(moves) == 4 and all("seal_archive \"$_bak\"" in m for m in moves), moves)
check("[3] convert.sh heals the old archives at the start of a real run (not on --check)",
      re.search(r'if \[ "\$CHECK" != yes \]; then\n[^\n]*\n[^\n]*CONVERSION[^\n]*\n  seal_archives', CV) is not None)
for key, anchor in (("HOST", '$DRYRUN || seal_archives'), ("NODE", '$DRYRUN || seal_archives'), ("DOCKER", '$DRYRUN || seal_archives'),
                    ("UPDATE", 'if $DRYRUN; then info "DRY RUN — nothing will change."; else seal_archives; fi')):
    check("[3] %s heals the archives (not on a dry run)" % os.path.basename(PATHS[key]) if key != "UPDATE"
          else "[3] update.sh heals the archives (not on a dry run)", SRC[key].count(anchor) == 1, SRC[key].count(anchor))

print("\n[4] uninstall.sh's twin")
strip = lambda s: re.sub(r"\s+", "", re.sub(r"(^|\s)#[^\n]*", r"\1", s))
norm = lambda s: re.sub(r"\brun ", "", s).replace("_seal_archive", "seal_archive").replace("_SEAL_GLOBS", "SWG_ARCHIVE_GLOBS")
body = lambda s: strip(s[s.index("{"):])
check("[4] the globs are lib/common.sh's", var(U, "_SEAL_GLOBS") == var(C, "SWG_ARCHIVE_GLOBS"), (var(U, "_SEAL_GLOBS"), var(C, "SWG_ARCHIVE_GLOBS")))
check("[4] _seal_archive is seal_archive (run-wrapped, for --dry-run)",
      body(norm(fn(U, "_seal_archive"))) == body(fn(C, "seal_archive")),
      (norm(fn(U, "_seal_archive")), fn(C, "seal_archive")))

print("\n[5] every account this run deletes is handed over first")
def order(text, acct):
    text = re.sub(r"(^|\s)#[^\n]*", r"\1", text)          # code only: a comment may name either
    i = text.find("hand_ids_to_root")
    names = re.findall(r"hand_ids_to_root ([^#\n]*)", text)
    d = min([m.start() for m in re.finditer(r"\b(userdel|groupdel)\b", text)] or [-1])
    return i >= 0 and d > i and all(any(a in n.split() for n in names) for a in acct)
check("[5] rm_panel: hand_ids_to_root names swgpanel swgsub before their userdel", order(fn(U, "rm_panel"), ("swgpanel", "swgsub")))
check("[5] rm_node: hand_ids_to_root names swgpush swgagent before their userdel", order(fn(U, "rm_node"), ("swgpush", "swgagent")))
check("[5] rm_leftovers: hand_ids_to_root names all four before their userdel",
      order(fn(U, "rm_leftovers"), ("swgpanel", "swgsub", "swgpush", "swgagent")))
g = U[U.index("# group cleanup (shared by panel + agent)"):]; g = g[:g.index("\nfi\n") + 4]
check("[5] the group: hand_ids_to_root swg before groupdel swg", order(g, ("swg",)), g)
dels = len(re.findall(r"^[^#\n]*\b(?:userdel|groupdel)\b", U, re.M))
check("[5] …and there is no other userdel / groupdel in uninstall.sh (%d)" % dels, dels == 6, dels)

print("\n[6] hand_ids_to_root, driven")
H = fn(U, "hand_ids_to_root")
t3 = tempfile.mkdtemp(prefix="oi-hand-")
H3 = H
for r in ("/etc/swg-panel*", "/etc/swg-sub*", "/etc/swg-agent*", "/var/lib/swg-panel*", "/var/lib/swg-noded*", "/var/lib/swg-recovery*",
          "/opt/swg*", "/srv/swg*", "/var/www/wgstats*", "/var/log/swg*", "/etc/wireguard", "/etc/amnezia", "/var/lib/docker", "/home"):
    H3 = re.sub(r"(?<=\s)" + re.escape(r) + r"(?=[\s;])", lambda m: t3 + r, H3)   # the roots, under a scratch dir
assert not re.search(r"(?<=\s)/(etc|var|opt|srv|home)/", H3), "a root of hand_ids_to_root was not moved under the scratch dir — this drive would search the real box"
inside = ["etc/swg-panel.converted-1/auth", "var/lib/swg-panel.converted-1/session.key", "opt/swg-panel-docker/data/lib/users.json",
          "etc/swg-panel/tls/key.pem", "var/lib/swg-noded/.update-request", "srv/mydocker/data/lib/nodes.json"]
outside = ["var/lib/docker/overlay2/l1/etc/passwd", "home/alice/notes.txt", "opt-other/app/data"]
for rel in inside + outside:
    p = os.path.join(t3, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write("x")
os.symlink(os.path.join(t3, "home/alice/notes.txt"), os.path.join(t3, "etc/swg-panel.converted-1/link"))
me, mygid = os.getuid(), os.getgid()
st6 = stubdir(chown=CHOWN_LOG, chgrp=CHOWN_LOG, chmod=":",
              id='[ "$1" = -u ] && [ "$2" = swgpanel ] && { echo %d; exit 0; }; exit 1' % me,
              getent='[ "$1" = group ] && [ "$2" = swg ] && { echo "swg:x:%d:"; exit 0; }; exit 2' % mygid)
log6 = os.path.join(t3, "log")
rc, out = bash("DRYRUN=false; DOCKER_DIR=%s\nrun(){ \"$@\"; }\n_seal_archives(){ echo SEALED >> \"$OI_LOG\"; }\n%shand_ids_to_root swgpanel\n"
               % (os.path.join(t3, "srv/mydocker"), H3), st6, {"OI_LOG": log6})
got = open(log6).read() if os.path.exists(log6) else ""
check("[6] every path under swg's roots carrying the account's uid → root (%d)" % len(inside),
      rc == 0 and "chown -h root" in got and all(os.path.join(t3, rel) in got for rel in inside), (rc, out, got[:600]))
check("[6] …and nothing outside those roots is touched (a container's storage, an operator's home)",
      not any(os.path.join(t3, rel) in got for rel in outside), [l for l in got.splitlines() if any(o in l for o in outside)])
check("[6] …a symlink as a link (chown -h), never its target", os.path.join(t3, "etc/swg-panel.converted-1/link") in got
      and os.path.join(t3, "home/alice/notes.txt") not in got, got[:400])
check("[6] …and the recovery archives are sealed with it", "SEALED" in got, got[-200:])
open(log6, "w").close()
rc, out = bash("DRYRUN=false; DOCKER_DIR=%s\nrun(){ \"$@\"; }\n_seal_archives(){ :; }\n%shand_ids_to_root swg\n"
               % (os.path.join(t3, "srv/mydocker"), H3), st6, {"OI_LOG": log6})
got = open(log6).read()
check("[6] the group's gid: every path under swg's roots in that group → group root",
      rc == 0 and all(os.path.join(t3, rel) in got for rel in inside) and "chgrp -h root" in got
      and not any(os.path.join(t3, rel) in got for rel in outside), (rc, out, got[:400]))

print("\n[7] the group goes only when it can")
G = g
def group_block(primary_user):
    st7 = stubdir(getent='case "$1" in group) echo "swg:x:4242:";; passwd) %s;; esac; exit 0' %
                  ('echo "swgpanel:x:999:4242::/var/lib/swg-panel:/usr/sbin/nologin"' if primary_user else 'echo "root:x:0:0::/root:/bin/bash"'))
    return bash("DRYRUN=false; REMOVED_PANEL=false; REMOVED_NODE=true; REMOVED_LEFTOVERS=false\n"
                "run(){ echo \"RUN $*\"; }; info(){ echo \"INFO $*\"; }; hand_ids_to_root(){ echo \"HAND $*\"; }\n" + G, st7)
rc, out = group_block(True)
check("[7] a group still some kept account's own: nothing handed to root, no groupdel",
      rc == 0 and "HAND" not in out and "RUN groupdel" not in out and "still in use" in out, out)
rc, out = group_block(False)
check("[7] …a group nobody holds: handed to root, then groupdel", rc == 0 and out.find("HAND swg") >= 0
      and out.find("RUN groupdel swg") > out.find("HAND swg"), out)

print("\n[8] the Docker node's recovery copy")
check("[8] the .uninstalled-* copy is sealed when it is made",
      re.search(r'run sed -i -E [^\n]*"\$_bak/\.env"\n\s*_seal_archive "\$_bak"', U) is not None)

print("\n[9] the convert's recovery marker")
wr = fn(CV, "write_recovery")
t9 = tempfile.mkdtemp(prefix="oi-rec-"); rec = os.path.join(t9, "swg-recovery")
rc, out = bash('umask 022; RECOVERY=%s; FROM=docker; TO=baremetal; ROLE=node; NTOK=tok; PURL=https://p; NEP=1.2.3.4\n%s'
               'chmod(){ :; }\nwrite_recovery wg0\n' % (rec, wr))
check("[9] the recovery marker (the node token) is 0600 from its first byte — not by a chmod after",
      rc == 0 and os.path.exists(rec) and mode(rec) == 0o600 and "SWG_RV_TOKEN='tok'" in open(rec).read(),
      (rc, out, oct(mode(rec)) if os.path.exists(rec) else "missing"))

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
