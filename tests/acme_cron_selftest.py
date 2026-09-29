#!/usr/bin/env python3
"""Self-test — A BARE PANEL'S LET'S ENCRYPT CERTIFICATE HAS A RENEWER: cron, AND acme.sh's DAILY ENTRY (round 12b).

acme.sh's daily cron entry (`acme.sh --cron --home /root/.acme.sh`) is the only thing that renews a bare panel's Let's
Encrypt certificate — the panel's 6-hourly sync-acme copies a renewed one in and never renews it. On a box without cron
(Debian cloud images, "minimal" VPS templates) that entry never existed: acme.sh's installer refuses to install without
crontab, so a convert or re-install kept a certificate nothing renewed, and update.sh's heal could not install acme.sh
either. A domain's certificate died within 90 days, an IP's within a week — then browsers refused the panel, nodes that
verify it stopped syncing and subscription pages failed.

Every function is lifted from the shipped scripts and run under `set -euo pipefail`, with apt-get / systemctl / crontab /
acme.sh stubbed on a PATH that has no real crontab (the stub acme.sh installer refuses without crontab, as 3.1.4 does):
  [1] ensure_acme_cron (lib/common.sh): cron missing → apt index refreshed, then cron installed, its unit enabled and
      started, and acme.sh's entry re-registered (--install-cronjob --home <home>) — one line says so; cron AND entry
      present → nothing at all (no apt, no systemctl, no acme.sh, no output); cron present, entry missing → the entry
      re-registered; an entry in /etc/cron.d counts, a commented-out one does not; a failed install (apt's error, or no
      apt-get at all) → the clear warning (the certificate will NOT renew, and the fix), never fatal; a unit that does not
      start → said; an entry acme.sh could not add → said; a dry run says it WOULD install cron / register the entry and
      runs nothing
  [2] install-host.sh: ensure_acme installs cron BEFORE acme.sh (whose installer then registers the entry itself), and on
      a box that has acme.sh re-registers a missing entry; ensure_renewer_for_reuse (a re-install / convert keeping its
      certificate) does the same; a TLS type that uses no acme.sh touches nothing; a dry run says what it would do
  [3] update.sh: ensure_acme_renewal on a bare panel with acme.sh: cron + entry, DID_UPDATE and one summary note; where
      acme.sh is missing but TLS_MODE needs it: cron, so ensure_acme_client right after it can install acme.sh; a PARKED
      bare panel (the Docker panel beside it renews in its container), a TLS type without acme.sh, a box already renewing
      → nothing; it runs in the bare panel's heal pass, before ensure_acme_client
  [4] nothing else calls it: not install-docker, install-node, uninstall, bootstrap, nix/, docker/; a Docker → bare
      convert reaches it through install-host.sh; the three scripts that do refuse to run on NixOS
  [5] CHANGELOG.md and CHANGELOG.ru.md say it

Run: python3 tests/acme_cron_selftest.py        (0 = pass)
     --perturb   nine plants, each on its own — each must turn its own check red
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FILES = (("COMMON", "lib/common.sh"), ("HOST", "install-host.sh"), ("UPDATE", "update.sh"))
PATHS = {k: os.environ.get("SWG_AC_" + k) or os.path.join(ROOT, f) for k, f in FILES}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("apt", "COMMON", "aerr=\"$( { apt-get update -qq || true; apt-get install -y cron; } 2>&1 >/dev/null | grep -E '^E: ' | tail -n 1 || true)\"",
     'aerr=""', "[1] cron missing → the apt index refreshed, then cron installed"),
    ("enable", "COMMON", "    systemctl enable --now cron >/dev/null 2>&1 \\\n", "    true \\\n",
     "[1] …its unit enabled and started"),
    ("entry", "COMMON", '    "$a" --install-cronjob --home "$home" >/dev/null 2>&1 || true\n', "    true\n",
     "[1] cron present, entry missing → the entry re-registered"),
    ("warn", "COMMON", "      warn \"cron is missing and could not be installed${aerr:+ ($aerr)}", "      : \"cron is missing and could not be installed${aerr:+ ($aerr)}",
     "[1] a failed install → the clear warning: the certificate will NOT renew, and the fix"),
    ("first", "HOST", "  ensure_acme_cron   # cron FIRST: acme.sh's installer refuses to install without crontab", "  :   # cron FIRST: acme.sh's installer refuses to install without crontab",
     "[2] a fresh install: cron BEFORE acme.sh, whose installer then registers its entry"),
    ("found", "HOST", '    ensure_acme_cron "$ACME" "$ACME_HOME"   # cron + acme.sh\'s renewal entry: the ONLY renewer', "    :   # cron + acme.sh's renewal entry: the ONLY renewer",
     "[2] a box that has acme.sh and no cron: cron installed and the entry re-registered"),
    ("reuse", "HOST", '      find_acme && { ensure_acme_cron "$ACME" "$ACME_HOME"; return 0; }\n', "      find_acme && return 0\n",
     "[2] a re-install keeping its certificate (reuse): the missing entry re-registered"),
    ("heal", "UPDATE", "  ensure_acme_renewal    # HEAL: cron + acme.sh's daily renewal entry", "  :                      # HEAL: cron + acme.sh's daily renewal entry",
     "[3] it runs in the bare panel's heal pass, before ensure_acme_client"),
    ("parked", "UPDATE", "  bare_panel_parked && return 0\n  local conf=", "  local conf=",
     "[3] a PARKED bare panel (a Docker panel beside it renews in its container) → nothing"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-7s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_AC_" + key: f.name}), capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-7s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:900]) if detail and not ok else ""), flush=True)
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

# ── the sandbox: a PATH with no real crontab, and stubs that behave like the real tools ──────────────────────────────
CRONTAB_STUB = r'''#!/bin/bash
echo "crontab $*" >> "$LOG"
case "${1:-}" in
  -l) if [ -f "$CRONTAB_FILE" ]; then cat "$CRONTAB_FILE"; exit 0; fi; echo "no crontab for root" >&2; exit 1;;
  -)  cat > "$CRONTAB_FILE"; exit 0;;
esac
exit 0
'''
APT_STUB = r'''#!/bin/bash
echo "apt-get $*" >> "$LOG"
case "$*" in
  "update -qq") exit "${APT_UPDATE_RC:-0}";;
  "install -y cron")
    if [ -n "${APT_FAIL:-}" ]; then echo "Reading package lists..."; echo "E: Unable to locate package cron" >&2; exit 100; fi
    cp "$STUBS/crontab.tmpl" "$BIN/crontab"; chmod 755 "$BIN/crontab"; exit 0;;
esac
exit 0
'''
SYSTEMCTL_STUB = r'''#!/bin/bash
echo "systemctl $*" >> "$LOG"
case "$*" in
  "enable --now cron") exit "${CRON_UNIT_RC:-0}";;
  "is-enabled --quiet swg-panel-server") exit "${PANEL_ENABLED_RC:-0}";;
  "is-active --quiet swg-panel-server") exit "${PANEL_ACTIVE_RC:-0}";;
esac
exit 0
'''
# acme.sh 3.1.4's installcronjob: no crontab → refuse; else add `acme.sh --cron` unless a line already has it
ACME_STUB = r'''#!/bin/bash
echo "acme $*" >> "$LOG"
home=""; prev=""; for x in "$@"; do [ "$prev" = --home ] && home="$x"; prev="$x"; done
case " $* " in
  *" --version "*) echo "https://github.com/acmesh-official/acme.sh"; echo "v3.1.4"; exit 0;;
  *" --install-cronjob "*)
    command -v crontab >/dev/null 2>&1 || { echo "crontab/fcrontab doesn't exist, so we cannot install cron jobs." >&2; exit 1; }
    [ -n "${ACME_NOADD:-}" ] && exit 0
    cur="$(crontab -l 2>/dev/null || true)"
    printf '%s\n' "$cur" | grep -c "acme.sh --cron" >/dev/null && exit 0
    { [ -n "$cur" ] && printf '%s\n' "$cur"; echo "17 3,9,15,21 * * * \"${home:-/root/.acme.sh}\"/acme.sh --cron --home \"${home:-/root/.acme.sh}\" > /dev/null"; } | crontab -
    exit 0;;
esac
exit 0
'''
TOOLS = ("bash", "sh", "cat", "grep", "tail", "sed", "sort", "chmod", "mkdir", "cp", "rm", "env", "printf")

def sandbox(cron=False, entry=None, sysentry=None, acme=True, apt=True):
    """A fresh world. cron: crontab already installed; entry: root's crontab text (None = no crontab file);
    sysentry: /etc/cron.d/acme text; acme: an acme.sh at <T>/root/.acme.sh/acme.sh; apt: apt-get on PATH."""
    t = tempfile.mkdtemp(prefix="acmecron-")
    b, s = os.path.join(t, "bin"), os.path.join(t, "stubs")
    for d in (b, s, os.path.join(t, "etc", "cron.d"), os.path.join(t, "home"), os.path.join(t, "root", ".acme.sh")):
        os.makedirs(d)
    for tool in TOOLS:
        w = shutil.which(tool)
        if w:
            os.symlink(w, os.path.join(b, tool))
    def put(path, text):
        open(path, "w").write(text); os.chmod(path, 0o755)
    put(os.path.join(s, "crontab.tmpl"), CRONTAB_STUB)
    put(os.path.join(b, "systemctl"), SYSTEMCTL_STUB)
    if apt:
        put(os.path.join(b, "apt-get"), APT_STUB)
    if cron:
        put(os.path.join(b, "crontab"), CRONTAB_STUB)
    if entry is not None:
        open(os.path.join(t, "crontab.root"), "w").write(entry)
    if sysentry is not None:
        open(os.path.join(t, "etc", "cron.d", "acme"), "w").write(sysentry)
    if acme:
        put(os.path.join(t, "root", ".acme.sh", "acme.sh"), ACME_STUB)
    return t

def world(t):
    return os.path.join(t, "root", ".acme.sh", "acme.sh")

def lib_fns(t):
    C = SRC["COMMON"]
    ent = fn(C, "acme_cron_entry").replace("/etc/crontab /etc/cron.d/*", "%s/etc/crontab %s/etc/cron.d/*" % (t, t))
    assert ent != fn(C, "acme_cron_entry"), "acme_cron_entry no longer reads /etc/crontab /etc/cron.d/* — re-anchor the sandbox"
    return fn(C, "ensure_acme_cron") + ent

def run(t, body, dry=False, **env):
    script = ("set -euo pipefail\nDRYRUN=%s\ninfo(){ echo \"INFO $*\"; }\nok(){ echo \"OK $*\"; }\nwarn(){ echo \"WARN $*\"; }\n"
              "note(){ echo \"NOTE $*\"; }\ndie(){ echo \"DIE $*\"; exit 1; }\n%s\necho END\n") % ("true" if dry else "false", body)
    e = {"PATH": os.path.join(t, "bin"), "LOG": os.path.join(t, "log"), "CRONTAB_FILE": os.path.join(t, "crontab.root"),
         "BIN": os.path.join(t, "bin"), "STUBS": os.path.join(t, "stubs"), "HOME": os.path.join(t, "home")}
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run([shutil.which("bash"), "-c", script], capture_output=True, text=True, env=e, timeout=60)
    log = open(e["LOG"]).read() if os.path.exists(e["LOG"]) else ""
    tab = open(e["CRONTAB_FILE"]).read() if os.path.exists(e["CRONTAB_FILE"]) else ""
    return r.returncode, r.stdout + r.stderr, log, tab

def entries(tab):
    return [l for l in tab.splitlines() if "acme.sh --cron" in l and not l.lstrip().startswith("#")]

# ── [1] ensure_acme_cron ──────────────────────────────────────────────────────────────────────────────────────────────
print("[1] ensure_acme_cron (lib/common.sh), driven")
t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\necho "DID=[$ACME_CRON_DID]"\n' % world(t))
calls = log.splitlines()
i_upd = calls.index("apt-get update -qq") if "apt-get update -qq" in calls else -1
i_ins = calls.index("apt-get install -y cron") if "apt-get install -y cron" in calls else -1
check("[1] cron missing → the apt index refreshed, then cron installed", rc == 0 and 0 <= i_upd < i_ins and "END" in out, (rc, out, log))
check("[1] …its unit enabled and started", "systemctl enable --now cron" in calls and calls.index("systemctl enable --now cron") > i_ins, log)
check("[1] …and acme.sh's entry re-registered (--install-cronjob --home /root/.acme.sh): one entry, the home pinned",
      "acme --install-cronjob --home /root/.acme.sh" in calls and len(entries(tab)) == 1 and '--home "/root/.acme.sh"' in entries(tab)[0], (log, tab))
said = [l for l in out.splitlines() if l.startswith(("OK ", "WARN "))]
check("[1] …and one line says so (the certificate renews on its own again), the run carries on",
      said == ["OK cron installed and acme.sh's daily renewal entry registered — the certificate renews on its own again"]
      and "DID=[cron installed + renewal entry registered]" in out, out)

t = sandbox(cron=True, entry="17 3,9,15,21 * * * \"/root/.acme.sh\"/acme.sh --cron --home \"/root/.acme.sh\" > /dev/null\n", acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\necho "DID=[$ACME_CRON_DID]"\n' % world(t))
check("[1] cron AND entry present → nothing: no apt, no systemctl, no acme.sh, not a line of output",
      rc == 0 and not [c for c in log.splitlines() if not c.startswith("crontab -l")] and out.strip() == "DID=[]\nEND", (rc, out, log))

t = sandbox(cron=True, entry="# m h dom mon dow command\n0 4 * * * /usr/local/bin/backup\n", acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\necho "DID=[$ACME_CRON_DID]"\n' % world(t))
check("[1] cron present, entry missing → the entry re-registered",
      rc == 0 and "acme --install-cronjob --home /root/.acme.sh" in log and len(entries(tab)) == 1 and "/usr/local/bin/backup" in tab
      and "apt-get" not in log and "systemctl" not in log and "DID=[renewal entry registered]" in out, (rc, out, log, tab))
check("[1] …said in one line", [l for l in out.splitlines() if l.startswith(("OK ", "WARN ", "INFO "))]
      == ["OK acme.sh's daily renewal entry was missing from root's crontab — registered; the certificate renews on its own again"], out)

t = sandbox(cron=True, entry="", sysentry="17 3 * * * root \"/root/.acme.sh\"/acme.sh --cron --home \"/root/.acme.sh\" > /dev/null\n", acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\n' % world(t))
check("[1] an entry in /etc/cron.d counts — no second one is added", rc == 0 and "install-cronjob" not in log and not entries(tab), (out, log, tab))
t = sandbox(cron=True, entry="#17 3 * * * \"/root/.acme.sh\"/acme.sh --cron --home \"/root/.acme.sh\" > /dev/null\n", acme=True,)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\n' % world(t), ACME_NOADD=1)
check("[1] a commented-out entry does not count — and when acme.sh adds none beside it, that is said: will NOT renew, and the fix",
      rc == 0 and "acme --install-cronjob --home /root/.acme.sh" in log and "END" in out
      and "WARN acme.sh's renewal entry is not in root's crontab and could not be added — the certificate will NOT renew on its own. Fix: %s --install-cronjob --home /root/.acme.sh" % world(t) in out, (out, log))

t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\necho "DID=[$ACME_CRON_DID]"\n' % world(t), APT_FAIL=1)
warns = [l for l in out.splitlines() if l.startswith("WARN ")]
check("[1] a failed install → the clear warning: the certificate will NOT renew, and the fix",
      rc == 0 and "END" in out and len(warns) == 1 and "cron is missing and could not be installed (E: Unable to locate package cron)" in warns[0]
      and "will NOT renew" in warns[0] and "Fix: apt-get install cron && systemctl enable --now cron, then %s --install-cronjob --home /root/.acme.sh" % world(t) in warns[0]
      and "systemctl" not in log and "acme " not in log and "DID=[]" in out, (rc, out, log))
t = sandbox(cron=False, acme=False, apt=False)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron\n')
check("[1] no apt-get at all → the same warning, naming why, and never fatal",
      rc == 0 and "END" in out and "WARN cron is missing and could not be installed (no apt-get on this system) — the panel's Let's Encrypt certificate will NOT renew" in out
      and "Fix: apt-get install cron && systemctl enable --now cron" in out and ", then " not in out.split("Fix:")[1], (rc, out, log))
t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\n' % world(t), CRON_UNIT_RC=1)
check("[1] a cron unit that does not start → said, and the entry is still registered",
      rc == 0 and "WARN cron is installed but did not start — acme.sh's renewals need it running: systemctl enable --now cron" in out
      and len(entries(tab)) == 1, (out, log, tab))

t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\n' % world(t), dry=True)
check("[1] a dry run, cron missing: says it WOULD install cron, and runs nothing",
      rc == 0 and "[skip] would install cron (apt-get install cron, then enable and start it)" in out and log == "" and not tab, (out, log))
t = sandbox(cron=True, entry="", acme=True)
rc, out, log, tab = run(t, lib_fns(t) + 'ensure_acme_cron %s /root/.acme.sh\n' % world(t), dry=True)
check("[1] a dry run, entry missing: says it WOULD register the entry, and registers nothing",
      rc == 0 and "[skip] would register acme.sh's daily renewal entry in root's crontab (%s --install-cronjob --home /root/.acme.sh)" % world(t) in out
      and "install-cronjob" not in log and not entries(tab), (out, log))

# ── [2] install-host.sh ──────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] install-host.sh: ensure_acme and ensure_renewer_for_reuse, driven")
H = SRC["HOST"]
def host_fns(t):
    fa = fn(H, "find_acme").replace("/root/.acme.sh/acme.sh", world(t))
    assert fa != fn(H, "find_acme"), "find_acme no longer searches /root/.acme.sh/acme.sh — re-anchor the sandbox"
    # the piped get.acme.sh: acme.sh 3.1.4's installer refuses without crontab (and get.acme.sh still exits 0 — its
    # `if ! … | sh -s …; then echo "Install error"; fi`), and registers the entry itself where crontab is
    run_ = ('run(){ if $DRYRUN; then echo "    [skip] $*"; return 0; fi\n'
            '  if [ "$1" = sh ]; then echo "RUN get.acme.sh" >> "$LOG"\n'
            '    command -v crontab >/dev/null 2>&1 || { echo "It is recommended to install crontab first. Pre-check failed, cannot install." >&2; echo "Install error"; return 0; }\n'
            '    cp "$STUBS/acme.tmpl" "%s"; chmod 755 "%s"; "%s" --install-cronjob --home /root/.acme.sh >/dev/null; return 0; fi\n'
            '  "$@"; }\n') % (world(t), world(t), world(t))
    return (lib_fns(t) + run_ + "ACME_HOME=/root/.acme.sh\nACME_MIN=3.1.4\nACME_EMAIL=\nPANEL_DOMAIN=panel.example.com\n"
            + fa + fn(H, "acme") + fn(H, "acme_version") + fn(H, "ensure_acme") + fn(H, "ensure_renewer_for_reuse"))

def host_world(**kw):
    t = sandbox(**kw)
    open(os.path.join(t, "stubs", "acme.tmpl"), "w").write(ACME_STUB)   # what the piped installer lays down
    return t

t = host_world(cron=False, acme=False)
rc, out, log, tab = run(t, host_fns(t) + "ensure_acme\necho \"ACME=$ACME\"\n")
calls = log.splitlines()
check("[2] a fresh install: cron BEFORE acme.sh, whose installer then registers its entry",
      rc == 0 and "apt-get install -y cron" in calls and "RUN get.acme.sh" in calls
      and calls.index("apt-get install -y cron") < calls.index("RUN get.acme.sh") and len(entries(tab)) == 1
      and "ACME=%s" % world(t) in out, (rc, out, log, tab))
check("[2] …and no second registration after it (the installer's own entry is found)",
      [c for c in calls if "install-cronjob" in c] == ["acme --install-cronjob --home /root/.acme.sh"], log)

t = host_world(cron=False, acme=True)
rc, out, log, tab = run(t, host_fns(t) + "ensure_acme\n")
check("[2] a box that has acme.sh and no cron: cron installed and the entry re-registered",
      rc == 0 and "apt-get install -y cron" in log and "acme --install-cronjob --home /root/.acme.sh" in log and len(entries(tab)) == 1
      and "RUN get.acme.sh" not in log and "cron installed and acme.sh's daily renewal entry registered" in out, (rc, out, log, tab))

t = host_world(cron=True, entry="", acme=True)
rc, out, log, tab = run(t, host_fns(t) + "TLS_MODE=letsencrypt-ip\nensure_renewer_for_reuse\n")
check("[2] a re-install keeping its certificate (reuse): the missing entry re-registered",
      rc == 0 and "acme --install-cronjob --home /root/.acme.sh" in log and len(entries(tab)) == 1 and "apt-get" not in log, (rc, out, log, tab))
t = host_world(cron=False, acme=False)
rc, out, log, tab = run(t, host_fns(t) + "TLS_MODE=letsencrypt\nensure_renewer_for_reuse\n")
check("[2] …and one with no acme.sh (a Docker → bare convert brings the state, not the program): cron, then acme.sh, then its entry",
      rc == 0 and "END" in out and log.find("apt-get install -y cron") < log.find("RUN get.acme.sh") and log.find("apt-get install -y cron") >= 0
      and len(entries(tab)) == 1 and "acme.sh isn't installed" not in out, (rc, out, log, tab))
t = host_world(cron=False, acme=True)
rc, out, log, tab = run(t, host_fns(t) + "TLS_MODE=selfsigned\nensure_renewer_for_reuse\nTLS_MODE=cf15\nensure_renewer_for_reuse\n")
check("[2] a TLS type that uses no acme.sh touches nothing", rc == 0 and log == "" and out.strip() == "END", (out, log))
t = host_world(cron=False, acme=False)
rc, out, log, tab = run(t, host_fns(t) + "ensure_acme\n", dry=True)
check("[2] a dry run says it WOULD install cron, then shows the acme.sh install it would run — and runs neither",
      rc == 0 and out.find("[skip] would install cron") >= 0 and out.find("[skip] would install cron") < out.find("[skip] sh -c curl -fsSL https://get.acme.sh")
      and log == "", (out, log))

# ── [3] update.sh ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] update.sh: ensure_acme_renewal, driven")
U, C = SRC["UPDATE"], SRC["COMMON"]
def upd_fns(t, mode):
    er = fn(U, "ensure_acme_renewal").replace("/root/.acme.sh/acme.sh", world(t))
    assert er != fn(U, "ensure_acme_renewal"), "ensure_acme_renewal no longer looks at /root/.acme.sh/acme.sh — re-anchor the sandbox"
    conf = os.path.join(t, "install.conf"); open(conf, "w").write("PANEL_DOMAIN=panel.example.com\nTLS_MODE=%s\n" % mode)
    return (lib_fns(t) + fn(C, "bare_panel_parked") + fn(C, "docker_parked") + fn(C, "docker_panel_live")
            + "ETC_DIR=%s\nACME_HOME_CANON=/root/.acme.sh\nDID_UPDATE=no\n" % t + er)
tail_ = 'ensure_acme_renewal\necho "DID_UPDATE=$DID_UPDATE"\n'

t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, upd_fns(t, "letsencrypt") + tail_)
check("[3] a bare panel with acme.sh and no cron: cron installed and the entry re-registered, DID_UPDATE and one summary note",
      rc == 0 and "apt-get install -y cron" in log and "acme --install-cronjob --home /root/.acme.sh" in log and len(entries(tab)) == 1
      and "DID_UPDATE=yes" in out and [l for l in out.splitlines() if l.startswith("NOTE ")] == ["NOTE certificate renewal: cron installed + renewal entry registered"],
      (rc, out, log, tab))
t = sandbox(cron=False, acme=False)
rc, out, log, tab = run(t, upd_fns(t, "letsencrypt-ip") + tail_)
check("[3] acme.sh missing where TLS_MODE needs it: cron — so ensure_acme_client, right after, can install acme.sh",
      rc == 0 and "apt-get install -y cron" in log and "acme " not in log and "NOTE certificate renewal: cron installed" in out, (rc, out, log))
t = sandbox(cron=False, acme=True)
rc, out, log, tab = run(t, upd_fns(t, "letsencrypt") + tail_, PANEL_ENABLED_RC=1, PANEL_ACTIVE_RC=3)
check("[3] a PARKED bare panel (a Docker panel beside it renews in its container) → nothing",
      rc == 0 and "apt-get" not in log and "acme " not in log and "crontab" not in log and "DID_UPDATE=no" in out, (rc, out, log))
t = sandbox(cron=False, acme=False)
rc, out, log, tab = run(t, upd_fns(t, "selfsigned") + tail_)
check("[3] no acme.sh and a TLS type that needs none → nothing", rc == 0 and "apt-get" not in log and "DID_UPDATE=no" in out, (out, log))
t = sandbox(cron=True, entry="5 1 * * * \"/root/.acme.sh\"/acme.sh --cron --home \"/root/.acme.sh\" > /dev/null\n", acme=True)
rc, out, log, tab = run(t, upd_fns(t, "letsencrypt") + tail_)
check("[3] a box already renewing → nothing, not a line, DID_UPDATE untouched",
      rc == 0 and "apt-get" not in log and "install-cronjob" not in log and "DID_UPDATE=no" in out
      and not [l for l in out.splitlines() if l.startswith(("OK ", "INFO ", "WARN ", "NOTE "))], (out, log))

i_bare = U.find('if ! $NODE_ONLY && [ -f "$PANEL_DIR/swg-panel-server" ]; then')
i_node = U.find("# ───────────────────────── bare-metal node daemon", i_bare)
i_heal = U.find("  ensure_acme_renewal    # HEAL: cron + acme.sh's daily renewal entry")
i_client = U.find("  ensure_acme_client     # HEAL: the ACME client itself")
check("[3] it runs in the bare panel's heal pass, before ensure_acme_client",
      0 < i_bare < i_heal < i_client < i_node and U.count("\n  ensure_acme_renewal ") == 1, (i_bare, i_heal, i_client, i_node))

# ── [4] nothing else calls it ────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] where it runs, and where it does not")
others = []
for rel in ("install-docker.sh", "install-node.sh", "uninstall.sh", "bootstrap.sh", "convert.sh"):
    p = os.path.join(ROOT, rel)
    if os.path.exists(p) and re.search(r"ensure_acme_cron|ensure_acme_renewal|install-cronjob", open(p, encoding="utf-8").read()):
        others.append(rel)
for d in ("nix", "docker"):
    for base, _, files in os.walk(os.path.join(ROOT, d)):
        for f in files:
            try:
                if re.search(r"ensure_acme_cron|install-cronjob", open(os.path.join(base, f), encoding="utf-8", errors="replace").read()):
                    others.append(os.path.relpath(os.path.join(base, f), ROOT))
            except OSError:
                pass
check("[4] not install-docker, install-node, uninstall, bootstrap, convert, nix/, docker/ (a Docker panel renews in its container)", not others, others)
def calls_in(src, name):
    """(line number, code) of every line whose CODE — a comment is not a call — names <name>."""
    out = []
    for i, l in enumerate(src.split("\n")):
        code = "" if l.lstrip().startswith("#") else l.split("  #")[0]
        if re.search(r"\b%s\b" % re.escape(name), code):
            out.append((i, code.strip()))
    return out
def body_lines(src, name):
    a = src[:src.index(name + "(){")].count("\n")
    return a, a + fn(src, name).count("\n")
cu = calls_in(U, "ensure_acme_cron"); ua, ub = body_lines(U, "ensure_acme_renewal")
check("[4] update.sh calls it only from ensure_acme_renewal (once)", len(cu) == 1 and ua < cu[0][0] < ub, (cu, ua, ub))
ch = calls_in(H, "ensure_acme_cron"); ea, eb = body_lines(H, "ensure_acme"); ra, rb = body_lines(H, "ensure_renewer_for_reuse")
check("[4] install-host.sh calls it only in ensure_acme (3: acme.sh found, before its install, after it) and ensure_renewer_for_reuse (1)",
      len(ch) == 4 and sum(ea < i < eb for i, _ in ch) == 3 and sum(ra < i < rb for i, _ in ch) == 1, (ch, ea, eb, ra, rb))
CV = open(os.path.join(ROOT, "convert.sh"), encoding="utf-8").read()
check("[4] a Docker → bare convert reaches it through install-host.sh (the reuse path, or a fresh issue)",
      re.search(r'SWG_CONVERT_DIR=convert-bare[^\n]*\\\n(?:[^\n]*\\\n)*\s*bash "\$SRC/install-host.sh"', CV) is not None)
check("[4] install-host.sh, update.sh and convert.sh refuse to run on NixOS (declarative)",
      all("\nrefuse_on_declarative_host '" in s for s in (H, U, CV)))

# ── [5] CHANGELOG ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] the CHANGELOG")
en = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read().split("\n## ")[1]
ru = open(os.path.join(ROOT, "CHANGELOG.ru.md"), encoding="utf-8").read().split("\n## ")[1]
check("[5] CHANGELOG.md's current release says it (cron, Let's Encrypt, renewed)",
      re.search(r"(?i)without cron[^\n]*never renewed[^\n]*Let's Encrypt|Let's Encrypt[^\n]*(?:\n  [^\n]*){0,3}without cron", en) is not None)
check("[5] …and CHANGELOG.ru.md's", re.search(r"cron", ru) is not None and re.search(r"Let's Encrypt", ru) is not None
      and re.search(r"(?i)обновля|продлева", ru) is not None)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
