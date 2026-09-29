#!/usr/bin/env python3
"""Self-test — AmneziaWG 3.1, the client configs (docs/AWG3-PLAN.md §7.5, gate G12).

An interface is 3.1 when its dict holds a HeaderProtectionKey (§7.1). Every config a client is handed from such an
interface must carry the 3.1 set exactly once, RandomTrailers as `1` (the one spelling every parser takes — `on` fails
free-turn 3.2.0, `true` fails the tools), never AdvancedSecurity, never DisableCookies (D-cookies), and a keepalive of
`k-(k+10)` derived from the integer the panel resolves — except free-turn's link, which carries `k` (FreeTurn 4.3.0 pins
core 3.2.0, whose Atoi rejects a range). A 2.0 interface renders exactly as before. Every emitter is the REAL code: the
panel's js/crypto.js and sub.js's twin run under node, turn-artifacts.js is evaluated as the browser loads it, and the
subscription bundle comes from swg-sub's own read_data over a fixture state.

  [1] crypto.js buildConf — 3.1: the set once, `1`, no DisableCookies / AdvancedSecurity, keepalive 25-35 (0 stays 0,
      30 → 30-40, blank → the 25 default); 2.0 and a 2.0 dict holding a stray one-sided 3.x key: no 3.x key, keepalive k
  [2] sub.js buildConf renders every case of [1] byte-for-byte as crypto.js does (the subscription page's QR)
  [3] rerenderConf rebuilds the AWG block from live meta: a config built at 2.0 gains the set after a switch to 3.1, one
      built at 3.1 loses it after a switch back, both idempotent; a 2.0 config on a 2.0 interface is refreshed the way it
      always was (existing lines only)
  [4] Edit peer / a deployment's settings Save (js/sheets-crud.js) re-parses the config getConfig returned and rebuilds
      it: that round trip keeps the generation the interface has, in both directions
  [5] the formats that embed a conf: free-turn's `wg` carries the set with `1` and a single keepalive `k`; sidecar
      carries it with `k-(k+10)`; Amnezia's vpn:// decodes to the config byte-for-byte; from a 2.0 config none
      carries a 3.x key
  [6] the swg-sub bundle: a 3.1 interface's deployment renders the set; one switched back to 2.0 while its node still
      reports the 3.x keys (offline, or not yet applied) renders none — the record decides, as in the panel

Run: python3 tests/awg3_render_selftest.py            (0 = pass; needs node)
     --perturb <name>   plants one regression in a copy of the tree and expects RED on exactly its sections:
                        rerender [3][4] · empty-meta [3] · keepalive [1][2][3][4][5] · bool [1][2][3] · cookies [1][2][3] · gen [1][2] ·
                        sub [2][6] · freeturn [5] · swgsub [6]
"""
import hashlib, importlib.machinery, importlib.util, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

PLANTS = {   # name: (file, anchor, replacement, the sections it must redden)
    "rerender": ("js/crypto.js", "  if (!AWG_ORDER.slice(AWG3_FROM).some(k => awg[k] != null || lineRe(k).test(out))) {\n",
                 "  if (true) {\n", ["[3]", "[4]"]),
    "keepalive": ("js/crypto.js", '  return g31 && /^\\s*\\d+\\s*$/.test(String(k)) && +k > 0 ? (+k) + "-" + (+k + 10) : k;\n',
                  "  return k;\n", ["[1]", "[2]", "[3]", "[4]", "[5]"]),
    "bool": ("js/crypto.js", '    if (k === "RandomTrailers") { if (!/^\\s*(0|off)\\s*$/i.test(String(awg[k]))) L.push(k + " = 1"); return; }',
             "", ["[1]", "[2]", "[3]"]),
    "cookies": ("js/crypto.js", '(i >= AWG3_FROM && (!g31 || k === "DisableCookies"))', "(i >= AWG3_FROM && !g31)",
                ["[1]", "[2]", "[3]"]),
    "empty-meta": ("js/crypto.js", "  if (!Object.keys(awg).length) return out;   // no AWG dict to render from (a report without one): leave the block as it is\n",
                   "", ["[3]"]),
    "gen": ("js/crypto.js", '(i >= AWG3_FROM && (!g31 || k === "DisableCookies"))', '(k === "DisableCookies")', ["[1]", "[2]"]),
    "sub": ("sub.js", '      if (awg[k] == null || (i >= from && (!g31 || k === "DisableCookies"))) continue;\n',
            "      if (awg[k] == null) continue;\n", ["[2]", "[6]"]),
    "freeturn": ("turn-artifacts.js", '      return l.trim().replace(/^(PersistentKeepalive\\s*=\\s*)(\\d+)\\s*-\\s*\\d+$/i, "$1$2");\n',
                 "      return l.trim();\n", ["[5]"]),
    "swgsub": ("swg-sub", "            ifc[\"awg_params\"] = {**{k: v for k, v in rep_awg.items() if k not in AWG3_FIELDS},\n",
               "            ifc[\"awg_params\"] = {**rep_awg,\n", ["[6]"]),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

if not shutil.which("node"):
    print("  FAIL no node on PATH — the emitters are JavaScript and this gate cannot run, which is not a pass"); sys.exit(1)

TMP = tempfile.mkdtemp(prefix="awg3-render-")
TREE = ROOT
if MODE:
    f, old, new, _ = PLANTS[MODE]
    TREE = os.path.join(TMP, "tree")
    for d in ("js", "vendor"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(TREE, d))
    os.makedirs(os.path.join(TREE, "tests"))
    for n in ("tests/spa_env.mjs", "tests/spa_hooks.mjs", "reconcile.js", "sub.js", "turn-artifacts.js", "swg-sub", "VERSION"):
        if os.path.exists(os.path.join(ROOT, n)):
            shutil.copy2(os.path.join(ROOT, n), os.path.join(TREE, n))
    src = open(os.path.join(TREE, f), encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    open(os.path.join(TREE, f), "w", encoding="utf-8").write(src.replace(old, new))
    print("== PERTURB %s planted in %s" % (MODE, f))

# ── the fixtures ──────────────────────────────────────────────────────────────────────────────────────────────────────
HPK = "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0="
BASE20 = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33",
          "H1": "103509605-103509620", "H2": "1694692368-1694692383", "H3": "2553282719-2553282734",
          "H4": "3170237912-3170237927", "I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>",
          "I4": "<b 0xc000000001><r 32><t>", "I5": "<t><r 48>"}
SET31 = {"HeaderProtectionKey": HPK, "RandomTrailers": "1", "ContentPaddingAddition": "10-100", "RekeyAfterTime": "100-120",
         "RekeyTimeout": "3-7", "RejectAfterTime": "150-180", "KeepaliveTimeout": "5-15", "MaxHandshakeAttempts": "15-20"}
FULL31 = {**BASE20, **SET31}
ONBOARD31 = {**FULL31, "RandomTrailers": "on", "DisableCookies": "on"}     # a 3.1 interface taken over — blessed as the node said
STRAY20 = {**BASE20, "ContentPaddingAddition": "10-100", "DisableCookies": "1"}   # 2.0: one-sided server keys only, no HPK
INT20 = {k: (int(v) if v.isdigit() else v) for k, v in BASE20.items()}   # blessed from a node report: ints where it gave ints
AWG3 = ["HeaderProtectionKey", "RandomTrailers", "ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout", "RejectAfterTime",
        "KeepaliveTimeout", "MaxHandshakeAttempts", "DisableCookies"]
O = {"privkey": "cPrivKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "address": "10.9.0.7/32", "dns": ["1.1.1.1", "8.8.8.8"],
     "mtu": 1280, "server_pubkey": "sPubKeyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "psk": "pskAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
     "endpoint": "203.0.113.7:51820", "allowed": "0.0.0.0/0, ::/0", "keepalive": 25}
BUILD = {"31": {**O, "awg_params": FULL31}, "31-onboard": {**O, "awg_params": ONBOARD31},
         "31-ka0": {**O, "awg_params": FULL31, "keepalive": 0}, "31-ka30s": {**O, "awg_params": FULL31, "keepalive": "30"},
         "31-kablank": {**O, "awg_params": FULL31, "keepalive": ""},
         "20": {**O, "awg_params": BASE20}, "20-ka0": {**O, "awg_params": BASE20, "keepalive": 0},
         "20-ka30s": {**O, "awg_params": BASE20, "keepalive": "30"}, "20-int": {**O, "awg_params": INT20},
         "20-stray": {**O, "awg_params": STRAY20}, "wg": {**O, "awg_params": {}}}
EXP_KA = {"31": "25-35", "31-onboard": "25-35", "31-ka0": "0", "31-ka30s": "30-40", "31-kablank": "25-35",
          "20": "25", "20-ka0": "0", "20-ka30s": "30", "20-int": "25", "20-stray": "25", "wg": "25"}
META31 = {"endpoint": O["endpoint"], "awg_params": FULL31}
META20 = {"endpoint": O["endpoint"], "awg_params": BASE20}
TP_FT = {"service": "vk-turn-proxy-samosvalishe-56100", "listen": "203.0.113.7:56100", "connect": "127.0.0.1:51820",
         "wrap_key": "ab" * 32, "params": "-obf-profile rtpopus -obf-key " + "ab" * 32}
TP_SC = {"service": "vk-turn-proxy-Moroka8-56200", "listen": "203.0.113.7:56200", "connect": "127.0.0.1:51820", "wrap_key": "cd" * 32}

# ── [6]'s input: swg-sub's own bundle over a fixture state ────────────────────────────────────────────────────────────
def load(path, name):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m

S = load(os.path.join(TREE, "swg-sub"), "swgsub_awg3")
ST = os.path.join(TMP, "state")
for d in ("subs/blobs", "stats"):
    os.makedirs(os.path.join(ST, d))
def J(rel, obj):
    with open(os.path.join(ST, rel), "w") as fh:
        json.dump(obj, fh)
TOKEN = "t0k3n-awg3-render"
J("fleet.json", {"roster_path": ST + "/users.json", "nodes_path": ST + "/nodes.json", "stats_dir": ST + "/stats",
                 "sub_dir": ST + "/subs"})
J("subs/serve.json", {"enabled": True})
J("subs/users.json", {"u1": {"enabled": True, "token_sha": hashlib.sha256(TOKEN.encode()).hexdigest()}})
J("subs/blobs/u1.json", {"p1": {"sec": "c2VhbGVk"}})
J("users.json", {"users": {"u1": {"name": "Anna"}},
                 "peers": {"p1": {"id": "p1", "user_id": "u1", "title": "phone",
                                  "targets": [{"node": "n1", "iface": "awg31", "type": "awg", "ip": "10.31.0.2/32"},
                                              {"node": "n1", "iface": "awgback", "type": "awg", "ip": "10.32.0.2/32"},
                                              {"node": "n1", "iface": "awgonb", "type": "awg", "ip": "10.33.0.2/32"}]}}})
J("nodes.json", {"n1": {"name": "q-node", "endpoint_host": "203.0.113.7",
                        "ifaces": {"awg31": {"awg_params": FULL31}, "awgback": {"awg_params": BASE20},
                                   "awgonb": {"awg_params": ONBOARD31}}}})
_meta = lambda port, sub: {"public_key": O["server_pubkey"], "listen_port": port, "subnet": sub, "awg_params": FULL31}
J("stats/stats-n1.json", {"interfaces": {"awg31": {"meta": _meta(51831, "10.31.0.0/24")},
                                          "awgback": {"meta": _meta(51832, "10.32.0.0/24")},   # awgback: not yet switched back
                                          "awgonb": {"meta": {**_meta(51833, "10.33.0.0/24"), "awg_params": ONBOARD31}}}})
_bundle = S.read_data(S.State(json.load(open(os.path.join(ST, "fleet.json")))), TOKEN) or {}
TGTS = {t["iface"]: t for p in (_bundle.get("peers") or []) for t in (p.get("targets") or [])}

# ── the emitters, run for real under node ─────────────────────────────────────────────────────────────────────────────
HARNESS = r"""
import fs from "node:fs"; import vm from "node:vm"; import zlib from "node:zlib"; import { pathToFileURL } from "node:url";
const IN = JSON.parse(fs.readFileSync(0, "utf8")), R = IN.root;
const { spa } = await import(pathToFileURL(R + "/tests/spa_env.mjs").href);
const C = await spa("crypto.js"), { Store } = await spa("store.js");
// sub.js is a classic script: take its twin functions out whole (brackets matched, not regexed), as the page defines them.
const subSrc = fs.readFileSync(R + "/sub.js", "utf8");
function grab(head) {
  const i = subSrc.indexOf(head); if (i < 0 || subSrc.indexOf(head, i + 1) >= 0) throw new Error("sub.js: not exactly one " + head);
  const open = head.endsWith("[") ? "[" : "{", close = open === "[" ? "]" : "}";
  let j = open === "[" ? i + head.length - 1 : subSrc.indexOf("{", i), d = 0;
  for (let k = j; k < subSrc.length; k++) { if (subSrc[k] === open) d++; else if (subSrc[k] === close && --d === 0) return subSrc.slice(i, k + 1) + ";\n"; }
  throw new Error("sub.js: unbalanced " + head);
}
const SUB = new Function(grab("var AWG_ORDER = [") + grab("function guardAllowed(") + grab("function buildConf(") +
                         grab("function confFor(") + "return { buildConf, confFor };")();
vm.runInThisContext(fs.readFileSync(R + "/turn-artifacts.js", "utf8"));
const TA = globalThis.SWGTurn;
const unlink = s => Buffer.from(s.replace(/^[a-z]+:\/\//, ""), "base64url");
const out = [];
for (const c of IN.ops) {
  if (c.op === "build") out.push((c.impl === "sub" ? SUB : C).buildConf(c.o));
  else if (c.op === "rerender") { Store.ifaceMeta = () => c.meta; out.push(C.rerenderConf(c.conf, "n1", "awg0")); }
  else if (c.op === "roundtrip") {           // js/sheets-crud.js ~804: parse what getConfig returned, rebuild it
    Store.ifaceMeta = () => c.meta;
    const s = C.parseFullConf(C.rerenderConf(c.conf, "n1", "awg0"));
    out.push(C.buildConf({ privkey: s.privkey, address: s.address, dns: s.dns, mtu: s.mtu, awg_params: s.awg_params,
      server_pubkey: s.server_pubkey, psk: s.psk, endpoint: s.endpoint, allowed: s.allowed, keepalive: String(s.keepalive) }));
  } else if (c.op === "art") {
    const a = TA.artifact(c.conf, c.tp, "", {}, [], c.as || undefined);
    const t = a.text != null ? a.text : await a.buildAsync();
    out.push(c.as === "freeturn" ? JSON.parse(unlink(t).toString("utf8")).wg : t);
  } else if (c.op === "vpn") {
    const b = unlink(await TA.amneziaVpn(c.conf));
    out.push(zlib.inflateSync(b.subarray(4)).toString("utf8"));
  } else if (c.op === "confFor") out.push(SUB.confFor(c.secret, c.tgt));
}
console.log(JSON.stringify(out));
"""
_ops, _idx = [], {}
def op(key, **kw):
    _idx[key] = len(_ops); _ops.append(kw)

for k, o in BUILD.items():
    op("c/" + k, op="build", impl="crypto", o=o)
    op("s/" + k, op="build", impl="sub", o=o)

def run(ops):
    p = subprocess.run(["node", "--input-type=module", "-e", HARNESS], input=json.dumps({"root": TREE, "ops": ops}),
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        print("  FAIL the node harness did not run: " + (p.stderr or "")[-1500:]); sys.exit(1)
    return json.loads(p.stdout)

first = run(_ops)
R1 = {k: first[i] for k, i in _idx.items()}
C20, C31, CON = R1["c/20"], R1["c/31"], R1["c/31-onboard"]
_ops, _idx = [], {}
op("up", op="rerender", conf=C20, meta=META31)
op("down", op="rerender", conf=C31, meta=META20)
op("wg-up", op="rerender", conf=R1["c/wg"], meta={"endpoint": O["endpoint"], "awg_params": {}})
op("31-nodict", op="rerender", conf=C31, meta={"endpoint": O["endpoint"], "awg_params": {}})
op("31-nokey", op="rerender", conf=C31, meta={"endpoint": O["endpoint"]})
op("jc", op="rerender", conf=C20, meta={"endpoint": "198.51.100.9:443", "awg_params": {**BASE20, "Jc": "7"}})
op("noI5", op="rerender", conf=C20, meta={"endpoint": O["endpoint"], "awg_params": {k: v for k, v in BASE20.items() if k != "I5"}})
op("onb-up", op="rerender", conf=C20, meta={"endpoint": O["endpoint"], "awg_params": ONBOARD31})
op("rt-up", op="roundtrip", conf=C20, meta=META31)
op("rt-down", op="roundtrip", conf=C31, meta=META20)
op("rt-20", op="roundtrip", conf=C20, meta=META20)
for tag, conf in (("31", C31), ("20", C20)):
    op("ft/" + tag, op="art", conf=conf, tp=TP_FT, **{"as": "freeturn"})
    op("sc/" + tag, op="art", conf=conf, tp=TP_SC)
    op("vpn/" + tag, op="vpn", conf=conf)
SECRET = {"k": O["privkey"], "p": O["psk"]}
for ifn in ("awg31", "awgback", "awgonb"):
    if ifn in TGTS:
        op("sub/" + ifn, op="confFor", secret=SECRET, tgt=TGTS[ifn])
second = run(_ops)
R2 = {k: second[i] for k, i in _idx.items()}
# idempotence: a rerender of a rerender is the same text
_ops, _idx = [], {}
op("up2", op="rerender", conf=R2["up"], meta=META31)
op("down2", op="rerender", conf=R2["down"], meta=META20)
R3 = {k: v for k, v in zip(_idx, run(_ops))}

# ── the rules, stated once ────────────────────────────────────────────────────────────────────────────────────────────
def lines(conf):
    return [l.strip() for l in (conf or "").splitlines()]
def keyvals(conf):
    return [(l.split("=", 1)[0].strip(), l.split("=", 1)[1].strip()) for l in lines(conf) if "=" in l]
def ka(conf):
    return [v for k, v in keyvals(conf) if k == "PersistentKeepalive"]
def rules31(label, conf, want_ka):
    kv = keyvals(conf)
    names = [k for k, _ in kv]
    check(label + ": each of the 3.1 set exactly once", all(names.count(k) == 1 for k in SET31),
          {k: names.count(k) for k in SET31})
    check(label + ": RandomTrailers = 1", dict(kv).get("RandomTrailers") == "1", dict(kv).get("RandomTrailers"))
    check(label + ": no DisableCookies, no AdvancedSecurity", "DisableCookies" not in names and "AdvancedSecurity" not in names, names)
    check(label + ": the HeaderProtectionKey is the interface's", dict(kv).get("HeaderProtectionKey") == HPK)
    check(label + ": PersistentKeepalive = %s" % want_ka, ka(conf) == [want_ka], ka(conf))
def rules20(label, conf, want_ka):
    names = [k for k, _ in keyvals(conf)]
    check(label + ": no AmneziaWG 3.x key", not [k for k in names if k in AWG3 or k == "AdvancedSecurity"], names)
    check(label + ": PersistentKeepalive = %s" % want_ka, ka(conf) == [want_ka], ka(conf))

try:
    SECTION[0] = "[1]"
    print("[1] js/crypto.js buildConf")
    for k in BUILD:
        (rules31 if k.startswith("31") else rules20)("buildConf " + k, R1["c/" + k], EXP_KA[k])
    check("buildConf 31-onboard: DisableCookies is never rendered, RandomTrailers `on` goes as 1",
          "DisableCookies" not in R1["c/31-onboard"] and "RandomTrailers = 1" in lines(R1["c/31-onboard"]))
    check("buildConf 20-stray: a one-sided key on a 2.0 interface stays on the server",
          "ContentPaddingAddition" not in R1["c/20-stray"] and R1["c/20-stray"] == R1["c/20"], R1["c/20-stray"])
    check("buildConf 20: the 2.0 AWG block is BASE20 in list order, I-lines whole",
          [l for l in lines(R1["c/20"]) if l.split(" ")[0] in BASE20] == ["%s = %s" % kv for kv in BASE20.items()])

    SECTION[0] = "[2]"
    print("\n[2] sub.js buildConf is the same config")
    for k in BUILD:
        check("sub.js " + k + " == crypto.js " + k, R1["s/" + k] == R1["c/" + k],
              [a + "  |  " + b for a, b in zip(lines(R1["s/" + k]), lines(R1["c/" + k])) if a != b])

    SECTION[0] = "[3]"
    print("\n[3] rerenderConf rebuilds the AWG block when the generation is in play")
    check("a config built at 2.0, after the switch to 3.1, is the 3.1 config", R2["up"] == C31,
          [l for l in lines(R2["up"]) if l not in lines(C31)] or lines(R2["up"])[-3:])
    rules31("rerender up", R2["up"], "25-35")
    check("a config built at 3.1, after the switch back, is the 2.0 config", R2["down"] == C20,
          [l for l in lines(R2["down"]) if l not in lines(C20)])
    rules20("rerender down", R2["down"], "25")
    check("both are idempotent", R3["up2"] == R2["up"] and R3["down2"] == R2["down"])
    rules31("rerender onto a taken-over 3.1 interface", R2["onb-up"], "25-35")
    check("a plain WireGuard config stays plain", R2["wg-up"] == R1["c/wg"])
    check("a 3.1 config whose interface meta carries no AWG dict (a report without one) is left as it is, as before",
          R2["31-nodict"] == C31 and R2["31-nokey"] == C31, [l for l in lines(C31) if l not in lines(R2["31-nodict"])][:4])
    check("2.0 on 2.0: Jc and the Endpoint refreshed, nothing else moved (the refresh it always was)",
          R2["jc"] == C20.replace("Jc = 4", "Jc = 7").replace(O["endpoint"], "198.51.100.9:443"), R2["jc"])
    check("2.0 on 2.0: a line the interface no longer has is kept, as it always was", R2["noI5"] == C20)

    SECTION[0] = "[4]"
    print("\n[4] the Edit-peer / settings Save round trip keeps the generation")
    check("built at 2.0, saved after the switch to 3.1 → the 3.1 config", R2["rt-up"] == C31,
          [l for l in lines(R2["rt-up"]) if l not in lines(C31)])
    check("built at 3.1, saved after the switch back → the 2.0 config", R2["rt-down"] == C20,
          [l for l in lines(R2["rt-down"]) if l not in lines(C20)])
    check("control: 2.0 saved on 2.0 is unchanged", R2["rt-20"] == C20)
    rules31("the Save after the switch to 3.1", R2["rt-up"], "25-35")
    rules20("the Save after the switch back", R2["rt-down"], "25")

    SECTION[0] = "[5]"
    print("\n[5] the formats that embed a config")
    rules31("free-turn wg", R2["ft/31"], "25")
    check("free-turn wg: MTU still rides in its own field, not the conf", not any(l.startswith("MTU") for l in lines(R2["ft/31"])))
    rules31("sidecar", R2["sc/31"], "25-35")
    check("Amnezia vpn:// decodes to the 3.1 config byte-for-byte", R2["vpn/31"] == C31)
    for f in ("ft", "sc"):
        rules20(f + " from a 2.0 config", R2[f + "/20"], "25")
    check("Amnezia vpn:// of a 2.0 config is that config", R2["vpn/20"] == C20)

    SECTION[0] = "[6]"
    print("\n[6] the swg-sub bundle")
    check("the bundle carries the three deployments", set(TGTS) == {"awg31", "awgback", "awgonb"}, sorted(TGTS))
    if "sub/awg31" in R2:
        rules31("sub page, 3.1 interface", R2["sub/awg31"], "25-35")
    if "sub/awgback" in R2:
        check("switched back, node still reporting 3.x: the bundle's dict has none",
              not [k for k in (TGTS["awgback"].get("awg") or {}) if k in AWG3], TGTS["awgback"].get("awg"))
        rules20("sub page, switched back while the node still reports 3.x", R2["sub/awgback"], "25")
    if "sub/awgonb" in R2:
        rules31("sub page, a taken-over 3.1 interface (RandomTrailers on, DisableCookies)", R2["sub/awgonb"], "25-35")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if MODE:
    want = sorted(PLANTS[MODE][3])
    red = sorted({s for s, _ in FAILS})
    ok = red == want
    print(("PERTURB OK — %s went red on %s" if ok else "PERTURB FAILED — %s: red sections %s, wanted exactly %s")
          % ((MODE, want) if ok else (MODE, red, want)))
    sys.exit(0 if ok else 1)
if FAILS:
    print("FAILED: " + "; ".join("%s %s" % f for f in FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
