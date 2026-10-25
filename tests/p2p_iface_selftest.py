#!/usr/bin/env python3
"""Self-test — per-interface torrent choice on the node (docs/IFACE-P2P-PICK-PLAN.md §4, 1.8.11 S11): swg-noded's `iface` mode.

  [1] GOLDEN: the four shipped modes (block / direct / route / legacy) render byte-identical to the tree before S11 —
      every `_p2p_nft` text of a matrix (strict, devices, mesh links, @ih, log, route), every `_ensure_p2p` pass's commands
      and state (two passes, wire objects incl. junk), and every `reconcile_cascade` route trace. A changed text reloads
      the table on every node on update (tests/fixtures/p2p_golden_modes.json, taken at the base commit it names)
  [2] the mode word: `iface` with any of entries / direct / block → iface; an empty one → legacy (an iface node today); an
      old node reads it as unknown → legacy (strict still dropped, the rest not checked: §3.3)
  [3] groups fail CLOSED and strictest wins: `block`, an entry that is no usable route (table outside the band, a device
      name that is no interface name) or that reuses a table, join strict; a group never holds a strict subnet or one an
      earlier group holds; v6 and junk are ignored; direct takes the main default device(s)
  [4] the table: legacy's scope widened (`!= @checked return`, auto-merge), each group marked with its own mark (hit, the
      flagged rules) and judged in guard only against its own devices; v6 and every non-group source leave guard at once;
      the node's own processes are not checked (`fib saddr type != local`); only block → no guard; and where `sudo -n`
      exists the real nft accepts it, overlapping prefixes included
  [5] the rules: one `fwmark M lookup T` per group at 6880, converged in one pass, compared as a SET (another listing order
      is no drift), rebuilt when one is missing, all removed when iface leaves
  [6] the route state: the first route group with no `default` line is reported down with its device; all up → up
  [7] each route entry's table is installed by reconcile_cascade (`default dev`, `fwmark T`), a down device withheld, a bad
      or repeated entry skipped
  [8] the report says mode "iface"
  [9] on the real kernel (throwaway namespaces, `sudo -n`; said SKIPPED without): a client in a Direct group sends a DHT
      query and then a new high-port flow — both leave by the WAN; the same client in a route group whose device is not
      the WAN — both dropped (the signature in sig, the flagged flow in gflag), never out the WAN; a client outside every
      group — both leave, never flagged (not checked)

Run: python3 tests/p2p_iface_selftest.py        (0 = pass)
     --perturb    plant each defect in turn → every one must go RED (exit 0 when all are caught)
     --write-golden   (once, on the base tree) write the fixture
"""
import hashlib, json, os, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2p_policy_selftest as base   # Box, load: the stand-in box the node's P2P gate already uses

ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = base.NODED
SRC = base.SRC
GOLDEN = os.path.join(HERE, "fixtures", "p2p_golden_modes.json")

PLANTS = {   # name: (old text, planted text) — each re-introduces a defect the checks exist for
    "golden-legacy":  ('    if routes or grp:                                         # our own restore', '    if routes or grp or mode == "legacy":                     # our own restore'),
    "rule-stale":     ('    ok = on and len(cur) == len(wants) and', '    ok = on and len(cur) >= 1 and'),
    "mode-never":     ('        return "iface" if any(p2p.get(k) for k in ("entries", "direct", "block")) else "legacy"', '        return "legacy"'),
    "bad-entry-open": ('    for e in bad:\n        strict.extend(v4(e.get("subnets")))', '    for e in bad:\n        pass'),
    "table-reuse":    ('        if u and int(u["table"]) not in taken:', '        if u:'),
    "block-ignored":  ('    strict.extend(v4(p2p.get("block")))\n', ''),
    "strict-routed":  ('        subs = sorted({n for n in v4(lst) if n not in seen})', '        subs = sorted(set(v4(lst)))'),
    "no-automerge":   ('  set checked { typeof ip saddr; flags interval; auto-merge; elements', '  set checked { typeof ip saddr; flags interval; elements'),
    "guard-all":      ('        L.append("    ip saddr @flag jump gflag")', '        L.append("    jump gflag")'),
    "gflag-skip":     ('        L.append("    ip saddr @flag jump gflag")\n', ''),
    "sig-ungrouped":  ('            L.append("    ip saddr @grouped meta l4proto { tcp, udp } jump sig")', '            L.append("    meta l4proto { tcp, udp } jump sig")'),
    "sig-local":      ('l4, m, goif(g)))', 'l4, m, goif(g).replace("oifname", "fib saddr type local oifname") or "fib saddr type local "))'),
    "group-oif":      ('    goif = lambda g: "oifname != { %s } "', '    goif = lambda g: "" and "oifname != { %s } "'),
    "rule-ordered":   ('all(any(("fwmark %#x lookup %s" % w) in ln for ln in cur) for w in wants)', 'all(("fwmark %#x lookup %s" % w) in ln for ln, w in zip(cur, wants))'),
    "route-first":    ('                if not _P2P["route"] or (not _up and _P2P["route"] == "up"):', '                if not _P2P["route"]:'),
    "recon-borrowed": ('    if _pi.get("action") == "iface":                          # …and each', '    if False:                          # …and each'),
}


def _h(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()


def golden(src):
    """case name → digest, for every shipped-mode input this gate fixes."""
    out = {}
    m = base.load(src)
    BIT = m.P2P_BIT
    for mode in ("block", "direct", "route", "legacy"):
        for si, strict in enumerate(([], ["10.67.0.0/24"], ["10.67.0.0/24", "10.69.0.0/24"])):
            for oi, oif in enumerate(([], ["eth0"], ["eth0", "eth1"])):
                for ni, nofan in enumerate(([], ["10.99.0.0/30"])):
                    for ih in (True, False):
                        for logged in (True, False):
                            routes = ((None,) if mode != "route" else
                                      (None, {"mark": 7003 | BIT, "routable": []}, {"mark": 7003 | BIT, "routable": ["10.68.0.0/24"]}))
                            for ri, rt in enumerate(routes):
                                k = "nft|%s|s%d|o%d|n%d|ih%d|log%d|r%d" % (mode, si, oi, ni, ih, logged, ri)
                                out[k] = _h(m._p2p_nft(mode, strict, oif, nofan, ih, rt, logged=logged))
    E = {"table": 7003, "via_iface": "wgx0", "subnets": ["10.68.0.0/24", "10.67.0.0/24"]}
    wires = {"none": None, "block": {"action": "block"}, "direct": {"action": "direct"}, "route": {"action": "route", "entry": E},
             "route-bad": {"action": "route", "entry": {"table": 6000, "via_iface": "x"}}, "route-noentry": {"action": "route"},
             "junk": {"action": "zzz"}, "notdict": "block"}
    mechs = {"m0": {}, "mstrict": {"10.67.0.0/24": ["torrents"]}, "msmtp": {"10.67.0.0/24": ["smtp"]}}
    mm = base.load(src)
    p0 = json.loads(json.dumps(mm._P2P))                     # one load, the state reset per case (a load is most of the cost)
    for wn, w in wires.items():
        for mn, mech in mechs.items():
            for ih in (True, False):
                for rt in ("", "default dev wgx0 scope link\n"):
                    mm._P2P.clear(); mm._P2P.update(json.loads(json.dumps(p0))); b = base.Box(ih=ih)
                    mm.run = b.run; mm.GEO_DIR = tempfile.mkdtemp(); mm._relay_links = lambda cfg: ()
                    b.tables_rt["7003"] = rt
                    trace = []
                    for _ in range(2):
                        res = {"changed": 0, "errors": []}
                        b.cmds[:] = []
                        mm._ensure_p2p(w, mech, {}, res)
                        st = {k: v for k, v in mm._P2P.items() if k != "ih"}
                        trace.append([[(a, i) for a, i in b.cmds], res, st])
                    out["ensure|%s|%s|ih%d|rt%d" % (wn, mn, ih, bool(rt))] = _h(trace)
    for via in ("wgx9", "swg_q"):
        for link in ("up", "down", "dead"):
            out["recon|%s|%s" % (via, link)] = _h(_recon(src, {"action": "route", "entry": {"table": 7005, "via_iface": via, "subnets": ["10.9.0.0/24"]}}, link))
    out["recon|none|up"] = _h(_recon(src, None, "up"))
    out["recon|block|up"] = _h(_recon(src, {"action": "block"}, "up"))
    out["recon|direct|up"] = _h(_recon(src, {"action": "direct"}, "up"))
    return out


def _recon(src, p2p, link, plan=None):
    """reconcile_cascade with everything around it stubbed (p2p_policy_selftest [14]'s harness): the commands it runs."""
    m = base.load(src)
    calls = []
    m._dev_link_state = lambda dev: (link if link != "dead" else "up") if dev in ("wgx9", "swg_q", "wgx8") else "up"
    def rr(a, input_text=None, timeout=20):
        calls.append(list(a))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    m.run = rr
    m.GEO_DIR = tempfile.mkdtemp()
    m._devexit_state = lambda dev: link if dev in ("wgx9", "swg_q", "wgx8") else "up"
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
                             "egress_ip": "", "gw": ""}]}
    m.reconcile_cascade(cfg, plan, {"entries": [], "p2p": p2p})
    return calls


def run_checks(src):
    fails = []
    def ok(cond, what):
        if not cond:
            fails.append(what)

    # [1] golden
    want = json.load(open(GOLDEN))["cases"]
    got = golden(src)
    diff = sorted(k for k in want if got.get(k) != want[k])
    ok(set(got) >= set(want) and not diff,
       "[1] the four shipped modes render byte-identical to the base tree (%d case(s) differ: %s)" % (len(diff), ", ".join(diff[:4])))
    m = base.load(src)
    BIT = m.P2P_BIT
    # [2]
    ok(m._p2p_mode({"action": "iface", "direct": ["10.1.0.0/24"]}) == "iface" and m._p2p_mode({"action": "iface", "block": ["10.1.0.0/24"]}) == "iface"
       and m._p2p_mode({"action": "iface", "entries": [{"table": 7003, "via_iface": "w"}]}) == "iface", "[2] iface with choices → iface")
    ok(m._p2p_mode({"action": "iface"}) == "legacy" and m._p2p_mode({"action": "iface", "direct": []}) == "legacy", "[2] an empty iface → legacy")

    # [3]
    m, b = fresh(src)
    st = ["10.67.0.0/24"]
    E = lambda T, via, *s: {"table": T, "via_iface": via, "subnets": list(s)}
    g = m._p2p_groups({"entries": [E(7003, "wgx0", "10.68.0.0/24", "10.67.0.0/24", "fd00::/64"), E(6000, "wgx0", "10.71.0.0/24"),
                                   E(7004, 'wg"x', "10.73.0.0/24"), E(7003, "swg_q", "10.74.0.0/24"), E(7005, "swg_q", "10.69.0.0/24", "10.75.0.0/24"),
                                   "junk"],
                       "direct": ["10.69.0.0/24", "zz"], "block": ["10.72.0.0/24", "10.68.0.0/24"]}, st)
    G = {x["name"]: x for x in g}
    ok(st == sorted(["10.67.0.0/24", "10.68.0.0/24", "10.71.0.0/24", "10.72.0.0/24", "10.73.0.0/24", "10.74.0.0/24"]),
       "[3] block, a bad entry, a bad device name and a reused table join strict (%s)" % st)
    ok("r7003" not in G and G.get("r7005", {}).get("subnets") == ["10.75.0.0/24"] and G.get("d", {}).get("subnets") == ["10.69.0.0/24"],
       "[3] no group holds a strict subnet or one an earlier group holds; v6 / junk ignored (%s)" % g)
    ok(G.get("d", {}).get("oif") == ["eth0"] and G["d"]["mark"] == BIT and G["d"]["table"] is None
       and G.get("r7005", {}).get("oif") == ["swg_q"] and G["r7005"]["mark"] == 7005 | BIT, "[3] marks and devices per group")

    # [4]
    t = m._p2p_nft("iface", st, [], [], True, groups=g)
    cls = t.split("chain cls {", 1)[1].split("\n  }", 1)[0].splitlines()
    gu = [l for l in t.split("chain guard {", 1)[1].split("\n  }", 1)[0].splitlines() if l.strip()] if "chain guard {" in t else []
    gf = [l for l in t.split("chain gflag {", 1)[1].split("\n  }", 1)[0].splitlines() if l.strip()] if "chain gflag {" in t else []
    sig = [l for l in t.split("chain sig {", 1)[1].split("\n  }", 1)[0].splitlines() if l.strip()] if "chain sig {" in t else []
    ok("    ip saddr != @checked return" in cls and "    ip saddr != @strict return" not in cls
       and "flags interval; auto-merge; elements = { " in t.split("set checked {", 1)[1].split("\n", 1)[0], "[4] legacy's scope, widened to @checked (auto-merge)")
    ok(all(any(("ip saddr @g_%s" % x["name"]) in l and l.endswith("meta mark set %#x ct mark set %#x" % (x["mark"], x["mark"])) for l in cls)
           for x in g) and "ip saddr @g_d meta l4proto udp meta mark set %#x" % BIT in t, "[4] each group carries its own mark (cls + hit)")
    ok([l.strip() for l in gu[1:]] == ['oifname "lo" return', "ct direction reply return", "meta nfproto ipv6 return", "ip saddr @flag jump gflag",
                                         "ct original packets > 4 return", "ip saddr @grouped meta l4proto { tcp, udp } jump sig"],
       "[4] guard: one set lookup per established v4 packet (@flag); @grouped only on packets 1-4; no held check (cls has it) (%s)" % gu[1:])
    ok(len(gf) == len(g) and any(l.strip().startswith("ip saddr @g_d meta l4proto") and 'oifname != { "eth0" }' in l and l.endswith("drop") for l in gf)
       and any(l.strip().startswith("ip saddr @g_r7005 meta l4proto") and 'oifname != { "swg_q" }' in l for l in gf), "[4] each group judged against its own devices (%s)" % gf)
    ok(sig and all("fib saddr type != local jump gdrop" in l for l in sig) and all("fib saddr type local" not in l for l in sig)
       and len(sig) == len(m._P2P_SIGS) * len(g), "[4] the node's own processes are not checked; one sig line per signature and group")
    t0 = m._p2p_nft("iface", st, [], [], True, groups=[])
    ok("chain guard" not in t0 and "ip saddr != @checked return" in t0, "[4] only block / strict → no guard (legacy's shape)")
    import shutil, subprocess as _sp
    if shutil.which("sudo") and _sp.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        ov = m._p2p_nft("iface", ["10.0.0.0/16"], [], ["10.255.0.2/31"], True, groups=[dict(G["r7005"], subnets=["10.0.1.0/24"])], logged=False)
        for name, tx in (("groups", t), ("block only", t0), ("overlapping prefixes", ov), ("no @ih", m._p2p_nft("iface", st, [], [], False, groups=g))):
            r = _sp.run(["sudo", "-n", "nft", "-c", "-f", "-"], input=tx, capture_output=True, text=True)
            ok(r.returncode == 0, "[4] the real nft accepts the iface table, %s (%s)" % (name, (r.stderr or "").strip()[:120]))
    else:
        print("  [4] real-nft check SKIPPED — no passwordless sudo here")

    # [5]
    m, b = fresh(src)
    W = {"action": "iface", "entries": [E(7005, "swg_q", "10.75.0.0/24"), E(7003, "wgx0", "10.68.0.0/24")], "direct": ["10.69.0.0/24"]}
    b.tables_rt["7003"] = b.tables_rt["7005"] = "default dev x scope link\n"
    res = {"changed": 0, "errors": []}
    m._ensure_p2p(W, {}, {}, res)
    want = sorted(["6880:\tfrom all fwmark %#x lookup main" % BIT, "6880:\tfrom all fwmark %#x lookup 7003" % (7003 | BIT),
                   "6880:\tfrom all fwmark %#x lookup 7005" % (7005 | BIT)])
    ok(sorted(b.rules) == want, "[5] one rule per group in one pass (%s)" % b.rules)
    b.rules.reverse(); b.cmds[:] = []
    m._ensure_p2p(W, {}, {}, {"changed": 0, "errors": []})
    ok(not any(a[:3] in (["ip", "rule", "del"], ["ip", "rule", "add"]) for a, _ in b.cmds), "[5] another listing order is no drift")
    b.rules[:] = b.rules[:-1]
    m._ensure_p2p(W, {}, {}, {"changed": 0, "errors": []})
    ok(sorted(b.rules) == want, "[5] a missing rule is rebuilt (%s)" % b.rules)
    W2 = dict(W, entries=W["entries"][:1])
    m._ensure_p2p(W2, {}, {}, {"changed": 0, "errors": []})
    ok(sorted(b.rules) == [w for w in want if "lookup 7003" not in w], "[5] a group gone takes its rule with it (%s)" % b.rules)
    m._ensure_p2p(W, {}, {}, {"changed": 0, "errors": []})
    m._ensure_p2p({"action": "block"}, {}, {}, {"changed": 0, "errors": []})
    ok(not any(r.startswith("6880:\tfrom all fwmark %#x" % (7003 | BIT)) for r in b.rules) and len([r for r in b.rules if r.startswith("6880:")]) == 0,
       "[5] leaving iface removes every group's rule (%s)" % b.rules)

    # [6]
    m, b = fresh(src)
    b.tables_rt["7005"], b.tables_rt["7003"] = "default dev swg_q scope link\n", "prohibit default metric 4096\n"   # the 2nd group is down
    m._ensure_p2p(W, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "down" and m._P2P["route_dev"] == "wgx0", "[6] the first group with no way out is said (%s %s)" % (m._P2P["route"], m._P2P["route_dev"]))
    b.tables_rt["7003"] = "default dev wgx0 scope link\n"
    m._ensure_p2p(W, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "up", "[6] all up → up")
    m._ensure_p2p({"action": "iface", "direct": ["10.69.0.0/24"]}, {}, {}, {"changed": 0, "errors": []})
    ok(m._P2P["route"] == "" and m._P2P["mode"] == "iface", "[6] no route group → no route state")

    # [7]
    PIF = {"action": "iface", "entries": [E(7005, "swg_q", "10.9.0.0/24"), E(6000, "wgx8", "10.9.0.0/24"), E(7005, "wgx8", "10.10.0.0/24"),
                                          E(7006, "wgx8", "10.11.0.0/24")]}
    c = _recon(src, PIF, "up", plan={})
    ok(["ip", "route", "replace", "default", "dev", "swg_q", "table", "7005"] in c and ["ip", "route", "replace", "default", "dev", "wgx8", "table", "7006"] in c
       and any(x[:7] == ["ip", "rule", "add", "fwmark", "7006", "lookup", "7006"] for x in c), "[7] each route entry's table is installed")
    ok(not any(x[:4] == ["ip", "route", "replace", "default"] and x[-1] in ("6000",) for x in c)
       and ["ip", "route", "replace", "default", "dev", "wgx8", "table", "7005"] not in c, "[7] a bad or repeated entry installs nothing")
    c = _recon(src, PIF, "down", plan={})
    ok(not any(x[:4] == ["ip", "route", "replace", "default"] for x in c) and any(x[:7] == ["ip", "rule", "add", "fwmark", "7005", "lookup", "7005"] for x in c),
       "[7] a down device's route is withheld, its fwmark rule kept")

    # [8]
    m, b = fresh(src)
    m._ensure_p2p({"action": "iface", "direct": ["10.69.0.0/24"]}, {}, {}, {"changed": 0, "errors": []})
    st8 = None
    m.run = lambda a, input_text=None, timeout=20: types.SimpleNamespace(returncode=1, stdout="", stderr="")
    with __import__("contextlib").suppress(Exception):
        st8 = m.smart_status()
    ok(((st8 or {}).get("p2p") or {}).get("mode") == "iface", "[8] the report says mode iface (%s)" % ((st8 or {}).get("p2p")))

    # [9]
    if _sp.run(["sudo", "-n", "true"], capture_output=True).returncode == 0 and shutil.which("unshare"):
        m9 = base.load(src)
        G9 = lambda name, sub, mark, oif, T: [{"name": name, "subnets": [sub], "mark": mark, "oif": oif, "table": T}]
        for name, groups, want in (("a Direct group", G9("d", "10.9.0.0/24", BIT, ["eth0"], None), (2, 0, 1)),
                                   ("a route group via another device", G9("r7003", "10.9.0.0/24", 7003 | BIT, ["wgx0"], 7003), (0, 2, 1)),
                                   ("outside every group", G9("d", "10.62.0.0/24", BIT, ["eth0"], None), (2, 0, 0))):
            got = _wire_iface(m9._p2p_nft("iface", ["10.67.0.0/24"], [], [], True, groups=groups, logged=False))
            if got is None:
                print("  SKIPPED [9] real-kernel %s — the throwaway namespace could not be set up here" % name)
                continue
            ok(got == want, "[9] on the real kernel, the client in %s: (left by the WAN, dropped, flagged) = %s, want %s" % (name, got, want))
    else:
        print("  SKIPPED [9] real-kernel datapath — no `sudo -n` here")
    return fails


WIRE_IF = base.WIRE.split("nft add element")[0] + r'''
nft -f - <<'EOF'
table inet obs {
  counter left {}
  chain p {
    type filter hook postrouting priority 100; policy accept;
    oifname "eth0" ip saddr 10.9.0.2 counter name left
  }
}
EOF
nsenter -t "$CPID" -n python3 -c '
import os, socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("10.9.0.2", 50001))
s.sendto(b"d1:ad2:id20:" + os.urandom(20) + b"9:info_hash20:" + os.urandom(20) + b"e1:q9:get_peers1:t2:aa1:y1:qe", ("198.51.100.7", 6881))
time.sleep(0.2)
s.sendto(b"\x00" * 40, ("198.51.100.8", 40000))
'
sleep 0.3
echo "LEFT $(nft list counter inet obs left | grep -o 'packets [0-9]*' | grep -o '[0-9]*')"
echo "DROPPED $(nft list counter inet swg_p2p dropped | grep -o 'packets [0-9]*' | grep -o '[0-9]*')"
echo "FLAG $(nft list set inet swg_p2p flag | grep -c '10\.9\.0\.2')"
kill $CPID 2>/dev/null
'''


def _wire_iface(table):
    """(left by the WAN, dropped, flagged) for the client 10.9.0.2's DHT query + one flagged flow, or None (not set up)."""
    import subprocess as sp
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(table)
    try:
        r = sp.run(["sudo", "-n", "unshare", "-n", "bash", "-s", f.name], input=WIRE_IF, capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    finally:
        os.unlink(f.name)
    out = {ln.split(" ", 1)[0]: ln.split(" ", 1)[1].strip() for ln in (r.stdout or "").splitlines() if " " in ln}
    try:
        return int(out["LEFT"]), int(out["DROPPED"]), int(out["FLAG"])
    except (KeyError, ValueError):
        return None


def fresh(src, ih=True):
    m = base.load(src); b = base.Box(ih=ih)
    m.run = b.run
    m.GEO_DIR = tempfile.mkdtemp()
    m._relay_links = lambda cfg: ()
    return m, b


def main():
    if "--write-golden" in sys.argv:
        rev = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", ROOT, "diff", "--quiet", "HEAD", "--", "swg-noded"]).returncode != 0
        if dirty:
            print("swg-noded differs from HEAD — the golden texts are taken on the base tree only"); return 1
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        cases = golden(SRC)
        json.dump({"base": rev, "cases": cases}, open(GOLDEN, "w"), indent=0, sort_keys=True)
        print("wrote %d cases at %s" % (len(cases), rev)); return 0
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if old not in SRC:
                print("PLANT %-16s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(SRC.replace(old, new, 1))
            print("PLANT %-16s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(SRC)
    for x in f:
        print("FAIL", x)
    print("p2p_iface_selftest:", "PASS" if not f else "%d FAIL" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
