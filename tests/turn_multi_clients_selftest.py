#!/usr/bin/env python3
"""Self-test: MCRF and Rawline, two other authors' apps that speak several of our server kinds (1.8.12 items 9 + 10,
docs/RELEASE-1.8.12-PLAN.md), and the release lookup's `tag_re`.

  [1] the catalog: MCRF reuses the `wdttplus` encoder (csqtt 2.1 + 2.5, Android one-tap, its own app releases only);
      Rawline is one entry with RawlineMobile as its Android name, csqtt 2.5 only (every csqtt link imports into it as
      2.5.0), one-tap on every OS (both register rawline://); MCRF in WG_APPS picks releases the same way
  [2] compat: both friendly on csqtt and the visible WDTT forks, Rawline on hack-diaz too; the hidden xxcipherx neither
  [3] client settings: none on csqtt / WDTT (the link is the configuration); Rawline on hack-diaz has FreeTurn's knobs,
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

Hermetic (node for [6]). Run: python3 tests/turn_multi_clients_selftest.py   (0 = pass)
     --perturb-tagre  the lookup reads only the newest release (a beta or engine pack wins) → RED in [4]
     --perturb-udp    Rawline's link keeps no transport when none is saved (its relay falls to tcp) → RED in [6]
     --perturb-qt     the -system-qt package is not ranked last → RED in [5]
     --perturb-lines  Rawline is offered on csqtt 2.1 → RED in [1]
     --perturb-wrap   RawlineMobile is handed the desktop's JSON list (it rejects a string inside an array) → RED in [7]
"""
import json, os, re, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ARGS = set(sys.argv[1:])
PLANTS = {
    "--perturb-tagre": ("swg-panel-server", "10 if tag_re else 1", "1"),
    "--perturb-udp":   ("turn-artifacts.js", 'if (!csR.transport || csR.transport === "auto") csR.transport = "udp";', ""),
    "--perturb-qt":    ("swg-panel-server", 'cands.sort(key=lambda nu: bool(re.search(r"system-qt", nu[0], re.I)))', "pass"),
    "--perturb-lines": ("swg-panel-server", '"encoder": "rawline", "csqtt_lines": ["2.5"]', '"encoder": "rawline", "csqtt_lines": ["2.1", "2.5"]'),
    "--perturb-wrap":  ("sub.js", 'subOs() === "android" ? link : JSON.stringify([link])', "JSON.stringify([link])"),
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

print("[1] the catalog")
m, r = TC.get("mcrf") or {}, TC.get("rawline") or {}
check("MCRF reuses the wdttplus encoder, csqtt 2.1 + 2.5", m.get("encoder") == "wdttplus" and m.get("csqtt_lines") == ["2.1", "2.5"], m)
check("…Android only, one-tap, its app releases only", list(m.get("platforms") or {}) == ["android"]
      and m["platforms"]["android"].get("autostart") is True and m["platforms"]["android"].get("tag_re") == MCRF_RE, m.get("platforms"))
check("Rawline: its own encoder, csqtt 2.5 only", r.get("encoder") == "rawline" and r.get("csqtt_lines") == ["2.5"], r)
check("…desktop + RawlineMobile on Android", sorted(r.get("platforms") or {}) == ["android", "linux", "macos", "windows"]
      and r["platforms"]["android"].get("name") == "RawlineMobile" and "RawlineMobile" in r["platforms"]["android"].get("github", ""), r.get("platforms"))
check("…one-tap on every OS (rawline:// registered there)", all(p.get("autostart") is True for p in (r.get("platforms") or {}).values()), r.get("platforms"))
check("MCRF in WG_APPS, Android only, the same tag_re", list((WG.get("mcrf") or {}).get("platforms") or {}) == ["android"]
      and WG["mcrf"]["platforms"]["android"].get("tag_re") == MCRF_RE, WG.get("mcrf"))

print("\n[2] compat")
for sid in ("csqtt", "amurcanov", "ildarmaga", "wdttplus", "qwdtt"):
    cm = P._turn_compat(sid)
    check("%s offers MCRF and Rawline as friendly" % sid, cm.get("mcrf") == "friendly" and cm.get("rawline") == "friendly", cm)
cm = P._turn_compat("samosvalishe")
check("hack-diaz offers Rawline, not MCRF (no turn-proxy parser)", cm.get("rawline") == "friendly" and "mcrf" not in cm, cm)
check("the hidden xxcipherx keeps its map", "mcrf" not in P._TURN_CLIENT_COMPAT["xxcipherx"] and "rawline" not in P._TURN_CLIENT_COMPAT["xxcipherx"])

print("\n[3] client settings")
for sid in ("csqtt", "amurcanov", "ildarmaga"):
    check("%s: MCRF and Rawline take none" % sid, P._client_schema_for(sid, "mcrf") == [] and P._client_schema_for(sid, "rawline") == [])
rs, fs = P._client_schema_for("samosvalishe", "rawline"), P._client_schema_for("samosvalishe", "freeturn")
check("Rawline on hack-diaz: FreeTurn's knobs, the same list", rs == fs and len(rs) >= 5, [d["key"] for d in rs])
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
out.c21 = T.csqttArtifact(c, "wdttplus", "2.1").text;
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
for key in ("rawlineNote25:", "dlNotes: { mcrf:"):
    check("%s in English and Russian" % key.split(":")[0], sub.count(key) == 2, sub.count(key))
check("Start hands every cell's app its own form (csqtt, WDTT, turn)", sub.count("appOpenUri(") == 4, sub.count("appOpenUri("))
check("the 2.5 note rides Rawline's download bubble on a 2.5 server", 'cga.cid === "rawline" && cd.line === "2.5") cshown.note' in sub)
check("MCRF in both WG/AWG lists", '"amneziawg", "mcrf"]' in sub and '"wireguard", "mcrf"]' in sub)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red under %s" % (len(FAILS), " ".join(PERTURB))) if ok
          else "PERTURB FAILED — %s planted and every check still passed" % " ".join(PERTURB))
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
