#!/usr/bin/env python3
"""Self-test for `_SMART_MARK_RE` — the count behind `smartroute.rules` and `smartroute.active`.

The bug this locks down: the regex was `ip saddr \\S+ ip daddr @\\S+ meta mark set`, written before the
per-connection pin put `ct state new` between those two clauses. From that day on it matched NOTHING on
either SNI engine, and it never matched a catch-all (which carries no `ip daddr @` at all). Every node in
the fleet reported `active: false` and `rules: 0` while its chain was built, populated and marking. Nothing
on any screen reads the two fields, which is why it survived: a health number nobody looks at is a number
nobody checks.

FIXTURES ARE CAPTURED FROM REAL NODES, not written from the regex — one `nft list table inet swg_smart`
prerouting chain per routing mode off msk-main (bare metal, kernel / forcedns / sni_kernel / sni) plus
svo-im (docker) for the catch-all + explicit-direct shape that no other mode produces. Deriving them from
the pattern under test is how a counting bug passes its own gate.

Run: python3 tests/smart_rulecount_selftest.py (0 = pass).
  --perturb   restore the pre-fix regex and expect the fixtures to go red.
"""
import importlib.machinery, importlib.util, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv

# ── the shapes, exactly as `nft list` renders them back on a live node ────────────────────────
# (name, chain text, how many rules mark a packet into a category)
FIXTURES = [
    ("kernel · IP-only, one exit rule (msk-main)", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
		ip saddr 10.8.0.0/24 ip daddr @cat_custom_0a16e96ac5 meta mark set 0x00001b59 return
	}
""", 1),
    ("forcedns · same shape, dnsmasq fills the set (msk-main)", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
		ip saddr 10.8.0.0/24 ip daddr @cat_custom_1eece5fc77 meta mark set 0x00001b59 return
	}
""", 1),
    ("sni_kernel · pinned, so `ct state new` splits the two clauses (msk-main)", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
		ct direction original meta mark set ct mark
		ip saddr 10.8.0.0/24 udp dport 443 drop
		ip saddr 10.8.0.0/24 ct state new ip daddr @cat_custom_1eece5fc77 meta mark set 0x00001b59 ct mark set 0x00001b59 return
	}
""", 1),
    ("sni · pinned AND a learned set, so TWO mark rules + the NFQUEUE line (msk-main)", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
		ct direction original meta mark set ct mark
		ip saddr 10.8.0.0/24 udp dport 443 drop
		ip saddr 10.8.0.0/24 ct state new ip daddr @cat_custom_1eece5fc77 meta mark set 0x00001b59 ct mark set 0x00001b59 return
		ip saddr 10.8.0.0/24 ct state new ip daddr @catl_custom_1eece5fc77 meta mark set 0x00001b59 ct mark set 0x00001b59 return
		ip saddr 10.8.0.0/24 tcp dport 443 ct state established ct packets < 12 queue flags bypass to 0
	}
""", 2),
    ("catch-all + explicit direct — the one shape with no `ip daddr @` (svo-im, docker)", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
		ip saddr 10.8.0.0/24 ip daddr @cat_custom_b0af86399d return
		ip saddr 10.8.0.0/24 meta mark set 0x00001b58
	}
""", 1),
    ("nothing configured", """
	chain prerouting {
		type filter hook prerouting priority mangle; policy accept;
	}
""", 0),
]

# Lines that set a mark but are NOT a category decision. Written out because the regex is deliberately
# literal rather than "some words, then a mark": these are what a looser one would swallow.
NEGATIVES = [
    ("the pin's restore rule (no `ip saddr`)", "\t\tct direction original meta mark set ct mark\n"),
    ("swg_relay's tproxy divert (another table, same opening clause)",
     "\t\tip saddr 10.8.0.0/24 meta l4proto tcp socket transparent 1 meta mark set 0x1 accept\n"
     "\t\tip saddr 10.8.0.0/24 meta l4proto tcp tproxy ip to :9998 meta mark set 0x1 accept\n"),
    ("the SNI first-hit reset in the forward chain",
     "\t\tip saddr 10.8.0.0/24 tcp dport 443 meta mark 0x00009999 counter packets 0 bytes 0 reject with tcp reset\n"),
    ("the kill-switch catch-all (a drop, not a mark)", "\t\tip saddr 10.8.0.0/24 ct state new drop\n"),
    ("a block rule against a set", "\t\tip saddr 10.8.0.0/24 ip daddr @cat_blku_ads counter drop\n"),
]

OLD_RE = r'r"^\\s*ip saddr \\S+ (?:ct state new )?(?:ip daddr @\\S+ )?meta mark set (?:0x)?[0-9a-fA-F]+"'
src = open(NODED).read()
path = NODED
if PERTURB:
    frm = '''_SMART_MARK_RE = re.compile(
    r"^\\s*ip saddr \\S+ (?:ct state new )?(?:ip daddr @\\S+ )?meta mark set (?:0x)?[0-9a-fA-F]+", re.M)'''
    to = '''_SMART_MARK_RE = re.compile(r"ip saddr \\S+ ip daddr @\\S+ meta mark set")'''
    if src.count(frm) != 1:
        print("HARNESS BROKEN: perturbation matched %d times, not 1" % src.count(frm))
        sys.exit(2)
    src = src.replace(frm, to, 1)
    path = os.path.join(tempfile.mkdtemp(), "swg-noded")
    open(path, "w").write(src)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

loader = importlib.machinery.SourceFileLoader("swgnoded", path)
spec = importlib.util.spec_from_loader("swgnoded", loader)
N = importlib.util.module_from_spec(spec)
try:
    loader.exec_module(N)
except SystemExit:
    pass

RE = N._SMART_MARK_RE

print("── captured chains ──")
for name, body, want in FIXTURES:
    got = len(RE.findall(body))
    check("%-72s → %d" % (name, want), got == want, "counted %d" % got)

print("── `active` is `rules > 0`, so a miscount is a wrong health verdict ──")
for name, body, want in FIXTURES:
    check("active for: " + name[:60], (len(RE.findall(body)) > 0) == (want > 0))

print("── lines that set a mark but are not a category decision ──")
for name, body in NEGATIVES:
    got = len(RE.findall(body))
    check(name, got == 0, "counted %d" % got)

print("── the emitter still writes what this reads ──")
real = open(NODED).read()
for frag in ('_add("ip", "saddr", S, *_new, "ip", "daddr", "@" + snm, "meta", "mark", "set", str(T)',
             '_add("ip", "saddr", S, *_new, "meta", "mark", "set", str(T)',
             '_new = ["ct", "state", "new"] if pin else []'):
    check("emitter fragment present: " + frag[:56], frag in real,
          "the rule shape moved — re-capture the fixtures from a live node before touching the regex")
check("rules is counted with _SMART_MARK_RE", "rules = len(_SMART_MARK_RE.findall(t[\"out\"]))" in real)

print("── the counter reaper and the counter minter spell the name the same way ──")
# The reap added beside the set reap builds a WANTED set and deletes everything else in the table. So a name
# the two sites spell differently is not a visible mismatch — it is a LIVE counter the wanted-set fails to
# name, deleted, taking that category's cumulative history with it. Both derived it inline from
# `_smart_setname(c)[4:]`; one function now, and this fails if a third spelling appears.
minted = [l.strip() for l in real.splitlines()
          if "_smart_setname(" in l and ('"c_"' in l or "'c_'" in l) and not l.strip().startswith("#")]
check("only _smart_countername builds a counter name from a set name", len(minted) == 1, minted)
check("…and that one line IS the helper", minted and minted[0].startswith("return "), minted)
for site in ("cn = _smart_countername(c)", "{_smart_countername(c) + \"_\" + d",
             "snm, cn = _smart_setname(c), _smart_countername(c)"):
    check("both callers go through it: " + site[:34], site in real)
# and the derivation itself survives a category whose name needs sanitising
check("a category that sanitises still yields a c_-prefixed nft-legal name",
      N._smart_countername("RU Net-2") == "c_ru_net_2" and
      N._smart_countername("x") == "c_" + N._smart_setname("x")[4:],
      N._smart_countername("RU Net-2"))

print()
if PERTURB:
    if FAILS:
        print("PERTURB OK — %d check(s) red with the pre-fix regex: %s" % (len(FAILS), FAILS[:4]))
        sys.exit(0)
    print("PERTURB FAILED — the old regex still passed every fixture")
    sys.exit(1)
if FAILS:
    print("FAIL: %d — %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("PASS")
