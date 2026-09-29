#!/usr/bin/env python3
"""Self-test — a conf rebuilt from a live AmneziaWG device carries no line that only `showconf` prints
(docs/AWG3-PLAN.md §7.6).

A 3.x kernel's `awg showconf` prints eight AWG3 interface keys at 0/off and `AdvancedSecurity = off` on every peer.
swg-noded `_reconstruct_conf` (panel onboard, self-heal of a lost conf, a create that finds the device already there)
and install-node.sh `reconstruct_live_orphans` (a docker→bare convert) wrote that text into the conf verbatim.
MEASURED on swgt's live awg2 text through the shipped `_reconstruct_conf` (2026-09-18): the conf came up on the 3.1
kernel only — amneziawg-go 3.1 (our pinned fallback included), 3.0 and 2.0 refused it with EINVAL, and 2.0 tools refused
`ContentPaddingAddition=0` at parse. So the day the module is lost, the fallback cannot bring that interface up.

  [1] noded, a 2.0 interface on a 3.1 kernel: no AdvancedSecurity, none of the eight AWG3 keys, and nothing else
      changed — every 2.0 key verbatim (I1 with its spaces), every peer, the learned-Endpoint rule as before.
  [2] ⚠️ CONTROL — noded, a real 3.1 interface being adopted: HeaderProtectionKey, RandomTrailers = on, the padding and
      the timings are KEPT; only DisableCookies = off and AdvancedSecurity go.
  [3] install-node.sh reconstruct_live_orphans, run for real (awg/ip stubbed, /etc remapped): the same two verdicts.
  [4] the two rebuilders drop exactly the same lines.

The fixtures are real `awg showconf` output of a 3.1 kernel (amneziawg 3.1.20260906, tools v3.1.20260812), captured
2026-09-18 from throwaway devices whose keys were generated for them and are used nowhere. Whether the rebuilt text is
ACCEPTED by each datapath is the root rig's job: .campaign/rigs/awg3-g1-replay.sh.

Run: python3 tests/reconstruct_showconf_selftest.py              (0 = pass)
     --perturb       noded keeps the AdvancedSecurity lines           → RED
     --perturb-sh    install-node.sh keeps the AdvancedSecurity lines → RED
     --perturb-keep  noded drops the AWG3 keys whatever their value   → RED (the control)
"""
import importlib.machinery, importlib.util, os, re, shutil, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
INSTALL = os.path.join(ROOT, "install-node.sh")
P_AS, P_SH, P_KEEP = ("--perturb" in sys.argv, "--perturb-sh" in sys.argv, "--perturb-keep" in sys.argv)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

IF20 = """[Interface]
ListenPort = 443
PrivateKey = KDdlMM3KZQD7DBVo+QzZkM6zrmHv35COGoO386+rmWQ=
Jc = 4
Jmin = 40
Jmax = 70
S1 = 28
S2 = 94
S3 = 88
S4 = 33
H1 = 103509605-103509620
H2 = 1694692368-1694692383
H3 = 2553282719-2553282734
H4 = 3170237912-3170237927
I1 = <b 0xc000000001><r 64><t>
I2 = <r 24><t>
I3 = <r 32>
I4 = <b 0xc000000001><r 32><t>
I5 = <t><r 48>
ContentPaddingAddition = 0
RekeyAfterTime = 0
RekeyTimeout = 0
RejectAfterTime = 0
KeepaliveTimeout = 0
MaxHandshakeAttempts = 0
RandomTrailers = off
DisableCookies = off
"""
IF31 = """[Interface]
ListenPort = 443
PrivateKey = yNARsYutuyBHUIfbFfl2V0gnACFnekogFcs3SEfRBVM=
Jc = 4
Jmin = 40
Jmax = 70
S1 = 28
S2 = 94
S3 = 88
S4 = 33
H1 = 103509605-103509620
H2 = 1694692368-1694692383
H3 = 2553282719-2553282734
H4 = 3170237912-3170237927
I1 = <b 0xc000000001><r 64><t>
I2 = <r 24><t>
I3 = <r 32>
I4 = <b 0xc000000001><r 32><t>
I5 = <t><r 48>
HeaderProtectionKey = KM1/yq/3v+3TVnXs/DwuCG9R6AIeyl065b676XZRm3A=
ContentPaddingAddition = 10-100
RekeyAfterTime = 100-120
RekeyTimeout = 3-7
RejectAfterTime = 150-180
KeepaliveTimeout = 5-15
MaxHandshakeAttempts = 15-20
RandomTrailers = on
DisableCookies = off
"""
# Both captures carried these three peers byte for byte: a client whose Endpoint showconf LEARNED, a dial-out (mesh)
# peer whose Endpoint is config (it has a keepalive), and one that never connected.
PEERS = """
[Peer]
PublicKey = tcOQ4pQRZAog7xWejZ25EUUxk+1yFvjeMCIwHQRHoxg=
PresharedKey = MJEpCkTC02SE+depc1Dv0kPaJH3Pg7A/BbXYBHXAqEo=
AdvancedSecurity = off
AllowedIPs = 10.9.0.2/32, 192.168.2.0/24
Endpoint = 198.51.100.7:43286

[Peer]
PublicKey = XquKfcWJAZ7bX15dMo/ja5G2T0je8stMfyBuytKYaHU=
AdvancedSecurity = off
AllowedIPs = 10.255.0.1/32
Endpoint = 203.0.113.9:9999
PersistentKeepalive = 25

[Peer]
PublicKey = cISB1E2rrx6V4UlS8++MEAQwvhaLNc9AXDuGM7ywWz4=
AdvancedSecurity = off
AllowedIPs = 10.9.0.3/32
"""
V20, V31 = IF20 + PEERS, IF31 + PEERS
AWG3 = ("ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout", "RejectAfterTime", "KeepaliveTimeout",
        "MaxHandshakeAttempts", "RandomTrailers", "DisableCookies")
IP_ADDR = "7: g1f    inet 10.9.0.1/24 scope global g1f\\       valid_lft forever preferred_lft forever\n"
IP_LINK = "7: g1f: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1280 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000\n"
LEARNED, DIALOUT = "Endpoint = 198.51.100.7:43286", "Endpoint = 203.0.113.9:9999"
T = tempfile.mkdtemp(prefix="g1-")

# ── noded ───────────────────────────────────────────────────────────────────────────────────────────────────────────
src = open(NODED).read()
A_AS = r'r"(?i)^\s*(?:AdvancedSecurity\s*=.*|(?:ContentPaddingAddition'
A_KEEP = r'r"\s*=\s*(?:0|off)\s*)$")'
# ⚠️ ASSERT THE ANCHORS. A perturbation that matches nothing leaves a clean pass behind.
for a in (A_AS,) * P_AS + (A_KEEP,) * P_KEEP:
    if a not in src:
        print("  FAIL anchor missing in swg-noded: " + a + "\n\n1 FAIL"); sys.exit(1)
if P_AS:
    src = src.replace(A_AS, r'r"(?i)^\s*(?:(?:ContentPaddingAddition')
if P_KEEP:
    src = src.replace(A_KEEP, r'r"\s*=.*)$")')
mod_path = os.path.join(T, "swg-noded.py")
open(mod_path, "w").write(src)
_l = importlib.machinery.SourceFileLoader("swgnoded_g1", mod_path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_g1", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
if not hasattr(N, "_reconstruct_conf"):
    print("  FAIL swg-noded has no _reconstruct_conf\n\n1 FAIL"); sys.exit(1)

def noded_rebuild(showconf, strip=True):
    def fake_run(args, input_text=None, timeout=20):
        a = list(args)
        s = showconf if "showconf" in a else IP_ADDR if a[:2] == ["ip", "-4"] else IP_LINK if a[:3] == ["ip", "-o", "link"] else None
        if s is None:
            raise RuntimeError("unexpected run: %r" % (a,))
        return types.SimpleNamespace(stdout=s, stderr="", returncode=0)
    d = tempfile.mkdtemp(dir=T)
    N.run, N.AWG_CONF_DIRS, N._awg_conf_dirs = fake_run, (d,), (lambda: [d])
    keep = getattr(N, "_strip_showconf_only", None)        # absent on the tree before the fix
    if keep and not strip:            # the shipped behaviour, as the reference for "nothing ELSE changed"
        N._strip_showconf_only = lambda body: body
    try:
        p = N._reconstruct_conf("g1f", ["awg"])
    finally:
        if keep:
            N._strip_showconf_only = keep
    return open(p).read() if p else ""

# ── install-node.sh ─────────────────────────────────────────────────────────────────────────────────────────────────
inst = open(INSTALL).read()
def grab(name):
    i = inst.index("\n" + name + "(){") + 1
    return inst[i:inst.index("\n}\n", i) + 3]
fn = grab("reconstruct_live_orphans")
A_SH = "        /^[ \\t]*AdvancedSecurity[ \\t]*=/ { next }\n"
if P_SH and A_SH not in fn:
    print("  FAIL anchor missing in install-node.sh: " + A_SH.strip() + "\n\n1 FAIL"); sys.exit(1)
if P_SH:
    fn = fn.replace(A_SH, "")
AWGD, WGD, STUB = os.path.join(T, "amneziawg"), os.path.join(T, "wireguard"), os.path.join(T, "stub")
fn = fn.replace("/etc/amnezia/amneziawg", AWGD).replace("/etc/wireguard", WGD)
os.makedirs(STUB)
open(os.path.join(STUB, "awg"), "w").write('#!/bin/sh\ncase "$*" in "show interfaces") echo g1f ;; "showconf g1f") cat "$FIXTURE" ;; *) exit 1 ;; esac\n')
open(os.path.join(STUB, "wg"), "w").write("#!/bin/sh\nexit 0\n")
open(os.path.join(STUB, "ip"), "w").write('#!/bin/sh\ncase "$*" in *route*) echo "default via 192.0.2.1 dev eth0" ;; *addr*) printf "%s" "$IP_ADDR" ;; *) exit 1 ;; esac\n')
for f in ("awg", "wg", "ip"):
    os.chmod(os.path.join(STUB, f), 0o755)
_in = re.search(r"^_in\(\)\{.*$", inst, re.M).group(0) + "\n"          # a one-line function
# the NAT hook writers the function calls (lib/common.sh) — lifted as shipped, like the function itself
_common = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
_a = _common.index("_ipt_reap_sh(){"); _b = _common.index("\n# installed_sum <path…>", _a)
NAT_HOOKS = _common[_a:_b] + "\n"

def sh_rebuild(showconf):
    for d in (AWGD, WGD):
        shutil.rmtree(d, ignore_errors=True)
    fx = os.path.join(T, "fixture")
    open(fx, "w").write(showconf)
    script = ("set -eu\nDRYRUN=false\ninfo(){ :; }\nb(){ printf '%s' \"$*\"; }\n" + _in + NAT_HOOKS + fn
              + "reconstruct_live_orphans\n")
    env = dict(os.environ, PATH=STUB + ":" + os.environ.get("PATH", ""), FIXTURE=fx, IP_ADDR=IP_ADDR,
               SWG_CONVERT="1", ADOPTED_IFACES="g1f")
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    p = os.path.join(AWGD, "g1f.conf")
    return open(p).read() if os.path.exists(p) else "(no conf: rc=%d %s)" % (r.returncode, r.stderr.strip()[:200])

# ── the verdicts ────────────────────────────────────────────────────────────────────────────────────────────────────
lines = lambda t: [l.strip() for l in t.splitlines() if l.strip()]
def has(t, key):
    return [l for l in lines(t) if re.match(r"(?i)" + key + r"\s*=", l)]

def common(tag, out, fixture):
    check(tag + ": no AdvancedSecurity line", not has(out, "AdvancedSecurity"), has(out, "AdvancedSecurity"))
    ifsec = fixture.split("[Peer]")[0]
    keep20 = [l for l in lines(ifsec) if not re.match(r"(?:%s)\s*=" % "|".join(AWG3 + ("HeaderProtectionKey",)), l)]
    miss = [l for l in keep20 if l not in lines(out)]
    check(tag + ": every 2.0 interface line verbatim (I1 with its spaces)", not miss, miss)
    peers = [l for l in lines(PEERS) if not l.startswith(("AdvancedSecurity", "Endpoint"))]
    miss = [l for l in peers if l not in lines(out)]
    check(tag + ": every peer, key and route kept", not miss and lines(out).count("[Peer]") == 3, miss)
    check(tag + ": a learned Endpoint still dropped, a dial-out one still kept", LEARNED not in out and DIALOUT in out)

print("\n[1] noded — a 2.0 interface on a 3.1 kernel")
o20 = noded_rebuild(V20)
common("noded 2.0", o20, V20)
left = [l for k in AWG3 for l in has(o20, k)]
check("noded 2.0: none of the eight zero AWG3 keys", not left, left)
ref = noded_rebuild(V20, strip=False)
want = {l for l in lines(V20) if l.startswith("AdvancedSecurity") or any(l.startswith(k + " ") for k in AWG3)}
check("noded 2.0: exactly those lines removed, nothing else changed (the shipped output minus them, in order)",
      len(want) == 9 and [l for l in lines(ref) if l not in want] == lines(o20),
      {"removed": sorted(set(lines(ref)) - set(lines(o20))), "added": sorted(set(lines(o20)) - set(lines(ref)))})

print("\n[2] ⚠️ CONTROL — noded, a real 3.1 interface being adopted keeps its 3.1 settings")
o31 = noded_rebuild(V31)
common("noded 3.1", o31, V31)
kept = [l for l in lines(IF31) if l.startswith("HeaderProtectionKey") or (any(l.startswith(k + " ") for k in AWG3) and not l.endswith(("= 0", "= off")))]
miss = [l for l in kept if l not in lines(o31)]
check("noded 3.1: HeaderProtectionKey, RandomTrailers = on, padding and timings kept verbatim", len(kept) == 8 and not miss, miss)
check("noded 3.1: DisableCookies = off dropped", not has(o31, "DisableCookies"), has(o31, "DisableCookies"))

print("\n[3] install-node.sh reconstruct_live_orphans — the same two verdicts")
s20, s31 = sh_rebuild(V20), sh_rebuild(V31)
common("sh 2.0", s20, V20)
left = [l for k in AWG3 for l in has(s20, k)]
check("sh 2.0: none of the eight zero AWG3 keys", not left, left)
common("sh 3.1", s31, V31)
miss = [l for l in kept if l not in lines(s31)]
check("sh 3.1: HeaderProtectionKey, RandomTrailers = on, padding and timings kept verbatim", not miss, miss)
check("sh 3.1: DisableCookies = off dropped", not has(s31, "DisableCookies"), has(s31, "DisableCookies"))

print("\n[4] the twins drop the same lines")
for tag, fx, a, b in (("2.0", V20, o20, s20), ("3.1", V31, o31, s31)):
    da = sorted(l for l in lines(fx) if l not in lines(a))
    db = sorted(l for l in lines(fx) if l not in lines(b))
    check(tag + ": noded and install-node.sh drop the same fixture lines", da == db, {"noded": da, "sh": db})

shutil.rmtree(T, ignore_errors=True)
print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
