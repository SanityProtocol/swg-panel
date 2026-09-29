#!/usr/bin/env python3
"""Self-test — a learned set that was recreated is written into again (swg-noded _CATL_GEN → swg-sni's `seen`).

swg-sni keeps a "written" cache per (address, category) and writes an address again only when that entry is half a
learn-TTL old. When a rule is turned off, its category's `catl_` set goes (the reaper); when it comes back the set is
recreated EMPTY — and swg-sni, still believing the address was in it, neither wrote it nor reset the connection, so the
rule routed nothing for up to half an hour. Found on the test fleet (KSNI-hostnames qualification, 2026-09-28): a Direct
rule by name, put back after other cells, left by the catch-all exit on every Hybrid SNI node.

Real programs: swg-noded's `_ensure_smart_nft` (queue on, through the nft model) and `_ensure_sni_router` (files in a
temp dir, the classifier not launched), and swg-sni's `Classifier` fed a real ClientHello.

  [1] the set is created → its generation is written to sni-sets.json
  [2] the rule goes → the set is reaped; the rule comes back → a NEW generation
  [3] swg-sni: the address it had written is written again (a first learn: queued, and the connection reset)
  [4] an unchanged pass writes nothing (the file is not rewritten)

Run: python3 tests/sni_set_regen_selftest.py      --plant nogen | nopurge   (exit 0 when caught)
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {"nogen": ("noded", "            _CATL_GEN[c] = time.time()                           # a new, empty set: swg-sni must write into it afresh",
                    "            pass"),
          "nopurge": ("sni", "            gone = {c for c, t in gen.items() if c in self.set_gen and self.set_gen[c] != t}",
                      "            gone = set()")}
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="sni-regen-")
paths = {"noded": os.path.join(ROOT, "swg-noded"), "sni": os.path.join(ROOT, "swg-sni")}
if PLANT:
    which, old, new = PLANTS[PLANT]
    src = open(paths[which]).read()
    assert src.count(old) == 1, "plant anchor missing — this run would measure nothing"
    paths[which] = os.path.join(TMP, "planted-" + which + ".py")
    open(paths[which], "w").write(src.replace(old, new, 1))


def load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NODED_STATE"] = TMP
N, S = load(paths["noded"], "noded_regen"), load(paths["sni"], "sni_regen")
N.GEO_DIR = os.path.join(TMP, "geo"); os.makedirs(N.GEO_DIR)
open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
N.SNI_MAP_PATH, N.SNI_PATTERNS_PATH = os.path.join(TMP, "sni-map.json"), os.path.join(TMP, "sni-patterns.json")
N.SNI_BLOCKS_PATH, N.SNI_SETS_PATH = os.path.join(TMP, "sni-blocks.json"), os.path.join(TMP, "sni-sets.json")


class Up:
    def poll(self):
        return None

    def terminate(self):
        pass


N._SNI_PROC.update(p=Up(), ttl=3600)
K = SmartKernel()
N.run = K
SUB = "10.188.1.0/24"
DIRECT = {"subnet": SUB, "category": "custom_d", "action": "direct"}
OTHER = {"subnet": SUB, "category": "custom_o", "action": "direct"}
DOMS = {"custom_d": ["api.seeip.org"], "custom_o": ["other.example"]}


def npass(entries):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    N._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=True, queue=True,
                        reset_mark=N.SNI_RESET_MARK, name_cats=set(DOMS))
    N._ensure_sni_router({c: DOMS[c] for c in {e["category"] for e in entries}}, [SUB], res, 3600, map_key=None, patterns={})
    return res


def gen(c):
    try:
        return json.load(open(N.SNI_SETS_PATH)).get(c)
    except OSError:
        return None


def hello(host):
    name = host.encode()
    sni = struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    ext = struct.pack(">HH", 0, len(sni)) + sni
    body = b"\x03\x03" + b"\x11" * 32 + b"\x00\x00\x02\x13\x01\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    tls = b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs
    tcp = struct.pack(">HHIIBBHHH", 40000, 443, 1, 1, 5 << 4, 0x18, 65535, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 40 + len(tls), 1, 0, 64, 6, 0, socket.inet_aton("10.188.1.9"), socket.inet_aton("23.128.64.156"))
    return ip + tcp + tls


print("\n[1] created")
npass([DIRECT]); npass([DIRECT])
g1 = gen("custom_d")
check("the set's generation is written", g1 is not None and "catl_custom_d" in K.m.tables[N.SMART_NFT_TABLE]["sets"], (g1, sorted(K.m.tables[N.SMART_NFT_TABLE]["sets"])))

S.subprocess.run = lambda args, input=None, **kw: subprocess.CompletedProcess(args, 0, "", "")
C = S.Classifier(N.SNI_MAP_PATH, N.SMART_NFT_TABLE, reset_mark=N.SNI_RESET_MARK, learn_ttl=3600)
m1 = C.on_packet(hello("api.seeip.org"))
m2 = C.on_packet(hello("api.seeip.org"))
check("(swg-sni learns it once: reset, then nothing)", m1 == N.SNI_RESET_MARK and m2 is None, (m1, m2))

print("\n[2] the rule goes, and comes back")
N.time.sleep(0.01)
npass([OTHER]); npass([OTHER])
check("the set is reaped with its rule", "catl_custom_d" not in K.m.tables[N.SMART_NFT_TABLE]["sets"], sorted(K.m.tables[N.SMART_NFT_TABLE]["sets"]))
npass([DIRECT])
g2 = gen("custom_d")
check("recreated → a new generation", g2 is not None and g2 != g1, (g1, g2))

print("\n[3] swg-sni writes it again")
C._last_reload = 0
m3 = C.on_packet(hello("api.seeip.org"))
with C._lock:
    pend = list(C._pending)
check("the address is a first learn again: queued for the new set …", ("custom_d", "23.128.64.156") in pend, pend)
check("…and the connection reset, so the retry routes by the rule", m3 == N.SNI_RESET_MARK, m3)

print("\n[4] quiet")
mt = lambda: os.stat(N.SNI_SETS_PATH).st_mtime_ns if os.path.exists(N.SNI_SETS_PATH) else None
before = mt()
npass([DIRECT])
check("an unchanged pass does not rewrite the file", before is not None and mt() == before, (before, mt()))

shutil.rmtree(TMP, ignore_errors=True)
print()
if PLANT:
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(FAILS) if FAILS else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if FAILS else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
