#!/usr/bin/env python3
"""Self-test: converting a docker NODE to bare-metal keeps the panel address and token the node LEARNED.

A docker node that the panel re-pointed (its host/port moved) or transferred (another panel took it over) keeps
running on what it learned: swg-noded writes data/node/panel-url and data/node/panel-token, and
docker/node-entrypoint.sh reads them AHEAD of the .env on every start. The .env is never rewritten, so it still names
where the node USED to sync. convert.sh's docker→bare path read PANEL_URL / NODE_TOKEN from the .env alone, so the bare
node it built dialled the old address (syncing nowhere) or presented the old panel's token (401 for ever) — while the
docker node it replaced had been syncing fine. (bare→docker is not affected: on bare-metal swg-noded writes what it
learns straight into /etc/swg-agent/config.json, which is what that path reads.)

  [1] a learned panel-url that differs from the .env wins — and the convert says so
  [2] a learned panel-token that differs wins (the token itself is never printed)
  [3] learned files equal to the .env, or absent: the .env values, silently (no abort on a missing file)
  [4] a RESUME still wins over both (the recovery marker is the identity of a half-finished convert)
  [5] what reaches install-node.sh and the lifecycle post is that same PURL / NTOK

[1]–[4] run the docker→bare prologue of convert.sh as shipped, against a temp DOCKER_DIR.

Run: python3 tests/convert_node_follows_learned_panel_selftest.py      (0 = pass)
     --perturb   removes the learned-address/token read (the shipped behaviour) → RED
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
    m = re.search(r"\n  # ⚠️ …AND THE ADDRESS AND TOKEN IT LEARNED\..*?NTOK=\"\$_lpt\"; \}\n", src, re.S)
    assert m, "perturbation anchor missing — this run would FALSE-PASS"
    src = src[:m.start()] + "\n" + src[m.end():]

d2b = re.search(r'\n(  envf="\$DOCKER_DIR/\.env"; confd=.*?\n  \[ "\$NVERIFY" = yes \] \|\| NVERIFY=no\n)', src, re.S)
assert d2b, "docker→bare prologue missing — this run would FALSE-PASS"
PROLOGUE = d2b.group(1)
T = tempfile.mkdtemp(prefix="convlearn-")
STUBS = 'sub(){ echo "SUB $*"; }; b(){ printf %s "$*"; }\n'
TOK_ENV, TOK_LEARNED = "stale-token-0123456789abcdef", "learned-token-fedcba9876543210"
URL_ENV, URL_LEARNED = "https://192.168.77.99:2087", "https://192.168.77.3:2087/"
ENV = "NODE_TOKEN=%s\nPANEL_URL=%s\nNODE_ENDPOINT=192.168.77.4\nTLS_VERIFY=no\n" % (TOK_ENV, URL_ENV)


def run(label, url=None, token=None, recovery=""):
    d = os.path.join(T, label); dd = os.path.join(d, "docker"); os.makedirs(os.path.join(dd, "data", "node"))
    open(os.path.join(dd, ".env"), "w").write(ENV)
    if url is not None:
        open(os.path.join(dd, "data", "node", "panel-url"), "w").write(url + "\n")
    if token is not None:
        open(os.path.join(dd, "data", "node", "panel-token"), "w").write(token + "\n")
    script = ('set -euo pipefail\n%s%sDOCKER_DIR="%s"\n%s\necho "PURL=$PURL"; echo "NTOK=$NTOK"\n'
              % (STUBS, recovery, dd, PROLOGUE))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    vals = dict(l.split("=", 1) for l in r.stdout.splitlines() if re.match(r"^(PURL|NTOK)=", l))
    return r.returncode, vals, r.stdout + r.stderr


print("[1] a learned panel-url wins")
rc, v, out = run("url", url=URL_LEARNED)
check("the prologue ran", rc == 0, out[-300:])
check("⚠️ PURL is the learned address", v.get("PURL") == URL_LEARNED, v)
check("…and the convert says it re-pointed", "re-pointed itself to %s" % URL_LEARNED in out, out[-300:])
check("the .env token is kept when no token was learned", v.get("NTOK") == TOK_ENV, v)

print("\n[2] a learned panel-token wins")
rc, v, out = run("token", token=TOK_LEARNED)
check("⚠️ NTOK is the learned token", rc == 0 and v.get("NTOK") == TOK_LEARNED, (rc, out[-300:]))
check("…said without printing the token", "transferred" in out and TOK_LEARNED not in "".join(l for l in out.splitlines() if l.startswith("SUB")))
rc, v, out = run("both", url=URL_LEARNED, token=TOK_LEARNED)
check("both learned → both used", (v.get("PURL"), v.get("NTOK")) == (URL_LEARNED, TOK_LEARNED), v)

print("\n[3] equal or absent → the .env, silently")
rc, v, out = run("same", url=URL_ENV, token=TOK_ENV)
check("equal learned files: .env values, no message", rc == 0 and (v.get("PURL"), v.get("NTOK")) == (URL_ENV, TOK_ENV) and "SUB" not in out, out[-300:])
rc, v, out = run("none")
check("no learned files: .env values, and no abort", rc == 0 and (v.get("PURL"), v.get("NTOK")) == (URL_ENV, TOK_ENV), (rc, out[-300:]))
rc, v, out = run("blank", url="", token="")
check("empty learned files are ignored (never blank the address or token)", (v.get("PURL"), v.get("NTOK")) == (URL_ENV, TOK_ENV), v)

print("\n[4] a resume still wins")
REC = "SWG_RV_TOKEN='resume-token-00000000'; SWG_RV_URL='https://resume.example:2087'; SWG_RV_EP='192.168.77.4'; SWG_RV_VERIFY='no'; SWG_RV_FP=''\n"
rc, v, out = run("resume", url=URL_LEARNED, token=TOK_LEARNED, recovery=REC)
check("the recovery marker's identity wins over learned files", (v.get("PURL"), v.get("NTOK")) == ("https://resume.example:2087", "resume-token-00000000"), v)

print("\n[5] the hand-offs use the same PURL / NTOK")
blk = re.search(r'if \[ "\$FROM" = docker \] && \[ "\$TO" = baremetal \]; then\n(.*?)\nfi\n', src, re.S)
check("install-node.sh is given NODE_TOKEN=\"$NTOK\" PANEL_URL=\"$PURL\"",
      blk is not None and 'env NODE_TOKEN="$NTOK" PANEL_URL="$PURL"' in blk.group(1))
check("the lifecycle post dials LC_URL=\"$PURL\" with LC_TOKEN=\"$NTOK\"",
      blk is not None and 'LC_URL="$PURL"; LC_TOKEN="$NTOK"' in blk.group(1))
check("…and both come AFTER the learned read (nothing uses the stale pair first)",
      blk is not None and blk.group(1).find('LC_URL="$PURL"') > blk.group(1).find("[ \"$NVERIFY\" = yes ] || NVERIFY=no"))

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PERTURB:
    print("(--perturb expects RED above)")
sys.exit(1 if FAILS else 0)
