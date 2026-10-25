#!/usr/bin/env python3
"""Self-test — THE SOCKS5 EXIT, the node's half (docs/SOCKS5-EXIT-PLAN.md §6, release plan S10 / P3).

The panel hands a node a proxy; the node runs hev-socks5-tunnel, which presents it as the TUN `s5x-<id>`, and from there it
is an ordinary point-to-point device exit. What has to hold, each on the real swg-noded with only its effects stubbed:

  [1] the binary — the pinned hev and nothing else: a tampered download from any source is deleted and never made
      executable, the panel's mirror is asked first with the pin, an arch with no build is refused, and a fetch runs in a
      background thread, never in the pass
  [2] the config — §6.3 as P0 ran it: `udp: 'udp'` always (T2), mapdns always, cache-size below the /16's address count
      (hev 2.18.0 exits 254 with no log line at 65536), MTU 1500; the operator's text quoted
  [3] the unit — §6.4's transient unit in swg-exit.slice, the signature in its Description and never the password on the
      command line; a settled exit costs no fork; one waiting out its restart back-off is left to it; a changed config
      replaces it; the slice's CPU cap set once; below systemd 254 RestartSec=30 instead of the back-off; docker — a child,
      relaunched after a back-off, never two
  [4] the proxy check — greeting, login, CONNECT by name + TLS through it, UDP ASSOCIATE + DNS through the relay, against
      an in-test SOCKS5 server: every failure code, UDP yes and no; and the UDP flag's hysteresis (the first result sets
      it, a change needs two in a row, a disagreement brings the next check forward)
  [5] the rule families (§6.6) — whole-interface DNS DNAT'd to mapdns while the device is up, with the carried-network
      RETURNs above (T15); UDP refused in nft except to mapdns (T10) while the proxy carries none; rule-scoped DNS
      unmarked (T13); nothing rewritten when nothing changed; Force DNS unchanged by the shared helper
  [6] s9a F18 — an unknown kind takes down the device a known kind made for that id
  [7] the exit in the pass — a SOCKS row reports udp_ok and the check, never asks for a WireGuard handshake (no fork),
      is probed at the adopted cadence, and a dead verdict carries the proxy's own reason
  [8] T14 — the TUN is never an operator's device in a picker

Hermetic: run() is stubbed and its argv inspected; the SOCKS5, TLS and DNS servers are threads on 127.0.0.1.

Run: python3 tests/socks5_exit_node_selftest.py           (0 = pass)
     --perturb-<name>   plants one regression (see PLANTS) and expects RED
"""
import importlib.machinery, importlib.util, json, os, socket, ssl, struct, subprocess, sys, tempfile, threading, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb-pin": ("            if _turn_sha_ok(tmp, want):\n                try:\n                    os.chmod(tmp, 0o755)",
                      "            if True:\n                try:\n                    os.chmod(tmp, 0o755)"),                       # [1]
    "--perturb-arch": ('    if arch not in HEV_SHA256:\n        return "", "no hev build', '    if False:\n        return "", "no hev build'),  # [1]
    "--perturb-udp": ("socks5:\\n  address: %s\\n  port: %d\\n  udp: 'udp'\\n%s", "socks5:\\n  address: %s\\n  port: %d\\n%s"),  # [2]
    "--perturb-cache": ("S5X_CACHE = 65535", "S5X_CACHE = 65536"),                                                      # [2]
    "--perturb-backoff": ('    if live and u.get("Description", "").split()[3:] == sig.split():',
                          '    if False and u.get("Description", "").split()[3:] == sig.split():'),                     # [3]
    "--perturb-settled": ('    if state == "up" and started == sig and xid in _S5X_SEEN:\n        return ""',
                          '    if False:\n        return ""'),                                                           # [3]
    "--perturb-sysd": ('if _s5x_sysd() >= 254', 'if True'),                                                             # [3]
    "--perturb-child": ("    if pid and have == sig:\n", "    if False:\n"),                                             # [3]
    "--perturb-hyst": ("        elif s[\"pending\"] == u:\n", "        elif True:\n"),                                   # [4]
    "--perturb-udpcheck": ("            if len(d) > 12 and d[3] == 1 and d[10:12] == qid.to_bytes(2, \"big\"):",
                           "            if len(d) > 12 and d[3] == 1:"),                                                 # [4]
    "--perturb-t10": ("    oifname \"%s\" ip daddr != %s meta l4proto udp reject", "    oifname \"%s\" %.0smeta l4proto udp reject"),  # [5]
    "--perturb-t15": ('_dns_dnat(whole, res, [p for p, _i in (nets or ())], S5X_DNS_TAG', '_dns_dnat(whole, res, [], S5X_DNS_TAG'),  # [5]
    "--perturb-dead": ("                    and _devexit_state(e[\"dev\"]) == \"up\"})", "                    })"),  # [5]
    # [5] s10-p3 F4 — a partial arrival
    "--perturb-part-dnat": ('if (not e.get("part") or str(e["subnet"]) in _fell)', 'if (True or str(e["subnet"]) in _fell)'),
    "--perturb-part-full": ('if e.get("part")} - _full), res', 'if e.get("part")}), res'),                                     # review F4
    "--perturb-part-fell": ('    return set(bad)\n', '    return set()\n'),                                                     # review F1
    "--perturb-part-retry": ("    if _S5X_NFT[\"arr_bad\"] and _S5X_NFT[\"arr_bad\"][0] == key:", "    if False:"),       # review F2
    "--perturb-part-first": ('(_S5X_NFT["arr"] is None and not any_socks)', '(False)'),                                         # golden
    "--perturb-part-rule": ("    _fell = _s5x_arr_dns(sorted({", "    _fell = (lambda *a: set())(sorted({"),
    "--perturb-part-settle": ("    if have != sorted(_one(S) for S in want) or len(cur) != len(have):", "    if True:"),
    "--perturb-unmark": ('                  and e.get("scope") == "rule" and str(e.get("table") or "").isdigit()})',
                         '                  and False})'),                                                                  # [5]
    "--perturb-f18": ('                    if rec.get("provider") in EXIT_KINDS and (_dev_link_state(_od) != "absent" or rec.get("started")):',
                      '                    if False:'),                                                                # [6]
    "--perturb-hs": ('"handshake": (_exit_handshake(rec, dev) if _live and prov != "socks5" else None)',
                     '"handshake": (_exit_handshake(rec, dev) if _live else None)'),                                     # [7]
    "--perturb-cadence": ("if dev not in _sx or _sx[dev]]", "]"),                                                    # [7]
    "--perturb-why": ('                    _hl["why"] = S5X_WHY.get(_c["why"], _c["why"])', '                    pass'),       # [7]
    "--perturb-t14": ('"flannel", "s5x")', '"flannel")'),                                                              # [8]
    "--perturb-idle": ('    if whole or _S5X_NFT["dns"] is not False:', '    if True:'),                                       # [5]
    # the max review's fix round (F-numbers of runs/s10-p3-socks)
    "--perturb-udpfirst": ('        out["udp"] = _s5x_udp(host, port, user, pw, timeout, udp_wait, _dns)\n    except Exception:\n        out["udp"] = False\n',
                           '        pass\n    except Exception:\n        pass\n'),                                       # [4] F12
    "--perturb-tries": ("        for k in range(3):", "        for k in range(1):"),                                       # [4] F17
    "--perturb-firstno": ("s[\"udp_ok\"], s[\"pending\"] = u, (False if u is False else None)", "s[\"udp_ok\"], s[\"pending\"] = u, None"),  # [4] F17
    "--perturb-stalecheck": ("    if not got or (sig is not None and got[1] != sig):", "    if not got:"),                    # [4] F22
    "--perturb-bare": ("    subnets = [_one(str(S)) for S in subnets]\n", "    subnets = [str(S) for S in subnets]\n"),   # [5] F30
    "--perturb-retry": ('        _S5X_NFT["dns"] = bool(whole) or _had', '        _S5X_NFT["dns"] = bool(whole)'),           # [5] F11
    "--perturb-heal": ('        if not (rej or unm) or run(["nft", "list", "table", "inet", S5X_NFT_TABLE]).returncode == 0:\n            return',
                       '        return'),                                                                                # [5] F3
    "--perturb-nonft": (" or _nft_absent(r) or r.returncode == 127,", " or _nft_absent(r),"),                         # [5] F25
    "--perturb-once": ('                if _downed and rec.get("started"):', '                if False:'),                       # [6] F36
    "--perturb-sync": ("    threading.Thread(target=go, daemon=True).start()\n\n\ndef _s5x_take", "    go()\n\n\ndef _s5x_take"),  # [7] F15
    "--perturb-byip": ('{"endpoint": rec.get("endpoint"), "mapdns": S5X_DNS})', '{"endpoint": rec.get("endpoint"), "mapdns": None})'),  # [7] F9
    "--perturb-twice": ("    if dev in _S5X_INFLIGHT or not sk:\n        return\n", "    if not sk:\n        return\n"),   # [7] F23
    "--perturb-answered": ('    return bool((tr or {}).get("ip") or (tr or {}).get("err") or reach is not None)',
                           '    return bool((tr or {}).get("ip") or reach is not None)'),                                   # [7] F24
    "--perturb-s5xblip": ('                        if _EXIT_HEALTH.get(dev):\n                            _EXIT_HEALTH[dev]["ok_since"] = None\n',
                          '                        _EXIT_HEALTH.pop(dev, None)\n'),                                     # [7] F8
    "--perturb-setup": ('                            rec["setup"], err = err, ""', '                            pass'),          # [7] F13
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)
if "--perturb-sete" in sys.argv:                     # verify F47's plant: lib/common.sh's `|| true` dropped (in the test's copy)
    os.environ["S5X_PLANT_SETE"] = "1"
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NO_REEXEC"] = "1"
TMP = tempfile.mkdtemp(prefix="s5x-node-")
if MODE:
    _src = open(NODED, encoding="utf-8").read()
    _cut, _new = PLANTS[MODE]
    assert _src.count(_cut) == 1, "perturbation anchor for %s is missing or not unique — would FALSE-PASS" % MODE
    _tmp = os.path.join(TMP, "noded-perturbed.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, _new, 1))
    N = _load(_tmp, "swgnoded")
else:
    N = _load(NODED, "swgnoded")
N.log = lambda *a, **k: None
N.STATE_DIR = os.path.join(TMP, "state")
N.EXIT_DIR = os.path.join(TMP, "state", "exits")
os.makedirs(N.EXIT_DIR)


class R:
    def __init__(s, out="", rc=0, err=""):
        s.stdout, s.stderr, s.returncode = out, err, rc


# ── [1] the binary ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the binary: the pinned hev, from wherever it comes")
P = _load(PANEL, "swgpanel")
check("the panel's pin is the node's (tag, owner, both hashes, both assets)",
      (P.HEV_TAG, P.HEV_OWNER, P.HEV_SHA256, P.HEV_ASSET) == (N.HEV_TAG, N.HEV_OWNER, N.HEV_SHA256, N.HEV_ASSET))
GOOD, BAD = b"\x7fELF-the-pinned-one", b"\x7fELF-something-else"
N.HEV_SHA256 = dict(N.HEV_SHA256, amd64=__import__("hashlib").sha256(GOOD).hexdigest())
_fetches, _bytes = [], {"v": BAD}
N._turn_panel_fetch = lambda owner, tag, arch, dest, want: (_fetches.append((owner, tag, arch, want)), False)[1]
def _curl(argv, **k):
    if argv[0] == "curl":
        open(argv[argv.index("-o") + 1], "wb").write(_bytes["v"])
        return R()
    return R()
N.run = _curl
dest = os.path.join(TMP, "hev", "bin")
err = N._hev_fetch("amd64", dest)
check("the panel's mirror is asked first, for the pinned tag and with the pinned hash",
      _fetches[:1] == [(N.HEV_OWNER, N.HEV_TAG, "amd64", N.HEV_SHA256["amd64"])], _fetches)
check("a tampered download (GitHub, then every mirror) is refused and nothing is left behind",
      "checksum mismatch" in err and not os.path.exists(dest) and not os.path.exists(dest + ".dl"), (err, os.listdir(os.path.dirname(dest))))
_bytes["v"] = GOOD
err = N._hev_fetch("amd64", dest)
check("the pinned bytes are put in place, executable", err == "" and os.access(dest, os.X_OK), err)
N._turn_arch = lambda: "riscv64"
try:
    p, why = N.hev_binary()
except Exception as e:                              # a refusal that raises is no refusal
    p, why = "", "raised %r" % e
check("an arch with no build is refused, never fetched", p == "" and "no hev build" in why, why)
N._turn_arch = lambda: "amd64"
N._HEV.update(thread=None, err="", next=0.0, fails=0, ok=None)
_gate = threading.Event()
N._hev_fetch = lambda arch, d: (_gate.wait(5), "")[1]
t0 = time.monotonic()
p, why = N.hev_binary()
check("a missing binary is fetched in the BACKGROUND: the pass returns at once, saying so",
      p == "" and "fetching" in why and time.monotonic() - t0 < 1 and N._HEV["thread"].is_alive(), (why, time.monotonic() - t0))
p2, why2 = N.hev_binary()
check("…and a second pass does not start a second fetch", N._HEV["thread"].is_alive() and "fetching" in why2)
_gate.set(); N._HEV["thread"].join(5)

# ── [2] the config ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the config hev reads")
y = N._s5x_yml("s5x-aabbccdd", {"host": "proxy.example", "port": 1080, "user": "u'1", "pass": "p: #x"})
check("UDP is standard SOCKS5 UDP (`udp: 'udp'`, T2)", "\n  udp: 'udp'\n" in y, y)
check("mapdns is always there: 198.18.0.2:53, 198.19.0.0/16", "mapdns:\n  address: 198.18.0.2\n  port: 53\n  network: 198.19.0.0\n  netmask: 255.255.0.0\n" in y, y)
_cache = int(y.split("cache-size: ")[1].split()[0])
check("cache-size is below the /16's address count (65536 makes hev 2.18.0 exit 254 with no log line)", _cache < 2 ** 16, _cache)
check("the TUN: its name, MTU 1500 (P0), 198.18.0.1", "tunnel:\n  name: s5x-aabbccdd\n  mtu: 1500\n  ipv4: 198.18.0.1\n" in y, y)
check("the operator's text is quoted, a quote doubled", "username: 'u''1'" in y and "password: 'p: #x'" in y, y)
check("no login, no login lines", "username" not in N._s5x_yml("s5x-a", {"host": "1.2.3.4", "port": 1, "user": "", "pass": ""}))

# ── [3] the unit ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the transient unit (bare metal) and the child (docker)")
calls, UNIT = [], {}
def _sd(argv, **k):
    calls.append(argv)
    if argv[:2] == ["systemctl", "show"]:
        return R("\n".join("%s=%s" % kv for kv in UNIT.items()))
    if argv[:2] == ["systemctl", "--version"]:
        return R("systemd 255 (255.4)")
    return R()
N.run = _sd
N._S5X_RUN.update(quota=False, sysd=None)
N._S5X_SEEN.clear()
SIG = "0123456789ab hev-2.18.0"
UNIT.clear()
e = N._s5x_ensure_unit("aabbccdd", SIG, "/bin/hev", "/x/s5x-aabbccdd.yml", "absent", "")
_start = next((c for c in calls if c[0] == "systemd-run"), [])
check("no unit: started as swg-s5x-<id> in swg-exit.slice", e == "" and "--unit=swg-s5x-aabbccdd" in _start
      and "--slice=swg-exit.slice" in _start, _start)
check("…its Description carries the id and the signature", "--description=swg exit aabbccdd " + SIG in _start, _start)
check("…with §6.4's sandbox and the back-off (systemd ≥ 254)",
      all(x in _start for x in ("Restart=on-failure", "RestartSteps=8", "RestartMaxDelaySec=300", "NoNewPrivileges=yes",
                                "CapabilityBoundingSet=CAP_NET_ADMIN", "DeviceAllow=/dev/net/tun rw", "ProtectSystem=strict",
                                "SystemCallFilter=@system-service")), _start)
check("…the password never on a command line (only the yml path)", _start[-2:] == ["/bin/hev", "/x/s5x-aabbccdd.yml"], _start[-3:])
check("…and the slice capped once (CPUQuota=50%)", ["systemctl", "set-property", "--runtime", "swg-exit.slice", "CPUQuota=50%"] in calls)
calls.clear()
N._s5x_ensure_unit("aabbccdd", SIG, "/bin/hev", "/x/s5x-aabbccdd.yml", "up", SIG)
check("settled (up, same signature, seen): no fork at all", calls == [], calls)
calls.clear()
UNIT.update(LoadState="loaded", ActiveState="activating", SubState="auto-restart", Description="swg exit aabbccdd " + SIG)
e = N._s5x_ensure_unit("aabbccdd", SIG, "/bin/hev", "/x/s5x-aabbccdd.yml", "absent", SIG)
check("a unit waiting out its restart back-off is LEFT to it (no stop, no new start), and the row says so",
      not any(c[0] == "systemd-run" or c[:2] == ["systemctl", "stop"] for c in calls) and "keeps exiting" in e, (calls, e))
calls.clear()
UNIT.update(ActiveState="active", SubState="running", Description="swg exit aabbccdd fedcba987654 hev-2.18.0")
N._s5x_ensure_unit("aabbccdd", SIG, "/bin/hev", "/x/s5x-aabbccdd.yml", "up", "fedcba987654 hev-2.18.0")
check("a changed config: the running unit is stopped and the new one started",
      ["systemctl", "stop", "swg-s5x-aabbccdd"] in calls and any(c[0] == "systemd-run" for c in calls)
      and not any(c[:3] == ["systemctl", "set-property", "--runtime"] for c in calls), calls)
N._S5X_RUN["sysd"] = 252
_old = N._s5x_argv("aabbccdd", SIG, "/bin/hev", "/y")
check("below systemd 254: RestartSec=30, no back-off properties it would refuse",
      "RestartSec=30" in _old and not any("RestartSteps" in x for x in _old), _old)
N._S5X_RUN["sysd"] = None
# docker: a real child — a stand-in for hev that holds its yml on its command line
fake = os.path.join(TMP, "fakehev")
open(fake, "w").write("#!%s\nimport time\ntime.sleep(30)\n" % sys.executable); os.chmod(fake, 0o755)   # keeps its argv
yml = os.path.join(N.EXIT_DIR, "s5x-11223344.yml"); open(yml, "w").write("x")
N.run = lambda *a, **k: R()
N._S5X_PROCS.clear()
e1 = N._s5x_ensure_child("11223344", "s5x-11223344", SIG, fake, yml)
time.sleep(0.3)
pid1, sig1 = N._s5x_child("s5x-11223344", yml)
e2 = N._s5x_ensure_child("11223344", "s5x-11223344", SIG, fake, yml)
pid2, _ = N._s5x_child("s5x-11223344", yml)
check("docker: hev runs as a child, its pid and signature beside it", e1 == "" and pid1 and sig1 == SIG, (e1, pid1, sig1))
check("…a second pass keeps it (never two)", e2 == "" and pid2 == pid1, (pid1, pid2))
assert pid1 > 1, "no child pid — never signal 0 (it is this test's own process group)"
try:
    os.kill(pid1, 9)
except ProcessLookupError:
    pass
N._S5X_PROCS["11223344"]["proc"].wait()
e3 = N._s5x_ensure_child("11223344", "s5x-11223344", SIG, fake, yml)
check("…one that died is relaunched only after a back-off, and the row says so", "starting it again" in e3
      and not N._s5x_child("s5x-11223344", yml)[0], e3)
N._S5X_PROCS["11223344"]["next"] = 0
N._s5x_ensure_child("11223344", "s5x-11223344", SIG, fake, yml)
time.sleep(0.3)
pid4, _ = N._s5x_child("s5x-11223344", yml)
N._s5x_ensure_child("11223344", "s5x-11223344", "aaaaaaaaaaaa hev-2.18.0", fake, yml)
time.sleep(0.3)
pid5, sig5 = N._s5x_child("s5x-11223344", yml)
check("…a changed config replaces it", pid4 and pid5 and pid5 != pid4 and sig5 == "aaaaaaaaaaaa hev-2.18.0", (pid4, pid5, sig5))
N.NODE_KIND = "docker"
N._s5x_down("11223344", "s5x-11223344")
N.NODE_KIND = "baremetal"
time.sleep(0.2)
check("…and teardown stops it and removes its yml and pidfile", not N._pid_alive(pid5)
      and not os.path.exists(yml) and not os.path.exists(N._s5x_pidfile("s5x-11223344")))

# verify F47: the bare→Docker convert's hev stop runs under `set -euo pipefail` (install-docker.sh) — a stopped transient unit
# is unloaded, so its `reset-failed` fails, and that must not abort the convert half-way
_lc = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
_lb = _lc[_lc.index("lc_teardown_baremetal(){"):]
_loop = _lb[_lb.index("  local u; for u in"):_lb.index("  systemctl stop swg-exit.slice")]
if os.environ.get("S5X_PLANT_SETE"):
    _loop = _loop.replace(" || true", "")
_sh = ("set -euo pipefail\nsystemctl(){ case \"$1\" in list-units) echo 'swg-s5x-aabbccdd.service loaded active running x';; "
       "reset-failed) return 1;; *) return 0;; esac; }\nf(){\n" + _loop + "\n}\nf\necho REACHED\n")
_o = subprocess.run(["bash", "-c", _sh], capture_output=True, text=True)
check("the convert's hev stop survives `set -e` when a unit is already unloaded — verify F47", "REACHED" in _o.stdout, (_o.stdout, _o.stderr))

# ── [4] the proxy check ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the proxy check, against a SOCKS5 server in this test")
cd = tempfile.mkdtemp(dir=TMP)
crt, key = os.path.join(cd, "c.pem"), os.path.join(cd, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=www.cloudflare.com", "-days", "1",
                "-keyout", key, "-out", crt], capture_output=True, check=True)
sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sctx.load_cert_chain(crt, key)
def listen():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(16); return s, s.getsockname()[1]
tls_l, TLS_PORT = listen()
def tls_srv():
    while True:
        try:
            c, _ = tls_l.accept()
        except OSError:
            return
        try:
            t = sctx.wrap_socket(c, server_side=True); t.recv(4096)
            t.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nfl=1\nip=203.0.113.77\nloc=FI\n"); t.close()
        except Exception:
            pass
threading.Thread(target=tls_srv, daemon=True).start()
dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); dns.bind(("127.0.0.1", 0)); DNS_PORT = dns.getsockname()[1]
def dns_srv():
    while True:
        try:
            d, a = dns.recvfrom(4096)
        except OSError:
            return
        dns.sendto(d[:2] + b"\x81\x80" + d[4:], a)                 # an answer: the same id
threading.Thread(target=dns_srv, daemon=True).start()
MODEL = {"auth": None, "rep": 0, "udp": True, "junk": False, "stray": False, "drop_first": False}
def rx(c, n):
    b = b""
    while len(b) < n:
        x = c.recv(n - len(b))
        if not x:
            raise ConnectionError()
        b += x
    return b
def socks_conn(c):
    try:
        ver, nm = rx(c, 2); meth = rx(c, nm)
        if MODEL["junk"]:
            c.sendall(b"HTTP/1.1 400 Bad\r\n\r\n"); return
        if MODEL["auth"]:
            if 2 not in meth:
                c.sendall(b"\x05\xff"); return
            c.sendall(b"\x05\x02"); rx(c, 1); u = rx(c, rx(c, 1)[0]); p = rx(c, rx(c, 1)[0])
            if (u.decode(), p.decode()) != MODEL["auth"]:
                c.sendall(b"\x01\x01"); return
            c.sendall(b"\x01\x00")
        else:
            c.sendall(b"\x05\x00")
        v, cmd, _r, at = rx(c, 4)
        dst = rx(c, rx(c, 1)[0]).decode() if at == 3 else socket.inet_ntoa(rx(c, 4)); port = struct.unpack(">H", rx(c, 2))[0]
        if cmd == 1:
            if MODEL["rep"]:
                c.sendall(b"\x05" + bytes([MODEL["rep"]]) + b"\x00\x01" + b"\x00" * 6); return
            up = socket.create_connection(("127.0.0.1", TLS_PORT))
            c.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
            def pipe(a, b):
                try:
                    while True:
                        d = a.recv(65536)
                        if not d:
                            break
                        b.sendall(d)
                except Exception:
                    pass
                for x in (a, b):
                    try: x.shutdown(socket.SHUT_RDWR)
                    except Exception: pass
            threading.Thread(target=pipe, args=(up, c), daemon=True).start(); pipe(c, up)
        elif cmd == 3:
            if not MODEL["udp"]:
                c.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6); return
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("127.0.0.1", 0)); u.settimeout(5)
            c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + struct.pack(">H", u.getsockname()[1]))
            d, fr = u.recvfrom(4096)
            if MODEL["drop_first"]:                     # a lost datagram: the first query never reaches the resolver
                d, fr = u.recvfrom(4096)
            out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); out.settimeout(3)
            out.sendto(d[10:], ("127.0.0.1", DNS_PORT)); a, _ = out.recvfrom(4096)
            if MODEL["stray"]:                          # a datagram that is not the answer to our query
                a = bytes([a[0] ^ 0xFF, a[1]]) + a[2:]
            u.sendto(d[:10] + a, fr); c.recv(1)
    except Exception:
        pass
    finally:
        try: c.close()
        except Exception: pass
socks_l, SOCKS_PORT = listen()
def socks_srv():
    while True:
        try:
            c, _ = socks_l.accept()
        except OSError:
            return
        threading.Thread(target=socks_conn, args=(c,), daemon=True).start()
threading.Thread(target=socks_srv, daemon=True).start()
_cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); _cctx.check_hostname = False; _cctx.verify_mode = ssl.CERT_NONE
N._exit_tls = lambda: _cctx                       # the test's server is self-signed; the real one verifies
CK = lambda **k: N._socks_check("127.0.0.1", k.pop("port", SOCKS_PORT), k.pop("user", ""), k.pop("pw", ""), timeout=3,
                                udp_wait=2, _dns=("127.0.0.1", DNS_PORT))
r = CK()
check("all well: logged in, the egress IP and country from the trace, UDP carried",
      r["login"] and r["egress_ip"] == "203.0.113.77" and r["loc"] == "FI" and r["udp"] is True and r["why"] == "", r)
MODEL["udp"] = False
r = CK()
check("a proxy that refuses UDP ASSOCIATE: UDP not carried, everything else fine", r["udp"] is False and r["why"] == "", r)
MODEL.update(stray=True, udp=True)
r = CK()
check("…and a stray datagram on the relay is not taken for the answer", r["udp"] is False, r)
MODEL.update(stray=False, udp=True, auth=("u", "p"))
check("a login the proxy wants and none is set: auth_required", CK()["why"] == "auth_required")
check("a wrong password: auth_failed", CK(user="u", pw="x")["why"] == "auth_failed")
check("the right one passes", CK(user="u", pw="p")["why"] == "", CK(user="u", pw="p"))
MODEL.update(auth=None, rep=2)
check("SOCKS reply 2 (not allowed by ruleset): not_allowed — the allow-list sentence", CK()["why"] == "not_allowed")
MODEL["rep"] = 5
r = CK()
check("any other refusal of the CONNECT: connect_failed", r["why"] == "connect_failed")
check("…and its UDP relay is still judged (it answered: carried) — F12", r["udp"] is True, r)
MODEL.update(rep=0, drop_first=True)
r = CK()
check("one lost datagram is not \"no UDP\": the query is sent again — F17", r["udp"] is True, r)
MODEL["drop_first"] = False
MODEL.update(rep=0, junk=True)
check("something that is not SOCKS5: not_socks5", CK()["why"] == "not_socks5")
MODEL["junk"] = False
_dead = socket.socket(); _dead.bind(("127.0.0.1", 0)); _dp = _dead.getsockname()[1]; _dead.close()
check("a closed port: refused", CK(port=_dp)["why"] == "refused")
# hysteresis
res = {"changed": 0, "errors": []}
N._S5X.clear()
def take(u, at=None, sig="s1", cur="s1"):
    N._S5X_CHECKS["s5x-h"] = (at or time.time(), sig, {"login": True, "egress_ip": "1", "loc": "", "udp": u, "rtt_ms": 1, "why": ""})
    return N._s5x_take("s5x-h", res, sig=cur)
s = take(True)
check("the first result sets the UDP flag", s["udp_ok"] is True and s["pending"] is None, s)
s = take(False)
check("one disagreeing result does not flip it…", s["udp_ok"] is True and s["pending"] is False, s)
check("…but brings the next check forward to a minute", 50 < s["next"] - time.time() <= N.S5X_RECHECK_S + 1, s["next"] - time.time())
s = take(False)
check("…and a second in a row does", s["udp_ok"] is False and s["pending"] is None, s)
s = take(True); s = take(False)
check("a result that agrees again clears the pending one", s["udp_ok"] is False and s["pending"] is None, s)
check("…and the next check is the usual ten minutes away", s["next"] - time.time() > N.S5X_CHECK_EVERY_S - 5)
s = take(True, sig="old", cur="new")
check("an answer about a config since replaced is not taken for the new one — F22", s["udp_ok"] is False and s["pending"] is None, s)
N._S5X.clear()
s = take(False)
check("a FIRST \"no\" sets the flag but is asked again in a minute, not ten — F17",
      s["udp_ok"] is False and s["next"] - time.time() <= N.S5X_RECHECK_S + 1, (s, s["next"] - time.time()))

# ── [5] the rule families ───────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[5] DNS to mapdns, UDP refused, rule DNS unmarked")
NAT = []                                          # a model of nat PREROUTING: the rules as `iptables -S` prints them
NFT = []
def _ipt(argv, **k):
    if argv[0] == "nft":
        NFT.append((argv, k.get("input_text", ""))); return R()
    if argv[:5] == ["iptables", "-t", "nat", "-S", "PREROUTING"]:
        return R("\n".join(["-P PREROUTING ACCEPT"] + NAT))
    if argv[:3] == ["iptables", "-t", "nat"] and argv[3] in ("-A", "-I", "-D"):
        a = argv[6:] if argv[3] == "-I" else argv[5:]   # `-I PREROUTING 1 …`: the position is not part of the rule
        ln = "-A PREROUTING " + " ".join(x if " " not in x else '"%s"' % x for x in a)
        ln = ln.replace("--comment ", "-m comment --comment ").replace("-m comment -m comment", "-m comment")
        if argv[3] == "-A": NAT.append(ln)
        elif argv[3] == "-I": NAT.insert(0, ln)
        elif ln in NAT: NAT.remove(ln)
        return R()
    return R()
N.run = _ipt
N._ipt_del_listed = lambda targs, chain, ln: (NAT.remove(ln) if ln in NAT else None) is None
N._dev_link_state = lambda d: "up" if d in ("s5x-aa", "s5x-bb") else "absent"
N._EXIT_HEALTH.clear()
N._EXITS["socks"] = {"s5x-aa": False, "s5x-bb": True}
DX = [{"subnet": "10.17.0.0/24", "dev": "s5x-aa", "table": 7001},
      {"subnet": "10.18.0.0/24", "dev": "s5x-bb", "table": 7002},
      {"subnet": "10.19.0.0/24", "dev": "s5x-aa", "table": 7003, "scope": "rule"},
      {"subnet": "10.20.0.0/24", "dev": "wgx-other", "table": 7004}]
NETS = [("192.168.50.0/24", "awg0")]
N._S5X_NFT["sig"] = None
res = {"changed": 0, "errors": []}
N._s5x_rules(DX, NETS, res)
dnat = [l for l in NAT if "swg-s5x-dns " in l + " " and "DNAT" in l]
ret = [l for l in NAT if "swg-s5x-dns-net" in l]
check("whole-interface DNS of each SOCKS exit's subnet goes to mapdns (UDP only, 198.18.0.2:53)",
      sorted(l.split("-s ")[1].split()[0] for l in dnat) == ["10.17.0.0/24", "10.18.0.0/24"]
      and all("-p udp" in l and "198.18.0.2:53" in l for l in dnat), NAT)
check("…not a rule-scoped one (T13), nor another device's", not any(x in " ".join(dnat) for x in ("10.19.0.0", "10.20.0.0")), dnat)
check("T15: DNS to a network this node carries is let past it, ABOVE the DNATs",
      ret and all(NAT.index(r_) < NAT.index(dnat[0]) for r_ in ret) and all("-d 192.168.50.0/24" in r_ for r_ in ret), NAT)
txt = NFT[-1][1] if NFT else ""
check("UDP into the device whose proxy carries none is refused at once — except to mapdns (T10)",
      'oifname "s5x-aa" ip daddr != 198.18.0.2 meta l4proto udp reject' in txt, txt)
check("…not into the one whose proxy carries it", 's5x-bb' not in txt, txt)
check("…its rule-scoped DNS unmarked so it goes direct (T13), after swg_smart and swg_p2p",
      "meta mark 0x1b5b udp dport 53 meta mark set 0x0" in txt and "priority mangle + 6" in txt, txt)
check("…in an nft table of its own, so no iptables accept can sit above the refusal",
      "table inet swg_s5x" in txt and "hook forward priority filter - 1" in txt, txt)
check("…its chains named nothing nft reads as a keyword (`fwd` is one — measured: the ruleset did not load)",
      "chain udp_refuse {" in txt and "chain dns_unmark {" in txt and "chain fwd " not in txt and "chain pre " not in txt, txt)
_writes = lambda: [x for x in NFT if x[0][:2] == ["nft", "-f"]]
n0, nat0 = len(_writes()), list(NAT)
N._s5x_rules(DX, NETS, {"changed": 0, "errors": []})
check("a second pass with nothing changed writes nothing", len(_writes()) == n0 and NAT == nat0, (len(_writes()), NAT))
N._EXIT_HEALTH["s5x-aa"] = {"dead": True, "fail_since": 0, "fails": 9, "ok_since": None, "since": 0, "why": "x"}
N._s5x_rules(DX, NETS, {"changed": 0, "errors": []})
dnat = [l for l in NAT if "swg-s5x-dns " in l + " " and "DNAT" in l]
check("a DEAD device's subnet is not sent to mapdns (its traffic goes direct or is held — DNS must not die with it)",
      not any("10.17.0.0" in l for l in dnat) and any("10.18.0.0" in l for l in dnat), dnat)
N._EXIT_HEALTH.clear()
N._EXITS["socks"] = {}
N._s5x_rules([], NETS, {"changed": 0, "errors": []})
check("no SOCKS exit: its DNATs and its nft table are gone", not [l for l in NAT if "swg-s5x" in l]
      and NFT[-1][0][:4] == ["nft", "delete", "table", "inet"], (NAT, NFT[-1]))
# F30: a hop-2 record's BARE address is settled, not rewritten every pass
N._EXITS["socks"] = {"s5x-aa": True}; N._S5X_NFT.update(sig=None, dns=None); NAT[:] = []
N._s5x_rules([{"subnet": "10.255.0.3", "dev": "s5x-aa", "table": 7005}], [], {"changed": 0, "errors": []})
_nat1 = list(NAT); _c30 = {"changed": 0, "errors": []}
N._s5x_rules([{"subnet": "10.255.0.3", "dev": "s5x-aa", "table": 7005}], [], _c30)
check("a bare (hop-2) subnet: DNAT'd once, then left alone — no rewrite every pass — F30",
      any("10.255.0.3/32" in l for l in _nat1) and _c30["changed"] == 0 and NAT == _nat1, (_nat1, NAT, _c30))
# F11: a removal that did not take is retried on the next pass
_stuck = {"on": True}
_r11 = N.run
N.run = lambda argv, **k: (R() if (_stuck["on"] and argv[:4] == ["iptables", "-t", "nat", "-D"]) else _r11(argv, **k))
N._EXITS["socks"] = {}
N._s5x_rules([], [], {"changed": 0, "errors": []})
check("a removal that failed is retried: the next pass reads again — F11", N._S5X_NFT["dns"] is True and any("swg-s5x" in l for l in NAT),
      (N._S5X_NFT["dns"], NAT))
_stuck["on"] = False
N._s5x_rules([], [], {"changed": 0, "errors": []}); N._s5x_rules([], [], {"changed": 0, "errors": []})
check("…and once it took, the reads stop", N._S5X_NFT["dns"] is False and not any("swg-s5x" in l for l in NAT), (N._S5X_NFT, NAT))
N.run = _r11
# F3: a table flushed from outside is written again
_tbl = {"there": True}
_r3 = N.run
N.run = lambda argv, **k: (R(rc=0 if _tbl["there"] else 1) if argv[:3] == ["nft", "list", "table"] else _r3(argv, **k))
N._EXITS["socks"] = {"s5x-aa": False}; N._S5X_NFT.update(sig=None, dns=None)
N._s5x_rules([{"subnet": "10.17.0.0/24", "dev": "s5x-aa", "table": 7001}], [], {"changed": 0, "errors": []})
n3 = len(_writes()); _tbl["there"] = False
N._s5x_rules([{"subnet": "10.17.0.0/24", "dev": "s5x-aa", "table": 7001}], [], {"changed": 0, "errors": []})
check("the nft table flushed by something else (nftables.service, firewalld) is written again the next pass — F3",
      len(_writes()) == n3 + 1 and "udp_refuse" in _writes()[-1][1], (n3, len(_writes())))
N.run = _r3
# F25: no nft binary, no SOCKS exit: nothing said
_r25 = N.run
N.run = lambda argv, **k: (R(rc=127, err="No such file or directory: 'nft'") if argv[0] == "nft" else _r25(argv, **k))
N._EXITS["socks"] = {}; N._S5X_NFT.update(sig=None, dns=None)
_c25 = {"changed": 0, "errors": []}
N._s5x_rules([], [], _c25)
check("a node without nft and without a SOCKS exit reports no error — F25", _c25["errors"] == [] and N._S5X_NFT["sig"] == ((), ()), _c25)
N.run = _r25
_seen = []
_r0 = N.run
N.run = lambda argv, **k: (_seen.append(argv), _r0(argv, **k))[1]
N._S5X_NFT.update(sig=None, dns=None)
N._s5x_rules([], [], {"changed": 0, "errors": []})
_n1 = len(_seen)
_c2 = {"changed": 0, "errors": []}
N._s5x_rules([], [], _c2)
N._s5x_rules([], [], _c2)
check("⚠️ a node with no SOCKS exit: after its first pass, a routing pass costs no fork and counts no change",
      _n1 >= 1 and len(_seen) == _n1 and _c2["changed"] == 0, (_n1, _seen[_n1:], _c2))
N.run = _r0
NAT[:] = []
N._smart_dns_redirect(["10.30.0.0/24"], {"changed": 0, "errors": []}, nets=["192.168.50.0/24"])
check("Force DNS through the shared helper: udp + tcp to dnsmasq, its own RETURN above — unchanged",
      sorted(l.split("-p ")[1].split()[0] for l in NAT if "swg-smartdns " in l + " ") == ["tcp", "udp"]
      and all(("127.0.0.1:%d" % N.SMART_DNS_PORT) in l for l in NAT if "swg-smartdns " in l + " ")
      and NAT[0].count("swg-smartdns-net") == 1, NAT)

# s10-p3 F4: a PARTIAL arrival (another node's smart rule sends this one some destinations; the SOCKS exit is its default) —
# no stand-in addresses for it, and its DNS out the main table by one ip rule above the band
RULES = []
_r4 = N.run
def _ipr(argv, **k):
    if argv[:3] == ["ip", "rule", "show"]:
        return R("\n".join(["0:\tfrom all lookup local"] + RULES + ["32766:\tfrom all lookup main"]))
    if argv[:4] == ["ip", "rule", "del", "pref"]:
        for i, l in enumerate(RULES):
            if l.startswith(argv[4] + ":"):
                RULES.pop(i); return R()
        return R(rc=2)
    if argv[:3] == ["ip", "rule", "add"]:            # as iproute2 prints it: a /32 bare, the protocol by name
        S = argv[4][:-3] if argv[4].endswith("/32") else argv[4]
        RULES.append("%s:\tfrom %s ipproto udp dport 53 lookup main" % (argv[-1], S)); return R()
    return _r4(argv, **k)
N.run = _ipr
N._EXITS["socks"] = {"s5x-aa": False}; N._S5X_NFT.update(sig=None, dns=None, arr=None); NAT[:] = []
DX4 = [{"subnet": "10.17.0.0/24", "dev": "s5x-aa", "table": 7001},
       {"subnet": "10.40.0.0/24", "dev": "s5x-aa", "table": 7001, "part": True},
       {"subnet": "10.255.0.9", "dev": "s5x-aa", "table": 7001, "part": True}]
N._s5x_rules(DX4, [], {"changed": 0, "errors": []})
dnat = [l for l in NAT if "swg-s5x-dns " in l + " " and "DNAT" in l]
check("a partial arrival's DNS gets no stand-in addresses: only the node's own interface goes to mapdns — s10-p3 F4",
      sorted(l.split("-s ")[1].split()[0] for l in dnat) == ["10.17.0.0/24"], NAT)
check("…its UDP 53 leaves by the main table, above the band: `from S ipproto udp dport 53 lookup main` at 6870, a bare hop-2 address too",
      sorted(l.split("from ")[1].split()[0] for l in RULES) == ["10.255.0.9", "10.40.0.0/24"]
      and all(l.startswith("6870:") and "ipproto udp dport 53 lookup main" in l for l in RULES), RULES)
_rules0, _c4 = list(RULES), {"changed": 0, "errors": []}
N._s5x_rules(DX4, [], _c4)
check("…and a second pass with nothing changed rewrites none of it (a /32 read back bare)", RULES == _rules0 and _c4["changed"] == 0,
      (RULES, _c4))
# review F4: a subnet that ALSO arrives whole on this device never gets the bypass, even with the device down (its kill-switch)
N._EXIT_HEALTH["s5x-aa"] = {"dead": True, "fail_since": 0, "fails": 9, "ok_since": None, "since": 0, "why": "x"}
N._s5x_rules(DX4 + [{"subnet": "10.40.0.0/24", "dev": "s5x-aa", "table": 7001}], [], {"changed": 0, "errors": []})
check("a subnet that also arrives whole gets no bypass — not even while the device is dead (its kill-switch holds it) — review F4",
      sorted(l.split("from ")[1].split()[0] for l in RULES) == ["10.255.0.9"], RULES)
N._EXIT_HEALTH.clear()
N._EXITS["socks"] = {}
N._s5x_rules([], [], {"changed": 0, "errors": []})
check("…gone with the exit", RULES == [], RULES)
# review F1/F2: a kernel that refuses `ipproto`/`dport` — the subnet keeps mapdns, said, and not retried every pass
_r12 = N.run
N.run = lambda argv, **k: (R(rc=2, err="Error: argument \"ipproto\" is wrong") if argv[:3] == ["ip", "rule", "add"] else _ipr(argv, **k))
N._EXITS["socks"] = {"s5x-aa": True}; N._S5X_NFT.update(sig=None, dns=None, arr=None, arr_bad=None); NAT[:] = []
_c12 = {"changed": 0, "errors": []}
N._s5x_rules(DX4, [], _c12)
dnat = [l for l in NAT if "swg-s5x-dns " in l + " " and "DNAT" in l]
check("a bypass the kernel refuses: that subnet keeps mapdns (its DNS answered, as before this existed), and it is said — review F1",
      sorted(l.split("-s ")[1].split()[0] for l in dnat) == ["10.17.0.0/24", "10.255.0.9/32", "10.40.0.0/24"]
      and any("not installed" in e for e in _c12["errors"]), (NAT, _c12))
_seen12 = []
N.run = lambda argv, **k: (_seen12.append(argv), R(rc=2) if argv[:3] == ["ip", "rule", "add"] else _ipr(argv, **k))[1]
_c12b = {"changed": 0, "errors": []}
N._s5x_rules(DX4, [], _c12b)
check("…and the next pass neither retries the adds nor counts a change (still said) — review F2",
      not [a_ for a_ in _seen12 if a_[:2] == ["ip", "rule"]] and _c12b["changed"] == 0 and _c12b["errors"], (_seen12, _c12b))
N.run = _r4
# the golden's promise: a node with NO SOCKS exit never reads the rule list — not even on its first pass
_seen0 = []
N.run = lambda argv, **k: (_seen0.append(argv), R())[1]
N._EXITS["socks"] = {}; N._S5X_NFT.update(arr=None, arr_bad=None)
N._s5x_arr_dns([], {"changed": 0, "errors": []}, False)
check("⚠️ no SOCKS exit: the bypass costs no fork even on a process's first pass (p2p_iface's byte-identical golden)", _seen0 == [], _seen0)
N.run = _r4

# ── [6] F18 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] an unknown kind takes the device it replaced down (s9a F18)")
downs = []
N._exit_down = lambda dev, rec: (downs.append(dev), True)[1]
N._dev_link_state = lambda d: "up" if d == "wgx-cafebabe" else "absent"
json.dump({"provider": "warp", "priv": "k", "device": "wgx-cafebabe"}, open(os.path.join(N.EXIT_DIR, "cafebabe.json"), "w"))
res = {"changed": 0, "errors": []}
N._exit_probe_all = lambda devs: {}
N.reconcile_exits([{"id": "cafebabe", "device": "wgx-cafebabe", "provider": "vless9"}], res)
row = next((x for x in N._EXITS["list"] if x["id"] == "cafebabe"), {})
check("the old kind's device comes down", downs == ["wgx-cafebabe"], downs)
check("…the row says the node does not know the kind", "does not know" in str(row.get("error")), row)
check("…and the record stays for a node that does", os.path.exists(os.path.join(N.EXIT_DIR, "cafebabe.json")))
downs.clear()
json.dump({"provider": "socks5", "device": "s5x-cafebabe", "started": "x hev-2.18.0"}, open(os.path.join(N.EXIT_DIR, "cafebabe.json"), "w"))
N._dev_link_state = lambda d: "absent"
N.reconcile_exits([{"id": "cafebabe", "device": "s5x-cafebabe", "provider": "vless9"}], res)
N.reconcile_exits([{"id": "cafebabe", "device": "s5x-cafebabe", "provider": "vless9"}], res)
check("a SOCKS record under an unknown kind is stopped ONCE, not every pass — F36", downs == ["s5x-cafebabe"], downs)

# ── [7] the exit in the pass ────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[7] a SOCKS exit in reconcile_exits")
os.unlink(os.path.join(N.EXIT_DIR, "cafebabe.json"))
_hs, _probed, _checks = [], [], []
N._exit_handshake = lambda rec, dev: (_hs.append(dev), 0)[1]
N.hev_binary = lambda: ("/bin/hev", "")
N._s5x_ensure_unit = lambda *a: ""
_link7 = {"v": "up"}
N._dev_link_state = lambda d: _link7["v"]
BADTR = {"err": "TimeoutError: timed out"}
_reach7 = {"v": False}
def probe_all(devs):
    out = {}
    for d, rec in devs:
        _probed.append((d, rec.get("mapdns")))
        out[d] = (dict(BADTR), _reach7["v"], None)
    return out
N._exit_probe_all = probe_all
def _ck7(*a, **k):
    _checks.append(a[:3]); time.sleep(1.0)
    return {"login": False, "egress_ip": "", "loc": "", "udp": None, "rtt_ms": None, "why": "auth_failed"}
N._socks_check = _ck7
N.EXIT_DEAD_AFTER_S, N.EXIT_DEAD_MIN_PROBES = 0, 2
N._EXIT_HEALTH.clear(); N._EXIT_PROBED_AT.clear(); N._S5X.clear(); N._S5X_CHECKS.clear(); N._S5X_INFLIGHT.clear()
WANT = [{"id": "5a5a5a5a", "device": "s5x-5a5a5a5a", "provider": "socks5", "cfg_sig": "c0ffee000001",
         "socks": {"host": "198.51.100.5", "port": 1080, "user": "u", "pass": "secret"}}]
DEV7 = "s5x-5a5a5a5a"
res = {"changed": 0, "errors": []}
t0 = time.monotonic(); N.reconcile_exits(WANT, res); dt = time.monotonic() - t0
row = next((x for x in N._EXITS["list"] if x["id"] == "5a5a5a5a"), {})
check("bring-up dispatches the proxy check in a thread of its own: the pass does not wait for it (%.2f s) — F15" % dt,
      dt < 0.8 and DEV7 in N._S5X_INFLIGHT, dt)
check("…its trace asks hev's mapdns, so hev CONNECTs BY NAME as its clients do — F9", _probed[:1] == [(DEV7, N.S5X_DNS)], _probed)
check("the row reports the proxy's UDP flag — never the password", "udp_ok" in row and "secret" not in json.dumps(row), row)
check("…no WireGuard handshake is asked for a TUN (no `wg show` fork per pass)", _hs == [] and row.get("handshake") is None, _hs)
check("…the proxy is the endpoint pinged (Latency)", row.get("endpoint") == "198.51.100.5:1080", row.get("endpoint"))
N.reconcile_exits(WANT, res)
check("while one check runs, no second one is started — F23", len(_checks) == 1, _checks)
for _ in range(30):
    if DEV7 not in N._S5X_INFLIGHT:
        break
    time.sleep(0.1)
N.reconcile_exits(WANT, res)
row = next((x for x in N._EXITS["list"] if x["id"] == "5a5a5a5a"), {})
st = N._EXIT_HEALTH.get(DEV7) or {}
check("its answer is taken on a later pass and shown on the row", (row.get("check") or {}).get("why") == "auth_failed", row.get("check"))
check("dead: the verdict carries the proxy's own reason, not a bare timeout", st.get("dead") and "login" in st.get("why", ""), st)
check("the yml it runs is 0600 and holds the password (and nothing else does)",
      oct(os.stat(os.path.join(N.EXIT_DIR, "s5x-5a5a5a5a.yml")).st_mode & 0o777) == "0o600"
      and "secret" not in open(os.path.join(N.EXIT_DIR, "5a5a5a5a.json")).read())
# F8: hev restarts (its TUN gone a pass): the dead verdict stays, only the recovery is proven again
_link7["v"] = "absent"; N.reconcile_exits(WANT, res); _link7["v"] = "up"
check("hev restarting (its TUN gone a pass) keeps the dead verdict: no route back into a dead proxy — F8",
      (N._EXIT_HEALTH.get(DEV7) or {}).get("dead") is True, N._EXIT_HEALTH.get(DEV7))
# F24: a probe that cannot bind (reach None) but whose trace failed with a reason waits its minute, not every pass
N._EXIT_HEALTH.clear(); N._EXIT_PROBED_AT.clear(); _reach7["v"] = None; _probed.clear()
N._S5X[DEV7].update(next=time.time() + 600, check={"why": "", "at": 1})
N.reconcile_exits(WANT, res); N.reconcile_exits(WANT, res)
check("a probe that cannot bind is a standing condition: probed once a minute, not every pass — F24", len(_probed) == 1, _probed)
_reach7["v"] = False
# healthy: probed at most every minute
_probed.clear()
BADTR.clear(); BADTR.update(ip="203.0.113.9")
N._EXIT_HEALTH.clear(); N._EXIT_PROBED_AT.clear()
N.reconcile_exits(WANT, res)
N.reconcile_exits(WANT, res)
check("carrying, it is probed once a minute, not every pass (T3: a metered proxy)", len(_probed) == 1, _probed)
# F13: the binary still being fetched is progress, not a fault
N.hev_binary = lambda: ("", "fetching the SOCKS5 tunnel program…")
_link7["v"] = "absent"
res13 = {"changed": 0, "errors": []}
N.reconcile_exits([dict(WANT[0], cfg_sig="c0ffee000002")], res13)
row = next((x for x in N._EXITS["list"] if x["id"] == "5a5a5a5a"), {})
check("the tunnel program being fetched reads as setup, never as an error (the row is busy, not red) — F13",
      row.get("setup") and not row.get("error") and not any("fetching" in e for e in res13["errors"]), (row, res13))
_link7["v"] = "up"

# ── [8] T14 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[8] the TUN is not an operator's device")
check("`s5x` is skipped like every tunnel of ours (no picker row, no node IP)", any("s5x-aa".startswith(p) for p in N._NODE_ADDR_SKIP))
check("the node reports the kinds it can make, socks5 among them", "socks5" in N.EXIT_KINDS
      and 'snap["exit_kinds"] = list(EXIT_KINDS)' in open(NODED, encoding="utf-8").read())

print()
if os.environ.get("S5X_PLANT_SETE"):
    print(("perturbed (--perturb-sete): CAUGHT (%d red)" % len(FAILS)) if FAILS else "perturbed (--perturb-sete): NOTHING FAILED")
    sys.exit(0 if FAILS else 1)
if MODE:
    print(("perturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS))) if FAILS
          else "perturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(0 if FAILS else 1)
print(("FAILED: " + "; ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
