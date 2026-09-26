#!/usr/bin/env python3
"""Self-test — THE PANEL SERVES acme.sh's RENEWED CERTIFICATE, WHOEVER THE ENTRY INSTALLS FOR.

acme.sh gives each name ONE install target. 3x-ui's certificate menu re-points our entry at /root/cert/ip, and
from then on every renewal went there while the panel served its last copy until it expired (a 6-day IP
certificate, seen live 2026-09-25). `swg-netctl sync-acme` reads the renewed certificate out of the entry and
installs it when it is newer — and must never touch the entry or the other tool's files.

Also pins the IP-SAN half (B): an IP certificate names its address ONLY as an `IP Address` SAN, and both the
helper's and the panel's coverage checks read DNS names alone, so no IP certificate ever "covered" its panel.
And the short-lived judgement (C): a ~6.7-day certificate is overdue past 2/3 of its life, not at ≤21 days.

Real certificates (openssl), a fake acme store and a fake 3x-ui target in a temp dir; no root, no network.

Run: python3 tests/acme_follow_selftest.py      (0 = pass)
     --perturb   every plant below (each a fix taken back out) must turn ITS OWN check red ("N plants, N caught").
"""
import ast, contextlib, io, hashlib, importlib.machinery, importlib.util, json, os, shutil, ssl, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
# every source this test reads, overridable so --perturb can hand it a planted copy
SRCS = {"NETCTL": "swg-netctl", "PANEL": "swg-panel-server", "INSTALL_HOST": "install-host.sh",
        "UPDATE": "update.sh", "UI_JS": "js/ui.js", "CONVERT": "convert.sh"}
PATHS = {k: os.environ.get("SWG_AF_" + k) or os.path.join(ROOT, v) for k, v in SRCS.items()}

# (file key, anchor, replacement, the check that must go red)
PLANTS = [
    # 1.8.8 qualification: the SIGHUP handler is installed FIRST in main() — an acme renewal's reload during the
    # migrations / store loads / ledger start took the default action and killed the panel (a clean exit to systemd)
    ("PANEL", "    with contextlib.suppress(ValueError, OSError, AttributeError):\n        signal.signal(signal.SIGHUP, _sighup_reload)\n",
     "",
     "SIGHUP is handled from the top of main(), before the migrations, the loads and the ledger start"),
    ("PANEL", "self._lock = threading.RLock(); self._by_id = {}; self._seq = 0",
     "self._lock = threading.Lock(); self._by_id = {}; self._seq = 0",
     "the listener registry lock is re-entrant (the SIGHUP handler takes it on the main thread)"),
    ("NETCTL", '    d = _acme_ecc_dir(host)                                    # panel drops a report about a name it no longer serves\n    if d is None or not _acme_entry_usable(d, host):\n        res["state"] = "no-entry"',
     '    d = None\n    if d is None or not _acme_entry_usable(d, host):\n        res["state"] = "no-entry"',
     "the newer certificate is adopted"),
    # review 2026-09-25 #6: a request is TAKEN before it runs, so a long one is never withdrawn
    ("NETCTL", "            where = qfd\n            if cfd is not None:", "            where = qfd\n            if False:",
     "a renewal the helper is still RUNNING after the pickup window is never withdrawn"),
    # …and the claim leaves the WATCHED dir (DirectoryNotEmpty, no start limit → a leftover claim would spin the helper)
    ("NETCTL", "                    os.rename(name, name, src_dir_fd=qfd, dst_dir_fd=cfd)\n                    where = cfd",
     "                    os.rename(name, name + \".taking\", src_dir_fd=qfd, dst_dir_fd=qfd)\n                    name = name + \".taking\"; where = qfd",
     "while a request runs, the watched queue dir is EMPTY (a leftover claim there would re-trigger the helper forever)"),
    # #1: a self-signed served certificate is held, never swapped under pinned nodes
    ("NETCTL", '    if service == "panel" and cur_self and new_end is not None:\n        res["state"], res["reason"] = "held"',
     '    if False:\n        res["state"], res["reason"] = "held"', "a self-signed served certificate is HELD, never swapped (nodes may have pinned it)"),
    ("NETCTL", '    if service == "panel" and cur_self and new_end is not None:', '    if cur_self and new_end is not None:',
     "swg-sub's self-signed certificate is NOT held (nothing pins it) — it yields to the CA certificate"),
    # #4: drop-cert keeps a name the other service still uses
    ("NETCTL", "        if serves or (targets & mine):", "        if False:",
     "drop-cert panel <old name> keeps the entry while swg-sub still SERVES that name"),
    # #3: every report carries its host
    ("NETCTL", '    res["host"] = host                                         # on EVERY report', '    pass                                         # on EVERY report',
     "a no-entry report says which name it is about"),
    # #2: the installer's reload is a HUP; update heals the old restart
    ("INSTALL_HOST", 'chmod 640 $TLS_DIR/key.pem; systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true"; then',
     'chmod 640 $TLS_DIR/key.pem; systemctl restart swg-panel-server"; then', "the installer's acme reload command is a SIGHUP, never a restart"),
    ("UPDATE", 'new = pat.sub("systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true", cmd)', 'new = cmd',
     "update heals an entry's `systemctl restart swg-panel-server` into a SIGHUP"),
    # #7: TLS_STATUS swapped whole
    ("PANEL", ["        with _TLS_LOCK:                          # swapped in whole — a poll never sees it half-built\n            TLS_STATUS.clear()\n            TLS_STATUS.update(new)",
               "    with _TLS_LOCK:\n        _refresh_tls_status_locked(quiet)"],
     ["        TLS_STATUS.clear()\n        time.sleep(0.0005)\n        TLS_STATUS.update(new)", "    _refresh_tls_status_locked(quiet)"],
     "a poll never sees TLS_STATUS half-built"),
    # #3: a SIGHUP asks for a follow
    ("PANEL", "it only sets an Event (see _acme_follow_soon).\n    _acme_follow_soon()", "it only sets an Event (see _acme_follow_soon).\n    pass",
     "a SIGHUP (every certificate change) asks for a follow"),
    # #8: the pinned bubble stands aside for a layer on top
    ("UI_JS", "      if (modalDepth() !== depthAtPin) return;\n", "", "a pinned bubble lets a layer opened on top of it take Escape"),
    # review 3
    ("NETCTL", '    try:\n        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)',
     '    try:\n        return os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=dir_fd)',
     "status/ swapped for a symlink: root never writes through it (the answer lands in a fresh root-owned status/)"),
    ("NETCTL", "            if st.st_uid == os.geteuid() and not (st.st_mode & 0o022):\n                return fd",
     "            if True:\n                return fd", "a claims/ dir that is not root's own is never used — moved aside, a fresh 0700 one made"),
    ("NETCTL", "    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)",
     "    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)", "a FIFO in the queue cannot wedge the helper (read O_NONBLOCK, checked on the fd)"),
    ("NETCTL", '        _sweep(qfd, 0, keep=lambda n: n.endswith(".json") or (n.endswith(".json.tmp") and not _older(qfd, n, 60)))',
     "        pass", "the watched queue dir is cleared of what is not a request (an old claim, an abandoned .tmp)"),
    ("NETCTL", "            _sweep(sfd, 3600)", "            pass", "answers older than an hour are swept (the panel, group-only on status/, cannot delete them)"),
    ("NETCTL", "        if not names:\n            return ", "        if False:\n            return ", "an idle tick (empty queue) does nothing and logs nothing"),
    ("NETCTL", "            if d and (targets & here) and not DRYRUN:", "            if False:",
     "a kept entry that still installs into the PANEL's paths is moved to swg-sub's (else its renewal overwrites the panel)"),
    ("NETCTL", '            res["swap_at"] = _acme_conf_value(d, host, "Le_NextRenewTimeStr") or "its next renewal"', "            pass",
     "held, but acme.sh's OWN target is the panel's path: say when acme.sh will install over it"),
    ("PANEL", "    with _TLS_LOCK:\n        _refresh_tls_status_locked(quiet)", "    _refresh_tls_status_locked(quiet)",
     "a slow rebuild from the OLD certificate never lands after a newer one"),
    ("PANEL", "        with _FOLLOW_RUN:\n            _FOLLOW_KICK.clear()", "        _FOLLOW_KICK.clear()\n        with _FOLLOW_RUN:",
     "certificate changes that queue behind a running follow are answered by ONE follow"),
    ("UPDATE", 'pat = re.compile(r"systemctl restart swg-panel-server(?:\\.service)?(?=\\s*(?:;|&&|\\|\\||$))")',
     'pat = re.compile(r"systemctl restart swg-panel-server")', "…and heals the `.service` spelling to exactly the SIGHUP (no `|| true.service`)"),
    ("CONVERT", "Le_ReloadCmd='systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true'", "Le_ReloadCmd='systemctl restart swg-panel-server'",
     "a docker→bare convert stores the SIGHUP too, never the restart"),
    ("NETCTL", '        serves = _service_host(other) == domain.lower() and _load_access_tls()["mode"] in _ACME_FOLLOW_MODES',
     "        serves = _service_host(other) == domain.lower()",
     "under `skip` swg-sub serves the operator's own certificate: the old name is dropped, never moved onto it"),
    ("PANEL", "        with contextlib.suppress(Exception):\n            _refresh_tls_status(quiet=True)   # the new certificate on screen NOW",
     "        with contextlib.suppress(Exception):\n            pass   # the new certificate on screen NOW",
     "…and the new certificate is on screen at once: the status refresh does not wait for the follow lock"),
    # earlier fixes in this series, kept planted so they cannot quietly come undone
    # killing only acme.sh leaves its child holding the output pipe: communicate() then blocks until the child exits
    # on its own — the helper hangs for the child's whole life, which is what "promptly" catches
    ("NETCTL", "            os.killpg(p.pid, signal.SIGKILL)", "            p.kill()", "run(timeout): a hung command is stopped with rc 124, promptly"),
    ("NETCTL", '    env["ACME_FORCE_COLOR"] = "1"\n', "", "acme.sh is asked for colour (it prints red only on a TTY) — the red lines are how its reason is found"),
    ("PANEL", "            os.unlink(queued)\n            return False,", "            return False,", "a request the root helper never takes is withdrawn from its queue, and the job says so"),
    ("PANEL", '        if svc == "panel" and ok and r and not r.get("transient"):', '        if svc == "panel":', "the last report survives an 'address change in flight' skip"),
]

if "--perturb" in sys.argv:
    caught, bad = 0, []
    for key, old, new, must in PLANTS:
        src = open(PATHS[key], encoding="utf-8").read()
        edits = list(zip(old, new)) if isinstance(old, (list, tuple)) else [(old, new)]   # several edits = one plant
        stale = [o for o, _n in edits if src.count(o) != 1]
        if stale:
            bad.append("%s: anchor found %d times (stale plant) — %s" % (key, src.count(stale[0]), must)); continue
        for o, n_ in edits:
            src = src.replace(o, n_)
        with tempfile.NamedTemporaryFile("w", suffix="-plant", delete=False) as f:
            f.write(src)
        try:
            r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_AF_" + key: f.name}),
                               capture_output=True, text=True, timeout=300)
            red = ("  FAIL " + must) in r.stdout and r.returncode != 0
        except subprocess.TimeoutExpired as e:        # the plant hung the run — a wedge IS the failure it plants
            r = subprocess.CompletedProcess([], 1, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "")
            red = True
        os.unlink(f.name)
        print("  %-13s %s — %s" % (key, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT"), must[:70]))
        caught += red
        if not red:
            bad.append(must)
    print("%d plants, %d caught" % (len(PLANTS), caught))
    for b_ in bad:
        print("  ✗ " + b_)
    sys.exit(0 if caught == len(PLANTS) and not bad else 1)

FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="acmefollow-")
ETC, STATE, SUBTLS, ACME, OTHER = (os.path.join(TMP, d) for d in ("etc", "state", "subtls", "acme", "x-ui-cert"))
for d in (ETC, STATE, SUBTLS, ACME, OTHER, os.path.join(ETC, "tls")):
    os.makedirs(d, exist_ok=True)
os.environ.update({"SWG_ETC_DIR": ETC, "SWG_STATE_DIR": STATE, "SWG_SUB_TLS_DIR": SUBTLS, "LE_WORKING_DIR": ACME,
                   "SWG_NETCTL_STATE": os.path.join(TMP, "root-netctl")})


def sh(*a):
    subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# a CA, so leaves are CA-issued (issuer != subject) like Let's Encrypt's
CA_KEY, CA_CRT = os.path.join(TMP, "ca.key"), os.path.join(TMP, "ca.crt")
sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", CA_KEY)
sh("openssl", "req", "-x509", "-new", "-key", CA_KEY, "-days", "30", "-subj", "/CN=Test CA", "-out", CA_CRT)


def leaf(tag, san, days):
    """(fullchain path, key path) of a CA-issued leaf with an empty subject — the shape of an LE IP cert."""
    key, csr, crt, ext = (os.path.join(TMP, "%s.%s" % (tag, x)) for x in ("key", "csr", "crt", "ext"))
    sh("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", key)
    sh("openssl", "req", "-new", "-key", key, "-subj", "/", "-out", csr)
    open(ext, "w").write("subjectAltName=critical," + san + "\n")
    sh("openssl", "x509", "-req", "-in", csr, "-CA", CA_CRT, "-CAkey", CA_KEY, "-CAcreateserial",
       "-days", str(days), "-extfile", ext, "-out", crt)
    fc = crt + ".full"
    open(fc, "w").write(open(crt).read() + open(CA_CRT).read())
    return fc, key


def selfsigned(tag, san, days):
    key, crt = os.path.join(TMP, tag + ".key"), os.path.join(TMP, tag + ".crt")
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", str(days), "-subj", "/CN=" + tag,
       "-addext", "subjectAltName=" + san, "-keyout", key, "-out", crt)
    return crt, key


IP = "5.252.226.186"
OLD = leaf("old", "IP:" + IP, 1)          # what the panel serves: the last renewal that reached it
NEW = leaf("new", "IP:" + IP, 6)          # what acme.sh renewed since, delivered to 3x-ui's path
WRONG = leaf("wrong", "IP:198.51.100.7", 6)
V6 = leaf("v6", "IP:2001:db8::1", 6)
DNS = leaf("dns", "DNS:panel.example.com", 6)

# ── the helper, loaded as a module (optionally with sync-acme blinded to the entry, as before the fix) ──
SRC = open(PATHS["NETCTL"], encoding="utf-8").read()
_fd, NPATH = tempfile.mkstemp(suffix=".py", prefix="netctl-", dir=TMP)
os.write(_fd, SRC.encode()); os.close(_fd)
_l = importlib.machinery.SourceFileLoader("netctl_af", NPATH)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("netctl_af", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
HUPS = []
N.run = lambda argv, env=None, timeout=None: (HUPS.append(argv) or (0, ""))
SERVED, SERVED_KEY = N.SERVICES["panel"]["cert"], N.SERVICES["panel"]["key"]


def settings(host, mode="letsencrypt-ip"):
    json.dump({"access": {"panel": {"url": "https://%s" % host}, "tls": {"mode": mode}}},
              open(os.path.join(STATE, "panel-settings.json"), "w"))


def entry(name, cert, key, target, **extra):
    """An acme.sh store entry for `name` whose install target is `target` (3x-ui's path, or ours)."""
    d = os.path.join(ACME, name + "_ecc")
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    shutil.copyfile(cert, os.path.join(d, "fullchain.cer"))
    shutil.copyfile(cert, os.path.join(d, name + ".cer"))
    shutil.copyfile(key, os.path.join(d, name + ".key"))
    open(os.path.join(d, name + ".conf"), "w").write(
        "Le_Domain='%s'\nLe_RealFullChainPath='%s'\nLe_ReloadCmd='__ACME_BASE64__START_eA==__ACME_BASE64__END_'\n"
        % (name, target) + "".join("%s='%s'\n" % kv for kv in extra.items()))
    return d


def serve(cert, key):
    shutil.copyfile(cert, SERVED); shutil.copyfile(key, SERVED_KEY)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def tree(d):
    return {f: sha(os.path.join(d, f)) for f in sorted(os.listdir(d))}


def sync():
    del HUPS[:]
    return json.loads(N.do_sync_acme("panel"))


print("sync-acme — an entry another tool took over")
settings(IP)
serve(*OLD)
shutil.copyfile(NEW[0], os.path.join(OTHER, "fullchain.pem")); shutil.copyfile(NEW[1], os.path.join(OTHER, "privkey.pem"))
d = entry(IP, NEW[0], NEW[1], os.path.join(OTHER, "fullchain.pem"))
before_entry, before_other = tree(d), tree(OTHER)
r = sync()
check("the newer certificate is adopted", r.get("state") == "adopted", r)
check("the panel now serves acme.sh's renewal", sha(SERVED) == sha(NEW[0]) and sha(SERVED_KEY) == sha(NEW[1]))
check("the owner is reported as another program, with its path",
      r.get("owner") == "other" and r.get("install_path") == os.path.join(OTHER, "fullchain.pem"), r)
check("the panel is reloaded (SIGHUP) exactly once", len(HUPS) == 1 and "HUP" in HUPS[0], HUPS)
check("acme's entry is untouched (read-only)", tree(d) == before_entry)
check("the other program's files are untouched", tree(OTHER) == before_other)

r = sync()
check("a second pass is a no-op: current, no reload", r.get("state") == "current" and not HUPS, (r, HUPS))

print("sync-acme — the ordinary box (entry installs for us)")
serve(*NEW)
entry(IP, NEW[0], NEW[1], SERVED)
r = sync()
check("nothing to do, owner ours, no reload", r.get("state") == "current" and r.get("owner") == "ours" and not HUPS, r)
entry(IP, NEW[0], NEW[1], N.SERVICES["sub"]["cert"])
r = sync()
check("swg-sub's path also counts as ours (a shared name re-points the entry to the sub)", r.get("owner") == "ours", r)

print("sync-acme — what must never be installed")
serve(*NEW)
entry(IP, OLD[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))
r = sync()
check("an OLDER entry certificate is left alone", r.get("state") == "current" and sha(SERVED) == sha(NEW[0]), r)

serve(*OLD)
entry(IP, WRONG[0], WRONG[1], os.path.join(OTHER, "fullchain.pem"))
r = sync()
check("a certificate for another address is refused, served cert kept",
      r.get("state") == "refused" and sha(SERVED) == sha(OLD[0]) and not HUPS, r)

d = entry(IP, NEW[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))       # key does not match the cert
r = sync()
check("a mismatched key is refused, served cert kept",
      r.get("state") == "refused" and sha(SERVED) == sha(OLD[0]) and not HUPS, r)

entry(IP, NEW[0], NEW[1], os.path.join(OTHER, "fullchain.pem"))
_real_time = N.time.time
N.time.time = lambda: _real_time() + 7 * 86400                          # the renewal has itself expired
r = sync()
N.time.time = _real_time
check("an expired certificate is refused (the adopt-cert expiry check now actually fires)",
      r.get("state") == "refused" and "expired" in (r.get("reason") or "") and sha(SERVED) == sha(OLD[0]), r)

ss = selfsigned("placeholder", "IP:" + IP, 3650)
serve(*ss)
r = sync()
check("a self-signed served certificate is HELD, never swapped (nodes may have pinned it)",
      r.get("state") == "held" and sha(SERVED) == sha(ss[0]) and "pinned" in (r.get("reason") or ""), r)
check("…installed elsewhere, nothing is said about acme.sh overwriting it", "swap_at" not in r, r)
_d = entry(IP, NEW[0], NEW[1], SERVED)
open(os.path.join(_d, IP + ".conf"), "a").write("Le_NextRenewTimeStr='2026-10-09T08:55:58Z'\n")
r = sync()
check("held, but acme.sh's OWN target is the panel's path: say when acme.sh will install over it",
      r.get("state") == "held" and r.get("swap_at") == "2026-10-09T08:55:58Z" and sha(SERVED) == sha(ss[0]), r)
entry(IP, NEW[0], NEW[1], os.path.join(OTHER, "fullchain.pem"))
# swg-sub's certificate is pinned by nothing: a self-signed one there yields to acme.sh's CA certificate
SUBC, SUBK = N.SERVICES["sub"]["cert"], N.SERVICES["sub"]["key"]
os.makedirs(os.path.dirname(SUBC), exist_ok=True)
shutil.copyfile(ss[0], SUBC); shutil.copyfile(ss[1], SUBK)
json.dump({"access": {"panel": {"url": "https://%s" % IP}, "sub": {"url": "https://%s:8444" % IP}, "tls": {"mode": "letsencrypt-ip"}}},
          open(os.path.join(STATE, "panel-settings.json"), "w"))
r = json.loads(N.do_sync_acme("sub"))
check("swg-sub's self-signed certificate is NOT held (nothing pins it) — it yields to the CA certificate",
      r.get("state") == "adopted" and sha(SUBC) == sha(NEW[0]), r)
os.unlink(SUBC); os.unlink(SUBK)
settings(IP)

print("sync-acme — when it must not act")
serve(*OLD)
open(SERVED + ".applyback", "w").write("x")
r = sync()
os.unlink(SERVED + ".applyback")
check("an address change in flight is left to its apply", r.get("state") == "skipped" and sha(SERVED) == sha(OLD[0]), r)
settings(IP, mode="selfsigned")
r = sync()
check("a mode acme.sh does not issue is skipped", r.get("state") == "skipped", r)
settings(IP)
shutil.rmtree(os.path.join(ACME, IP + "_ecc"))
r = sync()
check("no entry at all is reported as no-entry (nothing renews it)", r.get("state") == "no-entry", r)
check("a no-entry report says which name it is about", r.get("host") == IP, r)

print("IP SANs count as names (B)")
check("helper: an IP certificate covers its address", N._cert_covers_host(NEW[0], IP))
check("helper: …and not another one", not N._cert_covers_host(NEW[0], "198.51.100.7"))
check("helper: IPv6 matches in any spelling", N._cert_covers_host(V6[0], "[2001:DB8:0::1]"))
check("helper: a DNS certificate still matches by name, and is not an IP's",
      N._cert_covers_host(DNS[0], "panel.example.com") and not N._cert_covers_host(DNS[0], IP))

# the panel's twin — extracted by name, so the test does not boot a whole panel
PSRC = open(PATHS["PANEL"], encoding="utf-8").read()
_mod = ast.parse(PSRC)
_want = {"_ip_canon", "_cert_covers", "_refresh_tls_status", "_refresh_tls_status_locked", "_acme_follow_status", "_status_cert", "_tls_snapshot", "_follow_get", "_follow_set"}
_code = "\n\n".join(ast.get_source_segment(PSRC, n) for n in _mod.body
                    if isinstance(n, ast.FunctionDef) and n.name in _want)
import contextlib, ipaddress
import threading
P = {"os": os, "ssl": ssl, "ipaddress": ipaddress, "contextlib": contextlib, "time": time, "TLS_CERT": "", "MANAGED_CERT": "/nonexistent",
     "_TLS_LOCK": threading.RLock(), "threading": threading,
     "TLS_STATUS": {}, "_ACME_FOLLOW": {}, "_SHORT_LIVED_S": 10 * 86400, "_renew_status": lambda: {},
     "_ACME_FOLLOW_MODES": ("letsencrypt", "letsencrypt-ip", "cloudflare")}
exec(compile(_code, "swg-panel-server(extract)", "exec"), P)
check("panel: an IP certificate covers its address", P["_cert_covers"](NEW[0], IP))
check("panel: …and not another one", not P["_cert_covers"](NEW[0], "198.51.100.7"))
check("panel: IPv6 matches in any spelling", P["_cert_covers"](V6[0], "2001:db8:0:0:0:0:0:1"))
check("panel: a DNS certificate still matches by name", P["_cert_covers"](DNS[0], "PANEL.example.com"))

print("short-lived certificates are judged by their life, not by days (C)")


class _T:
    def __init__(self, off): self.off = off
    def time(self): return time.time() + self.off


P["TLS_CERT"] = NEW[0]                                                  # a 6-day CA-issued certificate
P["time"] = _T(0)
P["_refresh_tls_status"]()
S = P["TLS_STATUS"]
check("fresh: short_lived, with its lifetime (~6 days)", S.get("short_lived") is True and 5.9 * 86400 < S.get("lifetime_s", 0) <= 6 * 86400 + 60, S)
check("…and no verdict baked in (the SPA judges overdue on the panel's clock)", "renew_overdue" not in S and "hours_left" not in S, S)
import io, contextlib as _cl
P["time"] = _T(4.5 * 86400)                                             # 1.5 of 6 days left < 1/3
_out = io.StringIO()
with _cl.redirect_stdout(_out):
    P["_refresh_tls_status"]()
check("past 2/3 of its life the server log says it is overdue", "should have been renewed" in _out.getvalue(), _out.getvalue())
P["time"] = _T(0)
_out = io.StringIO()
with _cl.redirect_stdout(_out):
    P["_refresh_tls_status"]()
check("…and says nothing while it is fresh (no ≤14-day nag)", _out.getvalue() == "", _out.getvalue())
P["time"] = _T(7 * 86400)
_out = io.StringIO()
with _cl.redirect_stdout(_out):
    P["_refresh_tls_status"]()
check("an expired one is called EXPIRED, not '0 hour(s) left'", "EXPIRED" in _out.getvalue(), _out.getvalue())
P["time"] = _T(4.5 * 86400)
_out = io.StringIO()
with _cl.redirect_stdout(_out):
    P["_refresh_tls_status"](quiet=True)
check("the quiet read (before the follow) logs nothing", _out.getvalue() == "", _out.getvalue())
P["time"] = _T(0)
P["TLS_CERT"] = ss[0]
P["_refresh_tls_status"]()
check("a self-signed certificate is never short-lived", not S.get("short_lived"), S)

P["TLS_CERT"] = ""; P["_ACME_FOLLOW"].clear()
P["TLS_STATUS"].update({"days_left": 3, "renewer": "ours"})
P["_refresh_tls_status"]()
check("nothing to report → the status is cleared, never the last certificate's health left on screen", P["TLS_STATUS"] == {}, P["TLS_STATUS"])

# a poll (/api/state copies TLS_STATUS via _tls_snapshot) racing the watch loop's rebuild
P["TLS_CERT"] = NEW[0]; P["time"] = time
P["_refresh_tls_status"]()
_stop, _torn = [False], []
def _writer():
    while not _stop[0]:
        P["_refresh_tls_status"](quiet=True)
_wt = threading.Thread(target=_writer); _wt.start()
_t_end = time.time() + 3
while time.time() < _t_end:
    snap = P["_tls_snapshot"]()
    if "expires_at" not in snap:
        _torn.append(snap)
_stop[0] = True; _wt.join()
check("a poll never sees TLS_STATUS half-built", not _torn, _torn[:2])
_orig_sc = P["_status_cert"]
def _slow_sc():
    if threading.current_thread().name == "stale":
        time.sleep(0.4); return OLD[0]           # built from the OLD certificate, slowly
    return NEW[0]
P["_status_cert"] = _slow_sc
_ta = threading.Thread(target=P["_refresh_tls_status"], kwargs={"quiet": True}, name="stale"); _ta.start()
time.sleep(0.1)
P["_refresh_tls_status"](quiet=True)            # the newer certificate, while the stale build is in flight
_ta.join()
_exp_new = int(ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(NEW[0])["notAfter"]))
check("a slow rebuild from the OLD certificate never lands after a newer one",
      P["_tls_snapshot"]().get("expires_at") == _exp_new, (P["_tls_snapshot"]().get("expires_at"), _exp_new))
P["_status_cert"] = _orig_sc
P["TLS_CERT"] = ""
_sig = ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.FunctionDef) and n.name == "_sighup_reload"))
check("a SIGHUP (every certificate change) asks for a follow", "_acme_follow_soon()" in _sig)
_main = ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.FunctionDef) and n.name == "main"))
_hup = _main.find("signal.signal(signal.SIGHUP, _sighup_reload)")
check("SIGHUP is handled from the top of main(), before the migrations, the loads and the ledger start",
      _hup != -1 and _hup < _main.find("migrate_node_ids(") and _hup < _main.find("LEDGER.start(")
      and _hup < _main.find("Handler.deps = "), _hup)
_lst = ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.ClassDef) and n.name == "_Listeners"))
check("the listener registry lock is re-entrant (the SIGHUP handler takes it on the main thread)",
      "self._lock = threading.RLock()" in _lst)
_soon = ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.FunctionDef) and n.name == "_acme_follow_soon"))
check("…without starting a thread from the signal handler (threading's internal lock is not reentrant)",
      "Thread(" not in _soon and "Thread(" not in _sig and "_refresh_tls_status" not in _sig, _soon)
_kcode = ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.FunctionDef) and n.name == "_follow_kick_loop"))
KN = {"time": time, "contextlib": contextlib, "_FOLLOW_RUN": threading.Lock(), "_FOLLOW_KICK": threading.Event()}
_RUNS = []
KN["_acme_follow"] = lambda: _RUNS.append(1)
_EARLY = []
KN["_refresh_tls_status"] = lambda **k: _EARLY.append(KN["_FOLLOW_RUN"].locked())
exec(compile(_kcode, "swg-panel-server(extract)", "exec"), KN)
KN["_FOLLOW_RUN"].acquire()                      # a slow follow is running
threading.Thread(target=KN["_follow_kick_loop"], daemon=True).start()
for _ in range(5):
    KN["_FOLLOW_KICK"].set(); time.sleep(0.6)   # five certificate changes while it runs
KN["_FOLLOW_RUN"].release()
time.sleep(3.5)
check("certificate changes that queue behind a running follow are answered by ONE follow", len(_RUNS) == 1, len(_RUNS))
check("…and the new certificate is on screen at once: the status refresh does not wait for the follow lock",
      _EARLY[:1] == [True], _EARLY)

print("renewer reported from the last sync (C)")
for got, want in (({"state": "adopted", "owner": "other", "install_path": "/root/cert/ip/fullchain.pem"},
                   {"renewer": "other", "renewer_path": "/root/cert/ip/fullchain.pem"}),
                  ({"state": "current", "owner": "ours"}, {"renewer": "ours"}),
                  ({"state": "no-entry"}, {"renewer": "missing"}),
                  ({"state": "skipped"}, {}), ({}, {})):
    P["_ACME_FOLLOW"].clear(); P["_ACME_FOLLOW"].update(got)
    check("renewer for %s" % (got or "no sync"), P["_acme_follow_status"]() == want, P["_acme_follow_status"]())
P["TLS_CERT"] = NEW[0]                      # we serve the IP certificate
P["_ACME_FOLLOW"].clear(); P["_ACME_FOLLOW"].update({"state": "current", "owner": "other", "host": IP, "install_path": "/x"})
check("a report about the address we serve is shown", P["_acme_follow_status"]().get("renewer") == "other")
P["_ACME_FOLLOW"]["host"] = "old.example.com"
check("a report about an address we no longer serve is dropped (stale until the next 6-hourly follow)",
      P["_acme_follow_status"]() == {}, P["_acme_follow_status"]())

print("D — our side never takes another program's entry")
DOM = "panel.example.com"
settings(DOM, mode="letsencrypt")
OTHER_DOM = os.path.join(TMP, "x-ui-dom"); os.makedirs(OTHER_DOM, exist_ok=True)
foreign_fc = os.path.join(OTHER_DOM, "fullchain.pem")
check("foreign target: another program's path is reported",
      N._acme_foreign_target(DOM) == "" and (entry(DOM, DNS[0], DNS[1], foreign_fc) and N._acme_foreign_target(DOM) == foreign_fc))
entry(DOM, DNS[0], DNS[1], SERVED)
check("foreign target: our panel path is ours", N._acme_foreign_target(DOM) == "")
entry(DOM, DNS[0], DNS[1], N.SERVICES["sub"]["cert"])
check("foreign target: swg-sub's path is ours", N._acme_foreign_target(DOM) == "")
entry(DOM, DNS[0], DNS[1], "")
check("foreign target: an entry with no install target is not foreign", N._acme_foreign_target(DOM) == "")

CALLS = []
def fake_run(argv, env=None, timeout=None):
    CALLS.append(list(argv))
    return (2, "") if "--issue" in argv else (0, "")
N.run = fake_run
N.find_acme = lambda: "/fake/acme.sh"
CREDS = {"cf_token": "", "cf_account": "", "email": ""}

serve(*OLD)
d = entry(DOM, DNS[0], DNS[1], foreign_fc)
before = tree(d)
del CALLS[:]
N._issue_acme(N.SERVICES["panel"], "panel", [DOM], "letsencrypt", CREDS, reloadcmd=True)
check("issue over a foreign entry: NO --install-cert", not any("--install-cert" in c for c in CALLS), CALLS)
check("…the entry's certificate is copied into our path", sha(SERVED) == sha(DNS[0]) and sha(SERVED_KEY) == sha(DNS[1]))
check("…and the panel is reloaded itself", any("HUP" in c for c in CALLS), CALLS)
check("…the entry is untouched", tree(d) == before)
del CALLS[:]
serve(*OLD)
N._issue_acme(N.SERVICES["panel"], "panel", [DOM], "letsencrypt", CREDS, reloadcmd=False)
check("a live-apply (noreload) copies without reloading", sha(SERVED) == sha(DNS[0]) and not any("HUP" in c for c in CALLS), CALLS)

entry(DOM, DNS[0], DNS[1], foreign_fc)
open(N.CONF, "w").write("SERVE_MODE=nginx\n")    # behind the installer's nginx, which serves the same file
serve(*OLD)
del CALLS[:]
N._issue_acme(N.SERVICES["panel"], "panel", [DOM], "letsencrypt", CREDS, reloadcmd=True)
check("behind nginx a foreign entry is copied too (never taken), and nginx is reloaded",
      not any("--install-cert" in c for c in CALLS) and sha(SERVED) == sha(DNS[0])
      and ["systemctl", "reload", "nginx"] in CALLS, CALLS)
settings(DOM, mode="letsencrypt")
serve(*OLD)
d = entry(DOM, DNS[0], DNS[1], foreign_fc)
del CALLS[:]
r = json.loads(N.do_sync_acme("panel"))
check("sync-acme behind nginx: adopted, the panel HUPed AND nginx reloaded",
      r.get("state") == "adopted" and ["systemctl", "reload", "nginx"] in CALLS and any("HUP" in c for c in CALLS), (r, CALLS))
os.unlink(N.CONF)

entry(DOM, DNS[0], DNS[1], "", Le_RealCertPath=os.path.join(OTHER_DOM, "cert.pem"), Le_RealKeyPath=os.path.join(OTHER_DOM, "key.pem"))
check("owner: a tool that installed with --cert-file/--key-file (no fullchain) is another program",
      N._acme_foreign_target(DOM) == os.path.join(OTHER_DOM, "cert.pem"), N._acme_foreign_target(DOM))
entry(DOM, DNS[0], DNS[1], os.path.join(os.path.dirname(SERVED), "old-fullchain.pem"))
check("owner: a leftover path inside our TLS dir is NOT ours (exact files only)",
      N._acme_foreign_target(DOM) == os.path.join(os.path.dirname(SERVED), "old-fullchain.pem"))
entry(DOM, DNS[0], DNS[1], SERVED, Le_RealKeyPath=SERVED_KEY)
check("owner: our fullchain + our key is ours", N._acme_foreign_target(DOM) == "")

entry(DOM, DNS[0], DNS[1], SERVED)
del CALLS[:]
N._issue_acme(N.SERVICES["panel"], "panel", [DOM], "letsencrypt", CREDS, reloadcmd=True)
check("issue over OUR entry: --install-cert exactly as before",
      any("--install-cert" in c and "--reloadcmd" in c for c in CALLS), CALLS)

d = entry(DOM, DNS[0], DNS[1], foreign_fc)
rsa = os.path.join(ACME, DOM); os.makedirs(rsa, exist_ok=True)
del CALLS[:]
msg = N.do_drop_cert("panel", DOM)
check("drop-cert on a foreign entry: no --remove, entry kept",
      not any("--remove" in c for c in CALLS) and os.path.isdir(d) and "another program" in msg, (CALLS, msg))
d = entry(DOM, DNS[0], DNS[1], SERVED)
del CALLS[:]
N.do_drop_cert("panel", DOM)
check("drop-cert on OUR entry: --remove and the _ecc dir goes", any("--remove" in c for c in CALLS) and not os.path.isdir(d), CALLS)
check("…the RSA <domain> dir beside it (never ours) is left alone", os.path.isdir(rsa))
# the panel moved to a NEW name; swg-sub still serves the OLD one, from the same entry
json.dump({"access": {"panel": {"url": "https://new.example.com"}, "sub": {"url": "https://%s:8444" % DOM},
           "tls": {"mode": "letsencrypt"}}}, open(os.path.join(STATE, "panel-settings.json"), "w"))
d = entry(DOM, DNS[0], DNS[1], SERVED)
del CALLS[:]
msg = N.do_drop_cert("panel", DOM)
check("drop-cert panel <old name> keeps the entry while swg-sub still SERVES that name",
      os.path.isdir(d) and not any("--remove" in c for c in CALLS) and "sub" in msg, (msg, CALLS))
json.dump({"access": {"panel": {"url": "https://new.example.com"}, "sub": {"url": "https://other.example.com:8444"},
           "tls": {"mode": "letsencrypt"}}}, open(os.path.join(STATE, "panel-settings.json"), "w"))
d = entry(DOM, DNS[0], DNS[1], N.SERVICES["sub"]["cert"])
del CALLS[:]
msg = N.do_drop_cert("panel", DOM)
check("…and while the entry installs into swg-sub's certificate path", os.path.isdir(d) and "sub" in msg, msg)
json.dump({"access": {"panel": {"url": "https://new.example.com"}, "sub": {"url": "https://%s:8444" % DOM},
           "tls": {"mode": "letsencrypt"}}}, open(os.path.join(STATE, "panel-settings.json"), "w"))
d = entry(DOM, DNS[0], DNS[1], SERVED, Le_RealKeyPath=SERVED_KEY)
del CALLS[:]
msg = N.do_drop_cert("panel", DOM)
_ic = [c for c in CALLS if "--install-cert" in c]
json.dump({"access": {"panel": {"url": "https://new.example.com"}, "sub": {"url": "https://%s:8444" % DOM},
           "tls": {"mode": "skip"}}}, open(os.path.join(STATE, "panel-settings.json"), "w"))
_dk = entry(DOM, DNS[0], DNS[1], SERVED, Le_RealKeyPath=SERVED_KEY)
del CALLS[:]
_mk = N.do_drop_cert("panel", DOM)
check("under `skip` swg-sub serves the operator's own certificate: the old name is dropped, never moved onto it",
      not any("--install-cert" in c for c in CALLS) and any("--remove" in c for c in CALLS), (_mk, CALLS))
json.dump({"access": {"panel": {"url": "https://new.example.com"}, "sub": {"url": "https://%s:8444" % DOM},
           "tls": {"mode": "letsencrypt"}}}, open(os.path.join(STATE, "panel-settings.json"), "w"))
d = entry(DOM, DNS[0], DNS[1], SERVED, Le_RealKeyPath=SERVED_KEY)
del CALLS[:]
msg = N.do_drop_cert("panel", DOM)
_ic = [c for c in CALLS if "--install-cert" in c]
check("a kept entry that still installs into the PANEL's paths is moved to swg-sub's (else its renewal overwrites the panel)",
      os.path.isdir(d) and _ic and N.SERVICES["sub"]["cert"] in _ic[0] and N.SERVICES["sub"]["key"] in _ic[0]
      and SERVED not in _ic[0] and "moved" in msg, (msg, _ic))
settings(DOM, mode="letsencrypt")

print("renew-acme — the operator's Renew now")
settings(IP)                                 # an IP panel, the entry owned by 3x-ui
serve(*OLD)
RENEW = {"rc": 0, "out": ""}
def renew_run(argv, env=None, timeout=None):
    CALLS.append(list(argv))
    if "--renew" in argv:
        if RENEW["rc"] == 0:                 # acme.sh renewed: the entry now holds the new certificate
            entry(IP, NEW[0], NEW[1], os.path.join(OTHER, "fullchain.pem"))
        return RENEW["rc"], RENEW["out"]
    return 0, ""
N.run = renew_run
entry(IP, OLD[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))
del CALLS[:]
r = json.loads(N.do_renew_acme("panel"))
check("renewed: acme --renew for the panel's name, NEVER --force",
      any("--renew" in c and IP in c and "--ecc" in c for c in CALLS) and not any("--force" in c for c in CALLS), CALLS)
check("…and the result is installed at once (sync-acme), the panel reloaded",
      r.get("state") == "renewed" and (r.get("sync") or {}).get("state") == "adopted" and sha(SERVED) == sha(NEW[0])
      and any("HUP" in c for c in CALLS), r)
check("…reporting who owns the entry", r.get("owner") == "other" and r.get("install_path") == os.path.join(OTHER, "fullchain.pem"), r)
d = entry(IP, NEW[0], NEW[1], os.path.join(OTHER, "fullchain.pem"))
open(os.path.join(d, IP + ".conf"), "a").write("Le_NextRenewTimeStr='2026-09-28T16:31:03Z'\n")
RENEW.update(rc=2, out="Skipping. Next renewal time is: 2026-09-28T16:31:03Z")
r = json.loads(N.do_renew_acme("panel"))
check("not due: reported with acme.sh's next renewal time", r.get("state") == "not-due" and r.get("message") == "2026-09-28T16:31:03Z", r)
RENEW.update(rc=1, out="[Fri] Standalone mode.\n[Fri] Account key not found in cache, reading it\n[Fri] \x1b[31mTcp port 80 is held by nginx\x1b[0m\n[Fri] \x1b[31mPlease stop it first\x1b[0m\n")
r = json.loads(N.do_renew_acme("panel"))
check("failed: acme.sh's own reason (its RED lines) comes back, colour stripped, not the noise around it",
      r.get("state") == "failed" and r.get("message") == "[Fri] Tcp port 80 is held by nginx\n[Fri] Please stop it first", r)
shutil.rmtree(os.path.join(ACME, IP + "_ecc"))
r = json.loads(N.do_renew_acme("panel"))
check("no entry: nothing to renew, said so", r.get("state") == "no-entry", r)
settings(IP, mode="selfsigned")
check("a mode acme.sh does not issue is skipped", json.loads(N.do_renew_acme("panel")).get("state") == "skipped")
settings(DOM, mode="cloudflare")
open(N.CONF, "w").write("CF_TOKEN=cf-secret-token\n")
entry(DOM, DNS[0], DNS[1], SERVED)
ENVS = []
def env_run(argv, env=None, timeout=None):
    if "--renew" in argv:
        ENVS.append((env or {}).get("CF_Token"))
    return (2, "") if "--renew" in argv else (0, "")
N.run = env_run
N.do_renew_acme("panel")
check("cloudflare: the DNS-01 token rides the renewal's environment, never its argv", ENVS == ["cf-secret-token"], ENVS)
COLOR = []
N.run = lambda argv, env=None, timeout=None: (COLOR.append((env or {}).get("ACME_FORCE_COLOR")) or ((2, "") if "--renew" in argv else (0, "")))
N.do_renew_acme("panel")
check("acme.sh is asked for colour (it prints red only on a TTY) — the red lines are how its reason is found", COLOR[:1] == ["1"], COLOR)
check("acme's stored --reloadcmd is the panel's own HUP only — nothing that goes stale when the serve mode flips",
      N.reload_cmd_for("panel") == "systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true")
open(N.CONF, "w").write("SERVE_MODE=nginx\n")
settings(IP)
serve(*NEW)
entry(IP, NEW[0], NEW[1], SERVED)
FRONT = []
N.run = lambda argv, env=None, timeout=None: (FRONT.append(list(argv)) or (0, ""))
with contextlib.suppress(OSError):
    os.unlink(N._FRONT_MARK)
r = json.loads(N.do_sync_acme("panel"))
check("behind nginx: a served file nginx has not loaded yet (a cron renewal) makes 'current' reload it",
      r.get("state") == "current" and r.get("front") == "nginx" and ["systemctl", "reload", "nginx"] in FRONT, (r, FRONT))
del FRONT[:]
N.do_sync_acme("panel")
check("…once — an unchanged file never reloads nginx again", ["systemctl", "reload", "nginx"] not in FRONT, FRONT)
serve(*OLD); serve(*NEW)
os.utime(SERVED)
shutil.copyfile(DNS[0], SERVED); shutil.copyfile(DNS[1], SERVED_KEY)
del FRONT[:]
N._front_sync()
check("…and a changed file reloads it again", ["systemctl", "reload", "nginx"] in FRONT, FRONT)
open(N.CONF, "w").write("SERVE_MODE=internal\n")
del FRONT[:]
N._front_sync()
check("a panel serving its own TLS never reloads a proxy", not FRONT, FRONT)
settings(IP)
serve(*OLD)
d = entry(IP, OLD[0], OLD[1], SERVED)
open(SERVED + ".applyback", "w").write("x")
r = json.loads(N.do_sync_acme("panel"))
os.unlink(SERVED + ".applyback")
check("a skip during an address change is marked transient (the panel keeps its last report)", r.get("transient") is True, r)
RENEW.update(rc=124, out="")
N.run = lambda argv, env=None, timeout=None: ((124, "") if "--renew" in argv else (0, ""))
r = json.loads(N.do_renew_acme("panel"))
check("the helper's own words are labelled as the helper's, not acme.sh's", r.get("source") == "helper" and r.get("state") == "failed", r)
N.run = lambda argv, env=None, timeout=None: ((1, "\x1b[1;31mTcp port 80 is held by nginx\x1b[0m") if "--renew" in argv else (0, ""))
r = json.loads(N.do_renew_acme("panel"))
check("…and acme.sh's lines as acme.sh's", r.get("source") == "acme", r)
os.unlink(N.CONF)
N.run = fake_run

print("renew-acme — a hung acme.sh, and swg-sub on the same name")
_l2 = importlib.machinery.SourceFileLoader("netctl_af2", NPATH)
N2 = importlib.util.module_from_spec(importlib.util.spec_from_loader("netctl_af2", _l2))
try:
    _l2.exec_module(N2)
except SystemExit:
    pass
_mark = "31.%d" % os.getpid()
t0 = time.time()
rc, out = N2.run(["sh", "-c", "sleep %s & sleep %s" % (_mark, _mark)], timeout=1)
_left = subprocess.run(["pgrep", "-f", "sleep %s" % _mark], capture_output=True, text=True).stdout.strip()
check("run(timeout): a hung command is stopped with rc 124, promptly", rc == 124 and time.time() - t0 < 10 and "stopped" in out, (rc, out))
check("…and its whole process group dies with it (acme's :80 listener child too)", _left == "", _left)
check("run() without a timeout behaves as before", N2.run(["sh", "-c", "echo hi; exit 3"]) == (3, "hi\n"))

settings(IP)
serve(*OLD)
entry(IP, OLD[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))
N.run = lambda argv, env=None, timeout=None: ((124, "(stopped: still running after 240 s)") if "--renew" in argv else (0, ""))
r = json.loads(N.do_renew_acme("panel"))
check("a renewal that hangs is stopped and reported as failed, with why",
      r.get("state") == "failed" and "did not finish" in r.get("message", ""), r)

SUBC, SUBK = N.SERVICES["sub"]["cert"], N.SERVICES["sub"]["key"]
json.dump({"access": {"panel": {"url": "https://%s" % IP}, "sub": {"url": "https://%s:8444" % IP}, "tls": {"mode": "letsencrypt-ip"}}},
          open(os.path.join(STATE, "panel-settings.json"), "w"))
shutil.copyfile(OLD[0], SUBC); shutil.copyfile(OLD[1], SUBK)
RENEW.update(rc=0, out="")
N.run = renew_run
entry(IP, OLD[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))
r = json.loads(N.do_renew_acme("panel"))
check("renewing the panel also brings swg-sub on the same name across", r.get("state") == "renewed" and sha(SUBC) == sha(NEW[0]), r)
os.unlink(SUBC); os.unlink(SUBK); os.rmdir(os.path.dirname(SUBC))
serve(*OLD)
entry(IP, OLD[0], OLD[1], os.path.join(OTHER, "fullchain.pem"))
N.do_renew_acme("panel")
check("…but never creates swg-sub's certificate where swg-sub has none", not os.path.exists(os.path.dirname(SUBC)))
os.makedirs(os.path.dirname(SUBC), exist_ok=True)
settings(IP)
N.run = fake_run

# the installer's bash twin, run for real
ISRC = open(PATHS["INSTALL_HOST"], encoding="utf-8").read()
def bash_fn(name):
    i = ISRC.index(name + "(){")
    j = ISRC.index("; }\n", i) + 3
    return ISRC[i:j]
_rp_line = next(l for l in ISRC.splitlines() if l.startswith("_acme_rp(){"))
BASH = "\n".join([_rp_line, bash_fn("acme_foreign_target"), bash_fn("acme_copy_foreign")])
def installer(dom, extra=""):
    env = dict(os.environ, ACME_HOME=ACME, TLS_DIR=os.path.dirname(SERVED), DRYRUN="false",
               CERT_FULLCHAIN=SERVED, CERT_KEY=SERVED_KEY)
    return subprocess.run(["bash", "-c", "set -euo pipefail\n" + BASH + "\n" + extra], env=env,
                          capture_output=True, text=True)
entry(DOM, DNS[0], DNS[1], foreign_fc)
r = installer(DOM, 'acme_foreign_target "%s"' % DOM)
check("installer: foreign target reported", r.returncode == 0 and r.stdout == foreign_fc, (r.returncode, r.stdout, r.stderr))
serve(*OLD)
r = installer(DOM, 'acme_copy_foreign "%s"' % DOM)
check("installer: copies the entry's pair into our path", r.returncode == 0 and sha(SERVED) == sha(DNS[0]) and sha(SERVED_KEY) == sha(DNS[1]), r.stderr)
entry(DOM, DNS[0], DNS[1], SERVED)
r = installer(DOM, 'acme_foreign_target "%s"' % DOM)
check("installer: our own path is not foreign", r.returncode == 0 and r.stdout == "", r.stdout)
entry(DOM, DNS[0], DNS[1], "", Le_RealCertPath=os.path.join(OTHER_DOM, "cert.pem"))
r = installer(DOM, 'acme_foreign_target "%s"' % DOM)
check("installer: --cert-file ownership seen too", r.stdout == os.path.join(OTHER_DOM, "cert.pem"), r.stdout)
entry(DOM, DNS[0], DNS[1], os.path.join(os.path.dirname(SERVED), "old-fullchain.pem"))
r = installer(DOM, 'acme_foreign_target "%s"' % DOM)
check("installer: a leftover path inside our TLS dir is NOT ours (agrees with swg-netctl)",
      r.stdout == os.path.join(os.path.dirname(SERVED), "old-fullchain.pem"), r.stdout)
LINK = os.path.join(TMP, "tls-link"); os.symlink(os.path.dirname(SERVED), LINK)
entry(DOM, DNS[0], DNS[1], os.path.join(LINK, "fullchain.pem"))
r = installer(DOM, 'acme_foreign_target "%s"' % DOM)
check("installer: our file spelled through a symlinked dir is ours (resolved, as swg-netctl does)",
      r.returncode == 0 and r.stdout == "" and N._acme_foreign_target(DOM) == "", (r.stdout, N._acme_foreign_target(DOM)))
check("the installer's acme reload command is a SIGHUP, never a restart",
      ISRC.count('systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true"; then') == 1
      and 'systemctl restart swg-panel-server"; then' not in ISRC)
USRC = open(PATHS["UPDATE"], encoding="utf-8").read()
_hi = USRC.index("heal_acme_reloadcmd(){"); _hj = USRC.index("  return 0; }\n", _hi) + len("  return 0; }\n")
HEAL = USRC[_hi:_hj]
import base64 as _b64
def heal_run(dom, target, cmd):
    hd = tempfile.mkdtemp(prefix="heal-", dir=TMP)
    os.makedirs(os.path.join(hd, "acme", dom + "_ecc")); os.makedirs(os.path.join(hd, "etc", "tls"))
    open(os.path.join(hd, "etc", "install.conf"), "w").write("PANEL_DOMAIN=%s\n" % dom)
    conf = os.path.join(hd, "acme", dom + "_ecc", dom + ".conf")
    enc = "__ACME_BASE64__START_%s__ACME_BASE64__END_" % _b64.b64encode(cmd.encode()).decode()
    open(conf, "w").write("Le_Domain='%s'\nLe_RealFullChainPath='%s'\nLe_ReloadCmd='%s'\nLe_API='x'\n"
                          % (dom, target.replace("@TLS", os.path.join(hd, "etc", "tls")), enc))
    sh_ = ("ok(){ :; }; note(){ :; }; DRYRUN=false; ACME_HOME_CANON=%s; ETC_DIR=%s; TLS_DIR=%s\n%s\nheal_acme_reloadcmd"
           % (os.path.join(hd, "acme"), os.path.join(hd, "etc"), os.path.join(hd, "etc", "tls"), HEAL))
    subprocess.run(["bash", "-c", sh_], capture_output=True, text=True)
    raw = next(l for l in open(conf).read().splitlines() if l.startswith("Le_ReloadCmd="))
    m = re.search(r"START_(.*)__ACME_BASE64__END_", raw)
    return _b64.b64decode(m.group(1)).decode(), open(conf).read()
import re
OLDCMD = "chown root:swg /etc/swg-panel/tls/fullchain.pem /etc/swg-panel/tls/key.pem; chmod 640 /etc/swg-panel/tls/key.pem; systemctl restart swg-panel-server"
got, conf_after = heal_run(DOM, "@TLS/fullchain.pem", OLDCMD)
check("update heals an entry's `systemctl restart swg-panel-server` into a SIGHUP",
      "systemctl restart" not in got and got.endswith("systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true")
      and got.startswith("chown root:swg") and "Le_API='x'" in conf_after, got)
got2, _ = heal_run(DOM, "@TLS/fullchain.pem", got)
check("…and is idempotent", got2 == got, got2)
got3, _ = heal_run(DOM, "/root/cert/ip/fullchain.pem", OLDCMD)
check("…and never touches an entry that installs somewhere else (another program's)", got3 == OLDCMD, got3)
got4, _ = heal_run(DOM, "@TLS/fullchain.pem", "systemctl restart swg-panel-server.service")
check("…and heals the `.service` spelling to exactly the SIGHUP (no `|| true.service`)",
      got4 == "systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true", got4)
got5, _ = heal_run(DOM, "@TLS/fullchain.pem", "systemctl restart swg-panel-server-staging")
check("…and leaves a command that merely starts with it alone", got5 == "systemctl restart swg-panel-server-staging", got5)
CSRC = open(PATHS["CONVERT"], encoding="utf-8").read()
check("a docker→bare convert stores the SIGHUP too, never the restart",
      "Le_ReloadCmd='systemctl kill -s HUP swg-panel-server.service 2>/dev/null || true'" in CSRC
      and "Le_ReloadCmd='systemctl restart swg-panel-server'" not in CSRC)
r = installer("nope.example", 'acme_foreign_target "nope.example"')
check("installer: no entry is not foreign (and set -e survives)", r.returncode == 0 and r.stdout == "", r.stderr)

print("panel: POST /api/access/renew-cert")
import threading
_want2 = {"_renew_worker", "_renew_start", "_renew_await", "_renew_running", "_renew_refusal", "_follow_set", "_follow_get"}
_code2 = "\n\n".join(ast.get_source_segment(PSRC, n) for n in _mod.body
                     if isinstance(n, ast.FunctionDef) and n.name in _want2)
JOBDIR = tempfile.mkdtemp(prefix="renewjob-", dir=TMP)
def _perr(key, **v):
    return {"error": key, "error_key": key}
Q = {"json": json, "time": time, "threading": threading, "os": os, "contextlib": contextlib, "perr": _perr,
     "_RENEW_PICKUP_S": 60, "_RENEW_ANSWER_S": 480, "_RENEW_JOB": {"state": "idle", "message": "", "at": 0, "result": "", "source": ""},
     "_RENEW_LOCK": threading.Lock(), "_ACME_FOLLOW": {}, "_TLS_LOCK": threading.RLock(), "IN_DOCKER": False, "PANEL_DECLARATIVE": False,
     "_refresh_tls_status": lambda *a, **k: None, "_invalidate_state_cache": lambda: None,
     "_declarative_access_refusal": lambda deps: (409, {"ok": False, "code": "declarative"}),
     "_access_cooldown": lambda: (0, "")}
exec(compile(_code2, "swg-panel-server(extract)", "exec"), Q)
DEPS = {"nodes_path": os.path.join(JOBDIR, "nodes.json")}
def join_jobs():
    for t in threading.enumerate():
        if t.name == "renew-cert":
            t.join(10)
def run_job(reply, rid="r1"):
    Q["_RENEW_JOB"].update(state="idle")
    Q["_netctl_enqueue"] = lambda deps, verb, args: (ENQ.append((verb, args)) or rid)
    Q["_netctl_wait"] = lambda deps, r, t: reply
    code, obj = Q["_renew_start"](DEPS)
    for t in threading.enumerate():
        if t.name == "renew-cert":
            t.join(10)
    return code, obj, dict(Q["_RENEW_JOB"])
ENQ = []
import io as _io, contextlib as _cl2
with _cl2.redirect_stdout(_io.StringIO()):
    code, obj, job = run_job((True, json.dumps({"state": "renewed", "sync": {"state": "adopted", "owner": "other", "install_path": "/root/cert/ip/fullchain.pem"}})))
check("starts in the background (202) and asks the helper to renew the panel's certificate",
      code == 202 and ENQ[-1] == ("renew-acme", ["panel"]), (code, ENQ))
check("…the job ends done/renewed, and who renews it is updated from the renewal",
      job["state"] == "done" and job["result"] == "renewed" and Q["_ACME_FOLLOW"].get("owner") == "other", (job, Q["_ACME_FOLLOW"]))
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((True, json.dumps({"state": "failed", "message": "Tcp port 80 is already used by nginx"})))
check("a failure carries acme.sh's reason to the screen", job["result"] == "failed" and "port 80" in job["message"], job)
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((False, "the root helper is not available"), rid=None)
check("no root helper: failed, and says why", job["result"] == "failed" and "not available" in job["message"], job)
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((False, "unknown verb 'renew-acme'"))
check("an older helper (no such verb): failed with its answer, not a crash", job["result"] == "failed" and "unknown verb" in job["message"], job)
def _boom(deps, r, t):
    raise RuntimeError("helper went away")
Q["_RENEW_JOB"].update(state="idle")
Q["_netctl_enqueue"] = lambda deps, verb, args: "r9"
Q["_netctl_wait"] = _boom
with _cl2.redirect_stdout(_io.StringIO()):
    Q["_renew_start"](DEPS)
    for t in threading.enumerate():
        if t.name == "renew-cert":
            t.join(10)
check("a worker that raises still ENDS the job (the button never stays disabled)",
      Q["_RENEW_JOB"]["state"] == "done" and Q["_RENEW_JOB"]["result"] == "failed", Q["_RENEW_JOB"])
Q["_access_cooldown"] = lambda: (30, "verifying")
Q["_RENEW_JOB"].update(state="idle")
check("refused while an address change waits to be confirmed", Q["_renew_start"](DEPS)[0] == 409 and Q["_RENEW_JOB"]["state"] == "idle")
Q["_access_cooldown"] = lambda: (30, "migrating")
Q["_netctl_wait"] = lambda deps, r, t: (True, json.dumps({"state": "renewed"}))
with _cl2.redirect_stdout(_io.StringIO()):
    code = Q["_renew_start"](DEPS)[0]
    for t in threading.enumerate():
        if t.name == "renew-cert":
            t.join(10)
check("…but allowed in a confirmed change's grace (the new certificate is already served)", code == 202)
Q["_access_cooldown"] = lambda: (0, "")
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((True, json.dumps({"state": "failed", "message": "Tcp port 80 is held by nginx", "source": "acme"})))
check("acme.sh's words are labelled as acme.sh's (source acme)", job["source"] == "acme", job)
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((True, json.dumps({"state": "failed", "message": "acme.sh did not finish within 240 s", "source": "helper"})))
check("swg-netctl's own words inside its answer are NOT called acme.sh's", job["source"] == "panel", job)
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((False, "timed out waiting for the root helper"))
check("the panel's own words are NOT labelled as acme.sh's (source panel)", job["source"] == "panel", job)

Q["_ACME_FOLLOW"].clear(); Q["_ACME_FOLLOW"].update({"state": "current", "owner": "other", "install_path": "/root/cert/ip/fullchain.pem"})
with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((True, json.dumps({"state": "renewed", "sync": {"state": "skipped", "reason": "an address change is in flight"}})))
check("renewed but NOT installed is its own outcome — never 'Renewed, valid until <the old date>'",
      job["result"] == "not-installed" and "address change" in job["message"], job)
check("…and a report that does not say who renews it leaves the last one alone",
      Q["_ACME_FOLLOW"].get("owner") == "other", Q["_ACME_FOLLOW"])

# a request the helper never takes is WITHDRAWN, not left to run after the guard lifts
QDIR = os.path.join(JOBDIR, "netctl", "queue"); os.makedirs(QDIR, exist_ok=True)
Q["_RENEW_PICKUP_S"] = 1
Q["_netctl_enqueue"] = lambda deps, verb, args: (open(os.path.join(QDIR, "r-stuck.json"), "w").write("{}") and "r-stuck")
Q["_netctl_wait"] = lambda deps, r, t: (_ for _ in ()).throw(AssertionError("must not wait for a request nobody took"))
Q["_RENEW_JOB"].update(state="idle")
with _cl2.redirect_stdout(_io.StringIO()):
    Q["_renew_start"](DEPS)
    join_jobs()
check("a request the root helper never takes is withdrawn from its queue, and the job says so",
      not os.path.exists(os.path.join(QDIR, "r-stuck.json")) and Q["_RENEW_JOB"]["result"] == "failed"
      and "did not take" in Q["_RENEW_JOB"]["message"], Q["_RENEW_JOB"])
Q["_RENEW_PICKUP_S"] = 60
Q["_netctl_enqueue"] = lambda deps, verb, args: (_ for _ in ()).throw(RuntimeError("queue dir vanished"))
Q["_RENEW_JOB"].update(state="idle")
with _cl2.redirect_stdout(_io.StringIO()):
    Q["_renew_start"](DEPS)
    join_jobs()
check("even the enqueue failing ENDS the job (every step is inside the try)", Q["_RENEW_JOB"]["state"] == "done", Q["_RENEW_JOB"])

# review 2026-09-25 #6 — the REAL helper queue: a request still RUNNING when the pickup window ends is not withdrawn
_wcode = "\n\n".join(ast.get_source_segment(PSRC, n) for n in _mod.body
                     if isinstance(n, ast.FunctionDef) and n.name in ("_renew_await", "_netctl_wait"))
W = {"os": os, "json": json, "time": time, "contextlib": contextlib, "_RENEW_PICKUP_S": 1, "_RENEW_ANSWER_S": 20}
exec(compile(_wcode, "swg-panel-server(extract)", "exec"), W)
WDEPS = {"nodes_path": os.path.join(STATE, "nodes.json")}           # the panel's netctl dir = the helper's STATE_DIR/netctl
os.makedirs(N.QUEUE_DIR, exist_ok=True)
N.VERBS["slow-test"] = (lambda: (time.sleep(3), json.dumps({"state": "renewed"}))[1], 0)
open(os.path.join(N.QUEUE_DIR, "rt-long.json"), "w").write(json.dumps({"id": "rt-long", "verb": "slow-test", "args": []}))
_ht = threading.Thread(target=N.process_queue); _ht.start()
time.sleep(0.3)
_during = os.listdir(N.QUEUE_DIR)
ok_, msg_ = W["_renew_await"](WDEPS, "rt-long")
_ht.join()
check("a renewal the helper is still RUNNING after the pickup window is never withdrawn",
      ok_ and '"renewed"' in (msg_ or ""), (ok_, msg_))
check("while a request runs, the watched queue dir is EMPTY (a leftover claim there would re-trigger the helper forever)",
      _during == [], _during)
check("…and it leaves nothing behind in the queue", not [f for f in os.listdir(N.QUEUE_DIR) if f.startswith("rt-long")],
      os.listdir(N.QUEUE_DIR))
open(os.path.join(N.QUEUE_DIR, "rt-gone.json"), "w").write(json.dumps({"id": "rt-gone", "verb": "slow-test", "args": []}))
os.unlink(os.path.join(N.QUEUE_DIR, "rt-gone.json"))                 # withdrawn by its waiter first
N.process_queue()
check("a withdrawn request is never run by the helper", not os.path.exists(os.path.join(N.STATUS_DIR, "rt-gone.json")))

# review 4 #1/#10: netctl/ is the PANEL's — root's children there are verified through fds, never a path it resolves
VICTIM = os.path.join(TMP, "victim-etc"); os.makedirs(VICTIM); os.chmod(VICTIM, 0o755)   # like /etc: passes an owner/mode check
open(os.path.join(VICTIM, "daemon.json"), "w").write('{"real": true}\n')
open(os.path.join(VICTIM, "passwd"), "w").write("root:x:0:0\n"); os.utime(os.path.join(VICTIM, "passwd"), (1, 1))
N.VERBS["quick-test"] = (lambda: json.dumps({"state": "renewed"}), 0)
_nd = N.NETCTL_DIR
shutil.rmtree(os.path.join(_nd, "status")); os.symlink(VICTIM, os.path.join(_nd, "status"))   # the panel's plant
open(os.path.join(N.QUEUE_DIR, "daemon.json"), "w").write(json.dumps({"id": "daemon", "verb": "quick-test", "args": []}))
with contextlib.redirect_stderr(io.StringIO()):
    N.process_queue()
check("status/ swapped for a symlink: root never writes through it (the answer lands in a fresh root-owned status/)",
      open(os.path.join(VICTIM, "daemon.json")).read() == '{"real": true}\n' and not os.path.islink(os.path.join(_nd, "status"))
      and os.path.exists(os.path.join(_nd, "status", "daemon.json")), os.listdir(VICTIM))
os.rename(os.path.join(_nd, "claims"), os.path.join(_nd, "claims.real")); os.symlink(VICTIM, os.path.join(_nd, "claims"))
open(os.path.join(N.QUEUE_DIR, "rt-sym.json"), "w").write(json.dumps({"id": "rt-sym", "verb": "quick-test", "args": []}))
with contextlib.redirect_stderr(io.StringIO()):
    N.process_queue()
check("a planted symlink where the claim dir should be is refused — nothing is deleted or dropped through it",
      sorted(os.listdir(VICTIM)) == ["daemon.json", "passwd"] and os.path.exists(os.path.join(_nd, "status", "rt-sym.json"))
      and not os.path.islink(os.path.join(_nd, "claims")), sorted(os.listdir(VICTIM)))
# a REAL directory at claims/ that is not root's own (here: group/other-writable, as a panel-made one would be) is
# never used — it is moved aside and a fresh one made
shutil.rmtree(os.path.join(_nd, "claims")); os.mkdir(os.path.join(_nd, "claims")); os.chmod(os.path.join(_nd, "claims"), 0o777)
open(os.path.join(N.QUEUE_DIR, "rt-own.json"), "w").write(json.dumps({"id": "rt-own", "verb": "quick-test", "args": []}))
with contextlib.redirect_stderr(io.StringIO()):
    N.process_queue()
_cm = os.stat(os.path.join(_nd, "claims")).st_mode & 0o777
check("a claims/ dir that is not root's own is never used — moved aside, a fresh 0700 one made",
      _cm == 0o700 and any(n.startswith("claims.untrusted.") for n in os.listdir(_nd)), (oct(_cm), os.listdir(_nd)))
os.mkfifo(os.path.join(N.QUEUE_DIR, "rt-fifo.json"))
_ft = threading.Thread(target=N.process_queue, daemon=True)
with contextlib.redirect_stderr(io.StringIO()):
    _ft.start(); _ft.join(5)
check("a FIFO in the queue cannot wedge the helper (read O_NONBLOCK, checked on the fd)",
      not _ft.is_alive() and os.path.exists(os.path.join(_nd, "status", "rt-fifo.json"))
      and json.load(open(os.path.join(_nd, "status", "rt-fifo.json")))["status"] == "error")
if _ft.is_alive():                                   # (planted) stuck on the FIFO: give it a writer so it lets go
    with contextlib.suppress(OSError):
        _w = os.open(os.path.join(N.QUEUE_DIR, "rt-fifo.json"), os.O_WRONLY | os.O_NONBLOCK); os.close(_w)
    _ft.join(5)
_old = os.path.join(_nd, "status", "acc-old.json"); open(_old, "w").write("{}"); os.utime(_old, (1, 1))
for fn, age in (("rt-a.json.taking", 0), ("rt-b.json.tmp", 3600), ("rt-c.json.tmp", 0), ("junk.d", 0)):
    fp = os.path.join(N.QUEUE_DIR, fn)
    os.mkdir(fp) if fn.endswith(".d") else open(fp, "w").write("{}")
    if age:
        os.utime(fp, (time.time() - age, time.time() - age))
open(os.path.join(N.QUEUE_DIR, "rt-w.json"), "w").write(json.dumps({"id": "rt-w", "verb": "quick-test", "args": []}))
N.process_queue()
_left = sorted(os.listdir(N.QUEUE_DIR))
check("the watched queue dir is cleared of what is not a request (an old claim, an abandoned .tmp)",
      "rt-a.json.taking" not in _left and "rt-b.json.tmp" not in _left and "junk.d" not in _left, _left)
check("…but never of a .tmp the panel may be writing right now", "rt-c.json.tmp" in _left, _left)
check("answers older than an hour are swept (the panel, group-only on status/, cannot delete them)",
      not os.path.exists(_old) and os.path.exists(os.path.join(_nd, "status", "rt-w.json")))
os.unlink(os.path.join(N.QUEUE_DIR, "rt-c.json.tmp"))
# the case the early return is for: claims UNAVAILABLE (here: claims/ gone and netctl/ read-only, so it cannot be made)
# — every 10 s timer tick would otherwise log "claims unavailable" on a box with nothing to do
shutil.rmtree(os.path.join(_nd, "claims")); os.chmod(_nd, 0o555)
_logged = io.StringIO()
try:
    with contextlib.redirect_stderr(_logged):
        N.process_queue()
finally:
    os.chmod(_nd, 0o755)
check("an idle tick (empty queue) does nothing and logs nothing", _logged.getvalue() == "", _logged.getvalue())

with _cl2.redirect_stdout(_io.StringIO()):
    _, _, job = run_job((True, json.dumps({"state": "renewed", "sync": {"state": "held", "owner": "ours", "reason": "x"}})))
check("a renewal the follow HELD (self-signed served, nodes may pin it) is reported not-installed, with what to do",
      job["result"] == "not-installed" and "self-signed" in job["message"] and "node installer" in job["message"], job)
Q["_RENEW_JOB"].update(state="running")
check("address changes (apply, apply-sub, console-apply) are refused while a renewal runs",
      (Q["_renew_refusal"]() or (0,))[0] == 409 and Q["_renew_refusal"]()[1].get("code") == "renewing")
Q["_RENEW_JOB"].update(state="done")
check("…and allowed again the moment it ends", Q["_renew_refusal"]() is None)
check("the gate sits on all three address-change doors", all(
    PSRC.count('    if method == "POST" and path == "%s":\n        if _renew_refusal():' % p_) == 1
    for p_ in ("/api/access/apply", "/api/access/apply-sub", "/api/access/console-apply")))
check("…and the address-change cooldown itself is untouched (Save's lock is what it was)", "renewing" not in
      ast.get_source_segment(PSRC, next(n for n in _mod.body if isinstance(n, ast.FunctionDef) and n.name == "_access_cooldown")))

Q["_RENEW_JOB"].update(state="running")
check("a second press while one runs is refused (409 busy)", Q["_renew_start"](DEPS)[0] == 409)
Q["_RENEW_JOB"].update(state="idle"); Q["IN_DOCKER"] = True
check("a container panel is refused with why (it renews itself)", Q["_renew_start"](DEPS)[1].get("code") == "docker")
Q["IN_DOCKER"] = False; Q["PANEL_DECLARATIVE"] = True
check("a declarative panel is refused", Q["_renew_start"](DEPS)[1].get("code") == "declarative")

print("panel: the follow keeps its last report through a skip that says nothing")
_code4 = "\n\n".join(ast.get_source_segment(PSRC, n) for n in _mod.body
                     if isinstance(n, ast.FunctionDef) and n.name in ("_acme_follow", "_follow_set", "_follow_get"))
class _H: deps = {"panel_settings": {"access": {"tls": {"mode": "letsencrypt-ip"}}}, "nodes_path": os.path.join(JOBDIR, "n.json")}
F = {"os": os, "json": json, "contextlib": contextlib, "Handler": _H, "IN_DOCKER": False, "PANEL_DECLARATIVE": False,
     "_TLS_LOCK": threading.RLock(),
     "_ACME_FOLLOW_MODES": ("letsencrypt", "letsencrypt-ip", "cloudflare"), "_ACME_FOLLOW_RIDS": [],
     "_ACME_FOLLOW": {"state": "current", "owner": "other", "install_path": "/root/cert/ip/fullchain.pem"},
     "MANAGED_CERT": NEW[0], "SUB_CERT_PATH": "/nonexistent/fullchain.pem", "_sub_tls_mode": lambda m: m,
     "_netctl_enqueue": lambda deps, verb, args: "rf"}
exec(compile(_code4, "swg-panel-server(extract)", "exec"), F)
for label, reply in (("an 'address change in flight' skip", (True, json.dumps({"state": "skipped", "transient": True}))),
                     ("a helper error", (False, "unknown verb 'sync-acme'"))):
    F["_netctl_wait"] = lambda deps, r, t, _r=reply: _r
    with _cl2.redirect_stdout(_io.StringIO()):
        F["_acme_follow"]()
    check("the last report survives %s" % label, F["_ACME_FOLLOW"].get("owner") == "other", F["_ACME_FOLLOW"])
F["_netctl_wait"] = lambda deps, r, t: (True, json.dumps({"state": "no-entry", "owner": ""}))
with _cl2.redirect_stdout(_io.StringIO()):
    F["_acme_follow"]()
check("…but a real answer (the entry is gone) replaces it", F["_ACME_FOLLOW"].get("state") == "no-entry", F["_ACME_FOLLOW"])

print("SPA: a pinned bubble and the layers above it")
UISRC = open(PATHS["UI_JS"], encoding="utf-8").read()
_esc = UISRC[UISRC.index("const onEsc = e => {"):UISRC.index("};", UISRC.index("const onEsc = e => {"))]
check("a pinned bubble lets a layer opened on top of it take Escape",
      "const depthAtPin = modalDepth();" in UISRC and "if (modalDepth() !== depthAtPin) return;" in _esc
      and _esc.index("modalDepth()") < _esc.index("stopPropagation"), _esc[:200])
check("…and an open dropdown", 'if (document.querySelector(".ddpop")) return;' in _esc and _esc.index(".ddpop") < _esc.index("stopPropagation"))

print("panel: the certificate Settings reports")
_code3 = "\n\n".join(ast.get_source_segment(PSRC, n) for n in _mod.body
                     if isinstance(n, ast.FunctionDef) and n.name in ("_status_cert", "_follow_get"))
C = {"os": os, "TLS_CERT": "", "MANAGED_CERT": NEW[0], "_ACME_FOLLOW": {}, "_TLS_LOCK": threading.RLock()}
exec(compile(_code3, "swg-panel-server(extract)", "exec"), C)
check("no acme follow yet: no certificate is reported", C["_status_cert"]() == "")
C["_ACME_FOLLOW"].update(owner="ours", front="")
check("a managed file with NO installer proxy in front (the operator's own proxy) warns nobody", C["_status_cert"]() == "")
C["_ACME_FOLLOW"].update(front="nginx")
check("behind the installer's nginx/caddy, once acme.sh manages it, the managed file is reported", C["_status_cert"]() == NEW[0])
C["TLS_CERT"] = OLD[0]
check("a panel serving its own TLS reports that certificate, as before", C["_status_cert"]() == OLD[0])

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAIL: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
