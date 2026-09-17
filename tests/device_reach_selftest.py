#!/usr/bin/env python3
"""Self-test for DEVICE ACCESS — who may open a connection to a device (docs/DEVICE-ACCESS-PLAN.md §10, §13, §14, §16).

Per client interface a level: Everyone (stored `"everyone"`), Same user and their groups (absent), Nobody (`"none"`). The
panel sends `dev_reach` only while some interface on a node is not at Everyone; the node enforces it with one prerouting
table, `swg_reach`, whose map covers each protected subnet whole — listed devices to their zone, the rest to Nobody.

The node's loads run against `nft_guarded_model` (tests/): a transaction model of the table that refuses what nft was measured
refusing and walks a packet through `pre` — so what is checked is who reaches what, not how the file is laid out.

 NODE
  [1] the plan: the node's own address is a map `accept` and the subnets are listed whole for the guard, the network address and every unlisted address go to the
      interface's Nobody chain, a listed device to its zone; an address two zones claim falls to the rest; an address
      outside every listed subnet, an unknown interface, a mesh link and a source element that could escape its quotes
      never reach nft; a WDTT instance brings its RAW TUN under its own counter; an overlapping subnet is skipped.
  [2] the declared table: the skeleton line exact (replies first, guard before map, a miss inside the guard dropped — never a
      bare drop, which took IPv6); then by packet: a zone's source in, a stranger out, the node's own address, replies, IPv6 and
      everything outside the guard untouched; a drop counts into its interface's counter; no concat interval set (§16 C2).
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
 [12] P2 fixes (§11.2): F1 a lost interface hands the recreate sheet its level · F2 the node says why a listed interface is not in
      its table, also when it holds no table · F3 a refused RELOAD keeps counting the previous table and says stale, a refused
      FIRST load stays open · F4 unvouched builds per path · F5 the pass after both mirrors · F7 no peer-to-peer claim for a device
      deployed nowhere.
 [13] swap-safe reloads (§13): the first load DECLARES; the same reply builds nothing (memo); a plan change SWAPS — no `delete
      table`, `sel` repointed, the held generation gone whole, the suffix alternating; the guard moves with the protected subnets;
      a drop lands in the same counter in every generation; a refused swap leaves generation, plan and memo; a leftover table is
      declared over.
 [14] the compact wire (§14, the only shape since §16 B1): each source once; a node below reach 2 gets nothing; a bad index names
      nobody; a zone written the old way names nobody; the SPA's capability check matches the panel's.
 [15] §16: A1 a fault inside the reconciler is a status, not a stale one · A3 a swap refused because the table vanished is open ·
      A4 an unknown stored level is Nobody · B2 a count survives a declare its interface was not part of · B3 a refused load
      reports the reasons of the table in force · C2 a network source reaches only arriving on its own interface, and nested
      network sources load.
 F-P3a (1.8.7 qualification PART 3): a refused load or a fault over a table that no longer ENFORCES — flushed in place, or a
      stranger's by that name — is open, never "stale"; only a table passing `_gtable_intact` holds (R4 / A1 use a real leftover).

Hermetic. Run: python3 tests/device_reach_selftest.py            (0 = pass)
     --perturb          maps only the listed devices (no "rest is Nobody") and expects RED on [1].
     --perturb-reply    drops the reply exemption from the declared table and expects RED on [2].
     --perturb-hold     forgets the last subnet on a failed read and expects RED on [7].
     --perturb-groups   forgets every group when planning and expects RED on [9].
     --perturb-skipped  forgets why interfaces were left out and expects RED on [12] F2.
     --perturb-stale    calls every refused load open and expects RED on [12] F3.
     --perturb-swap     reloads a plan change by delete + recreate, as v1 (§11.7's leak), and expects RED on [13].
     --perturb-guard    drops the node's own `accept` from the map, so it falls into the guard, and expects RED on [1] and [13].
     --perturb-compact  makes the node ignore `users` and expects RED on [14].
     --perturb-fault    removes the reconciler's own fault handler and expects RED on [15] A1.
     --perturb-vanished calls a vanished table held and expects RED on [15] A3.
     --perturb-iface    matches a network source from any interface and expects RED on [15] C2.
     --perturb-retry    stops declaring after a refused swap and expects RED on [13] (nft 1.0.2) and [15] A3.
     --perturb-open     makes the node ignore `open` (the rest of a promoted interface is Nobody again) and expects RED on [16].
     --perturb-held     calls any table whose counters read "held" (the pre-F-P3a rule) and expects RED on the F-P3a checks in [12b] and [15].
"""
import copy, importlib.machinery, importlib.util, inspect, ipaddress, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from nft_guarded_model import Kernel, _span   # noqa: E402

NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
ARGS = set(sys.argv[1:])
PERTURB = "--perturb" in ARGS
PERTURB_REPLY = "--perturb-reply" in ARGS
PERTURB_HOLD = "--perturb-hold" in ARGS
PERTURB_GROUPS = "--perturb-groups" in ARGS
PERTURB_SKIPPED = "--perturb-skipped" in ARGS
PERTURB_STALE = "--perturb-stale" in ARGS
PERTURB_SWAP = "--perturb-swap" in ARGS
PERTURB_GUARD = "--perturb-guard" in ARGS
PERTURB_COMPACT = "--perturb-compact" in ARGS
PERTURB_FAULT = "--perturb-fault" in ARGS
PERTURB_VANISHED = "--perturb-vanished" in ARGS
PERTURB_IFACE = "--perturb-iface" in ARGS
PERTURB_RETRY = "--perturb-retry" in ARGS
PERTURB_OPEN = "--perturb-open" in ARGS
PERTURB_HELD = "--perturb-held" in ARGS

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
T = "swg_reach"

if PERTURB:
    _rp = N._reach_plan
    def _no_rest(cfg, wire, devices=None):
        p, sk = _rp(cfg, wire, devices)
        return (p and dict(p, map=[e for e in p["map"] if not e[2].startswith("jump n")])), sk
    N._reach_plan = _no_rest
if PERTURB_REPLY:
    _gd = N._gtable_declare
    N._gtable_declare = lambda *a: _gd(*a).replace("ct direction reply accept; ", "")
if PERTURB_HOLD:
    _rd = N._reach_devices
    def _forget(cfg, names):
        N._REACH["seen"] = {}
        return _rd(cfg, names)
    N._reach_devices = _forget
if PERTURB_SKIPPED:
    _rp2 = N._reach_plan
    N._reach_plan = lambda cfg, wire, devices=None: (_rp2(cfg, wire, devices)[0], {})
if PERTURB_STALE:
    _rc = N._reach_read_counters
    N._reach_read_counters = lambda: None if getattr(N.run, "last_refused", False) else _rc()
if PERTURB_SWAP:
    N._gtable_swap = lambda table, old_guard, guard, counters, gen, old: N._gtable_declare(table, N.REACH_HOOK_PRI, guard, counters, gen)
if PERTURB_GUARD:
    _rpg = N._reach_plan
    def _no_accept(cfg, wire, devices=None):
        p, sk = _rpg(cfg, wire, devices)
        return (p and dict(p, map=[e for e in p["map"] if e[2] != "accept"])), sk
    N._reach_plan = _no_accept
if PERTURB_COMPACT:
    _rpc = N._reach_plan
    N._reach_plan = lambda cfg, wire, devices=None: _rpc(cfg, {k: v for k, v in wire.items() if k != "users"} if isinstance(wire, dict) else wire, devices)
if PERTURB_FAULT:
    N.reconcile_dev_reach = lambda cfg, wire, res: N._reach_converge(cfg, wire, res)
if PERTURB_OPEN:
    _rpo = N._reach_plan
    N._reach_plan = lambda cfg, wire, devices=None: _rpo(cfg, {k: v for k, v in wire.items() if k != "open"} if isinstance(wire, dict) else wire, devices)
if PERTURB_HELD:
    N._reach_held = lambda: N._reach_read_counters() if N._REACH["installed"] else None
if PERTURB_VANISHED:
    _rcv = N._reach_read_counters
    N._reach_read_counters = lambda: _rcv() if T in N.run.m.tables else {}
if PERTURB_RETRY:
    def _no_retry(swap, declare):
        if swap is not None:
            return N.run(["nft", "-f", "-"], input_text=swap[0]), swap[1], True
        text, gen = declare()
        return N.run(["nft", "-f", "-"], input_text=text), gen, False
    N._gtable_load = _no_retry
if PERTURB_IFACE:
    _rg = N._reach_generation
    N._reach_generation = lambda plan, g: dict(_rg(plan, g), lines=[re.sub(r'iifname "[^"]+" ip saddr', "ip saddr", l) for l in _rg(plan, g)["lines"]])

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
                    skipped={}, stale=None, declared=False, gen="a", names=None)

def res():
    return {"changed": 0, "errors": []}

def plan_of(cfg, wire, devices=None):
    p = N._reach_plan(cfg, wire, devices)
    return p if isinstance(p, tuple) else (p, dict(N._REACH.get("skipped") or {}))

def kernel(**kw):
    k = Kernel(**kw)
    N.run = k
    return k

def pk(iif, saddr, daddr, **kw):
    return K.m.packet(T, iif, saddr, daddr, **kw)[0]

def drops(n, iif, saddr, daddr):
    for _ in range(n):
        assert pk(iif, saddr, daddr) == "drop", (iif, saddr, daddr)

DECLARE = "table inet swg_reach\ndelete table inet swg_reach\ntable inet swg_reach {"

# Users: 0 = anna (her phone, her laptop, the network behind her router; a source that could escape its quotes; one that is no
# prefix), 1 = boris, 2 = the WDTT instance's device on both paths.
WIRE = {"ifaces": ["awg0", "wg0", "wdtt1", "csqtt1", "swg_x", "nope", 'wg0" drop', "wgover"],
        "users": [[["wg0", "10.8.0.5/32"], ["awg0", "10.9.0.7/32"], ["wg0", "192.168.50.0/24"], ['wg0" accept; #', "10.8.0.6/32"], ["wg0", "not-a-prefix"]],
                  [["wg0", "10.8.0.9/32"]],
                  [["wdtt1", "10.77.0.2/32"], ["wdtt1raw", "10.78.0.2/32"]]],
        "zones": [{"to": ["10.8.0.5", "10.9.0.7", "10.8.0.1", "172.16.0.9"], "users": [0]},
                  {"to": ["10.8.0.9", "10.8.0.5"], "users": [1]},
                  {"to": ["10.77.0.2", "10.78.0.2"], "users": [2]}]}
W2 = json.loads(json.dumps(WIRE)); W2["zones"][1]["to"] = ["10.8.0.9", "10.8.0.10"]

def verdicts(plan):
    """{address as int: verdict} by walking the map's ranges."""
    return lambda a: next((v for lo, hi, v in plan["map"] if lo <= int(ipaddress.ip_address(a)) <= hi), None)

print("\n[1] the plan")
fresh()
PLAN, SKIP = plan_of(CFG, WIRE)
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
check("a listed device jumps to its zone", (v("10.9.0.7") or "").startswith("jump z") and (v("10.8.0.9") or "").startswith("jump z"), (v("10.9.0.7"), v("10.8.0.9")))
check("⚠️ an address two zones claim is in neither — the rest, Nobody", v("10.8.0.5") == "jump n%d" % j["wg0"], v("10.8.0.5"))
check("an address outside every listed subnet is not in the map", v("172.16.0.9") is None)
check("a zone device counts into its own interface: 10.9.0.7 → awg0's chain", (v("10.9.0.7") or "").endswith("i%d" % j["awg0"]), v("10.9.0.7"))
check("the WDTT RAW TUN is protected under the instance's chain", (v("10.78.0.2") or "").endswith("i%d" % j["wdtt1"]) and v("10.78.0.99") == "jump n%d" % j["wdtt1"],
      (v("10.78.0.2"), v("10.78.0.99")))
_elems = [e for s in PLAN["sets"] for e in s]
check("a source that could escape its quotes, or is not a prefix, never reaches a set",
      not any('"' in d or "#" in d for d, _p in _elems) and all(re.match(r"^\d+\.\d+\.\d+\.\d+/\d+$", p) for _d, p in _elems), _elems)
check("sources stay keyed by (device, prefix) — a network behind a device included",
      ["wg0", "192.168.50.0/24"] in [list(e) for e in _elems] or ("wg0", "192.168.50.0/24") in _elems)
check("an address inside a skipped overlapping subnet belongs to the first interface", v("10.8.0.200") == "jump n%d" % j["wg0"], v("10.8.0.200"))
check("no protected interface ⇒ no plan", plan_of(CFG, {"ifaces": ["nope", "swg_x"], "users": [], "zones": []})[0] is None)
check("ranges never overlap and are ordered", all(PLAN["map"][i][1] < PLAN["map"][i + 1][0] for i in range(len(PLAN["map"]) - 1)))

print("\n[2] the declared table (§13.1, §16)")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
RS = K.loads[-1] if K.loads else ""
TB = K.m.tables.get(T) or {"sets": {}, "maps": {}, "chains": {}, "counters": {}}
check("created, deleted and declared in one load — the DECLARE path", RS.startswith(DECLARE), RS[:80])
check("⚠️ the skeleton at mangle - 4: replies first, the guard before the map, a miss INSIDE the guard into a counted drop — "
      "never a bare drop, which took every IPv6 packet (§13.3 M)",
      'chain pre { type filter hook prerouting priority mangle - 4; policy accept; ct direction reply accept; '
      'ip daddr != @guard accept; jump sel; ip daddr @guard counter name "gc" drop; }' in RS)
check("the guard holds exactly the protected subnets",
      sorted((x["lo"], x["hi"]) for x in TB["sets"].get("guard", {}).get("els", [])) == sorted(_span(p) for p in PLAN["subnets"]))
check("a zone's sources reach its device, from any of their interfaces",
      pk("wg0", "10.8.0.5", "10.9.0.7") == "accept" and pk("awg0", "10.9.0.7", "10.9.0.7") == "accept" and pk("wg0", "192.168.50.7", "10.9.0.7") == "accept")
check("…a stranger does not; nor a device two zones claim, nor an unlisted one",
      pk("wg0", "10.8.0.9", "10.9.0.7") == "drop" and pk("wg0", "10.8.0.9", "10.8.0.5") == "drop" and pk("wg0", "10.8.0.5", "10.8.0.77") == "drop")
check("⚠️ the node's own address is reachable by anyone on the subnet", pk("wg0", "10.8.0.9", "10.8.0.1") == "accept" and pk("csqtt1", "10.66.67.9", "10.66.67.1") == "accept")
check("replies pass (a device may answer what it opened)", pk("wg0", "10.8.0.9", "10.9.0.7", reply=True) == "accept")
check("⚠️ IPv6 and everything outside the guard are never touched", K.m.packet(T, "wg0", "", "", v6=True)[0] == "accept"
      and pk("wg0", "10.8.0.9", "1.1.1.1") == "accept" and pk("eth0", "203.0.113.9", "172.16.0.9") == "accept")
_cw, _ca = K.m.packet(T, "wg0", "10.8.0.9", "10.8.0.77")[1], K.m.packet(T, "wg0", "10.8.0.9", "10.9.0.7")[1]
_craw, _cwd = K.m.packet(T, "wg0", "10.8.0.9", "10.78.0.99")[1], K.m.packet(T, "wg0", "10.8.0.9", "10.77.0.99")[1]
check("a drop counts into its destination interface's counter — one per enforced interface, the RAW TUN under its instance's",
      len(TB["counters"]) == len(PLAN["ifaces"]) + 1 and len({_cw, _ca, _cwd}) == 3 and _craw == _cwd and "gc" not in (_cw, _ca, _cwd),
      (_cw, _ca, _craw, _cwd, TB["counters"]))
check("⚠️ no concat INTERVAL set — ~0.31 MiB of kernel memory each however small (§11.7); a network source sits in a plain set (§16 C2)",
      bool(TB["sets"]) and not any("interval" in s["flags"] for s in TB["sets"].values() if s["type"] == "ifname . ipv4_addr")
      and any(n != "guard" and s["type"] == "ipv4_addr" for n, s in TB["sets"].items()), {n: (s["type"], sorted(s["flags"])) for n, s in TB["sets"].items()})

print("\n[3] D1 and the restart")
fresh(); K = kernel()
for _ in range(3):
    N.reconcile_dev_reach(CFG, None, res())
check("no dev_reach: the kernel asked ONCE, then nothing", K.calls == [["nft", "list", "table", "inet", "swg_reach"]], K.calls)
check("…and no status for the snapshot", N._REACH["status"] is None)
fresh(); K = kernel(); K.leftover(T); r = res()
N.reconcile_dev_reach(CFG, None, r)
check("a table left from before is removed", ["nft", "delete", "table", "inet", "swg_reach"] in K.calls and T not in K.m.tables and r["changed"] == 1)

print("\n[4] steady state and counters")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res()); N.reconcile_dev_reach(CFG, WIRE, res())
check("the same reply twice loads once", len(K.loads) == 1, len(K.loads))
st = N._REACH["status"]
check("status: ok, the enforced interfaces, a since, zero stopped",
      st and st["ok"] and st["ifaces"] == PLAN["ifaces"] and st["since"] > 0 and set(st["blocked"].values()) == {0}, st)
drops(7, "wg0", "10.8.0.5", "10.8.0.77")
N.dev_reach_verify(res())
check("the routing pass reads the counters and the skeleton rule — two small forks, never the whole table",
      K.calls[-2][:4] == ["nft", "-j", "list", "counters"] and K.calls[-1][:6] == ["nft", "list", "chain", "inet", T, "pre"]
      and N._REACH["status"]["blocked"]["wg0"] == 7, (K.calls[-2:], N._REACH["status"]))
drops(2, "wg0", "10.8.0.5", "10.8.0.77")
N.reconcile_dev_reach(CFG, W2, res())
check("a changed reply reloads — by a swap", len(K.loads) == 2 and "delete table" not in K.loads[-1], (len(K.loads), K.loads[-1][:60]))
N.dev_reach_verify(res())
check("⚠️ a swap zeroes nothing: the count survives it (9, not 0)", N._REACH["status"]["blocked"]["wg0"] == 9, N._REACH["status"])
drops(3, "wg0", "10.8.0.5", "10.8.0.77")
N.dev_reach_verify(res())
check("…and the counter keeps counting (12)", N._REACH["status"]["blocked"]["wg0"] == 12, N._REACH["status"])
W3 = {"ifaces": ["wg0"], "users": [], "zones": []}
N.reconcile_dev_reach(CFG, W3, res())
check("an interface no longer protected leaves the report", list(N._REACH["status"]["blocked"]) == ["wg0"], N._REACH["status"])

# ⚠️ `nft flush table` keeps the table, its counters and its sets, and empties the chains — measured on swgt (1.8.7 §D4): a stranger
# reached a private device for as long as it stood, the node reporting ok. The name and the counters are no evidence.
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
K.flush_rules(T)
check("fixture: flushed in place, a stranger is let in", pk("wg0", "10.8.0.9", "10.9.0.7") == "accept")
_nl = len(K.loads)
N.dev_reach_verify(res())
check("⚠️ a table standing but EMPTIED is declared again from the held plan — not read as enforcing",
      len(K.loads) == _nl + 1 and K.loads[-1].startswith(DECLARE), (len(K.loads), _nl))
check("…and the stranger is dropped again, the status still ok", pk("wg0", "10.8.0.9", "10.9.0.7") == "drop" and N._REACH["status"]["ok"],
      N._REACH["status"])

print("\n[5] open and loud")
fresh(); K = kernel(); K.refuse = True; r = res()
N.reconcile_dev_reach(CFG, WIRE, r)
st = N._REACH["status"]
check("a refused load: status ok false with the reason and the interfaces it meant to protect",
      st and st["ok"] is False and st["why"] == "nft_failed" and "Could not process" in st["detail"] and st["ifaces"] == PLAN["ifaces"], st)
check("…an error for the log", r["errors"] and r["errors"][0].startswith("device access:"), r["errors"])
check("…and nothing dropped meanwhile — the devices are open, as the status says", pk("wg0", "10.8.0.9", "10.9.0.7") == "accept")
K.refuse = False
N.reconcile_dev_reach(CFG, WIRE, res())
check("…and retried on the next pass", T in K.m.tables and N._REACH["status"]["ok"] is True)

print("\n[6] the routing pass")
fresh(); K = kernel()
N.dev_reach_verify(res())
check("nothing protected ⇒ no fork", K.calls == [])
N.reconcile_dev_reach(CFG, WIRE, res())
K.flush(T); K.calls = []; r = res()
N.dev_reach_verify(r)
check("a flushed table is DECLARED again from the held plan", T in K.m.tables and r["changed"] == 1 and K.loads[-1].startswith(DECLARE)
      and pk("wg0", "10.8.0.9", "10.9.0.7") == "drop" and pk("wg0", "10.8.0.5", "10.9.0.7") == "accept")
K.flush(T); K.refuse = True; r = res()
N.dev_reach_verify(r)
check("a rebuild that fails is forgotten, loud", N._REACH["installed"] is False and N._REACH["sig"] is None and N._REACH["status"]["ok"] is False and r["errors"])
K.refuse = False
N.reconcile_dev_reach(CFG, WIRE, res())
check("…so the next reply pass loads it again", T in K.m.tables and N._REACH["status"]["ok"] is True)

print("\n[7] a conf that cannot be read this pass")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
_saved = CFG["interfaces"]["awg0"]["conf"]
CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
N.reconcile_dev_reach(CFG, WIRE, res())
CFG["interfaces"]["awg0"]["conf"] = _saved
check("⚠️ the interface keeps its last subnet — no reload", len(K.loads) == 1 and "awg0" in N._REACH["status"]["ifaces"], (len(K.loads), N._REACH["status"]))
fresh(); CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
check("never read at all ⇒ not enforced (nothing to hold)", "awg0" not in (plan_of(CFG, WIRE)[0] or {}).get("ifaces", []))
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
PK = lambda c: c * 43 + "="
def roster():
    return {"users": {"anna": {"name": "Anna"}, "erin": {"name": "Erin"}, "boris": {"name": "Boris"}, "carol": {"name": "Carol"},
                      "dora": {"name": "Dora", "disabled": True}},
            "groups": {"g1": {"name": "Ivanov family", "users": ["anna", "erin"]}, "g2": {"name": "Solo", "users": ["carol", "ghost"]}},
            "peers": {
        "anna-phone":  {"id": "anna-phone", "user_id": "anna", "pubkey": PK("A"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5", "type": "wg"}]},
        "anna-laptop": {"id": "anna-laptop", "user_id": "anna", "pubkey": PK("L"), "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.7", "type": "awg"}]},
        "anna-router": {"id": "anna-router", "user_id": "anna", "pubkey": PK("R"), "created_at": 1, "routes": ["192.168.50.0/24"],
                        "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.6", "type": "wg"}]},
        "anna-wdtt":   {"id": "anna-wdtt", "user_id": "anna", "wdtt_password": "pwA", "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
        "anna-csqtt":  {"id": "anna-csqtt", "user_id": "anna", "csqtt_password": "pwC", "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]},
        "anna-far":    {"id": "anna-far", "user_id": "anna", "pubkey": PK("F"), "targets": [{"node": "n2", "iface": "wg0", "ip": "10.8.0.13", "type": "wg"}]},
        "erin-phone":  {"id": "erin-phone", "user_id": "erin", "pubkey": PK("E"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.8", "type": "wg"}]},
        "boris-phone": {"id": "boris-phone", "user_id": "boris", "pubkey": PK("B"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.9", "type": "wg"},
                                                                                              {"node": "n1", "iface": "wgE", "ip": "10.10.0.2", "type": "wg"}]},
        "carol-phone": {"id": "carol-phone", "user_id": "carol", "pubkey": PK("C"), "targets": [{"node": "n1", "iface": "awg0", "ip": "10.9.0.10", "type": "awg"}]},
        "carol-tab":   {"id": "carol-tab", "user_id": "carol", "pubkey": PK("T"), "targets": [{"node": "n1", "iface": "wgN", "ip": "10.11.0.2", "type": "wg"}]},
        "dora-phone":  {"id": "dora-phone", "user_id": "dora", "pubkey": PK("D"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.11", "type": "wg"}]},
        "nobodys":     {"id": "nobodys", "user_id": None, "pubkey": PK("U"), "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.12", "type": "wg"}]},
    }}
NREC = {"id": "n1", "name": "home",
        "ifaces": {"wg0": {}, "awg0": {"mtu": 1280}, "wgE": {"reach": "everyone"}, "wgN": {"reach": "none"}, "swg_x": {"system": True}},
        "wdtt": {"wdtt1": {"iface": "wdtt1", "wg_addr": "10.77.0.1/24", "listen": "0.0.0.0:56000", "fork": "qwdtt"}},
        "csqtt": {"csqtt1": {"iface": "csqtt1", "tun_addr": "10.66.67.1/24", "listen": "0.0.0.0:46000"}}}
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {n: {"meta": {"subnet": s}} for n, s in (("wg0", "10.8.0.0/24"), ("awg0", "10.9.0.0/24"), ("wgE", "10.10.0.0/24"), ("wgN", "10.11.0.0/24"))},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1, "reach": 2},
        "wdtt": [{"iface": "wdtt1", "fork": "qwdtt", "version": "1.4.3", "active": "active", "passwords": {"pwA": {"ip": "10.77.0.2"}}}],
        "csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9", "active": "active", "passwords": {"pwC": {"ip": "10.66.67.2"}}}]}
R = roster()
CARRY = P.node_networks(R, "n1", SNAP)["carry"]

def _skey(s):
    n = ipaddress.ip_network(s[1])
    return (s[0], int(n.network_address), n.prefixlen)
def zone_src(d, z):
    """A compact zone's sources, expanded: every source of every user it names, sorted as the panel sorts them."""
    return [list(s) for s in sorted({tuple(s) for i in z.get("users", []) for s in d["users"][i]}, key=_skey)]

print("\n[9] dev_reach_for_node")
DR = P.dev_reach_for_node(R, NREC, "n1", SNAP, CARRY)
check("protected: every client interface not at Everyone, never a mesh link", DR.get("ifaces") == ["awg0", "csqtt1", "wdtt1", "wg0", "wgN"], DR.get("ifaces"))
zone_of = {a: z for z in DR.get("zones", []) for a in z["to"]}
fam = zone_of.get("10.8.0.5") or {"to": [], "users": []}
check("⚠️ the owner's devices and the group's share one zone — across interfaces, the vouched keyless one included",
      fam["to"] == ["10.8.0.5", "10.8.0.6", "10.8.0.8", "10.9.0.7", "10.77.0.2"], fam["to"])
check("…reachable from the owner's and the group mate's devices, the network behind the router, the vouched keyless device",
      bool(DR) and zone_src(DR, fam) == [["awg0", "10.9.0.7/32"], ["wdtt1", "10.77.0.2/32"], ["wg0", "10.8.0.5/32"], ["wg0", "10.8.0.6/32"],
                                         ["wg0", "10.8.0.8/32"], ["wg0", "192.168.50.0/24"]], bool(DR) and zone_src(DR, fam))
_all_from = [tuple(e) for u in DR.get("users", []) for e in u]
_all_to = [a for z in DR.get("zones", []) for a in z["to"]]
_stranger = zone_of.get("10.8.0.9")
check("a stranger is a source only for its own zone", bool(_stranger) and zone_src(DR, _stranger) == [["wg0", "10.8.0.9/32"], ["wgE", "10.10.0.2/32"]]
      and ["wg0", "10.8.0.9/32"] not in zone_src(DR, fam), _stranger)
check("a device on an Everyone interface is a source, never a destination", "10.10.0.2" not in _all_to)
_carol = zone_of.get("10.9.0.10")
check("a Nobody interface lists no destination — its device still a source for its owner",
      "10.11.0.2" not in _all_to and bool(_carol) and zone_src(DR, _carol) == [["awg0", "10.9.0.10/32"], ["wgN", "10.11.0.2/32"]], _carol)
check("a group with a deleted member expands to the members that exist", (_carol or {}).get("to") == ["10.9.0.10"])
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
      re.search(r'"wdtt_cfg": \{ifn: \{k: \(reach_level\(ov\.get\(k\)\) if k == "reach" else ov\.get\(k\)\) for k in \([^)]*"reach"\)', _psrc) is not None
      and re.search(r'"csqtt_cfg": \{ifn: \{k: \(reach_level\(ov\.get\(k\)\) if k == "reach" else ov\.get\(k\)\) for k in \([^)]*"reach"\)', _psrc) is not None)
_nodes = {"n1": {"wdtt": {"wdtt1": {"iface": "wdtt1", "reach": "none", "fork": "qwdtt"}}, "csqtt": {"csqtt1": {"iface": "csqtt1", "reach": "none"}}}}
check("⚠️ the node's WDTT and csqtt replies never carry the level (§10.8 Round 9)",
      "reach" not in P._wdtt_reply(R, _nodes, "n1")["wdtt1"] and "reach" not in P._csqtt_reply(R, _nodes, "n1")["csqtt1"])
check("interface_defaults.reach defaults to 'user'", P.PANEL_SETTINGS_DEFAULTS["interface_defaults"].get("reach") == "user")
deps["panel_settings"]["interface_defaults"]["reach"] = "everyone"
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
check("the pass runs only while the node can enforce and something is guarded OR promoted",
      "_dr_on = snap is not None and bool(dev_reach_guarded(node, snap) or _promo)" in _psrc
      and "_dreach = dev_reach_for_node(roster, node, nid, snap, _carry, _promo) if _dr_on else {}" in _psrc)
# ⚠️ THE INVARIANT THE GREP ABOVE CANNOT STATE, and the one that was broken: on a node where EVERY interface is an
# explicit Everyone, dev_reach_guarded() is empty — so a gate that consults only it skips the pass, and the promotion
# living inside dev_reach_for_node never runs. That is the ordinary single-interface node, and the only shape promotion
# exists for, so the whole device half of Private was dead there while the peer sheet promised it. Behavioural: the two
# functions the gate is built from must disagree exactly this way.
_ev_node = {"id": "n1", "ifaces": {"wg0": {"reach": "everyone"}}}
_ev_snap = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}},
            "net_deps": {"panel": "p", "resolvers": [], "resolvers_known": True, "reach": 2}}
_ev_roster = {"users": {"anna": {"name": "Anna"}, "boris": {"name": "Boris"}},
              "peers": {"apriv": {"id": "apriv", "user_id": "anna", "private": True, "pubkey": "ap".ljust(43, "x") + "=",
                                  "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.2", "type": "wg"}]},
                        "b1": {"id": "b1", "user_id": "boris", "pubkey": "b1".ljust(43, "x") + "=",
                               "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.3", "type": "wg"}]}}}
check("⚠️ an all-Everyone node guards nothing by itself — which is why the gate cannot ask only that",
      P.dev_reach_guarded(_ev_node, _ev_snap) == {}, P.dev_reach_guarded(_ev_node, _ev_snap))
check("⚠️ …but a private device there DOES promote, so the gate has a second thing to ask",
      P.dev_reach_promotes(_ev_roster, _ev_node, "n1", _ev_snap) == {"wg0"},
      P.dev_reach_promotes(_ev_roster, _ev_node, "n1", _ev_snap))
_ev_dr = P.dev_reach_for_node(_ev_roster, _ev_node, "n1", _ev_snap)
check("…and the table it then builds reaches the private device for its owner alone",
      [sorted(a for i in z["users"] for _if, a in _ev_dr["users"][i]) for z in _ev_dr["zones"] if z["to"] == ["10.8.0.2"]]
      == [["10.8.0.2/32"]], _ev_dr)
check("…while everyone else on that promoted interface is not listed at all — the reply names it `open`, so the node passes them",
      _ev_dr.get("open") == ["wg0"] and not any("10.8.0.3" in z["to"] for z in _ev_dr["zones"]), _ev_dr)
# ⚠️ Promoting for a device the panel cannot vouch for buys it nothing — `protect` needs `user_id in users`, so it is not
# a destination even on a guarded interface — and still drops every unvouchable device on that subnet to Nobody.
for _who, _uid in (("an unassigned", None), ("an orphaned", "deleted-owner")):
    _r = json.loads(json.dumps(_ev_roster))
    _r["peers"]["apriv"]["user_id"] = _uid
    check("⚠️ %s private device promotes NOTHING — it cannot be protected, and others would pay for it" % _who,
          P.dev_reach_promotes(_r, _ev_node, "n1", _ev_snap) == set(), P.dev_reach_promotes(_r, _ev_node, "n1", _ev_snap))
_h0 = _psrc.find("_peers_all = [q for q in (roster.get(\"peers\") or {}).values() if isinstance(q, dict)]")
_h1 = _psrc.find("_dreach = dev_reach_for_node(", _h0)
_handler = _psrc[_h0:_h1] if 0 < _h0 < _h1 else ""
check("the networks are computed once for both passes, only when one needs them",
      _handler.count("node_networks(") == 1
      and '_carry = node_networks(roster, nid, snap)["carry"] if (_share_any or (_routes_any and _dr_on)) else {}' in _handler
      and "net_share_for_node(roster, nid, _carry, snap)" in _handler, (_h0, _h1))

print("\n[12] P2 fixes (§11.2)")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
_sk = (N._REACH["status"] or {}).get("skipped") or {}
check("F2: the node says why a listed interface is not in its table — overlap, mesh, not run here",
      _sk.get("wgover") == "overlap" and _sk.get("swg_x") == "mesh" and _sk.get("nope") == "not_here" and "wg0" not in _sk, _sk)
CFG["interfaces"]["awg0"]["conf"] = os.path.join(TMP, "missing.conf")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, {"ifaces": ["awg0"], "users": [], "zones": []}, res())
st = N._REACH["status"]
check("F2: …and a reply none of whose interfaces could be protected still says so, with no table loaded",
      bool(st) and st["ok"] is True and st["ifaces"] == [] and st.get("skipped") == {"awg0": "no_address"} and not K.loads, st)
CFG["interfaces"]["awg0"]["conf"] = _saved
N.reconcile_dev_reach(CFG, None, res())
check("F2: …and no reply ⇒ no status at all (D1)", N._REACH["status"] is None, N._REACH["status"])

fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
drops(5, "wg0", "10.8.0.5", "10.8.0.77")
K.refuse = True; r = res()
N.reconcile_dev_reach(CFG, W2, r)
st = N._REACH["status"]
check("F3: a refused RELOAD says the latest change did not apply, and that the previous table holds",
      bool(st) and st["ok"] is False and st.get("stale") is True and st.get("why") == "nft_failed" and bool(r["errors"]), st)
check("F3: …still naming what that table enforces and what it stopped", bool(st) and st["ifaces"] == PLAN["ifaces"] and st.get("blocked", {}).get("wg0") == 5, st)
drops(3, "wg0", "10.8.0.5", "10.8.0.77")
N.dev_reach_verify(res())
st = N._REACH["status"]
check("F3: …the routing pass keeps counting that table and keeps saying stale", bool(st) and st.get("blocked", {}).get("wg0") == 8 and st.get("stale") is True, st)
K.refuse = False
N.reconcile_dev_reach(CFG, W2, res())
st = N._REACH["status"]
check("F3: …the retry loads, clears stale, and no count is lost or doubled",
      bool(st) and st["ok"] is True and "stale" not in st and st.get("blocked", {}).get("wg0") == 8 and len(K.loads) == 2, (st, len(K.loads)))
fresh(); K = kernel(); K.refuse = True
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
fresh(); K = kernel(); K.refuse = True
N.reconcile_dev_reach(CFG, WIRE, res())
check("R3: a refused FIRST load still says why an interface was left out",
      ((N._REACH["status"] or {}).get("skipped") or {}).get("wgover") == "overlap", N._REACH["status"])
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())           # an earlier process loaded its generation…
fresh(); K.refuse = True                          # …and this one starts over it
N.reconcile_dev_reach(CFG, WIRE, res())
check("R4: a refused load over a table an EARLIER process left enforcing is stale — that table still holds — not open",
      (N._REACH["status"] or {}).get("stale") is True and N._REACH["installed"] is True and T in K.m.tables
      and pk("wg0", "10.8.0.5", "10.8.0.77") == "drop", N._REACH["status"])
# F-P3a (1.8.7 qualification PART 3): what stands by that name is not evidence that anything holds. Measured on a VM: the table
# replaced by another process's empty owner table, a refused reload said stale and the panel said "the previous rules stay in force".
fresh(); K = kernel(); K.leftover(T); K.refuse = True
N.reconcile_dev_reach(CFG, WIRE, res())
st = N._REACH["status"] or {}
check("F-P3a: a refused load over a table by that name that enforces NOTHING (no `pre`) is OPEN — never 'the previous rules hold'",
      st.get("ok") is False and not st.get("stale") and st.get("ifaces") == PLAN["ifaces"] and T in K.m.tables, st)
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
K.flush_rules(T); K.refuse = True                 # `nft flush table`: counters and sets kept, every chain empty
N.reconcile_dev_reach(CFG, W2, res())
st = N._REACH["status"] or {}
check("F-P3a: …and over a table FLUSHED in place (its counters still readable) it is OPEN, every interface named not enforced",
      st.get("ok") is False and not st.get("stale") and st.get("ifaces") == PLAN["ifaces"]
      and pk("wg0", "10.8.0.5", "10.8.0.77") != "drop", st)
K.refuse = False
N.reconcile_dev_reach(CFG, W2, res())
st = N._REACH["status"] or {}
check("F-P3a: …and the first load nft accepts enforces again", st.get("ok") is True and not st.get("stale")
      and pk("wg0", "10.8.0.5", "10.8.0.77") == "drop", st)
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

def _gen_names(k):
    return k.names(T, "sets") | k.names(T, "maps") | k.names(T, "chains")

print("\n[13] swap-safe reloads (§13)")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
check("the first load of a process DECLARES the skeleton and generation a",
      K.loads[-1].startswith(DECLARE) and N._REACH["gen"] == "a" and N._REACH["declared"] is True)
_ncalls, _built, _rp3 = len(K.calls), [], N._reach_plan
N._reach_plan = lambda cfg, wire, devices=None: _built.append(1) or _rp3(cfg, wire, devices)
N.reconcile_dev_reach(CFG, WIRE, res())
N._reach_plan = _rp3
check("the same reply over the same devices builds no plan and calls no nft (the memo)", not _built and len(K.calls) == _ncalls, (_built, K.calls[_ncalls:]))
_c0 = K.m.packet(T, "wg0", "10.8.0.5", "10.8.0.77")[1]
_v0 = K.m.tables[T]["counters"].get(_c0)
N.reconcile_dev_reach(CFG, W2, res())
_s = K.loads[-1]
_left = _gen_names(K)
check("⚠️ a plan change SWAPS: no `delete table`, generation b declared, `sel` repointed to it",
      "delete table" not in _s and _s.startswith("table inet swg_reach {") and N._REACH["gen"] == "b"
      and "flush chain inet swg_reach sel\nadd rule inet swg_reach sel ip daddr vmap @dmap_b" in _s, _s[:200])
check("…and the held generation is gone whole — nothing suffixed _a is left, in an order the kernel accepted",
      not any(n.endswith("_a") for n in _left) and any(n.endswith("_b") for n in _left) and not K.last_refused, sorted(_left))
check("…while it enforces the new plan (10.8.0.10 is boris's now, 10.8.0.5 nobody's)",
      pk("wg0", "10.8.0.9", "10.8.0.10") == "accept" and pk("wg0", "10.8.0.9", "10.8.0.5") == "drop")
_c1 = K.m.packet(T, "wg0", "10.8.0.5", "10.8.0.77")[1]
check("a drop lands in the same counter in every generation, its count kept", _c0 == _c1 and K.m.tables[T]["counters"].get(_c1) == (_v0 or 0) + 2,
      (_c0, _c1, _v0, K.m.tables[T]["counters"]))
N.reconcile_dev_reach(CFG, WIRE, res())
check("…and the next swap alternates back to a", N._REACH["gen"] == "a" and "vmap @dmap_a" in K.loads[-1] and not any(n.endswith("_b") for n in _gen_names(K)))
drops(7, "wg0", "10.8.0.9", "10.9.0.99")
N.reconcile_dev_reach(CFG, {"ifaces": ["wg0"], "users": [], "zones": []}, res())
check("subnets no longer protected leave the guard in the swap",
      sorted((x["lo"], x["hi"]) for x in K.m.tables[T]["sets"]["guard"]["els"]) == [_span("10.8.0.0/24")]
      and "delete element inet swg_reach guard {" in K.loads[-1] and "add element" not in K.loads[-1] and pk("wg0", "10.8.0.9", "10.9.0.99") == "accept")
N.reconcile_dev_reach(CFG, WIRE, res())
check("an interface protected AGAIN reports its count at once (7), not a routing pass later (§11.8, found live)",
      (N._REACH["status"] or {}).get("blocked", {}).get("awg0") == 7, N._REACH["status"])
check("…and its subnets arrive in the guard again",
      sorted((x["lo"], x["hi"]) for x in K.m.tables[T]["sets"]["guard"]["els"]) == sorted(_span(p) for p in PLAN["subnets"]))
CFG["interfaces"]["wg7"] = {"conf": conf("wg7", "10.21.0.1/24")}
_W5 = json.loads(json.dumps(WIRE)); _W5["ifaces"].append("wg7")
_nc = len(K.m.tables[T]["counters"])
N.reconcile_dev_reach(CFG, _W5, res())
_c7 = K.m.packet(T, "wg7", "10.21.0.9", "10.21.0.8")[1]
check("an interface added gets its own counter, the others kept", len(K.m.tables[T]["counters"]) == _nc + 1 and _c7 not in ("gc", _c0) and _c7,
      (K.m.tables[T]["counters"], _c7))
del CFG["interfaces"]["wg7"]
_snap = (N._REACH["gen"], N._REACH["plan"], N._REACH["sig"])
K.refuse = True
N.reconcile_dev_reach(CFG, W2, res())
K.refuse = False
check("a refused swap leaves generation, plan and memo — and says stale",
      (N._REACH["gen"], N._REACH["plan"], N._REACH["sig"]) == _snap and (N._REACH["status"] or {}).get("stale") is True, N._REACH["status"])
N.reconcile_dev_reach(CFG, W2, res())
check("…and the next pass DECLARES rather than retrying that swap (nft 1.0.2 refuses an overlapping guard change a declare loads)",
      K.loads[-1].startswith(DECLARE) and N._REACH["stale"] is None and N._REACH["gen"] == "a", K.loads[-1][:60])
fresh(); K = kernel(nft102=True)
_W6 = {"ifaces": ["wg0"], "users": [], "zones": []}
N.reconcile_dev_reach(CFG, _W6, res())
drops(3, "wg0", "10.8.0.9", "10.8.0.77")
conf("wg0", "10.8.0.1/23")
r6 = res()
N.reconcile_dev_reach(CFG, _W6, r6)
_st6 = dict(N._REACH["status"] or {})
conf("wg0", "10.8.0.1/24")
check("nft 1.0.2: a subnet grown in place (/24 → /23) is refused as a swap and DECLARED in the same pass — enforced, never stale, its count kept",
      _st6.get("ok") is True and not _st6.get("stale") and K.loads[-1].startswith(DECLARE) and not r6["errors"]
      and pk("wg0", "10.8.1.9", "10.8.1.7") == "drop" and _st6.get("blocked", {}).get("wg0") == 3, (_st6, r6))
fresh(); K = kernel(); K.leftover(T)
N.reconcile_dev_reach(CFG, WIRE, res())
check("a table an earlier process left is DECLARED over, never swapped", K.loads[-1].startswith(DECLARE) and "old" not in K.m.tables[T]["counters"])
check("⚠️ the node's own address stays reachable: a map `accept` inside the guard", pk("wg0", "10.8.0.9", "10.8.0.1") == "accept")

print("\n[14] the compact wire (§14 — the only shape, §16 B1)")
check("each source listed once, under its user", bool(DR.get("users")) and sum(len(u) for u in DR["users"]) == len({tuple(s) for u in DR["users"] for s in u}),
      DR.get("users"))
check("…and the old per-zone `from` is never sent", bool(DR) and all("from" not in z for z in DR["zones"]))
_nd = lambda rv: dict(SNAP, net_deps=dict(SNAP["net_deps"], reach=rv))
check("B1: a node reporting reach below 2 — or not as an int — gets nothing to enforce, and its interfaces read unguarded",
      all(P.dev_reach_for_node(R, NREC, "n1", _nd(rv), CARRY) == {} and P.dev_reach_guarded(NREC, _nd(rv)) == {} for rv in (1, 0, "2", True, 2.0)))
check("B1: `dev_reach_for_node` has one shape — no `compact` switch", "compact" not in inspect.signature(P.dev_reach_for_node).parameters)
_bad = json.loads(json.dumps(WIRE)); _bad["zones"][0]["users"] = [99, -1, "0", True] + _bad["zones"][0]["users"]
check("an index out of range, negative, a string or a bool names nobody", plan_of(CFG, _bad)[0] == PLAN)
_narrow = json.loads(json.dumps(WIRE)); _narrow["zones"][0]["users"] = [99]
_pn = plan_of(CFG, _narrow)[0]
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, _narrow, res())
check("…so a zone left with no valid user is reachable by nobody (fail closed)", _pn is not None and _pn != PLAN
      and pk("wg0", "10.8.0.5", "10.9.0.7") == "drop" and pk("wg0", "192.168.50.7", "10.9.0.7") == "drop" and pk("wg0", "10.8.0.9", "10.8.0.9") == "accept")
_v1 = {"ifaces": ["wg0"], "zones": [{"to": ["10.8.0.5"], "from": [["wg0", "10.8.0.9/32"]]}]}
_p1 = plan_of(CFG, _v1)[0]
check("B1: a zone written the old way (`from`, no users) names nobody — fail closed, never read", bool(_p1) and all(not s for s in _p1["sets"]), _p1 and _p1["sets"])
check("B1: the SPA calls a node able to enforce at the same line — reach >= 2 — in the sheet and on the card",
      all("(snap.net_deps || {}).reach >= 2" in _js[n] for n in ("views.js", "screen-nodes.js")))

print("\n[15] §16 — hardening, one counter name, one table grammar")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
_orig_dev = N._reach_devices
N._reach_devices = lambda cfg, names: (_ for _ in ()).throw(RuntimeError("boom"))
r, _raised = res(), False
try:
    N.reconcile_dev_reach(CFG, W2, r)
except Exception:
    _raised = True
N._reach_devices = _orig_dev
st = N._REACH["status"] or {}
check("A1: a fault inside the reconciler is a status, not a raise: ok false, why exception, stale — the loaded table still holds",
      not _raised and st.get("ok") is False and st.get("why") == "exception" and st.get("stale") is True and "boom" in st.get("detail", "")
      and bool(r["errors"]) and r["errors"][0].startswith("device access:"), (_raised, st, r))
N.reconcile_dev_reach(CFG, W2, res())
check("A1: …and the next pass DECLARES afresh and clears it", (N._REACH["status"] or {}).get("ok") is True and K.loads[-1].startswith(DECLARE), N._REACH["status"])
fresh(); K = kernel()
N._reach_devices = lambda cfg, names: (_ for _ in ()).throw(RuntimeError("boom"))
_raised = False
try:
    N.reconcile_dev_reach(CFG, WIRE, res())
except Exception:
    _raised = True
N._reach_devices = _orig_dev
st = N._REACH["status"] or {}
check("A1: a fault before any table: ok false, why exception, NOT stale, naming what it meant to protect",
      not _raised and st.get("ok") is False and st.get("why") == "exception" and not st.get("stale") and "wg0" in st.get("ifaces", []), (_raised, st))
def _fault(cfg, wire):
    N._reach_devices = lambda c, names: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        N.reconcile_dev_reach(cfg, wire, res())
    except Exception:
        pass
    N._reach_devices = _orig_dev
    return N._REACH["status"] or {}
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
K.flush(T)
st = _fault(CFG, W2)
check("A1: the kernel is ASKED, not the process's memory — a fault after the table was flushed says open, never stale",
      st.get("ok") is False and st.get("why") == "exception" and not st.get("stale"), st)
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())           # an earlier process's generation, still enforcing…
fresh()                                           # …under a restarted one
st = _fault(CFG, WIRE)
check("A1: …and a fault over a table an earlier process left says stale — that table still drops",
      st.get("stale") is True and st.get("why") == "exception" and pk("wg0", "10.8.0.5", "10.8.0.77") == "drop", st)
fresh(); K = kernel(); K.leftover(T)
st = _fault(CFG, WIRE)
check("F-P3a: …while a fault over a table by that name that enforces nothing says OPEN, never stale",
      st.get("ok") is False and st.get("why") == "exception" and not st.get("stale"), st)

fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
drops(4, "wg0", "10.8.0.5", "10.8.0.77")
N.dev_reach_verify(res())
K.flush(T)
N.reconcile_dev_reach(CFG, W2, res())
st = N._REACH["status"] or {}
check("A3: a swap refused because the table VANISHED is declared at once — enforced again in this pass, never stale, the counts "
      "read before the flush kept", st.get("ok") is True and not st.get("stale") and T in K.m.tables and K.loads[-1].startswith(DECLARE)
      and pk("wg0", "10.8.0.9", "10.8.0.5") == "drop" and st.get("blocked", {}).get("wg0") == 4, st)
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
K.flush(T); K.refuse = True
N.reconcile_dev_reach(CFG, W2, res())
K.refuse = False
st = N._REACH["status"] or {}
check("A3: …and when the kernel refuses that declare too, it says OPEN — nothing holds — never stale", st.get("ok") is False and not st.get("stale"), st)

_odd = json.loads(json.dumps(NREC)); _odd["ifaces"]["wg0"]["reach"] = "sometimes"; _odd["csqtt"]["csqtt1"]["reach"] = 3
_gd4 = P.dev_reach_guarded(_odd, SNAP)
_dr4 = P.dev_reach_for_node(R, _odd, "n1", SNAP, CARRY)
check("A4: a stored level this panel does not know is Nobody — guarded, and no device on it listed",
      _gd4.get("wg0") == "none" and _gd4.get("csqtt1") == "none" and "wg0" in _dr4.get("ifaces", [])
      and not any(ipaddress.ip_address(a) in ipaddress.ip_network("10.8.0.0/24") for z in _dr4.get("zones", []) for a in z["to"]), (_gd4, _dr4.get("zones")))
_meta4 = P.apply_iface_meta({"ifaces": {"wg0": {"reach": "sometimes"}, "wgE": {"reach": "everyone"}}}, {"wg0": {}, "wgE": {}, "wgU": {}})
_mi4 = P._missing_ifaces({"ifaces": {"wg0": {"reach": "sometimes", "_lastcfg": {"subnet": "10.8.0.0/24"}}}}, {"interfaces": {}}, None)
check("A4: …and every place the panel publishes a level says Nobody for it — the chip and sheets agree with the table, and a save "
      "posts back a level the door accepts",
      getattr(P, "reach_level", None) is not None and _meta4["wg0"]["reach"] == "none" and _meta4["wgE"]["reach"] == "everyone"
      and _meta4["wgU"]["reach"] == "user" and _mi4.get("wg0", {}).get("reach") == "none"
      and '"reach": reach_level(ov.get("reach"))' in _psrc, (_meta4, _mi4))

fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
drops(4, "wg0", "10.8.0.9", "10.9.0.99")
_noawg = json.loads(json.dumps(WIRE)); _noawg["ifaces"].remove("awg0")
N.reconcile_dev_reach(CFG, _noawg, res())
N.dev_reach_verify(res())
K.flush(T)
N.dev_reach_verify(res())
N.reconcile_dev_reach(CFG, WIRE, res())
check("B2: an interface's count survives a declare it was not part of (4) — counters are the interface's, by name",
      (N._REACH["status"] or {}).get("blocked", {}).get("awg0") == 4, N._REACH["status"])

fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WIRE, res())
_sk0 = dict((N._REACH["status"] or {}).get("skipped") or {})
_W4 = json.loads(json.dumps(W2)); _W4["ifaces"].append("ghost9")
K.refuse = True
N.reconcile_dev_reach(CFG, _W4, res())
K.refuse = False
check("B3: a refused load reports why the table IN FORCE left interfaces out — not the refused reply's reasons",
      (N._REACH["status"] or {}).get("skipped") == _sk0 and "ghost9" not in ((N._REACH["status"] or {}).get("skipped") or {}), (_sk0, N._REACH["status"]))

WN = json.loads(json.dumps(WIRE))
WN["users"][0] += [["wg0", "192.168.50.128/25"], ["wg0", "192.168.50.7/32"], ["awg0", "192.168.60.0/24"], ["awg0", "192.168.60.0/25"]]
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, WN, res())
check("C2: nested and overlapping network sources on one interface load — collapsed first (one prefix inside another refuses the "
      "whole load, measured on 1.0.9 and 1.0.2)", (N._REACH["status"] or {}).get("ok") is True and not K.last_refused, (N._REACH["status"], K.calls[-1:]))
check("C2: a network source reaches the zone's device only arriving on its own interface",
      pk("wg0", "192.168.50.200", "10.9.0.7") == "accept" and pk("awg0", "192.168.50.200", "10.9.0.7") == "drop"
      and pk("awg0", "192.168.60.9", "10.9.0.7") == "accept" and pk("wg0", "192.168.60.9", "10.9.0.7") == "drop")
check("C2: …and a single-address source, the same", pk("wg0", "10.8.0.5", "10.9.0.7") == "accept" and pk("awg0", "10.8.0.5", "10.9.0.7") == "drop")

print("\n[16] PRIVATE — a device its owner keeps to themselves (operator, 2026-09-16)")
# Its own roster, so nothing here perturbs the sections above. alice and bob share a group; carol shares none.
_PU = {"alice": {"name": "Alice"}, "bob": {"name": "Bob"}, "carol": {"name": "Carol"}}
_pp = lambda pid, uid, ip, ifn="wg0", **k: (pid, dict({"id": pid, "user_id": uid, "pubkey": pid.ljust(43, "x") + "=",
        "targets": [{"node": "n1", "iface": ifn, "ip": ip, "type": "wg"}]}, **k))
def _proster(**flags):
    return {"users": _PU, "groups": {"fam": {"name": "Family", "users": ["alice", "bob"]}},
            "peers": dict([_pp("a1", "alice", "10.8.0.1"), _pp("a2", "alice", "10.8.0.2", **flags),
                           _pp("b1", "bob", "10.8.0.3"), _pp("c1", "carol", "10.8.0.4")])}
def _zone_for(dr, addr):
    """The set of user indices allowed to reach one address, resolved to the users' own source lists."""
    for z in dr.get("zones") or []:
        if addr in z["to"]:
            return {tuple(map(tuple, dr["users"][i])) for i in z["users"]}
    return None
_ADDRS = {"alice": ["10.8.0.1", "10.8.0.2"], "bob": ["10.8.0.3"], "carol": ["10.8.0.4"]}
_who = lambda uid: tuple(("wg0", a + "/32") for a in _ADDRS[uid])   # that user's whole source list, as the wire carries it

_NR_USER = {"id": "n1", "name": "home", "ifaces": {"wg0": {"reach": "user"}}}
_SN = {"interfaces": {"wg0": {"meta": {"subnet": "10.8.0.0/24"}}},
       "net_deps": {"panel": "198.51.100.10", "resolvers": [], "resolvers_known": True, "reach": 2}}
_dr = P.dev_reach_for_node(_proster(private=True), _NR_USER, "n1", _SN)
check("a private device is a destination, like any device on a guarded interface", _zone_for(_dr, "10.8.0.2") is not None, _dr)
check("⚠️ only its OWNER's devices reach it — a group mate does NOT, though the interface says 'user + groups'",
      _zone_for(_dr, "10.8.0.2") == {_who("alice")}, _zone_for(_dr, "10.8.0.2"))
check("…while a NON-private device of the same user still lets the group mate in",
      _who("bob") in (_zone_for(_dr, "10.8.0.1") or set()), _zone_for(_dr, "10.8.0.1"))
check("and someone who shares no group reaches neither", all(_who("carol") not in (_zone_for(_dr, a) or set())
      for a in ("10.8.0.1", "10.8.0.2")))

# ⚠️ THE EVERYONE CASE: the node builds a table only for the interfaces it is sent, so private must promote its own.
_NR_EVERY = {"id": "n1", "name": "home", "ifaces": {"wg0": {"reach": "everyone"}}}
check("without a private device an Everyone interface is sent nothing at all — unchanged",
      P.dev_reach_for_node(_proster(), _NR_EVERY, "n1", _SN) == {})
_de = P.dev_reach_for_node(_proster(private=True), _NR_EVERY, "n1", _SN)
check("⚠️ a private device PROMOTES its Everyone interface, or nothing would enforce it", _de.get("ifaces") == ["wg0"], _de)
check("⚠️ and only its owner reaches it there, regardless of the interface saying Everyone",
      _zone_for(_de, "10.8.0.2") == {_who("alice")}, _zone_for(_de, "10.8.0.2"))
check("⚠️ every OTHER device on that interface is left to Everyone — only the private one is a destination, and the reply says `open`",
      _de.get("open") == ["wg0"] and {a for z in _de["zones"] for a in z["to"]} == {"10.8.0.2"}, _de)
# ⚠️ WHAT PROMOTION COSTS, PINNED — NOTHING. The first shape guarded the whole subnet and relisted every device the panel could
# vouch for in an all-comers zone, so anything it could not — an unassigned device, a host on the node's LAN, a keyless client,
# a cascade arrival — lost Everyone the moment one device was marked private: measured on swgt (qualification 1.8.7 §N10), an
# unassigned device could no longer open a connection to its neighbours and a LAN host reached nobody on the interface.
_rp = _proster(private=True)
_rp["peers"]["x1"] = {"id": "x1", "user_id": None, "pubkey": "x1".ljust(43, "x") + "=",
                      "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.9", "type": "wg"}]}
_dx = P.dev_reach_for_node(_rp, _NR_EVERY, "n1", _SN)
_listed = {a for z in _dx["zones"] for a in z["to"]}
check("an unassigned device on a promoted interface is not listed — the node's `open` rest is what reaches it, as Everyone did",
      "10.8.0.9" not in _listed and _dx.get("open") == ["wg0"], (sorted(_listed), _dx.get("open")))
check("…and the private device is still guarded for its owner alone", _zone_for(_dx, "10.8.0.2") == {_who("alice")}, _zone_for(_dx, "10.8.0.2"))
check("…and a node with no private device on an Everyone interface gets no `open` key — the reply it had",
      "open" not in P.dev_reach_for_node(_proster(private=True), {"id": "n1", "name": "home", "ifaces": {"wg0": {}}}, "n1", _SN))

# The node's half, by PACKET: an `open` interface judges its listed devices and passes the rest.
fresh(); K = kernel()
_OW = {"ifaces": ["wg0"], "open": ["wg0"], "users": [[["wg0", "10.8.0.5/32"]], [["wg0", "10.8.0.9/32"]]],
       "zones": [{"to": ["10.8.0.7"], "users": [0]}]}
N.reconcile_dev_reach(CFG, _OW, res())
check("⚠️ open: the private device is reached by its owner, not by a stranger on the interface",
      pk("wg0", "10.8.0.5", "10.8.0.7") == "accept" and pk("wg0", "10.8.0.9", "10.8.0.7") == "drop",
      (pk("wg0", "10.8.0.5", "10.8.0.7"), pk("wg0", "10.8.0.9", "10.8.0.7")))
check("⚠️ open: every other address keeps Everyone — a listed stranger, an unlisted device, a host on the node's LAN, a cascade arrival",
      all(pk(i, sa, "10.8.0.8") == "accept" for i, sa in (("wg0", "10.8.0.9"), ("wg0", "10.8.0.66"), ("eth1", "192.168.1.5"), ("swg_x", "10.99.0.3"))),
      [pk(i, sa, "10.8.0.8") for i, sa in (("wg0", "10.8.0.9"), ("wg0", "10.8.0.66"), ("eth1", "192.168.1.5"), ("swg_x", "10.99.0.3"))])
check("…but not the private device, from the LAN or over the mesh either",
      pk("eth1", "192.168.1.5", "10.8.0.7") == "drop" and pk("swg_x", "10.99.0.3", "10.8.0.7") == "drop")
fresh(); K = kernel()
_OW2 = json.loads(json.dumps(_OW)); _OW2["zones"].append({"to": ["10.8.0.7"], "users": [1]})
N.reconcile_dev_reach(CFG, _OW2, res())
check("⚠️ open: an address two zones claim is Nobody — never passed because the rest is open",
      pk("wg0", "10.8.0.5", "10.8.0.7") == "drop" and pk("wg0", "10.8.0.9", "10.8.0.7") == "drop" and pk("wg0", "10.8.0.9", "10.8.0.8") == "accept")
fresh(); K = kernel()
N.reconcile_dev_reach(CFG, {k: v for k, v in _OW.items() if k != "open"}, res())
check("control — the same reply WITHOUT `open` is a guarded interface: the unlisted address is Nobody",
      pk("wg0", "10.8.0.9", "10.8.0.8") == "drop" and pk("wg0", "10.8.0.5", "10.8.0.7") == "accept")
# private is about who reaches IT — it never stops the device reaching out
check("a private device is still a SOURCE: private limits who reaches it, not what it reaches",
      any(("wg0", "10.8.0.2/32") in {tuple(x) for x in u} for u in _dx["users"]), _dx["users"])

_dblocked = P.dev_reach_for_node(_proster(private=True, disabled=True), _NR_EVERY, "n1", _SN)
check("a BLOCKED private device promotes nothing — it is off the node, and the interface stays as it was", _dblocked == {}, _dblocked)
check("a node that cannot enforce is still sent nothing, private or not",
      P.dev_reach_for_node(_proster(private=True), _NR_EVERY, "n1",
                           dict(_SN, net_deps=dict(_SN["net_deps"], reach=1))) == {})

# the NETWORKS half — one choke point, and it outranks every share
_nowv = int(__import__("time").time())
_grp = {"fam": {"name": "Family", "users": ["alice", "bob"]}}
_shared = {"id": "gw", "user_id": "alice", "private": True,
           "share": {"users": {"bob": 0, "carol": 0}, "groups": {"fam": 0}}}
check("⚠️ private outranks a named grant AND a group grant — the owner alone",
      P.share_grants(_shared, _PU, _nowv, _grp) == {"alice": 0}, P.share_grants(_shared, _PU, _nowv, _grp))
check("⚠️ …and outranks having no share at all, which would otherwise mean everyone on the node",
      P.share_grants({"id": "g2", "user_id": "alice", "private": True}, _PU, _nowv, _grp) == {"alice": 0})
check("a private device whose owner is gone grants NOBODY — fail closed, never open",
      P.share_grants({"id": "g3", "user_id": "ghost", "private": True}, _PU, _nowv, _grp) == {})
check("without the flag, sharing behaves exactly as before",
      P.share_grants(dict(_shared, private=False), _PU, _nowv, _grp) == {"alice": 0, "bob": 0, "carol": 0})

# ⚠️ TWO PRIVATE DEVICES, TWO OWNERS — the shape a real fleet has on day one, and the one the fixture above cannot
# express. Zones are keyed by their allowed set, so `("own", uid)` losing its uid collapses every private device into ONE
# zone: the second owner's device inherits the first owner's sources and becomes reachable by the wrong person, silently.
_two = _proster(private=True)
_two["peers"]["b2"] = dict(_pp("b2", "bob", "10.8.0.5", private=True)[1])
_ADDRS2 = dict(_ADDRS, bob=["10.8.0.3", "10.8.0.5"])
_who2 = lambda uid: tuple(("wg0", a + "/32") for a in _ADDRS2[uid])
_dt = P.dev_reach_for_node(_two, _NR_USER, "n1", _SN)
check("⚠️ two private devices of DIFFERENT owners do not share a zone — each is its own owner's alone",
      _zone_for(_dt, "10.8.0.2") == {_who2("alice")} and _zone_for(_dt, "10.8.0.5") == {_who2("bob")},
      (_zone_for(_dt, "10.8.0.2"), _zone_for(_dt, "10.8.0.5")))
check("…so neither owner reaches the other's private device", _who2("bob") not in (_zone_for(_dt, "10.8.0.2") or set())
      and _who2("alice") not in (_zone_for(_dt, "10.8.0.5") or set()))

# ⚠️ THE KEYLESS PATH (WDTT/csqtt), which section [16]'s wg-only fixture never executed: a private keyless device takes a
# DIFFERENT branch to become a destination (`keyless_sources`), and the promise has to hold on it too.
_kr = {"users": {"anna": {"name": "Anna"}, "erin": {"name": "Erin"}},
       "groups": {"fam": {"name": "Family", "users": ["anna", "erin"]}},
       "peers": {"anna-wdtt": {"id": "anna-wdtt", "user_id": "anna", "wdtt_password": "pwA", "private": True,
                               "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
                 "anna-phone": {"id": "anna-phone", "user_id": "anna", "pubkey": PK("A"),
                                "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5", "type": "wg"}]},
                 "erin-phone": {"id": "erin-phone", "user_id": "erin", "pubkey": PK("E"),
                                "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.8", "type": "wg"}]}}}
_kd = P.dev_reach_for_node(_kr, NREC, "n1", SNAP)
_kz = _zone_for(_kd, "10.77.0.2")
check("⚠️ a private KEYLESS device is a destination, and only its owner's devices reach it",
      _kz is not None and all("10.8.0.8/32" not in [a for _i, a in src] for src in (_kz or set())), (_kz, _kd.get("ifaces")))
check("…and its group mate is refused there too, though the interface allows user + groups",
      _kz == {tuple(sorted((("wdtt1", "10.77.0.2/32"), ("wg0", "10.8.0.5/32"))))} or
      all(any(a == "10.8.0.5/32" for _i, a in src) for src in (_kz or set())), _kz)

# ⚠️ A PRIVATE DEVICE THAT IS ITSELF A PROVIDER. "Private limits who reaches it, not what it reaches", so the networks it
# carries stay in ITS OWN source list — the `carry` branch was never exercised with a private peer, and dropping it there
# would quietly cut the owner off from the network behind their own router.
_pr = {"users": {"anna": {"name": "Anna"}},
       "peers": {"anna-router": {"id": "anna-router", "user_id": "anna", "pubkey": PK("R"), "private": True,
                                 "routes": ["192.168.50.0/24"],
                                 "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.6", "type": "wg"}]},
                 "anna-phone": {"id": "anna-phone", "user_id": "anna", "pubkey": PK("A"),
                                "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.5", "type": "wg"}]}}}
_pc = P.node_networks(_pr, "n1", SNAP)["carry"]
_pd = P.dev_reach_for_node(_pr, NREC, "n1", SNAP, _pc)
check("⚠️ a private provider still carries its networks as a SOURCE — private limits who reaches it, not what it reaches",
      any(("wg0", "192.168.50.0/24") in src for src in (_zone_for(_pd, "10.8.0.6") or set())),
      (_pc, _zone_for(_pd, "10.8.0.6")))

# ⚠️ peer_set PRESERVING THE FLAG was asserted in a comment and in a commit message and pinned nowhere: an unrelated save
# that does not name `private` must not clear it, because that direction silently OPENS a device.
_ps = {"users": {"alice": {"name": "Alice"}},
       "peers": {"a1": {"id": "a1", "user_id": "alice", "pubkey": PK("A"), "private": True, "title": "before",
                        "targets": [{"node": "n1", "iface": "wg0", "ip": "10.8.0.1", "type": "wg"}]}}}
P.peer_set(_ps, "a1", {"title": "after"}, int(__import__("time").time()))
check("⚠️ a save that only changes the title leaves the device private", _ps["peers"]["a1"].get("private") is True,
      _ps["peers"]["a1"])
check("…and the field it DID name is written", _ps["peers"]["a1"].get("title") == "after", _ps["peers"]["a1"])

# ⚠️ THE PANEL HAS TO SAY SO. Promotion changes the level IN FORCE while the level the operator SET stays "everyone", so
# every screen that read the setting went on calling a guarded interface open — the green chip over a guarded subnet, a
# refused reload there unreportable, and no way to find the device that caused it. The browser must not re-derive this
# (two answers drift); the panel publishes it per node, and this proves the wire actually carries it.
json.dump({"version": P.ROSTER_VERSION, "users": {"alice": {"name": "Alice"}},
           "peers": {"apv": {"id": "apv", "user_id": "alice", "pubkey": PK("P"), "private": True,
                             "targets": [{"node": "n1", "iface": "wgE", "ip": "10.10.0.3", "type": "wg"}]}}},
          open(roster_path, "w"))
P.Handler.deps = deps          # nodes_view reads the live deps, as the server sets them per request
def _nview():
    """The node record as the SPA receives it — /api/nodes and /api/state share nodes_view (NOT /api/fleet, which
    returns a minimal projection: id, name, color, transport, stats_file)."""
    try:
        _c, _b = P.api("GET", "/api/nodes", {}, None, deps)
    except Exception as _e:
        return 599, {"exception": repr(_e)}
    return _c, next((x for x in (((_b or {}).get("data") or {}).get("nodes") or []) if x.get("id") == "n1"), {})
_fc, _fn = _nview()
check("⚠️ the node view publishes the PROMOTED interfaces, so a screen can tell guarded from open",
      _fc == 200 and _fn.get("reach_promoted") == ["wgE"], (_fc, _fn.get("reach_promoted")))
json.dump({"version": P.ROSTER_VERSION, "users": {"alice": {"name": "Alice"}},
           "peers": {"apv": {"id": "apv", "user_id": "alice", "pubkey": PK("P"),
                             "targets": [{"node": "n1", "iface": "wgE", "ip": "10.10.0.3", "type": "wg"}]}}},
          open(roster_path, "w"))
_fc2, _fn2 = _nview()
check("…and says nothing is promoted when no device is private — an Everyone interface stays Everyone",
      _fc2 == 200 and _fn2.get("reach_promoted") == [], (_fc2, _fn2.get("reach_promoted")))

# ⚠️ MULTI-NODE. Promotion is per node, and the scan filters targets by `node == nid` — with a single-node fixture that
# filter can be deleted and everything stays green. The failure it guards is the worst direction there is: a private
# device on n2 makes n1 guard a subnet that has no private device on it, and every unvouchable device there loses reach.
_mn_node2 = {"id": "n2", "name": "away", "ifaces": {"wgE": {"reach": "everyone"}}}
_mn = {"users": {"alice": {"name": "Alice"}},
       "peers": {"apv": {"id": "apv", "user_id": "alice", "pubkey": PK("P"), "private": True,
                         "targets": [{"node": "n2", "iface": "wgE", "ip": "10.10.0.3", "type": "wg"}]}}}
check("⚠️ a private device on ANOTHER node promotes nothing here — promotion is per node",
      P.dev_reach_promotes(_mn, NREC, "n1", SNAP) == set(), P.dev_reach_promotes(_mn, NREC, "n1", SNAP))
check("…and does promote on the node it is actually deployed to",
      P.dev_reach_promotes(_mn, _mn_node2, "n2", SNAP) == {"wgE"}, P.dev_reach_promotes(_mn, _mn_node2, "n2", SNAP))

# ⚠️ ALL FOUR TERMS of the off-the-node test, not just the peer's own `disabled`: a blocked USER's device and an EXPIRED
# one are dropped from the node's desired set too, so neither is on the wire and neither can promote anything.
_TOMORROW, _YESTERDAY = int(__import__("time").time()) + 86400, int(__import__("time").time()) - 86400
for _lbl, _pmut, _umut in (("the peer itself is blocked", {"disabled": True}, {}),
                           ("its OWNER is blocked", {}, {"disabled": True}),
                           ("the peer has expired", {"expiry": _YESTERDAY}, {}),
                           ("its OWNER has expired", {}, {"expiry": _YESTERDAY})):
    _off = {"users": {"alice": dict({"name": "Alice"}, **_umut)},
            "peers": {"apv": dict({"id": "apv", "user_id": "alice", "pubkey": PK("P"), "private": True,
                                   "targets": [{"node": "n1", "iface": "wgE", "ip": "10.10.0.3", "type": "wg"}]}, **_pmut)}}
    check("⚠️ nothing is promoted when %s — it is off the node" % _lbl,
          P.dev_reach_promotes(_off, NREC, "n1", SNAP) == set(), P.dev_reach_promotes(_off, NREC, "n1", SNAP))
_live = {"users": {"alice": {"name": "Alice", "expiry": _TOMORROW}},
         "peers": {"apv": {"id": "apv", "user_id": "alice", "pubkey": PK("P"), "private": True, "expiry": _TOMORROW,
                           "targets": [{"node": "n1", "iface": "wgE", "ip": "10.10.0.3", "type": "wg"}]}}}
check("…while a date still in the future promotes normally — the guard is expiry, not merely having a date",
      P.dev_reach_promotes(_live, NREC, "n1", SNAP) == {"wgE"}, P.dev_reach_promotes(_live, NREC, "n1", SNAP))

shutil.rmtree(TMP2, ignore_errors=True)
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
