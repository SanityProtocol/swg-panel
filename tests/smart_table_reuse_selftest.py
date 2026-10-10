#!/usr/bin/env python3
"""Self-test — the smart table is read once per ruleset, not once per pass (docs/CPU-PLAN.md B5b).

`nft list table inet swg_smart` cost 55 ms of nft every pass on swgt (63 % of the node's nft CPU) and its parse another
~25 ms of the node's own. What is taken from it changes only through a transaction, which bumps the ruleset's generation
id — except the per-category byte counters, read over netlink (B5a), and the SNI first-hit reset counter, now read from the
`forward` chain that _block_activity lists every pass anyway.

  [1] A pass whose generation id is the render's keeps it: no render; the set counts, the set names, the chains as they
      were; the bytes from netlink — the same document, keys in the same order, a render of those values would give.
  [2] The id moved — before the pass, or DURING the render (the render is kept with the id read before it) — or cannot be
      read: a render.
  [3] A render holding what the datapath changes by itself — an element with an expiry, a set an `add @` / `update @`
      rule or a meter fills — is never kept.
  [4] Netlink cannot read the counters, or lacks one of the render's: a render. A table with no byte counters is kept
      without a netlink read.
  [5] No table: read every pass, as before. The two invalidations (a table torn down for a rebuild) render again.
  [6] smart_status — what a node POSTs (I2): kept or rendered, the same sets, rules and active; `resets` follows the forward
      chain's counter every pass even while the render is kept; that chain is read ONCE a pass for both its readers.

Run: python3 tests/smart_table_reuse_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     stalebytes      a kept render keeps its bytes too
     nolive          a render holding expiring elements / datapath-filled sets is kept
     afterid         the render is kept with an id read after it (a commit during the render would be missed)
     resetstable     smart_status reads the reset counter from the (possibly kept) render
"""
import importlib.machinery, importlib.util, json, os, re, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
SRC = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "stalebytes": ('''                _SMART_TABLE.update(n=_LOOP["n"], bytes=_smart_cat_bytes((c, nl[c][1]) for c in _SMART_TABLE["cnames"]))''',
                   '''                _SMART_TABLE.update(n=_LOOP["n"])'''),
    "nolive": ('''    return "expires " in out or "add @" in out or "update @" in out or " meter " in out''', '''    return False'''),
    "afterid": ('''                            gen=gen if keep else None, cnames=cnames)''',
                '''                            gen=_nft_genid() if keep else None, cnames=cnames)'''),
    "resetstable": ('''    resets = sum(int(x) for x in re.findall(r"meta mark 0x0*9999 counter packets (\\d+)", _smart_forward()))''',
                    '''    resets = sum(int(x) for x in re.findall(r"meta mark 0x0*9999 counter packets (\\d+)", t["out"]))'''),
}
if PLANT:
    a, b = PLANTS[PLANT]
    assert SRC.count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
    SRC = SRC.replace(a, b)

T = tempfile.mkdtemp(prefix="smartkeep-")
prog = os.path.join(T, "swg-noded")
open(prog, "w", encoding="utf-8").write(SRC)
os.environ["SWG_NODED_STATE"] = os.path.join(T, "state")
ld = importlib.machinery.SourceFileLoader("sk_noded", prog)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("sk_noded", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
N.log = lambda *a, **k: None


def render(up=1000, dn=2000, gh=100, rst=7, catl="", extra_rule=""):
    """`nft list table inet swg_smart` as nft 1.0.9 prints it (the shape captured on swgt)."""
    return ("table inet swg_smart {\n"
            "\tcounter c_discord_up {\n\t\tpackets 10 bytes %d\n\t}\n\n"
            "\tcounter c_discord_dn {\n\t\tpackets 20 bytes %d\n\t}\n\n"
            "\tcounter c_github_up {\n\t\tpackets 1 bytes %d\n\t}\n\n"
            "\tcounter cnt_other {\n\t\tpackets 5 bytes 5\n\t}\n\n"
            "\tset cat_discord {\n\t\ttypeof ip daddr\n\t\tflags interval\n\t\tauto-merge\n\t\telements = { 1.0.0.0/24, 2.0.0.0/24 }\n\t}\n\n"
            "\tset catl_discord {\n\t\ttypeof ip daddr\n\t\ttimeout 1h\n%s\t}\n\n"
            "\tchain prerouting {\n\t\ttype filter hook prerouting priority mangle; policy accept;\n"
            "\t\tip saddr 10.8.0.0/24 ip daddr @cat_discord meta mark set 0x00000101\n%s\t}\n\n"
            "\tchain forward {\n\t\ttype filter hook forward priority filter; policy accept;\n"
            "\t\tip saddr 10.8.0.0/24 tcp dport 443 meta mark 0x00009999 counter packets %d bytes 420 reject with tcp reset\n\t}\n"
            "}\n") % (up, dn, gh, catl, extra_rule, rst)


def forward(rst):
    return ("table inet swg_smart {\n\tchain forward {\n\t\ttype filter hook forward priority filter; policy accept;\n"
            "\t\tip saddr 10.8.0.0/24 tcp dport 443 meta mark 0x00009999 counter packets %d bytes 420 reject with tcp reset\n\t}\n}\n" % rst)


K = {"table": render(), "rc": 0, "fwd": forward(7), "gen": [5], "nl": None, "commit_during": False}
CALLS = []


def fake_run(args, input_text=None, timeout=20, env=None):
    c = " ".join(args)
    CALLS.append(c)
    if c == "nft list table inet swg_smart":
        if K["commit_during"]:                               # another writer commits while nft is reading the ruleset
            K["gen"], K["commit_during"] = [K["gen"][-1] + 1], False
        return subprocess.CompletedProcess(args, K["rc"], K["table"] if not K["rc"] else "", "")
    if c == "nft list chain inet swg_smart forward":
        return subprocess.CompletedProcess(args, K["rc"], K["fwd"] if not K["rc"] else "", "")
    return subprocess.CompletedProcess(args, 0, "", "")


def genid():
    return K["gen"][0]


NLREADS = []


def nl_counters(table):
    NLREADS.append(table)
    return K["nl"]


N.run, N._nft_genid, N._nft_counters = fake_run, genid, nl_counters
N._dnsmasq_running = lambda: False
N._route_localnet_ok = lambda: True
N._blk_domains_read = lambda: {}


def a_pass():
    N._LOOP["n"] += 1
    CALLS.clear()
    t = N._smart_table()
    return t, sum(c == "nft list table inet swg_smart" for c in CALLS)


def nl_of(up, dn, gh):
    return {"c_discord_up": (11, up), "c_discord_dn": (21, dn), "c_github_up": (2, gh), "cnt_other": (6, 6)}


# ── [1] kept, bytes refreshed ─────────────────────────────────────────────────────────────────────────────────────────
print("[1] the generation id unchanged")
t1, r1 = a_pass()
snap1 = (dict(t1["counts"]), set(t1["setnames"]), t1["out"], t1["rc"])
check("[1] CONTROL: the first pass renders and parses", r1 == 1 and t1["counts"] == {"cat_discord": 2, "catl_discord": 0}
      and t1["bytes"] == {"discord": {"up": 1000, "dn": 2000}, "github": {"up": 100, "dn": 0}}, (r1, t1["counts"], t1["bytes"]))
K["nl"] = nl_of(1100, 2100, 200)
t2, r2 = a_pass()
check("[1] the next pass keeps the render: no `nft list table`", r2 == 0, CALLS)
check("[1] …the set counts, the set names, the text, the rc as they were",
      (dict(t2["counts"]), set(t2["setnames"]), t2["out"], t2["rc"]) == snap1)
fresh = N._smart_cat_bytes(re.findall(r"counter (c_[a-z0-9_]+) \{\s*packets \d+ bytes (\d+)", render(1100, 2100, 200)))
check("[1] …and the bytes from netlink: the document a render of those values gives, keys in its order",
      json.dumps(t2["bytes"]) == json.dumps(fresh) == json.dumps({"discord": {"up": 1100, "dn": 2100}, "github": {"up": 200, "dn": 0}}),
      (t2["bytes"], fresh))

# ── [2] the id moved, or cannot be read ───────────────────────────────────────────────────────────────────────────────
print("\n[2] the generation id moved, or cannot be read")
K["gen"] = [6]
_, r3 = a_pass()
check("[2] the id moved since the render: a render", r3 == 1)
K["gen"] = [None]
_, ra = a_pass()
_, rb = a_pass()
check("[2] an id that cannot be read: a render every pass", ra == 1 and rb == 1, (ra, rb))
K["gen"], K["commit_during"] = [7], True                     # read 7 before the render; a commit lands while nft reads (→ 8)
a_pass()
_, r4 = a_pass()
check("[2] the id moved DURING the render: the next pass renders again (it was kept with the id read before it)", r4 == 1)
_, r5 = a_pass()
check("[2] …and keeps that one", r5 == 0)

# ── [3] contents the datapath changes by itself ───────────────────────────────────────────────────────────────────────
print("\n[3] what the datapath changes by itself")
for what, kw in (("an element with an expiry", {"catl": "\t\telements = { 3.3.3.3 expires 59m58s }\n"}),
                 ("a set an `add @` rule fills", {"extra_rule": "\t\tip saddr 10.8.0.0/24 add @catl_discord { ip daddr }\n"}),
                 ("a set an `update @` rule fills", {"extra_rule": "\t\tip saddr 10.8.0.0/24 update @catl_discord { ip daddr }\n"}),
                 ("a meter", {"extra_rule": "\t\ttcp flags syn meter m1 size 128 { ip saddr limit rate 10/second } accept\n"})):
    K["table"], K["gen"] = render(**kw), [20]
    a_pass()
    _, rr = a_pass()
    check("[3] %s: rendered again on the next pass" % what, rr == 1)
K["table"] = render()

# ── [4] netlink ───────────────────────────────────────────────────────────────────────────────────────────────────────
print("\n[4] the byte counters over netlink")
K["gen"] = [30]
a_pass()
K["nl"] = None
_, r6 = a_pass()
check("[4] netlink cannot read them: a render", r6 == 1)
K["nl"] = {"c_discord_up": (1, 1)}
_, r7 = a_pass()
check("[4] netlink lacks one of the render's counters: a render", r7 == 1)
K["table"] = re.sub(r"\tcounter [^\n]+\{\n[^\n]+\n\t\}\n\n", "", render())
K["gen"] = [31]
a_pass()
NLREADS.clear()
t8, r8 = a_pass()
check("[4] a table with no byte counters is kept, without a netlink read", r8 == 0 and not NLREADS and t8["bytes"] == {}, (r8, NLREADS))
K["table"] = render()

# ── [5] no table; the invalidations ───────────────────────────────────────────────────────────────────────────────────
print("\n[5] no table; a table torn down for a rebuild")
K["rc"], K["gen"] = 1, [40]
_, ra = a_pass()
_, rb = a_pass()
check("[5] no table: read every pass", ra == 1 and rb == 1)
K["rc"] = 0
check("[5] both teardowns for a rebuild invalidate the render AND what keeps it",
      SRC.count('_SMART_TABLE.update(n=-1, gen=None)') == 2 and '_SMART_TABLE["n"] = -1' not in SRC)

# ── [6] smart_status, what the node POSTs ─────────────────────────────────────────────────────────────────────────────
print("\n[6] smart_status")


def status():
    N._LOOP["n"] += 1
    CALLS.clear()
    s = N.smart_status()
    return s, sum(c == "nft list table inet swg_smart" for c in CALLS), sum(c == "nft list chain inet swg_smart forward" for c in CALLS)


K["gen"], K["nl"], K["fwd"] = [50], nl_of(1000, 2000, 100), forward(7)
s1, ra, fa = status()
K["fwd"] = forward(9)
s2, rb, fb = status()
check("[6] CONTROL: rendered, then kept", ra == 1 and rb == 0, (ra, rb))
check("[6] kept or rendered: the same sets, rules and active", (s1["sets"], s1["rules"], s1["active"]) == (s2["sets"], s2["rules"], s2["active"])
      and s1["rules"] == 1 and s1["sets"] == {"cat_discord": 2, "catl_discord": 0}, (s1["sets"], s1["rules"]))
check("[6] resets follow the forward chain's counter while the render is kept (7 → 9)", (s1["resets"], s2["resets"]) == (7, 9),
      (s1["resets"], s2["resets"]))
check("[6] the forward chain is read once a pass for both its readers", fa == 1 and fb == 1, (fa, fb))
K["gen"] = [51]
s3, rc_, _ = status()
check("[6] a render of the same state reports the same document", rc_ == 1 and json.dumps(s3, sort_keys=False) == json.dumps(s2, sort_keys=False),
      (s3, s2))

import shutil
shutil.rmtree(T, ignore_errors=True)
print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if PLANT:
    print("(--plant %s expects RED above)" % PLANT)
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
