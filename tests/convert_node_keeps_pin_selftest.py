#!/usr/bin/env python3
"""Self-test: converting a NODE between bare-metal and docker keeps its panel-certificate pin.

A node of a self-signed panel trusts it by PINNING the certificate (TLS_VERIFY=no + a sha256 fingerprint). convert.sh
carried only the verify flag in both directions:
  · bare → docker read token/url/verify/endpoint out of /etc/swg-agent/config.json and exec'd install-docker.sh with
    TLS_VERIFY=no and no TLS_FINGERPRINT, so the docker node came up `verify: False` with no fingerprint — trusting any
    certificate at all, where the bare node it replaced had been pinned;
  · docker → bare read TLS_VERIFY out of the .env and ran install-node.sh with it alone — the same loss, mirrored
    (install-node.sh skips its own pin detection whenever TLS_VERIFY is set).
The recovery marker (/var/lib/swg-recovery), which a resumed convert trusts over the half-torn-down source, did not
carry the pin either.

  [1] bare → docker: the fingerprint in the bare config reaches install-docker.sh as TLS_FINGERPRINT (verify stays no)
  [2] …and lands in the recovery marker, hex only (the marker is SOURCED, so nothing else may get in)
  [3] …and a RESUME (bare config already gone) takes it from the marker
  [4] …a bare node with NO pin converts exactly as before (TLS_FINGERPRINT empty)
  [5] docker → bare: the .env pin is carried; a self-learned data/node/panel-fp wins over it, as the entrypoint decides
  [6] …and install-node.sh is handed TLS_FINGERPRINT

[1]–[4] run convert.sh's bare→docker block as shipped (the config path pointed at a temp file, the hand-off pointed at
a stub install-docker.sh that records the environment it was given); [5] runs the docker→bare prologue as shipped.

Run: python3 tests/convert_node_keeps_pin_selftest.py      (0 = pass)
     --perturb   re-plants the shipped convert (no pin read, none handed on, none in the marker) → RED
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
if PERTURB:
    for a, b in [
        ('''fp="".join(ch for ch in str(p.get("fingerprint") or "") if ch in "0123456789abcdefABCDEF:")\n''', ""),
        (''', c.get("endpoint_host","") or "-", fp or "-")''', ''', c.get("endpoint_host","") or "-")'''),
        ("read -r NTOK PURL NVERIFY NEP NFP <<EOF", "read -r NTOK PURL NVERIFY NEP <<EOF"),
        (' TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_CONVERT_DIR=convert-docker', ' TLS_VERIFY="$NVERIFY" SWG_CONVERT_DIR=convert-docker'),
        (' TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_DOCKER_DIR=', ' TLS_VERIFY="$NVERIFY" SWG_DOCKER_DIR='),
        ('''    printf "SWG_RV_FP='%s'\\n" "$(printf '%s' "${NFP:-}" | tr -cd '0-9A-Fa-f:')"''', "    :"),
        ('  [ "$NFP" = "-" ] && NFP=""\n', ""),
    ]:
        assert src.count(a) == 1, "perturbation anchor missing — this run would FALSE-PASS: %r" % a[:60]
        src = src.replace(a, b, 1)
    assert src.count(' NFP="${SWG_RV_FP:-}";') == 2, "perturbation anchor missing (resume) — this run would FALSE-PASS"
    src = src.replace(' NFP="${SWG_RV_FP:-}";', "")
    m = re.search(r"\n  # ⚠️ …AND THE PANEL-CERT PIN\..*?\n(?=  \[ -n \"\$\{SWG_RV_TOKEN:-\}\" \])", src, re.S)
    assert m, "perturbation anchor missing (docker→bare pin read) — this run would FALSE-PASS"
    src = src[:m.start()] + "\n" + src[m.end():]

T = tempfile.mkdtemp(prefix="convpin-")
PIN = "0f" * 32

wr = re.search(r"^write_recovery\(\)\{.*?\n\}\n", src, re.S | re.M)
b2d = re.search(r"# ── NODE: bare-metal → docker ──\n(if .*?\nfi)\n\ndie \"unsupported conversion", src, re.S)
d2b = re.search(r'\n(  envf="\$DOCKER_DIR/\.env"; confd=.*?\n  \[ "\$NVERIFY" = yes \] \|\| NVERIFY=no\n)', src, re.S)
assert wr and b2d and d2b, "convert.sh blocks missing — this run would FALSE-PASS"
B2D = b2d.group(1)
assert B2D.count("/etc/swg-agent/config.json") == 1
STUBS = ('die(){ echo "DIE $*"; exit 3; }; info(){ :; }; sub(){ :; }; warn(){ :; }; b(){ printf %s "$*"; }\n'
         'docker_node_present(){ return 1; }; lc_init(){ :; }; lc_handoff(){ :; }\n')

# the stub hand-off: records what install-docker.sh would have been given
FAKE = os.path.join(T, "fake"); os.makedirs(FAKE)
open(os.path.join(FAKE, "install-docker.sh"), "w").write(
    '#!/bin/bash\n{ echo "TLS_FINGERPRINT=${TLS_FINGERPRINT-<unset>}"; echo "TLS_VERIFY=${TLS_VERIFY-<unset>}"; } > "$OUT"\n')


def bare_to_docker(label, config, recovery=None):
    d = os.path.join(T, label); os.makedirs(d)
    cfg = os.path.join(d, "config.json")
    if config is not None:
        import json
        json.dump(config, open(cfg, "w"))
    rec, out = os.path.join(d, "recovery"), os.path.join(d, "handoff")
    pre = ""
    if recovery:
        open(rec, "w").write(recovery)
        pre = '. "%s"\n' % rec
    script = ('set -euo pipefail\n%s%sFROM=baremetal; TO=docker; ROLE=node; CHECK=no; RESUMING=no; DOCKER_DIR="%s/docker"\n'
              'MIGRATED_TURNS=""; SRC="%s"; RECOVERY="%s"; export OUT="%s"\n%s\n%s\n') % (
        STUBS, pre, d, FAKE, rec, out, wr.group(0), B2D.replace("/etc/swg-agent/config.json", cfg))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    got = dict(l.split("=", 1) for l in open(out).read().splitlines()) if os.path.exists(out) else {}
    return r, got, (open(rec).read() if os.path.exists(rec) else "")


BARE = {"panel": {"url": "https://192.168.77.3:2087", "token": "tok-0123456789abcdef", "verify": False, "fingerprint": PIN},
        "endpoint_host": "192.168.77.4", "interfaces": {}}

print("[1] bare → docker: the pin reaches install-docker.sh")
r, got, rec = bare_to_docker("b2d", BARE)
check("the block ran to the hand-off", r.returncode == 0 and got, (r.returncode, (r.stdout + r.stderr)[-300:]))
check("⚠️ TLS_FINGERPRINT is the bare node's pin", got.get("TLS_FINGERPRINT") == PIN, got)
check("TLS_VERIFY=no (the pin is the verification)", got.get("TLS_VERIFY") == "no", got)

print("\n[2] …and the recovery marker carries it")
check("SWG_RV_FP='<pin>' in the marker", ("SWG_RV_FP='%s'" % PIN) in rec, rec)
evil = dict(BARE, panel=dict(BARE["panel"], fingerprint="ab'; touch %s/pwned; '" % T))
r, got, rec = bare_to_docker("b2d-evil", evil)
check("a hostile fingerprint cannot break out of the sourced marker", not os.path.exists(os.path.join(T, "pwned"))
      and "touch" not in rec, rec)

print("\n[3] …and a resume takes it from the marker")
REC = ("SWG_RV_FROM='baremetal'\nSWG_RV_TO='docker'\nSWG_RV_ROLE='node'\nSWG_RV_TOKEN='tok-0123456789abcdef'\n"
       "SWG_RV_URL='https://192.168.77.3:2087'\nSWG_RV_EP='192.168.77.4'\nSWG_RV_VERIFY='no'\nSWG_RV_FP='%s'\n" % PIN)
r, got, rec = bare_to_docker("b2d-resume", None, recovery=REC)
check("resumed with the bare config gone: TLS_FINGERPRINT from SWG_RV_FP", got.get("TLS_FINGERPRINT") == PIN, (got, (r.stdout + r.stderr)[-300:]))

print("\n[4] a bare node with no pin converts as before")
nopin = dict(BARE, panel={k: v for k, v in BARE["panel"].items() if k != "fingerprint"})
r, got, rec = bare_to_docker("b2d-nopin", nopin)
check("TLS_FINGERPRINT empty, TLS_VERIFY=no", got.get("TLS_FINGERPRINT") == "" and got.get("TLS_VERIFY") == "no", got)

print("\n[5] docker → bare: the pin the running node uses")


def docker_to_bare(label, envtxt, learned=None):
    d = os.path.join(T, label); dd = os.path.join(d, "docker"); os.makedirs(os.path.join(dd, "data", "node"))
    open(os.path.join(dd, ".env"), "w").write(envtxt)
    if learned:
        open(os.path.join(dd, "data", "node", "panel-fp"), "w").write(learned + "\n")
    script = 'set -euo pipefail\nDOCKER_DIR="%s"\n%s\necho "NFP=${NFP-<unset>} NVERIFY=$NVERIFY"\n' % (dd, d2b.group(1))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    m = re.search(r"NFP=(\S*) NVERIFY=(\S*)", r.stdout)
    return (m.group(1), m.group(2)) if m else (None, r.stdout + r.stderr)


ENV = "NODE_TOKEN=tok-0123456789abcdef\nPANEL_URL=https://192.168.77.3:2087\nNODE_ENDPOINT=192.168.77.4\nTLS_VERIFY=no\nTLS_FINGERPRINT=%s\n" % PIN
check("⚠️ the .env pin is carried", docker_to_bare("d2b", ENV) == (PIN, "no"), docker_to_bare("d2b-x", ENV))
LEARNED = "1e" * 32
check("a self-learned data/node/panel-fp wins over the .env", docker_to_bare("d2b-learned", ENV, learned=LEARNED) == (LEARNED, "no"))
check("no pin anywhere: empty, as before (and no abort on the missing learned file)",
      docker_to_bare("d2b-nopin", ENV.replace("TLS_FINGERPRINT=%s\n" % PIN, "")) == ("", "no"))

print("\n[6] install-node.sh is handed the pin")
inv = re.search(r'env NODE_TOKEN="\$NTOK" PANEL_URL="\$PURL" ENDPOINT_IP="\$NEP" ADOPTED_IFACES="\$names"[^\n]*\\\n(.*?)bash "\$SRC/install-node\.sh"', src, re.S)
check('the docker → bare hand-off passes TLS_FINGERPRINT="$NFP"', inv is not None and 'TLS_FINGERPRINT="$NFP"' in inv.group(1),
      inv.group(1) if inv else "invocation not found")

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
