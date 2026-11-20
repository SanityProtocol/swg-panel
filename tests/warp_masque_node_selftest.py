#!/usr/bin/env python3
"""Self-test — THE MASQUE EXIT and WARP re-enrolment, the node's half (1.8.12 item 17b P2, docs/WARP-MASQUE-PLAN.md §4, §6).

A `warp-masque` exit is a WARP account presented over MASQUE by usque `nativetun` as the TUN `wgx-<id>`; the same account can
switch between WireGuard and MASQUE in place; the escrow and the restore cover both kinds; and a WARP exit of either kind
that stays dead re-enrols its own key. Each on the real swg-noded with only its effects stubbed (run(), the links, the units,
Cloudflare's /reg — a fake in this file):

  [1] P-256 — NIST/RFC 6979 known answers, the SEC1 (curve OID inside: usque parses it with none given) and PKIX templates,
      an `openssl ec` round trip
  [2] the binary — usque from the pin's own release (owner, tag, sha256, asset), refused on an arch with no build
  [3] the unit — swg-mqx-<id> in the hev sandbox with Restart=always (usque exits 0 on a bad config, T4), the proxy
      variables unset (T9), the argv of §4.5, --http2 by transport; the conf usque's JSON, sorted, 0600, written twice
      byte-identical with no restart; an incomplete record never started; docker — a child without a proxy in its env
  [4] teardown (T12, T28) — `_exit_down` on a MASQUE TUN stops its unit and never runs wg-quick; a pause and a reap stop a
      unit that has no device; the start sweep stops one nothing wants
  [5] the freeze check (T1, T30) — 64 KB through a local TLS server: pass, a stall = freeze, a 403 = no answer, nothing
      connected = no answer; the sticky verdict judges a failing probe dead with its reason even when reach answers
  [6] the kick — dead 180 s → restart, then ×2 up to 30 min, reset when the verdict clears
  [7] registration and the switch (T6, T19, T21) — a MASQUE exit POSTs once and PATCHes its key; a failed PATCH is retried
      alone; WireGuard ↔ MASQUE keeps account_id and token; the old device goes by the OLD kind; a refused PATCH leaves the
      old one carrying on the same device and says why; WireGuard's endpoint is the answer's `host` (P0 #8); 1001 → a fresh
      key once
  [8] restore (§4.11, T24, T29) — the blob's own kind, its account enrolled for the exit's current kind; a failed same-kind
      PATCH installs it as it is (R3); a failed cross-kind one keeps the running exit and says why; applied once
  [9] re-enrolment (§4.12) — both kinds, only after 15 min dead, only when the network is not to blame (a fresh WireGuard
      handshake, a MASQUE freeze), 6 h after an answer that changed nothing, one per node per 5 min; a refused account
      (JSON 1012/1006) stops; a carrying exit costs no handshake read
  [10] escrow — both kinds sealed, `acct` in the clear and the same across a key change (T22)
  [11] the rows — a MASQUE row: no peer key, no handshake, its `colo` and freeze verdict; a WireGuard row unchanged (no colo)

Hermetic: run() is stubbed and its argv inspected; Cloudflare is a dict; the TLS servers are threads on 127.0.0.1.

Run: python3 tests/warp_masque_node_selftest.py           (0 = pass)
     --perturb-<name>   plants one regression (see PLANTS) and expects RED
"""
import base64, hashlib, importlib.machinery, importlib.util, json, os, socket, ssl, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

PLANTS = {
    "--perturb-oid": ('oid = bytes.fromhex("06082a8648ce3d030107")', 'oid = bytes.fromhex("06082a8648ce3d030108")'),          # [1]
    "--perturb-arch": ('    if arch not in USQ_SHA256:\n        return "", "no usque build', '    if False:\n        return "", "no usque build'),  # [2]
    "--perturb-restart": ('what="MASQUE tunnel", restart="always",', 'what="MASQUE tunnel", restart="on-failure",'),       # [3]
    "--perturb-unsetenv": ('extra=["-p", "UnsetEnvironment=HTTP_PROXY', 'extra=["-p", "X-Nothing=HTTP_PROXY'),               # [3]
    "--perturb-env": ("cmd=[binp] + argv, env=_mqx_env(),", "cmd=[binp] + argv, env=None,"),                                 # [3]
    "--perturb-churn": ("json.dumps([USQ_TAG, argv, text]).encode()", "json.dumps([USQ_TAG, argv, text, time.time()]).encode()"),  # [3]
    "--perturb-incomplete": ('        return "the MASQUE settings are incomplete", ""', '        pass'),                         # [3]
    "--perturb-wgdown": ('    if (rec or {}).get("provider") == "warp-masque":\n        _mqx_down(',
                         '    if False:\n        _mqx_down('),                                                                    # [4]
    "--perturb-pauselink": ('                if not _exit_is_wg(rec.get("provider")) and rec.get("started"):',
                            '                if rec.get("provider") == "socks5" and rec.get("started"):'),                   # [4]
    "--perturb-reaplink": ('if od and (_dev_link_state(od) != "absent" or not _exit_is_wg(old.get("provider"))):',
                           'if od and (_dev_link_state(od) != "absent" or old.get("provider") == "socks5"):'),               # [4]
    "--perturb-sweep": ('        _s5x_sweep(want, "mqx")', '        pass'),                                                      # [4]
    "--perturb-403": ('                        return None                   # an HTTP refusal: no answer (§4.7)', '                        return "freeze"'),  # [5]
    "--perturb-onpass": ('        return dict(rec, mqx="onpass" if time.time() - fz_at >= 60 else "")', '        return dict(rec, mqx="")'),  # [5]
    "--perturb-namelater": ('                    _hl["why"] = MQX_FREEZE_WHY          # named once a run proves it, even after the exit went dead',
                            '                    pass'),                                                         # [5]
    "--perturb-fzthread": ('threading.Thread(target=_mqx_freeze_run, args=(dev, _me), daemon=True).start()', '_mqx_freeze_run(dev, _me)'),  # [5]
    "--perturb-fzonce": ('    if dev in _MQX_FZ_RUN or dev in _MQX_FZ:\n        return dict(rec, mqx="")', '    if False:\n        return dict(rec, mqx="")'),  # [5]
    "--perturb-fzstale": ('        if _MQX_FZ_RUN.get(dev) is me:\n            if ok:', '        if True:\n            if ok:'),       # [5]
    "--perturb-fzdrop": ('for m in (_EXIT_HEALTH, _EXIT_PROBED_AT, _MQX, _MQX_FZ, _MQX_FZ_RUN):', 'for m in (_EXIT_HEALTH, _EXIT_PROBED_AT, _MQX, _MQX_FZ):'),  # [5]
    "--perturb-log1": ('    for lg in (dev + ".log", dev + ".log.1"):', '    for lg in (dev + ".log",):'),                     # [4]
    "--perturb-keyedsent": ('                    _keyed = rec is not _r0              # a request went out', '                    _keyed = True              # a request went out'),  # [9]
    "--perturb-noevidence": ('    if m.get("freeze") == "freeze" and tr and not tr.get("ip"):',
                             '    if m.get("freeze") == "freeze" and not (tr or {}).get("ip"):'),                                # [5]
    "--perturb-sticky": ('        tr, rch = dict(tr or {}, err=MQX_FREEZE_WHY), False', '        tr = dict(tr or {}, err=MQX_FREEZE_WHY)'),  # [5]
    "--perturb-kick": ("min(MQX_KICK_MAX_S, MQX_KICK_AFTER_S * 2 ** n)", "MQX_KICK_AFTER_S"),
    "--perturb-kickok": ('    if hl.get("ok_since") is not None:\n        return False', '    if False:\n        return False'),       # [6]
    "--perturb-kickdeath": ('        if p:                                 # … as a deliberate stop', '        if False:  # … as a deliberate stop'),  # [6]                                 # [6]
    "--perturb-post": ('    if not rec.get("account_id"):\n        reg, why = _warp_register()', '    if True:\n        reg, why = _warp_register()'),  # [7]
    "--perturb-acctonly": ('                acct = {k: v for k, v in reg.items() if k not in ("priv", "pub", "peer_key", "endpoint", "address")}',
                           '                acct = reg'),                                                                      # [7]
    "--perturb-firstdown": ('                rec, _sw, _rin[xid] = _warp_keyed(xid, dev, prov, rec, sp, res)',
                            '                _exit_down(dev, dict(rec, id=xid)); rec, _sw, _rin[xid] = _warp_keyed(xid, dev, prov, rec, sp, res)'),  # [7]
    "--perturb-newkind": ('        if rec.get("priv") and (rec.get("provider") or "warp") != prov:\n            _exit_down(dev, dict(rec, id=xid))',
                          '        if rec.get("priv") and (rec.get("provider") or "warp") != prov:\n            _exit_down(dev, dict(new, id=xid))'),  # [7]
    "--perturb-switchwait": ('                if _ub[0]:\n                    _r0 = rec', '                if True:\n                    _r0 = rec'),  # [7]
    "--perturb-transport": ('                if _wkind == "warp-masque":\n                    rec["transport"]',
                            '                if True:\n                    rec["transport"]'),                                   # [7]
    "--perturb-host": ('        endpoint = ep.get("host") or ep.get("v4") or ""', '        endpoint = ep.get("v4") or ep.get("host") or ""'),  # [7]
    "--perturb-1001": ("        if code == 1001 and not _try:", "        if False:"),                                        # [7]
    "--perturb-restorewarp": ('    bk, bpub = str(blob.get("provider") or "warp"), str(blob.get("pub") or "")',
                              '    bk, bpub = "warp", str(blob.get("pub") or "")'),                                         # [8]
    "--perturb-restoreonce": ('    if relay and relay == rec.get("restore_ref"):\n        return rec, str(', '    if False:\n        return rec, str('),  # [8]
    "--perturb-relay": ('    if relay and relay == rec.get("restore_ref"):', '    if rec.get("restore_ref"):'),                         # [8]
    "--perturb-usqwait": ('    if not _ub[0]:\n        return rec, "waits for the MASQUE', '    if False:\n        return rec, "waits for the MASQUE'),  # [8]
    "--perturb-keyedpass": ('if not (_blob_err or _keyed) and rec.get("priv")', 'if not _blob_err and rec.get("priv")'),           # [8]
    "--perturb-restorepersist": ("                            _replace_if_changed(sp, json.dumps(rec), 0o600)   # `restored`: one press, one PATCH (T29)",
                                 "                            pass"),                                                 # [8]
    "--perturb-giveup": ('                    for _k in ("reg_fails", "reg_next", "reg_error"):\n                        rec.pop(_k, None)',
                         '                    for _k in ():\n                        rec.pop(_k, None)'),                    # [7]
    "--perturb-asis": ('    if new is None and (ref or (bk != prov and rec.get("priv"))):', '    if new is None:'),         # [8]
    "--perturb-wgnet": ("    return hs is not None and (hs == 0 or hs > EXIT_SESSION_DEAD_S)", "    return hs is not None"),  # [9]
    "--perturb-mqnet": ('        return (_MQX.get(dev) or {}).get("freeze") != "freeze"', '        return True'),               # [9]
    "--perturb-900": ('now - st["since"] >= WARP_REENROL_AFTER_S) or st', 'now - st["since"] >= 0) or st'),
    "--perturb-reenok": ('WARP_REENROL_AFTER_S) or st.get("ok_since") is not None:', 'WARP_REENROL_AFTER_S):'),                 # [9]
    "--perturb-reenprobe": (' and dev not in _reen]', ']'),                                                                     # [9]
    "--perturb-licrefused": ('lic != rec.get("licence_applied") and not rec.get("refused"):', 'lic != rec.get("licence_applied"):'),  # [9]                             # [9]
    "--perturb-6h": ("    return dict(rec, reenrol_next=time.time() + WARP_REENROL_BACKOFF_S)", "    return dict(rec, reenrol_next=0)"),  # [9]
    "--perturb-spacing": (' or now - _WARP_REENROL["at"] < WARP_REENROL_SPACING_S:', ':'),                                   # [9]
    "--perturb-401": ("        if code in (1012, 1006):\n            return None, False, WARP_REFUSED, True",
                      "        if False:\n            return None, False, WARP_REFUSED, True"),                               # [9]
    "--perturb-fork": ('    now = time.time() if now is None else now\n    st = _EXIT_HEALTH.get(dev)\n    if not (st and st.get("dead")',
                       '    now = time.time() if now is None else now\n    _exit_handshake(rec, dev)\n    st = _EXIT_HEALTH.get(dev)\n    if not (st and st.get("dead")'),  # [9]
    "--perturb-acct": ("dict(ivk_seal(_IVK_VAULT_PUB, plaintext), **(got[2] if len(got) > 2 else {}))", "dict(ivk_seal(_IVK_VAULT_PUB, plaintext))"),  # [10]
    "--perturb-underlay": ('_ul = _exit_underlay(rec, dev, _hs) if _live and _exit_is_wg(prov)',
                           '_ul = _exit_underlay(rec, dev, _hs) if _live and prov != "socks5"'),                               # [11]
    "--perturb-mqlog": ('n.startswith(("s5x-", "wgx-"))', 'n.startswith("s5x-")'),                                            # [11]
    "--perturb-py37": ("pow(2 * a[1], P - 2, P)", "pow(2 * a[1], -1, P)"),                                                     # [1]
    "--perturb-colo": ('_exit_trace(dev, colo=True) if "mqx" in rec\n              else _exit_trace(dev))',
                       '_exit_trace(dev, colo=True) if "mqx" in rec\n              else _exit_trace(dev, colo=True))'),     # [11]
    "--perturb-pem": ('"peer_key": rec.get("peer_key", "") if prov != "warp-masque" else "",', '"peer_key": rec.get("peer_key", ""),'),  # [11]
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
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
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k)
TMP = tempfile.mkdtemp(prefix="mqx-node-")
if MODE:
    _src = open(NODED, encoding="utf-8").read()
    _cut, _new = PLANTS[MODE]
    assert _src.count(_cut) == 1, "perturbation anchor for %s is missing or not unique — would FALSE-PASS" % MODE
    _tmp = os.path.join(TMP, "noded-perturbed.py")
    open(_tmp, "w", encoding="utf-8").write(_src.replace(_cut, _new, 1))
    N = _load(_tmp, "swgnoded")
else:
    N = _load(NODED, "swgnoded")
LOGS = []
N.log = lambda lvl, fmt, *a: LOGS.append(fmt % a if a else fmt)
N.STATE_DIR = os.path.join(TMP, "state")
N.EXIT_DIR = os.path.join(TMP, "state", "exits")
os.makedirs(N.EXIT_DIR)
N.NODE_KIND = "baremetal"


class R:
    def __init__(s, out="", rc=0, err=""):
        s.stdout, s.stderr, s.returncode = out, err, rc


# ── the world: links, units, run() ─────────────────────────────────────────────────────────────────────────────────────────
LINK, UNITS, CALLS = {}, {}, []
_kc = [0]


def _run(argv, **k):
    argv = list(argv)
    CALLS.append(argv)
    if "genkey" in argv:
        _kc[0] += 1
        return R(base64.b64encode(("wgpriv-%04d" % _kc[0]).encode().ljust(32, b"x")).decode() + "\n")
    if "pubkey" in argv:
        return R("PUB" + hashlib.sha256((k.get("input_text") or "").encode()).hexdigest()[:40] + "\n")
    if argv[:2] == ["systemctl", "--version"]:
        return R("systemd 255 (255.4)")
    if argv[:2] == ["systemctl", "show"]:
        u = UNITS.get(argv[-1])
        return R("LoadState=loaded\nActiveState=active\nSubState=running\nDescription=%s" % u if u else "LoadState=not-found\n")
    if argv[:2] == ["systemctl", "stop"]:
        u = argv[2]
        if u in UNITS:
            UNITS.pop(u)
            LINK["wgx-" + u.rsplit("-", 1)[1]] = "absent"
        return R()
    if argv[0] == "systemd-run":
        unit = next(a for a in argv if a.startswith("--unit="))[7:]
        UNITS[unit] = next(a for a in argv if a.startswith("--description="))[len("--description="):]
        if unit.startswith("swg-mqx-"):
            LINK["wgx-" + unit[8:]] = "up"
        return R()
    if argv[:3] == ["ip", "link", "del"]:
        LINK[argv[3]] = "absent"
        return R()
    if len(argv) >= 3 and argv[0] in ("wg-quick", "awg-quick") and argv[1] == "down":
        LINK[os.path.basename(argv[2])[:-5]] = "absent"
        return R()
    return R()


N.run = _run
N._dev_link_state = lambda dev: LINK.get(dev, "absent")
N._link_kind = lambda dev: "wg" if LINK.get(dev) == "up" else ""
UPS = []
def _scoped_up(tool, conf):
    UPS.append((tool, conf)); LINK[os.path.basename(conf)[:-5]] = "up"; return R()
N._scoped_up = _scoped_up
TR = {}
def _trace(dev, mapdns=None, colo=False):
    t = dict(TR.get(dev) or {"ip": "198.51.100.7", "warp": "on", "loc": "RU"})
    if colo and t.get("ip"):
        t["colo"] = "DME"
    return t
N._exit_trace = _trace
N._exit_reach = lambda dev, *a, **k: True
N._exit_ping = lambda ep, *a, **k: 5
FZ = {"v": "pass"}
N._mqx_freeze = lambda dev, *a, **k: FZ["v"]
N.usq_binary = lambda: ("/opt/usque", "")

# ── a fake Cloudflare /reg ──────────────────────────────────────────────────────────────────────────────────────────────────
PEM = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEmasque\n-----END PUBLIC KEY-----\n"
CF = {"accts": {}, "calls": [], "fail": [], "mq_peer": PEM, "wg_peer": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="}


def _answer(kind, aid):
    mq = kind == "masque"
    return {"id": aid, "config": {"interface": {"addresses": {"v4": "172.16.0.2", "v6": "2606::1"}},
            "peers": [{"public_key": CF["mq_peer"] if mq else CF["wg_peer"],
                       "endpoint": ({"v4": "162.159.198.1:0", "v6": "[2606:4700:103::1]:0"} if mq else
                                    {"host": "engage.cloudflareclient.com:2408", "v4": "8.6.112.0:0"})}]},
            "account": {"license": "LIC", "account_type": "free"}}


def _cf(path, data, method, token=""):
    CF["calls"].append((method, path, dict(data or {}), token))
    if CF["fail"]:
        return CF["fail"].pop(0)
    if method == "POST" and path == "/reg":
        aid = "acct-%d" % (len(CF["accts"]) + 1)
        CF["accts"][aid] = {"token": "tok-" + aid, "key": data["key"]}
        return 200, dict(_answer("wireguard", aid), token="tok-" + aid)
    if method == "PATCH" and path.startswith("/reg/"):
        a = CF["accts"].get(path[5:])
        if a is None:
            return 404, {"success": False, "errors": [{"code": 1006, "message": "Registration not found"}]}
        if token != a["token"]:
            return 401, {"success": False, "errors": [{"code": 1012, "message": "Not authorized"}]}
        a["key"] = data["key"]
        return 200, _answer(data["tunnel_type"], path[5:])
    if method == "PUT":
        return 200, {"account_type": "unlimited"}
    return 404, "nope"


N._warp_api = _cf
N._WARP_REENROL["at"] = 0.0


def posts():
    return sum(1 for c in CF["calls"] if c[0] == "POST")


def patches():
    return [c for c in CF["calls"] if c[0] == "PATCH"]


def rec_of(xid):
    with open(os.path.join(N.EXIT_DIR, xid + ".json")) as f:
        return json.load(f)


def save_rec(xid, rec):
    with open(os.path.join(N.EXIT_DIR, xid + ".json"), "w") as f:
        json.dump(rec, f)


def sync(*exits):
    res = {"errors": [], "changed": 0}
    N.reconcile_exits([dict(e, device=e.get("device") or "wgx-" + e["id"]) for e in exits], res)
    return {x["id"]: x for x in N._EXITS["list"]}, res


def fzwait():
    """The freeze run is its own thread (review F14): wait for it, as a later pass would."""
    for _ in range(500):
        if not N._MQX_FZ_RUN:
            return
        time.sleep(0.01)


def reset():
    LINK.clear(); UNITS.clear(); CALLS.clear(); UPS.clear(); CF["calls"].clear(); CF["fail"].clear(); TR.clear()
    for m in (N._EXIT_HEALTH, N._MQX, N._MQX_FZ, N._EXIT_PROBED_AT, N._S5X_PROCS):
        m.clear()
    N._S5X_SEEN.clear()
    N._WARP_REENROL["at"] = 0.0
    for fn in os.listdir(N.EXIT_DIR):
        os.unlink(os.path.join(N.EXIT_DIR, fn))


# ── [1] P-256 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] P-256: known answers, the DER templates usque reads, an openssl round trip")
check("d = 1 → G", N._p256_mul(1) == N._P256_G)
check("d = n − 1 → −G", N._p256_mul(N._P256_N - 1) == (N._P256_G[0], N._P256_P - N._P256_G[1]))
check("d·n = the point at infinity", N._p256_mul(N._P256_N) is None)
_d = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721           # RFC 6979 A.2.5
check("RFC 6979 A.2.5's key pair", N._p256_mul(_d) == (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
                                                      0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299))
priv, pub = N._p256_keypair(_d)
sec1, pkix = base64.b64decode(priv), base64.b64decode(pub)
check("SEC1 DER: 121 bytes, the scalar, the curve OID inside (usque parses it with none given)",
      len(sec1) == 121 and sec1[7:39] == _d.to_bytes(32, "big") and bytes.fromhex("2a8648ce3d030107") in sec1, sec1.hex())
check("PKIX DER: 91 bytes, id-ecPublicKey + prime256v1, the uncompressed point", len(pkix) == 91 and pkix[-65:] == sec1[-65:])
_kd = tempfile.mkdtemp(dir=TMP)
open(os.path.join(_kd, "k.der"), "wb").write(sec1)
_o = subprocess.run(["openssl", "ec", "-inform", "DER", "-in", os.path.join(_kd, "k.der"), "-pubout", "-outform", "DER"],
                    capture_output=True)
check("openssl reads the private key and derives the same public key", _o.returncode == 0 and _o.stdout == pkix,
      (_o.returncode, _o.stderr[-200:]))
_o2 = subprocess.run(["openssl", "ec", "-inform", "DER", "-in", os.path.join(_kd, "k.der"), "-check", "-noout"], capture_output=True)
check("…and finds it a valid P-256 key", _o2.returncode == 0, _o2.stderr[-200:])
_ps = open(N.__file__, encoding="utf-8").read()
_ps = _ps[_ps.index("def _p256_mul"):_ps.index("def _p256_keypair")]
check("inverses by Fermat: no pow(x, -1, P), which the Python 3.7 a node may run refuses (review F9)", ", -1, P) %" not in _ps)
_r1, _r2 = N._p256_keypair(), N._p256_keypair()
check("a fresh key each time", _r1 != _r2 and len(base64.b64decode(_r1[1])) == 91)

# ── [2] the binary ──────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the binary: the pinned usque")
_N2 = _load(_tmp if MODE else NODED, "swgnoded2")
_N2.log = lambda *a, **k: None
_N2.STATE_DIR = os.path.join(TMP, "state2")
_seen, _gate = [], threading.Event()
_N2._pin_fetch = lambda owner, tag, want, asset, arch, dest: (_gate.wait(5), _seen.append((owner, tag, want, asset, dest)), "nope")[2]
_N2._turn_arch = lambda: "amd64"
p, why = _N2.usq_binary()
_gate.set()
for _ in range(50):
    if _N2._USQ["thread"] and not _N2._USQ["thread"].is_alive():
        break
    time.sleep(0.05)
check("fetched in the background, saying so (fixed words)", p == "" and why == _N2.MQX_BUSY, why)
check("…from the pin: owner, tag, the amd64 sha256, asset usque-linux-amd64, its own directory per tag",
      _seen[:1] == [(_N2.USQ_OWNER, _N2.USQ_TAG, _N2.USQ_SHA256["amd64"], "usque-linux-amd64",
                     os.path.join(_N2.STATE_DIR, "usque", _N2.USQ_TAG, "usque"))], _seen)
_N2._turn_arch = lambda: "riscv64"
try:
    p, why = _N2.usq_binary()
except Exception as e:                              # a refusal that raises is no refusal
    p, why = "", "raised %r" % e
check("an arch with no build is refused, never fetched", p == "" and "no usque build" in why and len(_seen) == 1, (why, _seen))
check("hev keeps its own fetcher state (no shared stamp)", _N2._HEV is not _N2._USQ)

# ── [3] the unit ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] the unit (bare metal), the conf, the child (docker)")
reset()
MREC = {"provider": "warp-masque", "priv": priv, "pub": pub, "peer_key": PEM, "endpoint": "162.159.198.1:443",
        "address": "172.16.0.2", "account_id": "acct-x", "token": "tok-x"}
r = dict(MREC)
e, setup = N._mqx_up("aabbccdd", "wgx-aabbccdd", r, "h3")
_start = next((c for c in CALLS if c[0] == "systemd-run"), [])
conf = os.path.join(N.EXIT_DIR, "wgx-aabbccdd.conf")
check("started as swg-mqx-<id> in swg-exit.slice", e == "" and "--unit=swg-mqx-aabbccdd" in _start and "--slice=swg-exit.slice" in _start, (e, _start))
check("…Restart=always (usque exits 0 on a bad config, T4), with the back-off", "Restart=always" in _start and "RestartSteps=8" in _start, _start)
check("…in hev's sandbox: CAP_NET_ADMIN only, /dev/net/tun, ProtectSystem=strict",
      all(x in _start for x in ("CapabilityBoundingSet=CAP_NET_ADMIN", "DeviceAllow=/dev/net/tun rw", "ProtectSystem=strict",
                                "NoNewPrivileges=yes")), _start)
check("…the proxy variables unset (T9)", any(x.startswith("UnsetEnvironment=") and "HTTPS_PROXY" in x for x in _start), _start)
check("…the argv of §4.5: -c <conf> nativetun -n wgx-<id> -S --always-reconnect -r 5s, no --http2",
      _start[-10:] == ["/opt/usque", "-c", conf, "nativetun", "-n", "wgx-aabbccdd", "-S", "--always-reconnect", "-r", "5s"], _start[-11:])
_cj = json.load(open(conf))
check("the conf is usque's JSON: v4 endpoint without its port, the pin, the HTTP/2 endpoint, no v6",
      _cj == {"private_key": priv, "endpoint_v4": "162.159.198.1", "endpoint_v6": "", "endpoint_h2_v4": "162.159.198.2",
              "endpoint_h2_v6": "", "endpoint_pub_key": PEM, "id": "acct-x", "access_token": "tok-x", "ipv4": "172.16.0.2",
              "ipv6": ""}, _cj)
check("…0600", (os.stat(conf).st_mode & 0o777) == 0o600)
check("…sorted keys (byte-stable)", open(conf).read() == json.dumps(_cj, sort_keys=True, indent=1) + "\n")
_sig1, _ino = r["started"], os.stat(conf).st_ino
CALLS.clear()
e2, _ = N._mqx_up("aabbccdd", "wgx-aabbccdd", r, "h3")
check("written twice: byte-identical, same digest, no fork, no restart", e2 == "" and r["started"] == _sig1
      and os.stat(conf).st_ino == _ino and not any(c[0] in ("systemd-run", "systemctl") for c in CALLS), (CALLS, r["started"], _sig1))
CALLS.clear()
N._mqx_up("aabbccdd", "wgx-aabbccdd", r, "h2")
_start2 = next((c for c in CALLS if c[0] == "systemd-run"), [])
check("HTTP/2: --http2, and the changed digest replaces the unit", _start2[-1:] == ["--http2"] and r["started"] != _sig1
      and ["systemctl", "stop", "swg-mqx-aabbccdd"] in CALLS, (_start2[-2:], CALLS))
CALLS.clear()
e3, _ = N._mqx_up("11223344", "wgx-11223344", dict(MREC, peer_key=""), "h3")
check("an incomplete record is never started (usque would exit 0 on it for ever)",
      "incomplete" in e3 and not any(c[0] == "systemd-run" for c in CALLS), (e3, CALLS))
# docker: a real child — a stand-in that writes its environment and holds its conf on its command line
fake = os.path.join(TMP, "fakeusque")
open(fake, "w").write("#!%s\nimport os, sys, json, time\njson.dump(sorted(os.environ), open(%r, 'w'))\ntime.sleep(30)\n"
                      % (sys.executable, os.path.join(TMP, "child-env.json")))
os.chmod(fake, 0o755)
N.usq_binary = lambda: (fake, "")
N.NODE_KIND = "docker"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
os.environ["no_proxy"] = "x"
rd = dict(MREC)
ed, _ = N._mqx_up("55667788", "wgx-55667788", rd, "h3")
for _ in range(40):
    if os.path.exists(os.path.join(TMP, "child-env.json")):
        break
    time.sleep(0.05)
time.sleep(0.1)
_env = json.load(open(os.path.join(TMP, "child-env.json"))) if os.path.exists(os.path.join(TMP, "child-env.json")) else None
pid, _ = N._s5x_child("wgx-55667788", os.path.join(N.EXIT_DIR, "wgx-55667788.conf"))
check("docker: usque runs as a child holding its conf on the command line", ed == "" and pid > 1, (ed, pid))
check("…with no proxy in its environment (T9)", _env is not None and not any(k.lower().endswith("_proxy") for k in _env), _env)
os.environ.pop("HTTPS_PROXY"); os.environ.pop("no_proxy")
N._exit_down("wgx-55667788", dict(rd, id="55667788"))
time.sleep(0.2)
check("…and teardown stops it, its conf and pidfile gone", pid > 1 and not N._pid_alive(pid)
      and not os.path.exists(os.path.join(N.EXIT_DIR, "wgx-55667788.conf")) and not os.path.exists(N._s5x_pidfile("wgx-55667788")))
N.NODE_KIND = "baremetal"
N.usq_binary = lambda: ("/opt/usque", "")

# ── [4] teardown ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] teardown: a process, never wg-quick; with or without a device")
reset()
r = dict(MREC)
N._mqx_up("aabbccdd", "wgx-aabbccdd", r, "h3")
CALLS.clear()
N._exit_down("wgx-aabbccdd", dict(r, id="aabbccdd"))
check("_exit_down on a MASQUE TUN: its unit stopped, never wg-quick (T12)", ["systemctl", "stop", "swg-mqx-aabbccdd"] in CALLS
      and not any(c[0] in ("wg-quick", "awg-quick") for c in CALLS), CALLS)
check("…its conf removed", not os.path.exists(os.path.join(N.EXIT_DIR, "wgx-aabbccdd.conf")))
# pause: a unit waiting out its back-off has no device (T28)
reset()
save_rec("aabbccdd", dict(MREC, started="0123456789ab", device="wgx-aabbccdd"))
UNITS["swg-mqx-aabbccdd"] = "swg exit aabbccdd 0123456789ab"
rows, _ = sync({"id": "aabbccdd", "provider": "warp-masque", "down": True})
check("a pause stops a unit that has no device (T28)", ["systemctl", "stop", "swg-mqx-aabbccdd"] in CALLS and rows["aabbccdd"].get("paused"), CALLS)
check("…and keeps the account", rec_of("aabbccdd").get("account_id") == "acct-x" and rec_of("aabbccdd").get("priv") == priv)
CALLS.clear()
sync({"id": "aabbccdd", "provider": "warp-masque", "down": True})
check("…once (no stop every pass)", not any(c[:2] == ["systemctl", "stop"] for c in CALLS), CALLS)
# reap
reset()
save_rec("aabbccdd", dict(MREC, started="0123456789ab", device="wgx-aabbccdd"))
UNITS["swg-mqx-aabbccdd"] = "swg exit aabbccdd 0123456789ab"
sync()
check("a reap stops a unit that has no device (T28)", ["systemctl", "stop", "swg-mqx-aabbccdd"] in CALLS
      and not os.path.exists(os.path.join(N.EXIT_DIR, "aabbccdd.json")), CALLS)
# the start sweep
reset()
N._S5X_RUN.pop("swept_mqx", None)
_lu = N.run
def _run_lu(argv, **k):
    if argv[:2] == ["systemctl", "list-units"] and "swg-mqx-*" in argv:
        CALLS.append(list(argv))
        return R("swg-mqx-deadbeef.service loaded active running swg exit deadbeef 0123\n")
    return _lu(argv, **k)
N.run = _run_lu
sync()
N.run = _lu
check("the once-per-start sweep stops a MASQUE unit nothing wants", ["systemctl", "stop", "swg-mqx-deadbeef"] in CALLS, CALLS)

# ── [5] the freeze check ────────────────────────────────────────────────────────────────────────────────────────────────────
for _lg in ("wgx-aabbccdd.log", "wgx-aabbccdd.log.1"):
    open(os.path.join(N.EXIT_DIR, _lg), "w").close()
N._mqx_down("aabbccdd", "wgx-aabbccdd")
check("docker: a MASQUE exit's log goes with it, its rotated half too (review F13, F34)",
      not any(os.path.exists(os.path.join(N.EXIT_DIR, _lg)) for _lg in ("wgx-aabbccdd.log", "wgx-aabbccdd.log.1")))

print("\n[5] the freeze check (T1) and its sticky verdict (T30)")
cd = tempfile.mkdtemp(dir=TMP)
crt, key = os.path.join(cd, "c.pem"), os.path.join(cd, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost", "-days", "1",
                "-keyout", key, "-out", crt], capture_output=True, check=True)
sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sctx.load_cert_chain(crt, key)
MODE_SRV = {"m": "pass"}
lsn = socket.socket(); lsn.bind(("127.0.0.1", 0)); lsn.listen(8); FPORT = lsn.getsockname()[1]
def fsrv():
    while True:
        try:
            c, _ = lsn.accept()
        except OSError:
            return
        def one(c):
            try:
                t = sctx.wrap_socket(c, server_side=True); t.recv(4096)
                m = MODE_SRV["m"]
                if m == "403":
                    t.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                else:
                    t.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 65536\r\nConnection: close\r\n\r\n")
                    t.sendall(b"x" * (65536 if m == "pass" else 12000))
                    if m == "freeze":
                        time.sleep(6)
                t.close()
            except Exception:
                pass
        threading.Thread(target=one, args=(c,), daemon=True).start()
threading.Thread(target=fsrv, daemon=True).start()
_N3 = _load(_tmp if MODE else NODED, "swgnoded3")
_cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); _cctx.check_hostname = False; _cctx.verify_mode = ssl.CERT_NONE
_N3._exit_tls = lambda: _cctx
_fz = lambda: _N3._mqx_freeze("lo", host="localhost", port=FPORT, timeout=3)
MODE_SRV["m"] = "pass";   v1 = _fz()
MODE_SRV["m"] = "freeze"; v2 = _fz()
MODE_SRV["m"] = "403";    v3 = _fz()
v4 = _N3._mqx_freeze("lo", host="localhost", port=1, timeout=2)
check("64 KB crossed → pass", v1 == "pass", v1)
check("connected, then stalled at 12 KB → freeze", v2 == "freeze", v2)
check("an HTTP refusal (403) → no answer, never a freeze", v3 is None, v3)
check("nothing connected → no answer (a dead tunnel is the trace's to judge)", v4 is None, v4)
# stickiness
reset()
dev = "wgx-aabbccdd"
N._MQX_FZ[dev] = (time.time(), "freeze")
tr, _now, reach = N._mqx_evidence(dev, {"err": "timed out"}, True)
check("while the verdict says freeze, a failing probe is judged with its reason and reach=False, even if reach answered",
      tr.get("err") == N.MQX_FREEZE_WHY and reach(dev) is False, (tr, reach(dev)))
tr2, _n, reach2 = N._mqx_evidence(dev, {"ip": "1.2.3.4"}, None)
check("…a passing trace is left alone", tr2 == {"ip": "1.2.3.4"} and reach2(dev) is None)
_t0 = 1000.0
for i in range(4):
    tr, _n, rc = N._mqx_evidence(dev, {"err": "timed out"}, True)
    st = N._exit_judge(dev, tr, now=_t0 + 15 * i, reach=rc)
check("…so the exit goes dead with the freeze's reason", st["dead"] and st["why"] == N.MQX_FREEZE_WHY, st)
N._MQX_FZ[dev] = (time.time(), None)
N._mqx_evidence(dev, {}, None)
check("a run with no answer moves nothing (still freeze)", N._MQX[dev]["freeze"] == "freeze")
N._MQX_FZ[dev] = (time.time(), "pass")
N._mqx_evidence(dev, {}, None)
check("a later pass clears it", N._MQX[dev]["freeze"] == "pass")
N._MQX[dev]["freeze"] = "freeze"
tr3, _n, rc3 = N._mqx_evidence(dev, {}, None)
check("…and under a sticky freeze a probe still out at the bound ({}) stays no evidence (review F17)", tr3 == {} and rc3(dev) is None,
      (tr3, rc3(dev)))
# when it runs (§4.7)
N._MQX.clear(); N._EXIT_HEALTH.clear()
check("at bring-up: due", N._mqx_probe(dev, {})["mqx"] == "due")
N._MQX[dev] = {"fz_at": time.time()}
check("…then only on a first failure", N._mqx_probe(dev, {})["mqx"] == "onfail")
N._EXIT_HEALTH[dev] = {"fails": 2}
check("…not again while it keeps failing", N._mqx_probe(dev, {})["mqx"] == "")
N._MQX[dev] = {"fz_at": time.time() - 601}
check("…and every 10 min", N._mqx_probe(dev, {})["mqx"] == "due")
N._EXIT_HEALTH[dev] = {"fails": 9, "dead": True}
N._MQX[dev] = {"fz_at": time.time() - 61}
check("DEAD: on a trace that passes (a fresh flow nobody else uses), at most once a minute",
      N._mqx_probe(dev, {})["mqx"] == "onpass" and (N._MQX.__setitem__(dev, {"fz_at": time.time() - 30}) or N._mqx_probe(dev, {})["mqx"] == ""))
_calls = []
N._mqx_freeze = lambda d, *a, **k: (_calls.append(d), "freeze")[1]
N._exit_probe_all([(dev, {"endpoint": "1.2.3.4:443", "mqx": "onpass"})])
fzwait()
TR[dev] = {"err": "timed out"}
N._exit_probe_all([(dev, {"endpoint": "1.2.3.4:443", "mqx": "onpass"})])
fzwait()
TR.pop(dev)
check("…run when the trace passed, not when it failed", _calls == [dev], _calls)
# the run is a thread of its own: the pass never waits on its 10 s, one run at a time per device (review F14)
_gate, _calls = threading.Event(), []
N._mqx_freeze = lambda d, *a, **k: (_calls.append(d), _gate.wait(3), "pass")[2]
N._MQX_FZ.clear()
_t0 = time.monotonic()
N._exit_probe_all([(dev, {"endpoint": "1.2.3.4:443", "mqx": "due"})])
_el = time.monotonic() - _t0
N._exit_probe_all([(dev, {"endpoint": "1.2.3.4:443", "mqx": "due"})])
_n = len(_calls)
_gate.set(); fzwait()
check("the 64 KB run never holds the pass, one at a time per device, its answer parked for a later pass (review F14)",
      _el < 1.5 and _n == 1 and (N._MQX_FZ.get(dev) or (0, None))[1] == "pass", (_el, _n, N._MQX_FZ.get(dev)))
N._MQX_FZ.clear()
# …and the next pass starts no second run while one is in flight or its answer is unread: fz_at moves when it is taken (F29)
N._MQX[dev] = {"fz_at": time.time() - 700}
N._EXIT_HEALTH.pop(dev, None)
N._MQX_FZ_RUN[dev] = object()
_d1 = N._mqx_probe(dev, {})["mqx"]
N._MQX_FZ_RUN.clear()
N._MQX_FZ[dev] = (time.time(), "pass")
_d2 = N._mqx_probe(dev, {})["mqx"]
N._mqx_evidence(dev, {"ip": "1.2.3.4"}, None)
_d3 = N._mqx_probe(dev, {})["mqx"]
check("no second freeze run while one is in flight or its answer is not yet taken; none after it is (review F29)",
      (_d1, _d2, _d3) == ("", "", "onfail"), (_d1, _d2, _d3))
# a run that outlives its tunnel (a new config) is discarded, and does not hold up the new tunnel's own run (F30)
reset()
sync({"id": "aabbccdd", "provider": "warp-masque"})
fzwait(); N._MQX_FZ.clear()
_gate = threading.Event()
N._mqx_freeze = lambda d, *a, **k: (_gate.wait(3), "freeze")[1]
N._exit_probe_all([(dev, {"endpoint": "1.2.3.4:443", "mqx": "due"})])
_r = rec_of("aabbccdd")
N._mqx_up("aabbccdd", dev, _r, "h2")                    # a new config (the transport) while the run is out
_free = dev not in N._MQX_FZ_RUN
_gate.set(); time.sleep(0.3)
check("a freeze run that outlived its tunnel's config is discarded, and the new tunnel may run its own (review F30)",
      _free and dev not in N._MQX_FZ, (_free, N._MQX_FZ.get(dev)))
N._mqx_freeze = lambda dev, *a, **k: FZ["v"]

# a verdict already dead (the trace's timeout) is renamed once a run proves the freeze
reset()
sync({"id": "aabbccdd", "provider": "warp-masque"})
dev = "wgx-aabbccdd"
N._EXIT_HEALTH[dev] = {"dead": True, "since": time.time() - 100, "fails": 20, "fail_since": time.time() - 130, "ok_since": None,
                       "why": "TimeoutError: timed out"}
N._MQX[dev] = {"fz_at": time.time() - 100}
TR[dev] = {"ip": "198.51.100.7", "warp": "on"}       # usque reconnected: the fresh flow's trace passes …
FZ["v"] = "freeze"                                     # … and the 64 KB check stalls
sync({"id": "aabbccdd", "provider": "warp-masque"})
fzwait()                                               # its own thread (F14): the next pass takes the answer
rows, _ = sync({"id": "aabbccdd", "provider": "warp-masque"})
FZ["v"] = "pass"; TR.pop(dev)
check("a dead exit whose fresh flow passes the trace and stalls at 64 KB: named a freeze (the rig's case)",
      (rows["aabbccdd"].get("no_traffic") or {}).get("why") == N.MQX_FREEZE_WHY and rows["aabbccdd"].get("freeze") == "freeze",
      rows["aabbccdd"])

# ── [6] the kick ────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[6] the kick: dead 180 s → restart, then ×2 up to 30 min")
reset()
hl = {"dead": True, "since": 0.0}
kicks = [t for t in range(0, 6000, 10) if N._mqx_kick("aabbccdd", dev, hl, now=float(t))]
check("restarts at 180, +360, +720, +1440, then every 1800", kicks == [180, 540, 1260, 2700, 4500], kicks)
check("…with systemctl restart", ["systemctl", "restart", "swg-mqx-aabbccdd"] in CALLS)
N._mqx_kick("aabbccdd", dev, {"dead": False})
check("reset when the verdict clears", "kick_n" not in N._MQX[dev])
check("a dead exit carrying again, inside its alive window, is not restarted (review F15)",
      not N._mqx_kick("aabbccdd", dev, {"dead": True, "since": 0.0, "ok_since": 9990.0}, now=10000.0))
N.NODE_KIND = "docker"
_sc, _skl = N._s5x_child, N._s5x_kill
N._s5x_child = lambda d, c: (4242, "sig")
N._s5x_kill = lambda pid: None
N._S5X_PROCS["aabbccdd"] = {"proc": None, "deaths": 1, "next": 0.0, "at": 5.0}
N._MQX.pop(dev, None)
_k = N._mqx_kick("aabbccdd", dev, {"dead": True, "since": 0.0}, now=200.0)
_p = N._S5X_PROCS["aabbccdd"]
check("docker: a kick is a deliberate stop — the next pass relaunches it with no death and no back-off (review F20)",
      _k and _p["proc"] is None and not _p["at"] and _p["deaths"] == 1, _p)
N._s5x_child, N._s5x_kill = _sc, _skl
N.NODE_KIND = "baremetal"
N._S5X_PROCS.clear()

# ── [7] registration and the switch ─────────────────────────────────────────────────────────────────────────────────────────
print("\n[7] registration and the switch, against a fake /reg")
reset()
X = "aabbccdd"
rows, res = sync({"id": X, "provider": "warp-masque"})
rc = rec_of(X)
check("a new MASQUE exit: one POST, one PATCH to secp256r1/masque", posts() == 1 and len(patches()) == 1
      and patches()[0][2].get("key_type") == "secp256r1" and patches()[0][2].get("tunnel_type") == "masque", CF["calls"])
check("…the record: the account, a P-256 key, the PEM pin, <v4>:443", str(rc.get("account_id")).startswith("acct-") and rc.get("token") == "tok-" + str(rc.get("account_id"))
      and len(base64.b64decode(rc.get("pub", ""))) == 91 and rc.get("peer_key") == PEM and rc.get("endpoint") == "162.159.198.1:443"
      and rc.get("provider") == "warp-masque", rc)
check("…and usque started on wgx-<id>", "swg-mqx-" + X in UNITS and rows[X]["up"] is True, (UNITS, rows[X]))
# a failed PATCH is retried alone
reset()
CF["fail"] = [None]
CF["fail"] = []
_orig = N._warp_enrol
_once = {"n": 0}
def _enrol_fail_once(rec, kind, key=None):
    if _once["n"] == 0:
        _once["n"] += 1
        return None, False, "Cloudflare is refusing requests from this node's address just now (HTTP 503).", False
    return _orig(rec, kind, key)
N._warp_enrol = _enrol_fail_once
rows, _ = sync({"id": X, "provider": "warp-masque"})
rc = rec_of(X)
check("a PATCH that fails after the POST: the account is kept, without the WireGuard key the POST carried (T6)",
      rc.get("account_id") and not rc.get("priv") and rc.get("reg_fails") == 1 and rows[X].get("retry_in"), (rc, rows[X]))
save_rec(X, dict(rc, reg_next=0))
rows, _ = sync({"id": X, "provider": "warp-masque"})
N._warp_enrol = _orig
check("…the retry is the PATCH alone — no second account", posts() == 1 and rec_of(X).get("provider") == "warp-masque"
      and rows[X]["up"] is True, (posts(), rec_of(X)))
check("…and success clears the back-off", "reg_fails" not in rec_of(X))
# the switch, MASQUE → WireGuard
acct0 = (rec_of(X)["account_id"], rec_of(X)["token"])
CALLS.clear(); UPS.clear()
rows, _ = sync({"id": X, "provider": "warp"})
rc = rec_of(X)
check("MASQUE → WireGuard keeps account_id and token, no POST", (rc["account_id"], rc["token"]) == acct0 and posts() == 1
      and patches()[-1][2].get("tunnel_type") == "wireguard", (rc, CF["calls"][-1]))
check("…the old device went by the OLD kind: its unit stopped (T21)", ["systemctl", "stop", "swg-mqx-" + X] in CALLS, CALLS)
check("…the WireGuard endpoint is the answer's host, not its v4 (P0 #8: v4 lands at DME)",
      rc.get("endpoint") == "engage.cloudflareclient.com:2408", rc.get("endpoint"))
check("…wg-quick brought the new device up on the same name", UPS and UPS[-1][0] == "wg-quick" and rows[X]["up"] is True
      and rows[X]["provider"] == "warp", (UPS, rows[X]))
# WireGuard → MASQUE
CALLS.clear()
rows, _ = sync({"id": X, "provider": "warp-masque"})
rc = rec_of(X)
check("WireGuard → MASQUE keeps the account, no POST", (rc["account_id"], rc["token"]) == acct0 and posts() == 1 and rc["provider"] == "warp-masque")
check("…the WireGuard device went by wg-quick, then usque started", any(c[:2] == ["wg-quick", "down"] for c in CALLS)
      and "swg-mqx-" + X in UNITS, CALLS)
# a refused PATCH leaves the old kind carrying on the same device
CALLS.clear()
CF["fail"] = [(503, "busy")]
rows, _ = sync({"id": X, "provider": "warp"})
rc = rec_of(X)
check("a failed switch PATCH: nothing torn down, the MASQUE exit still carrying on wgx-<id> (T19)",
      rc["provider"] == "warp-masque" and "swg-mqx-" + X in UNITS and LINK.get("wgx-" + X) == "up" and rows[X]["up"] is True
      and not any(c[:2] == ["systemctl", "stop"] for c in CALLS), (rc.get("provider"), CALLS))
check("…and the row says why, with when it retries", rows[X].get("error", "").startswith("still on MASQUE:") and rows[X].get("retry_in"), rows[X])
CALLS.clear()
rows, _ = sync({"id": X, "provider": "warp"})
check("…backing off, it still carries — judged, routed", rows[X]["up"] is True and not patches()[-1:] == [] and len(CF["calls"]) and
      rows[X].get("error", "").startswith("still on MASQUE:"), rows[X])
CF["fail"] = [(503, "busy")]
save_rec(X, dict(rec_of(X), reg_next=0))
sync({"id": X, "provider": "warp"})
CF["calls"].clear()
rows, _ = sync({"id": X, "provider": "warp-masque"})
check("a switch given up (the panel wants the running kind again): its back-off is cleared, no PATCH", not CF["calls"]
      and "reg_fails" not in rec_of(X) and not rows[X].get("error"), (CF["calls"], rec_of(X).get("reg_fails"), rows[X].get("error")))
# a switch to MASQUE waits for usque: nothing PATCHed or torn down meanwhile (review F8)
reset()
sync({"id": X, "provider": "warp"})
CF["calls"].clear(); CALLS.clear()
N.usq_binary = lambda: ("", N.MQX_BUSY)
rows, _ = sync({"id": X, "provider": "warp-masque"})
check("a switch to MASQUE while usque is being fetched: no PATCH, WireGuard carries on, the row says so (review F8)",
      not patches() and rec_of(X)["provider"] == "warp" and not any(c[:2] == ["wg-quick", "down"] for c in CALLS)
      and rows[X]["up"] is True and rows[X].get("error", "").startswith("still on WireGuard: fetching"), (patches(), rows[X]))
N.usq_binary = lambda: ("/opt/usque", "")
sync({"id": X, "provider": "warp-masque"})
check("…and goes ahead once it is there", rec_of(X)["provider"] == "warp-masque" and len(patches()) == 1, rec_of(X).get("provider"))
# a failed switch away from an HTTP/2 MASQUE exit keeps it on HTTP/2 (review F11)
CALLS.clear()
sync({"id": X, "provider": "warp-masque", "transport": "h2"})
_was = any(c[0] == "systemd-run" and "--http2" in c for c in CALLS)
CALLS.clear()
CF["fail"] = [(503, "busy")]
rows, _ = sync({"id": X, "provider": "warp"})
check("a failed switch away from an HTTP/2 MASQUE exit: usque is not restarted on HTTP/3 (review F11)",
      _was and not any(c[0] == "systemd-run" or c[:2] == ["systemctl", "stop"] for c in CALLS) and rec_of(X).get("transport") == "h2"
      and rows[X].get("error", "").startswith("still on MASQUE:"), (_was, CALLS, rec_of(X).get("transport")))
# 1001: a fresh key, once
reset()
save_rec(X, {"provider": "warp", "account_id": "acct-9", "token": "tok-acct-9"})
CF["accts"]["acct-9"] = {"token": "tok-acct-9", "key": ""}
CF["fail"] = [(401, {"success": False, "errors": [{"code": 1001, "message": "Invalid public key"}]})]
rows, _ = sync({"id": X, "provider": "warp-masque"})
check("1001 (also a 401) → one fresh key, never a refused account", len(patches()) == 2 and patches()[0][2]["key"] != patches()[1][2]["key"]
      and rec_of(X).get("priv") and not rec_of(X).get("refused"), (patches(), rec_of(X)))

# ── [8] restore ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[8] restore: the blob's kind, its account enrolled for the exit's current kind")
N.transport_priv = lambda: b""
N.ivk_unseal = lambda priv, blob: json.dumps(blob["_plain"]).encode()
mpriv, mpub = N._p256_keypair()
BLOB_MQ = {"priv": mpriv, "pub": mpub, "address": "172.16.0.2", "peer_key": PEM, "endpoint": "162.159.198.1:443",
           "account_id": "acct-old", "token": "tok-acct-old", "account_type": "free", "provider": "warp-masque"}
BLOB_WG = {"priv": "d2dwcml2", "pub": "PUBwg-old", "address": "172.16.0.2", "peer_key": CF["wg_peer"],
           "endpoint": "engage.cloudflareclient.com:2408", "account_id": "acct-old", "token": "tok-acct-old",
           "account_type": "free", "provider": "warp", "mtu": 1280}
reset()
CF["accts"]["acct-old"] = {"token": "tok-acct-old", "key": ""}
sync({"id": X, "provider": "warp-masque"})                     # the node re-registered after a rebuild
CF["calls"].clear()
rows, _ = sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
rc = rec_of(X)
check("a MASQUE blob onto a MASQUE exit: its OWN key enrolled on its account", rc.get("account_id") == "acct-old" and rc.get("pub") == mpub
      and patches() and patches()[-1][2]["key"] == mpub and patches()[-1][3] == "tok-acct-old", (rc.get("pub"), patches()))
check("…and the row reports the blob's key (the relay clears)", rows[X].get("public_key") == mpub and "restored" not in rows[X], rows[X])
CF["calls"].clear()
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
check("…applied once: the relay riding the next sync makes no second PATCH (T29)", not patches(), CF["calls"])
# a legacy WireGuard blob onto a MASQUE exit: the account, a fresh P-256 key
reset()
CF["accts"]["acct-old"] = {"token": "tok-acct-old", "key": ""}
sync({"id": X, "provider": "warp-masque"})
CF["calls"].clear(); CALLS.clear()
rows, _ = sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_WG}})
rc = rec_of(X)
check("a WireGuard blob onto a MASQUE exit: the blob's account, a fresh P-256 key (Q12)", rc.get("account_id") == "acct-old"
      and rc.get("provider") == "warp-masque" and patches() and patches()[-1][2]["key_type"] == "secp256r1"
      and rc.get("pub") != BLOB_WG["pub"], (rc, patches()))
check("…`restored` reported while the key differs from the blob's (T29)", rows[X].get("restored") == BLOB_WG["pub"], rows[X])
CF["calls"].clear()
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_WG}})
check("…and never applied twice", not patches(), CF["calls"])
# a legacy WireGuard blob onto a WireGuard exit, Cloudflare unreachable: installed as it is (R3)
reset()
sync({"id": X, "provider": "warp"})
CF["fail"] = [(0, "timed out")]
rows, _ = sync({"id": X, "provider": "warp", "key_blob": {"ct": "x", "_plain": BLOB_WG}})
rc = rec_of(X)
check("a same-kind blob whose PATCH fails is installed as it is — today's restore (R3)", rc.get("pub") == BLOB_WG["pub"]
      and rc.get("account_id") == "acct-old" and rows[X].get("public_key") == BLOB_WG["pub"], rc)
# a cross-kind blob whose PATCH fails: the running exit stays, and says why
reset()
sync({"id": X, "provider": "warp"})
_run_pub = rec_of(X)["pub"]
CF["fail"] = [(0, "timed out")]
rows, _ = sync({"id": X, "provider": "warp", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
check("a cross-kind blob whose PATCH fails keeps the running exit and reports restore_error",
      rec_of(X)["pub"] == _run_pub and rows[X]["up"] is True and "could not be enrolled" in rows[X].get("restore_error", "")
      and rows[X].get("restored") == mpub, rows[X])

# a refused account on a node with no key: said, and one press is one PATCH
reset()
CF["accts"].pop("acct-old", None)
rows, _ = sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
n1 = len(patches())
rows2, _ = sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
check("a blob whose account Cloudflare deleted (1006), on a node with no key: said, and never PATCHed twice",
      n1 >= 1 and len(patches()) == n1 and "could not be enrolled" in rows2[X].get("error", ""), (n1, len(patches()), rows2[X]))

# a failed restore: not again on the same relay, tried again on a new press — each is sealed afresh (review F3)
reset()
sync({"id": X, "provider": "warp"})
CF["accts"]["acct-old"] = {"token": "tok-acct-old", "key": ""}
CF["fail"] = [(0, "timed out")]
sync({"id": X, "provider": "warp", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
CF["calls"].clear()
sync({"id": X, "provider": "warp", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
_same = len(patches())
rows, _ = sync({"id": X, "provider": "warp", "key_blob": {"ct": "y", "_plain": BLOB_MQ}})
check("a restore that failed: not again on the same relay, tried again on a new press — and applied (review F3)",
      _same == 0 and len(patches()) == 1 and rec_of(X).get("account_id") == "acct-old" and not rows[X].get("restore_error"),
      (_same, patches(), rows[X]))
# a restore onto a MASQUE exit waits for usque (review F8)
reset()
sync({"id": X, "provider": "warp"})
CF["accts"]["acct-old"] = {"token": "tok-acct-old", "key": ""}
CF["calls"].clear(); CALLS.clear()
N.usq_binary = lambda: ("", N.MQX_BUSY)
rows, _ = sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_WG}})
check("a restore onto a MASQUE exit while usque is being fetched: nothing PATCHed or torn down, and said (review F8)",
      not patches() and rec_of(X)["provider"] == "warp" and not any(c[:2] == ["wg-quick", "down"] for c in CALLS)
      and "waits for the MASQUE tunnel program" in rows[X].get("restore_error", ""), (patches(), rows[X]))
N.usq_binary = lambda: ("/opt/usque", "")
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_WG}})
check("…and the same relay applies once it is there", len(patches()) == 1 and rec_of(X)["provider"] == "warp-masque", patches())
# a restore onto a DEAD exit: one PATCH; the restored key is judged afresh, never re-enrolled in that pass (review F1).
# (A new key is a new config: the bring-up drops the old key's verdict — _mqx_up, the WireGuard bounce.)
reset()
CF["accts"]["acct-old"] = {"token": "tok-acct-old", "key": ""}
sync({"id": X, "provider": "warp-masque"})
dev = "wgx-" + X
_dead = lambda: {"dead": True, "since": time.time() - 1000, "fails": 99, "fail_since": time.time() - 1000, "ok_since": None, "why": "x"}
N._EXIT_HEALTH[dev] = _dead()
N._MQX[dev] = {"fz_at": time.time(), "freeze": "pass"}
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "x", "_plain": BLOB_MQ}})
check("a restore onto an exit dead 15 min: one PATCH, no 6 h back-off on the restored key, the old key's verdict dropped (review F1)",
      len(patches()) == 1 and not rec_of(X).get("reenrol_next") and not (N._EXIT_HEALTH.get(dev) or {}).get("dead"),
      (patches(), rec_of(X).get("reenrol_next"), N._EXIT_HEALTH.get(dev)))
N._EXIT_HEALTH[dev] = _dead()
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "z", "_plain": BLOB_MQ}})
check("…and the same key put back on a dead exit: still one PATCH in that pass", len(patches()) == 1, patches())
# a relay already acted on, riding on: nothing was sent this pass, so a due re-enrolment is not held off (review F32)
N._EXIT_HEALTH[dev] = _dead()
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp-masque", "key_blob": {"ct": "z", "_plain": BLOB_MQ}})
check("…a relay already acted on, still riding, does not hold off a due re-enrolment (review F32)",
      len(patches()) == 1 and patches()[0][2]["key"] == rec_of(X)["pub"], patches())

# ── [9] re-enrolment ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[9] re-enrolment, both kinds")
reset()
sync({"id": X, "provider": "warp"})
dev = "wgx-" + X
rc = rec_of(X)
HS = {"v": 0}
_hs_real = N._exit_handshake
_hs_calls = [0]
def _hs(rec, d):
    _hs_calls[0] += 1
    return HS["v"]
N._exit_handshake = _hs
now = time.time()
N._EXIT_HEALTH[dev] = {"dead": False, "since": now - 10000, "fails": 0}
check("a carrying exit: not due, and no handshake read (no fork)", not N._warp_reenrol_due(dev, rc) and _hs_calls[0] == 0, _hs_calls)
N._EXIT_HEALTH[dev] = {"dead": True, "since": now - 899, "fails": 9}
check("dead 899 s: not yet", not N._warp_reenrol_due(dev, rc, now=now))
N._EXIT_HEALTH[dev]["since"] = now - 901
check("dead 15 min, never handshook: due", N._warp_reenrol_due(dev, rc, now=now))
HS["v"] = 30
check("…a FRESH handshake with nothing crossing: the path, not the key — never", not N._warp_reenrol_due(dev, rc, now=now))
HS["v"] = 400
check("…a stale one: due", N._warp_reenrol_due(dev, rc, now=now))
N._WARP_REENROL["at"] = now - 100
check("one per node per 5 min", not N._warp_reenrol_due(dev, rc, now=now))
N._WARP_REENROL["at"] = 0.0
check("its own back-off", not N._warp_reenrol_due(dev, dict(rc, reenrol_next=now + 60), now=now))
check("no account, no re-enrolment", not N._warp_reenrol_due(dev, dict(rc, token=""), now=now))
mrec = dict(MREC)
N._MQX[dev] = {"freeze": "freeze"}
check("MASQUE: not while the freeze verdict blames the network", not N._warp_reenrol_due(dev, mrec, now=now))
N._MQX[dev] = {"freeze": "pass"}
check("MASQUE: due when bytes flowed and stopped", N._warp_reenrol_due(dev, mrec, now=now))
N._EXIT_HEALTH[dev]["ok_since"] = now - 5
check("…not while it carries again, inside its alive window (review F15)", not N._warp_reenrol_due(dev, mrec, now=now))
N._EXIT_HEALTH[dev].pop("ok_since")
N._MQX.clear()
# through the pass: a new peer key → rebuilt; the same → 6 h
HS["v"] = 0
N._EXIT_HEALTH[dev] = {"dead": True, "since": time.time() - 1000, "fails": 99, "fail_since": time.time() - 1000, "ok_since": None, "why": "x"}
TR[dev] = {"err": "timed out"}
N._exit_reach = lambda d, *a, **k: False
CF["wg_peer"] = "TmV3UGVlcktleU5ld1BlZXJLZXlOZXdQZWVyS2V5MD0="
CF["calls"].clear(); UPS.clear()
_trc, _tr0 = [], N._exit_trace
N._exit_trace = lambda d, *a, **k: (_trc.append(d), _tr0(d, *a, **k))[1]
sync({"id": X, "provider": "warp"})
N._exit_trace = _tr0
rc2 = rec_of(X)
check("the pass that re-enrolled an exit (its PATCH took up to 30 s of it) does not probe it too (review F2)", dev not in _trc, _trc)
check("a WireGuard exit whose /reg answers a new peer key is rebuilt on it", patches() and patches()[-1][2]["key"] == rc["pub"]
      and rc2["peer_key"] == CF["wg_peer"] and UPS and not rc2.get("reenrol_next"), (patches(), rc2.get("peer_key"), UPS))
check("…its own key, the same account", rc2["pub"] == rc["pub"] and rc2["account_id"] == rc["account_id"])
N._EXIT_HEALTH[dev] = {"dead": True, "since": time.time() - 1000, "fails": 99, "fail_since": time.time() - 1000, "ok_since": None, "why": "x"}
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp"})
rc3 = rec_of(X)
check("one that answers the same waits 6 h", len(patches()) == 1 and rc3.get("reenrol_next", 0) > time.time() + 6 * 3600 - 60, rc3.get("reenrol_next"))
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp"})
check("…and is not asked again meanwhile", not patches())
# a refused account stops
save_rec(X, dict(rec_of(X), reenrol_next=0, token="tok-revoked"))
N._EXIT_HEALTH[dev] = {"dead": True, "since": time.time() - 1000, "fails": 99, "fail_since": time.time() - 1000, "ok_since": None, "why": "x"}
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
rows, _ = sync({"id": X, "provider": "warp"})
rc4 = rec_of(X)
check("a JSON 401 (1012) stops: refused, said on the row, no new account", rc4.get("refused") == N.WARP_REFUSED
      and rows[X].get("error") == N.WARP_REFUSED and posts() == 0, (rc4.get("refused"), rows[X].get("error")))
N._WARP_REENROL["at"] = 0.0
CF["calls"].clear()
sync({"id": X, "provider": "warp"})
check("…and nothing more is asked of Cloudflare", not CF["calls"], CF["calls"])
rows, _ = sync({"id": X, "provider": "warp", "licence": "LIC-123"})
check("…not even a WARP+ licence, and the row keeps saying why (review F5)", not CF["calls"] and rows[X].get("error") == N.WARP_REFUSED,
      (CF["calls"], rows[X].get("error")))
N._exit_handshake = _hs_real
N._exit_reach = lambda dev, *a, **k: True
CF["wg_peer"] = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="

# ── [10] escrow ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[10] escrow: both kinds, `acct` in the clear")
reset()
N._IVK_VAULT_PUB = ""
N._EXIT_SEALED.clear()
_seal = N.ivk_seal
N.ivk_seal = lambda vpub, pt: {"ct": base64.b64encode(pt).decode(), "eph": "e", "mac": "m"}
save_rec(X, dict(MREC))
N.exit_vault_process("VAULT", [X])
b1 = N._EXIT_SEALED.get(X) or {}
_acct = hashlib.sha256(b"swg-acct\0acct-x").hexdigest()[:16]
check("a MASQUE exit is sealed, `provider` inside, `acct` outside", json.loads(base64.b64decode(b1.get("ct", "e30=")))
      .get("provider") == "warp-masque" and b1.get("acct") == _acct and b1.get("pub") == MREC["pub"], b1)
save_rec(X, dict(MREC, provider="warp", priv="wgk", pub="PUBnew"))
N.exit_vault_process("VAULT", [X])
b2 = N._EXIT_SEALED.get(X) or {}
check("…re-sealed after a switch: a new `pub`, the SAME `acct` (a rotation, not a new account — T22)",
      b2.get("pub") == "PUBnew" and b2.get("acct") == _acct, b2)
N.ivk_seal = _seal

# ── [11] rows ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[11] the rows")
reset()
rows, _ = sync({"id": X, "provider": "warp-masque"}, {"id": "11223344", "provider": "warp"})
m, w = rows[X], rows["11223344"]
check("a MASQUE row: no peer key (the PEM stays on the node), no handshake", m.get("peer_key") == "" and m.get("handshake") is None, m)
check("…its colo and freeze verdict", m.get("colo") == "DME" and m.get("freeze") == "pass", m)
check("a WireGuard row as before: no colo anywhere", "colo" not in w and "colo" not in (w.get("trace") or {}) and "freeze" not in w, w)
check("node reports the new kind", "warp-masque" in N.EXIT_KINDS)
_ul0 = N._exit_underlay
N._exit_underlay = lambda rec, dev, hs: {"via": "v4", "failed": ["v6"]}
rows, _ = sync({"id": X, "provider": "warp-masque"}, {"id": "11223344", "provider": "warp"})
N._exit_underlay = _ul0
check("item 11's underlay is WireGuard's: never on a MASQUE row (review F18)", "underlay" not in rows[X] and "underlay" in rows["11223344"],
      (rows[X].get("underlay"), rows["11223344"].get("underlay")))
open(os.path.join(N.EXIT_DIR, "wgx-aabbccdd.log"), "w").close()
check("docker: a MASQUE child's log is inside the log budget (review F13)",
      os.path.join(N.EXIT_DIR, "wgx-aabbccdd.log") in N._supervised_logs(), N._supervised_logs())

if MODE:
    print("\nperturbed (%s): %s" % (MODE, "CAUGHT — %d red" % len(FAILS) if FAILS else "NOTHING FAILED"))
    sys.exit(0 if FAILS else 1)
if FAILS:
    print("\nFAILED: " + "; ".join(FAILS)); sys.exit(1)
print("\nALL PASS"); sys.exit(0)
