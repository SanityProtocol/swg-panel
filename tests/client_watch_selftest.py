#!/usr/bin/env python3
"""Self-test: the client-format watch (the Client rosters sheet's commit-drift check) watches the file that decides
whether our link imports, and a watch moved to a new file can fire.

ildarmaga's PWDTT client moved to its own repository (ildarmaga/pwdtt-client); ildarmaga/wdtt main stopped at ef69799,
so the watch on its pkg/sharelink could never fire again. A watch repointed to a new file kept the old paths' baseline,
and the new path — with nothing stored to differ from — read "up to date" forever.

  [1] pwdttilg watches ildarmaga/pwdtt-client main backend/subscription.go (parseWdttLink) and backend/subvalidate.go (the
      sub-URL check), not ildarmaga/wdtt
  [2] a client whose stored baseline names only its OLD paths: the next check seeds the new path, and a later commit on it
      reads "changed"; a path that already had a baseline is never re-seeded — its drift stays "changed" until acknowledged

Hermetic (GitHub reads are stubbed). Run: python3 tests/client_watch_selftest.py   (0 = pass)
     --perturb-seed   only a client with no baseline at all is seeded again → RED in [2]
"""
import atexit, importlib.machinery, importlib.util, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.abspath(os.path.join(HERE, "..", "swg-panel-server"))
PERTURB_SEED = "--perturb-seed" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="clientwatch-")
atexit.register(shutil.rmtree, TMP, True)
src = open(SERVER, encoding="utf-8").read()
if PERTURB_SEED:
    a = "        if seed and fresh:\n"
    if src.count(a) != 1:
        print("PERTURB FAILED — the anchor is not in the panel exactly once (%d)" % src.count(a)); sys.exit(1)
    src = src.replace(a, "        if seed and fresh and not prev:\n")
    print("(perturbed: only a client with no baseline is seeded — this run must FAIL)")
SRV = os.path.join(TMP, "swg-panel-server")
open(SRV, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel_clientwatch", SRV)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_clientwatch", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

print("[1] what pwdttilg watches")
srcs = P._client_sources("pwdttilg")
check("[1] ildarmaga/pwdtt-client main backend/subscription.go",
      {"owner": "ildarmaga", "repo": "pwdtt-client", "branch": "main", "path": "backend/subscription.go"} in srcs, srcs)
check("[1] …and backend/subvalidate.go, where a sub-URL is accepted or refused",
      {"owner": "ildarmaga", "repo": "pwdtt-client", "branch": "main", "path": "backend/subvalidate.go"} in srcs, srcs)
check("[1] …and nothing in ildarmaga/wdtt, whose main no longer moves", not any(s["repo"] == "wdtt" for s in srcs), srcs)

print("\n[2] a repointed watch")
P.TURN_ROSTER_PATH = os.path.join(TMP, "turn-roster.json")
P._gh_raw = lambda *a, **k: None
NEW, OLD = "backend/subscription.go", "pkg/sharelink/codec.go"
HEAD = {}                                            # (repo, path) -> sha the stub answers; anything else "fails"
P._gh_latest_commit = lambda owner, repo, branch, path: ({"sha": HEAD[(repo, path)], "date": "", "url": ""}
                                                         if (repo, path) in HEAD else None)
def write_roster(files):
    json.dump({"pwdttilg": {"files": files, "at": 1700000000}}, open(P.TURN_ROSTER_PATH, "w"))
def row():
    return P._turn_roster_check()["clients"]["pwdttilg"]

write_roster({OLD: {"commit": "a" * 40, "at": 1700000000}})   # what a panel acknowledged before the repoint
HEAD[("pwdtt-client", NEW)] = "1" * 40
r1 = row()
stored = json.load(open(P.TURN_ROSTER_PATH))["pwdttilg"]
check("[2] the first check after the repoint seeds the new path", (stored["files"].get(NEW) or {}).get("commit") == "1" * 40, stored)
check("[2] …reads up to date, and drops the old path's baseline", r1["status"] == "up_to_date" and OLD not in stored["files"], [r1["status"], stored])
HEAD[("pwdtt-client", NEW)] = "2" * 40
r2 = row()
check("[2] a later commit on the new path reads changed", r2["status"] == "changed", r2)
check("[2] …and is not re-seeded under the operator: the baseline is still the first commit",
      (json.load(open(P.TURN_ROSTER_PATH))["pwdttilg"]["files"].get(NEW) or {}).get("commit") == "1" * 40, json.load(open(P.TURN_ROSTER_PATH)))
r3 = row()
check("[2] …and it stays changed on the next check, until acknowledged", r3["status"] == "changed", r3)
P._turn_roster_ack("pwdttilg")
check("[2] control: acknowledged, it reads up to date", row()["status"] == "up_to_date")

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURB_SEED:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURB_SEED:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
