#!/usr/bin/env python3
"""Self-test: return by link on the node (docs/FAILOVER-PLAN.md §14.2, §14.7) — and nothing new anywhere else.

A failover pair's two members both send their shared subnet to one far node; the far node labels a connection with the
link it arrived on (ct mark bits 16-23) and returns its replies by that link. Every ct-mark restore must keep the label off
the packet mark and every writer on a later packet must keep it in the ct mark — but ONLY on a node holding a `ret` record.
A node without one must render exactly what the build before F2 rendered: that is the byte-identical gate.

  [1] off: P2P's table, the relay's env and container spec, the drift signature, the Kernel-SNI target, the restore — the
      reference build's text exactly
  [2] on: the restores mask the label, P2P's writers keep it, Kernel-SNI's CONNMARK keeps it, `--save-mark` keeps it
  [3] the `swg_rbl` table and the labels: one rule per link, the reply restore in prerouting and output, bad input refused
  [4] `_rbl_apply`: the rules, tables and nft it runs; steady passes run nothing new; off sweeps once and then never
  [5] a `to: false` record signs its backstop and nothing else
  [6] swg-relay: a member's half of the ephemeral range, the two halves disjoint and covering it

Run: python3 tests/rbl_selftest.py (0 = pass)
     --plant <x>  plant one defect and expect RED (exit 0 when caught):
       restore      the smart restore copies the whole ct mark on a node that returns by link
       p2p-keep     P2P's writer clears the label (full `ct mark set X`)
       connmark     Kernel SNI's CONNMARK clears the label
       savemark     Kernel SNI's `--save-mark` copies the label away
       sweep        a process restarted out of return by link does not sweep it (its rule and table stay)
       live         the band read never notes the rule (a restart out of it is never swept)
       steady       every steady pass rewrites the nft table
       env          every relay env file carries RELAY_SPORT (every node's relays restart)
       to-sig       a `to: false` record still signs its `to S` rule (the band rebuilds every pass)
       half         the two halves overlap
"""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = "a3104bff"                                    # origin/dev before F2
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
PLANTS = {
    "restore": ("noded", '    return ["ct", "mark", "and", "%#010x" % RBL_KEEP] if _RBL["on"] else ["ct", "mark"]',
                '    return ["ct", "mark"]'),
    "p2p-keep": ("noded", '    return ("ct mark set ct mark and %#010x or %#x" % (RBL_F, x)) if _RBL["on"] else ("ct mark set %#x" % x)',
                 '    return "ct mark set %#x" % x'),
    "connmark": ("noded", '    return ["CONNMARK", "--set-xmark", "%s/%#010x" % (T, RBL_KEEP)] if _RBL["on"] else ["CONNMARK", "--set-mark", T]',
                 '    return ["CONNMARK", "--set-mark", T]'),
    "savemark": ("noded", '"-j", "CONNMARK", "--save-mark", *(["--nfmask", "%#010x" % RBL_KEEP, "--ctmask", "%#010x" % RBL_KEEP]',
                 '"-j", "CONNMARK", "--save-mark", *([]'),
    "sweep": ("noded", '_RBL = {"on": False, "nft": None, "rsig": None, "swept": False, "live": False}',
              '_RBL = {"on": False, "nft": None, "rsig": None, "swept": True, "live": False}'),
    "live": ("noded", "            if pri == RBL_PRI:\n                _RBL[\"live\"] = True\n", ""),
    "steady": ("noded", '    if text != _RBL["nft"] or run(["nft", "list", "chain", "inet", RBL_TABLE, "lab"]).returncode != 0:',
               '    if True:'),
    "env": ("noded", '            + ("RELAY_SPORT=%d\\n" % e["half"] if e.get("half") else ""))', '            + ("RELAY_SPORT=%d\\n" % e.get("half", 0)))'),
    "to-sig": ("noded", '''        if e.get("to") is False:                       # returns by link only: no `to S` rule, no route (§14.7)
            continue
''', ""),
    "half": ("relay", "    return (lo, mid - 1) if half == 1 else (mid, hi)", "    return (lo, mid) if half == 1 else (mid, hi)"),
}
FAILS = []
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)
TMP = tempfile.mkdtemp(prefix="rbl-")


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def load(src, name):
    p = os.path.join(TMP, name)
    open(p, "w", encoding="utf-8").write(src)
    os.environ["SWG_NO_REEXEC"] = "1"
    ld = importlib.machinery.SourceFileLoader(name, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


def src(f, plant=None):
    s = open(os.path.join(ROOT, f), encoding="utf-8").read()
    if plant and PLANTS[plant][0] == {"swg-noded": "noded", "swg-relay": "relay"}[f]:
        a, b = PLANTS[plant][1:]
        assert s.count(a) == 1, "plant anchor missing (%s) — this run would FALSE-PASS" % plant
        s = s.replace(a, b, 1)
    return s


N = load(src("swg-noded", PLANT), "noded_cur")
R = load(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-noded"], capture_output=True, check=True).stdout.decode(), "noded_ref")
RL = load(src("swg-relay", PLANT), "relay_cur")
RBL0 = dict(N._RBL)                                 # a fresh process's state: [4] starts every scenario from it

G = lambda d: [{"name": "d", "subnets": d, "mark": 0x40000000, "oif": ["eth0"], "table": None},
               {"name": "r7001", "subnets": ["10.9.0.0/24"], "mark": 0x40001b59, "oif": ["wgx"], "table": 7001}]
P2P_CASES = [("route", [], [], [], True, {"mark": 0x40001b58, "table": 7000}), ("direct", [], ["eth0"], [], True, None),
             ("block", [], [], [], True, None), ("iface", [], [], [], True, None)]


def p2p_texts(m):
    out = [m._p2p_nft(*c[:5], route=c[5]) for c in P2P_CASES]
    out.append(m._p2p_nft("iface", [], [], [], True, groups=G(["10.8.0.0/24"])))
    return out


def sec1():
    print("[1] a node without a `ret` record: the reference build's text exactly")
    N._RBL["on"] = False
    check("[1] P2P's table, every mode and per-interface groups", p2p_texts(N) == p2p_texts(R))
    e = {"port": 5600, "gw": "10.8.0.1", "cc_up": "", "cc_cli": "", "mss": 1300, "up": 0, "half": 0}
    check("[1] the relay's env file", N._relay_env_text("awg0", e) == R._relay_env_text("awg0", e))
    check("[1] the relay's container spec", N._relay_docker_spec("awg0", e, 0.5) == R._relay_docker_spec("awg0", e, 0.5))
    ex = [{"subnet": "10.8.0.0/24", "via_iface": "swg_a", "table": 7001, "egress_ip": "", "wan_iface": ""}]
    fw = [{"subnet": "10.7.0.0/24", "via_iface": "swg_b", "table": 7002}]
    check("[1] the policy-routing drift signature", N._cascade_want_sig(fw, ex) == R._cascade_want_sig(fw, ex))
    check("[1] Kernel SNI's CONNMARK and the smart restore", N._rbl_connmark("7001") == ["CONNMARK", "--set-mark", "7001"]
          and N._rbl_restore() == ["ct", "mark"])
    check("[1] no record carries a label: nothing to lower", N._rbl_labels(ex) == {})


def sec2():
    print("[2] a node that returns by link: the label survives every writer and never reaches a packet mark")
    N._RBL["on"] = True
    try:
        t = p2p_texts(N)
        flat = "\n".join(t)
        check("[2] P2P's restore masks the label", "meta mark set ct mark and 0xff00ffff" in flat
              and "meta mark set ct mark\n" not in flat and "meta mark set ct mark " not in flat.replace("meta mark set ct mark and", ""))
        check("[2] P2P's writers keep it — no full `ct mark set X` left", "ct mark set ct mark and 0x00ff0000 or 0x40001b58" in flat
              and not any(l.strip().endswith(("ct mark set 0x40000000", "ct mark set 0x40001b58")) or "ct mark set 0x" in l for l in flat.splitlines()),
              [l for l in flat.splitlines() if "ct mark set 0x" in l][:3])
        check("[2] …and otherwise the text is the reference's", [x.replace("ct mark set ct mark and 0x00ff0000 or ", "ct mark set ")
                                                                 .replace("meta mark set ct mark and 0xff00ffff", "meta mark set ct mark")
                                                                 for x in t] == p2p_texts(R))
        check("[2] Kernel SNI's CONNMARK keeps it", N._rbl_connmark("7001") == ["CONNMARK", "--set-xmark", "7001/0xff00ffff"])
        check("[2] the smart restore masks it", N._rbl_restore() == ["ct", "mark", "and", "0xff00ffff"])
        _src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read() if not PLANT else src("swg-noded", PLANT)
        check("[2] Kernel SNI's `--save-mark` keeps it (masks both ways)",
              '"--save-mark", *(["--nfmask", "%#010x" % RBL_KEEP, "--ctmask", "%#010x" % RBL_KEEP]' in _src)
        check("[2] F and its complement cover the mark exactly, clear of the band, SNI and P2P bits",
              N.RBL_F | N.RBL_KEEP == 0xffffffff and N.RBL_F & N.RBL_KEEP == 0 and not N.RBL_F & (N.P2P_BIT | 0xffff))
    finally:
        N._RBL["on"] = False


def sec3():
    print("[3] the labels and the swg_rbl table")
    ex = [{"subnet": "10.8.0.0/24", "via_iface": "swg_a", "table": 7001, "ret": 6},
          {"subnet": "10.8.0.0/24", "via_iface": "swg_b", "table": 7001, "ret": 7, "to": False},
          {"subnet": "10.6.0.0/24", "via_iface": "swg_c", "table": 7003}]
    check("[3] one label per labelled link", N._rbl_labels(ex) == {"swg_a": 6, "swg_b": 7})
    bad = [{"via_iface": "swg_x", "ret": True}, {"via_iface": "swg_x", "ret": 0}, {"via_iface": "swg_x", "ret": 256},
           {"via_iface": "swg_x", "ret": "6"}, {"via_iface": 'a" accept; x', "ret": 6}, {"via_iface": "", "ret": 6}]
    check("[3] a bool, 0, 256, a string, a device name that is not one: no label", N._rbl_labels(bad) == {}, N._rbl_labels(bad))
    t = N._rbl_nft({"swg_a": 6, "swg_b": 7})
    check("[3] the first packet is labelled in prerouting after every writer (mangle + 20), one rule per link — one hook",
          '    iifname "swg_a" ct mark set ct mark or 0x00060000' in t and '    iifname "swg_b" ct mark set ct mark or 0x00070000' in t
          and "hook prerouting priority mangle + 20" in t and t.count("ct state new jump lab") == 1
          and "hook postrouting" not in t and "hook input" not in t, t)
    check("[3] the reply restore runs in prerouting AND in a route output chain", t.count(
        "ct direction reply ct mark and 0x00ff0000 != 0x0 meta mark set ct mark and 0x00ff0000") == 2
          and "type route hook output" in t and "hook prerouting" in t, t)
    check("[3] no map anywhere (nft 1.0.6 segfaults on them)", " map " not in t and "vmap" not in t)


class Run:
    def __init__(self, rules=""):
        self.calls, self.rules = [], rules

    def __call__(self, args, input_text=None, **k):
        self.calls.append(list(args) + ([input_text] if input_text else []))
        out = self.rules if args[:3] == ["ip", "rule", "show"] else ""
        rc = 1 if args[:3] == ["ip", "rule", "del"] and not self.rules else 0
        if args[:3] == ["ip", "rule", "del"]:
            self.rules = ""
        return subprocess.CompletedProcess(args, rc, out, "")


def sec4():
    print("[4] _rbl_apply")
    _run = N.run
    try:
        N._RBL.update(RBL0)
        r0 = Run(); N.run = r0; res = {"changed": 0, "errors": []}
        N._rbl_apply({}, lambda d: ("up", 3), res)
        check("[4] off, and no rule of ours at 6995 (the pass's own `ip rule show` says so): nothing is run — byte-identical",
              r0.calls == [] and res["changed"] == 0, r0.calls)
        N._RBL.update(RBL0)
        r = Run("6995:\tfrom all fwmark 0x60000/0xff0000 lookup 7106\n"); N.run = r; res = {"changed": 0, "errors": []}
        _sh = N.run(["ip", "rule", "show"])                    # what _live_band_prios reads, as the pass does
        N._RBL["live"] = "6995:" in _sh.stdout
        r.calls[:] = []
        N._rbl_apply({}, lambda d: ("up", 3), res)
        first = [c[:4] for c in r.calls]
        r2 = Run(); N.run = r2
        N._rbl_apply({}, lambda d: ("up", 3), res)
        check("[4] off after a restart out of it (its rule still there): one sweep — later passes run nothing",
              ["nft", "delete", "table", "inet"] in first and ["ip", "rule", "del", "pref"] in first and r2.calls == [], (first, r2.calls))
        rb = Run("0:\tfrom all lookup local\n6995:\tfrom all fwmark 0x60000/0xff0000 lookup 7106\n7001:\tfrom 10.8.0.0/24 lookup 7001\n")
        N.run = rb; _p = N._live_band_prios(); _l1 = N._RBL["live"]
        N.run = Run("0:\tfrom all lookup local\n"); N._live_band_prios(); _l0 = N._RBL["live"]
        check("[4] the band read notes our rule at 6995 (and only it), and never counts it in the band", _l1 and not _l0 and _p == [7001], (_l1, _l0, _p))
        N._RBL.update(RBL0)
        r3 = Run(); N.run = r3; res = {"changed": 0, "errors": []}
        N._rbl_apply({"swg_a": 6, "swg_b": 7}, lambda d: ("up", 3), res)
        cmds = [" ".join(map(str, c[:-1] if c[0] == "nft" and c[1] == "-f" else c)) for c in r3.calls]
        check("[4] on: each link's table holds its default route", "ip route replace default dev swg_a table 7106" in cmds
              and "ip route replace default dev swg_b table 7107" in cmds, cmds)
        check("[4] …a rule per label above the band, below the relay", "ip rule add fwmark 0x60000/0xff0000 lookup 7106 priority 6995" in cmds
              and "ip rule add fwmark 0x70000/0xff0000 lookup 7107 priority 6995" in cmds, cmds)
        check("[4] …and the nft table, with no error", any(c[:2] == ["nft", "-f"] for c in r3.calls) and not res["errors"], res)
        live = "6995:\tfrom all fwmark 0x60000/0xff0000 lookup 7106\n6995:\tfrom all fwmark 0x70000/0xff0000 lookup 7107\n"
        r4 = Run(live); N.run = r4; res = {"changed": 0, "errors": []}
        N._rbl_apply({"swg_a": 6, "swg_b": 7}, lambda d: ("up", 3), res)
        check("[4] a steady pass reads the rules back and changes nothing", res["changed"] == 0
              and not any(c[:3] in (["ip", "rule", "add"], ["ip", "route", "replace"]) or c[:2] == ["nft", "-f"] for c in r4.calls), r4.calls)
        r5 = Run(live); N.run = r5; res = {"changed": 0, "errors": []}
        N._rbl_apply({"swg_a": 6, "swg_b": 7}, lambda d: ("up", 9) if d == "swg_b" else ("up", 3), res)
        check("[4] a link recreated (a new index) gets its route again", [c for c in r5.calls if c[:3] == ["ip", "route", "replace"]]
              == [["ip", "route", "replace", "default", "dev", "swg_a", "table", "7106"],
                  ["ip", "route", "replace", "default", "dev", "swg_b", "table", "7107"]], r5.calls)
        r6 = Run(live); N.run = r6; res = {"changed": 0, "errors": []}
        N._rbl_apply({"swg_a": 6, "swg_b": 7}, lambda d: ("down", 9) if d == "swg_b" else ("up", 3), res)
        check("[4] a link down: its table is emptied — the reply falls through to `to S`",
              ["ip", "route", "flush", "table", "7107"] in r6.calls, r6.calls)
        r7 = Run(live); N.run = r7; res = {"changed": 0, "errors": []}
        N._rbl_apply({}, lambda d: ("up", 3), res)
        check("[4] off again: the nft table, the rules and both tables go",
              ["nft", "delete", "table", "inet", "swg_rbl"] in r7.calls and ["ip", "rule", "del", "pref", "6995"] in r7.calls
              and ["ip", "route", "flush", "table", "7106"] in r7.calls and ["ip", "route", "flush", "table", "7107"] in r7.calls, r7.calls)
    finally:
        N.run = _run
        N._RBL.update(RBL0)


def sec5():
    print("[5] a record that returns by link only")
    ex = [{"subnet": "10.8.0.0/24", "via_iface": "swg_b", "table": 7001, "ret": 7, "to": False},
          {"subnet": "10.8.0.0/24", "via_iface": "swg_a", "table": 7001, "ret": 6}]
    sig = N._cascade_want_sig([], ex)
    check("[5] its backstop is signed, its `to S` rule and route are not; the other member's are",
          "R|backstop|10.8.0.0/24|swg_b|7001" in sig and "T|7001|10.8.0.0/24|swg_b|" not in sig
          and "R|to|10.8.0.0/24|7001" in sig and "T|7001|10.8.0.0/24|swg_a|" in sig, sorted(sig))
    order = sorted(ex[::-1], key=lambda e: e.get("to") is not False)
    check("[5] lowered first, so its backstop precedes the other member's `to S` at the same priority",
          order[0]["via_iface"] == "swg_b")
    _s = src("swg-noded", PLANT)
    check("[5] reconcile_cascade sorts it first and installs no `to S` for it",
          "    exit_ = sorted(exit_, key=lambda e: e.get(\"to\") is not False)\n" in _s
          and "            if _to:\n                run([\"ip\", \"rule\", \"add\", \"to\", S, \"lookup\", T, \"priority\", T])" in _s)


def sec6():
    print("[6] swg-relay's port halves")
    p = os.path.join(TMP, "range")
    open(p, "w").write("32768\t60999\n")
    a, b = RL.sport_half(1, p), RL.sport_half(2, p)
    check("[6] the two halves are disjoint and cover the range", a and b and a[1] < b[0] and a[0] == 32768 and b[1] == 60999
          and a[1] + 1 == b[0], (a, b))
    check("[6] no half (0, None, 3): the kernel picks, as ever", RL.sport_half(0, p) is None and RL.sport_half(None, p) is None
          and RL.sport_half(3, p) is None)
    check("[6] the relay reads it from the env the unit already loads — the unit text is unchanged",
          'os.environ.get("RELAY_SPORT", "")' in src("swg-relay", PLANT)
          and N.RELAY_UNIT_TMPL == R.RELAY_UNIT_TMPL)
    e = {"port": 5600, "gw": "10.8.0.1", "cc_up": "", "cc_cli": "", "mss": 1300, "up": 0, "half": 2}
    check("[6] a pair member's env file and container spec carry its half",
          N._relay_env_text("awg0", e).endswith("RELAY_SPORT=2\n") and '"sport": 2' in N._relay_docker_spec("awg0", e, 0.5))


def main():
    for fn in (sec1, sec2, sec3, sec4, sec5, sec6):
        try:
            fn()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            check(fn.__name__ + " raised", False, ex)
    if PLANT:
        print("plant %s: %s" % (PLANT, "RED (caught)" if FAILS else "GREEN — NOT caught"))
        return 0 if FAILS else 1
    print("PASS" if not FAILS else "FAIL (%d)" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
