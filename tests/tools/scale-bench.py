#!/usr/bin/env python3
"""scale-bench.py — the scale plan's yardstick (docs/SCALE-PLAN.md §0.2, K0). Tooling, not a gate: it prints numbers.

A REAL swg-panel-server on temp state, pinned to one core (taskset), plain HTTP, no login. A synthetic fleet built with the
panel's own user_set/peer_set (so the roster is shaped exactly as the panel writes it): users with one or two devices each,
wg0 + awg0 on every node, a csqtt 2.5 and a WDTT instance on every node (turn users ~10 % of devices), a few blocked and
expired users, ~5 % of identities on two nodes, one big node. The nodes are played by POSTing /api/node/sync with synthetic
snapshots every 5 s (~60 % of peers online, counters moving); operator tabs poll /api/state with gzip every 5 s, and
/api/roster when its revision moves, as the SPA does; an operator clicks create user → create device → block over HTTP
every 5 s (--click-every: each click saves the roster, so every tab fetches it again).

  A1  panel CPU, steady (own + children, % of the pinned core)
  A2  panel RSS (start / end / max of the steady window)
  A3  node sync latency p50/p95/max + resets/errors, steady and in a simultaneous reconnect of every node (3 bursts)
  A4  operator click latency p50/p95/max (create user / create device / block)
  A7  browser (--browser): headless Chrome, 4× CPU throttle, one pass per main screen: the longest task and the long-task
      time per poll after the screen settled, and the heap after a GC
  A8  node converging (--converge N): the REAL swg-noded reconcile() spawning the REAL swg-agent against a stub `wg`, from
      an empty interface to N peers; reported: the longest single reconcile() (= the longest stretch with no snapshot POST,
      since noded posts between passes) and the total time to converge
  A10 turn (sizes with a big node): the big node's csqtt instance is filled to its pool (248); a 249th user is created on it
      over the API — refused, or silent (200)
  A9  node idle CPU is measured on the 1-vCPU test node with tests/tools/cpu-measure.sh --exact, not here
  first sync: every node once, one after another, nothing else running — the per-sync cost uncontended; its ratio between
      two machines is the speed factor (a 1-vCPU calibration run: --core 0 on the box, no --browser)
  A11 small fleets: run --sizes 200x5 before and after a step and compare (the hard gate)

A3, A4 and the poll cover the whole loaded period: the steady window and, with --browser, the browser pass (the load runs on;
the browser is one of the three tabs). What the rig does not play: the nodes never bring up the mesh links the panel asks for
(their cost grows with nodes, not users), and the synthetic tabs poll /api/state + /api/roster only (the SPA also reads events
and traffic).

Run:   python3 tests/tools/scale-bench.py                                  # 200x5, 10000x20, 15000x20; 120 s steady each
       python3 tests/tools/scale-bench.py --sizes 10000x20 --duration 60 --browser --converge 2500
       --core N      the core the panel is pinned to (default: the last one)      --json FILE  the results as JSON too
       --keep        leave the temp state behind (its path is printed)

Never run it while the qualification nightly runs (systemctl --user list-timers swg-qual-nightly.timer): the numbers are
timings. Never against a live panel: it starts its own on temp state and a free port.
"""
import argparse, base64, gzip, http.client, importlib.machinery, importlib.util, json, os, random, shutil, signal, socket
import statistics, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
AGENT = os.environ.get("SWG_AGENT") or os.path.join(ROOT, "swg-agent")
HZ = os.sysconf("SC_CLK_TCK")
SYNC_EVERY = 5.0
CSQTT_CAP = 248                                   # csqtt 2.5's pool on a /24 (plan §1.3)


def b64key():
    return base64.b64encode(os.urandom(32)).decode()


def load_module(path, name, env=None):
    for k, v in (env or {}).items():
        os.environ[k] = v
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    sys.modules[name] = m
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


def pct(v, q):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q / 100.0 * (len(v) - 1))))]


# ─────────────────────────────────────────── the fleet ───────────────────────────────────────────

class Fleet:
    """The synthetic fleet: state files on disk + what each node has on the wire (for its snapshots)."""

    def __init__(self, P, users, nodes, big, rnd):
        self.P, self.n_users, self.n_nodes, self.big, self.rnd = P, users, nodes, big, rnd
        self.nids = ["n%02d" % (i + 1) for i in range(nodes)]
        self.next_ip = {}                                 # (nid, iface) → next host number
        self.roster = {"version": P.ROSTER_VERSION, "users": {}, "peers": {}}
        self.wire = {n: {"wg0": [], "awg0": []} for n in self.nids}            # nid → iface → [(pubkey, ip, psk)]
        self.turn = {n: {"csqtt1": [], "wdtt0": []} for n in self.nids}        # nid → iface → [password]

    def subnet(self, nid, iface):
        i = self.nids.index(nid) + 1
        return "10.%d.0.0/16" % (i if iface == "wg0" else 100 + i)

    def take_ip(self, nid, iface):
        k = (nid, iface)
        h = self.next_ip.get(k, 2)
        self.next_ip[k] = h + 1
        i = self.nids.index(nid) + 1
        return "10.%d.%d.%d" % (i if iface == "wg0" else 100 + i, h // 250, h % 250 + 2)

    def pick_node(self, k, n_devices):
        """The big node takes `big` of the devices, the rest spread evenly; a fleet with no big node spreads all."""
        if self.big and k < self.big:
            return self.nids[0]
        rest = self.nids[1:] if self.big else self.nids
        return rest[k % len(rest)]

    def build(self):
        P, rnd, now = self.P, self.rnd, int(time.time())
        n_dev = 0
        devices = []                                      # (uid, kind)
        for u in range(self.n_users):
            uid = "u%06d" % u
            P.user_set(self.roster, uid, {"name": "user%05d" % u, "tag": "", "note": ""}, now - 86400)
            r = rnd.random()
            if r < 0.02:
                self.roster["users"][uid]["disabled"] = True
            elif r < 0.04:
                self.roster["users"][uid]["expiry"] = now - 3600
            for _ in range(1 if rnd.random() < 0.5 else 2):
                devices.append(uid)
        rnd.shuffle(devices)
        # the big node's csqtt instance holds exactly its pool (A10); every other instance a share of ~10 % turn devices
        big_csqtt = CSQTT_CAP if (self.big and self.big >= 10 * CSQTT_CAP) else 0
        for k, uid in enumerate(devices):
            nid = self.pick_node(k, len(devices))
            pid = "p%06d" % k
            if nid == self.nids[0] and big_csqtt and len(self.turn[nid]["csqtt1"]) < big_csqtt:
                kind = "csqtt"
            else:
                r = rnd.random()
                kind = "csqtt" if r < 0.065 else "wdtt" if r < 0.10 else "wg" if r < 0.55 else "awg"
                if kind == "csqtt" and nid == self.nids[0] and big_csqtt:
                    kind = "wdtt"                                      # the probed instance stays exactly full
            if kind in ("wg", "awg"):
                iface = kind + "0"
                tg = [{"node": nid, "iface": iface, "type": kind, "ip": self.take_ip(nid, iface)}]
                if rnd.random() < 0.05 and self.n_nodes > 1:          # the same identity on a second node (failover)
                    other = self.nids[(self.nids.index(nid) + 1 + rnd.randrange(self.n_nodes - 1)) % self.n_nodes]
                    tg.append({"node": other, "iface": iface, "type": kind, "ip": self.take_ip(other, iface)})
                fields = {"user_id": uid, "title": "", "pubkey": b64key(), "psk": b64key(), "targets": tg}
            else:
                iface = "csqtt1" if kind == "csqtt" else "wdtt0"
                tg = [{"node": nid, "iface": iface, "type": kind, "ip": ""}]
                fields = {"user_id": uid, "title": "", "pubkey": "", "psk": "", "targets": tg}
                fields.update(P.mint_keyless_secrets(tg, {}))
            p = P.peer_set(self.roster, pid, fields, now - 86400)
            n_dev += 1
            u = self.roster["users"][uid]
            cut = u.get("disabled") or (u.get("expiry") or 0) and u["expiry"] < now
            for t in p["targets"]:
                if kind in ("wg", "awg"):
                    if not cut:                                        # a converged node carries only active peers
                        self.wire[t["node"]][t["iface"]].append((p["pubkey"], t["ip"], p["psk"]))
                else:
                    self.turn[t["node"]][t["iface"]].append(p.get("csqtt_password") or p.get("wdtt_password"))
        return n_dev

    def write(self, state, stats):
        P = self.P
        nodes = {}
        wver = (P._wdtt_current_version("amurcanov") if hasattr(P, "_wdtt_current_version") else "") or ""
        self.csqtt_ver = P.CSQTT_LINES["2.5"][0][0]
        self.wdtt_ver = wver
        for i, n in enumerate(self.nids):
            nodes[n] = {"id": n, "name": "node-%s" % n, "endpoint_host": "203.0.113.%d" % (i + 1), "links": {},
                        "ifaces": {"wg0": {}, "awg0": {}},
                        "csqtt": {"csqtt1": {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "line": "2.5"}},
                        "wdtt": {"wdtt0": {"listen": "0.0.0.0:56000", "wg_port": 56001, "wg_addr": "10.66.73.1/24",
                                           "fork": "amurcanov"}}}
        self.nodes_path = os.path.join(state, "nodes.json")
        self.users_path = os.path.join(state, "users.json")
        json.dump(nodes, open(self.nodes_path, "w"))
        P.roster_save(self.users_path, self.roster)                    # the panel's own writer, as a real panel left it
        for f in os.listdir(state):                                    # …minus the backup it takes
            if ".bak." in f:
                os.unlink(os.path.join(state, f))
        self.fleet_cfg = os.path.join(state, "fleet.json")
        json.dump({"nodes_path": self.nodes_path, "roster_path": self.users_path, "stats_dir": stats}, open(self.fleet_cfg, "w"))


class NodeSim:
    """One node's snapshots: its wire peers ~60 % online with counters that move, its turn instances."""

    def __init__(self, fleet, nid, enforcing, rnd):
        self.f, self.nid, self.enforcing = fleet, nid, enforcing
        self.ifkey = {i: b64key() for i in ("wg0", "awg0")}
        self.online = {}
        self.bytes = {}
        for iface, peers in fleet.wire[nid].items():
            for pk, _ip, _psk in peers:
                self.online[pk] = rnd.random() < 0.6
                self.bytes[pk] = [rnd.randrange(1 << 20, 1 << 30), rnd.randrange(1 << 20, 1 << 30)]
        self.pw_online = {pw: rnd.random() < 0.6 for ifs in fleet.turn[nid].values() for pw in ifs}
        self.pw_bytes = {pw: [rnd.randrange(1 << 20, 1 << 30), rnd.randrange(1 << 20, 1 << 30)] for pw in self.pw_online}
        self.n = 0

    def snapshot(self):
        now = int(time.time())
        self.n += 1
        ifs = {}
        for iface, peers in self.f.wire[self.nid].items():
            lst = []
            for pk, ip, psk in peers:
                on = self.online[pk]
                b = self.bytes[pk]
                if on:
                    b[0] += 40000; b[1] += 250000
                hs = now - 30 if on else now - 7200
                lst.append({"public_key": pk, "endpoint": "198.51.100.%d:%d" % (len(lst) % 250 + 1, 40000 + len(lst)) if on else None,
                            "preshared_key": psk, "allowed_ips": ip + "/32", "rx_bytes": b[0], "tx_bytes": b[1],
                            "rx_speed": 8000 if on else 0, "tx_speed": 50000 if on else 0, "last_handshake": hs,
                            "handshake_age": now - hs, "online": on, "hs_gap_med": 120.0 if on else None, "hs_seen": 5,
                            "ep_moves": 0, "hs_bytes_med": 9000.0})
            sub = self.f.subnet(self.nid, iface)
            ifs[iface] = {"peers": lst, "onboarded": False, "boot_persist": True,
                          "meta": {"public_key": self.ifkey[iface], "listen_port": 51820 if iface == "wg0" else 51821,
                                   "mtu": 1420, "endpoint": None, "address": sub.replace(".0.0/16", ".0.1/16"), "subnet": sub,
                                   "awg_params": ({"jc": 4, "jmin": 40, "jmax": 70, "s1": 0, "s2": 0, "h1": 1, "h2": 2, "h3": 3, "h4": 4}
                                                  if iface == "awg0" else None),
                                   "tool": "awg" if iface == "awg0" else "wg", "dns": []}}

        def pws(iface):
            out = {}
            for k, pw in enumerate(self.f.turn[self.nid][iface]):
                on = self.pw_online[pw]
                b = self.pw_bytes[pw]
                if on:
                    b[0] += 40000; b[1] += 250000
                out[pw] = {"device_id": "d%d" % k, "up_bytes": b[0], "down_bytes": b[1], "is_deactivated": False,
                           "expires_at": 0, "ip": "10.66.%d.%d" % (67 if iface == "csqtt1" else 73, k % 250 + 2),
                           "online": on, "rx_speed": 8000 if on else 0, "tx_speed": 50000 if on else 0}
            return out
        csq = pws("csqtt1")
        wdt = pws("wdtt0")
        snap = {"hostname": "node-" + self.nid, "generated_at": now, "interfaces": ifs, "noded_version": self.f.P.VERSION
                if hasattr(self.f.P, "VERSION") else "bench", "kind": "baremetal", "net_mode": "host", "turn_manage": True,
                "turn_proxies": [], "turn_flags": {}, "turn_drops": {}, "cmd_errors": {}, "cmd_progress": {},
                "onboard_notes": {}, "quarantined": {}, "node_ips": ["203.0.113.1"], "node_ifaces": ["eth0"],
                "ether_ifaces": ["eth0"], "ether_gws": {"eth0": "203.0.113.254"}, "wan_iface": "eth0",
                "node_ip_ifaces": [], "lans": [], "doh_peers": {},
                "ip_forward": {"ok": True}, "rp_filter": {"needed": False, "bad": []}, "iface_drops": {},
                "iface_key_backups": {}, "ifaces_awaiting_key": [], "iface_key_vault_restore": True,
                "iface_key_sealed": {}, "exit_key_sealed": {}, "wdtt_key_sealed": {},
                "csqtt_lines": ["2.1", "2.5"], "csqtt_ar_pw": 1, "csqtt_candidates": [], "wdtt_dormant": [],
                "csqtt": [{"iface": "csqtt1", "service": "csqtt@csqtt1", "active": "active", "listen": "0.0.0.0:46000",
                           "tun_addr": "10.66.67.1/24", "stopped": False, "kind": "csqtt", "fork": "amurcanov",
                           "version": self.f.csqtt_ver, "line": "2.5", "max_passwords": "", "params": "", "dns": "",
                           "rx_bytes": 1 << 30, "tx_bytes": 1 << 32, "rx_speed": 100000, "tx_speed": 900000,
                           "adopt_users": {}, "passwords": csq, "devices": {}}],
                "wdtt": [{"iface": "wdtt0", "service": "wdtt@wdtt0", "active": "active", "listen": "0.0.0.0:56000",
                          "wg_addr": "10.66.73.1/24", "wg_port": 56001, "server_pub": self.ifkey["wg0"], "stopped": False,
                          "fork": "amurcanov", "version": self.f.wdtt_ver, "max_passwords": "", "params": "", "dns": "",
                          "rx_bytes": 1 << 30, "tx_bytes": 1 << 32, "rx_speed": 100000, "tx_speed": 900000,
                          "adopt_users": {}, "passwords": wdt, "devices": {}}]}
        if self.enforcing:
            snap["net_deps"] = {"panel": "127.0.0.1", "resolvers": [], "resolvers_known": True, "share": 1, "carried": 1, "reach": 2}
        return snap


# ─────────────────────────────────────────── the drivers ───────────────────────────────────────────

class Rec:
    def __init__(self):
        self.lock = threading.Lock()
        self.lat, self.err = {}, {}

    def add(self, k, ms):
        with self.lock:
            self.lat.setdefault(k, []).append(ms)

    def fail(self, k, why):
        with self.lock:
            self.err.setdefault(k, {}).setdefault(why, 0)
            self.err[k][why] += 1


def http_req(port, method, path, body=None, headers=None, timeout=60):
    """One request on a FRESH connection (as noded and the browser's first request do). → (status, bytes, ms)."""
    t0 = time.perf_counter()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        return r.status, data, (time.perf_counter() - t0) * 1000.0
    finally:
        c.close()


def classify(e):
    if isinstance(e, ConnectionResetError):
        return "reset"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, ConnectionRefusedError):
        return "refused"
    if isinstance(e, http.client.RemoteDisconnected):
        return "disconnected"
    return type(e).__name__


def sync_once(port, sim, tok, rec, key):
    body = json.dumps({"snapshot": sim.snapshot()}).encode()
    try:
        st, data, ms = http_req(port, "POST", "/api/node/sync", body,
                                {"Content-Type": "application/json", "Authorization": "Bearer " + tok})
        if st != 200 or b'"desired"' not in data:
            rec.fail(key, "http%d" % st)
        else:
            rec.add(key, ms)
    except Exception as e:
        rec.fail(key, classify(e))


def node_loop(port, sim, tok, rec, stop, offset):
    if stop.wait(offset):
        return
    while not stop.is_set():                              # swg-noded's pacing: sleep max(0.5, interval − the pass)
        t0 = time.monotonic()
        sync_once(port, sim, tok, rec, "sync")
        stop.wait(max(0.5, SYNC_EVERY - (time.monotonic() - t0)))


def tab_loop(port, rec, stop, offset, sizes):
    if stop.wait(offset):
        return
    nxt = time.monotonic()
    rev = None                                   # as the SPA polls (js/store.js): the roster only when its revision moved
    while not stop.is_set():
        try:
            st, data, ms = http_req(port, "GET", "/api/state", None, {"Accept-Encoding": "gzip"})
            if st == 200:
                want = json.loads(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)["data"].get("roster_rev")
                if isinstance(want, str) and want != rev:
                    rst, rdata, rms = http_req(port, "GET", "/api/roster?rev=" + want, None, {"Accept-Encoding": "gzip"})
                    if rst == 200:
                        rev = json.loads(gzip.decompress(rdata) if rdata[:2] == b"\x1f\x8b" else rdata)["rev"]
                        ms += rms; data += rdata
                    else:
                        rec.fail("state", "roster http%d" % rst)
                rec.add("state", ms)
                sizes.append(len(data))
            else:
                rec.fail("state", "http%d" % st)
        except Exception as e:
            rec.fail("state", classify(e))
        nxt += SYNC_EVERY
        stop.wait(max(0.0, nxt - time.monotonic()))


def post(port, path, obj, rec, key):
    try:
        st, data, ms = http_req(port, "POST", path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
        if st == 200:
            rec.add(key, ms)
        else:
            rec.fail(key, "http%d" % st)
        return st, json.loads(data or b"{}")
    except Exception as e:
        rec.fail(key, classify(e))
        return 0, {}


def click_loop(port, fleet, rec, stop, every=SYNC_EVERY):
    k = 0
    small = fleet.nids[1:] if fleet.big else fleet.nids
    nxt = time.monotonic() + 1.0
    while not stop.wait(max(0.0, nxt - time.monotonic())):
        nxt += every
        k += 1
        _st, r = post(port, "/api/users/create", {"name": "bench%05d" % k}, rec, "click")
        uid = (r.get("data") or {}).get("id")
        if not uid:
            continue
        nid = small[k % len(small)]
        _st, r = post(port, "/api/peers/create", {"user_id": uid, "pubkey": b64key(),
                      "targets": [{"node": nid, "iface": "wg0", "ip": fleet.take_ip(nid, "wg0")}]}, rec, "click")
        pid = (r.get("data") or {}).get("id")
        if pid:
            post(port, "/api/peers/block", {"peer_id": pid}, rec, "click")


def proc_cpu(pid):
    f = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()
    return sum(int(x) for x in f[11:15]) / HZ                    # utime stime cutime cstime


def proc_rss(pid):
    for ln in open("/proc/%d/status" % pid):
        if ln.startswith("VmRSS:"):
            return int(ln.split()[1]) / 1024.0
    return 0.0


# ─────────────────────────────────────────── the browser (A7) ───────────────────────────────────────────

LT_OBSERVER = """(() => { window.__lt = []; try { new PerformanceObserver(l => { for (const e of l.getEntries())
  window.__lt.push([e.startTime, e.duration]); }).observe({type: 'longtask', buffered: true}); } catch (e) {} })();"""


def browser_pass(port, screens, settle, window):
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import cdp_pipe
    out = {}
    br = cdp_pipe.Browser()
    try:
        for name, route in screens:
            tab = cdp_pipe.Tab(br)
            try:
                br.send("Emulation.setCPUThrottlingRate", {"rate": 4}, session=tab.s)
                br.send("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False}, session=tab.s)
                br.send("Page.addScriptToEvaluateOnNewDocument", {"source": LT_OBSERVER}, session=tab.s)
                t0 = time.time()
                tab.goto("http://127.0.0.1:%d/%s" % (port, route))
                polled = False
                while time.time() - t0 < 180:
                    br.pump(1.0)
                    try:
                        polled = tab.ev("performance.getEntriesByType('resource').filter(r => r.name.includes('/api/state')).length", timeout=60) >= 1
                    except Exception:
                        polled = False
                    if polled:
                        break
                load_s = time.time() - t0
                br.pump(settle)
                tab.ev("window.__lt = []")
                n0 = tab.ev("performance.getEntriesByType('resource').filter(r => r.name.includes('/api/state')).length")
                br.pump(window)
                lt = tab.ev("window.__lt") or []
                n1 = tab.ev("performance.getEntriesByType('resource').filter(r => r.name.includes('/api/state')).length")
                polls = max(1, (n1 or 0) - (n0 or 0))
                br.send("HeapProfiler.enable", session=tab.s)
                br.send("HeapProfiler.collectGarbage", session=tab.s, timeout=120)
                heap = br.send("Runtime.getHeapUsage", session=tab.s)
                durs = [d for _s, d in lt]
                out[name] = {"load_s": round(load_s, 1), "polled": polled, "polls": polls,
                             "longest_ms": round(max(durs), 0) if durs else 0,
                             "over100": sum(1 for d in durs if d > 100),
                             "lt_per_poll_ms": round(sum(durs) / polls, 0),
                             "heap_mb": round(heap.get("usedSize", 0) / 1048576.0, 1),
                             "dom": tab.ev("document.getElementsByTagName('*').length")}      # proof the screen rendered
            except Exception as e:
                out[name] = {"error": str(e)[:200]}
            finally:
                tab.close()
            print("    A7 %-9s %s" % (name, out[name]), flush=True)
    finally:
        br.close()
    return out


# ─────────────────────────────────────────── the node (A8) ───────────────────────────────────────────

STUB_WG = r"""#!/bin/sh
# a stand-in `wg`: peers live in $SWG_BENCH_WG/<iface>.peers, one dump line each
D="$SWG_BENCH_WG"
case "$1" in
  genpsk|genkey) head -c 32 /dev/urandom | base64; exit 0;;
  pubkey) cat >/dev/null; head -c 32 /dev/urandom | base64; exit 0;;
  show)
    if [ "$2" = all ]; then
      for f in "$D"/*.peers; do i=$(basename "$f" .peers); printf '%s\tPRIV=\tPUB=\t51820\toff\n' "$i"
        sed "s/^/$i\t/" "$f"; done; exit 0; fi
    [ -f "$D/$2.peers" ] || { echo "Unable to access interface: No such device" >&2; exit 1; }
    printf 'PRIV=\tPUB=\t51820\toff\n'; cat "$D/$2.peers"; exit 0;;
  set)
    i="$2"; pk="$4"; shift 4
    case "$1" in
      remove) grep -v "^$pk	" "$D/$i.peers" > "$D/$i.tmp"; mv "$D/$i.tmp" "$D/$i.peers";;
      allowed-ips) [ "$3" = preshared-key ] && cat >/dev/null
        printf '%s\t(none)\t(none)\t%s\t0\t0\t0\toff\n' "$pk" "$2" >> "$D/$i.peers";;
    esac; exit 0;;
esac
exit 0
"""


def converge(n_peers):
    tmp = tempfile.mkdtemp(prefix="scale-bench-node-")
    stub = os.path.join(tmp, "bin"); os.makedirs(stub)
    wgd = os.path.join(tmp, "wg"); os.makedirs(wgd)
    open(os.path.join(stub, "wg"), "w").write(STUB_WG); os.chmod(os.path.join(stub, "wg"), 0o755)
    open(os.path.join(wgd, "wg0.peers"), "w").close()
    conf = os.path.join(tmp, "wg0.conf")
    open(conf, "w").write("[Interface]\nPrivateKey = %s\nAddress = 10.8.0.1/16\nListenPort = 51820\n" % b64key())
    acfg = os.path.join(tmp, "agent.json")
    json.dump({"interfaces": {"wg0": {"cmd": ["wg"], "conf": conf}}}, open(acfg, "w"))
    os.environ["PATH"] = stub + os.pathsep + os.environ["PATH"]
    N = load_module(NODED, "swgnoded_bench", {"SWG_NODED_STATE": os.path.join(tmp, "state"), "SWG_AGENT_CONFIG": acfg,
                                              "SWG_AGENT_AUDIT": os.path.join(tmp, "audit.log"),
                                              "SWG_AGENT_LOCK": os.path.join(tmp, "agent.lock"), "SWG_BENCH_WG": wgd,
                                              "SWG_NO_REEXEC": "1"})
    os.makedirs(os.path.join(tmp, "state"), exist_ok=True)
    N.STATE_DIR = os.path.join(tmp, "state")
    desired = {"wg0": [{"public_key": b64key(), "allowed_ips": "10.8.%d.%d/32" % (k // 250, k % 250 + 2),
                        "preshared_key": b64key()} for k in range(n_peers)]}
    cfg = {"interfaces": {"wg0": {"cmd": ["wg"], "conf": conf}}}
    calls, t_all = [], time.perf_counter()
    for _ in range(1000):
        N._LOOP["n"] += 1                                   # a new pass: the pass-cached dumps are read again
        t0 = time.perf_counter()
        res = N.reconcile(cfg, desired, AGENT, False, {})
        calls.append(time.perf_counter() - t0)
        if res.get("errors"):
            print("    A8 errors: %s" % str(res["errors"])[:300], flush=True)
        live = sum(1 for _ in open(os.path.join(wgd, "wg0.peers")))
        if live >= n_peers or (not res.get("added") and not res.get("errors")):
            break
    total = time.perf_counter() - t_all
    shutil.rmtree(tmp, ignore_errors=True)
    return {"peers": n_peers, "live": live, "passes": len(calls), "longest_pass_s": round(max(calls), 1),
            "total_s": round(total, 1)}


# ─────────────────────────────────────────── one size ───────────────────────────────────────────

def run_size(P, users, nodes, args, core):
    rnd = random.Random(1000 * users + nodes)
    big = (2500 if users <= 10000 else 4000) if users >= 5000 else 0
    tmp = tempfile.mkdtemp(prefix="scale-bench-%d-" % users)
    state, stats = os.path.join(tmp, "state"), os.path.join(tmp, "stats")
    os.makedirs(state); os.makedirs(stats)
    t0 = time.time()
    fleet = Fleet(P, users, nodes, big, rnd)
    n_dev = fleet.build()
    fleet.write(state, stats)
    per_node = {n: sum(len(v) for v in fleet.wire[n].values()) + sum(len(v) for v in fleet.turn[n].values()) for n in fleet.nids}
    print("  fleet: %d users, %d devices, %d nodes (devices on a node: max %d, median %d), users.json %.2f MB — built in %.0f s"
          % (users, n_dev, nodes, max(per_node.values()), statistics.median(per_node.values()),
             os.path.getsize(fleet.users_path) / 1048576.0, time.time() - t0), flush=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(os.path.join(tmp, "panel.log"), "w+")
    env = {**os.environ, "SWG_PANEL_FLEET": fleet.fleet_cfg, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
           "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": ""}
    env.pop("SWG_NO_REEXEC", None)                             # set for our own import of it; the panel runs as installed
    proc = subprocess.Popen(["taskset", "-c", str(core), sys.executable, PANEL], stdout=log, stderr=subprocess.STDOUT,
                            env=env, start_new_session=True)
    res = {"users": users, "nodes": nodes, "devices": n_dev, "big_node": max(per_node.values()),
           "users_json_mb": round(os.path.getsize(fleet.users_path) / 1048576.0, 2)}
    stop = threading.Event()
    threads = []
    try:
        for _ in range(600):
            try:
                if http_req(port, "GET", "/healthz", timeout=2)[0] == 200:
                    break
            except Exception:
                if proc.poll() is not None:
                    raise SystemExit("panel exited:\n" + open(log.name).read()[-3000:])
            time.sleep(0.1)
        res["start_s"] = round(time.time() - t0, 1)
        tok = {}
        for n in fleet.nids:
            st, data, _ms = http_req(port, "POST", "/api/nodes/rotate", json.dumps({"id": n}).encode(), {"Content-Type": "application/json"})
            tok[n] = json.loads(data)["data"]["token"]
        sims = {n: NodeSim(fleet, n, enforcing=(i != nodes - 1 or nodes < 5), rnd=rnd) for i, n in enumerate(fleet.nids)}
        rec = Rec()
        for n in fleet.nids:                                   # every node once, one after another (the first sync)
            sync_once(port, sims[n], tok[n], rec, "first")

        # A3: a simultaneous reconnect of every node, three times
        for _b in range(3):
            bar = threading.Barrier(nodes)
            def burst(n):
                bar.wait()
                sync_once(port, sims[n], tok[n], rec, "burst")
            ts = [threading.Thread(target=burst, args=(n,)) for n in fleet.nids]
            [t.start() for t in ts]; [t.join() for t in ts]
            time.sleep(2)

        # steady window: nodes @5 s, 3 tabs @5 s, a click every --click-every s
        sizes = []
        for i, n in enumerate(fleet.nids):
            threads.append(threading.Thread(target=node_loop, args=(port, sims[n], tok[n], rec, stop, SYNC_EVERY * i / nodes), daemon=True))
        n_tabs = 2 if args.browser else 3
        for i in range(n_tabs):
            threads.append(threading.Thread(target=tab_loop, args=(port, rec, stop, 1.3 * i + 0.4, sizes), daemon=True))
        [t.start() for t in threads]
        time.sleep(10)                                         # warm: every node synced, every tab polled
        click = threading.Thread(target=click_loop, args=(port, fleet, rec, stop, args.click_every), daemon=True)
        click.start(); threads.append(click)
        rec.lat.pop("sync", None); rec.lat.pop("state", None)
        c0, w0 = proc_cpu(proc.pid), time.time()
        rss = [proc_rss(proc.pid)]
        while time.time() - w0 < args.duration:
            time.sleep(2)
            rss.append(proc_rss(proc.pid))
        cpu = (proc_cpu(proc.pid) - c0) / (time.time() - w0) * 100.0
        res["A1_cpu_pct"] = round(cpu, 1)
        res["A2_rss_mb"] = {"start": round(rss[0]), "end": round(rss[-1]), "max": round(max(rss))}

        if args.browser:
            screens = [("overview", "#/"), ("nodes", "#/nodes"), ("peers", "#/peers"), ("users", "#/users"),
                       ("node-big", "#/node/" + fleet.nids[0])]
            res["A7"] = browser_pass(port, screens, args.settle, args.window)

        # A10: one more csqtt user on the big node's full instance
        if big:
            n_csq = len(fleet.turn[fleet.nids[0]]["csqtt1"])
            st, r = post(port, "/api/users/create", {"name": "a10probe"}, rec, "a10")
            uid = (r.get("data") or {}).get("id")
            st, r = post(port, "/api/peers/create", {"user_id": uid, "targets": [{"node": fleet.nids[0], "iface": "csqtt1"}]}, rec, "a10")
            res["A10"] = "csqtt1 holds %d (pool %d); user #%d: %s" % (n_csq, CSQTT_CAP, n_csq + 1,
                                                                 "silent (created, HTTP 200)" if st == 200 else "refused (HTTP %s)" % st)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=70)
        res["final_rss_mb"] = round(proc_rss(proc.pid)) if proc.poll() is None else None
        os.killpg(proc.pid, signal.SIGTERM)                    # its own session: only the panel and its children
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
        if args.keep:
            print("  kept: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    def stat(k):
        v = rec.lat.get(k) or []
        return {"n": len(v), "p50": round(pct(v, 50) or 0), "p95": round(pct(v, 95) or 0), "max": round(max(v) if v else 0),
                "errors": rec.err.get(k) or {}}
    res["A3_sync"] = stat("sync")
    res["A3_burst"] = stat("burst")
    res["first_sync"] = stat("first")
    res["A4_click"] = stat("click")
    res["poll"] = dict(stat("state"), gzip_kb=round(statistics.median(sizes) / 1024.0) if sizes else None)
    return res


def table(results):
    rows = [("users / nodes / devices", lambda r: "%d / %d / %d" % (r["users"], r["nodes"], r["devices"])),
            ("devices on the big node", lambda r: r["big_node"]),
            ("users.json MB", lambda r: r["users_json_mb"]),
            ("A1 panel CPU % of a core", lambda r: r.get("A1_cpu_pct")),
            ("A2 RSS MB start/end/max", lambda r: "%(start)s / %(end)s / %(max)s" % r["A2_rss_mb"] if "A2_rss_mb" in r else "-"),
            ("first sync p50/p95 ms (uncontended)", lambda r: "%(p50)s / %(p95)s" % r["first_sync"]),
            ("A3 sync p50/p95/max ms", lambda r: "%(p50)s / %(p95)s / %(max)s" % r["A3_sync"]),
            ("A3 sync errors", lambda r: r["A3_sync"]["errors"] or 0),
            ("A3 burst p50/p95/max ms", lambda r: "%(p50)s / %(p95)s / %(max)s" % r["A3_burst"]),
            ("A3 burst errors", lambda r: r["A3_burst"]["errors"] or 0),
            ("A4 click p50/p95/max ms", lambda r: "%(p50)s / %(p95)s / %(max)s" % r["A4_click"]),
            ("poll /api/state p50/p95 ms", lambda r: "%(p50)s / %(p95)s" % r["poll"]),
            ("poll gzip KB", lambda r: r["poll"]["gzip_kb"]),
            ("A10 turn", lambda r: r.get("A10", "-"))]
    names = sorted({k for r in results for k in (r.get("A7") or {})}, key=lambda k: ["overview", "nodes", "peers", "users", "node-big"].index(k))
    for k in names:
        rows.append(("A7 %s longest/per-poll ms, heap MB" % k,
                     lambda r, k=k: ("%(longest_ms)s / %(lt_per_poll_ms)s, %(heap_mb)s" % r["A7"][k]) if "longest_ms" in (r.get("A7") or {}).get(k, {})
                     else ((r.get("A7") or {}).get(k) or {}).get("error", "-")))
    w = max(len(n) for n, _f in rows)
    cols = [str(r["users"]) for r in results]
    print("\n| %s | %s |" % ("what".ljust(w), " | ".join(c.rjust(22) for c in cols)))
    print("|%s|%s|" % ("-" * (w + 2), "|".join("-" * 24 for _ in cols)))
    for n, f in rows:
        vals = []
        for r in results:
            try:
                vals.append(str(f(r)))
            except Exception:
                vals.append("-")
        print("| %s | %s |" % (n.ljust(w), " | ".join(v.rjust(22) for v in vals)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sizes", default="200x5,10000x20,15000x20")
    ap.add_argument("--duration", type=float, default=120.0, help="the steady window, seconds")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--settle", type=float, default=12.0, help="browser: seconds after the first poll before measuring")
    ap.add_argument("--window", type=float, default=30.0, help="browser: the measured window, seconds")
    ap.add_argument("--converge", type=int, default=0, help="A8: converge a node to N peers (0 = skip)")
    ap.add_argument("--core", type=int, default=(os.cpu_count() or 1) - 1)
    ap.add_argument("--click-every", type=float, default=SYNC_EVERY,
                    help="seconds between operator clicks; each saves the roster, so the tabs refetch it (default 5)")
    ap.add_argument("--json")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "swg-panel-server", "swg-noded", "swg-agent",
                            "app.js", "js", "reconcile.js"], capture_output=True, text=True).stdout.strip()
    print("scale-bench · HEAD %s%s · %s · panel pinned to core %d · %s UTC" % (
        head, " (product files modified)" if dirty else "", open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
        args.core, time.strftime("%Y-%m-%d %H:%M", time.gmtime())), flush=True)
    P = load_module(PANEL, "swgpanel_bench", {"SWG_NO_REEXEC": "1"})
    results = []
    for sz in [s for s in args.sizes.split(",") if s]:
        u, n = (int(x) for x in sz.lower().split("x"))
        print("\n== %d users / %d nodes" % (u, n), flush=True)
        results.append(run_size(P, u, n, args, args.core))
        print("  " + json.dumps({k: v for k, v in results[-1].items() if k != "A7"}), flush=True)
    a8 = None
    if args.converge:
        print("\n== A8: converge a node to %d peers (real noded reconcile + real agent, stub wg)" % args.converge, flush=True)
        a8 = converge(args.converge)
        print("  " + json.dumps(a8), flush=True)
    table(results)
    if a8:
        print("\nA8 node converging %(peers)d peers: longest pass (no snapshot meanwhile) %(longest_pass_s)s s, "
              "%(passes)d pass(es), converged in %(total_s)s s (%(live)d live)" % a8)
    if args.json:
        json.dump({"head": head, "dirty": bool(dirty), "results": results, "A8": a8}, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
