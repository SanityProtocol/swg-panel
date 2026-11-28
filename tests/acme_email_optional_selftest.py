#!/usr/bin/env python3
"""Self-test — the installers no longer ask for an ACME account email (1.8.12 item 26; the operator, 2026-11-27:
"No email … remove from installers as well if it is not mandatory").

A Let's Encrypt account needs no contact address, and Let's Encrypt has sent no expiry mail since 2025-06-04. What made
the address mandatory was our own question: with no terminal and no ACME_EMAIL, an unattended install with a Let's
Encrypt mode died at it. Two things leaned on the address and move with it.

  [1] the question is gone from both installers (letsencrypt, letsencrypt-ip, cloudflare), and each of those modes takes
      a given or kept address through lib/common.sh's acme_email_take
  [2] acme_email_take, as shipped: none → none, no output, status 0; a given one is kept and said; a re-install keeps
      the one it had; given beats kept; a value that is not an address is said and dropped, never fatal
  [3] each installer's own block after the TLS choice, lifted out AS SHIPPED and run with no terminal and no address:
      it asks nothing and does not stop (the old line died here: "no valid value … and no interactive input")
  [4] acme.sh is installed with the address only when there is one: never the made-up admin@<panel address>
      (admin@203.0.113.77 on an IP) that used to go into its account settings — nor update.sh's admin@localhost: its
      heal (ensure_acme_client, the lines lifted AS SHIPPED) hands on install.conf's address only when it is one
      (review F1; an install.conf written before this item may hold whatever the old loose test let through)
  [5] the TLS type never came from the address: lib/common.sh's seed_access_settings writes the mode the installer chose
      into the panel's settings before its first start, and the panel's boot reconcile (swg-panel-server
      _reconcile_saved_ahead, run as shipped) keeps it wherever that start already serves HTTPS — a container, whose
      placeholder certificate is up before the real one: a panel by IP, no address anywhere, reads letsencrypt-ip.
      (A bare-metal panel's first start is plain HTTP, before its certificate exists: the reconcile clears the type
      there and reads it off the certificate at the next start — "letsencrypt" for a certificate by IP too. Seen on
      alb-onyx 2026-11-27; older than this item and the same with an address: the card's backlog. The panel cannot
      read install.conf: it is root-only, it holds the Cloudflare tokens.)
  [6] .env.example says the address is optional
      (swg-netctl's on-demand install, which also made the address up, is tests/acme_on_demand_selftest.py [1])

Run: python3 tests/acme_email_optional_selftest.py      (0 = pass)
     --perturb   each change taken back out must turn ITS OWN check red ("N plants, N caught")
"""
import atexit, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRCS = {"HOST": "install-host.sh", "DOCKER": "install-docker.sh", "COMMON": "lib/common.sh", "PANEL": "swg-panel-server",
        "ENVEX": ".env.example", "UPDATE": "update.sh"}
PATHS = {k: os.environ.get("SWG_AEO_" + k) or os.path.join(ROOT, v) for k, v in SRCS.items()}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

OLD_Q = 'ask_valid "ACME account email" "${ACME_EMAIL:-}" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com"'
# (name, file key, anchor, replacement, the check that must go red)
PLANTS = [
    ("ask-host", "HOST", '  letsencrypt) acme_email_take "${EMAIL_SAVED:-}";;', "  letsencrypt) " + OLD_Q + ";;",
     "[3] install-host.sh, letsencrypt, no terminal, no address: nothing asked, not stopped"),
    ("ask-docker", "DOCKER", "    letsencrypt) acme_email_take ", "    letsencrypt) " + OLD_Q + " ",
     "[3] install-docker.sh, letsencrypt, no terminal, no address: nothing asked, not stopped"),
    ("menu", "HOST", 'needs a Zone:DNS:Edit+Read token"', 'needs a Zone:DNS:Edit+Read token + email"',
     "[1] install-host.sh: the TLS menu no longer says the Cloudflare mode needs an email"),
    ("fake", "HOST", 'sh${ACME_EMAIL:+ -s email=$ACME_EMAIL}"', 'sh -s email=${ACME_EMAIL:-admin@$PANEL_DOMAIN}"',
     "[4] no address: acme.sh is installed with none"),
    ("fake-update", "UPDATE", 'sh${ACME_EMAIL:+ -s email=$ACME_EMAIL}" >/dev/null', 'sh -s email=${ACME_EMAIL:-admin@localhost}" >/dev/null',
     "[4] update.sh's heal, no address in install.conf: acme.sh is installed with none"),
    ("heal-raw", "UPDATE", '  local ACME_EMAIL=""; acme_email_take "$(sed', '  local ACME_EMAIL; ACME_EMAIL="$(sed',
     "[4] update.sh's heal: a kept value that is not an address is dropped, and said"),
    ("heal-leak", "UPDATE", '  local ACME_EMAIL=""; acme_email_take "$(sed', '  acme_email_take "$(sed',
     "[4] update.sh's heal reads install.conf's address and leaves the run's own alone"),
    ("saved", "COMMON", '  ACME_EMAIL="${ACME_EMAIL:-${1:-}}"', '  ACME_EMAIL="${ACME_EMAIL:-}"',
     "[2] a re-install keeps the address it had"),
    ("keep-bad", "COMMON", '(the certificate needs none)"; ACME_EMAIL=""', '(the certificate needs none)"',
     "[2] a value that is not an address is said and dropped"),
    ("loose", "COMMON", '  if [[ "$ACME_EMAIL" =~ $re ]]; then', '  if case "$ACME_EMAIL" in ?*@?*.?*) true;; *) false;; esac; then',
     "[2] a value that is not an address is said and dropped"),
    ("seed", "COMMON", 'tls["mode"]  = "" if os.environ.get("PROXIED") == "yes" else (os.environ.get("TLS_MODE") or tls.get("mode") or "").strip()',
     'tls["mode"]  = (tls.get("mode") or "").strip()',
     "[5] a panel by IP that starts on HTTPS (the placeholder up), no address: the first start reads letsencrypt-ip"),
    ("required", "ENVEX", "account email — OPTIONAL", "account email (required for those)",
     "[6] .env.example says the address is optional"),
]

if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-11s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        d = tempfile.mkdtemp(prefix="aeo-plant-")
        f = os.path.join(d, os.path.basename(PATHS[key]))
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_AEO_" + key: f}),
                           capture_output=True, text=True, timeout=300)
        shutil.rmtree(d, ignore_errors=True)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-11s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:1200]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


SB = tempfile.mkdtemp(prefix="aeo-")
atexit.register(shutil.rmtree, SB, True)
H, D, C, P, U = SRC["HOST"], SRC["DOCKER"], SRC["COMMON"], SRC["PANEL"], SRC["UPDATE"]


def fn(src, name):
    """One shell function, as shipped: from `name(){` to the first line that closes it."""
    m = re.search(r"^%s\(\)\{.*?^(?:\}|.*; \})$" % re.escape(name), src, re.S | re.M)
    assert m, name
    return m.group(0) + "\n"


def bash(script, **env):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                       env=dict({"PATH": os.environ["PATH"]}, **env), start_new_session=True)   # no terminal at all
    return r.returncode, r.stdout + r.stderr


def tls_block(src, var):
    """The installer's own `case "$<var>" in … esac` that follows the TLS choice — the block the question lived in."""
    i = src.index("acme_email_take") if "acme_email_take" in src else src.index('ask_valid "ACME account email"')
    a = src.rindex('case "$%s" in' % var, 0, i)
    ind = src[src.rindex("\n", 0, a) + 1:a]
    b = src.index("\n" + ind + "esac", a)
    return src[a:b] + "\n" + ind + "esac\n"


# ── [1] the question is gone ─────────────────────────────────────────────────────────────────────────────────
print("[1] neither installer asks for the address")
for label, src, var in (("install-host.sh", H, "TLS_MODE"), ("install-docker.sh", D, "TLS")):
    blk = tls_block(src, var)
    check("[1] %s: no \"ACME account email\" question, no v_email" % label,
          'ask_valid "ACME account email"' not in src and "v_email" not in src, label)
    check("[1] %s: the TLS menu no longer says the Cloudflare mode needs an email" % label,
          "token + email" not in src and "needs a Zone:DNS:Edit+Read token\"" in src, label)
    takes = {m: bool(re.search(r"^\s*%s\)(?:.|\n)*?acme_email_take(?:.|\n)*?;;" % re.escape(m), blk, re.M))
             for m in ("letsencrypt", "letsencrypt-ip", "cloudflare")}
    check("[1] %s: letsencrypt, letsencrypt-ip and cloudflare each take a given or kept address" % label,
          all(takes.values()) and blk.count("acme_email_take") == 3, (takes, blk.count("acme_email_take")))

# ── [2] acme_email_take ──────────────────────────────────────────────────────────────────────────────────────
print("\n[2] acme_email_take, as shipped")
PRE = 'set -euo pipefail\nsub(){ echo "SUB $*"; }\nwarn(){ echo "WARN $*" >&2; }\n' + fn(C, "acme_email_take")


def take(given=None, saved=None):
    rc, out = bash(PRE + ("ACME_EMAIL=%s\n" % given if given is not None else "ACME_EMAIL=\n")
                   + "acme_email_take %s\necho \"GOT=[$ACME_EMAIL]\"\n" % ("'%s'" % saved if saved is not None else ""))
    return rc, out


rc, out = take()
check("[2] no address given or kept: none, nothing said, status 0", rc == 0 and out.strip() == "GOT=[]", (rc, out))
rc, out = take("ops@example.org")
check("[2] a given address is kept and said", rc == 0 and "GOT=[ops@example.org]" in out
      and "SUB ACME account email: ops@example.org" in out and "optional" in out, (rc, out))
rc, out = take(saved="old@example.org")
check("[2] a re-install keeps the address it had", rc == 0 and "GOT=[old@example.org]" in out, (rc, out))
rc, out = take("new@example.org", saved="old@example.org")
check("[2] a given address beats the kept one", rc == 0 and "GOT=[new@example.org]" in out, (rc, out))
bad_ok = True
for bad in ("ops", "ops@example", "@example.org", "ops@.org", "ops @example.org", "a@b.c;id", "*@example.org", "a@b.c$(id)"):
    rc, out = take("'%s'" % bad)
    bad_ok = bad_ok and rc == 0 and "GOT=[]" in out and "WARN ignoring ACME_EMAIL='%s'" % bad in out
    if not bad_ok:
        break
check("[2] a value that is not an address is said and dropped", bad_ok, (bad, rc, out))
rc, out = bash(PRE + "ACME_EMAIL=$'a@b.c\\nid'\nacme_email_take\necho \"GOT=[$ACME_EMAIL]\"\n")
check("[2] …judged whole: a second line does not ride in behind a good first one", rc == 0 and "GOT=[]" in out, (rc, out))

# ── [3] the installers' own block, unattended ────────────────────────────────────────────────────────────────
print("\n[3] the block after the TLS choice, with no terminal and no address")
STUBS = ('set -euo pipefail\nsub(){ echo "SUB $*"; }\nwarn(){ :; }\ncol(){ :; }\nb(){ :; }\nv_cfport(){ return 0; }\n'
         'ask_secret(){ echo "ASKED-SECRET $1"; }\n'
         # the helper the question used, as it behaved with no terminal and no value: it stopped the run
         'v_email(){ case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }\n'
         'ask_valid(){ echo "ASKED $1" >&2; echo "no valid value for $1 and no interactive input to re-prompt" >&2; exit 1; }\n'
         + fn(C, "acme_email_take"))
for label, src, var in (("install-host.sh", H, "TLS_MODE"), ("install-docker.sh", D, "TLS")):
    blk = tls_block(src, var)
    for mode in ("letsencrypt", "letsencrypt-ip"):
        rc, out = bash(STUBS + 'ACME_EMAIL=""; EMAIL_SAVED=""; PANEL_DOMAIN=203.0.113.77; PANEL_PORT=443; URL_PORT=""\n'
                       '%s=%s\n' % (var, mode) + blk + 'echo "DONE email=[$ACME_EMAIL]"\n')
        check("[3] %s, %s, no terminal, no address: nothing asked, not stopped" % (label, mode),
              rc == 0 and "DONE email=[]" in out and "ASKED" not in out, (rc, out))
    rc, out = bash(STUBS + 'ACME_EMAIL=ops@example.org; EMAIL_SAVED=""; PANEL_DOMAIN=panel.example.org; PANEL_PORT=443; URL_PORT=""\n'
                   '%s=letsencrypt\n' % var + blk + 'echo "DONE email=[$ACME_EMAIL]"\n')
    check("[3] %s: an address that is given is still carried" % label, rc == 0 and "DONE email=[ops@example.org]" in out, (rc, out))

# ── [4] the acme.sh install ──────────────────────────────────────────────────────────────────────────────────
print("\n[4] acme.sh's own install")
m = re.search(r'run sh -c "(curl -fsSL https://get\.acme\.sh \| sh[^"\n]*)"', H)
line = m.group(1) if m else ""
rc0, out0 = bash('ACME_EMAIL=""; PANEL_DOMAIN=203.0.113.77\necho "%s"\n' % line)
rc1, out1 = bash('ACME_EMAIL=ops@example.org; PANEL_DOMAIN=203.0.113.77\necho "%s"\n' % line)
check("[4] no address: acme.sh is installed with none", bool(line) and rc0 == 0
      and out0.strip() == "curl -fsSL https://get.acme.sh | sh" and "admin@$PANEL_DOMAIN" not in H, (line, out0))
check("[4] an address: handed to acme.sh's installer as before", rc1 == 0
      and out1.strip() == "curl -fsSL https://get.acme.sh | sh -s email=ops@example.org", out1)
# update.sh's heal: from the line that reads install.conf's address to the one that installs acme.sh, as shipped
_g = U.index('sh -c "curl -fsSL https://get.acme.sh')
_a = U.rindex("\n", 0, U.rindex("s/^ACME_EMAIL=//p", 0, _g)) + 1
HEAL = U[_a:U.index("\n", _g) + 1]


def heal(conf_line):
    t = tempfile.mkdtemp(prefix="heal-", dir=SB)
    with open(os.path.join(t, "install.conf"), "w") as f:
        f.write("TLS_MODE=letsencrypt\n" + (conf_line + "\n" if conf_line is not None else ""))
    rc, out = bash('set -euo pipefail\nsub(){ echo "SUB $*"; }\nwarn(){ echo "WARN $*" >&2; }\ninfo(){ :; }\n'
                   'sh(){ printf \'%s\\n\' "$2" >> "$LOG"; }\n' + fn(C, "acme_email_take")                 # what would be run
                   + 'heal(){\n  local conf="$T/install.conf" mode=letsencrypt\n' + HEAL + '}\n'
                   'ACME_EMAIL=run@example.org\nheal\necho "OUTER=[$ACME_EMAIL]"\n', T=t, LOG=os.path.join(t, "ran"))
    ran = open(os.path.join(t, "ran")).read() if os.path.exists(os.path.join(t, "ran")) else ""
    return rc, out, ran


BARE = "curl -fsSL https://get.acme.sh | sh\n"
got = [heal("ACME_EMAIL="), heal(None)]
check("[4] update.sh's heal, no address in install.conf: acme.sh is installed with none",
      all(rc == 0 and ran == BARE and "WARN" not in out for rc, out, ran in got) and "admin@localhost" not in U, got)
rc, out, ran = heal("ACME_EMAIL=ops@example.org")
check("[4] update.sh's heal, an address in install.conf: handed to acme.sh's installer",
      rc == 0 and ran == "curl -fsSL https://get.acme.sh | sh -s email=ops@example.org\n", (rc, out, ran))
check("[4] update.sh's heal reads install.conf's address and leaves the run's own alone",
      "OUTER=[run@example.org]" in out and "run@example.org" not in ran, (out, ran))
got = [heal("ACME_EMAIL=" + v) for v in ("ops @example.org", "a@b.c;touch PWNED", "a@b.c$(id)", "admin@localhost", "*@example.org")]
check("[4] update.sh's heal: a kept value that is not an address is dropped, and said",
      all(rc == 0 and ran == BARE and "WARN ignoring ACME_EMAIL=" in out for rc, out, ran in got), got)

# ── [5] where the TLS type comes from ────────────────────────────────────────────────────────────────────────
print("\n[5] the seed, then the panel's first start")
import contextlib, io, json, types
SEED = fn(C, "seed_access_settings")


def seed(tls_mode, email="", proxied="no"):
    f = os.path.join(tempfile.mkdtemp(prefix="seed-", dir=SB), "panel-settings.json")
    rc, out = bash('have(){ command -v "$1" >/dev/null 2>&1; }\nwarn(){ echo "WARN $*"; }\n' + SEED + 'seed_access_settings "$F"\n',
                   F=f, PANEL_DOMAIN="203.0.113.77", PANEL_BASE="", PORT="443", TLS_MODE=tls_mode, PROXIED=proxied, ACME_EMAIL=email)
    return (json.load(open(f)) if os.path.exists(f) else {}), (rc, out)


M = types.ModuleType("p"); M.__dict__.update({"__name__": "p", "__file__": PATHS["PANEL"]})
exec(compile(P.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), M.__dict__)
placeholder = os.path.join(SB, "fullchain.pem"); open(placeholder, "w").write("placeholder\n")
M.IN_DOCKER = False; M.BIND_PORT = 443; M.BIND_HOST = "0.0.0.0"; M.PANEL_BASE = ""; M.TLS_CERT = placeholder
M._cert_selfsigned = lambda p: True; M._cert_is_cf_origin = lambda p: False     # the placeholder, mid-issuance


def first_start(settings):
    t = tempfile.mkdtemp(prefix="boot-", dir=SB)
    deps = {"panel_settings": json.loads(json.dumps(settings)), "panel_settings_path": os.path.join(t, "panel-settings.json"),
            "nodes_path": os.path.join(t, "nodes.json")}
    with contextlib.redirect_stdout(io.StringIO()):
        M._reconcile_saved_ahead(deps, None)
    return ((deps["panel_settings"].get("access") or {}).get("tls") or {}).get("mode")


st, why = seed("letsencrypt-ip")
tls = (st.get("access") or {}).get("tls") or {}
check("[5] the seed writes the installer's mode, and no address when none was given",
      tls.get("mode") == "letsencrypt-ip" and tls.get("email") == "", (tls, why))
got = first_start(st)
check("[5] a panel by IP that starts on HTTPS (the placeholder up), no address: the first start reads letsencrypt-ip", got == "letsencrypt-ip", (got, tls))
st2, why = seed("letsencrypt")
got = first_start(st2)
check("[5] …and letsencrypt for a panel by name", got == "letsencrypt", (got, why))
bare = json.loads(json.dumps(st)); bare["access"]["tls"]["mode"] = ""
got = first_start(bare)
check("[5] what the seed is for: the same start with no mode in the settings and no address guesses selfsigned", got == "selfsigned", got)
st3, why = seed("letsencrypt", email="ops@example.org")
check("[5] a given address is still seeded beside the mode", ((st3.get("access") or {}).get("tls") or {}).get("email") == "ops@example.org", (st3, why))

# ── [6] the docs a person fills in ───────────────────────────────────────────────────────────────────────────
print("\n[6] .env.example")
ln = next((l for l in SRC["ENVEX"].splitlines() if l.startswith("ACME_EMAIL=")), "")
check("[6] .env.example says the address is optional", "OPTIONAL" in ln and "required" not in ln, ln)

print("\n" + ("ALL PASS" if not FAILS else "FAILED: %d\n  " % len(FAILS) + "\n  ".join(FAILS)))
sys.exit(1 if FAILS else 0)
