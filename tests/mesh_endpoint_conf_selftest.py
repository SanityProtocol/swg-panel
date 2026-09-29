#!/usr/bin/env python3
"""Self-test: a mesh peer's .conf names the endpoint the panel wants — not the one the peer was ADDED with.

Found in the 1.8.8 qualification (round 7, q1 ↔ q2): q2's endpoint moved (10.0.2.15 → 192.168.77.2). q2 dialled q1
from its new address, WireGuard on q1 ROAMED the live peer to it, and when the panel then sent the new endpoint,
swg-noded's reconcile saw the peer already dialled there and ADOPTED it without re-adding a healthy link (its
SELF-HEAL branch) — recording the new endpoint in mesh-eps.json. Only add-peer writes an Endpoint into the .conf, so
q1's .conf kept 10.0.2.15:9999 until something re-added the peer. The .conf is what brings the interface up: after a
reboot or a container restart the link dialled the stale address, and nothing re-dialled it — mesh-eps.json said the
new endpoint was already applied, and the stale-link bounce waits for a handshake a restarted interface never had. A
link only this side could start stayed down. (Pre-existing: the SELF-HEAL branch is 5efeb4c, 1.8.7.)

Through the REAL functions (swg-agent's rewrite + op, swg-noded's reconcile with the agent stubbed onto the REAL op):
  [A1] rewrite_peer_endpoint_in_conf: replaces exactly the peer's Endpoint line; inserts one after its PublicKey when
       the block has none; leaves an equal one, an absent peer, the other peers, the "# name:" comments and the
       [Interface] (AmneziaWG params) byte for byte; the file stays 0600
  [A2] persist-peer-endpoint refuses an endpoint that is not one host:port token (a line break would be conf code)
  [N1] the roam case: live endpoint == desired, mesh-eps.json holds the old one → ONE persist-peer-endpoint with the
       desired endpoint, and NO remove/add (the datapath is not touched); the .conf now names the desired endpoint
  [N2] the next pass: no agent call at all (no churn)
  [N3] a .conf left stale by an older build (mesh-eps.json already current): mended at the first pass of a new process
  [N4] a .conf already right: never written
  [N5] an agent that cannot do it (an older agent: unknown op): one attempt per change, said once — not every pass
  [N6] a user peer (no endpoint) and a peer the .conf does not hold: no call
  [N7] a peer ADDED this pass with an endpoint: its .conf is not re-checked on the next pass
  [N8] THE REAL SEQUENCE, in one long-running process: the .conf checked at the old endpoint; the far node moves, the
       live peer roams to its new address, THEN the panel's desired endpoint follows → adopted, and the .conf follows too

Run: python3 tests/mesh_endpoint_conf_selftest.py      (0 = pass)
     --perturb         the .conf check taken out of reconcile (the shipped behaviour) → RED on [N1] [N3]
     --perturb-churn   a failed write retried every pass → RED on [N5]
     --perturb-insert  the rewrite never inserts a missing Endpoint → RED on [A1]
     --perturb-once    the .conf checked once per process only, not again when the desired endpoint changes → RED on [N8]
"""
import importlib.machinery, importlib.util, json, os, stat, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.path.join(ROOT, "swg-noded")
AGENT = os.path.join(ROOT, "swg-agent")

NODED_PLANTS = {
    "--perturb": ("                if want_ep and _EP_CONF.get(ek) != want_ep:\n", "                if False:\n"),
    "--perturb-churn": ("                    _EP_CONF[ek] = want_ep   # once per change, whatever the outcome",
                        "                    _EP_CONF[ek] = want_ep if conf_ep == want_ep or conf_ep is None else _EP_CONF.get(ek)   #"),
    "--perturb-once": ("                if want_ep and _EP_CONF.get(ek) != want_ep:\n",
                       "                if want_ep and ek not in _EP_CONF:\n"),
}
AGENT_PLANTS = {
    "--perturb-insert": ("            lines.insert(pk_at[0] + 1, f\"Endpoint = {endpoint}\")\n", "            return False\n"),
}
MODE = next((a for a in sys.argv[1:] if a in NODED_PLANTS or a in AGENT_PLANTS), None)
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def _load(path, name, plant=None):
    src = open(path, encoding="utf-8").read()
    if plant:
        cut, new = plant
        assert src.count(cut) == 1, "perturbation anchor missing or not unique — this run would FALSE-PASS"
        src = src.replace(cut, new, 1)
    tmp = os.path.join(tempfile.mkdtemp(), name + ".py")
    open(tmp, "w", encoding="utf-8").write(src)
    ld = importlib.machinery.SourceFileLoader(name, tmp)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(mod)
    except SystemExit:
        pass
    return mod


A = _load(AGENT, "swgagent", AGENT_PLANTS.get(MODE))
N = _load(NODED, "swgnoded", NODED_PLANTS.get(MODE))
T = tempfile.mkdtemp(prefix="meshep-")

PK_USER = "5dYQ79ynisVEC8XyQgXamgfpZe38PN6KihtEV6kpGjk="
PK_MESH = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
PK_BARE = "cHJpdmF0ZS1rZXktcHJpdmF0ZS1rZXktcHJpdmF0ZS0="   # a mesh peer whose block carries no Endpoint line
PK_GONE = "Z29uZS1rZXktZ29uZS1rZXktZ29uZS1rZXktZ29uZT0="   # not in the .conf at all (live-only)
CONF = """[Interface]
PrivateKey = cHJpdmF0ZS1rZXktc2VydmVyLXNlcnZlci1zZXJ2ZXI=
Address = 10.255.0.1/31
ListenPort = 9999
Jc = 4
I1 = <b 0x0f00><r 16><t>
Table = off

# name: phone
[Peer]
PublicKey = %s
PresharedKey = cHNrLXBzay1wc2stcHNrLXBzay1wc2stcHNrLXBzay0=
AllowedIPs = 10.71.1.2/32

# name: mesh-q2
[Peer]
PublicKey = %s
PresharedKey = cHNrLXBzay1wc2stcHNrLXBzay1wc2stcHNrLXBzay0=
AllowedIPs = 10.255.0.0/32
Endpoint = 10.0.2.15:9999
PersistentKeepalive = 25

# name: mesh-q5
[Peer]
PublicKey = %s
AllowedIPs = 10.255.0.2/32
PersistentKeepalive = 25
""" % (PK_USER, PK_MESH, PK_BARE)


def fresh_conf(name, text=CONF):
    p = os.path.join(T, name)
    open(p, "w").write(text)
    os.chmod(p, 0o600)
    return p


def lines_of(p):
    return open(p).read().splitlines()


# ── [A1] the rewrite ──────────────────────────────────────────────────────────────────────────────────────────────
c = fresh_conf("a1.conf")
before = lines_of(c)
ch = A.rewrite_peer_endpoint_in_conf(c, PK_MESH, "192.168.77.2:9999")
after = lines_of(c)
diff = [(i, b, a) for i, (b, a) in enumerate(zip(before, after)) if b != a]
check("[A1] replace: returns True", ch is True, ch)
check("[A1] …exactly one line changed — the mesh peer's Endpoint", len(before) == len(after) and
      diff == [(before.index("Endpoint = 10.0.2.15:9999"), "Endpoint = 10.0.2.15:9999", "Endpoint = 192.168.77.2:9999")], diff)
check("[A1] …and the file is still 0600", stat.S_IMODE(os.stat(c).st_mode) == 0o600, oct(os.stat(c).st_mode))
ino, raw = os.stat(c).st_ino, open(c).read()
ch = A.rewrite_peer_endpoint_in_conf(c, PK_MESH, "192.168.77.2:9999")
check("[A1] the same endpoint again: False, the file not even rewritten", ch is False and os.stat(c).st_ino == ino
      and open(c).read() == raw, ch)
ch = A.rewrite_peer_endpoint_in_conf(c, PK_GONE, "192.168.77.9:9999")
check("[A1] a peer the .conf does not hold: False, nothing written", ch is False and open(c).read() == raw, ch)
c2 = fresh_conf("a1b.conf")
before = lines_of(c2)
ch = A.rewrite_peer_endpoint_in_conf(c2, PK_BARE, "192.168.77.5:9999")
after = lines_of(c2)
pk_i = before.index("PublicKey = %s" % PK_BARE)
check("[A1] a block with no Endpoint: one inserted right after its PublicKey, nothing else moved",
      ch is True and after == before[:pk_i + 1] + ["Endpoint = 192.168.77.5:9999"] + before[pk_i + 1:], after[pk_i - 2:pk_i + 4])
check("[A1] …the [Interface] (AmneziaWG params) and the other peers untouched",
      after[:before.index("# name: mesh-q5")] == before[:before.index("# name: mesh-q5")])

# ── [A2] the op's own guard ───────────────────────────────────────────────────────────────────────────────────────
c3 = fresh_conf("a2.conf")
cfg = {"interfaces": {"swg_x": {"cmd": ["awg"], "conf": c3}}}
bad = []
for ep in ("192.168.77.2:9999\nPostUp = touch /tmp/pwned", "host:", ":9999", "a b:1", "10.0.0.1:123456", ""):
    try:
        A.op_persist_peer_endpoint(cfg, {"iface": "swg_x", "public_key": PK_MESH, "endpoint": ep})
        bad.append(ep)
    except A.AgentError:
        pass
check("[A2] not one host:port token (a line break, no port, a space…) is refused, and nothing written",
      bad == [] and open(c3).read() == CONF, bad)
ok = []
for ep in ("192.168.77.2:9999", "[2001:db8::1]:51820", "node-2.example.net:443"):
    try:
        A.op_persist_peer_endpoint(cfg, {"iface": "swg_x", "public_key": PK_MESH, "endpoint": ep}); ok.append(ep)
    except A.AgentError as e:
        print("   ", ep, e.msg)
check("[A2] …an IPv4, a [v6] and a host name are taken", len(ok) == 3, ok)

# ── the reconcile, with the agent stubbed onto the REAL op against the temp .conf ────────────────────────────────
IFACE = "swg_x"
CALLS = []
AGENT_BEHAVIOUR = {"mode": "real"}


def stub_agent(agent, sudo, payload):
    CALLS.append(payload)
    if payload.get("op") != "persist-peer-endpoint":
        return {"ok": True}
    if AGENT_BEHAVIOUR["mode"] == "old":
        return {"ok": False, "error": "unknown op 'persist-peer-endpoint'", "code": "unknown_op"}
    try:
        return {"ok": True, "data": A.op_persist_peer_endpoint(CFG, payload)}
    except A.AgentError as e:
        return {"ok": False, "error": e.msg, "code": e.code}


N.run_agent = stub_agent
N.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconcile must not shell out in this test"))
N.STATE_DIR = tempfile.mkdtemp(prefix="meshep-state-")
CONFP = fresh_conf("n.conf")
CFG = {"interfaces": {IFACE: {"cmd": ["awg"], "conf": CONFP}}}
WANT_EP = "192.168.77.2:9999"


def live(mesh_ep):
    """The live interface: the user peer, the mesh peer (dialled at `mesh_ep`, handshaken just now), the q5 peer."""
    import time
    now = int(time.time())
    peers = [
        {"public_key": PK_USER, "preshared_key": None, "endpoint": "198.51.100.7:40000", "allowed_ips": "10.71.1.2/32",
         "last_handshake": now, "rx_bytes": 0, "tx_bytes": 0},
        {"public_key": PK_MESH, "preshared_key": None, "endpoint": mesh_ep, "allowed_ips": "10.255.0.0/32",
         "last_handshake": now, "rx_bytes": 0, "tx_bytes": 0},
        {"public_key": PK_BARE, "preshared_key": None, "endpoint": "192.168.77.5:9999", "allowed_ips": "10.255.0.2/32",
         "last_handshake": now, "rx_bytes": 0, "tx_bytes": 0},
    ]
    N._iface_dump = lambda cfg, ifn: (["dev", "key", "9999"], peers)


def desired(mesh_ep=WANT_EP, bare_ep="192.168.77.5:9999"):
    return {IFACE: [
        {"public_key": PK_USER, "allowed_ips": "10.71.1.2/32", "name": "phone"},
        {"public_key": PK_MESH, "allowed_ips": "10.255.0.0/32", "endpoint": mesh_ep, "persistent_keepalive": 25,
         "name": "mesh-q2"},
        {"public_key": PK_BARE, "allowed_ips": "10.255.0.2/32", "endpoint": bare_ep, "persistent_keepalive": 25,
         "name": "mesh-q5"},
    ]}


def set_applied(d):
    json.dump(d, open(os.path.join(N.STATE_DIR, "mesh-eps.json"), "w"))


def conf_ep(pk):
    return N._conf_peer_endpoints(open(CONFP).read()).get(pk)


def one_pass():
    CALLS.clear()
    return N.reconcile(CFG, desired(), "/opt/swg-agent/swg-agent", False)


# [N1] the roam: live already at the desired endpoint, mesh-eps.json still at the old one
N._EP_CONF.clear()
live(WANT_EP)
set_applied({IFACE + "|" + PK_MESH: "10.0.2.15:9999", IFACE + "|" + PK_BARE: "192.168.77.5:9999"})
one_pass()
ops = [(c.get("op"), c.get("public_key", "")[:8], c.get("endpoint")) for c in CALLS]
check("[N1] one persist-peer-endpoint for the roamed peer, with the DESIRED endpoint — and nothing else",
      [o for o in ops if o[1] == PK_MESH[:8]] == [("persist-peer-endpoint", PK_MESH[:8], WANT_EP)], ops)
check("[N1] …no remove-peer / add-peer at all: the datapath is not touched",
      not any(c.get("op") in ("remove-peer", "add-peer") for c in CALLS), ops)
check("[N1] …and the .conf now names it", conf_ep(PK_MESH) == WANT_EP, conf_ep(PK_MESH))
check("[N1] …the peer whose block had no Endpoint gets one too (it is dialled at the desired address)",
      conf_ep(PK_BARE) == "192.168.77.5:9999", conf_ep(PK_BARE))

# [N2] the next pass: nothing
one_pass()
check("[N2] the next pass: the agent is not called at all", CALLS == [], CALLS)

# [N3] a new process (the in-memory record empty), mesh-eps.json CURRENT, the .conf stale (an older build's leftover)
fresh_conf("n.conf")
N._EP_CONF.clear()
set_applied({IFACE + "|" + PK_MESH: WANT_EP, IFACE + "|" + PK_BARE: "192.168.77.5:9999"})
one_pass()
ops = [(c.get("op"), c.get("public_key", "")[:8]) for c in CALLS]
check("[N3] a .conf left stale by an older build is mended at the first pass of a new process",
      ("persist-peer-endpoint", PK_MESH[:8]) in ops and conf_ep(PK_MESH) == WANT_EP, (ops, conf_ep(PK_MESH)))
check("[N3] …still without touching the datapath", not any(c.get("op") in ("remove-peer", "add-peer") for c in CALLS), ops)

# [N4] a .conf already right: read, never written
N._EP_CONF.clear()
raw = open(CONFP).read()
one_pass()
check("[N4] a .conf already right: no call, the file as it was", CALLS == [] and open(CONFP).read() == raw, CALLS)

# [N5] an older agent that has no such op: one attempt per change, then quiet
fresh_conf("n.conf")
N._EP_CONF.clear()
AGENT_BEHAVIOUR["mode"] = "old"
one_pass()
first = [c.get("op") for c in CALLS]
one_pass(); one_pass()
check("[N5] an agent without the op: tried once for this change…", first.count("persist-peer-endpoint") == 2, first)
check("[N5] …and not again on every pass after", CALLS == [], CALLS)
AGENT_BEHAVIOUR["mode"] = "real"

# [N6] a user peer and a peer the .conf does not hold
fresh_conf("n.conf")
N._EP_CONF.clear()
one_pass()
check("[N6] the user peer (no endpoint) is never the subject of a call",
      not any(c.get("public_key") == PK_USER for c in CALLS), CALLS)
N._EP_CONF.clear()
CALLS.clear()
live(WANT_EP)
peers_gone = [{"public_key": PK_GONE, "preshared_key": None, "endpoint": "192.168.77.9:9999", "allowed_ips": "10.255.0.4/32",
               "last_handshake": 1, "rx_bytes": 0, "tx_bytes": 0}]
N._iface_dump = lambda cfg, ifn: (["dev", "key", "9999"], peers_gone)
set_applied({IFACE + "|" + PK_GONE: "192.168.77.9:9999"})
N.reconcile(CFG, {IFACE: [{"public_key": PK_GONE, "allowed_ips": "10.255.0.4/32", "endpoint": "192.168.77.9:9999",
                           "persistent_keepalive": 25}]}, "/opt/swg-agent/swg-agent", False)
check("[N6] a live peer the .conf does not hold: no call (nothing there to correct)",
      not any(c.get("op") == "persist-peer-endpoint" for c in CALLS), CALLS)

# [N7] a peer ADDED this pass: its .conf was written by add-peer — not re-checked next pass
N._EP_CONF.clear()
live(WANT_EP)
peers_now = []
N._iface_dump = lambda cfg, ifn: (["dev", "key", "9999"], peers_now)
set_applied({})
CALLS.clear()
N.reconcile(CFG, {IFACE: [{"public_key": PK_GONE, "allowed_ips": "10.255.0.4/32", "endpoint": "192.168.77.9:9999",
                           "persistent_keepalive": 25}]}, "/opt/swg-agent/swg-agent", False)
added = [c.get("op") for c in CALLS]
peers_now.append({"public_key": PK_GONE, "preshared_key": None, "endpoint": "192.168.77.9:9999",
                  "allowed_ips": "10.255.0.4/32", "last_handshake": 0, "rx_bytes": 0, "tx_bytes": 0})
CALLS.clear()
N.reconcile(CFG, {IFACE: [{"public_key": PK_GONE, "allowed_ips": "10.255.0.4/32", "endpoint": "192.168.77.9:9999",
                           "persistent_keepalive": 25}]}, "/opt/swg-agent/swg-agent", False)
check("[N7] added this pass (add-peer wrote its .conf), then the next pass makes no call",
      added == ["add-peer"] and CALLS == [], (added, CALLS))

# [N8] the real sequence in ONE process: checked at the old endpoint, the far node moves, live roams, desired follows
fresh_conf("n.conf", CONF.replace("Endpoint = 10.0.2.15:9999", "Endpoint = 192.168.77.2:9999"))
N._EP_CONF.clear()
live("192.168.77.2:9999")
set_applied({IFACE + "|" + PK_MESH: "192.168.77.2:9999", IFACE + "|" + PK_BARE: "192.168.77.5:9999"})
N.reconcile(CFG, desired(mesh_ep="192.168.77.2:9999"), "/opt/swg-agent/swg-agent", False)   # the first pass: all in step
live("192.168.77.12:9999")                  # q2 moved and dialled in from .12: WireGuard roamed the live peer
CALLS.clear()
N.reconcile(CFG, desired(mesh_ep="192.168.77.2:9999"), "/opt/swg-agent/swg-agent", False)   # the panel has not caught up yet
check("[N8] before the panel follows: no call (the .conf matches the DESIRED endpoint, which has not moved)", CALLS == [], CALLS)
CALLS.clear()
N.reconcile(CFG, desired(mesh_ep="192.168.77.12:9999"), "/opt/swg-agent/swg-agent", False)  # …now it has
ops = [(c.get("op"), c.get("endpoint")) for c in CALLS]
check("[N8] the desired endpoint moves to where the link already is: adopted with ONE .conf write, no re-add",
      ops == [("persist-peer-endpoint", "192.168.77.12:9999")], ops)
check("[N8] …and the .conf names the new address", conf_ep(PK_MESH) == "192.168.77.12:9999", conf_ep(PK_MESH))

print()
if MODE:
    print("PERTURBED (%s): %s" % (MODE, "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate is blind"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
