#!/usr/bin/env python3
"""Self-test: a node that reports a shape the panel cannot read is handled per FIELD, not per accident.

A snapshot is remote input and `swg-noded` reconciles ONLY on a 200 — so a field whose shape a reader cannot
handle does not merely lose a chart. It raises inside the sync handler, the node gets a 500, and it never
converges again: its peers freeze where they are and the panel says "offline", which is the one thing that
is not wrong with it. Five long-shipped fields could do this. The realistic trigger is version skew — a node
newer than its panel sending a shape this build does not expect.

⚠️ THE ANSWER IS NOT THE SAME FOR EVERY FIELD, and that is the whole point of this gate:

  TELEMETRY (`inet`, `cat_rate`, `exit_rate`) — a lost sample is a gap in a graph. Cleaned and kept, so the
    node keeps syncing and no reader downstream needs a guard of its own.
  STATE (`interfaces`, `wdtt`, `csqtt`) — these say what the node is RUNNING. Syncing a malformed one as
    empty would read as every peer on that node having vanished; refusing leaves it stale, and `reconcile.js`
    deliberately never counts a stale node's peers as missing. So refusing is right — what was wrong was that
    the refusal was a silent 500. It is a 400 with a reason, recorded on the node and said on its card.

1.8.9 qualification R2 PANEL-1 — ONE LEVEL FURTHER IN. The state check stopped at "each entry is an object", and the
readers walk on into a few fields as given: a string `interfaces.*.meta` failed EVERY node's sync (cascade_plan plans the
whole fleet), a non-object `ip_forward` / `rp_filter` / turn-proxy or a non-string WDTT / csqtt `listen` gave /api/state a
500 for every operator, and a NaN / Infinity (a JSON token, a literal past a double's range, a telemetry string) came back
out of /api/state as a bare token the browser's r.json() refuses — the console froze. [5] the sanitiser drops exactly
those sub-fields; [6] on the wire, one node's report touches no other node's sync and no operator's console, and its
non-finite number is refused at the door; [7] a REAL snapshot (one of the test fleet's, reduced and anonymised below;
SWG_SNAP_FIXTURES=<a dir of mirrored stats-*.json> runs whole real ones too) goes through the door and the sanitiser byte
for byte — small fleets feel nothing.

Hermetic ([6] and [7] run a real panel on a loopback scratch port, everything under a temp dir).
Run: python3 tests/snap_shape_selftest.py (0 = pass).  --perturb makes the sanitiser a no-op and
expects the malformed shapes to sail through.  --perturb-<meta|listwalk|forward|listen|turnproxies|door|snapnum> takes
out one PANEL-1 line each (exit 0 when caught).
"""
import atexit, copy, importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PLANT = next((a[len("--perturb-"):] for a in sys.argv if a.startswith("--perturb-")), "")
# Each puts back exactly one PANEL-1 line as it was at d0bad281 (the anchor must match once, or the run measures nothing).
PLANTS = {
    "meta": ('    for blk in (snap["interfaces"].values() if isinstance(snap.get("interfaces"), dict) else ()):\n'
             '        if not isinstance(blk.get("meta") or {}, dict):\n'
             '            del blk["meta"]\n', ""),
    # …and the walk taken unguarded: a LIST of interface objects passes the state check, and `.values()` then raised
    # inside the sanitiser — at the warm start, outside any try, that is a panel that does not boot.
    "listwalk": ('snap["interfaces"].values() if isinstance(snap.get("interfaces"), dict) else ()',
                 '(snap.get("interfaces") or {}).values()'),
    "forward": ('    for k in ("ip_forward", "rp_filter"):\n'
                '        if not isinstance(snap.get(k) or {}, dict):\n'
                '            del snap[k]\n', ""),
    "listen": ('    for k in ("wdtt", "csqtt"):\n'
               '        for e in (snap[k] if isinstance(snap.get(k), list) else ()):\n'
               '            if not isinstance(e.get("listen") or "", str):\n'
               '                del e["listen"]\n', ""),
    "turnproxies": ('    if not isinstance(snap.get("turn_proxies") or [], list):\n'
                    '        del snap["turn_proxies"]                         # a map or a string walks as its keys / letters\n'
                    '    elif snap.get("turn_proxies"):\n'
                    '        snap["turn_proxies"] = [t for t in snap["turn_proxies"] if isinstance(t, dict)]\n', ""),
    "door": ('json.loads(raw or "{}", parse_constant=_json_finite, parse_float=_json_finite)', 'json.loads(raw or "{}")'),
    "snapnum": ("    return n if math.isfinite(n) else None\n", "    return n\n"),
}
TMP = tempfile.mkdtemp(prefix="snap-shape-")
atexit.register(shutil.rmtree, TMP, True)          # every exit, an early one too
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r — one of %s" % (PLANT, ", ".join(PLANTS)))
    _src = open(PANEL, encoding="utf-8").read()
    if _src.count(PLANTS[PLANT][0]) != 1:
        sys.exit("PLANT %s anchor missing — this run would measure nothing" % PLANT)
    PANEL = os.path.join(TMP, "swg-panel-server")
    open(PANEL, "w", encoding="utf-8").write(_src.replace(*PLANTS[PLANT]))

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)

_l = importlib.machinery.SourceFileLoader("swgpanel", PANEL)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
_san = P._snap_sanitise
if PERTURB:
    P._snap_sanitise = lambda snap: None          # accepts anything, cleans nothing — how it shipped

print("\n[1] telemetry is CLEANED, and the node keeps syncing")
for field, bad, why in (("inet", "nope", "a string where a rate map goes"),
                        ("cat_rate", [1, 2], "a list"),
                        ("exit_rate", {"d": 5}, "an entry that is not an object")):
    s = {"generated_at": 1, field: bad}
    err = P._snap_sanitise(s)
    check("%s: %s is dropped, not refused" % (field, why),
          err is None and not s.get(field), (err, s.get(field)))
s = {"inet": {"up": "5000", "down": None, "junk": "x"}}
check("a numeric STRING counts — this project's own nodes send them", P._snap_sanitise(s) is None
      and s["inet"].get("up") == 5000.0, s.get("inet"))
# `None` coerces to 0.0 — "reported nothing this pass" IS zero for a rate. Only a value that cannot be read
# as a number at all (`"x"`) is dropped, because guessing a rate from it would be inventing data.
check("a null rate reads as zero", s["inet"].get("down") == 0.0, s["inet"])
check("…and an unreadable one is simply absent", "junk" not in s["inet"], s["inet"])
s = {"exit_rate": {"tun0": {"up": "7", "down": 2}, "bad": 9, "empty": {"up": "x"}}}
P._snap_sanitise(s)
check("a rate map keeps its good entries and drops the rest",
      s["exit_rate"] == {"tun0": {"up": 7.0, "down": 2.0}}, s["exit_rate"])

# `generated_at` is cleaned the same way, and for the same reason: three readers int() it — fp_converged on
# every convergence check, the warm start at boot — so an unparseable one used to raise THERE. A node sending an
# ISO string (a plausible future build) could stop a sync mid-flight, or keep the panel from starting.
for bad, want in (("1700000000", 1700000000), (1700000000.9, 1700000000), ("x", None), ({}, None), (None, None)):
    s = {"generated_at": bad, "interfaces": {}}
    err = P._snap_sanitise(s)
    got = s.get("generated_at")
    check("generated_at %r is cleaned to %r, never refused" % (bad, want), err is None and got == want, (err, got))
check("a good generated_at is left exactly as it was", P._snap_sanitise(s := {"generated_at": 42}) is None
      and s["generated_at"] == 42, s)

print("\n[2] malformed STATE is refused, with a reason that names the field")
for field, bad in (("interfaces", {"awg0": "x"}), ("interfaces", "x"),
                   ("wdtt", ["x"]), ("csqtt", 7), ("csqtt", {"c1": 3})):
    err = P._snap_sanitise({"generated_at": 1, field: bad})
    check("%s = %r is refused" % (field, bad), bool(err), err)
    check("…and the reason names the field", bool(err) and field in err, err)

print("\n[3] a well-formed snapshot is left alone")
good = {"generated_at": 1, "interfaces": {"awg0": {"up": True, "peers": []}},
        "wdtt": {"w1": {"fork": "x"}}, "csqtt": [{"iface": "c1"}],
        "inet": {"up": 10, "down": 20}, "exit_rate": {"tun0": {"up": 1, "down": 2}}}
import copy
before = copy.deepcopy(good)
check("no refusal", P._snap_sanitise(good) is None)
check("state is untouched", good["interfaces"] == before["interfaces"] and good["wdtt"] == before["wdtt"]
      and good["csqtt"] == before["csqtt"], good)
check("telemetry survives as numbers", good["inet"] == {"up": 10.0, "down": 20.0}
      and good["exit_rate"] == {"tun0": {"up": 1.0, "down": 2.0}}, (good["inet"], good["exit_rate"]))

print("\n[4] BOTH doors into the snapshot cache run it")
# ⚠️ The readers downstream state this as an invariant instead of re-checking it, so a door that skipped the
# sanitiser would put back exactly the value the other one refuses. The warm-start seed is the easy one to
# forget: those files were written by an EARLIER run, possibly one that stored a shape this build cannot read.
lines = open(PANEL, encoding="utf-8").read().splitlines()
doors = [i for i, l in enumerate(lines)
         if ("node_snaps" in l and "=" in l and l.strip().endswith(("= snap", "= _snap")))]
check("both entry points into node_snaps were found", len(doors) == 2,
      [lines[i].strip()[:60] for i in doors])
near = [i for i in doors if any("_snap_sanitise" in lines[j] for j in range(max(0, i - 14), i + 1))]
check("…and neither seeds the cache without sanitising first", len(near) == len(doors) == 2,
      [lines[i].strip()[:60] for i in doors if i not in near])

print("\n[5] PANEL-1 — a sub-field the readers walk into, of another shape, is DROPPED (never refused), and only that")
# The readers (q189 R2 PANEL-1): cascade_plan's `(blk.get("meta") or {}).get(…)` on every node's sync; _node_issues'
# `(snap.get("ip_forward") or {}).get(…)`, `tp.get(…)` and `(listen or "").strip()` on every /api/state poll.
def _san(over):
    s = {"generated_at": 1, "interfaces": {"wg1": {"peers": [], "meta": {"subnet": "10.9.0.0/24"}}}}
    s.update(copy.deepcopy(over))
    try:
        return P._snap_sanitise(s), s
    except Exception as e:                         # an int(inf) inside the sanitiser itself — the node's own sync 500s
        return "RAISED %s: %s" % (type(e).__name__, e), s
for label, over, want in (
        ("interfaces.*.meta = 'x'", {"interfaces": {"wg1": {"peers": [], "meta": "x"}}},
         lambda s: s["interfaces"] == {"wg1": {"peers": []}}),
        ("interfaces.*.meta = [1]", {"interfaces": {"wg1": {"peers": [], "meta": [1]}}},
         lambda s: s["interfaces"] == {"wg1": {"peers": []}}),
        ("ip_forward = true", {"ip_forward": True}, lambda s: "ip_forward" not in s),
        ("rp_filter = 'on'", {"rp_filter": "on"}, lambda s: "rp_filter" not in s),
        ("turn_proxies = ['x', {…}]", {"turn_proxies": ["x", {"service": "t1"}]},
         lambda s: s["turn_proxies"] == [{"service": "t1"}]),
        ("turn_proxies = {service: {…}} (walks as its keys)", {"turn_proxies": {"t1": {}}}, lambda s: "turn_proxies" not in s),
        ("wdtt[0].listen = 443", {"wdtt": [{"iface": "wdtt1", "listen": 443}]}, lambda s: s["wdtt"] == [{"iface": "wdtt1"}]),
        ("csqtt[0].listen = [':443']", {"csqtt": [{"iface": "csqtt1", "listen": [":443"]}]},
         lambda s: s["csqtt"] == [{"iface": "csqtt1"}]),
        ("inet.up = 'inf' (float() reads it, JSON cannot carry it)", {"inet": {"up": "inf", "down": 1}},
         lambda s: s["inet"] == {"down": 1.0}),
        ("cat_rate.x.up = '1e999'", {"cat_rate": {"x": {"up": "1e999", "dn": 2}}}, lambda s: s["cat_rate"] == {"x": {"dn": 2.0}}),
        ("generated_at = 'inf'", {"generated_at": "inf"}, lambda s: "generated_at" not in s)):
    err, s = _san(over)
    check("%s: dropped, not refused — the rest kept" % label, err is None and want(s), (err, s))
_nothing = {"ip_forward": None, "rp_filter": {}, "turn_proxies": [], "wdtt": [{"iface": "w", "listen": ""}],
            "csqtt": [{"iface": "c", "listen": None}], "interfaces": {"wg1": {"peers": [], "meta": None}}}
err, s = _san(_nothing)
check("a value every reader already reads as nothing is left exactly as it was",
      err is None and s == {"generated_at": 1, **_nothing}, (err, s))
err, s = _san({"interfaces": [{"peers": [], "meta": "x"}], "wdtt": {"w1": {"listen": 443}}})
check("a shape the state check passes and these walks do not take (a LIST of interfaces, a MAP of WDTT servers) leaves the "
      "sanitiser standing — it runs at boot, outside any try", err is None, err)

# One of the test fleet's own snapshots (msk-main, 1.8.8-beta by its stamp, d81cba17 by content: two interfaces — one a
# mesh link —, a turn proxy, a WDTT and a csqtt server, and the telemetry), as the panel mirrored it on 2026-10-09:
# reduced to one item per list / map, keys and public addresses replaced; every field's TYPE is the node's own.
FIXTURE = (
    '{"generated_at":1791575180,"hostname":"node-a","noded_version":"1.8.8-beta","kind":"baremetal","interfaces":{"awg2":{"peers":[{"public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=",'
    '"endpoint":null,"preshared_key":"x","allowed_ips":"x","rx_bytes":0,"tx_bytes":0,"rx_speed":0.0,"tx_speed":0.0,'
    '"last_handshake":null,"handshake_age":null,"online":false,"hs_gap_med":null,"hs_seen":0,"ep_moves":0,"hs_bytes_med":null}],'
    '"meta":{"public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=","listen_port":443,"mtu":1280,"endpoint":"203.0.113.10:443",'
    '"address":"10.9.0.1/24","subnet":"10.9.0.0/24","awg_params":{"Jc":4,"Jmin":40,"Jmax":70,"S1":28,"S2":94,"S3":88},'
    '"tool":"awg","dns":["203.0.113.11"],"backup_public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK="},"onboarded":false,'
    '"boot_persist":true},"swg_002cdb7b":{"peers":[{"public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=","endpoint":"203.0.113.12:9999",'
    '"preshared_key":"x","allowed_ips":"x","rx_bytes":2927285884,"tx_bytes":277263979,"rx_speed":0.0,"tx_speed":0.0,'
    '"last_handshake":1791575126,"handshake_age":54,"online":true,"hs_gap_med":36.0,"hs_seen":8,"ep_moves":0,"hs_bytes_med":51268.5}],'
    '"meta":{"public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=","listen_port":10001,"mtu":1420,"endpoint":"203.0.113.10:10001",'
    '"address":"10.255.0.1/31","subnet":"10.255.0.0/31","awg_params":{"Jc":4,"Jmin":40,"Jmax":70,"S1":60,"S2":56,"S3":16},'
    '"tool":"awg","dns":["203.0.113.11"],"backup_public_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK="},"onboarded":false,'
    '"boot_persist":true}},"turn_proxies":[{"service":"vk-turn-proxy-fork-56004","listen":"203.0.113.10:56004","connect":"127.0.0.1:51821",'
    '"wrap_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=","params":"-turn x","bind":"203.0.113.10:56004","bind_ip":"",'
    '"running":true,"restarts":0,"version":"v3.0.0","src_ips":[]}],"wdtt":[{"iface":"wdtt1","service":"swg-wdtt-wdtt1",'
    '"active":"active","listen":"203.0.113.10:56000","bind":"203.0.113.10:56000","bind_ip":"","wg_addr":"10.11.0.1/24",'
    '"wg_port":56001,"server_pub":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=","stopped":false,"fork":"amurcanov",'
    '"raw_port":"","raw_iface":"","raw_addr":"","version":"1.2.4-3","max_passwords":200,"params":"-turn x","dns":"203.0.113.11",'
    '"dns_unsupported":false,"rx_bytes":0,"tx_bytes":4752,"rx_speed":0,"tx_speed":0,"adopt_users":{},"passwords":{"pas1":{"device_id":"",'
    '"up_bytes":0,"down_bytes":0,"is_deactivated":false,"expires_at":0,"online":false,"ip":"10.11.0.2","raw_ip":"",'
    '"rx_speed":0,"tx_speed":0}},"devices":{"dev1":{"ip":"10.11.0.2","pub_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=",'
    '"raw_ip":""}},"src_ips":[]}],"csqtt":[{"iface":"csqtt1","service":"swg-csqtt-csqtt1","active":"active","listen":"203.0.113.10:56002",'
    '"bind":"203.0.113.10:56002","bind_ip":"","tun_addr":"10.10.0.1/24","web_port":57002,"stopped":false,"kind":"csqtt",'
    '"fork":"csqtt","version":"2.1.9-4","line":"2.1","max_passwords":500,"params":"-turn x","dns":"203.0.113.11","dns_server":"203.0.113.11",'
    '"rx_bytes":0,"tx_bytes":4752,"rx_speed":0,"tx_speed":0,"adopt_users":{},"passwords":{"pas1":{"device_id":"x","up_bytes":1613204064,'
    '"down_bytes":1298217030,"is_deactivated":false,"expires_at":0,"ip":"10.10.0.2","online":false,"rx_speed":0,"tx_speed":0}},'
    '"devices":{"dev1":{"ip":"10.10.0.3","pub_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK="}},"src_ips":[]}],'
    '"ip_forward":{"needed":true,"ok":true},"rp_filter":{"needed":true,"bad":[]},"inet":{"up":0.0,"down":0.0},"cat_rate":{"c0":{"up":0.0,'
    '"dn":0.0},"c1":{"up":0.0,"dn":0.0}},"exit_rate":{"wgx-00000001":{"up":0.0,"down":0.0}},"log":{"mb":100,"used_mb":49.2,'
    '"oldest":1791136149,"live":1,"range":1},"smartroute":{"mode":"sni","engine":"sni_user","engine_ok":true,"sni_alive":true,'
    '"dnsmasq":false,"route_localnet":true,"src":1,"arr":1,"caps_keep":1,"p2p":{"state":"ok","mode":"block"},"lowered":{"zone":26,'
    '"ends":1,"contains":1},"active":true,"rules":151,"resets":0},"mesh_health":{"swg_002cdb7b":{"peer":"10.255.0.0",'
    '"rtt_ms":0.891,"mdev_ms":0.402,"rtt_min":0.587,"rtt_max":2.353,"loss":0.0,"peak_loss":0.0,"last_loss_s":null,"probes":30,'
    '"probe_every_s":60,"probe_size":1200,"window_sent":600,"window_lost":0,"at":1791575144},"swg_4d548000":{"peer":"10.255.0.2",'
    '"rtt_ms":0.757,"mdev_ms":0.1,"rtt_min":0.538,"rtt_max":0.983,"loss":0.0,"peak_loss":0.0,"last_loss_s":null,"probes":30,'
    '"probe_every_s":60,"probe_size":1200,"window_sent":600,"window_lost":0,"at":1791575148}},"iface_drops":{"wg8":{"pct":0.0,'
    '"window_pkts":369,"window_bad":0,"rx_drop":0,"rx_err":0,"tx_drop":0,"tx_err":0,"peak":null,"peak_bad":0,"span_s":295,'
    '"last_bad_s":null,"life_pkts":729476,"life_bad":0,"life_since":null,"dp":"wg","fault_kinds":["rx_drop"]},"swg_61a5799d":{"pct":100.0,'
    '"window_pkts":0,"window_bad":260,"rx_drop":0,"rx_err":0,"tx_drop":0,"tx_err":260,"peak":null,"peak_bad":23,"span_s":295,'
    '"last_bad_s":0,"life_pkts":0,"life_bad":221332,"life_since":null,"dp":"wg","fault_kinds":["rx_drop"]}},"datapath":{"awg":{"needed":true,'
    '"ok":true,"gen":{"module":"3.1","fallback":"3.1","tools":"3.1","disk":"3.1"},"exact":1}},"node_ips":["203.0.113.10"],'
    '"node_ifaces":["eth0"]}'
)


print("\n[6] on the wire — one node's report reaches no other node's sync and no operator's console (a real panel)")
A, Q, B = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"
_lk = lambda a, p: {"iface": "swg_1", "address": a, "peer_address": p, "subnet": "10.255.0.0/31", "listen_port": 51999}
_st = os.path.join(TMP, "state"); os.makedirs(_st); STATS = os.path.join(TMP, "stats"); os.makedirs(STATS)
_np = os.path.join(_st, "nodes.json")
json.dump({A: {"id": A, "name": "a", "ifaces": {"wg0": {"egress_mode": "forward", "egress_node": Q}},   # A forwards through Q
               "links": {Q: _lk("10.255.0.0", "10.255.0.1")}},
           Q: {"id": Q, "name": "q", "ifaces": {"wg1": {}}, "links": {A: _lk("10.255.0.1", "10.255.0.0")}},
           B: {"id": B, "name": "b", "ifaces": {"wg2": {}}}}, open(_np, "w"))                              # B: unrelated to Q
open(os.path.join(_st, "users.json"), "w").write("{}\n")
_fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": _np, "roster_path": os.path.join(_st, "users.json"), "stats_dir": STATS}, open(_fleet, "w"))
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
_log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, PANEL], stdout=_log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": _fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "",
                             "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None, raw=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=raw if raw is not None else (json.dumps(data).encode() if data is not None else None),
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _strict(b):                                    # what the browser's r.json() accepts: no NaN / Infinity tokens
    try:
        json.loads(b, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        return True
    except ValueError:
        return False


def sync(nid, snap=None, raw=None):
    code, out = req("/api/node/sync", {"snapshot": snap} if raw is None else None, TOK[nid], raw=raw)
    try:
        j = json.loads(out)
    except ValueError:
        j = {}
    return code, "desired" in (j.get("data") or j)


def snap_of(nid, ifn, sub, **over):
    s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "node_ips": ["192.0.2.1"],
         "interfaces": {ifn: {"peers": [], "meta": {"subnet": sub, "listen_port": 51820}}}, "smartroute": {"arr": 1, "src": 1}}
    s.update(over)
    return s


try:
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                sys.exit("panel exited: " + open(_log.name).read()[-2000:])
            time.sleep(0.1)
    TOK = {n: json.loads(req("/api/nodes/rotate", {"id": n})[1])["data"]["token"] for n in (A, Q, B)}
    GOOD = {A: snap_of(A, "wg0", "10.8.0.0/24"), Q: snap_of(Q, "wg1", "10.9.0.0/24"), B: snap_of(B, "wg2", "10.7.0.0/24")}
    for n in (A, Q, B):
        sync(n, GOOD[n])

    def others():                                  # every OTHER node's next sync, and the operator's poll
        st = req("/api/state")
        return sync(A, GOOD[A]), sync(B, GOOD[B]), (st[0], _strict(st[1]))
    _o = others()
    check("control: A and B sync 200 with `desired`, /api/state 200 as JSON", _o == ((200, True), (200, True), (200, True)), _o)
    _qbase = json.dumps({"snapshot": GOOD[Q]})[:-2]  # Q's good body, open at its end for one more field
    for label, body, q_want in (
            ("(a) Q's interfaces.wg1.meta = 'x'", {"snapshot": snap_of(Q, "wg1", "", interfaces={"wg1": {"peers": [], "meta": "x"}})}, 200),
            ("(a) Q's interfaces.wg1.meta = [1]", {"snapshot": snap_of(Q, "wg1", "", interfaces={"wg1": {"peers": [], "meta": [1]}})}, 200),
            ("(b) Q's ip_forward = true", {"snapshot": snap_of(Q, "wg1", "10.9.0.0/24", ip_forward=True)}, 200),
            ("(b) Q's rp_filter = 'on'", {"snapshot": snap_of(Q, "wg1", "10.9.0.0/24", rp_filter="on")}, 200),
            ("(b) Q's turn_proxies = ['x']", {"snapshot": snap_of(Q, "wg1", "10.9.0.0/24", turn_proxies=["x"])}, 200),
            ("(b) Q's wdtt[0].listen = 443", {"snapshot": snap_of(Q, "wg1", "10.9.0.0/24", wdtt=[{"iface": "wdtt1", "listen": 443}])}, 200),
            ("(b) Q's csqtt[0].listen = 443", {"snapshot": snap_of(Q, "wg1", "10.9.0.0/24", csqtt=[{"iface": "csqtt1", "listen": 443}])}, 200),
            ("(c) Q's log.oldest = Infinity", _qbase + ', "log": {"oldest": Infinity, "live": 1}}}', 400),
            ("(c) Q's NaN", _qbase + ', "zzz": NaN}}', 400),
            ("(c) Q's log.oldest = -Infinity", _qbase + ', "log": {"oldest": -Infinity, "live": 1}}}', 400),
            ("(c) Q's log.oldest = 1e400 (a literal past a double's range)", _qbase + ', "log": {"oldest": 1e400, "live": 1}}}', 400),
            ("(c) Q's inet.up = \"inf\" (a string)", _qbase + ', "inet": {"up": "inf", "down": 1}}}', 200)):
        qc = sync(Q, raw=(body if isinstance(body, str) else json.dumps(body)).encode())[0]
        check("[6] %s: Q's own sync answers %d" % (label, q_want) + (" (refused at the door, nothing stored)" if q_want == 400
              else " (dropped, not refused)"), qc == q_want, qc)
        _o = others()
        check("[6] %s: A's and B's next syncs 200 with `desired`, /api/state 200 as JSON" % label,
              _o == ((200, True), (200, True), (200, True)), _o)
        sync(Q, GOOD[Q])                           # Q heals before the next case

    print("\n[7] a real snapshot goes through the door and the sanitiser byte for byte — small fleets feel nothing")
    REAL = [("the test fleet's msk-main (reduced, anonymised)", json.loads(FIXTURE))]
    if os.environ.get("SWG_SNAP_FIXTURES"):
        _d = os.environ["SWG_SNAP_FIXTURES"]
        REAL += [(f, json.load(open(os.path.join(_d, f)))) for f in sorted(os.listdir(_d))
                 if f.startswith("stats-") and f.endswith(".json")]
    for label, snap in REAL:
        qc = sync(Q, snap)[0]
        with open(os.path.join(STATS, "stats-%s.json" % Q)) as fh:   # the mirror: what the door + the sanitiser stored
            stored = fh.read()
        check("[7] %s: 200, and stored exactly as the node sent it (%d bytes)" % (label, len(stored)),
              qc == 200 and stored == json.dumps(snap), (qc, len(stored), len(json.dumps(snap))))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: malformed shapes sailed through" % len(FAILS)) if ok
          else "PERTURB FAILED — the sanitiser was disabled and nothing noticed")
    sys.exit(0 if ok else 1)
if PLANT:
    print(("PLANT %s: caught — %d red" % (PLANT, len(FAILS))) if FAILS else ("PLANT %s: NOT CAUGHT" % PLANT))
    sys.exit(0 if FAILS else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
