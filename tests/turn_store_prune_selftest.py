#!/usr/bin/env python3
"""Self-test — the panel's turn-binary store is pruned without ever removing a version something needs.

TURN_BINS_DIR keeps each fork's mirrored server binaries: the copy nodes pull (censorship-robust), the rollback cache,
and for an upstream turn proxy the rollback MENU itself (turn_available_tags lists what is on disk). It was pruned to the
newest TURN_BINS_KEEP by mtime and nothing else: a version a node runs or an operator holds could be the one removed,
a failed fetch's empty dir took a slot, and a build of ours no longer advertised lingered with no picker to reach it.

  [1] _turn_bins_needed: what nodes run (wdtt / csqtt / turn_proxies by owner or by service, a silent node's snapshot
      too), what operators hold (wdtt: · fork:csqtt · fork:<turn>), our current builds; a version-less report → "*";
      no stats dir or an unreadable snapshot → None
  [2] an upstream fork: newest KEEP stay, and an older held / in-use one stays too; only an unneeded one past them goes
  [3] a fork of ours: a build no longer advertised goes — unless a node still runs it; advertised builds stay
  [4] a dir with no binary: an hour old → goes; fresh → stays; a download writing into it (even an old dir) → stays
  [5] a fork a node runs at an unreported version: only no-binary dirs go
  [6] not knowing what is needed (no stats dir) prunes NOTHING, not even a no-binary dir
  [7] _turn_bins_prune_all: every known fork's dir; a dir no known owner maps to is left alone
  [8] wiring: a fetch still prunes its fork; startup prunes once, in the background

Run: python3 tests/turn_store_prune_selftest.py        (0 = pass)
     --plant noinuse|noholds|noinfo|noretire|busy|unknown    the defect it names, planted → RED
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "noinuse":  ("        for w in snap.get(\"wdtt\") or []:\n", "        for w in ():\n"),
    "noholds":  ("    for k, v in (_turn_holds_load() or {}).items():\n        rest, tag", "    for k, v in {}.items():\n        rest, tag"),
    "noinfo":   ("    if need is False:\n        need = _turn_bins_needed()\n    if need is None:\n        return\n",
                 "    if need is False:\n        need = _turn_bins_needed()\n    if need is None:\n        need = {}\n"),
    "noretire": ("    if owner in _WDTT_OWNER_FORK:\n        advertised = {", "    if False:\n        advertised = {"),
    "busy":     ("            if any(\".dl.\" in f and now - os.path.getmtime(os.path.join(p, f)) < 3600 for f in files):\n                continue",
                 "            if False:\n                continue"),
    "unknown":  ("            if dn in by_dir:\n                _turn_bins_prune(by_dir[dn], need)",
                 "            _turn_bins_prune(by_dir.get(dn, dn.replace(\"_\", \"/\", 1)), need)"),
}
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
if PLANT:
    a, b = PLANTS[PLANT]
    assert src.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    src = src.replace(a, b)
TMP = tempfile.mkdtemp(prefix="turnprune-")
prog = os.path.join(TMP, "swg-panel-server"); open(prog, "w", encoding="utf-8").write(src)
ld = importlib.machinery.SourceFileLoader("turnprune_panel", prog)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
ld.exec_module(P)
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
LOG = []
P.log = lambda lvl, msg, *a: LOG.append(msg % a if a else msg)

STORE = os.path.join(TMP, "turn-bins"); SD = os.path.join(TMP, "stats"); os.makedirs(STORE); os.makedirs(SD)
P.TURN_BINS_DIR = STORE
P.TURN_HOLDS_PATH = os.path.join(TMP, "turn-holds.json")
P.Handler.deps = {"stats_dir": SD}
NOW = time.time()
WP = "Ivan4537/WDTT-Plus"                                   # a fork of OURS (WDTT_BUILDS["wdttplus"])
CS = P.CSQTT_MIRROR_OWNER                                   # ours too (CSQTT_BUILDS)
UP = "samosvalishe/free-turn-proxy"                         # an UPSTREAM fork
ADV = [v for v, _ in P._wdtt_versions("wdttplus")]          # its advertised builds, newest first (the module's own list)

def mk(owner, tag, age_h, binary=True, dl_age_s=None):
    p = os.path.join(STORE, P._turn_safe(owner), P._turn_safe(tag)); os.makedirs(p, exist_ok=True)
    if binary:
        open(os.path.join(p, "server-linux-amd64"), "wb").write(b"\x7fELF" + b"x" * 64)
    if dl_age_s is not None:
        f = os.path.join(p, "server-linux-amd64.dl.4242"); open(f, "wb").write(b"part")
        os.utime(f, (NOW - dl_age_s, NOW - dl_age_s))
    os.utime(p, (NOW - age_h * 3600, NOW - age_h * 3600))
def present(owner):
    d = os.path.join(STORE, P._turn_safe(owner))
    return sorted(os.listdir(d)) if os.path.isdir(d) else []
def snap(name, body):
    json.dump(body, open(os.path.join(SD, name), "w"))
def holds(d):
    json.dump(d, open(P.TURN_HOLDS_PATH, "w"))

print("[1] _turn_bins_needed")
snap("stats-aaa.json", {"wdtt": [{"fork": "wdttplus", "iface": "wdtt1", "version": "13"}],
                        "csqtt": [{"fork": "csqtt", "iface": "csqtt1", "version": "2.1.9-2"}],
                        "turn_proxies": [{"service": "vk-turn-proxy-samosvalishe-56007", "version": "v2"}]})
snap("stats-silent.json", {"turn_proxies": [{"owner": UP, "version": "v3"}]})   # a node gone quiet: its last word counts
holds({"aaa|fork:samosvalishe": {"tag": "v1", "at": 1}, "aaa|wdtt:wdttplus": {"tag": "15", "at": 1},
       "aaa|fork:csqtt": {"tag": "2.0.1", "at": 1}})
need = P._turn_bins_needed()
check("[1] in use (wdtt, csqtt, a turn proxy by service AND by owner, a silent node's too) + held + current",
      need and {"13", "15", ADV[0]} <= need.get(WP, set()) and {"2.1.9-2", "2.0.1", P._csqtt_current_version()} <= need.get(CS, set())
      and {"v1", "v2", "v3"} <= need.get(UP, set()), need)
snap("stats-bad.json", {"turn_proxies": [{"owner": "x/y", "version": ""}]})
check("[1] a fork reported without a version → \"*\" (nothing of it is judged)", "*" in (P._turn_bins_needed() or {}).get("x/y", set()))
open(os.path.join(SD, "stats-torn.json"), "w").write("{not json")
check("[1] an unreadable snapshot → None (it might name a version)", P._turn_bins_needed() is None)
os.remove(os.path.join(SD, "stats-torn.json")); os.remove(os.path.join(SD, "stats-bad.json"))
P.Handler.deps = {}
check("[1] no stats dir → None", P._turn_bins_needed() is None)
P.Handler.deps = {"stats_dir": SD}

print("[2] an upstream fork")
for i, t in enumerate(["v1", "v2", "v3", "old4", "v5", "v6", "v7", "v8", "v9"]):
    mk(UP, t, age_h=100 - i)                                 # v9 newest … v1 oldest
P._turn_bins_prune(UP)
check("[2] the newest %d stay; held v1 and in-use v2/v3 stay although older; only unneeded old4 goes" % P.TURN_BINS_KEEP,
      present(UP) == sorted(["v1", "v2", "v3", "v5", "v6", "v7", "v8", "v9"]), present(UP))

print("[3] a fork of ours")
for i, t in enumerate(reversed(ADV)):
    mk(WP, t, age_h=10 - i)
mk(WP, "14", age_h=30); mk(WP, "13", age_h=40)               # retired, and retired-but-in-use
P._turn_bins_prune(WP)
check("[3] a build no longer advertised goes (14); one a node still runs stays (13); advertised builds stay",
      present(WP) == sorted(ADV + ["13"]), (present(WP), ADV))
check("[3] each removal is said, with its reason", any("no longer offered" in l and "/14" in l for l in LOG), LOG[-3:])

print("[4] dirs with no binary")
mk(CS, "2.1.5", age_h=2, binary=False)                       # a failed fetch, an hour+ old
mk(CS, "9.9.9", age_h=0.05, binary=False)                    # just created — a fetch may be about to write
mk(CS, "8.8.8", age_h=5, binary=False, dl_age_s=30)          # an old dir a download is writing into right now
mk(CS, P._csqtt_current_version(), age_h=1)
P._turn_bins_prune(CS)
got = present(CS)
check("[4] an hour-old dir with no binary goes", "2.1.5" not in got, got)
check("[4] a fresh one stays", "9.9.9" in got, got)
check("[4] one a download is writing into stays, old as the dir is", "8.8.8" in got, got)

print("[5] a fork run at an unreported version")
XO = "WINGS-N/vk-turn-proxy"
snap("stats-ver.json", {"turn_proxies": [{"service": "vk-turn-proxy-WINGS-N-56004", "version": ""}]})
for i in range(8):
    mk(XO, "v%d" % i, age_h=50 - i)
mk(XO, "empty", age_h=3, binary=False)
P._turn_bins_prune(XO)
check("[5] only the no-binary dir goes; nothing past the newest %d is judged" % P.TURN_BINS_KEEP,
      present(XO) == sorted("v%d" % i for i in range(8)), present(XO))
os.remove(os.path.join(SD, "stats-ver.json"))

print("[6] not knowing what is needed")
mk(UP, "stale-empty", age_h=9, binary=False)
for i in range(10, 16):
    mk(UP, "w%d" % i, age_h=200 + i)
before = present(UP)
P.Handler.deps = {}
P._turn_bins_prune_all(); P._turn_bins_prune(UP)
check("[6] no stats dir → nothing at all is removed, not even a no-binary dir", present(UP) == before, (before, present(UP)))
P.Handler.deps = {"stats_dir": SD}

print("[7] _turn_bins_prune_all")
os.makedirs(os.path.join(STORE, "nobody_knows", "v0")); os.utime(os.path.join(STORE, "nobody_knows", "v0"), (NOW - 99999, NOW - 99999))
P._turn_bins_prune_all()
check("[7] every known fork is pruned (the upstream fork's stale no-binary dir is gone)", "stale-empty" not in present(UP), present(UP))
check("[7] a dir no known owner maps to is left alone", os.path.isdir(os.path.join(STORE, "nobody_knows", "v0")))

print("[8] wiring")
check("[8] a successful fetch still prunes its fork", "            _turn_bins_prune(owner)\n        return sha" in src)
check("[8] startup prunes once, in the background, after a delay",
      "threading.Thread(target=_turn_store_prune_soon, name=\"turn-store-prune\", daemon=True).start()" in src
      and "time.sleep(60)" in src[src.index("def _turn_store_prune_soon"):][:200])

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but plant %r was planted and should have gone RED" % PLANT if PLANT else ""))
sys.exit(2 if PLANT else 0)
