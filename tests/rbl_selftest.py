#!/usr/bin/env python3
"""Self-test: return by link on the node (docs/FAILOVER-PLAN.md §14.2, §14.7) — and nothing new anywhere else.

A failover pair's two members both send their shared subnet to one far node; the far node labels a connection with the
link it arrived on (ct mark bits 16-23) and returns its replies by that link. Every ct-mark restore must keep the label off
the packet mark and every writer on a later packet must keep it in the ct mark — but ONLY on a node holding a `ret` record.
A node without one must render exactly what the build before F2 rendered: that is the byte-identical gate.

  [1] off: P2P's table, the relay's env and container spec, the drift signature, the Kernel-SNI target, the restore — the
      reference build's text exactly
  [2] on: the restores mask the label, P2P's writers keep it, Kernel-SNI's CONNMARK keeps it, `--save-mark` keeps it
  [3] the `swg_rbl` table and the labels: an ip table, labelled per packet from the labelled links only, one rule per link,
      the reply restore in prerouting and output, bad input refused
  [4] `_rbl_apply`: the rules, tables and nft it runs; steady passes run nothing new; a route the kernel dropped comes back;
      off sweeps once and then never; a table whose load or removal failed is not lost
  [5] a `to: false` record signs its backstop and nothing else; one SNAT rule per subnet; the masks stay once set; the
      lowering is the pass's last step
  [6] swg-relay: a member's half of the ephemeral range, the two halves disjoint and covering it; never left

Run: python3 tests/rbl_selftest.py (0 = pass)
     --plant <x>  plant one defect and expect RED (exit 0 when caught):
       restore      the smart restore copies the whole ct mark on a node that returns by link
       p2p-keep     P2P's writer clears the label (full `ct mark set X`)
       connmark     Kernel SNI's CONNMARK clears the label
       savemark     Kernel SNI's `--save-mark` copies the label away
       uncat        the uncategorised counters skip a connection whose ct mark holds only a label
       sweep        a process restarted out of return by link does not sweep it (its rule and table stay)
       live         the band read never notes the rule (a restart out of it is never swept)
       steady       every steady pass rewrites the nft table
       readback     a route the kernel dropped (a link bounced, same index) is never put back
       orphan       a refused load forgets the table: a turn-off leaves it loaded
       first-only   only a connection's first packet is labelled (one that moved to the other member keeps the old link)
       env          every relay env file carries RELAY_HALF (every node's relays restart)
       to-sig       a `to: false` record still signs its `to S` rule (the band rebuilds every pass)
       snat         both records of a pair's subnet reconcile one SNAT tag (a duplicate, or a flip every pass)
       sticky       a turn-off unmasks the restores while labelled connections live on
       early        the labels are lowered before the pass renders the masked writers
       half         the two halves overlap
       fallback     after 16 misses the relay binds outside its half
       share        a half bind leaves its socket without SO_REUSEADDR, so the fallback cannot share its port (verify F46)
"""
import errno, importlib.machinery, importlib.util, json, os, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = "a3104bff"                                    # origin/dev before F2
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
PLANTS = {
    "restore": ("noded", '    return ["ct", "mark", "and", "%#010x" % RBL_KEEP] if _RBL["mask"] else ["ct", "mark"]',
                '    return ["ct", "mark"]'),
    "p2p-keep": ("noded", '    return ("ct mark set ct mark and %#010x or %#x" % (RBL_F, x)) if _RBL["mask"] else ("ct mark set %#x" % x)',
                 '    return "ct mark set %#x" % x'),
    "connmark": ("noded", '    return ["CONNMARK", "--set-xmark", "%s/%#010x" % (T, RBL_KEEP)] if _RBL["mask"] else ["CONNMARK", "--set-mark", T]',
                 '    return ["CONNMARK", "--set-mark", T]'),
    "savemark": ("noded", '    return ["--nfmask", "%#010x" % RBL_KEEP, "--ctmask", "%#010x" % RBL_KEEP] if _RBL["mask"] else []',
                 '    return []'),
    "uncat": ("noded", '    return ["and", "%#010x" % RBL_KEEP] if _RBL["mask"] else []', '    return []'),
    "sweep": ("noded", '_RBL = {"on": False, "mask": False, "nft": None, "rsig": None, "swept": False, "live": ()}',
              '_RBL = {"on": False, "mask": False, "nft": None, "rsig": None, "swept": True, "live": ()}'),
    "live": ("noded", "                _rbl_live.append(line)\n", "                pass\n"),
    "steady": ("noded", '    if text != _RBL["nft"] or not _rbl_nft_whole():', '    if True:'),
    "readback": ("noded", '            if not (len(live) == 1 and live[0][:3] == ["default", "dev", d]):   # iproute2 adds `scope link`',
                 '            if (d, L, (st, _ix)) not in (_RBL["rsig"] or ()):'),
    "orphan": ("noded", '            _RBL["nft"] = ""                                   # not None:', '            _RBL["nft"] = None                                   # not None:'),
    "first-only": ("noded", '"    iifname { %s } ct direction original jump lab" % devs', '"    ct state new jump lab"'),
    "env": ("noded", '            + ("RELAY_HALF=%d\\n" % e["half"] if e.get("half") else ""))', '            + ("RELAY_HALF=%d\\n" % e.get("half", 0)))'),
    "snat": ("noded", '        if _snat_by[e["subnet"]] is not e:\n            continue\n', ''),
    "sticky": ("noded", '    _RBL["mask"] = _RBL["mask"] or _RBL["on"] ', '    _RBL["mask"] = _RBL["on"] '),
    "early": ("noded", "    # IPTABLES (SNAT / FORWARD accept / MSS clamp) — always reconciled by tag (cheap, no-churn).\n",
              "    _rbl_apply(_rbl_lab, lambda d: _lst.get(d) or _dev_seen(d), res)\n"
              "    # IPTABLES (SNAT / FORWARD accept / MSS clamp) — always reconciled by tag (cheap, no-churn).\n"),
    "to-sig": ("noded", '''        if e.get("to") is False:                       # returns by link only: no `to S` rule, no route (§14.7)
            continue
''', ""),
    "half": ("relay", "    return (lo, mid - 1) if half == 1 else (mid, hi)", "    return (lo, mid) if half == 1 else (mid, hi)"),
    "fallback": ("relay", "            up.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n            up.bind((self.bind, self._pick()))\n",
                 "            up.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n            up.bind((self.bind, 0))\n"),
    "share": ("relay", "                    up.bind((self.bind, self._pick()))\n                    up.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n",
              "                    up.bind((self.bind, self._pick()))\n"),
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
    N._RBL.update(RBL0)
    check("[1] P2P's table, every mode and per-interface groups", p2p_texts(N) == p2p_texts(R))
    e = {"port": 5600, "gw": "10.8.0.1", "cc_up": "", "cc_cli": "", "mss": 1300, "up": 0, "half": 0}
    check("[1] the relay's env file", N._relay_env_text("awg0", e) == R._relay_env_text("awg0", e))
    check("[1] the relay's container spec", N._relay_docker_spec("awg0", e, 0.5) == R._relay_docker_spec("awg0", e, 0.5))
    ex = [{"subnet": "10.8.0.0/24", "via_iface": "swg_a", "table": 7001, "egress_ip": "", "wan_iface": ""}]
    fw = [{"subnet": "10.7.0.0/24", "via_iface": "swg_b", "table": 7002}]
    check("[1] the policy-routing drift signature", N._cascade_want_sig(fw, ex) == R._cascade_want_sig(fw, ex))
    check("[1] Kernel SNI's CONNMARK, its --save-mark, the smart restore and the uncategorised test",
          N._rbl_connmark("7001") == ["CONNMARK", "--set-mark", "7001"] and N._rbl_savemask() == []
          and N._rbl_restore() == ["ct", "mark"] and N._rbl_uncat() == [])
    check("[1] no record carries a label: nothing to lower", N._rbl_labels(ex) == {})


def sec2():
    print("[2] a node that returns by link: the label survives every writer and never reaches a packet mark")
    N._RBL.update(RBL0, on=True, mask=True)
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
        _src = src("swg-noded", PLANT)
        check("[2] Kernel SNI's `--save-mark` keeps it (masks both ways), through its helper",
              N._rbl_savemask() == ["--nfmask", "0xff00ffff", "--ctmask", "0xff00ffff"]
              and '"-j", "CONNMARK", "--save-mark", *_rbl_savemask()])' in _src)
        check("[2] the uncategorised counters test the mark without the label — a label is no category",
              N._rbl_uncat() == ["and", "0xff00ffff"] and _src.count('"ct", "mark", *_rbl_uncat(), "!=", "0x0", "return")') == 2)
        check("[2] F and its complement cover the mark exactly, clear of the band, SNI and P2P bits",
              N.RBL_F | N.RBL_KEEP == 0xffffffff and N.RBL_F & N.RBL_KEEP == 0 and not N.RBL_F & (N.P2P_BIT | 0xffff))
    finally:
        N._RBL.update(RBL0)


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
    check("[3] an ip table (IPv6 never walks it)", "table ip swg_rbl {" in t and "inet" not in t, t)
    check("[3] EVERY original-direction packet from a labelled link is labelled, in prerouting after every writer (mangle + 20)"
          " — the label follows the member a connection now comes through; nothing else enters `lab`",
          '    iifname { "swg_a", "swg_b" } ct direction original jump lab' in t and "ct state new" not in t
          and "hook prerouting priority mangle + 20" in t and "hook postrouting" not in t and "hook input" not in t, t)
    check("[3] one rule per link: the old label cleared, this link's set, and out",
          '    iifname "swg_a" ct mark set ct mark and 0xff00ffff or 0x00060000 return' in t
          and '    iifname "swg_b" ct mark set ct mark and 0xff00ffff or 0x00070000 return' in t, t)
    check("[3] the reply restore runs in prerouting AND in a route output chain", t.count(
        "ct direction reply ct mark and 0x00ff0000 != 0x0 meta mark set ct mark and 0x00ff0000") == 2
          and "type route hook output" in t and "hook prerouting" in t, t)
    check("[3] no map anywhere (nft 1.0.6 segfaults on them)", " map " not in t and "vmap" not in t)


class Run:
    """A fake kernel for `_rbl_apply`: the 6995 rules, the route tables, the nft table — each command acts on them."""
    def __init__(self, rules="", routes=None, nft=None, refuse=()):
        self.calls, self.rules, self.routes, self.nft, self.refuse = [], rules, dict(routes or {}), nft, set(refuse)

    def __call__(self, args, input_text=None, **k):
        a = list(args)
        self.calls.append(a + ([input_text] if input_text else []))
        rc, out, err = 0, "", ""
        if a[:3] == ["ip", "rule", "show"]:
            out = self.rules
        elif a[:3] == ["ip", "rule", "del"]:
            ls = [l for l in self.rules.splitlines() if l.startswith(a[4] + ":")]
            if ls:
                self.rules = "\n".join(l for l in self.rules.splitlines() if l != ls[0]) + "\n"
            else:
                rc = 2
        elif a[:3] == ["ip", "rule", "add"]:
            self.rules += "%s:\tfrom all fwmark %s lookup %s\n" % (a[-1], a[4], a[6])
        elif a[:4] == ["ip", "-4", "route", "show"] and a[4] == "table":
            out = (self.routes.get(a[5], "") if a[5] != "all" else
                   "".join(v.rstrip("\n") + " table %s\n" % t for t, v in self.routes.items()))
        elif a[:3] == ["ip", "route", "replace"]:
            self.routes[a[-1]] = "default dev %s scope link \n" % a[5]
        elif a[:3] == ["ip", "route", "flush"]:
            self.routes.pop(a[-1], None)
        elif a[:2] == ["nft", "-f"]:
            if "load" in self.refuse:
                rc, err = 1, "Error: refused"
            else:
                self.nft = input_text
        elif a[:3] == ["nft", "list", "table"]:
            if self.nft is None:
                rc, err = 1, "Error: No such file or directory"
            else:
                out = self.nft.split("table ip swg_rbl {\n", 2)[-1]
                out = "table ip swg_rbl {\n" + out
        elif a[:3] == ["nft", "delete", "table"]:
            if "delete" in self.refuse:
                rc, err = 1, "Error: Device or resource busy"
            elif self.nft is None:
                rc, err = 1, "Error: No such file or directory"
            else:
                self.nft = None
        return subprocess.CompletedProcess(args, rc, out, err)


def a_pass(r, labels, seen=lambda d: ("up", 3)):
    """One routing pass as reconcile_cascade runs it: the band read (`ip rule show`), then the lowering."""
    N.run = r
    N._live_band_prios()
    r.calls[:] = []
    res = {"changed": 0, "errors": []}
    N._rbl_apply(labels, seen, res)
    return res


def sec4():
    print("[4] _rbl_apply")
    _run, _gen = N.run, N._nft_genid
    N._nft_genid = lambda: None                                # every read is fresh (no ruleset generation here)
    L2 = {"swg_a": 6, "swg_b": 7}
    try:
        N._RBL.update(RBL0)
        r0 = Run(); res = a_pass(r0, {})
        check("[4] off, and no rule of ours at 6995 (the pass's own `ip rule show` says so): nothing is run — byte-identical",
              r0.calls == [] and res["changed"] == 0, r0.calls)
        N._RBL.update(RBL0)
        r = Run("6995:\tfrom all fwmark 0x60000/0xff0000 lookup 7106\n", routes={"7106": "default dev swg_a scope link \n"}, nft="")
        a_pass(r, {})
        first = [c[:4] for c in r.calls]
        a_pass(r, {})
        check("[4] off after a restart out of it (its rule still there): one sweep — later passes run nothing",
              ["nft", "delete", "table", "ip"] in first and ["ip", "rule", "del", "pref"] in first and r.calls == []
              and not r.rules.strip() and not r.routes, (first, r.calls, r.rules, r.routes))
        rb = Run("0:\tfrom all lookup local\n6995:\tfrom all fwmark 0x60000/0xff0000 lookup 7106\n7001:\tfrom 10.8.0.0/24 lookup 7001\n")
        N.run = rb; _p = N._live_band_prios(); _l1 = N._RBL["live"]
        N.run = Run("0:\tfrom all lookup local\n"); N._live_band_prios(); _l0 = N._RBL["live"]
        check("[4] the band read notes our rule at 6995 (and only it), and never counts it in the band",
              len(_l1) == 1 and "6995:" in _l1[0] and not _l0 and _p == [7001], (_l1, _l0, _p))
        N._RBL.update(RBL0)
        k = Run(); res = a_pass(k, L2)
        cmds = [" ".join(map(str, c[:-1] if c[0] == "nft" and c[1] == "-f" else c)) for c in k.calls]
        check("[4] on: each link's table holds its default route", "ip route replace default dev swg_a table 7106" in cmds
              and "ip route replace default dev swg_b table 7107" in cmds, cmds)
        check("[4] …a rule per label above the band, below the relay", "ip rule add fwmark 0x60000/0xff0000 lookup 7106 priority 6995" in cmds
              and "ip rule add fwmark 0x70000/0xff0000 lookup 7107 priority 6995" in cmds, cmds)
        check("[4] …and the nft table, with no error", any(c[:2] == ["nft", "-f"] for c in k.calls) and not res["errors"], res)
        res = a_pass(k, L2)
        check("[4] a steady pass reads the tables and rules back and changes nothing", res["changed"] == 0
              and not any(c[:3] in (["ip", "rule", "add"], ["ip", "route", "replace"]) or c[:2] == ["nft", "-f"] for c in k.calls), k.calls)
        check("[4] …and forks no `ip rule show` of its own (the band read has it)", not any(c[:3] == ["ip", "rule", "show"] for c in k.calls), k.calls)
        k.routes.pop("7107")                                   # the link bounced between two passes: same state, same index
        res = a_pass(k, L2)
        check("[4] a route the kernel dropped while state and index stayed the same comes back",
              [c for c in k.calls if c[:3] == ["ip", "route", "replace"]] == [["ip", "route", "replace", "default", "dev", "swg_b", "table", "7107"]],
              k.calls)
        res = a_pass(k, L2, lambda d: ("down", 9) if d == "swg_b" else ("up", 3))
        check("[4] a link down: its table is emptied — the reply falls through to `to S`",
              ["ip", "route", "flush", "table", "7107"] in k.calls and "7107" not in k.routes, k.calls)
        res = a_pass(k, L2)
        check("[4] …and up again: the route is back", k.routes.get("7107", "").startswith("default dev swg_b"), k.routes)
        a_pass(k, {})
        check("[4] off again: the nft table, the rules and both tables go",
              ["nft", "delete", "table", "ip", "swg_rbl"] in k.calls and k.nft is None and not k.rules.strip() and not k.routes,
              (k.calls, k.rules, k.routes))
        # a refused load, then a turn-off: the table it may have left is still removed (F13)
        N._RBL.update(RBL0)
        o = Run(); a_pass(o, L2)
        o.refuse.add("load"); a_pass(o, {"swg_a": 6, "swg_b": 8})
        o.refuse.clear(); a_pass(o, {})
        check("[4] a relabel refused, then off: the table loaded before is deleted all the same",
              o.nft is None and not o.rules.strip(), (o.nft, o.rules))
        # a removal that fails keeps the rules, so the table is never orphaned
        N._RBL.update(RBL0)
        d = Run(); a_pass(d, L2)
        d.refuse.add("delete"); res = a_pass(d, {})
        check("[4] off, and the table will not go: its rules stay and the pass says so",
              d.nft is not None and "6995:" in d.rules and res["errors"], (d.rules, res))
        d.refuse.clear(); a_pass(d, {})
        check("[4] …and the next pass removes both", d.nft is None and not d.rules.strip(), (d.nft, d.rules))
    finally:
        N.run, N._nft_genid = _run, _gen
        N._RBL.update(RBL0)


def sec5():
    print("[5] a record that returns by link only; the pass around it")
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
    # one SNAT rule per subnet, the serving member's (F14)
    _run, _rec = N.run, N._snat_reconcile_rule
    seen = []
    try:
        N.run = lambda a, **k: subprocess.CompletedProcess(a, 0, "", "")
        N._snat_reconcile_rule = lambda tag, S, des, nat: (seen.append((tag, des)), (False, None))[1]
        exs = [dict(ex[0], egress_ip="1.1.1.1", wan_iface=""), dict(ex[1], egress_ip="2.2.2.2", wan_iface="")]
        N._ensure_fwd_iptables([], sorted(exs, key=lambda e: e.get("to") is not False), "eth0", {"changed": 0, "errors": []})
    finally:
        N.run, N._snat_reconcile_rule = _run, _rec
    check("[5] a pair's two records of one subnet reconcile ONE SNAT rule — the serving member's address",
          seen == [("swg-fwd-snat:10.8.0.0/24", ("SNAT", "eth0", "2.2.2.2"))], seen)
    # the masks stay once set; the lowering comes after every writer
    check("[5] the masks are kept once a pass lowered it (labels outlive a turn-off in conntrack)",
          '    _RBL["mask"] = _RBL["mask"] or _RBL["on"] ' in _s)
    _rc = _s[_s.index("def reconcile_cascade("):]
    _rc = _rc[:_rc.index("\ndef ")]
    _call = "    _rbl_apply(_rbl_lab, lambda d: _lst.get(d) or _dev_seen(d), res)\n"
    check("[5] the lowering is the pass's last step, after the smart, Kernel SNI and P2P writers are rendered masked",
          _rc.count(_call) == 1 and _rc.index(_call) > max(_rc.rindex("_ensure_p2pfwd("), _rc.rindex("_ensure_smart_xtstring("),
                                                           _rc.rindex("_ensure_smart_nft(")))


class FakeSock:
    """Binds without SO_REUSEADDR always miss; IP_LOCAL_PORT_RANGE is refused (a kernel before 6.3)."""
    def __init__(self):
        self.reuse, self.bound = False, None

    def setsockopt(self, lvl, opt, v):
        if lvl == socket.IPPROTO_IP and opt == 51:
            raise OSError(92, "Protocol not available")
        if opt == socket.SO_REUSEADDR:
            self.reuse = True

    def bind(self, addr):
        if not self.reuse and addr[1]:
            raise OSError(errno.EADDRINUSE, "in use")
        self.bound = addr


def _free_window(n):
    """n consecutive ports free on 127.0.0.1, below the ephemeral range."""
    for base in range(20000, 30000, n):
        ss = []
        try:
            for q in range(base, base + n):
                x = socket.socket(); ss.append(x); x.bind(("127.0.0.1", q))
            return base, base + n - 1
        except OSError:
            pass
        finally:
            for x in ss:
                x.close()
    raise RuntimeError("no free port window")


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
          'os.environ.get("RELAY_HALF", "")' in src("swg-relay", PLANT)
          and N.RELAY_UNIT_TMPL == R.RELAY_UNIT_TMPL)
    e = {"port": 5600, "gw": "10.8.0.1", "cc_up": "", "cc_cli": "", "mss": 1300, "up": 0, "half": 2}
    check("[6] a pair member's env file and container spec carry its half",
          N._relay_env_text("awg0", e).endswith("RELAY_HALF=2\n") and '"half": 2' in N._relay_docker_spec("awg0", e, 0.5))
    _pr = RL._PRANGE[0]
    try:
        RL._PRANGE[0] = True
        rl = RL.Relay(0, "", bind="10.8.0.1", sport=b)
        fs = FakeSock(); rl._bind_up(fs)
        check("[6] an older kernel, and every port of the half in use: still bound inside the half (shared, never the other's)",
              fs.bound and fs.bound[0] == "10.8.0.1" and b[0] <= fs.bound[1] <= b[1] and RL._PRANGE[0] is False, fs.bound)
        # The real kernel (verify F46): Linux shares a port only when its holder has SO_REUSEADDR too. Every port of a
        # 4-port half held by the relay's own upstreams, live and then in TIME_WAIT: the next one still binds inside it.
        RL._PRANGE[0] = False
        q = _free_window(4)
        sa = socket.socket(); sa.bind(("127.0.0.1", 0)); sa.listen(64)
        sb = socket.socket(); sb.bind(("127.0.0.1", 0)); sb.listen(64)
        rl = RL.Relay(0, "", bind="127.0.0.1", sport=q); held, got, ports = [], [], set()
        try:
            for _ in range(400):
                if len({u.getsockname()[1] for u in held}) == 4:
                    break
                u = socket.socket()
                try:
                    rl._bind_up(u); u.connect(sa.getsockname()); held.append(u)
                except OSError:
                    u.close()
            ports = {u.getsockname()[1] for u in held}
            for mode in ("live", "timewait"):
                if mode == "timewait":
                    for u in held:
                        u.close()                               # the relay side closes first: TIME_WAIT
                u = socket.socket()
                try:
                    rl._bind_up(u); u.connect(sb.getsockname()); got.append((mode, u.getsockname()[1]))
                except OSError as ex:
                    got.append((mode, ex))
                u.close()
        finally:
            for x in held + [sa, sb]:
                x.close()
        check("[6] an older kernel, every port of the half held by live and then TIME_WAIT upstreams: the next shares one",
              ports == set(range(q[0], q[1] + 1))
              and [m for m, x in got if isinstance(x, int) and q[0] <= x <= q[1]] == ["live", "timewait"], got)
        RL._PRANGE[0] = True
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(64)
        rl = RL.Relay(0, "", bind="127.0.0.1", sport=b); got = []
        for _ in range(20):
            u = socket.socket(); rl._bind_up(u); u.connect(srv.getsockname()); got.append(u.getsockname()[1]); u.close()
        srv.close()
        check("[6] this kernel: every upstream port inside the half", all(b[0] <= x <= b[1] for x in got), got)
        check("[6] a relay with no half does not load `random`", not hasattr(RL.Relay(0, ""), "_pick")
              and "\nimport random" not in src("swg-relay", PLANT).split("class Relay")[0])
    finally:
        RL._PRANGE[0] = _pr


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
