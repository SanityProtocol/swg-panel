#!/usr/bin/env python3
"""Self-test — AN INTERFACE STOPPED FROM THE PANEL STAYS STOPPED ON A DOCKER NODE, AND A STOPPED ONE IS NOT AN ERROR (N7).

The panel's Stop takes an interface down; swg-noded records it (iface-stopped.json in its state dir) and a bare node
also disables its unit, so a reboot keeps it down. A Docker node's entrypoint brought up EVERY conf at every container
start — a reboot, an update, a recreate — and swg-noded then saw it up and cleared the mark: the Stop was undone. And
while an interface stayed stopped, every sync logged "cannot read interface" for it, every 5 s (1.8.8 qualification,
round 10, N7).

  [1] docker/node-entrypoint.sh's bring-up, lifted and run against stubs (awg-quick, iptables): an interface named in
      iface-stopped.json is left down and said so — and nothing else is done for it, as on bare metal (no NAT rule of the
      entrypoint's own: swg-noded's egress baseline covers a client subnet); every other one comes up as before, NAT and
      all; a name is matched whole (awg is not awg1); no file, an unreadable one or one that is not a list → every
      interface comes up, as before
  [2] swg-noded reconcile, driven (the interface reads fail): a stopped interface is not "cannot read interface"; one
      that is not stopped still is
  [3] the mark survives: swg-noded's snapshot reports a down, stopped interface as stopped and keeps the mark (it clears
      it only for an interface it finds UP) — so after [1] the panel still reads it as stopped, and never auto-starts it

Run: python3 tests/docker_node_stop_kept_selftest.py        (0 = pass)
     --perturb   two plants, each on its own — each must turn its own check red
"""
import importlib.machinery, importlib.util, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {"ENTRY": os.environ.get("SWG_NS_ENTRY") or os.path.join(ROOT, "docker", "node-entrypoint.sh"),
         "NODED": os.environ.get("SWG_NS_NODED") or os.path.join(ROOT, "swg-noded")}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("entry", "ENTRY", '  case " $STOPPED_IFACES " in *" $IFACE "*)\n',
     '  case " $STOPPED_IFACES " in *" never-a-name "*)\n', "[1] a stopped interface is left down"),
    ("noded", "NODED", "            if iface not in stopped:\n                res[\"errors\"].append(f\"{iface}: cannot read interface\")\n",
     "            res[\"errors\"].append(f\"{iface}: cannot read interface\")\n", "[2] a stopped interface is not \"cannot read interface\""),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        if SRC[key].count(old) != 1:
            print("  %-6s STALE ANCHOR (%d) — this plant would plant nothing" % (name, SRC[key].count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(SRC[key].replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_NS_" + key: f.name}), capture_output=True, text=True, timeout=180)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-6s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

# ── [1] the entrypoint's bring-up ──────────────────────────────────────────────────────────────────────────────────
E = SRC["ENTRY"]
a = E.index('STOPPED_IFACES="$(python3 -c')
b = E.index("\ndone\n", E.index("for IFACE in $MANAGED; do", a)) + len("\ndone\n")
BRINGUP = E[a:b]
assert subprocess.run(["bash", "-n"], input=BRINGUP, capture_output=True, text=True).returncode == 0, "the bring-up loop was not lifted whole"

def bringup(stopped_text, managed="wg0 awg1"):
    t = tempfile.mkdtemp(prefix="ns-")
    st = os.path.join(t, "iface-stopped.json")
    if stopped_text is not None:
        open(st, "w").write(stopped_text)
    confs = os.path.join(t, "confs"); os.makedirs(confs)
    for i, n in enumerate(managed.split()):
        open(os.path.join(confs, n + ".conf"), "w").write("[Interface]\nAddress = 10.%d.0.1/24\nListenPort = 5182%d\n" % (i + 7, i))
    stub = os.path.join(t, "bin"); os.makedirs(stub)
    log = os.path.join(t, "calls")
    for tool in ("awg-quick", "wg-quick"):
        open(os.path.join(stub, tool), "w").write('#!/bin/bash\necho "%s $*" >> %s\nexit 0\n' % (tool, log))
    open(os.path.join(stub, "iptables"), "w").write('#!/bin/bash\necho "iptables $*" >> %s\ncase "$*" in *" -C "*) exit 1;; *" -D "*) exit 1;; esac\nexit 0\n' % log)
    open(os.path.join(stub, "ip"), "w").write('#!/bin/bash\necho "ip $*" >> %s\nexit 0\n' % log)
    for x in ("awg-quick", "wg-quick", "iptables", "ip"):
        os.chmod(os.path.join(stub, x), 0o755)
    script = ('set -eu\nlog(){ echo "LOG $*"; }\nWAN=eth0; MANAGED="%s"\n'
              'iface_conf(){ echo "%s/$1.conf"; }\niface_cmd(){ echo awg; }\n%s') % (managed, confs, BRINGUP.replace("/var/lib/swg-noded/iface-stopped.json", st))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=dict(os.environ, PATH=stub + ":" + os.environ["PATH"]))
    calls = open(log).read() if os.path.exists(log) else ""
    return r.returncode, r.stdout + r.stderr, calls, confs

print("[1] the Docker node's entrypoint")
rc, out, calls, confs = bringup('["awg1"]')
check("[1] a stopped interface is left down", rc == 0 and ("awg-quick up %s/awg1.conf" % confs) not in calls
      and "LOG leaving awg1 down — it was stopped from the panel, and stays down until it is started there" in out, (rc, out, calls))
check("[1] …every other one comes up as before", ("awg-quick up %s/wg0.conf" % confs) in calls and "LOG bringing up wg0 via awg-quick" in out, calls)
check("[1] …and nothing else is done for the stopped one — no NAT rule of the entrypoint's own (as on bare metal)",
      "swg-nat:awg1" not in calls and "10.8.0.0/24" not in calls, calls)
check("[1] …while a running one gets its NAT as before",
      "iptables -t nat -A POSTROUTING -s 10.7.0.0/24 -o eth0 -m comment --comment swg-nat:wg0 -j MASQUERADE" in calls, calls)
rc, out, calls, confs = bringup('["awg"]')
check("[1] a name is matched whole (a stopped \"awg\" is not awg1)", ("awg-quick up %s/awg1.conf" % confs) in calls, calls)
for label, text in (("no file", None), ("an unreadable one", "{not json"), ("one that is not a list", '{"awg1": true}')):
    rc, out, calls, confs = bringup(text)
    check("[1] %s → every interface comes up, as before" % label, rc == 0 and ("awg-quick up %s/awg1.conf" % confs) in calls
          and ("awg-quick up %s/wg0.conf" % confs) in calls and "leaving" not in out, (rc, out, calls))

# ── [2] swg-noded's reconcile ──────────────────────────────────────────────────────────────────────────────────────
print("\n[2] swg-noded reconcile")
os.environ["SWG_NODED_STATE"] = tempfile.mkdtemp(prefix="ns-state-")
spec = importlib.util.spec_from_loader("nd_stop", importlib.machinery.SourceFileLoader("nd_stop", PATHS["NODED"]))
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
m._iface_dump = lambda cfg, iface: None
m.current_pubkeys = lambda cfg, iface, dump=None: None
m._load_stopped_ifaces = lambda: {"awg1"}
cfg = {"interfaces": {"wg0": {"conf": "/nonexistent/wg0.conf", "cmd": ["awg"]}, "awg1": {"conf": "/nonexistent/awg1.conf", "cmd": ["awg"]}}}
res = m.reconcile(cfg, {"wg0": [], "awg1": []}, "/bin/false", False)
check("[2] a stopped interface is not \"cannot read interface\"", "awg1: cannot read interface" not in res["errors"], res["errors"])
check("[2] …one that is not stopped still is", "wg0: cannot read interface" in res["errors"], res["errors"])

# ── [3] the mark survives a snapshot of the down interface ─────────────────────────────────────────────────────────
print("\n[3] the mark survives")
N = SRC["NODED"]
snap = N[N.index("def build_snapshot("):N.index("\ndef ", N.index("def build_snapshot(") + 10)]
i_down = snap.find('if iface in stopped_set:            # the operator stopped it — a choice, not a failure (no error)')
i_clear = snap.find("if iface in stopped_set:               # it's up again (e.g. brought up outside the panel) → clear the stopped mark")
check("[3] a DOWN interface in the stopped set is reported stopped (the mark kept); only one found UP clears it",
      0 < i_down < i_clear and '"stopped": True' in snap[i_down:i_down + 300]
      and "_set_iface_stopped(iface, False)" in snap[i_clear:i_clear + 250] and "_set_iface_stopped" not in snap[i_down:i_clear], (i_down, i_clear))
P = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("[3] …and the panel never auto-starts a stopped interface", 'if not _e.get("down") or _e.get("stopped"):' in P)   # mesh links no longer skipped there (q189 MESH-1)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
