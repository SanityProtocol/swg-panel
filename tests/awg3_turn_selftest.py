#!/usr/bin/env python3
"""Self-test — AmneziaWG 3.1 and the turn proxies (docs/AWG3-PLAN.md §7.5 D-apps, gate G13).

A WINGS-N proxy's app cannot carry AmneziaWG 3.x: WINGS V (Android) pins amneziawg-android 2.0.1, which throws on any key
it does not know, and WINGS DeX (desktop) parses Jc–H4 only. The server relays UDP and does not care, so the rule is the
catalog's per-fork `awg3: False` fact, read wherever a proxy and a 3.1 interface could meet. The operator's choice
(2026-09-19): REFUSE AND NAME — never an automatic unlink, which no node can do today (an unknown turn action restarts the
proxy; a stop leaves it on the port, still offered on the subscription page). A proxy counts where the node REPORTS it or
where a pending request will put it; a re-point or delete the node has not applied yet does not clear it (a request can
expire unapplied). Driven through a REAL panel process (temp state, scratch port, no auth; the node is played by POSTing
snapshots; `curl` shimmed so no install reaches GitHub).

Node n1 reports awg0 (2.0, :51820) served by a WINGS-N proxy AND a samosvalishe proxy, awg1 (3.1, :51821), awg2 (2.0,
:51822), awg3 (2.0, :51823, its WINGS-N proxy being deleted), awg4 (2.0, :51824, a WINGS-N install pending), a WINGS-N
proxy left pointing at :51825 where no interface is, awg8/awg9 (2.0 records the node has drifted to 3.1; a WINGS-N proxy on
awg8), awg10 (3.1 with a WINGS-N proxy already on it — taken over that way) and a lost awg11 (last seen on :51833).

  [1] install — a WINGS-N proxy pointed at awg1 (3.1) is refused with the reason, nothing queued; WINGS-N at a 2.0
      interface and samosvalishe at awg1 go through
  [2] manage  — moving the WINGS-N proxy's connect onto awg1 is refused, nothing queued; a params-only edit goes through
  [3] switch  — awg0 → 3.1 (by `awg_gen`, and by an HPK in a raw dict) is a 409 naming the WINGS-N proxy and NOT the
      samosvalishe one, the record untouched; one being installed blocks (awg4); one being deleted blocks until the node
      reports it gone, then the switch goes through (awg3)
  [4] the operator re-points the WINGS-N proxy at awg2: the switch is still refused until the node reports the move, then
      it goes through
  [5] the samosvalishe proxy is the one left on awg0, and its freeturn:// link, decoded, carries the 3.1 set with
      RandomTrailers = 1 and a single keepalive `k`
  [6] a 3.1 create on :51825, where the stray WINGS-N proxy points, is refused naming it; a 2.0 create there is not
  [7] moving the 3.1 awg1 onto :51825 is refused; onto a free port it goes through
  [8] Adopting a node-side 3.1 drift is the same line: refused while a WINGS-N proxy is on awg8; awg9 adopts
  [9] a 3.1 interface created but not yet reported (:51831) already refuses a WINGS-N proxy
  [10] saves that re-send what is already there are not moves: awg10's Edit (its reported port re-sent) and its WINGS-N
      proxy's params-only Edit (its connect re-sent) go through; re-pointing that proxy at another 3.1 port does not
  [11] a lost interface is judged at the port it last had: switching awg11 is refused for the WINGS-N proxy on :51833

Run: python3 tests/awg3_turn_selftest.py                 (0 = pass; needs node for [5])
     --perturb <name>   plants one regression in a copy of the tree and expects RED on exactly its sections:
                        fact [1]–[4][6]–[11] · install [1][9] · manage [2][10] · switch [3][4][7][11] · create [6] ·
                        reported-only [3] · trust-pending [3][4] · freeturn [5] · adopt [8] · created [9] · moved [10] ·
                        manage-same [10] · lastport [11]
"""
import base64, importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

PLANTS = {   # name: (file, anchor, replacement, sections it must redden)
    "fact": ("swg-panel-server", '                     "awg3": False,\n', "",
             ["[1]", "[2]", "[3]", "[4]", "[6]", "[7]", "[8]", "[9]", "[10]", "[11]"]),
    "install": ("swg-panel-server", "        _t3 = turn_awg3_target(deps, nodes, nid, fork, connect)   # a WINGS-N proxy never serves an AmneziaWG 3.1 interface\n",
                "        _t3 = None\n", ["[1]", "[9]"]),
    "manage": ("swg-panel-server", "                        _t3 = turn_awg3_target(deps, nodes, nid, turn_fork(svc), body[k].strip())\n",
               "                        _t3 = None\n", ["[2]", "[10]"]),
    "switch": ("swg-panel-server", "            _bl = turn_awg3_blockers(deps, nodes, nid, _t3p)\n", "            _bl = []\n",
               ["[3]", "[4]", "[7]", "[11]"]),
    "create": ("swg-panel-server", "            _bl = turn_awg3_blockers(deps, nodes, nid, {req.get(\"listen_port\")})",
               "            _bl = []", ["[6]"]),
    "reported-only": ("swg-panel-server",
                      "        conns = [tp.get(\"connect\") or \"\"] + ([req[\"connect\"]] if req.get(\"action\") in (\"install\", \"manage\") and req.get(\"connect\") else [])\n",
                      "        conns = [tp.get(\"connect\") or \"\"]\n", ["[3]"]),
    "trust-pending": ("swg-panel-server",
                      "        conns = [tp.get(\"connect\") or \"\"] + ([req[\"connect\"]] if req.get(\"action\") in (\"install\", \"manage\") and req.get(\"connect\") else [])\n",
                      "        conns = [] if req.get(\"action\") == \"delete\" else [(req.get(\"connect\") if req.get(\"action\") in (\"install\", \"manage\") else None) or tp.get(\"connect\") or \"\"]\n",
                      ["[3]", "[4]"]),
    "freeturn": ("turn-artifacts.js", '      return l.trim().replace(/^(PersistentKeepalive\\s*=\\s*)(\\d+)\\s*-\\s*\\d+$/i, "$1$2");\n',
                 "      return l.trim();\n", ["[5]"]),
    "adopt": ("swg-panel-server", "                _bl = turn_awg3_blockers(deps, nodes, nid, {ov.get(\"listen_port\") or _rm.get(\"listen_port\"), _rm.get(\"listen_port\")})\n",
              "                _bl = []\n", ["[8]"]),
    "created": ("swg-panel-server", ', str(mk.get("listen_port") or ""))', ')', ["[9]"]),
    "moved": ("swg-panel-server", "                    else ({_lp(ov)} if str(_lp(ov)) != str(_lp(_was)) else set()))",
              "                    else ({_lp(ov)} if ov.get(\"listen_port\") != _was.get(\"listen_port\") else set()))", ["[10]"]),
    "manage-same": ("swg-panel-server",
                    "                    elif _port_of(body[k].strip()) != _port_of(turn_connect_now(deps, nodes, nid, svc)):",
                    "                    elif True:", ["[10]"]),
    "lastport": ("swg-panel-server", "                             or (r.get(\"_lastcfg\") or {}).get(\"listen_port\"))",
                 "                             or None)", ["[11]"]),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="awg3-turn-")
TREE = ROOT
if MODE:
    f, old, new, _ = PLANTS[MODE]
    TREE = os.path.join(TMP, "tree")
    for d in ("js", "vendor"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(TREE, d))
    os.makedirs(os.path.join(TREE, "tests"))
    for n in ("tests/spa_env.mjs", "tests/spa_hooks.mjs", "reconcile.js", "turn-artifacts.js", "swg-panel-server", "VERSION"):
        if os.path.exists(os.path.join(ROOT, n)):
            shutil.copy2(os.path.join(ROOT, n), os.path.join(TREE, n))
    src = open(os.path.join(TREE, f), encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    open(os.path.join(TREE, f), "w", encoding="utf-8").write(src.replace(old, new))
    print("== PERTURB %s planted in %s" % (MODE, f))
SERVER = os.path.join(TREE, "swg-panel-server")

_l = importlib.machinery.SourceFileLoader("swgpanel_awg3turn", SERVER)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_awg3turn", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

HPK = "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0="
BASE20 = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33",
          "H1": "103509605-103509620", "H2": "1694692368-1694692383", "H3": "2553282719-2553282734",
          "H4": "3170237912-3170237927", "I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>",
          "I4": "<b 0xc000000001><r 32><t>", "I5": "<t><r 48>"}
SET31 = {"HeaderProtectionKey": HPK, "RandomTrailers": "1", "ContentPaddingAddition": "10-100", "RekeyAfterTime": "100-120",
         "RekeyTimeout": "3-7", "RejectAfterTime": "150-180", "KeepaliveTimeout": "5-15", "MaxHandshakeAttempts": "15-20"}
FULL31 = {**BASE20, **SET31}
PUB = "8Y1mOEM2Uv3Ez6CUfXOvsUg0dNrV4kx0mB9rp1cV3lE="
KEY = "ab" * 32
def wn(port, lport, title=""):
    return {"service": "vk-turn-proxy-WINGS-N-%d" % lport, "title": title, "listen": "0.0.0.0:%d" % lport,
            "connect": "127.0.0.1:%d" % port, "wrap_key": KEY, "params": "-wrap-mode on -wrap-key " + KEY}
W0 = wn(51820, 56005, "wings-office")
S0 = {"service": "vk-turn-proxy-samosvalishe-56009", "title": "freeturn-office", "listen": "0.0.0.0:56009",
      "connect": "127.0.0.1:51820", "wrap_key": KEY, "params": "-obf-profile rtpopus -obf-key " + KEY}
W3, W5, W8, W10, W11 = wn(51823, 56007), wn(51825, 56008), wn(51827, 56013), wn(51832, 56014), wn(51833, 56015)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "endpoint_host": "203.0.113.7",
                  "ifaces": {"awg1": {"awg_params": dict(FULL31)}, "awg10": {"awg_params": dict(FULL31)},
                             "awg8": {"awg_params": dict(BASE20), "_synced": {"awg_params": dict(BASE20)}},
                             "awg9": {"awg_params": dict(BASE20), "_synced": {"awg_params": dict(BASE20)}},
                             "awg11": {"awg_params": dict(BASE20), "_lastcfg": {"listen_port": 51833, "subnet": "10.33.0.0/24"}}},
                  "turn": {"vk-turn-proxy-WINGS-N-56006": {"action": "install", "owner": "WINGS-N/vk-turn-proxy",
                                                            "listen": "0.0.0.0:56006", "connect": "127.0.0.1:51824",
                                                            "wrap_flags": "", "title": "", "at": int(time.time())}}}},
          open(NODES, "w"))   # `at` is now: the sync drops an install still unreported after 240 s
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
SHIM = os.path.join(TMP, "shim"); os.makedirs(SHIM)
with open(os.path.join(SHIM, "curl"), "w") as fh:     # no install here may reach GitHub (turn_pin resolves a tag with curl)
    fh.write("#!/bin/sh\nexit 6\n")
os.chmod(os.path.join(SHIM, "curl"), 0o755)
PORT = free_port()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, SERVER], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "PATH": SHIM + os.pathsep + os.environ.get("PATH", ""),
                             "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": TREE, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    try:
        return code, json.loads(raw or b"{}")
    except Exception:
        return code, {"raw": raw[:200]}

for _ in range(150):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
    except Exception:
        if proc.poll() is not None:
            sys.exit("panel exited: " + open(log.name).read()[-2000:])
        time.sleep(0.1)
TOK = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]

def nodes():
    return json.load(open(NODES))

def iface(port, awg):
    return {"peers": [], "meta": {"public_key": PUB, "listen_port": port, "mtu": 1280, "subnet": "10.%d.0.0/24" % (port - 51800),
                                  "address": "10.%d.0.1/24" % (port - 51800), "awg_params": awg, "tool": "awg"}}
# what the node reports — the story changes it the way a node would after applying something
IFACES = {"awg0": iface(51820, dict(BASE20)), "awg1": iface(51821, dict(FULL31)), "awg2": iface(51822, dict(BASE20)),
          "awg3": iface(51823, dict(BASE20)), "awg4": iface(51824, dict(BASE20)), "awg8": iface(51827, dict(FULL31)),
          "awg9": iface(51828, dict(FULL31)), "awg10": iface(51832, dict(FULL31))}
TPS = {tp["service"]: tp for tp in (W0, S0, W3, W5, W8, W10, W11)}

def sync():
    code, r = req("/api/node/sync", {"snapshot": {"hostname": "n1", "noded_version": "t", "generated_at": int(time.time()),
                                                  "interfaces": IFACES, "turn_proxies": list(TPS.values()),
                                                  "datapath": {"awg": {"gen": {"module": "3.1", "fallback": "3.1", "tools": "3.1"}}}}}, TOK)
    assert code == 200, (code, r)

def install(fork, listen, connect):
    return req("/api/turn/install", {"node": "n1", "fork": fork, "owner": P.turn_fork_owner(fork), "listen": listen,
                                     "connect": connect, "wrap_flags": ""})

def rec(ifn):
    return (nodes()["n1"].get("ifaces") or {}).get(ifn) or {}

def pending(svc):
    return (nodes()["n1"].get("turn") or {}).get(svc)

def hpk(ifn):
    return (rec(ifn).get("awg_params") or {}).get("HeaderProtectionKey")

HARNESS = r"""
import fs from "node:fs"; import vm from "node:vm"; import { pathToFileURL } from "node:url";
const IN = JSON.parse(fs.readFileSync(0, "utf8")), R = IN.root;
const { spa } = await import(pathToFileURL(R + "/tests/spa_env.mjs").href);
const C = await spa("crypto.js");
vm.runInThisContext(fs.readFileSync(R + "/turn-artifacts.js", "utf8"));
const conf = C.buildConf(IN.o), a = globalThis.SWGTurn.artifact(conf, IN.tp, "", {}, [], "freeturn");
console.log(JSON.stringify({ conf, link: a.text }));
"""

try:
    sync()
    SECTION[0] = "[1]"
    print("[1] a WINGS-N proxy is never pointed at a 3.1 interface")
    code, r = install("WINGS-N", "0.0.0.0:56010", "127.0.0.1:51821")
    err = r.get("error") or ""
    check("WINGS-N → awg1 (3.1) is refused", code == 400 and "awg1" in err and "AmneziaWG 3.1" in err and "WINGS V" in err, (code, r))
    check("…and nothing is queued", not pending("vk-turn-proxy-WINGS-N-56010"))
    code, r = install("WINGS-N", "0.0.0.0:56011", "127.0.0.1:51822")
    check("control: WINGS-N → awg2 (2.0) goes through", code == 200 and pending("vk-turn-proxy-WINGS-N-56011"), (code, r))
    code, r = install("samosvalishe", "0.0.0.0:56012", "127.0.0.1:51821")
    check("control: samosvalishe → awg1 (3.1) goes through", code == 200 and pending("vk-turn-proxy-samosvalishe-56012"), (code, r))

    SECTION[0] = "[2]"
    print("\n[2] …nor moved onto one")
    code, r = req("/api/turn/manage", {"node": "n1", "service": W0["service"], "connect": "127.0.0.1:51821"})
    check("manage WINGS-N connect → awg1 is refused", code == 400 and "awg1" in (r.get("error") or ""), (code, r))
    check("…and nothing is queued", not pending(W0["service"]))
    code, r = req("/api/turn/manage", {"node": "n1", "service": W0["service"], "params": W0["params"]})
    check("control: a params-only edit goes through", code == 200 and (pending(W0["service"]) or {}).get("action") == "manage", (code, r))

    SECTION[0] = "[3]"
    print("\n[3] a switch to 3.1 is refused while a WINGS-N proxy points at the interface, naming it")
    for how, body in (("awg_gen 3.1", {"awg_gen": "3.1"}), ("a raw dict with an HPK", {"awg_params": dict(FULL31)})):
        code, r = req("/api/iface/update", {"node": "n1", "iface": "awg0", **body})
        err = r.get("error") or ""
        check("%s → 409" % how, code == 409 and r.get("code") == "turn_awg3", (code, r))
        check("%s: names the WINGS-N proxy (title, fork, app)" % how,
              "wings-office" in err and "WINGS-N" in err and "WINGS V" in err, err)
        check("%s: does not name the samosvalishe one" % how, "freeturn-office" not in err and "samosvalishe" not in err, err)
        check("%s: lists exactly it" % how, [b.get("service") for b in (r.get("turn_proxies") or [])] == [W0["service"]],
              r.get("turn_proxies"))
        check("%s: the record is untouched" % how, not hpk("awg0"), rec("awg0"))
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg4", "awg_gen": "3.1"})
    check("a WINGS-N install still pending blocks too (awg4), by name", code == 409
          and "vk-turn-proxy-WINGS-N-56006" in (r.get("error") or ""), (code, r))
    code, r = req("/api/turn/delete", {"node": "n1", "service": W3["service"]})
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg3", "awg_gen": "3.1"})
    check("a WINGS-N proxy being deleted still blocks while the node reports it (awg3)", code == 409 and not hpk("awg3"), (code, r))
    TPS.pop(W3["service"]); sync()                  # the node has removed it
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg3", "awg_gen": "3.1"})
    check("…and once the node reports it gone, the switch goes through", code == 200 and hpk("awg3"), (code, r))

    SECTION[0] = "[4]"
    print("\n[4] the operator re-points it: the switch goes through once the node has applied that")
    code, r = req("/api/turn/manage", {"node": "n1", "service": W0["service"], "connect": "127.0.0.1:51822"})
    check("WINGS-N re-pointed at awg2 (2.0)", code == 200 and (pending(W0["service"]) or {}).get("connect") == "127.0.0.1:51822", (code, r))
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg0", "awg_gen": "3.1"})
    check("before the node applies it, the switch is still refused (the request may never be applied)",
          code == 409 and not hpk("awg0"), (code, r))
    TPS[W0["service"]] = dict(W0, connect="127.0.0.1:51822"); sync()   # the node has applied the re-point
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg0", "awg_gen": "3.1"})
    a0 = rec("awg0").get("awg_params") or {}
    check("after it, the switch goes through", code == 200 and a0.get("HeaderProtectionKey"), (code, r))

    SECTION[0] = "[5]"
    print("\n[5] the samosvalishe proxy stays on awg0, and its freeturn:// link carries the 3.1 set, `1` and a single keepalive")
    sync()
    meta = P.apply_iface_meta(nodes()["n1"], P.node_describe({"interfaces": IFACES})["data"]["interfaces"])["awg0"]
    on0 = [tp["service"] for tp in TPS.values() if P._port_of(tp["connect"]) == str(meta.get("listen_port"))]
    check("the proxies pointing at awg0 now (the turnProxiesFor rule, over what the node reports): the samosvalishe one alone",
          on0 == [S0["service"]], on0)
    o = {"privkey": "cPrivKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "address": "10.20.0.2/32", "dns": meta.get("dns") or [],
         "mtu": meta.get("mtu") or 1280, "awg_params": meta.get("awg_params"), "server_pubkey": meta.get("public_key"),
         "psk": "pskAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "endpoint": meta.get("endpoint"),
         "allowed": "0.0.0.0/0, ::/0", "keepalive": meta.get("keepalive") if meta.get("keepalive") is not None else 25}
    if not shutil.which("node"):
        check("node on PATH to build the link", False, "this section cannot run, which is not a pass")
    else:
        p = subprocess.run(["node", "--input-type=module", "-e", HARNESS], input=json.dumps({"root": TREE, "o": o, "tp": S0}),
                           capture_output=True, text=True, timeout=120)
        check("the link builds", p.returncode == 0, (p.stderr or "")[-600:])
        if p.returncode == 0:
            out = json.loads(p.stdout)
            s = out["link"].replace("freeturn://", "")
            payload = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode())
            kv = [(l.split("=", 1)[0].strip(), l.split("=", 1)[1].strip()) for l in payload["wg"].splitlines() if "=" in l]
            names = [k for k, _ in kv]
            check("wg: each of the 3.1 set exactly once", all(names.count(k) == 1 for k in SET31), {k: names.count(k) for k in SET31})
            check("wg: the interface's HeaderProtectionKey", dict(kv).get("HeaderProtectionKey") == a0.get("HeaderProtectionKey"))
            check("wg: RandomTrailers = 1", dict(kv).get("RandomTrailers") == "1", dict(kv).get("RandomTrailers"))
            check("wg: no DisableCookies, no AdvancedSecurity", "DisableCookies" not in names and "AdvancedSecurity" not in names)
            check("wg: a single keepalive k (FreeTurn 4.3.0's core rejects a range)",
                  [v for k, v in kv if k == "PersistentKeepalive"] == ["25"], [v for k, v in kv if k == "PersistentKeepalive"])
            check("control: the panel's own config for it says 25-35", "PersistentKeepalive = 25-35" in out["conf"])

    SECTION[0] = "[6]"
    print("\n[6] a 3.1 create where a WINGS-N proxy already points")
    code, r = req("/api/iface/create", {"node": "n1", "iface": "awg5", "subnet": "10.25.0.0/24", "listen_port": 51825, "awg_gen": "3.1"})
    check("refused naming the stray proxy", code == 409 and W5["service"] in (r.get("error") or ""), (code, r))
    check("…and nothing is queued", "awg5" not in (nodes()["n1"].get("create") or {}))
    code, r = req("/api/iface/create", {"node": "n1", "iface": "awg6", "subnet": "10.26.0.0/24", "listen_port": 51825})
    check("control: a 2.0 create there goes through", code == 200 and "awg6" in (nodes()["n1"].get("create") or {}), (code, r))

    SECTION[0] = "[7]"
    print("\n[7] a 3.1 interface moved onto such a proxy's port")
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg1", "listen_port": 51825})
    check("awg1 (3.1) → :51825 is refused naming the proxy", code == 409 and W5["service"] in (r.get("error") or ""), (code, r))
    check("…and its port is untouched", rec("awg1").get("listen_port") in (None, 51821), rec("awg1"))
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg1", "listen_port": 51829})
    check("control: onto a free port it goes through", code == 200 and rec("awg1").get("listen_port") == 51829, (code, r))

    SECTION[0] = "[8]"
    print("\n[8] adopting a node-side 3.1 drift crosses the same line")
    d8, d9 = (rec("awg8").get("_drift") or {}).get("awg_params") or {}, (rec("awg9").get("_drift") or {}).get("awg_params") or {}
    check("the node's 3.1 set is drift on both (confirmed 2.0 records)", d8.get("HeaderProtectionKey") and d9.get("HeaderProtectionKey"),
          (rec("awg8"), rec("awg9")))
    code, r = req("/api/iface/adopt", {"node": "n1", "iface": "awg8", "key": "awg_params"})
    check("Adopt on awg8 (a WINGS-N proxy on it) → 409 naming it", code == 409 and W8["service"] in (r.get("error") or ""), (code, r))
    check("…the record and its drift untouched", not hpk("awg8") and (rec("awg8").get("_drift") or {}).get("awg_params"), rec("awg8"))
    code, r = req("/api/iface/adopt", {"node": "n1", "iface": "awg9", "key": "awg_params"})
    check("control: Adopt on awg9 (no such proxy) goes through", code == 200 and hpk("awg9"), (code, r))

    SECTION[0] = "[9]"
    print("\n[9] a 3.1 interface created but not yet reported")
    code, r = req("/api/iface/create", {"node": "n1", "iface": "awg7", "subnet": "10.31.0.0/24", "listen_port": 51831, "awg_gen": "3.1"})
    check("the 3.1 create is queued", code == 200 and "awg7" in (nodes()["n1"].get("create") or {}), (code, r))
    code, r = install("WINGS-N", "0.0.0.0:56016", "127.0.0.1:51831")
    check("a WINGS-N proxy onto its port is refused already", code == 400 and "awg7" in (r.get("error") or ""), (code, r))

    SECTION[0] = "[10]"
    print("\n[10] a save that re-sends what is already there is not a move")
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg10", "listen_port": "51832", "dns": "9.9.9.9"})
    check("awg10's Edit (its reported port re-sent) goes through", code == 200 and rec("awg10").get("dns") == ["9.9.9.9"], (code, r))
    code, r = req("/api/turn/manage", {"node": "n1", "service": W10["service"], "listen": W10["listen"], "connect": W10["connect"],
                                       "params": "-wrap-mode on -wrap-key " + "cd" * 32})
    check("its WINGS-N proxy's params-only Edit (connect re-sent) goes through", code == 200, (code, r))
    code, r = req("/api/turn/manage", {"node": "n1", "service": W10["service"], "connect": "127.0.0.1:51828"})
    check("re-pointing that proxy at another 3.1 interface (awg9) is refused", code == 400 and "awg9" in (r.get("error") or ""), (code, r))

    SECTION[0] = "[11]"
    print("\n[11] a lost interface is judged at the port it last had")
    code, r = req("/api/iface/update", {"node": "n1", "iface": "awg11", "awg_gen": "3.1"})
    check("switching the lost awg11 is refused for the WINGS-N proxy on :51833", code == 409 and W11["service"] in (r.get("error") or ""),
          (code, r))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    _plog = open(log.name).read()
    shutil.rmtree(TMP, ignore_errors=True)

check("no Traceback in the panel log", "Traceback" not in _plog, _plog[-1500:])
print()
if MODE:
    want = sorted(PLANTS[MODE][3])
    red = sorted({s for s, _ in FAILS})
    ok = red == want
    print(("PERTURB OK — %s went red on %s" if ok else "PERTURB FAILED — %s: red sections %s, wanted exactly %s")
          % ((MODE, want) if ok else (MODE, red, want)))
    sys.exit(0 if ok else 1)
if FAILS:
    print("FAILED: " + "; ".join("%s %s" % f for f in FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
