#!/usr/bin/env python3
"""Self-test: the port-scan meter (`swg_mech`) lets a client's ordinary burst through and still cuts a scan.

The meter's limit carried no `burst`, so nft gave it 5: one address could open 5 connections in a row, then one per 5 ms. Every
packet of an unanswered UDP flow is `ct state new`, so a nested AmneziaWG handshake (10 packets) lost 6–10 on every try —
measured on msk-shadow 2026-10-08, reproduced on swgt and in `.campaign/rigs/portscan-burst-rig.sh` (5 of 10, 5 of 16 parallel
flows, 5 of 40) — and one handshake put the client in @pscf, where the panel names it as a scanner. A page load is the same
shape (Chrome netlogs of six sites: 1–10 SYNs lost a page at burst 5, 19–128 flows with QUIC and an outside resolver).

  [1] every meter rule swg-noded writes carries `limit rate over 200/second burst 200 packets` — the rate unchanged
  [2] a node that holds the v5 table (intact, its signature current for v5) rebuilds it once, then stays a no-op
  [3] the token bucket that rule describes, fed real bursts: a 10-packet handshake, 16 and 40 parallel flows, three handshake
      tries 5 s apart, and theverge.com's page load (TCP + QUIC + outside DNS, the worst of the six) → nothing dropped
  [4] …and a scan (3000 ports flat out) is still cut — no more than burst + 1 % through — and the rate holds over time
  [5] the reader: _block_activity still finds the flagged scanner in a listing of the new table as nft prints it (nft 1.0.9,
      the meter with its burst), per subnet, and an empty flagged set names nobody

Hermetic: swg-noded imported, `run` stubbed. The packets themselves are the rig's job (root, netns).
Run: python3 tests/mech_portscan_burst_selftest.py
     --perturb   two plants, each on its own: the burst removed (→ [1] [3] red), the signature left at v5 (→ [2] red);
                 prints "PERTURB OK", exit 0 (exit 1 if a plant stayed green)
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
os.environ["SWG_NO_REEXEC"] = "1"

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(src):
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src)
    ld = importlib.machinery.SourceFileLoader("noded_psb", path)
    N = importlib.util.module_from_spec(importlib.util.spec_from_loader("noded_psb", ld))
    try:
        ld.exec_module(N)
    except SystemExit:
        pass
    N.GEO_DIR = tempfile.mkdtemp(prefix="psbgeo-")
    return N

class FakeNft:
    """Holds the text `nft list table inet swg_mech` would print; records every load."""
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

MECH = {"10.8.0.0/24": ["smtp", "portscan"], "10.9.0.0/24": ["portscan"], "10.12.0.0/24": ["quic"]}
METER = re.compile(r"ct state new meter (psc_\S+) \{ ip saddr limit rate over (\d+)/second(?: burst (\d+) packets)? \}")

def render(N):
    nft = FakeNft(); N.run = nft.run
    N._ensure_mech_block(MECH, {"changed": 0, "errors": []})
    return nft.loads[0] if nft.loads else ""

def bucket(ts, rate, burst):
    """nft's limit: a bucket of `burst` tokens, refilled at `rate`/s, full at the start; a packet without a token is over."""
    tok, last, over = float(burst), None, 0
    for t in ts:
        if last is not None:
            tok = min(burst, tok + (t - last) * rate)
        last = t
        if tok >= 1:
            tok -= 1
        else:
            over += 1
    return over

# theverge.com loaded by headless Chrome (2026-10-08 netlog): every TCP connect attempt, every non-loopback UDP socket (QUIC),
# and two queries (A, AAAA) per DNS lookup — as if the device asked an outside resolver. Milliseconds since the previous flow.
VERGE = [int(x) for x in (
    "0,0,0,5,0,1,0,0,0,16,0,0,0,1,0,0,0,6,0,0,0,37,0,0,0,1,0,19,1,1,22,0,0,0,10,0,0,0,3,0,0,0,5,42,3,1,1,3,16,0,1,0,0,"
    "1,0,0,0,1,196,0,0,0,15,0,0,0,9,0,0,0,1,2,2,2,2,2,2,2,2,2,0,0,0,3,5,2,1,0,0,0,1,0,0,0,1,1,2,5,4,0,0,0,15,7,0,0,0,"
    "1,0,0,0,1,0,0,0,0,0,1,0,1,0,0,0,1,0,0,0,1,0,0,0,10,0,0,0,4,0,0,0,1,3,0,0,0,5,6,2,5,4,15,0,0,1,3,1,2,2,1,3,0,0,0,"
    "2,3,8,0,1,0,20,1,1,1,446,1,0,0,0,61,122,0,0,0,59,0,0,1,58,1,749,0,0,0,0,38,2,26,0,0,0,5,56,114,72,0,0,0,2,0,2,54,"
    "190,12,1292,0,0,0,0,21,38,40,831,0,1,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1,0,0,0,1,0,0,0,0,0,0,0,59,0,1,1,1,0,1,0,"
    "0,0,0,0,188,292,0,2,0,64,0,629,0,16,0,0,9,0"
).split(",")]

def verge_times():
    t, out = 0, []
    for d in VERGE:
        t += d / 1000.0
        out.append(t)
    return out

def run_checks(N, label=""):
    text = render(N)
    meters = METER.findall(text)
    check("[1] one meter per port-scan subnet, each `rate over 200/second burst 200 packets`",
          len(meters) == 2 and all(r == "200" and b == "200" for _, r, b in meters), meters)

    # [2] the v5 table on a node: exactly what this code wrote before the burst, its v5 signature stored
    nft = FakeNft(); N.run = nft.run
    N._ensure_mech_block(MECH, {"changed": 0, "errors": []})
    nft.table = nft.table.replace(" burst 200 packets", "")
    import hashlib, json
    portsets = {"10.12.0.0/24": ["udp . 443"], "10.8.0.0/24": ["tcp . 25"]}
    v5 = hashlib.sha256(json.dumps({"p": portsets, "m": ["10.8.0.0/24", "10.9.0.0/24"], "v": 5}, sort_keys=True).encode()).hexdigest()
    open(os.path.join(N.GEO_DIR, ".mech.sig"), "w").write(v5)
    nft.loads.clear()
    N._ensure_mech_block(MECH, {"changed": 0, "errors": []})
    rebuilt = len(nft.loads) == 1 and "burst 200 packets" in nft.loads[0] and nft.loads[0].startswith("delete table inet swg_mech")
    N._ensure_mech_block(MECH, {"changed": 0, "errors": []})
    check("[2] a node holding the v5 table rebuilds it once (delete + load in one transaction), then stays a no-op",
          rebuilt and len(nft.loads) == 1, (len(nft.loads), nft.loads[:1]))

    rate = int(meters[0][1]) if meters else 200
    burst = int(meters[0][2] or 5) if meters else 5        # what nft makes of a limit with no burst
    at = lambda n, gap=0.0: [i * gap for i in range(n)]
    cells = {"handshake, 10 packets back-to-back": at(10, 20e-6),
             "16 parallel flows": at(16, 20e-6), "40 parallel flows": at(40, 20e-6),
             "three handshake tries 5 s apart": [r * 5 + i * 20e-6 for r in range(3) for i in range(10)],
             "theverge.com page load, outside DNS": verge_times()}
    over = {k: bucket(v, rate, burst) for k, v in cells.items()}
    check("[3] ordinary bursts lose nothing: " + ", ".join(cells), not any(over.values()), over)

    scan = at(3000, 5e-6)                                  # 3000 probes in 15 ms
    slow_scan = at(4000, 1 / 400.0)                        # 400/s for 10 s: twice the rate, for long
    s1, s2 = 3000 - bucket(scan, rate, burst), 4000 - bucket(slow_scan, rate, burst)
    check("[4] a scan is still cut: flat out ≤ burst + 1 % through, 400/s for 10 s ≈ the rate (≤ 200·10 + burst + 1)",
          s1 <= burst + 30 and s2 <= rate * 10 + burst + 1, (s1, s2))

    # [5] the reader, on the table as nft 1.0.9 lists it (loaded in a netns, an element added to one flagged set)
    listing = """table inet swg_mech {
\tset mps_10_8_0_0_24 {
\t\ttype inet_proto . inet_service
\t\tflags interval
\t\telements = { tcp . 25 }
\t}

\tset pscf_10_8_0_0_24 {
\t\ttypeof ip saddr
\t\tsize 65535
\t\tflags dynamic,timeout
\t\telements = { 10.8.0.7 timeout 10m expires 9m59s990ms }
\t}

\tset pscf_10_9_0_0_24 {
\t\ttypeof ip saddr
\t\tsize 65535
\t\tflags dynamic,timeout
\t}

\tchain pre {
\t\ttype filter hook prerouting priority mangle - 10; policy accept;
\t\tip saddr 10.8.0.0/24 fib daddr type != local meta l4proto . th dport @mps_10_8_0_0_24 counter packets 3 bytes 180 drop
\t\tip saddr 10.8.0.0/24 fib daddr type != local ct state new meter psc_10_8_0_0_24 size 65535 { ip saddr limit rate over 200/second burst 200 packets } add @pscf_10_8_0_0_24 { ip saddr timeout 10m } counter packets 41 bytes 2460 drop
\t\tip saddr 10.9.0.0/24 fib daddr type != local ct state new meter psc_10_9_0_0_24 size 65535 { ip saddr limit rate over 200/second burst 200 packets } add @pscf_10_9_0_0_24 { ip saddr timeout 10m } counter packets 0 bytes 0 drop
\t}
}
"""
    def run5(args, input_text=None, timeout=20):
        out = listing if args[:5] == ["nft", "list", "table", "inet", "swg_mech"] else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    N.run = run5
    N._P2P["on"] = False
    act = N._block_activity()
    check("[5] the reader finds the scanner on its subnet, counts the port drops, and names nobody on the quiet one",
          act.get("10.8.0.0/24", {}).get("scan_ips") == ["10.8.0.7"] and act["10.8.0.0/24"].get("mech") == 3
          and act.get("10.9.0.0/24", {}).get("scan") == 0 and "scan_ips" not in act.get("10.9.0.0/24", {}), act)

SRC = open(NODED).read()
if "--perturb" in sys.argv:
    plants = {"the burst removed": (" burst 200 packets }", " }", "[1]"),
              "the signature left at v5": ('"v": 6}', '"v": 5}', "[2]")}
    bad = []
    for name, (a, b, want) in plants.items():
        if SRC.count(a) != 1:
            print("PERTURB FAILED — anchor for %r not in swg-noded exactly once" % name); sys.exit(1)
        FAILS.clear()
        print("-- plant: " + name)
        run_checks(load(SRC.replace(a, b)))
        if not any(f.startswith(want) for f in FAILS):
            bad.append(name)
    print()
    print("PERTURB OK — every plant turned its check red" if not bad else "PERTURB FAILED — stayed green: " + ", ".join(bad))
    sys.exit(1 if bad else 0)

run_checks(load(SRC))
print()
print("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
