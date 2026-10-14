#!/usr/bin/env python3
"""Self-test: an app published from a server's own repository follows the version that server RUNS (operator,
2026-10-14) — a csqtt 2.1.9 server hands out the CSQTT app 2.1.9, not 2.5 once 2.5 is out. The panel half: which
servers want a release, which tag a version names, the lookup, and what the catalog publishes (the sub page half is
sub_page_render_selftest [8]).

  [1] _pin_tags: upstream's own tag as reported (a turn proxy's "v4.0.3"), and our "<upstream>-<N>" build of it
      (csqtt 2.1.9-4 → v2.1.9, WDTT-Plus 18-2 → v18, ildarmaga 1.5.40-2 → v1.5.40), most exact first
  [2] _pin_wanted, over a fleet's snapshots: a server whose repository also publishes an app (csqtt, amurcanov's WDTT,
      WDTT-Plus, a hack-diaz proxy — the free-turn CLI) is wanted with its running version; a server whose app lives
      elsewhere (WINGS-N, anton48) is not; a csqtt 2.5 line ("csqtt@2.5") resolves to csqtt's repository
  [3] _turn_warm_pins with GitHub stubbed: ONE releases list per repository; a version a release names is pinned (csqtt
      2.1.9-4 → v2.1.9 though v2.5.0 is newer), one none names (ildarmaga's 1.5.0-4) is not, and is not asked again within the hour; nothing is asked when everything
      is resolved; an unreachable GitHub gives no verdict (asked again next pass); a changed fleet says "changed"
  [4] the catalog: the CSQTT app carries pins for the running versions only — the release's page, tag, assets and this
      OS's installer (the hack-diaz CLI: per OS) — while its own latest stays as it was; an app from another repository
      carries none; a version no server runs any more is not published
  [5] the release cache: pins survive a restart (_release_cache_save → _release_cache_load)

Hermetic. Run: python3 tests/turn_app_pins_selftest.py   (0 = pass)
     --perturb        _pin_tags keeps our build suffix (2.1.9-4 never finds v2.1.9) → RED in [1], [3], [4]
     --perturb-repo   _pin_wanted takes every server, its app's repository or not → RED in [2]
"""
import atexit, importlib.machinery, importlib.util, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_REPO = "--perturb-repo" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="apppins-")
atexit.register(shutil.rmtree, TMP, True)   # the copied panel is ~4.6 MB, and the nightly runs this five times
src = open(SERVER, encoding="utf-8").read()
def plant(a, b, what):
    global src
    if src.count(a) != 1:
        print("PERTURB FAILED — %s: the anchor is not in the panel exactly once (%d)" % (what, src.count(a))); sys.exit(1)
    src = src.replace(a, b)
    print("(perturbed: %s — this run must FAIL)" % what)
if PERTURB:
    plant('    for x in (v, re.sub(r"-\\d+$", "", v)):\n', "    for x in (v,):\n", "our build suffix kept")
if PERTURB_REPO:
    plant("        if ver and len(orp) == 2 and orp in app_repos:\n", "        if ver and len(orp) == 2:\n", "every server wanted")
SRV = os.path.join(TMP, "swg-panel-server")
open(SRV, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel_apppins", SRV)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_apppins", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

print("[1] the tag a version names")
check("[1] csqtt 2.1.9-4 → v2.1.9 (after the exact forms)", P._pin_tags("2.1.9-4") == ["v2.1.9-4", "2.1.9-4", "v2.1.9", "2.1.9"], P._pin_tags("2.1.9-4"))
check("[1] WDTT-Plus 18-2 → v18", "v18" in P._pin_tags("18-2"), P._pin_tags("18-2"))
check("[1] ildarmaga 1.5.40-2 → v1.5.40", "v1.5.40" in P._pin_tags("1.5.40-2"), P._pin_tags("1.5.40-2"))
check("[1] a turn proxy's own tag stays as reported", P._pin_tags("v4.0.3") == ["v4.0.3"], P._pin_tags("v4.0.3"))
check("[1] no version, no tag", P._pin_tags("") == [], P._pin_tags(""))

print("\n[2] which servers want their release")
deps = {"node_snaps": {
    "n1": {"csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"},
                     {"iface": "csqtt2", "fork": "csqtt", "line": "2.5", "version": "2.5.0-1"}],
           "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.2.4-3"},
                    {"iface": "wdtt2", "fork": "ildarmaga", "version": "1.5.0-4"}],
           "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-56007", "version": "v4.0.3"},
                            {"service": "vk-turn-proxy-WINGS-N-56010", "version": "v3.0.0"},
                            {"service": "vk-turn-proxy-anton48-56011", "version": "srtp-build440"}]},
    "n2": {"wdtt": [{"iface": "wdtt1", "fork": "wdttplus", "version": "18-2"}]}}}
W = P._pin_wanted(deps)
check("[2] csqtt (both lines), amurcanov's WDTT, ildarmaga, WDTT-Plus and the hack-diaz proxy, each with its running version",
      W == {("amurcanov", "csqtt"): {"2.1.9-4", "2.5.0-1"}, ("amurcanov", "proxy-turn-vk-android"): {"1.2.4-3"},
            ("ildarmaga", "wdtt"): {"1.5.0-4"}, ("Ivan4537", "WDTT-Plus"): {"18-2"},
            ("hackdiaz-dev", "free-turn-proxy"): {"v4.0.3"}}, {"/".join(k): sorted(v) for k, v in W.items()})
check("[2] WINGS-N and anton48 (their apps live in other repositories) want nothing",
      ("WINGS-N", "vk-turn-proxy") not in W and ("anton48", "vk-turn-proxy") not in W, sorted("/".join(k) for k in W))

print("\n[3] the lookup")
CALLS = []
REL = {("amurcanov", "csqtt"): [{"tag": "v2.5.0", "page": "p250", "assets": [{"name": "csqtt-v2.5.0.apk", "url": "u250"}]},
                                 {"tag": "v2.1.9", "page": "p219", "assets": [{"name": "csqtt-v2.1.9.apk", "url": "u219"}]}],
       ("amurcanov", "proxy-turn-vk-android"): [{"tag": "v1.2.4", "page": "p124", "assets": []}],
       ("ildarmaga", "wdtt"): [{"tag": "v1.5.76", "page": "p76", "assets": []}],
       ("Ivan4537", "WDTT-Plus"): [{"tag": "v20", "page": "p20", "assets": []}, {"tag": "v18", "page": "p18", "assets": []}],
       ("hackdiaz-dev", "free-turn-proxy"): [{"tag": "v4.0.4", "page": "p404", "assets": []},
                                             {"tag": "v4.0.3", "page": "p403", "assets": [{"name": "client-linux-amd64", "url": "l403"},
                                                                                          {"name": "client-windows-amd64.exe", "url": "w403"},
                                                                                          {"name": "server-linux-amd64", "url": "s403"}]}]}
P._gh_releases = lambda o, r: (CALLS.append((o, r)), REL.get((o, r)))[1]
ch = P._turn_warm_pins(deps)
check("[3] one releases list per repository", sorted(CALLS) == sorted(W), CALLS)
check("[3] the versions a release names are pinned: csqtt 2.1.9-4 → v2.1.9 and 2.5.0-1 → v2.5.0, amurcanov 1.2.4-3 → v1.2.4, WDTT-Plus 18-2 → v18, hack-diaz v4.0.3",
      P._RELEASE_PIN.get(("amurcanov", "csqtt", "2.1.9-4"), {}).get("tag") == "v2.1.9"
      and P._RELEASE_PIN.get(("amurcanov", "csqtt", "2.5.0-1"), {}).get("tag") == "v2.5.0"
      and P._RELEASE_PIN.get(("amurcanov", "proxy-turn-vk-android", "1.2.4-3"), {}).get("tag") == "v1.2.4"
      and P._RELEASE_PIN.get(("Ivan4537", "WDTT-Plus", "18-2"), {}).get("tag") == "v18"
      and P._RELEASE_PIN.get(("hackdiaz-dev", "free-turn-proxy", "v4.0.3"), {}).get("tag") == "v4.0.3",
      {"|".join(k): v.get("tag") for k, v in P._RELEASE_PIN.items()})
check("[3] …and the one none names is not (ildarmaga 1.5.0-4: its tags are v1.5.x CI rebuilds) — the latest stands in",
      ("ildarmaga", "wdtt", "1.5.0-4") not in P._RELEASE_PIN, "")
check("[3] the pass says the catalog changed", ch is True, ch)
CALLS.clear()
ch2 = P._turn_warm_pins(deps)
check("[3] the next pass asks nothing (the misses wait an hour) and changes nothing", not CALLS and ch2 is False, (CALLS, ch2))
P._PIN_TRIED.clear()
P._gh_releases = lambda o, r: (CALLS.append((o, r)), None)[1]
P._turn_warm_pins(deps)
check("[3] an hour on, the misses are asked again — and an unreachable GitHub leaves no verdict (asked again next pass)",
      CALLS == [("ildarmaga", "wdtt")] and not P._PIN_TRIED, (CALLS, P._PIN_TRIED))
P._gh_releases = lambda o, r: (CALLS.append((o, r)), REL.get((o, r)))[1]
deps2 = {"node_snaps": {"n1": {"csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"}]}}}
check("[3] a fleet that changed says so (the sub's serve.json is rewritten)", P._turn_warm_pins(deps2) is True, "")

print("\n[4] what the catalog publishes")
P._RELEASE_INFO[("amurcanov", "csqtt")] = {"tag": "v2.5.0", "page": "p250", "assets": [{"name": "csqtt-v2.5.0.apk", "url": "u250"}]}
P._PLATFORM_ASSET[("amurcanov", "csqtt", "android")] = "u250"
P._turn_warm_pins(deps)
cl = P.turn_catalog_view(pins=True)["clients"]
an = (cl.get("csqttapp") or {}).get("platforms", {}).get("android") or {}
check("[4] the CSQTT app on Android: its latest is still 2.5.0", an.get("tag") == "v2.5.0" and an.get("url") == "u250", an)
pins = an.get("pins") or {}
check("[4] …and it carries the pin of the version the fleet runs: v2.1.9, its page, its assets, its Android installer",
      set(pins) == {"2.1.9-4", "2.5.0-1"} and pins["2.1.9-4"].get("tag") == "v2.1.9" and pins["2.1.9-4"].get("page") == "p219"
      and pins["2.1.9-4"].get("url") == "u219" and pins["2.1.9-4"].get("assets") == [{"name": "csqtt-v2.1.9.apk", "url": "u219"}], pins)
sc = (cl.get("sidecar") or {}).get("platforms", {})
check("[4] each OS gets its own installer from the pinned release (the hack-diaz CLI v4.0.3: Linux's binary, Windows' .exe — never the server's)",
      ((sc.get("linux") or {}).get("pins") or {}).get("v4.0.3", {}).get("url") == "l403"
      and ((sc.get("windows") or {}).get("pins") or {}).get("v4.0.3", {}).get("url") == "w403", {o: (x or {}).get("pins") for o, x in sc.items()})
other = [cid for cid, c in cl.items() if cid not in ("csqttapp", "wdttapp", "wdttplus", "pwdttilg", "sidecar")
         and any((x or {}).get("pins") for x in (c.get("platforms") or {}).values())]
check("[4] no app from another repository carries a pin (La Lune, FOCSQ, FreeTurn, VK TURN Proxy, …)", not other, other)
P._turn_warm_pins({"node_snaps": {}})
check("[4] a version no server runs any more is not published", not ((P.turn_catalog_view(pins=True)["clients"]["csqttapp"]["platforms"]["android"]).get("pins")), "")

check("[4] /api/state's catalog (every 5 s, the SPA's) carries no pins", not any((x or {}).get("pins") for c in P.turn_catalog_view()["clients"].values()
      for x in (c.get("platforms") or {}).values()), "")
print("\n[5] the release cache")
cdeps = {"nodes_path": os.path.join(TMP, "nodes.json")}
P._release_cache_save(cdeps)
saved = dict(P._RELEASE_PIN)
P._RELEASE_PIN.clear()
P._release_cache_load(cdeps)
check("[5] pins survive a restart", P._RELEASE_PIN == saved and ("amurcanov", "csqtt", "2.1.9-4") in P._RELEASE_PIN,
      sorted("|".join(k) for k in P._RELEASE_PIN))

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURB or PERTURB_REPO:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURB or PERTURB_REPO:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
