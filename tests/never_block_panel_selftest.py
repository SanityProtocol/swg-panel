#!/usr/bin/env python3
"""Self-test — the Never-block list, the panel's half (docs/NEVER-BLOCK-AND-PORT-RULES-PLAN.md A.2–A.4, 1.8.11 S5 A2), driven
through a REAL panel process (temp state, scratch port, no auth; nodes played by POSTing snapshots). Two block lists are
already resolved on disk — hagezi `light` (names, the `ads` category) and FireHOL level1 (addresses, `malware_ip`) — so the
sync builds its unions the way production does.

  n-dns   Force-DNS, wg0 filters ads + malware_ip        → a host union and an ip union
  n-sni   Hybrid SNI, no filter                           → no union
  n-ip    IP-only, wg0 filters ads + malware_ip           → the ip union only (host lists do not run there)

  [1] the setting: names and IPv4 addresses/ranges stored in canonical form (lower case, host bits masked, deduplicated);
      a zone, a pattern, an AS number, IPv6 and a range wider than /8 are each refused, named, and nothing is stored;
      over the cap is refused, at once, before any entry is read; an entry ipaddress cannot read (zero-padded octets) or
      holding a space or line break is refused, named, never a 500; an empty list removes the key
  [2] the wire: `smart.allow` carries the names to n-dns only — not to IP-only n-ip, not to n-sni with no host union, not
      when the list holds addresses alone; with no list no node's reply carries the key
  [3] the address cut renames the ip union (n-dns and n-ip alike: a new list, loaded at once), a list of names alone keeps
      every union's name, and clearing the list brings the old name back; the host union's name never moves
  [4] the node card: a Force-DNS node filtering by name whose noded does not report `allow` is told to update while the
      list holds names; not once it reports `allow`, not on IP-only, not with addresses alone, and not once its name list is
      no longer on disk (no host union runs there — the card asks by the datapath's own rule)

Run: python3 tests/never_block_panel_selftest.py      (0 = pass)
     --plant nowire     the sync never sends `smart.allow`                                    → RED on [2]
     --plant noname     the address cut leaves the ip union's name as it was                  → RED on [3]
     --plant nocard     the node card never asks                                              → RED on [4]
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "nowire": ("[2]", '                                          **({"allow": list(_nb_names)}', '                                          **({}'),
    "noname": ("[3]", '    al = ("al:" + ",".join(allow) + ";") if allow else ""', '    al = ""'),
    "nocard": ("[4]", "    if never_block and _srp is not None and not _srp.get(\"allow\"):", "    if False:"),
}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="never-block-panel-")
server = SERVER
if PLANT:
    _s, old, new = PLANTS[PLANT]
    src = open(SERVER).read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    server = os.path.join(TMP, "planted-server.py")
    open(server, "w").write(src.replace(old, new, 1))

ST = os.path.join(TMP, "state"); os.makedirs(os.path.join(ST, "lists")); SD = os.path.join(TMP, "stats"); os.makedirs(SD)
NODES = {"n-dns": {"routing_mode": "forcedns", "ifaces": {"wg0": {"block": ["ads", "malware_ip"]}}},
         "n-sni": {"routing_mode": "sni", "ifaces": {"wg0": {}}},
         "n-ip": {"routing_mode": "kernel", "ifaces": {"wg0": {"block": ["ads", "malware_ip"]}}}}
json.dump({n: dict(v, id=n, name=n, links={}) for n, v in NODES.items()}, open(os.path.join(ST, "nodes.json"), "w"))
open(os.path.join(ST, "users.json"), "w").write("{}\n")
json.dump({"block_catalog": {"categories": {c: {"enabled_nodes": list(NODES)} for c in ("ads", "malware_ip")}}},
          open(os.path.join(ST, "panel-settings.json"), "w"))
NOW = int(time.time())
for key, body in (("blk_hagezi_light__host", "ads.example.net\ntracker.example.com\n"),
                  ("blk_firehol_firehol_level1__ip", "203.0.113.0/24\n198.51.100.0/24\n")):
    open(os.path.join(ST, "lists", key + ".txt"), "w").write(body)
    json.dump({"v": "t1", "at": NOW, "n": 2}, open(os.path.join(ST, "lists", key + ".meta"), "w"))
FLEET = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": os.path.join(ST, "nodes.json"), "roster_path": os.path.join(ST, "users.json"), "stats_dir": SD}, open(FLEET, "w"))
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
LOG = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=LOG, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": FLEET, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "",
                             "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


try:
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(LOG.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in NODES}

    def sync(nid, allow_cap=False):
        snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t",
                "interfaces": {"wg0": {"peers": [], "meta": {"public_key": "8Y1mOEM2Uv3Ez6CUfXOvsUg0dNrV4kx0mB9rp1cV3lE=", "listen_port": 51820,
                                                              "mtu": 1280, "subnet": "10.60.0.0/24", "address": "10.60.0.1/24"}}},
                "smartroute": {"mode": NODES[nid]["routing_mode"], "engine": "dns", "engine_ok": True, **({"allow": 1} if allow_cap else {})}}
        code, r = req("/api/node/sync", {"snapshot": snap}, TOK[nid])
        assert code == 200, (code, r)
        return r

    def smart(r):
        return ((r.get("desired") or {}).get("smart") if isinstance(r.get("desired"), dict) else None) or r.get("smart") or {}

    def unions(r, tier):
        sm = smart(r)
        ents = sm.get("entries") if isinstance(sm, dict) and "entries" in sm else None
        cats = set(sm.get("categories") or []) if isinstance(sm, dict) else set()
        return sorted(c for c in cats if c.startswith("blku:" + tier + ":"))

    def settled(nid, allow_cap=False):
        r = None
        for _ in range(40):                                  # the union is registered on the first sync, built off the request path
            r = sync(nid, allow_cap)
            if unions(r, "ip") or nid == "n-sni":
                return r
            time.sleep(0.25)
        return r

    def settings():
        return json.load(open(os.path.join(ST, "panel-settings.json")))

    SECTION[0] = "[0]"
    base = {n: settled(n) for n in NODES}
    check("the fixture: n-dns has a host and an ip union, n-ip an ip union only, n-sni none",
          unions(base["n-dns"], "host") and unions(base["n-dns"], "ip") and unions(base["n-ip"], "ip") and not unions(base["n-ip"], "host")
          and not unions(base["n-sni"], "ip") and not unions(base["n-sni"], "host"),
          {n: (unions(r, "host"), unions(r, "ip")) for n, r in base.items()})
    check("no list: no reply carries `allow`", not any("allow" in smart(r) for r in base.values()), {n: sorted(smart(r)) for n, r in base.items()})

    SECTION[0] = "[1]"
    print("\n[1] the setting")
    code, r = req("/api/panel/settings", {"block_allow": ["Example.COM", "https://Shop.example.org/cart", "203.0.113.7",
                                                          "198.51.100.9/24", "example.com", "10.1.0.0/8"]})
    check("names and addresses are stored canonical (lower case, URL stripped, host bits masked, deduplicated)",
          code == 200 and settings().get("block_allow") == ["example.com", "shop.example.org", "203.0.113.7/32", "198.51.100.0/24", "10.0.0.0/8"],
          (code, r, settings().get("block_allow")))
    for bad, why in (("*.ru", "a zone"), ("first.*", "a pattern"), ("AS13335", "an AS number"), ("2001:db8::/32", "IPv6"),
                     ("0.0.0.0/4", "wider than /8")):
        code, r = req("/api/panel/settings", {"block_allow": ["ok.example", bad]})
        check("refused, named: %s (%s) — and nothing stored" % (bad, why),
              code == 400 and bad.lower().split("/")[0] in json.dumps(r).lower() and settings().get("block_allow", [])[:1] == ["example.com"],
              (code, r))
    code, r = req("/api/panel/settings", {"block_allow": ["h%d.example" % i for i in range(501)]})
    check("over 500 entries: refused", code == 400, (code, r))
    t0 = time.time()
    code, r = req("/api/panel/settings", {"block_allow": ["h%d.example" % i for i in range(50000)]})
    check("a 50 000-entry paste: refused at once (under 2 s), the lock held for nothing", code == 400 and time.time() - t0 < 2,
          (code, round(time.time() - t0, 2)))
    for bad, why in (("010.1.1.1", "zero-padded octets"), ("example\n.com", "a line break inside one entry"),
                     ("a.example b.example", "a space inside one entry")):
        code, r = req("/api/panel/settings", {"block_allow": ["ok.example", bad]})
        check("refused, named, 400 not 500: %r (%s)" % (bad, why),
              code == 400 and bad.split()[0].lower() in json.dumps(r).lower() and settings().get("block_allow", [])[:1] == ["example.com"],
              (code, r))
    code, r = req("/api/panel/settings", {"block_allow": []})
    check("an empty list removes the key", code == 200 and "block_allow" not in settings(), settings().get("block_allow"))

    SECTION[0] = "[2]"
    print("\n[2] the wire")
    req("/api/panel/settings", {"block_allow": ["cdn.tracker.example.com", "ads.example.net", "198.51.100.7"]})
    w = {n: settled(n) for n in NODES}
    check("Force-DNS with a host union: `allow` = the names, sorted, no address",
          smart(w["n-dns"]).get("allow") == ["ads.example.net", "cdn.tracker.example.com"], smart(w["n-dns"]).get("allow"))
    check("IP-only: no `allow` (host lists do not run there)", "allow" not in smart(w["n-ip"]), smart(w["n-ip"]).get("allow"))
    check("Hybrid SNI with no host union: no `allow`", "allow" not in smart(w["n-sni"]), smart(w["n-sni"]).get("allow"))
    req("/api/panel/settings", {"block_allow": ["198.51.100.7"]})
    w2 = {n: settled(n) for n in NODES}
    check("addresses alone: no `allow` anywhere", not any("allow" in smart(r) for r in w2.values()))

    SECTION[0] = "[3]"
    print("\n[3] union names")
    check("the address cut renames the ip union on n-dns and n-ip (a new list, loaded at once)",
          unions(w2["n-dns"], "ip") != unions(base["n-dns"], "ip") and unions(w2["n-ip"], "ip") != unions(base["n-ip"], "ip")
          and unions(w2["n-dns"], "ip") == unions(w2["n-ip"], "ip"), (unions(base["n-dns"], "ip"), unions(w2["n-dns"], "ip")))
    check("…and never the host union", unions(w2["n-dns"], "host") == unions(base["n-dns"], "host"))
    req("/api/panel/settings", {"block_allow": ["example.com"]})
    w3 = {n: settled(n) for n in NODES}
    check("names alone: every union keeps its name", all(unions(w3[n], t) == unions(base[n], t) for n in NODES for t in ("ip", "host")))
    req("/api/panel/settings", {"block_allow": []})
    w4 = {n: settled(n) for n in NODES}
    check("the list cleared: the old names are back", all(unions(w4[n], t) == unions(base[n], t) for n in NODES for t in ("ip", "host")))

    SECTION[0] = "[4]"
    print("\n[4] the node card")
    CARD = "Never-block list's site names need a node update"

    def issues(nid):
        st = req("/api/state")[1]
        nd = next((n for n in ((st.get("data") or st).get("nodes") or []) if n.get("id") == nid), {})
        return json.dumps(nd.get("issues") or [])

    req("/api/panel/settings", {"block_allow": ["example.com"]})
    for n in NODES:
        settled(n)
    check("names on the list, Force-DNS node filtering by name, noded without `allow`: told to update", CARD in issues("n-dns"), issues("n-dns"))
    check("…not the IP-only node", CARD not in issues("n-ip"), issues("n-ip"))
    check("…not a node with no filter", CARD not in issues("n-sni"), issues("n-sni"))
    settled("n-dns", allow_cap=True)
    check("once noded reports `allow`: no card", CARD not in issues("n-dns"), issues("n-dns"))
    settled("n-dns")
    req("/api/panel/settings", {"block_allow": ["198.51.100.7"]})
    check("addresses alone: no card (the panel cuts them for every version)", CARD not in issues("n-dns"), issues("n-dns"))
    req("/api/panel/settings", {"block_allow": ["example.com"]})
    os.remove(os.path.join(ST, "lists", "blk_hagezi_light__host.txt"))   # the name list gone: no host union runs on n-dns
    r = settled("n-dns")
    check("no name list ready on the node: no host union, no `allow`, no card", not unions(r, "host") and "allow" not in smart(r)
          and CARD not in issues("n-dns"), (unions(r, "host"), issues("n-dns")))
finally:
    proc.terminate()
    try:
        proc.wait(10)
    except Exception:
        proc.kill()

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
