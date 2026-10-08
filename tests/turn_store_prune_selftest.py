#!/usr/bin/env python3
"""Self-test — the panel's turn-binary store is pruned without ever removing a version something needs.

TURN_BINS_DIR keeps each fork's mirrored server binaries: the copy nodes pull (censorship-robust), the rollback cache,
and for an upstream turn proxy the rollback MENU itself (turn_available_tags lists what is on disk). It was pruned to the
newest TURN_BINS_KEEP by mtime and nothing else: a version a node runs or an operator holds could be the one removed,
a failed fetch's empty dir took a slot, and a build of ours no longer advertised lingered with no picker to reach it.

  [1] _turn_bins_needed: what nodes run (wdtt / csqtt / turn_proxies by owner or by service, a silent node's snapshot
      too), what operators hold (wdtt: · fork:csqtt · fork:<turn>, a bare-string value too), our current builds; a
      version-less report → "*"; a field of the wrong type is skipped; no stats dir, an unreadable or non-object
      snapshot → None (no exception, said once)
  [2] an upstream fork: newest KEEP stay, and an older held / in-use one stays too; only an unneeded one past them goes
  [3] a fork of ours: a build no longer advertised goes — unless a node runs it, it is the pseudo-tag a node with no
      version asks under (`wdtt` / `csqtt`), or it was fetched within the hour (it is being served)
  [4] a dir with no binary: an hour old → goes, a needed tag's too; fresh → stays; a download writing into it (even an
      old dir) → stays; a download's temp file an hour old goes from any dir (the dir and its binary stay)
  [5] the ranking: only dirs holding a binary, by when the BINARY landed — a failed fetch's young empty dir takes no
      slot, and a dir touched later (a temp file removed) does not jump ahead
  [6] a fork run at an unreported version: only no-binary dirs go
  [7] a version swg-noded cut to 40 characters still protects the longer tag it begins
  [8] not knowing what is needed prunes NOTHING; a temp file vanishing mid-prune does not stop the rest
  [9] _turn_bins_prune_all: every known fork's dir; a dir no known owner maps to is left alone; one fork failing is
      said and the rest still pruned
  [10] turn_sum: a pruned binary with a remembered hash is answered by hash for a pin (no fetch) and fetched again for a
       serve; bytes that changed since the pin are kept and the cache follows the file (said); the tag dir is made
       fresh before curl; the prune runs on a thread of its own, one at a time per owner, a failure said
  [11] wiring: the binary endpoint asks for the file; startup prunes once, in the background

Run: python3 tests/turn_store_prune_selftest.py        (0 = pass)
     --plant NAME    the defect it names, planted → RED  (names: see PLANTS)
"""
import hashlib, importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "noinuse":   ("        for w in rows(snap, \"wdtt\"):\n", "        for w in ():\n"),
    "noholds":   ("    for k, v in (_turn_holds_load() or {}).items():\n        rest = str(k)", "    for k, v in {}.items():\n        rest = str(k)"),
    "noinfo":    ("    if need is None:\n        need = _turn_bins_needed()\n    if need is None:\n        return\n",
                  "    if need is None:\n        need = _turn_bins_needed()\n    if need is None:\n        need = {}\n"),
    "noretire":  ("    if owner in _WDTT_OWNER_FORK:\n        advertised = {", "    if False:\n        advertised = {"),
    "busy":      ("        if any(\".dl.\" in f for f in _turn_files(p)):\n            continue                          # a download",
                  "        if False:\n            continue                          # a download"),
    "unknown":   ("        if dn in by_dir:\n            try:\n                _turn_bins_prune(by_dir[dn], need)",
                  "        if True:\n            try:\n                _turn_bins_prune(by_dir.get(dn, dn.replace(\"_\", \"/\", 1)), need)"),
    "staledl":   ("            if \".dl.\" in f and (_turn_age(os.path.join(p, f)) or 0) > 3600:", "            if False:"),
    "silent":    ("                log(LOG_WARNING, \"turn store: not pruned — %s cannot be read (%s)\", os.path.join(sd, n), e)\n", "                pass\n"),
    "shape":     ("            if not isinstance(snap, dict):\n                raise ValueError(\"not a JSON object\")\n", ""),
    "fieldtype": ("            add(text(t.get(\"owner\")) or", "            add(t.get(\"owner\") or"),
    "pseudo":    ("        keep.add(\"wdtt\")\n", ""),
    "young":     ("            if age > 3600:\n                shutil.rmtree(p, ignore_errors=True)\n                landed.pop(p, None)",
                  "            if True:\n                shutil.rmtree(p, ignore_errors=True)\n                landed.pop(p, None)"),
    "emptyneed": ("        if at is None:\n            if age > 3600:", "        if at is None and t not in keep:\n            if age > 3600:"),
    "rankall":   ("        if at is not None:\n            landed[p] = at\n", "        landed[p] = at if at is not None else time.time() - age\n"),
    "dirtime":   ("        if at is not None:\n            landed[p] = at\n", "        if at is not None:\n            landed[p] = time.time() - age\n"),
    "cut":       ("    cut = [k for k in keep if len(k) == _TURN_VER_CUT]", "    cut = []"),
    "refill":    ("        cached = _TURN_SUMS.get(key)\n    if cached and not need_file:\n        return cached\n",
                  "        cached = _TURN_SUMS.get(key)\n    if cached:\n        return cached\n"),
    "follow":    ("        if sha and sha != cached:", "        if sha and not cached:"),
    "touch":     ("                os.utime(os.path.dirname(dest), None)", "                pass"),
    "sync":      ("        _turn_bins_prune_soon(owner)      # in the background", "        _turn_bins_prune(owner)      # in the background"),
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
P.TURN_SUMS_PATH = os.path.join(TMP, "turn-sums.json")
P.Handler.deps = {"stats_dir": SD}
NOW = time.time()
WP = "Ivan4537/WDTT-Plus"                                   # a fork of OURS (WDTT_BUILDS["wdttplus"])
CS = P.CSQTT_MIRROR_OWNER                                   # ours too (CSQTT_BUILDS)
UP = "hackdiaz-dev/free-turn-proxy"                         # an UPSTREAM fork
ADV = [v for v, _ in P._wdtt_versions("wdttplus")]          # its advertised builds, newest first (the module's own list)

def ago(path, hours):
    os.utime(path, (NOW - hours * 3600, NOW - hours * 3600))
def mk(owner, tag, age_h, binary=True, dl_age_s=None, dir_age_h=None):
    """A tag dir whose binary landed `age_h` ago (the dir last touched then too, or `dir_age_h` ago)."""
    p = os.path.join(STORE, P._turn_safe(owner), P._turn_safe(tag)); os.makedirs(p, exist_ok=True)
    if binary:
        b = os.path.join(p, "server-linux-amd64")
        open(b, "wb").write(b"\x7fELF" + b"x" * 64); ago(b, age_h)
    if dl_age_s is not None:
        f = os.path.join(p, "server-linux-amd64.dl.4242"); open(f, "wb").write(b"part")
        os.utime(f, (NOW - dl_age_s, NOW - dl_age_s))
    ago(p, age_h if dir_age_h is None else dir_age_h)
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
       "aaa|fork:csqtt": "2.0.1"})                           # a bare-string value: read as the tag, never a crash
need = P._turn_bins_needed()
check("[1] in use (wdtt, csqtt, a turn proxy by service AND by owner, a silent node's too) + held + current",
      need and {"13", "15", ADV[0]} <= need.get(WP, set()) and {"2.1.9-2", "2.0.1", P._csqtt_current_version()} <= need.get(CS, set())
      and {"v1", "v2", "v3"} <= need.get(UP, set()), need)
snap("stats-bad.json", {"turn_proxies": [{"owner": "x/y", "version": ""}, {"owner": {"no": 1}, "service": 5, "version": "v9"}],
                        "wdtt": [{"fork": ["a"], "version": "1"}], "csqtt": [7, None]})
try:
    r, err = P._turn_bins_needed(), None
except Exception as e:
    r, err = None, e
check("[1] a fork reported without a version → \"*\"; fields of the wrong type are skipped, not fatal",
      err is None and "*" in (r or {}).get("x/y", set()), err or r)
os.remove(os.path.join(SD, "stats-bad.json"))
for body, label in (("{not json", "torn"), ("null", "null"), ("[1, 2]", "a list")):
    open(os.path.join(SD, "stats-odd.json"), "w").write(body)
    P._TURN_PRUNE_WARNED.clear(); LOG.clear()
    try:
        r, err = P._turn_bins_needed(), None
    except Exception as e:
        r, err = "raised", e
    check("[1] a snapshot that is %s → None, no exception, said once" % label,
          r is None and err is None and len([l for l in LOG if "not pruned" in l]) == 1, (r, err, LOG))
os.remove(os.path.join(SD, "stats-odd.json"))
P._TURN_PRUNE_WARNED.clear(); LOG.clear()
P._turn_bins_needed()
check("[1] …and said once per file, not every time", not [l for l in LOG if "not pruned" in l])
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
mk(WP, "14", age_h=30); mk(WP, "13", age_h=40); mk(WP, "wdtt", age_h=50); mk(WP, "12", age_h=0.2)
P._turn_bins_prune(WP)
got = present(WP)
check("[3] a build no longer advertised goes (14); one a node still runs stays (13)", "14" not in got and "13" in got, got)
check("[3] the pseudo-tag `wdtt` (a node with no version asks under it) stays", "wdtt" in got, got)
check("[3] one no longer advertised but fetched within the hour stays — it is being served (12)", "12" in got, got)
check("[3] advertised builds stay", set(ADV) <= set(got), (got, ADV))
check("[3] each removal is said, with its reason", any("no longer offered" in l and "/14" in l for l in LOG), LOG[-3:])
mk(CS, "csqtt", age_h=70)
P._turn_bins_prune(CS)
check("[3] csqtt's pseudo-tag `csqtt` stays too", "csqtt" in present(CS), present(CS))

print("[4] dirs with no binary")
mk(CS, "2.1.5", age_h=2, binary=False)                       # a failed fetch, an hour+ old
mk(CS, "9.9.9", age_h=0.05, binary=False)                    # just created — a fetch may be about to write
mk(CS, "8.8.8", age_h=5, binary=False, dl_age_s=30)          # an old dir a download is writing into right now
mk(CS, "2.1.9-2", age_h=3, binary=False)                     # a NEEDED tag (a node runs it) whose fetch failed
cur = P._csqtt_current_version(); mk(CS, cur, age_h=1)
P._turn_bins_prune(CS)
got = present(CS)
check("[4] an hour-old dir with no binary goes", "2.1.5" not in got, got)
check("[4] …a needed tag's too: there is nothing in it to keep (a fetch makes it again)", "2.1.9-2" not in got, got)
check("[4] a fresh one stays", "9.9.9" in got, got)
check("[4] one a download is writing into stays, old as the dir is", "8.8.8" in got, got)
stale = os.path.join(STORE, P._turn_safe(CS), cur, "server-linux-amd64.dl.777")
open(stale, "wb").write(b"half a binary"); os.utime(stale, (NOW - 7200, NOW - 7200))
P._turn_bins_prune(CS)
check("[4] a download's temp file an hour old goes — even from the current (needed) build's dir",
      not os.path.exists(stale), os.listdir(os.path.dirname(stale)))
check("[4] …and that dir and its binary stay", os.path.isfile(os.path.join(STORE, P._turn_safe(CS), cur, "server-linux-amd64")))

print("[5] the ranking")
U2 = "WINGS-N/vk-turn-proxy"
for i in range(5):
    mk(U2, "r%d" % i, age_h=48 - i)                          # five real binaries, two days old
for i in range(3):
    mk(U2, "bad%d" % i, age_h=0.1, binary=False)             # three fetches that failed minutes ago
mk(U2, "r-new", age_h=0.2)                                   # and one success: six real, five slots
P._turn_bins_prune(U2)
got = present(U2)
check("[5] young empty dirs take no slot: the newest %d real binaries stay, only the oldest real one goes" % P.TURN_BINS_KEEP,
      [t for t in got if t.startswith("r")] == sorted(["r1", "r2", "r3", "r4", "r-new"]), got)
U3 = "kiper292/vk-turn-proxy"
for i in range(6):
    mk(U3, "s%d" % i, age_h=60 - i)                          # s0 oldest … s5 newest
mk(U3, "s0", age_h=60, dl_age_s=7200)                        # the oldest also holds a dead fetch's temp file: removing it
P._turn_bins_prune(U3)                                       # touches s0's dir — its BINARY is still the oldest
check("[5] ranked by when the binary landed: a dir touched later (a temp file removed) does not jump ahead",
      present(U3) == ["s1", "s2", "s3", "s4", "s5"], present(U3))

print("[6] a fork run at an unreported version")
XO = "XXcipherX-like/vk-turn-proxy"
snap("stats-ver.json", {"turn_proxies": [{"owner": XO, "version": ""}]})
for i in range(8):
    mk(XO, "v%d" % i, age_h=50 - i)
mk(XO, "empty", age_h=3, binary=False)
P._turn_bins_prune(XO)
check("[6] only the no-binary dir goes; nothing past the newest %d is judged" % P.TURN_BINS_KEEP,
      present(XO) == sorted("v%d" % i for i in range(8)), present(XO))
os.remove(os.path.join(SD, "stats-ver.json"))

print("[7] a version cut to 40 characters")
LONG = "release-2026.10.06-" + "x" * 31                       # 50 characters; swg-noded reports the first 40
assert len(LONG) == 50
snap("stats-long.json", {"turn_proxies": [{"owner": U2, "version": LONG[:40]}]})
mk(U2, LONG, age_h=500)                                      # far past the newest KEEP
P._turn_bins_prune(U2)
check("[7] the tag it begins is protected", LONG in present(U2), present(U2))
os.remove(os.path.join(SD, "stats-long.json"))

print("[8] not knowing, and a temp file vanishing")
mk(UP, "stale-empty", age_h=9, binary=False)
for i in range(10, 16):
    mk(UP, "w%d" % i, age_h=200 + i)
before = present(UP)
P.Handler.deps = {}
P._turn_bins_prune_all(); P._turn_bins_prune(UP)
check("[8] no stats dir → nothing at all is removed, not even a no-binary dir", present(UP) == before, (before, present(UP)))
P.Handler.deps = {"stats_dir": SD}
mk(WP, "11", age_h=80)                                       # retired, should go
ghost = os.path.join(STORE, P._turn_safe(WP), ADV[0], "server-linux-amd64.dl.555"); open(ghost, "wb").write(b"x")
real_age = P._turn_age
def vanishing(path):
    if path == ghost:
        os.remove(ghost)
        return None                                          # it finished between the listdir and the stat
    return real_age(path)
P._turn_age = vanishing
P._turn_bins_prune(WP)
P._turn_age = real_age
check("[8] a temp file vanishing mid-prune does not stop the rest (the retired build still went)",
      "11" not in present(WP), present(WP))

print("[9] _turn_bins_prune_all")
os.makedirs(os.path.join(STORE, "nobody_knows", "v0")); ago(os.path.join(STORE, "nobody_knows", "v0"), 30)
real_prune = P._turn_bins_prune
def flaky(owner, need=None):
    if owner == CS:
        raise RuntimeError("boom")
    return real_prune(owner, need)
P._turn_bins_prune = flaky; LOG.clear()
P._turn_bins_prune_all()
P._turn_bins_prune = real_prune
check("[9] every known fork is pruned (the upstream fork's stale no-binary dir is gone)", "stale-empty" not in present(UP), present(UP))
check("[9] a dir no known owner maps to is left alone", os.path.isdir(os.path.join(STORE, "nobody_knows", "v0")))
check("[9] one fork failing is said, and the others are still pruned", any("stopped" in l and CS in l for l in LOG), LOG)

print("[10] turn_sum")
BODY = b"\x7fELF" + b"served" * 100
SHA = hashlib.sha256(BODY).hexdigest()
CURL = {"n": 0, "body": BODY, "dir_age": None}
def fake_run(args, **kw):
    if args and args[0] == "curl":
        CURL["n"] += 1
        out = args[args.index("-o") + 1]
        CURL["dir_age"] = time.time() - os.path.getmtime(os.path.dirname(out))
        open(out, "wb").write(CURL["body"])
        return subprocess.CompletedProcess(args, 0, "", "")
    return subprocess.CompletedProcess(args, 1, "", "")
P.subprocess.run = fake_run
OWN, TAG = "someone/vk-turn-proxy", "v7"
KEY = OWN + "|" + TAG + "|amd64"
dest = P._turn_store_path(OWN, TAG, "amd64")
os.makedirs(os.path.dirname(dest), exist_ok=True)
ago(os.path.dirname(dest), 2)                               # an old empty dir: a fetch that failed two hours ago
P._TURN_SUMS[KEY] = SHA                                     # pruned earlier: the hash is remembered, the file is gone
PRUNED_ON = []
P._turn_bins_prune = lambda owner, need=None: PRUNED_ON.append((threading.current_thread().name, owner))
check("[10] for a pin, a remembered hash is the answer — no fetch", P.turn_sum(OWN, TAG, "amd64") == SHA and CURL["n"] == 0, CURL)
r = P.turn_sum(OWN, TAG, "amd64", need_file=True)
check("[10] for a serve, the pruned binary is fetched again and kept", r == SHA and CURL["n"] == 1 and os.path.isfile(dest), (r, CURL))
check("[10] the tag dir was made fresh before curl ran (no prune can take it as an hour-old empty dir)",
      CURL["dir_age"] is not None and CURL["dir_age"] < 60, CURL["dir_age"])
time.sleep(0.3)
check("[10] the prune ran on a thread of its own", PRUNED_ON and PRUNED_ON[-1] == ("turn-store-prune", OWN), PRUNED_ON)
os.remove(dest); CURL["body"] = b"\x7fELF" + b"rebuilt" * 50; LOG.clear()
NEW = hashlib.sha256(CURL["body"]).hexdigest()
r = P.turn_sum(OWN, TAG, "amd64", need_file=True)
check("[10] bytes that changed since the pin: kept and served — the cache follows the file, as for a mirrored one",
      r == NEW and os.path.isfile(dest) and P._TURN_SUMS.get(KEY) == NEW
      and json.load(open(P.TURN_SUMS_PATH)).get(KEY) == NEW, (r, P._TURN_SUMS.get(KEY)))
check("[10] …and said", any("not the one it was pinned with" in l for l in LOG), LOG)
GATE = threading.Event(); RUNS = []
P._turn_bins_prune = lambda owner, need=None: (RUNS.append(owner), GATE.wait(5))
P._turn_bins_prune_soon(OWN); P._turn_bins_prune_soon(OWN); time.sleep(0.2)
check("[10] one prune at a time per owner (a second request while one runs is dropped)", RUNS == [OWN], RUNS)
GATE.set(); time.sleep(0.2)
def boom(owner, need=None):
    raise RuntimeError("disk on fire")
P._turn_bins_prune = boom; LOG.clear()
P._turn_bins_prune_soon(OWN); time.sleep(0.2)
check("[10] a prune that fails is said (and the next one is not blocked)",
      any("stopped" in l and "disk on fire" in l for l in LOG) and OWN not in P._TURN_PRUNING, (LOG, P._TURN_PRUNING))
P._turn_bins_prune = real_prune

print("[11] wiring")
ep = src[src.index("    def _node_turn_binary(self, u):"):][:2500]
check("[11] the binary endpoint asks turn_sum for the FILE", "turn_sum(owner, tag, arch, need_file=True)" in ep)
check("[11] startup prunes once, in the background, after a delay",
      "threading.Thread(target=_turn_store_prune_soon, name=\"turn-store-prune\", daemon=True).start()" in src
      and "time.sleep(60)" in src[src.index("def _turn_store_prune_soon"):][:200])

shutil.rmtree(TMP, ignore_errors=True)
print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS" + (" — but plant %r was planted and should have gone RED" % PLANT if PLANT else ""))
sys.exit(2 if PLANT else 0)
