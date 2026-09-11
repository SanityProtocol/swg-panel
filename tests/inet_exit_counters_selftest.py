#!/usr/bin/env python3
"""Self-test for the EXIT-DEVICE counter pair — §5.3 of docs/WARP-EGRESS-PLAN.md, decisions 11/13/14.

`reconcile_inet_chain` used to count exactly `iface→wan` and `wan→iface`. We deliberately keep the default
route off an exit device (§5.1), so an interface egressing through one forwards `iface → <exit dev>` and
matched NEITHER rule: the internet lane read zero on exactly the nodes using the feature, and the Overview
widget and flow-map satellite had nothing to draw. The fix is one more output device per managed interface,
tagged `swg-inet-up:<ifn>@<dev>`, which pays for itself twice — the node TOTAL still moves (decision 11)
because the total sums every `swg-inet-*` line, and the `@` suffix splits the same bytes per exit device
(decisions 13/14).

⚠️ THE BUILDER AND THE READER ARE CHECKED AGAINST EACH OTHER, NOT AGAINST FIXTURES. This feature's one shipped
defect was a seam: a value computed at one end, consumed at the other, and carried by nobody — and three
reviews missed it because every gate fed each end a hand-built dict. So the fake iptables here is a real
little state machine: `reconcile_inet_chain` appends rules into it, `read_inet_bytes` parses what came out.
A comment grammar the two halves disagree about therefore CANNOT pass, whichever half is wrong.

Hermetic: no iptables, no network, no state dir. `run` and `_detect_wan` are the only stubs.

Run: python3 tests/inet_exit_counters_selftest.py (0 = pass).  --perturb backs the fix out (the chain is
built as if it had never been told about exits) and expects the checks to FAIL — a green run means nothing
until the red one is reachable.
"""
import ast, importlib.machinery, importlib.util, inspect, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
# Two halves, two perturbations: the BUILDER can stop tagging and the READER can stop splitting, and each
# must be independently provable. One mode that breaks both would let either half's checks be dead weight.
PERTURB = "--perturb" in sys.argv or "--perturb-reader" in sys.argv
P_READER = "--perturb-reader" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded", NODED)
spec = importlib.util.spec_from_loader("swgnoded", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

CHAIN, TABLE = N.SWG_INET_CHAIN, N.SWG_INET_TABLE
WAN = "eth0"
NODE_CFG = {"interfaces": {"wg1": {}, "awg2": {}}}


# ── a fake iptables that REMEMBERS, so the reader reads what the builder wrote ──────────────────────
class R:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class Iptables:
    """Just enough of iptables to hold rules: -N/-F/-A on one chain, -S to render, iptables-save -c to
    render with counters. Byte counts come from `self.bytes[comment]`, so a test can put traffic on one
    rule and see where it surfaces."""

    def __init__(self):
        self.exists = False
        self.jumped = False
        self.rules = []          # argv after "-A <chain>"
        self.bytes = {}          # comment -> (pkts, bytes)
        self.flushes = 0

    @staticmethod
    def _comment(argv):
        return argv[argv.index("--comment") + 1] if "--comment" in argv else ""

    def _render(self, argv):
        out = []
        for i, a in enumerate(argv):
            out.append('"%s"' % a if i and argv[i - 1] == "--comment" else a)
        return "-A " + CHAIN + " " + " ".join(out)

    def run(self, cmd, **kw):
        c = list(cmd)
        if c[:2] == ["iptables-save", "-c"]:
            if not self.exists:
                return R(1)
            ln = []
            for argv in self.rules:
                p, b = self.bytes.get(self._comment(argv), (0, 0))
                ln.append("[%d:%d] %s" % (p, b, self._render(argv)))
            return R(0, "\n".join(ln) + "\n")
        if c[0] != "iptables":
            return R(0, "")
        tbl = c[c.index("-t") + 1] if "-t" in c else "filter"
        if "-nL" in c:
            return R(0 if (self.exists and tbl == TABLE) else 1)
        if tbl != TABLE:
            return R(0, "")                                  # the legacy-filter migration path: nothing there
        if "-N" in c:
            self.exists = True; return R(0)
        if "-S" in c:
            if c[c.index("-S") + 1] == "FORWARD":
                return R(0, ("-A FORWARD -j " + CHAIN) if self.jumped else "-P FORWARD ACCEPT")
            return R(0, "\n".join(self._render(a) for a in self.rules))
        if "-I" in c:
            self.jumped = True; return R(0)
        if "-F" in c:
            self.rules = []; self.flushes += 1; return R(0)
        if "-A" in c:
            self.rules.append(c[c.index("-A") + 2:]); return R(0)
        return R(0, "")


IPT = Iptables()
N.run = lambda cmd, **kw: IPT.run(cmd, **kw)
N._detect_wan = lambda: WAN

_build, _read = N.reconcile_inet_chain, N.read_inet_bytes
if P_READER:
    # The reader forgets the `@` grammar: totals still right, split always empty. This is the half that would
    # silently ship as "the widget is just always zero".
    N.read_inet_bytes = lambda: (lambda r: r if r is None else dict(r, dev={}))(_read())
elif PERTURB:
    # The builder is told nothing about exits — the chain exactly as it was before §5.3. Faithful, and it
    # cannot raise, so a red run here is a CAUGHT bug and never a broken stub.
    N.reconcile_inet_chain = lambda cfg, exit_devs=(): _build(cfg)

sigs = lambda: sorted(Iptables._comment(a) for a in IPT.rules)
pair = lambda ifn, tag: {"swg-inet-up:" + ifn + tag, "swg-inet-dn:" + ifn + tag}


# ── 1. the chain: which output devices get a pair ───────────────────────────────────────────────────
print("\n[1] chain build — one pair per (managed iface, output device)")
N.reconcile_inet_chain(NODE_CFG, {"tun-lab0"})
have = set(sigs())
check("WAN pair still built, untagged", pair("wg1", "") | pair("awg2", "") <= have)
check("exit device gets its own pair", pair("wg1", "@tun-lab0") | pair("awg2", "@tun-lab0") <= have, have)
check("exactly 2 ifaces x 2 devices x 2 directions", len(IPT.rules) == 8, len(IPT.rules))
# `.get`-shaped, not `[0]`: with the builder backed out these rules do not exist, and a gate that RAISES
# there reports the same non-zero exit whether it caught the bug or simply fell over.
rule = lambda cm: next((a for a in IPT.rules if Iptables._comment(a) == cm), [])
inout = lambda a: (a[a.index("-i") + 1], a[a.index("-o") + 1]) if "-i" in a and "-o" in a else ()
check("up rule is iface -> exit device", inout(rule("swg-inet-up:wg1@tun-lab0")) == ("wg1", "tun-lab0"))
check("dn rule is exit device -> iface", inout(rule("swg-inet-dn:wg1@tun-lab0")) == ("tun-lab0", "wg1"))
check("counting only — no target", not any("-j" in a for a in IPT.rules))

print("\n[2] devices that must NOT get a second pair")
IPT.rules = []; IPT.exists = False
N.reconcile_inet_chain(NODE_CFG, {WAN, "wg1", "", None, "  "})
check("the WAN is not duplicated (it would double-count itself)", len(IPT.rules) == 4, sigs())
check("a MANAGED iface named as an exit gets no pair", not any("@wg1" in s for s in sigs()), sigs())
check("blank / None exit devices are dropped", not any("@" in s for s in sigs()), sigs())

# ── 3. the signature: rebuilds cost counters, so it must fire exactly when the set moves ─────────────
print("\n[3] rebuild only when the device set actually changes")
IPT.rules = []; IPT.exists = False
N.reconcile_inet_chain(NODE_CFG, {"tun-lab0"})
f0 = IPT.flushes
N.reconcile_inet_chain(NODE_CFG, {"tun-lab0"})
check("same exit set -> no flush, counters keep accruing", IPT.flushes == f0, IPT.flushes - f0)
N.reconcile_inet_chain(NODE_CFG, {"tun-lab0", "tun-lab1"})
check("a NEW exit rebuilds (the signature covers exits)", IPT.flushes == f0 + 1 and len(IPT.rules) == 12, len(IPT.rules))
N.reconcile_inet_chain(NODE_CFG, set())
check("the last exit going away rebuilds back to WAN-only", len(IPT.rules) == 4, sigs())

# ── 4. the reader, over the chain the builder just wrote ─────────────────────────────────────────────
print("\n[4] read_inet_bytes — one chain, two readings of it")
IPT.rules = []; IPT.exists = False
N.reconcile_inet_chain(NODE_CFG, {"tun-lab0"})
IPT.bytes = {"swg-inet-up:wg1": (5, 1000), "swg-inet-dn:wg1": (5, 2000),          # wg1 out the WAN
             "swg-inet-up:awg2@tun-lab0": (9, 300), "swg-inet-dn:awg2@tun-lab0": (9, 40)}   # awg2 out the exit
got = N.read_inet_bytes()
check("node total counts the WAN traffic", got["up"] >= 1000 and got["down"] >= 2000, got)
check("node total ALSO counts exit traffic (decision 11)", (got["up"], got["down"]) == (1300, 2040), got)
# One check, two facts, and neither can pass vacuously: the split names the exit device AND ONLY it, so an
# empty `dev` fails it and so does a `dev` that swept the untagged WAN pair in as a device of its own.
check("the split is the exit device alone — never the WAN", sorted(got["dev"]) == ["tun-lab0"], got["dev"])
check("…carrying only that device's bytes", got["dev"].get("tun-lab0") == {"up": 300, "down": 40}, got["dev"])

# ── 5. the sampler: rates, and what happens when a device goes away ──────────────────────────────────
print("\n[5] sample_inet / sample_exit — deltas off that same read")
N._INET.update({"t": 0.0, "cum": None, "rate": {"up": 0.0, "down": 0.0}, "drate": {}})
r0 = N.sample_inet(NODE_CFG, 100.0)
check("first sample sets a baseline only, node rate 0", r0 == {"up": 0.0, "down": 0.0}, r0)
check("…and no per-exit rate yet either", N.sample_exit() == {}, N.sample_exit())
IPT.bytes = {"swg-inet-up:wg1": (5, 1000), "swg-inet-dn:wg1": (5, 2000),
             "swg-inet-up:awg2@tun-lab0": (9, 600), "swg-inet-dn:awg2@tun-lab0": (9, 140)}   # +300 up, +100 down
N.sample_inet(NODE_CFG, 110.0)
check("per-exit rate is the delta over dt", N.sample_exit() == {"tun-lab0": {"up": 30.0, "down": 10.0}}, N.sample_exit())
check("node rate moved by the same bytes", N._INET["rate"] == {"up": 30.0, "down": 10.0}, N._INET["rate"])
IPT.bytes["swg-inet-up:awg2@tun-lab0"] = (9, 100)                                   # counter reset (chain rebuilt)
N.sample_inet(NODE_CFG, 120.0)
check("a counter reset clamps to 0, never negative", N.sample_exit().get("tun-lab0", {}).get("up") == 0.0, N.sample_exit())
IPT.rules = []; IPT.exists = False
N.reconcile_inet_chain(NODE_CFG, set())                                             # exit deleted
N.sample_inet(NODE_CFG, 130.0)
check("a device that left the chain stops being reported", N.sample_exit() == {}, N.sample_exit())
N.reconcile_inet_chain(NODE_CFG, {"tun-lab9"})
IPT.bytes = {"swg-inet-up:wg1@tun-lab9": (1, 9_000_000)}
N.sample_inet(NODE_CFG, 140.0)
check("a brand-new device reports no rate until it has a baseline", N.sample_exit() == {}, N.sample_exit())
IPT.bytes["swg-inet-up:wg1@tun-lab9"] = (2, 9_005_000)      # +5000 over 10s — measured FROM the baseline,
N.sample_inet(NODE_CFG, 150.0)                              # never from zero, or adopting a busy device
check("…and a real rate on the next pass", N.sample_exit() == {"tun-lab9": {"up": 500.0, "down": 0.0}},
      N.sample_exit())                                      # would report its whole lifetime as one spike
snap = N.sample_exit()
for _v in snap.values():
    _v["up"] = -1
check("sample_exit hands back a copy, not the live cache", N.sample_exit().get("tun-lab9", {}).get("up") == 500.0)

# ── 6. the two seams — the thing three reviews missed last time ───────────────────────────────────────
print("\n[6] seams: the value is computed, and something CARRIES it")
src = inspect.getsource(N)
calls = [n for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "reconcile_inet_chain"]
check("the sync loop calls reconcile_inet_chain", len(calls) == 1, len(calls))
arg = ast.dump(calls[0].args[1]) if calls and len(calls[0].args) > 1 else ""
check("…and hands it a SECOND argument", bool(arg), "called with %d args" % (len(calls[0].args) if calls else 0))
check("…built from the cascade plan's devexit list", "'devexit'" in arg and "'dev'" in arg, arg[:120])
sn = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "build_snapshot"]
sbody = ast.dump(sn[0]) if sn else ""
check("the snapshot reports exit_rate", "'exit_rate'" in sbody)
check("…from sample_exit, not a hand-built dict", "'sample_exit'" in sbody)

print("\n[7] the PANEL's reader can trust the shape it is handed")
# ⚠️ A SNAPSHOT IS REMOTE INPUT AND A NODE ONLY RECONCILES ON A 200, so a value of the wrong type in the
# per-exit RRD writer would raise, the sync would 500, and that node would never converge again. This USED
# to be three guards in the loop itself. They are gone on purpose: `_snap_sanitise` now cleans the telemetry
# at BOTH doors into the snapshot cache, so the loop states that invariant instead of re-answering it —
# a second answer to a settled question is the kind that rots while the first one changes.
# What that contract IS, and that both doors keep it, is gated by tests/snap_shape_selftest.py.
_psrc = open(os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("the sanitiser exists and covers exit_rate",
      "_SNAP_TELEMETRY" in _psrc and '"exit_rate"' in _psrc.split("_SNAP_TELEMETRY")[1][:120],
      _psrc.split("_SNAP_TELEMETRY")[1][:80] if "_SNAP_TELEMETRY" in _psrc else "absent")
check("…and its own gate is in the tree, so the contract is not just asserted here",
      os.path.exists(os.path.join(ROOT, "tests", "snap_shape_selftest.py")))

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d checks went red" % ("reader" if P_READER else "builder", len(FAILS))) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed: this gate guards nothing")
    sys.exit(0 if ok else 1)
print(("FAIL: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
