#!/usr/bin/env python3
"""Self-test for EXIT BACKUPS (1.8.12 item 18; docs/RELEASE-1.8.12-PLAN.md "Exit failover" → Design).

An exit may name backup exits on its node, in order. While its device is not up (dead, down, absent), the node moves the
exit's OWN table to the first backup that is up, so every user of the exit — a whole interface, a rule, arrivals, the P2P
route — follows with no change of its own. The list is flat (never followed into a backup's own list): A → [B] beside
B → [A] is allowed, which is the request (WG and MASQUE WARP backing each other). No backup up → today: the route is
withheld and the exit's own kill switch decides. tests/exit_failover_selftest.py stays the dead → direct JUDGE's gate.

Node (the real reconcile_cascade, `run()` answered by a fake kernel that models `ip route replace` as the kernel does —
it REPLACES a table's default; no network, no root):
  [1] owner up: its route, and the SNAT for every chain member up front · settles
  [2] owner dead → the table defaults via the first live backup, in place (no rule deleted, no flush, no `del` before
      the `replace`, no iptables in the move) · the report keeps the owner's device · `exit_via` names the backup · settles
  [3] the first backup dead too → the next · the list's order decides
  [4] no backup up → kill switch off: no default (direct); on: the `prohibit` only · `exit_via` says "" for it
  [5] the owner back → the table returns to it in place, `exit_via` empties
  [6] no `xbackup` → today exactly (a dead owner withholds its route; `xbackup: []` = absent)
  [7] `_xbackup_take` refuses malformed entries (a device name reaches argv and nft text)
  [8] `_devexit_sig` moves on a backup's state, and is unchanged without `xbackup`
  [9] a SOCKS backup gets its DNS redirect while it carries, not before
  [10] a dial-in backup's private cut is in the table whichever member carries: a move never rebuilds the band
  [11] the P2P route: its table follows, and its `oifname !=` allows every member (route and per-interface groups)
  [12] a rule-scoped exit's smart route follows too
Panel:
  [13] `_validate_exits`: stored in order; mutual allowed; self / twice / adopted (either end) / not-a-list refused; a
       deleted member pruned; a disabled one kept; a request without the field keeps the stored list; `[]` clears
  [14] cascade_plan: `xbackup` per planned exit table, members through resolve_exit (a disabled one left out); no key at
       all without backups; nothing for an exit nothing uses
  [15] failover nodes: exit_refs takes the members; the mirror copies the list and holds the members' copies
  [16] the node's Issues line names the backup carrying; with none up, today's sentence
  [17] exits_live puts `via` on the row; `exit_via` is shape-checked in the snapshot

Run: python3 tests/exit_backup_selftest.py   (0 = pass)
     SWG_XBK_BASE=<commit> … also compares, for plans WITHOUT backups, the node's every command and report and the panel's
     plan against that commit's programs (the byte-identical claim; needs git and the commit).
     --perturb-noswap · --perturb-order · --perturb-anystate · --perturb-delfirst · --perturb-snat · --perturb-s5x ·
     --perturb-cut · --perturb-p2p · --perturb-p2proute · --perturb-carried · --perturb-sig · --perturb-report · --perturb-smart · --perturb-arr · --perturb-self ·
     --perturb-prune · --perturb-keep · --perturb-resolve · --perturb-refs · --perturb-issue · --perturb-live ·
     --perturb-follow — each plants one regression (PLANTS below) and must go RED.
"""
import copy, importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)

# (program, anchor, replacement) — each must match exactly once, or the run would FALSE-PASS
PLANTS = {
    "--perturb-noswap": ("N", "                _via[T], _xvia[oid] = md, mid", "                _xvia[oid] = mid"),
    "--perturb-order": ("N", "        for mid, md in ms:\n            if md != own[\"dev\"]",
                        "        for mid, md in reversed(ms):\n            if md != own[\"dev\"]"),
    "--perturb-anystate": ("N", "if md != own[\"dev\"] and not _dev_is_ether(md) and _devexit_state(md) == \"up\":",
                           "if md != own[\"dev\"] and not _dev_is_ether(md):"),
    "--perturb-delfirst": ("N", "            elif (m[1], m[2]) not in _took:", "            elif True:"),
    "--perturb-snat": ("N", "devexit=devexit + [dict(e, dev=md, egress_ip=\"\", gw=\"\") for e in devexit",
                       "devexit=devexit + [dict(e, dev=md, egress_ip=\"\", gw=\"\") for e in ()"),
    "--perturb-s5x": ("N", "    _s5x_rules(_dxs if _via else devexit, nets, res)", "    _s5x_rules(devexit, nets, res)"),
    "--perturb-cut": ("N", "    _cut = _dialin_cut(fwd + smart_exit + arr_exit + _xcut,", "    _cut = _dialin_cut(fwd + smart_exit + arr_exit,"),
    "--perturb-p2p": ("N", "        take(\"r%d\" % T, e.get(\"subnets\"), T | P2P_BIT, [e[\"via_iface\"]] + list((xdevs or {}).get(T) or ()), T)",
                      "        take(\"r%d\" % T, e.get(\"subnets\"), T | P2P_BIT, [e[\"via_iface\"]], T)"),
    "--perturb-p2proute": ("N", "else ([ent[\"via_iface\"]] + list((xdevs or {}).get(int(ent[\"table\"])) or ())",
                           "else ([ent[\"via_iface\"]] + list(())"),
    "--perturb-carried": ("N", "or (_devexit_state(d) != \"up\" and d not in _EXIT_VIA[\"carried\"])}) if _r else []",
                          "or _devexit_state(d) != \"up\"}) if _r else []"),
    "--perturb-sig": ("N", "        + ([[\"xbk\"] + [(d, _devexit_state(d)) for d in _xd]] if _xd else [])", "        + []"),
    "--perturb-report": ("N", "    _EXIT_VIA[\"m\"] = _xvia", "    _EXIT_VIA[\"m\"] = {}"),
    "--perturb-smart": ("N", "    smart_exit = [dict(e, via_iface=_xd(e.get(\"table\"), e.get(\"via_iface\"))) for e in smart_exit] if _via else smart_exit",
                        "    smart_exit = smart_exit"),
    "--perturb-arr": ("N", "        _pd = _xd(_pe[\"table\"], _pe[\"via_iface\"])", "        _pd = _pe[\"via_iface\"]"),
    "--perturb-self": ("P", "            if bid == x[\"id\"]:", "            if False:"),
    "--perturb-prune": ("P", "            if bid not in byid:\n                continue",
                        "            if bid not in byid:\n                out.append(bid)\n                continue"),
    "--perturb-keep": ("P", "        elif isinstance(_old.get(\"backup\"), list):", "        elif False:"),
    "--perturb-resolve": ("P", "                _r = resolve_exit(nodes, snaps, nid, bid)\n",
                          "                _r = resolve_exit(nodes, snaps, nid, bid) or (\"wgx-\" + bid,)\n"),
    "--perturb-refs": ("P", "    out |= {b for i in list(out) for b in exit_backups(_xs.get(i))}", "    out |= set()"),
    "--perturb-issue": ("P", "        if _vid:\n            _vx = next(", "        if False:\n            _vx = next("),
    "--perturb-live": ("P", "            out[str(xi)] = dict(out[str(xi)], via=xv)", "            pass"),
    "--perturb-follow": ("P", "                  \"backup\")", "                  )"),
}
PLANT = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def _load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod


def _planted(path, which):
    if not PLANT or PLANTS[PLANT][0] != which:
        return path
    _, a, b = PLANTS[PLANT]
    src = open(path, encoding="utf-8").read()
    assert src.count(a) == 1, "perturbation anchor (%s) missing or not unique — this run would FALSE-PASS" % PLANT
    out = os.path.join(tempfile.mkdtemp(prefix="xbk-plant-"), os.path.basename(path) + ".py")
    open(out, "w", encoding="utf-8").write(src.replace(a, b, 1))
    return out


N = _load(_planted(NODED, "N"), "swgnoded_xbk")
P = _load(_planted(PANEL, "P"), "swgpanel_xbk")

# Hermetic: the host's own routes are not this test's subject (as tests/devexit_killswitch_selftest.py does it).
_ROUTE0 = os.path.join(tempfile.mkdtemp(prefix="xbk-route-"), "route")
open(_ROUTE0, "w").write("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n")


def _hermetic(mod):
    clr = mod._cascade_local_routes
    mod._cascade_local_routes = lambda cfg, _proc=None: clr(cfg, _proc=_ROUTE0)
    mod._detect_wan = lambda *a, **k: "eth0"
    mod._sysctl_ensure = lambda *a, **k: 2
    mod._rp_filter_val = lambda *a, **k: 2


_hermetic(N)


class _R:
    def __init__(s, out="", rc=0):
        s.stdout, s.stderr, s.returncode = out, "", rc


class Kernel:
    """Enough `ip` and `iptables -t nat` to settle a pass: `ip route replace` REPLACES the table's default (metric 0) as the
    kernel does — a move is one command — and a route through a device that is not up is refused and not created."""
    def __init__(k, state):
        k.state, k.rules, k.tables, k.nat, k.log = state, [], {}, [], []

    def up(k, d):
        return k.state.get(d, "absent") in ("up", "dead")          # a dead tunnel's device is UP (the judge says dead)

    def __call__(k, argv, **kw):
        a = [str(x) for x in (argv if isinstance(argv, (list, tuple)) else [argv])]
        k.log.append(" ".join(a))
        if a[:2] == ["sh", "-c"] and a[2].startswith("iptables -t nat -D POSTROUTING"):
            ln = a[2][len("iptables -t nat "):].replace("-D POSTROUTING", "-A POSTROUTING", 1)
            if ln in k.nat:
                k.nat.remove(ln)
            return _R()
        if a[:5] == ["iptables", "-t", "nat", "-S", "POSTROUTING"]:
            return _R("\n".join(["-P POSTROUTING ACCEPT"] + k.nat) + "\n")
        if a[:5] == ["iptables", "-t", "nat", "-I", "POSTROUTING"]:
            k.nat.insert(0, "-A POSTROUTING " + " ".join(a[5:]))
            return _R()
        if a[:3] == ["ip", "rule", "show"]:
            out = []
            for pri, kind, x, T in k.rules:
                out.append("%d:\tfrom %s lookup %d" % (pri, x, T) if kind == "from"
                           else "%d:\tfrom all fwmark %#x lookup %d" % (pri, x, T))
            return _R("\n".join(out) + "\n")
        if a[:3] == ["ip", "rule", "add"]:
            pri = int(a[a.index("priority") + 1]); T = int(a[a.index("lookup") + 1])
            if "fwmark" in a:
                k.rules.append((pri, "fwmark", int(a[a.index("fwmark") + 1], 0), T))
            elif "from" in a:
                k.rules.append((pri, "from", a[a.index("from") + 1], T))
            return _R()
        if a[:3] == ["ip", "rule", "del"]:
            pref = int(a[a.index("pref") + 1])
            hit = [r for r in k.rules if r[0] == pref]
            if not hit:
                return _R("", 2)
            k.rules.remove(hit[0])
            return _R()
        if a[:3] == ["ip", "route", "show"] and "table" in a:
            return _R("".join(r + "\n" for r in k.tables.get(a[a.index("table") + 1], [])))
        if a[:3] == ["ip", "route", "flush"] and "table" in a:
            k.tables.pop(a[a.index("table") + 1], None)
            return _R()
        if a[:3] == ["ip", "route", "replace"] and "table" in a:
            T = a[a.index("table") + 1]; rt = k.tables.setdefault(T, [])
            body = a[3:a.index("table")]
            if body[0] == "prohibit":
                line = " ".join(body)
                if line not in rt:
                    rt.append(line)
                return _R()
            dst = body[0]
            dev = body[body.index("dev") + 1] if "dev" in body else ""
            if dev and not k.up(dev):
                return _R("", 2)                                      # ENETDOWN / ENODEV: the route is NOT created
            via = body[body.index("via") + 1] if "via" in body else ""
            rt[:] = [r for r in rt if not (r.split()[0] == dst and "metric" not in r)]
            rt.append("%s %sdev %s scope link" % (dst, ("via %s " % via) if via else "", dev))
            return _R()
        if a[:3] == ["ip", "route", "del"] and "table" in a:
            T, dev = a[a.index("table") + 1], a[a.index("dev") + 1]
            k.tables[T] = [r for r in k.tables.get(T, []) if not (r.split()[0] == a[3] and " dev %s " % dev in " " + r + " ")]
            return _R()
        return _R()


S, T, KS_GUARD = "10.17.0.0/24", 7003, "prohibit default metric %d" % N.DEVEXIT_GUARD_METRIC
A, B, C = "aaaa0001", "bbbb0002", "cccc0003"
DA, DB, DC = "wgx-" + A, "wgx-" + B, "wgx-" + C


def plan(ks=False, members=((B, DB), (C, DC)), xb=True, extra=None):
    p = {"devexit": [{"subnet": S, "dev": DA, "table": T, "killswitch": ks, "egress_ip": "", "gw": ""}]}
    if xb is True:
        p["xbackup"] = [{"table": T, "id": A, "b": [{"id": i, "dev": d} for i, d in members]}]
    elif xb is not None:
        p["xbackup"] = xb
    p.update(extra or {})
    return p


def set_state(mod, kern, state):
    """`state` {device: up|dead|down|absent}: a dead device is UP with the judge's verdict on it."""
    kern.state = state
    mod._dev_link_state = lambda d: ("up" if state.get(d) in ("up", "dead") else state.get(d, "absent"))
    mod._EXIT_HEALTH.clear()
    mod._EXIT_HEALTH.update({d: {"dead": True, "fails": 3, "fail_since": 0, "ok_since": None, "since": 0, "why": "x"}
                             for d, s in state.items() if s == "dead"})


def pas(kern, p, smart=None, mod=N):
    kern.log = []
    mod.run = kern
    mod._DEVEXIT["list"] = []
    res = mod.reconcile_cascade({"interfaces": {}}, p, smart, "")
    return list(kern.log), res


MUT = ("ip route replace", "ip route del", "ip rule add", "ip rule del", "ip route flush")
def muts(log):
    return [x for x in log if x.startswith(MUT)]
def nat_muts(log):
    return [x for x in log if x.startswith("iptables -t nat -I POSTROUTING") or x.startswith("sh -c iptables -t nat -D POSTROUTING")]
def tags(kern):
    import re as _re
    return sorted(m.group(1) for ln in kern.nat for m in [_re.search(r"--comment (swg-egress:exit:\S+)", ln)] if m)
def table(kern):
    return [r for r in kern.tables.get(str(T), [])]


print("[1] the owner up: its own route, and every member's SNAT installed up front")
K = Kernel({})
set_state(N, K, {DA: "up", DB: "up", DC: "up"})
l1, r1 = pas(K, plan())
check("the table defaults via the owner", table(K) == ["default dev %s scope link" % DA], table(K))
check("SNAT for the owner AND each backup, before any move",
      tags(K) == sorted("swg-egress:exit:%s@%s" % (S, d) for d in (DA, DB, DC)), tags(K))
check("nothing says a backup carries", N._EXIT_VIA["m"] == {} and not N._EXIT_VIA["carried"], N._EXIT_VIA)
check("no errors", not r1["errors"], r1["errors"])
l1b, _ = pas(K, plan())
check("settles: a second pass changes nothing", not muts(l1b) and not nat_muts(l1b), muts(l1b) + nat_muts(l1b))

print("[2] the owner dead → its table leaves by the first backup that is up, in place")
set_state(N, K, {DA: "dead", DB: "up", DC: "up"})
l2, r2 = pas(K, plan())
check("the table defaults via the first backup", table(K) == ["default dev %s scope link" % DB], table(K))
check("the move is a `replace` of the default — one command",
      "ip route replace default dev %s table %d" % (DB, T) in l2, muts(l2))
check("…never a `del` of the owner's route first (a moment with no default: direct past the kill switch)",
      "ip route del default dev %s table %d" % (DA, T) not in l2, muts(l2))
check("…no rule deleted, no table flushed (the in-place repair, not a band rebuild)",
      not [x for x in l2 if x.startswith(("ip rule del", "ip route flush"))], muts(l2))
check("…and no iptables in the move: the SNAT was there already", not nat_muts(l2), nat_muts(l2))
check("`exit_via` names the backup carrying", N._EXIT_VIA["m"] == {A: B}, N._EXIT_VIA["m"])
check("the report keeps the owner's own device and verdict",
      [(e["dev"], e["state"]) for e in N._DEVEXIT["list"]] == [(DA, "dead")], N._DEVEXIT["list"])
check("the owner's device is the one carried (the P2P status reads it)", N._EXIT_VIA["carried"] == {DA}, N._EXIT_VIA)
l2b, _ = pas(K, plan())
check("settles on the backup", not muts(l2b) and not nat_muts(l2b), muts(l2b))

print("[3] the order decides, and a dead backup is passed over")
set_state(N, K, {DA: "dead", DB: "dead", DC: "up"})
pas(K, plan())
check("first backup dead too → the next", table(K) == ["default dev %s scope link" % DC] and N._EXIT_VIA["m"] == {A: C},
      (table(K), N._EXIT_VIA["m"]))
K3 = Kernel({})
set_state(N, K3, {DA: "absent", DB: "up", DC: "up"})
pas(K3, plan(members=((C, DC), (B, DB))))
check("the list's order, not the devices' (C first when listed first)", table(K3) == ["default dev %s scope link" % DC],
      table(K3))
set_state(N, K3, {DA: "down", DB: "up", DC: "absent"})
pas(K3, plan(members=((C, DC), (B, DB))))
check("a down owner moves too, past an absent backup", table(K3) == ["default dev %s scope link" % DB], table(K3))

print("[4] no backup up → today: the owner's kill switch decides")
set_state(N, K, {DA: "dead", DB: "dead", DC: "absent"})
l4, _ = pas(K, plan())
check("kill switch off: no default left — the traffic goes direct", table(K) == [], table(K))
check("`exit_via` says no backup is carrying", N._EXIT_VIA["m"] == {A: ""}, N._EXIT_VIA["m"])
K4 = Kernel({})
set_state(N, K4, {DA: "dead", DB: "dead", DC: "absent"})
pas(K4, plan(ks=True))
check("kill switch on: the prohibit alone — dropped", table(K4) == [KS_GUARD], table(K4))
set_state(N, K4, {DA: "dead", DB: "up", DC: "absent"})
l4b, _ = pas(K4, plan(ks=True))
check("kill switch on and a backup up: the backup carries over the prohibit",
      sorted(table(K4)) == sorted([KS_GUARD, "default dev %s scope link" % DB]), table(K4))

print("[5] the owner back → the table returns to it")
set_state(N, K, {DA: "dead", DB: "up", DC: "up"})
pas(K, plan())
set_state(N, K, {DA: "up", DB: "up", DC: "up"})
l5, _ = pas(K, plan())
check("back via the owner, in one replace", table(K) == ["default dev %s scope link" % DA]
      and "ip route replace default dev %s table %d" % (DA, T) in l5
      and not [x for x in l5 if x.startswith(("ip rule del", "ip route flush", "ip route del"))], muts(l5))
check("`exit_via` empties", N._EXIT_VIA["m"] == {} and not N._EXIT_VIA["carried"], N._EXIT_VIA)

print("[6] no `xbackup` → exactly today")
K6 = Kernel({})
set_state(N, K6, {DA: "dead", DB: "up", DC: "up"})
l6, _ = pas(K6, plan(xb=None))
check("a dead owner with no backups withholds its route", table(K6) == [], table(K6))
check("…only the owner's SNAT", tags(K6) == ["swg-egress:exit:%s@%s" % (S, DA)], tags(K6))
check("…and no `exit_via`", N._EXIT_VIA["m"] == {}, N._EXIT_VIA["m"])
K6b = Kernel({})
set_state(N, K6b, {DA: "dead", DB: "up", DC: "up"})
l6b, _ = pas(K6b, plan(xb=[]))
check("`xbackup: []` is the same as none — every command alike", l6b == l6, [x for x in l6b if x not in l6][:5])

print("[7] a malformed `xbackup` lowers nothing")
for bad in ([{"table": True, "id": A, "b": [{"id": B, "dev": DB}]}],
            [{"table": 6000, "id": A, "b": [{"id": B, "dev": DB}]}],
            [{"table": T, "id": A, "b": [{"id": B, "dev": "a b"}]}],
            [{"table": T, "id": A, "b": [{"id": B, "dev": "x" * 16}]}],
            [{"table": T, "id": "", "b": [{"id": B, "dev": DB}]}],
            [{"table": T, "id": A, "b": "wgx-b"}], "nope", [1, None]):
    check("refused: %s" % json.dumps(bad)[:70], N._xbackup_take(bad) == {}, N._xbackup_take(bad))
check("a good one reads", N._xbackup_take(plan()["xbackup"]) == {T: (A, [(B, DB), (C, DC)])})

print("[8] the routing trigger follows a backup's state")
_c = plan()
set_state(N, K, {DA: "dead", DB: "up", DC: "up"})
s_up = N._devexit_sig(_c)
set_state(N, K, {DA: "dead", DB: "dead", DC: "up"})
check("a backup going dead changes the signature", N._devexit_sig(_c) != s_up)
_c0 = plan(xb=None)
check("without `xbackup` the signature is the plain device list",
      N._devexit_sig(_c0) == sorted((e["dev"], N._devexit_state(e["dev"]), N._dev_gateway(e["dev"])) for e in _c0["devexit"]),
      N._devexit_sig(_c0))

print("[9] a SOCKS backup's DNS redirect while it carries")
_sx = dict(N._EXITS.get("socks") or {})
N._EXITS["socks"] = {DB: False}
K9 = Kernel({})
set_state(N, K9, {DA: "up", DB: "up", DC: "up"})
l9a, _ = pas(K9, plan())
dns = lambda log: [x for x in log if "swg-s5x-dns" in x and S in x and "DNAT" in x and " -D " not in x]
check("owner carrying: no redirect into the SOCKS backup", not dns(l9a), dns(l9a))
set_state(N, K9, {DA: "dead", DB: "up", DC: "up"})
l9b, _ = pas(K9, plan())
check("the SOCKS backup carrying: its subnet's DNS goes to the proxy's mapdns", dns(l9b), [x for x in l9b if "s5x" in x][:4])
N._EXITS["socks"] = _sx

print("[10] a dial-in backup's private cut stays put across a move")
_dl = N._EXITS.get("dialin")
N._EXITS["dialin"] = {DC}
K10 = Kernel({})
set_state(N, K10, {DA: "up", DB: "absent", DC: "up"})
pas(K10, plan(members=((C, DC),)))
_cuts = sorted(r for r in table(K10) if r.startswith("prohibit ") and "default" not in r)
check("the cut is in the table while the owner carries (a member is a dial-in exit)", len(_cuts) == len(N.EXIT_PRIVATE_CUT), table(K10))
set_state(N, K10, {DA: "dead", DB: "absent", DC: "up"})
l10, _ = pas(K10, plan(members=((C, DC),)))
check("the move to the dial-in backup is in place: no flush, no rule deleted",
      not [x for x in l10 if x.startswith(("ip rule del", "ip route flush"))] and table(K10)[-1] == "default dev %s scope link" % DC,
      muts(l10))
check("…and the cut is the same", sorted(r for r in table(K10) if r.startswith("prohibit ") and "default" not in r) == _cuts)
N._EXITS["dialin"] = _dl

print("[11] the P2P route follows, and its drop allows every member")
_cap = []
_p2p_nft = N._p2p_nft
N._p2p_nft = lambda mode, strict, oif, *a, **kw: (_cap.append((mode, list(oif), [g.get("oif") for g in kw.get("groups") or []])),
                                                  _p2p_nft(mode, strict, oif, *a, **kw))[1]
_sm = {"p2p": {"action": "route", "entry": {"table": T, "via_iface": DA, "subnets": [S]}}}
# a P2P route out of an exit is a RULE-scoped plan entry (cascade_plan's p2p_items): no `from S` route of its own, so the
# table's default comes from the P2P route alone — the one this checks
_p11 = plan()
_p11["devexit"][0]["scope"] = "rule"
K11 = Kernel({})
set_state(N, K11, {DA: "dead", DB: "up", DC: "up"})
del _cap[:]
pas(K11, _p11, smart=_sm)
check("the route's allowed devices: the owner and every backup", _cap and _cap[-1][1] == [DA, DB, DC], _cap[-1:])
check("…and its table defaults via the live backup", table(K11) == ["default dev %s scope link" % DB], table(K11))
del _cap[:]
pas(Kernel({}), plan(xb=None), smart=_sm)
check("without backups: the owner alone, as today", _cap and _cap[-1][1] == [DA], _cap[-1:])
_g = N._p2p_groups({"entries": [{"table": T, "via_iface": DA, "subnets": [S]}]}, [], {T: [DB]})
check("per-interface groups: the route group's devices take the backups", [g["oif"] for g in _g if g.get("table") == T] == [[DA, DB]], _g)
_g0 = N._p2p_groups({"entries": [{"table": T, "via_iface": DA, "subnets": [S]}]}, [])
check("…and without, the owner alone", [g["oif"] for g in _g0 if g.get("table") == T] == [[DA]], _g0)
N._p2p_nft = _p2p_nft
# …and the node's card: the route reads "up" while a backup carries it, "down" when none does
set_state(N, K11, {DA: "dead", DB: "up", DC: "up"})
pas(K11, _p11, smart=_sm)
_st11 = ((N.smart_status() or {}).get("p2p") or {}).get("route")
check("the P2P route reads up on the node's card while a backup carries it", _st11 == "up", _st11)
set_state(N, K11, {DA: "dead", DB: "dead", DC: "absent"})
pas(K11, _p11, smart=_sm)
_st11b = ((N.smart_status() or {}).get("p2p") or {}).get("route")
check("…and down when none does", _st11b == "down", _st11b)

print("[12] a rule-scoped exit's route follows too")
_rp = {"devexit": [{"subnet": "10.18.0.0/24", "dev": DA, "table": T, "killswitch": False, "scope": "rule", "egress_ip": "", "gw": ""}],
       "xbackup": plan()["xbackup"]}
_rs = {"entries": [{"subnet": "10.18.0.0/24", "category": "netflix", "action": "exit", "via_iface": DA, "table": T}],
       "categories": ["netflix"]}
K12 = Kernel({})
set_state(N, K12, {DA: "dead", DB: "up", DC: "up"})
pas(K12, _rp, smart=_rs)
check("the category's table defaults via the live backup", "default dev %s scope link" % DB in table(K12), table(K12))

# ── panel ────────────────────────────────────────────────────────────────────────────────────────────────────────────
NODE = {"ifaces": {"awg0": {}}}
V = P._validate_exits
def X(i, **kw):
    return dict({"id": i, "producer": "imported", "provider": "warp", "device": "wgx-" + i, "label": i.upper()}, **kw)

print("[13] the exit list's save")
c13, e13 = V([X(A, backup=[B, C]), X(B), X(C, enabled=False)], NODE)
check("stored in order; a disabled backup kept", c13 and [x.get("backup") for x in c13] == [[B, C], None, None], (e13, c13))
c13m, e13m = V([X(A, backup=[B]), X(B, backup=[A])], NODE)
check("mutual backups are allowed (flat lists)", c13m and c13m[0]["backup"] == [B] and c13m[1]["backup"] == [A], e13m)
for why, lst in (("itself", [X(A, backup=[A]), X(B)]), ("twice", [X(A, backup=[B, B]), X(B)]),
                 ("not a list", [X(A, backup=B), X(B)]), ("not ids", [X(A, backup=[1]), X(B)]),
                 ("an adopted backup", [X(A, backup=["dddd0004"]), {"id": "dddd0004", "producer": "adopted", "device": "tun9"}]),
                 ("an adopted owner", [{"id": "dddd0004", "producer": "adopted", "device": "tun9", "backup": [A]}, X(A)])):
    _c, _e = V(lst, NODE)
    check("refused: %s" % why, _c is None and _e, (_c, _e))
c13d, e13d = V([X(A, backup=[B, C]), X(C)], NODE, prev=c13)
check("a member deleted in the same save is pruned", c13d and c13d[0].get("backup") == [C], (e13d, c13d))
c13k, e13k = V([{k: v for k, v in x.items() if k != "backup"} for x in c13], NODE, prev=c13)
check("a request that does not carry the field keeps the stored list", c13k and c13k[0].get("backup") == [B, C], (e13k, c13k))
c13c, _ = V([X(A, backup=[]), X(B), X(C)], NODE, prev=c13)
check("`[]` clears it: no key stored", c13c and "backup" not in c13c[0], c13c)
c13u, _ = V([X(A, backup=["ffff9999", B]), X(B)], NODE)
check("an id the list does not hold is dropped", c13u and c13u[0].get("backup") == [B], c13u)

print("[14] the plan")
def fleet(exits, used=True):
    nd = {"name": "n1", "links": {}, "exits": exits,
          "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": A}} if used else {"awg0": {}}}
    return {"n1": nd}, {"n1": {"interfaces": {"awg0": {"meta": {"subnet": S}}}}}
_xs = [X(A, backup=[B, C]), X(B), X(C, enabled=False)]
_n, _s = fleet(_xs)
p14 = P.cascade_plan(_n, _s)["n1"]
_t = next((e["table"] for e in p14.get("devexit") or [] if e["dev"] == "wgx-" + A), None)
check("xbackup: the owner's table, members resolved, the disabled one left out",
      p14.get("xbackup") == [{"table": _t, "id": A, "b": [{"id": B, "dev": "wgx-" + B}]}], p14.get("xbackup"))
_n0, _s0 = fleet([X(A), X(B), X(C, enabled=False)])
check("no backups anywhere → no key at all (a byte-identical plan)", "xbackup" not in P.cascade_plan(_n0, _s0)["n1"])
_nu, _su = fleet(_xs, used=False)
check("an exit nothing uses gets none", "xbackup" not in (P.cascade_plan(_nu, _su).get("n1") or {}))
_nd, _sd = fleet([X(A, backup=[B]), X(B, device="wgx-" + A)])
check("a member on the owner's own device is left out", "xbackup" not in P.cascade_plan(_nd, _sd)["n1"],
      P.cascade_plan(_nd, _sd)["n1"].get("xbackup"))

print("[15] failover nodes")
_a = {"exits": [X(A, backup=[B]), X(B)], "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": A}}}
check("exit_refs takes the backups of an exit in use", P.exit_refs(_a) == {A, B}, P.exit_refs(_a))
_w = {}
P._fo_mirror_exits(_a, _w)
_wb = {x["id"]: x for x in _w.get("exits") or []}
check("the mirror holds the backup's copy and the list", B in _wb and _wb.get(A, {}).get("backup") == [B], _w.get("exits"))

print("[16] the node's Issues line")
_c16 = {"exits": [X(A), X(B, label="Bee")], "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": A}}}
_snap16 = {"devexit": [{"dev": "wgx-" + A, "subnet": S, "state": "dead", "killswitch": False}], "exit_via": {A: B}}
_iss = [i.get("error") if isinstance(i, dict) else str(i) for i in P._node_issues(_c16, _snap16)]
check("names the backup carrying, not this node's own IP",
      any("backup exit Bee" in i for i in _iss) and not any("own IP" in i for i in _iss), _iss)
_snap16b = dict(_snap16, exit_via={A: ""})
_iss2 = [i.get("error") if isinstance(i, dict) else str(i) for i in P._node_issues(_c16, _snap16b)]
check("none up: today's sentence (this node's own IP)", any("own IP" in i for i in _iss2) and not any("backup exit" in i for i in _iss2), _iss2)

print("[17] the row's `via`, and the snapshot's shape")
_row = {"id": A, "device": "wgx-" + A, "up": True}
check("exits_live puts `via` on the row", P.exits_live({"exits": [_row], "exit_via": {A: B}})[A].get("via") == B)
check("…and a node that sends none gives the row as it came", P.exits_live({"exits": [_row]})[A] is _row)
_sn = {"exit_via": {A: B, "x": 1}}
P._snap_sanitise(_sn, "n1")
check("a non-string value is dropped from `exit_via`", _sn.get("exit_via") == {A: B}, _sn)
_sn2 = {"exit_via": [A]}
P._snap_sanitise(_sn2, "n1")
check("a list is not `exit_via`", "exit_via" not in _sn2, _sn2)

# ── optional: the byte-identical claim, against a commit's programs ────────────────────────────────────────────────
BASE = os.environ.get("SWG_XBK_BASE")
if BASE and not PLANT:
    print("[B] plans without backups vs %s" % BASE)
    d = tempfile.mkdtemp(prefix="xbk-base-")
    for f in ("swg-noded", "swg-panel-server"):
        open(os.path.join(d, f + ".py"), "w").write(subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (BASE, f)],
                                                                   capture_output=True, text=True, check=True).stdout)
    NB = _load(os.path.join(d, "swg-noded.py"), "swgnoded_base")
    PB = _load(os.path.join(d, "swg-panel-server.py"), "swgpanel_base")
    _hermetic(NB)
    for mod in (N, NB):                                  # each process's one-time setup (a chain made once, a probe table) first
        for sm in (None, _sm):
            kk = Kernel({})
            set_state(mod, kk, {DA: "up"})
            pas(kk, plan(xb=None), smart=sm, mod=mod)
    for st in ({DA: "up"}, {DA: "dead"}, {DA: "absent"}):
        for ks in (False, True):
            for sm in (None, _sm):
                outs = []
                for mod in (N, NB):
                    kk = Kernel({})
                    set_state(mod, kk, st)
                    la, _ = pas(kk, plan(ks=ks, xb=None), smart=sm, mod=mod)
                    lb, _ = pas(kk, plan(ks=ks, xb=None), smart=sm, mod=mod)
                    outs.append((la, lb, sorted(kk.nat), kk.tables, copy.deepcopy(mod._DEVEXIT["list"])))
                check("node, %s ks=%s p2p=%s: every command, the SNAT, the tables and the report alike"
                      % (st[DA], ks, bool(sm)), outs[0] == outs[1],
                      [x for x in outs[0][0] if x not in outs[1][0]][:4] + ["|"] + [x for x in outs[1][0] if x not in outs[0][0]][:4])
    _n0, _s0 = fleet([X(A), X(B), X(C, enabled=False)])
    check("panel: the plan alike", P.cascade_plan(copy.deepcopy(_n0), _s0) == PB.cascade_plan(copy.deepcopy(_n0), _s0))
    _cb = {"exits": [X(A), X(B)], "ifaces": {"awg0": {"egress_mode": "exit", "exit_id": A}}}
    _sb = {"devexit": [{"dev": "wgx-" + A, "subnet": S, "state": "dead", "killswitch": False}]}
    check("panel: the Issues line alike", P._node_issues(_cb, _sb) == PB._node_issues(_cb, _sb))
    _xl = [X(A), X(B)]
    check("panel: the exit list's save alike", V(copy.deepcopy(_xl), NODE) == PB._validate_exits(copy.deepcopy(_xl), NODE))

print("\n%s" % ("FAIL: %d check(s) red%s" % (len(FAILS), (" (" + PLANT + ")") if PLANT else "") if FAILS
                else "OK — exit backups hold" + ((" (" + PLANT + " NOT caught)") if PLANT else "")))
sys.exit(1 if FAILS else 0)
