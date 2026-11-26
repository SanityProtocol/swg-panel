#!/usr/bin/env python3
"""Self-test: MCRF and Rawline, two other authors' apps that speak several of our server kinds (1.8.12 items 9 + 10,
docs/RELEASE-1.8.12-PLAN.md), and the release lookup's `tag_re`.

  [1] the catalog: MCRF reuses the `wdttplus` encoder (csqtt 2.1 + 2.5, Android one-tap, its own app releases only);
      Rawline is one entry with RawlineMobile as its Android name, csqtt 2.5 only (every csqtt link imports into it as
      2.5.0), one-tap on every OS (both register rawline://); MCRF in WG_APPS picks releases the same way
  [2] compat: both friendly on csqtt and the visible WDTT forks, Rawline on hackdiaz too; the hidden xxcipherx neither
  [3] client settings: none on csqtt / WDTT (the link is the configuration); Rawline on hackdiaz has FreeTurn's knobs,
      whose "auto" relay transport its link writes as udp (operator, 2026-11-24: udp by default)
  [4] tag_re: the newest of a page of 10 whose tag matches (mcrf's betas and android-engines-v* skipped); no match →
      None, so the button keeps /releases; a client without it asks one release, as before; a repository's platforms
      share one tag_re (the release cache is keyed by repository)
  [5] the download button: Rawline's bundled-Qt .deb, not the -system-qt one; its installer .exe; the arm64 macOS zip
  [6] the links (node): Rawline's freeturn:// carries transport=udp when nothing is saved or "auto", tcp when saved;
      FreeTurn's link unchanged; on WDTT Rawline gets the colon form, MCRF wdtt://connect; csqtt 2.5 seals for both
  [7] the sub page: Start hands Rawline rawline://add/ with each app's form — the desktop a JSON list of the link, RawlineMobile
      the plain link (run from sub.js, decoded back) — other apps their link unchanged; its 2.5 note and MCRF's download
      note in English and Russian; the WG row
  [8] the WG / AWG apps (1.8.12 item 24): Rawline and WINGS V in WG_APPS, each repository as its turn entry has it;
      WINGS V's direct link (run from turn-artifacts.js, inflated and read back): WireGuard = type 1, backend 4, the
      server's endpoint and the title; AmneziaWG = type 3, backend 8, the whole .conf and the title; the list's order

Hermetic (node for [6]). Run: python3 tests/turn_multi_clients_selftest.py   (0 = pass)
     --perturb-tagre  the lookup reads only the newest release (a beta or engine pack wins) → RED in [4]
     --perturb-udp    Rawline's link keeps no transport when none is saved (its relay falls to tcp) → RED in [6]
     --perturb-qt     the -system-qt package is not ranked last → RED in [5]
     --perturb-lines  Rawline is offered on csqtt 2.1 → RED in [1]
     --perturb-wrap   RawlineMobile is handed the desktop's JSON list (it rejects a string inside an array) → RED in [7]
     --perturb-gen    MCRF's 2.1 link names no generation (its Windows app asks the user) → RED in [6]
     --perturb-genver MCRF's 2.1 link names 2.1.9 whatever the server runs (a 2.0.1 rollback dials the wrong wire) → RED in [6]
     --perturb-blobs  mcrf-desktop's runtime-*.bin blobs and update zip are listed as installers → RED in [5]
     --perturb-qr     MCRF's Windows cell opens on a QR its app cannot scan → RED in [7]
     --perturb-engines MCRF's engine APKs (mcrf-engine-*, mcrf-anubis) are listed as installers → RED in [5]
     --perturb-wsvawg WINGS V's AmneziaWG link names the WireGuard backend → RED in [8]
"""
import json, os, re, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PLANTS = {
    "--perturb-tagre": ("swg-panel-server", "10 if tag_re else 1", "1"),
    "--perturb-udp":   ("turn-artifacts.js", 'if (!csR.transport || csR.transport === "auto") csR.transport = "udp";', ""),
    "--perturb-qt":    ("swg-panel-server", 'cands.sort(key=lambda nu: bool(re.search(r"system-qt", nu[0], re.I)))', "pass"),
    "--perturb-lines": ("swg-panel-server", '"encoder": "rawline", "csqtt_lines": ["2.5", "mrtt"]', '"encoder": "rawline", "csqtt_lines": ["2.1", "2.5", "mrtt"]'),
    "--perturb-wrap":  ("sub.js", 'subOs() === "android" ? link : JSON.stringify([link])', "JSON.stringify([link])"),
    "--perturb-gen":   ("turn-artifacts.js", 'if (asClient === "wdttplus") { var mg = mcrfGeneration(c.version); if (mg) qp.push("mcrf_generation=" + mg); }', ""),
    "--perturb-genver": ("turn-artifacts.js", "var mg = mcrfGeneration(c.version);", 'var mg = "2.1.9";'),
    "--perturb-blobs": ("sub.js", "      if (/^runtime-[0-9a-f]{64}\\.bin$|[-_]app[-_]update\\.zip$/i.test(n)) return false;", ""),
    "--perturb-qr":    ("sub.js", "    return !(p && p.qr === false);", "    return true;"),
    "--perturb-engines": ("sub.js", "      if (/^mcrf-(engine|anubis)[-_]/i.test(n)) return false;", ""),
    "--perturb-wsvawg": ("turn-artifacts.js", "{ ver: 1, type: 3, backend: 8, awg:", "{ ver: 1, type: 3, backend: 4, awg:"),
}
PERTURB = [a for a in ARGS if a in PLANTS]

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:240]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

def source(rel):
    s = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    for a in PERTURB:
        f, old, new = PLANTS[a]
        if f == rel:
            assert s.count(old) == 1, "plant anchor missing for %s — this run would FALSE-PASS" % a
            s = s.replace(old, new)
    return s

src = source("swg-panel-server")
P = types.ModuleType("p")
P.__dict__.update({"__name__": "p", "__file__": os.path.join(ROOT, "swg-panel-server")})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), P.__dict__)
TC, WG = P.TURN_CLIENTS, P.WG_APPS
MCRF_RE = r"^android-v\d+\.\d+\.\d+$"
MCRFD_RE = r"^v\d+\.\d+(\.\d+)?$"

print("[1] the catalog")
m, r = TC.get("mcrf") or {}, TC.get("rawline") or {}
check("MCRF reuses the wdttplus encoder, csqtt 2.1 + 2.5", m.get("encoder") == "wdttplus" and m.get("csqtt_lines") == ["2.1", "2.5"], m)
check("…Android one-tap with its app releases only, Windows (mcrf-desktop, no scheme) with its own",
      sorted(m.get("platforms") or {}) == ["android", "windows"] and m["platforms"]["android"].get("autostart") is True
      and m["platforms"]["android"].get("tag_re") == MCRF_RE and not m["platforms"]["windows"].get("autostart")
      and "mcrf-desktop" in m["platforms"]["windows"].get("github", "") and m["platforms"]["windows"].get("tag_re") == MCRFD_RE, m.get("platforms"))
check("Rawline: its own encoder, csqtt 2.5 and MRTT (never 2.1)", r.get("encoder") == "rawline" and r.get("csqtt_lines") == ["2.5", "mrtt"], r)
check("…desktop + RawlineMobile on Android", sorted(r.get("platforms") or {}) == ["android", "linux", "macos", "windows"]
      and r["platforms"]["android"].get("name") == "RawlineMobile" and "RawlineMobile" in r["platforms"]["android"].get("github", ""), r.get("platforms"))
check("…one-tap on every OS (rawline:// registered there)", all(p.get("autostart") is True for p in (r.get("platforms") or {}).values()), r.get("platforms"))
check("MCRF in WG_APPS, Android and Windows, each repository's tag_re", sorted((WG.get("mcrf") or {}).get("platforms") or {}) == ["android", "windows"]
      and WG["mcrf"]["platforms"]["android"].get("tag_re") == MCRF_RE and WG["mcrf"]["platforms"]["windows"].get("tag_re") == MCRFD_RE, WG.get("mcrf"))
check("…mcrf-desktop's tag_re takes v1.2, not its engine catalogue", [t for t in ("v1.2", "v1.1.2", "windows-engines-2026-11-16") if re.search(MCRFD_RE, t)] == ["v1.2", "v1.1.2"])

print("\n[2] compat")
for sid in ("csqtt", "amurcanov", "ildarmaga", "wdttplus", "qwdtt"):
    cm = P._turn_compat(sid)
    check("%s offers MCRF and Rawline as friendly" % sid, cm.get("mcrf") == "friendly" and cm.get("rawline") == "friendly", cm)
cm = P._turn_compat("samosvalishe")
check("hackdiaz offers Rawline, not MCRF (no turn-proxy parser)", cm.get("rawline") == "friendly" and "mcrf" not in cm, cm)
check("the hidden xxcipherx keeps its map", "mcrf" not in P._TURN_CLIENT_COMPAT["xxcipherx"] and "rawline" not in P._TURN_CLIENT_COMPAT["xxcipherx"])

print("\n[3] client settings")
for sid in ("csqtt", "amurcanov", "ildarmaga"):
    check("%s: MCRF and Rawline take none" % sid, P._client_schema_for(sid, "mcrf") == [] and P._client_schema_for(sid, "rawline") == [])
rs, fs = P._client_schema_for("samosvalishe", "rawline"), P._client_schema_for("samosvalishe", "freeturn")
check("Rawline on hackdiaz: FreeTurn's knobs, the same list", rs == fs and len(rs) >= 5, [d["key"] for d in rs])
rt = next((d for d in rs if d["key"] == "transport"), {})
check("…its relay transport auto (the link writes it as udp, [6]) or a pick of udp / tcp", rt.get("default") == "auto"
      and {"udp", "tcp"} <= set(rt.get("values") or []) and "(udp)" in rt.get("help", ""), rt)

print("\n[4] tag_re")
REL = [{"tag_name": "android-engines-v2.0.0", "assets": [{"name": "mcrf-engine-bs-arm64-v8a-release.apk", "browser_download_url": "u0"}]},
       {"tag_name": "android-v2.0.0-beta.10178", "prerelease": True, "assets": [{"name": "mcrf-android-beta-universal-release.apk", "browser_download_url": "u1"}]},
       {"tag_name": "android-v2.0.1", "assets": [{"name": "mcrf-android-universal-release.apk", "browser_download_url": "u2"}]},
       {"tag_name": "android-v2.0.0", "assets": []}]
CALLS = []
def api(path):
    CALLS.append(path)
    n = int(re.search(r"per_page=(\d+)", path).group(1))
    return [x for x in REL if "nomatch" not in path][:n]
P._gh_api = api
P._GH_COMMIT_CACHE.clear()
got = P._gh_latest_release("vnenapravo7-source", "mcrf", MCRF_RE)
check("the newest matching release of a page of 10 (engines and the beta skipped)", (got or {}).get("tag") == "android-v2.0.1"
      and CALLS[-1].endswith("per_page=10"), (got, CALLS))
check("no match → None (the button keeps /releases)", P._gh_latest_release("o", "r", r"^nothing$") is None)
CALLS.clear()
plain = P._gh_latest_release("vnenapravo7-source", "mcrf")
check("without tag_re: one release, the newest, as before (its own cache entry)", (plain or {}).get("tag") == "android-engines-v2.0.0"
      and CALLS == ["/repos/vnenapravo7-source/mcrf/releases?per_page=1"], (plain, CALLS))
repos = {}
for cat in (TC, WG):
    for c in cat.values():
        for pl in (c.get("platforms") or {}).values():
            orp = P._gh_owner_repo((pl or {}).get("github"))
            if orp[0]:
                repos.setdefault(orp, set()).add((pl or {}).get("tag_re"))
check("every repository's platforms pick releases one way", all(len(v) == 1 for v in repos.values()),
      {k: v for k, v in repos.items() if len(v) > 1})

print("\n[5] the download button")
RAW = [{"name": n, "url": n} for n in ("Rawline-1.2-arch-x86_64.pkg.tar.zst", "Rawline-1.2-debian-amd64-system-qt.deb", "Rawline-1.2-debian-amd64.deb",
       "Rawline-1.2-debian-arm64-system-qt.deb", "Rawline-1.2-macos-amd64.zip", "Rawline-1.2-macos-arm64.zip", "Rawline-1.2-macoslegacy-amd64.zip",
       "Rawline-1.2-windows-arm64.zip", "Rawline-1.2-windows-universal-installer.exe", "Rawline-1.2-windows64.zip")]
check("Linux: the bundled-Qt .deb", P._match_os_asset(RAW, "linux") == "Rawline-1.2-debian-amd64.deb", P._match_os_asset(RAW, "linux"))
check("Windows: the installer", P._match_os_asset(RAW, "windows") == "Rawline-1.2-windows-universal-installer.exe", P._match_os_asset(RAW, "windows"))
check("macOS: the arm64 zip", P._match_os_asset(RAW, "macos") == "Rawline-1.2-macos-arm64.zip", P._match_os_asset(RAW, "macos"))
# mcrf-desktop v1.2 (live, 2026-11-24): the app, its update payload, its source, and ~33 runtime blobs
MD = ["mcrf.exe", "mcrf-app-update.zip", "mcrf-1.2-source.zip"] + ["runtime-%064x.bin" % i for i in range(3)]
check("Windows, mcrf-desktop: the button gets mcrf.exe", P._match_os_asset([{"name": n, "url": n} for n in MD], "windows") == "mcrf.exe",
      P._match_os_asset([{"name": n, "url": n} for n in MD], "windows"))
# mcrf android-v2.0.1 (live, 2026-11-26): the app and the engines it downloads on first start
MA = ["mcrf-android-universal-release.apk", "mcrf-anubis-release.apk", "mcrf-engine-bs-arm64-v8a-release.apk", "mcrf-engine-bs-x86_64-release.apk"]
subsrc = source("sub.js")
fa = subsrc[subsrc.index("  function installerAssets("):]
fa = fa[:fa.index("\n  }\n") + 4]
pr5 = subprocess.run(["node", "-e", fa + "\nconsole.log(JSON.stringify(installerAssets(JSON.parse(process.argv[1])).map(a => a.name)));",
                      json.dumps([{"name": n} for n in MD + MA + ["Rawline-1.2-windows64.zip", "Amnezia.apk", "Foo-1.0-linux-x64.bin"]])], capture_output=True, text=True, timeout=60)
kept = (pr5.stdout.strip().splitlines() or ["null"])[-1]
check("…and its download bubble lists the app only, not its update payload or the runtime blobs (other zips and an app's own .bin installer stay)",
      json.loads(kept)[:1] == ["mcrf.exe"] and json.loads(kept)[2:] == ["Rawline-1.2-windows64.zip", "Amnezia.apk", "Foo-1.0-linux-x64.bin"], (kept, pr5.stderr[-200:]))
check("…on Android the app, not the engine APKs it fetches itself (mcrf-engine-*, mcrf-anubis)",
      json.loads(kept)[1:2] == ["mcrf-android-universal-release.apk"], (kept, pr5.stderr[-200:]))

print("\n[6] the links")
JS = r"""
global.window = global; require(process.argv[1]); const T = global.SWGTurn;
const conf = "[Interface]\nPrivateKey = a\nAddress = 10.0.0.5/32\n[Peer]\nPublicKey = b\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n";
const tp = { service: "free-turn", listen: "1.2.3.4:56009", wrap_key: "ab".repeat(32), params: "-obf-profile rtpopus" };
const dec = l => JSON.parse(Buffer.from(l.replace(/^freeturn:\/\//, "").replace(/-/g, "+").replace(/_/g, "/"), "base64").toString());
const vk = ["https://vk.ru/call/join/abc"], out = {};
for (const [k, cs] of [["none", {}], ["auto", {transport: "auto"}], ["tcp", {transport: "tcp"}]]) {
  const a = T.artifact(conf, tp, "", cs, vk, "rawline"); out[k] = { t: dec(a.text).transport || null, app: a.app, vk: dec(a.text).vk, emb: a.vkEmbedded }; }
out.freeturn = dec(T.artifact(conf, tp, "", {}, vk, "freeturn").text).transport || null;
const w = { password: "p", endpoint_host: "1.2.3.4", vk_links: ["https://vk.ru/call/join/h1"] };
out.wdttRawline = T.wdttArtifact(w, "rawline").text; out.wdttMcrf = T.wdttArtifact(w, "wdttplus").text;
const c = { host: "1.2.3.4", port: 46000, password: "p", vk_links: ["https://vk.ru/call/join/h1"] };
out.c25 = [T.csqttArtifact(c, "rawline", "2.5"), T.csqttArtifact(c, "wdttplus", "2.5")].map(a => !!(a.src && a.buildAsync));
out.c21 = T.csqttArtifact(c, "wdttplus", "2.1").text; out.c21other = T.csqttArtifact(c, "lalune", "2.1").text;
out.gens = Object.fromEntries(["2.1.9-4", "2.0.1", "2.1.5", "2.4.0"].map(v => [v, (T.csqttArtifact({ ...c, version: v }, "wdttplus", "2.1").text.match(/mcrf_generation=([^&]*)/) || [])[1] || null]));
console.log(JSON.stringify(out));
"""
with tempfile.TemporaryDirectory() as td:
    ta = os.path.join(td, "turn-artifacts.js")
    open(ta, "w", encoding="utf-8").write(source("turn-artifacts.js"))
    pr = subprocess.run(["node", "-e", JS, ta], capture_output=True, text=True, timeout=60)
try:
    o = json.loads(pr.stdout.strip().splitlines()[-1])
except Exception:
    o = {}
check("node ran the encoders", bool(o), pr.stderr[-400:])
if o:
    check("Rawline, nothing saved → transport=udp", o["none"]["t"] == "udp", o["none"])
    check("…\"auto\" saved → udp too", o["auto"]["t"] == "udp", o["auto"])
    check("…tcp saved → tcp", o["tcp"]["t"] == "tcp", o["tcp"])
    check("…named Rawline, the VK call link inside", o["none"]["app"] == "Rawline" and o["none"]["vk"] == "https://vk.ru/call/join/abc"
          and o["none"]["emb"] is True, o["none"])
    check("FreeTurn's own link unchanged (no transport: the app's udp)", o["freeturn"] is None, o["freeturn"])
    check("WDTT: Rawline the colon form, MCRF wdtt://connect", o["wdttRawline"].startswith("wdtt://1.2.3.4:") and o["wdttMcrf"].startswith("wdtt://connect?"),
          (o["wdttRawline"], o["wdttMcrf"]))
    check("csqtt 2.5: both sealed; 2.1: MCRF the plain link", o["c25"] == [True, True] and o["c21"].startswith("csqtt://connect?v=2"), (o["c25"], o["c21"]))
    check("…MCRF's 2.1 link names its generation (its Windows app would ask), no other app's does",
          o["c21"].endswith("&mcrf_generation=2.1.9") and "mcrf_generation" not in o["c21other"], (o["c21"][-30:], o["c21other"][-30:]))
    check("…the generation the server runs: 2.1.9-4 → 2.1.9, a 2.0.1 rollback → 2.0, an adopted 2.1.5 → 2.1.5, a build MCRF has no engine for → none (it asks)",
          o["gens"] == {"2.1.9-4": "2.1.9", "2.0.1": "2.0", "2.1.5": "2.1.5", "2.4.0": None}, o["gens"])

print("\n[7] the sub page")
sub = source("sub.js")
fn = sub[sub.index("  function appOpenUri("):]
fn = fn[:fn.index("\n  }\n") + 4]
JS7 = r"""
const os_ = process.argv[1]; function subOs() { return os_; }
""" + fn + r"""
const links = ["freeturn://eyJ2IjoxfQ", "wdtt://1.2.3.4:56000:56001:9000:p:h1", "csqtt://AbC-_x"];
console.log(JSON.stringify({ r: links.map(l => appOpenUri("rawline", l)), o: links.map(l => appOpenUri("lalune", l)) }));
"""
import base64
def unwrap(u):
    return base64.urlsafe_b64decode(u[len("rawline://add/"):] + "==").decode() if u.startswith("rawline://add/") else None
LINKS = ["freeturn://eyJ2IjoxfQ", "wdtt://1.2.3.4:56000:56001:9000:p:h1", "csqtt://AbC-_x"]
for os_ in ("android", "windows"):
    pr = subprocess.run(["node", "-e", JS7, os_], capture_output=True, text=True, timeout=60)
    try:
        o7 = json.loads(pr.stdout.strip().splitlines()[-1])
    except Exception:
        o7 = {}
    check("%s: sub.js's appOpenUri ran" % os_, bool(o7), pr.stderr[-300:])
    if not o7:
        continue
    want = LINKS if os_ == "android" else [json.dumps([l], separators=(",", ":")) for l in LINKS]
    check("%s: Rawline gets rawline://add/ with %s" % (os_, "the plain link" if os_ == "android" else "a JSON list of the link"),
          [unwrap(u) for u in o7["r"]] == want and not any(c in u[len("rawline://add/"):] for u in o7["r"] for c in "+/="), o7["r"])
    check("%s: another app's link is handed over unchanged" % os_, o7["o"] == LINKS, o7["o"])
for key in ("rawlineNote25:", 'dlNotes: { "mcrf@android":'):
    check("%s in English and Russian" % key.split(":")[0], sub.count(key) == 2, sub.count(key))
check("Start hands every cell's app its own form (csqtt, WDTT, turn, WG / AWG)", sub.count("appOpenUri(") == 5, sub.count("appOpenUri("))
check("the 2.5 note rides Rawline's download bubble on a 2.5 server", 'cga.cid === "rawline" && cd.line === "2.5") cshown.note' in sub)
check("MCRF in both WG/AWG lists", '"amneziawg", "mcrf", ' in sub and '"wireguard", "mcrf", ' in sub)
check("a download note can be per OS (MCRF's Android one is not shown on Windows)", 'dnotes[ga.cid + "@" + ga.platform]' in sub)
fq = sub[sub.index("  function appScans("):]
fq = fq[:fq.index("\n  }\n") + 4]
JSQ = r"""
const os_ = process.argv[1]; function subOs() { return os_; }
var _lastData = { turn_catalog: { clients: JSON.parse(process.argv[2]) } };
""" + fq + r"""
console.log(JSON.stringify(["mcrf", "rawline", "csqttapp"].map(appScans)));
"""
cat = json.dumps({cid: {"platforms": P.TURN_CLIENTS[cid]["platforms"]} for cid in ("mcrf", "rawline", "csqttapp")})
scans = {}
for os_ in ("windows", "android"):
    pq = subprocess.run(["node", "-e", JSQ, os_, cat], capture_output=True, text=True, timeout=60)
    scans[os_] = json.loads((pq.stdout.strip().splitlines() or ["null"])[-1])
check("MCRF scans no QR on Windows (a pasted link only), on Android it does; other apps as their catalog says",
      scans == {"windows": [False, True, True], "android": [True, True, True]}, scans)
check("…and the csqtt and WDTT cells ask it before a QR, and the app list's import line", sub.count("appScans(") == 4, sub.count("appScans("))

print("\n[8] the WG / AWG apps")
for cid in ("rawline", "wingsv"):
    w, tcp = (WG.get(cid) or {}).get("platforms") or {}, TC[cid]["platforms"]
    check("%s in WG_APPS: each OS's repository and release choice as its turn entry has them" % cid,
          bool(w) and all(tcp.get(o, {}).get("github") == p.get("github") and tcp.get(o, {}).get("tag_re") == p.get("tag_re") for o, p in w.items()), w)
check("WINGS V in WG_APPS on Android only (WINGS DeX takes no direct profile)", sorted((WG.get("wingsv") or {}).get("platforms") or {}) == ["android"])
check("Rawline in WG_APPS on all four OSes", sorted((WG.get("rawline") or {}).get("platforms") or {}) == ["android", "linux", "macos", "windows"])
m8 = re.search(r'var WG_ORDER = \{ awg: (\[.*?\]), wg: (\[.*?\]) \};', sub)
check("the list: AmneziaVPN first (the default), Rawline after MCRF, then WINGS V; WireGuard for WireGuard only",
      bool(m8) and json.loads(m8.group(1)) == ["amneziavpn", "amneziawg", "mcrf", "rawline", "wingsv"]
      and json.loads(m8.group(2)) == ["amneziavpn", "amneziawg", "wireguard", "mcrf", "rawline", "wingsv"], m8 and m8.groups())
JS8 = r"""
global.window = global; require(process.argv[1]); const T = global.SWGTurn, zlib = require("zlib");
const conf = "[Interface]\nPrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\nAddress = 10.8.0.5/32\nDNS = 1.1.1.1\n\n[Peer]\n" +
  "PublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 203.0.113.7:51820\n";
const aconf = conf.replace("DNS = 1.1.1.1\n", "DNS = 1.1.1.1\nJc = 4\nJmin = 40\nJmax = 70\nI1 = <b 0xdeadbeef>\n");
function rd(b) { const o = {}; let i = 0; const v = () => { let r = 0, s = 0, x; do { x = b[i++]; r += (x & 127) * 2 ** s; s += 7; } while (x & 128); return r; };
  while (i < b.length) { const k = v(), f = Math.floor(k / 8); if ((k & 7) === 0) o[f] = v(); else { const n = v(); o[f] = b.slice(i, i + n); i += n; } } return o; }
const dec = l => { const b = Buffer.from(l.slice(9).replace(/-/g, "+").replace(/_/g, "/"), "base64"); return b[0] === 0x12 ? rd(zlib.inflateSync(b.slice(1))) : null; };
(async () => {
  const w = dec(await T.wingsvDirect(conf, false, "Anna · msk")), a = dec(await T.wingsvDirect(aconf, true, "Anna · msk"));
  const wg = rd(w[4]), ep = rd(wg[3]), aw = rd(a[7]);
  console.log(JSON.stringify({ w: [w[1], w[2], w[5], !!w[3]], ep: [Buffer.from(ep[1]).toString(), ep[2]], wt: Buffer.from(wg[4]).toString(), wkey: wg[1].length > 0,
    a: [a[1], a[2], a[5], !!a[3], !!a[4]], aconf: Buffer.from(aw[1]).toString() === aconf, at: Buffer.from(aw[2]).toString() }));
})().catch(e => { console.log(JSON.stringify({ err: String(e) })); });
"""
with tempfile.TemporaryDirectory() as td:   # the source as planted, as [6] runs it
    ta = os.path.join(td, "turn-artifacts.js")
    open(ta, "w", encoding="utf-8").write(source("turn-artifacts.js"))
    pr8 = subprocess.run(["node", "-e", JS8, ta], capture_output=True, text=True, timeout=60)
try:
    o8 = json.loads(pr8.stdout.strip().splitlines()[-1])
except Exception:
    o8 = {"err": pr8.stderr[-300:]}
check("WINGS V, WireGuard: ver 1, type VK (1), backend WIREGUARD (4), no turn", o8.get("w") == [1, 1, 4, False], o8)
check("…its endpoint is the server's, and the profile is titled", o8.get("ep") == ["203.0.113.7", 51820] and o8.get("wt") == "Anna · msk" and o8.get("wkey"), o8)
check("WINGS V, AmneziaWG: ver 1, type AMNEZIAWG (3), backend AMNEZIAWG_TL (8), no turn, no wg", o8.get("a") == [1, 3, 8, False, False], o8)
check("…carrying the whole .conf, titled", o8.get("aconf") is True and o8.get("at") == "Anna · msk", o8)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red under %s" % (len(FAILS), " ".join(PERTURB))) if ok
          else "PERTURB FAILED — %s planted and every check still passed" % " ".join(PERTURB))
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
