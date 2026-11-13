#!/usr/bin/env python3
"""Self-test — a reboot pending is said as one, never as "Update rebuilds it" (user report 2026-11-13, 1.8.12 item 13).

The report: a master on its install kernel 6.8.0-35-generic, whose headers the archive no longer had, with 6.8.0-149-generic
and its DKMS AmneziaWG module installed beside it. The panel said "its kernel module isn't built or loaded; running Update
rebuilds it", and every update spent minutes on a build that could not succeed. A reboot fixed it.

  [1] lib awg_reboot_kernel, driven on a fake /lib/modules + /boot: the newest kernel with an image in /boot, newer than the
      running one, with the module → named; CONTROLS: it has no module · the running kernel has one · a newer kernel without
      the module is the newest · a modules dir with no image (a removed kernel's leftovers) · only an older kernel has one
  [2] update.sh's REAL ensure_awg_datapath, driven: a reboot pending with amneziawg-go → one note naming the kernel, no heal
      (no apt, no clone, no compile); CONTROL: no amneziawg-go → the heal runs as before
  [3] swg-noded node_datapath_health, driven: why=reboot + kernel, ahead of a compile record; CONTROLS: a module for the
      running kernel, a loaded module, a newest kernel without the module → no why=reboot
  [4] the panel's host_datapath_health, driven: the same
  [5] the panel's node sentences (fallback / none), no "update the node"; a name that is not a kernel's → the generic
      sentence; "repair node" not offered for it
  [6] the master's notice: fix:false (no Run update), its own foot and command line; every new sentence has its Russian line
  [7] _kver_key (noded + panel) orders kernel names as `sort -V` does

Run: python3 tests/awg_reboot_pending_selftest.py      (0 = pass)
     --plant upd-noreboot   the update.sh check removed → RED on [2]
     --plant lib-lexsort    `sort` for `sort -V` in awg_reboot_kernel → RED on [1]
     --plant noded-strmax   noded picks the newest kernel by plain string order → RED on [3]
     --plant repair-pill    "repair node" offered for a reboot again → RED on [5]
     --plant lib-headers    awg_reboot_kernel ignores the running kernel's headers (review F1/F2) → RED on [1]
     --plant upd-aptcand    update.sh skips the heal although apt can fetch the headers (review F1) → RED on [2]
     --plant upd-norefresh  the headers candidate read before this run refreshed apt's lists (verify F10) → RED on [2]
     --plant lib-compile    headers alone read as "buildable" though the module is recorded as not compiling (verify F7–F9) → RED
"""
import builtins, importlib.machinery, importlib.util, io, os, re, shutil, subprocess, sys, tempfile
from unittest import mock
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
rd = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read()
FAILS, SEC = [], [0]
def sec(n, title):
    SEC[0] = n; print(("\n" if n > 1 else "") + "[%d] %s" % (n, title))
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append((SEC[0], name))
def plant(src, old, new):
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    return src.replace(old, new)
def grab(path, *names, src=None):
    """Functions as bash itself defines them: the file sourced (definitions only), then `declare -f`."""
    f = os.path.join(ROOT, path)
    if src is not None:
        f = os.path.join(tempfile.mkdtemp(prefix="rbsrc-"), os.path.basename(path)); open(f, "w").write(src)
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; declare -f "${@:2}"', "_", f] + list(names), capture_output=True, text=True)
    assert all((n + " ()") in r.stdout for n in names), "could not read %s from %s: %s" % (names, path, r.stderr[-300:])
    return r.stdout + "\n"
def grab_text(src, name):
    a = src.index("\n" + name + "(){") + 1; b = src.index("\n}\n", a) + 3
    return src[a:b]

OLD, NEW, NEWER = "6.8.0-35-generic", "6.8.0-149-generic", "6.8.0-150-generic"
T = tempfile.mkdtemp(prefix="rbpend-")
def fs(kernels):
    """kernels: {release: (has image in /boot, where its module is: "dkms" | "updates" | "extra" | "net" | None[, its headers])}
    → a fake tree."""
    root = tempfile.mkdtemp(dir=T)
    os.makedirs(root + "/boot"); os.makedirs(root + "/mods")
    for k, (img, mod, *hd) in kernels.items():
        os.makedirs(root + "/mods/" + k + "/kernel")
        if hd and hd[0]:
            os.makedirs(root + "/mods/" + k + "/build")
        if img:
            open(root + "/boot/vmlinuz-" + k, "w").close()
        if mod:
            d = root + "/mods/" + k + {"dkms": "/updates/dkms", "updates": "/updates", "extra": "/extra", "net": "/kernel/drivers/net"}[mod]
            os.makedirs(d, exist_ok=True); open(d + "/amneziawg.ko.zst", "w").close()
    return root

LIBSRC = rd("lib/common.sh")
if PLANT == "lib-headers":
    LIBSRC = plant(LIBSRC, 'if _awg_ko_for "$cur" || { [ -e "$(_awg_kbuild)" ] && ! awg_build_failed_here; }; then return 1; fi', 'if _awg_ko_for "$cur"; then return 1; fi')
if PLANT == "lib-compile":   # round 1's form: headers alone mean "buildable" (verify F7–F9)
    LIBSRC = plant(LIBSRC, '{ [ -e "$(_awg_kbuild)" ] && ! awg_build_failed_here; }', '[ -e "$(_awg_kbuild)" ]')
if PLANT == "lib-lexsort":
    LIBSRC = plant(LIBSRC, '''new="$(printf '%s\\n%s\\n' "$new" "$k" | sort -V | tail -n1)"''', '''new="$(printf '%s\\n%s\\n' "$new" "$k" | sort | tail -n1)"''')
    LIBSRC = plant(LIBSRC, '''[ "$(printf '%s\\n%s\\n' "$cur" "$new" | sort -V | tail -n1)" = "$new" ]''', '''[ "$(printf '%s\\n%s\\n' "$cur" "$new" | sort | tail -n1)" = "$new" ]''')
LIB = grab("lib/common.sh", "_awg_ko_for", "_awg_kbuild", "awg_reboot_kernel", "awg_build_failed_here", "awg_fail_get",
           "awg_mod_built", "awg_mod_key_rejected", src=LIBSRC)
def lib(root, body, running=OLD):
    stubs = ('uname(){ [ "$1" = -r ] && echo %s || command uname "$@"; }\nDRYRUN=false\nAWG_MOD_FAILED="$T/awg-module-failed"\n') % running
    return subprocess.run(["bash", "-c", stubs + LIB + body], capture_output=True, text=True,
                          env=dict(os.environ, T=T, SWG_LIB_MODULES=root + "/mods", SWG_BOOT=root + "/boot"))
Q = 'k="$(awg_reboot_kernel)" && echo "K=$k" || echo NONE'

sec(1, "lib awg_reboot_kernel")
r = lib(fs({OLD: (True, None), NEW: (True, "dkms")}), Q)
check("the report's box: running 6.8.0-35 with no module, 6.8.0-149 installed with its DKMS module → 6.8.0-149", "K=" + NEW in r.stdout, r.stdout + r.stderr)
r = lib(fs({OLD: (True, None), NEW: (True, "net")}), Q)
check("…a module `make install` put in kernel/drivers/net counts too", "K=" + NEW in r.stdout, r.stdout + r.stderr)
r = lib(fs({OLD: (True, None), NEW: (True, "extra")}), Q)
check("…and one in extra/ (an external module's modules_install) (review F4)", "K=" + NEW in r.stdout, r.stdout + r.stderr)
check("CONTROL: the running kernel's headers are here → nothing (a build can still give it a module now, review F1/F2)",
      "NONE" in lib(fs({OLD: (True, None, True), NEW: (True, "dkms")}), Q).stdout)
def failrec(on, kernel=OLD):
    f = T + "/awg-module-failed"
    if on:
        open(f, "w").write("kernel=%s\nsrc=abc1234\n" % kernel)
    elif os.path.exists(f):
        os.remove(f)
failrec(True)
r = lib(fs({OLD: (True, None, True), NEW: (True, "dkms")}), Q)
check("…headers here but the module recorded as not compiling on the running kernel → 6.8.0-149 (the reboot is the only fix, verify F7–F9)",
      "K=" + NEW in r.stdout, r.stdout + r.stderr)
failrec(True, kernel="6.8.0-1-generic")
check("CONTROL: a compile record for ANOTHER kernel does not count", "NONE" in lib(fs({OLD: (True, None, True), NEW: (True, "dkms")}), Q).stdout)
failrec(False)
check("CONTROL: the newer kernel has no module → nothing (a reboot would not help)", "NONE" in lib(fs({OLD: (True, None), NEW: (True, None)}), Q).stdout)
check("CONTROL: the running kernel has the module → nothing", "NONE" in lib(fs({OLD: (True, "dkms"), NEW: (True, "dkms")}), Q).stdout)
check("CONTROL: the NEWEST kernel (150) has no module, 149 has → nothing (GRUB boots 150)",
      "NONE" in lib(fs({OLD: (True, None), NEW: (True, "dkms"), NEWER: (True, None)}), Q).stdout)
check("CONTROL: 149's modules dir is a removed kernel's leftover (no image in /boot) → nothing",
      "NONE" in lib(fs({OLD: (True, None), NEW: (False, "dkms")}), Q).stdout)
check("CONTROL: running the newest, only an older kernel has the module → nothing",
      "NONE" in lib(fs({OLD: (True, "dkms"), NEW: (True, None)}), Q, running=NEW).stdout)
check("CONTROL: no kernels listed at all → nothing", "NONE" in lib(fs({}), Q).stdout)

sec(2, "update.sh's heal, driven")
USRC = rd("update.sh")
if PLANT == "upd-aptcand":
    USRC = plant(USRC, '[ -z "$_hc" ] || [ "$_hc" = "(none)" ]; }; }; then', 'true; }; }; then')
if PLANT == "upd-norefresh":   # verify F10: the candidate read from lists this run did not refresh
    USRC = plant(USRC, '{ apt_refresh; _hc="$(pkg_candidate', '{ _hc="$(pkg_candidate')
if PLANT == "upd-noreboot":
    USRC = plant(USRC, 'if [ "$_tools" = yes ] && have amneziawg-go && _rk="$(awg_reboot_kernel)" \\\n', 'if false && \\\n')
PKGC = next(ln for ln in USRC.splitlines() if ln.startswith("pkg_candidate(){")) + "\n"   # the updater's own parser (review F13)
FN = grab_text(USRC, "ensure_awg_datapath")
HEAL = ('set -euo pipefail\nDRYRUN=false; HAVE_BNODE=yes; DID_UPDATE=no; DID_FAIL=no\n'
        'ok(){ echo "OK $*"; }\ninfo(){ echo "INFO $*"; }\nwarn(){ echo "WARN $*"; }\nnote(){ echo "NOTE $*"; }\n'
        'run(){ echo "RUN $*" >> "$T/calls"; }\n'
        'git_clone_depth1(){ echo "CLONE $1" >> "$T/calls"; return 1; }\n'
        'modprobe(){ echo "modprobe: FATAL: Module amneziawg not found" >&2; return 1; }\nmodinfo(){ return 1; }\n'
        'have(){ case "$1" in awg|awg-quick|dkms|apt-cache) return 0;; amneziawg-go) [ -e "$T/go" ];; *) command -v "$1" >/dev/null 2>&1;; esac; }\n'
        'awg_compat_patch_installed(){ return 1; }\nawg_go_needs_install(){ return 1; }\nawg_blacklisted(){ return 1; }\n'
        'awg_nothing_new(){ return 1; }\nawg_ppa_suite(){ echo "HEAL-PPA" >> "$T/calls"; return 1; }\n'
        'awg_build_from_source(){ echo "HEAL-BUILD" >> "$T/calls"; return 1; }\nensure_awg_userspace(){ return 0; }\n'
        'awg_key_refused_here(){ return 1; }\nawg_tools_drive_3x(){ return 0; }\n'
        # apt's lists as this run's refresh leaves them: $T/cand-stale is a candidate only the UNrefreshed lists still name
        'apt_refresh(){ echo "APT" >> "$T/calls"; rm -f "$T/cand-stale"; }\n'
        'apt-cache(){ if [ -e "$T/cand" ] || [ -e "$T/cand-stale" ]; then printf "  Installed: (none)\\n  Candidate: 6.8.0-35.35\\n"; '
        'else printf "  Installed: (none)\\n  Candidate: (none)\\n"; fi; }\n') + PKGC
def heal(root, go, cand=False, stale=False):
    for f in ("calls", "go", "cand", "cand-stale"):
        if os.path.exists(T + "/" + f):
            os.remove(T + "/" + f)
    if go:
        open(T + "/go", "w").close()
    if cand:
        open(T + "/cand", "w").close()
    if stale:
        open(T + "/cand-stale", "w").close()
    r = lib(root, HEAL + FN + 'ensure_awg_datapath; echo "RC=$?"\n')
    c = open(T + "/calls").read() if os.path.exists(T + "/calls") else ""
    return r, c
PEND = fs({OLD: (True, None), NEW: (True, "dkms")})
r, c = heal(PEND, go=True)
check("a reboot pending, amneziawg-go serving → one note naming 6.8.0-149 and 'reboot', the run ends there",
      "RC=0" in r.stdout and ("NOTE AmneziaWG: the kernel module is ready for kernel %s" % NEW) in r.stdout and "reboot this server" in r.stdout,
      r.stdout + r.stderr)
check("…no heal: no package route, no clone, no compile, no 'healing' line — one refresh of apt's lists, nothing else",
      c == "APT\n" and "healing" not in r.stdout, c + r.stdout)
r, c = heal(PEND, go=True, stale=True)
check("…a candidate only the stale lists still name: the lists are refreshed first, then the reboot note (verify F10)",
      "reboot this server" in r.stdout and "healing" not in r.stdout and c.startswith("APT"), r.stdout + c)
failrec(True)
r, c = heal(fs({OLD: (True, None, True), NEW: (True, "dkms")}), go=True, cand=True)
check("headers here AND to be had, but the module recorded as not compiling → the reboot note, not 'does not compile' (verify F9)",
      "reboot this server" in r.stdout and "healing" not in r.stdout and "HEAL" not in c, r.stdout + c)
failrec(False)
r, c = heal(PEND, go=False)
check("CONTROL: no amneziawg-go → the heal runs as before (the interfaces need a datapath now)",
      "healing the AmneziaWG kernel module" in r.stdout and "HEAL-BUILD" in c, r.stdout + c)
r, c = heal(PEND, go=True, cand=True)
check("CONTROL: apt can still fetch the running kernel's headers → the heal runs (it builds the module now, review F1)",
      "healing the AmneziaWG kernel module" in r.stdout and "reboot this server" not in r.stdout, r.stdout + c)
r, c = heal(fs({OLD: (True, None), NEW: (True, None)}), go=True)
check("CONTROL: no kernel with the module → the heal runs as before", "healing the AmneziaWG kernel module" in r.stdout, r.stdout + c)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
_NODED = os.path.join(ROOT, "swg-noded")
if PLANT == "noded-strmax":
    _p = os.path.join(tempfile.mkdtemp(prefix="rbplant-"), "swg-noded")
    open(_p, "w").write(plant(rd("swg-noded"), "    new = max(ks, key=_kver_key)\n    return new if _kver_key(new) > _kver_key(kr) and _awg_ko_for(new) else \"\"",
                              "    new = max(ks)\n    return new if new > kr and _awg_ko_for(new) else \"\""))
    _NODED = _p
PSRC = rd("swg-panel-server")
_PANEL = os.path.join(ROOT, "swg-panel-server")
if PLANT == "repair-pill":
    _p = os.path.join(tempfile.mkdtemp(prefix="rbplant-"), "swg-panel-server")
    PSRC = plant(PSRC, ' and not _awg_reboot_why(_awg_datapath(snap))\n', '\n')
    open(_p, "w").write(PSRC); _PANEL = _p
N = load("swgnoded", _NODED)
P = load("swgpanel", _PANEL)

class FakeFS:
    """/lib/modules, /boot and /proc/modules as the tree in `root` says — for code that reads the real paths."""
    def __init__(self, root, loaded=False):
        self.root, self.loaded = root, loaded
    def _map(self, p):
        for a, b in (("/lib/modules", "/mods"), ("/boot", "/boot")):
            if p == a or p.startswith(a + "/"):
                return self.root + b + p[len(a):]
        return None
    def __enter__(self):
        ro, rl, re_, ra = builtins.open, os.listdir, os.path.exists, os.access
        def fopen(p, *a, **k):
            return io.StringIO("amneziawg 123 0 - Live\n" if self.loaded else "") if p == "/proc/modules" else ro(p, *a, **k)
        def flist(d):
            m = self._map(d)
            if m is None:
                raise FileNotFoundError(d)
            return rl(m)
        def fexists(p):
            m = self._map(p)
            return re_(m) if m is not None else p == "/usr/bin/awg"
        self.ps = [mock.patch("builtins.open", fopen), mock.patch("os.listdir", flist), mock.patch("os.path.exists", fexists),
                   mock.patch("os.access", lambda p, m: p == "/usr/local/bin/amneziawg-go"),
                   mock.patch("os.uname", lambda: os.uname_result(("Linux", "h", OLD, "#1", "x86_64")))]
        for x in self.ps:
            x.start()
        return self
    def __exit__(self, *a):
        for x in self.ps:
            x.stop()

sec(3, "swg-noded node_datapath_health")
def nh(root, loaded=False, why=(None, ""), rec=False):
    with FakeFS(root, loaded), mock.patch.object(N, "NODE_KIND", "bare"), mock.patch.object(N, "_awg_unloadable_why", lambda b: why), \
         mock.patch.object(N, "_awg_record", lambda n: {"kernel": OLD} if rec and n == "awg-module-failed" else None):
        return (N.node_datapath_health({"awg0": {"meta": {"tool": "awg"}}}) or {}).get("awg") or {}
a = nh(PEND)
check("the report's box → not ok, fallback, why=reboot, kernel=6.8.0-149", a.get("ok") is False and a.get("fallback") is True
      and a.get("why") == "reboot" and a.get("kernel") == NEW, a)
a = nh(PEND, why=("compile", ""))
check("…ahead of a compile record (the reboot fixes a running kernel that does not compile it, too)", a.get("why") == "reboot", a)
a = nh(fs({OLD: (True, None), NEW: (True, "dkms"), "6.8.0-99-generic": (True, None)}))
check("…149 over 99 and 35: numbers by value, not by text", a.get("kernel") == NEW, a)
a = nh(fs({OLD: (True, "dkms"), NEW: (True, "dkms")}))
check("CONTROL: a module for the running kernel → ok, no why", a.get("ok") is True and "why" not in a, a)
a = nh(fs({OLD: (True, None, True), NEW: (True, "dkms")}))
check("CONTROL: the running kernel's headers are here → no why=reboot (an update builds it now, review F2)",
      a.get("ok") is False and "why" not in a, a)
a = nh(fs({OLD: (True, None, True), NEW: (True, "dkms")}), why=("compile", ""), rec=True)
check("…headers here but the module recorded as not compiling → why=reboot, ahead of compile (verify F7)",
      a.get("why") == "reboot" and a.get("kernel") == NEW, a)
a = nh(PEND, loaded=True)
check("CONTROL: the module loaded → ok, no why", a.get("ok") is True and "why" not in a, a)
a = nh(fs({OLD: (True, None), NEW: (True, "dkms"), NEWER: (True, None)}))
check("CONTROL: the newest kernel has no module → no why=reboot (the generic sentence stands)", a.get("ok") is False and "why" not in a
      and "kernel" not in a, a)

sec(4, "the panel's host_datapath_health")
def ph(root, loaded=False, rec=False):
    P._DATAPATH_SVC.update(at=0.0, data={})
    with FakeFS(root, loaded), mock.patch.object(P, "IN_DOCKER", False), \
         mock.patch.object(P, "_host_awg_record", lambda n: {"kernel": OLD} if rec and n == "awg-module-failed" else None):
        return (P.host_datapath_health() or {}).get("awg") or {}
a = ph(PEND)
check("the report's box → not ok, why=reboot, kernel=6.8.0-149", a.get("ok") is False and a.get("why") == "reboot" and a.get("kernel") == NEW, a)
a = ph(fs({OLD: (True, "updates"), NEW: (True, "dkms")}))
check("CONTROL: a module for the running kernel → ok, no why", a.get("ok") is True and "why" not in a, a)
a = ph(fs({OLD: (True, None, True), NEW: (True, "dkms")}))
check("CONTROL: the running kernel's headers are here → no why=reboot", a.get("ok") is False and "why" not in a, a)
a = ph(fs({OLD: (True, None, True), NEW: (True, "dkms")}), rec=True)
check("…headers here but the module recorded as not compiling → why=reboot, not compile (verify F8)",
      a.get("why") == "reboot" and a.get("kernel") == NEW, a)
a = ph(fs({OLD: (True, None), NEW: (True, None)}))
check("CONTROL: no kernel has the module → not ok, no why", a.get("ok") is False and "why" not in a, a)

sec(5, "the panel's node sentences")
def issues(**awg):
    return [i["error"] for i in P._node_issues({"id": "n1", "name": "n1"}, {"datapath": {"awg": dict(needed=True, ok=False, **awg)}})]
i = issues(fallback=True, why="reboot", kernel=NEW)
check("fallback → ready for kernel 6.8.0-149, slower datapath until rebooted, no 'update the node'", len(i) == 1
      and ("ready for kernel %s" % NEW) in i[0] and "slower fallback" in i[0] and "rebooted" in i[0] and "update the node" not in i[0]
      and "cannot fix" not in i[0], i)
i = issues(fallback=False, why="reboot", kernel=NEW)
check("no fallback → can't come up until rebooted", len(i) == 1 and "can't come up until the node is rebooted" in i[0], i)
i = issues(fallback=True, why="reboot", kernel="6.8; reboot now")
check("a name that is not a kernel's → the generic sentence, the name never shown", len(i) == 1 and "update the node to rebuild" in i[0]
      and "reboot now" not in i[0], i)
check("'repair node' is not offered for a reboot pending (nor for Secure Boot) — decided by the same helper as the sentence",
      '_awg_datapath(snap).get("needed") and _awg_datapath(snap).get("why") != "key" and not _awg_reboot_why(_awg_datapath(snap))\n' in PSRC)
check("…which counts only a kernel-shaped name: a bad or missing one reads as the generic case for both (review F3)",
      P._awg_reboot_why({"why": "reboot", "kernel": NEW}) == NEW and P._awg_reboot_why({"why": "reboot", "kernel": "6.8; x"}) == ""
      and P._awg_reboot_why({"why": "reboot"}) == "" and P._awg_reboot_why({"why": "key", "kernel": NEW}) == "")

sec(6, "the master's notice")
VS, OV, ru = rd("js/views.js"), rd("js/screen-overview.js"), rd("js/lang/ru.js")
m = re.search(r'else if \(dp\.why === "reboot" && dp\.kernel\) add\("awg", dp\.fallback \? "warn" : "critical", "reboot",(.*?)\), false\);', VS, re.S)
check("views.js: why=reboot → its own issue, marked fix:false (no Run update, no Fix count)", bool(m))
check("…asked before 'compile'", 0 < VS.index('dp.why === "reboot"') < VS.index('dp.why === "compile"'))
check("the sheet: its own command line and foot for it",
      'i.fix === false && i.kind === "reboot" ? html`<div class="svc-cmd"><code>uname -r</code> · <code>dkms status</code></div>`' in OV
      and 'noUpdate && list.every(i => i.id === "subcert" || i.kind === "reboot") ? T("A reboot fixes this — the kernel module is built' in OV)
keys = re.findall(r'T\(("[^"]*(?:ready for kernel|the reboot starts it)[^"]*")', VS + OV)
keys += re.findall(r'(?:perr\(|if _dp\.get\("fallback"\) else\s+)("AmneziaWG: the kernel module is ready[^"]*")', PSRC)
check("every new sentence (%d) has its Russian line" % len(keys), len(keys) == 5 and all(("  " + k + ":") in ru for k in keys),
      [k[:60] for k in keys if ("  " + k + ":") not in ru] or len(keys))

sec(7, "_kver_key orders as `sort -V`")
names = ["6.8.0-35-generic", "6.8.0-149-generic", "6.8.0-99-generic", "6.1.0-53-cloud-amd64", "6.12.0-1-amd64", "5.15.0-140-generic",
         "6.8.0-149-lowlatency", "7.0.0-38-generic", "6.10.0-9-generic"]
sv = subprocess.run(["sort", "-V"], input="\n".join(names) + "\n", capture_output=True, text=True).stdout.split()
check("noded: the same order as sort -V", sorted(names, key=N._kver_key) == sv, (sorted(names, key=N._kver_key), sv))
check("panel: the same order as sort -V", sorted(names, key=P._kver_key) == sv, (sorted(names, key=P._kver_key), sv))

shutil.rmtree(T, ignore_errors=True)
if PLANT:
    want = {"upd-noreboot": {2}, "upd-aptcand": {2}, "upd-norefresh": {2}, "lib-lexsort": {1, 2}, "lib-headers": {1, 2},
            "lib-compile": {1, 2}, "noded-strmax": {3},
            "repair-pill": {5}}[PLANT]   # lexsort: [2] drives the same lib
    got = {n for n, _ in FAILS}
    print("\nplant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(FAILS), sorted(got))) if FAILS and got <= want
                                     else "NOT CAUGHT — the gate is blind to it" if not FAILS else "ALSO red elsewhere: %s" % FAILS))
    sys.exit(0 if FAILS and got <= want else 1)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
sys.exit(1 if FAILS else 0)
