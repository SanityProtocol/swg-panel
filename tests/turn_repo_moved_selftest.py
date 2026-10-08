#!/usr/bin/env python3
"""A turn-proxy fork whose repository moved: samosvalishe deleted samosvalishe/free-turn-proxy (2026-10) and hackdiaz-dev
carries it on. The panel's catalog names the new repo, so every request the panel sends does too — but a proxy installed
before the move REMEMBERS the old one (repo.txt, the docker record, an old docker record a conversion reads), and three
programs fetch from what they remember: swg-noded, update.sh and install-node.sh. Each must fetch from the new repo, and
what it writes back must name the new one, so the old name heals away.

  [1] swg-noded: the old repo maps to the new one; any other repo, and none, is left as it is
  [2] swg-noded's fetch helpers: _turn_resolve_tag asks the NEW repo for the latest tag, _turn_dl_urls builds from it
  [3] swg-noded _dturn_download (docker, a missing binary) asks the panel mirror — keyed by repo — and GitHub for the new repo
  [4] swg-noded _dturn_force_download (docker reinstall) the same
  [5] swg-noded _turn_install (bare) the same, and writes the new repo to repo.txt and the unit; the old name is gone
  [6] update.sh asks GitHub about the new repo and rewrites repo.txt to it; control: another fork's repo is untouched
  [7] install-node.sh (docker → bare conversion) downloads from the new repo

Run: python3 tests/turn_repo_moved_selftest.py            (0 = pass)
     --perturb-noded    swg-noded's map hands the old repo back → RED on [1]–[5]
     --perturb-update   update.sh without its redirect → RED on [6]
     --perturb-install  install-node.sh without its redirect → RED on [7]
   A perturbation prints "PERTURB OK" and exits 0 when something went red, exits 1 when nothing did — or when its anchor
   is gone (a perturbation that cannot be applied proves nothing).
"""
import os, re, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
P_NODED = "--perturb-noded" in sys.argv
P_UPDATE = "--perturb-update" in sys.argv
P_INSTALL = "--perturb-install" in sys.argv
PERTURB = P_NODED or P_UPDATE or P_INSTALL
OLD, NEW = "samosvalishe/free-turn-proxy", "hackdiaz-dev/free-turn-proxy"

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:240]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def perturbed(src, old, new, what):
    # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
    if src.count(old) != 1:
        print("PERTURB FAILED — %s: its anchor is not there exactly once (%d)" % (what, src.count(old)))
        sys.exit(1)
    return src.replace(old, new)

T = tempfile.mkdtemp(prefix="turnmoved-")

# ── swg-noded ───────────────────────────────────────────────────────────────────────────────────────────────────────
src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if P_NODED:
    src = perturbed(src, "    return _TURN_REPO_MOVED.get(owner, owner)\n", "    return owner\n", "swg-noded's repo map")
N = types.ModuleType("n")
N.__dict__.update({"__name__": "n", "__file__": "swg-noded"})
exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)

check("[1] the old repo maps to the new one", N._turn_owner_now(OLD) == NEW, N._turn_owner_now(OLD))
check("[1] …another fork's repo, and none, are left as they are",
      N._turn_owner_now("WINGS-N/vk-turn-proxy") == "WINGS-N/vk-turn-proxy" and N._turn_owner_now("") == "")

ran = []
N.run = lambda cmd, timeout=None, **k: (ran.append(cmd), types.SimpleNamespace(returncode=0, stdout="", stderr=""))[1]
N._turn_resolve_tag(OLD)
urls = [a for c in ran for a in c if isinstance(a, str) and a.startswith("https://")]
check("[2] _turn_resolve_tag asks the new repo", urls and all(NEW in u for u in urls), urls)

import urllib.parse
Q_NEW, Q_OLD = urllib.parse.quote(NEW, safe=""), urllib.parse.quote(OLD, safe="")
check("[2] _turn_dl_urls builds every GitHub URL from the new repo",
      all(NEW in u and OLD not in u for u in N._turn_dl_urls(OLD, "amd64", "v4.0.1")), N._turn_dl_urls(OLD, "amd64", "v4.0.1"))

# The network is the only stub: the panel mirror (by repo, like GitHub) misses, so each path also falls through to
# GitHub — and both must name the new repo. The fetch helpers themselves run for real.
mirror, gh = [], []
N._TURN_PANEL = {"url": "https://panel.test", "token": "t"}
N._panel_get = lambda url, token, panel, timeout=None: (mirror.append(url), (404, b"", None))[1]
def run(cmd, timeout=None, **k):
    gh.extend(a for a in cmd if isinstance(a, str) and a.startswith("https://"))
    if "-o" in cmd:
        dest = cmd[cmd.index("-o") + 1]
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w").close()
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
N.run = run
N._turn_arch_ok = lambda: True
N._turn_arch = lambda: "amd64"
N._turn_bin_local = lambda svc: os.path.join(T, "bin", svc, "server")
N._turn_bin_local_legacy = lambda svc: os.path.join(T, "legacy", svc, "server")
N._turn_ver_path = lambda svc: os.path.join(T, "ver", svc)
N._turn_write_version = lambda svc, tag: None
PIN = {"tag": "v4.0.1"}
def asks(what):
    ok = (len(mirror) == 1 and "owner=" + Q_NEW + "&" in mirror[0] and gh and all(NEW in u for u in gh)
          and not any(Q_OLD in u for u in mirror) and not any(OLD in u for u in gh))
    check(what, ok, (mirror, gh))
    del mirror[:], gh[:]
err = N._dturn_download("vk-turn-proxy-samosvalishe-56100", OLD, PIN)
asks("[3] _dturn_download asks the panel mirror, then GitHub, for the new repo" + ("" if not err else " — " + err))
err = N._dturn_force_download("vk-turn-proxy-samosvalishe-56101", OLD, PIN)
asks("[4] _dturn_force_download asks the panel mirror, then GitHub, for the new repo" + ("" if not err else " — " + err))

sh = []
N.host_sh = lambda cmd, timeout=None: (sh.append(cmd), types.SimpleNamespace(returncode=1, stdout="", stderr="stub"))[1]
N._turn_install("vk-turn-proxy-samosvalishe-56102", {"owner": OLD, "listen": "0.0.0.0:56102", "connect": "127.0.0.1:51820",
                                                     "params": "-obf-profile rtpopus -obf-key " + "a" * 64, "pin": PIN})
cmd = next((c for c in sh if "/releases/" in c), "")   # the install script (an earlier call probes the unit dir)
check("[5] _turn_install asks the panel mirror and GitHub for the new repo",
      "github.com/" + NEW + "/releases/" in cmd and len(mirror) == 1 and "owner=" + Q_NEW + "&" in mirror[0], (mirror, cmd[:200]))
check("[5] …writes the new repo to repo.txt and the unit, and the old name is nowhere",
      ("printf %s " + NEW + " > ") in cmd and "vk-turn-proxy (" + NEW + ")" in cmd and OLD not in cmd, cmd[:300])

# ── update.sh: turn_check_one ───────────────────────────────────────────────────────────────────────────────────────
def shell_fn(path, name, perturb=None):
    s = open(os.path.join(ROOT, path), encoding="utf-8").read()
    if perturb:
        s = perturbed(s, perturb, "", path + "'s redirect")
    m = re.search(r"(?ms)^" + name + r"\(\)\{.*?^\}\n", s)
    assert m, name + " not found in " + path
    return m.group(0)

UPD_LINE = ('  [ "$owner" = "samosvalishe/free-turn-proxy" ] && { owner="hackdiaz-dev/free-turn-proxy"; $DRYRUN || printf %s "$owner"'
            ' > "${d}repo.txt" 2>/dev/null || true; }\n')
fn = shell_fn("update.sh", "turn_check_one", UPD_LINE if P_UPDATE else None)
STUBS = r"""
sub(){ :; }; col_l(){ printf %s "$1"; }; col_v(){ printf %s "$1"; }; warn(){ echo "WARN $*"; }; ok(){ echo "OK $*"; }
info(){ :; }; note(){ :; }; confirm(){ return 1; }; run(){ "$@"; }
curl(){ echo "$*" >> "$LOG"; echo '{"tag_name":"v4.0.1"}'; }
DRYRUN=false; FORCE=false
"""
def update_case(owner):
    d = tempfile.mkdtemp(dir=T) + "/"
    open(d + "repo.txt", "w").write(owner)
    open(d + "version.txt", "w").write("v4.0.1")
    log = os.path.join(d, "curl.log")
    out = subprocess.run(["bash", "-c", STUBS + fn + 'turn_check_one samosvalishe "$D" fork'],
                         env=dict(os.environ, LOG=log, D=d), capture_output=True, text=True, timeout=30)
    asked = open(log).read() if os.path.exists(log) else ""
    return asked, open(d + "repo.txt").read().strip(), out.stdout + out.stderr

asked, repo, out = update_case(OLD)
check("[6] update.sh asks GitHub about the new repo", "repos/" + NEW + "/" in asked and OLD not in asked, (asked, out))
check("[6] …and rewrites repo.txt to it", repo == NEW, (repo, out))
asked, repo, out = update_case("WINGS-N/vk-turn-proxy")
check("[6] control: another fork's repo is asked about and left as it is",
      "repos/WINGS-N/vk-turn-proxy/" in asked and repo == "WINGS-N/vk-turn-proxy", (asked, repo, out))

# ── install-node.sh: install_turn_binary (the docker → bare conversion feeds it the record's repo) ─────────────────────
INS_LINE = ('  [ "$owner" = "samosvalishe/free-turn-proxy" ] && owner="hackdiaz-dev/free-turn-proxy"   # repo deleted 2026-10;'
            ' hackdiaz-dev carries it on (a record from before the move names the old one)\n')
fn = shell_fn("install-node.sh", "install_turn_binary", INS_LINE if P_INSTALL else None)
log = os.path.join(T, "dl.log")
out = subprocess.run(["bash", "-c", r"""
warn(){ :; }; info(){ :; }; uname(){ echo x86_64; }
dl_turn_bin(){ echo "$1" >> "$LOG"; return 1; }
DRYRUN=false; PREFIX=""; TURN_DIR="$TD"
""" + fn + 'install_turn_binary samosvalishe "$OLD" 0.0.0.0:56103 127.0.0.1:51820 ""'],
                     env=dict(os.environ, LOG=log, TD=os.path.join(T, "turn"), OLD=OLD), capture_output=True, text=True, timeout=30)
got = open(log).read().split() if os.path.exists(log) else []
check("[7] install-node.sh downloads from the new repo", got == [NEW], (got, out.stdout + out.stderr))

print()
if PERTURB:
    print(("PERTURB OK — %d check(s) went red" % len(FAILS)) if FAILS else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
