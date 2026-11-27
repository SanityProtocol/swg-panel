#!/usr/bin/env python3
"""Self-test — MOVING A PANEL FROM ITS IP TO A DOMAIN WITH LET'S ENCRYPT (1.8.12 item 19, a user's report 2026-11-21).

(a) A panel installed with a self-signed certificate (or none, or a Cloudflare Origin one) has no acme.sh: install-host.sh
    installs it only for the modes that issue through it. Moving it to a domain with Let's Encrypt answered "acme.sh not
    found". swg-netctl's issuance now installs it, with install-host.sh ensure_acme's steps for a box without it.
(b) A same-port move from the IP asked Let's Encrypt for "<domain>,<IP>" (the self-signed certificate's CN is the IP), and
    its default profile refuses IP identifiers — the whole order failed. An old IP never joins a CA's order now.

  [1] swg-netctl `_issue_acme` with NO acme.sh, in a sandbox: a PATH holding only stubs (apt-get, systemctl, crontab, curl)
      and the plain tools they use; curl "downloads" a stub get.acme.sh that installs a stub acme.sh into $LE_WORKING_DIR —
      and, as 3.1.4's _precheck does, installs nothing where there is no crontab. Checked: cron (and curl) from apt FIRST,
      then the fetch, the installer, acme.sh's renewal entry, the version floor, and only then the order; the installer
      runs with HOME=/root and LE_WORKING_DIR=<the store>, in a fresh temp dir that is gone afterwards; the Access email,
      and NONE when there is none (1.8.12 item 26: never a made-up admin@<domain>); a bad email refused before anything is fetched; offline → the clear Reject naming the manual
      commands, no installer, no order; an installer that installs nothing → the same; an old acme.sh → --upgrade; an
      acme.sh already there → no install at all; no apt-get → the Reject; a dry run → the argv logged, nothing run, no dir
  [2] swg-netctl `_issue_acme`: an IP literal beside a name is left out of the order; IPs alone are left for the CA
  [3] swg-panel-server `_apply_panel_cert_only`: under a CA mode an old IP (v4, v6, bracketed) is left out and the change is
      armed new-only; an old DNS name is kept; self-signed is unchanged; `_place_cert` waits ≥ 300 s
  [4] the "not found" message names each place once (under root `~` is /root)
  [5] parity with install-host.sh ensure_acme / lib/common.sh ensure_acme_cron: cron before get.acme.sh, the same URL,
      the same email fallback, the same floor; only issuance installs
  [6] CHANGELOG.md and CHANGELOG.ru.md say it

Run: python3 tests/acme_on_demand_selftest.py      (0 = pass)
     --perturb   each fix taken back out must turn ITS OWN check red ("N plants, N caught").
"""
import ast, atexit, contextlib, importlib.machinery, importlib.util, io, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRCS = {"NETCTL": "swg-netctl", "PANEL": "swg-panel-server", "HOST": "install-host.sh", "COMMON": "lib/common.sh"}
PATHS = {k: os.environ.get("SWG_AOD_" + k) or os.path.join(ROOT, v) for k, v in SRCS.items()}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

# (name, file key, anchor, replacement, the check that must go red)
PLANTS = [
    ("install", "NETCTL", '    acme = _locate_acme() or _acme_install(creds["email"])',
     "    acme = find_acme()", "[1] no acme.sh: installed, then the certificate ordered"),
    ("noemail", "NETCTL", '    acme = _locate_acme() or _acme_install(creds["email"])',
     '    acme = _locate_acme() or _acme_install(creds["email"] or "admin@" + domains[0])',
     "[1] no Access / install.conf email: the installer gets none (never a made-up admin@<domain>)"),
    ("cron-first", "NETCTL", "    missing = [pkg for pkg, binary in want if not shutil.which(binary)]\n    if not missing:",
     "    missing = []\n    if not missing:", "[1] the steps in order: cron + curl from apt, the fetch, the installer, the renewal entry, the floor, the order"),
    ("home", "NETCTL", "    env = dict(os.environ, HOME=pwd.getpwuid(0).pw_dir, LE_WORKING_DIR=ACME_HOME)",
     "    env = dict(os.environ)", "[1] the installer runs with HOME=/root and LE_WORKING_DIR=<the store>"),
    ("cwd", "NETCTL", 'rc, out = run(["sh", script] + (["email=" + email] if email else []), env=env, cwd=tmp, timeout=_left(deadline, 180))',
     'rc, out = run(["sh", script] + (["email=" + email] if email else []), env=env, timeout=_left(deadline, 180))',
     "[1] …in a fresh temp dir (installOnline unpacks into its cwd), gone afterwards"),
    ("cleanup", "NETCTL", "        if not DRYRUN:\n            shutil.rmtree(tmp, ignore_errors=True)", "        pass",
     "[1] …in a fresh temp dir (installOnline unpacks into its cwd), gone afterwards"),
    ("cronjob", "NETCTL", '    run(acme_argv(acme, "--install-cronjob"), env=env, timeout=30)\n', "",
     "[1] the steps in order: cron + curl from apt, the fetch, the installer, the renewal entry, the floor, the order"),
    ("floor", "NETCTL", '        if run(acme_argv(acme, "--upgrade"), env=env, timeout=_left(deadline, 180))[0]:', "        if False:",
     "[1] an acme.sh older than 3.1.4 → --upgrade, before the order"),
    ("offline", "NETCTL", "        if rc and not DRYRUN:\n            raise Reject(\"acme.sh is not installed, and its installer could not be downloaded",
     "        if False:\n            raise Reject(\"acme.sh is not installed, and its installer could not be downloaded",
     "[1] offline: the clear Reject (curl's error, the manual commands), no installer, no order"),
    ("email", "NETCTL", '    if email and not _ACME_EMAIL_RE.match(email):', "    if False:",
     "[1] an email with a space or '=' is refused before anything is fetched (get.acme.sh word-splits it)"),
    ("nothing", "NETCTL", '    acme = _locate_acme() or ("/root/.acme.sh/acme.sh" if DRYRUN else None)',
     '    acme = _locate_acme() or "/root/.acme.sh/acme.sh"',
     "[1] an installer that installs nothing (get.acme.sh exits 0 anyway): the Reject, no order"),
    ("dry", "NETCTL", '    tmp = os.path.join(tempfile.gettempdir(), "swg-acme-XXXXXX") if DRYRUN else tempfile.mkdtemp(prefix="swg-acme-")',
     '    tmp = tempfile.mkdtemp(prefix="swg-acme-")', "[1] a dry run: every step's argv logged, nothing run, no temp dir made"),
    ("ip-netctl", "NETCTL", "    if names and len(names) < len(domains):", "    if False:",
     "[2] an IP literal beside a name is left out of the order"),
    ("ip-panel", "PANEL", '        if old_domain and _mode in REAL_CA_MODES and _is_ip(old_domain.strip("[]")):',
     "        if False:", "[3] letsencrypt: an old IPv4 is left out, the change armed new-only"),
    ("wait", "PANEL", 'def _place_cert(deps, service, domain, reload_flag="reload", timeout=600):',
     'def _place_cert(deps, service, domain, reload_flag="reload", timeout=300):', "[3] the panel waits longer than the install can take: its budget + every cap outside it, and 60 s for the order"),
    # verify F4: dpkg is never killed for the budget
    ("dpkg", "NETCTL", 'rc, out = run(["apt-get", "install", "-y"] + missing, env=env, timeout=180)',
     'rc, out = run(["apt-get", "install", "-y"] + missing, env=env, timeout=_left(deadline, 180))',
     "[1] apt-get install is never cut short by the budget (a SIGKILL mid-dpkg breaks apt on the box)"),
    # verify F6: apt spent the budget → say so, not "does this box reach GitHub?"
    ("apt-slow", "NETCTL", "    if deadline - time.monotonic() < ACME_FETCH_MIN and not DRYRUN:", "    if False:",
     "[1] apt spent the budget: the Reject says so and to apply again (cron is in now), no doomed fetch"),
    ("dedupe", "NETCTL", '    return tuple(dict.fromkeys((os.path.join(ACME_HOME, "acme.sh"),) + _ACME_CANDIDATES))',
     '    return (os.path.join(ACME_HOME, "acme.sh"),) + _ACME_CANDIDATES',
     "[4] the message names /root/.acme.sh once (under root `~` is /root)"),
    # review F2: the store the installer was pointed at is where the program is looked for
    ("store", "NETCTL", "    for a in _acme_paths():", "    for a in _ACME_CANDIDATES:",
     "[1] no acme.sh: installed, then the certificate ordered"),
    # review F1: the network steps share one budget, so the panel hears this helper's answer, not its own timeout
    ("budget", "NETCTL", "    deadline = started + ACME_INSTALL_BUDGET\n", "    deadline = started + 10 ** 6\n",
     "[1] the install's network steps share one budget: a slow installer is stopped when it runs out, and the Reject says so"),
]

if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-11s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        d = tempfile.mkdtemp(prefix="aod-plant-")
        f = os.path.join(d, os.path.basename(PATHS[key]))
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(src.replace(old, new))
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_AOD_" + key: f}),
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


SB = tempfile.mkdtemp(prefix="aod-")
atexit.register(shutil.rmtree, SB, True)                    # gone even when a planted copy crashes the run
os.chdir(SB)                                                # a stub that writes into its cwd writes here
os.environ["HOME"] = os.path.join(SB, "user-home")          # nothing a stub writes can reach the real home
os.makedirs(os.environ["HOME"])

# swg-netctl as a module, its state under the sandbox. Loaded with HOME=/root, as the helper runs: `~` is /root there.
os.environ.update(SWG_STATE_DIR=os.path.join(SB, "state"), SWG_ETC_DIR=os.path.join(SB, "etc"),
                  SWG_SUB_TLS_DIR=os.path.join(SB, "sub-tls"), SWG_NETCTL_STATE=os.path.join(SB, "netctl-state"),
                  LE_WORKING_DIR=os.path.join(SB, "acme-home"))
_h = os.environ["HOME"]; os.environ["HOME"] = "/root"
_l = importlib.machinery.SourceFileLoader("netctl_aod", PATHS["NETCTL"])
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("netctl_aod", _l))
_l.exec_module(N)
os.environ["HOME"] = _h
SHIPPED_CANDIDATES, SHIPPED_BUDGET, SHIPPED_FETCH_MIN = N._ACME_CANDIDATES, N.ACME_INSTALL_BUDGET, N.ACME_FETCH_MIN

# ── the sandbox ──────────────────────────────────────────────────────────────────────────────────────────────────────
LOG = os.path.join(SB, "calls.log")
STUBS = os.path.join(SB, "stubs")
os.makedirs(STUBS)
CRONTAB_STUB = r'''#!/bin/sh
echo "crontab $*" >> "$AOD_LOG"
case "${1:-}" in
  -l) if [ -f "$AOD_CRONTAB" ]; then cat "$AOD_CRONTAB"; exit 0; fi; echo "no crontab for root" >&2; exit 1;;
  -)  cat > "$AOD_CRONTAB"; exit 0;;
esac
exit 0
'''
# apt-get installs exactly the stubs it is asked for, or fails the way apt does
APT_STUB = r'''#!/bin/sh
echo "apt-get $* DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-}" >> "$AOD_LOG"
[ "$1" = update ] && { [ -n "${AOD_APT_SLEEP:-}" ] && sleep "$AOD_APT_SLEEP"; exit 0; }
[ -n "${AOD_APT_INSTALL_SLEEP:-}" ] && sleep "$AOD_APT_INSTALL_SLEEP"
if [ -n "${AOD_APT_FAIL:-}" ]; then echo "E: Unable to locate package cron"; exit 100; fi
for p in "$@"; do case "$p" in
  cron) cp "$AOD_STUBS/crontab" "$AOD_BIN/crontab"; chmod 755 "$AOD_BIN/crontab";;
  curl) cp "$AOD_STUBS/curl" "$AOD_BIN/curl"; chmod 755 "$AOD_BIN/curl";;
esac; done
exit 0
'''
SYSTEMCTL_STUB = '#!/bin/sh\necho "systemctl $*" >> "$AOD_LOG"\nexit 0\n'
CURL_STUB = r'''#!/bin/sh
echo "curl $*" >> "$AOD_LOG"
if [ -n "${AOD_OFFLINE:-}" ]; then echo "curl: (6) Could not resolve host: get.acme.sh" >&2; exit 6; fi
out=""; prev=""; for x in "$@"; do [ "$prev" = -o ] && out="$x"; prev="$x"; done
cp "$AOD_STUBS/get.acme.sh" "$out"
'''
# get.acme.sh → acme.sh --install-online: 3.1.4's _precheck refuses without crontab (and get.acme.sh still exits 0);
# else the program lands in $LE_WORKING_DIR (falling back to $HOME/.acme.sh) and installcronjob adds the daily entry
GETACME_STUB = r'''#!/bin/sh
echo "installer $* HOME=$HOME LE_WORKING_DIR=${LE_WORKING_DIR:-} PWD=$PWD" >> "$AOD_LOG"
echo partial > ./master.tar.gz
command -v crontab >/dev/null 2>&1 || { echo "Pre-check failed, cannot install."; echo "Install error"; exit 0; }
[ -n "${AOD_INSTALL_SLEEP:-}" ] && sleep "$AOD_INSTALL_SLEEP"
[ -n "${AOD_INSTALL_NOTHING:-}" ] && { echo "Download error."; echo "Install error"; exit 0; }
home="${LE_WORKING_DIR:-$HOME/.acme.sh}"
mkdir -p "$home" && cp "$AOD_STUBS/acme.sh" "$home/acme.sh" && chmod 755 "$home/acme.sh"
"$home/acme.sh" --install-cronjob --home "$home" >/dev/null
echo "Install success!"
'''
ACME_STUB = r'''#!/bin/sh
echo "acme $*" >> "$AOD_LOG"
home=""; prev=""; for x in "$@"; do [ "$prev" = --home ] && home="$x"; prev="$x"; done
case " $* " in
  *" --version "*) echo "https://github.com/acmesh-official/acme.sh"; echo "v${AOD_ACME_VER:-3.1.4}"; exit 0;;
  *" --install-cronjob "*)
    cur="$(crontab -l 2>/dev/null)"
    printf '%s\n' "$cur" | grep -q "acme.sh --cron" && exit 0
    { [ -n "$cur" ] && printf '%s\n' "$cur"; echo "17 3 * * * \"$home\"/acme.sh --cron --home \"$home\" > /dev/null"; } | crontab -
    exit 0;;
esac
exit 0
'''
for name, body in (("crontab", CRONTAB_STUB), ("apt-get", APT_STUB), ("systemctl", SYSTEMCTL_STUB), ("curl", CURL_STUB),
                   ("get.acme.sh", GETACME_STUB), ("acme.sh", ACME_STUB)):
    with open(os.path.join(STUBS, name), "w") as f:
        f.write(body)
    os.chmod(os.path.join(STUBS, name), 0o755)
TOOLS = ("sh", "cat", "cp", "chmod", "mkdir", "grep", "printf", "sleep")


def sandbox(cron=False, curl=True, apt=True, acme=False, **env):
    """A fresh box: BIN holds the plain tools plus the stubs asked for; returns (bin dir, acme store)."""
    box = tempfile.mkdtemp(prefix="box-", dir=SB)
    bindir = os.path.join(box, "bin")
    os.makedirs(bindir)
    for t in TOOLS:
        os.symlink(shutil.which(t), os.path.join(bindir, t))
    for want, name in ((cron, "crontab"), (curl, "curl"), (apt, "apt-get"), (True, "systemctl")):
        if want:
            shutil.copy(os.path.join(STUBS, name), os.path.join(bindir, name))
    store = os.path.join(box, "acme-home")
    if acme:
        os.makedirs(store)
        shutil.copy(os.path.join(STUBS, "acme.sh"), os.path.join(store, "acme.sh"))
    tmp = os.path.join(box, "tmp")
    os.makedirs(tmp)
    for k in [k for k in os.environ if k.startswith("AOD_")]:
        del os.environ[k]
    os.environ.update(PATH=bindir, AOD_LOG=LOG, AOD_BIN=bindir, AOD_STUBS=STUBS, AOD_CRONTAB=os.path.join(box, "crontab"),
                      LE_WORKING_DIR=store, **{"AOD_" + k.upper(): v for k, v in env.items()})
    N.ACME_HOME = store
    N._ACME_CANDIDATES = (os.path.join(box, "decoy", "acme.sh"),)   # the store itself must be where it is looked for
    N.ACME_INSTALL_BUDGET, N.ACME_FETCH_MIN = SHIPPED_BUDGET, SHIPPED_FETCH_MIN
    N.DRYRUN = False
    tempfile.tempdir = tmp
    open(LOG, "w").close()
    return box, store, tmp


def issue(domains, email="ops@example.com", mode="letsencrypt", dry=False):
    """Drive _issue_acme; returns (Reject message or "", the calls made in order, what it logged)."""
    N.DRYRUN = dry
    box = os.path.dirname(os.environ["PATH"])
    svc = {"cert": os.path.join(box, "tls", "fullchain.pem"), "key": os.path.join(box, "tls", "key.pem"),
           "unit": "swg-panel-server.service"}
    creds = {"mode": mode, "email": email, "cf_token": "", "cf_account": "", "cf_origin_token": ""}
    err, buf = "", io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            N._issue_acme(svc, "panel", list(domains), mode, creds, reloadcmd=False)
        except N.Reject as e:
            err = str(e) or "rejected"
        except Exception as e:                     # a plant that reaches a missing program must read red, not crash
            err = "%s: %s" % (type(e).__name__, e)
    N.DRYRUN = False
    with open(LOG) as f:
        calls = [l.rstrip("\n") for l in f]
    return err, calls, buf.getvalue()


def idx(calls, pat):
    for i, c in enumerate(calls):
        if re.search(pat, c):
            return i
    return -1


# ── [1] no acme.sh: swg-netctl installs it ───────────────────────────────────────────────────────────────────────────
print("[1] swg-netctl: an issuance that finds no acme.sh installs it")
box, store, tmp = sandbox(cron=False, curl=False)
err, calls, logged = issue(["new.example.com"])
check("[1] no acme.sh: installed, then the certificate ordered", not err and os.path.isfile(os.path.join(store, "acme.sh"))
      and idx(calls, r"^acme .*--issue .*-d new\.example\.com") >= 0, (err, calls))
steps = [idx(calls, p) for p in (r"^apt-get update -qq", r"^apt-get install -y cron curl DEBIAN_FRONTEND=noninteractive",
                                 r"^systemctl enable --now cron", r"^curl -fsSL --max-time 60 -o \S+ https://get\.acme\.sh$",
                                 r"^installer email=ops@example\.com ", r"^acme --home \S+ --install-cronjob$",
                                 r"^acme --version$", r"^acme --home \S+ --issue ")]
check("[1] the steps in order: cron + curl from apt, the fetch, the installer, the renewal entry, the floor, the order",
      all(i >= 0 for i in steps) and steps == sorted(steps), list(zip(steps, calls)))
inst = calls[idx(calls, r"^installer ")] if idx(calls, r"^installer ") >= 0 else ""
check("[1] the installer runs with HOME=/root and LE_WORKING_DIR=<the store>",
      " HOME=/root " in inst and (" LE_WORKING_DIR=%s " % store) in inst, inst)
m = re.search(r" PWD=(\S+)$", inst)
check("[1] …in a fresh temp dir (installOnline unpacks into its cwd), gone afterwards",
      bool(m) and os.path.dirname(m.group(1)) == tmp and os.path.basename(m.group(1)).startswith("swg-acme-")
      and not os.listdir(tmp), (inst, os.listdir(tmp)))
tab = open(os.path.join(box, "crontab")).read() if os.path.exists(os.path.join(box, "crontab")) else ""
check("[1] acme.sh's daily renewal entry is in root's crontab", "acme.sh --cron --home \"%s\"" % store in tab, tab)
check("[1] the journal says acme.sh was installed", "acme.sh installed at " + os.path.join(store, "acme.sh") in logged, logged)

box, store, tmp = sandbox(cron=True)
err, calls, _ = issue(["new.example.com"], email="")
_inst0 = calls[idx(calls, r"^installer ")] if idx(calls, r"^installer ") >= 0 else ""
check("[1] no Access / install.conf email: the installer gets none (never a made-up admin@<domain>)", not err
      and bool(re.match(r"^installer\s+HOME=", _inst0)) and "email=" not in _inst0 and "admin@" not in " ".join(calls)
      and idx(calls, r"--register-account") < 0 and idx(calls, r"^acme .*--issue .*-d new\.example\.com") >= 0, (err, calls))
check("[1] cron and curl already there: no apt-get, no systemctl", idx(calls, r"^(apt-get|systemctl) ") < 0, calls)

for bad in ("ops @example.com", "ops=x@example.com", "*@example.com"):
    box, store, tmp = sandbox(cron=True)
    err, calls, _ = issue(["new.example.com"], email=bad)
    ok = "not a plain email address" in err and idx(calls, r"^(curl|installer|apt-get) ") < 0
    if not ok:
        break
check("[1] an email with a space or '=' is refused before anything is fetched (get.acme.sh word-splits it)", ok, (bad, err, calls))

box, store, tmp = sandbox(cron=True, offline="1")
err, calls, _ = issue(["new.example.com"])
check("[1] offline: the clear Reject (curl's error, the manual commands), no installer, no order",
      "could not be downloaded from https://get.acme.sh (curl rc 6: curl: (6) Could not resolve host" in err
      and "apt-get install -y cron curl, then curl -fsSL https://get.acme.sh | sh -s email=ops@example.com" in err
      and idx(calls, r"^installer ") < 0 and idx(calls, r"--issue") < 0 and not os.listdir(tmp), (err, calls))

box, store, tmp = sandbox(cron=True, install_nothing="1")
err, calls, _ = issue(["new.example.com"])
check("[1] an installer that installs nothing (get.acme.sh exits 0 anyway): the Reject, no order",
      "its installer did not install it (Install error)" in err and "curl -fsSL https://get.acme.sh | sh -s email=" in err
      and idx(calls, r"--issue") < 0, (err, calls))

box, store, tmp = sandbox(cron=True, install_sleep="6")
N.ACME_INSTALL_BUDGET, N.ACME_FETCH_MIN = 2, 0
t0 = __import__("time").monotonic()
err, calls, _ = issue(["new.example.com"])
took = __import__("time").monotonic() - t0
check("[1] the install's network steps share one budget: a slow installer is stopped when it runs out, and the Reject says so",
      took < 5 and "stopped: still running after" in err and "curl -fsSL https://get.acme.sh | sh -s email=" in err
      and idx(calls, r"--issue") < 0, (round(took, 1), err, calls))

# verify F4: a slow `apt-get install` runs to its end even when the budget is gone — then F6: the Reject names apt
box, store, tmp = sandbox(cron=False, apt_install_sleep="3")
N.ACME_INSTALL_BUDGET, N.ACME_FETCH_MIN = 2, 1
err, calls, _ = issue(["new.example.com"])
check("[1] apt-get install is never cut short by the budget (a SIGKILL mid-dpkg breaks apt on the box)",
      os.path.exists(os.path.join(box, "bin", "crontab")) and "could not be installed" not in err, (err, calls))
box, store, tmp = sandbox(cron=False, apt_sleep="2")
N.ACME_INSTALL_BUDGET, N.ACME_FETCH_MIN = 3, 2
err, calls, _ = issue(["new.example.com"])
check("[1] apt spent the budget: the Reject says so and to apply again (cron is in now), no doomed fetch",
      "installing cron took" in err and "apply the change again" in err and "curl -fsSL https://get.acme.sh | sh -s" in err
      and "reach GitHub" not in err and idx(calls, r"^curl ") < 0, (err, calls))

box, store, tmp = sandbox(cron=True, acme_ver="3.1.2")
err, calls, _ = issue(["new.example.com"])
up, iss = idx(calls, r"^acme --home \S+ --upgrade$"), idx(calls, r"--issue")
check("[1] an acme.sh older than 3.1.4 → --upgrade, before the order", not err and 0 <= up < iss, (err, calls))

box, store, tmp = sandbox(cron=True, acme=True)
err, calls, _ = issue(["new.example.com"])
check("[1] acme.sh already there: nothing installed, straight to the order", not err and idx(calls, r"^(curl|installer|apt-get) ") < 0
      and idx(calls, r"^acme --version") < 0 and idx(calls, r"--issue") >= 0, (err, calls))

box, store, tmp = sandbox(cron=False, curl=False, apt=False)
err, calls, _ = issue(["new.example.com"])
check("[1] no cron and no apt-get: the Reject naming the manual commands, nothing fetched",
      "no cron or curl and no apt-get" in err and "curl -fsSL https://get.acme.sh | sh -s email=ops@example.com" in err
      and idx(calls, r"^curl ") < 0, (err, calls))

box, store, tmp = sandbox(cron=False, apt_fail="1")
err, calls, _ = issue(["new.example.com"])
check("[1] apt cannot install cron: the Reject carries apt's E: line, nothing fetched",
      "cron could not be installed (E: Unable to locate package cron)" in err and idx(calls, r"^curl ") < 0, (err, calls))

box, store, tmp = sandbox(cron=False, curl=False)
err, calls, logged = issue(["new.example.com"], dry=True)
check("[1] a dry run: every step's argv logged, nothing run, no temp dir made",
      not err and not calls and not os.listdir(tmp) and not os.path.exists(store)
      and all(re.search(p, logged) for p in (r"exec: apt-get install -y cron curl", r"exec: curl -fsSL --max-time 60 -o \S+ https://get\.acme\.sh",
                                             r"exec: sh \S+get\.acme\.sh email=ops@example\.com", r"exec: \S+acme\.sh --home \S+ --install-cronjob",
                                             r"exec: \S+acme\.sh --home \S+ --issue ")), (err, calls, os.listdir(tmp), logged))

# ── [2] the order never carries an IP beside a name ──────────────────────────────────────────────────────────────────
print("\n[2] swg-netctl: no IP literal beside a name in the order")
box, store, tmp = sandbox(cron=True, acme=True)
err, calls, logged = issue(["new.example.com", "203.0.113.7"])
o = calls[idx(calls, r"--issue")] if idx(calls, r"--issue") >= 0 else ""
check("[2] an IP literal beside a name is left out of the order", not err and "-d new.example.com" in o and "203.0.113.7" not in o
      and "left 203.0.113.7 out of the certificate order" in logged, (err, o, logged))
box, store, tmp = sandbox(cron=True, acme=True)
err, calls, _ = issue(["203.0.113.7"])
o = calls[idx(calls, r"--issue")] if idx(calls, r"--issue") >= 0 else ""
check("[2] an order of IPs alone is left for the CA to answer", "-d 203.0.113.7" in o, (err, calls))

# ── [3] the panel: an old IP never joins a CA's order ────────────────────────────────────────────────────────────────
print("\n[3] swg-panel-server: a same-port move from the IP orders the domain alone")
PT = ast.parse(SRC["PANEL"])
fsrc = {n.name: ast.get_source_segment(SRC["PANEL"], n) for n in PT.body           # only the three it runs: the
        if isinstance(n, ast.FunctionDef) and n.name in ("_is_ip", "_apply_panel_cert_only", "_place_cert")}  # file is 41k lines


def cert_only(mode, old):
    seen = {}

    class L:
        @staticmethod
        def primary():
            return 7, None
    ns = {"_apply_status": lambda *a, **k: seen.setdefault("status", []).append(a),
          "_netctl_wait": lambda *a, **k: (True, ""), "_netctl_enqueue": lambda deps, verb, args: seen.setdefault("q", []).append(verb) or "r",
          "_place_cert": lambda deps, svc, doms, *a, **k: seen.setdefault("order", doms) and (True, ""),
          "_arm_pending": lambda *a, **k: seen.setdefault("armed", k), "LISTENERS": L, "_APPLY": {"lock": contextlib.nullcontext()},
          "REAL_CA_MODES": ("cloudflare", "letsencrypt", "cf15", "letsencrypt-ip"), "_is_ip": None}
    exec(fsrc["_is_ip"], {"ipaddress": __import__("ipaddress")}, ns)
    exec(fsrc["_apply_panel_cert_only"], ns)
    deps = {"panel_settings": {"access": {"tls": {"mode": mode}}}}
    ns["_apply_panel_cert_only"](deps, "0.0.0.0", 8443, "https://new.example.com:8443", "new.example.com", old)
    return seen.get("order"), (seen.get("armed") or {}).get("old_domain", "?"), seen


order, armed, seen = cert_only("letsencrypt", "203.0.113.7")
check("[3] letsencrypt: an old IPv4 is left out, the change armed new-only",
      order == "new.example.com" and armed == "", (order, armed, seen))
res = [cert_only(m, o)[:2] for m, o in (("letsencrypt", "2001:db8::1"), ("letsencrypt", "[2001:db8::1]"),
                                         ("cloudflare", "203.0.113.7"), ("cf15", "203.0.113.7"))]
check("[3] …an old IPv6 (bare or bracketed), and under cloudflare / cf15 too", all(r == ("new.example.com", "") for r in res), res)
r = cert_only("letsencrypt", "old.example.com")[:2]
check("[3] an old DNS name is still ordered beside the new one, and kept for the grace",
      r == ("new.example.com,old.example.com", "old.example.com"), r)
r = cert_only("selfsigned", "203.0.113.7")[:2]
check("[3] self-signed: unchanged (the old IP still beside the new name)", r == ("new.example.com,203.0.113.7", "203.0.113.7"), r)
pc = next(n for n in PT.body if isinstance(n, ast.FunctionDef) and n.name == "_place_cert")
dflt = dict(zip([a.arg for a in pc.args.args][-len(pc.args.defaults):], [ast.literal_eval(d) for d in pc.args.defaults]))
# the install's worst case, from the source: the shared budget, plus every step that keeps a cap of its own
NT = ast.parse(SRC["NETCTL"])
inst = "".join(ast.get_source_segment(SRC["NETCTL"], n) for n in NT.body
               if isinstance(n, ast.FunctionDef) and n.name in ("_acme_prereqs", "_acme_install"))
fixed = [int(x) for x in re.findall(r"timeout=(\d+)\)", inst)]
worst = SHIPPED_BUDGET + sum(fixed)
check("[3] the panel waits longer than the install can take: its budget + every cap outside it, and 60 s for the order", len(fixed) >= 5 and dflt.get("timeout", 0) >= worst + 60, (dflt, SHIPPED_BUDGET, fixed, worst))

# ── [4] the message ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the \"not found\" message")
N._ACME_CANDIDATES, N.ACME_HOME = SHIPPED_CANDIDATES, "/root/.acme.sh"   # the shipped list, the shipped store
_loc = N._locate_acme
N._locate_acme = lambda: None
try:
    N.find_acme(); msg = ""
except N.Reject as e:
    msg = str(e)
N._locate_acme = _loc
check("[4] the message names /root/.acme.sh once (under root `~` is /root)",
      msg.count("/root/.acme.sh/acme.sh") == 1 and "/opt/acme.sh/acme.sh" in msg, (msg, SHIPPED_CANDIDATES))
N.ACME_HOME = "/opt/le"
check("[4] …and names a store set elsewhere (ACME_HOME), first", N._acme_paths()[0] == "/opt/le/acme.sh", N._acme_paths())

# ── [5] parity with the installer ────────────────────────────────────────────────────────────────────────────────────
print("\n[5] the same steps as install-host.sh's ensure_acme")
H, C, NS = SRC["HOST"], SRC["COMMON"], SRC["NETCTL"]
ea = H[H.index("\nensure_acme(){"):]
ea = ea[:ea.index("\n# A REUSED cert")]
i_cron, i_get = ea.find("\n  ensure_acme_cron   # cron FIRST"), ea.find('curl -fsSL https://get.acme.sh | sh${ACME_EMAIL:+ -s email=$ACME_EMAIL}')
check("[5] install-host.sh still installs cron before get.acme.sh, with the same URL and an email only when one was given",
      0 <= i_cron < i_get and N.ACME_GET_URL == "https://get.acme.sh", (i_cron, i_get))
mm = re.search(r"^ACME_MIN=(\d+)\.(\d+)\.(\d+)$", H, re.M)
check("[5] the same version floor as install-host.sh's ACME_MIN", bool(mm) and tuple(map(int, mm.groups())) == N.ACME_MIN,
      (mm and mm.groups(), N.ACME_MIN))
ec = C[C.index("\nensure_acme_cron(){"):]
ec = ec[:ec.index("\nacme_cron_entry(){")]
check("[5] lib/common.sh's ensure_acme_cron still installs cron from apt and registers --install-cronjob --home",
      "apt-get install -y cron" in ec and '--install-cronjob --home "$home"' in ec and "systemctl enable --now cron" in ec)
calls_install = [l for l in NS.split("\n") if re.search(r"\b_acme_install\(", l) and not l.lstrip().startswith(("#", "def "))]
check("[5] only issuance installs (one call, in _issue_acme; sync-acme / renew-acme / drop-cert keep find_acme)",
      len(calls_install) == 1 and "_locate_acme() or _acme_install(" in calls_install[0], calls_install)

# ── [6] CHANGELOG ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the CHANGELOG")
en = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read().split("\n## [Unreleased]")[1].split("\n## [")[0]
ru = open(os.path.join(ROOT, "CHANGELOG.ru.md"), encoding="utf-8").read().split("\n## [Unreleased]")[1].split("\n## [")[0]
check("[6] CHANGELOG.md's Unreleased says it (acme.sh installed, the IP left out of the order)",
      re.search(r"acme\.sh[^\n]*(?:\n  [^\n]*){0,6}install", en) is not None and re.search(r"Let's Encrypt", en) is not None
      and re.search(r"IP address[^\n]*(?:\n  [^\n]*){0,4}(?:refus|left out)", en) is not None)
check("[6] …and CHANGELOG.ru.md's", "acme.sh" in ru and re.search(r"(?i)IP-адрес", ru) is not None)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
