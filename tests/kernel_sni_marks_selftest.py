"""Self-test — KERNEL-SNI MARKED THE CONNECTION AND NEVER THE PACKET, so it routed nothing.

`ip rule fwmark` reads the PACKET's mark. `-j CONNMARK --set-mark` writes the CONNECTION's. Kernel-SNI's
learned-IP rule wrote only the second and relied — in a docstring that said so in as many words — on "the
nft ct-restore carr[ying] it to the packet". It cannot: the restore (`ct direction original meta mark set
ct mark`) lives in the nft prerouting chain at priority `mangle`, and the SWGK chain is iptables mangle
PREROUTING — the SAME priority, registered after it. The restore therefore always reads the ct mark from
BEFORE SWGK ran, and the packet SWGK just marked leaves unmarked.

⚠️ WORSE THAN "DOES NOT ROUTE". The SYN goes out the WAN and is SNATted there; later packets of the same
flow DO carry the restored mark and are routed into the exit's table instead. The flow is split across two
paths and dies — so the engine breaks exactly the traffic it matches, instead of merely mis-sending it.

MEASURED on hel-flux (bare metal, a real WireGuard client in a netns, destination already learned into the
ipset). Before: the ipset rule matched **36 packets**, not one reached the exit, every packet left by the
WAN, `curl` returned **http=000 with 0 bytes**, and the cascade's SNAT counter at the far end never moved.
The diagnosis was confirmed by adding a SECOND ct-restore at a later hook priority — nothing else changed —
which turned the same request into **http=200, 253,954 bytes**, marked packets 4 → 113, and moved the far
end's counter. After the fix, with no observer in place: **http=200, 253,954 bytes**, far-end SNAT 6 → 7,
and an unmatched host still egressing direct as the node's own address.

⚠️ AND NO CELL IN THE CAMPAIGN WOULD HAVE CAUGHT IT. Every kernel-SNI run measured that the rules were
BUILT, that xt_string matched, and that the ipset filled — the cause, never the consequence. The engine was
green on four arms while delivering nothing.

The second half is the reset flag, which had the same shape: the reject lives in the nft FORWARD hook and
tests `meta mark`, so with only a CONNMARK the RST fired ONE PACKET LATE — observed as a 52-byte packet,
never the 517-byte ClientHello that triggered it. A packet late means that ClientHello has already been
forwarded out the WAN, which is the one thing an exit exists to prevent.

⚠️ THE CT MARK IS SAVED, NOT RE-SEARCHED. `-m string` is a match module — every rule carrying it runs its
own Boyer-Moore search, and iptables shares nothing between rules. Writing the connection mark per operand
therefore cost a THIRD search of a needle two other rules had already searched for: measured on the real
chain at the 256-operand cap, 512 searches per scanned packet before the packet-mark fix, **768** after,
**512** with one mark-keyed `--save-mark` per entry. Section [6] is why the LEARN rule may not be keyed the
same way, which is the version that looks even cheaper and silently mixes two categories together.

Run: python3 tests/kernel_sni_marks_selftest.py      (0 = pass)
     --perturb   drops the packet-mark rules, the way it shipped, and expects RED.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

NSRC = open(NODED, encoding="utf-8").read()
_P1 = '''        rules.append(["-A", CHAIN, "-s", e["subnet"], "-m", "set", "--match-set", setn, "dst", "-j", "MARK", "--set-mark", T])
'''
_P2 = '''                rules.append(["-A", CHAIN, *_xts_scan(e["subnet"]), "--string", d, "-j", "MARK", "--set-mark", hex(reset_mark)])
'''
# The ct-mark save sits OUTSIDE the operand loop, so reverting the reset half means putting the per-operand
# CONNMARK back AND taking this away — otherwise the perturbed tree is neither shape.
_SAVE = '''            rules.append(["-A", CHAIN, "-s", e["subnet"], "-m", "mark", "--mark", hex(reset_mark),
                          "-j", "CONNMARK", "--save-mark"])
'''
_SHIPPED = '''                rules.append(["-A", CHAIN, *_xts_scan(e["subnet"]), "--string", d, "-j", "CONNMARK", "--set-mark", hex(reset_mark)])
'''
# ⚠️ ASSERT BEFORE PERTURBING. A replacement that matches nothing leaves the tree intact and the run reads
# as a clean PASS while measuring the code it was supposed to break.
assert NSRC.count(_P1) == 1, "phase-1 packet-mark anchor missing — this run would FALSE-PASS"
assert NSRC.count(_P2) == 1, "reset packet-mark anchor missing — this run would FALSE-PASS"
assert NSRC.count(_SAVE) == 1, "ct-mark save anchor missing — this run would FALSE-PASS"
if PERTURB:
    # ⚠️ THE PERTURBED TREE MUST STILL PARSE. Deleting the MARK line alone left `for d in ops…:` with an
    # empty body, and the run died with an IndentationError — which `grep -c FAIL` reads as zero failures
    # and a non-zero exit reads as "caught". A crash is not a measurement. Swapping the line for the one it
    # replaced reproduces the SHIPPED chain exactly: learn + connection mark, no packet mark anywhere.
    NSRC = NSRC.replace(_P1, "").replace(_P2, _SHIPPED).replace(_SAVE, "")
    compile(NSRC, "<perturbed>", "exec")   # …and say so out loud if it ever stops parsing again

npath = NODED
if PERTURB:
    _fd, npath = tempfile.mkstemp(suffix=".py", prefix="ksni-", dir=HERE)
    os.write(_fd, NSRC.encode()); os.close(_fd)

def _load(p, n):
    l = importlib.machinery.SourceFileLoader(n, p)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(n, l))
    try: l.exec_module(m)
    except SystemExit: pass
    return m

N = _load(npath, "swgnoded")
if PERTURB:
    os.unlink(npath)


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err

CALLS = []
def fake_run(cmd, **kw):
    CALLS.append(list(cmd))
    if cmd[:1] == ["ipset"] and "list" in cmd:
        return R(0, "")
    # the "-C PREROUTING … -j SWGK" probe: say NOT hooked, so the builder rebuilds rather than short-circuits
    return R(0, "")

N.run = fake_run
N._kernel_sni_ok = lambda: True
N.GEO_DIR = tempfile.mkdtemp(prefix="ksni-geo-")

TABLE = "7000"
RESET = 0x9999
ENTRIES = [{"subnet": "10.15.0.0/24", "category": "custom_abc", "table": TABLE}]
res = {"errors": [], "changed": 0}
N._ensure_smart_xtstring(ENTRIES, {"custom_abc": ["wikipedia.org"]}, RESET, res,
                         active=True, ttl=3600, contains={"custom_abc": ["wikipedia"]})

# the chain as the node would have written it, in order
CHAIN = [c[3:] for c in CALLS if c[:3] == ["iptables", "-t", "mangle"] and "-A" in c and "SWGK" in c]
def txt(r):
    return " ".join(r)
LINES = [txt(r) for r in CHAIN]
print("[0] the chain the node builds")
for l in LINES:
    print("   " + re.sub(r"-m connbytes.*?original ", "", l))
check("it built a chain at all", len(LINES) >= 4, LINES)

print("\n[1] a LEARNED destination is marked on the PACKET, which is what `ip rule fwmark` reads")
setr = [l for l in LINES if "--match-set" in l]
mark_pkt = [l for l in setr if "-j MARK --set-mark " + TABLE in l]
mark_con = [l for l in setr if "-j CONNMARK --set-mark " + TABLE in l]
ret = [l for l in setr if "-j RETURN" in l]
check("the packet mark is set", len(mark_pkt) == 1, setr)
check("…and the connection mark too, so the rest of the flow keeps it", len(mark_con) == 1, setr)
check("…both before the RETURN that ends the lookup", bool(ret) and bool(mark_pkt) and bool(mark_con)
      and LINES.index(mark_pkt[0]) < LINES.index(ret[0]) and LINES.index(mark_con[0]) < LINES.index(ret[0]))
check("they mark the SAME set and subnet the RETURN matches",
      bool(ret) and bool(mark_pkt) and "--match-set" in mark_pkt[0]
      and mark_pkt[0].split("--match-set")[1].split("-j")[0] == ret[0].split("--match-set")[1].split("-j")[0])

print("\n[2] the FIRST-hit flag, which the nft forward hook rejects on — also a packet mark")
scan = [l for l in LINES if "--string" in l]
check("the ClientHello scan is still there", len(scan) >= 1, scan)
check("the reset flag is set on the packet", any("-j MARK --set-mark " + hex(RESET) in l for l in scan), scan)
check("…and the IP is still learned into the set", any("-j SET --add-set" in l for l in scan), scan)
# ⚠️ THE CONNECTION MARK IS STILL SET — by ONE mark-keyed rule per entry, not by a third string search.
# `-m string` is a match module, so a per-operand CONNMARK re-ran a Boyer-Moore search two other rules had
# already run: 512 searches per scanned packet at the 256-operand cap became 768. This is the same fact for
# one integer compare. What must stay true is that the ct mark still ends up set, or the restore, the nft
# reject and its counter all stop seeing it.
save = [l for l in LINES if "-j CONNMARK --save-mark" in l]
check("…and the connection mark is saved from it", len(save) >= 1, LINES)
check("…keyed on the mark, so it costs no search", all("--string" not in l for l in save), save)
check("…and gated on THIS chain's own flag, not on every packet",
      all("-m mark --mark " + hex(RESET) in l for l in save), save)
# The ordering is the whole reason it is emitted per entry rather than hoisted to one per subnet.
check("…and it comes AFTER the packet marks it copies",
      LINES.index(save[0]) > max(LINES.index(l) for l in scan if "-j MARK --set-mark " + hex(RESET) in l), LINES)
check("⚠️ no per-operand CONNMARK survives — that is the cost this removes",
      not any("-j CONNMARK --set-mark " + hex(RESET) in l for l in scan), scan)

print("\n[3] the invariant, stated once: nothing may pin a mark to a flow without marking the packet")
# Said as a rule rather than as two strings, so a THIRD mark added later cannot quietly repeat the bug.
conn_marks = {l.split("--set-mark ")[1].split()[0] for l in LINES if "-j CONNMARK --set-mark" in l}
pkt_marks = {l.split("--set-mark ")[1].split()[0] for l in LINES if "-j MARK --set-mark" in l}
check("every value written to a CONNMARK is also written to the packet mark",
      conn_marks and conn_marks <= pkt_marks, {"connmark": sorted(conn_marks), "packet": sorted(pkt_marks)})
# …and the OTHER way of pinning a mark to a flow — copying the packet's — is safe by construction only
# because the packet mark is set first. Stated so a `--save-mark` added somewhere with nothing above it
# cannot pass by writing the connection a mark the packet never carried.
for _s in save:
    _sub = _s.split("-s ")[1].split()[0]
    check("the save for %s follows a packet mark on the same subnet" % _sub,
          any("-j MARK --set-mark" in l and ("-s " + _sub) in l and LINES.index(l) < LINES.index(_s)
              for l in LINES), _s)

print("\n[4] the other engine already did this, and the two must not drift apart")
# Force-DNS never had the bug because its nft rule sets BOTH in one rule, on `ct state new`. Pinned here so
# the pair is read as one grammar rather than as two independent implementations.
check("Force-DNS sets the packet mark AND the ct mark in one rule",
      re.search(r"meta mark set [^\n]*ct mark set", NSRC) is not None)
check("…and the restore that carries it to later packets is still installed",
      "ct direction original meta mark set ct mark" in NSRC)

print("\n[5] the MARK SPACE is partitioned — and now that these values reach the PACKET, it has to be")
# ⚠️ THIS BECAME LOAD-BEARING WITH THE FIX ABOVE. While kernel-SNI wrote only a CONNMARK, a collision with
# a routing fwmark was invisible; `-j MARK` puts these values on the packet, where `ip rule fwmark` reads
# them, so an overlap would route the wrong traffic into the wrong table. The separation is real today —
# the exit band is hard-capped at [SWG_RT_BASE, SWG_RT_MAX] and the three flag marks sit far outside it —
# but it is stated only in three comments ("outside the 7000-band fwmarks", "not the cascade's table-shaped
# marks", "outside the 7000-7099 fwmark band"), which is a convention, not a guard. The band is the thing
# most likely to move: this panel is meant to grow to large fleets, and widening the band is how a future
# edit would silently swallow 0x7770 (30576) or 0x9999 (39321). Said once, here, as a rule.
BAND = range(N.SWG_RT_BASE, N.SWG_RT_MAX + 1)
FLAGS = {"SNI_RESET_MARK": N.SNI_RESET_MARK, "RELAY_MARK": N.RELAY_MARK, "TORRENT_MARK": N.TORRENT_MARK}
check("the exit fwmark band is a bounded range, not open-ended", len(BAND) < 1000, len(BAND))
for _n, _v in sorted(FLAGS.items()):
    check("%s (%s / %d) is outside the exit fwmark band %d-%d"
          % (_n, hex(_v), _v, N.SWG_RT_BASE, N.SWG_RT_MAX), _v not in BAND, _v)
check("…and no two flag marks collide with each other", len(set(FLAGS.values())) == len(FLAGS),
      sorted(FLAGS.items()))
# RELAY_RT is a TABLE id, and the relay's own note says it must stay outside the band the cascade flushes.
check("the relay's routing table also sits outside that band", N.RELAY_RT not in BAND, N.RELAY_RT)
# Every value this chain actually writes must be one of those two kinds and nothing else — so a mark
# invented inline, with no constant behind it, cannot slip in unnoticed.
_written = {int(m, 0) for m in (conn_marks | pkt_marks)}
check("every mark this chain writes is either an exit table or a declared flag",
      all(v in BAND or v in FLAGS.values() for v in _written),
      sorted(v for v in _written if v not in BAND and v not in FLAGS.values()))

print("\n[6] ⚠️ TWO CATEGORIES ON ONE SUBNET — the case that decides how the ct mark may be keyed")
# The cheap way to save another 256 searches is to key the LEARN rule on the mark as well. It is wrong, and
# only this shape shows it: a packet flagged by category A's operand still carries the mark when it reaches
# category B's `-j SET`, so A's address is learned into B's set and leaves by B's exit until the TTL runs
# out. Reproduced on a prototype before this landed. The rule that IS mark-keyed is safe for a reason that
# has to keep holding: it writes one constant and cannot name a category at all.
CALLS.clear()
N.GEO_DIR = tempfile.mkdtemp(prefix="ksni-geo2-")
N._ensure_smart_xtstring(
    [{"subnet": "10.15.0.0/24", "category": "news", "table": "7000"},
     {"subnet": "10.15.0.0/24", "category": "video", "table": "7001"}],
    {"news": ["bbc.co.uk"], "video": ["youtube.com"]}, RESET,
    {"errors": [], "changed": 0}, active=True, ttl=3600, contains={})
L2 = [txt(c[3:]) for c in CALLS if c[:3] == ["iptables", "-t", "mangle"] and "-A" in c and "SWGK" in c]
learn = [l for l in L2 if "-j SET --add-set" in l]
check("both categories still learn", len(learn) == 2, learn)
check("⚠️ every learn rule is keyed on its OWN string, never on the shared mark",
      all("--string" in l and "-m mark --mark" not in l for l in learn), learn)
# …and each category's learn names only its own set, so no rule can add to a set it does not belong to.
for _c in ("news", "video"):
    _own = [l for l in learn if "swgk_" + _c in l]
    check("the %s learn rule adds to swgk_%s and nothing else" % (_c, _c),
          len(_own) == 1 and "--string" in _own[0], _own)
sv2 = [l for l in L2 if "-j CONNMARK --save-mark" in l]
check("one ct-mark save per entry, so the second category's flags are saved too", len(sv2) == 2, sv2)
check("…and both write the same constant, which is what makes the duplicate harmless",
      len({l.split("-m mark --mark ")[1].split()[0] for l in sv2}) == 1, sv2)
# the ordering claim, on the shape that can actually break it
for _i, _s in enumerate(sv2):
    _before = [l for l in L2[:L2.index(_s)] if "-j MARK --set-mark " + hex(RESET) in l]
    check("save #%d follows at least one packet mark" % (_i + 1), bool(_before), L2)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
