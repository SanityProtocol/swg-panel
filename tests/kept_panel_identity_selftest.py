#!/usr/bin/env python3
"""Self-test — a bare-metal panel uninstalled with "keep the data" comes back as ITSELF.

The keep-data answer kept /var/lib/swg-panel (users, peers, nodes) and deleted /etc/swg-panel: the login, the TLS
certificate and key, install.conf. The re-install then minted a new certificate, and every node pinned to the old one
stopped syncing ("tls fingerprint mismatch") until its own installer was re-run; an Enter-through re-install also moved
the panel to the default-route address, minted a new login name and renamed its node (q1m → q1) — while the kept store
still held the old address and the node's name, which nothing read (1.8.8 qualification, round 4). The Docker path always
kept its login and certificate (data/etc).

  THE UNINSTALL (uninstall.sh rm_panel, lifted as shipped and run for real on a remapped root; systemd/users stubbed)
    [1] keep: /etc/swg-panel's login, certificate + key and install.conf stay (its Cloudflare tokens emptied, the ufw
        record gone with its rules), /etc/swg-sub stays, the roster stays (minus stored configs and .ssh); the programs
        go; the line names what was kept
    [2] delete: all of it goes, as before
  THE RE-INSTALL (install-host.sh's existing-install block, lifted as shipped)
    [3] onto kept data (login, no panel unit): a re-install — the login is kept, every saved answer is the default, and
        it says it is re-installing this panel as it was, not "Existing panel install detected"
    [4] onto a store an OLDER uninstall kept (no /etc/swg-panel): the address, TLS mode and the node's name and
        endpoint come from the store (this box's node is the one keyed by its machine-id), and it says that the
        login and certificate were not kept
    [5] the lifecycle word: after an uninstall there are no programs to compare, so the panel's last version decides
        "reinstalled" (same) or "reinstalled-updated" (different)
    [6] a kept install.conf, rewritten by the re-install, gets back the group a fresh one has (the uninstall gave it root's)

Run: python3 tests/kept_panel_identity_selftest.py        (0 = pass)
     --perturb   the shipped uninstall (always deletes /etc/swg-panel) and a re-install that reads no kept store → RED
"""
import hashlib, json, os, re, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
U = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
H = open(os.path.join(ROOT, "install-host.sh"), encoding="utf-8").read()
VERSION = open(os.path.join(ROOT, "VERSION")).read().strip()

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def plant(src, a, b):
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS: " + a[:90]
    return src.replace(a, b)

if PERTURB:
    U = plant(U, '  if [ "$PANEL_DATA_DEL" = yes ]; then rmrf /var/lib/swg-panel /etc/swg-panel /etc/swg-sub   # /etc/swg-sub = swg-sub\'s OWN tls dir\n  else\n',
              '  rmrf /etc/swg-panel /etc/swg-sub\n  if [ "$PANEL_DATA_DEL" = yes ]; then rmrf /var/lib/swg-panel\n  else\n')
    H = plant(H, 'elif [ -f "$STATE_DIR/panel-settings.json" ] || [ -f "$STATE_DIR/nodes.json" ]; then\n',
              'elif false; then\n')
    H = plant(H, 'run chown root:swg "$ETC_DIR/install.conf" 2>/dev/null || true   # a KEPT one comes back root:root (uninstall) — the group a fresh one gets\n', "")

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

def stubdir(names):
    d = tempfile.mkdtemp(prefix="kpi-stub-")
    for n, body in names.items():
        p = os.path.join(d, n); open(p, "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(p, 0o755)
    return d

# ── [1]–[2] the uninstall ─────────────────────────────────────────────────────────────────────────────────────────
MAPPED = ("/etc/swg-panel", "/etc/swg-sub", "/var/lib/swg-panel", "/var/lib/swg-noded", "/var/lib/swg-netctl",
          "/opt/swg-panel", "/opt/swg-sub", "/var/www/wgstats", "/var/www/acme", "/usr/local/bin/swg-passwd",
          "/usr/local/bin/swg-netctl", "/etc/nginx")
def uninstall(delete):
    R = tempfile.mkdtemp(prefix="kpi-root-")
    def put(path, text=""):
        p = R + path; os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text); return p
    put("/etc/swg-panel/auth", "admin41:pbkdf2_sha256$200000$c2FsdA==$aGFzaA==\n")
    put("/etc/swg-panel/tls/fullchain.pem", "CERT\n"); put("/etc/swg-panel/tls/key.pem", "KEY\n")
    put("/etc/swg-panel/install.conf", "ROLE_SEL=master\nPANEL_DOMAIN=192.168.77.1\nPORT=2087\nCF_TOKEN=secret-token\n"
        "CF_ORIGIN_TOKEN=secret-origin\nHOST_NODE_NAME=q1m\nHOST_ENDPOINT_IP=192.168.77.1\n")
    put("/etc/swg-panel/fleet.json", "{}\n"); put("/etc/swg-panel/ufw-added", "2087/tcp\n")
    put("/etc/swg-sub/tls/fullchain.pem", "SUBCERT\n")
    put("/var/lib/swg-panel/users.json", "{}\n"); put("/var/lib/swg-panel/configs/a.conf", "PrivateKey = x\n")
    put("/var/lib/swg-panel/.ssh/id", "k\n"); put("/opt/swg-panel/swg-panel-server", "x\n"); put("/opt/swg-sub/swg-sub", "x\n")
    body = fn(U, "rm_panel")
    for m in MAPPED:
        body = body.replace(m, R + m)
    st = stubdir({"systemctl": "exit 0", "nginx": "exit 1", "userdel": "exit 0", "id": "exit 1"})
    script = ('set -uo pipefail\nDRYRUN=false; SD=%s/sd; DOMAIN=""; PANEL_DATA_DEL=%s; REMOVED_PANEL=false\n'
              'info(){ echo "INFO $*"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ echo "SUB $*"; }; b(){ printf %%s "$*"; }\n'
              'run(){ "$@"; }\nrmrf(){ local p; for p in "$@"; do rm -rf "$p"; done; }\nask_yn(){ :; }\n'
              'ufw_forget(){ echo "UFWFORGET $*"; }\nrm_updater_if_last(){ :; }\ndocker_running(){ return 1; }\n%srm_panel\n') % (
        R, "yes" if delete else "no", body)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=dict(os.environ, PATH=st + ":" + os.environ["PATH"]))
    return R, (r.stdout + r.stderr).replace(R, "")

print("[1] keep the data: the panel's identity stays")
R, out = uninstall(delete=False)
ex = lambda p: os.path.exists(R + p)
check("[1] the login, the certificate and key, and install.conf stay",
      all(ex(p) for p in ("/etc/swg-panel/auth", "/etc/swg-panel/tls/fullchain.pem", "/etc/swg-panel/tls/key.pem",
                          "/etc/swg-panel/install.conf")), out)
conf = open(R + "/etc/swg-panel/install.conf").read() if ex("/etc/swg-panel/install.conf") else ""
check("[1] …install.conf keeps the address and the node's name, and loses the Cloudflare tokens (secrets at rest)",
      "PANEL_DOMAIN=192.168.77.1" in conf and "HOST_NODE_NAME=q1m" in conf and "secret" not in conf
      and "CF_TOKEN=\n" in conf and "CF_ORIGIN_TOKEN=\n" in conf, conf)
check("[1] …the ufw record goes with the rules it named (closed above: the ports close with the panel)",
      not ex("/etc/swg-panel/ufw-added") and "UFWFORGET /etc/swg-panel/ufw-added" in out, out)
check("[1] the subscription page's certificate stays", ex("/etc/swg-sub/tls/fullchain.pem"), out)
check("[1] the roster stays; stored client configs and .ssh do not",
      ex("/var/lib/swg-panel/users.json") and not ex("/var/lib/swg-panel/configs") and not ex("/var/lib/swg-panel/.ssh"), out)
check("[1] the programs go", not ex("/opt/swg-panel") and not ex("/opt/swg-sub"), out)
check("[1] the line names the login, certificate and address as kept",
      "OK Kept /var/lib/swg-panel (users, peers, nodes) and /etc/swg-panel (its login, certificate and address)" in out, out)

print("\n[2] delete the data: everything goes")
R, out = uninstall(delete=True)
check("[2] /etc/swg-panel, /etc/swg-sub and /var/lib/swg-panel are gone",
      not any(os.path.exists(R + p) for p in ("/etc/swg-panel", "/etc/swg-sub", "/var/lib/swg-panel")), out)

# ── [3]–[4] the re-install ────────────────────────────────────────────────────────────────────────────────────────
a = H.index('EXISTING_HOST=no; KEEP_AUTH=no\n')
b = H.index("\nfi\n", H.index('if [ -f "$ETC_DIR/auth" ] || [ -f "$_unit" ]; then', a)) + 4
HBLOCK = H[a:b]
def reinstall(etc_files, store):
    t = tempfile.mkdtemp(prefix="kpi-re-"); etc = os.path.join(t, "etc"); st = os.path.join(t, "state")
    os.makedirs(etc); os.makedirs(st)
    for n, text in etc_files.items():
        open(os.path.join(etc, n), "w").write(text)
    for n, obj in store.items():
        json.dump(obj, open(os.path.join(st, n), "w"))
    script = ('set -euo pipefail\nBOLD=""; RESET=""\ninfo(){ echo "INFO $*"; }; b(){ printf %%s "$*"; }\nhave(){ command -v "$1" >/dev/null; }\n'
              'ETC_DIR=%s; STATE_DIR=%s; BASIC_USER=admin; SUB_DOMAIN=""; SWG_CONVERT_DIR=""\n%s\n'
              'for v in EXISTING_HOST KEEP_AUTH BASIC_USER DOM_SAVED PORT_SAVED BASE_SAVED TLS_SAVED ROLE_SAVED NODENAME_SAVED ENDPOINT_SAVED; do '
              'echo "$v=${!v}"; done\n') % (etc, st, HBLOCK.replace("/etc/systemd/system/swg-panel-server.service", t + "/no-unit"))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.stdout + r.stderr

print("\n[3] a re-install onto the data the uninstall kept")
out = reinstall({"auth": "admin41:hash\n", "install.conf": "ROLE_SEL=master\nPANEL_DOMAIN=192.168.77.1\nPORT=2087\n"
                 "TLS_MODE=selfsigned\nHOST_NODE_NAME=q1m\nHOST_ENDPOINT_IP=192.168.77.1\n"}, {})
check("[3] it is a re-install that keeps the login", "EXISTING_HOST=yes" in out and "KEEP_AUTH=yes" in out and "BASIC_USER=admin41" in out, out)
check("[3] …with the kept address, TLS mode, node name and endpoint as the defaults",
      all(k in out for k in ("DOM_SAVED=192.168.77.1", "PORT_SAVED=2087", "TLS_SAVED=selfsigned", "NODENAME_SAVED=q1m",
                              "ENDPOINT_SAVED=192.168.77.1", "ROLE_SAVED=master")), out)
check("[3] …and says it re-installs this panel as it was", "INFO Found this panel's kept data" in out
      and "Existing panel install detected" not in out, out)

print("\n[4] a re-install onto a store an older uninstall kept")
mid = ""
for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
    try:
        mid = open(p).read().strip()
    except Exception:
        mid = ""
    if mid:
        break
nid = hashlib.sha256(((mid or socket.gethostname()) + "|swg-local-node").encode()).hexdigest()[:12]
store = {"panel-settings.json": {"access": {"panel": {"url": "https://192.168.77.1:2087/swg"}, "tls": {"mode": "selfsigned"}}},
         "nodes.json": {nid: {"id": nid, "name": "q1m", "endpoint_host": "192.168.77.1"},
                        "other": {"id": "other", "name": "q2n", "endpoint_host": "192.168.77.2"}}}
out = reinstall({}, store)
check("[4] the address comes from the store (host, port, subpath) with its TLS mode",
      all(k in out for k in ("DOM_SAVED=192.168.77.1", "PORT_SAVED=2087", "BASE_SAVED=/swg", "TLS_SAVED=selfsigned")), out)
check("[4] …the node's name and endpoint are THIS box's node (its machine-id), not another node's",
      "NODENAME_SAVED=q1m" in out and "ENDPOINT_SAVED=192.168.77.1" in out and "ROLE_SAVED=master" in out, out)
check("[4] …it is not a re-install of the login (there is none), and it says the login and certificate were not kept",
      "EXISTING_HOST=no" in out and "Its login and certificate were not kept" in out, out)
out = reinstall({}, {})
check("[4] a box with no kept store: nothing is invented", "DOM_SAVED=\n" in out and "NODENAME_SAVED=\n" in out
      and "INFO" not in out, out)

print("\n[5] after an uninstall, the panel's last version names the re-install")
a = H.index('if [ "${LC_SUCCESS:-}" = reinstalled-updated ] && [ -n "${_SUM_BEFORE:-}" ] \\\n')
b = H.index("\nfi\n", a) + 4
LCB = H[a:b]
def lc(ver_before):
    t = tempfile.mkdtemp(prefix="kpi-lc-"); open(os.path.join(t, "VERSION"), "w").write(VERSION + "\n")
    script = ('LC_SUCCESS=reinstalled-updated; _SUM_BEFORE=""; _VER_BEFORE="%s"; SRC=%s\ninstalled_sum(){ :; }\n'
              'PANEL_DIR=x; SUB_DIR=x; NODED_DIR=x; AGENT_DIR=x\n%s\necho "LC=$LC_SUCCESS"\n') % (ver_before, t, LCB)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
check("[5] the same version → reinstalled", "LC=reinstalled\n" in lc(VERSION), lc(VERSION))
check("[5] a different one → reinstalled-updated", "LC=reinstalled-updated" in lc("1.8.7-beta"), lc("1.8.7-beta"))
check("[5] nothing known → reinstalled-updated, as before", "LC=reinstalled-updated" in lc(""), lc(""))

print("\n[6] install.conf gets its group back when the re-install rewrites a kept one")
a = H.index('writef "$ETC_DIR/install.conf" 600 <<EOF\n'); b = H.index("\n# Seed the panel's OWN Access & TLS settings", a) + 1
WR = H[a:b]
t = tempfile.mkdtemp(prefix="kpi-wr-")
r = subprocess.run(["bash", "-c", 'ETC_DIR=%s\nwritef(){ cat > "$ETC_DIR/install.conf"; }\nrun(){ echo "RUN $*"; }\n%s' % (t, WR)],
                   capture_output=True, text=True, env=dict(os.environ, ROLE_SEL="master"))
check("[6] the writer is followed by chown root:swg (a kept file keeps the root:root the uninstall gave it)",
      ("RUN chown root:swg %s/install.conf" % t) in r.stdout, r.stdout + r.stderr)

print()
if PERTURB:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
