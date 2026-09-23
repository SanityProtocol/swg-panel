#!/usr/bin/env python3
"""The panel's time zone — Settings → Display → Data, "Days are counted in" (TRAFFIC-HISTORY-PLAN §11 P0).

A day is the operator's day only if the panel process runs in the operator's zone, and hosts and containers mostly run
in UTC. So the panel carries ONE setting, applied at startup and on save as TZ + time.tzset(). What can go wrong, and
is asserted here:

  1. A zone that does not resolve is taken anyway. glibc never says so: TZ=Nowhere/Bogus runs in UTC under the name
     "Nowhere", so every day is silently counted in UTC while the setting reads Moscow. The panel looks the zone up
     where glibc looks ($TZDIR, else /usr/share/zoneinfo) and hands glibc the file's ABSOLUTE PATH.
  2. The zone is set and nothing follows it — TZ written, tzset() forgotten. Checked by its consequences: the
     turn-proxy auto-update window, the dates in expiry messages, the charts' 2-hour bucket alignment.
  3. Clearing it does not give back the zone the process started with.
  4. A stored zone this server has LOST (an image or tzdata change) crashes startup, or silently counts in UTC, or —
     because every Save sends the field — makes every unrelated Save fail.
  5. The SPA's three halves (state init, save payload, the Display arm of glDirty) and the confirm list: a zone-only
     change must reach diffList, or Save lights up and then writes nothing.

Hermetic: a fixture TZDIR (copies of this host's UTC, Europe/Moscow and America/New_York files, plus zone.tab,
tzdata.zi, a right/ tree and a junk file), so the answer does not depend on whether this host ships tzdata-legacy.

Run: python3 tests/panel_tz_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     a  a file that is not TZif is accepted as a zone
     b  $TZDIR is ignored — the lookup is not where glibc looks
     c  glibc is handed the NAME, not the checked file's path
     d  an unchanged stored zone is re-judged on every Save (a lost zone blocks every unrelated Save)
     e  a changed zone is not judged at all
     f  startup does not apply the stored zone
     g  a stored zone this server lost is not reported
     h  clearing the zone does not restore the zone the process started with
     i  right/ (leap-second) zones are accepted
     j  the browser's legacy zone name is not resolved to the name this server has
     k  TZ is written but tzset() is never called
     l  the Display arm of glDirty does not see the zone          (SPA)
     m  the Save payload does not carry the zone                  (SPA)
     n  the zone's state starts blank instead of from the stored setting — the next Save clears it   (SPA)
     o  a zone-only change leaves diffList empty — Save says "No changes to save"   (SPA)
"""
import calendar, http.client, importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SETTINGS = os.path.join(ROOT, "js", "screen-settings.js")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {   # name: (file, anchor, replacement, the check it must redden)
    "a": ("panel", 'return path if f.read(4) == b"TZif" else ""', "return path", "not TZif"),
    "b": ("panel", 'return os.environ.get("TZDIR") or "/usr/share/zoneinfo"', 'return "/usr/share/zoneinfo"', "$TZDIR"),
    "c": ("panel", '        os.environ["TZ"] = path\n', '        os.environ["TZ"] = name\n', "absolute path"),
    "d": ("panel", '_tz_new = _tz_new.strip() if isinstance(_tz_new, str) and _tz_new.strip() != str(cur.get("time_zone") or "") else None',
          '_tz_new = _tz_new.strip() if isinstance(_tz_new, str) else None', "unrelated Save"),
    "e": ("panel", "            if not tz_file(_tz_new):\n", "            if False:\n", "refused with"),
    "f": ("panel", "    if _tz0 and not tz_apply(_tz0):\n", "    if False:\n", "restart applies"),
    "g": ("panel", '        _TZ_STATE["missing"] = _tz0\n', "", "lost zone is reported"),
    "h": ("panel", '    elif _TZ_BOOT is None:\n        os.environ.pop("TZ", None)\n    else:\n        os.environ["TZ"] = _TZ_BOOT\n',
          '    else:\n        os.environ.pop("TZ", None)\n', "started with"),
    "i": ("panel", 'name.split("/")[0] in ("posix", "right")', 'name.split("/")[0] in ("posix",)', "right/"),
    "j": ("panel", '            found = link if tz_file(link) else ""\n', '            found = ""\n', "legacy name"),
    "k": ("panel", '    time.tzset()\n    _TZ_STATE["zone"], _TZ_STATE["missing"] = name, ""\n',
          '    _TZ_STATE["zone"], _TZ_STATE["missing"] = name, ""\n', "follows the zone"),
    "l": ("spa", 'sec === "display" ? (dispDirty() || tzDirty()) :', 'sec === "display" ? (dispDirty()) :', "glDirty"),
    "m": ("spa", "        time_zone: tz,\n", "", "payload"),
    "n": ("spa", 'useState(ps.time_zone || "")', 'useState("")', "state starts"),
    "o": ("spa", '    if (tzDirty()) out.push(', '    if (false) out.push(', "diffList"),
}

TMP = tempfile.mkdtemp(prefix="panel-tz-")
panel_path, spa_src = PANEL, open(SETTINGS, encoding="utf-8").read()
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    where, old, new, _ = PLANTS[PLANT]
    src = open(PANEL, encoding="utf-8").read() if where == "panel" else spa_src
    assert src.count(old) == 1, "plant anchor missing — this run would FALSE-PASS: %r" % old[:80]
    if where == "panel":
        panel_path = os.path.join(TMP, "planted-panel.py")
        open(panel_path, "w", encoding="utf-8").write(src.replace(old, new, 1))
    else:
        spa_src = src.replace(old, new, 1)

# ── the fixture TZDIR ────────────────────────────────────────────────────────────────────────────────────────────
HOST = "/usr/share/zoneinfo"
for z in ("UTC", "Europe/Moscow", "America/New_York"):
    if not os.path.isfile(os.path.join(HOST, z)):
        sys.exit("this host has no %s/%s — install tzdata to run this gate" % (HOST, z))
TZD = os.path.join(TMP, "zoneinfo")
for z, frm in (("UTC", "UTC"), ("Europe/Moscow", "Europe/Moscow"), ("America/New_York", "America/New_York"),
               ("Test/Only_Here", "Europe/Moscow"), ("right/Europe/Moscow", "Europe/Moscow"),
               ("America/Argentina/Buenos_Aires", "America/New_York")):
    os.makedirs(os.path.dirname(os.path.join(TZD, z)), exist_ok=True)
    shutil.copyfile(os.path.join(HOST, frm), os.path.join(TZD, z))
os.makedirs(os.path.join(TZD, "Fake"), exist_ok=True)
open(os.path.join(TZD, "Fake", "Zone"), "w").write("not a zone file\n")
open(os.path.join(TZD, "zone.tab"), "w").write(
    "# comment line\nRU\t+554521+0373704\tEurope/Moscow\tMSK+00\nUS\t+404251-0740023\tAmerica/New_York\tEastern\n"
    "XX\t+0000+00000\tFake/Zone\tjunk\nAR\t-3436-05827\tAmerica/Argentina/Buenos_Aires\tBuenos Aires\n")
open(os.path.join(TZD, "tzdata.zi"), "w").write(
    "# version test\nZ Europe/Moscow 2:30:17 - LMT 1880\nL Europe/Moscow W-SU\nL Asia/Nowhere Legacy/Dangling\n")
os.environ["TZDIR"] = TZD

_l = importlib.machinery.SourceFileLoader("swgpanel_tz", panel_path)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_tz", _l))
_l.exec_module(P)

MSK_0410 = calendar.timegm((2026, 9, 24, 1, 10, 0))          # 04:10 in Moscow, 01:10 UTC
LATE_30SEP = calendar.timegm((2026, 9, 30, 22, 30, 0))       # 1 October in Moscow, still 30 September in UTC
SCHED = {"every_days": 1, "at": "04:00"}

print("[1] which zones resolve — where glibc looks, and only real zone files")
check("Europe/Moscow resolves under $TZDIR", P.tz_file("Europe/Moscow") == os.path.join(TZD, "Europe/Moscow"),
      P.tz_file("Europe/Moscow"))
check("a zone that exists ONLY under $TZDIR resolves ($TZDIR is where glibc looks)",
      P.tz_file("Test/Only_Here") == os.path.join(TZD, "Test/Only_Here"), P.tz_file("Test/Only_Here"))
check("a three-part name resolves", bool(P.tz_file("America/Argentina/Buenos_Aires")))
check("a file that is not TZif is refused (not TZif)", P.tz_file("Fake/Zone") == "")
check("right/ (leap-second) zones are refused although the file exists (right/)", P.tz_file("right/Europe/Moscow") == "")
for bad in ("Nowhere/Bogus", "../zoneinfo/UTC", "/etc/localtime", "Europe/Moscow/../../UTC", "", None, 7,
            "Europe/Moscow\n", "zone.tab", "posix/Europe/Moscow"):
    check("refused: %r" % (bad,), P.tz_file(bad) == "")

print("[2] applying a zone — and everything that reads the clock follows it")
P._TZ_BOOT = "UTC"
os.environ["TZ"] = "UTC"; time.tzset()
check("at UTC the 04:00 window is not open at 01:10 UTC", P._turn_update_due(SCHED, 0, MSK_0410) is False)
check("Europe/Moscow applies", P.tz_apply("Europe/Moscow") is True)
check("glibc is handed the checked file's absolute path", os.environ.get("TZ") == os.path.join(TZD, "Europe/Moscow"),
      os.environ.get("TZ"))
check("the offset follows the zone (+3 h)", time.localtime(MSK_0410).tm_gmtoff == 10800, time.localtime(MSK_0410).tm_gmtoff)
check("the auto-update window follows the zone — 04:10 Moscow is inside 04:00", P._turn_update_due(SCHED, 0, MSK_0410) is True)
check("an expiry date follows the zone", P.fmt_day(LATE_30SEP) == "2026-10-01", P.fmt_day(LATE_30SEP))
_ep = P._bucket_epoch(P._bucket_of(MSK_0410, 7200), 7200)
check("the month chart's 2-hour buckets start on the zone's even hours",
      time.localtime(_ep).tm_hour % 2 == 0 and time.localtime(_ep).tm_min == 0, time.localtime(_ep)[:6])
check("the zone in force is recorded", P._TZ_STATE["zone"] == "Europe/Moscow" and P.tz_view()["offset"] == 10800,
      P.tz_view())
check("a zone that does not resolve is refused, nothing changed",
      P.tz_apply("Nowhere/Bogus") is False and os.environ.get("TZ") == os.path.join(TZD, "Europe/Moscow")
      and time.localtime(MSK_0410).tm_gmtoff == 10800 and P._TZ_STATE["zone"] == "Europe/Moscow")
check("clearing gives back the zone the process started with", P.tz_apply("") is True and os.environ.get("TZ") == "UTC"
      and time.localtime(MSK_0410).tm_gmtoff == 0 and P.fmt_day(LATE_30SEP) == "2026-09-30", os.environ.get("TZ"))
P._TZ_BOOT = None
P.tz_apply("Europe/Moscow"); P.tz_apply("")
check("clearing with no TZ at start leaves none behind (the process started with)", "TZ" not in os.environ, os.environ.get("TZ"))

print("[3] the zone list, and the browser's own zone as this server names it")
Z = P.tz_zones("W-SU")
check("the list is zone.tab's zones that resolve, UTC first, junk filtered",
      Z["zones"] == ["UTC", "America/Argentina/Buenos_Aires", "America/New_York", "Europe/Moscow"], Z["zones"])
check("a legacy name (Chrome's Asia/Calcutta, here W-SU) comes back as the zone this server has",
      Z["browser"] == "Europe/Moscow", Z["browser"])
check("a name this server has comes back as itself", P.tz_zones("America/New_York")["browser"] == "America/New_York")
for b in ("Legacy/Dangling", "Nowhere", "../UTC", ""):
    check("no zone for browser %r" % b, P.tz_zones(b)["browser"] == "")
check("a zone reads as its place", P._tz_short("America/Argentina/Buenos_Aires") == "Buenos Aires (Argentina)"
      and P._tz_short("Etc/UTC") == "UTC")

print("[4] a real panel: save, refuse, clear, restart, and a zone the server has lost")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


state = os.path.join(TMP, "state")
os.makedirs(state, exist_ok=True)
os.makedirs(os.path.join(TMP, "stats"), exist_ok=True)
PSET = os.path.join(state, "panel-settings.json")
json.dump({"nodes_path": os.path.join(state, "nodes.json"), "roster_path": os.path.join(state, "users.json"),
           "panel_settings_path": PSET, "config_dir": os.path.join(TMP, "conf"), "stats_dir": os.path.join(TMP, "stats"),
           "store_configs": False}, open(os.path.join(TMP, "fleet.json"), "w"))
PORT = free_port()
ENV = {**os.environ, "SWG_PANEL_FLEET": os.path.join(TMP, "fleet.json"), "SWG_PANEL_WEB": ROOT,
       "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "",
       "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "TZ": "America/New_York", "TZDIR": TZD}
NY = {-14400, -18000}


def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.request(method, path, body=json.dumps(body) if body is not None else None,
              headers={"Content-Type": "application/json"} if body is not None else {})
    r = c.getresponse(); out = (r.status, json.loads(r.read() or b"{}")); c.close()
    return out


def zone_now():
    return (call("GET", "/api/state")[1].get("data") or {}).get("panel_settings", {}).get("time_zone_now") or {}


def start():
    p = subprocess.Popen([sys.executable, panel_path], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(150):
        try:
            call("GET", "/api/state"); return p
        except Exception:
            if p.poll() is not None:
                break
            time.sleep(0.1)
    print("  FAIL the panel never came up:", (p.stderr.read() or b"")[-600:].decode(errors="replace"))
    p.kill(); sys.exit(1)


def stop(p):
    p.terminate()
    try: p.wait(timeout=5)
    except Exception: p.kill()


proc = start()
try:
    z = zone_now()
    check("unset: days are counted in the zone the process started with (New York), nothing set",
          z.get("zone") == "" and z.get("offset") in NY and z.get("server") == "New York", z)
    code, r = call("POST", "/api/panel/settings", {"time_zone": "Europe/Moscow"})
    z = zone_now()
    check("Save Europe/Moscow → in force now (+3 h, MSK) and stored",
          code == 200 and z.get("zone") == "Europe/Moscow" and z.get("offset") == 10800
          and json.load(open(PSET)).get("time_zone") == "Europe/Moscow", (code, z))
    code, r = call("POST", "/api/panel/settings", {"time_zone": "Nowhere/Bogus"})
    check("a zone this server does not have is refused with the sentence the browser translates",
          code == 400 and r.get("error_key") == "This server has no time zone called {v1}. Pick one from the list."
          and (r.get("error_vars") or {}).get("v1") == "Nowhere/Bogus", (code, r))
    check("…and nothing changed", zone_now().get("zone") == "Europe/Moscow"
          and json.load(open(PSET)).get("time_zone") == "Europe/Moscow")
    code, r = call("POST", "/api/panel/settings", {"time_zone": "right/Europe/Moscow"})
    check("a right/ zone is refused over the wire (right/)", code == 400, (code, r))
    code, r = call("GET", "/api/time-zones?browser=W-SU")
    check("GET /api/time-zones lists this server's zones and resolves the browser's legacy name",
          code == 200 and (r.get("data") or {}).get("browser") == "Europe/Moscow"
          and ((r.get("data") or {}).get("zones") or [None])[0] == "UTC", r)
    code, r = call("POST", "/api/panel/settings", {"time_zone": ""})
    z = zone_now()
    check("Save the server's own zone → back to the zone it started with",
          code == 200 and z.get("zone") == "" and z.get("offset") in NY, (code, z))
    call("POST", "/api/panel/settings", {"time_zone": "Europe/Moscow"})
finally:
    stop(proc)

proc = start()
try:
    z = zone_now()
    check("a restart applies the stored zone before serving", z.get("zone") == "Europe/Moscow" and z.get("offset") == 10800, z)
finally:
    stop(proc)

ps = json.load(open(PSET)); ps["time_zone"] = "Asia/Lost"; json.dump(ps, open(PSET, "w"))
proc = start()
try:
    z = zone_now()
    check("a lost zone is reported and not in force — startup survives, days use the server's own zone",
          z.get("missing") == "Asia/Lost" and z.get("zone") == "" and z.get("offset") in NY, z)
    code, r = call("POST", "/api/panel/settings", {"time_zone": "Asia/Lost", "top_talkers": 12})
    check("an unrelated Save that carries the unchanged lost zone still saves",
          code == 200 and json.load(open(PSET)).get("top_talkers") == 12, (code, r))
    code, r = call("POST", "/api/panel/settings", {"time_zone": "Europe/Moscow"})
    z = zone_now()
    check("picking another zone clears the report and applies it",
          code == 200 and z.get("missing") == "" and z.get("offset") == 10800, (code, z))
finally:
    stop(proc)

print("[5] the SPA names the zone in every half of the settings idiom")
check("the zone's state starts from the stored setting", 'const [tz, setTz] = useState(ps.time_zone || "");' in spa_src)
check("the Save payload carries it", "\n        time_zone: tz,\n" in spa_src)
check("the Display arm of glDirty sees it", 'sec === "display" ? (dispDirty() || tzDirty()) :' in spa_src
      and 'const tzDirty = () => tz !== (ps.time_zone || "");' in spa_src)
check("a zone-only change reaches diffList — else Save writes nothing", "    if (tzDirty()) out.push(" in spa_src)
check("the field is on screen, fed by the server's list", "options=${tzOptions(tzCat, ps.time_zone_now || {}, tz)}" in spa_src
      and 'api.get("/api/time-zones?browser="' in spa_src)

shutil.rmtree(TMP, ignore_errors=True)
if PLANT:
    want = PLANTS[PLANT][3]
    hit = [f for f in FAILS if want in f]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
