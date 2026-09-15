#!/usr/bin/env python3
"""Self-test for DEVICE ACCESS P1 — who may open a connection to a device (docs/DEVICE-ACCESS-PLAN.md §10).

Per client interface a level: Everyone (stored `"everyone"`), Same user and their groups (absent), Nobody (`"none"`). The
panel sends `dev_reach` only while some interface on a node is not at Everyone; the node enforces it with one prerouting
table, `swg_reach`, whose map covers each protected subnet whole — listed devices to their zone, the rest to Nobody.

 NODE
  [1] the plan: the node's own address is a map `accept` and the subnets are listed whole for the guard, the network address and every unlisted address go to the
      interface's Nobody chain, a listed device to its zone; an address two zones claim falls to the rest; an address
      outside every listed subnet, an unknown interface, a mesh link and a source element that could escape its quotes
      never reach nft; a WDTT instance brings its RAW TUN under its own counter; an overlapping subnet is skipped.
  [2] the declared table: the skeleton (replies first, guard before map, a miss inside the guard dropped — never a bare drop,
      which took IPv6), the guard == the subnets, zone and Nobody chains counting into slot counters, hash vs interval sets.
  [3] D1 and the restart: no `dev_reach` ⇒ the kernel asked once, then nothing; a table left from before is removed.
  [4] steady state: the same reply twice loads once; a changed reply SWAPS and zeroes no counter; `blocked` is the sum.
  [5] ⚠️ open and loud (A11): a table nft refuses leaves the status `ok: false` with the reason, and is retried next pass.
  [6] the routing pass: a table still there has its counters read (one fork); a flushed one is declared again from the held plan;
      a rebuild that fails is forgotten, so the next reply pass loads it again.
  [7] ⚠️ a conf that cannot be read this pass keeps the interface's last subnet — no reload open, then closed.
  [8] the sync loop protects before the peer write and after the WDTT/csqtt records; the routing pass verifies; `net_deps`
      says `reach`; the snapshot carries `dev_reach` only while a status is held.
 PANEL
  [9] `dev_reach_for_node`: a device at "user" is reachable by its owner's devices and its groups' — across interfaces, a
      network behind a device included, a vouched keyless device both ways — and by nobody else; a stranger, a blocked
      user, an unassigned device, another node's deployment and an unvouched keyless device are never sources or
      destinations; a "none" interface lists no destination; Everyone and mesh interfaces are not protected; the
      interface list comes from the node RECORD; no capability or every level Everyone ⇒ {}; deterministic.
 [10] the doors: `/api/iface/update`, `/api/iface/create`, `/api/wdtt/set`, `/api/csqtt/set` store only a chosen
      Everyone or Nobody, "user" removes the key, a bad level is refused and changes nothing, a save without `reach`
      keeps it; the interface meta, `wdtt_cfg` and `csqtt_cfg` publish it; the node's WDTT/csqtt replies never carry it;
      `interface_defaults.reach` defaults to "user" and survives a settings save that does not name it.
 [11] the sync reply names `dev_reach` once, behind that result, and the networks are computed once for both passes.
 [13] node table v2 (§13): the first load DECLARES; the same reply builds nothing (memo); a plan change SWAPS — no `delete
      table`, the new generation declared, `sel` repointed, exactly the held generation deleted map → chains → sets, the suffix
      alternating; the guard moves with the protected subnets; a counter only for an interface the table lacks; a refused swap
      leaves generation, plan, slots and memo; a leftover table is declared over; the node's own address is a map `accept`.
 [14] the compact wire (§14): it expands to exactly the v1 zones; each source once; a v1 node's reply unchanged; the node
      plans the same table from either shape; a bad index names nobody; net_deps says 2; the handler's capability check.
 [12] P2 fixes (docs/DEVICE-ACCESS-PLAN.md §11.2): F1 a lost interface hands the recreate sheet its level · F2 the node says why
      a listed interface is not in its table, also when it holds no table · F3 a refused RELOAD keeps counting the previous
      table and says stale, a refused FIRST load stays open · F4 unvouched builds per path · F5 the pass after both mirrors ·
      F7 no peer-to-peer claim for a device deployed nowhere.

Hermetic. Run: python3 tests/device_reach_selftest.py            (0 = pass)
     --perturb         maps only the listed devices (no "rest is Nobody") and expects RED on [1].
     --perturb-reply   drops the reply exemption from the declared table and expects RED on [2].
     --perturb-hold    forgets the last subnet on a failed read and expects RED on [7].
     --perturb-groups  forgets every group when planning and expects RED on [9].
     --perturb-skipped forgets why interfaces were left out and expects RED on [12] F2.
     --perturb-stale   calls every refused load open and expects RED on [12] F3.
     --perturb-swap    reloads a plan change by delete + recreate, as v1 (§11.7's leak), and expects RED on [13].
     --perturb-guard   drops the node's own `accept` from the map, so it falls into the guard, and expects RED on [1] and [13].
     --perturb-compact makes the node ignore `users` (v1 reading only) and expects RED on [14].
"""
import importlib.machinery, importlib.util, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_REPLY = "--perturb-reply" in sys.argv
PERTURB_HOLD = "--perturb-hold" in sys.argv
PERTURB_GROUPS = "--perturb-groups" in sys.argv
PERTURB_SKIPPED = "--perturb-skipped" in sys.argv
PERTURB_STALE = "--perturb-stale" in sys.argv
PERTURB_SWAP = "--perturb-swap" in sys.argv
PERTURB_GUARD = "--perturb-guard" in sys.argv
PERTURB_COMPACT = "--perturb-compact" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
N = load("swgnoded", NODED)
CP = N.subprocess.CompletedProcess

if PERTURB:
    _rp = N._reach_plan
    def _no_rest(cfg, wire, devices=None):
        p = _rp(cfg, wire, devices)
        return p and dict(p, map=[e for e in p["map"] if not e[2].startswith("jump n")])
    N._reach_plan = _no_rest
if PERTURB_REPLY:
    _rd = N._reach_declare_text
    N._reach_declare_text = lambda plan, slots: _rd(plan, slots).replace("ct direction reply accept; ", "")
if PERTURB_HOLD:
    _rd = N._reach_devices
    def _forget(cfg, names):
        N._REACH["seen"] = {}
        return _rd(cfg, names)
    N._reach_devices = _forget
if PERTURB_SKIPPED:
    _rp2 = N._reach_plan
    def _no_why(cfg, wire, devices=None):
        p = _rp2(cfg, wire, devices)
        N._REACH["skipped"] = {}
        return p
    N._reach_plan = _no_why
if PERTURB_STALE:
    N._reach_previous_holds = lambda swap, live: False
if PERTURB_SWAP:
    N._reach_swap_text = lambda old, new, old_slots, slots, old_g, g: N._reach_declare_text(new, slots)
if PERTURB_GUARD:
    _rpg = N._reach_plan
    def _no_accept(cfg, wire, devices=None):
        p = _rpg(cfg, wire, devices)
        return p and dict(p, map=[e for e in p["map"] if e[2] != "accept"])
    N._reach_plan = _no_accept
if PERTURB_COMPACT:
    _rpc = N._reach_plan
    def _v1_only(cfg, wire, devices=None):
        return _rpc(cfg, {k: v for k, v in wire.items() if k != "users"} if isinstance(wire, dict) else wire, devices)
    N._reach_plan = _v1_only

TMP = tempfile.mkdtemp(prefix="devreach-")
def conf(name, addr):
    p = os.path.join(TMP, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\nListenPort = 51820\n" % addr)
    return p
CFG = {"interfaces": {"wg0": {"conf": conf("wg0", "10.8.0.1/24")}, "awg0": {"conf": conf("awg0", "10.9.0.1/24")},
                      "swg_x": {"conf": conf("swg_x", "10.255.0.1/31")}, "wgover": {"conf": conf("wgover", "10.8.0.129/25")}}}
N._wdtt_load = lambda: {"wdtt1": {"iface": "wdtt1", "wg_addr": "10.77.0.1/24", "raw_port": "56003",
                                  "raw_iface": "wdtt1raw", "raw_addr": "10.78.0.1/24", "listen": "0.0.0.0:56000"}}
N._csqtt_load = lambda: {"csqtt1": {"iface": "csqtt1", "tun_addr": "10.66.67.1/24"}}

def fresh():
    N._REACH.update(probed=False, installed=False, sig=None, plan=None, status=None, seen={}, loaded=[], base={}, live={}, since=0,
                    skipped={}, stale=None, declared=False, gen="a", slots={})

class Nft:
    """The kernel as `run` sees it: a table there or not, its named counters, and whether the next load is refused."""
    def __init__(self, table=False):
        self.table, self.counters, self.refuse, self.calls, self.loads = table, {}, False, [], []
    def __call__(self, args, input_text=None, timeout=20):
        self.calls.append(list(args))
        if args[:2] == ["nft", "-f"]:
            if self.refuse:
                return CP(args, 1, "", "Error: Could not process rule: No such file or directory")
            if (input_text or "").startswith("table inet swg_reach\ndelete table"):
                self.counters = {}                    # a declare replaces the table, its counters included
            elif not self.table:
                return CP(args, 1, "", "Error: Could not process rule: No such file or directory")   # a swap needs the table
            self.table = True
            self.loads.append(input_text)
            for m in re.findall(r"counter (c\d+) \{ \}", input_text or ""):
                self.counters.setdefault(m, 0)        # a swap keeps every counter it does not declare
            return CP(args, 0, "", "")
        if args[:3] == ["nft", "delete", "table"]:
            self.table = False
            return CP(args, 0, "", "")
        if args[:3] == ["nft", "list", "table"]:
            return CP(args, 0 if self.table else 1, "", "" if self.table else "Error: No such file or directory")
        if args[:4] == ["nft", "-j", "list", "counters"]:
            if not self.table:
                return CP(args, 1, "", "Error: No such file or directory")
            return CP(args, 0, json.dumps({"nftables": [{"metainfo": {}}] + [{"counter": {"name": k, "packets": v, "bytes": v * 60}}
                                                                              for k, v in sorted(self.counters.items())]}), "")
        return CP(args, 0, "", "")

def res():
    return {"changed": 0, "errors": []}

WIRE = {"ifaces": ["awg0", "wg0", "wdtt1", "csqtt1", "swg_x", "nope", 'wg0" drop', "wgover"],
        "zones": [{"to": ["10.8.0.5", "10.9.0.7", "10.8.0.1", "172.16.0.9"],
                   "from": [["wg0", "10.8.0.5/32"], ["awg0", "10.9.0.7/32"], ["wg0", "192.168.50.0/24"],
                            ['wg0" accept; #', "10.8.0.6/32"], ["wg0", "not-a-prefix"]]},
                  {"to": ["10.8.0.9", "10.8.0.5"], "from": [["wg0", "10.8.0.9/32"]]},
                  {"to": ["10.77.0.2", "10.78.0.2"], "from": [["wdtt1", "10.77.0.2/32"], ["wdtt1raw", "10.78.0.2/32"]]}]}

def verdicts(plan):
    """{address as int: verdict} by walking the map's ranges."""
    import ipaddress
    return lambda a: next((v for lo, hi, v in plan["map"] if lo <= int(ipaddress.ip_address(a)) <= hi), None)

print("\n[1] the plan")
fresh()
PLAN = N._reach_plan(CFG, WIRE)
v = verdicts(PLAN)
check("the interfaces enforced: listed, run here, not a mesh link, not overlapping, sorted",
      PLAN["ifaces"] == ["awg0", "csqtt1", "wdtt1", "wg0"], PLAN["ifaces"])
j = {n: i for i, n in enumerate(PLAN["ifaces"])}
check("⚠️ the node's own address on each subnet is a map `accept` — never a zone, never Nobody (§13.5 Round 6)",
      all(v(a) == "accept" for a in ("10.8.0.1", "10.9.0.1", "10.77.0.1", "10.78.0.1", "10.66.67.1")), [v(a) for a in ("10.8.0.1", "10.9.0.1")])
check("the protected subnets, whole, for the guard", PLAN["subnets"] == ["10.8.0.0/24", "10.9.0.0/24", "10.66.67.0/24", "10.77.0.0/24", "10.78.0.0/24"],
      PLAN["subnets"])
check("the network address and an unlisted device go to the interface's Nobody chain",
      v("10.8.0.0") == "jump n%d" % j["wg0"] and v("10.8.0.77") == "jump n%d" % j["wg0"] and v("10.66.67.200") == "jump n%d" % j["csqtt1"],
      (v("10.8.0.0"), v("10.8.0.77")))
check("a listed device jumps to its zone", v("10.9.0.7", ).startswith("jump z") and v("10.8.0.9").startswith("jump z"), (v("10.9.0.7"), v("10.8.0.9")))
check("⚠️ an address two zones claim is in neither — the rest, Nobody", v("10.8.0.5") == "jump n%d" % j["wg0"], v("10.8.0.5"))
check("an address outside every listed subnet is not in the map", v("172.16.0.9") is None)
check("a zone device counts into its own interface: 10.9.0.7 → awg0's counter", v("10.9.0.7").endswith("i%d" % j["awg0"]), v("10.9.0.7"))
check("the WDTT RAW TUN is protected under the instance's counter", v("10.78.0.2").endswith("i%d" % j["wdtt1"]) and v("10.78.0.99") == "jump n%d" % j["wdtt1"],
      (v("10.78.0.2"), v("10.78.0.99")))
_elems = [e for s in PLAN["sets"] for e in s]
check("a source that could escape its quotes, or is not a prefix, never reaches a set",
      not any('"' in d or "#" in d for d, _p in _elems) and all(re.match(r"^\d+\.\d+\.\d+\.\d+/\d+$", p) for _d, p in _elems), _elems)
check("sources stay keyed by (device, prefix) — a network behind a device included",
      ["wg0", "192.168.50.0/24"] in [list(e) for e in _elems] or ("wg0", "192.168.50.0/24") in _elems)
check("an address inside a skipped overlapping subnet belongs to the first interface", v("10.8.0.200") == "jump n%d" % j["wg0"], v("10.8.0.200"))
check("no protected interface ⇒ no plan", N._reach_plan(CFG, {"ifaces": ["nope", "swg_x"], "zones": []}) is None)
check("ranges never overlap and are ordered", all(PLAN["map"][i][1] < PLAN["map"][i + 1][0] for i in range(len(PLAN["map"]) - 1)))

print("\n[2] the declared table (§13.1)")
SLOTS = {n: jj for jj, n in enumerate(PLAN["ifaces"])}
RS = N._reach_declare_text(PLAN, SLOTS)
check("created, deleted and declared in one load — the DECLARE path",
      RS.startswith("table inet swg_reach\ndelete table inet swg_reach\ntable inet swg_reach {"), RS[:80])
check("⚠️ the skeleton at mangle - 4: replies first, the guard before the map, a miss INSIDE the guard into a counted drop — "
      "never a bare drop, which took every IPv6 packet (§13.3 M)",
      'chain pre { type filter hook prerouting priority mangle - 4; policy accept; ct direction reply accept; '
      'ip daddr != @guard accept; jump sel; ip daddr @guard counter name "gc" drop; }' in RS)
check("…and `sel` holds the one vmap rule", "chain sel { ip daddr vmap @dmap_a; }" in RS)
_guard = re.search(r"set guard \{ type ipv4_addr; flags interval; elements = \{ (.*?) \} \}", RS)
check("the guard holds exactly the protected subnets", bool(_guard) and _guard.group(1).split(", ") == PLAN["subnets"], _guard and _guard.group(1))
_chains = re.findall(r"chain ([zn]\w*) \{ (.*?) \}", RS)
check("a zone accepts its sources, then counts and drops; a Nobody chain counts and drops",
      bool(_chains) and all(re.fullmatch(r'iifname \. ip saddr @f\d+_a accept; counter name "c\d+" drop;' if c.startswith("z")
                                         else r'counter name "c\d+" drop;', b) for c, b in _chains), _chains[:3])
check("each chain counts into its own interface's slot counter",
      all('counter name "c%d"' % SLOTS[PLAN["ifaces"][int((re.match(r"^z\d+i(\d+)_a$", c) or re.match(r"^n(\d+)_a$", c)).group(1))]] in b
          for c, b in _chains))
check("one counter per enforced interface, and the guard's", len(re.findall(r"counter c\d+ \{ \}", RS)) == len(PLAN["ifaces"]) and "counter gc { }" in RS)
_setl = re.findall(r"set f\d+_a \{ type ifname \. ipv4_addr;( flags interval;)?(?: elements = \{ (.*?) \})? \}", RS)
check("⚠️ a source set is HASH while every member is a /32 (written bare) and interval once one is a prefix (§11.7 memory)",
      bool(_setl) and any(not iv for iv, _e in _setl) and all(
          bool(iv) == any("/" in e and not e.endswith("/32") for e in (els or "").split(", ")) and (bool(iv) or "/" not in (els or ""))
          for iv, els in _setl), _setl)

print("\n[3] D1 and the restart")
fresh(); K = Nft(); N.run = K
for _ in range(3):
    N.reconcile_dev_reach(CFG, None, res())
check("no dev_reach: the kernel asked ONCE, then nothing", K.calls == [["nft", "list", "table", "inet", "swg_reach"]], K.calls)
check("…and no status for the snapshot", N._REACH["status"] is None)
fresh(); K = Nft(table=True); N.run = K; r = res()
N.reconcile_dev_reach(CFG, None, r)
check("a table left from before is removed", ["nft", "delete", "table", "inet", "swg_reach"] in K.calls and not K.table and r["changed"] == 1)

print("\n[4] steady state and counters")
fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res()); N.reconcile_dev_reach(CFG, WIRE, res())
check("the same reply twice loads once", len(K.loads) == 1, len(K.loads))
st = N._REACH["status"]
check("status: ok, the enforced interfaces, a since, zero stopped",
      st and st["ok"] and st["ifaces"] == PLAN["ifaces"] and st["since"] > 0 and set(st["blocked"].values()) == {0}, st)
K.counters["c%d" % j["wg0"]] = 7
N.dev_reach_verify(res())
check("the routing pass reads the counters with one fork", K.calls[-1][:4] == ["nft", "-j", "list", "counters"] and N._REACH["status"]["blocked"]["wg0"] == 7,
      N._REACH["status"])
K.counters["c%d" % N._REACH["slots"]["wg0"]] = 9
W2 = json.loads(json.dumps(WIRE)); W2["zones"][1]["to"] = ["10.8.0.9", "10.8.0.10"]
N.reconcile_dev_reach(CFG, W2, res())
check("a changed reply reloads — by a swap, the table's counters kept", len(K.loads) == 2 and "delete table" not in K.loads[-1]
      and K.counters.get("c%d" % N._REACH["slots"]["wg0"]) == 9, (len(K.loads), K.loads[-1][:60]))
N.dev_reach_verify(res())
check("⚠️ a swap zeroes nothing: the count survives it (9, not 0)", N._REACH["status"]["blocked"]["wg0"] == 9, N._REACH["status"])
K.counters["c%d" % N._REACH["slots"]["wg0"]] = 12
N.dev_reach_verify(res())
check("…and the counter keeps counting (12)", N._REACH["status"]["blocked"]["wg0"] == 12, N._REACH["status"])
W3 = {"ifaces": ["wg0"], "zones": []}
N.reconcile_dev_reach(CFG, W3, res())
check("an interface no longer protected leaves the report", list(N._REACH["status"]["blocked"]) == ["wg0"], N._REACH["status"])

print("\n[5] open and loud")
fresh(); K = Nft(); K.refuse = True; N.run = K; r = res()
N.reconcile_dev_reach(CFG, WIRE, r)
st = N._REACH["status"]
check("a refused load: status ok false with the reason and the interfaces it meant to protect",
      st and st["ok"] is False and st["why"] == "nft_failed" and "Could not process" in st["detail"] and st["ifaces"] == PLAN["ifaces"], st)
check("…an error for the log", r["errors"] and r["errors"][0].startswith("device access:"), r["errors"])
K.refuse = False
N.reconcile_dev_reach(CFG, WIRE, res())
check("…and retried on the next pass", K.table and N._REACH["status"]["ok"] is True)

print("\n[6] the routing pass")
fresh(); K = Nft(); N.run = K
N.dev_reach_verify(res())
check("nothing protected ⇒ no fork", K.calls == [])
N.reconcile_dev_reach(CFG, WIRE, res())
K.table = False; K.calls = []; r = res()
N.dev_reach_verify(r)
check("a flushed table is DECLARED again from the held plan", K.table and r["changed"] == 1
      and K.loads[-1] == N._reach_declare_text(N._REACH["plan"], N._REACH["slots"]))
K.table = False; K.refuse = True; r = res()
N.dev_reach_verify(r)
check("a rebuild that fails is forgotten, loud", N._REACH["installed"] is False and N._REACH["sig"] is None and N._REACH["status"]["ok"] is False and r["errors"])
K.refuse = False
N.reconcile_dev_reach(CFG, WIRE, res())
check("…so the next reply pass loads it again", K.table and N._REACH["status"]["ok"] is True)

print("\n[7] a conf that cannot be read this pass")
fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
_saved = CFG["interfaces"]["awg0"]["conf"]
CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
N.reconcile_dev_reach(CFG, WIRE, res())
CFG["interfaces"]["awg0"]["conf"] = _saved
check("⚠️ the interface keeps its last subnet — no reload", len(K.loads) == 1 and "awg0" in N._REACH["status"]["ifaces"], (len(K.loads), N._REACH["status"]))
fresh(); CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
check("never read at all ⇒ not enforced (nothing to hold)", "awg0" not in (N._reach_plan(CFG, WIRE) or {}).get("ifaces", []))
CFG["interfaces"]["awg0"]["conf"] = _saved

print("\n[8] the sync loop, the routing pass, the snapshot")
SRC = open(NODED, encoding="utf-8").read()
i_cq = SRC.find("cq = reconcile_csqtt(reply.get(\"csqtt\")")
i_dr = SRC.find("reconcile_dev_reach(node_cfg, reply.get(\"dev_reach\"), _dar)")
i_rc = SRC.find("r = reconcile(node_cfg, reconcile_net_share(")
check("protected after the WDTT/csqtt records, before the peer write", 0 < i_cq < i_dr < i_rc, (i_cq, i_dr, i_rc))
check("…inside a guard, so a fault never stops the peer write",
      re.search(r"try:\s+reconcile_dev_reach\(node_cfg, reply\.get\(\"dev_reach\"\), _dar\)\s+except Exception", SRC) is not None)
i_nv = SRC.find("net_share_verify(nr)")
check("the routing pass verifies beside P5", i_nv > 0 and "dev_reach_verify(nr)" in SRC[i_nv:i_nv + 200])
N._PANEL_PEER["addr"] = "198.51.100.1"
check("net_deps says reach — 2, the compact reply (§14)", N.net_deps().get("reach") == 2, N.net_deps())
check("the snapshot names dev_reach only while a status is held",
      re.search(r"if _REACH\[\"status\"\]:[^\n]*\n\s+snap\[\"dev_reach\"\] = dict\(_REACH\[\"status\"\]\)", SRC) is not None)

P = load("swgpanel", PANEL)
if PERTURB_GROUPS:
    P.roster_groups = lambda roster: {}
NOW = int(P.time.time())
K = lambda c: c * 43 + "="
def roster():
    return {"users": {"anna": {"name": "Anna"}, "erin": {"name": "Erin"}, "boris": {"name": "Boris"}, "carol": {"name": "Carol"},
                      "dora": {"name": "Dora", "disabled": True}},
            "groups": {"g1": {"name": "Ivanov family", "users": ["anna", "erin"]}, "g2": {"name": "Solo", "users": ["carol", "ghost"]}},
            "peers": {
        "anna-phone":  {"id": "anna-phone", "user_id": "anna", "pubkey": K("A"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5", "type": "wg"}]},
        "anna-laptop": {"id": "anna-laptop", "user_id": "anna", "pubkey": K("L"), "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.7", "type": "awg"}]},
        "anna-router": {"id": "anna-router", "user_id": "anna", "pubkey": K("R"), "created_at": 1, "routes": ["192.168.50.0/24"],
                        "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.6", "type": "wg"}]},
        "anna-wdtt":   {"id": "anna-wdtt", "user_id": "anna", "wdtt_password": "pwA", "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
        "anna-csqtt":  {"id": "anna-csqtt", "user_id": "anna", "csqtt_password": "pwC", "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]},
        "anna-far":    {"id": "anna-far", "user_id": "anna", "pubkey": K("F"), "targets": [{"node": "n2", "iface": "wg0", "ip": "10.8.0.13", "type": "wg"}]},
        "erin-phone":  {"id": "erin-phone", "user_id": "erin", "pubkey": K("E"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.8", "type": "wg"}]},
        "boris-phone": {"id": "boris-phone", "user_id": "boris", "pubkey": K("B"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.9", "type": "wg"},
                                                                                             {"node": "n1", "iface": "wgE", "ip": "10.10.0.2", "type": "wg"}]},
        "carol-phone": {"id": "carol-phone", "user_id": "carol", "pubkey": K("C"), "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.10", "type": "awg"}]},
        "carol-tab":   {"id": "carol-tab", "user_id": "carol", "pubkey": K("T"), "targets": [{"node": "n1", "iface": "wgN", "ip": "10.11.0.2", "type": "wg"}]},
        "dora-phone":  {"id": "dora-phone", "user_id": "dora", "pubkey": K("D"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.11", "type": "wg"}]},
        "nobodys":     {"id": "nobodys", "user_id": None, "pubkey": K("U"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.12", "type": "wg"}]},
    }}
NREC = {"id": "n1", "name": "home",
        "ifaces": {"wg0": {}, "awg0": {"mtu": 1280}, "wgE": {"reach": "everyone"}, "wgN": {"reach": "none"}, "swg_x": {"system": True}},
        "wdtt": {"wdtt1": {"iface": "wdtt1", "wg_addr": "10.77.0.1/24", "listen": "0.0.0.0:56000", "fork": "qwdtt"}},
        "csqtt": {"csqtt1": {"iface": "csqtt1", "tun_addr": "10.66.67.1/24", "listen": "0.0.0.0:46000"}}}
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {n: {"meta": {"subnet": s}} for n, s in (("wg0", "10.8.0.0/24"), ("awg0", "10.9.0.0/24"), ("wgE", "10.10.0.0/24"), ("wgN", "10.11.0.0/24"))},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1, "reach": 1},
        "wdtt": [{"iface": "wdtt1", "fork": "qwdtt", "version": "1.4.3", "active": "active", "passwords": {"pwA": {"ip": "10.77.0.2"}}}],
        "csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9", "active": "active", "passwords": {"pwC": {"ip": "10.66.67.2"}}}]}
R = roster()
CARRY = P.node_networks(R, "n1", SNAP)["carry"]

print("\n[9] dev_reach_for_node")
DR = P.dev_reach_for_node(R, NREC, "n1", SNAP, CARRY)
check("protected: every client interface not at Everyone, never a mesh link", DR.get("ifaces") == ["awg0", "csqtt1", "wdtt1", "wg0", "wgN"], DR.get("ifaces"))
zone_of = {a: z for z in DR.get("zones", []) for a in z["to"]}
fam = zone_of.get("10.8.0.5") or {"to": [], "from": []}
check("⚠️ the owner's devices and the group's share one zone — across interfaces, the vouched keyless one included",
      fam["to"] == ["10.8.0.5", "10.8.0.6", "10.8.0.8", "10.9.0.7", "10.77.0.2"], fam["to"])
check("…reachable from the owner's and the group mate's devices, the network behind the router, the vouched keyless device",
      fam["from"] == [["awg0", "10.9.0.7/32"], ["wdtt1", "10.77.0.2/32"], ["wg0", "10.8.0.5/32"], ["wg0", "10.8.0.6/32"],
                      ["wg0", "10.8.0.8/32"], ["wg0", "192.168.50.0/24"]], fam["from"])
_all_from = [tuple(e) for z in DR.get("zones", []) for e in z["from"]]
_all_to = [a for z in DR.get("zones", []) for a in z["to"]]
check("a stranger is a source only for its own zone", zone_of.get("10.8.0.9", {}).get("from") == [["wg0", "10.8.0.9/32"], ["wgE", "10.10.0.2/32"]]
      and ("wg0", "10.8.0.9/32") not in [tuple(e) for e in fam["from"]], zone_of.get("10.8.0.9"))
check("a device on an Everyone interface is a source, never a destination", "10.10.0.2" not in _all_to)
check("a Nobody interface lists no destination — its device still a source for its owner",
      "10.11.0.2" not in _all_to and zone_of.get("10.9.0.10", {}).get("from") == [["awg0", "10.9.0.10/32"], ["wgN", "10.11.0.2/32"]],
      zone_of.get("10.9.0.10"))
check("a group with a deleted member expands to the members that exist", zone_of.get("10.9.0.10", {}).get("to") == ["10.9.0.10"])
check("never listed: a blocked user, an unassigned device, another node's deployment, an unvouched keyless device",
      not ({"10.8.0.11", "10.8.0.12", "10.8.0.13", "10.66.67.2"} & (set(_all_to) | {p.split("/")[0] for _d, p in _all_from})), (_all_to, _all_from))
check("the interface list is the node record's — a snapshot missing an interface changes nothing",
      P.dev_reach_for_node(R, NREC, "n1", dict(SNAP, interfaces={}), CARRY) == DR)
check("deterministic", P.dev_reach_for_node(R, NREC, "n1", SNAP, CARRY) == DR)
check("zones ordered by their first address", [z["to"][0] for z in DR["zones"]] == sorted((z["to"][0] for z in DR["zones"]), key=P.ipaddress.ip_address))
_everyone = json.loads(json.dumps(NREC))
for _ov in list(_everyone["ifaces"].values()) + list(_everyone["wdtt"].values()) + list(_everyone["csqtt"].values()):
    _ov["reach"] = "everyone"
check("every level an explicit Everyone ⇒ {} (D1)", P.dev_reach_for_node(R, _everyone, "n1", SNAP, CARRY) == {} and P.dev_reach_guarded(_everyone, SNAP) == {})
_old = dict(SNAP, net_deps={k: v for k, v in SNAP["net_deps"].items() if k != "reach"})
check("a node that cannot enforce it gets nothing (A10)", P.dev_reach_for_node(R, NREC, "n1", _old, CARRY) == {})
check("⚠️ absent is 'user' — an interface nobody configured is protected (A3)", "wg0" in DR["ifaces"] and "reach" not in NREC["ifaces"]["wg0"])

print("\n[10] the doors, the published lists, the replies to the node")
TMP2 = tempfile.mkdtemp(prefix="devreach-panel-")
nodes_path, roster_path = os.path.join(TMP2, "nodes.json"), os.path.join(TMP2, "users.json")
json.dump({"n1": json.loads(json.dumps(NREC))}, open(nodes_path, "w"))
RD = roster(); RD["version"] = P.ROSTER_VERSION
json.dump(RD, open(roster_path, "w"))
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {"n1": SNAP}, "stats_dir": TMP2, "fleet": {},
        "panel_settings": json.loads(json.dumps(P.PANEL_SETTINGS_DEFAULTS))}
def rec():
    return json.load(open(nodes_path))["n1"]
def door(path, body):
    try:
        return P.api("POST", path, {}, body, deps)
    except Exception as e:
        return 599, {"exception": repr(e)}
c, b = door("/api/iface/update", {"node": "n1", "iface": "wg0", "reach": "none"})
check("/api/iface/update stores Nobody", c == 200 and rec()["ifaces"]["wg0"].get("reach") == "none", (c, b))
c, b = door("/api/iface/update", {"node": "n1", "iface": "wg0", "mtu": 1300})
check("…a save without reach keeps it", c == 200 and rec()["ifaces"]["wg0"].get("reach") == "none", (c, b, rec()["ifaces"]["wg0"]))
c, b = door("/api/iface/update", {"node": "n1", "iface": "wg0", "reach": "anyone"})
check("…a bad level is refused and changes nothing", c == 400 and rec()["ifaces"]["wg0"].get("reach") == "none", (c, b))
c, b = door("/api/iface/update", {"node": "n1", "iface": "wg0", "reach": "user"})
check("…'user' removes the key — absent is user", c == 200 and "reach" not in rec()["ifaces"]["wg0"], (c, b, rec()["ifaces"].get("wg0")))
c, b = door("/api/iface/create", {"node": "n1", "iface": "wg7", "protocol": "wg", "subnet": "10.30.0.0/24", "reach": "nope"})
check("/api/iface/create refuses a bad level before any record exists", c == 400 and "wg7" not in rec()["ifaces"], (c, b))
c, b = door("/api/iface/create", {"node": "n1", "iface": "wg7", "protocol": "wg", "subnet": "10.30.0.0/24", "reach": "everyone"})
check("/api/iface/create stores the preselected level", c == 200 and rec()["ifaces"].get("wg7", {}).get("reach") == "everyone", (c, b))
c, b = door("/api/wdtt/set", {"node": "n1", "iface": "wdtt1", "reach": "none"})
check("/api/wdtt/set stores Nobody", c == 200 and rec()["wdtt"]["wdtt1"].get("reach") == "none", (c, b))
c, b = door("/api/wdtt/set", {"node": "n1", "iface": "wdtt1", "reach": 7})
check("…and refuses a bad one, changing nothing", c == 400 and rec()["wdtt"]["wdtt1"].get("reach") == "none", (c, b))
c, b = door("/api/csqtt/set", {"node": "n1", "iface": "csqtt1", "reach": "everyone"})
check("/api/csqtt/set stores Everyone", c == 200 and rec()["csqtt"]["csqtt1"].get("reach") == "everyone", (c, b))
c, b = door("/api/csqtt/set", {"node": "n1", "iface": "csqtt1", "reach": "user"})
check("…and 'user' removes it", c == 200 and "reach" not in rec()["csqtt"]["csqtt1"], (c, b))
_meta = P.apply_iface_meta({"ifaces": {"wgN": {"reach": "none"}}}, {"wgN": {}, "wg0": {}})
check("the interface meta publishes the level, 'user' when absent", _meta["wgN"]["reach"] == "none" and _meta["wg0"]["reach"] == "user", _meta)
_psrc = open(PANEL, encoding="utf-8").read()
check("wdtt_cfg and csqtt_cfg publish reach",
      re.search(r'"wdtt_cfg": \{ifn: \{k: ov\.get\(k\) for k in \([^)]*"reach"\)', _psrc) is not None
      and re.search(r'"csqtt_cfg": \{ifn: \{k: ov\.get\(k\) for k in \([^)]*"reach"\)', _psrc) is not None)
_nodes = {"n1": {"wdtt": {"wdtt1": {"iface": "wdtt1", "reach": "none", "fork": "qwdtt"}}, "csqtt": {"csqtt1": {"iface": "csqtt1", "reach": "none"}}}}
check("⚠️ the node's WDTT and csqtt replies never carry the level (§10.8 Round 9)",
      "reach" not in P._wdtt_reply(R, _nodes, "n1")["wdtt1"] and "reach" not in P._csqtt_reply(R, _nodes, "n1")["csqtt1"])
check("interface_defaults.reach defaults to 'user'", P.PANEL_SETTINGS_DEFAULTS["interface_defaults"].get("reach") == "user")
deps["panel_settings"]["interface_defaults"]["reach"] = "everyone"
_before = dict(deps["panel_settings"]["interface_defaults"])
try:
    c, b = P.api("POST", "/api/panel/settings", {}, {"interface_defaults": {"dns": "1.1.1.1", "mtu": 1280, "keepalive": 25}}, deps)
except Exception as e:
    c, b = 599, {"exception": repr(e)}
check("⚠️ a settings save that does not name reach keeps the stored one (the dict is rebuilt from named keys)",
      (deps.get("panel_settings") or {}).get("interface_defaults", {}).get("reach") == "everyone", (c, b, deps.get("panel_settings", {}).get("interface_defaults")))
try:
    c, b = P.api("POST", "/api/panel/settings", {}, {"interface_defaults": {"dns": "1.1.1.1", "mtu": 1280, "keepalive": 25, "reach": "none"}}, deps)
except Exception as e:
    c, b = 599, {"exception": repr(e)}
check("…and one that names it stores it", (deps.get("panel_settings") or {}).get("interface_defaults", {}).get("reach") == "none",
      (c, deps.get("panel_settings", {}).get("interface_defaults")))

print("\n[11] the sync reply")
check("names dev_reach exactly once, behind the pass's result",
      _psrc.count('"dev_reach":') == 1 and '**({"dev_reach": _dreach} if _dreach else {})' in _psrc)
check("the pass runs only while the node can enforce and something is guarded",
      "_dr_on = snap is not None and bool(dev_reach_guarded(node, snap))" in _psrc
      and "_dreach = dev_reach_for_node(roster, node, nid, snap, _carry, compact=type(_rv) is int and _rv >= 2) if _dr_on else {}" in _psrc)
_h0 = _psrc.find("_peers_all = [q for q in (roster.get(\"peers\") or {}).values() if isinstance(q, dict)]")
_h1 = _psrc.find("_dreach = dev_reach_for_node(", _h0)
_handler = _psrc[_h0:_h1] if 0 < _h0 < _h1 else ""
check("the networks are computed once for both passes, only when one needs them",
      _handler.count("node_networks(") == 1
      and '_carry = node_networks(roster, nid, snap)["carry"] if (_share_any or (_routes_any and _dr_on)) else {}' in _handler
      and "net_share_for_node(roster, nid, _carry, snap)" in _handler, (_h0, _h1))

print("\n[12] P2 fixes (§11.2)")
fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
_sk = (N._REACH["status"] or {}).get("skipped") or {}
check("F2: the node says why a listed interface is not in its table — overlap, mesh, not run here",
      _sk.get("wgover") == "overlap" and _sk.get("swg_x") == "mesh" and _sk.get("nope") == "not_here" and "wg0" not in _sk, _sk)
CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, {"ifaces": ["awg0"], "zones": []}, res())
st = N._REACH["status"]
check("F2: …and a reply none of whose interfaces could be protected still says so, with no table loaded",
      bool(st) and st["ok"] is True and st["ifaces"] == [] and st.get("skipped") == {"awg0": "no_address"} and not K.loads, st)
CFG["interfaces"]["awg0"]["conf"] = _saved
N.reconcile_dev_reach(CFG, None, res())
check("F2: …and no reply ⇒ no status at all (D1)", N._REACH["status"] is None, N._REACH["status"])

fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
K.counters["c%d" % N._REACH["loaded"].index("wg0")] = 5
K.refuse = True; r = res()
N.reconcile_dev_reach(CFG, W2, r)
st = N._REACH["status"]
check("F3: a refused RELOAD says the latest change did not apply, and that the previous table holds",
      bool(st) and st["ok"] is False and st.get("stale") is True and st.get("why") == "nft_failed" and bool(r["errors"]), st)
check("F3: …still naming what that table enforces and what it stopped", bool(st) and st["ifaces"] == PLAN["ifaces"] and st.get("blocked", {}).get("wg0") == 5, st)
if "wg0" in N._REACH["loaded"]:                 # absent only when the previous table was forgotten — the F3 defect itself
    K.counters["c%d" % N._REACH["loaded"].index("wg0")] = 8
N.dev_reach_verify(res())
st = N._REACH["status"]
check("F3: …the routing pass keeps counting that table and keeps saying stale", bool(st) and st.get("blocked", {}).get("wg0") == 8 and st.get("stale") is True, st)
K.refuse = False
N.reconcile_dev_reach(CFG, W2, res())
st = N._REACH["status"]
check("F3: …the retry loads, clears stale, and no count is lost or doubled",
      bool(st) and st["ok"] is True and "stale" not in st and st.get("blocked", {}).get("wg0") == 8 and len(K.loads) == 2, (st, len(K.loads)))
fresh(); K = Nft(); K.refuse = True; N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
check("F3: a refused FIRST load is still open and loud — never called stale",
      N._REACH["status"]["ok"] is False and not N._REACH["status"].get("stale") and not N._REACH["installed"], N._REACH["status"])

_mi = P._missing_ifaces({"ifaces": {"wgE": {"reach": "everyone", "_lastcfg": {"subnet": "10.10.0.0/24"}},
                                    "wg0": {"_lastcfg": {"subnet": "10.8.0.0/24"}}}}, {"interfaces": {}}, None)
check("F1: a lost interface hands the recreate sheet its level — absent said as 'user'",
      _mi.get("wgE", {}).get("reach") == "everyone" and _mi.get("wg0", {}).get("reach") == "user", _mi)
_rsnap = {"wdtt": [{"iface": "q1", "fork": "qwdtt", "version": "1.4.3", "raw_iface": "q1raw"},
                   {"iface": "q2", "fork": "qwdtt", "version": "1.4.3", "raw_iface": ""},
                   {"iface": "x1", "fork": "xxcipherx", "version": "2.0.0.70"}],
          "csqtt": [{"iface": "c1", "version": "2.1.9"}]}
_ur = P.reach_unvouched_report(_rsnap) if hasattr(P, "reach_unvouched_report") else None
check("F4: unvouched per path — no path (xxcipherx, csqtt 2.1.9) vs only RAW (qWDTT 1.4.3 with RAW on); RAW off is not named",
      _ur == (["c1", "x1"], ["q1"]), _ur)
check("F4: the node list publishes both from that one helper",
      '**dict(zip(("reach_unvouched", "reach_unvouched_raw"), reach_unvouched_report(snap))),' in _psrc)
_i17 = _psrc.find('"Recorded an interface the node reports"')
_i18 = _psrc.find('"Recorded a server the node runs"')
_idr = _psrc.find("_dreach = dev_reach_for_node(")
check("F5: the pass runs after the interface mirror AND the WDTT/csqtt mirror", 0 < _i17 < _idr and 0 < _i18 < _idr, (_i17, _i18, _idr))
_js = {n: open(os.path.join(ROOT, "js", n), encoding="utf-8").read() for n in ("sheets-crud.js", "views.js", "screen-nodes.js")}
check("F7: a device deployed nowhere gets no peer-to-peer claim", "(ts => ts.length > 0 && ts.every(t => {" in _js["sheets-crud.js"])
check("F2/F3: the sheet and the card chip both read `skipped` and `stale`",
      all("st.skipped[iface]" in _js[n] and "st.stale" in _js[n] for n in ("views.js", "screen-nodes.js")))
_srv = [s for s in P.turn_catalog_view()["servers"] if s.get("kind") in ("wdtt", "csqtt")]
check("F4: the catalog says whether the build a create installs is vouched — WDTT on its WG path, csqtt on RAW",
      bool(_srv) and all(s.get("reach_vouched") is P.keyless_share_capable(s["id"], "wg" if s["kind"] == "wdtt" else "raw",
                                                                         P._wdtt_current_version(s["id"]) if s["kind"] == "wdtt" else P._csqtt_current_version())
                         for s in _srv), {s["id"]: s.get("reach_vouched") for s in _srv})
_ifjs = open(os.path.join(ROOT, "js", "iface.js"), encoding="utf-8").read()
check("F4: …and the create sheet warns from it for the chosen WDTT fork or csqtt build",
      "create=${true}\n        unvouched=" in _ifjs and ".reach_vouched" in _ifjs)
_setjs = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
check("F6: the Settings count and the window behind it read ONE list, and the window pages",
      "const everyone = reachEveryoneRows().length;" in _setjs and "pageSlice(rows, pg)" in _setjs and "<${ReachEveryoneSheet}/>" in _setjs)

print("\n[12b] the fix pass's own review (§11.2 review)")
fresh(); K = Nft(); K.refuse = True; N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
check("R3: a refused FIRST load still says why an interface was left out",
      ((N._REACH["status"] or {}).get("skipped") or {}).get("wgover") == "overlap", N._REACH["status"])
fresh(); K = Nft(table=True); K.refuse = True; N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
check("R4: a refused load over a table an EARLIER process left is stale — that table still holds — not open",
      (N._REACH["status"] or {}).get("stale") is True and N._REACH["installed"] is True and K.table, N._REACH["status"])
_g = P._ghost_ifaces({"ifaces": {"wgE": {"reach": "everyone"}, "wg0": {}}}, {"interfaces": {}},
                     {"wgE": ["p1"], "wg0": ["p2"], "wgZ": ["p3"]}, True)
check("R6: a cold ghost hands the recreate its level; with no record the panel-wide default stands",
      _g.get("wgE", {}).get("reach") == "everyone" and _g.get("wg0", {}).get("reach") == "user" and "wgZ" in _g and "reach" not in _g["wgZ"], _g)
check("R6: …and the cold path carries it to the sheet",
      "subnet: null, reach: g.reach || null" in open(os.path.join(ROOT, "js", "model.js"), encoding="utf-8").read())
_nodesjs = open(os.path.join(ROOT, "js", "screen-nodes.js"), encoding="utf-8").read()
check("R1: the card chip says Nobody for an instance whose build can't prove ownership, and RAW in the hover",
      "(nrec.reach_unvouched || []).includes(iface)" in _nodesjs and "(nrec.reach_unvouched_raw || []).includes(iface)" in _nodesjs
      and 'lv === "none" || unv ?' in _nodesjs)
check("R2: the Nodes notice counts a stale node's stopped packets", "st && (st.ok || st.stale) ?" in _nodesjs)

print("\n[13] node table v2 — swap-safe reloads (§13)")
fresh(); K = Nft(); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
check("the first load of a process DECLARES the skeleton and generation a",
      K.loads[-1].startswith("table inet swg_reach\ndelete table") and "@dmap_a" in K.loads[-1] and N._REACH["gen"] == "a" and N._REACH["declared"] is True)
_ncalls, _built, _rp3 = len(K.calls), [], N._reach_plan
N._reach_plan = lambda cfg, wire, devices=None: _built.append(1) or _rp3(cfg, wire, devices)
N.reconcile_dev_reach(CFG, WIRE, res())
N._reach_plan = _rp3
check("the same reply over the same devices builds no plan and calls no nft (the memo)", not _built and len(K.calls) == _ncalls, (_built, K.calls[_ncalls:]))
_held = N._REACH["plan"]
N.reconcile_dev_reach(CFG, W2, res())
_s = K.loads[-1]
check("⚠️ a plan change SWAPS: no `delete table`, generation b declared, `sel` repointed to it",
      "delete table" not in _s and _s.startswith("table inet swg_reach {") and N._REACH["gen"] == "b"
      and "flush chain inet swg_reach sel\nadd rule inet swg_reach sel ip daddr vmap @dmap_b" in _s, _s[:200])
_dels = [l for l in _s.splitlines() if l.startswith("delete ")]
_want = (["delete map inet swg_reach dmap_a"] + ["delete chain inet swg_reach z%di%d_a" % c for c in _held["chains"]]
         + ["delete chain inet swg_reach n%d_a" % jj for jj in range(len(_held["ifaces"]))]
         + ["delete set inet swg_reach f%d_a" % k for k in range(len(_held["sets"]))])
check("…deleting exactly the held generation's names, the map before its chains before their sets", _dels == _want, (_dels, _want))
N.reconcile_dev_reach(CFG, WIRE, res())
check("…and the next swap alternates back to a", N._REACH["gen"] == "a" and "vmap @dmap_a" in K.loads[-1] and "delete map inet swg_reach dmap_b" in K.loads[-1])
N.reconcile_dev_reach(CFG, {"ifaces": ["wg0"], "zones": []}, res())
check("subnets no longer protected leave the guard in the swap", "delete element inet swg_reach guard { 10.9.0.0/24, 10.66.67.0/24, 10.77.0.0/24, 10.78.0.0/24 }"
      in K.loads[-1] and "add element" not in K.loads[-1], K.loads[-1][-300:])
N.reconcile_dev_reach(CFG, WIRE, res())
check("…and arrive in it again", "add element inet swg_reach guard { 10.9.0.0/24, 10.66.67.0/24, 10.77.0.0/24, 10.78.0.0/24 }" in K.loads[-1]
      and not re.findall(r"counter c\d+ \{ \}", K.loads[-1]))
CFG["interfaces"]["wg7"] = {"conf": conf("wg7", "10.21.0.1/24")}
_W5 = json.loads(json.dumps(WIRE)); _W5["ifaces"].append("wg7")
N.reconcile_dev_reach(CFG, _W5, res())
check("a counter is declared only for an interface the table lacks, on a slot never used before",
      re.findall(r"counter (c\d+) \{ \}", K.loads[-1]) == ["c4"] and N._REACH["slots"].get("wg7") == 4, (re.findall(r"counter (c\d+) \{ \}", K.loads[-1]), N._REACH["slots"]))
del CFG["interfaces"]["wg7"]
_snap = (N._REACH["gen"], N._REACH["plan"], dict(N._REACH["slots"]), N._REACH["sig"])
K.refuse = True
N.reconcile_dev_reach(CFG, W2, res())
K.refuse = False
check("a refused swap leaves generation, plan, slots and memo — and says stale",
      (N._REACH["gen"], N._REACH["plan"], N._REACH["slots"], N._REACH["sig"]) == _snap and (N._REACH["status"] or {}).get("stale") is True, N._REACH["status"])
N.reconcile_dev_reach(CFG, W2, res())
check("…and the next pass DECLARES rather than retrying that swap (nft 1.0.2 refuses an overlapping guard change a declare loads)",
      K.loads[-1].startswith("table inet swg_reach\ndelete table") and N._REACH["stale"] is None and N._REACH["gen"] == "a", K.loads[-1][:60])
fresh(); K = Nft(table=True); N.run = K
N.reconcile_dev_reach(CFG, WIRE, res())
check("a table an earlier process left is DECLARED over, never swapped", K.loads[-1].startswith("table inet swg_reach\ndelete table"))
check("⚠️ the node's own address stays reachable: a map `accept` inside the guard", "10.8.0.1 : accept" in K.loads[-1])

print("\n[14] the compact wire (§14)")
DC = P.dev_reach_for_node(R, NREC, "n1", SNAP, CARRY, compact=True)
def _zones_of(d):
    us = d.get("users")
    return sorted([sorted(z["to"]), sorted({tuple(s) for i in z["users"] for s in us[i]} if us is not None else {tuple(s) for s in z["from"]})]
                  for z in d["zones"])
check("the compact reply expands to exactly the v1 reply's zones", _zones_of(DC) == _zones_of(DR) and len(DC["zones"]) == len(DR["zones"]), (DC, DR))
check("…each source listed once, under its user", sum(len(u) for u in DC["users"]) == len({tuple(s) for u in DC["users"] for s in u}), DC["users"])
check("…and a node reporting reach 1 gets the v1 shape: `from`, no `users`", "users" not in DR and all("from" in z and "users" not in z for z in DR["zones"]))
_pv1, _pc = N._reach_plan(CFG, DR), N._reach_plan(CFG, DC)
check("the node plans the same table from either shape", _pv1 is not None and _pv1 == _pc, (_pv1, _pc))
_bad = json.loads(json.dumps(DC)); _bad["zones"][0]["users"] = [99, -1, "0", True] + _bad["zones"][0]["users"]
check("an index out of range, negative, a string or a bool names nobody", N._reach_plan(CFG, _bad) == _pc)
_narrow = json.loads(json.dumps(DC)); _narrow["zones"][0]["users"] = [99]
check("…so a zone left with no valid user is reachable by nobody (fail closed)", N._reach_plan(CFG, _narrow) != _pc)
check("the handler sends the compact shape only to a node reporting an int reach >= 2",
      '_rv = (snap.get("net_deps") or {}).get("reach") if snap is not None else None' in _psrc)

shutil.rmtree(TMP2, ignore_errors=True)
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
