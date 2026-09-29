#!/usr/bin/env python3
"""Self-test — BEHIND A REVERSE PROXY THE EMPTY TLS TYPE STAYS: NO UPDATE ↔ BOOT PING-PONG (N4).

A panel behind a reverse proxy serves plain HTTP, and its settings say so with tls.mode "" ("None — reverse proxy").
update.sh's ensure_access_seed fills EMPTY Access settings from install.conf — and took that "" for empty: every update
wrote install.conf's TLS_MODE ("skip" there, or the proxy's certificate mode) and printed a bare "TLS type" line; the
panel's next start rolled it back to "" with "rolled saved-but-unconfirmed panel settings back to the live address",
blaming the operator for what the update had written. Once per update, for ever (1.8.8 qualification, round 10, N4).
The installers' own seed wrote the same value at every install.

  [1] update.sh ensure_access_seed, driven (stubs for systemctl): a panel whose unit gives it no certificate keeps "" —
      whatever install.conf's TLS_MODE / SERVE_MODE say, and also when the serve mode says internal (a "skip" install
      with no certificate); with no systemd answer, install.conf's serve mode decides; a panel that serves its own
      certificate still gets an empty TLS type filled, as before; what it fills is said on ONE line, with its source
      (no bare "TLS type"), and nothing at all when nothing was empty; a Docker .env with TLS=none keeps "" too
  [2] seed_access_settings (lib/common.sh), driven: PROXIED=yes → tls.mode "", else TLS_MODE as before; install-host.sh
      decides PROXIED from the serve mode and the certificate (lifted, every combination); install-docker.sh from TLS=none
  [3] the panel's boot reconcile, driven: a TLS type that says HTTPS on a plain-HTTP socket is put back to "" with a
      line of its own that says what it was and what the socket serves — not the "saved-but-unconfirmed" line; a ""
      on a plain-HTTP socket is left alone, silently
  [4] the round trip: update seed → panel start → update seed → panel start on a reverse-proxy box changes nothing and
      prints nothing after the first pass

Run: python3 tests/access_seed_proxied_selftest.py        (0 = pass)
     --perturb   five plants, each on its own — each must turn its own check red
"""
import json, os, re, subprocess, sys, tempfile, types, io, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {k: os.environ.get("SWG_AS_" + k) or os.path.join(ROOT, f) for k, f in
         (("UPDATE", "update.sh"), ("COMMON", "lib/common.sh"), ("HOST", "install-host.sh"), ("DOCKER", "install-docker.sh"),
          ("PANEL", "swg-panel-server"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("update", "UPDATE", '        and os.environ.get("PROXIED") != "yes"):       # behind a reverse proxy "" IS the TLS type (N4)\n',
     "        ):\n", "[1] a reverse-proxy panel keeps its empty TLS type"),
    ("env", "UPDATE", '    if [ -n "$_penv" ]; then case " $_penv " in *" SWG_PANEL_TLS_CERT="[!\\ ]*) ;; *) _proxied=yes;; esac\n'
     '    else case "$(sed -n \'s/^SERVE_MODE=//p\' "$conf" | sed -n 1p)" in nginx|caddy|skip) _proxied=yes;; esac; fi\n',
     '    case "$(sed -n \'s/^SERVE_MODE=//p\' "$conf" | sed -n 1p)" in nginx|caddy|skip) _proxied=yes;; esac\n',
     "[1] …and so does one whose serve mode says internal, when its unit gives it no certificate"),
    ("seed", "COMMON", 'tls["mode"]  = "" if os.environ.get("PROXIED") == "yes" else (os.environ.get("TLS_MODE") or tls.get("mode") or "").strip()\n',
     'tls["mode"]  = (os.environ.get("TLS_MODE") or tls.get("mode") or "").strip()\n', "[2] seed_access_settings: PROXIED=yes → \"\""),
    ("rolled", "PANEL", "tls[\"mode\"] = newmode; ps.setdefault(\"access\", {})[\"tls\"] = tls; rolled = (saved_mode, str(newmode))\n",
     "tls[\"mode\"] = newmode; ps.setdefault(\"access\", {})[\"tls\"] = tls; changed = True\n",
     "[3] the TLS type put back on a plain-HTTP socket says so on its own line"),
    ("line", "UPDATE", '  [ -n "$_out" ] && ok "Access & TLS: filled what was empty in the panel\'s settings from ${conf:-$env_f} — $_out"\n',
     '  [ -n "$_out" ] && echo "$_out"\n', "[1] what it fills is said on one line, with its source"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        if SRC[key].count(old) != 1:
            print("  %-7s STALE ANCHOR (%d) — this plant would plant nothing" % (name, SRC[key].count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(SRC[key].replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_AS_" + key: f.name}), capture_output=True, text=True, timeout=180)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-7s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
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

SEED = fn(SRC["UPDATE"], "ensure_access_seed")
def seed(conf=None, env=None, settings=None, unit_env=None, docker=False):
    """ensure_access_seed as shipped, paths remapped into a temp root; systemctl answers `unit_env` (None = no answer)"""
    t = tempfile.mkdtemp(prefix="as-")
    ps = os.path.join(t, "panel-settings.json")
    if settings is not None:
        open(ps, "w").write(json.dumps(settings))
    stub = os.path.join(t, "bin"); os.makedirs(stub)
    open(os.path.join(stub, "systemctl"), "w").write(
        "#!/bin/bash\n" + ("[ \"$1 $2 $3 $4\" = 'show -p Environment --value' ] && printf '%%s\\n' %s\n" % json.dumps(unit_env)
                           if unit_env is not None else "") + "exit 0\n")
    os.chmod(os.path.join(stub, "systemctl"), 0o755)
    body = SEED.replace("/var/lib/swg-panel/panel-settings.json", ps).replace("/etc/swg-panel/install.conf", os.path.join(t, "install.conf"))
    if conf is not None:
        open(os.path.join(t, "install.conf"), "w").write(conf)
        os.makedirs(os.path.join(t, "panel")); open(os.path.join(t, "panel", "swg-panel-server"), "w").write("")
    dd = os.path.join(t, "docker")
    if env is not None:
        os.makedirs(os.path.join(dd, "data", "lib")); open(os.path.join(dd, ".env"), "w").write(env)
        if settings is not None:
            os.rename(ps, os.path.join(dd, "data", "lib", "panel-settings.json"))
    script = ('set -euo pipefail\nDRYRUN=false; PANEL_DIR="%s/panel"; DOCKER_DIR="%s"\n'
              'have(){ command -v "$1" >/dev/null 2>&1; }; ok(){ echo "OK $*"; }; sub(){ echo "SUB $*"; }\n'
              'docker_profile(){ echo %s; }\n%sensure_access_seed\necho RC=$?\n') % (t, dd, "master" if docker else "node", body)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, PATH=stub + ":" + os.environ["PATH"]))
    f = os.path.join(dd, "data", "lib", "panel-settings.json") if env is not None else ps
    got = json.load(open(f)) if os.path.exists(f) else None
    return r.returncode, r.stdout + r.stderr, got

PROXY_CONF = "PANEL_DOMAIN=panel.example\nPORT=8088\nTLS_MODE=skip\nSERVE_MODE=skip\nACME_EMAIL=\n"
PLAIN_ENV = "SWG_PANEL_FLEET=/etc/swg-panel/fleet.json SWG_PANEL_HOST=127.0.0.1 SWG_PANEL_PORT=8088 SWG_PANEL_AUTH=/etc/swg-panel/auth"
TLS_ENV = PLAIN_ENV + " SWG_PANEL_TLS_CERT=/etc/swg-panel/tls/fullchain.pem SWG_PANEL_TLS_KEY=/etc/swg-panel/tls/key.pem"
PROXY_SET = {"access": {"panel": {"url": "https://panel.example"}, "tls": {"mode": ""}}}

print("[1] update.sh ensure_access_seed")
rc, out, got = seed(conf=PROXY_CONF, settings=PROXY_SET, unit_env=PLAIN_ENV)
check("[1] a reverse-proxy panel keeps its empty TLS type", rc == 0 and got["access"]["tls"]["mode"] == "", (rc, out, got))
check("[1] …and nothing is said when nothing was empty (no bare \"TLS type\" line)", "TLS type" not in out and "OK" not in out, out)
for sm, tm in (("nginx", "letsencrypt"), ("caddy", "letsencrypt"), ("skip", "skip")):
    rc, out, got = seed(conf=PROXY_CONF.replace("SERVE_MODE=skip", "SERVE_MODE=" + sm).replace("TLS_MODE=skip", "TLS_MODE=" + tm),
                        settings=PROXY_SET, unit_env=PLAIN_ENV)
    check("[1] a reverse-proxy panel keeps its empty TLS type — serve %s, TLS_MODE %s" % (sm, tm), got["access"]["tls"]["mode"] == "", (out, got))
rc, out, got = seed(conf=PROXY_CONF.replace("SERVE_MODE=skip", "SERVE_MODE=internal"), settings=PROXY_SET, unit_env=PLAIN_ENV)
check("[1] …and so does one whose serve mode says internal, when its unit gives it no certificate", got["access"]["tls"]["mode"] == "", (out, got))
rc, out, got = seed(conf=PROXY_CONF, settings=PROXY_SET, unit_env=None)
check("[1] no systemd answer → install.conf's serve mode decides (skip → left alone)", rc == 0 and got["access"]["tls"]["mode"] == "", (out, got))
rc, out, got = seed(conf="PANEL_DOMAIN=panel.example\nPORT=443\nTLS_MODE=letsencrypt\nSERVE_MODE=internal\nACME_EMAIL=ops@example.org\n",
                    settings={"access": {"panel": {"url": ""}, "tls": {"mode": ""}}}, unit_env=TLS_ENV)
check("[1] a panel serving its own certificate still gets an empty TLS type filled (letsencrypt)", got["access"]["tls"]["mode"] == "letsencrypt", (out, got))
check("[1] what it fills is said on one line, with its source",
      re.search(r"OK Access & TLS: filled what was empty in the panel's settings from \S+install\.conf — public URL, TLS type, ACME email\n", out)
      is not None and not re.search(r"^TLS type", out, re.M), out)
rc, out, got = seed(env="TLS=none\nPANEL_DOMAIN=panel.example\nPANEL_PORT=8088\n", settings=PROXY_SET, docker=True)
check("[1] a Docker .env with TLS=none keeps \"\" too", rc == 0 and got["access"]["tls"]["mode"] == "", (out, got))
rc, out, got = seed(env="TLS=selfsigned\nPANEL_DOMAIN=panel.example\nPANEL_PORT=8443\n", settings={"access": {"tls": {"mode": ""}}}, docker=True)
check("[1] …and TLS=selfsigned is filled as before", got["access"]["tls"]["mode"] == "selfsigned", (out, got))

print("\n[2] the installers' seed")
SAS = fn(SRC["COMMON"], "seed_access_settings")
def sas(proxied, tls_mode):
    t = tempfile.mkdtemp(prefix="sas-"); p = os.path.join(t, "ps.json")
    r = subprocess.run(["bash", "-c", "set -euo pipefail\nhave(){ command -v \"$1\" >/dev/null 2>&1; }; warn(){ echo WARN; }\n%s"
                        "PANEL_DOMAIN=panel.example PORT=8088 TLS_MODE=%s PROXIED=%s seed_access_settings %s\n" % (SAS, tls_mode, proxied, p)],
                       capture_output=True, text=True, timeout=60)
    return json.load(open(p))["access"]["tls"]["mode"] if os.path.exists(p) else r.stderr
check("[2] seed_access_settings: PROXIED=yes → \"\"", sas("yes", "skip") == "" and sas("yes", "letsencrypt") == "", (sas("yes", "skip"),))
check("[2] …PROXIED=no → TLS_MODE, as before", sas("no", "letsencrypt") == "letsencrypt" and sas("no", "skip") == "skip")
H = SRC["HOST"]
i = H.index("  _seed_proxied=yes\n"); j = H.index("    _seed_proxied=no; fi\n", i) + len("    _seed_proxied=no; fi\n")
DECIDE = H[i:j]
def decide(serve, tls, cert):
    r = subprocess.run(["bash", "-c", "set -euo pipefail\nSERVE_MODE=%s; TLS_MODE=%s; CERT_FULLCHAIN=%s; CERT_KEY=%s\n%secho \"$_seed_proxied\"\n"
                        % (serve, tls, "/c" if cert else "", "/k" if cert else "", DECIDE)], capture_output=True, text=True, timeout=30)
    return r.stdout.strip()
cases = {("internal", "letsencrypt", False): "no", ("internal", "selfsigned", False): "no", ("internal", "skip", True): "no",
         ("internal", "skip", False): "yes", ("nginx", "letsencrypt", False): "yes", ("caddy", "selfsigned", False): "yes",
         ("skip", "skip", False): "yes"}
wrong = {k: decide(*k) for k in cases if decide(*k) != cases[k]}
check("[2] install-host.sh: plain HTTP behind a proxy unless the internal serve mode has a certificate — every combination", not wrong, wrong)
check("[2] …and it is what the seed is handed", 'TLS_MODE="$TLS_MODE" PROXIED="$_seed_proxied" \\\n' in H)
check("[2] install-docker.sh hands PROXIED=yes for TLS=none", 'PROXIED="$([ "${TLS:-}" = none ] && echo yes || echo no)" \\\n' in SRC["DOCKER"])

print("\n[3] the panel's boot reconcile")
m = types.ModuleType("p"); m.__dict__.update({"__name__": "p", "__file__": PATHS["PANEL"]})
exec(compile(SRC["PANEL"].split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)
m.IN_DOCKER = False; m.BIND_PORT = 8088; m.BIND_HOST = "127.0.0.1"; m.TLS_CERT = ""; m.PANEL_BASE = ""
def boot(settings):
    t = tempfile.mkdtemp(prefix="rc-")
    deps = {"panel_settings": json.loads(json.dumps(settings)), "panel_settings_path": os.path.join(t, "panel-settings.json"),
            "nodes_path": os.path.join(t, "nodes.json")}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m._reconcile_saved_ahead(deps, None)
    return deps["panel_settings"], buf.getvalue()
base = {"access": {"panel": {"url": "https://panel.example", "port": 8088, "host": "127.0.0.1", "base": "/"}, "tls": {"mode": "skip"}}}
ps, out = boot(base)
check("[3] the TLS type put back on a plain-HTTP socket says so on its own line",
      ps["access"]["tls"]["mode"] == "" and "access: boot reconcile — the TLS type said 'skip', but this panel serves plain HTTP "
      "(behind a reverse proxy); it is 'None' (reverse proxy) again" in out, (ps, out))
check("[3] …not the \"saved-but-unconfirmed settings\" line (nothing unconfirmed was there)", "saved-but-unconfirmed" not in out, out)
b2 = json.loads(json.dumps(base)); b2["access"]["tls"]["mode"] = ""
ps, out = boot(b2)
check("[3] \"\" on a plain-HTTP socket: left alone, nothing said", ps["access"]["tls"]["mode"] == "" and out == "", (ps, out))

print("\n[4] the round trip on a reverse-proxy box")
state = {"access": {"panel": {"url": "https://panel.example", "port": 8088, "host": "127.0.0.1", "base": "/"}, "tls": {"mode": ""}}}
lines = []
for n in range(2):
    rc, out, got = seed(conf=PROXY_CONF, settings=state, unit_env=PLAIN_ENV)
    lines.append(out.replace("RC=0", "").strip()); state = got
    state, out = boot(state)
    lines.append(out.strip())
check("[4] update → start → update → start: the TLS type stays \"\" and not one line is printed",
      state["access"]["tls"]["mode"] == "" and not any(lines), lines)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
