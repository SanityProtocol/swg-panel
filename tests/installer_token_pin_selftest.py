#!/usr/bin/env python3
"""Self-test — a node re-install decides whom it trusts BEFORE its token goes anywhere, and a kept pin changes nothing.

1.8.8 qualification, round 6 (q2 bare, q4 Docker): a re-install against a panel presenting a CHANGED certificate
correctly "kept the old pin" — but it had already posted "reinstalling" with the node token, at the very start, with
curl -k, to whatever answered (the interceptor its own warning named), deleted the node's interface-key backups, and at
exit posted its terminal status the same way. On the real panel that post dropped the node's interface keys and the far
end's mesh peer until a re-pin. Now (install-node.sh, install-docker.sh):

  BARE — install-node.sh run for real (a copy whose absolute paths point into a temp dir, stopped at its datapath step)
    [1] CHANGED certificate, no terminal → exit 1 and the stop line; the listener received NOTHING; the key backups and
        the agent config untouched; no lifecycle armed
    [2] …at a terminal, Enter → the same (and the question was on the terminal)
    [3] …at a terminal, y → proceeds: "reinstalling", whoami and the terminal status reach the panel, pinned to the NEW
        certificate; the key backups dropped only now
    [4] TLS_FINGERPRINT=<new> given → proceeds the same way
    [5] the SAME certificate → proceeds with its pin (the ordinary re-install)
  DOCKER — install-docker.sh node, the same way (its .env's pin, a kept data/node/iface-keys)
    [6] CHANGED, no terminal → exit 1, nothing received, iface-keys kept   [7] y → proceeds, pinned to the new one

Run: python3 tests/installer_token_pin_selftest.py     (0 = pass)
     --perturb-bare-early     the bare lifecycle armed at the start again (before the prompts, the stored trust unread) → RED
     --perturb-docker-early   the Docker node's lifecycle armed at the start again → RED
     --perturb-goon           a kept pin carries on with the run (the round-6 shape) → RED
"""
import hashlib, http.server, json, os, re, shutil, ssl, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PERTURBED = any(a.startswith("--perturb") for a in ARGS)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[-700:]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

T = tempfile.mkdtemp(prefix="tokpin-")
LOG = []
class H(http.server.BaseHTTPRequestHandler):
    def _h(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = self.rfile.read(n).decode() if n else ""
        LOG.append((self.command, self.path, self.headers.get("Authorization") or "", b))
        data = b'{"ok": true, "data": {"name": "nodeA"}}'
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = _h
    def log_message(self, *a):
        pass

CERT, KEY = os.path.join(T, "c.pem"), os.path.join(T, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", KEY, "-out", CERT], check=True, capture_output=True)
NEW = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(CERT).read())).hexdigest()   # what the panel presents now
OLD = "ab" * 32                                                                  # what the node pinned
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(CERT, KEY)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "https://127.0.0.1:%d" % srv.server_address[1]
TOKEN = "node-token-0123456789"

def plant(text, a, b, what):
    assert text.count(a) == 1, "anchor missing (%s) — would FALSE-PASS: %s" % (what, a[:90])
    return text.replace(a, b)

def staged(script, box):
    """A copy of the repo's installer + lib, its absolute paths pointed into `box`, stopped at the datapath step."""
    d = os.path.join(box, "src"); os.makedirs(os.path.join(d, "lib"))
    shutil.copy(os.path.join(ROOT, "lib/common.sh"), os.path.join(d, "lib/common.sh"))
    s = open(os.path.join(ROOT, script), encoding="utf-8").read()
    s = plant(s, '[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root', 'true || $DRYRUN || die "run as root', "root check")
    for p in ("/etc/swg-agent/", "/var/lib/swg-noded/"):
        s = s.replace(p, box + p)
    if script == "install-node.sh":
        s = plant(s, '\nstep "Datapath tooling"\n', '\necho "REACHED the datapath step"; exit 0\nstep "Datapath tooling"\n', "datapath")
        if "--perturb-bare-early" in ARGS:   # the round-6 order: armed before the prompts, with the stored (unverified) trust
            s = plant(s, '\n# Panel connection — normally supplied by the install command\'s -host / -key flags; on a re-install\n',
                      '\nif [ "$EXISTING" = yes ] && ! $DRYRUN && [ -n "$EXIST_URL" ]; then rm -rf %s/var/lib/swg-noded/iface-keys; '
                      'LC_URL="$EXIST_URL"; LC_TOKEN="$EXIST_TOKEN"; LC_VERIFY=no; lc_init reinstall lc_emit_post; fi\n'
                      '# Panel connection — normally supplied by the install command\'s -host / -key flags; on a re-install\n' % box,
                      "bare early")
    else:
        s = plant(s, '    _lc_docker_arm   # the lifecycle signal, now that the node\'s trust is decided (see _lc_docker_arm)\n',
                  '    _lc_docker_arm   # the lifecycle signal, now that the node\'s trust is decided (see _lc_docker_arm)\n'
                  '    echo "REACHED the datapath step"; exit 0\n', "docker stop point")
        if "--perturb-docker-early" in ARGS:
            s = plant(s, '[ "$PROFILE" = node ] || _lc_docker_arm\n', '_lc_docker_arm\n', "docker early")
    if "--perturb-goon" in ARGS:
        c = open(os.path.join(d, "lib/common.sh"), encoding="utf-8").read()
        open(os.path.join(d, "lib/common.sh"), "w", encoding="utf-8").write(plant(c, '  exit 1; }\n# panel_ca_ok', '  return 0; }\n# panel_ca_ok', "goon"))
    open(os.path.join(d, script), "w", encoding="utf-8").write(s)
    stub = os.path.join(box, "stub"); os.makedirs(stub)
    for n in ("docker", "systemctl"):   # nothing of this host's own is asked or touched
        open(os.path.join(stub, n), "w").write("#!/bin/sh\nexit 0\n"); os.chmod(os.path.join(stub, n), 0o755)
    return d

def run(script, args, box, env, answer=None):
    d = staged(script, box)
    e = dict(os.environ, PATH=os.path.join(box, "stub") + ":" + os.environ["PATH"], SWG_REF="dev", **env)
    for k in ("TLS_VERIFY", "TLS_FINGERPRINT", "NODE_TOKEN", "PANEL_URL"):
        if k not in env:
            e.pop(k, None)
    cmd = "bash %s %s" % (os.path.join(d, script), " ".join(args))
    del LOG[:]
    if answer is None:
        r = subprocess.run(["bash", "-c", cmd], cwd=d, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=240, start_new_session=True)
    else:
        r = subprocess.run(["script", "-qec", cmd, "/dev/null"], cwd=d, env=e, input=answer, capture_output=True, text=True,
                           timeout=240, start_new_session=True)
    return r.returncode, r.stdout + r.stderr, list(LOG)

def bare_box(pin):
    box = tempfile.mkdtemp(prefix="bare-", dir=T)
    os.makedirs(os.path.join(box, "etc/swg-agent")); os.makedirs(os.path.join(box, "var/lib/swg-noded/iface-keys"))
    open(os.path.join(box, "var/lib/swg-noded/iface-keys/wg0.json"), "w").write("{}")
    json.dump({"panel": {"url": URL, "token": TOKEN, "verify": False, "fingerprint": pin}, "endpoint_host": "192.168.77.2",
               "interfaces": {}}, open(os.path.join(box, "etc/swg-agent/config.json"), "w"))
    return box

def docker_box(pin):
    box = tempfile.mkdtemp(prefix="dock-", dir=T)
    inst = os.path.join(box, "opt/swg-panel-docker"); os.makedirs(os.path.join(inst, "data/node/iface-keys"))
    open(os.path.join(inst, "data/node/iface-keys/awg0.json"), "w").write("{}")
    open(os.path.join(inst, ".env"), "w").write("PANEL_URL=%s\nNODE_TOKEN=%s\nNODE_ENDPOINT=192.168.77.4\nTLS_VERIFY=no\n"
                                                "TLS_FINGERPRINT=%s\nPANEL_PASSWORD=unused-on-node-only\n" % (URL, TOKEN, pin))
    return box, inst

STOP = "stopped before changing anything"
def tokened(log):
    return [l[:2] + (json.loads(l[3]).get("state") if l[3] else None,) for l in log if TOKEN in l[2]]

def cfg_pin(box):
    return json.load(open(os.path.join(box, "etc/swg-agent/config.json")))["panel"].get("fingerprint")

print("[1]–[5] the bare-metal node's re-install (install-node.sh, as shipped)")
box = bare_box(OLD)
rc, out, log = run("install-node.sh", [], box, {})
check("[1] CHANGED, no terminal → exit 1 with the stop line", rc == 1 and STOP in out and "kept the old pin" in out, out)
check("[1] ⚠️ the listener received NOTHING — no \"reinstalling\", no whoami, no terminal status", log == [], log)
check("[1] …the key backups and the agent config untouched, no lifecycle armed",
      os.path.exists(os.path.join(box, "var/lib/swg-noded/iface-keys/wg0.json")) and cfg_pin(box) == OLD
      and "REACHED" not in out and "telling the panel" not in out, out)
box = bare_box(OLD)
rc, out, log = run("install-node.sh", [], box, {}, answer="\n\n")     # URL: Enter · trust: Enter
check("[2] …at a terminal, Enter → the same: stopped, nothing received, backups kept",
      rc == 1 and STOP in out and log == [] and os.path.exists(os.path.join(box, "var/lib/swg-noded/iface-keys/wg0.json")), (rc, log, out))
check("[2] …and the question was ON the terminal", "Trust the new certificate? (y/N)" in out, out)
box = bare_box(OLD)
rc, out, log = run("install-node.sh", [], box, {}, answer="\ny\n\n")   # URL: Enter · trust: y · name: Enter
check("[3] at a terminal, y → the run proceeds", rc == 0 and "REACHED the datapath step" in out, (rc, out))
check("[3] …\"reinstalling\", whoami and the terminal status reach the panel (pinned to the NEW certificate)",
      tokened(log) == [("POST", "/api/node/proc-status", "reinstalling"), ("GET", "/api/node/whoami", None),
                       ("POST", "/api/node/proc-status", "reinstalled-updated")], log)
check("[3] …and only now are the key backups dropped (swg-noded re-harvests them)",
      not os.path.exists(os.path.join(box, "var/lib/swg-noded/iface-keys")), os.listdir(os.path.join(box, "var/lib/swg-noded")))
box = bare_box(OLD)
rc, out, log = run("install-node.sh", [], box, {"TLS_FINGERPRINT": NEW})
check("[4] TLS_FINGERPRINT=<new> → proceeds the same way, nothing asked",
      rc == 0 and [x[2] for x in tokened(log) if x[1].endswith("proc-status")] == ["reinstalling", "reinstalled-updated"], (rc, log, out))
box = bare_box(NEW)
rc, out, log = run("install-node.sh", [], box, {})
check("[5] the SAME certificate → the ordinary re-install, with its pin",
      rc == 0 and "still presents that certificate" in out and len(tokened(log)) == 3, (rc, log, out))

print("\n[6]–[7] the Docker node's re-install (install-docker.sh node, as shipped)")
box, inst = docker_box(OLD)
rc, out, log = run("install-docker.sh", ["node"], box, {"SWG_DOCKER_DIR": inst})
check("[6] CHANGED, no terminal → exit 1 with the stop line", rc == 1 and STOP in out and "kept the old pin" in out, out)
check("[6] ⚠️ the listener received NOTHING", log == [], log)
check("[6] …data/node/iface-keys and the .env's pin untouched",
      os.path.exists(os.path.join(inst, "data/node/iface-keys/awg0.json"))
      and ("TLS_FINGERPRINT=%s" % OLD) in open(os.path.join(inst, ".env")).read(), out)
box, inst = docker_box(OLD)
rc, out, log = run("install-docker.sh", ["node"], box, {"SWG_DOCKER_DIR": inst}, answer="\ny\n\n")   # URL · trust: y · name
check("[7] at a terminal, y → proceeds: whoami, then \"reinstalling\" — both with the token, both to the pinned new certificate",
      rc == 0 and "REACHED the datapath step" in out
      and tokened(log)[:2] == [("GET", "/api/node/whoami", None), ("POST", "/api/node/proc-status", "reinstalling")], (rc, log, out))
check("[7] …and the key backups go only now", not os.path.exists(os.path.join(inst, "data/node/iface-keys")), out)

srv.shutdown()
shutil.rmtree(T, ignore_errors=True)
print()
if PERTURBED:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see it"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
