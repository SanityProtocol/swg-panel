#!/usr/bin/env python3
"""Self-test — an AmneziaWG node on the userspace fallback is DEGRADED, not down (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D2).

With the kernel module missing and amneziawg-go on the box, awg-quick brings every awg interface up on userspace by
itself (measured on 6.8.0-139 with the DKMS build removed: "[!] Missing … Falling back to slow userspace
implementation", awg0 a tun, peers and traffic intact). The panel still said "awg interfaces can't come up" — the same
critical sentence as a node that really is down — and it could not see an interface left on userspace at all.

  [1] all well: noded reports {needed, ok} and nothing else.
  [2] module missing, fallback present, awg0 a tun: ok False, fallback True, userspace [awg0] — a kernel awg1 and a
      tun that is plain WireGuard (wg1) are not listed.
  [3] module missing, no fallback binary: fallback False, no userspace key.
  [4] module LOADED but awg0 still a tun — after a repair: ok, userspace [awg0], no fallback key. [4b] module BUILT but
      not loaded while awg0 is a tun — the kernel refused it: NOT ok (no update can move them back), fallback True even
      with no binary found where we look — the running interface is the proof. [2c] likewise with no module at all. An exit device (swg-noded's own, not in `interfaces`) is listed the same way when amneziawg-go serves
      it (its UAPI socket) — a tun exit anything else serves is not.
  [5] the panel words them apart: [2] → "run on the slower fallback datapath", never "can't come up"; [3] and a node
      too old to send `fallback` → "can't come up"; [4] → "awg0: on the slower fallback datapath".
  [6] datapath_broken is only the real outage; repairable also covers [4]; _awg_datapath tolerates no report at all.
  [7] a docker node reports nothing (userspace is its normal state there).
  [8] a malformed report (datapath a list, awg a bool, userspace a string or with non-strings) is no report: the panel
      neither raises nor spells "awg0" out letter by letter.

Hermetic. Run: python3 tests/awg_fallback_datapath_selftest.py     (0 = pass)
     --perturb   drops the panel's fallback branch and expects RED on [5].
"""
import builtins, importlib.machinery, importlib.util, io, os, sys, tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PANEL = os.environ.get("SWG_PANEL") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path, src=None):
    if src is not None:
        fd, tmp = tempfile.mkstemp(suffix=".py"); os.write(fd, src.encode()); os.close(fd); path = tmp
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m

N = load("swgnoded", NODED)
psrc = open(PANEL).read()
if PERTURB:
    assert psrc.count('        if _dp.get("fallback"):\n') == 1
    psrc = psrc.replace('        if _dp.get("fallback"):\n', '        if False:\n')
P = load("swgpanel", PANEL, psrc)

KR = os.uname().release
AWG_IFACES = {"awg0": {"meta": {"tool": "awg"}}, "awg1": {"meta": {"tool": "awg"}}, "wg1": {"meta": {"tool": "wg"}}}

def noded(modules="", built=False, fallback=False, tun=(), exits=(), socks=()):
    N._EXITS["list"] = [{"device": d} for d in exits]
    exists = {"/usr/bin/awg"} | {"/sys/class/net/%s/tun_flags" % i for i in tun} | {"/var/run/amneziawg/%s.sock" % i for i in socks}
    real_open = builtins.open
    def fopen(p, *a, **k):
        return io.StringIO(modules) if p == "/proc/modules" else real_open(p, *a, **k)
    def flistdir(d):
        if built and d == "/lib/modules/%s/updates/dkms" % KR:
            return ["amneziawg.ko.zst"]
        raise FileNotFoundError(d)
    with mock.patch("builtins.open", fopen), mock.patch("os.path.exists", lambda p: p in exists), \
         mock.patch("os.access", lambda p, m: fallback and p == "/usr/local/bin/amneziawg-go"), \
         mock.patch("os.listdir", flistdir):
        return N.node_datapath_health(AWG_IFACES)

old_kind = getattr(N, "NODE_KIND", None)
N.NODE_KIND = "baremetal"
r1 = noded(modules="amneziawg 135168 0 - Live 0x0\n")
check("[1] all well → {needed, ok} only", r1 == {"awg": {"needed": True, "ok": True}}, r1)
r2 = noded(fallback=True, tun=("awg0", "wg1"))
check("[2] missing + fallback + awg0 tun", r2 == {"awg": {"needed": True, "ok": False, "fallback": True, "userspace": ["awg0"]}}, r2)
r3 = noded()
check("[3] missing, no fallback", r3 == {"awg": {"needed": True, "ok": False, "fallback": False}}, r3)
LOADED = "amneziawg 135168 0 - Live 0x0\n"
r4 = noded(modules=LOADED, tun=("awg0",))
check("[4] loaded but awg0 still a tun", r4 == {"awg": {"needed": True, "ok": True, "userspace": ["awg0"]}}, r4)
r4b = noded(built=True, tun=("awg0",))
check("[4b] built, NOT loaded, awg0 a tun → not ok, fallback proven by the interface", r4b == {"awg": {"needed": True, "ok": False, "fallback": True, "userspace": ["awg0"]}}, r4b)
r4c = noded(built=True)
check("[4b] built, not loaded, nothing on a tun → ok (it loads on first use)", r4c == {"awg": {"needed": True, "ok": True}}, r4c)
r2c = noded(tun=("awg0",))
check("[2c] no module, no binary where we look, awg0 a tun → fallback True", r2c == {"awg": {"needed": True, "ok": False, "fallback": True, "userspace": ["awg0"]}}, r2c)
r4x = noded(modules=LOADED, tun=("wgx-1", "wgx-2", "wgx-4"), exits=("wgx-1", "wgx-3", "wgx-4"), socks=("wgx-1",))
check("[4] an EXIT on amneziawg-go is listed too — not a tun that is no exit, not a tun exit amneziawg-go does not serve", r4x == {"awg": {"needed": True, "ok": True, "userspace": ["wgx-1"]}}, r4x)
N.NODE_KIND = "docker"
check("[7] docker → nothing", N.node_datapath_health(AWG_IFACES) == {})
N.NODE_KIND = old_kind

def texts(dp):
    snap = {"datapath": dp} if dp is not None else {}
    try:
        iss = P._node_issues({"id": "n1", "name": "n1"}, snap)
    except Exception as e:
        return ["<raised %r>" % e]
    return [(i.get("error") if isinstance(i, dict) else str(i)) for i in iss]
t2, t3, t4 = texts(r2), texts(r3), texts(r4)
told = texts({"awg": {"needed": True, "ok": False}})
CANT, FB = "can't come up", "run on the slower fallback datapath"
check("[5] fallback node → the fallback sentence", any(FB in t for t in t2) and not any(CANT in t for t in t2), t2)
check("[5] no fallback → can't come up", any(CANT in t for t in t3), t3)
check("[5] older node (no fallback key) → can't come up", any(CANT in t for t in told), told)
check("[5] repaired but still on userspace → names awg0", any(t.startswith("awg0: on the slower fallback datapath") for t in t4), t4)
check("[5] all well → no datapath sentence", not any("AmneziaWG" in t or "fallback" in t for t in texts(r1)), texts(r1))
# A raise inside _node_issues would come back as "<raised …>" — which contains neither keyword, so every check above that
# asserts an ABSENCE could pass on an exception. Nothing may have raised.
check("[5] _node_issues never raised on these snapshots", not any(t.startswith("<raised") for t in t2 + t3 + t4 + told + texts(r1)), t2 + t3 + t4 + told)

def broken(report):            # the node record's expression, over a SNAPSHOT shaped like the wire ({"datapath": …})
    snap = {"datapath": report}
    return bool(P._awg_datapath(snap).get("needed") and not P._awg_datapath(snap).get("ok") and not P._awg_datapath(snap).get("fallback"))
check("[6] _awg_datapath tolerates no report", P._awg_datapath({}) == {} and P._awg_datapath(None) == {})
src = open(PANEL).read()
check("[6] datapath_broken = missing AND no fallback (the expression the node record uses)",
      '"datapath_broken": bool(_awg_datapath(snap).get("needed") and not _awg_datapath(snap).get("ok") and not _awg_datapath(snap).get("fallback")),' in src
      and broken(r3) and not broken(r2) and not broken(r4))
for bad in ({"datapath": ["x"]}, {"datapath": {"awg": True}}, {"datapath": {"awg": {"needed": True, "ok": True, "userspace": "awg0"}}},
            {"datapath": {"awg": {"needed": True, "ok": True, "userspace": ["awg0", None, 7]}}}, "not a dict", None):
    try:
        got = P._awg_datapath(bad); iss = P._node_issues({"id": "n1", "name": "n1"}, bad if isinstance(bad, dict) else {})
        txt = " ".join((i.get("error") if isinstance(i, dict) else str(i)) for i in iss); ok8 = "a, w, g" not in txt and "None" not in txt
    except Exception as ex:
        got, ok8 = repr(ex), False
    check("[8] malformed %r → no raise, no letter-by-letter" % (bad,), ok8 and isinstance(got, dict), got)
check("[6] repairable covers interfaces still on userspace",
      '_awg_datapath(snap).get("needed") and (not _awg_datapath(snap).get("ok") or _awg_datapath(snap).get("userspace"))' in src)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
sys.exit(1 if FAILS else 0)
