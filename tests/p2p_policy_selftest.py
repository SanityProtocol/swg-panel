#!/usr/bin/env python3
"""Self-test — the node-wide P2P policy (docs/P2P-POLICY-PLAN.md, P1): swg-noded's `swg_p2p` table.

  [1] the policy word: absent/unknown → legacy (today's per-interface semantics), route → block (P3 unbuilt: fail CLOSED)
  [2] legacy: only the strict subnets are classified and dropped; no guard, no cls_out, no mark; nothing strict → no table
  [3] block: drops for everyone, decided in PREROUTING (before the relay divert, -140) and again on every egress (empty oif)
  [4] direct: P2P routed by P2P_BIT (restore + marks) with `fwmark P2P_BIT lookup main` at 6880, BELOW the band — and
      only the main table's default device(s) may carry it; strict subnets still dropped
  [5] chain ORDER — traffic to the node itself and replies are never judged; held flows die before the packet gate;
      a blocked user's drop precedes the direct mark
  [6] no `@ih` (old kernel): no signature rules, state "degraded" — fan-out still runs
  [7] the gate: a second pass with the same answer loads nothing; a table flushed in place (no drop) is rebuilt
  [8] the torrent port-hint is gone from swg_mech; activity reads swg_p2p's counters into "*"
  [11] host-readable keys: only `typeof ip saddr|ip daddr|th dport` and concatenations (nft_host_readable_selftest)
  [9] the old SWGP chain + swgp_src ipset are torn down once per process
  [12] the @ih capability PROBE is valid nft: every closing brace on its own line (a one-line `{ … } }` is a syntax error
       on every kernel and silently disabled signatures fleet-wide, 2026-10-02) — and, where `sudo -n nft` exists, the
       real nft accepts it (`nft -c`); said SKIPPED out loud when it cannot ask
  [13] route (P3): only a lowered entry in the band routes — none, junk or a table outside 7000-7099 → block (fail closed);
       the routable set is the entry's subnets minus the strict ones; the mark is T|P2P_BIT with `fwmark T|P2P_BIT lookup T`
       at 6880; only entry.via_iface may carry P2P; everything outside the routable set is blocked in prerouting
  [14] RETROSPECTIVE BUG: a route's table is installed BY THE NODE — reconcile_cascade with nothing but smart.p2p must
       add `default dev <via> table T` and `fwmark T lookup T` (it was borrowed from other rules' tables; with none, P2P
       was dropped instead of routed while the node reported "route"); a dead exit withholds the route (fail closed)
  [15] route state: the table in force has a default route → "up", none → "down" (the card names it)
  [16] the device name the panel sends is written into nft and ip rules: anything but an interface name → no route
  [17] CODE REVIEW: a route through a DOWN or ABSENT device is withheld (never signed, never attempted) — the P2P route,
       and a routing rule's own smart exit too: signed, it could not install, and the band was rebuilt on every pass
  [18] CODE REVIEW: a node whose only routing is a P2P route still gets forwarding + loose rp_filter on the route's device
  [19] CODE REVIEW: the route state is judged by a `default dev/via` line (a kill-switch table's `prohibit default` is not
       a way out), is cleared each pass, and every status report corrects "up" by the device itself
  [20] CODE REVIEW #2: whole-interface cascades (fwd) and exit records (exit_) through a down leg are withheld too —
       their rules stay; and a device is judged by `_devexit_state` (a dead tunnel the plan did not list included)
  [21] CODE REVIEW #2/#3/#4: the trigger re-reads exactly what the last COMPLETED routing pass judged (`_ROUTED`): a
       device back up, an exit's dead verdict cleared, or a device created again under its name (an exit rebuilt in
       place) runs the pass on the next sync instead of the 60 s sweep; it settles once every device reads as judged, a
       change while the pass ran is caught, a pass that fails after judging is retried, a pass that judges nothing
       leaves nothing to re-read, and a name the link reader refuses is absent with no index
  [22] CODE REVIEW #2: swg_mech is read once per report, and the flagged IPs survive a failed counter read
  [10] a node with nothing to do pays no subprocess per sync once it has looked; a new strict subnet still builds

Run: python3 tests/p2p_policy_selftest.py        (0 = pass)
     --perturb    plant each old behaviour in turn → every one must go RED (exit 0 when all are caught)
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SRC = open(NODED, encoding="utf-8").read()

PLANTS = {   # name: (old text, planted text) — each re-introduces a defect the checks exist for
    "route-open":   ('    if a == "route":                                          # P3 is not built: an unrunnable route fails CLOSED, never open\n        return "block"\n', ""),
    "local-judged": ('    L.append("    fib daddr type local return")', '    pass'),
    "reply-judged": ('    L.append("    ct direction reply return")\n    L += ["    " + h for h in held]\n    # Traffic TO the node',
                     '    L += ["    " + h for h in held]\n    # Traffic TO the node'),
    "rule-in-band": ("P2P_RULE_PRI = 6880 ", "P2P_RULE_PRI = 7050 "),
    "porthint":     ('            if "smtp" in cats:     els.append("tcp . 25")\n',
                     '            if "smtp" in cats:     els.append("tcp . 25")\n            if "torrents" in cats: els += ["udp . 6881-6889", "tcp . 6881-6889"]\n'),
    "gate-memo":    ('if have.returncode == 0 and cur == sig and " drop" in (have.stdout or ""):\n            return\n        _P2P["tbl"] = True',
                     'if have.returncode == 0 and cur == sig:\n            return\n        _P2P["tbl"] = True'),
    "rule-poll":    ('    if not on and _P2P["rule"] is False:\n        return\n', ''),
    "ctid-key":     ('"  set flag { typeof ip saddr; flags timeout; size 65535; }",', '"  set flag { typeof ip saddr; flags timeout; size 65535; }", "  set p2p_ct { typeof ct id; flags timeout; }",'),
    "probe-1line":  ('P2P_PROBE = "table inet swg_p2p_probe {\\n  chain c {\\n    meta l4proto udp @ih,0,64 0x0000041727101980 counter\\n  }\\n}\\n"',
                     'P2P_PROBE = "table inet swg_p2p_probe { chain c { meta l4proto udp @ih,0,64 0x0000041727101980 counter } }\\n"'),
    "route-open":   ('        return "route" if _p2p_entry(p2p) else "block"', '        return "route"'),
    "route-strict": ('                    if n.version == 4 and str(n) not in strict:', '                    if n.version == 4:'),
    "rt-borrowed":  ('    if _pe:\n        arr_exit = arr_exit + [', '    if False:\n        arr_exit = arr_exit + ['),
    "rt-nostate":   ('            _P2P["route"] = "up" if any(ln.split()[:1] == ["default"] for ln in _rt.splitlines()) else "down"',
                     '            _P2P["route"] = "up"'),
    "iface-any":    ('and re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", str(e.get("via_iface") or ""))):', 'and e.get("via_iface")):'),
    "fib-perpkt":   ('    L += ["    " + h for h in held]\n    # Traffic TO the node', '    L.append("    fib daddr type local return")\n    L += ["    " + h for h in held]\n    # Traffic TO the node'),
    "rt-prohibit":  ('            _P2P["route"] = "up" if any(ln.split()[:1] == ["default"] for ln in _rt.splitlines()) else "down"',
                     '            _P2P["route"] = "up" if "default" in _rt else "down"'),
    "withhold-down":('        return dev in _dxnogw or _lst[dev][0] != "up"', '        return dev in _dxnogw'),
    "rp-gate":      ('        if fwd or smart_e or exit_ or arr_exit:', '        if fwd or smart_e or exit_:'),
    "status-stale": ('        if _r == "up" and _devexit_state(', '        if False and _devexit_state('),
    "route-stale":  ('        _P2P.update(route="", route_dev="")', '        pass'),
    "read-table":   ('            cj = json.loads(run(["nft", "-j", "list", "counters", "table", "inet", P2P_NFT_TABLE]).stdout or "{}")',
                     '            cj = json.loads(run(["nft", "-j", "list", "table", "inet", P2P_NFT_TABLE]).stdout or "{}")'),
    "fwd-signed":   ('        if not e.get("_noroute"):                      # a route the rebuild withholds (device not up) is not signed: drift\n            sig.add(f"T|{T}|default|{e[\'via_iface\']}|{str(e.get(\'gw\') or \'\')}")',
                     '        sig.add(f"T|{T}|default|{e[\'via_iface\']}|{str(e.get(\'gw\') or \'\')}")'),
    "fwd-unmarked": ('    fwd = [dict(e, _noroute=_withheld(e["via_iface"])) for e in fwd]\n', ''),
    "seen-linkonly":('    s = _devexit_state(dev) if state is None else state', '    s = _dev_link_state(dev) if state is None else state'),
    "no-ifindex":   ('    return (s, _dev_ifindex(dev) if s != "absent" else 0)', '    return (s, 0)'),
    "index-unguarded":('    return (s, _dev_ifindex(dev) if s != "absent" else 0)', '    return (s, _dev_ifindex(dev))'),
    "seed-byhand":  ('    _lst = {e["dev"]: _dev_seen(e["dev"], e["state"]) for e in _dxs if e.get("dev")}',
                     '    _lst = {e["dev"]: (e["state"], 0) for e in _dxs if e.get("dev")}'),
    "commit-midpass":('    _ROUTED["pending"] = {d: v for d, v in _lst.items() if d}', '    _ROUTED["judged"] = _ROUTED["pending"] = {d: v for d, v in _lst.items() if d}'),
    "no-commit":    ('                    _ROUTED["judged"] = _ROUTED["pending"]    # …with what it judged', '                    pass    # …with what it judged'),
    "trig-missing": ('                if (_route_sig != last_route_sig or _iface_churn or _routed_devs_moved()\n',
                     '                if (_route_sig != last_route_sig or _iface_churn\n'),
    "record-stale": ('    _ROUTED["pending"] = {d: v for d, v in _lst.items() if d}', '    _ROUTED["pending"].update({d: v for d, v in _lst.items() if d})'),
    "record-fresh": ('    _ROUTED["pending"] = {d: v for d, v in _lst.items() if d}', '    _ROUTED["pending"] = {d: _dev_seen(d) for d in _lst if d}'),
    "mech-twice":   ('        for ln in mech.splitlines():                              # ONE rule carries', '        for ln in (run(["nft", "list", "table", "inet", "swg_mech"]).stdout or "").splitlines():   # ONE rule carries'),
    "ips-coupled":  ('                out.setdefault("*", {})["torrent_ips"] = [str(i) for i in ips]', '                out["*"]["torrent_ips"] = [str(i) for i in ips]'),
    "no-retire":    ('        if not _P2P["retired"]:', '        if False:'),
}


def load(src):
    ld = importlib.machinery.SourceFileLoader("noded_p2p", NODED)
    m = types.ModuleType("noded_p2p"); m.__file__ = NODED
    exec(compile(src, NODED, "exec"), m.__dict__)
    return m


class Box:
    """A stand-in for the box: records every command, answers the few reads the code makes."""
    def __init__(self, ih=True, wan="eth0"):
        self.cmds, self.tables, self.rules, self.ih, self.wan, self.tables_rt = [], {}, [], ih, wan, {}

    def run(self, args, input_text=None, timeout=20):
        a = list(args); self.cmds.append((a, input_text))
        out, rc = "", 0
        if a[:2] == ["nft", "-f"]:
            text = input_text if a[2] == "-" else open(a[2]).read()
            if "swg_p2p_probe" in text:
                rc = 0 if self.ih else 1
            else:
                for name in ("swg_p2p", "swg_mech"):
                    if "table inet %s {" % name in text:
                        self.tables[name] = text
        elif a[:4] == ["nft", "list", "table", "inet"]:
            if a[4] in self.tables:
                out = self.tables[a[4]]
            else:
                rc = 1
        elif a[:3] == ["nft", "delete", "table"]:
            self.tables.pop(a[4], None)
        elif a[:4] == ["ip", "route", "show", "table"]:
            out = self.tables_rt.get(a[4], "")
        elif a[:4] == ["ip", "route", "show", "default"]:
            out = "default via 1.2.3.1 dev %s proto static\n" % self.wan
        elif a[:2] == ["ip", "rule"] and a[2] == "show":
            out = "".join(r + "\n" for r in self.rules)
        elif a[:3] == ["ip", "rule", "add"]:
            self.rules.append("%s:\tfrom all fwmark %s lookup %s" % (a[-1], a[4], a[6]))
        elif a[:3] == ["ip", "rule", "del"]:
            before = len(self.rules)
            self.rules = [r for r in self.rules if not r.startswith(a[-1] + ":")][:]
            rc = 0 if len(self.rules) < before else 2
        elif a[:3] == ["iptables", "-t", "mangle"] and "-C" in a:
            rc = 1
        r = types.SimpleNamespace(returncode=rc, stdout=out, stderr="")
        return r


def run_checks(src):
    fails = []
    def ok(cond, what):
        if not cond:
            fails.append(what)

    def fresh(ih=True):
        m = load(src); b = Box(ih=ih)
        m.run = b.run
        m.GEO_DIR = tempfile.mkdtemp()
        m._relay_links = lambda cfg: ()
        return m, b

    m, b = fresh()
    # [1]
    ok(m._p2p_mode(None) == "legacy" and m._p2p_mode({"action": "zzz"}) == "legacy", "[1] absent/unknown → legacy")
    ok(m._p2p_mode({"action": "route"}) == "block", "[1] route must fail CLOSED (block) until P3")
    ok(m._p2p_mode({"action": "direct"}) == "direct" and m._p2p_mode({"action": "block"}) == "block", "[1] block/direct kept")

    # [2] legacy
    t = m._p2p_nft("legacy", ["10.67.0.0/24"], [], [], True)
    ok("chain guard" not in t, "[2] legacy builds no guard")
    ok("ip saddr != @strict return" in t and "meta mark set" not in t, "[2] legacy is scoped to strict, never marks")
    res = {"changed": 0, "errors": []}
    m._ensure_p2p(None, {"10.68.0.0/24": ["smtp"]}, {}, res)
    ok("swg_p2p" not in b.tables and not any(r.startswith("6880:") for r in b.rules), "[2] nothing strict → no table, no rule")

    # [3] block
    t = m._p2p_nft("block", [], [], [], True)
    cls = t.split("chain cls {", 1)[1].split("\n  }", 1)[0]
    ok("    ip saddr @flag meta l4proto" in cls and "counter name dropped drop" in cls, "[3] block drops flagged users in prerouting")
    g = t.split("chain guard {", 1)[1]
    ok("oifname != {" not in g and "jump gdrop" in t, "[3] block allows no egress device: every signature drops")
    ok("chain guard" in t and "fib saddr type local" in t, "[3] block judges every egress + the node's own processes")

    # [4] direct
    m, b = fresh()
    res = {"changed": 0, "errors": []}
    m._ensure_p2p({"action": "direct"}, {"10.67.0.0/24": ["torrents"]}, {}, res)
    t = b.tables.get("swg_p2p", "")
    ok('oifname != { "eth0" }' in t, "[4] direct allows only the main default device")
    ok("ct mark & 0x40000000 == 0x40000000 meta mark set ct mark" in t and "meta mark set 0x40000000" in t, "[4] direct restores + marks P2P_BIT")
    ok(any(r.startswith("6880:") and "0x40000000" in r for r in b.rules), "[4] fwmark rule at 6880")
    ok(m.P2P_RULE_PRI < m.SWG_RT_UP_BASE, "[4] the P2P rule sits below every band (a `from S lookup T` must not outrank it)")
    ok("ip saddr @strict ip saddr @flag" in t, "[4] strict subnets still dropped under direct")
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    ok(not any(r.startswith("6880:") for r in b.rules), "[4] leaving direct removes the rule")

    # [5] order
    for mode in ("legacy", "block", "direct"):
        t = m._p2p_nft(mode, ["10.67.0.0/24"], ["eth0"], [], True)
        cls = t.split("chain cls {", 1)[1].split("\n  }", 1)[0].splitlines()
        idx = lambda s: next((i for i, l in enumerate(cls) if s in l), 10 ** 6)
        first_drop = min(i for i, l in enumerate(cls) if "drop" in l)
        _lr = idx("fib daddr type local return")
        ok(idx("ct direction reply return") < first_drop and all("fib daddr type != local" in l or i > _lr or "@held" in l
                                                                for i, l in enumerate(cls) if "drop" in l),
           "[5] %s: replies return before any drop, and traffic to the node is never dropped (each early drop asks fib)" % mode)
        ok(idx("@held4") < idx("ct original packets > 4 return") and idx("@held6") < idx("ct original packets > 4 return"), "[5] %s: held flows die before the packet gate" % mode)
        if mode == "direct":
            ok(idx("ip saddr @strict ip saddr @flag") < idx("ct state new ip saddr @flag"), "[5] strict drop precedes the direct mark")
        if "chain guard" in t:
            g = t.split("chain guard {", 1)[1]
            ok(g.index("ct direction reply return") < g.index("drop"), "[5] %s guard: replies never judged" % mode)

    # [6] no @ih
    m, b = fresh(ih=False)
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    t = b.tables.get("swg_p2p", "")
    ok("@ih" not in t and "meter p2pfan" in t and m._P2P["state"] == "degraded", "[6] no @ih → fan-out only, degraded")

    # [7] gate
    m, b = fresh()
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    n = sum(1 for a, _ in b.cmds if a[:2] == ["nft", "-f"] and a[2] == "-")
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    n2 = sum(1 for a, _ in b.cmds if a[:2] == ["nft", "-f"] and a[2] == "-")
    ok(n2 == n, "[7] same answer → nothing loaded")
    b.tables["swg_p2p"] = "table inet swg_p2p {\n  chain cls {\n  }\n}\n"          # flushed in place
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    ok(" drop" in b.tables["swg_p2p"], "[7] a flushed table is rebuilt")

    # [8] port-hint gone; activity
    m, b = fresh()
    m._ensure_mech_block({"10.67.0.0/24": ["torrents", "smtp"]}, {"changed": 0, "errors": []})
    ok("6881" not in b.tables.get("swg_mech", "") and "tcp . 25" in b.tables.get("swg_mech", ""), "[8] torrent port-hint retired, smtp kept")
    m._P2P["on"] = True
    def fake(args, input_text=None, timeout=20):
        if args[:5] == ["nft", "-j", "list", "counters", "table"]:
            o = {"nftables": [{"counter": {"name": n, "packets": p}} for n, p in (("dht", 3), ("fan_flag", 4), ("dropped", 99))]}
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(o), stderr="")
        if args[:4] == ["nft", "-j", "list", "set"]:
            o = {"nftables": [{"set": {"name": "flag", "elem": [{"elem": {"val": "10.68.0.7", "timeout": 600}}]}}]}
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(o), stderr="")
        if args[:4] == ["nft", "-j", "list", "table"]:
            return types.SimpleNamespace(returncode=0, stdout="WHOLE TABLE READ", stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")
    m.run = fake
    act = m._block_activity()
    ok(act.get("*", {}).get("torrent") == 7 and act["*"].get("torrent_ips") == ["10.68.0.7"],
       "[8] activity = sig + fan under *, flagged IPs — by two TARGETED reads, never the whole table (meter + flow sets)")
    # [22] one swg_mech read; names survive a failed count
    seen = []
    def fake2(args, input_text=None, timeout=20):
        seen.append(list(args))
        if args[:5] == ["nft", "-j", "list", "counters", "table"]:
            return types.SimpleNamespace(returncode=0, stdout="{not json", stderr="")
        return fake(args, input_text, timeout)
    m.run = fake2
    act2 = m._block_activity()
    ok(sum(1 for a in seen if a == ["nft", "list", "table", "inet", "swg_mech"]) == 1, "[22] swg_mech is read once per report")
    ok((act2.get("*") or {}).get("torrent_ips") == ["10.68.0.7"], "[22] a failed counter read does not lose the flagged IPs")

    # [11] keys the host's older nft can read
    import re as _re
    for mode in ("legacy", "block", "direct"):
        t = m._p2p_nft(mode, ["10.67.0.0/24"], ["eth0"], ["10.255.0.2/31"], True)
        ks = set(_re.findall(r"\{ typeof ([^;]+);", t))
        ok(ks <= {"ip saddr", "ip daddr", "th dport"} and "ct id" not in t, "[11] %s: only measured typeof keys (%s)" % (mode, sorted(ks)))

    # [12] the probe the node really sends
    pr = m.P2P_PROBE
    ok(all(ln.strip() == "}" or "}" not in ln for ln in pr.splitlines()), "[12] the probe puts every closing brace on its own line")
    import shutil, subprocess as _sp
    if shutil.which("sudo") and _sp.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        r = _sp.run(["sudo", "-n", "nft", "-c", "-f", "-"], input=pr, capture_output=True, text=True)
        ok(r.returncode == 0, "[12] the real nft accepts the probe (%s)" % (r.stderr or "").strip()[:80])
    else:
        print("  [12] real-nft check SKIPPED — no passwordless sudo here; the static check above still ran")

    # [13] route
    E = {"table": 7003, "via_iface": "wgx0", "subnets": ["10.68.0.0/24", "10.67.0.0/24"]}
    ok(m._p2p_mode({"action": "route", "entry": E}) == "route", "[13] a lowered route runs as route")
    for bad in (None, {}, {"table": 6000, "via_iface": "x"}, {"table": "zz", "via_iface": "x"}, {"table": 7003}):
        ok(m._p2p_mode({"action": "route", "entry": bad}) == "block", "[13] route without a usable entry → block (%s)" % bad)
    m, b = fresh()
    m._ensure_p2p({"action": "route", "entry": E}, {"10.67.0.0/24": ["torrents"]}, {}, {"changed": 0, "errors": []})
    t = b.tables.get("swg_p2p", "")
    ok("set routable { typeof ip saddr; flags interval; elements = { 10.68.0.0/24 } }" in t, "[13] routable = entry subnets minus strict")
    ok("meta mark set %#x" % (7003 | m.P2P_BIT) in t and 'oifname != { "wgx0" }' in t, "[13] mark T|BIT, only via_iface allowed")
    ok("ip saddr != @routable ip saddr @flag" in t and "ip saddr @strict ip saddr @flag" in t, "[13] outside routable / strict → dropped")
    ok(any(r.startswith("6880:") and "fwmark %#x" % (7003 | m.P2P_BIT) in r and r.endswith("lookup 7003") for r in b.rules),
       "[13] fwmark T|BIT lookup T at 6880 (%s)" % b.rules)

    # [14] the route's table, through the real reconcile_cascade with everything around it stubbed
    def recon(entry, dead=False, link="up", smart_entries=(), sysctls=None, plan=None, states=None, idx=None):
        m = load(src)
        calls = []
        m._dev_link_state = lambda dev: link if dev in ("wgx9", "swg_q") else "up"
        _st = states if states is not None else {}
        if sysctls is not None:
            m._sysctl_ensure = lambda key, val, ok=None: sysctls.append((key, val)) or val
        def rr(a, input_text=None, timeout=20):
            calls.append(list(a))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        m.run = rr
        m.GEO_DIR = tempfile.mkdtemp()
        def _dx(dev):
            v = _st.get(dev)
            if isinstance(v, list):                       # successive reads: the device changes while the pass runs
                return v.pop(0) if len(v) > 1 else v[0]
            return v if v is not None else (("dead" if dead else link) if dev in ("wgx9", "swg_q") else "up")
        m._devexit_state = _dx
        if idx is not None:
            m._dev_ifindex = lambda d: idx.get(d, 0)
        m._dev_is_ether = lambda dev: False
        m._ensure_smart_nft = lambda *a, **k: {}
        for fn in ("_ensure_fwd_iptables", "_ensure_sni_router", "_ensure_smart_xtstring", "reconcile_catk_chain", "_ensure_smart_dnsmasq",
                   "_dnsmasq_refill", "_ensure_doh_block", "_ensure_mech_block", "_smart_geo_refresh", "_smart_load_cidrs",
                   "_panel_list_refresh", "_apply_routing_reset", "_smart_domain_refresh", "_ensure_p2p"):
            setattr(m, fn, (lambda *a, **k: ({}, {})) if fn == "_smart_domain_refresh" else (lambda *a, **k: None))
        m._cascade_local_routes = lambda cfg, _proc=None: []
        cfg = {"interfaces": {"wg0": {"conf": "/nonexistent"}}}
        m._iface_subnet = lambda c, n: {"wg0": "10.9.0.0/24"}.get(n, "")
        if plan is None:
            plan = {"devexit": [{"subnet": "10.9.0.0/24", "dev": "wgx9", "table": 7005, "killswitch": True, "scope": "rule",
                                 "egress_ip": "", "gw": ""}]} if entry and entry["via_iface"] == "wgx9" else {}
        m.reconcile_cascade(cfg, plan, {"entries": list(smart_entries), "p2p": {"action": "route", "entry": entry} if entry else None})
        recon.m = m
        return calls
    for via in ("wgx9", "swg_q"):
        c = recon({"table": 7005, "via_iface": via, "subnets": ["10.9.0.0/24"]})
        ok(["ip", "route", "replace", "default", "dev", via, "table", "7005"] in c,
           "[14] route via %s with no other rule: the node installs `default dev %s table 7005`" % (via, via))
        ok(any(x[:7] == ["ip", "rule", "add", "fwmark", "7005", "lookup", "7005"] for x in c), "[14] …and `fwmark 7005 lookup 7005`")
    c = recon({"table": 7005, "via_iface": "wgx9", "subnets": ["10.9.0.0/24"]}, dead=True)
    ok(["ip", "route", "replace", "default", "dev", "wgx9", "table", "7005"] not in c,
       "[14] a DEAD exit withholds the route (the table stays empty → P2P dropped, never sent another way)")

    # [17] down / absent devices are withheld — the P2P route and a routing rule's own smart exit alike
    for st in ("down", "absent"):
        c = recon({"table": 7005, "via_iface": "wgx9", "subnets": ["10.9.0.0/24"]}, link=st)
        ok(not any(x[:4] == ["ip", "route", "replace", "default"] and "wgx9" in x for x in c),
           "[17] P2P route via a %s device: the route is withheld, not attempted" % st)
        ok(any(x[:7] == ["ip", "rule", "add", "fwmark", "7005", "lookup", "7005"] for x in c),
           "[17] …while its fwmark rule stays (the way into the table, kill-switch reachable)")
        c = recon(None, link=st, smart_entries=[{"subnet": "10.9.0.0/24", "category": "x", "action": "exit", "via_iface": "swg_q", "table": 7004}])
        ok(not any(x[:4] == ["ip", "route", "replace", "default"] and "swg_q" in x for x in c),
           "[17] a routing rule's smart exit via a %s leg is withheld too (the band no longer churns)" % st)
    c = recon(None, link="up", smart_entries=[{"subnet": "10.9.0.0/24", "category": "x", "action": "exit", "via_iface": "swg_q", "table": 7004}])
    ok(["ip", "route", "replace", "default", "dev", "swg_q", "table", "7004"] in c, "[17] …and installed again the moment it is up")

    # [20] fwd / exit_ through a down leg: route withheld, rules kept
    PL = {"forward": [{"subnet": "10.9.0.0/24", "via_iface": "swg_q", "table": 7006}],
          "exit": [{"subnet": "10.40.0.0/24", "via_iface": "swg_q", "table": 7007, "egress_ip": "", "wan_iface": ""}]}
    for st in ("down", "absent"):
        c = recon(None, link=st, plan=PL)
        ok(not any(x[:3] == ["ip", "route", "replace"] and "swg_q" in x for x in c),
           "[20] fwd + exit_ via a %s leg: no route is attempted" % st)
        ok(["ip", "rule", "add", "from", "10.9.0.0/24", "lookup", "7006", "priority", "7006"] in c
           and ["ip", "rule", "add", "to", "10.40.0.0/24", "lookup", "7007", "priority", "7007"] in c,
           "[20] …and their rules stay (from S / to S)")
    c = recon(None, link="up", plan=PL)
    ok(["ip", "route", "replace", "default", "dev", "swg_q", "table", "7006"] in c
       and ["ip", "route", "replace", "10.40.0.0/24", "dev", "swg_q", "table", "7007"] in c, "[20] …and both installed once the leg is up")
    m0 = load(src)
    s1 = m0._cascade_want_sig([dict(PL["forward"][0], _noroute=True)], [dict(PL["exit"][0], _noroute=True)])
    s2 = m0._cascade_want_sig(PL["forward"], PL["exit"])
    ok(not any(x.startswith("T|7006|default") or x.startswith("T|7007|10.40") for x in s1)
       and any(x.startswith("T|7006|default") for x in s2) and any(x.startswith("T|7007|10.40") for x in s2),
       "[20] the drift signature leaves a withheld fwd/exit route out (and signs it once it is not)")
    c = recon(None, link="up", states={"wgx7": "dead"},
              smart_entries=[{"subnet": "10.9.0.0/24", "category": "x", "action": "exit", "via_iface": "wgx7", "table": 7008}])
    ok(not any(x[:3] == ["ip", "route", "replace"] and "wgx7" in x for x in c),
       "[20] a tunnel the exit judge calls dead is withheld even when the plan lists no devexit for it (one reader)")

    # [21] the trigger re-reads exactly what the last COMPLETED routing pass judged
    def commit(m):                                    # the main loop's step beside `last_route_sig = _route_sig`
        m._ROUTED["judged"] = m._ROUTED["pending"]
    st, ix = {"swg_q": "up", "wgx7": "dead", "wgx9": "up"}, {"swg_q": 11, "wgx7": 12, "wgx9": 13}
    P21 = dict(PL, devexit=[{"subnet": "10.9.0.0/24", "dev": "wgx9", "table": 7005, "killswitch": True, "scope": "rule",
                             "egress_ip": "", "gw": ""}])
    SM21 = {"entries": [{"subnet": "10.9.0.0/24", "category": "x", "action": "exit", "via_iface": "wgx7", "table": 7008}],
            "p2p": {"action": "route", "entry": {"table": 7005, "via_iface": "wgx9", "subnets": ["10.9.0.0/24"]}}}
    CFG = {"interfaces": {"wg0": {"conf": "/nonexistent"}}}
    recon(SM21["p2p"]["entry"], plan=P21, states=st, idx=ix, smart_entries=SM21["entries"])
    m2 = recon.m
    ok(set(m2._ROUTED["pending"]) == {"swg_q", "wgx7", "wgx9"} and m2._ROUTED["judged"] == {},
       "[21] the pass records every device it judged — cascade/exit leg, a rule's exit, the P2P route's device exit — and "
       "none of it is the trigger's reference until the pass completes (%s)" % sorted(m2._ROUTED["pending"]))
    commit(m2)
    ok(not m2._routed_devs_moved(), "[21] …and once committed nothing reads as moved (seed and re-read built alike)")
    st["wgx7"] = "up"
    ok(m2._routed_devs_moved(), "[21] a routing rule's exit whose dead verdict clears moves the trigger (not only the P2P device)")
    st["wgx7"] = "dead"; ix["wgx9"] = 99
    ok(m2._routed_devs_moved(), "[21] …and so does a device created again under its name (rebuilt in place: same state, new index)")
    ix["wgx9"] = 13
    ok(not m2._routed_devs_moved(), "[21] …and it settles once every device reads as judged (never sticky)")
    st["swg_q"] = "down"
    m2.reconcile_cascade(CFG, P21, SM21)              # judged "down" — then the pass raises before the main loop commits
    ok(m2._routed_devs_moved(), "[21] a pass that fails after judging leaves the reference as it was: the next sync retries it")
    commit(m2)
    ok(not m2._routed_devs_moved(), "[21] …and the pass that completes settles it")
    m2.reconcile_cascade(CFG, {}, {"entries": [], "p2p": None}); commit(m2)
    st["swg_q"] = "up"
    ok(not m2._ROUTED["judged"] and not m2._routed_devs_moved(),
       "[21] a pass that judges nothing leaves nothing to re-read (a device no longer used cannot trigger a pass every sync)")
    recon(None, plan=PL, states={"swg_q": ["down", "up"]}); commit(recon.m)
    ok(recon.m._ROUTED["judged"].get("swg_q", ("",))[0] == "down" and recon.m._routed_devs_moved(),
       "[21] the record is what the pass JUDGED: a leg that came up while the pass ran re-runs it on the next sync")
    m0 = load(src)
    _lo = os.path.isdir("/sys/class/net/lo")
    ok(all(m0._dev_seen(n) == ("absent", 0) for n in (None, "", "lo/.", "x" * 16, "..")) and (not _lo or m0._dev_seen("lo")[1] > 0),
       "[21] a name the link reader refuses is absent with no index — no sysfs path is built from it (lo itself has one)")
    tg = src[src.find("if (_route_sig != last_route_sig"):]
    tg = tg[:tg.find(":\n")]
    cm = src[src.find("last_route_sig = _route_sig; last_route_t = time.time()"):]
    ok("_routed_devs_moved()" in tg and "_route_dev_sig" not in src
       and cm.split("\n")[1].strip().startswith('_ROUTED["judged"] = _ROUTED["pending"]'),
       "[21] the main loop's trigger asks it (reading nothing of the reply), and commits what the pass judged beside last_route_sig")

    # [18] forwarding + loose rp_filter with only a P2P route
    sc = []
    recon({"table": 7005, "via_iface": "wgx9", "subnets": ["10.9.0.0/24"]}, sysctls=sc)
    ok(("net.ipv4.ip_forward", 1) in sc and ("net.ipv4.conf.wgx9.rp_filter", 2) in sc,
       "[18] a node whose only routing is a P2P route gets ip_forward and loose rp_filter on the route's device (%s)" % sc)

    # [15] route up / down
    m, b = fresh()
    E2 = {"table": 7006, "via_iface": "wgx0", "subnets": ["10.68.0.0/24"]}
    b.tables_rt["7006"] = ""
    m._ensure_p2p({"action": "route", "entry": E2}, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "down", "[15] empty table → route down (%s)" % m._P2P["route"])
    b.tables_rt["7006"] = "default dev wgx0 scope link\n"
    m._ensure_p2p({"action": "route", "entry": E2}, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "up", "[15] default route present → route up")
    b.tables_rt["7006"] = "prohibit default metric 4096\n"
    m._ensure_p2p({"action": "route", "entry": E2}, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "down", "[19] a kill-switch table (`prohibit default`) is NOT a way out → down")
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "" and m._P2P["route_dev"] == "", "[19] leaving route clears the state (no stale answer)")
    # [19] every report corrects "up" by the device
    m._P2P.update(on=True, state="ok", mode="route", route="up", route_dev="wgx0")
    m.run = lambda a, input_text=None, timeout=20: types.SimpleNamespace(returncode=1, stdout="", stderr="")
    for dev_state, want in (("down", "down"), ("dead", "down"), ("up", "up")):
        m._devexit_state = lambda d, _s=dev_state: _s
        with __import__("contextlib").suppress(Exception):
            st = m.smart_status()
        ok(((st or {}).get("p2p") or {}).get("route") == want, "[19] status report with the device %s → route %s" % (dev_state, want))

    # [16] the device name
    for bad in ('wgx"; drop', "a" * 16, "", "wg x", "wg/0"):
        ok(m._p2p_mode({"action": "route", "entry": {"table": 7006, "via_iface": bad}}) == "block", "[16] via_iface %r → block" % bad)

    # [5b] no route lookup per packet
    t2 = m._p2p_nft("block", [], [], [], True)
    cls2 = t2.split("chain cls {", 1)[1].split("\n  }", 1)[0].splitlines()
    gi = next(i for i, l in enumerate(cls2) if "ct original packets > 4 return" in l)
    ok(not any(l.strip() == "fib daddr type local return" for l in cls2[:gi]), "[5b] no `fib … return` before the packet gate in cls")
    g2 = t2.split("chain guard {", 1)[1]
    fl = [l for l in g2.splitlines() if "@flag" in l][0]
    ok(fl.index("@flag") < fl.index("fib"), "[5b] guard: the flagged-user lookup comes before the route lookup")

    # [9] retirement
    m, b = fresh()
    m._ensure_p2p(None, {}, {}, {"changed": 0, "errors": []})
    m._ensure_p2p(None, {}, {}, {"changed": 0, "errors": []})
    ok(sum(1 for a, _ in b.cmds if a[:3] == ["ipset", "destroy", "swgp_src"]) == 1, "[9] SWGP/swgp_src retired exactly once")
    n = len(b.cmds)
    m._ensure_p2p(None, {"10.68.0.0/24": ["smtp"]}, {}, {"changed": 0, "errors": []})
    ok(len(b.cmds) == n, "[10] a node with nothing to do runs no subprocess once it has looked (small fleets feel nothing)")
    m._ensure_p2p(None, {"10.67.0.0/24": ["torrents"]}, {}, {"changed": 0, "errors": []})
    ok("swg_p2p" in b.tables, "[10] …and still builds the moment a strict subnet appears")
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if old not in SRC:
                print("PLANT %-13s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(SRC.replace(old, new, 1))
            print("PLANT %-13s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(SRC)
    for x in f:
        print("FAIL", x)
    print("p2p_policy_selftest:", "PASS" if not f else "%d FAIL" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
