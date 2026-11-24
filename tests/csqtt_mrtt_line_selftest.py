#!/usr/bin/env python3
"""Self-test: the csqtt line `mrtt` (1.8.12 item 10, card D) — MRTT 1.0 with our integration (forks/csqtt/mrtt) as a third
csqtt line beside 2.1 and 2.5, its own apps, and its own link.

  [1] the panel: the line is on offer with its build mrtt-1.0-1, fetched from release csqtt-mrtt-1.0-1 (the node asks for
      "csqtt-" + version); its address pool is 2.5's (.3–.250); the share table vouches for the rigged build
  [2] the node: it advertises the line, gives it its own binary slot, and reads its store (csqtt.db, MRTT's schema: 2.5's
      passwords table plus MRTT's columns) by the password's own address, as a 2.5 store
  [3] the catalog: the MRTT app speaks mrtt only (one-tap on Android, its stable v* releases, not -legacy or a beta);
      Rawline speaks 2.5 and mrtt; no other app speaks mrtt; none takes client settings
  [4] the link (node): an mrtt server's link is mrtt:// sealed under MRTT's seed — its own decoder opens it, csqtt's does not
      — for the MRTT app and for Rawline; a 2.5 server's stays csqtt:// under csqtt's seed

Hermetic (node for [4]). Run: python3 tests/csqtt_mrtt_line_selftest.py   (0 = pass)
     --perturb-noded  the node does not know the line (it is never sent there) → RED in [2]
     --perturb-seed   an mrtt link sealed under csqtt's seed → RED in [4]
     --perturb-store  the node reads an mrtt store as a 2.1 one (through devices) → RED in [2]
"""
import json, os, re, sqlite3, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANTS = {
    "--perturb-noded": ("swg-noded", 'CSQTT_KNOWN_LINES = ("2.1", "2.5", "mrtt")', 'CSQTT_KNOWN_LINES = ("2.1", "2.5")'),
    "--perturb-seed":  ("turn-artifacts.js", 'var MRTT_LINK_SEED = "mrtt-chiper-key";', 'var MRTT_LINK_SEED = "csqtt-chiper-key";'),
    "--perturb-store": ("swg-noded", 'if "device_id" in cols and ((line or "2.1") == "2.1" or "ip" not in cols):',
                        'if True:'),
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
check("mrtt is on offer, beside 2.1 and 2.5", list(P.CSQTT_LINES)[-1] == "mrtt" and {"2.1", "2.5"} <= set(P.CSQTT_LINES), list(P.CSQTT_LINES))
check("…its build mrtt-1.0-1 from release csqtt-mrtt-1.0-1 (the node asks for csqtt- + version)",
      P.CSQTT_LINES["mrtt"][0] == ("mrtt-1.0-1", "csqtt-mrtt-1.0-1") and P._csqtt_tag_for("mrtt-1.0-1") == "csqtt-" + "mrtt-1.0-1",
      P.CSQTT_LINES.get("mrtt"))
check("…its current build", P._csqtt_current_version("mrtt") == "mrtt-1.0-1")
check("its pool is 2.5's", P.turn_cap("csqtt", {"line": "mrtt"}) == P.turn_cap("csqtt", {"line": "2.5"}) == 248)
check("the share table vouches for the rigged build", "mrtt-1.0-1" in P.KEYLESS_SHARE_BUILDS["csqtt"]["raw"])

print("\n[2] the node")
check("it advertises mrtt", "mrtt" in N.CSQTT_KNOWN_LINES, N.CSQTT_KNOWN_LINES)
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
check("…its stable releases, not -legacy or a beta", [t for t in ("v1.0", "v1.1", "v1.0-beta1", "v2.5.0-legacy", "v2.1.9-legacy") if re.search(tre, t)] == ["v1.0", "v1.1"], tre)
check("Rawline speaks 2.5 and mrtt", TC["rawline"].get("csqtt_lines") == ["2.5", "mrtt"])
speakers = sorted(cid for cid, c in TC.items() if "mrtt" in (c.get("csqtt_lines") or []))
check("no other app speaks mrtt", speakers == ["mrttapp", "rawline"], speakers)
cm = P._turn_compat("csqtt")
check("csqtt servers list both, with no client settings", cm.get("mrttapp") == "friendly" and P._client_schema_for("csqtt", "mrttapp") == [], cm)

print("\n[4] the link")
JS = r"""
global.window = global; require(process.argv[1]); const T = global.SWGTurn;
const c = { host: "203.0.113.7", port: 56005, password: "pw6", vk_links: ["https://vk.ru/call/join/h1"] };
const open = async (link, seed, pre) => { try {
  const b = Buffer.from(link.slice(pre.length).replace(/-/g, "+").replace(/_/g, "/"), "base64");
  const k = await crypto.subtle.importKey("raw", await crypto.subtle.digest("SHA-256", new TextEncoder().encode(seed)), {name: "AES-GCM"}, false, ["decrypt"]);
  return new TextDecoder().decode(await crypto.subtle.decrypt({name: "AES-GCM", iv: b.subarray(0, 12)}, k, b.subarray(12)));
} catch (e) { return ""; } };
(async () => {
  const m = await T.csqttArtifact(c, "csqtt", "mrtt").buildAsync(), r = await T.csqttArtifact(c, "rawline", "mrtt").buildAsync();
  const v25 = await T.csqttArtifact(c, "csqtt", "2.5").buildAsync();
  console.log(JSON.stringify({ m, r, v25, mOpen: await open(m, "mrtt-chiper-key", "mrtt://"), mByCsqtt: await open(m, "csqtt-chiper-key", "mrtt://"),
    v25Open: await open(v25, "csqtt-chiper-key", "csqtt://"), app: T.csqttArtifact(c, "csqtt", "mrtt").app }));
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

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d check(s) went red under %s" % (len(FAILS), " ".join(PERTURB))) if ok
          else "PERTURB FAILED — %s planted and every check still passed" % " ".join(PERTURB))
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
