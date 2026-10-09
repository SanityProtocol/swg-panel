#!/usr/bin/env python3
"""Self-test — THE NIXOS FLEET CHECK READS swg-noded's LOGS WHERE THEY ARE (q189 DN-4).

Since 1.8.9 the native node unit logs into its own journal namespace (nix/modules/node.nix `LogNamespace = "swg-node"`,
docs/LOGS-PLAN.md §2). A plain `journalctl -u swg-noded.service` reads only the main journal, where nothing but PID 1's
start/stop lines are left, so every read nix/checks/fleet.nix made of the daemon's log came back empty: the failure prints
said nothing, the host_sh aliveness wait could only time out (90 s), and the subtest after it — the critical invariant, a
panel outage must never wipe a node's peers — never ran. `--namespace=+swg-node` reads the namespace merged with the main
journal (the `+`), so the start/stop lines stay in the same read.

⚠️ THIS IS AN ANCHOR GATE, and it says so. The NixOS VM test itself is not run here (it needs KVM and a nix build); what
this file defends is the wiring a green VM run cannot show is missing — the five reads carry the namespace the unit
actually logs into, and the gate reads that name from the module, so renaming it there turns this red.

  [1] the native unit sets a LogNamespace (its name is taken from node.nix, not copied here)
  [2] every journalctl read of swg-noded.service in nix/checks/*.nix passes --namespace=+<that name>
  [3] the five reads are all still there, each named by what it is for
  [4] the panel's unit has no namespace, so its one read stays a plain -u (the sixth journalctl, left as it is)
  [5] (1.8.9 qualification DN-15) the self-update services — swg-update (panel.nix), swg-node-update (node.nix), which the
      container arm's timer starts every 30 s — keep systemd's own start/stop lines out of the journal (LogLevelMax
      notice, at every level, Off included: ~8,600 lines a day each) and their own lines in (SyslogLevel notice)

Run: python3 tests/nix_fleet_journal_selftest.py      (0 = pass)
     --perturb      takes the namespace off the outage-window read (the one the invariant subtest counts) → RED
     --perturb-ns   renames the unit's namespace in node.nix (in memory) → RED (the reads no longer follow it)
     --perturb-quiet  the two update services without their notice caps (e66018f, in memory) → RED on [5] only
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_NS = "--perturb-ns" in sys.argv
PERTURB_QUIET = "--perturb-quiet" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

NODE = open(os.path.join(ROOT, "nix", "modules", "node.nix"), encoding="utf-8").read()
PANEL = open(os.path.join(ROOT, "nix", "modules", "panel.nix"), encoding="utf-8").read()
CHECKS = {os.path.relpath(p, ROOT): open(p, encoding="utf-8").read()
          for p in sorted(glob.glob(os.path.join(ROOT, "nix", "checks", "*.nix")))}
FLEET = "nix/checks/fleet.nix"

if PERTURB:
    a = "journalctl --namespace=+swg-node -u swg-noded.service --since '-45s'"
    assert CHECKS[FLEET].count(a) == 1, "anchor missing — this run would FALSE-PASS"
    CHECKS[FLEET] = CHECKS[FLEET].replace(a, "journalctl -u swg-noded.service --since '-45s'")
if PERTURB_NS:
    a = 'LogNamespace = "swg-node";'
    assert NODE.count(a) == 1, "anchor missing — this run would FALSE-PASS"
    NODE = NODE.replace(a, 'LogNamespace = "swg-node2";')

if PERTURB_QUIET:
    a = '          LogLevelMax = "notice";\n          SyslogLevel = "notice";\n'
    assert NODE.count(a) == 1 and PANEL.count(a) == 1, "anchor missing — this run would FALSE-PASS"
    NODE, PANEL = NODE.replace(a, ""), PANEL.replace(a, "")

# a Nix comment line is not a command: only code lines are read below
code = lambda src: "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))

print("[1] the native node unit logs into a journal namespace")
ns = re.findall(r'^\s*LogNamespace = "([^"]+)";', code(NODE), re.M)
check("node.nix sets exactly one LogNamespace", len(ns) == 1, ns)
NS = ns[0] if ns else "\0"

print("\n[2] every read of swg-noded's journal in the NixOS checks passes --namespace=+%s" % NS)
reads = [(f, l.strip()) for f, src in CHECKS.items() for l in code(src).splitlines()
         if "journalctl" in l and "swg-noded.service" in l]
bad = [r for r in reads if ("--namespace=+%s " % NS) not in r[1]]
check("none reads the main journal alone (a plain -u sees only PID 1's start/stop lines)", reads and not bad, bad or "no reads at all")

print("\n[3] the five reads are all there")
FIVE = {
    "the daemon's log printed after start": "| tail -40",
    "the log printed when enrolment fails": "| tail -60",
    "the host_sh aliveness wait": "grep -qE 'wdtt|host_sh'",
    "the host_sh journal read (no rc=127)": 'journal = node1.succeed("journalctl',
    "the failure count while the panel is down (the critical-invariant subtest)": "--since '-45s'",
}
fleet = code(CHECKS.get(FLEET, ""))
for what, mark in FIVE.items():
    hit = [l.strip() for l in fleet.splitlines() if mark in l and "journalctl" in l]
    check("%s reads the namespace" % what, len(hit) == 1 and ("--namespace=+%s -u swg-noded.service" % NS) in hit[0], hit)
check("…and no other read of it was added unnoticed", len([r for r in reads if r[0] == FLEET]) == len(FIVE),
      [r[1][:80] for r in reads if r[0] == FLEET])

print("\n[4] the panel's unit has no namespace, so its read stays a plain -u")
check("panel.nix sets no LogNamespace", not re.search(r"^\s*LogNamespace\s*=", code(PANEL), re.M))
check("the panel's one read is the main journal's", "journalctl -u swg-panel-server.service" in fleet)

print("\n[5] the self-update services keep systemd's per-tick lines out (DN-15)")
for f, src, unit in (("panel.nix", PANEL, "swg-update"), ("node.nix", NODE, "swg-node-update")):
    m = re.search(r"systemd\.services\.%s = mkIf [^\n]*\{\n(.*?)\n      \};\n" % re.escape(unit), code(src), re.S)
    body = m.group(1) if m else ""
    sc = re.search(r"serviceConfig = \{(.*?)\}", body, re.S)
    sc = sc.group(1) if sc else ""
    check("%s: systemd.services.%s — LogLevelMax and SyslogLevel notice, in its serviceConfig" % (f, unit),
          'LogLevelMax = "notice";' in sc and 'SyslogLevel = "notice";' in sc, sc.strip()[:200] or "unit or serviceConfig not found")

print()
if PERTURB_QUIET:
    _red = [x for x in FAILS if "LogLevelMax and SyslogLevel" in x]
    print("perturb-quiet: %s" % ("RED as it must be (%d), all [5]" % len(_red) if _red and len(_red) == len(FAILS) else "WRONG: %s" % FAILS))
    sys.exit(0 if _red and len(_red) == len(FAILS) else 1)
if PERTURB or PERTURB_NS:
    if FAILS:
        print("PERTURB OK (%s) — %d checks went red" % ("--perturb-ns" if PERTURB_NS else "--perturb", len(FAILS))); sys.exit(0)
    print("PERTURB FAILED — nothing went red"); sys.exit(1)
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS")
