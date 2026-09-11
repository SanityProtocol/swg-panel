#!/usr/bin/env python3
"""Self-test for the IMPORTED exit arm — the exits the node CREATES (WARP registration / a pasted profile).

Two properties here can lose a node or leak a secret, so they are asserted rather than assumed:

  §5.1  `Table = off` in every conf we write. A WARP profile carries `AllowedIPs = 0.0.0.0/0`; without that
        line `wg-quick up` installs a second default route plus a policy rule and the box's OWN traffic —
        the SSH session, the panel's inbound — is routed into the tunnel. Measured both ways on a live box:
        with it, four commands and no route; without it, `0.0.0.0/0 dev <D> table 51820` and two defaults.

  keys  A WARP private key is generated on the node and must never travel (decision 8). A PASTED profile's
        key must travel panel→node — the node cannot invent it — but must never reach a BROWSER.

Hermetic: no network, no wg, no iptables. `run()` is stubbed and the registration API is faked.

Run: python3 tests/imported_exit_selftest.py (0 = pass)
     --perturb  drops `Table = off` from the conf writer, which is how a node gets lost, and expects RED.
"""
import importlib.machinery, importlib.util, json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

N, P = _load(NODED, "swgnoded"), _load(PANEL, "swgpanel")
# Captured BEFORE anything stubs it: the lifecycle checks below replace `_warp_register` with a fake, which
# is right for them and is precisely how the real one went untested until it shipped broken.
_REAL_WARP_REGISTER = N._warp_register
if PERTURB:
    _orig = N._exit_conf_text
    N._exit_conf_text = lambda rec: _orig(rec).replace("Table = off\n", "")

class _R:
    def __init__(s, out="", rc=0): s.stdout, s.stderr, s.returncode = out, "", rc

WARP = {"priv": "cHJpdmF0ZS1rZXktcHJpdmF0ZS1rZXktcHJpdmF0ZS0=", "pub": "cHVia2V5LXB1YmtleS1wdWJrZXktcHVia2V5LXB1Yms=",
        "address": "172.16.0.2", "peer_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
        "endpoint": "engage.cloudflareclient.com:2408", "account_id": "acc", "token": "tok",
        "licence": "LIC", "account_type": "free"}

def lower(desired, up="absent"):
    calls = []
    N.EXIT_DIR = tempfile.mkdtemp()
    N.run = lambda a, **k: (calls.append(" ".join(map(str, a))), _R(""))[1]
    # The REAL transition: absent until the bring-up runs, up afterwards. A fixture that says "absent"
    # throughout never reaches the health probe, and the health probe is half the point.
    #
    # ⚠️ KEYED ON THE BRING-UP HAVING HAPPENED, not on how many times the reconciler ASKS. It counted reads
    # ("absent for the first two, up after") and therefore encoded the caller's call pattern as if it were a
    # fact about the device: reading the state once and reusing it — which is both correct and three fewer
    # `ip` invocations per exit per sync — moved the boundary and this fixture reported a working bring-up as
    # broken. A stub that models STATE survives a caller that gets cheaper.
    def _st(dev):
        if up != "absent":
            return up
        return "up" if any(" up " in c for c in calls) else "absent"
    N._dev_link_state = _st
    N._exit_trace = lambda d: {"ip": "104.28.222.16", "warp": "on", "loc": "FI"}
    N._warp_register = lambda: (dict(WARP), "")
    res = {"changed": 0, "errors": []}
    N.reconcile_exits(desired, res)
    return calls, res, N.EXIT_DIR

# ── 1. §5.1 — the line that keeps the box reachable ──────────────────────────────────────────────
calls, res, d = lower([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp"}])
conf = open(os.path.join(d, "wgx-aabbccdd.conf")).read()
check("§5.1: the conf we write carries `Table = off`", "Table = off" in conf, conf)
check("…and AllowedIPs really is the whole internet, which is WHY it matters",
      "AllowedIPs = 0.0.0.0/0" in conf, conf)
check("decision 6: no IPv6 anywhere in the conf", "::" not in conf, conf)
check("the device is brought up from the node's OWN state dir, not /etc/wireguard",
      any(c.startswith("wg-quick up ") and d in c for c in calls), calls)

# ── 2. secrets ───────────────────────────────────────────────────────────────────────────────────
rep = N._EXITS["list"]
blob = json.dumps(rep)
check("a WARP private key never reaches the snapshot the panel reads",
      WARP["priv"] not in blob, rep)
check("…but the public half, address and health do (the panel has to render something)",
      rep and rep[0].get("public_key") == WARP["pub"] and rep[0]["trace"]["warp"] == "on", rep)
check("the key is stored 0600 on the node", oct(os.stat(os.path.join(d, "aabbccdd.json")).st_mode)[-3:] == "600")

# ── 3. the pasted profile: read, don't trust ─────────────────────────────────────────────────────
PROF = ("[Interface]\nPrivateKey = aGVsbG8taGVsbG8taGVsbG8taGVsbG8taGVsbG8taGU=\n"
        "Address = 10.9.0.2/32, fd00::1/128\nMTU = 1420\nPostUp = rm -rf /\n\n[Peer]\n"
        "PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=\nAllowedIPs = 0.0.0.0/0, ::/0\n"
        "Endpoint = vps.example.com:51820\n")
pr, err = P.parse_wg_profile(PROF)
check("a pasted profile parses", not err and pr["address"] == "10.9.0.2", (pr, err))
check("its v6 Address half is dropped at the door", ":" not in pr["address"], pr)
check("⚠️ PostUp is never carried — it is root command execution from a stranger's file",
      "rm -rf" not in json.dumps(pr), pr)
for bad, why in [("garbage", "no key"), (PROF.replace("Address = 10.9.0.2/32, fd00::1/128", "Address = fd00::1/128"), "v6 only"),
                 (PROF.replace("Endpoint = vps.example.com:51820", ""), "no endpoint")]:
    check("a profile with %s is refused WITH A SENTENCE" % why, bool(P.parse_wg_profile(bad)[1]))

# ── 4. the panel: it owns the device name, and only imported exits go on the wire ────────────────
ex, verr = P._validate_exits([
    {"id": "aabbccdd", "label": "WARP", "producer": "imported", "provider": "warp", "licence": " KEY-1 "},
    {"id": "11223344", "producer": "imported", "provider": "profile", "profile_text": PROF},
    {"id": "99887766", "producer": "adopted", "device": "wgcf"}], {"name": "n1"}, nics=["eth0"])
check("the validator accepts all three producers", not verr, verr)
check("an imported exit's device is MINTED from its id, never typed",
      ex[0]["device"] == "wgx-aabbccdd" and ex[1]["device"] == "wgx-11223344", [e["device"] for e in ex])
check("…and not under the mesh prefix, which the refusal set would reject",
      not any(e["device"].startswith("swg_") for e in ex[:2]))
check("the WARP+ licence is kept, trimmed", ex[0]["licence"] == "KEY-1", ex[0])
check("a re-save that does not re-paste keeps the stored profile",
      (P._validate_exits([{"id": "11223344", "producer": "imported", "provider": "profile"}],
                         {"name": "n1"}, prev=ex)[0][0].get("profile") or {}).get("address") == "10.9.0.2")
check("a re-save with NO stored profile and no paste is refused",
      bool(P._validate_exits([{"id": "aaaa1111", "producer": "imported", "provider": "profile"}], {"name": "n1"})[1]))

src = open(PANEL, encoding="utf-8").read()
m = re.search(r'"exits": \[\{"id": x\.get\("id"\).*?\],', src, re.S)
check("the wire payload was found", bool(m))
wire = m.group(0) if m else ""
check("only IMPORTED exits are sent to the node", 'x.get("producer") == "imported"' in wire, wire[:200])
check("no WARP private key is on the wire — the node generates and keeps it",
      "private_key" not in wire and "priv" not in wire, wire[:200])
_state = re.search(r'"exits": \[dict\(\{k: v for k, v in e\.items\(\).*?\],', src, re.S)
check("/api/state strips a pasted profile's private key before it reaches a browser",
      bool(_state) and 'k2 != "private_key"' in _state.group(0), (_state.group(0)[:200] if _state else ""))

# ── 4b. ⚠️ AN IMPORTED EXIT MUST NOT BE REFUSED BY THE SET THAT PROTECTS IT ──────────────────────
# The `imported` refusal exists to stop an ADOPTED exit pointing at a tunnel another exit owns. Applied to
# the imported exit ITSELF it is self-refusal: cascade_plan drops it (so the arm never routes at all) and
# /api/state tells the operator their own exit's device is unusable. Both shipped for twenty minutes and
# were found by RENDERING the row, not by any test — hence this one.
_inode = {"name": "n1", "links": {},
          "exits": [{"id": "aabbccdd", "producer": "imported", "provider": "warp",
                     "device": "wgx-aabbccdd", "enabled": True, "killswitch": True}],
          "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": "aabbccdd"}}}
_isnap = {"n1": {"ether_ifaces": ["eth0"], "interfaces": {"awg0": {"meta": {"subnet": "10.17.0.0/24"}}}}}
_ip = (P.cascade_plan({"n1": _inode}, _isnap).get("n1") or {}).get("devexit") or []
check("an imported exit LOWERS — it does not refuse its own minted device",
      len(_ip) == 1 and _ip[0]["dev"] == "wgx-aabbccdd", _ip)
check("…while an ADOPTED exit pointing at that same tunnel is still refused",
      P.exit_device_refusal(_inode, "wgx-aabbccdd") == "imported")
check("…and /api/state exempts it too, so the row does not call its own device unusable",
      "_exr2" in open(PANEL, encoding="utf-8").read())

# ── 4c. ⚠️ "ACTIVE" MUST BE A PAUSE, NOT A DESTROY ───────────────────────────────────────────────
# Filtering a disabled exit off the wire made the node's REAP fire on it — tunnel down AND key deleted,
# which for a WARP exit is the ACCOUNT. Re-enabling would have registered a fresh one with a different
# egress IP, while the row promised the selection was kept. Decision 3 says disabling degrades; it does not
# say it discards.
_d2 = tempfile.mkdtemp()
N.EXIT_DIR = _d2
N._dev_link_state = lambda dev: "absent"
N.run = lambda a, **k: _R("")
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp"}], {"changed": 0, "errors": []})
_keyfile = os.path.join(_d2, "aabbccdd.json")
check("a live imported exit has key material on the node", os.path.exists(_keyfile))
_before = open(_keyfile).read()
calls3 = []
N._dev_link_state = lambda dev: "up"
N.run = lambda a, **k: (calls3.append(" ".join(map(str, a))), _R(""))[1]
res3 = {"changed": 0, "errors": []}
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp", "down": True}], res3)
check("switching it OFF takes the device down", any(c.startswith("wg-quick down") for c in calls3), calls3)
check("…and KEEPS the key — the WARP account survives a pause",
      os.path.exists(_keyfile) and open(_keyfile).read() == _before)
check("…and says so, rather than reporting a broken exit",
      N._EXITS["list"] and N._EXITS["list"][0].get("paused") is True and not N._EXITS["list"][0].get("error"),
      N._EXITS["list"])
# switched off before it ever came up: do NOT register an account for something nobody enabled
_d3 = tempfile.mkdtemp(); N.EXIT_DIR = _d3
N._warp_register = lambda: (_ for _ in ()).throw(AssertionError("registered a DISABLED exit"))
N.reconcile_exits([{"id": "eeeeeeee", "device": "wgx-eeeeeeee", "provider": "warp", "down": True}],
                  {"changed": 0, "errors": []})
check("an exit that was never enabled is never registered", not os.listdir(_d3), os.listdir(_d3))
N._warp_register = lambda: (dict(WARP), "")
N.EXIT_DIR = d

# and the WIRE has to carry the disabled one, or none of the above can happen
_wire = re.search(r'"exits": \[\{"id": x\.get\("id"\).*?\],', open(PANEL, encoding="utf-8").read(), re.S).group(0)
check("a disabled exit is still SENT, carrying `down`", '"down": x.get("enabled", True) is False' in _wire)
check("…and is no longer filtered off the wire (which is what made the reap fire)",
      'and x.get("enabled", True) is not False' not in _wire, _wire[-160:])

# ── 4d. DECISION 4, REWRITTEN — the node owns the default, and AUTO is what inherits it ─────────
# The first build made it a per-exit "default for new interfaces" radio: a creation seed with different
# semantics from every control beside it. `default_egress_ip` has always been LIVE, node-wide and beaten by
# any interface that chose for itself — so the way out is the same ladder on the other axis, and the seed
# is unnecessary: an interface inherits by NOT choosing.
_EX = [{"id": "aaaaaaaa", "producer": "imported", "provider": "warp", "device": "wgx-aaaaaaaa", "enabled": True},
       {"id": "bbbbbbbb", "producer": "adopted", "device": "wgvps", "enabled": True}]
def _dplan(default_exit, fwd_ip="", fwd_nic=""):
    nodes = {"n1": {"name": "n1", "links": {"n2": {"iface": "swg_a"}},
                    "ifaces": {"awg9": {"egress_mode": "forward", "egress_node": "n2",
                                        "egress_ip": fwd_ip, "wan_iface": fwd_nic}}},
             "n2": {"name": "n2", "links": {"n1": {"iface": "swg_b", "peer_address": "10.255.0.1"}},
                    "default_exit": default_exit, "exits": _EX,
                    "ifaces": {"awg0": {},                                             # AUTO
                               "awg1": {"egress_mode": "direct", "wan_iface": "eth0"},  # pinned NIC
                               "awg2": {"egress_mode": "direct", "egress_ip": "203.0.113.9"},   # pinned IP
                               "awg3": {"egress_mode": "exit", "exit_id": "bbbbbbbb"}}}}   # own exit
    snaps = {"n1": {"ether_ifaces": ["eth0"], "interfaces": {"awg9": {"meta": {"subnet": "10.99.0.0/24"}}}},
             "n2": {"ether_ifaces": ["eth0"], "interfaces": {
                 "awg0": {"meta": {"subnet": "10.10.0.0/24"}}, "awg1": {"meta": {"subnet": "10.11.0.0/24"}},
                 "awg2": {"meta": {"subnet": "10.12.0.0/24"}}, "awg3": {"meta": {"subnet": "10.13.0.0/24"}}}}}
    return dict((e["subnet"], e["dev"]) for e in ((P.cascade_plan(nodes, snaps).get("n2") or {}).get("devexit") or []))
_d = _dplan("aaaaaaaa")
check("an AUTO interface inherits the node's default exit", _d.get("10.10.0.0/24") == "wgx-aaaaaaaa", _d)
check("an interface pinned to a NIC keeps its NIC — an explicit WHERE is not a gap to fill",
      "10.11.0.0/24" not in _d, _d)
check("an interface pinned to an IP is untouched too", "10.12.0.0/24" not in _d, _d)
check("an interface that picked its OWN exit keeps it", _d.get("10.13.0.0/24") == "wgvps", _d)
# decision 4's other half — the one the plan warns is easy to miss
check("traffic cascaded in from another node leaves by THIS node's default",
      _d.get("10.99.0.0/24") == "wgx-aaaaaaaa", _d)
check("…unless the forwarding interface pinned an egress IP, which is an explicit choice about the far end",
      "10.99.0.0/24" not in _dplan("aaaaaaaa", fwd_ip="203.0.113.9"))
check("…or pinned a WAN NIC there", "10.99.0.0/24" not in _dplan("aaaaaaaa", fwd_nic="eth0"))
_n = _dplan("")
check("with no node default, only explicit choices lower", set(_n) == {"10.13.0.0/24"}, _n)
# and the node-level field is validated against the node's OWN exits
check("a default_exit naming an exit this node does not have is refused",
      "default_exit" in open(PANEL, encoding="utf-8").read())

# ── 4d-bis. ⚠️ THE REAL `_warp_register`, NOT A STUB ────────────────────────────────────────────
# Every other check here replaces `_warp_register` with a fake, which is right for testing the lifecycle
# around it — and is exactly why the one function that talks to the outside world was never exercised. It
# called `_warp_api` without a method, `_warp_api` defaulted to GET, and a GET to /reg is a 404: every
# registration the feature ever attempted was malformed. It shipped, deployed to four nodes, and was found
# by an operator asking "why 404?". So this one drives the REAL function with only the socket replaced.
_req = {}
class _Resp:
    status = 200
    def read(s2): return json.dumps({
        "id": "acc", "token": "tok", "account": {"license": "LIC", "account_type": "free"},
        "config": {"peers": [{"public_key": "PEER", "endpoint": {"host": "engage.cloudflareclient.com:2408"}}],
                   "interface": {"addresses": {"v4": "172.16.0.2", "v6": "2606::1"}}}}).encode()
    def __enter__(s2): return s2
    def __exit__(s2, *a2): return False
import urllib.request as _u
_real_open = _u.urlopen
_u.urlopen = lambda req, **kw: (_req.update({"method": req.get_method(), "url": req.full_url,
                                             "body": json.loads(req.data.decode()),
                                             "hdrs": dict(req.header_items())}), _Resp())[1]
N.run = lambda a, **k: _R("aGVsbG8taGVsbG8taGVsbG8taGVsbG8taGVsbG8taGU=")
_reg, _rerr = _REAL_WARP_REGISTER()
_u.urlopen = _real_open
check("registration is a POST — the default GET is a 404 and nothing else would say so",
      _req.get("method") == "POST", _req.get("method"))
check("…to /v0a2158/reg", str(_req.get("url", "")).endswith("/v0a2158/reg"), _req.get("url"))
check("…carrying the public key, not the private one",
      _req.get("body", {}).get("key") and "PrivateKey" not in json.dumps(_req.get("body")), _req.get("body"))
check("…with the client headers Cloudflare expects",
      "Cf-client-version" in _req.get("hdrs", {}) or "CF-Client-Version" in _req.get("hdrs", {}), _req.get("hdrs"))
check("…and the reply is parsed into the profile the conf needs",
      not _rerr and _reg and _reg["address"] == "172.16.0.2" and _reg["peer_key"] == "PEER"
      and _reg["account_id"] == "acc", (_reg, _rerr))
check("…v6 is dropped right here, not later", "2606" not in json.dumps(_reg), _reg)
N._warp_register = lambda: (dict(WARP), "")

# ── 4e. ⚠️ A FAILED REGISTRATION MUST BACK OFF ──────────────────────────────────────────────────
# reconcile_exits runs every sync (5s) and registration is a one-shot call to somebody else's free API.
# Without a delay one failure is retried ~17,000 times a day from a single IP. Measured on a live node:
# Cloudflare answered 429 `error code: 1015` and the exit could then never register at all — the retry
# storm was not merely rude, it was self-defeating.
_d4 = tempfile.mkdtemp(); N.EXIT_DIR = _d4
N.run = lambda a, **k: _R("")
N._dev_link_state = lambda dev: "absent"
N._exit_trace = lambda dev: {}
_tries = {"n": 0}
def _failing():
    _tries["n"] += 1
    return None, "registration failed (429) error code: 1015"
N._warp_register = _failing
for _ in range(5):                                  # five syncs in a row, as the loop really would
    N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp"}], {"changed": 0, "errors": []})
check("a failing registration is attempted ONCE across five syncs, not five times",
      _tries["n"] == 1, _tries["n"])
_st = json.load(open(os.path.join(_d4, "aabbccdd.json")))
check("…the backoff is remembered in the state file, so a restart cannot reset it",
      _st.get("reg_fails") == 1 and _st.get("reg_next", 0) > 0, _st)
check("…and the operator is told what happened and when it will retry",
      (N._EXITS["list"] or [{}])[0].get("error", "").startswith("registration failed")
      and (N._EXITS["list"] or [{}])[0].get("retry_in", 0) > 0, N._EXITS["list"])
# and once it succeeds the counters must not linger
N._warp_register = lambda: (dict(WARP), "")
_st["reg_next"] = 0
open(os.path.join(_d4, "aabbccdd.json"), "w").write(json.dumps(_st))
N.reconcile_exits([{"id": "aabbccdd", "device": "wgx-aabbccdd", "provider": "warp"}], {"changed": 0, "errors": []})
_ok = json.load(open(os.path.join(_d4, "aabbccdd.json")))
check("a success clears the backoff rather than leaving a dead counter",
      not _ok.get("reg_fails") and _ok.get("priv") == WARP["priv"], _ok)
N._warp_register = lambda: (dict(WARP), "")
N.EXIT_DIR = d

# ── 5. reap: an exit the panel stopped listing takes its tunnel with it ──────────────────────────
N.EXIT_DIR = d
N._dev_link_state = lambda dev: "up"
calls2, res2 = [], {"changed": 0, "errors": []}
N.run = lambda a, **k: (calls2.append(" ".join(map(str, a))), _R(""))[1]
N.reconcile_exits([], res2)
check("a removed exit is taken DOWN, not left running unowned",
      any(c.startswith("wg-quick down") for c in calls2), calls2)
check("…and its key material is deleted with it",
      not os.path.exists(os.path.join(d, "aabbccdd.json")))

if PERTURB:
    if FAILS:
        print("\nperturbed: a conf written without `Table = off` was CAUGHT (%d red) — wg-quick would have "
              "taken the box's default route" % len(FAILS))
        sys.exit(0)
    print("\nperturbed: NOTHING FAILED — this gate does not actually test §5.1")
    sys.exit(1)

print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
