#!/usr/bin/env python3
"""Self-test — a FULL uninstall, run FOR REAL over a fake box, takes what swg left on it (1.8.9 qualification, round 2).

The WHOLE uninstall.sh runs here, not a lifted function: every absolute path it touches is moved under a temp root, the
PATH holds only stubs and a short list of plain tools, and the stubs keep state — the host's interfaces, iptables rules,
nft tables, ip rules, containers and images — so what the run leaves is read back afterwards. `rm` / `rmdir` / `cp` / `mv`
refuse any path outside the box, and such an escape fails the section that made it.

  [1] a Docker NODE whose container is ALREADY GONE (`docker rm -f swg-node`, a crash, a `compose down` first — 1.8.8
      deferred #15, measured again by LC-24 lc7): the run listed only "Docker deployment (files)", left wg0 and the mesh
      link UP, their FORWARD/NAT rules, the swg nft tables and ip rules, and said "✓ Uninstall complete". Now the node is
      offered as the node it was (its data/node + node-confs say one ran here): its interfaces go, their rules, its nft
      tables — with its own nft, from the image its .env names, when the box still has it — and the datapath sweep runs
  [2] …the image gone too: nothing is pulled; the interfaces go, the host's nft takes the tables
  [3] a Docker MASTER whose node container is gone and whose panel container is not (1.8.8 round 12c, R28): the node is
      offered BEFORE the panel — whose data-dir answer takes node-confs with it — and its host side goes
  [4] a panel-only Docker box with no container left is still just "Docker deployment (files)"
  [5] a dry run of [1] changes nothing
  [6] a BARE node beside a Docker data dir an earlier uninstall kept: no gone node is made up — the host's interfaces and
      tables are the bare node's; the kept data is "Docker deployment (files)", as before
  [7] a bare Debian node — AmneziaWG BUILT FROM SOURCE (1.8.8 deferred #1, #16, #2): never offered, so its tools, man pages,
      unit templates, the DKMS tree (DKMS rebuilt the module at every kernel upgrade, on a box without swg) and the pinned
      amneziawg-go stayed. Now offered and taken, `dkms remove … --all` included; each removed interface's unit is stopped
      before the interface goes (a boot-started one stayed "active (exited)", and failed once its package went)
  [8] …beside a foreign AmneziaWG interface: offered, never removed unattended (kept, every file of it)
  [9] Ubuntu on the PPA's packages: none of the package's files is called a source build; the purge takes amneziawg-go
  [10] a bare → Docker converted box: the PPA packages its bare past installed are offered (the amnezia PPA is swg's)
  [11]–[15] what else a FULL uninstall left (1.8.8 deferred #3): 22.04's PPA key (+ .gpg~) and /root/.launchpadlib (a, b);
      the source fallback's PPA list (LC-24 lc7); an empty /var/www after a bare master (c); 26.04's local/wg the grant created,
      emptied and left, and a revert line claiming "a kept userspace server" before any keep question (d); route_localnet=1
      LIVE after the files that set it went — hosts on the box's network reach its 127.0.0.1 services until a reboot (e),
      bare and Docker; an operator's own sysctl file asking for it and their own local/wg lines are kept
  [17] a Docker uninstall leaves Docker Engine and says so in the summary, with how to remove it; a bare one says nothing
      (1.8.8 deferred #8)
  [18] a bare node's WDTT and csqtt servers under the documented `WDTT_DATA_DEL=y CSQTT_DATA_DEL=y`: /opt/swg-wdtt and
      /opt/swg-csqtt were left empty (the per-instance answer was normalised, the parent's removal read the RAW preset) —
      now the dir goes once empty; an identity kept keeps its dir (1.8.9 qualification D12-3)
  [19] a bare → Docker converted node: the bare csqtt store no unit names (the convert deleted the units) was never offered
      and outlived a FULL uninstall — its clients' passwords on a box the operator wiped. Now asked about by path, with
      rm_csqtt's question and preset, and nothing of a server torn down for it (L8-a)
  [20] the datapath sweep takes the torrent policy's rule (`6880: from all fwmark 0x40000000 lookup main` under Direct —
      measured left on every OS) and never flushes main; /etc/sysctl.d/99-swg-turn.conf (swg-noded's turn socket caps, kept
      across every reboot after the uninstall) goes with the other two sysctl files (1.8.9 qualification NR-6, DEB-2)
  [21] a turn proxy behind NAT / DDNS is listed (and asked about) by the host its clients dial — SWG_DIAL, as every other
      list reads it — not its bind 0.0.0.0; one whose dial is its bind as before (1.8.9 qualification FN-2(a), a dry run)
  [16] systemd < 254: the restart back-off swg-noded writes in the three family dirs (swg-restart.conf, D12-1) — rm_node no
      longer says it "keeps" a dir that holds only that file (the end of the run takes both); an operator's own drop-in
      there is still said and kept

Run: python3 tests/uninstall_full_selftest.py        (0 = pass)
     SWG_UNINSTALL=<file>   run it against another uninstall.sh
     --perturb-gone    the gone node is not offered (as shipped) → RED on [1] [2] [3]
     --perturb-bare    …it is, beside a bare node too → RED on [6] only
     --perturb-src     the source build is not offered (as shipped) → RED on [7] [8] [12] (the fallback's PPA goes with it)
     --perturb-stop    a removed interface's unit is not stopped (as shipped) → RED on [7]'s unit check only
     --perturb-ppa     the PPA packages are offered only beside a bare install (as shipped) → RED on [10] only
     --perturb-go      the package purge leaves amneziawg-go (as shipped) → RED on [9]'s amneziawg-go check only
     --perturb-key     the PPA's key file and /root/.launchpadlib stay (as shipped) → RED on [11] [12]
     --perturb-srcppa  the source build's removal leaves the PPA (as shipped) → RED on [12] only
     --perturb-www     an empty /var/www stays (as shipped) → RED on [13]'s /var/www check only
     --perturb-aa      the emptied local/wg stays (as shipped) → RED on [13]'s local/wg check only
     --perturb-aatext  the revert line claims a kept server (as shipped) → RED on [13]'s revert-line check only
     --perturb-rl      route_localnet stays 1 (as shipped) → RED on [13] [15]'s route_localnet checks only
     --perturb-rlown   …turned off even where another file asks for it → RED on [14]'s route_localnet check only
     --perturb-keepmsg rm_log_ns says it keeps a family dir holding only swg-restart.conf → RED on [16] only
     --perturb-engine  the Docker uninstall's summary is silent about Docker Engine (as shipped) → RED on [17]'s first check only
     --perturb-d123    the raw `= yes` preset test back (as shipped) → RED on [18] and [19]'s nothing-left check only
     --perturb-orphan  state no unit runs from is never offered (as shipped) → RED on [19]'s question and nothing-left checks only
     --perturb-6880    the sweep skips the torrent policy's rule (as shipped) → RED on [20]'s 6880 check only
     --perturb-turnconf  99-swg-turn.conf stays (as shipped) → RED on [20]'s sysctl check only
     --perturb-dial    a turn proxy listed by its bind (as shipped) → RED on [21]'s first check only
     --perturb-image   its image is not read from the .env → RED on [1]'s own-nft check only
"""
import json, os, re, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
U = open(os.environ.get("SWG_UNINSTALL") or os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
FLAGS = {f: f in sys.argv[1:] for f in ("--perturb-gone", "--perturb-image", "--perturb-bare", "--perturb-src", "--perturb-stop",
                                         "--perturb-ppa", "--perturb-go", "--perturb-key", "--perturb-srcppa", "--perturb-www",
                                         "--perturb-aa", "--perturb-aatext", "--perturb-rl", "--perturb-rlown", "--perturb-keepmsg",
                                         "--perturb-engine", "--perturb-d123", "--perturb-orphan", "--perturb-6880",
                                         "--perturb-turnconf", "--perturb-dial")}
PERTURBED = any(FLAGS.values())

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[-1500:]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def plant(a, b):
    global U
    assert U.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    U = U.replace(a, b)

if FLAGS["--perturb-gone"]:
    plant('   && { [ -d "$DOCKER_DIR/data/node" ] || [ -d "$DOCKER_DIR/data/node-confs" ]; }; then\n', '   && false; then\n')
if FLAGS["--perturb-bare"]:
    plant('if ! $DNODE && [ ! -f "$SD/swg-noded.service" ] && [ ! -d /opt/swg-noded ] \\\n', 'if ! $DNODE \\\n')
if FLAGS["--perturb-src"]:
    plant('{ awg_src_tools || [ -n "$(awg_src_trees)" ]; } && $_bare_swg && {', 'false && {')
if FLAGS["--perturb-stop"]:
    plant('    else run systemctl stop "${tool}@$n" >/dev/null 2>&1 || true   # its unit FIRST', '    else :   # its unit FIRST')
if FLAGS["--perturb-ppa"]:
    plant('awg_pkg    && { $_bare_swg || ls /etc/apt/sources.list.d/*amnezia* >/dev/null 2>&1; } &&', 'awg_pkg    && $_bare_swg &&')
if FLAGS["--perturb-go"]:
    plant('      rmrf /usr/local/bin/amneziawg-go   # the userspace fallback', '      :   # the userspace fallback')
if FLAGS["--perturb-key"]:
    plant('  rmrf /etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg /etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg~ /root/.launchpadlib; return 0; }',
          '  return 0; }')
if FLAGS["--perturb-srcppa"]:
    plant('  awg_pkg || _awg_ppa_forget   # the PPA, when no package of it is left\n', '')
if FLAGS["--perturb-www"]:
    plant('/etc/wireguard /var/www; do', '/etc/wireguard; do')
if FLAGS["--perturb-aa"]:
    plant('    [ -s "$_aal" ] || ! grep -qsE', '    true || ! grep -qsE')
if FLAGS["--perturb-aatext"]:
    plant("(should you keep a WDTT / csqtt server or a userspace awg interface below, the wg CLI can no longer read its socket)",
          "(a kept userspace server's socket becomes unreadable by the wg CLI)")
if FLAGS["--perturb-rl"]:
    plant('    || run sysctl -q -w net.ipv4.conf.all.route_localnet=0 >/dev/null 2>&1 || true\n', '    || true\n')
if FLAGS["--perturb-rlown"]:
    plant("  grep -qsE --exclude='99-swg-*' '^", "  false && grep -qsE --exclude='99-swg-*' '^")
if FLAGS["--perturb-keepmsg"]:
    plant('    [ "$(ls -A "$SD/$u.d" 2>/dev/null)" = swg-restart.conf ] || rmdir_if_empty "$SD/$u.d";', '    rmdir_if_empty "$SD/$u.d";')
if FLAGS["--perturb-engine"]:
    plant('case " ${DID_REMOVE[*]-} " in *" Docker "*) command -v docker', 'case "" in *" Docker "*) command -v docker')
if FLAGS["--perturb-d123"]:
    plant('    $DRYRUN || rmdir "$WDTT_DIR" 2>/dev/null || true', '    [ "${WDTT_DATA_DEL:-}" = yes ] && rmrf "$WDTT_DIR"')
    plant('    $DRYRUN || rmdir "$CSQTT_DIR" 2>/dev/null || true', '    [ "${CSQTT_DATA_DEL:-}" = yes ] && rmrf "$CSQTT_DIR"')
if FLAGS["--perturb-orphan"]:
    plant('_fork_orphans(){ local d k; for d in', '_fork_orphans(){ return 0; local d k; for d in')
if FLAGS["--perturb-6880"]:
    plant("awk '$1==6880 || ($1>=6890 && $1<=6989)'", "awk '$1>=6890 && $1<=6989'")
if FLAGS["--perturb-turnconf"]:
    plant(" /etc/sysctl.d/99-swg-turn.conf   # + swg-noded's", "   # + swg-noded's")
if FLAGS["--perturb-dial"]:
    plant("\"$({ sed -n 's/^SWG_DIAL=//p' \"$envf\"; sed -n 's/^SWG_LISTEN=//p' \"$envf\"; } 2>/dev/null | awk 'NF && !d {print; d=1}')\"",
          "\"$(sed -n 's/^SWG_LISTEN=//p' \"$envf\" 2>/dev/null | sed -n 1p)\"")
if FLAGS["--perturb-image"]:
    plant('  [ -n "$img" ] || { _tag="$(sed -n ', '  false && { _tag="$(sed -n ')

T = tempfile.mkdtemp(prefix="unin-full-")

# ── the box: every absolute path the uninstaller names moves under it ──────────────────────────────────────────────────
_ROOTS = ("/opt/", "/etc/", "/var/", "/srv/", "/root/", "/run/", "/usr/local/bin/", "/usr/local/lib/", "/usr/src/", "/usr/bin/awg",
          "/usr/share/man/", "/lib/systemd/", "/usr/lib/systemd/", "/lib/modules/", "/lib/sysctl.d/", "/usr/lib/sysctl.d/")
_RE = re.compile(r"(?<![\w./])(" + "|".join(re.escape(r) for r in _ROOTS) + ")")
def rooted(text, box):
    return _RE.sub(lambda m: box + m.group(1), text)

# ── the stubs: one program, dispatched on its name; state in $BOX/fx ───────────────────────────────────────────────────
STUB = r'''#!/usr/bin/python3 -I
import os, re, sys
BOX = os.environ["BOX"]; FX = os.path.join(BOX, "fx"); name = os.path.basename(sys.argv[0]); a = sys.argv[1:]
with open(os.path.join(BOX, "calls.log"), "a") as f:
    f.write(name + "\t" + " ".join(a) + "\n")
def rd(n):
    p = os.path.join(FX, n)
    return open(p).read() if os.path.exists(p) else ""
def ls(n):
    return [l for l in rd(n).splitlines() if l.strip()]
def wr(n, items):
    open(os.path.join(FX, n), "w").write("".join(x + "\n" for x in items))
def escape(p):
    return p.startswith("/") and not os.path.realpath(p).startswith(os.path.realpath(BOX) + "/") and p != "/dev/null"
if name in ("rm", "rmdir", "cp", "mv", "mkdir", "chmod", "ln", "touch"):
    bad = [x for x in a if not x.startswith("-") and escape(x)]
    if bad:
        open(os.path.join(BOX, "escapes.log"), "a").write(name + " " + " ".join(a) + "\n"); sys.exit(99)
    real = {"rm": "/bin/rm", "rmdir": "/bin/rmdir", "cp": "/bin/cp", "mv": "/bin/mv", "mkdir": "/bin/mkdir",
            "chmod": "/bin/chmod", "ln": "/bin/ln", "touch": "/usr/bin/touch"}[name]
    os.execv(real, [name] + a)
if name == "docker":
    ctrs = ls("docker.ps"); s = " ".join(a)
    if a[:1] == ["ps"]:
        m = re.search(r"name=([A-Za-z0-9_-]+)", s)
        for c in ctrs:
            if not m or m.group(1) in c:
                print(c)
        sys.exit(0)
    if a[:1] == ["inspect"]:
        if a[-1] in ctrs:
            print(rd("docker.image").strip() if "-f" in a else "{}"); sys.exit(0)
        sys.exit(1)
    if a[:2] == ["image", "inspect"]:
        sys.exit(0 if a[2] in ls("docker.images") else 1)
    if a[:1] == ["exec"]:
        sys.exit(1 if a[1] not in ctrs else 0)
    if a[:1] == ["rm"]:
        wr("docker.ps", [c for c in ctrs if c not in a]); sys.exit(0)
    if a[:1] == ["run"]:
        if "nft" in a and "list" in a:
            print(rd("nft.tables"), end=""); sys.exit(0)
        if "nft" in a and "-f" in a:
            dels = [l.split()[2:4] for l in sys.stdin.read().splitlines() if l.startswith("delete table ")]
            wr("nft.tables", [t for t in ls("nft.tables") if t.split()[1:3] not in dels])
            open(os.path.join(BOX, "own-nft.log"), "a").write(" ".join(d[1] for d in dels) + "\n"); sys.exit(0)
        sys.exit(0)
    if a[:1] == ["pull"]:
        open(os.path.join(BOX, "pulled.log"), "a").write(s + "\n"); sys.exit(1)
    sys.exit(0)
if name == "ip":
    links = ls("ip.links")
    if a[:2] == ["link", "show"]:
        sys.exit(0 if a[-1] in links else 1)
    if a[:2] == ["link", "delete"]:
        if a[-1] in links:
            wr("ip.links", [l for l in links if l != a[-1]]); sys.exit(0)
        sys.exit(1)
    if a[:2] == ["rule", "show"]:
        print(rd("ip.rules"), end=""); sys.exit(0)
    if a[:2] == ["rule", "del"]:
        if "pref" in a:
            p = a[a.index("pref") + 1]; r = ls("ip.rules")
            for i, l in enumerate(r):
                if l.startswith(p + ":"):
                    del r[i]; wr("ip.rules", r); sys.exit(0)
        sys.exit(2)
    if a[:2] == ["route", "flush"]:
        sys.exit(0)
    if "addr" in a:
        print("2: eth0    inet 192.168.77.9/24 brd 192.168.77.255 scope global eth0"); sys.exit(0)
    sys.exit(0)
if name == "iptables":
    t = "filter"; x = list(a)
    if "-t" in x:
        i = x.index("-t"); t = x[i + 1]; del x[i:i + 2]
    r = ls("ipt." + t)
    if x[:1] == ["-S"]:
        for l in r:
            if len(x) < 2 or l.split()[1] == x[1]:
                print(l)
        sys.exit(0)
    if x[:1] == ["-D"]:
        spec = "-A " + " ".join(x[1:])
        for i, l in enumerate(r):
            if l.replace('"', "") == spec:
                del r[i]; wr("ipt." + t, r); sys.exit(0)
        sys.exit(1)
    if x[:1] == ["-F"]:
        wr("ipt." + t, [l for l in r if not l.startswith("-A %s " % x[1])]); sys.exit(0)
    if x[:1] == ["-X"]:
        wr("ipt." + t, [l for l in r if l != "-N " + x[1]]); sys.exit(0)
    sys.exit(0)
if name == "nft":
    if a[:2] == ["list", "tables"]:
        print(rd("nft.tables"), end=""); sys.exit(0)
    if a[:2] == ["delete", "table"]:
        wr("nft.tables", [t for t in ls("nft.tables") if t.split()[1:3] != a[2:4]]); sys.exit(0)
    sys.exit(0)
if name == "ipset":
    if a[:2] == ["list", "-name"]:
        print(rd("ipset"), end=""); sys.exit(0)
    if a[:1] == ["destroy"]:
        wr("ipset", [n for n in ls("ipset") if n != a[1]])
    sys.exit(0)
if name in ("awg-quick", "wg-quick"):
    links = ls("ip.links")
    if a[:1] == ["down"] and a[1] in links:
        wr("ip.links", [l for l in links if l != a[1]]); sys.exit(0)
    sys.exit(1)
if name == "systemctl":
    if a[:1] in (["is-enabled"], ["is-active"]):
        sys.exit(1)
    sys.exit(0)
if name == "id":
    if a == ["-u"]:
        print(0); sys.exit(0)
    sys.exit(1)
if name == "getent":
    sys.exit(2)
if name == "hostname":
    print("192.168.77.9"); sys.exit(0)
if name == "nginx":
    sys.exit(1)
if name == "dpkg":
    if a[:1] == ["-S"]:
        sys.exit(0 if a[1].replace(BOX, "", 1) in ls("dpkg.owned") else 1)
    if a[:1] == ["-l"]:
        print(rd("dpkg.l"), end="")
    sys.exit(0)
if name == "sysctl":
    st = dict(l.split("=", 1) for l in ls("sysctl"))
    if a[:1] == ["-n"]:
        print(st.get(a[1], "0")); sys.exit(0)
    for x in a:
        if "=" in x:
            k, v = x.split("=", 1); st[k] = v
    wr("sysctl", ["%s=%s" % kv for kv in st.items()]); sys.exit(0)
if name == "dkms":
    if a[:1] == ["status"]:
        print(rd("dkms.status"), end="")
    sys.exit(0)
sys.exit(0)
'''
STUBS = ("docker", "ip", "iptables", "nft", "ipset", "systemctl", "awg-quick", "wg-quick", "awg", "wg", "id", "getent",
         "hostname", "userdel", "groupdel", "useradd", "apt-get", "add-apt-repository", "dpkg", "dpkg-query", "ufw",
         "apparmor_parser", "nginx", "modprobe", "depmod", "sysctl", "dkms", "chown", "chgrp", "findmnt",
         "rm", "rmdir", "cp", "mv", "mkdir", "chmod", "ln", "touch")
# the plain tools the script may run for real (everything else: "command not found", which the output shows)
REAL = ("bash", "sh", "cat", "ls", "grep", "sed", "awk", "tr", "cut", "head", "tail", "sort", "uniq", "wc", "basename",
        "dirname", "readlink", "mktemp", "date", "printf", "seq", "env", "xargs", "tee", "true", "false", "test", "[",
        "stat", "sleep", "find", "python3", "uname", "expr", "realpath", "comm", "od")

def mkbox(name, files, fx):
    box = os.path.join(T, name)
    os.makedirs(os.path.join(box, "fx")); os.makedirs(os.path.join(box, "bin")); os.makedirs(os.path.join(box, "tmp"))
    for rel, text in files.items():
        p = os.path.join(box, rel)
        if rel.endswith("/"):
            os.makedirs(p, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text.replace("@BOX@", box))
    for rel, text in fx.items():
        open(os.path.join(box, "fx", rel), "w").write(text)
    sp = os.path.join(box, "bin", ".stub"); open(sp, "w").write(STUB); os.chmod(sp, 0o755)
    for n in STUBS:
        os.symlink(sp, os.path.join(box, "bin", n))
    for n in REAL:
        for d in ("/usr/bin", "/bin"):
            if os.path.exists(os.path.join(d, n)) and not os.path.exists(os.path.join(box, "bin", n)):
                os.symlink(os.path.join(d, n), os.path.join(box, "bin", n))
    open(os.path.join(box, "run.sh"), "w").write(rooted(U, box))
    return box

def run(box, *args, env=None):
    e = {"BOX": box, "HOME": os.path.join(box, "root"), "PATH": os.path.join(box, "bin"), "TMPDIR": os.path.join(box, "tmp"),
         "LANG": "C.UTF-8", "SWG_TTY_WARNED": "1"}
    e.update(env or {})
    for f in ("calls.log", "escapes.log", "own-nft.log", "pulled.log"):
        p = os.path.join(box, f)
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run(["/bin/bash", os.path.join(box, "run.sh")] + list(args), env=e, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300, start_new_session=True)
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    rdf = lambda n: open(os.path.join(box, n)).read() if os.path.exists(os.path.join(box, n)) else ""
    return r.returncode, out, rdf("calls.log"), rdf("escapes.log")

def fx(box, n):
    p = os.path.join(box, "fx", n)
    return [l for l in open(p).read().splitlines() if l.strip()] if os.path.exists(p) else []

def components(out):
    m = re.search(r"Found these installed components:\n\n(.*?)\n\n", out, re.S)
    return [l.strip() for l in (m.group(1).splitlines() if m else [])]

FULL = {"PANEL_DATA_DEL": "y", "ARCHIVES_DEL": "y", "DOCKER_DATA_DEL": "y", "DOCKER_KEEP_CONFS": "n",
        "REMOVE_DOCKER_IMAGES": "n", "WDTT_DATA_DEL": "y", "CSQTT_DATA_DEL": "y"}
IMG = "ghcr.io/sanityprotocol/swg-node:sha-52aa9c4"
ENV_NODE = ("# generated by install-docker.sh — profile: node\nPANEL_URL=https://127.0.0.1:9\nNODE_TOKEN=node-token-0123456789\n"
            "NODE_ENDPOINT=192.168.77.7\nTLS_VERIFY=no\nSWG_IMAGE_TAG=sha-52aa9c4\n")
NODE_FILES = {"opt/swg-panel-docker/.env": ENV_NODE, "opt/swg-panel-docker/docker-compose.yml": "services: {}\n",
              "opt/swg-panel-docker/data/node/turn-proxy.json": '{"turn_proxies": []}',
              "opt/swg-panel-docker/data/node-confs/wg0.conf": "[Interface]\nAddress = 10.81.1.1/24\nListenPort = 51820\n",
              "opt/swg-panel-docker/data/node-confs/swg_839afbc0.conf": "[Interface]\nAddress = 10.255.0.0/31\nListenPort = 9999\n",
              "etc/systemd/system/swg-update.service": "[Service]\n", "etc/systemd/system/swg-update.path": "[Path]\n",
              "usr/local/bin/swg-update": "#!/bin/sh\n"}
# what a Docker node on host networking leaves in the host's kernel (LC-24 lc7: 2 nft tables, 17 iptables rules, 2 links)
NODE_FX = {"docker.ps": "", "docker.images": IMG + "\n",
           "ip.links": "lo\neth0\nwg0\nswg_839afbc0\n",
           "ip.rules": "0:\tfrom all lookup local\n7000:\tfrom 10.81.1.0/24 lookup 7000\n32766:\tfrom all lookup main\n32767:\tfrom all lookup default\n",
           "ipt.filter": ("-P FORWARD ACCEPT\n-N SWG_INET\n-A FORWARD -j SWG_INET\n-A FORWARD -i wg0 -j ACCEPT\n-A FORWARD -o wg0 -j ACCEPT\n"
                          "-A FORWARD -i swg_839afbc0 -j ACCEPT\n-A FORWARD -o swg_839afbc0 -j ACCEPT\n"
                          "-A FORWARD -i eth1 -o eth0 -j ACCEPT\n"
                          "-A SWG_INET -s 10.81.1.0/24 -m comment --comment \"swg-inet:wg0\" -j ACCEPT\n"),
           "ipt.nat": ("-P POSTROUTING ACCEPT\n-A POSTROUTING -s 10.81.1.0/24 -m comment --comment \"swg-nat:wg0\" -j MASQUERADE\n"
                       "-A POSTROUTING -s 10.81.1.0/24 -o eth0 -j MASQUERADE\n-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE\n"),
           "ipt.mangle": "-A FORWARD -o wg0 -p tcp -m comment --comment \"swg-mss:wg0\" -j TCPMSS --clamp-mss-to-pmtu\n",
           "nft.tables": "table ip filter\ntable inet swg_p2p\ntable inet swg_reach\n"}
OPERATOR_RULES = ("-A FORWARD -i eth1 -o eth0 -j ACCEPT", "-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE")

def swg_left(box):
    """What of swg's is still in the host's kernel: links, iptables lines naming it, nft tables, ip rules in its bands."""
    links = [l for l in fx(box, "ip.links") if l not in ("lo", "eth0")]
    ipt = [l for t in ("filter", "nat", "mangle") for l in fx(box, "ipt." + t)
           if re.search(r"swg|SWG|wg0|swg_839afbc0", l)]
    nft = [t for t in fx(box, "nft.tables") if t.split()[-1].startswith("swg")]
    rules = [r for r in fx(box, "ip.rules") if int(r.split(":")[0]) not in (0, 32766, 32767)]
    return {"links": links, "iptables": ipt, "nft": nft, "ip rules": rules}

def clean(left):
    return not any(left.values())

print("[1] a Docker node whose container is already gone — the image still on the box")
box = mkbox("gone-node", NODE_FILES, NODE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
OUT_DOCKER = out
comps = components(out)
check("the run stays inside its box (no rm/cp/mv outside it)", not esc, esc)
check("the node is offered as the node it was, its container named gone",
      any(c.startswith("Docker node (swg-node)") and "container is gone" in c for c in comps), comps)
check("…and not as mere \"Docker deployment (files)\" (the files go with it)", not any(c.startswith("Docker deployment (files)") for c in comps), comps)
left = swg_left(box)
check("NOTHING of the node is left in the kernel — its interfaces, their rules, its nft tables, its ip rules", clean(left), left)
check("its nft tables went with its OWN nft, from the image its .env names (no pull)",
      os.path.exists(os.path.join(box, "own-nft.log")) and "swg_p2p" in open(os.path.join(box, "own-nft.log")).read()
      and not os.path.exists(os.path.join(box, "pulled.log")), calls[-2500:])
check("an operator's own rules are untouched", all(any(l == r for l in fx(box, "ipt.filter") + fx(box, "ipt.nat")) for r in OPERATOR_RULES),
      fx(box, "ipt.filter") + fx(box, "ipt.nat"))
check("the Docker dir is gone (data deleted, as asked) and the run says it completed",
      not os.path.exists(os.path.join(box, "opt/swg-panel-docker")) and "Uninstall complete" in out, out[-1500:])

print("\n[2] …and its image gone too")
box = mkbox("gone-node-noimg", NODE_FILES, dict(NODE_FX, **{"docker.images": ""}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("the run stays inside its box", not esc, esc)
left = swg_left(box)
check("nothing of the node is left — the host's nft took the tables", clean(left), left)
check("nothing was pulled, nothing run from an image", not os.path.exists(os.path.join(box, "pulled.log"))
      and "docker\trun " not in calls, calls[-1500:])

print("\n[3] a Docker master: its node's container gone, its panel's still here")
mfiles = dict(NODE_FILES, **{"opt/swg-panel-docker/.env": ENV_NODE.replace("profile: node", "profile: master")
                             + "PANEL_DOMAIN=192.168.77.9\nPANEL_PASSWORD=x\n",
                             "opt/swg-panel-docker/data/lib/users.json": "{}", "opt/swg-panel-docker/data/etc/fleet.json": "{}"})
box = mkbox("gone-node-master", mfiles, dict(NODE_FX, **{"docker.ps": "swg-panel\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
comps = components(out)
check("the run stays inside its box", not esc, esc)
ni = next((k for k, c in enumerate(comps) if c.startswith("Docker node (swg-node)")), None)
pi = next((k for k, c in enumerate(comps) if c.startswith("Docker panel (swg-panel)")), None)
check("the node is offered, BEFORE the panel", ni is not None and pi is not None and ni < pi, comps)
left = swg_left(box)
check("nothing of the node is left in the kernel", clean(left), left)
check("the panel went too, and the data dir (asked once)", "swg-panel" not in fx(box, "docker.ps")
      and not os.path.exists(os.path.join(box, "opt/swg-panel-docker")) and out.count("Delete the data dir") == 1, out[-2000:])

print("\n[4] a panel-only Docker box, no container left")
pfiles = {"opt/swg-panel-docker/.env": "# generated by install-docker.sh — profile: host\nNODE_TOKEN=set-in-nodes-screen\nPANEL_DOMAIN=192.168.77.9\n",
          "opt/swg-panel-docker/docker-compose.yml": "services: {}\n", "opt/swg-panel-docker/data/lib/users.json": "{}"}
box = mkbox("panel-files", pfiles, {"docker.ps": "", "ip.links": "lo\neth0\n"})
rc, out, calls, esc = run(box, "--yes", env=FULL)
comps = components(out)
check("only \"Docker deployment (files)\" — no node is made up", [c.split("  ")[0] for c in comps] == ["Docker deployment (files)"], comps)

print("\n[5] a dry run of [1]")
box = mkbox("gone-node-dry", NODE_FILES, NODE_FX)
before = {n: fx(box, n) for n in os.listdir(os.path.join(box, "fx"))}
snap = sorted(os.path.relpath(os.path.join(dp, f), box) for dp, ds, fs in os.walk(box) for f in fs
              if not os.path.relpath(dp, box).startswith(("fx", "bin", "tmp")) and f not in ("calls.log",))
rc, out, calls, esc = run(box, "--dry-run", "--yes", env=FULL)
after = {n: fx(box, n) for n in os.listdir(os.path.join(box, "fx"))}
snap2 = sorted(os.path.relpath(os.path.join(dp, f), box) for dp, ds, fs in os.walk(box) for f in fs
               if not os.path.relpath(dp, box).startswith(("fx", "bin", "tmp")) and f not in ("calls.log",))
check("the kernel state and every file exactly as they were; the plan said", before == after and snap == snap2
      and "[dry]" in out and not esc, (before == after, sorted(set(snap) ^ set(snap2)), esc, out[-800:]))

print("\n[6] a bare node beside a Docker data dir an earlier uninstall kept")
bfiles = dict(NODE_FILES, **{"etc/systemd/system/swg-noded.service": "[Service]\n", "opt/swg-noded/swg-noded": "x",
                             "etc/swg-agent/config.json": '{"panel": {"url": "https://127.0.0.1:9", "token": "t"}, "interfaces": {"wg0": {}}}',
                             "etc/wireguard/wg0.conf": "[Interface]\nAddress = 10.71.1.1/24\nListenPort = 51820\n"})
box = mkbox("bare-beside-kept", bfiles, dict(NODE_FX, **{"ip.links": "lo\neth0\nwg0\n"}))
rc, out, calls, esc = run(box, "--yes", env=dict(FULL, DOCKER_DATA_DEL="y"))
comps = components(out)
check("[6] no gone Docker node is offered beside the bare node — its kept data is \"Docker deployment (files)\"",
      not any(c.startswith("Docker node (swg-node)") for c in comps) and any(c.startswith("Docker deployment (files)") for c in comps), comps)

# ── a bare node whose AmneziaWG was BUILT FROM SOURCE (every Debian node; Ubuntu's fallback) ─────────────────────────────
SRC_AWG = {"usr/bin/awg": "x", "usr/bin/awg-quick": "x", "usr/share/man/man8/awg.8": "x", "usr/share/man/man8/awg-quick.8": "x",
           "lib/systemd/system/awg-quick@.service": "[Service]\n", "lib/systemd/system/awg-quick.target": "[Unit]\n",
           "usr/src/amneziawg-1.0.0/dkms.conf": 'PACKAGE_NAME="amneziawg"\nPACKAGE_VERSION="1.0.0"\n',
           "usr/local/bin/amneziawg-go": "x"}
BARE_NODE = {"etc/systemd/system/swg-noded.service": "[Service]\n", "opt/swg-noded/swg-noded": "x", "opt/swg-agent/swg-agent": "x",
             "etc/swg-agent/config.json": '{"panel": {"url": "https://127.0.0.1:9", "token": "t", "verify": false}, '
                                          '"interfaces": {"awg0": {}, "wg0": {}}}',
             "etc/amnezia/amneziawg/awg0.conf": "[Interface]\nAddress = 10.60.2.1/24\nListenPort = 51821\n",
             "etc/amnezia/amneziawg/swg_88930e42.conf": "[Interface]\nAddress = 10.255.0.0/31\nListenPort = 9999\n",
             "etc/wireguard/wg0.conf": "[Interface]\nAddress = 10.60.1.1/24\nListenPort = 51820\n"}
BARE_FX = {"ip.links": "lo\neth0\nawg0\nwg0\nswg_88930e42\n", "dpkg.l": "ii  wireguard  1.0  all\nii  wireguard-tools  1.0  amd64\n",
           "dkms.status": "amneziawg/1.0.0, 6.1.0-53-cloud-amd64, x86_64: installed\n", "docker.ps": ""}
AWG_SRC_LEFT = lambda box: [p for p in SRC_AWG if os.path.lexists(os.path.join(box, p))]
SRC_LABEL = "AmneziaWG built from source (kernel module + tools)"

print("\n[7] a bare node on Debian: its AmneziaWG built from source")
box = mkbox("deb-src", dict(BARE_NODE, **SRC_AWG), BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
OUT_BARE = out
comps = components(out)
check("[7] the run stays inside its box", not esc, esc)
check("[7] the source build is offered for removal", any(c.startswith(SRC_LABEL) for c in comps), comps)
check("[7] …and taken: the tools, man pages, unit templates, the DKMS tree and the pinned amneziawg-go — nothing of it left",
      not AWG_SRC_LEFT(box), AWG_SRC_LEFT(box))
check("[7] DKMS forgets the module (`dkms remove amneziawg/1.0.0 --all`) — no rebuild at the next kernel",
      "dkms\tremove amneziawg/1.0.0 --all" in calls, calls[-1200:])
cl = calls.splitlines()
def at(pred):
    return next((k for k, l in enumerate(cl) if pred(l)), -1)
st_a, dn_a = at(lambda l: l == "systemctl\tstop awg-quick@awg0"), at(lambda l: l == "awg-quick\tdown awg0")
st_w, dn_w = at(lambda l: l == "systemctl\tstop wg-quick@wg0"), at(lambda l: l == "wg-quick\tdown wg0")
check("[7] each removed interface's unit is STOPPED before the interface goes (a boot-started one stayed \"active (exited)\", "
      "and failed once its package went — 1.8.8 deferred #16)", 0 <= st_a < dn_a and 0 <= st_w < dn_w, (st_a, dn_a, st_w, dn_w))

print("\n[8] …a foreign AmneziaWG interface beside it")
box = mkbox("deb-src-foreign", dict(BARE_NODE, **SRC_AWG, **{"etc/amnezia/amneziawg/awg9.conf": "[Interface]\nListenPort = 51999\n"}), BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[8] the source build is offered but never removed unattended then — kept, every file of it still there",
      any(c.startswith(SRC_LABEL) for c in components(out)) and "Kept %s." % SRC_LABEL in out
      and sorted(AWG_SRC_LEFT(box)) == sorted(SRC_AWG) and "dkms\tremove" not in calls, (components(out), AWG_SRC_LEFT(box), out[-1500:]))

print("\n[9] an Ubuntu node on the PPA's packages: nothing of them is called a source build")
box = mkbox("ubu-pkg", dict(BARE_NODE, **SRC_AWG),
            dict(BARE_FX, **{"dpkg.l": BARE_FX["dpkg.l"] + "ii  amneziawg  1.0  all\nii  amneziawg-tools  1.0  amd64\nii  amneziawg-dkms  1.0  all\n",
                             "dpkg.owned": "/usr/bin/awg\n/usr/bin/awg-quick\n/usr/src/amneziawg-1.0.0\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
comps = components(out)
check("[9] the package is offered, no \"built from source\" component, and its tree is never `dkms remove`d by us",
      any(c.startswith("AmneziaWG package") for c in comps) and not any(c.startswith(SRC_LABEL) for c in comps)
      and "dkms\tremove" not in calls, (comps, calls[-800:]))
check("[9] …and the purge takes the pinned userspace fallback with it (/usr/local/bin/amneziawg-go — 1.8.8 deferred #2)",
      not os.path.exists(os.path.join(box, "usr/local/bin/amneziawg-go")) and os.path.exists(os.path.join(box, "usr/bin/awg")), AWG_SRC_LEFT(box))

print("\n[10] a bare → Docker converted box: the PPA's packages its bare past installed")
cfiles = dict(NODE_FILES, **{"etc/apt/sources.list.d/amnezia-ubuntu-ppa-noble.sources": "Types: deb\n"})
box = mkbox("conv-ppa", cfiles, dict(NODE_FX, **{"docker.ps": "swg-node\n", "dpkg.l": "ii  amneziawg  1.0  all\nii  amneziawg-tools  1.0  amd64\nii  amneziawg-dkms  1.0  all\n",
                                               "dpkg.owned": "/usr/bin/awg\n/usr/src/amneziawg-1.0.0\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
comps = components(out)
check("[10] the AmneziaWG package (and its DKMS module, rebuilt at every kernel upgrade) is offered — the amnezia PPA is swg's",
      any(c.startswith("AmneziaWG package") for c in comps) and "apt-get\tpurge -y amneziawg amneziawg-tools amneziawg-dkms" in calls,
      (comps, calls[-800:]))

# ── #3: what else a FULL uninstall left (1.8.8 deferred #3 a–e) ──────────────────────────────────────────────────────────
AA_BLOCK = ("  # --- swgPanel: userspace WireGuard datapaths (begin) ---\n  /run/wireguard/ r,\n  /run/wireguard/*.sock rw,\n"
            "  /var/run/wireguard/ r,\n  /var/run/wireguard/*.sock rw,\n  # --- swgPanel: userspace WireGuard datapaths (end) ---\n")
PKG_L = "ii  amneziawg  1.0  all\nii  amneziawg-tools  1.0  amd64\nii  amneziawg-dkms  1.0  all\n"
def sysctl(box, k="net.ipv4.conf.all.route_localnet"):
    return dict(l.split("=", 1) for l in fx(box, "sysctl")).get(k)

print("\n[11] Ubuntu 22.04 on the PPA's packages: the PPA's key and add-apt-repository's cache")
box = mkbox("u2204-ppa", dict(BARE_NODE, **{"etc/apt/sources.list.d/amnezia-ubuntu-ppa-jammy.list": "deb x jammy main\n",
                                           "etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg": "K", "etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg~": "",
                                           "root/.launchpadlib/api.launchpad.net/cache/x": "c", "usr/bin/awg": "x"}),
            dict(BARE_FX, **{"dpkg.l": BARE_FX["dpkg.l"] + PKG_L, "dpkg.owned": "/usr/bin/awg\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[11] the run stays inside its box", not esc, esc)
check("[11] the PPA goes with its packages, and its key (+ the .gpg~ beside it) and /root/.launchpadlib with it (#3 a, b)",
      "add-apt-repository\t-y --remove ppa:amnezia/ppa" in calls and not [p for p in ("etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg",
      "etc/apt/trusted.gpg.d/amnezia-ubuntu-ppa.gpg~", "root/.launchpadlib") if os.path.lexists(os.path.join(box, p))], calls[-600:])

print("\n[12] Ubuntu's source fallback (LC-24 lc7): the PPA swg added first, no package of it installed")
box = mkbox("u2404-src", dict(BARE_NODE, **SRC_AWG, **{"etc/apt/sources.list.d/amnezia-ubuntu-ppa-noble.sources": "Types: deb\n",
                                                     "root/.launchpadlib/api.launchpad.net/cache/x": "c"}), BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[12] the PPA list and /root/.launchpadlib go with the source build", "add-apt-repository\t-y --remove ppa:amnezia/ppa" in calls
      and not os.path.lexists(os.path.join(box, "root/.launchpadlib")), calls[-600:])

print("\n[13] a bare master, FULL: an empty /var/www, 26.04's local/wg, route_localnet")
MASTER = dict(BARE_NODE, **{"etc/systemd/system/swg-panel-server.service": "[Service]\n", "opt/swg-panel/swg-panel-server": "x",
                            "etc/swg-panel/install.conf": "PANEL_DOMAIN=192.168.77.9\n", "var/lib/swg-panel/users.json": "{}",
                            "var/www/wgstats/x.json": "{}", "var/www/acme/.well-known/x": "x",
                            "etc/apparmor.d/wg": "profile wg /usr/bin/wg {\n  include if exists <local/wg>\n}\n",
                            "etc/apparmor.d/local/wg": AA_BLOCK,
                            "etc/sysctl.d/99-swg-forward.conf": "net.ipv4.ip_forward = 1\nnet.ipv4.conf.all.route_localnet = 1\n"})
box = mkbox("master", MASTER, dict(BARE_FX, **{"sysctl": "net.ipv4.conf.all.route_localnet=1\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[13] the run stays inside its box", not esc, esc)
check("[13] /var/www, left empty once the panel's stats and acme dirs went, goes (#3 c)", not os.path.exists(os.path.join(box, "var/www")),
      sorted(os.listdir(os.path.join(box, "var"))))
check("[13] the AppArmor local/wg the grant created — empty once our span is cut — goes; the profile includes it `if exists` (#3 d)",
      not os.path.exists(os.path.join(box, "etc/apparmor.d/local/wg")), calls[-400:])
rv = [l for l in out.splitlines() if "reverting the swgPanel AppArmor grant" in l]
check("[13] …and the revert line does not claim a kept userspace server when it cannot know one (it runs before the keep questions)",
      rv and not any("a kept userspace server" in l for l in rv), rv)
check("[13] route_localnet is OFF again — the file that set it is gone, and nothing else asks for it (#3 e)",
      sysctl(box) == "0" and not os.path.exists(os.path.join(box, "etc/sysctl.d/99-swg-forward.conf")), (sysctl(box), out[-600:]))

print("\n[14] …the operator's own: a sysctl file that asks for route_localnet, a local/wg holding their lines")
box = mkbox("master-own", dict(MASTER, **{"etc/sysctl.d/50-mine.conf": "net.ipv4.conf.all.route_localnet=1\n",
                                          "etc/apparmor.d/local/wg": "  /etc/mine r,\n" + AA_BLOCK}),
            dict(BARE_FX, **{"sysctl": "net.ipv4.conf.all.route_localnet=1\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[14] route_localnet stays 1 — another file asks for it", sysctl(box) == "1", sysctl(box))
check("[14] local/wg stays, their line in it, our span cut", open(os.path.join(box, "etc/apparmor.d/local/wg")).read() == "  /etc/mine r,\n"
      if os.path.exists(os.path.join(box, "etc/apparmor.d/local/wg")) else False)

print("\n[15] a Docker node, FULL: route_localnet")
box = mkbox("dnode-rl", dict(NODE_FILES, **{"etc/sysctl.d/99-swg-node.conf": "net.ipv4.ip_forward = 1\nnet.ipv4.conf.all.route_localnet = 1\n"}),
            dict(NODE_FX, **{"docker.ps": "swg-node\n", "sysctl": "net.ipv4.conf.all.route_localnet=1\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[15] route_localnet is OFF again after the Docker node's uninstall (measured left at 1: LC-24, Debian, Ubuntu 22.04/26.04)",
      sysctl(box) == "0", (sysctl(box), out[-600:]))

print("\n[16] systemd < 254: swg-noded's restart back-off drop-in in the three family dirs (1.8.9 qualification D12-1)")
rfiles = dict(BARE_NODE)
for fam in ("vk-turn-proxy-", "swg-wdtt-", "swg-csqtt-"):
    rfiles["etc/systemd/system/%s.service.d/swg-ns.conf" % fam] = "[Service]\nLogNamespace=swg-node\n"
    rfiles["etc/systemd/system/%s.service.d/swg-restart.conf" % fam] = "[Service]\nRestartSec=30\n"
box = mkbox("restart-dropins", rfiles, BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
keeping = [l for l in out.splitlines() if "keeping " in l and ".service.d" in l]
check("[16] no \"keeping …\" line about a family dir that holds only swg's own restart drop-in", not keeping, keeping)
check("[16] …and the dirs are gone at the end, the drop-in with them",
      not [d for d in os.listdir(os.path.join(box, "etc/systemd/system")) if d.endswith(".service.d")],
      os.listdir(os.path.join(box, "etc/systemd/system")))
rfiles["etc/systemd/system/vk-turn-proxy-.service.d/override.conf"] = "[Service]\nNice=5\n"
box = mkbox("restart-dropins-own", rfiles, BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
keeping = [l for l in out.splitlines() if "keeping " in l and ".service.d" in l]
check("[16] an operator's own drop-in there is still said and kept (only swg-restart.conf is ignored)",
      len(keeping) == 1 and "vk-turn-proxy-.service.d" in keeping[0]
      and sorted(os.listdir(os.path.join(box, "etc/systemd/system/vk-turn-proxy-.service.d"))) == ["override.conf"], (keeping, out[-800:]))

print("\n[17] Docker Engine: a Docker uninstall leaves it — and says so (1.8.8 deferred #8)")
def kept_list(out):
    return out.split("Kept:", 1)[1].split("\n\n", 1)[0] if "Kept:" in out else ""
check("[17] the summary of [1]'s Docker uninstall names Docker Engine under Kept, and how to remove it",
      "Docker Engine" in kept_list(OUT_DOCKER) and "apt-get purge docker-ce" in kept_list(OUT_DOCKER), OUT_DOCKER[-700:])
check("[17] …and [7]'s bare one says nothing about Docker", "Docker Engine" not in OUT_BARE, OUT_BARE[-500:])

# ── WDTT / csqtt state on the box (1.8.9 qualification D12-3, L8-a) ──────────────────────────────────────────────────
FORKS = {"etc/systemd/system/swg-wdtt-wdtt0.service": "[Unit]\nDescription=swg-wdtt (amurcanov/proxy-turn-vk-android)\n",
         "opt/swg-wdtt/wdtt0/wg-keys.dat": "K", "opt/swg-wdtt/wdtt0/wdtt.env": "SWG_LISTEN=0.0.0.0:56000\n",
         "opt/swg-wdtt/.bin/amurcanov/server": "x",
         "etc/systemd/system/swg-csqtt-csqtt0.service": "[Service]\n", "opt/swg-csqtt/csqtt0/csqtt.env": "SWG_LISTEN=0.0.0.0:46000\n",
         "opt/swg-csqtt/csqtt0/passwords.json": '{"passwords": {"alice": "x"}}', "opt/swg-csqtt/.bin/amd64/server": "x"}
here = lambda box, p: os.path.lexists(os.path.join(box, p))

print("\n[18] a bare node's WDTT and csqtt servers, FULL, the documented `y` (1.8.9 qualification D12-3)")
box = mkbox("forks-y", dict(BARE_NODE, **FORKS), BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[18] the run stays inside its box", not esc, esc)
check("[18] WDTT_DATA_DEL=y / CSQTT_DATA_DEL=y: /opt/swg-wdtt and /opt/swg-csqtt go — not left behind, empty",
      not here(box, "opt/swg-wdtt") and not here(box, "opt/swg-csqtt"), [p for p in ("opt/swg-wdtt", "opt/swg-csqtt") if here(box, p)])
box = mkbox("forks-keep", dict(BARE_NODE, **FORKS), BARE_FX)
rc, out, calls, esc = run(box, "--yes", env=dict(FULL, WDTT_DATA_DEL="n"))
check("[18] WDTT_DATA_DEL=n: the identity stays, its dir with it; the shared binaries go",
      here(box, "opt/swg-wdtt/wdtt0/wg-keys.dat") and not here(box, "opt/swg-wdtt/.bin") and not here(box, "opt/swg-csqtt"),
      sorted(os.listdir(os.path.join(box, "opt"))))

print("\n[19] a bare → Docker converted node, FULL: the WDTT / csqtt state its bare past left (1.8.9 qualification L8-a)")
CONV_FORK = dict(NODE_FILES, **{"etc/systemd/system/swg-wdtt-wdtt0.service": FORKS["etc/systemd/system/swg-wdtt-wdtt0.service"],
                                "opt/swg-wdtt/wdtt0/wg-keys.dat": "K", "opt/swg-wdtt/.bin/amurcanov/server": "x",
                                "opt/swg-csqtt/csqtt0/passwords.json": '{"passwords": {"alice": "x"}}',
                                "opt/swg-csqtt/csqtt0/csqtt.env": "SWG_LISTEN=0.0.0.0:46000\n", "opt/swg-csqtt/.bin/amd64/server": "x"})
box = mkbox("conv-forks", CONV_FORK, dict(NODE_FX, **{"docker.ps": "swg-node\n"}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[19] the run stays inside its box", not esc, esc)
check("[19] the csqtt password store no unit names (the convert deleted the bare csqtt units) is asked about, by its path",
      "/opt/swg-csqtt/csqtt0" in "\n".join(l for l in out.splitlines() if "Delete" in l), out[-1500:])
check("[19] …and with CSQTT_DATA_DEL=y nothing of /opt/swg-csqtt or /opt/swg-wdtt is left",
      not here(box, "opt/swg-csqtt") and not here(box, "opt/swg-wdtt"), [p for p in ("opt/swg-wdtt", "opt/swg-csqtt") if here(box, p)])
check("[19] …and no server is torn down for it: no `ip link delete csqtt0`, no rule of csqtt0's touched (a name the Docker node may use)",
      "link delete dev csqtt0" not in calls and "swg-egress:csqtt0" not in calls, calls[-800:])
box = mkbox("conv-forks-keep", CONV_FORK, dict(NODE_FX, **{"docker.ps": "swg-node\n"}))
rc, out, calls, esc = run(box, "--yes", env=dict(FULL, CSQTT_DATA_DEL="n"))
check("[19] CSQTT_DATA_DEL=n: the store is kept, with what it needs", here(box, "opt/swg-csqtt/csqtt0/passwords.json"), out[-800:])

print("\n[20] the sweep: the torrent policy's rule at 6880, the turn listeners' sysctl file (1.8.9 qualification NR-6, DEB-2)")
RULES = ("0:\tfrom all lookup local\n6880:\tfrom all fwmark 0x40000000 lookup main\n6890:\tfrom all fwmark 0x1aea lookup 7000\n"
         "7000:\tfrom 10.60.1.0/24 lookup 7000\n32766:\tfrom all lookup main\n32767:\tfrom all lookup default\n")
box = mkbox("sweep-6880", dict(BARE_NODE, **{"etc/sysctl.d/99-swg-turn.conf": "net.core.rmem_max = 25165824\nnet.core.wmem_max = 25165824\n"}),
            dict(BARE_FX, **{"ip.rules": RULES}))
rc, out, calls, esc = run(box, "--yes", env=FULL)
check("[20] the run stays inside its box", not esc, esc)
check("[20] `6880: from all fwmark 0x40000000 lookup main` (the P2P policy under Direct) goes with the rest — rules only: main is never flushed",
      not [r for r in fx(box, "ip.rules") if r.startswith("6880:")] and "ip\troute flush table main" not in calls
      and "ip\troute flush table 6880" not in calls, (fx(box, "ip.rules"), [l for l in calls.splitlines() if l.startswith("ip\t")]))
check("[20] /etc/sysctl.d/99-swg-turn.conf (the turn listeners' socket-buffer caps swg-noded wrote) goes with the other two",
      not here(box, "etc/sysctl.d/99-swg-turn.conf"), sorted(os.listdir(os.path.join(box, "etc/sysctl.d"))))

print("\n[21] turn proxies listed by the host their clients dial (1.8.9 qualification FN-2(a))")
TURN_UNIT = ("[Unit]\nDescription=vk-turn-proxy (WINGS-N)\n[Service]\nEnvironmentFile=-@BOX@/opt/vk-turn-proxy/%s/turn.env\n"
             "ExecStart=@BOX@/opt/vk-turn-proxy/.bin/WINGS-N/turn -listen ${SWG_LISTEN} -connect ${SWG_CONNECT}\n")
tfiles = dict(BARE_NODE, **{
    "etc/systemd/system/vk-turn-proxy-WINGS-N-56200.service": TURN_UNIT % "WINGS-N-56200",
    "opt/vk-turn-proxy/WINGS-N-56200/turn.env": "SWG_LISTEN=0.0.0.0:56200\nSWG_DIAL=home.example.net:56200\nSWG_CONNECT=127.0.0.1:51820\n",
    "etc/systemd/system/vk-turn-proxy-WINGS-N-56300.service": TURN_UNIT % "WINGS-N-56300",
    "opt/vk-turn-proxy/WINGS-N-56300/turn.env": "SWG_LISTEN=203.0.113.7:56300\nSWG_CONNECT=127.0.0.1:51820\n"})
box = mkbox("turn-dial", tfiles, BARE_FX)
rc, out, calls, esc = run(box, "--dry-run", "--yes", env=FULL)
comps = components(out)
t1 = next((c for c in comps if "vk-turn-proxy-WINGS-N-56200" in c), "")
t2 = next((c for c in comps if "vk-turn-proxy-WINGS-N-56300" in c), "")
check("[21] a proxy behind NAT / DDNS is listed by the host its clients dial (SWG_DIAL), not its bind 0.0.0.0",
      "home.example.net:56200 → 127.0.0.1:51820" in t1 and "0.0.0.0" not in t1, comps)
check("[21] …one with no SWG_DIAL (dial == bind) by its listen, as before", "203.0.113.7:56300 → 127.0.0.1:51820" in t2, comps)

shutil.rmtree(T, ignore_errors=True)
print("")
if PERTURBED:
    sect = {"--perturb-gone": ("the node is offered", "…and not as mere", "NOTHING of the node", "its nft tables went",
                               "the Docker dir is gone", "nothing of the node", "nothing was pulled", "the panel went too"),
            "--perturb-image": ("its nft tables went with its OWN nft",), "--perturb-bare": ("[6]",),
            "--perturb-src": ("[7] the source build is offered", "[7] …and taken", "[7] DKMS forgets", "[8]", "[12]"),
            "--perturb-stop": ("[7] each removed interface's unit",), "--perturb-ppa": ("[10]",), "--perturb-go": ("[9] …and the purge",),
            "--perturb-key": ("[11] the PPA goes", "[12]"), "--perturb-srcppa": ("[12]",), "--perturb-www": ("[13] /var/www",),
            "--perturb-aa": ("[13] the AppArmor local/wg",), "--perturb-aatext": ("[13] …and the revert line",),
            "--perturb-rl": ("[13] route_localnet", "[15]"), "--perturb-rlown": ("[14] route_localnet",), "--perturb-keepmsg": ("[16]",),
            "--perturb-engine": ("[17] the summary of [1]'s",), "--perturb-d123": ("[18] WDTT_DATA_DEL", "[19] …and with CSQTT_DATA_DEL=y"),
            "--perturb-orphan": ("[19] the csqtt password store", "[19] …and with CSQTT_DATA_DEL=y"),
            "--perturb-6880": ("[20] `6880",), "--perturb-turnconf": ("[20] /etc/sysctl.d/99-swg-turn.conf",),
            "--perturb-dial": ("[21] a proxy behind NAT",)}
    want = tuple(p for f, on in FLAGS.items() if on for p in sect[f])
    red = [f for f in FAILS if f.startswith(want)]
    okk = bool(red) and len(red) == len(FAILS)
    print("perturb: %s" % ("RED as it must be (%d), all in the targeted sections" % len(red) if okk
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % [f for f in FAILS if f not in red]))
    sys.exit(0 if okk else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
