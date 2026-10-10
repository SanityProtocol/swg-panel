#!/usr/bin/env python3
"""Self-test: the scan guard (docs/SCAN-GUARD-PLAN.md) — a source that SWEEPS many servers on a management port is
flagged and cut on those ports, our own fleet management is exempted, and nothing else about the mech table changes.

A SWEEP is one source reaching many DIFFERENT servers on a management port; a real user re-hits a known handful.
Measured on production 2026-10-10: malware swept 27–35 distinct :22 hosts an hour (46–60 /24s, never revisiting);
no legitimate user touched these ports at all, and the only legit high-fan-out source was our own fleet management
(10.10.0.4), which sweeps the fleet the same way — so it is named in an allowlist and left alone. The guard rides the
existing `portscan` mechanism (same subnets); its only new wire input is `scan_allow`.

  [1] with portscan on + an allowlist, `_ensure_mech_block` renders, PER portscan subnet, two rules BEFORE the 200/s
      meter: (a) a flagged source's new scan-port connections dropped and its flag RENEWED (`update @pscf…`), (b) a
      distinct-destination meter (`rate over <B>/<unit> burst <B>`) gated by the (src.dst) seen-set, flagging into the
      same @pscf the panel reads — both carrying `ip saddr != @scanallow`; the shared @scanports and @scanallow sets
      and the per-subnet (src.dst) seen-set exist; the untouched 200/s meter is still last
  [2] no allowlist → no @scanallow set and no `!= @scanallow` guard on the scan rules (nothing to exempt)
  [3] a node with NO portscan subnet (smtp only) builds no scan sets or rules even when an allowlist is sent — the
      allowlist means nothing without the guard — and still carries the v7 signature
  [4] the meter is a token bucket: SCAN_B distinct destinations pass, the next in the window is over (→ flagged); a
      source that re-hits the SAME few servers never crosses it (the seen-set counts a destination once per window)
  [5] the reader (_block_activity) still finds a flagged scanner in @pscf with the scan rules present — the extra
      `add @pscf…` on rule (b) and the `add @scs_…`/scanallow lines do not confuse the per-subnet attribution
  [8] an allowlist with OVERLAPPING entries — a host and its range, 10.10.0.0/24 + 10.10.0.4/32, which the panel stores
      as typed — renders a table REAL nft accepts: `nft -c`, then a live load in a throwaway network namespace, and the
      loaded @scanallow holds the union: 10.10.0.9 (only the /24) and 10.10.0.4 (the /32) are in it, 10.10.1.4 is not.
      Without auto-merge every nft from 1.0.2 to 1.1.3 refuses the whole table ("conflicting intervals specified"), and a
      node with no table yet ran with no SMTP / QUIC / port-scan drop at all (1.8.9 final-candidate round, SG-NFT F1)
  [9] every rule with `ct state new` has it right after `ip saddr <subnet>`, with an allowlist and without: an ESTABLISHED
      packet bails on its conntrack state before any set lookup, fib or allowlist. With @scanports first in (a) and (b)
      every established packet of a portscan subnet paid two pipapo lookups (SG-BEH F2: 200,002 per 100,000 packets, +213
      ns a packet); with fib and @scanallow first in the 200/s rule, a route lookup and an interval lookup (N3, N4)

[1]–[7] and [9] are hermetic: swg-noded imported, `run` stubbed (mirrors tests/mech_portscan_burst_selftest.py). [8] alone runs
the real nft, as root or through `sudo -n`, inside `unshare --net` (the namespace dies with the command; the host's ruleset is
never read or written); without either it is SKIPPED, and says so — never passed. The packets themselves are the rig's
job (root, netns): .campaign/rigs/portscan-burst-rig.sh, cell `scandist`.
Run: python3 tests/mech_scan_guard_selftest.py
     --perturb   eight plants, each on its own: the flag's renew turned into a plain add, the allowlist guard dropped,
                 scanallow built with no allowlist, the private-destination guard removed, the scanallow set without
                 auto-merge, `ct state new` back behind @scanports in (a) and in (b) and behind fib in the 200/s rule —
                 each must turn its own check red. Prints "PERTURB OK", exit 0 (exit 1 if a plant stayed green); a plant
                 whose check was SKIPPED is named as such.
"""
import importlib.machinery, importlib.util, os, re, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
os.environ["SWG_NO_REEXEC"] = "1"

FAILS, SKIPS = [], []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(src):
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src)
    ld = importlib.machinery.SourceFileLoader("noded_scan", path)
    N = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_scan", ld))
    try:
        ld.exec_module(N)
    except SystemExit:
        pass
    N.GEO_DIR = tempfile.mkdtemp(prefix="scangeo-")
    return N

class FakeNft:
    def __init__(self):
        self.table, self.loads = None, []
    def run(self, args, input_text=None, timeout=20):
        if args[:5] == ["nft", "list", "table", "inet", "swg_mech"]:
            return types.SimpleNamespace(returncode=0 if self.table is not None else 1, stdout=self.table or "", stderr="")
        if args[:2] == ["nft", "-f"]:
            text = open(args[2]).read()
            self.loads.append(text)
            self.table = "table inet swg_mech {" + text.split("table inet swg_mech {", 1)[1]
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

# 10.8.0.0/24 runs smtp + portscan, 10.9.0.0/24 portscan only, 10.12.0.0/24 quic only (no scan guard there).
MECH = {"10.8.0.0/24": ["smtp", "portscan"], "10.9.0.0/24": ["portscan"], "10.12.0.0/24": ["quic"]}
ALLOW = ["10.10.0.4/32"]
ALLOW_OVERLAP = ["10.10.0.0/24", "10.10.0.4/32"]   # [8]: a host and its range

def live_load(text):
    """[8]'s real nft, in a namespace of its own: `nft -c`, a live load, @scanallow listed back and three addresses looked
    up in it. Returns (stdout, stderr), or (None, why) when there is no root / `sudo -n` / unshare / nft to run it."""
    path = os.path.join(tempfile.mkdtemp(), "mech.nft")
    open(path, "w").write(text)
    script = ('command -v nft >/dev/null || { echo NONFT; exit 0; }; '
              'nft -c -f "$1"; echo "C=$?"; nft -f "$1"; echo "F=$?"; nft list set inet swg_mech scanallow; '
              'for a in 10.10.0.9 10.10.0.4 10.10.1.4; do '
              'nft get element inet swg_mech scanallow "{ $a }" >/dev/null 2>&1 && echo "IN $a" || echo "OUT $a"; done')
    pre = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try:
        r = subprocess.run(pre + ["unshare", "--net", "sh", "-c", script, "sh", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)[:120]
    if "NONFT" in r.stdout:
        return None, "nft is not installed"
    if "C=" not in r.stdout:
        return None, ((r.stderr or r.stdout).strip().splitlines() or ["rc %d" % r.returncode])[0][:120]
    return r.stdout, r.stderr

def render(N, mech=MECH, allow=ALLOW):
    nft = FakeNft(); N.run = nft.run
    N._ensure_mech_block(mech, {"changed": 0, "errors": []}, scan_allow=allow)
    return nft.loads[0] if nft.loads else ""

def lines_of(text):
    return [l.strip() for l in text.splitlines()]

def bucket_over(ts, rate_per_s, burst):
    """nft's token bucket: `burst` tokens, refilled at rate_per_s, full at the start; a packet with no token is over."""
    tok, last, over = float(burst), None, 0
    for t in ts:
        if last is not None:
            tok = min(burst, tok + (t - last) * rate_per_s)
        last = t
        if tok >= 1:
            tok -= 1
        else:
            over += 1
    return over

def run_checks(N, label=""):
    text = render(N)
    L = lines_of(text)
    # the two scan-rule lines + the 200/s line, for 10.8.0.0/24
    a_rule = [l for l in L if l.startswith("ip saddr 10.8.0.0/24") and "@scanports" in l and "update @pscf_10_8_0_0_24" in l]
    b_rule = [l for l in L if l.startswith("ip saddr 10.8.0.0/24") and "@scanports" in l and "meter scm_10_8_0_0_24" in l]
    c_rule = [l for l in L if l.startswith("ip saddr 10.8.0.0/24") and "meter psc_10_8_0_0_24" in l]
    unit = N.SCAN_WIN_UNIT; B = N.SCAN_B
    meter_ok = bool(b_rule) and ("limit rate over %d/%s burst %d packets" % (B, unit, B)) in b_rule[0]
    sets_ok = ("set scanports {" in text and "set scanallow {" in text
               and "set scs_10_8_0_0_24 {" in text and "set scs_10_9_0_0_24 {" in text
               and "10.10.0.4/32" in text)
    # order: both scan rules for a subnet come BEFORE its 200/s meter
    def idx(sub, needle):
        for i, l in enumerate(L):
            if l.startswith("ip saddr " + sub) and needle in l:
                return i
        return -1
    order_ok = all(0 <= idx(s, "update @pscf") < idx(s, "meter scm_") < idx(s, "meter psc_")
                   for s in ("10.8.0.0/24", "10.9.0.0/24"))
    allow_ok = bool(a_rule) and "ip saddr != @scanallow" in a_rule[0] and bool(b_rule) and "ip saddr != @scanallow" in b_rule[0]
    seen_gate = bool(b_rule) and "ip saddr . ip daddr != @scs_10_8_0_0_24 add @scs_10_8_0_0_24" in b_rule[0]
    check("[1] portscan+allowlist: (a) renew-drop + (b) distinct-dest meter %d/%s before the 200/s meter, sets + seen-gate + allowlist guard"
          % (B, unit),
          bool(a_rule) and meter_ok and bool(c_rule) and sets_ok and order_ok and allow_ok and seen_gate,
          {"a": a_rule[:1], "b": b_rule[:1], "meter_ok": meter_ok, "sets_ok": sets_ok, "order_ok": order_ok, "allow_ok": allow_ok, "seen": seen_gate})

    # [2] no allowlist → no scanallow set, no guard on the scan rules
    t2 = render(N, allow=[])
    L2 = lines_of(t2)
    b2 = [l for l in L2 if l.startswith("ip saddr 10.8.0.0/24") and "meter scm_10_8_0_0_24" in l]
    check("[2] no allowlist → no @scanallow set and no `!= @scanallow` on the scan rules",
          "set scanallow {" not in t2 and bool(b2) and "@scanallow" not in b2[0], {"b2": b2[:1]})

    # [3] no portscan subnet (smtp only), allowlist sent anyway → no scan sets/rules, still v7
    nft = FakeNft(); N.run = nft.run
    N._ensure_mech_block({"10.8.0.0/24": ["smtp"]}, {"changed": 0, "errors": []}, scan_allow=ALLOW)
    t3 = nft.loads[0] if nft.loads else ""
    sig3 = ""
    import contextlib
    with contextlib.suppress(OSError):
        sig3 = open(os.path.join(N.GEO_DIR, ".mech.sig")).read()
    # rebuild forced from a v6 holder → proves v7 is what it writes now
    check("[3] no portscan subnet → no scan sets/rules even with an allowlist; smtp drop still there",
          ("scanports" not in t3 and "scanallow" not in t3 and "scm_" not in t3 and "scs_" not in t3
           and "@mps_10_8_0_0_24" in t3 and sig3 != ""), t3[:200])

    # [4] the meter as a token bucket (rate SCAN_B per window, burst SCAN_B). Window → seconds for the sim.
    win_s = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]
    rate_s = B / float(win_s)
    at = lambda n, gap: [i * gap for i in range(n)]
    sweep = at(B + 6, 0.5)                                 # B+6 DISTINCT destinations, 0.5 s apart — a slow sweep
    over_sweep = bucket_over(sweep, rate_s, B)
    # a user re-hitting the same few servers: the seen-set means only the FIRST hit of each pair reaches the meter,
    # so N revisits of 3 servers = 3 metered events — never over. Modelled as 3 metered events over an hour.
    revisit = bucket_over(at(3, 1200), rate_s, B)
    check("[4] a %d-destination sweep trips the meter (≥1 over); re-hitting 3 servers never does" % (B + 6),
          over_sweep >= 1 and revisit == 0, {"sweep_over": over_sweep, "revisit_over": revisit})

    # [5] the reader on the full table as nft 1.0.9 lists it, with the scan rules present and a flagged scanner
    listing = """table inet swg_mech {
\tset pscf_10_8_0_0_24 {
\t\ttypeof ip saddr
\t\tsize 65535
\t\tflags dynamic,timeout
\t\telements = { 10.8.0.44 timeout 10m expires 9m }
\t}

\tset scanallow {
\t\ttypeof ip saddr
\t\tflags interval
\t\telements = { 10.10.0.4/32 }
\t}

\tset scanports {
\t\ttype inet_proto . inet_service
\t\tflags interval
\t\telements = { tcp . 22 }
\t}

\tset scs_10_8_0_0_24 {
\t\ttype ipv4_addr . ipv4_addr
\t\tflags timeout
\t\telements = { 10.8.0.44 . 45.1.2.3 timeout 59m }
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 10; policy accept;
\t\tip saddr 10.8.0.0/24 ip saddr != @scanallow meta l4proto . th dport @scanports fib daddr type != local ct state new ip saddr @pscf_10_8_0_0_24 update @pscf_10_8_0_0_24 { ip saddr timeout 600s } counter packets 7 bytes 420 drop
\t\tip saddr 10.8.0.0/24 ip saddr != @scanallow meta l4proto . th dport @scanports fib daddr type != local ct state new ip saddr . ip daddr != @scs_10_8_0_0_24 add @scs_10_8_0_0_24 { ip saddr . ip daddr timeout 3600s } meter scm_10_8_0_0_24 { ip saddr limit rate over 15/hour burst 15 packets } add @pscf_10_8_0_0_24 { ip saddr timeout 600s } counter packets 1 bytes 60 drop
\t\tip saddr 10.8.0.0/24 fib daddr type != local ct state new meter psc_10_8_0_0_24 size 65535 { ip saddr limit rate over 200/second burst 200 packets } add @pscf_10_8_0_0_24 { ip saddr timeout 600s } counter packets 0 bytes 0 drop
\t}
}
"""
    def run5(args, input_text=None, timeout=20):
        out = listing if args[:5] == ["nft", "list", "table", "inet", "swg_mech"] else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    N.run = run5
    N._P2P["on"] = False
    act = N._block_activity()
    check("[5] the reader names the swept-flagged scanner on its subnet (scanallow/scs lines don't confuse it)",
          act.get("10.8.0.0/24", {}).get("scan_ips") == ["10.8.0.44"], act.get("10.8.0.0/24"))

    # [6] consistency: a trusted source is exempt from EVERY portscan rule — the 200/s meter too — so it is never
    # added to @pscf and never shows as a scanner, which is what the "never flags" promise means. With an allowlist,
    # the 200/s rule carries `!= @scanallow`; without one, it does not.
    c_allow = [l for l in L if l.startswith("ip saddr 10.8.0.0/24") and "meter psc_10_8_0_0_24" in l]
    c_none = [l for l in lines_of(render(N, allow=[])) if l.startswith("ip saddr 10.8.0.0/24") and "meter psc_10_8_0_0_24" in l]
    check("[6] the 200/s meter carries `!= @scanallow` with an allowlist and not without — a trusted source never shows as a scanner",
          bool(c_allow) and "ip saddr != @scanallow" in c_allow[0] and bool(c_none) and "@scanallow" not in c_none[0],
          {"with": c_allow[:1], "without": c_none[:1]})

    # [7] private / internal destinations are out of scope — the @priv set exists and both scan rules exclude it, so a
    # user reaching their own LAN / a mesh peer / an internal service on a management port is neither counted nor cut.
    priv_ok = ("set priv {" in text and "10.0.0.0/8" in text and "192.168.0.0/16" in text
               and bool(a_rule) and "ip daddr != @priv" in a_rule[0]
               and bool(b_rule) and "ip daddr != @priv" in b_rule[0])
    check("[7] private/internal destinations excluded — @priv set exists and both scan rules carry `ip daddr != @priv`",
          priv_ok, {"set": "set priv {" in text, "a": a_rule[:1], "b": b_rule[:1]})

    # [8] an OVERLAPPING allowlist through REAL nft (SG-NFT F1). The batch is atomic, so one refused set is no table at
    # all on a node that had none; the render must load and the loaded set must still hold each entry's addresses.
    out, err = live_load(render(N, allow=ALLOW_OVERLAP))
    name8 = "[8] an overlapping allowlist (10.10.0.0/24 + 10.10.0.4/32) loads in real nft and @scanallow holds the union"
    if out is None:
        SKIPS.append("[8]")
        print("  SKIP " + name8 + "  — real nft cannot run here (no root, no `sudo -n`, or no unshare / nft): " + str(err))
    else:
        c, f = re.search(r"C=(\d+)", out), re.search(r"F=(\d+)", out)
        kept = re.search(r"elements = \{([^}]*)\}", out)
        check(name8,
              c.group(1) == "0" and bool(f) and f.group(1) == "0" and "IN 10.10.0.9" in out and "IN 10.10.0.4" in out
              and "OUT 10.10.1.4" in out,
              {"nft -c": c.group(1), "nft -f": f.group(1) if f else "?", "kept": kept.group(1).strip() if kept else None,
               "lookup": re.findall(r"(?:IN|OUT) [\d.]+", out), "nft": [l.strip() for l in (err or "").splitlines() if "Error" in l][:1]})

    # [9] `ct state new` right after the subnet in every rule that has it (SG-BEH F2, N3, N4) — 3 rules per portscan subnet,
    # 2 subnets, rendered with the allowlist and without.
    n9, bad9 = 0, []
    for t9 in (text, render(N, allow=[])):
        for l in lines_of(t9):
            if "ct state new" in l:
                n9 += 1
                if not re.match(r"ip saddr \S+ ct state new ", l):
                    bad9.append(l[:100])
    check("[9] `ct state new` comes right after `ip saddr <subnet>` in every rule that has it, with an allowlist and without",
          n9 == 12 and not bad9, {"rules": n9, "out of order": bad9[:3]})

SRC = open(NODED).read()
if "--perturb" in sys.argv:
    # The version bump (v7) is gated by tests/mech_portscan_burst_selftest.py [2]; here we plant the scan-guard's own
    # shape. Each anchor must appear in swg-noded exactly once.
    plants = {
        "flag not renewed (update → add) in rule (a)":
            (' fib daddr type != local update @" + _mech_flagged(S) +',
             ' fib daddr type != local add @" + _mech_flagged(S) +', "[1]"),
        "allowlist guard dropped from the scan rules":
            ('_na = "ip saddr != @scanallow " if _sa else ""',
             '_na = ""  # if _sa', "[1]"),
        "scanallow built with no allowlist":
            ('if meters and _sa:                                        # trusted sources',
             'if meters:                                                # trusted sources', "[2]"),
        "private-destination guard removed":
            ('lines.append("  set priv { typeof ip daddr; flags interval; elements = { 10.0.0.0/8',
             'lines.append("  set privX { typeof ip daddr; flags interval; elements = { 10.0.0.0/8', "[7]"),
        "scanallow without auto-merge":
            ('set scanallow { typeof ip saddr; flags interval; auto-merge; elements = { " + ", ".join(_sa)',
             'set scanallow { typeof ip saddr; flags interval; elements = { " + ", ".join(_sa)', "[8]"),
        "(a) checks @scanports before ct state new":
            (' ct state new meta l4proto . th dport @scanports " + _na +         # the flag',
             ' meta l4proto . th dport @scanports ct state new " + _na +         # the flag', "[9]"),
        "(b) checks @scanports before ct state new":
            (' ct state new meta l4proto . th dport @scanports " + _na +         # source',
             ' meta l4proto . th dport @scanports ct state new " + _na +         # source', "[9]"),
        "the 200/s rule checks fib (and the allowlist) before ct state new":
            (' ct state new " + _na + "fib daddr type != local meter "',
             ' " + _na + "fib daddr type != local ct state new meter "', "[9]"),
    }
    bad, skipped = [], []
    for name, (a, b, want) in plants.items():
        if SRC.count(a) != 1:
            print("PERTURB FAILED — anchor for %r not in swg-noded exactly once (found %d)" % (name, SRC.count(a))); sys.exit(1)
        FAILS.clear(); SKIPS.clear()
        print("-- plant: " + name)
        run_checks(load(SRC.replace(a, b)))
        if not any(f.startswith(want) for f in FAILS):
            (skipped if want in SKIPS else bad).append(name)
    print()
    print("PERTURB FAILED — stayed green: " + ", ".join(bad) if bad else
          "PERTURB OK — every plant that could run turned its check red; SKIPPED (real nft needs root or `sudo -n`): "
          + ", ".join(skipped) if skipped else "PERTURB OK — every plant turned its check red")
    sys.exit(1 if bad else 0)

run_checks(load(SRC))
print()
print(("ALL PASS" + (" — SKIPPED: %s (real nft needs root or `sudo -n`)" % ", ".join(SKIPS) if SKIPS else "")) if not FAILS
      else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
