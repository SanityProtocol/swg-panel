#!/usr/bin/env python3
"""Self-test — a run-model change hands over the previous arm's RELAYS, not only its fork servers.

Relays were never in the run-model inventory, and the container arm often records nothing at all there (its fork
servers are its own children), so the handover returned before stopping anything. MEASURED in the 1.8.8 qualification
(nixos, podman -> native): two `swg-relay-<inst>` containers kept running under `--restart unless-stopped`, every native
`swg-relay@<inst>` unit failed on the held ports, and the divert stayed DISARMED — relayed links silently back on plain
forwarding. The handover now asks the previous arm's runtime for its relays by name and removes / disables them.

The real `handover_from_previous_runmodel` runs against recording stubs. No root, no runtime.

Run: python3 tests/relay_runmodel_handover_selftest.py      (0 = pass)
     --perturb   the relay lookup taken out (the shipped handover) → RED
"""
import importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

src = open(NODED, encoding="utf-8").read()
if PERTURB:
    a = "    r_units, r_ctrs = _relay_leftovers(prev.get(\"kind\"))\n"
    assert src.count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(a, "    r_units, r_ctrs = [], []\n")
tmp = tempfile.mkdtemp(prefix="relay-handover-")
path = os.path.join(tmp, "noded.py")
open(path, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgnoded_relay_handover", path)
spec = importlib.util.spec_from_loader("swgnoded_relay_handover", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err

def scenario(prev, kind, ctr_names="", host_units=""):
    inv = os.path.join(tmp, "inv-%d.json" % len(FAILS + [0]) )
    json.dump(prev, open(inv, "w"))
    calls, hs = [], []
    def run(cmd, input_text=None, timeout=20, **kw):
        calls.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "ps":
            return R(0, ctr_names)
        return R(0)
    def host_sh(cmd, timeout=90):
        hs.append(cmd)
        if "list-units" in cmd:
            return R(0, host_units)
        return R(0)
    N.run, N.host_sh = run, host_sh
    N.NODE_INVENTORY, N.NODE_KIND, N.NODE_RUNTIME = inv, kind, ("podman" if kind == "docker" else "")
    N._ctr_cli = lambda: "podman"
    N._ctr_running = lambda c, timeout=20: False
    N._handover_fork_dirs = lambda: None
    N._handover_turn = lambda: None
    N.handover_from_previous_runmodel()
    return calls, hs

CT = "swg-relay-awg0.ebc7097094ab\nswg-relay-wg9.ebc7097094ab\n"

print("[container arm -> native: its relay containers are removed]")
calls, hs = scenario({"kind": "docker", "runtime": "podman", "units": [], "containers": []}, "baremetal", CT)
rms = [c[-1] for c in calls if c[1:3] == ["rm", "-f"]]
check("both relay containers removed (rm -f), although the inventory recorded no containers",
      rms == ["swg-relay-awg0.ebc7097094ab", "swg-relay-wg9.ebc7097094ab"], calls)

print("\n[…and a turn container the inventory names is still only stopped]")
calls, hs = scenario({"kind": "docker", "runtime": "podman", "units": [], "containers": ["swg-turn-x"]}, "baremetal", CT)
check("the turn container: stop, not rm", ["podman", "stop", "-t", "10", "swg-turn-x"] in calls, calls)
check("the relays: rm -f", sum(1 for c in calls if c[1:3] == ["rm", "-f"]) == 2, calls)

print("\n[native -> container arm: the host's relay units are disabled]")
calls, hs = scenario({"kind": "baremetal", "runtime": "", "units": [], "containers": []}, "docker",
                     host_units="swg-relay@awg0.ebc7097094ab.service\nswg-relay@.service\nnot-a-relay.service\n")
stops = [h for h in hs if "list-units" not in h]
check("exactly the one instance unit is stopped", len(stops) == 1 and "swg-relay@awg0.ebc7097094ab.service" in stops[0], hs)

print("\n[same run-model: nothing is touched]")
calls, hs = scenario({"kind": "baremetal", "runtime": "", "units": ["swg-wdtt-a"], "containers": []}, "baremetal", CT)
check("no ps, no rm, no stop", calls == [] and hs == [], (calls, hs))

print(("\nFAIL (%d)" % len(FAILS)) if FAILS else ("\nALL PASS" + (" — but the perturbation was planted and should have gone RED" if PERTURB else "")))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
