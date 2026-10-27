#!/usr/bin/env python3
"""Self-test — a router peer is never flagged by the torrent guard (docs/RELEASE-1.8.11-PLAN.md § S11b).

A user's report (1.8.10): a Keenetic router on awg0 NATs several devices. One device's DHT flagged the router's address,
and under Block every high-port flow from it was cut — a corporate OpenVPN (UDP 1194) on another device stopped until the
flag was deleted by hand. The flag judges an ADDRESS; a router is many devices. A peer marked "Router" now goes into the
node's never-flag set (@nofan, what mesh arrivals and bridge sources already get): its torrent packets are still dropped one
by one by signature, but nothing else of it is cut.

  THE PANEL (a REAL panel process: temp state, scratch port, no auth; the node is played by POSTing /api/node/sync)
    [1] /api/peers/update {shared: true} stores `shared`, and an event says so; an unrelated save (a title, a target's
        settings) keeps it; false clears the key (stored only when set), and anything but `true` is false; the event
        says the mark was removed; a save that changes nothing logs nothing
    [2] the sync carries `smart.p2p_shared` — this node's wg/awg /32s of the marked peers only: not another node's, not a
        keyless (WDTT) target, not an unmarked peer's, sorted and once
    [3] nobody marked → the key is absent (the reply a fleet that marks nobody always got)
    [4] /api/state carries the mark (the SPA reads it from there)
  THE NODE (the REAL swg-noded)
    [5] _p2p_nofan: the links alone when nothing is marked; a marked /32 added, sorted; v6, a prefix, junk and a /32 a link
        subnet already holds (the set has no auto-merge: an overlap refuses the whole table) left out
    [6] reconcile_cascade hands `smart.p2p_shared` to _ensure_p2p, and the table it loads carries the /32 in @nofan, which
        every flag write reads (`ip saddr != @nofan`)
    [7] on the real kernel (throwaway namespaces, `sudo -n`; said SKIPPED without), Block: two clients each send a DHT
        query, then an OpenVPN-shaped UDP flow to port 1194 — the router's DHT is still caught (dht 2) but it is never
        flagged and its OpenVPN flow leaves by the WAN; the unmarked client is flagged and its flow is cut

Run: python3 tests/p2p_router_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import json, os, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2p_policy_selftest as base   # load, Box, WIRE: the stand-in box and the namespace router the node's P2P gate uses

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PSRC = open(PANEL, encoding="utf-8").read()
NSRC = base.SRC

PLANTS = {   # name: (file, old text, planted text) — each re-introduces a defect the checks exist for
    "unpreserved":  ("panel", '              "routes", "share", "private", "shared"):', '              "routes", "share", "private"):'),
    "store-false":  ("panel", '            changed["shared"] = True if body.get("shared") is True else None', '            changed["shared"] = bool(body.get("shared"))'),
    "store-truthy": ("panel", '            changed["shared"] = True if body.get("shared") is True else None', '            changed["shared"] = True if body.get("shared") else None'),
    "no-event":     ("panel", '            ev_append(roster_path, "peer", pid, "Marked as a router" if changed["shared"] else "Router mark removed",',
                     '            (lambda *a: 0)(roster_path, "peer", pid, "Marked as a router" if changed["shared"] else "Router mark removed",'),
    "event-noop":   ("panel", '        if "shared" in changed and bool(changed["shared"]) != bool(p.get("shared")):', '        if "shared" in changed:'),
    "wire-unmarked": ("panel", '        if not isinstance(p, dict) or not p.get("shared"):\n            continue\n        for t in p.get("targets") or []:',
                      '        if not isinstance(p, dict):\n            continue\n        for t in p.get("targets") or []:'),
    "wire-allnodes": ("panel", 'if isinstance(t, dict) and t.get("node") == node_id and not _is_self_contained_target(t):',
                      'if isinstance(t, dict) and not _is_self_contained_target(t):'),
    "wire-keyless": ("panel", 'if isinstance(t, dict) and t.get("node") == node_id and not _is_self_contained_target(t):',
                     'if isinstance(t, dict) and t.get("node") == node_id:'),
    "wire-always":  ("panel", '**({"p2p_shared": _shr} if (_shr := p2p_shared_for_node(roster, nid)) else {}),',
                     '"p2p_shared": p2p_shared_for_node(roster, nid),'),
    "wire-unwired": ("panel", '**({"p2p_shared": _shr} if (_shr := p2p_shared_for_node(roster, nid)) else {}),', ''),
    "node-unread":  ("node", '                shared=(smart or {}).get("p2p_shared") or [])', '                shared=[])'),
    "node-dropped": ("node", ' and not any(n.subnet_of(h) for h in have):\n                out.add(str(n))', ' and not any(n.subnet_of(h) for h in have):\n                pass'),
    "node-overlap": ("node", ' and not any(n.subnet_of(h) for h in have):', ':'),
    "node-prefix":  ("node", 'if n.version == 4 and n.prefixlen == 32 and not', 'if n.version == 4 and not'),
    "node-links":   ("node", '        nofan = _p2p_nofan(node_cfg, shared)\n', '        nofan = _p2p_nofan(node_cfg, shared)[len(_p2p_link_nets(node_cfg)):]\n'),
}


def key(c):
    return (c * 43)[:43] + "="


NOW = int(time.time())


def roster():
    def peer(pid, ip, targets=None, shared=False):
        p = {"id": pid, "pubkey": key(pid[1].upper()), "psk": "PSK" + pid + "=", "user_id": "u1", "title": pid,
             "targets": targets or [{"node": "n1", "iface": "wg0", "type": "wg", "ip": ip}],
             "created_at": NOW - 100, "modified_at": NOW - 100}
        if shared:
            p["shared"] = True
        return p
    return {"version": 1, "users": {"u1": {"id": "u1", "name": "carol"}},
            "peers": {"pa": peer("pa", "10.8.0.2"),                                       # marked through the API in [1]
                      "pb": peer("pb", "10.8.0.3"),                                       # never marked
                      "pc": peer("pc", "", shared=True, targets=[{"node": "n1", "iface": "wg0", "type": "wg", "ip": "10.8.0.9"},
                                                                 {"node": "n2", "iface": "wg0", "type": "wg", "ip": "10.8.0.40"},
                                                                 {"node": "n1", "iface": "wdtt0", "type": "wdtt", "ip": "10.7.0.5"}])}}


def snapshot():
    meta = lambda sub: {"subnet": sub, "listen_port": 51820, "public_key": key("Z"), "address": sub.replace("0/24", "1/24")}
    return {"hostname": "node-a", "generated_at": int(time.time()), "noded_version": "t",
            "interfaces": {"wg0": {"peers": [], "meta": meta("10.8.0.0/24")}}}


def panel_checks(src, ok):
    tmp = tempfile.mkdtemp(prefix="p2p-router-")
    server = os.path.join(tmp, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src)
    state = os.path.join(tmp, "state"); os.makedirs(state); stats = os.path.join(tmp, "stats"); os.makedirs(stats)
    nodes, users = os.path.join(state, "nodes.json"), os.path.join(state, "users.json")
    json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}}},
               "n2": {"id": "n2", "name": "node-b", "ifaces": {"wg0": {}}}}, open(nodes, "w"))
    json.dump(roster(), open(users, "w"))
    fleet = os.path.join(tmp, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": users, "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(os.path.join(tmp, "panel.log"), "w+")
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                 "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                 "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

    def req(path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                                   headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def stored(pid):
        return json.load(open(users))["peers"][pid]

    def events():
        p = os.path.join(state, "events.jsonl")
        return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []

    def verbs():
        return [e.get("verb") for e in events() if e.get("verb") in ("Marked as a router", "Router mark removed")]

    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    ok(False, "the panel started (%s)" % open(log.name).read()[-600:]); return
                time.sleep(0.1)
        tok = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
        tok2 = req("/api/nodes/rotate", {"id": "n2"})[1]["data"]["token"]

        # [3] nobody marked yet but pc (another node's /32 and a keyless one only on n1 besides 10.8.0.9) — so first unmark pc
        c, r = req("/api/peers/update", {"peer_id": "pc", "shared": False})
        ok(c == 200 and "shared" not in stored("pc"), "[1] false clears the key — stored only when set (%s %s)" % (c, stored("pc").get("shared")))
        ok(verbs() == ["Router mark removed"], "[1] …and the event says the mark was removed (%s)" % verbs())
        c, r = req("/api/node/sync", {"snapshot": snapshot()}, tok)
        sm = (r.get("smart") or {})
        ok(c == 200 and "p2p_shared" not in sm, "[3] nobody marked → no p2p_shared on the wire (%s)" % sm.get("p2p_shared"))

        # [1] the door
        c, r = req("/api/peers/update", {"peer_id": "pa", "shared": True})
        ok(c == 200 and stored("pa").get("shared") is True, "[1] true stores the mark (%s %s)" % (c, stored("pa").get("shared")))
        ok(verbs() == ["Router mark removed", "Marked as a router"], "[1] …and an event says so (%s)" % verbs())
        req("/api/peers/update", {"peer_id": "pa", "shared": True})
        ok(verbs() == ["Router mark removed", "Marked as a router"], "[1] a save that changes nothing logs nothing (%s)" % verbs())
        req("/api/peers/update", {"peer_id": "pa", "title": "keenetic"})
        req("/api/peers/update-target", {"peer_id": "pa", "node": "n1", "iface": "wg0", "overrides": {"mtu": 1380}})
        ok(stored("pa").get("shared") is True and stored("pa").get("title") == "keenetic",
           "[1] a title save and a target's settings keep the mark (%s)" % stored("pa").get("shared"))
        c, r = req("/api/peers/update", {"peer_id": "pb", "shared": "yes"})
        ok(c == 200 and "shared" not in stored("pb"), "[1] anything but true is false (%s)" % stored("pb").get("shared"))
        req("/api/peers/update", {"peer_id": "pc", "shared": True})

        # [2] the wire
        c, r = req("/api/node/sync", {"snapshot": snapshot()}, tok)
        got = (r.get("smart") or {}).get("p2p_shared")
        ok(got == ["10.8.0.2/32", "10.8.0.9/32"],
           "[2] n1: its own wg/awg /32s of the marked peers — not n2's, not the keyless one, not the unmarked one (%s)" % got)
        c, r = req("/api/node/sync", {"snapshot": snapshot()}, tok2)
        got2 = (r.get("smart") or {}).get("p2p_shared")
        ok(got2 == ["10.8.0.40/32"], "[2] n2: only its own (%s)" % got2)

        # [4] the SPA's source
        c, st = req("/api/state")
        sp = (((st.get("data") or st).get("roster") or {}).get("peers") or {})
        ok((sp.get("pa") or {}).get("shared") is True and "shared" not in (sp.get("pb") or {}),
           "[4] /api/state carries the mark (%s)" % {k: (v or {}).get("shared") for k, v in sp.items()})
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


# [7] the namespace router of p2p_policy_selftest [25]: client 10.9.0.2 (the router) + 10.9.0.3, each a DHT get_peers and then
# an OpenVPN-shaped UDP flow to 1194; the WAN's postrouting counts what left. None = could not set up.
WIRE_ROUTER = base.WIRE.split("nft add element")[0].replace(
    "ip addr add 10.9.0.2/24 dev vc && ip link set vc up",
    "ip addr add 10.9.0.2/24 dev vc && ip addr add 10.9.0.3/24 dev vc && ip link set vc up") + r'''
nft -f - <<'EOT' || { echo SETUP-FAILED leave; kill $CPID; exit 0; }
table inet leave {
  counter v2 {}
  counter v3 {}
  chain post {
    type filter hook postrouting priority 300;
    oifname "eth0" ip saddr 10.9.0.2 udp dport 1194 counter name v2
    oifname "eth0" ip saddr 10.9.0.3 udp dport 1194 counter name v3
  }
}
EOT
nsenter -t "$CPID" -n python3 -c '
import os, socket, time
for src in ("10.9.0.2", "10.9.0.3"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((src, 0))
    s.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"9:info_hash20:" + os.urandom(20) + b"e1:q9:get_peers1:t2:aa1:y1:qe", ("198.51.100.7", 6881))
time.sleep(0.2)
for src in ("10.9.0.2", "10.9.0.3"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((src, 40000))
    for i in range(3):
        s.sendto(b"\x38" + os.urandom(40), ("198.51.100.200", 1194))
'
sleep 0.3
pk() { nft list counter inet "$1" "$2" | grep -o "packets [0-9]*" | grep -o "[0-9]*"; }
echo "FLAG $(nft list set inet swg_p2p flag | grep -o '10\.9\.0\.[0-9]*' | sort | tr '\n' ' ')"
echo "DHT $(pk swg_p2p dht)"
echo "LEFT $(pk leave v2) $(pk leave v3)"
kill $CPID 2>/dev/null
'''


def _wire_router(table):
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(table)
    try:
        r = subprocess.run(["sudo", "-n", "unshare", "-n", "bash", "-s", f.name], input=WIRE_ROUTER, capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    finally:
        os.unlink(f.name)
    out = {ln.split(" ", 1)[0]: ln.split(" ", 1)[1].strip() for ln in (r.stdout or "").splitlines() if " " in ln}
    return None if "FLAG" not in out or "LEFT" not in out else (out["FLAG"].split(), out.get("DHT", ""), out["LEFT"].split())


def node_checks(src, ok):
    m = base.load(src)
    # [5] the set's contents
    m._relay_links = lambda cfg: ["swg_n"]
    m._iface_subnet = lambda cfg, ln: "10.255.0.0/31"
    links = m._p2p_link_nets({})
    ok(m._p2p_nofan({}, []) == links == ["10.255.0.0/31"] and m._p2p_nofan({}, None) == links,
       "[5] nothing marked → the links alone (%s)" % m._p2p_nofan({}, []))
    got = m._p2p_nofan({}, ["10.8.0.9/32", "10.8.0.2/32", "10.8.0.2", "fd00::2/128", "10.8.0.0/24", "junk", 7, "10.255.0.1/32"])
    ok(got == ["10.255.0.0/31", "10.8.0.2/32", "10.8.0.9/32"],
       "[5] marked /32s added once and sorted; v6, a prefix, junk and a /32 inside a link subnet left out (%s)" % got)

    # [6] the reconcile hands the list over, and the table carries it
    seen = []
    m2 = base.load(src)
    m2.run = lambda a, input_text=None, timeout=20: types.SimpleNamespace(returncode=0, stdout="", stderr="")
    m2.GEO_DIR = tempfile.mkdtemp()
    for fn in ("_ensure_fwd_iptables", "_ensure_sni_router", "_ensure_smart_xtstring", "reconcile_catk_chain", "_ensure_smart_dnsmasq",
               "_dnsmasq_refill", "_ensure_doh_block", "_ensure_mech_block", "_smart_geo_refresh", "_smart_load_cidrs",
               "_panel_list_refresh", "_apply_routing_reset", "_smart_domain_refresh"):
        setattr(m2, fn, (lambda *a, **k: ({}, {})) if fn == "_smart_domain_refresh" else (lambda *a, **k: None))
    m2._ensure_smart_nft = lambda *a, **k: {}
    m2._cascade_local_routes = lambda cfg, _proc=None: []
    m2._ensure_p2p = lambda *a, **k: seen.append(k.get("shared"))
    m2.reconcile_cascade({"interfaces": {}}, {}, {"entries": [], "p2p": None, "p2p_shared": ["10.8.0.2/32"]})
    ok(seen == [["10.8.0.2/32"]], "[6] reconcile_cascade hands smart.p2p_shared to _ensure_p2p (%s)" % seen)

    m3 = base.load(src); b = base.Box()
    m3.run = b.run; m3.GEO_DIR = tempfile.mkdtemp()
    m3._relay_links = lambda cfg: ["swg_n"]; m3._iface_subnet = lambda cfg, ln: "10.255.0.0/31"
    m3._ensure_p2p(None, {"10.8.0.0/24": ["torrents"]}, {}, {"changed": 0, "errors": []}, shared=["10.8.0.2/32"])
    text = "".join(i or "" for a, i in b.cmds if a[:2] == ["nft", "-f"])
    ok("set nofan { typeof ip saddr; flags interval; elements = { 10.255.0.0/31, 10.8.0.2/32 } }" in text
       and text.count("ip saddr != @nofan") >= 3,
       "[6] the loaded table holds the /32 in @nofan beside the mesh link's subnet, read by every flag write (%s)"
       % [ln.strip() for ln in text.splitlines() if "set nofan" in ln])

    # [7] the real kernel
    if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
        print("  SKIPPED [7] real-kernel router — no `sudo -n` here")
        return
    m._relay_links = lambda cfg: ()
    tbl = m._p2p_nft("block", [], [], m._p2p_nofan({}, ["10.9.0.2/32"]), True)
    got = _wire_router(tbl)
    if got is None:
        print("  SKIPPED [7] real-kernel router — the throwaway namespaces could not be set up here")
        return
    flag, dht, left = got
    ok(dht == "2", "[7] both DHT queries are still caught by signature, the router's too (dht %s)" % dht)
    ok(flag == ["10.9.0.3"], "[7] the router is never flagged; the unmarked client is (flag %s)" % flag)
    ok(left == ["3", "0"], "[7] the router's OpenVPN flow leaves by the WAN; the flagged client's is cut (left %s)" % left)


def run_checks(psrc, nsrc):
    fails = []
    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
    node_checks(nsrc, ok)
    panel_checks(psrc, ok)
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (which, old, new) in PLANTS.items():
            src = PSRC if which == "panel" else NSRC
            if src.count(old) != 1:
                print("PLANT %-14s anchor missing — fix the plant" % name); missed.append(name); continue
            p = src.replace(old, new)
            f = run_checks(p, NSRC) if which == "panel" else run_checks(PSRC, p)
            print("PLANT %-14s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC, NSRC)
    print("p2p_router_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
