#!/usr/bin/env python3
"""Self-test — Peer targets' Deploy is one call, applied whole or not at all (docs/SCALE-PLAN.md "F28 — design").

The sheet sent every add, then every address edit, then every removal as its own write, so a refused add (a full turn server)
still ran the removals: a move to a full server left the peer on neither. /api/peers/targets checks every change against the
stored peer and writes all of it or nothing. The panel's own api(), in process, on temp state:

  [1] a move from awg1 to a full qWDTT (pool 1) → 409 refused naming it (turn_full); every state file byte-identical
  [2] the move to awg2 → applied: awg1 retired on the node and its stored config gone, one Added and one Removed line
  [3] the same body again (a Deploy whose answer was lost) → 200 with the peer, nothing written
  [4] a stale base (the sheet opened before another change) → 409 changed, nothing written; so is an add another tab made
      first at another address (it is not this Deploy's: the sheet would file a QR for an address the peer does not hold)
  [5] an address edit onto a taken address beside an add → refused whole, the add not applied; a free one → both applied
  [6] a keyless peer's first key: applied once; the retry 200 and nothing written; another key → 409 key_changed
  [7] every target removed → 409 last_target; an interface named twice → 400
  [8] a deployment that would take another device's network over → refused (network_refused), nothing written

Run: python3 tests/peer_targets_move_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     nobase      the base check off                                   [4]
     nodone      a change already made is not answered as done        [3]
     doneip      an add at another address counts as done              [4]
     nofails     the collected refusals are not acted on              [1]
     noretire    a removal leaves the key on the node                 [2]
     notakeover  the takeover check skipped in this door              [8]
"""
import importlib.machinery, importlib.util, hashlib, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "nobase": ('        if {key(x) for x in lists["base"]} != set(have):\n', '        if False:\n'),
    "nodone": ('                and (not nk or p.get("pubkey") == nk)):\n', '                and (not nk or p.get("pubkey") == nk)) and False:\n'),
    "doneip": ('all(key(x) in have and ipof(have[key(x)]) == ipof(x) for x in lists["add"])', 'all(key(x) in have for x in lists["add"])'),
    "nofails": ('        if fails:\n            return 409, {"ok": False, "error": "nothing was changed"', '        if False:\n            return 409, {"ok": False, "error": "nothing was changed"'),
    "noretire": ('            retire_pubkey(nodes, deps["nodes_path"], [{"node": x["node"], "iface": x["iface"]}], old_key)\n', '            pass\n'),
    "notakeover": ('            took = network_takeover(roster, pid, p, final, nid, snaps)\n', '            took = []\n'),
}
if PLANT and PLANT not in PLANTS:
    sys.exit("unknown plant %r" % PLANT)
src = open(PANEL, encoding="utf-8").read()
if PLANT:
    old, new = PLANTS[PLANT]
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    src = src.replace(old, new, 1)
TMPM = tempfile.mkdtemp(prefix="targets-mod-")
path = os.path.join(TMPM, "swg-panel-server")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)

K = lambda c: (c * 43)[:43] + "="
AWG = {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 0, "S2": 0, "H1": 1, "H2": 2, "H3": 3, "H4": 4}
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {"awg1": {"meta": {"subnet": "10.8.0.0/24", "type": "awg", "awg_params": AWG}},
                       "awg2": {"meta": {"subnet": "10.71.0.0/24", "type": "awg", "awg_params": AWG}}},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1, "carried": 1}}
SNAP2 = dict(SNAP, interfaces={"wgs1": {"meta": {"subnet": "10.145.0.0/24", "type": "wg"}}})
NODES = {"n1": {"id": "n1", "name": "msk", "ifaces": {},
                "wdtt": {"wdtt7": {"fork": "qwdtt", "wg_addr": "10.66.70.1/30", "listen": "0.0.0.0:56000"}}},   # a pool of 1
         "n2": {"id": "n2", "name": "svo", "ifaces": {}}}


def roster():
    T = lambda n, i, ip, ty="awg": {"node": n, "iface": i, "ip": ip, "type": ty}
    return {"version": P.ROSTER_VERSION, "users": {"u1": {"name": "Anna"}, "u2": {"name": "Boris"}},
            "peers": {
                "a": {"id": "a", "user_id": "u1", "pubkey": K("A"), "psk": K("a"), "created_at": 100, "targets": [T("n1", "awg1", "10.8.0.5")]},
                "b": {"id": "b", "user_id": "u2", "pubkey": K("B"), "psk": K("b"), "created_at": 100, "targets": [T("n1", "awg2", "10.71.0.6")]},
                "w": {"id": "w", "user_id": "u2", "pubkey": "", "psk": "", "created_at": 100, "wdtt_password": "seat-holder",
                      "targets": [T("n1", "wdtt7", "", "wdtt")]},                                      # holds wdtt7's one seat
                "q": {"id": "q", "user_id": "u1", "pubkey": "", "psk": "", "created_at": 100, "wdtt_password": "keyless-q",
                      "targets": [T("n1", "wdtt7", "", "wdtt")]},                                      # no key yet
                # g1 carries an office network on n1; g2, OLDER, has the same prefix and lives on n2 — on n1 it would win it
                "g1": {"id": "g1", "user_id": "u1", "pubkey": K("G"), "created_at": 200, "routes": ["192.168.141.0/24"],
                       "share": {"users": {}}, "targets": [T("n1", "awg1", "10.8.0.40")]},
                "g2": {"id": "g2", "user_id": "u2", "pubkey": K("H"), "created_at": 50, "routes": ["192.168.141.0/24"],
                       "targets": [T("n2", "wgs1", "10.145.0.6", "wg")]},
            }}


D = tempfile.mkdtemp(prefix="targets-")
nodes_path, roster_path = os.path.join(D, "nodes.json"), os.path.join(D, "users.json")
CONF = os.path.join(D, "configs")
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {"n1": SNAP, "n2": SNAP2}, "stats_dir": D,
        "fleet": {"config_dir": CONF}, "panel_settings": json.loads(json.dumps(P.PANEL_SETTINGS_DEFAULTS))}


def reset():
    shutil.rmtree(D); os.makedirs(CONF)
    json.dump(NODES, open(nodes_path, "w"))
    json.dump(roster(), open(roster_path, "w"))


def files():
    """Every state file under D, by content — a refusal must leave them all as they were."""
    out = {}
    for dp, _dn, fns in os.walk(D):
        for fn in fns:
            out[os.path.relpath(os.path.join(dp, fn), D)] = hashlib.sha256(open(os.path.join(dp, fn), "rb").read()).hexdigest()
    return out


def door(body):
    try:
        return P.api("POST", "/api/peers/targets", {}, body, deps)
    except Exception as e:
        return 599, {"exception": repr(e)}


def peer(pid):
    return json.load(open(roster_path))["peers"][pid]


def tg(pid):
    return sorted((t["iface"], t.get("ip") or "") for t in peer(pid)["targets"])


def events():
    """The event log's lines, read through the panel (wherever it keeps them)."""
    c, b = P.api("GET", "/api/events", {"limit": ["200"]}, {}, deps)
    return [(e.get("verb"), e.get("detail")) for e in ((b.get("data") or {}).get("events") if isinstance(b.get("data"), dict) else b.get("data") or [])]


N = lambda i, ip="": {"node": "n1", "iface": i, **({"ip": ip} if ip else {})}

try:
    print("[1] a move onto a full turn server")
    reset()
    before = files()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "wdtt7", "ip": "", "type": "wdtt"}], "remove": [N("awg1")]})
    f = (b.get("fails") or [{}])
    check("[1] 409 refused, naming the full server", c == 409 and b.get("code") == "refused" and len(f) == 1
          and f[0].get("iface") == "wdtt7" and f[0].get("op") == "add" and f[0].get("code") == "turn_full"
          and "wdtt7 on msk is full" in (f[0].get("error") or ""), (c, b))
    check("[1] nothing written: every state file as it was, the peer still on awg1", files() == before and tg("a") == [("awg1", "10.8.0.5")], tg("a"))

    print("\n[2] the move onto a free interface")
    cfg = os.path.join(CONF, P.cfg_hash(K("A"), "n1", "awg1"))
    open(cfg, "w").write("legacy plaintext config")
    ev0 = events()
    body = {"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg"}], "remove": [N("awg1")]}
    c, b = door(body)
    check("[2] 200, the peer on awg2 alone", c == 200 and tg("a") == [("awg2", "10.71.0.5")] and [t["iface"] for t in b["data"]["targets"]] == ["awg2"], (c, b, tg("a")))
    retire = (json.load(open(nodes_path))["n1"].get("retire") or {}).get("awg1") or []
    check("[2] awg1 retired on the node, its stored config gone", K("A") in retire and not os.path.exists(cfg), (retire, os.path.exists(cfg)))
    new = events()[len(ev0):] if events()[:len(ev0)] == ev0 else events()
    verbs = sorted(v for v, _d in new)
    check("[2] one Added and one Removed line", verbs == ["Added deployment", "Removed deployment"], new)

    print("\n[3] the same Deploy again — its answer was lost")
    before = files()
    c, b = door(body)
    check("[3] 200 with the peer as it stands, nothing written", c == 200 and b.get("ok") and [t["iface"] for t in b["data"]["targets"]] == ["awg2"]
          and files() == before, (c, b))

    print("\n[4] a stale base")
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.9", "type": "awg"}]})
    check("[4] 409 changed, nothing written", c == 409 and b.get("code") == "changed" and "reopen" in (b.get("error") or "")
          and files() == before and tg("a") == [("awg2", "10.71.0.5")], (c, b, tg("a")))
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.77", "type": "awg"}], "remove": [N("awg1")]})
    check("[4] an add another tab made first at another address is not this one: 409 changed", c == 409 and b.get("code") == "changed"
          and files() == before, (c, b))

    print("\n[5] an address edit beside an add")
    c, b = door({"peer_id": "a", "base": [N("awg2")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.9", "type": "awg"}],
                 "address": [N("awg2", "10.71.0.6")]})                                                    # b holds .6
    f = b.get("fails") or [{}]
    check("[5] a taken address refuses the whole Deploy, the add not applied", c == 409 and b.get("code") == "refused"
          and [(x.get("op"), x.get("code")) for x in f] == [("address", "exists")] and files() == before, (c, b))
    c, b = door({"peer_id": "a", "base": [N("awg2")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.9", "type": "awg"}],
                 "address": [N("awg2", "10.71.0.9")]})
    check("[5] a free one: both applied", c == 200 and tg("a") == [("awg1", "10.8.0.9"), ("awg2", "10.71.0.9")], (c, b, tg("a")))
    check("[5] …with a Changed address line", any(v == "Changed address" and "10.71.0.9" in (d or "") for v, d in events()), events()[-4:])

    print("\n[6] a keyless peer's first key")
    body = {"peer_id": "q", "base": [N("wdtt7")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.8", "type": "awg"}],
            "pubkey": K("Q"), "psk": K("q")}
    c, b = door(body)
    p = peer("q")
    check("[6] applied: the key and PSK, its WDTT password as it was", c == 200 and p.get("pubkey") == K("Q") and p.get("psk") == K("q")
          and p.get("wdtt_password") == "keyless-q" and tg("q") == [("awg1", "10.8.0.8"), ("wdtt7", "")], (c, b))
    before = files()
    c, b = door(body)
    check("[6] the retry: 200, the peer holds that key, nothing written", c == 200 and b["data"].get("pubkey") == K("Q") and files() == before, (c, b))
    c, b = door({"peer_id": "q", "base": [N("wdtt7"), N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.8", "type": "awg"}],
                 "pubkey": K("R")})
    check("[6] another key: 409 key_changed, nothing written", c == 409 and b.get("code") == "key_changed" and files() == before, (c, b))

    print("\n[7] the rules of the body")
    c, b = door({"peer_id": "a", "base": [N("awg1"), N("awg2")], "remove": [N("awg1"), N("awg2")]})
    check("[7] every target removed → last_target, nothing written", c == 409 and b.get("code") == "last_target" and files() == before, (c, b))
    c, b = door({"peer_id": "a", "base": [N("awg1"), N("awg2")], "add": [{"node": "n1", "iface": "awg3", "ip": "10.9.0.2", "type": "awg"}],
                 "remove": [N("awg3")]})
    check("[7] an interface named twice → 400", c == 400 and b.get("code") == "bad_request" and files() == before, (c, b))

    print("\n[8] a deployment that would take a network over")
    c, b = door({"peer_id": "g2", "base": [{"node": "n2", "iface": "wgs1"}], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.40", "type": "awg"}],
                 "remove": [{"node": "n2", "iface": "wgs1"}]})
    f = b.get("fails") or [{}]
    check("[8] refused as network_refused, naming the prefix; nothing written", c == 409 and b.get("code") == "refused"
          and f[0].get("code") == "network_refused" and (f[0].get("refusals") or [{}])[0].get("prefix") == "192.168.141.0/24"
          and files() == before, (c, b))
finally:
    shutil.rmtree(D, ignore_errors=True)
    shutil.rmtree(TMPM, ignore_errors=True)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
