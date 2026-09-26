#!/usr/bin/env python3
"""Self-test — a Docker → bare-metal convert carries what the box IS: a master stays a master, and an interface the
Docker node adopted from this host is the same interface, not a name clash.

  · a MASTER's convert installs the panel with install-host.sh as ROLE=host (the node follows in install-node.sh), and
    install-host.sh wrote its install.conf back over the master line convert.sh had staged: ROLE_SEL=host with an empty
    HOST_NODE_NAME / HOST_ENDPOINT_IP — so the next re-install or update read a panel-only box (1.8.8 qualification,
    round 4). The convert now hands install-host the node's name (the panel's record for this node's token) and its
    endpoint, and puts the role back.
  · a Docker node that ADOPTED one of this host's interfaces rebuilt its conf inside the container; the host's own
    original was still on disk with the SAME private key, read as a clash, and the convert was refused with only a
    manual remedy (since 1.6.0). Same key = same interface: carried like the rest, its original kept beside it.

  [1] master: install.conf after the panel phase says master, with the node's name and endpoint
  [2] panel-only (host): unchanged — host, no node name
  [3] a same-key original is not a clash; a different-key conf of that name still is
  [4] the import carries the Docker copy (its peers, its #swg: marks) and keeps the original as <conf>.pre-convert
  [5] a resumed convert that already imported it is left alone (no .pre-convert of our own import)

convert.sh's blocks are lifted as shipped; install-host.sh is a stub that writes install.conf's role lines exactly as
the real writer does (ROLE_SEL from ROLE, HOST_NODE_NAME / HOST_ENDPOINT_IP from the environment); paths remapped.

Run: python3 tests/convert_carries_identity_selftest.py     (0 = pass)
     --plant <role|name|clash|carry>   plant one old behaviour → RED (exit 0 when caught);  --perturb plants all four
"""
import base64, hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
V = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
ALL = ("role", "name", "clash", "carry")
PLANTS = set(ALL) if "--perturb" in sys.argv else ({sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if "role" in PLANTS:
    V = plant(V, '  [ "$ROLE" = master ] && sed -i \'s/^ROLE_SEL=.*/ROLE_SEL=master/\' "$ETC/install.conf" 2>/dev/null   # the role, not install-host\'s ROLE=host\n', "")
if "name" in PLANTS:
    V = plant(V, '      ${_MNAME:+HOST_NODE_NAME="$_MNAME"} ${NEP:+HOST_ENDPOINT_IP="$NEP"} \\\n', "")
if "clash" in PLANTS:
    V = plant(V, '        same_iface_conf "$_bc" "$confd/$nm.conf" && continue\n', "")
if "carry" in PLANTS:
    a = V.index("    # the host's own original of an interface this node adopted (same key)"); b = V.index("    if [ -f \"$dest\" ]; then sub \"kept", a)
    V = V[:a] + V[b:]

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

# the real writer's role lines, to hold the stub to them
_w = H[H.index('writef "$ETC_DIR/install.conf" 600 <<EOF'):]
assert "ROLE_SEL=${ROLE_SEL}" in _w and "HOST_NODE_NAME=${HOST_NODE_NAME:-}" in _w and "HOST_ENDPOINT_IP=${HOST_ENDPOINT_IP:-}" in _w, \
    "install-host.sh's install.conf writer changed — update the stub"

PRE = ('set -uo pipefail\nDRYRUN=false; BOLD=""; RESET=""\ninfo(){ echo "INFO $*"; }; sub(){ echo "SUB $*"; }; warn(){ echo "WARN $*"; }\n'
       'die(){ echo "DIE $*"; exit 1; }; b(){ printf %s "$*"; }\n')

def token_hash(tok):
    salt = b"0123456789abcdef"
    return "pbkdf2_sha256$1000$%s$%s" % (base64.b64encode(salt).decode(),
                                         base64.b64encode(hashlib.pbkdf2_hmac("sha256", tok.encode(), salt, 1000)).decode())

print("[1]–[2] install.conf after a master's convert")
a = V.index('  _LNENV=""; [ "$ROLE" = master ] && _LNENV=')
b = V.index("\n", V.index("  [ \"$ROLE\" = master ] && sed -i", a)) + 1 if "role" not in PLANTS else \
    V.index("\n", V.index("re-run the bare-metal host install to finish", a)) + 1
BLOCK = V[a:b]
def master_convert(role):
    t = tempfile.mkdtemp(prefix="cci-")
    etc, state, src = (os.path.join(t, d) for d in ("etc", "state", "src"))
    for d in (etc, state, src):
        os.makedirs(d)
    json.dump({"n1": {"id": "n1", "name": "q3m", "token_hash": token_hash("node-token-3")},
               "n2": {"id": "n2", "name": "q4n", "token_hash": token_hash("node-token-4")}}, open(os.path.join(state, "nodes.json"), "w"))
    open(os.path.join(src, "install-host.sh"), "w").write(
        '#!/bin/bash\ncase "$ROLE" in master|host+node) ROLE_SEL=master;; host) ROLE_SEL=host;; esac\n'
        'printf "ROLE_SEL=%s\\nHOST_NODE_NAME=%s\\nHOST_ENDPOINT_IP=%s\\n" "$ROLE_SEL" "${HOST_NODE_NAME:-}" "${HOST_ENDPOINT_IP:-}" > "$STUB_ETC/install.conf"\n')
    tail = ('export STUB_ETC={e}\nETC={e}; STATE={s}; SRC={r}; ROLE={o}; NTOK=node-token-3; NEP=192.168.77.3\n'
            'PDOM=192.168.77.3; PPORT=2087; PBASE=""; PEMAIL=""; PSUBPORT=8444; PLOCALPORT=8088; PCFT=""; PCFO=""; PUSER=admin613\n'
            ).format(e=etc, s=state, r=src, o=role)
    script = PRE + fn(C, "panel_node_name_tok") + tail + BLOCK + 'cat "$ETC/install.conf"\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout + r.stderr
out = master_convert("master")
check("[1] a master's convert: ROLE_SEL=master", "ROLE_SEL=master\n" in out, out)
check("[1] …with the node's name (the panel's record for its token) and its endpoint",
      "HOST_NODE_NAME=q3m\n" in out and "HOST_ENDPOINT_IP=192.168.77.3\n" in out, out)
out = master_convert("host")
check("[2] a panel-only convert: host, no node name — as before", "ROLE_SEL=host\n" in out and "HOST_NODE_NAME=\n" in out, out)

print("\n[3]–[5] an interface the Docker node adopted from this host")
PF_A = V.index("  conflicts=\"\"\n  if [ \"$RESUMING\" != yes ]; then\n"); PF_B = V.index("\n  fi\n", PF_A) + 5
PREFLIGHT = V[PF_A:PF_B]
IM_A = V.index("  names=\"\"\n  for s in $specs; do nm=\"${s%:*}\"; pr=\"${s#*:}\"\n"); IM_B = V.index("\n  done\n", IM_A) + 8
IMPORT = V[IM_A:IM_B]
HOOKS = "".join(fn(C, n) for n in ("_ipt_reap_sh", "_ipt_set_sh", "nat_hook_up", "nat_hook_down"))
FUNCS = HOOKS + "detect_wan(){ echo ens3; }\n" + "".join(fn(V, n) for n in ("conf_privkey", "same_iface_conf", "import_bare_conf"))
DOCKER_COPY = ("#swg:onboarded\n#swg:cmd wg\n[Interface]\nPrivateKey = SAMEKEY=\nAddress = 10.65.0.1/24\nListenPort = 51825\n\n"
               "[Peer]\nPublicKey = OWN=\nAllowedIPs = 10.65.0.2/32\n\n[Peer]\nPublicKey = ADDEDBYPANEL=\nAllowedIPs = 10.65.0.3/32\n")
ORIGINAL = ("[Interface]\nPrivateKey = SAMEKEY=\nAddress = 10.65.0.1/24\nListenPort = 51825\nPostUp = operator-own\n\n"
            "[Peer]\nPublicKey = OWN=\nAllowedIPs = 10.65.0.2/32\n")
def convert_node(host_conf, resuming="no", pre_imported=False):
    t = tempfile.mkdtemp(prefix="cci-n-")
    awg, wg, confd = (os.path.join(t, d) for d in ("awg", "wg", "confd"))
    for d in (awg, wg, confd):
        os.makedirs(d)
    open(os.path.join(confd, "wg5.conf"), "w").write(DOCKER_COPY)
    if host_conf is not None:
        open(os.path.join(wg, "wg5.conf"), "w").write(host_conf)
    code = (PREFLIGHT + '\necho "CONFLICTS=[$conflicts]"\n' + IMPORT).replace("/etc/amnezia/amneziawg", awg).replace("/etc/wireguard", wg)
    if pre_imported:   # a resumed run: our own import already there
        subprocess.run(["bash", "-c", FUNCS + 'import_bare_conf "%s" "%s"' % (os.path.join(confd, "wg5.conf"), os.path.join(wg, "wg5.conf"))])
    script = PRE + FUNCS + 'confd=%s; specs="wg5:wg"; RESUMING=%s\n%s\necho "NAMES=[$names]"\n' % (confd, resuming, code)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return t, r.stdout + r.stderr
t, out = convert_node(ORIGINAL)
check("[3] the same-key original is not a clash", "CONFLICTS=[]" in out, out)
t2, out2 = convert_node(ORIGINAL.replace("SAMEKEY=", "OTHERKEY="))
check("[3] …a conf of that name with a DIFFERENT key still is", "CONFLICTS=[wg5]" in out2, out2)
imp = open(os.path.join(t, "wg", "wg5.conf")).read() if os.path.exists(os.path.join(t, "wg", "wg5.conf")) else ""
check("[4] the Docker copy is imported — its peers (the one the panel added too) and its #swg: marks",
      "ADDEDBYPANEL=" in imp and imp.startswith("#swg:onboarded\n") and "NAMES=[wg5]" in out, (imp, out))
pre = os.path.join(t, "wg", "wg5.conf.pre-convert")
check("[4] …and the host's original is kept beside it, as it was", os.path.exists(pre) and open(pre).read() == ORIGINAL, out)
t3, out3 = convert_node(None, resuming="yes", pre_imported=True)
check("[5] a resumed convert that already imported it: left alone, no .pre-convert of our own import",
      not os.path.exists(os.path.join(t3, "wg", "wg5.conf.pre-convert")) and "already imported" in out3, out3)

print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)), "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
