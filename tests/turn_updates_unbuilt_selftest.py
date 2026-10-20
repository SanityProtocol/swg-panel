#!/usr/bin/env python3
"""Self-test: Server updates offers only what a node can install, and never a version that differs by its "v" alone.

swgt, 2026-10-16: svo-im's XXcipherX · WDTT server sat in Server updates as "2.0.0.72 → v2.0.0.72" for good. The fork has
no build of ours since 2026-10-14 (hidden, its releases removed), so its "latest" fell through to the upstream Android
tag — which no node can install (WDTT comes only from OUR releases) — and the two strings, equal but for the "v",
read as behind (a 4-part version parses to the same triple, and equal triples with different strings count as one of
our rebuilds). Update could never clear it.

  [1] _turn_behind: equal but for a leading "v" is not behind; an older upstream tag, an older rebuild of ours are
  [2] _turn_latest_for: a WDTT fork with no build of ours has no latest, and GitHub is not asked; a built WDTT fork
      gives our build, a turn proxy its upstream tag
  [3] turn_updates_view over a fleet: no row for the unbuilt fork; the turn proxy behind its tag keeps its row
  [4] /api/turn/check-updates (the Settings check) answers the same: nothing for the unbuilt fork, never asking GitHub
  [5] Settings → Check updates (the SPA) uses the same "v" rule: its update flag and its "updated" follow both compare
      through sameVer, which takes "4.0.3" for "v4.0.3" and nothing else (review F1, 2026-10-16)

Hermetic (GitHub stubbed). Run: python3 tests/turn_updates_unbuilt_selftest.py   (0 = pass)
     --perturb-unbuilt   the unbuilt fork falls through to its upstream tag again → RED in [2], [4]
     --perturb-v         a version differing by its "v" alone reads as behind again → RED in [1], [3]
     --perturb-spa       Settings compares the latest with a plain !== again → RED in [5]
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb-unbuilt": ('    if _wdtt_unbuilt(fork):\n        return ""\n    owner = turn_fork_owner(fork)',
                          '    owner = turn_fork_owner(fork)',
                          '            elif _wdtt_unbuilt(fid):                    # a WDTT fork we no longer build: nothing installable\n                latest[fid] = ""\n',
                          ''),
    "--perturb-v": ('inst.lstrip("vV") == latest.lstrip("vV"):', 'inst == latest:'),
}
SPA_PLANT = ("dep.some(v => !sameVer(v, lt))", "dep.some(v => v !== lt)")
MODE = next((a for a in sys.argv[1:] if a in PLANTS or a == "--perturb-spa"), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(SERVER, encoding="utf-8").read()
if MODE in PLANTS:
    pl = PLANTS[MODE]
    for cut, new in zip(pl[0::2], pl[1::2]):
        # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
        assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
        src = src.replace(cut, new, 1)
P = types.ModuleType("p")
P.__dict__.update({"__name__": "p", "__file__": SERVER})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), P.__dict__)

ASKED = []
def fake_tag(owner):
    ASKED.append(owner)
    return {"XXcipherX/proxy-turn-vk-android": "v2.0.0.72", "hackdiaz-dev/free-turn-proxy": "v4.0.3"}.get(owner, "")
P._resolve_turn_tag = fake_tag
P._turn_hold_get = lambda nid, key: None
proxy_fork = P.turn_fork("vk-turn-proxy-samosvalishe-1")

print("[1] _turn_behind")
check('"2.0.0.72" is "v2.0.0.72"', P._turn_behind("2.0.0.72", "v2.0.0.72") is False)
check('"v4.0.3" is "4.0.3"', P._turn_behind("v4.0.3", "4.0.3") is False)
check('"v4.0.1" is behind "v4.0.3"', P._turn_behind("v4.0.1", "v4.0.3") is True)
check('our rebuild "1.2.4-2" is behind "1.2.4-3"', P._turn_behind("1.2.4-2", "1.2.4-3") is True)
check('newer than the release is not behind', P._turn_behind("v4.0.4", "v4.0.3") is False)

print("[2] _turn_latest_for")
check("xxcipherx is a WDTT fork with no build of ours", "xxcipherx" not in P.WDTT_BUILDS and P.TURN_SERVERS["xxcipherx"]["kind"] == "wdtt")
del ASKED[:]
check("…so it has no latest", P._turn_latest_for("xxcipherx") == "", P._turn_latest_for("xxcipherx"))
check("…and GitHub is not asked for it", not any("XXcipherX" in a for a in ASKED), ASKED)
check("a built WDTT fork gives our build", P._turn_latest_for("amurcanov") == P._wdtt_current_version("amurcanov"))
check("a turn proxy gives its upstream tag", P._turn_latest_for(proxy_fork) == "v4.0.3", P._turn_latest_for(proxy_fork))

print("[3] Server updates over a fleet")
deps = {"node_snaps": {"svo": {"wdtt": [{"iface": "WDTT3", "fork": "xxcipherx", "version": "2.0.0.72"}],
                               "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-1", "version": "v4.0.1"}]}}}
P._check_turn_latest(deps)
rows = P.turn_updates_view(deps)
check("no row for the XXcipherX server", not [r for r in rows if r["fork"] == "xxcipherx"], rows)
check("the hack-diaz proxy behind its tag keeps its row",
      [(r["fork"], r["installed"], r["latest"]) for r in rows] == [(proxy_fork, "v4.0.1", "v4.0.3")], rows)
# a fork whose latest differs by the "v" alone: never a row
P.TURN_LATEST["forks"][proxy_fork] = "4.0.1"
check("a proxy on v4.0.1 with latest 4.0.1 has no row", P.turn_updates_view(deps) == [], P.turn_updates_view(deps))

print("[4] the Settings check")
P.TURN_LATEST.clear()
del ASKED[:]
try:
    _tmp = __import__("tempfile").mkdtemp(prefix="turnupd-")
    _np = os.path.join(_tmp, "nodes.json"); open(_np, "w").write("{}")
    code, r = P.api("POST", "/api/turn/check-updates", {}, {"forks": [
        {"id": "xxcipherx", "owner": "XXcipherX/proxy-turn-vk-android"},
        {"id": proxy_fork, "owner": "hackdiaz-dev/free-turn-proxy"}]},
        {"fleet": {}, "roster_path": os.path.join(_tmp, "users.json"), "nodes_path": _np})
    lt = (r.get("data") or {}).get("latest") or {}
except Exception as ex:
    code, lt = None, {"error": repr(ex)}
check("answers nothing installable for xxcipherx", code == 200 and lt.get("xxcipherx") == "", (code, lt))
check("…without asking GitHub", not any("XXcipherX" in a for a in ASKED), ASKED)
check("…and the proxy's tag as before", lt.get(proxy_fork) == "v4.0.3", lt)

print("[5] Settings → Check updates")
import re, subprocess
spa = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
if MODE == "--perturb-spa":
    assert spa.count(SPA_PLANT[0]) == 1, "perturbation anchor for --perturb-spa missing — would FALSE-PASS"
    spa = spa.replace(SPA_PLANT[0], SPA_PLANT[1])
m = re.search(r"^const sameVer = .*$", spa, re.M)
check("sameVer is defined", bool(m))
if m:
    js = m.group(0) + "\nconsole.log(JSON.stringify([sameVer('4.0.3','v4.0.3'), sameVer('V2.0.0.72','2.0.0.72'), sameVer('4.0.1','v4.0.3'), sameVer('','v1')]))"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30).stdout.strip()
    check("…takes \"4.0.3\" for \"v4.0.3\" and nothing else", out == "[true,true,false,false]", out)
check("the update flag compares through it", "dep.some(v => !sameVer(v, lt))" in spa)
check("the \"updated\" follow compares through it", "sameVer(s.version, v.latest)" in spa)

print("\n" + ("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
