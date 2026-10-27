#!/usr/bin/env python3
"""Self-test — ports the torrent filter never cuts (docs/RELEASE-1.8.11-PLAN.md § S11c).

The flag cuts a flagged source's flows to ports >= 1024 except @portok, which was hard-coded: a laptop that torrented lost
its own corporate OpenVPN / WireGuard with it. The list is now the operator's — a fleet default (Settings, beside Never
block, pre-filled with the built-ins + 1194 + 51820) and a per-node override. @portok is read by the ONE shape every flag
cut, fan-out count and flagged re-route uses; signatures never read it, so a torrent to an exempt port is still caught.

  THE NODE (the REAL swg-noded)
    [1] _p2p_portok — the port rules' own `_ports_spans`: canonical (merged, sorted); absent, empty, junk, out of range or
        past 32 entries → the built-in list — never an empty set (a syntax error) and never "nothing exempt"
    [2] _ensure_p2p renders `set portok` from the wire; absent → the built-in list
    [3] reconcile_cascade hands `smart.p2p_portok` to _ensure_p2p
    [4] the built-in list is one list in three places: swg-noded, the panel, the SPA (and has 1194 + 51820)
    [5] on the real nft a merged list loads; on the real kernel (throwaway namespaces, `sudo -n`; SKIPPED without) a FLAGGED
        source's UDP flow to an exempt port leaves by the WAN, to a port next to it is cut, and a DHT query to the exempt
        port is still dropped (dht counted)
  THE PANEL (a REAL panel process: temp state, scratch port, no auth; the node is played by POSTing /api/node/sync)
    [6] settings save — the port rules' grammar (`ports_clean`): stored merged and sorted; an en dash reads as a hyphen; the
        defaults, or null, store no key; a bad entry is refused by name, a 0 in a JSON list too (never dropped), digits
        that are not ASCII too; past 32 entries is refused saying so; an empty list is refused
    [7] node save: its own list stored; null clears it; a bad entry refused
    [8] the wire: on the defaults no key (the reply a fleet always got); a fleet list reaches every node; a node's own list
        reaches only that node; a node whose own list IS the built-in list gets no key even while the fleet's differs; a
        stored value that is not a list counts as absent
    [9] /api/state carries both (the SPA reads them there; a node field not published is posted back empty by the next save)

Run: python3 tests/p2p_portok_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import json, os, re, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2p_policy_selftest as base   # load, Box, WIRE: the node's P2P gate harness

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PSRC = open(PANEL, encoding="utf-8").read()
NSRC = base.SRC
MODEL = open(os.path.join(ROOT, "js", "model.js"), encoding="utf-8").read()

PLANTS = {   # name: (file, old text, planted text)
    "node-first-only": ("node", '    ps = _ports_spans({"proto": "both", "list": v.replace(" ", "")}) if isinstance(v, str) else None',
                        '    ps = (lambda r: (r[0], r[1][:1]) if r else r)(_ports_spans({"proto": "both", "list": v.replace(" ", "")})) if isinstance(v, str) else None'),
    "node-hard":    ("node", '"  set portok { typeof th dport; flags interval; elements = { %s } }" % portok,', '"  set portok { typeof th dport; flags interval; elements = { %s } }" % _P2P_PORTOK,'),
    "node-unread":  ("node", '                portok=(smart or {}).get("p2p_portok"))', '                portok=None)'),
    "node-nodefault": ("node", '_P2P_PORTOK = "1194, 3478-3481, 4500, 5222-5223, 5349, 8801-8810, 19302-19309, 27000-27200, 51820"',
                       '_P2P_PORTOK = "3478-3481, 4500, 5222-5223, 5349, 8801-8810, 19302-19309, 27000-27200"'),
    "panel-twin":   ("panel", 'P2P_PORTOK_DEFAULT = ["1194", "3478-3481",', 'P2P_PORTOK_DEFAULT = ["3478-3481",'),
    "panel-number-empty": ("panel", '    if not isinstance(raw, str):                              # a number, an object: named, never read as "empty" (s11c F15)\n        return None, perr("Not a port or a port range (1-65535): {v1}", v1=str(raw)[:40])\n',
                           '    raw = raw if isinstance(raw, str) else None\n'),
    "panel-dropzero": ("panel", '        raw = " ".join(str(x) for x in raw)', '        raw = " ".join(str(x) for x in raw if x)'),
    "panel-noname": ("panel", '    return None, perr("Not a port or a port range (1-65535): {v1}", v1=", ".join(bad[:5]) or str(raw)[:40])',
                     '    return None, perr("Not a port or a port range (1-65535): {v1}", v1="")'),
    "panel-empty":  ("panel", '    if canon == "empty":\n        return None, perr("Keep at least one port', '    if canon == "empty":\n        return [], None\n        return None, perr("Keep at least one port'),
    "panel-keepdefault": ("panel", '                if _pok == P2P_PORTOK_DEFAULT:\n                    cur.pop("p2p_portok", None)', '                if False:\n                    cur.pop("p2p_portok", None)'),
    "node-save-unwired": ("panel", '        if "p2p_portok" in body:                # this node\'s own never-cut ports', '        if False:                # this node\'s own never-cut ports'),
    "wire-always":  ("panel", '    return None if eff == P2P_PORTOK_DEFAULT else ", ".join(eff)', '    return ", ".join(eff)'),
    "wire-fleetonly": ("panel", '    eff = own if isinstance(own, list) and own else fleet', '    eff = fleet'),
    "wire-string":  ("panel", '    eff = own if isinstance(own, list) and own else fleet if isinstance(fleet, list) and fleet else P2P_PORTOK_DEFAULT',
                     '    eff = own or fleet or P2P_PORTOK_DEFAULT'),
    "wire-unwired": ("panel", '**({"p2p_portok": _pokw} if (_pokw := p2p_portok_wire(_ps, node)) else {}),', ''),
    "unpublished":  ("panel", '                        "p2p_portok": c.get("p2p_portok") if isinstance(c.get("p2p_portok"), list) else None,\n', ''),
}


def key(c):
    return (c * 43)[:43] + "="


# [5] the namespace router of p2p_policy_selftest [25]: client 10.9.0.2, FLAGGED; a DHT get_peers to :1194, then three UDP
# packets to :1194 and three to :1195; the WAN's postrouting counts what left. None = could not set up.
WIRE_PORTOK = base.WIRE.split("nft add element")[0] + r'''
nft add element inet swg_p2p flag '{ 10.9.0.2 timeout 10m }'
nft -f - <<'EOT' || { echo SETUP-FAILED leave; kill $CPID; exit 0; }
table inet leave {
  counter ok {}
  counter cut {}
  chain post {
    type filter hook postrouting priority 300;
    oifname "eth0" udp dport 1194 counter name ok
    oifname "eth0" udp dport 1195 counter name cut
  }
}
EOT
nsenter -t "$CPID" -n python3 -c '
import os, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("10.9.0.2", 0))
s.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"9:info_hash20:" + os.urandom(20) + b"e1:q9:get_peers1:t2:aa1:y1:qe", ("198.51.100.9", 1194))
for port in (1194, 1195):
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(("10.9.0.2", 40000 + port))
    for i in range(3):
        u.sendto(b"\x38" + os.urandom(40), ("198.51.100.200", port))
'
sleep 0.3
pk() { nft list counter inet "$1" "$2" | grep -o "packets [0-9]*" | grep -o "[0-9]*"; }
echo "DHT $(pk swg_p2p dht)"
echo "LEFT $(pk leave ok) $(pk leave cut)"
kill $CPID 2>/dev/null
'''


def _wire(table, script):
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(table)
    try:
        r = subprocess.run(["sudo", "-n", "unshare", "-n", "bash", "-s", f.name], input=script, capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    finally:
        os.unlink(f.name)
    return {ln.split(" ", 1)[0]: ln.split(" ", 1)[1].strip() for ln in (r.stdout or "").splitlines() if " " in ln}


def node_checks(src, psrc, ok):
    m = base.load(src)
    D = m._P2P_PORTOK
    # [1]
    ok(m._p2p_portok("51820, 1194 , 3478-3481, 3480-3500, 7000") == "1194, 3478-3500, 7000, 51820",
       "[1] canonical: merged and sorted (%s)" % m._p2p_portok("51820, 1194 , 3478-3481, 3480-3500, 7000"))
    ok(m._p2p_portok("1194, 1195-1200") == "1194-1200", "[1] adjacent ranges join (%s)" % m._p2p_portok("1194, 1195-1200"))
    bad = [None, "", "  ", 7, "x", "0", "70000", "9-8", ", ".join(str(2000 + 2 * i) for i in range(33))]
    got = [m._p2p_portok(b) for b in bad]
    ok(all(g == D for g in got), "[1] absent, empty, junk, out of range, reversed or past the port rules' 32 entries → the built-in list (%s)"
       % [b for b, g in zip(bad, got) if g != D][:3])
    # [2]
    def table(portok):
        mm = base.load(src); b = base.Box()
        mm.run = b.run; mm.GEO_DIR = tempfile.mkdtemp(); mm._relay_links = lambda cfg: ()
        mm._ensure_p2p(None, {"10.8.0.0/24": ["torrents"]}, {}, {"changed": 0, "errors": []}, portok=portok)
        return "".join(i or "" for a, i in b.cmds if a[:2] == ["nft", "-f"])
    t1, t0 = table("51820, 1194"), table(None)
    ok("set portok { typeof th dport; flags interval; elements = { 1194, 51820 } }" in t1, "[2] the wire's list renders @portok")
    ok("set portok { typeof th dport; flags interval; elements = { %s } }" % D in t0, "[2] no wire → the built-in list")
    # [3]
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
    m2._ensure_p2p = lambda *a, **k: seen.append(k.get("portok"))
    m2.reconcile_cascade({"interfaces": {}}, {}, {"entries": [], "p2p": None, "p2p_portok": "1194, 51820"})
    ok(seen == ["1194, 51820"], "[3] reconcile_cascade hands smart.p2p_portok to _ensure_p2p (%s)" % seen)
    # [4]
    pm = re.search(r'^P2P_PORTOK_DEFAULT = (\[.*\])', psrc, re.M)
    jm = re.search(r'^export const P2P_PORTOK_DEFAULT = (\[.*\]);', MODEL, re.M)
    pl = json.loads(pm.group(1)) if pm else None
    jl = json.loads(jm.group(1)) if jm else None
    ok(pl is not None and jl is not None and ", ".join(pl) == D and jl == pl and "1194" in pl and "51820" in pl,
       "[4] one built-in list in swg-noded, the panel and the SPA, with 1194 and 51820 (%s | %s | %s)" % (D, pl, jl))
    # [5]
    if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
        print("  SKIPPED [5] real nft / kernel — no `sudo -n` here")
        return
    merged = m._p2p_portok("1194, 3478-3500, 3490-3510, 51820, 1195-1199")
    tl = m._p2p_nft("block", [], [], [], True, portok=merged)
    out = _wire(tl, "nft -f \"$1\" && echo LOADED yes")
    ok(out is not None and out.get("LOADED") == "yes", "[5] a merged list loads on the real nft (%s)" % merged)
    tb = m._p2p_nft("block", [], [], [], True, portok=m._p2p_portok("1194, 51820"))
    out = _wire(tb, WIRE_PORTOK)
    if not out or "LEFT" not in out:
        print("  SKIPPED [5] real kernel — the throwaway namespaces could not be set up here")
        return
    ok(out["LEFT"].split() == ["3", "0"], "[5] a flagged source's flow to the exempt port leaves, to the next port is cut (left %s)" % out["LEFT"])
    ok(out.get("DHT") == "1", "[5] a DHT query to the exempt port is still caught by signature (dht %s)" % out.get("DHT"))


def panel_checks(src, ok):
    tmp = tempfile.mkdtemp(prefix="p2p-portok-")
    server = os.path.join(tmp, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src)
    state = os.path.join(tmp, "state"); os.makedirs(state); stats = os.path.join(tmp, "stats"); os.makedirs(stats)
    nodes, users = os.path.join(state, "nodes.json"), os.path.join(state, "users.json")
    json.dump({"n1": {"id": "n1", "name": "node-a", "ifaces": {"wg0": {}}},
               "n2": {"id": "n2", "name": "node-b", "ifaces": {"wg0": {}}}}, open(nodes, "w"))
    json.dump({"version": 1, "users": {}, "peers": {}}, open(users, "w"))
    fleet = os.path.join(tmp, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": users, "stats_dir": stats,
               "panel_settings_path": os.path.join(state, "panel-settings.json")}, open(fleet, "w"))
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

    def snapshot():
        return {"hostname": "n", "generated_at": int(time.time()), "noded_version": "t",
                "interfaces": {"wg0": {"peers": [], "meta": {"subnet": "10.8.0.0/24", "listen_port": 51820, "public_key": key("Z"),
                                                             "address": "10.8.0.1/24"}}}}

    def wire(tok):
        c, r = req("/api/node/sync", {"snapshot": snapshot()}, tok)
        return (r.get("smart") or {}).get("p2p_portok", "ABSENT") if c == 200 else "SYNC %s" % c

    def ps():
        c, st = req("/api/state")
        return ((st.get("data") or st).get("panel_settings") or {})

    def stnode(nid):
        c, st = req("/api/state")
        ns = (st.get("data") or st).get("nodes") or []
        ns = ns.values() if isinstance(ns, dict) else ns
        return next((n for n in ns if n.get("id") == nid), {})

    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    ok(False, "the panel started (%s)" % open(log.name).read()[-600:]); return
                time.sleep(0.1)
        t1 = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
        t2 = req("/api/nodes/rotate", {"id": "n2"})[1]["data"]["token"]
        # [8] the defaults: no key
        ok(wire(t1) == "ABSENT" and wire(t2) == "ABSENT", "[8] on the defaults no p2p_portok on the wire")
        # [6]
        c, r = req("/api/panel/settings", {"p2p_portok": "51820 1194, 3478-3481 3480-3500"})
        ok(c == 200 and ps().get("p2p_portok") == ["1194", "3478-3500", "51820"],
           "[6] the fleet list is stored merged and sorted (%s %s)" % (c, ps().get("p2p_portok")))
        ok(wire(t1) == "1194, 3478-3500, 51820" and wire(t2) == "1194, 3478-3500, 51820", "[8] a fleet list reaches every node (%s)" % wire(t1))
        c, r = req("/api/panel/settings", {"p2p_portok": "1194, 70000, x"})
        ok(c == 400 and "70000" in json.dumps(r) and ps().get("p2p_portok") == ["1194", "3478-3500", "51820"],
           "[6] a bad entry is refused by name, nothing changed (%s %s)" % (c, str(r)[:120]))
        c, r = req("/api/panel/settings", {"p2p_portok": ""})
        ok(c == 400, "[6] an empty list is refused (%s)" % c)
        c, r = req("/api/panel/settings", {"p2p_portok": 1194})
        ok(c == 400 and "empty" not in json.dumps(r).lower() and "Keep at least one" not in json.dumps(r) and "1194" in json.dumps(r),
           "[6] a number (not a list or text) is named, never read as empty (s11c F15) (%s %s)" % (c, str(r)[:120]))
        c, r = req("/api/panel/settings", {"p2p_portok": [0, 1194]})
        ok(c == 400 and ps().get("p2p_portok") == ["1194", "3478-3500", "51820"], "[6] a 0 in a JSON list is refused, never dropped (%s)" % c)
        c, r = req("/api/panel/settings", {"p2p_portok": "\u0661\u0661\u0669\u0664"})
        ok(c == 400, "[6] digits that are not ASCII are refused, as the browser does (%s)" % c)
        c, r = req("/api/panel/settings", {"p2p_portok": " ".join(str(2000 + i) for i in range(33))})
        ok(c == 400 and "32" in json.dumps(r), "[6] past the port rules' 32 entries is refused, saying so (%s %s)" % (c, str(r)[:100]))
        c, r = req("/api/panel/settings", {"p2p_portok": "1194, 19302\u201319309, 51820"})
        ok(c == 200 and ps().get("p2p_portok") == ["1194", "19302-19309", "51820"], "[6] an en dash reads as a hyphen (%s %s)" % (c, ps().get("p2p_portok")))
        req("/api/panel/settings", {"p2p_portok": "51820 1194, 3478-3481 3480-3500"})
        # [7] + [8] the node's own
        c, r = req("/api/nodes/update", {"id": "n2", "p2p_portok": "1194, 8443"})
        ok(c == 200 and json.load(open(nodes))["n2"].get("p2p_portok") == ["1194", "8443"], "[7] a node's own list is stored (%s)" % c)
        ok(wire(t2) == "1194, 8443" and wire(t1) == "1194, 3478-3500, 51820", "[8] a node's own list reaches only that node (%s | %s)" % (wire(t2), wire(t1)))
        ok(stnode("n2").get("p2p_portok") == ["1194", "8443"] and stnode("n1").get("p2p_portok") is None,
           "[9] /api/state publishes the node's own list (%s)" % stnode("n2").get("p2p_portok"))
        req("/api/nodes/update", {"id": "n2", "p2p_portok": ", ".join(["1194", "3478-3481", "4500", "5222-5223", "5349", "8801-8810", "19302-19309", "27000-27200", "51820"])})
        ok(wire(t2) == "ABSENT", "[8] a node whose own list is the built-in one gets no key while the fleet's differs (%s)" % wire(t2))
        _nd = json.load(open(nodes)); _nd["n1"]["p2p_portok"] = "1194"; json.dump(_nd, open(nodes, "w"))
        ok(wire(t1) == "1194, 3478-3500, 51820", "[8] a stored value that is not a list (a hand edit) counts as absent — never its characters (%s)" % wire(t1))
        _nd = json.load(open(nodes)); _nd["n1"].pop("p2p_portok", None); json.dump(_nd, open(nodes, "w"))
        c, r = req("/api/nodes/update", {"id": "n2", "p2p_portok": "1194, 0"})
        ok(c == 400, "[7] a bad entry on the node is refused (%s)" % c)
        c, r = req("/api/nodes/update", {"id": "n2", "p2p_portok": None})
        ok(c == 200 and "p2p_portok" not in json.load(open(nodes))["n2"], "[7] null clears the node's own list (%s)" % c)
        # [6] back to the defaults → no key
        c, r = req("/api/panel/settings", {"p2p_portok": None})
        ok(c == 200 and "p2p_portok" not in ps(), "[6] null stores no key (%s)" % ps().get("p2p_portok"))
        req("/api/panel/settings", {"p2p_portok": "8443"})
        c, r = req("/api/panel/settings", {"p2p_portok": "51820, 1194, 3478-3481, 4500, 5222-5223, 5349, 8801-8810, 19302-19309, 27000-27200"})
        ok(c == 200 and "p2p_portok" not in ps() and wire(t1) == "ABSENT", "[6] the defaults typed out store no key, and the wire has none (%s)" % ps().get("p2p_portok"))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


def run_checks(psrc, nsrc):
    fails = []
    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
    node_checks(nsrc, psrc, ok)
    panel_checks(psrc, ok)
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (which, old, new) in PLANTS.items():
            src = PSRC if which == "panel" else NSRC
            if src.count(old) != 1:
                print("PLANT %-17s anchor missing — fix the plant" % name); missed.append(name); continue
            p = src.replace(old, new)
            f = run_checks(p, NSRC) if which == "panel" else run_checks(PSRC, p)
            print("PLANT %-17s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC, NSRC)
    print("p2p_portok_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
