#!/usr/bin/env python3
"""Self-test — THE SOCKS5 EXIT, the panel's half (docs/SOCKS5-EXIT-PLAN.md §6.1, §6.8, release plan S10 / P3).

  [1] the paste — the forms proxy dashboards show (socks5://, socks5h://, user:pass@host:port, host:port:user:pass, a bare
      host:port; percent-decoded), and the refusals: http(s)://, socks4://, an IPv6 literal (D4)
  [2] the password — write-only: a paste's wins, else a typed one, else the stored one, and the stored one only for the
      same user (a different login never inherits it); the sentinel keeps it
  [3] a save — through a REAL panel process (/api/nodes/update): the device is `s5x-<id>`, the record holds the proxy and
      no licence / dial source, and the signature changes with the password (salted: it is shown to the browser)
  [4] s9a F17 — a node that does not report `socks5` among its `exit_kinds` is refused a new SOCKS exit, is never SENT one
      (/api/node/sync — an older node registered WARP for any kind that was not `profile`), and its row says why
  [5] T7 — /api/state never carries the password or its salt; the sync reply carries the password to the node, never the
      salt; the fingerprint masks both
  [6] D-c — a SOCKS exit and a tunnel are not one exit edited: the kind change is refused
  [7] the mirror — the pinned hev bytes or nothing: a file in the store that is not the pin is deleted, never served
  [8] the Test (§6.8) — armed on a node that can run it, carried to the node with the password, its answer absorbed, the
      password gone from the reply once answered; a second while one runs is busy; a node that cannot run it is refused

Run: python3 tests/socks5_exit_panel_selftest.py           (0 = pass)
     --perturb-<name>   plants one regression in a copy of the panel (see PLANTS) and expects RED
"""
import hashlib, importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANTS = {
    "--perturb-http": ('        if m.group(1).lower() not in ("socks5", "socks5h"):', '        if m.group(1).lower() not in ("socks5", "socks5h", "http"):'),  # [1]
    "--perturb-v6": ('    if "[" in hp or hp.count(":") > 1:', '    if False:'),                                         # [1]
    "--perturb-salt": ('    "pass": hashlib.sha256((str(sk.get("salt") or "") + "\\0" + str(sk.get("pass") or "")).encode()).hexdigest()[:16]}',
                       '    "pass": hashlib.sha256(str(sk.get("pass") or "").encode()).hexdigest()[:16]}'),                  # [3]
    "--perturb-sig": ('        mat["socks"] = _socks_sig_part(rec["socks"])', '        pass'),                                # [3]
    "--perturb-f17save": ('                if gen_snap is not None and not _kept:\n', '                if False:\n'),                # [4]
    "--perturb-f17sync": ('                                          and not exit_kind_refusal(snap, x.get("provider") or "warp")],',
                          '                                          ],'),                                                  # [4]
    "--perturb-state": ('**({"socks": socks_public(e["socks"])} if isinstance(e.get("socks"), dict) else {}))',
                        '**({"socks": e["socks"]} if isinstance(e.get("socks"), dict) else {}))'),                         # [5]
    "--perturb-salt-wire": ('**({"socks": {k: x["socks"].get(k) for k in ("host", "port", "user", "pass")}}',
                            '**({"socks": dict(x["socks"])}'),                                                          # [5]
    "--perturb-kind": ('            if _was_pv and (_was_pv == "socks5") != (_pv == "socks5"):', '            if False:'),     # [6]
    "--perturb-mirror": ('            if _turn_sha256_file(dest) == want:\n                return dest\n            os.remove(dest)',
                         '            return dest'),                                                                       # [7]
    # the max review's fix round (runs/s10-p3-socks)
    "--perturb-host": ('        same = (sk["host"], int(sk["port"]), sk["user"]) == (kept.get("host"), int(kept.get("port") or 0), kept.get("user"))',
                       '        same = sk["user"] == kept.get("user")'),                                              # [2] F10
    "--perturb-silent": ('        elif kept.get("pass") and sk["user"] and pw == EXIT_PASS_KEEP:\n            return None, "the proxy\'s address or user changed — type its password again"\n',
                         ''),                                                                                       # [2] F2
    "--perturb-pct": ('    if url:                    # percent-escapes are a URL\'s', '    if True:                   # percent-escapes are a URL\'s'),  # [1] F20
    "--perturb-guess": ("    if len(reads) > 1:", "    if False:"),                                                     # [1] verify F61–F63
    "--perturb-negcache": ("            _HEV_MIRROR_FAIL[arch] = time.time()", "            pass"),                              # [7] verify F48
    "--perturb-kinds-shape": ('    if isinstance(_k, list) and kind in _k:', '    if kind in (_k or []):'),                     # [4] F6
    "--perturb-unknown": ('    if kind != "socks5":\n        return None\n', ''),                                              # [4] F28
    "--perturb-fp": ('                    v = str(o.get("salt") or "") + "\\0" + v       # salted by its own record', '                    pass  #'),  # [5] F26
    "--perturb-transfer": ("_FP_EXCLUDE = (\n", "_FP_EXCLUDE = (\n    (\"exits.*.socks.pass\", \"x\"),\n"),  # [5] F46
    "--perturb-expire": ('        rec["socks"] = {}                             # its password goes with it, whoever asks first (review F27)\n', ''),  # [8] F27
    "--perturb-lock": ("    with _HEV_MIRROR_LOCK:                            # one fetch at a time", "    if True:  #"),              # [7] F5
    "--perturb-busy": ('            if cur["result"] is None:\n                return 409, {"ok": False, "error": "a test is already running on this node", "code": "busy"}',
                       '            if False:\n                return 409, {"ok": False, "error": "a test is already running on this node", "code": "busy"}'),  # [8]
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="s5x-panel-")
server = SERVER
if MODE:
    _s = open(SERVER, encoding="utf-8").read()
    _a, _b = PLANTS[MODE]
    assert _s.count(_a) == 1, "perturbation anchor for %s is missing or not unique — would FALSE-PASS" % MODE
    server = os.path.join(TMP, "panel-perturbed.py")
    open(server, "w", encoding="utf-8").write(_s.replace(_a, _b, 1))
_l = importlib.machinery.SourceFileLoader("swgpanel", server)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

# ── [1] the paste ───────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] the one paste field")
OK = {"socks5://alice:s%3Acret@proxy.example:1080": ("proxy.example", 1080, "alice", "s:cret"),
      "socks5h://198.51.100.7:1085": ("198.51.100.7", 1085, "", ""),
      "bob:pw@198.51.100.8:9050": ("198.51.100.8", 9050, "bob", "pw"),
      "gate.provider.net:7777:carol:pass123": ("gate.provider.net", 7777, "carol", "pass123"),
      "198.51.100.9:1080": ("198.51.100.9", 1080, "", "")}
for t, want in OK.items():
    sk, err = P.parse_socks_text(t)
    check("accepted: %s" % t, not err and (sk["host"], sk["port"], sk["user"], sk["pass"]) == want, (sk, err))
for t, want in {"gw.example.com:1080:user:Summer%2024": ("gw.example.com", 1080, "user", "Summer%2024"),
                "gw.example.com:1080:user:pa:ss@x": ("gw.example.com", 1080, "user", "pa:ss@x"),
                "myuser:pw:proxy.example.com:1080": ("proxy.example.com", 1080, "myuser", "pw"),
                "gw.example.com:1080:user:ab::cd": ("gw.example.com", 1080, "user", "ab::cd"),           # verify F51
                "proxy:1080:user:pass": ("proxy", 1080, "user", "pass")}.items():                         # verify F52
    sk, err = P.parse_socks_text(t)
    check("a dashboard form, taken as shown (no %%-decoding outside a URL, ':' and '@' in the password, user:pass:host:port) — F20/F21: %s" % t,
          not err and (sk["host"], sk["port"], sk["user"], sk["pass"]) == want, (sk, err))
for t in ("1.2.3.4:1080:me@mail.com:1234", "gw.example.com:1080:user:secret@x:12", "john.smith:9999:1.2.3.4:1080",
          "my.user:123:x@gw.example.com:1080", "myuser:48213:proxy.example.com:1080"):
    sk, err = P.parse_socks_text(t)
    check("⚠️ a paste that reads as two different proxies is refused, never guessed (a guess sends the login elsewhere) — verify F53 F61–F63: %s" % t,
          sk is None and "more than one way" in err, (sk, err))
for t in ("http://proxy.example:8080", "https://u:p@proxy.example:443", "socks4://proxy.example:1080"):
    sk, err = P.parse_socks_text(t)
    check("refused with the SOCKS5-only sentence: %s" % t, sk is None and "SOCKS5 only" in err, err)
for t in ("[2001:db8::1]:1080", "2001:db8::1:1080", "socks5://[2001:db8::2]:1080", "u:p@[2001:db8::3]:1080",
          "[2001:db8:0:0:0:0:0:1]:1080", "u:p@[2001:db8:1:2:3:4:5:6]:1080"):
    sk, err = P.parse_socks_text(t)
    check("an IPv6 literal is refused (exits are IPv4): %s" % t, sk is None and "IPv6" in err, err)
for t in ("proxy.example", "proxy.example:0", "proxy.example:70000", "a b:1080", ":pw@host.example:1080"):
    check("malformed, refused: %r" % t, P.parse_socks_text(t)[0] is None, P.parse_socks_text(t))

# ── [2] the password ────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the password is write-only")
KEPT = {"host": "proxy.example", "port": 1080, "user": "alice", "pass": "old", "salt": "s"}
R_ = lambda t, pw: (P.socks_resolve(t, pw, KEPT)[0] or {}).get("pass")
check("nothing pasted, nothing typed: the stored proxy and password", R_("", None) == "old" and R_("", P.EXIT_PASS_KEEP) == "old")
check("a typed password replaces it — with the address untouched too", R_("", "new") == "new")
check("re-pasting the same login without a password keeps the stored one", R_("alice@proxy.example:1080", P.EXIT_PASS_KEEP) == "old")
check("a password in the paste wins over the field", R_("alice:pasted@proxy.example:1080", "typed") == "pasted")
check("⚠️ a DIFFERENT user never inherits the stored password — and \"keep it\" is refused, not silently dropped (F2)",
      P.socks_resolve("mallory@proxy.example:1080", P.EXIT_PASS_KEEP, KEPT)[0] is None
      and "type its password again" in P.socks_resolve("mallory@proxy.example:1080", P.EXIT_PASS_KEEP, KEPT)[1])
check("⚠️ the stored password never goes to ANOTHER HOST that shares the user name (a Test would send it there) — F10",
      P.socks_resolve("alice@attacker.example:1080", P.EXIT_PASS_KEEP, KEPT)[0] is None
      and (P.socks_resolve("alice@attacker.example:1080", None, KEPT)[0] or {}).get("pass") == "")
check("a password without a user is refused", P.socks_resolve("proxy.example:1080", "x", {})[0] is None)

# ── a real panel process ────────────────────────────────────────────────────────────────────────────────────────────────────
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
NIDS = ("n11", "nold")
json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in NIDS}, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
PORT = free_port()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    try:
        return code, json.loads(raw or b"{}")
    except Exception:
        return code, {"raw": raw[:200]}


try:
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in NIDS}
    KINDS = {"n11": ["warp", "profile", "socks5"], "nold": None}
    TEST_ANSWER = {}
    def snap(nid):
        s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}, "exits": []}
        if KINDS[nid]:
            s["exit_kinds"] = KINDS[nid]
        if TEST_ANSWER.get(nid):
            s["exit_test"] = TEST_ANSWER[nid]
        return s
    def sync(nid):
        code, r = req("/api/node/sync", {"snapshot": snap(nid)}, TOK[nid])
        assert code == 200, (code, r)
        return r
    def stored(nid):
        return json.load(open(NODES))[nid].get("exits") or []
    def state_exits(nid):
        _c, r = req("/api/state")
        return next((n for n in (r.get("data") or {}).get("nodes") or [] if n["id"] == nid), {}).get("exits") or []
    def plant(nid, exits):
        n = json.load(open(NODES)); n[nid]["exits"] = exits
        with open(NODES + ".tmp", "w") as f:
            json.dump(n, f)
        os.replace(NODES + ".tmp", NODES)
    for n in NIDS:
        sync(n)

    # ── [3] a save ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[3] a save, through the panel")
    NEW = {"id": "5a5a5a5a", "producer": "imported", "provider": "socks5", "label": "", "enabled": True, "killswitch": False,
           "socks_text": "alice:hunter2@proxy.example:1080", "socks_pass": "", "licence": "xx", "dial_src": "198.51.100.1"}
    code, r = req("/api/nodes/update", {"id": "n11", "exits": [NEW]})
    x = next((e for e in stored("n11") if e.get("id") == "5a5a5a5a"), {})
    check("saved on a node that can run it", code == 200 and x.get("provider") == "socks5", (code, r))
    check("…its device is s5x-<id>", x.get("device") == "s5x-5a5a5a5a", x.get("device"))
    check("…holding the proxy, its password and a salt of its own", (x.get("socks") or {}).get("pass") == "hunter2"
          and (x.get("socks") or {}).get("host") == "proxy.example" and len((x.get("socks") or {}).get("salt") or "") == 16, x)
    check("…and no licence or dial source (they mean nothing for a proxy)", x.get("licence") == "" and x.get("dial_src") == "", x)
    sig1 = x.get("cfg_sig")
    req("/api/nodes/update", {"id": "n11", "exits": [dict(x, socks_text="", socks_pass=P.EXIT_PASS_KEEP)]})
    x2 = next(e for e in stored("n11") if e.get("id") == "5a5a5a5a")
    check("a save that changes nothing keeps the signature (and the salt)", x2.get("cfg_sig") == sig1
          and x2["socks"]["salt"] == x["socks"]["salt"], (sig1, x2.get("cfg_sig")))
    req("/api/nodes/update", {"id": "n11", "exits": [dict(x2, socks_text="", socks_pass="hunter3")]})
    x3 = next(e for e in stored("n11") if e.get("id") == "5a5a5a5a")
    check("a new password changes the signature (so the node re-applies it)", x3["socks"]["pass"] == "hunter3"
          and x3.get("cfg_sig") != sig1, (x3.get("cfg_sig"), sig1))
    _sp = dict(x3["socks"], salt="")
    _brute = hashlib.sha256(json.dumps(dict({"device": x3["device"], "provider": "socks5", "licence": "", "dial_src": "",
                                              "down": False, "profile": {}}, socks=P._socks_sig_part(_sp)),
                                       sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
    check("⚠️ the signature cannot be rebuilt from a guessed password without the server's salt", _brute != x3.get("cfg_sig"),
          (_brute, x3.get("cfg_sig")))

    # ── [4] F17 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[4] a node that cannot run a SOCKS exit (s9a F17)")
    code, r = req("/api/nodes/update", {"id": "nold", "exits": [dict(NEW, id="6b6b6b6b")]})
    check("a new SOCKS exit on it is refused, saying to update the node", code == 400 and "update the node" in str(r.get("error")),
          (code, r))
    check("…and nothing is stored", not stored("nold"), stored("nold"))
    plant("nold", [dict(x3, id="6b6b6b6b", device="s5x-6b6b6b6b")])   # one stored anyway (a node rolled back after the save)
    rep = sync("nold")
    check("⚠️ it is never SENT one (an older node registered a WARP account for any kind but `profile`)",
          not any(e.get("provider") == "socks5" for e in rep.get("exits") or []), rep.get("exits"))
    check("…its row says why (`kind_unsupported`, worded by the SPA)",
          next((e for e in state_exits("nold") if e.get("id") == "6b6b6b6b"), {}).get("why_not") == "kind_unsupported",
          state_exits("nold"))
    rep = sync("n11")
    w = next((e for e in rep.get("exits") or [] if e.get("id") == "5a5a5a5a"), {})
    check("a node that lists socks5 is sent it, with the proxy and its password (over TLS, as a profile's key)",
          (w.get("socks") or {}).get("pass") == "hunter3" and w.get("device") == "s5x-5a5a5a5a", w)

    try:
        _f6 = P.exit_kind_refusal({"exit_kinds": 1}, "socks5") is not None
    except Exception:
        _f6 = False                                  # a crash is the defect itself
    check("a node reporting `exit_kinds` that is not a list is refused, never a crash — F6",
          _f6 and P._SNAP_SHAPE.get("exit_kinds") == (list, str))
    plant("nold", [dict(x3, id="6b6b6b6b", device="s5x-6b6b6b6b"),
                   {"id": "7c7c7c7c", "producer": "imported", "provider": "vless9", "device": "wgx-7c7c7c7c", "label": "", "enabled": True,
                    "killswitch": False, "cfg_sig": "x"}])
    rep = sync("nold")
    check("an UNKNOWN kind (a newer panel's) is still sent — the node refuses it and keeps its record; withheld, it would be reaped — F28",
          any(e.get("provider") == "vless9" for e in rep.get("exits") or []) and not any(e.get("provider") == "socks5" for e in rep.get("exits") or []),
          rep.get("exits"))

    # ── [5] T7 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[5] the password reaches the node and nobody else")
    check("the sync reply never carries the salt", "salt" not in (w.get("socks") or {}), w.get("socks"))
    sx = next((e for e in state_exits("n11") if e.get("id") == "5a5a5a5a"), {})
    _c, _whole = req("/api/state")
    check("⚠️ /api/state carries neither the password nor its salt (T7)", "hunter3" not in json.dumps(_whole)
          and x3["socks"]["salt"] not in json.dumps(_whole), sx.get("socks"))
    check("…only that one is kept (`has_pass`)", sx.get("socks") == {"host": "proxy.example", "port": 1080, "user": "alice",
                                                                    "has_pass": True}, sx.get("socks"))
    _kept, _ = P._fp_prune({"exits": [x3]}, P._FP_EXCLUDE_PATS)
    _m = json.dumps(P._fp_mask(_kept))
    _h = hashlib.sha256(b"exit_socks_pass\0hunter3").hexdigest()[:16]
    check("the fingerprint carries neither the password nor any digest of it (an unsalted one falls to a word list) — F26",
          "hunter3" not in _m and _h not in _m and x3["socks"]["salt"] not in _m and '"host": "proxy.example"' in _m, _m[:300])
    _tc, _tb = P.transfer_strip({"id": "n11", "exits": [x3]})
    check("⚠️ a transfer moves the proxy's password and salt with the record — the exit keeps working on panel B — F46",
          ((_tc.get("exits") or [{}])[0].get("socks") or {}).get("pass") == "hunter3"
          and ((_tc.get("exits") or [{}])[0].get("socks") or {}).get("salt") == x3["socks"]["salt"], _tc.get("exits"))

    # ── [6] D-c ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[6] a SOCKS exit is not a tunnel edited")
    code, r = req("/api/nodes/update", {"id": "n11", "exits": [dict(x3, provider="warp", socks_text="", socks_pass="")]})
    check("turning it into a WARP exit is refused", code == 400 and "cannot change" in str(r.get("error")), (code, r))
    check("…and it is still the SOCKS exit it was", next(e for e in stored("n11") if e["id"] == "5a5a5a5a").get("provider") == "socks5")

    # ── [8] the Test ────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[8] the Test button, round trip")
    code, r = req("/api/exit/test", {"node": "nold", "socks_text": "198.51.100.9:1080"})
    check("a node that cannot run one is refused", code == 400 and r.get("code") == "unsupported", (code, r))
    code, r = req("/api/exit/test", {"node": "n11", "exit_id": "5a5a5a5a", "socks_text": "", "socks_pass": P.EXIT_PASS_KEEP})
    tid = (r.get("data") or {}).get("id")
    check("armed on the stored exit (its password from the store)", code == 200 and (r.get("data") or {}).get("state") == "pending", (code, r))
    code2, r2 = req("/api/exit/test", {"node": "n11", "socks_text": "198.51.100.9:1080"})
    check("a second while it runs is busy", code2 == 409 and r2.get("code") == "busy", (code2, r2))
    rep = sync("n11")
    check("the node is sent it, the stored password with it", (rep.get("exit_test") or {}).get("id") == tid
          and (rep.get("exit_test") or {}).get("pass") == "hunter3", rep.get("exit_test"))
    TEST_ANSWER["n11"] = {"id": tid, "login": True, "egress_ip": "203.0.113.5", "loc": "DE", "udp": False, "rtt_ms": 230, "why": ""}
    rep = sync("n11")
    _c, r = req("/api/exit/test", {"node": "n11", "id": tid})
    res = (r.get("data") or {}).get("result") or {}
    check("its answer is absorbed and readable", (r.get("data") or {}).get("state") == "done" and res.get("egress_ip") == "203.0.113.5"
          and res.get("udp") is False, r)
    check("⚠️ once answered the reply stops carrying it — and its password", "exit_test" not in rep, rep.get("exit_test"))
    TEST_ANSWER.clear()
    rep = sync("n11")
    check("…on every later sync too", "exit_test" not in rep)
except Exception as _e:                               # a section that raises is a red check, never a silent stop
    check("the panel sections ran to their end", False, repr(_e)[:200])
finally:
    proc.terminate()
    with __import__("contextlib").suppress(Exception):
        proc.wait(5)

# ── [7] the mirror (in this process: the store is a temp dir, curl a stand-in) ─────────────────────────────────────────────
print("\n[7] the mirror serves the pinned hev or nothing")
P.TURN_BINS_DIR = os.path.join(TMP, "bins")
GOOD, BAD = b"\x7fELF-pinned", b"\x7fELF-other"
P.HEV_SHA256 = dict(P.HEV_SHA256, amd64=hashlib.sha256(GOOD).hexdigest())
_real_run = P.subprocess.run
def _curl(argv, **k):
    open(argv[argv.index("-o") + 1], "wb").write(_CURL["v"])
    return subprocess.CompletedProcess(argv, 0, "", "")
_CURL = {"v": BAD}
P.subprocess.run = _curl
P._HEV_MIRROR_FAIL.clear()
check("a download that is not the pin is never kept", P.hev_mirror_file("amd64") == "")
_CURL["v"] = GOOD
P._HEV_MIRROR_FAIL.clear()
d = P.hev_mirror_file("amd64")
check("the pinned one is", d and open(d, "rb").read() == GOOD, d)
open(d, "wb").write(BAD)
_CURL["v"] = BAD
P._HEV_MIRROR_FAIL.clear()
check("⚠️ a file in the store that is not the pin (put there, or changed) is deleted, never served",
      P.hev_mirror_file("amd64") == "" and not os.path.exists(d))
check("an arch with no build has nothing", P.hev_mirror_file("riscv64") == "")
# F5: nodes asking at once on a cold store — one download, every one of them served
import threading as _th
with __import__("contextlib").suppress(OSError):
    os.remove(d)
_curls = []
def _slow(argv, **k):
    _curls.append(1); time.sleep(0.5); return _curl(argv, **k)
_CURL["v"] = GOOD
P.subprocess.run = _slow
P._HEV_MIRROR_FAIL.clear()
_got = []
_ts = [_th.Thread(target=lambda: _got.append(P.hev_mirror_file("amd64"))) for _ in range(3)]
[t.start() for t in _ts]; [t.join(10) for t in _ts]
check("three nodes fetching at once on a cold mirror: one download, all three served — F5",
      len(_curls) == 1 and len(_got) == 3 and all(g and open(g, "rb").read() == GOOD for g in _got), (_curls, _got))
# verify F48: a panel that cannot reach GitHub does not run a failing fetch for every node in the queue
with __import__("contextlib").suppress(OSError):
    os.remove(_got[0])
_curls.clear(); _CURL["v"] = BAD; P._HEV_MIRROR_FAIL.clear()
P.hev_mirror_file("amd64"); P.hev_mirror_file("amd64"); P.hev_mirror_file("amd64")
check("after a failed fetch the mirror answers at once for ten minutes (no ~200 s fetch per queued node) — verify F48",
      len(_curls) == 1, _curls)
P.subprocess.run = _real_run

print("\n[8b] a test's password does not outlive the test (in this process)")
st_, _r = P.exit_test_request("nx", "", {"host": "h", "port": 1, "user": "u", "pass": "pw-x"},
                              {"exit_kinds": ["socks5"], "x": 1}, 1, 30, now=1000.0)
P.exit_test_reply("nx", now=1001.0)
check("a pending test holds the password it was armed with", P._EXIT_TESTS["nx"]["socks"].get("pass") == "pw-x")
check("…and drops it the moment the test expires unanswered", P.exit_test_reply("nx", now=1000.0 + P.EXIT_TEST_TTL + 1) is None
      and P._EXIT_TESTS["nx"]["socks"] == {}, P._EXIT_TESTS["nx"])
P.exit_test_request("ny", "", {"host": "h", "port": 1, "user": "u", "pass": "pw-y"}, {"exit_kinds": ["socks5"]}, 1, 30, now=2000.0)
P.exit_test_status("ny", now=2000.0 + P.EXIT_TEST_TTL + 1)
check("…whoever notices the expiry first — a status read too, with the node gone dark — F27", P._EXIT_TESTS["ny"]["socks"] == {}, P._EXIT_TESTS["ny"])
shutil.rmtree(TMP, ignore_errors=True)

print()
if MODE:
    print(("perturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS))) if FAILS
          else "perturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(0 if FAILS else 1)
print(("FAILED: " + "; ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
