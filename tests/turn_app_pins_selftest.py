#!/usr/bin/env python3
"""Self-test: an app published from a server's own repository follows the version that server RUNS (operator,
2026-10-14) — a csqtt 2.1.9 server hands out the CSQTT app 2.1.9, not 2.5 once 2.5 is out. The panel and swg-sub halves:
which servers want a release, which tag a version names, the lookup, what serve.json publishes and what each
subscriber is handed (the page half is sub_page_render_selftest [8]).

  [1] _pin_tags: upstream's own tag as reported (a turn proxy's "v4.0.3"), and our "<upstream>-<N>" build of it
      (csqtt 2.1.9-4 → v2.1.9, WDTT-Plus 18-2 → v18), most exact first
  [2] _pin_wanted, over a fleet's snapshots: a server whose repository also publishes an app (csqtt, amurcanov's WDTT,
      WDTT-Plus, ildarmaga, a hack-diaz proxy — the free-turn CLI) is wanted with its running version; a server whose app
      lives elsewhere (WINGS-N, anton48) is not; csqtt's 2.5 line ("csqtt@2.5") resolves to csqtt's repository; a stray
      value in a snapshot (a non-string fork) raises nothing
  [3] _turn_warm_pins, GitHub stubbed by tag: the release a version names is pinned with each OS's installer decided
      once (csqtt 2.1.9-4 → v2.1.9 though v2.5.0 is newer); a build label that does not name its source follows the
      override (ildarmaga 1.5.40-2 → v1.5.0, never v1.5.40); a version no release names is not, and is not asked again
      within the hour; a failing lookup (rate limit, a deleted repository) is rested an hour too, never asked every pass;
      no network (a boot before egress, GitHub blocked) rests nothing and stops the pass at its first lookup (one
      timeout per pass, not one per version); the hourly refresh re-reads a pin (a release captured mid-upload gains its
      late installers), asking its own tag once; a version is retired only after an hour no snapshot shows it — a row
      one sync misses unpublishes nothing, on a 5-minute pass or the hourly one
  [4] serve.json's catalog carries the pins once per (repository, version) at its top, no client or OS copy; the
      catalog /api/state carries every 5 s has none, and that call site asks for none
  [5] the release cache: pins survive a restart and are published by the first pass, before any node reports again; a
      b1bb5d34 entry (no per-OS url) is dropped at load, so it is resolved again
  [6] swg-sub: a subscriber is handed only the pins of versions its own servers run (_own_pins), and a node snapshot of
      any shape yields its servers' running versions without an exception (_running_versions)

Hermetic. Run: python3 tests/turn_app_pins_selftest.py   (0 = pass)
     --perturb        _pin_tags keeps our build suffix (2.1.9-4 never finds v2.1.9) → RED in [1], [3], [4]
     --perturb-repo   _pin_wanted takes every server, its app's repository or not → RED in [2]
     --perturb-own    swg-sub hands every subscriber the whole fleet's pins → RED in [6]
     --perturb-offline a network error skips one version, not the pass (a timeout per version) → RED in [3]
     --perturb-seen   a version is retired the first pass it is unseen (a missed row unpublished) → RED in [3], [5]
"""
import atexit, importlib.machinery, importlib.util, io, json, os, re, shutil, sys, tempfile, urllib.error, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SUB = os.environ.get("SWG_SUB") or os.path.join(ROOT, "swg-sub")
PERTURB = "--perturb" in sys.argv
PERTURB_REPO = "--perturb-repo" in sys.argv
PERTURB_OWN = "--perturb-own" in sys.argv
PERTURB_OFFLINE = "--perturb-offline" in sys.argv
PERTURB_SEEN = "--perturb-seen" in sys.argv
PERTURBED = PERTURB or PERTURB_REPO or PERTURB_OWN or PERTURB_OFFLINE or PERTURB_SEEN

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="apppins-")
atexit.register(shutil.rmtree, TMP, True)   # the copied panel is ~4.6 MB, and the nightly runs this five times
def planted(path, plants):
    src = open(path, encoding="utf-8").read()
    for a, b, what in plants:
        if src.count(a) != 1:
            print("PERTURB FAILED — %s: the anchor is not there exactly once (%d)" % (what, src.count(a))); sys.exit(1)
        src = src.replace(a, b)
        print("(perturbed: %s — this run must FAIL)" % what)
    out = os.path.join(TMP, os.path.basename(path))
    open(out, "w", encoding="utf-8").write(src)
    return out
def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel_apppins", planted(SERVER, ([('    for x in (v, re.sub(r"-\\d+$", "", v)):\n', "    for x in (v,):\n", "our build suffix kept")] if PERTURB else [])
                                          + ([("        if ver and orp in app_repos:\n", "        if ver:\n", "every server wanted")] if PERTURB_REPO else [])
                                          + ([("            break                                     # no network", "            continue  #", "a lookup per version offline")] if PERTURB_OFFLINE else [])
                                          + ([("if now - t >= _PIN_KEEP]:", "if t < now]:", "retired when unseen once")] if PERTURB_SEEN else [])))
S = load("swgsub_apppins", planted(SUB, [("for repo, vs in pins.items() if isinstance(vs, dict) and any(v in mine for v in vs)}}",
                                          "for repo, vs in pins.items() if isinstance(vs, dict)} if False else pins}",
                                          "every subscriber gets the fleet's pins")] if PERTURB_OWN else []))
key = lambda d: {"|".join(k): v for k, v in d.items()}

print("[1] the tag a version names")
check("[1] csqtt 2.1.9-4 → v2.1.9 (after the exact forms)", P._pin_tags("2.1.9-4") == ["v2.1.9-4", "2.1.9-4", "v2.1.9", "2.1.9"], P._pin_tags("2.1.9-4"))
check("[1] WDTT-Plus 18-2 → v18", "v18" in P._pin_tags("18-2"), P._pin_tags("18-2"))
check("[1] a turn proxy's own tag stays as reported", P._pin_tags("v4.0.3") == ["v4.0.3"], P._pin_tags("v4.0.3"))
check("[1] no version, no tag", P._pin_tags("") == [], P._pin_tags(""))

print("\n[2] which servers want their release")
deps = {"node_snaps": {
    "n1": {"csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"},
                     {"iface": "csqtt2", "fork": "csqtt", "line": "2.5", "version": "2.5.0-1"}],
           "wdtt": [{"iface": "wdtt1", "fork": "amurcanov", "version": "1.2.4-3"},
                    {"iface": "wdtt2", "fork": "ildarmaga", "version": "1.5.40-2"},
                    {"iface": "wdtt3", "fork": "ildarmaga", "version": "1.5.99-1"}],
           "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-56007", "version": "v4.0.3"},
                            {"service": "vk-turn-proxy-WINGS-N-56010", "version": "v3.0.0"},
                            {"service": "vk-turn-proxy-anton48-56011", "version": "srtp-build440"}]},
    "n2": {"wdtt": [{"iface": "wdtt1", "fork": "wdttplus", "version": "18-2"}]}}}
W = P._pin_wanted(deps)
check("[2] csqtt (both lines), amurcanov's WDTT, ildarmaga, WDTT-Plus and the hack-diaz proxy, each with its running version",
      W == {("amurcanov", "csqtt"): {"2.1.9-4", "2.5.0-1"}, ("amurcanov", "proxy-turn-vk-android"): {"1.2.4-3"},
            ("ildarmaga", "wdtt"): {"1.5.40-2", "1.5.99-1"}, ("Ivan4537", "WDTT-Plus"): {"18-2"},
            ("hackdiaz-dev", "free-turn-proxy"): {"v4.0.3"}}, {"/".join(k): sorted(v) for k, v in W.items()})
check("[2] WINGS-N and anton48 (their apps live in other repositories) want nothing",
      ("WINGS-N", "vk-turn-proxy") not in W and ("anton48", "vk-turn-proxy") not in W, sorted("/".join(k) for k in W))
try:
    P._pin_wanted({"node_snaps": {"n1": {"wdtt": [{"iface": "w1", "fork": 5, "version": "1"}]}}})
    ok = True
except Exception as e:
    ok = repr(e)
check("[2] a stray value in a snapshot (a non-string fork) raises nothing", ok is True, ok)

print("\n[3] the lookup")
def A(*names):
    return [{"name": n, "browser_download_url": "https://dl/" + n} for n in names]
REL = {("amurcanov", "csqtt", "v2.5.0"): A("CSQTT-2.5.0.apk"), ("amurcanov", "csqtt", "v2.1.9"): A("CSQTT-universal.apk"),
       ("amurcanov", "proxy-turn-vk-android", "v1.2.4"): A("WDTT-universal.apk"),
       ("ildarmaga", "wdtt", "v1.5.0"): A("pwdtt-client-linux-amd64", "pwdtt-client-windows-amd64.exe"),
       ("ildarmaga", "wdtt", "v1.5.40"): A("pwdtt-client-linux-amd64-NOT-THIS-SERVER"),
       ("Ivan4537", "WDTT-Plus", "v18"): A("WDTT-Plus-v18-universal-release.apk"),
       ("hackdiaz-dev", "free-turn-proxy", "v4.0.3"): A("client-linux-amd64", "server-linux-amd64")}
CALLS, DOWN, NET = [], set(), {"up": True}
def api(path):
    if not NET["up"]:
        CALLS.append(path)
        raise urllib.error.URLError("timed out")      # no network: a URLError, never an HTTPError
    m = re.match(r"/repos/([^/]+)/([^/]+)/releases/tags/(.+)$", path)
    CALLS.append(path)
    o, r, t = m.group(1), m.group(2), urllib.parse.unquote(m.group(3))
    if (o, r) in DOWN:
        raise urllib.error.HTTPError(path, 403, "rate limited", {}, io.BytesIO(b""))
    if (o, r, t) not in REL:
        raise urllib.error.HTTPError(path, 404, "Not Found", {}, io.BytesIO(b""))
    return {"tag_name": t, "html_url": "page/" + t, "assets": REL[(o, r, t)]}
P._gh_api = api
ch = P._turn_warm_pins(deps)
pin = lambda o, r, v: P._RELEASE_PIN.get((o, r, v)) or {}
check("[3] csqtt 2.1.9-4 → v2.1.9 with its Android installer, though v2.5.0 is newer; amurcanov 1.2.4-3 → v1.2.4; WDTT-Plus 18-2 → v18; hack-diaz v4.0.3",
      pin("amurcanov", "csqtt", "2.1.9-4").get("tag") == "v2.1.9" and pin("amurcanov", "csqtt", "2.1.9-4").get("url", {}).get("android") == "https://dl/CSQTT-universal.apk"
      and pin("amurcanov", "proxy-turn-vk-android", "1.2.4-3").get("tag") == "v1.2.4" and pin("Ivan4537", "WDTT-Plus", "18-2").get("tag") == "v18"
      and pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("tag") == "v4.0.3", {k: v.get("tag") for k, v in key(P._RELEASE_PIN).items()})
check("[3] each OS's installer decided once, per OS — the CLI's Linux client, never its server; no OS without one",
      pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("url") == {"linux": "https://dl/client-linux-amd64"}, pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("url"))
check("[3] ildarmaga 1.5.40-2 (source 1.5.0 + our patch) follows its override to v1.5.0, never upstream v1.5.40",
      pin("ildarmaga", "wdtt", "1.5.40-2").get("tag") == "v1.5.0", pin("ildarmaga", "wdtt", "1.5.40-2"))
check("[3] a version no release names is not pinned (ildarmaga 1.5.99-1); csqtt 2.5.0-1 is, once v2.5.0 exists",
      ("ildarmaga", "wdtt", "1.5.99-1") not in P._RELEASE_PIN and pin("amurcanov", "csqtt", "2.5.0-1").get("tag") == "v2.5.0", "")
check("[3] the pass says serve.json changed", ch is True, ch)
CALLS.clear()
ch2 = P._turn_warm_pins(deps)
check("[3] the next 5-minute pass asks nothing (pins kept, the miss rests an hour) and changes nothing", not CALLS and ch2 is False, (CALLS, ch2))
P._PIN_TRIED.clear(); CALLS.clear(); DOWN.add(("ildarmaga", "wdtt"))
P._turn_warm_pins(deps); n1 = len(CALLS); P._turn_warm_pins(deps); n2 = len(CALLS)
check("[3] a failing lookup (403) is rested an hour like a miss — asked once, not every pass",
      n1 >= 1 and n2 == n1 and ("ildarmaga", "wdtt", "1.5.99-1") in P._PIN_TRIED, (n1, n2, sorted(key(P._PIN_TRIED))))
DOWN.clear(); P._PIN_TRIED.clear(); CALLS.clear(); NET["up"] = False
held = {k: P._RELEASE_PIN.pop(k, None) for k in [("amurcanov", "csqtt", "2.1.9-4"), ("Ivan4537", "WDTT-Plus", "18-2")]}
P._turn_warm_pins(deps)
check("[3] no network: one lookup, then the pass stops (one timeout per pass, not one per version), and nothing is rested",
      len(CALLS) == 1 and not P._PIN_TRIED, (CALLS, sorted(key(P._PIN_TRIED))))
NET["up"] = True; CALLS.clear()
P._turn_warm_pins(deps)
check("[3] …the next pass, online, pins them", all(k in P._RELEASE_PIN for k in held), sorted(key(P._RELEASE_PIN)))
REL[("hackdiaz-dev", "free-turn-proxy", "v4.0.3")] = A("client-linux-amd64", "client-windows-amd64.exe")   # the late upload
ch3 = P._turn_warm_pins(deps, refresh=True)
check("[3] the hourly refresh re-reads a pin: a late Windows installer appears", ch3 is True and
      pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("url", {}).get("windows") == "https://dl/client-windows-amd64.exe", pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3"))
deps2 = {"node_snaps": {"n1": {"csqtt": [{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9-4"}]}}}   # the other rows missed
before, vbefore = set(P._RELEASE_PIN), P._turn_pins_view()
ch5 = P._turn_warm_pins(deps2)
check("[3] a 5-minute pass drops nothing when a snapshot misses a row (a WDTT restart mid-sync)", set(P._RELEASE_PIN) == before,
      sorted(key(P._RELEASE_PIN)))
check("[3] …and unpublishes nothing: serve.json's pins stay, no rewrite", P._turn_pins_view() == vbefore and ch5 is False,
      ({r: sorted(v) for r, v in P._turn_pins_view().items()}, ch5))
CALLS.clear()
P._turn_warm_pins(deps2, refresh=True)
check("[3] the hourly refresh drops nothing either while a version was seen within the hour (F24)",
      set(P._RELEASE_PIN) == before and P._turn_pins_view() == vbefore, sorted(key(P._RELEASE_PIN)))
check("[3] …and asks a pin's own tag once (no -N spellings first)",
      CALLS.count("/repos/amurcanov/csqtt/releases/tags/v2.1.9") == 1 and not any("2.1.9-4" in c for c in CALLS), CALLS)
CSQ, IMG = ("amurcanov", "csqtt", "2.1.9-4"), ("Ivan4537", "WDTT-Plus", "18-2")
for k in P._PIN_SEEN:
    if k != CSQ:
        P._PIN_SEEN[k] -= 3601 if k != IMG else 3500   # unseen for an hour; WDTT-Plus for 58 minutes
ch4 = P._turn_warm_pins(deps2)
check("[3] a version no snapshot has shown for an hour is retired, and the pass says so; one seen 58 minutes ago stays",
      ch4 is True and set(P._RELEASE_PIN) == {CSQ, IMG} and set(P._turn_pins_view()) == {"amurcanov/csqtt", "Ivan4537/WDTT-Plus"},
      sorted(key(P._RELEASE_PIN)))

print("\n[4] what serve.json publishes")
P._RELEASE_INFO[("amurcanov", "csqtt")] = {"tag": "v2.5.0", "page": "p250", "assets": [{"name": "CSQTT-2.5.0.apk", "url": "u250"}]}
P._PLATFORM_ASSET[("amurcanov", "csqtt", "android")] = "u250"
P._PIN_TRIED.clear()
P._turn_warm_pins(deps)
sv = P.turn_catalog_view(pins=True)
pins = sv.get("pins") or {}
check("[4] the pins once per repository and version, at the catalog's top",
      set(pins.get("amurcanov/csqtt") or {}) == {"2.1.9-4", "2.5.0-1"} and pins["amurcanov/csqtt"]["2.1.9-4"]["tag"] == "v2.1.9"
      and pins["amurcanov/csqtt"]["2.1.9-4"]["url"] == {"android": "https://dl/CSQTT-universal.apk"}, {k: sorted(v) for k, v in pins.items()})
check("[4] …and no client or OS carries a copy; the CSQTT app's own latest is still 2.5.0",
      not any("pins" in (x or {}) for c in sv["clients"].values() for x in (c.get("platforms") or {}).values())
      and sv["clients"]["csqttapp"]["platforms"]["android"].get("url") == "u250", "")
check("[4] the catalog /api/state carries every 5 s has no pins", "pins" not in P.turn_catalog_view(), "")
src = open(SERVER, encoding="utf-8").read()
check("[4] …the /api/state call site asks for none, and only serve.json's does",
      re.search(r'"turn_catalog": turn_catalog_view\(\),\s+# single-source', src) is not None
      and src.count("turn_catalog_view(pins=True)") == 1 and '"turn_catalog": turn_catalog_view(pins=True),' in src, "")

print("\n[5] the release cache")
cdeps = {"nodes_path": os.path.join(TMP, "nodes.json")}
P._release_cache_save(cdeps)
saved = dict(P._RELEASE_PIN)
P._RELEASE_PIN.clear()
P._release_cache_load(cdeps)
check("[5] pins survive a restart", P._RELEASE_PIN == saved and ("amurcanov", "csqtt", "2.1.9-4") in P._RELEASE_PIN, sorted(key(P._RELEASE_PIN)))
cp = P._release_cache_path(cdeps); c = json.load(open(cp))
c["release_pin"]["amurcanov/csqtt/2.0.0-1"] = {"tag": "v2.0.0", "page": "p", "assets": []}   # b1bb5d34's shape: no url
json.dump(c, open(cp, "w")); P._RELEASE_PIN.clear(); P._PIN_SEEN.clear(); P._PIN_WANTED = {}; P._release_cache_load(cdeps)
check("[5] a b1bb5d34 cache entry (no per-OS url) is dropped at load — resolved again, never published unusable",
      ("amurcanov", "csqtt", "2.0.0-1") not in P._RELEASE_PIN and P._RELEASE_PIN == saved, sorted(key(P._RELEASE_PIN)))
chb = P._turn_warm_pins({"node_snaps": {}})          # the boot pass: no node has reported yet
check("[5] the first pass after a restart publishes the cached pins before any node reports again",
      chb is True and P._turn_pins_view().get("amurcanov/csqtt", {}).get("2.1.9-4", {}).get("tag") == "v2.1.9",
      {r: sorted(v) for r, v in P._turn_pins_view().items()})

print("\n[6] swg-sub")
peers = [{"targets": [{"type": "csqtt", "csqtt": {"version": "2.1.9-4"}},
                      {"type": "awg", "turn": [{"service": "vk-turn-proxy-samosvalishe-1", "version": "v4.0.3"}]}]}]
cat = {"servers": [], "pins": {"amurcanov/csqtt": {"2.1.9-4": {"tag": "v2.1.9"}, "2.5.0-1": {"tag": "v2.5.0"}},
                                "hackdiaz-dev/free-turn-proxy": {"v4.0.3": {"tag": "v4.0.3"}},
                                "Ivan4537/WDTT-Plus": {"18-2": {"tag": "v18"}}}}
own = S._own_pins(cat, peers).get("pins")
check("[6] a subscriber is handed only its own servers' versions (csqtt 2.1.9-4, hack-diaz v4.0.3) — not 2.5.0-1 or WDTT-Plus 18-2 run elsewhere",
      own == {"amurcanov/csqtt": {"2.1.9-4": {"tag": "v2.1.9"}}, "hackdiaz-dev/free-turn-proxy": {"v4.0.3": {"tag": "v4.0.3"}}}, own)
rv = S._running_versions({"wdtt": {"w1": {"iface": "w1", "version": "18-2"}, "bad": 5},
                          "csqtt": [{"iface": ["x"]}, {"iface": "c1", "version": "2.1.9-4"}, "junk"]})
check("[6] any snapshot shape yields the running versions, a stray value skipped (a map of records, a non-string iface, junk)",
      rv == {"w1": "18-2", "c1": "2.1.9-4"}, rv)

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURBED:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURBED:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
