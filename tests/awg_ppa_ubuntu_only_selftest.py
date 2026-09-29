#!/usr/bin/env python3
"""Self-test — THE AMNEZIA PPA IS TRIED ON UBUNTU ONLY; EVERYWHERE ELSE AmneziaWG GOES STRAIGHT TO THE SOURCE BUILD (round 12c).

ppa:amnezia/ppa is Launchpad's and builds for Ubuntu series only. The installers tried it everywhere: on Debian 12 it
installed software-properties-common and ~36 packages (packagekit and polkit left running), add-apt-repository died with a
raw Python traceback ("'NoneType' object has no attribute 'people'"), four "E: Unable to locate package amneziawg…" lines
followed, and only then did the source build install AmneziaWG; on Debian 13 "E: Unable to locate package
software-properties-common" and the same four (1.8.8 qualification, R27). The first thing a Debian user saw, and it read as a
failed install.

  [1] awg_ppa_suite (lib/common.sh) on real /etc/os-release files — Debian 12 and 13 → no PPA; Ubuntu 22.04 / 24.04 / 26.04
      → jammy / noble / resolute; derivatives that say ID_LIKE=ubuntu → their UBUNTU_CODENAME (Mint 22 → noble, elementary
      7.1 → jammy, Pop!_OS → jammy); Debian-likes that are not Ubuntu (Kali, Raspberry Pi OS), no file, a broken file → no
      PPA; never fatal under set -euo pipefail; awg_os_name gives the system's own name for the line that says why
  [2] awg_ppa_add: software-properties-common and add-apt-repository, and on a derivative whose own codename is no Ubuntu
      series (elementary's "horus") the entry add-apt-repository wrote is re-pointed at the Ubuntu one (.list and
      .sources); another source never touched; on Ubuntu itself nothing is re-pointed
  [3] install-host.sh and install-node.sh ensure_wg_tools awg, driven: on Debian 12 / 13 no software-properties-common, no
      add-apt-repository, no amneziawg package, no linux-headers-generic — one line saying AmneziaWG is built from source
      because its packages are published for Ubuntu only, naming the system — then the source build; on Ubuntu the PPA
      route as before; a dry run says so and builds nothing
  [4] update.sh ensure_awg_datapath (the heal): the same choice
  [5] no copy of the PPA step outside awg_ppa_add
  [6] CHANGELOG.md and CHANGELOG.ru.md say it

Run: python3 tests/awg_ppa_ubuntu_only_selftest.py        (0 = pass)
     --perturb   six plants, each on its own — each must turn its own check red
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FILES = (("COMMON", "lib/common.sh"), ("HOST", "install-host.sh"), ("NODE", "install-node.sh"), ("UPDATE", "update.sh"))
PATHS = {k: os.environ.get("SWG_PPA_" + k) or os.path.join(ROOT, f) for k, f in FILES}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("id", "COMMON", '  case "$id" in ubuntu) ;; *) case " $like " in', '  case "$id" in ubuntu|debian) ;; *) case " $like " in',
     "[1] Debian 12 and 13 → no PPA"),
    ("like", "COMMON", '*) case " $like " in *" ubuntu "*) ;; *) return 1;; esac;; esac', '*) case " $like " in *" debian "*) ;; *) return 1;; esac;; esac',
     "[1] Debian-likes that are not Ubuntu (Kali, Raspberry Pi OS), a broken file, no file → no PPA, never fatal"),
    ("repoint", "COMMON", '      [ -f "$f" ] && run sed -i -E', '      [ -f "$f" ] && : sed -i -E',
     "[2] a derivative whose own codename is no Ubuntu series: the PPA entry re-pointed at the Ubuntu one"),
    ("host", "HOST", '  if _ppa="$(awg_ppa_suite)"; then   # Ubuntu, or a system built on it', '  if _ppa="$(awg_ppa_suite)" || true; then   # Ubuntu, or a system built on it',
     "[3] install-host.sh on Debian 12: no PPA step at all, one line why, then the source build"),
    ("node", "NODE", '  if _ppa="$(awg_ppa_suite)"; then   # Ubuntu, or a system built on it', '  if _ppa="$(awg_ppa_suite)" || true; then   # Ubuntu, or a system built on it',
     "[3] install-node.sh on Debian 12: no PPA step at all, one line why, then the source build"),
    ("update", "UPDATE", '  if have apt-get && _ppa="$(awg_ppa_suite)"; then', '  if have apt-get; then',
     "[4] update.sh's heal on Debian 12: no PPA step, one line why, then the source build"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_PPA_" + key: f.name}), capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-8s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
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

# The files as the official images carry them (captured 2026-09-28: debian:bookworm-slim, debian:trixie-slim, ubuntu:22.04,
# ubuntu:24.04, ubuntu:26.04); the derivatives as their releases ship them.
OSR = {
    "debian12": 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nNAME="Debian GNU/Linux"\nVERSION_ID="12"\nVERSION="12 (bookworm)"\n'
                'VERSION_CODENAME=bookworm\nID=debian\nHOME_URL="https://www.debian.org/"\n',
    "debian13": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\nVERSION="13 (trixie)"\n'
                'VERSION_CODENAME=trixie\nDEBIAN_VERSION_FULL=13.7\nID=debian\nHOME_URL="https://www.debian.org/"\n',
    "ubuntu2204": 'PRETTY_NAME="Ubuntu 22.04.5 LTS"\nNAME="Ubuntu"\nVERSION_ID="22.04"\nVERSION="22.04.5 LTS (Jammy Jellyfish)"\n'
                  'VERSION_CODENAME=jammy\nID=ubuntu\nID_LIKE=debian\nUBUNTU_CODENAME=jammy\n',
    "ubuntu2404": 'PRETTY_NAME="Ubuntu 24.04.5 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nVERSION="24.04.5 LTS (Noble Numbat)"\n'
                  'VERSION_CODENAME=noble\nID=ubuntu\nID_LIKE=debian\nUBUNTU_CODENAME=noble\nLOGO=ubuntu-logo\n',
    "ubuntu2604": 'PRETTY_NAME="Ubuntu 26.04.1 LTS"\nNAME="Ubuntu"\nVERSION_ID="26.04"\nVERSION="26.04.1 LTS (Resolute Raccoon)"\n'
                  'VERSION_CODENAME=resolute\nID=ubuntu\nID_LIKE=debian\nUBUNTU_CODENAME=resolute\nLOGO=ubuntu-logo\n',
    "mint22": 'NAME="Linux Mint"\nVERSION="22 (Wilma)"\nID=linuxmint\nID_LIKE="ubuntu debian"\nPRETTY_NAME="Linux Mint 22"\n'
              'VERSION_ID="22"\nVERSION_CODENAME=wilma\nUBUNTU_CODENAME=noble\n',
    "elementary7": 'PRETTY_NAME="elementary OS 7.1 Horus"\nNAME="elementary OS"\nVERSION_ID="7.1"\nVERSION="7.1 Horus"\n'
                   'VERSION_CODENAME=horus\nID=elementary\nID_LIKE=ubuntu\nUBUNTU_CODENAME=jammy\n',
    "pop2204": 'NAME="Pop!_OS"\nVERSION="22.04 LTS"\nID=pop\nID_LIKE="ubuntu debian"\nPRETTY_NAME="Pop!_OS 22.04 LTS"\n'
               'VERSION_ID="22.04"\nVERSION_CODENAME=jammy\nUBUNTU_CODENAME=jammy\n',
    "kali": 'PRETTY_NAME="Kali GNU/Linux Rolling"\nNAME="Kali GNU/Linux"\nVERSION_ID="2025.3"\nID=kali\nID_LIKE=debian\nVERSION_CODENAME=kali-rolling\n',
    "raspios": 'PRETTY_NAME="Raspbian GNU/Linux 12 (bookworm)"\nNAME="Raspbian GNU/Linux"\nVERSION_ID="12"\nID=raspbian\nID_LIKE=debian\nVERSION_CODENAME=bookworm\n',
    "broken": 'this is ( not a shell file\n',
}
T = tempfile.mkdtemp(prefix="ppa-")
for k, v in OSR.items():
    open(os.path.join(T, k), "w").write(v)
C = SRC["COMMON"]
LIB = fn(C, "awg_ppa_suite") + fn(C, "awg_os_name") + fn(C, "awg_ppa_add")

def bash(script, env=None):
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True, text=True, env=dict(os.environ, **(env or {})), timeout=60)
    return r.returncode, r.stdout, r.stderr

# ── [1] which systems get the PPA ────────────────────────────────────────────────────────────────────────────────────
print("[1] awg_ppa_suite on real /etc/os-release files")
got = {}
for k in ("debian12", "debian13", "ubuntu2204", "ubuntu2404", "ubuntu2604", "mint22", "elementary7", "pop2204", "kali", "raspios", "broken", "missing"):
    rc, out, err = bash(LIB + 'if s="$(awg_ppa_suite)"; then echo "PPA:$s"; else echo "NONE"; fi\necho END\n', {"SWG_OS_RELEASE": os.path.join(T, k)})
    got[k] = out.split("\n")[0] if rc == 0 and "END" in out else "CRASH rc=%d %s" % (rc, err[:80])
check("[1] Debian 12 and 13 → no PPA", got["debian12"] == "NONE" and got["debian13"] == "NONE", got)
check("[1] Ubuntu 22.04 / 24.04 / 26.04 → jammy / noble / resolute",
      (got["ubuntu2204"], got["ubuntu2404"], got["ubuntu2604"]) == ("PPA:jammy", "PPA:noble", "PPA:resolute"), got)
check("[1] a derivative (ID_LIKE=ubuntu) → its UBUNTU_CODENAME: Mint 22 → noble, elementary 7.1 → jammy, Pop!_OS → jammy",
      (got["mint22"], got["elementary7"], got["pop2204"]) == ("PPA:noble", "PPA:jammy", "PPA:jammy"), got)
check("[1] Debian-likes that are not Ubuntu (Kali, Raspberry Pi OS), a broken file, no file → no PPA, never fatal",
      all(got[k] == "NONE" for k in ("kali", "raspios", "broken", "missing")), got)
rc, out, err = bash(LIB + 'awg_os_name; echo; SWG_OS_RELEASE=%s awg_os_name; echo\n' % os.path.join(T, "missing"), {"SWG_OS_RELEASE": os.path.join(T, "debian12")})
check("[1] awg_os_name: the system's own name (and \"this system\" without a file)", out == "Debian GNU/Linux 12 (bookworm)\nthis system\n", (rc, out, err))

# ── [2] awg_ppa_add ──────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] awg_ppa_add")
def ppa_add(osr, series):
    d = tempfile.mkdtemp(prefix="ppa-src-")
    own = re.search(r"^VERSION_CODENAME=(\S+)", OSR[osr], re.M).group(1)
    open(os.path.join(d, "amnezia-ubuntu-ppa-%s.list" % own), "w").write("deb https://ppa.launchpadcontent.net/amnezia/ppa/ubuntu/ %s main\n" % own)
    open(os.path.join(d, "amnezia-ubuntu-ppa-%s.sources" % own), "w").write(
        "Types: deb\nURIs: https://ppa.launchpadcontent.net/amnezia/ppa/ubuntu/\nSuites: %s\nComponents: main\n" % own)
    open(os.path.join(d, "other-tool.list"), "w").write("deb https://example.org/%s %s main\n" % (own, own))
    rc, out, err = bash('DRYRUN=false\nrun(){ echo "RUN $*"; "$@" 2>/dev/null || true; }\n' + LIB + 'awg_ppa_add %s\necho END\n' % series,
                        {"SWG_OS_RELEASE": os.path.join(T, osr), "SWG_APT_SOURCES_D": d,
                         "PATH": _stubpath()})
    files = {f: open(os.path.join(d, f)).read() for f in sorted(os.listdir(d))}
    return rc, out, err, files, own
def _stubpath():
    b = tempfile.mkdtemp(prefix="ppa-bin-")
    for tool in ("apt-get", "add-apt-repository"):
        p = os.path.join(b, tool); open(p, "w").write("#!/bin/sh\nexit 0\n"); os.chmod(p, 0o755)
    return b + ":" + os.environ["PATH"]
rc, out, err, files, own = ppa_add("elementary7", "jammy")
check("[2] software-properties-common and add-apt-repository, as before",
      rc == 0 and "RUN apt-get install -y software-properties-common" in out and "RUN add-apt-repository -y ppa:amnezia/ppa" in out, (rc, out, err))
check("[2] a derivative whose own codename is no Ubuntu series: the PPA entry re-pointed at the Ubuntu one",
      files["amnezia-ubuntu-ppa-horus.list"] == "deb https://ppa.launchpadcontent.net/amnezia/ppa/ubuntu/ jammy main\n"
      and "Suites: jammy\n" in files["amnezia-ubuntu-ppa-horus.sources"], files)
check("[2] …another source never touched", files["other-tool.list"] == "deb https://example.org/horus horus main\n", files)
rc, out, err, files, own = ppa_add("ubuntu2404", "noble")
check("[2] on Ubuntu itself nothing is re-pointed", rc == 0 and "sed" not in out and "noble main" in files["amnezia-ubuntu-ppa-noble.list"], (out, files))

# ── [3] the installers ───────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] install-host.sh and install-node.sh: ensure_wg_tools awg, driven")
STUBS = ('have(){ case "$1" in apt-get) return 0;; *) return 1;; esac; }\nmodprobe(){ return 1; }\n'
         'info(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\n'
         'run(){ if $DRYRUN; then echo "    [skip] $*"; else echo "RUN $*"; fi; }\n'
         'awg_go_needs_install(){ return 1; }\nawg_go_pinned(){ :; }\nensure_awg_headers_follow(){ echo "HEADERS-FOLLOW"; }\n'
         'awg_dkms_drop_unowned(){ echo "DROP-UNOWNED"; }\nbuild_awg_module(){ echo "BUILD-PKG-MODULE"; }\n'
         'awg_build_from_source(){ echo "SOURCE-BUILD"; return 0; }\nensure_awg_userspace(){ echo "USERSPACE"; }\nawg_tools_drive_3x(){ return 1; }\n')
def installer(key, osr, dry=False):
    body = "DRYRUN=%s\n%s%s%sensure_wg_tools awg && echo RC0 || echo RC$?\necho END\n" % ("true" if dry else "false", STUBS, LIB, fn(SRC[key], "ensure_wg_tools"))
    rc, out, err = bash(body, {"SWG_OS_RELEASE": os.path.join(T, osr)})
    return rc, out + err
PPA_WORDS = ("software-properties-common", "add-apt-repository", "install -y amneziawg", "linux-headers-generic", "BUILD-PKG-MODULE", "DROP-UNOWNED")
for key, label in (("HOST", "install-host.sh"), ("NODE", "install-node.sh")):
    for osr, name in (("debian12", "Debian GNU/Linux 12 (bookworm)"), ("debian13", "Debian GNU/Linux 13 (trixie)")):
        rc, out = installer(key, osr)
        lines = [l for l in out.splitlines() if l.startswith(("INFO", "WARN"))]
        check("[3] %s on %s: no PPA step at all, one line why, then the source build" % (label, "Debian 12" if osr == "debian12" else "Debian 13"),
              rc == 0 and "END" in out and not [w for w in PPA_WORDS if w in out] and "SOURCE-BUILD" in out
              and lines[:1] == ["INFO installing AmneziaWG from source (tools + DKMS kernel module) — its packages are published for Ubuntu only, and this is %s — this can take a few minutes…" % name],
              (rc, out))
    rc, out = installer(key, "ubuntu2404")
    check("[3] %s on Ubuntu 24.04: the PPA route as before" % label,
          rc == 0 and "RUN apt-get install -y software-properties-common" in out and "RUN add-apt-repository -y ppa:amnezia/ppa" in out
          and "RUN apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" in out and "BUILD-PKG-MODULE" in out
          and "INFO installing AmneziaWG (tools + DKMS kernel module) from the amnezia PPA for Ubuntu noble — this can take a minute…" in out, out)
    rc, out = installer(key, "mint22")
    check("[3] %s on Linux Mint 22: the PPA route, for noble" % label, rc == 0 and "from the amnezia PPA for Ubuntu noble" in out and "add-apt-repository" in out, out)
    rc, out = installer(key, "debian12", dry=True)
    check("[3] %s: a Debian dry run says so and builds nothing" % label,
          rc == 0 and "installing AmneziaWG from source" in out and "SOURCE-BUILD" not in out and "add-apt-repository" not in out, out)

# ── [4] update.sh's heal ─────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] update.sh: ensure_awg_datapath, driven (a node whose AmneziaWG tools are missing)")
USTUBS = STUBS + ('HAVE_BNODE=yes\nDID_UPDATE=no\nok(){ echo "OK $*"; }\nnote(){ echo "NOTE $*"; }\napt_refresh(){ echo "APT-REFRESH"; }\n'
                  'awg_dkms_register_source(){ :; }\nawg_dkms_build_all_kernels(){ :; }\nawg_headers_meta(){ :; }\n'
                  'dkms(){ :; }\napt-cache(){ return 1; }\nawg_tools_old_why(){ :; }\n')
def heal(osr):
    body = "DRYRUN=false\n%s%s%sensure_awg_datapath && echo RC0 || echo RC$?\necho END\n" % (USTUBS, LIB, fn(SRC["UPDATE"], "ensure_awg_datapath"))
    rc, out, err = bash(body, {"SWG_OS_RELEASE": os.path.join(T, osr)})
    return rc, out + err
rc, out = heal("debian12")
check("[4] update.sh's heal on Debian 12: no PPA step, one line why, then the source build",
      "END" in out and not [w for w in PPA_WORDS if w in out] and "SOURCE-BUILD" in out
      and "INFO AmneziaWG: building it from source — its packages are published for Ubuntu only, and this is Debian GNU/Linux 12 (bookworm)" in out, (rc, out))
rc, out = heal("ubuntu2204")
check("[4] …and on Ubuntu 22.04 the PPA route as before",
      "END" in out and "RUN add-apt-repository -y ppa:amnezia/ppa" in out and "RUN apt-get install -y amneziawg amneziawg-dkms amneziawg-tools" in out, out)

# ── [5] one copy ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] where the PPA step lives")
hits = []
for key in ("COMMON", "HOST", "NODE", "UPDATE"):
    for i, l in enumerate(SRC[key].split("\n")):
        code = "" if l.lstrip().startswith("#") else l.split("  #")[0]
        if re.search(r"add-apt-repository|software-properties-common", code):
            hits.append((key, i + 1, code.strip()[:60]))
check("[5] no copy of the PPA step outside awg_ppa_add", [h[0] for h in hits] == ["COMMON", "COMMON"]
      and all(h[2].startswith("run ") for h in hits), hits)

# ── [6] CHANGELOG ────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the CHANGELOG")
en = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read().split("\n## ")[1]
ru = open(os.path.join(ROOT, "CHANGELOG.ru.md"), encoding="utf-8").read().split("\n## ")[1]
check("[6] CHANGELOG.md's current release says it (Debian, the PPA, AmneziaWG)",
      re.search(r"Debian[^\n]*(?:\n  [^\n]*){0,3}PPA|PPA[^\n]*(?:\n  [^\n]*){0,3}Debian", en) is not None and "AmneziaWG" in en)
check("[6] …and CHANGELOG.ru.md's", re.search(r"Debian", ru) is not None and "PPA" in ru and "AmneziaWG" in ru)

shutil.rmtree(T, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
