#!/usr/bin/env python3
"""Self-test: MRTT (1.8.12 item 10) — MRTT 1.0 with our integration (forks/csqtt/mrtt) as a csqtt FORK (ttrroyy's; operator
2026-11-25: "MRTT is a fork, not a version of csqtt") that the node runs as its fixed line `mrtt`, its own apps, its own link.

  [1] the panel: the fork mrtt (kind csqtt, label ttrroyy) runs the line mrtt — its build mrtt-1.0-1 from release
      csqtt-mrtt-1.0-1 (the node asks for "csqtt-" + version), 2.5's address pool (.3–.250); the Version control offers
      2.1 and 2.5 only; the share table vouches for the rigged build under the fork's own key
  [2] the node: it knows the fork, advertises the line, gives it its own binary slot, and reads its store (csqtt.db, MRTT's schema: 2.5's
      passwords table plus MRTT's columns) by the password's own address, as a 2.5 store
  [3] the catalog: the MRTT app speaks mrtt only (one-tap on Android, its stable v* releases, not -legacy or a beta);
      Rawline speaks 2.5 and mrtt; no other app speaks mrtt; the fork mrtt offers both (the MRTT app native), csqtt's
      does not offer the MRTT app; none takes client settings
  [4] the link (node): an mrtt server's link is mrtt:// sealed under MRTT's seed — its own decoder opens it, csqtt's does not
      — for the MRTT app and for Rawline; a 2.5 server's stays csqtt:// under csqtt's seed

Hermetic (node for [4]). Run: python3 tests/csqtt_mrtt_line_selftest.py   (0 = pass)
     --perturb-noded  the node does not know the line (it is never sent there) → RED in [2]
     --perturb-seed   an mrtt link sealed under csqtt's seed → RED in [4]
     --perturb-store  the node reads an mrtt store as a 2.1 one (through devices) → RED in [2]
     --perturb-src    the MRTT link's cache key is the bare payload again (an open sheet keeps the 2.5 link) → RED in [4]
     --perturb-vk     an MRTT link with no VK hash warns that it won't authenticate (the app takes MAX / its own VK) → RED in [4]
     --perturb-vkraw  Rawline's MRTT link with no VK hash loses the warning too (not known to manage without one) → RED in [4]
     --perturb-forkline the catalog's MRTT fork names no line (the Version control lists mrtt again) → RED in [1]
     --perturb-nodefork the node does not know the fork mrtt (an MRTT server never installs) → RED in [2]
     --perturb-tag    the MRTT app's tags are two-part only again (a v1.0.1 fix release is never handed out) → RED in [3]
"""
import json, os, re, sqlite3, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANTS = {
    "--perturb-noded": ("swg-noded", 'CSQTT_KNOWN_LINES = ("2.1", "2.5", "mrtt")', 'CSQTT_KNOWN_LINES = ("2.1", "2.5")'),
    "--perturb-seed":  ("turn-artifacts.js", 'var MRTT_LINK_SEED = "mrtt-chiper-key";', 'var MRTT_LINK_SEED = "csqtt-chiper-key";'),
    "--perturb-store": ("swg-noded", 'if "device_id" in cols and ((line or "2.1") == "2.1" or "ip" not in cols):',
                        'if True:'),
    "--perturb-src":   ("turn-artifacts.js", 'src: "mrtt:" + p25,', 'src: p25,'),
    "--perturb-vk":    ("turn-artifacts.js", 'vkMissing: asClient === "rawline" ? vkMissing : false, hint: "Open the mrtt:// link', 'vkMissing: vkMissing, hint: "Open the mrtt:// link'),
    "--perturb-vkraw": ("turn-artifacts.js", 'vkMissing: asClient === "rawline" ? vkMissing : false, hint: "Open the mrtt:// link', 'vkMissing: false, hint: "Open the mrtt:// link'),
    "--perturb-forkline": ("swg-panel-server", '"owner": "ttrroyy/MRTT", "line": "mrtt",', '"owner": "ttrroyy/MRTT",'),
    "--perturb-nodefork": ("swg-noded", ', "mrtt": "ttrroyy/MRTT"}', '}'),
    "--perturb-tag":   ("swg-panel-server", '"autostart": True, "tag_re": r"^v\\d+\\.\\d+(\\.\\d+)?$"}}},', '"autostart": True, "tag_re": r"^v\\d+\\.\\d+$"}}},'),
}
PERTURB = [a for a in sys.argv[1:] if a in PLANTS]
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

def load(rel, name):
    m = types.ModuleType(name)
    m.__dict__.update({"__name__": name, "__file__": os.path.join(ROOT, rel)})
    exec(compile(source(rel).split("\nif __name__ ==")[0], rel, "exec"), m.__dict__)
    return m

P = load("swg-panel-server", "p")
N = load("swg-noded", "n")

print("[1] the panel")
mf = P.TURN_SERVERS.get("mrtt") or {}
check("MRTT is a csqtt fork of ttrroyy's that runs the line mrtt", mf.get("kind") == "csqtt" and mf.get("label") == "ttrroyy"
      and P._csqtt_fork_line("mrtt") == "mrtt" and P._csqtt_fork_line("csqtt") == "", {k: mf.get(k) for k in ("kind", "label", "line")})
check("…the line runs on the node's machinery beside 2.1 and 2.5, and the Version control offers 2.1 and 2.5 only",
      list(P.CSQTT_LINES)[-1] == "mrtt" and P._csqtt_version_lines() == ["2.1", "2.5"], (list(P.CSQTT_LINES), P._csqtt_version_lines()))
check("…its build mrtt-1.0-1 from release csqtt-mrtt-1.0-1 (the node asks for csqtt- + version)",
      P.CSQTT_LINES["mrtt"][0] == ("mrtt-1.0-1", "csqtt-mrtt-1.0-1") and P._csqtt_tag_for("mrtt-1.0-1") == "csqtt-" + "mrtt-1.0-1",
      P.CSQTT_LINES.get("mrtt"))
check("…its current build", P._csqtt_current_version("mrtt") == "mrtt-1.0-1")
check("its pool is 2.5's", P.turn_cap("csqtt", {"line": "mrtt"}) == P.turn_cap("csqtt", {"line": "2.5"}) == 248)
check("the share table vouches for the rigged build under the fork's own key (and the catalog says so)",
      "mrtt-1.0-1" in P.KEYLESS_SHARE_BUILDS["mrtt"]["raw"] and "mrtt-1.0-1" not in P.KEYLESS_SHARE_BUILDS["csqtt"]["raw"]
      and next(s for s in P.turn_catalog_view()["servers"] if s["id"] == "mrtt").get("reach_vouched") is True)
check("its refusals name it whole (MRTT; a csqtt line as csqtt 2.5)", P._csqtt_line_name("mrtt") == "MRTT" and P._csqtt_line_name("2.5") == "csqtt 2.5")

print("\n[2] the node")
check("it knows the fork mrtt (an MRTT server installs) and advertises its line", "mrtt" in N.CSQTT_FORK_OWNER and not N._csqtt_fork_unknown({"fork": "mrtt"})
      and "mrtt" in N.CSQTT_KNOWN_LINES, (sorted(N.CSQTT_FORK_OWNER), N.CSQTT_KNOWN_LINES))
slots = {l: N._csqtt_bin_shared(l) for l in ("2.1", "2.5", "mrtt")}
check("…with its own binary slot", len(set(slots.values())) == 3 and slots["mrtt"].endswith("/mrtt/csqtt-server"), slots)
MRTT_SCHEMA = """CREATE TABLE passwords (password TEXT PRIMARY KEY, ip TEXT NOT NULL DEFAULT '', expires_at INTEGER NOT NULL DEFAULT 0,
  down_bytes INTEGER NOT NULL DEFAULT 0, up_bytes INTEGER NOT NULL DEFAULT 0, vk_hash TEXT NOT NULL DEFAULT '', ports TEXT NOT NULL DEFAULT '',
  is_deactivated INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '', vk_hashes TEXT NOT NULL DEFAULT '',
  vk_token_enabled INTEGER NOT NULL DEFAULT 0, dtls_port INTEGER NOT NULL DEFAULT 0, wg_port INTEGER NOT NULL DEFAULT 0,
  local_port INTEGER NOT NULL DEFAULT 0, group_id TEXT NOT NULL DEFAULT '', routing_rule_id TEXT NOT NULL DEFAULT '',
  sub_uuid TEXT NOT NULL DEFAULT '', workers INTEGER, max_devices INTEGER, devices_json TEXT NOT NULL DEFAULT '{}',
  transport TEXT NOT NULL DEFAULT '', exit TEXT NOT NULL DEFAULT '', link_room_off INTEGER NOT NULL DEFAULT 0)"""   # the port's own (rig 2026-11-24)
with tempfile.TemporaryDirectory() as td:
    c = sqlite3.connect(os.path.join(td, "csqtt.db"))
    c.execute(MRTT_SCHEMA)
    c.execute("INSERT INTO passwords (password, ip, up_bytes, down_bytes, name) VALUES ('pwA', '10.66.68.3', 11, 22, 'alice')")
    c.commit(); c.close()
    st = {}
    try:
        st = N._csqtt_read_store(td, "mrtt") or {}
    except Exception as e:
        st = {"error": repr(e)}
    e = (st.get("passwords") or {}).get("pwA") or {}
check("…and reads its store (MRTT's schema) by the password's own address, with its traffic",
      e.get("ip") == "10.66.68.3" and e.get("up_bytes") == 11 and e.get("down_bytes") == 22 and e.get("name") == "alice", st)

print("\n[3] the catalog")
TC = P.TURN_CLIENTS
m = TC.get("mrttapp") or {}
check("the MRTT app speaks mrtt only, one-tap on Android", m.get("csqtt_lines") == ["mrtt"] and m["platforms"]["android"].get("autostart") is True, m)
tre = m["platforms"]["android"].get("tag_re", "")
check("…its stable releases, a fix release too, not -legacy or a beta",
      [t for t in ("v1.0", "v1.1", "v1.0.1", "v1.0-beta1", "v2.5.0-legacy", "v2.1.9-legacy") if re.search(tre, t)] == ["v1.0", "v1.1", "v1.0.1"], tre)
check("Rawline speaks 2.5 and mrtt", TC["rawline"].get("csqtt_lines") == ["2.5", "mrtt"])
speakers = sorted(cid for cid, c in TC.items() if "mrtt" in (c.get("csqtt_lines") or []))
check("no other app speaks mrtt", speakers == ["mrttapp", "rawline"], speakers)
cm, cc = P._turn_compat("mrtt"), P._turn_compat("csqtt")
check("the fork mrtt offers the MRTT app (native) and Rawline, with no client settings; csqtt's offers no MRTT app",
      cm == {"mrttapp": "native", "rawline": "friendly"} and P._client_schema_for("mrtt", "mrttapp") == [] and "mrttapp" not in cc, (cm, sorted(cc)))

print("\n[4] the link")
JS = r"""
global.window = global; require(process.argv[1]); const T = global.SWGTurn;
const c = { host: "203.0.113.7", port: 56005, password: "pw6", vk_links: ["https://vk.ru/call/join/h1"] };
const nohash = { host: "203.0.113.7", port: 56005, password: "pw6", vk_links: [] };
const open = async (link, seed, pre) => { try {
  const b = Buffer.from(link.slice(pre.length).replace(/-/g, "+").replace(/_/g, "/"), "base64");
  const k = await crypto.subtle.importKey("raw", await crypto.subtle.digest("SHA-256", new TextEncoder().encode(seed)), {name: "AES-GCM"}, false, ["decrypt"]);
  return new TextDecoder().decode(await crypto.subtle.decrypt({name: "AES-GCM", iv: b.subarray(0, 12)}, k, b.subarray(12)));
} catch (e) { return ""; } };
(async () => {
  const m = await T.csqttArtifact(c, "csqtt", "mrtt").buildAsync(), r = await T.csqttArtifact(c, "rawline", "mrtt").buildAsync();
  const v25 = await T.csqttArtifact(c, "csqtt", "2.5").buildAsync();
  console.log(JSON.stringify({ m, r, v25, mOpen: await open(m, "mrtt-chiper-key", "mrtt://"), mByCsqtt: await open(m, "csqtt-chiper-key", "mrtt://"),
    v25Open: await open(v25, "csqtt-chiper-key", "csqtt://"), app: T.csqttArtifact(c, "csqtt", "mrtt").app,
    srcM: T.csqttArtifact(c, "csqtt", "mrtt").src, src25: T.csqttArtifact(c, "csqtt", "2.5").src,
    vkM: T.csqttArtifact(nohash, "csqtt", "mrtt").vkMissing, vk25: T.csqttArtifact(nohash, "csqtt", "2.5").vkMissing,
    vkR: T.csqttArtifact(nohash, "rawline", "mrtt").vkMissing }));
})();
"""
with tempfile.TemporaryDirectory() as td:
    ta = os.path.join(td, "turn-artifacts.js")
    open(ta, "w", encoding="utf-8").write(source("turn-artifacts.js"))
    pr = subprocess.run(["node", "-e", JS, ta], capture_output=True, text=True, timeout=60)
try:
    o = json.loads(pr.stdout.strip().splitlines()[-1])
except Exception:
    o = {}
check("node sealed the links", bool(o), pr.stderr[-300:])
if o:
    check("an mrtt server's link is mrtt://, and MRTT's own decoder opens it to the server",
          o["m"].startswith("mrtt://") and o["mOpen"].startswith("connect?v=2&host=203.0.113.7&peer=56005&password=pw6&hashes=h1"), (o["m"][:20], o["mOpen"]))
    check("…csqtt's decoder does not (another seed)", o["mByCsqtt"] == "", o["mByCsqtt"])
    check("…the same link for Rawline, named for MRTT", o["r"] == o["m"] and o["app"] == "MRTT", (o["r"][:20], o["app"]))
    check("a 2.5 server's link stays csqtt:// under csqtt's seed", o["v25"].startswith("csqtt://") and o["v25Open"].startswith("connect?v=2&"), o["v25"][:20])
    check("…and the two links' cache keys differ, so a sheet left open across a 2.5 ⇄ MRTT switch seals again",
          o["srcM"] != o["src25"] and o["srcM"].endswith(o["src25"]), (o["srcM"][:20], o["src25"][:20]))
    check("no VK hash: the MRTT app's link raises no \"won't authenticate\" warning (MAX or the user's own VK, in the app); a 2.5 one still does",
          o["vkM"] is False and o["vk25"] is True, (o["vkM"], o["vk25"]))
    check("…while Rawline's MRTT link keeps the warning (it is not known to manage without a hash)", o["vkR"] is True, o["vkR"])

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red under %s" % (len(FAILS), " ".join(PERTURB))) if ok
          else "PERTURB FAILED — %s planted and every check still passed" % " ".join(PERTURB))
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
