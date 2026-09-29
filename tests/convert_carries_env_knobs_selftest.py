#!/usr/bin/env python3
"""Self-test: a convert keeps the settings each side holds only in its own place — the Docker .env, the bare drop-ins.

1.8.8 qualification, round 7 follow-up — the mirror of F64 (a convert BACK to Docker keeps the operator's .env keys):
SWG_LATEST_URL (the panel's release check — a box following dev) and SWG_TURN_MIRROR (the node's proxy for the turn
downloads) reach a container from the .env and nowhere else. The bare services read the same variables from their
environment, and nothing carried them: a converted box silently went back to main's release check and the direct
download. The node's client DNS (the Docker .env's DNS, the bare node's config "dns") was dropped by the convert in
BOTH directions too — a node set to its own resolver came out on 1.1.1.1.

  [1] carry_env_to_dropin (convert.sh, run with the systemd dir rooted in a temp dir):
      a. SWG_LATEST_URL (unquoted, with a trailing ` # comment`) → a drop-in 50-swg-from-docker.conf naming it, mode
         644, a daemon-reload, and ONE line saying what was kept and where
      b. a value carrying % " \\ → escaped so that systemd reads back exactly the value (% is a specifier in a unit)
      c. SWG_TURN_MIRROR with two prefixes (a space) → one Environment= line, read back whole
      d. a quoted value `"…"  # c` → the value inside the quotes
      e. nothing set → no drop-in; one an EARLIER convert wrote is removed, the operator's own beside it is not
  [2] the call sites in convert.sh: the panel's drop-in is written after install-host.sh and before the switch first
      starts the bare panel; the node's before install-node.sh (both the node convert and a master's node phase)
  [3] the node's client DNS: docker → bare hands the .env's DNS to install-node.sh (both paths), bare → docker hands the
      bare config's to install-docker.sh (both paths); the bare config's is read by the real snippet, and anything but
      a plain address list is refused (it is written into JSON)
  [4] install-node.sh (dry run) writes the DNS it is given into the node's config

…and the other way (round 7c): a bare → Docker convert deleted the bare units' drop-in dirs (teardown_bare_panel,
lc_teardown_baremetal) with whatever the operator had put there — SWG_LATEST_URL following dev, SWG_TURN_MIRROR, a
console port — and the Docker box came up on main's release check and the direct download.
  [5] carry_dropins_to_env (convert.sh, the systemd dir and the parking place rooted in a temp dir):
      a. SWG_LATEST_URL from an operator's drop-in → the carry file, as the .env reads it; another variable and another
         directive are NAMED as not carried; the file is kept byte for byte in the parking place (0700 dir, 0600 file);
         ONE line says all of it
      b. %% → % (systemd's own reading); an empty Environment= resets what came before it (systemd's too)
      c. SWG_TURN_MIRROR (two prefixes, quoted) from swg-noded's drop-in, whole; our own drop-ins (zz-swg-update.conf,
         10-swg-reach-sweep.conf) are not read and not parked; 50-swg-from-docker.conf (a Docker → bare convert's) is read
         — its values carried — but never parked (round 8: every D→B→D trip parked it in a directory of its own); with
         only that file there, no parking directory at all
      d. the console's SWG_PANEL_CONSOLE_PORT / _HOST → given to install-docker.sh as CONSOLE_PORT / CONSOLE_BIND; a
         value that is not a plain port / address, or one with a quote the .env cannot hold, is named, not carried
      e. only the units asked for are read (a node convert does not carry a panel drop-in); no drop-ins → nothing said,
         nothing parked
  [6] install-docker.sh appends the carried keys under their own heading, a key the file already has never twice
  [7] the call sites: the host / master convert reads the panel's (and a master's node's) drop-ins and hands the carry
      file and the given values to install-docker.sh (host, and a master's node step); the node convert reads
      swg-noded's — before the hand-off, while the bare units still exist

Run: python3 tests/convert_carries_env_knobs_selftest.py      (0 = pass)
     --perturb-carry    the panel's drop-in never written (the shipped behaviour) → RED on [2]
     --perturb-escape   % not escaped → RED on [1b]
     --perturb-stale    an earlier convert's drop-in left behind → RED on [1e]
     --perturb-dns      docker → bare hands install-node.sh no DNS → RED on [3]
     --perturb-dropins  bare → docker carries nothing from the drop-ins (the shipped behaviour) → RED on [5]
     --perturb-park     the drop-ins are not kept aside → RED on [5a]
     --perturb-own-park our own 50-swg-from-docker.conf is parked again (round 8's noise) → RED on [5c]
     --perturb-docker-carry   install-docker.sh ignores SWG_CARRY_ENV → RED on [6]
"""
import json, os, re, shutil, stat, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


src = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
PLANTS = {
    # (the call carries the console's keys too since 20dde63 — F95 — on a continuation line; the plant takes both lines)
    "--perturb-carry": ('  carry_env_to_dropin "$envf" swg-panel-server SWG_LATEST_URL \\\n'
                        "      'SWG_PANEL_CONSOLE_PORT=CONSOLE_PORT/8445/[0-9]{1,5}' 'SWG_PANEL_CONSOLE_HOST=CONSOLE_BIND/127.0.0.1/[0-9A-Fa-f.:]{2,45}'"
                        "   # the release check and the console's own address, before the first start below\n", ""),
    "--perturb-escape": ("; s/%/%%/g')", "')"),
    "--perturb-stale": ('    [ -f "$f" ] && { rm -f "$f"; rmdir "$d" 2>/dev/null || true; systemctl daemon-reload 2>/dev/null || true; }\n', ""),
    "--perturb-dns": ('      SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_DOCKER_DIR="$DOCKER_DIR" ${NDNS:+DNS="$NDNS"} bash "$SRC/install-node.sh" \\\n',
                      '      SWG_CONVERT=1 TLS_VERIFY="$NVERIFY" TLS_FINGERPRINT="$NFP" SWG_DOCKER_DIR="$DOCKER_DIR" bash "$SRC/install-node.sh" \\\n'),
    "--perturb-dropins": ('  shift; : > "$carry"; DROPIN_GIVE=""\n', '  shift; : > "$carry"; DROPIN_GIVE=""; return 0\n'),
    "--perturb-park": ('      FILE)  u="$k"; f="$v"; mkdir -p "$park/$u.service.d" && chmod 700 "$park" && cp -p "$f" "$park/$u.service.d/" \\\n'
                       '               && chmod 600 "$park/$u.service.d/$(basename "$f")" && parked=yes ;;\n', '      FILE)  : ;;\n'),
    "--perturb-own-park": ('        if name != "50-swg-from-docker.conf":\n            print("FILE\\t%s\\t%s" % (unit, f))',
                           '        if True:\n            print("FILE\\t%s\\t%s" % (unit, f))'),
}
DOCKER_PLANTS = {
    "--perturb-docker-carry": ('if [ -n "${SWG_CARRY_ENV:-}" ] && [ -s "$SWG_CARRY_ENV" ]; then\n', 'if false; then\n'),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS or a in DOCKER_PLANTS), None)
if MODE in PLANTS:
    cut, new = PLANTS[MODE]
    assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — this run would FALSE-PASS" % MODE
    src = src.replace(cut, new, 1)
dsrc = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
if MODE in DOCKER_PLANTS:
    cut, new = DOCKER_PLANTS[MODE]
    assert dsrc.count(cut) == 1, "perturbation anchor for %s missing or not unique — this run would FALSE-PASS" % MODE
    dsrc = dsrc.replace(cut, new, 1)

T = tempfile.mkdtemp(prefix="envknobs-")


def fn(name, text=src):
    m = re.search(r"(?ms)^%s\(\)\{.*?^\}\n" % re.escape(name), text)
    if not m:
        m = re.search(r"(?m)^%s\(\)\{.*\}\n" % re.escape(name), text)   # a one-line function
    assert m, "function %s not found — this run would FALSE-PASS" % name
    return m.group(0)


FUNCS = ("DOTENV_DROPIN=50-swg-from-docker.conf\n" + fn("_dotenv_val") + fn("carry_env_to_dropin") + fn("_dns_ok"))
FUNCS = FUNCS.replace('d="/etc/systemd/system/$unit.service.d"', 'd="$SDROOT/$unit.service.d"')
assert "$SDROOT" in FUNCS, "the systemd dir is not where this gate roots it — this run would FALSE-PASS"


def carry(label, env_text, unit, *keys, pre=None):
    sd = os.path.join(T, label, "sd"); os.makedirs(sd)
    envf = os.path.join(T, label, ".env"); open(envf, "w").write(env_text)
    for rel, body in (pre or {}).items():
        p = os.path.join(sd, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(body)
    log = os.path.join(T, label, "systemctl.log")
    script = ('set -euo pipefail\nSDROOT="%s"\nsub(){ echo "SUB $*"; }; b(){ printf %%s "$*"; }\n'
              'systemctl(){ echo "$*" >> "%s"; }\n%s\ncarry_env_to_dropin "%s" %s %s\n' % (sd, log, FUNCS, envf, unit, " ".join(keys)))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    f = os.path.join(sd, unit + ".service.d", "50-swg-from-docker.conf")
    return r, sd, f, (open(log).read() if os.path.exists(log) else "")


def systemd_env(text):
    """Environment= lines of a drop-in, read back the way systemd does for the escapes this writer uses."""
    out = {}
    for ln in text.splitlines():
        m = re.match(r'^Environment="(.*)"$', ln)
        if not m:
            continue
        v, i, buf = m.group(1), 0, ""
        while i < len(v):
            if v[i] == "\\" and i + 1 < len(v):
                buf += v[i + 1]; i += 2; continue
            if v[i] == "%":
                assert v[i:i + 2] == "%%", "a lone %% in a unit is a specifier: %r" % v
                buf += "%"; i += 2; continue
            buf += v[i]; i += 1
        k, val = buf.split("=", 1); out[k] = val
    return out


URL = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/VERSION"
# [1a]
r, sd, f, log = carry("a", "PANEL_DOMAIN=x\nSWG_LATEST_URL=%s   # follow dev\n" % URL, "swg-panel-server", "SWG_LATEST_URL")
body = open(f).read() if os.path.exists(f) else ""
check("[1a] the drop-in names SWG_LATEST_URL (the trailing comment is not part of it)",
      r.returncode == 0 and systemd_env(body) == {"SWG_LATEST_URL": URL}, (r.returncode, body, r.stderr[-300:]))
check("[1a] …it is a [Service] drop-in, 644, and says whose setting it is",
      "[Service]" in body and "your own setting" in body and os.path.exists(f) and stat.S_IMODE(os.stat(f).st_mode) == 0o644, body)
check("[1a] …a daemon-reload follows", "daemon-reload" in log, log)
check("[1a] …and ONE line says what was kept and where",
      r.stdout.count("SUB ") == 1 and "SWG_LATEST_URL" in r.stdout and "50-swg-from-docker.conf" in r.stdout, r.stdout)
# [1b]
odd = 'https://mirror.example/dl?x=50%25off&q="a\\b"'
r, sd, f, log = carry("b", "SWG_LATEST_URL='%s'\n" % odd, "swg-panel-server", "SWG_LATEST_URL")
body = open(f).read() if os.path.exists(f) else ""
try:
    got = systemd_env(body)
except AssertionError as e:
    got = str(e)
check("[1b] a value with %% \" and \\ is read back by systemd as exactly itself", got == {"SWG_LATEST_URL": odd}, (got, body))
# [1c]
mir = "https://ghproxy.example/ https://mirror2.example/gh/"
r, sd, f, log = carry("c", 'SWG_TURN_MIRROR="%s"\nDNS=1.1.1.1\n' % mir, "swg-noded", "SWG_TURN_MIRROR")
body = open(f).read() if os.path.exists(f) else ""
check("[1c] SWG_TURN_MIRROR with two prefixes: one Environment= line, read back whole",
      systemd_env(body) == {"SWG_TURN_MIRROR": mir} and body.count("Environment=") == 1, body)
# [1d]
r, sd, f, log = carry("d", 'SWG_LATEST_URL="%s"   # quoted\n' % URL, "swg-panel-server", "SWG_LATEST_URL")
check("[1d] a quoted value: the value inside the quotes", systemd_env(open(f).read()) == {"SWG_LATEST_URL": URL}, open(f).read())
# [1e]
r, sd, f, log = carry("e", "PANEL_DOMAIN=x\n", "swg-panel-server", "SWG_LATEST_URL",
                      pre={"swg-panel-server.service.d/50-swg-from-docker.conf": "[Service]\nEnvironment=\"SWG_LATEST_URL=old\"\n",
                           "swg-panel-server.service.d/latest.conf": "[Service]\nEnvironment=OPS=1\n"})
check("[1e] nothing set: an earlier convert's drop-in is removed",
      r.returncode == 0 and not os.path.exists(f), (r.returncode, os.listdir(os.path.join(sd, "swg-panel-server.service.d"))))
check("[1e] …the operator's own drop-in beside it is not", os.path.exists(os.path.join(sd, "swg-panel-server.service.d", "latest.conf")))
check("[1e] …and nothing is said (nothing was kept)", "SUB " not in r.stdout, r.stdout)
r, sd, f, log = carry("e2", "PANEL_DOMAIN=x\n", "swg-noded", "SWG_TURN_MIRROR")
check("[1e] nothing set, nothing there: no drop-in, no dir", r.returncode == 0 and not os.path.exists(os.path.join(sd, "swg-noded.service.d")))

# ── [2] the call sites ────────────────────────────────────────────────────────────────────────────────────────────
pd = src.find('if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then')
nd = src.find('if [ "$FROM" = docker ] && [ "$TO" = baremetal ]; then')
assert 0 < pd < nd, "the docker → bare blocks are not where this gate reads them — this run would FALSE-PASS"
panel_blk, node_blk = src[pd:nd], src[nd:src.find("# ── NODE: bare-metal → docker ──", nd)]
i_host = panel_blk.find('bash "$SRC/install-host.sh"')
i_carry = panel_blk.find('carry_env_to_dropin "$envf" swg-panel-server SWG_LATEST_URL')
i_start = panel_blk.find("systemctl start swg-panel-server")
check("[2] panel convert: the drop-in is written after install-host.sh and before the bare panel's first start",
      0 < i_host < i_carry < i_start, (i_host, i_carry, i_start))
for label, blk in (("node convert", node_blk), ("a master's node phase", panel_blk)):
    i_nc = blk.find('carry_env_to_dropin "$envf" swg-noded SWG_TURN_MIRROR')
    i_in = blk.find('bash "$SRC/install-node.sh"')
    check("[2] %s: the node's drop-in is written before install-node.sh starts swg-noded" % label, 0 < i_nc < i_in, (i_nc, i_in))

# ── [3] the node's client DNS ────────────────────────────────────────────────────────────────────────────────────
for label, blk in (("node convert", node_blk), ("a master's node phase", panel_blk)):
    inv = blk[blk.find('bash "$SRC/install-node.sh"') - 400: blk.find('bash "$SRC/install-node.sh"')]
    check("[3] docker → bare (%s): install-node.sh is handed the .env's DNS" % label,
          '${NDNS:+DNS="$NDNS"}' in inv and 'NDNS="$(_dotenv_val DNS "$envf")"' in blk, inv[-260:])
b2d = src[src.find("# ── NODE: bare-metal → docker ──"):]
check("[3] bare → docker (node convert): install-docker.sh is handed the bare config's DNS",
      re.search(r'exec env NODE_TOKEN=.*?\$\{NDNS:\+DNS="\$NDNS"\} (?:SWG_CARRY_ENV="\$_carry" )?bash "\$SRC/install-docker.sh" node', b2d, re.S) is not None)
pb2d = src[src.find('if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then'):pd]
check("[3] bare → docker (a master's node step): install-docker.sh node is handed it too",
      re.search(r'TLS_VERIFY=no \$\{NDNS:\+DNS="\$NDNS"\} \\\n\s+(?:SWG_CARRY_ENV="\$_carry" )?bash "\$SRC/install-docker.sh" node', pb2d) is not None)
m = re.search(r"(?s)(  read -r NTOK PURL NVERIFY NEP NFP NDNS <<EOF\n.*?\n  \[ \"\$NDNS\" = \"-\" \] && NDNS=\"\"; _dns_ok \"\$NDNS\" \|\| NDNS=\"\".*?\n)", b2d)
check("[3] the bare config's DNS is read by the convert's own snippet", m is not None)
if m:
    for dns, want in ((["9.9.9.9"], "9.9.9.9"), ([], ""), (["1.1.1.1, 8.8.8.8"], "1.1.1.1, 8.8.8.8"), (['8.8.8.8"],"x'], "")):
        cfg = os.path.join(T, "cfg-%d.json" % len(want)); json.dump({"panel": {"url": "https://p:1", "token": "t" * 20}, "dns": dns}, open(cfg, "w"))
        script = 'set -euo pipefail\n%s\ncfg="%s"\n%s\necho "NDNS=[$NDNS]"' % (fn("_dns_ok"), cfg, m.group(1))
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        check("[3] bare config dns %s → carried %r" % (json.dumps(dns), want), r.returncode == 0 and "NDNS=[%s]" % want in r.stdout,
              (r.returncode, r.stdout, r.stderr[-200:]))

# ── [4] install-node.sh writes the DNS it is given ──────────────────────────────────────────────────────────────
S = os.path.join(T, "src")
shutil.copytree(ROOT, S, ignore=shutil.ignore_patterns(".git", "dryrun", "node_modules", "*.png", "scratchpad", "docs",
                                                       ".campaign", "__pycache__", "forks", "screenshots", ".claude"))
env = dict(os.environ, DNS="9.9.9.9", PANEL_URL="https://192.168.77.1:2087", NODE_TOKEN="R20dryDummyToken00000000",
           TLS_VERIFY="no", ENDPOINT_IP="192.168.77.2")
r = subprocess.run(["bash", "install-node.sh", "--dry-run"], cwd=S, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                   text=True, timeout=300, start_new_session=True)
cfgp = os.path.join(S, "dryrun", "etc", "swg-agent", "config.json")
try:
    got = json.load(open(cfgp)).get("dns")
except Exception as e:
    got = repr(e)
check("[4] install-node.sh (dry run) writes the DNS it is handed into the node's config", got == ["9.9.9.9"], (got, r.stdout[-400:]))

# ── [5] carry_dropins_to_env ─────────────────────────────────────────────────────────────────────────────────────
DFUNCS = "DROPIN_GIVE=\"\"\n" + fn("carry_dropins_to_env")
assert DFUNCS.count('"/etc/systemd/system/%s.service.d/*.conf" % unit') == 1 and DFUNCS.count('park="/etc/swg-panel-dropins.converted-') == 1, \
    "carry_dropins_to_env's paths are not where this gate roots them — this run would FALSE-PASS"


def dropins(label, files, *units):
    root = os.path.join(T, "d-" + label); sd = os.path.join(root, "sd"); os.makedirs(sd)
    for rel, body in files.items():
        q = os.path.join(sd, rel); os.makedirs(os.path.dirname(q), exist_ok=True); open(q, "w").write(body)
    park = os.path.join(root, "park")
    body = DFUNCS.replace('"/etc/systemd/system/%s.service.d/*.conf" % unit', '"%s/%%s.service.d/*.conf" %% unit' % sd) \
                 .replace('park="/etc/swg-panel-dropins.converted-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo bak)"', 'park="%s"' % park)
    carryf = os.path.join(root, "carry")
    script = ('set -euo pipefail\nsub(){ echo "SUB $*"; }; b(){ printf %%s "$*"; }\n%s\ncarry_dropins_to_env "%s" %s\n'
              'echo "GIVE=[$DROPIN_GIVE]"\n' % (body, carryf, " ".join(units)))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return r, (open(carryf).read() if os.path.exists(carryf) else None), park, sd


URLD = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/dev/VERSION"
LATEST = "[Service]\nEnvironment=SWG_LATEST_URL=%s \"OPS_NOTE=keep me\"\nNice=5\n" % URLD
r, carried, park, sd = dropins("a", {"swg-panel-server.service.d/latest.conf": LATEST}, "swg-panel-server")
check("[5a] SWG_LATEST_URL from an operator's drop-in → the carry file, as the .env reads it",
      r.returncode == 0 and carried == "SWG_LATEST_URL='%s'\n" % URLD, (r.returncode, carried, r.stderr[-300:]))
pf = os.path.join(park, "swg-panel-server.service.d", "latest.conf")
check("[5a] …the drop-in is kept byte for byte in the parking place (dir 0700, file 0600)",
      os.path.exists(pf) and open(pf).read() == LATEST and stat.S_IMODE(os.stat(park).st_mode) == 0o700
      and stat.S_IMODE(os.stat(pf).st_mode) == 0o600, os.listdir(park) if os.path.isdir(park) else "no park dir")
subs = [l for l in r.stdout.splitlines() if l.startswith("SUB ")]
check("[5a] …and ONE line says what was kept, what was not (the other variable, the other directive) and where it is",
      len(subs) == 1 and "SWG_LATEST_URL" in subs[0] and "OPS_NOTE (latest.conf)" in subs[0] and "Nice= (latest.conf)" in subs[0]
      and park in subs[0], subs)
r, carried, park, sd = dropins("b", {"swg-panel-server.service.d/a.conf": "[Service]\nEnvironment=SWG_LATEST_URL=https://x/100%%25/V\n",
                                     "swg-panel-server.service.d/b.conf": "[Service]\nEnvironment=SWG_LATEST_URL=https://old/V\nEnvironment=\n"},
                               "swg-panel-server")
check("[5b] %% is read as % (a specifier escape in a unit); an empty Environment= resets the file's earlier values",
      carried == "SWG_LATEST_URL='https://x/100%25/V'\n", carried)
MIR = "https://ghproxy.example/ https://mirror2.example/gh/"
r, carried, park, sd = dropins("c", {"swg-noded.service.d/mirror.conf": "[Service]\nEnvironment=\"SWG_TURN_MIRROR=%s\"\n" % MIR,
                                     "swg-noded.service.d/10-swg-reach-sweep.conf": "[Service]\nExecStartPre=/x\n",
                                     "swg-panel-server.service.d/zz-swg-update.conf": "[Service]\nEnvironment=SWG_UPDATE_TRIGGER=/y\n",
                                     "swg-panel-server.service.d/50-swg-from-docker.conf": "[Service]\nEnvironment=\"SWG_LATEST_URL=%s\"\n" % URLD},
                               "swg-panel-server", "swg-noded")
check("[5c] SWG_TURN_MIRROR (two prefixes) from swg-noded's drop-in, whole; 50-swg-from-docker.conf's SWG_LATEST_URL too",
      carried is not None and "SWG_TURN_MIRROR='%s'\n" % MIR in carried and "SWG_LATEST_URL='%s'\n" % URLD in carried, carried)
parked = sorted(os.path.relpath(os.path.join(dp, f), park) for dp, _, fs in os.walk(park) for f in fs) if os.path.isdir(park) else []
check("[5c] …our own drop-ins are neither read nor parked — 50-swg-from-docker.conf is read, not parked",
      parked == ["swg-noded.service.d/mirror.conf"] and "SWG_UPDATE_TRIGGER" not in r.stdout and "ExecStartPre" not in r.stdout,
      (parked, r.stdout))
r, carried, park, sd = dropins("c2", {"swg-panel-server.service.d/50-swg-from-docker.conf": "[Service]\nEnvironment=\"SWG_LATEST_URL=%s\"\n" % URLD},
                               "swg-panel-server", "swg-noded")
check("[5c] a Docker → bare → Docker trip (only our own file there): its value carried, NO parking directory, the line names no copy",
      carried == "SWG_LATEST_URL='%s'\n" % URLD and not os.path.exists(park) and "SWG_LATEST_URL" in r.stdout and "kept as they were" not in r.stdout,
      (carried, os.path.exists(park), r.stdout))
r, carried, park, sd = dropins("d", {"swg-panel-server.service.d/console.conf":
                                     "[Service]\nEnvironment=SWG_PANEL_CONSOLE_PORT=8446 SWG_PANEL_CONSOLE_HOST=0.0.0.0\n"},
                               "swg-panel-server")
check("[5d] the console's port / host → given to install-docker.sh as CONSOLE_PORT / CONSOLE_BIND",
      "GIVE=[CONSOLE_PORT=8446 CONSOLE_BIND=0.0.0.0]" in r.stdout and carried == "", (r.stdout, carried))
r, carried, park, sd = dropins("d2", {"swg-panel-server.service.d/odd.conf":
                                      "[Service]\nEnvironment=\"SWG_PANEL_CONSOLE_HOST=1.2.3.4;touch /tmp/x\"\n"
                                      "Environment=\"SWG_LATEST_URL=https://x/it's\"\n"},
                               "swg-panel-server")
check("[5d] …a host that is not a plain address, a value with a quote: named, not carried",
      "GIVE=[]" in r.stdout and carried == "" and "SWG_PANEL_CONSOLE_HOST: not a plain value" in r.stdout
      and "SWG_LATEST_URL: a quote the .env cannot hold" in r.stdout, (r.stdout, carried))
r, carried, park, sd = dropins("e", {"swg-panel-server.service.d/latest.conf": LATEST}, "swg-noded")
check("[5e] a node convert reads swg-noded's drop-ins only (a panel drop-in on that box is not carried)",
      carried == "" and "SUB " not in r.stdout and not os.path.exists(park), (carried, r.stdout))
r, carried, park, sd = dropins("e2", {}, "swg-panel-server", "swg-noded")
check("[5e] no drop-ins: nothing carried, nothing said, nothing parked",
      r.returncode == 0 and carried == "" and "SUB " not in r.stdout and not os.path.exists(park), (r.returncode, r.stdout))

# ── [6] install-docker.sh takes the carry file ───────────────────────────────────────────────────────────────────
a = dsrc.find('if [ -n "${SWG_CARRY_ENV:-}" ] && [ -s "$SWG_CARRY_ENV" ]; then\n')
if a < 0:
    a = dsrc.find("if false; then\n", dsrc.find("# …then what the BARE services this box is leaving held"))
blk6 = dsrc[a:dsrc.index("\nfi\n", a) + 4]
d6 = os.path.join(T, "d6"); os.makedirs(d6)
open(os.path.join(d6, ".env"), "w").write("# generated\nPANEL_DOMAIN=x\nDNS=1.1.1.1\nSWG_LATEST_URL=https://kept-from-the-previous-env/V\n")
open(os.path.join(d6, "carry"), "w").write("SWG_LATEST_URL='%s'\nSWG_TURN_MIRROR='%s'\n" % (URLD, MIR))
r = subprocess.run(["bash", "-c", 'set -euo pipefail\nPREFIX=""; INSTALL_DIR="%s"; SWG_CARRY_ENV="%s/carry"\n%s' % (d6, d6, blk6)],
                   capture_output=True, text=True, timeout=60)
envt = open(os.path.join(d6, ".env")).read()
check("[6] the carried keys land in the .env under their own heading, byte for byte",
      "# ───────── kept from the bare-metal drop-ins this box was converted from ─────────\nSWG_TURN_MIRROR='%s'\n" % MIR in envt,
      (r.returncode, envt, r.stderr[-200:]))
check("[6] …a key the file already has is never written twice", envt.count("SWG_LATEST_URL=") == 1, envt)

# ── [7] the call sites ───────────────────────────────────────────────────────────────────────────────────────────
pb = src.find('if { [ "$ROLE" = host ] || [ "$ROLE" = master ]; } && [ "$FROM" = baremetal ] && [ "$TO" = docker ]; then')
nb = src.find("# ── NODE: bare-metal → docker ──")
assert 0 < pb and 0 < nb, "the bare → docker blocks are not where this gate reads them — this run would FALSE-PASS"
pblk = src[pb:src.find("\nfi\n", pb)]
nblk = src[nb:src.find('\ndie "unsupported conversion', nb)]
i_c = pblk.find('if [ "$ROLE" = master ]; then carry_dropins_to_env "$_carry" swg-panel-server swg-noded; else carry_dropins_to_env "$_carry" swg-panel-server; fi')
i_h = pblk.find('SWG_CARRY_ENV="$_carry" $DROPIN_GIVE bash "$SRC/install-docker.sh" host\n')
i_m = pblk.find('SWG_CARRY_ENV="$_carry" $DROPIN_GIVE bash "$SRC/install-docker.sh" host \\\n')
i_n = pblk.find('SWG_CARRY_ENV="$_carry" bash "$SRC/install-docker.sh" node')
check("[7] host / master convert: the panel's (and a master's node's) drop-ins are read before either hand-off",
      0 < i_c < i_h and i_c < i_m, (i_c, i_h, i_m))
check("[7] …the host exec and the master's host step get the carry file and the given values; the master's node step the file",
      i_h > 0 and i_m > 0 and i_n > i_m, (i_h, i_m, i_n))
i_nc = nblk.find('carry_dropins_to_env "$_carry" swg-noded')
i_ne = nblk.find('SWG_CARRY_ENV="$_carry" bash "$SRC/install-docker.sh" node')
check("[7] node convert: swg-noded's drop-ins are read before the hand-off, which gets the carry file", 0 < i_nc < i_ne, (i_nc, i_ne))

print()
shutil.rmtree(T, ignore_errors=True)
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
