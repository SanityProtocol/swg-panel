#!/usr/bin/env python3
"""Self-test: restoring an interface puts back its PROTOCOL — a plain WireGuard interface comes back as WireGuard.

`iface_restore_req` (behind /api/iface/recreate and the Rebuild adapter) sent `cmd: ["awg"]` for every interface,
on the belief that an AWG interface without params speaks plain WireGuard. It does not: the node gives it its default
obfuscation. Measured on a fresh 1.8.7 master (qualification S3): uninstall → reinstall → Restore turned a plain
WireGuard `wg0` into AmneziaWG with jc 4 / jmin 40, and its client — holding the new key and the unchanged PSK —
never completed a handshake (0 bytes either way).

  [1] no AWG params (in the panel's override or in `_lastcfg`) → `cmd: ["wg"]`, and no `awg_params` sent
  [2] AWG params in `_lastcfg` → `cmd: ["awg"]` with exactly those params
  [3] the panel's own override wins over `_lastcfg` (the blessed identity), and still means AWG
  [4] an EMPTY override does not hide real `_lastcfg` params (an empty dict is "nothing blessed", not "plain WG")
  [5] the rule is the SPA's: the browser calls an interface awg iff it has params (iface.js), so the panel's two
      ways of rebuilding one cannot disagree

Run: python3 tests/restore_keeps_protocol_selftest.py (0 = pass)
     --perturb   every restore is AWG again → RED on [1]
"""
import importlib.machinery, importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")
PERTURB = "--perturb" in sys.argv

src = open(PANEL, encoding="utf-8").read()
if PERTURB:
    cut = '''        req["cmd"] = ["wg"]\n    _mtu = ov.get("mtu") or lc.get("mtu")'''
    assert src.count(cut) == 1, "perturbation anchor missing — this run would FALSE-PASS"
    src = src.replace(cut, '''        pass\n    _mtu = ov.get("mtu") or lc.get("mtu")''', 1)
path = os.path.join(tempfile.mkdtemp(), "swg-panel-server")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel", path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:260]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


LC = {"subnet": "10.150.0.0/24", "listen_port": 51990, "address": "10.150.0.1/24", "mtu": 1280}
AWG = {"jc": "4", "jmin": "40", "jmax": "70", "s1": "0", "s2": "0", "h1": "1", "h2": "2", "h3": "3", "h4": "4"}

print("[1] plain WireGuard is restored as WireGuard")
r = P.iface_restore_req({"public_key": "K=", "_lastcfg": dict(LC)})
check("⚠️ cmd is wg", r and r.get("cmd") == ["wg"], r)
check("…with no awg_params", r and "awg_params" not in r, r)
check("…and its identity otherwise intact", r and r.get("listen_port") == 51990 and r.get("address") == "10.150.0.1/24" and r.get("restore"), r)
r = P.iface_restore_req({"public_key": "K=", "_lastcfg": dict(LC, awg_params={})})
check("an empty awg_params in _lastcfg is still plain WireGuard", r and r.get("cmd") == ["wg"], r)

print("\n[2] AmneziaWG is restored as AmneziaWG, with its own params")
r = P.iface_restore_req({"public_key": "K=", "_lastcfg": dict(LC, awg_params=dict(AWG))})
check("cmd is awg with exactly those params", r and r.get("cmd") == ["awg"] and r.get("awg_params") == AWG, r)

print("\n[3] the panel's override is the identity")
r = P.iface_restore_req({"public_key": "K=", "awg_params": {"jc": "9"}, "_lastcfg": dict(LC, awg_params=dict(AWG))})
check("override wins, and means awg", r and r.get("cmd") == ["awg"] and r.get("awg_params") == {"jc": "9"}, r)

print("\n[4] an empty override is not a protocol")
r = P.iface_restore_req({"public_key": "K=", "awg_params": {}, "_lastcfg": dict(LC, awg_params=dict(AWG))})
check("real _lastcfg params still make it awg", r and r.get("cmd") == ["awg"] and r.get("awg_params") == AWG, r)

print("\n[5] the SPA's rule")
iface_js = open(os.path.join(HERE, "..", "js", "iface.js"), encoding="utf-8").read()
check("iface.js calls an interface awg iff it has params",
      '(meta.awg_params && Object.keys(meta.awg_params).length) ? "awg" : "wg"' in iface_js)

print()
if PERTURB:
    print("--perturb: %d check(s) RED" % len(FAILS))
    sys.exit(1 if FAILS else 0)
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
