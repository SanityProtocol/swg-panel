#!/usr/bin/env python3
"""Self-test — Kernel SNI matches a SITE name and its subdomains, not any text that contains it (KSNI-HOSTNAMES-PLAN D4).

A `site` operand was one xt_string substring: `x.com` claimed `netflix.com`, `ya.ru` claimed `vanya.ru`, `ip.me`
claimed `whatismyip.me` — a wrong route for an exit, a leak for a Direct, another site refused for a Block. Now a name is
two patterns, built by `_xts_pats`: `|00 00 LL|<name>` (the SNI entry's own type byte and 2-byte length, RFC 6066 — the
whole name exactly) and `.<name>` (a subdomain). A `contains` operand stays a substring, by definition.

The chain is the real one (`_ensure_smart_xtstring`, iptables stubbed, the one-transaction restore read back through
tests/_iptrestore.py — quoting included), and each rendered pattern is matched against a REAL ClientHello the way xt_string
does it: the pattern's bytes anywhere in the packet.

  [1] `example.com`: matches example.com and www.example.com; NOT badexample.com, example.community, example.com-evil.net
  [2] short names: `x.com` does not match netflix.com / dropbox.com; `ya.ru` not vanya.ru; `ip.me` not whatismyip.me
  [3] a `contains` operand still matches as text (`*google*` → googleapis.com, notgoogle.example)
  [4] the rendered chain carries the hex pattern through the restore's quoting unchanged; a name past 125 characters is
      counted as too long (its hex form would pass xt_string's 128-byte ceiling), not installed
  [5] what is left, stated: a longer name carrying `.example.com` in its middle still matches

Run: python3 tests/ksni_site_exact_selftest.py   (0 = pass)
  --plant <x>:  text   a name is one substring again                 [1] [2]
                wronglen the exact pattern's length off by one        [1]
                nodot  the subdomain pattern dropped                  [1]
"""
import importlib.machinery, importlib.util, os, socket, struct, sys, tempfile

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
    "text": ("[1] [2]", '    return [["--hex-string", "|00%04x|%s" % (len(op), op)], ["--string", "." + op]]', '    return [["--string", op]]'),
    "wronglen": ("[1]", '    return [["--hex-string", "|00%04x|%s" % (len(op), op)], ["--string", "." + op]]',
                 '    return [["--hex-string", "|00%04x|%s" % (len(op) + 1, op)], ["--string", "." + op]]'),
    "nodot": ("[1]", '    return [["--hex-string", "|00%04x|%s" % (len(op), op)], ["--string", "." + op]]',
              '    return [["--hex-string", "|00%04x|%s" % (len(op), op)]]'),
}
TMP = tempfile.mkdtemp(prefix="ksni-site-")
path = NODED
if PLANT:
    sec, old, new = PLANTS[PLANT]
    src = open(NODED, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    path = os.path.join(TMP, "planted.py")
    open(path, "w").write(src.replace(old, new, 1))
_l = importlib.machinery.SourceFileLoader("swgnoded_site", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_site", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
N.GEO_DIR = TMP


class R:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


CALLS = []


def fake(cmd, **kw):
    CALLS.append(list(cmd))
    if cmd[:1] == ["iptables-restore"]:
        CALLS.extend(restore_to_calls(kw.get("input_text")))
    return R(1 if cmd[:1] == ["iptables"] and "-C" in cmd else 0)


N.run = fake
N._kernel_sni_ok = lambda: True


def hello(host):
    name = host.encode()
    sni = struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    ext = struct.pack(">HH", 0, len(sni)) + sni + struct.pack(">HH", 0x0a, 4) + b"\x00\x02\x00\x1d"
    body = b"\x03\x03" + b"\x22" * 32 + b"\x00" + struct.pack(">H", 2) + b"\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    tls = b"\x16\x03\x01" + struct.pack(">H", len(hs)) + hs
    tcp = struct.pack(">HHIIBBHHH", 40000, 443, 1, 1, 5 << 4, 0x18, 65535, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 40 + len(tls), 1, 0, 64, 6, 0, socket.inet_aton("10.9.0.5"), socket.inet_aton("1.2.3.4"))
    return ip + tcp + tls


def patbytes(args):
    """An xt_string rule's pattern, as the bytes it searches for (`--hex-string` decoded the way iptables decodes it)."""
    if "--string" in args:
        return args[args.index("--string") + 1].encode()
    h = args[args.index("--hex-string") + 1]
    out, i = b"", 0
    while i < len(h):
        if h[i] == "|":
            j = h.index("|", i + 1)
            out += bytes.fromhex(h[i + 1:j].replace(" ", "")); i = j + 1
        else:
            out += h[i].encode(); i += 1
    return out


def build(domains, contains=None):
    CALLS.clear()
    N._ensure_smart_xtstring([{"subnet": "10.9.0.0/24", "category": c, "table": 7001 + k} for k, c in enumerate(sorted(domains))],
                             domains, 0x9999, {"errors": [], "changed": 0}, ttl=3600, contains=contains or {})
    rules = [c[3:] for c in CALLS if c[:3] == ["iptables", "-t", "mangle"] and "-A" in c]
    return [r for r in rules if "--string" in r or "--hex-string" in r]


def matches(rules, host):
    pkt = hello(host)
    return any(patbytes(r) in pkt for r in rules)


SECTION[0] = "[1]"
print("\n[1] `example.com`")
R1 = build({"custom_e": ["example.com"]})
for h, want in (("example.com", True), ("www.example.com", True), ("a.b.example.com", True), ("badexample.com", False),
                ("example.community", False), ("example.com-evil.net", False)):
    check("%s %s" % (h, "matches" if want else "does not match"), matches(R1, h) == want)

SECTION[0] = "[2]"
print("\n[2] short names — the ones a substring over-matched most")
R2 = build({"custom_x": ["x.com"], "custom_y": ["ya.ru"], "custom_i": ["ip.me"]})
for h, want in (("x.com", True), ("api.x.com", True), ("netflix.com", False), ("dropbox.com", False), ("ya.ru", True),
                ("mail.ya.ru", True), ("vanya.ru", False), ("ip.me", True), ("whatismyip.me", False)):
    check("%s %s" % (h, "matches" if want else "does not match"), matches(R2, h) == want)

SECTION[0] = "[3]"
print("\n[3] a `contains` operand is still text")
R3 = build({"custom_g": []}, contains={"custom_g": ["google"]})
for h in ("googleapis.com", "notgoogle.example"):
    check("`*google*` matches %s" % h, matches(R3, h))
check("…with ONE pattern, the operand itself", len(R3) == 1 and R3[0][R3[0].index("--string") + 1] == "google", R3)

SECTION[0] = "[4]"
print("\n[4] the rendered chain")
hx = [r for r in R1 if "--hex-string" in r]
check("the exact pattern crosses the restore's quoting unchanged", hx and hx[0][hx[0].index("--hex-string") + 1] == "|00000b|example.com", hx)
long_name = ("a" * 61 + ".") * 2 + "com"                          # 127: 125 < len ≤ 128
N._SMART_MODE.pop("xts_cap", None)
R4 = build({"custom_l": [long_name, "ok.example"]})
check("a name past 125 characters is not installed", not any(long_name in " ".join(r) for r in R4), R4[:1])
check("…and is counted as too long (reported, not silent)", (N._SMART_MODE.get("xts_cap") or {}).get("long") == 1, N._SMART_MODE.get("xts_cap"))

SECTION[0] = "[5]"
print("\n[5] what is left, stated")
check("a longer name carrying `.example.com` in its middle still matches (the end cannot be anchored)",
      matches(R1, "a.example.com.evil.net"))

print()
if PLANT:
    red = [f for f in FAILS if f.split()[0] in PLANTS[PLANT][0].split()]
    print("plant %s: %s" % (PLANT, "RED as it must be (%d)" % len(red) if red else "NOT CAUGHT — the gate is blind to it"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
