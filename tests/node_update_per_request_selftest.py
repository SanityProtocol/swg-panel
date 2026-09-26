#!/usr/bin/env python3
"""Self-test — a node acts on every Update REQUEST once, not on one request per process.

`swg-noded` used a process-lifetime latch (`update_started`): after one update request it ignored every later one until
it restarted. An update that changes nothing does not restart it — nothing new, or (since 236400f) a Docker node whose
images are already current — so the operator's next press of Update was silently dropped, and five minutes on the panel
called it "never reported a new version (e.g. it couldn't reach GitHub)". Measured on the 1.8.8 VM re-run (D3, q2 and q4).
The latch is now the `at` of the request acted on.

The block is lifted from swg-noded as shipped (from `_upd0 = reply.get("update")` to the interface creation that follows)
and run in a fake sync loop: the recording stubs stand in for the updater, the host trigger and the panel report.

Run: python3 tests/node_update_per_request_selftest.py      (0 = pass)
     --perturb   the per-process latch back (fire only while nothing has fired) → RED
"""
import os, re, sys, tempfile, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
NODED = os.environ.get("SWG_NODED") or os.path.join(HERE, "..", "swg-noded")
PERTURB = "--perturb" in sys.argv
src = open(NODED, encoding="utf-8").read()
i = src.index('                _upd0 = reply.get("update")\n')
j = src.index("                cr = create_ifaces(", i)
blk = textwrap.dedent(src[i:j])
if PERTURB:
    n = blk.count("_at != update_fired")
    assert n == 2, "perturbation anchor missing — would FALSE-PASS"
    blk = blk.replace("_at != update_fired", "not update_fired")
code = compile(blk, "noded-update-block", "exec")

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

class Box:
    """One node process: `update_fired` lives as long as it does; the marker file survives it (Docker: data/node)."""
    def __init__(self, state_dir, trig=None, kind="baremetal", start_ok=True):
        self.ns = {"update_fired": "", "os": os, "time": __import__("time"), "STATE_DIR": state_dir,
                   "NODE_DECLARATIVE": False, "NODE_KIND": kind, "node_cfg": {}, "panel": {}, "print": lambda *a, **k: None}
        self.runs, self.reports, self.trig, self.start_ok = [], [], trig, start_ok
        self.ns["run_self_update"] = lambda cfg, want: (self.runs.append(want.get("at", "no-at")), self.start_ok)[1]
        self.ns["report_proc"] = lambda *a: self.reports.append(a)
    def sync(self, update):
        if self.trig:
            os.environ["SWG_UPDATE_TRIGGER"] = self.trig
        else:
            os.environ.pop("SWG_UPDATE_TRIGGER", None)
        self.ns["reply"] = {"update": update} if update else {}
        exec(code, self.ns)

d = tempfile.mkdtemp(prefix="upd-")
print("[bare metal]")
b = Box(d)
b.sync({"to": "1.8.8", "at": 100}); b.sync({"to": "1.8.8", "at": 100}); b.sync({"to": "1.8.8", "at": 100})
check("one request, three syncs → the updater runs once", b.runs == [100], b.runs)
b.sync(None)
b.sync({"to": "1.8.8", "at": 200})
check("the updater changed nothing and did not restart us; the operator presses Update again → it runs again",
      b.runs == [100, 200], b.runs)
c = Box(d, start_ok=False)
c.sync({"to": "1.8.8", "at": 300}); c.sync({"to": "1.8.8", "at": 300})
check("a failed START is retried on the next sync", c.runs == [300, 300], c.runs)

print("\n[docker: the host trigger]")
td = tempfile.mkdtemp(prefix="updd-"); trig = os.path.join(td, "trigger")
k = Box(td, trig=trig, kind="docker")
k.sync({"to": "1.8.8", "at": 400})
check("the trigger is written and the request remembered on disk", os.path.exists(trig) and open(os.path.join(td, ".update-done")).read().strip() == "400")
os.unlink(trig)
k2 = Box(td, trig=trig, kind="docker")                 # the recreate restarted the daemon: a NEW process, same pending request
k2.sync({"to": "1.8.8", "at": 400})
check("…a recreate-restarted daemon does not fire the SAME request again (no recreate loop)", not os.path.exists(trig))
k2.sync({"to": "1.8.8", "at": 500})
check("…but a NEW request after a no-change run fires (the D3 case on Docker)", os.path.exists(trig))

print("\n[an older panel that sends no `at`]")
o = Box(tempfile.mkdtemp(prefix="updo-"))
o.sync({"to": "1.8.8"}); o.sync({"to": "1.8.8"})
check("fires once per process, as before", o.runs == ["no-at"], o.runs)

print(("\nFAIL (%d)" % len(FAILS)) if FAILS else ("\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else "")))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
