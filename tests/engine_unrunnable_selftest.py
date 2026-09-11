#!/usr/bin/env python3
"""Self-test — AN ENGINE MUST SAY WHAT IT CANNOT RUN, not just what it built.

Two of the three host engines run exactly ONE pattern kind. Kernel-SNI runs `contains` (xt_string asks only
whether some bytes appear anywhere, which is the whole of what `*google*` means). Force-DNS runs `zone` (a
name is a dnsmasq key; there is no key shape for "contains these letters"). Both limitations are correct and
stay.

What was not correct is that everything else was dropped in SILENCE. The panel accepts `*.ru` on a
Kernel-SNI node, validates it, stores it, plans it, and the node builds that category's nft set and the mark
rule that matches it — and then no engine ever fills that set. The operator is left with a rule the UI draws
as healthy and that routes nothing: the same ending as the patterns-only rule and the tld-* list, twice
shipped under other names.

Every other report on this channel is about what did NOT FIT (`xts_cap`, `sni_cap`) or what DID (`lowered`).
"cannot be expressed here at all" had no reading, so it is `no_lower` — operands, the same unit as
`lowered`, set only when such patterns actually arrived.

⚠️ IP-ONLY IS DELIBERATELY EXEMPT. The dispatch's `else` branch serves Force-DNS AND kernel/IP-only, patterns
survive `_ip_only` upstream on purpose, and the panel hides host health there — so a report would be noise
about a question nobody asked. That exemption is asserted below, not assumed.

Run: python3 tests/engine_unrunnable_selftest.py      (0 = pass)
     --perturb   makes the helper report nothing and expects RED.
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

SRC = open(NODED, encoding="utf-8").read()
_ANCH = '''    if out:
        _SMART_MODE["no_lower"] = out
    else:
        _SMART_MODE.pop("no_lower", None)'''
assert SRC.count(_ANCH) == 1, "anchor missing — this run would FALSE-PASS"
path = NODED
if PERTURB:
    SRC = SRC.replace(_ANCH, '    _SMART_MODE.pop("no_lower", None)')     # the shipped behaviour: say nothing
    _fd, path = tempfile.mkstemp(suffix=".py", prefix="unrunnable-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

l = importlib.machinery.SourceFileLoader("swgnoded", path)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded", l))
l.exec_module(N)
if PERTURB:
    os.unlink(path)

# The bucket a node is handed: the operator's `*.ru` + `*google*`, and the pulled tld-ru zones.
PATS = {"zone":     {"custom_a": ["ru"], "mc:tld-ru": ["moscow", "ru", "su", "tatar"]},
        "contains": {"custom_a": ["google"]},
        "ends":     {"custom_a": ["cdn"]}}

print("[1] Kernel-SNI runs `contains` — everything else must be REPORTED, not dropped in silence")
N._SMART_MODE.pop("no_lower", None)
N._report_unrunnable(PATS, {"contains"})
got = N._SMART_MODE.get("no_lower")
check("it reports something at all (the shipped bug: it did not)", bool(got), got)
check("zones counted as DISTINCT operands across categories (ru is one, not two)",
      (got or {}).get("zone") == 4, got)          # moscow, ru, su, tatar  — custom_a's "ru" merges
check("`ends` reported too", (got or {}).get("ends") == 1, got)
check("`contains` NOT reported — this engine runs it", "contains" not in (got or {}), got)

print("\n[2] Force-DNS runs `zone` — the mirror image")
N._SMART_MODE.pop("no_lower", None)
N._report_unrunnable(PATS, {"zone"})
got = N._SMART_MODE.get("no_lower")
check("`contains` reported here", (got or {}).get("contains") == 1, got)
check("`ends` reported here", (got or {}).get("ends") == 1, got)
check("`zone` NOT reported — this engine runs it", "zone" not in (got or {}), got)

print("\n[3] nothing to say → nothing said (no empty shape for readers to filter)")
N._SMART_MODE["no_lower"] = {"stale": 1}
N._report_unrunnable({"contains": {"c": ["google"]}}, {"contains"})
check("a clean pass clears a stale report", N._SMART_MODE.get("no_lower") is None, N._SMART_MODE.get("no_lower"))
N._report_unrunnable({}, {"zone"})
check("an empty bucket reports nothing", N._SMART_MODE.get("no_lower") is None, N._SMART_MODE.get("no_lower"))

print("\n[4] it is shipped, and it has `lowered`'s lifetime (a teardown must not leave it stale)")
src = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
check("the snapshot carries it", 'base["no_lower"] = _SMART_MODE["no_lower"]' in src)
check("cleared beside `lowered`, once per pass, before an engine is chosen",
      '_SMART_MODE.pop("lowered", None)\n    _SMART_MODE.pop("no_lower", None)' in src)
check("Kernel-SNI declares `contains` runnable", '_report_unrunnable(_pats, {"contains"})' in src)
check("Force-DNS declares `zone` runnable", '_report_unrunnable(_pats, {"zone"})' in src)

print("\n[5] ⚠️ IP-ONLY IS EXEMPT — the same branch serves it, and it must stay quiet")
i = src.index('_report_unrunnable(_pats, {"zone"})')
window = src[max(0, i - 700):i]
check("the Force-DNS call is guarded on the ENGINE, not just on the branch",
      'if host_engine == "dns":' in window, window[-200:])

print("\n[6] the operator is actually told — the panel renders it")
rj = open(os.path.join(ROOT, "js", "routing.js"), encoding="utf-8").read()
check("the SPA reads no_lower", "sr.no_lower" in rj)
check("…and appends it rather than losing it to the else-chain", 'note = note ? note + " · " + s : s;' in rj)
key = "{v1} this engine can't match at all — switch this node's mode, or route them from a node that can"
check("the sentence is a translation key", key in rj)
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("…and it is translated", key in ru)

print("\n[7] ⚠️ AND THE UI MUST NOT CLAIM A REFUSAL THAT DOES NOT EXIST")
# The Kernel-SNI card said whole-ending rules "are refused here rather than shipped broken". Nothing refuses
# them: `cascade_plan` filters patterns for `kernel` (IP-only) and for no other mode, so a `*.ru` on a
# Kernel-SNI node is validated, stored, planned and shipped — the exact outcome the sentence promised could
# not happen. Refusing them in the panel would ALSO be wrong, and the tree says why: "the panel must never
# grow a second copy of an engine's limits, because two copies drift and the node's is the one that decides".
# So the sentence is what was wrong, and `no_lower` is the honest mechanism.
srv = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
check("the plan still filters ONLY for IP-only — no per-engine second-guessing crept in",
      len(re.findall(r'_ip_only = \(\(nodes\.get\(nid\) or \{\}\)\.get\("routing_mode"\) or "kernel"\) == "kernel"', srv)) == 1)
check("nothing refuses a zone operand by routing mode",
      not re.search(r'routing_mode.*==\s*"sni_kernel".*(refus|reject|invalid)', srv))
check("the card no longer claims they are refused", "are refused here rather than shipped broken" not in rj)
check("…and says what actually happens instead", "cannot be matched here at all" in rj)
check("the Russian says the same", "здесь не сопоставляются вовсе" in ru)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
