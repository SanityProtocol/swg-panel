#!/usr/bin/env python3
"""Self-test — an I1–I5 line the panel stores must be one every app reads (docs/AWG-MIMICRY-PLAN.md F7, F9; P2).

An app that cannot read one I line refuses the WHOLE config, and a node whose live `awg set` fails keeps the line in its
conf and fails the interface's next start. The Edit sheet checks a changed line (js/mimic.js mimicCheck); the panel checks
it again on /api/iface/update (awg_i_check), so an API caller or an older cached SPA cannot store one either.

  [1] the twins: one corpus — the shapes measured at setconf on swgt 2026-10-08, the refusals, and 300 renders of each
      preset — through js/mimic.js mimicCheck and the panel's awg_i_check: the same verdict, reason and byte count per line
  [2] the refusals speak the Edit sheet's words: the panel's six sentences are the six of js/iface.js mimicWhy (one catalog
      entry each, so the Russian is the same on both paths)
  [3] a REAL panel process (temp state, scratch port, no auth; the node is played by POSTing snapshots):
      a QUIC and a DNS preset are stored; <r 1001>, <c>, two <t>, a line break, an unknown tag are refused naming the cell,
      the record untouched; a line break in S1 (not an I line) is refused too; "-" still removes a line; a line the record — or, under a partial record, the node's report —
      already holds is re-sent with an unrelated edit and the save goes through; changing that line to another bad one is refused

  [4] the templates every new interface or mesh link is made from (Settings → interface defaults, the fleet's and a link's
      mesh_awg) go through the same check in awg_template_refusal: a changed bad I line and a line break in S1 are
      refused, a stored bad line re-sent with an unrelated change is saved, and all three save sites pass the stored one

Run: python3 tests/awg_i_check_selftest.py      (0 = pass; needs node)
     --perturb cap|nocheck|resent|tplcheck|ctl|ascii|huge   plants one regression in a copy of swg-panel-server and expects RED:
        cap      the 1000-byte cap gone from awg_i_check          → [1] [3]
        nocheck  the check gone from /api/iface/update             → [3]
        resent   a line the node reports counts as a change        → [3]
        tplcheck the check gone from the template saves            → [4]
        ctl      control characters allowed in fields other than I → [3] [4]
        ascii    the character rule back to C0 controls only       → [1] [3]
        huge     no ceiling on a packet's size                     → [1]
"""
import importlib.machinery, importlib.util, json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None
PLANTS = {
    "cap": ["            if int(arg) > AWG_I_TAG_MAX:", "            if False:"],
    "ascii": ['_AWG_BAD_CHAR = re.compile(r"[^\\x20-\\x7e]")', '_AWG_BAD_CHAR = re.compile(r"[\\x00-\\x1f\\x7f]")'],
    "huge": ['return (False, 0, "huge", "") if n > AWG_I_UDP_MAX else (True, n, "", "")', 'return (True, n, "", "")'],
    "nocheck": ["                        _ib = awg_value_refusal(_k, clean[_k])", "                        _ib = None"],
    "tplcheck": ["            _b = awg_value_refusal(k, v)\n            if _b:\n                return _b",
                 "            _b = None\n            if _b:\n                return _b"],
    "ctl": ["    if _AWG_BAD_CHAR.search(_awg_trim(v)):\n        return perr(", "    if False:\n        return perr("],
    "resent": ["clean[_k] not in (str(_rec_u.get(_k, \"\")).strip(), str(_rep_ap.get(_k, \"\")).strip())",
               "clean[_k] != str(_rec_u.get(_k, \"\")).strip()"],
}
if MODE and MODE not in PLANTS:
    sys.exit("unknown perturbation " + MODE)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail != "" and not ok else ""))
    if not ok:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="awg-i-check-")
SERVER = os.path.join(ROOT, "swg-panel-server")
if MODE:
    s = open(SERVER, encoding="utf-8").read()
    a, b = PLANTS[MODE]
    assert s.count(a) == 1, "plant anchor did not match exactly once — this run would measure nothing"
    SERVER = os.path.join(TMP, "swg-panel-server")
    open(SERVER, "w", encoding="utf-8").write(s.replace(a, b))
os.environ["SWG_NO_REEXEC"] = "1"
_l = importlib.machinery.SourceFileLoader("swgpanel_icheck", SERVER)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_icheck", _l))
_l.exec_module(P)

# ── [1] ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("[1] one verdict per line, in both languages")
CORPUS = ["", "-", " - ", "<r 3><r 4>", "<r 3> <r 4>", " <r 3>", "<r 0>", "<b 0xABCD>", "<b 0xabc>", "<b abc>", "<b 0x>",
          "<r 1000>", "<r 1001>", "<rc 1001>", "<rd 5000>", "<t><t>", "<t><r 4><t>", "<rc 5><rd 5>", "<c>", "<c><r 3>",
          "<r 3>\n<r 4>", "<r 3>\t", "<r 3>\t<r 4>", "<x 3>",
          # code review 2026-10-08: Unicode line breaks the node's splitlines() splits on, Unicode spaces the two languages
          # trimmed differently, a BOM pasted from an editor, the UDP ceiling
          "<r 3>\u2028<r 4>", "<r 3>\u2029", "<r 3>\x85<r 4>", "\x85<r 3>", "<r 3>\ufeff<r 4>", "\ufeff<r 3>", "<r 3>\u00a0<r 4>",
          "<r 3>\u3000", "<r 3>\x1c<r 4>", " <r 3> ", "<r 1000>" * 70, "<r 1000>" * 65 + "<r 507>", "<r 1000>" * 65 + "<r 508>", "<r 3", "junk<r 3>", "<r -3>", "<r 3 >", "<t 1>",
          "<r " + "9" * 5000 + ">", "<b 0xc000000001><r 64><t>", "<r 24><t>", "<t><r 48>", "<r 1000><r 500>",
          "<b 0xc10000000108><r 8><b 0x000044be><r 1000><r 214>",
          "<r 2><b 0x010000010000000000010377777706676f6f676c6503636f6d00000100010000291000000000000000>"]
js = r"""
const M = await import(process.argv[1]);
const lines = JSON.parse(process.argv[2]);
for (const id of ["quic", "dns", "off"]) for (let i = 0; i < 300; i++) lines.push(M.mimicRender(id).I1);
console.log(JSON.stringify(lines.map(s => [s, M.mimicCheck(s)])));
"""
r = subprocess.run(["node", "--input-type=module", "-e", js, "file://" + os.path.join(ROOT, "js", "mimic.js"), json.dumps(CORPUS)],
                   capture_output=True, text=True)
check("node ran js/mimic.js", r.returncode == 0, r.stderr[-300:])
pairs = json.loads(r.stdout) if r.returncode == 0 else []
check("the corpus and 900 renders came back", len(pairs) == len(CORPUS) + 900, len(pairs))
diff = []
for s, c in pairs:
    ok, n, why, tag = P.awg_i_check(s)
    want = (c["ok"], c.get("bytes", 0) if c["ok"] else 0, c.get("why", ""), c.get("tag", "") if not c["ok"] else "")
    if (ok, n, why, tag) != want:
        diff.append((s[:60], (ok, n, why, tag), want))
check("Python and JS agree on every line (verdict, reason, tag, bytes)", not diff, diff[:3])
v = {s: P.awg_i_check(s) for s in CORPUS}
check("what every build reads is read: spaces between tags, <r 0>, upper-case hex",
      v["<r 3> <r 4>"][:2] == (True, 7) and v["<r 0>"][:2] == (True, 0) and v["<b 0xABCD>"][:2] == (True, 2))
check("what some build refuses is refused: <r 1001>, two <t>, <c>, odd hex",
      [v[x][2] for x in ("<r 1001>", "<t><t>", "<c>", "<b 0xabc>")] == ["big", "t2", "c", "tag"])
check("a line break and an inner tab are refused; a trailing tab is trimmed, as sanitize trims what it stores",
      v["<r 3>\n<r 4>"][2] == "ctl" and v["<r 3>\t<r 4>"][2] == "ctl" and v["<r 3>\t"][:2] == (True, 3))
check("Unicode line breaks, spaces and a BOM are refused, wherever they sit",
      all(v[x][2] == "ctl" for x in ("<r 3>\u2028<r 4>", "<r 3>\u2029", "<r 3>\x85<r 4>", "\x85<r 3>", "<r 3>\ufeff<r 4>",
                                     "\ufeff<r 3>", "<r 3>\u00a0<r 4>", "<r 3>\u3000", "<r 3>\x1c<r 4>")))
check("a packet over 65,507 bytes is refused; exactly 65,507 is read",
      v["<r 1000>" * 70][2] == "huge" and v["<r 1000>" * 65 + "<r 508>"][2] == "huge" and v["<r 1000>" * 65 + "<r 507>"][:2] == (True, 65507))
check("the P0 strings: QUIC 1232 bytes, DNS 43", v[CORPUS[-2]][:2] == (True, 1232) and v[CORPUS[-1]][:2] == (True, 43))

# ── [2] ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[2] the panel says it in the Edit sheet's words")
ui = open(os.path.join(ROOT, "js", "iface.js"), encoding="utf-8").read()
mw = ui[ui.index("const mimicWhy"):ui.index("const MIMIC_BIG")]
ui_keys = set(re.findall(r'T\("(\{v1\}:[^"]*)"', mw))
srv = open(SERVER, encoding="utf-8").read()
fr = srv[srv.index("def awg_i_refusal"):srv.index("# The AmneziaWG 3.1 set an interface switched")]
srv_keys = set(re.findall(r'perr\("(\{v1\}:[^"]*)"', fr))
check("seven sentences on each side", len(ui_keys) == 7 and len(srv_keys) == 7, (len(ui_keys), len(srv_keys)))
check("…and they are the same seven", ui_keys == srv_keys, ui_keys ^ srv_keys)
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("each has its Russian", all(('"%s":' % k) in ru for k in srv_keys), [k for k in srv_keys if ('"%s":' % k) not in ru])

# ── [3] ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[3] /api/iface/update on a real panel")
BUILTIN = {"I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>", "I4": "<b 0xc000000001><r 32><t>",
           "I5": "<t><r 48>"}
BASE = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33", "H1": "103509605-103509620",
        "H2": "1694692368-1694692383", "H3": "2553282719-2553282734", "H4": "3170237912-3170237927"}
# awg1's RECORD holds a line no app reads (a hand-edited store); awg2's record is PARTIAL (F5: no I lines) while its node
# REPORTS one no app reads — the Edit sheet shows the report under the record and re-sends it. (A missing record is filled
# from the first report, so only a partial one reaches the report half of the rule — measured: without the seed the
# `resent` plant stayed green.)
REC_BAD, REP_BAD = "<r 1214>", "<c><r 8>"
ST = os.path.join(TMP, "state"); SD = os.path.join(TMP, "stats"); os.makedirs(ST); os.makedirs(SD)
json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {"awg1": {"awg_params": {**BASE, **BUILTIN, "I3": REC_BAD}},
                                                                    "awg2": {"awg_params": dict(BASE)}}}},
          open(os.path.join(ST, "nodes.json"), "w"))
open(os.path.join(ST, "users.json"), "w").write("{}\n")
TPL_BAD = "<r 1214>"   # a stored interface-defaults I1 no app reads (written before the check existed)
json.dump({"interface_defaults": {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25, "awg_params": {"I1": TPL_BAD}}},
          open(os.path.join(ST, "panel-settings.json"), "w"))
FLEET = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": os.path.join(ST, "nodes.json"), "roster_path": os.path.join(ST, "users.json"), "stats_dir": SD}, open(FLEET, "w"))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
log = open(os.path.join(TMP, "panel.log"), "w")
proc = subprocess.Popen([sys.executable, SERVER], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": FLEET, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "",
                             "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1"})

def req(path, data=None, tok=None):
    rq = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                                headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    try:
        with urllib.request.urlopen(rq, timeout=30) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

try:
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            time.sleep(0.1)
    TOK = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
    REP = {"awg0": {**BASE, **BUILTIN}, "awg1": {**BASE, **BUILTIN}, "awg2": {**BASE, **BUILTIN, "I4": REP_BAD}}

    def sync():
        s = {"hostname": "n1", "generated_at": int(time.time()), "noded_version": "t", "node_ips": ["203.0.113.7"],
             "datapath": {"awg": {"gen": {"module": "2.0", "fallback": "2.0", "tools": "2.0"}, "exact": 1}}, "interfaces": {}}
        for i, (n, a) in enumerate(sorted(REP.items())):
            s["interfaces"][n] = {"peers": [], "meta": {"public_key": "8Y1mOEM2Uv3Ez6CUfXOvsUg0dNrV4kx0mB9rp1cV3lE=",
                                  "listen_port": 51820 + i, "mtu": 1280, "subnet": "10.6%d.0.0/24" % i,
                                  "address": "10.6%d.0.1/24" % i, "awg_params": a, "tool": "awg", "endpoint": "203.0.113.7:%d" % (51820 + i)}}
        return req("/api/node/sync", {"snapshot": s}, TOK)
    sync(); sync()

    def rec(iface):
        return ((json.load(open(os.path.join(ST, "nodes.json")))["n1"].get("ifaces") or {}).get(iface) or {}).get("awg_params") or {}

    def upd(iface, ap, **kw):
        return req("/api/iface/update", {"node": "n1", "iface": iface, "awg_params": ap, **kw})

    QUIC = CORPUS[-2]; DNS = CORPUS[-1]
    c, r = upd("awg0", {**BASE, **BUILTIN, "I1": QUIC, "I2": "-", "I3": "-", "I4": "-", "I5": "-"})
    check("QUIC over the built-in set is stored, I2–I5 removed", c == 200 and r.get("ok") and rec("awg0").get("I1") == QUIC
          and not any(k in rec("awg0") for k in ("I2", "I3", "I4", "I5")), (c, r.get("error"), rec("awg0")))
    c, r = upd("awg0", {"I1": DNS})
    check("a DNS preset is stored", c == 200 and rec("awg0").get("I1") == DNS, (c, r.get("error")))
    before = dict(rec("awg0"))
    for what, ap, key in [("<r 1001>", {"I1": "<r 1001>"}, "a random part is at most 1000 bytes"),
                          ("a <c>", {"I2": "<c><r 3>"}, "<c> is gone"),
                          ("two <t>", {"I3": "<t><r 4><t>"}, "<t> appears twice"),
                          ("a line break", {"I1": "<r 3>\n<r 4>"}, "line break"),
                          ("an unknown tag", {"I5": "<x 3>"}, "apps cannot read"),
                          ("odd hex", {"I4": "<b 0xabc>"}, "apps cannot read")]:
        k = next(iter(ap))
        c, r = upd("awg0", {**before, **ap})
        check("%s in %s → 400, the cell named, the reason said" % (what, k),
              c == 400 and (r.get("error") or "").startswith(k + ":") and key in (r.get("error") or ""), (c, r.get("error")))
        check("…and the record untouched", rec("awg0") == before, rec("awg0"))
    c, r = upd("awg0", {**before, "S1": "28\nPostUp = id"})
    check("a line break in S1 (not an I line) → 400, S1 named", c == 400 and (r.get("error") or "").startswith("S1:")
          and "line break" in (r.get("error") or ""), (c, r.get("error")))
    check("…and the record untouched", rec("awg0") == before, rec("awg0"))
    c, r = upd("awg0", {**before, "H1": "103509605-103509620\u2028PostUp = id"})
    check("a Unicode line separator in H1 → 400, H1 named (the node's splitlines() would split there)",
          c == 400 and (r.get("error") or "").startswith("H1:"), (c, r.get("error")))
    c, r = upd("awg0", {**before, "S2": "94\t"})
    check("a trailing tab is trimmed, not refused", c == 200 and rec("awg0").get("S2") == "94", (c, r.get("error"), rec("awg0").get("S2")))
    before = dict(rec("awg0"))
    c, r = upd("awg0", {**before, "I1": "-"})
    check("\"-\" still removes a line", c == 200 and "I1" not in rec("awg0"), (c, r.get("error")))
    c, r = upd("awg1", {**BASE, **BUILTIN, "I3": REC_BAD}, mtu="1300")
    check("a line the RECORD already holds is re-sent with an unrelated edit — saved", c == 200 and rec("awg1").get("I3") == REC_BAD,
          (c, r.get("error")))
    c, r = upd("awg2", {**BASE, **BUILTIN, "I4": REP_BAD}, mtu="1300")
    check("a line the NODE reports is re-sent with an unrelated edit — saved", c == 200, (c, r.get("error")))
    c, r = upd("awg1", {"I3": "<r 1215>"})
    check("…changing such a line to another bad one is refused", c == 400 and (r.get("error") or "").startswith("I3:"), (c, r.get("error")))
    c, r = upd("awg1", {"I3": "<r 1000><r 214>"})
    check("…and to a good one is saved", c == 200 and rec("awg1").get("I3") == "<r 1000><r 214>", (c, r.get("error")))

    print("\n[4] the templates new interfaces and mesh links are made from")
    def ps():
        return json.load(open(os.path.join(ST, "panel-settings.json")))
    IDF = {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25}
    c, r = req("/api/panel/settings", {"interface_defaults": {**IDF, "mtu": 1300, "awg_params": {"I1": TPL_BAD}}})
    check("a stored bad I1 in the interface defaults is re-sent with an unrelated change — saved",
          c == 200 and ((ps().get("interface_defaults") or {}).get("mtu") == 1300), (c, r.get("error")))
    for what, ap, k in [("a changed bad I1", {"I1": "<r 1215>"}, "I1"), ("a <c> in I3", {"I3": "<c>"}, "I3"),
                        ("a line break in S1", {"S1": "28\nPostUp = id"}, "S1")]:
        c, r = req("/api/panel/settings", {"interface_defaults": {**IDF, "awg_params": ap}})
        check("interface defaults, %s → 400, %s named" % (what, k), c == 400 and (r.get("error") or "").startswith(k + ":"), (c, r.get("error")))
    check("…and the stored defaults untouched", (ps().get("interface_defaults") or {}).get("awg_params") == {"I1": TPL_BAD},
          (ps().get("interface_defaults") or {}).get("awg_params"))
    c, r = req("/api/panel/settings", {"interface_defaults": {**IDF, "awg_params": {"I1": "<r 1000><r 214>"}}})
    check("…a good I1 is saved", c == 200 and (ps().get("interface_defaults") or {}).get("awg_params", {}).get("I1") == "<r 1000><r 214>",
          (c, r.get("error")))
    c, r = req("/api/panel/settings", {"mesh_awg": {"I2": "<t><t>"}})
    check("the fleet's mesh_awg, two <t> in I2 → 400, I2 named", c == 400 and (r.get("error") or "").startswith("I2:"), (c, r.get("error")))
    c, r = req("/api/panel/settings", {"mesh_awg": {"I2": "<r 24><t>"}})
    check("…a good one is saved", c == 200 and (ps().get("mesh_awg") or {}).get("I2") == "<r 24><t>", (c, r.get("error")))
    srv_src = open(SERVER, encoding="utf-8").read()
    calls = re.findall(r"(?<!def )awg_template_refusal\(([^\n]*(?:\n[^\n]*was=[^\n]*)?)", srv_src)
    check("all three template saves pass the stored template (interface defaults, the fleet's mesh_awg, a link's)",
          len(calls) == 3 and all("was=" in c for c in calls), calls)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)

print()
if MODE:
    print(("PERTURB OK (%s) — %d checks went red" % (MODE, len(FAILS))) if FAILS
          else "PERTURB FAILED — the plant was in and every check still passed")
    sys.exit(0 if FAILS else 1)
print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
