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

Run: python3 tests/uninstall_full_selftest.py        (0 = pass)
     SWG_UNINSTALL=<file>   run it against another uninstall.sh
     --perturb-gone    the gone node is not offered (as shipped) → RED on [1] [2] [3]
     --perturb-bare    …it is, beside a bare node too → RED on [6] only
     --perturb-image   its image is not read from the .env → RED on [1]'s own-nft check only
"""
import json, os, re, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
U = open(os.environ.get("SWG_UNINSTALL") or os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
FLAGS = {f: f in sys.argv[1:] for f in ("--perturb-gone", "--perturb-image", "--perturb-bare")}
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
if FLAGS["--perturb-image"]:
    plant('  [ -n "$img" ] || { _tag="$(sed -n ', '  false && { _tag="$(sed -n ')

T = tempfile.mkdtemp(prefix="unin-full-")

# ── the box: every absolute path the uninstaller names moves under it ──────────────────────────────────────────────────
_ROOTS = ("/opt/", "/etc/", "/var/", "/srv/", "/root/", "/run/", "/usr/local/bin/", "/usr/src/", "/usr/bin/awg",
          "/usr/share/man/", "/lib/systemd/", "/usr/lib/systemd/", "/lib/modules/")
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
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)
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

shutil.rmtree(T, ignore_errors=True)
print("")
if PERTURBED:
    sect = {"--perturb-gone": ("the node is offered", "…and not as mere", "NOTHING of the node", "its nft tables went",
                               "the Docker dir is gone", "nothing of the node", "nothing was pulled", "the panel went too"),
            "--perturb-image": ("its nft tables went with its OWN nft",), "--perturb-bare": ("[6]",)}
    want = tuple(p for f, on in FLAGS.items() if on for p in sect[f])
    red = [f for f in FAILS if f.startswith(want)]
    okk = bool(red) and len(red) == len(FAILS)
    print("perturb: %s" % ("RED as it must be (%d), all in the targeted sections" % len(red) if okk
                           else "NOT CAUGHT" if not FAILS else "ALSO red elsewhere: %s" % [f for f in FAILS if f not in red]))
    sys.exit(0 if okk else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
