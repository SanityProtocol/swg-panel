#!/usr/bin/env python3
"""Self-test — a blocked or expired device loses its tunnel on an ADD-ONLY interface too.

An add-only interface (`#swg:onboarded`: adopted with peers the panel never made) removes nothing it is merely not sent;
it removes only what the sync's `remove` names. Blocking a peer, blocking its owner, or letting either one expire only
dropped the peer from `desired`, so on such an interface the device kept working. Measured on the 1.8.8 qualification
(q4, converted Docker→bare, which stamped the panel's own wg0/awg0 add-only): a blocked peer, a blocked user's device
and an expired peer all still passed traffic; a deleted peer — retired, so named in `remove` — was cut at once.

The sync now names every cut-off peer the node still reports, beside the operator's retirements. Every node since the
retire list existed honours `remove` on an add-only interface, so a 1.8.7 node is covered by the panel alone.

  THE PANEL (a REAL panel process: temp state, scratch port, no auth; the node is played by POSTing /api/node/sync)
    [1] `remove` names the live keys of: a blocked peer, a blocked user's peer, an expired peer, an expired user's peer
        — per interface — and not: an active peer, a stranger key, a cut-off peer that is not live here, a cut-off peer
        whose target is another node, the keyless (WDTT) side of a mixed peer
    [2] the operator's retirements still ride along, first, and a key both retired and cut off is named once
    [3] a quiet node's reply is unchanged: nothing cut off on the wire → `remove` is exactly the retire map ({} when none)
  THE NODE (the REAL swg-noded `reconcile`, fed that reply; the agent and the interface read stubbed)
    [4] on the add-only interface the four cut-off devices are removed; the active peer and the stranger stay
    [5] unblocking brings the device back on the next sync (an add-only interface still ADDS)

Run: python3 tests/cutoff_remove_selftest.py     (0 = pass)
     --perturb   the shipped `remove` (retirements only) planted back → RED
"""
import importlib.machinery, importlib.util, json, os, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="cutoff-")
server = PANEL
if PERTURB:
    _s = open(PANEL, encoding="utf-8").read()
    _a = '"remove": _remove,'
    assert _s.count(_a) == 1, "perturbation anchor missing — would FALSE-PASS"
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(_s.replace(_a, '"remove": node.get("retire") or {},'))


def _load(path, name):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


def key(c):
    return (c * 43)[:43] + "="


A, B, C, D, E, S, H, G, R, M = (key(c) for c in "ABCDEFGHRM")   # S = a stranger (no roster entry)
NOW = int(time.time())
PAST, FUTURE = NOW - 3600, NOW + 30 * 86400


def roster(unblock_b=False):
    def peer(pid, pk, ip, uid=None, disabled=False, expiry=0, targets=None):
        return {"id": pid, "pubkey": pk, "psk": "PSK" + pid + "=", "user_id": uid, "title": pid, "disabled": disabled,
                "expiry": expiry, "targets": targets or [{"node": "n1", "iface": "wg0", "type": "wg", "ip": ip}],
                "created_at": NOW - 100, "modified_at": NOW - 100}
    return {"version": 1,
            "users": {"u1": {"id": "u1", "name": "carol"}, "u2": {"id": "u2", "name": "dave", "disabled": True},
                      "u3": {"id": "u3", "name": "erin", "expiry": PAST}, "u4": {"id": "u4", "name": "fay", "expiry": FUTURE}},
            "peers": {"pa": peer("pa", A, "10.8.0.2", "u1"),
                      "pb": peer("pb", B, "10.8.0.3", "u1", disabled=not unblock_b),          # peer blocked
                      "pc": peer("pc", C, "10.8.0.4", "u2"),                                  # its owner blocked
                      "pd": peer("pd", D, "10.8.0.5", "u4", expiry=PAST),                     # peer expired
                      "pe": peer("pe", E, "10.8.0.6", "u3"),                                  # its owner expired
                      "ph": peer("ph", H, "10.8.0.7", "u1", disabled=True),                   # blocked, not on the wire
                      "pg": peer("pg", G, "10.8.0.8", "u1", disabled=True,                    # blocked, lives on n2
                                 targets=[{"node": "n2", "iface": "wg0", "type": "wg", "ip": "10.8.0.8"}]),
                      "pm": peer("pm", M, "10.8.0.9", "u1", disabled=True,                    # mixed: wg1 + a WDTT side
                                 targets=[{"node": "n1", "iface": "wg1", "type": "wg", "ip": "10.9.0.9"},
                                          {"node": "n1", "iface": "wdtt0", "type": "wdtt", "ip": ""}]),
                      "pr": peer("pr", R, "10.8.0.10", "u1", disabled=True)}}              # blocked AND retired


def live(pk, ip):
    return {"public_key": pk, "allowed_ips": ip + "/32", "endpoint": None, "last_handshake": NOW - 5,
            "rx_bytes": 1000, "tx_bytes": 1000, "preshared_key": None}


def snapshot(keys_wg0, keys_wg1=()):
    ips = {A: "10.8.0.2", B: "10.8.0.3", C: "10.8.0.4", D: "10.8.0.5", E: "10.8.0.6", S: "10.8.0.99", G: "10.8.0.8",
           R: "10.8.0.10", M: "10.9.0.9"}
    meta = lambda sub: {"subnet": sub, "listen_port": 51820, "public_key": key("Z"), "address": sub.replace("0/24", "1/24")}
    return {"hostname": "node-a", "generated_at": int(time.time()), "noded_version": "t",
            "interfaces": {"wg0": {"peers": [live(k, ips[k]) for k in keys_wg0], "meta": meta("10.8.0.0/24"), "onboarded": True},
                           "wg1": {"peers": [live(k, ips[k]) for k in keys_wg1], "meta": meta("10.9.0.0/24"), "onboarded": False},
                           "wdtt0": {"peers": [live(M, "10.9.0.9")], "meta": meta("10.7.0.0/24")}}}


state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json"); USERS = os.path.join(state, "users.json")
json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}, "wg1": {}}, "retire": {"wg0": [R]}},
           "n2": {"id": "n2", "name": "node-b", "ifaces": {"wg0": {}}}}, open(NODES, "w"))
json.dump(roster(), open(USERS, "w"))
fleet_cfg = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": USERS, "stats_dir": stats}, open(fleet_cfg, "w"))
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": fleet_cfg, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


try:
    for _ in range(150):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]

    print("[1]–[2] what the sync asks the node to drop")
    c, r1 = req("/api/node/sync", {"snapshot": snapshot([A, B, C, D, E, S, G, R], [M])}, TOK)
    check("the sync answered", c == 200 and isinstance(r1.get("desired"), dict), (c, str(r1)[:300]))
    rm = r1.get("remove") or {}
    want0 = [R, B, C, D, E]
    check("[1] wg0 (add-only): the blocked peer, the blocked user's peer, the expired peer and the expired user's peer",
          set(rm.get("wg0") or []) >= {B, C, D, E}, rm)
    check("[1] …and nobody else: not the active peer, not the stranger, not a cut-off key that lives on another node",
          not ({A, S, G} & set(rm.get("wg0") or [])), rm)
    check("[1] …a cut-off peer that is not on the wire is not named (nothing to drop)", H not in json.dumps(rm), rm)
    check("[1] the mixed peer: named on its wg interface, never on its keyless (WDTT) side",
          rm.get("wg1") == [M] and "wdtt0" not in rm, rm)
    check("[1] desired still carries only the active peer on wg0", [p.get("public_key") for p in (r1.get("desired") or {}).get("wg0", [])] == [A],
          (r1.get("desired") or {}).get("wg0"))
    check("[2] the operator's retirement rides along, first, and a key both retired and cut off is named once",
          (rm.get("wg0") or [])[:1] == [R] and (rm.get("wg0") or []).count(R) == 1 and sorted(rm.get("wg0") or []) == sorted(want0), rm)

    print("\n[3] a quiet node's reply is unchanged")
    c, r2 = req("/api/node/sync", {"snapshot": snapshot([A, S, R])}, TOK)
    check("[3] only the retirement left on the wire → `remove` is exactly the retire map",
          r2.get("remove") == {"wg0": [R]}, r2.get("remove"))
    c, r3 = req("/api/node/sync", {"snapshot": snapshot([A, S])}, TOK)          # R gone → the panel clears it
    c, r3 = req("/api/node/sync", {"snapshot": snapshot([A, S])}, TOK)
    check("[3] nothing retired, nobody cut off on the wire → `remove` is {} (what it always was)", r3.get("remove") == {}, r3.get("remove"))

    print("\n[4]–[5] the node, fed that reply")
    N = _load(NODED, "swgnoded_cutoff")
    N.STATE_DIR = TMP
    LIVE = {"wg0": [A, B, C, D, E, S], "wg1": []}
    calls = []

    def dump(cfg, ifn):
        ips = {A: "10.8.0.2", B: "10.8.0.3", C: "10.8.0.4", D: "10.8.0.5", E: "10.8.0.6", S: "10.8.0.99"}
        return (["dev", "key", "51820"], [dict(live(k, ips.get(k, "10.8.0.50")), preshared_key="PSK" + {A: "pa", B: "pb"}.get(k, "x") + "=")
                                           for k in LIVE.get(ifn, [])])

    def agent(_a, _s, payload):
        calls.append(payload)
        if payload.get("op") == "remove-peer":
            LIVE[payload["iface"]] = [k for k in LIVE[payload["iface"]] if k != payload["public_key"]]
        elif payload.get("op") == "add-peer":
            LIVE[payload["iface"]].append(payload["public_key"])
        return {"ok": True}
    N._iface_dump = dump
    N.run_agent = agent
    N.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out in this test"))
    CFG = {"interfaces": {"wg0": {"cmd": ["wg"], "conf": os.path.join(TMP, "wg0.conf"), "onboarded": True},
                          "wg1": {"cmd": ["wg"], "conf": os.path.join(TMP, "wg1.conf")}}}
    res = N.reconcile(CFG, r1["desired"], "/opt/swg-agent/swg-agent", False, r1.get("remove"))
    gone = sorted(c["public_key"] for c in calls if c.get("op") == "remove-peer" and c.get("iface") == "wg0")
    check("[4] add-only wg0: the four cut-off devices are removed", gone == sorted([B, C, D, E]), [g[:4] for g in gone])
    check("[4] …the active peer and the stranger stay", A in LIVE["wg0"] and S in LIVE["wg0"], [k[:4] for k in LIVE["wg0"]])
    check("[4] …and the pass reports it without errors", res.get("removed") == 4 and not res.get("errors"), res)

    json.dump(roster(unblock_b=True), open(USERS, "w"))
    c, r4 = req("/api/node/sync", {"snapshot": snapshot([k for k in LIVE["wg0"]])}, TOK)
    calls.clear()
    N.reconcile(CFG, r4["desired"], "/opt/swg-agent/swg-agent", False, r4.get("remove"))
    check("[5] unblocked: the next sync sends the device again and the add-only interface adds it back",
          [c.get("public_key") for c in calls if c.get("op") == "add-peer"] == [B] and B in LIVE["wg0"],
          [(c.get("op"), (c.get("public_key") or "")[:4]) for c in calls])
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print()
if PERTURB:
    print("PERTURBED: %s" % ("RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 2)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
