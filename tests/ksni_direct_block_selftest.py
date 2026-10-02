#!/usr/bin/env python3
"""Self-test — Kernel SNI runs Direct and Block by SITE NAME (docs/KSNI-HOSTNAMES-PLAN.md D3).

Until 1.8.8 Kernel SNI lowered a site name only for a rule that leaves by an exit; a Direct or a Block by name did nothing
(qualification F19, measured on msk-main: `ip.me → Block` let the site through, `api.seeip.org → Direct` above a catch-all
exit left by the exit). Now:

  · a DIRECT learns its names' addresses like an exit (Phase 2) and routes a known one to the main table — both marks set
    to SNI_DIRECT_MARK, which no `ip rule` matches and which counts as categorised;
  · a BLOCK refuses the ClientHello of each of its names, every connection, with SNI_BLOCK_MARK (reset by the one nft
    forward rule), learns nothing, and never touches another name on the address — the invariant of the whole work;
  · ORDER is the engine's own: first match by name. A Block sits BEFORE Phase 1 (a learned address says nothing about
    the name), and its tail lets through a name that a rule ABOVE it claims.

The chain is the real one (`_ensure_smart_xtstring` through a model of iptables + ipset, the restore read back through
tests/_iptrestore.py) and every connection is walked through it with REAL ClientHello bytes: `-m string` / `--hex-string`
search the packet, `-j` jumps and returns, `-g` goes, connbytes reads the packet count or the reply's average packet.

  [1] Direct by name: the first connection learns (and is reset); the next one's SYN leaves unrouted-by-us (SNI_DIRECT_MARK),
      over an IP-tier catch-all exit's mark
  [2] Block by name: refused every time, the first included; nothing learned; another name on the same address passes
  [3] ORDER — an exit above a Direct keeps the name; a Direct above an exit keeps it; a Block below an exit that claims the
      name lets it through; a Block above the exit refuses it; a Block below an exit that LEARNED the address for another
      name still refuses its own name
  [4] per person: a Block row refuses its chosen device only; an exit row above it for Alice keeps her connection
  [5] only the ClientHello: a SYN and a packet after the server answered are not scanned by a Block
  [6] arrivals: an arrival Block by name refuses for the arrivals' source; an arrival Direct routes unmarked
  [7] the dispatcher hands Kernel SNI its Direct and Block rules and asks nft for the reset when a Block is lowered
  [8] a node with only exits builds no Block chain, no mark return
  [9] the Direct mark: not a table, not zero (the uncategorised count skips it), even, not another flag

Run: python3 tests/ksni_direct_block_selftest.py   (0 = pass)
  --plant <x>:  blockafter  Blocks after Phase 1 (a learned address hides a blocked name)      [3]
                notail      the tail does not re-check the names above                      [3]
                blocklearn  a Block gets a learn set                                         [2]
                nowho       a Block row refuses everyone on its interface                    [4]
                anypkt      a Block's chain is entered by a SYN (no payload gate)            [5]
                anydata     a Block's chain is entered after the server answered              [5]
                norst       the dispatcher does not ask for the reset                        [7]
                directzero  a Direct marks 0 (counted as uncategorised as well as its category) [9]
"""
import importlib.machinery, importlib.util, ipaddress, os, socket, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
sys.path.insert(0, HERE)
from _iptrestore import restore_to_calls  # noqa: E402

PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


PLANTS = {
    "blockafter": ("[3]", """    for S in _bysrc:
        _blocks(_bysrc[S], ["-s", S])
    _blocks(arr_ents, ["-m", "set", "--match-set", _XTS_ARR, "src,src"], arr=True)
    for e in rents:                                            # Phase 1: route KNOWN learned IPs to their exit, then RETURN""",
                   """    _late = True
    for e in rents:                                            # Phase 1: route KNOWN learned IPs to their exit, then RETURN"""),
    "notail": ("[3]", """            for x in ents[:i]:                                 # a name a rule above claims (for this device) is not refused""",
               """            for x in []:                                 # a name a rule above claims (for this device) is not refused"""),
    "blocklearn": ("[2]", """    want_cats = sorted({e["category"] for e in rents + arr_r})""", """    want_cats = sorted({e["category"] for e in entries + arr_ents})"""),
    "nowho": ("[4]", """            rules.append(["-A", CHAIN, *sel, *([] if arr else _who(e)), "-m", "connbytes", "--connbytes", "0:%d" % _XTS_SRVANS,""",
              """            rules.append(["-A", CHAIN, *sel, "-m", "connbytes", "--connbytes", "0:%d" % _XTS_SRVANS,"""),
    "anypkt": ("[5]", """                          "--connbytes-dir", "reply", "--connbytes-mode", "avgpkt", "-m", "length", "--length",
                          "%d:65535" % (_XTS_NOPAYLOAD + 1), "-j", bc])""",
               """                          "--connbytes-dir", "reply", "--connbytes-mode", "avgpkt", "-m", "length", "--length",
                          "0:65535", "-j", bc])"""),
    "anydata": ("[5]", """            rules.append(["-A", CHAIN, *sel, *([] if arr else _who(e)), "-m", "connbytes", "--connbytes", "0:%d" % _XTS_SRVANS,""",
                """            rules.append(["-A", CHAIN, *sel, *([] if arr else _who(e)), "-m", "connbytes", "--connbytes", "0:99999","""),
    "norst": ("[7]", """                                    name_cats=_name_cats, spare_dns=(host_engine == "dns"), blk_reject=_ks_blk,""",
              """                                    name_cats=_name_cats, spare_dns=(host_engine == "dns"),"""),
    "directzero": ("[9]", """SNI_DIRECT_MARK = 0x9996 """, """SNI_DIRECT_MARK = 0x0 """),
}
TMP = tempfile.mkdtemp(prefix="ksni-db-")
path = NODED
if PLANT:
    sec, old, new = PLANTS[PLANT]
    src = open(NODED, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    src = src.replace(old, new, 1)
    if PLANT == "blockafter":                                   # …and the Blocks go after Phase 2 instead
        a = "    rules, subs = _xts_split(rules, CHAIN)                     # one chain per source — see _xts_split"
        src = src.replace(a, "    for S in _bysrc:\n        _blocks(_bysrc[S], [\"-s\", S])\n" + a, 1)
    path = os.path.join(TMP, "planted.py")
    open(path, "w").write(src)
os.environ["SWG_NODED_STATE"] = TMP
_l = importlib.machinery.SourceFileLoader("swgnoded_db", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_db", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass


# ── a model of iptables -t mangle + ipset, enough for SWGK ───────────────────────────────────────────────────────────────
class CP:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class Box:
    def __init__(self):
        self.sets, self.chains, self.hooked, self.entered = {}, {}, False, {}

    def __call__(self, args, input_text=None, timeout=20, **kw):
        a = [str(x) for x in args]
        if a[0] == "iptables-restore":
            for c in restore_to_calls(input_text):
                self.ipt(c[1:])
            return CP()
        if a[0] == "iptables":
            return self.ipt(a[1:])
        if a[0] == "ipset":
            a = [x for x in a[1:] if x != "-exist"]
            if a[0] == "create":
                self.sets.setdefault(a[1], {"type": a[2], "m": set()})
            elif a[0] == "restore":
                for ln in (input_text or "").splitlines():
                    p = ln.split()
                    if p and p[0] == "create":
                        self.sets.setdefault(p[1], {"type": p[2], "m": set()})
                    elif p and p[0] == "add":
                        ip, _, dev = p[2].partition(",")
                        self.sets.setdefault(p[1], {"type": "hash:net,iface", "m": set()})["m"].add((ip, dev))
                    elif p and p[0] == "swap":
                        self.sets[p[1]], self.sets[p[2]] = self.sets.get(p[2]), self.sets.get(p[1])
                    elif p and p[0] == "destroy":
                        self.sets.pop(p[1], None)
            elif a[0] == "list":
                return CP(0, "".join("Name: %s\nHeader: family inet timeout 3600\nNumber of entries: %d\n" % (n, len(s["m"]))
                                     for n, s in self.sets.items()))
            elif a[0] == "destroy":
                self.sets.pop(a[1], None)
            return CP()
        return CP()

    def ipt(self, a):
        while a and a[0] == "-w":
            a = a[2:]
        if a[:2] != ["-t", "mangle"]:
            return CP()
        op, ch, rest = a[2], (a[3] if len(a) > 3 else ""), a[4:]
        if ch == "PREROUTING":
            if op == "-C":
                return CP(0 if self.hooked else 1)
            if op == "-A":
                self.hooked = True
            if op == "-D":
                self.hooked = False
            return CP()
        if op == "-N":
            self.chains.setdefault(ch, [])
        elif op == "-F":
            self.chains[ch] = []
        elif op == "-X":
            self.chains.pop(ch, None)
        elif op == "-A":
            self.chains.setdefault(ch, []).append(rest)
        elif op == "-S":
            if not ch:
                return CP(0, "".join("-N %s\n" % c for c in self.chains))
            return CP(0, "".join("-A %s %s\n" % (ch, " ".join(r)) for r in self.chains.get(ch, [])))
        return CP()

    # a packet through SWGK
    def _pat(self, r, i):
        kind, v = r[i], r[i + 1]
        if kind == "--string":
            return v.encode()
        out, j = b"", 0
        while j < len(v):
            if v[j] == "|":
                k = v.index("|", j + 1)
                out += bytes.fromhex(v[j + 1:k]); j = k + 1
            else:
                out += v[j].encode(); j += 1
        return out

    def _inset(self, name, flags, pkt):
        s = self.sets.get(name) or {"m": set()}
        if s.get("type") == "hash:ip":
            return any(pkt["dst"] == m[0] for m in s["m"])
        return any(ipaddress.ip_address(pkt["src"]) in ipaddress.ip_network(ip, strict=False) and d == pkt["iif"] for ip, d in s["m"])

    def walk(self, pkt, ct, chain="SWGK"):
        """→ "return" | None (fell off the end). Returns to the caller of a GOTO'd chain on RETURN, as iptables does."""
        self.entered[chain] = self.entered.get(chain, 0) + 1          # what a packet costs: the chains it walks
        for r in self.chains.get(chain, []):
            i, ok, tgt, go = 0, True, None, False
            while i < len(r) and ok:
                t = r[i]
                if t == "-s":
                    ok = ipaddress.ip_address(pkt["src"]) in ipaddress.ip_network(r[i + 1]); i += 2
                elif t == "!" and r[i + 1] == "-i":
                    ok = pkt["iif"] != r[i + 2]; i += 3
                elif t in ("-p", "--dport"):
                    i += 2
                elif t == "-m" and r[i + 1] == "connbytes":
                    lo, hi = r[i + 3].split(":")
                    mode = r[r.index("--connbytes-mode", i) + 1]
                    v = pkt["n"] if mode == "packets" else pkt["ravg"]
                    ok = int(lo or 0) <= v <= (int(hi) if hi else 1 << 62); i += 8
                elif t == "-m" and r[i + 1] == "string":
                    ok = self._pat(r, i + 4) in pkt["payload"]; i += 6
                elif t == "-m" and r[i + 1] == "length":
                    lo, hi = r[i + 3].split(":")
                    ok = int(lo or 0) <= pkt["len"] <= (int(hi) if hi else 1 << 62); i += 4
                elif t == "-m" and r[i + 1] == "set":
                    ok = self._inset(r[i + 3], r[i + 4], pkt); i += 5
                elif t == "-m" and r[i + 1] == "mark":
                    v, _, m = r[i + 3].partition("/")
                    ok = (pkt["mark"] & int(m or "0xffffffff", 0)) == int(v, 0); i += 4
                elif t in ("-j", "-g"):
                    tgt, go = r[i + 1:], t == "-g"; break
                else:
                    raise AssertionError("model cannot read %r in %r" % (t, r))
            if not ok:
                continue
            if tgt[0] in self.chains:
                v = self.walk(pkt, ct, tgt[0])
                if go:
                    return "return"                           # a goto: its end (or RETURN) returns to OUR caller
                continue
            if tgt[0] == "MARK":
                pkt["mark"] = int(tgt[2], 0)
            elif tgt[0] == "CONNMARK":
                ct["mark"] = pkt["mark"] if tgt[1] == "--save-mark" else int(tgt[2], 0)
            elif tgt[0] == "SET":
                self.sets.setdefault(tgt[2], {"type": "hash:ip", "m": set()})["m"].add((pkt["dst"], None))
            elif tgt[0] == "RETURN":
                return "return"
            else:
                raise AssertionError("model cannot run target %r" % tgt)
        return None

    def conn(self, src, dst, host, iif="wg0", premark=0):
        """One TLS connection: the SYN (whatever the nft chain's IP tier marked it: `premark`), then the ClientHello, then a
        data packet after the server answered. → {syn, ch, data, ct, blocked, reset}."""
        ct, out = {"mark": premark}, {}
        for k, n, ravg, payload, ln in (("syn", 1, 0, b"", 60), ("ch", 3, 60, hello(host), 517),
                                        ("data", 5, 1400, b"\x17\x03\x03" + hello(host), 600)):
            pkt = {"src": src, "iif": iif, "dst": dst, "n": n, "ravg": ravg, "payload": payload, "mark": ct["mark"], "len": ln}
            self.walk(pkt, ct)
            out[k] = pkt["mark"]
        out["ct"] = ct["mark"]
        out["blocked"] = (out["ch"] & 0xffff) == N.SNI_BLOCK_MARK
        out["reset"] = out["ch"] == N.SNI_RESET_MARK
        return out

    def learned(self, cat):
        return {m[0] for m in (self.sets.get(N._xts_setname(cat)) or {"m": set()})["m"]}


def hello(host):
    name = host.encode()
    sni = struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    ext = struct.pack(">HH", 0, len(sni)) + sni + struct.pack(">HH", 0x0a, 4) + b"\x00\x02\x00\x1d"
    body = b"\x03\x03" + b"\x33" * 32 + b"\x00" + struct.pack(">H", 2) + b"\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs


N._kernel_sni_ok = lambda: True
S = "10.9.0.0/24"
A, B, C = "10.9.0.5", "10.9.0.6", "10.9.0.7"
W1 = "1f2e3d4c5b6a"
DOMS = {"custom_d": ["api.seeip.org"], "custom_x": ["seeip.org"], "custom_b": ["ip.me"], "custom_t": ["googleads.googleapis.com"],
        "custom_g": ["googleapis.com"], "custom_r": ["row.example"], "custom_ar": ["alice.row.example"]}
IPSEE, IPME, GFE = "23.128.64.156", "5.2.67.226", "172.217.114.4"


def build(entries, arrivals=None, srcs=None):
    B = Box()
    N.run = B
    N.GEO_DIR = tempfile.mkdtemp(dir=TMP)
    N._XTS_SRC.clear()
    res = {"errors": [], "changed": 0}
    N._ensure_smart_xtstring([dict(e) for e in entries], DOMS, N.SNI_RESET_MARK, res, ttl=3600, contains={},
                             srcs=srcs, arrivals=arrivals)
    return B, res


E = lambda c, a, **k: dict({"subnet": S, "category": c, "action": a}, **k)
X = lambda c, T=7001, **k: E(c, "exit", via_iface="swg_h", table=T, **k)

SECTION[0] = "[1]"
print("\n[1] Direct by name")
B, r = build([E("custom_d", "direct")])
check("built without an error", not r["errors"], r["errors"])
c1 = B.conn(A, IPSEE, "api.seeip.org", premark=7000)
check("the first connection learns the address and is reset (the engine's first hit)", IPSEE in B.learned("custom_d") and c1["reset"], c1)
c2 = B.conn(A, IPSEE, "api.seeip.org", premark=7000)
check("the next one's SYN leaves by the main table: SNI_DIRECT_MARK over the catch-all exit's 7000",
      c2["syn"] == N.SNI_DIRECT_MARK and c2["ct"] == N.SNI_DIRECT_MARK, c2)

SECTION[0] = "[2]"
print("\n[2] Block by name")
B, r = build([E("custom_b", "block"), E("custom_t", "block")])
c1, c2 = B.conn(A, IPME, "ip.me"), B.conn(A, IPME, "ip.me")
check("refused on the first connection, and on the next", c1["blocked"] and c2["blocked"], (c1, c2))
check("nothing learned — a Block has no set", "swgk_custom_b" not in B.sets and not B.learned("custom_b"), sorted(B.sets))
c3 = B.conn(A, GFE, "googleads.googleapis.com")
c4 = B.conn(A, GFE, "youtubei.googleapis.com")
check("the tracker on a shared front end is refused …", c3["blocked"], c3)
check("…and the allowed name on the SAME address passes, unmarked", not c4["blocked"] and c4["ch"] == 0, c4)
c5 = B.conn(A, IPME, "whatismyip.me")
check("a name that merely CONTAINS the blocked one passes (D4)", not c5["blocked"], c5)

SECTION[0] = "[3]"
print("\n[3] order — first match by name")
B, _ = build([X("custom_x"), E("custom_d", "direct")])
B.conn(A, IPSEE, "api.seeip.org")
c = B.conn(A, IPSEE, "api.seeip.org")
check("an exit above a Direct for the same name keeps it (7001)", c["syn"] == 7001, c)
B, _ = build([E("custom_d", "direct"), X("custom_x")])
B.conn(A, IPSEE, "api.seeip.org")
c = B.conn(A, IPSEE, "api.seeip.org", premark=7000)
check("a Direct above the exit keeps it (SNI_DIRECT_MARK)", c["syn"] == N.SNI_DIRECT_MARK, c)
B, _ = build([X("custom_x"), E("custom_d", "block")])
c1, c2 = B.conn(A, IPSEE, "api.seeip.org"), B.conn(A, IPSEE, "api.seeip.org")
check("a Block below an exit that claims the name lets it through — the first connection …", not c1["blocked"], c1)
check("…and once the exit learned it (7001)", not c2["blocked"] and c2["syn"] == 7001, c2)
B, _ = build([E("custom_d", "block"), X("custom_x")])
c1, c2 = B.conn(A, IPSEE, "api.seeip.org"), B.conn(A, IPSEE, "api.seeip.org")
check("a Block above the exit refuses it, every time", c1["blocked"] and c2["blocked"], (c1, c2))
B, _ = build([X("custom_g"), E("custom_t", "block")])
B.conn(A, GFE, "youtubei.googleapis.com"); B.conn(A, GFE, "youtubei.googleapis.com")    # the exit learns the front end
check("(the exit learned the front end for another name)", GFE in B.learned("custom_g"))
c = B.conn(A, GFE, "googleads.googleapis.com")
check("…a Block below it still refuses ITS name? no — the exit above claims `googleapis.com`, the tracker's parent (first match)",
      not c["blocked"], c)
B, _ = build([X("custom_x"), E("custom_t", "block")])
B.conn(A, GFE, "seeip.org")                                     # the exit learned the front end for a name of its own
c = B.conn(A, GFE, "googleads.googleapis.com")
check("a Block below an exit that learned the ADDRESS for another name still refuses its own name", c["blocked"], c)

SECTION[0] = "[4]"
print("\n[4] per person")
srcs = {W1: [["wg0", A + "/32"]]}
B, r = build([E("custom_r", "block", src=W1)], srcs=srcs)
check("a Block row refuses its chosen device …", B.conn(A, "198.51.100.9", "row.example")["blocked"])
check("…and not another device on the interface", not B.conn(B_ := "10.9.0.6", "198.51.100.9", "row.example")["blocked"])
check("…nor the chosen ADDRESS arriving on another device", not B.conn(A, "198.51.100.9", "row.example", iif="wg1")["blocked"])
B, r = build([X("custom_ar", src=W1), E("custom_r", "block")], srcs=srcs)
check("an exit row above for Alice keeps her name through the Block below", not B.conn(A, "198.51.100.9", "alice.row.example")["blocked"])
check("…while Bob is refused", B.conn("10.9.0.6", "198.51.100.9", "alice.row.example")["blocked"])

SECTION[0] = "[5]"
print("\n[5] only the ClientHello")
B, _ = build([E("custom_b", "block")])
c = B.conn(A, IPME, "ip.me")
check("the SYN carries no block mark", (c["syn"] & 0xffff) != N.SNI_BLOCK_MARK, c)
check("a packet after the server answered, carrying the name, is not scanned by the Block", (c["data"] & 0xffff) != N.SNI_BLOCK_MARK
      or c["data"] == c["ch"], c)
# …and what they COST: a Block's patterns are searched for the ClientHello alone — a SYN, an ACK, a packet after the
# server answered never enter its chain (one rule each, no search)
for label, n, ravg, ln, payload in (("a SYN", 1, 0, 60, b""), ("a packet after the server answered", 5, 1400, 600, hello("ip.me"))):
    B2, _ = build([E("custom_b", "block")])
    pkt = {"src": A, "iif": "wg0", "dst": IPME, "n": n, "ravg": ravg, "payload": payload, "mark": 0, "len": ln}
    B2.walk(pkt, {"mark": 0})
    check("%s never enters the Block's chain (no search), and carries no mark" % label,
          not any(k.startswith("SWGKB_") for k in B2.entered) and pkt["mark"] == 0, (B2.entered, pkt["mark"]))

SECTION[0] = "[6]"
print("\n[6] arrivals")
arr = {"entries": [{"category": "custom_b", "action": "block"}, {"category": "custom_d", "action": "direct"}],
       "pairs": [("10.50.0.0/24", "swg_leg")]}
B, r = build([], arrivals=arr)
check("built", not r["errors"], r["errors"])
check("an arrival's ClientHello to a blocked name is refused", B.conn("10.50.0.9", IPME, "ip.me", iif="swg_leg")["blocked"])
B.conn("10.50.0.9", IPSEE, "api.seeip.org", iif="swg_leg")
c = B.conn("10.50.0.9", IPSEE, "api.seeip.org", iif="swg_leg")
check("an arrival Direct by name routes unmarked-by-an-exit (SNI_DIRECT_MARK)", c["syn"] == N.SNI_DIRECT_MARK, c)

SECTION[0] = "[7]"
print("\n[7] the dispatcher")
_seen = {}
_real_nft = N._ensure_smart_nft
N._ensure_smart_nft = lambda *a, **k: (_seen.setdefault("nft", []).append(k), {})[1]
N._ensure_smart_xtstring = lambda host_entries, *a, **k: (_seen.setdefault("xt", []).append([dict(e) for e in host_entries]), [])[1]
for stub in ("_smart_geo_refresh", "_smart_load_cidrs", "_panel_list_refresh", "_ensure_doh_block", "_ensure_mech_block",
             "_ensure_torrent_sig", "_ensure_sni_router", "reconcile_catk_chain", "_dnsmasq_refill", "_ensure_smart_dnsmasq"):
    setattr(N, stub, lambda *a, **k: None)
N._smart_domain_refresh = lambda cats, res: ({}, {})
N._ksni_src_ok = lambda: True
N.run = lambda args, **kw: CP()
for ents, want in (([E("custom_b", "block"), E("custom_d", "direct"), X("custom_x"), E("all", "direct")], True),
                   ([X("custom_x"), E("all", "direct")], False)):
    _seen.clear()
    smart = {"entries": ents, "categories": sorted({e["category"] for e in ents}), "mode": "sni_kernel", "domains": DOMS}
    try:
        N.reconcile_cascade({"interfaces": {}}, {}, smart, "")
    except Exception as e:
        _seen["err"] = str(e)
    k = (_seen.get("nft") or [{}])[-1]
    check("%s: nft is asked for the block reset = %s" % ("with a Block" if want else "exits only", want), k.get("blk_reject") is want,
          (_seen.get("err"), k.get("blk_reject")))
    if want:
        xt = (_seen.get("xt") or [[]])[-1]
        check("…and Kernel SNI is handed the Block, the Direct and the exit — never the catch-all",
              sorted((e["category"], e["action"]) for e in xt) == [("custom_b", "block"), ("custom_d", "direct"), ("custom_x", "exit")], xt)
N._ensure_smart_nft = _real_nft

SECTION[0] = "[8]"
print("\n[8] exits only: nothing new")
B, _ = build([X("custom_x")])
check("no Block chain, no mark return", not any(c.startswith("SWGKB_") for c in B.chains)
      and not any("--mark" in r and "0x9998/0xffff" in r for rs in B.chains.values() for r in rs), sorted(B.chains))

SECTION[0] = "[9]"
print("\n[9] the Direct mark")
m = N.SNI_DIRECT_MARK
check("not zero — the uncategorised count (`ct mark != 0`) skips it, so a Direct-by-name flow is counted once", m != 0, m)
check("not a table of the exit band, and no other flag", not (N.SWG_RT_BASE <= m <= N.SWG_RT_MAX)
      and m not in (N.SNI_RESET_MARK, N.SNI_BLOCK_MARK, N.RELAY_MARK, N.P2P_BIT), hex(m))
check("even (no `fwmark 0x1/0x1` rule of another tool takes it)", m % 2 == 0, hex(m))

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
