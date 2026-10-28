#!/usr/bin/env python3
"""Self-test — a port conflict excludes the edited server by IDENTITY, never by port number (pool-doors backlog ⭐).

_node_ports counts every claim on a node, the record's and what the node reports. A WDTT / csqtt server (or a turn-proxy,
an interface) whose report differs from its record — a move not applied yet, a restore with no record — read as a clash
with itself; leaving its reported ports out by number instead (pool-doors round 2) let a stale report hide another holder's
claim and the RAW-IP reservation (verify F17). Now the edited holder is left out by who it is.

    [1] _node_ports(skip=…) leaves out exactly that holder's claims — record and report — for each kind; nobody else's
    [2] _port_conflict(me=…): a server moved but not converged saves back onto its reported port; another holder on that
        port is still a clash; a port it holds in its record is tolerated (as before); RAW-IP 56003 stays reserved unless
        the record holds it; without `me` every caller reads as before
    [3] the interface update, turn-proxy edit, WDTT and csqtt saves pass their own identity

Run: python3 tests/port_identity_selftest.py     (0 = pass)
     --perturb   plant each defect in turn → every one must go RED (exit 0 when all are caught)
"""
import ast, os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PSRC = open(PANEL, encoding="utf-8").read()

PLANTS = {   # name: (old text, planted text)
    "skip-ignored":  ('        if who is not None and who == skip:\n            return\n', ''),
    "skip-unpassed": ('    return _node_ports(deps, nodes, nid, skip=me).get(port)', '    return _node_ports(deps, nodes, nid).get(port)'),
    "snapwdtt-noid": ('    for ifn, w in ents(snap.get("wdtt")):\n        add(tail(w.get("listen")), ifn + " (WDTT)", ("wdtt", ifn))',
                      '    for ifn, w in ents(snap.get("wdtt")):\n        add(tail(w.get("listen")), ifn + " (WDTT)")'),
    "snapcsqtt-noid": ('    for ifn, c in ents(snap.get("csqtt")):\n        add(tail(c.get("listen")), ifn + " (csqtt)", ("csqtt", ifn))',
                       '    for ifn, c in ents(snap.get("csqtt")):\n        add(tail(c.get("listen")), ifn + " (csqtt)")'),
    "snapturn-noid": ('        add(tail(tp.get("listen")), tp.get("service") or "a turn-proxy", ("turn", tp.get("service")))',
                      '        add(tail(tp.get("listen")), tp.get("service") or "a turn-proxy")'),
    "snapif-noid":   ('        add((blk.get("meta") or {}).get("listen_port"), ifn, ("iface", ifn))', '        add((blk.get("meta") or {}).get("listen_port"), ifn)'),
    "raw-open":      ('    if port == WDTT_RAW_PORT:\n        return _wdtt_raw_holder', '    if False:\n        return _wdtt_raw_holder'),
    "door-wdtt":     ('own=_own, me=("wdtt", iface))', 'own=_own)'),
    "door-csqtt":    ('own=_own, me=("csqtt", iface))', 'own=_own)'),
    "door-turn":     ('own=_ownt, me=("turn", svc))', 'own=_ownt)'),
    "door-iface":    ('own=_own, me=("iface", iface))', 'own=_own)'),
}
# the record's WDTT claims without their identity
PLANTS["wdtt-noid"] = ('        add(tail(w.get("listen")), ifn + " (WDTT)", ("wdtt", ifn))\n        add(w.get("wg_port"), perr("{v1} (WDTT internal WG)", v1=ifn), ("wdtt", ifn))\n    def ents',
                       '        add(tail(w.get("listen")), ifn + " (WDTT)")\n        add(w.get("wg_port"), perr("{v1} (WDTT internal WG)", v1=ifn))\n    def ents')


def load(src):
    m = types.ModuleType("swgpanel_ports"); m.__file__ = PANEL
    exec(compile(src, PANEL, "exec"), m.__dict__)
    return m


def checks(src, ok):
    m = load(src)
    # node n1: wdtt1's record moved to :50010 (not applied: the node still reports :50000); csqtt1's record :41000, reported
    # :40000; a turn-proxy recorded :5000, listening :25000 after a move; wg0 recorded 51830, reported 51820; awg1 on :51000;
    # wdttR restored — reported only (:25100, wg 25101), no record
    nodes = {"n1": {"ifaces": {"wg0": {"desired_port": 51830}},
                    "wdtt": {"wdtt1": {"listen": "0.0.0.0:50010", "wg_port": 50011}},
                    "csqtt": {"csqtt1": {"listen": "0.0.0.0:41000"}},
                    "turn": {"vk-turn-proxy-WINGS-N-5000": {"listen": "0.0.0.0:5000"}}}}
    snap = {"interfaces": {"wg0": {"meta": {"listen_port": 51820}}, "awg1": {"meta": {"listen_port": 51000}}},
            "wdtt": [{"iface": "wdtt1", "listen": "0.0.0.0:50000", "wg_port": 50001}, {"iface": "wdttR", "listen": "0.0.0.0:25100", "wg_port": 25101}],
            "csqtt": {"csqtt1": {"listen": "0.0.0.0:40000"}},
            "turn_proxies": [{"service": "vk-turn-proxy-WINGS-N-5000", "listen": "0.0.0.0:25000"}]}
    deps = {"node_snaps": {"n1": snap}}
    # [1]
    full = m._node_ports(deps, nodes, "n1")
    for who, gone in ((("wdtt", "wdtt1"), {50000, 50001, 50010, 50011}), (("csqtt", "csqtt1"), {40000, 41000}),
                      (("turn", "vk-turn-proxy-WINGS-N-5000"), {5000, 25000}), (("iface", "wg0"), {51820, 51830}), (("wdtt", "wdttR"), {25100, 25101})):
        left = m._node_ports(deps, nodes, "n1", skip=who)
        ok(gone <= set(full) and not (gone & set(left)) and set(full) - gone == set(left),
           "[1] skip=%s leaves out its record's and its reported ports, nobody else's (%s)" % (who, sorted(gone & set(left)) or sorted(set(full) - gone - set(left))))
    # [2]
    pc = lambda port, own=(), me=None: m._port_conflict(deps, nodes, "n1", port, own=own, me=me)
    ok(pc(50000, own=["50010", 50011]) is not None, "[2] without `me`, as before: the reported port reads as the server's own clash (%s)" % pc(50000, own=["50010"]))
    ok(pc(50000, own=["50010", 50011], me=("wdtt", "wdtt1")) is None and pc(40000, own=["41000"], me=("csqtt", "csqtt1")) is None,
       "[2] a WDTT / csqtt server moved but not converged saves back onto the port the node reports it on")
    ok(pc(25100, me=("wdtt", "wdttR")) is None, "[2] a restored server with no record saves on the port it runs on")
    ok(pc(51000, own=["50010"], me=("wdtt", "wdtt1")) == "awg1" and pc(51820, me=("csqtt", "csqtt1")) == "wg0",
       "[2] another holder on the port is still a clash — no report of its own hides it (verify F17)")
    ok(pc(50010, own=["50010"], me=("wdtt", "wdtt1")) is None, "[2] a port the record holds is tolerated, as before")
    ok(pc(56003, me=("wdtt", "wdtt1")) is not None and pc(56003, own=[56003], me=("wdtt", "wdtt1")) is None,
       "[2] RAW-IP 56003 stays reserved unless the record holds it")
    ok(pc(25000, own=["5000"], me=("turn", "vk-turn-proxy-WINGS-N-5000")) is None and pc(25000, own=["5000"], me=("turn", "other")) is not None,
       "[2] a turn-proxy's moved listen is its own, and only its own")
    # [3]
    tree = ast.parse(src)
    def block(test_has):
        return next((ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.If) and test_has in ast.unparse(n.test)), "")
    wd, cq, tm, iu = block("'/api/wdtt/set'"), block("'/api/csqtt/set'"), block("path.endswith('/manage')"), block("'/api/iface/update'")
    ok("me=('wdtt', iface)" in wd and "me=('csqtt', iface)" in cq and "me=('turn', svc)" in tm and "me=('iface', iface)" in iu,
       "[3] the WDTT and csqtt saves, a turn-proxy edit and an interface update pass their own identity")


def run_checks(src):
    fails = []
    def ok(cond, what):
        print(("  PASS " if cond else "  FAIL ") + what)
        if not cond:
            fails.append(what)
    checks(src, ok)
    return fails


def main():
    if "--perturb" in sys.argv:
        missed = []
        for name, (old, new) in PLANTS.items():
            if PSRC.count(old) != 1:
                print("PLANT %-15s anchor missing — fix the plant" % name); missed.append(name); continue
            f = run_checks(PSRC.replace(old, new))
            print("PLANT %-15s %s" % (name, ("RED  (" + f[0] + ")") if f else "GREEN — NOT CAUGHT"))
            if not f:
                missed.append(name)
        print("perturb:", "all caught" if not missed else "MISSED " + ", ".join(missed))
        return 1 if missed else 0
    f = run_checks(PSRC)
    print("port_identity_selftest:", "PASS" if not f else "FAIL (%d)" % len(f))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
