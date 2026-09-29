#!/usr/bin/env python3
"""Self-test — Hybrid SNI blocks a NAME per connection and never drops its ADDRESS (docs/KSNI-HOSTNAMES-PLAN.md D1).

The field defect (a client, 1.8.7, 2026-09-26; reproduced on msk-main 2026-09-28): a content filter's tracker names live
on the same front ends as the services beside them (Google, Facebook, CloudFront). swg-sni learned a blocked name's
destination into the block's `catl_` set and swg-noded dropped every packet to it, so `googleads.g.doubleclick.net` on
172.217.113.4 took `youtubei.googleapis.com` on 172.217.113.4 down with it — for as long as trackers kept being seen.

Now swg-noded tells swg-sni, per source subnet, the rules in its chain's order (`sni-blocks.json`), swg-sni refuses the
ClientHello of a blocked name with `(entry << 16) | 0x9998`, and one forward rule resets it. What is checked, on the REAL
programs — swg-noded's `_ensure_smart_nft` through the nft transaction model (tests/nft_guarded_model.py) and swg-sni's
`Classifier` fed real IPv4/TCP/TLS ClientHello packets built from the payload swg-noded wrote:

  [1] the chain: no rule matches a Block's learned set (the address drop is gone); a host-only union's static set is not
      matched either; a Block's STATIC half still drops by address; the forward chain resets the block mark
  [2] the payload: every source that has a Block, its rules in chain order with their shadows; block-only categories are
      not learned (`nolearn`), a category a routing rule uses is
  [3] THE COLLATERAL, end to end: the tracker's ClientHello from the filtered subnet is refused (mark → forward → reset);
      the allowed name on the SAME address passes; the address never enters a set; the next connection to the address
      for another name passes the chain (no drop)
  [4] per interface: the same tracker from a subnet WITHOUT the filter passes
  [5] order: an Exit ABOVE a Block that claims the same name at the same rung keeps it; a Block above an Exit refuses it
  [6] per person: a Block row refuses only its chosen devices
  [7] IP rules in order: an Exit above a name Block whose STATIC set holds the destination gets the connection back in
      the post-queue chain `svb` (its route restored, accepted); an address outside it is still refused; `svb` exists only
      for that shape
  [8] a node with no Block writes no payload and signs its chain exactly as before (nothing rebuilds on upgrade)
  [9] the blocked counter: `_block_activity` reads the forward reset under "*"

Hermetic: no nft, no root, no network. Run: python3 tests/sni_block_by_name_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     learndrop  swg-noded matches a Block's learned set again (the address drop)            [1]
     norst      the forward chain has no reset for the block mark                            [1]
     anysrc     swg-sni refuses a blocked name from every source                              [4]
     blocksonly swg-sni walks only the Block rules (an Exit above loses its name)             [5]
     nosel      swg-sni ignores a rule's selection                                            [6]
     ipsel      swg-sni takes an address for the person whatever device it came in on        [6]
     learnblk   swg-sni learns a block-only category (its address enters a set)               [3]
     nosvb      the post-queue chain is never built                                           [7]
     nosig      a node with a Block does not re-sign (a running node keeps the address drop)  [8]
     nocount    the blocked counter skips the forward reset                                   [9]
     relay      the relay's companion rule takes a refused ClientHello again                  [10]
     relayinp   the relay's input chain has no refusal (early demux delivers the refused packet there) [10]
     inpcount   the blocked counter skips the relay's input refusal                           [10]
"""
import hashlib, importlib.machinery, importlib.util, json, os, shutil, socket, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")
sys.path.insert(0, HERE)
from nft_guarded_model import SmartKernel  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
SECTION = [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


PLANTS = {   # name: (sections it must redden, file, anchor, replacement)
    "learndrop": ("[1]", "noded", '            return [] if str(c).startswith("blku:host:") else [(_smart_setname(c), [])]',
                  '            return [(_smart_setname(c), []), (_smart_learnsetname(c), [])]'),
    "norst": ("[1]", "noded", "            if blk_rst:                                    # a BLOCK BY NAME (D1/D3)",
              "            if False:                                    # a BLOCK BY NAME (D1/D3)"),
    "anysrc": ("[4]", "sni", "            if src & m == net:\n                rules = rl\n                break",
               "            if True:\n                rules = rl\n                break"),
    "blocksonly": ("[5]", "sni", "                    return mark if act == \"block\" else 0",
                   "                    if act == \"block\": return mark"),
    "nosel": ("[6]", "sni", "                if me not in sel.get(who, ()):\n                    continue", "                if False:\n                    continue"),
    "ipsel": ("[6]", "sni", "                me = me or (self._ifname(indev), src)\n                if me not in", "                me = me or (\"wgq\", src)\n                if me not in"),
    "learnblk": ("[3]", "sni", "                if cat in self.nolearn:                    # only Block rules use it",
                 "                if False:                    # only Block rules use it"),
    "nosvb": ("[7]", "noded", "            if ex:\n                svb_of[(i + 1) << 16 | SNI_BLOCK_MARK] = ex",
              "            if False:\n                svb_of[(i + 1) << 16 | SNI_BLOCK_MARK] = ex"),
    "nosig": ("[8]", "noded", '    if (queue and _nb(("block",))) or blk_rst:', "    if False:"),
    "relay": ("[10]", "noded", """ct state != new meta mark & 0x0000fffe != %#010x meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept"
                 % (S, SNI_BLOCK_MARK, RELAY_MARK))""", """ct state != new meta l4proto tcp socket transparent 1 counter meta mark set 0x%x accept"
                 % (S, RELAY_MARK))"""),
    "relayinp": ("[10]", "noded", '            L.append("    ip saddr %s fib daddr type != local meta mark & 0x0000ffff == %#010x meta l4proto tcp counter reject with tcp reset"',
                 '            L.append("    ip saddr %s fib daddr type != local meta mark & 0x0000ffff == %#010x meta l4proto tcp counter"'),
    "inpcount": ("[10]", "noded", '            pk = re.search(r"counter packets (\\d+)", ln) if ("== %#010x" % SNI_BLOCK_MARK) in ln else None',
                 "            pk = None"),
    "nocount": ("[9]", "noded", '            pk = re.search(r"counter packets (\\d+)", ln) if ("%#010x" % SNI_BLOCK_MARK) in ln else None',
                "            pk = None"),
}
TMP = tempfile.mkdtemp(prefix="sni-blk-")
paths = {"noded": NODED, "sni": SNI}
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _sec, which, old, new = PLANTS[PLANT]
    src = open(paths[which], encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    paths[which] = os.path.join(TMP, "planted-" + os.path.basename(paths[which]))
    open(paths[which], "w", encoding="utf-8").write(src.replace(old, new, 1))


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


os.environ["SWG_NODED_STATE"] = TMP
N = load(paths["noded"], "swgnoded_blk")
S = load(paths["sni"], "swgsni_blk")
N.GEO_DIR = os.path.join(TMP, "geo")
T = N.SMART_NFT_TABLE

# ── the fleet's shape, in miniature: wgq filters (the ads union first, as the panel prepends it), wg0 does not ───────────
WGQ, WG0 = "10.188.1.0/24", "10.8.0.0/24"
UNION = "blku:host:4fe45fc4b8fa"
W1 = "1f2e3d4c5b6a"
ENTRIES = [
    {"subnet": WGQ, "category": UNION, "action": "block"},
    {"subnet": WGQ, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
    {"subnet": WGQ, "category": "custom_ipme", "action": "block"},                                  # a routing Block by name
    {"subnet": WGQ, "category": "custom_dual", "action": "block"},                                  # names AND an address
    {"subnet": WGQ, "category": "custom_row", "action": "block", "src": W1},                        # a per-person Block
    {"subnet": WGQ, "category": "all", "action": "direct"},
    {"subnet": WG0, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
    {"subnet": WG0, "category": "all", "action": "direct"},
]
SRCS = {W1: [["wgq", "10.188.1.5/32"]]}
DOMAINS = {UNION: ["g.doubleclick.net", "googleads.googleapis.com"], "google": ["googleapis.com", "google.com"],
           "custom_ipme": ["ip.me"], "custom_dual": ["dual.example"], "custom_row": ["row.example"]}
GFE = "172.217.114.4"
DUAL_IP = "198.51.100.7/32"                                      # custom_dual's static half


def fresh():
    shutil.rmtree(N.GEO_DIR, ignore_errors=True)
    os.makedirs(N.GEO_DIR)
    open(os.path.join(N.GEO_DIR, ".automerge-migrated"), "w").write("1")
    N._SRC_SETS.clear()
    K = SmartKernel()
    N.run = K
    return K


def npass(K, entries, queue=True, pin=True, name_cats=None):
    N._LOOP["n"] += 1
    res = {"changed": 0, "errors": []}
    try:
        N._ensure_smart_nft([dict(e) for e in entries], sorted({e["category"] for e in entries}), res, pin=pin, queue=queue,
                            reset_mark=(N.SNI_RESET_MARK if pin else 0), srcs=SRCS,
                            name_cats=set(DOMAINS) if name_cats is None else name_cats)
    except Exception as e:
        res["errors"].append("raised %s: %s" % (type(e).__name__, e))
    return res


def rules(K, chain):
    return [r["text"] for r in ((K.m.tables.get(T) or {}).get("chains", {}).get(chain) or {}).get("rules", [])]


# ── swg-sni, fed from the files swg-noded wrote ──────────────────────────────────────────────────────────────────────────
def hello(host):
    """A minimal TLS ClientHello record naming `host` (one extension, SNI)."""
    name = host.encode()
    sni = struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    ext = struct.pack(">HH", 0, len(sni)) + sni
    body = b"\x03\x03" + b"\x11" * 32 + b"\x00" + struct.pack(">H", 2) + b"\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs


def packet(src, dst, host, sport=40000):
    tls = hello(host)
    tcp = struct.pack(">HHIIBBHHH", sport, 443, 1000, 1, 5 << 4, 0x18, 65535, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(tls), 1, 0, 64, 6, 0, socket.inet_aton(src), socket.inet_aton(dst))
    return ip + tcp + tls


class NoNft:
    """swg-sni's `subprocess.run` (it writes learned addresses with `nft -f -`): records what would have been written."""
    def __init__(self):
        self.scripts = []

    def __call__(self, args, input=None, capture_output=True, text=True, **kw):
        self.scripts.append(input or "")
        return subprocess.CompletedProcess(args, 0, "", "")


def classifier(blocks):
    d = tempfile.mkdtemp(dir=TMP)
    mp = os.path.join(d, "sni-map.json")
    json.dump(DOMAINS, open(mp, "w"))
    if blocks:
        json.dump(blocks, open(os.path.join(d, "sni-blocks.json"), "w"))
    nn = NoNft()
    S.subprocess.run = nn
    c = S.Classifier(mp, T, reset_mark=N.SNI_RESET_MARK, learn_ttl=3600)
    return c, nn


def learned(c):
    with c._lock:
        pend = list(c._pending)
    return {(cat, ip) for cat, ip in pend} | {(cat, ip) for (ip, cat) in c.seen}


def fwd(K, mark):
    return K.m.chain_walk(T, "forward", "wgq", "10.188.1.9", GFE, mark=mark)


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
SECTION[0] = "[1]"
print("\n[1] the chain on Hybrid SNI")
K = fresh()
r = [npass(K, ENTRIES) for _ in range(2)]
K.load_set(T, N._smart_setname("custom_dual"), [DUAL_IP])
K.load_set(T, N._smart_setname("google"), ["172.217.0.0/16"])
r.append(npass(K, ENTRIES))
check("three passes run without an error, nothing refused by nft", not any(x["errors"] for x in r) and not K.refused,
      ([x["errors"] for x in r], K.refused[:2]))
pre = rules(K, "prerouting")
check("no rule matches a Block's learned set (no name's address is ever dropped)",
      not any(("@" + N._smart_learnsetname(c)) in t for t in pre for c in (UNION, "custom_ipme", "custom_dual", "custom_row")),
      [t for t in pre if "catl_" in t and "drop" in t])
check("…nor a host-only union's static set (always empty on Hybrid: a lookup per packet for nothing)",
      not any("@" + N._smart_setname(UNION) in t for t in pre), [t for t in pre if "blku" in t])
check("a Block's STATIC half still drops by address (itself, or through its pin-mode chain below an Exit)",
      any("@" + N._smart_setname("custom_dual") in t and (t.endswith("drop") or " jump pb" in t) for t in pre), pre)
v = K.m.packet(T, "wgq", "10.188.1.9", DUAL_IP.split("/")[0])
check("…and a packet to it is dropped", v["verdict"] == "drop", v)
check("the forward chain resets the block mark (one rule, masked to the low 16 bits)",
      any("meta mark & 0x0000ffff == 0x00009998" in t and "reject with tcp reset" in t for t in rules(K, "forward")), rules(K, "forward"))
v = fwd(K, (3 << 16) | 0x9998)
check("a packet carrying a block mark is refused with a reset", v["verdict"] == "reject", v)
check("a packet with a routing mark is not", fwd(K, 7001)["verdict"] == "accept")

SECTION[0] = "[2]"
print("\n[2] the payload for swg-sni")
B = N._SNI_BLOCKS["v"] or {}
srcs = dict((s, rl) for s, rl in B.get("src") or [])
check("written, with the mark", bool(B) and B.get("mark") == 0x9998, B)
check("only the sources that have a Block (wgq, not wg0)", set(srcs) == {WGQ}, sorted(srcs))
acts = [(r[2][0][0], r[1]) for r in srcs.get(WGQ, [])]
check("wgq's rules in chain order, the catch-all left out",
      acts == [(UNION, "block"), ("google", "exit"), ("custom_ipme", "block"), ("custom_dual", "block"), ("custom_row", "block")], acts)
check("each rule's mark names its entry: (index + 1) << 16 | 0x9998",
      [r[0] for r in srcs.get(WGQ, [])] == [((i + 1) << 16) | 0x9998 for i in range(5)], [hex(r[0]) for r in srcs.get(WGQ, [])])
check("the per-person rule carries its selection, and the selection its (device, address) pairs",
      (srcs.get(WGQ) or [[None] * 4] * 5)[4][3] == W1 and [list(x) for x in B.get("sel", {}).get(W1) or []] == [["wgq", "10.188.1.5"]], (srcs.get(WGQ), B.get("sel")))
check("block-only categories are not learned; a category a routing rule uses is",
      set(B.get("nolearn") or []) == {UNION, "custom_ipme", "custom_dual", "custom_row"}, B.get("nolearn"))

SECTION[0] = "[3]"
print("\n[3] the collateral, end to end (swg-noded's payload → swg-sni → the forward chain)")
c, nn = classifier(B)
m = c.on_packet(packet("10.188.1.9", GFE, "googleads.googleapis.com"))
check("the tracker's ClientHello from the filtered subnet gets the union's block mark", m == (1 << 16) | 0x9998, m)
check("…which the forward chain refuses", fwd(K, m or 0)["verdict"] == "reject", fwd(K, m or 0))
m2 = c.on_packet(packet("10.188.1.9", GFE, "youtubei.googleapis.com", sport=40001))
check("the ALLOWED name on the same address is not refused (the learn's reset at most — not a block)",
      m2 in (None, N.SNI_RESET_MARK), m2)
m2b = c.on_packet(packet("10.188.1.9", GFE, "youtubei.googleapis.com", sport=40011))
check("…and its next connection carries no mark at all, so the forward chain lets it through",
      m2b is None and fwd(K, 7001)["verdict"] == "accept", m2b)
m3 = c.on_packet(packet("10.188.1.9", GFE, "googleads.googleapis.com", sport=40002))
check("the tracker again: refused again (every connection, not only the first)", m3 == (1 << 16) | 0x9998, m3)
check("the tracker's address never enters a block set", not any(cat == UNION for cat, _ip in learned(c)), learned(c))
v = K.m.packet(T, "wgq", "10.188.1.9", GFE)
check("a new connection to that address for any name meets no drop in the chain", v["verdict"] != "drop", v)

SECTION[0] = "[4]"
print("\n[4] per interface")
m = c.on_packet(packet("10.8.0.9", GFE, "googleads.googleapis.com", sport=40003))
check("the same tracker from a subnet WITHOUT the filter is not refused", m in (None, N.SNI_RESET_MARK), m)

SECTION[0] = "[5]"
print("\n[5] order: an Exit above a Block keeps a name both claim at one rung; a Block above an Exit refuses it")
ORDER = [{"subnet": WGQ, "category": "google", "action": "exit", "via_iface": "swg_h", "table": 7001},
         {"subnet": WGQ, "category": "custom_same", "action": "block"},
         {"subnet": WGQ, "category": "custom_same2", "action": "block"},
         {"subnet": WGQ, "category": "google2", "action": "exit", "via_iface": "swg_h", "table": 7001},
         {"subnet": WGQ, "category": "all", "action": "direct"}]
DOMAINS.update({"custom_same": ["google.com"], "custom_same2": ["youtube.com"], "google2": ["youtube.com"]})
K2 = fresh()
for _ in range(2):
    npass(K2, ORDER)
c2, _nn = classifier(N._SNI_BLOCKS["v"])
m = c2.on_packet(packet("10.188.1.9", "142.250.1.1", "mail.google.com"))
check("`google.com` in the Exit above AND the Block below: the Exit keeps mail.google.com", m in (None, N.SNI_RESET_MARK), m)
m = c2.on_packet(packet("10.188.1.9", "142.250.1.2", "www.youtube.com"))
check("`youtube.com` in the Block above AND the Exit below: refused", m == (3 << 16) | 0x9998, m)

SECTION[0] = "[6]"
print("\n[6] per person")
m = c.on_packet(packet("10.188.1.5", "203.0.113.5", "row.example"), "wgq")
check("the chosen device is refused by its row's Block", m == (5 << 16) | 0x9998, m)
m = c.on_packet(packet("10.188.1.9", "203.0.113.5", "row.example", sport=40010), "wgq")
check("another device on the same interface is not", m in (None, N.SNI_RESET_MARK), m)
m = c.on_packet(packet("10.188.1.5", "203.0.113.5", "row.example", sport=40012), "wg0")
check("the chosen ADDRESS arriving on another device is not the person (device + address, as the chain binds it)", m in (None, N.SNI_RESET_MARK), m)
m = c.on_packet(packet("10.188.1.9", "203.0.113.5", "row.example", sport=40013), "wgq")
check("another device on the same interface is not", m in (None, N.SNI_RESET_MARK), m)

SECTION[0] = "[7]"
print("\n[7] IP rules in order: a static Exit above a name Block keeps its connection (post-queue chain `svb`)")
check("`svb` exists (google's static set sits above custom_ipme / custom_dual / custom_row)", "svb" in K.m.tables[T]["chains"],
      sorted(K.m.tables[T]["chains"]))
check("…hooked after the queue (prerouting, priority -149), before routing",
      (K.m.tables[T]["chains"].get("svb") or {}).get("hook") == ("prerouting", "-149"), K.m.tables[T]["chains"].get("svb"))
mk = (3 << 16) | 0x9998                                          # custom_ipme's mark
v = K.m.chain_walk(T, "svb", "wgq", "10.188.1.9", "172.217.9.9", mark=mk, ctmark=7001)
check("ip.me on an address inside google's STATIC set: the route comes back (the ct mark) and it is accepted",
      v["verdict"] == "accept" and v["mark"] == 7001, v)
v = K.m.chain_walk(T, "svb", "wgq", "10.188.1.9", "203.0.113.9", mark=mk, ctmark=0)
check("…outside it: the block mark stays", v["mark"] == mk and v["verdict"] == "accept", v)
check("…and the forward chain refuses that", fwd(K, v["mark"])["verdict"] == "reject")
v = K.m.chain_walk(T, "svb", "wgq", "10.188.1.9", "172.217.9.9", mark=(1 << 16) | 0x9998, ctmark=7001)
check("a content filter (first in the plan) has no exception", v["mark"] == (1 << 16) | 0x9998, v)
check("no `svb` exception for a Block that no Exit/Direct above holds statically", not any("custom_same2" in t for t in rules(K2, "svb")),
      rules(K2, "svb"))

SECTION[0] = "[8]"
print("\n[8] a node with no Block is what it always was")
PLAIN = [e for e in ENTRIES if e["action"] != "block"]
for label, queue, pin in (("Hybrid SNI", True, True), ("Kernel SNI", False, True), ("Force-DNS", False, False)):
    K3 = fresh()
    for _ in range(2):
        npass(K3, PLAIN, queue=queue, pin=pin)
    spec = [e for e in PLAIN if e["category"] != "all"]
    allr = [e for e in PLAIN if e["category"] == "all"]
    w4 = [(e["subnet"], e["category"], e.get("action", "exit"), e.get("table")) for e in spec + allr]
    rst = N.SNI_RESET_MARK if pin else 0
    want_sig = hashlib.sha1((("pin;" if pin else "") + ("q2;" if queue else "") + json.dumps(w4) + "|v6:" + "|rst:" + str(rst)
                             + ("|lttl:3600" if queue else "") + "|s9").encode()).hexdigest()[:16]
    have = open(os.path.join(N.GEO_DIR, ".smart-sig")).read().strip()
    check("%s: no payload, and the chain signs byte-for-byte as before" % label, N._SNI_BLOCKS["v"] is None and have == want_sig,
          (N._SNI_BLOCKS["v"], have, want_sig))
    check("%s: no reset rule for the block mark" % label, not any("0x00009998" in t for t in rules(K3, "forward")))
# THE UPGRADE, as a running node meets it: the table as the previous build left it (a Block's learned set dropped, the
# chain signed without the marker) — that build is this file with its two D1 lines put back — then a pass of this build.
_old_src = open(NODED, encoding="utf-8").read()
for a, b in (('            return [] if str(c).startswith("blku:host:") else [(_smart_setname(c), [])]',
              '            return [(_smart_setname(c), []), (_smart_learnsetname(c), [])]'),
             ('    if (queue and _nb(("block",))) or blk_rst:', '    if False:')):
    assert _old_src.count(a) == 1, "the previous build cannot be rebuilt from this file (anchor %r) — the upgrade check would measure nothing" % a[:60]
    _old_src = _old_src.replace(a, b, 1)
open(os.path.join(TMP, "previous-noded.py"), "w").write(_old_src)
OLDN = load(os.path.join(TMP, "previous-noded.py"), "swgnoded_prev")
K4 = fresh()
OLDN.GEO_DIR, OLDN.run = N.GEO_DIR, K4
for _ in range(2):
    OLDN._ensure_smart_nft([dict(e) for e in ENTRIES], sorted({e["category"] for e in ENTRIES}), {"changed": 0, "errors": []},
                           pin=True, queue=True, reset_mark=N.SNI_RESET_MARK, srcs=SRCS, name_cats=set(DOMAINS))
check("(the previous build's table drops a Block's learned set — the upgrade check starts from the defect)",
      any("@catl_blku" in t and "drop" in t for t in rules(K4, "prerouting")), rules(K4, "prerouting")[:6])
npass(K4, ENTRIES)
check("a Hybrid node WITH a Block re-signs on upgrade: the learned-set drop is gone after this build's first pass",
      not any("@catl_" in t and "drop" in t for t in rules(K4, "prerouting")), [t for t in rules(K4, "prerouting") if "catl_" in t and "drop" in t])

SECTION[0] = "[9]"
print("\n[9] the blocked counter")
N.run = K
K.m.tables[T]["chains"]["forward"]["rules"][0]["pk"] = 7
act = N._block_activity()
check("the forward reset is counted as blocked, under \"*\"", (act.get("*") or {}).get("blocked") == 7, act)

SECTION[0] = "[10]"
print("\n[10] a RELAYED leg: the relay's companion rule lets a connection refused by name go (nixos, 2026-09-28)")
# The relay takes a relayed connection's handshake; its `socket transparent` rule then re-marked every later packet and
# delivered it to the relay — the refused ClientHello included, so the Block did nothing on relayed legs.
_rn = N._relay_nft([{"subnet": WGQ, "port": 5876, "iface": "wgq", "peer": "p1", "mark": 7001, "iid": "wgq.p1"}])
_sock = [l.strip() for l in _rn.splitlines() if "socket transparent" in l]
from nft_guarded_model import SmartModel
RM = SmartModel()
RM.script("add table inet r\nadd chain inet r pre { type filter hook prerouting priority mangle + 10; policy accept; }\n" +
          "\n".join("add rule inet r pre " + l for l in _sock))
v = RM.chain_walk("r", "pre", "wgq", "10.188.1.9", GFE, mark=(3 << 16) | 0x9998, ctmark=7001, sock=True)
check("a refused ClientHello on a relayed connection is NOT taken by the relay (keeps its block mark, not 0x9c40)",
      v["mark"] == (3 << 16) | 0x9998, v)
check("…so the forward reset refuses it", fwd(K, v["mark"])["verdict"] == "reject", v)
v = RM.chain_walk("r", "pre", "wgq", "10.188.1.9", GFE, mark=N.SNI_RESET_MARK, ctmark=7001, sock=True)
check("…and a first learn's reset likewise (a relayed site's first connection is reset like any other)", v["mark"] == N.SNI_RESET_MARK, v)
v = RM.chain_walk("r", "pre", "wgq", "10.188.1.9", GFE, mark=7001, ctmark=7001, sock=True)
check("a live relayed connection's packet still reaches the relay (0x9c40)", v["mark"] == N.RELAY_MARK and v["verdict"] == "accept", v)
# …but not marking it is not enough: TCP early demux finds the relay's socket by the four-tuple and delivers the packet to
# INPUT whatever its mark (counted on nixos: input 2, forward 0). The relay's own input chain refuses it.
_inp = [l.strip() for l in _rn.split("chain inp {", 1)[1].split("}", 1)[0].splitlines()[2:] if l.strip()]
RI = K.m                                                  # the node's one kernel: swg_smart and swg_relay side by side
RI.script("add table inet %s\nadd chain inet %s inp { type filter hook input priority mangle + 10; policy accept; }\n" % (N.RELAY_TABLE, N.RELAY_TABLE) +
          "\n".join("add rule inet %s inp %s" % (N.RELAY_TABLE, l) for l in _inp))
walk = lambda **kw: RI.chain_walk(N.RELAY_TABLE, "inp", "wgq", "10.188.1.9", kw.pop("d", GFE), ctmark=7001, sock=True, **kw)
ib = walk(mark=(3 << 16) | 0x9998)
check("a refused ClientHello delivered to INPUT by early demux is reset there", ib["verdict"] == "reject", (ib, _inp))
ir = walk(mark=N.SNI_RESET_MARK)
check("…and a first learn's reset likewise", ir["verdict"] == "reject", ir)
check("a live relayed connection's packet passes the input chain", walk(mark=N.RELAY_MARK)["verdict"] == "accept")
check("the node's own services are never refused here (a refusal mark on a packet to a local address)",
      walk(d="10.188.1.1", mark=(3 << 16) | 0x9998, local=True, dport=8443)["verdict"] == "accept")
check("…and the self-dial port guard is unchanged", walk(d="10.188.1.1", local=True, dport=5876)["verdict"] == "drop")
_fpk = K.m.tables[T]["chains"]["forward"]["rules"][0].get("pk", 0)
act = N._block_activity()
check("the relayed refusal is counted as blocked with the forward ones (%d + 1), the learn reset is not" % _fpk,
      (act.get("*") or {}).get("blocked") == _fpk + 1, act)

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    red = [f for f in FAILS if f.split()[0] in sec.split()]
    print("plant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(red), sec)) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
