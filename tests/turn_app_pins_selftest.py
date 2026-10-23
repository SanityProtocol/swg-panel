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
      once (amurcanov's WDTT 1.2.4-3 → v1.2.4; csqtt 2.1.9-4 → our csqtt-app-2.1.9, [7]); a build label that does not name its source follows the
      override (ildarmaga 1.5.40-2 → v1.5.0, never v1.5.40); a version no release names is not, and is not asked again
      within the hour; a failing lookup (rate limit, a deleted repository) is rested an hour too, never asked every pass;
      no network (a boot before egress, GitHub blocked) rests nothing and stops the pass at its first lookup (one
      timeout per pass, not one per version); the hourly refresh re-reads a pin (a release captured mid-upload gains its
      late installers), asking its own tag once; a version is retired only after an hour no snapshot shows it — a row
      one sync misses unpublishes nothing, on a 5-minute pass or the hourly one (a monotonic clock: a boot-time step
      moves nothing); the loop runs the refresh — every pin re-asked — hourly, never on its 2-minute retries
  [4] serve.json's catalog carries the pins once per (repository, version) at its top, no client or OS copy; the
      catalog /api/state carries every 5 s has none, and that call site asks for none
  [5] the release cache: pins survive a restart and are published by the first pass, before any node reports again; a
      b1bb5d34 entry (no per-OS url) is dropped at load, so it is resolved again
  [6] swg-sub: a subscriber is handed only the pins of versions its own servers run (_own_pins), and a node snapshot of
      any shape yields its servers' running versions without an exception (_running_versions)
  [7] apps hosted in OUR repository (operator, 2026-10-20): every build the panel lists on a line, of that line's version
      (CSQTT_LINES: 2.1.9-4, 2.1.9 → csqtt-app-2.1.9; 2.5.1 → csqtt-app-2.5.1; the 2.0.1 rollback row keeps his app) pins our app release under his key, shown as the app's
      version (v2.1.9, v2.5.1), only its .apk files, the Android button the universal APK; one lookup per release per pass;
      a build it does not list (a hand-placed 2.1.5, 2.5.0-1) still asks his repository; our release missing → his, as
      before, and that stand-in is kept by the 5-minute pass, not re-asked every pass; a release of ours with no APK yet
      is missing; GitHub refusing ours rests every build sharing it after ONE request; a pin cached from his repository
      before the upgrade is asked again on the next pass, not served for an hour; the hourly refresh asks ours again; the
      catalog's "latest" for his repository is our newest app release (his when ours errs or has no APK); a rebuild tag
      csqtt-app-2.5.1-2 shows as v2.5.1-2

Hermetic. Run: python3 tests/turn_app_pins_selftest.py   (0 = pass)
     --perturb        _pin_tags keeps our build suffix (1.2.4-3 never finds v1.2.4) → RED in [1], [3]
     --perturb-repo   _pin_wanted takes every server, its app's repository or not → RED in [2]
     --perturb-own    swg-sub hands every subscriber the whole fleet's pins → RED in [6]
     --perturb-offline a network error skips one version, not the pass (a timeout per version) → RED in [3]
     --perturb-seen   a version is retired the first pass it is unseen (a missed row unpublished) → RED in [3], [5]
     --perturb-src    no hosted line: a csqtt server hands out amurcanov's own release again → RED in [3], [4], [7]
     --perturb-cache  a pin cached from his repository is served until the hourly refresh → RED in [7]
     --perturb-memo   one lookup per build, not per hosted release → RED in [7]
     --perturb-fallback our release missing pins nothing (his release is not asked) → RED in [7]
     --perturb-latest the catalog's "latest" still leans on his repository → RED in [7]
     --perturb-fbsrc  his stand-in pin is not marked, so every 5-minute pass asks GitHub again → RED in [7]
     --perturb-proto  any listed build is hosted, the 2.0.1 rollback row included → RED in [7]
     --perturb-403    a refused release is asked again by every build that shares it → RED in [7]
     --perturb-follow the 2.5 line stays on its floor (2.5.1) whatever we release → RED in [8]
     --perturb-lexical tags compared as text (2.5.9 above 2.5.10) → RED in [8]
     --perturb-noapk  a release with no APK yet (still uploading) is offered → RED in [8]
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
PERTURB_SRC = "--perturb-src" in sys.argv
PERTURB_CACHE = "--perturb-cache" in sys.argv
PERTURB_MEMO = "--perturb-memo" in sys.argv
PERTURB_FALLBACK = "--perturb-fallback" in sys.argv
PERTURB_LATEST = "--perturb-latest" in sys.argv
PERTURB_FBSRC = "--perturb-fbsrc" in sys.argv
PERTURB_PROTO = "--perturb-proto" in sys.argv
PERTURB_403 = "--perturb-403" in sys.argv
PERTURB_FOLLOW = "--perturb-follow" in sys.argv
PERTURB_LEXICAL = "--perturb-lexical" in sys.argv
PERTURB_NOAPK = "--perturb-noapk" in sys.argv
PERTURBED = (PERTURB or PERTURB_REPO or PERTURB_OWN or PERTURB_OFFLINE or PERTURB_SEEN or PERTURB_SRC or PERTURB_CACHE
             or PERTURB_MEMO or PERTURB_FALLBACK or PERTURB_LATEST or PERTURB_FBSRC or PERTURB_PROTO or PERTURB_403
             or PERTURB_FOLLOW or PERTURB_LEXICAL or PERTURB_NOAPK)

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
                                          + ([("if seen - t >= _PIN_KEEP]:", "if t < seen]:", "retired when unseen once")] if PERTURB_SEEN else [])
                                          + ([("        src = _pin_source(owner, repo, v)\n", "        src = None\n", "no hosted line")] if PERTURB_SRC else [])
                                          + ([('and _RELEASE_PIN[key].get("src") == sk:', ":", "a cached pin served whatever its source")] if PERTURB_CACHE else [])
                                          + ([("                if sk not in hosted:\n", "                if True:\n", "a lookup per build")] if PERTURB_MEMO else [])
                                          + ([("            if rec is None:                           # not hosted", "            if rec is None and not src:   # not hosted", "no fallback to his release")] if PERTURB_FALLBACK else [])
                                          + ([("rel = _hosted_latest(owner, repo) or _gh_latest_release(owner, repo)", "rel = _gh_latest_release(owner, repo)", "latest from his repository")] if PERTURB_LATEST else [])
                                          + ([("                    rec[\"src\"] = sk                   #", "                    pass  #", "his stand-in unmarked")] if PERTURB_FBSRC else [])
                                          + ([("if str(version).startswith(line + \".\") and any(", "if any(", "the line's version not required")] if PERTURB_PROTO else [])
                                          + ([("                        hosted[sk] = False\n", "                        pass\n", "a refused release not remembered")] if PERTURB_403 else [])
                                          + ([("    res = best[1] if best else ", "    res = ", "the floor kept")] if PERTURB_FOLLOW else [])
                                          + ([("rank = (int(tm.group(1)), int(tm.group(2) or 0))", "rank = t", "tags compared as text")] if PERTURB_LEXICAL else [])
                                          + ([('re.search(r"\\.apk$", str(a.get("name") or ""), re.I)', "True", "no APK required")] if PERTURB_NOAPK else [])))
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
       ("SanityProtocol", "swg-panel", "csqtt-app-2.1.9"): A("CSQTT-universal.apk"),   # [7]: csqtt apps are hosted by us
       ("SanityProtocol", "swg-panel", "csqtt-app-2.5.1"): A("CSQTT-2.5.1-universal.apk"),
       ("amurcanov", "proxy-turn-vk-android", "v1.2.4"): A("WDTT-universal.apk"),
       ("ildarmaga", "wdtt", "v1.5.0"): A("pwdtt-client-linux-amd64", "pwdtt-client-windows-amd64.exe"),
       ("ildarmaga", "wdtt", "v1.5.40"): A("pwdtt-client-linux-amd64-NOT-THIS-SERVER"),
       ("Ivan4537", "WDTT-Plus", "v18"): A("WDTT-Plus-v18-universal-release.apk"),
       ("hackdiaz-dev", "free-turn-proxy", "v4.0.3"): A("client-linux-amd64", "server-linux-amd64")}
CALLS, DOWN, NET = [], set(), {"up": True}
PRE, LIST_DOWN = set(), {"on": False}
def api(path):
    if not NET["up"]:
        CALLS.append(path)
        raise urllib.error.URLError("timed out")      # no network: a URLError, never an HTTPError
    CALLS.append(path)
    if path == "/repos/SanityProtocol/swg-panel/releases?per_page=100":   # [8]: our releases, newest first as GitHub lists them
        if ("SanityProtocol", "swg-panel") in DOWN or LIST_DOWN["on"]:
            raise urllib.error.HTTPError(path, 403, "rate limited", {}, io.BytesIO(b""))
        return [{"tag_name": t, "prerelease": t in PRE, "assets": REL[(o, r, t)]}
                for (o, r, t) in reversed(list(REL)) if (o, r) == ("SanityProtocol", "swg-panel")]
    m = re.match(r"/repos/([^/]+)/([^/]+)/releases/tags/(.+)$", path)
    o, r, t = m.group(1), m.group(2), urllib.parse.unquote(m.group(3))
    if (o, r) in DOWN:
        raise urllib.error.HTTPError(path, 403, "rate limited", {}, io.BytesIO(b""))
    if (o, r, t) not in REL:
        raise urllib.error.HTTPError(path, 404, "Not Found", {}, io.BytesIO(b""))
    return {"tag_name": t, "html_url": "page/" + t, "assets": REL[(o, r, t)]}
P._gh_api = api
ch = P._turn_warm_pins(deps)
pin = lambda o, r, v: P._RELEASE_PIN.get((o, r, v)) or {}
check("[3] csqtt 2.1.9-4 → our csqtt-app-2.1.9 with its Android installer, though 2.5 is newer; amurcanov 1.2.4-3 → v1.2.4; WDTT-Plus 18-2 → v18; hack-diaz v4.0.3",
      pin("amurcanov", "csqtt", "2.1.9-4").get("tag") == "v2.1.9" and pin("amurcanov", "csqtt", "2.1.9-4").get("src") == "SanityProtocol/swg-panel@csqtt-app-2.1.9"
      and pin("amurcanov", "csqtt", "2.1.9-4").get("url", {}).get("android") == "https://dl/CSQTT-universal.apk"
      and pin("amurcanov", "proxy-turn-vk-android", "1.2.4-3").get("tag") == "v1.2.4" and pin("Ivan4537", "WDTT-Plus", "18-2").get("tag") == "v18"
      and pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("tag") == "v4.0.3", {k: v.get("tag") for k, v in key(P._RELEASE_PIN).items()})
check("[3] each OS's installer decided once, per OS — the CLI's Linux client, never its server; no OS without one",
      pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("url") == {"linux": "https://dl/client-linux-amd64"}, pin("hackdiaz-dev", "free-turn-proxy", "v4.0.3").get("url"))
check("[3] ildarmaga 1.5.40-2 (source 1.5.0 + our patch) follows its override to v1.5.0, never upstream v1.5.40",
      pin("ildarmaga", "wdtt", "1.5.40-2").get("tag") == "v1.5.0", pin("ildarmaga", "wdtt", "1.5.40-2"))
check("[3] a version no release names is not pinned (ildarmaga 1.5.99-1); csqtt 2.5.0-1 (a build the panel does not list) is his v2.5.0",
      ("ildarmaga", "wdtt", "1.5.99-1") not in P._RELEASE_PIN and pin("amurcanov", "csqtt", "2.5.0-1").get("tag") == "v2.5.0"
      and not pin("amurcanov", "csqtt", "2.5.0-1").get("src"), "")
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
      CALLS.count("/repos/amurcanov/proxy-turn-vk-android/releases/tags/v1.2.4") == 1 and not any("1.2.4-3" in c for c in CALLS), CALLS)
CSQ, IMG = ("amurcanov", "csqtt", "2.1.9-4"), ("Ivan4537", "WDTT-Plus", "18-2")
for k in P._PIN_SEEN:
    if k != CSQ:
        P._PIN_SEEN[k] -= 3601 if k != IMG else 3500   # unseen for an hour; WDTT-Plus for 58 minutes
ch4 = P._turn_warm_pins(deps2)
check("[3] a version no snapshot has shown for an hour is retired, and the pass says so; one seen 58 minutes ago stays",
      ch4 is True and set(P._RELEASE_PIN) == {CSQ, IMG} and set(P._turn_pins_view()) == {"amurcanov/csqtt", "Ivan4537/WDTT-Plus"},
      sorted(key(P._RELEASE_PIN)))

src = open(SERVER, encoding="utf-8").read()
check("[3] the loop refreshes (every pin re-asked) only on the hourly pass — a rate-limited panel's 2-minute retries ask none",
      "            if (pins(bool(resolved)) or resolved):" in src and "pins(True)" not in src, "")
check("[3] the last-seen clock is monotonic, at the pass and at the cache load",
      "    seen = time.monotonic()" in src and "_PIN_SEEN[(o, r, v)] = time.monotonic()" in src and "_PIN_SEEN[(o, r, v)] = time.time()" not in src, "")

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

print("\n[7] apps hosted in our repository")
P._RELEASE_PIN.clear(); P._PIN_SEEN.clear(); P._PIN_TRIED.clear(); P._PIN_WANTED = {}; CALLS.clear()
REL[("SanityProtocol", "swg-panel", "csqtt-app-2.5.1")] = A("CSQTT-2.5.1-universal.apk", "CSQTT-2.5.1-arm64-v8a.apk",
                                                            "csqtt-app-2.5.1.patch", "CSQTT-LICENSE.txt", "build-apk.sh")
REL[("SanityProtocol", "swg-panel", "csqtt-app-2.1.9")] = A("CSQTT-universal.apk", "CSQTT-arm64-v8a.apk", "CSQTT-LICENSE.txt")
REL[("amurcanov", "csqtt", "v2.1.5")] = A("CSQTT-2.1.5.apk")
REL[("amurcanov", "csqtt", "v2.0.1")] = A("CSQTT-2.0.1.apk")
d7 = {"node_snaps": {"n1": {"csqtt": [{"iface": "c1", "fork": "csqtt", "version": "2.5.1", "line": "2.5"},
                                      {"iface": "c2", "fork": "csqtt", "version": "2.5.0-1", "line": "2.5"},
                                      {"iface": "c3", "fork": "csqtt", "version": "2.1.9-4"},
                                      {"iface": "c4", "fork": "csqtt", "version": "2.1.9"},
                                      {"iface": "c5", "fork": "csqtt", "version": "2.0.1"},
                                      {"iface": "c6", "fork": "csqtt", "version": "2.1.5"}]}}}
P._turn_warm_pins(d7)
own = lambda v: (pin("amurcanov", "csqtt", v).get("tag"), pin("amurcanov", "csqtt", v).get("src"), pin("amurcanov", "csqtt", v).get("url"))
check("[7] 2.5.1 (the build the panel lists on 2.5) → our csqtt-app-2.5.1, shown as v2.5.1, its universal APK",
      own("2.5.1") == ("v2.5.1", "SanityProtocol/swg-panel@csqtt-app-2.5.1", {"android": "https://dl/CSQTT-2.5.1-universal.apk"}), own("2.5.1"))
check("[7] every listed 2.1.x build (2.1.9-4, 2.1.9) → our csqtt-app-2.1.9, shown as v2.1.9",
      own("2.1.9-4") == own("2.1.9") == ("v2.1.9", "SanityProtocol/swg-panel@csqtt-app-2.1.9", {"android": "https://dl/CSQTT-universal.apk"}),
      (own("2.1.9-4"), own("2.1.9")))
check("[7] the 2.0.1 rollback row (an older protocol on the 2.1 line) keeps his v2.0.1, not our 2.1.9 app",
      own("2.0.1")[:2] == ("v2.0.1", None), own("2.0.1"))
check("[7] …its files are the APKs only — no patch, licence or build script",
      sorted(a["name"] for a in pin("amurcanov", "csqtt", "2.5.1").get("assets", [])) == ["CSQTT-2.5.1-arm64-v8a.apk", "CSQTT-2.5.1-universal.apk"],
      pin("amurcanov", "csqtt", "2.5.1").get("assets"))
check("[7] a build the panel does not list asks his repository (a hand-placed 2.1.5 → his v2.1.5; 2.5.0-1 → his v2.5.0)",
      own("2.1.5")[:2] == ("v2.1.5", None) and own("2.5.0-1")[:2] == ("v2.5.0", None), (own("2.1.5"), own("2.5.0-1")))
check("[7] one lookup per hosted release per pass, though three 2.1 builds share it",
      CALLS.count("/repos/SanityProtocol/swg-panel/releases/tags/csqtt-app-2.1.9") == 1
      and CALLS.count("/repos/SanityProtocol/swg-panel/releases/tags/csqtt-app-2.5.1") == 1, CALLS)
CALLS.clear(); P._turn_warm_pins(d7, refresh=True)
check("[7] the hourly refresh asks our releases again, once each, never his for a listed build",
      CALLS.count("/repos/SanityProtocol/swg-panel/releases/tags/csqtt-app-2.1.9") == 1
      and CALLS.count("/repos/SanityProtocol/swg-panel/releases/tags/csqtt-app-2.5.1") == 1
      and not [c for c in CALLS if "/amurcanov/csqtt/" in c and ("v2.1.9" in c or "2.5.1" in c)], CALLS)
P._RELEASE_PIN[("amurcanov", "csqtt", "2.1.9-4")] = {"tag": "v2.1.9", "page": "page/v2.1.9", "assets": [], "url": {"android": "https://dl/his.apk"}}
CALLS.clear(); P._turn_warm_pins(d7)
check("[7] a pin cached from his repository (before the upgrade) is asked again on the next 5-minute pass, not served",
      own("2.1.9-4")[1] == "SanityProtocol/swg-panel@csqtt-app-2.1.9", own("2.1.9-4"))
held = REL.pop(("SanityProtocol", "swg-panel", "csqtt-app-2.1.9")); CALLS.clear(); P._turn_warm_pins(d7, refresh=True)
check("[7] our release missing → his release by tag, as before (2.1.9-4 → his v2.1.9)",
      own("2.1.9-4")[0] == "v2.1.9" and pin("amurcanov", "csqtt", "2.1.9-4").get("page") == "page/v2.1.9", pin("amurcanov", "csqtt", "2.1.9-4"))
CALLS.clear(); P._turn_warm_pins(d7)
check("[7] …and that stand-in is kept by the 5-minute pass — GitHub is not asked again until the hourly refresh",
      not [c for c in CALLS if "2.1.9" in c], CALLS)
REL[("SanityProtocol", "swg-panel", "csqtt-app-2.1.9")] = A("CSQTT-LICENSE.txt")   # created, its APKs still uploading
CALLS.clear(); P._turn_warm_pins(d7, refresh=True)
check("[7] a release of ours with no APK yet counts as missing: his v2.1.9 stands in",
      pin("amurcanov", "csqtt", "2.1.9-4").get("page") == "page/v2.1.9", pin("amurcanov", "csqtt", "2.1.9-4"))
REL[("SanityProtocol", "swg-panel", "csqtt-app-2.1.9")] = held
DOWN.add(("SanityProtocol", "swg-panel")); P._PIN_TRIED.clear(); CALLS.clear(); P._turn_warm_pins(d7, refresh=True)
check("[7] GitHub refusing our release (403): ONE request for it, and every build sharing it rests the hour",
      CALLS.count("/repos/SanityProtocol/swg-panel/releases/tags/csqtt-app-2.1.9") == 1
      and all(("amurcanov", "csqtt", v) in P._PIN_TRIED for v in ("2.1.9-4", "2.1.9")), (CALLS, sorted(key(P._PIN_TRIED))))
check("[7] …and the catalog's latest falls back to his on that refusal", P._hosted_latest("amurcanov", "csqtt") is None)
DOWN.clear(); P._PIN_TRIED.clear()
check("[7] a rebuild tag of ours (csqtt-app-2.5.1-2) shows as v2.5.1-2, the plain one as v2.5.1",
      P._hosted_app_ver("csqtt-app-2.5.1-2") == "v2.5.1-2" and P._hosted_app_ver("csqtt-app-2.5.1") == "v2.5.1")
P._GH_COMMIT_CACHE.pop("rel:amurcanov/csqtt", None)
lat = P._hosted_latest("amurcanov", "csqtt")
check("[7] the catalog's \"latest\" for his repository is our newest app release (v2.5.1, APKs only)",
      lat and lat["tag"] == "v2.5.1" and sorted(a["name"] for a in lat["assets"]) == ["CSQTT-2.5.1-arm64-v8a.apk", "CSQTT-2.5.1-universal.apk"], lat)
P._gh_latest_release = lambda o, r: {"tag": "v2.5.0", "html_url": "page/his", "assets": [{"name": "CSQTT-his.apk", "url": "https://dl/his.apk"}]}
P._RELEASE_INFO.clear(); P._turn_warm_assets()
check("[7] …and _turn_warm_assets takes it for the CSQTT app: its Android button is ours",
      P._RELEASE_INFO.get(("amurcanov", "csqtt"), {}).get("tag") == "v2.5.1"
      and P._PLATFORM_ASSET.get(("amurcanov", "csqtt", "android")) == "https://dl/CSQTT-2.5.1-universal.apk",
      (P._RELEASE_INFO.get(("amurcanov", "csqtt")), P._PLATFORM_ASSET.get(("amurcanov", "csqtt", "android"))))

print("\n[8] the 2.5 line follows our newest 2.5.x release (operator, 2026-10-23)")
SP = ("SanityProtocol", "swg-panel")
TAG25 = lambda: P._hosted_tag("csqtt-app-2.5.1+")
P._GH_COMMIT_CACHE.clear(); P._RELEASE_PIN.clear(); P._PIN_SEEN.clear(); P._PIN_TRIED.clear(); P._PIN_WANTED = {}
CALLS.clear(); P._turn_warm_pins(d7)
check("[8] only 2.5.1 released → csqtt-app-2.5.1, from ONE listing of our releases in the pass",
      own("2.5.1")[1] == "SanityProtocol/swg-panel@csqtt-app-2.5.1" and CALLS.count("/repos/SanityProtocol/swg-panel/releases?per_page=100") == 1,
      (own("2.5.1"), CALLS))
REL[SP + ("csqtt-app-2.5.2",)] = A("CSQTT-2.5.2-universal.apk", "CSQTT-LICENSE.txt")
CALLS.clear(); P._turn_warm_pins(d7)
check("[8] …the answer is kept for the hour: the next 5-minute pass lists nothing and still offers 2.5.1",
      own("2.5.1")[1] == "SanityProtocol/swg-panel@csqtt-app-2.5.1" and not [c for c in CALLS if "releases?per_page" in c], (own("2.5.1"), CALLS))
P._GH_COMMIT_CACHE.clear(); CALLS.clear(); P._turn_warm_pins(d7)
check("[8] 2.5.2 released, the hour gone → a 2.5 server's app is our csqtt-app-2.5.2 (v2.5.2) on the 5-minute pass, no refresh needed",
      own("2.5.1") == ("v2.5.2", "SanityProtocol/swg-panel@csqtt-app-2.5.2", {"android": "https://dl/CSQTT-2.5.2-universal.apk"}), own("2.5.1"))
REL[SP + ("csqtt-app-2.5.2-2",)] = A("CSQTT-2.5.2-universal.apk")
P._GH_COMMIT_CACHE.clear()
check("[8] a rebuild of ours (2.5.2-2) is above 2.5.2", TAG25() == "csqtt-app-2.5.2-2", TAG25())
REL[SP + ("csqtt-app-2.5.9",)] = A("CSQTT-2.5.9-universal.apk")
REL[SP + ("csqtt-app-2.5.10",)] = A("CSQTT-2.5.10-universal.apk")
P._GH_COMMIT_CACHE.clear()
check("[8] versions compare by number: 2.5.10 above 2.5.9", TAG25() == "csqtt-app-2.5.10", TAG25())
REL[SP + ("csqtt-app-2.5.11",)] = A("CSQTT-2.5.11-universal.apk"); PRE.add("csqtt-app-2.5.11")
REL[SP + ("csqtt-app-2.5.12",)] = A("CSQTT-LICENSE.txt", "csqtt-app-2.5.12.patch")      # created, its APKs still uploading
REL[SP + ("csqtt-app-2.6.0",)] = A("CSQTT-2.6.0-universal.apk")
REL[SP + ("csqtt-2.5.13",)] = A("csqtt-linux-amd64")                                     # a server release, not the app
P._GH_COMMIT_CACHE.clear()
check("[8] a prerelease, a release with no APK yet, another line (2.6.0) and a server release are not offered",
      TAG25() == "csqtt-app-2.5.10", TAG25())
lat = P._hosted_latest("amurcanov", "csqtt")
check("[8] the catalog's \"latest\" follows too (v2.5.10)", lat and lat["tag"] == "v2.5.10", lat)
P._GH_COMMIT_CACHE["hosted:csqtt-app-2.5.1+"]["at"] = 0; LIST_DOWN["on"] = True
check("[8] the listing refused when the hour is up → the last answer stands", TAG25() == "csqtt-app-2.5.10", TAG25())
CALLS.clear(); TAG25()
check("[8] …and it rests five minutes: the next ask makes no request (not one timeout per server build)", not CALLS, CALLS)
P._GH_COMMIT_CACHE["hosted:csqtt-app-2.5.1+"]["at"] -= 301; CALLS.clear(); TAG25()
check("[8] …five minutes on, the listing is asked again", CALLS == ["/repos/SanityProtocol/swg-panel/releases?per_page=100"], CALLS)
P._GH_COMMIT_CACHE.clear()
check("[8] the listing refused with no answer yet → the floor, 2.5.1 (never his app)", TAG25() == "csqtt-app-2.5.1", TAG25())
LIST_DOWN["on"] = False; P._GH_COMMIT_CACHE["hosted:csqtt-app-2.5.1+"]["at"] -= 301
check("[8] …and five minutes later, the listing answering, the newest again — the floor was not held for the hour",
      TAG25() == "csqtt-app-2.5.10", TAG25())
LIST_DOWN["on"] = False; CALLS.clear()
check("[8] a plain tag (the 2.1 line) is itself, with no request", P._hosted_tag("csqtt-app-2.1.9") == "csqtt-app-2.1.9" and not CALLS, CALLS)

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURBED:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURBED:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
