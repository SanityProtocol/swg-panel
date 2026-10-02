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
    "reply-judged": ('    L.append("    ct direction reply return")\n    L.append("    fib daddr type local return")', '    L.append("    fib daddr type local return")'),
    "rule-in-band": ("P2P_RULE_PRI = 6880 ", "P2P_RULE_PRI = 7050 "),
    "porthint":     ('            if "smtp" in cats:     els.append("tcp . 25")\n',
                     '            if "smtp" in cats:     els.append("tcp . 25")\n            if "torrents" in cats: els += ["udp . 6881-6889", "tcp . 6881-6889"]\n'),
    "gate-memo":    ('if have.returncode == 0 and cur == sig and " drop" in (have.stdout or ""):\n            return\n        _P2P["tbl"] = True',
                     'if have.returncode == 0 and cur == sig:\n            return\n        _P2P["tbl"] = True'),
    "rule-poll":    ('    if not on and _P2P["rule"] is False:\n        return\n', ''),
    "ctid-key":     ('"  set flag { typeof ip saddr; flags timeout; size 65535; }",', '"  set flag { typeof ip saddr; flags timeout; size 65535; }", "  set p2p_ct { typeof ct id; flags timeout; }",'),
    "probe-1line":  ('P2P_PROBE = "table inet swg_p2p_probe {\\n  chain c {\\n    meta l4proto udp @ih,0,64 0x0000041727101980 counter\\n  }\\n}\\n"',
                     'P2P_PROBE = "table inet swg_p2p_probe { chain c { meta l4proto udp @ih,0,64 0x0000041727101980 counter } }\\n"'),
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
        self.cmds, self.tables, self.rules, self.ih, self.wan = [], {}, [], ih, wan

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
        elif a[:4] == ["ip", "route", "show", "default"]:
            out = "default via 1.2.3.1 dev %s proto static\n" % self.wan
        elif a[:2] == ["ip", "rule"] and a[2] == "show":
            out = "".join(r + "\n" for r in self.rules)
        elif a[:3] == ["ip", "rule", "add"]:
            self.rules.append("%s:\tfrom all fwmark %s lookup main" % (a[-1], a[4]))
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
        ok(idx("ct direction reply return") < first_drop and idx("fib daddr type local return") < first_drop,
           "[5] %s: replies and traffic to the node return before any drop" % mode)
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
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")
    m.run = fake
    act = m._block_activity()
    ok(act.get("*", {}).get("torrent") == 7 and act["*"].get("torrent_ips") == ["10.68.0.7"], "[8] activity = sig + fan under *, flagged IPs")

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
