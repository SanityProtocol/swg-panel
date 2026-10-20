#!/usr/bin/env python3
"""Self-test: a Docker node's re-install, and every other reader of its panel, go by the panel the node REALLY uses.

A transfer (another panel took the node over) or a re-point (its panel moved) is written by swg-noded to
data/node/panel-url / -token / -verify / -fp, and docker/node-entrypoint.sh reads those AHEAD of the .env at every
start; the .env still names the panel the node used to sync with. update.sh, uninstall.sh and convert.sh already read
the learned files (lib/common.sh docker_node_panel and its twins) — install-docker.sh's re-install did not (1.8.8
qualification, round 7 follow-up): it offered the OLD panel as the default, posted its status there with the old token,
and decided the pin against the old panel's certificate, so a certificate changed THERE stopped the run (pin_kept_stop)
while the node's own panel was fine. And every reader shared one more gap: a transfer to a panel a public CA vouches for
leaves panel-verify=yes and NO panel-fp — and the readers put the .env's pin back, the pin of the panel the node LEFT.
The entrypoint did too, so the node itself refused every sync after its next restart.

  [1] docker_node_panel (lib/common.sh) on five fixtures: .env only · a re-point (url only) · a pinned transfer ·
      a CA transfer (verify=yes, no fp → NO pin) · a learned verify=no with an empty panel-fp (→ the .env pin: fail closed)
  [2] uninstall.sh's twin gives the same four values on every fixture
  [3] docker/node-entrypoint.sh (its learned-values section, under /bin/sh) gives the same values on every fixture
  [4] convert.sh's docker → bare prologue gives the same values on every fixture
  [5] install-docker.sh node re-install (dry run) after a pinned transfer: the learned panel is the default, its pin is
      the one kept, the rendered .env carries the learned panel, says so in one line, and — a dry run — keeps the files
  [6] …after a CA transfer: TLS_VERIFY=yes and no pin in the rendered .env
  [7] …an explicit -host / -key still wins over what the node learned
  [8] …after a re-point (url only): the .env's pin is carried to the learned address (not a fresh trust-on-first-use)
  [9] after a real .env write the learned copy is removed (and only it); a dry run removes nothing
  [10] bootstrap.sh's recovery list (a node whose live install is gone) reads a Docker identity the same way:
       the learned address and key over the .env's, and the trust by the same rule (_salv_learned, _salv_trust)

Run: python3 tests/docker_effective_panel_selftest.py      (0 = pass)
     --perturb-overlay     the re-install back to the .env alone (the shipped behaviour) → RED on [5] [6] [8]
     --perturb-pinurl      the pin's URL back to the .env's → RED on [8]
     --perturb-ca          docker_node_panel without the CA rule → RED on [1] and every comparison with it
     --perturb-twin        uninstall.sh's twin without it → RED on [2]
     --perturb-entrypoint  the entrypoint without it → RED on [3]
     --perturb-convert     convert.sh without it → RED on [4]
     --perturb-keep        the learned copy left behind after the .env is written → RED on [9]
     --perturb-salv        the recovery list back to the .env's address and key → RED on [10]
     --perturb-salvtrust   the recovery's trust without the CA rule → RED on [10]
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from _tree_copy import copy_tree  # noqa: E402 — the live tree, minus what other gates remove while it is copied
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "--perturb-overlay": ("install-docker.sh", '    if [ -n "$DNP_LEARNED" ]; then\n      _envurl=', '    if false; then\n      _envurl='),
    "--perturb-pinurl": ("install-docker.sh", '_pinurl="${_EFF_URL:-$(_env_val PANEL_URL "$INSTALL_DIR/.env")}"',
                         '_pinurl="$(_env_val PANEL_URL "$INSTALL_DIR/.env")"'),
    "--perturb-ca": ("lib/common.sh", '  [ "$_lv" = yes ] && [ -z "$_lf" ] && DNP_FP=""\n  DNP_LEARNED=', '  DNP_LEARNED='),
    "--perturb-twin": ("uninstall.sh", '  [ "$_lv" = yes ] && [ -z "$_lf" ] && DNP_FP=""\n  [ "$DNP_VERIFY" = yes ]', '  [ "$DNP_VERIFY" = yes ]'),
    "--perturb-entrypoint": ("docker/node-entrypoint.sh", 'if [ "${_pv:-}" = yes ] && [ -z "${_pf:-}" ] && [ -n "$TLS_FINGERPRINT" ]; then',
                             'if false; then'),
    "--perturb-convert": ("convert.sh", '  [ "$_lvf" = yes ] && [ -z "$_lfp" ] && NFP=""\n', ""),
    "--perturb-keep": ("install-docker.sh", '    else rm -f "$INSTALL_DIR/data/node/panel-url" "$INSTALL_DIR/data/node/panel-token"',
                       '    else : "$INSTALL_DIR/data/node/panel-url" "$INSTALL_DIR/data/node/panel-token"'),
    "--perturb-salv": ("bootstrap.sh", '    _salv_learned "$(dirname "$_f")"\n', ""),
    "--perturb-salvtrust": ("bootstrap.sh", '    [ "$_lv" = yes ] && [ -z "$_lf" ] && f="";; esac', "    ;; esac"),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

T = tempfile.mkdtemp(prefix="effpanel-")
SRC = os.path.join(T, "src")
copy_tree(ROOT, SRC, ignore=shutil.ignore_patterns(".git", "dryrun", "node_modules", "*.png", "scratchpad", "docs",
                                                   ".campaign", "__pycache__", "forks", "screenshots", ".claude"))
if MODE:
    f, cut, new = PLANTS[MODE]
    p = os.path.join(SRC, f)
    s = open(p, encoding="utf-8").read()
    assert s.count(cut) == 1, "perturbation anchor for %s missing or not unique — this run would FALSE-PASS" % MODE
    open(p, "w", encoding="utf-8").write(s.replace(cut, new, 1))


def src_of(f):
    return open(os.path.join(SRC, f), encoding="utf-8").read()


def bash_fn(text, name):
    m = re.search(r"(?ms)^%s\(\)\{.*?^  return 0; \}\n" % re.escape(name), text)
    assert m, "function %s not found — this run would FALSE-PASS" % name
    return m.group(0)


OLD_URL, NEW_URL = "https://192.168.77.3:2087", "https://192.168.77.6:2087"
OLD_TOK, NEW_TOK = "OLDtokOLDtokOLDtokOLDtok00", "NEWtokNEWtokNEWtokNEWtok11"
OLD_FP, NEW_FP = "a" * 64, "b" * 64
ENV = "PANEL_URL=%s\nNODE_TOKEN=%s\nNODE_ENDPOINT=192.168.77.4\nTLS_VERIFY=no\nTLS_FINGERPRINT=%s   # the pin\nSWG_IMAGE_TAG=sha-1726ba8\n" % (
    OLD_URL, OLD_TOK, OLD_FP)
FIXTURES = {   # name → (learned files, the effective (url, token, verify, fp))
    "env-only":    ({}, (OLD_URL, OLD_TOK, "no", OLD_FP)),
    "re-point":    ({"panel-url": NEW_URL}, (NEW_URL, OLD_TOK, "no", OLD_FP)),
    "pinned-xfer": ({"panel-url": NEW_URL, "panel-token": NEW_TOK, "panel-verify": "no", "panel-fp": NEW_FP},
                    (NEW_URL, NEW_TOK, "no", NEW_FP)),
    "ca-xfer":     ({"panel-url": NEW_URL, "panel-token": NEW_TOK, "panel-verify": "yes"}, (NEW_URL, NEW_TOK, "yes", "")),
    "empty-fp":    ({"panel-url": NEW_URL, "panel-token": NEW_TOK, "panel-verify": "no", "panel-fp": ""},
                    (NEW_URL, NEW_TOK, "no", OLD_FP)),
}


def make_dir(label, learned, env=ENV):
    d = os.path.join(T, label)
    os.makedirs(os.path.join(d, "data", "node"), exist_ok=True)
    open(os.path.join(d, ".env"), "w").write(env)
    open(os.path.join(d, "data", "node", "transport.json"), "w").write("{}\n")   # a file the removal must leave
    for k, v in learned.items():
        open(os.path.join(d, "data", "node", k), "w").write(v + ("\n" if v else ""))
    return d


def run_bash(script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def vals(out):
    d = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln and ln.split("=", 1)[0] in ("URL", "TOK", "VERIFY", "FP"))
    return (d.get("URL"), d.get("TOK"), d.get("VERIFY"), d.get("FP"))


# ── [1] + [2] the two readers ─────────────────────────────────────────────────────────────────────────────────────
DNP = bash_fn(src_of("lib/common.sh"), "docker_node_panel")
TWIN = bash_fn(src_of("uninstall.sh"), "_docker_node_panel")
for name, (learned, want) in FIXTURES.items():
    d = make_dir("r-" + name, learned)
    rc, out, err = run_bash('set -euo pipefail\n%s\ndocker_node_panel "%s"\necho "URL=$DNP_URL"; echo "TOK=$DNP_TOKEN"; '
                            'echo "VERIFY=$DNP_VERIFY"; echo "FP=$DNP_FP"; echo "LEARNED=$DNP_LEARNED"' % (DNP, d))
    check("[1] docker_node_panel, %s → %s" % (name, "/".join(x[:12] if x else "-" for x in want)), rc == 0 and vals(out) == want,
          (rc, vals(out), err[-200:]))
    if name == "env-only":
        check("[1] …nothing learned: DNP_LEARNED is empty", "LEARNED=\n" in out + "\n", out)
    rc, out2, err = run_bash('set -euo pipefail\n%s\n_docker_node_panel "%s"\necho "URL=$DNP_URL"; echo "TOK=$DNP_TOKEN"; '
                             'echo "VERIFY=$DNP_VERIFY"; echo "FP=$DNP_FP"' % (TWIN, d))
    check("[2] uninstall.sh's twin agrees, %s" % name, rc == 0 and vals(out2) == want, (rc, vals(out2), err[-200:]))

# ── [3] the entrypoint ────────────────────────────────────────────────────────────────────────────────────────────
ep = src_of("docker/node-entrypoint.sh")
m = re.search(r"(?ms)^if \[ -f /var/lib/swg-noded/panel-url \]; then.*?^  TLS_FINGERPRINT=\"\"\nfi\n", ep)
if MODE == "--perturb-entrypoint" and not m:
    m = re.search(r"(?ms)^if \[ -f /var/lib/swg-noded/panel-url \]; then.*?^if false; then.*?^fi\n", ep)
assert m, "the entrypoint's learned-values section is not where this gate reads it — this run would FALSE-PASS"
SECTION = m.group(0)
SH = shutil.which("dash") or "/bin/sh"
for name, (learned, want) in FIXTURES.items():
    d = make_dir("e-" + name, learned)
    body = SECTION.replace("/var/lib/swg-noded/", d + "/data/node/")
    script = ('set -eu\nlog(){ :; }\nPANEL_URL=%s; NODE_TOKEN=%s; TLS_VERIFY=no; TLS_FINGERPRINT=%s\n%s\n'
              'echo "URL=$PANEL_URL"; echo "TOK=$NODE_TOKEN"; echo "VERIFY=$TLS_VERIFY"; echo "FP=$TLS_FINGERPRINT"\n'
              % (OLD_URL, OLD_TOK, OLD_FP, body))
    r = subprocess.run([SH, "-c", script], capture_output=True, text=True, timeout=60)
    check("[3] the entrypoint (%s) agrees, %s" % (os.path.basename(SH), name), r.returncode == 0 and vals(r.stdout) == want,
          (r.returncode, vals(r.stdout), r.stderr[-200:]))

# ── [4] convert.sh's docker → bare prologue ──────────────────────────────────────────────────────────────────────
cv = src_of("convert.sh")
m = re.search(r'\n(  envf="\$DOCKER_DIR/\.env"; confd=.*?\n  \[ "\$NVERIFY" = yes \] \|\| NVERIFY=no\n)', cv, re.S)
assert m, "convert.sh's docker → bare prologue not found — this run would FALSE-PASS"
PROLOGUE = m.group(1)
for name, (learned, want) in FIXTURES.items():
    d = make_dir("c-" + name, learned)
    rc, out, err = run_bash('set -euo pipefail\nsub(){ :; }; b(){ printf %%s "$*"; }\nDOCKER_DIR="%s"\n%s\n'
                            'echo "URL=$PURL"; echo "TOK=$NTOK"; echo "VERIFY=$NVERIFY"; echo "FP=$NFP"' % (d, PROLOGUE))
    check("[4] convert.sh (docker → bare) agrees, %s" % name, rc == 0 and vals(out) == want, (rc, vals(out), err[-200:]))


# ── [5]–[8] install-docker.sh node re-install, dry run ───────────────────────────────────────────────────────────
def dry(label, learned, extra_env=None, args=()):
    d = make_dir("i-" + label, learned)
    env = dict(os.environ, SWG_DOCKER_DIR=d)
    for k in ("TLS_VERIFY", "TLS_FINGERPRINT", "PANEL_URL", "NODE_TOKEN", "ENDPOINT_IP", "NODE_ENDPOINT"):
        env.pop(k, None)
    env.update(extra_env or {})
    r = subprocess.run(["bash", "install-docker.sh", "node", *args, "--dry-run"], cwd=SRC, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=300, start_new_session=True)
    rendered = os.path.join(SRC, "dryrun" + d, ".env")
    v = {}
    for ln in (open(rendered).read() if os.path.exists(rendered) else "").splitlines():
        mm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ln)
        if mm and mm.group(1) not in v:
            v[mm.group(1)] = re.sub(r"\s+#.*$", "", mm.group(2)).strip()
    return r.returncode, r.stdout + r.stderr, v, d


rc, out, v, d = dry("pinned", FIXTURES["pinned-xfer"][0])
check("[5] pinned transfer: the re-install says it goes by the panel the node was transferred to (one line)",
      rc == 0 and len(re.findall(r"this node was transferred to .*%s.* — re-installing against that panel, not the \.env's %s"
                                 % (re.escape(NEW_URL), re.escape(OLD_URL)), out)) == 1, out[-1500:])
check("[5] …the learned panel is the default of the Panel URL question", "Panel URL (https://host[/subpath]): %s" % NEW_URL in out,
      out[-1500:])
check("[5] …the pin carried is the learned one (the decision is made against the node's own panel)",
      "keeping the panel cert pin (sha256 %s…)" % NEW_FP[:16] in out and OLD_FP[:16] not in out, out[-1500:])
check("[5] …the rendered .env names that panel, its key and its pin",
      (v.get("PANEL_URL"), v.get("NODE_TOKEN"), v.get("TLS_VERIFY"), v.get("TLS_FINGERPRINT")) == (NEW_URL, NEW_TOK, "no", NEW_FP),
      v)
check("[5] …and a dry run removes nothing (it says what it would)",
      all(os.path.exists(os.path.join(d, "data", "node", f)) for f in ("panel-url", "panel-token", "panel-verify", "panel-fp"))
      and "would be removed" in out, out[-600:])
rc, out, v, d = dry("ca", FIXTURES["ca-xfer"][0])
check("[6] CA transfer: TLS_VERIFY=yes and no pin — never the pin of the panel the node left",
      rc == 0 and (v.get("PANEL_URL"), v.get("TLS_VERIFY"), v.get("TLS_FINGERPRINT")) == (NEW_URL, "yes", ""), (rc, v))
GIVEN_URL, GIVEN_TOK = "https://192.168.77.1:2087", "GIVtokGIVtokGIVtokGIVtok22"
rc, out, v, d = dry("given", FIXTURES["pinned-xfer"][0], {"PANEL_URL": GIVEN_URL, "NODE_TOKEN": GIVEN_TOK})
check("[7] an explicit panel and key still win over what the node learned",
      rc == 0 and (v.get("PANEL_URL"), v.get("NODE_TOKEN")) == (GIVEN_URL, GIVEN_TOK), (rc, v))
rc, out, v, d = dry("repoint", FIXTURES["re-point"][0])
check("[8] re-point: the .env's pin is carried to the learned address — the same panel, not a new trust decision",
      rc == 0 and "keeping the panel cert pin (sha256 %s…)" % OLD_FP[:16] in out
      and (v.get("PANEL_URL"), v.get("NODE_TOKEN"), v.get("TLS_FINGERPRINT")) == (NEW_URL, OLD_TOK, OLD_FP)
      and "panel moved to" in out, (rc, v, out[-1200:]))

# ── [9] the removal after a real .env write ──────────────────────────────────────────────────────────────────────
ids = src_of("install-docker.sh")
m = re.search(r'(?ms)^if \[ "\$PROFILE" = node \] && \[ -z "\$\{SWG_CONVERT_DIR:-\}" \]; then\n  _lrn="".*?^  fi\nfi\n', ids)
assert m, "the removal block is not where this gate reads it — this run would FALSE-PASS"
REMOVAL = m.group(0)
for dryrun in ("false", "true"):
    d = make_dir("rm-" + dryrun, FIXTURES["pinned-xfer"][0])
    rc, out, err = run_bash('set -euo pipefail\nsub(){ echo "SUB $*"; }\nPROFILE=node; DRYRUN=%s; INSTALL_DIR="%s"\n%s' % (dryrun, d, REMOVAL))
    left = sorted(os.listdir(os.path.join(d, "data", "node")))
    if dryrun == "false":
        check("[9] after a real .env write the learned copy is gone — and only it", rc == 0 and left == ["transport.json"],
              (rc, left, out, err[-200:]))
        check("[9] …said in one line", out.count("SUB ") == 1 and "removed" in out, out)
    else:
        check("[9] a dry run leaves them", rc == 0 and len(left) == 5, (rc, left))

# ── [10] bootstrap.sh's recovery list ──────────────────────────────────────────────────────────────────────────
bs = src_of("bootstrap.sh")
SALV = bash_fn(bs, "_salv_learned")
mt = re.search(r"(?ms)^_salv_trust\(\)\{.*?\n  printf '%s %s\\n' .*?; \}\n", bs)
assert mt, "_salv_trust not where this gate reads it — this run would FALSE-PASS"
for name, (learned, want) in FIXTURES.items():
    d = make_dir("b-" + name, learned)
    rc, out, err = run_bash('set -euo pipefail\n%s\n%s\n_f="%s/.env"\n'
                            '_t="$(sed -n \'s/^NODE_TOKEN=//p\' "$_f" | sed -n 1p | tr -d \'"\')"; _u="$(sed -n \'s/^PANEL_URL=//p\' "$_f" | sed -n 1p | tr -d \'"\')"\n'
                            '_salv_learned "$(dirname "$_f")"\nread -r _v _p <<EOF\n$(_salv_trust "$_f")\nEOF\n'
                            'echo "URL=$_u"; echo "TOK=$_t"; echo "VERIFY=$_v"; echo "FP=${_p:-}"' % (SALV, mt.group(0), d))
    check("[10] the recovery list agrees, %s" % name, rc == 0 and vals(out) == want, (rc, vals(out), err[-200:]))
loop = bs[bs.find("  for _f in /opt/swg-panel-docker/.env $(ls -dt"):]
loop = loop[:loop.find("  done\n")]
cont = bs[bs.find('    _env="$(docker inspect swg-node'):]
cont = cont[:cont.find("  fi\n")]
check("[10] …and every Docker source goes through it: each .env in the list, and the leftover container",
      '_salv_learned "$(dirname "$_f")"' in loop and "_salv_learned /opt/swg-panel-docker" in cont, (loop[-300:], cont[-200:]))

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    shutil.rmtree(T, ignore_errors=True)
    sys.exit(0 if FAILS else 1)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
