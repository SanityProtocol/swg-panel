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
  [9] "already done" is exact (review F2/F3/F11): a retry of a Deploy whose draft lost an add since → changed, not done; an
      add stored with other settings → changed; a keyless add sent with an address, sent again → done
  [10] what a body may carry (F4/F7/F45): an add onto another peer's address → refused (exists); a non-string node / iface / ip,
      a psk or pubkey that is not a key → 400, never stored, never a crash; a key another door gave the peer → key_changed
  [11] a network refusal names the keyed add that takes it, not a keyless one beside it (F10)
  [12] removals retire every key in one nodes.json write (F12)
  [13] the verify round and F42: the sheet's key after another tab rotated it → key_changed; an address edit on a keyless
      deployment is never "done", an empty address included (F51, F58); a key with a newline, a non-string peer_id → 400 (F52, F54); an add at another
      peer's IPv6 address written differently → exists (F53)

Run: python3 tests/peer_targets_move_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     nobase      the base check off                                   [4]
     nodone      a change already made is not answered as done        [3]
     doneip      an add at another address counts as done              [4]
     doneset     "done" asks only for this Deploy's own rows           [9]
     doneov      "done" ignores an add's settings                     [9]
     nofails     the collected refusals are not acted on              [1]
     noretire    a removal leaves the key on the node                 [2]
     notakeover  the takeover check skipped in this door              [8]
     addrtaken   an add may take another peer's address               [10]
     keytype     pubkey / psk taken as sent                           [10]
     keyguard    a key other than the peer's is taken                 [10]
     netkeyless  a network refusal names a keyless add                 [11]
     donekeyless an address edit on a keyless deployment counts as done [13]
     doneempty   an empty-address edit on a keyless deployment is done [13]
     keynl       a key with a trailing newline passes                 [13]
     addrtext    addresses compared as text                           [13]
"""
import importlib.machinery, importlib.util, hashlib, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "nobase": ('        if {key(x) for x in lists["base"]} != set(have):\n', '        if False:\n'),
    "nodone": ('                and (not nk or p.get("pubkey") == nk)):\n', '                and (not nk or p.get("pubkey") == nk)) and False:\n'),
    "doneip": ('        same = lambda t, x: is_keyless_kind(t.get("type") or "") or ipof(t) == ipof(x)', '        same = lambda t, x: True'),
    "doneset": ('        if (set(have) == ({key(x) for x in lists["base"]} - gone) | {key(x) for x in lists["add"]}\n',
                '        if (all(key(x) in have for x in lists["add"]) and not any(key(x) in have for x in lists["remove"])\n'),
    "doneov": (' and clean_overrides(have[key(x)].get("overrides")) == clean_overrides(x.get("overrides"))\n', '\n'),
    "addrtaken": ('        if addr_taken(roster, pid, target["node"], target["iface"], _ip):\n', '        if False:\n'),
    "keytype": ('        if not (_str(nk, True) and _str(psk, True)) or any(k and not _WG_KEY_RE.fullmatch(k) for k in (nk, psk)):\n', '        if False:\n'),
    "keyguard": ('    if nk and p.get("pubkey") and nk != p["pubkey"]:\n', '    if False:\n'),
    "donekeyless": ('                and all(key(x) in have and ipof(x) and ipof(have[key(x)]) == ipof(x) for x in lists["address"])',
                    '                and all(key(x) in have and same(have[key(x)], x) for x in lists["address"])'),
    "doneempty": ('and all(key(x) in have and ipof(x) and ipof(have[key(x)])', 'and all(key(x) in have and ipof(have[key(x)])'),
    "keynl": ("any(k and not _WG_KEY_RE.fullmatch(k) for k in (nk, psk))", "any(k and not _WG_KEY_RE.match(k) for k in (nk, psk))"),
    "addrtext": ('                if a == ip or (":" in a and norm(a) == want):', '                if a == ip:'),
    "netkeyless": ('next(t["iface"] for t in adds if t["node"] == nid and not is_keyless_kind(t["type"]))', 'next(t["iface"] for t in adds if t["node"] == nid)'),
    "nofails": ('        if fails:\n            return 409, {"ok": False, "error": "nothing was changed"', '        if False:\n            return 409, {"ok": False, "error": "nothing was changed"'),
    "noretire": ('            retire_pubkey(nodes, deps["nodes_path"], [{"node": x["node"], "iface": x["iface"]} for x in lists["remove"]], old_key)\n', '            pass\n'),
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
                "wdtt": {"wdtt7": {"fork": "qwdtt", "wg_addr": "10.66.70.1/30", "listen": "0.0.0.0:56000"},     # a pool of 1
                         "wdtt8": {"fork": "qwdtt", "wg_addr": "10.66.80.1/24", "listen": "0.0.0.0:56001"}}},
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
    """The event log's lines, newest first, read through the panel."""
    c, b = P.api("GET", "/api/events", {"limit": ["200"]}, {}, deps)
    return [(e.get("verb"), e.get("detail")) for e in b.get("data") or []]


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
    new = events()[:len(events()) - len(ev0)]          # newest first: the lines this Deploy wrote
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
    check("[4] …with the peer as it stands (a sheet whose lost Deploy took its key keeps it)", (b.get("data") or {}).get("pubkey") == K("A"), b)
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
    check("[5] …with a Changed address line", any(v == "Changed address" and "10.71.0.9" in (d or "") for v, d in events()), events()[:4])

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

    print("\n[9] \"already done\" is exact")
    reset()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg"},
                                                              {"node": "n2", "iface": "wgs1", "ip": "10.145.0.9", "type": "wg"}]})
    check("[9] two adds applied (their answer lost)", c == 200 and len(peer("a")["targets"]) == 3, (c, b))
    before = files()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg"}]})
    check("[9] the draft unticked one since: not done — 409 changed, nothing written", c == 409 and b.get("code") == "changed" and files() == before, (c, b))
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg", "overrides": {"mtu": 1300}},
                                                              {"node": "n2", "iface": "wgs1", "ip": "10.145.0.9", "type": "wg"}]})
    check("[9] the same adds with other settings: not done — 409 changed, nothing written", c == 409 and b.get("code") == "changed" and files() == before, (c, b))
    body = {"peer_id": "a", "base": [N("awg1"), N("awg2"), {"node": "n2", "iface": "wgs1"}], "add": [{"node": "n1", "iface": "wdtt8", "ip": "10.66.80.2", "type": "wdtt"}]}
    c, b = door(body)
    check("[9] a keyless add sent with an address: stored with none", c == 200 and ("wdtt8", "") in tg("a"), (c, b, tg("a")))
    before = files()
    c, b = door(body)
    check("[9] …sent again: done, nothing written", c == 200 and files() == before, (c, b))

    print("\n[10] what a body may carry")
    reset()
    before = files()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.6", "type": "awg"}], "remove": [N("awg1")]})
    f = b.get("fails") or [{}]
    check("[10] a move onto another peer's address (b holds .6): refused, exists, nothing written", c == 409 and b.get("code") == "refused"
          and [(x.get("iface"), x.get("code")) for x in f] == [("awg2", "exists")] and files() == before and tg("a") == [("awg1", "10.8.0.5")], (c, b))
    bad = [("an int iface", {"add": [{"node": "n1", "iface": 7, "ip": "10.9.0.2"}]}),
           ("a list node", {"add": [{"node": ["n1"], "iface": "awg2", "ip": "10.71.0.9"}]}),
           ("an int ip", {"add": [{"node": "n1", "iface": "awg2", "ip": 5}]}),
           ("a NaN psk", {"peer_id": "q", "base": [N("wdtt7")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.8"}], "pubkey": K("Q"), "psk": float("nan")}),
           ("a pubkey that is not a key", {"peer_id": "q", "base": [N("wdtt7")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.8"}], "pubkey": "x"})]
    for what, extra in bad:
        c, b = door(dict({"peer_id": "a", "base": [N("awg1")]}, **extra))
        check("[10] %s → 400, nothing written" % what, c == 400 and b.get("code") == "bad_request" and files() == before, (c, b))
    r = json.load(open(roster_path)); r["peers"]["q"]["pubkey"] = K("Z"); json.dump(r, open(roster_path, "w"))   # another door keyed it
    before = files()
    c, b = door({"peer_id": "q", "base": [N("wdtt7")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.8", "type": "awg"}], "pubkey": K("Q")})
    check("[10] a key another door gave the peer, same interfaces: 409 key_changed, nothing written", c == 409 and b.get("code") == "key_changed"
          and files() == before, (c, b))

    print("\n[11] a network refusal names the keyed add")
    reset()
    c, b = door({"peer_id": "g2", "base": [{"node": "n2", "iface": "wgs1"}], "add": [{"node": "n1", "iface": "wdtt8", "ip": "", "type": "wdtt"},
                                                                                   {"node": "n1", "iface": "awg2", "ip": "10.71.0.40", "type": "awg"}]})
    f = b.get("fails") or [{}]
    check("[11] refused, naming awg2 (not wdtt8, which carries no networks)", c == 409 and [(x.get("iface"), x.get("code")) for x in f] == [("awg2", "network_refused")], (c, b))

    print("\n[12] removals retire in one write")
    reset()
    first = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg"},
                                                              {"node": "n2", "iface": "wgs1", "ip": "10.145.0.9", "type": "wg"}]})
    saves, _save = [], P.nodes_save
    P.nodes_save = lambda *a, **k: (saves.append(1), _save(*a, **k))[1]
    try:
        c, b = door({"peer_id": "a", "base": [N("awg1"), N("awg2"), {"node": "n2", "iface": "wgs1"}], "remove": [N("awg1"), {"node": "n2", "iface": "wgs1"}]})
    finally:
        P.nodes_save = _save
    ns = json.load(open(nodes_path))
    ret = lambda n, i: (ns[n].get("retire") or {}).get(i) or []
    check("[12] both keys retired, one nodes.json write", first[0] == 200 and c == 200 and K("A") in ret("n1", "awg1")
          and K("A") in ret("n2", "wgs1") and len(saves) == 1, (first[0], c, b, len(saves)))

    print("\n[13] the verify round and F42")
    reset()
    r = json.load(open(roster_path)); r["peers"]["a"]["pubkey"] = K("Y"); json.dump(r, open(roster_path, "w"))   # another tab rotated it
    before = files()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "10.71.0.5", "type": "awg"}], "pubkey": K("A")})
    check("[13] the sheet's key after another tab rotated it: 409 key_changed, nothing written", c == 409 and b.get("code") == "key_changed"
          and files() == before, (c, b))
    c, b = door({"peer_id": "w", "base": [N("wdtt7")], "address": [N("wdtt7", "10.66.70.2")]})
    f = b.get("fails") or [{}]
    check("[13] an address edit on a keyless deployment: refused, not \"done\"", c == 409 and b.get("code") == "refused"
          and f[0].get("op") == "address" and files() == before, (c, b))
    c, b = door({"peer_id": "w", "base": [N("wdtt7")], "address": [{"node": "n1", "iface": "wdtt7", "ip": ""}]})
    check("[13] …an empty address on it: refused too, not \"done\" (F58)", c == 409 and b.get("code") == "refused" and files() == before, (c, b))
    for what, extra in (("a pubkey with a trailing newline", {"peer_id": "q", "base": [N("wdtt7")], "add": [{"node": "n1", "iface": "awg1", "ip": "10.8.0.8"}],
                                                              "pubkey": K("Q") + "\n"}),
                        ("a list peer_id", {"peer_id": ["a"], "base": [N("awg1")]})):
        c, b = door(extra)
        check("[13] %s → 400, nothing written" % what, c == 400 and b.get("code") == "bad_request" and files() == before, (c, b))
    r = json.load(open(roster_path)); r["peers"]["b"]["targets"][0]["ip"] = "fd00::5"; json.dump(r, open(roster_path, "w"))
    before = files()
    c, b = door({"peer_id": "a", "base": [N("awg1")], "add": [{"node": "n1", "iface": "awg2", "ip": "FD00:0::5", "type": "awg"}], "pubkey": K("Y")})
    f = b.get("fails") or [{}]
    check("[13] an add at b's IPv6 address written another way: refused, exists", c == 409 and [(x.get("iface"), x.get("code")) for x in f] == [("awg2", "exists")]
          and files() == before, (c, b))
finally:
    shutil.rmtree(D, ignore_errors=True)
    shutil.rmtree(TMPM, ignore_errors=True)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
