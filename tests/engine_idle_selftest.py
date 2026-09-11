#!/usr/bin/env python3
"""Self-test: an engine that is idle BY DESIGN must not be reported as down.

Three host-fill engines answer one question — "is the thing that fills my routing sets alive?" — and all
three are stopped on purpose when no interface carries a routed category. Two said so from the day they
were written:

    sni_user     engine_ok = sni_alive or sni_idle        "up, or idle by design (nothing routed)"
    sni_kernel   engine_ok = xts_idle or <chain present>  "torn down on purpose when there is nothing to route"
    dns          engine_ok = dns_alive and route_localnet          <-- no exemption at all

MEASURED on hel-fresh the moment it was switched to Force-DNS, with no smart interface on it yet:

    smartroute: mode=forcedns engine=dns engine_ok=false dnsmasq=false route_localnet=true rules=0 sets={}
    on the node: 0 dnsmasq processes, /proc/sys/net/ipv4/conf/all/route_localnet = 1

and the panel drew `DNS resolver — down — host routing degraded`, in red, on a node behaving exactly as
configured. It is the first thing an operator sees after picking the mode and before assigning a category —
the same complaint `sni_idle`'s own comment describes, in the one engine that fix did not reach.

⚠️ `route_localnet` KEEPS ITS UNCONDITIONAL CHECK. A box that cannot DNAT to loopback can never do
Force-DNS at all; that is a real fact about the box and worth saying before anything is routed. Only the
absent-process half is exempted.

Run: python3 tests/engine_idle_selftest.py       (0 = pass)
     --perturb  removes the dns exemption, the way it shipped, and expects RED.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
EXEMPT = 'engine_ok = (dns_alive or bool(_SMART_MODE.get("dns_idle"))) and _route_localnet_ok()'
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert EXEMPT in src, "anchor missing — this run would FALSE-PASS"
if PERTURB:
    src = src.replace(EXEMPT, "engine_ok = dns_alive and _route_localnet_ok()")

print("[1] every host-fill engine treats 'stopped because there is nothing to fill' the same way")
# Derived from the source: the engine_ok ladder, one arm per engine.
ladder = re.search(r"if engine == \"sni_user\":[\s\S]*?else:\s*engine_ok = True", src)
check("the engine_ok ladder was found", bool(ladder), "it moved — this gate is blind")
if ladder:
    arms = ladder.group(0)
    for eng, flag in (("sni_user", "sni_idle"), ("sni_kernel", "xts_idle"), ("dns", "dns_idle")):
        check("`%s` exempts itself when idle (`%s`)" % (eng, flag), flag in arms, arms)

print("\n[2] …and every one of those flags is actually SET by the code that stops the engine")
for flag, fn in (("sni_idle", "_SMART_MODE[\"sni_idle\"]"), ("xts_idle", "_SMART_MODE[\"xts_idle\"]"),
                 ("dns_idle", "_SMART_MODE[\"dns_idle\"]")):
    check("`%s` is written, not merely read" % flag, fn in src,
          "an exemption keyed on a flag nobody sets is an exemption that never fires")
# …and set from the SAME question each engine already asks itself, not a second one that can disagree.
m = re.search(r'want = bool\(\(domains or zones\) and subnets\)\s*\n(?:\s*#[^\n]*\n)*\s*_SMART_MODE\["dns_idle"\] = not want', src)
check("⚠️ `dns_idle` is `not want` — the same `want` that decides whether dnsmasq runs at all", bool(m),
      "a second reading of 'is there anything to fill' can disagree with the one that acts on it")

print("\n[3] ⚠️ …and the flag is set somewhere the idle pass can actually REACH")
# ⚠️ THE HALF THE FIRST VERSION OF THIS GATE MISSED. `dns_idle` was added inside `_ensure_smart_dnsmasq`,
# whose call site is guarded by four conditions that are ALL false on exactly the node this is about — one
# just switched to Force-DNS with nothing routed. The flag was written in a function the pass skipped, the
# gate went green on source it could see, and the live node still read `engine_ok: false`. The engine's own
# name has to be in that guard, or the exemption is unreachable. [[lesson-gate-never-ran]]
_call = re.search(r"^\s*if ([^\n]*?):\n\s*_ensure_smart_dnsmasq\(domains, smart_e", src, re.M)
check("the dnsmasq call site was found", bool(_call), "it moved — this gate is blind")
if _call:
    check("⚠️ …and a Force-DNS node reaches it even with nothing to route",
          'host_engine == "dns"' in _call.group(1), _call.group(1))
    check("…while IP-only still does not, so an idle kernel node pays nothing for this",
          "smart_e or domains" in _call.group(1), _call.group(1))

print("\n[4] ⚠️ …and the capability check is NOT exempted — it is a fact about the box, not about load")
if ladder:
    dns_arm = [l for l in ladder.group(0).splitlines() if 'engine == "dns"' in l]
    check("the dns arm still requires route_localnet", bool(dns_arm) and "_route_localnet_ok()" in dns_arm[0],
          dns_arm[0] if dns_arm else "")
    check("…and it is ANDed, so idleness cannot mask it",
          bool(dns_arm) and re.search(r"\)\s*and _route_localnet_ok\(\)", dns_arm[0]) is not None,
          dns_arm[0] if dns_arm else "")

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: an idle resolver reads as down again" % len(FAILS)) if ok
          else "PERTURB FAILED — the exemption was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
